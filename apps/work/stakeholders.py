"""Stakeholders — FR-3.20, 3.20a, 3.21, 3.33.

**A stakeholder is a Contact, not a User.** Digests go to the contact's primary
email whether or not that person has ever signed in; a client's CFO who reads
the weekly report and never opens the portal is the common case, not an edge
one. Where a contact does have a login, the portal and the digest are two views
of the same entitlement — there is no second subscription list.

Attachments live at goal, project or task level. For any task the **effective**
stakeholders are the union of all three, de-duplicated per person, with the
**most specific attachment deciding cadence**: task beats project beats goal.
Nothing about that is stored.
"""

from __future__ import annotations

from django.db.models import Q

from apps.crm.models import Task
from apps.work.models import Cadence, Stakeholder

# Most specific first — the order that decides whose cadence wins.
LEVELS = ("task", "project", "goal")


def rows_for_task(task: Task):
    """Every stakeholder row that reaches this task, most specific first."""
    query = Stakeholder.objects.filter(task=task)
    if task.project_id:
        query = query | Stakeholder.objects.filter(project_id=task.project_id)
    goal_id = task.goal_id or (task.project.goal_id if task.project_id else None)
    if goal_id:
        query = query | Stakeholder.objects.filter(goal_id=goal_id)
    return query.select_related("contact").distinct()


def specificity(row: Stakeholder) -> int:
    if row.task_id:
        return 0
    if row.project_id:
        return 1
    return 2


def effective_for_task(task: Task) -> dict:
    """{contact_id: stakeholder} — one row per person, the most specific one.

    FR-3.20a. Two rows for the same person at different levels are not a
    duplicate to be cleaned up: they are a deliberate override.
    """
    winner: dict = {}
    for row in sorted(rows_for_task(task), key=specificity):
        winner.setdefault(row.contact_id, row)
    return winner


def entities_for(row: Stakeholder):
    """The tasks an attachment covers. A goal- or project-level row covers
    everything under it, including tasks added later."""
    if row.task_id:
        return Task.objects.filter(pk=row.task_id, deleted_at__isnull=True)
    if row.project_id:
        return Task.objects.filter(project_id=row.project_id, deleted_at__isnull=True)
    return Task.objects.filter(deleted_at__isnull=True).filter(under_goal(row.goal_id))


def under_goal(goal_id):
    """Filed directly on the goal, or on a project beneath it."""
    return Q(goal_id=goal_id) | Q(project__goal_id=goal_id)


def tasks_for_contact(tenant, contact_id):
    """Every task any of this contact's attachments reaches, with the cadence
    that wins for each. Used by digest generation."""
    rows = (Stakeholder.objects.filter(contact_id=contact_id, is_muted=False)
            .select_related("contact"))
    reach: dict = {}
    for row in sorted(rows, key=specificity):
        for task in entities_for(row):
            reach.setdefault(task.pk, (task, row))
    return reach


def contacts_with_attachments(tenant):
    return (Stakeholder.objects.filter(is_muted=False)
            .values_list("contact_id", flat=True).distinct())


def cadence_of(row: Stakeholder) -> str:
    return row.cadence or Cadence.WEEKLY
