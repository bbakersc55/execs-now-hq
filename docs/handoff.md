# Execs NOW HQ — handoff to the next chat

Written 2026-10-03, replacing the 2026-09-22 version. Upload this at the
start of the next chat with: "Read this handoff, then pick up where it leaves
off." The specs in `docs/` are the source of truth; this covers what they
don't, and what changed since 9/30.

## What this is, in one paragraph

Execs NOW HQ is a multi-tenant SaaS for fractional executives, built by the
owner (Bryan Baker, Executives Now, an operations fractional; Noble Rose LLC)
with Claude Code (CC) doing the coding and this chat doing product direction,
review and the prompts CC receives. Django 5.2 / DRF / Postgres / Django-Q2
(ORM broker, no Redis); React + Vite + TypeScript; WeasyPrint PDFs; the Claude
API; Google (Gmail send and read, Drive read, Speech-to-Text); GCS for files
and backups. **Production runs on Railway at app.getexecutivesnow.com since
the cutover on 9/30.** Repo github.com/bbakersc55/execs-now-hq: work on
`dev`, release to `main`.

## The three environments, and their rules

| | Production | Demo | Laptop |
|---|---|---|---|
| Where | app.getexecutivesnow.com (Railway project `execs-now-hq-live-app-no-testing`) | demo.getexecutivesnow.com (Railway project `execs-now-hq-demo`) | `~/projects/execs-now-hq` |
| Code | `main`, only on the word **"release"**, full suite green | `dev`, every push | `dev` |
| Data | the real practice | a fictional practice (Summit Operations Partners), seeded | **`execsnowhq_local`**: a scrubbed copy of production (B7) |
| Worker | the Railway `qcluster` service | **none**; the demo sends nothing and reads no mailbox or Drive | a local qcluster is fine on `execsnowhq_local`; never on `execsnowhq_dev` |
| Migrations | **only by "Releasing a migration"** (runbook): confirm the newest backup, release, apply in the waiting worker with `railway ssh --service qcluster -- python manage.py migrate`, redeploy web (`railway redeploy --service execs-now-hq -y`) | applied by web at start (`APP_ENVIRONMENT=demo` only) | CC applies when `.env` names `execsnowhq_local` and the suite is green; no backup needed |
| Backups | nightly 08:00 UTC (02:00 MT), Railway cron → `gs://execs-now-hq-db-backups/execsnowhq_prod_*` | none needed | none needed: `./scripts/refresh_dev_from_prod.sh` rebuilds it from the newest production dump, scrubbed |
| Files | `gs://execs-now-hq-media` | its own demo bucket (refuses production's) | `STORAGE_BACKEND=local` (`media/`): production's files are not on the laptop |

- **`execsnowhq_dev`** (the laptop's pre-cutover database) is the fallback until
  runbook **C12, about 10/14**. Then the owner says so and it's deleted (dry
  run first). Nothing points at it.
- **The release sequence is proven** (Release 2, 10/3, P1 + P2, 7
  migrations): push to new code serving took **4 min 22 s**, and the **old web
  kept serving throughout** (polled every 5 s, every response 200). The worker
  paused about 68 s. Recorded in `docs/phase7_cutover_runbook.md`.
- Laptop session (five tabs): see `docs/05_dev_environment.md` §8. Tab 1 runs
  `gcloud config configurations activate execs-now-hq`, `git pull`, the
  installs, `migrate` and `ensure_schedules`; then runserver 8100, qcluster,
  Vite 5200 and Mailpit 8125. The old daily `backup_db.sh` is no longer part
  of it.

## Where it stands

| | State |
|---|---|
| Modules 0.5–6 | Built and in use; details below in "Open threads" |
| Phase 7 cutover | Done 9/30 (Release 1); B7 laptop move done 10/2 |
| **P1** vocabulary, roles, branding | **Released 10/3** |
| **P2** Practices admin and onboarding | **Released 10/3**, except creating Blue Sky |
| P3 strategy template builder and session v3 | **Not started**; spec not yet written |
| P4 billing | **Spec written** (`docs/p4_billing.md`), ten decisions open, no code |
| Microsoft 365 transport | **Spec written** (`docs/m365_transport.md`), seven decisions open, no code |
| Backlog, built 10/3, **not released** | dashboard blocks drag across rows; "Not duplicates" on Merge duplicates (migration `crm 0031`); remove an accepted diagnostic question |

Tests on `dev` as of 10/3: **2076 backend, 538 frontend**. The
tenant-isolation and role-boundary families are registries that fail on an
unregistered model; the isolation family now includes the platform owner.

### P1 in brief (`docs/p1_practices_vocabulary_branding.md`)

- **Vocabulary:** a tenant is a **Practice**. Roles are shown by name:
  practice owner (FF), associate (CF), assistant (VA), client owner (FCC),
  client team member (ECC). Codes stay in code and data. Guard tests fail on a
  role code or "tenant" in readable text.
- **Branding per practice** (Settings → Branding, practice owner only): display
  name, logo, mark (favicon and email sign-off), primary and accent colors,
  email footer.
  - **Contrast rules:** primary vs white ≥ 4.5 and accent vs primary ≥ 3
    block a save; accent vs white only warns, and the accent is never used
    for text on white.
  - **Unbranded default:** an unbranded practice shows its name over neutral
    grays, with an initials mark.
  - **Where it applies:** the portal, client emails and PDFs. Staff screens
    keep the product look and show the practice name under the wordmark.
- **The product favicon** comes from `assets/brand/mark-transparent.png`,
  derived from the owner's `mark.png` (original kept).

### P2 in brief (`docs/p2_practices_admin_onboarding.md`)

- **Platform owner** = the owner's own sign-in (set in production 10/3 with
  `set_platform_owner`). The sidebar switch goes between "Executives Now" and
  "Practices". In the Practices area **no practice is bound**: it shows each
  practice's record and totals, and the feedback staff send, never anything
  inside a practice (`docs/data_and_the_platform_owner.md`).
- **Practices:**
  - **Create:** sets your defaults (AI $50 a month and $5 a day unattended,
    digests held, no strategy template, neutral brand, never Executives Now's
    addresses).
  - **Invite owner:** sends only when you press it, and is refused while the
    practice's Google client isn't set up.
  - **Archive / unarchive:** archiving signs everyone out, stops the jobs and
    keeps the data.
- **Signed-out pages** name no practice. Only an emailed link names one
  (`?via=` token), and the tab shows the product icon until the practice is
  known.
- **The beta agreement** (`docs/legal/beta_agreement_v1.md`) gates a practice
  owner on the server until accepted; the acceptance records a hash of the
  text.
- **Getting started:** a seven-item checklist on the practice owner's
  dashboard, computed from the practice's own data.
- **Feedback button** on every staff screen; it goes to the platform owner.
- **Two Google OAuth clients** (D1):
  - **Executives Now** keeps its Internal client.
  - **Outside practices** use a second client, External/Testing, in a new GCP
    project: staff are added as test users, and connections expire every 7
    days until Google verifies the app.
  - **Staff sign-in is email-first:** the address decides which client.

## Blocked on the owner

1. **Blue Sky Business Consulting LLC** (display name "Blue Sky Business
   Consulting", blueskybizconsulting.com, owner Shawn): created through
   Practices → Add a practice **when Shawn's email arrives**. Inviting him also
   needs steps 1–6 of the Google verification plan (the External client and its
   two variables in Railway, Shawn as a test user).
2. **Google verification** (`docs/google_verification.md`), the owner's steps:
   - Set up the new GCP project and verify `getexecutivesnow.com` in Search
     Console.
   - Publish the homepage and privacy policy (both drafted; have a lawyer
     read the policy).
   - Configure the consent screen and the OAuth client; add test users.
   - Record the demo video (script drafted) and submit with the drafted scope
     justifications.
   - Answer Google's emails, then the annual CASA assessment for the
     restricted scopes, then publish.
   - Scope classifications and costs are marked to confirm in the console.
3. **P4 and Microsoft 365 decisions** (the tables at the end of each spec).
4. **"Release"** for the three backlog items.
5. **C12** (about 10/14): say the word, and `execsnowhq_dev` is deleted with a
   dry run.

## Rules and decisions that live outside the repo docs (or are easy to miss)

- **Every AI output and every client email goes through a human.** Review
  queues everywhere; `hold_all_digests` ON; magic links and PIN resets are the
  deliberate direct sends. Platform mail (invitations, feedback notices) goes
  through Executives Now's Gmail and its Outbox.
- **Nothing sends without the full body on screen** (incident 9/22). **A
  rewording never changes a question's shape.**
- **White-label:** a client never sees the product's name. Signed-out pages
  show the product icon but no product name; a practice's own surfaces wear its
  brand.
- **Migrations:** SQL shown before generating, always.
  - **Laptop:** applied by CC on `execsnowhq_local` once the suite is green,
    destructive or not.
  - **Production:** only through the release sequence, after that day's
    backup.
  - **Demo:** migrates itself at start.
  - Never a migrating start command for production.
- **Branches:** work on `dev`; `main` only on "release" with the full suite
  green at the merged commit.
- **Snapshot rule:** a strategy session freezes its template at Start.
- **Goals → Projects → Tasks**, three levels; clients create tasks and projects,
  never goals. **Percent-of-tasks-done is never a headline.**
- **Stakeholders are contacts**, not users; digests reach contacts without
  logins.
- **AC-3.5 faithfulness:** every Claude narrative asserts nothing absent from
  its input.

## Gotchas that cost time before

- **qcluster does not reload** on code changes; restart it after a backend
  commit or migrate. `runserver` does reload: a model change breaks the dev
  server until its migration is applied.
- **Production's web service is named `execs-now-hq`**, not `web`.
- `railway ssh` reaches only an active instance. The waiting worker is how a
  migration reaches production; a shell in old web would run old code.
- **A refused web deployment shows FAILED, and the old one keeps serving** until
  web is redeployed after the migration.
- Hard-reload Vite before calling a frontend change broken. `pip install`
  after pulls.
- On the laptop, mail goes to Mailpit unless the address is on the dev
  allow-list (`.env` plus Email settings).
- **Google OAuth:** the Internal consent screen accepts getexecutivesnow.com
  only. The External client is for everyone else and has Testing mode's 7-day
  expiry until verified. `gmail.settings.basic`, `gmail.readonly` and
  `drive.readonly` are (to confirm) restricted scopes, which means CASA.
- **GCP** project `execs-now-hq`: buckets `execs-now-hq-db-backups` and
  `execs-now-hq-media`; the app uses the service-account key (Railway:
  `GOOGLE_SA_APP_JSON`), backups the backup service account. On the laptop,
  `gcloud auth login` expires: run `! gcloud auth login` when a gcloud step
  fails with "Reauthentication failed".
- **Secrets:** `FIELD_ENCRYPTION_KEY` is in the owner's password manager;
  losing it loses every stored token and key.
- **Test data in production:** Acme Facilities, Noble Baker, and Fake Practice,
  LLC (an outside-practice test) exist; keep them out of external demos.

## Open threads

1. **Phase 6 live checks** wait on a real reply on an app-started thread.
   Confirm `gmail.readonly` was granted by reading `GmailConnection.scopes`, not
   by memory.
2. **Phase 4 Check 1 and Module 4B's manual checks** need real events: a real
   prospect session end to end with its PDF, and real goals with measurements.
   *(The 9/29 session with Brett Murray, Grime Fighters, and its outcome are
   not recorded here. Update this line.)*
3. **Referral-touch drafts** were scheduled to appear on 10/7 for approval.
4. **Meeting ingestion:** live pickup of a brand-new Google Meet meeting had not
   been observed at last check.
5. **Not seen in a browser yet:** P1 (Branding screen, portal colors), P2
   (Practices, switcher fix, agreement, checklist, feedback), and the three
   backlog items.

## Roadmap (recorded, not scheduled)

- **P3:** strategy template builder and session v3.
- **Then**, in this order: P4 billing, Microsoft 365 transport per its spec,
  the campaign/sequence editor, task dependencies, private tasks, notes stacks,
  Google Calendar, an in-app AI helper (inbox triage first), other AI models
  through an integration layer, dark mode, per-practice labels for
  Goal/Project/Task, and a multi-site service-business strategy template.
- **Post-Beta modules**, in `CLAUDE.md`'s order: invoicing (P4 §2) → basic
  financials → e-signature → simple HRIS → connectors → product billing and
  self-serve onboarding.

## Beta exit criteria (from the build plan)

5 real digests approved and delivered, 2 real strategy sessions end to end
with a PDF sent, 10 real meeting proposals reviewed with the approve/reject
rate reported (27 reviewed on 9/26: 18 approved, 9 rejected), a backup
restored at least once (done), all mandatory test families green.

## How we work (keep this rhythm)

- The owner runs everything through copy-paste blocks with a stated target
  (terminal, Claude Code, Railway shell). A separate Aris project must never
  be touched.
- CC finishes a unit, commits on `dev`, pushes, and reports: what's tested
  end to end versus written but not exercised, and anything not seen in a
  browser. The owner reviews several units at once.
- Prompts to CC are specific: the gap, the rule, the test, "commit, stop".
