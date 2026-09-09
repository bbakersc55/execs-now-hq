# 02 — Data Model: Beta

**Phase 0 · Execs NOW HQ · for owner review**
**Built on:** `CLAUDE.md`, `00_assumptions.md` (closed), `01_prd.md` (approved with 17 changes applied), `strategy_session_seed.md`.

---

## 0. Conventions

These apply to **every** table in this document and are not repeated per table.

| Convention | Rule | Source |
|---|---|---|
| Primary key | `id UUID` (uuid4), not sequential | D1 |
| Tenant | `tenant_id UUID NOT NULL FK → tenant` on every domain table, `ON DELETE PROTECT`, indexed | `CLAUDE.md`, B1 |
| Timestamps | `created_at`, `updated_at` — `timestamptz`, UTC | D4 |
| Soft delete | `deleted_at timestamptz NULL` on Contact, Company, Note, Goal, Project, Task, Comment | D2 |
| Actor columns | `created_by`, `updated_by` → `user`, nullable (system actions have no user) | — |
| Money | none in Beta beyond free-text fee terms | D5 |
| Enum style | Python choices for anything permission logic depends on; **tables** for anything V1 lets a tenant customise | D5 |

**Tenant scoping is enforced by the fail-closed manager in B1, not by the schema.** `tenant_id` is on every row so the filter is *possible*; the manager is what makes it *unavoidable*. Two schema-level supports:

- Every unique constraint that could otherwise collide across tenants is scoped: `UNIQUE (tenant_id, …)`, never a bare `UNIQUE (…)`.
- Every FK between two domain tables carries a **model-level `clean()` check that both sides share a `tenant_id`**. Postgres cannot express this as a simple FK, so it is a validation rule plus a test in the isolation registry (B3), not a constraint.

**Legend:** `PK` primary key · `FK→x` foreign key · `?` nullable · `U(a,b)` unique together · `IX` indexed.

---

## 1. Tenancy, identity, access

### `tenant`
The practice. One row in Beta.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `name` | text | "Executives Now" |
| `slug` | text U | |
| `timezone` | text | IANA, default `America/Denver` (D4) |
| `from_address` | text | `info@getexecutivesnow.com` (H2) |
| `inbound_domain` | text | `inbound.getexecutivesnow.com` |
| `discipline` | text | `operations` in Beta; multi-discipline is V1 |
| `hold_all_digests` | bool | **default `true`** (FR-3.25) |
| `digest_ai_prose_default` | bool | default `true`; the value a new client company inherits (FR-3.24) |
| `digest_send_day` | smallint | ISO weekday, default 5 = Friday (FR-3.23) |
| `digest_send_hour` | smallint | default 8 |
| `audio_retention_days` | int | default 30 (F7) |
| `referral_blurb` | text? | "what I'm working on lately" (FR-1.21a) |
| `referral_blurb_updated_at` | timestamptz? | drives the staleness warning, FR-1.22a |
| `marketing_flyer` | FK→`stored_file`? | optional onboarding attachment (FR-1.23b) |
| `created_at` / `updated_at` | timestamptz | |

> `tenant` is the one table with **no** `tenant_id`. It is the root.

### `user`
Django's user, extended. Tenant staff **and** client portal users.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `email` | citext U | |
| `full_name` | text | |
| `is_active` | bool | |
| `password` | text | **always unusable** except the local superuser (C4) |
| `timezone` | text? | overrides tenant default |
| `last_login_at` | timestamptz? | |

### `membership`
User × tenant × role. Exists as a table from migration 1; **enforced one-per-user in Beta** (B4).

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `tenant_id` | FK→`tenant` | |
| `user_id` | FK→`user` | |
| `role` | text | `FF` · `CF` · `VA` · `FCC` · `ECC` |
| `client_company_id` | FK→`company`? | **required when role is FCC/ECC, null otherwise** — the second scope layer (FR-0.2) |
| `contact_id` | FK→`contact`? | the person this login belongs to (F1) |
| `invited_by` / `invited_at` | FK→`user`? / timestamptz | |
| `revoked_at` | timestamptz? | set on revoke; frees a seat (FR-3.33g) |

> **Revoking a tenant staff member cascades** (FR-0.8c): sessions are invalidated, and for a CF every live `client_assignment` is closed (`removed_at` set) and their `gmail_connection` is deleted along with its `tenant_secret`. Nothing they authored is deleted — a departed CF's tasks, notes, and sent mail remain.
| | | `U(tenant_id, user_id)` |

**Check constraint:** `role IN ('FCC','ECC') = (client_company_id IS NOT NULL)`. This is the one invariant worth expressing in the database rather than in code, because a client user without a company is an unbounded client user.

### `client_assignment`
Tenant user × client company (FR-1.9a). **Every "assigned accounts" rule in Modules 1–6 resolves here.**

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK · `tenant_id` | |
| `user_id` | FK→`user` | must hold a CF (or FF) membership |
| `company_id` | FK→`company` | must have `is_client_company` |
| `assigned_by` / `assigned_at` | FK→`user` / timestamptz | FF only (FR-1.9b) |
| `removed_at` | timestamptz? | soft removal keeps the audit trail |
| | | `U(tenant_id, user_id, company_id)` where `removed_at IS NULL` |

### `magic_link_token` (C3)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK · `tenant_id` | |
| `user_id` | FK→`user` | |
| `token_hash` | char(64) IX | SHA-256; **the raw token exists only in the email** |
| `purpose` | text | `signin` · `pin_reset` |
| `expires_at` | timestamptz | 20 minutes |
| `used_at` | timestamptz? | single use |
| `requested_ip` | inet? | |
| `redirect_to` | text? | validated against an internal allow-list |

### `stakeholder_token` (F18, FR-3.33a)
Separate from magic links by design: different lifetime, different scope, one capability.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK · `tenant_id` | |
| `stakeholder_id` | FK→`stakeholder` | |
| `token_hash` | char(64) IX | |
| `expires_at` | timestamptz | 30 days (FR-3.33b) |
| `revoked_at` | timestamptz? | set when the stakeholder row is removed |

### `tenant_secret` (E1)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK · `tenant_id` | |
| `kind` | text | `anthropic_api_key` · `gmail_refresh` · `drive_refresh` |
| `user_id` | FK→`user`? | set for per-user Gmail tokens |
| `ciphertext` | bytea | **Fernet; the key lives in the environment, never in this table** |
| `last4` | char(4) | all the UI ever shows |
| `created_at` / `rotated_at` / `verified_at` | timestamptz | |
| `verified_by` | FK→`user`? | |
| | | `U(tenant_id, kind, user_id)` **plus** a partial unique index |

```sql
-- U(tenant_id, kind, user_id) does NOT enforce one Anthropic key per tenant:
-- Postgres treats NULLs as distinct, so unlimited rows with user_id IS NULL collide with nothing.
CREATE UNIQUE INDEX tenant_secret_one_per_tenant
  ON tenant_secret (tenant_id, kind) WHERE user_id IS NULL;
```

**Write-only across the entire API.** No serializer, admin page, log line, or error message returns `ciphertext`.

### `audit_event` (D3)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK · `tenant_id` | |
| `actor_id` | FK→`user`? | null = system |
| `verb` | text IX | `digest.approved`, `pin.reset`, `stage.changed`, `portal.granted`, … |
| `target_type` / `target_id` | text / UUID | IX together |
| `payload` | jsonb | |
| `created_at` | timestamptz IX | |

### `ai_call` (E1.7, FR-4.18c)
Every Claude call, so cost per module is a number you can look up.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK · `tenant_id` | |
| `purpose` | text | `strategy_rows` · `strategy_mirror` · `digest_prose` · `meeting_parse` · `meeting_summary` · `note_summary` · `referral_touch` |
| `target_type` / `target_id` | text / UUID? | |
| `model` / `input_tokens` / `output_tokens` / `cost_usd` | text / int / int / numeric(10,6) | |
| `trigger` | text | `button` · `auto` · `schedule` (FR-4.18a) |
| `succeeded` / `error` | bool / text? | |

### `stored_file`
One place for GCS-backed blobs: recording audio, flyers, PDFs, inbound attachments.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK · `tenant_id` | |
| `bucket` / `object_key` | text / text | |
| `content_type` / `byte_size` | text / bigint | |
| `purpose` | text | `recording_audio` · `marketing_flyer` · `session_pdf` · `email_attachment` |
| `delete_after` | timestamptz? | set by retention (FR-2.19) |

---

## 2. Module 1 — Contacts & pipeline

### `company`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK · `tenant_id` | |
| `name` | text IX | |
| `industry` | text? | |
| `address` | jsonb? | |
| `is_client_company` | bool | derived by FR-1.6a.1, cleared only by hand |
| `seat_count` | int? | FF-set; null until it is a client company (FR-3.33f) |
| `digest_ai_prose` | bool | **FR-3.24 — AI prose on/off for this client's digests**, seeded from `tenant.digest_ai_prose_default` |
| `primary_contact_id` | FK→`contact`? | FR-1.3a — designated recipient, FCC default |
| `deleted_at` | timestamptz? | |

**Circular FK note:** `company.primary_contact_id → contact` and `contact.company_id → company` reference each other. Both are nullable and created in two migrations (company, then contact, then the FK), which is the ordinary Django resolution. It is called out because it is the only cycle in the schema.

### `company_domain`
Separate table, because domain matching drives meeting-participant matching (FR-5.10).

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK · `tenant_id` · `company_id` | |
| `domain` | citext IX | `U(tenant_id, domain)` |

### `company_location`
Ordered list. Feeds `{Location A}` / `{Location B}` (FR-1.3, FR-4.9a).

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK · `tenant_id` · `company_id` | |
| `name` | text | |
| `position` | smallint | 0 = Location A, 1 = Location B |

### `contact`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK · `tenant_id` | |
| `first_name` / `last_name` | text / text | IX on both |
| `title` | text? | |
| `company_id` | FK→`company`? | |
| `owner_id` | FK→`user` | drives CF visibility (FR-1.9c) |
| `stage_id` | FK→`pipeline_stage` | **authoritative for "is a client" (FR-1.6a)** |
| `source` | text? | |
| `background` | text? | short "who this is / how we met". **Renamed from `notes`** — one concept in this product is called a note, and it is the `note` table (§12.2) |
| `tags` | text[] (ArrayField, GIN-indexed) | |
| `referral_fee_terms` | text? | FR-1.20a |
| `referral_cadence` | text? | `monthly` (default) · `bimonthly` · `quarterly` |
| `referral_touch_mode` | text | `ai` (default) · `template` — FR-1.22's per-contact choice, which had no column in the first draft |
| `referral_template_id` | FK→`email_template`? | used when mode is `template` |
| `referral_next_touch_at` | timestamptz? | clock starts at onboarding (FR-1.23c) |
| `referral_onboarded_at` | timestamptz? | **presence prevents re-triggering (FR-1.23d)** |
| `search_vector` | tsvector IX(GIN) | FR-1.33 |
| `source` | text? | on `note`: `manual · import · recording` |
| `merged_into_id` | FK→`contact`? | survivor pointer (FR-1.34) |
| `deleted_at` | timestamptz? | |

### `contact_email` / `contact_phone`
Multiple per contact, one primary each (FR-1.1). Stakeholder delivery uses the primary email (FR-3.20).

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK · `tenant_id` · `contact_id` | |
| `address` (or `number`) | citext / text | IX — email match is the first matching rule (FR-5.10) |
| `is_primary` | bool | at most one true per contact |

### `contact_type` / `contact_type_link`
Per-tenant list (D5); many-to-many (FR-1.2).

`contact_type`: `id · tenant_id · code · label · position` — seeded `prospect, client, referral_partner, vendor, coworker`.
`contact_type_link`: `id · tenant_id · contact_id · contact_type_id · is_primary` — `U(tenant_id, contact_id, contact_type_id)`.

### `pipeline_stage`
Per-tenant rows (D5, FR-1.6).

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK · `tenant_id` | |
| `code` / `label` | text / text | `contact, lead, qualified_lead, client, lost, dormant` |
| `position` | smallint | |
| `is_terminal` | bool | true for `lost`, `dormant` |

### `stage_change`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK · `tenant_id` · `contact_id` | |
| `from_stage_id` / `to_stage_id` | FK→`pipeline_stage`? / FK | |
| `reason` | text? | prompted on `lost` |
| `actor_id` / `created_at` | FK→`user`? / timestamptz | |

### `service_category` / `contact_service_category`
Vendor search (FR-1.24–25). `service_category`: `id · tenant_id · name` with `U(tenant_id, name)`. Link table joins to `contact`.

### `stage_automation`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK · `tenant_id` | |
| `from_stage_id` | FK? | null = any |
| `to_stage_id` | FK | |
| `action_type` | text | `create_task` · `draft_email` |
| `task_title_template` / `task_due_offset_days` | text? / int? | for `create_task` |
| `email_template_id` | FK→`email_template`? | for `draft_email` |
| `send_by_offset_days` | int | **default 7** (FR-1.12) |
| `is_active` | bool | |

### `email_template`
`id · tenant_id · name · subject · body · kind` where `kind ∈ {stage, referral_touch, referral_onboarding}`.

### `import_batch` / `import_row`
Reversible CSV import (FR-1.26–32).

`import_batch`: `id · tenant_id · filename · mapping_profile_id? · status (dry_run|committed|rolled_back) · counts jsonb · created_by · created_at · rolled_back_at?`

`import_row`: `id · tenant_id · import_batch_id · row_number · raw jsonb · outcome (create|update|skip|error|ambiguous) · error_text? · contact_id? · previous_values jsonb?`

> **`previous_values` is what makes rollback real.** It stores the pre-import value of every field the import changed, so an update can be reversed field by field. A row whose contact was hand-edited after import is detected by comparing `updated_at` and is skipped with a report (FR-1.31).

`import_mapping_profile`: `id · tenant_id · name · mapping jsonb`.

> **A CSV "notes" column becomes a real `note` row** linked to the contact with `source = 'import'` — not a blob on the contact (§12.2). `contact.background` is a short "who this is / how we met" line, written by a person. One concept in this product is called a note, and it lives in one table.

---

## 3. The Outbox — one table, every send

Per FR-1.15 the Outbox is **both** the approval queue and the complete send log.

### `outbox_message`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK · `tenant_id` | |
| `state` | text IX | `draft · pending_approval · approved · sent · rejected · expired` |
| `producer` | text IX | `stage_rule · referral_touch · referral_onboarding · digest · strategy_pdf · precall_invite · magic_link · cadence_change · inbound_forward · manual` |
| `to_contact_id` | FK→`contact`? | |
| `to_address` | citext | resolved at creation; survives contact edits |
| `from_address` | citext | tenant alias, or a user's own address for Gmail sends |
| `subject` / `body_html` / `body_text` | text | |
| `is_ai_generated` | bool | drives the Outbox label (FR-1.23) and the approval rule (FR-3.27) |
| `warning` | text? | e.g. the stale-blurb notice (FR-1.22a) |
| `send_by` | timestamptz? | expiry deadline (FR-1.12, FR-1.18) |
| `approved_by` / `approved_at` | FK→`user`? / timestamptz? | |
| `sent_at` | timestamptz? | |
| `provider_message_id` | text? | Postmark or Gmail id |
| `thread_id` | FK→`email_thread`? | |
| `sent_via` | text | `postmark` · `gmail` |
| `dev_real_send` | bool | true when delivered from a localhost build via the allow-list (H6) |
| `source_type` / `source_id` | text / UUID? | the digest, session, or stage change that produced it |

**Direct-to-`sent` producers** (FR-1.15b): `strategy_pdf`, `magic_link`, `cadence_change`, `inbound_forward`, `precall_invite`, and `manual` **when sent by an FF or CF**.

**Two producers whose routing depends on the sender's role:**

| Producer | FF / CF | VA |
|---|---|---|
| `precall_invite` | direct-to-`sent` | **direct-to-`sent`** — template-only, non-AI, from the tenant address (H7a) |
| `manual` | direct-to-`sent`, via their own Gmail | **`pending_approval`** — a VA never sends to a contact (H7) |

Everything else enters at `pending_approval`.

### `outbox_attachment`
`id · tenant_id · outbox_message_id · stored_file_id · filename` — carries the marketing flyer (FR-1.23b).

---

## 4. Module 2 — Notes

### `note`

> **Created across two phases — deliberate, and recorded here so the split is not mistaken for drift.**
>
> FR-1.1a makes a CSV notes column create a real `note` row rather than a blob on the contact (§12.2), so **Module 1's import depends on this table**. Phase 1 therefore creates `note` with six columns only: `title`, `title_is_auto`, `body`, `contact`, `company`, `source`, plus `import_batch` (so a rollback removes the notes it created) and `deleted_at`.
>
> **Phase 2 adds the rest:** `pin_hash`, `pin_set_at`, `failed_pin_attempts`, `pin_locked_until`, `transcript`, `summary`, `proposed_summary`, `summary_state`, `audio_file`, `transcription_state`, and `search_vector`. The `task` FK arrives with Module 3.
>
> The alternative — deferring the notes-column mapping to Phase 2 — would keep the module boundary clean but leave FR-1.1a untestable in Phase 1. Owner ruling: create it early.


| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK · `tenant_id` | |
| `title` | text? | |
| `title_is_auto` | bool | **derived from the first body line; gates PIN-setting (FR-2.11a) and stub rendering (FR-2.11b)** |
| `body` | text | markdown; **not encrypted** (FR-2.8) |
| `contact_id` | FK→`contact`? | |
| `company_id` | FK→`company`? | |
| `task_id` | FK→`task`? | **independent of the above (FR-2.3)** |
| `pin_hash` | text? | Django password hash; null = unlocked |
| `pin_set_at` | timestamptz? | |
| `failed_pin_attempts` / `pin_locked_until` | smallint / timestamptz? | 5 attempts → 15 min (FR-2.10) |
| `transcript` | text? | |
| `summary` | text? | **null until a human accepts it (FR-2.17)** |
| `summary_state` | text | `none · proposed · accepted · discarded` |
| `proposed_summary` | text? | held separately so accepting is an explicit copy, not an edit-in-place |
| `audio_file_id` | FK→`stored_file`? | deleted per `audio_retention_days` |
| `transcription_state` | text | `none · uploading · transcribing · done · failed` |
| `search_vector` | tsvector IX(GIN) | **excludes body and summary when `pin_hash IS NOT NULL`** |
| `deleted_at` | timestamptz? | |

**Check constraint:** `NOT (contact_id IS NOT NULL AND company_id IS NOT NULL)` — a contact already implies its company (FR-2.3a).

**Two rules the schema supports but does not enforce**, both covered by tests:
1. Setting `pin_hash` requires `title_is_auto = false` (FR-2.11a).
2. A locked stub renders `"Locked note"` when `title_is_auto` is true, whatever the title holds (FR-2.11b).

### `note_pin_unlock`
Session-scoped unlock (FR-2.9). `id · tenant_id · note_id · user_id · session_key · unlocked_at · expires_at`.

---

## 5. Module 3 — Task engine

> The hierarchy is **Goal → Project → Task**, with `goal` and `project` both nullable on a Task (FR-3.5), and **depth capped at three** — a task has no self-FK, which is what makes the cap structural rather than a rule someone has to remember.

### `goal`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK · `tenant_id` | |
| `title` / `description` | text / text? | |
| `client_company_id` | FK→`company`? | null = internal |
| `owner_id` | FK→`user` | the accountable **tenant** user |
| `client_owner_contact_id` | FK→`contact`? | **who on the client side is accountable** — see below |
| `target_date` | date? | |
| `status_override` | text? | **FR-3.10: null means derive from children at read time; never store the derived value** |
| `source_map_row_id` | FK→`strategy_map_row`? | **the back-link from Module 4 (FR-4.31)** |
| `deleted_at` | timestamptz? | |

### `project`
Same shape — including `owner_id`, `client_owner_contact_id`, and `status_override` — plus `goal_id FK→goal?`, `start_date`, its own `source_map_row_id` (a map row becomes a Goal *or* a Project, chosen per row — FR-4.28), and **`created_by_client bool`**.

> A **client-created project** has `created_by_client = true`, `goal_id = null` by definition (strategy stays the fractional's), and `client_company_id` set to the creator's own company. It is how a client groups their own work in the portal (FR-3.35a, matrix row 7.2a).

### Client-side ownership on `goal` / `project` / `task`

`owner_id` is the accountable **tenant** user and never changes meaning. `client_owner_contact_id` answers a different question — *who on the client side is accountable* — and it exists because both upstream sources name client people, not app users:

| Source | Field | Mapping on conversion / approval |
|---|---|---|
| Strategy Map row | `owner_text` (free text, usually the Integrator) | If it resolves to exactly one Contact at the company, set `client_owner_contact_id`; **otherwise keep `owner_text` as written** and leave the FK null. Never guess between two candidates. |
| Meeting action item | `proposed_owner_contact_id` | Set `client_owner_contact_id`. If that Contact has a login, `assignee_id` may also be set; if not, the client owner is recorded without inventing a user. |

The unresolved case is deliberately preserved rather than dropped: "Maria in dispatch" is useful on a Goal even when no Contact matches it.

### `task`

> **Created across two phases, on the same precedent as `note`.**
>
> FR-1.11 says a `create_task` stage rule "fires immediately, no approval", so **Module 1 depends on this table**. Phase 1 creates it with only the columns a stage rule needs: `title`, `description`, `status`, `due_date`, `owner`, `contact`, `source_automation`, `deleted_at`. The **full FR-3.7 status set is declared from the start**, so Phase 3 extends the table rather than migrating its values.
>
> **Phase 3 adds:** `project`, `goal`, `client_company`, `assignee`, `is_client_visible`, `created_by_client`, `client_owner_contact`, `status_override` semantics on parents, `source_map_row`, `source_proposal_item`, plus `task_checklist_item`, `comment`, `task_update`, and `stakeholder`.


| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK · `tenant_id` | |
| `title` / `description` | text / text? | |
| `project_id` / `goal_id` | FK? / FK? | both nullable (FR-3.5) |
| `client_company_id` | FK→`company`? | |
| `assignee_id` | FK→`user`? | the app user doing the work; client users may only assign within their company (FR-3.9) |
| `client_owner_contact_id` | FK→`contact`? | client-side accountable person, per the table above |
| `status` | text IX | `not_started · in_progress · blocked · waiting_on_client · done · cancelled` (FR-3.7) |
| `priority` | smallint | |
| `due_date` | date? | |
| `is_client_visible` | bool | defaults true when `client_company_id` is set (FR-3.11) |
| `created_by_client` | bool | FR-3.37 |
| `source_map_row_id` | FK→`strategy_map_row`? | |
| `source_proposal_item_id` | FK→`proposal_item`? | provenance from Module 5 |
| `deleted_at` | timestamptz? | |

> **No `parent_task_id`.** Three levels is enforced by the absence of the column (FR-3.4).

### `task_checklist_item`
`id · tenant_id · task_id · text · is_done · position` — the flat substitute for subtasks (FR-3.4).

### `comment`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK · `tenant_id` | |
| `task_id` / `project_id` / `goal_id` | FK? ×3 | exactly one set |
| `author_id` | FK→`user` | |
| `body` | text | |
| `visibility` | text | `internal` · `shared` — **defaults `internal` (FR-3.12a)** |
| `deleted_at` | timestamptz? | |

### `task_update` — the digest's source material

This is the most consequential table in the product. Digests are assembled from these rows, never from diffing current state (FR-3.15).

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK · `tenant_id` | |
| `task_id` / `project_id` / `goal_id` | FK? ×3 | the entity that changed |
| `kind` | text | `created · status_changed · assignee_changed · due_changed · comment_added · checklist_completed · completed · narrative` |
| `from_value` / `to_value` | text? / text? | |
| `client_facing_line` | text? | **the prompted "what this means for you" (FR-3.16) — a first-class field, not a comment** |
| `actor_id` | FK→`user`? | **nullable — a stage automation or ingestion job has no user actor** |
| `source` | text | `user · stage_automation · meeting_approval · strategy_conversion · system` |
| `source_id` | UUID? | e.g. the `stage_automation` row that fired |
| `is_client_actor` | bool | client-originated updates are visible but never digest-triggering for their own author |
| `created_at` | timestamptz IX | |

> **There is deliberately no `digest_id` column here.** An earlier draft had one, and it was wrong: a single update is sent to *every* stakeholder on the entity, so one column cannot be simultaneously "consumed" for Dana on weekly and "unconsumed" for her site manager on `every_update`. Consumption is per recipient, so it lives in a join table — `digest_item`, below.

### `stakeholder` (F18)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK · `tenant_id` | |
| `contact_id` | FK→`contact` | **a Contact, not a User (FR-3.20)** |
| `goal_id` / `project_id` / `task_id` | FK? ×3 | exactly one set — the attachment level (FR-3.20a) |
| `cadence` | text | `every_update · weekly · monthly` — default `weekly` |
| `is_muted` | bool | set by the recipient's own cadence link |
| `last_notified_at` | timestamptz? | FR-3.32 |
| | | `U(tenant_id, contact_id, task_id)` etc. per level |

**Effective stakeholders for a task** = union across its task, project, and goal rows, de-duplicated by `contact_id`, **most specific attachment wins for cadence** (FR-3.20a). Computed, never stored.

### `digest`

**Keyed by recipient, not by stakeholder attachment.** Since the same Contact may hold stakeholder rows at both Goal and Task level (§12.1, approved), keying a digest per attachment would put two emails in one person's inbox on the same Friday. The key is the person.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK · `tenant_id` | |
| `contact_id` | FK→`contact` | **the recipient — authoritative** |
| `period_start` / `period_end` | timestamptz | |
| `cadence` | text | `every_update · weekly · monthly` |
| | | **`U(tenant_id, contact_id, cadence, period_start)`** |

> **Why `cadence` belongs in the key.** Most-specific-wins (FR-3.20a) can legitimately put one person on two cadences at once — weekly across a Goal, `every_update` on one urgent task inside it. Those are genuinely two different emails with different timing, not a duplicate. The unique constraint collapses the duplicates that matter (two Friday weeklies) while permitting the ones that are real.

> **`stakeholder_id` is gone from this table.** Which attachment an update arrived through is a property of the update, not of the digest, so it is recorded per row in `digest_item`.
| `state` | text IX | `pending · approved · sent · expired · skipped` |
| `is_ai_generated` | bool | **derived at generation from `company.digest_ai_prose` (FR-3.24); decides whether approval is required when `hold_all_digests` is off (FR-3.27)** |
| `is_stale` | bool | **FR-3.30a** |
| `stale_reason` | text? | names what changed |
| `body_html` / `body_text` | text | rendered at generation |
| `generated_at` / `send_window_at` | timestamptz | Thursday 08:00 / Friday 08:00 by default |
| `approved_by` / `approved_at` | FK→`user`? / timestamptz? | |
| `outbox_message_id` | FK→`outbox_message`? | the send log row |

### `digest_item`
The join written at generation. **This is what makes multi-stakeholder delivery correct.**

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK · `tenant_id` | |
| `digest_id` | FK→`digest` | |
| `task_update_id` | FK→`task_update` IX | |
| `stakeholder_id` | FK→`stakeholder`? | **which attachment this update reached the recipient through** — nullable, since the stakeholder row may later be removed |
| | | `U(tenant_id, digest_id, task_update_id)` |

**The three rules this table encodes:**

1. **Roll-forward** (FR-3.30) is now a per-recipient question: an update is still owed to a contact when **no `digest_item` exists joining it to a `digest` for that contact in state `sent`**. The same `task_update` can be sent to Dana on Friday and to her site manager 30 minutes after it happened — the two are independent rows.
2. **Expiry releases.** When a digest expires, its `digest_item` rows are **deleted**. The digest row itself is retained with its rendered body for audit, but its claim on those updates is gone, so they are owed again next period.
3. **Approved is immutable** (FR-3.30b). Once a digest reaches `approved`, its items are never added to, removed, or re-pointed. A late `task_update` simply has no item for that recipient and is picked up next period.

> The roll-forward query is `task_update` → left join `digest_item` → `digest` filtered to `contact_id` and `state = 'sent'`, which is why `digest_item.task_update_id` is indexed.

---

## 6. Module 4 — Strategy session

### `strategy_template` / `strategy_section` / `strategy_question`

`strategy_template`: `id · tenant_id · name · discipline · version · is_default`

`strategy_section`: `id · tenant_id · template_id · code · title · position · time_budget_minutes` — the seed's 10/25/5/15/5/10 (FR-4.15).

`strategy_question`:

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK · `tenant_id` · `section_id` | |
| `key` | text | **stable identifier that survives every edit** — `U(tenant_id, template_id, key)`. Assigned once at creation and never reused |
| `deleted_at` | timestamptz? | **questions are never hard-deleted** |
| `prompt` | text | may contain merge fields |
| `ask_when` | text | `precall` · `live` — **overridable per question (FR-4.2)** |
| `must_ask` | bool | the seed's ★ |
| `area` | text? | the diagnostic's six areas. **Renamed from `group`**, which is an SQL reserved word |
| `response_schema` | text | `free_text · rating_1_10 · diagnostic_triple · value_pair · agreed_note · path_reaction` (FR-4.3) |
| `is_fractional_observation` | bool | §3 item 4 — shown, never asked aloud (FR-4.17) |
| `has_fractional_note` | bool | enables the private note field |
| `is_financial` | bool | **§9 investment fields — hidden from VA (AC-4.13)** |
| `position` | smallint | |

### `strategy_session`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK · `tenant_id` | |
| `template_snapshot` | jsonb | **the whole template as run (FR-4.5)** — editing the live template never rewrites history |
| `template_id` | FK→`strategy_template` | provenance only |
| `contact_id` / `company_id` | FK / FK? | |
| `visionary_contact_id` | FK→`contact`? | `{Visionary}` (FR-4.9a) |
| `integrator_contact_id` | FK→`contact`? | `{Integrator}`; null renders the graceful note |
| `owner_id` | FK→`user` | `{Fractional name}` |
| `scheduled_at` | timestamptz | `{Session date}` |
| `state` | text | `draft · precall_sent · precall_complete · in_call · complete · converted · lost` |
| `precall_token_hash` / `precall_expires_at` | char(64) / timestamptz | public form, 30 days (FR-4.6) |
| `mirror_goal` / `mirror_unlocks` | text? / text? | accepted values only |
| `proposed_mirror_goal` / `proposed_mirror_unlocks` | text? / text? | Claude's draft, held separately (FR-4.19) |
| `pdf_file_id` | FK→`stored_file`? | |
| `pdf_include_flags` | jsonb | the five exclusion toggles, **all false by default (FR-4.24)** |
| `converted_at` | timestamptz? | |

### `strategy_answer`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK · `tenant_id` · `session_id` | |
| `question_key` | text | **references the key inside `template_snapshot`. There is deliberately no FK to `strategy_question`.** `U(tenant_id, session_id, question_key)` |
| `value` | jsonb | **validated against the `response_schema` recorded in the snapshot (FR-4.3)** |
| `fractional_note` | text? | **never rendered to the prospect or in the PDF** |
| `answered_by` | text | `prospect` · `fractional` |
| `updated_at` | timestamptz | |

The five shapes inside `value`:

| `response_schema` | `value` shape |
|---|---|
| `free_text` | `{"text": "…"}` |
| `rating_1_10` | `{"rating": 7, "comment": "…"}` |
| `diagnostic_triple` | `{"said": "…", "cause": "…", "tried": "…"}` |
| `value_pair` | `{"value": "…", "why": "…"}` |
| `agreed_note` | `{"agreed": true, "notes": "…"}` |
| `path_reaction` | `{"path": "A", "reaction": "…", "risk": "…", "leaning": "…"}` |

#### What actually protects AC-4.12

Two mechanisms, and they are not equal — worth being precise about which one carries the guarantee:

- **`template_snapshot` + `question_key` with no FK is the protection.** A completed session renders entirely from its own snapshot: section order, prompts, `ask_when`, response schemas, `must_ask`, and the `is_financial` flag all come from the frozen jsonb. Deleting a section or rewording a question in the live template cannot cascade, cannot block, and cannot change a byte of what a past session displays — because nothing in the session points at the live rows at all.
- **`strategy_question.deleted_at` + a never-reused `key` is defence in depth**, not the guarantee. It keeps keys stable so that *forward-looking* work — reporting across sessions, diffing a template against a session, seeding a new template from an old one — can still resolve a key to its current question. Without it, a deleted-and-recreated question could reuse a key and quietly change what a historical answer appears to be answering.

Put plainly: the snapshot is why AC-4.12 passes; the soft delete is why cross-session analysis in V1 will not silently lie.

### `strategy_map_row`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK · `tenant_id` · `session_id` | |
| `position` | smallint | reorderable (FR-4.20) |
| `bottleneck` / `root_cause` / `the_fix` | text | |
| `owner_text` | text? | free text — the owner is often the client's Integrator, not a user |
| `horizon` | smallint | 30 · 60 · 90 |
| `measurable` | text? | |
| `mechanics_note` | text? | **"notes / mechanics from experience" — excluded from the PDF by default (FR-4.24.2)** |
| `state` | text | `proposed · accepted · discarded` |
| `ai_call_id` | FK→`ai_call`? | which draft run produced it |
| `converted_to` | text? | `goal` · `project` — the per-row choice (FR-4.28) |

> A row is on the map only when `state = 'accepted'` (FR-4.18). `proposed` rows are the tray.

---

## 7. Module 5 — Meeting ingestion

### `drive_watch`
`id · tenant_id · folder_id · page_token · last_polled_at · last_error?` (FR-5.1).

### `meeting_source_file`
`id · tenant_id · drive_file_id · drive_version · name · mime_type · `**`drive_file_owner_email citext IX`**` · state (recorded|parsing|parsed|skipped|failed) · skip_reason? · fetched_at`

> **`drive_file_owner_email` is captured at ingestion and is load-bearing for permissions**, not metadata: it is the second limb of the CF `proposal-scope` rule in `03_access_matrix.md` — a CF sees a proposal from their *own* meeting even before any participant is matched to a company. — **`U(tenant_id, drive_file_id, drive_version)` is the idempotency guarantee** (FR-5.4).

### `meeting_proposal`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK · `tenant_id` | |
| `source_file_id` | FK→`meeting_source_file` | |
| `meeting_date` / `title` | date / text | |
| `proposed_summary` | text? | **reviewed with the proposal (FR-5.8b, R11a)** |
| `state` | text | `pending · partially_actioned · actioned · rejected · superseded` |
| `ai_call_id` | FK→`ai_call` | |
| `meeting_id` | FK→`meeting`? | set on approval |

### `proposal_item`
**One table holds all three proposal kinds**, because they share a lifecycle (pending → approved/rejected) and a review screen.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK · `tenant_id` · `proposal_id` | |
| `kind` | text | `participant · action_item · deliverable` |
| `state` | text | `pending · approved · rejected` — **independently actionable (FR-5.15)** |
| `source_excerpt` | text | **the passage it was drawn from (FR-5.14)** |
| `payload` | jsonb | shape by `kind`, below |
| `created_record_type` / `created_record_id` | text? / UUID? | what approval produced |
| `actioned_by` / `actioned_at` | FK→`user`? / timestamptz? | |

**`payload` by kind:**

```jsonc
// participant  (FR-5.9, 5.9a)
{
  "parsed_name": "Dana Reyes",
  "parsed_email": "dana@acme.com",
  "parsed_title": "COO",
  "parsed_company": "Acme Facilities",
  "proposed_contact_type": "prospect",        // reviewer confirms or changes (FR-5.9a)
  "new_contact_candidate": { … },             // the "create new" path
  "existing_candidates": [                    // ranked; may be empty
    { "contact_id": "…", "match_reason": "email", "rank": 1, "confidence": 0.98 },
    { "contact_id": "…", "match_reason": "email_domain_and_name", "rank": 2, "confidence": 0.71 },
    { "contact_id": "…", "match_reason": "name_only", "rank": 3, "confidence": 0.40 }
  ],
  "service_categories": []                    // captured inline when type = vendor (FR-5.9c)
}

// action_item  (FR-5.12)
{ "text": "Send Q3 margin breakdown", "proposed_owner_contact_id": "…", "proposed_due_date": "2026-09-19" }

// deliverable  (FR-5.13)
{ "text": "Rebuild the inspection checklist",
  "proposed_due_date": "2026-10-01",
  "proposed_stakeholders": [ { "contact_id": "…", "cadence": "weekly" } ] }
```

> **A participant proposal always carries both paths** — `new_contact_candidate` *and* `existing_candidates` — so the reviewer can always reject every match and create new (FR-5.11, AC-5.4). `match_reason` is one of `email`, `email_domain_and_name`, `name_only`, in that ranking order (FR-5.10).

### `meeting`
Created on approval (FR-5.8a). **This is the "update their profile with the meeting notes" requirement.**

`id · tenant_id · source_file_id · proposal_id · meeting_date · title · summary? · client_company_id? · created_at`

### `meeting_participant`
`id · tenant_id · meeting_id · contact_id` — `U(tenant_id, meeting_id, contact_id)`. **The join that puts the meeting on every approved participant's timeline.**

---

## 8. Module 6 — Communication

### `email_thread`
`id · tenant_id · thread_token (U, IX) · contact_id? · client_company_id? · gmail_thread_id? (IX) · subject · last_message_at`

> Two match keys, per FR-6.6: `thread_token` (app mail and Tier 1 personal sends) and `gmail_thread_id` (Tier 2 ingestion).

### `email_message`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK · `tenant_id` · `thread_id` | |
| `direction` | text | `outbound` · `inbound` |
| `provider` / `provider_message_id` | text / text | **`U(tenant_id, provider, provider_message_id)` — the idempotency guard (FR-6.12)** |
| `from_address` / `to_addresses` / `cc_addresses` | citext / citext[] / citext[] | |
| `subject` / `body_html` / `body_text` | text | |
| `body_stripped` | text? | quoted history and signature removed for display (FR-6.9) |
| `raw` | jsonb | full payload retained |
| `contact_id` | FK→`contact`? | |
| `matched_by` | text | `thread_token · gmail_thread_id · sender_email · manual` |
| `outbox_message_id` | FK→`outbox_message`? | links a send back to its Outbox row |
| `received_at` / `sent_at` | timestamptz? | |

### `email_attachment`
`id · tenant_id · message_id · stored_file_id · filename`.

### `unmatched_inbound`
FR-6.8 — **never dropped.**

`id · tenant_id · email_message_id · state (pending|filed|discarded) · filed_to_contact_id? · filed_by? · filed_at?`

### `gmail_connection`
Per user (C2, F19).

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK · `tenant_id` · `user_id` | |
| `email_address` | citext | the address sends come from |
| `scopes` | text[] | `gmail.send` always; `gmail.readonly` **only when Tier 2 is connected (FR-6.3g)** |
| `tier2_enabled` | bool | opt-in |
| `last_polled_at` | timestamptz? | 15-minute thread poll |
| `secret_id` | FK→`tenant_secret` | the encrypted refresh token |

> **A VA has no row here.** The connect action is not offered and the endpoint returns 403 (FR-6.3h, H7).

---

## 9. Background work

### `django_q_*`
Django-Q2's own tables on the ORM broker (A2). Not ours, but they live in this database — which is why the restore runbook flushes the queue before starting `qcluster` (A2 consequence 2).

### `scheduled_job_run`
Thin wrapper for the health screen (FR-5.7): `id · tenant_id · job_name · started_at · finished_at? · succeeded · error? · items_processed`.

---

## 10. Walkthrough: one prospect, CSV import to portal tasks

Every row created, in order. This is the test of whether the schema actually holds the product.

**Cast:** Dana Reyes, COO of Acme Facilities. Imported from a CSV, runs a strategy session, converts, and ends up watching tasks in the portal.

---

**Step 1 — CSV import (FR-1.26–32)**

You upload `contacts_2026.csv` and map the columns.

- `import_mapping_profile` — 1 row, "Standard export", reusable next time.
- `import_batch` — 1 row, `status = dry_run`, `counts = {create: 196, update: 3, skip: 0, error: 1}`.
- `import_row` — 200 rows, one per CSV line, each with `raw` and an `outcome`.

**Nothing else exists yet.** You read the dry run, then commit.

- `import_batch.status → committed`
- `company` — 1 row, *Acme Facilities*, `is_client_company = false`.
- `company_domain` — 1 row, `acme.com`.
- `contact` — 1 row, *Dana Reyes*, `stage_id → contact`, `owner_id → you`.
- `contact_email` — 1 row, `dana@acme.com`, `is_primary = true`.
- `contact_type_link` — 1 row → `prospect`.
- `note` — 1 row, from the CSV's notes column: `source = 'import'`, `contact_id → Dana` (§12.2). Her `contact.background` holds the one-line "met at the facilities roundtable" instead.
- `import_row` for Dana gets `contact_id` and `previous_values = null` (a create, so rollback deletes rather than reverts).
- `audit_event` — `import.committed`.

---

**Step 2 — Dana becomes a lead, then a qualified lead (FR-1.6–1.14)**

You move her to `lead`.

- `stage_change` — 1 row, `contact → lead`.
- `stage_automation` matching `to_stage = lead` fires `create_task`:
  - `task` — 1 row, *"Send intro packet"*, `client_company_id = null` (not a client yet), due in 3 days.
  - `task_update` — 1 row, `kind = created`.

She responds well; you move her to `qualified_lead`.

- `stage_change` — 1 row.
- A `draft_email` rule fires: **`outbox_message` — 1 row, `state = pending_approval`**, `producer = stage_rule`, `send_by = now + 7 days` (FR-1.12).
- **Nothing has been emailed.** You approve it the next morning → `state → sent`, `sent_at` set, `provider_message_id` recorded.
- `email_thread` — 1 row with a `thread_token`; `email_message` — 1 outbound row.
- `audit_event` — `outbox.approved`.

---

**Step 3 — Strategy session, pre-call (FR-4.6–4.13)**

You schedule the session for Dana.

- `strategy_session` — 1 row. `template_snapshot` freezes the nine-section Operations template **as it exists today** (FR-4.5). `contact_id → Dana`, `company_id → Acme`, `visionary_contact_id → Dana` (defaulted from `company.primary_contact_id`, FR-4.9b), `integrator_contact_id = null`, `precall_token_hash` set, expires in 30 days.
- `outbox_message` — 1 row for the form invitation.

Dana fills in the form. She answers Section 1 (7 items) and Section 2 (6 ratings).

- `strategy_answer` — **13 rows**, `answered_by = prospect`.
  - Section 1 rows carry `{"text": "…"}`.
  - Section 2 rows carry `{"rating": 4, "comment": "…"}` — Data lowest at 4.
- The average and the "look here first" flag on Data are **computed on read** (FR-4.12). No row stores them.

Because Acme has **no Integrator**, every `{Integrator}` question renders the "no Integrator identified" note (FR-4.9) — again, no row; it is a render-time resolution against `integrator_contact_id = null`.

---

**Step 4 — The live call (FR-4.14–4.22)**

You run the 75-minute session. Diagnostic answers land in the three-field shape.

- `strategy_answer` — ~14 more rows, `answered_by = fractional`, `value = {"said": …, "cause": …, "tried": …}`. Two carry a `fractional_note` (private).

You finish the **People & labor** area, which triggers a draft run automatically (FR-4.18a).

- `ai_call` — 1 row, `purpose = strategy_rows`, `trigger = auto`, tokens and cost recorded.
- `strategy_map_row` — **4 rows, `state = proposed`**. The map is still empty.

You accept two, edit-and-accept a third, discard the fourth.

- 3 rows → `state = accepted` (one with your edited text); 1 → `discarded`.

Claude drafts the mirror.

- `ai_call` — 1 row, `purpose = strategy_mirror`.
- `strategy_session.proposed_mirror_goal` / `proposed_mirror_unlocks` set. **`mirror_goal` and `mirror_unlocks` are still null.** You edit and accept → the accepted values are copied across (FR-4.19).

Sections 7, 8, 9 are captured live.

- `strategy_answer` — 3 `value_pair` rows, 2 `path_reaction` rows, 9 `agreed_note` rows. The §9 investment row has `is_financial = true` on its question, so a VA never sees it (AC-4.13).

---

**Step 5 — The PDF (FR-4.23–4.27)**

You generate the PDF.

- `stored_file` — 1 row, `purpose = session_pdf`.
- `strategy_session.pdf_include_flags` — **all five false**, so the two `fractional_note` values, the three `mechanics_note` values, the §3 observation, and **all of §9** are absent from the rendered file (FR-4.24).

You review the preview and click send.

- **`outbox_message` — 1 row written directly as `state = sent`** (FR-1.15b) — the click *is* the approval.
- `outbox_attachment` — 1 row → the PDF.
- `audit_event` — `strategy.pdf_sent`.

---

**Step 6 — Conversion (FR-4.28–4.32, FR-1.6a)**

Dana signs. You convert.

You choose per row: 2 rows → Goal, 1 row → Project.

- `goal` — 2 rows, each with `source_map_row_id` **pointing back at the map row** (FR-4.31).
- `project` — 1 row, likewise.
- `strategy_map_row.converted_to` set on all three.
- `strategy_session.state → converted`, `converted_at` set.

The client invariant fires (FR-1.6a.1):

- `stage_change` — 1 row, `qualified_lead → client`.
- `contact_type_link` — **1 new row** → `client`. The existing `prospect` link **remains** (FR-1.6a.2).
- `company.is_client_company → true`.
- `audit_event` — 3 rows: `stage.changed`, `contact_type.derived`, `company.flagged`.

You assign a CF to the account.

- `client_assignment` — 1 row (FR-1.9a). From here, that CF sees Acme's contacts.

---

**Step 7 — Portal access (FR-3.33c–33h)**

You set `company.seat_count = 3` and grant Dana access.

- `user` — 1 row, `dana@acme.com`, password unusable (C4).
- `membership` — 1 row: `role = FCC` (she is `company.primary_contact`), `client_company_id → Acme`, `contact_id → Dana`. **One seat consumed** — seats are counted as live `membership` rows, not stored as a counter, so the count cannot drift.
- `magic_link_token` — 1 row, 20-minute TTL.
- **`outbox_message` — 1 row written directly as `sent`**, `producer = magic_link`, sent synchronously in the request (A2a).
- `audit_event` — `portal.granted`.

Dana clicks the link, lands on the confirm page, POSTs, and gets a 30-day session. `magic_link_token.used_at` is set.

---

**Step 8 — Work, and the first digest (FR-3.15–3.33)**

Under the Goal from the map row *"Supervisor overload"*, you add two tasks.

- `task` — 2 rows, `client_company_id → Acme`, `is_client_visible = true`, one carrying `source_map_row_id`.
- `task_update` — 2 rows, `kind = created`.

You add **two** stakeholders:

- `stakeholder` — row A: `contact_id → Dana`, **`goal_id` set**, `cadence = weekly`. **It points at her Contact, not her User** (FR-3.20) — she would receive this even without portal access.
- `stakeholder` — row B: `contact_id → Marcus (site manager)`, **`task_id → task 1`**, `cadence = every_update`. He wants to know the moment task 1 moves; he does not want the whole goal every Friday.

Both are stakeholders on task 1 — Dana through the Goal, Marcus directly. **This is the case that broke the earlier design**, and it is the reason consumption lives in `digest_item`.

Through the week:

- You move task 1 to `in_progress` and supply the prompted line. → **`task_update` U1**, `kind = status_changed`, `actor_id = you`, `source = 'user'`, `client_facing_line = "Inspections now run from the app, so you'll see per-site coverage from Monday."`
- You move task 2 to `waiting_on_client`, skipping the line. → `task_update`, `client_facing_line = null`.
- You post an internal comment. → `comment` with **`visibility = internal`** (the default, FR-3.12a) and a `task_update`, `kind = comment_added`. **This one is excluded from the digest** (FR-3.19).

**Tuesday 14:30** — Marcus's quiet window on U1 closes (FR-3.28a). `every_update` generates immediately, not 24 hours ahead.

- `digest` — **row D1**: `contact_id → Marcus`, `cadence = every_update`, `period_start = Tuesday 14:00`, `state = pending`, `is_ai_generated` derived from `company.digest_ai_prose`.
- `digest_item` — **1 row: `digest_id → D1`, `task_update_id → U1`, `stakeholder_id → row B`.**
- `hold_all_digests` is ON, so it waits. You approve Tuesday evening → `D1.state → sent`.
- **U1 is now consumed for Marcus. It is not consumed for Dana** — no `digest_item` joins U1 to any sent digest of hers. One update, two independent claims.

**Thursday 08:00** — Dana's weekly generation (FR-3.28).

- `digest` — **row D2**: `contact_id → Dana`, `cadence = weekly`, `period_start` = last Friday, `state = pending`, `send_window_at = Friday 08:00`.
  Unique on `(tenant_id, contact_id, cadence, period_start)` — so even though Dana also holds a task-level stakeholder row elsewhere in the goal, she gets **one** Friday email, not two.
- `digest_item` — **2 rows**: U1 (via `stakeholder` row A, the Goal attachment) and U2 (task 2 → `waiting_on_client`).
  **U1 appears in both D1 and D2.** Different digests, different recipients, one update — which is exactly what a single `digest_id` column could not express.
- The internal comment's `task_update` gets **no** `digest_item` (FR-3.19).
- `ai_call` — 1 row, `purpose = digest_prose`.

**Thursday 14:00** — you mark task 2 done.

- `task_update` — **U3**.
- D2 is **flagged stale** (FR-3.30a): `is_stale = true`, `stale_reason` names the change. You click regenerate → the body is rebuilt and `digest_item` gains a third row for U3. D1 is untouched: it is already `sent`, and a sent digest's items are immutable.

**Friday 08:00** — `hold_all_digests` is ON, so D2 waits. You approve at 08:40.

- `D2.state → approved → sent`, `approved_by` set. Its three `digest_item` rows are now frozen.
- **`outbox_message` — 1 row**, `producer = digest`, `state = sent`.
- `stakeholder.last_notified_at` updated on row A.
- `audit_event` — `digest.approved`.

*Had you never approved D2, it would expire: its three `digest_item` rows are **deleted**, U1, U2 and U3 become owed to Dana again, and next week's digest picks them up. Marcus's D1 is unaffected — his claim on U1 was settled on Tuesday.*

Dana clicks the footer link to switch to monthly.

- `stakeholder_token` — 1 row, 30-day TTL, verified without a session (FR-3.33a).
- `stakeholder.cadence → monthly`; `audit_event` — `stakeholder.cadence_changed`.

---

**Step 9 — Dana uses it as her own tool (FR-3.35–3.37)**

She creates a task for her site manager, whom you granted ECC access earlier.

- `task` — 1 row, `created_by_client = true`, `assignee_id →` the ECC's user, `client_company_id → Acme`.
- `task_update` — 1 row, `is_client_actor = true`.
- **No review queue** (FR-3.36) — she is a person writing about her own work.
- A notification to the tenant owner batches on the 30-minute quiet window.

---

### Final tally for Dana

| Table | Rows |
|---|---|
| `company` · `company_domain` | 1 · 1 |
| `contact` · `contact_email` · `contact_type_link` | 1 · 1 · **2** (prospect + client) |
| `stage_change` | 3 |
| `client_assignment` | 1 |
| `user` · `membership` | 1 · 1 (FCC, 1 seat) |
| `strategy_session` · `strategy_answer` · `strategy_map_row` | 1 · ~41 · 4 (3 accepted, 1 discarded) |
| `goal` · `project` · `task` | 2 · 1 · 4 |
| `task_update` | 8 |
| `stakeholder` | 2 (Dana @ goal/weekly, Marcus @ task/every_update) |
| `digest` · `digest_item` | 2 (D1 Marcus, D2 Dana) · 4 (U1 twice, U2, U3) |
| `note` | 1 (from the CSV notes column) |
| `outbox_message` | 6 (3 approved, 3 direct-to-sent) |
| `ai_call` | 4 |
| `audit_event` | ~15 |

**What the walkthrough proves:** the client invariant derives one way and keeps the `prospect` type; a stakeholder needs no login; the map row survives as a back-link on the Goal all the way into the digest; **one `task_update` is claimed independently by two recipients through `digest_item`, with expiry releasing one claim without touching the other**; Dana gets one Friday email despite holding stakeholder rows at two levels; and every one of the six `outbox_message` rows is in the send log whether or not it passed through approval.

---

## 11. Notes for the migration

1. **Migration order** is: `tenant` → `user`/`membership` → `company` (no `primary_contact_id`) → `contact` → add `company.primary_contact_id` → everything else. The one FK cycle in the schema is broken by adding that column last.
2. **Seed data** in a separate data migration: `pipeline_stage` (6), `contact_type` (5), the Operations `strategy_template` from `strategy_session_seed.md`, and the worked example map row (FR-4.21).
3. **`search_vector` columns** are maintained by triggers, with GIN indexes, and Dana's PIN'd notes are excluded at index time, not filtered at query time (FR-2.11) — a filter someone can forget is not an access control.
4. **Every table in §1–§8 registers in the tenant-isolation registry** (B3). The meta-test fails on an unregistered model, which is what keeps this document and the code from drifting apart.

---

## 12. Review outcome

All three items marked, and eleven further changes applied from the data-model review.

**Rulings:**

- **12.1 — Approved.** The same Contact may hold stakeholder rows at several levels; most specific wins for cadence. This is what made change 2 (keying digests by recipient) necessary.
- **12.2 — Applied.** `contact.notes` is renamed **`contact.background`** — a short "who this is / how we met" line. A CSV notes column now becomes a real `note` row with `source = 'import'`. One concept called a note, in one table.
- **12.3 — Approved.** Seats are counted from live memberships, never stored.

**Changes applied:**

| # | Change | Where |
|---|---|---|
| 1 | `digest_item` join table replaces `task_update.digest_id` | §5 `digest_item`, §10 Step 8 |
| 2 | `digest` keyed `(tenant_id, contact_id, cadence, period_start)`; `stakeholder_id` dropped | §5 `digest` |
| 3 | `client_owner_contact_id` on goal / project / task, with mapping table | §5 |
| 4 | `question_key` + snapshot as source of truth; `strategy_question.key` + `deleted_at` | §6 |
| 5 | Partial unique index for one Anthropic key per tenant | §1 `tenant_secret` |
| 6 | `company.digest_ai_prose` + `tenant.digest_ai_prose_default` | §1, §2 |
| 7 | `status_override`; effective status derived at read time | §5 |
| 8 | `task_update.actor_id` nullable, plus `source` / `source_id` | §5 |
| 9 | `precall_invite` and `manual` producers, with role-dependent routing | §3 |
| 10 | `strategy_question.group` → `area` | §6 |
| 11 | VA may send `precall_invite` directly (H7a) | §3, `00_assumptions.md`, `03_access_matrix.md` |

**On change 1 — this was the significant one.** The single `digest_id` column was wrong in a way that would have surfaced only with a second stakeholder on the same entity: one column cannot be consumed for Dana on weekly and unconsumed for Marcus on `every_update` at the same time. Consumption is per recipient, so it belongs in a join. §10 Step 8 now runs both stakeholders through one `task_update` to show the mechanism working, including what expiry releases and what it leaves alone.

**On change 2** — with §12.1 approved, per-attachment keying would have put two emails in one inbox on the same Friday. Keying on the recipient fixes that, while leaving `cadence` in the key so the genuinely-different case (weekly across a goal, `every_update` on one urgent task) still produces two appropriately-timed emails rather than being wrongly collapsed.

**Status:** `02_data_model.md` is complete. Proceeding to `03_access_matrix.md`.
