# IMAP Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One-off import of past mail from chosen IMAP folders of an Email Account, with an address review step, as Closed Communications.

**Architecture:** Four new DocTypes hold one run (*Mail Import*), its scanned mails (*Mail Import Message*), its unknown addresses (*Mail Import Address*) and the site-wide ignore list (*Mail Ignored Address*). Plain modules in `mailsync/backfill/` do the work in resumable background jobs: scan headers → build the address list → import mails with a known Contact. CRM knowledge comes in through hooks.

**Tech Stack:** Frappe v16, Python 3.14, `imaplib`, Frappe `IntegrationTestCase`, GreenMail for the real-server test.

**Spec:** `docs/superpowers/specs/2026-10-28-imap-backfill-design.md`

## Global Constraints

- Never write to the mailbox: folders are selected with `readonly=True`, only `BODY.PEEK` fetches, no `STORE`/`COPY`/`MOVE`/`EXPUNGE`/`APPEND`.
- Max 25 MB per mail (`sent_mail.MAX_MAIL_BYTES`), max 100 MB and 50 mails per fetch batch (`sent_mail.MAX_BATCH_BYTES`, `sent_mail.BATCH`).
- Code, README, commit messages in English; every `_("…")` string in `.py` files gets a German row in `mailsync/translations/de.csv` (enforced by `test_translations.py`). DocType labels and JS strings get German rows too.
- Style: tabs, ruff 0.14.10 (`ruff check . && ruff format --check .`), few comments, match `sent_mail.py`.
- Imports are allowed for any IMAP Email Account (incoming on or off), not POP3 / Frappe Mail.
- Only System Managers and users with the account in their *User Emails* may create, read or run an import.
- Tests run in the dev bench: `docker compose -f <scratchpad>/dev/compose.yaml exec -T bench bash -lc "cd frappe-bench && bench --site mailsync.test run-tests --app mailsync --module <module>"`.

## Review Focus

- Mail without Message-ID: cannot be deduplicated by id; import it once per run (state on the message row), never as "Present". Test in Task 5.
- Address case and display names (`"Doe, Jane" <Jane@X.com>`): addresses are compared lowercased and parsed with `parse_addr`; a comma inside a quoted name must not split it. Test in Task 3.
- A mail whose only other participants are own addresses (mail to self): Filtered, never stays Pending forever. Test in Task 5.
- Email Account with *Create Contact* on: importing must not create contacts. Test in Task 5.
- UIDVALIDITY change between scan and import: the folder's pending rows are not imported from wrong UIDs; the run reports it and a new scan fixes it. Test in Task 5.

---

### Task 1: DocTypes and access rules

**Files:**
- Create: `mailsync/mailsync/doctype/{mail_import,mail_import_folder,mail_import_message,mail_import_address,mail_ignored_address}/` (`__init__.py`, `<name>.json`, `<name>.py`)
- Create: `mailsync/backfill/__init__.py`, `mailsync/backfill/access.py`
- Modify: `mailsync/hooks.py`
- Test: `mailsync/tests/test_backfill_access.py`

DocTypes (module *Mailsync*, `track_changes` off, no `is_submittable`):

- **Mail Import** (autoname `hash`, title field `email_account`): `email_account` Link Email Account reqd; `from_date`, `to_date` Date; `folders` Table *Mail Import Folder*; read-only: `status` Select `Draft\nScanning\nReview\nImporting\nDone\nFailed` default Draft, `error` Small Text, counters Int `total, pending, present, imported, filtered, too_large, failed`.
- **Mail Import Folder** (istable): `folder` Data reqd, `uidvalidity` Int, `scanned_uid` Int, `scan_done` Check.
- **Mail Import Message**: `mail_import` Link reqd (in standard filter), `folder` Data, `uidvalidity` Int, `uid` Int, `message_id` Data, `mail_date` Datetime, `subject` Data, `sender` Data, `participants` Small Text (newline-separated, lowercased, own addresses removed), `outgoing` Check, `size` Int, `state` Select `Pending\nPresent\nImported\nFiltered\nToo Large\nFailed`, `communication` Link Communication, `error` Small Text.
- **Mail Import Address**: `mail_import` Link reqd, `email_id` Data reqd, `full_name` Data, `mail_count` Int, `subjects` Small Text, `decision` Select `Open\nContact\nIgnored` default Open, `contact` Link Contact, `suggested_contact` Link Contact, `first_name`, `last_name` Data, `link_doctype` Link DocType, `link_name` Dynamic Link on `link_doctype`.
- **Mail Ignored Address**: autoname `field:email_id`, `email_id` Data reqd unique.

DocPerms: System Manager (all) and *Desk User* (read, write, create; delete on Mail Import) on all five; row-level access comes from the hooks below.

**Interfaces:**
- Produces: `access.can_use_account(email_account: str, user: str | None = None) -> bool`; `access.has_permission(doc, ptype=None, user=None) -> bool` and `access.query_conditions(user=None) -> str` wired in `hooks.py` for Mail Import, Mail Import Message, Mail Import Address (the latter two through `mail_import`); `MailImport.validate` throws unless `can_use_account` and the account `use_imap`.

- [ ] **Step 1: Write the failing tests**: `test_assigned_user_sees_own_import` (user with a *User Emails* row for the account reads the import, its messages and addresses), `test_other_user_cannot_read_or_create` (`frappe.has_permission` False, insert raises `frappe.PermissionError`), `test_system_manager_sees_all`, `test_pop3_account_rejected` (validate throws for `use_imap=0`).
- [ ] **Step 2: Run, expect FAIL** (`--module mailsync.tests.test_backfill_access`).
- [ ] **Step 3: Create the DocTypes and `access.py`, wire `has_permission` / `permission_query_conditions` in `hooks.py`.** `can_use_account`: System Manager, or a `User Email` row with `parent=user, email_account=account`.
- [ ] **Step 4: Run, expect PASS.** Also `bench --site mailsync.test migrate` succeeds.
- [ ] **Step 5: Commit** `feat(import): add mail import doctypes and access rules`.

### Task 2: Address rules and hooks

**Files:**
- Create: `mailsync/backfill/addresses.py`
- Test: `mailsync/tests/test_backfill_addresses.py`

**Interfaces:**
- Produces:
  - `is_own(address: str) -> bool`: lowercased address is an Email Account `email_id`, an enabled System User's email, or any `mailsync_own_address` hook returns truthy. Cached per request in `frappe.local`.
  - `contact_for(address: str) -> str | None`: Contact via `Contact Email.email_id`.
  - `is_ignored(address: str) -> bool`.
  - `suggestion(address: str) -> dict`: merged results of `mailsync_address_suggestion` hooks, keys `contact`, `link_name`; errors logged, `{}` on failure.
  - `link_doctype() -> str | None`: last value of the `mailsync_contact_link_doctype` hook (a plain string hook, e.g. `"Organization"`).

- [ ] **Step 1: Failing tests**: `test_account_and_system_user_are_own`, `test_hook_marks_own` (via `factories.hooks`), `test_contact_found_case_insensitive`, `test_ignored`, `test_failing_suggestion_hook_is_logged_and_empty`, `test_link_doctype_from_hook`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** `feat(import): add address rules and extension hooks`.

### Task 3: Folder list and scan

**Files:**
- Create: `mailsync/backfill/mailbox.py`, `mailsync/backfill/scan.py`
- Create: `mailsync/tests/fake_mailbox.py` (fake IMAP with folders, UIDVALIDITY, `uid search` honouring `UID n:*`, `SENTSINCE`, `SENTBEFORE`, header and body fetch; any write command raises)
- Test: `mailsync/tests/test_backfill_scan.py`

**Interfaces:**
- Produces:
  - `mailbox.login(account_doc) -> EmailServer` (calls `tls.apply()`, sets `imap_timeout` like `sync_account`, `get_incoming_server(in_receive=True)`), `mailbox.folders(imap) -> list[str]` (reuses `mail_status.list_entry`, skips `\Noselect`), `mailbox.criteria(after_uid, from_date, to_date) -> str` (`UID {n}:* SENTSINCE 01-Jan-2020 SENTBEFORE <to_date+1>`).
  - `scan.scan(doc: MailImport, imap, deadline: float) -> bool` returns True when all folders are done. Per folder: `STATUS UIDVALIDITY`; on change from the stored value delete the folder's `Pending` rows and restart at UID 0. Fetch `(UID RFC822.SIZE BODY.PEEK[HEADER.FIELDS (FROM TO CC MESSAGE-ID DATE SUBJECT)])` in chunks of 200, insert one *Mail Import Message* per mail (skip if `(mail_import, folder, uidvalidity, uid)` exists), save `scanned_uid` and commit after each chunk, stop when `time.monotonic() > deadline`.
  - Row state at scan: `Too Large` over 25 MB, `Present` when `SentMail`'s known-rule matches (move `is_known` to a module function `sent_mail.known(message_id) -> bool` and use it in both), else `Pending`. `outgoing` = sender `is_own`. `participants` = From/To/Cc minus own, via `sent_mail.addresses`.

- [ ] **Step 1: Failing tests**: `test_folders_listed_without_noselect`, `test_scan_records_headers_and_participants` (display name with comma, upper-case address), `test_scan_marks_present_and_too_large`, `test_scan_respects_date_range`, `test_scan_resumes_after_deadline` (deadline in the past after first chunk → second call continues, no duplicates), `test_uidvalidity_change_rescans`, `test_mailbox_never_written` (fake raises on writes; all selects read-only).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS**, plus `test_sent_mail` still passes after the `known` refactor.
- [ ] **Step 5: Commit** `feat(import): list folders and scan headers`.

### Task 4: Address review

**Files:**
- Create: `mailsync/backfill/review.py`
- Modify: `mail_import_address.py` (whitelisted actions), `mail_import_address.js` (form buttons), `mail_import_address_list.js` (bulk *Ignore*)
- Test: `mailsync/tests/test_backfill_review.py`

**Interfaces:**
- Produces:
  - `review.refresh(doc: MailImport) -> None`: rebuilds Open address rows from Pending messages: participant addresses with no Contact and not ignored, `mail_count`, up to 3 `subjects`, `full_name` from headers, `first_name`/`last_name` split from it, `suggested_contact`/`link_name` from `addresses.suggestion`, `link_doctype` from `addresses.link_doctype()`. Rows with a decision are kept.
  - Whitelisted on *Mail Import Address* (normal permissions, so the user's Contact rights apply): `create_contact()` inserts a Contact with `first_name`, `last_name`, the address as primary email and a Dynamic Link `link_doctype`/`link_name` when both set → `decision=Contact`, `contact` set; `add_to_contact(contact)` appends the address to that Contact → `decision=Contact`; `ignore()` inserts *Mail Ignored Address* → `decision=Ignored`. `mailsync.backfill.review.ignore_many(names: list[str])` for the list view.

- [ ] **Step 1: Failing tests**: `test_refresh_lists_unknown_only` (Contact address and ignored address absent, own absent), `test_refresh_keeps_decisions`, `test_create_contact_with_company_link`, `test_add_to_existing_contact`, `test_ignore_is_site_wide` (second import's refresh does not list it), `test_suggestion_prefilled`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** `feat(import): review unknown addresses`.

### Task 5: Import

**Files:**
- Create: `mailsync/backfill/importer.py`
- Test: `mailsync/tests/test_backfill_import.py`

**Interfaces:**
- Consumes: `sent_mail.SentMail`, `sent_mail.known`, `sent_mail.recipient_links` pattern, `sent_mail.mail_read`.
- Produces:
  - `importer.decide(row) -> str`: `"import"` if any participant has a Contact; `"filtered"` if every participant is ignored or there are none; else `"wait"`.
  - `importer.run(doc: MailImport, imap, deadline: float) -> bool` (True when no row is left to process this run). Per folder: check UIDVALIDITY; on mismatch set `doc.error` naming the folder and skip it. Fetch with `BODY.PEEK[]` in batches within the size/count limits, re-check `known`, build the Communication through `BackfillMail(InboundMail)`: `sent_or_received` from `row.outgoing`, `imap_folder`, `timeline_links` from `mailsync_recipient_links` for all participants, no `email_account` during insert (so *Create Contact* never fires) then `db_set` of `email_account`, `status="Closed"`, `seen=1`, `unread_notification_sent=1`; the document carries `flags.mailsync_import = True`. Then `mail_read(..., sent_or_received=…)`. Each mail in its own savepoint; failures → `Failed` with the error, logged. Mails without Message-ID are imported once (row state guards it). Commit per mail.

- [ ] **Step 1: Failing tests**: `test_imports_mail_with_contact_as_closed_received` (status Closed, seen, linked to Contact and its Dynamic Link), `test_outgoing_mail_is_sent`, `test_all_ignored_is_filtered`, `test_mail_to_self_is_filtered`, `test_undecided_waits_then_imports_after_decision`, `test_no_contact_created_with_create_contact_on`, `test_present_skipped_and_rerun_idempotent`, `test_mail_without_message_id_imported_once`, `test_recipient_links_and_mail_read_hooks_called`, `test_uidvalidity_changed_folder_skipped_with_error`, `test_broken_mail_marked_failed_others_continue`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** `feat(import): import mails with known contacts as closed communications`.

### Task 6: Jobs, form and real-server test

**Files:**
- Create: `mailsync/backfill/jobs.py`
- Modify: `mail_import.py` (whitelisted `load_folders`, `start_scan`, `start_import`), `mail_import.js`
- Modify: `mailsync/tests/test_imap_server.py`
- Test: `mailsync/tests/test_backfill_jobs.py`

**Interfaces:**
- Produces: `jobs.enqueue(name: str, step: "scan" | "import")` → `frappe.enqueue("mailsync.backfill.jobs.work", queue="long", timeout=1500, job_id=f"mailsync_import::{name}", deduplicate=True, name=name, step=step)`. `jobs.work(name, step)`: login, run `scan.scan` or `importer.run` with `deadline = monotonic() + 1200`; when unfinished re-enqueue itself; when the scan finishes → `review.refresh`, status Review; when the import finishes → status Done if no Pending rows, else Review; `counters(doc)` recomputed by `GROUP BY state`; login or IMAP failure → status Failed with `error`, logged. Publishes `frappe.publish_realtime("mailsync_import", {"name": name}, doctype="Mail Import", docname=name)` so the form reloads.
- Form: buttons *Load folders* (dialog with checkboxes from `load_folders`, fills `folders`), *Scan*, *Review addresses* (route to *Mail Import Address* list filtered to Open rows of this import), *Import*; progress as the counters; buttons hidden while Scanning/Importing.

- [ ] **Step 1: Failing tests**: `test_work_scan_then_review_status`, `test_work_requeues_when_unfinished`, `test_login_failure_sets_failed`, `test_counters`. In `test_imap_server.py`: `test_backfill_end_to_end` against GreenMail (two folders incl. a subfolder, one known contact, one ignored address, one outside the date range; after scan → review → ignore → import: one Closed Communication, mailbox flags unchanged — no `\Seen`).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the whole suite, expect PASS.**
- [ ] **Step 5: Commit** `feat(import): run scan and import as resumable jobs`.

### Task 7: README, translations, release

**Files:**
- Modify: `README.md` (section *Importing past mail*: setup of an import-only account with *Enable Incoming* off, permissions, flow, limits, `flags.mailsync_import`; hook docs for `mailsync_own_address`, `mailsync_address_suggestion`, `mailsync_contact_link_doctype` and that `mailsync_recipient_links` / `mailsync_mail_read` are called for imported mails), `mailsync/hooks.py` comments, `mailsync/translations/de.csv`, `app_description` unchanged.

- [ ] **Step 1:** Write README and translations; full suite and ruff pass.
- [ ] **Step 2:** Whole-branch review by a fresh reviewer; fix findings.
- [ ] **Step 3:** Commit `docs: describe importing past mail`, push branch, open PR, wait for CI green, merge.
- [ ] **Step 4:** Merge the release-please PR (minor bump, `feat`), confirm the tag and GitHub release exist and `version-16` points to it.
