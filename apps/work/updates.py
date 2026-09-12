"""Writing `task_update` rows — FR-3.15 to FR-3.18.

Every digest downstream is assembled from these rows and never from diffing
current state, so this is the only place they are written. Two things matter
more than the mechanics:

1. **`client_facing_line` is a field, not a comment** (FR-3.17). On a status
   change a tenant user is *prompted, not forced*, for one line on what the
   change means for the client; that line is what turns a digest from a
   changelog into a report.
2. **`is_client_actor` marks client-originated updates**, which are visible but
   never trigger a digest to their own author.
"""

from __future__ import annotations

from apps.tenancy.models import CLIENT_ROLES
from apps.work.models import Comment, TaskUpdate

K = TaskUpdate.Kind


def target_kwargs(entity) -> dict:
    """Which of the three FKs this entity fills."""
    from apps.crm.models import Task
    from apps.work.models import Goal, Project

    if isinstance(entity, Task):
        return {"task": entity}
    if isinstance(entity, Project):
        return {"project": entity}
    if isinstance(entity, Goal):
        return {"goal": entity}
    raise TypeError(f"{type(entity).__name__} cannot carry updates.")


def record(entity, kind, *, actor=None, role=None, from_value="", to_value="",
           client_facing_line="", source=TaskUpdate.Source.USER, source_id=None):
    return TaskUpdate.all_objects.create(
        tenant_id=entity.tenant_id,
        kind=kind,
        from_value=from_value or "",
        to_value=to_value or "",
        client_facing_line=(client_facing_line or "").strip(),
        actor=actor,
        source=source,
        source_id=source_id,
        is_client_actor=role in CLIENT_ROLES,
        **target_kwargs(entity),
    )


def record_comment(comment: Comment, *, role=None):
    """FR-3.15 — a comment is an update.

    `to_value` carries the visibility because digest assembly must include
    shared comments and exclude internal ones (FR-3.19), and it should not have
    to join back to the comment to find out.
    """
    entity = comment.task or comment.project or comment.goal
    return record(
        entity, K.COMMENT_ADDED, actor=comment.author, role=role,
        to_value=comment.visibility, source_id=comment.pk,
    )


def is_digestible(update: TaskUpdate) -> bool:
    """Whether an update may appear in a client's digest at all (FR-3.19).

    Client-visibility of the task is checked by the assembler, which knows the
    recipient; this is the part that is a property of the update itself.
    """
    if update.kind == K.COMMENT_ADDED:
        return update.to_value == Comment.Visibility.SHARED
    return True
