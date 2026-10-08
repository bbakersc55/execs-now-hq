# 03 — Access Matrix: Beta

> **Vocabulary (P1, 2026-10-02).** A *practice* is what the code calls a tenant. Roles: practice owner (`FF`), associate (`CF`), assistant (`VA`), client owner (`FCC`), client team member (`ECC`). The codes stay in code and data.

**Phase 0 · Execs NOW HQ · for owner review**
**Built on:** `CLAUDE.md` (role definitions), `00_assumptions.md`, `01_prd.md`, `02_data_model.md`.

> **This document is the source of truth for permission tests.** The role-boundary suite (assumption B3) is generated from these rows: every row becomes a parametrised test asserting the expected result for all five roles. A row without a test, or a test without a row, fails the meta-test.

---

## 1. How to read the matrix

**Roles** are exactly the five in `CLAUDE.md`: **Practice owner** (`FF`, the practice's founder) · **Associate** (`CF`, a contractor or employee fractional) · **Assistant** (`VA`) · **Client owner** (`FCC`, the client company's founder) · **Client team member** (`ECC`, the client company's employees).

**Cell values:**

| Value | Meaning | Expected HTTP |
|---|---|---|
| **✅** | Allowed, unconditionally within the practice | 2xx |
| **🔸** | Allowed, **scoped** — the scope is named in the row's Notes | 2xx for in-scope, **404** out of scope |
| **❌** | Denied | **403** |
| **—** | Not applicable: no such surface exists for this role | 404 (route absent) |

**Two rules about status codes**, applied consistently and worth stating once:

1. **Out-of-scope reads return 404, not 403.** A 403 confirms the row exists. An associate probing for a client company they are not assigned to, or a client team member probing another company's task, must not be able to distinguish "exists but forbidden" from "does not exist." **Cross-practice access always returns 404.**
2. **In-practice, in-scope but role-forbidden actions return 403.** An assistant hitting the digest-approve endpoint gets a 403: the row exists, the assistant can see it, they simply may not perform that verb. Hiding that would make the product confusing for no security gain.

**Scope keys used in the Notes column:**

- `assigned` — associate must hold a live `client_assignment` for the client company (FR-1.9a).
- `owned` — the contact's `owner_id` is this user.
- `own-work` — the goal, project or task's `owner_id` or `assignee_id` is this user, **whatever company it belongs to, and including none**. An associate's own work does not stop being theirs because it sits outside an assignment. *(Added 2026-09-17.)*
- `own-company` — the client user's `membership.client_company_id` matches the row's `client_company_id` (FR-0.2).
- `client-visible` — additionally requires `task.is_client_visible = true` and, for comments, `visibility = 'shared'`.
- `client-editable` — a client-visible task in the user's own company that is **assigned to a client-side user or was created by a client user** (FR-3.9a). Tasks assigned to a practice user are read-only to clients apart from shared comments.
- `proposal-scope` — for an associate: a meeting proposal where **any participant is matched to a company they are assigned to**, *or* where the **source Drive file is owned by that associate** (their own meeting). Practice owner and assistant see every proposal.

**Client owner and client team member columns are identical in every row of this document.** That is the deliberate outcome of the PRD review: user management is V1, and it is the only thing that will separate them. The columns are kept **separate rather than merged** so that when client owner gains capabilities in V1 it is a data change to this table and to test parameters — not a schema migration and not a re-derivation of the whole matrix.

---

## 2. Cross-cutting: tenancy and identity

| # | Action | Practice owner | Associate | Assistant | Client owner | Client team member | Notes |
|---|---|---|---|---|---|---|---|
| 2.1 | Read any row belonging to another practice | ❌ | ❌ | ❌ | ❌ | ❌ | **404 always.** The non-negotiable rule (`CLAUDE.md`); enforced by the fail-closed manager (B1), not by views |
| 2.2 | Sign in with Google | ✅ | ✅ | ✅ | — | — | Invite-only; membership must pre-exist (C1) |
| 2.3 | Sign in by magic link | — | — | — | ✅ | ✅ | Client users have no other method (C3, C4) |
| 2.4 | Belong to more than one practice | ❌ | ❌ | ❌ | ❌ | ❌ | One membership per user in Beta (B4) |
| 2.5 | View own profile / timezone | ✅ | ✅ | ✅ | ✅ | ✅ | |
| 2.6 | View the audit log | ✅ | ❌ | ❌ | ❌ | ❌ | |

## 3. Practice settings

| # | Action | Practice owner | Associate | Assistant | Client owner | Client team member | Notes |
|---|---|---|---|---|---|---|---|
| 3.1 | View practice settings | ✅ | 🔸 | ❌ | — | — | Associate sees non-financial, non-secret settings only |
| 3.2 | Edit practice settings | ✅ | ❌ | ❌ | — | — | `CLAUDE.md`: Assistant has no settings access |
| 3.3 | Set / rotate the Anthropic API key | ✅ | ❌ | ❌ | — | — | Write-only field; **no role can ever read it** (E1.3) |
| 3.4 | Read the Anthropic API key | ❌ | ❌ | ❌ | ❌ | ❌ | **Denied to everyone including practice owner** — there is no read path in the product |
| 3.5 | Connect the Google Drive folder | ✅ | ❌ | ❌ | — | — | |
| 3.6 | Edit the referral blurb | ✅ | ❌ | ❌ | — | — | FR-1.21a |
| 3.7 | Upload / replace the marketing flyer | ✅ | ❌ | ❌ | — | — | FR-1.23b |
| 3.8 | Toggle `hold_all_digests` | ✅ | ❌ | ❌ | — | — | The master safety switch (FR-3.25) |
| 3.9 | Toggle `digest_ai_prose` on a client company | ✅ | 🔸 | ❌ | — | — | Associate: `assigned` |
| 3.10 | Set digest send day / hour | ✅ | ❌ | ❌ | — | — | |
| 3.11 | Set `audio_retention_days` | ✅ | ❌ | ❌ | — | — | |
| 3.12 | Manage stage automation rules | ✅ | ❌ | ❌ | — | — | |
| 3.13 | Manage email templates | ✅ | ❌ | 🔸 | — | — | Assistant may edit body copy, not create or delete rules |
| 3.14 | Manage contact types and service categories | ✅ | ❌ | ✅ | — | — | CRM hygiene is the assistant's job (FR-1.9d) |
| 3.14a | **Manage pipelines** (create, rename, remove) | ✅ | ❌ | ❌ | — | — | **Practice owner only, per pipeline.** A practice runs several — a sales pipeline and a nurture pipeline for referral partners (FR-1.6). Adding or removing one changes how the practice works |
| 3.15 | **Manage the stages within a pipeline** (rename, reorder, add, remove) | ✅ | ❌ | ❌ | — | — | **Practice owner only, per pipeline.** Renaming is safe by design — behavior keys on the stage's `semantic`, never its label — but adding and removing stages is a workflow change. A sales-kind pipeline must keep **exactly one `won` stage**; removing the last one is refused, because without it nothing can become a client (FR-1.6a) |
| 3.15a | **Read pipelines and their stages** | ✅ | ✅ | ✅ | ❌ | ❌ | Every practice user works the board daily. Client users have no CRM surface at all (4.18) |
| 3.16 | Invite an associate or assistant | ✅ | ❌ | ❌ | — | — | No self-serve signup (C1) |
| 3.17 | Change a member's role | ✅ | ❌ | ❌ | — | — | |
| 3.18 | Remove / revoke a practice staff member | ✅ | ❌ | ❌ | — | — | Kills sessions; **for an associate also ends every `client_assignment` and disconnects Gmail** (FR-0.8c) |
| 3.19 | **View AI usage and cost (`ai_call`)** | ✅ | ❌ | ❌ | — | — | **Spend is financial** — `CLAUDE.md` gives the assistant no financials, and an associate no practice-wide spend |

## 4. Module 1 — Contacts & pipeline

| # | Action | Practice owner | Associate | Assistant | Client owner | Client team member | Notes |
|---|---|---|---|---|---|---|---|
| 4.1 | List / search contacts | ✅ | 🔸 | ✅ | — | — | Associate: `assigned` companies + `owned` contacts (FR-1.9c). **Assistant sees all** (FR-1.9d) |
| 4.2 | View a contact | ✅ | 🔸 | ✅ | — | — | |
| 4.3 | Create / edit a contact | ✅ | 🔸 | ✅ | — | — | |
| 4.4 | Delete (soft) a contact or company | ✅ | 🔸 | ✅ | — | — | Soft delete (D2) is exactly what makes this safe to delegate |
| 4.4a | **Restore a soft-deleted record** | ✅ | 🔸 | ✅ | — | — | Associate: `assigned`/`owned` |
| 4.5 | **Merge two contacts** | ✅ | ❌ | **✅** | — | — | **Assistant ✅, audited.** Post-import dedupe is the core of CRM hygiene and the assistant runs the imports; a merge the assistant cannot perform just sends the practice owner a queue of the cleanup the assistant was hired to do. Associate ❌ |
| 4.6 | Edit `contact.background` | ✅ | 🔸 | ✅ | — | — | |
| 4.7 | View / edit companies | ✅ | 🔸 | ✅ | — | — | |
| 4.8 | Set `company.primary_contact` | ✅ | 🔸 | ❌ | — | — | Determines the client owner default (FR-3.33d) |
| 4.9 | Change a contact's pipeline stage | ✅ | 🔸 | ✅ | — | — | Triggers the client invariant (FR-1.6a) |
| 4.10 | Unset contact type `client` / `is_client_company` | ✅ | ❌ | ❌ | — | — | Deliberate manual act (FR-1.6a.2) |
| 4.11 | Create / remove a `client_assignment` | ✅ | ❌ | ❌ | — | — | **Practice owner only** (FR-1.9b). The row every `assigned` scope depends on |
| 4.12 | Set `company.seat_count` | ✅ | ❌ | ❌ | — | — | FR-3.33f |
| 4.13 | Run a CSV import dry run | ✅ | ❌ | ✅ | — | — | |
| 4.14 | Commit a CSV import | ✅ | ❌ | ✅ | — | — | Assistant commits and may roll back (Module 1 assistant story) |
| 4.15 | Roll back an import batch | ✅ | ❌ | ✅ | — | — | |
| 4.16 | Set referral cadence / fee terms | ✅ | 🔸 | ✅ | — | — | Fee **terms** are free text about a partnership, not practice financials |
| 4.17 | Search vendors by service category | ✅ | ✅ | ✅ | — | — | |
| 4.18 | Access any CRM surface | — | — | — | ❌ | ❌ | **Permanent boundary, not a Beta limitation** (Module 1 stories) |

## 5. The Outbox

| # | Action | Practice owner | Associate | Assistant | Client owner | Client team member | Notes |
|---|---|---|---|---|---|---|---|
| 5.1 | View the Outbox | ✅ | 🔸 | ✅ | — | — | Associate: messages to contacts on `assigned` companies |
| 5.2 | Create / edit a draft | ✅ | 🔸 | ✅ | — | — | |
| 5.3 | **Approve and send a draft** | ✅ | 🔸 | ❌ | — | — | **The H7 boundary.** assistant gets 403 (FR-1.19) |
| 5.4 | Reject a draft | ✅ | 🔸 | ✅ | — | — | Rejecting sends nothing; safe for an assistant |
| 5.5 | Send a `precall_invite` directly | ✅ | 🔸 | **✅** | — | — | **The single assistant send exception** (H7a, FR-4.6a): template-only, non-AI, practice address |
| 5.6 | Send a `manual` email | ✅ | 🔸 | ❌ | — | — | Practice owner/associate direct-to-`sent` via own Gmail; **an assistant's `manual` becomes a `pending_approval` draft** (FR-1.19a) |
| 5.7 | Connect Gmail (Tier 1, `gmail.send`) | ✅ | ✅ | ❌ | — | — | H7 |
| 5.8 | Connect Gmail Tier 2 (`gmail.readonly`) | ✅ | ✅ | ❌ | — | — | Opt-in; restricted scope (FR-6.3g) |
| 5.9 | View the complete send log | ✅ | 🔸 | ✅ | — | — | The Outbox is also the log (FR-1.15) |

## 6. Module 2 — Notes

| # | Action | Practice owner | Associate | Assistant | Client owner | Client team member | Notes |
|---|---|---|---|---|---|---|---|
| 6.1 | Create a note | ✅ | ✅ | ✅ | — | — | |
| 6.2 | View an **unlocked** note | ✅ | 🔸 | ✅ | — | — | Associate: notes on `assigned`/`owned` records |
| 6.3 | View a **PIN-locked** note's stub | ✅ | 🔸 | ✅ | — | — | Title only — and **"Locked note"** if the title was auto-derived (FR-2.11b) |
| 6.4 | View a PIN-locked note's **body** | 🔸 | 🔸 | 🔸 | — | — | **Scope is the PIN, not the role.** Anyone with the PIN, nobody without — including the practice owner |
| 6.5 | Set / change a PIN | ✅ | ✅ | ✅ | — | — | Requires a typed title first (FR-2.11a) |
| 6.6 | **Reset a PIN** | ✅ | ❌ | ❌ | — | — | **Practice owner only, by emailed link, clears rather than reveals** (`CLAUDE.md`, FR-2.12) |
| 6.7 | Record audio / transcribe | ✅ | ✅ | ✅ | — | — | Consent reminder shown (FR-2.15) |
| 6.8 | Accept / edit / discard a Claude summary | ✅ | ✅ | ✅ | — | — | The note's author reviews (R3); the practice owner may too. Another associate or assistant gets 403. (Retention and the Anthropic key are rows 3.11 and 3.3) |
| 6.9 | Access any note | — | — | — | ❌ | ❌ | **No client-visible note type exists in Beta** |

> **Row 6.4 is the only row in this document whose scope is not a role or an assignment.** It is worth stating plainly, as FR-2.13 does: a PIN screens a note from other users of the app. It does not protect it from the practice owner (who can reset), from a database dump, or from the nightly backup.

## 7. Module 3 — Task engine

| # | Action | Practice owner | Associate | Assistant | Client owner | Client team member | Notes |
|---|---|---|---|---|---|---|---|
| 7.1 | View goals / projects / tasks | ✅ | 🔸 | ✅ | 🔸 | 🔸 | Associate: `assigned` **or `own-work`** — work at their assigned client companies, plus work they own or are assigned **regardless of company**, the practice's internal work included. Goals and projects carry no assignee, so for those `own-work` means owner. A task reaches an associate by a fourth path as well: the contact it hangs off, if that contact is in their FR-1.9c universe (Phase 1 stage-rule tasks land this way). Client: `own-company` + `client-visible` |
| 7.2 | Create a **goal** | ✅ | 🔸 | ✅ | ❌ | ❌ | Strategy is the fractional's. *(2026-10-07, owner)* A client owner may **propose** a goal; it is a goal only once the practice owner or an assigned associate accepts it (`/api/goal-proposals/`). A client owner or team member may likewise **propose** an order for their company's goals; the practice owner or an assigned associate sets it (`/api/goal-order/`). An assistant decides neither |
| 7.2a | Create a **project** | ✅ | 🔸 | ✅ | 🔸 | 🔸 | Client: `own-company`. A client using the portal as their task tool needs a way to group their own work; a client-created project has no parent goal, or one of their own company's goals (FR-3.35a, changed 2026-10-07; it was none by definition) |
| 7.3 | Create a task | ✅ | 🔸 | ✅ | 🔸 | 🔸 | Client: `own-company`. **No review queue** (FR-3.36) |
| 7.4 | Edit a task | ✅ | 🔸 | ✅ | 🔸 | 🔸 | Client: **`client-editable`** (FR-3.9a) |
| 7.5 | Change task status | ✅ | 🔸 | ✅ | 🔸 | 🔸 | Client: **`client-editable`** (FR-3.9a) |
| 7.6 | Assign a task | ✅ | 🔸 | ✅ | 🔸 | 🔸 | Client: **`client-editable`**, and the assignee must be a user in their own company (FR-3.9, FR-3.9a) |
| 7.6a | Soft-delete a task | ✅ | 🔸 | ✅ | 🔸 | 🔸 | Client: **tasks they created only** — narrower than `client-editable`, because deleting work a fractional assigned is not a client's call |
| 7.7 | Set `is_client_visible` | ✅ | 🔸 | ✅ | ❌ | ❌ | A client cannot hide work from their own company |
| 7.8 | Set `client_owner_contact_id` | ✅ | 🔸 | ✅ | 🔸 | 🔸 | Client: contacts at own company |
| 7.9 | Post an **internal** comment | ✅ | 🔸 | ✅ | ❌ | ❌ | Default for practice users (FR-3.12a) |
| 7.10 | Post a **shared** comment | ✅ | 🔸 | ✅ | ✅ | ✅ | The only kind a client can create or see |
| 7.11 | Read internal comments | ✅ | 🔸 | ✅ | ❌ | ❌ | Must be absent from the API response, not merely hidden (AC-3.4) |
| 7.12 | Add / remove stakeholders | ✅ | 🔸 | ✅ | ❌ | ❌ | Who gets emailed is the fractional's call |
| 7.13 | Set a stakeholder's cadence | ✅ | 🔸 | ✅ | 🔸 | 🔸 | **Client: only their own**, via the signed token or the portal (FR-3.33a) |
| 7.14 | Set a **status override** on a goal / project | ✅ | 🔸 | ✅ | ❌ | ❌ | FR-3.10 |
| 7.15 | View the client's report | ✅ | 🔸 | ✅ | ✅ | ✅ | **Reworded 2026-09-21.** FR-3.38's on-demand progress report is replaced by the **client value report (Module 4B)**; the row survives the replacement because its rule does — **requires a login, no email, no approval**. The surface and its scopes are now §10A, rows 10A.1–10A.2 |
| 7.16 | **View the activity feed** | ✅ | 🔸 | ✅ | ❌ | ❌ | **Reversed 2026-09-16** (FR-3.41a). It was the client's log; it is now the practice's, across every account. Associate: `assigned` companies **plus contacts they own** — the FR-1.9c universe. A client is refused the endpoint and has no nav entry; their window into the work is the value report (Module 4B) |
| 7.17 | Edit or delete an activity-feed entry | ❌ | ❌ | ❌ | ❌ | ❌ | **Nobody.** The endpoint has no write methods, and `apps/work/activity.py` has no function that writes |

> **Row 7.1 was amended on 2026-09-17, and the code was not.** The row read "Associate: `assigned`" from Phase 0 onward; `work/permissions.py` has always also admitted work an associate owns or is assigned, whatever company it sits on. **Owner ruling: the code is right and the row was wrong.** A contractor fractional's own work is theirs — an internal task the practice hands them, or a task on an account they are not the assigned lead for, does not become invisible to the person doing it. The narrower reading would have been a real bug hiding behind a correct-looking document: work assigned to an associate that they could not see. The discrepancy surfaced on 2026-09-17 while writing the company filter's role tests, which is the first thing that had asked the question of internal work.

> **Row 7.16 is deliberately narrower than 7.1**, and the two should not be collapsed. The activity feed is the FR-1.9c contact universe — assigned companies plus contacts they own — because it is a feed *about accounts*. Row 7.1 is about work, and work has an owner and an assignee that a contact does not.


## 8. Digests — the highest-consequence rows in this document

| # | Action | Practice owner | Associate | Assistant | Client owner | Client team member | Notes |
|---|---|---|---|---|---|---|---|
| 8.1 | View the digest approval screen | ✅ | 🔸 | ✅ | — | — | An assistant may read and prepare |
| 8.2 | Edit a pending digest's content | ✅ | 🔸 | ✅ | — | — | Preparation is the assistant's job |
| 8.3 | **Approve / send a digest** | ✅ | 🔸 | ❌ | — | — | **403 for assistant** (AC-3.18). Associate: `assigned` only |
| 8.4 | Skip a pending digest | ✅ | 🔸 | ❌ | — | — | Skipping suppresses a client email; a send decision either way |
| 8.5 | Regenerate a stale digest | ✅ | 🔸 | ✅ | — | — | Rebuilds content; sends nothing (FR-3.30a) |
| 8.6 | Approve a digest for an **unassigned** company | ❌ | ❌ | ❌ | — | — | Associate gets 403; practice owner is never unassigned |
| 8.7 | Receive a digest | 🔸 | 🔸 | 🔸 | 🔸 | 🔸 | **Scope is being a stakeholder Contact — not a role, and not a login** (FR-3.20) |
| 8.8 | Change own cadence via the emailed link | 🔸 | 🔸 | 🔸 | 🔸 | 🔸 | Signed `stakeholder_token`; **grants that one capability and nothing else** (FR-3.33a) |

> **Row 8.7 is the reason `stakeholder` points at a Contact.** A client CFO who has never signed in is a first-class digest recipient. Role does not gate delivery; being a stakeholder does.

## 9. Portal access and seats

| # | Action | Practice owner | Associate | Assistant | Client owner | Client team member | Notes |
|---|---|---|---|---|---|---|---|
| 9.1 | Grant portal access to a contact | ✅ | 🔸 | ❌ | ❌ | ❌ | Associate: `assigned`. **Assistant 403** (FR-3.33c) |
| 9.2 | Choose client owner vs client team member on grant | ✅ | 🔸 | ❌ | ❌ | ❌ | Defaults to client owner for `primary_contact` |
| 9.2a | Change an existing portal user's client owner/client team member role | ✅ | 🔸 | ❌ | ❌ | ❌ | Associate: `assigned`. Audited. **Client owner → client team member ends sessions and outstanding links** as revoke does; access continues. Changing `primary_contact` (4.8) never changes an existing role |
| 9.3 | Revoke portal access | ✅ | 🔸 | ❌ | ❌ | ❌ | Frees the seat, kills sessions and outstanding links (FR-3.33g) |
| 9.4 | Manage users within their own company | — | — | — | ❌ | ❌ | **V1** (`CLAUDE.md`). The one capability that will separate client owner from client team member |
| 9.5 | See how many seats are in use | ✅ | 🔸 | ❌ | ❌ | ❌ | |
| 9.6 | **Act as another user** | ✅ | 🔸 | ❌ | 🔸 | ❌ | FR-3.42. Practice owner: any client user at a client company. Associate: `assigned`. Client owner: another user in their own company. **Assistant 403** |
| 9.7 | Stop acting as | ✅ | ✅ | — | ✅ | — | Whoever is acting; explicit, audited. Also ends, audited as `act_as.ended` with its reason, when no longer permitted or on sign-out |
| 9.8 | Send any email while acting as | ❌ | ❌ | — | ❌ | — | Suppressed and logged (`suppressed` in the Outbox, `email.suppressed` audited); acting updates never reach a digest or notice |
| 9.9 | Act as across a company or practice, as practice staff, or as oneself | ❌ | ❌ | ❌ | ❌ | ❌ | 404 |
| 9.10 | Act as while already acting (nested) | ❌ | ❌ | — | ❌ | — | 409 |

## 10. Module 4 — Strategy session

| # | Action | Practice owner | Associate | Assistant | Client owner | Client team member | Notes |
|---|---|---|---|---|---|---|---|
| 10.1 | Edit the practice's template | ✅ | ❌ | ❌ | — | — | FR-4.4 |
| 10.2 | Create / schedule a session | ✅ | 🔸 | ✅ | — | — | Associate: their own prospects |
| 10.3 | Send the pre-call invite | ✅ | 🔸 | **✅** | — | — | H7a — see row 5.5 |
| 10.3a | **Email the pre-call questions** (from their own address) | ✅ | 🔸 | ❌ | — | — | **Assistant 403** — the exception in 10.3 is H7a's, and it is for a template-only send. This one carries an intro a person wrote and goes from their address (FR-4.10c) |
| 10.3b | **Prepare for a session** (Claude, with web search) | ✅ | 🔸 | ❌ | — | — | FR-4.21a. Costs money against the practice key and searches the web. **Assistant 403** |
| 10.3c | **Read the prep brief** | ✅ | 🔸 | ❌ | — | — | **Absent from an assistant's payload**, not hidden in it — the §9 standard (FR-4.21e) |
| 10.4 | Run the live session view | ✅ | 🔸 | ❌ | — | — | |
| 10.5 | Trigger a Claude draft run | ✅ | 🔸 | ❌ | — | — | Costs money against the practice key; writes an `ai_call` |
| 10.6 | Accept / edit / discard map rows | ✅ | 🔸 | ❌ | — | — | R6 — the fractional's judgment |
| 10.6a | Accept / edit / discard **§8's pros and cons** | ✅ | 🔸 | ❌ | — | — | R6a — the same judgment as 10.6, on the decision page. **Only an accepted note reaches the prospect's PDF** |
| 10.7 | View sections 1–8 of a session | ✅ | 🔸 | ✅ | — | — | |
| 10.8 | **View §9 investment range and reaction** | ✅ | 🔸 | ❌ | — | — | **`is_financial` questions. `CLAUDE.md`: Assistant has no financials.** Must be absent from the API response (AC-4.13) |
| 10.9 | Generate the PDF | ✅ | 🔸 | ✅ | — | — | Generating is not sending |
| 10.10 | Toggle a PDF inclusion flag | ✅ | 🔸 | ❌ | — | — | Each toggle exposes private content (FR-4.24) |
| 10.11 | **Send the PDF to the prospect** | ✅ | 🔸 | ❌ | — | — | R8, direct-to-`sent` on the click |
| 10.12 | Convert a session to goals / projects | ✅ | 🔸 | ❌ | — | — | R9; also fires the client invariant |
| 10.13 | Complete the pre-call form | — | — | — | — | — | **Public tokenised page. The prospect has no role at all** (FR-4.6) |

## 10A. Module 4B — Client value report

> **Specified 2026-09-21, from ruling 6 of the Phase 4.5 scope, and amended the same day by rulings B, E, G and H.** The line this section draws: **judging the client relationship is practice owner-and-assigned-associate; administering it is an assistant's too.** Resolving a goal and accepting a narrative are judgments. Recording a reading and exporting a PDF are not. **Client roles are read-only throughout** — the report is the one place in the product built for them to read, and there is nothing in it for them to write.

| # | Action | Practice owner | Associate | Assistant | Client owner | Client team member | Notes |
|---|---|---|---|---|---|---|---|
| 10A.1 | View a client company's value report | ✅ | 🔸 | ✅ | 🔸 | 🔸 | Associate: `assigned`. Client: `own-company`. **Requires a login** — a `stakeholder_token` does not reach it (AC-4B.21) |
| 10A.2 | Open one goal's report | ✅ | 🔸 | ✅ | 🔸 | 🔸 | Same scopes as 10A.1. Another company's goal is **404**, not 403 |
| 10A.3 | See an **internal** goal in a report | — | — | — | — | — | **No surface for anyone** (ruling 10). A goal with no client company is absent from the response, not filtered in the UI (AC-4B.3) |
| 10A.4 | Record a measurement | ✅ | 🔸 | ✅ | ❌ | ❌ | **An assistant may**: taking a reading is administration, not judgment. **A client may not** — a client typing their own numbers into the report they are being shown changes what the artifact is |
| 10A.5 | Correct or delete a measurement | ✅ | 🔸 | ✅ | ❌ | ❌ | A reading is a fact that can be wrong; correcting it moves the chart and never the headline (AC-4B.5) |
| 10A.6 | Write / update the **outcome statement** | ✅ | 🔸 | ❌ | ❌ | ❌ | **Assistant 403 — ruling H, 2026-09-21**, which ruling 6 had not reached. It is the fractional's sentence about what the goal is for, in the client's language — the nearest thing in the product to speaking for the practice |
| 10A.7 | Create / edit a standalone milestone | ✅ | 🔸 | ✅ | ❌ | ❌ | Dated beats are administration |
| 10A.8 | Mark a task as a milestone | ✅ | 🔸 | ✅ | ❌ | ❌ | **Ruling E, 2026-09-21 — only a client-visible task in the goal's own tree, never an internal one.** Follows the task's own edit rights (row 7.4) on top of that; a client-editable task does **not** carry this, because the goal's timeline is not the client's to compose |
| 10A.9 | Edit a **derived** milestone's title or dates | ❌ | ❌ | ❌ | ❌ | ❌ | **Nobody.** They belong to the task, and un-completing it clears the date (FR-4B.25). Two places to maintain one fact is what ruling 8 exists to prevent |
| 10A.10 | **Resolve a goal** | ✅ | 🔸 | ❌ | ❌ | ❌ | **Ruling 6 — assistant 403**, asserted against the API body. Associate: `assigned`. A judgment about the relationship |
| 10A.10a | See a resolution's **reason** | ✅ | 🔸 | ✅ | 🔸 | 🔸 | **Ruling G, 2026-09-21 — the client reads it.** No internal-only resolution and no visibility flag on the line: a reason the client cannot read cannot make *changed course* read as judgment (FR-4B.30a) |
| 10A.11 | Edit or delete a resolution | ❌ | ❌ | ❌ | ❌ | ❌ | **Nobody, ever** (ruling 7). Append-only: no update or delete route exists. Reversing a resolution is appending another with its own reason |
| 10A.11a | Edit or delete a **narrative version** | ❌ | ❌ | ❌ | ❌ | ❌ | **Nobody, ever** (ruling B). Each acceptance appends a dated snapshot; the living narrative is rewritten freely and **what the client was told is not** |
| 10A.12 | Trigger a narrative draft | ✅ | 🔸 | ✅ | ❌ | ❌ | Costs money against the practice key; writes an `ai_call`. An assistant may **prepare**, exactly as with a digest (row 8.2) |
| 10A.13 | **Accept / edit a narrative** | ✅ | 🔸 | ❌ | ❌ | ❌ | **Ruling 6 — assistant 403.** R9a. Accepting is publishing to the client |
| 10A.14 | Read an **unaccepted** draft | ✅ | 🔸 | ✅ | ❌ | ❌ | Must be **absent from the client's response body**, not hidden in the UI (AC-4B.15) — the AC-3.4 standard |
| 10A.15 | Export the report as a PDF | ✅ | 🔸 | ✅ | ❌ | ❌ | Generating is not sending (row 10.9's precedent). **A client does not export**: the portal is their copy, always current |
| 10A.16 | View a stored export | ✅ | 🔸 | ✅ | ❌ | ❌ | Snapshots are the practice's record of what was shown when (ruling 4) |
| 10A.17 | **Send an export to the client** | ✅ | 🔸 | ❌ | — | — | Not a new verb: it is an ordinary Outbox message with an attachment, under §5's rules. **An assistant may prepare and not approve** (row 5.4) |

> **Row 10A.6 is the one that will look inconsistent, so here is why it is not.** An assistant may record a measurement (10A.4) but not write the outcome statement. A reading is a number someone took; the outcome statement is the sentence a founder repeats to their board, and it goes out under the fractional's name. The test is not how much typing the action involves — it is whether being wrong is an administrative error or a wrong thing said to a client on the practice's behalf.

> **Rows 10A.10 and 10A.13 are the 4B analogues of row 8.3** (approving a digest), and they fail the same way: an assistant who may do them can publish a judgment about the engagement that the fractional never made. Both are asserted **against the API response body**, not by the absence of a button.

> **The client columns are read-only in every row of this section**, which is deliberate and worth stating once. FR-3.35a gives a client tasks and projects of their own precisely so the portal is a working tool; the value report is the opposite kind of artifact — the practice's account of the engagement, which a client reads and does not co-author.

## 11. Module 5 — Meeting ingestion

| # | Action | Practice owner | Associate | Assistant | Client owner | Client team member | Notes |
|---|---|---|---|---|---|---|---|
| 11.1 | View the review queue | ✅ | 🔸 | ✅ | ❌ | ❌ | **Associate: `proposal-scope`.** practice owner and assistant see every proposal |
| 11.2 | Trigger "Sync now" | ✅ | 🔸 | ✅ | ❌ | ❌ | Associate: `proposal-scope` |
| 11.3 | Approve a participant (create / link a contact) | ✅ | 🔸 | ✅ | ❌ | ❌ | Associate: `proposal-scope`. Creates a record; sends nothing |
| 11.4 | Confirm a participant's contact type | ✅ | 🔸 | ✅ | ❌ | ❌ | Confirming `referral partner` **queues** onboarding (FR-5.9b) |
| 11.5 | Approve action items / deliverables | ✅ | 🔸 | ✅ | ❌ | ❌ | R11, R12 |
| 11.6 | Accept / edit / discard the meeting summary | ✅ | 🔸 | ✅ | ❌ | ❌ | R11a |
| 11.7 | Reject a proposal item | ✅ | 🔸 | ✅ | ❌ | ❌ | |
| 11.8 | Re-parse a source file | ✅ | 🔸 | ✅ | ❌ | ❌ | Writes an `ai_call` |
| 11.9 | View meetings on a contact timeline | ✅ | 🔸 | ✅ | ❌ | ❌ | Client users see tasks, never meeting records |
| 11.10 | Connect / disconnect the notes folder | ✅ | ❌ | ❌ | ❌ | ❌ | **Practice owner only.** Grants the app a standing read of a Drive |
| 11.11 | Grant Drive access (`drive.readonly` consent) | ✅ | ❌ | ❌ | ❌ | ❌ | Practice owner only; on the practice owner's own Google connection |
| 11.12 | See the folder's name, last poll and last error | ✅ | ✅ | ✅ | ❌ | ❌ | Read-only for associate and assistant |
| 11.13 | Choose and run the folder backfill; stop it | ✅ | ❌ | ❌ | ❌ | ❌ | **Practice owner only.** It spends the practice's money against the practice's own Drive |

> **Row 11.4 does not apply to our own staff (FR-5.9e).** A participant who matches somebody on the practice's staff is recognized rather than asked about: no type is offered, no approval is needed, and the row is excluded from whether the proposal is still open. There is nothing to authorize because nothing is created — so there is no role question here, for any role.
>
> **Connecting is narrower than using (11.10–11.12).** Clearing this queue is the assistant's job and an associate's own meetings are in it, so both act on proposals freely. But pointing the app at a folder grants it a standing read of a whole Google Drive, and there is one folder per practice — so choosing it belongs with the person who answers for the practice's data. The asymmetry with 11.12 is deliberate too: every staff role may *see* where the folder has got to, because a queue that is empty and a queue that is asleep look identical to whoever has to clear it.
>
> **The assistant's broad rights here are deliberate.** Clearing this queue is the assistant's job, and every action in it creates records rather than sending mail — the send is a separate, gated step (FR-5.19, row 5.3).
>
> **Why `proposal-scope` is not simply "all practice staff".** A meeting proposal usually *precedes* any company link — matching participants is the point of the queue — so an unmatched proposal has no company to scope by. The tempting fix is to show unmatched proposals to everyone. That is wrong: **an associate is not assigned to the practice owner's prospects, and must not read the practice owner's prospect meeting notes before anyone has decided they should.** So the scope has a second limb — **the associate owns the source Drive file**, i.e. it was their own meeting — which covers the legitimate case without opening the practice owner's pipeline. A proposal that is neither matched to an assigned company nor from the associate's own file is visible to practice owner and assistant only, which is the correct default for an unreviewed document.

## 12. Module 6 — Communication

| # | Action | Practice owner | Associate | Assistant | Client owner | Client team member | Notes |
|---|---|---|---|---|---|---|---|
| 12.1 | View a contact's email history | ✅ | 🔸 | ✅ | ❌ | ❌ | |
| 12.2 | View the unmatched inbound queue | ✅ | 🔸 | ✅ | ❌ | ❌ | |
| 12.3 | File an unmatched message to a contact | ✅ | 🔸 | ✅ | ❌ | ❌ | Filing creates no outbound mail |
| 12.4 | Send a reply | ✅ | 🔸 | ❌ | ❌ | ❌ | Assistant drafts only (row 5.6) |
| 12.5 | Access any communication surface | — | — | — | ❌ | ❌ | Includes internal correspondence *about* them |

## 13. Financial boundary (V1 modules, recorded now)

Beta ships no financial module. These rows exist so the role-boundary suite has a failing target from day one: **an endpoint that does not exist yet must still 403 for an assistant when it arrives**, rather than being remembered later.

| # | Action | Practice owner | Associate | Assistant | Client owner | Client team member | Notes |
|---|---|---|---|---|---|---|---|
| 13.1 | View P&L / balance sheet | ✅ | ❌ | ❌ | ❌ | ❌ | |
| 13.2 | View fee splits on assigned clients | ✅ | 🔸 | ❌ | ❌ | ❌ | `CLAUDE.md`: Associate financials limited to assigned clients |
| 13.3 | View fee splits on **unassigned** clients | ✅ | ❌ | ❌ | ❌ | ❌ | |
| 13.4 | Product billing (the practice's own subscription) | ✅ | ❌ | ❌ | ❌ | ❌ | Not built (P4) |
| 13.4a | **See and download client invoices, and the list with its totals** | ✅ every one | 🔸 `assigned` client companies | ❌ | ✅ their company's, sent and after | ✅ their company's, sent and after | P4A, owner 2026-10-08 (P4 D7, D8). A client never sees a draft, an unsent invoice, or one written to a contact. Out of scope is 404 |
| 13.4b | Write and edit a draft; make it ready; recurring schedules | ✅ | 🔸 `assigned` | ❌ | — | — | Making ready sends nothing |
| 13.4c | **Approve the send of an invoice; resend** | ✅ | ❌ | ❌ | — | — | Narrower than 5.3: an associate approves other mail, never an invoice |
| 13.4d | Record or remove a payment; void | ✅ | ❌ | ❌ | — | — | Each with an audit event; remove and void need a reason |
| 13.4e | Invoice a contact that is not a client company | ✅ | ❌ | ❌ | — | — | Email only; in no portal |
| 13.4f | Invoice settings (prefix, next number, terms, how to pay, the email) | ✅ | ❌ (reads) | ❌ | — | — | |
| 13.4g | **See an invoice's email anywhere else**: the Outbox, the Sending queue, the send log, a client's email history and timeline, the activity feed | ✅ | 🔸 `assigned` | **❌** | — | — | The one exception to 5.1, 5.9 and 12.x for an assistant: an invoice and the replies to it are on a thread of their own (`email_thread.is_financial`) |
| 13.6 | **The books**: see, add, change and remove entries | ✅ | ❌ | ❌ | — | — | P5, owner 2026-10-08. Associate and assistant 403 on every route; a client user 404 |
| 13.7 | Accounts, categories, where paid invoices are entered, the lock | ✅ | ❌ | ❌ | — | — | |
| 13.8 | Import a bank or card export; roll one back | ✅ | ❌ | ❌ | — | — | Not built (P5, second stop) |
| 13.9 | The CPA export | ✅ | ❌ | ❌ | — | — | Each download is an audit event |
| 13.10 | The dashboard's revenue, expenses and margin | ✅ | ❌ | ❌ | — | — | Absent from everyone else's payload |
| 13.5 | Any financial endpoint | ✅ | 🔸 | **❌** | ❌ | ❌ | **The non-negotiable assistant test family** (`CLAUDE.md`) |

---

## 14. The two mandatory test families, derived from this table

Per `CLAUDE.md` these are non-negotiable, and per assumption B3 they are a registry, not hand-written per module.

### 14.1 Practice isolation

For **every** model in `02_data_model.md` §1–§8 — **including §6A's six** (`goal_measurement`, `goal_milestone`, `goal_resolution`, `goal_narrative`, `goal_narrative_version`, `goal_report_export`): create a row in practice A and a row in practice B, then assert that a user of practice A gets **404** on read, update, and delete of B's row — through the API, through search, and through any timeline or aggregate view.

**The meta-test:** enumerate every concrete model inheriting `TenantScopedModel`; fail if any is absent from the registry. This is what stops the matrix and the code drifting apart.

### 14.2 Role boundaries

Every row above becomes a parametrised case: `(action, role, scope_fixture) → expected`.

Five cases carry the most weight and are called out so they are never merely inherited from a loop:

1. **Assistant cannot approve or send** — rows 5.3, 8.3, 10.11, 12.4. Expect **403**, and assert the dev outbox is empty afterwards.
2. **Assistant cannot reach financials** — row 13.5, including §9 investment fields (row 10.8) absent from the response body, not merely hidden in the UI.
3. **Client team member cannot reach anything outside their company** — rows 7.1–7.15 **and 10A.1–10A.2** with a second client company in the *same* practice. Expect **404**, never 403.
4. **Associate `assigned` scope is real** — every 🔸 associate row tested both in and out of assignment, with the assignment removed mid-test to confirm it takes effect on the next request (AC-1.13).
5. **PIN gating is not a role** — row 6.4 tested as practice owner *without* the PIN, expecting the body to be absent (AC-2.3).
6. **An assistant may administer and may not judge** — rows 10A.6, 10A.10 and 10A.13. Expect **403**, asserted against the API response body, with rows 10A.4 and 10A.15 passing for the same assistant in the same test so the boundary is shown to be a line and not a blanket refusal. *(Added 2026-09-21 with Module 4B.)*

### 14.3 Two assertions every send-related case must make

Because the review-queue rule is the product's central promise, a 403 alone is not a sufficient assertion:

- **The dev outbox is empty** after every denied send attempt.
- **No `outbox_message` row moved to `sent`**, and no `digest.state` advanced.

---

## 15. Review outcome

All four flagged rows ruled on; seven changes applied.

**Rulings:**

- **15.1 (row 3.13) — approved as written.** assistant edits template body copy; practice owner creates and deletes templates.
- **15.2 (row 4.14) — approved.** The assistant commits and rolls back imports, because they are the one running them and it is reversible (FR-1.31).
- **15.3 (row 4.5) — changed to assistant ✅, audited.** Your reasoning is better than mine: I restricted merge on the grounds that it is not cleanly reversible, but the practical effect was to route the cleanup half of the assistant's own import work back to the practice owner. Associate stays ❌.
- **15.4 (rows 11.x) — kept scoped, with a second limb added.** `proposal-scope` is now "participant matched to an assigned company **or** the associate owns the source Drive file." This required a data-model change: `meeting_source_file` now records `drive_file_owner_email` at ingestion.

**Changes:**

| # | Change | Rows |
|---|---|---|
| 1 | Pipeline stages split out as practice owner-only; contact types and service categories stay assistant ✅ | 3.14, 3.15 |
| 1a | **Pipeline management became per pipeline** once the owner's real CRM turned out to run two (sales, and a nurture pipeline for referral partners). Practice owner-only to change, readable by all practice staff | 3.14a, 3.15, 3.15a |
| 2 | Assistant soft-deletes contacts and companies; restore row added | 4.4, 4.4a |
| 3 | Practice staff management rows added, practice owner-only | 3.16, 3.17, 3.18 |
| 4 | AI usage and cost visibility, practice owner-only — spend is financial | 3.19 |
| 5 | Soft-delete a task, with clients limited to tasks they created | 7.6a |
| 6 | Goal and Project creation split; clients may create projects | 7.2, 7.2a |
| 7 | `client-editable` defined once and cited in three rows | 7.4, 7.5, 7.6 |

**On change 7.** Rows 7.4–7.6 previously overlapped in a way that could not be tested: "tasks they created or are assigned" and "assign other users' tasks" are not the same set. **FR-3.9a** now states one rule — a client user may edit, restatus, and reassign any client-visible task in their company that is **assigned to a client-side user or created by a client user**; a task assigned to a *practice* user is read-only to clients apart from shared comments. Row 7.6a is deliberately narrower still: deleting work a fractional assigned is not a client's call.

**Documents updated by these changes:** `01_prd.md` (FR-3.9a, FR-3.35a, FR-0.8, FR-0.9, plus four ACs), `02_data_model.md` (`meeting_source_file.drive_file_owner_email`, `project.created_by_client`, staff-revocation cascade).
