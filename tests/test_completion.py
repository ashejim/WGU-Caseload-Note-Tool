"""Tests for the completion-by-month chart data + momentum estimator model
(history.momentum_completion_model / completion_by_month), on a temp DB.
"""
import os
import sqlite3
import sys
import tempfile
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import history  # noqa: E402

# A fixed "today" so resolution/window logic is deterministic.
_NOW = __import__("datetime").datetime(2026, 6, 15)


def _seed(rows):
    """Make a temp history DB with the given outcome rows and return its path.
    Each row: (course, outcome, entry_rank, start, pass_date, term_end)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    conn = history._connect(path)   # creates schema
    for i, (course, outcome, rank, start, passd, term) in enumerate(rows):
        conn.execute(
            "INSERT INTO outcomes (student_id, course_code, outcome, "
            "entry_momentum_rank, course_start_date, pass_date, term_end_date) "
            "VALUES (?,?,?,?,?,?,?)",
            (str(i), course, outcome, rank, start, passd, term))
    conn.commit()
    conn.close()
    return path


def test_model_rates_by_rank_with_fallback():
    # rank 5: 4 passed / 5 resolved = .8 (>= min_n won't trigger at min_n=2);
    # rank 1: 1 sample → below min_n=2 → falls back to overall.
    rows = [
        ("X", "passed", 5, "2026-01-01", "2026-02-01", None),
        ("X", "passed", 5, "2026-01-01", "2026-02-01", None),
        ("X", "passed", 5, "2026-01-01", "2026-02-01", None),
        ("X", "passed", 5, "2026-01-01", "2026-02-01", None),
        ("X", "not_passed", 5, "2026-01-01", None, "2026-03-01"),
        ("X", "not_passed", 1, "2026-01-01", None, "2026-03-01"),
    ]
    p = _seed(rows)
    try:
        m = history.momentum_completion_model(db_path=p, min_n=2, now=_NOW)
        assert abs(m[5] - 0.8) < 1e-9, m               # 4 passed / 5 resolved
        assert abs(m[None] - 4 / 6) < 1e-9, m          # 4 passed of 6 resolved
        assert m[1] == m[None]                          # rank 1 too sparse → fallback
    finally:
        os.unlink(p)


def test_model_excludes_unresolved():
    # A not_passed whose term end is in the FUTURE isn't resolved → excluded.
    rows = [
        ("X", "passed", 5, "2026-01-01", "2026-02-01", None),
        ("X", "not_passed", 5, "2026-01-01", None, "2026-12-31"),  # future term
    ]
    p = _seed(rows)
    try:
        m = history.momentum_completion_model(db_path=p, min_n=1, now=_NOW)
        assert m[None] == 1.0            # only the resolved pass counts
    finally:
        os.unlink(p)


def test_completion_by_start_projects_inprogress():
    # A Jan cohort: 1 passed (resolved), 1 in-progress (future term).
    rows = [
        ("X", "passed", 5, "2026-01-10", "2026-02-01", None),
        ("X", "not_passed", 5, "2026-01-10", None, "2026-12-31"),  # in progress
    ]
    p = _seed(rows)
    try:
        d = history.completion_by_month(by="start", db_path=p, now=_NOW)
        jan = [m for m in d["months"] if m["month"] == "2026-01"][0]
        assert jan["total"] == 2 and jan["resolved"] == 1 and jan["passed"] == 1
        assert jan["actual_rate"] == 1.0        # 1 passed of 1 resolved
        assert jan["est_rate"] is not None      # projects both students
    finally:
        os.unlink(p)


def test_completion_by_resolution_only_resolved():
    rows = [
        ("X", "passed", 5, "2026-01-10", "2026-02-05", None),      # resolves Feb
        ("X", "not_passed", 5, "2026-01-10", None, "2026-12-31"),  # unresolved
    ]
    p = _seed(rows)
    try:
        d = history.completion_by_month(by="resolution", db_path=p, now=_NOW)
        assert [m["month"] for m in d["months"]] == ["2026-02"]
        feb = d["months"][0]
        assert feb["total"] == 1 and feb["actual_rate"] == 1.0
    finally:
        os.unlink(p)


def test_course_filter():
    rows = [
        ("A", "passed", 5, "2026-01-10", "2026-02-01", None),
        ("B", "passed", 5, "2026-01-10", "2026-02-01", None),
    ]
    p = _seed(rows)
    try:
        d = history.completion_by_month(by="start", courses={"A"}, db_path=p,
                                        now=_NOW)
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
