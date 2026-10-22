"""The bonus routes (M5 part 2). Each finds the company through
`access.company_for` and asks `bonus.BonusReader` whose rows the person is
sent (decision 7). A plan the reader can see none of is 404.

GET   /api/scorecard/bonus/?company=&view=mine|team|all&plan=&period=
GET   /api/scorecard/bonus/payroll/?company=&period=      the closed period as .xlsx
POST  /api/scorecard/bonus/plans/                          {company, ...}: a new plan
GET   /api/scorecard/bonus/plans/<id>/                     for the editor
PATCH /api/scorecard/bonus/plans/<id>/
POST  /api/scorecard/bonus/plans/<id>/copy-forward/        the next period's plan
POST  /api/scorecard/bonus/plans/<id>/archive/
POST  /api/scorecard/bonus/plans/<id>/close/               freeze an ended period
POST  /api/scorecard/bonus/plans/<id>/reopen/              {confirm: true}: the client owner
"""

from __future__ import annotations

from django.http import Http404, HttpResponse
from rest_framework.response import Response

from . import board, bonus, payroll
from .models import BonusPlan, Kpi
from .setup import SetupError
from .views import Base, _reader, _setup_error, _today, _uuid_or_404


def _period_key(plan) -> str:
    return f"{plan.period}:{plan.period_start.isoformat()}"


def _default_period(plans, today):
    """The period running today, monthly before quarterly, else the latest."""
    running = [p for p in plans if p.period_start <= today <= bonus.period_end(p)]
    running.sort(key=lambda p: (p.period != "monthly", -p.period_start.toordinal()))
    if running:
        return _period_key(running[0])
    return _period_key(plans[0]) if plans else None


def _editor_choices(scorecard):
    from apps.tenancy.models import CLIENT_ROLES, Membership

    kpis = [{"id": str(k.pk), "name": k.name, "kind": k.kind, "direction": k.direction,
             "rollup": k.rollup, "cadence": k.cadence, "target": board.num(k.target_value),
             "people": [str(m) for m in k.people.values_list("membership_id", flat=True)]}
            for k in Kpi.objects.filter(scorecard=scorecard, archived_at__isnull=True,
                                        per_person=True).exclude(direction="range")
            .order_by("page__position", "position", "created_at")]
    members = [{"membership": str(m.pk), "name": board.name_of(m.user)}
               for m in Membership.objects.filter(client_company=scorecard.company,
                                                  role__in=CLIENT_ROLES,
                                                  revoked_at__isnull=True)
               .select_related("user").order_by("user__full_name", "user__email")]
    return {"kpis": kpis, "members": members}


class BonusView(Base):
    def get(self, request):
        reader = _reader(request, request.query_params.get("company"))
        scorecard = board.scorecard_for(reader.company)
        if scorecard is None:
            raise Http404
        br = bonus.BonusReader(reader)
        today = _today(request)
        plans = bonus.visible_plans(scorecard)
        people = bonus.plan_people(plans)
        # A plan is the reader's business only when they see one of its rows.
        mine_plans = [p for p in plans if br.people_of(people[p.pk])]
        views = br.views([people[p.pk] for p in plans])
        out = {"views": views, "may_build": br.builds, "may_close": br.closes,
               "may_confirm_reopen": br.confirms_reopen, "sees_amounts": br.sees_amounts,
               "practice": reader.is_practice, "practice_name": _practice(reader)}
        if br.builds:
            out["editor"] = _editor_choices(scorecard)
        view = request.query_params.get("view") or (views[0] if views else None)
        if view is None or view not in views:
            out["view"] = None
            return Response(out)
        out["view"] = view
        week_start = scorecard.week_start
        if view == "mine":
            out.update(self._mine(reader, br, plans, people, request, today, week_start))
            return Response(out)
        periods = {}
        for p in mine_plans:
            periods.setdefault(_period_key(p), bonus.period_label(p))
        out["periods"] = [{"key": k, "label": v} for k, v in periods.items()]
        key = request.query_params.get("period") or _default_period(mine_plans, today)
        if key and key not in periods:
            raise Http404
        out["period"] = key
        chosen = [p for p in mine_plans if _period_key(p) == key]
        loaded = bonus.Loaded(chosen)
        groups = []
        for plan in chosen:
            rows = bonus.results(plan, loaded, today, week_start,
                                 people=br.people_of(people[plan.pk]))
            if not br.sees_amounts:
                rows = [bonus.strip_amounts(r) for r in rows]
            head = bonus.plan_head(plan, today, totals=bonus.totals_of(rows)
                                   if br.sees_amounts else None)
            if plan.closed_at and br.sees_everyone:
                fixes = bonus.corrections(plan, today)
                if fixes:
                    head["corrections"] = fixes
            if br.builds:
                head["next_exists"] = BonusPlan.all_objects.filter(
                    series=plan.series, period_start=_next(plan)).exists()
            groups.append({"plan": head, "rows": rows})
        out["plans"] = groups
        if view == "all" and br.sees_amounts:
            closed = [g for g in groups if g["plan"]["closed"]]
            out["payroll"] = [{"name": r["name"], "plan": g["plan"]["name"],
                               "period": g["plan"]["period_label"], "earned": r["earned"]}
                              for g in closed for r in g["rows"]]
            out["payroll_open"] = [g["plan"]["name"] for g in groups if not g["plan"]["closed"]]
        return Response(out)

    def _mine(self, reader, br, plans, people, request, today, week_start):
        me = reader.membership.pk
        on = [p for p in plans if me in people[p.pk]]
        if not on:
            raise Http404
        wanted = request.query_params.get("plan")
        if wanted:
            plan = next((p for p in on if str(p.pk) == wanted), None)
            if plan is None:
                raise Http404
        else:
            running = [p for p in on if p.period_start <= today <= bonus.period_end(p)]
            plan = running[0] if running else on[0]
        loaded = bonus.Loaded([plan])
        rows = bonus.results(plan, loaded, today, week_start, people={me})
        if not rows:
            raise Http404
        earlier = []
        for p in [p for p in on if p.series == plan.series and p.period_start
                  < plan.period_start][:6]:
            row = bonus.results(p, bonus.Loaded([p]), today, week_start, people={me})
            if row:
                earlier.append({"id": str(p.pk), "label": bonus.period_label(p),
                                "short": bonus.P.MONTHS[p.period_start.month - 1]
                                if p.period == "monthly" else bonus.period_label(p),
                                "earned": row[0]["earned"], "full": row[0]["amount"],
                                "closed": p.closed_at is not None})
        return {"plan": bonus.plan_head(plan, today), "me": rows[0], "earlier": earlier,
                "choices": [{"id": str(p.pk), "label": f"{bonus.period_label(p)}"
                             + (f" · {p.name}" if len({q.series for q in on}) > 1 else "")}
                            for p in on]}


def _next(plan):
    return bonus.P.next_start(plan.period_start, plan.period)


def _practice(reader):
    from apps.work.teams import practice_name

    return practice_name(reader.company.tenant)


def _plan_for(request, pk, *, need="see"):
    """The plan, after the reader is known to see it; 404 otherwise."""
    _uuid_or_404(pk)
    plan = BonusPlan.objects.filter(pk=pk).select_related("scorecard", "scorecard__company") \
        .first()
    if plan is None:
        raise Http404
    reader = _reader(request, plan.scorecard.company_id)
    br = bonus.BonusReader(reader)
    if not br.people_of(bonus.plan_people([plan])[plan.pk]) and not br.sees_everyone:
        raise Http404
    return plan, reader, br


def _refuse(text):
    return Response({"detail": text}, status=403)


class PayrollView(Base):
    def get(self, request):
        reader = _reader(request, request.query_params.get("company"))
        scorecard = board.scorecard_for(reader.company)
        if scorecard is None:
            raise Http404
        br = bonus.BonusReader(reader)
        if not br.sees_everyone or not br.sees_amounts:
            raise Http404
        key = request.query_params.get("period") or ""
        today = _today(request)
        plans = [p for p in bonus.visible_plans(scorecard)
                 if p.closed_at and _period_key(p) == key]
        if not plans:
            return Response({"detail": "Nothing in that period is closed yet."}, status=404)
        loaded = bonus.Loaded(plans)
        groups = [(bonus.plan_head(p, today),
                   bonus.results(p, loaded, today, scorecard.week_start)) for p in plans]
        data = payroll.workbook(payroll.rows_for(groups))
        label = groups[0][0]["period_label"].replace(" ", "-")
        name = f"bonus-payroll-{reader.company.name}-{label}".replace("/", "-")
        response = HttpResponse(data, content_type="application/vnd.openxmlformats-"
                                "officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = f'attachment; filename="{name}.xlsx"'
        return response


class PlansView(Base):
    def post(self, request):
        reader = _reader(request, request.data.get("company"))
        scorecard = board.scorecard_for(reader.company)
        if scorecard is None:
            raise Http404
        if not bonus.BonusReader(reader).builds:
            return _refuse(f"{_practice(reader)} builds the bonus plans.")
        try:
            plan = bonus.create_plan(scorecard, request.data, request.user)
        except SetupError as exc:
            return _setup_error(exc)
        return Response(bonus.describe(plan), status=201)


class PlanView(Base):
    def get(self, request, pk):
        plan, reader, br = _plan_for(request, pk)
        if not br.builds:
            raise Http404
        return Response(bonus.describe(plan))

    def patch(self, request, pk):
        plan, reader, br = _plan_for(request, pk)
        if not br.builds:
            return _refuse(f"{_practice(reader)} builds the bonus plans.")
        try:
            plan = bonus.update_plan(plan, request.data, request.user)
        except SetupError as exc:
            return _setup_error(exc)
        return Response(bonus.describe(plan))


class PlanCopyView(Base):
    def post(self, request, pk):
        plan, reader, br = _plan_for(request, pk)
        if not br.builds:
            return _refuse(f"{_practice(reader)} builds the bonus plans.")
        try:
            new = bonus.copy_forward(plan, request.user)
        except SetupError as exc:
            return _setup_error(exc)
        return Response(bonus.describe(new), status=201)


class PlanArchiveView(Base):
    def post(self, request, pk):
        plan, reader, br = _plan_for(request, pk)
        if not br.builds:
            return _refuse(f"{_practice(reader)} builds the bonus plans.")
        try:
            bonus.archive_plan(plan, request.user)
        except SetupError as exc:
            return _setup_error(exc)
        return Response({"archived": True})


class PlanCloseView(Base):
    def post(self, request, pk):
        plan, reader, br = _plan_for(request, pk)
        if not br.closes:
            return _refuse("The client owner or the practice closes a period.")
        try:
            bonus.close(plan, request.user, _today(request))
        except SetupError as exc:
            return _setup_error(exc)
        return Response(bonus.plan_head(plan, _today(request)))


class PlanReopenView(Base):
    def post(self, request, pk):
        plan, reader, br = _plan_for(request, pk)
        if not br.confirms_reopen:
            return _refuse("Only the client owner can confirm working a closed period's "
                           "amounts out again.")
        if request.data.get("confirm") is not True:
            return Response({"detail": "Confirm to work the amounts out again."}, status=400)
        try:
            bonus.reopen(plan, request.user, _today(request))
        except SetupError as exc:
            return _setup_error(exc)
        return Response(bonus.plan_head(plan, _today(request)))


def views_for_board(reader, scorecard):
    """Which bonus tabs the scorecard page shows this reader."""
    if scorecard is None:
        return []
    br = bonus.BonusReader(reader)
    plans = bonus.visible_plans(scorecard)
    if not plans:
        return ["all"] if br.builds else []
    people = bonus.plan_people(plans)
    return br.views([people[p.pk] for p in plans])


__all__ = ["BonusView", "PayrollView", "PlansView", "PlanView", "PlanCopyView",
           "PlanArchiveView", "PlanCloseView", "PlanReopenView", "views_for_board"]
