"""P6 M4 stop 3: the forecast and the rest (decisions 15–19, and the personal
forecast's two Claude buttons).

The stop proves: **the vehicle repair shows on the forecast; the payoff date
moves when the extra changes.**

1. The personal forecast: cash is the household's bank accounts, never a
   card; Known (pay from the practice at its cadence, debts under the plan,
   a yearly bill), Regular (twice a month when it comes twice), Planned (a
   goal's date, a one-off, a what-if only when tried); moves between the
   household's own accounts are neither in nor out; the floor, the views,
   adjustments and "How good it has been".
2. Debts: balances (an imported card from its import), Snowball and
   Avalanche, the other order's cost, the extra as an envelope, Unassigned
   toward debts, a debt never paid off at its minimum.
3. Retirement and investments: contributions recognized from transfers, on
   track or behind at the assumed return.
4. The household: labels, whose, one person's view, the withholding kept.
5. Net worth: assets less debts over time, a home's equity.
6. The Overview's two sides, side by side as numbers.
7. Explain this forecast and Review with Claude: priced first, what is sent.
8. Isolation and role boundaries for every new route.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.personal import (
    budget, debts, forecast, forecast_ai, household, networth, retirement, services,
)
from apps.personal.models import (
    PersonalAccount, PersonalAsset, PersonalBalance, PersonalCategory, PersonalDebt,
    PersonalEnvelope, PersonalForecastSnapshot, PersonalHolding, PersonalLine, PersonalMember,
    PersonalPlanned,
)
from apps.personal.services import PersonalError

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import ClientCompanyFactory
from .test_client_invoicing import get, patch, post
from .test_personal_budget import ago, spend
from .test_personal_sides import switched_on

TODAY = timezone.localdate()
THIS = TODAY.replace(day=1)


@pytest.fixture
def ledger(seeded_tenant, ff):
    switched_on(seeded_tenant)
    return services.ledger_for(ff.user)


@pytest.fixture
def chart(ledger):
    return {c.name: c for c in PersonalCategory.objects.filter(ledger=ledger)}


def account(ledger, name, kind="bank", opening=0):
    return PersonalAccount.objects.create(ledger=ledger, name=name, kind=kind,
                                          opening_balance_cents=opening, opening_on=ago(7))


def paired(ledger, one_account, other_account, category, month, cents, day=5):
    out = spend(ledger, one_account, category, month, cents, day=day, text="TRANSFER OUT")
    back = spend(ledger, other_account, category, month, cents, day=day, direction="in",
                 text="TRANSFER IN")
    out.transfer_pair, back.transfer_pair = back, out
    out.save()
    back.save()
    return out, back


@pytest.fixture
def house(ledger, chart):
    """Three complete months: Dana's pay twice a month, pay from the practice
    once, a mortgage, groceries, a move to savings, a card's charges and its
    payment from checking."""
    joint = account(ledger, "Joint checking", opening=500_000)
    savings = account(ledger, "Joint savings", opening=1_000_000)
    card = account(ledger, "Rewards card", kind="card")
    for n in (3, 2, 1):
        month = ago(n)
        spend(ledger, joint, chart["Spouse pay"], month, 245_000, day=1, direction="in",
              text="MAPLE HILL PAYROLL")
        spend(ledger, joint, chart["Spouse pay"], month, 245_000, day=15, direction="in",
              text="MAPLE HILL PAYROLL")
        spend(ledger, joint, chart["Pay from the practice"], month, 600_000, day=2,
              direction="in", text="SUMMIT OPS TRANSFER")
        spend(ledger, joint, chart["Rent or mortgage"], month, 284_000, day=1,
              text="FRONT RANGE MORTGAGE")
        spend(ledger, joint, chart["Groceries"], month, 81_000 + n * 100, day=12,
              text="MOUNTAIN MARKET #118")
        paired(ledger, joint, savings, chart["Transfers"], month, 80_000)
        spend(ledger, card, chart["Dining"], month, 30_000, day=8, text="TRAILHEAD GRILL")
        paired(ledger, joint, card, chart["Transfers"], month, 30_000, day=20)
    return {"joint": joint, "savings": savings, "card": card}


def groups_of(found, kind=None):
    return {row["group"] for row in found["lines"] if kind is None or row["kind"] == kind}


def lines_in(found, month: date, group_start: str):
    key = month.isoformat()[:7]
    return [row for row in found["lines"] if row["on_date"].startswith(key)
            and row["group"].startswith(group_start)]


# ================================================================ 1. forecast

@pytest.mark.django_db
def test_cash_is_the_households_bank_accounts_and_never_a_card(ledger, house):
    from apps.personal import reconcile

    found = forecast.build(ledger, TODAY)
    expected = reconcile.balance(house["joint"], TODAY) + reconcile.balance(house["savings"],
                                                                         TODAY)
    assert found["cash_today_cents"] == expected
    assert {a["name"] for a in found["accounts"]} == {"Joint checking", "Joint savings"}
    # The card's charges are not drawn; its payment from checking is.
    labels = {row["label"] for row in found["lines"]}
    assert "TRAILHEAD GRILL" not in labels
    assert "TRANSFER OUT" in labels


@pytest.mark.django_db
def test_a_move_between_two_household_cash_accounts_is_neither_in_nor_out(ledger, house):
    found = forecast.build(ledger, TODAY)
    out = [row for row in found["lines"] if row["label"] == "TRANSFER OUT"]
    # Only the card's payment (30,000), never the 80,000 move to savings.
    assert out and {row["amount_cents"] for row in out} == {30_000}
    assert not [row for row in found["lines"] if row["label"] == "TRANSFER IN"]


@pytest.mark.django_db
def test_regular_lines_come_as_often_as_they_have_been_coming(ledger, house):
    found = forecast.build(ledger, TODAY)
    next_month = budget.add_months(THIS, 1)
    dana = [row for row in lines_in(found, next_month, "pattern:")
            if row["category"] == "Income: Spouse pay"]
    assert [(row["on_date"][8:], row["amount_cents"]) for row in dana] \
        == [("01", 245_000), ("15", 245_000)]
    assert dana[0]["cadence"] == "2 a month" and "2 times a month" in dana[0]["detail"]
    groceries = [row for row in lines_in(found, next_month, "pattern:")
                 if row["category"] == "Groceries"]
    assert len(groceries) == 1 and groceries[0]["amount_cents"] == 81_200   # the median


@pytest.mark.django_db
def test_pay_from_the_practice_is_known_at_the_cadence_it_has_been_paid(ledger, house):
    found = forecast.build(ledger, TODAY)
    pay = lines_in(found, budget.add_months(THIS, 2), "pay")
    assert len(pay) == 1 and pay[0]["kind"] == "known" and pay[0]["direction"] == "in"
    assert pay[0]["amount_cents"] == 600_000 and pay[0]["on_date"].endswith("-02")
    assert "pattern:" not in "".join(row["group"] for row in found["lines"]
                                     if row["category"] == "Pay from the practice")


@pytest.mark.django_db
def test_a_debt_is_paid_under_the_plan_on_its_due_day_as_a_known_line(ledger, chart, house):
    mortgage = PersonalDebt.objects.create(
        ledger=ledger, name="Home mortgage", kind="mortgage", rate_percent=Decimal("6"),
        minimum_cents=284_000, due_day=1, category=chart["Rent or mortgage"])
    PersonalBalance.objects.create(ledger=ledger, debt=mortgage, on_date=ago(1),
                                   balance_cents=30_000_000)
    debts.set_plan(ledger, extra=10_000)
    found = forecast.build(ledger, TODAY)
    later = lines_in(found, budget.add_months(THIS, 2), f"debt:{mortgage.pk}")
    assert len(later) == 1 and later[0]["kind"] == "known"
    assert later[0]["amount_cents"] == 294_000 and later[0]["on_date"].endswith("-01")
    assert "$100.00 of the plan's extra" in later[0]["detail"]
    # Its category's lines are not also forecast as Regular.
    assert not [row for row in found["lines"] if row["kind"] == "regular"
                and row["category"] == "Housing: Rent or mortgage"]
    # This month's, once a line is in for it, is not drawn again.
    spend(ledger, house["joint"], chart["Rent or mortgage"], THIS, 284_000, day=1)
    again = forecast.build(ledger, TODAY)
    assert lines_in(again, THIS, f"debt:{mortgage.pk}") == []


@pytest.mark.django_db
def test_the_vehicle_repair_shows_on_the_forecast(ledger, house):
    """The stop's proof, first half."""
    on = TODAY + timedelta(days=60)
    goal = budget.save_goal(ledger, name="Car repairs", target_cents=250_000, target_on=on,
                            saved_cents=90_000)
    found = forecast.build(ledger, TODAY)
    repair = [row for row in found["lines"] if row["label"] == "Car repairs"]
    assert len(repair) == 1
    assert repair[0]["kind"] == "planned" and repair[0]["counted"] is True
    assert repair[0]["on_date"] == on.isoformat() and repair[0]["amount_cents"] == 250_000
    week = next(row for row in found["weeks"] if repair[0]["id"] in row["lines"])
    assert week["out_cents"] >= 250_000
    assert any(p["goal"] == str(goal.pk) for p in found["planned"])
    # A goal with no date is saved for, never spent on a day: listed, not drawn.
    budget.save_goal(ledger, name="Emergency fund", target_cents=3_000_000)
    found = forecast.build(ledger, TODAY)
    assert [g["name"] for g in found["goals_not_drawn"]] == ["Emergency fund"]
    assert "Emergency fund" not in {row["label"] for row in found["lines"]}


@pytest.mark.django_db
def test_a_yearly_bill_spread_in_the_budget_is_known_in_its_month(ledger, chart, house):
    spend(ledger, house["joint"], chart["Home insurance"], ago(2), 138_000, day=14,
          text="ALLSTATE HOME POLICY")
    env = budget.spread_yearly(ledger, category=chart["Home insurance"], cents=138_000,
                               month=ago(2).month)
    assert env.planned_cents == 12_000
    found = forecast.build(ledger, TODAY)
    bill = [row for row in found["lines"] if row["group"] == f"yearly:{env.pk}"]
    assert len(bill) == 1 and bill[0]["amount_cents"] == 138_000
    assert bill[0]["on_date"] == forecast._add_months(ago(2), 12, 14).isoformat()


@pytest.mark.django_db
def test_a_what_if_is_drawn_only_when_tried_and_saves_nothing(ledger, house, ff, api):
    roof = forecast.save_planned(ledger, name="New roof", amount_cents=1_450_000,
                                 on_date=TODAY + timedelta(days=20), is_what_if=True)
    found = get(api, ff, "/api/personal/forecast").json()
    line = next(row for row in found["lines"] if row["label"] == "New roof")
    assert line["counted"] is False and line["what_if"] is True
    tried = post(api, ff, "/api/personal/forecast/what-if", {"on": [str(roof.pk)]}).json()
    assert tried["what_if"]["views"]["90"]["end_cents"] \
        == found["views"]["90"]["end_cents"] - 1_450_000
    assert tried["what_if"]["difference_at_low"]["90"] < 0
    assert tried["what_if"]["months"][-1]["end_cents"] \
        == found["months"][-1]["end_cents"] - 1_450_000
    # Off and another amount, on a Regular line.
    group = next(row["group"] for row in found["lines"] if row["label"] == "MOUNTAIN MARKET #118")
    without = post(api, ff, "/api/personal/forecast/what-if", {"off": [group]}).json()
    assert without["what_if"]["months"][-1]["end_cents"] > found["months"][-1]["end_cents"]
    assert post(api, ff, "/api/personal/forecast/what-if",
                {"amounts": {group: "lots"}}).status_code == 400
    assert get(api, ff, "/api/personal/forecast").json()["months"] == found["months"]


@pytest.mark.django_db
def test_the_floor_and_the_views(ledger, house, ff, api):
    found = post(api, ff, "/api/personal/forecast/floor", {"floor_cents": 10_000_000}).json()
    assert found["floor_cents"] == 10_000_000
    assert set(found["views"]) == {"30", "90", "180", "months"}
    assert len(found["weeks"]) == 26 and len(found["months"]) == 12
    assert found["views"]["90"]["first_below_floor"] is not None
    first = found["weeks"][0]
    assert first["end_cents"] == first["start_cents"] + first["in_cents"] - first["out_cents"]
    assert found["weeks"][1]["start_cents"] == first["end_cents"]
    assert post(api, ff, "/api/personal/forecast/floor",
                {"floor_cents": None}).json()["floor_cents"] is None


@pytest.mark.django_db
def test_two_complete_months_are_needed_for_regular_lines(ledger, chart):
    joint = account(ledger, "Joint checking")
    spend(ledger, joint, chart["Groceries"], ago(1), 50_000)
    found = forecast.build(ledger, TODAY)
    assert found["ready"] is False and found["note"] == forecast.NOT_READY
    assert not [row for row in found["lines"] if row["kind"] == "regular"]
    assert not PersonalForecastSnapshot.objects.filter(ledger=ledger).exists()


@pytest.mark.django_db
def test_an_adjustment_changes_a_regular_line_and_can_be_undone(ledger, house, ff, api):
    found = get(api, ff, "/api/personal/forecast").json()
    group = next(row["group"] for row in found["lines"] if row["label"] == "MOUNTAIN MARKET #118")
    after = post(api, ff, "/api/personal/forecast/adjustments",
                 {"group": group, "kind": "amount", "amount_cents": 99_900}).json()
    mine = [row for row in after["lines"] if row["group"] == group]
    assert mine and {row["amount_cents"] for row in mine} == {99_900}
    assert mine[0]["adjusted"].startswith("You set it to $999.00")
    gone = post(api, ff, "/api/personal/forecast/adjustments",
                {"group": group, "kind": "not_regular"}).json()
    assert group not in groups_of(gone)
    for adj in gone["adjustments"]:
        api.as_(ff).delete(f"/api/personal/forecast/adjustments/{adj['id']}")
    back = get(api, ff, "/api/personal/forecast").json()
    assert {row["amount_cents"] for row in back["lines"] if row["group"] == group} \
        == {mine_row["amount_cents"] for mine_row in found["lines"]
            if mine_row["group"] == group}
    assert post(api, ff, "/api/personal/forecast/adjustments",
                {"group": "pattern:nothing", "kind": "not_regular"}).status_code == 404


@pytest.mark.django_db
def test_planned_lines_once_and_repeating_and_a_goals_follows_its_goal(ledger, house, ff, api):
    on = (TODAY + timedelta(days=10)).isoformat()
    made = post(api, ff, "/api/personal/forecast/planned",
                {"name": "Dana's bonus", "direction": "in", "amount_cents": 150_000,
                 "on_date": on}).json()
    assert [row["amount_cents"] for row in made["lines"] if row["label"] == "Dana's bonus"] \
        == [150_000]
    post(api, ff, "/api/personal/forecast/planned",
         {"name": "Piano lessons", "amount_cents": 16_000, "on_date": on, "repeat": "monthly"})
    piano = [row for row in get(api, ff, "/api/personal/forecast").json()["lines"]
             if row["label"] == "Piano lessons"]
    assert len(piano) >= 11
    goal = budget.save_goal(ledger, name="Christmas", target_cents=180_000,
                            target_on=TODAY + timedelta(days=40))
    planned = PersonalPlanned.objects.get(goal=goal)
    assert patch(api, ff, f"/api/personal/forecast/planned/{planned.pk}",
                 {"amount_cents": 1}).status_code == 409
    assert api.as_(ff).delete(f"/api/personal/forecast/planned/{planned.pk}").status_code == 409


@pytest.mark.django_db
def test_how_good_it_has_been_sets_the_forecast_kept_beside_what_happened(ledger, chart,
                                                                         house):
    """A snapshot is taken once, the first time the month is worked out; what
    happened is the month's lines that came in after it, worked out each time."""
    month = ago(1)
    taken = month.replace(day=3)
    PersonalForecastSnapshot.objects.create(
        ledger=ledger, month=month, taken_on=taken,
        forecast={"start_cents": 1, "in_cents": 0, "out_cents": 81_000, "end_cents": -80_999,
                  "by": {"Groceries": {"in": 0, "out": 81_000}}})
    late = spend(ledger, house["joint"], chart["Groceries"], month, 90_000, day=25)
    assert late.created_at > PersonalForecastSnapshot.objects.get(month=month).created_at
    rows = forecast.history(ledger, TODAY)
    row = next(r for r in rows if r["month"] == month.isoformat()[:7])
    groceries = next(g for g in row["largest"] if g["name"] == "Groceries")
    assert groceries["forecast_cents"] == -81_000 and groceries["actual_cents"] == -90_000
    # This month's is taken by looking, once.
    forecast.build(ledger, TODAY)
    forecast.build(ledger, TODAY)
    assert PersonalForecastSnapshot.objects.filter(ledger=ledger, month=THIS).count() == 1


# =================================================================== 2. debts

@pytest.fixture
def two_debts(ledger, chart):
    car = PersonalDebt.objects.create(ledger=ledger, name="Car loan", kind="auto",
                                      rate_percent=Decimal("5.9"), minimum_cents=51_200,
                                      due_day=10, category=chart["Car payment"])
    card = PersonalDebt.objects.create(ledger=ledger, name="Store card", kind="card",
                                       rate_percent=Decimal("24.9"), minimum_cents=5_000,
                                       due_day=20)
    PersonalBalance.objects.create(ledger=ledger, debt=car, on_date=ago(1),
                                   balance_cents=1_864_000)
    PersonalBalance.objects.create(ledger=ledger, debt=card, on_date=ago(1),
                                   balance_cents=420_000)
    return {"car": car, "card": card}


@pytest.mark.django_db
def test_the_payoff_date_moves_when_the_extra_changes(ledger, two_debts, ff, api):
    """The stop's proof, second half."""
    none = get(api, ff, "/api/personal/debts").json()
    some = get(api, ff, "/api/personal/debts?extra=20000").json()
    car = lambda found: next(d for d in found["debts"] if d["name"] == "Car loan")  # noqa: E731
    assert car(some)["payoff_on"] < car(none)["payoff_on"]
    assert some["debt_free_on"] < none["debt_free_on"]
    assert some["interest_cents"] < none["interest_cents"]
    # A look saves nothing; the plan does, and the forecast follows it.
    assert get(api, ff, "/api/personal/debts").json()["extra_cents"] == 0
    saved = post(api, ff, "/api/personal/debts/plan", {"extra_cents": 20_000}).json()
    assert saved["extra_cents"] == 20_000 and saved["debt_free_on"] == some["debt_free_on"]
    assert saved["extra_saves"]["interest_cents"] > 0 and saved["extra_saves"]["months"] > 0


@pytest.mark.django_db
def test_snowball_takes_the_smallest_first_and_avalanche_the_highest_rate(ledger, chart):
    rows = [{"id": "a", "name": "A", "balance": 100_000, "rate": 5.0, "minimum": 5_000,
             "due_day": 1},
            {"id": "b", "name": "B", "balance": 400_000, "rate": 22.0, "minimum": 10_000,
             "due_day": 1}]
    snow = debts.simulate(rows, order="snowball", extra=20_000, today=TODAY)
    ava = debts.simulate(rows, order="avalanche", extra=20_000, today=TODAY)
    assert snow["order"] == ["a", "b"] and ava["order"] == ["b", "a"]
    assert snow["debts"]["a"]["payoff_month"] < ava["debts"]["a"]["payoff_month"]
    assert ava["interest_cents"] < snow["interest_cents"]
    # In the first month the extra goes all to the first in the order.
    assert snow["debts"]["a"]["payments"][0] == (0, 25_000)
    assert snow["debts"]["b"]["payments"][0] == (0, 10_000)


@pytest.mark.django_db
def test_the_other_order_says_what_it_would_cost_or_save(ledger, two_debts):
    shown = debts.represent(ledger, TODAY, extra=20_000)
    assert shown["order"] == "snowball" and shown["other_order"] == "avalanche"
    other = debts.represent(ledger, TODAY, extra=20_000, order="avalanche")
    assert shown["other"]["interest_cents"] == other["interest_cents"] - shown["interest_cents"]
    assert other["other"]["interest_cents"] == -shown["other"]["interest_cents"]


@pytest.mark.django_db
def test_a_debt_whose_minimum_never_covers_its_interest_is_never_paid_off(ledger):
    rows = [{"id": "x", "name": "X", "balance": 1_000_000, "rate": 30.0, "minimum": 1_000,
             "due_day": 1}]
    found = debts.simulate(rows, order="snowball", extra=0, today=TODAY)
    assert found["debts"]["x"]["payoff_on"] is None and found["all_paid"] is False
    assert found["interest_cents"] is None


@pytest.mark.django_db
def test_an_imported_card_takes_its_balance_from_the_import(ledger, chart):
    from apps.personal import reconcile

    card = account(ledger, "Rewards card", kind="card")
    spend(ledger, card, chart["Dining"], ago(1), 12_345)
    debt = PersonalDebt.objects.create(ledger=ledger, name="Rewards card", kind="card",
                                       account=card, minimum_cents=2_500, due_day=20,
                                       rate_percent=Decimal("21"))
    cents, _on, source = debts.balance_of(debt)
    assert cents == reconcile.balance(card) == 12_345 and source == "import"
    with pytest.raises(PersonalError):
        debts.add_balance(debt, on_date=TODAY, cents=1)


@pytest.mark.django_db
def test_the_extra_is_an_envelope_in_debt_payments(ledger, two_debts, chart, joint_history):
    budget.accept(ledger)
    debts.set_plan(ledger, extra=20_000)
    env = PersonalEnvelope.objects.get(ledger=ledger, category=chart["Debt payments"],
                                       archived_at__isnull=True)
    assert env.planned_cents == 20_000 and env.source == "debt"
    debts.set_plan(ledger, extra=35_000)
    env.refresh_from_db()
    assert env.planned_cents == 35_000
    debts.set_plan(ledger, extra=0)
    env.refresh_from_db()
    assert env.archived_at is not None


@pytest.fixture
def joint_history(ledger, chart):
    """Enough history for a budget: three months of pay and groceries."""
    joint = account(ledger, "Household checking")
    for n in (3, 2, 1):
        spend(ledger, joint, chart["Spouse pay"], ago(n), 500_000, direction="in")
        spend(ledger, joint, chart["Groceries"], ago(n), 80_000)
    return joint


@pytest.mark.django_db
def test_unassigned_can_go_toward_the_debts(ledger, two_debts, joint_history, ff, api):
    budget.accept(ledger)
    left = budget.month_view(ledger)["unassigned_cents"]
    assert post(api, ff, "/api/personal/budget/assign",
                {"debts": True, "amount_cents": 10_000}).status_code == 200
    ledger.refresh_from_db()
    assert ledger.payoff_extra_cents == 10_000
    assert budget.month_view(ledger)["unassigned_cents"] == left - 10_000
    assert post(api, ff, "/api/personal/budget/assign",
                {"debts": True, "amount_cents": left * 2}).status_code == 409


@pytest.mark.django_db
def test_debts_are_added_changed_balanced_and_closed_through_the_routes(ledger, chart, ff,
                                                                        api):
    made = post(api, ff, "/api/personal/debts",
                {"name": "Student loan", "kind": "student", "rate_percent": "4.5",
                 "minimum_cents": 30_000, "due_day": 5, "balance_cents": 2_200_000}).json()
    row = next(d for d in made["debts"] if d["name"] == "Student loan")
    assert row["balance_cents"] == 2_200_000 and row["payoff_on"]
    assert len(row["projected"]) > 12 and row["history"][0]["cents"] == 2_200_000
    assert post(api, ff, "/api/personal/debts", {"name": "x", "kind": "boat"}).status_code \
        == 400
    assert post(api, ff, "/api/personal/debts",
                {"name": "x", "kind": "other", "due_day": 32}).status_code == 400
    changed = patch(api, ff, f"/api/personal/debts/{row['id']}",
                    {"minimum_cents": 60_000}).json()
    assert next(d for d in changed["debts"] if d["id"] == row["id"])["payoff_on"] \
        < row["payoff_on"]
    post(api, ff, f"/api/personal/debts/{row['id']}/balance",
         {"on_date": TODAY.isoformat(), "balance_cents": 2_000_000})
    assert next(d for d in get(api, ff, "/api/personal/debts").json()["debts"]
                if d["id"] == row["id"])["balance_cents"] == 2_000_000
    api.as_(ff).delete(f"/api/personal/debts/{row['id']}")
    assert get(api, ff, "/api/personal/debts").json()["debts"] == []


# ============================================================== 3. retirement

@pytest.mark.django_db
def test_contributions_are_recognized_from_transfers_or_typed(ledger, chart):
    joint = account(ledger, "Joint checking")
    for n in range(1, 7):
        spend(ledger, joint, chart["Savings and retirement"], ago(n), 50_000,
              text="VANGUARD ROTH IRA")
    roth = PersonalHolding.objects.create(ledger=ledger, name="Roth IRA", kind="retirement",
                                          contribution_text="vanguard roth")
    solo = PersonalHolding.objects.create(ledger=ledger, name="Solo 401(k)",
                                          kind="retirement", monthly_cents=200_000)
    assert retirement.contributions(roth, TODAY)["monthly_cents"] == 50_000
    assert retirement.contributions(roth, TODAY)["recognized"] is True
    assert retirement.contributions(solo, TODAY) == {
        **retirement.contributions(solo, TODAY), "monthly_cents": 200_000,
        "recognized": False}


@pytest.mark.django_db
def test_on_track_or_behind_at_the_assumed_return(ledger, ff, api):
    assert ledger.assumed_return_percent == Decimal("6.00")
    year = TODAY.year + 10
    made = post(api, ff, "/api/personal/holdings",
                {"name": "Solo 401(k)", "kind": "retirement", "balance_cents": 10_000_000,
                 "target_cents": 50_000_000, "target_year": year,
                 "monthly_cents": 100_000}).json()
    row = made["holdings"][0]
    months = (year - TODAY.year) * 12 + 12 - TODAY.month
    assert row["status"]["months"] == months
    assert row["status"]["projected_cents"] == retirement.project(
        10_000_000, 100_000, Decimal("6"), months)
    assert row["status"]["on_track"] is False and row["status"]["short_cents"] > 0
    need = row["status"]["needed_monthly_cents"]
    assert retirement.project(10_000_000, need + 1, Decimal("6"), months) >= 50_000_000
    # At a higher return the same account is on track.
    raised = post(api, ff, "/api/personal/holdings", {"assumed_return_percent": "12"}).json()
    assert raised["holdings"][0]["status"]["on_track"] is True
    assert "not financial advice" in raised["estimate"]
    assert post(api, ff, "/api/personal/holdings",
                {"assumed_return_percent": "45"}).status_code == 400
    assert post(api, ff, "/api/personal/holdings",
                {"name": "x", "target_cents": 100}).status_code == 400


# =============================================================== 4. household

@pytest.mark.django_db
def test_the_household_is_labels_with_whose_and_one_persons_view(ledger, chart, ff, api):
    shown = get(api, ff, "/api/personal/household").json()
    assert [m["is_you"] for m in shown["members"]] == [True]
    added = post(api, ff, "/api/personal/household",
                 {"name": "Dana Carter", "relation": "spouse",
                  "expected_withholding_cents": 840_000}).json()
    dana = next(m for m in added["members"] if m["name"] == "Dana Carter")
    assert dana["expected_withholding_cents"] == 840_000
    car = post(api, ff, "/api/personal/debts",
               {"name": "Car loan", "kind": "auto", "balance_cents": 1_000_000,
                "whose": dana["id"]}).json()
    post(api, ff, "/api/personal/debts", {"name": "Mortgage", "kind": "mortgage",
                                          "balance_cents": 30_000_000})
    hers = get(api, ff, f"/api/personal/debts?whose={dana['id']}").json()
    assert [d["name"] for d in hers["debts"]] == ["Car loan"]
    # Whose, on income, from the Household page.
    assert post(api, ff, "/api/personal/household/whose",
                {"thing": "category", "id": str(chart["Spouse pay"].pk),
                 "whose": dana["id"]}).status_code == 200
    assert PersonalCategory.objects.get(pk=chart["Spouse pay"].pk).whose_id is not None
    assert post(api, ff, "/api/personal/household/whose",
                {"thing": "category", "id": str(chart["Groceries"].pk),
                 "whose": dana["id"]}).status_code == 400
    # Taken out of the household, what was hers is joint.
    api.as_(ff).delete(f"/api/personal/members/{dana['id']}")
    debt = PersonalDebt.objects.get(pk=next(d["id"] for d in car["debts"]
                                            if d["name"] == "Car loan"))
    assert debt.whose_id is None
    you = shown["members"][0]["id"]
    assert api.as_(ff).delete(f"/api/personal/members/{you}").status_code == 409
    assert post(api, ff, "/api/personal/household",
                {"name": "Another me", "relation": "self"}).status_code == 409


# =============================================================== 5. net worth

@pytest.mark.django_db
def test_net_worth_is_assets_less_debts_with_a_homes_equity(ledger, chart, ff, api):
    joint = account(ledger, "Joint checking", opening=1_000_000)
    mortgage = PersonalDebt.objects.create(ledger=ledger, name="Mortgage", kind="mortgage")
    PersonalBalance.objects.create(ledger=ledger, debt=mortgage, on_date=ago(2),
                                   balance_cents=30_000_000)
    PersonalBalance.objects.create(ledger=ledger, debt=mortgage, on_date=ago(1),
                                   balance_cents=29_900_000)
    holding = PersonalHolding.objects.create(ledger=ledger, name="Roth", kind="retirement")
    PersonalBalance.objects.create(ledger=ledger, holding=holding, on_date=ago(1),
                                   balance_cents=4_000_000)
    made = post(api, ff, "/api/personal/net-worth",
                {"name": "The house", "kind": "home", "debt": str(mortgage.pk),
                 "value_cents": 60_000_000, "value_on": ago(3).isoformat()}).json()
    assert made["assets_cents"] == 1_000_000 + 4_000_000 + 60_000_000
    assert made["debts_cents"] == 29_900_000
    assert made["total_cents"] == made["assets_cents"] - 29_900_000
    assert made["equity"] == [{**made["equity"][0], "value_cents": 60_000_000,
                               "owed_cents": 29_900_000, "equity_cents": 30_100_000}]
    assert made["series"][-1]["on_date"] == TODAY.isoformat()
    assert len(made["series"]) >= 2 and made["change_cents"] is not None
    # A new value is a new point; the old one stays for the line.
    asset = PersonalAsset.objects.get(ledger=ledger)
    patch(api, ff, f"/api/personal/assets/{asset.pk}", {"value_cents": 61_000_000})
    assert networth.value_of(asset)[0] == 61_000_000
    assert PersonalBalance.objects.filter(asset=asset).count() == 2
    assert post(api, ff, "/api/personal/net-worth", {"name": "Boat"}).status_code == 400
    del joint


# ================================================================ 6. two sides

@pytest.mark.django_db
def test_the_overview_sets_both_sides_ending_balances_side_by_side(ledger, house, ff, api,
                                                                  seeded_tenant):
    from apps.tenancy import modules

    shown = get(api, ff, "/api/personal/sides").json()
    assert shown["days"] == 90 and shown["business"] is None
    assert shown["personal"]["end_cents"] == forecast.build(
        ledger, TODAY, snapshot=False)["views"]["90"]["end_cents"]
    modules.set_enabled(seeded_tenant, modules.BOOKKEEPING, True, actor=ff.user)
    modules.set_enabled(seeded_tenant, modules.FORECAST, True, actor=ff.user)
    both = get(api, ff, "/api/personal/sides").json()
    assert set(both["business"]) >= {"ready", "end_cents", "cash_today_cents"}


# ===================================================== 7. the two Claude buttons

@pytest.fixture
def fake_claude(monkeypatch, settings):
    from apps.tenancy import claude

    settings.ANTHROPIC_API_KEY = "sk-ant-test"
    asked, answers = [], []

    def create(**kw):
        asked.append(kw)
        return SimpleNamespace(
            usage=SimpleNamespace(input_tokens=1500, output_tokens=300, server_tool_use=None),
            model="claude-opus-4-1", stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=answers.pop(0) if answers
                                     else "The low point is the mortgage.")])

    monkeypatch.setattr(claude, "_client", lambda key: SimpleNamespace(
        beta=SimpleNamespace(messages=SimpleNamespace(create=create))))
    return SimpleNamespace(asked=asked, answers=answers)


@pytest.mark.django_db
def test_explain_this_forecast_is_priced_first_and_sends_no_merchant_or_account(
        ledger, chart, house, ff, api, fake_claude):
    from apps.finance import explain
    from apps.tenancy.models import AiCall

    mortgage = PersonalDebt.objects.create(
        ledger=ledger, name="Front Range Mortgage Co", kind="mortgage", minimum_cents=284_000,
        due_day=1, rate_percent=Decimal("6"), category=chart["Rent or mortgage"])
    PersonalBalance.objects.create(ledger=ledger, debt=mortgage, on_date=ago(1),
                                   balance_cents=30_000_000)
    roth = PersonalHolding.objects.create(ledger=ledger, name="Roth", kind="retirement")
    PersonalBalance.objects.create(ledger=ledger, holding=roth, on_date=ago(1),
                                   balance_cents=4_123_456)
    price = get(api, ff, "/api/personal/forecast/ask").json()
    assert float(price["estimate_usd"]) > 0 and float(price["review_estimate_usd"]) > 0
    assert not fake_claude.asked
    sent = forecast_ai.explain_input(ledger)
    assert "Mortgage payment" in sent and "Income: Spouse pay" in sent and "LINES" in sent
    for private in (ff.user.full_name, ff.user.email, "Joint checking", "MAPLE HILL",
                    "MOUNTAIN MARKET", "Front Range", "41,234.56", "TRANSFER OUT"):
        assert private not in sent, private
    answer = post(api, ff, "/api/personal/forecast/ask/explain", {"view": "90"}).json()
    assert answer["text"] == "The low point is the mortgage." and len(fake_claude.asked) == 1
    assert AiCall.all_objects.get().purpose == forecast_ai.EXPLAIN
    assert {forecast_ai.EXPLAIN, forecast_ai.REVIEW} <= set(explain.PRESSED)


@pytest.mark.django_db
def test_review_proposes_only_from_ids_it_was_given_and_changes_nothing(
        ledger, chart, house, ff, api, fake_claude):
    spend(ledger, house["joint"], chart["Gifts"], ago(2), 25_000, text="PINE STREET GOODS")
    text, regular, missed = forecast_ai.review_input(ledger, TODAY)
    assert "PINE STREET" not in text and "MOUNTAIN MARKET" not in text
    gifts = next(item for item in missed if item["category"] == "Gifts")
    groceries = next(item for item in regular if item["category"] == "Groceries")
    fake_claude.answers.append(
        '{"one_offs": [{"id": "%s", "why": "Looks like one."}, {"id": "R999", "why": "x"}],'
        ' "missed": [{"id": "%s", "cadence": "yearly", "why": "A birthday."}],'
        ' "questions": [{"question": "Any trips planned?"}]}'
        % (groceries["ref"], gifts["ref"]))
    before = PersonalPlanned.objects.filter(ledger=ledger).count()
    found = post(api, ff, "/api/personal/forecast/ask/review", {}).json()
    assert [item["group"] for item in found["one_offs"]] == [groceries["group"]]
    assert found["missed"][0]["cadence"] == "yearly" and found["missed"][0]["next_on"]
    assert found["questions"] == [{"question": "Any trips planned?"}]
    assert PersonalPlanned.objects.filter(ledger=ledger).count() == before


@pytest.mark.django_db
def test_review_waits_for_two_complete_months(ledger, chart, ff, api, fake_claude):
    joint = account(ledger, "Joint checking")
    spend(ledger, joint, chart["Groceries"], ago(1), 50_000)
    assert post(api, ff, "/api/personal/forecast/ask/review", {}).status_code == 409
    assert not fake_claude.asked


# ============================================ 8. isolation and role boundaries

ROUTES = ("/api/personal/forecast", "/api/personal/forecast/ask", "/api/personal/sides",
          "/api/personal/debts", "/api/personal/holdings", "/api/personal/household",
          "/api/personal/net-worth")


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["CF", "VA", "FCC", "ECC"])
def test_role_boundaries_nobody_else_in_the_practice_reaches_stop_3(ledger, api, role,
                                                                    seeded_tenant):
    company = ClientCompanyFactory(tenant=seeded_tenant) if role in ("FCC", "ECC") else None
    someone = _member(seeded_tenant, role, company)
    for url in ROUTES:
        assert get(api, someone, url).status_code == 404, url
    for url, body in (("/api/personal/debts", {"name": "x", "kind": "other"}),
                      ("/api/personal/debts/plan", {"extra_cents": 1}),
                      ("/api/personal/holdings", {"name": "x"}),
                      ("/api/personal/household", {"name": "x"}),
                      ("/api/personal/net-worth", {"name": "x", "value_cents": 1}),
                      ("/api/personal/forecast/floor", {"floor_cents": 1}),
                      ("/api/personal/forecast/planned",
                       {"name": "x", "amount_cents": 1, "on_date": TODAY.isoformat()}),
                      ("/api/personal/forecast/ask/explain", {})):
        assert post(api, someone, url, body).status_code == 404, url


@pytest.mark.django_db
def test_tenant_isolation_another_owner_reaches_none_of_stop_3(ledger, chart, house, ff, api,
                                                               tenant_b):
    other = _member(tenant_b, "FF")
    switched_on(tenant_b)
    debt = PersonalDebt.objects.create(ledger=ledger, name="Mine", kind="auto")
    holding = PersonalHolding.objects.create(ledger=ledger, name="Mine", kind="retirement")
    asset = PersonalAsset.objects.create(ledger=ledger, name="Mine", kind="home")
    dana = PersonalMember.objects.create(ledger=ledger, name="Dana", relation="spouse")
    planned = forecast.save_planned(ledger, name="Mine", amount_cents=100,
                                    on_date=TODAY + timedelta(days=3))
    group = next(row["group"] for row in forecast.build(ledger, TODAY)["lines"]
                 if row["kind"] == "regular")
    adj = forecast.adjust(ledger, group=group, kind="not_regular")
    theirs = get(api, other, "/api/personal/forecast").json()
    assert theirs["lines"] == [] and theirs["cash_today_cents"] == 0
    assert get(api, other, "/api/personal/debts").json()["debts"] == []
    assert get(api, other, "/api/personal/holdings").json()["holdings"] == []
    assert get(api, other, "/api/personal/net-worth").json()["things"] == []
    assert [m["name"] for m in get(api, other, "/api/personal/household").json()["members"]] \
        == [other.user.full_name or other.user.email]
    for method, url, body in (
            ("patch", f"/api/personal/debts/{debt.pk}", {"name": "Theirs"}),
            ("post", f"/api/personal/debts/{debt.pk}/balance", {"balance_cents": 1}),
            ("patch", f"/api/personal/holdings/{holding.pk}", {"name": "Theirs"}),
            ("post", f"/api/personal/holdings/{holding.pk}/balance", {"balance_cents": 1}),
            ("patch", f"/api/personal/assets/{asset.pk}", {"name": "Theirs"}),
            ("patch", f"/api/personal/members/{dana.pk}", {"name": "Theirs"}),
            ("patch", f"/api/personal/forecast/planned/{planned.pk}", {"name": "Theirs"}),
            ("post", "/api/personal/forecast/adjustments", {"group": group,
                                                            "kind": "not_regular"})):
        sent = post(api, other, url, body) if method == "post" else patch(api, other, url,
                                                                           body)
        assert sent.status_code == 404, url
    assert api.as_(other).delete(f"/api/personal/forecast/adjustments/{adj.pk}").status_code \
        == 404
    assert api.as_(other).delete(f"/api/personal/debts/{debt.pk}").status_code == 404
    # Nor can one of theirs be named as whose on one of this owner's things.
    them = household.members(services.ledger_for(other.user)).first()
    assert post(api, ff, "/api/personal/household/whose",
                {"thing": "debt", "id": str(debt.pk), "whose": str(them.pk)}).status_code \
        == 404
    debt.refresh_from_db()
    assert debt.name == "Mine" and debt.closed_at is None


@pytest.mark.django_db
def test_without_the_module_there_is_no_stop_3(seeded_tenant, ff, api):
    for url in ROUTES:
        assert get(api, ff, url).status_code == 404, url
