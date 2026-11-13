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

**Per-unit pay** (2026-11-12) sits beside the components, or takes their
place: a fixed amount for each unit of a company KPI's reading for the period,
"4 × $5 = $20" for four five-star Google reviews. The plan chooses whether
each person earns that in full, or it is one pool split evenly among the
people on the plan (by days on it, which is evenly when everyone is on it all
period). A person on part of the period earns their days' share either way.

**Who is on a plan**: people named one by one, whole teams, or both. A team
counts the client users on it as it stands (a client owner is on a team only
by being named, as P7 has it); someone named and on a team is on once, by
their own row. The close freezes who was on it.

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
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone

from . import periods as P
from .board import Targets, name_of, num
from .models import (BonusComponent, BonusPerson, BonusPlan, BonusReopen, BonusResult,
                     BonusTeam, BonusUnitRule, Kpi, KpiMonthTarget, KpiPerson, KpiReading,
                     default_tiers)
from .setup import SetupError, audit

CENTS = Decimal("0.01")
MOST_COMPONENTS, FEWEST_COMPONENTS = 5, 2
MOST_UNIT_RULES = 3
#: What per-unit pay counts: a number of things, or dollars ("2¢ a dollar").
UNIT_KINDS = (Kpi.Kind.COUNT, Kpi.Kind.NUMBER, Kpi.Kind.MONEY)
POOL = BonusPlan.UnitSplit.POOL
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


def rate_text(value) -> str:
    """A rate per unit: "$5", "$2.50", "$0.015"."""
    value = Decimal(value)
    if value == value.quantize(CENTS):
        return dollars(value)
    return f"${value.normalize():f}"


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


def _team_members(plans) -> dict:
    """The open plans' whole teams, as they stand: {plan id: {membership id:
    (membership, [team names])}}. A team counts its client team members whose
    access is live; the client owner is on a plan only by being named (P7:
    their rows on a team do not matter). An archived team counts nobody."""
    from apps.tenancy.models import Role
    from apps.work.models import ClientTeamMember

    out = defaultdict(dict)
    open_ids = [p.pk for p in plans if not p.closed_at]
    by_team = defaultdict(list)
    for plan_id, team_id in BonusTeam.all_objects.filter(
            plan_id__in=open_ids, team__archived_at__isnull=True).values_list("plan_id",
                                                                               "team_id"):
        by_team[team_id].append(plan_id)
    if not by_team:
        return out
    for row in ClientTeamMember.all_objects.filter(
            team_id__in=list(by_team), membership__role=Role.ECC,
            membership__revoked_at__isnull=True).select_related("membership__user", "team"):
        if row.membership.client_company_id != row.team.client_company_id:
            continue
        for plan_id in by_team[row.team_id]:
            entry = out[plan_id].setdefault(row.membership_id, (row.membership, []))
            entry[1].append(row.team.name)
    return out


def _stand_in(plan, membership) -> BonusPerson:
    """Someone on a plan through a team (or frozen at the close) and not
    named on it: on it all period, at the plan's amount. Never saved."""
    return BonusPerson(tenant_id=plan.tenant_id, plan_id=plan.pk, membership=membership,
                       amount=None, joined_on=None, left_on=None)


class Loaded:
    """Everything one or more plans need, read once. A plan's `people` are
    everyone on it: those named, then, while it is open, its teams' people;
    once closed, those its close froze."""

    def __init__(self, plans):
        plans = list(plans)
        self.plans = plans
        self.components = defaultdict(list)
        self.units = defaultdict(list)
        self.people = defaultdict(list)
        #: (plan id, membership id): the teams that put them on it.
        self.via = {}
        ids = [p.pk for p in plans]
        for c in BonusComponent.all_objects.filter(plan_id__in=ids).select_related("kpi"):
            self.components[c.plan_id].append(c)
        for rule in BonusUnitRule.all_objects.filter(plan_id__in=ids).select_related("kpi"):
            self.units[rule.plan_id].append(rule)
        named = defaultdict(set)
        for person in BonusPerson.all_objects.filter(plan_id__in=ids).select_related(
                "membership__user"):
            self.people[person.plan_id].append(person)
            named[person.plan_id].add(person.membership_id)
        by_id = {p.pk: p for p in plans}
        for plan_id, members in _team_members(plans).items():
            for membership_id, (membership, teams) in sorted(
                    members.items(), key=lambda kv: str(kv[0])):
                if membership_id not in named[plan_id]:
                    self.people[plan_id].append(_stand_in(by_id[plan_id], membership))
                    self.via[(plan_id, membership_id)] = sorted(teams)
        closed = [p.pk for p in plans if p.closed_at]
        for r in BonusResult.all_objects.filter(plan_id__in=closed).select_related(
                "membership__user"):
            if r.membership_id not in named[r.plan_id]:
                named[r.plan_id].add(r.membership_id)
                self.people[r.plan_id].append(_stand_in(by_id[r.plan_id], r.membership))
            self.via[(r.plan_id, r.membership_id)] = (r.detail or {}).get("via") or []
        self._pool = {}
        kpi_ids = {c.kpi_id for cs in self.components.values() for c in cs}
        unit_kpis = {r.kpi_id for rs in self.units.values() for r in rs}
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
        #: Per-unit pay counts the company's own reading of its KPI.
        self.company_readings = defaultdict(dict)
        if unit_kpis and first is not None:
            for r in KpiReading.all_objects.filter(kpi_id__in=unit_kpis,
                                                   membership__isnull=True,
                                                   period_start__gte=first - timedelta(days=7)):
                self.company_readings[r.kpi_id][r.period_start] = r.value

    def pool(self, plan) -> dict:
        """How a pooled plan splits: how many people, their days on it all
        told, and whether everyone is on it all period."""
        if plan.pk not in self._pool:
            total = days_in(plan)
            spans = [_on_days(plan, person) for person in self.people[plan.pk]]
            self._pool[plan.pk] = {"people": len(spans), "days": sum(spans),
                                   "even": all(d == total for d in spans)}
        return self._pool[plan.pk]


def _on_days(plan, person) -> int:
    first, last = _person_span(plan, person)
    return max(0, (last - first).days + 1)


def _unit_text(kpi, count, rate, total, part, *, split, pool, prorated, on_days, days) -> str:
    """ "4 × $5 = $20", and how the person's part comes from it."""
    head = f"{fmt(kpi, count)} × {rate_text(rate)} = {dollars(total)}"
    if split == POOL:
        if pool["people"] <= 1:
            return f"{head}, one pool: {dollars(part)}"
        how = "" if pool["even"] else " by days on the plan"
        return f"{head}, split among {pool['people']}{how}: {dollars(part)}"
    if prorated:
        return f"{head}, for {on_days} of {days} days: {dollars(part)}"
    return head


def _unit_rows(plan, person, loaded, today, week_start, *, factor, on_days, total_days):
    rows, earned = [], Decimal(0)
    for rule in loaded.units[plan.pk]:
        kpi = rule.kpi
        starts = kpi_starts(plan, kpi, week_start)
        readings = loaded.company_readings.get(kpi.pk, {})
        seen = [(s, readings[s]) for s in starts if s in readings and s <= today]
        count = P.combine([Decimal(v) for _, v in seen], kpi.rollup) if seen else None
        rate = Decimal(rule.rate)
        total = money((count or 0) * rate)
        pool = loaded.pool(plan)
        if plan.unit_split == POOL:
            part = money(total * Decimal(on_days) / pool["days"]) if pool["days"] else Decimal(0)
        else:
            part = money(total * factor)
        earned += part
        rows.append({
            "kpi": str(kpi.pk), "name": kpi.name, "kind": kpi.kind, "rollup": kpi.rollup,
            "rate": float(rate), "rate_text": rate_text(rate),
            "units": num(count), "units_text": fmt(kpi, count or 0),
            "total": float(total), "split": plan.unit_split, "people": pool["people"],
            "earned": float(part),
            "text": _unit_text(kpi, count or 0, rate, total, part, split=plan.unit_split,
                               pool=pool, prorated=on_days < total_days, on_days=on_days,
                               days=total_days),
            "readings": [{"period_start": s.isoformat(), "label": P.short_label(s, kpi.cadence),
                          "value": num(v)} for s, v in seen],
        })
    return rows, earned


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
    if not loaded.components[plan.pk]:
        full_amount = Decimal(0)               # per-unit pay only: no amount to earn toward
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
    units, unit_earned = _unit_rows(plan, person, loaded, today, week_start, factor=factor,
                                    on_days=on_days, total_days=total_days)
    return {
        "membership": str(person.membership_id), "name": name_of(person.membership.user),
        "full_amount": float(money(full_amount)), "amount": float(money(amount)),
        "prorated": on_days < total_days, "days_on": on_days, "days": total_days,
        "joined_on": person.joined_on.isoformat() if person.joined_on else None,
        "left_on": person.left_on.isoformat() if person.left_on else None,
        "earned": float(money(earned + unit_earned)),
        "earned_components": float(money(earned)), "earned_units": float(money(unit_earned)),
        "components": rows, "units": units,
        "via": loaded.via.get((plan.pk, person.membership_id), []),
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
    for plan_id, members in _team_members(plans).items():
        out[plan_id] |= set(members)
    return out


def team_counts(teams) -> dict:
    """{team id: how many people a plan naming it would count}."""
    from apps.tenancy.models import Role
    from apps.work.models import ClientTeamMember

    out = defaultdict(int)
    for row in ClientTeamMember.all_objects.filter(
            team__in=teams, membership__role=Role.ECC,
            membership__revoked_at__isnull=True).select_related("membership", "team"):
        if row.membership.client_company_id == row.team.client_company_id:
            out[row.team_id] += 1
    return out


def per_unit_text(row) -> str:
    """A person's per-unit pay in one line, for the Payroll list."""
    return "; ".join(f"{u['name']}: {u['text']}" for u in row.get("units") or [] if u.get("text"))


def strip_amounts(row) -> dict:
    """An assistant's copy of a row: achievement, no dollars."""
    out = {k: v for k, v in row.items()
           if k not in ("full_amount", "amount", "earned", "earned_components", "earned_units",
                        "next")}
    out["components"] = [{k: v for k, v in c.items() if k not in ("earned", "next")}
                         for c in row.get("components", [])]
    out["units"] = [{k: v for k, v in u.items()
                     if k not in ("rate", "rate_text", "total", "earned", "text")}
                    for u in row.get("units", [])]
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


@contextmanager
def _at_row(field, index):
    """A refusal about one row of a plan's components, per-unit pay or people
    says which row it is (`row`, from 0, as sent), so the form can point at it."""
    try:
        yield
    except SetupError as exc:
        if "row" in exc.extra:
            raise
        raise SetupError(str(exc), field, **{**exc.extra, "row": index}) from None


def _clean_components(scorecard, plan_period, raw, *, units=False) -> list:
    if raw in (None, ""):
        raw = []
    if not isinstance(raw, list):
        raise SetupError("A plan has two to five components.", "components")
    if not raw and units:
        return []
    if not raw:
        raise SetupError("A plan needs two to five components, per-unit pay, or both.",
                         "components")
    if not FEWEST_COMPONENTS <= len(raw) <= MOST_COMPONENTS:
        raise SetupError("A plan has two to five components"
                         + (", or none beside its per-unit pay." if units else "."),
                         "components")
    kpis = {str(k.pk): k for k in Kpi.objects.filter(scorecard=scorecard,
                                                     archived_at__isnull=True)}
    out, seen, total = [], set(), Decimal(0)
    for i, row in enumerate(raw):
        with _at_row("components", i):
            if not isinstance(row, dict):
                raise SetupError("Each component is a KPI and a weight.", "components")
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


def _clean_units(scorecard, plan_period, raw) -> list:
    """Per-unit pay: up to three company KPIs, each with its rate."""
    if raw in (None, ""):
        return []
    if not isinstance(raw, list) or len(raw) > MOST_UNIT_RULES:
        raise SetupError("A plan has up to three per-unit rules.", "units")
    kpis = {str(k.pk): k for k in Kpi.objects.filter(scorecard=scorecard,
                                                     archived_at__isnull=True)}
    out, seen = [], set()
    for i, row in enumerate(raw):
        with _at_row("units", i):
            if not isinstance(row, dict):
                raise SetupError("Each per-unit rule is a KPI and a rate.", "units")
            kpi = kpis.get(str(row.get("kpi") or ""))
            if kpi is None:
                raise SetupError("Each per-unit rule is one of this scorecard's KPIs.", "units")
            if kpi.pk in seen:
                raise SetupError(f"{kpi.name} is paid per unit twice.", "units")
            seen.add(kpi.pk)
            if kpi.per_person:
                raise SetupError(f"{kpi.name} has a reading per person. Per-unit pay counts one "
                                 "number for the company, such as its Google reviews.", "units")
            if kpi.is_computed:
                raise SetupError(f"{kpi.name} is worked out from two other KPIs. Per-unit pay "
                                 "counts a KPI's own readings.", "units")
            if kpi.direction != Kpi.Direction.HIGHER:
                raise SetupError(f"{kpi.name} isn't a KPI where more is better, so it can't be "
                                 "paid per unit.", "units")
            if kpi.kind not in UNIT_KINDS:
                raise SetupError(f"{kpi.name} is a {kpi.get_kind_display().lower()}. Per-unit pay "
                                 "counts a Count, Number or Money KPI.", "units")
            if plan_period == BonusPlan.Period.MONTHLY and kpi.cadence == Kpi.Cadence.QUARTERLY:
                raise SetupError(f"{kpi.name} is read quarterly, longer than a monthly plan.",
                                 "units")
            rate = _decimal(row, "rate", "a rate per unit", required=True, high=Decimal(100000))
            if rate <= 0:
                raise SetupError("A rate per unit is more than $0.", "units")
            out.append({"kpi": kpi, "rate": rate})
    return out


def _clean_teams(company, raw) -> list:
    """Whole teams on the plan: live teams of the plan's own company, once."""
    from apps.work.teams import live_teams

    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise SetupError("Each team on a plan is one of the company's own teams, once.", "teams")
    ids = [str((r.get("team") if isinstance(r, dict) else r) or "") for r in raw]
    found = {str(t.pk): t for t in live_teams(company).filter(
        pk__in=[i for i in ids if setup_is_uuid(i)])}
    if len(found) != len(set(ids)) or len(ids) != len(set(ids)):
        raise SetupError("Each team on a plan is one of the company's own teams, once.", "teams")
    return [found[i] for i in ids]


def _clean_people(company, plan_start, plan_end, raw, *, teams=False) -> list:
    from apps.tenancy.models import CLIENT_ROLES, Membership

    if raw in (None, "") and teams:
        return []
    if not isinstance(raw, list) or (not raw and not teams):
        raise SetupError("Name at least one person or team on the plan.", "people")
    ids = [str(r.get("membership") or "") for r in raw]
    found = {str(m.pk): m for m in Membership.objects.filter(
        pk__in=[i for i in ids if setup_is_uuid(i)], client_company=company,
        role__in=CLIENT_ROLES, revoked_at__isnull=True)}
    if len(found) != len(set(ids)) or len(ids) != len(set(ids)):
        raise SetupError("Each person on a plan is a portal user of the company, once.",
                         "people")
    out = []
    for i, row in enumerate(raw):
        with _at_row("people", i):
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
    units = _clean_units(scorecard, period, merged.get("units"))
    components = _clean_components(scorecard, period, merged.get("components"),
                                   units=bool(units))
    if components:
        amount = _decimal(merged, "amount", "the amount per person", required=True,
                          low=Decimal(0))
    else:
        amount = Decimal(0)                    # per-unit pay only
    split = merged.get("unit_split") or BonusPlan.UnitSplit.EACH
    if split not in BonusPlan.UnitSplit.values:
        raise SetupError("Per-unit pay goes to each person in full, or is one pool split "
                         "evenly.", "unit_split")
    straight = bool(merged.get("straight_line"))
    cap = _decimal(merged, "cap_pct", "the cap", low=Decimal(0), high=Decimal(500))
    end = P.end_of(start, period)
    teams = _clean_teams(scorecard.company, merged.get("teams"))
    return {
        "name": name, "period": period, "period_start": start, "amount": money(amount),
        "straight_line": straight, "cap_pct": (cap if cap is not None else Decimal(120)),
        "unit_split": split, "components": components, "units": units, "teams": teams,
        "people": _clean_people(scorecard.company, start, end, merged.get("people"),
                                teams=bool(teams)),
    }


PLAN_FIELDS = ("name", "period", "period_start", "amount", "straight_line", "cap_pct",
               "unit_split")


def _write_parts(plan, clean):
    BonusComponent.all_objects.filter(plan=plan).delete()
    BonusUnitRule.all_objects.filter(plan=plan).delete()
    BonusPerson.all_objects.filter(plan=plan).delete()
    BonusTeam.all_objects.filter(plan=plan).delete()
    for i, c in enumerate(clean["components"]):
        BonusComponent.all_objects.create(tenant_id=plan.tenant_id, plan=plan, kpi=c["kpi"],
                                          weight=c["weight"], target_value=c["target_value"],
                                          tiers=c["tiers"], position=i)
    for i, u in enumerate(clean["units"]):
        BonusUnitRule.all_objects.create(tenant_id=plan.tenant_id, plan=plan, kpi=u["kpi"],
                                         rate=u["rate"], position=i)
    for team in clean["teams"]:
        BonusTeam.all_objects.create(tenant_id=plan.tenant_id, plan=plan, team=team)
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
        created_by=actor, **{k: clean[k] for k in PLAN_FIELDS})
    _write_parts(plan, clean)
    audit(scorecard.company, actor, "scorecard.bonus_plan_created", name=plan.name,
          plan=str(plan.pk), period=period_label(plan))
    return plan


@transaction.atomic
def update_plan(plan, data, actor) -> BonusPlan:
    plan = BonusPlan.all_objects.select_for_update().get(pk=plan.pk)
    _refuse_closed(plan)
    clean = clean_plan(plan.scorecard, data, plan)
    for key in PLAN_FIELDS:
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
    """The next period's plan, the same in every way: people and teams,
    amounts, components, weights, targets and tiers, per-unit pay and its
    split. Someone who joined part-way is on the next period from its start;
    someone who left part-way is not on it."""
    start = P.next_start(plan.period_start, plan.period)
    if BonusPlan.all_objects.filter(series=plan.series, period_start=start).exists():
        raise SetupError(f"{plan.name} for {period_label(plan.period, start)} is already "
                         "there.")
    new = BonusPlan.all_objects.create(
        tenant_id=plan.tenant_id, scorecard=plan.scorecard, series=plan.series,
        name=plan.name, period=plan.period, period_start=start, amount=plan.amount,
        straight_line=plan.straight_line, cap_pct=plan.cap_pct, unit_split=plan.unit_split,
        copied_from=plan, created_by=actor)
    for c in BonusComponent.all_objects.filter(plan=plan):
        BonusComponent.all_objects.create(tenant_id=plan.tenant_id, plan=new, kpi_id=c.kpi_id,
                                          weight=c.weight, target_value=c.target_value,
                                          tiers=c.tiers, position=c.position)
    for u in BonusUnitRule.all_objects.filter(plan=plan):
        BonusUnitRule.all_objects.create(tenant_id=plan.tenant_id, plan=new, kpi_id=u.kpi_id,
                                         rate=u.rate, position=u.position)
    for t in BonusTeam.all_objects.filter(plan=plan, team__archived_at__isnull=True):
        BonusTeam.all_objects.create(tenant_id=plan.tenant_id, plan=new, team_id=t.team_id)
    for p in BonusPerson.all_objects.filter(plan=plan):
        if p.left_on is not None:
            continue
        BonusPerson.all_objects.create(tenant_id=plan.tenant_id, plan=new,
                                       membership_id=p.membership_id, amount=p.amount)
    audit(plan.scorecard.company, actor, "scorecard.bonus_plan_copied", name=new.name,
          plan=str(new.pk), period=period_label(new), **{"from": period_label(plan)})
    return new


def _snapshot(plan, today, loaded=None):
    week_start = plan.scorecard.week_start
    loaded = loaded or Loaded([plan])
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
    # Per-unit pay reads the company's number: one line for everyone on it.
    for rule in loaded.units[plan.pk]:
        kpi = rule.kpi
        then = next(({r["period_start"]: r["value"] for r in u.get("readings", [])}
                     for old in frozen.values() for u in (old.detail or {}).get("units", [])
                     if u.get("kpi") == str(kpi.pk)), None)
        if then is None:
            continue
        mine = loaded.company_readings.get(kpi.pk, {})
        for s in kpi_starts(plan, kpi, week_start):
            now, was = num(mine.get(s)), then.get(s.isoformat())
            if now != was:
                out.append({"membership": "", "name": "Everyone on the plan", "kpi": kpi.name,
                            "period": P.short_label(s, kpi.cadence), "frozen": was,
                            "now": now})
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
    loaded = Loaded([plan])                     # closed: its people are those it froze
    closed_at = plan.closed_at
    plan.closed_at = None                       # worked out live, once
    rows = _snapshot(plan, today, loaded)
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
    units = list(BonusUnitRule.all_objects.filter(plan=plan).select_related("kpi"))
    teams = [t for t in BonusTeam.all_objects.filter(plan=plan).select_related("team")
             .order_by("team__name") if t.team.archived_at is None]
    people = list(BonusPerson.all_objects.filter(plan=plan).select_related("membership__user"))
    out = {
        "id": str(plan.pk), "name": plan.name, "period": plan.period,
        "period_start": plan.period_start.isoformat(), "period_label": period_label(plan),
        "amount": str(plan.amount), "straight_line": plan.straight_line,
        "cap_pct": float(plan.cap_pct), "closed": plan.closed_at is not None,
        "unit_split": plan.unit_split,
        "components": [{"kpi": str(c.kpi_id), "name": c.kpi.name, "weight": float(c.weight),
                        "target_value": None if c.target_value is None
                        else float(c.target_value), "tiers": c.tiers} for c in comps],
        "units": [{"kpi": str(u.kpi_id), "name": u.kpi.name,
                   "rate": f"{Decimal(u.rate).normalize():f}"} for u in units],
        "teams": [{"team": str(t.team_id), "name": t.team.name} for t in teams],
        "people": [{"membership": str(p.membership_id), "name": name_of(p.membership.user),
                    "amount": None if p.amount is None else str(p.amount),
                    "joined_on": p.joined_on.isoformat() if p.joined_on else None,
                    "left_on": p.left_on.isoformat() if p.left_on else None}
                   for p in people],
    }
    if for_edit:
        for key in ("components", "units", "teams"):
            out[key] = [{k: v for k, v in c.items() if k != "name"} for c in out[key]]
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
        "amount": float(plan.amount), "unit_split": plan.unit_split,
        **({"totals": totals} if totals is not None else {}),
    }


def totals_of(rows) -> dict:
    return {"people": len(rows),
            "earned": float(sum((Decimal(str(r["earned"])) for r in rows), Decimal(0))),
            "full": float(sum((Decimal(str(r.get("amount", r["full_amount"])))
                               for r in rows), Decimal(0)))}
