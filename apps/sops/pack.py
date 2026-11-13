"""The Notebook pack (P10, "Notebook pack"): one zip, built on a company's
page, for the owner's own Gemini Notebook.

Numbered in reading order:

    00 README.md                  making the notebook, uploading, the prompts, pasting back
    01 prompts.md                 the prompt sets (the Operations Command Center's, or
                                  the practice's own copy once edited)
    02 Goals outline.md           goals, their projects and open tasks
    03 Plan by horizon.md         this period of each horizon of the plan
    04 Scorecard.csv              each KPI's last 13 readings
    05.. SOP - <title>.pdf        every SOP that isn't archived, on the letterhead
    .. Strategy map - <date>.pdf  each strategy session with accepted map rows
    .. Tool run - <name>.pdf      the tool runs chosen
    .. Document - <title>.pdf     the documents chosen, as signed (or as sent)
    .. Meetings.md                summaries of approved meeting proposals

**Never in a pack:** mail of any kind, any note (so never a PIN-locked one),
and People data. Each pack is recorded in Activity, with the files' names.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile

from django.db import transaction
from django.utils import timezone

from apps.tenancy.models import AuditEvent

from . import exports
from .models import PackPrompts, Sop

MAX_RUNS = 20
MAX_DOCUMENTS = 20
MAX_SESSIONS = 5

README = """# {company}: Notebook pack

Built {day} by {who} at {practice}, for your own Gemini Notebook.

## 1. Make the notebook
Open notebooklm.google.com with your own Google account and choose **New notebook**.
Name it "{company}, operations".

## 2. Upload the files
Upload every file in this pack except this README and prompts.md, in the numbered
order. They are the company's SOPs, strategy maps, plan, scorecard, chosen tool runs
and documents, and meeting summaries. Nothing in it is mail, a note, or People data.

## 3. Paste the prompts
Open prompts.md. Paste one prompt at a time into the notebook's chat, and read the
answer against the sources it cites.

## 4. Bring the answers back
Copy an answer worth keeping. In Execs NOW HQ, open the company's SOP brainstorm (or
start one from its SOPs card), choose **Paste text**, and paste it in as a source,
titled with the prompt's name. Claude can then draft or revise the SOP from it, and
nothing changes until you accept it.

The notebook is yours, under your own agreement with Google; this pack is a copy of
what was in the app on {day} and doesn't update itself.
"""


class PackRefused(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def prompts(tenant_id) -> list[dict]:
    from apps.centers.content import operations

    own = PackPrompts.all_objects.filter(tenant_id=tenant_id).first()
    return own.prompts if own is not None and own.prompts else operations.NOTEBOOK_PROMPTS


@transaction.atomic
def save_prompts(tenant, rows, *, actor) -> list[dict]:
    clean = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        title = " ".join(str(row.get("title") or "").split())[:120]
        prompt = str(row.get("prompt") or "").strip()[:4000]
        if title and prompt:
            clean.append({"title": title, "prompt": prompt})
    if not clean:
        raise PackRefused("Keep at least one prompt, with a title.")
    PackPrompts.all_objects.update_or_create(tenant=tenant, defaults={
        "prompts": clean[:20], "updated_by": actor})
    return clean


def reset_prompts(tenant) -> list[dict]:
    PackPrompts.all_objects.filter(tenant=tenant).delete()
    return prompts(tenant.pk)


def _safe(name) -> str:
    return re.sub(r"[^A-Za-z0-9 ._-]+", "", str(name or "")).strip()[:80] or "untitled"


def choices(company) -> dict:
    """What the pack dialog offers to choose: tool runs and documents."""
    from apps.esign.models import Document
    from apps.tools.models import ToolRun

    return {"runs": [{"id": str(r.pk), "name": r.name, "tool": r.tool_name,
                      "date": r.run_date.isoformat()}
                     for r in ToolRun.objects.filter(company=company, archived_at__isnull=True)
                     .order_by("-run_date")[:50]],
            "documents": [{"id": str(d.pk), "title": d.title, "state": d.get_state_display()}
                          for d in Document.all_objects.filter(company=company)
                          .exclude(pdf__isnull=True, signed_pdf__isnull=True,
                                   final_pdf__isnull=True).order_by("-created_at")[:50]],
            "always": ["Goals outline", "Plan by horizon", "Scorecard", "SOPs",
                       "Strategy maps", "Meeting summaries"],
            "never": "Mail, notes (PIN-locked or not) and People data are never in a pack."}


def _goals_outline(company) -> str:
    from apps.crm.models import Task
    from apps.work.models import Goal, Project

    lines = [f"# {company.name}: goals outline", ""]
    for goal in Goal.objects.filter(client_company=company, deleted_at__isnull=True) \
            .order_by("title"):
        lines.append(f"## {goal.title}")
        if goal.description:
            lines.append(goal.description.strip())
        for project in Project.objects.filter(goal=goal, deleted_at__isnull=True).order_by("title"):
            lines.append(f"- Project: {project.title}")
            for task in Task.objects.filter(project=project, deleted_at__isnull=True) \
                    .exclude(status=Task.Status.DONE).order_by("due_date")[:30]:
                due = f" (due {task.due_date:%b %-d})" if task.due_date else ""
                lines.append(f"  - {task.title}{due}")
        lines.append("")
    if len(lines) == 2:
        lines.append("No goals yet.")
    return "\n".join(lines)


def _plan(company) -> str:
    from apps.plans import periods as PP
    from apps.plans.models import Horizon, PlanItem
    from apps.plans.read import horizon_names

    from .services import _today

    today = _today(company)
    names = horizon_names(company.tenant)
    lines = [f"# {company.name}: the plan, by horizon", ""]
    for horizon in Horizon.values:
        start = PP.start_of(horizon, today, company)
        lines.append(f"## {names.get(horizon) or Horizon(horizon).label}: "
                     f"{PP.label(horizon, start, company)}")
        items = PlanItem.objects.filter(company=company, horizon=horizon, period_start=start,
                                        state=PlanItem.State.ACCEPTED).order_by("position")
        for item in items:
            done = f" — done means: {item.done_means}" if item.done_means else ""
            lines.append(f"- {item.title} ({item.get_status_display()}){done}")
        if not items:
            lines.append("- (nothing yet)")
        lines.append("")
    return "\n".join(lines)


def _scorecard_csv(company) -> bytes:
    from apps.scorecard import periods as SP
    from apps.scorecard.models import Kpi, KpiReading

    from .services import _today

    today = _today(company)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["KPI", "Cadence", "Target", "Period", "Value"])
    for kpi in Kpi.objects.filter(scorecard__company=company, archived_at__isnull=True,
                                  per_person=False).select_related("scorecard").order_by("name"):
        start = SP.start_of(today, kpi.cadence, kpi.scorecard.week_start)
        since = start
        for _ in range(12):
            since = SP.previous_start(since, kpi.cadence, kpi.scorecard.week_start)
        readings = KpiReading.objects.filter(kpi=kpi, membership__isnull=True,
                                             period_start__gte=since).order_by("period_start")
        for r in readings:
            writer.writerow([kpi.name, kpi.cadence, kpi.target_value if kpi.target_value
                             is not None else "", r.period_start.isoformat(), r.value])
        if not readings:
            writer.writerow([kpi.name, kpi.cadence, kpi.target_value or "", "", ""])
    return out.getvalue().encode()


def _meetings(company) -> str:
    from apps.plans.sources import _meeting_text, _meetings as meetings_of

    found = list(meetings_of(company))
    lines = [f"# {company.name}: approved meeting summaries", ""]
    for proposal in found:
        lines.append(_meeting_text(proposal))
        lines.append("")
    if not found:
        lines.append("No approved meeting proposals yet.")
    return "\n".join(lines)


def build(company, *, actor, runs=(), documents=()) -> tuple[bytes, list[str]]:
    from apps.esign.models import Document
    from apps.strategy import pdf as strategy_pdf
    from apps.strategy.models import StrategySession
    from apps.tenancy import storage
    from apps.tools import exports as tool_exports
    from apps.tools.models import ToolRun

    from .access import _is_uuid
    from .services import _today

    if company.is_practice:
        raise PackRefused("A Notebook pack is built for a client company.", 409)
    run_ids = [r for r in runs or [] if _is_uuid(r)][:MAX_RUNS]
    doc_ids = [d for d in documents or [] if _is_uuid(d)][:MAX_DOCUMENTS]
    chosen_runs = list(ToolRun.objects.filter(pk__in=run_ids, company=company,
                                              archived_at__isnull=True))
    chosen_docs = list(Document.all_objects.filter(pk__in=doc_ids, company=company))
    if len(chosen_runs) != len(run_ids) or len(chosen_docs) != len(doc_ids):
        raise PackRefused("A chosen run or document isn't one of this company's.", 404)
    files: list[tuple[str, bytes]] = []
    n = [0]

    def add(name, content):
        files.append((f"{n[0]:02d} {name}", content if isinstance(content, bytes)
                      else content.encode()))
        n[0] += 1

    from apps.crm.services.email_layout import branding

    brand = branding(company.tenant)
    add("README.md", README.format(company=company.name, day=f"{_today(company):%B %-d, %Y}",
                                   who=(actor.full_name or actor.email),
                                   practice=brand.display_name or brand.practice_name or ""))
    add("prompts.md", "\n\n".join(
        [f"# Prompts for {company.name}'s notebook"]
        + [f"## {i}. {p['title']}\n\n{p['prompt']}"
           for i, p in enumerate(prompts(company.tenant_id), start=1)]))
    add("Goals outline.md", _goals_outline(company))
    add("Plan by horizon.md", _plan(company))
    add("Scorecard.csv", _scorecard_csv(company))
    for sop in Sop.objects.filter(company=company).exclude(status=Sop.Status.ARCHIVED) \
            .order_by("title"):
        from .services import latest

        version = latest(sop) if sop.status == Sop.Status.PUBLISHED else None
        tag = "" if version else " (draft)"
        add(f"SOP - {_safe(sop.title)}{tag}.pdf", exports.pdf(sop, actor, version))
    sessions = [s for s in StrategySession.all_objects.filter(company=company)
                .order_by("-created_at") if s.map_rows.filter(state="accepted").exists()]
    for session in sessions[:MAX_SESSIONS]:
        day = (session.started_at or session.created_at).date()
        add(f"Strategy map - {day:%Y-%m-%d}.pdf", strategy_pdf.render_pdf(session))
    for run in chosen_runs:
        add(f"Tool run - {_safe(run.name)}.pdf", tool_exports.pdf(run, actor))
    for document in chosen_docs:
        stored = document.final_pdf or document.signed_pdf or document.pdf
        if stored is None:
            continue
        try:
            add(f"Document - {_safe(document.title)}.pdf", storage.read(stored))
        except storage.StorageError:
            continue
    add("Meeting summaries.md", _meetings(company))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files:
            zf.writestr(name, content)
    names = [name for name, _ in files]
    AuditEvent.all_objects.create(
        tenant_id=company.tenant_id, actor=actor, verb="sops.pack_built",
        target_type="company", target_id=company.pk,
        payload={"files": names, "runs": len(chosen_runs), "documents": len(chosen_docs)})
    return out.getvalue(), names


def filename(company) -> str:
    stem = re.sub(r"[^A-Za-z0-9]+", "-", company.name).strip("-") or "company"
    return f"{stem}-notebook-pack-{timezone.localdate():%Y%m%d}.zip"
