"""Scheduled work for invoicing. One job: the recurring drafts."""

from __future__ import annotations

from apps.tenancy.claude import unattended_job
from apps.tenancy.context import tenant_context


# The worker's own, like every scheduled job. It makes no Claude call.
@unattended_job("billing.run_invoice_schedules")
def run_invoice_schedules(tenant_id: str) -> int:
    """Writes a draft for each schedule whose day has come. It numbers nothing
    and sends nothing: a person makes each draft ready
    (`docs/p4a_client_invoicing.md` §3)."""
    from apps.billing import services
    from apps.tenancy.models import Tenant

    with tenant_context(tenant_id):
        tenant = Tenant.objects.get(pk=tenant_id)
        return len(services.run_schedules(tenant))
