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

echo "gate: backend suite…"
# The project's addopts add a second -q, which hides the line that counts.
.venv/bin/python -m pytest -o addopts="--strict-markers" -q -p no:cacheprovider >"$log/pytest" 2>&1 || fail "the backend suite" $? "$log/pytest"
echo "gate: migration check…"
.venv/bin/python manage.py makemigrations --check --dry-run >"$log/migrations" 2>&1 || fail "the migration check (a model change has no migration)" $? "$log/migrations"
echo "gate: frontend type check…"
(cd frontend && npx tsc --noEmit -p .) >"$log/tsc" 2>&1 || fail "the frontend type check" $? "$log/tsc"
echo "gate: frontend suite…"
(cd frontend && npx vitest run) >"$log/vitest" 2>&1 || fail "the frontend suite" $? "$log/vitest"

# Still the tree that was tested: nothing was staged while the suites ran.
if [ "$(git write-tree)" != "$tree" ] || ! git diff --quiet; then
  echo "gate: the files changed while the suites were running. Run it again." >&2
  exit 1
fi
echo "$tree $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$(git rev-parse --git-dir)/green-trees"
echo "gate: GREEN. Tree $tree may be committed and pushed."
echo "      backend:  $(grep -E "[0-9]+ passed" "$log/pytest" | tail -1)"
echo "      frontend: $(grep -E "Tests " "$log/vitest" | tail -1 | sed 's/^ *//')"
