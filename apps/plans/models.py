"""The plans engine (P11, docs/p11_plans_engine.md).

One plan per company, and one for the practice itself (its hidden company
row), in five horizons: the three-year picture, the year's goals, the
quarter's priorities, the month's plan and the week's sprint. The plan
links what already exists: a year's item is one of the company's goals; any
item may link a goal, a project, tasks and KPIs. Nothing it links is
replaced or changed by it.

An item serves the item above it (`parent`), which is how the cascade is
read both ways. A proposal (Claude's, an AI app's, or a client's at the year
or quarter) is an item in the `proposed` state, shown in the plan's tray
until someone accepts, edits or discards it. Closing a period records what
became of its items (`PlanClose`); carrying one over is always chosen.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.tenancy.models import TenantScopedModel


class Horizon(models.TextChoices):
    PICTURE = "picture", "Three-year picture"
    YEAR = "year", "This year's goals"
    QUARTER = "quarter", "This quarter's priorities"
    MONTH = "month", "This month's plan"
    WEEK = "week", "This week's sprint"


#: Top to bottom: an item serves the horizon above its own.
ORDER = (Horizon.PICTURE, Horizon.YEAR, Horizon.QUARTER, Horizon.MONTH, Horizon.WEEK)


class PlanItem(TenantScopedModel):
    """One item on one horizon of one company's plan."""

    class Status(models.TextChoices):
        ON_TRACK = "on_track", "On track"
        OFF_TRACK = "off_track", "Off track"
        DONE = "done", "Done"
        DROPPED = "dropped", "Dropped"

    class State(models.TextChoices):
        #: In the tray: Claude's, an AI app's, or a client's at the year or quarter.
        PROPOSED = "proposed", "Proposed"
        ACCEPTED = "accepted", "On the plan"
        DISCARDED = "discarded", "Discarded"

    class Source(models.TextChoices):
        HAND = "hand", "Added by hand"
        DRAFT = "draft", "Drafted from sources"
        BREAKDOWN = "breakdown", "Broken down from the item above"
        SESSION = "session", "From a strategy session"
        PLAYBOOK = "playbook", "From a playbook"
        CLIENT = "client", "Proposed by the client"
        AI_APP = "ai_app", "From an AI app"
        CARRIED = "carried", "Carried over"

    company = models.ForeignKey("crm.Company", on_delete=models.CASCADE,
                                related_name="plan_items")
    horizon = models.CharField(max_length=8, choices=Horizon.choices)
    #: The first day of the item's period: the fiscal year or quarter, the
    #: month, or the week by the company's week start. The picture's is the
    #: fiscal year it was set in.
    period_start = models.DateField()
    title = models.CharField(max_length=300)
    done_means = models.TextField(blank=True, default="", db_default="")
    status = models.CharField(max_length=10, choices=Status.choices,
                              default=Status.ON_TRACK, db_default=Status.ON_TRACK)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="+")
    #: The item above it that it serves.
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL,
                               related_name="children")
    goal = models.ForeignKey("work.Goal", null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="plan_items")
    project = models.ForeignKey("work.Project", null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="plan_items")
    #: A month's or week's item for one team; unset is the whole company.
    client_team = models.ForeignKey("work.ClientTeam", null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="+")
    #: A picture's measurable target, read against its linked KPI.
    target_value = models.DecimalField(max_digits=16, decimal_places=4, null=True, blank=True)
    position = models.PositiveSmallIntegerField(default=0, db_default=0)
    state = models.CharField(max_length=10, choices=State.choices,
                             default=State.ACCEPTED, db_default=State.ACCEPTED)
    source = models.CharField(max_length=10, choices=Source.choices,
                              default=Source.HAND, db_default=Source.HAND)
    #: What a session row, a playbook run or a carried item came from.
    source_id = models.UUIDField(null=True, blank=True)
    #: The sources a draft drew on, named: ["Strategy session, October 2", ...].
    drew_on = models.JSONField(default=list, blank=True)
    ai_call = models.ForeignKey("tenancy.AiCall", null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="+")
    from_ai_app = models.BooleanField(default=False, db_default=False)
    proposed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="+")
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "plan_item"
        ordering = ["position", "created_at"]
        indexes = [models.Index(fields=["company", "horizon", "period_start"],
                                name="plan_item_by_period")]
        constraints = [
            models.CheckConstraint(condition=~Q(title=""), name="plan_item_has_a_title"),
        ]

    def __str__(self):
        return self.title


class PlanItemTask(TenantScopedModel):
    """A task an item links: a week's sprint is its tasks."""

    item = models.ForeignKey(PlanItem, on_delete=models.CASCADE, related_name="task_links")
    task = models.ForeignKey("crm.Task", on_delete=models.CASCADE, related_name="plan_links")
    position = models.PositiveSmallIntegerField(default=0, db_default=0)

    class Meta(TenantScopedModel.Meta):
        db_table = "plan_item_task"
        ordering = ["position", "created_at"]
        constraints = [
            models.UniqueConstraint(fields=["item", "task"], name="plan_item_task_once"),
        ]


class PlanItemKpi(TenantScopedModel):
    """A KPI an item links: the item shows its current status."""

    item = models.ForeignKey(PlanItem, on_delete=models.CASCADE, related_name="kpi_links")
    kpi = models.ForeignKey("scorecard.Kpi", on_delete=models.CASCADE, related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "plan_item_kpi"
        constraints = [
            models.UniqueConstraint(fields=["item", "kpi"], name="plan_item_kpi_once"),
        ]


class PlanClose(TenantScopedModel):
    """A week, month or quarter closed: what became of each of its items (or,
    for a week, each of its tasks), and the short summary the weekly digest
    draft carries."""

    company = models.ForeignKey("crm.Company", on_delete=models.CASCADE,
                                related_name="plan_closes")
    horizon = models.CharField(max_length=8, choices=Horizon.choices)
    period_start = models.DateField()
    #: [{"kind": "task"|"item", "id", "title", "outcome": "done"|"not_done"|"carried"}]
    outcomes = models.JSONField(default=list, blank=True)
    summary = models.TextField()
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                  on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "plan_close"
        ordering = ["-period_start"]
        constraints = [
            models.UniqueConstraint(fields=["company", "horizon", "period_start"],
                                    name="plan_close_once_per_period"),
        ]
