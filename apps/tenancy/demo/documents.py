"""E-signature on the demo (owner, 2026-10-29).

- **Sheinhardt Wig Company**: Jack Donaghy's proposal, sent four days ago
  and opened the day after, waiting for his signature. A visitor signs it
  from the company card's "Open the signing page" (the demo only), which is
  both sides of the deal at once; signing moves Jack to Closed Won by the
  default rule, and the visitor then countersigns it.
- **Pied Piper Compression**: the engagement letter Richard Hendricks
  signed before the work began, countersigned and complete, so the card
  shows a whole one and the welcome letter has terms to quote.

Made through the app's own services, so the PDFs, hashes, signature pages
and Outbox rows are what the app makes. The seed's mail goes nowhere.
"""

from __future__ import annotations

from datetime import timedelta

from .clock import at, moment

SENT_DAYS_AGO = 4


def documents(world) -> dict:
    from apps.crm.models import Company
    from apps.crm.services import outbox
    from apps.esign import seed, services
    from apps.esign.models import DocumentTemplate

    seed.seed_tenant(world.tenant)
    templates = {t.original: t for t in DocumentTemplate.all_objects.filter(
        tenant=world.tenant)}
    made = {}

    def send(document, when):
        with at(when):
            message = services.queue_request(document, actor=world.owner, role="FF")
            outbox.approve(message, actor=world.owner, role="FF")
        document.refresh_from_db()
        return document

    # Pied Piper: signed, countersigned, complete, before the work began.
    piper = world.companies.get("Pied Piper Compression")
    richard = next((c for c in world.people.get("Pied Piper Compression", [])
                    if c.first_name == "Richard"), None)
    if piper is not None and richard is not None:
        began = world.start.get("Pied Piper Compression")
        day = began - timedelta(days=10)
        with at(moment(day, 10, 0)):
            letter = services.from_template(piper, templates["engagement_letter"], richard,
                                            fields={
                                                "Scope": "Operations for the compression "
                                                         "team: hiring plan, release cadence "
                                                         "and a weekly operating review.",
                                                "Fee": "$2,500 a month, invoiced on the 1st",
                                                "Term": "Twelve months",
                                                "StartDate": began.isoformat()},
                                            actor=world.owner)
        send(letter, moment(day, 10, 30))
        with at(moment(day + timedelta(days=1), 8, 40)):
            services.viewed(letter, ip="203.0.113.24", user_agent="Demo browser")
        with at(moment(day + timedelta(days=1), 9, 5)):
            services.sign(letter, method="typed", typed="Richard Hendricks", agreed=True,
                          ip="203.0.113.24", user_agent="Demo browser")
        with at(moment(day + timedelta(days=1), 11, 20)):
            services.countersign(letter, actor=world.owner, method="typed",
                                 typed=world.owner.full_name or "Practice owner", agreed=True,
                                 ip="198.51.100.7", user_agent="Demo browser")
        made["complete"] = 1

    # Sheinhardt: Jack's proposal, opened and waiting.
    jack = world.prospects.get("Jack Donaghy")
    company = Company.all_objects.filter(pk=getattr(jack, "company_id", None)).first()
    if jack is not None and company is not None:
        day = world.today - timedelta(days=SENT_DAYS_AGO)
        with at(moment(day, 14, 0)):
            proposal = services.from_template(company, templates["proposal"], jack, fields={
                "Scope": "A 90-day operations reset: order-to-delivery mapped, the three "
                         "slowest steps fixed, and a weekly scorecard the leadership team "
                         "runs without us.",
                "Fee": "$4,500 a month",
                "Term": "Three months, then month to month",
                "StartDate": (world.today + timedelta(days=14)).isoformat()},
                actor=world.owner)
        send(proposal, moment(day, 14, 30))
        with at(moment(day + timedelta(days=1), 7, 50)):
            services.viewed(proposal, ip="203.0.113.80", user_agent="Demo browser")
        made["waiting"] = 1
    return made
