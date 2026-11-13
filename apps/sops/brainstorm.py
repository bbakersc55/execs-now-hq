"""Brainstorm mode (P10, "Brainstorm mode"): a saved conversation with Claude
about one process, on the practice's own key.

- **The tier** is Standard by default (the practice's choice for the action
  "SOP brainstorm" under Settings → AI) and switchable to Deep per brainstorm.
- **The price is shown before each send**, from what this send would carry
  (the sources, the conversation, the images), and the brainstorm keeps a
  running total of what it has cost. Inside the practice's caps: a key must be
  set, the month's AI budget not spent, a demo visitor's allowance not used,
  and at most `DAILY_CAP` sends a day for the practice.
- **Sources:** pasted text; screenshots and photos, which Claude reads as
  images; PDFs, whose text is extracted; a video or audio file's transcript
  (`apps.sops.media`); a note; a tool run; an SOP.
- **Four actions** make proposals a person accepts, edits or discards; nothing
  applies before that, and each decision goes to the practice library:
  "Draft the SOP" (a diff when it changes an existing SOP), "Draw the process
  map", "Make the checklist" (tasks in Work under a chosen goal or project)
  and "Suggest measures" (KPIs from the library).
"""

from __future__ import annotations

import base64
import difflib
import io
import json
import re
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from . import flow
from .models import Brainstorm, BrainstormMessage, BrainstormProposal, BrainstormSource, Sop

ACTION = "sop_brainstorm"
CHAT, DRAFT, MAP, CHECKLIST, MEASURES = ("sop_brainstorm", "sop_draft", "sop_map",
                                         "sop_checklist", "sop_measures")
PURPOSE_OF = {"chat": CHAT, "draft": DRAFT, "map": MAP, "checklist": CHECKLIST,
              "measures": MEASURES}
OUTPUT = {CHAT: 1200, DRAFT: 3000, MAP: 1500, CHECKLIST: 1500, MEASURES: 1200}
MAX_TOKENS = {CHAT: 3000, DRAFT: 6000, MAP: 3000, CHECKLIST: 3000, MEASURES: 2500}
DAILY_CAP = 60
IMAGE_TOKENS = 1600
MAX_IMAGES = 6
MAX_SOURCE_CHARS = 12000
MAX_CONTEXT_CHARS = 60000
HISTORY = 20
MAX_PASTE = 40000
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 100

SYSTEM = """You help a fractional operations executive write a standard operating
procedure (SOP) for one of their client companies, or for their own practice. You are
given the company, the SOP as it stands (if there is one), the sources the person added
(pasted text, transcripts, PDFs' text, notes, worksheet runs, images) and your
conversation so far.

Talk plainly and briefly. Ask about what is missing: who does each part, what starts
the process, what "done" looks like, where it goes wrong, and what number shows it is
working. Use the company's own words for roles and things. Never invent facts the
sources don't support; say what you'd need to know. Never use a named management
system's own terms."""

TASKS = {
    DRAFT: """Draft the SOP from everything above. Reply with JSON only:
{"title": "...", "purpose": "...", "applies_when": "...",
 "roles": [{"name": "...", "does": "..."}],
 "steps": [{"text": "...", "role": "...", "warning": "..."}],
 "category": "...", "why": "..."}
- steps are in order, one action each, written as instructions ("Count the bins.");
  "role" names who does it (one of the roles, or ""); "warning" is a safety or quality
  caution for that step, or "".
- If an SOP is given above, revise it: keep what the sources don't contradict.
- "why" is one plain sentence on what you based it on.""",
    MAP: """Draw the process map of the SOP's steps (or, with no SOP yet, the process
discussed above) as a flowchart in this small language, and reply with JSON only:
{"map": "flowchart TD\\n  ...", "why": "..."}
The language: a step is id[text], a decision is id{text?}, a start or an end is
id([text]); an arrow is a --> b, with a label as a -->|Yes| b. Ids are letters and
digits. One statement per line. Start with flowchart TD. Keep each box's text under
60 characters, and the whole map under 30 boxes. Show the real decisions and loops.""",
    CHECKLIST: """Propose a checklist of tasks to put this SOP in place at the company (not
the SOP's own steps repeated: the work of adopting it, such as training people, making
a form, setting a review). Reply with JSON only:
{"tasks": [{"title": "...", "due_in_days": 7}], "why": "..."}
At most 12 tasks, each a short instruction.""",
    MEASURES: """Choose the numbers this process should move, from the KPI list given below
only. Reply with JSON only: {"kpis": [{"name": "...", "why": "..."}], "why": "..."}.
Use each name exactly as listed. At most 4.""",
}


class BrainstormRefused(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _name(user):
    return (user.full_name or user.email) if user is not None else ""


# ------------------------------------------------------------------ the brainstorm

@transaction.atomic
def start(company, *, actor, title="", sop=None, tier=None) -> Brainstorm:
    from apps.tenancy import ai_actions

    title = " ".join(str(title or (sop.title if sop else "") or "").split())[:200] or \
        "A process"
    if tier not in Brainstorm.Tier.values:
        tier = ai_actions.tier_for(company.tenant_id, ai_actions.BY_KEY[ACTION])
        tier = tier if tier in Brainstorm.Tier.values else Brainstorm.Tier.STANDARD
    return Brainstorm.objects.create(tenant_id=company.tenant_id, company=company, sop=sop,
                                     title=title, tier=tier, created_by=actor)


def spent(brainstorm) -> Decimal:
    from django.db.models import Sum

    from apps.tenancy.models import AiCall

    return AiCall.all_objects.filter(tenant_id=brainstorm.tenant_id, target_type="sop_brainstorm",
                                     target_id=brainstorm.pk).aggregate(
        s=Sum("cost_usd"))["s"] or Decimal("0")


def _used_today(tenant) -> int:
    from apps.scorecard.ai import _day_start
    from apps.tenancy.models import AiCall

    return AiCall.all_objects.filter(tenant=tenant, purpose__in=list(PURPOSE_OF.values()),
                                     created_at__gte=_day_start(tenant)).count()


def refusal(tenant) -> str:
    from apps.scorecard.ai import _over_budget
    from apps.tenancy import claude
    from apps.tenancy.demo import visitors

    stop = visitors.ai_stop(tenant)
    if stop:
        return stop
    if claude.key_source(tenant) is None:
        return "No Anthropic API key is set. The practice owner adds one under AI usage."
    if _used_today(tenant) >= DAILY_CAP:
        return f"That is today's {DAILY_CAP} brainstorm sends for the practice. More tomorrow."
    if _over_budget(tenant):
        return "This month's AI budget is spent. Raise it under AI usage to keep going."
    return ""


# ------------------------------------------------------------------ sources

def _text_source(brainstorm, *, kind, title, text, actor, source_id=None):
    text = str(text or "").strip()
    if not text:
        raise BrainstormRefused("There's nothing to add.")
    return BrainstormSource.objects.create(
        tenant_id=brainstorm.tenant_id, brainstorm=brainstorm, kind=kind,
        title=" ".join(str(title or "").split())[:200] or "Source", text=text[:MAX_PASTE],
        created_by=actor, source_id=source_id)


def add_pasted(brainstorm, *, title, text, actor):
    return _text_source(brainstorm, kind=BrainstormSource.Kind.PASTED,
                        title=title or "Pasted text", text=text, actor=actor)


def add_note(brainstorm, note, *, actor):
    if note.pin_hash:
        raise BrainstormRefused("A PIN-locked note is never a source.", 409)
    body = note.body or ""
    if note.transcript:
        body = f"{body}\n\nTranscript: {note.transcript}"
    if note.summary:
        body = f"{body}\n\nSummary: {note.summary}"
    return _text_source(brainstorm, kind=BrainstormSource.Kind.NOTE,
                        title=f"Note: {note.title or 'Untitled'}", text=body or note.title,
                        actor=actor, source_id=note.pk)


def add_tool_run(brainstorm, run, *, actor):
    from apps.tools.services import summary_text

    return _text_source(brainstorm, kind=BrainstormSource.Kind.TOOL_RUN,
                        title=f"{run.tool_name}: {run.name}", text=summary_text(run),
                        actor=actor, source_id=run.pk)


def add_sop(brainstorm, sop, *, actor):
    from .services import snapshot

    return _text_source(brainstorm, kind=BrainstormSource.Kind.SOP, title=f"SOP: {sop.title}",
                        text=_sop_text(snapshot(sop)), actor=actor, source_id=sop.pk)


def _sop_text(record) -> str:
    lines = [f"Title: {record['title']}"]
    for key, label in (("purpose", "Purpose"), ("applies_when", "When it applies"),
                       ("category", "Category"), ("owner", "Owner")):
        if record.get(key):
            lines.append(f"{label}: {record[key]}")
    if record.get("roles"):
        lines.append("Roles: " + "; ".join(f"{r['name']} ({r.get('does', '')})"
                                           for r in record["roles"]))
    for i, step in enumerate(record.get("steps") or [], start=1):
        extra = f" [{step['role']}]" if step.get("role") else ""
        warn = f" Warning: {step['warning']}" if step.get("warning") else ""
        lines.append(f"{i}. {step['text']}{extra}{warn}")
    if record.get("process_map"):
        lines.append("Process map:\n" + record["process_map"])
    return "\n".join(lines)


def _shrink(content: bytes) -> tuple[bytes, str]:
    """An image as the API takes it: at most 1568 px on the long side."""
    from PIL import Image

    image = Image.open(io.BytesIO(content))
    image.load()
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    image.thumbnail((1568, 1568))
    out = io.BytesIO()
    image.save(out, "JPEG", quality=85)
    return out.getvalue(), "image/jpeg"


@transaction.atomic
def add_upload(brainstorm, upload, *, actor):
    """An image Claude reads, or a PDF whose text is extracted. (Video and
    audio go through `apps.sops.media`.)"""
    from apps.tenancy import storage

    from .media import MEDIA_TYPES

    content_type = (getattr(upload, "content_type", "") or "").split(";")[0].lower()
    name = re.sub(r"[^A-Za-z0-9._ -]+", "", getattr(upload, "name", "") or "file")[:120] or "file"
    if content_type in MEDIA_TYPES or content_type.startswith(("video/", "audio/")):
        raise BrainstormRefused("Video and audio are read with the media key: use “Add video "
                                "or audio”.", 409)
    if content_type.startswith("image/"):
        if upload.size > MAX_IMAGE_BYTES:
            raise BrainstormRefused("An image is 10 MB at most.")
        try:
            content, mime = _shrink(upload.read())
        except Exception:  # noqa: BLE001  (Pillow raises many kinds for a bad file)
            raise BrainstormRefused("That image couldn't be opened.") from None
        stored = storage.save(tenant=brainstorm.company.tenant, content=content,
                              object_key=storage.object_key(f"brainstorms/{brainstorm.pk}",
                                                            f"{name}.jpg"),
                              purpose="sop_brainstorm_image", content_type=mime)
        return BrainstormSource.objects.create(
            tenant_id=brainstorm.tenant_id, brainstorm=brainstorm,
            kind=BrainstormSource.Kind.IMAGE, title=name, file=stored, content_type=mime,
            created_by=actor)
    if content_type == "application/pdf" or name.lower().endswith(".pdf"):
        if upload.size > MAX_PDF_BYTES:
            raise BrainstormRefused("A PDF is 20 MB at most.")
        text = pdf_text(upload.read())
        if not text.strip():
            raise BrainstormRefused("That PDF has no text to read (a scan?). Paste its text, "
                                    "or upload its pages as images.", 409)
        return BrainstormSource.objects.create(
            tenant_id=brainstorm.tenant_id, brainstorm=brainstorm, kind=BrainstormSource.Kind.PDF,
            title=name, text=text[:MAX_PASTE * 2], content_type="application/pdf",
            created_by=actor)
    raise BrainstormRefused("Add an image, a PDF, a video or an audio file, or paste text.")


def pdf_text(content: bytes) -> str:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(content))
        pages = reader.pages[:MAX_PDF_PAGES]
        return "\n\n".join((page.extract_text() or "").strip() for page in pages)
    except Exception:  # noqa: BLE001  (pypdf raises many kinds for a damaged file)
        raise BrainstormRefused("That PDF couldn't be read.") from None


def remove_source(brainstorm, source_id):
    from apps.tenancy import storage

    source = BrainstormSource.objects.filter(brainstorm=brainstorm, pk=source_id).first()
    if source is None:
        raise BrainstormRefused("That isn't one of this brainstorm's sources.", 404)
    if source.file_id:
        try:
            storage.delete(source.file)
        except storage.StorageError:
            pass
    source.delete()


# ------------------------------------------------------------------ what is sent

def _library_kpis(company) -> list[dict]:
    from apps.scorecard import library
    from apps.scorecard.models import Kpi

    own = [{"ref": f"kpi:{k.pk}", "name": k.name, "where": "on the scorecard"}
           for k in Kpi.objects.filter(scorecard__company=company, archived_at__isnull=True)
           .order_by("name")]
    names = {k["name"].lower() for k in own}
    shipped = [{"ref": f"lib:{e['key']}", "name": e["name"], "where": "in the KPI library"}
               for e in library.entries(company.tenant) if e.get("key")
               and e["name"].lower() not in names]
    return own + shipped


def _context(brainstorm) -> tuple[str, list]:
    """(the context text, the image blocks)."""
    from apps.tenancy import storage

    from .services import snapshot

    company = brainstorm.company
    parts = [f"The company: {'the practice itself' if company.is_practice else company.name}"
             + (f" ({company.industry})" if getattr(company, "industry", "") else "") + "."]
    sop = brainstorm.sop
    if sop is not None:
        parts.append("The SOP as it stands:\n" + _sop_text(snapshot(sop)))
    else:
        parts.append(f"No SOP yet. The process: {brainstorm.title}.")
    images, room = [], MAX_CONTEXT_CHARS
    sources = list(brainstorm.sources.filter(state=BrainstormSource.State.READY))
    for i, source in enumerate(sources, start=1):
        if source.kind == BrainstormSource.Kind.IMAGE:
            parts.append(f"[Source {i}] An image: {source.title} (attached).")
            continue
        text = source.text[:min(MAX_SOURCE_CHARS, max(room, 0))]
        room -= len(text)
        parts.append(f"[Source {i}] {source.get_kind_display()}: {source.title}\n{text}")
    for source in [s for s in sources if s.kind == BrainstormSource.Kind.IMAGE][-MAX_IMAGES:]:
        try:
            data = storage.read(source.file)
        except storage.StorageError:
            continue
        images.append({"type": "image", "source": {
            "type": "base64", "media_type": source.content_type or "image/jpeg",
            "data": base64.standard_b64encode(data).decode("ascii")}})
    return "\n\n".join(parts), images


def _conversation(brainstorm, context, images, ask) -> list:
    """Alternating turns, the context first, the ask last."""
    turns = [{"role": "user", "content": [*images, {"type": "text", "text": context}]}]
    history = list(brainstorm.messages.order_by("-created_at")[:HISTORY])[::-1]
    for m in history + [None]:
        role, text = ("user", ask) if m is None else (
            "user" if m.role == BrainstormMessage.Role.USER else "assistant", m.text)
        if turns[-1]["role"] == role:
            turns[-1]["content"].append({"type": "text", "text": text})
        else:
            turns.append({"role": role, "content": [{"type": "text", "text": text}]})
    return turns


def price(brainstorm, kind="chat", message="") -> dict:
    """What the next send would cost, said before it is sent."""
    from apps.tenancy import ai_actions

    purpose = PURPOSE_OF[kind]
    context, images = _context(brainstorm)
    chars = len(SYSTEM) + len(context) + len(message or "") + len(TASKS.get(purpose, "")) + sum(
        len(m) for m in brainstorm.messages.order_by("-created_at")
        .values_list("text", flat=True)[:HISTORY])
    if purpose == MEASURES:
        chars += sum(len(k["name"]) + 20 for k in _library_kpis(brainstorm.company))
    tokens_in = chars // 4 + IMAGE_TOKENS * len(images)
    estimate = ai_actions.tier_row(brainstorm.tier).cost(tokens_in, OUTPUT[purpose])
    return {"kind": kind, "estimate_usd": str(estimate.quantize(Decimal("0.0001"))),
            "tier": brainstorm.tier, "model": ai_actions.tier_row(brainstorm.tier).model,
            "images": len(images)}


def _ask_claude(brainstorm, purpose, ask, *, actor):
    from apps.tenancy import claude

    stop = refusal(brainstorm.company.tenant)
    if stop:
        raise BrainstormRefused(stop, 409)
    context, images = _context(brainstorm)
    try:
        return claude.complete_with_call(
            tenant=brainstorm.company.tenant, purpose=purpose, system=claude.drafting(SYSTEM),
            user_text=f"{context}\n\n{ask}", messages=_conversation(brainstorm, context,
                                                                     images, ask),
            trigger="button", max_tokens=MAX_TOKENS[purpose], target_type="sop_brainstorm",
            target_id=brainstorm.pk, tier=brainstorm.tier)
    except claude.ClaudeRefused:
        raise BrainstormRefused("Claude declined to answer that.", 502) from None
    except claude.ClaudeUnavailable as exc:
        raise BrainstormRefused(str(exc), 502) from None


@transaction.atomic
def send(brainstorm, text, *, actor) -> BrainstormMessage:
    text = str(text or "").strip()
    if not text:
        raise BrainstormRefused("Say something first.")
    answer, call = _ask_claude(brainstorm, CHAT, text[:8000], actor=actor)
    BrainstormMessage.objects.create(tenant_id=brainstorm.tenant_id, brainstorm=brainstorm,
                                     role=BrainstormMessage.Role.USER, text=text[:8000],
                                     author=actor)
    reply = BrainstormMessage.objects.create(
        tenant_id=brainstorm.tenant_id, brainstorm=brainstorm, role=BrainstormMessage.Role.CLAUDE,
        text=answer, ai_call=call)
    Brainstorm.objects.filter(pk=brainstorm.pk).update(updated_at=timezone.now())
    return reply


def _json(text):
    match = re.search(r"\{.*\}", text or "", re.S)
    try:
        data = json.loads(match.group(0)) if match else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise BrainstormRefused("Claude's answer couldn't be read. Try again.", 502)
    return data


def _clean_draft(data) -> dict:
    from .services import _clean_roles

    steps = []
    for row in data.get("steps") or []:
        if isinstance(row, str):
            row = {"text": row}
        if isinstance(row, dict) and str(row.get("text") or "").strip():
            steps.append({"text": str(row["text"]).strip()[:2000],
                          "role": " ".join(str(row.get("role") or "").split())[:80],
                          "warning": str(row.get("warning") or "").strip()[:600]})
    return {"title": " ".join(str(data.get("title") or "").split())[:200],
            "purpose": str(data.get("purpose") or "").strip()[:6000],
            "applies_when": str(data.get("applies_when") or "").strip()[:3000],
            "roles": _clean_roles(data.get("roles")), "steps": steps[:60],
            "category": " ".join(str(data.get("category") or "").split())[:80]}


@transaction.atomic
def act(brainstorm, kind, *, actor) -> BrainstormProposal:
    """One of the four actions: a proposal, waiting for a person."""
    purpose = PURPOSE_OF.get(kind)
    if purpose not in TASKS:
        raise BrainstormRefused("That isn't one of the brainstorm's actions.", 404)
    ask = TASKS[purpose]
    if purpose == MEASURES:
        ask += "\n\nThe KPI list:\n" + "\n".join(
            f"- {k['name']} ({k['where']})" for k in _library_kpis(brainstorm.company))
    if purpose == MAP and brainstorm.sop is None and not brainstorm.messages.exists() \
            and not brainstorm.sources.exists():
        raise BrainstormRefused("Add a source or say something about the process first.", 409)
    answer, call = _ask_claude(brainstorm, purpose, ask, actor=actor)
    data = _json(answer)
    why = str(data.get("why") or "")[:500]
    if purpose == DRAFT:
        payload = _clean_draft(data)
        if not payload["steps"]:
            raise BrainstormRefused("Claude's draft had no steps. Add more to go on, and try "
                                    "again.", 502)
        payload["title"] = payload["title"] or brainstorm.title
    elif purpose == MAP:
        text = str(data.get("map") or "").strip()
        errors = flow.check(text)
        if not text or errors:
            raise BrainstormRefused("Claude's map couldn't be drawn: " + "; ".join(errors[:3]),
                                    502)
        payload = {"map": text}
    elif purpose == CHECKLIST:
        tasks = []
        for row in data.get("tasks") or []:
            title = " ".join(str((row or {}).get("title") if isinstance(row, dict) else row
                                 or "").split())[:200]
            if title:
                days = row.get("due_in_days") if isinstance(row, dict) else None
                tasks.append({"title": title,
                              "due_in_days": int(days) if isinstance(days, (int, float))
                              and 0 <= days <= 365 else None})
        if not tasks:
            raise BrainstormRefused("Claude proposed no tasks. Try again.", 502)
        payload = {"tasks": tasks[:12]}
    else:
        offered = {k["name"].lower(): k for k in _library_kpis(brainstorm.company)}
        kpis = []
        for row in data.get("kpis") or []:
            name = str((row or {}).get("name") if isinstance(row, dict) else row or "").strip()
            found = offered.get(name.lower())
            if found and found["ref"] not in {k["ref"] for k in kpis}:
                kpis.append({**found, "why": str(row.get("why") if isinstance(row, dict)
                                                 else "")[:300]})
        if not kpis:
            raise BrainstormRefused("Claude named no KPI from the list. Try again.", 502)
        payload = {"kpis": kpis[:4]}
    proposal = BrainstormProposal.objects.create(
        tenant_id=brainstorm.tenant_id, brainstorm=brainstorm, kind=kind, payload=payload,
        why=why, ai_call=call)
    Brainstorm.objects.filter(pk=brainstorm.pk).update(updated_at=timezone.now())
    return proposal


# ------------------------------------------------------------------ deciding

def diff(sop, payload) -> dict:
    """What accepting a draft would change on an existing SOP, field by field,
    and the steps added, removed and changed."""
    from .services import snapshot

    if sop is None:
        return {}
    now = snapshot(sop)
    fields = {}
    for key in ("title", "purpose", "applies_when", "category"):
        if payload.get(key) and payload[key] != (now.get(key) or ""):
            fields[key] = {"from": now.get(key) or "", "to": payload[key]}
    old_roles = [r["name"] for r in now.get("roles") or []]
    new_roles = [r["name"] for r in payload.get("roles") or []]
    if payload.get("roles") and old_roles != new_roles:
        fields["roles"] = {"from": ", ".join(old_roles), "to": ", ".join(new_roles)}
    old = [s["text"] for s in now.get("steps") or []]
    new = [s["text"] for s in payload.get("steps") or []]
    steps = []
    for op, a1, a2, b1, b2 in difflib.SequenceMatcher(a=old, b=new, autojunk=False).get_opcodes():
        if op == "equal":
            steps += [{"change": "same", "text": t} for t in new[b1:b2]]
        elif op == "delete":
            steps += [{"change": "removed", "text": t} for t in old[a1:a2]]
        elif op == "insert":
            steps += [{"change": "added", "text": t} for t in new[b1:b2]]
        else:
            steps += [{"change": "removed", "text": t} for t in old[a1:a2]]
            steps += [{"change": "added", "text": t} for t in new[b1:b2]]
    return {"fields": fields, "steps": steps}


def _record(proposal, accepted: bool):
    from apps.centers import recorder
    from apps.centers.models import LibraryRecord

    if not recorder._recording(proposal.tenant_id):
        return
    recorder.keep(proposal.tenant_id,
                  kind=LibraryRecord.Kind.SOP_AI_ACCEPTED if accepted
                  else LibraryRecord.Kind.SOP_AI_REJECTED,
                  source_type="sop_proposal", source_id=proposal.pk,
                  title=f"{proposal.get_kind_display()}: {proposal.brainstorm.title}",
                  structure={"kind": proposal.kind, "payload": proposal.payload,
                             "why": proposal.why, "result": proposal.result})


def _decided(proposal, state, actor, result=None):
    proposal.state = state
    proposal.decided_by, proposal.decided_at = actor, timezone.now()
    proposal.result = result or {}
    proposal.save(update_fields=["state", "decided_by", "decided_at", "result", "updated_at"])
    _record(proposal, state == BrainstormProposal.State.ACCEPTED)
    return proposal


def _waiting(brainstorm, proposal_id):
    from .access import _is_uuid

    proposal = BrainstormProposal.objects.filter(
        brainstorm=brainstorm, pk=proposal_id).first() if _is_uuid(proposal_id) else None
    if proposal is None:
        raise BrainstormRefused("That isn't one of this brainstorm's proposals.", 404)
    if proposal.state != BrainstormProposal.State.PROPOSED:
        raise BrainstormRefused("That was decided already.", 409)
    return proposal


@transaction.atomic
def discard(brainstorm, proposal_id, *, actor):
    return _decided(_waiting(brainstorm, proposal_id), BrainstormProposal.State.DISCARDED, actor)


def _sop_of(brainstorm, actor):
    from . import services

    if brainstorm.sop is None:
        brainstorm.sop = services.create(brainstorm.company, actor=actor, title=brainstorm.title)
        brainstorm.save(update_fields=["sop", "updated_at"])
    return brainstorm.sop


@transaction.atomic
def accept(brainstorm, proposal_id, *, actor, role, edits=None) -> BrainstormProposal:
    """Apply a proposal, with the person's edits. Nothing applies before this."""
    from . import services

    proposal = _waiting(brainstorm, proposal_id)
    edits = edits if isinstance(edits, dict) else {}
    if proposal.kind == BrainstormProposal.Kind.DRAFT:
        payload = _clean_draft({**proposal.payload, **edits})
        if not payload["steps"]:
            raise BrainstormRefused("The draft needs at least one step.")
        sop = _sop_of(brainstorm, actor)
        keep = {s["text"]: s.get("images", []) for s in sop.steps}
        services.update(sop, {**{k: v for k, v in payload.items() if v or k == "steps"},
                              "steps": [{**s, "images": keep.get(s["text"], [])}
                                        for s in payload["steps"]]}, actor=actor)
        proposal.payload = payload
        return _decided(proposal, BrainstormProposal.State.ACCEPTED, actor, {"sop": str(sop.pk)})
    if proposal.kind == BrainstormProposal.Kind.MAP:
        text = str(edits.get("map") or proposal.payload.get("map") or "")
        sop = _sop_of(brainstorm, actor)
        services.update(sop, {"process_map": text}, actor=actor)
        proposal.payload = {"map": text}
        return _decided(proposal, BrainstormProposal.State.ACCEPTED, actor, {"sop": str(sop.pk)})
    if proposal.kind == BrainstormProposal.Kind.CHECKLIST:
        made = _make_tasks(brainstorm, proposal, edits, actor=actor, role=role)
        return _decided(proposal, BrainstormProposal.State.ACCEPTED, actor,
                        {"tasks": [str(t.pk) for t in made]})
    made = _link_measures(brainstorm, proposal, edits, actor=actor)
    return _decided(proposal, BrainstormProposal.State.ACCEPTED, actor,
                    {"kpis": [str(k.pk) for k in made]})


def checklist_homes(company) -> dict:
    from apps.work.models import Goal, Project

    which = {"client_company__isnull": True} if company.is_practice \
        else {"client_company": company}
    goals = Goal.objects.filter(deleted_at__isnull=True, **which)
    projects = Project.objects.filter(deleted_at__isnull=True, **which)
    return {"goals": [{"id": str(g.pk), "name": g.title} for g in goals.order_by("title")[:100]],
            "projects": [{"id": str(p.pk), "name": p.title, "goal": str(p.goal_id)}
                         for p in projects.order_by("title")[:200]]}


def _make_tasks(brainstorm, proposal, edits, *, actor, role) -> list:
    from datetime import timedelta

    from apps.crm.models import Task
    from apps.work import services as work
    from apps.work.models import Goal, Project, TaskUpdate

    from .access import _is_uuid

    company = brainstorm.company
    homes = checklist_homes(company)
    project = goal = None
    if edits.get("project") and _is_uuid(edits["project"]) \
            and str(edits["project"]) in {p["id"] for p in homes["projects"]}:
        # A task sits under a project or a goal, never both.
        project = Project.objects.get(pk=edits["project"])
    elif edits.get("goal") and _is_uuid(edits["goal"]) \
            and str(edits["goal"]) in {g["id"] for g in homes["goals"]}:
        goal = Goal.objects.get(pk=edits["goal"])
    else:
        raise BrainstormRefused("Choose the goal or project the tasks go under.")
    tasks = proposal.payload.get("tasks") or []
    chosen = edits.get("chosen")
    picked = [i for i in (chosen if isinstance(chosen, list) else range(len(tasks)))
              if isinstance(i, int) and 0 <= i < len(tasks)]
    titles = edits.get("titles") if isinstance(edits.get("titles"), dict) else {}
    if not picked:
        raise BrainstormRefused("Tick at least one task to make.")
    today = timezone.localdate()
    made = []
    for i in picked:
        row = tasks[i]
        title = " ".join(str(titles.get(str(i)) or row["title"]).split())[:255]
        if not title:
            continue
        made.append(work.create_task(
            tenant=company.tenant, actor=actor, role=role, title=title,
            description=f"From the SOP brainstorm “{brainstorm.title}”.",
            status=Task.Status.NOT_STARTED,
            client_company=None if company.is_practice else company,
            project=project, goal=goal, owner=actor,
            due_date=today + timedelta(days=row["due_in_days"]) if row.get("due_in_days")
            else None, source=TaskUpdate.Source.SOP, source_id=brainstorm.pk))
    return made


def _link_measures(brainstorm, proposal, edits, *, actor) -> list:
    from apps.scorecard import library, setup
    from apps.scorecard.models import Kpi

    from . import services

    sop = _sop_of(brainstorm, actor)
    offered = proposal.payload.get("kpis") or []
    chosen = edits.get("chosen")
    picked = [offered[i] for i in (chosen if isinstance(chosen, list) else range(len(offered)))
              if isinstance(i, int) and 0 <= i < len(offered)]
    if not picked:
        raise BrainstormRefused("Tick at least one measure.")
    linked = []
    for row in picked:
        ref = str(row.get("ref") or "")
        if ref.startswith("kpi:"):
            kpi = Kpi.objects.filter(pk=ref[4:], scorecard__company=sop.company,
                                     archived_at__isnull=True).first()
        else:
            entry = next((e for e in library.entries(sop.company.tenant)
                          if e.get("key") == ref[4:]), None)
            kpi = None
            if entry is not None:
                kpi = Kpi.objects.filter(scorecard__company=sop.company, name__iexact=entry["name"],
                                         archived_at__isnull=True).first()
                if kpi is None:
                    card = setup.ensure(sop.company, actor)
                    page = card.pages.order_by("position").first()
                    kpi = setup.create_kpi(card, {**library.kpi_fields(entry),
                                                  "page": str(page.pk), "tile": "number_trend"},
                                           actor)
        if kpi is not None:
            linked.append(kpi)
    have = [str(k.kpi_id) for k in sop.kpi_links.all()]
    services.update(sop, {"kpis": have + [str(k.pk) for k in linked]}, actor=actor)
    return linked


# ------------------------------------------------------------------ for the screens

def represent(brainstorm) -> dict:
    from .media import status as media_status

    sop = brainstorm.sop
    proposals = []
    for p in brainstorm.proposals.select_related("decided_by"):
        row = {"id": str(p.pk), "kind": p.kind, "label": p.get_kind_display(), "state": p.state,
               "payload": p.payload, "why": p.why, "result": p.result,
               "decided_by": _name(p.decided_by),
               "cost_usd": str(p.ai_call.cost_usd) if p.ai_call_id else None}
        if p.kind == BrainstormProposal.Kind.DRAFT and p.state == BrainstormProposal.State.PROPOSED:
            row["diff"] = diff(sop, p.payload)
        proposals.append(row)
    return {
        "id": str(brainstorm.pk), "title": brainstorm.title, "tier": brainstorm.tier,
        "company": {"id": "practice" if brainstorm.company.is_practice
                    else str(brainstorm.company_id), "name": brainstorm.company.name,
                    "is_practice": brainstorm.company.is_practice},
        "sop": {"id": str(sop.pk), "title": sop.title, "status": sop.status} if sop else None,
        "sources": [{"id": str(s.pk), "kind": s.kind, "label": s.get_kind_display(),
                     "title": s.title, "state": s.state, "error": s.error,
                     "chars": len(s.text), "seconds": s.seconds, "kept": bool(s.file_id)
                     and s.kind == BrainstormSource.Kind.MEDIA,
                     "preview": s.text[:400]} for s in brainstorm.sources.all()],
        "messages": [{"id": str(m.pk), "role": m.role, "text": m.text, "by": _name(m.author),
                      "at": m.created_at.isoformat(),
                      "cost_usd": str(m.ai_call.cost_usd) if m.ai_call_id else None}
                     for m in brainstorm.messages.select_related("author", "ai_call")],
        "proposals": proposals,
        "spent_usd": str(spent(brainstorm).quantize(Decimal("0.0001"))),
        "price": price(brainstorm),
        "refused": refusal(brainstorm.company.tenant),
        "media": media_status(brainstorm.company.tenant),
        "homes": checklist_homes(brainstorm.company),
        "updated_at": brainstorm.updated_at.isoformat(),
    }
