"""Tests for the momentum-trajectory risk model (history.momentum_risk_students
/ momentum_risk_calibration / _isotonic_noninc).

Run: python tests/test_momentum_risk.py
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import history  # noqa: E402

NOW = datetime(2026, 8, 2, 12, 0, 0)
PAST = "2026-05-01"      # ~13 weeks before NOW → underway


def _tmp_db():
    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(p)
    return p


def _snap(conn, sid, rank, day, *, course="C769", attempted="", start=PAST,
          status="Registered"):
    """One momentum snapshot for a student on a given day."""
    ej = {"CourseStartDate": start, "CourseStatus": status,
          "TermDaysLeft": "60", "DaysSinceLastCourseContact": "5",
          "StudentEmail": "s@wgu.edu", "TextingPreference": "Opted In"}
    momentum = {1: "Low", 2: "Med Low", 3: "Med", 4: "Med High", 5: "High"}[rank]
    conn.execute("INSERT OR IGNORE INTO collections (collected_at, "
                 "collected_date, bucket, row_count) VALUES (?, ?, ?, 1)",
                 (f"{day}T09:00:00", day, day))
    conn.execute(
        "INSERT OR REPLACE INTO snapshots (collected_at, collected_date, "
        "student_id, course_code, name, momentum, momentum_rank, "
        "latest_task_status, extra_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (f"{day}T09:00:00", day, sid, course, f"S{sid}", momentum, rank,
         attempted, json.dumps(ej)))


def _outcome(conn, sid, outcome, ranks, course="C769"):
    """A resolved student with a momentum history (for calibration)."""
    for i, rk in enumerate(ranks):
        _snap(conn, sid, rk, f"2026-06-{10+i:02d}", course=course)
    conn.execute("INSERT INTO outcomes (student_id, course_code, outcome) "
                 "VALUES (?, ?, ?)", (sid, course, outcome))


def _build(seed):
    db = _tmp_db()
    conn = history._connect(db)
    try:
        with conn:
            seed(conn)
    finally:
        conn.close()
    return db


# ---- PAVA monotonic smoothing -------------------------------------------

def test_isotonic_enforces_noninc():
    # raw rates 0.32, 0.13, 0.17, 0.03, 0.005 — the 0.13<0.17 is a violation
    counts = [(32, 100), (13, 100), (17, 100), (3, 100), (1, 200)]
    prob = history._isotonic_noninc(counts)
    assert all(prob[i] >= prob[i + 1] - 1e-9 for i in range(len(prob) - 1)), prob
    # the two violators pool to (13+17)/(200) = 0.15
    assert abs(prob[1] - 0.15) < 1e-9 and abs(prob[2] - 0.15) < 1e-9, prob


# ---- calibration ---------------------------------------------------------

def test_calibration_low_riskier_than_high():
    def seed(c):
        # low-momentum resolvers mostly fail; high-momentum mostly pass
        for i in range(8):
            _outcome(c, f"L{i}", "not_passed" if i < 6 else "passed", [1, 1, 1])
        for i in range(8):
            _outcome(c, f"H{i}", "passed", [5, 5, 5])
    db = _build(seed)
    try:
        cal = history.momentum_risk_calibration(db_path=db)
        low = cal["prob"][history._avg_rank_bucket_idx(1.0)]
        high = cal["prob"][history._avg_rank_bucket_idx(5.0)]
        assert low > high, (low, high)
        assert low > 0.5 and high < 0.1, (low, high)
    finally:
        os.unlink(db)


# ---- ranking of live students -------------------------------------------

def test_interp_risk_continuous_and_monotonic():
    rates = [0.32, 0.16, 0.16, 0.03, 0.005]
    # clamp past the end anchors
    assert history._interp_risk(1.0, rates) == 0.32
    assert history._interp_risk(5.0, rates) == 0.005
    # a mid avg-rank lands STRICTLY between bucket rates (fills the gap)
    mid = history._interp_risk(1.5, rates)
    assert 0.16 < mid < 0.32, mid
    # non-increasing across the whole range
    ys = [history._interp_risk(x, rates)
          for x in (1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0)]
    assert all(ys[i] >= ys[i + 1] - 1e-9 for i in range(len(ys) - 1)), ys


def test_ranks_by_risk_and_excludes_resolved():
    def seed(c):
        # calibration set
        for i in range(6):
            _outcome(c, f"L{i}", "not_passed", [1, 1, 1])
        for i in range(6):
            _outcome(c, f"H{i}", "passed", [5, 5, 5])
        # live in-progress students on the LATEST collection day
        for d in ("2026-08-01", "2026-08-02"):
            _snap(c, "stuck", 1, d)         # consistently Low → high risk
            _snap(c, "strong", 5, d)        # consistently High → low risk
        # a resolved student must be excluded even if currently listed
        _snap(c, "done", 1, "2026-08-02")
        c.execute("INSERT INTO outcomes (student_id, course_code, outcome) "
                  "VALUES ('done','C769','passed')")
    db = _build(seed)
    try:
        rows = history.momentum_risk_students(db_path=db, now=NOW)
        ids = [r["student_id"] for r in rows]
        assert "done" not in ids, ids
        assert set(ids) == {"stuck", "strong"}, ids
        assert ids[0] == "stuck", ids            # highest risk first
        assert rows[0]["risk"] > rows[1]["risk"]
        assert rows[0]["avg_momentum_rank"] == 1.0
    finally:
        os.unlink(db)


def test_trend_detects_recovery():
    def seed(c):
        for i in range(6):
            _outcome(c, f"L{i}", "not_passed", [1, 1, 1])
        for i in range(6):
            _outcome(c, f"H{i}", "passed", [5, 5, 5])
        # a climber: Low early, High lately
        for i, rk in enumerate([1, 1, 1, 4, 5, 5]):
            _snap(c, "climber", rk, f"2026-07-{20+i:02d}")
    db = _build(seed)
    try:
        rows = history.momentum_risk_students(db_path=db, now=NOW)
        r = next(x for x in rows if x["student_id"] == "climber")
        assert r["trend"] > 0, r["trend"]        # recovering
    finally:
        os.unlink(db)


def test_window_limits_readings():
    def seed(c):
        for i in range(6):
            _outcome(c, f"L{i}", "not_passed", [1, 1, 1])
        for i in range(6):
            _outcome(c, f"H{i}", "passed", [5, 5, 5])
        # 6 weeks of readings for one live student
        for i in range(6):
            _snap(c, "s", 1, f"2026-06-{22+i:02d}")   # older
        for i in range(4):
            _snap(c, "s", 1, f"2026-07-{27+i:02d}")   # recent (within 4wk of NOW)
    db = _build(seed)
    try:
        allh = history.momentum_risk_students(db_path=db, now=NOW)
        wk4 = history.momentum_risk_students(db_path=db, now=NOW, window_weeks=4)
        ra = next(x for x in allh if x["student_id"] == "s")["readings"]
        rw = next(x for x in wk4 if x["student_id"] == "s")["readings"]
        assert rw < ra, (rw, ra)                 # window trims older readings
    finally:
        os.unlink(db)


# ---- §17 validated-signal flags (_signal_flags) --------------------------

def _row(**kw):
    base = dict(risk=0.02, never_attempted=False, ever_responded=True,
                days_into_course=100, days_since_contact=5)
    base.update(kw)
    return base


def test_signal_fresh_never_attempted_not_flagged():
    # never attempted but only 3 weeks in → benign (§12 time-weighting)
    f = history._signal_flags(_row(never_attempted=True, days_into_course=21))
    assert not f["never_attempted_stalled"] and not f["signal_flagged"]
    assert f["priority"] == 0.02          # unchanged risk


def test_signal_stalled_never_attempted_flagged_and_floored():
    f = history._signal_flags(_row(never_attempted=True, days_into_course=60,
                                   risk=0.005))
    assert f["never_attempted_stalled"] and f["signal_flagged"]
    assert f["signal_flag"] == "stalled"
    assert f["priority"] == history._SIGNAL_PRIORITY_FLOOR   # floored up


def test_signal_silent_requires_contacted_enrolled_noreply_AND_risky():
    # §18: silence only bites when momentum is ALREADY risky (>=8%).
    # risky + enrolled + contacted + never replied → silent
    assert history._signal_flags(
        _row(ever_responded=False, risk=0.15))["gone_silent"]
    # momentum-SAFE + silent → NOT flagged (they pass ~98%)
    assert not history._signal_flags(
        _row(ever_responded=False, risk=0.02))["gone_silent"]
    # replied → not silent
    assert not history._signal_flags(
        _row(ever_responded=True, risk=0.15))["gone_silent"]
    # never contacted (no last-contact age) → not silent
    assert not history._signal_flags(
        _row(ever_responded=False, risk=0.15, days_since_contact=None))["gone_silent"]
    # fresh (<6wk) → not silent even if risky + never replied
    assert not history._signal_flags(
        _row(ever_responded=False, risk=0.15, days_into_course=20))["gone_silent"]


def test_signal_silent_amplifies_risky_to_top():
    # a risky+silent student is floored to the amplify level (ranks above the
    # ~29% momentum ceiling — §18 says risky+silent ≈ 53% not-pass)
    f = history._signal_flags(_row(ever_responded=False, risk=0.12))
    assert f["gone_silent"] and f["priority"] == history._SILENT_AMPLIFY_FLOOR


def test_signal_both_flags_combine():
    # risky so silence fires too; never-attempted so stalled fires
    f = history._signal_flags(_row(never_attempted=True, ever_responded=False,
                                   days_into_course=90, risk=0.15))
    assert f["signal_flag"] == "stalled+silent" and f["signal_flagged"]
    assert f["priority"] == history._SILENT_AMPLIFY_FLOOR


def test_signal_safe_never_attempted_still_floored():
    # never-attempted stands alone at ANY momentum (§12) — floored even when safe
    f = history._signal_flags(_row(never_attempted=True, days_into_course=90,
                                   risk=0.005, ever_responded=True))
    assert f["signal_flag"] == "stalled"
    assert f["priority"] == history._SIGNAL_PRIORITY_FLOOR


def test_signal_high_risk_keeps_its_risk_as_priority():
    # a stalled student already above the 0.08 floor (but not silent) keeps risk
    f = history._signal_flags(_row(never_attempted=True, days_into_course=90,
                                   risk=0.25, ever_responded=True))
    assert f["priority"] == 0.25


def test_signal_unflagged_priority_is_risk():
    f = history._signal_flags(_row(risk=0.13))
    assert not f["signal_flagged"] and f["priority"] == 0.13


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok  {t.__name__}")
        except Exception as e:  # noqa: BLE001
            import traceback
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
