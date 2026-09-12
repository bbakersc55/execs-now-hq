"""Module 3 — the task engine: Goal → Project → Task, and what digests are made of.

`task` itself lives in `apps.crm`, where Phase 1 created it for stage rules
(FR-1.11) and where stage automations still write it. Everything Module 3 adds
lives here; Phase 3 extends `crm.Task` in place.

Three rules are structural rather than remembered:

1. **Three levels, full stop.** A task has no self-FK (FR-3.4), so depth cannot
   grow. Sub-steps are `TaskChecklistItem` rows.
2. **A derived status is never stored** (FR-3.10). Goals and Projects hold only
   `status_override`; the rollup is computed at read time, because a stored one
   drifts the moment a child changes outside the code path that wrote it.
3. **Digest delivery is per recipient.** `task_update` carries no digest
   pointer: one update goes to every stakeholder on the entity, so "has this
   been sent?" is a question about a (recipient, update) pair and lives in
   `digest_item`.
"""

from __future__ import annotations

import hashlib
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.crm.models import Task
from apps.tenancy.models import TenantScopedModel

CADENCE_TOKEN_TTL = timezone.timedelta(days=30)  # FR-3.33b


def _exactly_one_target(*names):
    """Exactly one of the given FKs is set — the check every polymorphic
    attachment in this module carries."""
    total = None
    for name in names:
        term = models.Q(**{f"{name}__isnull": False})
        total = term if total is None else total | term
    pairs = None
    for i, first in enumerate(names):
        for second in names[i + 1:]:
            both = models.Q(**{f"{first}__isnull": False, f"{second}__isnull": False})
            pairs = both if pairs is None else pairs | both
    return total & ~pairs


class Cadence(models.TextChoices):
    EVERY_UPDATE = "every_update", "On every update"
    WEEKLY = "weekly", "Weekly"
    MONTHLY = "monthly", "Monthly"


class Priority(models.IntegerChoices):
    """FR-3.3 names the field; the scale is this build's choice. `NORMAL` is the
    default so an unset priority means "ordinary", not "lowest"."""

    LOW = 0, "Low"
    NORMAL = 1, "Normal"
    HIGH = 2, "High"
    URGENT = 3, "Urgent"


class WorkItem(TenantScopedModel):
    """What a Goal and a Project have in common (FR-3.1, FR-3.2)."""

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    client_company = models.ForeignKey(
        "crm.Company", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )
    # The accountable TENANT user. Nullable so a departed member's goals stay
    # on the record (FR-0.8c: nothing they authored is removed).
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    # Who on the CLIENT side is accountable — a Contact, not a user, because
    # both upstream sources (a strategy map row's owner, a meeting action
    # item's owner) name people who often have no login.
    client_owner_contact = models.ForeignKey(
        "crm.Contact", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )
    target_date = models.DateField(null=True, blank=True)
    # FR-3.10 — null means "derive from children at read time".
    status_override = models.CharField(
        max_length=20, choices=Task.Status.choices, null=True, blank=True
    )
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        abstract = True


class Goal(WorkItem):
    """FR-3.1. Client-facing strategy; never authored by a client (FR-3.35a)."""

    class Meta(WorkItem.Meta):
        db_table = "goal"
        indexes = [models.Index(fields=["tenant", "client_company"])]


class Project(WorkItem):
    """FR-3.2. A client-created project has `created_by_client`, no parent goal,
    and its creator's own company (FR-3.35a)."""

    goal = models.ForeignKey(
        Goal, null=True, blank=True, on_delete=models.SET_NULL, related_name="projects"
    )
    start_date = models.DateField(null=True, blank=True)
    created_by_client = models.BooleanField(default=False)

    class Meta(WorkItem.Meta):
        db_table = "project"
        indexes = [models.Index(fields=["tenant", "client_company"])]
        constraints = [
            # FR-3.35a — strategy stays the fractional's.
            models.CheckConstraint(
                condition=models.Q(created_by_client=False) | models.Q(goal__isnull=True),
                name="project_client_created_has_no_goal",
            ),
        ]


class TaskChecklistItem(TenantScopedModel):
    """FR-3.4 — the flat substitute for subtasks, which is what keeps the
    three-level cap from becoming unlimited depth."""

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="checklist")
    text = models.CharField(max_length=500)
    is_done = models.BooleanField(default=False)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta(TenantScopedModel.Meta):
        db_table = "task_checklist_item"
        ordering = ["position", "created_at"]


class Comment(TenantScopedModel):
    """FR-3.12 — on a task, a project or a goal; exactly one.

    `visibility` defaults to INTERNAL (FR-3.12a): a comment meant for the
    client that stayed internal gets noticed and reposted, while an internal
    remark that reached the client cannot be recalled.
    """

    class Visibility(models.TextChoices):
        INTERNAL = "internal", "Internal only"
        SHARED = "shared", "Shared with the client"

    task = models.ForeignKey(Task, null=True, blank=True, on_delete=models.CASCADE,
                             related_name="comments")
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.CASCADE,
                               related_name="comments")
    goal = models.ForeignKey(Goal, null=True, blank=True, on_delete=models.CASCADE,
                             related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                               on_delete=models.SET_NULL, related_name="+")
    body = models.TextField()
    visibility = models.CharField(max_length=8, choices=Visibility.choices,
                                  default=Visibility.INTERNAL)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "comment"
        constraints = [
            models.CheckConstraint(
                condition=_exactly_one_target("task", "project", "goal"),
                name="comment_exactly_one_target",
            ),
        ]


class TaskUpdate(TenantScopedModel):
    """FR-3.15 — the digest's source material, and the most consequential table
    in the product. Digests are assembled from these rows, never from diffing
    current state.
    """

    class Kind(models.TextChoices):
        CREATED = "created", "Created"
        STATUS_CHANGED = "status_changed", "Status changed"
        ASSIGNEE_CHANGED = "assignee_changed", "Assignee changed"
        DUE_CHANGED = "due_changed", "Due date changed"
        COMMENT_ADDED = "comment_added", "Comment added"
        CHECKLIST_COMPLETED = "checklist_completed", "Checklist item completed"
        COMPLETED = "completed", "Completed"
        NARRATIVE = "narrative", "Narrative added"

    class Source(models.TextChoices):
        USER = "user", "A person"
        STAGE_AUTOMATION = "stage_automation", "Stage automation"
        MEETING_APPROVAL = "meeting_approval", "Meeting review approval"
        STRATEGY_CONVERSION = "strategy_conversion", "Strategy map conversion"
        SYSTEM = "system", "System"

    task = models.ForeignKey(Task, null=True, blank=True, on_delete=models.CASCADE,
                             related_name="updates")
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.CASCADE,
                                related_name="updates")
    goal = models.ForeignKey(Goal, null=True, blank=True, on_delete=models.CASCADE,
                             related_name="updates")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    from_value = models.TextField(blank=True, default="")
    to_value = models.TextField(blank=True, default="")
    # FR-3.16/3.17 — the prompted "what this means for you". A first-class
    # field, not a comment: every digest downstream is only as good as this.
    client_facing_line = models.TextField(blank=True, default="")
    # Nullable: a stage automation or an ingestion job has no user actor.
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="+")
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.USER)
    source_id = models.UUIDField(null=True, blank=True)
    # A client's own update is visible but never triggers a digest to its author.
    is_client_actor = models.BooleanField(default=False)

    class Meta(TenantScopedModel.Meta):
        db_table = "task_update"
        indexes = [
            models.Index(fields=["tenant", "created_at"]),
            models.Index(fields=["tenant", "task", "created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=_exactly_one_target("task", "project", "goal"),
                name="task_update_exactly_one_target",
            ),
        ]


class Stakeholder(TenantScopedModel):
    """F18 / FR-3.20 — a Contact, not a User.

    Digests go to the Contact's primary email whether or not that person has
    ever signed in. Attached at goal, project or task level; effective
    stakeholders for a task are the union of all three, de-duplicated per
    person, most specific attachment deciding cadence (FR-3.20a) — computed,
    never stored.
    """

    contact = models.ForeignKey("crm.Contact", on_delete=models.CASCADE,
                                related_name="stakeholder_rows")
    goal = models.ForeignKey(Goal, null=True, blank=True, on_delete=models.CASCADE,
                             related_name="stakeholders")
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.CASCADE,
                                related_name="stakeholders")
    task = models.ForeignKey(Task, null=True, blank=True, on_delete=models.CASCADE,
                             related_name="stakeholders")
    cadence = models.CharField(max_length=12, choices=Cadence.choices,
                               default=Cadence.WEEKLY)
    is_muted = models.BooleanField(default=False)
    last_notified_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "stakeholder"
        constraints = [
            models.CheckConstraint(
                condition=_exactly_one_target("goal", "project", "task"),
                name="stakeholder_exactly_one_level",
            ),
            models.UniqueConstraint(fields=["tenant", "contact", "goal"],
                                    name="stakeholder_unique_per_goal"),
            models.UniqueConstraint(fields=["tenant", "contact", "project"],
                                    name="stakeholder_unique_per_project"),
            models.UniqueConstraint(fields=["tenant", "contact", "task"],
                                    name="stakeholder_unique_per_task"),
        ]


class StakeholderToken(TenantScopedModel):
    """FR-3.33a — the cadence link in a digest footer.

    Separate from a magic link by design: 30 days rather than 20 minutes, and
    one capability — read and change the cadence on this one stakeholder row.
    It cannot read a task, a digest, or anything else. Stored as a hash, so a
    database read yields no working credential.
    """

    stakeholder = models.ForeignKey(Stakeholder, on_delete=models.CASCADE,
                                    related_name="tokens")
    token_hash = models.CharField(max_length=64, db_index=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "stakeholder_token"

    @staticmethod
    def hash_token(raw: str) -> str:
        return hashlib.sha256(raw.encode()).hexdigest()

    @classmethod
    def issue(cls, stakeholder):
        raw = secrets.token_urlsafe(32)
        token = cls.all_objects.create(
            tenant_id=stakeholder.tenant_id, stakeholder=stakeholder,
            token_hash=cls.hash_token(raw),
            expires_at=timezone.now() + CADENCE_TOKEN_TTL,
        )
        return token, raw

    @classmethod
    def resolve(cls, raw: str):
        return (
            cls.all_objects.select_related("stakeholder", "tenant")
            .filter(token_hash=cls.hash_token(raw or ""), revoked_at__isnull=True,
                    expires_at__gt=timezone.now())
            .first()
        )


class Digest(TenantScopedModel):
    """FR-3.19–3.32. Keyed by RECIPIENT, not by stakeholder attachment: the same
    Contact can hold rows at goal and task level, and keying per attachment
    would put two emails in one inbox on the same Friday.

    `cadence` is in the key because most-specific-wins can legitimately put one
    person on two cadences at once — weekly across a goal, `every_update` on one
    urgent task inside it. Those are two real emails, not a duplicate.
    """

    class State(models.TextChoices):
        PENDING = "pending", "Pending approval"
        APPROVED = "approved", "Approved"
        SENT = "sent", "Sent"
        EXPIRED = "expired", "Expired unsent"
        SKIPPED = "skipped", "Skipped"

    contact = models.ForeignKey("crm.Contact", on_delete=models.CASCADE,
                                related_name="digests")
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    cadence = models.CharField(max_length=12, choices=Cadence.choices)
    state = models.CharField(max_length=10, choices=State.choices,
                             default=State.PENDING, db_index=True)
    # Derived at generation from company.digest_ai_prose (FR-3.24). It decides
    # whether approval is required when hold_all_digests is off (FR-3.27).
    is_ai_generated = models.BooleanField(default=False)
    is_stale = models.BooleanField(default=False)          # FR-3.30a
    stale_reason = models.TextField(blank=True, default="")
    body_text = models.TextField(blank=True, default="")
    body_html = models.TextField(blank=True, default="")
    generated_at = models.DateTimeField(default=timezone.now)
    send_window_at = models.DateTimeField()
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    outbox_message = models.ForeignKey("crm.OutboxMessage", null=True, blank=True,
                                       on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "digest"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "contact", "cadence", "period_start"],
                name="digest_unique_per_recipient_period",
            ),
        ]
        indexes = [models.Index(fields=["tenant", "state", "send_window_at"])]


class DigestItem(TenantScopedModel):
    """The join written at generation — what makes multi-stakeholder delivery
    correct (FR-3.30).

    An update is still owed to a contact when no item joins it to a `sent`
    digest for that contact. Expiry DELETES these rows, so the claim is
    released and the updates are owed again next period; an approved digest's
    items are never touched again (FR-3.30b).
    """

    digest = models.ForeignKey(Digest, on_delete=models.CASCADE, related_name="items")
    task_update = models.ForeignKey(TaskUpdate, on_delete=models.CASCADE,
                                    related_name="digest_items", db_index=True)
    # Which attachment this update reached the recipient through. Nullable: the
    # stakeholder row may be removed later, and the item still happened.
    stakeholder = models.ForeignKey(Stakeholder, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "digest_item"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "digest", "task_update"],
                                    name="digest_item_unique_per_digest"),
        ]
