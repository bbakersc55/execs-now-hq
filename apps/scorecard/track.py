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
"""

from __future__ import annotations

import base64
import json
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


class TrackUnavailable(Exception):
    """Track could not be reached, or refused. Said in words."""


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

    def __init__(self, domain, key, secret, *, transport=None, sleep=time.sleep,
                 clock=time.monotonic):
        self.base = base_url(domain)
        self.auth = "Basic " + base64.b64encode(f"{key}:{secret}".encode()).decode()
        # Looked up when made, not when defined, so a test's stand-in applies.
        self.transport = transport or globals()["http_transport"]
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
            status, headers, body = self.transport(url, {"Authorization": self.auth,
                                                         "Accept": "application/json"})
            if status == 429 and attempt < RETRIES:
                wait = headers.get("Retry-After") or headers.get("retry-after") or 60
                try:
                    wait = min(300.0, float(wait))
                except ValueError:
                    wait = 60.0
                self.sleep(wait)
                continue
            break
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

    def collection(self, path, key, params=None):
        """Every row of a paged collection."""
        rows, page = [], 1
        while page <= MOST_PAGES:
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

    def maintenance(self, user=None):
        return self.collection("/pms/maintenance/work-orders", "workOrders",
                               {"userId": user} if user else None)

    def housekeeping(self, user=None):
        return self.collection("/pms/housekeeping/work-orders", "nodes",
                               {"userId": user} if user else None)


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


def options(client) -> dict:
    """What the picker offers: the properties, and the Track users seen on
    recent work orders (the reference documents no users list, so they are
    shown by id)."""
    units = [{"id": str(u.get("id")), "name": u.get("name") or f"Unit {u.get('id')}"}
             for u in client.units()]
    users = {}
    for stream in ("maintenance", "housekeeping"):
        try:
            rows = client.maintenance() if stream == "maintenance" else client.housekeeping()
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
