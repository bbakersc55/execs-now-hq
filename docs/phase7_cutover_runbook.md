# Phase 7 — Cutover runbook: laptop → Railway

*Written 2026-09-29. Preparation only: nothing below has been run. Nothing has
been deleted and the app has not moved.*

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
**[to run]** or **[to build]**. As of 2026-09-29: B0 proven; B1, B4 and B7 built
and tested locally, not run on Railway; B5 proven on the laptop; everything else
to run.

---

## Branching — in effect from 2026-09-29

- **`dev`** is the working branch. Every change lands there and is pushed there.
- **`main`** is production. Once Railway is connected, **a push to `main`
  deploys to `app.getexecutivesnow.com`** (build plan Phase 7 §1).
- **I merge `dev` → `main` only when you say "release".** The gate is the
  **full test suite, green on `dev` at the commit being merged**. A red suite
  means no merge, whatever the change.
- The staging service (B3) deploys from **`dev`**. So "pushed to dev" means
  "live on staging", and "release" means "live in production". This replaces the
  separate `staging` branch that the Phase 8+ note proposed. One working branch
  is enough while one person releases.
- **The GitHub rule on `main`: approved (owner, 2026-09-29), and it is step
  A0 below.** It is yours because this laptop has no `gh` CLI and no GitHub
  token for me to set it with.

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
   Postgres, three app services and staging will exceed the free allowance.
2. Create one **project** named `execs-now-hq`. Make two **environments** in it:
   `production` and `staging`. Each environment gets its own Postgres (B1, B3),
   **at version 16**, to match the laptop and the image's `pg_dump`. If Railway
   offers only a newer version, stop and tell me, because the Dockerfile
   changes with it.
3. Connect the GitHub repo `bbakersc55/execs-now-hq` to the project. This is
   Railway's GitHub app, and it asks for access to that repo only. Grant access
   to this repo only, not "all repositories".
4. Invite nobody else for now.
5. Tell me it is done. I do the service configuration (B1). Adding a service
   yourself is fine too, but leave its settings to me so the three services match.

### A2. DNS — CNAME for `app.getexecutivesnow.com` — *after B1 gives you the target*

1. Once the production web service exists, Railway → web service → Settings →
   Networking → **Custom domain** → `app.getexecutivesnow.com`. Railway shows a
   CNAME target, something like `xxxx.up.railway.app`.
2. At your DNS host for `getexecutivesnow.com`, add a **CNAME** record:
   - Name: `app`
   - Target: the value Railway shows
   - TTL: the lowest your host allows (300 s is typical) until cutover is done
3. Change nothing else. **Do not touch the MX, SPF, DKIM or DMARC records.**
   Workspace mail depends on them, and the app needs no DNS records of its own
   in Beta (build plan Phase 7 §2).
4. Railway issues the TLS certificate once the CNAME resolves. Tell me when the
   custom domain shows as verified.

Pointing the CNAME early is safe. Until cutover, the domain serves staging-grade
emptiness: the production database stays empty until the final restore (B6).

### A3. Google OAuth — redirect URIs for the new host — *before C5*

In the **`execs-now-hq`** GCP project → APIs & Services → Credentials → the
existing **Web application** OAuth client (the one the laptop uses). **Add these
URIs. Remove none.** The localhost URIs must stay, because the laptop remains the
development machine.

**Authorised JavaScript origins**, add:
- `https://app.getexecutivesnow.com`

**Authorised redirect URIs**, add both. They are two different consents, and a
missing one fails at Google's screen with `redirect_uri_mismatch`:
- `https://app.getexecutivesnow.com/accounts/google/login/callback/` (signing in)
- `https://app.getexecutivesnow.com/accounts/gmail/callback` (Gmail **and** Drive
  consent; both use this one callback)

**For staging**, only if you want to sign in to staging with Google during the
rehearsal (recommended, because it proves sign-in before the real move), also add
the staging host I give you in B3:
- `https://<staging-host>/accounts/google/login/callback/`
- Do **not** add the staging Gmail callback. Staging must never hold a working
  Gmail or Drive grant (see B3).

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

**Staging gets its own values, not production's:** a different
`DJANGO_SECRET_KEY` and a different `FIELD_ENCRYPTION_KEY`, **except during the
one rehearsal step C4.3**, where staging temporarily holds the production key to
prove decryption. B3 and C4 say exactly when it goes in and when it comes out.

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
2. **Settings → Gmail → Reconnect.** Tick reply collection
   (`gmail.readonly`), as on the laptop. Confirm the send-as alias
   `info@getexecutivesnow.com` shows as verified.
3. **Meeting queue → Drive folder → Reconnect Drive.** Confirm both watched
   folders still read back with their names and file counts ("Meet Recordings"
   and "Google Meet" with the Gemini pattern), and that the exclusion list
   (`AoA`, `Academy of America`) is still there.
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

### B2. The first deploy, empty — **[to run]**

1. For the first production deploy I ask you for a **"release"** of the B1
   code, with the suite green as always.
2. `web` refuses to start on the empty database (`migrate --check`). That is
   the point of the check. I apply the migrations in the service shell. The
   database is empty, so there is nothing to back up. Then `web` starts.
   Seeing the sign-in page at `https://app.getexecutivesnow.com` proves the
   image, WeasyPrint's libraries, the proxy settings, TLS and DNS, with no data
   at stake.
3. Nobody signs in to production yet. There is no tenant in it until C7.

### B3. The staging service, with its own database — **[to run]** · safety design **approved by the owner, 2026-09-29**

The `staging` environment mirrors production: `web` only (from **`dev`**), its
own `Postgres` at 16, and a Railway-generated domain that I give you for A3.

**What makes staging safe to hold a copy of real data** (approved as proposed):

- **Staging never runs `qcluster`.** It gets no qcluster service at all. The
  worker is what polls Drive (Claude spend on your key), polls your mailbox, and
  generates and sends digests. With no worker, none of that can happen.
- **Staging's own `FIELD_ENCRYPTION_KEY`**, different from production's, except
  during the one rehearsal step that proves decryption (C4.3). Afterwards the
  restored `tenant_secret` rows are deleted from staging, so staging holds no
  working Gmail, Drive or Anthropic credential.
- **No Gmail callback URI for staging** (A3), so nobody can connect Gmail there
  by accident.
- **The Django-Q schedule and queue tables are emptied** on staging after every
  restore, so nothing is queued even if a worker were ever added.
- The rehearsal data is **dropped** from staging once the rehearsal is signed
  off. Staging then holds seeded demo data only (the Phase 8+ demo tenant).
- Staging's `CSRF_TRUSTED_ORIGINS` names its own host, and its
  `DJANGO_ALLOWED_HOSTS` names its host and the health check's.

**Web requests on staging can still send mail when someone clicks send**, since
`PUBLIC_BASE_URL` is not localhost there. With no Gmail credential that decrypts,
a send fails rather than delivers. That failure is the safeguard, and D-check 5's
equivalent on staging is to confirm the failure happens.

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

### B6. The rehearsal restore into staging — **[to run]**

This is C4 in the timeline below. I run it, report the row-count output
verbatim, and the rehearsal counts as passed only when you have read it.

### B7. The laptop becomes development-only — **[built, not run]** 2026-09-29

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

---

## Part C — the timeline

| # | Who | Step | Gate to continue |
|---|---|---|---|
| C0 | Owner | **A0**: the ruleset on `main` | Tell me |
| C1 | Owner | **A1**: Railway account, project, repo connected; **Postgres created at version 16** in both environments | Tell me |
| C2 | Claude | **B1** code on `dev`, suite green, pushed | Suite green, reported |
| C2a | Owner | **"release"** of B1 → `main` → **B2** first empty deploy | `web` boots |
| C3 | Owner | **A2** DNS CNAME, **A3** OAuth URIs, **A4** production secrets, **A4a** backup SA | Custom domain verified; sign-in page loads at `https://app.getexecutivesnow.com` |
| C4 | Claude | **The rehearsal**, into staging: | |
| | | C4.1 fresh laptop dump (`pg_dump --no-owner --no-privileges`), the same form as the final dump | Dump over the size floor |
| | | C4.2 restore into staging Postgres | `psql` exits 0, no errors in the log |
| | | C4.3 **with the production key set on staging temporarily**: decrypt every `tenant_secret` row in a management shell, reporting *count decrypted / count total*, never the values | **All** decrypt |
| | | C4.4 empty the Django-Q queue and schedule tables on staging; delete `tenant_secret` rows; swap staging back to its own key | Done, reported |
| | | C4.5 **B5** row-count comparison, laptop vs staging | **Zero mismatches** apart from the tables C4.4 emptied |
| | | C4.6 sign in to staging with Google (if A3's staging URI was added); open a contact, a meeting, a strategy PDF, a flyer attachment (GCS media reached from Railway) | All open |
| | | C4.7 time the whole run | Gives the length of the real freeze |
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
| C11 | Claude | **B7** laptop to development-only | Reported |
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
7. **Decryption on production**: the Anthropic key works. Summarise one note, or
   run the smallest Claude call available, and see an `ai_call` row with
   `succeeded=true`.
8. **One Drive poll** completes. The folder health screen shows a fresh
   "last polled", and no file already recorded is read a second time (the
   restored cursor holds). **One inbound poll** completes without error.
9. **The backup cron ran**, its object is in `gs://execs-now-hq-db-backups/`,
   **and it has been restored into staging** and row-count-compared (build plan
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

**Nothing here has been deleted.**

**The owner's decisions, 2026-09-29.** All deletions are **hard deletes**, run
**after 3 PM Mountain on 2026-09-29** (not before: a live session at 1 PM), as
fresh backup → dry run listing every row → the owner's yes.

| | Decision |
|---|---|
| E1 Test Testing | **Delete** (with its portal login) |
| E2 Testing again testing | **Delete** (with its portal login) |
| E3 Hj hj | **Not decided.** The decision line was left as its placeholder, `[DELETE / KEEP AND RENAME — fill in after checking]`. The same message also says "delete Acme's other three test contacts", and Hj hj is one of those three, so the two instructions disagree. **Held out of the deletion until the owner says which.** |
| E4 Unknown 2 Unknown 2 | **Delete** |
| E5 Steven Paul | **Delete**, with his draft strategy session |
| E6 Mike Eller | **Delete the 2026-09-28 contact, meeting and 8 tasks; keep the 2026-09-22 set; add the owner as attended-by on the kept meeting** |
| E7 Acme Facilities, Noble Baker | **Keep**, as the demo company and demo client |

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
