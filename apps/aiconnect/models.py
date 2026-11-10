"""AI apps connected over MCP (P7, 2026-11-10; docs/p7_mcp.md).

A practice user signs their own AI app (Claude, ChatGPT) in through the app's
OAuth 2.1 authorization server. What they grant is a **connection**: one user,
one practice, one role, one AI app. Every token belongs to a connection, and
revoking the connection ends every token at once.

Tokens and codes are stored as SHA-256 digests only: a database copy cannot
be replayed.
"""

from __future__ import annotations

import hashlib

from django.conf import settings
from django.db import models

from apps.tenancy.models import TenantScopedModel, UUIDModel


def digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


class AiAppClient(UUIDModel):
    """An AI app as it registered itself (RFC 7591 dynamic registration).

    Platform-level, not a practice's: Claude registers once and is then
    connected by many practices' users. A public client: no secret, PKCE only.
    """

    client_id = models.CharField(max_length=64, unique=True)
    client_name = models.CharField(max_length=200, blank=True, default="")
    client_uri = models.URLField(max_length=500, blank=True, default="")
    redirect_uris = models.JSONField(default=list)
    #: What it sent, kept for support; nothing reads it back.
    registration = models.JSONField(default=dict)

    class Meta:
        db_table = "ai_app_client"

    def __str__(self):
        return self.client_name or self.client_id

    @property
    def display_name(self) -> str:
        return (self.client_name or "An AI app")[:200]


class AiAppConnection(TenantScopedModel):
    """One user's AI app connected to one practice, with the role it acts as.

    Shown on Profile ("Connected AI apps") and in Settings → AI; Revoke sets
    `revoked_at`, and every token of it stops working."""

    client = models.ForeignKey(AiAppClient, on_delete=models.PROTECT, related_name="connections")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="ai_app_connections")
    membership = models.ForeignKey("tenancy.Membership", on_delete=models.CASCADE,
                                   related_name="ai_app_connections")
    #: The role the grant covers, as it was when granted (a code, FF/CF/VA).
    role = models.CharField(max_length=8)
    app_name = models.CharField(max_length=200)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "ai_app_connection"
        ordering = ["-created_at"]

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


class AiAppCode(TenantScopedModel):
    """An authorization code: single use, ten minutes, PKCE S256."""

    connection = models.ForeignKey(AiAppConnection, on_delete=models.CASCADE, related_name="codes")
    code_hash = models.CharField(max_length=64, unique=True)
    redirect_uri = models.CharField(max_length=500)
    code_challenge = models.CharField(max_length=128)
    scope = models.CharField(max_length=200, blank=True, default="")
    resource = models.CharField(max_length=500, blank=True, default="")
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "ai_app_code"


class AiAppToken(TenantScopedModel):
    """An access token (an hour) or a refresh token (thirty days, used once:
    each use issues a new pair, and a second use of a spent one revokes the
    whole connection, as a stolen copy would)."""

    class Kind(models.TextChoices):
        ACCESS = "access", "Access"
        REFRESH = "refresh", "Refresh"

    connection = models.ForeignKey(AiAppConnection, on_delete=models.CASCADE, related_name="tokens")
    kind = models.CharField(max_length=8, choices=Kind.choices)
    token_hash = models.CharField(max_length=64, unique=True)
    scope = models.CharField(max_length=200, blank=True, default="")
    resource = models.CharField(max_length=500, blank=True, default="")
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "ai_app_token"
        indexes = [models.Index(fields=["connection", "kind"])]


class ModelTier(UUIDModel):
    """The three model tiers every AI action runs on (P7, 2026-11-10):
    Fast, Standard and Deep, each the model id the platform owner names here,
    with its price. Platform-wide, not a practice's: changed in the Practices
    area without a code change. A practice chooses a tier per action
    (`tenancy.AiActionSetting`); `apps.tenancy.ai_actions` resolves it. Kept
    here, not in apps/platform, which names nothing from a practice's models."""

    class Code(models.TextChoices):
        FAST = "fast", "Fast"
        STANDARD = "standard", "Standard"
        DEEP = "deep", "Deep"

    code = models.CharField(max_length=12, choices=Code.choices, unique=True)
    model = models.CharField(max_length=80)
    #: USD per million tokens, for the price shown before a click and the
    #: cost recorded after it.
    input_usd_per_mtok = models.DecimalField(max_digits=8, decimal_places=4)
    output_usd_per_mtok = models.DecimalField(max_digits=8, decimal_places=4)
    #: Whether the API's server-side refusal fallback is asked for. Off for a
    #: model that has none (Haiku).
    server_fallback = models.BooleanField(default=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")

    class Meta:
        db_table = "model_tier"

    def __str__(self):
        return f"{self.get_code_display()}: {self.model}"
