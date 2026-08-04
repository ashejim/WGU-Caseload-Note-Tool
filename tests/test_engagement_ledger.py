"""Tests for history.engagement_ledger() — per-student cost-aware channel strategy.

Run: python tests/test_engagement_ledger.py
"""
import os
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import history  # noqa: E402

URL = "https://srm.my.salesforce.com/a16S600000nIdA3IAK"


def _tmp_db():
    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(p)
    return p


def _note(sid, channel_type, direction, date, body="", n=0):
    # persist_notes derives channel/direction from type + body; craft accordingly.
    typ = {"text": "Instant Message (IM) / Text", "email": "Email to Student",
           "call": "Live Call"}[channel_type]
    if channel_type == "text":
        body = ("Incoming: " if direction == "inbound" else "Outgoing: ") + (body or "hi")
    elif channel_type == "email" and direction == "inbound":
        typ = "Email from Student"
    return {"url": "", "type": typ, "text": body, "course": "C769",
            "date": date, "author": "Jim Ashe", "subject": f"n{n}"}


def _seed(db, sid, notes):
    for i, nd in enumerate(notes):
        history.persist_notes([{**nd, "subject": f"{sid}-{i}"}],
                              student_id=sid, contact_id="", db_path=db)


def test_prefers_channel_student_replies_to():
    db = _tmp_db()
    try:
        # texted a lot (no reply), emailed once and student replied by email
        _seed(db, "111", [
            _note("111", "text", "outbound", "2026-07-01T09:00:00Z", n=1),
            _note("111", "text", "outbound", "2026-07-05T09:00:00Z", n=2),
            _note("111", "email", "outbound", "2026-07-06T09:00:00Z", n=3),
            _note("111", "email", "inbound", "2026-07-07T09:00:00Z", n=4),
        ])
        led = history.engagement_ledger("111", db_path=db)
        assert led["responds_to"] == ["email"], led["responds_to"]
        assert led["suggested_next"] == "email", led["suggested_next"]
        assert set(led["tried"]) == {"text", "email"}
        assert led["channels"]["text"]["responds"] is False
        assert led["channels"]["email"]["response_rate"] == 1.0
    finally:
        os.unlink(db)


def test_escalates_when_no_reply():
    db = _tmp_db()
    try:
        # only texted, never a reply -> escalate to the next tier (email)
        _seed(db, "222", [
            _note("222", "text", "outbound", "2026-07-01T09:00:00Z", n=1),
            _note("222", "text", "outbound", "2026-07-03T09:00:00Z", n=2),
        ])
        led = history.engagement_ledger("222", db_path=db)
        assert led["responds_to"] == []
        assert led["suggested_next"] == "email", led
        assert "escalate" in led["reason"]
    finally:
        os.unlink(db)


def test_all_tried_no_reply_calls_last():
    db = _tmp_db()
    try:
        _seed(db, "333", [
            _note("333", "text", "outbound", "2026-07-01T09:00:00Z", n=1),
            _note("333", "email", "outbound", "2026-07-02T09:00:00Z", n=2),
        ])
        led = history.engagement_ledger("333", db_path=db)
        assert led["suggested_next"] == "call", led
    finally:
        os.unlink(db)


def test_no_contact_starts_low_cost():
    db = _tmp_db()
    try:
        led = history.engagement_ledger("444", db_path=db)
        assert led["suggested_next"] == "text"
        assert led["tried"] == [] and led["responds_to"] == []
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
