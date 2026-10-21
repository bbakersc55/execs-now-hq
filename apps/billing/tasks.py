"""Scheduled work for invoicing: the recurring drafts, card payments whose
answer from NMI was lost, and auto-pay."""

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


@unattended_job("billing.run_autopay")
def run_autopay(tenant_id: str) -> dict:
    """Charges the card on file for each invoice due today under a standing
    auto-pay consent, tries a failed one once more on a later day, and tells
    clients of cards about to expire (P4 part 4). Safe to run twice."""
    from apps.billing import autopay
    from apps.tenancy.models import Tenant

    with tenant_context(tenant_id):
        tenant = Tenant.objects.get(pk=tenant_id)
        return autopay.run(tenant)


@unattended_job("billing.charge_subscription")
def charge_subscription(tenant_id: str) -> dict:
    """The practice's subscription (P4 part 5): its month's invoice and one
    charge on the platform's vault from the 1st, and any lost answer looked
    up. Nothing for the platform owner's own practice."""
    from apps.billing import subscriptions
    from apps.tenancy.models import Tenant

    with tenant_context(tenant_id):
        tenant = Tenant.objects.get(pk=tenant_id)
        return subscriptions.run(tenant)
