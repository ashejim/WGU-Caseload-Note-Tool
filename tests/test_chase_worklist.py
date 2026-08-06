"""Tests for the persistent worklist ledger (history.sync_chase_list /
set_chase_status). These test the PERSISTENCE mechanics only — membership
recording, first-listed stability, drop-off, and manual status — decoupled from
whatever ranking (momentum_risk_students) produced the rows. Rows are built by
hand and fed to sync_chase_list.

Run: python tests/test_chase_worklist.py
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import history  # noqa: E402

NOW = datetime(2026, 8, 2, 12, 0, 0)


def _tmp_db():
    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(p)
    return p


def _rows(*ids):
    return [{"student_id": s, "course_code": "C769", "name": f"S{s}"}
            for s in ids]


def _row(db, sid, course="C769"):
    conn = history._connect(db)
    try:
        return conn.execute("SELECT * FROM chase_list WHERE student_id = ? AND "
                            "course_code = ?", (sid, course)).fetchone()
    finally:
        conn.close()


def _ids(rows):
    return {r["student_id"] for r in rows}


def _worklist(db, now, include_dismissed=False):
    """Mimic chase_worklist's filter step on a fixed row set (no risk model)."""
    rows = history.sync_chase_list(_rows("111"), db_path=db, now=now)
    if not include_dismissed:
        rows = [r for r in rows if r.get("chase_status") != "dismissed"]
    return rows


def test_sync_records_membership():
    db = _tmp_db()
    try:
        rows = history.sync_chase_list(_rows("111"), db_path=db, now=NOW)
        assert _ids(rows) == {"111"}, _ids(rows)
        r = rows[0]
        assert r["days_on_list"] == 0 and r["chase_status"] == ""
        assert r["first_listed_at"].startswith("2026-08-02")
        assert _row(db, "111")["resolved_at"] is None
    finally:
        os.unlink(db)


def test_first_listed_stable_across_syncs():
    db = _tmp_db()
    try:
        history.sync_chase_list(_rows("111"), db_path=db, now=NOW)
        later = NOW + timedelta(days=3)
        rows = history.sync_chase_list(_rows("111"), db_path=db, now=later)
        r = rows[0]
        assert r["first_listed_at"].startswith("2026-08-02")   # unchanged
        assert r["days_on_list"] == 3
        assert _row(db, "111")["last_listed_at"].startswith("2026-08-05")
    finally:
        os.unlink(db)


def test_dropoff_sets_resolved():
    db = _tmp_db()
    try:
        history.sync_chase_list(_rows("111"), db_path=db, now=NOW)
        later = NOW + timedelta(days=1)
        rows = history.sync_chase_list([], db_path=db, now=later)  # 111 gone
        assert _ids(rows) == set()
        assert _row(db, "111")["resolved_at"].startswith("2026-08-03")
    finally:
        os.unlink(db)


def test_readd_clears_resolved():
    db = _tmp_db()
    try:
        history.sync_chase_list(_rows("111"), db_path=db, now=NOW)
        history.sync_chase_list([], db_path=db, now=NOW + timedelta(days=1))
        history.sync_chase_list(_rows("111"), db_path=db, now=NOW + timedelta(days=2))
        assert _row(db, "111")["resolved_at"] is None       # back on the list
    finally:
        os.unlink(db)


def test_dismiss_hides_and_persists():
    db = _tmp_db()
    try:
        history.sync_chase_list(_rows("111"), db_path=db, now=NOW)
        history.set_chase_status("111", "C769", "dismissed", db_path=db, now=NOW)
        assert _ids(_worklist(db, NOW)) == set()             # hidden
        shown = _worklist(db, NOW, include_dismissed=True)
        assert _ids(shown) == {"111"} and shown[0]["chase_status"] == "dismissed"
        # a later sync while still present must NOT revive them
        assert _ids(_worklist(db, NOW + timedelta(days=2))) == set()
        assert _row(db, "111")["status"] == "dismissed"
    finally:
        os.unlink(db)


def test_contacted_stays_active():
    db = _tmp_db()
    try:
        history.sync_chase_list(_rows("111"), db_path=db, now=NOW)
        history.set_chase_status("111", "C769", "contacted", db_path=db, now=NOW)
        rows = _worklist(db, NOW)
        assert _ids(rows) == {"111"} and rows[0]["chase_status"] == "contacted"
    finally:
        os.unlink(db)


def test_clear_status():
    db = _tmp_db()
    try:
        history.sync_chase_list(_rows("111"), db_path=db, now=NOW)
        history.set_chase_status("111", "C769", "dismissed", db_path=db, now=NOW)
        history.set_chase_status("111", "C769", "", db_path=db, now=NOW)
        rows = _worklist(db, NOW)
        assert _ids(rows) == {"111"} and rows[0]["chase_status"] == ""
    finally:
        os.unlink(db)


def test_invalid_status_rejected():
    db = _tmp_db()
    try:
        try:
            history.set_chase_status("111", "C769", "bogus", db_path=db)
        except ValueError:
            return
        raise AssertionError("expected ValueError for bogus status")
    finally:
        if os.path.exists(db):      # validation rejects before the DB is created
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
