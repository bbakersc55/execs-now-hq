"""Debts and the payoff plan (P6 M4 stop 3, decision 16).

- **A debt** has a name, a kind, a rate, a minimum, a due day and whose it
  is. Its balance is the newest one entered (monthly, or from a statement);
  a card that is also an imported household account takes its balance from
  the import instead.
- **The plan** is arithmetic, month by month from this one: interest at a
  twelfth of the yearly rate on what is owed, every minimum paid, and the
  extra a month (with each paid-off debt's minimum added to it) going to one
  debt at a time in the plan's order: **smallest balance first** (the
  default) or **highest rate first** (`ORDER_NAMES`; renamed from Snowball
  and Avalanche on 2026-10-19, the codes kept). The order is set
  from today's balances and kept. Each debt's payoff date and the interest
  paid on the way are worked out, and the same for the other order, so the
  screen can say what it would cost or save.
- **The extra becomes an envelope** in "Debt payments" (stop 2's budget),
  and the payments are Known lines on the personal forecast.

Nothing here asks Claude for anything, and nothing is advice: these are
estimates on the owner's own figures.
"""

from __future__ import annotations

import calendar
from datetime import date

from django.db import transaction
from django.utils import timezone

from apps.personal.models import (
    PersonalBalance, PersonalCategory, PersonalDebt, PersonalEnvelope, PersonalMember,
)
from apps.personal.services import PersonalError

ORDERS = ("snowball", "avalanche")
#: What people read, on screen and in what is sent to Claude (2026-10-19).
#: The codes stay in the data.
ORDER_NAMES = {"snowball": "Smallest balance first", "avalanche": "Highest rate first"}
BAD_ORDER = ("The order is smallest balance first (\"snowball\") or highest rate first "
             "(\"avalanche\").")
#: The plan stops looking after this many months: a debt not paid off by
#: then is "not at this payment".
MOST_MONTHS = 600
DEBT_PAYMENTS = "Debt payments"


# ------------------------------------------------------------------ dates

def _month(today: date, n: int) -> date:
    index = today.year * 12 + today.month - 1 + n
    return date(index // 12, index % 12 + 1, 1)


def due_on(month: date, day: int | None) -> date:
    """The debt's due day in that month, the month's last day if it is short."""
    day = day or 1
    return month.replace(day=min(day, calendar.monthrange(month.year, month.month)[1]))


# --------------------------------------------------------------- balances

def open_debts(ledger, *, whose="all"):
    rows = PersonalDebt.objects.filter(ledger=ledger, closed_at__isnull=True)\
        .select_related("whose", "account", "category")
    if whose != "all":
        rows = rows.filter(whose=whose)
    return rows


def balance_of(debt, as_of: date | None = None) -> tuple[int, date | None, str]:
    """`(cents owed, as of, where it came from)`. A card that is an imported
    account: what the import says is owed. Otherwise the newest balance
    entered on or before `as_of`."""
    from apps.personal import reconcile

    if debt.account_id:
        if as_of is not None and as_of < debt.account.opening_on:
            return 0, None, "import"
        return reconcile.balance(debt.account, as_of), as_of or timezone.localdate(), "import"
    rows = PersonalBalance.objects.filter(debt=debt)
    if as_of is not None:
        rows = rows.filter(on_date__lte=as_of)
    newest = rows.order_by("-on_date", "-created_at").first()
    if newest is None:
        return 0, None, "none"
    return newest.balance_cents, newest.on_date, "entered"


def history(debt, today: date) -> list[dict]:
    """What it was owed at each month end it has a balance for (or, for an
    imported card, each month end of the last twelve), oldest first."""
    if debt.account_id:
        out = []
        for n in range(-12, 1):
            month = _month(today, n)
            end = today if n == 0 else due_on(month, 31)
            if end < debt.account.opening_on:
                continue
            cents, _on, _source = balance_of(debt, end)
            out.append({"on_date": end.isoformat(), "cents": cents})
        return out
    return [{"on_date": row.on_date.isoformat(), "cents": row.balance_cents}
            for row in PersonalBalance.objects.filter(debt=debt).order_by("on_date")]


# ------------------------------------------------------------------- plan

def _ordered(rows: list[dict], order: str) -> list[dict]:
    if order == "avalanche":
        return sorted(rows, key=lambda r: (-r["rate"], r["balance"], r["name"]))
    return sorted(rows, key=lambda r: (r["balance"], -r["rate"], r["name"]))


def simulate(rows: list[dict], *, order: str, extra: int, today: date) -> dict:
    """Month by month from this one. `rows` are `{"id", "name", "balance",
    "rate" (yearly percent), "minimum", "due_day"}`. Returns each debt's
    payments by month, its payoff month and interest, and the totals."""
    owed = {r["id"]: r["balance"] for r in rows}
    interest = {r["id"]: 0 for r in rows}
    payments = {r["id"]: [] for r in rows}         # [(month index, cents)]
    balances = {r["id"]: [] for r in rows}         # [(month index, cents after)]
    paid_off: dict = {}
    targets = _ordered(rows, order)
    freed = 0                                      # minimums of debts paid off
    month = 0
    while any(cents > 0 for cents in owed.values()) and month < MOST_MONTHS:
        spare = extra + freed
        paid = {}
        for r in rows:
            if owed[r["id"]] <= 0:
                continue
            charge = round(owed[r["id"]] * r["rate"] / 1200)
            owed[r["id"]] += charge
            interest[r["id"]] += charge
            pay = min(r["minimum"], owed[r["id"]])
            owed[r["id"]] -= pay
            paid[r["id"]] = pay
            spare += r["minimum"] - pay            # a last payment smaller than the minimum
        for r in targets:
            if spare <= 0:
                break
            if owed[r["id"]] <= 0:
                continue
            more = min(spare, owed[r["id"]])
            owed[r["id"]] -= more
            paid[r["id"]] = paid.get(r["id"], 0) + more
            spare -= more
        for r in rows:
            if r["id"] in paid:
                payments[r["id"]].append((month, paid[r["id"]]))
                balances[r["id"]].append((month, owed[r["id"]]))
                if owed[r["id"]] <= 0 and r["id"] not in paid_off:
                    paid_off[r["id"]] = month
                    freed += r["minimum"]
        month += 1
    debts = {}
    for r in rows:
        when = paid_off.get(r["id"])
        debts[r["id"]] = {
            "payoff_month": when,
            "payoff_on": due_on(_month(today, when), r["due_day"]) if when is not None
            else None,
            "interest_cents": interest[r["id"]] if when is not None else None,
            "payments": payments[r["id"]], "balances": balances[r["id"]]}
    done = all(d["payoff_month"] is not None for d in debts.values())
    last = max((d["payoff_month"] for d in debts.values()
                if d["payoff_month"] is not None), default=None)
    return {"debts": debts, "order": [r["id"] for r in targets],
            "all_paid": done,
            "debt_free_on": (due_on(_month(today, last), 1) if done and last is not None
                             else None),
            "interest_cents": sum(interest.values()) if done else None}


def _rows(ledger, today: date) -> list[dict]:
    out = []
    for debt in open_debts(ledger):
        cents, _on, _source = balance_of(debt)
        if cents <= 0:
            continue
        out.append({"id": str(debt.pk), "name": debt.name, "balance": cents,
                    "rate": float(debt.rate_percent or 0),
                    "minimum": debt.minimum_cents or 0, "due_day": debt.due_day or 1})
    return out


def plan(ledger, *, order: str | None = None, extra: int | None = None,
         today: date | None = None) -> dict:
    """The plan as the owner has it (or as `order` and `extra` would make
    it: a look, nothing saved), the other order beside it, and the plan
    without the extra."""
    today = today or timezone.localdate()
    order = order or ledger.payoff_order
    extra = ledger.payoff_extra_cents if extra is None else extra
    rows = _rows(ledger, today)
    other = "avalanche" if order == "snowball" else "snowball"
    mine = simulate(rows, order=order, extra=extra, today=today)
    theirs = simulate(rows, order=other, extra=extra, today=today)
    bare = simulate(rows, order=order, extra=0, today=today)
    return {"order": order, "extra_cents": extra, "rows": rows, "mine": mine,
            "other_order": other, "other": theirs, "without_extra": bare}


def _difference(mine: dict, theirs: dict) -> dict:
    """What `theirs` would cost (+) or save (-) against `mine`."""
    if mine["interest_cents"] is None or theirs["interest_cents"] is None:
        return {"interest_cents": None, "months": None}
    months = None
    if mine["debt_free_on"] and theirs["debt_free_on"]:
        a, b = mine["debt_free_on"], theirs["debt_free_on"]
        months = (b.year - a.year) * 12 + b.month - a.month
    return {"interest_cents": theirs["interest_cents"] - mine["interest_cents"],
            "months": months}


def represent(ledger, today: date | None = None, *, whose="all", order=None,
              extra=None) -> dict:
    """The Debts page: each debt with its balance, payoff date and interest
    under the plan, a balance-over-time series (entered, then the plan's), and
    the plan's totals against the other order and against no extra."""
    today = today or timezone.localdate()
    found = plan(ledger, order=order, extra=extra, today=today)
    mine = found["mine"]
    position = {pk: n + 1 for n, pk in enumerate(mine["order"])}
    debts = []
    for debt in open_debts(ledger, whose=whose):
        cents, on, source = balance_of(debt)
        sim = mine["debts"].get(str(debt.pk))
        projected = []
        if sim is not None:
            projected = [{"on_date": due_on(_month(today, m), debt.due_day).isoformat(),
                          "cents": max(0, c)} for m, c in sim["balances"][:360]]
        debts.append({
            "id": str(debt.pk), "name": debt.name, "kind": debt.kind,
            "kind_label": debt.get_kind_display(),
            "whose": str(debt.whose_id) if debt.whose_id else None,
            "whose_name": debt.whose.name if debt.whose_id else "Joint",
            "balance_cents": cents, "balance_on": on.isoformat() if on else None,
            "balance_source": source,
            "rate_percent": str(debt.rate_percent) if debt.rate_percent is not None else None,
            "minimum_cents": debt.minimum_cents, "due_day": debt.due_day,
            "account": ({"id": str(debt.account_id), "name": debt.account.name}
                        if debt.account_id else None),
            "category": ({"id": str(debt.category_id), "name": debt.category.name}
                         if debt.category_id else None),
            "plan_position": position.get(str(debt.pk)),
            "payoff_on": (sim["payoff_on"].isoformat() if sim and sim["payoff_on"]
                          else None),
            "interest_cents": sim["interest_cents"] if sim else None,
            "never": bool(sim) and sim["payoff_on"] is None,
            "history": history(debt, today), "projected": projected,
        })
    bare = found["without_extra"]
    return {
        "order": found["order"], "other_order": found["other_order"],
        "order_label": ORDER_NAMES[found["order"]],
        "other_order_label": ORDER_NAMES[found["other_order"]],
        "extra_cents": found["extra_cents"],
        "saved_extra_cents": ledger.payoff_extra_cents, "saved_order": ledger.payoff_order,
        "total_cents": sum(r["balance"] for r in found["rows"]),
        "minimums_cents": sum(r["minimum"] for r in found["rows"]),
        "debt_free_on": mine["debt_free_on"].isoformat() if mine["debt_free_on"] else None,
        "interest_cents": mine["interest_cents"],
        # Decision 16: what the other order would cost (+) or save (-).
        "other": {**_difference(mine, found["other"]),
                  "debt_free_on": (found["other"]["debt_free_on"].isoformat()
                                   if found["other"]["debt_free_on"] else None)},
        "extra_saves": {**_difference(mine, bare),
                        "debt_free_on": (bare["debt_free_on"].isoformat()
                                         if bare["debt_free_on"] else None)},
        "debts": debts,
    }


def payments(ledger, today: date, end: date) -> list[dict]:
    """`[{debt, on_date, cents, minimum}]`: each open debt's payments under
    the plan, from this month to `end`, on its due day. The forecast's Known
    lines."""
    found = plan(ledger, today=today)
    by_id = {str(d.pk): d for d in open_debts(ledger)}
    out = []
    for pk, sim in found["mine"]["debts"].items():
        debt = by_id[pk]
        for month, cents in sim["payments"]:
            on = due_on(_month(today, month), debt.due_day)
            if on > end:
                break
            out.append({"debt": debt, "on_date": on, "cents": cents,
                        "minimum": min(cents, debt.minimum_cents or 0)})
    return out


# --------------------------------------------------------------- changing

def _whose(ledger, pk):
    if not pk:
        return None
    found = PersonalMember.objects.filter(ledger=ledger, pk=pk, removed_at__isnull=True).first()
    if found is None:
        raise PersonalError("That person is not in your household.", status=404)
    return found


FIELDS = ("name", "kind", "whose", "rate_percent", "minimum_cents", "due_day", "account",
          "category")


@transaction.atomic
def save(ledger, *, debt=None, data: dict) -> PersonalDebt:
    from decimal import Decimal, InvalidOperation

    from apps.personal.models import PersonalAccount

    made = debt is None
    debt = debt or PersonalDebt(ledger=ledger)
    if "name" in data or made:
        debt.name = " ".join(str(data.get("name") or "").split())[:120]
        if not debt.name:
            raise PersonalError("Give the debt a name.")
    if "kind" in data or made:
        debt.kind = data.get("kind") or "other"
        if debt.kind not in PersonalDebt.Kind.values:
            raise PersonalError("That is not a kind of debt.")
    if "whose" in data:
        debt.whose = _whose(ledger, data["whose"])
    if "rate_percent" in data:
        value = data["rate_percent"]
        try:
            rate = None if value in (None, "") else Decimal(str(value))
        except InvalidOperation:
            raise PersonalError("The rate is a percent, like 6.125.") from None
        if rate is not None and not Decimal("0") <= rate <= Decimal("99"):
            raise PersonalError("The rate is a percent from 0 to 99.")
        debt.rate_percent = rate
    for field, what in (("minimum_cents", "The minimum payment"),):
        if field in data:
            value = data[field]
            if value in (None, ""):
                setattr(debt, field, None)
            elif isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise PersonalError(f"{what} is a whole number of cents, zero or more.")
            else:
                setattr(debt, field, value)
    if "due_day" in data:
        day = data["due_day"]
        if day in (None, ""):
            debt.due_day = None
        elif isinstance(day, bool) or not isinstance(day, int) or not 1 <= day <= 31:
            raise PersonalError("The due day is from 1 to 31.")
        else:
            debt.due_day = day
    if "account" in data:
        account = None
        if data["account"]:
            account = PersonalAccount.objects.filter(ledger=ledger, pk=data["account"],
                                                     kind="card").first()
            if account is None:
                raise PersonalError("Choose one of your own card accounts.", status=404)
        debt.account = account
    if "category" in data:
        category = None
        if data["category"]:
            category = PersonalCategory.objects.filter(ledger=ledger, pk=data["category"],
                                                       type="expense").first()
            if category is None:
                raise PersonalError("Choose one of your spending categories.", status=404)
        debt.category = category
    debt.save()
    if made and data.get("balance_cents") not in (None, ""):
        add_balance(debt, on_date=timezone.localdate(), cents=data["balance_cents"])
    return debt


def add_balance(debt, *, on_date: date, cents) -> PersonalBalance:
    """A balance entered by hand or from a statement. A card that is an
    imported account takes its balance from there instead."""
    if debt.account_id:
        raise PersonalError(f"{debt.name} takes its balance from its imported statements.",
                            status=409)
    if isinstance(cents, bool) or not isinstance(cents, int) or cents < 0:
        raise PersonalError("A balance is a whole number of cents, zero or more.")
    if on_date > timezone.localdate():
        raise PersonalError("A balance is for today or a day before.")
    return PersonalBalance.objects.create(ledger=debt.ledger, debt=debt, on_date=on_date,
                                          balance_cents=cents)


def close(debt) -> None:
    debt.closed_at = timezone.now()
    debt.save(update_fields=["closed_at", "updated_at"])


@transaction.atomic
def set_plan(ledger, *, order: str | None = None, extra: int | None = None) -> None:
    """Save the order and the extra. The extra is an envelope in "Debt
    payments" (decision 16): made, changed by the difference, or put away."""
    from apps.personal import budget

    if order is not None:
        if order not in ORDERS:
            raise PersonalError(BAD_ORDER)
        ledger.payoff_order = order
    before = ledger.payoff_extra_cents
    if extra is not None:
        if isinstance(extra, bool) or not isinstance(extra, int) or extra < 0:
            raise PersonalError("The extra is a whole number of cents, zero or more.")
        ledger.payoff_extra_cents = extra
    ledger.save(update_fields=["payoff_order", "payoff_extra_cents", "updated_at"])
    if extra is None or extra == before or not budget.has_budget(ledger):
        return
    category = PersonalCategory.objects.filter(ledger=ledger, name=DEBT_PAYMENTS,
                                               parent__isnull=True,
                                               archived_at__isnull=True).first()
    if category is None:
        return
    env = budget.envelopes(ledger).filter(category=category).first()
    if env is None:
        if extra > 0:
            PersonalEnvelope.objects.create(
                ledger=ledger, category=category, kind=PersonalEnvelope.Kind.EVERYDAY,
                planned_cents=extra, source=PersonalEnvelope.Source.DEBT,
                start_month=budget.this_month(),
                position=budget.envelopes(ledger).count())
        return
    if env.source == PersonalEnvelope.Source.DEBT and extra == 0:
        env.archived_at = timezone.now()
        env.save(update_fields=["archived_at", "updated_at"])
        return
    # An envelope the category had already (from history, or typed): the
    # extra is added to it, by the difference.
    env.planned_cents = max(0, env.planned_cents + extra - before)
    env.save(update_fields=["planned_cents", "updated_at"])
