"""Tests for history.at_risk_students() — the 4-gate stuck-low filter.

Each gate (never-recovered / task-not-passed / course-underway / no-other-course)
must exclude the false positives it was designed to remove (data_analysis/
FINDINGS.md §5). A single genuinely-stuck student must survive all four.

Run: python tests/test_at_risk_gates.py
"""
import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import history  # noqa: E402

NOW = datetime(2026, 8, 2, 12, 0, 0)
PAST_START = "2026-05-01"     # underway
FUTURE_START = "2026-10-01"   # not started yet


def _tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    return path


def _insert(conn, day, sid, course, rank, *, task="", start=PAST_START,
            others="", name="Test Student", status="Registered"):
    ej = {"CourseStartDate": start, "OtherCourses": others,
          "DaysSinceLastCourseContact": "3", "TermDaysLeft": "20",
          "CourseStatus": status, "Icenddate": ""}
    conn.execute(
        "INSERT INTO collections (collected_at, collected_date, bucket, "
        "row_count) VALUES (?, ?, ?, 1)", (f"{day}T09:00:00", day, day))
    conn.execute(
        "INSERT INTO snapshots (collected_at, collected_date, student_id, "
        "course_code, name, momentum, momentum_rank, latest_task_status, "
        "extra_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (f"{day}T09:00:00", day, sid, course, name, "Low", rank, task,
         json.dumps(ej)))


def _build(specs):
    """specs: list of (sid, [(day, rank, kwargs), ...]). Returns db path."""
    db = _tmp_db()
    conn = sqlite3.connect(db)
    history._init_schema(conn) if hasattr(history, "_init_schema") else None
    conn.close()
    # _connect runs schema init; use it.
    conn = history._connect(db)
    try:
        with conn:
            for sid, course, hist in specs:
                for day, rank, kw in hist:
                    _insert(conn, day, sid, course, rank, **kw)
    finally:
        conn.close()
    return db


def _ids(rows):
    return {r["student_id"] for r in rows}


def test_genuinely_stuck_student_survives_all_gates():
    db = _build([
        ("111", "C769", [("2026-07-01", 1, {}), ("2026-08-02", 1, {})]),
    ])
    try:
        rows = history.at_risk_students(db_path=db, now=NOW)
        assert _ids(rows) == {"111"}, _ids(rows)
        r = rows[0]
        assert r["trend"] == "▬" and r["entry_rank"] == 1 and r["max_rank"] == 1
        assert r["days_into_course"] > 0
    finally:
        os.unlink(db)


def test_gate1_recovered_is_excluded():
    # Was Med (rank 3) at some point -> recovered -> not the risk, even if Low now.
    db = _build([
        ("111", "C769", [("2026-07-01", 3, {}), ("2026-08-02", 1, {})]),
    ])
    try:
        assert _ids(history.at_risk_students(db_path=db, now=NOW)) == set()
        # strict=False keeps it (legacy behaviour)
        assert _ids(history.at_risk_students(db_path=db, now=NOW, strict=False)) == {"111"}
    finally:
        os.unlink(db)


def test_gate2_task_passed_is_excluded():
    db = _build([
        ("111", "C769", [("2026-07-01", 1, {"task": "Passed"}),
                         ("2026-08-02", 1, {"task": "Passed"})]),
    ])
    try:
        assert _ids(history.at_risk_students(db_path=db, now=NOW)) == set()
    finally:
        os.unlink(db)


def test_gate3_not_started_is_excluded():
    db = _build([
        ("111", "C769", [("2026-08-02", 1, {"start": FUTURE_START})]),
    ])
    try:
        assert _ids(history.at_risk_students(db_path=db, now=NOW)) == set()
    finally:
        os.unlink(db)


def test_gate3_planned_status_is_excluded():
    # Start date is in the PAST but the course is still 'Planned' (not begun) —
    # a low reading is meaningless, so it must be excluded.
    db = _build([
        ("111", "C769", [("2026-07-01", 1, {"status": "Planned"}),
                         ("2026-08-02", 1, {"status": "Planned"})]),
    ])
    try:
        assert _ids(history.at_risk_students(db_path=db, now=NOW)) == set()
    finally:
        os.unlink(db)


def test_gate4_juggling_other_courses_is_excluded():
    db = _build([
        ("111", "C769", [("2026-07-01", 1, {"others": "D329, C769"}),
                         ("2026-08-02", 1, {"others": "D329, C769"})]),
    ])
    try:
        assert _ids(history.at_risk_students(db_path=db, now=NOW)) == set()
    finally:
        os.unlink(db)


def test_resolved_student_excluded():
    db = _build([
        ("111", "C769", [("2026-07-01", 1, {}), ("2026-08-02", 1, {})]),
    ])
    try:
        conn = history._connect(db)
        with conn:
            conn.execute("INSERT INTO outcomes (student_id, course_code, "
                         "outcome) VALUES ('111', 'C769', 'passed')")
        conn.close()
        assert _ids(history.at_risk_students(db_path=db, now=NOW)) == set()
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
