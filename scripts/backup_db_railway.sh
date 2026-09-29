#!/usr/bin/env bash
# Nightly backup of PRODUCTION (Railway) to GCS. 30-day retention.
#
# The Railway twin of scripts/backup_db.sh, which stays as it is for the
# laptop. Same flow, same safeguards, in the same order:
#
#   dump -> refuse a too-small dump -> upload -> media copy -> prune
#
# What differs is only what Railway lacks:
#   - the database comes from DATABASE_URL (Railway's reference variable);
#   - there is no gcloud and no interactive login, so every storage step goes
#     through scripts/gcs_backup.py as the backup-writer service account,
#     whose key is in GOOGLE_SA_BACKUP_JSON (runbook A4a);
#   - dumps are named execsnowhq_prod_*, so a laptop dump and a production
#     dump can never be mistaken for each other in the bucket.
#
# Media after the dump, never before (see backup_db.sh for why: one order
# leaves a harmless orphan blob, the other a row whose file opens empty).
# Recording audio is not copied (owner decision, Phase 2).
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL is not set}"
: "${GOOGLE_SA_BACKUP_JSON:?GOOGLE_SA_BACKUP_JSON is not set (runbook A4a)}"

BUCKET="${BACKUP_BUCKET:-gs://execs-now-hq-db-backups}"
MEDIA_BUCKET="gs://${GCS_BUCKET_MEDIA:-execs-now-hq-media}"
MEDIA_DEST="${BUCKET}/media/${GCS_BUCKET_MEDIA:-execs-now-hq-media}"
RECORDINGS_EXCLUDE='^recordings/'
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
STAMP="$(date -u +%Y%m%d_%H%M%S)"
TMP="$(mktemp -d)"
FILE="${TMP}/execsnowhq_prod_${STAMP}.sql.gz"
HELPER="$(dirname "$0")/gcs_backup.py"

trap 'rm -rf "${TMP}"' EXIT

echo "==> Dumping production ($(pg_dump --version))"
pg_dump --no-owner --no-privileges "${DATABASE_URL}" | gzip -9 > "${FILE}"

SIZE=$(stat -c%s "${FILE}")
if [ "${SIZE}" -lt 1024 ]; then
  echo "!! Dump is ${SIZE} bytes — refusing to upload a probably-empty backup" >&2
  exit 1
fi
echo "==> Dump OK (${SIZE} bytes)"

echo "==> Uploading to ${BUCKET}"
python "${HELPER}" upload "${FILE}" "${BUCKET}"

echo "==> Copying ${MEDIA_BUCKET} to ${MEDIA_DEST} (excluding ${RECORDINGS_EXCLUDE})"
# A backup, not a mirror: nothing is ever deleted from the destination.
python "${HELPER}" sync "${MEDIA_BUCKET}" "${MEDIA_DEST}" --exclude "${RECORDINGS_EXCLUDE}"
echo "==> Media copy OK"

echo "==> Pruning dumps older than ${RETENTION_DAYS} days"
# *.sql.gz only, so the media copy is never pruned by age.
python "${HELPER}" prune "${BUCKET}" --days "${RETENTION_DAYS}"

echo "==> Done: $(basename "${FILE}") + media"
