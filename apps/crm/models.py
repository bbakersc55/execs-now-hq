"""Module 1 — Contacts & pipeline (data model §2).

Build order follows `02_data_model.md` §11: company already exists from
Phase 0.5; contact arrives here, then company.primary_contact last.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models

from apps.tenancy.models import TenantScopedModel


# ---------------------------------------------------------------- companies

class Company(TenantScopedModel):
    name = models.CharField(max_length=200, db_index=True)
    industry = models.CharField(max_length=120, blank=True, default="")
    address = models.JSONField(null=True, blank=True)

    # FR-1.3a — designated recipient of company-level communication, and the
    # default FCC when portal access is first granted (FR-3.33d).
    primary_contact = models.ForeignKey(
        "crm.Contact", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="primary_for",
    )

    # FR-1.6a — derived from a contact reaching stage `client`; cleared only by
    # hand. The derivation runs one way and is never inferred backwards.
    is_client_company = models.BooleanField(default=False)

    # FR-3.33f — the limit. Usage is counted from live memberships, never
    # stored, so it cannot drift (§12.3).
    seat_count = models.PositiveIntegerField(null=True, blank=True)
    digest_ai_prose = models.BooleanField(default=True)  # FR-3.24
    deleted_at = models.DateTimeField(null=True, blank=True)  # D2

    class Meta(TenantScopedModel.Meta):
        db_table = "company"
        verbose_name_plural = "companies"

    def __str__(self):
        return self.name

    @property
    def seats_in_use(self):
        """Counted, never stored (§12.3). Scoped by this row's own tenant
        rather than through the fail-closed reverse manager, so the property
        works in management commands and jobs with no ambient context."""
        from apps.tenancy.models import Membership

        return Membership.all_objects.filter(
            tenant_id=self.tenant_id, client_company_id=self.pk,
            revoked_at__isnull=True,
        ).count()

    @property
    def seats_available(self):
        if self.seat_count is None:
            return 0
        return max(self.seat_count - self.seats_in_use, 0)


class CompanyDomain(TenantScopedModel):
    """Separate table: domain matching drives participant matching (FR-5.10)."""

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="domains")
    domain = models.CharField(max_length=253, db_index=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "company_domain"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "domain"], name="company_domain_unique")
        ]


class CompanyLocation(TenantScopedModel):
    """Ordered. Feeds {Location A} / {Location B} (FR-1.3, FR-4.9a)."""

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="locations")
    name = models.CharField(max_length=200)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta(TenantScopedModel.Meta):
        db_table = "company_location"
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "company", "position"], name="company_location_position_unique"
            )
        ]


# ------------------------------------------------------- types and pipeline

class ContactType(TenantScopedModel):
    """Per-tenant rows (D5) — V1 lets tenants customise these."""

    code = models.CharField(max_length=32)
    label = models.CharField(max_length=64)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta(TenantScopedModel.Meta):
        db_table = "contact_type"
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="contact_type_code_unique")
        ]

    def __str__(self):
        return self.label


class PipelineStage(TenantScopedModel):
    """FR-1.6. Seeded contact -> lead -> qualified_lead -> client, plus the two
    non-linear states without which every lost prospect stays in the pipeline
    forever (FR-1.6, assumption F2)."""

    code = models.CharField(max_length=32)
    label = models.CharField(max_length=64)
    position = models.PositiveSmallIntegerField(default=0)
    is_terminal = models.BooleanField(default=False)

    class Meta(TenantScopedModel.Meta):
        db_table = "pipeline_stage"
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="pipeline_stage_code_unique")
        ]

    def __str__(self):
        return self.label


class ServiceCategory(TenantScopedModel):
    """Vendor search (FR-1.24-25)."""

    name = models.CharField(max_length=120)

    class Meta(TenantScopedModel.Meta):
        db_table = "service_category"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "name"], name="service_category_name_unique")
        ]


# ----------------------------------------------------------------- contacts

class ReferralCadence(models.TextChoices):
    MONTHLY = "monthly", "Monthly"
    BIMONTHLY = "bimonthly", "Bi-monthly"
    QUARTERLY = "quarterly", "Quarterly"


class Contact(TenantScopedModel):
    first_name = models.CharField(max_length=120, db_index=True)
    last_name = models.CharField(max_length=120, db_index=True)
    title = models.CharField(max_length=160, blank=True, default="")
    company = models.ForeignKey(
        Company, null=True, blank=True, on_delete=models.SET_NULL, related_name="contacts"
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="owned_contacts",
    )
    # FR-1.6a — AUTHORITATIVE for "is a client". Type and the company flag are
    # derived from this, one way only.
    stage = models.ForeignKey(
        PipelineStage, null=True, blank=True, on_delete=models.PROTECT, related_name="contacts"
    )
    source = models.CharField(max_length=120, blank=True, default="")

    # §12.2 — renamed from `notes`. One thing in this product is called a note
    # and it is the `note` table; this is a short "who this is / how we met".
    background = models.TextField(blank=True, default="")
    # Postgres text[] with a GIN index, per the data model. Postgres is settled
    # for this project; nothing here is designed for backend neutrality.
    tags = ArrayField(models.CharField(max_length=64), default=list, blank=True)

    types = models.ManyToManyField(
        ContactType, through="crm.ContactTypeLink", related_name="contacts"
    )
    service_categories = models.ManyToManyField(
        ServiceCategory, through="crm.ContactServiceCategory", related_name="contacts"
    )

    # Referral partner fields (FR-1.20, 1.20a, 1.23c)
    referral_fee_terms = models.CharField(max_length=255, blank=True, default="")
    referral_cadence = models.CharField(
        max_length=16, choices=ReferralCadence.choices, blank=True, default=""
    )
    # FR-1.22 — "the tenant chooses per contact" between AI-drafted prose and an
    # FF-written template. The data model had no column for that choice; this is
    # the smallest thing that expresses it, and it keeps the two states from
    # contradicting each other (a template can be attached without switching).
    referral_touch_mode = models.CharField(
        max_length=12,
        choices=[("ai", "AI-drafted"), ("template", "FF-written template")],
        default="ai",
    )
    referral_template = models.ForeignKey(
        "crm.EmailTemplate", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    referral_next_touch_at = models.DateTimeField(null=True, blank=True)
    # Presence prevents onboarding re-triggering (FR-1.23d).
    referral_onboarded_at = models.DateTimeField(null=True, blank=True)

    search_vector = SearchVectorField(null=True, blank=True)
    # FR-1.34 — survivor pointer after a merge.
    merged_into = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="merged_from"
    )
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "contact"
        indexes = [
            GinIndex(fields=["search_vector"], name="contact_search_gin"),
            GinIndex(fields=["tags"], name="contact_tags_gin"),
            models.Index(fields=["tenant", "stage"]),
            models.Index(fields=["tenant", "owner"]),
        ]

    def __str__(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def primary_email(self):
        """Scoped by this row's own tenant, not through the reverse manager.

        The reverse manager is fail-closed (B1) and so needs ambient tenant
        context; a Contact already knows its tenant. Same reasoning as
        Company.seats_in_use — a model property must not break in a management
        command or a background job. `all_objects` here is narrowed by an
        explicit tenant filter, so nothing is unscoped.
        """
        row = (
            ContactEmail.all_objects.filter(tenant_id=self.tenant_id, contact_id=self.pk)
            .order_by("-is_primary", "created_at")
            .first()
        )
        return row.address if row else None


class ContactEmail(TenantScopedModel):
    """Multiple per contact, one primary (FR-1.1). Stakeholder delivery uses the
    primary (FR-3.20); email match is the first matching rule (FR-5.10)."""

    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name="emails")
    address = models.EmailField(db_index=True)
    is_primary = models.BooleanField(default=False)

    class Meta(TenantScopedModel.Meta):
        db_table = "contact_email"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "contact"], condition=models.Q(is_primary=True),
                name="contact_email_one_primary",
            )
        ]


class ContactPhone(TenantScopedModel):
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name="phones")
    number = models.CharField(max_length=40)
    is_primary = models.BooleanField(default=False)

    class Meta(TenantScopedModel.Meta):
        db_table = "contact_phone"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "contact"], condition=models.Q(is_primary=True),
                name="contact_phone_one_primary",
            )
        ]


class ContactTypeLink(TenantScopedModel):
    """FR-1.2 — multi-type, because a referral partner is frequently also a
    client and forcing one type would make one relationship invisible."""

    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name="type_links")
    contact_type = models.ForeignKey(ContactType, on_delete=models.PROTECT, related_name="links")
    is_primary = models.BooleanField(default=False)

    class Meta(TenantScopedModel.Meta):
        db_table = "contact_type_link"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "contact", "contact_type"], name="contact_type_link_unique"
            )
        ]


class ContactServiceCategory(TenantScopedModel):
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name="category_links")
    service_category = models.ForeignKey(
        ServiceCategory, on_delete=models.CASCADE, related_name="links"
    )

    class Meta(TenantScopedModel.Meta):
        db_table = "contact_service_category"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "contact", "service_category"],
                name="contact_service_category_unique",
            )
        ]


class StageChange(TenantScopedModel):
    """FR-1.7 — actor, timestamp, from/to, optional reason."""

    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name="stage_changes")
    from_stage = models.ForeignKey(
        PipelineStage, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    to_stage = models.ForeignKey(PipelineStage, on_delete=models.PROTECT, related_name="+")
    reason = models.TextField(blank=True, default="")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(TenantScopedModel.Meta):
        db_table = "stage_change"
        ordering = ["-created_at"]


# --------------------------------------------------------- automations, mail

class EmailTemplate(TenantScopedModel):
    class Kind(models.TextChoices):
        STAGE = "stage", "Stage change"
        REFERRAL_TOUCH = "referral_touch", "Referral touch"
        REFERRAL_ONBOARDING = "referral_onboarding", "Referral onboarding"
        PRECALL_INVITE = "precall_invite", "Pre-call invite"

    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=32, choices=Kind.choices)
    subject = models.CharField(max_length=255)
    body = models.TextField()

    class Meta(TenantScopedModel.Meta):
        db_table = "email_template"


class StageAutomation(TenantScopedModel):
    """FR-1.10-1.14. `create_task` fires immediately; `draft_email` only ever
    produces a pending_approval Outbox row (assumption F3)."""

    class Action(models.TextChoices):
        CREATE_TASK = "create_task", "Create a task"
        DRAFT_EMAIL = "draft_email", "Draft an email into the Outbox"

    from_stage = models.ForeignKey(
        PipelineStage, null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )  # null = any
    to_stage = models.ForeignKey(PipelineStage, on_delete=models.CASCADE, related_name="+")
    action_type = models.CharField(max_length=16, choices=Action.choices)

    task_title_template = models.CharField(max_length=255, blank=True, default="")
    task_due_offset_days = models.IntegerField(null=True, blank=True)
    email_template = models.ForeignKey(
        EmailTemplate, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    # FR-1.12 — default 7 days, configurable per rule.
    send_by_offset_days = models.PositiveSmallIntegerField(default=7)
    is_active = models.BooleanField(default=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "stage_automation"


# ------------------------------------------------------- threading (carve-back)

class EmailThread(TenantScopedModel):
    """Carved back from Module 6 (ruling 9.3).

    Module 1 promises a CF "send from my own address" and a `manual`
    direct-to-sent producer, so every outbound message needs a thread and a
    token from Phase 1. The inbound half stays in Module 6.
    """

    thread_token = models.CharField(max_length=48, unique=True, db_index=True)
    contact = models.ForeignKey(
        Contact, null=True, blank=True, on_delete=models.SET_NULL, related_name="threads"
    )
    client_company = models.ForeignKey(
        Company, null=True, blank=True, on_delete=models.SET_NULL, related_name="threads"
    )
    # Tier 2 match key (FR-6.6). Populated by Module 6; the column exists now so
    # Phase 1 sends can record it.
    gmail_thread_id = models.CharField(max_length=120, blank=True, default="", db_index=True)
    subject = models.CharField(max_length=255, blank=True, default="")
    last_message_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "email_thread"

    @staticmethod
    def new_token():
        import secrets

        return secrets.token_urlsafe(18)


class GmailConnection(TenantScopedModel):
    """Tier 1 connect (FR-6.3b). `gmail.send` only.

    Tier 2 adds `gmail.readonly` — a restricted scope over the whole mailbox —
    and is opt-in per user (FR-6.3g). VAs get neither (H7).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="gmail_connections"
    )
    email_address = models.EmailField()
    scopes = models.JSONField(default=list)
    tier2_enabled = models.BooleanField(default=False)
    last_polled_at = models.DateTimeField(null=True, blank=True)
    secret = models.ForeignKey(
        "tenancy.TenantSecret", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(TenantScopedModel.Meta):
        db_table = "gmail_connection"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "user"], name="gmail_connection_one_per_user")
        ]


class EmailMessage(TenantScopedModel):
    """Outbound is recorded in Phase 1; inbound arrives with Module 6."""

    thread = models.ForeignKey(EmailThread, on_delete=models.CASCADE, related_name="messages")
    direction = models.CharField(
        max_length=8, choices=[("outbound", "Outbound"), ("inbound", "Inbound")]
    )
    provider = models.CharField(max_length=16)  # postmark | gmail
    provider_message_id = models.CharField(max_length=255, blank=True, default="")
    from_address = models.EmailField()
    to_addresses = models.JSONField(default=list)
    cc_addresses = models.JSONField(default=list, blank=True)
    subject = models.CharField(max_length=255, blank=True, default="")
    body_html = models.TextField(blank=True, default="")
    body_text = models.TextField(blank=True, default="")
    body_stripped = models.TextField(blank=True, default="")
    raw = models.JSONField(default=dict, blank=True)
    contact = models.ForeignKey(
        Contact, null=True, blank=True, on_delete=models.SET_NULL, related_name="email_messages"
    )
    matched_by = models.CharField(max_length=24, blank=True, default="")
    received_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "email_message"
        constraints = [
            # FR-6.12 — a redelivered webhook must not duplicate a message.
            models.UniqueConstraint(
                fields=["tenant", "provider", "provider_message_id"],
                condition=~models.Q(provider_message_id=""),
                name="email_message_provider_id_unique",
            )
        ]


# ------------------------------------------------------------------- outbox

class OutboxMessage(TenantScopedModel):
    """FR-1.15 — both the approval queue AND the complete send log.

    If a message left the app, there is a row here. Rows a human explicitly
    clicked are written directly as `sent` (FR-1.15b); everything else enters
    at `pending_approval`.
    """

    class State(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING_APPROVAL = "pending_approval", "Pending approval"
        APPROVED = "approved", "Approved"
        SENT = "sent", "Sent"
        REJECTED = "rejected", "Rejected"
        EXPIRED = "expired", "Expired"

    class Producer(models.TextChoices):
        STAGE_RULE = "stage_rule", "Stage rule"
        REFERRAL_TOUCH = "referral_touch", "Referral touch"
        REFERRAL_ONBOARDING = "referral_onboarding", "Referral onboarding"
        DIGEST = "digest", "Progress digest"
        STRATEGY_PDF = "strategy_pdf", "Strategy session PDF"
        PRECALL_INVITE = "precall_invite", "Pre-call invite"
        MAGIC_LINK = "magic_link", "Magic link"
        CADENCE_CHANGE = "cadence_change", "Cadence change"
        INBOUND_FORWARD = "inbound_forward", "Inbound forward"
        MANUAL = "manual", "Manual"

    #: FR-1.15b. `manual` and `precall_invite` are role-dependent and resolved
    #: at creation time, not listed here.
    ALWAYS_DIRECT_TO_SENT = {
        Producer.STRATEGY_PDF, Producer.MAGIC_LINK,
        Producer.CADENCE_CHANGE, Producer.INBOUND_FORWARD,
    }

    state = models.CharField(max_length=20, choices=State.choices, db_index=True)
    producer = models.CharField(max_length=24, choices=Producer.choices, db_index=True)
    to_contact = models.ForeignKey(
        Contact, null=True, blank=True, on_delete=models.SET_NULL, related_name="outbox_messages"
    )
    to_address = models.EmailField()  # resolved at creation; survives contact edits
    from_address = models.EmailField()
    subject = models.CharField(max_length=255)
    body_html = models.TextField(blank=True, default="")
    body_text = models.TextField(blank=True, default="")
    # Drives the Outbox label (FR-1.23) and the approval rule (FR-3.27).
    is_ai_generated = models.BooleanField(default=False)
    warning = models.TextField(blank=True, default="")  # e.g. stale blurb (FR-1.22a)
    send_by = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    provider_message_id = models.CharField(max_length=255, blank=True, default="")
    thread = models.ForeignKey(
        EmailThread, null=True, blank=True, on_delete=models.SET_NULL, related_name="outbox_messages"
    )
    sent_via = models.CharField(max_length=16, blank=True, default="")  # postmark | gmail
    # H6 — a real send from a localhost build is badged, not invisible.
    dev_real_send = models.BooleanField(default=False)
    source_type = models.CharField(max_length=40, blank=True, default="")
    source_id = models.UUIDField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "outbox_message"
        indexes = [models.Index(fields=["tenant", "state", "send_by"])]


class OutboxAttachment(TenantScopedModel):
    """Carries the marketing flyer on referral onboarding (FR-1.23b)."""

    outbox_message = models.ForeignKey(
        OutboxMessage, on_delete=models.CASCADE, related_name="attachments"
    )
    stored_file = models.ForeignKey(
        "tenancy.StoredFile", on_delete=models.PROTECT, related_name="+"
    )
    filename = models.CharField(max_length=255)

    class Meta(TenantScopedModel.Meta):
        db_table = "outbox_attachment"


# ------------------------------------------------------------------- import

class ImportMappingProfile(TenantScopedModel):
    name = models.CharField(max_length=120)
    mapping = models.JSONField(default=dict)

    class Meta(TenantScopedModel.Meta):
        db_table = "import_mapping_profile"


class ImportBatch(TenantScopedModel):
    """FR-1.26-1.32 — three-step, reversible."""

    class Status(models.TextChoices):
        DRY_RUN = "dry_run", "Dry run"
        COMMITTED = "committed", "Committed"
        ROLLED_BACK = "rolled_back", "Rolled back"

    filename = models.CharField(max_length=255)
    mapping_profile = models.ForeignKey(
        ImportMappingProfile, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRY_RUN)
    counts = models.JSONField(default=dict)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    rolled_back_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "import_batch"


class ImportRow(TenantScopedModel):
    class Outcome(models.TextChoices):
        CREATE = "create", "Create"
        UPDATE = "update", "Update"
        SKIP = "skip", "Skip"
        ERROR = "error", "Error"
        AMBIGUOUS = "ambiguous", "Ambiguous match"

    import_batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name="rows")
    row_number = models.PositiveIntegerField()
    raw = models.JSONField(default=dict)
    outcome = models.CharField(max_length=12, choices=Outcome.choices)
    error_text = models.TextField(blank=True, default="")
    contact = models.ForeignKey(
        Contact, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # FR-1.31 — what makes rollback real: the pre-import value of every field
    # the import changed, so an update can be reversed field by field.
    previous_values = models.JSONField(null=True, blank=True)
    # FR-1.29 — the ranked candidates behind an `ambiguous` outcome, persisted
    # so the reviewer resolves the SAME set the dry run reported rather than a
    # recomputed one that may have drifted.
    candidate_ids = models.JSONField(default=list, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "import_row"
        ordering = ["row_number"]


# ------------------------------------------------------------------- tasks

class Task(TenantScopedModel):
    """Module 3's table, created early for one Module 1 requirement.

    FR-1.11 says a `create_task` stage rule "fires immediately, no approval".
    Module 1 therefore depends on this table. Created here with ONLY the columns
    a stage rule needs; Module 3 adds project, goal, client_company, assignee,
    is_client_visible, created_by_client, client_owner_contact,
    source_map_row, source_proposal_item, checklist items, comments, and
    stakeholders.

    Same precedent as `note` (owner ruling, data model §note). The full status
    set from FR-3.7 is declared now so Phase 3 does not have to migrate values.
    """

    class Status(models.TextChoices):
        NOT_STARTED = "not_started", "Not started"
        IN_PROGRESS = "in_progress", "In progress"
        BLOCKED = "blocked", "Blocked"
        WAITING_ON_CLIENT = "waiting_on_client", "Waiting on client"
        DONE = "done", "Done"
        CANCELLED = "cancelled", "Cancelled"

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.NOT_STARTED, db_index=True
    )
    due_date = models.DateField(null=True, blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="owned_tasks",
    )
    contact = models.ForeignKey(
        Contact, null=True, blank=True, on_delete=models.SET_NULL, related_name="tasks"
    )
    # Provenance: which stage rule created this, if any (FR-1.11).
    source_automation = models.ForeignKey(
        StageAutomation, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="created_tasks",
    )
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "task"

    def __str__(self):
        return self.title
