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


def _fire_titles(steps):
    return [s for s in steps if "fire a safe" in s["title"].lower()]


def test_fire_step_prefers_bundled_walkthrough_action():
    # When the bundled safe action ships, the fire step targets it by name.
    from src.walkthrough import WALKTHROUGH_ACTION
    app = SimpleNamespace(
        root=MagicMock(), settings=SimpleNamespace(walkthrough_done=False),
        scenarios={WALKTHROUGH_ACTION: object()},
        groups=[SimpleNamespace(name="Samples",
                                scenarios=[WALKTHROUGH_ACTION])])
    wt = Walkthrough(app)
    assert wt._fire_target() == ("Samples", WALKTHROUGH_ACTION)
    steps = wt._build_steps()
    fire = _fire_titles(steps)
    assert len(fire) == 1 and fire[0]["kind"] == "do"
    assert WALKTHROUGH_ACTION in fire[0]["body"]


def test_fire_step_falls_back_to_test_group():
    # No bundled action, but a user 'Test' group → still offered (by group).
    app = SimpleNamespace(
        root=MagicMock(), settings=SimpleNamespace(walkthrough_done=False),
        scenarios={}, groups=[SimpleNamespace(name="\U0001f9ea Test",
                                              scenarios=[])])
    wt = Walkthrough(app)
    assert wt._fire_target() == ("\U0001f9ea Test", "")
    assert len(_fire_titles(wt._build_steps())) == 1


def test_fire_step_omitted_without_target():
    app = SimpleNamespace(
        root=MagicMock(), settings=SimpleNamespace(walkthrough_done=False),
        scenarios={}, groups=[])
    wt = Walkthrough(app)
    assert wt._fire_target() == (None, "")
    assert _fire_titles(wt._build_steps()) == []


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
