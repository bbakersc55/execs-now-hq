"""Scheduled work for Module 1.

Plain module-level functions taking primitives (assumption A1), each opening an
explicit tenant_context because a background job has no request.
"""

from __future__ import annotations

from apps.tenancy.context import tenant_context


def draft_referral_touches(tenant_id: str) -> int:
    """FR-1.21 — drafts due touches 3 days early into the Outbox.

    Never sends. The automation buys drafting time, not send authority.
    """
    from apps.crm.services.referral import draft_due_touches
    from apps.tenancy.models import Tenant

    with tenant_context(tenant_id):
        tenant = Tenant.objects.get(pk=tenant_id)
        return len(draft_due_touches(tenant))


def expire_outbox(tenant_id: str) -> int:
    """FR-1.18 — an unapproved item past its send-by EXPIRES. It does not send."""
    from apps.crm.services.outbox import expire_due
    from apps.tenancy.models import Tenant

    with tenant_context(tenant_id):
        tenant = Tenant.objects.get(pk=tenant_id)
        return expire_due(tenant)


def reindex_search(tenant_id: str) -> int:
    """FR-1.33 — refresh contact search vectors."""
    from apps.crm.services.search import reindex_tenant
    from apps.tenancy.models import Tenant

    with tenant_context(tenant_id):
        tenant = Tenant.objects.get(pk=tenant_id)
        reindex_tenant(tenant)
        from apps.crm.models import Contact

        return Contact.objects.count()


def poll_inbound(tenant_id: str) -> dict:
    """Collect replies on the threads the app started (FR-6.5).

    Every 15 minutes. It does nothing at all unless the practice has granted
    the read scope, which is the normal state until somebody turns Tier 2 on —
    and "not connected" is not an error.
    """
    from apps.crm.services import inbound_poll
    from apps.tenancy.models import Tenant

    with tenant_context(tenant_id):
        tenant = Tenant.objects.get(pk=tenant_id)
        try:
            return inbound_poll.poll(tenant)
        except inbound_poll.NotConnected as exc:
            return {"connected": False, "detail": str(exc)}
