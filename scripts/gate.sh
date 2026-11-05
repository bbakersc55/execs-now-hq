#!/usr/bin/env bash
# The gate (owner, 2026-10-08): nothing is committed or pushed unless the full
# suite was green on exactly that tree.
#
#   git add -A && scripts/gate.sh && git commit ... && git push
#
# It runs the whole backend suite, the migration check, the frontend type
# check and the whole frontend suite, each judged by its own exit status, and
# only when all four pass does it record the tree it tested in
# .git/green-trees. The pre-commit and pre-push hooks (.githooks/, switched on
# with `git config core.hooksPath .githooks`) refuse any tree that is not in
# that file.
#
# Since 2026-11-05 the backend runs over six workers with the frontend
# alongside it (pytest-xdist, requirements-dev.txt); `GATE_SERIAL=1
# scripts/gate.sh` runs everything one step at a time, the old way.
#
# Why it exists: on 2026-10-08 a commit and push went out after a frontend run
# with one failing test, because the command that ran the tests judged a
# filtered copy of their output instead of their exit status.
set -uo pipefail
cd "$(git rev-parse --show-toplevel)"

# What is tested has to be what is committed. The suites run on the working
# tree, so it must match the index, with nothing left out of it.
if ! git diff --quiet; then
  echo "gate: there are unstaged changes. Stage them (git add) or put them aside:" >&2
  git diff --stat >&2
  exit 1
fi
untracked="$(git ls-files --others --exclude-standard)"
if [ -n "$untracked" ]; then
  echo "gate: these files are not staged, so the suite would test what the commit lacks:" >&2
  echo "$untracked" >&2
  exit 1
fi

tree="$(git write-tree)"
log="$(mktemp -d)"
fail() { echo "gate: REFUSED. $1 failed (exit $2). Its output: $3" >&2; tail -25 "$3" >&2; exit 1; }

# The project's addopts add a second -q, which hides the line that counts.
PYTEST=(.venv/bin/python -m pytest -o addopts="--strict-markers" -q -p no:cacheprovider)

if [ "${GATE_SERIAL:-}" = "1" ]; then
  # The fallback (2026-11-05): everything one after another, the backend in
  # one process, exactly as the gate ran before it went parallel. For a run
  # whose parallel failure needs explaining.
  echo "gate: GATE_SERIAL=1, one step at a time."
  echo "gate: backend suite (one process)…"
  "${PYTEST[@]}" >"$log/pytest" 2>&1 || fail "the backend suite" $? "$log/pytest"
  echo "gate: migration check…"
  .venv/bin/python manage.py makemigrations --check --dry-run >"$log/migrations" 2>&1 || fail "the migration check (a model change has no migration)" $? "$log/migrations"
  echo "gate: frontend type check…"
  (cd frontend && npx tsc --noEmit -p .) >"$log/tsc" 2>&1 || fail "the frontend type check" $? "$log/tsc"
  echo "gate: frontend suite…"
  (cd frontend && npx vitest run) >"$log/vitest" 2>&1 || fail "the frontend suite" $? "$log/vitest"
else
  # Parallel (2026-11-05): the backend over six workers (pytest-xdist), each
  # with its own test database (pytest-django's _gw0.._gw5) and each file
  # kept whole on one worker (--dist loadfile); the frontend's type check and
  # suite alongside it. Every step is still judged by its own exit status,
  # and all four must pass.
  echo "gate: frontend type check and suite, alongside the backend…"
  (
    cd frontend
    npx tsc --noEmit -p . >"$log/tsc" 2>&1
    status=$?
    echo "$status" >"$log/tsc.status"
    if [ "$status" = "0" ]; then
      npx vitest run >"$log/vitest" 2>&1
      echo "$?" >"$log/vitest.status"
    fi
  ) &
  frontend=$!
  echo "gate: backend suite (six workers)…"
  backend=0
  "${PYTEST[@]}" -n 6 --dist loadfile >"$log/pytest" 2>&1 || backend=$?
  migrations=0
  if [ "$backend" = "0" ]; then
    echo "gate: migration check…"
    .venv/bin/python manage.py makemigrations --check --dry-run >"$log/migrations" 2>&1 || migrations=$?
  fi
  # Always wait for the frontend, so nothing is left running behind a refusal.
  wait "$frontend"
  [ "$backend" = "0" ] || fail "the backend suite" "$backend" "$log/pytest"
  [ "$migrations" = "0" ] || fail "the migration check (a model change has no migration)" "$migrations" "$log/migrations"
  tsc="$(cat "$log/tsc.status" 2>/dev/null || echo missing)"
  [ "$tsc" = "0" ] || fail "the frontend type check" "$tsc" "$log/tsc"
  vitest="$(cat "$log/vitest.status" 2>/dev/null || echo missing)"
  [ "$vitest" = "0" ] || fail "the frontend suite" "$vitest" "$log/vitest"
fi

# Still the tree that was tested: nothing was staged while the suites ran.
if [ "$(git write-tree)" != "$tree" ] || ! git diff --quiet; then
  echo "gate: the files changed while the suites were running. Run it again." >&2
  exit 1
fi
echo "$tree $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$(git rev-parse --git-dir)/green-trees"
echo "gate: GREEN. Tree $tree may be committed and pushed."
echo "      backend:  $(grep -E "[0-9]+ passed" "$log/pytest" | tail -1)"
echo "      frontend: $(grep -E "Tests " "$log/vitest" | tail -1 | sed 's/^ *//')"
