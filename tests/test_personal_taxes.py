"""P6 M4 stop 4: taxes and the CPA (decisions 20–23, and decision 25's review).

The stop proves: **the quarterly number and the Jan 15 line; one CPA PDF with
both sides.**

1. The bracket table: data with a year on it; a missing year says so.
2. The estimate: self-employment tax, the brackets or a rate, the state's
   rate, the withholding, payments made on either side (January's for the
   year before), the four dates, the next date's figure and the safe harbor.
3. The set-aside: a percent of each draw, what it comes to since the last
   payment, and the Tax envelope (in the budget, Left is what is set aside).
4. Paying yourself: a draw and its pay matched (import, typed, removed),
   pay from the books when the account is not imported, the Overview's
   sentence, and the business forecast's line set from it.
5. For your CPA: the six groups, every line, miles, a non-cash donation
   naming its charity, standard against itemized, the personal facts, one
   PDF with both sections, and the business CSV unchanged.
6. Review with Claude: envelopes, goals and the set-aside, from ids only;
   the practice's name (which can be the owner's) never sent.
7. The payoff orders by name.
8. Isolation and role boundaries for every new route.
"""

from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.finance import reports
from apps.finance import services as finance
from apps.finance.models import FinanceEntry, FinanceForecastAdjustment, FinanceForecastPlanned
from apps.personal import (
    budget, cpa, debts, forecast, forecast_ai, paydays, services, tax_tables, taxes,
)
from apps.personal.models import (
    PersonalCategory, PersonalEnvelope, PersonalLine, PersonalMember, PersonalSetAside,
    PersonalTaxItem, PersonalTaxYear,
)
from apps.personal.services import PersonalError
from apps.tenancy import modules
from apps.tenancy.context import tenant_context

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import ClientCompanyFactory
from .test_client_invoicing import get, patch, post
from .test_finance_books import A, C, E, add, books  # noqa: F401
from .test_finance_forecast import back, cash, closed, on  # noqa: F401
from .test_personal_budget import ago, spend
from .test_personal_forecast import TODAY, account, fake_claude  # noqa: F401
from .test_personal_sides import switched_on

YEAR = 2026
ON = date(2026, 10, 19)


@pytest.fixture
def ledger(seeded_tenant, ff):
    switched_on(seeded_tenant)
    return services.ledger_for(ff.user)


@pytest.fixture
def chart(ledger):
    return {c.name: c for c in PersonalCategory.objects.filter(ledger=ledger)}


def practice_account(tenant, ff, name="Practice checking"):
    return finance.save_account(tenant, actor=ff.user, name=name, kind="bank",
                                opening_balance_cents=5_000_000, opening_on=date(2025, 1, 1))


def owner_draw(tenant, ff, bank, on_date, cents, **more):
    return finance.create_entry(
        tenant, actor=ff.user, kind="owner", direction="out", amount_cents=cents,
        on_date=on_date, account=bank, category=services.owner_category(tenant, "out"),
        **more)


def earned(tenant, ff, bank, kind, on_date, cents):
    from apps.finance.models import FinanceCategory

    finance.ensure_chart(tenant)
    category = FinanceCategory.all_objects.filter(tenant=tenant, type=kind,
                                                  archived_at__isnull=True).first()
    return finance.create_entry(tenant, actor=ff.user, kind=kind, direction=(
        "in" if kind == "income" else "out"), amount_cents=cents, on_date=on_date,
        account=bank, category=category)


@pytest.fixture
def practice(seeded_tenant, ff, ledger):
    """The practice's checking account; $240,000 net profit by October 19
    ($300,000 earned less $60,000 spent)."""
    bank = practice_account(seeded_tenant, ff)
    earned(seeded_tenant, ff, bank, "income", date(YEAR, 3, 1), 30_000_000)
    earned(seeded_tenant, ff, bank, "expense", date(YEAR, 3, 2), 6_000_000)
    return bank


def inputs(ledger, **more):
    return taxes.save_inputs(ledger, year=YEAR, **{
        "filing_status": "joint", "state": "CO", "state_rate_percent": "4.4",
        "other_income_cents": 7_200_000, **more})


# ============================================================ 1. the table

def test_the_brackets_are_data_with_a_year_and_a_missing_year_says_so():
    figures, used, note = tax_tables.for_year(2026)
    assert used == 2026 and note == ""
    assert figures["standard"]["joint"] == 3_220_000
    later, used, note = tax_tables.for_year(2031)
    assert used == max(tax_tables.YEARS) and later is tax_tables.YEARS[used]
    assert "no 2031 tax brackets" in note and str(used) in note
    # Band by band: $100,000 taxable, married filing jointly, 2026.
    brackets = figures["brackets"]["joint"]
    assert tax_tables.income_tax(10_000_000, brackets) == (
        2_480_000 * 0.10 + (10_000_000 - 2_480_000) * 0.12)
    assert tax_tables.income_tax(0, brackets) == 0


def test_self_employment_tax_is_15_3_percent_of_92_35_percent_social_security_capped():
    base = int(10_000_000 * 0.9235)
    assert taxes.se_tax(10_000_000, 18_450_000) == round(base * 0.153)
    # Over the wage base only the 2.9% goes on.
    big = int(40_000_000 * 0.9235)
    assert taxes.se_tax(40_000_000, 18_450_000) == round(18_450_000 * 0.124 + big * 0.029)


# ========================================================== 2. the estimate

@pytest.mark.django_db
def test_without_a_filing_status_it_says_what_is_missing(ledger, practice, seeded_tenant):
    found = taxes.estimate(ledger, seeded_tenant, YEAR, ON)
    assert not found["ready"] and "your filing status" in found["missing"]
    assert found["confirm"] == "Estimate; confirm with your CPA."


@pytest.mark.django_db
def test_the_estimate_is_se_tax_the_brackets_and_the_state_less_withholding(
        ledger, practice, seeded_tenant):
    inputs(ledger)
    PersonalMember.objects.create(ledger=ledger, name="Dana", relation="spouse",
                                  expected_withholding_cents=840_000)
    found = taxes.estimate(ledger, seeded_tenant, YEAR, ON)
    share = ((ON - date(YEAR, 1, 1)).days + 1) / 365
    profit = int(24_000_000 / share)
    assert found["profit"]["so_far_cents"] == 24_000_000
    assert found["profit"]["for_year_cents"] == profit
    se = taxes.se_tax(profit, 18_450_000)
    taxable = profit + 7_200_000 - se // 2 - 3_220_000
    federal = tax_tables.income_tax(taxable, tax_tables.YEARS[2026]["brackets"]["joint"])
    state = round(taxable * 0.044)
    assert (found["se_tax_cents"], found["taxable_cents"]) == (se, taxable)
    assert (found["federal_cents"], found["state_cents"]) == (federal, state)
    assert found["total_cents"] == se + federal + state
    assert found["required_cents"] == se + federal + state - 840_000
    assert found["method"] == "brackets" and found["deduction"]["kind"] == "standard"


@pytest.mark.django_db
def test_an_effective_rate_stands_in_for_the_brackets(ledger, practice, seeded_tenant):
    inputs(ledger, effective_rate_percent="18")
    found = taxes.estimate(ledger, seeded_tenant, YEAR, ON)
    assert found["method"] == "rate"
    assert found["federal_cents"] == round(found["taxable_cents"] * 0.18)


@pytest.mark.django_db
def test_payments_on_either_side_reduce_what_is_needed_and_januarys_is_last_years(
        ledger, chart, practice, seeded_tenant, ff):
    last = YEAR - 1                                             # its dates are all past
    taxes.save_inputs(ledger, year=last, filing_status="joint", state_rate_percent="4.4")
    owner_draw(seeded_tenant, ff, practice, date(last, 1, 15), 500_000,
               estimated_tax="federal")                        # the year before's fourth
    owner_draw(seeded_tenant, ff, practice, date(last, 4, 15), 1_000_000,
               estimated_tax="federal")
    owner_draw(seeded_tenant, ff, practice, date(last + 1, 1, 14), 300_000,
               estimated_tax="federal")                        # its own fourth
    savings = account(ledger, "Joint savings")
    spend(ledger, savings, chart["State estimated tax"], date(last, 6, 1), 70_000, day=15,
          text="COLO DEPT REV")
    found = taxes.estimate(ledger, seeded_tenant, last, date(last + 1, 2, 1))
    paid = [(p["on_date"], p["from"], p["which"], p["quarter_label"]) for p in found["payments"]]
    assert paid == [(f"{last}-04-15", "practice", "federal", "First quarter"),
                    (f"{last}-06-15", "household", "state", "Second quarter"),
                    (f"{last + 1}-01-14", "practice", "federal", "Fourth quarter")]
    assert found["paid_cents"] == 1_370_000
    assert found["still_needed_cents"] == max(0, found["required_cents"] - 1_370_000)
    before = taxes.payments(ledger, seeded_tenant, last - 1)
    assert [p["amount_cents"] for p in before] == [500_000]
    # And the year's payments are in its quarters, each paid against its date.
    assert [q["paid_cents"] for q in found["quarters"]] == [1_000_000, 70_000, 0, 300_000]


@pytest.mark.django_db
def test_the_four_dates_the_jan_15_line_and_the_safe_harbor(
        ledger, practice, seeded_tenant, ff):
    """The stop's proof, half one: the quarterly number and the Jan 15 line."""
    inputs(ledger, last_year_tax_cents=6_000_000, last_year_taxable_cents=18_000_000)
    owner_draw(seeded_tenant, ff, practice, date(YEAR, 4, 15), 1_000_000,
               estimated_tax="federal")
    found = taxes.estimate(ledger, seeded_tenant, YEAR, ON)
    dates = [q["on_date"] for q in found["quarters"]]
    assert dates == [f"{YEAR}-04-15", f"{YEAR}-06-15", f"{YEAR}-09-15", f"{YEAR + 1}-01-15"]
    quarter = taxes._round_up_ten(found["required_cents"] / 4)
    assert {q["amount_cents"] for q in found["quarters"]} == {quarter}
    assert [q["next"] for q in found["quarters"]] == [False, False, False, True]
    nxt = found["by_next"]
    assert nxt["on_date"] == f"{YEAR + 1}-01-15" and nxt["label"] == "Fourth quarter"
    assert nxt["needed_cents"] == taxes._round_up_ten(found["required_cents"]) - 1_000_000
    # 110%: last year's income was over $150,000.
    harbor = found["safe_harbor"]
    assert harbor["percent"] == 110 and harbor["target_cents"] == 6_600_000
    assert nxt["safe_harbor_cents"] == 6_600_000 - 1_000_000
    # Under the line, 100%, and it says when 110% would apply.
    inputs(ledger, last_year_taxable_cents=12_000_000)
    harbor = taxes.estimate(ledger, seeded_tenant, YEAR, ON)["safe_harbor"]
    assert harbor["percent"] == 100 and "110%" in harbor["why"] and "CPA" in harbor["why"]


@pytest.mark.django_db
def test_early_in_the_year_the_next_date_is_april_and_only_its_quarter_is_due(
        ledger, practice, seeded_tenant):
    inputs(ledger)
    found = taxes.estimate(ledger, seeded_tenant, YEAR, date(YEAR, 3, 31))
    assert found["by_next"]["on_date"] == f"{YEAR}-04-15"
    assert found["by_next"]["needed_cents"] == taxes._round_up_ten(found["required_cents"] / 4)


@pytest.mark.django_db
def test_a_missing_years_brackets_are_named_on_the_estimate(ledger, seeded_tenant):
    taxes.save_inputs(ledger, year=2031, filing_status="single", state_rate_percent="0")
    found = taxes.estimate(ledger, seeded_tenant, 2031, date(2031, 5, 1))
    assert found["brackets_year"] == max(tax_tables.YEARS)
    assert "no 2031 tax brackets" in found["brackets_note"]


@pytest.mark.django_db
def test_inputs_are_checked(ledger):
    for bad in ({"filing_status": "married"}, {"state": "Colorado"},
                {"state_rate_percent": "lots"}, {"state_rate_percent": "150"},
                {"last_year_tax_cents": -1}, {"medical_miles": "far"}):
        with pytest.raises(PersonalError):
            taxes.save_inputs(ledger, year=YEAR, **bad)
    with pytest.raises(PersonalError):
        taxes.save_inputs(ledger, year=YEAR, nonsense=1)
    row = taxes.save_inputs(ledger, year=YEAR, state="co", state_rate_percent="4.40")
    assert (row.state, row.state_rate_percent) == ("CO", Decimal("4.40"))


# ========================================================= 3. the set-aside

@pytest.mark.django_db
def test_the_set_aside_per_draw_and_what_it_comes_to_since_the_last_payment(
        ledger, practice, seeded_tenant, ff):
    inputs(ledger)
    today = TODAY
    owner_draw(seeded_tenant, ff, practice, today - timedelta(days=40), 1_000_000,
               estimated_tax="federal")
    for n in (1, 2, 3):
        owner_draw(seeded_tenant, ff, practice, ago(n).replace(day=28), 2_000_000)
    taxes.save_set_aside(ledger, year=taxes.payment_year(today), percent_per_draw="28",
                         saved_cents=150_000)
    found = taxes.estimate(ledger, seeded_tenant, today=today)
    draws = found["draws"]
    since = [d for d in (ago(n).replace(day=28) for n in (1, 2, 3))
             if d > today - timedelta(days=40)]
    assert draws["since_last_payment_cents"]["cents"] == int(2_000_000 * len(since) * 0.28)
    assert draws["to_cover_cents"] == max(0, found["still_needed_cents"] - 150_000)
    if draws["draws_ahead_cents"]:
        assert draws["suggested_percent"] == -(-draws["to_cover_cents"] * 100
                                               // draws["draws_ahead_cents"])
    assert found["envelope"]["saved_cents"] == 150_000


@pytest.mark.django_db
def test_the_tax_envelope_is_in_the_budget_and_its_left_is_what_is_set_aside(
        ledger, chart, seeded_tenant):
    joint = account(ledger, "Joint checking")
    for n in (3, 2, 1):
        spend(ledger, joint, chart["Groceries"], ago(n), 80_000)
        spend(ledger, joint, chart["Spouse pay"], ago(n), 490_000, direction="in")
    budget.accept(ledger)
    before = budget.month_view(ledger)["unassigned_cents"]
    env = taxes.use_envelope(ledger, planned_cents=120_000)
    assert env.category.name == "Taxes" and env.source == PersonalEnvelope.Source.TAX
    assert env.rolls and env.kind == PersonalEnvelope.Kind.SAVINGS
    taxes.save_set_aside(ledger, year=taxes.payment_year(TODAY), saved_cents=532_000)
    view = budget.month_view(ledger)
    row = next(r for r in view["envelopes"] if r["id"] == str(env.pk))
    assert row["left_cents"] == 532_000 and row["carried_cents"] == 0 and not row["over"]
    assert view["unassigned_cents"] == before - 120_000
    # Pressed again: the same envelope, another amount.
    assert taxes.use_envelope(ledger, planned_cents=90_000).pk == env.pk
    assert not PersonalSetAside.objects.filter(ledger=ledger, year=1999).exists()


# ======================================================== 4. paying yourself

@pytest.mark.django_db
def test_a_draw_and_its_pay_are_matched_when_the_account_is_imported(
        ledger, chart, practice, seeded_tenant, ff, api):
    from apps.personal import imports

    day = TODAY - timedelta(days=20)
    draw = owner_draw(seeded_tenant, ff, practice, day, 1_900_000)
    joint = account(ledger, "Joint checking")
    csv_text = ("Date,Description,Amount\n"
                f"{(day + timedelta(days=1)):%m/%d/%Y},ONLINE TRANSFER FROM BIZ,19000.00\n"
                f"{(day + timedelta(days=3)):%m/%d/%Y},SOMETHING ELSE,19000.00\n")
    batch = imports.dry_run(seeded_tenant, ledger=ledger, account=joint, filename="j.csv",
                            file_bytes=csv_text.encode(), mapping={
                                "date": "Date", "description": "Description",
                                "amount": "Amount", "date_format": "%m/%d/%Y",
                                "sign": "negative_is_out", "balance": ""})
    rows = list(batch.rows.order_by("row_number"))
    pay = services.system_category(ledger, services.PAY_FROM_PRACTICE)
    assert rows[0].category_id == pay.pk and rows[0].side == "personal"
    assert rows[1].category_id is None                      # three days later: not the draw
    imports.commit(batch, tenant=seeded_tenant, actor=ff.user)
    line = PersonalLine.objects.get(ledger=ledger, description="ONLINE TRANSFER FROM BIZ")
    assert line.draw_entry_id == draw.pk and line.category_id == pay.pk
    # The draw leaves the books: the pay is still pay, unmatched.
    finance.remove_entry(draw, actor=ff.user, reason="Typed twice.")
    line.refresh_from_db()
    assert line.draw_entry_id is None and line.category_id == pay.pk and not line.removed_at


@pytest.mark.django_db
def test_a_draw_typed_after_its_pay_is_imported_is_matched_then(
        ledger, chart, practice, seeded_tenant, ff):
    joint = account(ledger, "Joint checking")
    day = TODAY - timedelta(days=10)
    line = PersonalLine.objects.create(ledger=ledger, account=joint, on_date=day,
                                       amount_cents=1_234_500, direction="in",
                                       description="TRANSFER IN")
    elsewhere = PersonalLine.objects.create(
        ledger=ledger, account=joint, on_date=day, amount_cents=1_234_500, direction="in",
        description="BONUS", category=chart["Other income"])
    draw = owner_draw(seeded_tenant, ff, practice, day - timedelta(days=1), 1_234_500)
    line.refresh_from_db()
    elsewhere.refresh_from_db()
    assert line.draw_entry_id == draw.pk
    assert line.category.system_code == services.PAY_FROM_PRACTICE
    assert elsewhere.draw_entry_id is None                  # placed elsewhere by the owner
    # An estimated tax payment is not pay.
    tax = owner_draw(seeded_tenant, ff, practice, day, 500_000, estimated_tax="federal")
    assert not PersonalLine.objects.filter(draw_entry=tax).exists()


@pytest.mark.django_db
def test_with_no_household_account_imported_the_books_draws_are_the_pay(
        ledger, practice, seeded_tenant, ff):
    for n in (3, 2, 1):
        owner_draw(seeded_tenant, ff, practice, ago(n).replace(day=28), 1_500_000)
    found = forecast.build(ledger, TODAY, snapshot=False)
    pay = [row for row in found["lines"] if row["group"] == "pay"]
    assert pay and {row["amount_cents"] for row in pay} == {1_500_000}
    assert all(row["kind"] == "known" for row in pay)
    assert all(date.fromisoformat(row["on_date"]).day in (28, TODAY.day) for row in pay)


@pytest.mark.django_db
def test_the_overview_says_what_the_envelopes_need_and_what_was_paid_on_average(
        ledger, chart, practice, seeded_tenant, ff, api):
    joint = account(ledger, "Joint checking")
    for n in (3, 2, 1):
        spend(ledger, joint, chart["Groceries"], ago(n), 300_000)
        spend(ledger, joint, chart["Spouse pay"], ago(n), 100_000, direction="in")
        owner_draw(seeded_tenant, ff, practice, ago(n).replace(day=28), 600_000)
    budget.accept(ledger)
    found = get(api, ff, "/api/personal/pay-yourself").json()
    assert found["envelopes_cents"] == 300_000 and found["other_income_cents"] == 100_000
    assert found["needed_cents"] == 200_000
    assert found["paid"]["months"] == 3 and found["paid"]["average_cents"] == 600_000
    assert found["difference_cents"] == 400_000
    assert found["pay_category"] == f"Pay from {seeded_tenant.name}"
    assert found["forecasting"] is False and found["business_line"] is None
    assert post(api, ff, "/api/personal/pay-yourself",
                {"amount_cents": 200_000}).status_code == 409


@pytest.mark.django_db
def test_the_business_forecasts_pay_yourself_line_is_set_from_it(
        ledger, cash, ff, api):  # noqa: F811
    tenant = cash["tenant"]
    switched_on(tenant)
    closed(tenant, back(3), back(2), back(1))
    for month in (back(3), back(2), back(1)):
        add(api, ff, cash, "owner", 1_900_000, on(month, 28), "Owner draw", direction="out")
    line = paydays.business_line(tenant)
    assert line["amount_cents"] == 1_900_000 and line["cadence"] == "monthly"
    with tenant_context(tenant.pk):
        found = post(api, ff, "/api/personal/pay-yourself", {"amount_cents": 875_000})
    assert found.status_code == 200
    adj = FinanceForecastAdjustment.all_objects.get(tenant=tenant)
    assert (adj.kind, adj.amount_cents, adj.source) == ("amount", 875_000, "personal")
    assert found.json()["business_line"]["amount_cents"] == 875_000
    assert post(api, ff, "/api/personal/pay-yourself", {"amount_cents": 0}).status_code == 400


@pytest.mark.django_db
def test_with_no_draws_found_the_business_forecast_gets_a_planned_line(
        ledger, cash, ff, api):  # noqa: F811
    tenant = cash["tenant"]
    switched_on(tenant)
    assert post(api, ff, "/api/personal/pay-yourself",
                {"amount_cents": 875_000}).status_code == 200
    planned = FinanceForecastPlanned.all_objects.get(tenant=tenant)
    assert (planned.description, planned.amount_cents, planned.repeat, planned.direction) \
        == ("Pay yourself", 875_000, "monthly", "out")


# ============================================================ 5. For your CPA

@pytest.fixture
def deductible(ledger, chart):
    joint = account(ledger, "Joint checking")
    spend(ledger, joint, chart["Doctors and dentists"], date(YEAR, 4, 1), 18_000, day=9,
          text="BELL MEDICAL GROUP")
    spend(ledger, joint, chart["Doctors and dentists"], date(YEAR, 5, 1), 2_000, day=9,
          direction="in", text="BELL MEDICAL REFUND")
    spend(ledger, joint, chart["Property taxes"], date(YEAR, 6, 1), 214_000, day=15,
          text="EL PASO CNTY TREASURER")
    for month in (4, 5, 6):
        spend(ledger, joint, chart["Church"], date(YEAR, month, 1), 20_000, day=7,
              text="ST JOHNS GIVING")
    spend(ledger, joint, chart["Groceries"], date(YEAR, 4, 1), 50_000)    # not deductible
    spend(ledger, joint, chart["Childcare and education"], date(YEAR, 8, 1), 40_000,
          text="LITTLE OAKS")
    spend(ledger, joint, chart["Church"], date(YEAR - 1, 12, 1), 99_000)   # another year
    cpa.save_item(ledger, year=YEAR, tax_group="non_cash", charity="Goodwill of Colorado",
                  description="Clothing, four bags", amount_cents=34_000,
                  on_date=date(YEAR, 9, 10))
    cpa.save_item(ledger, year=YEAR, tax_group="interest",
                  description="Mortgage interest, from the lender's statement",
                  amount_cents=1_440_900)
    taxes.save_inputs(ledger, year=YEAR, medical_miles=86, charitable_miles=140,
                      hsa_cents=200_000)
    return joint


@pytest.mark.django_db
def test_the_personal_worksheet_is_the_cpas_six_groups_every_line_listed(
        ledger, deductible, seeded_tenant):
    found = {g["group"]: g for g in cpa.groups(ledger, YEAR)}
    assert list(found) == ["medical", "health_insurance", "interest", "property_tax",
                           "charitable", "non_cash"]
    medical = found["medical"]
    assert [r["amount_cents"] for r in medical["rows"]] == [18_000, -2_000]
    assert medical["total_cents"] == 16_000 and medical["miles"] == 86
    assert found["charitable"]["total_cents"] == 60_000 and found["charitable"]["miles"] == 140
    assert len(found["charitable"]["rows"]) == 3
    assert found["property_tax"]["rows"][0]["description"] == "EL PASO CNTY TREASURER"
    assert found["interest"]["total_cents"] == 1_440_900
    gift = found["non_cash"]["rows"][0]
    assert (gift["charity"], gift["kind"], gift["amount_cents"]) == (
        "Goodwill of Colorado", "item", 34_000)
    assert found["health_insurance"]["rows"] == []
    assert cpa.itemized_total(ledger, YEAR) == 16_000 + 1_440_900 + 214_000 + 60_000 + 34_000


@pytest.mark.django_db
def test_a_non_cash_donation_names_its_charity_and_a_figure_is_more_than_nothing(ledger):
    with pytest.raises(PersonalError, match="charity"):
        cpa.save_item(ledger, year=YEAR, tax_group="non_cash", description="Books",
                      amount_cents=1_000)
    with pytest.raises(PersonalError):
        cpa.save_item(ledger, year=YEAR, tax_group="interest", description="x",
                      amount_cents=0)
    with pytest.raises(PersonalError):
        cpa.save_item(ledger, year=YEAR, tax_group="groceries", description="x",
                      amount_cents=1)


@pytest.mark.django_db
def test_standard_against_itemized_with_no_advice_beyond_ask_your_cpa(ledger, deductible):
    found = cpa.standard_against_itemized(ledger, YEAR)
    assert found["standard_cents"] is None                   # no filing status yet
    taxes.save_inputs(ledger, year=YEAR, filing_status="joint")
    found = cpa.standard_against_itemized(ledger, YEAR)
    assert found["standard_cents"] == 3_220_000 and found["status_label"] == \
        "Married filing jointly"
    assert found["itemized_cents"] == cpa.itemized_total(ledger, YEAR)
    assert found["note"].endswith("ask your CPA.")


@pytest.mark.django_db
def test_the_personal_facts_each_say_ask_your_cpa(ledger, deductible, practice, seeded_tenant,
                                                   ff):
    from apps.personal.models import PersonalHolding

    owner_draw(seeded_tenant, ff, practice, date(YEAR, 6, 15), 430_000,
               estimated_tax="federal")
    PersonalHolding.objects.create(ledger=ledger, name="Roth IRA", kind="retirement",
                                   contribution_text="VANGUARD ROTH")
    spend(ledger, deductible, PersonalCategory.objects.get(ledger=ledger,
                                                           name="Savings and retirement"),
          date(YEAR, 5, 1), 50_000, day=18, text="VANGUARD ROTH IRA")
    PersonalHolding.objects.create(ledger=ledger, name="Solo 401(k)", kind="retirement",
                                   monthly_cents=200_000)
    facts = {f["key"]: f for f in cpa.facts(ledger, seeded_tenant, YEAR, ON)}
    assert list(facts) == ["estimated", "health", "retirement", "hsa", "childcare"]
    assert all("Ask your CPA." in f["note"] for f in facts.values())
    second = facts["estimated"]["quarters"][1]
    assert second["total_cents"] == 430_000 and second["payments"][0]["from"] == "practice"
    accounts = {a["name"]: a for a in facts["retirement"]["accounts"]}
    assert accounts["Roth IRA"]["cents"] == 50_000 and accounts["Roth IRA"]["from"] == "lines"
    assert accounts["Solo 401(k)"]["cents"] == 200_000 * 9          # January to September
    assert facts["hsa"]["total_cents"] == 200_000
    assert facts["childcare"]["total_cents"] == 40_000


@pytest.mark.django_db
def test_one_page_and_one_pdf_with_both_sections_and_the_business_csv_unchanged(
        ledger, deductible, practice, seeded_tenant, ff, api):
    """The stop's proof, half two: one CPA PDF with both sides."""
    page = get(api, ff, f"/api/personal/cpa?year={YEAR}").json()
    assert page["business"] == reports.worksheet(seeded_tenant, year=YEAR)
    assert [g["group"] for g in page["personal"]["groups"]][0] == "medical"
    html = cpa.render_html(ledger, seeded_tenant, YEAR)
    for text in (f"Business: Business income and expense worksheet, {YEAR}, cash basis",
                 "Personal: itemized deduction worksheet", "Goodwill of Colorado",
                 "EL PASO CNTY TREASURER", "Standard against itemized", "Personal facts",
                 "Estimate; confirm with your CPA."):
        assert text in html, text
    pdf = get(api, ff, f"/api/personal/cpa/pdf?year={YEAR}")
    assert pdf.status_code == 200 and pdf["Content-Type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")
    assert f"for-your-cpa-{YEAR}.pdf" in pdf["Content-Disposition"]
    # The business file alone: the worksheet's figures, line for line, as before.
    sheet = reports.export_worksheet(seeded_tenant, year=YEAR)
    first = next(csv.reader(io.StringIO(sheet)))
    assert first == [f"Business income and expense worksheet, {YEAR}, cash basis"]
    assert "itemized deduction" not in sheet.lower() and "Goodwill" not in sheet


@pytest.mark.django_db
def test_figures_for_the_cpa_are_added_and_removed_through_the_routes(ledger, ff, api):
    made = post(api, ff, "/api/personal/cpa/items", {
        "year": YEAR, "tax_group": "non_cash", "charity": "Habitat ReStore",
        "description": "A dining table", "amount_cents": 25_000, "on_date": f"{YEAR}-05-02"})
    assert made.status_code == 200
    rows = next(g for g in made.json()["personal"]["groups"] if g["group"] == "non_cash")["rows"]
    assert rows[0]["charity"] == "Habitat ReStore"
    item = PersonalTaxItem.objects.get(ledger=ledger)
    assert post(api, ff, "/api/personal/cpa/items", {
        "year": YEAR, "tax_group": "non_cash", "description": "x",
        "amount_cents": 1}).status_code == 400
    gone = api.as_(ff).delete(f"/api/personal/cpa/items/{item.pk}")
    assert gone.status_code == 200
    item.refresh_from_db()
    assert item.removed_at is not None


# ====================================================== 6. Review with Claude

@pytest.mark.django_db
def test_review_proposes_envelope_goal_and_set_aside_changes_from_ids_only(
        ledger, chart, practice, seeded_tenant, ff, api, fake_claude):
    joint = account(ledger, "Joint checking")
    for n in (3, 2, 1):
        spend(ledger, joint, chart["Groceries"], ago(n), 120_000)
        spend(ledger, joint, chart["Spouse pay"], ago(n), 490_000, direction="in")
        spend(ledger, joint, chart[services.PAY_DEFAULT_NAME], ago(n), 600_000, day=2,
              direction="in", text="TRANSFER IN")
        owner_draw(seeded_tenant, ff, practice, ago(n).replace(day=1), 600_000)
    budget.accept(ledger)
    groceries = next(e for e in budget.envelopes(ledger) if e.category.name == "Groceries")
    budget.update(groceries, planned_cents=60_000)
    goal = budget.save_goal(ledger, name="Christmas", target_cents=180_000,
                            target_on=TODAY + timedelta(days=60))
    inputs(ledger)
    taxes.save_set_aside(ledger, year=taxes.payment_year(TODAY), percent_per_draw="5")
    get(api, ff, "/api/personal/budget")                     # names the pay category
    text, _r, _m, envelopes, goals, aside = forecast_ai.review_input(ledger, TODAY)
    assert seeded_tenant.name not in text and services.PAY_DEFAULT_NAME in text
    assert "ENVELOPES" in text and "GOALS" in text
    env = next(e for e in envelopes if e["name"] == "Groceries")
    assert env["proposed_cents"] == 120_000
    g = next(item for item in goals if item["name"] == "Christmas")
    fake_claude.answers.append(
        '{"one_offs": [], "missed": [], "questions": [],'
        ' "envelopes": [{"id": "%s", "why": "Spent twice the plan."}, {"id": "E99"}],'
        ' "goals": [{"id": "%s", "why": "Close."}],'
        ' "set_aside": [{"id": "S1", "why": "Low against the estimate."}]}'
        % (env["ref"], g["ref"]))
    found = post(api, ff, "/api/personal/forecast/ask/review", {}).json()
    assert [e["id"] for e in found["envelopes"]] == [str(groceries.pk)]
    assert found["envelopes"][0]["proposed_cents"] == 120_000
    assert [x["id"] for x in found["goals"]] == [str(goal.pk)]
    if aside:
        assert found["set_aside"][0]["suggested_percent"] == aside[0]["suggested_percent"]
    groceries.refresh_from_db()
    assert groceries.planned_cents == 60_000                 # nothing changed by the call


@pytest.mark.django_db
def test_the_pay_category_is_named_for_the_practice_but_never_sent(ledger, chart, ff, api):
    get(api, ff, "/api/personal/categories")
    pay = services.system_category(ledger, services.PAY_FROM_PRACTICE)
    assert pay.name == f"Pay from {ff.tenant.name}"
    assert services.for_claude(ledger, f"x {pay.name} y") == \
        f"x {services.PAY_DEFAULT_NAME} y"
    # A name the owner gave it is kept.
    pay.name = "Salary"
    pay.save()
    services.name_pay(ledger, ff.tenant)
    pay.refresh_from_db()
    assert pay.name == "Salary"


# ============================================================ 7. the orders

@pytest.mark.django_db
def test_the_payoff_orders_are_shown_by_name(ledger, ff, api):
    shown = get(api, ff, "/api/personal/debts").json()
    assert (shown["order_label"], shown["other_order_label"]) == (
        "Smallest balance first", "Highest rate first")
    refused = get(api, ff, "/api/personal/debts?order=sideways").json()["detail"]
    assert "smallest balance first" in refused and "highest rate first" in refused
    assert debts.ORDER_NAMES == {"snowball": "Smallest balance first",
                                 "avalanche": "Highest rate first"}


# ============================================ 8. isolation and role boundaries

ROUTES = ("/api/personal/taxes", "/api/personal/pay-yourself", "/api/personal/cpa",
          f"/api/personal/cpa/pdf?year={YEAR}")
POSTS = (("/api/personal/taxes/inputs", {"filing_status": "joint"}),
         ("/api/personal/taxes/set-aside", {"saved_cents": 1}),
         ("/api/personal/taxes/envelope", {"planned_cents": 1}),
         ("/api/personal/pay-yourself", {"amount_cents": 1}),
         ("/api/personal/cpa/items", {"tax_group": "interest", "description": "x",
                                      "amount_cents": 1}))


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["CF", "VA", "FCC", "ECC"])
def test_role_boundaries_nobody_else_in_the_practice_reaches_stop_4(ledger, api, role,
                                                                    seeded_tenant):
    company = ClientCompanyFactory(tenant=seeded_tenant) if role in ("FCC", "ECC") else None
    someone = _member(seeded_tenant, role, company)
    for url in ROUTES:
        assert get(api, someone, url).status_code == 404, url
    for url, body in POSTS:
        assert post(api, someone, url, body).status_code == 404, url
    assert not PersonalTaxYear.objects.exists() and not PersonalTaxItem.objects.exists()


@pytest.mark.django_db
def test_a_practice_without_the_module_has_none_of_stop_4(tenant_b, api):
    owner = _member(tenant_b, "FF")
    for url in ROUTES:
        assert get(api, owner, url).status_code == 404, url


@pytest.mark.django_db
def test_tenant_isolation_another_owner_reaches_none_of_stop_4(
        ledger, deductible, practice, seeded_tenant, ff, api, tenant_b):
    inputs(ledger)
    taxes.save_set_aside(ledger, year=YEAR, saved_cents=532_000)
    owner_draw(seeded_tenant, ff, practice, date(YEAR, 4, 15), 1_000_000,
               estimated_tax="federal")
    other = _member(tenant_b, "FF")
    switched_on(tenant_b)
    theirs = get(api, other, f"/api/personal/taxes?year={YEAR}").json()
    assert theirs["payments"] == [] and theirs["set_aside"]["saved_cents"] == 0
    assert theirs["inputs"]["filing_status"] == "" and theirs["profit"]["so_far_cents"] == 0
    page = get(api, other, f"/api/personal/cpa?year={YEAR}").json()
    assert all(g["rows"] == [] for g in page["personal"]["groups"])
    assert page["business"]["estimated"] == []
    loop = get(api, other, "/api/personal/pay-yourself").json()
    assert loop["paid"]["average_cents"] is None and loop["matched"] == 0
    item = PersonalTaxItem.objects.filter(ledger=ledger).first()
    assert patch(api, other, f"/api/personal/cpa/items/{item.pk}",
                 {"description": "Theirs"}).status_code == 404
    assert api.as_(other).delete(f"/api/personal/cpa/items/{item.pk}").status_code == 404
    # A draw in the other practice's books is never matched to this ledger.
    bank_b = practice_account(tenant_b, other)
    owner_draw(tenant_b, other, bank_b, TODAY - timedelta(days=5), 777_700)
    line = PersonalLine.objects.create(ledger=ledger, account=deductible,
                                       on_date=TODAY - timedelta(days=4),
                                       amount_cents=777_700, direction="in",
                                       description="TRANSFER IN")
    assert paydays.match(ledger, seeded_tenant) == 0
    line.refresh_from_db()
    assert line.draw_entry_id is None
    assert not FinanceEntry.all_objects.filter(tenant=seeded_tenant, amount_cents=777_700)
