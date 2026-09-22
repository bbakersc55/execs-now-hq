"""Module 5 — meeting ingestion (PRD §7, data model §7).

**The whole module is a review queue with a parser in front of it.** Nothing
here creates a record or sends anything on its own; every row below is either
something we read, something Claude proposed, or the trail of a person deciding.

Two shapes carry most of the design:

1. **`MeetingSourceFile` is unique on `(tenant, drive_file_id, drive_version)`**,
   which is the idempotency guarantee (FR-5.4). Re-polling the same folder
   forever yields one record per version of a file and no second proposal.
2. **`ProposalItem` is one table for all three kinds** — participant, action
   item, deliverable — because they share a lifecycle and a review screen
   (pending → approved/rejected, independently, FR-5.15).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.tenancy.models import TenantScopedModel


class DriveWatch(TenantScopedModel):
    """The folder, and where we had got to in it (FR-5.1).

    **Cursor-based, not event-based** (assumption A6): the app runs on a laptop
    that is closed at night, so ingestion has to be something that catches up
    rather than something that must be listening at the moment a file lands.
    """

    folder_id = models.CharField(max_length=128)
    folder_name = models.CharField(max_length=255, blank=True, default="")
    #: Drive's `changes.list` cursor. **Advanced only after every file in a
    #: page is durably recorded** (FR-5.2, FR-5.5).
    page_token = models.TextField(blank=True, default="")
    last_polled_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "drive_watch"
        constraints = [
            # FR-5 out-of-scope 6: one folder per tenant in Beta.
            models.UniqueConstraint(fields=["tenant"], name="one_drive_watch_per_tenant"),
        ]


class DriveBackfill(TenantScopedModel):
    """Reading what was already in the folder — a choice, never a default.

    **The poll cannot see the past.** Drive's `changes.list` starts from a
    token that means "now", so a folder of six months of notes is, to a fresh
    watch, empty until the next meeting. Importing that history is a real
    decision: it costs one Claude call per note and fills the review queue with
    months of work. So the app states what is there, what it would cost, and
    lets the fractional choose — `NOW` is a recorded decision not to, which is
    why it is a row rather than an absence.

    Paced rather than queued all at once: `after_created_time` walks the folder
    oldest first, a few notes a minute, so the cluster keeps serving the app and
    **the spend is visible while it happens** rather than after it.
    """

    class Scope(models.TextChoices):
        NOW = "now", "Only new notes from now on"
        SINCE = "since", "Also notes since a date"
        ALL = "all", "Everything in the folder"

    class State(models.TextChoices):
        DECLINED = "declined", "Starting from now"
        RUNNING = "running", "Importing"
        DONE = "done", "Imported"
        CANCELLED = "cancelled", "Stopped"
        FAILED = "failed", "Stopped by an error"

    watch = models.ForeignKey("meetings.DriveWatch", on_delete=models.CASCADE,
                              related_name="backfills")
    scope = models.CharField(max_length=8, choices=Scope.choices)
    since = models.DateField(null=True, blank=True)
    state = models.CharField(max_length=10, choices=State.choices,
                             default=State.RUNNING, db_index=True)
    #: What the survey counted when the choice was made, and what it thought it
    #: would cost. Both are kept beside the real figures so an estimate that was
    #: badly wrong is visible afterwards rather than quietly replaced.
    planned = models.IntegerField(default=0)
    estimated_cost_usd = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    done = models.IntegerField(default=0)
    skipped = models.IntegerField(default=0)
    failed = models.IntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    #: RFC 3339, the `createdTime` of the last file this has walked past. The
    #: cursor is a timestamp rather than a page token because the walk is
    #: oldest-first over a fixed set, and a timestamp survives a restart.
    after_created_time = models.CharField(max_length=40, blank=True, default="")
    last_error = models.TextField(blank=True, default="")
    started_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "drive_backfill"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["tenant", "state"])]

    @property
    def is_running(self) -> bool:
        return self.state == self.State.RUNNING

    @property
    def remaining(self) -> int:
        return max(self.planned - self.done - self.skipped - self.failed, 0)


class MeetingSourceFile(TenantScopedModel):
    """One version of one file we have seen (FR-5.4)."""

    class State(models.TextChoices):
        RECORDED = "recorded", "Recorded"
        PARSING = "parsing", "Parsing"
        PARSED = "parsed", "Parsed"
        SKIPPED = "skipped", "Skipped"
        FAILED = "failed", "Parse failed"

    drive_file_id = models.CharField(max_length=128, db_index=True)
    drive_version = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=120)
    #: **Load-bearing for permissions, not metadata.** It is the second limb of
    #: the CF `proposal-scope` rule: a CF sees a proposal from their *own*
    #: meeting even before any participant is matched to a company.
    #: The data model says `citext`. This project has no citext extension and
    #: `contact_email.address` — the column the same kind of matching already
    #: runs against — is a plain indexed `EmailField`, so this follows it:
    #: stored lower-cased on write, compared case-insensitively. One pattern
    #: for email in this codebase beats two.
    drive_file_owner_email = models.EmailField(blank=True, default="", db_index=True)

    def save(self, *args, **kwargs):
        self.drive_file_owner_email = (self.drive_file_owner_email or "").strip().lower()
        super().save(*args, **kwargs)
    state = models.CharField(max_length=10, choices=State.choices,
                             default=State.RECORDED, db_index=True)
    skip_reason = models.TextField(blank=True, default="")
    error = models.TextField(blank=True, default="")
    fetched_at = models.DateTimeField(null=True, blank=True)
    #: Kept so a re-parse needs no second trip to Drive, and so the review
    #: screen can show the passage an item was drawn from (FR-5.14).
    text = models.TextField(blank=True, default="")
    web_view_link = models.URLField(blank=True, default="")

    class Meta(TenantScopedModel.Meta):
        db_table = "meeting_source_file"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "drive_file_id", "drive_version"],
                name="one_record_per_file_version"),
        ]

    @property
    def is_pending(self) -> bool:
        return self.state in (self.State.RECORDED, self.State.PARSING,
                              self.State.FAILED)


class MeetingProposal(TenantScopedModel):
    """What Claude made of one file, waiting for a person (FR-5.8)."""

    class State(models.TextChoices):
        PENDING = "pending", "Pending"
        PARTIALLY_ACTIONED = "partially_actioned", "Partly actioned"
        ACTIONED = "actioned", "Actioned"
        REJECTED = "rejected", "Rejected"
        SUPERSEDED = "superseded", "Superseded by a re-parse"

    source_file = models.ForeignKey(MeetingSourceFile, on_delete=models.CASCADE,
                                    related_name="proposals")
    meeting_date = models.DateField(null=True, blank=True)
    title = models.CharField(max_length=255, blank=True, default="")
    #: R11a — drafted by Claude, reviewed with the proposal, editable and
    #: discardable. A discarded summary means a Meeting with none, not no
    #: Meeting (FR-5.8b).
    proposed_summary = models.TextField(blank=True, default="")
    summary = models.TextField(blank=True, default="")
    summary_discarded = models.BooleanField(default=False)
    state = models.CharField(max_length=20, choices=State.choices,
                             default=State.PENDING, db_index=True)
    ai_call = models.ForeignKey("tenancy.AiCall", null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="+")
    meeting = models.ForeignKey("meetings.Meeting", null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "meeting_proposal"
        ordering = ["-created_at"]


class ProposalItem(TenantScopedModel):
    """One proposed thing, independently approvable (FR-5.15).

    `payload` is shaped by `kind` — the three shapes are in `02_data_model.md`
    §7 and are built by `apps.meetings.parsing`. They are JSON rather than three
    tables because they share a lifecycle and a screen, and because what Claude
    proposes is not yet a record: it becomes one, in the shape the receiving
    module already uses, only when somebody approves it.
    """

    class Kind(models.TextChoices):
        PARTICIPANT = "participant", "Participant"
        ACTION_ITEM = "action_item", "Action item"
        DELIVERABLE = "deliverable", "Deliverable"

    class State(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    proposal = models.ForeignKey(MeetingProposal, on_delete=models.CASCADE,
                                 related_name="items")
    kind = models.CharField(max_length=12, choices=Kind.choices, db_index=True)
    state = models.CharField(max_length=8, choices=State.choices,
                             default=State.PENDING, db_index=True)
    #: FR-5.14 — the passage it was drawn from, so a reviewer can check the
    #: claim rather than trust it.
    source_excerpt = models.TextField(blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    position = models.PositiveSmallIntegerField(default=0)
    created_record_type = models.CharField(max_length=32, blank=True, default="")
    created_record_id = models.UUIDField(null=True, blank=True)
    actioned_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="+")
    actioned_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "proposal_item"
        ordering = ["kind", "position", "created_at"]
        indexes = [models.Index(fields=["tenant", "proposal", "state"])]


class Meeting(TenantScopedModel):
    """The meeting itself, created on approval (FR-5.8a).

    **The meeting is the point, not only the tasks it produced.** Opening a
    contact six months later shows the meetings they were in, not merely
    whatever survived them.
    """

    source_file = models.ForeignKey(MeetingSourceFile, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="meetings")
    proposal = models.ForeignKey(MeetingProposal, null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="+")
    meeting_date = models.DateField(null=True, blank=True)
    title = models.CharField(max_length=255, blank=True, default="")
    summary = models.TextField(blank=True, default="")
    client_company = models.ForeignKey("crm.Company", null=True, blank=True,
                                       on_delete=models.SET_NULL, related_name="+")
    #: A link back to the document it came from, so the record is checkable.
    web_view_link = models.URLField(blank=True, default="")

    class Meta(TenantScopedModel.Meta):
        db_table = "meeting"
        ordering = ["-meeting_date", "-created_at"]
        indexes = [models.Index(fields=["tenant", "-meeting_date"])]


class MeetingParticipant(TenantScopedModel):
    """The join that puts the meeting on every approved participant's
    timeline (FR-5.8a)."""

    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE,
                                related_name="participants")
    contact = models.ForeignKey("crm.Contact", on_delete=models.CASCADE,
                                related_name="meetings")

    class Meta(TenantScopedModel.Meta):
        db_table = "meeting_participant"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "meeting", "contact"],
                                    name="one_participant_row_per_meeting"),
        ]
