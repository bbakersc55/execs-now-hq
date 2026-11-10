"""Settings → AI, "Actions", and the tier table (P7, docs/p7_mcp.md); and
every MCP read tool run once for each staff role, straight through
`tools.py`, so a tool that breaks on real records is caught here."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.aiconnect import tools as T
from apps.aiconnect.models import ModelTier
from apps.tenancy import ai_actions
from apps.tenancy.context import tenant_context

from .factories import (
    AiAppConnectionFactory, ClientCompanyFactory, ContactFactory, StrategySessionFactory,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def tiers():
    """The rows the migration seeds. A transactional test elsewhere in a
    worker flushes the table, so these tests put them back themselves."""
    for code, (model, per_in, per_out, fallback) in ai_actions.FALLBACK_MODELS.items():
        ModelTier.objects.update_or_create(code=code, defaults={
            "model": model, "input_usd_per_mtok": per_in, "output_usd_per_mtok": per_out,
            "server_fallback": fallback})


def test_the_platform_table_holds_the_three_tiers():
    rows = {r.code: r for r in ModelTier.objects.all()}
    assert rows["fast"].model == "claude-haiku-5-5" and rows["fast"].server_fallback is False
    assert rows["standard"].model == "claude-sonnet-5-5"
    assert rows["deep"].model == "claude-opus-5-5"


def test_the_defaults_named_in_the_brief():
    by = ai_actions.BY_KEY
    assert by["personal_sort_lines"].tier == "fast"
    assert by["meeting_owner_classify"].tier == "fast"
    for key in ("digest_prose", "scorecard_explain", "scorecard_weekly_note", "session_prep",
                "referral_touch"):
        assert by[key].tier == "standard", key
    for key in ("strategy_rows", "strategy_diagnostic_questions", "finance_review_forecast",
                "finance_read_statement"):
        assert by[key].tier == "deep", key
    # Scheduled and rule-fired ones are fixed in the app.
    assert by["digest_prose"].fixed and by["meeting_owner_classify"].fixed
    # Every purpose the app calls Claude with belongs to an action.
    assert len(ai_actions.BY_PURPOSE) == sum(len(a.purposes) for a in ai_actions.ACTIONS)


def test_the_owner_changes_tier_and_runs_in_and_the_call_follows(seeded_tenant, ff, api):
    table = api.as_(ff).get("/api/ai/actions/").json()
    assert table["may_change"] is True
    row = next(a for a in table["actions"] if a["key"] == "scorecard_explain")
    assert (row["runs_in"], row["tier"]) == ("app", "standard")
    response = api.as_(ff).patch("/api/ai/actions/", {"action": "scorecard_explain",
                                                      "tier": "deep", "runs_in": "ai_app"},
                                 content_type="application/json")
    assert response.status_code == 200 and response.json()["tier"] == "deep"
    assert ai_actions.model_for(seeded_tenant.pk, "scorecard_explain").model == "claude-opus-5-5"
    # Another practice keeps the default.
    assert ai_actions.model_for(None, "scorecard_explain").model == "claude-sonnet-5-5"


def test_a_fixed_action_cannot_move_and_only_the_owner_changes(seeded_tenant, ff, cf, api):
    refused = api.as_(ff).patch("/api/ai/actions/", {"action": "digest_prose",
                                                     "runs_in": "ai_app"},
                                content_type="application/json")
    assert refused.status_code == 400
    assert api.as_(cf).get("/api/ai/actions/").json()["may_change"] is False
    assert api.as_(cf).patch("/api/ai/actions/", {"action": "scorecard_explain",
                                                  "tier": "fast"},
                             content_type="application/json").status_code == 403


def test_tenant_isolation_one_practices_choice_is_its_own(seeded_tenant, ff, tenant_b, api):
    from .factories import MembershipFactory

    api.as_(ff).patch("/api/ai/actions/", {"action": "goal_narrative", "tier": "fast"},
                      content_type="application/json")
    owner_b = MembershipFactory(tenant=tenant_b, role="FF")
    theirs = api.as_(owner_b).get("/api/ai/actions/").json()["actions"]
    assert next(a for a in theirs if a["key"] == "goal_narrative")["tier"] == "standard"


def test_a_call_runs_on_its_tier_with_fallback_only_where_there_is_one(seeded_tenant,
                                                                        monkeypatch):
    from apps.tenancy import claude

    sent = {}

    class Messages:
        def create(self, **kw):
            sent.update(kw)
            return SimpleNamespace(
                model=kw["model"], stop_reason="end_turn",
                usage=SimpleNamespace(input_tokens=1000, output_tokens=100,
                                      server_tool_use=None),
                content=[SimpleNamespace(type="text", text="ok")])

    fake = SimpleNamespace(beta=SimpleNamespace(messages=Messages()))
    monkeypatch.setattr(claude, "_client", lambda key: fake)
    monkeypatch.setattr(claude, "_resolve_key", lambda tenant: "k")
    with tenant_context(seeded_tenant.pk):
        text, call = claude.complete_with_call(tenant=seeded_tenant,
                                               purpose="personal_sort_lines",
                                               system="s", user_text="u", trigger="button")
    assert text == "ok" and sent["model"] == "claude-haiku-5-5"
    assert "fallbacks" not in sent and "betas" not in sent
    assert call.cost_usd == Decimal("0.00015")       # 1000 x 0.10 + 100 x 0.50, per million
    with tenant_context(seeded_tenant.pk):
        claude.complete_with_call(tenant=seeded_tenant, purpose="strategy_rows", system="s",
                                  user_text="u", trigger="button")
    assert sent["model"] == "claude-opus-5-5" and sent["fallbacks"] == "default"


def test_the_platform_owner_edits_a_tier_without_a_code_change(seeded_tenant):
    ModelTier.objects.filter(code="standard").update(model="claude-sonnet-6",
                                                     input_usd_per_mtok=Decimal("3"))
    resolved = ai_actions.model_for(seeded_tenant.pk, "scorecard_explain")
    assert resolved.model == "claude-sonnet-6" and resolved.input_usd_per_mtok == Decimal("3")


# ---------------------------------------------- every read tool, every role

@pytest.mark.parametrize("role", ["FF", "CF", "VA"])
def test_every_read_tool_runs_for_each_staff_role(seeded_tenant, ff, role):
    from .factories import MembershipFactory

    member = ff if role == "FF" else MembershipFactory(tenant=seeded_tenant, role=role)
    with tenant_context(seeded_tenant.pk):
        company = ClientCompanyFactory(tenant=seeded_tenant)
        contact = ContactFactory(tenant=seeded_tenant, first_name="Wes", last_name="Calder",
                                 company=company)
        session = StrategySessionFactory(tenant=seeded_tenant, contact=contact,
                                         company=company, owner=ff.user)
    connection = AiAppConnectionFactory(tenant=seeded_tenant, membership=member)
    p = T.Principal(connection)
    with tenant_context(seeded_tenant.pk):
        calls = [
            (T.practice_summary, {}), (T.list_companies, {}), (T.search_contacts,
                                                               {"query": "Wes"}),
            (T.list_pipelines, {}), (T.list_tasks, {"status": "open"}),
            (T.list_tasks, {"overdue": True}), (T.list_goals, {}), (T.list_notes, {}),
            (T.pending_meeting_proposals, {}), (T.sending_queue, {}), (T.digest_drafts, {}),
            (T.documents, {}), (T.list_strategy_sessions, {}),
        ]
        if role == "FF":
            calls += [(T.company_overview, {"company_id": str(company.pk)}),
                      (T.get_contact, {"contact_id": str(contact.pk)}),
                      (T.scorecard_readings, {"company_id": str(company.pk)}),
                      (T.strategy_session, {"session_id": str(session.pk)}),
                      (T.invoices_summary, {})]
        for fn, kwargs in calls:
            try:
                assert isinstance(fn(p, **kwargs), dict), fn.__name__
            except T.ToolRefused:
                pass                        # a refusal in words is an answer too
