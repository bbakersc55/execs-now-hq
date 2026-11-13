"""The SOP studio (P10, docs/p10_sop_studio.md).

An **SOP** belongs to a client company or to the practice's own row. Its
fields are the working copy the practice edits. **Publishing** freezes the
working copy into a numbered **version** with a change note; the portal shows
only the latest published version, never the working copy. A version marked
*minor* keeps the read requests of the one before; any other asks the
audience again.

The **audience** is the whole company, chosen teams, or named people. Each
person in it ticks "Read and understood": an **acknowledgment** records who,
when and which version.

A **brainstorm** is a saved conversation with Claude about one process, with
its **sources** (pasted text, images Claude reads, PDFs' text, a media file's
transcript, a note, a tool run) and the **proposals** Claude made from it,
which a person accepts, edits or discards.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.tenancy.models import TenantScopedModel


class Sop(TenantScopedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"

    class Audience(models.TextChoices):
        COMPANY = "company", "The whole company"
        TEAMS = "teams", "Chosen teams"
        PEOPLE = "people", "Named people"

    company = models.ForeignKey("crm.Company", on_delete=models.CASCADE, related_name="sops")
    title = models.CharField(max_length=200)
    purpose = models.TextField(blank=True, default="", db_default="")
    applies_when = models.TextField(blank=True, default="", db_default="")
    #: [{"name": "Shipping lead", "does": "Owns the cut-off"}]
    roles = models.JSONField(default=list, blank=True)
    #: [{"text": "...", "role": "", "warning": "", "images": [attachment id]}]
    steps = models.JSONField(default=list, blank=True)
    #: The SOP template's other sections: [{"title": "...", "body": "..."}]
    sections = models.JSONField(default=list, blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="+")
    category = models.CharField(max_length=80, blank=True, default="", db_default="")
    review_date = models.DateField(null=True, blank=True)
    #: The flowchart, as text (`apps.sops.flow`).
    process_map = models.TextField(blank=True, default="", db_default="")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT,
                              db_default=Status.DRAFT)
    audience = models.CharField(max_length=8, choices=Audience.choices,
                                default=Audience.COMPANY, db_default=Audience.COMPANY)
    #: The latest published version's number (0: never published).
    version = models.PositiveSmallIntegerField(default=0, db_default=0)
    #: The number of the latest version that asked people to read it.
    ask_number = models.PositiveSmallIntegerField(default=0, db_default=0)
    published_at = models.DateTimeField(null=True, blank=True)
    #: Drafted by a person's AI app over MCP (`draft_sop`).
    from_ai_app = models.BooleanField(default=False, db_default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "sop"
        ordering = ["title"]
        indexes = [models.Index(fields=["company", "status"], name="sop_by_company")]
        constraints = [models.CheckConstraint(condition=~models.Q(title=""),
                                              name="sop_has_a_title")]

    def __str__(self):
        return self.title


class SopKpi(TenantScopedModel):
    """A company KPI the SOP should move."""

    sop = models.ForeignKey(Sop, on_delete=models.CASCADE, related_name="kpi_links")
    kpi = models.ForeignKey("scorecard.Kpi", on_delete=models.CASCADE, related_name="sop_links")

    class Meta(TenantScopedModel.Meta):
        db_table = "sop_kpi"
        constraints = [models.UniqueConstraint(fields=["sop", "kpi"], name="sop_kpi_once")]


class SopAudienceTeam(TenantScopedModel):
    sop = models.ForeignKey(Sop, on_delete=models.CASCADE, related_name="audience_teams")
    team = models.ForeignKey("work.ClientTeam", on_delete=models.CASCADE, related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "sop_audience_team"
        constraints = [models.UniqueConstraint(fields=["sop", "team"],
                                               name="sop_audience_team_once")]


class SopAudiencePerson(TenantScopedModel):
    sop = models.ForeignKey(Sop, on_delete=models.CASCADE, related_name="audience_people")
    membership = models.ForeignKey("tenancy.Membership", on_delete=models.CASCADE,
                                   related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "sop_audience_person"
        constraints = [models.UniqueConstraint(fields=["sop", "membership"],
                                               name="sop_audience_person_once")]


class SopVersion(TenantScopedModel):
    """A published version: the record as it was, frozen."""

    sop = models.ForeignKey(Sop, on_delete=models.CASCADE, related_name="versions")
    number = models.PositiveSmallIntegerField()
    change_note = models.TextField(blank=True, default="", db_default="")
    #: A minor change doesn't ask people to read it again.
    minor = models.BooleanField(default=False, db_default=False)
    snapshot = models.JSONField(default=dict)
    #: After this day an acknowledgment counts as late.
    read_by = models.DateField(null=True, blank=True)
    published_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name="+")
    published_at = models.DateTimeField()

    class Meta(TenantScopedModel.Meta):
        db_table = "sop_version"
        ordering = ["-number"]
        constraints = [models.UniqueConstraint(fields=["sop", "number"],
                                               name="sop_version_once")]


class SopAck(TenantScopedModel):
    """"Read and understood": who, when, and which version."""

    sop = models.ForeignKey(Sop, on_delete=models.CASCADE, related_name="acks")
    version = models.ForeignKey(SopVersion, on_delete=models.CASCADE, related_name="acks")
    membership = models.ForeignKey("tenancy.Membership", on_delete=models.CASCADE,
                                   related_name="+")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="+")
    acknowledged_at = models.DateTimeField()
    late = models.BooleanField(default=False, db_default=False)

    class Meta(TenantScopedModel.Meta):
        db_table = "sop_ack"
        constraints = [models.UniqueConstraint(fields=["version", "membership"],
                                               name="sop_ack_once_per_version")]


class SopAttachment(TenantScopedModel):
    """An image or a PDF on an SOP. A step names images by id."""

    class Kind(models.TextChoices):
        IMAGE = "image", "Image"
        PDF = "pdf", "PDF"

    sop = models.ForeignKey(Sop, on_delete=models.CASCADE, related_name="attachments")
    file = models.ForeignKey("tenancy.StoredFile", on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=8, choices=Kind.choices)
    name = models.CharField(max_length=200)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "sop_attachment"
        ordering = ["created_at"]


class SopComment(TenantScopedModel):
    """"Suggest a change", from someone in the audience, for the practice."""

    sop = models.ForeignKey(Sop, on_delete=models.CASCADE, related_name="comments")
    version_number = models.PositiveSmallIntegerField(default=0, db_default=0)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                               related_name="+")
    text = models.TextField()
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "sop_comment"
        ordering = ["-created_at"]


class Brainstorm(TenantScopedModel):
    """A saved conversation with Claude about one process."""

    class Tier(models.TextChoices):
        STANDARD = "standard", "Standard"
        DEEP = "deep", "Deep"

    company = models.ForeignKey("crm.Company", on_delete=models.CASCADE,
                                related_name="sop_brainstorms")
    #: The SOP it drafts into, once there is one.
    sop = models.ForeignKey(Sop, null=True, blank=True, on_delete=models.SET_NULL,
                            related_name="brainstorms")
    title = models.CharField(max_length=200)
    tier = models.CharField(max_length=10, choices=Tier.choices, default=Tier.STANDARD,
                            db_default=Tier.STANDARD)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "sop_brainstorm"
        ordering = ["-updated_at"]


class BrainstormSource(TenantScopedModel):
    class Kind(models.TextChoices):
        PASTED = "pasted", "Pasted text"
        IMAGE = "image", "An image"
        PDF = "pdf", "A PDF"
        MEDIA = "media", "Video or audio"
        NOTE = "note", "A note"
        TOOL_RUN = "tool_run", "A tool run"
        SOP = "sop", "An SOP"

    class State(models.TextChoices):
        READY = "ready", "Ready"
        READING = "reading", "Being read"
        FAILED = "failed", "Couldn't be read"

    brainstorm = models.ForeignKey(Brainstorm, on_delete=models.CASCADE, related_name="sources")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    title = models.CharField(max_length=200)
    #: What Claude reads: the text, a PDF's extracted text, a transcript and
    #: its steps. Empty for an image, which is sent as itself.
    text = models.TextField(blank=True, default="", db_default="")
    file = models.ForeignKey("tenancy.StoredFile", null=True, blank=True,
                             on_delete=models.SET_NULL, related_name="+")
    content_type = models.CharField(max_length=100, blank=True, default="", db_default="")
    state = models.CharField(max_length=8, choices=State.choices, default=State.READY,
                             db_default=State.READY)
    error = models.TextField(blank=True, default="", db_default="")
    #: A media file: its length, whether to keep it, and the reader's handle.
    seconds = models.PositiveIntegerField(null=True, blank=True)
    keep_file = models.BooleanField(default=False, db_default=False)
    external_ref = models.CharField(max_length=200, blank=True, default="", db_default="")
    #: The record it came from (a note, a run, an SOP).
    source_id = models.UUIDField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "sop_brainstorm_source"
        ordering = ["created_at"]


class BrainstormMessage(TenantScopedModel):
    class Role(models.TextChoices):
        USER = "user", "A person"
        CLAUDE = "claude", "Claude"

    brainstorm = models.ForeignKey(Brainstorm, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=8, choices=Role.choices)
    text = models.TextField()
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                               on_delete=models.SET_NULL, related_name="+")
    ai_call = models.ForeignKey("tenancy.AiCall", null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "sop_brainstorm_message"
        ordering = ["created_at"]


class BrainstormProposal(TenantScopedModel):
    """What Claude proposed from a brainstorm, waiting for a person."""

    class Kind(models.TextChoices):
        DRAFT = "draft", "The SOP"
        MAP = "map", "The process map"
        CHECKLIST = "checklist", "A checklist"
        MEASURES = "measures", "Measures"

    class State(models.TextChoices):
        PROPOSED = "proposed", "Waiting"
        ACCEPTED = "accepted", "Accepted"
        DISCARDED = "discarded", "Discarded"

    brainstorm = models.ForeignKey(Brainstorm, on_delete=models.CASCADE,
                                   related_name="proposals")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    payload = models.JSONField(default=dict)
    #: Claude's one-line reason, shown with the proposal.
    why = models.TextField(blank=True, default="", db_default="")
    state = models.CharField(max_length=10, choices=State.choices, default=State.PROPOSED,
                             db_default=State.PROPOSED)
    #: What accepting it made: {"sop": id} or {"tasks": [ids]} or {"kpis": [ids]}.
    result = models.JSONField(default=dict, blank=True)
    ai_call = models.ForeignKey("tenancy.AiCall", null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="+")
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "sop_brainstorm_proposal"
        ordering = ["-created_at"]


class PackPrompts(TenantScopedModel):
    """The practice's own copy of the Notebook pack's prompt sets, once edited.
    Until then the Operations Command Center's own (`content.operations`)."""

    prompts = models.JSONField(default=list)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "sop_pack_prompts"
        constraints = [models.UniqueConstraint(fields=["tenant"], name="sop_pack_prompts_one")]
