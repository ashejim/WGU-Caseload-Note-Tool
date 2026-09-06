# Inbox Labeler — Task Handoff

Written 2026-08-30 in the `D:\chatbot` Claude Code session; this doc carries the
context over so a session in this repo can start building without re-deriving
the decisions. Read `CLAUDE_HANDOFF.md` first for general project orientation.

## Why this exists (origin)

The chatbot project (`D:\chatbot` — RAG bot answering C769 capstone questions
from a local Ollama KB) hit a deployment wall: WGU won't host it, students
prefer email anyway. New direction: an email agent. **Phase 1 is this task** —
a zero-risk inbox *labeler* that identifies course + course instructor for
incoming mail and applies Outlook categories. Phase 2 (later, in `D:\chatbot`
as `phase7_email_agent.py`) adds bot-drafted replies for trained courses and
will **import the inbox-reading module built here**.

Full background: `D:\chatbot\CLAUDE.md` and the chatbot session's memory file
`project_email_agent_pivot.md` (under
`C:\Users\ashej\.claude\projects\D--chatbot\memory\`).

## Decisions already made with the user (do not re-litigate)

1. **Labeling = named Outlook categories** (scheme A), two per email:
   - a **course category** — the course code, e.g. `C769`. Team courses to
     cover (user, 2026-09-01): C769, C964, D342, D502, D424. (C868 dropped —
     retired; D370 dropped — it has its own inbox.)
   - an **instructor category** — the CI's FIRST name: `Tawnya`, `Jeff`,
     `Jim`, `Candice`, `Charlie`, `Emily` (user, 2026-08-30 — matches the
     team's existing folder/category naming; supersedes the original
     `CI: <last name>` scheme).
   The category *name* is the label; color is cosmetic. Folders/subject-tags
   were considered and rejected (single-dimension / mail-mutating).
2. **Dry-run milestone first**: the labeler reads mail, resolves senders, and
   *prints* what it would assign — applies nothing — until the user has
   eyeballed accuracy against real mail.
3. **Personal inbox first** (user validates), then the team shared box
   (`ugcapstoneit@wgu.edu`, ~12 courses).
4. **Zero IT approval**: Outlook COM under the user's own login, like
   everything else in this project. Graph API deferred (needs tenant app
   registration).
5. Non-destructive always: never move, never modify content, never send.
   Unmatched senders get an `Unidentified` category (or similar), not silence.
6. **Team-box scope = top-level Inbox only** (decided 2026-08-30): the per-CI
   subfolders under the `UG Capstone IT` Inbox (Jim Ashe, Jeff, Tawnya Lee,
   Charlie Paddock, Candice Allen, …) are each team member's own space —
   the labeler must never read or label inside them. Once a message is filed
   there it's that CI's to manage. (The labeler is single-folder,
   non-recursive by design, so this holds automatically.)

## What already exists in this repo (2026-08-30 review)

- `src/outlook_email.py` — COM compose/send. **No inbox-reading code exists
  anywhere yet** — that's the new capability. Reuse its hard-won patterns:
  `classic_available()` registry probe (new Outlook has NO COM automation),
  Exchange SMTP resolution via `GetExchangeUser()`, COM warm-up retry in
  `is_ready()`.
- `coursescan_roster.json` (repo root) — **the identification database**.
  1,141 student records with `StudentEmail`, `CourseCode`, `CourseMentor`
  (+ CI email in `CourseMentorUrl`, phone), `StudentID`, task statuses.
  Whole-course rosters, not just the user's caseload: C769 has 1,083 students
  across 5 CIs (Ashe, Paddock, Allen, Lee, Davis). Coverage today:
  C769 / D502 / C964. The other ~9 team-box courses need CourseScan runs (a
  data refresh, not new code) — until then their senders land in
  `Unidentified`.
- Conventions to follow (see `ARCHITECTURE.md`): small single-purpose `src/`
  modules with docstrings; tests are standalone scripts (NOT pytest) printing
  `N/N passed`; PII encrypted at rest (`crypto_store.py`) — note the roster
  contains student PII.

## Proposed shape

- `src/outlook_inbox.py` — COM inbox access: enumerate recent/unseen messages
  (personal or shared mailbox via `GetSharedDefaultFolder` /
  `Session.Folders`), read sender SMTP (Exchange senders need the
  `GetExchangeUser()` dance), apply categories, seen-message state. For state
  IDs prefer the internet message id / a stable key over `EntryID` semantics.
- `src/inbox_triage.py` — pure logic, unit-tested: roster load + sender email
  → student → course → CI → category names. Handle: students emailing from
  personal (non-WGU) addresses (roster `StudentEmail` may be either), name
  fallback matching (risky — flag, don't guess), multiple courses per student
  (label all, or prefer the course whose CI is on this team).
- `scripts/label_inbox.py` (or similar) — runner: `--dry-run` (default at
  first), `--mailbox`, `--since`, poll loop later.
- Log every decision to a JSONL (matched/unmatched, categories assigned) —
  this doubles as the accuracy-review artifact for the dry-run milestone.

## Gotchas queued up

- **Shared-mailbox category colors**: custom categories live in each mailbox's
  master category list. For colors to render for teammates, the category set
  must be created in the *shared* mailbox (one-time manual seeding — 5 min,
  no code — by anyone with access). Colorless text labels still filter/sort
  fine everywhere, including new Outlook and mobile.
- **Outlook Classic required** on the machine running the agent (COM). The
  existing `OUTLOOK_CLASSIC_REQUIRED_MSG` / probe covers the messaging.
- Shared mailbox must be added/auto-mapped in the user's Outlook profile to be
  reachable via COM.
- Machine must not sleep for unattended runs; Scheduled Task at logon +
  watchdog is the pattern (the chatbot repo's `tunnel_with_restart.ps1` has
  reusable SMTP-alert plumbing for "needs re-auth" notifications).

## Roadmap after the labeler (for context, not this task)

Draft-first bot replies for trained courses (C769 now): three response modes —
answer (routine + retrieval-confident, clearly labeled automated, never posing
as faculty), acknowledge-and-defer (OOO-style receipt for grades / extensions
/ accommodations / personal circumstances), silent + flag. Confidence-gated
auto-send only after the draft-first data supports it.
