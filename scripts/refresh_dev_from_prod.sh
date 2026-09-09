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
