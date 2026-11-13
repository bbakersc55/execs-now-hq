"""The demo's plans (P11, docs/p11_plans_engine.md, "The demo"). No Claude:
every item is written here as a person would have typed it.

**Acme Fasteners**, a full plan tied to the 90-day operations reset (started
three weeks ago, `centers.operations`) and its scorecard:

- the three-year picture: two statements and two measurable targets, read
  against Scrap rate and On-time completion rate;
- the year: the reset's goal (put there when the playbook started) and two
  of Acme's own goals, linked;
- the quarter: three priorities, one per stage of the reset still to come,
  each linking its project and serving the reset's goal, and a priority
  Wiley proposed, waiting for the practice;
- the month: three items, one off track (on-time completion is behind);
- last week's sprint, closed on Monday: its tasks done but the last, which
  was carried over;
- this week's sprint under way, with this week's reset tasks and the one
  carried over.

**Summit itself**, a short plan: a picture, two goals for the year (the
practice's own), a quarter's priority and a month's item.
"""

from __future__ import annotations

from datetime import timedelta

from .clock import at, moment

ACME = "Acme Fasteners"


def _add(company, horizon, start, title, *, actor, **fields):
    from apps.plans.models import PlanItem

    from apps.plans.services import _next_position

    return PlanItem.objects.create(
        tenant_id=company.tenant_id, company=company, horizon=horizon, period_start=start,
        title=title, created_by=actor, position=_next_position(company, horizon, start),
        **fields)


def _link(item, *, tasks=(), kpis=()):
    from apps.plans.models import PlanItemKpi, PlanItemTask

    for i, task in enumerate(tasks):
        PlanItemTask.objects.get_or_create(tenant_id=item.tenant_id, item=item, task=task,
                                           defaults={"position": i})
    for kpi in kpis:
        PlanItemKpi.objects.get_or_create(tenant_id=item.tenant_id, item=item, kpi=kpi)


def acme(world) -> dict:
    from apps.centers.models import PlaybookRun
    from apps.crm.models import Task
    from apps.plans import periods as P
    from apps.plans import services
    from apps.plans.models import PlanItem
    from apps.scorecard.models import Kpi
    from apps.work.models import Goal, Project

    company = world.companies[ACME]
    owner = world.owner
    wiley, marvin = world.portal[ACME][0], world.portal[ACME][1]
    today = world.today
    run = PlaybookRun.objects.filter(company=company).select_related("goal").get()
    reset = run.goal
    projects = {p.title: p for p in Project.objects.filter(goal=reset)}
    kpis = {k.name: k for k in Kpi.objects.filter(scorecard__company=company,
                                                  archived_at__isnull=True)}
    scrap, on_time = kpis["Scrap rate"], kpis["On-time completion rate"]
    first_fix = kpis.get("First-time fix rate")
    goals = {g.title: g for g in Goal.objects.filter(client_company=company)}
    year = P.start_of("year", today, company)
    quarter = P.start_of("quarter", today, company)
    month = P.start_of("month", today, company)
    week = P.start_of("week", today, company)
    last = week - timedelta(days=7)
    written = moment(run.start_date - timedelta(days=1), 17, 0)

    with at(written):
        # The picture: where Acme will be in three years.
        _add(company, "picture", year, "Acme ships every order complete and on time, without "
             "Wiley in the building", actor=owner, owner=wiley.user,
             done_means="A month of shipping with Wiley away and nothing late")
        _add(company, "picture", year, "A second shift with its own supervisor, running the "
             "same standard work", actor=owner, owner=wiley.user,
             done_means="The night shift's numbers match the day shift's for a quarter")
        target = _add(company, "picture", year, "Scrap under 2% on every line", actor=owner,
                      target_value=2, done_means="Twelve weeks in a row under 2%")
        _link(target, kpis=[scrap])
        target = _add(company, "picture", year, "On-time completion at 98%", actor=owner,
                      target_value=98, done_means="A quarter at 98% or better")
        _link(target, kpis=[on_time])

        # The year: the reset's goal is already there (the playbook put it
        # there); two of Acme's own goals beside it, each serving the picture.
        picture = {i.title: i for i in PlanItem.objects.filter(company=company,
                                                               horizon="picture")}
        reset_item = PlanItem.objects.get(company=company, horizon="year", goal=reset)
        PlanItem.objects.filter(pk=reset_item.pk).update(
            parent=picture["Acme ships every order complete and on time, without Wiley in "
                           "the building"],
            done_means="Weekly meeting running, top two bottlenecks fixed, the floor handed "
                       "to Marvin")
        cut = goals.get("Cut scrap on the header line")
        ship = goals.get("Ship on time, every time")
        if cut is not None:
            item = services.put_goal_on_year(company, cut, actor=owner, day=today,
                                             source="hand")
            PlanItem.objects.filter(pk=item.pk).update(
                parent=picture["Scrap under 2% on every line"],
                done_means="Header line scrap under 3% by year end")
            _link(item, kpis=[scrap])
        if ship is not None:
            item = services.put_goal_on_year(company, ship, actor=owner, day=today,
                                             source="hand")
            PlanItem.objects.filter(pk=item.pk).update(
                parent=picture["On-time completion at 98%"],
                done_means="On-time completion at 95% every week")
            _link(item, kpis=[on_time])

    with at(moment(run.start_date, 9, 0)):
        # The quarter: the reset's stages still to come.
        cadence = _add(company, "quarter", quarter, "Run the weekly operations meeting every "
                       "week, to the agenda", actor=owner, owner=marvin.user, parent=reset_item,
                       goal=reset, project=projects.get("Cadence"),
                       done_means="Eight meetings in a row, actions tracked to done")
        _link(cadence, kpis=[on_time])
        bottlenecks = _add(company, "quarter", quarter, "Fix the top two bottlenecks: press "
                           "line scrap and slow changeovers", actor=owner, owner=owner,
                           parent=reset_item, goal=reset,
                           project=projects.get("Fix the top two bottlenecks"),
                           done_means="Scrap under 3% and changeovers under 40 minutes")
        _link(bottlenecks, kpis=[scrap] + ([first_fix] if first_fix else []))
        _add(company, "quarter", quarter, "Hand the floor to Marvin", actor=owner,
                        owner=marvin.user, parent=reset_item, goal=reset,
                        project=projects.get("Handover"),
                        done_means="Marvin runs two weeks of the meeting with Wiley away")
        # Wiley's own idea, waiting for the practice.
        _add(company, "quarter", quarter, "Start hiring for a second shift", actor=wiley.user,
             state=PlanItem.State.PROPOSED, source=PlanItem.Source.CLIENT,
             proposed_by=wiley.user, done_means="A supervisor and two operators hired")

        # The month.
        meetings = _add(company, "month", month, "Hold four weekly operations meetings",
                        actor=owner, owner=marvin.user, parent=cadence,
                        done_means="Four meetings held, each with its actions written down")
        by_shift = _add(company, "month", month, "Measure scrap by shift and by press",
                        actor=owner, owner=marvin.user, parent=bottlenecks,
                        done_means="A week of scrap tags sorted by shift and press")
        _link(by_shift, kpis=[scrap])
        late = _add(company, "month", month, "On-time completion back over 95%", actor=owner,
                    owner=owner, parent=cadence, status=PlanItem.Status.OFF_TRACK,
                    done_means="Two weeks in a row at 95% or better")
        _link(late, kpis=[on_time])

    reset_tasks = list(Task.objects.filter(project__goal=reset, deleted_at__isnull=True)
                       .order_by("due_date", "created_at"))
    last_tasks = [t for t in reset_tasks if t.due_date and last <= t.due_date <= last + timedelta(days=6)]
    this_tasks = [t for t in reset_tasks if t.due_date and week <= t.due_date <= week + timedelta(days=6)]
    with at(moment(last, 8, 30)):
        last_sprint = _add(company, "week", last, "Write the agenda and hold the first "
                           "weekly meeting", actor=owner, owner=marvin.user, parent=meetings,
                           done_means="The first meeting held to the new agenda")
        _link(last_sprint, tasks=last_tasks)
    with at(moment(week, 8, 30)):
        # Marvin's own part of the week: what his This week opens with.
        from apps.work import services as work

        tags = work.create_task(
            tenant=world.tenant, actor=owner, role="FF",
            title="Sort a day of scrap tags by shift and press", client_company=company,
            project=projects.get("Fix the top two bottlenecks"), owner=owner,
            assignee=marvin.user, client_owner_contact=world.people[ACME][1],
            due_date=week + timedelta(days=4))
        _link(by_shift, tasks=[tags])
        sprint = _add(company, "week", week, "Run the second weekly meeting and start "
                      "measuring scrap by shift", actor=owner, owner=marvin.user,
                      parent=meetings,
                      done_means="Meeting held; a first day of scrap tags sorted by shift")
        _link(sprint, tasks=[*this_tasks, tags])
    with at(moment(week, 9, 15)):
        # Last week closed on Monday morning: its tasks done but one, carried over.
        open_ones = {str(t.pk): "carried" for t in last_tasks if t.status != Task.Status.DONE}
        closed = services.close(company, "week", last, open_ones, actor=owner) \
            if last_tasks else None
    return {"acme plan items": PlanItem.objects.filter(company=company).count(),
            "acme sprint tasks": len(this_tasks) + 1 + len(open_ones if last_tasks else {}),
            "acme last week": closed.summary if closed else ""}


def summit(world) -> dict:
    from apps.plans import periods as P
    from apps.plans.models import PlanItem
    from apps.scorecard.practice import practice_company
    from apps.work.models import Goal

    company = practice_company(world.tenant)
    owner = world.owner
    today = world.today
    year = P.start_of("year", today, company)
    with at(moment(year + timedelta(days=6), 9, 0)):
        picture = _add(company, "picture", year, "Twelve clients on retainer, each opening "
                       "its plan every Monday", actor=owner, owner=owner,
                       done_means="Twelve retainers, every one with a sprint set each week")
        goals = []
        for title, done in (("Sign four new retainer clients", "Four signed engagements"),
                            ("Run every client's plan from the app",
                             "Every client's week closed in the app for a month")):
            goal = Goal.objects.create(tenant=world.tenant, client_company=None, owner=owner,
                                       title=title, target_date=P.end_of("year", year))
            goals.append(_add(company, "year", year, title, actor=owner, owner=owner,
                              goal=goal, parent=picture, done_means=done))
    quarter = P.start_of("quarter", today, company)
    month = P.start_of("month", today, company)
    with at(moment(quarter + timedelta(days=2), 9, 0)):
        priority = _add(company, "quarter", quarter, "Put Acme, Wayne and Stark on the "
                        "five-horizon plan", actor=owner, owner=owner, parent=goals[1],
                        done_means="Each closes a week in the app")
    with at(moment(month, 9, 0)):
        _add(company, "month", month, "Close Acme's week every Monday morning", actor=owner,
             owner=owner, parent=priority, done_means="Four Mondays closed this month")
    return {"summit plan items": PlanItem.objects.filter(company=company).count()}


def plans(world) -> dict:
    return {**acme(world), **summit(world)}
