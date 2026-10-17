"""Decision 13: the app's own questions about the budget, no AI call. One
screen each, any of them skippable, in this order:

1. **Keep or target**, for the largest everyday envelopes whose months were
   not all the same: "Groceries have run $812 a month. Keep that, or set a
   target?"
2. **Which is normal**, where a category's months fell into a high and a low
   group: "Dining was $340 twice and $120 once. Which is normal?"
3. **A yearly bill**, for each single large payment history shows
   (`budget.yearly_candidates`): "This looks like a yearly bill: Home
   insurance, $1,380 in May. Spread it monthly?"
4. **Anything coming** that history does not show: a goal, or a planned line.

Asked after the proposal, and again (keep or target) when an envelope has
been 25% or more from its plan for each of the last two complete months.
Each question has a key, so none is asked twice.
"""

from __future__ import annotations

from datetime import date
from statistics import median

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.personal import budget
from apps.personal.models import PersonalPlanned, PersonalQuestion
from apps.personal.services import PersonalError

Q = PersonalQuestion.Kind
#: How many of each the proposal asks, at most.
KEEP_MOST, NORMAL_MOST = 2, 2
#: A high month at least this many times a low one makes two groups.
SPREAD = 1.75
NUMBER = {1: "once", 2: "twice", 3: "three times", 4: "four times", 5: "five times"}


def _money(cents: int) -> str:
    return f"${cents / 100:,.0f}" if cents % 100 == 0 else f"${cents / 100:,.2f}"


def _times(n: int) -> str:
    return NUMBER.get(n, f"{n} times")


def _ask(ledger, *, kind, run, key, text, envelope=None, category=None, detail=None,
         position=0):
    try:
        with transaction.atomic():
            return PersonalQuestion.objects.create(
                ledger=ledger, kind=kind, run=run, key=key, text=text[:300],
                envelope=envelope, category=category, detail=detail or {},
                position=position)
    except IntegrityError:
        return None                         # asked before: never twice


def groups(amounts: list[int]) -> tuple[list[int], list[int]] | None:
    """A high and a low group, when the months fall into two."""
    seen = [a for a in amounts if a > 0]
    if len(seen) < 3 or min(seen) * SPREAD > max(seen):
        return None
    middle = (max(seen) + min(seen)) / 2
    high = [a for a in seen if a >= middle]
    low = [a for a in seen if a < middle]
    return (high, low) if high and low else None


def after_proposal(ledger, found: dict) -> list[PersonalQuestion]:
    """The run after the proposal is used."""
    made = []
    by_category = {env.category_id: env for env in budget.envelopes(ledger)}
    everyday = [row for row in found["envelopes"] if row["kind"] == "everyday"]
    position = 0
    # 2 before 1 in the choosing, so a category is asked one of them only.
    normal = [row for row in everyday if groups(row["amounts"])][:NORMAL_MOST]
    asked = {row["category"].pk for row in normal}
    keep = [row for row in everyday if row["category"].pk not in asked
            and len(set(row["amounts"])) > 1][:KEEP_MOST]
    for row in keep:
        category = row["category"]
        made.append(_ask(
            ledger, kind=Q.KEEP_OR_TARGET, run="proposal", key=f"keep:{category.pk}",
            envelope=by_category.get(category.pk), category=category, position=position,
            text=f"{category.name} have run {_money(row['proposed_cents'])} a month. Keep "
                 "that, or set a target?" if category.name.endswith("s") else
                 f"{category.name} has run {_money(row['proposed_cents'])} a month. Keep "
                 "that, or set a target?",
            detail={"proposed_cents": row["proposed_cents"]}))
        position += 1
    for row in normal:
        category = row["category"]
        high, low = groups(row["amounts"])
        high_c, low_c = budget.to_ten(median(high)), budget.to_ten(median(low))
        made.append(_ask(
            ledger, kind=Q.WHICH_NORMAL, run="proposal", key=f"normal:{category.pk}",
            envelope=by_category.get(category.pk), category=category, position=position,
            text=f"{category.name} was {_money(high_c)} {_times(len(high))} and "
                 f"{_money(low_c)} {_times(len(low))}. Which is normal?",
            detail={"choices": [high_c, low_c], "proposed_cents": row["proposed_cents"]}))
        position += 1
    made += yearly(ledger, run="proposal", start=position)
    made.append(_ask(ledger, kind=Q.COMING, run="proposal", key="coming:proposal",
                     position=99,
                     text="Anything coming that your history doesn't show?"))
    return [q for q in made if q is not None]


def yearly(ledger, *, run: str, start: int = 0) -> list[PersonalQuestion]:
    made = []
    for n, row in enumerate(budget.yearly_candidates(ledger)):
        category, month = row["category"], row["month"]
        made.append(_ask(
            ledger, kind=Q.YEARLY, run=run, key=f"yearly:{category.pk}:{month:%Y-%m}",
            category=category, position=start + n,
            text=f"This looks like a yearly bill: {category.name}, {_money(row['cents'])} in "
                 f"{month:%B}. Spread it monthly?",
            detail={"cents": row["cents"], "month": month.month,
                    "monthly_cents": budget.round_up_ten(row["cents"] / 12)}))
    return [q for q in made if q is not None]


def drift(ledger, today_month: date | None = None) -> list[PersonalQuestion]:
    """Decision 13, again: an everyday envelope 25% or more from plan in each
    of the last two complete months, asked once for those two months."""
    today_month = today_month or budget.this_month()
    last, before = budget.add_months(today_month, -1), budget.add_months(today_month, -2)
    made = []
    spent = {m: budget.spent_in(ledger, m) for m in (before, last)}
    for env in budget.envelopes(ledger).filter(kind="everyday", start_month__lte=before,
                                               planned_cents__gt=0):
        amounts = [spent[m].get(env.category_id, 0) for m in (before, last)]
        if not all(abs(a - env.planned_cents) >= budget.DRIFT * env.planned_cents
                   for a in amounts):
            continue
        middle = budget.to_ten(sum(amounts) / 2)
        made.append(_ask(
            ledger, kind=Q.KEEP_OR_TARGET, run="drift",
            key=f"drift:{env.pk}:{last:%Y-%m}", envelope=env, category=env.category,
            text=f"{env.category.name} ran {_money(amounts[0])} and {_money(amounts[1])} the "
                 f"last two months, against {_money(env.planned_cents)} planned. Keep "
                 f"{_money(env.planned_cents)}, or set a new amount?",
            detail={"proposed_cents": env.planned_cents, "suggested_cents": middle,
                    "amounts": amounts}))
    return [q for q in made if q is not None]


def waiting(ledger) -> list[PersonalQuestion]:
    if budget.has_budget(ledger):
        drift(ledger)
        yearly(ledger, run="drift")
    return list(PersonalQuestion.objects.filter(ledger=ledger, state="open")
                .order_by("position", "created_at"))


def represent(q) -> dict:
    return {"id": str(q.pk), "kind": q.kind, "run": q.run, "text": q.text,
            "detail": q.detail, "state": q.state,
            "envelope": str(q.envelope_id) if q.envelope_id else None,
            "category": str(q.category_id) if q.category_id else None}


@transaction.atomic
def answer(q, data: dict) -> dict:
    """One answer, or a skip. What each answer changes is said back."""
    from apps.personal.models import PersonalAccount

    if q.state != "open":
        raise PersonalError("That question is answered already.", status=409)
    said = ""
    if data.get("skip"):
        q.state = "skipped"
    else:
        ledger = q.ledger
        if q.kind in (Q.KEEP_OR_TARGET, Q.WHICH_NORMAL):
            cents = data.get("amount_cents")
            env = q.envelope or budget.envelopes(ledger).filter(category=q.category).first()
            if data.get("keep"):
                said = "Kept."
            else:
                if not isinstance(cents, int) or cents < 0:
                    raise PersonalError("Give the amount a month.")
                if env is None:
                    env = budget.add(ledger, category=q.category, planned_cents=cents)
                else:
                    budget.update(env, planned_cents=cents)
                said = f"{q.category.name}: {_money(cents)} a month."
        elif q.kind == Q.YEARLY:
            if data.get("spread"):
                env = budget.spread_yearly(ledger, category=q.category,
                                           cents=q.detail["cents"], month=q.detail["month"])
                said = (f"{q.category.name} is spread: {_money(env.planned_cents)} a month, "
                        "kept until the bill comes.")
            else:
                said = "Left as it is."
        elif q.kind == Q.COMING:
            what = data.get("what")
            name = str(data.get("name") or "").strip()
            cents = data.get("amount_cents")
            on = data.get("on_date")
            if what not in ("goal", "planned"):
                raise PersonalError("A goal, or something coming on a date.")
            if not isinstance(cents, int) or cents <= 0:
                raise PersonalError("Give the amount.")
            on = date.fromisoformat(on) if on else None
            if what == "goal":
                account = PersonalAccount.of(ledger.owner).filter(
                    pk=data.get("account")).first() if data.get("account") else None
                goal = budget.save_goal(ledger, name=name, target_cents=cents, target_on=on,
                                        account=account)
                said = f"A goal, {goal.name}: {_money(budget.monthly_for(goal))} a month."
            else:
                if not name or on is None or on <= timezone.localdate():
                    raise PersonalError("Give it a name and a date after today.")
                PersonalPlanned.objects.create(
                    ledger=ledger, name=name, on_date=on, amount_cents=cents,
                    direction="in" if data.get("direction") == "in" else "out")
                said = f"{name} is planned for {on:%B} {on.day}."
        q.state = "answered"
    q.answer = {k: v for k, v in data.items() if k != "skip"}
    q.answered_at = timezone.now()
    q.save(update_fields=["state", "answer", "answered_at", "updated_at"])
    return {"said": said, "state": q.state}


def ask_again(ledger) -> list[PersonalQuestion]:
    """"Anything coming?", asked again on the owner's word, from the Overview."""
    stamp = timezone.now().strftime("%Y%m%d%H%M%S")
    q = _ask(ledger, kind=Q.COMING, run="asked", key=f"coming:{stamp}",
             text="Anything coming that your history doesn't show?", position=99)
    return [q] if q else []
