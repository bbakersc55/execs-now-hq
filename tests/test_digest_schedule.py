"""The digest day, time and time zone (beta feedback, 2026-10-05, item E).

The practice owner sets them; everyone on the practice's staff can read them;
`hold_all_digests` has no switch here or anywhere."""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from django_q.models import Schedule

from apps.tenancy.context import tenant_context
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
    body = api.as_(ff).get(URL).json()
    assert {k: body[k] for k in ("draft_day", "draft_day_name", "draft_hour", "day",
                                 "day_name", "hour", "timezone", "confirmed",
                                 "outside_working_hours")} == {
        # Drafted Thursday 8:00 AM, sent Friday 8:00 AM: the old "24 hours before".
        "draft_day": 4, "draft_day_name": "Thursday", "draft_hour": 8,
        "day": 5, "day_name": "Friday", "hour": 8, "timezone": "America/Denver",
        "confirmed": False, "outside_working_hours": False,
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

    assert (body["day"], body["day_name"], body["hour"], body["timezone"],
            body["confirmed"]) == (4, "Thursday", 14, "America/Chicago", True)
    event = AuditEvent.all_objects.get(tenant=seeded_tenant, verb="digest_schedule.changed")
    assert event.payload == {
        "from": {"draft_day": 4, "draft_hour": 8, "day": 5, "hour": 8,
                 "timezone": "America/Denver"},
        "to": {"draft_day": 4, "draft_hour": 8, "day": 4, "hour": 14,
               "timezone": "America/Chicago"},
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


# ------------------------------------------- Draft on and Send on (phase 1)

MOUNTAIN = ZoneInfo("America/Denver")


def at(*parts):
    return datetime(*parts, tzinfo=MOUNTAIN)


def set_times(tenant, draft, send):
    tenant.digest_draft_day, tenant.digest_draft_hour = draft
    tenant.digest_send_day, tenant.digest_send_hour = send
    tenant.save()


@pytest.mark.django_db
def test_the_default_drafts_exactly_when_the_fixed_24_hours_did(seeded_tenant):
    """Thursday 8:00 AM for a Friday 8:00 AM send, to the minute, in weeks on
    both sides of a daylight-saving change."""
    from datetime import timedelta

    for moment in (at(2027, 3, 10, 12), at(2027, 3, 13, 12), at(2027, 3, 16, 12),
                   at(2027, 10, 30, 12), at(2027, 11, 3, 12), at(2027, 11, 9, 12)):
        send = digests.next_window(seeded_tenant, Cadence.WEEKLY, after=moment)
        assert digests.draft_before(seeded_tenant, send) == send - timedelta(hours=24)


@pytest.mark.django_db
def test_friday_afternoon_draft_for_a_monday_morning_send(seeded_tenant):
    """Bryan's schedule: work finished by Friday 3:00 PM, sent Monday 8:00 AM."""
    set_times(seeded_tenant, draft=(5, 15), send=(1, 8))

    send = digests.next_window(seeded_tenant, Cadence.WEEKLY, after=at(2026, 10, 7, 12))
    draft = digests.draft_before(seeded_tenant, send)
    start, end = digests.period_for(seeded_tenant, Cadence.WEEKLY, send)

    assert send == at(2026, 10, 12, 8) and draft == at(2026, 10, 9, 15)
    # The week of work it covers ends at the draft time.
    assert (start, end) == (at(2026, 10, 2, 15), at(2026, 10, 9, 15))


@pytest.mark.django_db
def test_nothing_is_drafted_before_draft_on_and_it_is_from_then_on(seeded_tenant):
    set_times(seeded_tenant, draft=(5, 15), send=(1, 8))
    with tenant_context(seeded_tenant.pk):
        early = digests.generate_scheduled(seeded_tenant, cadence=Cadence.WEEKLY,
                                           now=at(2026, 10, 9, 14, 59))
        assert early == []
    send = digests.next_window(seeded_tenant, Cadence.WEEKLY, after=at(2026, 10, 9, 15, 1))
    assert at(2026, 10, 9, 15, 1) >= digests.draft_before(seeded_tenant, send)


@pytest.mark.django_db
def test_the_monthly_digest_drafts_on_the_draft_on_before_the_first_send_on(seeded_tenant):
    """Including when that Friday is in the previous month."""
    set_times(seeded_tenant, draft=(5, 15), send=(1, 8))

    send = digests.next_window(seeded_tenant, Cadence.MONTHLY, after=at(2027, 1, 20, 12))

    assert send == at(2027, 2, 1, 8)                       # the first Monday of February
    assert digests.draft_before(seeded_tenant, send) == at(2027, 1, 29, 15)   # a January Friday


@pytest.mark.django_db
def test_the_owner_sets_draft_on_and_send_on_together(seeded_tenant, ff, api):
    body = patch(api.as_(ff), {"draft_day": 5, "draft_hour": 15, "day": 1, "hour": 8}).json()

    assert (body["draft_day"], body["draft_day_name"], body["draft_hour"]) == (5, "Friday", 15)
    assert (body["day"], body["day_name"], body["hour"]) == (1, "Monday", 8)
    assert body["outside_working_hours"] is False        # Friday 3 to 5 PM is in hours
    seeded_tenant.refresh_from_db()
    assert (seeded_tenant.digest_draft_day, seeded_tenant.digest_draft_hour) == (5, 15)
    # The cycle it describes: a Friday 3:00 PM draft and the Monday after.
    draft = datetime.fromisoformat(body["next_draft_at"]).astimezone(MOUNTAIN)
    send = datetime.fromisoformat(body["next_send_at"]).astimezone(MOUNTAIN)
    assert (draft.isoweekday(), draft.hour, send.isoweekday(), send.hour) == (5, 15, 1, 8)
    assert 0 < (send - draft).days < 7


@pytest.mark.django_db
@pytest.mark.parametrize("draft,send,outside", [
    ((4, 8), (5, 8), False),     # the default
    ((5, 15), (1, 8), False),    # Friday afternoon to Monday morning
    ((7, 8), (1, 8), True),      # Sunday to Monday 8 AM: what 24 hours gave a Monday send
    ((5, 17), (1, 9), True),     # Friday 5 PM to Monday 9 AM: the whole weekend
    ((5, 17), (1, 10), False),   # ...but an hour of Monday morning counts
    ((6, 9), (7, 17), True),     # Saturday to Sunday
])
def test_the_working_hours_warning(draft, send, outside, seeded_tenant, ff, api):
    assert digests.outside_working_hours(*draft, *send) is outside
    body = patch(api.as_(ff), {"draft_day": draft[0], "draft_hour": draft[1],
                               "day": send[0], "hour": send[1]}).json()
    # A warning, never a refusal.
    assert body["outside_working_hours"] is outside


@pytest.mark.django_db
@pytest.mark.parametrize("bad", [
    {"draft_day": 5, "draft_hour": 8},                        # the same day and time
    {"draft_day": 5, "draft_hour": 7},                        # one hour before
    {"draft_day": 0}, {"draft_day": 8}, {"draft_hour": 24}, {"draft_hour": "3 PM"},
    {"draft_day": True},
])
def test_a_draft_time_that_leaves_no_time_to_approve_is_refused(bad, seeded_tenant, ff, api):
    response = patch(api.as_(ff), bad)

    assert response.status_code == 400
    seeded_tenant.refresh_from_db()
    assert (seeded_tenant.digest_draft_day, seeded_tenant.digest_draft_hour,
            seeded_tenant.digest_send_day, seeded_tenant.digest_send_hour) == (4, 8, 5, 8)


@pytest.mark.django_db
def test_two_hours_before_is_enough(seeded_tenant, ff, api):
    assert patch(api.as_(ff), {"draft_day": 5, "draft_hour": 6}).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["CF", "VA", "FCC", "ECC"])
def test_nobody_but_the_owner_moves_draft_on(role, seeded_tenant, api):
    assert patch(api.as_(member(seeded_tenant, role)), {"draft_day": 3}).status_code == 403
    seeded_tenant.refresh_from_db()
    assert seeded_tenant.digest_draft_day == 4


@pytest.mark.django_db
def test_draft_on_in_one_practice_never_moves_anothers(tenant_a, tenant_b, api):
    patch(api.as_(MembershipFactory(tenant=tenant_a, role="FF")),
          {"draft_day": 5, "draft_hour": 15, "day": 1, "hour": 8})
    tenant_b.refresh_from_db()
    assert (tenant_b.digest_draft_day, tenant_b.digest_draft_hour) == (4, 8)


@pytest.mark.django_db
def test_the_carry_over_gives_each_practice_the_day_before_at_the_same_hour(seeded_tenant):
    """The migration's data step, run as SQL against practices as they were:
    a Friday, a Monday (Bryan's, which wraps to Sunday) and an odd hour."""
    from pathlib import Path

    from django.conf import settings
    from django.db import connection

    monday = TenantFactory(digest_send_day=1, digest_send_hour=8)
    wednesday = TenantFactory(digest_send_day=3, digest_send_hour=15)
    source = Path(settings.BASE_DIR,
                  "apps/tenancy/migrations/0011_digest_draft_day_and_hour.py").read_text()
    statement = source[source.index('UPDATE "tenant"'):source.index('";\n"""') + 2]

    with connection.cursor() as cursor:
        cursor.execute(statement)

    for tenant, expected in ((seeded_tenant, (4, 8, 5, 8)), (monday, (7, 8, 1, 8)),
                             (wednesday, (2, 15, 3, 15))):
        tenant.refresh_from_db()
        assert (tenant.digest_draft_day, tenant.digest_draft_hour,
                tenant.digest_send_day, tenant.digest_send_hour) == expected
        # ...which is exactly the old behavior: drafted 24 hours before sending.
        assert digests.draft_gap_hours(*expected) == 24


@pytest.mark.django_db
def test_an_old_keep_it_is_asked_again_once_in_the_new_wording(seeded_tenant, ff, api):
    """D11. A "Keep it" from before Draft on existed does not answer the new
    question; one given now does, and so does ever having changed it."""
    AuditEvent.all_objects.create(
        tenant=seeded_tenant, actor=ff.user, verb="digest_schedule.confirmed",
        target_type="tenant", target_id=seeded_tenant.pk,
        payload={"day": 5, "hour": 8, "timezone": "America/Denver"})
    assert api.as_(ff).get(URL).json()["confirmed"] is False

    assert api.as_(ff).post(CONFIRM).json()["confirmed"] is True
    assert api.as_(ff).get(URL).json()["confirmed"] is True


@pytest.mark.django_db
def test_holding_digests_is_still_not_a_setting(seeded_tenant, ff, api):
    assert patch(api.as_(ff), {"draft_day": 5, "hold_all_digests": False}).status_code == 400
    seeded_tenant.refresh_from_db()
    assert seeded_tenant.hold_all_digests is True and seeded_tenant.digest_draft_day == 4
