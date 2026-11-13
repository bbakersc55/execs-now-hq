"""The connector rails (P13, docs/p13_connector_rails.md): three ways any
system can feed a KPI without a connector built for it.

1. **Webhook.** A KPI's own secret address (stored hashed, shown once,
   rotated) takes a POST of JSON, form fields or query parameters: a value,
   and optionally a date and a note. For another system's own payload the
   feed holds a path to the value and to the date. A post replaces the
   period's reading or adds to it. One address per company also takes a KPI
   key with the value. Rate limited; the last 20 deliveries are kept with
   what was done. Readings are marked "From a webhook".
2. **Any MCP server.** A company's connections to other vendors' MCP servers
   (Streamable HTTP, a token or headers). A KPI's feed names a tool, its
   arguments with period placeholders, and the path to the number in the
   answer: proposed by Claude from a description, or set by hand, previewed
   live and confirmed. The nightly read is deterministic and uses no AI.
3. **Any API.** A company's API connections (a base address and a header,
   basic or query-key secret). A KPI's feed is a GET or POST with period
   placeholders in the path, query or body, and a path to the value.

Every outbound request goes through `safe_http.fetch` (https only, public
addresses only, checked again on connect, no redirect off the host, capped
time and size). Secrets are encrypted like the other connections' and never
shown again. A typed-by-hand reading is never replaced, by any rail.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets as pysecrets
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.utils import timezone

from . import periods as P
from . import safe_http

KEEP_DELIVERIES = 20
PLACEHOLDERS = ("period_start", "period_end", "period_start_iso", "period_end_iso", "year",
                "month", "quarter")
DEMO_REFUSAL = ("This is the demo. It never connects to another system; the connection shown "
                "is the demo's own example.")


class RailRefused(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# ------------------------------------------------------------------ secrets

def new_token(prefix: str) -> tuple[str, str, str]:
    """(token shown once, its hash kept, a hint of its last four)."""
    token = f"{prefix}{pysecrets.token_urlsafe(24)}"
    return token, hash_of(token), token[-4:]


def hash_of(token: str) -> str:
    return hashlib.sha256(str(token or "").encode()).hexdigest()


def kpi_key(kpi) -> str:
    """A KPI's key for the company's address: its name, lower case, words
    joined by _ ("On-time completion rate" is on_time_completion_rate)."""
    return re.sub(r"[^a-z0-9]+", "_", kpi.name.lower()).strip("_")[:60]


# ------------------------------------------------------------------ the webhook

def payload_of(request) -> tuple[dict, str]:
    """What was posted, as one dict (query parameters, then form fields or a
    JSON object on top), and its text for the delivery list."""
    out = {k: v for k, v in request.GET.items()}
    raw = request.body[:20000] if request.body else b""
    text = raw.decode("utf-8", "replace")
    kind = (request.META.get("CONTENT_TYPE") or "").split(";")[0].strip().lower()
    if kind == "application/json" or (text.strip().startswith(("{", "[")) and kind in
                                      ("", "text/plain")):
        try:
            data = json.loads(text or "{}")
        except ValueError:
            raise RailRefused("The body isn't valid JSON.") from None
        if isinstance(data, dict):
            out.update(data)
        else:
            out["_json"] = data
    else:
        out.update({k: v for k, v in request.POST.items()})
        # Form fields and query parameters, as names and values, not the raw body.
        text = "&".join(f"{k}={v}" for k, v in out.items())
    return out, text[:2000]


def _day_of(raw, tenant) -> date:
    from zoneinfo import ZoneInfo

    from . import board

    if raw in (None, ""):
        return board.today_for(tenant)
    text = str(raw).strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if moment.tzinfo is not None:
            moment = moment.astimezone(ZoneInfo(tenant.timezone or "UTC"))
        return moment.date()
    except ValueError:
        raise RailRefused("The date isn't one that can be read: use YYYY-MM-DD.") from None


def _number(kpi, raw) -> Decimal:
    from . import readings

    if isinstance(raw, bool) or raw is None or raw == "":
        raise RailRefused("No value was sent.")
    try:
        return readings.parse(kpi, str(raw))
    except Exception as exc:  # noqa: BLE001  (parse refuses in words)
        raise RailRefused(str(exc) or "The value isn't a number.") from None


def write_reading(kpi, day: date, value: Decimal, *, source, add=False) -> dict:
    """One reading of the company's KPI for the period containing `day`.
    Never over a reading typed by hand; never for a period not yet started."""
    from .board import scorecard_for, today_for
    from .models import KpiReading, KpiReadingChange

    scorecard = scorecard_for(kpi.scorecard.company)
    start = P.start_of(day, kpi.cadence, scorecard.week_start)
    today = today_for(kpi.tenant)
    if start > P.start_of(today, kpi.cadence, scorecard.week_start):
        raise RailRefused("That date is in a period that hasn't started.")
    reading = KpiReading.all_objects.filter(kpi=kpi, period_start=start,
                                            membership__isnull=True).first()
    if reading is not None and reading.source == KpiReading.Source.HAND:
        return {"what": "kept", "period": P.long_label(start, kpi.cadence),
                "said": "A reading typed by hand is there; it is never replaced."}
    now = timezone.now()
    new_value = value + (reading.value if add and reading is not None
                         and reading.source == source else 0)
    if reading is None:
        reading = KpiReading.all_objects.create(
            tenant_id=kpi.tenant_id, kpi=kpi, period_start=start, value=new_value,
            source=source, entered_at=now)
        what = "new"
    else:
        reading.value, reading.source, reading.entered_at = new_value, source, now
        reading.times_changed += 1
        reading.provisional = False
        reading.save(update_fields=["value", "source", "entered_at", "times_changed",
                                    "provisional", "updated_at"])
        what = "added" if add else "replaced"
    KpiReadingChange.all_objects.create(tenant_id=kpi.tenant_id, reading=reading,
                                        value=new_value, changed_by=None)
    return {"what": what, "period": P.long_label(start, kpi.cadence),
            "value": f"{new_value.normalize():f}" if isinstance(new_value, Decimal) else
            str(new_value)}


def receive(feed, payload: dict) -> dict:
    """A KPI's own address: the value (or the value at the feed's path), the
    date (or the date at its path; today when none), replace or add."""
    from .models import KpiReading, KpiWebhookFeed

    kpi = feed.kpi
    data = payload.get("_json", payload)
    raw = safe_http.json_path(data, feed.value_path) if feed.value_path \
        else payload.get("value")
    raw_day = safe_http.json_path(data, feed.date_path) if feed.date_path \
        else payload.get("date")
    value = _number(kpi, raw)
    day = _day_of(raw_day, kpi.tenant)
    return write_reading(kpi, day, value, source=KpiReading.Source.WEBHOOK,
                         add=feed.mode == KpiWebhookFeed.Mode.ADD)


def receive_for_company(company, payload: dict) -> tuple[object, dict]:
    """The company's address: a KPI key ("kpi") with the value. Only a KPI
    whose feed is a webhook takes it."""
    from .models import KpiWebhookFeed

    key = str(payload.get("kpi") or payload.get("key") or "").strip().lower()
    if not key:
        raise RailRefused("Say which KPI with \"kpi\": its key from the Test panel.")
    feeds = KpiWebhookFeed.all_objects.filter(
        kpi__scorecard__company=company, active=True,
        kpi__archived_at__isnull=True).select_related("kpi", "kpi__scorecard__company",
                                                      "kpi__tenant")
    found = next((f for f in feeds if kpi_key(f.kpi) == key or str(f.kpi_id) == key), None)
    if found is None:
        raise RailRefused(f"No KPI with the key \"{key}\" takes a webhook here.", 404)
    return found, receive(found, payload)


def record(*, company, feed, ok: bool, what: str, payload_text: str, via_company=False):
    from .models import WebhookDelivery

    WebhookDelivery.all_objects.create(
        tenant_id=company.tenant_id, company=company, feed=feed, ok=ok, what=what[:500],
        payload=payload_text[:2000], via_company=via_company)
    keep = WebhookDelivery.all_objects.filter(company=company)
    keep = keep.filter(feed=feed) if feed is not None and not via_company \
        else keep.filter(via_company=True)
    old = list(keep.order_by("-created_at").values_list("pk", flat=True)[KEEP_DELIVERIES:])
    if old:
        WebhookDelivery.all_objects.filter(pk__in=old).delete()


# ------------------------------------------------------------------ placeholders, paths

def placeholders(start: date, end: date) -> dict:
    return {"period_start": start.isoformat(), "period_end": end.isoformat(),
            "period_start_iso": f"{start.isoformat()}T00:00:00Z",
            "period_end_iso": f"{end.isoformat()}T23:59:59Z",
            "year": f"{start.year}", "month": f"{start.month:02d}",
            "quarter": f"{(start.month - 1) // 3 + 1}"}


def fill(value, names: dict):
    """Every {placeholder} in a string, a list or a dict's values, filled."""
    if isinstance(value, str):
        for key, text in names.items():
            value = value.replace("{" + key + "}", text)
        return value
    if isinstance(value, list):
        return [fill(v, names) for v in value]
    if isinstance(value, dict):
        return {k: fill(v, names) for k, v in value.items()}
    return value


def number_at(kpi, data, path) -> Decimal:
    found = safe_http.json_path(data, path)
    if found is None:
        raise RailRefused(f"Nothing is at \"{path}\" in the answer.")
    if isinstance(found, (dict, list)):
        raise RailRefused(f"\"{path}\" is a group of values, not one number.")
    return _number(kpi, found)


def excerpt(data, limit=1500) -> str:
    text = data if isinstance(data, str) else json.dumps(data, indent=1, default=str)
    return text[:limit] + ("…" if len(text) > limit else "")


def last_closed(kpi, today) -> tuple[date, date]:
    week_start = kpi.scorecard.week_start
    start = P.previous_start(P.start_of(today, kpi.cadence, week_start), kpi.cadence,
                             week_start)
    return start, P.end_of(start, kpi.cadence)


def window(feed, today, *, read_open: bool) -> list[date]:
    """The closed periods a read covers (13 the first time, 2 after), and the
    open one so far when chosen: the other feeds' window."""
    kpi = feed.kpi
    week_start = kpi.scorecard.week_start
    closed = P.previous_start(P.start_of(today, kpi.cadence, week_start), kpi.cadence,
                              week_start)
    starts = P.last_n(closed, kpi.cadence, 13 if feed.last_success_at is None else 2,
                      week_start)
    if read_open:
        starts.append(P.start_of(today, kpi.cadence, week_start))
    return starts


# ------------------------------------------------------------------ MCP

class McpClient:
    """One connection to another vendor's MCP server, over Streamable HTTP,
    through the safe fetcher. Its headers carry the connection's secret and
    are never echoed."""

    PROTOCOL = "2025-03-26"

    def __init__(self, url: str, headers: dict, *, fetch=None):
        self.url = url
        self.headers = dict(headers)
        self.fetch = fetch or safe_http.fetch
        self.session = None
        self._id = 0

    def _post(self, body):
        headers = {**self.headers, "Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream"}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        status, answer_headers, data = self.fetch("POST", self.url, headers=headers,
                                                  body=json.dumps(body).encode())
        if status in (401, 403):
            raise RailRefused("The server refused the token or headers. Check them on the "
                              "connection.", 502)
        if status >= 400:
            raise RailRefused(f"The server answered {status}.", 502)
        return answer_headers, data.decode("utf-8", "replace")

    def _rpc(self, method, params=None):
        from .besty import _message

        self._id += 1
        body = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            body["params"] = params
        _, text = self._post(body)
        message = _message(text)
        if not isinstance(message, dict):
            raise RailRefused("The server's answer couldn't be read as MCP.", 502)
        if message.get("error"):
            raise RailRefused(f"The server refused it: "
                              f"{str(message['error'].get('message') or '')[:200]}", 502)
        return message.get("result") or {}

    def open(self):
        from .besty import _header, _message

        if self.session is not None:
            return
        self._id += 1
        headers, text = self._post({"jsonrpc": "2.0", "id": self._id, "method": "initialize",
                                    "params": {"protocolVersion": self.PROTOCOL,
                                               "capabilities": {},
                                               "clientInfo": {"name": "execs-now-hq",
                                                              "version": "1"}}})
        message = _message(text)
        if not isinstance(message, dict) or "result" not in message:
            raise RailRefused("The server didn't answer as an MCP server.", 502)
        self.session = _header(headers, "Mcp-Session-Id") or ""
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def tools(self) -> list[dict]:
        self.open()
        return [{"name": t.get("name", ""), "description": (t.get("description") or "")[:500],
                 "input_schema": t.get("inputSchema") or {}}
                for t in self._rpc("tools/list").get("tools") or []]

    def call(self, tool: str, arguments: dict):
        self.open()
        result = self._rpc("tools/call", {"name": tool, "arguments": arguments or {}})
        text = "".join(c.get("text") or "" for c in result.get("content") or []
                       if c.get("type") == "text")
        if result.get("isError"):
            raise RailRefused(f"The tool refused it: {text[:200]}", 502)
        if isinstance(result.get("structuredContent"), (dict, list)):
            return result["structuredContent"]
        try:
            return json.loads(text)
        except ValueError:
            return {"text": text}


def mcp_headers(connection) -> dict:
    from apps.crm.services.secrets import decrypt

    stored = decrypt(connection.secret_ciphertext) if connection.secret_ciphertext else ""
    try:
        data = json.loads(stored or "{}")
    except ValueError:
        data = {}
    headers = dict(data.get("headers") or {})
    if data.get("token"):
        headers["Authorization"] = f"Bearer {data['token']}"
    return headers


def mcp_client(connection, *, fetch=None) -> McpClient:
    from config import environment

    if environment.is_demo():
        raise RailRefused(DEMO_REFUSAL, 409)
    return McpClient(connection.url, mcp_headers(connection), fetch=fetch)


def mcp_value(feed, client, start: date, end: date) -> Decimal:
    arguments = fill(feed.arguments or {}, placeholders(start, end))
    return number_at(feed.kpi, client.call(feed.tool, arguments), feed.value_path)


# ------------------------------------------------------------------ any API

def api_request(connection, *, method, path, query=None, body=None, fetch=None):
    """One request to the connection, its secret where its kind puts it.
    Returns the JSON answer."""
    import base64
    from urllib.parse import urljoin

    from config import environment

    from apps.crm.services.secrets import decrypt

    if environment.is_demo():
        raise RailRefused(DEMO_REFUSAL, 409)
    secret = decrypt(connection.secret_ciphertext) if connection.secret_ciphertext else ""
    headers = {"Accept": "application/json"}
    query = dict(query or {})
    if connection.auth_kind == "header" and secret:
        headers[connection.auth_name or "Authorization"] = secret
    elif connection.auth_kind == "basic" and secret:
        headers["Authorization"] = "Basic " + base64.b64encode(secret.encode()).decode()
    elif connection.auth_kind == "query" and secret:
        query[connection.auth_name or "api_key"] = secret
    base = connection.base_url.rstrip("/") + "/"
    url = urljoin(base, str(path or "").lstrip("/"))
    if not url.startswith(base):          # the slash: "/v1evil" is not under "/v1"
        raise RailRefused("The path has to stay under the connection's address.")
    data = None
    if method == "POST":
        headers["Content-Type"] = "application/json"
        data = (json.dumps(body) if not isinstance(body, str) else body).encode()
    status, _, raw = (fetch or safe_http.fetch)(method, url, headers=headers, query=query,
                                                body=data)
    if status in (401, 403):
        raise RailRefused("The API refused the secret. Check it on the connection.", 502)
    if status >= 400:
        raise RailRefused(f"The API answered {status}.", 502)
    try:
        return json.loads(raw.decode("utf-8", "replace") or "null")
    except ValueError:
        raise RailRefused("The API's answer isn't JSON.", 502) from None


def api_value(feed, start: date, end: date, *, fetch=None) -> Decimal:
    names = placeholders(start, end)
    answer = api_request(feed.connection, method=feed.method, path=fill(feed.path, names),
                         query=fill(feed.query or {}, names),
                         body=fill(feed.body, names) if feed.method == "POST" else None,
                         fetch=fetch)
    return number_at(feed.kpi, answer, feed.value_path)


# ------------------------------------------------------------------ the nightly read

def run_feed(feed, today, value_of, *, source, now=None) -> dict:
    """The window's readings from `value_of(start, end)`, written by the
    feeds' own rules; a failure is said on the feed and nothing is deleted."""
    from . import feeds as F
    from . import sheets

    now = now or timezone.now()
    kpi = feed.kpi
    read_open = F.reads_open(feed)
    try:
        values = {}
        for start in window(feed, today, read_open=read_open):
            end = min(P.end_of(start, kpi.cadence), today)
            values[(start, None)] = value_of(start, end)
        results = sheets.outcome(kpi, values, today, kpi.scorecard.week_start, source=source,
                                 read_open=read_open)
        counts = sheets.write(feed, results, now, source=source)
    except (RailRefused, safe_http.FetchRefused, safe_http.FetchFailed,
            sheets.FeedRefused) as exc:
        message = str(exc)
        if feed.last_error != message:
            feed.error_since = now
        type(feed).all_objects.filter(pk=feed.pk).update(
            last_run_at=now, last_error=message, error_since=feed.error_since or now,
            updated_at=now)
        return {"ok": False, "error": message}
    type(feed).all_objects.filter(pk=feed.pk).update(
        last_run_at=now, last_success_at=now, last_error="", error_since=None,
        last_counts=counts, updated_at=now)
    return {"ok": True, **counts}


DAILY_AFTER = timedelta(hours=23)


def run_due(tenant_id, today, *, now=None) -> dict:
    """The MCP and API feeds that haven't run in a day: no AI, ever."""
    from .models import KpiApiFeed, KpiMcpFeed, KpiReading

    now = now or timezone.now()
    ran = failed = 0
    for model, kind in ((KpiMcpFeed, "mcp"), (KpiApiFeed, "api")):
        for feed in model.all_objects.filter(
                tenant_id=tenant_id, active=True, kpi__archived_at__isnull=True,
                kpi__scorecard__company__deleted_at__isnull=True).select_related(
                "kpi", "kpi__tenant", "kpi__scorecard", "kpi__scorecard__company",
                "connection"):
            if feed.last_run_at is not None and now - feed.last_run_at < DAILY_AFTER:
                continue
            try:
                if kind == "mcp":
                    client = mcp_client(feed.connection)
                    result = run_feed(feed, today, lambda s, e: mcp_value(feed, client, s, e),
                                      source=KpiReading.Source.MCP, now=now)
                else:
                    result = run_feed(feed, today, lambda s, e: api_value(feed, s, e),
                                      source=KpiReading.Source.API, now=now)
            except RailRefused as exc:            # the demo, before any request
                result = {"ok": False, "error": str(exc)}
            ran += 1
            failed += int(not result["ok"])
    return {"ran": ran, "failed": failed}
