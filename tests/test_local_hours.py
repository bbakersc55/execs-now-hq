"""The daily jobs keep their practice-time hour through daylight-saving
changes (2026-11-17). Django-Q adds 24 hours in UTC (its own correction reads
settings.TIME_ZONE, which is UTC), so after the clocks went back on November
1, 2026, the 5:00, 7:00 and 9:00 jobs ran at 4:00, 6:00 and 8:00 practice
time. `keep_local_hours`, hourly, moves each back onto its hour."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from django.core.management import call_command
from django_q.models import Schedule

from apps.tenancy.management.commands import ensure_schedules as E

from . import registry_config  # noqa: F401


def utc(*parts):
    return datetime(*parts, tzinfo=UTC)


@pytest.fixture
def denver(seeded_tenant):
    seeded_tenant.timezone = "America/Denver"
    seeded_tenant.save(update_fields=["timezone"])
    return seeded_tenant


@pytest.mark.parametrize("drifted, local_hour, right", [
    # Fall back (November 1, 2026): 7:00 MDT was 13:00 UTC; +24 h is 6:00 MST.
    (utc(2026, 11, 1, 13), 7, utc(2026, 11, 1, 14)),
    (utc(2026, 11, 18, 15), 9, utc(2026, 11, 18, 16)),
    # Spring forward (March 14, 2027): 9:00 MST was 16:00 UTC; +24 h is 10:00 MDT.
    (utc(2027, 3, 14, 16), 9, utc(2027, 3, 14, 15)),
    # Midnight jobs, across the date line in both directions.
    # (0:00 MDT November 1 was 6:00 UTC; +24 h is 23:00 MST that evening.)
    (utc(2026, 11, 2, 6), 0, utc(2026, 11, 2, 7)),
    (utc(2027, 3, 15, 7), 0, utc(2027, 3, 15, 6)),
    # Already on its hour: unchanged.
    (utc(2026, 11, 18, 14), 7, utc(2026, 11, 18, 14)),
])
@pytest.mark.django_db
def test_the_nearest_run_on_the_practice_hour(denver, drifted, local_hour, right):
    assert E.on_local_hour(denver, local_hour, drifted) == right


@pytest.mark.django_db
def test_django_q_drifts_and_the_hourly_pass_puts_each_daily_job_back(denver):
    call_command("ensure_schedules", stdout=open("/dev/null", "w"))
    slug = denver.slug
    autopay = Schedule.objects.get(name=f"billing.run_autopay:{slug}")
    # The 9:00 run on October 31 (MDT), then what Django-Q itself sets next.
    autopay.next_run = utc(2026, 10, 31, 15)
    nxt = autopay.calculate_next_run()
    assert nxt == utc(2026, 11, 1, 15)                       # 8:00 MST: an hour early
    Schedule.objects.filter(pk=autopay.pk).update(next_run=nxt)
    minute = Schedule.objects.get(name=f"work.tick:{slug}")
    minute_before = minute.next_run
    assert E.keep_local_hours(denver, now=utc(2026, 10, 31, 16)) >= 1
    autopay.refresh_from_db()
    assert autopay.next_run == utc(2026, 11, 1, 16)          # 9:00 MST
    minute.refresh_from_db()
    assert minute.next_run == minute_before                  # minute jobs are left alone
    # Once on the hour, nothing moves: never skipped, never doubled.
    assert E.keep_local_hours(denver, now=utc(2026, 10, 31, 17)) == 0


@pytest.mark.django_db
def test_a_run_about_to_be_taken_is_left_to_the_scheduler(denver):
    call_command("ensure_schedules", stdout=open("/dev/null", "w"))
    row = Schedule.objects.get(name=f"billing.run_autopay:{denver.slug}")
    Schedule.objects.filter(pk=row.pk).update(next_run=utc(2026, 11, 18, 15))
    assert E.keep_local_hours(denver, now=utc(2026, 11, 18, 15) - timedelta(minutes=2)) == 0
    row.refresh_from_db()
    assert row.next_run == utc(2026, 11, 18, 15)


@pytest.mark.django_db
def test_every_daily_job_with_an_hour_is_kept_and_the_pass_is_scheduled(denver):
    call_command("ensure_schedules", stdout=open("/dev/null", "w"))
    hourly = Schedule.objects.get(name=f"tenancy.keep_local_hours:{denver.slug}")
    assert hourly.schedule_type == Schedule.HOURLY
    daily = [(name, hour) for name, _f, kind, _m, hour in E.SCHEDULES
             if kind == Schedule.DAILY and hour is not None]
    assert {"billing.run_invoice_schedules", "billing.charge_subscription",
            "billing.run_autopay"} <= {name for name, _ in daily}
    late = utc(2026, 12, 1, 0)
    for name, hour in daily:
        Schedule.objects.filter(name=f"{name}:{denver.slug}").update(
            next_run=E.on_local_hour(denver, hour, late + timedelta(days=1)) - timedelta(hours=1))
    from apps.tenancy.tasks import keep_local_hours

    assert keep_local_hours(str(denver.pk)) == len(daily)
    for name, hour in daily:
        row = Schedule.objects.get(name=f"{name}:{denver.slug}")
        local = row.next_run.astimezone(E.ZoneInfo("America/Denver"))
        assert (local.hour, local.minute) == (hour, 0), name
