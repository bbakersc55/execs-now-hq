# 05 — Development Environment

**Phase 0 · Execs NOW HQ**

This is a runbook, not an explanation. Commands to paste, in order, with just enough context to know when to use them.

**Target for every code block:** your local terminal, from `~/projects/execs-now-hq`, unless the block says otherwise.

---

## 1. One-time setup

Already done (per the kickoff): repo, `git init`, `CLAUDE.md`, `.claude/settings.json`, `createdb execsnowhq_dev`, GCP project `execs-now-hq`, bucket `gs://execs-now-hq-db-backups`, gcloud ADC.

What remains:

```bash
# System packages (Debian/Ubuntu)
sudo apt install -y python3.12 python3.12-venv postgresql-client build-essential \
                    libpango-1.0-0 libpangoft2-1.0-0 libcairo2   # WeasyPrint needs these

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
DATABASE_URL=postgres://bbakersc@localhost:5432/execsnowhq_dev

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
GCS_BUCKET_MEDIA=execs-now-hq-media

# ---------- Backups ----------
BACKUP_BUCKET=gs://execs-now-hq-db-backups
BACKUP_RETENTION_DAYS=30

# ---------- Errors ----------
SENTRY_DSN=
# Enabled only when PUBLIC_BASE_URL is not localhost (assumption A5).
```

---

## 4. DNS records to add — do this early

**These have propagation lead time and Phase 1 mail does not work without the first two.** Add them in your DNS provider for `getexecutivesnow.com`. Postmark shows you the exact values when you add the domain and the inbound stream; the shapes are below.

| # | Purpose | Type | Host | Value |
|---|---|---|---|---|
| 1 | **DKIM** — signs outbound so it is not spam | `TXT` | `20260909pm._domainkey` | *(long key from Postmark)* |
| 2 | **Return-Path** — custom bounce domain | `CNAME` | `pm-bounces` | `pm.mtasv.net` |
| 3 | **Inbound MX** — receives client replies | `MX` | `inbound` | `inbound.postmarkapp.com` (priority `10`) |

**Record 3 is only needed for Module 6**, which now runs after the Railway move — but add it at the same time as 1 and 2, because discovering a propagation delay on cutover day is avoidable.

Verify:

```bash
dig +short TXT 20260909pm._domainkey.getexecutivesnow.com
dig +short CNAME pm-bounces.getexecutivesnow.com
dig +short MX inbound.getexecutivesnow.com
```

---

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
- Redirect URI: `http://localhost:8100/accounts/google/login/callback/`

**Internal, not External/Testing** — you are on Google Workspace at `getexecutivesnow.com`, which makes Internal available, and it is strictly better here for two reasons:

1. **No verification is required for `gmail.send`**, even though it is a restricted scope.
2. **No 7-day refresh-token expiry.** External apps left in *Testing* expire refresh tokens after seven days, which would silently break every Gmail connection and every Drive watch about once a week — a failure that looks like a bug and is not.

**The consequence, and it is a real constraint:** only `@getexecutivesnow.com` accounts can sign in with Google. **Any CF or VA you bring on needs an account in your Workspace domain.** Client users are unaffected — they use magic links (C3, C4) and never touch Google.

Switching to **External with CASA verification** is the V1 task, needed before another fractional's practice can use the app. It is slow and expensive, and it is the longest lead time in the V1 plan.

### 5b. Service account for the app's own API calls

```bash
gcloud iam service-accounts create execs-now-hq-app \
  --display-name="Execs NOW HQ application runtime" \
  --project=execs-now-hq

# Minimum roles — no project-wide editor
gcloud projects add-iam-policy-binding execs-now-hq \
  --member="serviceAccount:execs-now-hq-app@execs-now-hq.iam.gserviceaccount.com" \
  --role="roles/speech.client"
gcloud projects add-iam-policy-binding execs-now-hq \
  --member="serviceAccount:execs-now-hq-app@execs-now-hq.iam.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"

# Key file, OUTSIDE the repo
mkdir -p ~/.config/execs-now-hq
gcloud iam service-accounts keys create ~/.config/execs-now-hq/sa-app.json \
  --iam-account=execs-now-hq-app@execs-now-hq.iam.gserviceaccount.com
chmod 600 ~/.config/execs-now-hq/sa-app.json
```

**Why a key file rather than the ADC you already have:** your laptop's ADC is shared with another project and its quota-project setting cannot serve both at once — the app would intermittently bill or fail against the wrong project. A key file also makes **development identical to Railway**, where there is no interactive gcloud login and a key file is the only option. Discovering that difference at cutover is avoidable.

**`scripts/backup_db.sh` continues to use the gcloud CLI and your ADC.** It is the one thing that does.

Enable in the same project: **Google Drive API**, **Cloud Speech-to-Text API**, **Cloud Storage**.

---

## 6. Every session — the pre-Railway workflow

Four terminals, or a `tmux` session. This is what you run each time you sit down.

```bash
cd ~/projects/execs-now-hq

# 0. Back up first. Cheap, and it means an experiment is never irreversible.
./scripts/backup_db.sh

# 1. Django                                   [terminal 1]
.venv/bin/python manage.py runserver 8100

# 2. Background jobs                          [terminal 2]
.venv/bin/python manage.py qcluster

# 3. Frontend                                 [terminal 3]
npm run dev            # Vite on 5200

# 4. Dev outbox                               [terminal 4]
mailpit --smtp-bind-addr localhost:1025 --listen localhost:8125
```

Then open **http://localhost:5200** for the app and **http://localhost:8125** for mail.

**`qcluster` must be running** or digests never generate, Drive never polls, and transcriptions never finish. If something "isn't happening," check terminal 2 first.

Common commands:

```bash
.venv/bin/python manage.py makemigrations      # never applied without showing you first
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
.venv/bin/pytest                                # full suite
.venv/bin/pytest -k "isolation or role"         # the two mandatory families
.venv/bin/python manage.py replay_inbound fixtures/inbound/token_match.json   # Module 6
```

---

## 7. The backup script

`scripts/backup_db.sh` — uses **gcloud ADC**, not a service-account key file (kickoff §I).

```bash
#!/usr/bin/env bash
# Nightly + on-demand backup of execsnowhq_dev to GCS. 30-day retention.
set -euo pipefail

DB_NAME="execsnowhq_dev"
BUCKET="gs://execs-now-hq-db-backups"
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

echo "==> Pruning backups older than ${RETENTION_DAYS} days"
CUTOFF=$(date -u -d "${RETENTION_DAYS} days ago" +%Y-%m-%dT%H:%M:%SZ)
gcloud storage ls --long "${BUCKET}/**" 2>/dev/null \
  | awk -v c="${CUTOFF}" '$2 < c && $3 ~ /\.sql\.gz$/ {print $3}' \
  | while read -r old; do
      echo "    deleting ${old}"
      gcloud storage rm "${old}"
    done

echo "==> Done: $(basename "${FILE}")"
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

```bash
# Verify a backup by restoring it into a scratch database. Never into execsnowhq_dev.
createdb execsnowhq_verify
gcloud storage cp gs://execs-now-hq-db-backups/execsnowhq_dev_20260909_023000.sql.gz /tmp/
gunzip -c /tmp/execsnowhq_dev_20260909_023000.sql.gz | psql execsnowhq_verify

psql execsnowhq_verify -c "SELECT count(*) FROM contact;"
dropdb execsnowhq_verify
```

> **A backup you have never restored is a hypothesis.** This is a Phase 0.5 gate, not a suggestion.

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
| Restored DB replays old jobs | Queue tables came along in the dump | Flush the Django-Q2 queue tables before starting `qcluster` (A2) |
| Every stored secret unreadable | `FIELD_ENCRYPTION_KEY` changed or lost | No recovery. Re-enter the Anthropic key and reconnect Google |
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
