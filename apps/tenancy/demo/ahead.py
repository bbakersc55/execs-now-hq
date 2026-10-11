"""The demo's cash forecast (P6 M2 §10): what John Carter has said to it.

The forecast itself is never stored, so there is nothing to seed for it: it
is worked out from the books the rest of the seed made. What is seeded is
what an owner says: a floor, planned lines, one what-if, two corrections,
and an invoice old enough not to be counted. "How good it has been" is made
as the months go by (`money.history`), by looking at the forecast on the
first of each month, as he would have.
"""

from __future__ import annotations

from datetime import timedelta

from .clock import at, moment, next_month


def look_on_the_first(world, month) -> None:
    """The forecast as it stood when a month began: kept, to be set beside
    what happened once the month is closed. Only once two months are closed."""
    from apps.finance import forecast

    if len(forecast.closed_months(world.tenant)) < forecast.CLOSED_MONTHS_NEEDED:
        return
    with at(moment(month, 9, 0)):
        forecast.build(world.tenant, month)


def looking_ahead(world) -> None:
    from apps.billing import services as billing
    from apps.billing.models import ClientInvoice
    from apps.finance import forecast

    owner, tenant, today = world.owner, world.tenant, world.today
    this_month = today.replace(day=1)

    # An invoice old enough to be "not counted": a workshop for a referral
    # partner, sent three months ago and never paid.
    partner = next((p for p in world.partners if p.last_name != "Welton"), None)
    if partner is not None:
        with at(moment(today - timedelta(days=96), 10, 30)):
            old = billing.create_draft(
                tenant, actor=owner, kind=ClientInvoice.Kind.CONTACT, contact=partner,
                lines=[{"description": "Process walk-through for a member company, "
                                       "half day", "quantity": "1",
                        "unit_price_cents": 120_000}])
            billing.make_ready(old, actor=owner, role="FF")
            billing.send(old, actor=owner, role="FF")
        world.extra["old_invoice"] = old

    if len(forecast.closed_months(tenant)) < forecast.CLOSED_MONTHS_NEEDED:
        return
    with at(moment(today, 8, 40)):
        before = forecast.build(tenant, today, snapshot=False)
        # A floor a little under the low point as the books give it, so that
        # what he has planned takes the forecast under it.
        low = before["views"]["90"]["low_cents"]
        forecast.set_floor(tenant, actor=owner,
                           floor_cents=max(0, (low - 200_000) // 100_000 * 100_000))

        # Planned: a hire in two months, laptops next month.
        hire_from = next_month(next_month(this_month))
        forecast.save_planned(
            tenant, actor=owner, description="Operations analyst, part time",
            amount_cents=420_000, on_date=hire_from, repeat="monthly")
        forecast.save_planned(
            tenant, actor=owner, description="Two laptops for the associates",
            amount_cents=480_000, on_date=next_month(this_month) + timedelta(days=9))
        # One what-if: drawn, not counted, until he tries it.
        fee = world.fee.get("Globex Logistics")
        if fee:
            forecast.save_planned(
                tenant, actor=owner, is_what_if=True, repeat="monthly",
                description="Globex does not renew: its retainer stops",
                amount_cents=fee, on_date=next_month(hire_from) + timedelta(days=14))

        # Two corrections to what the forecast found.
        found = {row["label"]: row["group"] for row in before["lines"]
                 if row["kind"] == "regular"}
        if "Larimer Square Cowork" in found:
            forecast.adjust(tenant, actor=owner, group=found["Larimer Square Cowork"],
                            kind="amount", amount_cents=74_500, from_date=hire_from)
        once = next((row for row in before["lines"] if row["kind"] == "regular"
                     and row["category"].startswith("Travel: meals")), None)
        if once is not None:
            forecast.adjust(tenant, actor=owner, group=once["group"], kind="not_regular")
