"""Put the six Six Key Components back to the seed's wording.

The incident of 2026-09-22: prep suggested essay rewordings for the six, they
were applied to the template, and a prospect was emailed six open questions
under the heading *"Rate each one from 1 to 10"*.

The guard that stops it happening again is in `apps.strategy.rewording`. This
puts right what it did not stop, and it is **a one-off repair run by a person,
not a migration**: migration history in this project stays additive, and a
data rewrite is something the owner asks for out loud.

    manage.py repair_rating_prompts            # says what it would do
    manage.py repair_rating_prompts --apply    # does it

It is idempotent, it names every change, and it touches **only** questions whose
schema is `rating_1_10` and whose wording is not already the seed's.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.strategy.models import StrategyQuestion, StrategyTemplate
from apps.strategy.rewording import RATING_COMPONENTS, RATING_SCHEMA
from apps.tenancy.context import tenant_context
from apps.tenancy.models import AuditEvent


class Command(BaseCommand):
    help = "Restore the six Six Key Components prompts to the seed wording."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="Write the changes. Without it, this is a dry run.")

    def handle(self, *args, **options):
        apply_it = options["apply"]
        total = 0
        for template in StrategyTemplate.all_objects.all().order_by("name"):
            with tenant_context(template.tenant_id):
                changed = []
                for key, seeded in RATING_COMPONENTS.items():
                    question = StrategyQuestion.objects.filter(
                        template=template, key=key, response_schema=RATING_SCHEMA,
                        deleted_at__isnull=True).first()
                    if question is None or question.prompt == seeded:
                        continue
                    changed.append((key, question.prompt, seeded))
                    if apply_it:
                        question.prompt = seeded
                        question.save(update_fields=["prompt", "updated_at"])
                if not changed:
                    self.stdout.write(f"{template.name}: already the seed's wording.")
                    continue
                total += len(changed)
                self.stdout.write(self.style.WARNING(
                    f"{template.name}: {len(changed)} to restore"))
                for key, was, now in changed:
                    self.stdout.write(f"  {key}\n    was: {was}\n    now: {now}")
                if apply_it:
                    AuditEvent.all_objects.create(
                        tenant_id=template.tenant_id, actor=None,
                        verb="strategy.rating_prompts_repaired",
                        target_type="strategy_template", target_id=template.pk,
                        payload={"keys": [key for key, _w, _n in changed],
                                 "reason": "incident 2026-09-22"})
        if not apply_it and total:
            self.stdout.write(self.style.NOTICE(
                f"\n{total} would change. Re-run with --apply to write them."))
        elif apply_it and total:
            self.stdout.write(self.style.SUCCESS(f"\n{total} restored."))
