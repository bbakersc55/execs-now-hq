"""The HubSpot feed (M5 part 5, spec "Feeds"): a client company's HubSpot
account, read into a KPI's readings with a measure from a fixed menu.

Built to HubSpot's public API reference (developers.hubspot.com, read
2026-10-26), at the date-based version 2026-09: the semantic versions (v3
and older) stop being supported in September 2027. **Every path and field
name here is from that reference; none has been seen in a live account's
answer.** What the reference says, and what this code therefore assumes:

- Base URL `https://api.hubapi.com`. A private app's access token, sent as
  `Authorization: Bearer <token>`.
- Search: `POST /crm/objects/2026-09/{object}/search` with `filterGroups`
  (filters ANDed inside a group; at most five groups, six filters a group),
  `properties`, `limit` (200 at most) and `after`; it answers `total`,
  `results[].properties` and `paging.next.after`. At most 10,000 results a
  query. Datetime filters take epoch milliseconds (the reference's only
  example is 13 digits; its unit is not stated).
- Deal pipelines: `GET /crm/pipelines/2026-09/0-3` (`0-3` is deals); each
  stage's `metadata.probability` runs from 0.0 (Closed Lost) to 1.0 (Closed
  Won). `metadata.isClosed` is not reliable on its own (the reference's own
  example has a "Closed lost" stage with it "false").
- Owners: `GET /crm/owners/2026-09`; `id` is what `hubspot_owner_id` holds
  (`userId` is not).
- Rate limits: a private app has 100 requests every 10 seconds (Free and
  Starter; 190 on Professional and Enterprise) and an account 250,000 a day
  and up; search has its own five requests a second per account and sends
  none of the rate-limit headers. Going over is a 429 whose body names the
  policy (`DAILY`, or the ten-second one). `Retry-After` is not documented:
  read if present.

Streams and the fields each measure reads:

| Measure | Object | Fields |
|---|---|---|
| Deals created | deals | `createdate`, `hubspot_owner_id` |
| Deals won, lost, win rate | deals | `closedate`, `dealstage`, `hubspot_owner_id` |
| Pipeline value | deals | `dealstage`, `amount`, `hubspot_owner_id` |
| New contacts | contacts | `createdate`, `hubspot_owner_id` |
| Calls, emails, meetings logged | calls, emails, meetings | `hs_timestamp`, `hubspot_owner_id` |

Counts are the search's `total` (one request, `limit` 1); only pipeline value
reads rows, to add up `amount`. Everything that decides a number is a plain
function over the answers, so the tests run against recorded answers shaped
as the reference documents them (`tests/fixtures/hubspot/`), never HubSpot.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import date, datetime, time as day_time, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from . import periods as P

API = "https://api.hubapi.com"
VERSION = "2026-09"
#: The lowest tier's ten-second limit, and the share of it one read may use:
#: the client's other integrations share the same app limits and daily budget.
LIMIT, WINDOW_SECONDS, BUDGET = 100, 10, 40
#: Search's own limit is five a second per account; stay under it.
SEARCH_GAP = 0.25
#: Below this share of the day's budget left, a read stops rather than spend it.
DAILY_RESERVE = Decimal("0.05")
PAGE_SIZE = 200
MOST_RESULTS = 10_000
MOST_OWNER_PAGES = 20
RETRIES = 3
SCOPES = ("crm.objects.deals.read", "crm.objects.contacts.read", "crm.objects.owners.read")


class HubSpotUnavailable(Exception):
    """HubSpot could not be reached, or refused. Said in words."""


class HubSpotRefused(ValueError):
    """The measure asked for something that cannot be, said in words."""


# ------------------------------------------------------------- the menu

#: key -> (label, object, kind). Every measure is for the total or one owner.
MEASURES = {
    "deals_created": ("Deals created", "deals", "count"),
    "deals_won": ("Deals won", "deals", "count"),
    "deals_lost": ("Deals lost", "deals", "count"),
    "win_rate": ("Win rate (won of won and lost)", "deals", "percent"),
    "pipeline_value": ("Pipeline value", "deals", "money"),
    "new_contacts": ("New contacts", "contacts", "count"),
    "calls_logged": ("Calls logged", "calls", "count"),
    "emails_logged": ("Emails logged", "emails", "count"),
    "meetings_logged": ("Meetings logged", "meetings", "count"),
}
#: Kinds a KPI may be for each measure kind.
FITS = {"percent": {"percent"}, "money": {"money"}, "count": {"count", "number"}}
#: Read at each period's close and kept, as a sheet's cell is: HubSpot can't
#: say what the pipeline held on an earlier day.
SNAPSHOT = {"pipeline_value"}
#: How long after a period's close its snapshot may still be taken.
SNAPSHOT_GRACE = timedelta(days=2)
#: The datetime each counted object is placed in a period by.
WHEN = {"deals_created": "createdate", "deals_won": "closedate", "deals_lost": "closedate",
        "new_contacts": "createdate", "calls_logged": "hs_timestamp",
        "emails_logged": "hs_timestamp", "meetings_logged": "hs_timestamp"}


# ------------------------------------------------------------- the client

@dataclass
class Budget:
    """Requests made in the last ten seconds, by this process, for one
    company's token, and when its last search went. A read keeps to its
    share rather than spend the client's."""

    times: list = field(default_factory=list)
    last_search: float = -1e9
    sleep: object = time.sleep
    clock: object = time.monotonic

    def take(self, search=False):
        now = self.clock()
        self.times = [t for t in self.times if now - t < WINDOW_SECONDS]
        if len(self.times) >= BUDGET:
            self.sleep(max(0.0, WINDOW_SECONDS - (now - self.times[0])))
        if search:
            gap = SEARCH_GAP - (self.clock() - self.last_search)
            if gap > 0:
                self.sleep(gap)
            self.last_search = self.clock()
        self.times.append(self.clock())


_BUDGETS: dict = {}


def http_transport(method, url, headers, body):
    """One request. Returns (status, headers, body text)."""
    import requests

    try:
        response = requests.request(method, url, headers=headers, data=body, timeout=30)
    except requests.RequestException as exc:
        raise HubSpotUnavailable("HubSpot didn't answer. The read will try again later.") \
            from exc
    return response.status_code, dict(response.headers), response.text


def _header(headers, name):
    for key, value in (headers or {}).items():
        if key.lower() == name.lower():
            return value
    return None


def _int(value):
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


class HubSpotClient:
    """Read-only. One company's connection; its token is read from the
    company's own encrypted row and never leaves the Authorization header,
    never a log line or an error. Search is a POST, and still only reads."""

    def __init__(self, token, *, transport=None, sleep=time.sleep, clock=time.monotonic,
                 budget_key=None):
        self.auth = f"Bearer {token}"
        # Looked up when made, not when defined, so a test's stand-in applies.
        self.transport = transport or globals()["http_transport"]
        self.sleep = sleep
        key = budget_key or hashlib.sha256(token.encode()).hexdigest()
        self.budget = _BUDGETS.setdefault(key, Budget(sleep=sleep, clock=clock))
        self.calls = 0

    def request(self, method, path, params=None, body=None):
        url = f"{API}{path}" + (f"?{urlencode(params, doseq=True)}" if params else "")
        data = json.dumps(body) if body is not None else None
        search = path.endswith("/search")
        for attempt in range(RETRIES + 1):
            self.budget.take(search=search)
            self.calls += 1
            headers = {"Authorization": self.auth, "Accept": "application/json"}
            if data is not None:
                headers["Content-Type"] = "application/json"
            status, answer_headers, text = self.transport(method, url, headers, data)
            if status == 429:
                if self._policy(text) == "DAILY":
                    raise HubSpotUnavailable(
                        "HubSpot's daily API limit for this account is used up. The read "
                        "will try again tomorrow.")
                if attempt < RETRIES:
                    wait = _header(answer_headers, "Retry-After")
                    try:
                        wait = min(60.0, float(wait)) if wait is not None \
                            else (1.0 if search else float(WINDOW_SECONDS))
                    except ValueError:
                        wait = float(WINDOW_SECONDS)
                    self.sleep(wait)
                    continue
            break
        if status == 401:
            raise HubSpotUnavailable("HubSpot refused the access token. Check it on the company "
                                     "page and test the connection again.")
        if status == 403:
            raise HubSpotUnavailable(
                "HubSpot's token doesn't allow this read. In HubSpot, give the private app "
                f"these read scopes: {', '.join(SCOPES)}.")
        if status == 429:
            raise HubSpotUnavailable("HubSpot's request limit was reached. The read will try "
                                     "again later.")
        if status >= 400:
            raise HubSpotUnavailable(f"HubSpot answered {status}. The read will try again "
                                     "later.")
        self._mind_limits(answer_headers)
        try:
            return json.loads(text or "{}")
        except ValueError:
            raise HubSpotUnavailable("HubSpot's answer couldn't be read.") from None

    @staticmethod
    def _policy(text):
        try:
            return str((json.loads(text or "{}") or {}).get("policyName") or "").upper()
        except (ValueError, AttributeError):
            return ""

    def _mind_limits(self, headers):
        """The rate-limit headers, where HubSpot sends them (not on search):
        wait out a nearly spent ten seconds, and leave the client the last
        of their day's budget."""
        remaining = _int(_header(headers, "X-HubSpot-RateLimit-Remaining"))
        interval = _int(_header(headers, "X-HubSpot-RateLimit-Interval-Milliseconds"))
        if remaining is not None and remaining <= 2:
            self.sleep((interval or WINDOW_SECONDS * 1000) / 1000)
        daily = _int(_header(headers, "X-HubSpot-RateLimit-Daily"))
        left = _int(_header(headers, "X-HubSpot-RateLimit-Daily-Remaining"))
        if daily and left is not None and Decimal(left) < Decimal(daily) * DAILY_RESERVE:
            raise HubSpotUnavailable(
                "HubSpot's daily API limit for this account is nearly used up; the read "
                "leaves the rest to the client and will try again tomorrow.")

    # The streams.
    def test(self) -> str:
        found = len(self.pipelines())
        return f"Connected: {found} deal pipeline{'' if found == 1 else 's'}."

    def pipelines(self):
        return self.request("GET", f"/crm/pipelines/{VERSION}/0-3").get("results") or []

    def owners(self):
        rows, after = [], None
        for _ in range(MOST_OWNER_PAGES):
            got = self.request("GET", f"/crm/owners/{VERSION}",
                               {"limit": 100, **({"after": after} if after else {})})
            rows.extend(got.get("results") or [])
            after = ((got.get("paging") or {}).get("next") or {}).get("after")
            if not after:
                break
        return rows

    def search(self, obj, filters, properties=(), limit=1, after=None):
        body = {"filterGroups": [{"filters": filters}], "properties": list(properties),
                "limit": limit}
        if after:
            body["after"] = after
        return self.request("POST", f"/crm/objects/{VERSION}/{obj}/search", body=body)

    def count(self, obj, filters) -> int:
        return int(self.search(obj, filters).get("total") or 0)

    def rows(self, obj, filters, properties):
        out, after = [], None
        while True:
            got = self.search(obj, filters, properties, limit=PAGE_SIZE, after=after)
            if int(got.get("total") or 0) > MOST_RESULTS:
                raise HubSpotRefused(
                    f"HubSpot finds more than {MOST_RESULTS:,} {obj} for this measure, more "
                    "than its search will page through. Choose one owner or one stage.")
            out.extend(got.get("results") or [])
            after = ((got.get("paging") or {}).get("next") or {}).get("after")
            if not after:
                return out


# ------------------------------------------------------------- the arithmetic

def _probability(stage):
    try:
        return Decimal(str((stage.get("metadata") or {}).get("probability")))
    except (InvalidOperation, TypeError):
        return None


def stage_sets(pipelines) -> dict:
    """Every deal stage's id by outcome: won (probability 1.0), lost (0.0),
    and open (everything else, or a stage with no probability)."""
    out = {"won": set(), "lost": set(), "open": set()}
    for pipeline in pipelines:
        if pipeline.get("archived"):
            continue
        for stage in pipeline.get("stages") or []:
            if stage.get("archived"):
                continue
            p = _probability(stage)
            key = "won" if p == 1 else "lost" if p == 0 else "open"
            out[key].add(str(stage.get("id")))
    return out


def stage_choices(pipelines) -> list[dict]:
    """The open stages, for pipeline value's picker, named by pipeline when
    there is more than one."""
    live = [p for p in pipelines if not p.get("archived")]
    many = len(live) > 1
    out = []
    for pipeline in sorted(live, key=lambda p: int(p.get("displayOrder") or 0)):
        for stage in sorted(pipeline.get("stages") or [],
                            key=lambda s: int(s.get("displayOrder") or 0)):
            p = _probability(stage)
            if stage.get("archived") or p in (0, 1):
                continue
            label = stage.get("label") or str(stage.get("id"))
            out.append({"id": str(stage.get("id")),
                        "name": f"{pipeline.get('label')}: {label}" if many else label})
    return out


def window_ms(first: date, last: date, zone: str) -> tuple[int, int]:
    """The period first..last as epoch milliseconds, from midnight starting
    `first` to midnight ending `last`, in the practice's own time zone: a
    period closes at the practice's midnight, as a week does on the board."""
    tz = ZoneInfo(zone or "UTC")
    start = datetime.combine(first, day_time.min, tzinfo=tz)
    end = datetime.combine(last + timedelta(days=1), day_time.min, tzinfo=tz)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def _between(prop, start_ms, end_ms):
    return [{"propertyName": prop, "operator": "GTE", "value": str(start_ms)},
            {"propertyName": prop, "operator": "LT", "value": str(end_ms)}]


def _owner(owner):
    return [{"propertyName": "hubspot_owner_id", "operator": "EQ", "value": str(owner)}] \
        if owner else []


def _money(value) -> Decimal:
    try:
        found = Decimal(str(value).replace(",", "")) if value not in (None, "") else Decimal(0)
    except InvalidOperation:
        return Decimal(0)
    return found if found.is_finite() else Decimal(0)


def _round(value, places="0.01"):
    return Decimal(value).quantize(Decimal(places))


def _stages(client, cache):
    if "stages" not in cache:
        cache["stages"] = stage_sets(client.pipelines())
    return cache["stages"]


def _closed(client, cache, outcome, window, owner):
    ids = sorted(_stages(client, cache)[outcome])
    if not ids:
        word = "Closed Won (100%)" if outcome == "won" else "Closed Lost (0%)"
        raise HubSpotRefused(f"No deal stage in HubSpot is {word}, so there are no "
                             f"{outcome} deals to count.")
    return client.count("deals", _between("closedate", *window) + _owner(owner)
                        + [{"propertyName": "dealstage", "operator": "IN", "values": ids}])


def value_for(measure, client, first, last, *, zone="UTC", owner=None, stage=None,
              cache=None):
    """One period's number for a measure, or None when the period has
    nothing to say (a win rate with nothing closed)."""
    cache = cache if cache is not None else {}
    window = window_ms(first, last, zone)
    if measure in ("deals_won", "deals_lost"):
        return Decimal(_closed(client, cache, measure.removeprefix("deals_"), window, owner))
    if measure == "win_rate":
        won = _closed(client, cache, "won", window, owner)
        lost = _closed(client, cache, "lost", window, owner)
        return _round(Decimal(won) * 100 / (won + lost), "0.1") if won + lost else None
    if measure == "pipeline_value":
        open_ids = _stages(client, cache)["open"]
        if stage and str(stage) not in open_ids:
            raise HubSpotRefused("The deal stage this KPI reads is no longer an open stage in "
                                 "HubSpot. Choose its stage again.")
        ids = [str(stage)] if stage else sorted(open_ids)
        if not ids:
            return Decimal(0)
        rows = client.rows("deals", [{"propertyName": "dealstage", "operator": "IN",
                                      "values": ids}] + _owner(owner), ["amount", "dealstage"])
        return _round(sum((_money((r.get("properties") or {}).get("amount")) for r in rows),
                          Decimal(0)))
    obj = MEASURES[measure][1]
    return Decimal(client.count(obj, _between(WHEN[measure], *window) + _owner(owner)))


def plan_for(feed, client, today, *, zone="UTC", periods=2, back=13, read_open=False):
    """{(start, None): value} for the closed periods this read covers: the
    last two every day (late changes in HubSpot follow), and as far back as
    `back` periods the first time. Pipeline value is the latest closed
    period's alone, and only within two days of its close. With `read_open`,
    the open period too, up to today."""
    kpi = feed.kpi
    week_start = kpi.scorecard.week_start
    last_closed = P.previous_start(P.start_of(today, kpi.cadence, week_start), kpi.cadence,
                                   week_start)
    if feed.measure in SNAPSHOT:
        starts = [] if today - P.end_of(last_closed, kpi.cadence) > SNAPSHOT_GRACE \
            else [last_closed]
    else:
        count = back if feed.last_success_at is None else periods
        starts = P.last_n(last_closed, kpi.cadence, count, week_start)
    if read_open:
        starts.append(P.start_of(today, kpi.cadence, week_start))
    cache = {}
    values = {}
    for start in starts:
        value = value_for(feed.measure, client, start,
                          min(P.end_of(start, kpi.cadence), today), zone=zone,
                          owner=feed.owner_id or None, stage=feed.stage_id or None, cache=cache)
        if value is not None:
            values[(start, None)] = value
    return values


def options(client) -> dict:
    """What the picker offers: the owners, by name, and the open deal stages."""
    owners = []
    for row in client.owners():
        if row.get("archived"):
            continue
        name = " ".join(x for x in (row.get("firstName"), row.get("lastName")) if x).strip()
        owners.append({"id": str(row.get("id")), "name": name or row.get("email")
                       or f"Owner {row.get('id')}", "email": row.get("email") or ""})
    return {"owners": sorted(owners, key=lambda o: o["name"].lower()),
            "stages": stage_choices(client.pipelines())}


def menu() -> list[dict]:
    return [{"key": k, "label": label, "object": obj, "kind": kind,
             "snapshot": k in SNAPSHOT}
            for k, (label, obj, kind) in MEASURES.items()]


def check_fits(kpi, measure):
    if measure not in MEASURES:
        raise HubSpotRefused("Choose a measure from the list.")
    if kpi.per_person:
        raise HubSpotRefused(f"{kpi.name} has a reading per person; a HubSpot measure is one "
                             "number, for the company or one owner.")
    kind = MEASURES[measure][2]
    if kpi.kind not in FITS[kind]:
        need = {"percent": "Percent", "money": "Money", "count": "Count or Number"}[kind]
        raise HubSpotRefused(f"{MEASURES[measure][0]} fits a KPI of kind {need}; "
                             f"{kpi.name} is {kpi.get_kind_display()}.")
