"""Foundation tables (data model §1).

Conventions applied to every domain table, per `02_data_model.md` §0:
UUID PK, tenant FK with PROTECT, created_at/updated_at, tenant-scoped uniques.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from .context import get_current_tenant_id
from .managers import AllTenantsManager, TenantManager


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
                    {field.name: f"{field.name} belongs to a different tenant."}
                )


class Tenant(UUIDModel):
    """The practice. One row in Beta. The only table with no tenant_id."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
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
    FF = "FF", "Founder fractional"
    CF = "CF", "Contractor/employee fractional"
    VA = "VA", "Virtual assistant"
    FCC = "FCC", "Founder of client company"
    ECC = "ECC", "Employee of client company"


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
    # `contact` (FK -> crm.Contact, assumption F1: every human is a Contact and a
    # login attaches to it) is added in Phase 1. Data model §11 fixes the
    # migration order as company -> contact -> the FKs that point at contact,
    # and Contact is a Module 1 table.
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

    class Meta(TenantScopedModel.Meta):
        db_table = "ai_call"
