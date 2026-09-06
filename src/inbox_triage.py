"""Sender → course + CI triage for the inbox labeler.

Pure logic, no COM: resolve an email sender against the CourseScan team
roster (coursescan_roster.json) and decide which Outlook categories the
message should get. Two categories per identified message:

  - the course category  — the course code itself, e.g. ``C769``
  - the CI category      — the CI's first name, e.g. ``Jim`` (matches
    the team's existing folder/category naming; decided 2026-08-30,
    supersedes the earlier ``CI: <last name>`` scheme)

The category NAME is the label; colors are cosmetic and live in each
mailbox's master category list (seeded manually, not by code).

Matching policy (agreed with the user):
  - Email match (case-insensitive on the roster's StudentEmail) is the
    only CONFIDENT identification — safe to auto-apply.
  - Name match is a fallback for students writing from personal
    addresses: it is FLAGGED for review, never treated as confident
    (roster emails are all @wgu.edu, so personal-address mail can only
    match by display name — risky).
  - Anything else gets ``Unidentified`` — never silence.
  - A student with several roster records (multiple courses) gets ALL
    of their course/CI categories.
  - A roster record with a blank CourseMentor (common: unassigned
    C769 students) gets ``Unassigned`` in the CI slot — every
    identified message carries both a course and a CI-slot label
    (user request 2026-08-30).
"""
import json
from pathlib import Path

UNIDENTIFIED_CATEGORY = "Unidentified"
UNASSIGNED_CATEGORY = "Unassigned"

# Triage methods, in decreasing confidence.
METHOD_EMAIL = "email"   # sender SMTP == roster StudentEmail (confident)
METHOD_NAME = "name"     # unique display-name match only (flagged, review)
METHOD_NONE = "none"     # no match → Unidentified


def course_category(course_code: str) -> str:
    """Category name for a course — the code itself (``C769``)."""
    return (course_code or "").strip()


def ci_category(mentor_name: str) -> str:
    """Category name for a course instructor: their FIRST name
    ("Tawnya Lee" → "Tawnya") — the team's established naming (their
    shared-box folders and hand-made categories already use first
    names: Tawnya, Jeff, Jim, Candice, Charlie, Emily). Returns "" for
    a blank mentor (unassigned students) — the caller then labels
    course-only.
    """
    name = (mentor_name or "").strip()
    if not name:
        return ""
    return name.split()[0]


def normalize_name(name: str) -> str:
    """Canonical form for display-name comparison: lowercase,
    'Last, First' flipped to 'first last', periods stripped, spaces
    collapsed. 'Cisneros, Gerardo' and 'Gerardo Cisneros' both →
    'gerardo cisneros'."""
    s = (name or "").strip().lower().replace(".", "")
    if "," in s:
        last, _, first = s.partition(",")
        s = f"{first.strip()} {last.strip()}"
    return " ".join(s.split())


def load_roster(path) -> list:
    """Load coursescan_roster.json → list of record dicts."""
    with open(Path(path), encoding="utf-8") as f:
        return json.load(f)


def build_index(roster: list, courses=None) -> dict:
    """Index roster records for triage.

    `courses` — optional iterable of course codes to label (the team's
    configured list). Records for other courses are left out entirely,
    so their students triage to ``Unidentified`` rather than getting a
    label for a course the team doesn't handle. None/empty = all.

    Returns ``{"by_email": {lower email: [records]},
               "by_name": {normalized name: [records]}}``.
    """
    allowed = {c.strip().upper() for c in (courses or []) if c.strip()}
    by_email, by_name = {}, {}
    for r in roster:
        if allowed and (r.get("CourseCode") or "").strip().upper() not in allowed:
            continue
        email = (r.get("StudentEmail") or "").strip().lower()
        if email:
            by_email.setdefault(email, []).append(r)
        name = normalize_name(r.get("Name") or "")
        if name:
            by_name.setdefault(name, []).append(r)
    return {"by_email": by_email, "by_name": by_name}


def roster_summary(roster: list, courses=None) -> dict:
    """What the roster can label, for display in the settings GUI:
    per-course student counts and the auto-detected CI category names
    (first names from CourseMentor). Restricted to `courses` when given.

    Returns ``{"courses": {code: count}, "cis": [name, ...]}`` with CIs
    sorted; unassigned records don't add a CI.
    """
    allowed = {c.strip().upper() for c in (courses or []) if c.strip()}
    by_course, cis = {}, set()
    for r in roster:
        code = (r.get("CourseCode") or "").strip()
        if not code or (allowed and code.upper() not in allowed):
            continue
        by_course[code] = by_course.get(code, 0) + 1
        ci = ci_category(r.get("CourseMentor") or "")
        if ci:
            cis.add(ci)
    return {"courses": by_course, "cis": sorted(cis)}


def _categories_for(records: list) -> tuple:
    """(categories, students, notes) for a set of matched roster records.

    Categories keep a stable order: each record's course then its CI.
    """
    cats, students, notes = [], [], []
    for r in records:
        course = course_category(r.get("CourseCode") or "")
        ci = ci_category(r.get("CourseMentor") or "")
        # Both slots always get a label; a blank roster value fills its
        # slot with Unassigned rather than going silent.
        for cat in (course or UNASSIGNED_CATEGORY, ci or UNASSIGNED_CATEGORY):
            if cat not in cats:
                cats.append(cat)
        if course and not ci:
            note = f"{course}: no CI assigned in roster"
            if note not in notes:
                notes.append(note)
        students.append({
            "student_id": (r.get("StudentID") or "").strip(),
            "name": (r.get("Name") or "").strip(),
            "course": course,
            "ci": (r.get("CourseMentor") or "").strip(),
        })
    return cats, students, notes


def triage(index: dict, sender_email: str, sender_name: str = "") -> dict:
    """Resolve one sender to the categories their mail should get.

    Returns::

        {"method": "email"|"name"|"none",
         "confident": bool,          # True only for email matches
         "categories": [str, ...],   # what would be applied
         "students": [{student_id, name, course, ci}, ...],
         "note": str}                # human-readable reason / flag

    Only ``confident`` results should ever be auto-applied with real
    course/CI categories; name matches are candidates for the human
    reviewing the dry-run log.
    """
    email = (sender_email or "").strip().lower()
    if email and email in index["by_email"]:
        cats, students, notes = _categories_for(index["by_email"][email])
        return {"method": METHOD_EMAIL, "confident": True,
                "categories": cats or [UNIDENTIFIED_CATEGORY],
                "students": students, "note": "; ".join(notes)}

    name = normalize_name(sender_name)
    if name and name in index["by_name"]:
        records = index["by_name"][name]
        ids = {(r.get("StudentID") or "").strip() for r in records}
        if len(ids) == 1:
            cats, students, notes = _categories_for(records)
            notes.insert(0, "name match only (sender email not in roster)"
                            " — review before trusting")
            return {"method": METHOD_NAME, "confident": False,
                    "categories": cats or [UNIDENTIFIED_CATEGORY],
                    "students": students, "note": "; ".join(notes)}
        return {"method": METHOD_NONE, "confident": False,
                "categories": [UNIDENTIFIED_CATEGORY], "students": [],
                "note": f"ambiguous name match ({len(ids)} students named"
                        f" '{sender_name.strip()}') — not guessing"}

    return {"method": METHOD_NONE, "confident": False,
            "categories": [UNIDENTIFIED_CATEGORY], "students": [],
            "note": "sender not in roster"}


def triage_many(index: dict, addrs: list) -> dict:
    """Triage a message by a SET of addresses — for SENT mail, where the
    student is a recipient, not the sender. `addrs` = [(email, name), ...]
    (To + CC).

    Any confident (email) match wins: the result is the union of every
    matched student's categories, and unmatched co-recipients (the CI
    themselves, staff) are simply ignored. With no email match, a unique
    name match is surfaced flagged, same as `triage()`. Nothing at all →
    ``Unidentified``.
    """
    results = [triage(index, e, n) for e, n in addrs]

    for want in (METHOD_EMAIL, METHOD_NAME):
        hits = [r for r in results if r["method"] == want]
        if not hits:
            continue
        cats, students, notes = [], [], []
        for r in hits:
            for c in r["categories"]:
                if c not in cats:
                    cats.append(c)
            students.extend(r["students"])
            if r["note"] and r["note"] not in notes:
                notes.append(r["note"])
        return {"method": want, "confident": want == METHOD_EMAIL,
                "categories": cats, "students": students,
                "note": "; ".join(notes)}

    return {"method": METHOD_NONE, "confident": False,
            "categories": [UNIDENTIFIED_CATEGORY], "students": [],
            "note": "no recipient in roster"}
