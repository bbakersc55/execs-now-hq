"""Giving money back on a card payment the app took (2026-11-16,
`docs/p4_billing.md` §11).

**Who.** The practice owner, on a client's card payment (the pay link, the
portal's Pay, auto-pay), on the practice's own account. The platform owner,
on a practice's subscription charge, on the platform's account.

**A void or a refund.** The card processor is asked for the sale's state
first. A sale not yet settled, given back in full and never refunded before,
is **voided**: nothing reaches the payer's statement. Anything else is
**refunded**, in full or in part. Never more than was paid.

**One at a time, recorded before the call.** The refund row is written with
the payment locked, so two presses never give back twice (the database holds
it too: one in flight per payment). One call, never retried. A lost answer is
"unknown" and the ten-minute lookup (`resolve_unknown`) finds what the
processor did, by our reference on the sale.

**Once done:** a client payment's invoice is reopened by that amount (and
voided, if that was chosen on a full refund); the books are reversed, a void
by taking the payment's entry out and a refund by an entry of its own on its
own date; the payer gets a receipt and the owner a notice. A test payment's
refund (Test Mode, `gateway_mode`) touches no books.

**From the processor's portal.** One made there is flagged by the morning
read-back; "Record this refund" (`record_event`) does the same bookkeeping
without calling the processor and without emailing anyone.

**While card payments are paused** a refund still goes: the pause stops money
coming in, not going back. With real calls off in production nothing does.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.html import escape

from apps.billing import gateway as gw
from apps.billing import gateway_mode, money, payment_accounts, services
from apps.billing.models import (
    CardRefund, ClientInvoice, ClientPayment, NmiEvent, PaymentAttempt, PracticeInvoice,
)

log = logging.getLogger(__name__)
R = CardRefund

#: How long a refund may stay pending (the process asking died) before the
#: lookup takes it over, and how long it waits for the processor to show one.
PENDING_GRACE = timedelta(minutes=5)
GIVE_UP_AFTER = timedelta(hours=1)

UNKNOWN_MESSAGE = ("We did not hear back from the card processor, so we are checking "
                   "whether it went through. This page will show the result within the hour. "
                   "Please do not try again until it does.")
REAL_IN_TEST_MODE = ("The card processor is in Test Mode, so giving this payment back now "
                     "would move no money. Turn Test Mode off at the processor, press Test "
                     "connection, then try again.")
TEST_IN_LIVE_MODE = ("This was a test payment: no money moved, so there is nothing to give "
                     "back. Use Clear test payments instead.")


class RefundRefused(Exception):
    """Nothing was given back. Shown to the owner as it is."""

    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


# ------------------------------------------------------------- reading

def _given(qs) -> int:
    return qs.filter(status__in=R.COUNTED, cleared_at__isnull=True).aggregate(
        total=Sum("amount_cents"))["total"] or 0


def is_card_payment(payment) -> bool:
    return payment.method == ClientPayment.Method.CARD and bool(payment.nmi_transaction_id)


def refundable_cents(payment) -> int:
    """What may still be given back on a client payment."""
    return max(payment.amount_cents - _given(R.all_objects.filter(payment=payment)), 0)


def in_flight(**where) -> CardRefund | None:
    return R.all_objects.filter(status__in=R.IN_FLIGHT, **where).first()


def payment_options(payment) -> dict:
    """For the invoice page: whether "Refund or cancel this payment" shows,
    how much is left, and whether "and void the invoice" can be offered (a
    full refund that leaves nothing paid on the invoice)."""
    invoice = payment.invoice
    left = refundable_cents(payment) if is_card_payment(payment) else 0
    possible = (is_card_payment(payment) and payment.removed_at is None and left > 0
                and invoice.status != ClientInvoice.Status.VOID
                and in_flight(payment=payment) is None)
    return {"can_refund": possible, "refundable_cents": left,
            "can_void_invoice": possible and invoice.paid_cents - left == 0}


def subscription_refundable_cents(invoice) -> int:
    """A subscription invoice's: what was charged and is still kept. Done
    refunds have already come off `amount_paid_cents`."""
    pending = R.all_objects.filter(practice_invoice=invoice, status__in=R.IN_FLIGHT,
                                   cleared_at__isnull=True).aggregate(
        total=Sum("amount_cents"))["total"] or 0
    return max(invoice.amount_paid_cents - pending, 0) if invoice.nmi_transaction_id else 0


def subscription_options(invoice) -> dict:
    left = subscription_refundable_cents(invoice)
    possible = (left > 0 and invoice.status != PracticeInvoice.Status.VOID
                and in_flight(practice_invoice=invoice) is None)
    return {"can_refund": possible, "refundable_cents": left,
            "can_void_invoice": possible and invoice.amount_paid_cents - left == 0}


def represent(refund) -> dict:
    by = refund.requested_by
    return {
        "id": str(refund.pk), "kind": refund.kind, "kind_label": refund.get_kind_display(),
        "status": refund.status, "status_label": refund.get_status_display(),
        "amount_cents": refund.amount_cents, "reason": refund.reason,
        "source": refund.source, "source_label": refund.get_source_display(),
        "nmi_transaction_id": refund.nmi_transaction_id,
        "response_text": refund.response_text if refund.status == R.Status.FAILED else "",
        "is_test": refund.is_test, "problem": refund.problem,
        "by": (by.full_name or by.email) if by else "",
        "at": (refund.finished_at or refund.created_at).isoformat(),
        "payment": str(refund.payment_id) if refund.payment_id else None,
        "cleared": refund.cleared_at is not None,
    }


# ------------------------------------------------------ the shared steps

def _check_amount(amount_cents, left) -> int:
    try:
        amount = money.cents(amount_cents, what="The amount")
    except services.BillingError as exc:
        raise RefundRefused(str(exc), 400) from None
    if amount <= 0:
        raise RefundRefused("Give back more than nothing.", 400)
    if amount > left:
        raise RefundRefused(f"That is more than the {money.dollars(left)} that can still be "
                            "given back on it.", 400)
    return amount


def _check_reason(reason) -> str:
    reason = str(reason or "").strip()
    if not reason:
        raise RefundRefused("Say why the money is being given back.", 400)
    return reason[:1000]


def _mode_rule(test_mode, is_test) -> None:
    """A real payment is not given back while the processor is in Test Mode
    (nothing would move), and a test payment only while it is."""
    if test_mode is True and not is_test:
        raise RefundRefused(REAL_IN_TEST_MODE)
    if is_test and test_mode is not True:
        raise RefundRefused(TEST_IN_LIVE_MODE)


def _sale_state(account, transaction_id) -> gw.Transaction:
    try:
        return gw.gateway().get_transaction(account, transaction_id)
    except gw.CardPaymentsPaused:
        raise RefundRefused(gw.PAUSED_MESSAGE, 503) from None
    except gw.GatewayError as exc:
        raise RefundRefused("Couldn't ask the card processor about this payment, so nothing "
                            f"was done. {exc}".strip(), 503) from None


def _call(refund, account) -> tuple[str, gw.Transaction | None, str]:
    """One call to the processor: ("done", txn, ""), ("unknown", None, ""),
    or ("failed", None, what it said). Never retried."""
    try:
        if refund.kind == R.Kind.VOID:
            txn = gw.gateway().void(account, transaction_id=refund.against_transaction_id)
        else:
            txn = gw.gateway().refund(account, transaction_id=refund.against_transaction_id,
                                      amount_cents=refund.amount_cents)
    except gw.CardPaymentsPaused:
        # Real calls off in production: nothing left, so it never happened.
        R.all_objects.filter(pk=refund.pk).delete()
        raise RefundRefused(gw.PAUSED_MESSAGE, 503) from None
    except gw.GatewayUnreachable:
        _finish(refund, R.Status.UNKNOWN, response_text="No answer from the card processor.")
        return "unknown", None, ""
    except gw.GatewayRefused as exc:
        _finish(refund, R.Status.FAILED, response_code=exc.code, response_text=str(exc))
        return "failed", None, str(exc)
    except gw.GatewayError as exc:
        _finish(refund, R.Status.FAILED, response_text=str(exc))
        return "failed", None, str(exc)
    if not txn.approved:
        _finish(refund, R.Status.FAILED, response_code=txn.response_code,
                response_text=txn.response_text)
        return "failed", None, txn.response_text
    return "done", txn, ""


def _finish(refund, status, **fields) -> None:
    for name, value in fields.items():
        setattr(refund, name, value)
    refund.status = status
    if status != R.Status.UNKNOWN:
        refund.finished_at = timezone.now()
    refund.save()


def _failed_message(refund, said) -> str:
    said = (said or "").strip().rstrip(".")
    words = f' It said: "{said}".' if said else ""
    again = (" It has settled since, so try again: it will be refunded instead."
             if refund.kind == R.Kind.VOID and "pending settlement" in said.lower() else "")
    return f"The card processor did not do it, and nothing was given back.{words}{again}"


def _refuse_acting() -> None:
    from apps.tenancy.context import get_acting

    if get_acting() is not None:
        raise RefundRefused("Nothing is given back while acting as someone else.")


# ======================================================= a client payment

def refund_payment(payment, *, amount_cents, reason, void_invoice=False,
                   actor) -> tuple[CardRefund, str]:
    """The practice owner's "Refund or cancel this payment". Returns the
    refund and the sentence to show."""
    _refuse_acting()
    reason = _check_reason(reason)
    invoice = payment.invoice
    if not is_card_payment(payment):
        raise RefundRefused("Only a card payment the app took can be given back here. Remove "
                            "a payment recorded by hand instead.")
    if payment.removed_at is not None:
        raise RefundRefused("That payment was removed.")
    if invoice.status == ClientInvoice.Status.VOID:
        raise RefundRefused("The invoice is void.")
    amount = _check_amount(amount_cents, refundable_cents(payment))
    if void_invoice and (amount != refundable_cents(payment)
                         or invoice.paid_cents - amount != 0):
        raise RefundRefused("The invoice is voided only with a full refund that leaves "
                            "nothing paid on it.", 400)
    try:
        account = payment_accounts.practice_account(invoice.tenant)
    except payment_accounts.PaymentAccountError as exc:
        raise RefundRefused(str(exc)) from None
    _mode_rule(gateway_mode.for_practice(invoice.tenant, account), payment.is_test)
    sale = _sale_state(account, payment.nmi_transaction_id)
    if sale.status == "canceled":
        raise RefundRefused("The card processor shows this payment as cancelled already, so "
                            "nothing was done. The morning read-back lists it to record.")
    attempt = PaymentAttempt.all_objects.filter(payment=payment).first()
    try:
        with transaction.atomic():
            locked = ClientPayment.all_objects.select_for_update().get(pk=payment.pk)
            left = refundable_cents(locked)
            amount = _check_amount(amount, left)
            untouched = not R.all_objects.filter(payment=locked,
                                                 status__in=R.COUNTED).exists()
            void = (sale.status == "pendingsettlement" and untouched
                    and amount == locked.amount_cents)
            refund = R.all_objects.create(
                tenant_id=locked.tenant_id, payment=locked, invoice_id=locked.invoice_id,
                kind=R.Kind.VOID if void else R.Kind.REFUND, amount_cents=amount,
                reason=reason, against_transaction_id=locked.nmi_transaction_id,
                sale_reference=str(attempt.pk) if attempt else "",
                environment=account.environment, is_test=locked.is_test,
                void_invoice=bool(void_invoice), requested_by=actor)
    except IntegrityError:
        raise RefundRefused("Money is already being given back on this payment.") from None
    outcome, txn, said = _call(refund, account)
    if outcome == "unknown":
        return refund, UNKNOWN_MESSAGE
    if outcome == "failed":
        return refund, _failed_message(refund, said)
    settle_client(refund, nmi_transaction_id=txn.id, response_code=txn.response_code,
                  response_text=txn.response_text)
    refund.refresh_from_db()
    return refund, _done_message(refund)


def _done_message(refund) -> str:
    amount = money.dollars(refund.amount_cents)
    test = " (a test: no money moved)" if refund.is_test else ""
    said = (f"Cancelled before it settled{test}: {amount} will not reach the card statement."
            if refund.kind == R.Kind.VOID else f"Refunded {amount}{test}.")
    if refund.problem:
        said += f" {refund.problem}"
    return said


def settle_client(refund, *, nmi_transaction_id, response_code="", response_text="",
                  on_date=None, tell=True) -> CardRefund:
    """Finish a client refund the processor did: the invoice, the books, the
    receipt and the notice. Safe to run twice."""
    from apps.finance import services as finance

    with transaction.atomic():
        refund = R.all_objects.select_for_update().get(pk=refund.pk)
        if refund.status == R.Status.DONE:
            return refund
        _finish(refund, R.Status.DONE, nmi_transaction_id=nmi_transaction_id,
                response_code=response_code, response_text=response_text)
        invoice = ClientInvoice.all_objects.select_for_update().get(pk=refund.invoice_id)
        before = invoice.status
        services._recount(invoice)
        books = ""
        if not refund.is_test:
            books = _to_books(refund, finance, on_date=on_date)
        if refund.void_invoice and invoice.paid_cents == 0 \
                and invoice.status != ClientInvoice.Status.VOID:
            try:
                services.void(invoice, actor=refund.requested_by,
                              reason=f"Refunded in full: {refund.reason}"[:500])
            except services.BillingError as exc:
                refund.problem = (refund.problem + " " if refund.problem else "") + \
                    f"The invoice could not be voided: {exc}"
                refund.save(update_fields=["problem", "updated_at"])
        invoice.refresh_from_db()
        services.audit(invoice, "payment_cancelled" if refund.kind == R.Kind.VOID
                       else "payment_refunded", refund.requested_by,
                       refund=str(refund.pk), payment=str(refund.payment_id),
                       amount_cents=refund.amount_cents, before=before, after=invoice.status,
                       books=books, source=refund.source, reason=refund.reason,
                       **({"test": True} if refund.is_test else {}))
        if tell:
            transaction.on_commit(lambda: _tell_client(refund.pk))
    return refund


def _to_books(refund, finance, *, on_date=None) -> str:
    """The books, reversed. A void takes the payment's entry out; a refund is
    an entry of its own on its own date. If the books refuse (a closed month),
    a void is entered as a refund today instead; if that is refused too, the
    owner is told to enter it by hand. Never undoes the refund itself."""
    if refund.kind == R.Kind.VOID:
        try:
            with transaction.atomic():
                finance.payment_removed(
                    refund.payment, actor=refund.requested_by,
                    reason=f"Cancelled at the card processor before it settled: "
                           f"{refund.reason}"[:500])
            return "removed"
        except finance.FinanceError:
            pass
    try:
        with transaction.atomic():
            finance.refund_recorded(refund, actor=refund.requested_by, on_date=on_date)
        return "entered"
    except finance.FinanceError as exc:
        refund.problem = (f"Given back at the card processor, but not in the books: {exc} "
                          "Enter it in the books by hand.")
        refund.save(update_fields=["problem", "updated_at"])
        return "refused"


def _tell_client(refund_id) -> None:
    try:
        _send_client(refund_id)
    except Exception as exc:  # noqa: BLE001 — the refund is recorded either way
        log.warning("refund %s: receipt or notice not sent (%s)", refund_id,
                    type(exc).__name__)


def _send_client(refund_id) -> None:
    from apps.crm.models import OutboxMessage
    from apps.crm.services import email_layout, outbox
    from apps.tenancy.context import tenant_context
    from apps.tenancy.models import Membership, Role

    refund = R.all_objects.select_related("payment", "invoice", "invoice__tenant",
                                          "invoice__client_company").get(pk=refund_id)
    invoice, tenant = refund.invoice, refund.invoice.tenant
    attempt = PaymentAttempt.all_objects.select_related("payer").filter(
        payment_id=refund.payment_id).first()
    practice = services.practice_name(tenant)
    amount = money.dollars(refund.amount_cents)
    test = " (test mode: no real money moved)" if refund.is_test or refund.environment != "live" \
        else ""
    card = " ".join(p for p in ((attempt.card_type if attempt else ""),
                                (f"ending {attempt.last4}" if attempt and attempt.last4
                                 else "")) if p) or "card"
    thread = services._thread_for(invoice)
    to = (attempt.payer.email if attempt and attempt.payer else invoice.email_to) or ""
    if refund.kind == R.Kind.VOID:
        subject = f"Payment cancelled: {amount} on invoice {invoice.number}"
        first = (f"{practice} cancelled your card payment of {amount} on invoice "
                 f"{invoice.number} before it settled{test}. It will not appear on your "
                 "card statement; if your bank shows it as pending, that falls away within "
                 "a few days.")
    else:
        subject = f"Refund: {amount} on invoice {invoice.number}"
        first = (f"{practice} refunded {amount} to your {card} on invoice {invoice.number}"
                 f"{test}. A refund usually reaches the card within 5 to 10 business days.")
    after = ("The invoice has been voided." if invoice.status == ClientInvoice.Status.VOID
             else f"Still owed on this invoice: {money.dollars(invoice.balance_cents)}."
             if invoice.balance_cents > 0 else "")
    lines = [first, f"Transaction: {refund.nmi_transaction_id}"] + ([after] if after else [])
    with tenant_context(tenant.pk):
        if to:
            outbox.create_message(
                tenant=tenant, producer=OutboxMessage.Producer.PAYMENT_RECEIPT, to_address=to,
                subject=subject, body_text="\n\n".join(lines),
                body_html=email_layout.document(
                    tenant, subject=subject, preheader=lines[0],
                    content_html="".join(f"<p>{escape(line)}</p>" for line in lines)),
                thread=thread, source_type="card_refund", source_id=refund.pk,
                force_direct=True)
        company = invoice.client_company.name if invoice.client_company_id else ""
        verb = "cancelled before it settled" if refund.kind == R.Kind.VOID else "refunded"
        owner_subject = (f"{'Payment cancelled' if refund.kind == R.Kind.VOID else 'Refund'}: "
                         f"{amount} on invoice {invoice.number}"
                         + (f" ({company})" if company else ""))
        owner_lines = [
            f"{amount} on invoice {invoice.number} was {verb}{test}. Reason: {refund.reason}",
            f"Transaction {refund.nmi_transaction_id}.",
            refund.problem or ("Nothing changes in your books: it was a test." if refund.is_test
                               else "It is taken out of your books."
                               if refund.kind == R.Kind.VOID
                               else "It is in your books as a refund today."),
            ("The invoice was voided." if invoice.status == ClientInvoice.Status.VOID else
             f"Still owed on the invoice: {money.dollars(invoice.balance_cents)}."),
        ]
        owners = Membership.all_objects.filter(tenant=tenant, role=Role.FF,
                                               revoked_at__isnull=True).select_related("user")
        for owner in owners:
            if not owner.user.email:
                continue
            outbox.create_message(
                tenant=tenant, producer=OutboxMessage.Producer.PAYMENT_NOTICE,
                to_address=owner.user.email, subject=owner_subject,
                body_text="\n\n".join(owner_lines),
                body_html=email_layout.document(
                    tenant, subject=owner_subject, preheader=owner_lines[0], internal=True,
                    content_html="".join(f"<p>{escape(line)}</p>" for line in owner_lines)),
                thread=thread, source_type="card_refund", source_id=refund.pk,
                force_direct=True)


# ================================================ a subscription charge

def refund_subscription(invoice, *, amount_cents, reason, void_invoice=False,
                        actor) -> tuple[CardRefund, str]:
    """The platform owner's, on a practice's subscription charge."""
    _refuse_acting()
    reason = _check_reason(reason)
    if invoice.status == PracticeInvoice.Status.VOID:
        raise RefundRefused("The invoice is void.")
    if not invoice.nmi_transaction_id or invoice.amount_paid_cents <= 0:
        raise RefundRefused("Nothing was charged on this invoice.")
    left = subscription_refundable_cents(invoice)
    amount = _check_amount(amount_cents, left)
    if void_invoice and (amount != left or invoice.amount_paid_cents - amount != 0):
        raise RefundRefused("The invoice is voided only with a full refund that leaves "
                            "nothing paid on it.", 400)
    try:
        account = gw.platform_account()
    except gw.GatewayError as exc:
        raise RefundRefused(str(exc)) from None
    _mode_rule(gateway_mode.for_platform(), invoice.is_test)
    sale = _sale_state(account, invoice.nmi_transaction_id)
    if sale.status == "canceled":
        raise RefundRefused("The card processor shows this charge as cancelled already, so "
                            "nothing was done. The morning read-back lists it to record.")
    try:
        with transaction.atomic():
            locked = PracticeInvoice.all_objects.select_for_update().get(pk=invoice.pk)
            amount = _check_amount(amount, subscription_refundable_cents(locked))
            untouched = not R.all_objects.filter(
                practice_invoice=locked, against_transaction_id=locked.nmi_transaction_id,
                status__in=R.COUNTED).exists()
            void = (sale.status == "pendingsettlement" and untouched
                    and amount == locked.amount_paid_cents == locked.total_cents)
            refund = R.all_objects.create(
                tenant_id=locked.tenant_id, practice_invoice=locked,
                kind=R.Kind.VOID if void else R.Kind.REFUND, amount_cents=amount,
                reason=reason, against_transaction_id=locked.nmi_transaction_id,
                sale_reference=locked.reference, environment=account.environment,
                is_test=locked.is_test, void_invoice=bool(void_invoice), requested_by=actor)
    except IntegrityError:
        raise RefundRefused("Money is already being given back on this invoice.") from None
    outcome, txn, said = _call(refund, account)
    if outcome == "unknown":
        return refund, UNKNOWN_MESSAGE
    if outcome == "failed":
        return refund, _failed_message(refund, said)
    settle_subscription(refund, nmi_transaction_id=txn.id, response_code=txn.response_code,
                        response_text=txn.response_text)
    refund.refresh_from_db()
    return refund, _done_message(refund)


def settle_subscription(refund, *, nmi_transaction_id, response_code="", response_text="",
                        tell=True) -> CardRefund:
    """Finish a subscription refund: the invoice reopened by that amount (or
    voided, if chosen on a full refund), a receipt to the practice and a
    notice to the platform owner. Subscriptions are in no books."""
    from apps.billing import subscriptions

    with transaction.atomic():
        refund = R.all_objects.select_for_update().get(pk=refund.pk)
        if refund.status == R.Status.DONE:
            return refund
        _finish(refund, R.Status.DONE, nmi_transaction_id=nmi_transaction_id,
                response_code=response_code, response_text=response_text)
        invoice = PracticeInvoice.all_objects.select_for_update().get(
            pk=refund.practice_invoice_id)
        before = invoice.status
        invoice.amount_paid_cents = max(invoice.amount_paid_cents - refund.amount_cents, 0)
        if refund.void_invoice and invoice.amount_paid_cents == 0:
            invoice.status = PracticeInvoice.Status.VOID
        elif invoice.amount_paid_cents < invoice.total_cents:
            invoice.status, invoice.paid_at = PracticeInvoice.Status.OPEN, None
        invoice.save()
        subscriptions._audit(invoice.tenant, "subscription_cancelled"
                             if refund.kind == R.Kind.VOID else "subscription_refunded",
                             refund.requested_by, number=invoice.number,
                             amount_cents=refund.amount_cents, refund=str(refund.pk),
                             before=before, after=invoice.status, source=refund.source,
                             **({"test": True} if refund.is_test else {}))
        if tell:
            transaction.on_commit(lambda: _tell_subscription(refund.pk))
    return refund


def _tell_subscription(refund_id) -> None:
    try:
        _send_subscription(refund_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("subscription refund %s: receipt or notice not sent (%s)", refund_id,
                    type(exc).__name__)


def _send_subscription(refund_id) -> None:
    from apps.billing import subscriptions
    from apps.crm.models import OutboxMessage
    from apps.platform import mail

    refund = R.all_objects.select_related("practice_invoice", "practice_invoice__tenant").get(
        pk=refund_id)
    invoice = refund.practice_invoice
    from apps.tenancy.context import tenant_context

    with tenant_context(invoice.tenant_id):
        # The PDF again, now without "charged" on it.
        subscriptions._store_pdf(invoice)
    amount = money.dollars(refund.amount_cents)
    test = " (Test mode: no real money moved.)" if refund.is_test \
        or refund.environment != "live" else ""
    row = subscriptions.subscription_for(invoice.tenant)
    to = row.billing_email or subscriptions._owner_email(invoice.tenant)
    after = ("The invoice has been voided." if invoice.status == PracticeInvoice.Status.VOID
             else f"Still owed on this invoice: {money.dollars(invoice.balance_cents)}."
             if invoice.balance_cents > 0 else "")
    if refund.kind == R.Kind.VOID:
        first = (f"Your Execs NOW HQ charge of {amount} for {invoice.period_start:%B %Y} was "
                 "cancelled before it settled. It will not appear on your card statement.")
    else:
        first = (f"{amount} of your Execs NOW HQ charge for {invoice.period_start:%B %Y} was "
                 "refunded to your card. A refund usually reaches the card within 5 to 10 "
                 "business days.")
    if to:
        mail.send_platform_mail(
            to=to, subject=f"{'Charge cancelled' if refund.kind == R.Kind.VOID else 'Refund'}: "
                           f"Execs NOW HQ invoice {invoice.number}",
            paragraphs=[first + test, f"Invoice: {invoice.number}\nTransaction: "
                                      f"{refund.nmi_transaction_id}"] + ([after] if after else []),
            producer=OutboxMessage.Producer.SUBSCRIPTION_RECEIPT)
    owner = mail.platform_owner()
    if owner is not None and owner.email:
        practice = invoice.tenant.name
        mail.send_platform_mail(
            to=owner.email, subject=f"Subscription {refund.get_kind_display().lower()}: "
                                    f"{practice}, {invoice.number}",
            paragraphs=[f"{amount} on {practice}'s invoice {invoice.number} was "
                        f"{refund.get_kind_display().lower()}{test}. Reason: {refund.reason}",
                        f"Transaction {refund.nmi_transaction_id}.",
                        after or "Nothing is owed on it now."],
            producer=OutboxMessage.Producer.SUBSCRIPTION_NOTICE)


# ===================================================== the lost answers

def resolve_unknown(tenant, *, now=None) -> int:
    """Every refund of this practice whose answer was lost (its clients'
    payments, and its own subscription charges on the platform's account):
    what the processor did, read by our reference on the sale. Found: done.
    None an hour on: nothing was given back. No answer: the next run."""
    now = now or timezone.now()
    stuck = (R.all_objects.filter(tenant=tenant, status=R.Status.UNKNOWN)
             | R.all_objects.filter(tenant=tenant, status=R.Status.PENDING,
                                    created_at__lt=now - PENDING_GRACE))
    settled = 0
    for refund in stuck.order_by("created_at"):
        try:
            account = (gw.platform_account() if refund.practice_invoice_id
                       else payment_accounts.practice_account(tenant))
            actions = gw.gateway().actions_for_reference(account, refund.sale_reference) \
                if refund.sale_reference else []
        except (gw.GatewayError, payment_accounts.PaymentAccountError):
            R.all_objects.filter(pk=refund.pk).update(looked_up_at=now)
            continue
        R.all_objects.filter(pk=refund.pk).update(looked_up_at=now)
        found = _found(refund, actions)
        if found is not None:
            if refund.practice_invoice_id:
                settle_subscription(refund, nmi_transaction_id=found)
            else:
                settle_client(refund, nmi_transaction_id=found)
            settled += 1
        elif refund.created_at < now - GIVE_UP_AFTER:
            with transaction.atomic():
                locked = R.all_objects.select_for_update().get(pk=refund.pk)
                if locked.status in R.IN_FLIGHT:
                    _finish(locked, R.Status.FAILED,
                            response_text="The card processor has none: nothing was given "
                                          "back.")
                    settled += 1
    return settled


def _found(refund, actions) -> str | None:
    """The processor's id for what this refund did, if it did it."""
    sale = refund.against_transaction_id
    if refund.kind == R.Kind.VOID:
        return sale if any(a.action_type == "void" and a.success and a.transaction_id == sale
                           for a in actions) else None
    taken = set(R.all_objects.filter(kind=R.Kind.REFUND, against_transaction_id=sale)
                .exclude(pk=refund.pk).exclude(nmi_transaction_id="")
                .values_list("nmi_transaction_id", flat=True))
    since = refund.created_at - timedelta(minutes=2)
    for a in actions:
        if (a.action_type in ("refund", "credit") and a.success
                and a.original_transaction_id == sale and a.transaction_id != sale
                and a.amount_cents == refund.amount_cents and a.transaction_id not in taken
                and a.at >= since):
            return a.transaction_id
    return None


# ================================================== the read-back's flag

def is_ours(action, *, tenant=None, subscription=False) -> bool:
    """A refund or void the app made (or is making): never flagged."""
    qs = R.all_objects.filter(practice_invoice__isnull=not subscription)
    if tenant is not None:
        qs = qs.filter(tenant=tenant)
    if action.action_type == "void":
        return qs.filter(kind=R.Kind.VOID, against_transaction_id=action.transaction_id,
                         status__in=R.COUNTED).exists()
    if qs.filter(kind=R.Kind.REFUND, nmi_transaction_id=action.transaction_id).exists():
        return True
    # Under way, its answer lost: the lookup will claim it.
    sale = action.original_transaction_id or action.transaction_id
    return qs.filter(kind=R.Kind.REFUND, against_transaction_id=sale,
                     status__in=R.IN_FLIGHT, amount_cents=action.amount_cents).exists()


def can_record(event) -> bool:
    if event.kind not in (NmiEvent.Kind.REFUND, NmiEvent.Kind.VOID):
        return False
    if R.all_objects.filter(nmi_event=event).exists():
        return False
    return (event.practice_invoice_id is not None) if event.platform \
        else event.payment_id is not None


def record_event(event, *, actor, void_invoice=False) -> CardRefund:
    """"Record this refund": a refund or void made in the processor's own
    portal, flagged by the read-back, recorded with the same bookkeeping as
    one made here. No call to the processor, and no email."""
    _refuse_acting()
    if not can_record(event):
        raise RefundRefused("This one can't be recorded as a refund here.")
    kind = R.Kind.VOID if event.kind == NmiEvent.Kind.VOID else R.Kind.REFUND
    when = timezone.localtime(event.happened_at)
    reason = f"Made in the card processor's portal on {when:%B} {when.day}, {when.year}."
    try:
        with transaction.atomic():
            if event.platform:
                invoice = PracticeInvoice.all_objects.select_for_update().get(
                    pk=event.practice_invoice_id)
                amount = _check_amount(event.amount_cents,
                                       subscription_refundable_cents(invoice))
                if void_invoice and invoice.amount_paid_cents - amount != 0:
                    raise RefundRefused("The invoice is voided only when nothing is left "
                                        "paid on it.", 400)
                refund = R.all_objects.create(
                    tenant_id=invoice.tenant_id, practice_invoice=invoice, kind=kind,
                    source=R.Source.PORTAL, amount_cents=amount, reason=reason,
                    against_transaction_id=invoice.nmi_transaction_id,
                    sale_reference=invoice.reference,
                    environment=gw.platform_account().environment, is_test=invoice.is_test,
                    void_invoice=bool(void_invoice), requested_by=actor, nmi_event=event)
            else:
                payment = ClientPayment.all_objects.select_for_update().get(
                    pk=event.payment_id)
                amount = _check_amount(event.amount_cents, refundable_cents(payment))
                if void_invoice and payment.invoice.paid_cents - amount != 0:
                    raise RefundRefused("The invoice is voided only when nothing is left "
                                        "paid on it.", 400)
                attempt = PaymentAttempt.all_objects.filter(payment=payment).first()
                refund = R.all_objects.create(
                    tenant_id=payment.tenant_id, payment=payment, invoice_id=payment.invoice_id,
                    kind=kind, source=R.Source.PORTAL, amount_cents=amount, reason=reason,
                    against_transaction_id=payment.nmi_transaction_id,
                    sale_reference=str(attempt.pk) if attempt else "",
                    environment=attempt.environment if attempt else "live",
                    is_test=payment.is_test, void_invoice=bool(void_invoice),
                    requested_by=actor, nmi_event=event)
            NmiEvent.all_objects.filter(pk=event.pk).update(
                reviewed_at=timezone.now(), reviewed_by=actor, updated_at=timezone.now())
    except IntegrityError:
        raise RefundRefused("Money is already being given back on this payment.") from None
    if refund.practice_invoice_id:
        return settle_subscription(refund, nmi_transaction_id=event.transaction_id, tell=False)
    return settle_client(refund, nmi_transaction_id=event.transaction_id,
                         on_date=when.date(), tell=False)


# ------------------------------------------- for the Practices area (P4 §5)

def refund_practice_charge(practice_pk, invoice_pk, *, amount_cents, reason, void_invoice,
                           actor):
    """The platform owner's, by ids: (the practice's subscription row, the
    sentence to show), or None when the invoice is not that practice's."""
    from apps.billing import subscriptions

    invoice = PracticeInvoice.all_objects.select_related("tenant").filter(
        pk=invoice_pk, tenant_id=practice_pk).first()
    if invoice is None:
        return None
    _, message = refund_subscription(invoice, amount_cents=amount_cents, reason=reason,
                                     void_invoice=void_invoice, actor=actor)
    return subscriptions.platform_summary(invoice.tenant), message


def record_platform_event(pk, *, actor, void_invoice=False) -> dict | None:
    """"Record this refund" on a platform read-back flag, by id."""
    from apps.billing import readback

    event = NmiEvent.all_objects.filter(pk=pk, platform=True).first()
    if event is None:
        return None
    record_event(event, actor=actor, void_invoice=void_invoice)
    event.refresh_from_db()
    return readback.represent(event)

