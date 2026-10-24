"""Register every periodic job, per tenant. Idempotent — run it after a deploy.

Before Phase 2 nothing registered a schedule at all: the jobs existed and were
tested, but `django_q_schedule` was empty, so none of them ever ran — no
referral touch was ever drafted, no Outbox draft ever expired, and no contact
was ever in the search index. This list is the single place a periodic job is
declared.

Re-running updates what each job calls and how often, but does not move a
schedule's next run that is on cadence: that would re-fire a daily job every
time this ran. It DOES realign one that has fallen more than one interval
behind, which now matters only for a daily job's local hour — `catch_up` is off
(settings.Q_CLUSTER), so Django-Q's scheduler collapses a backlog itself and
fires a behind job once, at whatever time the cluster came back. Realigning
puts the daily ones back on their proper hour instead.

While `catch_up` was on, Django-Q advanced a stale next run by one interval per
scheduler pass, so a one-minute job left three days behind by a stopped cluster
fired every ~30 seconds for days instead of once a minute, and this command was
the only thing that stopped it (Phase 3: `work.tick` was stuck at 12 Sep).
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
    # Module 5 — the folder poll (FR-5.2). Ten minutes, cursor-based, so a
    # laptop that was shut for three days catches up rather than missing three
    # days of notes.
    ("meetings.poll_drive", "apps.meetings.tasks.poll_drive", Schedule.MINUTES, 10, None),
    # FR-5.1b: the folder backfill, paced. Every minute, and a no-op unless a
    # backfill is running — which is the normal state.
    ("meetings.run_backfill", "apps.meetings.tasks.run_backfill",
     Schedule.MINUTES, 1, None),
    # Module 6 — the inbound poll (FR-6.5). Fifteen minutes, over the threads
    # the app started. Tolerant of a closed laptop: `threads.get` returns the
    # whole thread, so catching up is the same operation as keeping up.
    ("crm.poll_inbound", "apps.crm.tasks.poll_inbound", Schedule.MINUTES, 15, None),
    # Module 2.
    ("notes.process", "apps.notes.tasks.process_notes", Schedule.MINUTES, 1, None),
    ("notes.purge_expired_audio", "apps.notes.tasks.purge_expired_audio",
     Schedule.DAILY, None, None),
    # P4A: a recurring invoice's draft, on its day. Writes a draft only; it
    # numbers nothing and sends nothing.
    ("billing.run_invoice_schedules", "apps.billing.tasks.run_invoice_schedules",
     Schedule.DAILY, None, 5),
    # P4 part 2: a card payment whose answer from NMI was lost, looked up by
    # our reference until it is known. A no-op unless one is waiting.
    ("billing.resolve_card_payments", "apps.billing.tasks.resolve_card_payments",
     Schedule.MINUTES, 10, None),
    # P4 part 4: auto-pay, on each invoice's due date, at the practice's
    # 9:00; a failed charge once more the next day; card-expiry notices.
    # Safe to run twice: an attempt made today is never made again.
    ("billing.run_autopay", "apps.billing.tasks.run_autopay", Schedule.DAILY, None, 9),
    # P4 part 5: the practice's own subscription, charged by the app on the
    # 1st (a missed day catches up), and a lost answer looked up. The one job
    # a suspended practice keeps: paying is what lifts the suspension.
    ("billing.charge_subscription", "apps.billing.tasks.charge_subscription",
     Schedule.DAILY, None, 7),
    # P6 M2: the month's forecast, kept for "how good it has been". Daily at
    # the practice's midnight, so the 1st is caught as the month begins and a
    # missed 1st the day after; a no-op once the month's is kept, and for a
    # practice without the Cash forecast.
    ("finance.keep_month_forecast", "apps.finance.tasks.keep_month_forecast",
     Schedule.DAILY, None, 0),
    # M5 part 1: a reading owner is reminded once when a period closes
    # without a value, the morning after (a week's close is Monday morning).
    # Safe to run twice: a period is reminded once.
    ("scorecard.remind_missing", "apps.scorecard.tasks.remind_missing",
     Schedule.DAILY, None, 8),
    # M5 part 3: the Google Sheet feeds. Hourly; each feed's own refresh
    # (hourly or daily) decides whether this pass reads it. A no-op for a
    # practice with no feed.
    ("scorecard.read_feeds", "apps.scorecard.tasks.read_feeds", Schedule.HOURLY, None, None),
]


#: What a suspended practice still runs (P4 part 5).
SUSPENDED_RUNS = ("billing.charge_subscription",)


def _first_run(tenant, local_hour):
    if local_hour is None:
        return timezone.now()
    zone = ZoneInfo(tenant.timezone)
    now = timezone.now().astimezone(zone)
    candidate = datetime.combine(now.date(), time(local_hour), tzinfo=zone)
    return candidate if candidate > now else candidate + timedelta(days=1)


def _interval(schedule_type, minutes):
    return {
        Schedule.MINUTES: timedelta(minutes=minutes or 1),
        Schedule.HOURLY: timedelta(hours=1),
        Schedule.DAILY: timedelta(days=1),
    }.get(schedule_type)


def realigned_next_run(tenant, schedule_type, minutes, local_hour, next_run, now=None):
    """The next run a behind schedule should have, or None when it is on cadence.

    Minute and hourly jobs simply run now and then keep their cadence. A daily
    job with a local hour goes to its next occurrence; one without runs now,
    which is the single catch-up a missed daily job is owed.
    """
    now = now or timezone.now()
    interval = _interval(schedule_type, minutes)
    if interval is None or next_run is None or next_run >= now - interval:
        return None
    return _first_run(tenant, local_hour) if local_hour is not None else now


def realign_local_hours(tenant) -> int:
    """After the practice's time zone changes: the daily jobs that run at a
    local hour move to that hour in the new zone. Minute and hourly jobs have
    no local hour and are left alone."""
    moved = 0
    for name, _func, _type, _minutes, local_hour in SCHEDULES:
        if local_hour is None:
            continue
        moved += Schedule.objects.filter(name=f"{name}:{tenant.slug}").update(
            next_run=_first_run(tenant, local_hour))
    return moved


def ensure_for(tenant, write=None, only=None) -> None:
    """Create or update one practice's schedules (P2: provisioning and
    unarchiving call this for the one practice). `only`: just those."""
    for name, func, schedule_type, minutes, local_hour in SCHEDULES:
        if only is not None and name not in only:
            continue
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
            verb = "updated"
            realigned = realigned_next_run(tenant, schedule_type, minutes, local_hour,
                                           schedule.next_run)
            if realigned is not None:
                Schedule.objects.filter(pk=schedule.pk).update(next_run=realigned)
                verb = "realigned"
            schedule.refresh_from_db()
        if write:
            write(f"{verb:8} {full_name:45} next run {schedule.next_run:%Y-%m-%d %H:%M %Z}")


def remove_for(tenant, keep=()) -> int:
    """Delete one practice's schedules: an archived practice runs nothing, a
    suspended one only what is in `keep`."""
    names = [f"{name}:{tenant.slug}" for name, *_ in SCHEDULES if name not in keep]
    deleted, _ = Schedule.objects.filter(name__in=names).delete()
    return deleted


class Command(BaseCommand):
    help = "Create or update the periodic job schedules for every active practice."

    def handle(self, *args, **options):
        for tenant in Tenant.objects.order_by("slug"):
            if tenant.status == Tenant.Status.ARCHIVED:
                # An archived practice runs nothing (P2), and this command is
                # run after every pull: it must not bring the jobs back.
                remove_for(tenant)
                self.stdout.write(f"{'skipped':8} {tenant.slug:45} archived")
                continue
            if tenant.status == Tenant.Status.SUSPENDED:
                remove_for(tenant, keep=SUSPENDED_RUNS)
                ensure_for(tenant, self.stdout.write, only=SUSPENDED_RUNS)
                continue
            ensure_for(tenant, self.stdout.write)
