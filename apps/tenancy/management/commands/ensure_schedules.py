"""Register every periodic job, per tenant. Idempotent — run it after a deploy.

Before Phase 2 nothing registered a schedule at all: the jobs existed and were
tested, but `django_q_schedule` was empty, so none of them ever ran — no
referral touch was ever drafted, no Outbox draft ever expired, and no contact
was ever in the search index. This list is the single place a periodic job is
declared.

Re-running updates what each job calls and how often, but never moves a
schedule's next run: that would re-fire a daily job every time this ran.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand
from django.utils import timezone
from django_q.models import Schedule

from apps.tenancy.models import Tenant

SCHEDULES = [
    # (name, function, schedule_type, minutes, first run at this local hour)
    # Module 1 — turned on 2026-09-11, owner decision.
    # FR-1.21: drafts touches due within 3 days into the Outbox. Never sends.
    ("crm.draft_referral_touches", "apps.crm.tasks.draft_referral_touches",
     Schedule.DAILY, None, 6),
    # FR-1.18: an unapproved draft past its send-by expires. It does not send.
    ("crm.expire_outbox", "apps.crm.tasks.expire_outbox", Schedule.HOURLY, None, None),
    # FR-1.33: contact full-text search reads a stored vector nothing else writes.
    ("crm.reindex_search", "apps.crm.tasks.reindex_search", Schedule.HOURLY, None, None),
    # Module 3 — one tick: quiet windows, generation, expiry, sending, and the
    # client-activity notice. FR-3.23's timing lives in the code, not here, so
    # a tenant's own send day and hour govern it.
    ("work.tick", "apps.work.tasks.tick", Schedule.MINUTES, 1, None),
    # Module 2.
    ("notes.process", "apps.notes.tasks.process_notes", Schedule.MINUTES, 1, None),
    ("notes.purge_expired_audio", "apps.notes.tasks.purge_expired_audio",
     Schedule.DAILY, None, None),
]


def _first_run(tenant, local_hour):
    if local_hour is None:
        return timezone.now()
    zone = ZoneInfo(tenant.timezone)
    now = timezone.now().astimezone(zone)
    candidate = datetime.combine(now.date(), time(local_hour), tzinfo=zone)
    return candidate if candidate > now else candidate + timedelta(days=1)


class Command(BaseCommand):
    help = "Create or update the periodic job schedules for every tenant."

    def handle(self, *args, **options):
        for tenant in Tenant.objects.order_by("slug"):
            for name, func, schedule_type, minutes, local_hour in SCHEDULES:
                full_name = f"{name}:{tenant.slug}"
                fields = {
                    "func": func, "args": repr(str(tenant.pk)),
                    "schedule_type": schedule_type, "minutes": minutes, "repeats": -1,
                }
                schedule = Schedule.objects.filter(name=full_name).first()
                if schedule is None:
                    schedule = Schedule.objects.create(
                        name=full_name, next_run=_first_run(tenant, local_hour), **fields
                    )
                    verb = "created"
                else:
                    Schedule.objects.filter(pk=schedule.pk).update(**fields)
                    schedule.refresh_from_db()
                    verb = "updated"
                self.stdout.write(
                    f"{verb:8} {full_name:45} next run {schedule.next_run:%Y-%m-%d %H:%M %Z}"
                )
