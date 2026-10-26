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
reminder waiting. Overtime fell as the work landed and crept back up the last
three weeks, Off track each, so its tile offers a task; the "Deliver the next
day" goal shows On-time delivery on its card (M5 ties).

Part 2 adds Revenue per order (Revenue ÷ Orders shipped, computed), each
rep's Sales booked, and the **Sales floor bonus**: $600 a month on Sales
booked, Sales calls and Customer rating, with the three months before this
one closed (Andy joined part-way through the first, so it is prorated), and
this month's copied forward from the last. The readings start in the first
of those months, so every closed month is worked out from real readings.
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
#: Closed months of bonus history before this one.
BONUS_MONTHS = 3

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
    first_month = world.today.replace(day=1)
    for _ in range(BONUS_MONTHS):
        first_month = P.previous_start(first_month, P.MONTHLY)
    starts = P.starts_between(first_month, world.today, P.WEEKLY)
    starts = [w for w in starts if P.closed(w, P.WEEKLY, world.today)]
    start = starts[0] - timedelta(days=14)

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
            "booked": setup.create_kpi(card, {
                "name": "Sales booked", "kind": "money", "cadence": "weekly", "rollup": "sum",
                "target_value": 11000, "tile": "my_row", "per_person": True,
                "audience": "each_person", "people": [str(m) for m in team],
                "reading_owner": str(dwight.pk), "page": str(sales.pk),
                "strategy_component": "traction",
                "note": "Orders each rep booked in the week, from the order system"},
                world.owner),
        }
        kpis["per_order"] = setup.create_kpi(card, {
            "name": "Revenue per order", "kind": "money", "cadence": "weekly",
            "rollup": "average", "target_value": 125, "tile": "number_trend",
            "formula": "ratio", "source_a": str(kpis["revenue"].pk),
            "source_b": str(kpis["orders"].pk), "page": str(weekly.pk),
            "strategy_component": "traction",
            "note": "Revenue ÷ orders shipped, worked out each week"}, world.owner)

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
        lift = i / (len(starts) - 1)                # things improve as the work lands
        enter(kpis["delivery"], week, round(86 + 9 * lift + roll.uniform(-3, 3), 1), dwight)
        enter(kpis["orders"], week, int(380 + 50 * lift + roll.randrange(-30, 30)), dwight)
        enter(kpis["revenue"], week,
              round(season * (0.9 + 0.12 * lift + roll.uniform(-0.06, 0.06)), -2), michael)
        # The fall rush: overtime fell as the work landed, then crept back up
        # the last three weeks, Off track each, so the tile offers a task.
        late = i - (len(starts) - 3)
        enter(kpis["overtime"], week, 46 + 2 * late + roll.randrange(0, 2) if late >= 0
              else int(52 - 16 * lift + roll.randrange(-4, 5)), world.owner)
        for pk, (member, skill) in reps.items():
            rr = dice("rep", pk, week)
            enter(kpis["calls"], week, int(60 * skill + 6 * lift + rr.randrange(-8, 9)),
                  dwight, member)
            enter(kpis["booked"], week,
                  round(season / 5 * (0.78 + 0.25 * skill + 0.1 * lift + rr.uniform(-0.12, 0.12)),
                        -1), dwight, member)
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

    plans = bonus_plans(world, card, kpis, team, starts)

    # M5 ties: the next-day delivery goal shows its KPI on its card.
    from apps.work.models import Goal

    Goal.objects.filter(client_company=company, title="Deliver the next day").update(
        kpi=kpis["delivery"])
    scorecard_digest = _scorecard_digest(world, company, owner_member)
    _review_session(world, company, owner_member, kpis)

    # Part 3: orders arrive from the warehouse's sheet. The demo never reads
    # Google (and has no worker), so the feed is shown, not run: its readings
    # are marked as the sheet's, and last week's correction stays by hand.
    from apps.scorecard.models import KpiFeed

    KpiFeed.objects.create(
        tenant=world.tenant, kpi=kpis["orders"], spreadsheet_id="demo-warehouse-log",
        spreadsheet_name="Warehouse log", tab="Weekly", mode="column", refresh="hourly",
        date_column="A", date_header="Week of", value_column="C",
        value_header="Orders shipped", header_row=2, last_run_at=moment(world.today, 7, 0),
        last_success_at=moment(world.today, 7, 0))
    Kpi.objects.filter(pk=kpis["orders"].pk).update(feed=Kpi.Feed.SHEET)
    KpiReading.objects.filter(kpi=kpis["orders"]).exclude(pk=fixed.pk).update(
        source=KpiReading.Source.SHEET, entered_by=None)

    return {"bonus plans": plans,
            "scorecard KPIs": Kpi.objects.filter(scorecard=card).count(),
            "scorecard readings": made,
            "scorecard reminders": KpiReminder.objects.filter(kpi__scorecard=card).count(),
            "scorecard team": len(team),
            "scorecard digest waiting": scorecard_digest}


def _review_session(world, company, owner_member, kpis) -> None:
    """Dunder Mifflin's quarterly review, held last week: three moves on the
    map, two naming the KPI they're meant to move, so a visitor sees "KPI it
    moves" (owner, 2026-10-26). Made after the scorecard, whose KPIs it names."""
    from apps.strategy.models import StrategyMapRow, StrategySession

    from .sessions import _start, _state

    template = (world.extra.get("templates") or [None])[0]
    contact = owner_member.contact
    if template is None or contact is None:
        return
    began = moment(world.today - timedelta(days=6), 14, 0)
    with at(began - timedelta(days=6)):
        call = _start(world, contact, template, began)
    with at(began + timedelta(minutes=55)):
        _state(call.session, StrategySession.State.COMPLETE, started_at=began,
               current_section="strategy_map",
               current_section_at=began + timedelta(minutes=25))
        accepted = StrategyMapRow.State.ACCEPTED
        call.row(0, "Overtime back under 40",
                 "Overtime crept back up with the fall rush; the warehouse needs a second "
                 "shift lead before November.", "Darryl", 30, "Overtime hours a week",
                 accepted, kpi=kpis["overtime"])
        call.row(1, "Every order on the morning truck",
                 "On-time delivery is a point short of target; the late ones are the "
                 "orders entered after 3.", "Dwight", 60, "On-time delivery",
                 accepted, kpi=kpis["delivery"])
        call.row(2, "A second supplier for cardstock",
                 "One supplier for cardstock has stopped two weeks of orders this year.",
                 "Michael", 90, "Weeks short of cardstock", accepted)


def _scorecard_digest(world, company, owner_member) -> int:
    """M5 ties: Michael's weekly digest, drafted once the scorecard exists, so
    a visitor sees its Scorecard section on Digests. The news in it is the
    Friday late-delivery review's first result."""
    from django.utils import timezone

    from apps.crm.models import Task
    from apps.work import digests, services as work
    from apps.work.models import Cadence, Goal, Stakeholder

    goal = Goal.objects.filter(client_company=company, title="Deliver the next day").first()
    contact = owner_member.contact
    task = Task.objects.filter(project__goal=goal, title="Review late deliveries every Friday",
                               deleted_at__isnull=True).first() if goal else None
    if goal is None or contact is None or task is None:
        return 0
    now = timezone.now()
    with at(now - timedelta(days=8)):
        if not Stakeholder.objects.filter(contact=contact, goal=goal).exists():
            Stakeholder.objects.create(tenant=world.tenant, contact=contact, goal=goal,
                                       cadence=Cadence.WEEKLY)
    with at(now - timedelta(hours=2)):
        work.add_narrative(task, actor=world.owner, role="FF",
                           line="The first Friday review found two routes running late; "
                                "both are redrawn for next week.")
    window = digests.next_window(world.tenant, Cadence.WEEKLY, now)
    start, end = digests.period_for(world.tenant, Cadence.WEEKLY, window)
    made = digests.generate(tenant=world.tenant, contact=contact, cadence=Cadence.WEEKLY,
                            period_start=start, period_end=end, send_window_at=window,
                            until=now)
    if made is not None and made.state in digests.UNSENT_DRAFTS \
            and "Scorecard" not in made.body_text:
        made = digests.regenerate(made)              # drafted before the scorecard was
    return int(made is not None)


def bonus_plans(world, card, kpis, team, starts) -> int:
    """The Sales floor bonus, month by month: made for the first month, each
    closed the morning after its last day and copied forward, so this month's
    is the copy of the last. Andy joined the first month's plan part-way."""
    from apps.scorecard import bonus
    from apps.scorecard import periods as P

    from .clock import at, moment

    andy = next(m for m in team.values() if m.user.full_name.startswith("Andy"))
    month = world.today.replace(day=1)
    for _ in range(BONUS_MONTHS):
        month = P.previous_start(month, P.MONTHLY)
    joined = month + timedelta(days=11)
    with at(moment(month, 8, 0)):
        plan = bonus.create_plan(card, {
            "name": "Sales floor bonus", "period": "monthly",
            "period_start": month.isoformat(), "amount": 600,
            "components": [
                {"kpi": str(kpis["booked"].pk), "weight": 40},
                {"kpi": str(kpis["calls"].pk), "weight": 30},
                {"kpi": str(kpis["rating"].pk), "weight": 30,
                 "tiers": [{"from": 0, "share": 0}, {"from": 90, "share": 50},
                           {"from": 100, "share": 100}, {"from": 105, "share": 120}]}],
            "people": [{"membership": str(m.pk),
                        **({"joined_on": joined.isoformat()} if m.pk == andy.pk else {})}
                       for m in team.values()]}, world.owner)
    made = 1
    while P.end_of(plan.period_start, P.MONTHLY) < world.today:
        # Closed once the last week starting in the month has closed too.
        last_week = [w for w in P.starts_between(plan.period_start, P.end_of(
            plan.period_start, P.MONTHLY), P.WEEKLY) if w >= plan.period_start][-1]
        close_on = P.end_of(last_week, P.WEEKLY) + timedelta(days=1)
        with at(moment(min(close_on, world.today), 10, 0)):
            if close_on <= world.today:
                bonus.close(plan, world.owner, close_on)
            plan = bonus.copy_forward(plan, world.owner)
        made += 1
    return made
