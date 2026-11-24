"""The onboarding checklist made after a successful send: one project per
property under the company, its tasks from the form's template, assigned to
whoever pressed Send.

Titles are generic and never carry the owner's name or contact details; the
street address may appear in the project's name (owner, 2026-11-19). Due
dates count from the owner's ready date, or from the day it was sent when the
ready date is blank or already past.
"""

from __future__ import annotations

from datetime import date, timedelta

from apps.tenancy.context import tenant_context
from apps.tenancy.models import CLIENT_ROLES, Membership

from . import derive, plan
from .defaults import CHECKLIST, CHECKLIST_WHEN


def base_day(answers, sent_on: date) -> date:
    ready = derive.ready_date(answers)
    if ready:
        try:
            day = date.fromisoformat(ready)
            if day >= sent_on:
                return day
        except ValueError:
            pass
    return sent_on


def conditions(submission, *, mode: str) -> set:
    a = submission.answers or {}
    home = a.get("home") or {}
    stays = a.get("stays") or {}
    prop = a.get("property") or {}
    out = {"always"}
    if home.get("permit") != "yes" or not home.get("permit_number"):
        out.add("no_permit")
    if submission.files.exists():
        out.add("has_insurance")
    else:
        out.add("no_insurance")
    if prop.get("has_bookings") == "yes":
        out.add("has_bookings")
    if stays.get("has") == "yes" and stays.get("ranges"):
        out.add("has_owner_dates")
    if mode == "existing" and len(plan.people(a)) > 1:
        out.add("existing_owner_new_people")
    emergency = (a.get("about") or {}).get("emergency") or {}
    if mode == "existing" and (emergency.get("name") or emergency.get("phone")):
        out.add("existing_owner_emergency")
    return out


def create(submission, *, sender, mode: str, sent_on: date) -> list:
    """The project and its tasks. Returns the tasks."""
    from apps.work import services as work
    from apps.work.models import Project, TaskUpdate

    template = (submission.form.settings or {}).get("checklist") or CHECKLIST
    wanted = conditions(submission, mode=mode)
    start = base_day(submission.answers or {}, sent_on)
    membership = Membership.all_objects.filter(tenant_id=submission.tenant_id, user=sender,
                                               revoked_at__isnull=True).first()
    role = membership.role if membership else None
    is_client = role in CLIENT_ROLES
    street = derive.street_line((submission.answers or {}).get("property"))
    title = f"New owner onboarding #{submission.number}" + (f" · {street}" if street else "")
    tasks = []
    with tenant_context(submission.tenant_id):
        project = Project.objects.create(
            tenant=submission.tenant, title=title[:255], client_company=submission.company,
            owner=None if is_client else sender, created_by_client=is_client,
            start_date=start,
            description="Made by sending the owner intake to Track. The intake's answers "
                        "are on its review screen in the app.")
        for item in template:
            if item.get("when", "always") not in CHECKLIST_WHEN or item["when"] not in wanted:
                continue
            due = start + timedelta(days=int(item.get("offset_days") or 0))
            tasks.append(work.create_task(
                tenant=submission.tenant, actor=sender, role=role,
                source=TaskUpdate.Source.INTAKE, source_id=submission.pk,
                title=item["title"][:255], due_date=due, project=project,
                assignee=sender, owner=None if is_client else sender,
                client_company=submission.company))
    submission.project = project
    submission.save(update_fields=["project"])
    return tasks
