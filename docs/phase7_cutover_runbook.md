# Phase 7 — Cutover runbook: laptop → Railway

*Written 2026-09-29. Preparation only: nothing below has been run. Nothing has
been deleted and the app has not moved.*

> **Three environments (owner, 2026-09-29, later the same day).** This replaces
> the separate staging service the first version described:
>
> | | Where | Deploys from | Database | Worker | Email out | Drive / mailbox |
> |---|---|---|---|---|---|---|
> | **Local** | the laptop, debug | the working tree | `execsnowhq_dev` now, `execsnowhq_local` after cutover | the owner's tab | Mailpit (+ the allow-list) | yes |
> | **Demo** | `demo.getexecutivesnow.com` | `dev` | its own, seeded (`manage.py seed_demo`) | **none** | **none** | **none** |
> | **Production** | `app.getexecutivesnow.com` | `main`, on "release" | its own | yes | yes | yes |
>
> The demo's "none"s are enforced in code by `APP_ENVIRONMENT=demo`
> (`config/environment.py`), not left to how Railway happens to be set up. It
> sends mail to a backend that discards it; Drive polling, the inbox poll,
> "Sync now" and both Google connects refuse; `qcluster` refuses to start; it
> refuses the production media bucket; staff see a "Demo" banner. **Both Railway
> environments, both DNS records and both sets of OAuth URIs are set up in the
> same pass (A1–A4).**

This is the runbook for the move described in `04_build_plan.md` Phase 7. The
build plan says **what** the move involves and why. This document says **who does
what, in what order**, and what has to be true before the next step starts.

- **Part A** lists the owner's steps, in the order they happen.
- **Part B** lists Claude Code's steps, in the order they happen.
- **Part C** is the combined timeline, showing how A and B fit together.
- **Part D** is the post-cutover verification list.
- **Part E** is the test data to delete before the move. **It needs your
  confirmation, row by row.**

Every step is marked **[proven]** (done and checked), **[built, not run]**,
**[to run]** or **[to build]**. As of 2026-09-29: B0 proven; B1, B3, B4 and B7
built and tested locally, not run on Railway; B5 proven on the laptop;
everything else to run.

---

## State at 2026-09-29, evening

**Done by the owner:** A0 (the ruleset on `main`); A1 as **two Railway
projects**, not two environments in one: `execs-now-hq-live-app-no-testing`
(branch `main`) and `execs-now-hq-demo` (branch `dev`), each with Postgres and a
web service; A2 (custom domains `app.` and `demo.getexecutivesnow.com` on port
8080, CNAME and TXT at GoDaddy); A3 (the "Execs NOW HQ" OAuth client carries
both hosts). **Not yet done: A4a (the backup service account) and A4b (the
demo bucket and service account).** Neither exists in GCP.

**Done by Claude, and checked:**

| Step | Result |
|---|---|
| Part E deletions | **Applied 18:08 MDT** after a fresh backup (`execsnowhq_dev_20260929_180818`) and a dry run: E1 8 rows, E2 8, E4 5, E5 24 (Steven Paul and his session, confirmed by the owner), E6 22 = 67, each group audited. Hj hj kept. |
| gunicorn | Pinned to 8080 (`scripts/start_web.sh`, `Dockerfile`). |
| Postgres versions | Production came up at **18**. The demo's image had been changed to 16 over an 18 data directory, so **it could not start**; set back to 18. Both are 18 now, and the image's `pg_dump` is 18. |
| Railway settings | Config-as-code is **deprecated** on Railway, so each web service's settings (Dockerfile, start command `scripts/start_web.sh`, health check `/healthz`, restart on failure) were applied through Railway's API. `railway/*.json` are the written record. |
| First deploy on an empty database | `migrate_if_empty` builds the schema only on a database with no migrations and no tables. Anywhere else a deploy refuses to start with a migration unapplied. |
| **Demo** | **Live at `https://demo.getexecutivesnow.com`**, from `dev` (the service had been on `main`; switched). Schema built, `/healthz` 200, the app and its assets served, sign-in route up. Variables set; see "Variables" below. **Not seeded**: the seed stores a PDF, and the demo bucket does not exist yet (A4b). |
| **Production web** | Variables and settings set. **Still failing to deploy, as expected**: `main` has no Dockerfile until the owner says "release". |
| **Rehearsal (C4)** | **Passed.** Laptop dump (9.7 MB) restored into a throwaway Postgres 18 in 32 s, no errors. Row counts, the same dump loaded locally vs the throwaway: 96 tables, 6,867 rows, 0 problems (and the same against the live laptop). **Decryption: 2 of 2 secrets** (Anthropic key, Gmail token), checked from the laptop against the throwaway with the laptop's own key, so **the production key never went to Railway**. Dump to restore to checks took 61 s. The throwaway database was then deleted and the dump shredded. |

**The freeze will be short:** the rehearsal suggests about a minute of dump and
restore, plus the checks.

### Release 1, 2026-09-30 02:49 UTC

- **"release"**: the full suite green on `dev` at `b72a671` (1,886 backend,
  478 frontend), `main` fast-forwarded to it. **Production deployed from the
  Dockerfile, built its schema on the empty database, and `/healthz` returns
  200.** The earlier localhost:5432 crash was the pre-Railway `main`, deployed
  before `DATABASE_URL` existed; settings were never at fault (now pinned by a
  test).
- **The owner's secrets had been staged, not deployed**, in both projects
  (Railway holds dashboard edits until "Deploy"). Committed through the API.
  Checked by fingerprint, not value: production's `FIELD_ENCRYPTION_KEY` and
  `GOOGLE_OAUTH_CLIENT_SECRET` **match the laptop exactly**; its service-account
  key is `execs-now-hq-app`, the demo's is `demo-app`. The demo's
  `GOOGLE_OAUTH_CLIENT_SECRET` had not been entered; set from the laptop's
  `.env` (the same OAuth client).
- **Demo seeded** (`seed_demo`, inside the container): Summit Operations
  Partners, 3 clients, 3 prospects, 3 digests waiting, 1 strategy session with
  its PDF in `execs-now-hq-demo-media`, 2 meeting proposals. Nothing written to
  the production bucket.
- **Backup cron (B4/C10) running, ahead of plan**: service `backup` in the
  production project, `scripts/backup_db_railway.sh` at `0 8 * * *`, as
  `backup-writer`. One run forced (schedule briefly every 5 minutes, then put
  back): `pg_dump` 18.6, 38.6 KB dump uploaded as
  `execsnowhq_prod_20260930_025522.sql.gz`, media copy and prune OK. The key
  file on the laptop was shredded after it was stored.
- **Not yet created: `qcluster`** in production. It is created at C9, after
  the cutover checks, not before.

**Next is the freeze (C6), which starts with the owner.**

### Cutover, 2026-09-30 ~02:58–03:01 UTC (C6–C7)

- **C6:** the owner stopped the laptop worker, dev server and Vite. Checked: no
  process, 0 queued jobs, no note transcribing or drafting. One file, the
  15 May note, had been left in `parsing` by the old worker at 15:43 UTC. The
  new poll never retries that state, so it was marked failed and needing a
  person (`auto_parse_failures=2`, 54 failures before the cap). It shows under
  "Couldn't be read" with Read again.
- **C7.1–7.2:** final dump 9.74 MB. Production's database was checked to hold
  only the rows the schema build makes (permissions, content types, migration
  records, the site row), then its schema reset and the dump restored: 40 s,
  no errors, through a temporary TCP proxy deleted straight afterwards.
- **C7.3:** the job queue was already empty; schedules kept (9). `ensure_schedules`
  runs at C9 with the worker.
- **C7.4 gate: 96 tables, 6,867 rows, 0 problems**, laptop vs production.
- **C7.5: `hold_all_digests` is ON.** Decryption on production, with its own
  key: **2 of 2** (Anthropic key, Gmail token). Daily AI cap $5.
- **C7.6:** web restarted on the restored data: "Migrations are current", 200.
- Freeze to live: **3 minutes**. The dump and credentials were shredded.

**The laptop's `execsnowhq_dev` is now the two-week fallback. Do not start the
laptop worker or dev server against it**: it still holds working Gmail and Drive
tokens, and a laptop worker would poll alongside production (B7 moves the
laptop to a separate scrubbed database).

**Next: C8, the owner's re-consent and D-checks 1–5**, then C9 (the worker).

### C8–C9, 2026-09-30 ~03:10–03:35 UTC

- **C8 (owner):** Gmail reconnected, Drive watch confirmed (after the
  Disconnect was undone), a test message to `bbakersc1@gmail.com` delivered
  from `info@getexecutivesnow.com` at 03:18:45, and the reply reached the
  owner's inbox. **The magic-link check could not be done:** production's
  signed-out screen had no client sign-in form. Fixed on `dev` (35bfe23); it
  reaches production at the next release. **Reply collection is not granted:**
  the reconnect did not include `gmail.readonly`, so the inbox poll reports
  "not connected". Cause: the Email settings screen had no reply-collection
  tick — the API accepted the flag but nothing sent it, so neither the laptop
  nor production ever held the scope. Tick added on `dev`; after the next
  release, redo A6 step 2.
- **C9:** `hold_all_digests` confirmed ON; `ensure_schedules` realigned the 9
  schedules. Service `qcluster` created in production from `main`
  (`scripts/start_qcluster.sh`, restart on failure, no domain). Its variables
  are Railway references to the web service's, so nothing was pasted twice (the
  encryption key's fingerprint matches). **First cycle, 03:31:48: every job
  succeeded** (tick, Drive poll, import step, inbox poll, notes), 0 failures, 0
  AI calls, 0 digests generated, nothing sent (the one message in the window is
  the owner's test, 13 minutes before the worker started).

### Variables

`*` = set by Claude. A generated secret was piped straight into Railway and
never displayed. **You paste only the four marked ☐.**

**Production, web service `execs-now-hq`:**

| Variable | Value |
|---|---|
| `APP_ENVIRONMENT`* | `production` |
| `PUBLIC_BASE_URL`* | `https://app.getexecutivesnow.com` |
| `APP_ROOT_URL`* | `/` |
| `DJANGO_DEBUG`* | `False` |
| `DJANGO_ALLOWED_HOSTS`* | `app.getexecutivesnow.com,healthcheck.railway.app` |
| `DATABASE_URL`* | `${{Postgres.DATABASE_URL}}` |
| `DJANGO_SECRET_KEY`* | generated |
| `GOOGLE_OAUTH_CLIENT_ID`* | from the laptop's `.env` |
| `GOOGLE_CLOUD_PROJECT`* · `GOOGLE_STT_LANGUAGE`* | `execs-now-hq` · `en-US` |
| `STORAGE_BACKEND`* · `GCS_BUCKET_MEDIA`* | `gcs` · `execs-now-hq-media` |
| `ANTHROPIC_MODEL`* · `APP_MAIL_TRANSPORT`* · `DEFAULT_FROM_ADDRESS`* · `Q_CLUSTER_WORKERS`* | `claude-opus-5` · `gmail` · `info@getexecutivesnow.com` · `4` |
| ☐ `FIELD_ENCRYPTION_KEY` | **exactly** the laptop `.env` value |
| ☐ `GOOGLE_OAUTH_CLIENT_SECRET` | the laptop `.env` value |
| ☐ `GOOGLE_SA_APP_JSON` | the **contents** of `~/.config/execs-now-hq/sa-app.json` |

The `qcluster` and `backup` services are created later (C9, C10). qcluster
takes the web's values by Railway reference (`${{execs-now-hq.FIELD_ENCRYPTION_KEY}}`),
so nothing is pasted twice. backup needs `GOOGLE_SA_BACKUP_JSON` (A4a) then.

**Demo, web service `execs-now-hq`:** everything set (`APP_ENVIRONMENT=demo`,
`PUBLIC_BASE_URL=https://demo.getexecutivesnow.com`,
`DJANGO_ALLOWED_HOSTS=demo.getexecutivesnow.com,healthcheck.railway.app`,
`DATABASE_URL=${{Postgres.DATABASE_URL}}?connect_timeout=10`,
`GCS_BUCKET_MEDIA=execs-now-hq-demo-media`, and a generated `DJANGO_SECRET_KEY`
and `FIELD_ENCRYPTION_KEY` of its own) except:

| Variable | Value |
|---|---|
| ☐ `GOOGLE_OAUTH_CLIENT_SECRET` | the same laptop `.env` value |
| (after A4b) `GOOGLE_SA_APP_JSON` | the **demo-app** key's contents, never the app's |

---

## Branching — in effect from 2026-09-29

- **`dev`** is the working branch. Every change lands there and is pushed there.
- **`main`** is production. Once Railway is connected, **a push to `main`
  deploys to `app.getexecutivesnow.com`** (build plan Phase 7 §1).
- **I merge `dev` → `main` only when you say "release".** The gate is the
  **full test suite, green on `dev` at the commit being merged**. A red suite
  means no merge, whatever the change.
- **The demo (B3) deploys from `dev`.** So "pushed to dev" means "live on the
  demo", and "release" means "live in production". This replaces both the
  staging service of this runbook's first version and the `staging` branch of
  the Phase 8+ note. One working branch is enough while one person releases.
- **The GitHub rule on `main`: approved (owner, 2026-09-29), and it is step
  A0 below.** It is yours because this laptop has no `gh` CLI and no GitHub
  token for me to set it with.

---

## Releasing a migration — the only way a migration reaches production

Owner, 2026-10-02. **No deploy ever migrates production.** `start_web.sh`
builds the schema only on an empty database and otherwise refuses to start
with a migration unapplied. `start_qcluster.sh` **waits** in the same case, and
that is deliberate. `railway ssh` reaches only an *active* instance, and the
waiting worker is the only active container running the new code, where the
migration files are. (A shell in the old web container would run the old
code's `migrate` and find nothing to apply.) No other route is used: not
`railway run … migrate` from the laptop, and not a start command that migrates.

**Before "release":** the migration's SQL has been shown (`sqlmigrate`), the
full suite is green on `dev`, and the laptop's `execsnowhq_local` is migrated.
Anything destructive or data-rewriting has your explicit yes on the dry run
(CLAUDE.md).

**On "release", in one sitting, straight through:**

| # | Step | Command | Gate |
|---|---|---|---|
| R1 | Confirm the backup | `gcloud storage ls -l "gs://execs-now-hq-db-backups/execsnowhq_prod_*" \| sort -k2 \| tail -1` | The newest dump is from the most recent 08:00 UTC run (02:00 Mountain), under 24 hours old, and over the 1 KB floor. If not, stop: run the backup by hand first (`railway redeploy --service backup -y`) and check again. |
| R2 | Release | merge `dev` → `main`, push | Railway builds web and qcluster |
| R3 | Watch the worker | `railway logs --service qcluster` | `WAITING` lists exactly the release's migrations, nothing else |
| R4 | **Apply, immediately** | `railway ssh --service qcluster -- python manage.py migrate` | Each migration `OK`; output pasted into the report |
| R5 | Worker resumes by itself | `railway logs --service qcluster` | `migrations current`, then `Q Cluster … starting`, within 30 s |
| R6 | Web onto the new code | `railway redeploy --service web -y` | Deployment active; `curl -s -o /dev/null -w '%{http_code}' https://app.getexecutivesnow.com/healthz` is `200` |
| R7 | Report | | R1–R6 results, the migration names, and the time from R2 to R6 |

**What it costs.** The worker is paused from R2 to R5. That is intended, so no
old-code job runs while the schema changes. Web's new deployment fails its
health check until R4. Whether Railway keeps the old web serving in the
meantime, as it does for a failed health check, **has not been observed yet**:
if it does, nothing goes down; if not, web is down from R2 to R6, a few minutes
when R4 follows R3 immediately. The first migration release records which.

**Not yet observed on Railway:** a waiting `qcluster` counting as active for
`railway ssh`, and `railway redeploy` on the backup cron. The waiting itself is
tested locally (2026-10-02: it waited on a database with every migration
unapplied, and started the cluster 4 s after `migrate` ran by hand). If R4 finds
no instance, stop and report. Do not improvise another route.

---

## Part A — the owner's steps, in order

### A0. Protect `main` on GitHub — *now; five minutes*

1. GitHub → `bbakersc55/execs-now-hq` → **Settings → Rules → Rulesets → New
   branch ruleset** (older screens: Settings → Branches → Add rule).
2. Name it `main`. Enforcement: **Active**. Target: **the default branch**
   (`main`).
3. Tick **Restrict deletions** and **Block force pushes**. Tick nothing else.
   Requiring pull requests or status checks would block my "release" merge,
   which is a plain push after the suite passes here.
4. Leave the bypass list empty, and save.
5. Tell me. I cannot check it from here: a dry-run push never reaches GitHub,
   and there is no `gh` on this laptop. So its first real test is the first
   force-push anyone tries, which should be never.

### A1. Railway account and project — *any time before B1*

1. Create the Railway account (or sign in) and put a payment method on it.
   Two Postgres databases and four app services will exceed the free allowance.
2. Create one **project** named `execs-now-hq`. Make two **environments** in it:
   `production` and `demo`. Each gets its own Postgres (B1, B3), **at version
   16**, to match the laptop and the image's `pg_dump`. If Railway offers only
   a newer version, stop and tell me, because the Dockerfile changes with it.
   - `production` will hold `web`, `qcluster`, `backup` and `Postgres`, from `main`.
   - `demo` will hold `web` and `Postgres` only, from `dev`. **No qcluster.**
3. Connect the GitHub repo `bbakersc55/execs-now-hq` to the project. This is
   Railway's GitHub app, and it asks for access to that repo only. Grant access
   to this repo only, not "all repositories".
4. Invite nobody else for now.
5. Tell me it is done. I do the service configuration (B1). Adding a service
   yourself is fine too, but leave its settings to me so the three services match.

### A2. DNS — two CNAMEs, `app` and `demo` — *after B1 and B3 give you the targets*

1. Once both web services exist: Railway → **production** → web → Settings →
   Networking → **Custom domain** → `app.getexecutivesnow.com`; and **demo** →
   web → the same → `demo.getexecutivesnow.com`. Railway shows a CNAME target
   for each, something like `xxxx.up.railway.app`. They are different targets.
2. At your DNS host for `getexecutivesnow.com`, add two **CNAME** records:
   - Name `app` → the production target
   - Name `demo` → the demo target
   - TTL: the lowest your host allows (300 s is typical) until cutover is done
3. Change nothing else. **Do not touch the MX, SPF, DKIM or DMARC records.**
   Workspace mail depends on them, and the app needs no DNS records of its own
   in Beta (build plan Phase 7 §2).
4. Railway issues the TLS certificate once the CNAME resolves. Tell me when the
   custom domain shows as verified.

Pointing both CNAMEs early is safe. Until cutover, `app` serves an empty
database (it stays empty until the final restore, C7), and `demo` serves only
fictional data.

### A3. Google OAuth — redirect URIs for the new host — *before C5*

In the **`execs-now-hq`** GCP project → APIs & Services → Credentials → the
existing **Web application** OAuth client (the one the laptop uses). **Add these
URIs. Remove none.** The localhost URIs must stay, because the laptop remains the
development machine.

**Authorized JavaScript origins**, add:
- `https://app.getexecutivesnow.com`

**Authorized redirect URIs**, add both. They are two different consents, and a
missing one fails at Google's screen with `redirect_uri_mismatch`:
- `https://app.getexecutivesnow.com/accounts/google/login/callback/` (signing in)
- `https://app.getexecutivesnow.com/accounts/gmail/callback` (Gmail **and** Drive
  consent; both use this one callback)

**For the demo**, in the same pass, add:
- Authorized JavaScript origin: `https://demo.getexecutivesnow.com`
- Redirect URI: `https://demo.getexecutivesnow.com/accounts/google/login/callback/`
  (signing in only)
- Do **not** add the demo's `/accounts/gmail/callback`. The demo never connects
  Gmail or Drive, and refuses to (B3).

Sign-in stays Internal, so only `@getexecutivesnow.com` accounts can sign in to
the demo, and only those the seed gave a membership (`--ff-email`). A prospect
you show it to watches you drive; they do not get a login.

The consent screen stays **Internal**. Nothing else on it changes.

### A4. Secrets — *entered by you, in Railway, before B4 and C6*

You enter these values yourself in Railway → service → Variables. **Do not paste
any of them into this conversation.** I set every non-secret variable; B1 lists them.

| Variable | Where it goes | Value |
|---|---|---|
| `FIELD_ENCRYPTION_KEY` | production **web and qcluster** | **The exact value from the laptop's `.env`.** Copy it; do not generate a new one. Every stored Anthropic key and OAuth token was encrypted with it, and a new key makes all of them unreadable. |
| `DJANGO_SECRET_KEY` | production web and qcluster (same value in both) | A **new** value. Generate: `.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(50))"`. Do not reuse the laptop's. |
| `GOOGLE_OAUTH_CLIENT_SECRET` | production web and qcluster | From the laptop's `.env`. The client ID is not secret; I set it. |
| `GOOGLE_SA_APP_JSON` | production web and qcluster | The **full contents** of `~/.config/execs-now-hq/sa-app.json`, the app's service-account key (Speech-to-Text, media bucket). The variable holds the JSON itself, not a path. B2 makes the app read it that way. |
| `GOOGLE_SA_BACKUP_JSON` | production **backup cron only** | A **new** service-account key for backups (A4a). |
| `SENTRY_DSN` | production web and qcluster | Optional. Only if you want error reporting from day one (A5 in the assumptions). |

**The demo gets its own values, never production's:**

| Variable | Demo web | Value |
|---|---|---|
| `DJANGO_SECRET_KEY` | yes | A **new** value, different from production's |
| `FIELD_ENCRYPTION_KEY` | yes | A **new** Fernet key (the command is in `.env.example`). Nothing real is ever encrypted with it |
| `GOOGLE_OAUTH_CLIENT_SECRET` | yes | The same OAuth client's secret (sign-in only on the demo) |
| `GOOGLE_SA_APP_JSON` | yes | The **demo** service account's key (A4b), not the app's |

**The production encryption key goes into Railway once, for one command,
during the rehearsal (C4.3)**, as a variable on a one-off command in the demo
environment, never on the demo's web service. Then it is removed.

#### A4b. The demo's own bucket and service account — *before B3*

1. GCP `execs-now-hq` → Cloud Storage → create bucket
   **`execs-now-hq-demo-media`**, same region as the production one. The demo
   refuses to boot pointed at `execs-now-hq-media`.
2. IAM → Service accounts → create `demo-app`. Grant it **Storage Object Admin
   on `execs-now-hq-demo-media` only**. Nothing at project level, nothing on
   the production buckets.
3. Create a JSON key and paste its contents into the demo web's
   `GOOGLE_SA_APP_JSON`, then delete the downloaded file.

#### The Anthropic key — not a Railway variable

**Your list included the Anthropic key. It must not go into Railway.** Settings
refuse to start with `ANTHROPIC_API_KEY` set off localhost
(`config/settings.py`, assumption E1.6). That refusal is deliberate: in
production each tenant supplies its own key. **Your key is already in the
database**, encrypted in `tenant_secret`, and it moves with the restore. It
works on Railway because `FIELD_ENCRYPTION_KEY` moves too, and D-check 7 proves
it. If you would rather rotate it at the move, do that after cutover in the app's
Settings screen as the FF, not in Railway.

#### A4a. The backup service account — *before B4*

The laptop backup uses your own `gcloud` login. Railway has none, so it needs its
own identity (build plan Phase 7 §5):

1. GCP `execs-now-hq` → IAM → Service accounts → create `backup-writer`.
2. On bucket **`execs-now-hq-db-backups`** only: grant `Storage Object Admin`.
   It needs to delete too, because the script prunes after 30 days.
3. On bucket **`execs-now-hq-media`**: grant `Storage Object Viewer`. The
   backup copies media into the backup bucket.
4. Grant it nothing at project level.
5. Create a JSON key and paste its contents into `GOOGLE_SA_BACKUP_JSON` on the
   backup cron service. Then delete the downloaded file.

### A5. The freeze on the laptop — *at cutover, C6*

Per the standing rule, the worker runs only in your tab:

1. In your qcluster tab: stop it with **Ctrl-C** and wait for it to exit.
2. Tell me. I confirm no task is mid-flight (C6.2) before anything else happens.
3. Stop the laptop's Django dev server (and Vite) in their tabs.
4. **From here until I say the cutover is done, do not use the laptop app.** Any
   write made after the final dump is lost.

### A6. Gmail and Drive re-consent on the new host — *after cutover, C8*

OAuth grants are tied to the redirect URI. The restored tokens will refresh, but
the app will also be reconnected on the new origin, so every future consent goes
through `app.getexecutivesnow.com`:

1. Sign in at `https://app.getexecutivesnow.com` with Google.
2. **Settings → Email settings → Your Gmail connection.** Tick **Also collect
   replies** (`gmail.readonly`), then **Reconnect**. Confirm the send-as alias
   `info@getexecutivesnow.com` shows as verified, and that "Granted" lists
   "Read your mailbox (Tier 2)". *(Corrected 2026-09-30: this step said "as on
   the laptop", but no screen ever sent the reply-collection flag — the laptop
   connection never held `gmail.readonly` either. The tick and the Reconnect
   button were added on `dev` the same day.)*
3. **Meeting queue: check, do not press anything.** Reconnecting Gmail with
   Drive ticked in step 2 *is* the Drive reconnect; there is no separate
   button. Confirm both watched folders read back with their names and file
   counts ("Meet Recordings", and "Google Meet" at any depth with the Gemini
   pattern), and the never-read list (`AoA`, `Academy of America`, and the
   ignored meetings). **Do not press Disconnect on the folder card:** it
   switches the watch off. *(Corrected 2026-09-30: this step said "Reconnect
   Drive", no such button exists, and Disconnect was pressed at 03:08:59 UTC;
   the watch was switched back on with its cursor unchanged.)*
4. Send one test message to yourself from the app (D-check 5).
5. Tell me. qcluster on Railway does not start until this and D-checks 1–5 pass.

### A7. After cutover — *the following days*

1. **Your session-start routine changes.** `scripts/backup_db.sh` on the laptop
   backs up the laptop database, which is no longer production after cutover.
   The production backup is the Railway cron (B4). Its result is in the Railway
   logs and as a new object in `gs://execs-now-hq-db-backups/`. I will give you
   a one-line check for your morning routine at cutover.
2. **Do not start the laptop's qcluster against the old database.** It still
   holds working Gmail and Drive tokens. A laptop worker would poll your mailbox
   and Drive **alongside** Railway and could send digests twice. B7 moves the
   laptop to a separate, scrubbed dev database before the laptop worker runs again.
3. Keep the old laptop database untouched for **at least two weeks** (to
   2026-10-13 at the earliest if we cut over this week), then tell me to delete it.

---

## Part B — Claude Code's steps, in order

### B0. Branching — **[proven]** 2026-09-29

`dev` created from `main` at `8f8851d` and pushed to `origin/dev`. All work from
now on happens on `dev`. `main` moves only on "release".

### B1. Railway configuration for the production services — **[built, not run]** 2026-09-29

**Built on `dev` and tested locally. None of it has run on Railway,** and the
image has not been built: Docker is not installed on the laptop, so the first
build is Railway's.

| What | Where | Tested how |
|---|---|---|
| `gunicorn==26.2.0` | `requirements.txt` | Installed; `pip check` clean |
| One image for all three services: Node 24 builds the bundle; Python 3.12 slim; WeasyPrint's Pango/HarfBuzz; Arimo and Liberation fonts (what the laptop resolves the PDFs' Helvetica/Arial to); `pg_dump` 16 from PGDG; `collectstatic`; runs as a non-root user | `Dockerfile`, `.dockerignore` | **Not built** (no Docker here) |
| Per-service config | `railway/web.json`, `railway/qcluster.json`, `railway/backup.json`, `railway/README.md` | Key names follow Railway's documented schema; to be checked against the real screens at A1/B1 |
| Behind Railway's proxy: `SECURE_PROXY_SSL_HEADER` (off localhost only), `CSRF_TRUSTED_ORIGINS` (the public origin, plus any named), `/healthz` exempt from the HTTPS redirect | `config/settings.py` | Production settings booted in a subprocess with production variables (`tests/test_production_settings.py`) |
| **Refused off localhost:** the development `DJANGO_SECRET_KEY`, and `DJANGO_DEBUG=True` (joining the two refusals that already existed) | `config/settings.py` | Same tests: each makes boot fail with its message |
| The service-account key from `GOOGLE_SA_APP_JSON` (the key's contents) in preference to the file path, with no key file written to disk; a malformed value is named and never echoed | `apps/tenancy/google_credentials.py`, used by storage and Speech-to-Text | Unit tests with a generated key |
| The React app served by Django: Vite builds with base `/static/` (WhiteNoise serves it), and every path outside `api/ admin/ accounts/ auth/ static/ media/ healthz` returns `index.html`, so a deep link opens the app | `frontend/vite.config.ts`, `config/spa.py`, `config/urls.py` | `npm run build` checked (the index asks for `/static/assets/…`); route tests. **Not seen in a browser.** |
| `/healthz`: the process and the database, nothing else | `config/spa.py` | Test |
| `.env.example` current | `.env.example` | By hand |

**Postgres major version: create the Railway database at 16.** The laptop is on
16.15, and the image's `pg_dump` is 16 (`PG_MAJOR` in the Dockerfile). A newer
server would need both changed together, because a `pg_dump` older than its
server refuses to run.

**Migrations are never applied by a deploy.** `web` and `qcluster` start with
`migrate --check`, so a release that carries a migration **refuses to start**
until the migration is applied by hand in the service shell, after that day's
backup. CLAUDE.md's migration rule (SQL first, additive, green, backup today)
holds in production exactly as on the laptop. The old version keeps serving
until the new one passes its health check. See `railway/README.md`.

**Services in the `production` environment**, all built from `main`:

| Service | Config | Notes |
|---|---|---|
| `web` | `railway/web.json` | Custom domain `app.getexecutivesnow.com`. Health check `/healthz`. |
| `qcluster` | `railway/qcluster.json` | **No public domain.** `Q_CLUSTER_WORKERS=4`; `CONN_MAX_AGE` is already 0. **Starts with 0 replicas** and is scaled to 1 only at C9. |
| `backup` | `railway/backup.json` | Cron `0 8 * * *` (08:00 UTC, 02:00 Mountain). |
| `Postgres` | Railway plugin | **Version 16.** |

**Non-secret variables I set:** `DJANGO_DEBUG=False`,
`DJANGO_ALLOWED_HOSTS=app.getexecutivesnow.com,healthcheck.railway.app` (the
second is the Host header Railway's health check sends),
`PUBLIC_BASE_URL=https://app.getexecutivesnow.com`, `APP_ROOT_URL=/`,
`DATABASE_URL` (Railway reference to the plugin), `APP_MAIL_TRANSPORT=gmail`,
`DEFAULT_FROM_ADDRESS`, `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_CLOUD_PROJECT`,
`GOOGLE_STT_LANGUAGE`, `STORAGE_BACKEND=gcs`, `GCS_BUCKET_MEDIA=execs-now-hq-media`,
`ANTHROPIC_MODEL`, `Q_CLUSTER_WORKERS=4`.

**Deliberately absent:** `DEV_REAL_SEND_ALLOWLIST` and `ANTHROPIC_API_KEY`
(settings refuse to boot with either off localhost), `GOOGLE_APPLICATION_CREDENTIALS`
(replaced by `GOOGLE_SA_APP_JSON`), `EMAIL_HOST`/`EMAIL_PORT` (Mailpit only),
`MEDIA_ROOT`.

**`PUBLIC_BASE_URL` is the most consequential variable in the move.** Off
localhost, outbound mail is real mail (FR-0.7). It is set on production from the
start, which is why the production database stays empty until C7 and qcluster
stays at 0 replicas until C9.

**Not built, on purpose:** `sentry-sdk`. Say if you want error reporting from
day one and I will add it; `SENTRY_DSN` then goes in A4.

### B2. The first deploys, both empty of real data — **[to run]**

1. For the first production deploy I ask you for a **"release"** of the B1
   code, with the suite green as always. The demo deploys from `dev` without
   one.
2. Each `web` refuses to start on its empty database (`migrate --check`). That
   is the point of the check. I apply the migrations in each service's shell;
   both databases are empty, so there is nothing to back up. Then each starts.
   The sign-in page at `https://app.getexecutivesnow.com` and at
   `https://demo.getexecutivesnow.com` proves the image, WeasyPrint's
   libraries, the proxy settings, TLS and DNS for both, with no data at stake.
3. Nobody signs in to production yet. There is no tenant in it until C7.

### B3. The demo — **[built, not run]** 2026-09-29 · safety design approved 2026-09-29

The `demo` environment: `web` only, from **`dev`**, its own Postgres at 16, at
`demo.getexecutivesnow.com`. What it does and does not do is set by one
variable, **`APP_ENVIRONMENT=demo`**, and enforced in code:

| Promise | Where it is kept | Tested |
|---|---|---|
| Sends no email | `outbox` always uses the dev transport; the email backend discards | `tests/test_demo_environment.py` |
| Reads no Drive, no mailbox | `ingest.poll` and `inbound_poll.poll` refuse, so the timer, "Sync now" and "Collect replies" all stop there | same |
| Connects no Google account | the Gmail and Drive consent starts refuse (409) | same |
| Runs no worker | a system check makes `qcluster` refuse to start | same |
| Holds no real files | boot refused if `GCS_BUCKET_MEDIA` is the production bucket | same (a real boot) |
| Says so | a "Demo" banner for FF, CF and VA; clients never reach it | `DemoBanner.test.tsx` |

**Demo variables I set:** `APP_ENVIRONMENT=demo`,
`PUBLIC_BASE_URL=https://demo.getexecutivesnow.com`, `APP_ROOT_URL=/`,
`DJANGO_DEBUG=False`,
`DJANGO_ALLOWED_HOSTS=demo.getexecutivesnow.com,healthcheck.railway.app`,
`DATABASE_URL` (the demo Postgres), `STORAGE_BACKEND=gcs`,
`GCS_BUCKET_MEDIA=execs-now-hq-demo-media`, `GOOGLE_OAUTH_CLIENT_ID`,
`GOOGLE_CLOUD_PROJECT`, `ANTHROPIC_MODEL`. Secrets are yours (A4, A4b).

**Seeding and resetting** (`manage.py seed_demo`; **[built, tested]**):

    railway ssh --service web          # in the demo environment
    python manage.py seed_demo --database <the demo database's name> \
        --ff-email bryan.baker@getexecutivesnow.com --ff-name "Bryan Baker"

Every run **empties the whole demo database first, then seeds it**, so
re-running is the reset. It refuses unless `APP_ENVIRONMENT` is `demo`, refuses
`execsnowhq_dev` by name whatever else is true, and needs the database's name
typed. What it makes, all fictional and all at `.example` addresses: **Summit
Operations Partners**; three client companies (Northwind Facility Services,
Bluebird HVAC, Cedar Ridge Landscaping), each with a goal, projects and tasks
in every status, carrying client-facing updates; weekly digests waiting for
approval, generated by the real digest code; three prospects at pipeline
stages, a referral partner and a vendor; one strategy session with Brianna
Castillo, completed, with a map, both paths, pros and cons, next steps, and its
PDF stored; and two meeting proposals in the queue, one client and one
prospect, built by the same code a real parse uses. The FF is `--ff-email`, and
there is a fictional VA.

**The demo has no Anthropic key**, so Claude's buttons there say so rather than
drafting. If you want to show drafting live, enter a key on the demo's AI usage
screen. It spends on that key, and the daily cap there is $0 for unattended
work, which the demo has none of anyway.

**The rehearsal no longer goes near the demo's database** (B6).

### B4. The backup cron — **[built, not run]** 2026-09-29

`scripts/backup_db_railway.sh`, with `scripts/gcs_backup.py` for the storage
steps. The laptop's `scripts/backup_db.sh` is unchanged, so the script you run
every morning does not change under you. Same flow and safeguards, in the same
order: dump, refuse a dump under 1 KB, upload, media copy (never deletes,
recordings excluded), prune `*.sql.gz` older than 30 days. What differs:

- the database comes from `DATABASE_URL`;
- there is no `gcloud` in the image, so upload, copy and prune use the
  google-cloud-storage library the app already has, as `backup-writer` from
  `GOOGLE_SA_BACKUP_JSON` (A4a); the media copy is server-side, bucket to bucket;
- production dumps are named `execsnowhq_prod_<stamp>.sql.gz`.

**Tested:** what is copied, what is pruned, and the order of the steps
(`tests/test_backup_railway.py`). **Not run:** it needs Railway and the backup
service account, so its first real run is C10, and D-check 9 restores it.

### B5. The row-count comparison — **[proven on the laptop]** 2026-09-29

`scripts/compare_row_counts.sh SOURCE TARGET` (a database name or a `postgres://`
URL on either side) runs an **exact** `count(*)` for every table in `public`,
prints both sides, and **exits 1 on any mismatch or on a table present on one
side only**. `django_q_*` tables are listed but never fail it, since they are
emptied on purpose (C4.4, C7.3). Read-only.

**Run for real:** `execsnowhq_dev` against itself gave 94 tables matching,
6,766 rows, exit 0. Two throwaway databases with a count mismatch, a table on
one side only and a differing queue table reported both problems, ignored the
queue, and exited 1. The throwaway databases were then dropped.

### B6. The rehearsal restore — into a throwaway database — **[to run]**

This is C4 in the timeline below. It uses a **third, temporary Postgres** added
to the demo environment for the day and deleted when the rehearsal is signed
off. **No service ever points at it.** It is used only by one-off commands
(`pg_dump`/`psql`, the row-count comparison, and one decryption check), so the
approved safety rules hold without needing a staging app: no worker, no web,
no Gmail callback, and the production key present only for the length of one
command. I report the row-count output verbatim, and the rehearsal counts as
passed only when you have read it.

### B7. The laptop becomes development-only — **[run]** 2026-10-02

- **`manage.py scrub_dev_data` now exists**, built to the spec in
  `05_dev_environment.md` §8, with one addition the spec could not have
  foreseen. **Until cutover, `execsnowhq_dev` on this laptop *is* production**,
  and it passes both of the spec's localhost checks. So the command also
  refuses that database by name, whatever else is true, and requires the target
  database's name typed as `--database <name>`. It rewrites every contact
  address, user address (`--keep-staff` keeps the practice's own sign-ins),
  phone number, suppression address, message address and parsed participant
  email to `.invalid`; empties CSV import rows; deletes Gmail connections, **all**
  `tenant_secret` rows (the Anthropic key too: the laptop uses its env
  fallback), Google sign-in tokens, outbox messages, queued jobs, magic links
  and stakeholder tokens; clears pre-call tokens; and turns `hold_all_digests`
  back on. Tested: every refusal, and a scrub after which nothing can receive,
  send or sign in (`tests/test_scrub_dev_data.py`). **Never run on real data.**
- **`scripts/refresh_dev_from_prod.sh` fixed.** Its `DEV_DB` was
  `execsnowhq_dev`, so run today it would have **dropped the production
  database** (it would have failed first at the Railway dump, but only because
  Railway does not exist yet). It now restores into `execsnowhq_local`, refuses
  unless `.env` points there, stops on the first SQL error, and calls the scrub
  with the typed name.
- Still to do at C11: the laptop's `.env` moves to `execsnowhq_local`, and
  `05_dev_environment.md` gets the post-move daily workflow next to the pre-move one.
- **Run 2026-10-02.** `execsnowhq_local` was restored from
  `execsnowhq_prod_20261002_080213.sql.gz`, stopping on the first error. The dump
  is from **Postgres 18.6**, not the 16 that C1 planned; its one 17+ line
  (`SET transaction_timeout = 0`) is dropped before restoring into the laptop's
  16. Checked against the database itself, not the scrub's report: no
  `tenant_secret`, `gmail_connection`, `socialaccount_socialtoken`, magic-link
  or allow-list rows; no Google access/refresh token, `sk-ant-` key or private
  key anywhere in the data, decoded Django-Q task history included. **Two gaps
  found and fixed in the scrub:** `dev_send_allowlist_entry` carried a client's
  real address (a localhost build sends REAL mail to those rows), and
  `import_row.preview` still held every CSV address after `raw` was emptied.
  **Not scrubbed, by spec:** real addresses inside free text (email bodies and
  raw headers, meeting transcripts, proposal excerpts, audit payloads). No send
  path reads them.
- The laptop's `.env` is `STORAGE_BACKEND=local`: with `gcs`, deleting a
  recording locally would have deleted production's object.
- All four services started against it, and the worker ran every schedule
  once with no failure. `refresh_dev_from_prod.sh` now restores from the
  newest nightly GCS dump (the live `railway run pg_dump` could not work: laptop
  `pg_dump` 16 cannot dump an 18 server). Run end to end, 5 s.

---

## Part C — the timeline

| # | Who | Step | Gate to continue |
|---|---|---|---|
| C0 | Owner | **A0**: the ruleset on `main` | Tell me |
| C1 | Owner | **A1**: Railway account, project, repo connected; **Postgres created at version 16** in both environments | Tell me |
| C2 | Claude | **B1** code on `dev`, suite green, pushed | Suite green, reported |
| C2a | Owner | **"release"** of B1 → `main` → **B2** first empty deploy | `web` boots |
| C3 | Owner | In one pass: **A2** both CNAMEs, **A3** OAuth URIs for both hosts, **A4** production and demo secrets, **A4a** backup SA, **A4b** demo bucket and SA | Both custom domains verified; the sign-in page loads on both |
| C3d | Claude | **B3**: seed the demo; you sign in to `demo.getexecutivesnow.com` and look around | The Demo banner shows; nothing sent (Outbox rows carry no delivery) |
| C4 | Claude | **The rehearsal**, into a throwaway Postgres (B6): | |
| | | C4.1 fresh laptop dump (`pg_dump --no-owner --no-privileges`), the same form as the final dump | Dump over the size floor |
| | | C4.2 restore into the throwaway database | `psql` exits 0, no errors in the log |
| | | C4.3 **one command with the production key in its environment**: decrypt every `tenant_secret` row, reporting *count decrypted / count total*, never the values | **All** decrypt |
| | | C4.4 **B5** row-count comparison, laptop vs throwaway | **Zero mismatches** |
| | | C4.5 time the whole run, then delete the throwaway database | Gives the length of the real freeze; the database is gone |
| C4r | Owner | Read the C4 report and confirm | Your yes |
| C5 | Both | **Part E** deletions, after your confirmation, then a fresh laptop backup | Deletions reported, backup ran |
| C6 | Owner + Claude | **The freeze.** A5: you stop qcluster and the dev server. I confirm no task is mid-flight: `django_q_ormq` empty of leased rows, and no `MeetingSourceFile` left in `parsing` (one was in `parsing` at 13:03 UTC today, so this check is not academic). | Nothing in flight |
| C7 | Claude | **The cutover**: | |
| | | C7.1 final `pg_dump` of the laptop database | Size floor |
| | | C7.2 restore into production Postgres. `web` was already migrated on the empty DB, so the restore goes into a **dropped and recreated** database, and then `migrate` confirms nothing is outstanding | `psql` exit 0; `showmigrations` shows nothing unapplied |
| | | C7.3 empty the Django-Q **queue** tables (build plan: stale jobs would replay). Keep `django_q_schedule` and run `ensure_schedules`, which realigns `next_run` so nothing fires as "missed" | Done |
| | | C7.4 **B5** row-count comparison, laptop vs production | **Zero mismatches.** Any mismatch stops the cutover and the laptop resumes as production. |
| | | C7.5 confirm **`hold_all_digests` is ON** in the production database | ON |
| | | C7.6 `web` restarted onto the restored database | Sign-in page |
| C8 | Owner | **A6** re-consent, then D-checks 1–5 | All pass |
| C9 | Claude | Only now: **`qcluster` scaled to 1** on Railway. Watch the first ticks, one Drive poll and one inbound poll. | D-checks 6–8 |
| C10 | Claude | **B4** backup cron enabled; first run triggered by hand | D-check 9 |
| C11 | Claude | **B7** laptop to development-only (done 2026-10-02) | Reported |
| C12 | Owner | Two weeks later: say so, and the old laptop database is deleted (dry-run first, per CLAUDE.md) | Your yes |

**Rollback, up to C9:** if any gate from C7 to C8 fails, production is not in
use yet. You restart qcluster and the dev server on the laptop, and the laptop is
production again. Nothing was written to it during the freeze, so nothing is lost.
**After C9** the two sides diverge. Rolling back then means a fresh dump from
Railway to the laptop, and that decision is yours.

---

## Part D — post-cutover verification

In this order. **Check 1 and check 6 have fixed positions and must not move.**

1. **`hold_all_digests` is ON before qcluster starts on Railway** (C7.5, before C9).
2. Google sign-in works on `https://app.getexecutivesnow.com`.
3. A magic link sent to yourself carries `https://app.getexecutivesnow.com/…`,
   not localhost, and signs you in.
4. Gmail reconnected (A6), with the send-as alias verified.
5. One test message from the app to yourself: delivered, shown in the Outbox as
   `sent`, `From` = `info@getexecutivesnow.com`.
6. **qcluster started (C9) only after 1–5.** The first `work.tick` runs and
   generates nothing, because digests are held.
7. **Decryption on production**: the Anthropic key works. Summarize one note, or
   run the smallest Claude call available, and see an `ai_call` row with
   `succeeded=true`.
8. **One Drive poll** completes. The folder health screen shows a fresh
   "last polled", and no file already recorded is read a second time (the
   restored cursor holds). **One inbound poll** completes without error.
9. **The backup cron ran**, its object is in `gs://execs-now-hq-db-backups/`,
   **and it has been restored into a throwaway database** and row-count-compared (build plan
   §5: a backup never restored is a hypothesis).
10. Strategy PDF renders on Railway (WeasyPrint's system libraries present).
11. A stored file (flyer or Outbox attachment) downloads with its real size.
    0 bytes would be the old media failure.
12. One real digest, approved by you, delivered to a real stakeholder. **This is
    your choice of when**, and it means turning `hold_all_digests` off for the
    tenant as a deliberate, logged action (PRD exit criterion 4).

Each check will be reported as passed-and-seen, failed, or not yet run.

---

## Part E — test data to delete before the move

**Applied 2026-09-29 18:08 MDT: 67 rows** (see "State at 2026-09-29, evening").

**The owner's decisions, 2026-09-29.** All deletions are **hard deletes**, run
**after 3 PM Mountain on 2026-09-29** (not before: a live session at 1 PM), as
fresh backup → dry run listing every row → the owner's yes.

| | Decision |
|---|---|
| E1 Test Testing | **Delete** (with its portal login) |
| E2 Testing again testing | **Delete** (with its portal login) |
| E3 Hj hj | **Keep** (owner, 2026-09-29, later): a webinar sign-up with a real address. Its portal login and task stay. |
| E4 Unknown 2 Unknown 2 | **Delete** |
| E5 Steven Paul | **Delete**, with his strategy session (by then in-call with 13 answers; confirmed as a mistaken entry, 18:08) |
| E6 Mike Eller | **Delete the 2026-09-28 contact, meeting and 8 tasks; keep the 2026-09-22 set; add the owner as attended-by on the kept meeting** |
| E7 Acme Facilities, Noble Baker | **Keep**, as the demo company and demo client |

**Do not merge the Mike Eller group** on the new Merge duplicates screen before
this runs. Merging would move the duplicate's 8 tasks onto the kept record;
E6 deletes them instead.

The findings under each row are unchanged below.

All rows belong to tenant Executives Now. The IDs are the first 8 characters of
the UUID. The full IDs are pulled fresh when I run the deletion.

### E1. Test Testing — contact `9d6b03a0`
- Email `test@testemail.com`, company **Acme Facilities**, created 2026-09-12.
- **Has a client-portal login**: membership `8f2b2d51`, role **ECC**, user
  `test@testemail.com`. Deleting the contact alone would **leave the login
  working** (the membership's contact link is `SET NULL`). The delete covers the
  membership and the user.
- Also: 1 stakeholder row and 1 digest row (both cascade with the contact).

### E2. Testing again testing — contact `98279b5f`
- Email `testing.again@testemail.com`, Acme Facilities, 2026-09-12.
- **Portal login**: membership `d2653bf3`, ECC, user
  `testing.again@testemail.com`. Handled as in E1.
- 1 stakeholder row, 1 digest row.

### E3. Hj hj — contact `aee46bf2`
- Email **`hjohn90975@aol.com`**, source "Webinar", Acme Facilities, 2026-09-11.
  **That address looks like a real mailbox, not a test domain.** Please confirm
  it is yours, or a test you made, before it goes.
- **Portal login**: membership `e803f394`, ECC, user `hjohn90975@aol.com`.
- A phone number, a pipeline position, 3 stage-change rows.
- **A task, "Follow up"** (`cd949a4e`, not started), with **2 notes linked to
  it**. The task's contact link is `SET NULL`, so the task would survive as an
  orphan. I propose deleting the task and its 2 notes as well.

### E4. Unknown 2 Unknown 2 — contact `7f5b82ed`
- No email, no company, source "Webinar", 2026-09-11. A phone number, a
  pipeline position, 1 stage change. Nothing else.

### E5. Steven Paul — contact `e45884fd`
- Email `stevenpaul03003667264@gmail.com`, 2026-09-28.
- **A draft strategy session**, `c8a6b39f`, created 2026-09-28. The session
  **blocks** the contact's deletion (`PROTECT`), so it is deleted first.
- A phone number, 1 contact-type link.

### E6. The duplicate Mike Eller, and its meeting

Why the duplicate exists. The same Drive file was read twice: version 12 on
2026-09-22, then version 13 on 2026-09-28, with identical text (104,232
characters). The second read became a **second proposal** instead of being
skipped as unchanged. On that second proposal the matcher **did** offer the
existing Mike Eller (match by email, 0.98), and a new contact was created anyway.
Both are findings about Phase 5, reported with the metric below, and **neither
has been changed today**.

| | Keep (original, 2026-09-22) | Delete (duplicate, 2026-09-28) |
|---|---|---|
| Contact | `047876e1` | `16c9f352` |
| Meeting | `0e5e6562`, participants: Mike only | `686f3ff7`, participants: Bryan + Mike |
| Proposal | `fdd8c1b0` | `06d16d47` |
| Tasks from it | 9 | **8, duplicates of the 9** (all `not_started`, one creation entry each, no work on them) |

**Proposal:** delete the 2026-09-28 contact, its meeting and **its 8 duplicate
tasks**. Your list named the contact and the meeting but not the tasks. Keep the
2026-09-22 set. Then add you as *attended-by* on the kept meeting with the
existing `recognise_practice_participants` command (dry-run shown first), which
restores the one thing the duplicate had that the original lacks. The two
proposals and source files stay as history. The v13 file stays recorded, so it
will not be read a third time.

The 8 tasks to delete: `dd366d86`, `5c01893d`, `f33f6736`, `da1e49e0`,
`ed49493a`, `303e8887`, `6d356f24`, `69d9ed54`.

### E7. For you to decide — not on your list

- **Acme Facilities** (company `0bddb077`, created 2026-09-09). Three of its
  four contacts are E1–E3. The fourth is **Noble Baker** (2026-09-12). It has 4
  portal memberships and 6 tasks against it. If Acme is a test company, it and
  Noble Baker probably go too. If it is real, only E1–E3 leave it. **I have not
  assumed either.**

### How the deletion will run, once you confirm

1. A fresh backup first (CLAUDE.md: significant data is about to change).
2. A **dry run** printing every row to be deleted, grouped as above, with
   counts. **Nothing is written.** You read it.
3. On your yes: one transaction per group (E1…E6), each audited, and a
   row-count before/after per affected table.
4. Everything uses the app's own delete paths where they exist (contacts are
   soft-deleted through the same path as the contact screen's Delete, which
   writes `contact.deleted`), and a hard delete only where you ask for one. **For
   the move, soft-deleted rows travel with the restore.** If you want them gone
   from production entirely, say "hard delete" and the dry run will show that
   instead.

---

## What this runbook assumes and has not checked

- Railway's current UI names (Custom domain, Variables, cron schedule,
  replicas). They are written from how Railway is normally laid out, and I will
  correct them against the real screens at A1/B1.
- The laptop's Postgres major version against Railway's. I check both before C4.
- The freeze length. C4.7 measures it. Until then it is unknown.
- That the restored Gmail and Drive refresh tokens keep working from a new
  origin. They should, because a refresh does not use the redirect URI, but A6
  reconnects them anyway so we do not depend on it.
