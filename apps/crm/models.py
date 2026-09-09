"""Company only, in Phase 0.5.

`02_data_model.md` §11 fixes the migration order as
tenant -> user/membership -> company (no primary_contact) -> contact ->
add company.primary_contact. Membership and ClientAssignment both point at
Company, so Company must exist in the foundation phase; `primary_contact` and
the rest of Module 1 arrive in Phase 1.
"""

from __future__ import annotations

from django.db import models

from apps.tenancy.models import TenantScopedModel


class Company(TenantScopedModel):
    name = models.CharField(max_length=200, db_index=True)
    industry = models.CharField(max_length=120, blank=True, default="")
    address = models.JSONField(null=True, blank=True)

    # FR-1.6a: derived from a contact reaching stage `client`; cleared only by
    # hand. The derivation runs one way and is never inferred backwards.
    is_client_company = models.BooleanField(default=False)

    # FR-3.33f: the limit. Usage is COUNT(live memberships) — never stored, so
    # it cannot drift (data model §12.3).
    seat_count = models.PositiveIntegerField(null=True, blank=True)

    # FR-3.24: AI prose on/off for this client's digests.
    digest_ai_prose = models.BooleanField(default=True)

    deleted_at = models.DateTimeField(null=True, blank=True)  # D2

    class Meta(TenantScopedModel.Meta):
        db_table = "company"
        verbose_name_plural = "companies"

    def __str__(self):
        return self.name

    @property
    def seats_in_use(self):
        return self.memberships.filter(revoked_at__isnull=True).count()

    @property
    def seats_available(self):
        if self.seat_count is None:
            return 0
        return max(self.seat_count - self.seats_in_use, 0)
