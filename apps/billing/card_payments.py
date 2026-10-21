"""Paying an invoice by card (P4 parts 2 and 3, `docs/p4_billing.md` §3.4).

A client owner or a client team member presses Pay on a sent or partly paid
invoice in the portal, or anyone with the invoice's signed pay link opens it
(`pay_links`; a contact invoice is paid only this way). NMI's Payment Component, loaded with the practice's public key,
turns the card into a one-time token in their browser; only the token comes
here. Then, in order:

1. **The attempt is written first**, with the invoice locked: the full
   balance (§10, choice 4), and only if no other attempt on that invoice is
   pending or unknown. The database holds that rule too.
2. **One sale, on the practice's own key**, carrying the attempt's id as our
   reference. Never the platform's account (D10), and never retried.
3. **NMI's answer finishes the attempt.** Approved: a `ClientPayment` through
   `services.record_payment`, so the balance, the status and the books move
   exactly as for a payment recorded by hand; then the receipt to whoever
   paid and the notice to the practice owner. Declined: NMI's text is kept.
   Refused as a duplicate: a plain message, nothing charged, no second try.
   No answer: the attempt is "unknown" and `resolve_unknown` looks the sale
   up by our reference until it knows.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.html import escape

from apps.billing import gateway as gw
from apps.billing import money, payment_accounts, services
from apps.billing.models import ClientInvoice, PaymentAttempt

A = PaymentAttempt.Status
log = logging.getLogger(__name__)

DUPLICATE_MESSAGE = (
    "The card processor refused this as a duplicate of a payment made with the same card "
    "for the same amount a few minutes ago, so nothing was charged this time. Check your "
    "email for a receipt before paying again; if the invoice still shows a balance in a "
    "few minutes, try again then.")
UNKNOWN_MESSAGE = (
    "We did not hear back from the card processor, so we are checking whether the payment "
    "went through. This invoice will show the result within the hour. Please do not pay "
    "again until it does.")
FAILED_MESSAGE = "The payment could not be made, and nothing was charged. Please try again."

#: How long an attempt may stay pending (the process asking NMI died) before
#: the lookup takes it over, and how long the lookup waits for NMI to show a
#: sale before deciding there was none.
PENDING_GRACE = timedelta(minutes=5)
GIVE_UP_AFTER = timedelta(hours=1)


class PaymentRefused(Exception):
    """The payment cannot start. Shown to the client as it is."""

    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def in_flight(invoice) -> PaymentAttempt | None:
    return PaymentAttempt.all_objects.filter(invoice=invoice,
                                             status__in=PaymentAttempt.IN_FLIGHT).first()


def can_pay(invoice, *, via=PaymentAttempt.Via.PORTAL) -> bool:
    """Whether Pay shows: sent or partly paid, something owed, the practice's
    account ready, and no payment already under way. A contact invoice is in
    no portal and has no card on file, so only its link pays it."""
    return (invoice.status in ClientInvoice.OPEN and invoice.balance_cents > 0
            and (via == PaymentAttempt.Via.LINK or invoice.kind != ClientInvoice.Kind.CONTACT)
            and payment_accounts.is_ready(invoice.tenant) and in_flight(invoice) is None)


def is_test_mode(tenant) -> bool:
    row = payment_accounts.PaymentAccount.all_objects.filter(tenant=tenant).first()
    return row is None or row.environment != "live"


def pay_config(invoice, *, via=PaymentAttempt.Via.PORTAL) -> dict:
    """What the card form needs, at runtime: the practice's public key."""
    if not can_pay(invoice, via=via):
        raise PaymentRefused(_why_not(invoice))
    account = payment_accounts.practice_account(invoice.tenant)
    return {"public_key": account.public_key, "test_mode": is_test_mode(invoice.tenant),
            "amount_cents": invoice.balance_cents, "number": invoice.number}


def _why_not(invoice) -> str:
    if in_flight(invoice) is not None:
        return UNKNOWN_MESSAGE if in_flight(invoice).status == A.UNKNOWN else (
            "A payment on this invoice is already under way.")
    if invoice.status == ClientInvoice.Status.PAID or invoice.balance_cents <= 0:
        return f"Invoice {invoice.number} is paid in full."
    if invoice.status == ClientInvoice.Status.VOID:
        return "This invoice was voided and takes no payment."
    return "This invoice cannot be paid online just now."


def start(invoice, *, payer, via=PaymentAttempt.Via.PORTAL) -> PaymentAttempt:
    """The attempt, written before NMI is asked, with the invoice locked."""
    from apps.tenancy.context import get_acting

    if get_acting() is not None:
        # Someone of the practice viewing the portal as this client: their
        # card is not the client's, and nothing is paid on another's behalf.
        raise PaymentRefused("Nothing is paid while acting as someone else.")
    try:
        with transaction.atomic():
            locked = ClientInvoice.all_objects.select_for_update().get(pk=invoice.pk)
            if not can_pay(locked, via=via):
                raise PaymentRefused(_why_not(locked))
            row = payment_accounts.PaymentAccount.all_objects.get(tenant_id=locked.tenant_id)
            return PaymentAttempt.all_objects.create(
                tenant_id=locked.tenant_id, invoice=locked, payer=payer, via=via,
                amount_cents=locked.balance_cents, environment=row.environment)
    except IntegrityError:
        # Another tab got there between the check and the insert.
        raise PaymentRefused("A payment on this invoice is already under way.") from None


def pay(invoice, *, payer, payment_token: str,
        via=PaymentAttempt.Via.PORTAL) -> tuple[PaymentAttempt, str]:
    """The whole payment. Returns the finished (or unknown) attempt and the
    sentence to show the client. `payer` is None by the link."""
    if not isinstance(payment_token, str) or not payment_token.strip():
        raise PaymentRefused("The card details did not come through. Please try again.", 400)
    attempt = start(invoice, payer=payer, via=via)
    return _charge(attempt, payment_token=payment_token)


def charge_on_file(invoice, *, card) -> tuple[PaymentAttempt, str]:
    """Auto-pay (P4 part 4): the company's card on file, for the balance,
    on the practice's own account. The caller has checked the consent; this
    checks the card belongs to the invoice's own company."""
    if card.removed_at is not None or card.client_company_id != invoice.client_company_id \
            or card.tenant_id != invoice.tenant_id:
        raise PaymentRefused("That card is not on file for this invoice's company.")
    attempt = start(invoice, payer=None, via=PaymentAttempt.Via.AUTOPAY)
    attempt.payment_method = card
    attempt.save(update_fields=["payment_method", "updated_at"])
    return _charge(attempt, vault_id=card.vault_id)


def _charge(attempt, **source) -> tuple[PaymentAttempt, str]:
    """One sale for a written attempt, never retried; its answer finishes it."""
    try:
        account = payment_accounts.practice_account(attempt.invoice.tenant)
        txn = gw.gateway().sale(account, amount_cents=attempt.amount_cents,
                                reference=str(attempt.pk), **source)
    except gw.GatewayUnreachable:
        _finish(attempt, A.UNKNOWN, response_text="No answer from NMI.")
        return attempt, UNKNOWN_MESSAGE
    except gw.GatewayRefused as exc:
        _finish(attempt, A.DECLINED, response_code=exc.code, response_text=str(exc))
        return attempt, DUPLICATE_MESSAGE if exc.duplicate else _declined_message(str(exc))
    except (gw.GatewayError, payment_accounts.PaymentAccountError) as exc:
        _finish(attempt, A.FAILED, response_text=str(exc))
        return attempt, FAILED_MESSAGE
    return settle(attempt, txn)


def _declined_message(text: str) -> str:
    text = (text or "").strip().rstrip(".")
    said = f' The card processor said: "{text}".' if text else ""
    return f"The card was declined, and nothing was charged.{said} You can try another card."


def _finish(attempt, status, **fields) -> None:
    for name, value in fields.items():
        setattr(attempt, name, value)
    attempt.status = status
    attempt.finished_at = timezone.now()
    attempt.save()


def settle(attempt, txn: gw.Transaction) -> tuple[PaymentAttempt, str]:
    """Finish an attempt from NMI's transaction: from the sale's own answer,
    or from the lookup. Safe to run twice."""
    if txn.reference and txn.reference != str(attempt.pk):
        # Not this attempt's sale: a subscription's ("sub-…") or another
        # payment's. Told apart by our reference, never by the account (§1.2).
        log.warning("card payment %s: NMI transaction carries another reference; ignored",
                    attempt.pk)
        return attempt, FAILED_MESSAGE
    with transaction.atomic():
        attempt = PaymentAttempt.all_objects.select_for_update().get(pk=attempt.pk)
        if attempt.status == A.APPROVED:
            return attempt, _paid_message(attempt)
        details = dict(nmi_transaction_id=txn.id, response_code=txn.response_code,
                       response_text=txn.response_text, card_type=txn.card_type,
                       last4=txn.last4)
        if not txn.approved:
            _finish(attempt, A.DECLINED, **details)
            return attempt, _declined_message(txn.response_text)
        _finish(attempt, A.APPROVED, **details)
        try:
            with transaction.atomic():
                card = " ".join(p for p in (txn.card_type, f"…{txn.last4}" if txn.last4
                                            else "") if p)
                payment = services.record_payment(
                    attempt.invoice, actor=attempt.payer, amount_cents=attempt.amount_cents,
                    paid_on=timezone.localdate(), method="card",
                    reference=f"Card {card}".strip()[:120], nmi_transaction_id=txn.id,
                    note={PaymentAttempt.Via.LINK: "Paid by the pay link.",
                          PaymentAttempt.Via.AUTOPAY: "Charged by auto-pay to the card on file.",
                          }.get(attempt.via, "Paid in the portal.")
                    + f" NMI transaction {txn.id}.")
            attempt.payment = payment
            attempt.save(update_fields=["payment", "updated_at"])
        except services.BillingError as exc:
            # The money was taken; the invoice would not take it (voided or
            # paid by hand meanwhile). The practice owner sorts it out in NMI.
            attempt.problem = f"Charged, but not recorded on the invoice: {exc}"
            attempt.save(update_fields=["problem", "updated_at"])
        transaction.on_commit(lambda: _tell(attempt.pk))
    return attempt, _paid_message(attempt)


def _paid_message(attempt) -> str:
    return (f"Thank you. {money.dollars(attempt.amount_cents)} was paid on invoice "
            f"{attempt.invoice.number}. A receipt is on its way to you by email.")


# ------------------------------------------------------------- the emails

def _tell(attempt_id) -> None:
    """The receipt to whoever paid, and the notice to the practice owner.
    Fixed wording; sent at once (they record what already happened). A mail
    that cannot go out never undoes or hides a payment that went through:
    it is logged, and the payment stands."""
    try:
        _send_receipt_and_notice(attempt_id)
    except Exception as exc:  # noqa: BLE001 — the payment is already recorded
        log.warning("card payment %s: receipt or notice not sent (%s)", attempt_id,
                    type(exc).__name__)


def _send_receipt_and_notice(attempt_id) -> None:
    from apps.crm.models import OutboxMessage
    from apps.crm.services import email_layout, outbox
    from apps.tenancy.context import tenant_context
    from apps.tenancy.models import Membership, Role

    attempt = (PaymentAttempt.all_objects.select_related("invoice", "invoice__tenant",
                                                         "invoice__client_company", "payer")
               .get(pk=attempt_id))
    invoice, tenant = attempt.invoice, attempt.invoice.tenant
    invoice.refresh_from_db()
    practice = services.practice_name(tenant)
    paid = money.dollars(attempt.amount_cents)
    card = " ".join(p for p in (attempt.card_type, f"ending {attempt.last4}"
                                if attempt.last4 else "") if p) or "card"
    thread = services._thread_for(invoice)
    test = " (test mode: no real money moved)" if attempt.environment != "live" else ""

    # By the link or auto-pay no one is signed in: the receipt goes where the
    # invoice went.
    receipt_to = (attempt.payer.email if attempt.payer is not None
                  else invoice.email_to if attempt.via in (PaymentAttempt.Via.LINK,
                                                           PaymentAttempt.Via.AUTOPAY) else "")
    with tenant_context(tenant.pk):
        if receipt_to and not attempt.problem:
            subject = f"Receipt: {paid} paid on invoice {invoice.number}"
            lines = [
                f"Thank you for your payment to {practice}{test}.",
                f"Amount: {paid}\nInvoice: {invoice.number}\nPaid with: {card}\n"
                f"Date: {timezone.localdate():%B %-d, %Y}\nTransaction: "
                f"{attempt.nmi_transaction_id}",
                (f"Still owed on this invoice: {money.dollars(invoice.balance_cents)}."
                 if invoice.balance_cents > 0 else "This invoice is now paid in full."),
            ]
            outbox.create_message(
                tenant=tenant, producer=OutboxMessage.Producer.PAYMENT_RECEIPT,
                to_address=receipt_to, subject=subject, body_text="\n\n".join(lines),
                body_html=email_layout.document(
                    tenant, subject=subject, preheader=lines[0],
                    content_html="".join(f"<p>{escape(l).replace(chr(10), '<br>')}</p>"
                                         for l in lines)),
                thread=thread, source_type="payment_attempt", source_id=attempt.pk,
                force_direct=True)

        who = ((attempt.payer.full_name or attempt.payer.email) if attempt.payer
               else f"{(invoice.bill_to or {}).get('name') or 'The client'}, by the pay link,"
               if attempt.via == PaymentAttempt.Via.LINK
               else "Auto-pay" if attempt.via == PaymentAttempt.Via.AUTOPAY else "A client")
        company = invoice.client_company.name if invoice.client_company_id else ""
        subject = (f"Card payment: {paid} on invoice {invoice.number}"
                   + (f" from {company}" if company else ""))
        lines = [f"{who} paid {paid} by {card} on invoice {invoice.number}"
                 + (f" ({company})" if company else "") + f"{test}.",
                 f"NMI transaction {attempt.nmi_transaction_id}."]
        if attempt.problem:
            lines.append(f"It could not be recorded on the invoice: {attempt.problem}. "
                         "Refund it in NMI, or record it by hand once the invoice can take it.")
        else:
            lines.append("It is recorded on the invoice and in your books. Still owed: "
                         f"{money.dollars(invoice.balance_cents)}.")
        owners = Membership.all_objects.filter(tenant=tenant, role=Role.FF,
                                               revoked_at__isnull=True).select_related("user")
        for owner in owners:
            if not owner.user.email:
                continue
            outbox.create_message(
                tenant=tenant, producer=OutboxMessage.Producer.PAYMENT_NOTICE,
                to_address=owner.user.email, subject=subject, body_text="\n\n".join(lines),
                body_html=email_layout.document(
                    tenant, subject=subject, preheader=lines[0], internal=True,
                    content_html="".join(f"<p>{escape(l)}</p>" for l in lines)),
                thread=thread, source_type="payment_attempt", source_id=attempt.pk,
                force_direct=True)


# ------------------------------------------------- the lookup of unknowns

def resolve_unknown(tenant, *, now=None) -> int:
    """Settle every attempt whose answer was lost: look the sale up at NMI by
    our reference. Found: finished from it. Not found an hour on: no sale was
    made. NMI not answering: left for the next run. Returns how many settled."""
    now = now or timezone.now()
    stuck = PaymentAttempt.all_objects.filter(tenant=tenant).filter(
        status=A.UNKNOWN) | PaymentAttempt.all_objects.filter(
        tenant=tenant, status=A.PENDING, created_at__lt=now - PENDING_GRACE)
    settled = 0
    for attempt in stuck.select_related("invoice").order_by("created_at"):
        try:
            account = payment_accounts.practice_account(tenant)
            txn = gw.gateway().find_by_reference(account, str(attempt.pk))
        except (gw.GatewayError, payment_accounts.PaymentAccountError):
            PaymentAttempt.all_objects.filter(pk=attempt.pk).update(looked_up_at=now)
            continue
        PaymentAttempt.all_objects.filter(pk=attempt.pk).update(looked_up_at=now)
        if txn is not None:
            settle(attempt, txn)
            settled += 1
        elif attempt.created_at < now - GIVE_UP_AFTER:
            with transaction.atomic():
                locked = PaymentAttempt.all_objects.select_for_update().get(pk=attempt.pk)
                if locked.status in PaymentAttempt.IN_FLIGHT:
                    _finish(locked, A.FAILED,
                            response_text="NMI has no sale for it: nothing was charged.")
                    settled += 1
    return settled
