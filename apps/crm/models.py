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


class Pipeline(TenantScopedModel):
    """FR-1.6 — a practice runs more than one (owner, Check 1).

    A sales pipeline for prospects and a nurture pipeline for referral partners
    are different processes with different stages, and collapsing them into one
    made every referral partner look like a stalled prospect. `kind` is what
    behaviour keys on; `name` is the FF's to change.
    """

    class Kind(models.TextChoices):
        SALES = "sales", "Sales"
        REFERRAL = "referral", "Referral partners"
        CUSTOM = "custom", "Custom"

    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.CUSTOM)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta(TenantScopedModel.Meta):
        db_table = "pipeline"
        ordering = ["position", "name"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "name"], name="pipeline_name_unique"),
        ]

    def __str__(self):
        return self.name

    @property
    def won_stage(self):
        return self.stages.filter(semantic=StageSemantic.WON).first()


class StageSemantic(models.TextChoices):
    """What a stage MEANS, independent of what it is called.

    The labels are the owner's ("Consult Given", "Proposal Given") and the FF
    renames them freely. Behaviour cannot key on a label that changes, so every
    rule in the app keys on this instead: the client invariant on `won` in a
    sales pipeline, the non-linear states on `lost` and `parked`.
    """

    ENTRY = "entry", "Entry"
    WORKING = "working", "Working"
    QUALIFIED = "qualified", "Qualified"
    WON = "won", "Won"
    LOST = "lost", "Lost"
    PARKED = "parked", "Parked"
    NONE = "none", "No semantic"


class PipelineStage(TenantScopedModel):
    """A stage within one pipeline. FF may rename, reorder, add and remove."""

    pipeline = models.ForeignKey(
        Pipeline, on_delete=models.CASCADE, related_name="stages"
    )
    code = models.CharField(max_length=32)
    label = models.CharField(max_length=64)
    semantic = models.CharField(
        max_length=12, choices=StageSemantic.choices, default=StageSemantic.NONE
    )
    position = models.PositiveSmallIntegerField(default=0)

    class Meta(TenantScopedModel.Meta):
        db_table = "pipeline_stage"
        ordering = ["position"]
        constraints = [
            # Per pipeline now: "Qualified" may legitimately exist in two.
            models.UniqueConstraint(
                fields=["tenant", "pipeline", "code"], name="pipeline_stage_code_unique"
            ),
            # At most one `won` per pipeline, in the database. "At least one for
            # a sales pipeline" is a cross-row rule and lives in the service.
            models.UniqueConstraint(
                fields=["tenant", "pipeline"], condition=models.Q(semantic="won"),
                name="pipeline_stage_one_won",
            ),
        ]

    def __str__(self):
        return self.label

    @property
    def is_terminal(self):
        """Derived, not stored: a second column would drift from the semantic."""
        return self.semantic in (StageSemantic.LOST, StageSemantic.PARKED)

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
    # FR-1.6a — a contact's position is now per pipeline, in
    # `contact_pipeline_position`. A referral partner who becomes a prospect is
    # in both at once, which one nullable FK could not express.
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


class ContactPipelinePosition(TenantScopedModel):
    """Where a contact sits in ONE pipeline (FR-1.6).

    Replaces `contact.stage_id`. A contact may hold a position in several
    pipelines at once — a referral partner who becomes a prospect is genuinely
    in both, and the old single FK forced a choice that lost one of them.

    Contact **type does not gate membership**: being in the referral pipeline is
    not the same fact as carrying the referral_partner type, and conflating them
    made one of the two invisible.
    """

    contact = models.ForeignKey(
        Contact, on_delete=models.CASCADE, related_name="pipeline_positions"
    )
    pipeline = models.ForeignKey(
        Pipeline, on_delete=models.PROTECT, related_name="positions"
    )
    stage = models.ForeignKey(
        PipelineStage, on_delete=models.PROTECT, related_name="positions"
    )
    entered_at = models.DateTimeField(auto_now_add=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "contact_pipeline_position"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "contact", "pipeline"],
                name="contact_pipeline_position_unique",
            )
        ]
        indexes = [models.Index(fields=["tenant", "pipeline", "stage"])]


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
    # Denormalised from to_stage: `from_stage` is null on a first entry, so the
    # pipeline a change belongs to cannot always be read off the other end.
    pipeline = models.ForeignKey(
        Pipeline, on_delete=models.PROTECT, related_name="stage_changes"
    )
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

    # FR-1.10 — rules are per pipeline. A "becomes Qualified" rule on the sales
    # pipeline must not fire for the referral pipeline's own Qualified stage.
    pipeline = models.ForeignKey(
        Pipeline, on_delete=models.CASCADE, related_name="automations"
    )
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


class MailPreference(TenantScopedModel):
    """Per-user sender defaults and signature (FR-1.15c).

    Everything went out from the practice alias, which is right for a digest and
    wrong for a referral touch: a partner being asked for introductions should
    hear from a person, not from `info@`. The default below encodes exactly
    that split, and the FF can change it per producer.

    Both choices are restricted to **verified** send-as addresses, because Gmail
    refuses anything else and a silent rejection at send time would be worse
    than not offering the option.
    """

    class Sender(models.TextChoices):
        ALIAS = "alias", "The practice alias"
        SELF = "self", "My own address"

    #: Producer -> Sender. Defaults are applied in `sender_for`, not stored, so
    #: an unset producer follows the product default rather than a stale copy.
    DEFAULTS = {
        "referral_touch": Sender.SELF,
        "referral_onboarding": Sender.SELF,
        "stage_rule": Sender.ALIAS,
        "manual": Sender.ALIAS,
    }

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mail_preference"
    )
    #: {producer: "alias" | "self"} — only the ones deliberately overridden.
    sender_by_producer = models.JSONField(default=dict, blank=True)
    #: FR-1.15d — replaces the bare practice name as a sign-off.
    signature_text = models.TextField(blank=True, default="")
    signature_html = models.TextField(blank=True, default="")

    class Meta(TenantScopedModel.Meta):
        db_table = "mail_preference"

    def sender_for(self, producer):
        choice = (self.sender_by_producer or {}).get(producer)
        if choice in (self.Sender.ALIAS, self.Sender.SELF):
            return choice
        return self.DEFAULTS.get(producer, self.Sender.ALIAS)


class DevSendAllowlistEntry(TenantScopedModel):
    """FR-0.7 / H6 — an exact address that may receive REAL mail from a
    localhost build.

    `DEV_REAL_SEND_ALLOWLIST` in `.env` already does this, but editing it means
    a file edit and a server restart mid-check. These rows are the same
    mechanism made changeable from the UI, and the two are unioned — `.env`
    entries can never be removed from the app, so the environment stays the
    floor rather than something the UI can quietly lower.

    Exact addresses only. A bare domain or a wildcard would put every colleague
    and client at that domain back in range, which is the whole thing H6 exists
    to prevent.
    """

    address = models.EmailField()
    note = models.CharField(max_length=200, blank=True, default="")
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta(TenantScopedModel.Meta):
        db_table = "dev_send_allowlist_entry"
        verbose_name_plural = "dev send allowlist entries"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "address"], name="dev_send_allowlist_unique"
            )
        ]

    def __str__(self):
        return self.address


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

    # The tenant's send-as alias (e.g. info@getexecutivesnow.com) and whether
    # Gmail has confirmed this account may send as it. Beta sends ALL
    # app-originated mail through this connection, so an unverified alias is a
    # hard error rather than a silent fallback to the personal address.
    send_as_address = models.EmailField(blank=True, default="")
    send_as_verified_at = models.DateTimeField(null=True, blank=True)
    send_as_error = models.TextField(blank=True, default="")
    # Tier 2 inbound: the history cursor, and the last poll's outcome.
    history_id = models.CharField(max_length=40, blank=True, default="")
    last_poll_error = models.TextField(blank=True, default="")
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

    # RFC 5322 threading. With no inbound domain in Beta there is no
    # reply+<token>@ address, so the thread token rides in the Message-ID and a
    # custom header instead, and replies are matched by Gmail thread id or by
    # In-Reply-To / References pointing at a Message-ID we issued.
    message_id_header = models.CharField(max_length=255, blank=True, default="", db_index=True)
    in_reply_to = models.CharField(max_length=255, blank=True, default="")
    references = models.TextField(blank=True, default="")
    gmail_message_id = models.CharField(max_length=120, blank=True, default="", db_index=True)
    gmail_thread_id = models.CharField(max_length=120, blank=True, default="", db_index=True)

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
        NOTE_PIN_RESET = "note_pin_reset", "Note PIN reset"
        CLIENT_ACTIVITY = "client_activity", "Client activity notice"
        CADENCE_CHANGE = "cadence_change", "Cadence change"
        INBOUND_FORWARD = "inbound_forward", "Inbound forward"
        MANUAL = "manual", "Manual"

    #: FR-1.15b. `manual` and `precall_invite` are role-dependent and resolved
    #: at creation time, not listed here.
    ALWAYS_DIRECT_TO_SENT = {
        Producer.STRATEGY_PDF, Producer.MAGIC_LINK, Producer.NOTE_PIN_RESET,
        # Internal, to the practice's own people: no approval gate applies, but
        # it is in the Outbox because every message that left is (FR-1.15).
        Producer.CLIENT_ACTIVITY,
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
    """A remembered column mapping, and the value mapping that goes with it.

    The two are saved together deliberately: a value mapping is meaningless
    without knowing which column produced those values, so splitting them
    across two profiles would let them drift apart.
    """

    name = models.CharField(max_length=120)
    mapping = models.JSONField(default=dict)
    # {raw CSV value: {"contact_type": code, "stage": code, "ignore": bool}}
    value_mapping = models.JSONField(default=dict, blank=True)

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
    # What the dry run was computed with. Persisted so the commit writes what
    # the preview showed: re-sending the mapping from the browser let the two
    # drift, which is the one thing a dry run exists to prevent.
    mapping = models.JSONField(default=dict, blank=True)
    value_mapping = models.JSONField(default=dict, blank=True)
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
    # FR-1.28 — the row as it WILL be written: phones, tags, types, stage.
    # Computed by the dry run with the same code the commit uses, so the
    # preview cannot disagree with the result.
    preview = models.JSONField(default=dict, blank=True)
    # Rollback needs more than scalar fields once an import can write phones
    # and type links: these are the rows it created, to be removed again.
    created_related = models.JSONField(default=dict, blank=True)
    # ...and the pre-import stage and tags, which are not plain CONTACT_FIELDS.
    previous_related = models.JSONField(default=dict, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "import_row"
        ordering = ["row_number"]


# ------------------------------------------------------------------- tasks

class Task(TenantScopedModel):
    """Module 3's table, created early for one Module 1 requirement.

    FR-1.11 says a `create_task` stage rule "fires immediately, no approval".
    Module 1 therefore depends on this table, so Phase 1 created it with only
    the columns a stage rule needs, and the full FR-3.7 status set so no value
    ever had to be migrated.

    **Phase 3 adds** the columns below the Phase 1 block: the hierarchy links,
    client company and assignee, client-side owner, priority, and the two
    visibility flags. `task_checklist_item`, `comment`, `task_update` and
    `stakeholder` live in `apps.work`, which is where everything else Module 3
    introduces lives; the table stays here because stage automations write it.

    Still deferred, because their target tables do not exist yet:
    `source_map_row_id` (Module 4) and `source_proposal_item_id` (Module 5).
    Each arrives as a real foreign key with the table it points at.

    **No `parent_task_id`, ever.** Three levels is enforced by the absence of
    the column (FR-3.4); sub-steps are checklist items.
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

    # ------------------------------------------------------ Phase 3 (Module 3)

    # FR-3.5 — both nullable, so a standalone task is a first-class thing.
    # SET_NULL, because deleting a goal or project detaches its children and
    # reports them rather than deleting work (FR-3.6).
    project = models.ForeignKey(
        "work.Project", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="tasks",
    )
    goal = models.ForeignKey(
        "work.Goal", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="tasks",
    )
    client_company = models.ForeignKey(
        Company, null=True, blank=True, on_delete=models.SET_NULL, related_name="tasks",
    )
    # The app user doing the work. A client user may only be assigned, or
    # assign, within their own company (FR-3.9).
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="assigned_tasks",
    )
    # Who on the client side is accountable — a Contact, since strategy map
    # rows and meeting action items name people who may have no login (FR-3.3a).
    client_owner_contact = models.ForeignKey(
        Contact, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    priority = models.SmallIntegerField(default=1)  # work.Priority
    # FR-3.11 — set true at creation when the task has a client company, false
    # otherwise. A default cannot express that, so the code path does; the
    # column default is the safe one.
    is_client_visible = models.BooleanField(default=False)
    created_by_client = models.BooleanField(default=False)  # FR-3.37

    class Meta(TenantScopedModel.Meta):
        db_table = "task"
        indexes = [
            models.Index(fields=["tenant", "client_company", "status"]),
            models.Index(fields=["tenant", "project"]),
        ]

    def __str__(self):
        return self.title
