"""Scheduled work for invoicing: the recurring drafts, and card payments
whose answer from NMI was lost."""

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


@unattended_job("billing.resolve_card_payments")
def resolve_card_payments(tenant_id: str) -> int:
    """Looks up, by our reference, each card payment NMI did not answer
    (P4 part 2). It charges nothing: it only reads what NMI did."""
    from apps.billing import card_payments
    from apps.tenancy.models import Tenant

    with tenant_context(tenant_id):
        tenant = Tenant.objects.get(pk=tenant_id)
        return card_payments.resolve_unknown(tenant)
