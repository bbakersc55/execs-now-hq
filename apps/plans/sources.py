"""What "Draft from sources" may draw on, for one company (P11, "Drafts from
sources"):

- the company's **strategy sessions**, each with its accepted map rows;
- its **SOPs**: the SOP studio's (P10; the published version, or the
  working copy of a draft), then documents made from an SOP template and
  unlocked notes an AI app saved as an SOP draft;
- its **approved meeting proposals**: the summary and the approved action
  items and deliverables;
- its **scorecard**, the KPIs behind or off track first;
- its **documents** (titles and the fields they were filled with);
- **pasted text**, such as a notebook's summary.

**Never a source:** mail of any kind, a PIN-locked note (or any note but an
unlocked SOP draft), and People data. Each source is read through the same
scoping its own screen uses, so nothing reaches Claude that the person could
not open.
"""

from __future__ import annotations

from .models import Horizon

MAX_PASTE = 20000
MAX_SOURCE_CHARS = 8000

KINDS = ("session", "sop", "meeting", "scorecard", "document", "pasted")
KIND_LABEL = {"session": "Strategy session", "sop": "SOP", "meeting": "Meeting",
              "scorecard": "Scorecard", "document": "Document", "pasted": "Pasted text"}


def _when(value) -> str:
    if value is None:
        return ""
    day = value.date() if hasattr(value, "date") else value
    return day.strftime("%B ") + str(day.day) + day.strftime(", %Y")


def _sessions(company):
    from apps.strategy.models import StrategySession

    return StrategySession.all_objects.filter(company=company).exclude(
        state=StrategySession.State.LOST).order_by("-created_at")[:20]


def _sop_documents(company):
    from apps.esign.models import Document

    return Document.all_objects.filter(company=company, template__original__endswith="_sop") \
        .select_related("template").order_by("-created_at")[:20]


def _studio_sops(company):
    from apps.sops.models import Sop

    return Sop.objects.filter(company=company).exclude(status=Sop.Status.ARCHIVED) \
        .order_by("title")[:30]


def _studio_text(sop) -> str:
    from apps.sops.brainstorm import _sop_text
    from apps.sops.services import latest, snapshot

    version = latest(sop) if sop.version else None
    record = version.snapshot if version is not None else snapshot(sop)
    head = f"SOP, version {version.number}" if version else "SOP, a draft"
    return f"{head}\n{_sop_text(record)}"


def _sop_notes(company):
    from apps.notes.models import Note

    # Only an unlocked, live note the AI app saved as an SOP draft.
    return Note.all_objects.filter(company=company, pin_hash__isnull=True,
                                   deleted_at__isnull=True,
                                   title__istartswith="SOP draft").order_by("-created_at")[:20]


def _meetings(company):
    from apps.meetings.models import MeetingProposal

    return MeetingProposal.all_objects.filter(
        meeting__client_company=company,
        state__in=(MeetingProposal.State.ACTIONED, MeetingProposal.State.PARTIALLY_ACTIONED)) \
        .select_related("meeting").order_by("-meeting_date", "-created_at")[:20]


def _documents(company):
    from apps.esign.models import Document

    return Document.all_objects.filter(company=company).exclude(
        template__original__endswith="_sop").select_related("template") \
        .order_by("-created_at")[:20]


def menu(access) -> list[dict]:
    """The sources on offer, newest first within each kind."""
    company = access.company
    out = []
    studio = [{"type": "sop", "id": f"sop:{s.pk}", "label": f"SOP: {s.title}",
               "detail": f"Version {s.version}" if s.version else "Draft"}
              for s in _studio_sops(company)]
    if company.is_practice:
        out.append({"type": "scorecard", "id": "scorecard", "label": "The practice's scorecard",
                    "detail": "KPIs behind or off track first"})
        return out + studio
    for s in _sessions(company):
        rows = s.map_rows.filter(state="accepted").count()
        out.append({"type": "session", "id": str(s.pk),
                    "label": f"Strategy session, {_when(s.started_at or s.created_at)}",
                    "detail": f"{rows} map {'row' if rows == 1 else 'rows'}"})
    out += studio
    for d in _sop_documents(company):
        out.append({"type": "sop", "id": f"doc:{d.pk}", "label": f"SOP: {d.title}",
                    "detail": d.get_state_display()})
    for n in _sop_notes(company):
        out.append({"type": "sop", "id": f"note:{n.pk}", "label": n.title or "SOP draft",
                    "detail": f"Note, {_when(n.created_at)}"})
    for m in _meetings(company):
        out.append({"type": "meeting", "id": str(m.pk),
                    "label": f"Meeting, {_when(m.meeting_date)}" + (f": {m.title}" if m.title
                                                                     else ""),
                    "detail": "Approved proposal"})
    out.append({"type": "scorecard", "id": "scorecard", "label": "The scorecard",
                "detail": "KPIs behind or off track first"})
    for d in _documents(company):
        out.append({"type": "document", "id": str(d.pk), "label": f"Document: {d.title}",
                    "detail": d.get_state_display()})
    return out


def _session_text(session) -> str:
    lines = [f"Strategy session with {session.company.name if session.company_id else ''}"]
    for row in session.map_rows.filter(state="accepted").order_by("position"):
        bits = [f"Bottleneck: {row.bottleneck}"]
        for label, value in (("Root cause", row.root_cause), ("The fix", row.the_fix),
                             ("Owner", row.owner_text), ("Measurable", row.measurable)):
            if value:
                bits.append(f"{label}: {value}")
        if row.horizon:
            bits.append(f"Within {row.horizon} days")
        lines.append("- " + "; ".join(bits))
    return "\n".join(lines)


def _meeting_text(proposal) -> str:
    lines = [f"Meeting {proposal.title or ''} on {_when(proposal.meeting_date)}".strip()]
    if proposal.summary:
        lines.append(proposal.summary)
    for item in proposal.items.filter(state="approved", kind__in=("action_item",
                                                                  "deliverable")):
        text = (item.payload or {}).get("text") or ""
        due = (item.payload or {}).get("proposed_due_date") or ""
        if text:
            lines.append(f"- {text}" + (f" (due {due})" if due else ""))
    return "\n".join(lines)


def _scorecard_text(access) -> str:
    from apps.scorecard import board, ties
    from apps.scorecard.access import Reader

    company = access.company
    today = board.today_for(company.tenant)
    reader = Reader(access.request, company)
    rows = []
    for kpi in ties._kpi_query().filter(scorecard__company=company, archived_at__isnull=True,
                                        helper=False):
        tile = ties.tiles_for(reader, [kpi], today).get(kpi.pk)
        if tile is None:
            continue
        found = ties.latest(kpi, tile, today) or {}
        rows.append((found.get("status"), kpi.name, found))
    order = {"off_track": 0, "behind": 1, "on_track": 2, None: 3}
    rows.sort(key=lambda r: (order.get(r[0], 3), r[1].lower()))
    lines = [f"{company.name}'s scorecard (latest reading, target, status):"]
    for status, name, found in rows:
        if not found:
            lines.append(f"- {name}: no readings yet")
            continue
        lines.append(f"- {name}: {found.get('value_text')} ({found.get('period')}), "
                     f"{found.get('target_text') or 'no target'}, "
                     f"{found.get('status_label') or 'no status'}")
    return "\n".join(lines)


def _document_text(document) -> str:
    lines = [f"Document: {document.title} ({document.get_state_display()})"]
    if document.template_id:
        lines.append(f"Made from the template {document.template.name}.")
    for key, value in (document.fields or {}).items():
        if isinstance(value, str) and value.strip():
            lines.append(f"{key}: {value.strip()}")
    return "\n".join(lines)


class SourceRefused(ValueError):
    pass


def gather(access, chosen: list, pasted: str = "") -> list[tuple[str, str, str]]:
    """[(ref, label, text)] for the chosen sources, each looked up again
    against this company: an id of anything else is refused, not skipped."""
    from apps.esign.models import Document
    from apps.meetings.models import MeetingProposal
    from apps.notes.models import Note
    from apps.strategy.models import StrategySession

    company = access.company
    offered = {(m["type"], m["id"]): m["label"] for m in menu(access)}
    out = []
    for raw in chosen or []:
        kind, ident = str(raw.get("type") or ""), str(raw.get("id") or "")
        if kind == "pasted":
            continue
        label = offered.get((kind, ident))
        if label is None:
            raise SourceRefused("A chosen source isn't one of this company's.")
        if kind == "session":
            text = _session_text(StrategySession.all_objects.get(pk=ident, company=company))
        elif kind == "sop" and ident.startswith("sop:"):
            from apps.sops.models import Sop

            text = _studio_text(Sop.objects.get(pk=ident[4:], company=company))
        elif kind == "sop" and ident.startswith("doc:"):
            text = _document_text(Document.all_objects.get(pk=ident[4:], company=company))
        elif kind == "sop":
            note = Note.all_objects.get(pk=ident[5:], company=company, pin_hash__isnull=True,
                                        deleted_at__isnull=True)
            text = f"{note.title}\n{note.body}"
        elif kind == "meeting":
            text = _meeting_text(MeetingProposal.all_objects.get(
                pk=ident, meeting__client_company=company))
        elif kind == "scorecard":
            text = _scorecard_text(access)
        elif kind == "document":
            text = _document_text(Document.all_objects.get(pk=ident, company=company))
        else:
            raise SourceRefused("Choose sources from the list.")
        out.append((f"S{len(out) + 1}", label, text[:MAX_SOURCE_CHARS]))
    pasted = (pasted or "").strip()
    if pasted:
        out.append((f"S{len(out) + 1}", "Pasted text", pasted[:MAX_PASTE]))
    return out


#: Per horizon, what an item there is, for the prompt.
WHAT = {
    Horizon.PICTURE: "a statement of where the company will be in three years, or a "
                     "measurable target for then",
    Horizon.YEAR: "a goal for the year",
    Horizon.QUARTER: "a priority for the quarter",
    Horizon.MONTH: "an item of the month's plan",
    Horizon.WEEK: "the week's sprint goal: one sentence",
}
