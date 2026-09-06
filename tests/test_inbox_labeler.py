"""Tests for src/inbox_labeler.py — the background labeler engine.

Covers the pure parts (settings parsing, apply policy, summaries) plus
run_pass's roster guard. No COM / no real Outlook.
Run: python tests/test_inbox_labeler.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import inbox_labeler as il  # noqa: E402
from src import inbox_triage  # noqa: E402


def test_parse_items_commas_newlines_blanks():
    assert il.parse_items("C769, D502", ["X"]) == ["C769", "D502"]
    assert il.parse_items("C769\nD502,  C964 ", ["X"]) == [
        "C769", "D502", "C964"]
    assert il.parse_items("", ["X"]) == ["X"]          # blank -> default
    assert il.parse_items(" ,\n, ", ["X"]) == ["X"]    # only separators


def test_defaults_are_the_agreed_team_set():
    assert il.DEFAULT_FOLDERS == ["UG Capstone IT"]
    # C868 retired; D370 has its own inbox (user, 2026-09-01)
    assert il.DEFAULT_COURSES == ["C769", "C964", "D342", "D502", "D424"]


def test_plan_categories_policy():
    email = {"method": inbox_triage.METHOD_EMAIL,
             "categories": ["C769", "Jim"]}
    name = {"method": inbox_triage.METHOD_NAME,
            "categories": ["C769", "Jim"]}
    none = {"method": inbox_triage.METHOD_NONE,
            "categories": [inbox_triage.UNIDENTIFIED_CATEGORY]}
    assert il.plan_categories(email) == ["C769", "Jim"]
    assert il.plan_categories(name) == []          # review-only, no label
    assert il.plan_categories(none) == ["Unidentified"]


def test_summary_line_reads_well():
    line = il.summary_line({"labeled": 3, "identified": 2, "review": 1,
                            "unidentified": 1, "scanned": 4,
                            "folder_errors": []})
    assert "3 labeled" in line and "2 identified" in line
    assert "1 name-match (review)" in line and "1 unidentified" in line
    quiet = il.summary_line({"labeled": 0, "identified": 0, "review": 0,
                             "unidentified": 0, "scanned": 0,
                             "folder_errors": []})
    assert quiet == "Inbox labeler: 0 labeled."


def test_state_entry_roundtrip_and_legacy():
    assert il.parse_state_entry(il.state_entry(True, "2026-08-31T10:00:00")) \
        == (True, "2026-08-31T10:00:00")
    assert il.parse_state_entry(il.state_entry(False, "2026-08-31T10:00:00")) \
        == (False, "2026-08-31T10:00:00")
    # legacy plain-timestamp entries re-check once against a newer roster
    assert il.parse_state_entry("2026-08-30T12:00:00") \
        == (False, "2026-08-30T12:00:00")


def test_is_resolved_only_for_full_email_match():
    ok = {"method": inbox_triage.METHOD_EMAIL,
          "categories": ["C769", "Charlie"]}
    unassigned = {"method": inbox_triage.METHOD_EMAIL,
                  "categories": ["C769", inbox_triage.UNASSIGNED_CATEGORY]}
    none = {"method": inbox_triage.METHOD_NONE,
            "categories": [inbox_triage.UNIDENTIFIED_CATEGORY]}
    assert il.is_resolved(ok)
    assert not il.is_resolved(unassigned)   # roster may assign a CI later
    assert not il.is_resolved(none)


def test_merge_categories_upgrade_removes_stale_marker():
    from src.outlook_inbox import merge_categories
    # the Timothy case: Unidentified → C769 + Charlie, marker stripped
    assert merge_categories("Unidentified", ["C769", "Charlie"],
                            remove=["Unidentified", "Unassigned"]) \
        == "C769, Charlie"
    # human categories survive an upgrade
    assert merge_categories("Orange Category, Unidentified", ["C769"],
                            remove=["Unidentified"]) \
        == "Orange Category, C769"
    # no change → None (no COM save)
    assert merge_categories("C769, Charlie", ["C769", "Charlie"],
                            remove=["Unidentified"]) is None
    assert merge_categories("", []) is None
    # plain add still works
    assert merge_categories("", ["Unidentified"]) == "Unidentified"


def test_run_pass_missing_roster_raises_actionable():
    missing = os.path.join(tempfile.gettempdir(), "no_such_roster_xyz.json")
    try:
        il.run_pass(folders=["Inbox"], courses=["C769"], lookback_days=1,
                    roster_path=missing)
        assert False, "should have raised"
    except FileNotFoundError as e:
        assert "coursescan" in str(e)


def test_state_roundtrip(tmp_swap=None):
    # swap the module's state path to a temp file for the test
    orig = il.STATE_PATH
    fd, p = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        il.STATE_PATH = type(orig)(p)
        il.save_state({"<msgid1>": "2026-08-30T12:00:00"})
        assert il.load_state() == {"<msgid1>": "2026-08-30T12:00:00"}
    finally:
        il.STATE_PATH = orig
        os.unlink(p)


def test_load_state_corrupt_returns_empty():
    orig = il.STATE_PATH
    fd, p = tempfile.mkstemp(suffix=".json")
    os.write(fd, b"{not json")
    os.close(fd)
    try:
        il.STATE_PATH = type(orig)(p)
        assert il.load_state() == {}
    finally:
        il.STATE_PATH = orig
        os.unlink(p)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  ok  {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            import traceback
            failed += 1
            print(f"FAIL  {fn.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
