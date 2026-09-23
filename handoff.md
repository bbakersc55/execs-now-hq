# Execs NOW HQ — handoff to the next chat

Written 2026-09-22 (evening). Upload this at the start of the next chat with: "Read this handoff, then pick up where it leaves off."

## What this is, in one paragraph

Execs NOW HQ is a multi-tenant SaaS for fractional executives, built by the owner (Bryan Baker, Executives Now, an operations fractional) with Claude Code (CC) doing the coding and this chat doing product direction, review, and the prompts CC receives. Django 5.2 / DRF / Postgres / Django-Q2 (ORM broker, no Redis) backend; React + Vite + TypeScript frontend; WeasyPrint PDFs; Claude API for AI; Google (Gmail send/read, Drive read, Speech-to-Text); GCS for files and backups. Runs on the owner's Zorin laptop in dev mode; Railway is the production target, not yet used. Repo: github.com/bbakersc55/execs-now-hq, branch main. Every spec doc lives in the repo under docs/ and is the source of truth; this handoff covers what the docs don't.

## Where it stands (all Beta modules built)

| Module | State |
|---|---|
| 0.5 Foundation | Signed off |
| 1 CRM (contacts, two pipelines, import, Outbox, referral touches, Gmail send) | Signed off, in real use (142 contacts, 42 referral partners) |
| 2 Notes (capture, PIN, recording→transcript→summary) | Signed off |
| 3 Tasks + client portal + digests + act-as + staff activity feed | Signed off 6/6 |
| 4 Strategy session (template, pre-call form + email variant, live view with Claude tray, 2-page sales PDF, conversion, prep panel) | Signed off except Check 1 (first real prospect session) |
| 4B Client value report (goal-anchored, measurables, milestones, resolutions, narrative, PDF) | Built, 4 manual checks pending (needs real goals with measurements) |
| 5 Meeting ingestion (Drive folder → Claude → review queue) | Built, folder connected, backfill running; approve/reject tally pending |
| 6 Inbound email (Gmail polling of app-started threads, unmatched queue) | Built; gmail.readonly granted; first real reply pending |
| Design pass Tier 1 (shell, Work, Tasks board + editor, live view, portal, value report) | Done, round 1 fixes in |
| Design pass Tier 2 (dashboard, contacts/companies, notes panel, settings) | CC building now, after a task-editor gap fix |
| Branded HTML email layout | Done, approved on real Gmail |
| Railway move | Not done; trigger = a client needs portal access |

Test counts as of tonight: ~1457 backend, ~304 frontend; tenant-isolation and role-boundary families are registries that fail on an unregistered model.

## Live dates and people

- **Brett Murray, Grime Fighters**: real prospect, strategy session **Tuesday 9/29/2026, 1:00 PM MT**. Pre-call questions were emailed 9/22 (with a correction email after an incident, see below). His reply lands in Gmail and, via Module 6, on his contact record. Owner types his answers into the session's pre-call boxes; the six ratings are taken on the call. His email is on the dev allow-list. His session snapshot was patched so the six rating questions show component names. Check 1 of Phase 4 = this session.
- A second real prospect session is scheduled in **October**.
- **Noble Baker / Acme Facilities**: test client and company (Noble's email is the owner's personal Gmail). Used for every dry run and for "View portal as" demos. Acme has converted strategy-session goals. Noble's old session has private-content PDF toggles switched ON from a marker test; do not send from it.
- **Friday 9/25**: planned full dry run with Noble on the finished UI before Brett's call.
- **Monday 9/28**: owner reviews Tier 2 design, clears the meeting queue and reports approve/reject tally, types Brett's answers if received.
- **Oct 7**: 42 referral-touch drafts appear in the Outbox for approval (scheduler; nothing sends without approval).

## Rules and decisions that live outside the repo docs (or are easy to miss)

- **Every AI output and every email goes through a human.** Review queues everywhere; hold_all_digests is ON; the only automation that sends unattended is a deterministic (non-AI) digest with hold OFF, which is not the case anywhere yet.
- **Nothing sends without the full body on screen** (incident 9/22). Magic links and PIN resets are the deliberate exceptions.
- **A rewording never changes a question's shape** (incident 9/22).
- **White-label rule**: clients never see the product name; every client-facing surface renders the tenant's name, colors, logo. Product name is staff-only. V1 adds per-tenant domains.
- **Referral touches and onboarding send from the FF's own address; system mail from info@** (per-producer defaults, per-draft override).
- **Migrations**: CC shows SQL first; may apply itself when additive + suite green + backup this session (owner's session-start backup counts). Destructive or data-rewriting waits for the owner and is done as a command with dry run.
- **Snapshot rule**: a strategy session freezes the template at Start. Edit the template first, then start the session. One template per practice in Beta; customize per prospect by editing before Start (the template is currently customized for Brett; re-edit or run prep before October's session).
- **Goals → Projects → Tasks**, three levels, structural cap; a task has one parent, never both. Clients create tasks and projects, never goals.
- **Digests**: weekly generates Thursday 08:00, sends Friday 08:00 tenant time, expires unapproved at the window (content rolls forward). Every-update batches on a 30-minute quiet window, waits 24h for approval when held. The Digests screen shows a Coming-up card and expiry countdowns.
- **Percent-of-tasks-done is never a headline** anywhere.
- **Stakeholders are Contacts, not Users**; digests go to contacts without logins.
- **Act-as**: FF/assigned CF may view the portal as a client user; everything logged as "X on behalf of Y"; no email sends while acting. Entry: company page portal-access list → "View portal as…".
- **Activity feed is staff-only** (reversed from an earlier client-facing decision).
- **AC-3.5 faithfulness constraint** applies to every Claude narrative: assert nothing absent from the input.
- **Owner's contact row** was merged and linked to his membership; it still carried prospect/referral-partner types at time of writing (owner was cleaning it up).

## Roadmap (recorded, not scheduled)

Campaign/sequence editor for referral partners and nurtured prospects; task dependencies with auto-collapse; private tasks; notes stacks/notebooks; Google Calendar integration; dynamic follow-up questions with a pre-call research pass (three guardrails: proposed never auto-asked, asserts nothing beyond input, never displaces a must-ask); in-app AI helper (email inbox triage first); additional AI models via an integration layer (N8N-style); dark mode; per-tenant display labels for Goal/Project/Task; then post-Beta modules: invoicing (PDF + payment link), financials/QB-lite, e-signature (build own if no API), HRIS-lite, connectors, product billing. Investor deck: owner deferred; when wanted, needs audience, ask, proof point.

## Beta exit criteria (from the build plan)

5 real digests approved and delivered (weekly delivered once via dev-triggered generation; real cycle continues), 2 real strategy sessions end to end with a PDF sent (Brett + October), 10 real meeting proposals reviewed with the approve/reject rate reported, backup restored at least once (done), all mandatory test families green.

## How we work (keep this rhythm)

- Owner is non-technical-ish; runs everything via copy-paste blocks with a stated target (terminal / Claude Code). CC works in `~/projects/execs-now-hq`; a separate Aris project must never be touched (CLAUDE.md isolation rule, Claude Code deny rules).
- Session start (five terminal tabs): `cd ~/projects/execs-now-hq && gcloud config configurations activate execs-now-hq && ./scripts/backup_db.sh`; `.venv/bin/python manage.py runserver 8100`; `.venv/bin/python manage.py qcluster`; `cd frontend && npm run dev`; `mailpit --smtp localhost:1025 --listen localhost:8125`; then `claude` in tab 1 with `/model claude-opus-5` and `/memory`. Runbook says also `pip install -r requirements-dev.txt` after any pull. App http://localhost:5200, Mailpit http://localhost:8125.
- Session end: `./scripts/backup_db.sh` (DB dump + media sync to GCS), Ctrl+C the four tabs.
- CC stops at the end of each phase with an AC table (tested / written-not-exercised / not implemented), full output of the two mandatory families, and asks on anything the docs do not settle. It commits to main (sometimes a phase branch) and pushes when told. It reports what it could not verify (it has no browser; every screen is first seen by the owner).
- Manual checks are where the real findings come from; five or six per phase; the owner runs them and sends notes; we batch findings into one CC message.
- Prompts to CC are specific: state the bug/gap, the rule, the test to add, "commit, push, stop."

## Gotchas that cost time before

- **Restart qcluster after any backend commit** (it doesn't reload; runserver and Vite do). Re-run `ensure_schedules` after a long outage.
- **Hard-reload / restart Vite** after frontend commits before calling something a bug (a stale module once looked like a broken page).
- **pip install after pulls**; a missing package shows as HTML-instead-of-JSON errors in the browser. CC added a startup check.
- **Dev allow-list**: on a localhost build, only exact addresses on the allow-list (Email settings, dev-only section, plus DEV_REAL_SEND_ALLOWLIST in .env) get real mail; everyone else goes to Mailpit. Real prospects must be added before any send.
- **Ports**: Django 8100, Vite 5200. If 8100 is "in use": `fuser -k 8100/tcp`.
- **OAuth**: Internal consent screen (getexecutivesnow.com Workspace only); scopes granted: openid/email/profile, gmail.send, gmail.settings.basic, drive.readonly, gmail.readonly. Redirect URIs registered for both 8100 and 5200 (Google login) and 8100 (Gmail callback). Google verification (CASA) is a V1 task.
- **GCP**: project execs-now-hq (org GetExecutivesNow); buckets execs-now-hq-db-backups and execs-now-hq-media; app runtime uses a service-account key at ~/.config/execs-now-hq/sa-app.json, not ADC; backups use the gcloud CLI. Named gcloud configuration `execs-now-hq` keeps it separate from the Aris project.
- **Secrets**: FIELD_ENCRYPTION_KEY is in the owner's password manager; losing it loses every stored token and API key. Anthropic key stored in-app (Organization "Executives Now" on console.anthropic.com, prepaid credits).
- **Test data**: Acme Facilities, Noble Baker, "Test Testing", "Testing again testing", "Hj hj", "Unknown 2 Unknown 2" are test rows. Clean up before any external demo that shows Contacts.

## Open threads at time of writing

1. CC: task-editor gap (company/goal/project on Edit task; meeting-derived tasks filed under the meeting's company; internal-task stakeholder warning), then Tier 2 design.
2. Owner: Monday review of Tier 2; meeting queue clear + tally; Brett's answers; design round 2 findings for the live view.
3. Friday dry run with Noble; Tuesday Brett's session (Check 1); PDF sent from the session after the call.
4. Module 4B manual checks once real goals with measurements exist (Brett, if he signs; or Acme).
5. Module 6 live: AC-6.12 proves itself on the first real reply.
6. Railway move when a client needs the portal (runbook in build plan Phase 7; note: reconnect Gmail on the new origin first, and hold_all_digests must be ON before qcluster starts there).
