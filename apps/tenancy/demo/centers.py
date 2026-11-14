"""The Operations Command Center on the demo (P8): on for the demo
practice, its 90-day operations reset started on Acme Fasteners and first in
Acme's order of goals, and three KPIs from the library on Acme's scorecard,
each with its target and thirteen closed weeks of readings, so every tile
shows a status.

Written directly, not through the switch: the switch refuses every change in
the demo (`apps.centers.services.can_switch`), which is what a visitor sees.
The demo practice is the platform owner's there, so nothing is billed.
"""

from __future__ import annotations

from datetime import timedelta

from .clock import at, moment

COMPANY = "Acme Fasteners"
LIBRARY_KPIS = ("on_time_completion", "rework_rate", "ops_first_time_fix")
#: Each library KPI's target, from its own guidance ("On track at 95% or
#: more"): the library entries carry none, and a tile without a target shows
#: no status (2026-11-12).
TARGETS = {"on_time_completion": 95, "rework_rate": 3, "ops_first_time_fix": 90}
#: Thirteen closed weeks of each, oldest first: flat before the reset, then
#: moving as its first three weeks land. On-time ends Behind (93% against 95,
#: within 5%), rework On track (2.8% against 3 or less), first-time fix On
#: track (91% against 90).
WEEKS = 13
READINGS = {
    "on_time_completion": [82, 81, 83, 82, 84, 83, 82, 84, 83, 85, 88, 91, 93],
    "rework_rate": [6.4, 6.1, 6.6, 6.2, 5.9, 6.3, 6.0, 5.8, 6.1, 5.2, 4.1, 3.3, 2.8],
    "ops_first_time_fix": [80, 82, 81, 79, 82, 81, 83, 82, 84, 85, 87, 89, 91],
}


def operations(world):
    from apps.centers import playbooks
    from apps.centers.models import PracticeCenter
    from apps.scorecard import library, setup

    tenant, owner = world.tenant, world.owner
    company = world.companies[COMPANY]
    started = world.today - timedelta(weeks=3)
    kpis = {}
    with at(moment(started - timedelta(days=4), 9, 0)):
        PracticeCenter.all_objects.update_or_create(
            tenant=tenant, center="operations",
            defaults={"enabled_at": moment(started - timedelta(days=4), 9, 0),
                      "enabled_by": owner, "disabled_at": None})
        # Library KPIs in use: copied into Acme's scorecard as its own, each
        # with the target its guidance names.
        card = setup.ensure(company, owner)
        page = card.pages.order_by("position").first()
        for key in LIBRARY_KPIS:
            fields = library.kpi_fields(library.shipped(key))
            kpis[key] = setup.create_kpi(card, {**fields, "target_value": TARGETS[key],
                                                "page": str(page.pk),
                                                "reading_owner": str(owner.pk)}, owner)
    _readings(world, kpis, added=moment(started - timedelta(days=4), 9, 30))
    # The reset, made ready and started on a Monday three weeks back.
    monday = started - timedelta(days=started.weekday())
    with at(moment(monday - timedelta(days=1), 16, 0)):
        playbook = playbooks.copy_shipped(tenant, "ops_90_day_reset", actor=owner)
        playbooks.save(playbook, ready=True, actor=owner)
        people = world.people.get(COMPANY) or []
        run = playbooks.start(playbook, company=company, start_date=monday, lead=owner,
                              owner_contact=people[0] if people else None,
                              second_contact=people[1] if len(people) > 1 else None,
                              actor=owner, role="FF")
        # The engagement's focus now, so Acme's first goal on Work and in the
        # portal (2026-11-12): a started playbook's goal comes after the ones
        # made before it, and the reset was fourth, far down both pages.
        from apps.work import goal_order

        rest = [str(g.pk) for g in goal_order.current_goals(company) if g.pk != run.goal_id]
        goal_order.set_order(company, [str(run.goal_id), *rest], actor=owner)
    # Three weeks in: what was due is done, but for one thing running late.
    # The late one is the last thing due **before this week**, so last week's
    # sprint closes with it carried over whatever day the seed runs: when it
    # was simply the last thing due before today, a seed run late in the week
    # put it in this week and last week closed with nothing carried (seen on a
    # Saturday, 2026-11-14 UTC).
    from apps.crm.models import Task
    from apps.plans import periods as P
    from apps.work.services import apply_task_changes

    this_week = P.start_of("week", world.today, company)
    past = list(Task.objects.filter(project__goal=run.goal, due_date__lt=world.today)
                .order_by("due_date", "created_at"))
    before = [t for t in past if t.due_date < this_week]
    late = before[-1] if before else (past[-1] if past else None)
    for task in past:
        if task is late:
            continue
        with at(moment(task.due_date, 15, 0)):
            apply_task_changes(task, actor=owner, role="FF", changes={"status": "done"})


def _readings(world, kpis, *, added):
    """Thirteen closed weeks of each library KPI (2026-11-12): the weeks
    before it was added back-filled from Acme's job log when it was, each
    later week entered the morning after it closed, by the owner, through the
    scorecard's own models as `scorecard.operations` enters scrap."""
    from decimal import Decimal

    from apps.scorecard import periods as P
    from apps.scorecard.models import KpiReading, KpiReadingChange

    last = P.previous_start(P.start_of(world.today, P.WEEKLY), P.WEEKLY)
    weeks = P.last_n(last, P.WEEKLY, WEEKS)
    for key, kpi in kpis.items():
        for week, value in zip(weeks, READINGS[key]):
            closed_on = moment(P.end_of(week, P.WEEKLY) + timedelta(days=1), 9, 10)
            when = max(closed_on, added)
            with at(when):
                reading = KpiReading.objects.create(
                    tenant_id=kpi.tenant_id, kpi=kpi, period_start=week,
                    value=Decimal(str(value)), entered_by=world.owner, entered_at=when)
                KpiReadingChange.objects.create(tenant_id=kpi.tenant_id, reading=reading,
                                                value=reading.value, changed_by=world.owner)
