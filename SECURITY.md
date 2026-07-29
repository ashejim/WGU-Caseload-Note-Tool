# Security & Privacy

CaseloadNotes is a **client-side Windows desktop tool**. It runs entirely on the
operator's own machine, under the operator's own login. There is no server, no
hosted account, and no telemetry — nothing is transmitted to the author or any
third party.

## Credentials and access

- **The app stores no credentials, and neither does this repository.** The
  operator signs in to Salesforce (and, if used, Mongoose) themselves, in a real
  browser window, using WGU's normal **SSO + MFA**.
- The resulting authenticated session is persisted only in a local
  `browser_data/` directory on the operator's PC. It is never committed, never
  uploaded, and never leaves the machine.
- Because access to WGU systems is always gated by the operator's own SSO and
  MFA, possession of this source code grants **no access to any account or data**.
  A copy of the code cannot sign in on anyone's behalf.

## Student data (FERPA)

- All student data the tool touches — caseload exports, notes, texting contacts,
  and history snapshots — is read from and written to the **operator's local
  machine only**.
- These artifacts are excluded from version control by `.gitignore` (caseload
  CSVs, `*.db`/history, Mongoose segment/contact exports, network captures, DOM
  dumps, and the encrypted vault). No student records have ever been committed to
  this repository.
- Local PII files can additionally be **encrypted at rest** behind an app
  password; the key is sealed with Windows DPAPI. See `src/crypto_store.py`.

## What is in this repository

Application source code, tests, documentation, and sample/template assets only.
There are **no credentials, session tokens, API keys, or student records** in the
tree or in its git history. Internal endpoint URLs (e.g. the Salesforce org and
vendor hosts the tool drives) appear in the code as configuration; they are not
secrets and confer no access without a valid authenticated session.

## Reporting a concern

If you believe you have found a security or privacy issue, please open a private
report to the repository owner rather than a public issue.
