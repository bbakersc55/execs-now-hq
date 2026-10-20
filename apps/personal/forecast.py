"""The personal cash forecast (P6 M4 stop 3, decision 15): M2's engine on the
household's own accounts.

"How much is the household likely to have in its accounts, week by week, if
pay comes as it has been coming and spending goes on as it has been going."

What it keeps true, as M2 does (`apps/finance/forecast.py`, whose table,
spans and summaries it uses):

- **Arithmetic on the owner's own lines.** Every figure is a sum of lines,
  and every line says where it came from. Nothing here asks Claude.
- **Never stored.** Worked out each time; what is kept is what the owner
  said (the floor, planned lines and what-ifs, adjustments) and one snapshot
  a month for "How good it has been".
- **Cash is the household's bank and cash accounts.** A card is not cash:
  what is charged on one leaves cash when the card is paid, so a card's
  payment is drawn as it has been paid (a Regular line) and its charges are
  not. A Mixed card is the practice's account; its payment from joint
  checking is the household's, and is drawn the same way.
- **Known:** pay from the practice at the cadence it has been paid; each
  debt's payment under the payoff plan on its due day; each yearly bill the
  budget spreads, in its month; estimated tax on the IRS dates.
- **Regular:** found in the complete months, by category and payee, as M2
  finds them (monthly when seen in two of the last three, quarterly when
  about three months apart). Spouse pay is one of these. A move between two
  of the household's cash accounts is neither in nor out.
- **Planned:** goals with a date (the target, spent that day) and the
  owner's one-offs, once or repeating. A what-if is drawn beside the
  forecast when tried, and never counted.
- **Never in the same chart as the business forecast** (decision 15): this
  module reads only the ledger. The Overview sets the two sides' ending
  balances side by side, as numbers.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from statistics import median

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.finance.forecast import (
    MONTHS, REPEAT_MONTHS, STALE_DAYS, TAX_DATES, VIEWS, _add_months, _long, _money,
    _months_between, _ordinal, _rows, _spans, _summary,
)
from apps.personal import budget, debts, reconcile, services
from apps.personal.models import (
    PersonalAccount, PersonalCategory, PersonalEnvelope, PersonalForecastAdjustment,
    PersonalForecastSnapshot, PersonalGoal, PersonalLine, PersonalPlanned,
    PersonalReconciliation,
)
from apps.personal.services import PAY_FROM_PRACTICE, PersonalError

#: Complete months of lines needed before anything is forecast from history.
MONTHS_NEEDED = 2
#: How far back the forecast reads for what is regular: far enough to see a
#: quarterly bill three times.
READ_MONTHS = 12
CASH = (PersonalAccount.Kind.BANK, PersonalAccount.Kind.CASH)
TAXES = "Taxes"
NOT_READY = ("Import two complete months of your accounts' statements and your regular "
             "spending will be forecast from them. Until then this is only what is known "
             "and what you have planned.")


# ------------------------------------------------------------- where it starts

def cash_accounts(ledger):
    return PersonalAccount.objects.filter(ledger=ledger, kind__in=CASH,
                                          closed_at__isnull=True).order_by("name")


def _accounts(ledger, today: date) -> tuple[list[dict], int]:
    rows, total = [], 0
    for account in cash_accounts(ledger):
        if account.opening_on > today:
            continue
        cents = reconcile.balance(account, today)
        last = PersonalLine.objects.filter(account=account, removed_at__isnull=True,
                                           on_date__lte=today).aggregate(m=Max("on_date"))["m"]
        through = PersonalReconciliation.objects.filter(
            account=account, state="finished").aggregate(m=Max("statement_on"))["m"]
        rows.append({
            "id": str(account.pk), "name": account.name, "kind": account.kind,
            "amount_cents": cents, "last_entry_on": last.isoformat() if last else None,
            "reconciled_through": through.isoformat() if through else None,
            "stale": last is None or (today - last).days > STALE_DAYS})
        total += cents
    return rows, total


# ------------------------------------------------------------------ the lines

def _cash_lines(ledger, start: date, stop: date):
    """Lines in the household's cash accounts between two days, less the
    moves between two of them (neither in nor out)."""
    cash = set(cash_accounts(ledger).values_list("pk", flat=True))
    rows = (PersonalLine.objects.filter(
        ledger=ledger, removed_at__isnull=True, account_id__in=cash,
        on_date__gte=start, on_date__lte=stop)
        .select_related("category", "category__parent", "transfer_pair")
        .order_by("on_date", "created_at"))
    return [line for line in rows
            if not (line.transfer_pair_id and line.transfer_pair.account_id in cash)]


def _who(line) -> str:
    return " ".join(re.sub(r"\d+", " ", (line.description or "").lower()).split())


def _key(line) -> tuple:
    return (line.direction, line.category_id, line.account_id, _who(line))


def _group(key) -> str:
    return "pattern:" + "|".join(str(part or "") for part in key)


def category_name(category) -> str:
    if category is None:
        return ""
    return f"{category.parent.name}: {category.name}" if category.parent_id else category.name


def _label(line) -> str:
    return (line.description or category_name(line.category) or "A line").strip()


def complete_months(ledger, today: date) -> list[date]:
    """The months before this one, of the last twelve, that have any line in
    a household cash account: what the forecast reads for what is regular."""
    this = today.replace(day=1)
    found = {line.on_date.replace(day=1) for line in _cash_lines(
        ledger, _add_months(this, -READ_MONTHS, 1), this - timedelta(days=1))}
    return sorted(found)


def _known_categories(ledger) -> dict:
    """`{category id: why}` for the categories whose lines are Known, not
    Regular: pay from the practice, each debt's payments, each yearly bill
    spread, and estimated tax."""
    out = {}
    pay = PersonalCategory.objects.filter(ledger=ledger, system_code=PAY_FROM_PRACTICE).first()
    if pay is not None:
        out[pay.pk] = "pay"
    for debt in debts.open_debts(ledger).exclude(category=None):
        if not debt.account_id:
            out[debt.category_id] = "debt"
    for env in budget.envelopes(ledger).exclude(yearly_cents=None).exclude(category=None):
        out[env.category_id] = "yearly"
    for category in PersonalCategory.objects.filter(ledger=ledger, type="expense")\
            .select_related("parent"):
        if TAXES in (category.name, category.parent.name if category.parent_id else ""):
            out[category.pk] = "tax"
    return out


def _line(*, id, group, kind, direction, cents, on, label, detail, category="",
          cadence="", link="/finance/personal/forecast", counted=True, what_if=False) -> dict:
    return {"id": id, "group": group, "kind": kind, "direction": direction,
            "amount_cents": cents, "on_date": on, "label": label, "detail": detail,
            "category": category, "cadence": cadence, "link": link, "counted": counted,
            "what_if": what_if, "adjusted": "", "adjustment": ""}


class _Pattern:
    def __init__(self, line):
        self.line, self.by_month, self.days, self.items = line, {}, {}, {}
        self.last_on, self.last_amount = line.on_date, line.amount_cents

    def add(self, line) -> None:
        month = line.on_date.replace(day=1)
        self.by_month[month] = self.by_month.get(month, 0) + line.amount_cents
        self.days.setdefault(month, line.on_date.day)
        self.items.setdefault(month, []).append((line.on_date.day, line.amount_cents))
        if line.on_date >= self.last_on:
            self.line, self.last_on, self.last_amount = line, line.on_date, line.amount_cents


def patterns(ledger, months: list[date]) -> dict:
    """Every category-and-payee of these months in the cash accounts, but
    the Known ones, with what it came to in each month."""
    if not months:
        return {}
    known = _known_categories(ledger)
    found: dict = {}
    for line in _cash_lines(ledger, months[0], _add_months(months[-1], 1, 1)
                            - timedelta(days=1)):
        if line.category_id in known or line.on_date.replace(day=1) not in months:
            continue
        found.setdefault(_key(line), _Pattern(line)).add(line)
    return found


def _regular(ledger, today: date, end: date, months: list[date]) -> list[dict]:
    last3, last12 = months[-3:], months[-12:]
    found = patterns(ledger, months)
    this = today.replace(day=1)
    entered: dict = {}
    for line in _cash_lines(ledger, this, today):
        found_key = (_key(line), line.on_date.replace(day=1))
        entered[found_key] = entered.get(found_key, 0) + 1
    lines = []

    def make(key, pattern, on, cents, cadence, detail, n=0):
        line = pattern.line
        group = _group(key)
        return _line(id=f"{group}:{on}" + (f":{n}" if n else ""), group=group, kind="regular",
                     direction=line.direction, cents=cents, on=on, label=_label(line),
                     detail=detail, category=category_name(line.category), cadence=cadence,
                     link=(f"/finance/personal/entries?category={line.category_id}"
                           if line.category_id else "/finance/personal/entries"))

    for key, pattern in found.items():
        in3 = [m for m in last3 if m in pattern.by_month]
        in12 = sorted(m for m in last12 if m in pattern.by_month)
        if len(in3) >= 2:
            # As many times a month as it usually comes (pay twice a month is
            # two lines, not one on the 1st), each on the median of its day.
            times = max(1, int(median(len(pattern.items[m]) for m in in3)))
            if times == 1:
                amounts = [pattern.by_month[m] for m in in3]
                fixed = len(set(amounts)) == 1
                slots = [(int(median(pattern.days[m] for m in in3)),
                          amounts[0] if fixed else int(median(amounts)))]
                how = "the same amount" if fixed else "the median"
            else:
                slots = []
                for n in range(times):
                    found_n = [sorted(pattern.items[m])[n] for m in in3
                               if len(pattern.items[m]) > n]
                    slots.append((int(median(day for day, _c in found_n)),
                                  int(median(cents for _d, cents in found_n))))
                how = "the median"
            when = " and ".join(f"{_money(cents)} on the {_ordinal(day)}"
                                for day, cents in slots)
            detail = (f"{when}, " + ("monthly" if times == 1 else f"{times} times a month")
                      + f": {how} of {len(in3)} of the last {len(last3)} complete months.")
            cadence = "monthly" if times == 1 else f"{times} a month"
            month = this
            while month <= end:
                already = entered.get((key, month), 0)
                for n, (day, cents) in enumerate(slots):
                    on = max(_add_months(month, 0, day), today)
                    if n >= already and on <= end:
                        lines.append(make(key, pattern, on, cents, cadence, detail, n))
                month = _add_months(month, 1, 1)
            continue
        gaps = [_months_between(a, b) for a, b in zip(in12, in12[1:])]
        if len(in12) >= 2 and all(2 <= gap <= 4 for gap in gaps):
            cents, day = pattern.last_amount, pattern.last_on.day
            detail = (f"{_money(cents)}, quarterly: seen {len(in12)} times in the last "
                      f"{len(last12)} complete months, about three months apart, last on "
                      f"{_long(pattern.last_on)}.")
            on = _add_months(pattern.last_on, 3, day)
            while on <= end:
                if on >= today and (key, on.replace(day=1)) not in entered:
                    lines.append(make(key, pattern, on, cents, "quarterly", detail))
                on = _add_months(on, 3, day)
    return lines


# --------------------------------------------------------------- known lines

def _pay(ledger, today: date, end: date, months: list[date], tenant=None) -> list[dict]:
    """Pay from the practice, at the cadence it has been paid: as many times
    a month as the last three complete months show (the median), each on
    the median of its day, at the median of its amount. Decision 20: a draw
    in the practice's books that no line of a household account was matched
    to (its account is not imported) is pay too, on the day it was drawn."""
    from apps.personal import paydays

    category = PersonalCategory.objects.filter(ledger=ledger,
                                               system_code=PAY_FROM_PRACTICE).first()
    if tenant is not None and len(months) < 3:
        # The books know the months even when no household account is in.
        this_one = today.replace(day=1)
        months = sorted(set(months) | {_add_months(this_one, -n, 1) for n in (1, 2, 3)})
    last3 = months[-3:]
    if category is None or not last3:
        return []
    cash = set(cash_accounts(ledger).values_list("pk", flat=True))
    rows = list(PersonalLine.objects.filter(
        ledger=ledger, removed_at__isnull=True, category=category, direction="in",
        account_id__in=cash, on_date__gte=last3[0], on_date__lte=today)
        .order_by("on_date", "created_at"))
    drawn = []
    if tenant is not None:
        matched = PersonalLine.objects.filter(removed_at__isnull=True,
                                              draw_entry__isnull=False)\
            .values_list("draw_entry_id", flat=True)
        drawn = list(paydays.draws(tenant, start=last3[0], end=today)
                     .exclude(pk__in=matched))
    rows = sorted(rows + drawn, key=lambda row: row.on_date)
    by_month: dict = {}
    for line in rows:
        by_month.setdefault(line.on_date.replace(day=1), []).append(line)
    counts = [len(by_month.get(m, [])) for m in last3]
    times = int(median(counts)) if counts else 0
    if times == 0:
        return []
    slots = []
    for n in range(times):
        found = [by_month[m][n] for m in last3 if len(by_month.get(m, [])) > n]
        slots.append((int(median(line.on_date.day for line in found)),
                      int(median(line.amount_cents for line in found))))
    days = " and ".join(f"the {_ordinal(day)}" for day, _cents in slots)
    how = {1: "once a month", 2: "twice a month"}.get(times, f"{times} times a month")
    this = today.replace(day=1)
    already = len(by_month.get(this, []))
    lines, month = [], this
    while month <= end:
        for n, (day, cents) in enumerate(slots):
            if month == this and n < already:
                continue                     # already in for this month
            on = max(_add_months(month, 0, day), today)
            if on > end:
                continue
            lines.append(_line(
                id=f"pay:{on.isoformat()}:{n}", group="pay", kind="known", direction="in",
                cents=cents, on=on, label=category.name, category=category.name,
                cadence="monthly" if times == 1 else f"{times} a month",
                detail=(f"{_money(cents)} {how}, around {days}: the median of the last "
                        f"{len(last3)} complete months, as you have been paying yourself."),
                link="/finance/personal/entries"))
        month = _add_months(month, 1, 1)
    return lines


def _debt_payments(ledger, today: date, end: date) -> list[dict]:
    """Each debt's payment under the payoff plan, on its due day. This
    month's is left out once a line in its category is in; one whose day has
    passed with no line is drawn today."""
    this = today.replace(day=1)
    lines = []
    for row in debts.payments(ledger, today, end):
        debt = row["debt"]
        if debt.account_id:
            continue      # a card is paid as it has been paid: a Regular line
        on = row["on_date"]
        if on.replace(day=1) == this:
            paid = debt.category_id and PersonalLine.objects.filter(
                ledger=ledger, removed_at__isnull=True, category_id=debt.category_id,
                direction="out", on_date__gte=this, on_date__lte=today).exists()
            if paid or (on < today and not debt.category_id):
                continue
            on = max(on, today)
        extra = row["cents"] - row["minimum"]
        lines.append(_line(
            id=f"debt:{debt.pk}:{on.isoformat()}", group=f"debt:{debt.pk}", kind="known",
            direction="out", cents=row["cents"], on=on, label=f"{debt.name} payment",
            category=category_name(debt.category) if debt.category_id else "Debt payments",
            cadence="monthly", link="/finance/personal/debts",
            detail=(f"The minimum, {_money(row['minimum'])}, on the "
                    f"{_ordinal(debt.due_day or 1)}"
                    + (f", and {_money(extra)} of the plan's extra" if extra > 0 else "")
                    + ": your payoff plan.")))
    return lines


def _yearly(ledger, today: date, end: date) -> list[dict]:
    """Each yearly bill the budget spreads, in its month, on the day it was
    last paid (the 15th if none is found)."""
    lines = []
    for env in budget.envelopes(ledger).exclude(yearly_cents=None).exclude(category=None):
        last = PersonalLine.objects.filter(
            ledger=ledger, removed_at__isnull=True, category_id=env.category_id,
            direction="out").order_by("-on_date").first()
        day = last.on_date.day if last else 15
        month = env.yearly_month or (last.on_date.month if last else today.month)
        for year in (today.year, today.year + 1):
            on = _add_months(date(year, month, 1), 0, day)
            if not today <= on <= end:
                continue
            if last and (on - last.on_date).days < 300:
                continue                     # paid already for this year
            lines.append(_line(
                id=f"yearly:{env.pk}:{on.isoformat()}", group=f"yearly:{env.pk}",
                kind="known", direction="out", cents=env.yearly_cents, on=on,
                label=env.category.name, category=category_name(env.category),
                cadence="yearly", link="/finance/personal",
                detail=(f"A yearly bill of {_money(env.yearly_cents)}, spread monthly in "
                        f"your budget: due in {on:%B}, as last time.")))
    return lines


def _estimated_tax(ledger, today: date, end: date) -> list[dict]:
    """Estimated tax paid from a household account: the last amount in each
    of the Taxes categories, on the dates it is due. One paid within a
    fortnight of a due date is not drawn again for it."""
    known = _known_categories(ledger)
    taxes = [pk for pk, why in known.items() if why == "tax"]
    if not taxes:
        return []
    cash = set(cash_accounts(ledger).values_list("pk", flat=True))
    rows = list(PersonalLine.objects.filter(
        ledger=ledger, removed_at__isnull=True, category_id__in=taxes, direction="out",
        account_id__in=cash, on_date__gte=_add_months(today, -12, 1), on_date__lte=today)
        .select_related("category").order_by("on_date"))
    latest = {}
    for line in rows:
        latest[line.category_id] = line
    lines = []
    for pk, line in latest.items():
        for year in range(today.year, end.year + 1):
            for month, day in TAX_DATES:
                due = date(year, month, day)
                if not today <= due <= end:
                    continue
                if any(r.category_id == pk and abs((r.on_date - due).days) <= 14
                       for r in rows):
                    continue
                lines.append(_line(
                    id=f"tax:{pk}:{due.isoformat()}", group=f"tax:{pk}", kind="known",
                    direction="out", cents=line.amount_cents, on=due,
                    label=line.category.name, category=category_name(line.category),
                    cadence="quarterly", link="/finance/personal/entries",
                    detail=(f"{_money(line.amount_cents)}, the last one paid "
                            f"({_long(line.on_date)}), on the date the next is due. "
                            "An estimate; confirm with your CPA.")))
    return lines


# ------------------------------------------------------------- planned lines

def _planned(ledger, today: date, end: date) -> tuple[list[dict], list[dict]]:
    """Goals with a date and the owner's one-offs. Returns `(lines, the
    planned items as the screen lists them)`."""
    lines, listed = [], []
    rows = PersonalPlanned.objects.filter(ledger=ledger, archived_at__isnull=True)\
        .select_related("goal")
    for row in rows:
        if row.goal_id and row.goal.archived_at is not None:
            continue
        step = REPEAT_MONTHS.get(row.repeat, 0)
        dates, on = [], row.on_date
        while on <= end:
            if on >= today:
                dates.append(on)
            if not step:
                break
            on = _add_months(on, step, row.on_date.day)
        lapsed = not step and row.on_date < today - timedelta(days=7)
        if not step and not lapsed and row.on_date < today:
            dates = [today]                  # just past: still expected
        state = "lapsed" if lapsed else "what_if" if row.is_what_if else "planned"
        listed.append({
            "id": str(row.pk), "description": row.name, "direction": row.direction,
            "amount_cents": row.amount_cents, "on_date": row.on_date.isoformat(),
            "repeat": row.repeat, "is_what_if": row.is_what_if, "state": state,
            "goal": str(row.goal_id) if row.goal_id else None,
            "next_on": dates[0].isoformat() if dates else None})
        for on in dates:
            lines.append(_line(
                id=f"planned:{row.pk}:{on.isoformat()}", group=f"planned:{row.pk}",
                kind="planned", direction=row.direction, cents=row.amount_cents, on=on,
                label=row.name, cadence=row.repeat, counted=not row.is_what_if,
                what_if=row.is_what_if,
                link="/finance/personal/goals" if row.goal_id else "/finance/personal/forecast",
                detail=("A what-if: drawn beside the forecast when you try it, not counted "
                        "in it." if row.is_what_if else
                        "A goal's target, spent on its date." if row.goal_id
                        else "Planned by you.")))
    return lines, listed


def goals_not_drawn(ledger) -> list[dict]:
    """Goals with no date: saved for, never spent on a day, so not a line."""
    return [{"id": str(goal.pk), "name": goal.name, "monthly_cents": budget.monthly_for(goal),
             "account": goal.account.name if goal.account_id else None}
            for goal in PersonalGoal.objects.filter(ledger=ledger, archived_at__isnull=True,
                                                    target_on__isnull=True)
            .select_related("account")]


# --------------------------------------------------------------- adjustments

def _adjustments(ledger) -> dict:
    found: dict = {}
    for row in PersonalForecastAdjustment.objects.filter(
            ledger=ledger, undone_at__isnull=True).order_by("created_at"):
        found.setdefault(row.line_key, []).append(row)
    return found


def _say(adj) -> str:
    if adj.kind == "not_regular":
        return "You said it is not regular."
    since = f" from {_long(adj.from_date)}" if adj.from_date else ""
    return f"You set it to {_money(adj.amount_cents or 0)}{since}."


def _apply(lines: list[dict], adjusted: dict, today: date) -> list[dict]:
    out = []
    for row in lines:
        mine = adjusted.get(row["group"], [])
        keep, said = True, []
        for adj in mine:
            if adj.kind == "not_regular":
                keep = False
            elif adj.kind == "amount" and row["on_date"] >= (adj.from_date or today):
                row = {**row, "amount_cents": adj.amount_cents}
                said.append(_say(adj))
        if keep:
            if said:
                row = {**row, "adjusted": " ".join(said), "adjustment": str(mine[-1].pk)}
            out.append(row)
    return out


# ---------------------------------------------------------------- the forecast

def _gather(ledger, today: date, *, adjusted: dict | None = None) -> dict:
    months = complete_months(ledger, today)
    ready = len(months) >= MONTHS_NEEDED
    _weeks, _months, end = _spans(today)
    adjusted = _adjustments(ledger) if adjusted is None else adjusted
    tenant = services.practice_of(ledger)
    known = (_pay(ledger, today, end, months, tenant) + _debt_payments(ledger, today, end)
             + _yearly(ledger, today, end) + _estimated_tax(ledger, today, end))
    regular = _apply(_regular(ledger, today, end, months), adjusted, today) if ready else []
    planned, listed = _planned(ledger, today, end)
    return {"months": months, "ready": ready, "end": end, "known": known,
            "regular": regular, "planned": planned, "planned_listed": listed,
            "adjusted": adjusted}


def _table(today: date, opening: int, floor, *, known, regular, planned) -> dict:
    weeks, months, _end = _spans(today)
    lines = sorted(known + regular + planned, key=lambda row: (row["on_date"], row["id"]))
    week_rows = _rows(weeks, opening, lines, floor)
    month_rows = _rows(months, opening, lines, floor)
    return {"lines": lines, "weeks": week_rows, "months": month_rows,
            "views": {**{days: _summary(week_rows[:count]) for days, count in VIEWS.items()},
                      "months": _summary(month_rows)}}


def _public(row: dict) -> dict:
    return {**row, "on_date": row["on_date"].isoformat()}


def build(ledger, today: date | None = None, *, what_if: dict | None = None,
          snapshot: bool = True) -> dict:
    """The whole personal forecast, from the lines as they are now."""
    from apps.personal.budget_ai import DISCLAIMER

    today = today or timezone.localdate()
    floor = ledger.forecast_floor_cents
    parts = _gather(ledger, today)
    accounts, opening = _accounts(ledger, today)
    table = _table(today, opening, floor, known=parts["known"], regular=parts["regular"],
                   planned=parts["planned"])
    if snapshot and parts["ready"]:
        _take_snapshot(ledger, today, table, opening)
    adjustments = [{"id": str(adj.pk), "group": adj.line_key, "label": adj.label,
                    "kind": adj.kind, "text": _say(adj), "source": adj.source,
                    "at": adj.created_at.isoformat()}
                   for rows in parts["adjusted"].values() for adj in rows]
    result = {
        "as_of": today.isoformat(), "ready": parts["ready"],
        "complete_months": len(parts["months"]),
        "note": "" if parts["ready"] else NOT_READY,
        "cash_today_cents": opening, "accounts": accounts, "floor_cents": floor,
        "weeks": table["weeks"], "months": table["months"], "views": table["views"],
        "lines": [_public(row) for row in table["lines"]],
        "planned": parts["planned_listed"], "goals_not_drawn": goals_not_drawn(ledger),
        "adjustments": sorted(adjustments, key=lambda row: row["at"], reverse=True),
        "history": history(ledger, today),
        "what_if": None, "disclaimer": DISCLAIMER,
    }
    if what_if:
        result["what_if"] = _what_if(today, parts, opening, floor, table, what_if)
    return result


def _what_if(today, parts, opening, floor, table, what_if: dict) -> dict:
    """The forecast with lines switched off, what-if lines switched on and
    amounts tried. A look: nothing is saved."""
    off = {str(item) for item in (what_if.get("off") or [])}
    on = {str(item) for item in (what_if.get("on") or [])}
    amounts = what_if.get("amounts") or {}
    if not isinstance(amounts, dict) or any(
            isinstance(c, bool) or not isinstance(c, int) or c < 0 for c in amounts.values()):
        raise PersonalError("amounts is a line and a whole number of cents to try for it.")

    def kept(rows):
        out = []
        for row in rows:
            if row["group"] in off:
                continue
            if row["group"] in amounts:
                row = {**row, "amount_cents": amounts[row["group"]]}
            if row["amount_cents"] > 0:
                out.append(row)
        return out

    planned = []
    for row in kept(parts["planned"]):
        if row["what_if"]:
            if row["group"].removeprefix("planned:") not in on:
                continue
            row = {**row, "counted": True}
        planned.append(row)
    other = _table(today, opening, floor, known=kept(parts["known"]),
                   regular=kept(parts["regular"]), planned=planned)
    return {"weeks": other["weeks"], "months": other["months"], "views": other["views"],
            "difference_at_low": {view: other["views"][view]["low_cents"]
                                  - table["views"][view]["low_cents"]
                                  for view in table["views"]},
            "off": sorted(off), "on": sorted(on), "amounts": amounts}


def groups(ledger, today: date | None = None) -> dict:
    """`{line key: what it is called}` for every Regular line before any
    adjustment: what an adjustment may name."""
    today = today or timezone.localdate()
    parts = _gather(ledger, today, adjusted={})
    return {row["group"]: row["label"] for row in parts["regular"]}


def ending(ledger, today: date | None = None, view: str = "90") -> dict | None:
    """The personal side's figure for the Overview: cash at the end of the
    view, and the low point. Takes no snapshot."""
    found = build(ledger, today, snapshot=False)
    summary = found["views"][view]
    return {"ready": found["ready"], "cash_today_cents": found["cash_today_cents"],
            "end_cents": summary["end_cents"], "low_cents": summary["low_cents"],
            "low_start": summary["low_start"]}


# ---------------------------------------------------- what the owner says

def set_floor(ledger, floor_cents) -> None:
    if floor_cents is not None and (isinstance(floor_cents, bool)
                                    or not isinstance(floor_cents, int)):
        raise PersonalError("The floor is a whole number of cents.")
    ledger.forecast_floor_cents = floor_cents
    ledger.save(update_fields=["forecast_floor_cents", "updated_at"])


def _a_day(value, what) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise PersonalError(f"{what} is a date, as YYYY-MM-DD.") from None


@transaction.atomic
def save_planned(ledger, *, planned=None, **fields) -> PersonalPlanned:
    """A one-off, a repeating line or a what-if. A goal's line follows its
    goal, and is changed there."""
    made = planned is None
    row = planned or PersonalPlanned(ledger=ledger)
    if row.goal_id:
        raise PersonalError("A goal's line follows the goal: change the goal.", status=409)
    if made and not {"name", "amount_cents", "on_date"} <= set(fields):
        raise PersonalError("A planned line has a name, an amount and a date.")
    if "name" in fields:
        row.name = " ".join(str(fields["name"] or "").split())[:120]
        if not row.name:
            raise PersonalError("Say what it is.")
    if "direction" in fields or made:
        row.direction = fields.get("direction") or "out"
        if row.direction not in ("in", "out"):
            raise PersonalError("direction is in or out.")
    if "amount_cents" in fields:
        cents = fields["amount_cents"]
        if isinstance(cents, bool) or not isinstance(cents, int) or cents <= 0:
            raise PersonalError("A planned line is for more than nothing, in whole cents.")
        row.amount_cents = cents
    if "on_date" in fields:
        row.on_date = _a_day(fields["on_date"], "The date")
    if "repeat" in fields:
        row.repeat = fields["repeat"] or ""
        if row.repeat and row.repeat not in REPEAT_MONTHS:
            raise PersonalError("repeat is monthly, quarterly, yearly, or nothing.")
    if "is_what_if" in fields:
        if not isinstance(fields["is_what_if"], bool):
            raise PersonalError("is_what_if is true or false.")
        row.is_what_if = fields["is_what_if"]
    row.save()
    return row


def remove_planned(row) -> None:
    if row.goal_id:
        raise PersonalError("A goal's line follows the goal: put the goal away instead.",
                            status=409)
    row.archived_at = timezone.now()
    row.save(update_fields=["archived_at", "updated_at"])


@transaction.atomic
def adjust(ledger, *, group, kind, amount_cents=None, from_date=None,
           source="") -> PersonalForecastAdjustment:
    known = groups(ledger)
    group = str(group or "")
    if group not in known:
        raise PersonalError("That line is not in your forecast.", status=404)
    if kind not in PersonalForecastAdjustment.Kind.values:
        raise PersonalError("kind is not_regular or amount.")
    row = PersonalForecastAdjustment(ledger=ledger, line_key=group, label=known[group][:255],
                                     kind=kind, source=source)
    if kind == "amount":
        if isinstance(amount_cents, bool) or not isinstance(amount_cents, int) \
                or amount_cents <= 0:
            raise PersonalError("An amount is more than nothing. Say it is not regular "
                                "instead.")
        row.amount_cents = amount_cents
        row.from_date = _a_day(from_date, "The date it starts") if from_date \
            else timezone.localdate()
    row.save()
    return row


def undo(adjustment) -> None:
    if adjustment.undone_at is not None:
        raise PersonalError("That was already undone.", status=409)
    adjustment.undone_at = timezone.now()
    adjustment.save(update_fields=["undone_at", "updated_at"])


# ------------------------------------------------------- how good it has been

def _by_name(rows: list[dict]) -> dict:
    found: dict = {}
    for row in rows:
        cell = found.setdefault(row["category"] or row["label"], {"in": 0, "out": 0})
        cell[row["direction"]] += row["amount_cents"]
    return found


def _take_snapshot(ledger, today: date, table: dict, opening: int) -> None:
    """This month's forecast as it stood the first time it was worked out in
    the month. Taken once, never changed."""
    month = today.replace(day=1)
    if PersonalForecastSnapshot.objects.filter(ledger=ledger, month=month).exists():
        return
    last = _add_months(month, 1, 1) - timedelta(days=1)
    mine = [row for row in table["lines"] if row["counted"] and row["on_date"] <= last]
    money_in = sum(row["amount_cents"] for row in mine if row["direction"] == "in")
    money_out = sum(row["amount_cents"] for row in mine if row["direction"] == "out")
    PersonalForecastSnapshot.objects.get_or_create(
        ledger=ledger, month=month, defaults={"taken_on": today, "forecast": {
            "start_cents": opening, "in_cents": money_in, "out_cents": money_out,
            "end_cents": opening + money_in - money_out, "by": _by_name(mine)}})


def _actual(ledger, snapshot) -> dict:
    """What happened to the household's cash in the snapshot's month after it
    was taken: the month's lines that were not in yet when it was (worked
    out each time: a statement often comes days after its month ends)."""
    month = snapshot.month
    last = _add_months(month, 1, 1) - timedelta(days=1)
    by: dict = {}
    money_in = money_out = 0
    for line in _cash_lines(ledger, month, last):
        if line.created_at <= snapshot.created_at:
            continue                         # in the cash it started from
        if line.category_id is None:
            name = "(to sort)"
        elif line.category.system_code == PAY_FROM_PRACTICE:
            name = line.category.name
        else:
            name = category_name(line.category)
        cell = by.setdefault(name, {"in": 0, "out": 0})
        cell[line.direction] += line.amount_cents
        if line.direction == "in":
            money_in += line.amount_cents
        else:
            money_out += line.amount_cents
    end = sum(reconcile.balance(account, last) for account in cash_accounts(ledger)
              if account.opening_on <= last)
    return {"in_cents": money_in, "out_cents": money_out, "end_cents": end, "by": by}


def history(ledger, today: date) -> list[dict]:
    """The last six complete months with a forecast kept: cash at the end,
    money in and out, forecast and what happened, and the three largest
    differences by line. No score."""
    rows = []
    for snapshot in PersonalForecastSnapshot.objects.filter(
            ledger=ledger, month__lt=today.replace(day=1)).order_by("-month")[:6]:
        forecast, actual = snapshot.forecast, _actual(ledger, snapshot)
        gaps = []
        for name in set(forecast["by"]) | set(actual["by"]):
            was = forecast["by"].get(name, {"in": 0, "out": 0})
            now = actual["by"].get(name, {"in": 0, "out": 0})
            a, b = was["in"] - was["out"], now["in"] - now["out"]
            if a != b:
                gaps.append({"name": name, "forecast_cents": a, "actual_cents": b,
                             "difference_cents": b - a})
        gaps.sort(key=lambda row: (-abs(row["difference_cents"]), row["name"]))
        rows.append({
            "month": snapshot.month.isoformat()[:7], "label": f"{snapshot.month:%B %Y}",
            "taken_on": snapshot.taken_on.isoformat(),
            "forecast": {k: forecast[k] for k in ("in_cents", "out_cents", "end_cents")},
            "actual": {k: actual[k] for k in ("in_cents", "out_cents", "end_cents")},
            "largest": gaps[:3]})
    return rows


__all__ = ["build", "ending", "groups", "adjust", "undo", "save_planned", "remove_planned",
           "set_floor", "history", "MONTHS"]
