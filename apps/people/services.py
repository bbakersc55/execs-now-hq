"""People: showing a record at a level, changing it, exporting, and the
access log (2026-11-17)."""

from __future__ import annotations

import json

from apps.people import access as A
from apps.people.models import SENSITIVE, PeopleAccessLog, PersonRecord

GUIDANCE = "HR guidance, not legal advice"


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


def write_sensitive(record, values: dict) -> list[str]:
    """Encrypt the sensitive fields; return the ones that changed."""
    from apps.crm.services.secrets import encrypt

    was = read_sensitive(record)
    clean = {}
    for key in SENSITIVE:
        value = values.get(key, was.get(key))
        if key == "documents":
            value = [str(v)[:200] for v in (value or []) if str(v).strip()][:50]
        else:
            value = str(value or "").strip()[:500]
        clean[key] = value
    changed = [k for k in SENSITIVE if clean.get(k) != was.get(k) and (clean.get(k) or was.get(k))]
    record.sensitive_ciphertext = encrypt(json.dumps(clean))
    return changed


# ------------------------------------------------------------- showing

def represent(record, access: A.Access) -> tuple[dict, list[str]]:
    """The record at this access, and the sensitive fields shown unmasked
    (what the access log records as viewed)."""
    row = {
        "id": str(record.pk), "name": record.name, "first_name": record.first_name,
        "last_name": record.last_name, "title": record.title, "team": record.team,
        "work_email": record.work_email,
        "manager": ({"id": str(record.manager_id), "name": record.manager.name}
                    if record.manager_id else None),
        "own": record.pk in access.own,
        "placeholder": record.is_placeholder,
    }
    if access.level == A.DIRECTORY or (access.level == A.REPORTS
                                       and record.pk not in access.own):
        return row, []
    values = read_sensitive(record)
    if A.sees_in_full(access, record):
        row["sensitive"] = {k: values.get(k, [] if k == "documents" else "") for k in SENSITIVE}
        row["masked"] = False
        return row, [k for k in SENSITIVE if values.get(k)]
    row["sensitive"] = {k: A.mask(values.get(k, [] if k == "documents" else ""))
                        for k in SENSITIVE}
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
    out = []
    for record in A.visible(access, records_for(tenant_id, company)):
        row, shown = represent(record, access)
        log(request, record, PeopleAccessLog.Action.VIEW, shown)
        out.append(row)
    return out


# ------------------------------------------------------------ changing

def save_record(request, access, tenant, company, data, record=None) -> PersonRecord:
    """A placeholder person, made or changed: an HR Director's alone."""
    from apps.tenancy.models import CLIENT_ROLES, Membership

    if access.level != A.DIRECTOR:
        raise PeopleRefused("Only an HR Director adds or changes a person.", 403)
    made = record is None
    if made:
        record = PersonRecord(tenant=tenant, client_company=company, created_by=request.user)
    for key in ("first_name", "last_name", "title", "team", "work_email"):
        if key in data:
            setattr(record, key, str(data.get(key) or "").strip()[:120])
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
    if "member" in data:
        member = data.get("member")
        found = None
        if member:
            found = Membership.all_objects.filter(pk=member, tenant=tenant,
                                                  revoked_at__isnull=True).first()
            if found is None or (company is None and found.role in CLIENT_ROLES) or (
                    company is not None and found.client_company_id != company.pk):
                raise PeopleRefused("Their sign-in is someone of this company.")
        record.user = found.user if found else None
    changed = write_sensitive(record, data.get("sensitive") or {}) \
        if "sensitive" in data or made else []
    record.save()
    if not made:
        log(request, record, PeopleAccessLog.Action.CHANGE, changed)
    return record


# ------------------------------------------------------------ exporting

def export_csv(request, access, tenant_id, company) -> str:
    import csv
    import io

    from apps.people.models import SENSITIVE_LABELS

    if access.level not in A.HR_LEVELS:
        raise PeopleRefused("Only HR permissions export.", 403)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Name", "Title", "Team", "Work email", "Manager",
                     *[SENSITIVE_LABELS[k] for k in SENSITIVE]])
    for record in A.visible(access, records_for(tenant_id, company)):
        row, shown = represent(record, access)
        sensitive = row.get("sensitive") or {}
        writer.writerow([row["name"], row["title"], row["team"], row["work_email"],
                         row["manager"]["name"] if row["manager"] else "",
                         *[("; ".join(v) if isinstance(v, list) else v or "")
                           for v in (sensitive.get(k) for k in SENSITIVE)]])
        log(request, record, PeopleAccessLog.Action.EXPORT, shown)
    return out.getvalue()


# ------------------------------------------------------------ the log

def access_log(tenant_id, company, limit=200) -> list[dict]:
    rows = (PeopleAccessLog.all_objects.filter(tenant_id=tenant_id, client_company=company)
            .order_by("-created_at")[:limit])
    return [{"at": r.created_at.isoformat(), "who": r.actor_name, "person": r.person_name,
             "action": r.action, "action_label": r.get_action_display(),
             "fields": r.fields, "from": r.ip_address or "", "browser": r.user_agent}
            for r in rows]
