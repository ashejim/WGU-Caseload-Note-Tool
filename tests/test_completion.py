"""Tests for the completion-by-month chart data (history.completion_by_month)
and the WGU Momentum-band predicted rate (momentum_band_rate), on a temp DB.
The 'predicted' line is the indicator's own band midpoint — NOT a trained model.
"""
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import history  # noqa: E402

_NOW = __import__("datetime").datetime(2026, 6, 15)


def _seed(rows):
    """Temp history DB from outcome rows. Each row:
    (course, outcome, entry_rank, exit_rank, start, pass_date, term_end)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    conn = history._connect(path)
    for i, (course, outcome, er, xr, start, passd, term) in enumerate(rows):
        conn.execute(
            "INSERT INTO outcomes (student_id, course_code, outcome, "
            "entry_momentum_rank, momentum_rank_at_outcome, course_start_date, "
            "pass_date, term_end_date) VALUES (?,?,?,?,?,?,?,?)",
            (str(i), course, outcome, er, xr, start, passd, term))
    conn.commit()
    conn.close()
    return path


def test_momentum_band_rate_midpoints():
    # WGU bands: Low 0-20 -> .10 ... High 80-100 -> .90.
    for rank, want in [(1, .10), (2, .30), (3, .50), (4, .70), (5, .90)]:
        assert abs(history.momentum_band_rate(rank) - want) < 1e-9, rank
    assert history.momentum_band_rate(None) is None
    assert history.momentum_band_rate(9) is None


def test_momentum_band_bounds():
    assert history.momentum_band_bounds(1) == (0.0, 0.2)     # Low
    assert history.momentum_band_bounds(5) == (0.8, 1.0)     # High
    assert history.momentum_band_bounds(None) == (None, None)


def test_predicted_band_and_midpoint_entry():
    # Two entrants: High (.8-1.0) + Low (.0-.2). Mean low=.4, high=.6, mid=.5.
    rows = [
        ("X", "passed", 5, 5, "2026-01-10", "2026-02-01", None),
        ("X", "passed", 1, 1, "2026-01-10", "2026-02-01", None),
    ]
    p = _seed(rows)
    try:
        d = history.completion_by_month(by="start", basis="entry", db_path=p,
                                        now=_NOW)
        jan = [m for m in d["months"] if m["month"] == "2026-01"][0]
        assert abs(jan["predicted_low"] - 0.40) < 1e-9, jan
        assert abs(jan["predicted_high"] - 0.60) < 1e-9, jan
        assert abs(jan["predicted_rate"] - 0.50) < 1e-9, jan
        assert jan["actual_rate"] == 1.0            # both passed
    finally:
        os.unlink(p)


def test_entry_vs_exit_basis_differ():
    # Entry High (.90) but exit Low (.10) — the two bases give different lines.
    rows = [("X", "passed", 5, 1, "2026-01-10", "2026-02-01", None)]
    p = _seed(rows)
    try:
        de = history.completion_by_month(basis="entry", db_path=p, now=_NOW)
        dx = history.completion_by_month(basis="exit", db_path=p, now=_NOW)
        assert de["months"][0]["predicted_rate"] == 0.90
        assert dx["months"][0]["predicted_rate"] == 0.10
    finally:
        os.unlink(p)


def test_actual_counts_resolved_only():
    # Jan cohort: 1 passed (resolved), 1 in-progress (future term, unresolved).
    rows = [
        ("X", "passed", 5, 5, "2026-01-10", "2026-02-01", None),
        ("X", "not_passed", 1, 1, "2026-01-10", None, "2026-12-31"),
    ]
    p = _seed(rows)
    try:
        d = history.completion_by_month(by="start", db_path=p, now=_NOW)
        jan = d["months"][0]
        assert jan["total"] == 2 and jan["resolved"] == 1
        assert jan["actual_rate"] == 1.0            # 1 passed of 1 resolved
        # predicted averages BOTH students' entry bands: (.90 + .10)/2 = .50
        assert abs(jan["predicted_rate"] - 0.50) < 1e-9
    finally:
        os.unlink(p)


def test_by_resolution_and_course_filter():
    rows = [
        ("A", "passed", 5, 5, "2026-01-10", "2026-02-05", None),
        ("B", "passed", 5, 5, "2026-01-10", "2026-02-05", None),
    ]
    p = _seed(rows)
    try:
        d = history.completion_by_month(by="resolution", courses={"A"},
                                        db_path=p, now=_NOW)
        assert [m["month"] for m in d["months"]] == ["2026-02"]
        assert sum(m["total"] for m in d["months"]) == 1
    finally:
        os.unlink(p)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok  {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
