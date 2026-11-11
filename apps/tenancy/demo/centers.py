"""The Operations Command Center on the demo (P8): on for the demo
practice, its 90-day operations reset started on Acme Fasteners, and three
KPIs from the library on Acme's scorecard.

Written directly, not through the switch: the switch refuses every change in
the demo (`apps.centers.services.can_switch`), which is what a visitor sees.
The demo practice is the platform owner's there, so nothing is billed.
"""

from __future__ import annotations

from datetime import timedelta

from .clock import at, moment

COMPANY = "Acme Fasteners"
LIBRARY_KPIS = ("on_time_completion", "rework_rate", "ops_first_time_fix")


def operations(world):
    from apps.centers import playbooks
    from apps.centers.models import PracticeCenter
    from apps.scorecard import library, setup

    tenant, owner = world.tenant, world.owner
    company = world.companies[COMPANY]
    started = world.today - timedelta(weeks=3)
    with at(moment(started - timedelta(days=4), 9, 0)):
        PracticeCenter.all_objects.update_or_create(
            tenant=tenant, center="operations",
            defaults={"enabled_at": moment(started - timedelta(days=4), 9, 0),
                      "enabled_by": owner, "disabled_at": None})
        # Library KPIs in use: copied into Acme's scorecard as its own.
        card = setup.ensure(company, owner)
        page = card.pages.order_by("position").first()
        for key in LIBRARY_KPIS:
            fields = library.kpi_fields(library.shipped(key))
            setup.create_kpi(card, {**fields, "page": str(page.pk),
                                    "reading_owner": str(owner.pk)}, owner)
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
    # Three weeks in: what was due is done, but for one thing running late.
    from apps.crm.models import Task
    from apps.work.services import apply_task_changes

    past = list(Task.objects.filter(project__goal=run.goal, due_date__lt=world.today)
                .order_by("due_date", "created_at"))
    for task in past[:-1]:
        with at(moment(task.due_date, 15, 0)):
            apply_task_changes(task, actor=owner, role="FF", changes={"status": "done"})
