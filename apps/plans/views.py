"""The plan's routes (P11). Each finds the company through
`access.company_for`, which is 404 for anyone who doesn't reach it (and for
every practice with no Command Center on), and asks `PlanAccess` what the
person may see and do.

GET    /api/plans/                              the practice's plans, each week at a glance
GET    /api/plans/<company>/?week=&month=...    the plan, a period per horizon (today's by default)
PATCH  /api/plans/<company>/                    {fiscal_year_start}
GET    /api/plans/<company>/week/               This week: the sprint, mine, my team's, what it serves
GET    /api/plans/<company>/close/?horizon=&period=   the walk
POST   /api/plans/<company>/close/              {horizon, period_start, outcomes: {id: done|not_done|carried}}
GET    /api/plans/<company>/sources/            what a draft may draw on, and its price
POST   /api/plans/<company>/draft/              {horizon, period_start, parent?, sources, pasted}
POST   /api/plans/from-session/                 {session}: a converted session's 30/60/90 rows
POST   /api/plan-items/                         {company, horizon, ...}: onto the plan, or proposed
PATCH  /api/plan-items/<id>/
DELETE /api/plan-items/<id>/
POST   /api/plan-items/<id>/accept/   /discard/

`<company>` is a company's id, "practice" for the practice's own plan, or
"mine" for a client user's own company.
"""

from __future__ import annotations

from datetime import date

from django.http import Http404
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.work.permissions import NotTheirTeam

from . import ai, read, services, sources
from . import periods as P
from .access import PlanAccess, access_for, available, company_for
from .models import PlanItem


def _today(company):
    from apps.scorecard import board

    return board.today_for(company.tenant)


def _refused(exc, status=None):
    body = {"detail": str(exc)}
    if getattr(exc, "field", None):
        body["field"] = exc.field
    return Response(body, status=status or getattr(exc, "status", 400))


class Base(APIView):
    permission_classes = [permissions.IsAuthenticated]


class PlansView(Base):
    def get(self, request):
        from apps.crm import permissions as crm_perms
        from apps.crm.models import Company
        from apps.scorecard.practice import practice_company
        from apps.tenancy.models import TENANT_ROLES

        membership = getattr(request, "membership", None)
        if membership is None or membership.role not in TENANT_ROLES \
                or not available(membership.tenant_id):
            raise Http404
        companies = list(crm_perms.company_queryset_for(request, Company.objects.filter(
            is_client_company=True, deleted_at__isnull=True)).order_by("name"))
        practice = practice_company(membership.tenant)
        today = _today(practice)
        glance = read.glance([practice, *companies], today)
        rows = [{"id": "practice", "company_id": str(practice.pk), "name": practice.name,
                 "is_practice": True, "week": glance.get(practice.pk)}]
        rows += [{"id": str(c.pk), "company_id": str(c.pk), "name": c.name,
                  "is_practice": False, "week": glance.get(c.pk)} for c in companies]
        return Response({"plans": rows, "names": read.horizon_names(membership.tenant)})


class PlanView(Base):
    def get(self, request, company):
        access = access_for(request, company)
        asked = {h: request.query_params.get(h) for h in ("picture", "year", "quarter",
                                                          "month", "week")}
        return Response(read.plan(access, _today(access.company), asked))

    def patch(self, request, company):
        access = access_for(request, company)
        if not access.edits:
            return Response({"detail": "The practice sets the plan's fiscal year."},
                            status=403)
        try:
            services.set_fiscal_start(access.company, request.data.get("fiscal_year_start"),
                                      actor=request.user)
        except services.PlanRefused as exc:
            return _refused(exc)
        return Response(read.plan(access, _today(access.company)))


class WeekView(Base):
    def get(self, request, company):
        access = access_for(request, company)
        return Response(read.week(access, _today(access.company)))


def _period(company, horizon, raw, today):
    if not raw:
        return P.start_of(horizon, today, company)
    try:
        return P.start_of(horizon, date.fromisoformat(str(raw)), company)
    except ValueError:
        raise services.PlanRefused("That isn't a date.", field="period_start") from None


class CloseView(Base):
    def get(self, request, company):
        access = access_for(request, company)
        if not access.may_close:
            raise Http404
        horizon = request.query_params.get("horizon") or ""
        if horizon not in services.CLOSABLE:
            return Response({"detail": "A week, a month or a quarter is closed."}, status=400)
        today = _today(access.company)
        try:
            start = _period(access.company, horizon, request.query_params.get("period"), today)
        except services.PlanRefused as exc:
            return _refused(exc)
        sprint = services._sprint(access.company, start) if horizon == "week" else None
        nxt = P.next_start(horizon, start)
        return Response({"horizon": horizon, "period_start": start.isoformat(),
                         "period_label": P.label(horizon, start),
                         "sprint": sprint.title if sprint is not None else "",
                         "rows": services.close_rows(access.company, horizon, start),
                         "next": {"period_start": nxt.isoformat(),
                                  "period_label": P.label(horizon, nxt)}})

    def post(self, request, company):
        access = access_for(request, company)
        if not access.may_close:
            return Response({"detail": "The practice closes a week, a month or a quarter."},
                            status=403)
        horizon = request.data.get("horizon") or ""
        today = _today(access.company)
        try:
            start = _period(access.company, horizon, request.data.get("period_start"), today) \
                if horizon in services.CLOSABLE else None
            if start is not None and start > today:
                raise services.PlanRefused("A period is closed once it has started.",
                                           status=409)
            record = services.close(access.company, horizon, start,
                                    request.data.get("outcomes") or {}, actor=request.user)
        except services.PlanRefused as exc:
            return _refused(exc)
        nxt = P.next_start(horizon, start)
        return Response({"summary": record.summary, "outcomes": record.outcomes,
                         "next": {"horizon": horizon, "period_start": nxt.isoformat(),
                                  "period_label": P.label(horizon, nxt)},
                         # Month and quarter: offer to draft the next one.
                         "offer_draft": horizon in ("month", "quarter")}, status=201)


class SourcesView(Base):
    def get(self, request, company):
        access = access_for(request, company)
        if not access.may_draft:
            raise Http404
        return Response({"sources": sources.menu(access),
                         "ai": ai.status(access.company.tenant)})


class DraftView(Base):
    def post(self, request, company):
        access = access_for(request, company)
        if not access.may_draft:
            return Response({"detail": "The practice drafts the plan."}, status=403)
        horizon = request.data.get("horizon") or ""
        today = _today(access.company)
        parent = None
        if request.data.get("parent"):
            parent = PlanItem.objects.filter(pk=request.data["parent"],
                                             company=access.company,
                                             state=PlanItem.State.ACCEPTED).first() \
                if services._is_uuid(request.data["parent"]) else None
            if parent is None:
                return Response({"detail": "That item isn't on this plan."}, status=400)
            horizon = P.below(parent.horizon) or ""
            if not horizon:
                return Response({"detail": "A week's sprint is broken into its tasks, not "
                                           "into more items."}, status=400)
        try:
            if horizon not in ("picture", "year", "quarter", "month", "week"):
                raise ai.DraftRefused("Choose a horizon.", 400)
            start = _period(access.company, horizon, request.data.get("period_start"),
                            today) if parent is None else P.start_of(
                horizon, max(today, parent.period_start), access.company)
            result = ai.draft(access, horizon=horizon, period_start=start, parent=parent,
                              chosen=request.data.get("sources") or [],
                              pasted=request.data.get("pasted") or "", actor=request.user,
                              today=today)
        except (ai.DraftRefused, services.PlanRefused) as exc:
            return _refused(exc)
        except sources.SourceRefused as exc:
            return Response({"detail": str(exc)}, status=400)
        reading = read.Reading(access, result["made"], today)
        return Response({"proposals": [reading.item(i) for i in result["made"]],
                         "cost_usd": result["cost_usd"], "used_today": result["used_today"],
                         "cap": result["cap"]}, status=201)


class FromSessionView(Base):
    def post(self, request):
        from apps.strategy.models import StrategySession

        session_id = request.data.get("session")
        session = StrategySession.objects.filter(pk=session_id).select_related(
            "company").first() if services._is_uuid(session_id) else None
        if session is None or session.company_id is None:
            raise Http404
        access = access_for(request, session.company_id)
        if not access.edits:
            return Response({"detail": "The practice puts a session on the plan."},
                            status=403)
        try:
            made = services.from_session(session, actor=request.user,
                                         today=_today(access.company))
        except services.PlanRefused as exc:
            return _refused(exc)
        return Response({"made": len(made), "titles": [i.title for i in made]}, status=201)


def _item_for(request, pk) -> tuple[PlanItem, PlanAccess]:
    if not services._is_uuid(pk):
        raise Http404
    item = PlanItem.objects.filter(pk=pk).select_related("company").first()
    if item is None:
        raise Http404
    access = access_for(request, item.company_id if not item.company.is_practice
                        else "practice")
    if not access.sees_item(item) and not (access.sees_tray
                                           and item.state == PlanItem.State.PROPOSED):
        raise Http404
    return item, access


class ItemsView(Base):
    def post(self, request):
        company_id = request.data.get("company")
        if not company_id:
            raise Http404
        access = access_for(request, company_id)
        horizon = request.data.get("horizon") or ""
        today = _today(access.company)
        try:
            if access.may_add(horizon):
                item = services.add(access.company, request.data, actor=request.user,
                                    role=access.role, today=today, request=request)
            elif access.may_propose(horizon):
                item = services.add(access.company, request.data, actor=request.user,
                                    role=access.role, today=today, request=request,
                                    state=PlanItem.State.PROPOSED,
                                    source=PlanItem.Source.CLIENT,
                                    proposed_by=request.user)
            elif horizon in access.horizons:
                return Response({"detail": "Adding to this horizon is the practice's to do."},
                                status=403)
            else:
                raise Http404
        except services.PlanRefused as exc:
            return _refused(exc)
        except NotTheirTeam as exc:
            return Response({"detail": str(exc)}, status=403)
        reading = read.Reading(access, [item], today)
        return Response(reading.item(item), status=201)


class ItemView(Base):
    def patch(self, request, pk):
        item, access = _item_for(request, pk)
        if item.state == PlanItem.State.PROPOSED:
            if not access.edits:
                return Response({"detail": "The practice edits a proposal."}, status=403)
        elif not access.may_edit(item):
            return Response({"detail": "Changing this item is the practice's to do."},
                            status=403)
        try:
            item = services.edit(item, request.data, actor=request.user, role=access.role,
                                 request=request)
        except services.PlanRefused as exc:
            return _refused(exc)
        return Response(read.Reading(access, [item], _today(access.company)).item(item))

    def delete(self, request, pk):
        item, access = _item_for(request, pk)
        if not access.edits:
            return Response({"detail": "The practice takes an item off the plan."},
                            status=403)
        services.remove(item, actor=request.user)
        return Response(status=204)


class AcceptView(Base):
    def post(self, request, pk):
        item, access = _item_for(request, pk)
        if not access.edits:
            return Response({"detail": "The practice accepts a proposal."}, status=403)
        try:
            item = services.accept(item, actor=request.user)
        except services.PlanRefused as exc:
            return _refused(exc)
        return Response(read.Reading(access, [item], _today(access.company)).item(item))


class DiscardView(Base):
    def post(self, request, pk):
        item, access = _item_for(request, pk)
        if not access.edits:
            return Response({"detail": "The practice discards a proposal."}, status=403)
        try:
            item = services.discard(item, actor=request.user)
        except services.PlanRefused as exc:
            return _refused(exc)
        return Response({"discarded": True})


__all__ = ["PlansView", "PlanView", "WeekView", "CloseView", "SourcesView", "DraftView",
           "FromSessionView", "ItemsView", "ItemView", "AcceptView", "DiscardView",
           "company_for"]
