"""Tests for history name-preservation when an export drops the Name column.

Covers the fix for the "nameless caseload rows" bug: a slimmed list view (or a
grid-missed row) exports no Name, which used to write blank names into history.

  - record_snapshot carries forward the last-known name instead of blanking it.
  - backfill_missing_names cleans rows already captured with a blank name.

Run: python tests/test_history_names.py
"""
import os
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import history  # noqa: E402


def _tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)  # let sqlite create it fresh
    return path


def test_record_snapshot_carries_forward_name():
    db = _tmp_db()
    try:
        # Day 1: full export with a Name.
        r1 = history.record_snapshot(
            [{"StudentID": "000000042", "CourseCode": "D502",
              "Name": "Test Student"}],
            csv_mtime=datetime(2026, 7, 31, 9, 0, 0), interval_hours=24,
            db_path=db, now=datetime(2026, 7, 31, 9, 0, 0))
        assert r1["status"] == "captured", r1

        # Day 2: slimmed export — SAME student, but NO Name column.
        r2 = history.record_snapshot(
            [{"StudentID": "000000042", "CourseCode": "D502"}],
            csv_mtime=datetime(2026, 8, 1, 9, 0, 0), interval_hours=24,
            db_path=db, now=datetime(2026, 8, 1, 9, 0, 0))
        assert r2["status"] == "captured", r2

        conn = history._connect(db)
        try:
            got = conn.execute(
                "SELECT name FROM snapshots WHERE collected_date = '2026-08-01'"
            ).fetchone()
        finally:
            conn.close()
        assert got["name"] == "Test Student", got["name"]
    finally:
        os.unlink(db)


def test_backfill_missing_names():
    db = _tmp_db()
    try:
        history.record_snapshot(
            [{"StudentID": "999", "CourseCode": "C769", "Name": "Ada Byron"}],
            csv_mtime=datetime(2026, 7, 30, 9, 0, 0), interval_hours=24,
            db_path=db, now=datetime(2026, 7, 30, 9, 0, 0))
        # Force a blank-name row in directly (as the old code would have written).
        conn = history._connect(db)
        try:
            with conn:
                conn.execute(
                    "INSERT INTO snapshots (collected_at, collected_date, "
                    "student_id, course_code, name) VALUES "
                    "('2026-08-01T09:00:00', '2026-08-01', '999', 'C769', '')")
        finally:
            conn.close()

        n = history.backfill_missing_names(db_path=db)
        assert n == 1, n

        conn = history._connect(db)
        try:
            got = conn.execute(
                "SELECT name FROM snapshots WHERE collected_date = '2026-08-01'"
            ).fetchone()
        finally:
            conn.close()
        assert got["name"] == "Ada Byron", got["name"]

        # Re-running is a no-op (nothing left blank).
        assert history.backfill_missing_names(db_path=db) == 0
    finally:
        os.unlink(db)


def test_backfill_leaves_never_named_rows_blank():
    db = _tmp_db()
    try:
        conn = history._connect(db)
        try:
            with conn:
                conn.execute(
                    "INSERT INTO snapshots (collected_at, collected_date, "
                    "student_id, course_code, name) VALUES "
                    "('2026-08-01T09:00:00', '2026-08-01', '777', 'C964', '')")
        finally:
            conn.close()
        # No prior non-blank name anywhere -> nothing to fill, stays blank.
        assert history.backfill_missing_names(db_path=db) == 0
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
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
