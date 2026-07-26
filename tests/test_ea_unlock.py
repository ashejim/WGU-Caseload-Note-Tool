"""Tests for the locked-task EA matcher that decides when the fire-time note
dialog shows the "Open the EA dashboard to unlock this task" jump.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.dialogs import _ea_is_locked_task  # noqa: E402


def test_matches_locked_and_assessment_task_phrasings():
    for reason in ["Assessment Task Locked", "Task Locked - PA",
                   "Locked assessment", "Objective Assessment Task",
                   "PA TASK LOCKED"]:
        assert _ea_is_locked_task({"reason": reason}), reason


def test_ignores_unrelated_eas():
    for reason in ["Welcome outreach", "Follow-up call", "Momentum check",
                   "", "Course kickoff"]:
        assert not _ea_is_locked_task({"reason": reason}), reason


def test_matches_locked_signal_in_intervention():
    # The 'locked'/'unlock' signal often lives in Intervention, not the reason.
    assert _ea_is_locked_task(
        {"reason": "Objective Assessment", "intervention": "Assessment Unlock"})
    assert _ea_is_locked_task(
        {"reason": "Assessment", "intervention": "Unlock Request"})
    assert _ea_is_locked_task(
        {"reason": "PA", "event_progress": "Task Locked"})


def test_tolerates_missing_or_bad_input():
    assert not _ea_is_locked_task({})
    assert not _ea_is_locked_task(None)
    assert not _ea_is_locked_task({"reason": None})


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
