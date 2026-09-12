"""Task-engine operations. Every state change here writes its `task_update`.

Nothing else in the codebase mutates a task's status, assignee or due date:
if it did, a digest would be assembled from an event log with holes in it.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.crm.models import Task
from apps.tenancy.models import AuditEvent, CLIENT_ROLES
from apps.work import updates
from apps.work.models import Comment, Stakeholder, TaskChecklistItem, TaskUpdate

K = TaskUpdate.Kind
S = Task.Status
# The fields whose change is an event in its own right (FR-3.15).
TRACKED = {"status": K.STATUS_CHANGED, "assignee": K.ASSIGNEE_CHANGED,
           "due_date": K.DUE_CHANGED}


def _label(field, value):
    if value is None or value == "":
        return ""
    if field == "assignee":
        return value.full_name or value.email
    return str(value)


def creator_of(task):
    """The user who created a task, from its own event log.

    `task` has no `created_by` column and does not need one: the CREATED
    update already records who and when, and FR-3.9a's "tasks they created"
    is the only question that asks.
    """
    created = (TaskUpdate.all_objects.filter(task=task, kind=K.CREATED)
               .order_by("created_at").first())
    return created.actor if created else None


@transaction.atomic
def create_task(*, tenant, actor, role, client_facing_line="", **fields):
    """FR-3.11 — client-visible by default when the task has a client company,
    hidden otherwise. FR-3.37 — a client's own task is marked as theirs."""
    is_client = role in CLIENT_ROLES
    fields.setdefault("is_client_visible", fields.get("client_company") is not None)
    task = Task.objects.create(tenant=tenant, created_by_client=is_client, **fields)
    updates.record(task, K.CREATED, actor=actor, role=role,
                   to_value=task.title, client_facing_line=client_facing_line)
    return task


@transaction.atomic
def apply_task_changes(task, *, actor, role, changes: dict, client_facing_line=""):
    """Apply a validated change set and record exactly what moved.

    The client-facing line rides on the status change when there is one (that
    is where the prompt appears), and becomes a `narrative` update on its own
    when nothing else changed (FR-3.18).
    """
    recorded, touched = [], []
    for field, kind in TRACKED.items():
        if field not in changes:
            continue
        before = getattr(task, field)
        after = changes[field]
        if before == after:
            continue
        setattr(task, field, after)
        touched.append(field if field != "assignee" else "assignee_id")
        recorded.append(updates.record(
            task, kind, actor=actor, role=role,
            from_value=_label(field, before), to_value=_label(field, after),
            client_facing_line=client_facing_line if kind == K.STATUS_CHANGED else "",
        ))
        if kind == K.STATUS_CHANGED and after == S.DONE:
            recorded.append(updates.record(task, K.COMPLETED, actor=actor, role=role,
                                           to_value=task.title))

    for field, value in changes.items():
        if field in TRACKED:
            continue
        if getattr(task, field) != value:
            setattr(task, field, value)
            touched.append(field if not field.endswith("_contact") else f"{field}_id")

    if touched:
        task.save(update_fields=sorted(set(touched)) + ["updated_at"])
    if client_facing_line and not any(u.kind == K.STATUS_CHANGED for u in recorded):
        recorded.append(add_narrative(task, actor=actor, role=role,
                                      line=client_facing_line))
    return recorded


def add_narrative(entity, *, actor, role, line):
    """FR-3.18 — a client-facing line at any time, without a status change."""
    return updates.record(entity, K.NARRATIVE, actor=actor, role=role,
                          client_facing_line=line)


@transaction.atomic
def add_comment(entity, *, author, role, body, visibility=None):
    """FR-3.12/3.12a. A tenant user's comment defaults to internal; a client
    user's is always shared, because that is the only kind they can see."""
    is_client = role in CLIENT_ROLES
    if is_client:
        visibility = Comment.Visibility.SHARED
    comment = Comment.objects.create(
        tenant_id=entity.tenant_id, author=author, body=body,
        visibility=visibility or Comment.Visibility.INTERNAL,
        **updates.target_kwargs(entity),
    )
    updates.record_comment(comment, role=role)
    return comment


@transaction.atomic
def set_checklist_done(item: TaskChecklistItem, *, actor, role, is_done: bool):
    if item.is_done == is_done:
        return None
    item.is_done = is_done
    item.save(update_fields=["is_done", "updated_at"])
    if not is_done:
        return None
    return updates.record(item.task, K.CHECKLIST_COMPLETED, actor=actor, role=role,
                          to_value=item.text)


@transaction.atomic
def soft_delete(entity, *, actor, verb):
    """FR-3.6 — deleting a goal or project DETACHES its children and reports
    them. Work is never deleted as a side effect of tidying the structure."""
    from apps.work.models import Goal, Project

    detached = {}
    if isinstance(entity, Goal):
        detached["projects"] = entity.projects.filter(deleted_at__isnull=True).update(goal=None)
        detached["tasks"] = entity.tasks.filter(deleted_at__isnull=True).update(goal=None)
    elif isinstance(entity, Project):
        detached["tasks"] = entity.tasks.filter(deleted_at__isnull=True).update(project=None)

    entity.deleted_at = timezone.now()
    entity.save(update_fields=["deleted_at", "updated_at"])
    AuditEvent.all_objects.create(
        tenant_id=entity.tenant_id, actor=actor, verb=verb,
        target_type=type(entity).__name__.lower(), target_id=entity.pk,
        payload={"detached": detached},
    )
    return detached


def audit_visibility_change(task, *, actor, to_visible: bool):
    """FR-3.14 — both directions are audited; the UI warns on the way to
    visible that prior activity becomes visible with it."""
    AuditEvent.all_objects.create(
        tenant_id=task.tenant_id, actor=actor, verb="task.visibility_changed",
        target_type="task", target_id=task.pk,
        payload={"is_client_visible": to_visible},
    )


def revoke_stakeholder_tokens(stakeholder: Stakeholder):
    """FR-3.33b — a removed stakeholder's cadence links stop working."""
    return stakeholder.tokens.filter(revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )
