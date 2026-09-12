# 01 — Product Requirements: Beta

**Phase 0 · Execs NOW HQ · for owner review**
**Built on:** `CLAUDE.md`, `00_assumptions.md` (all marks applied), `strategy_session_seed.md`.

---

## How to read this document

Six modules, in `CLAUDE.md`'s build order. Each carries: **Purpose** (one paragraph), **User stories** by role, **Functional requirements** (numbered `FR-<module>.<n>`), **Out of scope for Beta**, and **Acceptance criteria** (`AC-<module>.<n>`) written so you can verify each one by hand without reading code.

Two conventions worth knowing before you start:

- **Where a role has no surface in a module, I say so rather than inventing a story.** Client users have no access at all to four of the six modules, and pretending otherwise would put fictional rows in the access matrix.
- **Acceptance criteria are written as procedures with expected results**, not as aspirations. "Digests work" is not an acceptance criterion. "Make four changes in five minutes to a task with an `every_update` stakeholder; exactly one email arrives" is.
- **Numbering is stable.** Requirements added during review are inserted with a letter suffix (`FR-1.6a`) rather than renumbering the list. Every FR and AC number in this document is a permanent identifier that `03`, `04`, and the test registry will cite, so a number never changes meaning once written.

Requirements marked **⛔ REVIEW QUEUE** are points where something would otherwise reach a client or create a record without a human. They are collected in one register in §2 below.

---

## 1. Cross-cutting requirements

These are not a module. They ship in Phase 1 and every later module inherits them.

**FR-0.1 — Tenancy.** Every domain row carries `tenant_id`. Scoping is enforced by the fail-closed manager in assumption B1: an unscoped query raises rather than returning rows. No view is trusted to remember.

**FR-0.2 — Client-company scoping is a second, independent layer.** FCC/ECC requests bind both `current_tenant` and `current_client_company`. A bug in one layer must not defeat the other.

**FR-0.3 — Roles.** FF, CF, VA, FCC, ECC exactly as `CLAUDE.md` defines them. `03_access_matrix.md` is the source of truth; this document must not contradict it.

**FR-0.4 — Audit.** Every approval, rejection, send, PIN action, stage change, role change, import, and delete writes an `AuditEvent`.

**FR-0.5 — Time.** Stored UTC. Rendered in the recipient's timezone. Tenant default `America/Denver`.

**FR-0.6 — Branding.** `PRODUCT_NAME` and the palette (`#0A3A65`, `#F58220`, `#6D6E71`, `#939598`) come from one config surface, served to the frontend as data.

**FR-0.8 — Tenant staff management is FF-only.** Inviting a CF or VA, changing a member's role, and removing a member are all FF-only actions (matrix rows 3.16–3.18).
**FR-0.8a** — invitation is by email against a pre-created `membership`; sign-in fails for any address without one (C1).
**FR-0.8b** — a role change takes effect on the member's next request.
**FR-0.8c** — **removal cascades:** sessions invalidated; for a CF, every live `client_assignment` closed and their Gmail connection deleted with its stored token. Nothing they authored is removed — a departed CF's tasks, notes, and sent mail stay on the record.

**FR-0.9 — AI spend is visible to the FF only.** The `ai_call` log and any per-module cost view are FF-only (matrix row 3.19). Spend is financial: `CLAUDE.md` gives a VA no financials, and a CF's financial visibility is limited to their assigned clients, which tenant-wide API spend is not.

**FR-0.7 — Outbound mail safety. On a build where `PUBLIC_BASE_URL` is localhost, mail goes to the dev outbox unless the recipient is an exact match in `DEV_REAL_SEND_ALLOWLIST`. Real sends from a dev build are audited and badged in the UI.

---

## 2. The review queue register

This is the answer to "call out every place a review queue sits between AI output and a real-world effect," in one table. Every row is a point where the app stops and waits for a person.

There are **two review surfaces**, not one, and keeping them distinct matters because they fail differently:

- **The Outbox** — everything that would leave the building as email. One queue, many producers. A failure here reaches a client's inbox.
- **Proposal queues** — everything that would create or modify records. A failure here corrupts your data.

| # | Producer | Module | Surface | What is held | Effect if approved | Effect if never actioned |
|---|---|---|---|---|---|---|
| R1 | AI-drafted referral touch | 1 | Outbox | 3–5 line email draft | Sends from tenant address | Expires unsent at cadence date |
| R2 | Stage-change email rule | 1 | Outbox | Template-filled draft | Sends | Expires unsent |
| R3 | Claude summary of a recording | 2 | Inline accept/edit | Summary text | Attached to the Note | Note saves with transcript, no summary |
| R4 | **AI-drafted progress digest** | 3 | **Digest approval screen** | Whole digest, per stakeholder | Sends to stakeholder | Expires; content rolls into next period |
| R5 | **Deterministic digest, `hold_all_digests` ON** | 3 | Digest approval screen | Whole digest | Sends | Expires; content rolls forward |
| R6 | Claude-drafted Strategy Map rows | 4 | Live accept/edit/discard tray | Candidate map rows | Row created on the map | No row exists |
| R7 | Claude-drafted "mirror" | 4 | Live accept/edit tray | Goal + unlocks-most text | Saved to session | Blank, fractional writes it |
| R8 | Strategy session PDF | 4 | Send screen with preview | PDF + exclusion toggles | Emails prospect | Not sent |
| R9 | Strategy Map → task conversion | 4 | Conversion screen | Proposed Goals/Projects/Tasks | Rows created | No rows created |
| R10 | Meeting ingestion — contact match | 5 | Meeting review queue | New-contact candidate **or** ranked existing matches | Contact created or linked | Nothing created |
| R11 | Meeting ingestion — action items | 5 | Meeting review queue | Extracted tasks with dates | Tasks created | Nothing created |
| R11a | Claude-drafted meeting summary | 5 | Meeting review queue | Summary text | Stored on the Meeting record | Meeting created with no summary |
| R12 | Meeting ingestion — deliverables | 5 | Meeting review queue | Tasks + stakeholder notifications | Tasks created, stakeholders attached | Nothing created |
| R13 | Inbound reply, unmatched | 6 | Unmatched queue | Reply needing a human to file | Threaded to a contact | Stays queued, never dropped |

### What is deliberately *not* a review queue

Stated explicitly so the rule is applied where it belongs and not everywhere:

1. **A stage rule creating an internal task** (FR-1.14). Deterministic, configured by you, no outside-world effect. Approved as assumption F3.
2. **A client user creating a task or comment** (FR-3.31). A human writing about their own work. Putting a review queue in front of your client's own task list would make the portal useless.
3. **A tenant user's own email, written by hand and sent from their own Gmail.** No AI involved.
4. **Deterministic digests when `hold_all_digests` is OFF** (FR-3.24). No AI output in the message — only status transitions and text a person wrote. This is the single carve-out, it is off by default in Beta, and turning it on is a deliberate, visible act.

---

## 3. Module 1 — Contacts & Pipeline (CRM)

### Purpose

The record of every person and company the practice deals with, and the spine everything else attaches to. A fractional's book of business is currently spread across a mail client, a spreadsheet, and memory; this module consolidates it into contacts and companies with a type (prospect, client, referral partner, vendor, coworker), moves prospects along a pipeline with automations that fire on stage change, and imports the existing book from CSV without losing or duplicating anyone. It ships first because Modules 2 through 6 all attach to a contact: a note is about someone, a task is for someone, a meeting proposal has to match someone, and an email threads to someone.

### User stories

**FF — Founder fractional**
- As the FF, I import my existing contacts from a CSV and see exactly what will be created, updated, and skipped **before** anything is written, so my book of business is not silently mangled.
- As the FF, I move a prospect from lead to qualified lead and have the follow-up task created for me, so the next action never depends on my memory.
- As the FF, I configure what happens on each stage change once, rather than doing it by hand every time.
- As the FF, I open the Outbox and see referral touches already drafted for the partners due this month, so maintaining those relationships is a review task, not a writing task.
- As the FF, I find a vendor by service category when a client asks me who does commercial HVAC.
- As the FF, I merge two contacts that turned out to be the same person after an import, without losing the history on either.
- As the FF, I assign a CF to a client company so they can see and work that account.

**CF — Contractor/employee fractional**
- As a CF, I see the contacts on the client companies I am assigned to, plus prospects I own, so my view is my actual work.
- As a CF, I move my own prospects through the pipeline and get the same automations the FF gets.
- As a CF, I draft an email to a contact on one of my assigned accounts and send it from my own address.

**VA — Virtual assistant**
- As a VA, I add and correct contacts, companies, and categories, because keeping the CRM clean is my job.
- As a VA, I run a CSV import and review the dry run, but the commit is mine to perform and mine to roll back if it looks wrong.
- As a VA, I draft referral touches into the Outbox for the FF to approve, because nothing I write goes to a client without the FF seeing it.

**FCC / ECC — client users**
- **No stories. Module 1 has no client-facing surface.** Client users never see the CRM, the pipeline, other client companies, vendors, referral partners, or the Outbox. This is a deliberate, permanent boundary, not a Beta limitation.

### Functional requirements

**Records**

1. A **Contact** has: first name, last name, title, one or more email addresses (one primary), one or more phone numbers, linked Company (nullable), owner (tenant user), source, **`background`** (a short "who this is / how we met" line), tags, and timestamps.
1a. **There is exactly one thing in this product called a note, and it is a `note` record** (Module 2). A CSV notes column is imported as a real note linked to the contact with `source = import`, not as a blob on the contact — so imported context is searchable, PIN-able, and on the timeline like any other note.
2. A Contact has **one or more contact types** from the per-tenant list (prospect, client, referral partner, vendor, coworker), with one marked primary for display. Multi-type is required because a referral partner is frequently also a client, and forcing a single type would make one of those relationships invisible.
3. A **Company** has: name, domain(s), address, industry, an **ordered list of named locations** (used by Module 4's `{Location A}` / `{Location B}` merge fields), a **`primary_contact`** (nullable FK to a Contact at that company), and a flag `is_client_company` with a `seat_count` when set. Contacts belong to at most one Company.
3a. **`primary_contact` is the designated recipient of company-level communication** — the person Module 3 addresses when something concerns the company rather than a specific task, and the default grantee of FCC when portal access is first given. It is nullable, because a prospect company has no designated contact until someone is chosen.
4. Contacts and Companies are soft-deleted (`deleted_at`), never hard-deleted through the UI.
5. Every Contact and Company has an **activity timeline** aggregating: stage changes, notes, emails sent and received, meeting proposals approved, and tasks — in one reverse-chronological view.

**Pipeline**

6. **A practice runs more than one pipeline.** A `pipeline` is a per-tenant row with a `name`, a `kind` ∈ {`sales`, `referral`, `custom`}, and a position. Two are seeded: **"Sales"** (`sales`) and **"Referral partners"** (`referral`) — a sales funnel and a nurture track are different processes, and collapsing them made every referral partner look like a stalled prospect.
6b. **A stage belongs to one pipeline and carries a `semantic` independent of its label**: `entry · working · qualified · won · lost · parked · none`. The FF renames, reorders, adds and removes stages freely; **every rule in the app keys on the semantic, never on the label**, so renaming "Closed Won" to "Signed" changes nothing behavioural. Stage codes are unique *per pipeline*, so "Qualified" may legitimately exist in two. A `sales`-kind pipeline must have **exactly one `won` stage**; removing the last one is refused, because without it nothing can ever become a client.
6c. **Seeded stages are the owner's own**, not a generic funnel. *Sales:* Initial Contact Made (`entry`) → Prospecting (`working`) → Follow Up Needed (`working`) → Qualified (`qualified`) → Consult Given (`qualified`) → Proposal Given (`qualified`) → Decision Making (`qualified`) → Negotiation (`qualified`) → **Closed Won (`won`)** → Closed Lost (`lost`) → Nurture (`parked`). *Referral partners:* New Partner (`entry`) → Follow-up Sent (`working`) → Flyer Sent (`working`) → Nurturing (`working`) → Active Referrer (`qualified`) → Dormant (`parked`). The FF edits these after import.
6d. **A contact holds an independent position in each pipeline they belong to** (`contact_pipeline_position`, unique per contact per pipeline). A referral partner who becomes a prospect is genuinely in both; the single `contact.stage_id` this replaces forced a choice that lost one of the two facts. **Contact type does not gate pipeline membership** — being in the referral pipeline and carrying the `referral_partner` type are separate facts.
6a. **The client invariant. A `won` stage in a `sales` pipeline is the single source of truth for who is a client.** Three things can each say "client" — the contact's position, the contact's type, and the company's `is_client_company` flag — so exactly one is authoritative and the other two are derived from it:
    1. **Moving a contact to a `won` stage in a `sales` pipeline** (by hand, by CSV import, or by Module 4 conversion) **adds contact type `client`** to that contact and **sets `is_client_company = true`** on their company. Both derivations are idempotent and audited.
    2. **Moving them on to a `lost` or `parked` stage removes neither.** A lost client is still historically a client, and the company may have other active contacts. Unsetting the type or the company flag is a deliberate manual act.
    3. The derivation runs in one direction only. Adding the type `client` by hand does **not** change any position, and nothing in the app infers a stage from a type or a flag.
    4. A contact with no company can reach a `won` stage; the company derivation is simply skipped, and no placeholder company is invented.
    5. **A `won` stage in a `referral` or `custom` pipeline is not a sale.** Reaching "Active Referrer" must never flag a company as a client company. The invariant checks the pipeline's `kind`, not just the stage's semantic.
7. A stage change records actor, timestamp, **pipeline**, from-stage, to-stage, and an optional reason. Moving to a `lost` stage prompts for a reason; the prompt may be skipped.
8. A contact's stage history is visible on the timeline, **naming the pipeline** — "moved to Qualified" is ambiguous once a practice runs more than one.
9. **Pipeline view: one board per pipeline, with a selector.** Contacts grouped by stage with counts, filterable by owner, type, and company. A contact who appears on two boards is marked as such. The **contact detail screen shows their position in every pipeline they belong to.**

**Assignment**

9a. A **`ClientAssignment`** is a row joining a **tenant user** to a **client company**, with the date assigned and by whom. **This is the record every "assigned accounts" rule in Modules 1 through 6 depends on** — CF contact visibility, CF digest approval, CF Gmail send authority, and CF access to meeting proposals all resolve through it, so it exists as an explicit table rather than as a rule reimplemented per module.
9b. **Only the FF creates, changes, or removes assignments.** CFs and VAs cannot.
9c. **A CF's visible universe is exactly:** all contacts at client companies they are assigned to, **plus** prospects they personally own, **plus** contacts with no company that they own. Nothing else in the tenant — not other CFs' prospects, not unassigned client companies.
9d. **VAs see all contacts in the tenant.** A VA's restriction is on financials and settings (`CLAUDE.md`), not on the CRM.
9e. Removing an assignment takes effect immediately on the CF's next request; it does not delete anything they created.

**Automations**

10. A **stage automation rule** is a per-tenant row **scoped to one pipeline**: `pipeline`, `from_stage` (or any), `to_stage`, and an action. A "becomes Qualified" rule on Sales does **not** fire for the referral pipeline's own Qualified stage.
11. Action type **create_task**: creates a task from a template (title, offset-based due date, owner defaulting to the contact's owner). Fires immediately, no approval.
12. Action type **draft_email**: renders a template into an Outbox draft in `pending_approval` with a **send-by date defaulting to 7 days out, configurable per rule**. **⛔ REVIEW QUEUE (R2).** Never sends itself; on the send-by date it expires (FR-1.18).
13. Rules are listed per pipeline in one settings screen with a plain-English summary of each, **naming the pipeline** ("When a contact reaches *Qualified* in Sales, create task 'Book strategy session' due in 3 days").
14. **Task creation from a rule is not gated by a review queue** and this is intentional — it is deterministic, configured by the tenant, and has no effect outside the app (assumption F3).

**Outbox**

15. **Every app-originated email is an Outbox row.** The Outbox is therefore two things at once: the approval queue, and the complete send log for the tenant. If a message left the app, there is a row for it.
15a. **Not every Outbox row passes through `pending_approval`.** States are `draft → pending_approval → approved → sent`, plus `rejected` and `expired` — but a send that a human has **explicitly clicked** is written **directly as `sent`**, with no pending state, because the click *is* the approval. Requiring a second approval for a button the user just pressed would be theatre.
15b. The direct-to-`sent` producers are: **the strategy session PDF** (R8 — the fractional reviews a true preview and clicks send), **stakeholder cadence-change confirmations** (FR-3.33), **magic links** (assumption A2a, sent synchronously in the request), and **note PIN resets** (FR-2.12, added in Phase 2). *All of them go through the Outbox and the configured transport like every other email — Phase 2 found magic links and PIN resets going straight through Django's mail backend, bypassing both and the dev allow-list. For the two that carry a one-time link, the Outbox row stores the message with the link removed; the link is delivered but never stored, because the Outbox is readable by every tenant user (assumption C3).* Everything else — stage-rule drafts, referral touches, digests, referral onboarding — enters at `pending_approval`.
15c. This reconciles FR-1.15 with §2 of this document: R8 is a review queue, and its review is the preview-and-click, not a queue the message waits in afterwards.
16. An Outbox item shows: recipient, subject, body, what produced it, whether AI wrote any of it, and the send-by date.
17. Approving sends. Editing then approving sends the edited version. Rejecting keeps the row as `rejected` with the actor recorded.
18. **An item that reaches its send-by date without approval expires. It does not send.**
19. VAs can create and edit Outbox drafts. VAs cannot approve or send (assumption H7), **with one exception: a VA may send a `precall_invite` directly** (assumption H7a, FR-4.6a).
19a. An email a tenant user composes by hand in the app has producer `manual`. **Sent by an FF or CF it is written directly as `sent`** via their own Gmail; **composed by a VA it enters `pending_approval`** like any other VA draft.

**Referral touches**

20. A referral-partner contact carries a touch cadence: monthly (default), bi-monthly, or quarterly.
20a. A referral-partner contact also carries **`referral_fee_terms`** — free text, e.g. "10% of first 3 months". Optional; many partnerships have no fee.
21. A scheduled job drafts each due touch **3 days before** its due date into the Outbox. **⛔ REVIEW QUEUE (R1).**
21a. The tenant carries an FF-maintained **"what I'm working on lately" blurb** with a `last_updated_at`, editable from settings. It is the substance of every touch — the thing that makes the email worth a partner's attention rather than a checkbox.
22. A touch draft is **3–5 lines** composed from three parts:
    1. **the tenant's current blurb** — what the fractional has been working on lately;
    2. **a fee reminder**, included only when `referral_fee_terms` is set, phrased as a reminder of the arrangement rather than a demand;
    3. **a reciprocal line** — what the fractional is looking for, so the partner can send referrals *and* knows what to send. A touch that only asks is a worse email than one that also offers.
    The draft is AI-drafted from those inputs plus the contact's history, or rendered from an FF-written template — the tenant chooses per contact.
22a. **If the blurb is older than the cadence period** (a monthly cadence with a blurb last updated 40 days ago), **the Outbox item carries a visible warning** to the reviewer, naming the blurb's age. It does not block sending — sometimes last month's work is still this month's news — but nobody should mail twelve partners the same stale paragraph without noticing.
23. An AI-drafted touch is labelled as such in the Outbox, so the reviewer knows what they are reading.

**Referral partner onboarding**

23a. **When a contact first becomes a referral partner** — by hand, or by a reviewer confirming that type on a Module 5 meeting proposal — two things happen: they are **placed at the referral pipeline's `entry` stage** ("New Partner"), and a **"post-meeting follow-up" Outbox draft is created immediately** in `pending_approval` (the R2 path). It is the first touch, sent while the meeting is fresh, not on the next cadence date.
23a.i. **The placement is an ordinary stage change.** It writes a normal `stage_change` row and appears on the timeline like any other move — there is no second, invisible way for a contact to enter a pipeline. If they are **already** in the referral pipeline, onboarding does not reset their progress, and **it never disturbs their position in any other pipeline**: a live prospect who becomes a referral partner keeps their sales stage.
23a.ii. Movement within the referral pipeline afterwards ("Follow-up Sent", "Flyer Sent", "Nurturing", "Active Referrer", "Dormant") is ordinary stage-change behaviour, with its own per-pipeline automations.
23b. The onboarding draft **attaches the tenant's marketing flyer** — a single tenant-uploaded PDF held in settings. The flyer is **optional**: if none is uploaded, the draft is created without it and says so in the Outbox, rather than being suppressed.
23c. **The touch cadence clock starts from the date the onboarding draft is created**, not from the contact's creation date — so a partner onboarded on the 3rd is next touched a month after the 3rd.
23d. Becoming a referral partner a second time (type removed and re-added) does **not** re-trigger onboarding.

**Vendors**

24. Per-tenant **service categories**; a vendor contact carries one or more.
25. Vendors are searchable and filterable by service category.

**CSV import**

26. Import is three steps: **upload → column mapping → dry-run preview → commit**.
27. Column mappings are saved as reusable named profiles.
28. The dry run reports counts of create / update / skip / error, lists every error with its row number and the offending column, and shows the first 20 resulting records as they will be written.
29. Dedupe order: exact email match → normalised (name + company) match → no match, create new. **Ambiguous matches are listed for a human decision, never guessed.**
29a. A mapped **notes column creates a `note` row** per FR-1.1a; a mapped **background column** writes `contact.background`. Rolling back an import removes the notes it created.
30. Commit runs in one transaction and produces an `ImportBatch` row.
31. **An ImportBatch can be rolled back wholesale**, reverting creates and field-level updates, provided the affected rows have not since been edited by hand (those are listed and skipped, with a report).
32. A malformed row never aborts the import; it is reported and skipped.

**Search and merge**

33. Global search covers contacts, companies, and notes, using Postgres full-text search. Results are tenant-scoped and respect note PIN locking (Module 2).
34. Two contacts can be **merged**: pick the surviving record, choose field-by-field where they conflict, and all history (notes, tasks, emails, timeline) moves to the survivor. The merged-away record is soft-deleted with a pointer to the survivor.
34a. **Merge is available to the FF and the VA** (not CF), and **writes an `AuditEvent` naming both records and the actor.** Post-import de-duplication is the bulk of CRM hygiene and the VA is the one running imports; withholding merge would route the cleanup half of the VA's own work back to the FF.
34b. **Soft-deleted contacts and companies can be restored** by anyone who could delete them, which is what makes delegating deletion safe (D2).

### Out of scope for Beta

1. Custom fields on contacts or companies.
2. Email open/click tracking.
3. Bulk email campaigns or sequences (referral touches are one-at-a-time, reviewed).
4. Contact enrichment from third-party data providers.
5. Import from Google Contacts, HubSpot, or any API — CSV only.
6. Duplicate detection running continuously in the background; dedupe happens at import and on demand.
7. Any client-user access whatsoever.
8. Per-contact email preferences beyond referral cadence.

### Acceptance criteria

**AC-1.1 — Import dry run is honest.** Prepare a 200-row CSV containing 3 rows that duplicate existing contacts by email and 1 row with a malformed email address. Run the import. The dry run reports **196 create, 3 update, 1 error**, names the error's row number and column, and shows 20 sample records. No contact count has changed at this point.

**AC-1.1b — Phone, tags, and status columns all have somewhere to go.** The same file carries two phone columns, a comma-or-semicolon separated `tags` column, and a `status` column. Map both phone columns to **phone**, `tags` to **tags**, `status` to **contact_type**, and `stage` to **pipeline_stage**. The dry run's 20 sample rows show, per row: both numbers with the **first column's number marked primary**, the tags split, trimmed and de-duplicated, the contact type, and **every pipeline placement with its stage**. A tag longer than 64 characters is reported as a row error naming the column — it does not fail the import.

**AC-1.1c — Status and Stage values are mapped by hand, not guessed.** The owner's real file has **both** a `status` (type) column and a separate `stage` column; they map to **contact_type** and **pipeline_stage** and are kept as different facts. After column mapping, the wizard lists, **per mapped column**, every distinct value with **how many rows carry it**, matching trimmed and case-insensitively so `Client` and `client ` are one row. A **`pipeline_stage` column asks which pipeline it belongs to first**, once, for the whole column. A `contact_type` value may *additionally* place the contact at a stage in a pipeline of its own choosing. Each value is mapped, or ignored. **A value left unmapped is a row error in the dry run**, never a silent drop; so is a stage mapping with no pipeline named.

Mapping a value to a **`won` stage in a `sales` pipeline** fires FR-1.6a exactly as a manual stage change does — the client contact type is added and the company is flagged — and the dry run says so before you commit. A `won` stage in the referral pipeline does neither. It does **not** replay stage automations: an import is a statement about history, not a transition happening today, so no follow-up task is created and no client-facing draft is queued. **One row may land in both pipelines at once**, and the dry-run preview lists every placement. Saving the mapping remembers the column mapping **and** every value mapping together. Rollback removes the type links, phones and **pipeline positions the import created**, and restores the previous stage and tags for contacts that already existed.

**AC-1.2 — Commit and roll back.** Commit the import from AC-1.1. The contact count rises by exactly 196. Open the ImportBatch and roll it back. The count returns to its pre-import value and the 3 updated contacts show their original field values.

**AC-1.3 — Ambiguity is surfaced, not guessed.** Include in a CSV two rows with the same person's name at the same company but different email addresses. The dry run lists it as an ambiguous match requiring a decision, and offers merge-or-create. Nothing is auto-merged.

**AC-1.4 — Stage automation fires the task, queues the email, and only in its own pipeline.** Configure two rules on the Sales pipeline's *Qualified* stage: create a task, and draft an email. Move a contact to *Qualified* in Sales. Then move a different contact to *Active Referrer* in the referral pipeline and confirm **neither rule fires** — rules are per pipeline. The task exists immediately and is assigned to the contact's owner. The email is in the Outbox as `pending_approval`. **Check the dev outbox: nothing has been sent.**

**AC-1.5 — An unapproved draft expires rather than sending.** Leave the AC-1.4 draft unapproved past its send-by date. It moves to `expired`. Nothing was delivered.

**AC-1.6 — Referral touch arrives as a draft, three days early.** ✅ **TESTED END TO END (Check 4).** Set a referral partner to monthly with a due date three days out. Run the scheduler. A 3–5 line draft appears in the Outbox labelled as AI-drafted, addressed to that partner. Nothing is sent. Approve it; it sends, and the send appears on the contact's timeline.

> **Exercised live on 2026-09-11:** the owner drafted a touch to his own allow-listed address, approved it, and **received it in Gmail from `info@getexecutivesnow.com`** — a real send, through the real Gmail transport, with the verified send-as alias on the From line. This is the first acceptance criterion in Module 1 proven against real delivery rather than against the dev outbox.

**AC-1.7 — VA cannot send.** Signed in as a VA, open the Outbox. Drafts are visible and editable; the approve and send controls are absent, and calling the approve endpoint directly returns 403.

**AC-1.8 — Vendor search by category.** Tag three vendors with "Commercial HVAC" and two with "IT". Searching the category returns exactly the three, and no contact from another tenant.

**AC-1.9 — Merge preserves history.** Create two contacts for the same person, attach a note to each and a task to one. Merge them. The survivor shows both notes and the task; the merged-away record is gone from search but its ID still resolves to the survivor.

**AC-1.10 — Tenant isolation.** As a user in tenant A, attempt to open a contact, company, ImportBatch, and Outbox item belonging to tenant B by direct URL. All four return 404 (not 403 — existence is not confirmed).

**AC-1.11 — Client users are absent from this module.** Signed in as FCC, no CRM navigation exists, and direct requests to contact, pipeline, vendor, and Outbox endpoints return 403.

**AC-1.21 — VA can merge, and it is audited. (FR-1.34a, matrix 4.5.)** As a VA, merge two duplicate contacts created by an import. It succeeds, history moves to the survivor, and an `AuditEvent` names both records and the VA as actor. As a CF, confirm the merge control is absent and the endpoint returns 403.

**AC-1.22 — Delete and restore are delegable. (FR-1.34b, matrix 4.4/4.4a.)** As a VA, soft-delete a contact and a company: both succeed and disappear from search. Restore both: they return with their timelines intact.

**AC-1.23 — Pipelines and their stages are FF-only; types and categories are not. (Matrix 3.14/3.14a/3.15/3.15a.)** As a VA, create a contact type and a service category: both succeed. Attempt to create a pipeline, or to rename, reorder, add or delete a pipeline stage: **403** for each. Confirm a VA can still **read** pipelines and stages — they work the board every day.

**AC-1.24 — Staff removal cascades. (FR-0.8c.)** As FF, remove a CF who holds two client assignments and a Gmail connection. Confirm: their session no longer authenticates, both `client_assignment` rows are closed, the Gmail connection and its stored token are gone, and every task, note, and sent message they authored still exists.

**AC-1.25 — AI spend is FF-only. (FR-0.9, matrix 3.19.)** As FF, open the AI usage view and confirm it shows `ai_call` totals. As CF and as VA, confirm no navigation exists and the endpoint returns 403.

**AC-1.12 — The client invariant derives forward and does not reverse. (FR-1.6a.)** Take a prospect at a company with `is_client_company = false` and no `client` type. Move them to the sales pipeline's **`won`** stage (*Closed Won*). Confirm the contact now carries type `client` **and** the company is flagged. Now move them to *Closed Lost* (`lost`): **confirm the type is still present and the company is still flagged.** Separately, add type `client` by hand to a different contact and confirm no position changes. Move a contact with no company to `won` and confirm it succeeds with no company row invented. **Then rename the `won` stage** to "Signed" and repeat with a third contact: the invariant still fires, because it keys on the semantic and not the label. **Finally, move a contact to "Active Referrer" in the referral pipeline** and confirm their company is **not** flagged and no `client` type is added — a nurture pipeline's end state is not a sale.

**AC-1.12a — A contact holds a position in two pipelines at once. (FR-1.6d.)** Place one contact at *Negotiation* in Sales and at *Active Referrer* in Referral partners. Confirm both boards show them, the contact detail screen lists both positions, and moving them in Sales leaves the referral position untouched. Confirm that removing their `referral_partner` type does not remove them from the referral pipeline — type does not gate membership.

**AC-1.12b — A sales pipeline cannot lose its only `won` stage. (FR-1.6b.)** As the FF, delete *Closed Won* from the Sales pipeline: **refused with a message naming the reason**, and the stage is still there afterwards. Mark another stage `won` first, and the delete then succeeds. Attempt to delete a stage that still holds contacts: refused, naming the count.

**AC-1.13 — Assignment governs CF visibility. (FR-1.9a–9e.)** Assign a CF to client company A only. As that CF: contacts at A are visible; a prospect the CF owns is visible; a contact at unassigned client company B returns 404; another CF's prospect returns 404. As FF, remove the assignment; the CF's next request for a company-A contact returns 404, and any contact the CF created still exists.

**AC-1.14 — Only the FF assigns.** As CF and as VA, confirm no assignment control is offered and the assignment endpoints return 403.

**AC-1.15 — VA sees the whole CRM.** As a VA, confirm contacts at every client company and every CF's prospects are visible — the VA restriction is financials and settings, not the CRM.

**AC-1.16 — Stage-rule drafts expire on schedule. (FR-1.12.)** Create a rule with the default send-by. Trigger it and confirm the Outbox item's send-by date is 7 days out. Change the rule to 2 days, trigger again, and confirm the new item reflects it. Advance the clock past both: both are `expired` and the dev outbox is empty.

**AC-1.17 — The Outbox is the complete send log. (FR-1.15–15c.)** Perform one of each: approve a referral touch, send a strategy PDF, and trigger a magic link. **Confirm all three appear as Outbox rows.** Confirm the touch passed through `pending_approval`, and that the PDF and magic link were written **directly as `sent`** with no pending state.

**AC-1.18 — Touch composition includes all three parts. (FR-1.22.)** Set a tenant blurb, and set `referral_fee_terms` on partner X but leave it empty on partner Y. Generate both touches. X's draft contains blurb content, a fee reminder, and a reciprocal line. Y's contains blurb content and a reciprocal line and **no fee language whatsoever**. Both are 3–5 lines.

**AC-1.19 — Stale blurb warns but does not block. (FR-1.22a.)** Set the blurb's `last_updated_at` to 40 days ago and generate a monthly touch. The Outbox item shows a warning naming the blurb's age. Confirm the item can still be approved and sent.

**AC-1.20 — Referral onboarding fires once, attaches the flyer, and sends nothing. (FR-1.23a–23d.)** ✅ **TESTED END TO END (Check 5).**

> **Exercised live on 2026-09-11:** an onboarding/touch email was delivered to the owner's own allow-listed address **with the flyer attached, and the PDF opens with content**. It took two failed attempts to get here: the attachment first arrived at 0 bytes because `stored_file` content was never written to storage *and* `_deliver` handed the transport a literal `b""`. Both are fixed; a test now asserts that a delivered attachment's size equals the stored file's, and a send whose attachment content is missing is refused rather than delivering an empty document. Upload a flyer PDF in settings. Add type `referral partner` to a contact. **Immediately** an Outbox draft titled as a post-meeting follow-up exists in `pending_approval` with the flyer attached; **the dev outbox is empty.** Confirm the contact's next touch date is one cadence period from today. Remove and re-add the type: **no second onboarding draft is created.** Delete the flyer from settings, onboard a different partner, and confirm the draft is still created and states that no flyer is attached.

---

## 4. Module 2 — Notes

### Purpose

Capture that is fast enough to actually use during a call. A fractional's most valuable observations happen while talking to someone, and any tool that demands a title, a category, and a linked record before it will accept a sentence gets abandoned within a week. So a note takes one action to start, links to a contact, company, or task only if you want it to, and can be dictated instead of typed: a browser recording becomes a transcript via Google Speech-to-Text, and Claude drafts a summary you accept or edit before it is attached. A note can also carry an optional PIN that hides it from casual view — which is a privacy screen, not a vault, and this document is explicit about the difference.

### User stories

**FF**
- As the FF, I capture a thought in one action from anywhere in the app, without deciding first what it belongs to.
- As the FF, I record a client call in the browser and get a transcript and a draft summary, so my recollection is not the only record.
- As the FF, I put a PIN on a note about a sensitive personnel matter so it does not appear when a VA glances at the contact.
- As the FF, I reset a PIN on a note when I have forgotten it, knowing this clears the PIN rather than revealing it, and that the reset is logged.

**CF**
- As a CF, I do everything the FF does with notes on my assigned accounts, except reset PINs.

**VA**
- As a VA, I read and write notes that are not PIN-locked, so I can support the practice without seeing what has been screened off.
- As a VA, I see that a locked note exists on a contact — its title and nothing else — so I am not misled into thinking the record is empty.

**FCC / ECC**
- **No stories. Client users have no access to notes in Beta.** Notes are the fractional's working memory, including candid assessments of the client. There is no client-visible note type, and adding one later would be a deliberate product decision, not an oversight.

### Functional requirements

**Capture**

1. A note is created from a persistent global control available on every screen, and from a keyboard shortcut. Body only is required; title is optional and **auto-derived from the first line of the body** if blank. A note records whether its title was auto-derived or typed by a person.
2. Body supports basic markdown. No rich-text editor, no embedded media.
3. A note links to **at most one of a Contact or a Company**, *and independently* to **at most one Task** — or to nothing. Both links are optional and independent.
3a. This is a deliberate reading of `CLAUDE.md`'s "optional link to a contact, company, task, or nothing": a note taken on a client call about a specific deliverable belongs on **both** the person and the task, and forcing a choice would hide it from whichever view the reader happens to open. What is excluded is linking to a Contact *and* a Company at once — a contact already implies its company.
4. The link can be added or changed after creation.
5. Notes are soft-deleted.

**Surfacing**

6. A note appears on the timeline of its linked record, and in global search.
7. Global search covers note title, body, and any accepted summary, subject to PIN rules below.

**PIN**

8. A note may carry an optional **4–6 digit PIN**, stored as a password hash. **The body is not encrypted** — `CLAUDE.md` specifies the PIN gates viewing, and this requirement does not quietly upgrade it.
9. Entering the correct PIN unlocks that note for the browser session or 30 minutes, whichever is shorter.
10. 5 consecutive wrong attempts lock that note for 15 minutes and write an `AuditEvent`.
11. A locked note appears in search results and on timelines as a **stub: title and linked record only**. No body, no summary, no excerpt.
11a. **Setting a PIN on a note whose title was auto-derived requires the user to type a real title first**, and the PIN dialog says why: the title is shown on the locked stub, and an auto-derived title *is the first line of the body* — so a note PIN'd without this step would display on its own stub the very sentence it was hidden to protect. *(Built as a dialog rule. The API accepts a PIN on an auto-titled note — AC-2.3 requires that bypass to succeed — and FR-2.11b plus the generated search index keep it safe.)*
11b. **Defence in depth: a locked stub never renders an auto-derived title under any circumstance.** If one is somehow encountered — a note PIN'd through the API, a title auto-derived after the PIN was set, a data migration — the stub renders **"Locked note"** instead. FR-2.11a is the workflow; this is the invariant that holds when the workflow is bypassed.
12. **PIN reset is FF-only**, performed by an emailed link, and **clears the PIN rather than revealing it**. The note becomes readable to everyone with normal access from that moment. The reset is audited.
13. The PIN-set screen states plainly what the PIN does and does not do: it screens the note from other users of the app; it does not protect it from the FF, from a database dump, or from the nightly backup.

**Recording and transcription**

14. Recording uses the browser's `MediaRecorder`. **It captures this device's microphone only**, and the recorder says so before recording starts: it is for in-person conversations and dictation. The other side of a video call is not captured; meetings arrive through Module 5. *(Added from Phase 2 manual check 1.)* **Soft cap 120 minutes, with a warning at 110** — a strategy session runs 75 minutes to the seed's timing, and a cap that cannot hold the tool's own flagship session would be a self-inflicted limit.
15. **Starting a recording shows a one-line reminder to confirm all parties consent to being recorded.** Dismissible per session, not per recording.
16. Audio uploads to GCS; transcription runs asynchronously via Google Speech-to-Text; the note is usable (with a "transcribing" state) throughout.
17. When the transcript is ready, Claude drafts a summary. **⛔ REVIEW QUEUE (R3):** the summary is presented beside the transcript for the author to **accept, edit, or discard**. No summary is attached silently. *(The reviewer is the note's author, or the FF. Enforced in the database: `summary` can be non-null only when `summary_state = 'accepted'`.)*
18. If transcription fails, the note keeps the audio and shows a retry control. If Claude fails, the note keeps the transcript.
18a. **No speech is its own outcome.** When Speech-to-Text returns nothing, or fewer than 5 words per recorded minute, the note says **"No speech detected"** (or "Almost no speech detected"), lists what to check — microphone permission, headphones on a call, a muted microphone or call — keeps the audio for retry, and drafts no summary. *(Added from Phase 2 manual check 1: a 6-minute video call transcribed as one word.)*
19. **Audio retention is a per-tenant setting, `audio_retention_days`, default 30.** Transcript and summary are retained indefinitely. Setting it to 0 deletes audio on successful transcription, and the setting screen states that this forfeits re-transcription.
19a. **Audio whose transcription never succeeded is not deleted by retention** (owner decision, 2026-09-11). It is the only record of the call; the note is flagged until someone retries the transcription or discards the audio.
19b. **Recording audio is not in the nightly backup** (owner decision, 2026-09-11), so that retention actually deletes it. It relies on GCS durability and the media bucket's 7-day soft delete.

### Out of scope for Beta

1. Any client-user visibility of notes.
2. Real-time transcription during the call (transcription is post-hoc).
3. Speaker diarization / "who said what".
4. Note templates.
5. Collaborative or simultaneous editing.
6. File or image attachments on notes.
7. Note sharing between tenants or export beyond the database backup.
8. Encryption of note bodies — explicitly excluded, per `CLAUDE.md` and FR-2.8.
9. PIN on anything other than a note (no PIN'd contacts, tasks, or companies).

### Acceptance criteria

**AC-2.1 — Capture is genuinely fast.** From any screen, create a note containing only a sentence of body text and save it, without being asked for a title, a link, or a category. It saves and appears in search.

**AC-2.2 — Linking is optional, mutable, and dual. (FR-2.3.)** Create an unlinked note; confirm it saves. Link it to a contact; confirm it appears on that contact's timeline. **Now also link it to a task, and confirm it appears on both the contact timeline and the task, as one note and not two.** Confirm the UI offers no way to link a Contact and a Company simultaneously.

**AC-2.3 — A locked note shows as a stub, not a hole, and the stub leaks nothing. (FR-2.11, 2.11a, 2.11b.)** Set a PIN on a note attached to a contact. Sign in as a VA. The contact timeline shows the note's title with a locked indicator, no body and no summary text anywhere in the page source, and search for a distinctive word from the body returns nothing.

**Then test the title leak specifically.** Create a note with **no title**, whose first line of body is the distinctive string `CONFIDENTIAL SEVERANCE DISCUSSION`. Attempt to set a PIN: **the dialog requires a typed title before proceeding**, and explains why. Supply the title `HR matter` and set the PIN. As a VA, confirm the stub shows `HR matter` and that `CONFIDENTIAL SEVERANCE DISCUSSION` appears **nowhere** in the page source or any API response. Finally, set a PIN on an auto-titled note **through the API, bypassing the dialog**, and confirm the stub renders **"Locked note"** rather than the derived title.

**AC-2.4 — Lockout works and is recorded.** Enter a wrong PIN five times. The note refuses further attempts for 15 minutes with a clear message, and an `AuditEvent` records the attempts and the actor.

**AC-2.5 — Reset clears, does not reveal, and is FF-only.** As a CF and again as a VA, confirm no reset control is offered and the reset endpoint returns 403. As FF, request a reset; an email arrives with a link; following it clears the PIN. The note is now readable with no PIN. **At no point is the original PIN displayed or emailed.** The reset appears in the audit log.

**AC-2.5a — Recording cap. (FR-2.14.)** Begin a recording and advance to 110 minutes: a warning appears. Advance to 120: the recording stops cleanly and the audio captured so far is retained and transcribable.

**AC-2.6 — Consent reminder appears.** Start a recording. The consent reminder is shown before recording begins. Dismiss it; start a second recording in the same session and confirm it does not reappear. Sign out and back in; it reappears.

**AC-2.7 — Summary is proposed, not applied.** Record 60 seconds of speech. When transcription completes, the summary appears beside the transcript with accept / edit / discard controls, and the note's stored summary field is still empty. Discard it; the note retains the transcript with no summary. Repeat and accept; the summary is stored.

**AC-2.8 — Failure degrades gracefully.** *(Re-worded 2026-09-11, owner-approved: one service-account key now serves both storage and Speech-to-Text, so "an invalid Google credential" fails the upload as well and the original wording could not hold.)*

- **(a) Storage works, Speech-to-Text fails.** Record a note. The note saves, shows a transcription-failed state with a retry control, and the audio is retained in GCS.
- **(b) The upload fails.** The recording stays in the browser that made it and is retried until the server confirms it; nothing is lost, and the audio can be downloaded from the browser meanwhile.

**AC-2.9 — Retention setting is honoured.** Set `audio_retention_days` to 1, create a recording, and run the retention job with a clock 2 days ahead. The audio object is gone from GCS; the transcript and summary remain. A recording that never transcribed is **kept** by the same run and flagged (FR-2.19a).

**AC-2.10 — Tenant isolation.** A note in tenant B is not returned by tenant A's search, timeline, or direct URL — including when the note is unlocked in tenant B.

---

## 5. Module 3 — Task engine + client portal

> **This is the module the client actually experiences, and the one `CLAUDE.md` names as most important to the customer. It is specified in more depth than the others, and the digest requirements in particular are written to make an unintended send structurally impossible.**

### Purpose

Everything the fractional does for a client, in a structure the client can see, and a progress report that reads as value delivered rather than a list of field changes. Work is organised in three levels — **Goal → Project → Task** — where Goal and Project are optional above a task, so a client can use it as their day-to-day task tool without being forced to file a five-minute job under a strategic objective. Each task carries stakeholders, and each stakeholder chooses how often they hear: on every update, weekly, or monthly. The digest they receive is assembled from what actually changed plus what the fractional said it meant, and — while `hold_all_digests` is on, which is the Beta default — every digest waits in an approval screen before it can reach anyone. The measure of this module is not that it tracks tasks. It is that a founder reading the Monday email understands what they are paying for.

### User stories

**FF**
- As the FF, I create a Goal for a client engagement, break it into Projects, and fill those with Tasks, so the strategic work and the daily work are the same system.
- As the FF, when I move a task forward I am prompted for one line on what it means for the client, so the weekly digest writes itself out of work I was doing anyway.
- As the FF, I review all pending digests in one screen before they go anywhere, and approve them in a batch when they look right.
- As the FF, I can see exactly what was sent, to whom, and when, on the task itself — so "did they know?" is a question I can answer.
- As the FF, I turn off AI-written prose for a client who prefers a plain list, and the digest still sends on cadence.
- As the FF, I keep every digest held for approval, and I know that this is the default until I deliberately change it.
- As the FF, I keep internal comments on a task separate from what the client sees, so the record does not fork into a private tool and a shown tool.

**CF**
- As a CF, I do all of the above on the client companies I am assigned to, and nothing on the ones I am not.
- As a CF, I approve digests for my own accounts, because I am the one accountable for what that client is told.

**VA**
- As a VA, I create and update tasks, chase status, and prepare digest content, so the FF's review is quick.
- As a VA, I **cannot approve or send a digest**, because nothing I prepare reaches a client without a fractional seeing it.
- As a VA, I comment internally on tasks without any risk of the client seeing it.

**FCC — Founder of client company**
- As the client founder, I see my company's goals, projects, and tasks — and nothing from any other company.
- As the client founder, I create tasks for my own team and assign them among my own users, so this is my task tool and not just a viewing window.
- As the client founder, I comment on a task and the fractional sees it on the same record.
- As the client founder, I open a progress report on demand instead of waiting for the email.
- As the client founder, I change how often I get emailed without asking anyone.

**ECC — Employee of client company**
- As a client employee, I have the same access to my company's work as the founder does. **In Beta, FCC and ECC are functionally identical.** The only distinction is that FCC is the designated recipient for company-level communications; the user-management capability that will separate them is V1 (`CLAUDE.md` says "later"). The two roles exist separately in the model and the access matrix from day one so V1 does not require a migration — but I am not going to invent a Beta difference that does not exist.

### Functional requirements

**Hierarchy**

1. A **Goal** has: title, description, client company (nullable — internal goals exist), owner, target date, status, and an optional link back to the Strategy Map row that produced it (Module 4).
2. A **Project** has: title, description, parent Goal (nullable), client company, owner, start and target dates, status.
3. A **Task** has: title, description, parent Project (nullable), parent Goal (nullable), client company (nullable), assignee, status, priority, due date, `is_client_visible`, checklist items, comments, and stakeholders.
3a. **Goals, Projects, and Tasks each carry a `client_owner_contact_id` alongside the tenant-side owner** — *who on the client side is accountable*. It is a Contact, not a user, because the two things that populate it name client people who often have no login: a Strategy Map row's owner (usually the client's Integrator) and a meeting action item's owner.
4. **Depth is capped at three levels.** A task cannot parent another task. The "sub-step" need is served by **checklist items** — a flat, ordered list of strings with a done flag — so three levels does not quietly become unlimited.
5. `project` and `goal` are both nullable on a Task, so a standalone task is a first-class thing (assumption F8).
6. Deleting a Goal or Project does not delete its children; they are detached and reported.

**Status and ownership**

7. Task status is exactly: **Not started · In progress · Blocked · Waiting on client · Done · Cancelled.**
8. "Waiting on client" is distinct from "Blocked" and is rendered distinctly in the client portal, because the difference between *we are stuck* and *you are the blocker* is the most useful thing a progress report can say.
9. A task's assignee may be a tenant user or a client user. **Client users may only assign to users within their own company.**
9a. **What a client user may change, stated as one rule** (because "tasks they created" and "tasks they are assigned" are different sets and the overlap was previously ambiguous):

> A client user may **edit, change the status of, and reassign** any task that is **client-visible, in their own company, and either assigned to a client-side user or created by a client user**.

  1. **A task assigned to a tenant user is read-only to client users**, apart from posting shared comments. If the fractional owns the work, the client asks rather than edits.
  2. **Reassignment by a client user is always bounded to users in their own company** — they can hand work to a colleague, never to a fractional, and never outside the company.
  3. **Soft-deleting is narrower than editing:** a client user may delete only tasks **they created**. Deleting work a fractional assigned is not a client's call.
  4. This rule is the `client-editable` scope in `03_access_matrix.md` rows 7.4–7.6.
10. Goals and Projects carry a status **derived from their children at read time**, overridable by a manual value. *(Owner-approved precedence 2026-09-11, ignoring cancelled children: `waiting_on_client` > `blocked` > `in_progress` > `done` > `not_started`; all children done means done, all cancelled means cancelled, and a mix of done and not-started reads as in progress. `waiting_on_client` leads because FR-3.8 says the client being the blocker is the most useful thing a report can say.)* The derived value is **never stored** — a stored rollup drifts the moment a child changes outside the code path that wrote it. Clearing the override returns the entity to the derived value.

**Visibility**

11. Every Task carries `is_client_visible`, defaulting to true when the task has a client company and false otherwise.
12. **Comments carry `visibility ∈ {internal, shared}`.** Tenant users choose per comment and the current choice is unmistakable in the UI before posting. Client users see only `shared` comments and can only create `shared` ones.
12a. **A tenant user's comment defaults to `internal`.** The two failure modes are not symmetric: a comment meant for the client that stayed internal is noticed and reposted, while an internal remark that went to the client cannot be recalled. The safe default is the recoverable one.
13. A client user sees only: their company's goals, projects, and client-visible tasks, and shared comments on them.
14. Changing a task from client-visible to hidden is audited, and the reverse warns that prior activity will become visible.

**Updates — the source material for digests**

15. Every meaningful change writes a **`TaskUpdate`** event: status change, assignee change, due-date change, comment added, checklist item completed, task created, task completed. Each records actor, timestamp, and from/to values.
16. **On a status change, a tenant user is prompted — not forced — for a one-line "what this means for the client".** Optional, skippable, and the prompt states why it is being asked.
17. Digest quality depends on FR-3.16, so the client-facing line is a first-class field on the update, not a comment.
18. A tenant user can add a client-facing narrative to a task at any time without changing status.

**Digest assembly**

19. For a given stakeholder and period, a digest gathers `TaskUpdate` events on every Goal, Project, and Task where that person is an effective stakeholder, filtered to **client-visible tasks and shared comments only**.
20. **A stakeholder is a Contact, not a User.** A portal login is optional and orthogonal: digests go to the Contact's **primary email address** whether or not that person has ever signed in. A client's CFO who receives the weekly report but never opens the portal is a first-class stakeholder, and the common case.
20a. **Stakeholders attach at Goal, Project, or Task level.** Effective stakeholders for a task are the union of all three, de-duplicated per person, with the most specific attachment deciding cadence (assumption F12).
20b. Where a stakeholder Contact *does* have a linked User, the portal and the digest are two views of the same entitlement — no separate subscription list exists.
21. Each stakeholder carries a cadence: **`every_update`, `weekly` (default), `monthly`.**
22. `every_update` is **batched with a 30-minute quiet window**, so one editing session produces one email rather than six.
23. `weekly` and `monthly` fire on a per-tenant send day and hour, in tenant timezone. **Default: Friday 08:00.** *(Owner decision 2026-09-11: a **monthly** digest goes out on the **first send-day of the month and covers the previous calendar month** — 3 October covers all of September. Generated the day before, like the weekly.)* A Friday send means the approval batch is generated Thursday morning, inside a working day; a Monday send would put the batch in front of you on Sunday, where it would not be actioned and every digest would expire.

**Digest composition and approval**

24. Two composition modes, held as **`company.digest_ai_prose`** on each client company (seeded from a tenant-level default, changeable per client at any time):
    - **AI prose on** — Claude writes the connective narrative that turns transitions into a report. It is given **only** the status transitions and the human-written client-facing lines, and is instructed that it must not assert any fact not present in that input.
    - **AI prose off** — deterministic template: status transitions and human-written text only, no AI output whatsoever.
25. **`hold_all_digests` is a per-tenant setting, default ON for Beta.**
26. **While `hold_all_digests` is ON, every digest waits for approval — AI-drafted and deterministic alike.** ⛔ **REVIEW QUEUE (R4, R5).**
27. When `hold_all_digests` is OFF: **AI-drafted digests still require approval** (⛔ R4); deterministic digests send on cadence without approval.
28. **Scheduled digests** (`weekly`, `monthly`) are **generated 24 hours before their send window**, so review is possible without being urgent. With the FR-3.23 default this is **Thursday 08:00 generation, Friday 08:00 send** — a full working day to review, and no approval batch landing on a weekend.
28a. **`every_update` digests cannot use a 24-hour lead**, since the whole point is promptness. An `every_update` digest is **generated when its 30-minute quiet window closes** (FR-3.22). From that moment it follows exactly the same rules as any other digest: with `hold_all_digests` ON it waits in the approval screen; with it OFF, an AI-drafted digest still waits and a deterministic one sends.
28b. **Stated plainly so it is not a surprise in week one:** `hold_all_digests` ON *and* a stakeholder on `every_update` produces frequent small approvals — potentially several a day. That is accepted for Beta rather than engineered around, because the alternative is a special case in the one rule that must not have special cases. If it proves annoying in practice, the remedy is to move that stakeholder to `weekly` or to turn AI prose off for them, not to loosen the hold.
28c. FR-3.30a (stale drafts) applies to `every_update` digests too, and will fire often for them by nature. The regenerate action is one click for exactly this reason.
29. The **approval screen** lists all pending digests with recipient, period, and full rendered content, offering per-digest **approve / edit / skip** and an **approve-all** for a batch that has been read.
30. **An unapproved digest never sends.** At its send window it is marked `expired`, and **its content rolls into the next period's digest** so nothing is lost — it is deferred, not dropped.
30a. **A draft that has been overtaken by events is marked stale, not silently sent.** If a `TaskUpdate` lands on any entity covered by a **generated but not yet approved** draft, that draft is flagged **stale** in the approval screen, naming what changed, with a **one-click regenerate**. A stale draft can still be approved as-is — the flag informs the reviewer, it does not block them — but it can never be approved without the staleness being visible first.
30b. **An update arriving after approval rolls into the next period.** Once a draft is approved, it is a sent or sending artefact and is never rewritten in place. A late `TaskUpdate` is simply picked up by the next period's digest, on the same rules as any other update.

*Why 30a and 30b exist:* the 24-hour review window in FR-3.28 is exactly the window in which work continues. Without these two rules a Thursday-generated digest could be approved Friday morning while describing Wednesday's state, and a client would receive a report the fractional believed they had checked.
31. **If a period contains zero qualifying updates, no digest is generated and no email is sent.** Nobody should ever receive "nothing happened this week."
32. Every send writes an `AuditEvent`, appears on the entity timeline, and updates a per-stakeholder "last notified" value.
33. Every digest email footer carries a control for the recipient to **change their own cadence or stop receiving digests**, without contacting the fractional.
33a. **That link is authenticated by a signed, expiring token bound to the stakeholder row — not by a session**, because most stakeholders have no login (FR-3.20). The token grants exactly one capability: read and change the cadence on that one stakeholder row. It cannot read a task, a digest, or anything else.
33b. The token is long-lived enough to survive a forwarded email being opened late (30 days), single-purpose, and revoked when the stakeholder is removed.

**Portal access and seats**

33c. **Portal access is granted per Contact by a tenant user** — the FF, or a CF assigned to that client company (FR-1.9a). **VAs cannot grant, revoke, or change portal access.**
33d. Granting access to a Contact at a client company: creates the linked **User** (FR-1.1 / assumption F1), assigns role **FCC or ECC** (defaulting to FCC when the Contact is the company's `primary_contact` and ECC otherwise), **consumes one seat against the company's `seat_count`**, and sends a magic link.
33e. **When seats are exhausted, the grant fails with a clear message naming the company's seat count and how many are in use** — not a generic error, and never by silently succeeding without a seat.
33f. Seat count is set by the **FF only**. Changing it below the number in use does not revoke anyone; it blocks new grants until usage falls below the new number, and says so.
33g. **Revoking access** frees the seat, **invalidates the user's active sessions and every outstanding magic link**, and leaves the Contact, their stakeholder rows, and all their comments and tasks intact. Revocation is not deletion — a revoked person keeps receiving digests if they are still a stakeholder, because those are separate entitlements (FR-3.20).
33h. Grants and revocations are audited with actor and timestamp.

**Client portal**

34. The portal is scoped by both tenant and client company (FR-0.2).
35. Client users can **create tasks**, comment, complete, and assign within their company, subject to FR-3.9a.
35a. **Client users may also create Projects** — `own-company`, no parent Goal, `created_by_client = true` — so the portal is usable as a real task tool rather than a list that only ever grows. **Goals remain fractional-only:** a Goal is the strategy the engagement is being judged against, and it is not the client's to author.
35b. A client-created project is visible to the tenant staff on that account like any other, and its tasks follow the ordinary stakeholder and digest rules.
36. **A client user creating a task or comment does not pass through any review queue.** It is a person writing about their own work; a queue there would make the portal unusable. Stated explicitly so the review rule is not over-applied.
37. Client-created tasks default to client-visible, and notify the tenant owner of the parent project (or the company's assigned fractional if none) subject to the same 30-minute quiet window.
38. The portal offers an **on-demand progress report** rendering the same content as a digest for a chosen period, with no email and no approval required — because a client pulling a report has no outward effect.
39. List view and board (status-column) view. Both filterable by project, assignee, and status.

**Tenant notifications**

40. Tenant users are notified in-app and by email when a client comments or creates a task, batched on the same 30-minute quiet window. *(Owner decision 2026-09-11: the in-app half is a **feed built from the `task_update` rows already recorded** for client actions — no notification table and no per-user read state. The email half is batched as specified.)*

### Out of scope for Beta

1. Recurring tasks.
2. Task dependencies, critical path, or Gantt views.
3. Time tracking or billable hours.
4. File attachments on tasks or comments.
5. Custom statuses or custom fields.
6. **Client user management by the FCC** — `CLAUDE.md` places it later; seats are allocated by the FF in Beta.
7. Calendar view and calendar sync.
8. Native mobile applications (the portal is responsive web).
9. @-mentions and notification rules beyond stakeholder cadence.
10. Task templates (the Strategy Map conversion in Module 4 is the only bulk-create path).
11. Cross-client reporting or portfolio dashboards for the FF.

### Acceptance criteria

**AC-3.1 — Three levels, and only three.** Create a Goal, a Project under it, and a Task under that. Confirm no control exists to create a task under a task, and that the API rejects a task whose parent is a task. Add three checklist items to the task and complete one.

**AC-3.2 — A standalone task is first-class.** Create a task with no project and no goal. It saves, appears in list and board views, and can carry stakeholders.

**AC-3.3 — The client-facing line is prompted, not forced.** Move a task to In progress. The prompt for "what this means for the client" appears. Skip it — the status change saves. Move another task and supply the line; confirm it is stored on the update, not as a comment.

**AC-3.4 — Internal comments never leak.** Post an internal comment and a shared comment on a client-visible task. Sign in as FCC: only the shared comment is visible, and the internal comment's text does not appear anywhere in the page source or API response. Confirm the FCC comment form offers no visibility choice.

**AC-3.5 — Digest content is faithful.** Create a project with two tasks and one stakeholder on weekly cadence. Move both to In progress, adding a client-facing line to one. Run generation. The pending digest names both transitions and quotes your line **verbatim**. Read the AI narrative: **it contains no fact, name, date, or claim that is not present in those two transitions and that one line.**

**AC-3.6 — Nothing sends while held.** With `hold_all_digests` ON (the default), complete AC-3.5 and wait past the send window. **The dev outbox is empty.** The digest shows as `expired`. Its content appears in the next period's pending digest.

**AC-3.7 — Approval sends, and is recorded.** Approve a pending digest. It sends. The project timeline shows the send with recipient and timestamp; the stakeholder's "last notified" updates; an `AuditEvent` exists naming the approver.

**AC-3.8 — The carve-out behaves exactly as specified.** Turn `hold_all_digests` OFF. With AI prose **ON**, generate a digest — **it still waits for approval**. With AI prose **OFF**, generate a digest — it sends on cadence with no approval, and its content is only status transitions plus text you wrote.

**AC-3.9 — Silence produces silence.** Let a weekly period pass with no updates on a stakeholder's tasks. No digest is generated and no email is sent.

**AC-3.10 — Every-update batching.** Set a stakeholder to `every_update`. Make four changes within five minutes. **Exactly one email** is produced (subject to the approval rules in force).

**AC-3.11 — Stakeholder inheritance and override.** Attach a stakeholder at Project level with weekly cadence. Confirm they receive updates for all tasks in that project. Attach the same person to one task with monthly cadence. Confirm that task's updates follow monthly and the rest stay weekly.

**AC-3.12 — Self-service cadence.** From a delivered digest, follow the footer link. Without signing in with a password, change cadence from weekly to monthly. Confirm the stakeholder record updated and the change is audited.

**AC-3.13 — Client task creation works and is not queued.** As FCC, create a task, assign it to an ECC in the same company, and comment. All three take effect immediately with no approval step. The tenant owner receives a notification within the quiet window.

**AC-3.14 — Client assignment is bounded.** As FCC, open the assignee picker. It lists only users in your own company. Attempt via the API to assign a task to a user in another company and to a tenant user not on your account: both are rejected.

**AC-3.15 — On-demand report needs no approval.** As FCC, open a progress report for last month. It renders immediately, matches the content rules of a digest, and sends no email.

**AC-3.16 — "Waiting on client" is visibly distinct.** Set a task to Waiting on client. In the portal it is rendered distinctly from Blocked, and the distinction survives into the digest text.

**AC-3.17 — Client-company isolation.** As FCC of company A, request by direct URL: a goal, a project, a task, a comment, and a progress report belonging to company B **in the same tenant**. All return 404. Repeat for a company in a different tenant. All return 404.

**AC-3.18 — Role boundary on digest approval.** As a VA, open the digest approval screen: content is visible, approve and send controls are absent, and calling the approve endpoint returns 403. As a CF, confirm approval succeeds for an assigned client company and returns 403 for an unassigned one.

**AC-3.19 — Hidden tasks stay out of digests.** Set a task to not client-visible and update it. Confirm the update appears in no stakeholder digest and is absent from the client portal, while remaining fully visible internally.

**AC-3.20 — A draft overtaken by events is flagged, and regenerates. (FR-3.30a.)** Let a digest draft generate (Thursday). Before approving it, move one of its covered tasks from In progress to Done and add a client-facing line. Open the approval screen: **the draft is marked stale and names the change.** Confirm it can still be approved as-is. Instead click regenerate: the new draft includes the Done transition and the new line, and is no longer stale.

**AC-3.21 — A late update rolls forward, and never rewrites a sent digest. (FR-3.30b.)** Approve a digest. After approval, update a covered task. Confirm the approved digest's stored content is **byte-for-byte unchanged**, that no second email is produced for the current period, and that the late update appears in the next period's pending draft.

**AC-3.37 — The client-edit rule holds at all four boundaries. (FR-3.9a.)** In one client company, set up four client-visible tasks: (i) created by a client user, (ii) assigned to a client user, (iii) assigned to a **tenant** user, (iv) created by a client user in a **different** company. As an ECC: edit and restatus (i) and (ii) — both succeed. Attempt to edit (iii): **refused**, while posting a shared comment on it succeeds. Attempt (iv): **404**. Then attempt to reassign (i) to a tenant user and to a user at another company: **both refused**; reassigning to a colleague in their own company succeeds.

**AC-3.38 — Clients delete only what they created. (FR-3.9a.3, matrix 7.6a.)** As an FCC, soft-delete a task you created: succeeds. Attempt to delete a task a fractional created and assigned to a client user — editable under FR-3.9a but **not deletable**: refused.

**AC-3.39 — Clients create projects but not goals. (FR-3.35a, matrix 7.2/7.2a.)** As an FCC, create a project: it succeeds with `created_by_client = true`, no parent goal, and your own company set. Add two tasks to it and confirm they behave like any other task. Confirm **no control exists to create a Goal** and that the goal-create endpoint returns 403.

**AC-3.33 — One update reaches two recipients independently. (Data model: `digest_item`.)** Put contact X on a Goal at weekly and contact Y on one task inside it at `every_update`. Make one status change on that task. Confirm: Y's `every_update` digest generates on quiet-window close and, once sent, **X's weekly digest still contains that same update**. Approve X's weekly digest; confirm the update now shows as consumed for both and is not repeated to either next period.

**AC-3.34 — Expiry releases one claim without touching the other.** Repeat AC-3.33, but let X's weekly digest expire unapproved. Confirm the update is owed to X again and appears in next week's draft, while Y's already-sent digest is unchanged and Y is not re-sent anything.

**AC-3.35 — One recipient, one Friday email. (Data model: digest keyed by recipient.)** Add the same contact as a stakeholder at both Goal level and Task level, both weekly, and update tasks under each. On Friday, confirm **exactly one digest** exists for that person for that period, containing updates from both attachments — not two emails.

**AC-3.36 — Derived status is not stored. (FR-3.10.)** Set a Goal's status by override, then clear the override; confirm it returns to the value derived from its children. Change a child task's status directly in the database and re-read the Goal: the derived status reflects the change with no recalculation step.

**AC-3.23 — Comment default is internal. (FR-3.12a.)** Open a comment form as a tenant user and post without touching the visibility control. The comment is `internal`. Confirm as FCC that it is not visible and its text is absent from the API response.

**AC-3.24 — A stakeholder needs no login. (FR-3.20.)** Add a Contact with no linked User as a weekly stakeholder. Generate and approve a digest. It is delivered to that Contact's primary email. Confirm no User row was created and no portal seat was consumed.

**AC-3.25 — Cadence link works without a session. (FR-3.33a–33b.)** From that delivered digest, in a private window with no session, follow the footer link and change weekly to monthly. It succeeds; the stakeholder row updates; the change is audited. Then attempt, using the same token, to fetch a task, a digest, and another stakeholder's row: **all are refused.** Remove the stakeholder and confirm the token no longer works.

**AC-3.26 — On-demand report requires a login. (FR-3.38.)** Confirm the on-demand progress report is unreachable with only a cadence token, and reachable by a signed-in FCC.

**AC-3.27 — Portal grant creates the user and consumes a seat. (FR-3.33c–33d.)** Set a client company's `seat_count` to 2. As FF, grant portal access to the company's `primary_contact`: a User is created with role **FCC**, one seat is consumed, and a magic link is sent. Grant to a second contact: role defaults to **ECC**, second seat consumed.

**AC-3.28 — Seat exhaustion fails clearly. (FR-3.33e.)** With both seats used, attempt a third grant. It fails with a message naming the seat count and current usage. **Confirm no User was created and no magic link was sent.**

**AC-3.29 — Revoke frees the seat and cuts access. (FR-3.33g.)** Sign in as an ECC in one browser. In another, revoke their access. Confirm: their session no longer authenticates, a magic link issued before revocation no longer works, the seat is free, and their Contact, comments, and tasks all still exist. If they were a stakeholder, confirm they still receive digests.

**AC-3.30 — Only FF and assigned CF grant access. (FR-3.33c.)** As a VA, confirm no grant or revoke control exists and both endpoints return 403. As a CF assigned to company A, confirm granting on A succeeds and on unassigned company B returns 403.

**AC-3.31 — Seat count is FF-only and does not revoke retroactively. (FR-3.33f.)** As FF with 2 seats in use, lower `seat_count` to 1. Confirm no one loses access, and the next grant is refused with an explanatory message. As CF and VA, confirm the seat-count control is absent and the endpoint returns 403.

**AC-3.32 — `every_update` generates on quiet-window close. (FR-3.28a–28c.)** With `hold_all_digests` ON, set a stakeholder to `every_update` and make two changes. **30 minutes after the last change**, one digest appears in the approval screen — not 24 hours later. It sends only on approval. Turn `hold_all_digests` OFF with AI prose OFF and repeat: the digest sends on quiet-window close with no approval.

**AC-3.22 — Send timing default.** With tenant timezone `America/Denver` and defaults unchanged, confirm a weekly digest generates **Thursday 08:00 local** and its send window is **Friday 08:00 local**, and that both shift correctly across a daylight-saving boundary.

---

## 6. Module 4 — Strategy session tool

### Purpose

The instrument that turns a 75-minute diagnostic conversation into a document the prospect will pay to act on, and — on conversion — into the engagement's actual work plan. It runs the owner's real Operations template (seeded verbatim from `strategy_session_seed.md`): a pre-call web form covering the Snapshot and the Six Key Components self-rating, then a live in-call view where diagnostic answers are captured while Claude proposes candidate Strategy Map rows and a "mirror" in a side tray for the fractional to accept, edit, or discard. The output is a same-day PDF, and on conversion each map row becomes a Goal or a Project in Module 3 — so the thing the client agreed to in the room is the same thing they watch progress against for the next 90 days.

### User stories

**FF**
- As the FF, I send a prospect a pre-call form and see their Snapshot and Six Key Components ratings before the call, so I arrive knowing where to look first.
- As the FF, I run the call from one screen that keeps me on time and shows me which must-ask questions I have not covered yet.
- As the FF, I get candidate Strategy Map rows drafted as answers land, and I accept, edit, or bin each one — the map is mine, drafted faster.
- As the FF, I see exactly what the prospect will receive before I send it, with my private notes and the investment range excluded by default.
- As the FF, I convert a won session into Goals and Projects, choosing per row, and edit them before the engagement starts.

**CF**
- As a CF, I run sessions for my own prospects with the same tooling, and I can use the tenant's template without being able to edit the template itself.

**VA**
- As a VA, I schedule sessions and send pre-call form links directly, so the FF only does the call. **This is the single exception to "a VA never sends"** (assumption H7a): a pre-call invite is a template-only, non-AI email from the tenant address carrying a tokenised form link, with no discretionary content for a reviewer to catch.
- As a VA, I can see the session and its answers **except the §9 investment range and reaction**, which are financial and outside my access.

**FCC / ECC**
- **No stories.** A strategy session subject is a prospect, not a portal user. The pre-call form is a public tokenised page requiring no account (assumption F13). If the prospect converts, they become a client user afterwards, in Module 3.

### Functional requirements

**Template**

1. A **StrategyTemplate** contains ordered **Sections**, each containing ordered **Questions**. Beta seeds the Operations template verbatim from `strategy_session_seed.md`, all nine sections.
2. Every Question carries: `ask_when ∈ {precall, live}` (**fractional-overridable per question**), `must_ask` (the ★ flag), `order`, `group` (the diagnostic's six areas), a `response_schema`, and an optional **fractional-only note field never rendered to the prospect or in the PDF**.
3. Five response schemas, per assumption F13b: `free_text`, `rating_1_10` (value + optional comment), `diagnostic_triple` (*what they said* / *who or what causes it* / *what they tried and why it didn't stick*), `value_pair`, `agreed_note`. Section 8 uses a fixed two-row `path_reaction` structure.
4. Only the FF may edit the tenant's template. CFs and VAs use it.
5. **A session snapshots the template version it was run against.** Editing the template later never rewrites the content or structure of a past session.

**Pre-call form**

6. The pre-call form is a **public URL bearing a signed, expiring token** (30 days). No login.
6a. The invitation carrying that link is producer `precall_invite` — **template-only, non-AI, from the tenant address — and FF, CF, and VA may all send it directly** (H7a). It is the only send a VA may make without approval.
7. It renders exactly the questions whose effective `ask_when` is `precall` — seeded as Section 1 (Snapshot) and Section 2 (Six Key Components), with Section 3 items 1–3 flippable.
8. It autosaves and is resumable from the same link.
9. Merge fields resolve at render: `{Visionary} {Integrator} {Location A} {Location B} {Company} {Session date} {Fractional name}`. **An unresolved `{Integrator}` renders a "no Integrator identified" note**, never a blank or a literal brace.
9a. **Each merge field has one declared source, so there is somewhere for the data to live:**

| Field | Source |
|---|---|
| `{Visionary}` | Session's **`visionary_contact`** — nullable FK to Contact |
| `{Integrator}` | Session's **`integrator_contact`** — nullable FK to Contact |
| `{Location A}` / `{Location B}` | First and second entries of the Company's **ordered location list** (FR-1.3) |
| `{Company}` | Session's Company |
| `{Session date}` | Session's scheduled date |
| `{Fractional name}` | Session owner's display name |

9b. Both contact fields are **nullable and set when scheduling the session**, defaulting `{Visionary}` to the company's `primary_contact` (FR-1.3a). A company with fewer than two locations resolves `{Location B}` to the same graceful note as an absent Integrator — the degradation rule in FR-4.9 is general, not Integrator-specific.
10. Submission notifies the session owner. The prospect may edit until the session starts.

**Six Key Components**

11. Ratings are 1–10 with optional comment, across Vision, People, Data, Issues, Process, Traction.
12. The **average and the lowest-scoring component are computed at read time**, not stored, and the lowest is surfaced as "where to look first".
13. The lowest-score flag is passed to Claude as a hint when drafting the mirror.

**Live view**

14. One screen for the call, polling every 5 seconds. No WebSockets.
15. It displays the seed's **section time budget** (10 / 25 / 5 / 15 / 5 / 10 minutes, ~75 total) as elapsed-versus-budget, and a **count of unanswered ★ must-ask questions**.
16. Diagnostic answers are captured in their three fields, grouped by the six areas.
17. Section 3 item 4 (whether Visionary and Integrator describe the destination the same way) is marked as a **fractional observation, not asked aloud**, and is visually distinct from questions to be spoken.

**AI assistance**

18. Claude proposes **candidate Strategy Map rows** into a side tray with columns: bottleneck, root cause, the fix, owner, 30/60/90, measurable, notes. ⛔ **REVIEW QUEUE (R6):** a candidate becomes a map row **only when the fractional accepts it**. Accept, edit-then-accept, and discard are all one click.
18a. **Claude is not called on every answer save.** Drafting is triggered by exactly two things: **(a) an explicit "Draft rows" button**, always available, and **(b) automatically when every question in a diagnostic area has been answered.** Nothing else triggers a call.
18b. **Why:** a call per keystroke-save would be slow, expensive, and would fill the tray with candidates drafted from half a sentence — actively worse than no suggestion, because the fractional is mid-call and cannot afford to read noise.
18c. **Every Claude call in this module writes an `AiCall` row** (assumption E1.7) recording tenant, session, trigger, tokens, and cost — so the per-session cost of the tool is a number you can look up, not a guess.
18d. A draft run never removes or alters candidates already in the tray, and never touches accepted rows.
19. Claude drafts the **mirror** — the stated goal and which bottleneck, if fixed first, unlocks it — from Sections 3 and 4. ⛔ **REVIEW QUEUE (R7):** proposed, edited by the fractional, never auto-saved.
20. Map rows are reorderable, with the seed's sequence prompt available: "What has to happen first for the rest to work?"
21. An empty map shows the seeded **worked example row** (supervisor overload → area lead per 8 sites), clearly labelled as an example and dismissible.
22. Sections 7 (values), 8 (two paths with reaction / honest risk / leaning), and 9 (scope agreement) are captured live.

**Output PDF**

23. The PDF renders: Snapshot, the Six Key Components chart, the mirror, the Strategy Map, the two paths, and what they value.
24. **Excluded by default, each with an explicit per-block "include in PDF" toggle defaulted off:**
    1. every fractional-only note field on any question,
    2. the Strategy Map's **Notes / mechanics from experience** column,
    3. §4 diagnostic internal observations,
    4. §3 item 4 — the Visionary/Integrator alignment observation,
    5. **all of §9**, including the investment range, their reaction to it, and the proposal due date.
25. The send screen shows a **true preview of the exact PDF the prospect will receive**, not a description of it.
26. ⛔ **REVIEW QUEUE (R8):** the PDF is emailed only when the fractional reviews and clicks send. "Same day" is a workflow expectation, not an automation.
27. The PDF is stored against the session and re-downloadable.

**Conversion**

28. On conversion to client, the map is presented as a proposed tree. **The fractional chooses per row whether it becomes a Goal or a Project.**
29. Owner, 30/60/90 target date, and measurable carry across to the created record.
29a. **The map row's `owner_text` maps to `client_owner_contact_id` when it resolves to exactly one Contact at the company.** When it does not — "Maria in dispatch", or two people with the same first name — **the free text is preserved as written** and the FK stays null. An ambiguous owner is never guessed, and a useful scrap of text is never dropped because it failed to resolve.
30. ⛔ **REVIEW QUEUE (R9):** every row is editable and de-selectable, and **nothing is created until the FF confirms**.
31. Created records keep a **link back to the map row** that produced them, so a later progress report can point at the bottleneck the client named.
32. Conversion also flips the contact's pipeline stage to `client` and creates the client company if needed — subject to the same single confirmation.

### Out of scope for Beta

1. Multi-facilitator live sessions (one fractional drives).
2. Prospect-visible live view during the call.
3. Proposal or contract generation, and e-signature.
4. Template versioning UI beyond the per-session snapshot in FR-4.5.
5. Multi-discipline templates (Marketing, Finance, HR) — V1.
6. Scheduling and calendar integration; sessions are created manually.
7. Video or audio recording of the session itself (Module 2 handles recordings).
8. Benchmarking a prospect's Six Key Components against other sessions.

### Acceptance criteria

**AC-4.1 — Template seeds verbatim.** Open the seeded Operations template. All nine sections are present in the seed's order, the six diagnostic areas carry their questions, the ★ must-ask flags match the seed, and the seed's `precall`/`live` assignment matches.

**AC-4.2 — `ask_when` is overridable.** Flip Section 3 item 1 from `live` to `precall`. Generate a new pre-call form; the item appears on it. Confirm an existing in-flight session is unaffected.

**AC-4.3 — Pre-call form is public and resumable.** Open the form link in a private window with no session. Answer half of Section 1, close, reopen the same link: answers are still there. Submit; the session owner is notified.

**AC-4.4 — Merge field degrades as specified.** Run a session for a company with no Integrator identified. Every `{Integrator}` question renders with the **"no Integrator identified"** note. No literal `{Integrator}` and no blank gap appears on the form or the PDF.

**AC-4.5 — Scoring is computed and directs attention.** Enter the six ratings with Data lowest. The live view shows the average and flags Data as where to look first. Change Data's rating to the highest and confirm the flag moves without any stored value being edited.

**AC-4.6 — Timing and must-ask tracking are live.** Start a session. The section budget shows elapsed against the seed's minutes and the unanswered ★ count decreases as must-ask questions are answered.

**AC-4.7 — Map rows require acceptance.** Answer three diagnostic questions. Candidates appear in the tray. **Confirm the map itself is still empty.** Accept one, edit-and-accept another, discard the third: the map holds exactly two rows, one bearing your edit.

**AC-4.8 — The mirror is proposed, not saved.** Confirm Claude's mirror draft appears in the tray with the session's stored mirror still blank. Edit and accept; the stored value matches your edited text, not the draft.

**AC-4.9 — PDF exclusions hold. (From assumption F14a — verify all five.)** Populate every excluded field with a distinctive marker string: a fractional-only note, a Strategy Map "mechanics from experience" entry, a §4 internal observation, the §3 item 4 alignment observation, and a §9 investment range. Generate the PDF preview. **Search the generated PDF's text for each of the five markers: none appears.** Then toggle "include" on the mechanics column only, regenerate, and confirm that marker now appears and the other four still do not.

**AC-4.10 — Nothing is emailed without a click.** Complete a session and generate the PDF. **The dev outbox is empty.** Click send; it is delivered, recorded on the contact timeline, and audited.

**AC-4.11 — Conversion is per-row and confirmed.** Convert a session with four map rows. Choose Goal for two and Project for two, de-select one, and edit a title. **Before confirming, verify no Goal, Project, or Task exists.** Confirm: exactly three records are created, matching your choices, carrying owner, target date, and measurable, each linking back to its map row.

**AC-4.12 — Template snapshot protects history.** Convert a session, then edit the tenant template heavily (delete a section, reword questions). Reopen the completed session: its structure and content are unchanged.

**AC-4.13 — VA financial boundary.** As a VA, open a completed session. Sections 1–8 are visible; **§9's investment range and their reaction are not rendered**, and the API response for the session does not contain those values.

**AC-4.17 — Client owner resolves or is preserved. (FR-4.29a.)** Convert a session with three map rows: one whose `owner_text` is exactly a Contact's name at the company, one reading "Maria in dispatch" with no matching Contact, and one matching two Contacts with the same first name. Confirm the first sets `client_owner_contact_id`; the second and third leave it null and **retain the original text verbatim**.

**AC-4.18 — A VA can send a pre-call invite and nothing else. (FR-4.6a, H7a.)** As a VA, send a pre-call invite: it is delivered directly with no approval step and appears in the Outbox as `sent`. Then compose a manual email to a contact: it enters `pending_approval` and is not delivered. Confirm the referral-touch and digest approve endpoints still return 403.

**AC-4.19 — Template edits cannot reach a completed session. (FR-4.5; data model §6.)** Complete a session. Then, in the live template: delete an entire section, reword three questions, and change one question's `response_schema`. Reopen the completed session: **every section, prompt, and answer renders exactly as before.** Confirm the deleted question row carries `deleted_at` rather than being removed, and that the session's answers still resolve by `question_key` against its own snapshot.

**AC-4.15 — Merge sources resolve and degrade. (FR-4.9a–9b.)** Schedule a session for a company with two locations, setting `visionary_contact` and `integrator_contact`. Confirm all seven merge fields resolve to the right values and that `{Visionary}` defaulted to the company's `primary_contact`. Then run a session for a company with **one** location and no Integrator: confirm `{Location B}` and `{Integrator}` both render the graceful note, and no literal brace or blank gap appears.

**AC-4.16 — Drafting triggers only twice, and is costed. (FR-4.18a–18d.)** Answer one diagnostic question and save. **Confirm no Claude call was made** — no new `AiCall` row, no new candidates. Click "Draft rows": one `AiCall` row appears with tokens and cost. Then complete every question in one diagnostic area: a second call fires automatically. Confirm candidates already in the tray, and any accepted rows, are unchanged by the second run.

**AC-4.14 — Tenant isolation.** A session, its pre-call form token, and its PDF from tenant B are unreachable from tenant A, including by direct token URL.

---

## 7. Module 5 — Meeting ingestion

### Purpose

Meeting notes arrive in a Google Drive folder (Gemini notes, in Beta) and become proposed records that a human approves. Claude reads each document and proposes: who was in the room and whether each person is someone we already know, what was agreed as an action item and by when, and what was promised that ought to become a task with stakeholders notified. **Nothing in this module ever creates a record or sends anything on its own** — the entire module is a review queue with a parser in front of it, which is why the design starts from the queue rather than adding approval to an importer. On a laptop that is not always on, ingestion is cursor-based rather than event-based (assumption A6), so three days of closed lid means three days of notes waiting, not three days of notes missed.

### User stories

**FF**
- As the FF, meeting notes I never open turn into a queue of proposed contacts and tasks I can clear in a few minutes.
- As the FF, when a name in the notes might be someone we already know, I am shown ranked candidates and I pick — the app does not guess.
- As the FF, I approve some items from a meeting and reject others, without all-or-nothing.
- As the FF, I press "sync now" instead of waiting for a timer when I have just finished a call.

**CF**
- As a CF, I review proposals for meetings on my assigned accounts.

**VA**
- As a VA, clearing the meeting queue is my job, and I can approve contacts and tasks from it — but any email it would generate still goes to the Outbox for FF approval.

**FCC / ECC**
- **No stories. Client users have no access to meeting ingestion, the Drive connection, or the review queue** — including for meetings about their own company. What reaches them is the resulting task, once a human has approved it.

### Functional requirements

**Connection and polling**

1. A tenant connects a Google Drive folder, stored as a **`DriveWatch`** with folder id, `page_token`, `last_polled_at`, and `last_error`.
2. A scheduled job every 10 minutes calls Drive's `changes.list` from the stored cursor and advances it **only after each file is durably recorded**.
3. **A "Sync now" control** runs the same job on demand.
4. Every file seen becomes a **`MeetingSourceFile`**, unique on `(tenant, drive_file_id, drive_version)` — re-polling never yields a second proposal for the same file version.
5. Ingestion is a two-step commit: record the file, then parse. A parse failure leaves the file recorded and retryable, and **the cursor never advances past unprocessed work**.
6. Supported: Google Docs (exported as text), `.txt`, `.docx`. Other file types are **recorded and skipped with a visible reason**, never silently ignored.
7. Connection health — last poll time, last error, files pending — is visible on one screen.

**Parsing and proposals**

8. Claude parses each file into a **`MeetingProposal`** holding: meeting date, title, **a drafted meeting summary**, a set of **participant proposals**, a set of **action-item proposals**, and a set of **deliverable proposals**.
8a. **The meeting itself is the point, not only the tasks it produced.** Approving a proposal creates a **`Meeting`** record — date, title, the reviewed summary, a link to the source Drive file, and its confirmed participants — **attached to the timeline of every approved participant contact**. Opening a contact six months later shows the meetings they were in, not merely the tasks that survived them.
8b. **The drafted summary is part of the proposal and is reviewed with it** — editable before approval, and discardable, in which case the Meeting is created with no summary. ⛔ **REVIEW QUEUE (R11a).**
8c. The Meeting is also linked to the client company where one is identified, so it appears on the company timeline once.
9. A **participant proposal** holds either a **new-contact candidate** (parsed name, email, title, company) **or** a set of **ranked existing-contact candidates** with a match reason and confidence — and always offers both paths to the reviewer.
9a. **Every participant proposal also carries a proposed contact type** (prospect / client / referral partner / vendor / coworker) drawn from the meeting's context, **which the reviewer confirms or changes.** The type is never applied unconfirmed.
9b. **Confirming `referral partner` triggers the onboarding path in FR-1.23a** — an Outbox draft with the flyer, `pending_approval`, cadence clock started. Approving a meeting proposal therefore never sends anything; it queues.
9c. **Confirming `vendor` prompts for service categories inline in the review queue** (FR-1.24–1.25), so a vendor is searchable the moment they are created rather than being fixed up later.
9d. For a participant matched to an **existing** contact, a confirmed type is **added** to that contact's types; it never replaces the existing set, and never alters their pipeline stage (FR-1.6a.3).
10. **Match order is exactly:** email address → email domain + name → name alone. The reason is displayed ("matched on email domain + name").
11. ⛔ **REVIEW QUEUE (R10):** no contact is created or linked until a human picks. Where candidates exist, the human chooses one or rejects them all and creates new.
12. An **action-item proposal** holds: text, proposed owner, proposed due date, and the source excerpt it came from. ⛔ **REVIEW QUEUE (R11).** On approval the proposed owner becomes the task's **`client_owner_contact_id`**; where that Contact also holds a portal login, the task may additionally be assigned to them. A client owner without a login is recorded as such — no user is invented to hold the field.
13. A **deliverable proposal** additionally holds proposed stakeholders and their cadence. ⛔ **REVIEW QUEUE (R12).**
14. **Every proposed item shows the passage of the source document it was drawn from**, so a reviewer can check the claim rather than trust it.
15. **Partial approval is required:** each item is independently approvable and rejectable. Approving three action items and rejecting one is a normal outcome.
16. Rejection is persistent — a rejected proposal is retained as `rejected` and **does not reappear** on the next poll.
17. A proposal can be **re-parsed** on demand (for example after a prompt improvement), producing a fresh proposal that supersedes the pending one; already-approved items are untouched.
18. Approving items creates real records via the same paths as manual creation, so all Module 1 and Module 3 rules — including tenant scoping, stakeholder cadence, and client visibility — apply identically.
19. **If an approved deliverable would notify a stakeholder, that notification enters the Outbox or the digest approval flow like any other** — approving a proposal creates the record; it does not authorise a send.

### Out of scope for Beta

1. A forward-to email address for meeting notes (`CLAUDE.md` places it later).
2. Notetaker integrations — Fathom, Otter, Fireflies, Zoom, Read.
3. Audio or video files in the watched folder.
4. Calendar integration to pre-populate attendees.
5. **Auto-approval of any kind, at any confidence level, ever.** Not a Beta limitation — a product rule.
6. Watching more than one folder per tenant.
7. Extracting decisions, risks, or sentiment; Beta extracts participants, action items, and deliverables only.
8. Editing the source document from within the app.

### Acceptance criteria

**AC-5.1 — Cursor survives downtime.** Note the cursor. Stop the app. Add three documents to the folder. Wait past two poll intervals. Start the app. **All three are ingested**, in order, exactly once.

**AC-5.2 — Idempotency.** Force three consecutive polls over an unchanged folder. No duplicate `MeetingSourceFile` and no duplicate proposal is created.

**AC-5.3 — Matching is ranked, shown, and never guessed.** Prepare a Gemini-style note naming two known contacts (one by email, one by name at a known company domain) and one unknown person. Sync. The proposal shows: an email match with its reason, a domain+name match with its reason, and a new-contact candidate for the third. **Confirm no contact has been created or modified at this point.**

**AC-5.4 — Human picks; a rejected match creates new.** For the domain+name match, reject the candidate and create a new contact instead. Confirm the new contact exists and the candidate was not modified.

**AC-5.5 — Partial approval.** From a proposal with four action items, approve two and reject two. Exactly two tasks exist. The two rejected items remain visible as rejected.

**AC-5.6 — Rejections do not resurrect.** Re-poll after AC-5.5. The rejected items do not reappear as pending, and no new proposal is created for that file version.

**AC-5.7 — Provenance is visible.** For each proposed action item, confirm the source excerpt is shown and matches text in the source document.

**AC-5.8 — Approval creates records but authorises no send.** Approve a deliverable with a stakeholder on `every_update`. The task and stakeholder exist. **The dev outbox is empty**; the resulting notification is sitting in the appropriate approval flow.

**AC-5.9 — Unsupported files are reported.** Drop a `.pdf` and a `.mp4` in the folder and sync. Both appear as recorded-and-skipped with a stated reason. Neither blocks ingestion of a valid document dropped alongside them.

**AC-5.10 — Failure is retryable and does not lose position.** With an invalid Anthropic key, sync a valid document. The file is recorded, the parse fails visibly, and the cursor has not advanced past it. Restore the key, retry, and confirm the proposal is produced.

**AC-5.16 — CF proposal scope has exactly two limbs. (Matrix `proposal-scope`, `drive_file_owner_email`.)** Ingest three files: (a) one whose participants match a company the CF is assigned to, (b) one owned in Drive by that CF with no matched participants, (c) one owned by the FF with no matched participants — an FF prospect meeting. As the CF: (a) and (b) are visible, **(c) returns 404**. As FF and as VA: all three are visible. Confirm `drive_file_owner_email` was captured at ingestion for all three.

**AC-5.12 — Approval creates the meeting on every participant's timeline. (FR-5.8a–8c.)** Ingest a note with three participants. Review the drafted summary, edit one sentence, and approve all three participants. Confirm **one** `Meeting` record exists carrying your edited summary and a working link to the source Drive file, and that it appears on the timeline of **all three** contacts and once on the client company. Repeat with the summary discarded: the Meeting is created with no summary.

**AC-5.13 — Contact type is proposed and confirmed, never applied silently. (FR-5.9a, 5.9d.)** Confirm each participant proposal shows a proposed type. Change one from `prospect` to `coworker` before approving. Confirm the created contact carries the type you chose, not the proposed one. For a participant matched to an existing contact that already has type `client`, confirm the newly confirmed type is **added** and `client` is retained, and that the contact's **pipeline stage is unchanged**.

**AC-5.14 — Referral confirmation queues onboarding and sends nothing. (FR-5.9b.)** Confirm a participant as `referral partner`. On approval: the contact exists with that type, **an onboarding Outbox draft exists in `pending_approval` with the flyer attached**, the cadence clock starts today, and **the dev outbox is empty.**

**AC-5.15 — Vendor confirmation captures categories inline. (FR-5.9c.)** Confirm a participant as `vendor`. The queue prompts for service categories before approval completes. Supply two. Confirm the created vendor is immediately returned by a category search (AC-1.8's path).

**AC-5.11 — Role and tenant boundaries.** As FCC and ECC, confirm no navigation to the queue exists and the endpoints return 403. As a user in tenant A, confirm tenant B's `DriveWatch`, source files, and proposals return 404.

---

## 8. Module 6 — Unified client communication

### Purpose

One place where the whole conversation with a client lives, so FF, CF, and VA see the same history instead of three partial copies in three mailboxes. Mail the app sends carries a per-thread reply address; when the client replies, the reply is matched back to the thread and appears on the client's record. Where a reply cannot be matched confidently it goes to an unmatched queue for a person to file, because a misfiled email is worse than a queued one. **This module's inbound half requires a publicly reachable webhook and therefore only functions after the Railway move** (assumption F16); it is built against replayed Postmark payloads locally, and the Phase 6 plan in `04_build_plan.md` sequences it accordingly.

### User stories

**FF**
- As the FF, I open a client's record and see the full email history — mine, my CF's, and the app's digests — in one thread list.
- As the FF, when a client replies from a personal address I have never seen, it lands in a queue for me to file rather than vanishing.

**CF**
- As a CF, I send from my own Gmail address to contacts on client companies I am assigned to, and those sends appear on the shared record automatically.

**VA**
- As a VA, I see the full communication history so I can pick up a thread's context, and I file unmatched inbound mail.
- As a VA, I **draft replies into the Outbox** for FF approval; I cannot connect Gmail and cannot send from any address (assumption H7).

**FCC / ECC**
- **No stories.** Client users interact through the portal and through email they receive; they have no view of the tenant's communication history, which includes internal correspondence about them.

### Functional requirements

**Outbound and threading**

1. Every app-originated email belongs to an **`EmailThread`** carrying a `thread_token`, the tenant, and the linked Contact and/or client company.
2. **Outbound mail carries the thread token in its headers, not in a reply address.** Beta has no inbound domain (assumption A3 — Gmail is the transport), so there is no `reply+<token>@` address. Instead:
    1. `Message-ID: <{thread_token}.{random}@{tenant-domain}>` — the token is recoverable from the Message-ID alone;
    2. `X-ExecsNowHQ-Thread: {thread_token}` as a custom header;
    3. `In-Reply-To` / `References` set to the last Message-ID we issued on that thread, so a follow-up threads in the client's mail client rather than starting a new conversation;
    4. Gmail's own `threadId`, stored on the thread at first send and reused on every later send.
2a. **`From` is the tenant's send-as alias**, verified against Gmail's `settings.sendAs` before any send. An unverified alias is a hard error naming the exact step to fix it — never a silent fallback to the fractional's personal address (FR-6.2b).
3. Personal sends via the Gmail API (FF, and CF on assigned accounts) are recorded to the same thread structure, so a personal reply and an app digest sit in one history.

**Personal sends, and how their replies come back**

3a. **The problem this used to solve is now mostly gone.** In the Postmark design, app mail and personal mail travelled by different routes and only the former was threadable. With Gmail as the transport (assumption A3), **everything goes out through Gmail**, so there is one route and one recovery mechanism.

3b. **App mail** is sent by the FF's connection as the tenant alias (FR-6.2a). **Personal mail** is sent by an FF or CF as themselves — a CF only to contacts on client companies they are assigned to (H7). Both are recorded on the same `EmailThread` and carry the same threading headers.

3c. **Replies are recovered by polling** the threads the app started (FR-6.5), which also captures a reply the fractional types **natively in Gmail** rather than in the app. The old Tier 1 blind spot no longer exists: it was a consequence of not reading the mailbox, and Beta now reads the threads it created.

3d. **VAs get neither** — they cannot connect Gmail at all, and app mail never picks up a VA's connection even if a row existed (H7).

3e. **Scopes:** `gmail.send` to send, `gmail.settings.basic` to verify the send-as alias, `gmail.readonly` to poll threads. All three are restricted scopes and all three are **free under the Internal consent screen** (C1) — no verification, no CASA assessment, no refresh-token expiry. **The bill arrives at V1**, and the Postmark transport option is what keeps a security assessment from being the only road to launch.

**Inbound**

5. **Inbound arrives by polling, not by webhook.** `users.threads.get` over the threads the app started, on a 15-minute schedule, cursor-based and tolerant of the laptop being closed (assumption F19). No public endpoint is required, which is why Module 6 no longer waits for Railway.
6. **Matching order:** Gmail `threadId` → `In-Reply-To` / `References` quoting a Message-ID we issued → the `X-ExecsNowHQ-Thread` header → sender email matched to a Contact → no match.
7. A matched message is appended to its thread and appears on the contact's timeline and the shared history.
8. ⛔ **REVIEW QUEUE (R13):** an unmatched message enters the **unmatched queue** and is **never dropped**. A human files it to a contact or thread, which optionally adds the sending address to that contact.
9. Quoted history and signatures are trimmed for display, with the full raw message retained and viewable.
10. Attachments are stored and downloadable, with size limits enforced.
11. **Authenticity comes from the transport, not from a shared secret.** With polling there is no webhook to forge: messages are read from the tenant's own mailbox over an authenticated Google API call. The Postmark webhook and its `POSTMARK_INBOUND_WEBHOOK_SECRET` verification are **V1**, arriving with the Postmark transport option.
12. Inbound processing is idempotent on the provider's message id — **a re-poll of the same thread does not duplicate a message**, which matters more with polling than with webhooks because every poll re-reads the whole thread.

**Local development**

13. The poller is written as a plain function over a parsed Gmail thread payload, so it can be exercised without a live mailbox.
14. A `manage.py replay_inbound <fixture.json>` command replays captured Gmail thread payloads against it.
15. Fixtures cover, at minimum: `threadId` match, `In-Reply-To` match, custom-header match, sender-email fallback, no match, reply-with-quoted-history, attachment, and re-poll of an already-ingested message. **These fixtures are the module's regression suite.**
16. **Module 6 runs on the laptop.** Polling needs no public endpoint, so the module completes locally and the Railway move (Phase 7) verifies nothing about it beyond continuing to work.

**Visibility**

16. Communication history is visible to FF and VA for all contacts, and to CF for contacts on assigned client companies.
17. Threads inherit the client-company scope; nothing in this module is exposed to FCC or ECC.

### Out of scope for Beta

1. **Two-way Gmail mailbox sync** — pulling the fractional's entire mailbox, including correspondence the app never initiated. Polling reads *only threads the app started*, and that boundary is deliberate: it is the difference between a tool that completes its own conversations and one that ingests the owner's private mail.
1a. **The Postmark transport and its inbound webhook.** Both are **V1**, reachable by setting `APP_MAIL_TRANSPORT=postmark`. The seam exists in Beta and is tested; the implementation does not.
1b. **A third-party delivery log.** Postmark's per-message activity trail does not exist in Beta. The Outbox is the only send log, and bounces are visible only in the fractional's Gmail. This is one of three trade-offs the owner accepted in choosing the Gmail transport (assumption A3).
2. IMAP or Outlook/O365 connection.
3. Shared-inbox workflow: assignment, SLA timers, canned replies, read receipts.
4. Sending from a tenant alias other than the configured `info@` address.
5. Automatic contact creation from an unmatched sender — filing is manual (assumption F16 and the review rule).
6. Threading of SMS or any non-email channel.
7. AI-drafted replies. Beta records and threads; it does not compose.

### Acceptance criteria

**AC-6.1 — Outbound carries a threadable reply address.** Send a digest and a manual email to the same contact. Inspect both: the reply address contains the same `thread_token`, and one `EmailThread` exists.

**AC-6.2 — Token match, by replay.** Replay the token-match fixture. The message appends to the correct thread and appears on the contact's timeline. No new thread is created.

**AC-6.3 — Sender fallback.** Replay a fixture with no token but a known sender address. It matches to that contact by email and threads correctly.

**AC-6.4 — No match queues, never drops.** Replay a fixture from an unknown address with no token. It appears in the unmatched queue. **Confirm it exists as a stored message** — not merely logged. File it to a contact; it moves onto that contact's timeline.

**AC-6.5 — Redelivery is idempotent.** Replay the same fixture twice. Exactly one message exists.

**AC-6.6 — Quoted history is trimmed but retained.** Replay the quoted-history fixture. The display shows only the new content; the full raw message is retrievable.

**AC-6.7 — Authenticity is enforced.** Post an unsigned/unauthenticated payload to the webhook. It is rejected without creating a message.

**AC-6.8 — VA send boundary.** As a VA, confirm no Gmail connect control and no send control exist, and that both endpoints return 403. Confirm the VA can still read history and file unmatched mail.

**AC-6.9 — CF assignment boundary.** As a CF, send to a contact on an assigned client company: it succeeds and is recorded. Attempt the same for an unassigned company: 403.

**AC-6.10 — Client users see nothing.** As FCC and ECC, confirm no navigation to communication history, and that thread, message, and unmatched-queue endpoints return 403.

**AC-6.11 — Tenant isolation.** Threads, messages, and unmatched items from tenant B are unreachable from tenant A, including by direct URL.

**AC-6.13 — Outbound carries the token in its headers, and From is the alias. (FR-6.2, 6.2a.)** Send an app email to an allow-listed address. Inspect the delivered message: `From` is the **tenant alias**, not the fractional's personal address; `Message-ID` contains the thread token; `X-ExecsNowHQ-Thread` carries the same token. Send a second message on the same thread and confirm `In-Reply-To` quotes the first.

**AC-6.14 — An unverified send-as alias is a hard error. (FR-6.2a.)** Point the tenant's `from_address` at an alias that is not a confirmed "Send mail as" address on the connected account. Attempt any send. It **fails with a message naming the alias, the Gmail settings path to fix it, and which addresses are available** — and **nothing is delivered from the fractional's personal address instead.**

**AC-6.15 — Polling captures a Gmail-native reply. (FR-6.5.)** Reply to an app-sent message from the client's mailbox, and separately type a reply into Gmail as the fractional. Poll. Both appear on the thread and on the contact's timeline. Confirm a second poll of the same thread creates no duplicates (FR-6.12).

**AC-6.16 — Polling tolerates downtime. (FR-6.5.)** Stop the app. Reply to two known threads. Wait past several poll intervals. Start the app: both are ingested exactly once, with no full-mailbox resync.

**AC-6.17 — A revoked Gmail token names its consequence. (Assumption A3, trade-off 1.)** Revoke the FF's Gmail credential and request a magic link. The failure message states that app mail — **including client sign-in** — cannot be sent until Gmail is reconnected. It does not surface as a generic 500, and no token is silently used from another account.

**AC-6.12 — Live round trip.** Send a real digest to an allow-listed address and reply to it. The reply appears on the contact's timeline within one poll interval. **This now runs on the laptop** — polling needs no public endpoint, which is why Module 6 no longer waits for the Railway move.

---

## 9. Beta exit criteria

Beta is complete when all six modules pass their acceptance criteria and the following hold across the whole application:

1. **Tenant isolation suite passes** against the registry described in assumption B3, with every domain model and endpoint registered. An unregistered model fails the meta-test.
2. **Role boundary suite passes** for all five roles against `03_access_matrix.md`, with VA-financial and ECC-cross-company cases explicitly covered.
3. **No path exists by which AI output reaches a client or creates a record without a human action**, verified by walking every row of the register in §2 and confirming its "if never actioned" behaviour.
4. **`hold_all_digests` is ON**, and turning it off is a deliberate, logged, single-tenant action.
5. The nightly backup has run, and **a restore into a scratch database has been performed at least once** and verified — a backup that has never been restored is a hypothesis.
6. `.env.example` is current and no secret is committed.
7. **The owner's real practice has run on the app with real clients**, measured concretely rather than by feel:
   - **at least 5 real progress digests approved and delivered** to real stakeholders;
   - **2 real strategy sessions run end to end**, each including a PDF reviewed and sent to the prospect;
   - **10 real meeting proposals reviewed**, with the **approve/reject rate reported** — whatever it is. A high rejection rate is a finding about extraction quality, not a failure to hide.

---

## 10. Decisions taken during review

**First review round** (closed):

1. **A2a — approved.** Magic-link emails send synchronously in the request; everything else queues.
2. **FCC and ECC stay functionally identical in Beta**, with the role codes kept distinct throughout the model, the access matrix, and the permission tests, so V1 user management attaches to FCC without a migration. `03_access_matrix.md` carries two columns whose Beta cells are identical rather than one merged column.
3. **Digest cadence default: generation Thursday 08:00, send Friday 08:00**, tenant time, with the reasoning written into FR-3.23 so it is not silently reverted.
4. **FR-3.30a / FR-3.30b** — stale-draft flagging and late-update roll-forward, covered by AC-3.20 to AC-3.22.

**Second review round** — all 17 items applied:

| # | Change | Where |
|---|---|---|
| 1 | Client invariant: a `won` stage in a `sales` pipeline is authoritative, one-directional | FR-1.6a · AC-1.12 |
| 2 | `ClientAssignment` + CF visible universe | FR-1.9a–9e · AC-1.13–1.15 |
| 3 | `Company.primary_contact` | FR-1.3, 1.3a |
| 4 | Referral fee terms, tenant blurb, 3-part touch, onboarding + flyer | FR-1.20a, 1.21a, 1.22, 1.22a, 1.23a–23d · AC-1.18–1.20 |
| 5 | Stage-draft send-by, 7 days default | FR-1.12 · AC-1.16 |
| 6 | Outbox = approval queue **and** complete send log | FR-1.15–15c · AC-1.17 |
| 7 | Note links to Contact/Company **and** Task | FR-2.3, 2.3a · AC-2.2 |
| 8 | PIN title leak closed, workflow + invariant | FR-2.11a, 2.11b · AC-2.3 |
| 9 | Recording cap 120 min | FR-2.14 · AC-2.5a |
| 10 | Portal grant, seats, revoke | FR-3.33c–33h · AC-3.27–3.31 |
| 11 | Stakeholder is a Contact; signed-token cadence link | FR-3.20, 3.20a–20b, 3.33a–33b · AC-3.24–3.26 |
| 12 | Comment defaults to `internal` | FR-3.12a · AC-3.23 |
| 13 | `every_update` generates on quiet-window close | FR-3.28a–28c · AC-3.32 |
| 14 | Merge field sources table | FR-4.9a–9b · AC-4.15 |
| 15 | Two drafting triggers, `AiCall` per call | FR-4.18a–18d · AC-4.16 |
| 16 | `Meeting` record, participant type, referral/vendor paths | FR-5.8a–8c, 5.9a–9d · AC-5.12–5.15 |
| 17 | Gmail reply capture, two tiers | FR-6.3a–3h · AC-6.13–6.16 |

**On #17 specifically.** I did not defer it to V1. **Tier 1 (Reply-To rewriting) ships in Beta and needs no scope beyond `gmail.send`** — it captures the client reply, which is the mail that matters, at no verification cost. **Tier 2 (polling known thread IDs) is opt-in** and closes the remaining gap — a fractional's own Gmail-native reply — but requires `gmail.readonly`, a restricted scope over the entire mailbox with a CASA assessment gating it for V1. Layering them means the product is not architecturally dependent on clearing that assessment. FR-6.3d states Tier 1's blind spot rather than leaving it implied.

**Two new assumptions were added to `00_assumptions.md`:** **F17** (Outbox as complete send log) and **F19** (Gmail reply capture, both tiers).

**Status:** `01_prd.md` is complete. Proceeding to `02_data_model.md`.
