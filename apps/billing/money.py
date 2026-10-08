"""Money is integer cents. This is the only place it becomes text."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def cents(value, *, what="An amount") -> int:
    """A whole number of cents from what the API was sent. A float is refused
    rather than rounded: 19.99 * 100 is not 1999 in floating point."""
    from apps.billing.services import BillingError

    if isinstance(value, bool) or not isinstance(value, int):
        raise BillingError(f"{what} is a whole number of cents.")
    if value < 0:
        raise BillingError(f"{what} cannot be negative.")
    return value


def line_amount(quantity: Decimal, unit_price_cents: int) -> int:
    """Quantity times price, rounded once, half up, to the cent."""
    return int((quantity * Decimal(unit_price_cents)).quantize(Decimal("1"),
                                                             rounding=ROUND_HALF_UP))


def dollars(value: int) -> str:
    """`$1,234.56`, from cents."""
    sign = "-" if value < 0 else ""
    whole, part = divmod(abs(int(value)), 100)
    return f"{sign}${whole:,}.{part:02d}"
