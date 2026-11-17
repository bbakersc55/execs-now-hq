"""Automatic billing at Acme Fasteners (2026-11-17, `docs/p4_billing.md` §14).

Two recurring invoices that bill automatically, beside Acme's monthly
retainer (which the practice still sends itself):

- **Operations support, on the 1st and 15th**: agreed in the portal by Wiley
  Coyote six days ago, with a card saved; active, its first billing date the
  next 1st or 15th far enough off that no invoice is due yet.
- **Dashboard upkeep, on the 15th**: agreed nine days ago, and notice given
  yesterday, so it ends on the last day of next month and its last charge is
  next month's 15th.

The demo connects to no card processor and runs no worker, so nothing is
made or charged by itself: the agreements are written as the portal writes
them, through the app's own words, and the card is a stand-in record. The
practice's card account is a row with no keys, in the sandbox, so the card
reads as saved in the same environment.
"""

from __future__ import annotations

from datetime import date, timedelta

from .clock import at, moment


def _next_on(today: date, days: tuple[int, ...], *, after: int = 4) -> date:
    day = today + timedelta(days=after)
    while day.day not in days:
        day += timedelta(days=1)
    return day


def autobill(world) -> None:
    from apps.billing import recurring, services
    from apps.billing.models import (
        BillingAgreement, ClientInvoiceSchedule, ClientPaymentMethod, PaymentAccount,
    )

    name = "Acme Fasteners"
    company, owner = world.companies[name], world.portal[name][0]
    contact, today = world.people[name][0], world.today
    PaymentAccount.objects.get_or_create(tenant=world.tenant,
                                         defaults={"environment": "sandbox"})
    with at(moment(today - timedelta(days=9), 10, 5)):
        card = ClientPaymentMethod.objects.create(
            tenant=world.tenant, client_company=company, vault_id="demo-vault-acme",
            environment="sandbox", brand="Visa", last4="4242", exp_month=10, exp_year=2029,
            added_by=owner.user)

    plans = [
        ("Operations support, twice a month", 150000, (1, 15), 6, False),
        ("Dashboard upkeep", 40000, (15,), 9, True),
    ]
    for description, cents, days, agreed_ago, ending in plans:
        agreed_on = today - timedelta(days=agreed_ago)
        with at(moment(agreed_on - timedelta(days=1), 16, 30)):
            schedule = services.save_schedule(
                world.tenant, actor=world.owner, client_company=company, contact=contact,
                mode=ClientInvoiceSchedule.Mode.AUTO, days_of_month=list(days),
                first_billing_on=_next_on(today, days), lead_days=3,
                lines=[{"description": description, "quantity": "1",
                        "unit_price_cents": cents}])
        with at(moment(agreed_on, 10, 20)) as when:
            words = recurring.words(schedule, agreed_on)
            agreement = BillingAgreement.objects.create(
                tenant=world.tenant, schedule=schedule, client_company=company,
                agreed_by=owner.user, agreed_at=when, wording=words,
                wording_version=recurring.WORDING_VERSION, ip_address="203.0.113.24",
                user_agent="Mozilla/5.0 (Macintosh) demo", card=card)
        if ending:
            notice_on = today - timedelta(days=1)
            with at(moment(notice_on, 14, 45)) as when:
                from apps.billing import timing

                agreement.notice_given_at, agreement.notice_given_by = when, owner.user
                agreement.ends_on = timing.notice_end(notice_on, schedule.term_ends_on)
                agreement.ends_set_by = BillingAgreement.SetBy.CLIENT
                agreement.ends_set_at = when
                agreement.save()
    world.extra["automatic_billing"] = 2
