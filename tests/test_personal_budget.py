"""P6 M4 stop 2: the budget that builds itself (decisions 9–14, the brief's
Cash flow table, and "Explain this budget").

1. History proposes the budget: the median of six months, three if that is
   all, to the nearest $10; nothing is set until it is used.
2. Envelopes: Planned, Spent, Left; everyday resets, saving-up rolls, each
   with its switch; an overspend asks, and nothing moves by itself.
3. Unassigned, above and below zero.
4. The guided questions: the app's own, skippable, never twice; again on a
   25% drift for two months.
5. Goals: the monthly amount, a rolling envelope, a planned line; an
   emergency fund in months; a yearly bill spread.
6. The Cash flow table.
7. Explain this budget: priced first, what is sent, the shared cap.
8. Isolation and role boundaries for every new route.
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.personal import budget, questions, services
from apps.personal.models import (
    PersonalAccount, PersonalCategory, PersonalEnvelope, PersonalEnvelopeMove, PersonalGoal,
    PersonalLine, PersonalPlanned, PersonalQuestion,
)

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import ClientCompanyFactory
from .test_client_invoicing import get, patch, post
from .test_personal_sides import switched_on

THIS = budget.this_month()


def ago(n: int) -> date:
    return budget.add_months(THIS, -n)


@pytest.fixture
def ledger(seeded_tenant, ff):
    switched_on(seeded_tenant)
    return services.ledger_for(ff.user)


@pytest.fixture
def chart(ledger):
    return {c.name: c for c in PersonalCategory.objects.filter(ledger=ledger)}


@pytest.fixture
def joint(ledger):
    return PersonalAccount.objects.create(ledger=ledger, name="Joint checking",
                                          opening_on=ago(7), last4="2210")


def spend(ledger, account, category, month: date, cents: int, day=10, direction="out",
          text="LINE"):
    return PersonalLine.objects.create(ledger=ledger, account=account, category=category,
                                       on_date=month.replace(day=day), amount_cents=cents,
                                       direction=direction, description=text)


@pytest.fixture
def history(ledger, chart, joint):
    """Six months: groceries steady-ish, dining high twice and low once and
    so on, a mortgage the same each month, pay in, a transfer, and one large
    home insurance payment."""
    groceries = [81_200, 79_000, 84_400, 80_100, 83_000, 81_900]
    dining = [34_000, 12_000, 34_500, 33_800, 11_500, 12_200]
    for n, (g, d) in enumerate(zip(groceries, dining), start=1):
        month = ago(7 - n)
        spend(ledger, joint, chart["Groceries"], month, g)
        spend(ledger, joint, chart["Dining"], month, d)
        spend(ledger, joint, chart["Rent or mortgage"], month, 284_000, day=1)
        spend(ledger, joint, chart["Spouse pay"], month, 490_000, direction="in")
        spend(ledger, joint, chart["Pay from the practice"], month, 600_000, day=2,
              direction="in")
        spend(ledger, joint, chart["Transfers"], month, 80_000, day=5)
    # A month with nothing in Car maintenance but this one: no envelope.
    spend(ledger, joint, chart["Car maintenance"], ago(2), 9_000)
    spend(ledger, joint, chart["Home insurance"], ago(4), 138_000, day=14,
          text="ALLSTATE HOME POLICY")
    return {"groceries": groceries, "dining": dining}


def envelope_of(ledger, name):
    return next(e for e in budget.envelopes(ledger)
                if e.category_id and e.category.name == name)


# ============================================================ 1. the proposal

@pytest.mark.django_db
def test_history_proposes_the_median_to_the_nearest_ten_and_sets_nothing(ledger, history):
    found = budget.proposal(ledger)
    assert found["ready"] and len(found["months"]) == 6
    by = {row["category"].name: row for row in found["envelopes"]}
    # Groceries: the median of six, to the nearest $10.
    assert by["Groceries"]["proposed_cents"] == budget.to_ten(81_550) == 82_000
    assert by["Rent or mortgage"]["proposed_cents"] == 284_000
    # Dining: 340, 340, 338, 120, 115, 122 -> the median, 229.00, to $230.
    assert by["Dining"]["proposed_cents"] == 23_000
    # Income the same way; transfers never.
    assert by["Spouse pay"]["kind"] == "income" and by["Spouse pay"]["proposed_cents"] == 490_000
    assert "Transfers" not in by
    # A month with nothing counts as nothing: one $90 in six months is no envelope.
    assert "Car maintenance" not in by
    assert not budget.has_budget(ledger)


@pytest.mark.django_db
def test_three_months_are_enough_and_two_are_not(ledger, chart, joint):
    for n in (1, 2):
        spend(ledger, joint, chart["Groceries"], ago(n), 50_000 + n * 1_000)
    assert budget.proposal(ledger)["ready"] is False
    spend(ledger, joint, chart["Groceries"], ago(3), 70_000)
    found = budget.proposal(ledger)
    assert found["ready"] and len(found["months"]) == 3
    assert found["envelopes"][0]["proposed_cents"] == 52_000          # 500, 510, 700 -> 510


@pytest.mark.django_db
def test_using_the_proposal_makes_the_envelopes_and_asks_the_questions(
        ledger, history, ff, api):
    shown = get(api, ff, "/api/personal/budget").json()
    assert shown["has_budget"] is False and shown["proposal"]["ready"]
    assert any(row["category"]["name"] == "Groceries"
               for row in shown["proposal"]["envelopes"])
    used = post(api, ff, "/api/personal/budget/accept", {})
    assert used.status_code == 200 and used.json()["questions_waiting"] >= 3
    groceries = envelope_of(ledger, "Groceries")
    assert (groceries.kind, groceries.rolls, groceries.planned_cents, groceries.source) == (
        "everyday", False, 82_000, "history")
    assert post(api, ff, "/api/personal/budget/accept", {}).status_code == 409


# ======================================================= 2. envelopes, a month

@pytest.fixture
def accepted(ledger, history):
    budget.accept(ledger)
    return ledger


@pytest.mark.django_db
def test_planned_spent_and_left_and_everyday_resets_while_saving_up_rolls(
        accepted, chart, joint):
    ledger = accepted
    groceries = envelope_of(ledger, "Groceries")
    PersonalEnvelope.objects.filter(pk=groceries.pk).update(start_month=ago(1))
    spend(ledger, joint, chart["Groceries"], ago(1), 70_000, day=20)     # 120 left, last month
    spend(ledger, joint, chart["Groceries"], THIS, 30_000, day=1)
    spend(ledger, joint, chart["Groceries"], THIS, 2_000, day=1, direction="in")  # money back
    row = next(r for r in budget.month_view(ledger)["envelopes"] if r["name"] == "Groceries")
    assert (row["planned_cents"], row["spent_cents"], row["carried_cents"]) == (82_000,
                                                                               28_000, 0)
    assert row["left_cents"] == 54_000
    # With the switch on, last month's Left comes along.
    budget.update(groceries, rolls=True)
    row = next(r for r in budget.month_view(ledger)["envelopes"] if r["name"] == "Groceries")
    last_month_spent = history_month_spent = 81_900 + 70_000
    assert row["carried_cents"] == 82_000 - history_month_spent
    assert row["left_cents"] == 82_000 + (82_000 - last_month_spent) - 28_000


@pytest.mark.django_db
def test_an_overspend_asks_and_nothing_moves_until_the_owner_chooses(accepted, chart, joint,
                                                                    ff, api):
    ledger = accepted
    spend(ledger, joint, chart["Dining"], THIS, 30_000, day=3)          # 230 planned
    view = get(api, ff, "/api/personal/budget").json()["month"]
    dining = next(r for r in view["envelopes"] if r["name"] == "Dining")
    groceries = next(r for r in view["envelopes"] if r["name"] == "Groceries")
    assert dining["over"] and dining["left_cents"] == -7_000
    assert not PersonalEnvelopeMove.objects.exists()
    # Taking more than another has left is refused; taking what is short is not.
    too_much = post(api, ff, f"/api/personal/envelopes/{dining['id']}/cover",
                    {"from_envelope": groceries["id"], "amount_cents": 10_000_000})
    assert too_much.status_code == 409
    covered = post(api, ff, f"/api/personal/envelopes/{dining['id']}/cover",
                   {"from_envelope": groceries["id"]}).json()
    dining = next(r for r in covered["envelopes"] if r["name"] == "Dining")
    groceries_after = next(r for r in covered["envelopes"] if r["name"] == "Groceries")
    assert dining["left_cents"] == 0 and not dining["over"]
    assert groceries_after["left_cents"] == groceries["left_cents"] - 7_000
    # Or let it stand: it is still over, and not asked about again this month.
    spend(ledger, joint, chart["Dining"], THIS, 5_000, day=4)
    stood = post(api, ff, f"/api/personal/envelopes/{dining['id']}/cover", {"stand": True})
    dining = next(r for r in stood.json()["envelopes"] if r["name"] == "Dining")
    assert dining["over"] and dining["stood"]


# ============================================================== 3. Unassigned

@pytest.mark.django_db
def test_unassigned_is_income_less_every_envelope_and_can_go_to_a_goal(accepted, ff, api):
    ledger = accepted
    view = budget.month_view(ledger)
    assert view["income_planned_cents"] == 490_000 + 600_000
    assert view["unassigned_cents"] == view["income_planned_cents"] - view["planned_cents"]
    assert view["unassigned_cents"] > 0 and view["over_income"] == []
    goal = budget.save_goal(ledger, name="Vacation", target_cents=300_000)
    before = budget.month_view(ledger)["unassigned_cents"]
    assigned = post(api, ff, "/api/personal/budget/assign",
                    {"goal": str(goal.pk), "amount_cents": 10_000})
    assert assigned.status_code == 200
    assert assigned.json()["unassigned_cents"] == before - 10_000
    assert post(api, ff, "/api/personal/budget/assign",
                {"goal": str(goal.pk), "amount_cents": 100_000_000}).status_code == 409
    # Below zero: which envelopes are over the income.
    budget.update(envelope_of(ledger, "Spouse pay"), planned_cents=0)
    budget.update(envelope_of(ledger, "Pay from the practice"), planned_cents=100_000)
    view = budget.month_view(ledger)
    assert view["unassigned_cents"] < 0
    assert view["over_income"] and view["over_income"][-1]["planned_cents"] <= \
        view["over_income"][0]["planned_cents"]


# ============================================================== 4. questions

@pytest.mark.django_db
def test_the_proposal_asks_the_apps_own_questions_and_each_answer_does_what_it_says(
        accepted, ff, api, claude_never):
    ledger = accepted
    waiting = get(api, ff, "/api/personal/questions").json()
    texts = [q["text"] for q in waiting]
    assert any(t.startswith("Groceries have run $820 a month.") for t in texts)
    normal = next(q for q in waiting if q["kind"] == "normal")
    assert normal["text"] == "Dining was $340 three times and $120 three times. Which is normal?"
    yearly = next(q for q in waiting if q["kind"] == "yearly")
    assert yearly["text"] == ("This looks like a yearly bill: Home insurance, $1,380 in "
                              f"{ago(4):%B}. Spread it monthly?")
    assert waiting[-1]["kind"] == "coming"
    # Which is normal: the low one.
    said = post(api, ff, f"/api/personal/questions/{normal['id']}",
                {"amount_cents": normal["detail"]["choices"][1]}).json()
    assert envelope_of(ledger, "Dining").planned_cents == 12_000 and "Dining" in said["said"]
    # A yearly bill, spread: a rolling envelope at a twelfth, up to $10.
    post(api, ff, f"/api/personal/questions/{yearly['id']}", {"spread": True})
    insurance = envelope_of(ledger, "Home insurance")
    assert (insurance.kind, insurance.rolls, insurance.planned_cents, insurance.yearly_cents) \
        == ("savings", True, 12_000, 138_000)                  # $115, up to $120
    # Skipped is skipped; nothing else changes.
    keep = next(q for q in waiting if q["kind"] == "keep")
    post(api, ff, f"/api/personal/questions/{keep['id']}", {"skip": True})
    assert envelope_of(ledger, "Groceries").planned_cents == 82_000
    # Anything coming: a planned line, and a goal.
    coming = waiting[-1]
    on = (timezone.localdate() + timedelta(days=90)).isoformat()
    made = post(api, ff, f"/api/personal/questions/{coming['id']}",
                {"what": "planned", "name": "New roof", "amount_cents": 900_000,
                 "on_date": on})
    assert made.status_code == 200
    assert PersonalPlanned.objects.get(name="New roof").amount_cents == 900_000
    again = post(api, ff, "/api/personal/questions", {}).json()
    post(api, ff, f"/api/personal/questions/{again[-1]['id']}",
         {"what": "goal", "name": "Kitchen", "amount_cents": 600_000, "on_date": on})
    assert PersonalGoal.objects.get(name="Kitchen").envelope.rolls
    # Nothing is asked twice, and nothing asked Claude.
    questions.after_proposal(ledger, budget.proposal(ledger))
    assert PersonalQuestion.objects.filter(key__startswith="normal:").count() == 1
    assert get(api, ff, "/api/personal/questions").json() == []


@pytest.mark.django_db
def test_a_25_percent_drift_for_two_months_asks_again_once(accepted, chart, joint):
    ledger = accepted
    groceries = envelope_of(ledger, "Groceries")
    PersonalEnvelope.objects.filter(pk=groceries.pk).update(start_month=ago(2))
    PersonalQuestion.objects.all().delete()
    PersonalLine.objects.filter(category=chart["Groceries"],
                                on_date__gte=ago(2)).delete()
    spend(ledger, joint, chart["Groceries"], ago(2), 110_000)
    spend(ledger, joint, chart["Groceries"], ago(1), 82_000)
    assert questions.drift(ledger) == []                   # one month is not two
    spend(ledger, joint, chart["Groceries"], ago(1), 23_000, day=20)
    asked = questions.drift(ledger)
    assert len(asked) == 1 and asked[0].run == "drift"
    assert asked[0].text.startswith("Groceries ran $1,100 and $1,050 the last two months, "
                                    "against $820 planned.")
    assert asked[0].detail["suggested_cents"] == 108_000
    assert questions.drift(ledger) == []                   # asked once


# ======================================================== 5. goals, yearly

@pytest.mark.django_db
def test_a_goal_works_out_its_month_makes_a_rolling_envelope_and_a_planned_line(
        accepted, joint, ff, api):
    on = budget.add_months(THIS, 10).replace(day=15)
    made = post(api, ff, "/api/personal/goals",
                {"name": "Car repairs", "target_cents": 250_000, "target_on": on.isoformat(),
                 "saved_cents": 90_000, "account": str(joint.pk)})
    assert made.status_code == 201, made.json()
    goal = made.json()
    assert goal["monthly_cents"] == budget.round_up_ten(160_000 / 10) == 16_000
    env = PersonalEnvelope.objects.get(pk=goal["envelope"])
    assert (env.kind, env.rolls, env.planned_cents) == ("savings", True, 16_000)
    assert goal["planned"]["on_date"] == on.isoformat()
    assert goal["planned"]["amount_cents"] == 250_000
    assert goal["progress_cents"] == 90_000 + 16_000       # saved, and this month's set aside
    # No date: the owner's amount a month, and no planned line.
    trip = post(api, ff, "/api/personal/goals",
                {"name": "Vacation", "target_cents": 400_000, "monthly_cents": 25_000}).json()
    assert trip["monthly_cents"] == 25_000 and trip["planned"] is None
    # An emergency fund: three months of the everyday envelopes.
    fund = post(api, ff, "/api/personal/goals",
                {"name": "Emergency fund", "months_of_envelopes": 3}).json()
    assert fund["target_cents"] == 3 * budget.everyday_monthly(accepted)
    # Put away: its envelope and planned line go.
    assert patch(api, ff, f"/api/personal/goals/{goal['id']}",
                 {"name": "Car repairs", "target_cents": 300_000,
                  "target_on": on.isoformat(), "saved_cents": 90_000}).json()[
        "planned"]["amount_cents"] == 300_000
    assert api.as_(ff).delete(f"/api/personal/goals/{goal['id']}").status_code == 204
    assert PersonalEnvelope.objects.get(pk=env.pk).archived_at is not None
    assert not PersonalPlanned.objects.filter(goal_id=goal["id"]).exists()


@pytest.mark.django_db
def test_a_goal_before_the_budget_gets_its_envelope_when_the_budget_is_used(ledger, history):
    goal = budget.save_goal(ledger, name="Christmas", target_cents=180_000,
                            target_on=date(THIS.year + 1, 12, 1))
    assert not PersonalEnvelope.objects.filter(goal=goal).exists()
    budget.accept(ledger)
    assert PersonalEnvelope.objects.get(goal=goal).rolls


# ========================================================== 6. Cash flow

@pytest.mark.django_db
def test_the_cash_flow_table_is_in_and_out_by_category_by_month(accepted, ff, api):
    flow = get(api, ff, "/api/personal/budget").json()["cash_flow"]
    assert len(flow["months"]) == 7 and flow["so_far"] == THIS.isoformat()
    names = [row["name"] for row in flow["rows"]]
    assert names[0] == "Income" and "Transfers" not in names
    income = flow["rows"][0]
    assert income["cents"][-2] == 1_090_000
    housing = next(r for r in flow["rows"] if r["name"] == "Housing")
    assert housing["cents"][1] == 284_000
    assert flow["net_cents"][-2] == flow["in_cents"][-2] - flow["out_cents"][-2]


# ===================================================== 7. Explain this budget

@pytest.fixture
def claude_never(monkeypatch):
    from apps.tenancy import claude

    monkeypatch.setattr(claude, "_client", lambda key: pytest.fail("Claude was asked"))


@pytest.mark.django_db
def test_explain_is_priced_first_sends_only_the_budget_and_counts_on_the_cap(
        accepted, ff, api, monkeypatch, settings):
    from apps.finance import explain
    from apps.personal import budget_ai
    from apps.tenancy import claude
    from apps.tenancy.models import AiCall

    settings.ANTHROPIC_API_KEY = "sk-ant-test"
    asked = []
    monkeypatch.setattr(claude, "_client", lambda key: SimpleNamespace(
        beta=SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: (
            asked.append(kw), SimpleNamespace(
                usage=SimpleNamespace(input_tokens=900, output_tokens=200,
                                      server_tool_use=None),
                model="claude-opus-4-1", stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text="Groceries lead.")]))[1]))))
    price = get(api, ff, "/api/personal/budget/explain").json()
    assert float(price["estimate_usd"]) > 0 and not asked
    sent = budget_ai.explain_input(accepted)
    assert "Groceries" in sent and "Unassigned" in sent and "CASH FLOW" in sent
    for private in (ff.user.full_name, ff.user.email, "Joint checking", "2210"):
        assert private not in sent
    answer = post(api, ff, "/api/personal/budget/explain", {}).json()
    assert answer["text"] == "Groceries lead." and len(asked) == 1
    assert AiCall.all_objects.get().purpose == budget_ai.PURPOSE
    assert budget_ai.PURPOSE in explain.PRESSED


# ============================================ 8. isolation and role boundaries

ROUTES = ("/api/personal/budget", "/api/personal/questions", "/api/personal/goals",
          "/api/personal/budget/explain")


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["CF", "VA", "FCC", "ECC"])
def test_role_boundaries_nobody_else_in_the_practice_reaches_the_budget(accepted, api, role,
                                                                       seeded_tenant):
    company = ClientCompanyFactory(tenant=seeded_tenant) if role in ("FCC", "ECC") else None
    someone = _member(seeded_tenant, role, company)
    for url in ROUTES:
        assert get(api, someone, url).status_code == 404, url
    assert post(api, someone, "/api/personal/budget/accept", {}).status_code == 404
    assert post(api, someone, "/api/personal/goals",
                {"name": "x", "target_cents": 100}).status_code == 404


@pytest.mark.django_db
def test_tenant_isolation_another_owner_reaches_none_of_this_budget(accepted, ff, api,
                                                                   tenant_b):
    other = _member(tenant_b, "FF")
    switched_on(tenant_b)
    env = envelope_of(accepted, "Groceries")
    goal = budget.save_goal(accepted, name="Mine", target_cents=1_000)
    q = PersonalQuestion.objects.filter(ledger=accepted).first()
    assert get(api, other, "/api/personal/budget").json()["has_budget"] is False
    assert get(api, other, "/api/personal/goals").json() == []
    assert patch(api, other, f"/api/personal/envelopes/{env.pk}",
                 {"planned_cents": 1}).status_code == 404
    assert post(api, other, f"/api/personal/envelopes/{env.pk}/cover",
                {"stand": True}).status_code == 404
    assert patch(api, other, f"/api/personal/goals/{goal.pk}",
                 {"name": "Theirs", "target_cents": 1}).status_code == 404
    assert post(api, other, f"/api/personal/questions/{q.pk}",
                {"skip": True}).status_code == 404
    assert post(api, other, "/api/personal/budget/assign",
                {"goal": str(goal.pk), "amount_cents": 100}).status_code == 404
    env.refresh_from_db()
    assert env.planned_cents == 82_000


@pytest.mark.django_db
def test_without_the_module_there_is_no_budget(seeded_tenant, ff, api):
    for url in ROUTES:
        assert get(api, ff, url).status_code == 404, url


@pytest.mark.django_db
def test_a_bill_the_same_every_month_is_proposed_up_to_the_next_ten(ledger, chart, joint):
    for n in (1, 2, 3):
        spend(ledger, joint, chart["Entertainment and subscriptions"], ago(n), 2_299)
    [row] = budget.proposal(ledger)["envelopes"]
    assert row["proposed_cents"] == 3_000          # $22.99 every month: $30, not $20
