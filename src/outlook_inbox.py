"""Read Outlook inboxes and apply categories via Win32 COM.

The inbox-reading counterpart to `outlook_email.py` (compose/send).
Non-destructive by design: never moves messages, never modifies
content, never sends. The only write this module performs is
`apply_categories()`, which merges category names into a message's
existing Categories and saves — Outlook categories are metadata, not
content.

Requires Outlook Classic (COM) — same constraint as sending; reuse
`outlook_email.classic_available()` / `OUTLOOK_CLASSIC_REQUIRED_MSG`
for the messaging. The shared team mailbox must be added/auto-mapped
in the user's Outlook profile to be reachable.

Sender SMTP: Exchange-internal senders report a legacy DN in
`SenderEmailAddress`, not SMTP — resolve through
`Sender.GetExchangeUser()` first, then the PR_SMTP_ADDRESS MAPI
property, and only then trust `SenderEmailAddress` (same dance as
`outlook_email.get_user_info()`).

Message identity: prefer the internet message id (PR_INTERNET_MESSAGE_ID)
over EntryID — EntryID changes when a message moves between folders,
the internet id doesn't. Fall back to a prefixed EntryID for items
that lack one (rare: some meeting/system items).

win32com is lazy-imported inside functions so this module imports fine
on Mac/Linux and in tests.
"""
from typing import Optional

# MAPI property tags (schema-URL form for PropertyAccessor).
PR_SMTP_ADDRESS = "http://schemas.microsoft.com/mapi/proptag/0x39FE001E"
PR_INTERNET_MESSAGE_ID = "http://schemas.microsoft.com/mapi/proptag/0x1035001E"

OL_FOLDER_INBOX = 6
OL_MAIL_ITEM_CLASS = 43  # OlObjectClass olMail


def _namespace():
    """Dispatch Outlook and return the MAPI namespace."""
    import win32com.client
    from pywintypes import com_error

    try:
        outlook = win32com.client.Dispatch("Outlook.Application")
        return outlook.GetNamespace("MAPI")
    except com_error as e:
        raise OSError(f"Couldn't reach Outlook via COM: {e}") from e


def _child(folders, name: str):
    """Case-insensitive lookup of a subfolder in a Folders collection.
    Returns None if absent (COM's indexed lookup raises instead)."""
    want = name.strip().lower()
    try:
        for f in folders:
            if (f.Name or "").strip().lower() == want:
                return f
    except Exception:
        pass
    return None


def open_inbox(mailbox_smtp: str = ""):
    """Return the Inbox MAPIFolder — the signed-in user's own inbox, or a
    shared mailbox's when `mailbox_smtp` is given (e.g. the team box).

    Shared access goes through `GetSharedDefaultFolder`, which needs the
    mailbox present/auto-mapped in the user's profile and the user to have
    at least Reviewer rights on its Inbox.

    Raises OSError with an actionable message if Outlook or the mailbox
    can't be reached.
    """
    from pywintypes import com_error

    ns = _namespace()

    if not mailbox_smtp:
        try:
            return ns.GetDefaultFolder(OL_FOLDER_INBOX)
        except com_error as e:
            raise OSError(f"Couldn't open the personal Inbox: {e}") from e

    try:
        recip = ns.CreateRecipient(mailbox_smtp)
        recip.Resolve()
        if not recip.Resolved:
            raise OSError(
                f"Outlook couldn't resolve mailbox '{mailbox_smtp}' — "
                "check the address and that it's visible to your account.")
        return ns.GetSharedDefaultFolder(recip, OL_FOLDER_INBOX)
    except OSError:
        raise
    except com_error as e:
        raise OSError(
            f"Couldn't open shared mailbox '{mailbox_smtp}': {e}\n"
            "It must be added/auto-mapped in your Outlook profile and "
            "your account needs read access to its Inbox.") from e


def open_folder(path: str, mailbox_smtp: str = ""):
    """Resolve a folder by name/path — mail rules file student mail into
    subfolders ('Students') and mounted shared mailboxes appear as their
    own top-level store ('UG Capstone IT'), so the default Inbox isn't
    always where the mail is.

    `path` segments split on '/' or '\\'. Resolution order:
      1. relative to the Inbox (personal, or `mailbox_smtp`'s when given)
         — so "Students" finds Inbox\\Students;
      2. relative to that mailbox's root — top-level folders that SIT
         BESIDE the Inbox (a rules-filed "Students" folder lives there);
      3. from the profile's store roots — so "UG Capstone IT/Inbox" (or
         any mounted mailbox's display name) works. A bare store name
         descends into that store's Inbox automatically.

    Names are matched case-insensitively. Raises OSError listing what
    was tried if nothing resolves.
    """
    import re

    segs = [s.strip() for s in re.split(r"[/\\]", path or "") if s.strip()]
    if not segs:
        return open_inbox(mailbox_smtp)

    def _walk(start, names):
        cur = start
        for s in names:
            cur = _child(cur.Folders, s)
            if cur is None:
                return None
        return cur

    tried = []
    try:
        inbox = open_inbox(mailbox_smtp)
        found = _walk(inbox, segs)
        if found is not None:
            return found
        tried.append(f"under the {'shared ' if mailbox_smtp else ''}Inbox")
        try:
            root = inbox.Parent
        except Exception:
            root = None
        if root is not None:
            found = _walk(root, segs)
            if found is not None:
                return found
            tried.append("beside it at the mailbox root")
    except OSError:
        tried.append("under the Inbox (couldn't open it)")

    ns = _namespace()
    root = _child(ns.Folders, segs[0])
    if root is not None:
        rest = segs[1:]
        store_inbox = _child(root.Folders, "Inbox")
        if not rest:
            # A bare store name ("UG Capstone IT") is the mailbox root,
            # which holds folders, not mail — use its Inbox.
            return store_inbox if store_inbox is not None else root
        found = _walk(root, rest)
        if found is not None:
            return found
        # "UG Capstone IT/Jeff" — subfolders usually live under the
        # store's Inbox; spare the user spelling out "/Inbox/".
        if store_inbox is not None:
            found = _walk(store_inbox, rest)
            if found is not None:
                return found
    tried.append("as a mailbox/store name in your profile")

    raise OSError(
        f"Couldn't find folder '{path}' ({'; '.join(tried)}).\n"
        "Run with --list-folders to see the folder names Outlook exposes.")


def list_folders(max_depth: int = 3) -> list:
    """All folders across the profile's stores as indented
    '  name (item count)' lines — diagnostics for picking a --folder path."""
    ns = _namespace()
    lines = []

    def walk(folder, depth):
        try:
            count = folder.Items.Count
        except Exception:
            count = "?"
        lines.append(f"{'  ' * depth}{folder.Name} ({count})")
        if depth >= max_depth:
            return
        try:
            children = list(folder.Folders)
        except Exception:
            children = []
        for ch in children:
            walk(ch, depth + 1)

    try:
        for store_root in ns.Folders:
            walk(store_root, 0)
    except Exception:
        pass
    return lines


def sender_smtp(msg) -> str:
    """Best-effort SMTP address of a message's sender.

    Exchange senders → GetExchangeUser().PrimarySmtpAddress, then the
    PR_SMTP_ADDRESS property, then raw SenderEmailAddress (which for
    internet mail already IS the SMTP address)."""
    try:
        if (getattr(msg, "SenderEmailType", "") or "").upper() == "EX":
            try:
                ex = msg.Sender.GetExchangeUser()
                if ex is not None:
                    addr = (ex.PrimarySmtpAddress or "").strip()
                    if addr:
                        return addr
            except Exception:
                pass
            try:
                addr = (msg.PropertyAccessor.GetProperty(PR_SMTP_ADDRESS)
                        or "").strip()
                if addr:
                    return addr
            except Exception:
                pass
        return (msg.SenderEmailAddress or "").strip()
    except Exception:
        return ""


def recipient_addrs(msg) -> list:
    """[(smtp, display name), ...] for a message's To/CC recipients —
    the identification handles for SENT mail, where the student is on
    the receiving end. Exchange recipients need the same
    GetExchangeUser()/PR_SMTP_ADDRESS resolution as senders."""
    out = []
    try:
        recipients = msg.Recipients
    except Exception:
        return out
    for r in recipients:
        name, addr = "", ""
        try:
            name = (r.Name or "").strip()
            addr = (r.Address or "").strip()
            entry = r.AddressEntry
            if (getattr(entry, "Type", "") or "").upper() == "EX":
                smtp = ""
                try:
                    ex = entry.GetExchangeUser()
                    if ex is not None:
                        smtp = (ex.PrimarySmtpAddress or "").strip()
                except Exception:
                    pass
                if not smtp:
                    try:
                        smtp = (entry.PropertyAccessor.GetProperty(
                            PR_SMTP_ADDRESS) or "").strip()
                    except Exception:
                        pass
                if smtp:
                    addr = smtp
        except Exception:
            pass
        if addr or name:
            out.append((addr, name))
    return out


def message_key(msg) -> str:
    """Stable identity for seen-state: the internet message id, else a
    prefixed EntryID."""
    try:
        mid = (msg.PropertyAccessor.GetProperty(PR_INTERNET_MESSAGE_ID)
               or "").strip()
        if mid:
            return mid
    except Exception:
        pass
    try:
        return "entryid:" + (msg.EntryID or "")
    except Exception:
        return ""


def iter_messages(folder, since=None, limit: Optional[int] = None):
    """Yield mail items in `folder`, newest first, as
    `(info_dict, com_item)` pairs.

    `since` (datetime, local time) restricts by ReceivedTime via an
    Outlook-side filter — cheap even on huge shared inboxes. Non-mail
    items (meeting requests, delivery reports) are skipped.

    info_dict: {subject, received (datetime or None), sender_name,
    sender_smtp, message_key, categories (str)}.
    """
    items = folder.Items
    items.Sort("[ReceivedTime]", True)
    if since is not None:
        # Outlook's Restrict wants a US-style local datetime string.
        items = items.Restrict(
            "[ReceivedTime] >= '%s'" % since.strftime("%m/%d/%Y %I:%M %p"))

    count = 0
    msg = items.GetFirst()
    while msg is not None:
        if limit is not None and count >= limit:
            return
        try:
            is_mail = msg.Class == OL_MAIL_ITEM_CLASS
        except Exception:
            is_mail = False
        if is_mail:
            try:
                received = msg.ReceivedTime
            except Exception:
                received = None
            info = {
                "subject": (getattr(msg, "Subject", "") or ""),
                "received": received,
                "sender_name": (getattr(msg, "SenderName", "") or ""),
                "sender_smtp": sender_smtp(msg),
                "to": (getattr(msg, "To", "") or ""),
                "message_key": message_key(msg),
                "categories": (getattr(msg, "Categories", "") or ""),
            }
            count += 1
            yield info, msg
        msg = items.GetNext()


def apply_categories(msg, categories: list, remove: list = None) -> bool:
    """Merge `categories` into the message's Categories and save.

    Case-insensitive merge — existing categories (including ones other
    people/rules set) are always preserved. `remove` is the narrow
    self-correction exception: category names to strip if present, used
    ONLY for the labeler's own placeholder markers (Unidentified /
    Unassigned) when a roster refresh upgrades a message to its real
    labels. Returns True if the message changed (and was saved).

    This is the labeler's ONLY write. Raises OSError if the save fails
    (e.g. read-only rights on a shared mailbox).
    """
    from pywintypes import com_error

    new_value = merge_categories(msg.Categories or "", categories, remove)
    if new_value is None:
        return False
    try:
        msg.Categories = new_value
        msg.Save()
    except com_error as e:
        raise OSError(f"Couldn't save categories: {e}") from e
    return True


def merge_categories(existing_str: str, categories: list,
                     remove: list = None):
    """Pure merge logic behind apply_categories: the new Categories
    string, or None when nothing would change (no save needed)."""
    existing = [c.strip() for c in (existing_str or "").split(",")
                if c.strip()]
    drop = {c.lower() for c in (remove or []) if c}
    kept = [c for c in existing if c.lower() not in drop]
    have = {c.lower() for c in kept}
    added = [c for c in categories if c and c.lower() not in have]
    if not added and len(kept) == len(existing):
        return None
    return ", ".join(kept + added)
