#!/usr/bin/env bash
# Rebuild the laptop's LOCAL DEV database from production's newest nightly
# backup, and scrub it in the same run. Nothing between restore and scrub
# waits on a person.
#
#   ./scripts/refresh_dev_from_prod.sh                  # newest execsnowhq_prod_* dump
#   ./scripts/refresh_dev_from_prod.sh <object-name>    # a specific one
#
# Runbook B7 (run 2026-10-02). The local database is execsnowhq_local.
# execsnowhq_dev is the pre-cutover laptop database, kept as the fallback; this
# script never touches it, and scrub_dev_data refuses it by name. (Until
# 2026-09-29 this script's DEV_DB was execsnowhq_dev: it would have dropped
# production.)
#
# Why the GCS backup and not a live `railway run pg_dump`: production runs
# Postgres 18 and this laptop's pg_dump is 16, which refuses a newer server.
# The nightly dump (B4) is written by Railway's own pg_dump 18, needs only
# your gcloud login, and never opens a connection to the production database.
# It restores into 16 once its one 17+ setting line is dropped (below); any
# other incompatibility stops the restore on its first error.
set -euo pipefail
cd "$(dirname "$0")/.."

DEV_DB="execsnowhq_local"
BUCKET="gs://execs-now-hq-db-backups"
DUMP="$(mktemp /tmp/execsnowhq_prod_XXXXXX.sql.gz)"
trap 'shred -u "${DUMP}" 2>/dev/null || rm -f "${DUMP}"' EXIT

echo "==> Refusing to continue if this is not a local environment"
grep -qE '^PUBLIC_BASE_URL=https?://(localhost|127\.0\.0\.1)' .env \
  || { echo "!! PUBLIC_BASE_URL is not localhost. Aborting." >&2; exit 1; }
grep -qE "^DATABASE_URL=postgres(ql)?://[^/]*/${DEV_DB}\$" .env \
  || { echo "!! .env's DATABASE_URL does not name ${DEV_DB}. Aborting." >&2; exit 1; }
grep -qE '^STORAGE_BACKEND=local$' .env \
  || { echo "!! STORAGE_BACKEND is not local: a restored database would point at" \
            "production's media bucket. Aborting." >&2; exit 1; }

echo "==> Finding the backup"
if [ $# -ge 1 ]; then
  OBJECT="${BUCKET}/${1#"${BUCKET}/"}"
else
  OBJECT="$(gcloud storage ls "${BUCKET}/execsnowhq_prod_*.sql.gz" | sort | tail -1)"
fi
[ -n "${OBJECT}" ] || { echo "!! No execsnowhq_prod_* dump found." >&2; exit 1; }
echo "    ${OBJECT}"
gcloud storage cp --no-user-output-enabled "${OBJECT}" "${DUMP}"
[ "$(stat -c%s "${DUMP}")" -ge 1024 ] || { echo "!! Dump under 1 KB. Aborting." >&2; exit 1; }

echo "==> Restoring into ${DEV_DB} (dropdb fails if anything is still connected: stop the tabs first)"
dropdb --if-exists "${DEV_DB}"
createdb "${DEV_DB}"
# transaction_timeout is Postgres 17+, and 0 is its default: dropping the line
# changes nothing about the restore.
zcat "${DUMP}" | grep -v '^SET transaction_timeout = 0;$' \
  | psql -q -v ON_ERROR_STOP=1 --single-transaction "${DEV_DB}" > /dev/null

echo "==> Scrubbing (this is the step that matters)"
.venv/bin/python manage.py scrub_dev_data --database "${DEV_DB}" --keep-staff

echo "==> Schedules back on cadence, so the first qcluster start fires nothing stale"
.venv/bin/python manage.py ensure_schedules > /dev/null

echo "==> Done: ${DEV_DB} from $(basename "${OBJECT}"). Dump shredded."
echo "    If dev is ahead of main: .venv/bin/python manage.py migrate"
