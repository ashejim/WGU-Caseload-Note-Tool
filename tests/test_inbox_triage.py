"""Tests for src/inbox_triage.py — sender/recipient → course/CI triage.

Pure-logic tests against a small synthetic roster (no COM, no real PII).
Run: python tests/test_inbox_triage.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import inbox_triage as t  # noqa: E402


def _rec(email, name, course, mentor, sid):
    return {"StudentEmail": email, "Name": name, "CourseCode": course,
            "CourseMentor": mentor, "StudentID": sid}


ROSTER = [
    _rec("gcisne5@wgu.edu", "Gerardo Cisneros", "C769", "Jim Ashe", "010437735"),
    _rec("apark12@wgu.edu", "Ana Park", "C769", "Charlie Paddock", "010000001"),
    _rec("bmill3@wgu.edu", "Bo Miller", "C769", "", "010000002"),  # unassigned
    # same student in two courses (two records, same email)
    _rec("cdoe7@wgu.edu", "Cat Doe", "C769", "Jim Ashe", "010000003"),
    _rec("cdoe7@wgu.edu", "Cat Doe", "D502", "Tawnya Lee", "010000003"),
    # two DIFFERENT students who share a display name
    _rec("jsmith1@wgu.edu", "Jo Smith", "C964", "Jim Ashe", "010000004"),
    _rec("jsmith2@wgu.edu", "Jo Smith", "C769", "Jeff Davis", "010000005"),
]
INDEX = t.build_index(ROSTER)


def test_email_match_confident():
    r = t.triage(INDEX, "gcisne5@wgu.edu", "Cisneros, Gerardo")
    assert r["method"] == "email" and r["confident"]
    assert r["categories"] == ["C769", "Jim"]
    assert r["students"][0]["student_id"] == "010437735"


def test_email_match_case_insensitive():
    r = t.triage(INDEX, "GCisne5@WGU.EDU")
    assert r["method"] == "email" and r["categories"] == ["C769", "Jim"]


def test_blank_mentor_gets_unassigned_ci():
    r = t.triage(INDEX, "bmill3@wgu.edu")
    assert r["confident"]
    assert r["categories"] == ["C769", t.UNASSIGNED_CATEGORY]
    assert "no CI assigned" in r["note"]


def test_multi_course_student_gets_all_categories():
    r = t.triage(INDEX, "cdoe7@wgu.edu")
    assert r["categories"] == ["C769", "Jim", "D502", "Tawnya"]
    assert len(r["students"]) == 2


def test_unmatched_gets_unidentified():
    r = t.triage(INDEX, "stranger@gmail.com", "Total Stranger")
    assert r["method"] == "none" and not r["confident"]
    assert r["categories"] == [t.UNIDENTIFIED_CATEGORY]


def test_name_fallback_flagged_not_confident():
    # personal address, but display name matches one roster student
    r = t.triage(INDEX, "anap@gmail.com", "Park, Ana")
    assert r["method"] == "name" and not r["confident"]
    assert r["categories"] == ["C769", "Charlie"]
    assert "review" in r["note"]


def test_ambiguous_name_not_guessed():
    r = t.triage(INDEX, "jo@gmail.com", "Jo Smith")
    assert r["method"] == "none"
    assert r["categories"] == [t.UNIDENTIFIED_CATEGORY]
    assert "ambiguous" in r["note"]


def test_blank_sender_unidentified():
    r = t.triage(INDEX, "", "")
    assert r["method"] == "none"
    assert r["categories"] == [t.UNIDENTIFIED_CATEGORY]


def test_ci_category_first_name():
    assert t.ci_category("Charlie Paddock") == "Charlie"
    assert t.ci_category("Tawnya Lee") == "Tawnya"
    assert t.ci_category("") == ""


def test_normalize_name_forms():
    assert t.normalize_name("Cisneros, Gerardo") == "gerardo cisneros"
    assert t.normalize_name("  Gerardo   Cisneros ") == "gerardo cisneros"
    assert t.normalize_name("Dr. Jim Ashe") == "dr jim ashe"


# ---- course filtering + roster summary ---------------------------------

def test_course_filter_excludes_other_courses():
    # only D502 configured: C769-only students become Unidentified
    idx = t.build_index(ROSTER, courses=["D502"])
    r = t.triage(idx, "gcisne5@wgu.edu")
    assert r["categories"] == [t.UNIDENTIFIED_CATEGORY]
    # the multi-course student keeps only the D502 labels
    r = t.triage(idx, "cdoe7@wgu.edu")
    assert r["categories"] == ["D502", "Tawnya"]


def test_course_filter_case_insensitive():
    idx = t.build_index(ROSTER, courses=["c769"])
    r = t.triage(idx, "gcisne5@wgu.edu")
    assert r["categories"] == ["C769", "Jim"]


def test_roster_summary_counts_and_cis():
    s = t.roster_summary(ROSTER)
    assert s["courses"] == {"C769": 5, "D502": 1, "C964": 1}
    assert s["cis"] == ["Charlie", "Jeff", "Jim", "Tawnya"]
    s = t.roster_summary(ROSTER, courses=["D502"])
    assert s["courses"] == {"D502": 1} and s["cis"] == ["Tawnya"]


# ---- triage_many: sent-mail identification by recipient set ------------

def test_many_recipient_match_ignores_staff_corecipients():
    r = t.triage_many(INDEX, [
        ("jim.ashe@wgu.edu", "Jim Ashe"),           # the CI, not in roster
        ("gcisne5@wgu.edu", "Gerardo Cisneros"),    # the student
    ])
    assert r["method"] == "email" and r["confident"]
    assert r["categories"] == ["C769", "Jim"]


def test_many_two_students_union():
    r = t.triage_many(INDEX, [
        ("gcisne5@wgu.edu", "Gerardo Cisneros"),
        ("apark12@wgu.edu", "Ana Park"),
    ])
    assert r["categories"] == ["C769", "Jim", "Charlie"]
    assert len(r["students"]) == 2


def test_many_name_only_flagged():
    r = t.triage_many(INDEX, [("anap@gmail.com", "Ana Park")])
    assert r["method"] == "name" and not r["confident"]


def test_many_no_match_unidentified():
    r = t.triage_many(INDEX, [("someone@vendor.com", "Vendor Person")])
    assert r["method"] == "none"
    assert r["categories"] == [t.UNIDENTIFIED_CATEGORY]


def test_many_empty_recipients_unidentified():
    r = t.triage_many(INDEX, [])
    assert r["categories"] == [t.UNIDENTIFIED_CATEGORY]


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
