"""The connector rails' routes (P13). Setting a feed is the practice owner's
and associates', as the rest of the scorecard's setup is; making a
connection (an MCP server, an API) is the practice owner's, as Besty's is.
Every company route finds the company through `access.company_for`, so
another practice's company is 404.

POST   /webhooks/kpi/<token>/                     a KPI's own address (public; the token is the key)
POST   /webhooks/company/<token>/                 the company's address: {kpi, value, date?, note?}

GET    /api/scorecard/rails/webhook/?company=&kpi=      the feed, its deliveries, the Test panel
PUT    /api/scorecard/rails/webhook/                    {company, kpi, mode, value_path, date_path}
POST   /api/scorecard/rails/webhook/rotate/             {company, kpi}: a new address, shown once
DELETE /api/scorecard/rails/webhook/?company=&kpi=
GET    /api/scorecard/rails/company-webhook/?company=   the company's address and its deliveries
POST   /api/scorecard/rails/company-webhook/            {company}: make or rotate, shown once
GET    /api/scorecard/rails/mcp/?company=               the company's MCP connections
POST   /api/scorecard/rails/mcp/                        {company, name, url, token?, headers?}
DELETE /api/scorecard/rails/mcp/<id>/
POST   /api/scorecard/rails/mcp/<id>/test/              lists the server's tools
GET    /api/scorecard/rails/mcp-feed/?company=&kpi=     the feed, and the proposal's price
POST   /api/scorecard/rails/mcp-feed/propose/           {company, kpi, connection, description}
POST   /api/scorecard/rails/mcp-feed/preview/           {company, kpi, connection, tool, arguments, value_path}
PUT    /api/scorecard/rails/mcp-feed/                   the same, confirmed
DELETE /api/scorecard/rails/mcp-feed/?company=&kpi=
GET    /api/scorecard/rails/api/?company=               the company's API connections
POST   /api/scorecard/rails/api/                        {company, name, base_url, auth_kind, auth_name, secret}
DELETE /api/scorecard/rails/api/<id>/
GET    /api/scorecard/rails/api-feed/?company=&kpi=
POST   /api/scorecard/rails/api-feed/preview/           {company, kpi, connection, method, path, query, body, value_path}
PUT    /api/scorecard/rails/api-feed/
DELETE /api/scorecard/rails/api-feed/?company=&kpi=
POST   /api/scorecard/rails/request/                    {system, numbers, client}: a connector request
"""

from __future__ import annotations

import json

from django.conf import settings
from django.http import Http404, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from rest_framework.response import Response

from apps.accounts.ratelimit import RateLimit, too_many_shared
from apps.tenancy.context import tenant_context
from apps.tenancy.models import AuditEvent, Role

from . import feeds, rails, rails_ai, safe_http
from .models import (ApiConnection, CompanyWebhook, Kpi, KpiApiFeed, KpiMcpFeed, KpiReading,
                     KpiWebhookFeed, McpConnection, WebhookDelivery)
from .views import Base, _reader, _refuse_setup, _today, _uuid_or_404

WEBHOOK_RATE = RateLimit(limit=60, window_seconds=60, prefix="kpi_webhook")
OWNER_ONLY = "Only the practice owner connects another system."


def _owner_only(request):
    if request.membership.role != Role.FF:
        return Response({"detail": OWNER_ONLY}, status=403)
    return None


def _audit(company, actor, verb, **payload):
    AuditEvent.all_objects.create(tenant_id=company.tenant_id, actor=actor, verb=verb,
                                  target_type="company", target_id=company.pk, payload=payload)


def _kpi(reader, raw):
    _uuid_or_404(raw)
    kpi = Kpi.objects.filter(pk=raw, scorecard__company=reader.company,
                             archived_at__isnull=True).select_related(
        "scorecard", "scorecard__company", "tenant").first()
    if kpi is None:
        raise Http404
    return kpi


def _one_number(kpi):
    if kpi.per_person:
        raise rails.RailRefused(f"{kpi.name} has a reading per person; a rail feeds one "
                                "number for the company.")
    if kpi.is_computed:
        raise rails.RailRefused(f"{kpi.name} is worked out from two other KPIs; it takes no "
                                "feed.")


def _base_url(request) -> str:
    return getattr(settings, "PUBLIC_BASE_URL", "").rstrip("/") or \
        request.build_absolute_uri("/").rstrip("/")


def _deliveries(qs) -> list[dict]:
    return [{"at": d.created_at.isoformat(), "ok": d.ok, "what": d.what, "received": d.payload,
             "kpi": d.feed.kpi.name if d.feed_id else ""}
            for d in qs.select_related("feed__kpi").order_by("-created_at")[:20]]


def _feed_state(feed) -> dict:
    return {"active": feed.active, "last_run_at": feed.last_run_at.isoformat()
            if feed.last_run_at else None,
            "last_success_at": feed.last_success_at.isoformat() if feed.last_success_at else None,
            "last_error": feed.last_error,
            "error_since": feed.error_since.isoformat() if feed.error_since else None,
            "read_open": feeds.reads_open(feed)}


def _refused(exc):
    return Response({"detail": str(exc)}, status=getattr(exc, "status", 400))


# ------------------------------------------------------------------ the public addresses

def _hook_answer(status, ok, what):
    return JsonResponse({"ok": ok, "what": what}, status=status)


@csrf_exempt
@require_POST
def kpi_webhook(request, token):
    if too_many_shared(WEBHOOK_RATE, rails.hash_of(token)):
        return _hook_answer(429, False, "Too many posts this minute; wait and post again.")
    feed = KpiWebhookFeed.all_objects.filter(
        secret_hash=rails.hash_of(token), active=True, kpi__archived_at__isnull=True).select_related(
        "kpi", "kpi__tenant", "kpi__scorecard", "kpi__scorecard__company").first()
    if feed is None:
        return _hook_answer(404, False, "No KPI takes posts at this address.")
    with tenant_context(feed.tenant_id):            # no session: the token says whose
        return _kpi_delivery(request, feed)


def _kpi_delivery(request, feed):
    company = feed.kpi.scorecard.company
    try:
        payload, text = rails.payload_of(request)
        result = rails.receive(feed, payload)
    except rails.RailRefused as exc:
        rails.record(company=company, feed=feed, ok=False, what=str(exc),
                     payload_text=request.body[:2000].decode("utf-8", "replace"))
        return _hook_answer(400, False, str(exc))
    what = _said(result)
    rails.record(company=company, feed=feed, ok=result["what"] != "kept", what=what,
                 payload_text=text)
    KpiWebhookFeed.all_objects.filter(pk=feed.pk).update(last_received_at=timezone.now())
    return _hook_answer(200, result["what"] != "kept", what)


@csrf_exempt
@require_POST
def company_webhook(request, token):
    if too_many_shared(WEBHOOK_RATE, rails.hash_of(token)):
        return _hook_answer(429, False, "Too many posts this minute; wait and post again.")
    hook = CompanyWebhook.all_objects.filter(secret_hash=rails.hash_of(token)) \
        .select_related("company").first()
    if hook is None or hook.company.deleted_at is not None:
        return _hook_answer(404, False, "No company takes posts at this address.")
    with tenant_context(hook.tenant_id):            # no session: the token says whose
        return _company_delivery(request, hook)


def _company_delivery(request, hook):
    try:
        payload, text = rails.payload_of(request)
        feed, result = rails.receive_for_company(hook.company, payload)
    except rails.RailRefused as exc:
        rails.record(company=hook.company, feed=None, ok=False, what=str(exc),
                     payload_text=request.body[:2000].decode("utf-8", "replace"),
                     via_company=True)
        return _hook_answer(exc.status if exc.status in (400, 404) else 400, False, str(exc))
    what = f"{feed.kpi.name}: {_said(result)}"
    rails.record(company=hook.company, feed=feed, ok=result["what"] != "kept", what=what,
                 payload_text=text, via_company=True)
    return _hook_answer(200, result["what"] != "kept", what)


def _said(result) -> str:
    if result["what"] == "kept":
        return f"{result['period']}: kept. {result['said']}"
    verb = {"new": "saved", "replaced": "replaced", "added": "added to"}[result["what"]]
    return f"{result['period']}: {verb}, now {result['value']}."


# ------------------------------------------------------------------ the webhook feed

def _test_panel(request, kpi, token=None) -> dict:
    address = f"{_base_url(request)}/webhooks/kpi/{token or '<your address>'}/"
    return {"address": address if token else None,
            "example": f"curl -X POST {address} -H 'Content-Type: application/json' "
                       f"-d '{{\"value\": 12, \"date\": \"{timezone.localdate():%Y-%m-%d}\"}}'",
            "zapier": ["Add a step: Webhooks by Zapier, then POST.",
                       "URL: the address above. Payload type: json.",
                       "Data: value, the number from the earlier step; date, optional.",
                       "Test the step: the delivery shows here with what was done."],
            "make": ["Add an HTTP module: Make a request.",
                     "URL: the address above. Method: POST. Body type: Raw, JSON.",
                     "Request content: {\"value\": <the number>}.",
                     "Run once: the delivery shows here with what was done."]}


class WebhookFeedView(Base):
    def get(self, request):
        reader = _reader(request, request.query_params.get("company"))
        if (refusal := _refuse_setup(reader)):
            return refusal
        kpi = _kpi(reader, request.query_params.get("kpi"))
        feed = KpiWebhookFeed.objects.filter(kpi=kpi).first()
        out = {"feed": None, "test": _test_panel(request, kpi), "key": rails.kpi_key(kpi)}
        if feed is not None:
            out["feed"] = {**_feed_state(feed), "mode": feed.mode, "value_path": feed.value_path,
                           "date_path": feed.date_path, "hint": feed.secret_hint,
                           "last_received_at": feed.last_received_at.isoformat()
                           if feed.last_received_at else None,
                           "deliveries": _deliveries(WebhookDelivery.objects.filter(
                               feed=feed, via_company=False))}
        return Response(out)

    def put(self, request):
        reader = _reader(request, request.data.get("company"))
        if (refusal := _refuse_setup(reader)):
            return refusal
        kpi = _kpi(reader, request.data.get("kpi"))
        try:
            _one_number(kpi)
        except rails.RailRefused as exc:
            return _refused(exc)
        mode = request.data.get("mode") or KpiWebhookFeed.Mode.REPLACE
        if mode not in KpiWebhookFeed.Mode.values:
            return Response({"detail": "A post replaces the period's reading or adds to it."},
                            status=400)
        feed = KpiWebhookFeed.objects.filter(kpi=kpi).first()
        token = None
        if feed is None:
            token, hashed, hint = rails.new_token("kh_")
            feed = KpiWebhookFeed(tenant_id=kpi.tenant_id, kpi=kpi, secret_hash=hashed,
                                  secret_hint=hint, created_by=request.user)
        feed.mode = mode
        feed.value_path = str(request.data.get("value_path") or "").strip()[:200]
        feed.date_path = str(request.data.get("date_path") or "").strip()[:200]
        feed.active = True
        feed.save()
        feeds.stop_other_feeds(kpi, keep="webhook")
        Kpi.all_objects.filter(pk=kpi.pk).update(feed=Kpi.Feed.WEBHOOK)
        _audit(reader.company, request.user, "scorecard.webhook_feed_set", kpi=kpi.name)
        out = {"saved": True, "hint": feed.secret_hint}
        if token:
            out.update({"token": token, "test": _test_panel(request, kpi, token)})
        return Response(out)

    def delete(self, request):
        reader = _reader(request, request.query_params.get("company"))
        if (refusal := _refuse_setup(reader)):
            return refusal
        kpi = _kpi(reader, request.query_params.get("kpi"))
        KpiWebhookFeed.objects.filter(kpi=kpi).update(active=False)
        Kpi.all_objects.filter(pk=kpi.pk, feed=Kpi.Feed.WEBHOOK).update(feed=Kpi.Feed.HAND)
        return Response({"stopped": True})


class WebhookRotateView(Base):
    def post(self, request):
        reader = _reader(request, request.data.get("company"))
        if (refusal := _refuse_setup(reader)):
            return refusal
        kpi = _kpi(reader, request.data.get("kpi"))
        feed = KpiWebhookFeed.objects.filter(kpi=kpi).first()
        if feed is None:
            raise Http404
        token, hashed, hint = rails.new_token("kh_")
        KpiWebhookFeed.objects.filter(pk=feed.pk).update(secret_hash=hashed, secret_hint=hint)
        _audit(reader.company, request.user, "scorecard.webhook_rotated", kpi=kpi.name)
        return Response({"token": token, "hint": hint, "test": _test_panel(request, kpi, token)})


class CompanyWebhookView(Base):
    def get(self, request):
        reader = _reader(request, request.query_params.get("company"))
        if (refusal := _refuse_setup(reader)):
            return refusal
        hook = CompanyWebhook.objects.filter(company=reader.company).first()
        keys = [{"kpi": f.kpi.name, "key": rails.kpi_key(f.kpi)}
                for f in KpiWebhookFeed.objects.filter(kpi__scorecard__company=reader.company,
                                                       active=True).select_related("kpi")]
        return Response({"exists": hook is not None, "hint": hook.secret_hint if hook else "",
                         "keys": keys,
                         "deliveries": _deliveries(WebhookDelivery.objects.filter(
                             company=reader.company, via_company=True)) if hook else []})

    def post(self, request):
        reader = _reader(request, request.data.get("company"))
        if (refusal := _refuse_setup(reader)):
            return refusal
        token, hashed, hint = rails.new_token("ch_")
        CompanyWebhook.objects.update_or_create(
            company=reader.company, defaults={"tenant_id": reader.company.tenant_id,
                                              "secret_hash": hashed, "secret_hint": hint,
                                              "created_by": request.user})
        _audit(reader.company, request.user, "scorecard.company_webhook_set")
        address = f"{_base_url(request)}/webhooks/company/{token}/"
        return Response({"token": token, "hint": hint, "address": address,
                         "example": f"curl -X POST {address} -H 'Content-Type: application/json' "
                                    "-d '{\"kpi\": \"<key>\", \"value\": 12}'"})


# ------------------------------------------------------------------ connections

def _connection_row(c) -> dict:
    out = {"id": str(c.pk), "name": c.name, "checked_at": c.checked_at.isoformat()
           if c.checked_at else None, "check_ok": c.check_ok, "check_detail": c.check_detail,
           "secret_hint": c.secret_hint}
    if isinstance(c, McpConnection):
        out.update({"url": c.url, "tools": [t["name"] for t in c.tools or []]})
    else:
        out.update({"base_url": c.base_url, "auth_kind": c.auth_kind, "auth_name": c.auth_name})
    return out


def _check_address(url):
    safe_http.check_url(url)
    host = safe_http.urlsplit(url).hostname
    safe_http.resolve(host, safe_http.urlsplit(url).port or 443)


class McpConnectionsView(Base):
    def get(self, request):
        from config import environment

        reader = _reader(request, request.query_params.get("company"))
        if (refusal := _refuse_setup(reader)):
            return refusal
        return Response({"connections": [_connection_row(c) for c in McpConnection.objects.filter(
            company=reader.company).order_by("name")], "demo": environment.is_demo()})

    def post(self, request):
        from apps.crm.services import secrets
        from config import environment

        reader = _reader(request, request.data.get("company"))
        if (refusal := _refuse_setup(reader)) or (refusal := _owner_only(request)):
            return refusal
        if environment.is_demo():
            return Response({"detail": rails.DEMO_REFUSAL}, status=409)
        name = " ".join(str(request.data.get("name") or "").split())[:120]
        url = str(request.data.get("url") or "").strip()
        if not name:
            return Response({"detail": "Name the connection."}, status=400)
        try:
            _check_address(url)
        except (safe_http.FetchRefused, safe_http.FetchFailed) as exc:
            return Response({"detail": str(exc)}, status=400)
        token = str(request.data.get("token") or "").strip()
        headers = request.data.get("headers") or {}
        if not isinstance(headers, dict) or any(not isinstance(v, str) for v in headers.values()):
            return Response({"detail": "Headers are names and values."}, status=400)
        secret = json.dumps({"token": token, "headers": headers})
        hint = (token or "".join(headers.values()))[-4:]
        connection = McpConnection.objects.create(
            tenant_id=reader.company.tenant_id, company=reader.company, name=name, url=url,
            secret_ciphertext=secrets.encrypt(secret), secret_hint=hint,
            created_by=request.user)
        _audit(reader.company, request.user, "scorecard.mcp_connected", name=name)
        return Response(_connection_row(connection), status=201)


class McpConnectionView(Base):
    def _get(self, request, pk):
        _uuid_or_404(pk)
        connection = McpConnection.objects.filter(pk=pk).select_related("company").first()
        if connection is None:
            raise Http404
        reader = _reader(request, connection.company_id)
        if (refusal := _refuse_setup(reader)):
            return None, refusal
        return connection, None

    def delete(self, request, pk):
        connection, refusal = self._get(request, pk)
        if refusal:
            return refusal
        if (refusal := _owner_only(request)):
            return refusal
        KpiMcpFeed.objects.filter(connection=connection).update(active=False)
        connection.delete()
        return Response(status=204)

    def post(self, request, pk):                                   # test
        connection, refusal = self._get(request, pk)
        if refusal:
            return refusal
        now = timezone.now()
        try:
            tools = rails.mcp_client(connection).tools()
            detail, ok = f"Connected: {len(tools)} tools.", True
        except (rails.RailRefused, safe_http.FetchRefused, safe_http.FetchFailed) as exc:
            tools, detail, ok = connection.tools or [], str(exc), False
        McpConnection.objects.filter(pk=connection.pk).update(
            checked_at=now, check_ok=ok, check_detail=detail[:500], tools=tools, updated_at=now)
        connection.refresh_from_db()
        return Response({**_connection_row(connection),
                         **({} if ok else {"detail": detail}),
                         "tool_list": [{"name": t["name"], "description": t["description"]}
                                       for t in tools]}, status=200 if ok else 502)


class ApiConnectionsView(Base):
    def get(self, request):
        from config import environment

        reader = _reader(request, request.query_params.get("company"))
        if (refusal := _refuse_setup(reader)):
            return refusal
        return Response({"connections": [_connection_row(c) for c in ApiConnection.objects.filter(
            company=reader.company).order_by("name")], "demo": environment.is_demo()})

    def post(self, request):
        from apps.crm.services import secrets
        from config import environment

        reader = _reader(request, request.data.get("company"))
        if (refusal := _refuse_setup(reader)) or (refusal := _owner_only(request)):
            return refusal
        if environment.is_demo():
            return Response({"detail": rails.DEMO_REFUSAL}, status=409)
        name = " ".join(str(request.data.get("name") or "").split())[:120]
        base = str(request.data.get("base_url") or "").strip().rstrip("/")
        kind = request.data.get("auth_kind") or "header"
        if not name:
            return Response({"detail": "Name the connection."}, status=400)
        if kind not in ApiConnection.AuthKind.values:
            return Response({"detail": "The secret goes in a header, as basic sign-in, or as "
                                       "a query key."}, status=400)
        try:
            _check_address(base)
        except (safe_http.FetchRefused, safe_http.FetchFailed) as exc:
            return Response({"detail": str(exc)}, status=400)
        secret = str(request.data.get("secret") or "")
        connection = ApiConnection.objects.create(
            tenant_id=reader.company.tenant_id, company=reader.company, name=name,
            base_url=base, auth_kind=kind,
            auth_name=str(request.data.get("auth_name") or "")[:80],
            secret_ciphertext=secrets.encrypt(secret) if secret else None,
            secret_hint=secret[-4:] if secret else "", created_by=request.user)
        _audit(reader.company, request.user, "scorecard.api_connected", name=name)
        return Response(_connection_row(connection), status=201)


class ApiConnectionView(McpConnectionView):
    def _get(self, request, pk):
        _uuid_or_404(pk)
        connection = ApiConnection.objects.filter(pk=pk).select_related("company").first()
        if connection is None:
            raise Http404
        reader = _reader(request, connection.company_id)
        if (refusal := _refuse_setup(reader)):
            return None, refusal
        return connection, None

    def delete(self, request, pk):
        connection, refusal = self._get(request, pk)
        if refusal:
            return refusal
        if (refusal := _owner_only(request)):
            return refusal
        KpiApiFeed.objects.filter(connection=connection).update(active=False)
        connection.delete()
        return Response(status=204)

    def post(self, request, pk):
        raise Http404


# ------------------------------------------------------------------ the MCP and API feeds

def _feed_payload(feed, kind) -> dict | None:
    if feed is None:
        return None
    out = {**_feed_state(feed), "connection": str(feed.connection_id),
           "value_path": feed.value_path}
    if kind == "mcp":
        out.update({"tool": feed.tool, "arguments": feed.arguments, "from_ai": feed.from_ai})
    else:
        out.update({"method": feed.method, "path": feed.path, "query": feed.query,
                    "body": feed.body})
    return out


class _RailFeed(Base):
    kind = ""
    model = None
    connection_model = None

    def _setup(self, request, data):
        reader = _reader(request, data.get("company"))
        if (refusal := _refuse_setup(reader)):
            return None, None, None, refusal
        kpi = _kpi(reader, data.get("kpi"))
        _uuid_or_404(data.get("connection"))
        connection = self.connection_model.objects.filter(
            pk=data.get("connection"), company=reader.company).first()
        if connection is None:
            raise Http404
        return reader, kpi, connection, None

    def _settings(self, data) -> dict:
        raise NotImplementedError

    def _value(self, kpi, connection, settings_, start, end):
        raise NotImplementedError

    def get(self, request):
        reader = _reader(request, request.query_params.get("company"))
        if (refusal := _refuse_setup(reader)):
            return refusal
        kpi = _kpi(reader, request.query_params.get("kpi"))
        out = {"feed": _feed_payload(self.model.objects.filter(kpi=kpi).first(), self.kind),
               "placeholders": ["{" + p + "}" for p in rails.PLACEHOLDERS]}
        if self.kind == "mcp":
            out["ai"] = rails_ai.status(reader.company.tenant)
        return Response(out)

    def _preview(self, request):
        reader, kpi, connection, refusal = self._setup(request, request.data)
        if refusal:
            return None, refusal
        _one_number(kpi)
        settings_ = self._settings(request.data)
        start, end = rails.last_closed(kpi, _today(request))
        try:
            value, raw = self._value(kpi, connection, settings_, start, end)
        except (safe_http.FetchRefused, safe_http.FetchFailed) as exc:
            raise rails.RailRefused(str(exc), 502) from None
        return {"period": rails.P.long_label(start, kpi.cadence),
                "value": None if value is None else f"{value.normalize():f}",
                "answer": rails.excerpt(raw), "settings": settings_}, None

    def delete(self, request):
        reader = _reader(request, request.query_params.get("company"))
        if (refusal := _refuse_setup(reader)):
            return refusal
        kpi = _kpi(reader, request.query_params.get("kpi"))
        self.model.objects.filter(kpi=kpi).update(active=False)
        Kpi.all_objects.filter(pk=kpi.pk, feed=self.kind).update(feed=Kpi.Feed.HAND)
        return Response({"stopped": True})

    def put(self, request):
        """Confirmed: saved as the preview ran it, and read now."""
        try:
            preview, refusal = self._preview(request)
        except rails.RailRefused as exc:
            return _refused(exc)
        if refusal:
            return refusal
        if preview["value"] is None:
            return Response({"detail": "The preview found no number; nothing was saved."},
                            status=400)
        reader, kpi, connection, _ = self._setup(request, request.data)
        feed = self.model.objects.filter(kpi=kpi).first() or self.model(
            tenant_id=kpi.tenant_id, kpi=kpi, created_by=request.user)
        feed.connection = connection
        for key, value in preview["settings"].items():
            setattr(feed, key, value)
        feed.active = True
        feed.read_open = feeds.read_open_choice(request.data, feed.read_open)
        feed.last_success_at = None
        feed.save()
        feeds.stop_other_feeds(kpi, keep=self.kind)
        Kpi.all_objects.filter(pk=kpi.pk).update(feed=self.kind)
        _audit(reader.company, request.user, f"scorecard.{self.kind}_feed_set", kpi=kpi.name)
        feed.refresh_from_db()
        result = self._run(feed, _today(request))
        return Response({"feed": _feed_payload(feed, self.kind), "run": result})


class McpFeedView(_RailFeed):
    kind = "mcp"
    model = KpiMcpFeed
    connection_model = McpConnection

    def _settings(self, data) -> dict:
        tool = str(data.get("tool") or "").strip()[:120]
        arguments = data.get("arguments") or {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments or "{}")
            except ValueError:
                raise rails.RailRefused("The arguments aren't valid JSON.") from None
        if not tool:
            raise rails.RailRefused("Choose the tool.")
        if not isinstance(arguments, dict):
            raise rails.RailRefused("The arguments are a JSON object.")
        return {"tool": tool, "arguments": arguments,
                "value_path": str(data.get("value_path") or "").strip()[:200],
                "from_ai": bool(data.get("from_ai"))}

    def _value(self, kpi, connection, s, start, end):
        client = rails.mcp_client(connection)
        raw = client.call(s["tool"], rails.fill(s["arguments"], rails.placeholders(start, end)))
        try:
            return rails.number_at(kpi, raw, s["value_path"]), raw
        except rails.RailRefused:
            return None, raw

    def _run(self, feed, today):
        client = rails.mcp_client(feed.connection)
        return rails.run_feed(feed, today, lambda s, e: rails.mcp_value(feed, client, s, e),
                              source=KpiReading.Source.MCP)


class McpPreviewView(McpFeedView):
    def post(self, request):
        try:
            preview, refusal = self._preview(request)
        except rails.RailRefused as exc:
            return _refused(exc)
        return refusal or Response(preview)


class McpProposeView(McpFeedView):
    def post(self, request):
        reader, kpi, connection, refusal = self._setup(request, request.data)
        if refusal:
            return refusal
        try:
            _one_number(kpi)
            proposal = rails_ai.propose(reader.company.tenant, kpi, connection.tools or [],
                                        request.data.get("description"))
            if not proposal["tool"]:
                return Response({"proposal": proposal, "preview": None})
            start, end = rails.last_closed(kpi, _today(request))
            settings_ = {"tool": proposal["tool"], "arguments": proposal["arguments"],
                         "value_path": proposal["path"]}
            try:
                value, raw = self._value(kpi, connection, settings_, start, end)
                preview = {"period": rails.P.long_label(start, kpi.cadence),
                           "value": None if value is None else f"{value.normalize():f}",
                           "answer": rails.excerpt(raw)}
            except (rails.RailRefused, safe_http.FetchRefused, safe_http.FetchFailed) as exc:
                preview = {"error": str(exc)}
        except rails.RailRefused as exc:
            return _refused(exc)
        return Response({"proposal": proposal, "preview": preview})


class ApiFeedView(_RailFeed):
    kind = "api"
    model = KpiApiFeed
    connection_model = ApiConnection

    def _settings(self, data) -> dict:
        method = str(data.get("method") or "GET").upper()
        if method not in ("GET", "POST"):
            raise rails.RailRefused("A feed reads with GET or POST.")
        query = data.get("query") or {}
        if isinstance(query, str):
            try:
                query = json.loads(query or "{}")
            except ValueError:
                raise rails.RailRefused("The query isn't valid JSON.") from None
        if not isinstance(query, dict):
            raise rails.RailRefused("The query is names and values.")
        body = data.get("body")
        if isinstance(body, str) and body.strip():
            try:
                body = json.loads(body)
            except ValueError:
                raise rails.RailRefused("The body isn't valid JSON.") from None
        return {"method": method, "path": str(data.get("path") or "").strip()[:500],
                "query": {str(k): str(v) for k, v in query.items()},
                "body": body if method == "POST" else None,
                "value_path": str(data.get("value_path") or "").strip()[:200]}

    def _value(self, kpi, connection, s, start, end):
        names = rails.placeholders(start, end)
        raw = rails.api_request(connection, method=s["method"], path=rails.fill(s["path"], names),
                                query=rails.fill(s["query"], names),
                                body=rails.fill(s["body"], names) if s["method"] == "POST"
                                else None)
        try:
            return rails.number_at(kpi, raw, s["value_path"]), raw
        except rails.RailRefused:
            return None, raw

    def _run(self, feed, today):
        return rails.run_feed(feed, today, lambda s, e: rails.api_value(feed, s, e),
                              source=KpiReading.Source.API)


class ApiPreviewView(ApiFeedView):
    def post(self, request):
        try:
            preview, refusal = self._preview(request)
        except rails.RailRefused as exc:
            return _refused(exc)
        return refusal or Response(preview)


# ------------------------------------------------------------------ a connector request

class ConnectorRequestView(Base):
    def post(self, request):
        from apps.platform import feedback
        from apps.tenancy.models import TENANT_ROLES

        if request.membership is None or request.membership.role not in TENANT_ROLES:
            raise Http404
        system = " ".join(str(request.data.get("system") or "").split())[:200]
        numbers = str(request.data.get("numbers") or "").strip()[:2000]
        client = " ".join(str(request.data.get("client") or "").split())[:200]
        if not system or not numbers:
            return Response({"detail": "Say which system, and which numbers you want from "
                                       "it."}, status=400)
        # A connector request's three answers sit in the feedback's three
        # fields; the kind says to label them System, Numbers and Client.
        row = feedback.submit(request, doing=system, happened=numbers,
                              expected=client or "Not said",
                              page_url=str(request.data.get("page_url") or "/scorecard")[:500],
                              kind="connector")
        return Response({"sent": True, "id": str(row.pk)}, status=201)
