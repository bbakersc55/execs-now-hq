#!/bin/sh
# The web service's start on Railway (Phase 7). One script rather than a
# quoted `sh -c` start command, which Railway did not run as written.
set -eu
echo "==> $(date -u +%FT%TZ) web starting (APP_ENVIRONMENT=${APP_ENVIRONMENT:-unset})"
# A brand-new empty database gets its schema, and the demo applies its own
# migrations; anything else must already be migrated, or the start is refused
# (apps/tenancy/.../migrate_if_empty.py). It waits six minutes for a release's
# migrations to be applied by hand in the waiting worker before refusing, so
# the push's own build comes up (owner, 2026-10-20). Railway's health check
# timeout on web (railway/web.json) must stay longer than this wait.
python manage.py migrate_if_empty --wait 360 --every 10
python manage.py check --fail-level ERROR
# The access log masks signing tokens in paths and Referers (2026-10-29,
# config/log_masking.py).
exec gunicorn config.wsgi --bind 0.0.0.0:8080 --workers 3 --timeout 120 --access-logfile - \
  --logger-class config.log_masking.MaskedAccessLogger
