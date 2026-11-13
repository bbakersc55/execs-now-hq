"""P13: the connector rails (`docs/p13_connector_rails.md`).

- **Webhook:** the address shown once and stored hashed, rotation, JSON,
  form fields and query parameters, the path mapping, replace versus add,
  a typed-by-hand reading kept, the company's address by KPI key, the rate
  limit, the last 20 deliveries, practice isolation.
- **Any MCP server:** a fake server; Test connection lists its tools;
  Claude's proposal with a live preview and nothing saved until confirmed;
  the nightly read deterministic, with no AI.
- **Any API:** a fake server; the secret where its kind puts it, never shown
  again; the preview; the nightly read.
- **Safety,** each rule with a test that tries to break it: http, private,
  loopback, link-local and metadata addresses, a name that resolves private,
  rebinding on connect, a redirect off the host, the size and time caps,
  credentials in the address; failures said on the feed.
- **A connector request** lands in the platform owner's Feedback.
"""

from __future__ import annotations

import json
import socket
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.test import Client
from django.utils import timezone

from apps.scorecard import rails, safe_http
from apps.scorecard import periods as P
from apps.scorecard.models import (ApiConnection, KpiApiFeed, KpiMcpFeed, KpiReading,
                                   KpiWebhookFeed, McpConnection, WebhookDelivery)
from apps.tenancy.context import tenant_context

from .factories import MembershipFactory, TenantFactory
from .test_scorecard import post, sc  # noqa: F401  (the fixture)

R = "/api/scorecard/rails/"
PUBLIC_IP = "93.184.216.34"


def put(client, url, data):
    return client.put(url, json.dumps(data), content_type="application/json")


def ff(sc):
    return sc["api"].as_(sc["practice"]["ff"])


@pytest.fixture
def public_dns(monkeypatch):
    """Every name resolves to one public address (no network in tests)."""
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda host, port, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                                                   (PUBLIC_IP, port))])


def kpi_of(sc, name="all"):
    return sc["kpis"][name]


def reading(sc, kpi, start):
    with tenant_context(sc["tenant"].pk):
        return KpiReading.objects.filter(kpi=kpi, period_start=start,
                                         membership__isnull=True).first()


def this_week(sc):
    return P.start_of(timezone.localdate(), "weekly", "monday")


# ------------------------------------------------------------------ the webhook

@pytest.fixture
def hook(sc):
    r = put(ff(sc), f"{R}webhook/", {"company": str(sc["company"].pk),
                                     "kpi": str(kpi_of(sc).pk), "mode": "replace"})
    assert r.status_code == 200, r.content
    return {**sc, "token": r.json()["token"], "url": f"/webhooks/kpi/{r.json()['token']}/"}


def test_the_address_is_shown_once_and_stored_hashed(hook):
    sc = hook
    with tenant_context(sc["tenant"].pk):
        feed = KpiWebhookFeed.objects.get(kpi=kpi_of(sc))
    assert feed.secret_hash == rails.hash_of(sc["token"]) and sc["token"] not in json.dumps(
        feed.__dict__, default=str)
    got = ff(sc).get(f"{R}webhook/?company={sc['company'].pk}&kpi={kpi_of(sc).pk}").json()
    assert sc["token"] not in json.dumps(got) and got["feed"]["hint"] == sc["token"][-4:]
    assert got["test"]["zapier"] and got["test"]["make"]


@pytest.mark.parametrize("style", ["json", "form", "query"])
def test_each_payload_style_saves_a_reading_from_a_webhook(hook, style):
    sc = hook
    day = this_week(sc)
    c = Client()
    if style == "json":
        r = c.post(sc["url"], json.dumps({"value": 12, "date": day.isoformat(), "note": "hi"}),
                   content_type="application/json")
    elif style == "form":
        r = c.post(sc["url"], {"value": "12", "date": day.isoformat()})
    else:
        r = c.post(f"{sc['url']}?value=12&date={day.isoformat()}")
    assert r.status_code == 200, r.content
    got = reading(sc, kpi_of(sc), day)
    assert got.value == 12 and got.source == "webhook"


def test_replace_versus_add(hook):
    sc = hook
    c = Client()
    for value in (3, 4):
        c.post(sc["url"], json.dumps({"value": value}), content_type="application/json")
    assert reading(sc, kpi_of(sc), this_week(sc)).value == 4          # replaced
    put(ff(sc), f"{R}webhook/", {"company": str(sc["company"].pk), "kpi": str(kpi_of(sc).pk),
                                 "mode": "add"})
    for _ in range(3):
        r = c.post(sc["url"], json.dumps({"value": 1}), content_type="application/json")
    assert reading(sc, kpi_of(sc), this_week(sc)).value == 7          # 4 + 1 + 1 + 1
    assert "added to, now 7" in r.json()["what"]


def test_paths_map_another_systems_own_payload(hook):
    sc = hook
    put(ff(sc), f"{R}webhook/", {"company": str(sc["company"].pk), "kpi": str(kpi_of(sc).pk),
                                 "mode": "replace", "value_path": "data.metrics[1].count",
                                 "date_path": "data.closed_at"})
    last = P.previous_start(this_week(sc), "weekly", "monday")
    r = Client().post(sc["url"], json.dumps({"data": {
        "closed_at": f"{last.isoformat()}T15:30:00Z",
        "metrics": [{"count": 1}, {"count": 41}]}}), content_type="application/json")
    assert r.status_code == 200, r.content
    assert reading(sc, kpi_of(sc), last).value == 41


def test_a_reading_typed_by_hand_is_never_replaced(hook):
    sc = hook
    day = this_week(sc)
    with tenant_context(sc["tenant"].pk):
        KpiReading.objects.create(tenant=sc["tenant"], kpi=kpi_of(sc), period_start=day,
                                  value=99, source="hand", entered_at=timezone.now())
    r = Client().post(sc["url"], json.dumps({"value": 5}), content_type="application/json")
    assert r.status_code == 200 and r.json()["ok"] is False and "kept" in r.json()["what"]
    assert reading(sc, kpi_of(sc), day).value == 99


@pytest.mark.parametrize("body,words", [
    ({"value": "lots"}, "number"), ({}, "No value"),
    ({"value": 1, "date": "2099-01-01"}, "hasn't started"), ({"value": 1, "date": "soon"}, "date"),
])
def test_a_bad_post_is_refused_in_words_and_listed(hook, body, words):
    sc = hook
    r = Client().post(sc["url"], json.dumps(body), content_type="application/json")
    assert r.status_code == 400 and words in r.json()["what"]
    with tenant_context(sc["tenant"].pk):
        assert WebhookDelivery.objects.filter(ok=False).count() == 1


def test_rotation_retires_the_old_address(hook):
    sc = hook
    r = post(ff(sc), f"{R}webhook/rotate/", {"company": str(sc["company"].pk),
                                             "kpi": str(kpi_of(sc).pk)})
    new = r.json()["token"]
    assert Client().post(sc["url"], {"value": "1"}).status_code == 404
    assert Client().post(f"/webhooks/kpi/{new}/", {"value": "1"}).status_code == 200
    assert Client().post("/webhooks/kpi/kh_nonsense/", {"value": "1"}).status_code == 404


def test_the_rate_limit(hook, monkeypatch):
    from apps.accounts.ratelimit import RateLimit
    from apps.scorecard import views_rails

    monkeypatch.setattr(views_rails, "WEBHOOK_RATE", RateLimit(3, 60, "kpi_webhook_test"))
    sc = hook
    codes = [Client().post(sc["url"], {"value": "1"}).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]


def _counters(prefix):
    from apps.accounts.models import RateCount

    return RateCount.objects.filter(prefix=prefix)


def test_a_sender_trying_made_up_addresses_is_cut_off(hook, monkeypatch):
    """Posts to addresses that don't exist count against the sender, never
    against the made-up address; past the limit the sender is refused
    everywhere, its real address included, while another sender isn't."""
    from apps.accounts.ratelimit import RateLimit
    from apps.scorecard import views_rails

    monkeypatch.setattr(views_rails, "MISS_RATE", RateLimit(3, 60, "kpi_webhook_miss"))
    sc, them = hook, {"REMOTE_ADDR": "203.0.113.9"}
    codes = [Client().post(f"/webhooks/kpi/kh_madeup{i}/", {"value": "1"}, **them).status_code
             for i in range(8)]
    codes.append(Client().post(f"/webhooks/company/ch_madeup/", {"value": "1"}, **them).status_code)
    assert codes == [404, 404, 404] + [429] * 6
    cut = Client().post(sc["url"], {"value": "1"}, **them)
    assert cut.status_code == 429 and "don't exist" in cut.json()["what"]
    # The counter table holds one row for the sender's misses, none per address.
    assert not _counters("kpi_webhook").exists()
    assert _counters("kpi_webhook_miss").count() == 1
    assert _counters("kpi_webhook_miss").get().count == 3
    # Someone else posting to the real address is unaffected.
    assert Client().post(sc["url"], {"value": "1"}, REMOTE_ADDR="198.51.100.4").status_code == 200


def test_one_sender_is_limited_across_every_address(hook, monkeypatch):
    from apps.accounts.ratelimit import RateLimit
    from apps.scorecard import views_rails

    monkeypatch.setattr(views_rails, "SENDER_RATE", RateLimit(4, 60, "kpi_webhook_sender"))
    sc = hook
    r = post(ff(sc), f"{R}company-webhook/", {"company": str(sc["company"].pk)})
    company = f"/webhooks/company/{r.json()['token']}/"
    them = {"REMOTE_ADDR": "203.0.113.10"}
    codes = []
    for i in range(3):
        codes.append(Client().post(sc["url"], {"value": "1"}, **them).status_code)
        codes.append(Client().post(company, json.dumps({"kpi": "for_everyone", "value": 2}),
                                   content_type="application/json", **them).status_code)
    assert codes == [200, 200, 200, 200, 429, 429]
    assert Client().post(sc["url"], {"value": "1"}, REMOTE_ADDR="198.51.100.5").status_code == 200


def test_the_sender_is_the_address_the_proxy_saw(hook, monkeypatch, settings):
    """Behind Railway's one proxy, X-Forwarded-For's last entry is the sender;
    a sender can't dodge the limit by writing its own entries in front."""
    from apps.accounts.ratelimit import RateLimit
    from apps.scorecard import views_rails

    settings.TRUSTED_PROXY_HOPS = 1
    monkeypatch.setattr(views_rails, "MISS_RATE", RateLimit(2, 60, "kpi_webhook_miss"))
    codes = [Client().post(f"/webhooks/kpi/kh_x{i}/", {"value": "1"},
                           HTTP_X_FORWARDED_FOR=f"10.0.0.{i}, 203.0.113.20").status_code
             for i in range(4)]
    assert codes == [404, 404, 429, 429]


def test_old_counters_are_cleared(hook):
    """A new minute deletes the finished minutes' counters of every webhook
    limit, the old per-address ones included."""
    from datetime import timedelta as td

    from apps.accounts.models import RateCount

    sc, old = hook, timezone.now() - td(minutes=5)
    for prefix in ("kpi_webhook", "kpi_webhook_sender", "kpi_webhook_miss"):
        for i in range(3):
            RateCount.objects.create(prefix=prefix, key_digest=f"{prefix[:20]}{i}",
                                     window_start=old, count=7)
    RateCount.objects.create(prefix="site_lead", key_digest="kept", window_start=old, count=1)
    assert Client().post(sc["url"], {"value": "1"}, REMOTE_ADDR="198.51.100.6").status_code == 200
    left = set(RateCount.objects.values_list("prefix", "window_start"))
    assert all(start > old for prefix, start in left if prefix.startswith("kpi_webhook"))
    assert ("site_lead", old) in left


def test_the_last_twenty_deliveries_are_kept(hook):
    sc = hook
    for i in range(23):
        Client().post(sc["url"], {"value": str(i)})
    got = ff(sc).get(f"{R}webhook/?company={sc['company'].pk}&kpi={kpi_of(sc).pk}").json()
    deliveries = got["feed"]["deliveries"]
    assert len(deliveries) == 20 and "now 22" in deliveries[0]["what"]
    assert deliveries[0]["received"] == "value=22"


def test_the_companys_address_takes_a_kpi_key(hook):
    sc = hook
    r = post(ff(sc), f"{R}company-webhook/", {"company": str(sc["company"].pk)})
    address = f"/webhooks/company/{r.json()['token']}/"
    ok = Client().post(address, json.dumps({"kpi": "for_everyone", "value": 8}),
                       content_type="application/json")
    assert ok.status_code == 200, ok.content
    assert reading(sc, kpi_of(sc), this_week(sc)).value == 8
    # A KPI with no webhook feed doesn't take it.
    missing = Client().post(address, json.dumps({"kpi": "cash", "value": 8}),
                            content_type="application/json")
    assert missing.status_code == 404
    got = ff(sc).get(f"{R}company-webhook/?company={sc['company'].pk}").json()
    assert got["keys"] == [{"kpi": "For everyone", "key": "for_everyone"}]
    assert len(got["deliveries"]) == 2


def test_per_person_kpis_and_other_practices_are_refused(hook):
    sc = hook
    r = put(ff(sc), f"{R}webhook/", {"company": str(sc["company"].pk),
                                     "kpi": str(kpi_of(sc, "calls").pk)})
    assert r.status_code == 400 and "per person" in r.json()["detail"]
    stranger = sc["api"].as_(MembershipFactory(tenant=TenantFactory(), role="FF"))
    assert stranger.get(f"{R}webhook/?company={sc['company'].pk}&kpi={kpi_of(sc).pk}") \
        .status_code == 404
    assert put(stranger, f"{R}webhook/", {"company": str(sc["company"].pk),
                                          "kpi": str(kpi_of(sc).pk)}).status_code == 404
    for who in ("owner", "member"):
        member = sc["api"].as_(sc["who"][who])
        assert member.get(f"{R}webhook/?company={sc['company'].pk}&kpi={kpi_of(sc).pk}") \
            .status_code in (403, 404)


# ------------------------------------------------------------------ a fake MCP server

class FakeMcp:
    def __init__(self):
        self.calls = []

    def __call__(self, method, url, *, headers=None, query=None, body=None, **kw):
        message = json.loads(body or b"{}")
        self.calls.append((url, dict(headers or {}), message))
        name = message.get("method")
        if name == "initialize":
            return 200, {"mcp-session-id": "s-1", "content-type": "application/json"}, json.dumps(
                {"jsonrpc": "2.0", "id": message["id"], "result": {"serverInfo": {}}}).encode()
        if name == "notifications/initialized":
            return 202, {}, b""
        if name == "tools/list":
            return 200, {}, json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": {
                "tools": [{"name": "count_tickets", "description": "Tickets by status",
                           "inputSchema": {"type": "object", "properties": {
                               "status": {"type": "string"}, "since": {"type": "string"}}}}]}}
            ).encode()
        args = message["params"]["arguments"]
        count = 30 + int(args.get("since", "2026-01-01")[8:10])
        return 200, {}, json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": {
            "content": [{"type": "text", "text": json.dumps({"data": {"open": count}})}]}}).encode()


@pytest.fixture
def mcp(sc, monkeypatch, public_dns):
    fake = FakeMcp()
    monkeypatch.setattr(safe_http, "fetch", fake)
    r = post(ff(sc), f"{R}mcp/", {"company": str(sc["company"].pk), "name": "Helpdesk",
                                  "url": "https://mcp.helpdesk.example/mcp",
                                  "token": "secret-token-123456"})
    assert r.status_code == 201, r.content
    return {**sc, "fake": fake, "connection": r.json()["id"]}


def test_test_connection_lists_the_tools_and_never_shows_the_token(mcp):
    sc = mcp
    r = post(ff(sc), f"{R}mcp/{sc['connection']}/test/")
    assert r.status_code == 200 and r.json()["tools"] == ["count_tickets"]
    assert sc["fake"].calls[0][1]["Authorization"] == "Bearer secret-token-123456"
    listed = ff(sc).get(f"{R}mcp/?company={sc['company'].pk}").json()
    assert "secret-token-123456" not in json.dumps(listed)
    assert listed["connections"][0]["secret_hint"] == "3456"
    assert post(sc["api"].as_(sc["practice"]["cf"]), f"{R}mcp/", {
        "company": str(sc["company"].pk), "name": "X",
        "url": "https://x.example/mcp"}).status_code == 403


def test_claude_proposes_the_preview_is_live_and_nothing_saves_until_confirmed(mcp, fake_claude):
    sc = mcp
    post(ff(sc), f"{R}mcp/{sc['connection']}/test/")
    fake_claude.reply = json.dumps({"tool": "count_tickets",
                                    "arguments": {"status": "open", "since": "{period_start}"},
                                    "path": "data.open", "why": "Open tickets."})
    status = ff(sc).get(f"{R}mcp-feed/?company={sc['company'].pk}&kpi={kpi_of(sc).pk}").json()
    assert Decimal(status["ai"]["estimate_usd"]) >= 0
    r = post(ff(sc), f"{R}mcp-feed/propose/", {
        "company": str(sc["company"].pk), "kpi": str(kpi_of(sc).pk),
        "connection": sc["connection"], "description": "How many tickets are open"})
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["proposal"]["tool"] == "count_tickets"
    last = P.previous_start(this_week(sc), "weekly", "monday")
    assert body["preview"]["value"] == str(30 + last.day)
    assert fake_claude.requests[-1]["model"].startswith("claude-sonnet")    # Standard
    with tenant_context(sc["tenant"].pk):
        assert not KpiMcpFeed.objects.exists()
    saved = put(ff(sc), f"{R}mcp-feed/", {
        "company": str(sc["company"].pk), "kpi": str(kpi_of(sc).pk),
        "connection": sc["connection"], "tool": "count_tickets", "from_ai": True,
        "arguments": {"status": "open", "since": "{period_start}"}, "value_path": "data.open"})
    assert saved.status_code == 200, saved.content
    assert saved.json()["run"]["ok"] is True
    assert reading(sc, kpi_of(sc), last).source == "mcp"


def test_the_nightly_mcp_read_is_deterministic_and_uses_no_ai(mcp, fake_claude):
    sc = mcp
    put(ff(sc), f"{R}mcp-feed/", {
        "company": str(sc["company"].pk), "kpi": str(kpi_of(sc).pk),
        "connection": sc["connection"], "tool": "count_tickets",
        "arguments": {"since": "{period_start}"}, "value_path": "data.open"})
    asked = len(fake_claude.requests)
    with tenant_context(sc["tenant"].pk):
        KpiMcpFeed.objects.update(last_run_at=timezone.now() - timedelta(days=2))
        result = rails.run_due(sc["tenant"].pk, timezone.localdate())
    assert result == {"ran": 1, "failed": 0}
    assert len(fake_claude.requests) == asked
    calls = [c[2]["params"]["arguments"] for c in sc["fake"].calls
             if c[2].get("method") == "tools/call"]
    assert all(a["since"][:4].isdigit() and "{" not in a["since"] for a in calls)


def test_a_path_with_nothing_there_is_said(mcp):
    sc = mcp
    r = post(ff(sc), f"{R}mcp-feed/preview/", {
        "company": str(sc["company"].pk), "kpi": str(kpi_of(sc).pk),
        "connection": sc["connection"], "tool": "count_tickets", "arguments": {},
        "value_path": "data.closed"})
    assert r.status_code == 200 and r.json()["value"] is None and "open" in r.json()["answer"]
    refused = put(ff(sc), f"{R}mcp-feed/", {
        "company": str(sc["company"].pk), "kpi": str(kpi_of(sc).pk),
        "connection": sc["connection"], "tool": "count_tickets", "arguments": {},
        "value_path": "data.closed"})
    assert refused.status_code == 400 and "no number" in refused.json()["detail"]


# ------------------------------------------------------------------ a fake API

class FakeApi:
    def __init__(self, answer=None, status=200):
        self.calls = []
        self.answer = answer
        self.status = status

    def __call__(self, method, url, *, headers=None, query=None, body=None, **kw):
        self.calls.append({"method": method, "url": url, "headers": dict(headers or {}),
                           "query": dict(query or {}), "body": body})
        answer = self.answer if self.answer is not None else {"data": {"mrr": 4200,
                                                                         "month": query}}
        return self.status, {}, json.dumps(answer).encode()


@pytest.fixture
def apifeed(sc, monkeypatch, public_dns):
    fake = FakeApi()
    monkeypatch.setattr(safe_http, "fetch", fake)
    return {**sc, "fake": fake}


@pytest.mark.parametrize("kind,name,check", [
    ("header", "X-Api-Key", lambda c: c["headers"]["X-Api-Key"] == "k-9876"),
    ("basic", "", lambda c: c["headers"]["Authorization"].startswith("Basic ")),
    ("query", "token", lambda c: c["query"]["token"] == "k-9876"),
])
def test_the_api_feed_puts_its_secret_where_its_kind_says_and_reads(apifeed, kind, name, check):
    sc = apifeed
    r = post(ff(sc), f"{R}api/", {"company": str(sc["company"].pk), "name": "Billing",
                                  "base_url": "https://api.billing.example/v1",
                                  "auth_kind": kind, "auth_name": name, "secret": "k-9876"})
    assert r.status_code == 201, r.content
    assert "k-9876" not in json.dumps(ff(sc).get(f"{R}api/?company={sc['company'].pk}").json())
    body = {"company": str(sc["company"].pk), "kpi": str(kpi_of(sc).pk),
            "connection": r.json()["id"], "method": "GET", "path": "/mrr/{year}-{month}",
            "query": {"since": "{period_start}"}, "value_path": "data.mrr"}
    preview = post(ff(sc), f"{R}api-feed/preview/", body)
    assert preview.status_code == 200 and preview.json()["value"] == "4200", preview.content
    call = sc["fake"].calls[-1]
    assert check(call) and call["url"].startswith("https://api.billing.example/v1/mrr/")
    assert "{" not in call["url"] and "{" not in call["query"]["since"]
    saved = put(ff(sc), f"{R}api-feed/", body)
    assert saved.status_code == 200 and saved.json()["run"]["ok"] is True
    with tenant_context(sc["tenant"].pk):
        assert KpiReading.objects.filter(kpi=kpi_of(sc), source="api").count() >= 13


def test_an_api_failure_is_said_on_the_feed(apifeed):
    sc = apifeed
    conn = post(ff(sc), f"{R}api/", {"company": str(sc["company"].pk), "name": "Billing",
                                     "base_url": "https://api.billing.example",
                                     "auth_kind": "header", "secret": "k"}).json()
    put(ff(sc), f"{R}api-feed/", {"company": str(sc["company"].pk), "kpi": str(kpi_of(sc).pk),
                                  "connection": conn["id"], "path": "/mrr",
                                  "value_path": "data.mrr"})
    sc["fake"].status = 401
    with tenant_context(sc["tenant"].pk):
        KpiApiFeed.objects.update(last_run_at=timezone.now() - timedelta(days=2))
        assert rails.run_due(sc["tenant"].pk, timezone.localdate())["failed"] == 1
        feed = KpiApiFeed.objects.get()
    assert feed.last_error == "The API refused the secret. Check it on the connection."
    assert "k" not in feed.last_error.split()


def test_a_path_cannot_leave_the_connections_address(apifeed):
    sc = apifeed
    conn = post(ff(sc), f"{R}api/", {"company": str(sc["company"].pk), "name": "Billing",
                                     "base_url": "https://api.billing.example/v1",
                                     "auth_kind": "header", "secret": "k"}).json()
    for path in ("https://evil.example/steal", "../admin", "../v1evil/x", "//evil.example/x"):
        r = post(ff(sc), f"{R}api-feed/preview/", {
            "company": str(sc["company"].pk), "kpi": str(kpi_of(sc).pk), "connection": conn["id"],
            "path": path, "value_path": "x"})
        if path.startswith("//"):          # read as a path under the address, not a host
            assert "stay under" not in r.json().get("detail", ""), path
            continue
        assert r.status_code == 400 and "stay under" in r.json()["detail"], path


# ------------------------------------------------------------------ safety

@pytest.mark.parametrize("url,words", [
    ("http://api.example.com/x", "https"),
    ("https://10.0.0.1/x", "private"),
    ("https://127.0.0.1/x", "private"),
    ("https://[::1]/x", "private"),
    ("https://169.254.169.254/latest/meta-data", "private"),
    ("https://169.254.10.10/x", "private"),
    ("https://metadata.google.internal/computeMetadata", "metadata"),
    ("https://user:pass@api.example.com/x", "credentials"),
    ("ftp://api.example.com/x", "https"),
])
def test_addresses_the_app_will_not_fetch(url, words, monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, **kw: [
        (socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_STREAM, 6, "",
         (host, port))])
    with pytest.raises(safe_http.FetchRefused, match=words):
        safe_http.fetch("GET", url)


def test_a_name_that_resolves_to_a_private_address_is_refused(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC_IP, port)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.20", port))])
    with pytest.raises(safe_http.FetchRefused, match="private or internal"):
        safe_http.fetch("GET", "https://sneaky.example.com/")


def test_rebinding_on_connect_is_refused(monkeypatch):
    class Sock:
        def getpeername(self):
            return ("10.1.2.3", 443)

        def close(self):
            self.closed = True

    monkeypatch.setattr(socket, "create_connection", lambda addr, timeout: Sock())
    conn = safe_http._PinnedConnection("api.example.com", 443, PUBLIC_IP, 5)
    with pytest.raises(safe_http.FetchRefused, match="changed to a private"):
        conn.connect()


class FakeResponse:
    def __init__(self, status, headers, body):
        self.status, self._headers, self._body = status, headers, body

    def getheaders(self):
        return list(self._headers.items())

    def read(self, n):
        chunk, self._body = self._body[:n], self._body[n:]
        return chunk


class FakeConnection:
    def __init__(self, responses):
        self.responses = responses

    def request(self, *a, **kw):
        pass

    def getresponse(self):
        return self.responses.pop(0)

    def close(self):
        pass


def test_no_redirect_off_the_host(monkeypatch, public_dns):
    monkeypatch.setattr(safe_http, "connection_for", lambda *a: FakeConnection([
        FakeResponse(302, {"Location": "https://elsewhere.example/x"}, b"")]))
    with pytest.raises(safe_http.FetchRefused, match="another host"):
        safe_http.fetch("GET", "https://api.example.com/x")


def test_a_redirect_on_the_host_is_followed(monkeypatch, public_dns):
    responses = [FakeResponse(302, {"Location": "/y"}, b""), FakeResponse(200, {}, b"{\"ok\":1}")]
    monkeypatch.setattr(safe_http, "connection_for", lambda *a: FakeConnection(responses))
    assert safe_http.fetch("GET", "https://api.example.com/x")[2] == b"{\"ok\":1}"


def test_the_size_cap(monkeypatch, public_dns):
    monkeypatch.setattr(safe_http, "connection_for", lambda *a: FakeConnection([
        FakeResponse(200, {}, b"x" * 2000)]))
    with pytest.raises(safe_http.FetchFailed, match="larger than"):
        safe_http.fetch("GET", "https://api.example.com/x", max_bytes=1000)


def test_the_time_cap(monkeypatch, public_dns):
    class Slow(FakeConnection):
        def getresponse(self):
            raise socket.timeout()

    monkeypatch.setattr(safe_http, "connection_for", lambda *a: Slow([]))
    with pytest.raises(safe_http.FetchFailed, match="too long"):
        safe_http.fetch("GET", "https://api.example.com/x")


def test_connections_to_private_addresses_are_refused_when_made(sc, monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.7", port))])
    for path, body in (("mcp/", {"name": "x", "url": "https://internal.example/mcp"}),
                       ("api/", {"name": "x", "base_url": "https://internal.example",
                                 "auth_kind": "header"})):
        r = post(ff(sc), f"{R}{path}", {"company": str(sc["company"].pk), **body})
        assert r.status_code == 400 and "private or internal" in r.json()["detail"]
    with tenant_context(sc["tenant"].pk):
        assert not McpConnection.objects.exists() and not ApiConnection.objects.exists()


def test_json_paths():
    data = {"a": {"b": [{"c": 1}, {"c": 2}]}, "n": 5}
    assert safe_http.json_path(data, "a.b[1].c") == 2
    assert safe_http.json_path(data, "a.b[-1].c") == 2
    assert safe_http.json_path(data, "n") == 5
    assert safe_http.json_path(data, "a.x") is None and safe_http.json_path(data, "a.b[9]") is None


def test_the_demo_refuses_real_connections(sc, settings, public_dns):
    settings.APP_ENVIRONMENT = "demo"
    settings.IS_DEMO = True
    r = post(ff(sc), f"{R}mcp/", {"company": str(sc["company"].pk), "name": "x",
                                  "url": "https://mcp.example.com/mcp"})
    assert r.status_code == 409 and "demo" in r.json()["detail"]


# ------------------------------------------------------------------ a connector request

def test_a_connector_request_lands_in_the_platform_owners_feedback(sc):
    from apps.platform.models import Feedback

    r = post(ff(sc), f"{R}request/", {"system": "ServiceTitan", "numbers": "Jobs booked a week",
                                      "client": "Northwind Foods"})
    assert r.status_code == 201, r.content
    row = Feedback.all_objects.get(pk=r.json()["id"])
    assert (row.kind, row.doing, row.happened, row.expected) == (
        "connector", "ServiceTitan", "Jobs booked a week", "Northwind Foods")
    assert post(sc["api"].as_(sc["who"]["owner"]), f"{R}request/",
                {"system": "x", "numbers": "y"}).status_code == 404
    assert post(ff(sc), f"{R}request/", {"system": "x"}).status_code == 400
