"""Tests for App._merge_grid_and_csv_rows — the JSON-primary caseload merge.

The live grid is the authoritative roster; the CSV only overlays columns the
grid lacks. A student in the CSV but ABSENT from a healthy grid has departed
(WGU drops passers from the feed), so it must be LEFT OFF the live list rather
than re-injected as a name-less ghost row (the "nameless caseload row" bug).

Run: python tests/test_caseload_merge.py
"""
import importlib.util
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _load_app():
    path = os.path.join(ROOT, "scripts", "launcher.py")
    spec = importlib.util.spec_from_file_location("launcher_merge", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.App


App = _load_app()


def _merge(built, csv_rows):
    """Call the method against a bare stand-in self (it only sets one attr)."""
    fake = types.SimpleNamespace(_grid_dropped_csv_only=None)
    result = App._merge_grid_and_csv_rows(fake, built, csv_rows)
    return result, fake._grid_dropped_csv_only


def test_grid_missed_csv_row_is_dropped():
    # Grid (live roster) has one active student; CSV additionally lists a passer
    # who dropped off the grid and carries no Name (slimmed list view).
    built = [{"StudentID": "111", "CourseCode": "C769", "Name": "Ada Byron"}]
    csv_rows = [
        {"StudentID": "111", "CourseCode": "C769"},
        {"StudentID": "000000042", "CourseCode": "D502"},  # passer, grid-missed
    ]
    result, dropped = _merge(built, csv_rows)
    ids = {r.get("StudentID") for r in result}
    assert ids == {"111"}, ids                       # passer NOT re-injected
    assert dropped == [("000000042", "D502")], dropped


def test_csv_overlays_missing_columns_on_grid_rows():
    built = [{"StudentID": "111", "CourseCode": "C769", "Name": "Ada Byron"}]
    csv_rows = [{"StudentID": "111", "CourseCode": "C769",
                 "CourseFollowupNote": "call her"}]
    result, dropped = _merge(built, csv_rows)
    assert len(result) == 1
    assert result[0]["CourseFollowupNote"] == "call her"  # CSV-only col overlaid
    assert result[0]["Name"] == "Ada Byron"               # grid value kept
    assert dropped == []


def test_unkeyable_csv_row_is_not_dropped_or_added():
    # A CSV row with no StudentID (view dropped the ID column) can't be a
    # distinct student — it's neither re-injected nor counted as a departure.
    built = [{"StudentID": "111", "CourseCode": "C769", "Name": "Ada Byron"}]
    csv_rows = [{"CourseCode": "C769"}]
    result, dropped = _merge(built, csv_rows)
    assert {r.get("StudentID") for r in result} == {"111"}
    assert dropped == []


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
