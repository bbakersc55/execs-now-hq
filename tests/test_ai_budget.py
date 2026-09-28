"""AI credits, the monthly budget, and the estimate (owner, 2026-09-28).

Anthropic does not report the account balance, so the FF enters the credits on
the account when they top up; the app subtracts logged spend since that day and
**says it is an estimate**. A monthly budget warns at 80%, and a balance below
what the running import still needs warns too. AI spend is the FF's (FR-0.9).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.meetings.models import DriveBackfill
from apps.tenancy.models import AiCall, AuditEvent

from . import registry_config  # noqa: F401
from .factories import AiCallFactory, DriveBackfillFactory


def spend(tenant, usd, *, days_ago=0):
    call = AiCallFactory(tenant=tenant, cost_usd=Decimal(usd))
    AiCall.all_objects.filter(pk=call.pk).update(
        created_at=timezone.now() - timedelta(days=days_ago))
    return call


def today(tenant):
    return timezone.localdate(timezone=ZoneInfo(tenant.timezone))


@pytest.mark.django_db
def test_nothing_entered_means_no_estimate_and_the_console_link(seeded_tenant, ff, api):
    body = api.as_(ff).get("/api/ai-budget/").json()
    assert body["console_url"] == "https://console.anthropic.com/"
    assert body["estimated_balance"] is None and body["warnings"] == []


@pytest.mark.django_db
def test_the_estimate_is_credits_less_spend_since_the_top_up_day(
    seeded_tenant, ff, api, in_tenant_a
):
    topped_up = today(seeded_tenant) - timedelta(days=3)
    spend(seeded_tenant, "4.00", days_ago=10)            # before the top-up: not counted
    spend(seeded_tenant, "1.25", days_ago=2)
    spend(seeded_tenant, "0.50")

    body = api.as_(ff).post("/api/ai-budget/", {
        "credits_usd": "50", "credits_as_of": topped_up.isoformat()}).json()

    assert body["credits_usd"] == "50.00"
    assert body["spent_since_credits"] == "1.75"
    assert body["estimated_balance"] == "48.25"
    assert AuditEvent.all_objects.filter(verb="ai.budget_changed").exists()


@pytest.mark.django_db
@pytest.mark.parametrize("sent", [
    {"credits_usd": "-5", "credits_as_of": "2026-09-01"},
    {"credits_usd": "50"},                                  # no date
    {"credits_usd": "fifty", "credits_as_of": "2026-09-01"},
    {"monthly_budget_usd": "lots"},
])
def test_nonsense_is_refused(seeded_tenant, ff, api, sent):
    assert api.as_(ff).post("/api/ai-budget/", sent).status_code == 400


@pytest.mark.django_db
def test_a_top_up_date_in_the_future_is_refused(seeded_tenant, ff, api):
    future = (date.today() + timedelta(days=5)).isoformat()
    assert api.as_(ff).post("/api/ai-budget/", {
        "credits_usd": "50", "credits_as_of": future}).status_code == 400


@pytest.mark.django_db
def test_the_budget_warns_at_eighty_percent_of_this_months_spend(
    seeded_tenant, ff, api, in_tenant_a
):
    client = api.as_(ff)
    client.post("/api/ai-budget/", {"monthly_budget_usd": "10"})
    spend(seeded_tenant, "7.90")
    assert client.get("/api/ai-budget/").json()["warnings"] == []

    spend(seeded_tenant, "0.20")                          # 8.10 of 10
    [warning] = client.get("/api/ai-budget/").json()["warnings"]
    assert warning["kind"] == "budget" and "81%" in warning["message"]


@pytest.mark.django_db
def test_last_months_spend_does_not_count_against_this_months_budget(
    seeded_tenant, ff, api, in_tenant_a
):
    first = today(seeded_tenant).replace(day=1)
    spend(seeded_tenant, "9.00", days_ago=(today(seeded_tenant) - first).days + 2)
    api.as_(ff).post("/api/ai-budget/", {"monthly_budget_usd": "10"})
    assert api.as_(ff).get("/api/ai-budget/").json()["warnings"] == []


@pytest.mark.django_db
def test_a_balance_below_the_running_imports_cost_warns(seeded_tenant, ff, api,
                                                        in_tenant_a):
    DriveBackfillFactory(tenant=seeded_tenant, state=DriveBackfill.State.RUNNING,
                         planned=100, done=10)
    body = api.as_(ff).post("/api/ai-budget/", {
        "credits_usd": "1", "credits_as_of": today(seeded_tenant).isoformat()}).json()

    assert body["next_import"]["remaining"] == 90
    [warning] = body["warnings"]
    assert warning["kind"] == "balance" and "90 notes" in warning["message"]


@pytest.mark.django_db
def test_clearing_the_budget(seeded_tenant, ff, api):
    api.as_(ff).post("/api/ai-budget/", {"monthly_budget_usd": "10"})
    body = api.as_(ff).post("/api/ai-budget/", {"monthly_budget_usd": ""},
                            format="json").json()
    assert body["monthly_budget_usd"] is None


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["cf", "va"])
def test_ai_money_is_the_founders(seeded_tenant, api, role, request):
    member = request.getfixturevalue(role)
    assert api.as_(member).get("/api/ai-budget/").status_code == 403
    assert api.as_(member).post("/api/ai-budget/",
                                {"monthly_budget_usd": "1"}).status_code == 403


@pytest.mark.django_db
def test_the_dashboard_finances_slot_carries_it_for_the_founder_only(
    seeded_tenant, ff, cf, api, in_tenant_a
):
    api.as_(ff).post("/api/ai-budget/", {"monthly_budget_usd": "1"})
    spend(seeded_tenant, "0.95")

    mine = api.as_(ff).get("/api/dashboard/").json()["ai"]
    assert mine["warnings"][0]["kind"] == "budget"
    assert api.as_(cf).get("/api/dashboard/").json()["ai"] is None
