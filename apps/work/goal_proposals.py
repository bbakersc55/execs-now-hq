"""Goals a client owner proposes (owner, 2026-10-07).

A client never creates a goal (FR-3.35a). A **client owner** may propose one;
it waits for the practice, and only the practice owner or an assigned associate
turns it into a goal or declines it. Everything is audited with who did it.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.tenancy.models import AuditEvent
from apps.work.models import Goal, GoalProposal

State = GoalProposal.State

#: How many may wait at once for one company. A queue the practice has not
#: answered is not made better by a longer one.
MAX_PENDING = 10
TITLE_MAX = 255


class ProposalRefused(ValueError):
    """Said to the person in its own words."""


def _title(value) -> str:
    title = " ".join((value or "").split()) if isinstance(value, str) else ""
    if not title:
        raise ProposalRefused("Say what the goal is.")
    if len(title) > TITLE_MAX:
        raise ProposalRefused(f"A goal is at most {TITLE_MAX} characters.")
    return title


@transaction.atomic
def propose(company, *, title, why="", actor):
    title = _title(title)
    waiting = GoalProposal.all_objects.filter(
        tenant_id=company.tenant_id, client_company=company, state=State.PENDING).count()
    if waiting >= MAX_PENDING:
        raise ProposalRefused(
            f"{waiting} proposed goals are already waiting for an answer. "
            "Give the practice a chance to answer those first.")
    proposal = GoalProposal.all_objects.create(
        tenant_id=company.tenant_id, client_company=company, proposed_by=actor,
        title=title, why=(why or "").strip() if isinstance(why, str) else "")
    AuditEvent.all_objects.create(
        tenant_id=company.tenant_id, actor=actor, verb="goal.proposed",
        target_type="company", target_id=company.pk,
        payload={"proposal": str(proposal.pk), "title": title})
    return proposal


def _decide(proposal, state, *, actor, note=""):
    if proposal.state != State.PENDING:
        raise ProposalRefused("That proposal has already been answered.")
    proposal.state = state
    proposal.decided_by = actor
    proposal.decided_at = timezone.now()
    proposal.decision_note = (note or "").strip() if isinstance(note, str) else ""


@transaction.atomic
def accept(proposal, *, actor, title=None, note=""):
    """It becomes a goal: the practice's to own, word and measure from here.
    `title` is the practice's wording if they changed it; the proposal keeps
    the client's."""
    wording = _title(title) if title is not None else proposal.title
    _decide(proposal, State.ACCEPTED, actor=actor, note=note)
    goal = Goal.all_objects.create(
        tenant_id=proposal.tenant_id, client_company=proposal.client_company,
        owner=actor, title=wording, description=proposal.why)
    proposal.goal = goal
    proposal.save(update_fields=["state", "decided_by", "decided_at", "decision_note",
                                 "goal", "updated_at"])
    AuditEvent.all_objects.create(
        tenant_id=proposal.tenant_id, actor=actor, verb="goal.proposal_accepted",
        target_type="company", target_id=proposal.client_company_id,
        payload={"proposal": str(proposal.pk), "goal": str(goal.pk), "title": wording,
                 "proposed_title": proposal.title,
                 "proposed_by": str(proposal.proposed_by_id or "")})
    return goal


@transaction.atomic
def decline(proposal, *, actor, note=""):
    _decide(proposal, State.DECLINED, actor=actor, note=note)
    proposal.save(update_fields=["state", "decided_by", "decided_at", "decision_note",
                                 "updated_at"])
    AuditEvent.all_objects.create(
        tenant_id=proposal.tenant_id, actor=actor, verb="goal.proposal_declined",
        target_type="company", target_id=proposal.client_company_id,
        payload={"proposal": str(proposal.pk), "title": proposal.title,
                 "proposed_by": str(proposal.proposed_by_id or "")})


def for_company(company):
    """Newest first; the screen decides how far back to show."""
    return GoalProposal.all_objects.filter(
        tenant_id=company.tenant_id, client_company=company,
    ).select_related("proposed_by", "decided_by", "client_company", "goal")[:50]


def _name(user) -> str:
    return (user.full_name or user.email) if user else ""


def represent(proposal) -> dict:
    goal = proposal.goal if proposal.goal_id and proposal.goal.deleted_at is None else None
    return {
        "id": str(proposal.pk),
        "company": str(proposal.client_company_id),
        "company_name": proposal.client_company.name,
        "title": proposal.title,
        "why": proposal.why,
        "state": proposal.state,
        "state_label": proposal.get_state_display(),
        "proposed_by": _name(proposal.proposed_by),
        "proposed_at": proposal.created_at.isoformat(),
        "decided_by": _name(proposal.decided_by),
        "decided_at": proposal.decided_at.isoformat() if proposal.decided_at else None,
        "decision_note": proposal.decision_note,
        # The goal it became, and what the practice called it.
        "goal": str(goal.pk) if goal else None,
        "goal_title": goal.title if goal else "",
    }
