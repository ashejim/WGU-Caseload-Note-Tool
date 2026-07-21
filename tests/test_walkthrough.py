"""Navigation-logic tests for src.walkthrough.Walkthrough.

These verify the step sequencing WITHOUT a real Tk display (rendering is stubbed)
— so "the tour starts on step 1, advances, and finishing sets the done flag" is
guaranteed independent of any on-screen check.
"""
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.walkthrough import Walkthrough  # noqa: E402


def _wt():
    app = SimpleNamespace(
        root=MagicMock(),
        settings=SimpleNamespace(walkthrough_done=False),
    )
    wt = Walkthrough(app)
    wt._render = lambda: None          # skip all Tk rendering
    return wt


def test_starts_on_first_step():
    wt = _wt()
    wt.start()
    assert wt.i == 0
    assert wt._active is True
    assert len(wt.steps) >= 5          # golden path has several steps


def test_next_advances_and_back_returns():
    wt = _wt()
    wt.start()
    wt._next()
    assert wt.i == 1
    wt._next()
    assert wt.i == 2
    wt._back()
    assert wt.i == 1
    wt._back()
    assert wt.i == 0
    wt._back()                          # can't go before the first
    assert wt.i == 0


def test_next_on_last_step_finishes_and_sets_flag():
    wt = _wt()
    wt.start()
    for _ in range(len(wt.steps) - 1):
        wt._next()
    assert wt.i == len(wt.steps) - 1
    wt._next()                          # past the last step
    assert wt._active is False
    assert wt.app.settings.walkthrough_done is True


def test_skip_finishes_and_sets_flag():
    wt = _wt()
    wt.start()
    wt._finish(completed=False)
    assert wt._active is False
    assert wt.app.settings.walkthrough_done is True


def test_start_is_idempotent_while_active():
    wt = _wt()
    wt.start()
    wt._next()
    assert wt.i == 1
    wt.start()                          # already active — must not reset to 0
    assert wt.i == 1


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
