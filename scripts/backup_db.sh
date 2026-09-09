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
