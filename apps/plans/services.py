"""The plan's writes: items added, edited, accepted and discarded; links to
goals, projects, tasks and KPIs; a period closed; and the three ways other
modules put something on a plan (a playbook's goal, a session's 30/60/90
rows, an AI app's proposals).

Nothing here changes what it links. A goal made from the plan is an ordinary
goal; a task made for a sprint is an ordinary task; closing a week records
the outcome of each task and changes none of them.
"""

from __future__ import annotations

from datetime import date

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.tenancy.models import AuditEvent

from . import periods as P
from .models import ORDER, Horizon, PlanClose, PlanItem, PlanItemKpi, PlanItemTask

MAX_TITLE = 300
OUTCOMES = ("done", "not_done", "carried")


class PlanRefused(ValueError):
    def __init__(self, message, status=400, field=None):
        super().__init__(message)
        self.status = status
        self.field = field


def _audit(company, actor, verb, item=None, **payload):
    AuditEvent.all_objects.create(
        tenant_id=company.tenant_id, actor=actor, verb=verb,
        target_type="plan_item" if item is not None else "company",
        target_id=item.pk if item is not None else company.pk,
        payload={"company": str(company.pk), **payload})


def _clean_title(raw) -> str:
    title = " ".join(str(raw or "").split())[:MAX_TITLE]
    if not title:
        raise PlanRefused("An item needs a title.", field="title")
    return title


def _goal_company_id(company):
    """The practice's own goals have no company (they are its internal work)."""
    return None if company.is_practice else company.pk


def _next_position(company, horizon, period_start) -> int:
    top = PlanItem.all_objects.filter(company=company, horizon=horizon,
                                      period_start=period_start).aggregate(m=Max("position"))
    return (top["m"] or 0) + 1


# ------------------------------------------------------------------ choosing links

def _goal_of(company, raw):
    from apps.work.models import Goal

    if raw in (None, ""):
        return None
    found = Goal.all_objects.filter(pk=raw, tenant_id=company.tenant_id,
                                    client_company_id=_goal_company_id(company),
                                    deleted_at__isnull=True).first() \
        if _is_uuid(raw) else None
    if found is None:
        raise PlanRefused("That goal isn't one of this company's.", field="goal")
    return found


def _project_of(company, raw):
    from apps.work.models import Project

    if raw in (None, ""):
        return None
    found = Project.all_objects.filter(pk=raw, tenant_id=company.tenant_id,
                                       client_company_id=_goal_company_id(company),
                                       deleted_at__isnull=True).first() \
        if _is_uuid(raw) else None
    if found is None:
        raise PlanRefused("That project isn't one of this company's.", field="project")
    return found


def _tasks_of(company, raw) -> list:
    from apps.crm.models import Task

    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise PlanRefused("Tasks are a list.", field="tasks")
    ids = [str(x) for x in raw]
    found = {str(t.pk): t for t in Task.all_objects.filter(
        pk__in=[i for i in ids if _is_uuid(i)], tenant_id=company.tenant_id,
        client_company_id=_goal_company_id(company), deleted_at__isnull=True)}
    if len(found) != len(set(ids)):
        raise PlanRefused("Each task is one of this company's.", field="tasks")
    return [found[i] for i in dict.fromkeys(ids)]


def _kpis_of(company, raw) -> list:
    from apps.scorecard.models import Kpi

    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise PlanRefused("KPIs are a list.", field="kpis")
    ids = [str(x) for x in raw]
    found = {str(k.pk): k for k in Kpi.all_objects.filter(
        pk__in=[i for i in ids if _is_uuid(i)], tenant_id=company.tenant_id,
        scorecard__company_id=company.pk, archived_at__isnull=True)}
    if len(found) != len(set(ids)):
        raise PlanRefused("Each KPI is one of this company's scorecard's.", field="kpis")
    return [found[i] for i in dict.fromkeys(ids)]


def _parent_of(company, horizon, raw):
    if raw in (None, ""):
        return None
    above = P.above(horizon)
    found = PlanItem.all_objects.filter(pk=raw, company=company,
                                        state=PlanItem.State.ACCEPTED).first() \
        if _is_uuid(raw) else None
    if found is None or above is None or found.horizon != above:
        raise PlanRefused("An item serves an item on the horizon just above it.",
                          field="parent")
    return found


def _team_of(company, raw):
    from apps.work.teams import team_of_company

    if raw in (None, ""):
        return None
    team = team_of_company(company, raw)
    if team is None:
        raise PlanRefused("That team isn't one of this company's.", field="client_team")
    return team


def _owner_of(company, raw):
    from apps.tenancy.models import CLIENT_ROLES, Membership

    if raw in (None, ""):
        return None
    member = Membership.all_objects.filter(
        tenant_id=company.tenant_id, user_id=raw, revoked_at__isnull=True).first() \
        if _is_uuid(raw) else None
    if member is None or (member.role in CLIENT_ROLES
                          and member.client_company_id != company.pk):
        raise PlanRefused("The owner is someone at the practice or one of this company's "
                          "portal users.", field="owner")
    return member.user


def _is_uuid(value) -> bool:
    import uuid

    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, TypeError):
        return False


def _target(raw):
    from decimal import Decimal, InvalidOperation

    if raw in (None, ""):
        return None
    try:
        value = Decimal(str(raw).replace(",", "").replace("$", "").rstrip("%").strip())
    except InvalidOperation:
        raise PlanRefused("A target is a number.", field="target_value") from None
    if not value.is_finite() or abs(value) >= Decimal("1e12"):
        raise PlanRefused("That target is too large.", field="target_value")
    return value.quantize(Decimal("0.0001"))


# ------------------------------------------------------------------ the writes

def _set_links(item, *, tasks=None, kpis=None):
    if tasks is not None:
        PlanItemTask.all_objects.filter(item=item).delete()
        for i, task in enumerate(tasks):
            PlanItemTask.all_objects.create(tenant_id=item.tenant_id, item=item, task=task,
                                            position=i)
    if kpis is not None:
        PlanItemKpi.all_objects.filter(item=item).delete()
        for kpi in kpis:
            PlanItemKpi.all_objects.create(tenant_id=item.tenant_id, item=item, kpi=kpi)


def new_goal_for(company, *, title, actor, end):
    from apps.work.models import Goal

    return Goal.all_objects.create(tenant_id=company.tenant_id,
                                   client_company_id=_goal_company_id(company),
                                   owner=actor if actor is not None and not _is_client(actor,
                                                                                       company)
                                   else None,
                                   title=title[:255], target_date=end)


def _is_client(user, company) -> bool:
    from apps.tenancy.models import CLIENT_ROLES, Membership

    return Membership.all_objects.filter(user=user, tenant_id=company.tenant_id,
                                         role__in=CLIENT_ROLES).exists()


def new_tasks(company, titles, *, actor, role, request=None, due=None) -> list:
    """Tasks made for a sprint: ordinary tasks of the company."""
    from apps.crm.models import Task
    from apps.tenancy.models import CLIENT_ROLES
    from apps.work import services as work

    out = []
    for raw in titles or []:
        title = " ".join(str(raw or "").split())[:255]
        if not title:
            continue
        fields = {"title": title, "status": Task.Status.NOT_STARTED, "due_date": due,
                  "client_company_id": _goal_company_id(company)}
        if role in CLIENT_ROLES and request is not None:
            from apps.work.permissions import client_team_for_new

            fields["client_team"] = client_team_for_new(request)
        else:
            fields["owner"] = actor
        out.append(work.create_task(tenant=company.tenant, actor=actor, role=role, **fields))
    return out


def _period(company, horizon, raw, today) -> date:
    if raw in (None, ""):
        return P.start_of(horizon, today, company)
    try:
        day = date.fromisoformat(str(raw))
    except ValueError:
        raise PlanRefused("That isn't a date.", field="period_start") from None
    return P.start_of(horizon, day, company)


@transaction.atomic
def add(company, data, *, actor, role, today, state=PlanItem.State.ACCEPTED,
        source=PlanItem.Source.HAND, request=None, **extra) -> PlanItem:
    """An item, straight onto the plan or (a client's at the year or quarter,
    an AI app's) into the tray. A year's item is one of the company's goals:
    linked when one is named, made from the title otherwise."""
    horizon = data.get("horizon")
    if horizon not in Horizon.values:
        raise PlanRefused("Choose a horizon.", field="horizon")
    period_start = _period(company, horizon, data.get("period_start"), today)
    title = _clean_title(data.get("title"))
    if horizon == Horizon.WEEK and state == PlanItem.State.ACCEPTED and PlanItem.all_objects.filter(
            company=company, horizon=Horizon.WEEK, period_start=period_start,
            state=PlanItem.State.ACCEPTED).exists():
        raise PlanRefused(f"{P.label(horizon, period_start)} already has its sprint. Add "
                          "tasks to it instead.", status=409, field="horizon")
    goal = _goal_of(company, data.get("goal"))
    item = PlanItem.all_objects.create(
        tenant_id=company.tenant_id, company=company, horizon=horizon,
        period_start=period_start, title=title,
        done_means=str(data.get("done_means") or "").strip()[:2000],
        status=_status(data.get("status")) or PlanItem.Status.ON_TRACK,
        owner=_owner_of(company, data.get("owner")),
        parent=_parent_of(company, horizon, data.get("parent")),
        goal=goal, project=_project_of(company, data.get("project")),
        client_team=_team_of(company, data.get("client_team")),
        target_value=_target(data.get("target_value")),
        position=_next_position(company, horizon, period_start), state=state, source=source,
        created_by=actor, **extra)
    if horizon == Horizon.YEAR and goal is None and state == PlanItem.State.ACCEPTED:
        item.goal = new_goal_for(company, title=title, actor=actor,
                                 end=P.end_of(horizon, period_start))
        item.save(update_fields=["goal", "updated_at"])
    tasks = _tasks_of(company, data.get("tasks"))
    tasks += new_tasks(company, data.get("new_tasks"), actor=actor, role=role, request=request,
                       due=P.end_of(horizon, period_start) if horizon == Horizon.WEEK else None)
    _set_links(item, tasks=tasks, kpis=_kpis_of(company, data.get("kpis")))
    _audit(company, actor, "plan.item_added" if state == PlanItem.State.ACCEPTED
           else "plan.item_proposed", item, horizon=horizon, title=title)
    return item


def _status(raw):
    if raw in (None, ""):
        return None
    if raw not in PlanItem.Status.values:
        raise PlanRefused("A status is on track, off track, done or dropped.", field="status")
    return raw


@transaction.atomic
def edit(item, data, *, actor, role, request=None) -> PlanItem:
    item = PlanItem.all_objects.select_for_update().get(pk=item.pk)
    company = item.company
    fields = []
    if "title" in data:
        item.title = _clean_title(data["title"])
        fields.append("title")
    if "done_means" in data:
        item.done_means = str(data.get("done_means") or "").strip()[:2000]
        fields.append("done_means")
    if "status" in data:
        item.status = _status(data["status"]) or item.status
        fields.append("status")
    if "owner" in data:
        item.owner = _owner_of(company, data["owner"])
        fields.append("owner")
    if "parent" in data:
        item.parent = _parent_of(company, item.horizon, data["parent"])
        fields.append("parent")
    if "goal" in data:
        item.goal = _goal_of(company, data["goal"])
        fields.append("goal")
    if "project" in data:
        item.project = _project_of(company, data["project"])
        fields.append("project")
    if "client_team" in data:
        item.client_team = _team_of(company, data["client_team"])
        fields.append("client_team")
    if "target_value" in data:
        item.target_value = _target(data["target_value"])
        fields.append("target_value")
    if fields:
        item.save(update_fields=[*fields, "updated_at"])
    tasks = None
    if "tasks" in data or "new_tasks" in data:
        tasks = _tasks_of(company, data["tasks"]) if "tasks" in data else [
            link.task for link in PlanItemTask.all_objects.filter(item=item)
            .select_related("task")]
        tasks += new_tasks(company, data.get("new_tasks"), actor=actor, role=role,
                           request=request,
                           due=P.end_of(item.horizon, item.period_start)
                           if item.horizon == Horizon.WEEK else None)
    _set_links(item, tasks=tasks,
               kpis=_kpis_of(company, data["kpis"]) if "kpis" in data else None)
    _audit(company, actor, "plan.item_changed", item, horizon=item.horizon, title=item.title)
    return item


@transaction.atomic
def remove(item, *, actor) -> None:
    """Off the plan. What it linked stays as it was."""
    company = item.company
    _audit(company, actor, "plan.item_removed", item, horizon=item.horizon, title=item.title)
    PlanItem.all_objects.filter(parent=item).update(parent=None)
    item.delete()


@transaction.atomic
def accept(item, *, actor) -> PlanItem:
    """A proposal onto the plan. A year's is linked to a goal, made from it
    when it names none. A week's joins the sprint already there."""
    item = PlanItem.all_objects.select_for_update().get(pk=item.pk)
    if item.state != PlanItem.State.PROPOSED:
        raise PlanRefused("Only a proposal is accepted.", status=409)
    company = item.company
    if item.horizon == Horizon.WEEK:
        sprint = PlanItem.all_objects.filter(
            company=company, horizon=Horizon.WEEK, period_start=item.period_start,
            state=PlanItem.State.ACCEPTED).first()
        if sprint is not None:
            raise PlanRefused(f"{P.label(Horizon.WEEK, item.period_start)} already has its "
                              "sprint. Edit its goal sentence instead, or discard this.",
                              status=409)
    if item.horizon == Horizon.YEAR and item.goal_id is None:
        item.goal = new_goal_for(company, title=item.title, actor=actor,
                                 end=P.end_of(item.horizon, item.period_start))
    item.state = PlanItem.State.ACCEPTED
    item.decided_by, item.decided_at = actor, timezone.now()
    item.position = _next_position(company, item.horizon, item.period_start)
    item.save(update_fields=["state", "decided_by", "decided_at", "goal", "position",
                             "updated_at"])
    _audit(company, actor, "plan.proposal_accepted", item, horizon=item.horizon,
           title=item.title)
    return item


@transaction.atomic
def discard(item, *, actor) -> PlanItem:
    item = PlanItem.all_objects.select_for_update().get(pk=item.pk)
    if item.state != PlanItem.State.PROPOSED:
        raise PlanRefused("Only a proposal is discarded.", status=409)
    item.state = PlanItem.State.DISCARDED
    item.decided_by, item.decided_at = actor, timezone.now()
    item.save(update_fields=["state", "decided_by", "decided_at", "updated_at"])
    _audit(item.company, actor, "plan.proposal_discarded", item, horizon=item.horizon,
           title=item.title)
    return item


def set_fiscal_start(company, month, *, actor):
    try:
        month = int(month)
    except (TypeError, ValueError):
        raise PlanRefused("The fiscal year starts in a month, 1 to 12.",
                          field="fiscal_year_start") from None
    if not 1 <= month <= 12:
        raise PlanRefused("The fiscal year starts in a month, 1 to 12.",
                          field="fiscal_year_start")
    if company.fiscal_year_start != month:
        before = company.fiscal_year_start
        type(company).all_objects.filter(pk=company.pk).update(fiscal_year_start=month)
        company.fiscal_year_start = month
        _audit(company, actor, "plan.fiscal_year_changed", **{"from": before, "to": month})
    return company


# ------------------------------------------------------------------ closing a period

CLOSABLE = (Horizon.WEEK, Horizon.MONTH, Horizon.QUARTER)


def _sprint(company, period_start):
    return PlanItem.all_objects.filter(company=company, horizon=Horizon.WEEK,
                                       period_start=period_start,
                                       state=PlanItem.State.ACCEPTED).first()


def close_rows(company, horizon, period_start) -> list[dict]:
    """What the walk asks about: a week's sprint tasks, or the period's items,
    each with the outcome it suggests (never "carried": that is always chosen)."""
    from apps.crm.models import Task

    if horizon == Horizon.WEEK:
        sprint = _sprint(company, period_start)
        if sprint is None:
            return []
        return [{"kind": "task", "id": str(link.task_id), "title": link.task.title,
                 "status": link.task.status,
                 "suggested": "done" if link.task.status == Task.Status.DONE else "not_done"}
                for link in PlanItemTask.all_objects.filter(item=sprint)
                .select_related("task") if link.task.deleted_at is None]
    return [{"kind": "item", "id": str(i.pk), "title": i.title, "status": i.status,
             "suggested": "done" if i.status == PlanItem.Status.DONE else "not_done"}
            for i in PlanItem.all_objects.filter(company=company, horizon=horizon,
                                                 period_start=period_start,
                                                 state=PlanItem.State.ACCEPTED)
            if i.status != PlanItem.Status.DROPPED]


def _summary(horizon, period_start, rows, sprint=None) -> str:
    done = sum(1 for r in rows if r["outcome"] == "done")
    carried = sum(1 for r in rows if r["outcome"] == "carried")
    total = len(rows)
    nxt = P.next_start(horizon, period_start)
    if horizon == Horizon.WEEK:
        head = f"Week of {P.MONTHS[period_start.month - 1]} {period_start.day}"
        goal = f": “{sprint.title}”" if sprint is not None else ""
        text = f"{head}{goal}. {done} of {total} {'task' if total == 1 else 'tasks'} done"
        if carried:
            text += f"; {carried} carried over to next week"
        return text + "."
    if horizon == Horizon.MONTH:
        text = f"{P.MONTHS[period_start.month - 1]}'s plan: {done} of {total} done"
        if carried:
            text += f"; {carried} carried over to {P.MONTHS[nxt.month - 1]}"
        return text + "."
    text = f"The quarter's priorities ({P.label(horizon, period_start)}): {done} of {total} done"
    if carried:
        text += f"; {carried} carried over to the next quarter"
    return text + "."


@transaction.atomic
def close(company, horizon, period_start, outcomes: dict, *, actor) -> PlanClose:
    """Close a week, month or quarter. Each row's outcome is the one chosen,
    or the one suggested (done, or not done). A carried task joins next
    week's sprint (made with this one's goal sentence when there is none
    yet); a carried item is copied into the next period. The summary goes to
    the weekly digest drafts of the company's people (`apps.plans.digest`)."""
    if horizon not in CLOSABLE:
        raise PlanRefused("A week, a month or a quarter is closed.", field="horizon")
    if PlanClose.all_objects.filter(company=company, horizon=horizon,
                                    period_start=period_start).exists():
        raise PlanRefused(f"{P.label(horizon, period_start)} is already closed.", status=409)
    rows = close_rows(company, horizon, period_start)
    if not rows:
        raise PlanRefused(f"{P.label(horizon, period_start)} has nothing on it to close.",
                          status=409)
    outcomes = outcomes or {}
    for row in rows:
        chosen = outcomes.get(row["id"])
        if chosen not in (None, "") and chosen not in OUTCOMES:
            raise PlanRefused("Each outcome is done, not done or carried over.",
                              field="outcomes")
        row["outcome"] = chosen or row["suggested"]
    nxt = P.next_start(horizon, period_start)
    sprint = _sprint(company, period_start) if horizon == Horizon.WEEK else None
    if horizon == Horizon.WEEK:
        carried = [r for r in rows if r["outcome"] == "carried"]
        if carried:
            following = _sprint(company, nxt)
            if following is None:
                same_month = nxt.month == period_start.month
                following = PlanItem.all_objects.create(
                    tenant_id=company.tenant_id, company=company, horizon=Horizon.WEEK,
                    period_start=nxt, title=sprint.title, done_means=sprint.done_means,
                    owner=sprint.owner, parent=sprint.parent if same_month else None,
                    client_team=sprint.client_team, source=PlanItem.Source.CARRIED,
                    source_id=sprint.pk, created_by=actor,
                    position=_next_position(company, Horizon.WEEK, nxt))
            have = set(PlanItemTask.all_objects.filter(item=following)
                       .values_list("task_id", flat=True))
            start = PlanItemTask.all_objects.filter(item=following).count()
            for i, r in enumerate(r for r in carried if r["id"] not in {str(t) for t in have}):
                PlanItemTask.all_objects.create(tenant_id=company.tenant_id, item=following,
                                                task_id=r["id"], position=start + i)
        PlanItem.all_objects.filter(pk=sprint.pk).update(status=PlanItem.Status.DONE,
                                                         updated_at=timezone.now())
    else:
        for r in rows:
            item = PlanItem.all_objects.get(pk=r["id"])
            if r["outcome"] == "done" and item.status != PlanItem.Status.DONE:
                item.status = PlanItem.Status.DONE
                item.save(update_fields=["status", "updated_at"])
            if r["outcome"] == "carried":
                copy = PlanItem.all_objects.create(
                    tenant_id=company.tenant_id, company=company, horizon=horizon,
                    period_start=nxt, title=item.title, done_means=item.done_means,
                    owner=item.owner, parent=item.parent, goal=item.goal,
                    project=item.project, client_team=item.client_team,
                    target_value=item.target_value, source=PlanItem.Source.CARRIED,
                    source_id=item.pk, created_by=actor,
                    position=_next_position(company, horizon, nxt))
                _set_links(copy, tasks=[link.task for link in PlanItemTask.all_objects.filter(
                    item=item).select_related("task")],
                    kpis=[link.kpi for link in PlanItemKpi.all_objects.filter(item=item)
                          .select_related("kpi")])
    summary = _summary(horizon, period_start, rows, sprint)
    record = PlanClose.all_objects.create(
        tenant_id=company.tenant_id, company=company, horizon=horizon,
        period_start=period_start, summary=summary, closed_by=actor,
        outcomes=[{k: r[k] for k in ("kind", "id", "title", "outcome")} for r in rows])
    from .digest import flag_drafts

    flag_drafts(company)
    _audit(company, actor, "plan.period_closed", horizon=horizon,
           period=P.label(horizon, period_start), summary=summary)
    return record


# ------------------------------------------------------------------ from other modules

def put_goal_on_year(company, goal, *, actor, day, source=PlanItem.Source.PLAYBOOK,
                     source_id=None):
    """A playbook's goal (or a converted session's) on the plan's year, once."""
    from .access import available

    if not available(company.tenant_id):
        return None
    found = PlanItem.all_objects.filter(company=company, horizon=Horizon.YEAR, goal=goal,
                                        state=PlanItem.State.ACCEPTED).first()
    if found is not None:
        return found
    start = P.start_of(Horizon.YEAR, day, company)
    item = PlanItem.all_objects.create(
        tenant_id=company.tenant_id, company=company, horizon=Horizon.YEAR,
        period_start=start, title=goal.title[:MAX_TITLE], owner=goal.owner, goal=goal,
        source=source, source_id=source_id, created_by=actor,
        position=_next_position(company, Horizon.YEAR, start))
    _audit(company, actor, "plan.item_added", item, horizon=Horizon.YEAR, title=item.title)
    return item


def session_rows(session) -> list:
    """A converted session's accepted rows with a 30/60/90, not yet on the plan."""
    from apps.strategy.conversion import accepted_rows

    placed = set(PlanItem.all_objects.filter(source=PlanItem.Source.SESSION,
                                             horizon=Horizon.QUARTER,
                                             source_id__isnull=False,
                                             company_id=session.company_id)
                 .values_list("source_id", flat=True))
    return [r for r in accepted_rows(session) if r.horizon and r.pk not in placed]


@transaction.atomic
def from_session(session, *, actor, today) -> list[PlanItem]:
    """Put a converted session's 30/60/90 rows on the plan as this quarter's
    priorities: each serves the year's item for the goal it became (put on
    the year when it is not yet), and links that goal or project."""
    from apps.work.models import Goal, Project

    company = session.company
    if company is None:
        raise PlanRefused("This session has no company, so it has no plan.", status=409)
    if session.converted_at is None:
        raise PlanRefused("Convert the session first; its rows then become the quarter's "
                          "priorities.", status=409)
    rows = session_rows(session)
    if not rows:
        raise PlanRefused("Every 30/60/90 row of this session is on the plan already.",
                          status=409)
    quarter = P.start_of(Horizon.QUARTER, today, company)
    made = []
    for row in rows:
        project = Project.all_objects.filter(source_map_row=row, deleted_at__isnull=True).first()
        goal = Goal.all_objects.filter(source_map_row=row, deleted_at__isnull=True).first() \
            or (project.goal if project is not None and project.goal_id else None)
        parent = put_goal_on_year(company, goal, actor=actor, day=today,
                                  source=PlanItem.Source.SESSION, source_id=row.pk) \
            if goal is not None else None
        title = (row.the_fix or row.bottleneck or "").strip().split("\n")[0][:MAX_TITLE] \
            or row.bottleneck[:MAX_TITLE]
        item = PlanItem.all_objects.create(
            tenant_id=company.tenant_id, company=company, horizon=Horizon.QUARTER,
            period_start=quarter, title=title, done_means=row.measurable or "",
            parent=parent, goal=goal, project=project, source=PlanItem.Source.SESSION,
            source_id=row.pk, created_by=actor,
            position=_next_position(company, Horizon.QUARTER, quarter))
        if row.kpi_id:
            PlanItemKpi.all_objects.create(tenant_id=company.tenant_id, item=item,
                                           kpi_id=row.kpi_id)
        made.append(item)
    _audit(company, actor, "plan.from_session", session=str(session.pk), items=len(made))
    return made


def horizon_index(horizon) -> int:
    return list(ORDER).index(horizon)
