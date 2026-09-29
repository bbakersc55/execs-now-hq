#!/usr/bin/env bash
# Pull production data into the LOCAL DEV database and scrub it in one step.
# There is no point at which unscrubbed production data sits in a usable database.
#
# For AFTER cutover only (Phase 7). The local database is execsnowhq_local.
# execsnowhq_dev is the laptop's production database until cutover and its
# fallback for two weeks after; this script never drops it, and scrub_dev_data
# refuses it by name. (Until 2026-09-29 this script's DEV_DB was
# execsnowhq_dev: it would have dropped production.)
set -euo pipefail

DEV_DB="execsnowhq_local"
DUMP="$(mktemp /tmp/execsnowhq_prod_XXXXXX.sql)"
trap 'shred -u "${DUMP}" 2>/dev/null || rm -f "${DUMP}"' EXIT

echo "==> Refusing to continue if this is not a local environment"
grep -qE '^PUBLIC_BASE_URL=https?://(localhost|127\.0\.0\.1)' .env \
  || { echo "!! PUBLIC_BASE_URL is not localhost. Aborting." >&2; exit 1; }
grep -qE "^DATABASE_URL=postgres(ql)?://[^/]*/${DEV_DB}\$" .env \
  || { echo "!! .env's DATABASE_URL does not name ${DEV_DB}. Aborting." >&2; exit 1; }

echo "==> Dumping production (Railway)"
# DATABASE_PUBLIC_URL, not DATABASE_URL: the private one resolves only inside
# Railway's network. (Variable name to confirm on the real Postgres service.)
railway run --service Postgres -- \
  sh -c 'pg_dump --no-owner --no-privileges "$DATABASE_PUBLIC_URL"' > "${DUMP}"
test -s "${DUMP}" || { echo "!! Empty dump. Aborting." >&2; exit 1; }

echo "==> Restoring into ${DEV_DB}"
dropdb --if-exists "${DEV_DB}"
createdb "${DEV_DB}"
psql -q -v ON_ERROR_STOP=1 "${DEV_DB}" < "${DUMP}"

echo "==> Scrubbing (this is the step that matters)"
.venv/bin/python manage.py scrub_dev_data --database "${DEV_DB}" --keep-staff

echo "==> Done. Dump shredded."
