"""Fail-closed tenant scoping (assumption B1).

The important line in this file is the `raise` in `get_queryset`. Returning
every row when no tenant is bound would turn a forgotten filter into a silent
cross-tenant leak; raising turns it into a red test.
"""

from __future__ import annotations

from django.db import models

from .context import get_current_tenant_id, require_current_tenant_id


class TenantQuerySet(models.QuerySet):
    def for_tenant(self, tenant):
        tenant_id = getattr(tenant, "pk", tenant)
        return self.filter(tenant_id=tenant_id)


class TenantManager(models.Manager.from_queryset(TenantQuerySet)):
    """Default manager on every tenant-scoped model.

    Raises `TenantContextMissing` when no tenant is bound. That is deliberate
    and is the entire safety property — do not "fix" it by returning none or
    returning all.
    """

    def get_queryset(self):
        tenant_id = require_current_tenant_id()
        return super().get_queryset().filter(tenant_id=tenant_id)


class AllTenantsManager(models.Manager.from_queryset(TenantQuerySet)):
    """Unscoped access — the explicit, greppable escape hatch.

    Legitimate uses: migrations, management commands, the backup script, and
    Django's own related-object traversal (`Meta.base_manager_name`). Every
    other use is expected to be justified in review.
    """

    def get_queryset(self):
        return super().get_queryset()


class ClientCompanyScopedManager(TenantManager):
    """Second scope layer for client-facing querysets (FR-0.2).

    Tenant isolation and client-company isolation are separate mechanisms on
    purpose, so a bug in one does not defeat the other.
    """

    def visible_to_client(self, client_company_id=None):
        from .context import get_current_client_company_id

        company_id = client_company_id or get_current_client_company_id()
        if company_id is None:
            raise ValueError(
                "No client company bound. A client-facing queryset must be "
                "scoped by company as well as by tenant (FR-0.2)."
            )
        return self.get_queryset().filter(client_company_id=company_id)


def current_tenant_id_or_none():
    return get_current_tenant_id()
