"""Owner agreements never reach an AI app or an AI feature (owner, 2026-11-24).

A fully signed agreement and a submitted intake, for an owner with a name,
email and address found nowhere else. Then every MCP tool the server lists is
called for that company and practice (and every prompt), and every in-app AI
feature that takes company data is run against the fake Claude. None of the
owner's words, the agreement's title, or either of the owner's links may
appear in anything a tool returns or anything sent to Claude. A static check
covers every module that calls Claude: none of them reads agreements, intakes,
or the owner emails' log."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

import pytest
from django.test import Client
from django.utils import timezone

from apps.agreements import links
from apps.intake import links as intake_links
from apps.tenancy.context import tenant_context

from .ai_app_flow import connect
from .factories import (
    ContactEmailFactory, ContactFactory, GoalFactory, KpiFactory, NoteFactory, ScorecardFactory,
    ScorecardPageFactory, SopFactory, StrategySessionFactory, TaskFactory, ToolRunFactory,
)
from .test_agreements import as_, aw, countersign, create, fake, world  # noqa: F401
from .test_ai_apps_mcp import _with_client, call

pytestmark = pytest.mark.django_db(transaction=True)
APPS = Path(__file__).resolve().parent.parent / "apps"

OWNER = {"owner_type": "person", "first_name": "Zebulon", "last_name": "Quarterfield",
         "phone": "435-555-0177", "email": "zebulon.q@quarterfield-example.net",
         "mailing": {"street": "12 Obscurely Lane", "city": "Denver", "state": "CO",
                     "zip": "80202"},
         "bedrooms": "2", "bathrooms": "1", "square_feet": "900",
         "emergency": {"name": "Ophelia Quarterfield", "phone": "435-555-0178"}}
PROPERTY = {"street": "77 Unlikelyname Way", "unit": "", "city": "Park City", "state": "UT",
            "zip": "84060"}
NEVER = ("Zebulon", "Quarterfield", "quarterfield-example", "Unlikelyname", "Obscurely",
         "Ophelia", "Rental Management Agreement", "435-555-017")


@pytest.fixture
def signed(aw):
    """The agreement signed by both sides, and its intake submitted."""
    from .test_agreements import TERMS

    a = create(aw, terms={**TERMS, "property_address": PROPERTY}, name="Zebulon Quarterfield",
               email="zebulon.q@quarterfield-example.net")
    with tenant_context(a.tenant_id):
        t = links.ensure(a)
    o = Client()
    o.patch(f"/api/fa/{t}/details", json.dumps({"details": OWNER}),
            content_type="application/json")
    r = o.post(f"/api/fa/{t}/sign", json.dumps({"method": "typed", "typed": "Zebulon",
                                                "agreed": True}),
               content_type="application/json")
    assert r.status_code == 200, r.content
    assert countersign(aw, a, "michael", method="typed", typed="Michael").status_code == 200
    a.refresh_from_db()
    intake_token = intake_links.token_of(a.submission)
    r = Client().post(f"/api/f/{intake_token}/submit")
    assert r.status_code == 200, r.content
    return {**aw, "agreement": a, "tokens": (t, intake_token)}


def _clean(w, text: str, where: str):
    for word in NEVER + w["tokens"]:
        assert word not in text, f"{word!r} reached {where}"


def test_no_mcp_tool_or_prompt_ever_shows_the_owner_or_the_agreement(signed):
    w = signed
    t, co = w["practice"], w["company"]
    with tenant_context(t.pk):
        pat = ContactFactory(tenant=t, company=co, first_name="Pat", last_name="Regular")
        ContactEmailFactory(tenant=t, contact=pat, address="pat@regular.example")
        GoalFactory(tenant=t, client_company=co, title="Grow bookings")
        TaskFactory(tenant=t, client_company=co, title="Call the HOA")
        NoteFactory(tenant=t, body="General note.", company=co, created_by=w["ff"].user)
        session = StrategySessionFactory(tenant=t, contact=pat, company=co, owner=w["ff"].user)
        page = ScorecardPageFactory(tenant=t, scorecard=ScorecardFactory(tenant=t, company=co))
        kpi = KpiFactory(tenant=t, page=page)
        run = ToolRunFactory(tenant=t, company=co)
        sop = SopFactory(tenant=t, company=co)
    token = connect(w["ff"])["access_token"]

    async def listing(client):
        tools = await client.list_tools()
        prompts = await client.list_prompts()
        return [x.name for x in tools.tools], [p.name for p in prompts.prompts]

    tools, prompts = _with_client(token, listing)
    c, monday = str(co.pk), date.today() - timedelta(days=date.today().weekday())
    args = {
        "practice_summary": {}, "list_companies": {}, "company_overview": {"company_id": c},
        "search_contacts": {"query": "Quarterfield"}, "get_contact": {"contact_id": str(pat.pk)},
        "list_pipelines": {}, "list_tasks": {"company_id": c}, "list_goals": {"company_id": c},
        "list_notes": {"company_id": c}, "scorecard_readings": {"company_id": c},
        "pending_meeting_proposals": {}, "sending_queue": {}, "digest_drafts": {},
        "invoices_summary": {"company_id": c}, "documents": {"company_id": c},
        "list_strategy_sessions": {}, "strategy_session": {"session_id": str(session.pk)},
        "company_plan": {"company_id": c}, "list_tool_runs": {"company_id": c},
        "get_tool_run": {"run_id": str(run.pk)}, "list_sops": {"company_id": c},
        "read_sop": {"sop_id": str(sop.pk)},
        "create_task": {"title": "Sweep task", "company_id": c},
        "add_note": {"body": "Sweep note", "company_id": c},
        "draft_email": {"contact_id": str(pat.pk), "subject": "Hello", "body": "Hello"},
        "propose_map_rows": {"session_id": str(session.pk), "rows": []},
        "enter_kpi_reading": {"company_id": c, "kpi_id": str(kpi.pk),
                              "period_start": monday.isoformat(), "value": "3"},
        "create_digest_draft": {"contact_id": str(pat.pk), "body": "This week."},
        "propose_plan_items": {"company_id": c, "horizon": "week", "items": []},
        "draft_sop": {"company_id": c, "title": "Sweep SOP"},
    }
    assert set(tools) == set(args), f"a tool the sweep doesn't call: {set(tools) ^ set(args)}"
    seen = []
    for name in tools:
        error, data = call(token, name, **args[name])
        text = json.dumps(data, default=str)
        _clean(w, text, f"MCP tool {name}")
        seen.append(name)
    for query in ("Zebulon", "zebulon.q@quarterfield-example.net", "Unlikelyname"):
        error, data = call(token, "search_contacts", query=query)
        assert not error and data["contacts"] == [], query

    prompt_args = {"weekly_note": {"company": co.name}, "prep_contact": {"contact": "Pat"},
                   "whats_late": {}, "sop_from_note": {"note": "General note."},
                   "map_rows_from_meeting": {"proposal": "x"},
                   "weekly_note_from_scorecard": {"company": co.name}}
    assert set(prompts) == set(prompt_args)

    async def prompting(client):
        return [await client.get_prompt(name, prompt_args[name]) for name in prompts]

    for result in _with_client(token, prompting):
        _clean(w, json.dumps([getattr(m.content, "text", "") for m in result.messages]),
               "an MCP prompt")
    assert len(seen) == len(tools)


def test_no_ai_feature_that_takes_company_data_is_sent_the_owner_or_the_agreement(
        signed, fake_claude):
    from apps.centers.models import PracticeCenter
    from apps.crm.services import referral
    from apps.notes import summary
    from apps.strategy import ai as strategy_ai
    from apps.strategy import diagnostic, document, prep
    from apps.strategy import services as strategy
    from apps.tools import builder
    from apps.work import digests, narratives

    from .test_strategy_v3_session import build, precall, rate

    w = signed
    t, co = w["practice"], w["company"]
    PracticeCenter.all_objects.create(tenant=t, center="operations", enabled_at=timezone.now())
    with tenant_context(t.pk):
        pat = ContactFactory(tenant=t, company=co, first_name="Pat", last_name="Regular")
        ContactEmailFactory(tenant=t, contact=pat, address="pat@regular.example")
        goal = GoalFactory(tenant=t, client_company=co, title="Grow bookings")
        TaskFactory(tenant=t, client_company=co, title="Call the HOA")
        pat.referral_touch_mode = "claude"
        pat.save()
        note = NoteFactory(tenant=t, body="The HOA call.", company=co, created_by=w["ff"].user,
                           transcript="The HOA call went well; the board meets in May.")
        # A v3 session for the company's contact, with its pre-call answers
        # and ratings: what the diagnostic and the map rows are drafted from.
        session = strategy.start(tenant=t, contact=pat, template=build(t), owner=w["ff"].user)
        precall(session)
        rate(session)
        page = ScorecardPageFactory(tenant=t, scorecard=ScorecardFactory(tenant=t, company=co))
        KpiFactory(tenant=t, page=page)
    ff = as_(w["ff"])
    ran = {}

    def run(name, fn):
        before = len(fake_claude.requests)
        try:
            with tenant_context(t.pk):
                fn()
        except Exception:                      # noqa: BLE001 (a fake reply it can't use)
            pass
        ran[name] = len(fake_claude.requests) - before

    def post(url, body):
        return lambda: ff.post(url, json.dumps(body), content_type="application/json")

    def brainstorm():
        storm = ff.post("/api/sops/brainstorms/", json.dumps({"company": str(co.pk),
                                                             "title": "Check-in"}),
                        content_type="application/json")
        ff.post(f"/api/sops/brainstorms/{storm.json()['id']}/send/",
                json.dumps({"text": "What should the check-in SOP cover?"}),
                content_type="application/json")

    run("goal narrative", lambda: narratives.draft(goal))
    run("strategy map rows", lambda: strategy_ai.draft_map_rows(session))
    run("strategy diagnostic", lambda: diagnostic.propose(session))
    run("strategy prep", lambda: prep.prepare(session, notes="Short-term rentals."))
    run("strategy document", lambda: document.draft(session))
    run("referral touch", lambda: referral.compose_touch(pat))
    run("note summary", lambda: summary.draft(note))
    run("digest narrative", lambda: digests.narrative_for(
        t, digests.owed_to(pat.pk, tenant=t, cadence="weekly"), contact=pat))
    run("tool builder", lambda: builder.propose(t, "A check-in tracker for this company."))
    run("scorecard", post("/api/scorecard/ai/", {"company": str(co.pk), "purpose": "explain"}))
    run("plan draft", post(f"/api/plans/{co.pk}/draft/", {
        "horizon": "week", "pasted": "This week: the HOA call."}))
    run("SOP brainstorm", brainstorm)
    assert all(ran.values()), f"a feature that never asked Claude: {ran}"
    _clean(w, json.dumps(fake_claude.requests, default=str), "a request to Claude")


def test_no_module_that_calls_claude_reads_agreements_intakes_or_owner_emails():
    callers = [p for p in APPS.rglob("*.py") if "migrations" not in p.parts
               and re.search(r"complete_with_call\(|claude\.complete\(", p.read_text())]
    assert len(callers) > 10
    for path in callers:
        if path.parent.name == "tenancy" and path.name == "claude.py":
            continue
        text = path.read_text()
        for word in ("apps.agreements", "apps.intake", "OwnerAgreement", "OwnerEmail",
                     "AgreementSignature", "Submission"):
            assert word not in text, f"{path.relative_to(APPS.parent)} mentions {word}"
    tools = (APPS / "aiconnect" / "tools.py").read_text() + \
        (APPS / "aiconnect" / "mcp_server.py").read_text()
    for word in ("agreements", "intake", "OwnerEmail", "notify"):
        assert word not in tools, word
