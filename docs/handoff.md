# Execs NOW HQ — handoff to the next chat

Written 2026-10-03, replacing the 2026-09-22 version; **last updated the night
of 2026-10-10 Mountain (2026-10-11 UTC, the date the specs and the runbook
carry)**, after Release 10 (P6 M1, Bookkeeping) and P6 M2's two stops on
`dev`. **The next session starts at "2026-10-13" below, then "The night of
2026-10-12", "Tonight's state" and "Tomorrow's queue".** Everything from "Next" down was last brought up to date on 10/5 and
after Release 7; where it and the section below disagree, the section below
is the newer. Upload this at the start of the next chat with: "Read this handoff,
then pick up where it leaves off." The specs in `docs/` are the source of
truth; this covers what they don't, and what changed since 9/30.

## 2026-10-13: three M2 findings from the demo, Release 11, and P7 put to Bryan

**This section is the newest.** **Production is `main` at `147087f`: Release
11, 2026-10-14 00:05 UTC (10/13, 6:05 PM Mountain).** It carries everything
that was on `dev`: P6 M2 (the cash forecast, both stops), the ten fixes of
10/12, and the three below. Six migrations, all OK; the record is in the
runbook. Where the sections below say "not released" or "production is
unchanged", this is the newer.

- **The Cash forecast module is off for Executives Now** until Bryan switches
  it on in the Practices area (it needs Bookkeeping).
- `ensure_schedules` was run in production: `finance.keep_month_forecast`
  exists for both practices. **The laptop's qcluster still needs a restart
  and `ensure_schedules`.**
- **Nothing in Release 11 has been seen in a signed-in browser on
  production.** The smoke check is Bryan's: the Forecast tab once the module
  is on, Explain pressed once, Review run once, and one of the 10/12 fixes
  (Notes folders, the Tags setting).
- A fresh backup before a release is Bryan's to run: the "run now" command
  was refused to Claude Code by the permission check.

**Bryan looked at stop 2 on the demo** (queue item 2) and found three things.
Each is its own commit on a green gate; the detail is in the M2 spec, "As
built: after Bryan's look on the demo".

| Commit | What |
|---|---|
| `54b9d6c` | "Explain this forecast" was cut off every time: the output ceiling is 16,000 for the three pressed buttons, and Explain asks for low effort |
| `e4aa2df` | The form a review's proposal opens follows the proposal: its cadence, and the date it next falls. A planned line can repeat "Every year". **Migration `finance` 0011** (a new choice, no SQL), applied to `execsnowhq_local` |
| `147087f` | Review is sent a summary of the money in the forecast already has, by client, and told not to ask about it |

- **Not proven:** none of the three has been run with a real key or seen in
  a browser. The cause of the first is inferred from how the model is
  documented to behave; the demo's `ai_call` rows were not read. The first
  thing to do on the demo after its deploy is press Explain once.
- **The demo deploy of these commits was not checked.**
- **Still open behind this:** M3's spec (queue item 6); §5.6's move of old
  invoice income; the smoke check of Release 10; "the monthly AI budget can
  be set to stop, not warn".

**P7: Bryan answered all fifteen decisions as recommended (10/13)** and added
two things: a fourth level, **Viewer** (sees everything in the company
read-only; for a board member or an investor), and **"nothing"** as a
may-create choice. They are recorded in the spec, §10, and the task
migration is corrected to `crm` 0036.

**P7 phase 1 is built, committed and pushed (`31e13a8`), and not released.**
The tables, the three migrations (`tenancy` 0014, `work` 0010 with the data
step, `crm` 0036 with its task half), the rule in `apps/work/permissions.py`,
`manage.py client_teams_dry_run`, and `tests/test_client_teams.py`. The
spec's "As built: phase 1" says what is wired, what is ruled and not yet
opened, and the readings Bryan ruled on (1, 2, 4 and 5 stand; 3 overruled).

- **One release-day change, by Bryan's ruling:** a client's project is
  deleted only by whoever made it or by the client owner; anyone else who may
  change it sets it to cancelled.
- **Applied to the laptop's `execsnowhq_local`** after the gate was green: 4
  default teams, 3 portal users placed as Manager, 12 projects and 86 tasks
  given a team, as the dry run said. Not in production.
- **Golden files regenerated on Bryan's yes, twice, each for one cause:** in
  `31e13a8`, `converted_goals.json` and `converted_projects.json` gain the two
  new columns; in the commit after it, `claude_requests.json` and
  `prompt_constants.json` gain the no-em-dash sentence. The real-session
  fingerprints are still 4 identical.
- **The model is now told to write no em dashes** in the four drafting
  prompts (rows, consolidate, mirror, pros and cons). The filter stays. No
  real call has been made with the new prompts.
- **The production dry run is owed before phase 1 is released,** and Bryan's
  yes on it before "release" (the data step writes). The command arrives
  with the release, so before it the same plan is read from production by a
  script piped into its shell, as the demo's pre-check is; it reads only
  columns that exist today. Production reads are refused to Claude Code, so
  it is handed to Bryan as a paste block when phase 1 is to go. The laptop's
  dry run (a scrubbed copy of production) is in the 10/13 report: 4 default
  teams, 3 portal users placed as Manager, 12 projects and 86 tasks given a
  team, 28 tasks left to follow their project.

## The night of 2026-10-12: the call's backlog, a spec, and ten fixes

**Read this after the section above, then "Tonight's state" below, which is
as it was on 10/10 except where this says otherwise.**

**Production is unchanged: `main` at `a4037fb`, Release 10.** Everything
below is on `dev`, pushed, and not released. The demo deploys from `dev` and
applies the three new migrations itself at start; **that deploy was not
checked.**

**Earlier on 10/12:** two M2 fixes (`c06279e`, empty forecast lists say
"None."; `82cffe4`, the month's forecast kept by a daily job,
`finance.keep_month_forecast`), and the demo was reseeded onto `82cffe4` by
Bryan, with the forecast data in it. Queue items 1, 3 and 4 below are done;
item 2, Bryan's look at stop 2, is still his.

**The record of the 10/12 call** (`61aef34`):

- `docs/beta_feedback_2026-10-12.md` is the backlog, each item with a status
  and, for tonight's, the commit that built it.
- `docs/p4_billing.md` §9 is the pricing heard on the call, not decided.
- `docs/p7_client_teams_permissions.md` is the **spec for client teams and
  permissions, with fifteen decisions open (§10). No code.** The one to
  read first is P7-1: "their current rights" is what a Manager of the
  default team has, not what a Member has.

**Ten quick fixes, each its own commit on a green gate:**

| Commit | What |
|---|---|
| `f86df49` | Portal "Where we are": goal cards stay in the current order while a client proposes another; the proposal is a list; the Goals box is full width |
| `4d43f57` | Work: a goal card in rows (title; status, date, owner; progress and bar) |
| `800987c` | Tasks: sorted by due date by default, with a sort control on board and list |
| `7a3f4b5` | Meeting queue: the practice by name; a practice task to anyone on the team; a client's task filed under goal, project and task, existing or new, keeping its assignee; portal seats read live |
| `0401a1a` | Contacts and companies: LinkedIn and Alignable links. Settings, Tags (rename, remove). **Migration `crm` 0035** |
| `891aa9c`, `67536fc` | Notes: search matches part of a word in the body; folders. **Migration `notes` 0003** |
| `ffd8ca0` | Template builder: any section can be taken out; "On the prospect's map" on each. **Migration `strategy` 0018** |
| `795f762` | Strategy map: no em dashes in drafted text; the mirror, values and next steps editable on the PDF card |
| `32daa97` | Replies: a sentence under the title |
| `562397a` | Test only: an invitation to an address outside the client's domain signs in by link |

- **The three migrations are additive, with no data step, and are applied to
  the laptop's `execsnowhq_local`.** None is in production. At the next
  release they ride with `finance` 0009 and 0010: five in all, none
  destructive, so no dry run is owed.
- **The laptop's qcluster needs a restart and `ensure_schedules`** to have
  `finance.keep_month_forecast`; production gets that schedule only when
  `ensure_schedules` is run there after the release.

**Open from tonight, each Bryan's:**

1. **Done 2026-10-13, on Bryan's yes (see the section above).** As it was
   written: **Telling the model not to write em dashes** changes the prompts, and the
   prompts are in the v2, classic and v3 golden files
   (`claude_requests.json`, `prompt_constants.json`). Goldens are regenerated
   only on his yes. Until then the filter (`apps/strategy/dashes.py`) is what
   keeps them out of drafted rows, mirrors and pros and cons.
2. **Melissa's assignment bug was not reproduced** from its one line. What
   was found and fixed is in `7a3f4b5`'s message. If it happens again: who
   was named, whether they had a portal sign-in at the time, and which
   button was pressed.
3. **Words on the PDF that still cannot be changed for one session:** the
   ones that come from the template (a next step's label, the two paths'
   titles and lines, the rated items' labels, the chart's heading, the header
   chips' labels, a custom section's questions). They are changed on the
   template, for sessions started after.
4. **"What you have changed" and "How good it has been"** on the Forecast tab
   still hide when empty; only the two lists he named say "None."
5. **Nothing built tonight has been seen in a browser by anyone.**

Tests at the last code commit, by `scripts/gate.sh`: **3051 backend passed
(3 skipped, 2 xfailed), 997 frontend**, migration check and type check clean,
the v2 and v3 golden files unchanged.

## Tonight's state (end of 2026-10-10 Mountain)

**Production is `main` at `a4037fb`: Release 10, 2026-10-11 01:28 UTC.** `dev`
is three commits ahead, at `0abb177`. The runbook has the observed record of
every release through 10 (`docs/phase7_cutover_runbook.md`, "Releasing a
migration").

**Release 10 put P6 M1, Bookkeeping, in production**
(`docs/p6_m1_reconciliation_month_close.md`): sub-categories with combine,
split, archive and remove; the CPA's chart as the starting chart (§5.4) and
the CPA's worksheet export; reconciliation, month close and guided mode with
"Explain this step"; the "Estimated tax payment" mark on an owner draw and
the year-end facts; bulk actions on entries; the Getting started dismissals;
and invoice income entered by the kind of invoice (§5.6). M1 was accepted by
Bryan on the demo before it went.

- **Nine migrations,** applied in the waiting worker, all OK: `tenancy` 0012
  and 0013, `finance` 0003 to 0008, `billing` 0002.
- `finance` 0008 was added at the release, on Bryan's choice: production's
  chart had no "Retainers", so it adds one under "Client fees" for Executives
  Now and points recurring invoices at it. From the release on, payments on
  recurring invoices go to Retainers and on one-off invoices to Project fees
  with no setting touched.
- **§5.6's move is specified and not built.** Every invoice payment
  Executives Now recorded before Release 10 still sits on the "Client fees"
  parent. The move (each to Retainers or Project fees by its invoice's kind,
  closed months included, totals asserted unchanged) is in the spec under
  "The move, for books that already have invoice income on the parent". It is
  built and run only on Bryan's word, as part of a release, after a dry run.
- **Not done at Release 10:** nothing in it had been seen in a signed-in
  browser on production when it went out; production's database was not read
  afterwards; `/healthz` was sampled only from R3 on; the backup relied on
  was the 08:03 UTC dump, 17 hours old, with no fresh one taken.
- Recorded for later, not built: **"the monthly AI budget can be set to stop,
  not warn"** (M1 §12). Until then a person pressing a button is held only by
  the 20 a day below and, on the demo, by the key's own limit in the
  Anthropic console.

**P6 M2, the cash forecast, is built on `dev` in two stops and not released**
(`docs/p6_m2_cash_forecast.md`; its decisions table §12, the brief beside it
§12a, and an "As built" section for each stop).

| Commit | What |
|---|---|
| `a94c74e` | The M2 spec, and the runbook's Release 10 record |
| `849f854` | **Stop 1:** the forecast from known and regular lines, the card, the floor, the screen with 30, 90 and 180 days by week and 12 months, the dashboard line, the download, and the `forecast` module ("Cash forecast"; needs Bookkeeping; off for existing practices). Migration `finance` 0009 |
| `0abb177` | **Stop 2:** planned lines and what-ifs, changes to a line with undo, "how good it has been", "Explain this forecast", "Review with Claude", the setting "Include client names in AI explanations", and the demo's forecast data. Migration `finance` 0010 |

- Both migrations are additive with no data step, and are applied to the
  laptop's `execsnowhq_local`. Neither is in production.
- **Stop 1 was on the demo and timed there:** Forecast tab 110 ms median,
  dashboard line 88 ms, so no cache was added.
- **Stop 2 is pushed and not yet on the demo in any way that can be looked
  at.** The push deploys the demo by itself and the demo applies 0010 at
  start, but **that deploy was not checked**, and until the reseed the demo
  has the module off and none of the seeded forecast data.
- **Pressed AI calls:** "Explain this step", "Explain this forecast" and
  "Review with Claude" share one limit of 20 a day per practice and never go
  past the monthly AI budget. The worker's daily cap counts only what nobody
  asked for (decided 10/10).
- **Not proven:** nobody has seen any M2 screen in a browser; no real key has
  answered Explain or Review (a fake answers in the tests); nothing in M2 has
  run on real books.
- Tests at `0abb177`, by `scripts/gate.sh`: **2975 backend passed (3 skipped,
  2 xfailed), 971 frontend**, migration check and type check clean.

**The brief for the rest of P6 is `docs/p6_finance_expansion_brief.md`,**
saved verbatim from Bryan on 10/10. **It is the source for M3 and M4.** Where
a recorded decision in a spec differs from it, the decision holds (M2 §12a
shows how that was done for M2). The CPA's chart note for M4 is in M1 §5.4.

### The demo as it is set up

- **demo.getexecutivesnow.com**, Railway project `execs-now-hq-demo` (id
  `792ddb0f-a2fb-45a0-9034-fafca1d4d81f`), environment `production`, web
  service `execs-now-hq`, database `railway`. It deploys from `dev` on every
  push, applies its own migrations at start, and has **no worker**.
- **The practice is Summit Operations Partners,** fictional, owned by "John
  Carter", who signs in as `bryan.baker@getexecutivesnow.com` with the
  Internal Google client. Its books run January 2025 to today: 21 months
  reconciled and closed through September 2026, October in progress.
- **Mail goes only through the redirect.** `DEMO_MAIL_REDIRECT` on the demo
  service replaces every recipient with one address before a message is
  built, and it goes out from `DEMO_MAIL_FROM`. Empty, the demo sends
  nothing. The setting refuses to exist anywhere but the demo. Because there
  is no worker, **approving a digest on the demo sends it at once**, inside
  the request, and a digest whose window has passed is marked expired at the
  next page load. Production is unchanged by either.
- **A reseed empties the demo's database and rebuilds it, and keeps three
  things:** Django's own tables (sites, migrations and the rest of
  `demo.DJANGOS_OWN`), the owner's **Gmail connection**, and the practice's
  **Anthropic key**. The key's own limit in the Anthropic console is the
  guard on the demo's AI spend.
- **Changing a variable on the demo service** was refused to Claude Code by
  the permission check; variable changes go to Bryan as a copy-paste block.

**Reseeding, in three steps, each a paste-back:**

1. **The pre-check, read-only, run by Bryan.** Claude Code's own run of it
   was refused twice by the permission check ("production reads"), so it is
   handed over. Save the script below to a file, then in the Claude Code
   prompt:

   ```
   ! cd ~/projects/execs-now-hq && railway ssh -p 792ddb0f-a2fb-45a0-9034-fafca1d4d81f -e production -s execs-now-hq -- "echo $(base64 -w0 <the file>) | base64 -d | python manage.py shell"
   ```

   ```python
   import os
   from django.conf import settings
   from django.db import connection
   from django.db.migrations.executor import MigrationExecutor
   from apps.crm.models import GmailConnection
   from apps.tenancy.models import Tenant, TenantSecret
   from apps.tenancy import demo
   print("ENV", settings.APP_ENVIRONMENT, "| DB", settings.DATABASES["default"]["NAME"])
   print("COMMIT", os.environ.get("RAILWAY_GIT_COMMIT_SHA"))
   ex = MigrationExecutor(connection)
   print("UNAPPLIED", [str(m[0]) for m in ex.migration_plan(ex.loader.graph.leaf_nodes())])
   for t in Tenant.objects.all():
       print("PRACTICE", t.pk, t.slug, "| oauth_client", t.oauth_client, "| from", t.from_address)
   k = demo.kept_mail_connection()
   print("WOULD_KEEP", None if k is None else {a: k[a] for a in ("user_email", "email_address", "send_as_address", "oauth_client")})
   print("SECRETS", TenantSecret.all_objects.count())
   with connection.cursor() as c:
       for t in demo.DJANGOS_OWN:
           c.execute(f'SELECT count(*) FROM "{t}"')
           print("OWN", t, c.fetchone()[0])
   k = demo.kept_ai_key()
   print("AI_KEY would keep", None if k is None else {"owner_emails": k["owner_emails"], "last4 set": bool(k["last4"]), "cipher bytes": len(k["ciphertext"]), "verified_at": k["verified_at"]})
   ```

   These lines are cut from the script used on 10/8 to 10/10, which lived in
   a session's scratch folder and is **not in the repo**; the cut-down copy
   here has not itself been run.
2. **Read what comes back. Reseed only if all of these hold;** otherwise stop
   and say which does not:
   - `ENV` is `demo` and the database is `railway`;
   - `COMMIT` is the commit meant to be looked at, and `UNAPPLIED` is empty;
   - `WOULD_KEEP` is not `None` (the Gmail connection will be kept), and its
     `oauth_client` is what the seed is given as `--oauth-client`;
   - `AI_KEY would keep` is not `None`;
   - Django's own tables are there, with their counts noted to compare after.
3. **The reseed,** which Claude Code has been allowed to run, about three
   minutes:

   ```
   railway ssh -p 792ddb0f-a2fb-45a0-9034-fafca1d4d81f -e production -s execs-now-hq -- python manage.py seed_demo --database railway --ff-email bryan.baker@getexecutivesnow.com --oauth-client internal
   ```

   It prints its counts, which are reported back; for the forecast they are
   under `forecast` (cash today, the floor, the 90-day low, the first week
   under the floor, lines by kind, planned, what-ifs, changes, not counted,
   likely annual, months kept).

## Tomorrow's queue

In this order.

1. **Reseed the demo** onto `0abb177` by the three steps above. Before
   reading anything else, confirm the deploy itself: `COMMIT` is `0abb177…`
   and `UNAPPLIED` is empty, which is the first evidence that `finance` 0010
   applied there.
2. **Bryan's look at stop 2 on the demo.** First time any of it is in a
   browser, and the first real answers from Explain and Review. What he
   finds is fixed in M2, each fix its own commit, gate green.
3. **Empty forecast lists say "None".** **Done 10/12 (`c06279e`)** for "Not
   counted" and "Likely annual, to confirm", the two Bryan named; "What you
   have changed" and "How good it has been" still hide when empty. As it
   was written: Bryan's ask, not built. Which lists
   are meant (Known, Regular, Planned, Changes, Not counted, Likely annual)
   and whether a list that hides itself when empty should show instead is to
   be settled with him or from his look; today "Likely annual" and some
   others are not drawn at all when empty.
4. **A first-of-the-month snapshot job.** **Done 10/12:**
   `finance.keep_month_forecast`, daily at the practice's midnight, a no-op
   once the month's is kept (M2 spec, "As built: after stop 2"). No
   migration; **production gets the schedule only when `ensure_schedules` is
   run there after the release**, and the laptop's qcluster needs a restart
   and `ensure_schedules` to have it. As it was written: today the month's forecast is kept
   the first time the forecast is worked out in that month, so a month the
   owner never opens the app has no row in "how good it has been". The job
   takes it on the 1st for every practice with the module. It goes in the
   worker's schedules (`ensure_schedules`); it calls no AI; the lazy snapshot
   stays as the fallback. The demo has no worker, so its seed keeps taking
   them itself.
5. **Release M2,** on the word "release", by "Releasing a migration":
   `finance` 0009 and 0010, both additive, nothing destructive, so no dry
   run is owed, and any migration item 4 adds rides along. The module stays
   off for Executives Now until Bryan switches it on in the Practices area.
6. **M3's spec,** from `docs/p6_finance_expansion_brief.md`, in the shape of
   M1's and M2's: what it proposes in plain terms and a decisions table with
   a recommendation on each. No code until Bryan answers.

Still open behind these, in no order: §5.6's move for production's old
invoice income (above); a smoke check of Release 10 in a signed-in browser on
production; "the monthly AI budget can be set to stop, not warn".

## Next (as of 10/5, updated after Release 7; older than the two sections above)

In this order.

**0. Release 7 went out 2026-10-08 03:03 UTC (`main` = `dev` = `6627b03`,
then documents).** It carried everything that was on `dev`: the digest
schedule below, the "team" wording, and two rounds of portal, Tasks and Value
report work (invitations, the open goal, goal order, goal proposals, width,
buttons, the logo fallback). Seven migrations, record in the runbook. **Item 1
below was released without its laptop checklist**, on the owner's yes to the
dry run: the checklist is now a production smoke check, and Bryan still sets
Draft on to Friday 3:00 PM himself. Reminder emails are live;
`DIGEST_REMINDERS_ENABLED=false` stops them without a release.

**1. The digest schedule: ~~check it on the laptop, then release it~~ released
in Release 7; check it in production.**
(`docs/digest_schedule.md`; §12 is the as-built record. Built on `dev` 10/5 in
three phases, not released.)

- **Restart the laptop's qcluster first.** It does not reload code, and the
  tick is what drafts, marks late and sends reminders.
- Bryan runs the checklist on localhost:5200 (it is in the 10/5 chat):
  Settings → Digests with Draft on and Send on; Digests → "Generate now" with
  the send time in 2 minutes; Update this draft; Send now… with the whole
  email shown first; a digest going "Not sent on time" and being sent by hand;
  an approved digest staying on the screen; and the three reminder emails in
  Mailpit at http://localhost:8125 (ready, last call, not sent), none of which
  contains a digest's text.
- **If it passes, release.** This one has a migration that writes data, so it
  goes by "Releasing a migration" in the runbook **with a dry run of the data
  step and Bryan's yes before "release"**. `tenancy 0011` adds two columns to
  the practice and runs one `UPDATE` that gives each practice the day before
  its send day at the same hour, which is exactly today's behavior. The dry
  run prints each practice's before and after. `work 0006` and `crm 0032` ride
  along and run no SQL, so the worker will list three migrations as waiting.
- **Then Bryan sets Draft on to Friday 3:00 PM on his own practice in
  production** (Settings → Digests). The release deliberately does not choose
  it for him; until he does, Executives Now is draft Sunday 8:00 AM, send
  Monday 8:00 AM.
- **The same release carries** the "staff" to "team" wording (`c075766`) and
  the flaky Strategy test fix (`f9e8e04`). Neither has a migration.
- `DIGEST_REMINDERS_ENABLED=false` stops the reminder emails without a release
  if they turn out to be noise.

**2. Finish the v2 test session in production, then run a v3 one.**
The v2 test session for **Test Prospect** is in production and has been taken
as far as the diagnostic. Finish it from the diagnostic onward: the call, the
map, the PDF, and converting to a client. Then run a **v3** test session. This
is the rehearsal for **Cory Muscato's session on Thursday 10/8 at 1:00 PM**,
and it gates P3 part two phase 2 (custom sections): no part two code until both
are done and anything they turn up is fixed. The first real Claude call on v3
happens here.

**3. The profile picture bug.** On `feature/profile-picture` (commit
`7094dcf`), not on `dev` and not released. Adding a picture failed for Bryan
with an error saying the file was not the correct type, when it was.
**Waiting on Bryan's details: the file's type, its rough size, and the exact
wording of the error.** Nothing has been investigated yet. Its migration is
numbered `tenancy 0011`, which **now clashes with the digest migration** of the
same number on `dev`: when the branch is rebased onto `dev` it must be
renumbered to follow it (the laptop's database already has both applied, under
their different names).

### Where things are at the end of 10/5

- **Releases 5 and 6 are live.** Production is `main` at `e4222f6`. Release 5
  (`31286cf`): the Pipeline board, clickable rows, the Notes grid, the top bar
  with Sign out and the staff session rules, Settings by role, and Profile
  with the editable name. Release 6: sign-in wording, the practice address
  chosen by the owner, "Mark as a client" with its undo, and the digest day
  and time. Both passed Bryan's production smoke checks. Neither had a
  migration.
- **Bryan's production digest schedule is send Monday 8:00 AM.** Production
  still drafts a fixed 24 hours before, so his weekly digests are written
  **Sunday 8:00 AM** and are not sent unless approved by Monday 8:00 AM. That
  holds until the digest release in item 1 and his change to Friday 3:00 PM.
- **Shawn (Blue Sky Business Consulting) is set up on the beta.** Bryan is
  telling him about the new sign-in wording ("Practice sign-in"), "Mark as a
  client", and that **his strategy template needs two rated items**. **Any
  staff Shawn invites must be added as Google test users first**, or Google
  will refuse their sign-in while the app is unverified
  (`docs/google_verification.md`). His feedback and what was done about each
  item is in `docs/beta_feedback.md`.
- **Still open:**
  - the `/hq` homepage copy, needed for Google verification;
  - connecting a second mail account or a separate inbox (roadmap; needs its
    own spec; `docs/beta_feedback.md`, item B);
  - stage automations offered as a prompt when a card moves (roadmap;
    `docs/ui1_pipeline_board.md` §8);
  - two-factor authentication (roadmap;
    `docs/ui3_top_bar_settings_profile.md` §10);
  - UI 3 phase 5, pictures wherever initials show (after the picture bug).

### Branches at the end of 10/5

| Branch | Holds | State |
|---|---|---|
| `main` | Releases 1–6 | Live in production, at `e4222f6` |
| `dev` | `main` plus: the "team" wording, the flaky test fix, the digest schedule (three phases, with `tenancy 0011`, `work 0006`, `crm 0032`), and documents | **Unreleased.** Pushed. The demo deploys from it, and applies these migrations to its fictional data when it starts |
| `feature/profile-picture` | The profile picture (UI 3 phase 4) and its own `tenancy 0011` | **Unreleased, held for the bug.** Pushed. One commit on top of `31286cf`; needs rebasing onto `dev` and its migration renumbered |
| `backup/dev-2026-10-05` | A copy of `dev` as it was before the picture was moved off it | Nothing that is not on the two branches above. Safe to delete once the picture is released |

The laptop's `execsnowhq_local` has every `dev` migration applied, **and** the
picture's column from when that branch was on `dev`; `dev`'s code ignores it.

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
| **Digest schedule** Draft on / Send on, Update this draft, Send now, late, reminder emails | **Built on `dev` 10/5 (`21a3be2`, `c37f101`, `9eac353`), NOT released.** Spec and as-built: `docs/digest_schedule.md`. Release needs the dry run of `tenancy 0011`'s data step and Bryan's yes. Not seen in a browser by anyone yet |
| "Staff" to "team" wording; flaky Strategy test fix | **On `dev` (`c075766`, `f9e8e04`), NOT released**; they go with the digest release |
| **P6 M1** Bookkeeping: sub-categories, the CPA's chart, reconciliation, month close | **Released 10/10 Mountain (Release 10, `main` at `a4037fb`, nine migrations).** §5.6's move of old invoice income not built. See "Tonight's state" |
| **P6 M2** cash forecast | **Both stops built on `dev` (`849f854`, `0abb177`), NOT released.** Stop 2 not yet looked at on the demo. See "Tonight's state" |
| **P6 M3, M4** | Not specified. Source: `docs/p6_finance_expansion_brief.md` |
| P4 billing | **Spec written** (`docs/p4_billing.md`), ten decisions open, no code |
| Microsoft 365 transport | **Spec written** (`docs/m365_transport.md`), seven decisions open, no code |
| Backlog, built 10/3, **released 10/3 (Release 3)** | dashboard blocks drag across rows; "Not duplicates" on Merge duplicates (migration `crm 0031`); remove an accepted diagnostic question |

Tests on `dev` at the end of 10/5 (`9eac353`, with the digest schedule):
**2361 backend passed (3 skipped, 2 xfailed), 683 frontend**, goldens
unchanged, real-session fingerprints 4 identical.

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
6. **Cory Muscato, Thursday 10/8 at 1:00 PM:** his session is created in production on
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
