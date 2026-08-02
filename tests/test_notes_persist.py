"""Tests for history.persist_notes() + note classifiers (Phase 1a contact log).

Covers: note-id parse from the anchor href, channel/direction derivation
(email type + text Incoming:/Outgoing: prefix), insert vs upsert-on-re-scrape
(first_seen_at preserved, student/contact id not blanked), and skip-when-no-id.

Run: python tests/test_notes_persist.py
"""
import os
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import history  # noqa: E402

URL = "https://srm.my.salesforce.com/a16S600000nIdA3IAK"


def _tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    return path


def test_note_id_from_url():
    assert history.note_id_from_url(URL) == "a16S600000nIdA3IAK"
    assert history.note_id_from_url(URL + "?x=1") == "a16S600000nIdA3IAK"
    # Lightning-format record URL: id (18 chars) sits mid-path before /view
    lightning = ("https://srm.lightning.force.com/lightning/r/ShortText__c/"
                 "a16S600000nIdA3IAK/view")
    assert history.note_id_from_url(lightning) == "a16S600000nIdA3IAK"
    assert history.note_id_from_url("") == ""
    assert history.note_id_from_url("https://x/short") == ""


def test_channel_and_direction():
    assert history.classify_note_channel("Instant Message (IM) / Text") == "text"
    assert history.classify_note_channel("Email to Student") == "email"
    assert history.classify_note_channel("Mass Email") == "email"
    assert history.classify_note_channel("Live Call") == "call"
    assert history.classify_note_channel("Course Chatter Response") == "chatter"
    assert history.classify_note_channel("Admin Note") == "note"

    assert history.classify_note_direction("Email from Student", "") == "inbound"
    assert history.classify_note_direction("Email to Student", "") == "outbound"
    assert history.classify_note_direction("welcome email", "") == "outbound"
    # unmarked email (Mass Email, cohort invite) defaults outbound
    assert history.classify_note_direction("Mass Email", "cohort invite") == "outbound"
    assert history.classify_note_direction(
        "Email Exchange with Student", "long thread") == "outbound"
    # text direction from the body prefix
    assert history.classify_note_direction(
        "Instant Message (IM) / Text", "Incoming: hi Jim") == "inbound"
    assert history.classify_note_direction(
        "Instant Message (IM) / Text", "Outgoing: checking in") == "outbound"
    # first marker wins in a mixed thread
    assert history.classify_note_direction(
        "Instant Message (IM) / Text",
        "Outgoing: hi\nIncoming: thanks") == "outbound"
    # unprefixed text + calls/admin notes stay unknown
    assert history.classify_note_direction(
        "Instant Message (IM) / Text", "Pat • Hi how are you") == ""
    assert history.classify_note_direction("Live Call", "left vm") == ""
    assert history.classify_note_direction("Admin Note", "internal") == ""


def _note(url=URL, typ="Instant Message (IM) / Text", text="Incoming: hi",
          course="C769", date="2026-07-01T09:00:00", author="Jim Ashe",
          subject="chat"):
    return {"url": url, "type": typ, "text": text, "course": course,
            "date": date, "author": author, "subject": subject}


def test_persist_insert_then_upsert():
    db = _tmp_db()
    try:
        r1 = history.persist_notes(
            [_note()], student_id="000000042", contact_id="0031",
            db_path=db, now=datetime(2026, 7, 1, 10, 0, 0))
        assert r1 == {"inserted": 1, "updated": 0, "skipped": 0}, r1
        assert history.notes_count(db_path=db) == 1

        # Re-scrape: same note edited, and this scrape lacks a student_id — must
        # UPSERT (not duplicate) and must NOT blank the known student_id.
        r2 = history.persist_notes(
            [_note(text="Incoming: hi (edited)")], student_id="",
            contact_id="", db_path=db, now=datetime(2026, 7, 2, 10, 0, 0))
        assert r2 == {"inserted": 0, "updated": 1, "skipped": 0}, r2
        assert history.notes_count(db_path=db) == 1

        conn = history._connect(db)
        try:
            row = conn.execute("SELECT * FROM notes").fetchone()
        finally:
            conn.close()
        assert row["body"] == "Incoming: hi (edited)"     # refreshed
        assert row["student_id"] == "000000042"           # preserved
        assert row["direction"] == "inbound" and row["channel"] == "text"
        assert row["first_seen_at"] == "2026-07-01T10:00:00"   # preserved
        assert row["last_seen_at"] == "2026-07-02T10:00:00"    # refreshed
    finally:
        os.unlink(db)


def test_persist_synthetic_id_when_no_url():
    # No parseable href (common — anchor in a shadow root): the note must still
    # be STORED via a content-hash id, and a re-scrape of the same content must
    # UPSERT (stable id), not duplicate.
    db = _tmp_db()
    try:
        r1 = history.persist_notes(
            [_note(url="")], contact_id="0031", db_path=db,
            now=datetime(2026, 7, 1, 10, 0, 0))
        assert r1 == {"inserted": 1, "updated": 0, "skipped": 0}, r1
        r2 = history.persist_notes(
            [_note(url="")], contact_id="0031", db_path=db,
            now=datetime(2026, 7, 2, 10, 0, 0))
        assert r2 == {"inserted": 0, "updated": 1, "skipped": 0}, r2
        assert history.notes_count(db_path=db) == 1
    finally:
        os.unlink(db)


def test_persist_skips_empty_note():
    # No url, no date, no body — nothing to identify or store.
    db = _tmp_db()
    try:
        r = history.persist_notes(
            [{"url": "", "type": "Admin Note", "date": "", "text": ""}],
            db_path=db)
        assert r == {"inserted": 0, "updated": 0, "skipped": 1}, r
        assert history.notes_count(db_path=db) == 0
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
