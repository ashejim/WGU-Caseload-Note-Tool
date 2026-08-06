"""Tests for the persistent chase-list worklist (history.sync_chase_list /
set_chase_status / chase_worklist).

at_risk_students() recomputes the chase list live; the worklist layer remembers
who is on it and since when, when they dropped off, and the instructor's manual
status (contacted / dismissed).

Run: python tests/test_chase_worklist.py
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


def _snap(conn, sid, course="C769", *, attempted="", start=PAST, weeks=10,
          status="Registered", day="2026-08-02"):
    ej = {"CourseStartDate": start, "CourseStatus": status,
          "weeksincourse": str(weeks), "TermDaysLeft": "20",
          "DaysSinceLastCourseContact": "12", "StudentEmail": "s@wgu.edu",
          "TextingPreference": "Opted In"}
    conn.execute("INSERT OR IGNORE INTO collections (collected_at, "
                 "collected_date, bucket, row_count) VALUES (?, ?, ?, 1)",
                 (f"{day}T09:00:00", day, day))
    conn.execute(
        "INSERT INTO snapshots (collected_at, collected_date, student_id, "
        "course_code, name, momentum, momentum_rank, latest_task_status, "
        "extra_json) VALUES (?, ?, ?, ?, ?, 'Low', 1, ?, ?)",
        (f"{day}T09:00:00", day, sid, course, "Test Student", attempted,
         json.dumps(ej)))


def _build(seed):
    db = _tmp_db()
    conn = history._connect(db)
    try:
        with conn:
            seed(conn)
    finally:
        conn.close()
    return db


def _ids(rows):
    return {r["student_id"] for r in rows}


def _row(db, sid, course="C769"):
    conn = history._connect(db)
    try:
        return conn.execute("SELECT * FROM chase_list WHERE student_id = ? AND "
                            "course_code = ?", (sid, course)).fetchone()
    finally:
        conn.close()


def test_sync_records_membership():
    db = _build(lambda c: _snap(c, "111"))
    try:
        rows = history.sync_chase_list(db_path=db, now=NOW)
        assert _ids(rows) == {"111"}, _ids(rows)
        r = rows[0]
        assert r["days_on_list"] == 0 and r["chase_status"] == ""
        assert r["first_listed_at"].startswith("2026-08-02")
        persisted = _row(db, "111")
        assert persisted is not None and persisted["resolved_at"] is None
    finally:
        os.unlink(db)


def test_first_listed_stable_across_syncs():
    db = _build(lambda c: _snap(c, "111"))
    try:
        history.sync_chase_list(db_path=db, now=NOW)
        later = NOW + timedelta(days=3)
        rows = history.sync_chase_list(db_path=db, now=later)
        r = rows[0]
        assert r["first_listed_at"].startswith("2026-08-02")   # unchanged
        assert r["days_on_list"] == 3
        assert _row(db, "111")["last_listed_at"].startswith("2026-08-05")
    finally:
        os.unlink(db)


def test_dropoff_sets_resolved():
    db = _build(lambda c: _snap(c, "111"))
    try:
        history.sync_chase_list(db_path=db, now=NOW)
        # student resolves (passes) → drops off the live list
        conn = history._connect(db)
        with conn:
            conn.execute("INSERT INTO outcomes (student_id, course_code, "
                         "outcome) VALUES ('111','C769','passed')")
        conn.close()
        later = NOW + timedelta(days=1)
        rows = history.sync_chase_list(db_path=db, now=later)
        assert _ids(rows) == set()                       # gone from live
        assert _row(db, "111")["resolved_at"].startswith("2026-08-03")
    finally:
        os.unlink(db)


def test_dismiss_hides_from_worklist():
    db = _build(lambda c: _snap(c, "111"))
    try:
        history.sync_chase_list(db_path=db, now=NOW)
        history.set_chase_status("111", "C769", "dismissed", db_path=db, now=NOW)
        assert _ids(history.chase_worklist(db_path=db, now=NOW)) == set()
        shown = history.chase_worklist(db_path=db, now=NOW,
                                       include_dismissed=True)
        assert _ids(shown) == {"111"}
        assert shown[0]["chase_status"] == "dismissed"
    finally:
        os.unlink(db)


def test_dismiss_persists_across_sync():
    db = _build(lambda c: _snap(c, "111"))
    try:
        history.sync_chase_list(db_path=db, now=NOW)
        history.set_chase_status("111", "C769", "dismissed", db_path=db, now=NOW)
        # a later sync while still qualifying must NOT revive them
        later = NOW + timedelta(days=2)
        assert _ids(history.chase_worklist(db_path=db, now=later)) == set()
        assert _row(db, "111")["status"] == "dismissed"
    finally:
        os.unlink(db)


def test_contacted_stays_active():
    db = _build(lambda c: _snap(c, "111"))
    try:
        history.sync_chase_list(db_path=db, now=NOW)
        history.set_chase_status("111", "C769", "contacted", db_path=db, now=NOW)
        rows = history.chase_worklist(db_path=db, now=NOW)
        assert _ids(rows) == {"111"}
        assert rows[0]["chase_status"] == "contacted"
    finally:
        os.unlink(db)


def test_clear_status():
    db = _build(lambda c: _snap(c, "111"))
    try:
        history.sync_chase_list(db_path=db, now=NOW)
        history.set_chase_status("111", "C769", "dismissed", db_path=db, now=NOW)
        history.set_chase_status("111", "C769", "", db_path=db, now=NOW)
        rows = history.chase_worklist(db_path=db, now=NOW)
        assert _ids(rows) == {"111"} and rows[0]["chase_status"] == ""
    finally:
        os.unlink(db)


def test_invalid_status_rejected():
    db = _build(lambda c: _snap(c, "111"))
    try:
        try:
            history.set_chase_status("111", "C769", "bogus", db_path=db)
        except ValueError:
            return
        raise AssertionError("expected ValueError for bogus status")
    finally:
        os.unlink(db)


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
