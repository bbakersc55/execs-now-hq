#!/bin/sh
# The worker's start on Railway (Phase 7). Never migrates; refuses to start
# with a migration unapplied, and refuses in the demo (config/checks.py).
set -eu
echo "==> $(date -u +%FT%TZ) qcluster starting (APP_ENVIRONMENT=${APP_ENVIRONMENT:-unset})"
python manage.py migrate --check
exec python manage.py qcluster
