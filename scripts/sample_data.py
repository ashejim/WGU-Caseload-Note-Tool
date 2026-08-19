"""Synthetic caseload generator for the offline demo (see scripts/demo.py).

Everything here is FAKE — invented names, 9-digit ids starting 9000…, 555-01xx
phones, example.edu emails. No real student data, ever (FERPA). It exists so a
contributor can run the whole tool — viewer, student info, Data/Risk views,
momentum, contact prefs, pronouns — with NO Salesforce/Mongoose login.

`build(dest)` writes into `dest`:
  * caseload.csv   — the current roster (rich columns, matches the live grid feed)
  * history.db     — 8 weekly momentum snapshots (trajectories) + resolved
                     outcomes + a few contact notes, seeded via the real
                     history.py APIs so the schema is always correct.

Run standalone to (re)generate the committed, browsable copy:
    python -m scripts.sample_data                # -> sample_data/
"""

from __future__ import annotations

import csv
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Import the real history module so snapshots/outcomes are written through the
# same code the app uses (guarantees schema + momentum-rank correctness).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import history  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "sample_data"

# Weeks of momentum history to seed (0 = today). More weeks = smoother
# trajectories for the risk model to average over.
WEEKS = 8

_RANK_LABEL = {1: "Low", 2: "Med Low", 3: "Med", 4: "Med High", 5: "High"}

# Momentum trajectories (one rank per week, oldest -> newest). The risk model
# averages these; the mix gives the calibration buckets both passers and not.
_TRENDS = {
    "climbing":   [2, 2, 3, 3, 3, 4, 4, 5],
    "sliding":    [4, 4, 3, 3, 2, 2, 1, 1],
    "steady_low": [2, 1, 2, 2, 1, 2, 1, 2],
    "steady_mid": [3, 3, 3, 3, 3, 3, 3, 3],
    "steady_high": [4, 5, 4, 4, 5, 4, 5, 4],
    "stalled":    [1, 1, 1, 1, 1, 1, 1, 1],
}

# Three courses the tool actually targets (codes only — no real content).
_COURSES = {
    "C769": "Scripting and Programming — Applications",
    "D502": "Data Management — Applications",
    "C964": "Data-Driven Decision Making",
}
_MENTORS = [
    ("Dana Rivera", "drivera@example.edu", "555-0142"),
    ("Sam Okafor", "sokafor@example.edu", "555-0158"),
]
_TZS = ["EST", "CST", "MST", "PST"]

_FIRST = [
    "Avery", "Bella", "Carlos", "Divya", "Eli", "Farah", "Gabe", "Hana",
    "Ivan", "Jamie", "Kira", "Leo", "Mona", "Nate", "Priya", "Quinn",
    "Rosa", "Sven", "Tara", "Umar", "Vera", "Wes", "Xena", "Yusuf", "Zoe",
    "Aiden", "Bianca", "Cody", "Dora", "Emin", "Fiona", "Grant", "Halle",
    "Ismael", "June", "Kofi", "Lena", "Milo", "Nadia", "Oscar",
]
_LAST = [
    "Adams", "Boyd", "Cruz", "Diaz", "Egan", "Ford", "Gill", "Hume",
    "Iqbal", "Jones", "Kerr", "Long", "Mora", "Nash", "Ortiz", "Pace",
    "Reed", "Shah", "Tran", "Ueda", "Vance", "Ward", "Xu", "York", "Zane",
    "Ali", "Barr", "Chen", "Dunn", "Ellis", "Frost", "Gomez", "Hart",
    "Ide", "Kane", "Lowe", "Mensah", "Novak", "Park", "Quill",
]


def _make_students(rng: random.Random) -> list[dict]:
    """Build the fake roster. ~16 LIVE (in the caseload + still snapshotting) and
    ~24 DEPARTED (resolved with an outcome — they power the risk calibration)."""
    students = []
    trends = list(_TRENDS)
    for i in range(40):
        sid = f"9{i + 1:08d}"                      # 900000001, 900000002, …
        first, last = _FIRST[i], _LAST[i]
        course = list(_COURSES)[i % 3]
        mentor = _MENTORS[i % 2]
        trend = trends[i % len(trends)]
        traj = _TRENDS[trend]
        live = i < 16
        # Departed students left 1–5 weeks ago; live students are still here.
        exit_week = 0 if live else rng.randint(1, 5)
        opted_in = rng.random() < 0.6
        students.append({
            "sid": sid,
            "name": f"{first} {last}",
            "first": first,
            "course": course,
            "mentor": mentor,
            "tz": _TZS[i % 4],
            "email": f"{first.lower()}.{last.lower()}@example.edu",
            "mobile": f"555-01{(i % 90) + 10:02d}",
            "opted_in": opted_in,
            "trend": trend,
            "traj": traj,
            "live": live,
            "exit_week": exit_week,
            "start_days_ago": rng.randint(20, 75),
        })
    return students


def _rank_at(stu: dict, weeks_ago: int) -> int:
    """Momentum rank this student had `weeks_ago` weeks back (clamped)."""
    idx = (WEEKS - 1) - weeks_ago
    idx = max(0, min(len(stu["traj"]) - 1, idx))
    return stu["traj"][idx]


def _row(stu: dict, when: datetime, weeks_ago: int) -> dict:
    """A caseload-shaped row (real grid field names) for `stu` as of `when`."""
    rank = _rank_at(stu, weeks_ago)
    start = (when - timedelta(days=stu["start_days_ago"])).date().isoformat()
    term_end = (when + timedelta(days=40)).date().isoformat()
    last_contact = (when - timedelta(days=(weeks_ago * 7) % 11 + 2)).date().isoformat()
    # Tasks progress a little as momentum climbs (purely cosmetic for the badges).
    done = max(0, rank - 2)
    def task(n):
        return (f"{(when - timedelta(days=14 - n * 3)).date().isoformat()} (1)"
                if n <= done else "")
    return {
        "StudentID": stu["sid"],
        "Name": stu["name"],
        "stuprename": "",
        "CourseCode": stu["course"],
        "CourseTitle": _COURSES[stu["course"]],
        "CourseStatus": "Registered",
        "StudentStatus": "Active",
        "AcademicStanding": "Good",
        "Momentum": _RANK_LABEL[rank],
        "MentorName": stu["mentor"][0],
        "CourseMentor": stu["mentor"][0],
        "MentorEmail": stu["mentor"][1],
        "MobilePhone": stu["mobile"],
        "StudentEmail": stu["email"],
        "Timezone": stu["tz"],
        "CourseStartDate": start,
        "TermEndDate": term_end,
        "TermDaysLeft": "40",
        "Icenddate": "",
        "MyCourseContact": last_contact,
        "DaysSinceLastCourseContact": str((when.date()
                                           - datetime.fromisoformat(last_contact).date()).days),
        "CourseFollowupDate": "",
        "CourseFollowupNote": ("Checking in on pace." if rank <= 2 else ""),
        "LatestCourseNote": ("Left a voicemail." if rank <= 2 else "Making progress."),
        "TextingPreference": "Opted In" if stu["opted_in"] else "",
        "PlannedGraduationDate": (when + timedelta(days=180)).date().isoformat(),
        "LastAcademicActivityDate": last_contact,
        "OtherCourses": stu["course"],
        "weeksincourse": str(max(1, stu["start_days_ago"] // 7)),
        "Task1": task(1),
        "Task2": task(2),
        "Task3": task(3),
    }


# Column order for the written caseload.csv (StudentID + CourseCode first, as the
# app keys on them; the rest are the rich info-view fields).
_CSV_COLS = [
    "StudentID", "Name", "CourseCode", "CourseTitle", "CourseStatus",
    "StudentStatus", "AcademicStanding", "Momentum", "MentorName",
    "CourseMentor", "MentorEmail", "MobilePhone", "StudentEmail", "Timezone",
    "CourseStartDate", "TermEndDate", "TermDaysLeft", "Icenddate",
    "MyCourseContact", "DaysSinceLastCourseContact", "CourseFollowupDate",
    "CourseFollowupNote", "LatestCourseNote", "TextingPreference",
    "PlannedGraduationDate", "LastAcademicActivityDate", "OtherCourses",
    "weeksincourse", "stuprename", "Task1", "Task2", "Task3",
]


def _write_caseload_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_CSV_COLS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _seed_notes(db_path: Path, students: list[dict], now: datetime) -> None:
    """Seed a few contact notes for the first handful of LIVE students so the
    auto-inferred contact preference has something to work with (inbound events
    = the channel the student chose)."""
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    try:
        rows = []
        live = [s for s in students if s["live"]]
        # channel each of the first 6 live students engages on (round-robin).
        for i, s in enumerate(live[:6]):
            ch = ["text", "email", "call"][i % 3]
            for j in range(2):                     # 2 outbound
                t = (now - timedelta(days=6 - j)).isoformat(timespec="seconds")
                rows.append((f"{s['sid']}-o{j}", s["sid"], "", s["course"],
                             "Text" if ch == "text" else "Email", ch, "outbound",
                             t, "You", "", "reaching out", "", t, t))
            for j in range(2 if ch != "call" else 1):   # inbound (calls: 1)
                t = (now - timedelta(days=5 - j)).isoformat(timespec="seconds")
                rows.append((f"{s['sid']}-i{j}", s["sid"], "", s["course"],
                             "Text" if ch == "text" else "Email", ch,
                             "inbound", t, s["name"], "", "thanks!", "", t, t))
        conn.executemany(
            "INSERT OR REPLACE INTO notes (note_id, student_id, contact_id, "
            "course_code, type, channel, direction, created_at, author, subject, "
            "body, url, first_seen_at, last_seen_at) VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        conn.commit()
    finally:
        conn.close()


def build(dest, *, seed: int = 42) -> dict:
    """Generate caseload.csv + history.db into `dest`. Returns a small summary."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    db_path = dest / "history.db"
    if db_path.exists():
        db_path.unlink()                           # rebuild clean

    rng = random.Random(seed)
    students = _make_students(rng)
    now = datetime.now().replace(microsecond=0)

    # --- weekly momentum snapshots, oldest first so 'today' is the latest ---
    for weeks_ago in range(WEEKS - 1, -1, -1):
        when = now - timedelta(days=weeks_ago * 7)
        present = [s for s in students
                   if s["live"] or weeks_ago >= s["exit_week"]]
        rows = [_row(s, when, weeks_ago) for s in present]
        # A distinct csv_mtime per week so record_snapshot treats each as fresh.
        history.record_snapshot(rows, when, db_path=db_path, now=when,
                                note="demo seed")

    # --- resolved outcomes for the departed (drives risk calibration) ---
    departed = [s for s in students if not s["live"]]
    out_csv = dest / "sample_outcomes.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["StudentID", "CourseCode", "Name", "StudentEmail",
                    "Momentum", "CourseStatus", "LatestTaskStatus"])
        for s in departed:
            final = _rank_at(s, s["exit_week"])
            # Lower momentum -> more likely not to pass (with noise), so the
            # calibration curve slopes the way the real one does.
            p_pass = {1: 0.15, 2: 0.35, 3: 0.6, 4: 0.85, 5: 0.95}[final]
            passed = rng.random() < p_pass
            w.writerow([s["sid"], s["course"], s["name"], s["email"],
                        _RANK_LABEL[final],
                        "Passed" if passed else "Not Passed",
                        "Passed" if passed else "Returned"])
    history.ingest_outcomes_csv(out_csv, db_path=db_path, now=now)

    # --- a few contact notes so contact-preference auto-inference has data ---
    _seed_notes(db_path, students, now)

    # --- the current roster CSV (live students, today's snapshot) ---
    live_rows = [_row(s, now, 0) for s in students if s["live"]]
    _write_caseload_csv(dest / "caseload.csv", live_rows)

    return {"students": len(students), "live": len(live_rows),
            "departed": len(departed), "weeks": WEEKS, "dest": str(dest)}


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    summary = build(out)
    # Also drop a browsable copy of the roster that dodges the PII .gitignore
    # rules (so it can be committed and viewed on GitHub without cloning).
    src = Path(summary["dest"]) / "caseload.csv"
    (Path(summary["dest"]) / "sample_caseload.csv").write_bytes(src.read_bytes())
    print("Sample data written to", summary["dest"])
    print(f"  {summary['live']} live students, {summary['departed']} departed "
          f"(resolved), {summary['weeks']} weeks of momentum history.")


if __name__ == "__main__":
    main()
