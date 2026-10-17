"""The budget that builds itself (P6 M4 stop 2, decisions 9–14 and the brief's
Cash flow table). Arithmetic on the owner's own lines; nothing here asks
Claude ("Explain this budget" is `budget_ai.py`, pressed only).

- **The proposal (9).** Once lines cover three complete months, each personal
  category gets the median of its monthly totals over the last six complete
  months (three, four or five if that is all there is; a month with nothing
  in a category counts as nothing), to the nearest $10, "From your history";
  a bill the same amount every month, up to the next $10 (2026-10-17: at the
  nearest, a $22.99 subscription reads as overspent every month).
  Income the same way. Nothing is set until the owner uses it.
- **Envelopes (10).** Planned, Spent and Left for a month. Spent is the
  month's lines in the envelope's category (money back in the category takes
  away from it). An overspent envelope asks where to take it from, or whether
  to let it stand; nothing moves by itself.
- **Rollover by kind (11).** An everyday envelope's Left resets each month; a
  saving-up envelope's (a goal, a yearly bill, Taxes) rolls forward. Each has
  the switch.
- **Unassigned (12):** planned income for the month minus every envelope.
- **Questions (13):** `questions.py`.
- **Goals (14)** make a rolling envelope and, with a date, a planned line.
  Yearly bills found in history are spread the same way.

Months are calendar months of the dates on the lines.
"""

from __future__ import annotations

from datetime import date
from statistics import median

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.personal.models import (
    PersonalCategory, PersonalEnvelope, PersonalEnvelopeMove, PersonalGoal, PersonalLine,
    PersonalPlanned,
)
from apps.personal.services import PersonalError

HISTORY_MONTHS = 6
LEAST_MONTHS = 3
#: Decision 13: a category this far from plan, two months running, asks again.
DRIFT = 0.25
#: A single payment at least this large, in a category with nothing in the
#: other months, looks like a yearly bill.
YEARLY_AT_LEAST = 25_000
E = PersonalEnvelope.Kind


# ------------------------------------------------------------------ months

def month_of(day: date) -> date:
    return day.replace(day=1)


def add_months(month: date, n: int) -> date:
    index = month.year * 12 + month.month - 1 + n
    return date(index // 12, index % 12 + 1, 1)


def this_month() -> date:
    return month_of(timezone.localdate())


def label(month: date) -> str:
    return f"{month:%B %Y}"


def to_ten(cents: float) -> int:
    """To the nearest $10, halves up."""
    return int((int(round(cents)) + 500) // 1000 * 1000)


def round_up_ten(cents: float) -> int:
    return int(-(-int(round(cents)) // 1000) * 1000)


def _live_lines(ledger):
    return PersonalLine.objects.filter(ledger=ledger, removed_at__isnull=True,
                                       category__isnull=False)


def covered_months(ledger, today_month=None) -> list[date]:
    """The complete months, of the last six, that the lines cover: those with
    any line in them. Oldest first."""
    today_month = today_month or this_month()
    start = add_months(today_month, -HISTORY_MONTHS)
    found = set(month_of(d) for d in PersonalLine.objects.filter(
        ledger=ledger, removed_at__isnull=True, on_date__gte=start,
        on_date__lt=today_month).values_list("on_date", flat=True))
    return sorted(found)


def totals_by_month(ledger, months: list[date]) -> dict:
    """`{category id: {month: net cents}}`: for spending, out less money back;
    for income, in less out. Transfers are never counted."""
    if not months:
        return {}
    out: dict = {}
    rows = _live_lines(ledger).filter(
        on_date__gte=months[0], on_date__lt=add_months(months[-1], 1),
        category__type__in=("expense", "income")).values_list(
        "category_id", "category__type", "on_date", "direction", "amount_cents")
    for category, type_, on, direction, cents in rows:
        sign = 1 if (direction == "out") == (type_ == "expense") else -1
        month = month_of(on)
        out.setdefault(category, {}).setdefault(month, 0)
        out[category][month] += sign * cents
    return out


# ---------------------------------------------------------------- proposal

def proposal(ledger, today_month=None) -> dict:
    """Decision 9. `{"months": [...], "ready": bool, "envelopes": [...]}`;
    each row a category, its six (or fewer) monthly totals and the median to
    the nearest $10. Categories whose median is nothing are left out."""
    months = covered_months(ledger, today_month)
    ready = len(months) >= LEAST_MONTHS
    rows = []
    if ready:
        totals = totals_by_month(ledger, months)
        categories = {c.pk: c for c in PersonalCategory.objects.filter(
            ledger=ledger, pk__in=list(totals), archived_at__isnull=True)}
        for pk, by_month in totals.items():
            category = categories.get(pk)
            if category is None:
                continue
            amounts = [max(0, by_month.get(m, 0)) for m in months]
            # A bill the same every month goes up to the next $10, not to the
            # nearest: at $20, a $22.99 subscription is over every month.
            fixed = len(set(amounts)) == 1
            proposed = round_up_ten(amounts[0]) if fixed else to_ten(median(amounts))
            if proposed <= 0:
                continue
            rows.append({"category": category, "amounts": amounts, "proposed_cents": proposed,
                         "kind": E.INCOME if category.type == "income" else
                         default_kind(category)})
    rows.sort(key=lambda row: (row["kind"] == E.INCOME, -row["proposed_cents"]))
    return {"months": months, "ready": ready, "envelopes": rows}


def default_kind(category) -> str:
    """Everyday, but Taxes is saved up (decision 11)."""
    names = {category.name, category.parent.name if category.parent_id else ""}
    return E.SAVINGS if "Taxes" in names else E.EVERYDAY


def envelopes(ledger, *, include_archived=False):
    rows = PersonalEnvelope.objects.filter(ledger=ledger).select_related(
        "category", "category__parent", "goal")
    return rows if include_archived else rows.filter(archived_at__isnull=True)


def has_budget(ledger) -> bool:
    return envelopes(ledger).exists()


@transaction.atomic
def accept(ledger) -> list[PersonalEnvelope]:
    """Use the proposal: an envelope for each category it names, from this
    month, with history's amount. Then the questions (`questions.after_proposal`)."""
    from apps.personal import questions

    if has_budget(ledger):
        raise PersonalError("There is a budget already.", status=409)
    found = proposal(ledger)
    if not found["ready"]:
        raise PersonalError(f"The budget is proposed from history once your lines cover "
                            f"{LEAST_MONTHS} months. They cover {len(found['months'])}.",
                            status=409)
    start = this_month()
    made = []
    for position, row in enumerate(found["envelopes"]):
        kind = row["kind"]
        made.append(PersonalEnvelope.objects.create(
            ledger=ledger, category=row["category"], kind=kind, rolls=kind == E.SAVINGS,
            planned_cents=row["proposed_cents"], history_cents=row["proposed_cents"],
            source=PersonalEnvelope.Source.HISTORY, start_month=start, position=position))
    # Goals made before the budget get their envelope now.
    for goal in PersonalGoal.of(ledger.owner).filter(archived_at__isnull=True,
                                                     envelope__isnull=True):
        _goal_envelope(goal)
    questions.after_proposal(ledger, found)
    return made


# --------------------------------------------------------- a month's figures

def spent_in(ledger, month: date) -> dict:
    """`{category id: net cents}` for one month."""
    totals = totals_by_month(ledger, [month])
    return {pk: by.get(month, 0) for pk, by in totals.items()}


def month_view(ledger, month: date | None = None) -> dict:
    """Every envelope's Planned, Spent and Left in `month`, income, and
    Unassigned (decisions 10–12)."""
    month = month or this_month()
    rows = list(envelopes(ledger).filter(start_month__lte=month))
    first = min((env.start_month for env in rows), default=month)
    moves = list(PersonalEnvelopeMove.objects.filter(ledger=ledger, month__gte=first,
                                                     month__lte=month))
    spent = {m: spent_in(ledger, m) for m in _months(first, month)}
    out, income = [], []
    for env in rows:
        carried = 0
        for m in _months(env.start_month, month):
            moved_in = sum(x.amount_cents for x in moves
                           if x.to_envelope_id == env.pk and x.month == m)
            moved_out = sum(x.amount_cents for x in moves
                            if x.from_envelope_id == env.pk and x.month == m)
            used = spent[m].get(env.category_id, 0) if env.category_id else 0
            available = env.planned_cents + carried + moved_in - moved_out
            left = available - used
            if m < month:
                carried = left if env.rolls else 0
        row = {
            "id": str(env.pk), "name": envelope_name(env), "kind": env.kind,
            "kind_label": env.get_kind_display(), "rolls": env.rolls,
            "category": str(env.category_id) if env.category_id else None,
            "goal": str(env.goal_id) if env.goal_id else None,
            "source": env.source, "source_label": env.get_source_display(),
            "planned_cents": env.planned_cents, "history_cents": env.history_cents,
            "carried_cents": carried, "moved_in_cents": moved_in, "moved_out_cents": moved_out,
            "spent_cents": used, "left_cents": left,
            "yearly_cents": env.yearly_cents, "yearly_month": env.yearly_month,
            "over": env.kind != E.INCOME and left < 0,
            "stood": month.strftime("%Y-%m") in (env.stood_months or []),
        }
        (income if env.kind == E.INCOME else out).append(row)
    planned_income = sum(r["planned_cents"] for r in income)
    planned_out = sum(r["planned_cents"] for r in out)
    unassigned = planned_income - planned_out
    return {
        "month": month.isoformat(), "month_label": label(month),
        "envelopes": out, "income": income,
        "income_planned_cents": planned_income,
        "income_received_cents": sum(r["spent_cents"] for r in income),
        "planned_cents": planned_out, "spent_cents": sum(r["spent_cents"] for r in out),
        "unassigned_cents": unassigned,
        # Decision 12: below zero, which envelopes are over the income.
        "over_income": _over_income(out, planned_income) if unassigned < 0 else [],
        "unbudgeted": _unbudgeted(ledger, month, rows),
    }


def _months(first: date, last: date):
    month = first
    while month <= last:
        yield month
        month = add_months(month, 1)


def _over_income(rows: list[dict], income: int) -> list[dict]:
    """The envelopes past the income, the smallest last: what does not fit."""
    out, running = [], 0
    for row in sorted(rows, key=lambda r: -r["planned_cents"]):
        running += row["planned_cents"]
        if running > income:
            out.append({"id": row["id"], "name": row["name"],
                        "planned_cents": row["planned_cents"]})
    return out


def _unbudgeted(ledger, month: date, rows) -> list[dict]:
    """Spending this month in a category with no envelope."""
    have = {env.category_id for env in rows if env.category_id}
    spent = spent_in(ledger, month)
    names = {c.pk: c.name for c in PersonalCategory.objects.filter(
        ledger=ledger, pk__in=[pk for pk in spent if pk not in have], type="expense")}
    return sorted(({"category": str(pk), "name": names[pk], "spent_cents": cents}
                   for pk, cents in spent.items() if pk in names and cents > 0),
                  key=lambda row: -row["spent_cents"])


def envelope_name(env) -> str:
    if env.goal_id:
        return env.goal.name
    return env.category.name if env.category_id else "Envelope"


# ------------------------------------------------------- changing envelopes

def envelope(ledger, pk) -> PersonalEnvelope:
    found = envelopes(ledger).filter(pk=pk).first()
    if found is None:
        raise PersonalError("There is no such envelope.", status=404)
    return found


def update(env, *, planned_cents=None, rolls=None) -> PersonalEnvelope:
    fields = []
    if planned_cents is not None:
        if planned_cents < 0:
            raise PersonalError("An envelope's amount is zero or more.")
        if env.goal_id:
            raise PersonalError("A goal's envelope follows the goal: change the goal.")
        env.planned_cents, env.source = planned_cents, PersonalEnvelope.Source.TYPED
        fields += ["planned_cents", "source"]
    if rolls is not None:
        env.rolls = bool(rolls)
        fields.append("rolls")
    if fields:
        env.save(update_fields=fields + ["updated_at"])
    return env


def add(ledger, *, category, planned_cents, kind=None) -> PersonalEnvelope:
    if envelopes(ledger).filter(category=category).exists():
        raise PersonalError(f"{category.name} has an envelope already.", status=409)
    if category.type == "transfer":
        raise PersonalError("A transfer is never spending, so it has no envelope.")
    kind = kind or (E.INCOME if category.type == "income" else default_kind(category))
    return PersonalEnvelope.objects.create(
        ledger=ledger, category=category, kind=kind, rolls=kind == E.SAVINGS,
        planned_cents=max(0, planned_cents), source=PersonalEnvelope.Source.TYPED,
        start_month=this_month(), position=envelopes(ledger).count())


def cover(env, *, month: date, from_envelope=None, amount_cents=None, stand=False):
    """Decision 10: an overspent envelope, covered from another's Left, or
    let stand. Only what the owner chooses."""
    view = {row["id"]: row for row in month_view(env.ledger, month)["envelopes"]}
    mine = view.get(str(env.pk))
    if mine is None or not mine["over"]:
        raise PersonalError("That envelope is not over this month.", status=409)
    if stand:
        stood = list(env.stood_months or [])
        key = month.strftime("%Y-%m")
        if key not in stood:
            stood.append(key)
        env.stood_months = stood
        env.save(update_fields=["stood_months", "updated_at"])
        return None
    if from_envelope is None or from_envelope.pk == env.pk:
        raise PersonalError("Choose the envelope to take it from.")
    theirs = view.get(str(from_envelope.pk))
    amount = amount_cents if amount_cents is not None else -mine["left_cents"]
    if theirs is None or theirs["left_cents"] <= 0:
        raise PersonalError(f"{envelope_name(from_envelope)} has nothing left this month.",
                            status=409)
    if amount <= 0:
        raise PersonalError("The amount is more than zero.")
    if amount > theirs["left_cents"]:
        raise PersonalError(f"{envelope_name(from_envelope)} has only "
                            f"${theirs['left_cents'] / 100:,.2f} left.", status=409)
    return PersonalEnvelopeMove.objects.create(ledger=env.ledger, month=month,
                                               from_envelope=from_envelope, to_envelope=env,
                                               amount_cents=amount)


def assign_to_goal(ledger, *, goal, amount_cents: int) -> PersonalGoal:
    """Decision 12, above zero: put some of what is unassigned toward a goal,
    a month. The goal's monthly amount goes up by it."""
    if amount_cents <= 0:
        raise PersonalError("The amount is more than zero.")
    left = month_view(ledger)["unassigned_cents"]
    if amount_cents > left:
        raise PersonalError(f"Only ${max(0, left) / 100:,.2f} is unassigned.", status=409)
    env = getattr(goal, "envelope", None) or _goal_envelope(goal)
    env.planned_cents += amount_cents
    env.save(update_fields=["planned_cents", "updated_at"])
    goal.monthly_cents = env.planned_cents if goal.target_on is None else goal.monthly_cents
    goal.save(update_fields=["monthly_cents", "updated_at"])
    return goal


def assign_to_debts(ledger, *, amount_cents: int) -> None:
    """Decision 12 with stop 3: some of what is unassigned toward the debts,
    a month. The payoff plan's extra goes up by it (and so its envelope)."""
    from apps.personal import debts

    if amount_cents <= 0:
        raise PersonalError("The amount is more than zero.")
    left = month_view(ledger)["unassigned_cents"]
    if amount_cents > left:
        raise PersonalError(f"Only ${max(0, left) / 100:,.2f} is unassigned.", status=409)
    if not debts.open_debts(ledger).exists():
        raise PersonalError("There are no debts to put it toward.", status=409)
    debts.set_plan(ledger, extra=ledger.payoff_extra_cents + amount_cents)


# ------------------------------------------------------------------- goals

def everyday_monthly(ledger) -> int:
    return sum(envelopes(ledger).filter(kind=E.EVERYDAY).values_list("planned_cents",
                                                                    flat=True))


def target_of(goal) -> int:
    """An emergency fund's target follows the everyday envelopes."""
    if goal.months_of_envelopes:
        return goal.months_of_envelopes * everyday_monthly(goal.ledger) or goal.target_cents
    return goal.target_cents


def monthly_for(goal, today: date | None = None) -> int:
    """Decision 14: what to set aside a month. With a date, what is still to
    save over the months left (this one counted), up to the next $10; with
    none, the owner's amount, or a year's worth until they choose."""
    still = max(0, target_of(goal) - goal.saved_cents)
    if goal.target_on is None:
        return goal.monthly_cents if goal.monthly_cents is not None else round_up_ten(
            still / 12)
    today = today or timezone.localdate()
    months = max(1, (goal.target_on.year - today.year) * 12
                 + goal.target_on.month - today.month)
    return round_up_ten(still / months)


def _goal_envelope(goal) -> PersonalEnvelope:
    return PersonalEnvelope.objects.create(
        ledger=goal.ledger, goal=goal, kind=E.SAVINGS, rolls=True,
        planned_cents=monthly_for(goal), source=PersonalEnvelope.Source.GOAL,
        start_month=this_month(), position=100 + goal.position)


def _goal_planned(goal) -> None:
    """The goal's target on its date, as a planned line; none without a date."""
    existing = PersonalPlanned.objects.filter(goal=goal).first()
    if goal.target_on is None or goal.archived_at is not None:
        if existing is not None:
            existing.delete()
        return
    amount = max(1, target_of(goal))
    if existing is None:
        PersonalPlanned.objects.create(ledger=goal.ledger, goal=goal, name=goal.name,
                                       on_date=goal.target_on, amount_cents=amount,
                                       direction="out")
    else:
        existing.name, existing.on_date, existing.amount_cents = (goal.name, goal.target_on,
                                                                  amount)
        existing.save(update_fields=["name", "on_date", "amount_cents", "updated_at"])


@transaction.atomic
def save_goal(ledger, *, goal=None, name, target_cents=None, target_on=None, saved_cents=0,
              account=None, months_of_envelopes=None, monthly_cents=None) -> PersonalGoal:
    name = (name or "").strip()
    if not name:
        raise PersonalError("Give the goal a name.")
    if months_of_envelopes is not None and not 1 <= months_of_envelopes <= 24:
        raise PersonalError("An emergency fund is 1 to 24 months of your envelopes.")
    if months_of_envelopes:
        target_cents = months_of_envelopes * everyday_monthly(ledger) or target_cents
    if not target_cents or target_cents <= 0:
        raise PersonalError("Give the goal a target amount.")
    if saved_cents < 0:
        raise PersonalError("What is saved already is zero or more.")
    if target_on is not None and target_on <= timezone.localdate():
        raise PersonalError("The target date is after today.")
    fields = dict(name=name, target_cents=target_cents, target_on=target_on,
                  saved_cents=saved_cents, account=account,
                  months_of_envelopes=months_of_envelopes or None,
                  monthly_cents=monthly_cents if target_on is None else None)
    if goal is None:
        goal = PersonalGoal.objects.create(
            ledger=ledger, position=PersonalGoal.objects.filter(ledger=ledger).count(),
            **fields)
    else:
        for key, value in fields.items():
            setattr(goal, key, value)
        goal.save()
    env = PersonalEnvelope.objects.filter(goal=goal).first()
    if env is None:
        if has_budget(ledger):
            _goal_envelope(goal)
    else:
        env.planned_cents = monthly_for(goal)
        env.save(update_fields=["planned_cents", "updated_at"])
    _goal_planned(goal)
    return goal


def archive_goal(goal) -> None:
    goal.archived_at = timezone.now()
    goal.save(update_fields=["archived_at", "updated_at"])
    PersonalEnvelope.objects.filter(goal=goal).update(archived_at=timezone.now())
    _goal_planned(goal)


def represent_goal(goal, view: dict | None = None) -> dict:
    env = PersonalEnvelope.objects.filter(goal=goal, archived_at__isnull=True).first()
    row = next((r for r in (view or {}).get("envelopes", []) if env and r["id"] == str(env.pk)),
               None)
    set_aside = max(0, row["left_cents"]) if row else 0
    target = target_of(goal)
    progress = min(target, goal.saved_cents + set_aside) if target else 0
    planned = getattr(goal, "planned", None)
    return {
        "id": str(goal.pk), "name": goal.name, "target_cents": target,
        "target_on": goal.target_on.isoformat() if goal.target_on else None,
        "saved_cents": goal.saved_cents, "set_aside_cents": set_aside,
        "progress_cents": progress,
        "percent": int(progress * 100 / target) if target else 0,
        "monthly_cents": monthly_for(goal),
        "monthly_chosen": goal.target_on is None and goal.monthly_cents is not None,
        "months_of_envelopes": goal.months_of_envelopes,
        "account": ({"id": str(goal.account_id), "name": goal.account.name}
                    if goal.account_id else None),
        "envelope": str(env.pk) if env else None,
        "planned": ({"id": str(planned.pk), "on_date": planned.on_date.isoformat(),
                     "amount_cents": planned.amount_cents} if planned else None),
    }


# ------------------------------------------------------------ yearly bills

def yearly_candidates(ledger, today_month=None) -> list[dict]:
    """Decision 14: a single payment of at least `YEARLY_AT_LEAST`, in a
    spending category with nothing in the other covered months, that is not
    spread already. Only proposed; spreading is the owner's."""
    months = covered_months(ledger, today_month)
    if len(months) < LEAST_MONTHS:
        return []
    totals = totals_by_month(ledger, months)
    spread = set(envelopes(ledger).exclude(yearly_cents=None)
                 .values_list("category_id", flat=True))
    out = []
    for pk, by_month in totals.items():
        if pk in spread:
            continue
        paid = {m: c for m, c in by_month.items() if c > 0}
        if len(paid) != 1:
            continue
        (month, cents), = paid.items()
        if cents < YEARLY_AT_LEAST:
            continue
        category = PersonalCategory.objects.filter(pk=pk, type="expense").first()
        if category is None or category.system_code:
            continue
        out.append({"category": category, "cents": cents, "month": month})
    return sorted(out, key=lambda row: -row["cents"])


def spread_yearly(ledger, *, category, cents: int, month: int) -> PersonalEnvelope:
    """A yearly bill spread monthly (decision 14): the category's envelope
    becomes a saving-up one that rolls, at a twelfth of the bill, up to the
    next $10, so the money is there on the day."""
    monthly = round_up_ten(cents / 12)
    env = envelopes(ledger).filter(category=category).first()
    if env is None:
        env = PersonalEnvelope.objects.create(
            ledger=ledger, category=category, start_month=this_month(),
            position=envelopes(ledger).count(), planned_cents=monthly)
    env.kind, env.rolls, env.planned_cents = E.SAVINGS, True, monthly
    env.yearly_cents, env.yearly_month = cents, month
    env.source = PersonalEnvelope.Source.YEARLY
    env.save()
    return env


# ---------------------------------------------------------- Cash flow table

def cash_flow(ledger, today_month=None) -> dict:
    """The brief's Cash flow view: money in and out by category, month by
    month, the last six complete months and this one so far. Transfers are
    not in it; a Mixed card's personal side is."""
    today_month = today_month or this_month()
    months = [add_months(today_month, -n) for n in range(HISTORY_MONTHS, -1, -1)]
    totals = totals_by_month(ledger, months)
    categories = {c.pk: c for c in PersonalCategory.objects.filter(
        ledger=ledger, pk__in=list(totals)).select_related("parent")}
    groups: dict = {}
    for pk, by_month in totals.items():
        category = categories[pk]
        top = category.parent or category
        key = (category.type, top.name)
        group = groups.setdefault(key, {"type": category.type, "name": top.name,
                                        "cents": [0] * len(months), "children": {}})
        child = group["children"].setdefault(category.name, [0] * len(months))
        for i, month in enumerate(months):
            group["cents"][i] += by_month.get(month, 0)
            if category.parent_id:
                child[i] += by_month.get(month, 0)
    rows = []
    for (type_, _name), group in sorted(groups.items(),
                                        key=lambda kv: (kv[0][0] != "income",
                                                        -sum(kv[1]["cents"]))):
        rows.append({"type": type_, "name": group["name"], "cents": group["cents"],
                     "children": [{"name": n, "cents": c}
                                  for n, c in sorted(group["children"].items(),
                                                     key=lambda kv: -sum(kv[1]))
                                  if any(c) and n != group["name"]]})
    money_in = [sum(r["cents"][i] for r in rows if r["type"] == "income")
                for i in range(len(months))]
    money_out = [sum(r["cents"][i] for r in rows if r["type"] == "expense")
                 for i in range(len(months))]
    return {"months": [m.isoformat() for m in months],
            "labels": [f"{m:%b}" for m in months],
            "so_far": months[-1].isoformat(), "rows": rows,
            "in_cents": money_in, "out_cents": money_out,
            "net_cents": [a - b for a, b in zip(money_in, money_out)]}


def coming_up(ledger) -> list[dict]:
    today = timezone.localdate()
    return [{"id": str(p.pk), "name": p.name, "on_date": p.on_date.isoformat(),
             "amount_cents": p.amount_cents, "direction": p.direction,
             "goal": str(p.goal_id) if p.goal_id else None}
            for p in PersonalPlanned.objects.filter(
                ledger=ledger, archived_at__isnull=True, on_date__gte=today,
                is_what_if=False)
            .filter(Q(goal__isnull=True) | Q(goal__archived_at__isnull=True))[:12]]
