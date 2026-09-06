"""Export a full CSV backup of the local caseload history.

Motivation: colleagues report Salesforce inconsistencies ahead of a system
migration, so this dumps the app's OWN local record — which is richer and, for
departed/passed students, more complete than the live caseload (WGU's export
drops passers; this history keeps their last-known state).

Writes to ``backups/`` (gitignored):
  - ``caseload_backup_<stamp>.csv``   — the last-known snapshot for every
    (student, course) the app has ever tracked, rebuilt to the full ~105
    columns, tagged with whether they're still on the caseload and their
    outcome (Active / Passed / Left).
  - ``caseload_outcomes_<stamp>.csv`` — the passed-students archive (the
    ``outcomes`` table), which the live caseload no longer shows.

Read-only against ``history.db`` (safe to run while the app is open). The
output contains student PII (names, IDs, emails, etc.) in PLAINTEXT — it is
deliberately OUTSIDE the app's at-rest encryption, so store it securely.

Run:  .venv\\Scripts\\python.exe scripts\\export_caseload_backup.py
"""
import csv
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import HISTORY_DB, PROJECT_ROOT  # noqa: E402
from src import history as H  # noqa: E402


def _ro_connect(db_path) -> sqlite3.Connection:
    """Open history.db read-only so a concurrent running app is never disturbed;
    a short busy timeout rides out the app's brief commit locks."""
    uri = "file:" + Path(db_path).as_posix() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=8000")
    return conn


def export_caseload(conn: sqlite3.Connection):
    """(rows, current_count): last-known snapshot per (student, course), each
    rebuilt to full CSV-header columns + backup metadata columns."""
    snaps = conn.execute(
        "SELECT s.* FROM snapshots s JOIN ("
        "  SELECT student_id, course_code, MAX(collected_at) AS mx "
        "  FROM snapshots GROUP BY student_id, course_code) L "
        "ON s.student_id = L.student_id AND s.course_code = L.course_code "
        "AND s.collected_at = L.mx"
    ).fetchall()

    latest = conn.execute(
        "SELECT collected_at FROM collections "
        "ORDER BY collected_at DESC LIMIT 1"
    ).fetchone()
    current = set()
    if latest is not None:
        current = {
            (r["student_id"], r["course_code"]) for r in conn.execute(
                "SELECT student_id, course_code FROM snapshots "
                "WHERE collected_at = ?", (latest["collected_at"],))}

    outcomes = {
        (r["student_id"], r["course_code"]): r for r in conn.execute(
            "SELECT student_id, course_code, outcome, pass_date FROM outcomes")}

    rows = []
    for r in snaps:
        row = H._snapshot_to_viewer_row(r)
        key = (r["student_id"], r["course_code"])
        on_caseload = key in current
        oc = outcomes.get(key)
        if oc and (oc["outcome"] or "").strip() == "passed":
            outcome = ("Passed " + (oc["pass_date"] or "")).strip()
        elif (r["latest_task_status"] or "").strip() == "Passed":
            outcome = "Passed"
        elif on_caseload:
            outcome = "Active"
        else:
            outcome = "Left"
        # Backup metadata first so it lands in the leftmost columns.
        rows.append({
            "_LastSeen": r["collected_date"] or "",
            "_OnCaseload": "yes" if on_caseload else "no",
            "_Outcome": outcome,
            **row,
        })
    return rows, len(current)


def export_outcomes(conn: sqlite3.Connection):
    """The passed-students archive, extra_json flattened into columns."""
    rows = []
    for r in conn.execute("SELECT * FROM outcomes").fetchall():
        d = {k: r[k] for k in r.keys() if k != "extra_json"}
        try:
            extra = json.loads(r["extra_json"] or "{}")
            if isinstance(extra, dict):
                for k, v in extra.items():
                    d.setdefault(k, v)
        except Exception:
            pass
        rows.append(d)
    return rows


def _write_csv(path: Path, rows: list) -> int:
    """Write rows to CSV with a union-of-keys header (first-seen order).
    utf-8-sig so Excel opens it cleanly. Returns the row count."""
    if not rows:
        return 0
    fieldnames, seen = [], set()
    for row in rows:
        for k in row:
            if k not in seen:
                seen.add(k)
                fieldnames.append(k)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main() -> None:
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    out_dir = PROJECT_ROOT / "backups"
    out_dir.mkdir(exist_ok=True)

    if not Path(HISTORY_DB).exists():
        print(f"No history DB at {HISTORY_DB} — nothing to back up. "
              "(Is the app unlocked? While locked it lives as history.db.enc.)")
        return

    conn = _ro_connect(HISTORY_DB)
    try:
        caseload, current_count = export_caseload(conn)
        outcomes = export_outcomes(conn)
    finally:
        conn.close()

    cl_path = out_dir / f"caseload_backup_{stamp}.csv"
    oc_path = out_dir / f"caseload_outcomes_{stamp}.csv"
    n_cl = _write_csv(cl_path, caseload)
    n_oc = _write_csv(oc_path, outcomes)
    archived = sum(1 for r in caseload if r.get("_OnCaseload") == "no")

    print(f"Caseload backup: {n_cl} student-course records "
          f"({current_count} currently on caseload, {archived} archived/departed)")
    print(f"  -> {cl_path}")
    print(f"Passers archive: {n_oc} records")
    print(f"  -> {oc_path}")
    print()
    print("These CSVs hold student PII (FERPA) in PLAINTEXT and are NOT "
          "encrypted.\nStore them somewhere safe; backups/ is gitignored.")


if __name__ == "__main__":
    main()
