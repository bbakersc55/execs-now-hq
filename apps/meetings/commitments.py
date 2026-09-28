"""Waiting on others (owner, 2026-09-28): the open commitments people outside
the practice made in meetings, and what the practice does about them."""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from apps.crm import permissions as crm_perms
from apps.meetings.models import Commitment
from apps.tenancy.models import AuditEvent, CLIENT_ROLES

DONE_TASK = ("done", "cancelled")


def scoped(request, qs=None):
    """Staff only. A CF sees commitments by people they can see, or at the
    companies they are assigned to — the same rule as contacts."""
    from apps.crm.models import Contact

    qs = Commitment.objects.all() if qs is None else qs
    role = crm_perms.role_of(request)
    if role in CLIENT_ROLES or role is None:
        return qs.none()
    if role == crm_perms.Role.CF:
        visible = crm_perms.contact_queryset_for(request, Contact.objects.all())
        return qs.filter(Q(contact__in=visible)
                         | Q(company_id__in=crm_perms.assigned_company_ids(request)))
    return qs


def settle_portal(qs):
    """A commitment assigned in the portal is done when the client's task is:
    read from the task, so the two never disagree."""
    finished = qs.filter(state=Commitment.State.OPEN, outcome=Commitment.Outcome.PORTAL,
                         task__status__in=DONE_TASK)
    finished.update(state=Commitment.State.DONE, done_at=timezone.now(),
                    updated_at=timezone.now())


def overdue_filter(today=None):
    today = today or timezone.localdate()
    return (Q(follow_up_date__lt=today)
            | Q(follow_up_date__isnull=True, due_date__lt=today))


def represent(row, today=None) -> dict:
    today = today or timezone.localdate()
    when = row.follow_up_date or row.due_date
    return {
        "id": str(row.pk), "state": row.state, "outcome": row.outcome,
        "outcome_label": row.get_outcome_display(),
        "owner_name": row.owner_name, "owner_kind": row.owner_kind,
        "contact": str(row.contact_id) if row.contact_id else None,
        "company": str(row.company_id) if row.company_id else None,
        "company_name": row.company.name if row.company_id else "",
        "text": row.text,
        "due_date": row.due_date.isoformat() if row.due_date else None,
        "follow_up_date": row.follow_up_date.isoformat() if row.follow_up_date else None,
        "overdue": row.state == Commitment.State.OPEN and when is not None and when < today,
        "task": str(row.task_id) if row.task_id else None,
        "meeting": ({"id": str(row.meeting_id), "title": row.meeting.title,
                     "date": row.meeting.meeting_date.isoformat()
                     if row.meeting.meeting_date else None}
                    if row.meeting_id else None),
        "source_excerpt": row.source_excerpt,
        "done_at": row.done_at.isoformat() if row.done_at else None,
    }


def mark_done(row, *, actor, role):
    """Done. The practice's follow-up check closes with it; a client's portal
    task is closed too, recorded as the practice's change."""
    from apps.work import services as work_services

    row.state, row.done_at, row.done_by = Commitment.State.DONE, timezone.now(), actor
    row.save(update_fields=["state", "done_at", "done_by", "updated_at"])
    if row.task_id and row.task.status not in DONE_TASK:
        work_services.apply_task_changes(row.task, actor=actor, role=role,
                                         changes={"status": "done"})
    AuditEvent.all_objects.create(
        tenant_id=row.tenant_id, actor=actor, verb="commitment.done",
        target_type="commitment", target_id=row.pk, payload={"outcome": row.outcome})


def snooze(row, *, actor, role, days=None, until=None):
    """Look again later: the follow-up date moves, and a follow-up task's due
    date with it. A client's own task keeps its date — that is theirs."""
    from apps.work import services as work_services

    base = max(row.follow_up_date or timezone.localdate(), timezone.localdate())
    new = until or base + timedelta(days=int(days or 7))
    before = row.follow_up_date
    row.follow_up_date = new
    row.save(update_fields=["follow_up_date", "updated_at"])
    if row.outcome == Commitment.Outcome.FOLLOW_UP and row.task_id \
            and row.task.status not in DONE_TASK:
        work_services.apply_task_changes(row.task, actor=actor, role=role,
                                         changes={"due_date": new})
    AuditEvent.all_objects.create(
        tenant_id=row.tenant_id, actor=actor, verb="commitment.snoozed",
        target_type="commitment", target_id=row.pk,
        payload={"from": before.isoformat() if before else None, "to": new.isoformat()})
    return row
