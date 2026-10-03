"""The platform layer (P2, owner 2026-10-02): what sits above the practices.

Two tables, both scoped to a practice like every other domain table:

- `AgreementAcceptance` — a practice owner accepting a version of the beta
  agreement, with the hash of the exact text they were shown.
- `Feedback` — the one thing that crosses the practice boundary, and only
  because a person wrote it and sent it. The platform owner reads it through
  `apps/platform/feedback.py`; nothing else from a practice reaches the
  platform owner but the numbers in `apps/platform/stats.py`.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.tenancy.models import TenantScopedModel


class AgreementAcceptance(TenantScopedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="agreement_acceptances")
    version = models.CharField(max_length=32)
    #: SHA-256 of the exact text shown, so "which words did they accept" has
    #: one answer even after the file changes.
    text_sha256 = models.CharField(max_length=64)
    accepted_at = models.DateTimeField(default=timezone.now)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "agreement_acceptance"
        constraints = [
            models.UniqueConstraint(fields=["user", "version"],
                                    name="agreement_acceptance_once_per_version"),
        ]


class Feedback(TenantScopedModel):
    class Status(models.TextChoices):
        NEW = "new", "New"
        SEEN = "seen", "Seen"
        CLOSED = "closed", "Closed"

    #: The practice's display name when it was sent: what the platform owner
    #: reads, so they never need to look the practice up.
    practice_name = models.CharField(max_length=200)
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name="+")
    role = models.CharField(max_length=3)
    doing = models.TextField()
    happened = models.TextField()
    expected = models.TextField()
    page_url = models.CharField(max_length=500)
    screenshot = models.ForeignKey("tenancy.StoredFile", null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.NEW)

    class Meta(TenantScopedModel.Meta):
        db_table = "feedback"
        ordering = ["-created_at"]
