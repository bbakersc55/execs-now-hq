"""M5 part 4: the Track PMS feed.

Against recorded answers in `tests/fixtures/track/`, shaped from Track's
public API reference (not from a live account): every measure on the menu,
by property and by assignee; paging; the connection (encrypted, owner only,
one read-only test call); the feed rules shared with Sheets (the hand wins,
nothing deleted, one notice on failure, the source on the tile's back);
rate-limit handling; and that **one company's key is never used for another
company's KPI**, nor one practice's anything for another's.
"""

from __future__ import annotations

import base64
import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from django.utils import timezone

from apps.scorecard import feeds, setup, track
from apps.scorecard.models import Kpi, KpiReading, KpiTrackFeed, TrackConnection
from apps.tenancy.context import tenant_context

from . import registry_config  # noqa: F401
from .factories import ClientCompanyFactory, MembershipFactory, TenantFactory

pytestmark = pytest.mark.django_db
FIXTURES = Path(__file__).parent / "fixtures" / "track"
B = "/api/scorecard/track/"
OCT_1, OCT_31 = date(2026, 10, 1), date(2026, 10, 31)
TODAY = date(2026, 11, 5)


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


ROUTES = {
    "/api/pms/units": ["units.json"],
    "/api/v2/pms/reservations": ["reservations_october.json"],
    "/api/channel-management/channel/reviews": ["reviews.json"],
    "/api/pms/maintenance/work-orders": ["maintenance_page1.json", "maintenance_page2.json"],
    "/api/pms/housekeeping/work-orders": ["housekeeping.json"],
}


class FakeTrack:
    """A transport serving the fixtures by path and page, applying the date
    filters the reference says Track applies, and recording every call with
    the Authorization header it carried."""

    calls: list = []

    def __init__(self, status_first=None, retry_after=None):
        self.status_first = list(status_first or [])
        self.retry_after = retry_after

    def __call__(self, url, headers):
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        FakeTrack.calls.append({"host": parsed.hostname, "path": parsed.path,
                                "auth": headers.get("Authorization"), "query": query})
        if self.status_first:
            status = self.status_first.pop(0)
            return status, ({"Retry-After": str(self.retry_after)} if self.retry_after else {}), "{}"
        pages = ROUTES[parsed.path]
        page = int(query.get("page", ["1"])[0])
        body = fixture(pages[min(page, len(pages)) - 1])
        if "bookedStart" in query:
            first = query["bookedStart"][0][:10]
            last = query["bookedEnd"][0][:10]
            rows = body["_embedded"]["reservations"]
            body["_embedded"]["reservations"] = [r for r in rows
                                                 if first <= r["bookedAt"][:10] <= last]
        return 200, {}, json.dumps(body)


def client(**kw):
    return track.TrackClient("acme.trackhs.com", "key-acme", "secret-acme",
                             transport=FakeTrack(**kw), sleep=lambda s: None)


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    FakeTrack.calls = []
    track._BUDGETS.clear()
    monkeypatch.setattr(track, "http_transport", FakeTrack())


def basic(key, secret):
    return "Basic " + base64.b64encode(f"{key}:{secret}".encode()).decode()


# ---------------------------------------------------------------- the menu, by the numbers

@pytest.mark.parametrize("measure,expected", [
    # Stays in October: 5001 (2 of its 5 nights, $400 of $1,000), 5002 (4, $800),
    # 5003 (3 of 6, $600); a cancellation and a hold don't count. 2 units x 31 nights.
    ("nights_booked", Decimal("9")), ("revenue", Decimal("1800.00")),
    ("adr", Decimal("200.00")), ("occupancy", Decimal("14.5")),
    ("revpar", Decimal("29.03")),
    # Booked in October and a stay: 5002 and 5003 (the hold and the cancellation not).
    ("bookings_created", Decimal("2")),
    # Reviewed in October: 77 (5), 78 (4), 79 (no rating); 80 was September.
    ("reviews_received", Decimal("3")), ("average_rating", Decimal("4.50")),
    # Maintenance at the end of October: 900 open and past its date, 902 open;
    # 901 (3 days) and 904 (14 days, vendor-completed) closed; 903 cancelled.
    ("maint_open", Decimal("2")), ("maint_overdue", Decimal("1")),
    ("maint_closed", Decimal("2")), ("maint_days_to_close", Decimal("8.5")),
    # Housekeeping: 300 closed in a day; 301 open and past its date; 302 open.
    ("hk_open", Decimal("2")), ("hk_overdue", Decimal("1")),
    ("hk_closed", Decimal("1")), ("hk_days_to_close", Decimal("1.0")),
])
def test_every_measure_for_a_month_in_total(measure, expected):
    assert track.value_for(measure, client(), OCT_1, OCT_31) == expected


def test_by_property_and_by_assignee():
    c = client()
    # Beach House (101): 5001's 2 nights and 5002's 4, $1,200, over 31 nights.
    assert track.value_for("nights_booked", c, OCT_1, OCT_31, unit="101") == 6
    assert track.value_for("occupancy", c, OCT_1, OCT_31, unit="101") == Decimal("19.4")
    assert track.value_for("revenue", c, OCT_1, OCT_31, unit="101") == Decimal("1200.00")
    assert track.value_for("reviews_received", c, OCT_1, OCT_31, unit="101") == 2
    assert track.value_for("average_rating", c, OCT_1, OCT_31, unit="101") == Decimal("5.00")
    # Track user 11: 900 open and overdue, 901 closed in 3 days.
    for measure, value in (("maint_open", 1), ("maint_overdue", 1), ("maint_closed", 1),
                           ("maint_days_to_close", Decimal("3.0"))):
        assert track.value_for(measure, c, OCT_1, OCT_31, user="11") == value
    # The read asked Track for the unit, not only filtered here.
    assert any(call["query"].get("unitId") == ["101"] for call in FakeTrack.calls)


def test_an_average_over_nothing_is_no_reading():
    c = client()
    november = (date(2026, 11, 10), date(2026, 11, 30))
    assert track.value_for("adr", c, *november) is None
    assert track.value_for("average_rating", c, *november) is None


def test_every_page_is_read():
    rows = client().maintenance()
    assert [r["id"] for r in rows] == [900, 901, 902, 903, 904]
    assert [c["query"]["page"] for c in FakeTrack.calls] == [["1"], ["2"]]


def test_a_429_waits_as_told_and_tries_again_and_too_many_fail_in_words():
    waits = []
    c = track.TrackClient("acme.trackhs.com", "k", "s",
                          transport=FakeTrack(status_first=[429], retry_after=7),
                          sleep=waits.append)
    assert c.test() == "Connected: 2 active units."
    assert waits == [7.0]
    c = track.TrackClient("acme.trackhs.com", "k", "s",
                          transport=FakeTrack(status_first=[429] * 5), sleep=waits.append)
    with pytest.raises(track.TrackUnavailable, match="request limit was reached"):
        c.test()


def test_the_budget_stays_inside_tracks_limit():
    now = [0.0]
    slept = []
    budget = track.Budget(sleep=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)),
                          clock=lambda: now[0])
    for _ in range(track.BUDGET):
        budget.take()
        now[0] += 0.01
    # Over the share with most of the window left: it stops and says so.
    with pytest.raises(track.TrackUnavailable, match="nearly used up"):
        budget.take()
    # Near the window's end it waits for the oldest request to age out.
    now[0] = track.WINDOW_SECONDS - 30
    budget.take()
    assert slept and 0 < slept[0] <= 60 and track.BUDGET < track.LIMIT


def test_track_refusals_are_said_in_words_and_never_carry_the_key():
    for status, words in ((401, "refused the key and secret"), (403, "server key"),
                          (500, "answered 500")):
        c = track.TrackClient("acme.trackhs.com", "key-acme", "secret-acme",
                              transport=FakeTrack(status_first=[status]),
                              sleep=lambda s: None)
        with pytest.raises(track.TrackUnavailable) as exc:
            c.test()
        assert words in str(exc.value) and "secret-acme" not in str(exc.value)


# ---------------------------------------------------------------- the company, the KPI

@pytest.fixture
def practice(seeded_tenant, ff, api):
    t = seeded_tenant
    company = ClientCompanyFactory(tenant=t, name="Alpine Stay Co.", seat_count=5)
    owner = MembershipFactory(tenant=t, role="FCC", client_company=company)
    with tenant_context(t.pk):
        card = setup.ensure(company, ff.user)
        page = card.pages.get()

        def kpi(name, kind, **extra):
            return setup.create_kpi(card, {"name": name, "kind": kind, "cadence": "monthly",
                                           "rollup": "average", "page": str(page.pk),
                                           "reading_owner": str(owner.user_id), **extra},
                                    ff.user)

        kpis = {"occupancy": kpi("Occupancy", "percent", target_value=80),
                "revenue": kpi("Revenue", "money"),
                "closed": kpi("Work orders closed", "count")}
    return {"t": t, "company": company, "owner": owner, "card": card, "kpis": kpis,
            "client": api.as_(ff)}


def connect(p, *, domain="acme.trackhs.com", key="key-acme", secret="secret-acme", who=None):
    return (who or p["client"]).put(f"{B}connection/", json.dumps({
        "company": str(p["company"].pk), "domain": domain, "key": key, "secret": secret}),
        content_type="application/json")


def set_feed(p, kpi, measure, **extra):
    return p["client"].put(f"{B}feed/", json.dumps({
        "company": str(p["company"].pk), "kpi": str(kpi.pk), "measure": measure, **extra}),
        content_type="application/json")


def test_the_connection_is_the_practice_owners_and_its_secrets_are_never_shown(
        practice, seeded_tenant, api):
    p = practice
    response = connect(p)
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["connected"] and body["domain"] == "acme.trackhs.com"
    assert body["key_last4"] == "acme" and "secret-acme" not in json.dumps(body)
    assert "key-acme" not in json.dumps(body)
    stored = TrackConnection.all_objects.get(company=p["company"])
    for ciphertext in (stored.key_ciphertext, stored.secret_ciphertext):
        assert b"acme" not in bytes(ciphertext)                 # encrypted at rest
    tested = p["client"].post(f"{B}connection/test/", json.dumps(
        {"company": str(p["company"].pk)}), content_type="application/json").json()
    assert tested["check_ok"] is True and tested["check_detail"] == "Connected: 2 active units."
    [call] = FakeTrack.calls
    assert call["path"] == "/api/pms/units" and call["auth"] == basic("key-acme", "secret-acme")
    # Associates and assistants don't connect it; a client never reaches it.
    for role in ("CF", "VA"):
        m = MembershipFactory(tenant=seeded_tenant, role=role)
        assert connect(p, who=api.as_(m)).status_code in (403, 404)
    assert connect(p, who=api.as_(p["owner"])).status_code == 403


def test_an_average_reads_the_open_month_so_far(practice):
    p = practice
    connect(p)
    occupancy = p["kpis"]["occupancy"]
    from unittest import mock

    with mock.patch("apps.scorecard.views_track._today", return_value=TODAY):
        saved = set_feed(p, occupancy, "occupancy")
    assert saved.status_code == 200, saved.content
    assert saved.json()["feed"]["read_open"] is True
    got = {r.period_start: r for r in KpiReading.all_objects.filter(kpi=occupancy)}
    november = got[date(2026, 11, 1)]
    assert november.provisional and november.source == "track"
    assert not got[OCT_1].provisional
    assert saved.json()["feed"]["text"].endswith("computed once a day, the open period so far")


def test_a_measure_reads_closed_periods_by_the_feed_rules(practice):
    p = practice
    connect(p)
    occupancy = p["kpis"]["occupancy"]
    # Wrong kind, refused in words.
    refused = set_feed(p, occupancy, "revenue")
    assert refused.status_code == 400 and "fits a KPI of kind Money" in refused.json()["measure"]
    # A month typed by hand before the feed.
    with tenant_context(p["t"].pk):
        KpiReading.objects.create(tenant=p["t"], kpi=occupancy, period_start=date(2026, 9, 1),
                                  value=Decimal("70"), entered_at=timezone.now())
    from unittest import mock

    with mock.patch("apps.scorecard.views_track._today", return_value=TODAY):
        # Closed periods only here; the open period as it goes is
        # test_scorecard_feeds.py's.
        saved = set_feed(p, occupancy, "occupancy", read_open=False)
    assert saved.status_code == 200, saved.content
    assert saved.json()["run"]["ok"] is True
    got = {r.period_start: r for r in KpiReading.all_objects.filter(kpi=occupancy)}
    assert got[OCT_1].value == Decimal("14.5") and got[OCT_1].source == "track"
    assert got[date(2026, 9, 1)].value == Decimal("70") and got[date(2026, 9, 1)].source == "hand"
    assert date(2026, 11, 1) not in got                         # November is still open
    feed = KpiTrackFeed.all_objects.get(kpi=occupancy)
    # Each later day reads the last two closed periods, and changes only its own.
    calls = len(FakeTrack.calls)
    assert feeds.run_track(feed, TODAY)["ok"]
    assert len({c["path"] for c in FakeTrack.calls[calls:]}) <= 2
    # A failed read keeps every reading and tells the reading owner once.
    before = {s: r.value for s, r in got.items()}
    failing = track.TrackClient("acme.trackhs.com", "k", "s",
                                transport=FakeTrack(status_first=[401] * 20),
                                sleep=lambda s: None)
    result = feeds.run_track(feed, TODAY, client=failing)
    assert result["ok"] is False and "refused the key and secret" in result["error"]
    feeds.run_track(feed, TODAY, client=failing)
    assert {r.period_start: r.value for r in KpiReading.all_objects.filter(kpi=occupancy)} \
        == before
    notices = p["client"].get(f"/api/scorecard/notices/?company={p['company'].pk}").json()
    owner_notices = [n for n in api_get(p, "owner") if n["kind"] == "feed"]
    assert len(owner_notices) == 1 and owner_notices[0]["kpi"] == "Occupancy"
    assert not [n for n in notices if n["kind"] == "feed"]        # the asker isn't its owner
    # The tile's back names the source.
    board = p["client"].get(f"/api/scorecard/?company={p['company'].pk}&window=last_year").json()
    tile = next(t for t in board["kpis"] if t["name"] == "Occupancy")
    assert tile["feed"]["kind"] == "track"
    assert tile["feed"]["text"] == "From Track PMS: Occupancy, all properties, computed once a day"
    # Stopping keeps the readings.
    p["client"].delete(f"{B}feed/?company={p['company'].pk}&kpi={occupancy.pk}")
    assert KpiReading.all_objects.filter(kpi=occupancy).count() == len(before)
    occupancy.refresh_from_db()
    assert occupancy.feed == Kpi.Feed.HAND


def api_get(p, who):
    from django.test import Client

    c = Client()
    c.force_login(p[who].user)
    return c.get(f"/api/scorecard/notices/?company={p['company'].pk}").json()


def test_the_picker_offers_the_menu_properties_and_assignees(practice):
    p = practice
    connect(p)
    got = p["client"].get(f"{B}options/?company={p['company'].pk}").json()
    assert {m["key"] for m in got["measures"]} == set(track.MEASURES)
    assert [u["name"] for u in got["units"]] == ["Beach House", "Lake Cabin"]
    assert {a["id"] for a in got["assignees"]} == {"11", "12", "21", "22"}


def test_a_per_person_kpi_is_refused(practice):
    p = practice
    connect(p)
    with tenant_context(p["t"].pk):
        rep = MembershipFactory(tenant=p["t"], role="ECC", client_company=p["company"])
        per = setup.create_kpi(p["card"], {"name": "Closed per person", "kind": "count",
                                           "cadence": "monthly", "per_person": True,
                                           "people": [str(rep.pk)],
                                           "page": str(p["card"].pages.get().pk)},
                               p["owner"].user)
    assert "reading per person" in set_feed(p, per, "maint_closed").json()["measure"]


# ---------------------------------------------------------------- isolation

def test_one_companys_key_is_never_used_for_another_companys_kpi(practice, ff, api):
    p = practice
    connect(p)
    other = ClientCompanyFactory(tenant=p["t"], name="Summit Lodges", seat_count=3)
    p["client"].put(f"{B}connection/", json.dumps({
        "company": str(other.pk), "domain": "summit.trackhs.com", "key": "key-summit",
        "secret": "secret-summit"}), content_type="application/json")
    with tenant_context(p["t"].pk):
        card = setup.ensure(other, ff.user)
        theirs = setup.create_kpi(card, {"name": "Summit revenue", "kind": "money",
                                         "cadence": "monthly", "page": str(card.pages.get().pk)},
                                  ff.user)
    from unittest import mock

    with mock.patch("apps.scorecard.views_track._today", return_value=TODAY):
        set_feed(p, p["kpis"]["revenue"], "revenue")
        p["client"].put(f"{B}feed/", json.dumps({"company": str(other.pk), "kpi": str(theirs.pk),
                                                 "measure": "revenue"}),
                        content_type="application/json")
    by_host = {}
    for call in FakeTrack.calls:
        by_host.setdefault(call["host"], set()).add(call["auth"])
    assert by_host == {"acme.trackhs.com": {basic("key-acme", "secret-acme")},
                       "summit.trackhs.com": {basic("key-summit", "secret-summit")}}
    # A KPI of one company can't be pointed at through another's route.
    crossed = p["client"].put(f"{B}feed/", json.dumps({
        "company": str(p["company"].pk), "kpi": str(theirs.pk), "measure": "revenue"}),
        content_type="application/json")
    assert crossed.status_code == 404
    # And the daily pass, run for one company's feed, reads with that company's key only.
    FakeTrack.calls = []
    feed = KpiTrackFeed.all_objects.get(kpi=theirs)
    feeds.run_track(feed, TODAY)
    assert {c["auth"] for c in FakeTrack.calls} == {basic("key-summit", "secret-summit")}


def test_another_practice_never_reaches_a_connection_or_a_feed(practice):
    from apps.crm.seed import seed_tenant
    from django.test import Client

    p = practice
    connect(p)
    other = TenantFactory()
    seed_tenant(other)
    b = Client()
    b.force_login(MembershipFactory(tenant=other, role="FF").user)
    q = f"?company={p['company'].pk}"
    assert b.get(f"{B}connection/{q}").status_code == 404
    assert b.post(f"{B}connection/test/", json.dumps({"company": str(p["company"].pk)}),
                  content_type="application/json").status_code == 404
    assert b.get(f"{B}options/{q}").status_code == 404
    assert b.get(f"{B}feed/{q}&kpi={p['kpis']['revenue'].pk}").status_code == 404
    # The daily pass for B reads nothing of A's.
    FakeTrack.calls = []
    assert feeds.run_due_track(other.pk, TODAY) == {"ran": 0, "failed": 0}
    assert FakeTrack.calls == []
    # A's key is on A's company's row alone.
    assert TrackConnection.all_objects.filter(tenant=other).count() == 0


def test_the_demo_never_connects(practice, settings, monkeypatch):
    from config import environment

    monkeypatch.setattr(environment, "is_demo", lambda: True)
    response = connect(practice)
    assert response.status_code == 409 and "never connects to a Track account" in \
        response.json()["detail"]
