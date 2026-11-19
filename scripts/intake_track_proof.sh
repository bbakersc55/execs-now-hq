#!/bin/sh
# Intake forms, the production proof (docs/p14_intake_forms.md): one complete
# submission through the feature's own code to SkyRun Park City's real Track,
# creating a "ZZ TEST 2 ... DELETE ME" set (owner inactive, unit inactive and not
# bookable). Prepared 2026-11-19; run only on the owner's say. Running it again
# carries on from where it stopped, without duplicates.
#
# The feature isn't deployed, so its pure modules travel with the run: they are
# copied into production's web container as a package, used by
# scripts/intake_track_proof.py under `manage.py shell` (where the Track key
# is), and deleted afterwards. The log is saved to $1 (default ./intake_proof.log).
set -eu
cd "$(dirname "$0")/.."
LOG="${1:-intake_proof.log}"
PKG=$(mktemp -d)
mkdir -p "$PKG/intake_proof"
: > "$PKG/intake_proof/__init__.py"
for f in schema defaults derive plan track_writer trackread; do
  cp "apps/intake/$f.py" "$PKG/intake_proof/$f.py"
done
cp apps/scorecard/track.py "$PKG/intake_proof/track.py"
cp apps/scorecard/periods.py "$PKG/intake_proof/periods.py"
cp scripts/intake_track_proof.py "$PKG/main.py"
B=$(tar -C "$PKG" -czf - . | base64 -w0)
rm -rf "$PKG"
railway ssh -p 8f0dc06d-0265-4af7-8cab-2ec26c6eccca -e production --service execs-now-hq -- \
  sh -c "rm -rf /tmp/intake_proof_pkg && mkdir -p /tmp/intake_proof_pkg && echo $B | base64 -d | tar -C /tmp/intake_proof_pkg -xzf - && python manage.py shell < /tmp/intake_proof_pkg/main.py; rm -rf /tmp/intake_proof_pkg" \
  > "$LOG" 2>&1
echo "exit $?; $(wc -l < "$LOG") lines in $LOG"
grep -n "GUARD\|PROBLEM\|RESULT\|Secrets Track\|^UNIT\|^OWNER\|^CALLS" "$LOG" || true
