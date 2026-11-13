"""Google reviews for the scorecard (`docs/google_reviews_feed.md`).

- **Signing in.** The practice owner starts it on the company page; whoever
  manages the client's Business Profile signs in with Google, through the
  practice's existing OAuth client and its one redirect URI (told apart there
  by this consent's own state, as the calendar's is). The grant asks for
  `openid email business.manage` and nothing else, only now (incremental):
  it is the company's, not anyone's own mailbox grant. The refresh token is
  stored encrypted on the connection's row.
- **Choosing.** The account and the location come from Google's own lists:
  the Account Management API's accounts and the Business Information API's
  locations.
- **Reading.** Nightly, in the scorecard's feed job: the v4
  `accounts.locations.reviews.list`, newest change first, paged until a
  review already stored and unchanged is reached. Each review's id, stars,
  comment, reviewer's display name, create and update times and reply time
  are kept; so are the location's average rating and review count from the
  same answer.
- **Not approved.** Google gives a project the Business Profile APIs only
  once it approves it: until then the quota is 0, or the answer is a 403.
  That is said in one plain line, and the connection stays.
- **Measures** are worked out from the stored reviews, per period of the
  KPI's cadence and window.
"""

from __future__ import annotations

import json
import statistics
from datetime import date
from decimal import Decimal
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from . import periods as P

SCOPE = "https://www.googleapis.com/auth/business.manage"
SCOPES = ["openid", "email", SCOPE]
ACCOUNTS_URL = "https://mybusinessaccountmanagement.googleapis.com/v1/accounts"
LOCATIONS_URL = "https://mybusinessbusinessinformation.googleapis.com/v1/{account}/locations"
REVIEWS_URL = "https://mybusiness.googleapis.com/v4/{account}/{location}/reviews"
PAGE_SIZE = 50
MOST_PAGES = 200
#: The consent this browser started: {state, company}.
STATE_KEY = "google_reviews_oauth"

NOT_APPROVED = ("Google hasn't approved this app's access to Business Profile reviews yet. "
                "The connection stays, and reviews are read once Google approves it.")
DEMO_REFUSAL = ("This is the demo. It never signs in to Google, so a Business Profile can't "
                "be connected here. The location shown is the demo's own sample.")

STARS = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}

#: key: (label, kind, needs a star)
MEASURES = {
    "new_reviews": ("New reviews", "count", False),
    "average_rating": ("Average rating of new reviews", "rating", False),
    "five_star_share": ("Five-star share of new reviews", "percent", False),
    "reviews_by_star": ("New reviews with a given number of stars", "count", True),
    "unanswered": ("Unanswered reviews at the period's end", "count", False),
    "median_days_to_reply": ("Median days to reply", "duration", False),
    #: 2026-11-12: every review left by the period's last day.
    "total_reviews": ("Total reviews (all time)", "count", False),
}
FITS = {"percent": {"percent"}, "count": {"count", "number"},
        "rating": {"rating", "number"}, "duration": {"duration", "number"}}


class ReviewsUnavailable(Exception):
    """Google could not be read now; the next read tries again."""


class ReviewsRefused(Exception):
    """What was asked for is not allowed, in words."""


class NotApproved(ReviewsUnavailable):
    def __init__(self, message=NOT_APPROVED):
        super().__init__(message)


# ------------------------------------------------------------- the consent

def consent_url(tenant, state: str, *, login_hint: str = "") -> str:
    from apps.crm.services import gmail_oauth

    params = {"client_id": gmail_oauth.client_for(tenant)[0],
              "redirect_uri": gmail_oauth.redirect_uri(), "response_type": "code",
              "scope": " ".join(SCOPES), "access_type": "offline",
              # The picker, so the profile's manager can be chosen; consent, so
              # Google issues a refresh token for this grant.
              "prompt": "select_account consent", "state": state}
    if login_hint:
        params["login_hint"] = login_hint
    return f"{gmail_oauth.AUTH_URL}?{urlencode(params)}"


def is_reviews_consent(request) -> bool:
    started = request.session.get(STATE_KEY) or {}
    return bool(started.get("state")) and request.GET.get("state") == started.get("state")


def granted(tokens: dict) -> bool:
    return SCOPE in (tokens.get("scope") or "").split()


def http_post_form(url, data):
    import requests

    try:
        response = requests.post(url, data=data, timeout=20)
    except requests.RequestException as exc:
        raise ReviewsUnavailable("Google didn't answer. The read will try again later.") from exc
    return response.status_code, response.text


def access_token(connection, *, post=None) -> str:
    """A fresh access token from the connection's own refresh token."""
    from apps.crm.services import gmail_oauth
    from apps.crm.services.secrets import decrypt

    refresh = decrypt(connection.token_ciphertext)
    if not refresh:
        raise ReviewsUnavailable("No Google sign-in is stored for this location. Connect "
                                 "again on the company page.")
    client_id, client_secret = gmail_oauth.client_for(connection.tenant)
    status, body = (post or http_post_form)(gmail_oauth.TOKEN_URL, {
        "client_id": client_id, "client_secret": client_secret, "refresh_token": refresh,
        "grant_type": "refresh_token"})
    if status != 200:
        raise ReviewsUnavailable(f"Google refused the stored sign-in ({status}). Connect again "
                                 "on the company page.")
    return json.loads(body)["access_token"]


# -------------------------------------------------------------- the client

def http_transport(url, headers):
    """One GET. Returns (status, body text)."""
    import requests

    try:
        response = requests.get(url, headers=headers, timeout=30)
    except requests.RequestException as exc:
        raise ReviewsUnavailable("Google didn't answer. The read will try again later.") from exc
    return response.status_code, response.text


def _not_approved(status: int, body: str) -> bool:
    """403, or a quota of 0 (Google's 429 says the limit's value)."""
    if status == 403:
        return True
    if status == 429:
        text = (body or "").replace(" ", "")
        return any(mark in text for mark in ('"quota_limit_value":"0"', "limit:0",
                                             "Quotalimitis0", "quota_limit_value\":\"0"))
    return False


class ReviewsClient:
    def __init__(self, token, *, transport=None):
        self.token = token
        self.transport = transport or http_transport
        self.calls = 0

    def get(self, url, params=None):
        full = url + (f"?{urlencode(params)}" if params else "")
        self.calls += 1
        status, body = self.transport(full, {"Authorization": f"Bearer {self.token}",
                                             "Accept": "application/json"})
        if _not_approved(status, body):
            raise NotApproved()
        if status == 401:
            raise ReviewsUnavailable("Google refused the stored sign-in. Connect again on the "
                                     "company page.")
        if status == 404:
            raise ReviewsRefused("Google doesn't know that location any more. Choose it again "
                                 "on the company page.")
        if status >= 400:
            raise ReviewsUnavailable(f"Google answered {status}. The read will try again later.")
        try:
            return json.loads(body or "{}")
        except ValueError:
            raise ReviewsUnavailable("Google's answer couldn't be read.") from None

    def accounts(self) -> list[dict]:
        out, page = [], None
        for _ in range(20):
            got = self.get(ACCOUNTS_URL, {"pageSize": 20, **({"pageToken": page} if page else {})})
            out += [{"name": a.get("name", ""), "label": a.get("accountName") or a.get("name", ""),
                     "type": a.get("type", "")} for a in got.get("accounts") or []]
            page = got.get("nextPageToken")
            if not page:
                break
        return out

    def locations(self, account: str) -> list[dict]:
        out, page = [], None
        for _ in range(20):
            got = self.get(LOCATIONS_URL.format(account=account),
                           {"readMask": "name,title,storefrontAddress", "pageSize": 100,
                            **({"pageToken": page} if page else {})})
            for loc in got.get("locations") or []:
                address = loc.get("storefrontAddress") or {}
                line = ", ".join(x for x in [*(address.get("addressLines") or [])[:1],
                                             address.get("locality", "")] if x)
                out.append({"name": loc.get("name", ""), "title": loc.get("title", ""),
                            "address": line})
            page = got.get("nextPageToken")
            if not page:
                break
        return out

    def reviews_page(self, account: str, location: str, page_token=None,
                     page_size=PAGE_SIZE) -> dict:
        return self.get(REVIEWS_URL.format(account=account, location=location),
                        {"pageSize": page_size, "orderBy": "updateTime desc",
                         **({"pageToken": page_token} if page_token else {})})


def client_for(connection, *, transport=None, post=None) -> ReviewsClient:
    from config import environment

    if environment.is_demo():
        raise ReviewsUnavailable(DEMO_REFUSAL)
    return ReviewsClient(access_token(connection, post=post), transport=transport)


# ---------------------------------------------------------------- reading

def _when(text):
    return parse_datetime(text) if text else None


def read_review(raw: dict) -> dict:
    reply = raw.get("reviewReply") or {}
    reviewer = raw.get("reviewer") or {}
    created = _when(raw.get("createTime"))
    return {"review_id": str(raw.get("reviewId") or raw.get("name", "")).rsplit("/", 1)[-1][:200],
            "star_rating": STARS.get(raw.get("starRating") or ""),
            "comment": raw.get("comment") or "",
            "reviewer_name": ("A Google user" if reviewer.get("isAnonymous")
                              else reviewer.get("displayName") or "")[:200],
            "created_on_google": created,
            "updated_on_google": _when(raw.get("updateTime")) or created,
            "reply_at": _when(reply.get("updateTime")) if reply else None}


def sync(connection, client) -> dict:
    """Read new and changed reviews into the store. Returns counts."""
    from .models import GoogleReview, GoogleReviewsConnection

    if not connection.location_name or not connection.account_name:
        raise ReviewsRefused("Choose the Business Profile location on the company page first.")
    stored = {r.review_id: r for r in GoogleReview.all_objects.filter(connection=connection)}
    counts = {"new": 0, "updated": 0, "pages": 0}
    average = total = None
    page_token, reached = None, False
    while counts["pages"] < MOST_PAGES:
        got = client.reviews_page(connection.account_name, connection.location_name, page_token)
        counts["pages"] += 1
        if counts["pages"] == 1:
            average, total = got.get("averageRating"), got.get("totalReviewCount")
        for raw in got.get("reviews") or []:
            fields = read_review(raw)
            if not fields["review_id"] or fields["created_on_google"] is None:
                continue
            row = stored.get(fields["review_id"])
            if row is None:
                row = GoogleReview.all_objects.create(tenant_id=connection.tenant_id,
                                                      connection=connection, **fields)
                stored[row.review_id] = row
                counts["new"] += 1
            elif (row.updated_on_google, row.reply_at, row.star_rating, row.comment) == (
                    fields["updated_on_google"], fields["reply_at"], fields["star_rating"],
                    fields["comment"]):
                # Newest change first: an unchanged review means everything
                # after it is already stored as it is.
                reached = True
            else:
                for name, value in fields.items():
                    setattr(row, name, value)
                row.save()
                counts["updated"] += 1
        page_token = got.get("nextPageToken")
        if reached or not page_token:
            break
    now = timezone.now()
    GoogleReviewsConnection.all_objects.filter(pk=connection.pk).update(
        average_rating=Decimal(str(average)).quantize(Decimal("0.01")) if average is not None
        else None, total_review_count=int(total) if total is not None else None,
        not_approved=False, last_read_at=now, last_success_at=now, last_error="",
        updated_at=now)
    return counts


def failed(connection, exc) -> None:
    """A read that did not happen: said once on the connection, and kept."""
    from .models import GoogleReviewsConnection

    now = timezone.now()
    GoogleReviewsConnection.all_objects.filter(pk=connection.pk).update(
        not_approved=isinstance(exc, NotApproved), last_read_at=now, last_error=str(exc)[:500],
        updated_at=now)


# --------------------------------------------------------------- measures

def menu() -> list[dict]:
    return [{"key": k, "label": label, "kind": kind, "star": star}
            for k, (label, kind, star) in MEASURES.items()]


def check_fits(kpi, measure, star=None):
    if measure not in MEASURES:
        raise ReviewsRefused("Choose a measure from the list.")
    if kpi.per_person:
        raise ReviewsRefused(f"{kpi.name} has a reading per person; a reviews measure is one "
                             "number for the location.")
    label, kind, needs_star = MEASURES[measure]
    if needs_star and star not in (1, 2, 3, 4, 5):
        raise ReviewsRefused("Choose how many stars, from 1 to 5.")
    if kpi.kind not in FITS[kind]:
        need = {"percent": "Percent", "count": "Count or Number", "rating": "Rating or Number",
                "duration": "Duration or Number"}[kind]
        raise ReviewsRefused(f"{label} fits a KPI of kind {need}; {kpi.name} is "
                             f"{kpi.get_kind_display()}.")
    if measure == "total_reviews" and kpi.rollup != "last":
        # A running total: weeks added up into a month would count it twice.
        raise ReviewsRefused(f"{label} is a running total, so its KPI rolls up by Last; "
                             f"{kpi.name} rolls up by {kpi.get_rollup_display()}.")


def _day(moment, zone):
    return moment.astimezone(zone).date()


def value_for(measure, reviews, first: date, last: date, zone, *, star=None):
    """One period's value from the stored reviews, or None where the period
    has nothing to say (no new reviews for an average)."""
    made = [r for r in reviews if first <= _day(r.created_on_google, zone) <= last]
    if measure == "new_reviews":
        return Decimal(len(made))
    if measure == "reviews_by_star":
        return Decimal(sum(1 for r in made if r.star_rating == star))
    rated = [r.star_rating for r in made if r.star_rating]
    if measure == "average_rating":
        return (Decimal(sum(rated)) / len(rated)).quantize(Decimal("0.01")) if rated else None
    if measure == "five_star_share":
        return (Decimal(sum(1 for s in rated if s == 5)) * 100 / len(rated)).quantize(
            Decimal("0.1")) if rated else None
    if measure == "unanswered":
        return Decimal(sum(1 for r in reviews if _day(r.created_on_google, zone) <= last
                           and (r.reply_at is None or _day(r.reply_at, zone) > last)))
    if measure == "total_reviews":
        # Every stored review created by the last day. A review taken down on
        # Google stays stored (the read never deletes), so it is still counted.
        return Decimal(sum(1 for r in reviews if _day(r.created_on_google, zone) <= last))
    if measure == "median_days_to_reply":
        days = [(r.reply_at - r.created_on_google).total_seconds() / 86400 for r in reviews
                if r.reply_at is not None and first <= _day(r.reply_at, zone) <= last]
        return Decimal(str(statistics.median(days))).quantize(Decimal("0.1")) if days else None
    raise ReviewsRefused("Choose a measure from the list.")


def plan_for(feed, today, *, periods=2, back=13, read_open=False, reviews=None):
    """{(start, None): value} for the closed periods this read covers (the
    last two each day, as far back as 13 the first time), and with
    `read_open` the open one so far: the Track feed's own window."""
    from .models import GoogleReview

    kpi = feed.kpi
    company = kpi.scorecard.company
    zone = ZoneInfo(kpi.tenant.timezone)
    if reviews is None:
        reviews = list(GoogleReview.all_objects.filter(
            tenant_id=kpi.tenant_id, connection__company=company))
    week_start = kpi.scorecard.week_start
    last_closed = P.previous_start(P.start_of(today, kpi.cadence, week_start), kpi.cadence,
                                   week_start)
    count = back if feed.last_success_at is None else periods
    starts = P.last_n(last_closed, kpi.cadence, count, week_start)
    if read_open:
        starts.append(P.start_of(today, kpi.cadence, week_start))
    values = {}
    for start in starts:
        end = min(P.end_of(start, kpi.cadence), today)
        value = value_for(feed.measure, reviews, start, end, zone, star=feed.star)
        if value is not None and MEASURES[feed.measure][1] == "duration" \
                and kpi.kind == "duration":
            value = (value * (24 if kpi.duration_unit == "hours" else 1440)).quantize(
                Decimal("0.1"))
        if value is not None:
            values[(start, None)] = value
    return values


def latest(connection, n=10) -> list[dict]:
    from .models import GoogleReview

    return [{"id": r.review_id, "stars": r.star_rating, "comment": r.comment[:600],
             "reviewer": r.reviewer_name, "created_at": r.created_on_google.isoformat(),
             "replied": r.reply_at is not None,
             "reply_at": r.reply_at.isoformat() if r.reply_at else None}
            for r in GoogleReview.all_objects.filter(connection=connection)
            .order_by("-created_on_google")[:n]]
