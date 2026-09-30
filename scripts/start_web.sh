#!/bin/sh
# The web service's start on Railway (Phase 7). One script rather than a
# quoted `sh -c` start command, which Railway did not run as written.
set -eu
echo "==> $(date -u +%FT%TZ) web starting (APP_ENVIRONMENT=${APP_ENVIRONMENT:-unset})"
# A brand-new empty database gets its schema; anything else must already be
# migrated, or the start is refused (apps/tenancy/.../migrate_if_empty.py).
python manage.py migrate_if_empty
python manage.py check --fail-level ERROR
exec gunicorn config.wsgi --bind 0.0.0.0:8080 --workers 3 --timeout 120 --access-logfile -
