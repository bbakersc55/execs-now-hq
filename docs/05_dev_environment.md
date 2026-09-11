# 05 — Development Environment

**Phase 0 · Execs NOW HQ**

This is a runbook, not an explanation. Commands to paste, in order, with just enough context to know when to use them.

**Target for every code block:** your local terminal, from `~/projects/execs-now-hq`, unless the block says otherwise.

---

## 1. One-time setup

Already done (per the kickoff): repo, `git init`, `CLAUDE.md`, `.claude/settings.json`, GCP project `execs-now-hq`, bucket `gs://execs-now-hq-db-backups`, gcloud ADC.

What remains:

```bash
# System packages (Debian/Ubuntu)
# NOTE: postgresql (the SERVER), not just postgresql-client. CLAUDE.md requires
# Postgres locally from day one; the client alone gives you psql with nothing to
# connect to.
sudo apt install -y python3.12 python3.12-venv build-essential \
                    postgresql postgresql-client libpq-dev \
                    libpango-1.0-0 libpangoft2-1.0-0 libcairo2   # WeasyPrint needs these

# Start the server and create your role + database
sudo systemctl enable --now postgresql
sudo -u postgres createuser --superuser "$USER"      # peer auth for your own account
createdb execsnowhq_dev

# Verify: this must print the database name
psql -lqt | cut -d'|' -f1 | grep execsnowhq_dev

# Python
python3.12 -m venv .venv
.venv/bin/pip install --upgrade pip

# Node (for Vite) — nvm or system Node 20+
node --version   # expect v20 or newer
```

**Mailpit** — the local dev outbox (assumption A4). Everything the app sends lands here unless the recipient is in `DEV_REAL_SEND_ALLOWLIST`.

```bash
# Binary install, no Docker needed
sudo bash -c "curl -sL https://raw.githubusercontent.com/axllent/mailpit/develop/install.sh | bash"
mailpit --version
```

**No Redis.** Django-Q2 runs on the ORM broker against Postgres (assumption A2).

---

## 2. Ports

| Service | Port | Notes |
|---|---|---|
| Django | **8100** | `CLAUDE.md` — deliberately unusual |
| Vite | **5200** | proxies `/api` and `/admin` to 8100 |
| Postgres | 5432 | system default; database `execsnowhq_dev` |
| Mailpit SMTP | 1025 | Django's `EMAIL_PORT` |
| Mailpit web | **8125** | where you read dev mail |

```bash
# Confirm nothing else is on the app ports before you start
ss -ltnp | grep -E ':(8100|5200|8125)' || echo "ports clear"
```

---

## 3. `.env.example`

Kept current in the same commit as any new variable (assumption E2). Copy to `.env` and fill in.

```bash
# ---------- Core ----------
DJANGO_SECRET_KEY=change-me-generate-a-new-one
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
PUBLIC_BASE_URL=http://localhost:8100
# ^ THE most consequential variable here. While this is localhost, outbound mail
#   goes to Mailpit unless the recipient is in DEV_REAL_SEND_ALLOWLIST.

# ---------- Database ----------
# Empty host = connect over the local Unix socket using peer auth, which needs
# no password. A TCP form (postgres://user@localhost:5432/db) requires a
# password to be configured in Postgres first.
DATABASE_URL=postgres:///execsnowhq_dev

# ---------- Encryption ----------
# Fernet key protecting tenant_secret.ciphertext (Anthropic key, OAuth tokens).
# Generate: .venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# NEVER commit. If lost, every stored secret is unrecoverable.
FIELD_ENCRYPTION_KEY=

# ---------- Background jobs ----------
Q_CLUSTER_WORKERS=4
# >=4 so a long transcription cannot sit in front of a digest (assumption A2).

# ---------- Email ----------
EMAIL_HOST=localhost
EMAIL_PORT=1025

# Beta: all app mail goes through the tenant's connected Gmail, From = their
# send-as alias. Postmark is a per-tenant transport option in V1.
APP_MAIL_TRANSPORT=gmail

# --- Postmark: OPTIONAL in Beta. Leave blank unless APP_MAIL_TRANSPORT=postmark ---
POSTMARK_SERVER_TOKEN=
POSTMARK_TRANSACTIONAL_STREAM=outbound
POSTMARK_BROADCAST_STREAM=broadcast
# Module 6: the inbound webhook verifies before processing (FR-6.11).
POSTMARK_INBOUND_WEBHOOK_SECRET=
DEFAULT_FROM_ADDRESS=info@getexecutivesnow.com
INBOUND_DOMAIN=inbound.getexecutivesnow.com

# Exact addresses that receive REAL mail from this laptop build (assumption H6).
# Comma-separated. EXACT ADDRESSES ONLY — a domain wildcard is rejected at startup.
DEV_REAL_SEND_ALLOWLIST=bryan.baker@getexecutivesnow.com

# ---------- Anthropic ----------
# Dev fallback only, used when the tenant has no stored key. Refused when
# PUBLIC_BASE_URL is not localhost (assumption E1.6).
ANTHROPIC_API_KEY=
# The model string the app calls. Changeable without a code change.
ANTHROPIC_MODEL=claude-opus-5

# ---------- Google ----------
GOOGLE_OAUTH_CLIENT_ID=
GOOGLE_OAUTH_CLIENT_SECRET=
GOOGLE_CLOUD_PROJECT=execs-now-hq
# The app's OWN Google API calls (Speech-to-Text, GCS media, Drive where it is
# not acting on a tenant's OAuth token) use a dedicated service-account key.
# Path is OUTSIDE the repo and never committed. The backup script does NOT use
# this — it uses the gcloud CLI. The app never uses gcloud ADC (assumption A7).
GOOGLE_APPLICATION_CREDENTIALS=~/.config/execs-now-hq/sa-app.json
GOOGLE_STT_LANGUAGE=en-US
# Where stored_file CONTENT lives. gcs = gs://$GCS_BUCKET_MEDIA/<object_key>,
# read and written with the key above. `local` (MEDIA_ROOT/<bucket>/<key>) is
# for the test suite and the restore drill only; refused off localhost.
STORAGE_BACKEND=gcs
GCS_BUCKET_MEDIA=execs-now-hq-media
# Only read when STORAGE_BACKEND=local.
MEDIA_ROOT=

# ---------- Backups ----------
BACKUP_BUCKET=gs://execs-now-hq-db-backups
BACKUP_RETENTION_DAYS=30

# ---------- Errors ----------
SENTRY_DSN=
# Enabled only when PUBLIC_BASE_URL is not localhost (assumption A5).
```

---

## 4. DNS — **nothing to add for Beta**

**Beta needs no DNS records at all.** All app-originated mail goes out through the tenant's connected Gmail with `From` set to a send-as alias (assumption A3), and replies come back by polling that same mailbox. There is no sending domain to authenticate and no inbound domain to receive on.

What you need instead is a **Gmail "Send mail as" alias**, which is §5c below.

**These records return in V1**, when Postmark becomes a per-tenant transport option. Recorded here so the requirement is not rediscovered from scratch:

| # | Purpose | Type | Host | Value |
|---|---|---|---|---|
| 1 | DKIM — signs outbound | `TXT` | `<selector>._domainkey` | *(from Postmark)* |
| 2 | Return-Path — custom bounce domain | `CNAME` | `pm-bounces` | `pm.mtasv.net` |
| 3 | Inbound MX — receives client replies | `MX` | `inbound` | `inbound.postmarkapp.com` (priority `10`) |

**The one DNS record Beta eventually needs** is `app.getexecutivesnow.com` → Railway, at the Phase 7 move. It is a single A/CNAME, so DNS is no longer the long pole it was under the Postmark plan.

## 5. Google setup

Two separate credentials, for two separate purposes. Keeping them apart is deliberate.

| | Used for | Credential |
|---|---|---|
| **OAuth client** | *A person* signing in, and the app acting **as that person** (Gmail send) | OAuth consent screen + client ID/secret |
| **Service account** | The app acting **as itself** — Speech-to-Text, GCS media, Drive where no tenant token applies | Key file at `GOOGLE_APPLICATION_CREDENTIALS` |
| **gcloud CLI (ADC)** | **Backups only** | Your existing `gcloud auth application-default login` |

### 5a. OAuth client — user type **Internal**

In the **`execs-now-hq`** GCP project, configure the OAuth consent screen with **User type: Internal**, then create an OAuth client (Web application):

- Authorised origins: `http://localhost:5200`, `http://localhost:8100`
- Redirect URIs — **both are required**, they are two different consents (C2):
  - `http://localhost:8100/accounts/google/login/callback/` — signing in
  - `http://localhost:8100/accounts/gmail/callback` — connecting Gmail to send

**A missing second URI fails at the consent screen**, not in the app: Google returns
`redirect_uri_mismatch` before the user ever sees a permission list.

**Internal, not External/Testing** — you are on Google Workspace at `getexecutivesnow.com`, which makes Internal available, and it is strictly better here for two reasons:

1. **No verification is required for `gmail.send`**, even though it is a restricted scope.
2. **No 7-day refresh-token expiry.** External apps left in *Testing* expire refresh tokens after seven days, which would silently break every Gmail connection and every Drive watch about once a week — a failure that looks like a bug and is not.

**The consequence, and it is a real constraint:** only `@getexecutivesnow.com` accounts can sign in with Google. **Any CF or VA you bring on needs an account in your Workspace domain.** Client users are unaffected — they use magic links (C3, C4) and never touch Google.

Switching to **External with CASA verification** is the V1 task, needed before another fractional's practice can use the app. It is slow and expensive, and it is the longest lead time in the V1 plan.

### 5b. Service account for the app's own API calls

**Done 2026-09-11** (Phase 2 prerequisite). Recorded here as it was actually run, which
differs from the Phase 0 draft in two places, both noted inline.

```bash
# APIs. IAM to create the account and key; Org Policy to scope the override below.
gcloud services enable iam.googleapis.com speech.googleapis.com orgpolicy.googleapis.com \
  --project=execs-now-hq

# The media bucket — private, same region as the backups.
gcloud storage buckets create gs://execs-now-hq-media --project=execs-now-hq \
  --location=us-west3 --default-storage-class=STANDARD \
  --uniform-bucket-level-access --public-access-prevention

# DIFFERENCE 1: the organization enforces iam.disableServiceAccountKeyCreation
# (Google's secure-by-default for newer Workspace orgs), so the key command below
# is refused without this. It is overridden for THIS PROJECT ONLY; the org-wide
# rule stays on. Needs roles/orgpolicy.policyAdmin at the org.
cat > /tmp/execs-now-hq-sa-key-policy.yaml <<'EOF'
name: projects/execs-now-hq/policies/iam.disableServiceAccountKeyCreation
spec:
  rules:
  - enforce: false
EOF
gcloud org-policies set-policy /tmp/execs-now-hq-sa-key-policy.yaml

gcloud iam service-accounts create execs-now-hq-app \
  --display-name="Execs NOW HQ application runtime" \
  --project=execs-now-hq

# Minimum roles — no project-wide editor
gcloud projects add-iam-policy-binding execs-now-hq \
  --member="serviceAccount:execs-now-hq-app@execs-now-hq.iam.gserviceaccount.com" \
  --role="roles/speech.client" --condition=None

# DIFFERENCE 2: storage on the MEDIA BUCKET, not the project. Project-wide
# objectAdmin would let a leaked app key delete the database backups too.
# tests/test_storage.py::test_live_key_cannot_touch_the_backup_bucket asserts the 403.
gcloud storage buckets add-iam-policy-binding gs://execs-now-hq-media \
  --member="serviceAccount:execs-now-hq-app@execs-now-hq.iam.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"

# Key file, OUTSIDE the repo
mkdir -p ~/.config/execs-now-hq && chmod 700 ~/.config/execs-now-hq
gcloud iam service-accounts keys create ~/.config/execs-now-hq/sa-app.json \
  --iam-account=execs-now-hq-app@execs-now-hq.iam.gserviceaccount.com
chmod 600 ~/.config/execs-now-hq/sa-app.json
```

**Verify the key the way the app uses it** — this talks to the real bucket, writes
under `_selftest/`, and deletes what it wrote:

```bash
RUN_GCS_LIVE=1 .venv/bin/pytest tests/test_storage.py -m gcs_live -v
```

**Why a key file rather than the ADC you already have:** your laptop's ADC is shared with another project and its quota-project setting cannot serve both at once — the app would intermittently bill or fail against the wrong project. A key file also makes **development identical to Railway**, where there is no interactive gcloud login and a key file is the only option. Discovering that difference at cutover is avoidable.

**`scripts/backup_db.sh` continues to use the gcloud CLI and your ADC.** It is the one thing that does.

### 5c. The Gmail send-as alias — **required before any app mail sends**

Beta routes **every** app-originated message — magic links, digests, referral touches, strategy PDFs, pre-call invites — through your connected Gmail, with `From` set to `info@getexecutivesnow.com`. Gmail will only let you do that if the address is a confirmed alias on your account.

1. In Gmail: **Settings → See all settings → Accounts and Import → "Send mail as" → Add another email address**.
2. Enter `info@getexecutivesnow.com`. Leave **"Treat as an alias"** ticked.
3. Gmail sends a confirmation email to that address. **Open it and click the link** — an alias that is listed but unconfirmed will not work.
4. In Execs NOW HQ, go to **Email settings** in the sidebar, click **Connect Gmail**, then **Verify alias**. The app reads your `settings.sendAs` list, shows you every address on it, and confirms the alias is present *and* accepted. `docs/phase1_manual_checks.md` Step 0 is the click path.

**If it is not verified, the app refuses to send** and tells you which addresses *are* available. There is deliberately no fallback to your personal address: a client digest arriving from `bryan@…` instead of `info@…` is worse than a visible failure.

**Scopes this needs:** `gmail.send` to send, `gmail.settings.basic` to read the alias list, and `gmail.readonly` for Module 6's reply polling. All three are restricted scopes; all three are **free under the Internal consent screen** — no verification, no CASA assessment, no 7-day token expiry.

**Three trade-offs you accepted** in choosing this over Postmark:
1. **Magic links depend on this token.** If the Gmail connection breaks, client sign-in stops until you reconnect. The app says so explicitly rather than failing generically.
2. **App mail lands in your Sent folder.** Every digest and touch is sent by your account.
3. **No third-party delivery log.** The Outbox is the only send log; bounces show up in Gmail.

Enable in the same project: **Gmail API**, **Google Drive API**, **Cloud Speech-to-Text API**, **Cloud Storage**.

---

## 6. Every session — the pre-Railway workflow

Four terminals, or a `tmux` session. This is what you run each time you sit down.

```bash
cd ~/projects/execs-now-hq

# 0. Select this project's gcloud configuration. The owner keeps one named
#    configuration per project; without this, backups and the app's Google
#    calls can run against whichever project was last active.
gcloud config configurations activate execs-now-hq

# 1. Back up first. Cheap, and it means an experiment is never irreversible.
./scripts/backup_db.sh

# 2. Django                                   [terminal 1]
.venv/bin/python manage.py runserver 8100

# 3. Background jobs                          [terminal 2]
.venv/bin/python manage.py qcluster

# 4. Frontend                                 [terminal 3]
npm run dev            # Vite on 5200

# 5. Dev outbox                               [terminal 4]
mailpit --smtp localhost:1025 --listen localhost:8125
```

Then open **http://localhost:5200** for the app and **http://localhost:8125** for mail.

**`qcluster` must be running** or digests never generate, Drive never polls, and transcriptions never finish. If something "isn't happening," check terminal 2 first.

**`qcluster` does not reload on code changes** (`runserver` does). After pulling or changing code, restart it — a cluster started before a migration runs the old models and fails every job that touches the new columns.

**Periodic jobs are registered by one command**, idempotent, safe to re-run after every pull:

```bash
.venv/bin/python manage.py ensure_schedules
```

It declares every schedule in one list (`apps/tenancy/management/commands/ensure_schedules.py`): referral-touch drafting daily at 06:00 tenant time, Outbox expiry and contact reindex hourly, note processing every minute, audio retention daily. Re-running never moves a schedule's next run. Until Phase 2 nothing registered a schedule at all.

Common commands:

```bash
.venv/bin/python manage.py makemigrations      # never applied without showing you first
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
.venv/bin/pytest                                # full suite
.venv/bin/pytest -k "isolation or role"         # the two mandatory families
RUN_GCS_LIVE=1 .venv/bin/pytest -m gcs_live -k storage   # the app's key against the real bucket
RUN_STT_LIVE=1 .venv/bin/pytest tests/test_stt_live.py    # real Speech-to-Text on a 12 s fixture (cents)
.venv/bin/python manage.py dev_va_login          # LOCAL ONLY: one-time sign-in link for a test VA; --remove to revoke
.venv/bin/python manage.py replay_inbound fixtures/inbound/token_match.json   # Module 6
```

---

## 7. The backup script

`scripts/backup_db.sh` — uses **gcloud ADC**, not a service-account key file (kickoff §I).

**It backs up two things, because the database alone is not a restorable system.**
A `stored_file` row records a bucket, an object key and a size; the bytes live in
`gs://execs-now-hq-media`. Restoring the dump without the blobs gives you rows describing
files that do not exist — which is precisely the 0-byte-attachment failure from Check 5,
reintroduced by the backup itself.

> **Why the media sync runs AFTER the dump, and not before.** A file uploaded in the
> window between the two ends up in the backup as bytes with no row: a harmless orphan
> blob. Reverse the order and the same window produces a row with no bytes, which
> restores as a file that opens empty. One direction wastes a little space; the other
> loses data silently.

> **The media copy is never pruned — and so recordings are not in it.** Retention matches
> `*.sql.gz` only. A flyer from last year is still the flyer attached to live drafts, and
> `rsync` runs without `--delete-unmatched-destination-objects` on purpose — this is a
> backup, not a mirror, so a file deleted by accident stays recoverable.
>
> That same property is why **recording audio is excluded** (owner decision, Phase 2): a
> never-pruned copy would keep every recording forever and quietly break
> `audio_retention_days`. Recordings rely on GCS durability plus the media bucket's 7-day
> soft delete. `apps/tenancy/storage.py` refuses to store `recording_audio` anywhere but
> `recordings/`, and refuses anything else there, so the one `--exclude` is the whole rule.
> Verified 2026-09-11 with a probe object: copied without the exclude, skipped with it.

```bash
#!/usr/bin/env bash
# Nightly + on-demand backup of execsnowhq_dev to GCS. 30-day retention.
#
# Backs up TWO things, because the database alone is not a restorable system:
# the Postgres dump, and the media bucket that `stored_file` rows point at
# (marketing flyer, Outbox attachments, strategy PDFs). A dump without the blobs
# restores rows describing files that do not exist — which is exactly the
# 0-byte-attachment failure, reintroduced by the backup.
#
# Recording audio is NOT copied (owner decision, Phase 2). A never-pruned copy
# would keep every recording forever and make audio_retention_days a promise
# the backup breaks. Recordings rely on GCS durability plus the bucket's 7-day
# soft delete. storage.py forces all recording audio under recordings/, so the
# exclude below is the whole rule.
set -euo pipefail

DB_NAME="execsnowhq_dev"
BUCKET="gs://execs-now-hq-db-backups"
MEDIA_BUCKET="gs://execs-now-hq-media"
# Keeps the <bucket>/<object_key> layout the restore drill already expects.
MEDIA_DEST="${BUCKET}/media/execs-now-hq-media"
RECORDINGS_EXCLUDE='^recordings/'
RETENTION_DAYS=30
STAMP="$(date +%Y%m%d_%H%M%S)"
TMP="$(mktemp -d)"
FILE="${TMP}/${DB_NAME}_${STAMP}.sql.gz"

trap 'rm -rf "${TMP}"' EXIT

echo "==> Dumping ${DB_NAME}"
pg_dump --no-owner --no-privileges "${DB_NAME}" | gzip -9 > "${FILE}"

SIZE=$(stat -c%s "${FILE}")
if [ "${SIZE}" -lt 1024 ]; then
  echo "!! Dump is ${SIZE} bytes — refusing to upload a probably-empty backup" >&2
  exit 1
fi
echo "==> Dump OK (${SIZE} bytes)"

echo "==> Uploading to ${BUCKET}"
gcloud storage cp "${FILE}" "${BUCKET}/"

# --------------------------------------------------------------------------
# Media, AFTER the dump. The order is not arbitrary.
#
# Anything uploaded BETWEEN the dump and the rsync ends up in the backup as
# bytes with no row — a harmless orphan blob. Run the rsync first and the same
# window produces the opposite: a row with no bytes, which restores as a file
# that opens empty. One direction wastes a little space; the other loses data
# silently. So: dump, then media.
#
# Bucket to bucket, same region: a server-side copy, nothing passes through
# this machine.
# --------------------------------------------------------------------------
echo "==> Syncing ${MEDIA_BUCKET} to ${MEDIA_DEST} (excluding ${RECORDINGS_EXCLUDE})"
# No --delete-unmatched-destination-objects on purpose: this is a backup, not
# a mirror. A file deleted by accident stays recoverable here, which is the
# entire reason the copy exists.
gcloud storage rsync --recursive --exclude="${RECORDINGS_EXCLUDE}" \
  "${MEDIA_BUCKET}" "${MEDIA_DEST}"
echo "==> Media sync OK"

echo "==> Pruning backups older than ${RETENTION_DAYS} days"
CUTOFF=$(date -u -d "${RETENTION_DAYS} days ago" +%Y-%m-%dT%H:%M:%SZ)
# Only ever matches *.sql.gz, so the media mirror is never pruned by age — a
# flyer from last year is still the flyer that is attached to live drafts.
gcloud storage ls --long "${BUCKET}/**" 2>/dev/null \
  | awk -v c="${CUTOFF}" '$2 < c && $3 ~ /\.sql\.gz$/ {print $3}' \
  | while read -r old; do
      echo "    deleting ${old}"
      gcloud storage rm "${old}"
    done

echo "==> Done: $(basename "${FILE}") + media"
```

```bash
chmod +x scripts/backup_db.sh
```

**Nightly, via a systemd user timer** — not cron.

**Why not cron:** cron fires at a wall-clock time and, if the machine is asleep or off at 02:30, **that backup simply never happens** and nothing tells you. A systemd timer with `Persistent=true` records the last run and **fires as soon as the machine is next up** if a scheduled run was missed. On a laptop that closes at night, that is the difference between a nightly backup and an occasional one.

`~/.config/systemd/user/execsnowhq-backup.service`:

```ini
[Unit]
Description=Execs NOW HQ database backup to GCS
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=%h/projects/execs-now-hq
ExecStart=%h/projects/execs-now-hq/scripts/backup_db.sh
StandardOutput=append:%h/.execsnowhq_backup.log
StandardError=append:%h/.execsnowhq_backup.log
```

`~/.config/systemd/user/execsnowhq-backup.timer`:

```ini
[Unit]
Description=Nightly Execs NOW HQ backup

[Timer]
OnCalendar=*-*-* 02:30:00
# Run a missed backup at next boot instead of skipping it.
Persistent=true
# Avoid every timer firing at once on wake.
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
```

Enable it:

```bash
systemctl --user daemon-reload
systemctl --user enable --now execsnowhq-backup.timer

# Let the timer run even while you are logged out
sudo loginctl enable-linger "$USER"

# Verify
systemctl --user list-timers execsnowhq-backup.timer
systemctl --user start execsnowhq-backup.service   # run once now
journalctl --user -u execsnowhq-backup.service -n 30
```

`LAST` and `PASSED` in `list-timers` tell you when it actually last ran — which is the question cron could never answer.

**The session-start backup in §6 stays.** The timer covers nights; the manual run covers the moment before you start changing things.

### Restoring — do this at least once before you trust it

**Both halves, in one drill.** Restoring the database and declaring victory is how you
discover at the worst moment that the attachments were never in the backup.

```bash
# 1. The database, into a SCRATCH database. Never into execsnowhq_dev.
createdb execsnowhq_verify
gcloud storage cp gs://execs-now-hq-db-backups/execsnowhq_dev_20260909_023000.sql.gz /tmp/
gunzip -c /tmp/execsnowhq_dev_20260909_023000.sql.gz | psql execsnowhq_verify

psql execsnowhq_verify -c "SELECT count(*) FROM contact;"
psql execsnowhq_verify -c "SELECT purpose, count(*), sum(byte_size) FROM stored_file GROUP BY purpose;"
```

```bash
# 2. The media backup, into a scratch directory.
mkdir -p /tmp/media_verify
gcloud storage rsync --recursive gs://execs-now-hq-db-backups/media /tmp/media_verify
find /tmp/media_verify -type f | wc -l      # compare with the count above
```

```bash
# 3. Reconcile the two. THIS is the check that matters: not "are there files",
#    but "does every row the database references have content behind it" — and,
#    since Phase 2, at the recorded size.
#    STORAGE_BACKEND=local points check_media at the scratch copy instead of the
#    live bucket. Recordings are skipped because they are not in the backup by
#    design; the output says how many were skipped.
#    The empty-host URL uses the local socket (see DATABASE_URL in §3); a
#    postgres://localhost/... URL needs a Postgres password this setup does not have.
DATABASE_URL=postgres:///execsnowhq_verify \
STORAGE_BACKEND=local MEDIA_ROOT=/tmp/media_verify \
  .venv/bin/python manage.py check_media --strict --exclude-purpose recording_audio
```

→ `Every stored_file row has its content.` and exit code 0. Anything else names the
missing or wrong-size files, and `--strict` fails the drill rather than letting it pass
quietly. Exit code 2 means the check could not reach storage at all — not a pass.

**Day to day**, `.venv/bin/python manage.py check_media` with no overrides reconciles the
database against the live bucket.

```bash
# 4. Clean up.
dropdb execsnowhq_verify && rm -rf /tmp/media_verify
```

> **A backup you have never restored is a hypothesis.** This is a Phase 0.5 gate, not a
> suggestion — and after Check 5 it is a two-part gate, because a restore that brings
> back rows without blobs is not a restore.

### Media moved to GCS in Phase 2

`stored_file` content lives in `gs://execs-now-hq-media`, written and read with the
§5b service-account key. It moved at the start of Phase 2 rather than at the Railway
cutover because a nightly sync leaves up to 24 hours of writes unprotected — tolerable
for a flyer that can be re-uploaded from the original, not for a meeting recording that
exists nowhere else.

**What was moved, 2026-09-11:** two objects (the flyer, and one Outbox attachment),
both copied by `manage.py copy_media_to_gcs --apply` and verified by SHA-256 read-back
through the app's key. Object keys did not change; no row was edited. Two further rows
had no content to move — Outbox attachments on messages sent 2026-09-10, during the
0-byte bug. On owner approval they were removed with their two `outbox_attachment` rows
(dry run first; one `audit_event` each, verb `stored_file.orphan_removed`, recording the key,
size and message). `check_media --strict` passes against GCS from that point.
The laptop's `media/` directory was left in place and is no longer read.

**The trade-off accepted.** An offline laptop, a slow connection or a revoked key is now
a possible failure on every upload and every send with an attachment. It fails *as*
unavailability — `StorageUnavailable`, "try again" — never as `MissingContent`, "re-upload",
and screens show "storage unreachable — could not check" rather than "file missing".

---

## 8. After the Railway move — the post-cutover workflow

From cutover day, **the laptop is development-only and live data never returns to it** (build plan Phase 7, step 7).

**What changes:**

| | Before | After |
|---|---|---|
| Production data | on the laptop | on Railway |
| Local database | live data | **dev data only** — seeded, or scrubbed |
| Deploying | n/a | `git push origin main` → Railway builds |
| Backups | laptop cron, gcloud ADC | **Railway cron service, service-account key** |
| Real mail | allow-list only | **everything is real** |

**Daily loop:**

```bash
cd ~/projects/execs-now-hq
git pull
# ... work, with the same four terminals from §6 against the dev database ...
.venv/bin/pytest
git push origin main          # Railway builds and deploys from main
```

**Refreshing local dev data from production — one command, no gap:**

```bash
./scripts/refresh_dev_from_prod.sh
```

**There is deliberately no manual step between restore and scrub.** A three-command sequence has a window in which your local database holds real client addresses unscrubbed — and that window is exactly where an interruption, a phone call, or a forgotten terminal turns into a real email to a real client. One script closes it.

`scripts/refresh_dev_from_prod.sh`:

```bash
#!/usr/bin/env bash
# Pull production data into the LOCAL DEV database and scrub it in one step.
# There is no point at which unscrubbed production data sits in a usable database.
set -euo pipefail

DEV_DB="execsnowhq_dev"
DUMP="$(mktemp /tmp/execsnowhq_prod_XXXXXX.sql)"
trap 'shred -u "${DUMP}" 2>/dev/null || rm -f "${DUMP}"' EXIT

echo "==> Refusing to continue if this is not a local environment"
grep -qE '^PUBLIC_BASE_URL=https?://(localhost|127\.0\.0\.1)' .env \
  || { echo "!! PUBLIC_BASE_URL is not localhost. Aborting." >&2; exit 1; }

echo "==> Dumping production (Railway)"
railway run pg_dump --no-owner --no-privileges > "${DUMP}"
test -s "${DUMP}" || { echo "!! Empty dump. Aborting." >&2; exit 1; }

echo "==> Restoring into ${DEV_DB}"
dropdb --if-exists "${DEV_DB}"
createdb "${DEV_DB}"
psql -q "${DEV_DB}" < "${DUMP}"

echo "==> Scrubbing (this is the step that matters)"
.venv/bin/python manage.py scrub_dev_data

echo "==> Done. Dump shredded."
```

```bash
chmod +x scripts/refresh_dev_from_prod.sh
```

### `manage.py scrub_dev_data`

**It refuses to run unless both of these are true**, checked before it touches a single row:

1. the `DATABASE_URL` host is `localhost` or `127.0.0.1`, **and**
2. `PUBLIC_BASE_URL` is `localhost` or `127.0.0.1`.

Either check failing is a hard abort with a message naming which one — because the command that rewrites every email address in the database is the last thing that should ever run against production. `--force` is not offered.

**It prints what it rewrote**, so the scrub is verifiable rather than assumed:

```
Scrubbing execsnowhq_dev (host=localhost, PUBLIC_BASE_URL=http://localhost:8100)
  contact_email.address      1,284 rewritten -> <uuid>@example.invalid
  user.email                    11 rewritten -> <uuid>@example.invalid
  contact_phone.number       1,102 rewritten -> +1555xxxxxxx
  gmail_connection               3 deleted (and 3 tenant_secret rows)
  outbox_message               412 deleted
  django_q_ormq                  7 queued tasks flushed
  magic_link_token              24 deleted
  stakeholder_token             18 deleted
Done. No address in this database can receive mail.
```

**`.invalid` is a reserved TLD that cannot resolve**, so even a misconfigured build cannot deliver to a real client. That is the property worth having: the safety does not depend on the app's own send-guard logic being correct.

> **Why this matters more after the move than before.** Before cutover, a mistake meant a mail to Mailpit. After cutover, your local copy holds real client addresses and the production `PUBLIC_BASE_URL` is a real host. Scrubbing is what keeps a development mistake from reaching a client.

**Railway-side backups** move to a cron service using a dedicated service-account key (Railway has no interactive gcloud login), writing to the same bucket with the same retention. **Keep the laptop's production database untouched for two weeks** after cutover as a fallback.

---

## 9. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `TenantContextMissing` | A query ran with no tenant bound | **Working as designed** (B1). Fail-closed. Wrap job code in `with tenant_context(tenant_id):` |
| Digests never generate | `qcluster` not running | Terminal 2 |
| Nothing in Mailpit | Mailpit not running, or wrong port | `EMAIL_PORT=1025`, check terminal 4 |
| A real client got dev mail | An address is in `DEV_REAL_SEND_ALLOWLIST` | Remove it. Exact addresses only; wildcards are rejected at startup |
| Nothing sends; error names an alias | `info@` is not a confirmed Gmail send-as address | §5c — add it in Gmail, click the confirmation link, then Verify alias in the app |
| Nothing sends; error says reconnect Gmail | The stored refresh token was revoked or expired | Reconnect Gmail in Settings. **Client magic links are blocked until you do** |
| Mail sends from the wrong address | The alias is unverified and you expected a fallback | There is no fallback by design — verify the alias (§5c) |
| Restored DB replays old jobs | Queue tables came along in the dump | Flush the Django-Q2 queue tables before starting `qcluster` (A2) |
| Every stored secret unreadable | `FIELD_ENCRYPTION_KEY` changed or lost | No recovery. Re-enter the Anthropic key and reconnect Google |
| Upload or send fails: "No service-account key" or "Could not write/read gs://…" | Key missing or revoked, API disabled, or offline | Check `GOOGLE_APPLICATION_CREDENTIALS`, then `RUN_GCS_LIVE=1 .venv/bin/pytest tests/test_storage.py -m gcs_live` (§5b). The file is not lost — this is not `MissingContent` |
| Every note job fails with a missing column | `qcluster` started before a migration | Restart `qcluster` (§6) |
| Recording stuck on "Transcribing…" | `qcluster` not running, or no schedule | Terminal 2; then `manage.py ensure_schedules` |
| Transcription fails: "Speech-to-Text could not start" | API disabled, key lacks `roles/speech.client`, or offline | §5b; the audio is kept — use **Retry transcription** |
| Summary shows "Claude could not draft a summary" | No Anthropic key, a rejected key, or offline | Sidebar → AI usage → Anthropic API key; then **Draft another summary** |
| Yellow "recording waiting to upload" banner | The upload never reached the server | It is held in this browser; **Retry upload now**, or download it |
| WeasyPrint import error | Missing Pango/Cairo | The `apt install` line in §1 |
| Google sign-in refused | No membership for that address | Correct — invite-only (C1) |

---

## 10. Phase 0 is complete

Six documents, all approved:

| Doc | Purpose |
|---|---|
| `00_assumptions.md` | 53 assumptions, all marked; 7 open questions answered |
| `01_prd.md` | Six modules, ~130 acceptance criteria, the review-queue register |
| `02_data_model.md` | Every table; the CSV→portal walkthrough |
| `03_access_matrix.md` | Every action × five roles; the permission-test source |
| `04_build_plan.md` | Phases 0.5–8+, with the Railway trigger and cutover |
| `05_dev_environment.md` | This runbook |

**Two things to do before Phase 1**, both with lead time:

1. **Add the DNS records in §4.** Propagation is the long pole on mail.
2. **Create the Google OAuth client in §5** and keep it in testing mode.

**When you are ready**, the Phase 1 message from the kickoff doc still applies — with one correction, since Phase 0.5 now exists as a separate gate:

```
Phase 0 docs are approved. Begin Phase 0.5 from /docs/04_build_plan.md: scaffold
per /docs/05_dev_environment.md, then tenancy, auth, and the two test registries.
Stop at the first migration and show me the schema before applying it.
```
