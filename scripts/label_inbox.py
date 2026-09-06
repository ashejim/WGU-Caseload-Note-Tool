"""Inbox labeler runner — identify course + CI for incoming mail.

Reads an Outlook inbox (personal by default, or a shared mailbox via
--mailbox), resolves each sender against the CourseScan team roster,
and reports the Outlook categories each message should get (course code
+ ``CI: <last name>``; ``Unidentified`` for unknown senders).

DRY-RUN BY DEFAULT: prints and logs what it *would* assign, applies
nothing. Pass --apply only after the dry-run log has been eyeballed
for accuracy against real mail.

Apply policy (per the agreed matching policy in src/inbox_triage.py):
  - confident email matches   → course + CI categories applied
  - unmatched senders         → ``Unidentified`` applied (never silence)
  - name-only matches         → NOTHING applied; flagged in the log for
                                human review (too risky to guess)

Every decision is appended to a JSONL log (inbox_label_log.jsonl —
gitignored, contains student PII) which doubles as the accuracy-review
artifact for the dry-run milestone.

Examples:
    .venv/Scripts/python.exe scripts/label_inbox.py                # dry-run, personal, last 3 days
    .venv/Scripts/python.exe scripts/label_inbox.py --since 14
    .venv/Scripts/python.exe scripts/label_inbox.py --mailbox ugcapstoneit@wgu.edu
    .venv/Scripts/python.exe scripts/label_inbox.py --apply
"""
import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import inbox_triage  # noqa: E402
from src.config import USER_CONFIG_DIR  # noqa: E402

DEFAULT_ROSTER = USER_CONFIG_DIR / "coursescan_roster.json"
DEFAULT_LOG = USER_CONFIG_DIR / "inbox_label_log.jsonl"
DEFAULT_STATE = USER_CONFIG_DIR / "inbox_label_state.json"


def _load_state(path) -> dict:
    """Seen-message keys → ISO timestamp of when they were labeled."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_state(path, state: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=0)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Label Outlook inbox mail with course + CI categories "
                    "resolved from the CourseScan roster. Dry-run unless "
                    "--apply is passed.")
    ap.add_argument("--apply", action="store_true",
                    help="actually apply categories (default: dry-run — "
                         "print/log only)")
    ap.add_argument("--mailbox", default="",
                    help="SMTP address of a shared mailbox to read "
                         "(default: your own Inbox)")
    ap.add_argument("--folder", default="",
                    help="folder to read instead of the default Inbox — a "
                         "subfolder of the Inbox ('Students') or a mounted "
                         "mailbox's path ('UG Capstone IT/Inbox'; a bare "
                         "mailbox name uses its Inbox)")
    ap.add_argument("--list-folders", action="store_true",
                    help="print every folder Outlook exposes (with item "
                         "counts) and exit — for picking a --folder path")
    ap.add_argument("--match", choices=("sender", "recipients"),
                    default="sender",
                    help="who identifies the message: 'sender' for "
                         "received mail (default), 'recipients' for a "
                         "Sent folder, where the student is on the To/CC "
                         "line")
    ap.add_argument("--since", type=float, default=3, metavar="DAYS",
                    help="look back this many days (default: 3)")
    ap.add_argument("--limit", type=int, default=None, metavar="N",
                    help="stop after N messages (newest first)")
    ap.add_argument("--roster", default=str(DEFAULT_ROSTER),
                    help=f"path to coursescan_roster.json "
                         f"(default: {DEFAULT_ROSTER})")
    ap.add_argument("--log", default=str(DEFAULT_LOG),
                    help="JSONL decision log (default: "
                         "inbox_label_log.jsonl; PII — stays local)")
    ap.add_argument("--state", default=str(DEFAULT_STATE),
                    help="seen-message state file, consulted only with "
                         "--apply (dry runs always reprocess)")
    ap.add_argument("--rescan", action="store_true",
                    help="with --apply: ignore seen-state and reprocess "
                         "every message in the window")
    args = ap.parse_args()

    # Fail early with the canonical message if only "new Outlook" exists.
    from src import outlook_email, outlook_inbox
    if outlook_email.classic_available() is False:
        print(outlook_email.OUTLOOK_CLASSIC_REQUIRED_MSG)
        return 2

    if args.list_folders:
        for line in outlook_inbox.list_folders():
            print(line)
        return 0

    if not os.path.exists(args.roster):
        print(f"Roster not found: {args.roster}\n"
              "Run 'coursescan: capture' then 'coursescan: export' in the "
              "launcher first.")
        return 2
    roster = inbox_triage.load_roster(args.roster)
    index = inbox_triage.build_index(roster)
    print(f"Roster: {len(roster)} records, "
          f"{len(index['by_email'])} unique student emails "
          f"({os.path.basename(args.roster)})")

    since = dt.datetime.now() - dt.timedelta(days=args.since)
    box = args.folder or (args.mailbox or "(personal)") + " inbox"
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"{mode}: {box}, since {since:%Y-%m-%d %H:%M}"
          + (f", limit {args.limit}" if args.limit else ""))

    try:
        if args.folder:
            folder = outlook_inbox.open_folder(args.folder, args.mailbox)
        else:
            folder = outlook_inbox.open_inbox(args.mailbox)
    except OSError as e:
        print(f"\n{e}")
        return 2

    state = _load_state(args.state) if args.apply else {}
    counts = {"email": 0, "name": 0, "none": 0,
              "applied": 0, "skipped_seen": 0}
    now_iso = dt.datetime.now().isoformat(timespec="seconds")

    with open(args.log, "a", encoding="utf-8") as log:
        for info, msg in outlook_inbox.iter_messages(
                folder, since=since, limit=args.limit):
            key = info["message_key"]
            if args.apply and not args.rescan and key in state:
                counts["skipped_seen"] += 1
                continue

            if args.match == "recipients":
                addrs = outlook_inbox.recipient_addrs(msg)
                result = inbox_triage.triage_many(index, addrs)
                who = f"to {info['to']}"[:60]
            else:
                result = inbox_triage.triage(
                    index, info["sender_smtp"], info["sender_name"])
                who = f"{info['sender_name']} <{info['sender_smtp']}>"
            counts[result["method"]] += 1

            # Name matches are review candidates, not labels — apply
            # nothing (not even Unidentified, which would misfile a
            # probable student).
            to_apply = ([] if result["method"] == inbox_triage.METHOD_NAME
                        else result["categories"])
            applied = False
            if args.apply and to_apply:
                applied = outlook_inbox.apply_categories(msg, to_apply)
                if key:
                    state[key] = now_iso
                counts["applied"] += 1

            tag = {"email": "ok  ", "name": "NAME", "none": "----"}[
                result["method"]]
            recv = info["received"]
            recv_s = f"{recv:%m-%d %H:%M}" if recv else "?"
            print(f"[{tag}] {', '.join(result['categories']):<28} "
                  f"| {recv_s} | {who} | {info['subject'][:60]}"
                  + (f"  ({result['note']})" if result["note"] else ""))

            log.write(json.dumps({
                "ts": now_iso,
                "mailbox": args.folder or args.mailbox or "personal",
                "message_key": key,
                "received": str(recv) if recv else "",
                "sender_name": info["sender_name"],
                "sender_smtp": info["sender_smtp"],
                "to": info["to"],
                "match": args.match,
                "subject": info["subject"],
                "method": result["method"],
                "confident": result["confident"],
                "categories": result["categories"],
                "students": result["students"],
                "note": result["note"],
                "existing_categories": info["categories"],
                "applied": applied,
                "dry_run": not args.apply,
            }) + "\n")

    if args.apply:
        _save_state(args.state, state)

    total = counts["email"] + counts["name"] + counts["none"]
    print(f"\n{total} messages: {counts['email']} identified by email, "
          f"{counts['name']} name-only (review), "
          f"{counts['none']} unidentified"
          + (f"; {counts['applied']} labeled, "
             f"{counts['skipped_seen']} already seen" if args.apply
             else " -- dry run, nothing applied"))
    print(f"Decision log: {args.log}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
