"""Add "Operations — focused" to a practice and make it the default
(owner, 2026-09-29). Dry run by default, like every other change to live data.

    python manage.py add_focused_template --tenant <slug>          # says what it would do
    python manage.py add_focused_template --tenant <slug> --apply  # does it

Sessions already started keep the template they were started with: each has
its own frozen snapshot. Only the next session started takes the new default.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.strategy import seed
from apps.strategy.models import StrategyTemplate
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Tenant


class Command(BaseCommand):
    help = "Add the focused strategy template to a practice and make it the default."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", required=True, help="The practice's slug.")
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        tenant = Tenant.objects.filter(slug=options["tenant"]).first()
        if tenant is None:
            raise CommandError(f"No practice with slug {options['tenant']!r}.")
        with tenant_context(tenant.pk):
            current = StrategyTemplate.objects.filter(
                discipline=seed.DISCIPLINE, is_default=True).first()
            exists = StrategyTemplate.objects.filter(name=seed.FOCUSED_NAME).exists()
            self.stdout.write(f"{tenant.name}: default now "
                              f"{current.name if current else '(none)'!r}; "
                              f"{seed.FOCUSED_NAME!r} {'exists' if exists else 'would be created'}"
                              f" and made the default.")
            if not options["apply"]:
                self.stdout.write("Dry run: nothing changed. Add --apply.")
                return
            template = seed.create_focused(tenant)
            questions = template.questions.filter(deleted_at__isnull=True).count()
            self.stdout.write(f"Done: {template.name!r} is the default ({questions} questions).")
