"""The branded value-report PDF — FR-4B.38, FR-4B.39, ruling 4.

**A snapshot at export, never a live render.** The document a quarterly
conversation was held over still reads the way it read that day, a year and four
measurements later. That is the whole reason `goal_report_export` exists, and
the reason an export records which narrative version it carried.

One brand system, not a third: the colours come from the same place the email
layout takes them, and WeasyPrint is already established by Module 4's strategy
PDF.

**Exporting is not sending.** Nothing here reaches a client; a PDF travels only
as an attachment on an ordinary Outbox message a person approves.
"""

from __future__ import annotations

from django.template.loader import render_to_string
from django.utils import timezone

from apps.work import narratives as narrative_service
from apps.work import value_report
from apps.work.models import GoalReportExport

EXPORT_PURPOSE = "value_report_pdf"
EXPORT_PREFIX = "value-report"

#: Where the chart is drawn: a plain inline SVG, because a PDF renderer is not a
#: browser and a charting library here would be a dependency for one picture.
CHART_WIDTH = 520
CHART_HEIGHT = 120


def _chart(series):
    """Points laid out for the template. Returns None below the threshold —
    the decision itself lives in `value_report`, not here."""
    values = [float(point["value"]) for point in series]
    if len(values) < value_report.CHART_MINIMUM_READINGS:
        return None
    low, high = min(values), max(values)
    span = (high - low) or 1.0
    step = CHART_WIDTH / (len(values) - 1)
    points = []
    for index, (point, value) in enumerate(zip(series, values)):
        x = index * step
        y = CHART_HEIGHT - ((value - low) / span) * CHART_HEIGHT
        points.append({"x": round(x, 2), "y": round(y, 2), "at": point["at"],
                       "value": point["value"], "is_baseline": point["is_baseline"]})
    return {"points": points, "path": " ".join(f"{p['x']},{p['y']}" for p in points),
            "width": CHART_WIDTH, "height": CHART_HEIGHT,
            "low": f"{low:g}", "high": f"{high:g}"}


def context_for(request, *, company, goal=None) -> dict:
    """What the document shows. Built from the **client's** view of the report,
    so nothing a client could not see can reach a page they are handed."""
    report = value_report.report_for(request, company=company, for_client=True)
    blocks = report["current"] + report["historical"]
    if goal is not None:
        blocks = [b for b in blocks if b["id"] == str(goal.pk)]
    for block in blocks:
        block["chart"] = (_chart(block["measure"]["series"])
                          if block["measure"]["show_chart"] else None)
    return {
        "company": report["company"],
        "generated_on": timezone.localdate().strftime("%-d %B %Y"),
        # FR-4B.36b — the timeline is the all-goals view's. A single goal's page
        # is already a timeline of one goal.
        "timeline": report["timeline"] if goal is None else None,
        "blocks": blocks,
        "is_single_goal": goal is not None,
    }


def render_html(request, *, company, goal=None) -> str:
    return render_to_string("work/value_report.html",
                            context_for(request, company=company, goal=goal))


def render_pdf(request, *, company, goal=None) -> bytes:
    from weasyprint import HTML

    return HTML(string=render_html(request, company=company, goal=goal)).write_pdf()


def export(request, *, company, goal=None, actor=None):
    """Generate, store, and list it on the goal and the company (ruling F).

    **Nothing auto-deletes**: there is no retention window here and no cleanup
    job that could reach one of these rows.
    """
    from apps.tenancy import storage

    content = render_pdf(request, company=company, goal=goal)
    scope = "goal" if goal is not None else "all-goals"
    name = f"value-report-{scope}-{timezone.localdate().isoformat()}.pdf"
    stored = storage.save(
        tenant=request.tenant, content=content,
        object_key=storage.object_key(EXPORT_PREFIX, name),
        purpose=EXPORT_PURPOSE, content_type="application/pdf",
    )
    return GoalReportExport.objects.create(
        tenant=request.tenant, goal=goal, client_company=company, stored_file=stored,
        narrative_version=(narrative_service.current_version(goal)
                           if goal is not None else None),
        exported_by=actor,
    )
