"""Fingerprint every real strategy session on the laptop (P3 phase 1, 2026-10-03).

Reads each session on `execsnowhq_local` and hashes what the app would show
for it today: the session payload as the practice owner and as an assistant,
the PDF's HTML, the covering note, the pre-call questions and the conversion
preview. Run once before P3 code exists (`--write`) and again at the head of
each P3 phase (`--check`): the output hashes must match
(`docs/p3_strategy_templates_session_v3.md` §6.2).

    .venv/bin/python scripts/strategy_session_fingerprints.py --write
    .venv/bin/python scripts/strategy_session_fingerprints.py --check

**Read-only.** Nothing is stored or sent: every session is read inside a
transaction that is rolled back. The file it writes holds hashes only, with
each session named by a hash of its id, so nothing from inside a practice
leaves the database.

A session whose *data* changed since the baseline (the laptop was refreshed
from production, or someone edited it) is reported separately from one whose
data is the same and whose *output* differs. Only the second is a regression.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.db import connection, transaction  # noqa: E402

BASELINE = ROOT / "tests" / "golden" / "strategy_v2" / "real_sessions_execsnowhq_local.json"
DATABASE = "execsnowhq_local"
#: "Today" for anything that prints a date, so a baseline taken on one day
#: still matches on another.
FROZEN = datetime(2026, 10, 3, 18, 0, tzinfo=dt_timezone.utc)


def sha(value) -> str:
    if not isinstance(value, str):
        value = json.dumps(value, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(value.encode()).hexdigest()


def _sorted_answers(payload: dict) -> dict:
    """The API returns answers in database order; the order is not behavior."""
    return {**payload, "answers": sorted(payload.get("answers", []),
                                         key=lambda a: a["question_key"])}


def data_of(session) -> str:
    """A hash of the session's own rows: what the outputs are made from."""
    from apps.strategy.models import (
        StrategyAnswer, StrategyDiagnosticProposal, StrategyMapRow, StrategyPathNote,
        StrategyPrepQuestion, StrategySessionPrep,
    )

    def rows(model, **where):
        return sorted(json.dumps(row, sort_keys=True, default=str)
                      for row in model.objects.filter(**where).values())

    own = {f.attname: getattr(session, f.attname) for f in session._meta.concrete_fields}
    return sha({
        "session": own,
        "answers": rows(StrategyAnswer, session=session),
        "map_rows": rows(StrategyMapRow, session=session),
        "path_notes": rows(StrategyPathNote, session=session),
        "proposals": rows(StrategyDiagnosticProposal, session=session),
        "prep": rows(StrategySessionPrep, session=session),
        "prep_questions": rows(StrategyPrepQuestion, session=session),
    })


def outputs_of(session) -> dict:
    from apps.strategy import conversion, emails, pdf, serializers, services

    def attempt(fn):
        try:
            return fn()
        except Exception as exc:                 # a refusal is an output too
            return f"{type(exc).__name__}: {exc}"

    return {
        "payload_practice_owner": sha(_sorted_answers(serializers.represent_session(
            session, include_financial=True, full=True, include_prep=True))),
        "payload_assistant": sha(_sorted_answers(serializers.represent_session(
            session, include_financial=False, full=True, include_prep=False))),
        "pdf_html": sha(attempt(lambda: pdf.render_html(session))),
        "pdf_cover_note": sha(attempt(lambda: emails.default_pdf_cover(session))),
        "precall_questions": sha(attempt(lambda: emails.question_blocks(session))),
        "conversion_preview": sha(attempt(lambda: conversion.preview(session))),
        "ratings": sha(services.six_key_components(session)),
        "must_ask": sha(services.must_ask_outstanding(session)),
    }


def fingerprint() -> dict:
    from apps.strategy import services
    from apps.strategy.models import StrategySession
    from apps.tenancy.context import tenant_context

    sessions = {}
    with mock.patch("django.utils.timezone.now", return_value=FROZEN):
        for session in StrategySession.all_objects.order_by("created_at"):
            with tenant_context(session.tenant_id), transaction.atomic():
                session = StrategySession.objects.select_related(
                    "tenant", "contact", "company", "visionary_contact",
                    "integrator_contact", "owner").get(pk=session.pk)
                sessions[sha(str(session.pk))[:12]] = {
                    "format": services.format_of(session),
                    "state": session.state,
                    "archived": session.archived_at is not None,
                    "data": data_of(session),
                    "outputs": outputs_of(session),
                }
                transaction.set_rollback(True)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True).stdout.strip()
    return {"database": connection.settings_dict["NAME"], "commit": commit,
            "sessions": sessions}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="record the baseline")
    mode.add_argument("--check", action="store_true", help="compare with the baseline")
    args = parser.parse_args()

    name = connection.settings_dict["NAME"]
    if name != DATABASE:
        print(f"Refused: the configured database is {name!r}, not {DATABASE!r}.")
        return 2

    now = fingerprint()
    if args.write:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(now, indent=2, sort_keys=True) + "\n")
        print(f"Baseline written at {now['commit']}: {len(now['sessions'])} sessions.")
        for key, row in now["sessions"].items():
            print(f"  {key}  {row['format']:8} {row['state']:10}"
                  f"{' archived' if row['archived'] else ''}")
        return 0

    was = json.loads(BASELINE.read_text())
    same = changed_data = 0
    regressions = []
    for key, before in was["sessions"].items():
        after = now["sessions"].get(key)
        if after is None:
            print(f"  {key}  no longer in the database")
            changed_data += 1
        elif after["data"] != before["data"]:
            print(f"  {key}  its data changed since the baseline; not comparable")
            changed_data += 1
        elif after["outputs"] != before["outputs"]:
            which = sorted(name for name in before["outputs"]
                           if before["outputs"][name] != after["outputs"].get(name))
            regressions.append(key)
            print(f"  {key}  DIFFERENT, same data: {', '.join(which)}")
        else:
            same += 1
    new = len(set(now["sessions"]) - set(was["sessions"]))
    print(f"Baseline {was['commit']} against {now['commit']}: {same} identical, "
          f"{len(regressions)} different, {changed_data} not comparable, {new} new "
          f"since the baseline.")
    return 1 if regressions else 0


if __name__ == "__main__":
    sys.exit(main())
