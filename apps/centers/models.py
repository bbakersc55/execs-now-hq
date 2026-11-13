"""Command Centers (P8, docs/p8_command_centers.md).

The **catalog** is the platform's: eight modules, each a discipline, $50 a
month. A practice's **switch** is a row per module it has turned on. What a
module ships lives in code (`apps/centers/content/`) and is copied into the
practice on first use: a playbook becomes a `Playbook` row the practice edits;
a session template, a document template, an email template or a KPI become
the practice's own through their own apps. Edits never reach the catalog or
another practice.

The **practice library** (`LibraryRecord`) quietly keeps, per practice, the
structured records a later learning tool will draw on. Nothing reads it yet
but a count and the owner's export.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.tenancy.models import TenantScopedModel, UUIDModel


class CommandCenter(UUIDModel):
    """The platform's catalog: one row per module, seeded by migration."""

    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"
        COMING = "coming", "Coming"

    code = models.CharField(max_length=24, unique=True)
    #: "Operations Command Center": on the module card, Settings and the site.
    name = models.CharField(max_length=80)
    #: "Operations": the only name the app's navigation shows.
    short_name = models.CharField(max_length=40)
    discipline = models.CharField(max_length=40)
    price_cents = models.PositiveIntegerField(default=5000)
    description = models.TextField(blank=True, default="")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.COMING)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "command_center"
        ordering = ["position"]


class PracticeCenter(TenantScopedModel):
    """A module a practice has turned on (Settings → Command Centers). Kept
    when turned off, so turning it on again finds its copies where they were."""

    center = models.CharField(max_length=24)
    enabled_at = models.DateTimeField(null=True, blank=True)
    enabled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    disabled_at = models.DateTimeField(null=True, blank=True)
    disabled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "practice_command_center"
        constraints = [models.UniqueConstraint(fields=["tenant", "center"],
                                               name="practice_command_center_one_each")]


class Playbook(TenantScopedModel):
    """A goal, its projects and their tasks, as an outline with weeks and
    role owners (`apps.centers.playbooks` reads it). A module's playbook is
    copied here the first time the practice opens or starts it; the practice
    edits its copy."""

    name = models.CharField(max_length=160)
    description = models.TextField(blank=True, default="")
    #: The module it came from ("operations"), or empty for the practice's own.
    center = models.CharField(max_length=24, blank=True, default="")
    #: The shipped playbook it is a copy of, or empty.
    source_key = models.CharField(max_length=60, blank=True, default="")
    #: Shipped playbooks arrive as drafts: "draft, edit before first use".
    is_draft = models.BooleanField(default=False)
    outline = models.TextField()
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "playbook"
        constraints = [models.UniqueConstraint(
            fields=["tenant", "source_key"], condition=~models.Q(source_key=""),
            name="playbook_one_copy_each")]


class PlaybookRun(TenantScopedModel):
    """A playbook started on a company: the goal it made, and when."""

    playbook = models.ForeignKey(Playbook, on_delete=models.PROTECT, related_name="runs")
    company = models.ForeignKey("crm.Company", on_delete=models.CASCADE, related_name="+")
    start_date = models.DateField()
    goal = models.ForeignKey("work.Goal", null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="+")
    started_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    #: {"projects": n, "tasks": n}: what the start made.
    made = models.JSONField(default=dict, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "playbook_run"


class LibraryRecord(TenantScopedModel):
    """The practice library (P8): one record of the practice's own work, with
    its structure pulled out, for the learning tool to come. Recorded only
    while the practice has a Command Center on; never a PIN-locked note.
    Visible nowhere but a count; the practice owner exports or deletes it."""

    class Kind(models.TextChoices):
        NOTE = "note", "A note"
        MAP_ROW_ACCEPTED = "map_row_accepted", "An accepted map row"
        MAP_ROW_REJECTED = "map_row_rejected", "A discarded map row"
        SOP = "sop", "A finished SOP"
        DOCUMENT = "document", "A finished document"
        PLAYBOOK_RUN = "playbook_run", "A playbook run"
        #: P11: a plan item proposed (by Claude, an AI app or a client) and
        #: then accepted or discarded.
        PLAN_ITEM_ACCEPTED = "plan_item_accepted", "An accepted plan item"
        PLAN_ITEM_REJECTED = "plan_item_rejected", "A discarded plan item"

    kind = models.CharField(max_length=20, choices=Kind.choices)
    source_type = models.CharField(max_length=40)
    source_id = models.UUIDField()
    title = models.CharField(max_length=255, blank=True, default="")
    structure = models.JSONField(default=dict, blank=True)
    recorded_at = models.DateTimeField()

    class Meta(TenantScopedModel.Meta):
        db_table = "practice_library_record"
        constraints = [models.UniqueConstraint(fields=["tenant", "source_type", "source_id"],
                                               name="practice_library_one_per_source")]
