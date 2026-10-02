#!/bin/sh
# The worker's start on Railway (Phase 7). Never migrates, and refuses in the
# demo (config/checks.py).
#
# With a migration unapplied it WAITS instead of exiting. That is what makes a
# release with a migration possible: web refuses to start, so the only
# container running the NEW code is this one, and `railway ssh` reaches only an
# active instance. The migration is applied by hand from here (runbook,
# "Releasing a migration"), and the worker starts the moment it is.
set -eu
echo "==> $(date -u +%FT%TZ) qcluster starting (APP_ENVIRONMENT=${APP_ENVIRONMENT:-unset})"
until python manage.py migrate --check > /dev/null 2>&1; do
  echo "==> $(date -u +%FT%TZ) WAITING: not starting until this is applied by hand"
  echo "    (railway ssh --service qcluster -- python manage.py migrate):"
  # Also lands here if the database is unreachable; the list then says so.
  python manage.py showmigrations --plan 2>&1 | grep -vF '[X]' | head -10 | sed 's/^/    /'
  sleep 30
done
echo "==> $(date -u +%FT%TZ) migrations current"
exec python manage.py qcluster
