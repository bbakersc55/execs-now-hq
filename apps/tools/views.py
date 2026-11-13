"""The tools' routes (P12). Every company route goes through the plans
engine's reach rule (`apps.plans.access`): 404 for anyone who doesn't reach
the company, and for every practice with no Command Center on.

GET    /api/tools/                          the shelf: tools, recent runs, may_build
POST   /api/tools/                          {name, description, definition}: the practice's own (owner)
GET    /api/tools/<ref>/                    a shipped key or a practice tool's id
PATCH  /api/tools/<id>/                     the owner edits the practice's tool
POST   /api/tools/<ref>/duplicate/          a practice copy of any tool (owner)
POST   /api/tools/<id>/archive/
POST   /api/tools/validate/                 {definition}: every problem, with where
POST   /api/tools/evaluate/                 {definition, values}: worked out, nothing saved
GET    /api/tools/builder/                  the price first
POST   /api/tools/builder/                  {description}: Claude's proposal, checked, not saved
GET    /api/tool-runs/?company=<id|practice|mine>
POST   /api/tool-runs/                      {company, tool, name?, run_date?}
GET    /api/tool-runs/<id>/                 the run, worked out, with its choices
PATCH  /api/tool-runs/<id>/                 {name, run_date, values, shared_with_client}
DELETE /api/tool-runs/<id>/
POST   /api/tool-runs/<id>/<duplicate|tasks|reading|propose|sop-brainstorm|import-sop|calendar>/
GET    /api/tool-runs/<id>/files/<pdf|docx|agenda|ics|calendar>/
"""

from __future__ import annotations

from datetime import date

from django.http import Http404, HttpResponse
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.tenancy.models import TENANT_ROLES

from . import builder, exports, services
from . import definition as D
from .models import Tool, ToolRun


def _today(company):
    from apps.scorecard import board

    return board.today_for(company.tenant)


def _refused(exc):
    body = {"detail": str(exc)}
    if getattr(exc, "errors", None):
        body["errors"] = exc.errors
    return Response(body, status=getattr(exc, "status", 400))


def _staff(request):
    membership = getattr(request, "membership", None)
    if membership is None or membership.role not in TENANT_ROLES \
            or not services.available(membership.tenant_id):
        raise Http404
    return membership


class Base(APIView):
    permission_classes = [permissions.IsAuthenticated]


def represent(run, access=None) -> dict:
    return {"id": str(run.pk), "name": run.name, "tool_name": run.tool_name,
            "tool_key": run.tool_key, "tool_id": str(run.tool_id) if run.tool_id else None,
            "run_date": run.run_date.isoformat(),
            "company": {"id": "practice" if run.company.is_practice else str(run.company_id),
                        "name": run.company.name, "is_practice": run.company.is_practice},
            "shared_with_client": run.shared_with_client,
            "updated_at": run.updated_at.isoformat(),
            "may_edit": bool(access and access.edits)}


def _people(company) -> list[str]:
    from apps.crm.models import Contact
    from apps.tenancy.models import Membership

    names = []
    if not company.is_practice:
        names += [f"{c.first_name} {c.last_name}".strip() for c in Contact.objects.filter(
            company=company).order_by("first_name", "last_name")[:200]]
    names += [(m.user.full_name or m.user.email) for m in Membership.all_objects.filter(
        tenant_id=company.tenant_id, role__in=TENANT_ROLES, revoked_at__isnull=True)
        .select_related("user")]
    return sorted(dict.fromkeys(n for n in names if n), key=str.lower)


def full(run, access) -> dict:
    from apps.scorecard.models import Kpi

    out = represent(run, access)
    out.update({"definition": run.definition, "values": run.values,
                "evaluation": D.evaluate(run.definition, run.values)})
    if access.edits:
        out["choices"] = {
            "people": _people(run.company),
            "kpis": [{"id": str(k.pk), "name": k.name, "cadence": k.cadence}
                     for k in Kpi.objects.filter(scorecard__company=run.company,
                                                 archived_at__isnull=True, per_person=False,
                                                 formula="").order_by("name")],
            "sop_sources": services.sop_sources(run.company),
            "has_plan": True,
        }
    return out


class ToolsView(Base):
    def get(self, request):
        from apps.crm import permissions as crm_perms
        from apps.crm.models import Company

        membership = _staff(request)
        reach = crm_perms.company_queryset_for(request, Company.objects.all()).values("pk")
        runs = ToolRun.objects.filter(archived_at__isnull=True).filter(
            company_id__in=reach) | ToolRun.objects.filter(archived_at__isnull=True,
                                                           company__is_practice=True)
        recent = runs.select_related("company").order_by("-updated_at")[:10]
        return Response({"tools": services.catalog(membership.tenant_id),
                         "recent": [represent(r) for r in recent],
                         "may_build": services.builds(request)})

    def post(self, request):
        _staff(request)
        if not services.builds(request):
            return Response({"detail": "The practice owner makes the practice's tools."},
                            status=403)
        try:
            tool = services.save_tool(request.membership.tenant, request.data, actor=request.user)
        except services.ToolRefused as exc:
            return _refused(exc)
        return Response(services.tool_of(tool.tenant_id, tool.pk), status=201)


class ToolView(Base):
    def get(self, request, ref):
        membership = _staff(request)
        return Response(services.tool_of(membership.tenant_id, ref))

    def patch(self, request, ref):
        membership = _staff(request)
        tool = Tool.objects.filter(pk=ref, archived_at__isnull=True).first() \
            if services._is_uuid(ref) else None
        if tool is None:
            return Response({"detail": "A shipped tool is duplicated, then edited."},
                            status=404 if not services._is_uuid(ref) else 404)
        if not services.builds(request):
            return Response({"detail": "The practice owner edits the practice's tools."},
                            status=403)
        try:
            tool = services.save_tool(membership.tenant, request.data, actor=request.user,
                                      tool=tool)
        except services.ToolRefused as exc:
            return _refused(exc)
        return Response(services.tool_of(tool.tenant_id, tool.pk))


class ToolDuplicateView(Base):
    def post(self, request, ref):
        membership = _staff(request)
        if not services.builds(request):
            return Response({"detail": "The practice owner makes the practice's tools."},
                            status=403)
        tool = services.duplicate_tool(membership.tenant, ref, actor=request.user)
        return Response(services.tool_of(tool.tenant_id, tool.pk), status=201)


class ToolArchiveView(Base):
    def post(self, request, ref):
        _staff(request)
        tool = Tool.objects.filter(pk=ref, archived_at__isnull=True).first() \
            if services._is_uuid(ref) else None
        if tool is None:
            raise Http404
        if not services.builds(request):
            return Response({"detail": "The practice owner archives the practice's tools."},
                            status=403)
        services.archive_tool(tool, actor=request.user)
        return Response({"archived": True})


class ValidateView(Base):
    def post(self, request):
        _staff(request)
        return Response({"errors": D.check(request.data.get("definition"))})


class EvaluateView(Base):
    def post(self, request):
        _staff(request)
        definition = request.data.get("definition")
        errors = D.check(definition)
        if errors:
            return Response({"errors": errors}, status=400)
        return Response(D.evaluate(definition, request.data.get("values") or {}))


class BuilderView(Base):
    def get(self, request):
        membership = _staff(request)
        if not services.builds(request):
            raise Http404
        return Response(builder.status(membership.tenant))

    def post(self, request):
        membership = _staff(request)
        if not services.builds(request):
            return Response({"detail": "The practice owner builds the practice's tools."},
                            status=403)
        try:
            return Response(builder.propose(membership.tenant, request.data.get("description")))
        except builder.BuilderRefused as exc:
            return Response({"detail": str(exc)}, status=exc.status)


class RunsView(Base):
    def get(self, request):
        access = services.access_for(request, request.query_params.get("company") or "")
        runs = ToolRun.objects.filter(company=access.company, archived_at__isnull=True) \
            .select_related("company")
        if access.is_client:
            runs = runs.filter(shared_with_client=True) if access.sees_all else runs.none()
        return Response({"runs": [represent(r, access) for r in runs],
                         "may_start": access.edits})

    def post(self, request):
        access = services.access_for(request, request.data.get("company") or "")
        if not access.edits:
            return Response({"detail": "The practice runs a tool."}, status=403)
        try:
            run_date = date.fromisoformat(str(request.data["run_date"])) \
                if request.data.get("run_date") else None
            run = services.start_run(access.company, request.data.get("tool"),
                                     actor=request.user, name=request.data.get("name") or "",
                                     run_date=run_date)
        except ValueError:
            return Response({"detail": "That isn't a date."}, status=400)
        return Response(full(run, access), status=201)


class RunView(Base):
    def get(self, request, pk):
        run, access = services.run_for(request, pk)
        return Response(full(run, access))

    def patch(self, request, pk):
        run, access = services.run_for(request, pk)
        if not access.edits:
            return Response({"detail": "The practice edits a run."}, status=403)
        try:
            run = services.update_run(run, request.data, actor=request.user)
        except services.ToolRefused as exc:
            return _refused(exc)
        return Response(full(run, access))

    def delete(self, request, pk):
        run, access = services.run_for(request, pk)
        if not access.edits:
            return Response({"detail": "The practice archives a run."}, status=403)
        services.archive_run(run, actor=request.user)
        return Response(status=204)


class RunActionView(Base):
    def post(self, request, pk, action):
        run, access = services.run_for(request, pk)
        if not access.edits:
            return Response({"detail": "The practice does this from a run."}, status=403)
        today = _today(run.company)
        try:
            if action == "duplicate":
                return Response(full(services.duplicate_run(run, actor=request.user), access),
                                status=201)
            if action == "tasks":
                made = services.tasks_from_flags(run, actor=request.user, role=access.role)
                return Response({"made": len(made), "titles": [t.title for t in made]},
                                status=201)
            if action == "reading":
                return Response(self._reading(request, run, today), status=201)
            if action == "propose":
                item = services.propose_to_plan(run, actor=request.user,
                                                horizon=request.data.get("horizon"),
                                                title=request.data.get("title"),
                                                done_means=request.data.get("done_means", ""),
                                                today=today)
                return Response({"proposed": str(item.pk), "horizon": item.horizon},
                                status=201)
            if action == "sop-brainstorm":
                note = services.sop_brainstorm(run, actor=request.user)
                return Response({"note": str(note.pk), "title": note.title}, status=201)
            if action == "import-sop":
                count = services.import_steps(run, request.data.get("source"),
                                              actor=request.user)
                run.refresh_from_db()
                return Response({"imported": count, "run": full(run, access)})
            if action == "calendar":
                made = services.create_events(run, request.user,
                                              run.company.tenant.timezone or "America/Denver")
                return Response({"made": len(made)}, status=201)
        except services.ToolRefused as exc:
            return _refused(exc)
        raise Http404

    def _reading(self, request, run, today):
        from apps.scorecard import board
        from apps.scorecard import periods as SP
        from apps.scorecard.models import Kpi

        kpi = Kpi.objects.filter(pk=request.data.get("kpi"), scorecard__company=run.company,
                                 archived_at__isnull=True).first() \
            if services._is_uuid(request.data.get("kpi")) else None
        if kpi is None:
            raise services.ToolRefused("Choose one of this company's KPIs.")
        try:
            day = date.fromisoformat(str(request.data.get("day") or today.isoformat()))
        except ValueError:
            raise services.ToolRefused("That isn't a date.") from None
        scorecard = board.scorecard_for(run.company)
        start = SP.start_of(day, kpi.cadence, scorecard.week_start)
        return services.send_to_kpi(run, request, result_key=request.data.get("result"),
                                    kpi_id=str(kpi.pk), period_start=start.isoformat(),
                                    today=today)


class RunFileView(Base):
    def get(self, request, pk, kind):
        run, access = services.run_for(request, pk)
        try:
            if kind == "pdf":
                return self._file(exports.pdf(run, request.user), "application/pdf",
                                  exports.filename(run, "pdf"))
            if kind == "docx":
                return self._file(exports.docx(run), "application/vnd.openxmlformats-"
                                  "officedocument.wordprocessingml.document",
                                  exports.filename(run, "docx"))
            if kind == "agenda":
                return self._file(exports.agenda_docx(run), "application/vnd.openxmlformats-"
                                  "officedocument.wordprocessingml.document",
                                  exports.filename(run, "docx").replace(".docx", "-agendas.docx"))
            if kind == "ics":
                text = services.ics(run, run.company.tenant.timezone or "America/Denver")
                return self._file(text.encode(), "text/calendar",
                                  exports.filename(run, "ics"))
            if kind == "calendar":
                from apps.calendars.models import CalendarConnection
                from config import environment

                events = services.events_of(run)
                return Response({
                    "events": [{k: v for k, v in e.items() if k != "starts"} for e in events],
                    "connected": CalendarConnection.objects.filter(user=request.user).exists(),
                    "demo": environment.is_demo()})
        except services.ToolRefused as exc:
            return _refused(exc)
        raise Http404

    def _file(self, content, mime, name):
        response = HttpResponse(content, content_type=mime)
        response["Content-Disposition"] = f'attachment; filename="{name}"'
        return response
