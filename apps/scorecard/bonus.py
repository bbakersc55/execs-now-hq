"""Bonus plans (M5 part 2, spec "Per-person KPIs and bonus plans"): the
arithmetic, who sees whose, and the period close.

**What a plan earns.** Earned so far = amount × Σ (weight × share), where a
component's share comes from its tier table (or, on a straight-line plan, is
the achievement itself, capped). Achievement to date compares the person's
readings in the period so far with the target prorated to the same point, so
a member mid-month sees a fair number, not a scary one:

- A summed KPI (calls, sales) is judged against its full-period target times
  the share of the period gone: 31 reviews against 27 expected by the 21st of
  a 31-day month with a target of 40.
- An averaged or last-value KPI (a rating, a response time) is judged against
  its target as it stands, since an average does not build up over a month.
- Lower is better flips it: 9.4 minutes against a target of 15 is 160%.

A component's KPI periods are those that start inside the plan's period (a
week belongs to the month it starts in). Its full-period target is the
component's own when the plan gives one, else what the KPI's own targets add
up to over those periods (summed KPIs) or their average (the others).

**A person added mid-period** is prorated by days: their amount, and on a
summed KPI their target, scale by the days they are on the plan.

**Who sees whose** (decision 7): a person sees their own; a manager their own
and their team's; senior leadership and the client owner everyone's. Practice
owners and associates see every plan of the companies they reach; assistants
see the plans with no dollar amounts. Nobody else is sent a colleague's row,
and a route that names a plan the reader can see none of answers 404.

**The close** freezes a plan: each person's result, with the readings,
targets, weights and tiers it came from, is written to `BonusResult` and
shown from there ever after; a later change to a reading or to the plan
moves nothing. A corrected reading is shown against the frozen one, and the
amounts are worked out again only when the client owner confirms, which is
recorded (`BonusReopen`) and audited.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone

from . import periods as P
from .board import Targets, name_of, num
from .models import (BonusComponent, BonusPerson, BonusPlan, BonusReopen, BonusResult, Kpi,
                     KpiMonthTarget, KpiPerson, KpiReading, default_tiers)
from .setup import SetupError, audit

CENTS = Decimal("0.01")
MOST_COMPONENTS, FEWEST_COMPONENTS = 5, 2
#: An achievement past this is shown as this: a lower-is-better reading of
#: zero would otherwise be infinite.
ACHIEVEMENT_CEILING = Decimal("999")


def money(value) -> Decimal:
    return Decimal(value).quantize(CENTS, rounding=ROUND_HALF_UP)


def period_end(plan) -> date:
    return P.end_of(plan.period_start, plan.period)


def period_label(plan_or_period, start=None) -> str:
    if start is None:
        period, start = plan_or_period.period, plan_or_period.period_start
    else:
        period = plan_or_period
    return P.long_label(start, period)


def days_in(plan) -> int:
    return (period_end(plan) - plan.period_start).days + 1


def days_left(plan, today) -> int:
    end = period_end(plan)
    if today > end:
        return 0
    return (end - max(today, plan.period_start)).days + 1


def kpi_starts(plan, kpi, week_start) -> list:
    """The KPI's periods that start inside the plan's period."""
    end = period_end(plan)
    return [s for s in P.starts_between(plan.period_start, end, kpi.cadence, week_start)
            if s >= plan.period_start]


# ------------------------------------------------------------------ formats

def fmt(kpi, value) -> str:
    """A value the way a sentence says it: "$2,150", "31", "82%", "9.4 min"."""
    if value is None:
        return "–"
    value = Decimal(value)
    if kpi.kind == Kpi.Kind.MONEY:
        return f"${value:,.0f}" if value == value.to_integral_value() or abs(value) >= 100 \
            else f"${value:,.2f}"
    if kpi.kind == Kpi.Kind.COUNT:
        return f"{value.quantize(Decimal(1), rounding=ROUND_HALF_UP):,}"
    text = f"{value.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP).normalize():f}"
    if kpi.kind == Kpi.Kind.PERCENT:
        return f"{text}%"
    if kpi.kind == Kpi.Kind.DURATION:
        unit = {"minutes": "min", "hours": "hours", "days": "days"}.get(
            kpi.duration_unit or "hours", "hours")
        return f"{text} {unit}"
    return text


def dollars(value) -> str:
    value = money(value)
    return f"${value:,.0f}" if value == value.to_integral_value() else f"${value:,.2f}"


def pct(value) -> int | None:
    return None if value is None else int(Decimal(value).quantize(Decimal(1),
                                                                  rounding=ROUND_HALF_UP))


# ------------------------------------------------------------------ tiers

def clean_tiers(raw) -> list:
    """A tier table: rows of where a tier starts (an achievement percent) and
    the share it earns, starting at 0, rising, shares of 0 to 500."""
    if raw in (None, "", []):
        return default_tiers()
    if not isinstance(raw, list) or not 1 <= len(raw) <= 8:
        raise SetupError("A tier table has one to eight rows.", "tiers")
    rows = []
    for row in raw:
        try:
            start = Decimal(str(row.get("from")))
            share = Decimal(str(row.get("share")))
        except Exception:
            raise SetupError("Each tier has where it starts and the share it earns, "
                             "as percents.", "tiers") from None
        if not (start.is_finite() and share.is_finite()) or start < 0 or not 0 <= share <= 500:
            raise SetupError("A tier starts at 0% or more and earns 0% to 500%.", "tiers")
        rows.append({"from": float(start), "share": float(share)})
    rows.sort(key=lambda r: r["from"])
    if rows[0]["from"] != 0:
        rows.insert(0, {"from": 0, "share": 0})
    if len({r["from"] for r in rows}) != len(rows):
        raise SetupError("Two tiers start at the same percent.", "tiers")
    return rows


def tier_index(tiers, achievement) -> int:
    """The tier an achievement (a percent) falls in."""
    if achievement is None:
        return 0
    found = 0
    for i, row in enumerate(tiers):
        if achievement >= Decimal(str(row["from"])):
            found = i
    return found


def share_of(plan_like, tiers, achievement) -> Decimal:
    if achievement is None:
        return Decimal(0)
    if plan_like["straight_line"]:
        return max(Decimal(0), min(achievement, Decimal(plan_like["cap_pct"])))
    return Decimal(str(tiers[tier_index(tiers, achievement)]["share"]))


# ------------------------------------------------------------------ the arithmetic

def _full_target(component, kpi, months, starts):
    if component.target_value is not None:
        return Decimal(component.target_value)
    targets = Targets(kpi, months)
    values = [targets.of(s) for s in starts]
    if not values or any(v is None for v in values):
        return None
    if kpi.rollup == Kpi.Rollup.SUM:
        return sum((Decimal(v) for v in values), Decimal(0))
    return sum((Decimal(v) for v in values), Decimal(0)) / len(values)


def _person_span(plan, person):
    first = max(plan.period_start, person.joined_on or plan.period_start)
    last = min(period_end(plan), person.left_on or period_end(plan))
    return first, last


def _achievement(kpi, value, expected):
    if value is None or expected is None:
        return None
    if kpi.direction == Kpi.Direction.LOWER:
        if value <= 0:
            return ACHIEVEMENT_CEILING
        ratio = expected / value
    else:
        if expected <= 0:
            return ACHIEVEMENT_CEILING if value > 0 else None
        ratio = value / expected
    return min(ACHIEVEMENT_CEILING, ratio * 100)


def _next_step(plan_like, kpi, row, amount, end):
    """The sentence of what reaches the next tier, and what it adds, or None
    at the top tier, on a straight line, or with nothing to go on."""
    if plan_like["straight_line"] or row["full_target"] is None:
        return None
    tiers, ach = row["tiers"], row["achievement_exact"]
    index = tier_index(tiers, ach) if ach is not None else 0
    if ach is not None and index + 1 >= len(tiers):
        return None
    nxt = tiers[index + 1] if ach is not None else next(
        (t for t in tiers if t["share"] > 0), None)
    if nxt is None:
        return None
    goal_pct = Decimal(str(nxt["from"]))
    gain = money(amount * Decimal(row["weight"]) / 100
                 * (Decimal(str(nxt["share"])) - row["share_exact"]) / 100)
    if gain <= 0:
        return None
    full, value = row["full_target"], row["value_exact"]
    on = end.strftime("%B ") + str(end.day)
    reach = f"{pct(goal_pct)}% of that target" if goal_pct != 100 else "the target"
    share_words = {50: "half of its component", 100: "all of its component"}.get(
        pct(nxt["share"]), f"{pct(nxt['share'])}% of its component")
    if kpi.rollup == Kpi.Rollup.SUM and kpi.direction != Kpi.Direction.LOWER:
        need = full * goal_pct / 100 - (value or 0)
        if need <= 0:
            return None
        what = f"{fmt(kpi, need)} more" if kpi.kind == Kpi.Kind.MONEY \
            else f"{fmt(kpi, need.to_integral_value(rounding='ROUND_CEILING'))} more"
        return {"text": f"{what} in {kpi.name.lower()} by {on} reaches {reach} and earns "
                        f"{share_words}, another {dollars(gain)}.", "gain": float(gain)}
    if kpi.direction == Kpi.Direction.LOWER:
        bound = full * 100 / goal_pct
        return {"text": f"Bringing {kpi.name.lower()} to {fmt(kpi, bound)} or under reaches "
                        f"{reach} and earns {share_words}, another {dollars(gain)}.",
                "gain": float(gain)}
    bound = full * goal_pct / 100
    return {"text": f"{'An average' if kpi.rollup == Kpi.Rollup.AVERAGE else 'A value'} of "
                    f"{fmt(kpi, bound)} or better for {kpi.name.lower()} reaches {reach} and "
                    f"earns {share_words}, another {dollars(gain)}.", "gain": float(gain)}


class Loaded:
    """Everything one or more plans need, read once."""

    def __init__(self, plans):
        plans = list(plans)
        self.plans = plans
        self.components = defaultdict(list)
        self.people = defaultdict(list)
        ids = [p.pk for p in plans]
        for c in BonusComponent.all_objects.filter(plan_id__in=ids).select_related("kpi"):
            self.components[c.plan_id].append(c)
        for person in BonusPerson.all_objects.filter(plan_id__in=ids).select_related(
                "membership__user"):
            self.people[person.plan_id].append(person)
        kpi_ids = {c.kpi_id for cs in self.components.values() for c in cs}
        self.months = defaultdict(dict)
        for t in KpiMonthTarget.all_objects.filter(kpi_id__in=kpi_ids):
            self.months[t.kpi_id][t.month] = t.value
        first = min((p.period_start for p in plans), default=None)
        self.readings = defaultdict(dict)
        if kpi_ids and first is not None:
            for r in KpiReading.all_objects.filter(kpi_id__in=kpi_ids,
                                                   membership__isnull=False,
                                                   period_start__gte=first - timedelta(days=7)):
                self.readings[(r.kpi_id, r.membership_id)][r.period_start] = r.value
        self.tracked = defaultdict(set)
        for kp in KpiPerson.all_objects.filter(kpi_id__in=kpi_ids):
            self.tracked[kp.kpi_id].add(kp.membership_id)


def live_result(plan, person, loaded, today, week_start):
    """One person's result on one plan from the readings as they stand."""
    plan_like = {"straight_line": plan.straight_line, "cap_pct": plan.cap_pct}
    end = period_end(plan)
    first, last = _person_span(plan, person)
    total_days = days_in(plan)
    on_days = max(0, (last - first).days + 1)
    factor = Decimal(on_days) / total_days
    gone_to = end if (plan.closed_at or today > end) else min(today, last)
    gone = max(0, (gone_to - first).days + 1) if gone_to >= first else 0
    full_amount = Decimal(person.amount if person.amount is not None else plan.amount)
    amount = full_amount * factor
    rows, earned = [], Decimal(0)
    for comp in loaded.components[plan.pk]:
        kpi = comp.kpi
        starts = kpi_starts(plan, kpi, week_start)
        mine = loaded.readings.get((kpi.pk, person.membership_id), {})
        # Only the periods they were on the plan for.
        seen = [(s, mine[s]) for s in starts if s in mine and s <= today
                and P.end_of(s, kpi.cadence) >= first and s <= last]
        values = [Decimal(v) for _, v in seen]
        value = P.combine(values, kpi.rollup) if values else None
        full = _full_target(comp, kpi, loaded.months[kpi.pk], starts)
        tiers = comp.tiers or default_tiers()
        if full is not None and kpi.rollup == Kpi.Rollup.SUM:
            person_full = full * factor
            expected = full * Decimal(gone) / total_days
        else:
            person_full = full
            expected = full
        ach = _achievement(kpi, value, expected)
        share = share_of(plan_like, tiers, ach)
        part = money(amount * Decimal(comp.weight) / 100 * share / 100)
        earned += part
        row = {
            "kpi": str(kpi.pk), "name": kpi.name, "kind": kpi.kind,
            "direction": kpi.direction, "rollup": kpi.rollup,
            "weight": float(comp.weight), "tiers": tiers,
            "value": num(value), "value_text": fmt(kpi, value),
            "target": num(person_full), "target_text": fmt(kpi, person_full),
            "expected": num(expected), "expected_text": fmt(kpi, expected),
            "achievement": pct(ach), "tier": tier_index(tiers, ach) if ach is not None else None,
            "share": float(share), "earned": float(part),
            "readings": [{"period_start": s.isoformat(), "label": P.short_label(s, kpi.cadence),
                          "value": num(v)} for s, v in seen],
            "tracked": person.membership_id in loaded.tracked[kpi.pk],
            # Kept for the sentence; not sent.
            "value_exact": value, "full_target": person_full, "achievement_exact": ach,
            "share_exact": share,
        }
        row["next"] = _next_step(plan_like, kpi, row, amount, end) \
            if not (plan.closed_at or today > end) else None
        rows.append(row)
    for row in rows:
        for key in ("value_exact", "full_target", "achievement_exact", "share_exact"):
            row.pop(key)
    best = max((r["next"] for r in rows if r["next"]), key=lambda n: n["gain"], default=None)
    return {
        "membership": str(person.membership_id), "name": name_of(person.membership.user),
        "full_amount": float(money(full_amount)), "amount": float(money(amount)),
        "prorated": on_days < total_days, "days_on": on_days, "days": total_days,
        "joined_on": person.joined_on.isoformat() if person.joined_on else None,
        "left_on": person.left_on.isoformat() if person.left_on else None,
        "earned": float(money(earned)), "components": rows,
        "next": best["text"] if best else None,
    }


def frozen_result(result) -> dict:
    return {**result.detail, "membership": str(result.membership_id), "name": result.name,
            "earned": float(result.earned), "full_amount": float(result.full_amount),
            "next": None}


def results(plan, loaded, today, week_start, *, people=None) -> list:
    """Every person's result on a plan (or those given): frozen when closed."""
    wanted = None if people is None else {str(m) for m in people}
    if plan.closed_at:
        rows = [frozen_result(r) for r in
                BonusResult.all_objects.filter(plan=plan).order_by("name")]
    else:
        rows = [live_result(plan, person, loaded, today, week_start)
                for person in loaded.people[plan.pk]]
        rows.sort(key=lambda r: r["name"].lower())
    return [r for r in rows if wanted is None or r["membership"] in wanted]


# ------------------------------------------------------------------ who sees whose

class BonusReader:
    """Decision 7 on top of the scorecard's `Reader`."""

    def __init__(self, reader):
        self.reader = reader

    @property
    def sees_everyone(self) -> bool:
        """Senior leadership, the client owner, and the practice."""
        return self.reader.sees_all

    @property
    def sees_amounts(self) -> bool:
        from apps.tenancy.models import Role

        return self.reader.role != Role.VA

    @property
    def builds(self) -> bool:
        return self.reader.sets_up

    @property
    def closes(self) -> bool:
        """The practice owner, associates and the client owner close a period."""
        from apps.tenancy.models import Role

        return self.reader.sets_up or self.reader.role == Role.FCC

    @property
    def confirms_reopen(self) -> bool:
        """Only the client owner reopens a closed period's amounts."""
        from apps.tenancy.models import Role

        return self.reader.role == Role.FCC

    def people_of(self, plan_people) -> set:
        """The memberships on a plan whose rows this reader is sent."""
        everyone = {p if not hasattr(p, "membership_id") else p.membership_id
                    for p in plan_people}
        if self.sees_everyone:
            return everyone
        mine = {self.reader.membership.pk} | self.reader.managed_people()
        return everyone & mine

    def views(self, plans_people) -> list:
        """Which bonus views this person gets: My bonus when they are on a
        plan, Team bonus when they manage someone on one, All bonuses for
        senior leadership, the client owner and the practice."""
        out = []
        me = self.reader.membership.pk
        on = any(me in people for people in plans_people)
        if on and self.reader.is_client:
            out.append("mine")
        if not self.sees_everyone and self.reader.managed_teams:
            managed = self.reader.managed_people() - {me}
            if any(managed & people for people in plans_people):
                out.append("team")
        if self.sees_everyone:
            out.append("all")
        return out


def visible_plans(scorecard, *, include_archived=False):
    plans = BonusPlan.all_objects.filter(scorecard=scorecard)
    if not include_archived:
        plans = plans.filter(archived_at__isnull=True)
    return list(plans.order_by("-period_start", "name"))


def plan_people(plans) -> dict:
    out = defaultdict(set)
    for plan_id, membership_id in BonusPerson.all_objects.filter(
            plan_id__in=[p.pk for p in plans]).values_list("plan_id", "membership_id"):
        out[plan_id].add(membership_id)
    for plan_id, membership_id in BonusResult.all_objects.filter(
            plan_id__in=[p.pk for p in plans if p.closed_at]).values_list(
            "plan_id", "membership_id"):
        out[plan_id].add(membership_id)
    return out


def strip_amounts(row) -> dict:
    """An assistant's copy of a row: achievement, no dollars."""
    out = {k: v for k, v in row.items()
           if k not in ("full_amount", "amount", "earned", "next")}
    out["components"] = [{k: v for k, v in c.items() if k not in ("earned", "next")}
                         for c in row.get("components", [])]
    return out


# ------------------------------------------------------------------ the plan, set up

def _decimal(data, key, label, *, required=False, low=None, high=None):
    from .setup import _decimal as parse

    value = parse(data, key, required=required, label=label)
    if value is None:
        return None
    if low is not None and value < low or high is not None and value > high:
        raise SetupError(f"{label[0].upper()}{label[1:]} is out of range.", key)
    return value


def _date(raw, field):
    if raw in (None, ""):
        return None
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        raise SetupError("That isn't a date.", field) from None


def _clean_components(scorecard, plan_period, raw) -> list:
    if not isinstance(raw, list) or not FEWEST_COMPONENTS <= len(raw) <= MOST_COMPONENTS:
        raise SetupError("A plan has two to five components.", "components")
    kpis = {str(k.pk): k for k in Kpi.objects.filter(scorecard=scorecard,
                                                     archived_at__isnull=True)}
    out, seen, total = [], set(), Decimal(0)
    for row in raw:
        kpi = kpis.get(str(row.get("kpi") or ""))
        if kpi is None:
            raise SetupError("Each component is one of this scorecard's KPIs.", "components")
        if kpi.pk in seen:
            raise SetupError(f"{kpi.name} is in the plan twice.", "components")
        seen.add(kpi.pk)
        if not kpi.per_person or kpi.is_computed:
            raise SetupError(f"{kpi.name} isn't a per-person KPI. A component counts "
                             "each person's own numbers.", "components")
        if kpi.direction == Kpi.Direction.RANGE:
            raise SetupError(f"{kpi.name} is judged within a range; a component is "
                             "higher or lower is better.", "components")
        if plan_period == BonusPlan.Period.MONTHLY and kpi.cadence == Kpi.Cadence.QUARTERLY:
            raise SetupError(f"{kpi.name} is read quarterly, longer than a monthly plan.",
                             "components")
        weight = _decimal(row, "weight", "a weight", required=True, low=Decimal("0.01"),
                          high=Decimal(100))
        total += weight
        target = _decimal(row, "target_value", "a target")
        out.append({"kpi": kpi, "weight": weight.quantize(CENTS), "target_value": target,
                    "tiers": clean_tiers(row.get("tiers"))})
    if total.quantize(CENTS) != Decimal(100):
        raise SetupError(f"The weights add to {total.normalize():f}%; they must add to 100%.",
                         "components")
    return out


def _clean_people(company, plan_start, plan_end, raw) -> list:
    from apps.tenancy.models import CLIENT_ROLES, Membership

    if not isinstance(raw, list) or not raw:
        raise SetupError("Name at least one person on the plan.", "people")
    ids = [str(r.get("membership") or "") for r in raw]
    found = {str(m.pk): m for m in Membership.objects.filter(
        pk__in=[i for i in ids if setup_is_uuid(i)], client_company=company,
        role__in=CLIENT_ROLES, revoked_at__isnull=True)}
    if len(found) != len(set(ids)) or len(ids) != len(set(ids)):
        raise SetupError("Each person on a plan is a portal user of the company, once.",
                         "people")
    out = []
    for row in raw:
        joined = _date(row.get("joined_on"), "people")
        left = _date(row.get("left_on"), "people")
        for day in (joined, left):
            if day is not None and not plan_start <= day <= plan_end:
                raise SetupError("A start or end date on the plan is inside its period.",
                                 "people")
        if joined and left and left < joined:
            raise SetupError("Someone leaves the plan before they join it.", "people")
        out.append({"membership": found[str(row.get("membership"))],
                    "amount": _decimal(row, "amount", "an amount", low=Decimal(0)),
                    "joined_on": joined, "left_on": left})
    return out


def setup_is_uuid(value) -> bool:
    from .setup import _is_uuid

    return _is_uuid(value)


def clean_plan(scorecard, data, plan=None) -> dict:
    merged = {}
    if plan is not None:
        merged = describe(plan, for_edit=True)
    merged.update({k: v for k, v in data.items() if k != "company"})
    name = " ".join(str(merged.get("name") or "").split())[:120]
    if not name:
        raise SetupError("A plan needs a name.", "name")
    period = merged.get("period") or BonusPlan.Period.MONTHLY
    if period not in BonusPlan.Period.values:
        raise SetupError("A plan is monthly or quarterly.", "period")
    start = _date(merged.get("period_start"), "period_start")
    if start is None:
        raise SetupError("Choose the plan's period.", "period_start")
    start = P.start_of(start, period)
    amount = _decimal(merged, "amount", "the amount per person", required=True, low=Decimal(0))
    straight = bool(merged.get("straight_line"))
    cap = _decimal(merged, "cap_pct", "the cap", low=Decimal(0), high=Decimal(500))
    end = P.end_of(start, period)
    return {
        "name": name, "period": period, "period_start": start, "amount": money(amount),
        "straight_line": straight, "cap_pct": (cap if cap is not None else Decimal(120)),
        "components": _clean_components(scorecard, period, merged.get("components")),
        "people": _clean_people(scorecard.company, start, end, merged.get("people")),
    }


def _write_parts(plan, clean):
    BonusComponent.all_objects.filter(plan=plan).delete()
    BonusPerson.all_objects.filter(plan=plan).delete()
    for i, c in enumerate(clean["components"]):
        BonusComponent.all_objects.create(tenant_id=plan.tenant_id, plan=plan, kpi=c["kpi"],
                                          weight=c["weight"], target_value=c["target_value"],
                                          tiers=c["tiers"], position=i)
    for p in clean["people"]:
        BonusPerson.all_objects.create(tenant_id=plan.tenant_id, plan=plan,
                                       membership=p["membership"], amount=p["amount"],
                                       joined_on=p["joined_on"], left_on=p["left_on"])


def _refuse_closed(plan):
    if plan.closed_at:
        raise SetupError(f"{plan.name} for {period_label(plan)} is closed. Copy it forward "
                         "to change the next period.")


@transaction.atomic
def create_plan(scorecard, data, actor) -> BonusPlan:
    clean = clean_plan(scorecard, data)
    if BonusPlan.all_objects.filter(scorecard=scorecard, name=clean["name"],
                                    period_start=clean["period_start"],
                                    archived_at__isnull=True).exists():
        raise SetupError(f"There is already a {clean['name']} for "
                         f"{period_label(clean['period'], clean['period_start'])}.", "name")
    plan = BonusPlan.all_objects.create(
        tenant_id=scorecard.tenant_id, scorecard=scorecard, series=uuid.uuid4(),
        created_by=actor, **{k: clean[k] for k in ("name", "period", "period_start", "amount",
                                                   "straight_line", "cap_pct")})
    _write_parts(plan, clean)
    audit(scorecard.company, actor, "scorecard.bonus_plan_created", name=plan.name,
          plan=str(plan.pk), period=period_label(plan))
    return plan


@transaction.atomic
def update_plan(plan, data, actor) -> BonusPlan:
    plan = BonusPlan.all_objects.select_for_update().get(pk=plan.pk)
    _refuse_closed(plan)
    clean = clean_plan(plan.scorecard, data, plan)
    for key in ("name", "period", "period_start", "amount", "straight_line", "cap_pct"):
        setattr(plan, key, clean[key])
    plan.save()
    _write_parts(plan, clean)
    audit(plan.scorecard.company, actor, "scorecard.bonus_plan_changed", name=plan.name,
          plan=str(plan.pk), period=period_label(plan))
    return plan


@transaction.atomic
def archive_plan(plan, actor) -> BonusPlan:
    _refuse_closed(plan)
    plan.archived_at = timezone.now()
    plan.save(update_fields=["archived_at", "updated_at"])
    audit(plan.scorecard.company, actor, "scorecard.bonus_plan_archived", name=plan.name,
          plan=str(plan.pk), period=period_label(plan))
    return plan


@transaction.atomic
def copy_forward(plan, actor) -> BonusPlan:
    """The next period's plan, the same in every way: people, amounts,
    components, weights, targets and tiers. Someone who joined or left
    part-way is on the next period from its start."""
    start = P.next_start(plan.period_start, plan.period)
    if BonusPlan.all_objects.filter(series=plan.series, period_start=start).exists():
        raise SetupError(f"{plan.name} for {period_label(plan.period, start)} is already "
                         "there.")
    new = BonusPlan.all_objects.create(
        tenant_id=plan.tenant_id, scorecard=plan.scorecard, series=plan.series,
        name=plan.name, period=plan.period, period_start=start, amount=plan.amount,
        straight_line=plan.straight_line, cap_pct=plan.cap_pct, copied_from=plan,
        created_by=actor)
    for c in BonusComponent.all_objects.filter(plan=plan):
        BonusComponent.all_objects.create(tenant_id=plan.tenant_id, plan=new, kpi_id=c.kpi_id,
                                          weight=c.weight, target_value=c.target_value,
                                          tiers=c.tiers, position=c.position)
    for p in BonusPerson.all_objects.filter(plan=plan):
        if p.left_on is not None:
            continue
        BonusPerson.all_objects.create(tenant_id=plan.tenant_id, plan=new,
                                       membership_id=p.membership_id, amount=p.amount)
    audit(plan.scorecard.company, actor, "scorecard.bonus_plan_copied", name=new.name,
          plan=str(new.pk), period=period_label(new), **{"from": period_label(plan)})
    return new


def _snapshot(plan, today):
    week_start = plan.scorecard.week_start
    loaded = Loaded([plan])
    return [live_result(plan, person, loaded, today, week_start)
            for person in loaded.people[plan.pk]]


def _frozen_detail(row) -> dict:
    keep = {k: v for k, v in row.items() if k not in ("membership", "name", "earned",
                                                     "full_amount", "next")}
    keep["components"] = [{k: v for k, v in c.items() if k != "next"}
                          for c in row["components"]]
    return keep


@transaction.atomic
def close(plan, actor, today) -> BonusPlan:
    """Freeze a plan whose period has ended."""
    plan = BonusPlan.all_objects.select_for_update().select_related("scorecard").get(pk=plan.pk)
    if plan.closed_at:
        raise SetupError(f"{plan.name} for {period_label(plan)} is already closed.")
    if period_end(plan) >= today:
        raise SetupError(f"{period_label(plan)} hasn't ended yet. A period closes once its "
                         "last day is over.")
    rows = _snapshot(plan, today)
    plan.closed_at, plan.closed_by = timezone.now(), actor
    plan.save(update_fields=["closed_at", "closed_by", "updated_at"])
    for row in rows:
        BonusResult.all_objects.create(
            tenant_id=plan.tenant_id, plan=plan, membership_id=row["membership"],
            name=row["name"], full_amount=Decimal(str(row["full_amount"])),
            earned=Decimal(str(row["earned"])), detail=_frozen_detail(row))
    audit(plan.scorecard.company, actor, "scorecard.bonus_period_closed", name=plan.name,
          plan=str(plan.pk), period=period_label(plan),
          total=str(sum((Decimal(str(r["earned"])) for r in rows), Decimal(0))))
    return plan


def corrections(plan, today) -> list:
    """Readings that changed after the close, against the frozen ones."""
    if not plan.closed_at:
        return []
    frozen = {r.membership_id: r for r in BonusResult.all_objects.filter(plan=plan)}
    out = []
    week_start = plan.scorecard.week_start
    loaded = Loaded([plan])
    for person in loaded.people[plan.pk]:
        old = frozen.get(person.membership_id)
        if old is None:
            continue
        before = {c["kpi"]: c for c in old.detail.get("components", [])}
        for comp in loaded.components[plan.pk]:
            kpi = comp.kpi
            then = {r["period_start"]: r["value"] for r in
                    before.get(str(kpi.pk), {}).get("readings", [])}
            mine = loaded.readings.get((kpi.pk, person.membership_id), {})
            for s in kpi_starts(plan, kpi, week_start):
                now = num(mine.get(s))
                was = then.get(s.isoformat())
                if now != was:
                    out.append({"membership": str(person.membership_id), "name": old.name,
                                "kpi": kpi.name, "period": P.short_label(s, kpi.cadence),
                                "frozen": was, "now": now})
    return out


@transaction.atomic
def reopen(plan, actor, today) -> BonusPlan:
    """Work a closed plan's amounts out again from the readings as they
    stand. Only the client owner's confirmation calls this; it is recorded."""
    plan = BonusPlan.all_objects.select_for_update().select_related("scorecard").get(pk=plan.pk)
    if not plan.closed_at:
        raise SetupError("Only a closed period is reopened.")
    if not corrections(plan, today):
        raise SetupError("No reading has changed since the close; there is nothing to "
                         "work out again.")
    before = {str(r.membership_id): str(r.earned)
              for r in BonusResult.all_objects.filter(plan=plan)}
    closed_at = plan.closed_at
    plan.closed_at = None                       # worked out live, once
    rows = _snapshot(plan, today)
    plan.closed_at = closed_at
    BonusResult.all_objects.filter(plan=plan).delete()
    for row in rows:
        BonusResult.all_objects.create(
            tenant_id=plan.tenant_id, plan=plan, membership_id=row["membership"],
            name=row["name"], full_amount=Decimal(str(row["full_amount"])),
            earned=Decimal(str(row["earned"])), detail=_frozen_detail(row))
    after = {r["membership"]: str(r["earned"]) for r in rows}
    BonusReopen.all_objects.create(tenant_id=plan.tenant_id, plan=plan, confirmed_by=actor,
                                   before=before, after=after)
    audit(plan.scorecard.company, actor, "scorecard.bonus_period_reopened", name=plan.name,
          plan=str(plan.pk), period=period_label(plan))
    return plan


# ------------------------------------------------------------------ what is sent

def describe(plan, *, for_edit=False) -> dict:
    comps = list(BonusComponent.all_objects.filter(plan=plan).select_related("kpi"))
    people = list(BonusPerson.all_objects.filter(plan=plan).select_related("membership__user"))
    out = {
        "id": str(plan.pk), "name": plan.name, "period": plan.period,
        "period_start": plan.period_start.isoformat(), "period_label": period_label(plan),
        "amount": str(plan.amount), "straight_line": plan.straight_line,
        "cap_pct": float(plan.cap_pct), "closed": plan.closed_at is not None,
        "components": [{"kpi": str(c.kpi_id), "name": c.kpi.name, "weight": float(c.weight),
                        "target_value": None if c.target_value is None
                        else float(c.target_value), "tiers": c.tiers} for c in comps],
        "people": [{"membership": str(p.membership_id), "name": name_of(p.membership.user),
                    "amount": None if p.amount is None else str(p.amount),
                    "joined_on": p.joined_on.isoformat() if p.joined_on else None,
                    "left_on": p.left_on.isoformat() if p.left_on else None}
                   for p in people],
    }
    if for_edit:
        out["components"] = [{k: v for k, v in c.items() if k != "name"}
                             for c in out["components"]]
    return out


def plan_head(plan, today, *, totals=None) -> dict:
    end = period_end(plan)
    return {
        "id": str(plan.pk), "name": plan.name, "series": str(plan.series),
        "period": plan.period, "period_start": plan.period_start.isoformat(),
        "period_end": end.isoformat(), "period_label": period_label(plan),
        "days_left": days_left(plan, today), "ended": end < today,
        "closed": plan.closed_at is not None,
        "closed_at": plan.closed_at.isoformat() if plan.closed_at else None,
        "closed_by": name_of(plan.closed_by) if plan.closed_at else "",
        "straight_line": plan.straight_line, "cap_pct": float(plan.cap_pct),
        "amount": float(plan.amount),
        **({"totals": totals} if totals is not None else {}),
    }


def totals_of(rows) -> dict:
    return {"people": len(rows),
            "earned": float(sum((Decimal(str(r["earned"])) for r in rows), Decimal(0))),
            "full": float(sum((Decimal(str(r.get("amount", r["full_amount"])))
                               for r in rows), Decimal(0)))}
