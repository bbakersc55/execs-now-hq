"""M5 part 5: the HubSpot feed.

Against recorded answers in `tests/fixtures/hubspot/`, shaped from HubSpot's
public API reference (version 2026-09), not from a live account: every
measure on the menu, in total and by owner, pipeline value by stage; the
practice's time zone at a period's edges; search paging and its limits; the
connection (encrypted, owner only, one read-only test call); the feed rules
shared with Sheets and Track; rate-limit handling; and that **one company's
token is never used for another company's KPI**, nor one practice's anything
for another's.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

import pytest
from django.utils import timezone

from apps.scorecard import feeds, hubspot, setup
from apps.scorecard.models import (HubSpotConnection, Kpi, KpiHubSpotFeed, KpiReading,
                                   KpiTrackFeed)
from apps.tenancy.context import tenant_context

from . import registry_config  # noqa: F401
from .factories import ClientCompanyFactory, MembershipFactory, TenantFactory

pytestmark = pytest.mark.django_db
FIXTURES = Path(__file__).parent / "fixtures" / "hubspot"
B = "/api/scorecard/hubspot/"
OCT_1, OCT_31 = date(2026, 10, 1), date(2026, 10, 31)
TODAY = date(2026, 11, 1)
DENVER = "America/Denver"
TOKEN_A = "pat-na1-aaaaaaaa-0000-4000-8000-00000000acme"
TOKEN_B = "pat-na1-bbbbbbbb-0000-4000-8000-0000000summ"


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


def _ms(text):
    return int(datetime.fromisoformat(text.replace("Z", "+00:00"))
               .astimezone(dt_timezone.utc).timestamp() * 1000)


def _matches(record, f):
    value = (record.get("properties") or {}).get(f["propertyName"])
    op = f["operator"]
    if op == "IN":
        return value is not None and str(value) in f["values"]
    if op == "EQ":
        return value is not None and str(value) == f["value"]
    if value is None:
        return False
    have, want = _ms(value), int(f["value"])
    return {"GTE": have >= want, "LT": have < want, "LTE": have <= want,
            "GT": have > want}[op]


class FakeHubSpot:
    """A transport serving the fixtures: the pipelines and the owners (paged)
    as answered, and every search by applying its filters to the recorded
    records and paging them three at a time, as the reference says search
    does. It holds every request to the reference's documented limits and
    records each call with the Authorization header it carried."""

    calls: list = []
    PAGE = 3

    def __init__(self, status_first=None, body_first=None, headers=None):
        self.status_first = list(status_first or [])
        self.body_first = body_first
        self.headers = headers or {}

    def __call__(self, method, url, headers, body):
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        sent = json.loads(body) if body else None
        FakeHubSpot.calls.append({"method": method, "path": parsed.path, "query": query,
                                  "auth": headers.get("Authorization"), "body": sent})
        if self.status_first:
            status = self.status_first.pop(0)
            return status, {}, json.dumps(self.body_first or {})
        if parsed.path == "/crm/pipelines/2026-09/0-3":
            return 200, self.headers, json.dumps(fixture("pipelines.json"))
        if parsed.path == "/crm/owners/2026-09":
            assert int(query["limit"][0]) <= 100
            page = "owners_page2.json" if query.get("after") else "owners_page1.json"
            return 200, self.headers, json.dumps(fixture(page))
        prefix, _, rest = parsed.path.partition("/crm/objects/2026-09/")
        obj, _, tail = rest.partition("/")
        assert method == "POST" and prefix == "" and tail == "search", parsed.path
        groups = sent["filterGroups"]
        assert len(groups) <= 5 and all(len(g["filters"]) <= 6 for g in groups)
        assert 1 <= sent["limit"] <= 200
        rows = [r for r in fixture(f"{obj}.json")
                if any(all(_matches(r, f) for f in g["filters"]) for g in groups)]
        start = int(sent.get("after") or 0)
        size = min(sent["limit"], self.PAGE)
        page = rows[start:start + size]
        answer = {"total": len(rows), "results": page}
        if start + size < len(rows):
            answer["paging"] = {"next": {"after": str(start + size), "link": "?after="}}
        return 200, {}, json.dumps(answer)


def client(**kw):
    return hubspot.HubSpotClient(TOKEN_A, transport=FakeHubSpot(**kw), sleep=lambda s: None)


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    FakeHubSpot.calls = []
    hubspot._BUDGETS.clear()
    monkeypatch.setattr(hubspot, "http_transport", FakeHubSpot())


def bearer(token):
    return f"Bearer {token}"


# ---------------------------------------------------------------- the menu, by the numbers

@pytest.mark.parametrize("measure,expected", [
    # Created in October in Denver: 9001, 9002, 9004, 9008. 9006 was created
    # at 11:30 pm on September 30 there, October 1 in UTC.
    ("deals_created", Decimal("4")),
    # Closed in October in a 100% stage: 9003 (Sales), and 9005 (Renewals),
    # closed at 11:30 pm on October 31 in Denver. 9007 closed in September.
    ("deals_won", Decimal("2")),
    # A 0% stage: 9004 ("Closed lost", isClosed "false" as the reference shows).
    ("deals_lost", Decimal("1")),
    ("win_rate", Decimal("66.7")),
    # Open stages of both pipelines (the archived one not): 1,000 + 2,500.50 +
    # 800 + a deal with no amount.
    ("pipeline_value", Decimal("4300.50")),
    # 101, 102 and 103 (9 pm on October 31 in Denver); 104 was September.
    ("new_contacts", Decimal("3")),
    ("calls_logged", Decimal("3")), ("emails_logged", Decimal("2")),
    ("meetings_logged", Decimal("1")),
])
def test_every_measure_for_a_month_in_total(measure, expected):
    assert hubspot.value_for(measure, client(), OCT_1, OCT_31, zone=DENVER) == expected


def test_a_period_closes_at_the_practices_midnight():
    assert hubspot.value_for("deals_created", client(), OCT_1, OCT_31, zone="UTC") == 5
    start, end = hubspot.window_ms(OCT_1, OCT_31, DENVER)
    assert start == _ms("2026-10-01T06:00:00Z") and end == _ms("2026-11-01T06:00:00Z")


def test_by_owner_and_pipeline_value_by_stage():
    c = client()
    for measure, value in (("deals_created", 1), ("deals_won", 1), ("deals_lost", 0),
                           ("win_rate", Decimal("100.0")), ("new_contacts", 2),
                           ("calls_logged", 2), ("emails_logged", 1), ("meetings_logged", 1),
                           ("pipeline_value", Decimal("1800.00"))):
        assert hubspot.value_for(measure, c, OCT_1, OCT_31, zone=DENVER, owner="501") == value
    assert hubspot.value_for("pipeline_value", c, OCT_1, OCT_31, zone=DENVER,
                             stage="qualifiedtobuy") == Decimal("2500.50")
    # The owner is asked of HubSpot, not only filtered here.
    owners = [f for call in FakeHubSpot.calls if call["body"]
              for f in call["body"]["filterGroups"][0]["filters"]
              if f["propertyName"] == "hubspot_owner_id"]
    assert owners and all(f == {"propertyName": "hubspot_owner_id", "operator": "EQ",
                                "value": "501"} for f in owners)


def test_counts_are_one_request_each_and_pipeline_value_pages():
    c = client()
    hubspot.value_for("calls_logged", c, OCT_1, OCT_31, zone=DENVER)
    [call] = FakeHubSpot.calls
    assert call["body"]["limit"] == 1 and call["method"] == "POST"
    FakeHubSpot.calls = []
    hubspot.value_for("pipeline_value", c, OCT_1, OCT_31, zone=DENVER)
    searches = [x for x in FakeHubSpot.calls if x["body"]]
    assert [x["body"].get("after") for x in searches] == [None, "3"]   # 4 open deals, 3 a page


def test_nothing_closed_is_no_win_rate():
    november = (date(2026, 11, 10), date(2026, 11, 30))
    assert hubspot.value_for("win_rate", client(), *november, zone=DENVER) is None


def test_stages_by_probability_and_the_picker():
    sets = hubspot.stage_sets(fixture("pipelines.json")["results"])
    assert sets["won"] == {"closedwon", "1002"} and sets["lost"] == {"closedlost", "1003"}
    assert "1004" not in sets["open"]                                 # archived
    got = hubspot.options(client())
    assert [o["name"] for o in got["owners"]] == ["Ana Ruiz", "Ben Ode"]   # 503 archived
    assert [s["name"] for s in got["stages"]] == [
        "Sales Pipeline: Appointment scheduled", "Sales Pipeline: Qualified to buy",
        "Sales Pipeline: Presentation scheduled", "Renewals: Renewal open"]
    assert [c["query"].get("after") for c in FakeHubSpot.calls
            if c["path"] == "/crm/owners/2026-09"] == [None, ["2"]]


def test_a_stage_no_longer_open_is_refused_in_words():
    with pytest.raises(hubspot.HubSpotRefused, match="no longer an open stage"):
        hubspot.value_for("pipeline_value", client(), OCT_1, OCT_31, stage="closedwon")


def test_more_than_search_will_page_is_refused_in_words(monkeypatch):
    monkeypatch.setattr(hubspot, "MOST_RESULTS", 3)
    with pytest.raises(hubspot.HubSpotRefused, match="more than 3"):
        hubspot.value_for("pipeline_value", client(), OCT_1, OCT_31)


# ---------------------------------------------------------------- the rate limit

def test_a_ten_second_429_waits_and_tries_again():
    waits = []
    c = hubspot.HubSpotClient(TOKEN_A, transport=FakeHubSpot(
        status_first=[429], body_first=fixture("rate_limit_ten_secondly.json")),
        sleep=waits.append)
    assert c.test() == "Connected: 2 deal pipelines."
    assert waits == [10.0]
    # A search waits a second: its own limit is per second.
    waits.clear()
    c = hubspot.HubSpotClient(TOKEN_B, transport=FakeHubSpot(
        status_first=[429], body_first=fixture("rate_limit_ten_secondly.json")),
        sleep=waits.append)
    c.count("calls", [])
    assert 1.0 in waits
    c = hubspot.HubSpotClient(TOKEN_A, transport=FakeHubSpot(status_first=[429] * 5),
                              sleep=lambda s: None)
    with pytest.raises(hubspot.HubSpotUnavailable, match="request limit was reached"):
        c.test()


def test_the_daily_limit_stops_at_once_and_leaves_the_client_its_last_share():
    c = hubspot.HubSpotClient(TOKEN_A, transport=FakeHubSpot(
        status_first=[429, 429], body_first=fixture("rate_limit_daily.json")),
        sleep=lambda s: None)
    with pytest.raises(hubspot.HubSpotUnavailable, match="daily API limit"):
        c.test()
    assert len(FakeHubSpot.calls) == 1                                # no retry
    low = {"X-HubSpot-RateLimit-Daily": "250000",
           "X-HubSpot-RateLimit-Daily-Remaining": "9000"}
    c = hubspot.HubSpotClient(TOKEN_B, transport=FakeHubSpot(headers=low), sleep=lambda s: None)
    with pytest.raises(hubspot.HubSpotUnavailable, match="nearly used up"):
        c.test()


def test_a_nearly_spent_ten_seconds_is_waited_out():
    waits = []
    c = hubspot.HubSpotClient(TOKEN_A, transport=FakeHubSpot(headers={
        "X-HubSpot-RateLimit-Max": "100", "X-HubSpot-RateLimit-Remaining": "1",
        "X-HubSpot-RateLimit-Interval-Milliseconds": "10000"}), sleep=waits.append)
    c.test()
    assert waits == [10.0]


def test_the_budget_keeps_to_its_share_and_spaces_searches():
    now = [0.0]
    slept = []

    def sleep(s):
        slept.append(s)
        now[0] += s

    budget = hubspot.Budget(sleep=sleep, clock=lambda: now[0])
    for _ in range(hubspot.BUDGET):
        budget.take()
    budget.take()
    assert slept and slept[-1] == pytest.approx(hubspot.WINDOW_SECONDS)
    assert hubspot.BUDGET < hubspot.LIMIT
    slept.clear()
    budget.take(search=True)
    budget.take(search=True)
    assert slept == [pytest.approx(hubspot.SEARCH_GAP)]               # five a second at most


def test_refusals_are_said_in_words_and_never_carry_the_token():
    for status, words in ((401, "refused the access token"), (403, "crm.objects.deals.read"),
                          (500, "answered 500")):
        c = hubspot.HubSpotClient(TOKEN_A, transport=FakeHubSpot(status_first=[status]),
                                  sleep=lambda s: None)
        with pytest.raises(hubspot.HubSpotUnavailable) as exc:
            c.test()
        assert words in str(exc.value) and TOKEN_A not in str(exc.value)


# ---------------------------------------------------------------- the company, the KPI

@pytest.fixture
def practice(seeded_tenant, ff, api):
    t = seeded_tenant
    company = ClientCompanyFactory(tenant=t, name="Alpine Sales Co.", seat_count=5)
    owner = MembershipFactory(tenant=t, role="FCC", client_company=company)
    with tenant_context(t.pk):
        card = setup.ensure(company, ff.user)
        page = card.pages.get()

        def kpi(name, kind, **extra):
            return setup.create_kpi(card, {"name": name, "kind": kind, "cadence": "monthly",
                                           "rollup": "sum", "page": str(page.pk),
                                           "reading_owner": str(owner.user_id), **extra},
                                    ff.user)

        kpis = {"won": kpi("Deals won", "count", target_value=5),
                "rate": kpi("Win rate", "percent"),
                "pipeline": kpi("Pipeline", "money")}
    return {"t": t, "company": company, "owner": owner, "card": card, "kpis": kpis,
            "client": api.as_(ff)}


def connect(p, *, token=TOKEN_A, who=None, company=None):
    return (who or p["client"]).put(f"{B}connection/", json.dumps({
        "company": str((company or p["company"]).pk), "token": token}),
        content_type="application/json")


def set_feed(p, kpi, measure, company=None, **extra):
    with mock.patch("apps.scorecard.views_hubspot._today", return_value=TODAY):
        return p["client"].put(f"{B}feed/", json.dumps({
            "company": str((company or p["company"]).pk), "kpi": str(kpi.pk),
            "measure": measure, **extra}), content_type="application/json")


def test_the_connection_is_the_practice_owners_and_its_token_is_never_shown(
        practice, seeded_tenant, api):
    p = practice
    assert connect(p, token="not a token").status_code == 400
    response = connect(p)
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["connected"] and body["token_last4"] == "acme"
    assert TOKEN_A not in json.dumps(body)
    stored = HubSpotConnection.all_objects.get(company=p["company"])
    assert TOKEN_A.encode() not in bytes(stored.token_ciphertext)    # encrypted at rest
    tested = p["client"].post(f"{B}connection/test/", json.dumps(
        {"company": str(p["company"].pk)}), content_type="application/json").json()
    assert tested["check_ok"] is True and tested["check_detail"] == "Connected: 2 deal pipelines."
    [call] = FakeHubSpot.calls                                        # one read-only call
    assert call["method"] == "GET" and call["path"] == "/crm/pipelines/2026-09/0-3"
    assert call["auth"] == bearer(TOKEN_A)
    # Associates and assistants don't connect it; a client never reaches it.
    for role in ("CF", "VA"):
        m = MembershipFactory(tenant=seeded_tenant, role=role)
        assert connect(p, who=api.as_(m)).status_code in (403, 404)
    assert connect(p, who=api.as_(p["owner"])).status_code == 403
    # Disconnecting takes the token with it.
    assert p["client"].delete(f"{B}connection/?company={p['company'].pk}").status_code == 200
    assert not HubSpotConnection.all_objects.filter(company=p["company"]).exists()


def test_a_measure_reads_closed_periods_by_the_feed_rules(practice):
    p = practice
    connect(p)
    won = p["kpis"]["won"]
    refused = set_feed(p, won, "pipeline_value")
    assert refused.status_code == 400 and "fits a KPI of kind Money" in refused.json()["measure"]
    # A month typed by hand before the feed.
    with tenant_context(p["t"].pk):
        KpiReading.objects.create(tenant=p["t"], kpi=won, period_start=date(2026, 9, 1),
                                  value=Decimal("7"), entered_at=timezone.now())
    saved = set_feed(p, won, "deals_won")
    assert saved.status_code == 200, saved.content
    assert saved.json()["run"]["ok"] is True
    got = {r.period_start: r for r in KpiReading.all_objects.filter(kpi=won)}
    assert got[OCT_1].value == 2 and got[OCT_1].source == "hubspot"
    assert got[date(2026, 9, 1)].value == 7 and got[date(2026, 9, 1)].source == "hand"
    assert date(2026, 11, 1) not in got                               # November is open
    feed = KpiHubSpotFeed.all_objects.get(kpi=won)
    # A failed read keeps every reading and tells the reading owner once.
    before = {s: r.value for s, r in got.items()}
    failing = hubspot.HubSpotClient(TOKEN_A, transport=FakeHubSpot(status_first=[401] * 20),
                                    sleep=lambda s: None)
    result = feeds.run_hubspot(feed, TODAY, client=failing)
    assert result["ok"] is False and "refused the access token" in result["error"]
    feeds.run_hubspot(feed, TODAY, client=failing)
    assert {r.period_start: r.value for r in KpiReading.all_objects.filter(kpi=won)} == before
    owner_notices = [n for n in notices(p, "owner") if n["kind"] == "feed"]
    assert len(owner_notices) == 1 and owner_notices[0]["kpi"] == "Deals won"
    # The tile's back names the source.
    board = p["client"].get(f"/api/scorecard/?company={p['company'].pk}&window=last_year").json()
    tile = next(t for t in board["kpis"] if t["name"] == "Deals won")
    assert tile["feed"]["kind"] == "hubspot"
    assert tile["feed"]["text"] == "From HubSpot: Deals won, every owner, computed once a day"
    # Stopping keeps the readings.
    p["client"].delete(f"{B}feed/?company={p['company'].pk}&kpi={won.pk}")
    assert KpiReading.all_objects.filter(kpi=won).count() == len(before)
    won.refresh_from_db()
    assert won.feed == Kpi.Feed.HAND


def notices(p, who):
    from django.test import Client

    c = Client()
    c.force_login(p[who].user)
    return c.get(f"/api/scorecard/notices/?company={p['company'].pk}").json()


def test_pipeline_value_is_read_at_the_close_and_kept(practice):
    p = practice
    connect(p)
    pipeline = p["kpis"]["pipeline"]
    saved = set_feed(p, pipeline, "pipeline_value", stage_id="qualifiedtobuy",
                     stage_name="Qualified to buy", owner_id="502", owner_name="Ben Ode")
    assert saved.status_code == 200, saved.content
    [reading] = KpiReading.all_objects.filter(kpi=pipeline)
    assert reading.period_start == OCT_1 and reading.value == Decimal("2500.50")
    assert saved.json()["feed"]["text"] == ("From HubSpot: Pipeline value, Qualified to buy, "
                                            "owner Ben Ode, read at each period's close")
    # A later read the same period doesn't move it: the pipeline has moved on.
    feed = KpiHubSpotFeed.all_objects.get(kpi=pipeline)
    with mock.patch.object(hubspot, "value_for", return_value=Decimal("1")):
        assert feeds.run_hubspot(feed, date(2026, 11, 2))["ok"]
    assert KpiReading.all_objects.get(kpi=pipeline).value == Decimal("2500.50")
    # Set mid-period, there is no close to read yet: nothing is written.
    rate = p["kpis"]["rate"]
    KpiHubSpotFeed.all_objects.create(tenant=p["t"], kpi=rate, measure="pipeline_value")
    assert hubspot.plan_for(KpiHubSpotFeed.all_objects.get(kpi=rate), client(),
                            date(2026, 11, 20)) == {}


def test_pipeline_value_read_as_it_goes_is_replaced_at_the_close_then_kept(practice):
    p = practice
    connect(p)
    pipeline = p["kpis"]["pipeline"]
    assert set_feed(p, pipeline, "pipeline_value", read_open=True).status_code == 200
    feed = KpiHubSpotFeed.all_objects.get(kpi=pipeline)
    nov_1 = date(2026, 11, 1)

    def read(day, value):
        with mock.patch.object(hubspot, "value_for", return_value=Decimal(value)):
            assert feeds.run_hubspot(feed, day)["ok"]
        return {r.period_start: r for r in KpiReading.all_objects.filter(kpi=pipeline)}

    got = read(date(2026, 11, 20), "100")
    assert got[nov_1].value == Decimal("100") and got[nov_1].provisional
    got = read(date(2026, 11, 25), "150")
    assert got[nov_1].value == Decimal("150") and got[nov_1].provisional
    # The read at the close replaces the "so far"; later reads keep it.
    got = read(date(2026, 12, 1), "175")
    assert got[nov_1].value == Decimal("175") and not got[nov_1].provisional
    assert got[date(2026, 12, 1)].provisional
    got = read(date(2026, 12, 2), "1")
    assert got[nov_1].value == Decimal("175")
    assert feeds.hubspot_source_text(feed).endswith("read at each period's close, "
                                                    "the open period so far")


def test_a_stage_is_only_for_pipeline_value(practice):
    p = practice
    connect(p)
    set_feed(p, p["kpis"]["won"], "deals_won", stage_id="qualifiedtobuy")
    assert KpiHubSpotFeed.all_objects.get(kpi=p["kpis"]["won"]).stage_id == ""


def test_the_picker_offers_the_menu_owners_and_open_stages(practice):
    p = practice
    connect(p)
    got = p["client"].get(f"{B}options/?company={p['company'].pk}").json()
    assert {m["key"] for m in got["measures"]} == set(hubspot.MEASURES)
    assert [o["id"] for o in got["owners"]] == ["501", "502"]
    assert "qualifiedtobuy" in {s["id"] for s in got["stages"]}
    assert "closedwon" not in {s["id"] for s in got["stages"]}


def test_a_per_person_kpi_is_refused(practice):
    p = practice
    connect(p)
    with tenant_context(p["t"].pk):
        rep = MembershipFactory(tenant=p["t"], role="ECC", client_company=p["company"])
        per = setup.create_kpi(p["card"], {"name": "Calls per person", "kind": "count",
                                           "cadence": "monthly", "per_person": True,
                                           "people": [str(rep.pk)],
                                           "page": str(p["card"].pages.get().pk)},
                               p["owner"].user)
    assert "reading per person" in set_feed(p, per, "calls_logged").json()["measure"]


def test_a_kpi_has_one_feed(practice):
    p = practice
    connect(p)
    won = p["kpis"]["won"]
    track = KpiTrackFeed.all_objects.create(tenant=p["t"], kpi=won, measure="maint_closed")
    set_feed(p, won, "deals_won")
    track.refresh_from_db()
    assert track.active is False
    assert KpiHubSpotFeed.all_objects.get(kpi=won).active


# ---------------------------------------------------------------- isolation

def test_one_companys_token_is_never_used_for_another_companys_kpi(practice, ff):
    p = practice
    connect(p)
    other = ClientCompanyFactory(tenant=p["t"], name="Summit Lodges", seat_count=3)
    connect(p, token=TOKEN_B, company=other)
    with tenant_context(p["t"].pk):
        card = setup.ensure(other, ff.user)
        theirs = setup.create_kpi(card, {"name": "Summit calls", "kind": "count",
                                         "cadence": "monthly", "page": str(card.pages.get().pk)},
                                  ff.user)
    FakeHubSpot.calls = []
    set_feed(p, p["kpis"]["won"], "deals_won")
    ours = {c["auth"] for c in FakeHubSpot.calls}
    FakeHubSpot.calls = []
    set_feed(p, theirs, "calls_logged", company=other)
    assert ours == {bearer(TOKEN_A)}
    assert {c["auth"] for c in FakeHubSpot.calls} == {bearer(TOKEN_B)}
    # A KPI of one company can't be pointed at through another's route.
    crossed = set_feed(p, theirs, "calls_logged")
    assert crossed.status_code == 404
    # The daily pass reads each feed with its own company's token only.
    FakeHubSpot.calls = []
    feeds.run_hubspot(KpiHubSpotFeed.all_objects.get(kpi=theirs), TODAY)
    assert {c["auth"] for c in FakeHubSpot.calls} == {bearer(TOKEN_B)}
    # And each company keeps its own rate-limit budget.
    assert {f"company:{p['company'].pk}", f"company:{other.pk}"} <= set(hubspot._BUDGETS)


def test_another_practice_never_reaches_a_connection_or_a_feed(practice):
    from django.test import Client

    from apps.crm.seed import seed_tenant

    p = practice
    connect(p)
    other = TenantFactory()
    seed_tenant(other)
    b = Client()
    b.force_login(MembershipFactory(tenant=other, role="FF").user)
    q = f"?company={p['company'].pk}"
    assert b.get(f"{B}connection/{q}").status_code == 404
    assert b.put(f"{B}connection/", json.dumps({"company": str(p["company"].pk),
                                                "token": TOKEN_B}),
                 content_type="application/json").status_code == 404
    assert b.post(f"{B}connection/test/", json.dumps({"company": str(p["company"].pk)}),
                  content_type="application/json").status_code == 404
    assert b.get(f"{B}options/{q}").status_code == 404
    assert b.get(f"{B}feed/{q}&kpi={p['kpis']['won'].pk}").status_code == 404
    # The daily pass for B reads nothing of A's.
    FakeHubSpot.calls = []
    assert feeds.run_due_hubspot(other.pk, TODAY) == {"ran": 0, "failed": 0}
    assert FakeHubSpot.calls == []
    assert HubSpotConnection.all_objects.filter(tenant=other).count() == 0


def test_the_daily_pass_runs_each_feed_once_a_day(practice):
    p = practice
    connect(p)
    set_feed(p, p["kpis"]["won"], "deals_won")
    later = timezone.now() + timezone.timedelta(hours=1)
    assert feeds.run_due_hubspot(p["t"].pk, TODAY, now=later) == {"ran": 0, "failed": 0}
    tomorrow = timezone.now() + timezone.timedelta(hours=24)
    assert feeds.run_due_hubspot(p["t"].pk, TODAY, now=tomorrow) == {"ran": 1, "failed": 0}


def test_the_demo_never_connects(practice, monkeypatch):
    from config import environment

    monkeypatch.setattr(environment, "is_demo", lambda: True)
    response = connect(practice)
    assert response.status_code == 409 and "never connects to a HubSpot account" in \
        response.json()["detail"]
    with pytest.raises(hubspot.HubSpotUnavailable, match="never connects"):
        feeds.hubspot_client(practice["company"])
