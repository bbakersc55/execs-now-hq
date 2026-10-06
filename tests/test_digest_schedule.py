"""The digest day, time and time zone (beta feedback, 2026-10-05, item E).

The practice owner sets them; everyone on the practice's staff can read them;
`hold_all_digests` has no switch here or anywhere."""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from django_q.models import Schedule

from apps.tenancy.management.commands.ensure_schedules import ensure_for
from apps.tenancy.models import AuditEvent
from apps.work import digests
from apps.work.models import Cadence

from . import registry_config  # noqa: F401
from .factories import ClientCompanyFactory, MembershipFactory, TenantFactory

URL = "/api/digests/schedule/"
CONFIRM = "/api/digests/schedule/confirm/"


def patch(client, data):
    return client.patch(URL, json.dumps(data), content_type="application/json")


def member(tenant, role):
    company = ClientCompanyFactory(tenant=tenant) if role in ("FCC", "ECC") else None
    return MembershipFactory(tenant=tenant, role=role, client_company=company)


# ------------------------------------------------------------------ who may

@pytest.mark.django_db
@pytest.mark.parametrize("role,read,write", [
    ("FF", 200, 200), ("CF", 200, 403), ("VA", 200, 403), ("FCC", 403, 403), ("ECC", 403, 403),
])
def test_staff_read_the_schedule_and_only_the_owner_changes_it(
    role, read, write, seeded_tenant, api
):
    client = api.as_(member(seeded_tenant, role))

    assert client.get(URL).status_code == read
    assert patch(client, {"day": 2}).status_code == write
    assert client.post(CONFIRM).status_code == write

    seeded_tenant.refresh_from_db()
    assert seeded_tenant.digest_send_day == (2 if write == 200 else 5)


@pytest.mark.django_db
def test_the_signed_out_get_nothing(client, seeded_tenant):
    assert client.get(URL).status_code in (401, 403)
    assert patch(client, {"day": 2}).status_code in (401, 403)
    assert client.post(CONFIRM).status_code in (401, 403)


@pytest.mark.django_db
def test_one_practices_schedule_never_touches_anothers(tenant_a, tenant_b, api):
    a = MembershipFactory(tenant=tenant_a, role="FF")
    b = MembershipFactory(tenant=tenant_b, role="FF")

    patch(api.as_(a), {"day": 1, "hour": 15, "timezone": "America/New_York"})

    tenant_b.refresh_from_db()
    assert (tenant_b.digest_send_day, tenant_b.digest_send_hour, tenant_b.timezone) \
        == (5, 8, "America/Denver")
    theirs = api.as_(b).get(URL).json()
    assert (theirs["day"], theirs["hour"], theirs["confirmed"]) == (5, 8, False)
    assert not AuditEvent.all_objects.filter(tenant=tenant_b).exists()


# ------------------------------------------------------------- what it does

@pytest.mark.django_db
def test_a_new_practice_is_friday_eight_mountain_and_unconfirmed(seeded_tenant, ff, api):
    assert api.as_(ff).get(URL).json() == {
        "day": 5, "day_name": "Friday", "hour": 8, "timezone": "America/Denver",
        "confirmed": False,
    }


@pytest.mark.django_db
def test_keeping_it_changes_nothing_and_is_asked_once(seeded_tenant, ff, api):
    body = api.as_(ff).post(CONFIRM).json()
    api.as_(ff).post(CONFIRM)

    assert body["confirmed"] is True and (body["day"], body["hour"]) == (5, 8)
    events = AuditEvent.all_objects.filter(tenant=seeded_tenant,
                                           verb="digest_schedule.confirmed")
    assert events.count() == 1 and events[0].actor_id == ff.user.pk


@pytest.mark.django_db
def test_changing_it_is_recorded_and_counts_as_confirmed(seeded_tenant, ff, api):
    body = patch(api.as_(ff), {"day": 4, "hour": 14, "timezone": "America/Chicago"}).json()

    assert body == {"day": 4, "day_name": "Thursday", "hour": 14,
                    "timezone": "America/Chicago", "confirmed": True}
    event = AuditEvent.all_objects.get(tenant=seeded_tenant, verb="digest_schedule.changed")
    assert event.payload == {
        "from": {"day": 5, "hour": 8, "timezone": "America/Denver"},
        "to": {"day": 4, "hour": 14, "timezone": "America/Chicago"},
    }


@pytest.mark.django_db
def test_the_next_weekly_digest_follows_the_new_day_hour_and_zone(seeded_tenant, ff, api):
    patch(api.as_(ff), {"day": 2, "hour": 15, "timezone": "America/New_York"})
    seeded_tenant.refresh_from_db()
    # Friday 2026-10-09, noon UTC.
    after = datetime(2026, 10, 9, 12, 0, tzinfo=ZoneInfo("UTC"))

    window = digests.next_window(seeded_tenant, Cadence.WEEKLY, after=after)

    local = window.astimezone(ZoneInfo("America/New_York"))
    assert (local.isoweekday(), local.hour, local.date().isoformat()) == (2, 15, "2026-10-13")


@pytest.mark.django_db
def test_a_digest_already_waiting_keeps_the_time_it_was_written_with(seeded_tenant, ff, api):
    from apps.work.models import Digest

    from .factories import ContactFactory

    waiting = Digest.all_objects.create(
        tenant=seeded_tenant, contact=ContactFactory(tenant=seeded_tenant),
        cadence=Cadence.WEEKLY,
        period_start=datetime(2026, 10, 2, 14, tzinfo=ZoneInfo("UTC")),
        period_end=datetime(2026, 10, 9, 14, tzinfo=ZoneInfo("UTC")),
        send_window_at=datetime(2026, 10, 9, 14, tzinfo=ZoneInfo("UTC")),
    )

    patch(api.as_(ff), {"day": 1, "hour": 6})

    waiting.refresh_from_db()
    assert waiting.send_window_at == datetime(2026, 10, 9, 14, tzinfo=ZoneInfo("UTC"))
    assert waiting.state == Digest.State.PENDING


@pytest.mark.django_db
def test_a_new_time_zone_moves_the_daily_jobs_to_its_local_hour(seeded_tenant, ff, api):
    ensure_for(seeded_tenant)
    name = f"crm.draft_referral_touches:{seeded_tenant.slug}"

    patch(api.as_(ff), {"timezone": "Pacific/Honolulu"})

    run = Schedule.objects.get(name=name).next_run.astimezone(ZoneInfo("Pacific/Honolulu"))
    assert run.hour == 6


@pytest.mark.django_db
@pytest.mark.parametrize("bad", [
    {"day": 0}, {"day": 8}, {"day": "Friday"}, {"day": True},
    {"hour": 24}, {"hour": -1}, {"hour": "8"},
    {"timezone": "Mars/Olympus"}, {"timezone": ""}, {"timezone": 7},
])
def test_a_bad_value_is_refused_and_nothing_changes(bad, seeded_tenant, ff, api):
    response = patch(api.as_(ff), {"day": 3, **bad} if "day" not in bad else bad)

    assert response.status_code == 400
    seeded_tenant.refresh_from_db()
    assert (seeded_tenant.digest_send_day, seeded_tenant.digest_send_hour,
            seeded_tenant.timezone) == (5, 8, "America/Denver")


@pytest.mark.django_db
def test_there_is_no_switch_for_holding_digests(seeded_tenant, ff, api):
    """Decided 2026-10-05: turning approval off is not a setting."""
    assert seeded_tenant.hold_all_digests is True

    response = patch(api.as_(ff), {"day": 2, "hold_all_digests": False})

    assert response.status_code == 400 and "hold_all_digests" in response.json()["detail"]
    seeded_tenant.refresh_from_db()
    assert seeded_tenant.hold_all_digests is True and seeded_tenant.digest_send_day == 5
    assert "hold_all_digests" not in api.as_(ff).get(URL).json()
