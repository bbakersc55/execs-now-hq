"""The demo's Google reviews (`docs/google_reviews_feed.md`, "The demo").

The demo never signs in to Google: connecting a Business Profile is refused
there. So that the company page's Business Profile and Reviews cards and a
KPI have something to show, Stark Tool & Die's location is connected here,
with a year of reviews read through the real sync code from a stand-in for
Google, and its "Reputation" scorecard page has four KPIs fed from them, run
through the real feed code: the rating, new reviews, five-star reviews and
the all-time total.

**The five-star review bonus** (2026-11-12, the SkyRun bonus's example): $5
for each five-star Google review in the month, each person on the plan
earning it in full. Its people are the Customer service team (two people,
added here) and Happy Hogan, named on his own. The three months before this
one are closed, and this month's is the copy of the last.
"""

from __future__ import annotations

import json
from datetime import timedelta

from .clock import at, dice, moment

COMPANY = "Stark Tool & Die"
PAGE = "Reputation"
TEAM = "Customer service"
#: Who answers the phone and the reviews: (first, last, title).
SERVICE = [("Dana", "Ortiz", "Customer service lead"),
           ("Kevin", "Walsh", "Customer service")]
BONUS = "Five-star review bonus"
BONUS_MONTHS = 3
#: (text, stars) — what customers of a machine shop say.
SAID = [
    ("Tight tolerances, delivered a day early. Will order again.", 5),
    ("Great communication from quote to delivery.", 5),
    ("Parts were right the first time.", 5),
    ("Good work, but the lead time slipped a week.", 4),
    ("Solid shop. Pricing is fair.", 4),
    ("They fixed a drawing error before we even noticed it.", 5),
    ("Quality is excellent; invoicing took a few emails.", 4),
    ("Late delivery and nobody called.", 2),
    ("Answered every question on the first call.", 5),
    ("Rework on two parts, handled quickly.", 3),
]
NAMES = ["Ellen R.", "Dwayne K.", "Priya S.", "Marco T.", "Hank A.", "Sasha M.", "Tom O.",
         "Gwen L.", "Rafael D.", "Nora B.", "Ivan P.", "Leah W."]


def _reviews(world) -> list[dict]:
    """About three a month for a year, newest last; most replied to within a
    few days, the latest two not yet."""
    out = []
    day = world.today - timedelta(days=365)
    n = 0
    while day < world.today - timedelta(days=1):
        roll = dice("review", n)
        text, stars = SAID[roll.randrange(len(SAID))]
        created = moment(day, roll.randrange(8, 18), roll.randrange(60))
        reply = None
        if day < world.today - timedelta(days=12) and stars and roll.random() < 0.85:
            reply = created + timedelta(hours=roll.randrange(3, 96))
        out.append({"reviewId": f"demo-review-{n}",
                    "reviewer": {"displayName": NAMES[roll.randrange(len(NAMES))]},
                    "starRating": ["", "ONE", "TWO", "THREE", "FOUR", "FIVE"][stars],
                    "comment": text, "createTime": created.isoformat(),
                    "updateTime": (reply or created).isoformat(),
                    **({"reviewReply": {"comment": "Thank you!", "updateTime": reply.isoformat()}}
                       if reply else {})})
        day += timedelta(days=roll.randrange(6, 14))
        n += 1
    return out


def _stand_in(reviews):
    """Google, as the sync asks it: one page, newest change first."""
    ordered = sorted(reviews, key=lambda r: r["updateTime"], reverse=True)
    stars = [["", "ONE", "TWO", "THREE", "FOUR", "FIVE"].index(r["starRating"]) for r in reviews]

    def transport(url, headers):
        return 200, json.dumps({"reviews": ordered, "totalReviewCount": len(reviews),
                                "averageRating": round(sum(stars) / len(stars), 1)})

    return transport


def connect(world) -> dict:
    from apps.crm.services import secrets
    from apps.scorecard import feeds, google_reviews, setup
    from apps.scorecard.models import GoogleReviewsConnection, Kpi, KpiReviewsFeed

    company = world.companies[COMPANY]
    reviews = _reviews(world)
    when = moment(world.today, 6, 30)
    with at(when):
        connection = GoogleReviewsConnection.objects.create(
            tenant=world.tenant, company=company, google_email="reviews@starktooldie.example",
            # Never a real token: the demo refuses everything that would use it.
            token_ciphertext=secrets.encrypt("demo-no-google"),
            account_name="accounts/demo-stark", account_label=COMPANY,
            location_name="locations/demo-stark-long-island",
            location_title="Stark Tool & Die, Long Island", created_by=world.owner,
            checked_at=when, check_ok=True,
            check_detail=f"Connected: {len(reviews)} reviews.")
        google_reviews.sync(connection, google_reviews.ReviewsClient(
            "demo", transport=_stand_in(reviews)))
        card = setup.ensure(company, world.owner)
        page = card.pages.get()
        page.name = PAGE
        page.save(update_fields=["name", "updated_at"])
        kpis = [
            (setup.create_kpi(card, {
                "name": "Google rating", "kind": "rating", "rating_scale": 5,
                "cadence": "monthly", "rollup": "average", "target_value": "4.6",
                "tile": "number_trend", "page": str(page.pk),
                "reading_owner": str(world.owner.pk), "strategy_component": "people",
                "note": "Average stars of the month's new Google reviews"}, world.owner),
             "average_rating"),
            (setup.create_kpi(card, {
                "name": "New Google reviews", "kind": "count", "cadence": "monthly",
                "rollup": "sum", "target_value": 3, "tile": "bars", "page": str(page.pk),
                "reading_owner": str(world.owner.pk), "strategy_component": "traction",
                "note": "Reviews customers left on Google in the month"}, world.owner),
             "new_reviews"),
            (setup.create_kpi(card, {
                "name": "Five-star Google reviews", "kind": "count", "cadence": "monthly",
                "rollup": "sum", "target_value": 2, "tile": "bars", "page": str(page.pk),
                "reading_owner": str(world.owner.pk), "strategy_component": "people",
                "note": "Five-star reviews in the month; the five-star review bonus pays "
                        "on it"}, world.owner),
             "reviews_by_star"),
            (setup.create_kpi(card, {
                "name": "Total Google reviews", "kind": "count", "cadence": "monthly",
                "rollup": "last", "tile": "number_trend", "page": str(page.pk),
                "reading_owner": str(world.owner.pk), "strategy_component": "traction",
                "note": "Every review on the profile, all time, at the month's end"},
                world.owner),
             "total_reviews"),
        ]
        for kpi, measure in kpis:
            star = 5 if measure == "reviews_by_star" else None
            feed = KpiReviewsFeed.objects.create(
                tenant=world.tenant, kpi=kpi, measure=measure, star=star,
                # The bonus counts this month's five-star reviews so far.
                read_open=True if star else None, created_by=world.owner)
            Kpi.objects.filter(pk=kpi.pk).update(feed=Kpi.Feed.REVIEWS)
            feed.refresh_from_db()
            feeds.run_reviews(feed, world.today, now=when)
        plans = bonus_plan(world, card, kpis[2][0])
    return {"Google reviews": len(reviews), "reviews KPIs": [k.name for k, _ in kpis],
            "five-star review bonus months": plans}


def bonus_plan(world, card, five_star) -> int:
    """The five-star review bonus: the Customer service team, two people
    given portal access here, and Happy Hogan by name. Made for the month
    three back, each closed and copied forward, so this month's is open."""
    from apps.scorecard import bonus
    from apps.scorecard import periods as P
    from apps.work import portal, teams

    from .foundation import address_for, contact

    company = world.companies[COMPANY]
    happy = next(m for m in world.portal[COMPANY] if m.user.full_name.startswith("Happy"))
    used = len(world.portal[COMPANY])
    if company.seat_count < used + len(SERVICE):
        company.seat_count = used + len(SERVICE)
        company.save(update_fields=["seat_count", "updated_at"])
    service = teams.create_team(company, TEAM, actor=world.owner)
    for first, last, title in SERVICE:
        row = contact(world, first, last, title, company, address_for(first, last, COMPANY),
                      kind="client")
        member = portal.grant(tenant=world.tenant, contact=row, actor=world.owner,
                              role="ECC", team=service, level=teams.Level.MEMBER)
        member.user.last_login_at = moment(
            world.today - timedelta(days=dice("service", row.pk).randrange(1, 6)), 9, 30)
        member.user.save(update_fields=["last_login_at"])
    month = world.today.replace(day=1)
    for _ in range(BONUS_MONTHS):
        month = P.previous_start(month, P.MONTHLY)
    plan = bonus.create_plan(card, {
        "name": BONUS, "period": "monthly", "period_start": month.isoformat(),
        "units": [{"kpi": str(five_star.pk), "rate": 5}], "unit_split": "each",
        "teams": [str(service.pk)], "people": [{"membership": str(happy.pk)}]}, world.owner)
    made = 1
    while P.end_of(plan.period_start, P.MONTHLY) < world.today:
        bonus.close(plan, world.owner, world.today)
        plan = bonus.copy_forward(plan, world.owner)
        made += 1
    return made
