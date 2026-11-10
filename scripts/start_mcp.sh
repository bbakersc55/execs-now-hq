#!/bin/sh
# The `mcp` service's start on Railway (P7, docs/p7_mcp.md). Never migrates.
#
# Like the worker, it WAITS with a migration unapplied rather than serving new
# code against an old schema; the migration is applied from the waiting
# qcluster (runbook, "Releasing a migration"), and this starts once it is.
set -eu
echo "==> $(date -u +%FT%TZ) mcp starting (APP_ENVIRONMENT=${APP_ENVIRONMENT:-unset})"
until python manage.py migrate --check > /dev/null 2>&1; do
  echo "==> $(date -u +%FT%TZ) WAITING for migrations (applied from qcluster)"
  sleep 30
done
echo "==> $(date -u +%FT%TZ) migrations current"
exec uvicorn config.mcp_asgi:app --host 0.0.0.0 --port "${PORT:-8080}" \
  --proxy-headers --forwarded-allow-ips '*' --no-server-header
