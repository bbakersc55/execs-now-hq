"""The clients' work: goals with readings and milestones, projects, tasks in
every status, comments, stakeholders, and the digests that came of it.

Each task is created, started and finished through `apps.work.services` on
the day it happened, so every one has its own history of updates, and the
weekly digests of the last several weeks are generated, approved and sent
from those updates by `apps.work.digests`, as a real practice's would be.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from . import goals as content
from .clock import at, dice, moment, workday

#: Lines written on work still under way.
UNDERWAY = [
    "First draft is with {first} for comment.",
    "Tried on one line this week and it held. Wider next week.",
    "Two of the three pieces are in place; the last needs a decision from {first}.",
    "The first week of numbers is in, and they are moving the right way.",
    "Walked it with the team on Tuesday. Two changes, both small.",
    "On track. Nothing needed from you this week.",
]
#: Whose recent work makes the digests that are waiting for approval.
WAITING_WEEKLY = ("Acme Fasteners", "Stark Tool & Die")
EVERY_UPDATE = (("Wayne Industries", 1), ("Pied Piper Compression", 1))


def engagements(world) -> None:
    built = [_goal(world, index, spec) for index, spec in enumerate(content.GOALS)]
    world.extra["goals"] = built
    _conversation(world, built)
    _client_tasks(world, built)
    _proposals(world, built)
    _internal(world)
    _digests(world, built)


def _months_after(day: date, n: int) -> date:
    month = day.month - 1 + n
    return date(day.year + month // 12, month % 12 + 1, 1)


def _role(world, user) -> str:
    return "FF" if user.pk == world.owner.pk else "CF"


#: Things that are counted, so a reading of them is a whole number.
COUNTED = ("sites", "incidents", "shipments", "findings", "decisions", "reports")


def _shown(value: float, spec) -> Decimal:
    fine = spec["unit"] not in COUNTED and (
        isinstance(spec["baseline"], float) or abs(spec["target"] - spec["baseline"]) < 12)
    return Decimal(str(round(value, 1) if fine else int(round(value))))


# ------------------------------------------------------------------- a goal

def _goal(world, index: int, spec: dict) -> dict:
    from apps.tenancy.models import AuditEvent
    from apps.work import services as work
    from apps.work.models import (
        Cadence, Goal, GoalMeasurement, GoalMilestone, GoalResolution, Project, Stakeholder,
    )

    name, today, tenant = spec["company"], world.today, world.tenant
    company, people, lead = world.companies[name], world.people[name], world.lead[name]
    role, roll = _role(world, lead), dice("goal", name, spec["title"])
    started = min(_months_after(world.start[name], spec["after"]),
                  today - timedelta(days=45)) + timedelta(days=roll.randrange(2, 9))
    resolved = spec.get("resolved")
    end = today - timedelta(days=74 if resolved and resolved[0] == "achieved" else 48) \
        if resolved else today
    lived = max((end - started).days, 30)
    # How long the goal was given: in proportion to how far it has come, and
    # never more than eight months still to run.
    whole = lived if resolved else min(
        int(lived / min(max(spec["progress"], 0.3), 0.97)) + 6, lived + 240)
    good = Goal.Direction.UP_IS_GOOD if spec["good"] == "up" else Goal.Direction.DOWN_IS_GOOD

    fields = dict(
        owner=lead, client_owner_contact=people[0],
        target_date=started + timedelta(days=whole), measurable=spec["measurable"],
        measurable_unit=spec["unit"], measurable_kind=Goal.MeasurableKind.NUMERIC,
        baseline_value=Decimal(str(spec["baseline"])), baseline_at=started,
        target_value=Decimal(str(spec["target"])), direction=good, horizon_days=90,
        how_we_will_know=f"{spec['measurable']} reaches {spec['target']:g} "
                         f"{spec['unit']}, and stays there for a month.")
    # A goal that came out of a converted strategy session is already here:
    # the work carries on from the row it was made from.
    goal = Goal.objects.filter(client_company=company, title=spec["title"]).first()
    with at(started):
        if goal is None:
            goal = Goal.objects.create(tenant=tenant, title=spec["title"],
                                       client_company=company, **fields)
        else:
            Goal.objects.filter(pk=goal.pk).update(**fields)
            goal.refresh_from_db()
        Stakeholder.objects.create(tenant=tenant, contact=people[0], goal=goal,
                                   cadence=Cadence.WEEKLY)

    # Readings: one a month, from the baseline towards the target, as far as
    # the goal has come, with the wobble real numbers have.
    span = spec["target"] - spec["baseline"]
    days = list(range(30, lived + 1, 30))
    for step, offset in enumerate(days, start=1):
        along = spec["progress"] * (step / len(days)) ** 0.8
        value = spec["baseline"] + span * along + span * roll.uniform(-0.035, 0.035)
        if step == len(days):
            value = spec["baseline"] + span * spec["progress"]
        on = started + timedelta(days=offset)
        with at(moment(on, 16)):
            GoalMeasurement.objects.create(tenant=tenant, goal=goal, recorded_by=lead,
                                           value=_shown(value, spec), measured_at=on)

    # Projects and their tasks.
    tasks, projects = [], []
    late = {"wanted": bool(spec.get("overdue"))}
    for p_index, (p_title, rows) in enumerate(spec["projects"]):
        p_start = started + timedelta(days=int(lived * 0.22 * p_index) + 3)
        p_fields = dict(goal=goal, owner=lead, start_date=p_start,
                        target_date=started + timedelta(
                            days=int(whole * (0.5 + 0.45 * p_index))))
        project = Project.objects.filter(client_company=company, title=p_title).first()
        with at(p_start):
            if project is None:
                project = Project.objects.create(tenant=tenant, title=p_title,
                                                 client_company=company, **p_fields)
            else:
                Project.objects.filter(pk=project.pk).update(**p_fields)
                project.refresh_from_db()
        projects.append(project)
        done_rows = [row for row in rows if row[1]]
        for t_index, (title, line) in enumerate(rows):
            tasks.append(_task(world, spec, goal, project, p_start, end, lead, role, people,
                               title, line, t_index, len(done_rows), roll,
                               resolved=resolved, order=len(tasks), index=index,
                               late=late))

    # Milestones: four on the calendar, and one that is a finished task.
    reached = started + timedelta(days=int(whole * min(spec["progress"] + 0.04, 1.0)))
    for position, (pattern, share) in enumerate(content.MILESTONES):
        due = started + timedelta(days=int(whole * share))
        occurred = None
        if due <= min(reached, end - timedelta(days=3)) or (resolved and share < 1.0) \
                or (resolved and resolved[0] == "achieved"):
            occurred = min(due + timedelta(days=roll.randrange(-6, 3)), end)
            if position == 2 and index % 3 == 0:
                occurred = min(due + timedelta(days=17), end)     # this one came late
        with at(started + timedelta(days=1)):
            GoalMilestone.objects.create(
                tenant=tenant, goal=goal, position=position, due_date=due,
                occurred_at=occurred,
                title=pattern.format(first=spec["projects"][0][0],
                                     second=spec["projects"][1][0]))
    finished = [t for t in tasks if t.status == "done"]
    if index % 2 == 0 and len(finished) >= 2:
        GoalMilestone.objects.create(tenant=tenant, goal=goal, position=4,
                                     source_task=finished[1], title=finished[1].title)

    def resolve(kind, reason, on):
        with at(moment(on, 15, 30)):
            GoalResolution.objects.create(tenant=tenant, goal=goal, resolution=kind,
                                          reason=reason, resolved_by=world.owner,
                                          resolved_at=moment(on, 15, 30))
            AuditEvent.all_objects.create(tenant=tenant, actor=world.owner,
                                          verb="goal.resolved", target_type="goal",
                                          target_id=goal.pk, payload={"resolution": kind})

    if resolved:
        resolve(resolved[0], resolved[1], end)
    if spec.get("paused"):
        resolve("paused", "Wiley asked to stop while the plant got through its busiest "
                          "quarter. Nothing is lost; the handover sheet stays in use.",
                today - timedelta(days=150))
        resolve("resumed", "The busy quarter is over and the second-shift lead has been "
                           "named. Picking up where we stopped.", today - timedelta(days=82))
    return {"goal": goal, "spec": spec, "tasks": tasks, "projects": projects,
            "company": name, "lead": lead}


def _task(world, spec, goal, project, p_start, end, lead, role, people, title, line,
          t_index, done_in_project, roll, *, resolved, order, index, late):
    from apps.work import services as work

    today, tenant, company = world.today, world.tenant, goal.client_company
    created = min(p_start + timedelta(days=t_index * 2), today)
    with at(created):
        task = work.create_task(tenant=tenant, actor=lead, role=role, title=title,
                                project=project, client_company=company, owner=lead,
                                priority=2 if t_index == 0 else 1)

    def change(on, changes, said=""):
        with at(moment(min(on, today), 11 + t_index % 5, 10 * (order % 6))):
            work.apply_task_changes(task, actor=lead, role=role, changes=changes,
                                    client_facing_line=said)

    if line:
        # Finished: spread through the project's life, the last of them recent.
        share = (t_index + 1) / (done_in_project + 0.3)
        done_on = workday(p_start + timedelta(days=int(((end - p_start).days - 2) * share)))
        done_on = min(done_on, end - timedelta(days=1 + (order % 3)))
        due = done_on + timedelta(days=roll.choice([-3, 0, 1, 2, 2, 4, 5]))
        change(max(created, done_on - timedelta(days=roll.randrange(6, 15))),
               {"status": "in_progress", "due_date": due})
        change(done_on, {"status": "done"}, line)
        return task

    waits_on = next((p for p in people if title.startswith(f"{p.first_name} to ")), None)
    first_open = t_index == done_in_project
    if resolved and resolved[0] == "changed_course":
        change(end, {"status": "cancelled"})
    elif waits_on is not None:
        change(today - timedelta(days=roll.randrange(4, 12)),
               {"status": "waiting_on_client", "client_owner_contact": waits_on,
                "due_date": today + timedelta(days=roll.randrange(2, 12))},
               f"Waiting on {waits_on.first_name}: {title[len(waits_on.first_name) + 4:]}.")
    elif first_open:
        # The goal's first open task is the late one, where the goal has one.
        is_late, late["wanted"] = late["wanted"], False
        due = today - timedelta(days=roll.randrange(3, 10)) if is_late \
            else today + timedelta(days=roll.randrange(1, 7))
        change(today - timedelta(days=roll.randrange(9, 20)),
               {"status": "in_progress", "due_date": due})
        said = roll.choice(UNDERWAY).format(first=people[-1].first_name)
        with at(moment(today - timedelta(days=roll.randrange(3, 9)), 15, 20)):
            work.add_narrative(task, actor=lead, role=role, line=said)
    elif index % 4 == 1 and t_index == done_in_project + 1:
        change(today - timedelta(days=roll.randrange(2, 8)),
               {"status": "blocked", "due_date": today + timedelta(days=roll.randrange(5, 15))},
               "Blocked until the step before it is finished.")
    else:
        change(created, {"due_date": today + timedelta(days=8 + 9 * (t_index + order % 3))})
    task.refresh_from_db()
    return task


# -------------------------------------------------- what people said about it

def _conversation(world, built) -> None:
    """A few comments on the work under way: the practice's own notes, what
    it said to the client, and what the client said back."""
    from apps.work import services as work
    from apps.work.models import Comment

    seen = set()
    for item in built:
        name = item["company"]
        if name in seen:
            continue
        seen.add(name)
        open_tasks = [t for t in item["tasks"] if t.status in ("in_progress",
                                                               "waiting_on_client")]
        if not open_tasks:
            continue
        task, lead = open_tasks[0], item["lead"]
        role = _role(world, lead)
        first = world.people[name][0].first_name
        with at(moment(world.today - timedelta(days=6), 9, 30)):
            work.add_comment(task, author=lead, role=role, visibility=Comment.Visibility.INTERNAL,
                             body=f"{first} tends to agree in the room and change it later. "
                                  "Get this one in writing.")
        if len(seen) % 2:
            with at(moment(world.today - timedelta(days=4), 14)):
                work.add_comment(task, author=lead, role=role,
                                 visibility=Comment.Visibility.SHARED,
                                 body="Draft attached to Tuesday's notes. Tell me what is "
                                      "wrong with it; it is easier to fix now than later.")
            member = next((m for m in world.portal[name] if m.user.last_login_at), None)
            if member is not None:
                with at(moment(world.today - timedelta(days=3), 8, 15)):
                    work.add_comment(task, author=member.user, role=member.role,
                                     body="Read it. The second step will not work on the "
                                          "night shift; they have no supervisor after ten. "
                                          "Otherwise good.")


def _client_tasks(world, built) -> None:
    """Clients use it as their own task tool too."""
    from apps.work import services as work

    asked = {"Wayne Industries": "Send Summit the overtime report for all four sites",
             "Pied Piper Compression": "Decide who owns onboarding when Jared is out",
             "Hooli Field Services": "Pull the on-call logs for the last quarter"}
    for item in built:
        title = asked.pop(item["company"], None)
        if title is None:
            continue
        member = world.portal[item["company"]][0]
        with at(moment(world.today - timedelta(days=5), 13)):
            work.create_task(tenant=world.tenant, actor=member.user, role=member.role,
                             title=title, goal=item["goal"],
                             client_company=world.companies[item["company"]],
                             client_owner_contact=member.contact,
                             due_date=world.today + timedelta(days=4))


def _proposals(world, built) -> None:
    """One goal a client has proposed, and one order of goals a client has
    asked for. Both wait for the practice's answer."""
    from apps.work import goal_order, goal_proposals

    piper = world.portal["Pied Piper Compression"][0]
    with at(moment(world.today - timedelta(days=2), 10, 20)):
        goal_proposals.propose(
            world.companies["Pied Piper Compression"], actor=piper.user,
            title="Be ready for the security audit by spring",
            why="Two enterprise customers have asked for the report. We lose both deals "
                "without it, and nobody here owns getting ready.")
    company = world.companies["Wayne Industries"]
    wayne = world.portal["Wayne Industries"][0]
    current = goal_order.current_goals(company)
    if len(current) >= 2:
        with at(moment(world.today - timedelta(days=1), 16, 45)):
            goal_order.propose(company, [str(g.pk) for g in reversed(current)],
                               actor=wayne.user,
                               note="After last month's injury at Arkham Road I want "
                                    "safety ahead of the scorecard work.")


def _internal(world) -> None:
    """The practice's own to-do list, most of it the assistants'."""
    from apps.work import services as work

    for title, who, days, status in content.INTERNAL:
        user = world.staff[who]
        with at(moment(world.today - timedelta(days=8), 9)):
            task = work.create_task(tenant=world.tenant, actor=world.owner, role="FF",
                                    title=title, owner=user,
                                    due_date=world.today + timedelta(days=days))
        if status != "not_started":
            with at(moment(world.today - timedelta(days=3), 10)):
                work.apply_task_changes(task, actor=user, role="VA",
                                        changes={"status": status})


# ------------------------------------------------------------------ digests

def _digests(world, built) -> None:
    """The weekly digests of the last several weeks, generated at each Draft
    on from what had happened, approved and sent at each Send on; then the
    ones waiting now, weekly and every-update."""
    from django.utils import timezone

    from apps.work import digests, services as work
    from apps.work.models import Cadence, Digest, Stakeholder

    tenant, owner, now = world.tenant, world.owner, timezone.now()
    weekly = list(Stakeholder.objects.filter(cadence=Cadence.WEEKLY, goal__isnull=False)
                  .select_related("contact", "contact__company")
                  .order_by("contact_id").distinct("contact_id"))
    window = digests.next_weekly_window(tenant, now - timedelta(days=44))
    last_sent = None
    while window < now:
        drafted = digests.draft_before(tenant, window)
        start, end = digests.period_for(tenant, Cadence.WEEKLY, window)
        with at(drafted):
            made = [d for row in weekly if (d := digests.generate(
                tenant=tenant, contact=row.contact, cadence=Cadence.WEEKLY,
                period_start=start, period_end=end, send_window_at=window,
                until=drafted)) is not None]
        with at(drafted + timedelta(hours=3)):
            for digest in made:
                digests.approve(digest, actor=owner, role="FF")
        with at(window):
            for digest in made:
                digest.refresh_from_db()
                digests.send(digest, actor=None)
        last_sent = window
        window = digests.next_weekly_window(tenant, window + timedelta(hours=1))

    # What is waiting now. Two people follow every update, from last week on;
    # and two clients have had news since the last weekly digest went.
    fresh = min(now - timedelta(minutes=45),
                max(now - timedelta(hours=26), (last_sent or now) + timedelta(minutes=40)))
    by_company = {}
    for item in built:
        by_company.setdefault(item["company"], item)
    with at(now - timedelta(days=8)):
        for name, person in EVERY_UPDATE:
            item = by_company[name]
            Stakeholder.objects.create(tenant=tenant, contact=world.people[name][person],
                                       goal=item["goal"], cadence=Cadence.EVERY_UPDATE)
    with at(fresh):
        for name in WAITING_WEEKLY + tuple(n for n, _ in EVERY_UPDATE):
            item = by_company[name]
            task = next((t for t in item["tasks"] if t.status == "in_progress"),
                        item["tasks"][-1])
            lead = item["lead"]
            work.add_narrative(
                task, actor=lead, role=_role(world, lead),
                line={"Acme Fasteners": "Second shift ran the new changeover standard "
                                        "three nights in a row. Scrap on those nights was "
                                        "under 4%.",
                      "Stark Tool & Die": "Nine of this week's eleven quotes went out "
                                          "inside 48 hours. The two that did not were "
                                          "one-off tooling jobs.",
                      "Wayne Industries": "Arkham Road held its first scorecard meeting "
                                          "this morning. Forty minutes, three issues "
                                          "solved.",
                      "Pied Piper Compression": "This week's customer went live in nine "
                                                "days, the first under ten."}[name])
    next_window = digests.next_window(tenant, Cadence.WEEKLY, now)
    start, end = digests.period_for(tenant, Cadence.WEEKLY, next_window)
    for row in weekly:
        if row.contact.company and row.contact.company.name in WAITING_WEEKLY:
            digests.generate(tenant=tenant, contact=row.contact, cadence=Cadence.WEEKLY,
                             period_start=start, period_end=end,
                             send_window_at=next_window, until=now)
    digests.close_quiet_windows(tenant, now=now)
    world.extra["digests_waiting"] = Digest.objects.filter(state="pending").count()
