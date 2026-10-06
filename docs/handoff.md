# Execs NOW HQ — handoff to the next chat

Written 2026-10-03, replacing the 2026-09-22 version; updated at the end of that
day, after Release 4 (P3) and the part two spec, and again on **2026-10-05
after Release 5 (the UI work) and Release 6 (Shawn's beta feedback)**. **The next session starts at
"Next" below.** Upload this at the
start of the next chat with: "Read this handoff, then pick up where it leaves
off." The specs in `docs/` are the source of truth; this covers what they
don't, and what changed since 9/30.

## Next

**First, from 10/5:** Bryan runs the production smoke check for Release 5 (the
list is in the 10/5 chat: top bar and profile menu, Settings sections, Sign out
and back in, one Pipeline drag, a Contacts row click, the Notes grid with a
locked note, and Cory Muscato's and the Test Prospect sessions opening with the
call clock below the top bar). Then **the profile picture bug**: adding a
picture failed for Bryan with an error that the file was not the correct type,
when it was. Details to follow from him; nothing has been investigated yet.
The picture (UI 3 phase 4, commit `7094dcf`, migration `tenancy 0011`) is
**built and deliberately not released. Since the evening of 10/5 it lives on
its own branch, `feature/profile-picture`, and is no longer on `dev`**; see
"Where it stands".

**Also from 10/5, released the same evening (Release 6, `main` at
`e4222f6`):** Shawn's (Blue Sky) first beta feedback, in
`docs/beta_feedback.md`: sign-in wording, the practice address chosen by the
owner, "Mark as a client" with its undo, and the digest day and time. No
migration in any of it. Bryan approved all four on the laptop. Both suites, the
goldens and the real-session fingerprints were confirmed on `e4222f6` itself
after the release (2280 backend, 665 frontend, 4 fingerprints identical).
**Not yet smoke-checked in production**; the list is in the 10/5 chat, and it
is look-only: do not mark a real company as a client, change the real practice
address, or change the real digest day while checking. Two things to do by eye: read the alias instructions on
Settings → Email against a real Google Admin console and Gmail (they were
written from memory of Google's screens), and tell Shawn the sign-in page and
his options have changed.

**Then, unchanged from 10/3:**

Bryan runs **two test sessions in production** (part two, decision 14): one
v3 and one v2, with a test contact, before any part two code. **Start by
creating the test contact** (Contacts → Add contact, with an email address
Bryan can open). These two sessions are the first time any P3 screen is seen
in a browser and the first real Claude call on v3. Part two phase 2 (custom
sections) starts only after them, and after anything they turn up is fixed.

**After Release 6 (10/5, late):** it passed Bryan's production smoke check.
**Bryan changed Executives Now's digest schedule in production to Monday at
8:00 AM.** With the fixed 24-hour lead that means the weekly digest is written
**Sunday 8:00 AM** and must be approved by Monday 8:00 AM or it expires
unsent, so the whole approval window is now Sunday and early Monday. Bryan's
answer is a redesign, **built on `dev` in three phases and NOT released:
`docs/digest_schedule.md`** (D1–D13 accepted; §12 is the as-built record).
"Draft on" and "Send on" in Settings → Digests; Update this draft; Send now
with the whole email shown first; a late state, so a digest nobody approved
can still be sent by hand until the next one is drafted; and three reminder
emails to the practice owner and to associates for their own clients.
**The release needs a production dry run and Bryan's yes:** `tenancy 0011`
adds two columns and runs one `UPDATE` that fills them (each practice gets
the day before its send day at the same hour, which is today's behavior;
Executives Now becomes draft Sunday 8:00 AM, and Bryan then sets Friday 3:00
PM himself). `work 0006` and `crm 0032` ride along and run no SQL. Applied to
`execsnowhq_local` only. **After pulling this, restart the laptop's qcluster:
it does not reload, and the tick is what drafts, marks late and reminds.**
`DIGEST_REMINDERS_ENABLED=false` stops the reminder emails without a release.
When `feature/profile-picture` comes back, its `tenancy 0011` must be
renumbered to follow this one. Built on `dev` and **not released**: the
remaining "staff" wording changed to "team" (`c075766`).

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
  paused about 68 s. Releases 3 and 4 the same day took 2 min 10 s and 2 min
  28 s. Recorded in `docs/phase7_cutover_runbook.md`.
- **The demo is reached without relinking the CLI**, which stays linked to
  production: `railway ssh -p <demo project id> -e production -s execs-now-hq --
  <command>`. Check `$APP_ENVIRONMENT` is `demo` in the same command.
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
| **P2** Practices admin and onboarding | **Released 10/3**; Blue Sky created and its owner invited 10/3 |
| **P3** strategy template builder and session v3 | **Released 10/3 (Release 4, `main` at `0a07322`)**, phases 1–5; **no screen seen in a browser yet**; the demo dry run was waived |
| **P3 part two** custom sections, AI per section, per-session rewordings | **Spec approved 10/3** (`docs/p3_part2_custom_sections_ai.md`); **phase 1 done** (v3 pinned by 43 golden files); phase 2 waits on the two test sessions |
| **UI 1** Pipeline board, clickable rows, Notes grid, Work outlines | **Released 10/5 (Release 5, `main` at `31286cf`, no migration)**. Spec and UI backlog: `docs/ui1_pipeline_board.md`. Seen by Bryan on the laptop; **not yet smoke-checked in production** |
| **UI 3** top bar, Sign out, staff session rules, Settings by role, Profile (name) | **Phases 1–3 released 10/5 (Release 5)**. Spec: `docs/ui3_top_bar_settings_profile.md`, D1–D12 accepted |
| **UI 3 phase 4** profile picture | **Built, NOT released.** Commit `7094dcf` is on the branch **`feature/profile-picture`** (on GitHub), one commit on top of `31286cf`. **It is not on `dev`**, which was rebuilt without it on 10/5 so the rest can be released and the demo never gets the broken control. Migration `tenancy 0011` (one nullable column, `membership.avatar_id`) is still applied to `execsnowhq_local`; `dev`'s code ignores the extra column. Held back for the upload bug. To bring it back once fixed: rebase the branch onto `dev`, and if `dev` has gained a `tenancy` migration by then, renumber 0011 to follow it. `backup/dev-2026-10-05` on GitHub is the old line of `dev`, kept as a copy |
| **Beta feedback, Shawn 10/5** (`docs/beta_feedback.md`) | **Released 10/5 (Release 6, `main` at `e4222f6`, no migration):** "Practice sign-in" / "Client sign-in"; the practice address chosen by the owner (own email allowed); "Mark as a client" and its undo; digest day, time and time zone with a one-time prompt. No migration |
| UI 3 phase 5 pictures wherever initials show | Not started |
| P4 billing | **Spec written** (`docs/p4_billing.md`), ten decisions open, no code |
| Microsoft 365 transport | **Spec written** (`docs/m365_transport.md`), seven decisions open, no code |
| Backlog, built 10/3, **released 10/3 (Release 3)** | dashboard blocks drag across rows; "Not duplicates" on Merge duplicates (migration `crm 0031`); remove an accepted diagnostic question |

Tests as of 10/5, on the released commit `e4222f6`: **2280 backend passed (3
skipped, 2 xfailed), 665 frontend**, goldens unchanged, real-session
fingerprints 4 identical. (`feature/profile-picture`, at `7094dcf`, was 2250
and 649 when it was built on the earlier base.)

Tests on `dev` as of 10/3, after P3: the backend suite green (P3 added 65
tests across four files), **566 frontend**. The
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

### P3 in brief (`docs/p3_strategy_templates_session_v3.md`)

- **Three template formats, side by side.** Classic, v2 ("Operations —
  focused") and **v3**, made in the builder. A session keeps the format it was
  created with, frozen in its snapshot. Nothing converts one into another.
- **The builder** (Strategy → Manage the templates → New template; practice
  owner only): eight parts in session order.
  - The practice's own pre-call questions, rated items with labels, fixed
    diagnostic questions, mirror questions, values, the two paths and scope.
  - Settings per template: diagnostic questions per session (1 to 8, default
    3), the rating scale line, each path's words on the PDF, and how Claude
    describes the practice.
  - "What they value" can be taken out. A template needs two rated items to be
    **ready to run**; one that is not ready cannot start a session.
- **A v3 session:** pre-call questions, ratings on the call, a diagnostic
  proposed from the pre-call answers (plus "Propose from the ratings" and "Add
  a question" by hand, eight at most), the mirror under its own questions, the
  five-row card map, the two-page PDF with the template's own chips, labels and
  path copy. Conversion and prep are the existing code.
- **Every AI output still lands as proposed.** A rejected map row or
  diagnostic question is told to Claude and not proposed again.
- **v2 is pinned.** `tests/test_strategy_v2_golden.py` holds 34 golden files
  each for a classic and a v2 session, and
  `scripts/strategy_session_fingerprints.py --check` compares the real sessions
  on the laptop against a baseline. **Both must stay identical; a golden is
  never regenerated to make a test pass.**
- **"Restore from seed" is refused** (and not shown) for a practice with no
  classic or v2 template, so another practice cannot take the Operations
  questions.
- **Deferred from P3, now in part two:** custom sections; adding, removing and
  reordering sections; talk tracks; starting from a copy of a classic or v2
  template; the pre-call form preview in the builder; next-step sentences in a
  v3 covering note.
- **v3 is pinned too** (part two, phase 1): `tests/test_strategy_v3_golden.py`,
  43 files for a builder template and one session from it. They must stay
  identical for a template that uses no part two feature.
- **Found and left alone, for the owner to decide:**
  - Duplicating "Operations — focused" in the old editor gives a *classic*
    copy. Do not duplicate it before 10/8.
  - On a card map (v2 and v3) the mechanics note never prints, whatever its
    PDF flag says.

## Blocked on the owner

1. **Blue Sky Business Consulting** (blueskybizconsulting.com, owner Shawn):
   **the practice is created and the owner invitation is sent (owner, 10/3).**
   **Bryan meets Shawn Monday 10/5 in the afternoon.** For that meeting:
   - Shawn signs in under Staff with Google, passes Google's unverified-app
     warning, and accepts the beta agreement.
   - Branding is Shawn's own to set (Settings → Branding); the mark must be a
     **square PNG, at least 64 × 64 px, up to 500 KB**.
   - He connects Gmail, enters his Anthropic key, and reconnects Google every
     7 days until the app is verified.
   - His first template is built in the builder (Strategy → Manage the
     templates → New template). "Restore from seed" is not offered to him.
   - Any staff he adds must be test users on the External client first.
2. **Google verification** (`docs/google_verification.md`), the owner's steps:
   - **Steps 4–6 are done (owner, 10/3):** the consent screen and the External
     client exist, its two variables are in production on web
     (`execs-now-hq`) and `qcluster`, and Shawn is a test user.
   - **Open before step 7** (the demo video, which opens on that page): the
     `/hq` homepage copy, and the privacy policy beside it (drafted; have a
     lawyer read the policy).
   - Then record the demo video (script drafted) and submit with the drafted
     scope justifications.
   - Answer Google's emails, then the annual CASA assessment for the
     restricted scopes, then publish.
   - Scope classifications and costs are marked to confirm in the console.
3. **P4 and Microsoft 365 decisions** (the tables at the end of each spec).
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
- **Test data:** Acme Facilities and Noble Baker are test rows in production;
  keep them out of external demos. "Fake Practice, LLC" exists only on the
  laptop and goes with the next refresh from production; leave it.

## Open threads

1. **Phase 6 live checks** wait on a real reply on an app-started thread.
   Confirm `gmail.readonly` was granted by reading `GmailConnection.scopes`, not
   by memory.
2. **Brett Murray, Grime Fighters:** the strategy session ran 9/29 as planned,
   and the map and PDF were sent the same day. **Proposal pending, no decision
   yet.** That is one of the two real sessions the exit criteria ask for.
   Module 4B's manual checks still need real goals with measurements (Brett, if
   he signs).
3. **Referral-touch drafts** were scheduled to appear on 10/7 for approval.
4. **Meeting ingestion:** live pickup of a brand-new Google Meet meeting had not
   been observed at last check.
5. **Not seen in a browser yet:** P1 (Branding screen, portal colors), P2
   (Practices, switcher fix, agreement, checklist, feedback), the three
   backlog items, and **all of P3** (the builder, the v3 live view, the v3
   PDF, and that the v2 screens look as they did). The click-by-click checklist
   for one v3 and one v2 session is in the 10/3 chat; the demo is ready for it
   ("Operations — focused" is its default, migration applied), and needs an
   Anthropic key entered on its AI usage screen.
6. **Cory Muscato, 10/8:** his session is created in production on
   "Operations — focused", **with the form not sent**. It was created before P3
   was released, so its questions were frozen first. Bryan emailed Cory a
   questionnaire some time ago and has **no reply yet**. Run it on v2 as
   planned.
7. **No real Claude call has been made on v3.** Every P3 test scripts Claude;
   how the model words v3 diagnostic questions and rows is unseen until the
   two test sessions in production ("Next", above).
8. **Small items, open, each the owner's to decide:**
   - The v2 **"Six Key Components"** label wording (the live view's summary
     card and the PDF heading say six; "Operations — focused" rates five).
   - The **mechanics note does not print on a card map** (v2 and v3), whatever
     its PDF flag says.
   - **Duplicating "Operations — focused"** in the old editor gives a
     *classic* copy. Do not duplicate it before 10/8.
   - The **`/hq` homepage copy**, needed before Google verification step 7.
   Any change to the first three touches v2, so it moves the v2 goldens and
   needs the owner's yes before they are regenerated.

9. **From Release 5 (10/5):**
   - **Staff session rules are live:** quitting the browser signs staff out
     (not when the browser restores its last session), and 12 hours without a
     click, key or scroll signs them out; background refreshes do not count.
     **Client portal sessions are unchanged (30 days)**, waiting on Bryan's
     decision; the recommendation is to leave them.
   - **"Act as a colleague" is the client owner's control only.** Staff view a
     client's portal with "View portal as…". **Nobody can view the app as an
     associate or assistant**; that would be a new permission, not specced.
     The associate's and assistant's menus and Settings are covered by tests,
     not seen by eye.
   - **The flaky test below is fixed** (`f9e8e04`, 10/5): the same three
     steps now run before Apply. Kept here for the history.
   - **A flaky frontend test, not an app fault:** `session prep > ticks all,
     then unticks one, before applying` in `Strategy.test.tsx` failed once in
     a full run. Its last three lines act on the session screen after "Apply"
     has navigated away; the test's one-route router reopens the screen as a
     session called "template", and the control is briefly absent. Reproduced
     on demand, passes 15 of 15 alone. Fix when convenient: move those three
     lines before the Apply click. The test and the screen are unchanged from
     Release 4.
   - **Notes:** a locked note is found by every filter and by its typed title;
     its contents never match. The open-note page is two columns up to 1760px.
   - **Pipeline:** a column loads 100 cards, then "Show more" loads the rest
     in one response; fine for Beta, revisit for a column in the thousands.

## Roadmap (recorded, not scheduled)

- **From 10/5, recorded in the UI specs:** per-stage automations offered as a
  prompt when a card moves, including calendar events and nurture campaigns
  (`docs/ui1_pipeline_board.md` §8); two-factor authentication
  (`docs/ui3_top_bar_settings_profile.md` §10: staff get it from Google
  Workspace's 2-Step Verification; client users are the gap).

- **P3 part two** (`docs/p3_part2_custom_sections_ai.md`), which takes in the
  items P3 deferred: custom sections and talk tracks, AI per section,
  per-session rewordings and the form preview, the PDF and covering note,
  starting from a copy. Two releases.
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
