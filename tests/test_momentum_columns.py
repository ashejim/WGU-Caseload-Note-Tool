"""Momentum-risk columns are registered as filterable caseload columns and work
with the filter engine (numeric range + categorical). Guards the contract that
App._apply_derived_columns_to_rows injects (MomentumRisk / AvgMomentumRank /
MomentumTrend / NeverAttempted / ContactPref) and that they filter correctly.

Run: python tests/test_momentum_columns.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import caseload_csv  # noqa: E402
from src import caseload_filter as cf  # noqa: E402

_NEW = {
    "Risk %": "MomentumRisk",
    "Avg Momentum Rank": "AvgMomentumRank",
    "Momentum Trend": "MomentumTrend",
    "Never Attempted": "NeverAttempted",
    "Contact Preference": "ContactPref",
}


def _rows():
    return [
        {"StudentID": "1", "CourseCode": "C769", "Name": "A",
         "MomentumRisk": 32.4, "ContactPref": "text", "NeverAttempted": "No"},
        {"StudentID": "2", "CourseCode": "C769", "Name": "B",
         "MomentumRisk": 24.0, "ContactPref": "text", "NeverAttempted": "Yes"},
        {"StudentID": "3", "CourseCode": "C769", "Name": "C",
         "MomentumRisk": 24.0, "ContactPref": "email", "NeverAttempted": "No"},
        {"StudentID": "4", "CourseCode": "C769", "Name": "D",
         "MomentumRisk": 15.0, "ContactPref": "text", "NeverAttempted": "No"},
        {"StudentID": "5", "CourseCode": "C769", "Name": "E",
         "MomentumRisk": "", "ContactPref": "", "NeverAttempted": ""},
    ]


def _match(raw):
    rows = _rows()
    headers = list(rows[0].keys())
    filters = [cf.resolve_filter_columns(f, headers) for f in raw]
    return {r["Name"] for r in cf.apply_filters(filters, rows)}


def test_columns_registered_and_roundtrip():
    for disp, hdr in _NEW.items():
        assert caseload_csv.DISPLAY_TO_CSV.get(disp) == hdr, disp
        assert caseload_csv.display_for_column(hdr) == disp, hdr


def test_risk_range_and_pref():
    # the motivating example: 20 <= risk <= 30 AND preference is text
    got = _match([
        {"column": "Risk %", "op": "at least", "value": "20"},
        {"column": "Risk %", "op": "at most", "value": "30"},
        {"column": "Contact Preference", "op": "is", "value": "text"},
    ])
    assert got == {"B"}, got            # A too high, C email, D too low, E blank


def test_blank_risk_excluded_by_numeric():
    got = _match([{"column": "Risk %", "op": "at least", "value": "1"}])
    assert "E" not in got and got == {"A", "B", "C", "D"}, got


def test_never_attempted_categorical():
    got = _match([{"column": "Never Attempted", "op": "is", "value": "Yes"}])
    assert got == {"B"}, got


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
