"""Register every periodic job, per tenant. Idempotent — run it after a deploy.

Before Phase 2 nothing registered a schedule at all: the jobs existed and were
tested, but `django_q_schedule` was empty, so none of them ever ran. This list
is the single place a periodic job is declared.

Module 1's three jobs (draft_referral_touches, expire_outbox, reindex_search)
are deliberately NOT here yet: turning them on starts drafting touches for
every referral partner in the live Outbox, which is the owner's call.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django_q.models import Schedule

from apps.tenancy.models import Tenant

SCHEDULES = [
    # (name, function, schedule_type, minutes)
    ("notes.process", "apps.notes.tasks.process_notes", Schedule.MINUTES, 1),
    ("notes.purge_expired_audio", "apps.notes.tasks.purge_expired_audio", Schedule.DAILY, None),
]


class Command(BaseCommand):
    help = "Create or update the periodic job schedules for every tenant."

    def handle(self, *args, **options):
        for tenant in Tenant.objects.order_by("slug"):
            for name, func, schedule_type, minutes in SCHEDULES:
                full_name = f"{name}:{tenant.slug}"
                _, created = Schedule.objects.update_or_create(
                    name=full_name,
                    defaults={
                        "func": func, "args": repr(str(tenant.pk)),
                        "schedule_type": schedule_type, "minutes": minutes,
                        "repeats": -1,
                    },
                )
                self.stdout.write(f"{'created' if created else 'updated'}  {full_name}")
