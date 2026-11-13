"""Playbooks (P8): a goal, its projects and their tasks, written as an
outline with weeks and role owners, started on a company with real dates.

The outline, one item a line:

    Goal: The 90-day operations reset
    Why: what it is for (optional, the goal's description)
    ## Discovery | weeks 1-2
    - Interview the owner | week 1 | practice

A project names its weeks ("week 3" or "weeks 3-4"); a task its week and its
owner: `owner`, `second-in-command` or `practice` (the default). Week 1 starts
on the start date; a task is due on the fifth day of its week, a project
ends on the fifth day of its last week, and the goal when its last project
does.

A module's playbook is **copied into the practice** the first time it is
opened or started (`copy_shipped`), arriving as a draft: "draft, edit before
first use". A draft is not started until the practice saves it or marks it
ready.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.centers import catalog
from apps.centers.models import Playbook, PlaybookRun

ROLES = ("owner", "second-in-command", "practice")
ROLE_LABELS = {"owner": "Owner", "second-in-command": "Second-in-command",
               "practice": "The practice"}
_WEEKS = re.compile(r"^weeks?\s+(\d+)(?:\s*[-–]\s*(\d+))?$", re.I)


class PlaybookError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


@dataclass
class PTask:
    title: str
    week: int
    role: str


@dataclass
class PProject:
    title: str
    first_week: int
    last_week: int
    tasks: list = field(default_factory=list)


@dataclass
class Outline:
    goal: str
    why: str
    projects: list

    @property
    def weeks(self) -> int:
        return max((p.last_week for p in self.projects), default=0)

    @property
    def task_count(self) -> int:
        return sum(len(p.tasks) for p in self.projects)


def _weeks(text: str, line_no: int) -> tuple[int, int]:
    found = _WEEKS.match(text.strip())
    if not found:
        raise PlaybookError(f"Line {line_no}: write the weeks as \"week 3\" or \"weeks 3-4\".")
    first = int(found.group(1))
    last = int(found.group(2) or first)
    if first < 1 or last < first or last > 104:
        raise PlaybookError(f"Line {line_no}: the weeks run from 1, and the last is not "
                            "before the first.")
    return first, last


def parse(text: str) -> Outline:
    """The outline, or a `PlaybookError` naming the first line that is wrong."""
    goal, why, projects = "", "", []
    for line_no, raw in enumerate((text or "").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        if line.lower().startswith("goal:"):
            goal = line[5:].strip()
        elif line.lower().startswith("why:"):
            why = line[4:].strip()
        elif line.startswith("##"):
            parts = [p.strip() for p in line[2:].split("|")]
            if not parts[0]:
                raise PlaybookError(f"Line {line_no}: a project needs a name.")
            first, last = _weeks(parts[1], line_no) if len(parts) > 1 else (1, 1)
            projects.append(PProject(parts[0][:255], first, last))
        elif line.startswith("-"):
            if not projects:
                raise PlaybookError(f"Line {line_no}: a task sits under a project "
                                    "(a line starting \"##\").")
            parts = [p.strip() for p in line[1:].split("|")]
            project = projects[-1]
            if not parts[0]:
                raise PlaybookError(f"Line {line_no}: a task needs a name.")
            week = _weeks(parts[1], line_no)[0] if len(parts) > 1 and parts[1] else \
                project.first_week
            role = (parts[2].lower() if len(parts) > 2 and parts[2] else "practice")
            if role not in ROLES:
                raise PlaybookError(f"Line {line_no}: the owner is owner, second-in-command "
                                    "or practice.")
            project.tasks.append(PTask(parts[0][:255], week, role))
        else:
            raise PlaybookError(f"Line {line_no}: start it with \"Goal:\", \"Why:\", "
                                "\"##\" for a project or \"-\" for a task.")
    if not goal:
        raise PlaybookError("The outline needs a \"Goal:\" line.")
    if not projects:
        raise PlaybookError("The outline needs at least one project (a line starting \"##\").")
    return Outline(goal[:255], why, projects)


# ------------------------------------------------------------- copies

def offered(tenant) -> list[dict]:
    """The practice's playbooks, and every shipped one of a module it has on
    that it has not copied yet."""
    from apps.centers import services

    own = list(Playbook.all_objects.filter(tenant=tenant, archived_at__isnull=True)
               .order_by("name"))
    copied = {p.source_key for p in own if p.source_key}
    on = set(services.enabled(tenant.pk))
    out = [represent(p) for p in own]
    for key, (code, name, description, outline) in catalog.shipped_playbooks().items():
        if code in on and key not in copied:
            out.append({"id": None, "key": key, "name": name, "description": description,
                        "center": code, "center_name": catalog.NAMES[code], "is_draft": True,
                        "shipped": True, **_summary(outline)})
    return out


def _summary(outline_text: str) -> dict:
    try:
        outline = parse(outline_text)
    except PlaybookError:
        return {"weeks": 0, "projects": 0, "tasks": 0}
    return {"weeks": outline.weeks, "projects": len(outline.projects),
            "tasks": outline.task_count}


def represent(playbook: Playbook) -> dict:
    return {"id": str(playbook.pk), "key": playbook.source_key, "name": playbook.name,
            "description": playbook.description, "center": playbook.center,
            "center_name": catalog.NAMES.get(playbook.center, ""),
            "is_draft": playbook.is_draft, "shipped": False, "outline": playbook.outline,
            "updated_at": playbook.updated_at.isoformat(), **_summary(playbook.outline)}


def copy_shipped(tenant, key: str, *, actor=None) -> Playbook:
    """The practice's copy of a shipped playbook, made now if it has none."""
    from apps.centers import services

    shipped = catalog.shipped_playbooks().get(key)
    if shipped is None:
        raise PlaybookError("There is no such playbook.", 404)
    code, name, description, outline = shipped
    existing = Playbook.all_objects.filter(tenant=tenant, source_key=key).first()
    if existing is not None:
        return existing
    if not services.has(tenant.pk, code):
        raise PlaybookError(f"Turn on the {catalog.NAMES[code]} to use its playbooks.", 403)
    try:
        with transaction.atomic():
            return Playbook.all_objects.create(
                tenant=tenant, name=name, description=description, center=code,
                source_key=key, is_draft=True, outline=outline, updated_by=actor)
    except IntegrityError:
        return Playbook.all_objects.get(tenant=tenant, source_key=key)


def save(playbook: Playbook, *, name=None, description=None, outline=None,
         ready=None, actor=None) -> Playbook:
    """An edit. Saving the outline makes the copy the practice's: it is no
    longer a draft."""
    if outline is not None:
        parse(outline)
        playbook.outline = outline
        playbook.is_draft = False
    if name is not None:
        if not name.strip():
            raise PlaybookError("A playbook needs a name.")
        playbook.name = name.strip()[:160]
    if description is not None:
        playbook.description = description.strip()
    if ready:
        playbook.is_draft = False
    playbook.updated_by = actor
    playbook.save()
    return playbook


# ------------------------------------------------------------- starting

def due(start: date, week: int) -> date:
    """The fifth day of the week: Friday when it starts on a Monday."""
    return start + timedelta(days=7 * (week - 1) + 4)


@transaction.atomic
def start(playbook: Playbook, *, company, start_date: date, lead, owner_contact=None,
          second_contact=None, actor, role) -> PlaybookRun:
    """The goal, its projects and their tasks, with real dates, on `company`.
    `lead` is the practice's person: every item's owner. The owner and the
    second-in-command are the client's contacts named for those roles; a task
    of theirs carries them as its client owner."""
    from apps.work.models import Goal, Project, TaskUpdate
    from apps.work.services import create_task

    if playbook.is_draft:
        raise PlaybookError("This playbook is a draft. Edit it, or mark it ready, before "
                            "its first use.", 409)
    if playbook.archived_at is not None:
        raise PlaybookError("This playbook is archived.", 409)
    outline = parse(playbook.outline)
    tenant = playbook.tenant
    contacts = {"owner": owner_contact, "second-in-command": second_contact, "practice": None}
    goal = Goal.objects.create(
        tenant=tenant, title=outline.goal, description=outline.why, client_company=company,
        owner=lead, client_owner_contact=owner_contact,
        target_date=due(start_date, outline.weeks))
    # P11: the playbook's goal on the company plan's year.
    from apps.plans import services as plans

    plans.put_goal_on_year(company, goal, actor=actor, day=start_date, source_id=playbook.pk)
    tasks = 0
    for project_outline in outline.projects:
        project = Project.objects.create(
            tenant=tenant, goal=goal, title=project_outline.title, client_company=company,
            owner=lead, start_date=start_date + timedelta(days=7 * (project_outline.first_week
                                                                    - 1)),
            target_date=due(start_date, project_outline.last_week))
        for task in project_outline.tasks:
            who = contacts[task.role]
            note = "" if who is not None or task.role == "practice" else \
                f"For the client's {ROLE_LABELS[task.role].lower()}."
            create_task(tenant=tenant, actor=actor, role=role,
                        source=TaskUpdate.Source.PLAYBOOK, source_id=playbook.pk,
                        title=task.title, description=note, client_company=company,
                        project=project, owner=lead, client_owner_contact=who,
                        due_date=due(start_date, task.week))
            tasks += 1
    run = PlaybookRun.all_objects.create(
        tenant=tenant, playbook=playbook, company=company, start_date=start_date, goal=goal,
        started_by=actor, made={"projects": len(outline.projects), "tasks": tasks})
    from apps.tenancy.models import AuditEvent

    AuditEvent.all_objects.create(
        tenant=tenant, actor=actor, verb="playbook.started", target_type="goal",
        target_id=goal.pk, payload={"playbook": playbook.name, "company": company.name,
                                    "tasks": tasks})
    return run


def runs_at(company) -> list[dict]:
    """What has been started at one company, newest first, for its page
    (2026-11-12): until then a started playbook's goal was on Work and in the
    portal but nowhere on the company's own page. A run whose goal has since
    been deleted is listed without one."""
    rows = (PlaybookRun.objects.filter(company=company)
            .select_related("playbook", "goal").order_by("-start_date", "-created_at"))
    out = []
    for run in rows:
        goal = run.goal if run.goal is not None and run.goal.deleted_at is None else None
        out.append({"id": str(run.pk), "playbook": run.playbook.name,
                    "start_date": run.start_date.isoformat(),
                    "goal": str(goal.pk) if goal else None,
                    "goal_title": goal.title if goal else "",
                    "projects": run.made.get("projects", 0), "tasks": run.made.get("tasks", 0)})
    return out


def next_monday(today=None) -> date:
    today = today or timezone.localdate()
    return today + timedelta(days=(7 - today.weekday()) % 7 or 7)
