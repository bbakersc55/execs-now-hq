"""The MCP server, through a real MCP client (P7, docs/p7_mcp.md).

The SDK's own client speaks Streamable HTTP to the ASGI app in process: no
network, the same requests Claude makes. Tokens come from the real OAuth flow
(`ai_app_flow.connect`). The database is committed (`transaction=True`)
because the server runs tools on its own thread, as it does in production.

Covered: no token is a 401 naming the protected-resource metadata; tools and
prompts are listed; role scoping on three tools (invoices, companies, notes);
each write lands in its queue marked as made by an AI app; revoking ends
access; every call is an Activity line with the tool and ids, never content.
"""

from __future__ import annotations

import asyncio
import json

import httpx2
import pytest
from django.conf import settings
from django.utils import timezone
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from apps.tenancy.context import tenant_context
from apps.tenancy.models import AuditEvent

from .ai_app_flow import connect
from .factories import (
    ClientAssignmentFactory, ClientCompanyFactory, ClientInvoiceFactory, CompanyFactory,
    ContactEmailFactory, ContactFactory, NoteFactory, StrategySessionFactory,
)

pytestmark = pytest.mark.django_db(transaction=True)


def _with_client(token, work):
    """Run `work(client)` against a fresh MCP app, as an AI app holding `token`."""
    from config.mcp_asgi import create_app

    app, server = create_app()

    async def go():
        async with server.session_manager.run():
            headers = {"Authorization": f"Bearer {token}"}
            async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app),
                                          base_url=settings.MCP_PUBLIC_URL,
                                          headers=headers) as http:
                async with Client(streamable_http_client(f"{settings.MCP_PUBLIC_URL}/mcp",
                                                         http_client=http)) as client:
                    return await work(client)

    return asyncio.run(go())


def call(token, tool, **args):
    async def work(client):
        return await client.call_tool(tool, args)

    result = _with_client(token, work)
    return result.is_error, _data(result)


def _data(result):
    if result.structured_content is not None:
        data = result.structured_content
        return data.get("result", data) if isinstance(data, dict) and len(data) == 1 \
            and "result" in data else data
    text = "".join(getattr(c, "text", "") for c in result.content)
    try:
        return json.loads(text)
    except ValueError:
        return text


def raw(method, path, token=None, **kw):
    from config.mcp_asgi import create_app

    app, server = create_app()

    async def go():
        async with server.session_manager.run():
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app),
                                          base_url=settings.MCP_PUBLIC_URL,
                                          headers=headers) as http:
                return await http.request(method, path, **kw)

    return asyncio.run(go())


@pytest.fixture
def world(seeded_tenant, ff, cf, va):
    """Two client companies, one assigned to the associate; a contact in each;
    an invoice; a note and a PIN-locked note; a strategy session."""
    t = seeded_tenant
    with tenant_context(t.pk):
        mine = ClientCompanyFactory(tenant=t, name="Alder Fasteners")
        other = ClientCompanyFactory(tenant=t, name="Birch Logistics")
        ClientAssignmentFactory(tenant=t, user=cf.user, company=mine, assigned_by=ff.user)
        wes = ContactFactory(tenant=t, first_name="Wes", last_name="Calder", company=mine)
        ContactEmailFactory(tenant=t, contact=wes, address="wes@alder.example",
                            is_primary=True)
        bo = ContactFactory(tenant=t, first_name="Bo", last_name="Birch", company=other)
        ContactEmailFactory(tenant=t, contact=bo, address="bo@birch.example", is_primary=True)
        invoice = ClientInvoiceFactory(tenant=t, client_company=mine, contact=wes)
        open_note = NoteFactory(tenant=t, body="Wes wants the scrap report weekly.",
                                contact=wes, created_by=ff.user)
        locked = NoteFactory(tenant=t, body="Private: salary talk.", contact=wes,
                             created_by=ff.user, pin_hash="x", pin_set_at=timezone.now())
        session = StrategySessionFactory(tenant=t, contact=wes, company=mine, owner=ff.user)
    return {"mine": mine, "other": other, "wes": wes, "bo": bo, "invoice": invoice,
            "open_note": open_note, "locked": locked, "session": session}


# ------------------------------------------------------------------ the door

def test_no_token_is_a_401_naming_the_resource_metadata():
    response = raw("POST", "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                   headers={"Accept": "application/json, text/event-stream"})
    assert response.status_code == 401
    assert "resource_metadata=" in response.headers.get("www-authenticate", "")
    meta = raw("GET", "/.well-known/oauth-protected-resource/mcp").json()
    assert meta["resource"] == settings.MCP_RESOURCE_URL
    assert meta["authorization_servers"] == [settings.OAUTH_ISSUER_URL] or \
        [s.rstrip("/") for s in meta["authorization_servers"]] == [settings.OAUTH_ISSUER_URL]


def test_a_made_up_token_is_refused(seeded_tenant):
    response = raw("POST", "/mcp", token="not-a-token",
                   json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                   headers={"Accept": "application/json, text/event-stream"})
    assert response.status_code == 401


def test_the_tools_and_the_three_prompts_are_listed(world, ff):
    token = connect(ff)["access_token"]

    async def work(client):
        tools = await client.list_tools()
        prompts = await client.list_prompts()
        return [t.name for t in tools.tools], [p.name for p in prompts.prompts]

    tools, prompts = _with_client(token, work)
    for name in ("practice_summary", "company_overview", "search_contacts", "get_contact",
                 "list_pipelines", "list_tasks", "list_goals", "list_notes",
                 "scorecard_readings", "pending_meeting_proposals", "sending_queue",
                 "digest_drafts", "invoices_summary", "documents", "strategy_session",
                 "create_task", "add_note", "draft_email", "propose_map_rows",
                 "enter_kpi_reading", "create_digest_draft"):
        assert name in tools
    # Nothing that sends, deletes, approves, charges, signs or moves a stage.
    for never in ("send_", "delete", "approve", "charge", "sign_", "move_", "update_",
                  "set_", "revoke", "pay"):
        assert not any(name.startswith(never) for name in tools), never
    assert sorted(prompts) == ["prep_contact", "weekly_note", "whats_late"]


# ------------------------------------------------------- role scoping, x3

def test_invoices_are_the_owners_and_associates_never_an_assistants(world, ff, va):
    error, data = call(connect(ff)["access_token"], "invoices_summary")
    assert not error and [i["id"] for i in data["invoices"]] == [str(world["invoice"].pk)]
    error, data = call(connect(va)["access_token"], "invoices_summary")
    assert error and "owner and associates" in str(data)


def test_an_associate_sees_only_assigned_companies(world, ff, cf):
    error, data = call(connect(ff)["access_token"], "list_companies")
    assert {c["name"] for c in data["companies"]} >= {"Alder Fasteners", "Birch Logistics"}
    token = connect(cf)["access_token"]
    error, data = call(token, "list_companies")
    names = {c["name"] for c in data["companies"]}
    assert "Alder Fasteners" in names and "Birch Logistics" not in names
    error, data = call(token, "company_overview", company_id=str(world["other"].pk))
    assert error and "No company with that id" in str(data)


def test_pin_locked_notes_never_leave(world, ff):
    error, data = call(connect(ff)["access_token"], "list_notes",
                       contact_id=str(world["wes"].pk))
    assert not error
    bodies = json.dumps(data)
    assert "scrap report" in bodies and "salary" not in bodies
    assert str(world["locked"].pk) not in bodies


# --------------------------------------------------------------- the writes

def test_each_write_lands_in_its_queue_marked_as_an_ai_apps(world, ff, dev_outbox):
    from apps.crm.models import OutboxMessage
    from apps.notes.models import Note
    from apps.strategy.models import StrategyMapRow
    from apps.work.models import Digest, Task, TaskUpdate

    token = connect(ff)["access_token"]
    wes, mine = world["wes"], world["mine"]

    error, made = call(token, "create_task", title="Send the scrap tags",
                       company_id=str(mine.pk), due_date="2026-11-20")
    assert not error, made
    task = Task.all_objects.get(pk=made["id"])
    assert task.is_client_visible is False
    assert TaskUpdate.all_objects.filter(task=task, source=TaskUpdate.Source.AI_APP).exists()

    error, made = call(token, "add_note", body="Call notes from Claude.",
                       contact_id=str(wes.pk))
    assert not error, made
    assert Note.all_objects.get(pk=made["id"]).source == Note.Source.AI_APP

    error, made = call(token, "draft_email", contact_id=str(wes.pk), subject="This week",
                       body="Hi Wes,\n\nThe scrap tags are next.")
    assert not error, made
    message = OutboxMessage.all_objects.get(pk=made["id"])
    assert message.state == OutboxMessage.State.PENDING_APPROVAL
    assert message.source_type == "ai_app" and message.sent_at is None
    assert dev_outbox == []

    error, made = call(token, "propose_map_rows", session_id=str(world["session"].pk),
                       rows=[{"bottleneck": "Scrap is counted by hand", "horizon": 30,
                              "the_fix": "Tag at the press", "owner": "Mason"}])
    assert not error, made
    row = StrategyMapRow.all_objects.get(pk=made["ids"][0])
    assert row.state == StrategyMapRow.State.PROPOSED and row.from_ai_app is True

    error, made = call(token, "create_digest_draft", contact_id=str(wes.pk),
                       body="This week the scrap tags went live at two presses.")
    assert not error, made
    digest = Digest.all_objects.get(pk=made["id"])
    assert digest.state == Digest.State.PENDING and digest.from_ai_app is True
    assert digest.approved_at is None and dev_outbox == []


def test_a_kpi_reading_is_entered_by_ai(world, ff):
    from apps.scorecard import setup
    from apps.scorecard.models import KpiReading
    from .test_scorecard import last_week

    with tenant_context(ff.tenant_id):
        card = setup.ensure(world["mine"], ff.user)
        kpi = setup.create_kpi(card, {"name": "Scrap tags", "kind": "count",
                                      "cadence": "weekly", "rollup": "sum",
                                      "target_value": 10, "page": str(card.pages.get().pk),
                                      "reading_owner": str(ff.user_id)}, ff.user)
    week = last_week()
    error, made = call(connect(ff)["access_token"], "enter_kpi_reading",
                       company_id=str(world["mine"].pk), kpi_id=str(kpi.pk),
                       period_start=week.isoformat(), value="7")
    assert not error, made
    reading = KpiReading.all_objects.get(kpi=kpi)
    assert reading.source == KpiReading.Source.AI and reading.value == 7


def test_an_assistant_cannot_propose_rows_or_draft_digests(world, va):
    token = connect(va)["access_token"]
    error, data = call(token, "propose_map_rows", session_id=str(world["session"].pk),
                       rows=[{"bottleneck": "x"}])
    assert error
    error, data = call(token, "create_digest_draft", contact_id=str(world["wes"].pk),
                       body="x")
    assert error


# -------------------------------------------------------------- revocation

def test_revoking_ends_access(world, ff, api):
    token = connect(ff)["access_token"]
    error, _ = call(token, "list_companies")
    assert not error
    connection = api.as_(ff).get("/api/ai/connections/").json()[0]
    assert connection["last_used_at"]
    api.as_(ff).post(f"/api/ai/connections/{connection['id']}/revoke")
    response = raw("POST", "/mcp", token=token,
                   json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                   headers={"Accept": "application/json, text/event-stream"})
    assert response.status_code == 401


# ----------------------------------------------------------------- Activity

def test_every_call_is_an_activity_line_with_ids_never_content(world, ff, api):
    token = connect(ff)["access_token"]
    call(token, "get_contact", contact_id=str(world["wes"].pk))
    call(token, "add_note", body="Secret words never in Activity.",
         contact_id=str(world["wes"].pk))
    lines = list(AuditEvent.all_objects.filter(verb="ai_app.tool").order_by("created_at"))
    assert [a.payload["tool"] for a in lines] == ["get_contact", "add_note"]
    assert f"contact:{world['wes'].pk}" in lines[0].payload["ids"]
    assert "Secret words" not in json.dumps([a.payload for a in lines])
    feed = api.as_(ff).get("/api/activity/").json()
    texts = [e["text"] for e in (feed["entries"] if isinstance(feed, dict) else feed)]
    assert any("used get_contact through Claude on Wes Calder" in t for t in texts), texts
    assert any("used add_note through Claude" in t for t in texts)
