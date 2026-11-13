"""Tools and runs (P12): who reaches them, making and changing them, and what
a run hands to the rest of the app.

- **Who:** the practice owner and associates (for their companies) make and
  edit runs; an assistant reads them. Only the practice owner builds and
  edits the practice's own tools. In the portal, the client owner and senior
  leadership see a run the practice has shared with them, read only.
- **Available** while the practice has any Command Center on.
- **Hand-offs from a run:** tasks from its flagged rows; a computed value to a
  KPI as a reading "From a tool"; an item proposed to the company's plan; an
  SOP brainstorm note with the run as its source.
"""

from __future__ import annotations

import copy
import re
from datetime import date, datetime, timedelta

from django.db import transaction
from django.http import Http404
from django.utils import timezone

from apps.tenancy.models import AuditEvent, Role

from . import definition as D
from . import shipped
from .models import Tool, ToolRun


class ToolRefused(ValueError):
    def __init__(self, message, status=400, errors=None):
        super().__init__(message)
        self.status = status
        self.errors = errors or []


def _audit(tenant_id, actor, verb, target_type, target_id, **payload):
    AuditEvent.all_objects.create(tenant_id=tenant_id, actor=actor, verb=verb,
                                  target_type=target_type, target_id=target_id, payload=payload)


def _is_uuid(value) -> bool:
    import uuid

    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, TypeError):
        return False


# ------------------------------------------------------------------ access

def available(tenant_id) -> bool:
    from apps.plans.access import available as plans_available

    return plans_available(tenant_id)


def access_for(request, company_id):
    """The plans engine's own reach rule (`apps.plans.access`): 404 for anyone
    who doesn't reach the company, and with no Command Center on."""
    from apps.plans.access import access_for as plan_access

    return plan_access(request, company_id)


def portal_has_runs(request) -> bool:
    """For the portal's menu: a run shared with this client owner or senior leader."""
    from apps.tenancy.models import CLIENT_ROLES
    from apps.work.permissions import client_scope
    from apps.work.teams import Level

    membership = getattr(request, "membership", None)
    if membership is None or membership.role not in CLIENT_ROLES \
            or not available(membership.tenant_id):
        return False
    scope = client_scope(request)
    if scope is None or not (scope.is_owner or scope.leads_all
                             or Level.LEADER in dict(scope.levels).values()):
        return False
    return ToolRun.all_objects.filter(company_id=membership.client_company_id,
                                      shared_with_client=True,
                                      archived_at__isnull=True).exists()


def builds(request) -> bool:
    membership = getattr(request, "membership", None)
    return membership is not None and membership.role == Role.FF \
        and available(membership.tenant_id)


def run_for(request, pk):
    """The run and the person's reach, or 404. A client sees only a shared,
    live run of their own company, and only as the client owner or senior
    leadership."""
    if not _is_uuid(pk):
        raise Http404
    run = ToolRun.objects.filter(pk=pk, archived_at__isnull=True).select_related(
        "company").first()
    if run is None:
        raise Http404
    access = access_for(request, "practice" if run.company.is_practice else run.company_id)
    if access.is_client and not (run.shared_with_client and access.sees_all):
        raise Http404
    return run, access


# ------------------------------------------------------------------ tools

def tool_of(tenant_id, ref) -> dict:
    """A shipped tool by its key, or a practice's own by its id: {key, id,
    name, description, definition, shipped}."""
    found = shipped.get(str(ref))
    if found is not None:
        return {"key": str(ref), "id": None, "name": found["name"],
                "description": found["description"], "definition": found["definition"],
                "shipped": True}
    tool = Tool.all_objects.filter(pk=ref, tenant_id=tenant_id, archived_at__isnull=True) \
        .first() if _is_uuid(ref) else None
    if tool is None:
        raise Http404
    return {"key": "", "id": str(tool.pk), "name": tool.name, "description": tool.description,
            "definition": tool.definition, "shipped": False, "source_key": tool.source_key,
            "from_ai": tool.from_ai}


def _clean_name(raw, what="A tool") -> str:
    name = " ".join(str(raw or "").split())[:120]
    if not name:
        raise ToolRefused(f"{what} needs a name.")
    return name


@transaction.atomic
def save_tool(tenant, data, *, actor, tool=None, from_ai=False) -> Tool:
    definition = data.get("definition") if "definition" in data else (
        tool.definition if tool else None)
    errors = D.check(definition)
    if errors:
        raise ToolRefused(errors[0]["message"], errors=errors)
    name = _clean_name(data.get("name", tool.name if tool else ""))
    description = str(data.get("description", tool.description if tool else "") or "")[:2000]
    if tool is None:
        tool = Tool.all_objects.create(tenant=tenant, name=name, description=description,
                                       definition=definition, created_by=actor,
                                       source_key=str(data.get("source_key") or "")[:40],
                                       from_ai=bool(from_ai or data.get("from_ai")))
        _audit(tenant.pk, actor, "tools.tool_made", "practice_tool", tool.pk, name=name)
    else:
        tool.name, tool.description, tool.definition = name, description, definition
        tool.save(update_fields=["name", "description", "definition", "updated_at"])
        _audit(tenant.pk, actor, "tools.tool_changed", "practice_tool", tool.pk, name=name)
    return tool


def duplicate_tool(tenant, ref, *, actor) -> Tool:
    found = tool_of(tenant.pk, ref)
    return save_tool(tenant, {"name": f"{found['name']} (our copy)",
                              "description": found["description"],
                              "definition": copy.deepcopy(found["definition"]),
                              "source_key": found["key"] or found.get("source_key", "")},
                     actor=actor)


def archive_tool(tool, *, actor):
    tool.archived_at = timezone.now()
    tool.save(update_fields=["archived_at", "updated_at"])
    _audit(tool.tenant_id, actor, "tools.tool_archived", "practice_tool", tool.pk, name=tool.name)


def catalog(tenant_id) -> list[dict]:
    out = [{"ref": key, "name": t["name"], "description": t["description"], "shipped": True}
           for key, t in shipped.SHIPPED.items()]
    out += [{"ref": str(t.pk), "name": t.name, "description": t.description, "shipped": False,
             "source_key": t.source_key}
            for t in Tool.all_objects.filter(tenant_id=tenant_id, archived_at__isnull=True)]
    return out


# ------------------------------------------------------------------ runs

@transaction.atomic
def start_run(company, ref, *, actor, name="", run_date=None, values=None) -> ToolRun:
    found = tool_of(company.tenant_id, ref)
    definition = copy.deepcopy(found["definition"])
    run = ToolRun.all_objects.create(
        tenant_id=company.tenant_id, company=company,
        tool_id=found["id"], tool_key=found["key"], tool_name=found["name"],
        name=_clean_name(name or f"{found['name']}, {company.name}", "A run"),
        run_date=run_date or timezone.localdate(), definition=definition,
        values=D.clean_values(definition, values or {}), created_by=actor)
    _audit(company.tenant_id, actor, "tools.run_started", "tool_run", run.pk,
           name=run.name, company=str(company.pk))
    return run


@transaction.atomic
def update_run(run, data, *, actor) -> ToolRun:
    fields = []
    if "name" in data:
        run.name = _clean_name(data["name"], "A run")
        fields.append("name")
    if "run_date" in data:
        try:
            run.run_date = date.fromisoformat(str(data["run_date"]))
        except ValueError:
            raise ToolRefused("That isn't a date.") from None
        fields.append("run_date")
    if "values" in data:
        run.values = D.clean_values(run.definition, data["values"])
        fields.append("values")
    if "shared_with_client" in data:
        run.shared_with_client = bool(data["shared_with_client"])
        fields.append("shared_with_client")
    if fields:
        run.save(update_fields=[*fields, "updated_at"])
    return run


def duplicate_run(run, *, actor) -> ToolRun:
    copy_ = ToolRun.all_objects.create(
        tenant_id=run.tenant_id, company=run.company, tool_id=run.tool_id,
        tool_key=run.tool_key, tool_name=run.tool_name, name=f"{run.name} (copy)"[:200],
        run_date=timezone.localdate(), definition=copy.deepcopy(run.definition),
        values=copy.deepcopy(run.values), created_by=actor)
    _audit(run.tenant_id, actor, "tools.run_duplicated", "tool_run", copy_.pk, name=copy_.name)
    return copy_


def archive_run(run, *, actor):
    run.archived_at = timezone.now()
    run.save(update_fields=["archived_at", "updated_at"])
    _audit(run.tenant_id, actor, "tools.run_archived", "tool_run", run.pk, name=run.name)


def summary_text(run, evaluation=None) -> str:
    """The run as plain text: its fields, its tables and its results."""
    evaluation = evaluation or D.evaluate(run.definition, run.values)
    lines = [f"{run.tool_name}: {run.name} ({run.run_date:%B %-d, %Y})"]
    for section in run.definition.get("sections") or []:
        lines.append(f"\n{section['title']}")
        for field in section.get("fields") or []:
            key, kind = field["key"], field.get("type")
            if kind == "table":
                columns = field["columns"]
                lines.append(f"{field['label']}:")
                for i, row in enumerate(run.values.get(key) or []):
                    computed = evaluation["tables"].get(key, [{}] * (i + 1))[i] \
                        if i < len(evaluation["tables"].get(key, [])) else {}
                    cells = []
                    for c in columns:
                        if c.get("type") == "computed":
                            text = (computed.get(c["key"]) or {}).get("text", "")
                        else:
                            value = row.get(c["key"])
                            text = ", ".join(value) if isinstance(value, list) else str(value or "")
                        if text and text != "–":
                            cells.append(f"{c['label']}: {text}")
                    lines.append("- " + "; ".join(cells))
            elif kind == "computed":
                lines.append(f"{field['label']}: {evaluation['computed'][key]['text']}")
            else:
                value = run.values.get(key)
                text = ", ".join(value) if isinstance(value, list) else str(value or "")
                if text:
                    lines.append(f"{field['label']}: {text}")
    if evaluation["results"]:
        lines.append("\nResults")
        lines += [f"{r['label']}: {r['text']}" for r in evaluation["results"]]
    return "\n".join(lines)


# ------------------------------------------------------------------ hand-offs

def _row_label(table, row, index) -> str:
    for column in table["columns"]:
        if column.get("type") in ("text", "long_text") and str(row.get(column["key"]) or "").strip():
            return str(row[column["key"]]).strip().split("\n")[0]
    return f"Row {index + 1}"


@transaction.atomic
def tasks_from_flags(run, *, actor, role) -> list:
    """A task for each flagged row: the row's first words as its title, the run
    as where it came from. Ordinary tasks of the company."""
    from apps.crm.models import Task
    from apps.work import services as work
    from apps.work.models import TaskUpdate

    made = []
    company_id = None if run.company.is_practice else run.company_id
    for key, table in D.tables(run.definition).items():
        for i, row in enumerate(run.values.get(key) or []):
            if not row.get("_flag"):
                continue
            title = f"{_row_label(table, row, i)} ({table['label']})"[:255]
            made.append(work.create_task(
                tenant=run.tenant, actor=actor, role=role, title=title,
                description=f"From {run.tool_name}: {run.name}.",
                status=Task.Status.NOT_STARTED, client_company_id=company_id, owner=actor,
                source=TaskUpdate.Source.TOOL, source_id=run.pk))
    if not made:
        raise ToolRefused("No row is flagged. Tick the rows to make tasks of first.", 409)
    _audit(run.tenant_id, actor, "tools.tasks_made", "tool_run", run.pk, count=len(made))
    return made


def result_value(run, key):
    evaluation = D.evaluate(run.definition, run.values)
    found = next((r for r in evaluation["results"] if r["key"] == key), None)
    if found is None:
        found = evaluation["computed"].get(key)
        if found is not None:
            found = {**found, "label": key, "numeric": isinstance(found.get("value"),
                                                                  (int, float))}
    if found is None:
        raise ToolRefused("That result isn't one of this run's.")
    if found.get("error") or not found.get("numeric"):
        raise ToolRefused("Only a number can be a reading.")
    return found


def send_to_kpi(run, request, *, result_key, kpi_id, period_start, today) -> dict:
    """The result as one KPI reading "From a tool", by the scorecard's own
    entry rules: a KPI the person may enter, a real period, not the future."""
    from apps.scorecard import board, readings
    from apps.scorecard.access import Reader
    from apps.scorecard.models import KpiReading

    found = result_value(run, result_key)
    scorecard = board.scorecard_for(run.company)
    if scorecard is None:
        raise ToolRefused("This company has no scorecard yet.", 409)
    reader = Reader(request, run.company)
    value = f"{found['value']:.4f}".rstrip("0").rstrip(".")
    result = readings.save(reader, scorecard, [{"kpi": kpi_id, "period_start": period_start,
                                                 "value": value}], today,
                           source=KpiReading.Source.TOOL)
    if result["errors"]:
        raise ToolRefused("; ".join(result["errors"].values()))
    _audit(run.tenant_id, request.user, "tools.reading_sent", "tool_run", run.pk,
           kpi=str(kpi_id), value=value)
    return {"saved": result["saved"], "changed": result["changed"], "value": value}


def propose_to_plan(run, *, actor, horizon, title, done_means="", today):
    from apps.plans import periods as P
    from apps.plans.models import Horizon, PlanItem

    if horizon not in Horizon.values:
        raise ToolRefused("Choose a horizon.")
    title = " ".join(str(title or "").split())[:300]
    if not title:
        raise ToolRefused("A plan item needs a title.")
    item = PlanItem.all_objects.create(
        tenant_id=run.tenant_id, company=run.company, horizon=horizon,
        period_start=P.start_of(horizon, today, run.company), title=title,
        done_means=str(done_means or "")[:2000], state=PlanItem.State.PROPOSED,
        source=PlanItem.Source.TOOL, source_id=run.pk,
        drew_on=[f"{run.tool_name}: {run.name}"], created_by=actor)
    _audit(run.tenant_id, actor, "tools.plan_proposed", "tool_run", run.pk, title=title)
    return item


def sop_brainstorm(run, *, actor):
    """A note to brainstorm the SOP in, with the run as its source: there is
    no SOP studio yet, so it is a note on the company."""
    from apps.notes.models import Note

    note = Note.all_objects.create(
        tenant_id=run.tenant_id, company=None if run.company.is_practice else run.company,
        title=f"SOP brainstorm: {run.name}"[:255], created_by=actor,
        body="Purpose:\n\nRoles:\n\nSteps:\n\nMeasures:\n\nReview date:\n\n"
             "— Source —\n" + summary_text(run))
    _audit(run.tenant_id, actor, "tools.sop_brainstorm", "tool_run", run.pk, note=str(note.pk))
    return note


# ------------------------------------------------------------------ import from an SOP

_STEP = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+(.*\S)\s*$")


def sop_sources(company) -> list[dict]:
    from apps.plans.sources import _sop_documents, _sop_notes

    if company.is_practice:
        return []
    return [{"id": f"doc:{d.pk}", "label": f"SOP: {d.title}"} for d in _sop_documents(company)] \
        + [{"id": f"note:{n.pk}", "label": n.title or "SOP draft"} for n in _sop_notes(company)]


def _sop_text(company, source) -> str:
    from apps.esign.models import Document
    from apps.notes.models import Note

    source = str(source or "")
    if source.startswith("doc:") and _is_uuid(source[4:]):
        doc = Document.all_objects.filter(pk=source[4:], company=company,
                                          template__original__endswith="_sop").first()
        if doc is not None:
            fields = doc.fields or {}
            steps = [v for k, v in fields.items() if "step" in k.lower() and isinstance(v, str)]
            return "\n".join(steps) or "\n".join(v for v in fields.values() if isinstance(v, str))
    if source.startswith("note:") and _is_uuid(source[5:]):
        note = Note.all_objects.filter(pk=source[5:], company=company, pin_hash__isnull=True,
                                       deleted_at__isnull=True).first()
        if note is not None:
            return note.body
    raise ToolRefused("That SOP isn't one of this company's.", 404)


def steps_of(text) -> list[str]:
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    listed = [m.group(1) for m in (_STEP.match(ln) for ln in lines) if m]
    return [s[:200] for s in (listed or [ln.strip() for ln in lines])][:40]


@transaction.atomic
def import_steps(run, source, *, actor) -> int:
    if "import_sop" not in (run.definition.get("actions") or []):
        raise ToolRefused("This tool doesn't take steps from an SOP.", 409)
    table_key, table = next(iter(D.tables(run.definition).items()))
    first = next(c["key"] for c in table["columns"] if c.get("type") == "text")
    steps = steps_of(_sop_text(run.company, source))
    if not steps:
        raise ToolRefused("That SOP has no steps to read.", 409)
    values = dict(run.values)
    values[table_key] = list(values.get(table_key) or []) + [{first: s} for s in steps]
    run.values = D.clean_values(run.definition, values)
    run.save(update_fields=["values", "updated_at"])
    return len(steps)


# ------------------------------------------------------------------ the cadence's calendar

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
ICS_DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


def _first_on(start: date, weekday: int, cadence: str) -> date:
    if cadence in ("Weekly", "Every two weeks"):
        return start + timedelta(days=(weekday - start.weekday()) % 7)
    # Monthly and quarterly: the first of that weekday in a month, on or after start.
    month = start.replace(day=1)
    for _ in range(14):
        first = month + timedelta(days=(weekday - month.weekday()) % 7)
        if first >= start:
            return first
        month = (month + timedelta(days=32)).replace(day=1)
    return start


def events_of(run) -> list[dict]:
    """The recurring events the cadence makes: one per meeting with a day, a
    time, a length and a first date."""
    if "calendar" not in (run.definition.get("actions") or []):
        raise ToolRefused("This tool doesn't make calendar events.", 409)
    agenda = [r for r in run.values.get("agenda") or []]
    out = []
    for row in run.values.get("meetings") or []:
        name, cadence, day = (row.get("name") or "").strip(), row.get("cadence"), row.get("day")
        try:
            hour, minute = (int(x) for x in str(row.get("time") or "").split(":"))
            first = date.fromisoformat(str(row.get("start")))
            minutes = int(float(row.get("minutes") or 0))
        except (ValueError, TypeError):
            continue
        if not name or day not in DAYS or cadence not in ("Weekly", "Every two weeks", "Monthly",
                                                          "Quarterly") or minutes <= 0 \
                or not (0 <= hour < 24 and 0 <= minute < 60):
            continue
        weekday = DAYS.index(day)
        on = _first_on(first, weekday, cadence)
        rule = {"Weekly": f"FREQ=WEEKLY;BYDAY={ICS_DAYS[weekday]}",
                "Every two weeks": f"FREQ=WEEKLY;INTERVAL=2;BYDAY={ICS_DAYS[weekday]}",
                "Monthly": f"FREQ=MONTHLY;BYDAY=1{ICS_DAYS[weekday]}",
                "Quarterly": f"FREQ=MONTHLY;INTERVAL=3;BYDAY=1{ICS_DAYS[weekday]}"}[cadence]
        sections = [a for a in agenda if (a.get("meeting") or "").strip().lower() == name.lower()]
        clock = datetime.combine(on, datetime.min.time()).replace(hour=hour, minute=minute)
        lines = []
        for a in sections:
            lines.append(f"{clock:%-I:%M} {a.get('section') or ''} ({a.get('minutes') or 0} min)")
            clock += timedelta(minutes=int(float(a.get("minutes") or 0)))
        attendees = row.get("attendees") or []
        note = (("Who attends: " + ", ".join(attendees) + "\n") if attendees else "") + \
            ("Agenda:\n" + "\n".join(lines) if lines else "")
        out.append({"name": name, "cadence": cadence, "day": day, "first": on.isoformat(),
                    "time": f"{hour:02d}:{minute:02d}", "minutes": minutes, "rrule": rule,
                    "attendees": attendees, "agenda": lines, "note": note,
                    "starts": datetime.combine(on, datetime.min.time()).replace(
                        hour=hour, minute=minute)})
    return out


def _ics_text(text) -> str:
    return (text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,") \
        .replace("\n", "\\n")


def ics(run, tz_name) -> str:
    stamp = timezone.now().strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Execs NOW HQ//Meeting cadence//EN",
             "CALSCALE:GREGORIAN"]
    for i, e in enumerate(events_of(run)):
        lines += ["BEGIN:VEVENT", f"UID:{run.pk}-{i}@execsnowhq",
                  f"DTSTAMP:{stamp}",
                  f"DTSTART;TZID={tz_name}:{e['starts']:%Y%m%dT%H%M%S}",
                  f"DURATION:PT{e['minutes']}M", f"RRULE:{e['rrule']}",
                  f"SUMMARY:{_ics_text(e['name'])}", f"DESCRIPTION:{_ics_text(e['note'])}",
                  "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def create_events(run, user, tz_name) -> list[dict]:
    """The recurring events on the person's own connected calendar. Nobody is
    invited by the app: the attendees are named in each event's notes."""
    from config import environment

    from apps.calendars import providers
    from apps.calendars.models import CalendarConnection

    events = events_of(run)
    if environment.is_demo():
        raise ToolRefused("This is the demo. It never writes to a calendar; these are the "
                          "events it would make.", 409)
    connection = CalendarConnection.objects.filter(user=user).first()
    if connection is None:
        raise ToolRefused("No calendar is connected. Download the calendar file instead.", 409)
    made = []
    for e in events:
        made.append(providers.create_event(connection, title=e["name"], starts_at=e["starts"],
                                           minutes=e["minutes"], tz_name=tz_name,
                                           note=e["note"], rrule=e["rrule"]))
    _audit(run.tenant_id, user, "tools.events_made", "tool_run", run.pk, count=len(made))
    return made
