"""The quarterly tax set-aside, an estimate (P6 M4 decision 21).

**Every figure here is an estimate; confirm with your CPA.** It is arithmetic
on the owner's own inputs and books, never advice, and the screen says so in
bold on the Taxes page.

- **Inputs, once a year** (`PersonalTaxYear`): filing status, state and the
  flat state rate the owner gives, last year's total tax and taxable income
  from the return, or just an effective rate; the household's other income
  before withholding (or, if left empty, the household's income lines). The
  spouse's expected withholding is the household member's (stop 3).
- **The estimate.** Business net profit so far this year (the practice's
  books, cash basis), at the pace so far for the whole year; self-employment
  tax on it (15.3% of 92.35%, the 12.4% Social Security part only up to the
  year's wage base, `tax_tables`), half of it deducted; federal income tax at
  the year's brackets after the standard deduction (or the itemized total,
  if larger), or at the owner's effective rate; state at the owner's rate on
  the same taxable income. Less the expected withholding, what is left is
  what estimated payments have to cover.
- **The quarters**: April 15, June 15, September 15 and January 15 of the
  next year, a quarter each. **The safe harbor** beside it: 100% of last
  year's tax, or 110% when last year's income was over $150,000 ($75,000
  married filing separately), less the withholding.
- **Payments already made** reduce what is needed: those marked as
  estimated tax in the practice's books, and lines in the household's Taxes
  categories. A payment made in January counts toward the year before.
- **The set-aside**: a percent of each draw from here that covers what is
  still needed, and the **Tax envelope**: what is set aside so far against
  what is needed by the next date.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.finance.models import FinanceEntry
from apps.personal import tax_tables
from apps.personal.models import (
    PersonalCategory, PersonalEnvelope, PersonalLine, PersonalMember, PersonalSetAside,
    PersonalTaxYear,
)
from apps.personal.services import PAY_FROM_PRACTICE, PersonalError

K, D = FinanceEntry.Kind, FinanceEntry.Direction
CONFIRM = "Estimate; confirm with your CPA."
TAXES = "Taxes"
#: The IRS's four dates for a year's estimated payments: (month, day, year
#: offset), with the label the screen gives each.
DUE = ((4, 15, 0, "First quarter"), (6, 15, 0, "Second quarter"),
       (9, 15, 0, "Third quarter"), (1, 15, 1, "Fourth quarter"))
INPUTS = ("filing_status", "state", "state_rate_percent", "last_year_tax_cents",
          "last_year_taxable_cents", "effective_rate_percent", "other_income_cents",
          "medical_miles", "charitable_miles", "hsa_cents", "qbi")
MONEY = ("last_year_tax_cents", "last_year_taxable_cents", "other_income_cents",
         "hsa_cents")
RATES = ("state_rate_percent", "effective_rate_percent")
MILES = ("medical_miles", "charitable_miles")


# ------------------------------------------------------------------ dates

def due_dates(year: int) -> list[dict]:
    return [{"label": label, "on_date": date(year + offset, month, day)}
            for month, day, offset, label in DUE]


def payment_year(on: date) -> int:
    """The tax year an estimated payment is for: January's is the fourth
    quarter of the year before."""
    return on.year - 1 if on.month == 1 else on.year


def _window(year: int) -> tuple[date, date]:
    """The days a payment for `year` is made on: February 1 to January 31."""
    return date(year, 2, 1), date(year + 1, 1, 31)


def _quarter(on: date, year: int) -> int:
    """The quarter a payment counts toward: the first date on or after it,
    the fourth if it is after them all."""
    for index, row in enumerate(due_dates(year)):
        if on <= row["on_date"]:
            return index
    return 3


# ----------------------------------------------------------------- inputs

def inputs(ledger, year: int) -> PersonalTaxYear | None:
    return PersonalTaxYear.objects.filter(ledger=ledger, year=year).first()


def _cents(value, what):
    if value in (None, ""):
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PersonalError(f"{what} is a whole number of cents, zero or more.")
    return value


def _rate(value, what):
    if value in (None, ""):
        return None
    try:
        rate = Decimal(str(value))
    except ArithmeticError:
        raise PersonalError(f"{what} is a percent, like 4.4.") from None
    if not rate.is_finite() or not Decimal("0") <= rate <= Decimal("100"):
        raise PersonalError(f"{what} is a percent from 0 to 100.")
    return rate.quantize(Decimal("0.01"))


LABELS = {"last_year_tax_cents": "Last year's total tax",
          "last_year_taxable_cents": "Last year's taxable income",
          "other_income_cents": "Other household income", "hsa_cents": "HSA contributions",
          "state_rate_percent": "The state rate", "effective_rate_percent": "The rate",
          "medical_miles": "Medical miles", "charitable_miles": "Charitable miles"}


@transaction.atomic
def save_inputs(ledger, *, year: int, **fields) -> PersonalTaxYear:
    unknown = set(fields) - set(INPUTS)
    if unknown:
        raise PersonalError(f"Not a tax input: {', '.join(sorted(unknown))}.")
    if isinstance(year, bool) or not isinstance(year, int) or not 2000 <= year <= 2100:
        raise PersonalError("The year is a year, like 2026.")
    row, _made = PersonalTaxYear.objects.get_or_create(ledger=ledger, year=year)
    for name, value in fields.items():
        if name == "filing_status":
            value = value or ""
            if value and value not in tax_tables.STATUSES:
                raise PersonalError("The filing status is single, joint, separate or head.")
        elif name == "qbi":
            value = value or ""
            if value not in ("", "20"):
                raise PersonalError("The QBI deduction is none (\"\") or 20% (\"20\").")
        elif name == "state":
            value = str(value or "").strip().upper()
            if value and (len(value) != 2 or not value.isalpha()):
                raise PersonalError("The state is its two letters, like CO.")
        elif name in MONEY:
            value = _cents(value, LABELS[name])
        elif name in RATES:
            value = _rate(value, LABELS[name])
        elif name in MILES:
            if value not in (None, "") and (isinstance(value, bool)
                                            or not isinstance(value, int) or value < 0):
                raise PersonalError(f"{LABELS[name]} is a whole number, zero or more.")
            value = None if value in (None, "") else value
        setattr(row, name, value)
    row.save()
    return row


def saved_so_far(ledger, year: int) -> int:
    """What is set aside for `year`'s tax, as the owner keeps it; read only."""
    return PersonalSetAside.objects.filter(ledger=ledger, year=year)\
        .values_list("saved_cents", flat=True).first() or 0


def set_aside(ledger, year: int) -> PersonalSetAside:
    row, _made = PersonalSetAside.objects.get_or_create(ledger=ledger, year=year)
    return row


@transaction.atomic
def save_set_aside(ledger, *, year: int, percent_per_draw=None, saved_cents=None,
                   clear_percent=False) -> PersonalSetAside:
    row = set_aside(ledger, year)
    fields = []
    if clear_percent:
        row.percent_per_draw = None
        fields.append("percent_per_draw")
    elif percent_per_draw not in (None, ""):
        row.percent_per_draw = _rate(percent_per_draw, "The set-aside percent")
        fields.append("percent_per_draw")
    if saved_cents is not None:
        row.saved_cents = _cents(saved_cents, "What is set aside") or 0
        fields.append("saved_cents")
    if fields:
        row.save(update_fields=fields + ["updated_at"])
    return row


# ----------------------------------------------------------- the figures

def _fraction(year: int, today: date) -> float:
    """How much of `year` has gone by, for working a year out from so far."""
    if today.year > year:
        return 1.0
    if today.year < year:
        return 0.0
    start = date(year, 1, 1)
    days = (date(year + 1, 1, 1) - start).days
    return max(1, (today - start).days + 1) / days


def business_profit(tenant, year: int, today: date) -> dict:
    """Net profit in the practice's books (cash basis): what has come in
    less what has gone out, this year to date, and at that pace for the
    year."""
    from apps.finance.reports import SIGNED, live

    so_far = 0
    if tenant is not None:
        earned = live(tenant).filter(kind__in=FinanceEntry.EARNED, on_date__year=year,
                                     on_date__lte=today)
        income = earned.filter(kind=K.INCOME).aggregate(t=Sum(SIGNED))["t"] or 0
        spent = earned.filter(kind=K.EXPENSE).aggregate(t=Sum(SIGNED))["t"] or 0
        so_far = income - spent
    fraction = _fraction(year, today)
    return {"so_far_cents": so_far,
            "for_year_cents": int(so_far / fraction) if fraction else 0,
            "through": min(today, date(year, 12, 31)).isoformat(),
            "share_of_year": round(fraction, 4)}


def _income_categories(ledger):
    return PersonalCategory.objects.filter(ledger=ledger, type="income")\
        .exclude(system_code=PAY_FROM_PRACTICE)


def other_income(ledger, year: int, today: date, typed) -> dict:
    """The household's income other than the practice for the year: the
    owner's figure (before withholding), or else the income lines so far at
    that pace, which are take-home pay and so likely less."""
    if typed is not None:
        return {"cents": typed, "from": "typed", "so_far_cents": None}
    rows = PersonalLine.objects.filter(
        ledger=ledger, removed_at__isnull=True, on_date__year=year, on_date__lte=today,
        category__in=_income_categories(ledger))
    so_far = sum(row.amount_cents if row.direction == "in" else -row.amount_cents
                 for row in rows)
    fraction = _fraction(year, today)
    return {"cents": int(so_far / fraction) if fraction else 0, "from": "lines",
            "so_far_cents": so_far}


def withholding(ledger) -> int:
    return sum(PersonalMember.objects.filter(
        ledger=ledger, removed_at__isnull=True).exclude(expected_withholding_cents=None)
        .values_list("expected_withholding_cents", flat=True))


def _tax_categories(ledger) -> dict:
    """`{category id: "federal" or "state"}` for the household's Taxes
    categories, as the personal forecast finds them."""
    out = {}
    for category in PersonalCategory.objects.filter(ledger=ledger, type="expense")\
            .select_related("parent"):
        if TAXES in (category.name, category.parent.name if category.parent_id else ""):
            out[category.pk] = "state" if "state" in category.name.lower() else "federal"
    return out


def payments(ledger, tenant, year: int) -> list[dict]:
    """The estimated payments made for `year`: marked in the practice's
    books, and paid from the household's accounts. Oldest first."""
    start, end = _window(year)
    out = []
    if tenant is not None:
        for entry in FinanceEntry.all_objects.filter(
                tenant=tenant, removed_at__isnull=True, kind=K.OWNER, direction=D.OUT,
                on_date__gte=start, on_date__lte=end).exclude(estimated_tax="")\
                .order_by("on_date", "created_at"):
            out.append({"id": str(entry.pk), "on_date": entry.on_date,
                        "amount_cents": entry.amount_cents, "which": entry.estimated_tax,
                        "from": "practice",
                        "link": f"/finance?kind=owner&estimated_tax={entry.estimated_tax}"})
    marks = _tax_categories(ledger)
    for line in PersonalLine.objects.filter(
            ledger=ledger, removed_at__isnull=True, category_id__in=list(marks),
            on_date__gte=start, on_date__lte=end).order_by("on_date", "created_at"):
        cents = line.amount_cents if line.direction == "out" else -line.amount_cents
        out.append({"id": str(line.pk), "on_date": line.on_date, "amount_cents": cents,
                    "which": marks[line.category_id], "from": "household",
                    "link": "/finance/personal/entries"})
    out.sort(key=lambda row: row["on_date"])
    for row in out:
        row["quarter"] = _quarter(row["on_date"], year)
    return out


def _deduction(ledger, year: int, status: str, figures: dict) -> dict:
    from apps.personal import cpa

    standard = figures["standard"][status]
    itemized = cpa.itemized_total(ledger, year)
    if itemized > standard:
        return {"cents": itemized, "kind": "itemized", "standard_cents": standard,
                "itemized_cents": itemized}
    return {"cents": standard, "kind": "standard", "standard_cents": standard,
            "itemized_cents": itemized}


def se_tax(profit: int, wage_base: int) -> int:
    """Self-employment tax: 15.3% of 92.35% of net profit, the Social
    Security part up to the wage base."""
    base = max(0, int(profit * tax_tables.SE_SHARE))
    return int(round(min(base, wage_base) * tax_tables.SE_SOCIAL_SECURITY
                     + base * tax_tables.SE_MEDICARE))


def _round_up_ten(cents: float) -> int:
    return int(-(-int(round(cents)) // 1000) * 1000)


def estimate(ledger, tenant, year: int | None = None, today: date | None = None) -> dict:
    """Decision 21, in figures. `ready` is False until the filing status is
    entered; what is missing is said in `missing`."""
    today = today or timezone.localdate()
    year = year or payment_year(today)
    row = inputs(ledger, year)
    figures, figures_year, note = tax_tables.for_year(year)
    status = row.filing_status if row is not None else ""
    profit = business_profit(tenant, year, today)
    other = other_income(ledger, year, today, row.other_income_cents if row else None)
    held = withholding(ledger)
    paid = payments(ledger, tenant, year)
    paid_total = sum(p["amount_cents"] for p in paid)
    saving = PersonalSetAside.objects.filter(ledger=ledger, year=year).first() \
        or PersonalSetAside(ledger=ledger, year=year)
    missing = []
    if not status:
        missing.append("your filing status")
    if row is None or row.state_rate_percent is None:
        missing.append("a state rate (0 if your state has no income tax)")
    result = {
        "year": year, "as_of": today.isoformat(), "confirm": CONFIRM,
        "brackets_year": figures_year, "brackets_note": note,
        "inputs": _inputs_out(row, year), "profit": profit, "other_income": other,
        "withholding_cents": held, "payments": [_payment_out(p) for p in paid],
        "paid_cents": paid_total, "missing": missing, "ready": bool(status),
        "statuses": tax_tables.STATUSES,
        "set_aside": {"percent_per_draw": _percent(saving.percent_per_draw),
                      "saved_cents": saving.saved_cents},
    }
    if not status:
        return result
    profit_year = max(0, profit["for_year_cents"])
    se = se_tax(profit_year, figures["wage_base"])
    gross = profit_year + max(0, other["cents"])
    adjusted = max(0, gross - se // 2)
    deduction = _deduction(ledger, year, status, figures)
    taxable = max(0, adjusted - deduction["cents"])
    # Owner, 2026-10-19: the QBI deduction, if chosen, lowers federal income
    # tax only; self-employment tax and the state's figure are untouched.
    qbi = profit_year * 20 // 100 if row.qbi == "20" else 0
    federal_taxable = max(0, taxable - qbi)
    if row.effective_rate_percent is not None:
        federal = int(round(federal_taxable * float(row.effective_rate_percent) / 100))
        method = "rate"
    else:
        federal = tax_tables.income_tax(federal_taxable, figures["brackets"][status])
        method = "brackets"
    state = int(round(taxable * float(row.state_rate_percent or 0) / 100))
    total = se + federal + state
    required = max(0, total - held)
    harbor = _safe_harbor(row, status, held)
    dates = due_dates(year)
    nxt = next((n for n, d in enumerate(dates) if d["on_date"] >= today), None)
    quarters = []
    for n, d in enumerate(dates):
        made = sum(p["amount_cents"] for p in paid if p["quarter"] == n)
        quarters.append({"label": d["label"], "on_date": d["on_date"].isoformat(),
                         "amount_cents": _round_up_ten(required / 4),
                         "safe_harbor_cents": (_round_up_ten(harbor["required_cents"] / 4)
                                               if harbor else None),
                         "paid_cents": made, "next": n == nxt,
                         "past": d["on_date"] < today})
    by_next = None
    if nxt is not None:
        share = (nxt + 1) / 4
        by_next = {
            "on_date": dates[nxt]["on_date"].isoformat(), "label": dates[nxt]["label"],
            "needed_cents": max(0, _round_up_ten(required * share) - paid_total),
            "safe_harbor_cents": (max(0, _round_up_ten(harbor["required_cents"] * share)
                                      - paid_total) if harbor else None)}
    still = max(0, required - paid_total)
    result.update({
        "method": method, "se_tax_cents": se, "se_half_cents": se // 2,
        "gross_cents": gross, "adjusted_cents": adjusted, "deduction": deduction,
        "taxable_cents": taxable, "qbi_cents": qbi, "federal_taxable_cents": federal_taxable,
        "federal_cents": federal, "state_cents": state,
        "state_rate_percent": _percent(row.state_rate_percent), "total_cents": total,
        "required_cents": required, "still_needed_cents": still,
        "safe_harbor": harbor, "quarters": quarters, "by_next": by_next,
        "draws": _per_draw(tenant, today, year, still, saving),
        "envelope": _envelope(ledger, saving, by_next, still, today, year),
    })
    return result


def _safe_harbor(row, status: str, held: int) -> dict | None:
    """100% of last year's tax, or 110% when last year's income was over the
    line. Taxable income stands in for adjusted gross income, which is at
    least as much: over the line on taxable income is over it on AGI too."""
    if row.last_year_tax_cents is None:
        return None
    over = (row.last_year_taxable_cents or 0) > tax_tables.SAFE_HARBOR_OVER[status]
    share = 110 if over else 100
    target = row.last_year_tax_cents * share // 100
    return {"percent": share, "last_year_tax_cents": row.last_year_tax_cents,
            "target_cents": target, "required_cents": max(0, target - held),
            "why": ("110%: last year's income was over $150,000 ($75,000 married filing "
                    "separately)." if over else
                    "100%. If last year's adjusted gross income was over $150,000 "
                    "($75,000 married filing separately), it is 110%: ask your CPA.")}


def _per_draw(tenant, today: date, year: int, still: int, saving) -> dict:
    """What share of each draw from here covers what is still needed for the
    year, after what is set aside: the year's remaining months at the
    average draw of the last six."""
    from apps.personal import paydays

    paid = paydays.paid_on_average(tenant, today) if tenant is not None else None
    average = (paid or {}).get("drawn_cents") or 0
    end = date(year + 1, 1, 15)
    months = max(0.0, (end - today).days / 30.44) if today <= end else 0.0
    ahead = int(average * months)
    gap = max(0, still - saving.saved_cents)
    percent = math.ceil(gap * 100 / ahead) if ahead else None
    return {"average_draw_cents": average, "months_left": round(months, 1),
            "draws_ahead_cents": ahead, "to_cover_cents": gap,
            "suggested_percent": percent,
            "since_last_payment_cents": _since_last(tenant, today, year,
                                                    saving.percent_per_draw)}


def _since_last(tenant, today, year, percent) -> dict | None:
    """What the set-aside percent of each draw since the last estimated
    payment comes to: a check on what is set aside so far."""
    from apps.personal import paydays

    if tenant is None or percent is None:
        return None
    last = FinanceEntry.all_objects.filter(
        tenant=tenant, removed_at__isnull=True, kind=K.OWNER, direction=D.OUT,
        on_date__lte=today).exclude(estimated_tax="").order_by("-on_date").first()
    since = last.on_date if last is not None else date(year, 1, 1)
    drawn = paydays.draws(tenant, start=since + timedelta(days=1), end=today)\
        .aggregate(t=Sum("amount_cents"))["t"] or 0
    return {"since": since.isoformat(), "drawn_cents": drawn,
            "cents": int(drawn * float(percent) / 100)}


def _envelope(ledger, saving, by_next, still, today, year) -> dict:
    """The Tax envelope (decision 21): what is set aside so far against what
    is needed by the next date, and a monthly amount that gets there by the
    last date of the year's payments."""
    env = tax_envelope(ledger)
    last = date(year + 1, 1, 15)
    months = max(1, (last.year - today.year) * 12 + last.month - today.month)
    monthly = _round_up_ten(max(0, still - saving.saved_cents) / months)
    return {"id": str(env.pk) if env else None,
            "planned_cents": env.planned_cents if env else None,
            "saved_cents": saving.saved_cents,
            "needed_by_next_cents": by_next["needed_cents"] if by_next else None,
            "next_on": by_next["on_date"] if by_next else None,
            "short_cents": (max(0, by_next["needed_cents"] - saving.saved_cents)
                            if by_next else None),
            "suggested_monthly_cents": monthly, "months_left": months}


def tax_envelope(ledger) -> PersonalEnvelope | None:
    return PersonalEnvelope.objects.filter(ledger=ledger, archived_at__isnull=True,
                                           source=PersonalEnvelope.Source.TAX).first()


@transaction.atomic
def use_envelope(ledger, *, planned_cents: int) -> PersonalEnvelope:
    """The owner's press: the Tax envelope at `planned_cents` a month, in the
    Taxes category, saved up (it rolls). Made, or changed."""
    from apps.personal import budget

    if isinstance(planned_cents, bool) or not isinstance(planned_cents, int) \
            or planned_cents < 0:
        raise PersonalError("The amount is a whole number of cents, zero or more.")
    env = tax_envelope(ledger)
    if env is None:
        category = PersonalCategory.objects.filter(ledger=ledger, name=TAXES,
                                                   parent__isnull=True,
                                                   archived_at__isnull=True).first()
        if category is None:
            raise PersonalError("There is no Taxes category to hold it.", status=409)
        env = budget.envelopes(ledger).filter(category=category).first()
        if env is None:
            env = budget.add(ledger, category=category, planned_cents=planned_cents,
                             kind=PersonalEnvelope.Kind.SAVINGS)
    env.planned_cents, env.source = planned_cents, PersonalEnvelope.Source.TAX
    env.kind, env.rolls = PersonalEnvelope.Kind.SAVINGS, True
    env.save(update_fields=["planned_cents", "source", "kind", "rolls", "updated_at"])
    return env


# ---------------------------------------------------------------- output

def _percent(value) -> str | None:
    return None if value is None else f"{value:.2f}".rstrip("0").rstrip(".")


def _inputs_out(row, year) -> dict:
    out = {"year": year}
    for name in INPUTS:
        value = getattr(row, name) if row is not None else None
        if name in RATES:
            value = _percent(value)
        elif name in ("filing_status", "state", "qbi"):
            value = value or ""
        out[name] = value
    return out


def _payment_out(row) -> dict:
    return {**row, "on_date": row["on_date"].isoformat(),
            "quarter_label": DUE[row["quarter"]][3]}
