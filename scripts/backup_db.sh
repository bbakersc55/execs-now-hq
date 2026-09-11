#!/usr/bin/env bash
# Nightly + on-demand backup of execsnowhq_dev to GCS. 30-day retention.
#
# Backs up TWO things, because the database alone is not a restorable system:
# the Postgres dump, and the media bucket that `stored_file` rows point at
# (marketing flyer, Outbox attachments, strategy PDFs). A dump without the blobs
# restores rows describing files that do not exist — which is exactly the
# 0-byte-attachment failure, reintroduced by the backup.
#
# Recording audio is NOT copied (owner decision, Phase 2). A never-pruned copy
# would keep every recording forever and make audio_retention_days a promise
# the backup breaks. Recordings rely on GCS durability plus the bucket's 7-day
# soft delete. storage.py forces all recording audio under recordings/, so the
# exclude below is the whole rule.
set -euo pipefail

DB_NAME="execsnowhq_dev"
BUCKET="gs://execs-now-hq-db-backups"
MEDIA_BUCKET="gs://execs-now-hq-media"
# Keeps the <bucket>/<object_key> layout the restore drill already expects.
MEDIA_DEST="${BUCKET}/media/execs-now-hq-media"
RECORDINGS_EXCLUDE='^recordings/'
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

# --------------------------------------------------------------------------
# Media, AFTER the dump. The order is not arbitrary.
#
# Anything uploaded BETWEEN the dump and the rsync ends up in the backup as
# bytes with no row — a harmless orphan blob. Run the rsync first and the same
# window produces the opposite: a row with no bytes, which restores as a file
# that opens empty. One direction wastes a little space; the other loses data
# silently. So: dump, then media.
#
# Bucket to bucket, same region: a server-side copy, nothing passes through
# this machine.
# --------------------------------------------------------------------------
echo "==> Syncing ${MEDIA_BUCKET} to ${MEDIA_DEST} (excluding ${RECORDINGS_EXCLUDE})"
# No --delete-unmatched-destination-objects on purpose: this is a backup, not
# a mirror. A file deleted by accident stays recoverable here, which is the
# entire reason the copy exists.
gcloud storage rsync --recursive --exclude="${RECORDINGS_EXCLUDE}" \
  "${MEDIA_BUCKET}" "${MEDIA_DEST}"
echo "==> Media sync OK"

echo "==> Pruning backups older than ${RETENTION_DAYS} days"
CUTOFF=$(date -u -d "${RETENTION_DAYS} days ago" +%Y-%m-%dT%H:%M:%SZ)
# Only ever matches *.sql.gz, so the media mirror is never pruned by age — a
# flyer from last year is still the flyer that is attached to live drafts.
gcloud storage ls --long "${BUCKET}/**" 2>/dev/null \
  | awk -v c="${CUTOFF}" '$2 < c && $3 ~ /\.sql\.gz$/ {print $3}' \
  | while read -r old; do
      echo "    deleting ${old}"
      gcloud storage rm "${old}"
    done

echo "==> Done: $(basename "${FILE}") + media"
