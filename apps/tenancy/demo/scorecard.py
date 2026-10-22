"""Summit's scorecard (M5 part 1): one client's, so a visitor sees a real one.

Dunder Mifflin Paper, run by Summit's owner. Six KPIs on two pages, thirteen
closed weeks of readings entered through the app's own code, the week each
one closed:

- **Weekly scorecard**, everyone at the company: on-time delivery (a gauge),
  orders shipped (bars), revenue (progress, with a target per month: paper
  sells in the fall) and overtime hours (status, lower is better, for senior
  leadership and up).
- **Sales floor**, the Sales floor team: sales calls per person, with the
  leaderboard on, and customer rating per person, each person seeing their
  own. The team is five: Dwight manages it, and Jim, Phyllis, Stanley and
  Andy are on it.

One reading was corrected after it was entered, so its history shows, and
Andy's rating for the week just closed is missing, so his manager has a
reminder waiting.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from .clock import at, dice, moment
from .foundation import address_for, contact

COMPANY = "Dunder Mifflin Paper"
TEAM = "Sales floor"
#: The four who join Dwight on the team, (first, last, title).
FLOOR = [("Jim", "Halpert", "Sales representative"),
         ("Phyllis", "Vance", "Sales representative"),
         ("Stanley", "Hudson", "Sales representative"),
         ("Andy", "Bernard", "Sales representative")]
WEEKS = 13

#: Revenue's weekly target, by month: busier in the fall.
REVENUE_BY_MONTH = {1: 48000, 2: 48000, 3: 50000, 4: 50000, 5: 50000, 6: 50000, 7: 52000,
                    8: 52000, 9: 56000, 10: 60000, 11: 64000, 12: 66000}


def scorecard(world) -> dict:
    """Make it. Returns counts, for the seed's own summary."""
    from apps.scorecard import periods as P
    from apps.scorecard import setup
    from apps.scorecard.models import Kpi, KpiReading, KpiReadingChange, KpiReminder
    from apps.work import portal, teams

    company = world.companies[COMPANY]
    owner_member, dwight_member = world.portal[COMPANY][:2]
    start = world.today - timedelta(days=7 * (WEEKS + 2))

    with at(start):
        company.seat_count = 8
        company.save(update_fields=["seat_count", "updated_at"])
        floor_team = teams.create_team(company, TEAM, actor=world.owner)
        teams.set_level(floor_team, dwight_member, teams.Level.MANAGER, actor=world.owner)
        team = {dwight_member.pk: dwight_member}
        for first, last, title in FLOOR:
            row = contact(world, first, last, title, company, address_for(first, last, COMPANY),
                          kind="client")
            member = portal.grant(tenant=world.tenant, contact=row, actor=world.owner,
                                  role="ECC", team=floor_team, level=teams.Level.MEMBER)
            member.user.last_login_at = moment(
                world.today - timedelta(days=dice("seen", row.pk).randrange(1, 6)), 9, 30)
            member.user.save(update_fields=["last_login_at"])
            team[member.pk] = member

        card = setup.ensure(company, world.owner)
        weekly = card.pages.get()
        sales = setup.create_page(card, {"name": TEAM, "audience": "team",
                                         "team": str(floor_team.pk)}, world.owner)
        michael, dwight = owner_member.user, dwight_member.user
        kpis = {
            "delivery": setup.create_kpi(card, {
                "name": "On-time delivery", "kind": "percent", "cadence": "weekly",
                "rollup": "average", "target_value": 95, "tile": "gauge",
                "reading_owner": str(dwight.pk), "page": str(weekly.pk),
                "strategy_component": "process",
                "note": "Orders delivered by the promised date ÷ orders delivered, "
                        "from the warehouse log"}, world.owner),
            "orders": setup.create_kpi(card, {
                "name": "Orders shipped", "kind": "count", "cadence": "weekly",
                "rollup": "sum", "target_value": 420, "tile": "bars",
                "reading_owner": str(dwight.pk), "page": str(weekly.pk),
                "strategy_component": "traction",
                "note": "Orders that left the warehouse, from the shipping report"},
                world.owner),
            "revenue": setup.create_kpi(card, {
                "name": "Revenue", "kind": "money", "cadence": "weekly", "rollup": "sum",
                "target_value": 50000, "tile": "progress",
                "month_targets": REVENUE_BY_MONTH,
                "reading_owner": str(michael.pk), "page": str(weekly.pk),
                "strategy_component": "traction",
                "note": "Invoiced sales for the week, from the accounting system"},
                world.owner),
            "overtime": setup.create_kpi(card, {
                "name": "Overtime hours", "kind": "duration", "duration_unit": "hours",
                "direction": "lower", "cadence": "weekly", "rollup": "sum",
                "target_value": 40, "tile": "status", "audience": "leadership",
                "reading_owner": str(world.owner.pk), "page": str(weekly.pk),
                "strategy_component": "people",
                "note": "Warehouse and driver overtime, from payroll"}, world.owner),
            "calls": setup.create_kpi(card, {
                "name": "Sales calls", "kind": "count", "cadence": "weekly", "rollup": "sum",
                "target_value": 60, "tile": "leaderboard", "per_person": True,
                "leaderboard": True, "people": [str(m) for m in team],
                "reading_owner": str(dwight.pk), "page": str(sales.pk),
                "strategy_component": "traction",
                "note": "Calls logged to customers and prospects, from the phone system"},
                world.owner),
            "rating": setup.create_kpi(card, {
                "name": "Customer rating", "kind": "rating", "rating_scale": 5,
                "cadence": "weekly", "rollup": "average", "target_value": "4.5",
                "tile": "number_trend", "per_person": True, "person_total": "average",
                "audience": "each_person", "people": [str(m) for m in team],
                "reading_owner": str(dwight.pk), "page": str(sales.pk),
                "strategy_component": "people",
                "note": "Average of the week's customer survey scores, by the rep who "
                        "handled the account"}, world.owner),
        }

    starts = P.last_n(world.today, P.WEEKLY, WEEKS + 1, card.week_start)[:-1]
    made = 0

    def enter(kpi, week, value, by, member=None):
        nonlocal made
        when = moment(P.end_of(week, P.WEEKLY) + timedelta(days=1), 9,
                      dice("at", kpi.pk, week).randrange(0, 50))
        with at(when):
            reading = KpiReading.objects.create(
                tenant_id=kpi.tenant_id, kpi=kpi, period_start=week, membership=member,
                value=Decimal(value).quantize(Decimal("0.0001")), entered_by=by,
                entered_at=when)
            KpiReadingChange.objects.create(tenant_id=kpi.tenant_id, reading=reading,
                                            value=reading.value, changed_by=by)
        made += 1
        return reading

    reps = {m.pk: (m, 0.8 + 0.1 * i) for i, m in enumerate(team.values())}
    for i, week in enumerate(starts):
        roll = dice("scorecard", week)
        season = REVENUE_BY_MONTH[week.month]
        lift = i / (WEEKS - 1)                      # things improve as the work lands
        enter(kpis["delivery"], week, round(86 + 9 * lift + roll.uniform(-3, 3), 1), dwight)
        enter(kpis["orders"], week, int(380 + 50 * lift + roll.randrange(-30, 30)), dwight)
        enter(kpis["revenue"], week,
              round(season * (0.9 + 0.12 * lift + roll.uniform(-0.06, 0.06)), -2), michael)
        enter(kpis["overtime"], week, int(52 - 16 * lift + roll.randrange(-4, 5)),
              world.owner)
        for pk, (member, skill) in reps.items():
            rr = dice("rep", pk, week)
            enter(kpis["calls"], week, int(60 * skill + 6 * lift + rr.randrange(-8, 9)),
                  dwight, member)
            if week == starts[-1] and member.user.full_name.startswith("Andy"):
                continue                            # his manager is reminded
            enter(kpis["rating"], week,
                  round(min(5, 3.9 + 0.5 * skill + 0.2 * lift + rr.uniform(-0.2, 0.2)), 1),
                  dwight, member)

    # A correction: last week's orders were first entered short.
    fixed = KpiReading.objects.get(kpi=kpis["orders"], period_start=starts[-1])
    with at(moment(P.end_of(starts[-1], P.WEEKLY) + timedelta(days=1), 14, 10)):
        KpiReadingChange.objects.create(tenant_id=fixed.tenant_id, reading=fixed,
                                        value=fixed.value + 12, previous_value=fixed.value,
                                        changed_by=dwight)
        KpiReading.objects.filter(pk=fixed.pk).update(value=fixed.value + 12, times_changed=1)

    from apps.scorecard import readings
    with at(moment(P.end_of(starts[-1], P.WEEKLY) + timedelta(days=1), 8, 0)):
        readings.remind(world.tenant, P.end_of(starts[-1], P.WEEKLY) + timedelta(days=1))

    return {"scorecard KPIs": Kpi.objects.filter(scorecard=card).count(),
            "scorecard readings": made,
            "scorecard reminders": KpiReminder.objects.filter(kpi__scorecard=card).count(),
            "scorecard team": len(team)}
