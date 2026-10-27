"""A reading the meeting's notes state, proposed for a KPI (owner, 2026-10-27).

- **Proposed only when nothing is guessed:** one KPI by name (narrowed to the
  meeting's companies), never per-person or computed, the KPI's own period
  from the meeting's date, a value the KPI takes.
- **The audience rules:** someone who could not see the KPI on its scorecard
  is not shown the item at all; only someone who may enter the reading can
  confirm it; a client reaches none of the queue.
- **Confirming enters it** through the scorecard's own entry, as the person,
  with a corrected value if they give one, keeping an earlier value in the
  reading's history.
- **Isolation:** another practice's KPI is never matched or entered.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.meetings import measures, parsing
from apps.meetings.models import MeetingSourceFile, ProposalItem
from apps.scorecard import periods as P
from apps.scorecard import setup
from apps.scorecard.models import KpiReading, KpiReadingChange
from apps.tenancy.context import tenant_context

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import (
    ClientAssignmentFactory, ClientCompanyFactory, MeetingSourceFileFactory, TenantFactory,
)

pytestmark = pytest.mark.django_db
MEETING = date(2026, 10, 21)                      # a Wednesday
LAST_WEEK = date(2026, 10, 12)


def post(client, url, data=None):
    return client.post(url, json.dumps(data or {}), content_type="application/json")


@pytest.fixture
def world(seeded_tenant, ff):
    t = seeded_tenant
    with tenant_context(t.pk):
        acme = ClientCompanyFactory(tenant=t, name="Acme Fasteners")
        other = ClientCompanyFactory(tenant=t, name="Globex Logistics")
        card = setup.ensure(acme, ff.user)
        page = card.pages.get()

        def kpi(card, page, name, **extra):
            return setup.create_kpi(card, {"name": name, "kind": "percent", "cadence": "weekly",
                                           "rollup": "average", "target_value": 3,
                                           "page": str(page.pk), **extra}, ff.user)

        scrap = kpi(card, page, "Scrap rate", reading_owner=str(ff.user.pk))
        monthly = kpi(card, page, "Occupancy", cadence="monthly")
        other_card = setup.ensure(other, ff.user)
        other_scrap = kpi(other_card, other_card.pages.get(), "Scrap rate")
    return {"t": t, "acme": acme, "other": other, "scrap": scrap, "monthly": monthly,
            "other_scrap": other_scrap, "ff": ff}


def stated(measure="scrap", value="3.1%", kind="week", which="last", day=None):
    return {"measure": measure, "value": value,
            "period": {"kind": kind, "which": which, "date": day},
            "excerpt": f"{measure} was {value} {which} {kind}."}


def build(world, measurements, *, owner_email="bryan@getexecutivesnow.test", company="Acme"):
    with tenant_context(world["t"].pk):
        source = MeetingSourceFileFactory(tenant=world["t"], drive_file_owner_email=owner_email,
                                          state=MeetingSourceFile.State.PARSING)
        return parsing._build(source, {
            "title": "Weekly review", "meeting_date": MEETING.isoformat(), "summary": "",
            "participants": [{"name": "Wiley Coyote", "email": "wiley@acme.invalid",
                              "company": company, "excerpt": "Attendees: Wiley"}],
            "action_items": [], "measurements": measurements}, None)


def readings_of(proposal):
    return list(ProposalItem.all_objects.filter(proposal=proposal, kind="reading"))


# ------------------------------------------------------------ what is proposed

def test_a_stated_value_becomes_a_reading_for_last_week(world):
    [item] = readings_of(build(world, [stated()]))
    assert item.state == "pending" and item.source_excerpt == "scrap was 3.1% last week."
    assert item.payload["kpi_id"] == str(world["scrap"].pk)
    assert item.payload["period_start"] == LAST_WEEK.isoformat()
    assert (item.payload["value"], item.payload["value_label"]) == ("3.1000", "3.1%")
    assert item.payload["company_name"] == "Acme Fasteners"


def test_a_name_two_companies_hold_is_narrowed_to_the_meetings_company(world):
    [item] = readings_of(build(world, [stated()], company="Acme Fasteners"))
    assert item.payload["kpi_id"] == str(world["scrap"].pk)
    # Nobody at either company in the room: two KPIs answer, so nothing is guessed.
    assert readings_of(build(world, [stated()], company="")) == []


@pytest.mark.parametrize("raw", [
    stated(kind="month"),                          # a weekly KPI named by its month
    stated(which="", kind="week"),                 # no period said
    stated(value="about a third"),                 # not a value it takes
    stated(measure="headcount"),                   # no KPI by that name
    stated(which="date", day="2026-11-02"),        # a week after the meeting
])
def test_anything_doubtful_is_dropped_not_proposed(world, raw):
    assert readings_of(build(world, [raw])) == []


def test_a_monthly_kpi_takes_a_month_named_by_date(world):
    [item] = readings_of(build(world, [stated("occupancy", "78%", "month", "date",
                                              "2026-09-15")]))
    assert item.payload["period_start"] == "2026-09-01"
    assert item.payload["period_label"] == P.long_label(date(2026, 9, 1), "monthly")


def test_never_a_per_person_or_computed_kpi(world):
    with tenant_context(world["t"].pk):
        card = world["scrap"].scorecard
        page = card.pages.get()
        setup.create_kpi(card, {"name": "Calls made", "kind": "count", "cadence": "weekly",
                                "rollup": "sum", "page": str(page.pk), "per_person": True,
                                "people": []}, world["ff"].user)
    assert readings_of(build(world, [stated("calls made", "40")])) == []


def test_another_practices_kpi_is_never_matched(world):
    other = TenantFactory()
    ff_b = _member(other, "FF")
    with tenant_context(other.pk):
        company = ClientCompanyFactory(tenant=other, name="Acme Fasteners")
        card = setup.ensure(company, ff_b.user)
        setup.create_kpi(card, {"name": "Throughput", "kind": "count", "cadence": "weekly",
                                "rollup": "sum", "page": str(card.pages.get().pk)}, ff_b.user)
    assert readings_of(build(world, [stated("throughput", "40")])) == []


def test_names_match_by_their_words():
    assert measures.names_match("scrap", "Scrap rate")
    assert measures.names_match("on-time deliveries", "On-time delivery %")
    assert not measures.names_match("scrap", "Revenue")
    assert not measures.names_match("rate", "Scrap rate")       # filler alone names nothing


# ------------------------------------------------------- the audience rules

def items(api, who, proposal):
    response = api.as_(who).get(f"/api/proposal-items/?proposal={proposal.pk}")
    assert response.status_code == 200, response.content
    return [i for i in response.json() if i["kind"] == "reading"]


def test_an_associate_not_on_the_company_is_not_shown_it(world, api):
    cf = _member(world["t"], "CF")
    proposal = build(world, [stated()], owner_email=cf.user.email)   # their own meeting
    assert items(api, cf, proposal) == []
    detail = api.as_(cf).get(f"/api/meeting-proposals/{proposal.pk}/").json()
    assert not [i for i in detail["items"] if i["kind"] == "reading"]
    [hidden] = readings_of(proposal)
    assert post(api.as_(cf), f"/api/proposal-items/{hidden.pk}/approve/").status_code == 404

    ClientAssignmentFactory(tenant=world["t"], user=cf.user, company=world["acme"])
    [shown] = items(api, cf, proposal)
    assert shown["reading"] == {"may_enter": True, "current_label": ""}


def test_an_assistant_sees_it_and_confirms_only_what_they_own(world, api, va):
    proposal = build(world, [stated()])
    [row] = items(api, va, proposal)
    assert row["reading"]["may_enter"] is False
    refused = post(api.as_(va), f"/api/proposal-items/{row['id']}/approve/")
    assert refused.status_code == 403 and "can't enter readings" in refused.json()["detail"]
    with tenant_context(world["t"].pk):
        world["scrap"].reading_owner = va.user
        world["scrap"].save(update_fields=["reading_owner"])
    assert items(api, va, proposal)[0]["reading"]["may_enter"] is True
    assert post(api.as_(va), f"/api/proposal-items/{row['id']}/approve/").status_code == 201


def test_a_client_reaches_none_of_it(world, api, fcc):
    proposal = build(world, [stated()])
    [item] = readings_of(proposal)
    assert api.as_(fcc).get(f"/api/proposal-items/?proposal={proposal.pk}").status_code in (
        403, 404)
    assert post(api.as_(fcc), f"/api/proposal-items/{item.pk}/approve/").status_code in (
        403, 404)
    assert not KpiReading.all_objects.exists()


# ------------------------------------------------------------ confirming it

def test_confirming_enters_it_through_the_scorecard_as_the_person(world, api):
    proposal = build(world, [stated()])
    [item] = readings_of(proposal)
    made = post(api.as_(world["ff"]), f"/api/proposal-items/{item.pk}/approve/")
    assert made.status_code == 201, made.content
    reading = KpiReading.all_objects.get(kpi=world["scrap"], period_start=LAST_WEEK)
    assert str(reading.value) == "3.1000" and reading.entered_by == world["ff"].user
    item.refresh_from_db()
    assert (item.state, item.created_record_type, item.created_record_id) == (
        "approved", "kpi_reading", reading.pk)


def test_a_corrected_value_wins_and_an_earlier_one_stays_in_history(world, api):
    with tenant_context(world["t"].pk):
        held = KpiReading.all_objects.create(tenant=world["t"], kpi=world["scrap"],
                                         period_start=LAST_WEEK, value=4,
                                         entered_by=world["ff"].user,
                                         entered_at=timezone.now())
    proposal = build(world, [stated()])
    [row] = items(api, world["ff"], proposal)
    assert row["reading"]["current_label"] == "4%"
    post(api.as_(world["ff"]), f"/api/proposal-items/{row['id']}/approve/", {"value": "3.2"})
    held.refresh_from_db()
    assert str(held.value) == "3.2000"
    assert KpiReadingChange.all_objects.filter(reading=held, previous_value=4).exists()


def test_a_value_it_does_not_take_is_refused_and_nothing_entered(world, api):
    proposal = build(world, [stated()])
    [item] = readings_of(proposal)
    refused = post(api.as_(world["ff"]), f"/api/proposal-items/{item.pk}/approve/",
                   {"value": "lots"})
    assert refused.status_code == 400 and "isn't a number" in refused.json()["detail"]
    assert not KpiReading.all_objects.exists()
    item.refresh_from_db()
    assert item.state == "pending"


def test_not_a_reading_rejects_it_and_the_proposal_settles(world, api):
    proposal = build(world, [stated()])
    [item] = readings_of(proposal)
    post(api.as_(world["ff"]), f"/api/proposal-items/{item.pk}/reject/")
    item.refresh_from_db()
    assert item.state == "rejected" and not KpiReading.all_objects.exists()


def test_an_archived_kpi_cannot_be_confirmed(world, api):
    proposal = build(world, [stated()])
    [item] = readings_of(proposal)
    with tenant_context(world["t"].pk):
        world["scrap"].archived_at = timezone.now()
        world["scrap"].save(update_fields=["archived_at"])
    assert post(api.as_(world["ff"]),
                f"/api/proposal-items/{item.pk}/approve/").status_code in (404, 409)
    assert not KpiReading.all_objects.exists()


def test_the_prompt_asks_for_stated_numbers_only():
    assert '"measurements"' in parsing.SYSTEM
    assert "never one you work out" in parsing.SYSTEM
    assert P.start_of(MEETING, "weekly") - timedelta(days=7) == LAST_WEEK
