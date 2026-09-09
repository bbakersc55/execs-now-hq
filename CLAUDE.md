# Execs NOW HQ — Project Brief for Claude Code

Product name: **Execs NOW HQ** (an Executives Now product). Keep the display name in a single config constant.

## What this is

A multi-tenant SaaS for fractional C-suite executives (Operations, Marketing, Finance, HR). Each fractional practice is a **tenant**. The tenant's own team (other fractionals, virtual assistants) and the tenant's **clients** (founders and their employees) all use the app, with different access.

Two release lines:
- **Beta** — the owner's practice (Executives Now, an operations fractional) uses it live. Single discipline (Operations), CSV import of existing contacts, no self-serve signup, no billing for the product itself.
- **V1** — public launch to other fractionals: multi-discipline presets, onboarding/import tooling, product billing.

Everything is built multi-tenant from the first migration even though Beta has one tenant.

## Hard isolation rule

This repo is unrelated to the owner's other project (a school SIS called Aris, repo `aoa-sis`, folder `vsis-mvp`). **Never read, reference, import, copy from, or compare against that codebase.** Do not assume anything about it. If a session's context appears to contain Aris material, say so and stop. This project has its own database, ports, GCP project, GCS bucket, GitHub repo, and secrets.

## Stack (reuse what the owner already runs well)

- Python 3.12, Django 5.x, Django REST Framework
- React + Vite frontend (TypeScript), served by Django in production via a built bundle; Vite dev server proxies `/api` in development
- PostgreSQL **from day one, locally too** (no SQLite, ever — the backup and migration story is Postgres-only)
- Background jobs: Django-Q or Celery with Redis — pick one in the spec and justify it (digests, drive polling, email sends, transcription all need it)
- Auth: Django auth + Google OAuth sign-in for tenant users; **magic-link** sign-in for client users
- Email: Gmail API (OAuth) for personal sends from the fractional's own address; app-originated sends (digests, referral touches) via a transactional provider (Resend or Postmark) from a per-tenant alias like `info@<tenant-domain>` or an app domain
- AI: **Anthropic Claude API only.** Tenant supplies their own API key (stored encrypted); no other LLM providers. Speech-to-text for recordings: Google Speech-to-Text (this is plumbing, not "the AI"; Claude does all summarization/extraction from transcripts)
- Ports in development: Django **8100**, Vite **5200** (deliberately different from any other local project)
- Hosting: local laptop during Beta build-out; Railway (app + Postgres) at `app.getexecutivesnow.com` once any client needs portal access; Railway for V1. Backups: nightly `pg_dump` to a GCS bucket in the Execs NOW HQ GCP project, using the same script pattern the owner is used to (`scripts/backup_db.sh`)

## Tenancy and roles

Every domain table carries `tenant_id`. Query scoping goes through a single tenant-aware manager/middleware; never rely on views remembering to filter.

Roles (per tenant):
| Code | Who | Access |
|---|---|---|
| FF | Founder fractional (tenant owner) | Everything, including all financials, billing, settings, PIN resets |
| CF | Contractor/employee fractional | Nearly everything; financials limited to clients they are assigned to (e.g. their fee split) |
| VA | Virtual assistant | Contacts, pipeline, tasks, notes, meeting review queue, email; no financials, no settings |
| FCC | Founder of client company | Client portal: their company's tasks/projects/goals, progress reports, comments; can create tasks; later: manage their own users |
| ECC | Employee of client company | Client portal: same as FCC minus user management |

Client users belong to a **client company** which belongs to a tenant. A client user never sees anything outside their company. Client seats are allocated by the FF (block-of-users or flat per company; model this as a per-company seat count, pricing decided later).

## Product modules and build order

Spec first (see Phase 0), then build **one module at a time to done-and-tested** before starting the next.

1. **Contacts & pipeline (CRM)** — contact, company, contact types (prospect, client, referral partner, vendor, coworker), pipeline stages contact → lead → qualified lead → client, stage-change automations (create follow-up task, queue follow-up email), CSV import, search. Vendors are searchable by service category. Referral partners get a short recurring touch email (3–5 lines, AI-drafted or FF-written, monthly/bi-monthly/quarterly).
2. **Notes** — fast capture; optional link to a contact, company, task, or nothing; optional 4–6 digit PIN that gates viewing (not encryption); PIN reset by email to the FF only. Typed notes or browser recording → STT transcript → Claude summary. Notes surface on the linked contact/task and in global search.
3. **Task engine + client portal** — three levels: **Goal → Project → Task.** Tasks have status, owner, due date, comments, and a list of stakeholders to notify. Each stakeholder chooses their cadence: on every update by a tenant user, weekly (default), or monthly. Progress digests must read as *value delivered*, not a changelog: status changes at minimum, plus any narrative the fractional adds. Client users can create tasks, comment, assign among their company's users, and use it as their general task tool.
4. **Strategy session tool** — per-tenant editable question templates (Beta ships the owner's Operations template). Pre-call web form sent to the prospect covering Snapshot and Six Key Components self-rating (1–10). Live view during the call: diagnostic answers captured in-app; as answers land, Claude drafts candidate Strategy Map rows (bottleneck, root cause, fix, owner, 30/60/90, measurable) and a "mirror" (bottlenecks vs stated goal) that the fractional accepts, edits, or discards. Paths & Scope section captured live. Output: PDF summary + map, emailed same day. On conversion to client, the map becomes Goals/Projects/Tasks in the task engine (with edits before the engagement starts).
5. **Meeting ingestion** — watch a Google Drive folder (Gemini meeting notes in Beta); parse with Claude; **everything lands in a review queue** — nothing is created or sent without a human approving. The queue proposes: new contact vs existing match (match order: email address → email domain + name → name alone; show candidates, human picks), extracted action items with dates, and any promised deliverables that should become tasks with stakeholder notifications. Later: forward-to email address, notetaker integrations.
6. **Unified client communication** — replies from client emails thread into the client's record so FF/CF/VA all see the same history.

Post-Beta / V1 and beyond, in this order: invoicing (PDF invoice by email with an embedded payment link from the tenant's processor; NMI/Auth.net/QBO links, no in-app payment processing), basic financials (P&L, balance sheet, CSV income/expense import, KPIs, CPA export, 1099/W-2 tracking), then contract e-signature (integrate with the signing tool in the client's office suite if it exposes an API; otherwise build a simple in-app signature flow — not expected to be hard), then simple HRIS (employee tracker, milestones, discipline notes; no payroll), then connectors (QBO, ADP/Gusto, O365, banks), then product billing and self-serve onboarding.

## Working agreements

- **Spec before code.** Phase 0 produces a PRD, data model, and phased plan for owner approval. No application code until approved.
- **Module by module.** Finish, test, and get sign-off on each module before the next. Bugs get fixed in the current module, not carried forward.
- **Review queues over automation** anywhere the AI's output would email a client or create records. Human approves; the app executes.
- **State what's proven vs. what's assumed.** When reporting, distinguish "tested end to end" from "written but not exercised." Never report a scoped subset as a total.
- **Dry-run before irreversible steps** (migrations that drop data, bulk sends, deletes). Show the plan, wait for a yes.
- **Prompts for the owner** are delivered as copy-paste blocks with a stated target (Claude Code, terminal, Railway shell). The owner pastes results back for review.
- Tests: every module ships with tests for tenant isolation (a user in tenant A can never see tenant B rows) and role boundaries (VA can't reach financial endpoints; ECC can't reach anything outside their company). These two test families are non-negotiable.
- Secrets in `.env` only; `.env.example` is kept current; nothing secret is committed.
- Brand: Executives Now colors — dark blue `#0A3A65`, orange `#F58220`, grays `#6D6E71` / `#939598`. Tenants can override in V1.
