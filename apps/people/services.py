"""People: the employee record at a level, changing it, its directory,
exporting, and the access log (2026-11-17; the records, the same day).

A record shows in sections. **Directory** (name, title, department, team,
work email and phone, manager) to anyone who reaches the person;
**employment** (status, type, work state, start date, the company's own
fields, the access list and checklists) to HR permissions and the person
themself; **sensitive** (pay, home address, date of birth, personal phone and
email, emergency contact, documents) encrypted, in full to an HR Director and
the person themself, masked to an HR Generalist. Every view, change and
export of sensitive data is logged; every export is logged, whatever it held.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date, timedelta

from django.utils import timezone

from apps.people import access as A
from apps.people.models import (
    DIRECTORY, DIRECTORY_LABELS, EMPLOYMENT, HELD_IN_PAYROLL, SENSITIVE, SENSITIVE_LABELS,
    EmploymentType, PayUnit, PeopleAccessLog, PeopleCustomField, PersonRecord, Status, Target,
)

GUIDANCE = "HR guidance, not legal advice"
#: Client users are counted in blocks of this many, at $10 a block (P9 "Price").
BLOCK = 25
BLOCK_CENTS = 1000
#: A work state's name, for an offer letter: its two letters, then its name.
STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota",
    "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee",
    "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
STATES = tuple(STATE_NAMES)
#: A custom field's label naming something never stored is refused.
NEVER_WORDS = re.compile(
    r"social\s*security|\bssn\b|\bsin\b|tax\s*id|\btin\b|\bbank|routing|account\s*(no|num)|"
    r"\bi-?9\b|medical|health|diagnos|disabilit|leave\s*paper|\bfmla\b|background\s*check|"
    r"criminal|benefit|insurance|\bhsa\b|\b401", re.I)


class PeopleRefused(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# --------------------------------------------------------- the sensitive fields

def read_sensitive(record) -> dict:
    from apps.crm.services.secrets import decrypt

    if not record.sensitive_ciphertext:
        return {}
    return json.loads(decrypt(bytes(record.sensitive_ciphertext)))


def _a_date(value, what) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise PeopleRefused(f"{what} is a date (YYYY-MM-DD).") from None


def _clean_sensitive(key, value):
    if key == "pay_unit":
        value = str(value or "").strip()
        if value and value not in PayUnit.values:
            raise PeopleRefused("Pay is by the hour, week, month, year or project.")
        return value
    if key in ("pay_effective_on", "date_of_birth"):
        return _a_date(value, SENSITIVE_LABELS[key])
    return str(value or "").strip()[:500]


def write_sensitive(record, values: dict) -> list[str]:
    """Encrypt the sensitive fields; return the ones that changed. Documents
    are files of their own (`PersonDocument`), not kept here."""
    from apps.crm.services.secrets import encrypt

    was = read_sensitive(record)
    clean = {}
    for key in SENSITIVE:
        if key == "documents":
            continue
        clean[key] = _clean_sensitive(key, values[key]) if key in values else was.get(key, "")
    changed = [k for k in SENSITIVE if k != "documents"
               and (clean.get(k) or "") != (was.get(k) or "")]
    record.sensitive_ciphertext = encrypt(json.dumps(clean))
    return changed


# ------------------------------------------------------------- showing

def sees_employment(access: A.Access, record) -> bool:
    return access.hr or record.pk in access.own


def directory_row(record, access: A.Access) -> dict:
    return {
        "id": str(record.pk), "name": record.name, "first_name": record.first_name,
        "last_name": record.last_name, "title": record.title, "department": record.department,
        "team": record.team, "work_email": record.work_email, "work_phone": record.work_phone,
        "manager": ({"id": str(record.manager_id), "name": record.manager.name}
                    if record.manager_id else None),
        "own": record.pk in access.own,
        "placeholder": record.is_placeholder,
    }


def employment_row(record) -> dict:
    return {"status": record.status, "status_label": record.get_status_display(),
            "employment_type": record.employment_type,
            "employment_type_label": record.get_employment_type_display(),
            "work_state": record.work_state,
            "start_date": record.start_date.isoformat() if record.start_date else None,
            "ended_on": record.ended_on.isoformat() if record.ended_on else None,
            "has_sign_in": record.user_id is not None}


def list_row(record, access: A.Access) -> dict:
    """A row of the directory: directory fields, and employment ones where
    this access sees them. Never a sensitive field: those are on the person's
    page, where viewing them is logged."""
    row = directory_row(record, access)
    if sees_employment(access, record):
        row.update(employment_row(record))
    return row


def represent(record, access: A.Access) -> tuple[dict, list[str]]:
    """The record at this access, by section, and the sensitive fields shown
    unmasked (what the access log records as viewed)."""
    from apps.people import files

    row = directory_row(record, access)
    if access.level == A.DIRECTORY or (access.level == A.REPORTS
                                       and record.pk not in access.own):
        return row, []
    row["employment"] = employment_row(record)
    row["custom"] = custom_values(record, Target.RECORD)
    row["held_in_payroll"] = HELD_IN_PAYROLL
    values = read_sensitive(record)
    documents = files.listed(record)
    if A.sees_in_full(access, record):
        row["sensitive"] = {k: values.get(k, "") for k in SENSITIVE if k != "documents"}
        row["documents"] = documents
        row["masked"] = False
        shown = [k for k in SENSITIVE if k != "documents" and values.get(k)]
        return row, shown + (["documents"] if documents else [])
    row["sensitive"] = {k: A.mask(values.get(k, "")) for k in SENSITIVE if k != "documents"}
    row["documents"] = A.mask([d["title"] for d in documents])
    row["masked"] = True
    return row, []


def log(request, record, action: str, fields: list[str]) -> None:
    """One row of the access log, written once."""
    from apps.accounts.ratelimit import client_ip

    if not fields:
        return
    user = request.user
    PeopleAccessLog.all_objects.create(
        tenant_id=record.tenant_id, actor=user, actor_name=user.full_name or user.email,
        person=record, person_name=record.name, client_company_id=record.client_company_id,
        action=action, fields=list(fields), ip_address=client_ip(request) or None,
        user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:300])


def records_for(tenant_id, company):
    return (PersonRecord.all_objects.filter(tenant_id=tenant_id, client_company=company)
            .select_related("manager").order_by("last_name", "first_name"))


def show_records(request, access, tenant_id, company) -> list[dict]:
    return [list_row(r, access) for r in A.visible(access, records_for(tenant_id, company))]


# ------------------------------------------------------------ the directory

def headcount(records) -> list[dict]:
    counts = {s: 0 for s in Status.values}
    for record in records:
        counts[record.status] = counts.get(record.status, 0) + 1
    return [{"status": s, "label": Status(s).label, "count": counts[s]} for s in Status.values]


def _next(day: date, today: date) -> date:
    for year in (today.year, today.year + 1):
        try:
            when = day.replace(year=year)
        except ValueError:            # 29 February, in a year without one
            when = date(year, 3, 1)
        if when >= today:
            return when
    return today


def upcoming(records, today: date | None = None, days: int = 30) -> dict:
    """Work anniversaries and birthdays in the next `days`: a birthday as its
    day and month only, never the year."""
    today = today or timezone.localdate()
    until = today + timedelta(days=days)
    anniversaries, birthdays = [], []
    for record in records:
        if record.status in (Status.OFFER_OUT, Status.ENDED):
            continue
        if record.start_date and record.start_date < today:
            when = _next(record.start_date, today)
            years = when.year - record.start_date.year
            if years >= 1 and when <= until:
                anniversaries.append({"id": str(record.pk), "name": record.name,
                                      "on": when.isoformat(), "years": years})
        born = read_sensitive(record).get("date_of_birth") or ""
        try:
            born = date.fromisoformat(born) if born else None
        except ValueError:
            born = None
        if born:
            when = _next(born, today)
            if when <= until:
                birthdays.append({"id": str(record.pk), "name": record.name,
                                  "day": f"{when:%B} {when.day}", "on": when.isoformat()})
    return {"anniversaries": sorted(anniversaries, key=lambda r: r["on"]),
            "birthdays": [{k: v for k, v in b.items() if k != "on"}
                          for b in sorted(birthdays, key=lambda r: r["on"])]}


def org_chart(tenant, records) -> dict:
    """The chart drawn from managers, by the tools' own drawing."""
    from apps.crm.services.email_layout import branding
    from apps.tools import orgchart

    rows = [{"id": str(r.pk), "name": r.name, "title": r.title or "",
             "department": r.department or r.team or "",
             "manager_id": str(r.manager_id) if r.manager_id else ""}
            for r in records if r.status != Status.ENDED]
    view = {"key": "id", "parent": "manager_id", "name": "name", "person": "title",
            "department": "department", "checks": (), "people": True}
    return orgchart.drawing(rows, view, branding(tenant))


def client_users(tenant_id, company) -> dict | None:
    """Portal sign-ins and employee records, each person once: client users,
    counted in blocks of 25 at $10 a block. Ended records are not counted."""
    from apps.tenancy.models import CLIENT_ROLES, Membership

    if company is None:
        return None
    members = set(Membership.all_objects.filter(
        tenant_id=tenant_id, client_company_id=company.pk, revoked_at__isnull=True,
        role__in=CLIENT_ROLES).values_list("user_id", flat=True))
    extra = (PersonRecord.all_objects.filter(tenant_id=tenant_id, client_company=company)
             .exclude(status=Status.ENDED)
             .exclude(user_id__in=members).count())
    total = len(members) + extra
    blocks = math.ceil(total / BLOCK) if total else 0
    return {"sign_ins": len(members), "records_without_sign_in": extra, "total": total,
            "blocks": blocks, "block_size": BLOCK, "cents": blocks * BLOCK_CENTS}


# ------------------------------------------------------------ custom fields

def custom_fields(tenant_id, company, target) -> list:
    return list(PeopleCustomField.all_objects.filter(
        tenant_id=tenant_id, client_company=company, target=target, archived_at__isnull=True)
        .order_by("position", "created_at"))


def custom_values(owner, target) -> list[dict]:
    company = owner.client_company if target == Target.RECORD else owner.person.client_company
    values = owner.custom_values or {}
    return [{"id": str(f.pk), "label": f.label, "value": values.get(str(f.pk), "")}
            for f in custom_fields(owner.tenant_id, company, target)]


def set_custom(owner, target, values: dict) -> None:
    company = owner.client_company if target == Target.RECORD else owner.person.client_company
    live = {str(f.pk) for f in custom_fields(owner.tenant_id, company, target)}
    kept = dict(owner.custom_values or {})
    for key, value in (values or {}).items():
        if str(key) not in live:
            raise PeopleRefused("That field isn't one of this company's.")
        kept[str(key)] = str(value or "").strip()[:300]
    owner.custom_values = kept


def save_field(tenant, company, data, *, actor, field=None) -> PeopleCustomField:
    label = str(data.get("label") or "").strip()[:80] if "label" in data or field is None \
        else field.label
    if not label:
        raise PeopleRefused("Give the field a name.")
    if NEVER_WORDS.search(label):
        raise PeopleRefused(f"No field for that: {HELD_IN_PAYROLL}")
    if field is None:
        target = data.get("target")
        if target not in Target.values:
            raise PeopleRefused("A field is on the record, onboarding or offboarding.")
        last = len(custom_fields(tenant.pk, company, target))
        return PeopleCustomField.all_objects.create(
            tenant=tenant, client_company=company, target=target, label=label, position=last,
            created_by=actor)
    field.label = label
    if data.get("archived") is True:
        field.archived_at = timezone.now()
    field.save()
    return field


def reorder_fields(tenant_id, company, target, ids: list) -> None:
    fields = {str(f.pk): f for f in custom_fields(tenant_id, company, target)}
    if set(map(str, ids)) != set(fields):
        raise PeopleRefused("Send every field once, in the new order.")
    for position, key in enumerate(map(str, ids)):
        PeopleCustomField.all_objects.filter(pk=key).update(position=position)


# ------------------------------------------------------------ changing

PLAIN = ("first_name", "last_name", "title", "department", "team", "work_email", "work_phone")


def _plain(record, data) -> None:
    for key in PLAIN:
        if key in data:
            limit = 40 if key == "work_phone" else 120
            setattr(record, key, str(data.get(key) or "").strip()[:limit])
    if "employment_type" in data:
        if data["employment_type"] not in EmploymentType.values:
            raise PeopleRefused("Employment type is full-time, part-time or contractor.")
        record.employment_type = data["employment_type"]
    if "work_state" in data:
        state = str(data.get("work_state") or "").strip().upper()
        if state and state not in STATES:
            raise PeopleRefused("Work state is a state's two letters, such as UT.")
        record.work_state = state
    if "start_date" in data:
        record.start_date = date.fromisoformat(_a_date(data["start_date"], "The start date")) \
            if data.get("start_date") else None
    if "status" in data:
        # Onboarding, offboarding and ended follow their checklists; an offer
        # follows its letter. By hand: active and on leave, back and forth.
        if data["status"] not in (Status.ACTIVE, Status.ON_LEAVE) \
                or record.status not in (Status.ACTIVE, Status.ON_LEAVE):
            raise PeopleRefused("By hand, a status moves between active and on leave. "
                                "Onboarding, offboarding and ended follow their checklists.")
        record.status = data["status"]


def save_record(request, access, tenant, company, data, record=None) -> PersonRecord:
    """A record, made or changed: an HR Director's alone."""
    from apps.tenancy.models import CLIENT_ROLES, Membership

    if access.level != A.DIRECTOR:
        raise PeopleRefused("Only an HR Director adds or changes a person.", 403)
    made = record is None
    if made:
        record = PersonRecord(tenant=tenant, client_company=company, created_by=request.user,
                              is_placeholder=False, status=Status.ACTIVE)
        if data.get("offer") is True:
            if company is None:
                raise PeopleRefused("Offer letters go from a client company's People page.")
            record.status = Status.OFFER_OUT
    before_plain = {k: getattr(record, k) for k in PLAIN + EMPLOYMENT}
    _plain(record, data)
    if not record.first_name:
        raise PeopleRefused("A person needs a first name.")
    if "manager" in data:
        manager = data.get("manager")
        record.manager = (records_for(tenant.pk, company).filter(pk=manager).first()
                          if manager else None)
        if manager and record.manager is None:
            raise PeopleRefused("Their manager is someone here.")
        if record.manager is not None and record.manager.pk == record.pk:
            raise PeopleRefused("Someone isn't their own manager.")
        boss = record.manager
        while boss is not None and not made:
            if boss.pk == record.pk:
                raise PeopleRefused("That would make a loop of managers.")
            boss = boss.manager
    if "member" in data:
        member = data.get("member")
        found = None
        if member:
            found = Membership.all_objects.filter(pk=member, tenant=tenant,
                                                  revoked_at__isnull=True).first()
            if found is None or (company is None and found.role in CLIENT_ROLES) or (
                    company is not None and found.client_company_id != company.pk):
                raise PeopleRefused("Their sign-in is someone of this company.")
            taken = PersonRecord.all_objects.filter(
                tenant=tenant, client_company=company, user_id=found.user_id).exclude(
                pk=record.pk).exists()
            if taken:
                raise PeopleRefused("That sign-in is on someone else's record already.")
        record.user = found.user if found else None
    if "custom" in data:
        set_custom(record, Target.RECORD, data.get("custom") or {})
    changed = write_sensitive(record, data.get("sensitive") or {}) \
        if "sensitive" in data or made else []
    record.save()
    if not made:
        log(request, record, PeopleAccessLog.Action.CHANGE, changed)
        moved = [k for k, v in before_plain.items() if getattr(record, k) != v]
        if moved:
            _audit(record, request.user, "people.record_changed", fields=moved)
    else:
        _audit(record, request.user, "people.record_added", status=record.status)
    return record


def _audit(record, actor, verb, **payload) -> None:
    from apps.tenancy.models import AuditEvent

    AuditEvent.all_objects.create(tenant_id=record.tenant_id, actor=actor, verb=verb,
                                  target_type="person_record", target_id=record.pk,
                                  payload=payload)


# ------------------------------------------------------------ exporting

def export_csv(request, access, tenant_id, company, *, sensitive: bool = False) -> str:
    """The directory as a spreadsheet (CSV). Sensitive fields only when an HR
    Director asks for them. Every export is logged, person by person, with
    the fields it held."""
    import csv
    import io

    if access.level not in A.HR_LEVELS:
        raise PeopleRefused("Only HR permissions export.", 403)
    if sensitive and access.level != A.DIRECTOR:
        raise PeopleRefused("Only an HR Director exports sensitive fields.", 403)
    plain = [k for k in SENSITIVE if k != "documents"]
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([DIRECTORY_LABELS[k] for k in DIRECTORY]
                    + ["Status", "Employment type", "Work state", "Start date"]
                    + ([SENSITIVE_LABELS[k] for k in plain] if sensitive else []))
    for record in A.visible(access, records_for(tenant_id, company)):
        row = list_row(record, access)
        values = read_sensitive(record) if sensitive else {}
        writer.writerow([row["name"], row["title"], row["department"], row["team"],
                         row["work_email"], row["work_phone"],
                         row["manager"]["name"] if row["manager"] else "",
                         row.get("status_label", ""), row.get("employment_type_label", ""),
                         row.get("work_state", ""), row.get("start_date") or ""]
                        + ([values.get(k, "") for k in plain] if sensitive else []))
        held = list(DIRECTORY) + list(EMPLOYMENT) + \
            ([k for k in plain if values.get(k)] if sensitive else [])
        log(request, record, PeopleAccessLog.Action.EXPORT, held)
    return out.getvalue()


# ------------------------------------------------------------ the log

def access_log(tenant_id, company, limit=200) -> list[dict]:
    rows = (PeopleAccessLog.all_objects.filter(tenant_id=tenant_id, client_company=company)
            .order_by("-created_at")[:limit])
    return [{"at": r.created_at.isoformat(), "who": r.actor_name, "person": r.person_name,
             "action": r.action, "action_label": r.get_action_display(),
             "fields": r.fields, "from": r.ip_address or "", "browser": r.user_agent}
            for r in rows]
