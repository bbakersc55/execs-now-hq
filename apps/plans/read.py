"""What the Plan page, the portal's This week and Home are sent, each read as
the person asking may see it (`access.PlanAccess`)."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from . import periods as P
from .access import ALL, PlanAccess
from .models import Horizon, PlanClose, PlanItem, PlanItemKpi, PlanItemTask

STATUS_LABEL = dict(PlanItem.Status.choices)
SOURCE_LABEL = dict(PlanItem.Source.choices)


def horizon_names(tenant) -> dict:
    from apps.tenancy import words

    return words.horizons_of(tenant)


def _name(user) -> str:
    if user is None:
        return ""
    return (getattr(user, "full_name", "") or user.email or "").strip()


class Reading:
    """Everything one plan payload needs, read once."""

    def __init__(self, access: PlanAccess, items, today):
        from apps.scorecard import ties
        from apps.scorecard.access import Reader

        self.access = access
        self.today = today
        self.items = list(items)
        ids = [i.pk for i in self.items]
        self.tasks = defaultdict(list)
        for link in PlanItemTask.all_objects.filter(item_id__in=ids).select_related(
                "task", "task__owner", "task__client_owner_contact", "task__client_team",
                "task__project"):
            if link.task.deleted_at is None:
                self.tasks[link.item_id].append(link.task)
        if access.scope is not None:
            # A client sees a sprint's task only where Work would show it them.
            from apps.crm.models import Task

            every = {t.pk for ts in self.tasks.values() for t in ts}
            allowed = set(access.scope.tasks(Task.all_objects.filter(pk__in=every))
                          .values_list("pk", flat=True))
            for key in list(self.tasks):
                self.tasks[key] = [t for t in self.tasks[key] if t.pk in allowed]
        self.kpis = defaultdict(list)
        kpi_ids = set()
        for item_id, kpi_id in PlanItemKpi.all_objects.filter(item_id__in=ids).values_list(
                "item_id", "kpi_id"):
            self.kpis[item_id].append(kpi_id)
            kpi_ids.add(kpi_id)
        self.kpi_state = {}
        if kpi_ids:
            company = access.company
            reader = Reader(access.request, company)
            kpis = list(ties._kpi_query().filter(pk__in=kpi_ids, archived_at__isnull=True))
            for kpi in kpis:
                tile = ties.tiles_for(reader, [kpi], today).get(kpi.pk)
                if tile is None:
                    continue                     # not one this person sees
                found = ties.latest(kpi, tile, today) or {}
                self.kpi_state[kpi.pk] = {
                    "id": str(kpi.pk), "name": kpi.name,
                    "value_text": found.get("value_text", ""),
                    "target_text": found.get("target_text", ""),
                    "status": found.get("status"), "status_label": found.get("status_label", ""),
                    "period": found.get("period", "")}
        children = defaultdict(list)
        for child in PlanItem.all_objects.filter(parent_id__in=ids,
                                                 state=PlanItem.State.ACCEPTED):
            if access.sees_item(child):
                children[child.parent_id].append(child)
        self.children = children

    def task_row(self, task) -> dict:
        from apps.crm.models import Task

        return {"id": str(task.pk), "title": task.title, "status": task.status,
                "status_label": Task.Status(task.status).label if task.status else "",
                "done": task.status == Task.Status.DONE,
                "due_date": task.due_date.isoformat() if task.due_date else None,
                "owner": _name(task.owner),
                "client_owner": (" ".join(filter(None, (
                    task.client_owner_contact.first_name, task.client_owner_contact.last_name)))
                    if task.client_owner_contact_id else ""),
                "client_owner_contact": str(task.client_owner_contact_id)
                if task.client_owner_contact_id else None,
                "team": task.client_team.name if task.client_team_id else "",
                "team_id": str(task.client_team_id) if task.client_team_id else None,
                "project": task.project.title if task.project_id else ""}

    def item(self, item) -> dict:
        parent = item.parent if item.parent_id else None
        out = {
            "id": str(item.pk), "horizon": item.horizon,
            "period_start": item.period_start.isoformat(),
            "period_label": P.label(item.horizon, item.period_start),
            "title": item.title, "done_means": item.done_means,
            "status": item.status, "status_label": STATUS_LABEL[item.status],
            "owner": {"id": str(item.owner_id), "name": _name(item.owner)}
            if item.owner_id else None,
            "serves": {"id": str(parent.pk), "title": parent.title, "horizon": parent.horizon}
            if parent is not None and self.access.sees_item(parent) else None,
            "served_by": [{"id": str(c.pk), "title": c.title, "horizon": c.horizon,
                           "status": c.status, "status_label": STATUS_LABEL[c.status],
                           "period_label": P.label(c.horizon, c.period_start)}
                          for c in self.children.get(item.pk, [])],
            "goal": {"id": str(item.goal_id), "title": item.goal.title}
            if item.goal_id else None,
            "project": {"id": str(item.project_id), "title": item.project.title}
            if item.project_id else None,
            "client_team": {"id": str(item.client_team_id), "name": item.client_team.name}
            if item.client_team_id else None,
            "target_value": float(item.target_value) if item.target_value is not None else None,
            "tasks": [self.task_row(t) for t in self.tasks.get(item.pk, [])],
            "kpis": [self.kpi_state[k] for k in self.kpis.get(item.pk, [])
                     if k in self.kpi_state],
            "state": item.state, "source": item.source,
            "source_label": SOURCE_LABEL.get(item.source, ""),
            "drew_on": item.drew_on or [], "from_ai_app": item.from_ai_app,
            "from_ai": item.ai_call_id is not None,
            "proposed_by": _name(item.proposed_by) if item.proposed_by_id else "",
            "may_edit": self.access.may_edit(item),
        }
        return out


def _items_qs(company):
    return PlanItem.all_objects.filter(company=company).select_related(
        "owner", "parent", "goal", "project", "client_team", "proposed_by")


def periods_wanted(company, today, asked: dict) -> dict:
    """Each horizon's period: today's, or the one asked for."""
    out = {}
    for horizon in ALL:
        raw = asked.get(horizon)
        day = today
        if raw:
            try:
                day = date.fromisoformat(str(raw))
            except ValueError:
                day = today
        out[horizon] = P.start_of(horizon, day, company)
    return out


def _close_offer(company, horizon, start, today) -> dict | None:
    """The period a Close button acts on: last period's, while it is unclosed
    and had something on it; this one's otherwise."""
    from .services import close_rows

    closed = set(PlanClose.all_objects.filter(company=company, horizon=horizon)
                 .values_list("period_start", flat=True))
    current = P.start_of(horizon, today, company)
    candidates = [P.previous_start(horizon, current), current] if start == current else [start]
    for candidate in candidates:
        if candidate in closed or candidate > today:
            continue
        if close_rows(company, horizon, candidate):
            return {"period_start": candidate.isoformat(),
                    "label": P.label(horizon, candidate), "late": candidate < current}
    return None


def plan(access: PlanAccess, today, asked: dict | None = None) -> dict:
    company = access.company
    names = horizon_names(company.tenant)
    starts = periods_wanted(company, today, asked or {})
    columns = []
    every = list(_items_qs(company).filter(
        horizon__in=access.horizons,
        period_start__in={starts[h] for h in access.horizons}))
    shown = [i for i in every if i.period_start == starts[i.horizon] and access.sees_item(i)]
    reading = Reading(access, shown, today)
    closes = {(c.horizon, c.period_start): c for c in PlanClose.all_objects.filter(
        company=company)}
    for horizon in access.horizons:
        start = starts[horizon]
        mine = [i for i in shown if i.horizon == horizon]
        accepted = [reading.item(i) for i in mine if i.state == PlanItem.State.ACCEPTED]
        proposals = [reading.item(i) for i in mine if i.state == PlanItem.State.PROPOSED]
        prev = P.previous_start(horizon, start)
        last = closes.get((horizon, prev))
        this_close = closes.get((horizon, start))
        columns.append({
            "key": horizon, "name": names[horizon], "period_start": start.isoformat(),
            "period_label": P.label(horizon, start),
            "is_current": start == P.start_of(horizon, today, company),
            "previous": P.previous_start(horizon, start).isoformat(),
            "next": P.next_start(horizon, start).isoformat(),
            "items": accepted, "proposals": proposals,
            "closed": {"summary": this_close.summary,
                       "closed_at": this_close.created_at.isoformat()} if this_close else None,
            "last_close": {"summary": last.summary, "period_label": P.label(horizon, prev),
                           "closed_at": last.created_at.isoformat()} if last else None,
            "close_offer": _close_offer(company, horizon, start, today)
            if access.may_close and horizon in (Horizon.WEEK, Horizon.MONTH, Horizon.QUARTER)
            else None,
        })
    return {"company": {"id": str(company.pk), "name": company.name,
                        "is_practice": company.is_practice,
                        "fiscal_year_start": P.fiscal_start(company),
                        "week_start": P.week_start(company)},
            "today": today.isoformat(), "access": access.describe(), "horizons": columns,
            "choices": choices(access) if access.edits or access.describe()["may_add"] else None}


def choices(access) -> dict:
    """What the item form offers: owners, goals, projects, open tasks, KPIs,
    teams."""
    from apps.crm.models import Task
    from apps.scorecard.models import Kpi
    from apps.tenancy.models import CLIENT_ROLES, Membership, Role
    from apps.work.models import Goal, Project
    from apps.work.teams import live_teams

    company = access.company
    goal_company = None if company.is_practice else company.pk
    people = []
    for m in Membership.all_objects.filter(tenant_id=company.tenant_id,
                                           revoked_at__isnull=True).select_related("user"):
        if m.role in CLIENT_ROLES and m.client_company_id != company.pk:
            continue
        if access.is_client and m.role not in CLIENT_ROLES:
            continue
        if m.role not in CLIENT_ROLES and m.role not in (Role.FF, Role.CF, Role.VA):
            continue
        people.append({"id": str(m.user_id), "name": _name(m.user),
                       "side": "client" if m.role in CLIENT_ROLES else "practice"})
    people.sort(key=lambda p: (p["side"] != "practice", p["name"].lower()))
    tasks = Task.all_objects.filter(tenant_id=company.tenant_id, client_company_id=goal_company,
                                    deleted_at__isnull=True).exclude(
        status__in=(Task.Status.DONE, Task.Status.CANCELLED))
    if access.scope is not None:
        tasks = access.scope.tasks(tasks)
    tasks = tasks.order_by("due_date", "title")[:300]
    return {
        "people": people,
        "goals": [{"id": str(g.pk), "title": g.title} for g in Goal.all_objects.filter(
            tenant_id=company.tenant_id, client_company_id=goal_company,
            deleted_at__isnull=True).order_by("title")] if access.edits else [],
        "projects": [{"id": str(p.pk), "title": p.title} for p in Project.all_objects.filter(
            tenant_id=company.tenant_id, client_company_id=goal_company,
            deleted_at__isnull=True).order_by("title")] if access.edits else [],
        "tasks": [{"id": str(t.pk), "title": t.title,
                   "due_date": t.due_date.isoformat() if t.due_date else None}
                  for t in tasks],
        "kpis": [{"id": str(k.pk), "name": k.name} for k in Kpi.all_objects.filter(
            scorecard__company_id=company.pk, archived_at__isnull=True)
            .order_by("page__position", "position", "name")] if access.edits else [],
        "teams": [{"id": str(t.pk), "name": t.name} for t in live_teams(company)]
        if not company.is_practice else [],
    }


# ------------------------------------------------------------------ This week (the portal)

def week(access: PlanAccess, today) -> dict:
    """What a team member opens on Monday: the sprint goal, their own tasks,
    their team's tasks, and what the week serves."""
    company = access.company
    start = P.start_of(Horizon.WEEK, today, company)
    sprint = _items_qs(company).filter(horizon=Horizon.WEEK, period_start=start,
                                       state=PlanItem.State.ACCEPTED).first()
    names = horizon_names(company.tenant)
    out = {"company": {"id": str(company.pk), "name": company.name},
           "name": names[Horizon.WEEK], "period_start": start.isoformat(),
           "period_label": P.label(Horizon.WEEK, start), "sprint": None, "mine": [],
           "team": [], "others": [], "serves": [], "access": access.describe()}
    if sprint is None or not access.sees_item(sprint):
        return out
    reading = Reading(access, [sprint], today)
    row = reading.item(sprint)
    out["sprint"] = {k: row[k] for k in ("id", "title", "done_means", "status",
                                         "status_label", "owner", "may_edit")}
    contact_id = getattr(access.membership, "contact_id", None)
    user_id = access.request.user.pk
    tasks = reading.tasks.get(sprint.pk, [])
    for task in tasks:
        line = reading.task_row(task)
        # As Work reads it: a task in a project is on its project's team, and
        # one with no team is the company's default team's.
        team_id = task.client_team_id or (task.project.client_team_id if task.project_id
                                          else None) or (access.scope.default_team_id
                                                         if access.scope is not None else None)
        if (contact_id and task.client_owner_contact_id == contact_id) \
                or task.owner_id == user_id or task.assignee_id == user_id:
            out["mine"].append(line)
        elif team_id is not None and team_id in access.team_ids:
            out["team"].append(line)
        elif access.sees_all or not access.is_client:
            out["others"].append(line)
    # What the week serves, up the chain as far as the person may see.
    chain, seen, node = [], set(), sprint.parent
    while node is not None and node.pk not in seen:
        seen.add(node.pk)
        if access.sees_item(node):
            chain.append({"id": str(node.pk), "title": node.title, "horizon": node.horizon,
                          "name": names[node.horizon],
                          "status_label": STATUS_LABEL[node.status]})
        node = node.parent
    out["serves"] = chain
    out["done"] = sum(1 for t in tasks if t.status == "done")
    out["total"] = len(tasks)
    return out


# ------------------------------------------------------------------ Home and the index

def glance(companies, today) -> dict:
    """{company id: the week at a glance}: the sprint goal, tasks done of
    total, and how many current items are off track."""
    from apps.crm.models import Task

    out = {}
    companies = list(companies)
    if not companies:
        return out
    by_id = {c.pk: c for c in companies}
    starts = {c.pk: {h: P.start_of(h, today, c) for h in
                     (Horizon.QUARTER, Horizon.MONTH, Horizon.WEEK)} for c in companies}
    items = PlanItem.all_objects.filter(company_id__in=list(by_id),
                                        state=PlanItem.State.ACCEPTED,
                                        horizon__in=(Horizon.QUARTER, Horizon.MONTH,
                                                     Horizon.WEEK))
    sprints = {}
    off = defaultdict(int)
    for item in items:
        if item.period_start != starts[item.company_id][item.horizon]:
            continue
        if item.horizon == Horizon.WEEK:
            sprints[item.company_id] = item
        if item.status == PlanItem.Status.OFF_TRACK:
            off[item.company_id] += 1
    counts = defaultdict(lambda: [0, 0])
    for item_id, status, deleted in PlanItemTask.all_objects.filter(
            item_id__in=[s.pk for s in sprints.values()]).values_list(
            "item_id", "task__status", "task__deleted_at"):
        if deleted is not None:
            continue
        counts[item_id][1] += 1
        counts[item_id][0] += int(status == Task.Status.DONE)
    for company_id in by_id:
        sprint = sprints.get(company_id)
        if sprint is None and not off.get(company_id):
            continue
        done, total = counts[sprint.pk] if sprint is not None else (0, 0)
        out[company_id] = {"sprint": sprint.title if sprint is not None else "",
                           "done": done, "total": total, "off_track": off.get(company_id, 0)}
    return out
