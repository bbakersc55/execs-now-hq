# 04 — Build Plan: Beta

**Phase 0 · Execs NOW HQ · for owner review**
**Built on:** `CLAUDE.md`, `00_assumptions.md`, `01_prd.md`, `02_data_model.md`, `03_access_matrix.md`.

---

## 0. How this plan works

**One module at a time, to done-and-tested, before the next starts** (`CLAUDE.md`). Each phase below has four parts:

1. **What "done" means** — the gate. Not "the code exists"; the observable state that ends the phase.
2. **Tests that must pass** — always including the two non-negotiable families, plus the phase's own acceptance criteria from `01_prd.md`.
3. **Manual checks you do yourself** — the ones I cannot honestly run for you, either because they need your judgement or because they need your real data.
4. **What I will report** — stated as `CLAUDE.md` requires: proven versus assumed, never a scoped subset presented as a total.

**Reporting discipline.** At the end of every phase I give you a table of acceptance criteria with three possible values: **tested end to end**, **written but not exercised**, **not implemented**. A criterion I could not run — because it needs a real Postmark send, a real Drive folder, or the Railway host — is marked as such rather than quietly counted as passing. No phase is reported complete on a partial run.

**Bugs get fixed in the current module, not carried forward** (`CLAUDE.md`). A defect found in Phase 3 that belongs to Phase 1 stops Phase 3.

**Every migration is shown to you before it is applied.** Destructive migrations get a dry-run report first.

### Execution order

Module numbers follow `CLAUDE.md`. **Build order is not module order**, in one place:

`0.5 foundation → 1 → 2 → 3 → 4 → 5 → 6 → design pass → 7 (Railway move)`

(The design pass may also follow the Railway move; it must precede Beta exit — see its section.)

**Build order is module order again.** Ruling 9.3 moved Module 6 after Railway because its inbound half needed a public webhook. The transport change removes that dependency: with Gmail as the transport (assumption A3), inbound arrives by **polling the tenant's own mailbox**, which needs no public endpoint and runs on the laptop. **Module 6 returns to its original position, before the Railway move.**

The Phase 1 carve-back stays where it is — `email_thread`, `thread_token`, threading headers, and Gmail connect are all in Module 1, because Module 1 promises a CF "send from my own address" and a `manual` direct-to-`sent` producer.

---

## Phase 0.5 — Foundation (before Module 1)

`CLAUDE.md` numbers six modules, but the tenancy, auth, and test scaffolding they all inherit cannot belong to Module 1 without making Module 1 dishonest about what it delivers. This is a short, separately-gated phase.

### Done means

1. Django 5 + DRF + Postgres `execsnowhq_dev` on port **8100**; Vite + React + TypeScript on **5200**, proxying `/api`.
2. Django-Q2 on the **ORM broker**, `qcluster` running with **≥4 workers** (A2).
3. `TenantScopedModel`, the `current_tenant` contextvar, `TenantMiddleware`, and the **fail-closed `TenantManager`** (B1) — an unscoped query **raises**.
4. `tenant`, `user`, `membership`, `client_assignment`, `audit_event`, `stored_file`, `tenant_secret`, `ai_call` migrated.
5. Google OAuth sign-in (invite-only) and magic-link sign-in both working end to end.
6. **The two test registries exist and run**, with the foundation models registered.
7. `.env.example` current; `scripts/backup_db.sh` written and **restored once into a scratch database**.

### Tests that must pass

- **Tenant isolation (registry).** Foundation models registered; the **meta-test fails on an unregistered model** — verified by deliberately adding a model and watching the suite go red.
- **Role boundaries (registry).** Matrix §2 and §3 rows: 2.1 cross-tenant 404, 2.4 one membership, 3.3/3.4 API key unreadable **by every role including FF**, 3.16–3.19 FF-only.
- `TenantContextMissing` raises when a query runs with no tenant bound — the single most important negative test in the codebase.
- Magic link: single-use, 20-minute expiry, hashed at rest, **GET does not consume** (C3.3), rate limit holds, enumeration response is constant.

### Manual checks

1. Start everything with the commands in `05_dev_environment.md`. Confirm 8100 and 5200, and that nothing else on your machine is on those ports.
2. Sign in with your Google account. Then try a Google account with no membership — confirm it is refused.
3. Request a magic link for a test client user. Confirm the email lands, the link shows a **Sign in button** rather than logging you in on click, and that clicking it twice fails the second time.
4. Run `scripts/backup_db.sh`, then restore that dump into a scratch database. **A backup you have never restored is a hypothesis.**

### Report

Every criterion above as tested / written-not-exercised / not-implemented, plus the schema for your approval **before the first migration is applied**.

---

## Phase 1 — Contacts & pipeline

### Done means

1. Contacts, companies, domains, locations, types, stages, service categories — all CRUD, with soft delete and restore.
2. **The client invariant** (FR-1.6a) derives forward and does not reverse.
3. `client_assignment` in place and **actually governing CF visibility** (FR-1.9c).
4. CSV import: mapping profiles, dry run, commit, **rollback**, ambiguous-match listing, notes column → real `note` rows.
5. Merge, with audit.
6. Stage automations: `create_task` fires; `draft_email` queues.
7. **The Outbox** as both approval queue and complete send log, including direct-to-`sent` routing.
8. Referral: fee terms, tenant blurb, three-part touch composition, staleness warning, onboarding draft with flyer.
9. Global search over contacts, companies, notes.

**Carved back from Module 6 (ruling 9.3)** — required for FR-1.19a and the CF "send from my own address" story:

10. **`email_thread` created for every outbound message**, carrying a `thread_token`.
11. **Threading headers on every send** — the token in the `Message-ID` and in `X-ExecsNowHQ-Thread`, `In-Reply-To` quoting the previous message, and Gmail's `threadId` stored on the thread (FR-6.2).
12. **Gmail connect** for FF and CF, with **send-as verification** against `settings.sendAs`; **not offered to VAs** (H7).
13. The `manual` producer routing by role: FF/CF direct-to-`sent` via their own Gmail, VA to `pending_approval`.
14. **The `APP_MAIL_TRANSPORT` seam**, with the Gmail transport implemented and Postmark raising a clear "V1 option" error.

> Not in Phase 1: inbound polling, replay fixtures, and the unmatched queue. Those are Module 6.

### Tests that must pass

- **Tenant isolation:** every Module 1 model registered.
- **Role boundaries:** matrix §4 and §5 in full — with 5.3 (VA cannot approve), 5.5 (VA *may* send `precall_invite`), 5.6 (VA `manual` becomes a draft), 4.5 (VA may merge), 4.11 (FF-only assignment), 3.15 (FF-only stages) called out individually.
- **Acceptance criteria AC-1.1 through AC-1.25.**
- **Every denied-send test also asserts the dev outbox is empty** and that no `outbox_message` reached `sent` (matrix §14.3).
- **AC-6.1 and AC-6.13** (carved back): one `email_thread` per contact conversation with a consistent token, recoverable from the `Message-ID`; `From` set to the verified tenant alias; `In-Reply-To` quoting the previous message on a follow-up.
- **AC-6.14** (carved back): an unverified send-as alias fails with an actionable message and does **not** fall back to the fractional's personal address.
- **The dev-outbox guard is transport-independent**: a non-allow-listed recipient on a localhost build never reaches the Gmail API at all — asserted by confirming the HTTP call is never made, not merely that the message did not arrive.

### Manual checks

1. **Import your real book of business** — the highest-consequence data event in Beta. Read the dry run before committing. Then **roll it back**, confirm the count returns, and import again.
2. Confirm the ambiguous-match list contains the duplicates you already know about.
3. Move a real prospect through the pipeline and watch the follow-up task appear and the email draft queue.
4. Read a generated referral touch. **This is a judgement call I cannot make for you:** does it sound like you, and would you send it to a real partner? If not, the template or the prompt is wrong and it is a Phase 1 bug.
5. Confirm the flyer attaches and that an onboarding draft appeared the moment you tagged a referral partner.
6. **Connect your own Gmail, verify the `info@` send-as alias, and send a real email to an allow-listed address.** Confirm it arrives showing **`info@getexecutivesnow.com`** as the sender, and that it is in your Gmail Sent folder — that is trade-off 2 of the transport change, working as intended. Replies will not be ingested until Module 6; expected, and said here so it is not later read as a bug.
7. **Deliberately break the alias.** Point `from_address` at an address that is not a confirmed "Send mail as" on your account and try to send. The error should tell you exactly what to add in Gmail. **Nothing should go out from your personal address instead.**

### Report — Phase 1 status (2026-09-11)

**Phase 1 is complete. All 29 acceptance criteria pass and all five manual checks pass.**

| | |
|---|---|
| Automated tests | **487 passed**, 2 xfailed |
| — of which the two mandatory families | **236** (tenant isolation + role boundaries) |
| — Module 1 acceptance | **41** |
| Frontend tests | **53 passed** |
| Manual checks | **5 of 5 passed** |
| Live deliveries to a real inbox | **2** (AC-1.6, AC-1.20) |

**Legend.** **Live** = exercised by the owner against a real Gmail delivery, not the dev
outbox. **Walked** = automated *and* stepped through by hand in the named manual check.
**Automated** = covered by the test suite; correct in code and in CI, but not separately
exercised by hand. Nothing below is "written but not exercised" — that column is empty,
which is the point of reporting it.

| AC | What it covers | Status |
|---|---|---|
| AC-1.1 | Import dry run is honest | ✅ Walked (Check 1) |
| AC-1.1b | Phone, tags and status columns have mapping targets | ✅ Walked (Check 1) |
| AC-1.1c | Status/Stage values mapped by hand, per pipeline | ✅ Walked (Check 1) |
| AC-1.2 | Commit and roll back | ✅ Walked (Check 1) |
| AC-1.3 | Ambiguity surfaced, never guessed | ✅ Walked (Check 2) |
| AC-1.4 | Stage automation fires task, queues email, per pipeline | ✅ Walked (Check 3) |
| AC-1.5 | An unapproved draft expires rather than sending | ✅ Automated |
| AC-1.6 | **Referral touch drafted 3 days early, approved, delivered** | ✅ **Live** (Check 4) |
| AC-1.7 | VA cannot approve or send | ✅ Automated |
| AC-1.8 | Vendor search by service category | ✅ Walked (extras) |
| AC-1.9 | Merge preserves history and is audited | ✅ Walked (Check 2) |
| AC-1.10 | Out-of-scope reads 404, never 403 | ✅ Automated |
| AC-1.11 | Client users have no CRM surface | ✅ Automated |
| AC-1.12 | Client invariant derives forward only | ✅ Walked (Check 3) |
| AC-1.12a | A contact holds a position in two pipelines at once | ✅ Walked (Check 3) |
| AC-1.12b | A sales pipeline cannot lose its only `won` stage | ✅ Automated |
| AC-1.13 | Assignment governs CF visibility | ✅ Automated |
| AC-1.14 | Assignment endpoints reject CF and VA | ✅ Automated |
| AC-1.15 | VA sees the whole CRM | ✅ Automated |
| AC-1.16 | Send-by default, configurable, expiry sends nothing | ✅ Automated |
| AC-1.17 | Outbox is the complete send log | ✅ Walked (Check 4) |
| AC-1.18 | Touch composition has all three parts | ✅ Walked (Check 4) |
| AC-1.19 | Stale blurb warns but does not block | ✅ Automated |
| AC-1.20 | **Onboarding fires once, attaches the flyer, delivered intact** | ✅ **Live** (Check 5) |
| AC-1.21 | VA may merge; CF may not | ✅ Walked (Check 2) |
| AC-1.22 | Delete and restore are delegable | ✅ Automated |
| AC-1.23 | Pipelines and stages FF-only; types and categories not | ✅ Walked (Check 3) |
| AC-1.24 | Staff removal cascades | ✅ Walked (extras) |
| AC-1.25 | AI spend is FF-only | ✅ Walked (extras) |

**The two live deliveries are the ones that matter**, because they are the only points
where the app's behaviour left the machine:

- **AC-1.6** — a referral touch drafted, approved, and received in Gmail **from
  `info@getexecutivesnow.com`**. Proves the Gmail transport, the verified send-as alias,
  the dev allow-list and the approval gate together.
- **AC-1.20** — an onboarding email delivered **with the flyer attached and the PDF
  opening with content**. This one failed twice before passing: the attachment arrived
  at 0 bytes because `stored_file` content was never written to storage *and* the
  transport was handed a literal `b""`. Both are fixed, and a test now asserts a
  delivered attachment's size equals the stored file's.

**What Phase 1 corrected that the plan did not anticipate.** Five findings came out of
the manual checks rather than the test suite, and all five were design errors rather
than coding slips:

1. **One fixed pipeline was wrong.** The practice runs two (sales, and a nurture track
   for referral partners) and the owner's CRM carries both a Status and a Stage column.
   Modelled as `pipeline` + `contact_pipeline_position`, with stage behaviour keyed on a
   `semantic` independent of the label.
2. **No way to add a contact or company by hand** — everything had arrived by CSV.
3. **Imported referral partners were invisible to the scheduler** (no cadence, no next
   touch), so no touch would ever have been drafted for any of the 40.
4. **Attachments were never stored**, only their metadata.
5. **Real-delivery visibility** — the Outbox did not say, before approval, whether
   approving would reach a real person.

**Not carried into Phase 2:** nothing. Every bug found in Checks 1–5 was fixed in Phase 1,
per `CLAUDE.md`.

---

## Phase 2 — Notes

> **Prerequisite, added after Phase 1.** `stored_file` content lives on the laptop under
> `MEDIA_ROOT`, backed up by a nightly `rsync` to `gs://execs-now-hq-db-backups/media`.
> That is proportionate for a flyer, which can be re-uploaded from the original. It is
> **not** proportionate for a recording: the audio exists nowhere else, and a nightly
> sync leaves up to 24 hours of client calls unprotected. **Move `stored_file` content to
> `gs://execs-now-hq-media` before the first recording is captured** — not at the Railway
> move. The object keys already mirror the GCS layout, so this is a backend swap in
> `apps/tenancy/storage.py`, plus creating the bucket (it does not exist yet) and the
> service account in `05_dev_environment.md` §5b.
>
> **Done 2026-09-11.** Bucket created (us-west3, private); service account with storage
> scoped to the media bucket only; the flyer and one Outbox attachment copied and
> SHA-256-verified; `check_media` compares sizes against GCS; the backup copies the
> bucket excluding `recordings/` (owner decision: recordings rely on GCS durability and
> 7-day soft delete, so retention is not undone by the backup). Two changes the plan
> did not anticipate: key creation needed a **project-scoped org-policy override**, and
> **object keys are now unique per upload** — two flyer rows shared one object, which
> the retention job's deletes would have turned into data loss.


### Done means

1. One-action capture; optional dual linking (Contact *or* Company, **and** Task).
2. PIN: set, unlock, lockout, **FF-only reset that clears rather than reveals**.
3. **The title-leak defence** — explicit title required before PIN, and `"Locked note"` for any auto-derived title on a stub.
4. Locked notes excluded **at index time**, not filtered at query time.
5. Recording → GCS → Speech-to-Text → Claude summary, with the summary **proposed, never auto-attached**.
6. Consent reminder; 120-minute cap; per-tenant audio retention with the deletion job running.

### Tests that must pass

- **Tenant isolation** and **role boundaries** (matrix §6), including **6.4 — PIN gating is not a role**: the FF without the PIN gets no body.
- **AC-2.1 through AC-2.10**, with AC-2.3's title-leak case run **both** through the UI and **directly against the API**, since FR-2.11b exists precisely for the path that bypasses the dialog.
- Search returns no body text for a locked note, asserted against the raw API response and rendered HTML, not the UI.

### Manual checks

1. Record a real 20-minute call. Read the transcript for usability and the summary for accuracy. **Would you keep this summary?** If not, the prompt needs work now.
2. PIN a genuinely sensitive note. Sign in as a VA and try to find it — search for a phrase from its body.
3. Ask for a PIN reset and confirm the email clears rather than reveals.
4. Confirm the consent reminder is worded in a way you are comfortable relying on.

### Report — Phase 2 status (2026-09-11)

**Phase 2 is complete. All ten acceptance criteria pass and all four manual checks pass.**

| | |
|---|---|
| Automated tests | **613 passed**, 2 xfailed |
| — of which the two mandatory families | **294** (tenant isolation + role boundaries) |
| — Module 2 acceptance | **41** |
| Frontend tests | **76 passed** |
| Manual checks | **4 of 4 passed** |
| Live against Google | Speech-to-Text on the app's own path (1 synthetic fixture + 2 real recordings); GCS read/write/delete with the app's key |
| Live to a real inbox | **1** — the PIN reset, through the practice's Gmail (re-check after the fix below) |

**Speech-to-Text and Claude quality — observed on 2 real recordings, not a pass.**

| Recording | Outcome |
|---|---|
| Solo dictation, 3 min | Transcript usable. **Claude summary kept as written** — accepted unchanged by the owner. |
| Video call, 6 min | **Microphone-only failure**, not a quality result: the browser recorder captures this device's microphone, so 383 seconds produced one word and a summary saying nothing was captured. Fixed as FR-2.18a; the recorder now states what it records, and a transcript under 5 words per recorded minute is reported as "almost no speech detected" with the audio kept and no summary drafted. |

So the prompt in `apps/notes/summary.py` has **one** real result behind it, and it was good enough to keep unedited. Judge it again over the next few calls.

**Legend** as in Phase 1. **Live** = exercised by the owner against the real service.
**Walked** = automated *and* stepped through by hand. **Automated** = covered by the suite.
Nothing is "written but not exercised".

| AC | What it covers | Status |
|---|---|---|
| AC-2.1 | Capture needs only a sentence | ✅ Walked (Check 1) |
| AC-2.2 | Linking optional, mutable, dual; never contact *and* company | ✅ Walked (Check 2) |
| AC-2.3 | Locked stub leaks nothing; the title-leak defence, UI **and** API | ✅ Walked (Check 2) |
| AC-2.4 | Five wrong PINs lock the note, audited per attempt | ✅ Walked (Check 2) |
| AC-2.5 | **Reset clears rather than reveals, FF-only** | ✅ **Live** (Check 3) |
| AC-2.5a | 110-minute warning, clean stop at 120 | ✅ Automated (simulated clock; no real 2-hour recording) |
| AC-2.6 | Consent reminder, once per sign-in session | ✅ Walked (Check 4) — **wording approved by the owner as written** |
| AC-2.7 | Summary proposed, never auto-attached | ✅ Walked (Check 1) |
| AC-2.8 | (a) transcription fails, audio kept · (b) upload fails, browser keeps it | ✅ Automated |
| AC-2.9 | Retention deletes transcribed audio, keeps and flags the rest | ✅ Automated |
| AC-2.10 | Tenant isolation | ✅ Automated |

**What the manual checks corrected, none of which the suite would have caught:**

1. **PIN resets and magic links bypassed the Outbox entirely** — sent straight through
   Django's mail backend, so they were never logged, never checked against the dev
   allow-list, and never carried by the practice's Gmail. An allow-listed reset landed in
   Mailpit instead of the owner's inbox. Both are now direct-to-`sent` Outbox producers
   through the configured transport, with the one-time link delivered but never stored
   (FR-1.15b). A guard test now fails if any code outside the transport module sends mail.
2. **No speech is its own outcome** (FR-2.18a), from the video-call recording above.
3. **The capture panel's "Linked to" radios were unusable** — a panel-wide input width rule
   stretched the radios away from their labels, so the third label sat above the contact
   search box and read as if the field were for a company.
4. **Design debt recorded, not fixed:** the capture panel is functional but not
   presentable. One frontend design pass across all modules before Beta exit — its own
   section below, after Phase 6.

**Two things carried out of Phase 2, both the owner's to decide, neither blocking Phase 3:**

- **Staff magic links.** The magic-link request endpoint will issue a link to any member,
  staff included, while access matrix 2.3 says staff sign in with Google only. Never
  exposed in the UI, and now the only route for the local test VA (`dev_va_login`).
- **Module 1's scheduled jobs were never registered** and now are (`ensure_schedules`).
  The first referral-touch drafting run is due around 2026-10-07 with about 42 drafts, each
  awaiting approval.

---

## Phase 3 — Task engine + client portal

> **The largest phase, and the one `CLAUDE.md` names as most important to the customer.** I expect it to take longer than Phases 1 and 2 together, and I would rather tell you that now than discover it at the end.

### Done means

1. Goal → Project → Task, three levels, `project` and `goal` nullable, **no `parent_task_id`**.
2. Six statuses including **Waiting on client**, rendered distinctly.
3. `client_owner_contact_id` on all three levels.
4. Comments with visibility, **defaulting to internal**.
5. `task_update` events with the prompted **client-facing line**.
6. Stakeholders at any level, most-specific-wins, **pointing at Contacts not Users**.
7. **`digest_item`** driving per-recipient consumption; digests keyed `(contact, cadence, period_start)`.
8. Generation Thursday 08:00 / send Friday 08:00; `every_update` on quiet-window close.
9. **`hold_all_digests` ON**, the approval screen, stale flagging with regenerate, expiry-releases-claims.
10. Portal: scoped by tenant **and** company; client task and **project** creation; FR-3.9a edit rule; on-demand report; cadence self-service by signed token.
11. Portal access grant, seats counted from live memberships, revoke.

### Mid-phase checkpoint — a report, not a gate

**After done-items 1–5** (hierarchy, statuses, client owner, comments, `task_update` events) and **before digests and the portal begin**, I send a status report in the same three-value format. It is **visibility into a long phase, not a second sign-off** — I continue into digests without waiting for a reply unless you tell me to stop.

It reports the hierarchy and its three-level cap, the six statuses, `client_owner_contact_id`, comment visibility defaulting to internal, and — most importantly — **whether `task_update` is capturing the prompted client-facing line in practice**, since every digest downstream is only as good as that field.

### Tests that must pass

- **Tenant isolation**, plus **client-company isolation as a separate family** (FR-0.2) — two companies in the *same* tenant, expecting **404** both ways.
- **Role boundaries:** matrix §7, §8, §9 in full. **8.3 (VA cannot approve a digest) is the single most important role test in the product.**
- **AC-3.1 through AC-3.39.** The ones I will not let slide:
  - **AC-3.5** — the AI narrative asserts no fact absent from its inputs.
  - **AC-3.6** — nothing sends while held; dev outbox empty after the send window.
  - **AC-3.9** — a silent week produces no email at all.
  - **AC-3.10** — four changes in five minutes produce exactly one email.
  - **AC-3.20/3.21** — stale flagging, and an approved digest **byte-for-byte unchanged** by a late update.
  - **AC-3.33/3.34** — one update claimed independently by two recipients; expiry releases one claim without touching the other.
  - **AC-3.35** — one person, one Friday email, despite stakeholder rows at two levels.
  - **AC-3.37** — the client-edit rule at all four boundaries.
- A **DST test** (AC-3.22): generation and send hold across a `America/Denver` boundary.

### Manual checks

1. **Read a real digest as your client would.** Does it read as *value delivered* or as a changelog? This is the product's central promise and the only person who can judge it is you.
2. Run one full weekly cycle on a real engagement: Thursday generation, Friday approval.
   **What "real" means during laptop Beta:** the client's tasks, updates, and narrative are real, but **delivery is observed in Mailpit** — any stakeholder not in `DEV_REAL_SEND_ALLOWLIST` lands in the dev outbox, not their inbox (FR-0.7). **Add your own address as a stakeholder** on the engagement so at least one digest is genuinely delivered and read in a real mail client. Links in it point at `localhost` and work only on your machine (H6).
3. Deliberately leave a digest unapproved. Confirm nothing arrives and that next week's contains the deferred content.
4. Set yourself as an `every_update` stakeholder and edit for ten minutes. Confirm one email, not six.
5. Sign in to the portal as a real client user on a second device. Create a task, create a project, comment. Confirm you cannot see anything internal.
6. Grant a third seat with only two available and read the error message.

### Report

AC-3.1–3.39 with status, and a **plain statement of digest behaviour under each of the four combinations** of `hold_all_digests` × AI prose — since that matrix is where an unintended send would hide.

---

## Phase 4 — Strategy session

### Done means

1. The Operations template seeded **verbatim** from `strategy_session_seed.md`, all nine sections, with `ask_when`, `must_ask`, `area`, `is_financial`, and stable `key`s.
2. Public tokenised pre-call form; autosave; resume; merge fields with graceful degradation.
3. Six Key Components computed average and lowest-score flag.
4. Live view: section budgets, must-ask counter, three-field diagnostic capture.
5. Claude drafting on **two triggers only**, each writing an `ai_call`; accept / edit / discard tray.
6. **Template snapshot** so template edits cannot touch completed sessions.
7. PDF via WeasyPrint with **all five exclusions defaulted off** and a true preview.
8. Conversion: per-row Goal or Project, `owner_text` → `client_owner_contact_id` where it resolves, back-links preserved, client invariant fired.

### Tests that must pass

- **Tenant isolation** (including the pre-call token) and **role boundaries** (matrix §10) — with **10.8 (VA cannot see §9 investment fields)** asserted against the API response body, not the UI.
- **AC-4.1 through AC-4.19.** Especially:
  - **AC-4.9** — all five exclusion markers absent from the generated PDF's text, then one toggled on and only that one appearing.
  - **AC-4.12 / AC-4.19** — heavy template edits leave a completed session byte-identical.
  - **AC-4.16** — no Claude call on answer save; exactly two triggers.
  - **AC-4.11** — nothing created until conversion is confirmed.

### Manual checks

1. **Run a real strategy session with a real prospect.** Nothing else tests this module honestly.
2. Before that, send yourself the pre-call form and fill it in as a prospect would. Is it too long? The seed has 13 pre-call items and that is a real completion risk.
3. During the call, watch whether the drafted map rows are usable or noise. **If you find yourself ignoring the tray, tell me — that is a prompt problem and it is a Phase 4 bug.**
4. Generate the PDF and read every page **as the prospect**. Confirm none of your private notes, mechanics, or the investment range are present.
5. Convert the session and check the resulting Goals and Projects before the engagement starts.

### Report

AC-4.1–4.19. The quality of Claude's map rows and mirror is reported as **your judgement on N real sessions**, with N — not as a pass. I will not claim the AI output is good; I will report what you said about it.

---

## Phase 5 — Meeting ingestion

### Done means

1. `DriveWatch` cursor polling every 10 minutes, "Sync now", health screen, `drive_file_owner_email` captured.
2. `MeetingSourceFile` idempotent on `(tenant, file, version)`; two-step commit; cursor never advances past unprocessed work.
3. Claude parse producing participants, action items, deliverables, and a **drafted summary**.
4. Matching in the order **email → email domain + name → name alone**, ranked, with the reason shown and both paths always offered.
5. Proposed contact type per participant, with **referral → queued onboarding** and **vendor → inline categories**.
6. **Partial approval**; rejection persists; re-parse supersedes.
7. `Meeting` record on every approved participant's timeline.
8. CF `proposal-scope` with both limbs.

### Tests that must pass

- **Tenant isolation**, **role boundaries** (matrix §11), including **AC-5.16 — the CF two-limb scope**, with the FF's unmatched prospect meeting returning **404** to a CF.
- **AC-5.1 through AC-5.16.** Especially:
  - **AC-5.1** — three days of downtime loses nothing.
  - **AC-5.2** — three polls, no duplicates.
  - **AC-5.3** — nothing created before approval.
  - **AC-5.8** — approving a deliverable creates records and **sends nothing**.
  - **AC-5.10** — a parse failure does not advance the cursor.

### Manual checks

1. Point it at your **real** Gemini notes folder and let a week of real meetings accumulate.
2. Close the laptop for two days. Confirm nothing is lost.
3. Review a queue of real proposals. **Are the extracted action items ones you would actually have written down?** If precision is poor, the prompt is a Phase 5 bug.
4. Confirm a meeting you attended now appears on the right people's timelines.
5. Confirm no contact was created that you did not approve.

### Report

AC-5.1–5.16, plus **extraction quality on N real meetings** with a count of proposals approved versus rejected — a rejection rate is the honest measure here, and I will report it whatever it is.

---

## Phase 6 — Unified client communication

> **Back in module order.** Its outbound half — threading, tokens, Gmail sending — was **carved back into Phase 1**, because Module 1 could not honestly be called done without it. What remains is the inbound half, which the transport change makes laptop-friendly: polling the tenant's own mailbox needs no public endpoint.

### Done means

1. The **thread poller**, cursor-based over the threads the app started, idempotent on the provider message id — which matters more with polling than with webhooks, because every poll re-reads the whole thread.
2. `manage.py replay_inbound` and the **eight fixtures** — `threadId` match, `In-Reply-To` match, custom-header match, sender fallback, no match, quoted-history, attachment, re-poll — which are the module's regression suite.
3. Matching in order: Gmail `threadId` → `In-Reply-To`/`References` → `X-ExecsNowHQ-Thread` → sender email → no match.
4. The **unmatched queue**, with filing to a contact. Nothing is ever dropped.
5. Quoted-history trimming for display with the raw message retained; attachments stored.
6. `gmail.readonly` requested at connect time, with what it grants stated plainly at the point of consent.
7. Real replies ingested from the tenant's mailbox — **on the laptop**, no public endpoint.

### Tests that must pass

- **Tenant isolation** and **role boundaries** (matrix §12), including **12.4 — a VA cannot send a reply** and **12.5 — client users reach no communication surface at all**, since these threads include internal correspondence *about* them.
- **AC-6.2 through AC-6.11** by replay — reported as **fixture-driven**, never as live transport.
- **AC-6.12** — a real reply on a real digest appears on the timeline within one poll interval. **This now runs on your laptop**, which is the point of the transport change.
- **AC-6.15 / AC-6.16 / AC-6.17** — Gmail-native replies captured, downtime tolerated, and a revoked token naming its consequence.

### Manual checks

1. Reply from a real client address to a real digest. Confirm it threads onto the contact.
2. Reply from an address the app has never seen. **Confirm it lands in the unmatched queue rather than vanishing** — the failure mode that matters here is silence, not error.
3. Confirm you are comfortable with what `gmail.readonly` grants. It is a read scope over your whole mailbox, even though the app reads only threads it started. Under the Internal consent screen it costs nothing in verification — but it is still your mailbox, and the boundary is enforced by the app's code rather than by Google.

### Report

Fixture results and live results **reported separately and labelled**. A replay pass is not evidence that mail is being delivered or ingested.

---

## Design pass — frontend, all modules, before Beta exit

> **Added 2026-09-11 from the Phase 2 manual checks** (owner decision: recorded now, not
> done now). Each module has shipped a UI that is functional and tested but not
> presentable — the Notes capture panel was the example that prompted this. Fixing it
> piecemeal inside each phase would restyle the same components five times.

**One dedicated pass, after Phase 6 and before Beta exit.** It may run before or after the
Railway move; note that clients first see the portal at the move, so a pass before cutover
means no client ever sees the unstyled version.

**Scope — every screen in Modules 1–6 and the client portal:**

1. A small component set (form fields, choice rows, panels, dialogs, tables, status pills,
   banners) replacing the ad hoc styles in `theme.css`, built on the Executives Now tokens
   already there so V1's per-tenant branding stays a token swap.
2. Layout and hierarchy on each screen; empty, loading and error states; narrow widths.
3. Accessibility: every control labelled, keyboard reachable, visible focus, contrast
   against the brand palette.
4. **Known inputs:** the Notes capture panel (functional, not presentable — owner, Check 3);
   the "Linked to" choices, whose layout broke because a panel-wide `input { width: 100% }`
   also caught radio buttons.

**Not in scope:** changes to behaviour, copy that carries a rule (the consent reminder, the
PIN dialog's explanation, anything stating what is or isn't sent), or any review queue.
Those change only with their own AC.

**Done means:** every screen walked by the owner at desktop and laptop widths; the
existing frontend tests pass unchanged except where a test names an element that was
deliberately renamed.

---

## Phase 7 — The Railway move

### The trigger

**The first client portal user.** Not a date, not a module count. Until a client needs to sign in, the laptop is sufficient and Railway is unnecessary cost and complexity. The moment you grant portal access to a real client (matrix row 9.1), the move must already have happened — a magic link pointing at `localhost` is useless to them.

**So the practical trigger is one step earlier: when you decide the next client gets portal access, the move starts.** Phase 6b and Tier 2 also wait behind it.

### What the migration involves

**1. Provision**
- **The GitHub repo exists and Railway is connected to it.** Deployment is **git push to `main` → Railway builds and deploys** — the pattern you already run. There is no manual upload step and no separate deploy command.
- Railway project, Postgres, and the app service. **No Redis** — Django-Q2 is on the ORM broker (A2).
- The `qcluster` runs as a **second Railway service against the same database**, not as a thread in the web process, so a web restart cannot kill a running transcription.
- `CONN_MAX_AGE=0` on the cluster (A2 consequence 3).

**2. DNS**
- `app.getexecutivesnow.com` → Railway. **That is the whole list.**
- **No Postmark records are needed.** DKIM, Return-Path, and the inbound MX belonged to a transport Beta no longer uses (assumption A3); mail goes out through the tenant's Gmail and comes back by polling their mailbox. Those records return with the Postmark transport option in V1.
- **Consequence for sequencing:** DNS is no longer the long pole. Under the old plan it had to start days early; now it is a single A/CNAME record.

**3. Data — with an explicit freeze**

The cutover is a window, not a gradual migration. **No writes happen on the laptop between the final dump and go-live**, because any that did would be silently lost.

1. **Stop `qcluster`** on the laptop. Confirm no job is mid-flight.
2. **Stop the web process.** The freeze starts here.
3. Take the **final `pg_dump`**.
4. Restore to Railway Postgres.
5. **Verify row counts per table**, dump against restore. A mismatch stops the cutover.
6. Flip DNS and configuration (steps 2 and 4).
7. **Start the Railway services** — web first, then `qcluster` (see step 6 verification, which must happen between them).

- A **rehearsal restore into a scratch Railway database** happens days earlier, so the real window is short and already practised.
- **Flush the Django-Q2 queue tables before starting `qcluster`** (A2 consequence 2) — a restored database replays stale jobs otherwise, which after a migration could mean re-sending a week of digests.
- Re-key: `FIELD_ENCRYPTION_KEY` moves as a Railway secret. **The Anthropic key and OAuth tokens do not survive without it** — verify decryption on Railway before decommissioning the laptop copy.

**4. Configuration**
- `PUBLIC_BASE_URL` → `https://app.getexecutivesnow.com`. This alone flips outbound mail from the dev outbox to real delivery (FR-0.7), so **it is the single most consequential variable in the move.**
- `DEV_REAL_SEND_ALLOWLIST` **removed** — it is a localhost-only mechanism and must not exist in production.
- Sentry enabled (A5).
- Google OAuth redirect URIs updated for the new origin. **This is now load-bearing for mail, not just for sign-in** — the Gmail transport rides on the same OAuth client.

**5. Backups move**
- The laptop's `scripts/backup_db.sh` used **gcloud ADC** (§I). Railway has no interactive login, so the nightly job authenticates with a **dedicated service-account key** stored as a Railway secret, writing to the same `gs://execs-now-hq-db-backups` bucket with the same 30-day retention.
- Run as a **Railway cron service**, not on the laptop.
- **Restore once from a Railway-produced dump before the laptop copy is deleted.** The laptop database stays untouched as a fallback for at least two weeks.

**6. Verification before you call it done**

> **The consequence to internalise before anything starts:** on Railway there is **no `DEV_REAL_SEND_ALLOWLIST`**. It is a localhost-only mechanism and it is removed. From the moment the app runs on Railway, **every stakeholder email is real mail to a real client.** Every safeguard that was previously provided by the environment is now provided only by `hold_all_digests`.

1. **Confirm `hold_all_digests` is ON *before* the first `qcluster` start on Railway — not after.** Once the cluster runs, generation begins; verifying the switch afterwards is verifying it too late. This is the one check whose order matters.
2. Sign in with Google on the new host.
3. Send yourself a magic link and confirm the URL is `app.getexecutivesnow.com`.
4. **Reconnect Gmail on the new host and re-verify the send-as alias.** OAuth tokens are per-origin and the redirect URI has changed; until this is done, **no app mail sends at all — including client magic links** (assumption A3, trade-off 1). Confirm with one test message, delivered, appearing in the Outbox as `sent` with `From` set to the alias.
5. Approve one real digest and confirm delivery to a real stakeholder.
6. Confirm the nightly backup ran, **and restore it**.

### Order

DNS first (propagation), then provision, then a **rehearsal restore into a scratch Railway database**, then the real cutover, then the backup cron, then Phase 6b.

**7. After cutover, the laptop is development-only**

- **Live data never returns to the laptop.** Local development runs against a **separate dev database** — seeded fixtures, or a periodically restored production copy **with client email addresses scrubbed** so a stray send can never reach a real person.
- Changes ship by **git push → Railway deploy**. Nothing is edited on the production host.
- The laptop's production database is kept untouched as a fallback for **at least two weeks**, then deleted.
- The post-move daily workflow is documented alongside the pre-move one in `05_dev_environment.md`.

### What does not change

The polling architecture (A6 and F19 Tier 2 both stay pull-based), `hold_all_digests`, and every review queue. Railway changes where the app runs and who can reach it. It changes nothing about what the app is allowed to send.

---

## Phase 8+ — after Beta

In `CLAUDE.md`'s order, not started until Beta has run on your real practice for a full digest cycle: invoicing → basic financials → contract e-signature → simple HRIS → connectors → product billing and self-serve onboarding.

**Three things that should happen early in that sequence regardless:**

0. **A staging environment, before public launch.** `demo.getexecutivesnow.com` on Railway, its own database, a seeded demo tenant with fictional clients and no real data. It serves two purposes that both arrive with V1: **demonstrating the product to prospective fractionals** without exposing your practice's real client data, and **testing a release before it reaches production**. Once other people's practices depend on the app, shipping straight from `main` to production with no intermediate host stops being acceptable. Staging deploys from a `staging` branch; production continues to deploy from `main`.

1. **The V1 Google verification track.** Beta runs on an **Internal** OAuth consent screen (assumption C1), which needs no verification and has no refresh-token expiry — but Internal means *only Workspace accounts can sign in*. The moment a second fractional's practice needs access, the app must move to **External**, and `gmail.send` plus `gmail.readonly` then require **Google verification with a CASA security assessment**. It is slow, expensive, and **the longest lead time in the entire V1 plan.** Start it before it is needed, not when it blocks launch.
2. **Postgres row-level security** (B2), deferred from Beta as defence in depth once the schema stops moving.

---

## 9. Review outcome

**Rulings:**

- **9.1 — Phase 0.5 stays a separate gated phase.**
- **9.2 — Phase 3 is not split.** A **mid-phase checkpoint** is added after done-items 1–5: a status report in the three-value format before digests and the portal begin. **It is a report, not a gate** — I continue unless you say otherwise.
- **9.3 — Module 6 moves entirely after the Railway move**, with the outbound half carved back into Phase 1: `email_thread` and `thread_token` on every outbound message, `Reply-To` carrying the token on **both** Postmark and Gmail, and Tier 1 Gmail connect. You were right that a Module 1 which cannot send from Gmail is not done — the CF story and the `manual` producer both live in Module 1 and both need it.

**Phase 7 additions applied:** deployment is **git push to `main` → Railway** with repo connection added to provisioning; an explicit **freeze** with a seven-step cutover sequence and per-table row-count verification; the laptop becomes **development-only** afterwards with a scrubbed dev database and no path for live data to return; and the verification list now **leads** with confirming `hold_all_digests` is ON **before the first `qcluster` start**, because `DEV_REAL_SEND_ALLOWLIST` no longer exists and every stakeholder email becomes real at that moment.

**Also applied:** the Phase 3 manual check now states that laptop-Beta delivery is observed in Mailpit and that you should add your own address as a stakeholder to see one genuinely delivered digest; Beta exit criterion 7 is made concrete in `01_prd.md` (5 digests, 2 strategy sessions with PDFs sent, 10 meeting proposals with the approve/reject rate reported); and a **staging environment** (`demo.getexecutivesnow.com`, separate database, seeded demo tenant) is added to Phase 8+ as a pre-launch requirement.

**Status:** `04_build_plan.md` is complete. Proceeding to `05_dev_environment.md`, the last Phase 0 document.
