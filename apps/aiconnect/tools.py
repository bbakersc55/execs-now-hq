"""What an AI app can do over MCP (P7, docs/p7_mcp.md, "Tools").

Every tool runs as the connection's person, in their practice, with their
role, through **the same scoping the web app uses**: the querysets, viewset
methods and serializers its screens call, given a request stand-in
(`Principal.request`). A tool never sees more than that person would on the
screen.

Reads return what the screen shows. Writes land where a person approves (the
Sending queue, a session's tray, digests for approval), or as an internal
record marked as made by an AI app (a task, a note, a KPI reading "entered by
AI"). There is no tool to send mail, move or charge money, sign, delete,
change a pipeline stage, or change settings or connections.

Each function is synchronous and plain Django; `mcp_server.py` runs them off
the event loop and writes the Activity line (`record_call`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from types import SimpleNamespace

from django.db.models import Q
from django.http import Http404
from django.utils import timezone


class ToolRefused(Exception):
    """A plain-words refusal, returned to the AI app as a tool error."""


AI_APP_SOURCE = "ai_app"


@dataclass
class Principal:
    connection: object
    #: Record ids a call touched, for its Activity line (never content).
    touched: list = field(default_factory=list)

    @property
    def membership(self):
        return self.connection.membership

    @property
    def tenant(self):
        return self.connection.membership.tenant

    @property
    def user(self):
        return self.connection.user

    @property
    def role(self):
        return self.connection.membership.role

    def request(self, **query):
        """What the web app's scopers read from a request, for this person."""
        if not hasattr(self, "_request"):
            self._request = SimpleNamespace(
                user=self.user, membership=self.membership, tenant=self.tenant,
                real_user=self.user, real_membership=self.membership, acting_as=None,
                area="practice", session=SimpleNamespace(session_key=None, get=lambda *a: None),
                META={}, GET={}, data={}, query_params={}, method="GET")
        self._request.query_params = dict(query)
        self._request.GET = dict(query)
        return self._request

    def touch(self, kind: str, *ids):
        for i in ids:
            if i:
                self.touched.append((kind, str(i)))


def _plain(value):
    """JSON-safe: DRF ReturnDicts, dates, UUIDs and Decimals as strings."""
    return json.loads(json.dumps(value, default=str))


def _uuid(value, what: str) -> str:
    from apps.work.views import _is_uuid

    value = str(value or "").strip()
    if not _is_uuid(value):
        raise ToolRefused(f"{what} must be an id from another tool's answer.")
    return value


def _companies(p):
    from apps.crm import permissions as crm_perms
    from apps.crm.models import Company

    return crm_perms.company_queryset_for(
        p.request(), Company.objects.filter(deleted_at__isnull=True, is_practice=False))


def _contacts(p):
    from apps.crm import permissions as crm_perms
    from apps.crm.models import Contact

    return crm_perms.contact_queryset_for(
        p.request(), Contact.objects.filter(deleted_at__isnull=True, merged_into__isnull=True))


def _company(p, company_id):
    company = _companies(p).filter(pk=_uuid(company_id, "company_id")).first()
    if company is None:
        raise ToolRefused("No company with that id that you can see.")
    p.touch("company", company.pk)
    return company


def _contact(p, contact_id):
    contact = _contacts(p).filter(pk=_uuid(contact_id, "contact_id")).select_related(
        "company").first()
    if contact is None:
        raise ToolRefused("No contact with that id that you can see.")
    p.touch("contact", contact.pk)
    return contact


def _name(contact) -> str:
    return f"{contact.first_name} {contact.last_name}".strip()


def _contact_line(c) -> dict:
    primary = next((e.address for e in c.emails.all() if e.is_primary), None) or next(
        (e.address for e in c.emails.all()), "")
    return {"id": str(c.pk), "name": _name(c), "email": primary,
            "company": c.company.name if c.company_id else "",
            "company_id": str(c.company_id) if c.company_id else None,
            "title": getattr(c, "title", "") or ""}


# ===================================================================== READ

def practice_summary(p) -> dict:
    """Home's tiles, as the person's Home shows them."""
    from apps.work import dashboard

    if p.role not in ("FF", "CF", "VA"):
        raise ToolRefused("Only the practice's own team has a Home.")
    return _plain(dashboard.for_request(p.request()))


def list_companies(p, query: str = "", clients_only: bool = False, limit: int = 50) -> dict:
    qs = _companies(p)
    if query:
        qs = qs.filter(name__icontains=query.strip())
    if clients_only:
        qs = qs.filter(is_client_company=True)
    rows = list(qs.order_by("name")[:max(1, min(int(limit or 50), 200))])
    p.touch("company", *[c.pk for c in rows][:20])
    return {"companies": [{"id": str(c.pk), "name": c.name, "is_client": c.is_client_company}
                          for c in rows]}


def company_overview(p, company_id: str) -> dict:
    """A company's whole picture: people, goals, open tasks, invoices summary,
    documents and their states, scorecard summary. No mail: nothing read from
    Gmail or Microsoft 365 reaches an AI app (Google's Limited Use terms)."""
    company = _company(p, company_id)
    people = [_contact_line(c) for c in _contacts(p).filter(company=company)
              .prefetch_related("emails").order_by("last_name", "first_name")[:100]]
    out = {"company": {"id": str(company.pk), "name": company.name,
                       "is_client": company.is_client_company},
           "people": people}
    out["goals"] = list_goals(p, company_id=str(company.pk))["goals"]
    out["open_tasks"] = list_tasks(p, company_id=str(company.pk), status="open",
                                   limit=50)["tasks"]
    try:
        out["invoices"] = invoices_summary(p, company_id=str(company.pk))
    except ToolRefused as exc:
        out["invoices"] = {"not_shown": str(exc)}
    out["documents"] = documents(p, company_id=str(company.pk))["documents"]
    try:
        board = scorecard_readings(p, company_id=str(company.pk), window="this_week")
        out["scorecard"] = {"window": board.get("window"),
                            "kpis": [{"name": k.get("name"), "target": k.get("target_text"),
                                      "latest": k.get("latest")} for k in board.get("kpis", [])]}
    except ToolRefused as exc:
        out["scorecard"] = {"not_shown": str(exc)}
    return out


def search_contacts(p, query: str, limit: int = 25) -> dict:
    term = (query or "").strip()
    if len(term) < 2:
        raise ToolRefused("Search for at least two characters.")
    from django.db.models import Q

    qs = _contacts(p).filter(
        Q(first_name__icontains=term) | Q(last_name__icontains=term)
        | Q(emails__address__icontains=term) | Q(company__name__icontains=term)
    ).distinct().select_related("company").prefetch_related("emails")
    rows = list(qs.order_by("last_name", "first_name")[:max(1, min(int(limit or 25), 100))])
    p.touch("contact", *[c.pk for c in rows][:20])
    return {"contacts": [_contact_line(c) for c in rows]}


def get_contact(p, contact_id: str) -> dict:
    from apps.crm import permissions as crm_perms
    from apps.crm.serializers import ContactSerializer
    from apps.crm.services import timeline

    contact = _contact(p, contact_id)
    request = p.request()
    data = _plain(ContactSerializer(contact, context={"request": request}).data)
    money = crm_perms.sees_money(request, contact.company_id)
    # Mail stays out (Google's Limited Use terms): a reply's subject is read
    # from Gmail or Microsoft 365, and a sent one's is often "Re:" of it.
    data["timeline"] = _plain([e for e in timeline.for_contact(contact, money=money)
                               if e.get("kind") != "email"][:30])
    return data


def list_pipelines(p) -> dict:
    from apps.crm.models import Pipeline

    if p.role not in ("FF", "CF", "VA"):
        raise ToolRefused("Pipelines are the practice's own.")
    out = []
    for pipe in Pipeline.objects.prefetch_related("stages").order_by("position"):
        out.append({"id": str(pipe.pk), "name": pipe.name, "kind": pipe.get_kind_display(),
                    "stages": [{"id": str(s.pk), "label": s.label, "meaning": s.semantic,
                                "contacts": _contacts(p).filter(
                                    pipeline_positions__stage=s).count()}
                               for s in pipe.stages.order_by("position")]})
    return {"pipelines": out}


def list_tasks(p, status: str = "", company_id: str = "", assignee: str = "",
               due_before: str = "", overdue: bool = False, limit: int = 100) -> dict:
    """Tasks the person can see. status: open, done, or a status code;
    assignee: "me" for their own; due_before: YYYY-MM-DD."""
    from apps.work import permissions as work_perms
    from apps.work import serializers as work_serializers
    from apps.work.models import Task

    request = p.request()
    qs = work_perms.task_queryset_for(request, Task.objects.all())
    if company_id:
        qs = qs.filter(client_company_id=_company(p, company_id).pk)
    if assignee == "me":
        qs = qs.filter(owner=p.user)
    if status == "open":
        qs = qs.exclude(status__in=["done", "cancelled"])
    elif status == "done":
        qs = qs.filter(status="done")
    elif status:
        qs = qs.filter(status=status)
    today = timezone.localdate()
    if overdue:
        qs = qs.filter(due_date__lt=today).exclude(status__in=["done", "cancelled"])
    if due_before:
        try:
            qs = qs.filter(due_date__lte=date.fromisoformat(due_before))
        except ValueError as exc:
            raise ToolRefused("due_before is a date, YYYY-MM-DD.") from exc
    rows = list(qs.order_by("due_date", "created_at")[:max(1, min(int(limit or 100), 300))])
    p.touch("task", *[t.pk for t in rows][:20])
    return {"tasks": [_plain(work_serializers.represent_task(t, request=request))
                      for t in rows]}


def list_goals(p, company_id: str = "") -> dict:
    """Goals with their projects, as the person sees them."""
    from apps.work import permissions as work_perms
    from apps.work import serializers as work_serializers
    from apps.work.models import Goal, Project

    request = p.request()
    goals = work_perms.goal_queryset_for(request, Goal.objects.all())
    projects = work_perms.project_queryset_for(request, Project.objects.all())
    if company_id:
        company = _company(p, company_id)
        goals = goals.filter(client_company=company)
        projects = projects.filter(client_company=company)
    out = []
    for g in goals.order_by("created_at")[:100]:
        row = _plain(work_serializers.represent_parent(g, request=request, kind="goal"))
        row["projects"] = [_plain(work_serializers.represent_parent(x, request=request,
                                                                    kind="project"))
                           for x in projects.filter(goal=g).order_by("created_at")[:50]]
        out.append(row)
    return {"goals": out}


def list_notes(p, contact_id: str = "", company_id: str = "", query: str = "",
               limit: int = 25) -> dict:
    """Notes the person can open. PIN-locked notes are left out entirely."""
    from apps.notes import access
    from apps.notes.models import Note
    from apps.notes.serializers import represent_many

    request = p.request()
    qs = access.note_queryset_for(request, Note.objects.all()).filter(pin_hash__isnull=True)
    if contact_id:
        qs = qs.filter(contact_id=_contact(p, contact_id).pk)
    if company_id:
        qs = qs.filter(company_id=_company(p, company_id).pk)
    if query:
        qs = qs.filter(body__icontains=query.strip()) | qs.filter(title__icontains=query.strip())
    rows = list(qs.order_by("-created_at")[:max(1, min(int(limit or 25), 100))])
    p.touch("note", *[n.pk for n in rows][:20])
    return {"notes": _plain(represent_many(rows, request=request))}


def scorecard_readings(p, company_id: str, window: str = "this_week", from_date: str = "",
                       to_date: str = "") -> dict:
    """A company's scorecard for a window: this_week, last_week, this_month,
    last_month, last_13_weeks… or custom with from_date and to_date."""
    from apps.scorecard import board
    from apps.scorecard import periods as P
    from apps.scorecard.access import Reader, company_for

    request = p.request()
    try:
        company = company_for(request, _uuid(company_id, "company_id"))
    except Http404 as exc:
        raise ToolRefused("No company with that id whose scorecard you can see.") from exc
    p.touch("company", company.pk)
    reader = Reader(request, company)
    scorecard = board.scorecard_for(company)
    if scorecard is None:
        return {"company": company.name, "exists": False}
    today = board.today_for(p.tenant)
    try:
        win = P.window(window or "this_week", today, scorecard.week_start,
                       first=date.fromisoformat(from_date) if from_date else None,
                       last=date.fromisoformat(to_date) if to_date else None)
    except (ValueError, P.WindowInvalid) as exc:
        raise ToolRefused(str(exc) if isinstance(exc, P.WindowInvalid)
                          else "Dates are YYYY-MM-DD.") from exc
    out = _plain(board.build(reader, scorecard, None, win, today))
    out["exists"] = True
    return out


def pending_meeting_proposals(p) -> dict:
    from apps.meetings import permissions as meeting_perms
    from apps.meetings import serializers as meeting_serializers
    from apps.meetings.models import MeetingProposal

    request = p.request()
    # The open queue, as the Meetings screen's default ("state=open").
    qs = meeting_perms.proposals_for(request).filter(
        state__in=[MeetingProposal.State.PENDING, MeetingProposal.State.PARTIALLY_ACTIONED])
    rows = list(qs.order_by("-created_at")[:50])
    p.touch("meeting_proposal", *[m.pk for m in rows][:20])
    return {"proposals": [_plain(meeting_serializers.represent_proposal(m, request=request))
                          for m in rows]}


def sending_queue(p) -> dict:
    """What waits in the Sending queue for approval: messages and digests.
    Mail stays out (Google's Limited Use terms): a reply in a mail thread and
    an inbound forward carry what was read from Gmail or Microsoft 365, so
    they are counted, not shown."""
    from apps.crm.models import OutboxMessage
    from apps.crm.views_queue import SendingQueueView

    if p.role not in ("FF", "CF", "VA"):
        raise ToolRefused("The Sending queue is the practice's own.")
    view = SendingQueueView()
    request = p.request()
    queued = view._messages(request)
    from_mail = Q(thread__isnull=False) | Q(producer=OutboxMessage.Producer.INBOUND_FORWARD)
    messages = list(queued.exclude(from_mail).order_by("-created_at")[:100])
    p.touch("outbox", *[m.pk for m in messages][:20])
    return {"messages": _plain([view._message_row(m) for m in messages]),
            "replies_to_mail_not_shown": queued.filter(from_mail).count(),
            "digests_waiting": view._digests(request).count()}


def digest_drafts(p) -> dict:
    from apps.work import serializers as work_serializers
    from apps.work.models import Digest
    from apps.work.views import DigestViewSet

    view = DigestViewSet()
    view.request = p.request()
    rows = list(view.get_queryset().filter(state=Digest.State.PENDING)
                .order_by("send_window_at")[:50])
    p.touch("digest", *[d.pk for d in rows][:20])
    return {"digests": [_plain(work_serializers.represent_digest(d, full=True)) for d in rows]}


def invoices_summary(p, company_id: str = "", status: str = "") -> dict:
    from apps.billing import services as billing
    from apps.billing.views import InvoiceViewSet, represent_row

    if p.role not in ("FF", "CF"):
        raise ToolRefused("Invoices are shown to the practice owner and associates only.")
    view = InvoiceViewSet()
    view.request = p.request()
    qs = view.invoices()
    if company_id:
        qs = qs.filter(client_company_id=_company(p, company_id).pk)
    if status:
        qs = qs.filter(status=status)
    rows = list(qs.order_by("-issue_date" if hasattr(qs.model, "issue_date") else "-created_at")
                [:100])
    p.touch("invoice", *[i.pk for i in rows][:20])
    return {"totals": _plain(billing.totals(qs)),
            "invoices": _plain([represent_row(i) for i in rows])}


def documents(p, company_id: str = "") -> dict:
    """Documents for signature and where each stands (draft, sent, viewed,
    signed, declined, countersigned, complete, void, expired)."""
    from apps.crm import permissions as crm_perms
    from apps.esign.views import SENDERS, DocumentViewSet, represent

    view = DocumentViewSet()
    view.request = p.request()
    qs = view._documents()
    if company_id:
        qs = qs.filter(company_id=_company(p, company_id).pk)
    rows = list(qs.order_by("-created_at")[:100])
    p.touch("document", *[d.pk for d in rows][:20])
    full = crm_perms.role_of(view.request) in SENDERS
    return {"documents": _plain([represent(d, full=full) for d in rows])}


def list_strategy_sessions(p, limit: int = 50) -> dict:
    from apps.strategy.views import StrategyViewSet

    view = StrategyViewSet()
    view.request = p.request()
    rows = list(view.sessions().filter(archived_at__isnull=True)
                .order_by("-created_at")[:max(1, min(int(limit or 50), 200))])
    p.touch("strategy_session", *[s.pk for s in rows][:20])
    return {"sessions": [{"id": str(s.pk), "state": s.state,
                          "contact": _name(s.contact) if s.contact_id else "",
                          "company": s.company.name if s.company_id else "",
                          "created_at": s.created_at.isoformat()} for s in rows]}


def _session(p, session_id):
    from apps.strategy.views import StrategyViewSet

    view = StrategyViewSet()
    view.request = p.request()
    session = view.sessions().filter(pk=_uuid(session_id, "session_id")).first()
    if session is None:
        raise ToolRefused("No strategy session with that id that you can see.")
    p.touch("strategy_session", session.pk)
    return session, view.request


def strategy_session(p, session_id: str) -> dict:
    """A session's sections, answers and Strategy Map rows."""
    from apps.strategy import serializers as strategy_serializers
    from apps.strategy.views import _may_see_financial, _private

    session, request = _session(p, session_id)
    return _plain(strategy_serializers.represent_session(
        session, include_financial=_may_see_financial(request), full=True,
        private=_private(request), include_prep=_may_see_financial(request)))


# ==================================================================== WRITE

def create_task(p, title: str, due_date: str = "", company_id: str = "",
                contact_id: str = "", description: str = "") -> dict:
    """An internal task (hidden from the client until a person shows it),
    owned by the person, marked as made by an AI app."""
    from apps.crm import permissions as crm_perms
    from apps.work import serializers as work_serializers
    from apps.work import services
    from apps.work.models import TaskUpdate

    if p.role not in ("FF", "CF", "VA"):
        raise ToolRefused("Only the practice's team can create tasks from an AI app.")
    request = p.request()
    data = {"title": (title or "").strip()[:255], "owner": str(p.user.pk)}
    if not data["title"]:
        raise ToolRefused("A task needs a title.")
    if due_date:
        data["due_date"] = due_date
    if description:
        data["description"] = description
    if company_id:
        data["client_company"] = str(_company(p, company_id).pk)
    if contact_id:
        data["contact"] = str(_contact(p, contact_id).pk)
    serializer = work_serializers.TaskSerializer(data=data, context={"request": request})
    if not serializer.is_valid():
        raise ToolRefused(_first_error(serializer.errors))
    fields = dict(serializer.validated_data)
    fields.pop("client_facing_line", None)
    fields["is_client_visible"] = False
    task = services.create_task(tenant=p.tenant, actor=p.user, role=crm_perms.role_of(request),
                                source=TaskUpdate.Source.AI_APP, source_id=p.connection.pk,
                                **fields)
    p.touch("task", task.pk)
    return {"created": "task", "id": str(task.pk), "title": task.title,
            "note": "Internal: the client sees it only if a person shows it."}


def add_note(p, body: str, title: str = "", contact_id: str = "", company_id: str = "") -> dict:
    from apps.notes import access
    from apps.notes.models import Note

    if p.role not in ("FF", "CF", "VA"):
        raise ToolRefused("Only the practice's team can add notes from an AI app.")
    body = (body or "").strip()
    if not body:
        raise ToolRefused("A note needs a body.")
    # A note is on a contact or on a company, never both (the database says so).
    if contact_id and company_id:
        raise ToolRefused("A note goes on a contact or on a company, not both.")
    contact = _contact(p, contact_id) if contact_id else None
    company = _company(p, company_id) if company_id else None
    title = (title or "").strip()[:200]
    note = Note.objects.create(
        tenant=p.tenant, created_by=p.user, source=Note.Source.AI_APP,
        title=title or access.derive_title(body), title_is_auto=not title, body=body,
        contact=contact, company=company)
    p.touch("note", note.pk)
    return {"created": "note", "id": str(note.pk), "title": note.title}


def draft_email(p, contact_id: str, subject: str, body: str) -> dict:
    """A draft to one contact, from the person's default mailbox, waiting in
    the Sending queue for a person to approve. Never sent from here."""
    from apps.crm.models import OutboxMessage
    from apps.crm.services import outbox

    if p.role not in ("FF", "CF", "VA"):
        raise ToolRefused("Only the practice's team can draft email from an AI app.")
    contact = _contact(p, contact_id)
    if not (subject or "").strip() or not (body or "").strip():
        raise ToolRefused("An email needs a subject and a body.")
    message = outbox.create_manual_draft(contact, subject=subject.strip()[:255],
                                         body_text=body.strip(), actor=p.user)
    if message is None:
        raise ToolRefused("That contact can't be emailed (no address, or they opted out).")
    message.source_type, message.source_id = AI_APP_SOURCE, p.connection.pk
    message.save(update_fields=["source_type", "source_id", "updated_at"])
    if message.state != OutboxMessage.State.PENDING_APPROVAL:
        raise ToolRefused("The draft didn't land waiting for approval; nothing was sent.")
    p.touch("outbox", message.pk)
    return {"created": "email draft", "id": str(message.pk), "state": "waiting for approval",
            "to": message.to_address, "subject": message.subject}


def propose_map_rows(p, session_id: str, rows: list) -> dict:
    """Strategy Map rows into a session's tray, proposed: a person accepts,
    edits or discards each. Each row: bottleneck (required), root_cause,
    the_fix, owner, horizon (30, 60 or 90), measurable, header, statement."""
    from django.db.models import Max

    from apps.strategy.models import StrategyMapRow

    if p.role not in ("FF", "CF"):
        raise ToolRefused("Only the practice owner or an associate proposes map rows.")
    session, _ = _session(p, session_id)
    if not isinstance(rows, list) or not rows or len(rows) > 20:
        raise ToolRefused("rows is a list of one to twenty rows.")
    start = (StrategyMapRow.objects.filter(session=session)
             .aggregate(m=Max("position"))["m"] or 0) + 1
    made = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict) or not str(row.get("bottleneck") or "").strip():
            raise ToolRefused(f"Row {i + 1} needs a bottleneck.")
        horizon = row.get("horizon")
        if horizon not in (None, "", 30, 60, 90, "30", "60", "90"):
            raise ToolRefused(f"Row {i + 1}: horizon is 30, 60 or 90.")
        header = str(row.get("header") or "")[:120]
        statement = str(row.get("statement") or "")
        made.append(StrategyMapRow(
            tenant=p.tenant, session=session, position=start + i,
            state=StrategyMapRow.State.PROPOSED, from_ai_app=True,
            bottleneck=str(row["bottleneck"]).strip(),
            root_cause=str(row.get("root_cause") or ""), the_fix=str(row.get("the_fix") or ""),
            owner_text=str(row.get("owner") or "")[:200],
            horizon=int(horizon) if horizon not in (None, "") else None,
            measurable=str(row.get("measurable") or "")[:255],
            header=header, statement=statement,
            proposed_header=header, proposed_statement=statement))
    StrategyMapRow.objects.bulk_create(made)
    p.touch("map_row", *[r.pk for r in made])
    return {"proposed": len(made), "ids": [str(r.pk) for r in made],
            "note": "In the session's tray, waiting for a person to accept, edit or discard."}


def enter_kpi_reading(p, company_id: str, kpi_id: str, period_start: str, value: str,
                      membership_id: str = "") -> dict:
    """One KPI reading, marked "entered by AI", under the same rules as the
    entry form: a KPI the person may enter, a real period start, not future."""
    from apps.scorecard import board, readings
    from apps.scorecard.access import Reader, company_for
    from apps.scorecard.models import KpiReading

    request = p.request()
    try:
        company = company_for(request, _uuid(company_id, "company_id"))
    except Http404 as exc:
        raise ToolRefused("No company with that id whose scorecard you can see.") from exc
    reader = Reader(request, company)
    scorecard = board.scorecard_for(company)
    if scorecard is None:
        raise ToolRefused("That company has no scorecard.")
    row = {"kpi": _uuid(kpi_id, "kpi_id"), "period_start": period_start, "value": value}
    if membership_id:
        row["membership"] = _uuid(membership_id, "membership_id")
    result = readings.save(reader, scorecard, [row], board.today_for(p.tenant),
                           source=KpiReading.Source.AI)
    if result["errors"]:
        raise ToolRefused("; ".join(result["errors"].values()))
    p.touch("kpi", row["kpi"])
    p.touch("company", company.pk)
    return {"saved": result["saved"], "changed": result["changed"],
            "marked": "entered by AI"}


def create_digest_draft(p, contact_id: str, body: str) -> dict:
    """A digest to one client contact, in the words given, waiting for
    approval in Digests and the Sending queue. Never sent from here."""
    from django.utils.html import linebreaks

    from apps.work import digests
    from apps.work.models import Cadence, Digest

    if p.role not in ("FF", "CF"):
        raise ToolRefused("Only the practice owner or an associate drafts digests.")
    contact = _contact(p, contact_id)
    # As DigestViewSet: an associate's digests are their assigned companies'.
    if p.role == "CF" and contact.company_id not in set(_assigned(p)):
        raise ToolRefused("That contact's company isn't assigned to you.")
    text = (body or "").strip()
    if not text:
        raise ToolRefused("A digest needs words.")
    now = timezone.now()
    cadence = Cadence.WEEKLY
    try:
        window = digests.next_window(p.tenant, cadence, after=now)
    except Exception:
        window = now + timedelta(days=1)
    digest = Digest.objects.create(
        tenant=p.tenant, contact=contact, cadence=cadence, period_start=now,
        period_end=now, send_window_at=window, is_ai_generated=True, from_ai_app=True,
        state=Digest.State.PENDING, body_text=text, body_html=linebreaks(text))
    p.touch("digest", digest.pk)
    return {"created": "digest draft", "id": str(digest.pk), "state": "pending approval",
            "send_window_at": window.isoformat()}


def _assigned(p):
    from apps.crm import permissions as crm_perms

    return crm_perms.assigned_company_ids(p.request())


def _first_error(errors) -> str:
    for field_name, messages in (errors.items() if isinstance(errors, dict) else []):
        message = messages[0] if isinstance(messages, list) and messages else messages
        return f"{field_name}: {message}"
    return "That wasn't accepted."


# ================================================================ Activity

def record_call(connection, tool: str, touched: list, *, ok: bool) -> None:
    """One Activity line per tool call: the tool and the record ids, never
    the content."""
    from apps.tenancy.models import AuditEvent

    first = next(((kind, rid) for kind, rid in touched
                  if kind in ("contact", "company", "task")), (None, None))
    AuditEvent.all_objects.create(
        tenant_id=connection.tenant_id, actor=connection.user, verb="ai_app.tool",
        target_type=first[0] or "ai_app_connection",
        target_id=first[1] or connection.pk,
        payload={"tool": tool, "app": connection.app_name, "ok": ok,
                 "ids": [f"{kind}:{rid}" for kind, rid in touched[:50]]})
    type(connection).all_objects.filter(pk=connection.pk).update(last_used_at=timezone.now())


READ_TOOLS = (practice_summary, list_companies, company_overview, search_contacts, get_contact,
              list_pipelines, list_tasks, list_goals, list_notes, scorecard_readings,
              pending_meeting_proposals, sending_queue, digest_drafts, invoices_summary,
              documents, list_strategy_sessions, strategy_session)
WRITE_TOOLS = (create_task, add_note, draft_email, propose_map_rows, enter_kpi_reading,
               create_digest_draft)
