"""Tests for history.at_risk_students() — the CHASE LIST (FINDINGS §12/§15).

The list surfaces reachable students who most need a nudge to attempt and aren't
getting one: course underway, NEVER attempted a task, enrolled >= min_weeks, not
resolved. Each row carries reachability + suggested channel + contact preference.

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
PAST = "2026-05-01"      # ~13 weeks before NOW → underway
FUTURE = "2026-10-01"


def _tmp_db():
    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(p)
    return p


def _snap(conn, sid, course="C769", *, attempted="", start=PAST, weeks=10,
          status="Registered", opted_in=True, email="s@wgu.edu",
          name="Test Student", day="2026-08-02"):
    ej = {"CourseStartDate": start, "CourseStatus": status,
          "weeksincourse": str(weeks), "TermDaysLeft": "20",
          "DaysSinceLastCourseContact": "12", "StudentEmail": email,
          "TextingPreference": "Opted In" if opted_in else "Not Opted In"}
    conn.execute("INSERT OR IGNORE INTO collections (collected_at, "
                 "collected_date, bucket, row_count) VALUES (?, ?, ?, 1)",
                 (f"{day}T09:00:00", day, day))
    conn.execute(
        "INSERT INTO snapshots (collected_at, collected_date, student_id, "
        "course_code, name, momentum, momentum_rank, latest_task_status, "
        "extra_json) VALUES (?, ?, ?, ?, ?, 'Low', 1, ?, ?)",
        (f"{day}T09:00:00", day, sid, course, name, attempted, json.dumps(ej)))


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


def test_includes_stalled_nonattempter():
    db = _build(lambda c: _snap(c, "111"))
    try:
        rows = history.at_risk_students(db_path=db, now=NOW)
        assert _ids(rows) == {"111"}, _ids(rows)
        r = rows[0]
        assert r["reachable"] == "text+email"
        assert r["suggested_channel"] == "text"   # opted-in, no known pref → text
        assert r["weeks_enrolled"] == 10 and r["ever_responded"] is False
    finally:
        os.unlink(db)


def test_excludes_attempter():
    db = _build(lambda c: _snap(c, "111", attempted="Task Submitted"))
    try:
        assert _ids(history.at_risk_students(db_path=db, now=NOW)) == set()
    finally:
        os.unlink(db)


def test_excludes_fresh_enrollee():
    db = _build(lambda c: _snap(c, "111", weeks=3))   # < min_weeks
    try:
        assert _ids(history.at_risk_students(db_path=db, now=NOW)) == set()
    finally:
        os.unlink(db)


def test_excludes_planned_and_future_start():
    db = _build(lambda c: (_snap(c, "111", status="Planned"),
                           _snap(c, "222", start=FUTURE, weeks=0)))
    try:
        assert _ids(history.at_risk_students(db_path=db, now=NOW)) == set()
    finally:
        os.unlink(db)


def test_excludes_resolved():
    def seed(c):
        _snap(c, "111")
        c.execute("INSERT INTO outcomes (student_id, course_code, outcome) "
                  "VALUES ('111','C769','passed')")
    db = _build(seed)
    try:
        assert _ids(history.at_risk_students(db_path=db, now=NOW)) == set()
    finally:
        os.unlink(db)


def test_not_opted_in_suggests_email():
    db = _build(lambda c: _snap(c, "111", opted_in=False))
    try:
        r = history.at_risk_students(db_path=db, now=NOW)[0]
        assert r["reachable"] == "email"
        assert r["suggested_channel"] == "email"
    finally:
        os.unlink(db)


def test_contact_pref_drives_suggestion():
    # student replies by text -> auto contact pref = text -> suggested = text
    db = _build(lambda c: _snap(c, "111", opted_in=False))  # not opted-in now
    try:
        history.persist_notes(
            [{"url": "", "type": "Instant Message (IM) / Text",
              "text": "Incoming: hi", "course": "C769",
              "date": "2026-07-01T09:00:00Z", "author": "x", "subject": "s"}],
            student_id="111", db_path=db)
        r = history.at_risk_students(db_path=db, now=NOW)[0]
        assert r["contact_pref"] == "text" and r["contact_pref_source"] == "auto"
        assert r["suggested_channel"] == "text"   # pref wins over not-opted-in
        assert r["ever_responded"] is True
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
