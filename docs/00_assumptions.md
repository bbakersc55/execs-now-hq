# 00 — Assumptions Register

**Phase 0 · Execs NOW HQ · for owner review**

Every decision below is something `CLAUDE.md` does **not** settle. Nothing here contradicts `CLAUDE.md`; where it was explicit (Postgres, Claude-only, ports, roles, review queues, brand) I treated it as fixed and did not re-litigate it.

**How to review:** mark each item `A` (approve) or `C` (change, with a note). Anything marked `C` gets reworked before I write `01_prd.md` against it. Items flagged **[BLOCKING]** change the shape of the data model, so I need those resolved; the rest I can proceed under and revise cheaply.

Open questions I genuinely cannot answer myself are collected in §H at the end — those are questions, not assumptions.

---

## Review outcome — 2026-09-09

**Owner reviewed all 50 items.** Result: **48 approved**, **2 changed** (A2 broker, F16 sequencing), **5 approved with additions** (A3, C2, F7, F11, F14a), **all 7 open questions in §H answered**. A later review of `01_prd.md` added four more approved assumptions: **A2a** (synchronous magic-link send), **F17** (Outbox as send log), **F18** (stakeholder identity), **F19** (Gmail reply capture). Every mark is applied in the text below; changed and amended items are tagged inline.

**One new item was added during review and approved: `A2a`** — it falls out of the A2 decision (a single ORM-backed queue with no priority lanes): magic-link emails are sent **synchronously in the request**, everything else queues.

**Consequences routed to later documents, so they are not lost:**

| Carried to | What |
|---|---|
| `03_access_matrix.md` | H7's three Gmail rows: connect / send-as-self / draft-only |
| `04_build_plan.md` | F16 — Phase 6 inbound builds after or alongside the Railway move; local development by replaying Postmark JSON fixtures |
| `05_dev_environment.md` | A3 DNS records (DKIM `TXT`, Return-Path `CNAME`, inbound `MX`); C2 OAuth testing-mode note and the V1 verification lead time; A2's worker count, queue-flush-on-restore step, and `CONN_MAX_AGE=0`; H6's `DEV_REAL_SEND_ALLOWLIST` |
| `01_prd.md` | F14a's enumerated PDF exclusion list, as acceptance criteria |


---

## A. Infrastructure and background work

### A1. Job queue: **Django-Q2** (not Celery) **[BLOCKING]**

**Choice:** Django-Q2 with a Redis broker, one `qcluster` process, in both development and production.

**Why:** one process covers worker *and* scheduler (Celery needs `worker` + `beat` running separately, which is two more things to remember to start on a laptop), schedules and task results are ordinary Django models visible in the admin, and failures land in Postgres next to the review queues rather than in a separate result backend.

**Detail worth your attention:**
- Django-Q2's scheduler is **catch-up aware**: a schedule whose `next_run` has passed fires on the next cluster start. On a laptop that is off overnight, the 6am digest job runs when you open the lid instead of being silently skipped. Celery Beat drops missed windows by default. This matters for A6 as well.
- Cost of being wrong: I will write every task as a plain module-level function taking primitives (`run_digest(digest_id: str)`), never bound methods or ORM objects. Swapping to Celery later is then a decorator change plus a settings block, not a rewrite.
- Honest downside: Django-Q2 has a much smaller community than Celery and a thinner ecosystem for exotic routing/priority. At Beta volume (one tenant, tens of jobs/day) none of that is reachable.

`Approved.`

### A2. Broker: Django ORM on Postgres — no Redis  ·  **[C applied — owner decision]**

**Choice (yours, accepted):** Django-Q2 with the **Django ORM broker** on Postgres, in both development and production. No Redis service on the laptop or on Railway.

**You asked for a concrete failure mode at Beta volume. I do not have one.** The ORM broker's real ceiling is throughput — it polls a table taking row locks, which starts to matter somewhere in the thousands-of-tasks-per-minute range. One tenant at tens of jobs per day is nowhere near it. Broker parity is preserved and the laptop loses a service. Accepted as written.

Three consequences follow from it. None is a reason to reconsider; all three need handling in `05_dev_environment.md`:

1. **Worker sizing.** A Speech-to-Text transcription can occupy a worker for minutes. Run **at least 4 workers** so one long transcription cannot sit in front of a digest or a magic link.
2. **Backups now contain the queue.** `pg_dump` picks up queued tasks and schedules along with the data. That is a small benefit for restore consistency, but a restored database will replay stale tasks on cluster start — so the restore runbook must **flush the queue table before starting `qcluster`**.
3. **Connection use.** Run the cluster with `CONN_MAX_AGE=0` so idle workers do not pin Postgres connections; Railway's connection limit is the binding constraint later, not now.

`Applied.`

### A2a. Latency-critical email sends bypass the queue entirely  ·  **[NEW — arises from A2, needs a mark]**

**Choice:** **magic-link emails are sent synchronously inside the request**, not enqueued. Everything else (digests, referral touches, PDFs, notifications) goes through the queue.

**Why:** this is the one place A2's single shared queue bites. With no priority lanes in the ORM broker, a client clicking "email me a link" while a 40-minute recording is transcribing would wait behind it — a sign-in that appears broken. A magic-link send is one Postmark API call of a few hundred milliseconds; doing it in-request is both simpler and strictly more reliable than building a priority lane. If the send fails, the user sees the failure immediately and can retry, which is better than a silently dead queue job.

`Approved.`

### A3. Transactional email provider: **Postmark** (not Resend) **[BLOCKING]**

**Choice:** Postmark for all app-originated mail (digests, magic links, referral touches, strategy-session PDFs).

**Why:** Module 6 (unified client communication) needs **inbound** email parsing, and Postmark's inbound webhook with per-address routing is more mature and better documented than Resend's; its 45-day searchable per-message activity log is also the cheapest possible answer to "did the client actually get the digest?"

**Detail:** separate Message Streams for transactional (magic links, digest sends) and broadcast (referral touches) so a referral-touch complaint can never damage magic-link deliverability. Sender identity is a per-tenant `from_address` + `reply_to`, verified by DKIM/Return-Path on the tenant's domain.

**Carried to `05_dev_environment.md`:** the exact DNS records to add — DKIM `TXT`, Return-Path `CNAME`, and the inbound `MX` for `inbound.getexecutivesnow.com`. These have propagation lead time, so they are listed as a pre-Phase-1 action.

`Approved.`

### A4. Local email never reaches a real person

**Choice:** a `PUBLIC_BASE_URL` guard — when it points at `localhost`, all outbound mail is diverted to a local dev outbox (Mailpit) and a banner shows in the UI. No provider API key is loaded in dev by default.

**Why:** while the app lives on the laptop, every link it would email (magic link, portal task, PDF) points at `http://localhost:8100` and is useless to a client; better to make that structurally impossible than to remember it.

`Approved.`

### A5. Error tracking: Sentry, production only

**Choice:** Sentry free tier wired from Phase 1 but enabled only when `PUBLIC_BASE_URL` is not localhost.

**Why:** you will not watch a laptop's logs during a live client call; you will want the traceback afterwards.

`Approved.`

### A6. Google Drive polling on a laptop that is not always on **[BLOCKING]**

**Choice:** **cursor-based pull, never push.** Per tenant folder connection we store Drive's `startPageToken`; a Django-Q2 schedule calls `changes.list` every 10 minutes and advances the cursor only after each file is durably recorded.

**Why:** a cursor is a position, not an event — a laptop that was closed for three days asks Drive "what changed since token X" on next start and gets everything, in order, exactly once. Drive push notifications require a public HTTPS endpoint and expire on their own schedule, so they are unusable on a laptop and would silently stop delivering.

**Detail:**
1. `DriveWatch` row per tenant: folder id, `page_token`, `last_polled_at`, `last_error`.
2. Every file seen becomes a `MeetingSourceFile` row, unique on `(tenant, drive_file_id, drive_version)` — re-polling the same file never produces a second proposal.
3. A **"Sync now"** button in the UI runs the same task on demand, so you are never waiting on a timer during a working session.
4. Ingestion is a two-step commit: record the file first, parse with Claude second. If Claude fails, the file is still recorded and retried; the cursor never advances past unprocessed work.
5. On Railway this design is unchanged (it works and it is simple). Push notifications are a V1 optimisation, not a Beta requirement.

`Approved.`

### A7. GCS and GCP project

**Choice:** one dedicated GCP project for Execs NOW HQ holding: the backup bucket, the Speech-to-Text API, the Drive API credentials, and recording audio storage.

**Three credentials, three purposes, amended during the `05` review:**

| Purpose | Credential |
|---|---|
| **Backups** (`scripts/backup_db.sh`) | **gcloud CLI with your ADC** — no key file |
| **App runtime** (Speech-to-Text, GCS media, Drive without a tenant token) | **A dedicated service-account key** at `GOOGLE_APPLICATION_CREDENTIALS`, outside the repo |
| **Acting as a person** (Gmail send, tenant Drive) | That user's OAuth token, encrypted in `tenant_secret` (E1) |

**The app never uses gcloud ADC.** Your laptop's ADC is shared with another project and its quota-project setting cannot serve both, so the app would intermittently bill or fail against the wrong project. A key file also makes development identical to Railway, where interactive gcloud login does not exist.

**Why:** `CLAUDE.md` mandates a separate GCP project; separate service accounts mean revoking Drive access does not break backups.

`Approved.`

---

## B. Tenancy enforcement

### B1. Tenant scoping: contextvar + middleware + default manager, with a fail-closed default **[BLOCKING]**

**Choice:** a four-layer pattern, where layer 2 is the one that actually matters:

1. **`TenantScopedModel`** abstract base: `tenant = FK(Tenant, on_delete=PROTECT, db_index=True)`. Every domain table inherits it. A meta-test (B3) fails the build if a concrete model in a domain app does not.
2. **`current_tenant` contextvar**, set by `TenantMiddleware` from the authenticated user's `Membership`, and cleared in a `finally` block. Not a thread-local — a contextvar survives async and does not leak across a reused worker thread.
3. **`TenantManager` as the default manager**: `get_queryset()` filters on the contextvar and **raises `TenantContextMissing` when the contextvar is unset**, rather than returning everything. Fail-closed. A forgotten filter is a 500 in a test, not a silent cross-tenant leak in production.
4. **`Model.objects_all_tenants`** — an explicit, greppable escape hatch for migrations, management commands, and the backup script. Every use of it is expected to be justified in review.

**Why:** `CLAUDE.md` says never rely on views remembering to filter; the only version of that promise that holds under pressure is one where *not* scoping raises rather than returns rows.

**Also:**
- `save()` stamps `tenant` from the contextvar; a model `clean()` rejects any FK pointing at a different tenant (catches "assign task to a contact in tenant B").
- Background jobs have no request, so every task takes a `tenant_id` argument and opens an explicit `with tenant_context(tenant_id):` block — same manager, same guarantees.
- **Client users get a second scope layer:** FCC/ECC requests additionally bind `current_client_company`, and client-facing querysets filter on both. Tenant isolation and client-company isolation are separate mechanisms so a bug in one does not defeat the other.

`Approved.`

### B2. Postgres row-level security: **not in Beta**

**Choice:** application-layer scoping only; RLS noted as a V1 hardening option.

**Why:** RLS would give defence in depth but doubles the debugging surface (silent empty results) at exactly the phase where I am iterating on the schema fastest; the meta-test in B3 gets most of the safety for none of the cost.

`Approved.`

### B3. The two mandatory test families are a **registry**, not per-module hand-written tests

**Choice:** one `tests/test_tenant_isolation.py` and one `tests/test_role_boundaries.py` that iterate a registry of `(model, factory, endpoint, role → expected status)`. Adding a model or endpoint without registering it fails a meta-test.

**Why:** `CLAUDE.md` calls these non-negotiable; hand-written per-module tests decay the moment someone is in a hurry, whereas a registry that fails on omission cannot be forgotten.

`Approved.`

### B4. One user belongs to exactly one tenant in Beta

**Choice:** a `Membership` table (user × tenant × role) exists from migration 1, but the app assumes and enforces one membership per user until V1.

**Why:** modelling it as a table now costs nothing and avoids a painful migration; enforcing one-per-user now removes an entire class of "which tenant am I in?" UI from Beta.

`Approved.`

---

## C. Authentication

### C1. Google OAuth via django-allauth, invite-only

**Choice:** `django-allauth` for tenant-user Google sign-in, with the OAuth consent screen configured as **user type Internal** on the `getexecutivesnow.com` Workspace. Sign-in **fails** unless a `Membership` (or pending invitation) already exists for that email address. No self-serve signup, per `CLAUDE.md`.

**Amended during the `05` review — Internal, not External/Testing.** Two reasons, the second of which would otherwise have produced a recurring mystery bug:
1. **No Google verification is required for restricted scopes** under Internal.
2. **External apps left in Testing expire refresh tokens after 7 days.** Every Gmail connection and Drive watch would silently break about weekly, presenting as an intermittent fault rather than a configuration choice.

**The constraint this creates:** only `@getexecutivesnow.com` accounts can sign in with Google, so **any CF or VA needs an account in the Workspace domain**. Client users are unaffected — magic links only (C3, C4). Moving to External with CASA verification is the V1 task.

**Why:** allauth handles the OAuth dance, token refresh, and email verification correctly; writing that by hand is unpaid risk.

`Approved.`

### C2. Gmail send authorisation is a **separate** consent flow from sign-in

**Choice:** sign-in requests only `openid email profile`. A distinct "Connect Gmail" action requests `gmail.send` with offline access and stores a per-user refresh token (encrypted, per E1).

**Why:** a VA who will never send from the fractional's address should not be asked to grant send scope to log in, and Google's verification review is easier when the sensitive scope is optional and separately justified.

**Carried to `05_dev_environment.md`:** `gmail.send` is a **restricted scope**, but under the **Internal** consent screen in C1 it needs no verification at all during Beta, and refresh tokens do not expire. Google verification with a **CASA security assessment** becomes necessary only when the app moves to **External** so that another fractional's practice can use it — a **V1 task** with the longest lead time in the V1 plan, flagged now so it is not discovered the week of launch.

`Approved.`

### C3. Magic link implementation for client users **[BLOCKING]**

**Choice:** a stored single-use token row, hashed, short-lived, with a click-through confirmation page.

**Detail:**
1. `MagicLinkToken`: `tenant`, `user`, `token_hash` (SHA-256 of a `secrets.token_urlsafe(32)` value — the raw token exists only in the email), `purpose`, `expires_at`, `used_at`, `requested_ip`, `redirect_to`.
2. **TTL 20 minutes, single use.** Consuming a token invalidates every other outstanding token for that user.
3. **The link lands on a page with a "Sign in" button that POSTs**, rather than logging in on GET. Corporate mail scanners and link-preview bots follow GET links and would otherwise burn the token before the client clicks it. One extra click; removes the most common magic-link support ticket.
4. Request endpoint is **rate limited** (5/hour per email, 20/hour per IP) and always returns the same response — "if that address has access, we've sent a link" — so it cannot be used to enumerate client users.
5. On success: an ordinary Django session, **30-day rolling** for client users (they should not re-request a link weekly), 12-hour idle for tenant users.
6. `redirect_to` is validated against an allow-list of internal paths, never an arbitrary URL.

**Why:** stateless signed tokens (`itsdangerous`-style) cannot be revoked or made single-use without a table anyway, so the table is the honest design; hashing means a database read never yields a working credential.

`Approved.`

### C4. No passwords anywhere in Beta

**Choice:** tenant users use Google only; client users use magic links only. Django's password field stays unusable (`set_unusable_password()`) except for the local `createsuperuser` account.

**Why:** no password reset flow to build, no credential-stuffing surface, and one fewer thing to get wrong.

`Approved.`

---

## D. Data model conventions

### D1. UUID primary keys on all domain tables **[BLOCKING]**

**Choice:** `uuid4` primary keys, not auto-incrementing integers.

**Why:** record ids appear in magic links, client portal URLs, and emailed PDF links; sequential integers advertise your record counts and invite "what's at id-1?" probing across tenants.

`Approved.`

### D2. Soft delete on the records people regret deleting

**Choice:** `deleted_at` on Contact, Company, Note, Goal, Project, Task, Comment. Managers exclude soft-deleted rows by default. Hard delete only via an audited management command.

**Why:** a client user with task-create rights will eventually delete something they needed, and "restore it" should not mean "restore last night's backup."

`Approved.`

### D3. One `AuditEvent` table, not per-model history

**Choice:** `AuditEvent(tenant, actor, verb, target_type, target_id, payload jsonb, created_at)`, written for: review-queue approvals and rejections, every outbound send, PIN set/reset, pipeline stage changes, role and seat changes, imports, and deletes.

**Why:** these are the events you would ever have to answer a question about; full row-versioning on every model is storage and complexity Beta does not need.

`Approved.`

### D4. Times stored in UTC; rendered in the recipient's timezone

**Choice:** all timestamps UTC in the database. `Tenant.timezone` (default **`America/Denver`** — H3, answered) with a per-user override; digests, due dates, and PDF timestamps render in the recipient's zone.

**Why:** a client in a different zone receiving a "due today" digest at 9pm is a credibility problem, and it is free to get right at the start.

`Approved.`

### D5. Enumerations live in tables, not Python enums, where V1 will customise them

**Choice:** `PipelineStage` and `ContactType` are per-tenant rows seeded from a preset; task status and role codes stay as Python choices.

**Why:** V1 promises multi-discipline presets and per-tenant customisation of pipeline and contact types; status and role semantics are wired into permission logic and should not be user-editable.

`Approved.`

---

## E. Secrets and the Anthropic key

### E1. Per-tenant Anthropic key: encrypted at rest, write-only, validated on rotation **[BLOCKING]**

**Choice:**
1. `TenantSecret(tenant, kind, ciphertext, last4, created_at, rotated_at, verified_at, verified_by)` — `kind` covers the Anthropic key today and Gmail/Drive refresh tokens tomorrow.
2. Encrypted with **Fernet** (`cryptography`) using `FIELD_ENCRYPTION_KEY` from the environment. **The encryption key never lives in the database**, so a database dump — including the nightly GCS backup — contains no usable credential.
3. The field is **write-only across the entire API**: no serializer, admin page, log line, or error message ever returns it. The UI shows `sk-ant-…{last4}`.
4. **Rotation:** FF pastes a new key → the app makes one cheap validating call to the Anthropic API → on success the ciphertext is replaced atomically and `rotated_at` set; on failure nothing changes and the old key keeps working. One active key per tenant, no overlap window.
5. **Master-key rotation:** `manage.py rotate_field_encryption_key` re-encrypts every `TenantSecret` under a new Fernet key, supporting `MultiFernet` decrypt-old/encrypt-new so it can run without downtime.
6. **Development fallback:** if a tenant has no stored key, an `ANTHROPIC_API_KEY` from `.env` is used — local only, refused when `PUBLIC_BASE_URL` is not localhost — so Beta build-out is never blocked on the secrets UI existing.
7. Every Claude call records tokens and cost against the tenant (`AiCall` row) so key usage is attributable and you can see spend per module.

**Why:** `CLAUDE.md` requires encrypted per-tenant keys; the parts worth being deliberate about are that the key is unrecoverable from a backup, unreadable through any API path, and that rotation validates before it destroys the working key.

`Approved.`

### E2. Secret handling generally

**Choice:** `django-environ`, `.env` only, `.env.example` updated in the same commit as any new variable, and a pre-commit hook (`detect-secrets` or `gitleaks`) blocking commits containing key-shaped strings.

**Why:** `CLAUDE.md` requires the first two; the hook is what makes them true on a tired evening.

`Approved.`

---

## F. Module-shaping assumptions

### F1. `Contact` is the canonical person; a portal login is attached to it

**Choice:** every human is a `Contact` row. Granting portal access creates a `User` linked 1:1 to that Contact and consumes a seat on the client company. Tenant staff also have a Contact row.

**Why:** otherwise a client founder exists twice — once in the CRM and once as a login — and their meeting history splits between the two.

`Approved.`

### F2. Pipeline gets two non-linear stages beyond the four named

**Choice:** `contact → lead → qualified lead → client` as the forward path, plus `lost` and `dormant` as terminal/parked states any stage can move to and back from.

**Why:** without them every prospect who says no stays forever in "qualified lead" and the pipeline stops being usable after a month.

`Approved.`

### F3. Stage automations: task creation may fire automatically; email never does

**Choice:** a stage-change rule can (a) create a follow-up task immediately, or (b) generate a **draft** into the Outbox review queue. Drafts never send themselves, whether AI-written or template-filled.

**Why — and this is the one place I want explicit agreement:** `CLAUDE.md`'s rule is that *AI output* which would email a client or create records needs a human. A rule you configured that creates an internal task with a template title is deterministic, not AI, and has no outside-world effect — requiring approval there would make the automation pointless. Anything that reaches a client's inbox stays behind the queue regardless of who or what wrote it.

`Approved.`

### F4. Referral touches are generated ahead into a queue, never sent on a timer

**Choice:** a scheduled job drafts each due referral touch **3 days before** its cadence date into the Outbox. The FF/VA approves (or edits, or skips) and the app sends. An unapproved draft expires rather than sending.

**Why:** it preserves the review rule while still meaning you open the app to a ready-made queue instead of a blank page — the automation buys drafting time, not send authority.

`Approved.`

### F5. CSV import is a three-step, reversible batch

**Choice:** upload → column mapping (saved as a reusable mapping profile) → **dry-run preview** showing create / update / skip counts plus the first 20 resulting rows → commit inside one transaction, recorded as an `ImportBatch` that can be rolled back wholesale.

**Why:** `CLAUDE.md` requires a dry run before irreversible steps, and the first real import of your existing contacts is the single highest-consequence data event in Beta.

**Dedupe order:** exact email → (normalised name + company) → no match, create new. Ambiguous matches are listed for a human, not guessed.

`Approved.`

### F6. Note PIN: the smallest thing that works

**Choice:**
- Optional per-note 4–6 digit PIN, stored as a Django password hash. **The note body is not encrypted** — `CLAUDE.md` says the PIN gates viewing, and I am not quietly upgrading that.
- Unlocking a note grants access to *that note* for the browser session (or 30 minutes, whichever is shorter).
- 5 wrong attempts → 15-minute lockout on that note, logged as an `AuditEvent`.
- **Reset is FF-only, by emailed link, and clears the PIN rather than revealing it.** The note becomes readable to anyone with normal access from that point, and the reset is audited.
- **Stated plainly so it is not mistaken for something stronger:** this protects a note from a shoulder-surfer, a VA, and a casual browse. It does not protect it from the FF, from a database dump, or from the backup file. If a note needs protection from those, it should not be in the app.

**Search behaviour:** a locked note appears in search results as a locked stub — title and linked contact only, no body or summary — unless unlocked.

`Approved.`

### F7. Recording pipeline and audio retention

**Choice:** browser `MediaRecorder` → upload to GCS → Google Speech-to-Text long-running recognise → Claude summary → Note. Soft cap of 60 minutes per recording.

**Amended per your mark:**
- **(1) Consent reminder.** Starting a recording shows a one-line reminder to confirm the other parties consent to being recorded. Dismissible per session, not per recording.
- **(2) Retention is a per-tenant setting**, `audio_retention_days`, **defaulting to 30** rather than being fixed. Transcript and summary are always retained. Setting it to `0` means delete as soon as transcription succeeds; the UI states plainly that this forfeits the ability to re-run a failed or poor transcription.

**Why:** the transcript is the artefact of value; retained meeting audio is a liability with no offsetting use, and 30 days is enough to re-run a failed transcription.

**Review point:** the Claude summary is presented alongside the transcript for the author to accept or edit before the note is saved — no summary is silently attached.

`Approved.`

### F8. Task hierarchy: Goal and Project are both optional above a Task

**Choice:** strictly three levels (`Goal → Project → Task`), but `project` and `goal` are nullable on a Task. Depth is never more than three; a **checklist item** (a flat list on a Task) covers the "sub-step" need instead of nested tasks.

**Why:** `CLAUDE.md` wants client users to use this as their general task tool, and forcing every quick task into a Goal and Project would make them stop using it — while nested subtasks would quietly turn three levels into unlimited ones.

`Approved.`

### F9. Task status set includes "Waiting on client"

**Choice:** `Not started · In progress · Blocked · Waiting on client · Done · Cancelled`.

**Why:** the distinction between "I am stuck" and "you are the blocker" is the single most useful thing a fractional's progress report can say, and it cannot be reconstructed later from a generic "Blocked".

`Approved.`

### F10. Comments have a visibility flag; internal work is not accidentally client-facing

**Choice:** `Comment.visibility ∈ {internal, shared}`. Client users only ever see `shared` and can only create `shared`. Tasks additionally carry `is_client_visible`.

**Why:** the same task record has to carry both "here's what we delivered" and "chase their controller again"; without a flag, one of those two conversations moves off the platform.

`Approved.`

### F11. Progress digests: generated ahead, approved in a batch, never auto-sent when AI-written **[BLOCKING — most important item in this document]**

**Choice:**
1. A digest is assembled from **`TaskUpdate` events**, not from a diff of the row. When a tenant user changes status or adds narrative, the update carries an optional **client-facing line** ("what this means for you"). Digest content = status transitions + those lines, in the fractional's words.
2. **Claude drafts the connective prose** — the opening summary that turns a list of transitions into "here is the value delivered this week." It never invents a status or a fact; it is given only the transitions and the human-written lines.
3. **Every AI-drafted digest is generated 24 hours before its send window and lands in an approval screen** listing all pending digests, with per-digest approve / edit / skip and an "approve all" for a reviewed batch. **An unapproved digest does not send.** It expires and rolls into the next period.
4. **Deterministic digests may send without approval** — *gated by the master switch in 4a.* If a tenant turns off AI prose, the digest is a template containing only status transitions and text a human wrote: no AI output, therefore no review requirement.
4a. **Master switch, per tenant: `hold_all_digests`, default ON for Beta.** While ON, **every** digest waits in the approval screen regardless of how it was composed — AI-drafted or deterministic. When switched OFF, behaviour is exactly as item 4 describes: AI-drafted digests still require approval, deterministic digests send on cadence. This is the safe default and the answer to H4.
5. **Cadence** per stakeholder: `every_update` (batched with a 30-minute quiet window so one editing session sends one email, not six), `weekly` (default; anchored to a per-tenant send day and hour in tenant timezone), `monthly`.
6. Every digest send is an `AuditEvent` and is visible on the task/project timeline, so "did they hear about this?" is answerable.

**Why:** this is the part of the product the client experiences, so it is the part that must never surprise you by sending. Generating ahead is what makes a review queue tolerable at weekly cadence instead of a chore that gets switched off. Point 4 is a real distinction worth having — it lets a tenant who wants reliable unattended weekly reporting have it, without ever letting AI-written prose reach a client unreviewed — and 4a means a tenant has to make a deliberate, visible decision before any digest sends unattended. Beta ships held.

`Approved.`

### F12. Stakeholders attach at any level; the task-level entry wins

**Choice:** a stakeholder (a Contact or User, with a cadence) can be attached to a Goal, a Project, or a Task. Effective stakeholders for a task = the union of all three, de-duplicated per person, with the most specific attachment deciding cadence.

**Why:** `CLAUDE.md` requires task-level stakeholder lists, but nobody will re-add the client founder to forty tasks — project-level inheritance is what makes the task-level list survive contact with real use.

`Approved.`

### F13. Strategy session: public tokenised pre-call form, polled live view, WeasyPrint PDF

*Revised 2026-09-09 against the delivered Operations seed template — see H1, now answered.*

**Choice:**
- Pre-call form is a **public URL with a signed, expiring token** (30 days) — no login, resumable, autosaving. It renders exactly the questions whose `ask_when` is `precall` (seed: Section 1 Snapshot, Section 2 Six Key Components; Section 3 items 1–3 are flippable to precall per template).
- The live in-call view **polls every 5 seconds**. No WebSockets/ASGI in Beta.
- Claude's drafted Strategy Map rows and the mirror land in an **accept / edit / discard tray** beside the live view — the fractional's acceptance is what creates a row.
- PDF via **WeasyPrint** (HTML + CSS, so the brand palette is one stylesheet).
- "Emailed same day" = the FF reviews the generated PDF and clicks send. Not automatic.

**Why:** polling removes a whole deployment tier for a screen one person looks at for an hour; WeasyPrint means the PDF is styled with the same CSS discipline as the app.

`Approved.`

### F13a. The template is data, not code: `ask_when` and `must_ask` are per-question fields

**Choice:** `StrategyTemplate → Section → Question`, where every Question carries `ask_when ∈ {precall, live}` (fractional-overridable per question, per the seed), `must_ask` (the ★ priority flag), `order`, `group` (the diagnostic's six areas), and an optional fractional-only note field that is **never rendered on the prospect-facing form or the outbound PDF**.

**Why:** the seed explicitly makes `ask_when` overridable and V1 promises per-discipline templates — so the flow has to be editable rows, not a hard-coded form.

`Approved.`

### F13b. Five answer shapes, carried as a `response_schema` on the question — not five tables

**Choice:** the seed's sections need exactly five answer shapes. Model them as one `Answer` row with a JSONB `value` validated against the question's declared shape:

| Shape | Used by | Fields captured |
|---|---|---|
| `free_text` | §1 Snapshot, §3 Where they want to go | one text body |
| `rating_1_10` | §2 Six Key Components | integer 1–10 + optional comment |
| `diagnostic_triple` | §4 Diagnostic | *What they said* · *Who or what causes it* · *What have they tried — why didn't it stick* |
| `value_pair` | §7 What they value | *Value (their words)* · *Why it matters* |
| `agreed_note` | §9 Scope agreement | *Agreed on the call* (bool) · *Notes* |

§8 Two paths is a fixed two-row structure (`path_reaction`: *Their reaction* · *Honest risk* · *Leaning*) rather than a general shape, since there are always exactly two paths.

**Why:** one answer table with a validated shape keeps global search, PDF rendering, and the Claude prompt-builder each written once; a table per shape would triple all three for no gain.

`Approved.`

### F13c. Six Key Components scoring is computed, not stored

**Choice:** the app computes the average and flags the lowest-scoring component ("lowest score = where to look first") at read time, and passes that flag to Claude as a hint when drafting the mirror. No denormalised score column.

**Why:** six integers are free to average on read, and a stored aggregate is one more thing that can drift out of date when the prospect edits the form before the call.

`Approved.`

### F13d. Merge fields resolve at render time and degrade to a visible note

**Choice:** `{Visionary}` `{Integrator}` `{Location A}` `{Location B}` `{Company}` `{Session date}` `{Fractional name}` resolve from the session's linked Contact/Company at render. Per the seed, an unresolved `{Integrator}` renders the question with a **"no Integrator identified"** note rather than a blank or a literal brace.

**Why:** the seed calls for graceful degradation by name; a literal `{Integrator}` on a prospect-facing form is the kind of thing that ends a credibility conversation early.

`Approved.`

### F13e. The live view shows section timing and must-ask progress

**Choice:** the in-call view displays the seed's section budget (10 / 25 / 5 / 15 / 5 / 10 min, ~75 total) as elapsed-vs-budget per section, plus a count of unanswered ★ `must_ask` questions.

**Why:** the seed sets a time budget and marks the questions to prioritise if time is short — surfacing both is what makes that guidance operative during a live call rather than advice in a document.

`Approved.`

### F13f. The worked example row ships as seeded example content

**Choice:** the supervisor-overload row from the seed (1 supervisor / 14 sites → area lead per 8 sites, inspections to app → Integrator → 60 → inspections per site per month) ships as the in-app example on an empty Strategy Map, clearly labelled as an example and dismissible.

**Why:** the seed asks to keep it as the in-app example, and an empty map with a filled example row is a much better prompt to a fractional mid-call than an empty map with column headers.

`Approved.`

### F14. Conversion: each map row becomes a Goal **or** a Project, chosen per row

**Choice:** on conversion to client, the Strategy Map is shown as a proposed tree where the fractional picks **per row** whether it lands as a Goal or a Project (per the seed), with everything editable and de-selectable. The row's owner, 30/60/90 target, and measurable carry across. Nothing is created until the FF confirms. Created rows keep a link back to the map row that produced them.

**Why:** the seed specifies the per-row choice; the back-link is what later lets a progress report say "this is the bottleneck you told us about in March," and what makes the 90-day scope in §9 auditable against what was actually delivered.

`Approved.`

### F14a. The outbound PDF excludes fractional-only content by default, with an explicit per-section include toggle

**Choice:** the same-day PDF renders Snapshot, the Six Key Components chart, the mirror, the Strategy Map, the two paths, and what they value. It **excludes by default**: every fractional-only note field, the Strategy Map's *Notes / mechanics from experience* column, §4 diagnostic internal observations, §3 item 4 (the unasked Visionary/Integrator alignment observation), and all of §9 including the investment range. The send screen shows each excluded block with an explicit "include in PDF" toggle, defaulted off, and a preview of exactly what the prospect will receive.

**Why:** the seed says these are excluded "unless the fractional includes them," and the failure mode — emailing a prospect your private read on whether their #2 is up to the job, or your internal pricing notes — is severe enough that the default must be off and the preview must be real.

`Approved.`

### F15. Meeting ingestion accepts Google Docs, plus `.txt` and `.docx`

**Choice:** Google Docs exported as plain text (the Gemini notes case), plus dropped `.txt`/`.docx`. PDFs and audio files in the folder are recorded and skipped with a visible reason.

**Why:** Beta's real input is Gemini notes; silently ignoring an unsupported file is worse than saying why it was skipped.

**Every proposal is inert until approved:** contact match, action items, and deliverable-tasks are all rows in a pending state. Rejecting a proposal keeps it (as rejected) so the same file does not come back next poll.

`Approved.`

### F16. Module 6 inbound email: Postmark inbound with a per-thread reply address  ·  **[C applied]**

**Choice (design unchanged, sequencing corrected):** app-originated client email uses a reply address of the form `reply+<thread_token>@inbound.getexecutivesnow.com`. The inbound webhook matches on the token first, then falls back to sender email → Contact. Unmatched inbound lands in an **unmatched queue** for a human to file, never a silent drop.

**Why:** a token in the reply address is the only threading method that survives clients replying from a different address than the one we mailed; the fallback and the queue cover the rest.

**Your correction, accepted and carried into `04_build_plan.md`:** a webhook cannot reach a laptop, so **the inbound half of Module 6 only functions after the Railway move.** Phase 6 is therefore built **after or alongside the Railway migration**, and Phase 6's completion criteria distinguish the outbound half (works locally) from the inbound half (needs a public URL).

**How inbound is developed locally without a public endpoint:** the webhook handler is written as an ordinary view over a parsed payload, and developed by **replaying captured Postmark inbound JSON** against it — a `manage.py replay_inbound <fixture.json>` command plus a fixture set covering the cases that matter: token match, sender-email fallback, no match, reply-with-quoted-history, multi-recipient, and an attachment. Those fixtures become the module's regression suite, so the Railway cutover is verifying transport, not logic.

**Deliberately not doing:** tunnelling a public URL to the laptop (ngrok/Cloudflare Tunnel). It would put a live internet endpoint on your machine to save writing fixtures that are worth having anyway.

**Scope note:** two-way Gmail sync (pulling the fractional's whole mailbox) is **not** in Beta. Beta threads replies to mail the app sent.

`Applied.`

---

## G. Frontend, API, and testing

### F17. The Outbox is both the approval queue and the complete send log  ·  **[ADDED in PRD review]**

**Choice:** every app-originated email is an Outbox row. Rows that a human explicitly clicked to send — the strategy session PDF, cadence-change confirmations, magic links — are written **directly as `sent`** with no `pending_approval` state.

**Why:** it reconciles "the Outbox is the single queue" with the three producers that legitimately have no queue in front of them, and it means "did we ever email this person?" is one query against one table. Requiring approval for a button the user just pressed would be theatre, not a control.

`Approved (PRD review item 6).`

### F18. A stakeholder is a Contact; a portal login is orthogonal  ·  **[ADDED in PRD review]**

**Choice:** stakeholder rows point at Contacts, not Users. Digests go to the Contact's primary email whether or not that person can sign in. The cadence-change link in a digest footer is authenticated by a **signed, expiring token bound to that stakeholder row**, granting exactly one capability — read and change that row's cadence — and nothing else.

**Why:** the common case is a client CFO who reads the weekly report and never opens the portal. Requiring a User row would either create dormant accounts that consume seats or silently drop those recipients.

`Approved (PRD review item 11).`

### F19. Capturing replies to personal Gmail sends: two tiers  ·  **[ADDED in PRD review]**

**Choice:**

**Tier 1 — Reply-To rewriting. Beta default, no new scope.** Personal mail sent through the Gmail API keeps the fractional's `From` but carries `Reply-To: reply+<thread_token>@inbound.getexecutivesnow.com`. The client's reply reaches the inbound webhook and threads normally; the app forwards it to the fractional's own mailbox so nothing disappears from where they expect it. **Covered by the `gmail.send` scope already granted.**

**Tier 2 — Polling known thread IDs. Opt-in, restricted scope.** The app stores each `gmail_thread_id` it creates and polls `users.threads.get` for those threads every 15 minutes, ingesting messages it did not send. This closes Tier 1's blind spot: a reply the fractional types natively in Gmail.

**Why polling known threads rather than `users.history.list`:** Gmail's history has a limited retention window, so a laptop closed for ten days can return `404 historyId not found` and force a full resync. The set of threads the app started is always known and bounded, so fetching them directly is both simpler and free of that failure mode.

**The cost, stated plainly:** Tier 2 needs **`gmail.readonly`** — a **restricted** scope granting read access to the entire mailbox. No narrower Gmail scope reads only chosen threads. Beta absorbs this because the OAuth app is in testing mode with one test user (C2). **For V1 it is a hard gate: a CASA security assessment.** Tier 1 exists precisely so the product does not depend on clearing it.

**Not chosen:** full two-way mailbox sync. Tier 2 reads only threads the app started, and that boundary is the difference between completing the app's own conversations and ingesting the owner's private mail.

`Approved (PRD review item 17).`

### G1. React 19 + Vite + TypeScript, TanStack Query, React Router, Tailwind, shadcn/ui

**Choice:** as listed, with the brand palette (`#0A3A65`, `#F58220`, `#6D6E71`, `#939598`) defined once as CSS custom properties and referenced through Tailwind theme tokens.

**Why:** shadcn/ui is copy-in components you own and can restyle, which suits a product that must be re-themable per tenant in V1; the token indirection is what makes that a config change rather than a find-and-replace.

`Approved.`

### G2. Session-cookie auth, CSRF enforced — no JWT

**Choice:** DRF with Django session authentication. Vite proxies `/api` to `:8100` in dev; Django serves the built bundle in production, so it is same-origin.

**Why:** same-origin session cookies are the least dangerous option available and remove token storage, refresh, and revocation from the design entirely.

`Approved.`

### G3. Tests: pytest + pytest-django + factory_boy, Postgres in CI

**Choice:** as listed; GitHub Actions runs the suite against a Postgres service container on every push. No hard coverage percentage gate.

**Why:** a percentage gate rewards testing getters; the registry families in B3 plus per-module acceptance tests are what actually protect this product.

`Approved.`

### G4. Migrations are never squashed during Beta, and data migrations are separate

**Choice:** every migration reversible; schema and data migrations in separate files; anything destructive gets a dry-run report before it runs, per `CLAUDE.md`.

`Approved.`

### G5. Display name in one constant

**Choice:** `PRODUCT_NAME = "Execs NOW HQ"` in `config/branding.py`, exposed to the frontend through a single `/api/branding` payload alongside the palette.

**Why:** `CLAUDE.md` asks for one constant; routing it through the same payload as the palette means V1 per-tenant white-labelling changes data, not code.

`Approved.`

---

## H. Open questions — **all answered 2026-09-09**

**H1. Strategy session template — ANSWERED.** Resolved by `strategy_session_seed.md`. Six Key Components: **Vision, People, Data, Issues, Process, Traction**, self-rated 1–10. The full nine-section Operations template is seeded verbatim, including `ask_when`, `must_ask` ★ flags, merge fields, section timings, and the worked example row. Assumptions **F13, F13a–F13f, F14, F14a** were rewritten against it.

**H2. Mail addressing — ANSWERED.** App-originated mail from **`info@getexecutivesnow.com`**. Reply threading via **`reply+<token>@inbound.getexecutivesnow.com`**. Per-tenant sending domains are a **V1** concern; Beta hard-codes the Executives Now tenant's addresses as configuration, not as a data model gap — `Tenant.from_address` and `Tenant.inbound_domain` still exist as fields from migration 1.

**H3. Timezone — ANSWERED.** Tenant default **`America/Denver`**. Applied to D4.

**H4. Digest carve-out — ANSWERED.** The carve-out exists, gated by **`hold_all_digests`, default ON for Beta**. Applied to F11 as item 4a.

**H5. Referral touch default cadence — ANSWERED.** **Monthly**, when the FF has not set one per contact.

**H6. Real outbound mail from the laptop — ANSWERED (middle path).** A4 stands, plus a **`DEV_REAL_SEND_ALLOWLIST`** environment variable holding addresses that receive genuinely delivered mail from the laptop build. Everything to any other address goes to the dev outbox. You have accepted that links in those real sends point at `localhost` and are useful only on the machine that sent them.

*Two guardrails I am adding to that, because the whole point of A4 was to make a mis-send structurally impossible and an allow-list reopens the door a crack:*
- The allow-list is **exact-address match only** — no domain wildcards. `@getexecutivesnow.com` as an entry is rejected at startup with an explanatory error, because one wildcard entry would put every colleague and every client at that domain back in range.
- Every real send from a localhost build is **logged as an `AuditEvent` and shown in the UI with a "sent for real, from dev" marker**, so a message you did not expect to leave the machine is visible after the fact rather than invisible.

**H7a. Pre-call invites are the one send a VA may make directly — refinement, added during data-model review.** The Module 4 VA story ("I schedule sessions and send pre-call form links") and H7 ("VAs draft into the Outbox") contradicted each other. Resolution: a **`precall_invite` is a template-only, non-AI email from the tenant address** containing a tokenised form link and no free prose. **VAs may send it directly** (`direct-to-sent`). Every other VA send remains a `pending_approval` draft. The distinction that makes this safe is the same one behind assumption F3: there is no AI output and no discretionary content, so there is nothing for a reviewer to catch.

**H7. Gmail send authority — ANSWERED.** **VAs** draft into the Outbox for FF approval and **cannot connect Gmail send at all** (the connect action is not offered to them). **CFs** can connect their own Gmail and send from their own address, but only to contacts on client companies they are **assigned to**. **FF** unrestricted. Carried into `03_access_matrix.md` as three distinct rows: *connect Gmail*, *send from own address*, and *draft into Outbox*.

---

## I. Settled by the kickoff document — recorded here, not assumed

These came from `Execs_NOW_HQ_Kickoff.md` and are facts, not proposals. They feed `05_dev_environment.md` directly and need no mark.

- Local database: **`execsnowhq_dev`**, created with `createdb`.
- GCP project id: **`execs-now-hq`**; backup bucket **`gs://execs-now-hq-db-backups`**.
- Backup auth is **gcloud application-default credentials** under `bryan.baker@getexecutivesnow.com`, with the quota project set to `execs-now-hq`. So `scripts/backup_db.sh` uses ADC, not a downloaded service-account key file — which also means one fewer secret in `.env` than I had planned in A7. **A7 is amended accordingly:** a service-account key is needed for Drive and Speech-to-Text, but not for backups.
- `scripts/backup_db.sh` is run **manually at the start of each session** as well as nightly on a timer. `05_dev_environment.md` will cover both paths.
- Repo settings (`.claude/settings.json`, `.gitignore`) are already committed.
- Production host: **`app.getexecutivesnow.com`** on Railway, once the first client portal user exists.

---

## Status

**Closed. All 50 items marked, all 7 open questions answered.** 48 approved as written, 2 changed (A2 broker, F16 sequencing), 5 approved with additions (A3, C2, F7, F11, F14a), 1 added during review and approved (A2a).

This register is the reference for every later document in Phase 0. Nothing in it is outstanding.
