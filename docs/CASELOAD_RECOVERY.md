# Recovering caseload data from the Caseload Tool

If Salesforce loses or garbles data (or during the migration), the tool's local
history is a fallback copy of what it last saw: assigned instructor, last
contact dates, follow-ups, task progress, pass outcomes, and the full
contact-notes history — for **your own** caseload.

## Read this first (what it can and can't do)

1. **It's per person.** Your install only holds *your* caseload. Recovery is
   only as broad as who has been running the tool. Someone who never ran it
   has nothing to recover.
2. **Each person must export their own.** Local data is encrypted and sealed to
   your Windows account (DPAPI), so nobody can decrypt your file for you. Do the
   export yourself, on your machine, logged in as you.
3. **It's a copy, not the system of record.** Values are what the tool saw at
   the last snapshot. Verify before overwriting anything in Salesforce.
4. **Freshness = last snapshot.** Anything that changed in SF after your last
   run isn't captured, and nothing predates your first run.
5. **The files contain student PII (FERPA) in plaintext.** Treat them like a
   gradebook: access-controlled storage, encrypted transfer, delete working
   copies when done.

## A. Produce your backup

1. Open the Caseload Tool and **unlock it with your app password** (this
   decrypts your local history for the session).
2. Export the data to CSV:
   - **In-app (once the Export button ships):** Settings → Data →
     **Export caseload backup** → pick a folder.
   - **Dev checkout:** run
     `.venv\Scripts\python.exe scripts\export_caseload_backup.py`
     (files land in `backups\`).
3. You now have two files, datestamped:
   - `caseload_backup_<date>.csv` — every student the tool ever tracked, at
     their last-known state (current **and** departed).
   - `caseload_outcomes_<date>.csv` — students who **passed** (Salesforce drops
     these from the live caseload, so this is often the least-recoverable set).
4. Move both to a secure, access-controlled location.

## B. Use the backup to recover specific fields

5. Identify what SF lost (e.g. last assigned instructor, last contact date,
   follow-up note).
6. Open `caseload_backup_<date>.csv` and match rows by **StudentID**
   (+ **CourseCode** for students in more than one course). Key columns:
   - `CourseMentor`, `CourseMentorID`, `MentorEmail` — the **assigned
     instructor** (last known).
   - `LastSMContact`, `CourseContact`, `MyCourseContact`,
     `DaysSinceLastContact` — **last contact** timing.
   - `CourseFollowupDate`, `CourseFollowupNote` — follow-ups.
   - `LatestTaskStatus`, `Task1`..`Task3` — progress.
   - `contactID` — the Salesforce Contact record id (`003…`), for re-linking
     into a new system.
   - `_LastSeen`, `_OnCaseload`, `_Outcome` — when it was captured, whether the
     student is still on the caseload, and their outcome (Active / Passed /
     Left).
7. For students missing from SF because they finished, use
   `caseload_outcomes_<date>.csv` (pass dates) and the `_Outcome = Left/Passed`
   rows in the main file.
8. For the **content and timing of individual contacts** (who was contacted,
   when, inbound vs outbound, message text), that lives in the tool's `notes`
   history — richer than these CSVs. Ask the maintainer to export a notes CSV
   if you need that level of detail.

## C. Team-wide consolidation (optional)

9. Each colleague produces their two CSVs (section A) and sends them to one
   coordinator over a secure channel.
10. The coordinator merges and de-duplicates by StudentID + CourseCode into one
    recovery set.
11. Hand the consolidated set to whoever is fixing Salesforce / running the
    migration.
