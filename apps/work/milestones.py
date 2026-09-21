"""Milestones on a goal — FR-4B.23 to FR-4B.25, and ruling E.

Two rules do all the work here:

1. **A derived milestone's date is read, never stored.** A task marked as a
   milestone carries `source_task`, and its `occurred_at` is computed from the
   task's completion every time it is asked for. Storing it would need a sync
   path on every status change, and a sync path is a thing that drifts —
   un-completing a task would leave a milestone claiming a date that never
   happened (FR-4B.25). The column stays null for a derived milestone; it is
   the standalone milestone's field.

2. **Eligibility is a read-path rule, not a constraint** (ruling E). Only a
   **client-visible task in this goal's own tree** may be marked, and both
   `is_client_visible` and the tree are mutable afterwards — so a `CHECK` a
   later edit can falsify would be worse than checking on the way in *and* on
   the way out. A task hidden or moved later keeps its row and loses its place
   on the client's report (FR-4B.24b).
"""

from __future__ import annotations

from apps.crm.models import Task
from apps.work.models import GoalMilestone, TaskUpdate


class MilestoneRefused(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def in_goal_tree(task, goal) -> bool:
    """A task filed under the goal, or under one of its projects."""
    if task.goal_id == goal.pk:
        return True
    return task.project_id is not None and task.project.goal_id == goal.pk


def check_eligible(task, goal) -> None:
    """Ruling E, stated in the words the refusal is read in."""
    if not in_goal_tree(task, goal):
        raise MilestoneRefused(
            "That task is not under this goal. A goal's timeline is that goal's "
            "own — a task from elsewhere cannot be a beat on it.")
    if not task.is_client_visible:
        raise MilestoneRefused(
            "That task is hidden from the client, so it cannot be a milestone. A "
            "milestone is a beat on the client's timeline, and the title alone "
            "would show them work they are not meant to see.")


def completion_date(task):
    """When the task was completed, or None if it is not done now.

    Read from the `task_update` trail, which is where the fact already lives;
    the task's own `updated_at` stands in only when no status update recorded it
    (a task created done, or one completed before the trail existed).
    """
    if task.status != Task.Status.DONE:
        return None
    update = (TaskUpdate.all_objects
              .filter(tenant_id=task.tenant_id, task_id=task.pk,
                      kind=TaskUpdate.Kind.STATUS_CHANGED,
                      to_value=Task.Status.DONE)
              .order_by("-created_at").first())
    return (update.created_at if update else task.updated_at).date()


def occurred_on(milestone):
    """The date this beat happened — derived for a task, stored otherwise."""
    if milestone.source_task_id is None:
        return milestone.occurred_at
    return completion_date(milestone.source_task)


def is_visible_to_client(milestone) -> bool:
    """FR-4B.24b — a task hidden or moved out of the tree takes its milestone
    out of the client's report, while the row survives for the practice."""
    if milestone.source_task_id is None:
        return True
    task = milestone.source_task
    return (task.deleted_at is None and task.is_client_visible
            and in_goal_tree(task, milestone.goal))


def state_of(milestone, *, today) -> str:
    """hit · late · ahead · due — from two dates and no status column."""
    occurred = occurred_on(milestone)
    if occurred is not None:
        if milestone.due_date and occurred < milestone.due_date:
            return "ahead"
        if milestone.due_date and occurred > milestone.due_date:
            return "late"
        return "hit"
    if milestone.due_date and milestone.due_date < today:
        return "late"
    return "due"


def for_goal(goal, *, for_client: bool):
    """The goal's milestones, in order, filtered for who is looking."""
    rows = list(GoalMilestone.objects.filter(goal=goal)
                .select_related("source_task", "source_task__project", "goal"))
    if for_client:
        rows = [m for m in rows if is_visible_to_client(m)]
    return rows
