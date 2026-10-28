"""M5 part 3: the Google Sheet feed (spec "Feeds").

Against a fake Sheets client that serves grids of cell text, as the real
one returns them. What is proven here:

- a messy sheet (a title, headers in row 3, blank rows, a total row, text
  in number cells, dates as people type them) maps cleanly in column mode,
  and a dashboard sheet maps cleanly in cell mode;
- per-person rows match portal users by name, and the rest are listed;
- the hand wins, nothing is deleted, an open period waits for its close;
- a failed read keeps every reading and tells the reading owner once;
- **one practice's feed never reads through another practice's connection
  or reaches another practice's KPI**;
- only the practice owner and associates set a feed up;
- a grant from before the Sheets permission asks to reconnect, and the
  consent keeps what the connection already had.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.crm.services.gmail_oauth import DRIVE_SCOPES, SHEETS_SCOPES, TIER1_SCOPES
from apps.scorecard import feeds, readings, setup, sheets
from apps.scorecard import periods as P
from apps.scorecard.models import Kpi, KpiFeed, KpiReading
from apps.tenancy.context import tenant_context

from . import registry_config  # noqa: F401
from .factories import (ClientCompanyFactory, GmailConnectionFactory, MembershipFactory,
                        TenantFactory)

B = "/api/scorecard/feeds/"
SHEET_ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcd"
OTHER_ID = "1ZyXwVuTsRqPoNmLkJiHgFeDcBa9876543210zyxw"
GRANTED = TIER1_SCOPES + SHEETS_SCOPES


def post(client, url, data):
    return client.post(url, json.dumps(data), content_type="application/json")


def put(client, url, data):
    return client.put(url, json.dumps(data), content_type="application/json")


class FakeSheets:
    """Serves {(spreadsheet, tab): rows}; records every read with the
    connection it was made through."""

    calls: list = []

    def __init__(self, connection, books=None, *, refuse=None):
        self.connection = connection
        self.books = books if books is not None else FakeSheets.books
        self.refuse = refuse

    def spreadsheet(self, spreadsheet_id):
        FakeSheets.calls.append((self.connection.tenant_id, self.connection.pk, spreadsheet_id))
        tabs = sorted({tab for (sid, tab) in self.books if sid == spreadsheet_id})
        if not tabs:
            raise sheets.SheetUnavailable("That spreadsheet doesn't exist any more, or the "
                                          "address is wrong.")
        return {"title": "Weekly numbers", "tabs": [{"title": t, "id": i} for i, t in
                                                    enumerate(tabs)]}

    def rows(self, spreadsheet_id, tab, **_):
        FakeSheets.calls.append((self.connection.tenant_id, self.connection.pk, spreadsheet_id))
        if self.refuse:
            raise sheets.SheetUnavailable(self.refuse)
        return [list(r) for r in self.books.get((spreadsheet_id, tab), [])]


FakeSheets.books = {}


@pytest.fixture(autouse=True)
def fake_google(monkeypatch):
    FakeSheets.calls = []
    FakeSheets.books = {}
    monkeypatch.setattr(sheets, "SheetsClient", FakeSheets)
    return FakeSheets


def weeks_ago(n, week_start="monday"):
    today = timezone.localdate()
    return P.start_of(today, P.WEEKLY, week_start) - timedelta(weeks=n)


def us(day: date) -> str:
    return f"{day.month}/{day.day}/{day.year}"


def messy_weekly():
    """What a client's sheet looks like: a title, a note, headers in row 3,
    blank rows, a total, text in number cells, dates three ways, money."""
    w = [weeks_ago(n) for n in (4, 3, 2, 1, 0)]
    return [
        ["Northwind weekly numbers", "", "", ""],
        ["Updated by Olive every Monday", "", "", ""],
        ["Week of", "Occupancy", "Revenue", "Notes"],
        [us(w[0]), "81%", "$12,400.00", ""],
        ["", "", "", ""],
        [w[1].isoformat(), "79%", "$11,950", "slow week"],
        [f"{w[2]:%b} {w[2].day}, {w[2].year}", "n/a", "TBD", "PMS was down"],
        [us(w[3]), "84%", "(1,200)", "refund"],
        [us(w[4]), "88%", "$3,100", "this week so far"],
        ["", "", "", ""],
        ["Total", "", "$26,250", ""],
    ], w


@pytest.fixture
def practice(seeded_tenant, ff, api):
    tenant = seeded_tenant
    company = ClientCompanyFactory(tenant=tenant, name="Northwind Foods", seat_count=10)
    owner = MembershipFactory(tenant=tenant, role="FCC", client_company=company)
    owner.user.full_name = "Olive Owner"
    owner.user.save(update_fields=["full_name"])
    reps = {}
    for name in ("Mia Member", "Cole Colleague", "Sam Sales"):
        m = MembershipFactory(tenant=tenant, role="ECC", client_company=company)
        m.user.full_name = name
        m.user.save(update_fields=["full_name"])
        reps[name] = m
    connection = GmailConnectionFactory(tenant=tenant, user=ff.user, scopes=GRANTED,
                                        email_address="bryan@practice.example")
    with tenant_context(tenant.pk):
        card = setup.ensure(company, ff.user)
        page = card.pages.get()
        occupancy = setup.create_kpi(card, {
            "name": "Occupancy", "kind": "percent", "cadence": "weekly", "rollup": "average",
            "target_value": 82, "page": str(page.pk),
            "reading_owner": str(owner.user_id)}, ff.user)
        revenue = setup.create_kpi(card, {
            "name": "Revenue", "kind": "money", "cadence": "weekly", "rollup": "sum",
            "page": str(page.pk), "reading_owner": str(owner.user_id)}, ff.user)
        calls = setup.create_kpi(card, {
            "name": "Calls", "kind": "count", "cadence": "weekly", "rollup": "sum",
            "page": str(page.pk), "per_person": True,
            "reading_owner": str(owner.user_id),
            "people": [str(m.pk) for m in reps.values()]}, ff.user)
    return {"tenant": tenant, "company": company, "owner": owner, "reps": reps, "ff": ff,
            "api": api, "connection": connection, "card": card,
            "kpis": {"occupancy": occupancy, "revenue": revenue, "calls": calls}}


def mapping(p, kpi, **extra):
    return {"company": str(p["company"].pk), "kpi": str(kpi.pk),
            "spreadsheet": f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit#gid=0",
            "spreadsheet_name": "Weekly numbers", "tab": "Data", "mode": "column",
            "refresh": "hourly", **extra}


def readings_of(kpi, member=None):
    q = KpiReading.all_objects.filter(kpi=kpi)
    if member is not None:
        q = q.filter(membership=member)
    return {r.period_start: r for r in q}


# ---------------------------------------------------------------- the cells

def test_spreadsheet_addresses_cells_and_columns():
    assert sheets.spreadsheet_id_from(
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit?usp=sharing") == SHEET_ID
    assert sheets.spreadsheet_id_from(SHEET_ID) == SHEET_ID
    assert sheets.spreadsheet_id_from("https://drive.google.com/drive/folders/abc") == ""
    assert sheets.spreadsheet_id_from("not a sheet") == ""
    assert [sheets.column_letter(i) for i in (0, 25, 26, 27, 701)] == ["A", "Z", "AA", "AB", "ZZ"]
    assert sheets.column_index("AB") == 27
    assert sheets.parse_cell("$C$4") == (3, 2)
    with pytest.raises(sheets.FeedRefused):
        sheets.parse_cell("C0")


@pytest.mark.parametrize("text,expected", [
    ("10/19/2026", date(2026, 10, 19)), ("2026-10-19", date(2026, 10, 19)),
    ("Oct 19, 2026", date(2026, 10, 19)), ("October 19, 2026", date(2026, 10, 19)),
    ("Week of 10/19/2026", date(2026, 10, 19)), ("October 2026", date(2026, 10, 1)),
    ("Q4 2026", date(2026, 10, 1)), ("46314", date(2026, 10, 19)),
    ("Total", None), ("", None), ("82%", None), ("12", None),
])
def test_dates_as_people_type_them(text, expected):
    assert sheets.parse_date(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("1,234.50", Decimal("1234.50")), ("$1,234", Decimal("1234")), ("(1,200)", Decimal("-1200")),
    ("82%", Decimal("82")), ("3.5 hrs", Decimal("3.5")), ("", None), ("-", None),
])
def test_numbers_as_a_sheet_shows_them(text, expected):
    assert sheets.parse_number(text) == expected


def test_text_in_a_number_cell_is_said_in_words():
    with pytest.raises(sheets.FeedRefused, match='"n/a" isn\'t a number'):
        sheets.parse_number("n/a")


# ---------------------------------------------------------------- column mode

def test_a_messy_sheet_maps_cleanly_in_column_mode(practice):
    p = practice
    rows, w = messy_weekly()
    FakeSheets.books[(SHEET_ID, "Data")] = rows
    client = p["api"].as_(p["ff"])
    occupancy, revenue = p["kpis"]["occupancy"], p["kpis"]["revenue"]

    opened = post(client, f"{B}open/", mapping(p, occupancy)).json()
    assert opened["header_row"] == 2                      # row 3, counted from 0
    assert opened["title"] == "Weekly numbers" and opened["tab"] == "Data"

    body = mapping(p, revenue, date_column="A", date_header="Week of",
                   value_column="C", value_header="Revenue", header_row=2)
    preview = post(client, f"{B}preview/", body)
    assert preview.status_code == 200, preview.content
    shown = preview.json()
    by_start = {r["start"]: r for r in shown["periods"]}
    assert by_start[w[0].isoformat()]["value"] == 12400
    assert by_start[w[1].isoformat()]["value"] == 11950
    assert by_start[w[3].isoformat()]["value"] == -1200    # a refund in brackets
    assert by_start[w[4].isoformat()]["what"] == "open"    # this week: waits for its close
    assert w[2].isoformat() not in by_start                # "TBD" is not a reading
    assert shown["counts"]["new"] == 3 and shown["counts"]["open"] == 1
    skipped = {s["row"]: s["why"] for s in shown["skipped"]}
    assert skipped[7] == '"TBD" isn\'t a number.'
    assert skipped[11] == '"Total" isn\'t a date.'
    # The preview saved nothing.
    assert readings_of(revenue) == {}

    saved = put(client, B, body)
    assert saved.status_code == 200, saved.content
    assert saved.json()["run"] == {"ok": True, "new": 3, "update": 0, "kept": 0, "same": 0,
                                   "open": 1, "provisional": 0}
    got = readings_of(revenue)
    assert {s: r.value for s, r in got.items()} == {
        w[0]: Decimal("12400"), w[1]: Decimal("11950"), w[3]: Decimal("-1200")}
    assert all(r.source == KpiReading.Source.SHEET and r.entered_by_id is None
               for r in got.values())
    revenue.refresh_from_db()
    assert revenue.feed == Kpi.Feed.SHEET


def test_a_column_found_by_its_header_survives_a_column_inserted(practice):
    p = practice
    rows, w = messy_weekly()
    FakeSheets.books[(SHEET_ID, "Data")] = rows
    occupancy = p["kpis"]["occupancy"]
    put(p["api"].as_(p["ff"]), B, mapping(p, occupancy, date_column="A", date_header="Week of",
                                          value_column="B", value_header="Occupancy"))
    # Someone adds a column before Occupancy: it is found by its heading.
    FakeSheets.books[(SHEET_ID, "Data")] = [[r[0], "", *r[1:]] for r in rows]
    feed = KpiFeed.all_objects.get(kpi=occupancy)
    assert feeds.run(feed, timezone.localdate())["ok"]
    assert readings_of(occupancy)[w[3]].value == Decimal("84")


def test_daily_rows_feeding_a_weekly_kpi_combine_by_its_roll_up(practice):
    p = practice
    w = weeks_ago(1)
    rows = [["Date", "Revenue", "Occupancy"]] + [
        [us(w + timedelta(days=d)), f"${100 * (d + 1)}", f"{70 + d}%"] for d in range(7)]
    FakeSheets.books[(SHEET_ID, "Data")] = rows
    client = p["api"].as_(p["ff"])
    put(client, B, mapping(p, p["kpis"]["revenue"], date_column="A", date_header="Date",
                           value_column="B", value_header="Revenue"))
    put(client, B, mapping(p, p["kpis"]["occupancy"], date_column="A", date_header="Date",
                           value_column="C", value_header="Occupancy"))
    assert readings_of(p["kpis"]["revenue"])[w].value == Decimal("2800")      # summed
    assert readings_of(p["kpis"]["occupancy"])[w].value == Decimal("73")      # averaged


def test_per_person_rows_match_portal_users_by_name(practice):
    p = practice
    w = weeks_ago(1)
    reps = p["reps"]
    rows = [
        ["Calls by rep", "", ""], ["", "", ""],
        ["Week", "Rep", "Calls"],
        [us(w), "Mia Member", "41"],
        [us(w), "cole", "37"],                         # a first name, one Cole
        [us(w), reps["Sam Sales"].user.email.upper(), "29"],
        [us(w), "Jim H.", "12"],                       # nobody on the KPI
        [us(w), "", "5"],
    ]
    FakeSheets.books[(SHEET_ID, "Data")] = rows
    client = p["api"].as_(p["ff"])
    calls = p["kpis"]["calls"]
    body = mapping(p, calls, date_column="A", date_header="Week", value_column="C",
                   value_header="Calls")
    refused = post(client, f"{B}preview/", body)
    assert refused.status_code == 400 and "names" in refused.json()["detail"]
    body.update(name_column="B", name_header="Rep")
    shown = post(client, f"{B}preview/", body).json()
    assert {(r["person"], r["value"]) for r in shown["periods"]} == {
        ("Mia Member", 41), ("Cole Colleague", 37), ("Sam Sales", 29)}
    assert shown["unmatched"] == [{"name": "Jim H.", "rows": 1}]
    assert any(s["why"] == "No name in the name column." for s in shown["skipped"])
    # Matched by hand on the mapping screen.
    body["people"] = {"Jim H.": str(reps["Sam Sales"].pk)}
    body["value_header"] = "Calls"
    rows[5][1] = "Somebody else"
    shown = post(client, f"{B}preview/", body).json()
    assert ("Sam Sales", 12) in {(r["person"], r["value"]) for r in shown["periods"]}
    # Someone the KPI doesn't track can't be chosen.
    outsider = MembershipFactory(tenant=p["tenant"], role="ECC", client_company=p["company"])
    body["people"] = {"Jim H.": str(outsider.pk)}
    assert post(client, f"{B}preview/", body).status_code == 400


# ---------------------------------------------------------------- cell mode

def dashboard(value):
    return [
        ["", "NORTHWIND DASHBOARD", "", ""],
        ["", "", "", ""],
        ["", "This week", "", "Last updated"],
        ["", "Occupancy", value, "Mon 9am"],
        ["", "Revenue", "$4,200", ""],
        ["", "", "Notes: ignore row 6", ""],
    ]


def test_a_dashboard_sheet_maps_cleanly_in_cell_mode(practice):
    p = practice
    FakeSheets.books[(SHEET_ID, "Dash")] = dashboard("86.5%")
    client = p["api"].as_(p["ff"])
    occupancy = p["kpis"]["occupancy"]
    # Read at each close only; reading the open period too is tested below.
    body = mapping(p, occupancy, tab="Dash", mode="cell", cell="C4", read_open=False)
    shown = post(client, f"{B}preview/", body).json()
    assert shown["cell"] == {"ref": "C4", "value": 86.5, "period": P.long_label(
        weeks_ago(0), "weekly"), "closes": P.end_of(weeks_ago(0), "weekly").isoformat(),
        "so_far": False}
    saved = put(client, B, body).json()
    # The cell holds this week's number; it is stored when the week closes,
    # not as last week's.
    assert saved["run"]["ok"] and readings_of(occupancy) == {}

    feed = KpiFeed.all_objects.get(kpi=occupancy)
    next_week = weeks_ago(0) + timedelta(days=7)
    FakeSheets.books[(SHEET_ID, "Dash")] = dashboard("87%")
    feeds.run(feed, next_week)                               # the first read after the close
    assert readings_of(occupancy)[weeks_ago(0)].value == Decimal("87")
    # Read again later in the new week, the closed week's reading stays as it was.
    FakeSheets.books[(SHEET_ID, "Dash")] = dashboard("12%")
    feeds.run(feed, next_week + timedelta(days=2))
    assert readings_of(occupancy)[weeks_ago(0)].value == Decimal("87")
    # A blank cell makes nothing; text in it fails the read in words.
    FakeSheets.books[(SHEET_ID, "Dash")] = dashboard("")
    assert feeds.run(feed, next_week + timedelta(days=7))["ok"]
    assert next_week not in readings_of(occupancy)
    FakeSheets.books[(SHEET_ID, "Dash")] = dashboard("see Olive")
    result = feeds.run(feed, next_week + timedelta(days=7))
    assert result == {"ok": False, "error": '"see Olive" isn\'t a number.'}


def test_cell_mode_is_for_one_number_not_one_per_person(practice):
    p = practice
    body = mapping(p, p["kpis"]["calls"], mode="cell", cell="C4")
    response = post(p["api"].as_(p["ff"]), f"{B}preview/", body)
    assert response.status_code == 400 and "per person" in response.json()["detail"]


# ---------------------------------------------------------------- the rules of a feed

def test_the_hand_wins_and_a_feed_never_deletes(practice):
    p = practice
    rows, w = messy_weekly()
    FakeSheets.books[(SHEET_ID, "Data")] = rows
    revenue = p["kpis"]["revenue"]
    owner = p["owner"]
    # Olive typed week 1 before the feed existed.
    with tenant_context(p["tenant"].pk):
        KpiReading.objects.create(tenant=p["tenant"], kpi=revenue, period_start=w[1],
                                  value=Decimal("12000"), entered_by=owner.user,
                                  entered_at=timezone.now())
    client = p["api"].as_(p["ff"])
    body = mapping(p, revenue, date_column="A", date_header="Week of", value_column="C",
                   value_header="Revenue")
    shown = post(client, f"{B}preview/", body).json()
    kept = next(r for r in shown["periods"] if r["start"] == w[1].isoformat())
    assert kept["what"] == "kept" and kept["had"] == 12000
    run = put(client, B, body).json()["run"]
    assert run["kept"] == 1 and run["new"] == 2
    got = readings_of(revenue)
    assert got[w[1]].value == Decimal("12000") and got[w[1]].source == "hand"

    # The sheet changes its own number: the feed's reading follows, with history.
    rows[3][2] = "$12,500"
    feed = KpiFeed.all_objects.get(kpi=revenue)
    assert feeds.run(feed, timezone.localdate())["update"] == 1
    assert readings_of(revenue)[w[0]].value == Decimal("12500")
    # Someone corrects a sheet reading by hand: from then on it is theirs.
    with tenant_context(p["tenant"].pk):
        out = readings.save(_reader(p, p["owner"]), p["card"], [
            {"kpi": str(revenue.pk), "period_start": w[0].isoformat(), "value": "12450"}],
            timezone.localdate())
    assert out["changed"] == 1
    assert readings_of(revenue)[w[0]].source == "hand"
    rows[3][2] = "$99,999"
    feeds.run(feed, timezone.localdate())
    assert readings_of(revenue)[w[0]].value == Decimal("12450")
    # Rows deleted from the sheet delete nothing.
    FakeSheets.books[(SHEET_ID, "Data")] = rows[:3]
    before = {s: r.value for s, r in readings_of(revenue).items()}
    feeds.run(feed, timezone.localdate())
    assert {s: r.value for s, r in readings_of(revenue).items()} == before


def _reader(p, membership):
    from django.test import RequestFactory

    from apps.scorecard.access import Reader

    request = RequestFactory().get("/")
    request.user = membership.user
    request.membership = membership
    request.tenant = p["tenant"]
    return Reader(request, p["company"])


def test_a_failed_read_keeps_the_readings_and_tells_the_reading_owner_once(practice):
    p = practice
    rows, w = messy_weekly()
    FakeSheets.books[(SHEET_ID, "Data")] = rows
    occupancy = p["kpis"]["occupancy"]
    client = p["api"].as_(p["ff"])
    put(client, B, mapping(p, occupancy, date_column="A", date_header="Week of",
                           value_column="B", value_header="Occupancy"))
    before = {s: r.value for s, r in readings_of(occupancy).items()}
    assert len(before) == 4                 # three closed weeks and this one so far
    # The client renames the column.
    rows[2][1] = "Occ %"
    feed = KpiFeed.all_objects.get(kpi=occupancy)
    result = feeds.run(feed, timezone.localdate())
    words = "The sheet 'Weekly numbers' (tab 'Data') has no column called Occupancy."
    assert result == {"ok": False, "error": words}
    assert {s: r.value for s, r in readings_of(occupancy).items()} == before
    feeds.run(feed, timezone.localdate())                   # failing again, hours later
    owner_client = p["api"].as_(p["owner"])
    told = [n for n in owner_client.get(
        f"/api/scorecard/notices/?company={p['company'].pk}").json() if n["kind"] == "feed"]
    assert len(told) == 1 and told[0]["text"] == words and told[0]["kpi"] == "Occupancy"
    # Nobody else is told.
    rep = next(iter(p["reps"].values()))
    assert not [n for n in p["api"].as_(rep).get(
        f"/api/scorecard/notices/?company={p['company'].pk}").json() if n["kind"] == "feed"]
    # Google refusing is said as Google said it, and fixed is quiet again.
    feed.refresh_from_db()
    assert feeds.run(feed, timezone.localdate(), client=FakeSheets(
        p["connection"], refuse="bryan@practice.example can't open that spreadsheet."))[
        "error"] == "bryan@practice.example can't open that spreadsheet."
    rows[2][1] = "Occupancy"
    assert feeds.run(feed, timezone.localdate())["ok"]
    assert not [n for n in owner_client.get(
        f"/api/scorecard/notices/?company={p['company'].pk}").json() if n["kind"] == "feed"]


def test_the_tile_back_names_the_source(practice):
    p = practice
    rows, w = messy_weekly()
    FakeSheets.books[(SHEET_ID, "Data")] = rows
    occupancy = p["kpis"]["occupancy"]
    client = p["api"].as_(p["ff"])
    put(client, B, mapping(p, occupancy, date_column="A", date_header="Week of",
                           value_column="B", value_header="Occupancy"))
    data = client.get(f"/api/scorecard/?company={p['company'].pk}&window=this_quarter").json()
    tile = next(t for t in data["kpis"] if t["name"] == "Occupancy")
    assert tile["feed"] == {"kind": "sheet", "text": "From the Google Sheet 'Weekly numbers', "
                            "tab 'Data', read every hour, the open period so far",
                            "error": ""}
    point = next(x for x in tile["history"] if x["period_start"] == w[3].isoformat())
    assert point["source"] == "sheet"
    # A client reader sees where it comes from, not the failure details.
    rows[2][1] = "Gone"
    feeds.run(KpiFeed.all_objects.get(kpi=occupancy), timezone.localdate())
    rep = next(iter(p["reps"].values()))
    data = p["api"].as_(rep).get(f"/api/scorecard/?company={p['company'].pk}").json()
    tile = next(t for t in data["kpis"] if t["name"] == "Occupancy")
    assert tile["feed"]["text"].startswith("From the Google Sheet") and tile["feed"]["error"] == ""


def test_stopping_a_feed_keeps_its_readings(practice):
    p = practice
    rows, _ = messy_weekly()
    FakeSheets.books[(SHEET_ID, "Data")] = rows
    occupancy = p["kpis"]["occupancy"]
    client = p["api"].as_(p["ff"])
    put(client, B, mapping(p, occupancy, date_column="A", date_header="Week of",
                           value_column="B", value_header="Occupancy"))
    count = len(readings_of(occupancy))
    response = client.delete(f"{B}?company={p['company'].pk}&kpi={occupancy.pk}")
    assert response.status_code == 200
    assert len(readings_of(occupancy)) == count
    occupancy.refresh_from_db()
    assert occupancy.feed == Kpi.Feed.HAND
    assert feeds.run_due(p["tenant"].pk, timezone.localdate())["ran"] == 0


# ---------------------------------------------------------------- the schedule

def test_hourly_and_daily_refresh(practice):
    p = practice
    rows, _ = messy_weekly()
    FakeSheets.books[(SHEET_ID, "Data")] = rows
    client = p["api"].as_(p["ff"])
    put(client, B, mapping(p, p["kpis"]["occupancy"], date_column="A", date_header="Week of",
                           value_column="B", value_header="Occupancy", refresh="hourly"))
    put(client, B, mapping(p, p["kpis"]["revenue"], date_column="A", date_header="Week of",
                           value_column="C", value_header="Revenue", refresh="daily"))
    now = timezone.now()
    today = timezone.localdate()
    assert feeds.run_due(p["tenant"].pk, today, now=now + timedelta(hours=1))["ran"] == 1
    assert feeds.run_due(p["tenant"].pk, today, now=now + timedelta(hours=24))["ran"] == 2


# ---------------------------------------------------------------- the open period so far

def test_the_open_period_is_read_so_far_by_default_for_last_and_average(practice):
    p = practice
    rows, w = messy_weekly()
    FakeSheets.books[(SHEET_ID, "Data")] = rows
    client = p["api"].as_(p["ff"])
    occupancy, revenue = p["kpis"]["occupancy"], p["kpis"]["revenue"]
    cols = {"date_column": "A", "date_header": "Week of"}
    # The default follows the roll-up: on for an average, off for a sum.
    assert client.get(f"{B}?company={p['company'].pk}&kpi={occupancy.pk}").json()[
        "read_open_default"] is True
    assert client.get(f"{B}?company={p['company'].pk}&kpi={revenue.pk}").json()[
        "read_open_default"] is False

    saved = put(client, B, mapping(p, occupancy, value_column="B", value_header="Occupancy",
                                   **cols)).json()
    assert saved["run"]["provisional"] == 1 and saved["run"]["open"] == 0
    assert saved["feed"]["read_open"] is True and saved["feed"]["read_open_default"] is True
    now = readings_of(occupancy)[w[4]]
    assert now.value == Decimal("88") and now.provisional and now.source == "sheet"
    # A sum waits for the close, as before.
    run = put(client, B, mapping(p, revenue, value_column="C", value_header="Revenue",
                                 **cols)).json()["run"]
    assert run["open"] == 1 and run["provisional"] == 0 and w[4] not in readings_of(revenue)

    # Tiles and the grid mark it "so far"; closed weeks are not.
    board = client.get(f"/api/scorecard/?company={p['company'].pk}&window=this_week").json()
    tile = next(t for t in board["kpis"] if t["name"] == "Occupancy")
    assert tile["summary"]["value"] == 88 and tile["summary"]["so_far"] is True
    marks = {x["period_start"]: x["so_far"] for x in tile["history"]}
    assert marks[w[4].isoformat()] is True and marks[w[3].isoformat()] is False
    # The front's value is the open week's; Details lists the closed ones before it.
    assert tile["history"][-1]["period_start"] == w[4].isoformat()
    assert tile["history"][-1]["value"] == 88
    assert not any(x["so_far"] for x in tile["history"][:-1])

    # Each refresh replaces it, still "so far".
    feed = KpiFeed.all_objects.get(kpi=occupancy)
    rows[8][1] = "90%"
    assert feeds.run(feed, timezone.localdate())["provisional"] == 1
    again = readings_of(occupancy)[w[4]]
    assert again.pk == now.pk and again.value == Decimal("90") and again.provisional

    # The week closes before the next read: no missing-reading reminder for it,
    # and the last value read is its reading.
    next_week = w[4] + timedelta(days=7)
    with tenant_context(p["tenant"].pk):
        readings.remind(p["tenant"], next_week)
    from apps.scorecard.models import KpiReminder
    assert not KpiReminder.all_objects.filter(kpi=occupancy, period_start=w[4]).exists()
    assert feeds.finalise(p["tenant"].pk, next_week) == 1
    final = readings_of(occupancy)[w[4]]
    assert final.value == Decimal("90") and not final.provisional
    board = client.get(f"/api/scorecard/?company={p['company'].pk}&window=this_quarter").json()
    tile = next(t for t in board["kpis"] if t["name"] == "Occupancy")
    assert not any(x["so_far"] for x in tile["history"])


def test_the_first_read_after_the_close_makes_the_final_reading(practice):
    p = practice
    rows, w = messy_weekly()
    FakeSheets.books[(SHEET_ID, "Data")] = rows
    client = p["api"].as_(p["ff"])
    occupancy = p["kpis"]["occupancy"]
    put(client, B, mapping(p, occupancy, date_column="A", date_header="Week of",
                           value_column="B", value_header="Occupancy"))
    feed = KpiFeed.all_objects.get(kpi=occupancy)
    rows[8][1] = "91%"
    next_week = w[4] + timedelta(days=7)
    run = feeds.run(feed, next_week)
    assert run["update"] == 1 and run["provisional"] == 0
    got = readings_of(occupancy)[w[4]]
    assert got.value == Decimal("91") and not got.provisional
    from apps.scorecard.models import KpiReadingChange
    assert [c.value for c in KpiReadingChange.all_objects.filter(reading=got)] == [
        Decimal("88"), Decimal("91")]


def test_typed_by_hand_the_open_period_is_never_overwritten(practice):
    p = practice
    rows, w = messy_weekly()
    FakeSheets.books[(SHEET_ID, "Data")] = rows
    client = p["api"].as_(p["ff"])
    occupancy = p["kpis"]["occupancy"]
    put(client, B, mapping(p, occupancy, date_column="A", date_header="Week of",
                           value_column="B", value_header="Occupancy"))
    with tenant_context(p["tenant"].pk):
        out = readings.save(_reader(p, p["owner"]), p["card"], [
            {"kpi": str(occupancy.pk), "period_start": w[4].isoformat(), "value": "85"}],
            timezone.localdate())
    assert out["changed"] == 1
    typed = readings_of(occupancy)[w[4]]
    assert typed.source == "hand" and not typed.provisional
    rows[8][1] = "95%"
    feed = KpiFeed.all_objects.get(kpi=occupancy)
    assert feeds.run(feed, timezone.localdate())["kept"] == 1
    assert feeds.run(feed, w[4] + timedelta(days=7))["kept"] == 1
    assert readings_of(occupancy)[w[4]].value == Decimal("85")


def test_the_choice_is_the_feeds_and_is_kept_until_changed(practice):
    p = practice
    rows, w = messy_weekly()
    FakeSheets.books[(SHEET_ID, "Data")] = rows
    client = p["api"].as_(p["ff"])
    revenue = p["kpis"]["revenue"]
    body = mapping(p, revenue, date_column="A", date_header="Week of", value_column="C",
                   value_header="Revenue")
    shown = post(client, f"{B}preview/", {**body, "read_open": True}).json()
    assert {r["start"]: r["what"] for r in shown["periods"]}[w[4].isoformat()] == "provisional"
    saved = put(client, B, {**body, "read_open": True}).json()
    assert saved["feed"]["read_open"] is True and saved["feed"]["read_open_default"] is False
    assert readings_of(revenue)[w[4]].provisional
    # Saved again without saying, the choice stays; said, it changes.
    assert put(client, B, body).json()["feed"]["read_open"] is True
    off = put(client, B, {**body, "read_open": False}).json()
    assert off["feed"]["read_open"] is False and off["run"]["open"] == 1


def test_a_cell_read_as_it_goes_gives_the_close_its_last_number(practice):
    p = practice
    FakeSheets.books[(SHEET_ID, "Dash")] = dashboard("86.5%")
    client = p["api"].as_(p["ff"])
    occupancy = p["kpis"]["occupancy"]
    put(client, B, mapping(p, occupancy, tab="Dash", mode="cell", cell="C4"))
    this_week = weeks_ago(0)
    got = readings_of(occupancy)
    assert set(got) == {this_week} and got[this_week].provisional
    assert got[this_week].value == Decimal("86.5")
    feed = KpiFeed.all_objects.get(kpi=occupancy)
    assert feeds.source_text(feed).endswith("cell C4, read every hour, the open period so far")
    # The first read after the close is the closed week's final number, and
    # the new week's so far.
    next_week = this_week + timedelta(days=7)
    FakeSheets.books[(SHEET_ID, "Dash")] = dashboard("87%")
    feeds.run(feed, next_week)
    got = readings_of(occupancy)
    assert got[this_week].value == Decimal("87") and not got[this_week].provisional
    assert got[next_week].value == Decimal("87") and got[next_week].provisional
    # Later in the new week the closed week stays; the open one follows the cell.
    FakeSheets.books[(SHEET_ID, "Dash")] = dashboard("12%")
    feeds.run(feed, next_week + timedelta(days=2))
    got = readings_of(occupancy)
    assert got[this_week].value == Decimal("87")
    assert got[next_week].value == Decimal("12") and got[next_week].provisional


# ---------------------------------------------------------------- isolation

def test_one_practices_feed_never_reads_another_practices_sheet(practice, api):
    p = practice
    rows, _ = messy_weekly()
    FakeSheets.books[(SHEET_ID, "Data")] = rows
    FakeSheets.books[(OTHER_ID, "Data")] = rows
    # Practice B, with its own Google connection, KPI and feed.
    other = TenantFactory()
    from apps.crm.seed import seed_tenant

    seed_tenant(other)
    b_ff = MembershipFactory(tenant=other, role="FF")
    b_connection = GmailConnectionFactory(tenant=other, user=b_ff.user, scopes=GRANTED)
    b_company = ClientCompanyFactory(tenant=other, name="Blue Co", seat_count=3)
    with tenant_context(other.pk):
        b_card = setup.ensure(b_company, b_ff.user)
        b_kpi = setup.create_kpi(b_card, {"name": "Leads", "kind": "count", "cadence": "weekly",
                                          "page": str(b_card.pages.get().pk)}, b_ff.user)
    b_body = {"company": str(b_company.pk), "kpi": str(b_kpi.pk),
              "spreadsheet": OTHER_ID, "spreadsheet_name": "B's", "tab": "Data",
              "mode": "column", "refresh": "hourly", "date_column": "A",
              "date_header": "Week of", "value_column": "B", "value_header": "Occupancy"}
    assert put(api.as_(b_ff), B, b_body).status_code == 200
    a_body = mapping(p, p["kpis"]["occupancy"], date_column="A", date_header="Week of",
                     value_column="B", value_header="Occupancy")
    assert put(p["api"].as_(p["ff"]), B, a_body).status_code == 200

    FakeSheets.calls = []
    feeds.run_due(p["tenant"].pk, timezone.localdate(), now=timezone.now() + timedelta(hours=2))
    assert FakeSheets.calls and all(
        (tenant, conn, sid) == (p["tenant"].pk, p["connection"].pk, SHEET_ID)
        for tenant, conn, sid in FakeSheets.calls)
    assert KpiReading.all_objects.filter(kpi=b_kpi).count() == 3     # B's from its own run

    # A feed pointed at another practice's connection is never read through it.
    feed = KpiFeed.all_objects.get(kpi=p["kpis"]["occupancy"])
    KpiFeed.all_objects.filter(pk=feed.pk).update(connection=b_connection)
    feed.refresh_from_db()
    FakeSheets.calls = []
    feeds.run(feed, timezone.localdate())
    assert all(conn != b_connection.pk for _, conn, _ in FakeSheets.calls)

    # B's people can't reach A's KPI or its feed through any route.
    b_client = api.as_(b_ff)
    a_query = f"?company={p['company'].pk}&kpi={p['kpis']['occupancy'].pk}"
    assert b_client.get(f"{B}{a_query}").status_code == 404
    assert put(b_client, B, a_body).status_code == 404
    assert post(b_client, f"{B}preview/", a_body).status_code == 404
    assert post(b_client, f"{B}open/", a_body).status_code == 404
    assert post(b_client, f"{B}run/", a_body).status_code == 404
    assert b_client.delete(f"{B}{a_query}").status_code == 404
    # And B's KPI through A's company is 404 too.
    mixed = dict(a_body, kpi=str(b_kpi.pk))
    assert put(p["api"].as_(p["ff"]), B, mixed).status_code == 404


# ---------------------------------------------------------------- who sets it up

def test_only_the_practice_owner_and_associates_set_up_a_feed(practice, seeded_tenant):
    p = practice
    FakeSheets.books[(SHEET_ID, "Data")] = messy_weekly()[0]
    body = mapping(p, p["kpis"]["occupancy"], date_column="A", value_column="B")
    va = MembershipFactory(tenant=seeded_tenant, role="VA")
    for who, status in ((va, 403), (p["owner"], 403),
                        (next(iter(p["reps"].values())), 403)):
        client = p["api"].as_(who)
        assert put(client, B, body).status_code == status
        assert post(client, f"{B}preview/", body).status_code == status
    # An associate not assigned to the company doesn't reach it at all.
    cf = MembershipFactory(tenant=seeded_tenant, role="CF")
    assert put(p["api"].as_(cf), B, body).status_code == 404


# ---------------------------------------------------------------- Google

def test_a_grant_from_before_the_sheets_permission_asks_to_reconnect(practice):
    p = practice
    p["connection"].scopes = TIER1_SCOPES + DRIVE_SCOPES
    p["connection"].save(update_fields=["scopes"])
    client = p["api"].as_(p["ff"])
    query = f"?company={p['company'].pk}&kpi={p['kpis']['occupancy'].pk}"
    google = client.get(f"{B}{query}").json()["google"]
    assert google["ready"] is False and google["reconnect"] is True
    opened = post(client, f"{B}open/", mapping(p, p["kpis"]["occupancy"]))
    assert opened.status_code == 409 and opened.json()["reconnect"] is True
    assert "Reconnect Google" in opened.json()["detail"]

    from django.test import override_settings

    with override_settings(GOOGLE_OAUTH_CLIENT_ID="cid", GOOGLE_OAUTH_CLIENT_SECRET="secret"):
        url = post(client, f"{B}consent/", {"company": str(p["company"].pk),
                                            "kpi": str(p["kpis"]["occupancy"].pk)}).json()[
            "authorization_url"]
    # The Sheets permission is asked for, and Drive, which it already had, kept.
    assert "spreadsheets.readonly" in url and "drive.readonly" in url
    assert "gmail.readonly" not in url
    session = client.session
    assert session["gmail_oauth_sheets"] is True
    assert session["gmail_oauth_return"] == f"scorecard:{p['company'].pk}"


def test_the_callback_keeps_the_sheets_grant_and_returns_to_the_scorecard(practice, monkeypatch):
    from apps.crm.services import gmail_oauth, transport

    p = practice
    client = p["api"].as_(p["ff"])
    session = client.session
    session.update({"gmail_oauth_state": "s1", "gmail_oauth_return": f"scorecard:{p['company'].pk}",
                    "gmail_oauth_sheets": True, "gmail_oauth_drive": False,
                    "gmail_oauth_inbound": False})
    session.save()
    monkeypatch.setattr(gmail_oauth, "exchange_code", lambda code, tenant=None: {
        "access_token": "a", "refresh_token": "r", "scope": " ".join(GRANTED)})
    monkeypatch.setattr(gmail_oauth, "account_email", lambda token: "bryan@practice.example")
    monkeypatch.setattr(transport, "verify_send_as", lambda *a, **k: None)
    response = client.get("/accounts/gmail/callback?state=s1&code=c")
    assert response.status_code == 302
    assert f"/companies/{p['company'].pk}/scorecard?sheets_connected=" in response["Location"]
    p["connection"].refresh_from_db()
    assert set(SHEETS_SCOPES) <= set(p["connection"].scopes)
