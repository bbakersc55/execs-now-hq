"""Google reviews for the scorecard (`docs/google_reviews_feed.md`), with a
fake Google: the consent and the connection (encrypted, owner only), the
account and location lists, paging until stored reviews are reached,
de-duplication, updated reviews, every measure, the feed rules, practice
isolation, roles, the not-yet-approved state, and the demo's refusal.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest import mock
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import pytest
from django.test import Client

from apps.scorecard import feeds, google_reviews, setup
from apps.scorecard.models import (
    GoogleReview, GoogleReviewsConnection, Kpi, KpiReading, KpiReviewsFeed,
)
from apps.tenancy.context import tenant_context

from . import registry_config  # noqa: F401
from .factories import ClientCompanyFactory, MembershipFactory, TenantFactory

pytestmark = pytest.mark.django_db
B = "/api/scorecard/reviews/"
TODAY = date(2026, 11, 4)
STAR_WORDS = {1: "ONE", 2: "TWO", 3: "THREE", 4: "FOUR", 5: "FIVE"}


def review(n, stars=5, created="2026-10-20T15:00:00Z", updated=None, reply=None,
           comment=None, name=None):
    out = {"reviewId": f"r{n}", "name": f"accounts/1/locations/2/reviews/r{n}",
           "reviewer": {"displayName": name or f"Guest {n}"},
           "starRating": STAR_WORDS[stars], "comment": comment or f"Review {n}",
           "createTime": created, "updateTime": updated or created}
    if reply:
        out["reviewReply"] = {"comment": "Thank you!", "updateTime": reply}
    return out


class FakeGoogle:
    """Google's three APIs, answering from `pages` (each a list of reviews,
    newest change first), and recording every call."""

    def __init__(self, pages=None, status=200, body=None):
        self.pages = pages or []
        self.status, self.body = status, body
        self.calls = []

    def __call__(self, url, headers):
        parsed = urlparse(url)
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        self.calls.append({"host": parsed.hostname, "path": parsed.path, "query": query,
                           "auth": headers.get("Authorization")})
        if self.status != 200:
            return self.status, self.body or "{}"
        if parsed.hostname == "mybusinessaccountmanagement.googleapis.com":
            return 200, json.dumps({"accounts": [
                {"name": "accounts/1", "accountName": "Stark Tool & Die", "type": "LOCATION_GROUP"}]})
        if parsed.hostname == "mybusinessbusinessinformation.googleapis.com":
            return 200, json.dumps({"locations": [
                {"name": "locations/2", "title": "Stark Tool & Die, Denver",
                 "storefrontAddress": {"addressLines": ["1 Forge Way"], "locality": "Denver"}}]})
        page = int(query.get("pageToken", "0"))
        body = {"reviews": self.pages[page] if page < len(self.pages) else [],
                "averageRating": 4.6, "totalReviewCount": sum(len(p) for p in self.pages)}
        if page + 1 < len(self.pages):
            body["nextPageToken"] = str(page + 1)
        return 200, json.dumps(body)

    def review_reads(self):
        return [c for c in self.calls if c["path"].endswith("/reviews")]


def token_post(url, data):
    assert data["grant_type"] == "refresh_token" and data["refresh_token"] == "refresh-stark"
    return 200, json.dumps({"access_token": "access-stark"})


@pytest.fixture
def google(monkeypatch):
    fake = FakeGoogle()
    monkeypatch.setattr(google_reviews, "http_transport", fake)
    monkeypatch.setattr(google_reviews, "http_post_form", token_post)
    return fake


@pytest.fixture
def practice(seeded_tenant, ff, api):
    t = seeded_tenant
    company = ClientCompanyFactory(tenant=t, name="Stark Tool & Die", seat_count=5)
    owner = MembershipFactory(tenant=t, role="FCC", client_company=company)
    with tenant_context(t.pk):
        card = setup.ensure(company, ff.user)
        page = card.pages.get()

        def kpi(name, kind, cadence="monthly", **extra):
            return setup.create_kpi(card, {"name": name, "kind": kind, "cadence": cadence,
                                           "rollup": "sum", "page": str(page.pk),
                                           "reading_owner": str(ff.user_id), **extra},
                                    ff.user)

        kpis = {"new": kpi("New Google reviews", "count"),
                "rating": kpi("Google rating", "rating", rating_scale=5, rollup="average"),
                "share": kpi("Five-star share", "percent", rollup="average"),
                "reply": kpi("Days to reply", "duration", rollup="average"),
                "money": kpi("Revenue", "money")}
    return {"t": t, "company": company, "owner": owner, "card": card, "kpis": kpis,
            "client": api.as_(ff), "ff": ff}


def connected(p, *, location=True):
    """A connection as the consent and the chosen location leave it."""
    from apps.crm.services import secrets

    with tenant_context(p["t"].pk):
        return GoogleReviewsConnection.objects.create(
            tenant=p["t"], company=p["company"], google_email="manager@stark.example",
            token_ciphertext=secrets.encrypt("refresh-stark"),
            account_name="accounts/1" if location else "",
            location_name="locations/2" if location else "",
            location_title="Stark Tool & Die, Denver" if location else "")


def sync(connection):
    with tenant_context(connection.tenant_id):
        return google_reviews.sync(connection, google_reviews.client_for(connection))


def stored(connection):
    with tenant_context(connection.tenant_id):
        return {r.review_id: r for r in GoogleReview.objects.filter(connection=connection)}


def put(client, url, body):
    return client.put(url, json.dumps(body), content_type="application/json")


def post(client, url, body):
    return client.post(url, json.dumps(body), content_type="application/json")


# ------------------------------------------------------------ connecting

def test_the_consent_asks_for_business_manage_alone_and_stores_the_token_encrypted(
        practice, google):
    p = practice
    started = post(p["client"], f"{B}connection/start/", {"company": str(p["company"].pk)})
    assert started.status_code == 200, started.content
    url = urlparse(started.json()["url"])
    q = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert q["scope"] == "openid email https://www.googleapis.com/auth/business.manage"
    assert q["access_type"] == "offline" and q["redirect_uri"].endswith("/accounts/gmail/callback")
    assert "include_granted_scopes" not in q
    with mock.patch("apps.crm.services.gmail_oauth.exchange_code", return_value={
            "access_token": "a", "refresh_token": "refresh-stark",
            "scope": "openid email https://www.googleapis.com/auth/business.manage"}), \
            mock.patch("apps.crm.services.gmail_oauth.account_email",
                       return_value="manager@stark.example"):
        back = p["client"].get("/accounts/gmail/callback", {"state": q["state"], "code": "c"})
    assert back.status_code == 302 and f"/companies/{p['company'].pk}?reviews_connected=" \
        in back["Location"]
    with tenant_context(p["t"].pk):
        row = GoogleReviewsConnection.objects.get(company=p["company"])
    assert b"refresh-stark" not in bytes(row.token_ciphertext)
    state = p["client"].get(f"{B}connection/?company={p['company'].pk}").json()
    assert state["connected"] and not state["chosen"] and "refresh" not in json.dumps(state)
    # The account and location come from Google's lists; choosing reads at once.
    google.pages = [[review(1), review(2, stars=4)]]
    choices = p["client"].get(f"{B}connection/choices/?company={p['company'].pk}"
                              "&account=accounts/1").json()
    assert choices["accounts"][0]["name"] == "accounts/1"
    assert choices["locations"] == [{"name": "locations/2", "title": "Stark Tool & Die, Denver",
                                     "address": "1 Forge Way, Denver"}]
    chosen = put(p["client"], f"{B}connection/", {
        "company": str(p["company"].pk), "account": "accounts/1", "account_label": "Stark",
        "location": "locations/2", "location_title": "Stark Tool & Die, Denver"}).json()
    assert chosen["chosen"] and chosen["stored"] == 2
    assert chosen["average_rating"] == 4.6 and chosen["total_review_count"] == 2
    assert {c["auth"] for c in google.calls} == {"Bearer access-stark"}


def test_a_consent_without_the_scope_stores_nothing(practice, google):
    p = practice
    q = parse_qs(urlparse(post(p["client"], f"{B}connection/start/",
                               {"company": str(p["company"].pk)}).json()["url"]).query)
    with mock.patch("apps.crm.services.gmail_oauth.exchange_code", return_value={
            "access_token": "a", "refresh_token": "r", "scope": "openid email"}), \
            mock.patch("apps.crm.services.gmail_oauth.account_email", return_value="x@y.example"):
        back = p["client"].get("/accounts/gmail/callback", {"state": q["state"][0], "code": "c"})
    assert "reviews_error=" in back["Location"]
    assert not GoogleReviewsConnection.all_objects.filter(company=p["company"]).exists()


# ------------------------------------------------------- paging and storing

def test_reading_pages_until_stored_reviews_are_reached(practice, google):
    p = practice
    connection = connected(p)
    google.pages = [[review(5), review(4)], [review(3), review(2)], [review(1)]]
    assert sync(connection) == {"new": 5, "updated": 0, "pages": 3}
    # Nothing new: the first review is already stored, so one page is read.
    google.calls.clear()
    assert sync(connection) == {"new": 0, "updated": 0, "pages": 1}
    assert len(google.review_reads()) == 1
    assert google.review_reads()[0]["query"]["orderBy"] == "updateTime desc"
    # A new review arrives at the top: still one page, and it is stored once.
    google.pages = [[review(6, created="2026-11-01T10:00:00Z"), review(5), review(4)],
                    [review(3), review(2)], [review(1)]]
    google.calls.clear()
    assert sync(connection)["new"] == 1 and len(google.review_reads()) == 1
    assert sorted(stored(connection)) == ["r1", "r2", "r3", "r4", "r5", "r6"]
    assert GoogleReview.all_objects.filter(connection=connection).count() == 6


def test_an_updated_review_is_updated_not_duplicated(practice, google):
    p = practice
    connection = connected(p)
    google.pages = [[review(2), review(1, stars=2)]]
    sync(connection)
    # The reviewer changes their stars and the business replies: newest change first.
    google.pages = [[review(1, stars=4, updated="2026-10-25T09:00:00Z",
                            reply="2026-10-25T12:00:00Z", comment="Better now"), review(2)]]
    counts = sync(connection)
    assert counts["updated"] == 1 and counts["new"] == 0
    one = stored(connection)["r1"]
    assert (one.star_rating, one.comment) == (4, "Better now")
    assert one.reply_at == datetime(2026, 10, 25, 12, 0, tzinfo=dt_timezone.utc)
    assert GoogleReview.all_objects.filter(connection=connection).count() == 2


# ----------------------------------------------------------------- measures

def _r(created, stars=5, reply=None):
    zone = dt_timezone.utc
    return GoogleReview(review_id=str(created), star_rating=stars,
                        created_on_google=datetime.fromisoformat(created).replace(tzinfo=zone),
                        updated_on_google=datetime.fromisoformat(created).replace(tzinfo=zone),
                        reply_at=datetime.fromisoformat(reply).replace(tzinfo=zone)
                        if reply else None)


def test_every_measure_from_stored_reviews():
    utc = ZoneInfo("UTC")
    rows = [_r("2026-09-28T10:00:00", 5, reply="2026-09-29T10:00:00"),
            _r("2026-10-02T10:00:00", 5, reply="2026-10-03T22:00:00"),
            _r("2026-10-10T10:00:00", 4),
            _r("2026-10-15T10:00:00", 1, reply="2026-11-02T10:00:00"),
            _r("2026-10-30T10:00:00", 5, reply="2026-10-31T10:00:00")]
    first, last = date(2026, 10, 1), date(2026, 10, 31)
    v = lambda m, **kw: google_reviews.value_for(m, rows, first, last, utc, **kw)  # noqa: E731
    assert v("new_reviews") == 4
    assert v("average_rating") == Decimal("3.75")
    assert v("five_star_share") == Decimal("50.0")
    assert v("reviews_by_star", star=5) == 2 and v("reviews_by_star", star=1) == 1
    # At October's end: the 10th's (never) and the 15th's (replied in November).
    assert v("unanswered") == 2
    # Replied in October: 1.5 days and 1 day.
    assert v("median_days_to_reply") == Decimal("1.2")          # 1.25, half to even
    # Every review by October's last day, September's included; none after.
    assert v("total_reviews") == 5
    assert google_reviews.value_for("total_reviews", rows, date(2026, 10, 1),
                                    date(2026, 10, 12), utc) == 3
    assert google_reviews.value_for("total_reviews", rows, date(2026, 8, 1),
                                    date(2026, 8, 31), utc) == 0
    empty = google_reviews.value_for("average_rating", rows, date(2026, 8, 1), date(2026, 8, 31),
                                     utc)
    assert empty is None


def test_the_feed_writes_readings_by_the_kpis_cadence(practice, google):
    p = practice
    connection = connected(p)
    google.pages = [[review(3, created="2026-10-20T15:00:00Z"),
                     review(2, stars=3, created="2026-10-05T15:00:00Z"),
                     review(1, created="2026-09-10T15:00:00Z")]]
    sync(connection)
    with mock.patch("apps.scorecard.views_reviews._today", return_value=TODAY):
        made = put(p["client"], f"{B}feed/", {"company": str(p["company"].pk),
                                             "kpi": str(p["kpis"]["new"].pk),
                                             "measure": "new_reviews"})
    assert made.status_code == 200, made.content
    assert made.json()["run"]["ok"] is True
    with tenant_context(p["t"].pk):
        readings = {r.period_start: r.value for r in KpiReading.objects.filter(
            kpi=p["kpis"]["new"])}
        assert Kpi.objects.get(pk=p["kpis"]["new"].pk).feed == "reviews"
    assert readings[date(2026, 10, 1)] == 2 and readings[date(2026, 9, 1)] == 1
    assert all(r == 0 for start, r in readings.items() if start < date(2026, 9, 1))
    with tenant_context(p["t"].pk):
        assert set(KpiReading.objects.filter(kpi=p["kpis"]["new"]).values_list(
            "source", flat=True)) == {"reviews"}
    # The tile's back says where it comes from.
    board = p["client"].get(f"/api/scorecard/?company={p['company'].pk}").json()
    tile = next(t for t in board["kpis"] if t["name"] == "New Google reviews")
    assert tile["feed"]["kind"] == "reviews" and "Google reviews" in tile["feed"]["text"]


def test_the_all_time_total_reads_every_review_by_each_periods_end(practice, google):
    p = practice
    connection = connected(p)
    google.pages = [[review(3, created="2026-10-20T15:00:00Z"),
                     review(2, stars=3, created="2026-10-05T15:00:00Z"),
                     review(1, created="2026-09-10T15:00:00Z")]]
    sync(connection)
    with tenant_context(p["t"].pk):
        total = setup.create_kpi(p["card"], {
            "name": "Total Google reviews", "kind": "count", "cadence": "monthly",
            "rollup": "last", "page": str(p["card"].pages.get().pk),
            "reading_owner": str(p["ff"].user_id)}, p["ff"].user)
    with mock.patch("apps.scorecard.views_reviews._today", return_value=TODAY):
        made = put(p["client"], f"{B}feed/", {"company": str(p["company"].pk),
                                             "kpi": str(total.pk), "measure": "total_reviews"})
    assert made.status_code == 200, made.content
    with tenant_context(p["t"].pk):
        readings = {r.period_start: r.value for r in KpiReading.objects.filter(kpi=total)}
    assert readings[date(2026, 10, 1)] == 3 and readings[date(2026, 9, 1)] == 1
    assert readings[date(2026, 8, 1)] == 0


def test_a_measure_must_fit_the_kpi(practice, google):
    p = practice
    connected(p)
    refused = put(p["client"], f"{B}feed/", {"company": str(p["company"].pk),
                                            "kpi": str(p["kpis"]["money"].pk),
                                            "measure": "new_reviews"})
    assert refused.status_code == 400 and "Count or Number" in refused.json()["measure"]
    no_star = put(p["client"], f"{B}feed/", {"company": str(p["company"].pk),
                                            "kpi": str(p["kpis"]["new"].pk),
                                            "measure": "reviews_by_star"})
    assert no_star.status_code == 400 and "stars" in no_star.json()["measure"]
    # A running total, added up week by week, would count each review again.
    summed = put(p["client"], f"{B}feed/", {"company": str(p["company"].pk),
                                           "kpi": str(p["kpis"]["new"].pk),
                                           "measure": "total_reviews"})
    assert summed.status_code == 400 and "rolls up by Last" in summed.json()["measure"]


def test_the_editor_gets_the_menu_without_asking_google(practice, google):
    p = practice
    connected(p)
    got = p["client"].get(f"{B}feed/?company={p['company'].pk}"
                          f"&kpi={p['kpis']['new'].pk}").json()
    assert {m["key"] for m in got["measures"]} == set(google_reviews.MEASURES)
    assert google.calls == []


# --------------------------------------------------------- not yet approved

@pytest.mark.parametrize("status, body", [
    (403, '{"error": {"code": 403, "status": "PERMISSION_DENIED"}}'),
    (429, '{"error": {"code": 429, "details": [{"metadata": {"quota_limit_value": "0"}}]}}'),
])
def test_not_yet_approved_says_so_plainly_and_the_connection_stays(practice, google, status,
                                                                   body):
    p = practice
    connection = connected(p)
    google.status, google.body = status, body
    tested = post(p["client"], f"{B}connection/test/", {"company": str(p["company"].pk)}).json()
    assert tested["not_approved"] is True and tested["check_ok"] is False
    assert tested["not_approved_text"] == google_reviews.NOT_APPROVED
    # The nightly read says it once on the connection, and a KPI says it too.
    with tenant_context(p["t"].pk):
        feed = KpiReviewsFeed.objects.create(tenant=p["t"], kpi=p["kpis"]["new"],
                                             measure="new_reviews")
    assert feeds.run_due_reviews(p["t"].pk, TODAY)["failed"] == 1
    with tenant_context(p["t"].pk):
        connection.refresh_from_db()
        feed.refresh_from_db()
    assert connection.not_approved and connection.last_error == google_reviews.NOT_APPROVED
    assert feed.last_error == google_reviews.NOT_APPROVED
    assert GoogleReviewsConnection.all_objects.filter(pk=connection.pk).exists()


def test_an_ordinary_rate_limit_is_not_called_unapproved(practice, google):
    p = practice
    connected(p)
    google.status, google.body = 429, '{"error": {"code": 429, "message": "Slow down"}}'
    tested = post(p["client"], f"{B}connection/test/", {"company": str(p["company"].pk)}).json()
    assert tested["not_approved"] is False and "429" in tested["check_detail"]


# ------------------------------------------------- isolation and the roles

def test_another_practice_never_reaches_the_connection_reviews_or_a_feed(practice, google):
    from apps.crm.seed import seed_tenant

    p = practice
    connection = connected(p)
    google.pages = [[review(1, comment="SECRET-REVIEW")]]
    sync(connection)
    other = TenantFactory()
    seed_tenant(other)
    b = Client()
    b.force_login(MembershipFactory(tenant=other, role="FF").user)
    q = f"?company={p['company'].pk}"
    for url in (f"{B}connection/{q}", f"{B}latest/{q}", f"{B}connection/choices/{q}",
                f"{B}feed/{q}&kpi={p['kpis']['new'].pk}"):
        response = b.get(url)
        assert response.status_code == 404, url
        assert b"SECRET-REVIEW" not in response.content
    for url in (f"{B}connection/start/", f"{B}connection/test/"):
        assert post(b, url, {"company": str(p["company"].pk)}).status_code == 404
    google.calls.clear()
    assert feeds.run_due_reviews(other.pk, TODAY) == {"read": 0, "failed": 0, "ran": 0,
                                                      "failed_feeds": 0}
    assert google.calls == []
    assert GoogleReview.all_objects.filter(tenant=other).count() == 0


def test_only_the_practice_owner_connects_and_an_assistant_sees_nothing(practice, google,
                                                                       seeded_tenant):
    p = practice
    connected(p)
    from .factories import ClientAssignmentFactory

    associate = MembershipFactory(tenant=seeded_tenant, role="CF")
    ClientAssignmentFactory(tenant=seeded_tenant, user=associate.user, company=p["company"])
    cf = Client()
    cf.force_login(associate.user)
    assert cf.get(f"{B}latest/?company={p['company'].pk}").status_code == 200
    for url in (f"{B}connection/start/", f"{B}connection/test/"):
        assert post(cf, url, {"company": str(p["company"].pk)}).status_code == 403
    assert cf.delete(f"{B}connection/?company={p['company'].pk}").status_code == 403
    va = Client()
    va.force_login(MembershipFactory(tenant=seeded_tenant, role="VA").user)
    assert va.get(f"{B}latest/?company={p['company'].pk}").status_code == 403
    client_owner = Client()
    client_owner.force_login(p["owner"].user)
    assert client_owner.get(f"{B}latest/?company={p['company'].pk}").status_code in (403, 404)


def test_the_latest_reviews_card_is_read_only_and_newest_first(practice, google):
    p = practice
    connection = connected(p)
    google.pages = [[review(2, stars=3, created="2026-10-30T10:00:00Z", name="Pat"),
                     review(1, created="2026-10-01T10:00:00Z", reply="2026-10-02T10:00:00Z")]]
    sync(connection)
    got = p["client"].get(f"{B}latest/?company={p['company'].pk}").json()
    assert [r["stars"] for r in got["reviews"]] == [3, 5]
    assert got["reviews"][0]["reviewer"] == "Pat" and got["reviews"][0]["replied"] is False
    assert got["reviews"][1]["replied"] is True
    assert got["location_title"] == "Stark Tool & Die, Denver"


def test_disconnect_takes_the_token_and_the_stored_reviews_and_keeps_readings(practice,
                                                                              google):
    p = practice
    connection = connected(p)
    google.pages = [[review(1, created="2026-10-02T10:00:00Z")]]
    sync(connection)
    with mock.patch("apps.scorecard.views_reviews._today", return_value=TODAY):
        put(p["client"], f"{B}feed/", {"company": str(p["company"].pk),
                                      "kpi": str(p["kpis"]["new"].pk), "measure": "new_reviews"})
    assert p["client"].delete(f"{B}connection/?company={p['company'].pk}").status_code == 200
    assert not GoogleReviewsConnection.all_objects.filter(pk=connection.pk).exists()
    assert GoogleReview.all_objects.filter(connection_id=connection.pk).count() == 0
    with tenant_context(p["t"].pk):
        assert KpiReading.objects.filter(kpi=p["kpis"]["new"]).exists()


def test_the_demo_never_connects(practice, monkeypatch, google):
    from config import environment

    monkeypatch.setattr(environment, "is_demo", lambda: True)
    response = post(practice["client"], f"{B}connection/start/",
                    {"company": str(practice["company"].pk)})
    assert response.status_code == 409 and "never signs in to Google" in response.json()["detail"]
