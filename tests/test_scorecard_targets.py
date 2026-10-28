"""Live targets, computed operands and helper KPIs (`apps/scorecard/refs.py`).

What is proven here, each through the code the worker and the API run:

- a live target from **another KPI's latest reading**, from a **column** and
  from a **cell** of the KPI's own sheet feed, and from a **field** of its
  Track and of its HubSpot feed: its value now is on the tile and in
  Details, each period is judged against the value it had then, and the
  Progress tile reads "102 of 108";
- a computed KPI takes either operand from a KPI, the KPI's own target, or
  a number its feed reads ("Contacts Completed ÷ its target", no middle
  KPI), and the setup refuses what can't be;
- a helper KPI is never drawn as a tile, but is entered and feeds a target;
- **isolation**: a target or an operand is taken only from the same
  scorecard, never another company's or another practice's, and a reader
  who can't see the KPI a target comes from is not shown the target.
"""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from unittest import mock

import pytest
from django.utils import timezone

from apps.crm.services.gmail_oauth import SHEETS_SCOPES, TIER1_SCOPES
from apps.scorecard import feeds, hubspot, readings, refs, setup, sheets, track
from apps.scorecard import periods as P
from apps.scorecard.models import (Kpi, KpiFeed, KpiFeedValue, KpiHubSpotFeed, KpiReading,
                                   KpiTrackFeed)
from apps.tenancy.context import tenant_context

from . import registry_config  # noqa: F401
from .factories import (ClientCompanyFactory, GmailConnectionFactory, MembershipFactory,
                        TenantFactory)

B = "/api/scorecard/"
SHEET_ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcd"


class FakeSheets:
    books: dict = {}

    def __init__(self, connection):
        self.connection = connection

    def rows(self, spreadsheet_id, tab, **_):
        return [list(r) for r in FakeSheets.books.get((spreadsheet_id, tab), [])]


@pytest.fixture(autouse=True)
def fake_google(monkeypatch):
    FakeSheets.books = {}
    monkeypatch.setattr(sheets, "SheetsClient", FakeSheets)


def week(n):
    """The start of the week `n` weeks before this one."""
    return P.start_of(timezone.localdate(), P.WEEKLY) - timedelta(weeks=n)


def homeowners(contacts, total, attempted=None):
    """The homeowner contacts sheet: a row a week, contacts so far and the
    total homeowners to reach (which grows as homeowners sign up)."""
    rows = [["Week of", "Contacts Completed", "Total Homeowners", "Contacts Attempted"]]
    for n, (done, of) in enumerate(zip(contacts, total)):
        start = week(len(contacts) - 1 - n)
        rows.append([start.isoformat(), str(done), str(of),
                     str(attempted[n]) if attempted else ""])
    return rows


@pytest.fixture
def card(seeded_tenant, ff, api):
    tenant = seeded_tenant
    company = ClientCompanyFactory(tenant=tenant, name="Hooli Field Services", seat_count=10)
    owner = MembershipFactory(tenant=tenant, role="FCC", client_company=company)
    member = MembershipFactory(tenant=tenant, role="ECC", client_company=company)
    GmailConnectionFactory(tenant=tenant, user=ff.user, scopes=TIER1_SCOPES + SHEETS_SCOPES)
    with tenant_context(tenant.pk):
        sc = setup.ensure(company, ff.user)
        page = sc.pages.get()
        leaders = setup.create_page(sc, {"name": "Leaders", "audience": "leadership"}, ff.user)
    return {"tenant": tenant, "company": company, "owner": owner, "member": member, "ff": ff,
            "api": api, "card": sc, "page": page, "leaders": leaders}


def make(c, **fields):
    with tenant_context(c["tenant"].pk):
        return setup.create_kpi(c["card"], {"kind": "count", "cadence": "weekly",
                                            "rollup": "last", "page": str(c["page"].pk),
                                            **fields}, c["ff"].user)


def sheet_feed(c, kpi, **extra):
    config = {"spreadsheet_id": SHEET_ID, "spreadsheet_name": "Homeowner contacts",
              "tab": "Data", "mode": "column", "date_column": "A", "date_header": "Week of",
              "value_column": "B", "value_header": "Contacts Completed", "header_row": 0,
              **extra}
    feed = KpiFeed.all_objects.create(tenant=c["tenant"], kpi=kpi, **config)
    Kpi.all_objects.filter(pk=kpi.pk).update(feed=Kpi.Feed.SHEET)
    return feed


def tile_of(c, name, who=None, window="this_week"):
    client = c["api"].as_(who or c["ff"])
    data = client.get(f"{B}?company={c['company'].pk}&window={window}").json()
    return next((t for t in data["kpis"] if t["name"] == name), None), data


def read(kpi):
    return {r.period_start: r.value for r in KpiReading.all_objects.filter(kpi=kpi)}


def post(client, url, data):
    return client.post(url, json.dumps(data), content_type="application/json")


def patch(client, url, data):
    return client.patch(url, json.dumps(data), content_type="application/json")


# ---------------------------------------------------------------- from a sheet column

def test_a_live_target_from_the_sheets_column_and_the_progress_tile(card):
    c = card
    contacts = make(c, name="Contacts Completed", tile="progress",
                    target_live={"kind": "sheet_column", "header": "Total Homeowners"})
    feed = sheet_feed(c, contacts)
    FakeSheets.books[(SHEET_ID, "Data")] = homeowners([60, 81, 95, 102], [104, 104, 108, 108])
    assert feeds.run(feed, timezone.localdate())["ok"]
    key = refs.target_key(contacts)
    assert {v.period_start: v.value for v in KpiFeedValue.all_objects.filter(kpi=contacts,
                                                                             key=key)} == {
        week(3): Decimal("104"), week(2): Decimal("104"), week(1): Decimal("108"),
        week(0): Decimal("108")}

    tile, _ = tile_of(c, "Contacts Completed")
    # The front: "102 of 108", judged against 108; Details: the target now and its source.
    assert tile["shape"] == "progress"
    assert tile["summary"]["value"] == 102 and tile["summary"]["full_target"] == 108
    assert tile["summary"]["status"] == "behind"                 # 102 is within 10% of 108
    assert tile["target_live"] == {"text": "the sheet's Total Homeowners column", "value": 108}
    # Each week is judged against the total it had then.
    targets = {p["period_start"]: p["target"] for p in tile["history"]}
    assert targets[week(3).isoformat()] == 104 and targets[week(0).isoformat()] == 108

    # A typed target is not used while the target is live.
    with tenant_context(c["tenant"].pk):
        setup.update_kpi(contacts, {"target_value": "5"}, c["ff"].user)
    assert tile_of(c, "Contacts Completed")[0]["summary"]["full_target"] == 108

    # The column renamed: the read fails in words, and the last target stands.
    FakeSheets.books[(SHEET_ID, "Data")][0][2] = "Homeowners"
    result = feeds.run(feed, timezone.localdate())
    assert result["ok"] is False and "Total Homeowners" in result["error"]
    assert tile_of(c, "Contacts Completed")[0]["target_live"]["value"] == 108


def test_a_target_column_named_by_its_letter(card):
    c = card
    contacts = make(c, name="Contacts Completed",
                    target_live={"kind": "sheet_column", "column": "C"})
    feed = sheet_feed(c, contacts)
    FakeSheets.books[(SHEET_ID, "Data")] = homeowners([50, 70], [90, 100])
    feeds.run(feed, timezone.localdate())
    tile, _ = tile_of(c, "Contacts Completed")
    assert tile["target_live"] == {"text": "column C of the sheet", "value": 100}


# ---------------------------------------------------------------- from a sheet cell

def test_a_live_target_from_a_cell_of_the_sheet(card):
    c = card
    contacts = make(c, name="Contacts Completed",
                    target_live={"kind": "sheet_cell", "cell": "C2"})
    feed = sheet_feed(c, contacts, mode="cell", cell="B2", date_column="", date_header="",
                      value_column="", value_header="", header_row=None,
                      cell_from=week(0))
    FakeSheets.books[(SHEET_ID, "Data")] = [["", "Done", "Of"], ["", "40", "108"]]
    feeds.run(feed, timezone.localdate())
    assert tile_of(c, "Contacts Completed")[0]["target_live"]["value"] == 108
    # Next week: the cell's new number is the open week's; the closed week keeps its own.
    FakeSheets.books[(SHEET_ID, "Data")] = [["", "Done", "Of"], ["", "45", "120"]]
    feeds.run(feed, week(0) + timedelta(days=7))
    values = {v.period_start: v.value for v in KpiFeedValue.all_objects.filter(kpi=contacts)}
    assert values[week(0)] == Decimal("108") and values[week(-1)] == Decimal("120")


# ---------------------------------------------------------------- from Track and HubSpot

def test_a_live_target_from_a_field_of_the_track_feed(card):
    c = card
    nights = make(c, name="Nights booked", rollup="sum",
                  target_live={"kind": "track", "measure": "nights_booked"})
    occupancy = make(c, name="Occupancy", kind="percent", rollup="average",
                     target_live={"kind": "track", "measure": "occupancy"})
    feed = KpiTrackFeed.all_objects.create(tenant=c["tenant"], kpi=nights, measure="revenue")

    def value_for(measure, client, first, last, **_):
        return {"revenue": Decimal(9000), "nights_booked": Decimal(120)}[measure]

    with mock.patch.object(track, "value_for", side_effect=value_for):
        assert feeds.run_track(feed, timezone.localdate(), client=object())["ok"]
    tile, _ = tile_of(c, "Nights booked")
    assert tile["target_live"] == {"text": "Track: Nights booked", "value": 120}
    # Another KPI's Track field is its own feed's alone: Occupancy has none yet.
    assert tile_of(c, "Occupancy")[0]["target_live"]["value"] is None
    # A Track field named of a KPI fed from a sheet is refused in words.
    sheet_feed(c, occupancy)
    refused = patch(c["api"].as_(c["ff"]), f"{B}kpis/{occupancy.pk}/", {
        "target_live": {"kind": "track", "measure": "occupancy"}})
    assert refused.status_code == 400
    assert refused.json()["field"] == "target_live"
    assert "reads from a Google Sheet" in refused.json()["detail"]


def test_a_live_target_from_a_field_of_the_hubspot_feed(card):
    c = card
    won = make(c, name="Deals won", rollup="sum",
               target_live={"kind": "hubspot", "measure": "deals_created"})
    feed = KpiHubSpotFeed.all_objects.create(tenant=c["tenant"], kpi=won, measure="deals_won")

    def value_for(measure, client, first, last, **_):
        return {"deals_won": Decimal(4), "deals_created": Decimal(10)}[measure]

    with mock.patch.object(hubspot, "value_for", side_effect=value_for):
        assert feeds.run_hubspot(feed, timezone.localdate(), client=object())["ok"]
    tile, _ = tile_of(c, "Deals won")
    assert tile["target_live"] == {"text": "HubSpot: Deals created", "value": 10}
    assert tile["summary"]["target"] is not None


# ---------------------------------------------------------------- from another KPI

def test_a_live_target_from_another_kpis_latest_reading_and_a_helper(card):
    c = card
    goal = make(c, name="Calls goal", helper=True, reading_owner=str(c["owner"].user_id))
    calls = make(c, name="Calls", rollup="sum", target_live={"kind": "kpi", "kpi": str(goal.pk)})
    with tenant_context(c["tenant"].pk):
        for n, value in ((2, 40), (0, 50)):
            KpiReading.objects.create(tenant=c["tenant"], kpi=goal, period_start=week(n),
                                      value=value, entered_at=timezone.now())
        for n, value in ((2, 41), (1, 39), (0, 44)):
            KpiReading.objects.create(tenant=c["tenant"], kpi=calls, period_start=week(n),
                                      value=value, entered_at=timezone.now())
    tile, data = tile_of(c, "Calls")
    assert tile["target_live"] == {"text": "Calls goal's latest reading", "value": 50}
    targets = {p["period_start"]: p["target"] for p in tile["history"]}
    # Last week took the goal's latest then (40); this week, the new one (50).
    assert targets[week(1).isoformat()] == 40 and targets[week(0).isoformat()] == 50
    statuses = {p["period_start"]: p["status"] for p in tile["history"]}
    assert statuses[week(2).isoformat()] == "on_track"           # 41 against 40
    assert statuses[week(0).isoformat()] == "off_track"          # 44 against 50: 12% short
    # The helper is never drawn, for anyone, yet is still entered.
    assert "Calls goal" not in [t["name"] for t in data["kpis"]]
    assert tile_of(c, "Calls goal", who=c["owner"])[0] is None
    with tenant_context(c["tenant"].pk):
        from tests.test_scorecard_feeds import _reader

        form = readings.form(_reader({"tenant": c["tenant"], "company": c["company"]},
                                     c["owner"]), c["card"], timezone.localdate(),
                             timezone.localdate())
    assert "Calls goal" in [k["name"] for k in form["kpis"]]


def test_a_target_from_a_kpi_the_reader_cant_see_is_no_target_for_them(card):
    c = card
    secret = make(c, name="Margin goal", page=str(c["leaders"].pk))
    shown = make(c, name="Margin", target_live={"kind": "kpi", "kpi": str(secret.pk)})
    with tenant_context(c["tenant"].pk):
        KpiReading.objects.create(tenant=c["tenant"], kpi=secret, period_start=week(0),
                                  value=777, entered_at=timezone.now())
        KpiReading.objects.create(tenant=c["tenant"], kpi=shown, period_start=week(0),
                                  value=700, entered_at=timezone.now())
    assert tile_of(c, "Margin")[0]["target_live"]["value"] == 777
    seen, _ = tile_of(c, "Margin", who=c["member"])
    assert seen["target_live"]["value"] is None
    assert seen["summary"]["target"] is None and seen["summary"]["status"] is None
    assert "777" not in json.dumps(seen)


# ---------------------------------------------------------------- computed operands

def test_contacts_completed_over_its_own_target_needs_no_middle_kpi(card):
    c = card
    contacts = make(c, name="Contacts Completed", tile="progress",
                    target_live={"kind": "sheet_column", "header": "Total Homeowners"})
    share = make(c, name="Homeowners reached", kind="percent", rollup="last", formula="ratio",
                 source_a=str(contacts.pk), source_b=str(contacts.pk),
                 operand_b={"kind": "target"}, target_value=90)
    rate = make(c, name="Completion rate", kind="percent", rollup="last", formula="ratio",
                source_a=str(contacts.pk), source_b=str(contacts.pk),
                operand_b={"kind": "sheet_column", "header": "Contacts Attempted"})
    feed = sheet_feed(c, contacts)
    FakeSheets.books[(SHEET_ID, "Data")] = homeowners([81, 102], [104, 108], [90, 120])
    assert feeds.run(feed, timezone.localdate())["ok"]
    tile, data = tile_of(c, "Homeowners reached")
    assert tile["computed"] == "Contacts Completed ÷ Contacts Completed's target"
    assert tile["summary"]["value"] == pytest.approx(94.4444, abs=0.001)    # 102 ÷ 108
    assert {p["period_start"]: round(p["value"], 2) for p in tile["history"]
            if p["value"] is not None} == {week(1).isoformat(): 77.88,
                                           week(0).isoformat(): 94.44}
    attempted = tile_of(c, "Completion rate")[0]
    assert attempted["computed"] == "Contacts Completed ÷ the sheet's Contacts Attempted column"
    assert attempted["summary"]["value"] == 85                               # 102 ÷ 120
    # The page has the two tiles and no middle one for the total.
    assert sorted(t["name"] for t in data["kpis"]) == [
        "Completion rate", "Contacts Completed", "Homeowners reached"]
    assert share.pk and rate.pk


def test_the_setup_refuses_operands_that_cannot_be(card):
    c = card
    ff = c["api"].as_(c["ff"])
    contacts = make(c, name="Contacts Completed")
    sheet_feed(c, contacts)
    base = {"company": str(c["company"].pk), "name": "Ratio", "kind": "number",
            "page": str(c["page"].pk), "formula": "ratio", "source_a": str(contacts.pk),
            "source_b": str(contacts.pk)}
    for extra, field, said in (
            ({}, "source_b", "two different numbers of one"),
            ({"operand_b": {"kind": "target"}, "operand_a": {"kind": "target"}}, "source_b",
             "two different"),
            ({"operand_b": {"kind": "track", "measure": "occupancy"}}, "operand_b",
             "reads from a Google Sheet"),
            ({"operand_b": {"kind": "sheet_cell", "cell": "B2"}}, "operand_b", "by column"),
            ({"operand_b": {"kind": "sheet_column"}}, "operand_b", "heading, or its letter"),
            ({"operand_b": {"kind": "elsewhere"}}, "operand_b", "its value, its target")):
        refused = post(ff, f"{B}kpis/", {**base, **extra})
        assert refused.status_code == 400, extra
        assert refused.json().get("field") == field and said in refused.json()["detail"], extra
    made = post(ff, f"{B}kpis/", {**base, "operand_b": {"kind": "target"}})
    assert made.status_code == 201, made.content


def test_the_setup_refuses_live_targets_that_cannot_be(card):
    c = card
    ff = c["api"].as_(c["ff"])
    per = make(c, name="Calls each", per_person=True)
    base = {"company": str(c["company"].pk), "name": "Thing", "kind": "count",
            "page": str(c["page"].pk)}
    for extra, said in (
            ({"target_live": {"kind": "kpi", "kpi": str(per.pk)}}, "per person"),
            ({"target_live": {"kind": "kpi", "kpi": "not-an-id"}}, "Choose a KPI"),
            ({"target_live": {"kind": "sheet_column", "header": "Total"}, "direction": "range",
              "range_low": 1, "range_high": 2}, "range"),
            ({"target_live": {"kind": "track", "measure": "nope"}}, "Choose a field")):
        refused = post(ff, f"{B}kpis/", {**base, **extra})
        assert refused.status_code == 400 and said in refused.json()["detail"], extra
    # Back to typed: the live target is cleared.
    kpi = make(c, name="Live", target_live={"kind": "sheet_column", "header": "Total"})
    assert patch(ff, f"{B}kpis/{kpi.pk}/", {"target_live": None,
                                            "target_value": "8"}).status_code == 200
    kpi.refresh_from_db()
    assert kpi.target_live is None and kpi.target_value == 8


# ---------------------------------------------------------------- isolation

def test_a_target_or_operand_never_comes_from_another_company_or_practice(card):
    c = card
    ff = c["api"].as_(c["ff"])
    # Another company of the same practice.
    other_company = ClientCompanyFactory(tenant=c["tenant"], name="Pied Piper", seat_count=3)
    with tenant_context(c["tenant"].pk):
        other_card = setup.ensure(other_company, c["ff"].user)
        theirs = setup.create_kpi(other_card, {"name": "Their goal", "kind": "count",
                                               "page": str(other_card.pages.get().pk)},
                                  c["ff"].user)
        KpiReading.objects.create(tenant=c["tenant"], kpi=theirs, period_start=week(0),
                                  value=999, entered_at=timezone.now())
    base = {"company": str(c["company"].pk), "name": "Mine", "kind": "count",
            "page": str(c["page"].pk)}
    refused = post(ff, f"{B}kpis/", {**base, "target_live": {"kind": "kpi",
                                                             "kpi": str(theirs.pk)}})
    assert refused.status_code == 400 and "this scorecard" in refused.json()["detail"]
    refused = post(ff, f"{B}kpis/", {**base, "formula": "ratio", "source_a": str(theirs.pk),
                                     "source_b": str(theirs.pk),
                                     "operand_b": {"kind": "target"}})
    assert refused.status_code == 400

    # Another practice's KPI and feed values, even written onto the row by hand,
    # are never read.
    other = TenantFactory()
    from apps.crm.seed import seed_tenant

    seed_tenant(other)
    their_ff = MembershipFactory(tenant=other, role="FF")
    away = ClientCompanyFactory(tenant=other, name="Elsewhere", seat_count=3)
    with tenant_context(other.pk):
        away_card = setup.ensure(away, their_ff.user)
        away_kpi = setup.create_kpi(away_card, {"name": "Away", "kind": "count",
                                                "page": str(away_card.pages.get().pk)},
                                    their_ff.user)
        KpiReading.objects.create(tenant=other, kpi=away_kpi, period_start=week(0),
                                  value=555, entered_at=timezone.now())
    mine = make(c, name="Mine")
    Kpi.all_objects.filter(pk=mine.pk).update(target_live={"kind": "kpi",
                                                           "kpi": str(away_kpi.pk)})
    KpiFeedValue.all_objects.create(tenant=other, kpi=away_kpi, key="column:total:last",
                                    period_start=week(0), value=444, read_at=timezone.now())
    tile, _ = tile_of(c, "Mine")
    assert tile["target_live"]["value"] is None
    assert "555" not in json.dumps(tile) and "444" not in json.dumps(tile)
    # And a client of this practice never reaches the other company's page through it.
    assert tile_of(c, "Their goal", who=c["owner"])[0] is None
