"""Derived status for goals and projects (FR-3.10).

The value is computed at read time and **never stored**: a stored rollup drifts
the moment a child changes outside the code path that wrote it. A manual
`status_override` wins; clearing it returns the entity to the derived value.

**The precedence order is this build's choice — the docs name the behaviour,
not the algorithm.** Ignoring cancelled children:

    waiting_on_client > blocked > in_progress > done > not_started

`waiting_on_client` outranks everything because FR-3.8 says the difference
between *we are stuck* and *you are the blocker* is the most useful thing a
progress report can say — so if any child is waiting on the client, the parent
says so where the client will see it. A parent is only `done` when every
child is, and only `cancelled` when every child is.
"""

from __future__ import annotations

from apps.crm.models import Task

S = Task.Status

# Most-to-least "wants attention".
PRECEDENCE = [S.WAITING_ON_CLIENT, S.BLOCKED, S.IN_PROGRESS, S.DONE, S.NOT_STARTED]


def roll_up(statuses) -> str:
    """The derived status for a set of child statuses."""
    values = list(statuses)
    if not values:
        return S.NOT_STARTED
    if all(v == S.CANCELLED for v in values):
        return S.CANCELLED
    live = [v for v in values if v != S.CANCELLED]
    if all(v == S.DONE for v in live):
        return S.DONE
    for candidate in PRECEDENCE:
        if candidate not in live:
            continue
        # Reaching DONE here means some children are done and the rest are
        # not started — that is work in progress, not "done" and not "not
        # started". (All-done was handled above.)
        return S.IN_PROGRESS if candidate == S.DONE else candidate
    return S.NOT_STARTED


def child_statuses(entity) -> list:
    """A project's children are its tasks. A goal's are its projects' derived
    statuses plus any task attached straight to it (FR-3.5 allows both)."""
    from apps.work.models import Goal, Project

    if isinstance(entity, Project):
        return list(entity.tasks.filter(deleted_at__isnull=True)
                    .values_list("status", flat=True))
    if isinstance(entity, Goal):
        statuses = [
            status_of(project)
            for project in entity.projects.filter(deleted_at__isnull=True)
        ]
        statuses += list(entity.tasks.filter(deleted_at__isnull=True, project__isnull=True)
                         .values_list("status", flat=True))
        return statuses
    raise TypeError(f"{type(entity).__name__} has no derived status.")


def status_of(entity) -> str:
    """The status to show: the override if set, else the rollup."""
    return entity.status_override or roll_up(child_statuses(entity))


def is_derived(entity) -> bool:
    return not entity.status_override
