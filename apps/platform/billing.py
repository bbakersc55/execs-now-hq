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
