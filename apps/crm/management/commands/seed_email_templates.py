"""Seed every practice's template library (crm 0041 does the same at
migrate). `--dry-run` says what it would add or change and writes nothing:
the dry run shown before the migration is applied anywhere."""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Seed each practice's email template library with the app's own wording."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Say what would be done; write nothing.")

    def handle(self, *args, dry_run=False, **options):
        from apps.crm import template_seed
        from apps.tenancy.models import Tenant

        with transaction.atomic():
            for tenant in Tenant.objects.order_by("name"):
                done = template_seed.seed_tenant(tenant, dry_run=dry_run)
                self.stdout.write(f"{tenant.name} ({tenant.slug}): "
                                  + (f"{len(done)} change(s)" if done else "nothing to do"))
                for line in done:
                    self.stdout.write(f"    {line}")
            moved = template_seed.touch_modes(dry_run=dry_run)
            self.stdout.write(f"Partners moved from the old \"AI-drafted\" touch to \"My "
                              f"template\" (the same words): {moved}")
        if dry_run:
            self.stdout.write("Dry run: nothing was written.")
