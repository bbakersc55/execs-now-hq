"""Set up KPIs from a sheet (2026-11-17, `docs/p6_m5_kpi_scorecard.md`).

Against the Sheets feed tests' fake client. The sheet is the first real
one's shape: "Week ending" in column A (Sundays, for a company whose week
starts Monday), an unnamed column B, and 39 KPI columns with $ and % in their
headers and values such as 1,530,000. Proven here: week-ending dates land in
the right Monday-start week; blanks are no reading, never zero; money and
percent parse; every column is proposed with its name, unit, cadence,
direction and roll-up; they are made at once with a feed each and their
history loads; a new row arrives with the nightly read; a re-run offers only
the new columns and never makes a KPI twice; only the practice owner and
associates use it; and another practice reaches nothing.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.scorecard import feeds, sheet_setup, sheets
from apps.scorecard import periods as P
from apps.scorecard.models import Kpi, KpiFeed, KpiReading, ScorecardPage
from apps.tenancy.context import tenant_context

from . import registry_config  # noqa: F401
from .factories import ClientCompanyFactory, GmailConnectionFactory, MembershipFactory
from .test_scorecard_feeds import GRANTED, SHEET_ID, FakeSheets, fake_google  # noqa: F401

OPEN = "/api/scorecard/sheet-setup/open/"
MAKE = "/api/scorecard/sheet-setup/"
ADDRESS = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit#gid=0"
WEEKS = 12

#: The 39 KPI columns: (header, value for week n). A few are blank some weeks.
KPIS = [
    ("Revenue ($)", lambda n: f"{1_500_000 + 30_000 * n:,}"),
    ("Gross margin %", lambda n: f"{41 + n / 10:.1f}%"),
    ("Leads", lambda n: str(120 + n)),
    ("Cost per lead ($)", lambda n: f"${42 + n}.50"),
    ("Open pipeline ($)", lambda n: f"{2_400_000 + 10_000 * n:,}"),
    ("Close rate %", lambda n: "" if n == 3 else f"{22 + n % 4}%"),
    ("Ad spend ($)", lambda n: f"${8_000 + 100 * n:,}"),
    ("Churn %", lambda n: f"{2.1 + n / 100:.2f}%"),
] + [(f"Measure {i} ($)" if i % 3 == 0 else f"Measure {i} %" if i % 3 == 1
      else f"Measure {i}", lambda n, i=i: "" if (n + i) % 7 == 0 else f"{i * 1_000 + n:,}")
     for i in range(31)]


def week_ending(n: int) -> date:
    """The Sunday that ends the Monday-start week n weeks back."""
    today = timezone.localdate()
    return P.start_of(today, P.WEEKLY, "monday") - timedelta(weeks=n) + timedelta(days=6)


def the_sheet(weeks=WEEKS, extra=()):
    header = ["Week ending", ""] + [h for h, _ in KPIS] + [h for h, _ in extra]
    rows = [header]
    for n in range(weeks, 0, -1):
        day = week_ending(n)
        rows.append([f"{day.month}/{day.day}/{day.year}", "note" if n % 5 == 0 else ""]
                    + [f(n) for _, f in KPIS] + [f(n) for _, f in extra])
    return rows


@pytest.fixture
def shop(seeded_tenant, ff, api):
    tenant = seeded_tenant
    company = ClientCompanyFactory(tenant=tenant, name="Northwind Foods")
    GmailConnectionFactory(tenant=tenant, user=ff.user, scopes=GRANTED,
                           email_address="bryan@practice.example")
    FakeSheets.books[(SHEET_ID, "Weekly")] = the_sheet()
    FakeSheets.books[(SHEET_ID, "Notes")] = [["Nothing here"]]
    return {"tenant": tenant, "company": company, "ff": ff, "api": api}


def post(client, url, body):
    return client.post(url, json.dumps(body), content_type="application/json")


def opened(shop, who=None, **more):
    client = shop["api"].as_(who or shop["ff"])
    answer = post(client, OPEN, {"company": str(shop["company"].pk), "spreadsheet": ADDRESS,
                                 "tab": "Weekly", **more})
    assert answer.status_code == 200, answer.content
    return answer.json()


def make_all(shop, proposal, *, changes=None, new_pages=None, page=None):
    columns = []
    for c in proposal["columns"]:
        row = {k: c[k] for k in ("column", "header", "name", "kind", "cadence", "direction",
                                 "rollup", "skip")}
        row.update((changes or {}).get(c["column"], {}))
        if not row.get("new_page"):
            row["page"] = page
        columns.append(row)
    body = {"company": str(shop["company"].pk), "spreadsheet": ADDRESS,
            "spreadsheet_name": "Weekly numbers", "tab": "Weekly",
            "header_row": proposal["header_row"], "date_column": proposal["date_column"],
            "date_is": proposal["date_is"], "columns": columns, "new_pages": new_pages or []}
    return post(shop["api"].as_(shop["ff"]), MAKE, body)


def first_page(shop):
    return str(ScorecardPage.all_objects.filter(
        scorecard__company=shop["company"]).order_by("position").first().pk)


# ============================================================== the dates

@pytest.mark.parametrize("day, date_is, week_start, expected", [
    # The week ending Sunday October 4, 2026 starts Monday September 28.
    (date(2026, 10, 4), "end", "monday", date(2026, 9, 28)),
    (date(2026, 10, 4), "", "monday", date(2026, 9, 28)),
    # Week ending Saturday for a Monday-start company: most of it is the
    # week of September 28.
    (date(2026, 10, 3), "end", "monday", date(2026, 9, 28)),
    # For a Sunday-start company, the week ending Sunday the 4th is mostly
    # the week of Sunday September 27 (a plain date would say October 4).
    (date(2026, 10, 4), "end", "sunday", date(2026, 9, 27)),
    (date(2026, 10, 4), "", "sunday", date(2026, 10, 4)),
    # Dates that are a week's first day.
    (date(2026, 9, 28), "start", "monday", date(2026, 9, 28)),
])
def test_week_ending_dates_land_in_the_right_week(day, date_is, week_start, expected):
    placed = sheets.period_day(day, P.WEEKLY, date_is)
    assert P.start_of(placed, P.WEEKLY, week_start) == expected


@pytest.mark.parametrize("day, date_is, expected", [
    (date(2026, 10, 31), "end", date(2026, 10, 1)),
    (date(2026, 10, 1), "start", date(2026, 10, 1)),
    (date(2026, 12, 31), "end", date(2026, 12, 1)),
])
def test_month_end_and_month_start_dates_land_in_their_month(day, date_is, expected):
    assert P.start_of(sheets.period_day(day, P.MONTHLY, date_is), P.MONTHLY) == expected


def test_the_spacing_of_the_dates_gives_the_cadence_and_the_header_what_they_are():
    weekly = [date(2026, 9, 6) + timedelta(weeks=n) for n in range(6)]
    assert sheet_setup.cadence_of(weekly) == "weekly"
    assert sheet_setup.cadence_of([date(2026, m, 1) for m in range(1, 7)]) == "monthly"
    assert sheet_setup.cadence_of([date(2026, m, 1) for m in (1, 4, 7, 10)]) == "quarterly"
    assert sheet_setup.cadence_of([date(2026, 9, d) for d in range(1, 9)]) == "daily"
    assert sheet_setup.date_is_of("Week ending", weekly, "weekly", "monday") == "end"
    assert sheet_setup.date_is_of("Week of", weekly, "weekly", "monday") == "start"
    # No word in the header: Sundays for a Monday-start week are the week's last day.
    assert sheet_setup.date_is_of("Date", weekly, "weekly", "monday") == "end"
    assert sheet_setup.date_is_of("Date", [date(2026, m, 1) for m in range(1, 5)], "monthly",
                                  "monday") == "start"


# ============================================================== the cells

@pytest.mark.parametrize("cell, kind, expected", [
    ("1,530,000", "number", Decimal("1530000")), ("$1,530,000", "money", Decimal("1530000")),
    ("$42.50", "money", Decimal("42.50")), ("45.2%", "percent", Decimal("45.2")),
    ("(1,200)", "money", Decimal("-1200")),
])
def test_money_and_percent_parse(cell, kind, expected):
    kpi = Kpi(kind=kind, name="x")
    assert sheets.as_reading(kpi, sheets.parse_number(cell)) == expected


def test_a_blank_cell_is_no_reading_never_zero():
    assert sheets.parse_number("") is None and sheets.parse_number("  ") is None
    assert sheets.parse_number("-") is None


@pytest.mark.parametrize("header, name, kind, direction, rollup", [
    ("Revenue ($)", "Revenue", "money", "higher", "sum"),
    ("Gross margin %", "Gross margin", "percent", "higher", "average"),
    ("Cost per lead ($)", "Cost per lead", "money", "lower", "average"),
    ("Open pipeline ($)", "Open pipeline", "money", "higher", "last"),
    ("Ad spend ($)", "Ad spend", "money", "lower", "sum"),
    ("Leads", "Leads", "number", "higher", "sum"),
    ("Latest month AR ($)", "Latest month AR", "money", "higher", "last"),
    # 2026-11-18: counts add up, and cost-per figures and losses are lower-is-better.
    ("Google Ads conversions", "Google Ads conversions", "number", "higher", "sum"),
    ("Conversion rate %", "Conversion rate", "percent", "higher", "average"),
    ("Calls per day", "Calls per day", "number", "higher", "average"),
    ("Google Ads avg CPC $", "Google Ads avg CPC", "money", "lower", "average"),
    ("Meta cost per landing page view $", "Meta cost per landing page view", "money",
     "lower", "average"),
    ("Deals closed lost", "Deals closed lost", "number", "lower", "sum"),
    ("Deals closed won", "Deals closed won", "number", "higher", "sum"),
    ("Open pipeline deals", "Open pipeline deals", "number", "higher", "last"),
])
def test_a_header_gives_name_unit_direction_and_rollup(header, name, kind, direction, rollup):
    got = sheet_setup.name_of(header)
    unit = sheet_setup.kind_of(header)
    assert (got, unit, sheet_setup.direction_of(got), sheet_setup.rollup_of(got, unit)) == (
        name, kind, direction, rollup)


# ============================================================== the proposal

@pytest.mark.django_db
def test_the_sheet_is_proposed_column_by_column(shop):
    page = opened(shop)
    assert [t["title"] for t in page["tabs"]] == ["Notes", "Weekly"]
    p = page["proposal"]
    assert {c["priority"] for c in p["columns"]} == {"medium"}
    assert (p["date_column"], p["date_header"], p["date_is"], p["cadence"]) == (
        "A", "Week ending", "end", "weekly")
    assert p["dates"]["count"] == WEEKS
    assert p["skipped"] == [{"column": "B", "reason": "No header, so it is skipped."}]
    assert len(p["columns"]) == 39 and not p["already"]
    by = {c["header"]: c for c in p["columns"]}
    assert by["Revenue ($)"]["column"] == "C" and by["Revenue ($)"]["kind"] == "money"
    assert by["Gross margin %"]["rollup"] == "average"
    assert by["Cost per lead ($)"]["direction"] == "lower"
    assert by["Open pipeline ($)"]["rollup"] == "last"
    assert by["Close rate %"]["blanks"] == 1 and not by["Close rate %"]["skip"]
    assert {c["cadence"] for c in p["columns"]} == {"weekly"}


# ============================================================== making them

@pytest.mark.django_db
def test_making_them_all_loads_the_history_with_blanks_as_no_reading(shop):
    p = opened(shop)["proposal"]
    made = make_all(shop, p, page=first_page(shop),
                    changes={"C": {"name": "Net revenue", "priority": "top"},
                             "D": {"new_page": "money", "rollup": "last"},
                             "E": {"skip": True}},
                    new_pages=[{"key": "money", "name": "Money", "audience": "leadership"}])
    assert made.status_code == 201, made.content
    summary = made.json()
    assert len(summary["created"]) == 38
    assert {"column": "E", "reason": "Skipped by you."} in summary["columns_skipped"]
    assert {"column": "B", "reason": "No header, so it is skipped."} in summary["columns_skipped"]
    with tenant_context(shop["tenant"].pk):
        kpis = {k.name: k for k in Kpi.objects.filter(scorecard__company=shop["company"])}
        assert len(kpis) == 38 and "Leads" not in kpis
        revenue = kpis["Net revenue"]
        feed = KpiFeed.objects.get(kpi=revenue)
        assert (feed.value_column, feed.value_header, feed.date_column, feed.date_is,
                feed.mode) == ("C", "Revenue ($)", "A", "end", "column")
        assert revenue.feed == "sheet" and revenue.kind == "money"
        # 2026-11-18: the table's Priority column; a column not changed is Medium.
        assert revenue.priority == "top" and kpis["Gross margin"].priority == "medium"
        margin = kpis["Gross margin"]
        assert margin.page.name == "Money" and margin.page.audience == "leadership"
        assert margin.rollup == "last"
        # Each feed reads its own column: one KPI, one feed.
        assert KpiFeed.objects.filter(kpi__scorecard__company=shop["company"]).count() == 38
        values = {r.period_start: r.value for r in KpiReading.objects.filter(kpi=revenue)}
        first_week = week_ending(WEEKS) - timedelta(days=6)
        assert values[first_week] == Decimal(f"{1_500_000 + 30_000 * WEEKS}")
        assert len(values) == WEEKS
        close = {r.period_start: r.value for r in
                 KpiReading.objects.filter(kpi=kpis["Close rate"])}
        assert len(close) == WEEKS - 1                       # week 3 was blank
        assert (week_ending(3) - timedelta(days=6)) not in close
        assert Decimal("0") not in close.values()
        loaded = KpiReading.objects.filter(kpi__scorecard__company=shop["company"]).count()
    assert summary["readings"] == loaded and summary["blank_cells"] > 0
    assert summary["failed"] == []


@pytest.mark.django_db
def test_a_new_row_arrives_with_the_nightly_read(shop):
    p = opened(shop)["proposal"]
    assert make_all(shop, p, page=first_page(shop)).status_code == 201
    rows = the_sheet()
    rows.insert(1, ["10/1/2000", ""] + ["" for _ in KPIS])     # an old empty row
    today = timezone.localdate()
    with tenant_context(shop["tenant"].pk):
        revenue = Kpi.objects.get(scorecard__company=shop["company"], name="Revenue")
        before = KpiReading.objects.filter(kpi=revenue).count()
        # Next week's row, once that week has closed.
        later = today + timedelta(days=7)
        n_next = week_ending(0)
        rows.append([f"{n_next.month}/{n_next.day}/{n_next.year}", ""]
                    + ["9,999,999" for _ in KPIS])
        FakeSheets.books[(SHEET_ID, "Weekly")] = rows
        feeds.run(KpiFeed.objects.get(kpi=revenue), later)
        after = {r.period_start: r.value for r in KpiReading.objects.filter(kpi=revenue)}
    assert len(after) == before + 1
    assert after[n_next - timedelta(days=6)] == Decimal("9999999")


@pytest.mark.django_db
def test_a_rerun_offers_only_new_columns_and_never_makes_a_kpi_twice(shop):
    p = opened(shop)["proposal"]
    assert make_all(shop, p, page=first_page(shop)).status_code == 201
    FakeSheets.books[(SHEET_ID, "Weekly")] = the_sheet(
        extra=[("Referrals", lambda n: str(n)), ("Open tickets", lambda n: str(30 - n))])
    again = opened(shop)["proposal"]
    assert [c["header"] for c in again["columns"]] == ["Referrals", "Open tickets"]
    assert len(again["already"]) == 39
    assert {c["rollup"] for c in again["columns"]} == {"sum", "last"}
    # The first proposal sent again: nothing it names is made a second time.
    replay = make_all(shop, p, page=first_page(shop))
    assert replay.status_code == 201 and replay.json()["created"] == []
    assert len(replay.json()["already"]) == 39
    made = make_all(shop, again, page=first_page(shop))
    assert [k["name"] for k in made.json()["created"]] == ["Referrals", "Open tickets"]
    with tenant_context(shop["tenant"].pk):
        assert Kpi.objects.filter(scorecard__company=shop["company"]).count() == 41
    # A name already on the scorecard is skipped on the proposal, refused if sent.
    FakeSheets.books[(SHEET_ID, "Weekly")] = the_sheet(extra=[("Leads ", lambda n: "1")])
    clash = opened(shop)["proposal"]["columns"]
    assert clash == [] or (clash[0]["skip"] and "already" in clash[0]["why_skip"])


@pytest.mark.django_db
def test_two_columns_with_one_name_are_refused(shop):
    p = opened(shop)["proposal"]
    made = make_all(shop, p, page=first_page(shop),
                    changes={"C": {"name": "Leads"}})
    assert made.status_code == 400 and "rename one" in made.json()["detail"]
    with tenant_context(shop["tenant"].pk):
        assert not Kpi.objects.filter(scorecard__company=shop["company"]).exists()


# ============================================================== who uses it

@pytest.mark.django_db
def test_only_the_practice_owner_and_associates_set_it_up(shop, va, cf):
    from .factories import ClientAssignmentFactory

    body = {"company": str(shop["company"].pk), "spreadsheet": ADDRESS, "tab": "Weekly"}
    assert post(shop["api"].as_(va), OPEN, body).status_code == 403
    ClientAssignmentFactory(tenant=shop["tenant"], user=cf.user, company=shop["company"])
    assert post(shop["api"].as_(cf), OPEN, body).status_code in (200, 409)
    client_owner = MembershipFactory(tenant=shop["tenant"], role="FCC",
                                     client_company=shop["company"])
    assert post(shop["api"].as_(client_owner), OPEN, body).status_code == 403
    assert post(shop["api"].as_(va), MAKE, {**body, "columns": []}).status_code == 403


@pytest.mark.django_db
def test_another_practice_reaches_nothing(shop, tenant_b):
    from .conftest import _member

    theirs = _member(tenant_b, "FF")
    GmailConnectionFactory(tenant=tenant_b, user=theirs.user, scopes=GRANTED)
    body = {"company": str(shop["company"].pk), "spreadsheet": ADDRESS, "tab": "Weekly"}
    assert post(shop["api"].as_(theirs), OPEN, body).status_code == 404
    assert post(shop["api"].as_(theirs), MAKE, {**body, "columns": []}).status_code == 404
    # Our own read goes through our own connection, never theirs.
    p = opened(shop)["proposal"]
    FakeSheets.calls = []
    assert make_all(shop, p, page=first_page(shop)).status_code == 201
    assert {t for t, _c, _s in FakeSheets.calls} == {shop["tenant"].pk}
    with tenant_context(tenant_b.pk):
        assert not Kpi.objects.exists() and not KpiFeed.objects.exists()
