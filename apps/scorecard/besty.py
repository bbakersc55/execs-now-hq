"""The Besty feed (M5 part 6, spec "Feeds"): a client company's Besty
account, read into a KPI's readings with a measure from a fixed menu.

Besty is read through its MCP server, `https://mcp.getbesty.ai/mcp`, over
Streamable HTTP, with a long-lived read-only token as a Bearer header. **Seen
in a live account's answers (2026-10-28), not only documented:**

- `initialize` (JSON-RPC, POST) answers as a one-event SSE stream and sets
  `Mcp-Session-Id`; `notifications/initialized` answers 202 with no body;
  `tools/list` and `tools/call` answer as SSE too, and every call after
  `initialize` carries the session id and the Bearer header.
- A tool's answer is `result.content[0].text`, itself JSON:
  `{"ok": [{"mode": "inline", "rows": [...], "warnings": [...]}], "failed":
  [...]}`. A refused call is `result.isError` with the reason as plain text
  (an unknown field, a malformed measure), or a JSON-RPC `error`.
- Large answers are `"mode": "file"` with a presigned link
  (`presigned_url`) valid 24 hours, **in Parquet**, not NDJSON. This feed
  never asks for one: every measure uses Besty's own aggregation grammar
  (`aggregation.measures` like `count(*)`, `sum(revenue_amount)`,
  `avg(rating)`; `filters`; `dimensions`), whose answers are small and
  inline. A gzipped NDJSON link is fetched (without the token) and read
  then discarded, should one come; a Parquet one is refused in words.
- Aggregated numbers come as strings (`"count": "86"`, `"avg_rating":
  "4.94"`); `time.granularity` does not bucket, so each period is its own
  call, with `time_range` set to the period.

Windows Besty enforces, from `describe_export_schemas`: ops tasks, threads
and calls 365 days; reviews and upsells 730; messages 31 (a longer period is
read in pieces). `docs/besty_feed.md` lists every tool and column.

Everything that decides a number is a plain function over the answers, so
the tests run against answers in the envelopes recorded from the live
server (`tests/fixtures/besty/`), never against Besty.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import date, datetime, time as day_time, timedelta, timezone as dt_timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from . import periods as P

URL = "https://mcp.getbesty.ai/mcp"
PROTOCOL = "2025-03-26"
#: Besty documents no rate limit; one read keeps to this many calls a
#: minute for a company, and to this many calls in all.
LIMIT, WINDOW_SECONDS = 60, 60
MOST_CALLS = 400
RETRIES = 3
#: Besty's own windows (describe_export_schemas' "limits", and
#: compute_response_time's refusal of 92 days): a longer period is read in
#: pieces and added up.
MOST_DAYS = {"export_ops_tasks": 365, "export_upsell_events": 730, "export_reviews": 730,
             "compute_response_time": 90, "export_messages": 31, "export_calls": 365}
TASKS_DAYS = MOST_DAYS["export_ops_tasks"]
#: Owner threads a messages call names at once (its filter pins 100).
THREADS_A_CALL = 100
#: The tools the menu reads; a connection whose token can't see one says so.
TOOLS = ("export_ops_tasks", "export_upsell_events", "compute_response_time",
         "export_reviews", "export_messages", "export_owners", "export_calls", "list_users")


class BestyUnavailable(Exception):
    """Besty could not be reached, or refused. Said in words."""


class BestyRefused(ValueError):
    """The measure asked for something that cannot be, said in words."""


# ------------------------------------------------------------- the menu

#: key -> (label, tool, kind, scope). scope: "member" (a team member or
#: total), "upsell" (one upsell type or total), "owner" (a team member, an
#: owner, both or total), "total". The KPI's kind must fit.
MEASURES = {
    "tasks_open": ("Ops tasks open", "export_ops_tasks", "count", "member"),
    "tasks_overdue": ("Ops tasks overdue", "export_ops_tasks", "count", "member"),
    "tasks_completed": ("Ops tasks completed", "export_ops_tasks", "count", "member"),
    "tasks_days_to_close": ("Ops tasks: average days to close (tasks made by a person)",
                            "export_ops_tasks", "duration", "member"),
    "tasks_work_time": ("Ops tasks: average tracked work time", "export_ops_tasks",
                        "duration", "member"),
    "upsell_revenue": ("Upsell revenue", "export_upsell_events", "money", "upsell"),
    "upsell_count": ("Upsells sold", "export_upsell_events", "count", "upsell"),
    "response_time": ("Guest response time (average)", "compute_response_time", "duration",
                      "responder"),
    "reviews_received": ("Reviews received", "export_reviews", "count", "total"),
    "average_rating": ("Average rating (out of 5)", "export_reviews", "rating", "total"),
    "owner_messages": ("Messages to owners (sent by people)", "export_messages", "count",
                       "owner"),
    "owners_contacted": ("Owners contacted", "export_messages", "count", "member"),
    "calls_answered": ("Calls answered", "export_calls", "count", "member"),
}
#: Kinds a KPI may be for each measure kind ("rating" also fits a number).
FITS = {"percent": {"percent"}, "money": {"money"}, "count": {"count", "number"},
        "rating": {"rating", "number"}, "duration": {"duration", "number"}}
UPSELL_TYPES = {
    "booking_booster": "Booking booster", "early_checkin": "Early check-in",
    "late_checkout": "Late checkout", "custom_upsell": "Custom upsell",
    "damage_waiver": "Damage waiver", "workflow_upsell": "Sold by a workflow",
}
#: response_time's responder choices beside one team member.
RESPONDERS = {"": "Everyone, autopilot included", "people": "People only (no autopilot)",
              "autopilot": "Autopilot only"}


# ------------------------------------------------------------- the client

@dataclass
class Budget:
    """Calls made in the last minute, by this process, for one company."""

    times: list = field(default_factory=list)
    sleep: object = time.sleep
    clock: object = time.monotonic

    def take(self):
        now = self.clock()
        self.times = [t for t in self.times if now - t < WINDOW_SECONDS]
        if len(self.times) >= LIMIT:
            self.sleep(max(0.0, WINDOW_SECONDS - (now - self.times[0])))
        self.times.append(self.clock())


_BUDGETS: dict = {}


def http_transport(method, url, headers, body):
    """One request. Returns (status, headers, body text)."""
    import requests

    try:
        response = requests.request(method, url, headers=headers, data=body, timeout=60)
    except requests.RequestException as exc:
        raise BestyUnavailable("Besty didn't answer. The read will try again later.") from exc
    return response.status_code, dict(response.headers), response.text


def http_fetch(url):
    """A download link's bytes, fetched with no Authorization header: the
    link is presigned, and the token never goes anywhere but Besty."""
    import requests

    try:
        response = requests.get(url, timeout=60)
    except requests.RequestException as exc:
        raise BestyUnavailable("Besty's download link didn't answer. The read will try "
                               "again later.") from exc
    if response.status_code >= 400:
        raise BestyUnavailable("Besty's download link had expired. The read will try "
                               "again later.")
    return response.content


def _header(headers, name):
    for key, value in (headers or {}).items():
        if key.lower() == name.lower():
            return value
    return None


def _message(text):
    """The JSON-RPC message in an answer: plain JSON, or the last `data:`
    event of an SSE stream."""
    text = text or ""
    if text.lstrip().startswith("{"):
        try:
            return json.loads(text)
        except ValueError:
            return None
    found = None
    for line in text.splitlines():
        if line.startswith("data:") and line[5:].strip():
            try:
                found = json.loads(line[5:].strip())
            except ValueError:
                continue
    return found


class BestyClient:
    """Read-only. One company's connection; its token is read from the
    company's own encrypted row and never leaves the Authorization header
    sent to Besty, never a log line, an error or a download request."""

    def __init__(self, token, *, transport=None, fetch=None, sleep=time.sleep,
                 clock=time.monotonic, budget_key=None):
        self.auth = f"Bearer {token}"
        # Looked up when made, not when defined, so a test's stand-in applies.
        self.transport = transport or globals()["http_transport"]
        self.fetch = fetch or globals()["http_fetch"]
        self.sleep = sleep
        key = budget_key or hashlib.sha256(token.encode()).hexdigest()
        self.budget = _BUDGETS.setdefault(key, Budget(sleep=sleep, clock=clock))
        self.session = None
        self.calls = 0
        self._id = 0

    def _post(self, body):
        if self.calls >= MOST_CALLS:
            raise BestyUnavailable("This read asked Besty more than it should in one go; it "
                                   "stopped and will carry on tomorrow.")
        headers = {"Authorization": self.auth, "Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream"}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        data = json.dumps(body)
        for attempt in range(RETRIES + 1):
            self.budget.take()
            self.calls += 1
            status, answer_headers, text = self.transport("POST", URL, headers, data)
            if status == 429 and attempt < RETRIES:
                wait = _header(answer_headers, "Retry-After")
                try:
                    wait = min(60.0, float(wait)) if wait is not None else 10.0
                except ValueError:
                    wait = 10.0
                self.sleep(wait)
                continue
            break
        if status in (401, 403):
            raise BestyUnavailable("Besty refused the token. Check it on the company page and "
                                   "test the connection again.")
        if status == 404 and self.session:
            raise _SessionGone()
        if status == 429:
            raise BestyUnavailable("Besty's request limit was reached. The read will try again "
                                   "later.")
        if status >= 400:
            raise BestyUnavailable(f"Besty answered {status}. The read will try again later.")
        return answer_headers, text

    def _rpc(self, method, params=None):
        self._id += 1
        body = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            body["params"] = params
        _, text = self._post(body)
        message = _message(text)
        if not isinstance(message, dict):
            raise BestyUnavailable("Besty's answer couldn't be read.")
        if message.get("error"):
            raise BestyRefused(_said(message["error"].get("message")))
        return message.get("result") or {}

    def open(self):
        """initialize, then notifications/initialized: a session for this read."""
        if self.session:
            return
        self._id += 1
        headers, text = self._post({
            "jsonrpc": "2.0", "id": self._id, "method": "initialize",
            "params": {"protocolVersion": PROTOCOL, "capabilities": {},
                       "clientInfo": {"name": "execs-now-hq", "version": "1"}}})
        message = _message(text)
        if not isinstance(message, dict) or "result" not in message:
            raise BestyUnavailable("Besty's answer to connecting couldn't be read.")
        self.session = _header(headers, "Mcp-Session-Id")
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def tools(self) -> list[str]:
        self.open()
        return [t.get("name") for t in self._rpc("tools/list").get("tools") or []]

    def call(self, tool, arguments) -> dict:
        """One tool's answer: the first `ok` entry, or Besty's refusal in words."""
        self.open()
        try:
            result = self._rpc("tools/call", {"name": tool, "arguments": arguments})
        except _SessionGone:
            self.session = None                     # expired: one new session
            self.open()
            result = self._rpc("tools/call", {"name": tool, "arguments": arguments})
        text = "".join(c.get("text") or "" for c in result.get("content") or []
                       if c.get("type") == "text")
        if result.get("isError"):
            raise BestyRefused(f"Besty refused the read: {_said(text)}")
        try:
            got = json.loads(text or "{}")
        except ValueError:
            raise BestyUnavailable("Besty's answer couldn't be read.") from None
        if isinstance(got, dict) and "ok" in got:
            if got.get("ok"):
                return got["ok"][0]
            failed = (got.get("failed") or [{}])[0]
            raise BestyRefused(f"Besty refused the read: "
                               f"{_said(failed.get('error') or failed.get('message'))}")
        return got if isinstance(got, dict) else {"rows": got}

    def rows(self, tool, arguments) -> list[dict]:
        """A tool's rows, inline or from its download link (read, then
        dropped: nothing of it is kept beyond the number it makes)."""
        got = self.call(tool, arguments)
        if got.get("mode", "inline") == "inline":
            return list(got.get("rows") or [])
        link = got.get("presigned_url") or got.get("download_url") or got.get("url")
        form = str(got.get("format") or "").lower()
        if not link or form not in ("ndjson", "jsonl", "ndjson.gz", "jsonl.gz"):
            raise BestyRefused(
                f"Besty sent this read as a {form or 'download'} file, more than the feed "
                "reads at once. Choose a shorter cadence or one team member.")
        raw = self.fetch(link)
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]

    def test(self) -> str:
        names = self.tools()
        missing = [t for t in TOOLS if t not in names]
        if missing:
            return (f"Connected: {len(names)} tools, but not {', '.join(missing)}; the "
                    "measures that read those won't work with this token.")
        return f"Connected: {len(names)} read-only tools."


class _SessionGone(Exception):
    """Besty no longer knows the session (404): open a new one."""


def _said(text) -> str:
    """Besty's own words, kept short, with no token in them."""
    return " ".join(str(text or "no reason given").split())[:300]


# ------------------------------------------------------------- the arithmetic

def window(first: date, last: date, zone: str, now: datetime | None = None):
    """The period first..last as ISO instants, from midnight starting
    `first` to midnight ending `last`, in the practice's own time zone; an
    open period ends now."""
    tz = ZoneInfo(zone or "UTC")
    start = datetime.combine(first, day_time.min, tzinfo=tz)
    end = datetime.combine(last + timedelta(days=1), day_time.min, tzinfo=tz)
    if now is not None and now < end:
        end = max(start, now)
    return start.astimezone(dt_timezone.utc), end.astimezone(dt_timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _number(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        found = Decimal(str(value))
    except InvalidOperation:
        return None
    return found if found.is_finite() else None


def _round(value, places="0.01"):
    return Decimal(value).quantize(Decimal(places))


def _moment(value) -> datetime | None:
    if not value:
        return None
    try:
        found = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return found if found.tzinfo else found.replace(tzinfo=dt_timezone.utc)


def _agg(measures, *, filters=(), dimensions=(), limit=None):
    out = {"measures": list(measures)}
    if filters:
        out["filters"] = list(filters)
    if dimensions:
        out["dimensions"] = list(dimensions)
    if limit:
        out["limit"] = limit
    return out


def _first(rows, key) -> Decimal:
    return (_number(rows[0].get(key)) if rows else None) or Decimal(0)


def _tasks(member):
    return {"assignee_subuser_ids": [member]} if member else {}


def tasks_open(client, start, end, member=None, *, overdue=False):
    """Tasks open at the period's end: made before it, and not completed by
    then (Besty's `completed_at`; a task marked done with no completion time
    is not counted open). Overdue: open, and due before then. Besty reads
    at most 365 days back, so a task made earlier than that isn't seen."""
    since = end - timedelta(days=TASKS_DAYS)
    base = {"time_range": {"field": "created_at", "since": _iso(since), "until": _iso(end)}}
    if member:
        base["filter"] = _tasks(member)
    due = [{"field": "due_at", "op": "lt", "value": _iso(end)}] if overdue else []
    pending = client.rows("export_ops_tasks", {**base, "aggregation": _agg(
        ["count(*)"], filters=[{"field": "completed_at", "op": "is_null"},
                               {"field": "status", "op": "neq", "value": "done"}] + due)})
    later = client.rows("export_ops_tasks", {**base, "aggregation": _agg(
        ["count(*)"], filters=[{"field": "completed_at", "op": "gte", "value": _iso(end)}]
        + due)})
    return _first(pending, "count") + _first(later, "count")


def _completed(start, end, member, **extra_filter):
    out = {"time_range": {"field": "completed_at", "since": _iso(start), "until": _iso(end)}}
    flt = {**_tasks(member), **extra_filter}
    if flt:
        out["filter"] = flt
    return out


def tasks_days_to_close(client, start, end, member=None):
    """Average days from made to completed, of tasks completed in the period
    that a person made (`created_by` person). Besty doesn't give this for
    automation-made tasks: their creation time is often after completion.
    Grouped by both times, so the answer is small; negative spans dropped."""
    rows = _spread(client, "export_ops_tasks", start, end, lambda a, b: {
        **_completed(a, b, member, created_by=["person"], status=["done"]),
        "aggregation": _agg(["count(*)"], dimensions=["created_at", "completed_at"],
                            limit=10_000)})
    total = Decimal(0)
    count = 0
    for row in rows:
        made, done = _moment(row.get("created_at")), _moment(row.get("completed_at"))
        n = int(_number(row.get("count")) or 0)
        if made is None or done is None or done < made or not n:
            continue
        total += Decimal((done - made).total_seconds()) / 86_400 * n
        count += n
    return (total / count) * 1440 if count else None            # minutes


def _spread(client, tool, start, end, arguments):
    """Every piece's rows, for a period longer than the tool's window.
    `arguments(since, until)` makes one piece's call."""
    rows = []
    for since, until in _pieces(start, end, MOST_DAYS[tool]):
        rows.extend(client.rows(tool, arguments(since, until)))
    return rows


def _total(rows, key) -> Decimal:
    return sum(((_number(r.get(key)) or Decimal(0)) for r in rows), Decimal(0))


def _between(field_name, since, until):
    return {"field": field_name, "since": _iso(since), "until": _iso(until)}


def value_for(measure, client, first, last, *, zone="UTC", member=None, member_name=None,
              owner=None, param=None, now=None, cache=None):
    """One period's number for a measure, or None when the period has
    nothing to say (an average with nothing in it). A duration is in
    minutes; `plan_for` puts it in the KPI's own unit."""
    cache = cache if cache is not None else {}
    start, end = window(first, last, zone, now)
    if measure in ("tasks_open", "tasks_overdue"):
        return tasks_open(client, start, end, member, overdue=measure == "tasks_overdue")
    if measure == "tasks_completed":
        rows = _spread(client, "export_ops_tasks", start, end, lambda a, b: {
            **_completed(a, b, member, status=["done"]), "aggregation": _agg(["count(*)"])})
        return _total(rows, "count")
    if measure == "tasks_days_to_close":
        return tasks_days_to_close(client, start, end, member)
    if measure == "tasks_work_time":
        rows = _spread(client, "export_ops_tasks", start, end, lambda a, b: {
            **_completed(a, b, member, status=["done"]),
            "aggregation": _agg(["avg(time_total_seconds)", "count(*)"], filters=[
                {"field": "time_total_seconds", "op": "gt", "value": 0}])})
        count = _total(rows, "count")
        if not count:
            return None
        seconds = sum(((_number(r.get("avg_time_total_seconds")) or Decimal(0))
                       * (_number(r.get("count")) or 0) for r in rows), Decimal(0)) / count
        return seconds / 60
    if measure in ("upsell_revenue", "upsell_count"):
        flt = {"only_acceptances": True}
        if param:
            flt["upsell_type"] = [param]
        rows = _spread(client, "export_upsell_events", start, end, lambda a, b: {
            "time_range": _between("created_at", a, b), "filter": flt,
            "aggregation": _agg(["sum(revenue_amount)", "count(*)"])})
        if measure == "upsell_count":
            return _total(rows, "count")
        return _round(_total(rows, "sum_revenue_amount"))
    if measure == "response_time":
        return response_time(client, start, end, member=member, name=member_name,
                             who=param or "")
    if measure in ("reviews_received", "average_rating"):
        rows = _spread(client, "export_reviews", start, end, lambda a, b: {
            "time_range": _between("reviewed_at", a, b),
            "aggregation": _agg(["avg(rating)", "count(*)"],
                                dimensions=["rating_denominator"])})
        return review_numbers(rows)[0 if measure == "reviews_received" else 1]
    if measure in ("owner_messages", "owners_contacted"):
        return owner_contact(client, start, end, member=member, owner=owner,
                             distinct=measure == "owners_contacted", cache=cache)
    if measure == "calls_answered":
        flt = {"status": ["answered"]}
        if member:
            flt["answered_by_subuser_ids"] = [member]
        rows = _spread(client, "export_calls", start, end, lambda a, b: {
            "time_range": _between("created_at", a, b), "filter": flt,
            "aggregation": _agg(["count(*)"])})
        return _total(rows, "count")
    raise BestyRefused("Choose a measure from the list.")


def review_numbers(rows):
    """(reviews, average rating out of 5): each denominator's average put
    out of 5 (a 10-point channel halves), weighted by its count."""
    count, total = 0, Decimal(0)
    for row in rows:
        n = int(_number(row.get("count")) or 0)
        avg = _number(row.get("avg_rating"))
        out_of = _number(row.get("rating_denominator")) or Decimal(5)
        if not n:
            continue
        count += n
        if avg is not None and out_of:
            total += avg * 5 / out_of * n
    average = _round(total / count) if count else None
    return Decimal(count), average


def response_time(client, start, end, *, member=None, name=None, who=""):
    """Average minutes to answer a guest, Besty's dashboard figure: for a
    team member, theirs; else every responder's (or people's, or
    autopilot's), weighted by replies. Besty reads 90 days at a time, so a
    quarter is two pieces, each with Besty's own outlier rule."""
    rows = _spread(client, "compute_response_time", start, end, lambda a, b: {
        "since": _iso(a), "until": _iso(b), "aggregate_window": True})
    picked = []
    for row in rows:
        label = str(row.get("responder_label") or "")
        robot = label.lower() == "autopilot"
        if member:
            if label not in {str(member), str(name or "")} or not label:
                continue
        elif who == "people" and robot:
            continue
        elif who == "autopilot" and not robot:
            continue
        picked.append(row)
    count = sum(int(_number(r.get("response_count")) or 0) for r in picked)
    if not count:
        return None
    total = sum(((_number(r.get("avg_response_minutes")) or Decimal(0))
                 * int(_number(r.get("response_count")) or 0) for r in picked), Decimal(0))
    return total / count


def owner_threads(client, cache) -> dict:
    """{owner id: thread id} of the account's property owners."""
    if "owners" not in cache:
        rows = client.rows("export_owners", {"fields": ["owner_id", "name", "thread_id"]})
        cache["owners"] = {str(r.get("owner_id")): r.get("thread_id") for r in rows
                           if r.get("thread_id")}
    return cache["owners"]


def _pieces(start, end, days):
    """start..end in windows Besty accepts (messages: 31 days at most)."""
    while start < end:
        stop = min(end, start + timedelta(days=days))
        yield start, stop
        start = stop


def owner_contact(client, start, end, *, member=None, owner=None, distinct=False, cache=None):
    """Messages people sent on property owners' threads in the period (not
    automations or autopilot), for one team member or all, one owner or
    all; with `distinct`, how many owners got at least one."""
    threads = owner_threads(client, cache if cache is not None else {})
    if owner:
        if str(owner) not in threads:
            raise BestyRefused("The owner this KPI reads is no longer in Besty. Choose the "
                               "owner again.")
        ids = [int(threads[str(owner)])]
    else:
        ids = sorted({int(t) for t in threads.values()})
    if not ids:
        return Decimal(0)
    filters = [{"field": "subuser_id", "op": "eq", "value": member}] if member else []
    count, seen = Decimal(0), set()
    for since, until in _pieces(start, end, MOST_DAYS["export_messages"]):
        for i in range(0, len(ids), THREADS_A_CALL):
            rows = client.rows("export_messages", {
                "time_range": {"field": "created_at", "since": _iso(since),
                               "until": _iso(until)},
                "filter": {"thread_ids": ids[i:i + THREADS_A_CALL], "is_incoming": False,
                           "sender_type": ["host", "host_external"]},
                "aggregation": _agg(["count(*)"], filters=filters,
                                    dimensions=["thread_id"] if distinct else ())})
            if distinct:
                seen.update(str(r.get("thread_id")) for r in rows
                            if int(_number(r.get("count")) or 0))
            else:
                count += _first(rows, "count")
    return Decimal(len(seen)) if distinct else count


def in_unit(minutes, kpi):
    """A duration in minutes, in the KPI's own unit (a Number KPI: minutes)."""
    if kpi.kind != "duration":
        return _round(minutes, "0.1")
    per = {"days": 1440, "hours": 60}.get(kpi.duration_unit, 1)
    return _round(Decimal(minutes) / per, "0.1")


def plan_for(feed, client, today, *, zone="UTC", periods=2, back=13, read_open=False,
             measure=None, now=None):
    """{(start, None): value} for the closed periods this read covers: the
    last two every day (late changes in Besty follow), and as far back as
    `back` periods the first time. With `read_open`, the open period too, up
    to now. `measure` reads another field the same way (`refs.py`)."""
    kpi = feed.kpi
    measure = measure or feed.measure
    week_start = kpi.scorecard.week_start
    last_closed = P.previous_start(P.start_of(today, kpi.cadence, week_start), kpi.cadence,
                                   week_start)
    count = back if feed.last_success_at is None else periods
    starts = P.last_n(last_closed, kpi.cadence, count, week_start)
    if read_open:
        starts.append(P.start_of(today, kpi.cadence, week_start))
    now = now or datetime.now(dt_timezone.utc)
    cache = {}
    values = {}
    for start in starts:
        value = value_for(measure, client, start, min(P.end_of(start, kpi.cadence), today),
                          zone=zone, member=feed.member_id or None,
                          member_name=feed.member_name or None, owner=feed.owner_id or None,
                          param=feed.param or None, now=now, cache=cache)
        if value is None:
            continue
        if MEASURES[measure][2] == "duration":
            value = in_unit(value, kpi)
        values[(start, None)] = value
    return values


def options(client) -> dict:
    """What the picker offers: the team (Besty's users), the property
    owners, and the upsell types and responder choices."""
    got = client.call("list_users", {})            # a list_* answer: {"users": [...]}
    members = [{"id": str(u.get("id")), "name": u.get("name") or u.get("email")
                or str(u.get("id")), "state": u.get("state") or ""}
               for u in got.get("users") or [] if u.get("id")]
    owners = [{"id": str(r.get("owner_id")), "name": r.get("name") or f"Owner {r.get('owner_id')}"}
              for r in client.rows("export_owners", {"fields": ["owner_id", "name", "thread_id"]})
              if r.get("thread_id")]
    return {"members": sorted(members, key=lambda m: m["name"].lower()),
            "owners": sorted(owners, key=lambda o: o["name"].lower()),
            "upsell_types": [{"id": k, "name": v} for k, v in UPSELL_TYPES.items()],
            "responders": [{"id": k, "name": v} for k, v in RESPONDERS.items()]}


def menu() -> list[dict]:
    return [{"key": k, "label": label, "tool": tool, "kind": kind, "scope": scope}
            for k, (label, tool, kind, scope) in MEASURES.items()]


def check_fits(kpi, measure):
    if measure not in MEASURES:
        raise BestyRefused("Choose a measure from the list.")
    if kpi.per_person:
        raise BestyRefused(f"{kpi.name} has a reading per person; a Besty measure is one "
                           "number, for the company or one team member or owner.")
    kind = MEASURES[measure][2]
    if kpi.kind not in FITS[kind]:
        need = {"percent": "Percent", "money": "Money", "count": "Count or Number",
                "rating": "Rating or Number", "duration": "Duration or Number"}[kind]
        raise BestyRefused(f"{MEASURES[measure][0]} fits a KPI of kind {need}; "
                           f"{kpi.name} is {kpi.get_kind_display()}.")


def scope_of(measure, *, member="", owner="", param=""):
    """The measure's scope fields, cleared where the measure has none."""
    scope = MEASURES[measure][3]
    member = member if scope in ("member", "owner", "responder") else ""
    owner = owner if scope == "owner" else ""
    if scope == "upsell":
        if param and param not in UPSELL_TYPES:
            raise BestyRefused("Choose an upsell type from the list.")
    elif scope == "responder":
        if param not in RESPONDERS:
            raise BestyRefused("Choose who the response time is for.")
        if member:
            param = ""
    else:
        param = ""
    return member, owner, param
