"""Marking a company as a client by hand, and undoing it (beta feedback,
2026-10-05, item D).

FR-1.6a derives `is_client_company` from a contact reaching the won stage of
the sales pipeline, and for a year that was the only way in. A client who
arrives by referral never passes through the pipeline, so the practice owner
may now say so directly.

**What marking sets, compared with reaching Closed Won.** Closed Won does four
things: it records the stage change, runs that stage's automations, gives the
contact the `client` type, and flags the company. Marking does **one**: it
flags the company. No contact is moved, no contact's type changes, and no
stage automation runs, because no stage changed and `pipeline.change_stage` is
never called. Everything that keys on a client company then works for it: the
work pickers, portal access, seats, assignments.

**Undoing** is for a company marked by mistake, so it is allowed only while
nothing has been built on the mark (`blockers`). It never deletes or detaches
anything to make itself possible.
"""

from __future__ import annotations

from apps.crm.models import Pipeline, StageChange, StageSemantic, Task
from apps.tenancy.models import AuditEvent, ClientAssignment, Membership
from apps.work.models import Goal, GoalReportExport, Project

BY_HAND = "marked by the practice owner"


class ClientMarkRefused(Exception):
    def __init__(self, message, blockers=None):
        super().__init__(message)
        self.blockers = blockers or []


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def blockers(company) -> list[str]:
    """Why this company cannot stop being a client, in sentences. Empty means
    it can."""
    tenant_id = company.tenant_id
    found = []

    won = (StageChange.all_objects
           .filter(tenant_id=tenant_id, contact__company=company,
                   contact__deleted_at__isnull=True,
                   to_stage__semantic=StageSemantic.WON,
                   pipeline__kind=Pipeline.Kind.SALES)
           .select_related("contact", "to_stage").order_by("created_at").first())
    if won is not None:
        name = f"{won.contact.first_name} {won.contact.last_name}".strip() or "A contact"
        found.append(f"{name} reached {won.to_stage.label} on the sales pipeline, which is "
                     "what makes this a client company.")

    users = Membership.all_objects.filter(
        tenant_id=tenant_id, client_company=company, revoked_at__isnull=True).count()
    if users:
        found.append(f"{_count(users, 'person has', 'people have')} portal access. "
                     "Remove their access first.")

    work = [
        (Goal.all_objects.filter(tenant_id=tenant_id, client_company=company,
                                 deleted_at__isnull=True).count(), "goal", "goals"),
        (Project.all_objects.filter(tenant_id=tenant_id, client_company=company,
                                    deleted_at__isnull=True).count(), "project", "projects"),
        (Task.all_objects.filter(tenant_id=tenant_id, client_company=company,
                                 deleted_at__isnull=True).count(), "task", "tasks"),
    ]
    filed = [_count(n, one, many) for n, one, many in work if n]
    if filed:
        found.append(f"It has {', '.join(filed)} filed under it. Move or delete them first.")

    assigned = ClientAssignment.all_objects.filter(
        tenant_id=tenant_id, company=company, removed_at__isnull=True).count()
    if assigned:
        found.append(f"{_count(assigned, 'associate is', 'associates are')} assigned to it. "
                     "Remove the assignment first.")

    if GoalReportExport.all_objects.filter(tenant_id=tenant_id, client_company=company).exists():
        found.append("A value report has been exported for it.")
    return found


def mark(company, *, actor):
    """Flag the company. Nothing else: see the module docstring."""
    if company.is_client_company:
        return company
    company.is_client_company = True
    company.save(update_fields=["is_client_company", "updated_at"])
    AuditEvent.all_objects.create(
        tenant_id=company.tenant_id, actor=actor, verb="company.flagged",
        target_type="company", target_id=company.pk,
        payload={"is_client_company": True, "because": BY_HAND},
    )
    return company


def unmark(company, *, actor):
    if not company.is_client_company:
        return company
    why_not = blockers(company)
    if why_not:
        raise ClientMarkRefused(
            "This company cannot stop being a client yet.", blockers=why_not)
    company.is_client_company = False
    company.save(update_fields=["is_client_company", "updated_at"])
    AuditEvent.all_objects.create(
        tenant_id=company.tenant_id, actor=actor, verb="company.unflagged",
        target_type="company", target_id=company.pk,
        payload={"is_client_company": False, "because": "unmarked by the practice owner"},
    )
    return company

