"""Put the six rating prompts right **inside one session's snapshot**.

A session renders from the template it froze, and that is deliberate: AC-4.12
exists so an edit mid-engagement cannot move anything under a fractional
mid-call. This command is the one thing that reaches past it, and it exists
because of the incident of 2026-09-22 — a session was started from a template
whose six ratings had already been reworded into essay questions, so its
snapshot preserves the mistake faithfully.

**It is narrow on purpose.** One session, named on the command line; only
questions whose `response_schema` is `rating_1_10`; only their `prompt`; and
only where that prompt is not already the seed's. Nothing else in the snapshot
is touched, no answer is touched, and the before and after of every question it
changes goes into an `audit_event` so the patch is readable afterwards by
somebody who was not here.

    manage.py patch_session_rating_prompts <session-id>
    manage.py patch_session_rating_prompts <session-id> --apply
"""

from __future__ import annotations

import uuid

from django.core.management.base import BaseCommand, CommandError

from apps.strategy.models import StrategySession
from apps.strategy.rewording import RATING_COMPONENTS, RATING_SCHEMA
from apps.tenancy.context import tenant_context
from apps.tenancy.models import AuditEvent


def patch_snapshot(snapshot: dict) -> tuple[dict, list[dict]]:
    """Returns the new snapshot and what changed. Pure: no database, so a test
    can hold it to exactly what it may and may not touch."""
    changed: list[dict] = []
    sections = []
    for section in snapshot.get("sections", []):
        questions = []
        for question in section.get("questions", []):
            seeded = RATING_COMPONENTS.get(question.get("key", ""))
            if (seeded and question.get("response_schema") == RATING_SCHEMA
                    and question.get("prompt") != seeded):
                changed.append({"key": question["key"], "was": question["prompt"],
                                "now": seeded})
                question = {**question, "prompt": seeded}
            questions.append(question)
        sections.append({**section, "questions": questions})
    return {**snapshot, "sections": sections}, changed


class Command(BaseCommand):
    help = "Restore the six rating prompts inside one session's frozen snapshot."

    def add_arguments(self, parser):
        parser.add_argument("session")
        parser.add_argument("--apply", action="store_true",
                            help="Write it. Without this, a dry run.")

    def handle(self, *args, **options):
        try:
            session_id = uuid.UUID(options["session"])
        except ValueError as exc:
            raise CommandError("That is not a session id.") from exc
        session = StrategySession.all_objects.filter(pk=session_id).first()
        if session is None:
            raise CommandError("No session with that id.")

        patched, changed = patch_snapshot(session.template_snapshot)
        who = f"{session.contact.first_name} {session.contact.last_name}".strip()
        if not changed:
            self.stdout.write(f"{who}: the six already read as the seed wrote them.")
            return

        self.stdout.write(self.style.WARNING(
            f"{who} ({session.pk}): {len(changed)} to restore"))
        for row in changed:
            self.stdout.write(f"  {row['key']}\n    was: {row['was']}\n"
                              f"    now: {row['now']}")
        if not options["apply"]:
            self.stdout.write(self.style.NOTICE(
                "\nDry run. Re-run with --apply to write it."))
            return

        with tenant_context(session.tenant_id):
            session.template_snapshot = patched
            session.save(update_fields=["template_snapshot", "updated_at"])
            AuditEvent.all_objects.create(
                tenant_id=session.tenant_id, actor=None,
                verb="strategy.session_snapshot_patched",
                target_type="strategy_session", target_id=session.pk,
                payload={"reason": "incident 2026-09-22",
                         "what": "the six rating prompts, restored to the seed",
                         "changed": changed})
        self.stdout.write(self.style.SUCCESS(f"\n{len(changed)} restored, and audited."))
