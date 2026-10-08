"""Entries for invoice payments recorded before the books existed (P5, F13).

    manage.py backfill_invoice_income            # counts, writes nothing
    manage.py backfill_invoice_income --apply    # writes them

Safe to run again: a payment that has its entry gets no other.
"""

from django.core.management.base import BaseCommand

from apps.finance import services
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Tenant


class Command(BaseCommand):
    help = "Write income entries for invoice payments that have none. Dry run by default."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, apply=False, **options):
        total = 0
        for tenant in Tenant.objects.order_by("created_at"):
            with tenant_context(tenant.pk):
                count = services.backfill_payments(tenant, apply=apply)
            if count:
                self.stdout.write(f"{tenant.slug}: {count} payment(s)")
            total += count
        self.stdout.write(("Wrote entries for " if apply else "Would write entries for ")
                          + f"{total} payment(s)." + ("" if apply else " Nothing was written."))
