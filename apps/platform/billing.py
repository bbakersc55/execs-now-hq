"""What the platform owner sees and does about a practice's subscription
(P4 part 5, `docs/p4_billing.md` §5): its status, amount, whether a card is
on file, what is open and for how long. **Only amounts, dates and states**:
never the card's details beyond "on file", never anything inside the
practice, and never a client invoice. It names no practice model: the
subscription service answers (`apps/billing/subscriptions.py`).
"""

from __future__ import annotations


def subscription_row(tenant) -> dict:
    from apps.billing import subscriptions

    return subscriptions.platform_summary(tenant)


def set_amount(tenant, amount_cents, *, actor) -> None:
    from apps.billing import subscriptions

    subscriptions.set_amount(tenant, amount_cents, actor=actor)


def mark_nmi_event_seen(pk, *, user):
    from apps.billing import readback

    return readback.mark_platform_seen(pk, user=user)



def refund_charge(practice_pk, invoice_pk, *, amount_cents, reason, void_invoice, actor):
    """2026-11-16: "Refund or cancel this charge" on a practice's
    subscription invoice: (row, message), or None when it is not that
    practice's. The refund service answers; this names no practice model."""
    from apps.billing import refunds

    return refunds.refund_practice_charge(practice_pk, invoice_pk, amount_cents=amount_cents,
                                          reason=reason, void_invoice=void_invoice, actor=actor)


def record_nmi_event(pk, *, user, void_invoice=False):
    """"Record this refund" on what the platform's read-back flagged."""
    from apps.billing import refunds

    return refunds.record_platform_event(pk, actor=user, void_invoice=void_invoice)
