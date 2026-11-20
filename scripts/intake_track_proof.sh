#!/bin/sh
# Intake forms, the production proof (docs/p14_intake_forms.md): one complete
# submission through the feature's own code to SkyRun Park City's real Track,
# creating a "ZZ TEST 2 ... DELETE ME" set (owner inactive, unit inactive and not
# bookable). Prepared 2026-11-19; run only on the owner's say. Running it again
# carries on from where it stopped, without duplicates.
#
# The feature isn't deployed, so its pure modules travel with the run, packed
# here and unpacked in production's web container into a new private folder
# (mktemp -d /tmp/intake_proof.XXXXXXXX): never the app's folder, and added at
# the END of Python's import path under the one name `intake_proof`, so it can
# shadow nothing of the app's. scripts/intake_track_proof.py runs under
# `manage.py shell` (where the Track key is). The remote shell removes the
# folder on any exit: success, failure, hangup, Ctrl-C or terminate. Only a
# SIGKILL could skip that, and a new container starts clean from the image.
# The local packing folder is removed the same way. The log is saved to $1
# (default ./intake_proof.log).
set -eu
cd "$(dirname "$0")/.."
LOG="${1:-intake_proof.log}"
PKG=$(mktemp -d)
trap 'rm -rf "$PKG"' EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
mkdir -p "$PKG/lib/intake_proof"
: > "$PKG/lib/intake_proof/__init__.py"
for f in schema defaults derive plan track_writer trackread; do
  cp "apps/intake/$f.py" "$PKG/lib/intake_proof/$f.py"
done
cp apps/scorecard/track.py "$PKG/lib/intake_proof/track.py"
cp apps/scorecard/periods.py "$PKG/lib/intake_proof/periods.py"
cp scripts/intake_track_proof.py "$PKG/main.py"
B=$(tar -C "$PKG" -czf - . | base64 -w0)
# One line for the remote shell; $D and the traps are the remote's own.
REMOTE='D=$(mktemp -d /tmp/intake_proof.XXXXXXXX) || exit 1; '
REMOTE="$REMOTE"'trap '\''rm -rf "$D"'\'' EXIT; trap '\''exit 129'\'' HUP; '
REMOTE="$REMOTE"'trap '\''exit 130'\'' INT; trap '\''exit 143'\'' TERM; '
REMOTE="$REMOTE""echo $B | base64 -d | tar -C \"\$D\" -xzf - || exit 1; "
REMOTE="$REMOTE"'INTAKE_PROOF_DIR="$D" python manage.py shell < "$D/main.py"'
rc=0
railway ssh -p 8f0dc06d-0265-4af7-8cab-2ec26c6eccca -e production --service execs-now-hq -- \
  sh -c "$REMOTE" > "$LOG" 2>&1 || rc=$?
echo "exit $rc; $(wc -l < "$LOG") lines in $LOG"
grep -n "GUARD\|PROBLEM\|STOPPED\|RESULT\|Secrets Track\|^UNIT\|^OWNER\|^CALLS\|^STATE\|Traceback" "$LOG" || true
exit "$rc"
