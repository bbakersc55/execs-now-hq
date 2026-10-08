"""The order of a client company's goals (owner, 2026-10-07).

One order per company, shown the same on Work, on the practice's Value report
and in the portal:

1. **Current goals first**, in the company's `CompanyGoalOrder`; a goal that
   is not in it (made since) comes after the ones that are, by creation. So a
   company nobody has ordered reads in the order its goals were made.
2. **Historical goals after**, by creation. They are not ranked: a goal that
   was achieved or retired has no priority to argue about.

**The practice sets the order; a client proposes one** (`GoalOrderProposal`).
The proposal changes nothing until the practice accepts it, and every change
and every proposal is audited with who made it.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.tenancy.models import AuditEvent
from apps.work.models import CompanyGoalOrder, Goal, GoalOrderProposal, GoalResolution

State = GoalOrderProposal.State


class OrderRefused(ValueError):
    """Said to the person in its own words."""


def historical_ids(goals) -> set:
    """Which of these goals are historical, in one query: a goal's state is
    its latest resolution (`GoalResolution` is append-only)."""
    latest = {}
    rows = (GoalResolution.all_objects
            .filter(goal_id__in=[g.pk for g in goals])
            .order_by("goal_id", "-resolved_at", "-created_at")
            .values_list("goal_id", "resolution"))
    for goal_id, resolution in rows:
        latest.setdefault(goal_id, resolution)
    return {goal_id for goal_id, resolution in latest.items()
            if resolution in GoalResolution.HISTORICAL}


def _places(goals) -> dict:
    """Each ordered goal's place in its own company's order, in one query."""
    companies = {(g.tenant_id, g.client_company_id) for g in goals if g.client_company_id}
    places = {}
    rows = CompanyGoalOrder.all_objects.filter(
        tenant_id__in={t for t, _ in companies},
        client_company_id__in={c for _, c in companies})
    for row in rows:
        for place, goal_id in enumerate(row.order):
            places[goal_id] = place
    return places


def ordered(goals, historical=None) -> list:
    """`goals` in priority order. Safe across several companies at once: each
    company's goals keep their own order relative to each other."""
    goals = list(goals)
    historical = historical_ids(goals) if historical is None else historical
    places = _places(goals)

    def key(goal):
        place = None if goal.pk in historical else places.get(str(goal.pk))
        return (goal.pk in historical, place is None, place or 0, goal.created_at)

    return sorted(goals, key=key)


def company_goals(company) -> list:
    return list(Goal.all_objects.filter(
        tenant_id=company.tenant_id, client_company=company, deleted_at__isnull=True))


def current_goals(company) -> list:
    """The goals that have an order: every current one, in it."""
    goals = company_goals(company)
    historical = historical_ids(goals)
    return [g for g in ordered(goals, historical) if g.pk not in historical]


def _checked(company, order) -> list:
    """`order` as goals, or `OrderRefused`: it must name every current goal of
    this company exactly once and nothing else. A list built from a page that
    has since gone stale is refused rather than half-applied."""
    current = {str(g.pk): g for g in current_goals(company)}
    if not isinstance(order, list) or not all(isinstance(x, str) for x in order):
        raise OrderRefused("Send the order as a list of goal ids.")
    if len(set(order)) != len(order):
        raise OrderRefused("A goal is in that order twice.")
    if set(order) != set(current):
        raise OrderRefused("The goals have changed since this page was opened. "
                           "Reload it and order them again.")
    return [current[x] for x in order]


def _write(company, goals, *, actor) -> bool:
    """Make `goals` the company's order. True if anything moved."""
    if [g.pk for g in goals] == [g.pk for g in current_goals(company)]:
        return False
    CompanyGoalOrder.all_objects.update_or_create(
        tenant_id=company.tenant_id, client_company=company,
        defaults={"order": [str(g.pk) for g in goals], "updated_by": actor})
    return True


def _titles(goals) -> list:
    return [g.title for g in goals]


@transaction.atomic
def set_order(company, order, *, actor):
    """The practice orders the goals. Audited with the order before and after."""
    before = current_goals(company)
    goals = _checked(company, order)
    if _write(company, goals, actor=actor):
        AuditEvent.all_objects.create(
            tenant_id=company.tenant_id, actor=actor, verb="goal.reordered",
            target_type="company", target_id=company.pk,
            payload={"from": _titles(before), "to": _titles(goals)})
    return goals


@transaction.atomic
def propose(company, order, *, actor, note=""):
    """A client proposes an order. Nothing is reordered. An earlier proposal
    still waiting is superseded, and kept."""
    goals = _checked(company, order)
    if [g.pk for g in goals] == [g.pk for g in current_goals(company)]:
        raise OrderRefused("That is the order the goals are already in.")
    GoalOrderProposal.all_objects.filter(
        tenant_id=company.tenant_id, client_company=company, state=State.PENDING,
    ).update(state=State.SUPERSEDED, updated_at=timezone.now())
    proposal = GoalOrderProposal.all_objects.create(
        tenant_id=company.tenant_id, client_company=company, proposed_by=actor,
        order=[str(g.pk) for g in goals], note=(note or "").strip())
    AuditEvent.all_objects.create(
        tenant_id=company.tenant_id, actor=actor, verb="goal.order_proposed",
        target_type="company", target_id=company.pk,
        payload={"proposal": str(proposal.pk), "to": _titles(goals)})
    return proposal


def proposed_goals(proposal) -> list:
    """The proposal as it would apply today: its goals that are still current,
    in the order proposed, then any current goal it never mentioned (added
    since), in the order they are in now."""
    current = current_goals(proposal.client_company)
    by_id = {str(g.pk): g for g in current}
    named = [by_id[x] for x in proposal.order if x in by_id]
    return named + [g for g in current if g not in named]


def _decide(proposal, state, *, actor, note=""):
    if proposal.state != State.PENDING:
        raise OrderRefused("That proposal has already been answered.")
    proposal.state = state
    proposal.decided_by = actor
    proposal.decided_at = timezone.now()
    proposal.decision_note = (note or "").strip()
    proposal.save(update_fields=["state", "decided_by", "decided_at", "decision_note",
                                 "updated_at"])


@transaction.atomic
def accept(proposal, *, actor):
    """The practice accepts: the proposed order becomes the order."""
    company = proposal.client_company
    before = current_goals(company)
    goals = proposed_goals(proposal)
    _decide(proposal, State.ACCEPTED, actor=actor)
    _write(company, goals, actor=actor)
    AuditEvent.all_objects.create(
        tenant_id=company.tenant_id, actor=actor, verb="goal.order_accepted",
        target_type="company", target_id=company.pk,
        payload={"proposal": str(proposal.pk),
                 "proposed_by": str(proposal.proposed_by_id or ""),
                 "from": _titles(before), "to": _titles(goals)})
    return goals


@transaction.atomic
def decline(proposal, *, actor, note=""):
    """The practice declines: the order stays, and the client reads why."""
    _decide(proposal, State.DECLINED, actor=actor, note=note)
    AuditEvent.all_objects.create(
        tenant_id=proposal.tenant_id, actor=actor, verb="goal.order_declined",
        target_type="company", target_id=proposal.client_company_id,
        payload={"proposal": str(proposal.pk),
                 "proposed_by": str(proposal.proposed_by_id or "")})


def pending_for(company):
    return GoalOrderProposal.all_objects.filter(
        tenant_id=company.tenant_id, client_company=company, state=State.PENDING
    ).select_related("proposed_by", "client_company").first()


def last_decided_for(company):
    return GoalOrderProposal.all_objects.filter(
        tenant_id=company.tenant_id, client_company=company,
        state__in=[State.ACCEPTED, State.DECLINED],
    ).select_related("proposed_by", "decided_by", "client_company").first()


def _name(user) -> str:
    return (user.full_name or user.email) if user else ""


def represent(proposal) -> dict:
    by_id = {str(g.pk): g.title for g in company_goals(proposal.client_company)}
    pending = proposal.state == State.PENDING
    # A pending proposal reads as it would apply today; a decided one as it
    # was made, minus anything since deleted.
    goals = ([{"id": str(g.pk), "title": g.title} for g in proposed_goals(proposal)]
             if pending else
             [{"id": x, "title": by_id[x]} for x in proposal.order if x in by_id])
    return {
        "id": str(proposal.pk),
        "company": str(proposal.client_company_id),
        "company_name": proposal.client_company.name,
        "state": proposal.state,
        "state_label": proposal.get_state_display(),
        "order": goals,
        "note": proposal.note,
        "proposed_by": _name(proposal.proposed_by),
        "proposed_at": proposal.created_at.isoformat(),
        "decided_by": _name(proposal.decided_by),
        "decided_at": proposal.decided_at.isoformat() if proposal.decided_at else None,
        "decision_note": proposal.decision_note,
    }
