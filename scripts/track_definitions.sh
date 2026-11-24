#!/bin/sh
# A read-only look at the bed types and unit custom fields in SkyRun Park
# City's Track (scripts/track_definitions.py has what it reads and prints).
# Prepared 2026-11-23. Run only on the owner's say, as a `!` line.
#
# The script travels as base64 on the command line and runs under
# `manage.py shell -c` in production's web container (where the Track key is):
# nothing is unpacked or written there. ENHQ's database: one read-only
# transaction, rolled back. Track: GET only, to skyrunparkcity.trackhs.com.
# The output is saved to $1 (default ./track_definitions.log) and printed.
set -eu
cd "$(dirname "$0")/.."
LOG="${1:-track_definitions.log}"
# SkyRun Park City's company id (the one `intake_forms ... on` was run for).
COMPANY=c4e5ca2a-bee1-4b11-976b-838d63544de1
B=$(base64 -w0 < scripts/track_definitions.py)
REMOTE="TRACK_DEFS_COMPANY=$COMPANY python manage.py shell -c \"\$(echo $B | base64 -d)\""
rc=0
railway ssh -p 8f0dc06d-0265-4af7-8cab-2ec26c6eccca -e production --service execs-now-hq -- \
  sh -c "$REMOTE" > "$LOG" 2>&1 || rc=$?
cat "$LOG"
echo "exit $rc; $(wc -l < "$LOG") lines in $LOG"
exit "$rc"
