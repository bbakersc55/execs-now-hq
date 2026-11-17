"""Test payments, once the card processor is back in live mode (2026-11-16).

While the processor is in its own Test Mode (`gateway_mode`), every payment,
refund and saved card made is a test: no money moved. Once it reads live
again, the owner sees "N test payments" and one action, **Clear test
payments**, which:

- removes each test payment from its invoice (kept, marked removed, with the
  reason), and its test refunds with it; there is nothing in the books to
  take out, since a test payment never went in;
- reopens each invoice they paid, or voids it, as the owner chose, with no
  default (an invoice that also has real money on it is reopened, never
  voided; one dated after its automatic billing ended is voided either way,
  2026-11-17);
- deletes each test card from the vault (and so turns its auto-pay off).

The platform owner has the same on Practices for the platform account:
subscription charges made in Test Mode, and subscription cards saved then.
Clearing reads the processor again first and refuses while it still says
Test Mode, or cannot say.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.billing import gateway as gw
from apps.billing import gateway_mode
from apps.billing.models import (
    CardRefund, ClientInvoice, ClientPayment, ClientPaymentMethod, PracticeInvoice,
    PracticeSubscription,
)

log = logging.getLogger(__name__)
CHOICES = ("reopen", "void")
CLEARED = ("A test payment, made while the card processor was in Test Mode: no money moved. "
           "Cleared.")
STILL_TEST = ("The card processor still says it is in Test Mode. Turn Test Mode off there "
              "first; nothing was cleared.")
UNREADABLE = ("Couldn't read whether the card processor is in Test Mode, so nothing was "
              "cleared. Try again in a minute.")


class ClearRefused(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def _choice(invoices) -> str:
    if invoices not in CHOICES:
        raise ClearRefused("Choose whether the invoices are reopened or voided.", 400)
    return invoices


def _live_now(state) -> None:
    if state is True:
        raise ClearRefused(STILL_TEST)
    if state is None:
        raise ClearRefused(UNREADABLE, 503)


# ------------------------------------------------------------ a practice

def _test_payments(tenant):
    return ClientPayment.all_objects.filter(tenant=tenant, is_test=True,
                                            removed_at__isnull=True)


def _test_cards(tenant):
    return ClientPaymentMethod.all_objects.filter(tenant=tenant, is_test=True,
                                                  removed_at__isnull=True)


def practice_summary(tenant) -> dict:
    payments = _test_payments(tenant)
    count, cards = payments.count(), _test_cards(tenant).count()
    mode = gateway_mode.last_for_practice(tenant)
    return {"payments": count, "cards": cards,
            "amount_cents": payments.aggregate(t=Sum("amount_cents"))["t"] or 0,
            # Offered only once the processor last read live (2026-11-16).
            "can_clear": mode is False and bool(count or cards)}


def clear_practice(tenant, *, actor, invoices: str) -> dict:
    """The practice owner's "Clear test payments"."""
    from apps.billing import autopay, services

    invoices = _choice(invoices)
    _live_now(gateway_mode.for_practice(tenant))
    now = timezone.now()
    reopened = voided = cleared = 0
    with transaction.atomic():
        touched = set()
        for payment in _test_payments(tenant).select_for_update():
            payment.removed_at, payment.removed_by = now, actor
            payment.remove_reason = CLEARED
            payment.save(update_fields=["removed_at", "removed_by", "remove_reason",
                                        "updated_at"])
            CardRefund.all_objects.filter(payment=payment, cleared_at__isnull=True).update(
                cleared_at=now, updated_at=now)
            touched.add(payment.invoice_id)
            cleared += 1
        for invoice in ClientInvoice.all_objects.select_for_update().filter(pk__in=touched):
            services._recount(invoice)
            ended = after_its_end(invoice)
            services.audit(invoice, "test_payments_cleared", actor, choice=invoices,
                           **({"after_end": ended.isoformat()} if ended else {}))
            if invoice.paid_cents == 0 and invoice.status != ClientInvoice.Status.VOID \
                    and (invoices == "void" or ended):
                services.void(invoice, actor=actor, reason=_void_reason(ended))
                voided += 1
            elif invoice.status != ClientInvoice.Status.VOID:
                reopened += 1
    cards = 0
    for card in list(_test_cards(tenant).select_related("client_company")):
        try:
            # Removed and deleted from the vault, its auto-pay turned off.
            autopay.remove_card(card.client_company, user=actor)
            cards += 1
        except autopay.AutopayRefused as exc:
            log.warning("test card %s not cleared (%s)", card.pk, exc)
    _audit_tenant(tenant, actor, payments=cleared, reopened=reopened, voided=voided,
                  cards=cards)
    return {"payments": cleared, "reopened": reopened, "voided": voided, "cards": cards,
            "summary": practice_summary(tenant)}


def after_its_end(invoice):
    """The end of the automatic billing an invoice is dated after, or None.

    "Stop now" and an earlier end void the invoices made for later dates,
    but not one a test payment made look paid (2026-11-17, INV-0005): once
    that payment is cleared it is voided whichever choice was sent, since
    nothing will ever charge it."""
    from apps.billing.models import BillingAgreement

    if not invoice.billing_agreement_id or invoice.billing_date is None:
        return None
    ends_on = (BillingAgreement.all_objects.filter(pk=invoice.billing_agreement_id)
               .values_list("ends_on", flat=True).first())
    return ends_on if ends_on is not None and invoice.billing_date > ends_on else None


def _void_reason(ended) -> str:
    from apps.billing import recurring

    if ended is None:
        return "Test payments cleared: no money moved."
    return ("Test payments cleared: no money moved. Automatic billing ended "
            f"{recurring._date(ended)}, before this billing date, so it is not billed.")


def _audit_tenant(tenant, actor, **payload) -> None:
    from apps.tenancy.models import AuditEvent

    AuditEvent.all_objects.create(tenant=tenant, actor=actor,
                                  verb="billing.test_payments_cleared", target_type="tenant",
                                  target_id=tenant.pk, payload=payload)


# ------------------------------------------------------------ the platform

def _test_charges():
    return PracticeInvoice.all_objects.filter(is_test=True, amount_paid_cents__gt=0)


def _test_subscription_cards():
    return PracticeSubscription.all_objects.filter(card_is_test=True).exclude(nmi_vault_id="")


def platform_summary() -> dict:
    charges = _test_charges()
    count, cards = charges.count(), _test_subscription_cards().count()
    mode = gateway_mode.last_for_platform()
    return {"payments": count, "cards": cards,
            "amount_cents": charges.aggregate(t=Sum("amount_paid_cents"))["t"] or 0,
            "can_clear": mode is False and bool(count or cards)}


def clear_platform(*, actor, invoices: str) -> dict:
    """The platform owner's "Clear test payments" on Practices: subscription
    charges made in Test Mode reopened (charged again by the next daily run
    once a real card is on file) or voided; test cards deleted from the
    platform's vault."""
    invoices = _choice(invoices)
    _live_now(gateway_mode.for_platform())
    now = timezone.now()
    reopened = voided = 0
    with transaction.atomic():
        for invoice in _test_charges().select_for_update():
            CardRefund.all_objects.filter(practice_invoice=invoice,
                                          cleared_at__isnull=True).update(
                cleared_at=now, updated_at=now)
            invoice.amount_paid_cents, invoice.paid_at, invoice.is_test = 0, None, False
            invoice.charge_state, invoice.last_charge_text = "", ""
            if invoices == "void":
                invoice.status = PracticeInvoice.Status.VOID
                voided += 1
            else:
                invoice.status, invoice.charge_tries = PracticeInvoice.Status.OPEN, 0
                reopened += 1
            invoice.save()
            _audit_tenant(invoice.tenant, actor, subscription_invoice=invoice.number,
                          choice=invoices)
    cards = 0
    for row in list(_test_subscription_cards()):
        try:
            gw.gateway().vault_delete(gw.platform_account(), row.nmi_vault_id)
        except gw.GatewayError as exc:
            log.warning("test subscription card %s not deleted from the vault (%s)", row.pk,
                        type(exc).__name__)
        S = PracticeSubscription.Status
        PracticeSubscription.all_objects.filter(pk=row.pk).update(
            nmi_vault_id="", card_environment="", card_brand="", card_last4="",
            card_expires="", card_is_test=False, first_charge_on=None,
            status=S.NEEDS_CARD if row.status in (S.ACTIVE, S.PAST_DUE) else row.status,
            updated_at=now)
        cards += 1
    return {"payments": reopened + voided, "reopened": reopened, "voided": voided,
            "cards": cards, "summary": platform_summary()}
