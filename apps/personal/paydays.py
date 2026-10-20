"""Paying yourself, one line on both sides (P6 M4 decision 20).

- **A draw is one thing seen twice.** In the practice's books it is an owner
  draw, as it always was; in the ledger it is "Pay from <practice>". When the
  household account it lands in is imported, the two are **matched**: the
  same amount, on the day of the draw or the next. A matched line is linked
  to its draw (`PersonalLine.draw_entry`) and, if nothing else placed it,
  put in the pay category. Matching runs when either side is imported and
  when a draw is typed; a draw removed from the books unmatches its line.
- **When the account is not imported**, the books' draws are the pay: the
  personal forecast draws them as a Known line at the cadence they have come
  (`forecast._pay`).
- **The loop.** The personal Overview tells the business side what the
  household needs: "Your envelopes need $X a month; you have paid yourself
  $Y on average." The owner can set the business forecast's pay-yourself line
  from it, which is an ordinary adjustment of that line in the business
  forecast (or a planned line there, if it has found no draws yet).

Nothing here moves money or changes the books: the match is a link, and the
business forecast changes only when the owner presses for it.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.finance.models import FinanceAccount, FinanceEntry
from apps.personal.models import PersonalAccount, PersonalCategory, PersonalLine
from apps.personal.services import (
    EVERYTHING_ELSE, PAY_FROM_PRACTICE, PersonalError, system_category,
)

K, D = FinanceEntry.Kind, FinanceEntry.Direction
#: The months the average is taken over.
AVERAGE_MONTHS = 6
#: A draw arrives on its day or the next (decision 20).
ARRIVES_WITHIN = timedelta(days=1)


def draws(tenant, *, start: date | None = None, end: date | None = None):
    """The practice's owner draws to the owner: money out of one of its bank
    or cash accounts, not an estimated tax payment, not a line of personal
    spending on a practice card (those are in the ledger already)."""
    rows = FinanceEntry.all_objects.filter(
        tenant=tenant, removed_at__isnull=True, kind=K.OWNER, direction=D.OUT,
        estimated_tax="", side=FinanceEntry.Side.BUSINESS, account__isnull=False)\
        .exclude(account__kind=FinanceAccount.Kind.CARD)
    if start is not None:
        rows = rows.filter(on_date__gte=start)
    if end is not None:
        rows = rows.filter(on_date__lte=end)
    return rows.order_by("on_date", "created_at")


def _pay_category(ledger) -> PersonalCategory | None:
    return system_category(ledger, PAY_FROM_PRACTICE)


def draw_for(tenant, *, on_date: date, amount_cents: int, taken: set):
    """The draw a line of `amount_cents` arriving on `on_date` is, if any:
    the same amount, that day or the day before, not already matched."""
    if tenant is None:
        return None
    linked = set(PersonalLine.objects.filter(
        draw_entry__isnull=False, removed_at__isnull=True,
        draw_entry__tenant=tenant).values_list("draw_entry_id", flat=True))
    for entry in draws(tenant, start=on_date - ARRIVES_WITHIN, end=on_date)\
            .filter(amount_cents=amount_cents):
        if entry.pk not in linked and entry.pk not in taken:
            return entry
    return None


@transaction.atomic
def match(ledger, tenant) -> int:
    """Link every unmatched line of money in to a household bank or cash
    account that is a draw from `tenant`. A line no rule or person placed
    (To sort, or Everything else) goes in the pay category; one placed
    elsewhere by the owner keeps its category. Returns how many matched."""
    if tenant is None:
        return 0
    pay = _pay_category(ledger)
    loose = system_category(ledger, EVERYTHING_ELSE)
    lines = PersonalLine.objects.filter(
        ledger=ledger, removed_at__isnull=True, direction="in", draw_entry__isnull=True,
        transfer_pair__isnull=True, account__isnull=False)\
        .exclude(account__kind=PersonalAccount.Kind.CARD).order_by("on_date", "created_at")
    taken: set = set()
    made = 0
    for line in lines:
        if line.category_id not in (None, getattr(pay, "pk", None),
                                    getattr(loose, "pk", None)):
            continue
        entry = draw_for(tenant, on_date=line.on_date, amount_cents=line.amount_cents,
                         taken=taken)
        if entry is None:
            continue
        taken.add(entry.pk)
        line.draw_entry = entry
        fields = ["draw_entry", "updated_at"]
        if pay is not None and line.category_id != pay.pk:
            line.category = pay
            fields.append("category")
        line.save(update_fields=fields)
        made += 1
    return made


def match_for_practice(tenant) -> int:
    """After the books changed: match for the practice owner's ledger, if
    they have one and the practice has Personal finance."""
    from apps.personal.models import PersonalLedger
    from apps.tenancy import modules
    from apps.tenancy.models import Membership, Role

    if not modules.has(tenant, modules.PERSONAL):
        return 0
    owners = Membership.all_objects.filter(tenant=tenant, role=Role.FF,
                                           revoked_at__isnull=True).values_list("user_id",
                                                                                flat=True)
    return sum(match(ledger, tenant) for ledger in PersonalLedger.objects.filter(
        owner_id__in=list(owners)))


# ------------------------------------------------------------ the loop

def _months_back(today: date, n: int) -> date:
    index = today.year * 12 + today.month - 1 - n
    return date(index // 12, index % 12 + 1, 1)


def paid_on_average(tenant, today: date | None = None) -> dict:
    """What the practice has paid its owner a month, over the last six
    complete months (fewer if the draws began later): draws to the owner's
    accounts, and personal spending on the practice's own accounts (an owner
    draw too, decision 3). Estimated tax paid from the practice is named
    beside it, not in it."""
    today = today or timezone.localdate()
    this = today.replace(day=1)
    start = _months_back(today, AVERAGE_MONTHS)
    first = FinanceEntry.all_objects.filter(
        tenant=tenant, removed_at__isnull=True, kind=K.OWNER, direction=D.OUT)\
        .order_by("on_date").values_list("on_date", flat=True).first()
    if first is None or first >= this:
        return {"months": 0, "average_cents": None, "drawn_cents": 0, "spent_cents": 0,
                "tax_cents": 0, "start": None, "end": None}
    start = max(start, first.replace(day=1))
    end = this - timedelta(days=1)
    months = (this.year - start.year) * 12 + this.month - start.month
    owner_out = FinanceEntry.all_objects.filter(
        tenant=tenant, removed_at__isnull=True, kind=K.OWNER, direction=D.OUT,
        on_date__gte=start, on_date__lte=end)
    drawn = draws(tenant, start=start, end=end).aggregate(t=Sum("amount_cents"))["t"] or 0
    spent = owner_out.filter(side=FinanceEntry.Side.PERSONAL)\
        .aggregate(t=Sum("amount_cents"))["t"] or 0
    tax = owner_out.exclude(estimated_tax="").aggregate(t=Sum("amount_cents"))["t"] or 0
    return {"months": months, "average_cents": (drawn + spent) // months,
            "drawn_cents": drawn // months, "spent_cents": spent // months,
            "tax_cents": tax // months, "start": start.isoformat(), "end": end.isoformat()}


def needed(ledger) -> dict:
    """What the envelopes need from the practice a month: every envelope
    (goals, the debts' extra and the Tax envelope among them) less the
    income planned from anywhere else. None without a budget."""
    from apps.personal import budget

    if not budget.has_budget(ledger):
        return {"needed_cents": None, "envelopes_cents": 0, "other_income_cents": 0}
    view = budget.month_view(ledger)
    pay = _pay_category(ledger)
    other = sum(row["planned_cents"] for row in view["income"]
                if pay is None or row["category"] != str(pay.pk))
    return {"needed_cents": max(0, view["planned_cents"] - other),
            "envelopes_cents": view["planned_cents"], "other_income_cents": other}


def business_line(tenant) -> dict | None:
    """The business forecast's pay-yourself line: the largest regular owner
    draw it forecasts from a bank account, its monthly amount and any
    adjustment on it. None if the practice has no Cash forecast, or if the
    forecast has found no draws yet."""
    from apps.finance import forecast as business
    from apps.tenancy import modules

    if not modules.has(tenant, modules.FORECAST):
        return None
    found = business.build(tenant, snapshot=False)
    rows = [row for row in found["lines"]
            if row["kind"] == "regular"
            and row["group"].startswith(f"pattern:{K.OWNER}|{D.OUT}|")
            and row.get("counted")]
    if not rows:
        return {"group": "", "amount_cents": None, "cadence": "", "adjusted": "",
                "on_date": None}
    by_group: dict = {}
    for row in rows:
        by_group.setdefault(row["group"], row)
    row = max(by_group.values(), key=lambda r: r["amount_cents"])
    return {"group": row["group"], "amount_cents": row["amount_cents"],
            "cadence": row["cadence"], "adjusted": row["adjusted"],
            "on_date": row["on_date"].isoformat() if hasattr(row["on_date"], "isoformat")
            else row["on_date"]}


def loop(ledger, tenant, today: date | None = None) -> dict:
    """Decision 20's sentence, in figures, for the Overview."""
    from apps.tenancy import modules

    today = today or timezone.localdate()
    need = needed(ledger)
    paid = paid_on_average(tenant, today)
    pay = _pay_category(ledger)
    return {**need, "paid": paid,
            "difference_cents": (None if need["needed_cents"] is None
                                 or paid["average_cents"] is None
                                 else paid["average_cents"] - need["needed_cents"]),
            "pay_category": pay.name if pay is not None else "",
            "matched": PersonalLine.objects.filter(
                ledger=ledger, removed_at__isnull=True, draw_entry__isnull=False,
                on_date__gte=_months_back(today, AVERAGE_MONTHS)).count(),
            "forecasting": modules.has(tenant, modules.FORECAST),
            "business_line": business_line(tenant)}


@transaction.atomic
def set_business_line(ledger, tenant, *, actor, amount_cents) -> dict:
    """The owner's press: the business forecast's pay-yourself line becomes
    `amount_cents` a month from today. An adjustment of the line it found
    (source "personal", undone there like any other), or, with no draws
    found yet, a planned line repeating monthly."""
    from apps.finance import forecast as business
    from apps.finance.services import FinanceError

    if isinstance(amount_cents, bool) or not isinstance(amount_cents, int) \
            or amount_cents <= 0:
        raise PersonalError("The amount is a whole number of cents, more than nothing.")
    line = business_line(tenant)
    if line is None:
        raise PersonalError("The cash forecast is its own module, which this practice "
                            "does not have.", status=409)
    try:
        if line["group"]:
            business.adjust(tenant, actor=actor, group=line["group"], kind="amount",
                            amount_cents=amount_cents, source="personal")
        else:
            today = timezone.localdate()
            last = draws(tenant).last()
            day = last.on_date.day if last is not None else 28
            month = _months_back(today, -1)
            business.save_planned(
                tenant, actor=actor, description="Pay yourself", direction=D.OUT,
                amount_cents=amount_cents, repeat="monthly",
                on_date=month.replace(day=min(day, 28)))
    except FinanceError as exc:
        raise PersonalError(str(exc), status=getattr(exc, "status", 400)) from None
    return loop(ledger, tenant)
