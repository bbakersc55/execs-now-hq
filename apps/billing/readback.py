"""The daily read-back (P4 §4): what happened in a practice's NMI account
that this app did not do itself.

Every charge is made by the app, so the sale's own answer says paid or
declined at once; what the app cannot see is what someone does afterwards in
NMI's portal. Once a day, per connected account, the last several days of
actions are read (read-only: nothing is ever charged or refunded here) and
each one the app did not make becomes one `nmi_event`:

- a **refund, void or chargeback** is matched to the payment it was against,
  by NMI's transaction id (or the original one, for a refund NMI keeps as its
  own transaction), then by our reference, and recorded against it;
- anything that can't be matched, **including a charge made in NMI's portal**,
  is flagged for the practice owner.

Our own sales (a payment or an attempt carries their transaction id or our
reference) are not events. A subscription charge ("sub-…") is the platform's
and is left out, even where a practice shares the platform's keys (§1.2).
"""

from __future__ import annotations

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.billing import gateway as gw
from apps.billing import payment_accounts
from apps.billing.models import ClientPayment, NmiEvent, PaymentAttempt
from apps.tenancy.models import AuditEvent

#: How far back each read looks: a week, so a day or two missed is caught up.
DAYS_BACK = 7
KINDS = {"refund": NmiEvent.Kind.REFUND, "credit": NmiEvent.Kind.REFUND,
         "void": NmiEvent.Kind.VOID, "chargeback": NmiEvent.Kind.CHARGEBACK,
         "sale": NmiEvent.Kind.SALE}
#: Actions that are bookkeeping, not money moving: never events.
QUIET = {"auth", "capture", "settle", "validate", "update", "check_status", ""}


def event_id(action) -> str:
    return f"{action.transaction_id}:{action.action_type}:{action.at:%Y%m%d%H%M%S}"


def _payment_for(tenant, action):
    ids = [i for i in (action.transaction_id, action.original_transaction_id) if i]
    payment = ClientPayment.all_objects.filter(tenant=tenant, nmi_transaction_id__in=ids,
                                               removed_at__isnull=True).first()
    if payment is not None:
        return payment
    if action.reference:
        attempt = PaymentAttempt.all_objects.filter(
            tenant=tenant, nmi_transaction_id__in=ids).first() or (
            PaymentAttempt.all_objects.filter(tenant=tenant, pk=action.reference).first()
            if _uuid(action.reference) else None)
        if attempt is not None and attempt.payment_id:
            return attempt.payment
    return None


def _ours(tenant, action) -> bool:
    """A sale this app made (or the platform's subscription charge)."""
    if action.reference.startswith("sub-"):
        return True
    if ClientPayment.all_objects.filter(tenant=tenant,
                                        nmi_transaction_id=action.transaction_id).exists():
        return True
    if PaymentAttempt.all_objects.filter(tenant=tenant,
                                         nmi_transaction_id=action.transaction_id).exists():
        return True
    return bool(action.reference) and _uuid(action.reference) and \
        PaymentAttempt.all_objects.filter(tenant=tenant, pk=action.reference).exists()


def read_back(tenant, *, now=None) -> dict:
    """One practice's read-back. Returns counts; a practice with no account
    connected, or NMI not answering, is left for the next day."""
    now = now or timezone.now()
    try:
        account = payment_accounts.practice_account(tenant)
    except payment_accounts.PaymentAccountError:
        return {"read": 0, "matched": 0, "flagged": 0, "skipped": "not connected"}
    try:
        actions = gw.gateway().actions_between(account, now - timedelta(days=DAYS_BACK), now)
    except gw.GatewayError as exc:
        AuditEvent.all_objects.create(
            tenant=tenant, verb="billing.read_back_failed", target_type="tenant",
            target_id=tenant.pk, payload={"error": str(exc)[:300]})
        return {"read": 0, "matched": 0, "flagged": 0, "skipped": "NMI did not answer"}
    counts = {"read": len(actions), "matched": 0, "flagged": 0, "skipped": ""}
    for action in actions:
        if action.action_type in QUIET or not action.success:
            continue
        if action.reference.startswith("sub-"):
            continue                                  # the platform's, never a practice's
        kind = KINDS.get(action.action_type, NmiEvent.Kind.OTHER)
        if kind == NmiEvent.Kind.SALE and _ours(tenant, action):
            continue
        payment = None if kind == NmiEvent.Kind.SALE else _payment_for(tenant, action)
        outcome = NmiEvent.Outcome.MATCHED if payment is not None else NmiEvent.Outcome.UNMATCHED
        note = _words(kind, action, payment)
        try:
            with transaction.atomic():
                row = NmiEvent.all_objects.create(
                    tenant=tenant, event_id=event_id(action)[:120], kind=kind,
                    action_type=action.action_type[:40], transaction_id=action.transaction_id,
                    original_transaction_id=action.original_transaction_id,
                    reference=action.reference[:60], amount_cents=action.amount_cents,
                    happened_at=action.at, payment=payment,
                    invoice_id=payment.invoice_id if payment else None, outcome=outcome,
                    note=note)
        except IntegrityError:
            continue                                  # read on an earlier day
        counts["matched" if payment is not None else "flagged"] += 1
        AuditEvent.all_objects.create(
            tenant=tenant, verb=f"billing.nmi_{kind}_{outcome}", target_type="nmi_event",
            target_id=row.pk, payload={"transaction": action.transaction_id,
                                       "amount_cents": action.amount_cents,
                                       "invoice": str(row.invoice_id) if row.invoice_id else None})
    return counts


def _words(kind, action, payment) -> str:
    amount = f"${action.amount_cents / 100:,.2f}"
    when = f"{action.at:%b} {action.at.day}"
    if payment is not None:
        what = {"refund": "Refunded", "void": "Voided", "chargeback": "Charged back"}.get(
            kind, "Changed")
        return (f"{what} {amount} in NMI on {when}, against the payment of "
                f"${payment.amount_cents / 100:,.2f} on invoice {payment.invoice.number or ''}. "
                "The invoice's balance is not changed by this: record what it means by hand.")
    if kind == NmiEvent.Kind.SALE:
        return (f"A charge of {amount} made in NMI on {when} that no invoice here made "
                f"(NMI transaction {action.transaction_id}).")
    return (f"A {action.action_type or 'change'} of {amount} in NMI on {when} that matches no "
            f"payment here (NMI transaction {action.transaction_id}).")


def _uuid(value) -> bool:
    import uuid

    try:
        uuid.UUID(str(value))
    except (TypeError, ValueError):
        return False
    return True


def represent(event) -> dict:
    return {"id": str(event.pk), "kind": event.kind, "kind_label": event.get_kind_display(),
            "amount_cents": event.amount_cents, "happened_at": event.happened_at.isoformat(),
            "transaction_id": event.transaction_id, "outcome": event.outcome,
            "note": event.note, "invoice": str(event.invoice_id) if event.invoice_id else None,
            "invoice_number": event.invoice.number if event.invoice_id else "",
            "reviewed": event.reviewed_at is not None}
