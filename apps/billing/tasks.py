"""Scheduled work for invoicing: the recurring drafts, card payments whose
answer from NMI was lost, and auto-pay."""

from __future__ import annotations

from apps.tenancy.claude import unattended_job
from apps.tenancy.context import tenant_context


def _note(job: str, tenant, *, needs_processor) -> None:
    """2026-11-17: the worker says it is alive and whether it can reach the
    card processor; a job that needs the processor where real calls are off
    is recorded and the platform owner told (once a day). Never raises."""
    from apps.billing import worker_state

    worker_state.report()
    try:
        if needs_processor():
            worker_state.job_refused(job, tenant)
    except Exception:  # noqa: BLE001 — the job itself runs either way
        import logging

        logging.getLogger(__name__).exception("refused-job record for %s failed", job)


def _takes_cards(tenant) -> bool:
    from apps.billing import payment_accounts

    return payment_accounts.is_ready(tenant)


# The worker's own, like every scheduled job. It makes no Claude call.
@unattended_job("billing.run_invoice_schedules")
def run_invoice_schedules(tenant_id: str) -> int:
    """Writes a draft for each schedule whose day has come. It numbers nothing
    and sends nothing: a person makes each draft ready
    (`docs/p4a_client_invoicing.md` §3). 2026-11-17: also each recurring
    invoice that bills automatically makes, numbers and emails its invoice a
    set number of days before each billing date, with no approval step (the
    client agreed to it), and ends an agreement whose last day has passed."""
    from apps.billing import recurring, services
    from apps.tenancy.models import Tenant

    with tenant_context(tenant_id):
        tenant = Tenant.objects.get(pk=tenant_id)
        _note("billing.run_invoice_schedules", tenant, needs_processor=lambda: False)
        made = len(services.run_schedules(tenant))
        return made + len(recurring.make_due(tenant))


@unattended_job("billing.resolve_card_payments")
def resolve_card_payments(tenant_id: str) -> int:
    """Looks up, by our reference, each card payment NMI did not answer
    (P4 part 2), and each refund or void whose answer was lost (2026-11-16).
    It charges and gives back nothing: it only reads what NMI did."""
    from apps.billing import card_payments, refunds
    from apps.billing.models import CardRefund, PaymentAttempt
    from apps.tenancy.models import Tenant

    with tenant_context(tenant_id):
        tenant = Tenant.objects.get(pk=tenant_id)
        _note("billing.resolve_card_payments", tenant, needs_processor=lambda: (
            PaymentAttempt.all_objects.filter(
                tenant=tenant, status__in=PaymentAttempt.IN_FLIGHT).exists()
            or CardRefund.all_objects.filter(
                tenant=tenant, status__in=("pending", "unknown")).exists()))
        return card_payments.resolve_unknown(tenant) + refunds.resolve_unknown(tenant)


@unattended_job("billing.run_autopay")
def run_autopay(tenant_id: str) -> dict:
    """Charges the card on file for each invoice due today under a standing
    auto-pay consent, tries a failed one once more on a later day, and tells
    clients of cards about to expire (P4 part 4). 2026-11-17: also charges
    each invoice billed automatically on its billing date, under the
    client's agreement. Safe to run twice."""
    from apps.billing import autopay, recurring
    from apps.tenancy.models import Tenant

    with tenant_context(tenant_id):
        tenant = Tenant.objects.get(pk=tenant_id)
        _note("billing.run_autopay", tenant, needs_processor=lambda: _takes_cards(tenant))
        counts = autopay.run(tenant)
        counts["billed"] = recurring.charge_due(tenant)
        return counts


@unattended_job("billing.charge_subscription")
def charge_subscription(tenant_id: str) -> dict:
    """The practice's subscription (P4 part 5): its month's invoice and one
    charge on the platform's vault from the 1st, and any lost answer looked
    up. Nothing for the platform owner's own practice."""
    from apps.billing import subscriptions
    from apps.tenancy.models import Tenant

    with tenant_context(tenant_id):
        tenant = Tenant.objects.get(pk=tenant_id)
        _note("billing.charge_subscription", tenant, needs_processor=lambda: (
            not subscriptions.is_owners_practice(tenant)
            and bool(subscriptions.subscription_for(tenant).nmi_vault_id)))
        return subscriptions.run(tenant)


@unattended_job("billing.read_back_nmi")
def read_back_nmi(tenant_id: str) -> dict:
    """P4 §4: the last week of the practice's NMI account, read once a day.
    Refunds, voids and chargebacks made in NMI's portal are recorded against
    their payment; anything unmatched is flagged for the practice owner. It
    charges nothing and changes no invoice's money."""
    from apps.billing import readback
    from apps.tenancy.models import Tenant

    with tenant_context(tenant_id):
        tenant = Tenant.objects.get(pk=tenant_id)
        from apps.billing import subscriptions as subs

        _note("billing.read_back_nmi", tenant, needs_processor=lambda: (
            _takes_cards(tenant) or subs.is_owners_practice(tenant)))
        counts = readback.read_back(tenant)
        # The platform's own account, once a day: on the platform owner's
        # practice's run (owner, 2026-10-26).
        from apps.billing import subscriptions

        if subscriptions.is_owners_practice(tenant):
            counts["platform"] = readback.read_back_platform()
        return counts
