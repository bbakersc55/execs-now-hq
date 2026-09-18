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

**Every migration's SQL is shown to you before it is generated.** Destructive migrations get a dry-run report first and wait for your yes. **Since 2026-09-16** a purely additive migration may be applied immediately without waiting, on the three conditions in `CLAUDE.md` (additive, suite green on it, a backup ran this session); the report always says it was applied.

### Execution order

Module numbers follow `CLAUDE.md`. **Build order is not module order**, in one place:

`0.5 foundation → 1 → 2 → 3 → 4 → 4.5 → 5 → 6 → design pass → 7 (Railway move)`

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

### Report — Phase 3 status (2026-09-18): 5 of 6 manual checks pass; Check 2 half-run — generation proven, delivery not

**Not yet a phase sign-off.** All **41** acceptance criteria pass in the automated
suite (AC-3.40 and AC-3.41 were added on 2026-09-15). **Five of the six manual checks
pass.** `phase-3` is merged to `main` on the owner's instruction, but **Phase 4 does
not start until the owner confirms a digest was delivered.**

**Check 2 ran half-way on the real cycle, 2026-09-17/18.** Thursday's generation was
correct: three weekly drafts were written 24 hours ahead, all `pending`, and nothing
was sent. Friday's half did not happen — the drafts were not approved before their
08:00 MDT window, and the tick expired them unsent 36 seconds later, exactly as
FR-3.30 says it should. So what the cycle proved is **generation and expiry on real
work**; **delivery through the practice's Gmail on a weekly digest remains unproven**,
and Check 2 stays open. The content was not lost: the claims were released and
`owed_to` returns it to the same recipients for the next period.

**How the delivery half will be proven** (owner's decision, 2026-09-18): rather than
wait another calendar week, generate a weekly digest to the owner's own address with
the **dev control**, send window a couple of minutes out, then read it, approve it,
and confirm it arrives. That exercises the identical path — the only thing skipped is
the calendar wait. When it passes it will be recorded here in exactly those terms:
**dev-triggered generation, real approval, real Gmail send.** The natural
Thursday/Friday cycle keeps running alongside it as ordinary use.

| | |
|---|---|
| Automated tests | **981 passed**, 3 skipped, 2 xfailed (2026-09-18) |
| — tenant isolation + role boundaries files | **377** (`test_tenant_isolation.py` 231, `test_role_boundaries.py` 146). The Module 3 files below add their own isolation and role cases |
| — Module 3 test files | **207** (acceptance 32, digests 63, portal 63, act as 19, activity log 19, stakeholder picker 11) |
| Frontend tests | **220 passed** |
| Manual checks | **5 of 6 passed** · Check 2 **half-run**: generation proven on the real cycle, delivery not (above) |
| Migrations since the 2026-09-11 report | **4, all additive**, applied by the owner 2026-09-15: `work` 0002 (digest key unique among live digests only), `work` 0003 and `tenancy` 0003 (acting-as columns), `crm` 0019 (Outbox `suppressed` state). **None since** — the 2026-09-18 digest fix touches no schema |
| Live to a real inbox | An **every-update** digest, approved and delivered (retest, 2026-09-15). **A weekly digest: not yet** — that is Check 2 |

**Digest behaviour under each of the four combinations**, which is where an
unintended send would hide. Tested as a parametrised table, all four cases:

| `hold_all_digests` | AI prose | What happens at generation | What sends at the window |
|---|---|---|---|
| **ON** (Beta default) | ON | Waits: `pending` | **Nothing.** Unapproved at the window → `expired`, items released, content owed again |
| **ON** | OFF | Waits: `pending` | **Nothing**, same as above — held means held, AI or not |
| OFF | ON | **Still waits**: `pending` | **Nothing** unless approved: an AI-written digest always needs a person (FR-3.27) |
| OFF | OFF | Pre-approved at generation | **Sends on cadence**, no human involved — the only combination that does |

So exactly one of the four sends without a person, and it is the one with no AI
in it. `hold_all_digests` defaults ON, so out of the box none of them do.

**Four decisions the documents did not settle** (all owner-approved, recorded in
`01_prd.md` and `02_data_model.md`): the rollup precedence with
`waiting_on_client` first; monthly digests on the first send-day covering the
previous calendar month; the in-app client-activity half as a feed over existing
`task_update` rows rather than a new table; and the `apps/work` split with
`task` left in `apps.crm`.

**Three bugs the tests found in my own first cut**, all in the digest engine and
all the kind that would have shown up as a client receiving the wrong thing:

1. **A pending draft's updates looked unclaimed**, so a second draft could
   collect them again. A claim is now any `digest_item`, which exists exactly as
   long as the claim does.
2. **Deferred content could fall out of the window.** Generation bounded its
   query by the period label, so an update released by last week's expiry was
   older than this week's window and would have been lost silently. What is owed
   is now decided by claims, floored only at when the recipient was attached.
3. **The weekly period label can sit in the future** (it derives from the send
   window), and using it as the upper bound hid everything owed today.

**The six manual checks** (`phase3_manual_checks.md`). Everything listed as found
was fixed before the check was re-run, unless it says otherwise.

| Check | Status | What it found |
|---|---|---|
| 1 · Read a real digest as your client would | ✅ Passed (owner) | Functional, not polished: the digest email and the progress report go to the design pass as known inputs (item 5), layout and typography only |
| 2 · One full weekly cycle on a real engagement | ⏳ **Half-run 2026-09-17/18** | **Thursday passed:** three weekly drafts generated 24 h ahead, all `pending`, nothing sent. **Friday did not run:** the drafts were not approved before the 08:00 MDT window and the tick expired them unsent 36 s later — correct behaviour, but it leaves delivery unproven and released the content back to the next period. The remaining half is being proven by dev-triggered generation to the owner's own address with a short send window, then real approval and a real Gmail send. **Phase 4 waits for the owner's confirmation of delivery** |
| 3 · Leave a digest unapproved | ✅ Passed on retest | **The server expired it on time; the screen never refreshed**, so it looked pending. Now: the list refreshes, a passed window is flagged, approving after the window is refused (it would otherwise have sent on the next tick), and a banner shows when the tick has stopped. The cluster had been down overnight with nothing showing it; the runbook now says to restart `qcluster` after every backend commit, and stale schedules are realigned (`work.tick` had been stuck at 12 Sep, firing every ~30 s) |
| 4 · Be an every-update stakeholder | ✅ Passed on retest | **Two engine bugs:** a held every-update digest was expired by the same tick that generated it, and the expired row then blocked its content from ever generating again. Fixed; **FR-3.28d** (24-hour review window) confirmed by the owner. A later retest looked silent but was correctly inside the 30-minute quiet window — no defect — which led to the read-only **"Coming up"** card (FR-3.29a) |
| 5 · Sign in to the portal as a real client user | ✅ Passed on retest | No create controls in the portal; "Add a task here" on a goal gave a client a bare 400; magic-link sign-in landed on a 404. Added from what the check showed: the client **activity log** (FR-3.41) and **act as** (FR-3.42). *(The activity log was **reversed on 2026-09-16** — it is the practice's feed now, not the client's, and a client is refused it: FR-3.41a. Act as stands.)* |
| 6 · Grant a third seat with two available | ✅ Passed on retest | The seat message was clear. Also found: no FCC/ECC choice at grant, no way to change a role, the seat count out of step after a revoke, no primary contact picker, and a VA able to read seat usage (matrix 9.5). Matrix 9.2a added |

**Also found during the checks, and fixed:** the stakeholder picker searched every
contact in the tenant; it now defaults to the work's client company, with an explicit
"someone outside" search, and marks the practice's own people.

**Decided during the checks** (recorded in `01_prd.md` and `03_access_matrix.md`):
clients may file a task directly on a goal they can see; FR-3.28d's 24-hour review
window (owner-confirmed); who may act as whom, and that no email of any kind leaves
while acting (FR-3.42, matrix 9.6–9.10); and what the client activity log contains
and never contains (FR-3.41, matrix 7.16–7.17).

#### The defect the half-run cycle uncovered — a dead digest holding live claims (fixed 2026-09-18, commit `0bb2169`)

Confirming in the database what had become of Friday's two expired drafts turned up a
**third** weekly digest from the same generation, to the owner's own contact row. It
sat in `skipped` while its three `digest_item` rows **survived**.

**Why that is worse than it looks.** `qualifying_updates` excludes an update claimed
by any `digest_item` for that contact, *whatever state its digest is in*. A dead
digest holding claims therefore owes its content **to nobody, for ever**, and appears
on no screen. It is precisely the silent drop the digest engine exists to prevent —
FR-3.30 says an expiring or skipped draft releases its claims, and this row had not.

**What the evidence showed.** No audit event existed for the digest, and `skip()`
always writes one inside its transaction — so `skip()` never ran. The only other
writer of `skipped` is `regenerate()`'s "nothing owed" branch, which writes none. The
items were created **15 ms before** the state write, which a single `regenerate` call
cannot produce: it saves the row, *then* writes items. The reading that fits is **two
regenerate calls milliseconds apart** — one click of a one-click button arriving
twice. The first deleted the claims, re-collected and wrote fresh items; the second
had already run its own delete, read the first one's committed items as live claims,
found nothing owed, and marked the draft skipped while those items stayed behind.
Stated as what it is: well-supported inference from timestamps and the absence of an
audit event, not a logged sequence.

**The fix** (`apps/work/digests.py`):

- **`_locked(digest)`** — every writer of one draft (`regenerate`, `approve`, `skip`)
  re-reads the row `select_for_update`, so a second call waits for the first and
  redoes its work against the finished state.
- **`_enter_dead_state`** — now the only way into `expired` or `skipped`. Releasing
  the claims and writing the state is one operation, because the pair *is* the
  invariant; the re-count afterwards asserts the release took and raises
  `DigestClaimsHeld` rather than leave a dead row holding live claims. A refused
  write leaves a **live draft a person can still see and act on**, which is always
  the better failure.
- **`expire_due`** — one locked transaction per digest, so the tick cannot expire a
  draft someone is regenerating in the same second.
- **The screen made it reachable in one click, so the screen changed too:**
  Regenerate is single-submit, disabled and reading "Regenerating…" while in flight.

**Tests, all three non-negotiable for this module from here on:** the invariant itself
(every route into a dead state, then a sweep asserting no `digest_item` survives on
any dead digest); the release failing to take must refuse the state and leave the
draft `pending`; and the race fired on purpose — two threads on a barrier, asserting
one live draft whose claims match what its body describes. The race test reproduces
the exact production symptom (`skipped`) **three runs out of three** with the lock
removed and passes with it; it is a timing test, so it is not claimed to be
deterministic under load.

**The repair, and the audit behind it.** The stuck digest's three claims were released
on the owner's instruction, with a `digest.claims_released` audit event naming each
freed update and why; `owed_to` for that contact then returned the three, so they come
round again next period. **Every digest in a dead state, across all tenants, was then
scanned:** 6 `expired` and 1 `skipped` digest hold **zero** claims, and no update is
claimed only by a dead digest. The 18 claims that exist all sit on `sent` digests,
which is the delivery record and correct. **That one row was the only occurrence.**

#### The process lesson, and what changed because of it

**A pending digest expires at its send window.** It does not sit and wait to be
noticed; the window is a deadline, and the tick enforces it within seconds. That is
right — FR-3.30 exists so nothing can send unread — but the screen was stating the
deadline as an absolute time (*"expires 9/18, 8:00 AM if not"*), and an absolute time
reads as information rather than as *this morning*. Both weekly drafts were lost that
way.

So each pending digest card now leads with a **countdown** — "Expires in 6 hours" in a
warn pill, the absolute time beside it, the consequence spelled out — on a clock that
ticks every 30 seconds, rounding always **down** so it never shows time that is not
there. The general rule for this product: **where the app enforces a deadline, the
screen shows time remaining, not a timestamp.**

---

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
9. **Email:** the pre-call invite and the strategy-PDF email use the shared **base email layout** (`apps/crm/services/email_layout.py`, `templates/email/base.html`) with a text/plain part, and are previewable in the Outbox — no separate styling. Settled by the email presentation pass (2026-09-15).

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

## Phase 4.5 — Module 4B: the client value report

> **Scope approved by the owner 2026-09-16, with rulings on all eleven open questions
> (recorded below). Still scope: nothing here is built or designed.** The module starts
> when the owner says so, after Phase 4, and the full `FR-4B.x` write-up in `01_prd.md`
> comes with it.

### Why this exists

Module 3 shipped an on-demand progress report (FR-3.38) that renders **the same
content as a digest for a chosen period**. That is what it says it is, and it is the
wrong artifact. A client opening it reads a flat run of things that moved: statuses
changed, comments posted, tasks closed, newest first. It answers *what happened
lately*. It does not answer the only question a founder is actually paying to have
answered — **are we getting where we said we were going, and is it working?**

The difference is not presentational. A period-scoped activity list has no anchor
outside the period, so it cannot show a direction, cannot show a distance still to
travel, and cannot distinguish a month of real movement from a month of busywork.
Worse, it invites the one summary number that destroys trust the fastest:
percent-of-tasks-done. **A third of the tasks is not a third of an outcome**, and a
client who works that out once stops believing every number on the page after it.

The replacement is anchored on **goals** rather than on a period, because the goal is
where the engagement's promise lives. Goals arrive from the strategy session — each
accepted Strategy Map row becomes one on conversion (FR-4.28) — and are added
throughout the engagement as new bottlenecks surface. The report is therefore the
other half of the strategy session: the map says what we are going to change, and
this says whether it changed.

**This replaces FR-3.38.** It is not an additional screen alongside it.

### Purpose, in one sentence

Show a client, per goal, what outcome was promised, where the measure of it stood
when we started, where it stands now, where it is meant to land, what has been done
toward it, and — in the fractional's own words — what that adds up to.

### The shape

**Anchor and organisation.**

1. The report is organised **by goal**, not by period. It shows **all** of a client
   company's goals: **current first, historical below**.
2. **Any single goal is openable on its own** — the unit a quarterly-review
   conversation actually walks through, one goal at a time.
3. Goals come from two places and the report does not distinguish them: Phase 4's
   map-row conversion, and goals added by hand as the engagement runs.
3a. **A goal created by hand mid-engagement gets the same measurable prompt as one from
   conversion, at creation** — kind, name, unit, baseline, target, direction — with
   **"not measurable numerically" as an explicit choice** rather than an empty field
   someone skipped. An empty field records nothing about whether it was considered; a
   deliberate choice records that it was. This is what keeps goals added in month four
   reporting as well as the ones the engagement opened with.

**What a goal carries, beyond today's fields.** Today a `goal` has title,
description, client company, owner, client-owner contact, target date, a derived or
overridden status, and a back-link to its map row. This module adds:

4. **A measurable, of one of two kinds** (ruling 1):
   - **Numeric** — a name, a unit, a **baseline**, a **target**, and a dated
     measurement history. The baseline is what the number was when the engagement
     started; without it there is no distance travelled, only a reading.
   - **Qualitative** — a **"how we'll know" sentence** in place of a number, for the
     goals that do not reduce to one. "Reduce supervisor overload" is the ordinary
     case, not the exception.

   **The strategy session prompts for structure and accepts text; it never blocks on
   it.** A fractional mid-conversion, with a prospect waiting, must not be stopped by a
   form demanding a unit.
4a. **A direction of good** on every numeric measurable — **up-is-good or
   down-is-good, stored explicitly** and set at conversion or creation (ruling 2).
   Never inferred: inference is silently wrong when baseline and target are equal, and
   has nothing to work from before a target is set.
5. **A 30/60/90 horizon**, already captured on the map row and currently dropped on
   conversion.
6. **A short outcome statement** — the fractional's own sentence about what this goal
   is really for, written in client language and updated as understanding changes.
   Not the description, which is internal scoping; this is the line a founder would
   repeat to their board.
7. **Optional milestones** — dated beats: "area lead hired", "inspection app live". A
   goal may have none. Two ways to get one (ruling 8): **a standalone milestone**, or
   **a task marked as a milestone**, which derives its date from the task's completion
   rather than being maintained in two places.

**Progress display, and the rule that governs it.**

8. **When a measurable exists, it is the headline**: baseline → current → target.
9. **Task and project completion is a secondary bar**, present and clearly subordinate.
10. **Never lead with percent-of-tasks-done.** This is a product rule, not a layout
    preference, and it holds in the portal, in the PDF, and in any future digest that
    borrows from this module.
11. **A qualitative goal's headline is its outcome statement** (ruling 1), with the
    "how we'll know" sentence beneath it and the milestones carrying the timeline. The
    completion bar stays secondary there too — it does not get promoted to the headline
    just because the numeric slot is empty. The same holds for a goal with no
    measurable at all.
11a. **The measurement chart appears in both the portal and the PDF, from three
    readings up** (ruling 9). Below three it is not a chart, it is decoration over two
    points, so baseline → current shows as text instead.

**Resolution — how a goal becomes historical.**

12. A goal is resolved into exactly one of: **achieved · changed course · paused ·
    retired**. An unresolved goal is current; a resolved one moves to the historical
    section and keeps its measurements and history.
13. **Each resolution requires a one-line reason**, and that line becomes part of the
    goal's permanent history rather than a field that can be edited away quietly.
13a. **Resolutions append; they never erase** (ruling 7). Resuming a paused goal
    appends. Un-achieving an achieved goal is allowed and appends a new resolution line
    with its own reason. **No resolution line is ever edited away** — the history of how
    the thinking changed is the part worth keeping.
13b. **FF and an assigned CF may resolve a goal and accept a narrative. A VA may do
    neither** (ruling 6) — both are judgements about the client relationship, not
    administration of it.
14. **"Changed course" is normal consulting** and is frequently the most valuable
    judgement the fractional made all quarter. The reason line is the whole mechanism
    that makes it read as judgement rather than as failure, which is why it is
    required rather than optional. A resolution vocabulary with no reason attached
    would make "changed course" indistinguishable from "gave up".

**What updates itself, and what a person types.**

15. **Automatic — everything structural**: task and project completion, the goal tree,
    the timeline, milestone dates as they are hit.
16. **By hand — two things only:**
    - **The measurable's current value**, through a **"record measurement" action**
      that keeps a **dated history**, so the measure can be charted over the
      engagement rather than overwritten to a single latest number.
    - **The outcome statement.**
17. Nothing else is hand-maintained. Any field that would need the fractional to
    remember to update it, and would silently go stale if they did not, does not
    belong in this module.

**AI's role.**

18. Claude drafts **the connective narrative** for a goal, from **that goal's own
    material only**: the client-facing lines on its task updates (FR-3.16), notes
    linked to its tasks, its milestones, and its measurements.
19. **It asserts nothing not present in that input** — the same constraint the digest
    carries, tested the same way (AC-3.5).
20. **The fractional edits and accepts.** It is **never auto-published**: an
    unaccepted draft is invisible to the client.
20a. **The structural half shows regardless** (ruling 3). A goal whose narrative has
    not been accepted still shows its measurable, its progress, its milestones and its
    timeline. Holding the goal back until someone writes prose would make the report's
    availability depend on the fractional's backlog — which is the failure mode of the
    artifact this replaces.

**Where it appears.**

21. **Always available in the client portal**, not only when something was sent. A
    report a client can only see if it was emailed to them is a document; this is a
    place they can go.
22. **Exportable as a branded PDF** for the quarterly-review conversation, using the
    **email layout's brand system** (`apps/crm/services/email_layout.py`,
    `templates/email/base.html`) and WeasyPrint, which Phase 4 already establishes for
    the strategy PDF. One brand system, not a third.

### Data model additions — settled 2026-09-16, subject to the usual review at build

On **`goal`**:

| Column | Type | Notes |
|---|---|---|
| `measurable_kind` | text? | **`numeric · qualitative`** (ruling 1); null only on a goal predating the module |
| `measurable` | text? | the name — "supervisor hours per week". Carried from `strategy_map_row.measurable` |
| `how_we_will_know` | text? | **qualitative only** (ruling 1): the sentence that stands in for a number |
| `measurable_unit` | text? | numeric only. "hours/week", "%", "days" — drives display, never arithmetic |
| `direction` | text? | **`up_is_good · down_is_good`** (ruling 2). Required when `measurable_kind = 'numeric'`. **Never inferred** |
| `baseline_value` | numeric? | what it read at engagement start |
| `baseline_at` | date? | when that reading was taken |
| `target_value` | numeric? | where it is meant to land |
| `horizon_days` | smallint? | 30 · 60 · 90, from the map row |
| `outcome_statement` | text? | the fractional's client-facing sentence. Carries the headline for a qualitative goal |

> **No `resolution` columns on `goal`.** Ruling 7 makes resolution append-only, and a
> single column with a reason beside it is the one shape that cannot express that — the
> second resolution overwrites the first and the history is gone. See `goal_resolution`.

New tables:

- **`goal_measurement`** — `id · tenant_id · goal_id · value numeric · measured_at date
  · recorded_by FK→user · note text?`. The dated history behind the current value; the
  "current value" is a read of the latest row, not a stored column that can drift.
- **`goal_milestone`** — `id · tenant_id · goal_id · title · due_date date? ·
  occurred_at date? · position · source_task_id FK→task?`. Occurred-vs-due is what lets
  the timeline show a beat as hit, late, or ahead without a status vocabulary of its
  own. **`source_task_id` is ruling 8**: a task marked as a milestone derives
  `occurred_at` from its completion, so the fact is maintained once. A standalone
  milestone has `source_task_id` null and its dates are typed.
- **`goal_resolution`** — `id · tenant_id · goal_id · resolution text · reason text
  (NOT NULL) · resolved_by FK→user · resolved_at timestamptz`. **Append-only**
  (ruling 7): a goal's current state is its latest row, and no row is ever edited or
  deleted. Resuming a paused goal appends; un-achieving an achieved goal appends a new
  line with its own reason. A goal with no rows is current. The reason is `NOT NULL` at
  the database, not a serializer convention.
- **`goal_narrative`** — the AI draft and its accepted form, per goal per report
  period, with an `ai_call_id` and an accept/edit trail.
- **`goal_report_export`** — `id · tenant_id · goal_id? · stored_file_id · exported_at ·
  exported_by`. **Ruling 4**: the PDF is a snapshot at export, kept as a `stored_file`
  and listed on the goal, so the document a quarterly conversation was held over still
  reads the way it read that day. `goal_id` null is an all-goals export.

Not proposed, deliberately: any stored "percent complete", any stored derived status
(FR-3.10's rule stands), any denormalised "current value" on `goal`, and any
`direction` inferred from baseline-versus-target.

### What it draws from

| Source | What it contributes | Module |
|---|---|---|
| `goal` + the new columns | the anchor, the measurable of either kind, the direction, the outcome statement | 3 / this |
| `goal_measurement` | baseline → current → target, and the chart from three readings up | this |
| `goal_milestone` | the dated beats on the timeline, standalone or derived from a task | this |
| `goal_resolution` | current versus historical, and the reasons that made it so | this |
| `goal_report_export` | the snapshot PDFs a quarterly conversation was held over | this |
| `project` · `task` · status rollup (`apps/work/status.py`) | the secondary completion bar and the goal tree | 3 |
| `task_update.client_facing_line` (FR-3.16) | the narrative's primary raw material | 3 |
| `note` rows linked to the goal's tasks | narrative material the fractional already captured | 2 |
| `strategy_map_row` via `source_map_row_id` | the measurable, the horizon, the original bottleneck and fix | 4 |
| `ai_call` | the spend and audit trail for every narrative draft | 0.5 |
| `email_layout` + `templates/email/base.html` + WeasyPrint | the branded PDF | 1 / 4 |
| client-company scoping | that a client sees only their own company's goals | 0.5 / 3 |

### Consequence for Phase 4 — a correction, not an addition

**Phase 4's map-row conversion must capture the measurable and prompt for its
baseline. Today it does not, and the gap is already in the documents:**

- `strategy_map_row` has a single free-text `measurable` column and a `horizon`.
- **`goal` has no measurable column at all** — only `source_map_row_id`.
- **AC-4.11 asserts that a converted record carries "owner, target date, and
  measurable."** With no column to carry it into, the measurable is reachable only by
  joining back to the map row, and the horizon is dropped outright.

So this is not new Phase 4 scope invented by this module; it is a promise Phase 4
already makes that the schema cannot currently keep. Three changes fall out:

1. **The `goal` columns above must exist before or with Phase 4's conversion**, or
   conversion has nowhere to put what AC-4.11 says it carries.
2. **Conversion must prompt for the baseline** — at conversion, while the fractional
   still has the diagnostic in front of them. A baseline asked for three weeks later is
   a guess, and a guessed baseline makes every later reading dishonest.
3. **Conversion carries the measurable's kind, not just its text** (ruling 1). It asks
   for name, unit, target and direction, and takes a qualitative "how we'll know"
   sentence when the measure is not a number — **prompting for structure, accepting
   text, never blocking**. A fractional mid-conversion with a prospect waiting must not
   be stopped by a form demanding a unit.

### Consequences elsewhere

- **FR-3.38 is replaced**, so **AC-3.26** ("on-demand report requires a login") and
  **matrix row 7.15** ("view the on-demand progress report") are reworded onto this
  module rather than deleted — the login requirement still holds.
- `frontend/src/screens/Report.tsx` and `ProgressReportView` are replaced, not extended.
- **The client activity log (FR-3.41) is untouched.** It is the honest flat log and
  should stay flat; the mistake was having only that shape.
- **The weekly digest stays exactly as it is** (ruling 5). Two artifacts, two jobs: the digest is a weekly "what moved", this is the periodic "where are we". Whether the digest should eventually borrow the goal anchor is revisited **after real use**, not decided now.
- New access-matrix rows are needed for: recording a measurement, writing the outcome
  statement, resolving a goal, accepting a narrative, and exporting the PDF. **Settled
  by ruling 6:** resolving a goal and accepting a narrative are **FF and assigned CF
  only — never a VA**. Client roles are read-only throughout. A VA may still record a
  measurement and export a PDF; neither is a judgement about the relationship.

### Rulings — all settled by the owner, 2026-09-16

The eleven questions this scope opened, with the answers. Each keeps its question
visible: a decision without the alternative it was chosen over is hard to revisit
honestly later.

| # | The question | The ruling |
|---|---|---|
| 1 | Structured or free-text measurables | **Two kinds** (option c). **Numeric**: name, unit, baseline, target, dated measurement history; headline is baseline → current → target. **Qualitative**: a "how we'll know" sentence; headline falls back to the outcome statement. The strategy session **prompts for structure and accepts text; it never blocks on it** |
| 2 | Direction of good | **Stored explicitly** — up-is-good / down-is-good, set at conversion or creation. **No inference** |
| 3 | What a client sees before a narrative is accepted | **The structure shows.** A goal is never held back waiting for prose |
| 4 | Live or snapshot PDF | **Snapshot on export**, kept as a `stored_file`, listed on the goal |
| 5 | Does the weekly digest gain the goal anchor | **No — the digest stays as it is.** Two artifacts, two jobs. Revisit after real use |
| 6 | Who may resolve a goal and accept a narrative | **FF and an assigned CF. A VA neither** |
| 7 | Can a resolution be reversed | **Resolutions append, never erase.** Resuming a paused goal appends; un-achieving an achieved goal is allowed and appends a new line with its own reason. **No resolution line is ever edited away** |
| 8 | Milestones versus tasks | **Separate table, plus one affordance**: a task can be marked as a milestone, deriving the milestone from its completion rather than being maintained twice. **Standalone milestones remain possible** |
| 9 | Charting | **Both portal and PDF, from three readings up.** Below three, baseline → current as text |
| 10 | Internal goals (no client company) | **Never appear in this report.** Confirmed |
| 11 | Numbering and name | **Keep Phase 4.5 / Module 4B, `FR-4B.x` / `AC-4B.x`.** Modules 5 and 6 are not renumbered |

**Added by the owner beyond the eleven.** A goal created by hand mid-engagement gets
**the same measurable prompt as one from conversion, at creation**, with **"not
measurable numerically" as an explicit choice rather than an empty field**. An empty
field records nothing about whether the question was considered; a deliberate choice
records that it was — and it is what keeps a goal added in month four reporting as well
as the ones the engagement opened with.

**Where the rulings changed the proposal, not just confirmed it.** Three are worth
naming, because they moved the schema rather than picking between drafted options:

- **Ruling 7 removed the `resolution` columns from `goal`.** Append-only history cannot
  live in one column with a reason beside it — the second resolution overwrites the
  first. It is now the `goal_resolution` table, with `reason` `NOT NULL` at the
  database.
- **Ruling 1 split the measurable in two**, which adds `measurable_kind` and
  `how_we_will_know` and makes `direction` and `measurable_unit` numeric-only.
- **Ruling 8 added `source_task_id` to `goal_milestone`**, which is what stops the same
  dated beat being maintained in two places.

**Still genuinely open, and deliberately so:** whether the digest should eventually
borrow the goal anchor (ruling 5 defers this to real use, not to a later guess).

### Done means

With the rulings settled the gate can be stated, and this is it. It becomes
`FR-4B.x` in `01_prd.md` when the module is written up in full; the numbering is the
only thing still to add.

1. The `goal` columns and the **five** new tables migrated: `goal_measurement`,
   `goal_milestone`, `goal_resolution`, `goal_narrative`, `goal_report_export`.
2. The portal report organised **by goal**, all of a client's goals, **current first,
   historical below**, with **any single goal openable on its own**.
3. **Two kinds of measurable**, displayed by their own rules: numeric leads with
   baseline → current → target; qualitative leads with the outcome statement over the
   "how we'll know" sentence.
4. **Direction of good stored, never inferred**, and required on every numeric measurable.
5. **Task and project completion present and subordinate**, in both kinds. **No
   percent-of-tasks-done headline anywhere.**
6. **Record measurement**, keeping the dated history; the current value is read from
   the latest row and never stored on the goal.
7. **The chart in portal and PDF from three readings up**; baseline → current as text
   below that.
8. **Resolution** into achieved / changed course / paused / retired, **append-only**,
   each line carrying a reason the database requires.
9. **Milestones**, standalone or derived from a task marked as a milestone.
10. **The outcome statement**, hand-written and updatable.
11. **The AI narrative** under the AC-3.5 faithfulness constraint, drafted from the
    goal's own material only, accept/edit, **never auto-published** — and the
    structural half showing whether or not it has been accepted.
12. **The branded PDF**, a snapshot at export, stored and listed on the goal.
13. **A goal created by hand gets the measurable prompt at creation**, with "not
    measurable numerically" an explicit choice.
14. **Internal goals never appear** in the report at all.
15. **FR-3.38's implementation removed, not left alongside** — `Report.tsx` and
    `ProgressReportView` go.

**Phase 4 must land its half first** (see the correction above): the `goal` columns
exist, conversion carries measurable kind, name, unit, direction and horizon, and
**prompts for the baseline at conversion**.

### Tests that will be non-negotiable

- **Tenant isolation and client-company isolation**, as every phase — a client of one
  company never sees another's goals, measurements, or narratives, **404 both ways**.
- **Role boundaries** for the new verbs, VA's exclusions asserted against the API body.
- **The narrative asserts no fact absent from its inputs**, tested as AC-3.5 is.
- **An unaccepted narrative is absent from the client's API response**, not merely
  hidden in the UI — the same standard as internal comments (AC-3.4).
- **A resolution cannot be stored without its reason**, at the database, not only the
  serializer.
- **A second resolution appends and the first survives it**, readable in full after a
  goal has been paused, resumed and achieved.
- **A task marked as a milestone derives its date from completion**, and un-completing
  the task does not leave a milestone claiming a date that never happened.
- **A VA cannot resolve a goal or accept a narrative**, and **a CF cannot on a client
  they are not assigned to** — asserted against the API body.
- **The chart is absent below three readings** and present at three.
- **Percent-of-tasks-done never appears as a headline figure** in the portal or the
  PDF — worth an explicit test, because it is the thing most likely to creep back in.

### Manual checks that will matter most

1. **Read a real goal's report as the client.** Does it read as value delivered? This
   is the same judgement Check 1 of Phase 3 asked for, on the artifact that was
   supposed to answer it.
2. **Resolve a real goal as "changed course" and read it back.** Does the reason line
   make it read as judgement, or as failure? If it reads as failure, the vocabulary or
   the layout is wrong and it is a bug in this module.
3. **Export the quarterly PDF and take it into a real client conversation.** Whether it
   survives that hour is the only honest test of the module.
4. **Record a measurement every week for a month on one real goal**, then read the
   chart. Three readings is the threshold on paper; whether it is the right one is a
   judgement only the owner can make, on real data.

### Report

The usual three values. The AI narrative's quality will be reported as **the owner's
judgement on N real goals**, with N — never as a pass.

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
5. **Known inputs from Phase 3 (owner, Check 5, 2026-09-14):** ~~the portal's **progress
   report** formatting~~ — **struck 2026-09-16: the progress report's formatting is
   superseded by Module 4B (Phase 4.5), so spend no design-pass effort on it.** The
   screen is being replaced, not restyled, and polishing it would be work thrown away.
   *(The **digest email** got its branded HTML layout in the email presentation pass,
   2026-09-15.)* The digest's structure and wording carry a rule (Module 3's aim: a
   report that reads as value delivered rather than a list of field changes) and stay as
   they are; this is layout and typography only.
6. **Known input from Phase 3 (owner, 2026-09-15):** the **client-activity notification email** to the practice (FR-3.40) — the **subject** still needs proper wording. *(Its body moved to the branded layout — who, what and when — in the email presentation pass, 2026-09-15.)* What it reports and when (the 30-minute batching, never an update made while acting as) stays as it is.

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
