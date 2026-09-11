# 03 — Access Matrix: Beta

**Phase 0 · Execs NOW HQ · for owner review**
**Built on:** `CLAUDE.md` (role definitions), `00_assumptions.md`, `01_prd.md`, `02_data_model.md`.

> **This document is the source of truth for permission tests.** The role-boundary suite (assumption B3) is generated from these rows: every row becomes a parametrised test asserting the expected result for all five roles. A row without a test, or a test without a row, fails the meta-test.

---

## 1. How to read the matrix

**Roles** are exactly the five in `CLAUDE.md`: **FF** founder fractional · **CF** contractor/employee fractional · **VA** virtual assistant · **FCC** founder of client company · **ECC** employee of client company.

**Cell values:**

| Value | Meaning | Expected HTTP |
|---|---|---|
| **✅** | Allowed, unconditionally within the tenant | 2xx |
| **🔸** | Allowed, **scoped** — the scope is named in the row's Notes | 2xx for in-scope, **404** out of scope |
| **❌** | Denied | **403** |
| **—** | Not applicable: no such surface exists for this role | 404 (route absent) |

**Two rules about status codes**, applied consistently and worth stating once:

1. **Out-of-scope reads return 404, not 403.** A 403 confirms the row exists. A CF probing for a client company they are not assigned to, or an ECC probing another company's task, must not be able to distinguish "exists but forbidden" from "does not exist." **Cross-tenant access always returns 404.**
2. **In-tenant, in-scope but role-forbidden actions return 403.** A VA hitting the digest-approve endpoint gets a 403: the row exists, the VA can see it, they simply may not perform that verb. Hiding that would make the product confusing for no security gain.

**Scope keys used in the Notes column:**

- `assigned` — CF must hold a live `client_assignment` for the client company (FR-1.9a).
- `owned` — the contact's `owner_id` is this user.
- `own-company` — the client user's `membership.client_company_id` matches the row's `client_company_id` (FR-0.2).
- `client-visible` — additionally requires `task.is_client_visible = true` and, for comments, `visibility = 'shared'`.
- `client-editable` — a client-visible task in the user's own company that is **assigned to a client-side user or was created by a client user** (FR-3.9a). Tasks assigned to a tenant user are read-only to clients apart from shared comments.
- `proposal-scope` — for a CF: a meeting proposal where **any participant is matched to a company they are assigned to**, *or* where the **source Drive file is owned by that CF** (their own meeting). FF and VA see every proposal.

**FCC and ECC columns are identical in every row of this document.** That is the deliberate outcome of the PRD review: user management is V1, and it is the only thing that will separate them. The columns are kept **separate rather than merged** so that when FCC gains capabilities in V1 it is a data change to this table and to test parameters — not a schema migration and not a re-derivation of the whole matrix.

---

## 2. Cross-cutting: tenancy and identity

| # | Action | FF | CF | VA | FCC | ECC | Notes |
|---|---|---|---|---|---|---|---|
| 2.1 | Read any row belonging to another tenant | ❌ | ❌ | ❌ | ❌ | ❌ | **404 always.** The non-negotiable rule (`CLAUDE.md`); enforced by the fail-closed manager (B1), not by views |
| 2.2 | Sign in with Google | ✅ | ✅ | ✅ | — | — | Invite-only; membership must pre-exist (C1) |
| 2.3 | Sign in by magic link | — | — | — | ✅ | ✅ | Client users have no other method (C3, C4) |
| 2.4 | Belong to more than one tenant | ❌ | ❌ | ❌ | ❌ | ❌ | One membership per user in Beta (B4) |
| 2.5 | View own profile / timezone | ✅ | ✅ | ✅ | ✅ | ✅ | |
| 2.6 | View the audit log | ✅ | ❌ | ❌ | ❌ | ❌ | |

## 3. Tenant settings

| # | Action | FF | CF | VA | FCC | ECC | Notes |
|---|---|---|---|---|---|---|---|
| 3.1 | View tenant settings | ✅ | 🔸 | ❌ | — | — | CF sees non-financial, non-secret settings only |
| 3.2 | Edit tenant settings | ✅ | ❌ | ❌ | — | — | `CLAUDE.md`: VA has no settings access |
| 3.3 | Set / rotate the Anthropic API key | ✅ | ❌ | ❌ | — | — | Write-only field; **no role can ever read it** (E1.3) |
| 3.4 | Read the Anthropic API key | ❌ | ❌ | ❌ | ❌ | ❌ | **Denied to everyone including FF** — there is no read path in the product |
| 3.5 | Connect the Google Drive folder | ✅ | ❌ | ❌ | — | — | |
| 3.6 | Edit the referral blurb | ✅ | ❌ | ❌ | — | — | FR-1.21a |
| 3.7 | Upload / replace the marketing flyer | ✅ | ❌ | ❌ | — | — | FR-1.23b |
| 3.8 | Toggle `hold_all_digests` | ✅ | ❌ | ❌ | — | — | The master safety switch (FR-3.25) |
| 3.9 | Toggle `digest_ai_prose` on a client company | ✅ | 🔸 | ❌ | — | — | CF: `assigned` |
| 3.10 | Set digest send day / hour | ✅ | ❌ | ❌ | — | — | |
| 3.11 | Set `audio_retention_days` | ✅ | ❌ | ❌ | — | — | |
| 3.12 | Manage stage automation rules | ✅ | ❌ | ❌ | — | — | |
| 3.13 | Manage email templates | ✅ | ❌ | 🔸 | — | — | VA may edit body copy, not create or delete rules |
| 3.14 | Manage contact types and service categories | ✅ | ❌ | ✅ | — | — | CRM hygiene is the VA's job (FR-1.9d) |
| 3.14a | **Manage pipelines** (create, rename, remove) | ✅ | ❌ | ❌ | — | — | **FF only, per pipeline.** A practice runs several — a sales pipeline and a nurture pipeline for referral partners (FR-1.6). Adding or removing one changes how the practice works |
| 3.15 | **Manage the stages within a pipeline** (rename, reorder, add, remove) | ✅ | ❌ | ❌ | — | — | **FF only, per pipeline.** Renaming is safe by design — behaviour keys on the stage's `semantic`, never its label — but adding and removing stages is a workflow change. A sales-kind pipeline must keep **exactly one `won` stage**; removing the last one is refused, because without it nothing can become a client (FR-1.6a) |
| 3.15a | **Read pipelines and their stages** | ✅ | ✅ | ✅ | ❌ | ❌ | Every tenant user works the board daily. Client users have no CRM surface at all (4.18) |
| 3.16 | Invite a CF or VA | ✅ | ❌ | ❌ | — | — | No self-serve signup (C1) |
| 3.17 | Change a member's role | ✅ | ❌ | ❌ | — | — | |
| 3.18 | Remove / revoke a tenant staff member | ✅ | ❌ | ❌ | — | — | Kills sessions; **for a CF also ends every `client_assignment` and disconnects Gmail** (FR-0.8c) |
| 3.19 | **View AI usage and cost (`ai_call`)** | ✅ | ❌ | ❌ | — | — | **Spend is financial** — `CLAUDE.md` gives the VA no financials, and a CF no tenant-wide spend |

## 4. Module 1 — Contacts & pipeline

| # | Action | FF | CF | VA | FCC | ECC | Notes |
|---|---|---|---|---|---|---|---|
| 4.1 | List / search contacts | ✅ | 🔸 | ✅ | — | — | CF: `assigned` companies + `owned` contacts (FR-1.9c). **VA sees all** (FR-1.9d) |
| 4.2 | View a contact | ✅ | 🔸 | ✅ | — | — | |
| 4.3 | Create / edit a contact | ✅ | 🔸 | ✅ | — | — | |
| 4.4 | Delete (soft) a contact or company | ✅ | 🔸 | ✅ | — | — | Soft delete (D2) is exactly what makes this safe to delegate |
| 4.4a | **Restore a soft-deleted record** | ✅ | 🔸 | ✅ | — | — | CF: `assigned`/`owned` |
| 4.5 | **Merge two contacts** | ✅ | ❌ | **✅** | — | — | **VA ✅, audited.** Post-import dedupe is the core of CRM hygiene and the VA runs the imports; a merge the VA cannot perform just sends the FF a queue of the cleanup the VA was hired to do. CF ❌ |
| 4.6 | Edit `contact.background` | ✅ | 🔸 | ✅ | — | — | |
| 4.7 | View / edit companies | ✅ | 🔸 | ✅ | — | — | |
| 4.8 | Set `company.primary_contact` | ✅ | 🔸 | ❌ | — | — | Determines the FCC default (FR-3.33d) |
| 4.9 | Change a contact's pipeline stage | ✅ | 🔸 | ✅ | — | — | Triggers the client invariant (FR-1.6a) |
| 4.10 | Unset contact type `client` / `is_client_company` | ✅ | ❌ | ❌ | — | — | Deliberate manual act (FR-1.6a.2) |
| 4.11 | Create / remove a `client_assignment` | ✅ | ❌ | ❌ | — | — | **FF only** (FR-1.9b). The row every `assigned` scope depends on |
| 4.12 | Set `company.seat_count` | ✅ | ❌ | ❌ | — | — | FR-3.33f |
| 4.13 | Run a CSV import dry run | ✅ | ❌ | ✅ | — | — | |
| 4.14 | Commit a CSV import | ✅ | ❌ | ✅ | — | — | VA commits and may roll back (Module 1 VA story) |
| 4.15 | Roll back an import batch | ✅ | ❌ | ✅ | — | — | |
| 4.16 | Set referral cadence / fee terms | ✅ | 🔸 | ✅ | — | — | Fee **terms** are free text about a partnership, not tenant financials |
| 4.17 | Search vendors by service category | ✅ | ✅ | ✅ | — | — | |
| 4.18 | Access any CRM surface | — | — | — | ❌ | ❌ | **Permanent boundary, not a Beta limitation** (Module 1 stories) |

## 5. The Outbox

| # | Action | FF | CF | VA | FCC | ECC | Notes |
|---|---|---|---|---|---|---|---|
| 5.1 | View the Outbox | ✅ | 🔸 | ✅ | — | — | CF: messages to contacts on `assigned` companies |
| 5.2 | Create / edit a draft | ✅ | 🔸 | ✅ | — | — | |
| 5.3 | **Approve and send a draft** | ✅ | 🔸 | ❌ | — | — | **The H7 boundary.** VA gets 403 (FR-1.19) |
| 5.4 | Reject a draft | ✅ | 🔸 | ✅ | — | — | Rejecting sends nothing; safe for a VA |
| 5.5 | Send a `precall_invite` directly | ✅ | 🔸 | **✅** | — | — | **The single VA send exception** (H7a, FR-4.6a): template-only, non-AI, tenant address |
| 5.6 | Send a `manual` email | ✅ | 🔸 | ❌ | — | — | FF/CF direct-to-`sent` via own Gmail; **a VA's `manual` becomes a `pending_approval` draft** (FR-1.19a) |
| 5.7 | Connect Gmail (Tier 1, `gmail.send`) | ✅ | ✅ | ❌ | — | — | H7 |
| 5.8 | Connect Gmail Tier 2 (`gmail.readonly`) | ✅ | ✅ | ❌ | — | — | Opt-in; restricted scope (FR-6.3g) |
| 5.9 | View the complete send log | ✅ | 🔸 | ✅ | — | — | The Outbox is also the log (FR-1.15) |

## 6. Module 2 — Notes

| # | Action | FF | CF | VA | FCC | ECC | Notes |
|---|---|---|---|---|---|---|---|
| 6.1 | Create a note | ✅ | ✅ | ✅ | — | — | |
| 6.2 | View an **unlocked** note | ✅ | 🔸 | ✅ | — | — | CF: notes on `assigned`/`owned` records |
| 6.3 | View a **PIN-locked** note's stub | ✅ | 🔸 | ✅ | — | — | Title only — and **"Locked note"** if the title was auto-derived (FR-2.11b) |
| 6.4 | View a PIN-locked note's **body** | 🔸 | 🔸 | 🔸 | — | — | **Scope is the PIN, not the role.** Anyone with the PIN, nobody without — including the FF |
| 6.5 | Set / change a PIN | ✅ | ✅ | ✅ | — | — | Requires a typed title first (FR-2.11a) |
| 6.6 | **Reset a PIN** | ✅ | ❌ | ❌ | — | — | **FF only, by emailed link, clears rather than reveals** (`CLAUDE.md`, FR-2.12) |
| 6.7 | Record audio / transcribe | ✅ | ✅ | ✅ | — | — | Consent reminder shown (FR-2.15) |
| 6.8 | Accept / edit / discard a Claude summary | ✅ | ✅ | ✅ | — | — | The note's author reviews (R3); the FF may too. Another CF or VA gets 403. (Retention and the Anthropic key are rows 3.11 and 3.3) |
| 6.9 | Access any note | — | — | — | ❌ | ❌ | **No client-visible note type exists in Beta** |

> **Row 6.4 is the only row in this document whose scope is not a role or an assignment.** It is worth stating plainly, as FR-2.13 does: a PIN screens a note from other users of the app. It does not protect it from the FF (who can reset), from a database dump, or from the nightly backup.

## 7. Module 3 — Task engine

| # | Action | FF | CF | VA | FCC | ECC | Notes |
|---|---|---|---|---|---|---|---|
| 7.1 | View goals / projects / tasks | ✅ | 🔸 | ✅ | 🔸 | 🔸 | CF: `assigned`. Client: `own-company` + `client-visible` |
| 7.2 | Create a **goal** | ✅ | 🔸 | ✅ | ❌ | ❌ | Strategy is the fractional's |
| 7.2a | Create a **project** | ✅ | 🔸 | ✅ | 🔸 | 🔸 | Client: `own-company`. A client using the portal as their task tool needs a way to group their own work; a client-created project has no parent goal by definition (FR-3.35a) |
| 7.3 | Create a task | ✅ | 🔸 | ✅ | 🔸 | 🔸 | Client: `own-company`. **No review queue** (FR-3.36) |
| 7.4 | Edit a task | ✅ | 🔸 | ✅ | 🔸 | 🔸 | Client: **`client-editable`** (FR-3.9a) |
| 7.5 | Change task status | ✅ | 🔸 | ✅ | 🔸 | 🔸 | Client: **`client-editable`** (FR-3.9a) |
| 7.6 | Assign a task | ✅ | 🔸 | ✅ | 🔸 | 🔸 | Client: **`client-editable`**, and the assignee must be a user in their own company (FR-3.9, FR-3.9a) |
| 7.6a | Soft-delete a task | ✅ | 🔸 | ✅ | 🔸 | 🔸 | Client: **tasks they created only** — narrower than `client-editable`, because deleting work a fractional assigned is not a client's call |
| 7.7 | Set `is_client_visible` | ✅ | 🔸 | ✅ | ❌ | ❌ | A client cannot hide work from their own company |
| 7.8 | Set `client_owner_contact_id` | ✅ | 🔸 | ✅ | 🔸 | 🔸 | Client: contacts at own company |
| 7.9 | Post an **internal** comment | ✅ | 🔸 | ✅ | ❌ | ❌ | Default for tenant users (FR-3.12a) |
| 7.10 | Post a **shared** comment | ✅ | 🔸 | ✅ | ✅ | ✅ | The only kind a client can create or see |
| 7.11 | Read internal comments | ✅ | 🔸 | ✅ | ❌ | ❌ | Must be absent from the API response, not merely hidden (AC-3.4) |
| 7.12 | Add / remove stakeholders | ✅ | 🔸 | ✅ | ❌ | ❌ | Who gets emailed is the fractional's call |
| 7.13 | Set a stakeholder's cadence | ✅ | 🔸 | ✅ | 🔸 | 🔸 | **Client: only their own**, via the signed token or the portal (FR-3.33a) |
| 7.14 | Set a **status override** on a goal / project | ✅ | 🔸 | ✅ | ❌ | ❌ | FR-3.10 |
| 7.15 | View the on-demand progress report | ✅ | 🔸 | ✅ | ✅ | ✅ | Requires a login; no email, no approval (FR-3.38) |

## 8. Digests — the highest-consequence rows in this document

| # | Action | FF | CF | VA | FCC | ECC | Notes |
|---|---|---|---|---|---|---|---|
| 8.1 | View the digest approval screen | ✅ | 🔸 | ✅ | — | — | A VA may read and prepare |
| 8.2 | Edit a pending digest's content | ✅ | 🔸 | ✅ | — | — | Preparation is the VA's job |
| 8.3 | **Approve / send a digest** | ✅ | 🔸 | ❌ | — | — | **403 for VA** (AC-3.18). CF: `assigned` only |
| 8.4 | Skip a pending digest | ✅ | 🔸 | ❌ | — | — | Skipping suppresses a client email; a send decision either way |
| 8.5 | Regenerate a stale digest | ✅ | 🔸 | ✅ | — | — | Rebuilds content; sends nothing (FR-3.30a) |
| 8.6 | Approve a digest for an **unassigned** company | ❌ | ❌ | ❌ | — | — | CF gets 403; FF is never unassigned |
| 8.7 | Receive a digest | 🔸 | 🔸 | 🔸 | 🔸 | 🔸 | **Scope is being a stakeholder Contact — not a role, and not a login** (FR-3.20) |
| 8.8 | Change own cadence via the emailed link | 🔸 | 🔸 | 🔸 | 🔸 | 🔸 | Signed `stakeholder_token`; **grants that one capability and nothing else** (FR-3.33a) |

> **Row 8.7 is the reason `stakeholder` points at a Contact.** A client CFO who has never signed in is a first-class digest recipient. Role does not gate delivery; being a stakeholder does.

## 9. Portal access and seats

| # | Action | FF | CF | VA | FCC | ECC | Notes |
|---|---|---|---|---|---|---|---|
| 9.1 | Grant portal access to a contact | ✅ | 🔸 | ❌ | ❌ | ❌ | CF: `assigned`. **VA 403** (FR-3.33c) |
| 9.2 | Choose FCC vs ECC on grant | ✅ | 🔸 | ❌ | ❌ | ❌ | Defaults to FCC for `primary_contact` |
| 9.3 | Revoke portal access | ✅ | 🔸 | ❌ | ❌ | ❌ | Frees the seat, kills sessions and outstanding links (FR-3.33g) |
| 9.4 | Manage users within their own company | — | — | — | ❌ | ❌ | **V1** (`CLAUDE.md`). The one capability that will separate FCC from ECC |
| 9.5 | See how many seats are in use | ✅ | 🔸 | ❌ | ❌ | ❌ | |

## 10. Module 4 — Strategy session

| # | Action | FF | CF | VA | FCC | ECC | Notes |
|---|---|---|---|---|---|---|---|
| 10.1 | Edit the tenant's template | ✅ | ❌ | ❌ | — | — | FR-4.4 |
| 10.2 | Create / schedule a session | ✅ | 🔸 | ✅ | — | — | CF: their own prospects |
| 10.3 | Send the pre-call invite | ✅ | 🔸 | **✅** | — | — | H7a — see row 5.5 |
| 10.4 | Run the live session view | ✅ | 🔸 | ❌ | — | — | |
| 10.5 | Trigger a Claude draft run | ✅ | 🔸 | ❌ | — | — | Costs money against the tenant key; writes an `ai_call` |
| 10.6 | Accept / edit / discard map rows | ✅ | 🔸 | ❌ | — | — | R6 — the fractional's judgement |
| 10.7 | View sections 1–8 of a session | ✅ | 🔸 | ✅ | — | — | |
| 10.8 | **View §9 investment range and reaction** | ✅ | 🔸 | ❌ | — | — | **`is_financial` questions. `CLAUDE.md`: VA has no financials.** Must be absent from the API response (AC-4.13) |
| 10.9 | Generate the PDF | ✅ | 🔸 | ✅ | — | — | Generating is not sending |
| 10.10 | Toggle a PDF inclusion flag | ✅ | 🔸 | ❌ | — | — | Each toggle exposes private content (FR-4.24) |
| 10.11 | **Send the PDF to the prospect** | ✅ | 🔸 | ❌ | — | — | R8, direct-to-`sent` on the click |
| 10.12 | Convert a session to goals / projects | ✅ | 🔸 | ❌ | — | — | R9; also fires the client invariant |
| 10.13 | Complete the pre-call form | — | — | — | — | — | **Public tokenised page. The prospect has no role at all** (FR-4.6) |

## 11. Module 5 — Meeting ingestion

| # | Action | FF | CF | VA | FCC | ECC | Notes |
|---|---|---|---|---|---|---|---|
| 11.1 | View the review queue | ✅ | 🔸 | ✅ | ❌ | ❌ | **CF: `proposal-scope`.** FF and VA see every proposal |
| 11.2 | Trigger "Sync now" | ✅ | 🔸 | ✅ | ❌ | ❌ | CF: `proposal-scope` |
| 11.3 | Approve a participant (create / link a contact) | ✅ | 🔸 | ✅ | ❌ | ❌ | CF: `proposal-scope`. Creates a record; sends nothing |
| 11.4 | Confirm a participant's contact type | ✅ | 🔸 | ✅ | ❌ | ❌ | Confirming `referral partner` **queues** onboarding (FR-5.9b) |
| 11.5 | Approve action items / deliverables | ✅ | 🔸 | ✅ | ❌ | ❌ | R11, R12 |
| 11.6 | Accept / edit / discard the meeting summary | ✅ | 🔸 | ✅ | ❌ | ❌ | R11a |
| 11.7 | Reject a proposal item | ✅ | 🔸 | ✅ | ❌ | ❌ | |
| 11.8 | Re-parse a source file | ✅ | 🔸 | ✅ | ❌ | ❌ | Writes an `ai_call` |
| 11.9 | View meetings on a contact timeline | ✅ | 🔸 | ✅ | ❌ | ❌ | Client users see tasks, never meeting records |

> **The VA's broad rights here are deliberate.** Clearing this queue is the VA's job, and every action in it creates records rather than sending mail — the send is a separate, gated step (FR-5.19, row 5.3).
>
> **Why `proposal-scope` is not simply "all tenant staff".** A meeting proposal usually *precedes* any company link — matching participants is the point of the queue — so an unmatched proposal has no company to scope by. The tempting fix is to show unmatched proposals to everyone. That is wrong: **a CF is not assigned to the FF's prospects, and must not read the FF's prospect meeting notes before anyone has decided they should.** So the scope has a second limb — **the CF owns the source Drive file**, i.e. it was their own meeting — which covers the legitimate case without opening the FF's pipeline. A proposal that is neither matched to an assigned company nor from the CF's own file is visible to FF and VA only, which is the correct default for an unreviewed document.

## 12. Module 6 — Communication

| # | Action | FF | CF | VA | FCC | ECC | Notes |
|---|---|---|---|---|---|---|---|
| 12.1 | View a contact's email history | ✅ | 🔸 | ✅ | ❌ | ❌ | |
| 12.2 | View the unmatched inbound queue | ✅ | 🔸 | ✅ | ❌ | ❌ | |
| 12.3 | File an unmatched message to a contact | ✅ | 🔸 | ✅ | ❌ | ❌ | Filing creates no outbound mail |
| 12.4 | Send a reply | ✅ | 🔸 | ❌ | ❌ | ❌ | VA drafts only (row 5.6) |
| 12.5 | Access any communication surface | — | — | — | ❌ | ❌ | Includes internal correspondence *about* them |

## 13. Financial boundary (V1 modules, recorded now)

Beta ships no financial module. These rows exist so the role-boundary suite has a failing target from day one: **an endpoint that does not exist yet must still 403 for a VA when it arrives**, rather than being remembered later.

| # | Action | FF | CF | VA | FCC | ECC | Notes |
|---|---|---|---|---|---|---|---|
| 13.1 | View P&L / balance sheet | ✅ | ❌ | ❌ | ❌ | ❌ | |
| 13.2 | View fee splits on assigned clients | ✅ | 🔸 | ❌ | ❌ | ❌ | `CLAUDE.md`: CF financials limited to assigned clients |
| 13.3 | View fee splits on **unassigned** clients | ✅ | ❌ | ❌ | ❌ | ❌ | |
| 13.4 | Invoicing, product billing | ✅ | ❌ | ❌ | ❌ | ❌ | |
| 13.5 | Any financial endpoint | ✅ | 🔸 | **❌** | ❌ | ❌ | **The non-negotiable VA test family** (`CLAUDE.md`) |

---

## 14. The two mandatory test families, derived from this table

Per `CLAUDE.md` these are non-negotiable, and per assumption B3 they are a registry, not hand-written per module.

### 14.1 Tenant isolation

For **every** model in `02_data_model.md` §1–§8: create a row in tenant A and a row in tenant B, then assert that a user of tenant A gets **404** on read, update, and delete of B's row — through the API, through search, and through any timeline or aggregate view.

**The meta-test:** enumerate every concrete model inheriting `TenantScopedModel`; fail if any is absent from the registry. This is what stops the matrix and the code drifting apart.

### 14.2 Role boundaries

Every row above becomes a parametrised case: `(action, role, scope_fixture) → expected`.

Five cases carry the most weight and are called out so they are never merely inherited from a loop:

1. **VA cannot approve or send** — rows 5.3, 8.3, 10.11, 12.4. Expect **403**, and assert the dev outbox is empty afterwards.
2. **VA cannot reach financials** — row 13.5, including §9 investment fields (row 10.8) absent from the response body, not merely hidden in the UI.
3. **ECC cannot reach anything outside their company** — rows 7.1–7.15 with a second client company in the *same* tenant. Expect **404**, never 403.
4. **CF `assigned` scope is real** — every 🔸 CF row tested both in and out of assignment, with the assignment removed mid-test to confirm it takes effect on the next request (AC-1.13).
5. **PIN gating is not a role** — row 6.4 tested as FF *without* the PIN, expecting the body to be absent (AC-2.3).

### 14.3 Two assertions every send-related case must make

Because the review-queue rule is the product's central promise, a 403 alone is not a sufficient assertion:

- **The dev outbox is empty** after every denied send attempt.
- **No `outbox_message` row moved to `sent`**, and no `digest.state` advanced.

---

## 15. Review outcome

All four flagged rows ruled on; seven changes applied.

**Rulings:**

- **15.1 (row 3.13) — approved as written.** VA edits template body copy; FF creates and deletes templates.
- **15.2 (row 4.14) — approved.** The VA commits and rolls back imports, because they are the one running them and it is reversible (FR-1.31).
- **15.3 (row 4.5) — changed to VA ✅, audited.** Your reasoning is better than mine: I restricted merge on the grounds that it is not cleanly reversible, but the practical effect was to route the cleanup half of the VA's own import work back to the FF. CF stays ❌.
- **15.4 (rows 11.x) — kept scoped, with a second limb added.** `proposal-scope` is now "participant matched to an assigned company **or** the CF owns the source Drive file." This required a data-model change: `meeting_source_file` now records `drive_file_owner_email` at ingestion.

**Changes:**

| # | Change | Rows |
|---|---|---|
| 1 | Pipeline stages split out as FF-only; contact types and service categories stay VA ✅ | 3.14, 3.15 |
| 1a | **Pipeline management became per pipeline** once the owner's real CRM turned out to run two (sales, and a nurture pipeline for referral partners). FF-only to change, readable by all tenant staff | 3.14a, 3.15, 3.15a |
| 2 | VA soft-deletes contacts and companies; restore row added | 4.4, 4.4a |
| 3 | Tenant staff management rows added, FF-only | 3.16, 3.17, 3.18 |
| 4 | AI usage and cost visibility, FF-only — spend is financial | 3.19 |
| 5 | Soft-delete a task, with clients limited to tasks they created | 7.6a |
| 6 | Goal and Project creation split; clients may create projects | 7.2, 7.2a |
| 7 | `client-editable` defined once and cited in three rows | 7.4, 7.5, 7.6 |

**On change 7.** Rows 7.4–7.6 previously overlapped in a way that could not be tested: "tasks they created or are assigned" and "assign other users' tasks" are not the same set. **FR-3.9a** now states one rule — a client user may edit, restatus, and reassign any client-visible task in their company that is **assigned to a client-side user or created by a client user**; a task assigned to a *tenant* user is read-only to clients apart from shared comments. Row 7.6a is deliberately narrower still: deleting work a fractional assigned is not a client's call.

**Documents updated by these changes:** `01_prd.md` (FR-3.9a, FR-3.35a, FR-0.8, FR-0.9, plus four ACs), `02_data_model.md` (`meeting_source_file.drive_file_owner_email`, `project.created_by_client`, staff-revocation cascade).
