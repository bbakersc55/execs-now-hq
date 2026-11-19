"""The Track PMS feed (M5 part 4, spec "Feeds"): a client company's Track
account, read into a KPI's readings with a measure from a fixed menu.

Built to Track's public API reference (developer.trackhs.com, read
2026-10-24). **Every field name here is from that reference; none has been
seen in a live account's answer.** What the reference says, and what this
code therefore assumes:

- Base URL: the client's own Track domain + `/api` (the reference's
  `{customerDomain}`). HTTP Basic: the API key as user name, the secret as
  password ("Change the Username and Password to match one of your API keys
  and secrets").
- Collections are paged with `page` and `size` and answer
  `{"_embedded": {<key>: [...]}, "page_count": n, ...}`.
- Rate limit: 10,000 requests every five minutes, by IP. The answer to going
  over is not documented: a 429 is assumed, `Retry-After` read if present.

Streams and the fields each measure reads:

| Stream | Path | Fields |
|---|---|---|
| Units | `/pms/units` (`isActive=1`) | `id`, `name` |
| Reservations | `/v2/pms/reservations` (`startDateRange`, `endDateRange`; `bookedStart`, `bookedEnd`) | `id`, `status`, `unitId`, `arrivalDate`, `departureDate`, `nights`, `bookedAt`, `guestBreakdown.grossRent` |
| Reviews | `/channel-management/channel/reviews` (`updatedSince`) | `id`, `unitId`, `overAllRating`, `channelReviews[].reviewCreatedAt` (else `reviewerSubmittedAt`) |
| Maintenance | `/pms/maintenance/work-orders` | `id`, `status`, `unitId`, `userId`, `dateReceived`, `dateCompleted`, `scheduledAt` (a sort column in the reference, not in its response schema) |
| Housekeeping | `/pms/housekeeping/work-orders` | `id`, `status`, `unitId`, `userId`, `createdAt`, `scheduledAt`, `completedAt` |

Everything that decides a number is a plain function over those rows, so
the tests run against recorded answers shaped as the reference documents
them (`tests/fixtures/track/`), never against Track.

Writes (intake forms, docs/p14_intake_forms.md) go through `send`. Every call,
read or write, sends `Accept: application/json` (Track answers 406 without
one) and a User-Agent naming ENHQ. Track sits behind an AWS load balancer with
a firewall: its refusals are a 403 with `Server: awselb/2.0` and an HTML body,
and they are about the request's content (an @example.com email, for one),
never the key; they are said so in words (`TrackFirewall`).
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode, urlparse

from . import periods as P

#: Track's documented limit, and the share of it one read may use: other
#: software of the client's shares the same IP's budget.
LIMIT, WINDOW_SECONDS, BUDGET = 10_000, 300, 2_000
PAGE_SIZE = 100
MOST_PAGES = 200
RETRIES = 3


log = logging.getLogger(__name__)

USER_AGENT = "ExecsNowHQ/1.0 (+https://getexecutivesnow.com)"


class TrackUnavailable(Exception):
    """Track could not be reached, or refused. Said in words."""


class TrackFirewall(TrackUnavailable):
    """Track's firewall refused the content of a request: not the key."""


class TrackRefusal(TrackUnavailable):
    """Track answered a write with a refusal it explained (400/404/409/422):
    `messages` are Track's own words, for the person who sent it."""

    def __init__(self, text, *, status, messages=()):
        super().__init__(text)
        self.status = status
        self.messages = list(messages)


class TrackRefused(ValueError):
    """The measure asked for something that cannot be, said in words."""


# ------------------------------------------------------------- the menu

#: key -> (label, stream, kind, scope). scope: "property" (a unit or total)
#: or "assignee" (a Track user or total). The KPI's kind must fit.
MEASURES = {
    "occupancy": ("Occupancy", "reservations", "percent", "property"),
    "adr": ("ADR (average daily rate)", "reservations", "money", "property"),
    "revpar": ("RevPAR (revenue per available night)", "reservations", "money", "property"),
    "nights_booked": ("Nights booked", "reservations", "count", "property"),
    "bookings_created": ("Bookings created", "reservations", "count", "property"),
    "revenue": ("Revenue (gross rent)", "reservations", "money", "property"),
    "reviews_received": ("Reviews received", "reviews", "count", "property"),
    "average_rating": ("Average rating", "reviews", "rating", "property"),
    "maint_open": ("Maintenance work orders open", "maintenance", "count", "assignee"),
    "maint_overdue": ("Maintenance work orders overdue", "maintenance", "count", "assignee"),
    "maint_closed": ("Maintenance work orders closed", "maintenance", "count", "assignee"),
    "maint_days_to_close": ("Maintenance: average days to close", "maintenance", "duration",
                            "assignee"),
    "hk_open": ("Housekeeping work orders open", "housekeeping", "count", "assignee"),
    "hk_overdue": ("Housekeeping work orders overdue", "housekeeping", "count", "assignee"),
    "hk_closed": ("Housekeeping work orders closed", "housekeeping", "count", "assignee"),
    "hk_days_to_close": ("Housekeeping: average days to close", "housekeeping", "duration",
                         "assignee"),
}
#: Kinds a KPI may be for each measure kind ("rating" also fits a number).
FITS = {"percent": {"percent"}, "money": {"money"}, "count": {"count", "number"},
        "rating": {"rating", "number"}, "duration": {"duration", "number"}}

#: Reservations that are stays, not cancelled and not held.
STAYS = {"Confirmed", "Checked In", "Checked Out"}
MAINT_DONE = {"completed", "processed", "vendor-completed", "user-completed", "cancelled"}
HK_DONE = {"completed", "processed", "cancelled"}


# ------------------------------------------------------------- the client

@dataclass
class Budget:
    """Requests made in the last five minutes, by this process, to one
    domain. A read stops short of its share rather than spend the client's."""

    times: list = field(default_factory=list)
    sleep: object = time.sleep
    clock: object = time.monotonic

    def take(self):
        now = self.clock()
        self.times = [t for t in self.times if now - t < WINDOW_SECONDS]
        if len(self.times) >= BUDGET:
            wait = WINDOW_SECONDS - (now - self.times[0])
            if wait > 60:
                raise TrackUnavailable(
                    "Track's request limit for this account is nearly used up; the read "
                    "will try again later.")
            self.sleep(max(0.0, wait))
        self.times.append(self.clock())


_BUDGETS: dict = {}


def http_transport(url, headers):
    """One GET. Returns (status, headers, body text)."""
    import requests

    try:
        response = requests.get(url, headers=headers, timeout=30)
    except requests.RequestException as exc:
        raise TrackUnavailable("Track didn't answer. The read will try again later.") from exc
    return response.status_code, dict(response.headers), response.text


def http_send(method, url, headers, body):
    """One write (POST, PUT, PATCH or DELETE) with a JSON body, or none.
    Returns (status, headers, body text)."""
    import requests

    try:
        response = requests.request(method, url, headers=headers, timeout=45,
                                    data=None if body is None else json.dumps(body),
                                    allow_redirects=False)
    except requests.RequestException as exc:
        raise TrackUnavailable("Track didn't answer. Nothing more was sent; try the rest "
                               "again in a minute.") from exc
    return response.status_code, dict(response.headers), response.text


def is_firewall(status, headers, body) -> bool:
    """Track's load balancer refused it: a 403 from `awselb` with an HTML body."""
    lowered = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    return (status == 403 and "awselb" in lowered.get("server", "").lower()
            and "<html" in (body or "")[:200].lower())


FIREWALL_TEXT = ("Track's firewall refused the content of this request. It was not the key: "
                 "something in what was sent (an @example.com email, for one) looks wrong to "
                 "Track. Change it and try again.")


def path_template(path: str) -> str:
    """A path with its ids taken out, for logs: /pms/units/{n}/rooms."""
    return re.sub(r"/\d+", "/{n}", path.split("?")[0])


def _messages(data) -> list[str]:
    if not isinstance(data, dict):
        return []
    said = data.get("validation_messages")
    if isinstance(said, dict):
        flat = []
        for key, value in said.items():
            for item in (value.values() if isinstance(value, dict) else
                         value if isinstance(value, list) else [value]):
                flat.append(f"{key}: {item}")
        return flat
    if isinstance(said, list):
        return [str(m) for m in said]
    return [str(data["detail"])] if data.get("detail") else []


def base_url(domain: str) -> str:
    """The client's Track domain as `https://host/api`, from whatever was
    typed ("acme.trackhs.com", a full address, with or without /api)."""
    text = (domain or "").strip().rstrip("/")
    if not text:
        raise TrackRefused("Enter the company's Track address, like acme.trackhs.com.")
    parsed = urlparse(text if "//" in text else f"https://{text}")
    if not parsed.hostname or "." not in parsed.hostname:
        raise TrackRefused("That doesn't look like a Track address, like acme.trackhs.com.")
    return f"https://{parsed.hostname}/api"


class TrackClient:
    """Read-only. One company's connection; its key and secret are read from
    the company's own encrypted secrets and never leave the Authorization
    header, never a log line or an error."""

    def __init__(self, domain, key, secret, *, transport=None, sender=None, sleep=time.sleep,
                 clock=time.monotonic):
        self.base = base_url(domain)
        self.auth = "Basic " + base64.b64encode(f"{key}:{secret}".encode()).decode()
        # Looked up when made, not when defined, so a test's stand-in applies.
        self.transport = transport or globals()["http_transport"]
        self.sender = sender or globals()["http_send"]
        self.sleep = sleep
        host = urlparse(self.base).hostname
        self.budget = _BUDGETS.setdefault(host, Budget(sleep=sleep, clock=clock))
        self.calls = 0

    def _scrub(self, text):
        return str(text).replace(self.auth, "[credentials]")

    def get(self, path, params=None):
        url = f"{self.base}{path}" + (f"?{urlencode(params, doseq=True)}" if params else "")
        for attempt in range(RETRIES + 1):
            self.budget.take()
            self.calls += 1
            status, headers, body = self.transport(url, self._headers())
            if status == 429 and attempt < RETRIES:
                wait = headers.get("Retry-After") or headers.get("retry-after") or 60
                try:
                    wait = min(300.0, float(wait))
                except ValueError:
                    wait = 60.0
                self.sleep(wait)
                continue
            break
        if is_firewall(status, headers, body):
            raise TrackFirewall(FIREWALL_TEXT)
        if status == 401:
            raise TrackUnavailable("Track refused the key and secret. Check them on the "
                                   "company page and test the connection again.")
        if status == 403:
            raise TrackUnavailable("Track's key doesn't allow this read. It needs a server key "
                                   "with access to the PMS.")
        if status == 429:
            raise TrackUnavailable("Track's request limit was reached. The read will try again "
                                   "later.")
        if status >= 400:
            raise TrackUnavailable(f"Track answered {status}. The read will try again later.")
        try:
            return json.loads(body or "{}")
        except ValueError:
            raise TrackUnavailable("Track's answer couldn't be read.") from None

    def _headers(self, *, body=False):
        headers = {"Authorization": self.auth, "Accept": "application/json",
                   "User-Agent": USER_AGENT}
        if body:
            headers["Content-Type"] = "application/json"
        return headers

    def send(self, method, path, body=None):
        """One write. Returns Track's answer as data (None for an empty one).
        Raises `TrackFirewall`, `TrackRefusal` (Track's own words) or
        `TrackUnavailable`, each said for a person. A 429 waits and tries
        again, politely; anything else is never retried here, so a write is
        never sent twice by this method."""
        method = method.upper()
        if method not in ("POST", "PUT", "PATCH", "DELETE"):
            raise ValueError(f"send() is for writes, not {method}")
        url = f"{self.base}{path}"
        for attempt in range(RETRIES + 1):
            self.budget.take()
            self.calls += 1
            status, headers, text = self.sender(method, url, self._headers(body=body is not None),
                                                body)
            log.info("track %s %s -> %s", method, path_template(path), status)
            if status == 429 and attempt < RETRIES:
                wait = (headers or {}).get("Retry-After") or (headers or {}).get("retry-after") or 30
                try:
                    wait = min(120.0, float(wait))
                except ValueError:
                    wait = 30.0
                self.sleep(wait)
                continue
            break
        if is_firewall(status, headers, text):
            raise TrackFirewall(FIREWALL_TEXT)
        try:
            data = json.loads(text) if text else None
        except ValueError:
            data = None
        if status in (200, 201, 202, 204):
            return data
        if status == 401:
            raise TrackUnavailable("Track refused the key and secret. Check them on the company "
                                   "page.")
        if status == 403:
            raise TrackUnavailable("Track's key doesn't allow this change. It needs a server key "
                                   "with write access.")
        if status == 429:
            raise TrackUnavailable("Track's request limit was reached. Try the rest again in a "
                                   "few minutes.")
        if status in (400, 404, 405, 409, 422):
            messages = _messages(data)
            text = "Track refused it: " + ("; ".join(messages) if messages
                                           else f"it answered {status}.")
            raise TrackRefusal(text, status=status, messages=messages)
        raise TrackUnavailable(f"Track answered {status}. Try the rest again in a minute.")

    def collection(self, path, key, params=None, most_pages=MOST_PAGES):
        """Every row of a paged collection (or its first `most_pages` pages)."""
        rows, page = [], 1
        while page <= most_pages:
            got = self.get(path, {**(params or {}), "page": page, "size": PAGE_SIZE})
            embedded = got.get("_embedded") or {}
            rows.extend(embedded.get(key) or [])
            if page >= int(got.get("page_count") or 1):
                break
            page += 1
        return rows

    # The streams.
    def test(self) -> str:
        got = self.get("/pms/units", {"page": 1, "size": 1, "isActive": 1})
        return f"Connected: {int(got.get('total_items') or 0)} active units."

    def units(self):
        return self.collection("/pms/units", "units", {"isActive": 1})

    def stays(self, first: date, last: date, unit=None):
        params = {"startDateRange": first.isoformat(), "endDateRange": last.isoformat()}
        if unit:
            params["unitId"] = unit
        return self.collection("/v2/pms/reservations", "reservations", params)

    def booked(self, first: date, last: date, unit=None):
        params = {"bookedStart": f"{first.isoformat()}T00:00:00Z",
                  "bookedEnd": f"{last.isoformat()}T23:59:59Z"}
        if unit:
            params["unitId"] = unit
        return self.collection("/v2/pms/reservations", "reservations", params)

    def reviews(self, since: date, unit=None):
        params = {"updatedSince": f"{since.isoformat()}T00:00:00Z"}
        if unit:
            params["unit"] = unit
        return self.collection("/channel-management/channel/reviews", "channel_reviews", params)

    def maintenance(self, user=None, most_pages=MOST_PAGES):
        return self.collection("/pms/maintenance/work-orders", "workOrders",
                               {"userId": user} if user else None, most_pages=most_pages)

    def housekeeping(self, user=None, most_pages=MOST_PAGES):
        return self.collection("/pms/housekeeping/work-orders", "nodes",
                               {"userId": user} if user else None, most_pages=most_pages)


# ------------------------------------------------------------- the arithmetic

def _day(value) -> date | None:
    if not value:
        return None
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _money(value) -> Decimal:
    try:
        return Decimal(str(value or "0").replace(",", ""))
    except InvalidOperation:
        return Decimal("0")


def _overlap(arrival, departure, first, last) -> int:
    """Nights of a stay inside first..last (a night belongs to the day it starts)."""
    if arrival is None or departure is None:
        return 0
    start, end = max(arrival, first), min(departure, last + timedelta(days=1))
    return max(0, (end - start).days)


def _stay_nights(row) -> int:
    nights = row.get("nights")
    try:
        if nights not in (None, ""):
            return int(nights)
    except (TypeError, ValueError):
        pass
    a, d = _day(row.get("arrivalDate")), _day(row.get("departureDate"))
    return max(0, (d - a).days) if a and d else 0


def stay_numbers(stays, first, last, *, unit=None):
    """(nights in the period, gross rent earned in the period): rent is
    spread evenly over a stay's nights, so a stay across the period's edge
    counts only its nights inside."""
    nights, rent = 0, Decimal("0")
    for row in stays:
        if row.get("status") not in STAYS:
            continue
        if unit and str(row.get("unitId")) != str(unit):
            continue
        inside = _overlap(_day(row.get("arrivalDate")), _day(row.get("departureDate")),
                          first, last)
        if not inside:
            continue
        nights += inside
        total = _stay_nights(row)
        gross = _money((row.get("guestBreakdown") or {}).get("grossRent"))
        if total:
            rent += gross * inside / total
    return nights, rent


def available_nights(units, first, last, *, unit=None) -> int:
    count = 1 if unit else len(units)
    return count * ((last - first).days + 1)


def _round(value, places="0.01"):
    return Decimal(value).quantize(Decimal(places))


def _review_day(row):
    for review in row.get("channelReviews") or []:
        for key in ("reviewCreatedAt", "reviewerSubmittedAt"):
            found = _day(review.get(key))
            if found:
                return found
    return None


def _rating(row):
    try:
        value = Decimal(str(row.get("overAllRating")))
    except (InvalidOperation, TypeError):
        return None
    return value if value.is_finite() else None


def _work_rows(rows, *, user=None, unit=None):
    for row in rows:
        if user and str(row.get("userId")) != str(user):
            continue
        if unit and str(row.get("unitId")) != str(unit):
            continue
        yield row


def work_numbers(rows, first, last, *, stream, user=None):
    """For a stream of work orders, over first..last: open and overdue at the
    period's end, closed in it, and average days from received to closed."""
    done = MAINT_DONE if stream == "maintenance" else HK_DONE
    opened_key = "dateReceived" if stream == "maintenance" else "createdAt"
    closed_key = "dateCompleted" if stream == "maintenance" else "completedAt"
    open_n = overdue = closed = 0
    days = []
    for row in _work_rows(rows, user=user):
        received = _day(row.get(opened_key)) or _day(row.get("createdAt"))
        completed = _day(row.get(closed_key))
        cancelled = str(row.get("status") or "").lower() == "cancelled"
        if received is None or received > last or cancelled:
            continue
        if completed is None and str(row.get("status") or "").lower() in done:
            continue                              # done, with no date to place it by
        if completed is None or completed > last:
            open_n += 1
            due = _day(row.get("scheduledAt"))
            if due is not None and due < last:
                overdue += 1
        elif completed >= first:
            closed += 1
            days.append((completed - received).days)
    average = (Decimal(sum(days)) / len(days)) if days else None
    return {"open": open_n, "overdue": overdue, "closed": closed, "days_to_close": average}


def value_for(measure, client, first, last, *, unit=None, user=None, cache=None):
    """One period's number for a measure, or None when the period has
    nothing to say (an average with nothing in it)."""
    cache = cache if cache is not None else {}
    _, stream, _, _ = MEASURES[measure]
    if stream == "reservations":
        if measure == "bookings_created":
            rows = client.booked(first, last, unit)
            # A booking is a stay that holds: not a hold, not cancelled.
            return Decimal(sum(1 for r in rows if r.get("status") in STAYS
                               and (not unit or str(r.get("unitId")) == str(unit))))
        stays = client.stays(first, last, unit)
        nights, rent = stay_numbers(stays, first, last, unit=unit)
        if measure == "nights_booked":
            return Decimal(nights)
        if measure == "revenue":
            return _round(rent)
        if measure == "adr":
            return _round(rent / nights) if nights else None
        if "units" not in cache:
            cache["units"] = client.units()
        available = available_nights(cache["units"], first, last, unit=unit)
        if not available:
            return None
        if measure == "occupancy":
            return _round(Decimal(nights) * 100 / available, "0.1")
        return _round(rent / available)                     # revpar
    if stream == "reviews":
        rows = [r for r in client.reviews(first, unit)
                if (not unit or str(r.get("unitId")) == str(unit))
                and (d := _review_day(r)) is not None and first <= d <= last]
        if measure == "reviews_received":
            return Decimal(len(rows))
        ratings = [x for x in (_rating(r) for r in rows) if x is not None]
        return _round(sum(ratings) / len(ratings)) if ratings else None
    key = f"{stream}:{user or ''}"
    if key not in cache:
        cache[key] = (client.maintenance(user) if stream == "maintenance"
                      else client.housekeeping(user))
    numbers = work_numbers(cache[key], first, last, stream=stream, user=user)
    name = measure.split("_", 1)[1]
    if name == "days_to_close":
        return _round(numbers["days_to_close"], "0.1") if numbers["days_to_close"] is not None \
            else None
    return Decimal(numbers[name])


def plan_for(feed, client, today, *, periods=2, back=13, read_open=False, measure=None):
    """{(start, None): value} for the closed periods this read covers: the
    last two every day (late changes in Track follow), and as far back as
    `back` periods the first time. With `read_open`, the open period too, up
    to today. `measure` reads another field the same way (`refs.py`)."""
    kpi = feed.kpi
    measure = measure or feed.measure
    week_start = kpi.scorecard.week_start
    last_closed = P.previous_start(P.start_of(today, kpi.cadence, week_start), kpi.cadence,
                                   week_start)
    count = back if feed.last_success_at is None else periods
    starts = P.last_n(last_closed, kpi.cadence, count, week_start)
    if read_open:
        starts.append(P.start_of(today, kpi.cadence, week_start))
    cache = {}
    values = {}
    for start in starts:
        end = min(P.end_of(start, kpi.cadence), today)
        value = value_for(measure, client, start, end, unit=feed.unit_id or None,
                          user=feed.assignee_id or None, cache=cache)
        if value is not None and MEASURES[measure][2] == "duration" \
                and kpi.kind == "duration":
            # Days to close, in the KPI's own unit.
            value = _round(value * (24 if kpi.duration_unit == "hours" else 1440), "0.1")
        if value is not None:
            values[(start, None)] = value
    return values


#: Pages of work orders the picker reads for its list of people. The editor
#: waits on this read, and an account with years of work orders took minutes
#: to page through all of them (SkyRun Park City, 2026-11-04).
PICKER_PAGES = 2


def options(client) -> dict:
    """What the picker offers: the properties, and the Track users seen on
    the first pages of work orders (the reference documents no users list,
    so they are shown by id). Bounded: the editor waits on it."""
    units = [{"id": str(u.get("id")), "name": u.get("name") or f"Unit {u.get('id')}"}
             for u in client.units()]
    users = {}
    for stream in ("maintenance", "housekeeping"):
        try:
            rows = (client.maintenance(most_pages=PICKER_PAGES) if stream == "maintenance"
                    else client.housekeeping(most_pages=PICKER_PAGES))
        except TrackUnavailable:
            continue
        for row in rows:
            if row.get("userId"):
                users[str(row["userId"])] = users.get(str(row["userId"]), 0) + 1
    return {"units": sorted(units, key=lambda u: u["name"].lower()),
            "assignees": [{"id": k, "name": f"Track user {k}", "work_orders": n}
                          for k, n in sorted(users.items(), key=lambda kv: -kv[1])]}


def menu() -> list[dict]:
    return [{"key": k, "label": label, "stream": stream, "kind": kind, "scope": scope}
            for k, (label, stream, kind, scope) in MEASURES.items()]


def check_fits(kpi, measure):
    if measure not in MEASURES:
        raise TrackRefused("Choose a measure from the list.")
    if kpi.per_person:
        raise TrackRefused(f"{kpi.name} has a reading per person; a Track measure is one "
                           "number, for the company or one property or assignee.")
    kind = MEASURES[measure][2]
    if kpi.kind not in FITS[kind]:
        need = {"percent": "Percent", "money": "Money", "count": "Count or Number",
                "rating": "Rating or Number", "duration": "Duration or Number"}[kind]
        raise TrackRefused(f"{MEASURES[measure][0]} fits a KPI of kind {need}; "
                           f"{kpi.name} is {kpi.get_kind_display()}.")
