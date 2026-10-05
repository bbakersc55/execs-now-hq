"""Foundation tables (data model §1).

Conventions applied to every domain table, per `02_data_model.md` §0:
UUID PK, tenant FK with PROTECT, created_at/updated_at, tenant-scoped uniques.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from .context import get_current_tenant_id
from .managers import AllTenantsManager, TenantManager
from .roles import ROLE_LABEL


class UUIDModel(models.Model):
    """UUID primary keys everywhere (assumption D1).

    Record ids appear in magic links, portal URLs, and emailed PDF links;
    sequential integers advertise record counts and invite enumeration.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class TenantScopedModel(UUIDModel):
    """Every domain table inherits this. The isolation meta-test enforces it."""

    tenant = models.ForeignKey(
        "tenancy.Tenant",
        on_delete=models.PROTECT,
        db_index=True,
        related_name="%(app_label)s_%(class)s_set",
    )

    objects = TenantManager()
    all_objects = AllTenantsManager()

    class Meta:
        abstract = True
        # Django uses the base manager for related-object traversal. Pointing it
        # at the unscoped manager keeps FK access working while `objects` stays
        # fail-closed; the scope is still enforced on every query you write.
        base_manager_name = "all_objects"

    def save(self, *args, **kwargs):
        if self.tenant_id is None:
            current = get_current_tenant_id()
            if current is not None:
                self.tenant_id = current
        super().save(*args, **kwargs)

    def clean(self):
        """Reject cross-tenant foreign keys.

        Postgres cannot express "both sides share a tenant" as a simple FK, so
        it is a validation rule plus a test in the isolation registry (§0).
        """
        super().clean()
        if self.tenant_id is None:
            return
        for field in self._meta.concrete_fields:
            if not field.is_relation or field.name == "tenant":
                continue
            related_id = getattr(self, field.attname, None)
            if related_id is None:
                continue
            related_model = field.related_model
            if not issubclass(related_model, TenantScopedModel):
                continue
            other = related_model.all_objects.filter(pk=related_id).values_list(
                "tenant_id", flat=True
            ).first()
            if other is not None and other != self.tenant_id:
                raise ValidationError(
                    {field.name: f"{field.name} belongs to a different practice."}
                )


class Tenant(UUIDModel):
    """The practice. One row in Beta. The only table with no tenant_id."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        #: Provisioned; the practice owner has not signed in yet.
        INVITED = "invited", "Invited"
        #: Nobody signs in, nothing runs or sends; every row is kept.
        ARCHIVED = "archived", "Archived"

    class OAuthClient(models.TextChoices):
        #: The Executives Now Workspace client (consent screen Internal).
        INTERNAL = "internal", "Executives Now Workspace"
        #: The second client, External (P2 D1), for every other practice.
        EXTERNAL = "external", "External"

    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    # P2 (2026-10-02): the Practices area.
    legal_name = models.CharField(max_length=200, blank=True, default="", db_default="")
    domain = models.CharField(max_length=253, blank=True, default="", db_default="")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE,
                              db_default=Status.ACTIVE)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    oauth_client = models.CharField(max_length=12, choices=OAuthClient.choices,
                                    default=OAuthClient.INTERNAL,
                                    db_default=OAuthClient.INTERNAL)
    timezone = models.CharField(max_length=64, default="America/Denver")  # D4
    from_address = models.EmailField(default="info@getexecutivesnow.com")  # H2
    inbound_domain = models.CharField(
        max_length=200, default="inbound.getexecutivesnow.com"
    )
    discipline = models.CharField(max_length=32, default="operations")

    # FR-3.25 — the master safety switch. ON by default for Beta.
    hold_all_digests = models.BooleanField(default=True)
    digest_ai_prose_default = models.BooleanField(default=True)  # FR-3.24
    digest_send_day = models.PositiveSmallIntegerField(default=5)  # Friday
    digest_send_hour = models.PositiveSmallIntegerField(default=8)
    # AI spend (owner, 2026-09-28). Anthropic does not tell us the account's
    # balance, so the FF types what is on the account when they top up, and the
    # app subtracts what it has logged since — an estimate, and labelled so.
    ai_credits_usd = models.DecimalField(max_digits=10, decimal_places=2, null=True,
                                         blank=True)
    ai_credits_as_of = models.DateField(null=True, blank=True)
    ai_monthly_budget_usd = models.DecimalField(max_digits=10, decimal_places=2,
                                                null=True, blank=True)
    #: A hard stop on what the worker may spend on Claude in one practice day
    #: without anybody asking (owner, 2026-09-29). FF-set on AI usage.
    #: Person-initiated calls are never counted or stopped. apps/tenancy/ai_guard.py.
    ai_unattended_daily_cap_usd = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("5.00"), db_default=Decimal("5.00"))
    # Branding — the name, colours and logo every client-facing surface wears:
    # email (apps/crm/services/email_layout.py) and the portal, sign-in and
    # cadence pages through /api/branding. **White-label**: the defaults are a
    # practice's own name over neutral greys, never the product's name or
    # palette — Executives Now's values sit on its own tenant row (migration
    # tenancy 0005) exactly as another practice's would. Blank display name
    # falls back to `name`. `db_default` too, so a database migrated ahead of
    # the code still accepts rows written by code that does not know these
    # columns.
    email_display_name = models.CharField(max_length=80, blank=True, default="", db_default="")
    email_header_color = models.CharField(max_length=7, default="#1F2933",
                                          db_default="#1F2933")
    email_accent_color = models.CharField(max_length=7, default="#7B8794",
                                          db_default="#7B8794")
    # The header logo (PNG or JPEG) and its DISPLAY size in px, fitted to the
    # header when it is set (`manage.py set_email_logo`). No logo: the header
    # shows `email_display_name`.
    email_logo = models.ForeignKey(
        "tenancy.StoredFile", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    email_logo_width = models.PositiveSmallIntegerField(default=0, db_default=0)
    email_logo_height = models.PositiveSmallIntegerField(default=0, db_default=0)
    # The square mark beside the sign-off on mail from a person
    # (`set_email_logo --mark`). No mark: the sign-off has no image.
    email_mark = models.ForeignKey(
        "tenancy.StoredFile", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    email_mark_width = models.PositiveSmallIntegerField(default=0, db_default=0)
    email_mark_height = models.PositiveSmallIntegerField(default=0, db_default=0)
    # P1 (2026-10-02): the practice-wide footer under every client-facing email
    # (address, phone, website), and when the practice owner last saved
    # Settings → Branding. Null = never set: the neutral defaults, and P2's
    # "Set branding" checklist item still open. apps/tenancy/branding.py.
    brand_footer_text = models.TextField(blank=True, default="", db_default="")
    branding_updated_at = models.DateTimeField(null=True, blank=True)
    audio_retention_days = models.PositiveIntegerField(default=30)  # F7

    referral_blurb = models.TextField(blank=True, default="")  # FR-1.21a
    referral_blurb_updated_at = models.DateTimeField(null=True, blank=True)
    marketing_flyer = models.ForeignKey(
        "tenancy.StoredFile", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    objects = models.Manager()

    class Meta:
        db_table = "tenant"

    def __str__(self):
        return self.name


class Role(models.TextChoices):
    # Labels: apps/tenancy/roles.py, the one place a role's name is set.
    FF = "FF", ROLE_LABEL["FF"]
    CF = "CF", ROLE_LABEL["CF"]
    VA = "VA", ROLE_LABEL["VA"]
    FCC = "FCC", ROLE_LABEL["FCC"]
    ECC = "ECC", ROLE_LABEL["ECC"]


CLIENT_ROLES = {Role.FCC, Role.ECC}
TENANT_ROLES = {Role.FF, Role.CF, Role.VA}


class Membership(TenantScopedModel):
    """User x tenant x role. One per user in Beta (assumption B4)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(max_length=4, choices=Role.choices)
    client_company = models.ForeignKey(
        "crm.Company", null=True, blank=True,
        on_delete=models.PROTECT, related_name="memberships",
    )
    # Assumption F1 — every human is a Contact; a login attaches to one.
    # Deferred from Phase 0.5 because §11 fixes the order as company ->
    # contact -> the FKs pointing at contact. Contact now exists.
    contact = models.ForeignKey(
        "crm.Contact", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="memberships",
    )
    # UI 3: the person's profile picture, a 256x256 JPEG. On the membership,
    # not the user: files are stored per practice, and a client user's
    # membership is what ties the picture to their company for who may see it.
    avatar = models.ForeignKey(
        "tenancy.StoredFile", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="invitations_sent",
    )
    invited_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)  # FR-3.33g

    class Meta(TenantScopedModel.Meta):
        db_table = "membership"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "user"], name="membership_one_per_user_per_tenant"
            ),
            # The one invariant worth expressing in the database rather than in
            # code: a client user without a company is an unbounded client user.
            models.CheckConstraint(
                condition=(
                    models.Q(role__in=["FCC", "ECC"], client_company__isnull=False)
                    | models.Q(role__in=["FF", "CF", "VA"], client_company__isnull=True)
                ),
                name="membership_client_role_requires_company",
            ),
        ]

    @property
    def is_active_membership(self):
        return self.revoked_at is None

    @property
    def is_client_user(self):
        return self.role in CLIENT_ROLES


class ClientAssignment(TenantScopedModel):
    """Tenant user x client company (FR-1.9a).

    Every "assigned accounts" rule in Modules 1-6 resolves here, which is why
    it is an explicit table rather than a rule reimplemented per module.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="client_assignments"
    )
    company = models.ForeignKey(
        "crm.Company", on_delete=models.PROTECT, related_name="assignments"
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="assignments_made",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    removed_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "client_assignment"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "user", "company"],
                condition=models.Q(removed_at__isnull=True),
                name="client_assignment_unique_live",
            )
        ]


class SecretKind(models.TextChoices):
    ANTHROPIC_API_KEY = "anthropic_api_key", "Anthropic API key"
    GMAIL_REFRESH = "gmail_refresh", "Gmail refresh token"
    DRIVE_REFRESH = "drive_refresh", "Drive refresh token"


class TenantSecret(TenantScopedModel):
    """Encrypted at rest; write-only across the entire API (assumption E1).

    The Fernet key lives in the environment, never in this table, so a database
    dump — including the nightly GCS backup — contains no usable credential.
    """

    kind = models.CharField(max_length=32, choices=SecretKind.choices)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.CASCADE, related_name="secrets",
    )
    ciphertext = models.BinaryField()
    last4 = models.CharField(max_length=4, blank=True, default="")
    rotated_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta(TenantScopedModel.Meta):
        db_table = "tenant_secret"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "kind", "user"], name="tenant_secret_unique_per_user"
            ),
            # U(tenant, kind, user) does NOT enforce one Anthropic key per
            # tenant: Postgres treats NULLs as distinct, so unlimited rows with
            # user IS NULL collide with nothing (data model review item 5).
            models.UniqueConstraint(
                fields=["tenant", "kind"],
                condition=models.Q(user__isnull=True),
                name="tenant_secret_one_per_tenant",
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} (...{self.last4})"


class AuditEvent(TenantScopedModel):
    """One table, not per-model history (assumption D3)."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="audit_events",
    )
    verb = models.CharField(max_length=64, db_index=True)
    # FR-3.42 — set when written while someone acts as another user: the real
    # person, and who they were acting as. Stamped at save time.
    acting_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="+")
    acted_as_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name="+")
    target_type = models.CharField(max_length=64, blank=True, default="")
    target_id = models.UUIDField(null=True, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "audit_event"
        indexes = [
            models.Index(fields=["tenant", "target_type", "target_id"]),
            models.Index(fields=["tenant", "-created_at"]),
        ]


class StoredFile(TenantScopedModel):
    """GCS-backed blobs: recording audio, flyers, PDFs, inbound attachments."""

    bucket = models.CharField(max_length=200)
    object_key = models.CharField(max_length=500)
    content_type = models.CharField(max_length=100, blank=True, default="")
    byte_size = models.BigIntegerField(default=0)
    purpose = models.CharField(max_length=40)
    delete_after = models.DateTimeField(null=True, blank=True)  # FR-2.19

    class Meta(TenantScopedModel.Meta):
        db_table = "stored_file"


class AiCall(TenantScopedModel):
    """Every Claude call (assumption E1.7, FR-4.18c).

    Cost per module is a number you can look up, not a guess. FF-only to read
    (FR-0.9) — spend is financial.
    """

    purpose = models.CharField(max_length=40)
    target_type = models.CharField(max_length=64, blank=True, default="")
    target_id = models.UUIDField(null=True, blank=True)
    model = models.CharField(max_length=64)
    input_tokens = models.IntegerField(default=0)
    output_tokens = models.IntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    trigger = models.CharField(max_length=16, default="button")  # FR-4.18a
    succeeded = models.BooleanField(default=True)
    error = models.TextField(blank=True, default="")
    # Server-side tool use, when a call had tools (session prep searches the
    # web). **`cost_usd` is the token cost only**: Anthropic bills a web search
    # per request on top, so the count is recorded rather than folded into a
    # number that would then be wrong in a direction that flatters us.
    web_searches = models.IntegerField(default=0)
    #: Made by the worker with nobody asking (owner, 2026-09-29): counted
    #: against the tenant's daily cap. `db_default`s so a worker still on the
    #: previous code can insert.
    unattended = models.BooleanField(default=False, db_default=False)
    #: sha256 of what was asked, so "the same input failed twice" is exact:
    #: this week's digest for a contact is not last week's.
    input_hash = models.CharField(max_length=64, blank=True, default="", db_default="")

    class Meta(TenantScopedModel.Meta):
        db_table = "ai_call"
        # The daily-cap sum runs before every unattended call.
        indexes = [models.Index(fields=["tenant", "unattended", "created_at"],
                                name="ai_call_unattended_day")]
