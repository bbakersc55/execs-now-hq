"""Onboarding and offboarding checklists, and the access list (2026-11-17).

Each checklist has three sections, **People, IT and Manager**. A company's
items start as a copy of the People Command Center's standard ones
(`apps/centers/content/people.py`) the first time its checklists are opened;
it adds, edits, reorders and archives its own from there, and adds fields of
its own to either checklist.

**Starting one** makes each item a task in Work, with its owner and a due date
counted from the start date (onboarding) or the last day (offboarding).
Owners: **People** items go to whoever starts it, **IT** items to the IT owner
chosen then (whoever starts it, if no one is chosen), **Manager** items to
the person's manager's sign-in, and an item for the person themself to their
own sign-in; where there is no sign-in, to whoever starts it. The tasks are
the practice's: not shown to the client in Work, never to an AI app; a client
user owning one sees and finishes it on People. Done in Work is done here.

**Offboarding** takes a last day and a reason, and adds a revoke item for
every entry on the access list still given (and for any entry added while it
is open). It **closes only when every item is done, or waived with a note**,
and then the person is ended and their revoked entries marked. **It never ends
anyone in a payroll system**: a person does that, in the payroll provider.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from apps.people.models import (
    AccessEntry, Checklist, ChecklistItem, Kind, OwnerRole, PersonRecord, Section, Status,
    TemplateItem,
)
from apps.people.services import PeopleRefused, _a_date, custom_values, set_custom

SECTION_ORDER = {Section.PEOPLE: 0, Section.IT: 1, Section.MANAGER: 2}
NO_PAYROLL = ("This doesn't end anyone in payroll: a person does that in the payroll "
              "provider.")


# ------------------------------------------------------------ the template

def ensure_template(tenant, company, kind) -> list[TemplateItem]:
    """The company's items, copied from the standard ones the first time."""
    from apps.centers.content import people as shipped

    rows = TemplateItem.all_objects.filter(tenant=tenant, client_company=company, kind=kind)
    if not rows.exists():
        TemplateItem.all_objects.bulk_create([
            TemplateItem(tenant=tenant, client_company=company, kind=kind, section=section,
                         title=title, owner_role=role, due_days=days, position=position,
                         standard_key=key)
            for position, (key, section, title, role, days)
            in enumerate(shipped.CHECKLISTS[kind])])
    return list(rows.filter(archived_at__isnull=True).order_by("position", "created_at"))


def template_row(item: TemplateItem) -> dict:
    return {"id": str(item.pk), "kind": item.kind, "section": item.section,
            "section_label": item.get_section_display(), "title": item.title,
            "owner_role": item.owner_role, "owner_role_label": item.get_owner_role_display(),
            "due_days": item.due_days, "standard": bool(item.standard_key)}


def save_template_item(tenant, company, data, item=None) -> TemplateItem:
    made = item is None
    if made:
        kind = data.get("kind")
        if kind not in Kind.values:
            raise PeopleRefused("An item is on the onboarding or the offboarding checklist.")
        ensure_template(tenant, company, kind)
        item = TemplateItem(tenant=tenant, client_company=company, kind=kind,
                            position=TemplateItem.all_objects.filter(
                                tenant=tenant, client_company=company, kind=kind).count())
    if "title" in data or made:
        item.title = str(data.get("title") or "").strip()[:200]
        if not item.title:
            raise PeopleRefused("Say what the item is.")
    if "section" in data or made:
        if data.get("section") not in Section.values:
            raise PeopleRefused("An item is in the People, IT or Manager section.")
        item.section = data["section"]
    if "owner_role" in data or made:
        role = data.get("owner_role") or {"people": "hr", "it": "it",
                                          "manager": "manager"}.get(item.section)
        if role not in OwnerRole.values:
            raise PeopleRefused("Choose who it goes to.")
        item.owner_role = role
    if "due_days" in data:
        try:
            item.due_days = max(-365, min(365, int(data.get("due_days") or 0)))
        except (TypeError, ValueError):
            raise PeopleRefused("Days is a whole number, before (-) or after.") from None
    if data.get("archived") is True:
        item.archived_at = timezone.now()
    item.save()
    return item


def reorder_template(tenant, company, kind, ids: list) -> None:
    live = {str(i.pk): i for i in ensure_template(tenant, company, kind)}
    if set(map(str, ids)) != set(live):
        raise PeopleRefused("Send every item once, in the new order.")
    for position, key in enumerate(map(str, ids)):
        TemplateItem.all_objects.filter(pk=key).update(position=position)


# ------------------------------------------------------------ owners

def owner_choices(record) -> list[dict]:
    """Who can own items: the practice's team, and the company's sign-ins."""
    from apps.tenancy.models import CLIENT_ROLES, Membership

    rows = Membership.all_objects.filter(tenant_id=record.tenant_id,
                                         revoked_at__isnull=True).select_related("user")
    staff = rows.exclude(role__in=CLIENT_ROLES)
    client = rows.filter(client_company_id=record.client_company_id) \
        if record.client_company_id else rows.none()
    return [{"id": str(m.user_id), "name": m.user.full_name or m.user.email,
             "side": "client" if m.role in CLIENT_ROLES else "practice"}
            for m in list(staff) + list(client)]


def _owner(record, user_id):
    from apps.accounts.models import User

    if not user_id:
        return None
    if str(user_id) not in {c["id"] for c in owner_choices(record)}:
        raise PeopleRefused("Choose an owner from the practice's team or this company.")
    return User.objects.get(pk=user_id)


def role_of(user, tenant_id) -> str:
    from apps.tenancy.models import Membership, Role

    row = Membership.all_objects.filter(tenant_id=tenant_id, user=user,
                                        revoked_at__isnull=True).first()
    return row.role if row else Role.FF


# ------------------------------------------------------------ the tasks

def _task(item, checklist, *, actor):
    from apps.crm.models import Task
    from apps.work import services as work
    from apps.work.models import TaskUpdate

    person = checklist.person
    return work.create_task(
        tenant=person.tenant, actor=actor, role=role_of(actor, person.tenant_id),
        source=TaskUpdate.Source.SYSTEM, source_id=item.pk,
        title=f"{checklist.get_kind_display()}: {person.name} · {item.title}"[:255],
        description=(f"From {person.name}'s {checklist.get_kind_display().lower()} "
                     f"checklist on People ({item.get_section_display()})."),
        status=Task.Status.NOT_STARTED, due_date=item.due_date, owner=actor,
        assignee=item.owner, client_company=person.client_company, is_client_visible=False)


def _add_item(checklist, *, section, title, owner, due, position, actor, entry=None):
    item = ChecklistItem.all_objects.create(
        tenant_id=checklist.tenant_id, checklist=checklist, section=section, title=title[:200],
        owner=owner, due_date=due, position=position, access_entry=entry)
    item.task = _task(item, checklist, actor=actor)
    item.save(update_fields=["task", "updated_at"])
    return item


def _revoke_title(entry) -> str:
    return f"Revoke {entry.get_kind_display().lower()}: {entry.name}"


# ------------------------------------------------------------ starting

@transaction.atomic
def start(record, kind, *, actor, anchor_date=None, it_owner=None, reason="", note="",
          custom=None) -> Checklist:
    record = PersonRecord.all_objects.select_for_update().get(pk=record.pk)
    if Checklist.all_objects.filter(person=record, kind=kind, closed_at__isnull=True).exists():
        raise PeopleRefused(f"{record.name}'s {kind} is already under way.", 409)
    if kind == Kind.ONBOARDING:
        if record.status in (Status.OFFBOARDING, Status.ENDED):
            raise PeopleRefused("Onboarding is for someone joining, not someone leaving.", 409)
        anchor = anchor_date or record.start_date or timezone.localdate()
        record.status = Status.ONBOARDING
        if record.start_date is None:
            record.start_date = anchor
    elif kind == Kind.OFFBOARDING:
        if record.status in (Status.ENDED, Status.OFFER_OUT):
            raise PeopleRefused("Offboarding is for someone who works here.", 409)
        if anchor_date is None:
            raise PeopleRefused("Choose their last day.")
        if reason not in Checklist.Reason.values:
            raise PeopleRefused("Choose why they are leaving.")
        anchor = anchor_date
        record.status = Status.OFFBOARDING
    else:
        raise PeopleRefused("A checklist is onboarding or offboarding.")
    record.save(update_fields=["status", "start_date", "updated_at"])
    it = _owner(record, it_owner) or actor
    manager = record.manager.user if record.manager_id and record.manager.user_id else actor
    owners = {OwnerRole.HR: actor, OwnerRole.IT: it, OwnerRole.MANAGER: manager,
              OwnerRole.EMPLOYEE: record.user or actor}
    checklist = Checklist(tenant_id=record.tenant_id, person=record, kind=kind,
                          anchor_date=anchor, reason=reason if kind == Kind.OFFBOARDING else "",
                          note=str(note or "").strip()[:2000], hr_owner=actor, it_owner=it,
                          manager_owner=manager, started_by=actor)
    if custom:
        set_custom(checklist, kind, custom)
    checklist.save()
    template = sorted(ensure_template(record.tenant, record.client_company, kind),
                      key=lambda t: (SECTION_ORDER[t.section], t.position))
    position = 0
    for t in template:
        _add_item(checklist, section=t.section, title=t.title, owner=owners[t.owner_role],
                  due=anchor + timedelta(days=t.due_days), position=position, actor=actor)
        position += 1
    if kind == Kind.OFFBOARDING:
        for entry in record.access.filter(revoked_at__isnull=True).order_by("given_on",
                                                                           "created_at"):
            _add_item(checklist, section=Section.IT, title=_revoke_title(entry), owner=it,
                      due=anchor, position=position, actor=actor, entry=entry)
            position += 1
    _audit(record, actor, f"people.{kind}_started", anchor=anchor.isoformat(),
           reason=checklist.reason, items=position)
    return checklist


# ------------------------------------------------------------ items

def is_done(item) -> bool:
    from apps.crm.models import Task

    return item.done_at is not None or (item.task is not None
                                        and item.task.status == Task.Status.DONE)


def _set_task(item, status, actor) -> None:
    from apps.work import services as work

    if item.task is not None and item.task.status != status and item.task.deleted_at is None:
        work.apply_task_changes(item.task, actor=actor,
                                role=role_of(actor, item.tenant_id), changes={"status": status})


@transaction.atomic
def mark_done(item, *, actor) -> ChecklistItem:
    from apps.crm.models import Task

    item = ChecklistItem.all_objects.select_for_update(of=("self",)).select_related(
        "task", "checklist").get(pk=item.pk)
    if item.checklist.closed_at:
        raise PeopleRefused("That checklist is closed.", 409)
    item.done_at, item.done_by = timezone.now(), actor
    item.waived_at, item.waived_by, item.waive_note = None, None, ""
    item.save()
    _set_task(item, Task.Status.DONE, actor)
    if item.access_entry_id:
        AccessEntry.all_objects.filter(pk=item.access_entry_id, revoked_at__isnull=True).update(
            revoked_at=timezone.now(), revoked_by=actor)
    return item


@transaction.atomic
def waive(item, *, actor, note: str) -> ChecklistItem:
    from apps.crm.models import Task

    note = str(note or "").strip()
    if not note:
        raise PeopleRefused("Say why it is waived: a waived item needs a note.")
    item = ChecklistItem.all_objects.select_for_update(of=("self",)).select_related(
        "task", "checklist").get(pk=item.pk)
    if item.checklist.closed_at:
        raise PeopleRefused("That checklist is closed.", 409)
    item.waived_at, item.waived_by, item.waive_note = timezone.now(), actor, note[:1000]
    item.done_at, item.done_by = None, None
    item.save()
    _set_task(item, Task.Status.CANCELLED, actor)
    return item


@transaction.atomic
def reopen(item, *, actor) -> ChecklistItem:
    from apps.crm.models import Task

    item = ChecklistItem.all_objects.select_for_update(of=("self",)).select_related(
        "task", "checklist").get(pk=item.pk)
    if item.checklist.closed_at:
        raise PeopleRefused("That checklist is closed.", 409)
    item.done_at = item.done_by = item.waived_at = item.waived_by = None
    item.waive_note = ""
    item.save()
    _set_task(item, Task.Status.NOT_STARTED, actor)
    if item.access_entry_id:
        AccessEntry.all_objects.filter(pk=item.access_entry_id).update(revoked_at=None,
                                                                       revoked_by=None)
    return item


def open_items(checklist) -> list:
    return [i for i in checklist.items.select_related("task")
            if not is_done(i) and i.waived_at is None]


@transaction.atomic
def close(checklist, *, actor) -> Checklist:
    checklist = Checklist.all_objects.select_for_update().get(pk=checklist.pk)
    if checklist.closed_at:
        raise PeopleRefused("That checklist is closed already.", 409)
    left = open_items(checklist)
    if left:
        raise PeopleRefused(
            f"{len(left)} item{'' if len(left) == 1 else 's'} still open. Each is done, or "
            "waived with a note, before it closes.", 409)
    now = timezone.now()
    checklist.closed_at, checklist.closed_by = now, actor
    checklist.save(update_fields=["closed_at", "closed_by", "updated_at"])
    record = checklist.person
    if checklist.kind == Kind.ONBOARDING:
        record.status = Status.ACTIVE
        record.save(update_fields=["status", "updated_at"])
    else:
        for item in checklist.items.filter(access_entry__isnull=False).select_related("task"):
            if is_done(item):
                AccessEntry.all_objects.filter(pk=item.access_entry_id,
                                               revoked_at__isnull=True).update(
                    revoked_at=now, revoked_by=actor)
        record.status, record.ended_on = Status.ENDED, checklist.anchor_date
        record.save(update_fields=["status", "ended_on", "updated_at"])
    _audit(record, actor, f"people.{checklist.kind}_closed")
    return checklist


# ------------------------------------------------------------ showing

def _name(user) -> str:
    return (user.full_name or user.email) if user else ""


def item_row(item, viewer) -> dict:
    done = is_done(item)
    return {"id": str(item.pk), "section": item.section,
            "section_label": item.get_section_display(), "title": item.title,
            "owner": _name(item.owner), "mine": item.owner_id == getattr(viewer, "pk", None),
            "due_date": item.due_date.isoformat() if item.due_date else None,
            "done": done, "waived": item.waived_at is not None, "waive_note": item.waive_note,
            "revokes": str(item.access_entry_id) if item.access_entry_id else None,
            "task": str(item.task_id) if item.task_id else None}


def progress(checklist) -> dict:
    items = list(checklist.items.select_related("task"))
    done = sum(1 for i in items if is_done(i))
    waived = sum(1 for i in items if i.waived_at is not None and not is_done(i))
    return {"id": str(checklist.pk), "kind": checklist.kind,
            "kind_label": checklist.get_kind_display(), "done": done, "waived": waived,
            "total": len(items), "closed": checklist.closed_at is not None,
            "anchor_date": checklist.anchor_date.isoformat()}


def represent(checklist, viewer) -> dict:
    items = sorted(checklist.items.select_related("task", "owner"),
                   key=lambda i: (SECTION_ORDER[i.section], i.position))
    rows = [item_row(i, viewer) for i in items]
    return {**progress(checklist), "reason": checklist.reason,
            "reason_label": checklist.get_reason_display() if checklist.reason else "",
            "note": checklist.note, "started_at": checklist.created_at.isoformat(),
            "closed_at": checklist.closed_at.isoformat() if checklist.closed_at else None,
            "owners": {"hr": _name(checklist.hr_owner), "it": _name(checklist.it_owner),
                       "manager": _name(checklist.manager_owner)},
            "custom": custom_values(checklist, checklist.kind),
            "items": rows,
            "can_close": checklist.closed_at is None
            and not any(not r["done"] and not r["waived"] for r in rows),
            "no_payroll": NO_PAYROLL if checklist.kind == Kind.OFFBOARDING else ""}


def assigned_to(user, records) -> list[dict]:
    """The open checklist items this person owns, among these records."""
    rows = (ChecklistItem.all_objects.filter(owner=user, checklist__closed_at__isnull=True,
                                             checklist__person__in=records)
            .select_related("checklist__person", "task", "owner")
            .order_by("due_date", "position"))
    return [{**item_row(i, user), "person": i.checklist.person.name,
             "person_id": str(i.checklist.person_id), "kind": i.checklist.kind,
             "kind_label": i.checklist.get_kind_display()}
            for i in rows if not is_done(i) and i.waived_at is None]


# ------------------------------------------------------------ the access list

def entry_row(entry) -> dict:
    return {"id": str(entry.pk), "kind": entry.kind, "kind_label": entry.get_kind_display(),
            "name": entry.name, "detail": entry.detail,
            "given_on": entry.given_on.isoformat() if entry.given_on else None,
            "given_by": _name(entry.given_by) or entry.given_by_name,
            "revoked_at": entry.revoked_at.isoformat() if entry.revoked_at else None,
            "revoked_by": _name(entry.revoked_by)}


@transaction.atomic
def save_entry(record, data, *, actor, entry=None) -> AccessEntry:
    made = entry is None
    if made:
        entry = AccessEntry(tenant_id=record.tenant_id, person=record)
    if "kind" in data or made:
        if data.get("kind") not in AccessEntry.Kind.values:
            raise PeopleRefused("Choose a system, email account, phone number, equipment or "
                                "a key.")
        entry.kind = data["kind"]
    if "name" in data or made:
        entry.name = str(data.get("name") or "").strip()[:200]
        if not entry.name:
            raise PeopleRefused("Say what it is.")
    if "detail" in data:
        entry.detail = str(data.get("detail") or "").strip()[:300]
    if "given_on" in data or made:
        given = _a_date(data.get("given_on"), "When it was given")
        entry.given_on = date.fromisoformat(given) if given else timezone.localdate()
    if "given_by" in data or made:
        entry.given_by = _owner(record, data.get("given_by")) if data.get("given_by") else (
            actor if made and not data.get("given_by_name") else None)
        entry.given_by_name = str(data.get("given_by_name") or "").strip()[:200]
    entry.save()
    if made:
        open_off = Checklist.all_objects.filter(person=record, kind=Kind.OFFBOARDING,
                                                closed_at__isnull=True).first()
        if open_off is not None:
            _add_item(open_off, section=Section.IT, title=_revoke_title(entry),
                      owner=open_off.it_owner or actor, due=open_off.anchor_date,
                      position=open_off.items.count(), actor=actor, entry=entry)
    return entry


def remove_entry(entry, *, actor) -> None:
    if entry.revoke_items.exists():
        raise PeopleRefused("It is on an offboarding: revoke it, or waive it with a note.",
                            409)
    _audit(entry.person, actor, "people.access_removed", name=entry.name)
    entry.delete()


def _audit(record, actor, verb, **payload) -> None:
    from apps.tenancy.models import AuditEvent

    AuditEvent.all_objects.create(tenant_id=record.tenant_id, actor=actor, verb=verb,
                                  target_type="person_record", target_id=record.pk,
                                  payload=payload)

