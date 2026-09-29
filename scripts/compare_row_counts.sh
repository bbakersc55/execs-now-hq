#!/usr/bin/env bash
# Exact row counts, table by table, on two databases; exit non-zero on any
# difference (Phase 7 runbook B5 — the gate at C4.5 and C7.4).
#
#   scripts/compare_row_counts.sh SOURCE TARGET
#
# SOURCE and TARGET are anything psql accepts: a database name on this laptop
# ("execsnowhq_dev") or a postgres:// URL (Railway's public URL).
#
# Exact `count(*)` for every table, never pg_class estimates: an estimate that
# happens to match proves nothing. Read-only on both sides.
#
# The Django-Q tables (django_q_*) are listed separately and never fail the
# comparison, because the runbook empties them on purpose after a restore
# (C4.4 and C7.3). Every other table must match exactly, and a table present
# on one side only is a failure.
set -euo pipefail

if [ $# -ne 2 ]; then
  echo "usage: $0 SOURCE TARGET" >&2
  exit 2
fi

COUNTS_SQL="
SELECT table_name || E'\t' ||
       (xpath('/row/c/text()',
              query_to_xml(format('SELECT count(*) AS c FROM %I.%I',
                                  table_schema, table_name), false, true, '')))[1]::text
FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
ORDER BY table_name;"

TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

psql -X -q -At -v ON_ERROR_STOP=1 -d "$1" -c "${COUNTS_SQL}" > "${TMP}/source"
psql -X -q -At -v ON_ERROR_STOP=1 -d "$2" -c "${COUNTS_SQL}" > "${TMP}/target"

cut -f1 "${TMP}/source" "${TMP}/target" | sort -u > "${TMP}/names"

# Plain POSIX awk (the laptop's is mawk): files read in order source, target,
# then the sorted union of table names.
awk -F'\t' '
  FILENAME == ARGV[1] { source[$1] = $2; next }
  FILENAME == ARGV[2] { target[$1] = $2; next }
  FNR == 1 { printf "%-44s %12s %12s\n", "table", "source", "target" }
  {
    t = $1
    s = (t in source) ? source[t] : "-"
    g = (t in target) ? target[t] : "-"
    mark = ""
    if (t ~ /^django_q_/) { mark = "  (queue: emptied on purpose, not compared)" }
    else if (s == "-" || g == "-") { mark = "  !! ON ONE SIDE ONLY"; bad++ }
    else if (s != g) { mark = "  !! MISMATCH"; bad++ }
    else { tables++; rows += s }
    printf "%-44s %12s %12s%s\n", t, s, g, mark
  }
  END {
    printf "\n%d tables match exactly (%d rows). %d problem(s).\n", tables, rows, bad
    exit (bad > 0)
  }' "${TMP}/source" "${TMP}/target" "${TMP}/names"
