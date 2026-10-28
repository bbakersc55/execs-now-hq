"""The scorecard's routes (M5 part 1). Every one finds the company through
`access.company_for` (a client user's own, an associate's assigned ones;
anything else is 404) and asks `access.Reader` what the person may see and
do. A page, KPI or reading the person may not see is 404, never 403.

GET   /api/scorecard/?company=&window=&from=&to=&page=   the page, as tiles, grid or meeting
GET   /api/scorecard/entry/?company=&day=                 the entry form for a period
POST  /api/scorecard/readings/                            {company, readings: [...]}
GET   /api/scorecard/readings/<id>/history/               every value a reading held
GET   /api/scorecard/bulk/?company=&cadence=&count=       catch up on several periods
GET   /api/scorecard/notices/?company=                    reminders waiting on the asker
GET   /api/scorecard/setup/?company=                      the practice's editor
POST  /api/scorecard/setup/                               {company}: start the scorecard
PATCH /api/scorecard/setup/                               {company, week_start}
POST  /api/scorecard/pages/  PATCH /pages/<id>/  POST /pages/<id>/archive|restore/
POST  /api/scorecard/pages/order/                         {company, ids}
POST  /api/scorecard/kpis/   PATCH /kpis/<id>/   POST /kpis/<id>/archive|restore/
POST  /api/scorecard/kpis/order/                          {page, ids}
POST  /api/scorecard/starters/                            {company, key}

The Google Sheet feed's routes (part 3) are in `views_feeds.py`.
"""

from __future__ import annotations

from datetime import date

from django.db import transaction
from django.db.models import Count
from django.http import Http404
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.tenancy.models import CLIENT_ROLES

from . import board, readings, setup
from . import periods as P
from .access import Reader, company_for
from .models import Kpi, KpiReading, Scorecard, ScorecardPage


def _today(request=None):
    """Today where the practice is."""
    membership = getattr(request, "membership", None)
    return board.today_for(membership.tenant if membership else None)


def _uuid_or_404(value):
    from apps.work.views import _is_uuid

    if not _is_uuid(str(value or "")):
        raise Http404
    return value


def _reader(request, company_id):
    if getattr(request, "membership", None) is None:
        raise Http404
    company = company_for(request, company_id)
    return Reader(request, company)


def _refuse_setup(reader):
    """403 for someone who reaches the company but does not set it up."""
    if reader.sets_up:
        return None
    if reader.is_client:
        from apps.work.teams import practice_name

        text = f"{practice_name(reader.company.tenant)} sets up the scorecard."
    else:
        text = "Assistants don't set up a scorecard; they enter the readings they own."
    return Response({"detail": text}, status=403)


def _setup_error(exc):
    body = {"detail": str(exc), **exc.extra}
    if exc.field:
        body["field"] = exc.field
    return Response(body, status=400)


class Base(APIView):
    permission_classes = [permissions.IsAuthenticated]


class BoardView(Base):
    def get(self, request):
        reader = _reader(request, request.query_params.get("company"))
        scorecard = board.scorecard_for(reader.company)
        today = _today(request)
        key = request.query_params.get("window") or "this_week"
        try:
            first = date.fromisoformat(request.query_params["from"]) \
                if request.query_params.get("from") else None
            last = date.fromisoformat(request.query_params["to"]) \
                if request.query_params.get("to") else None
            win = P.window(key, today, scorecard.week_start if scorecard else "monday",
                           first=first, last=last)
        except (ValueError, P.WindowInvalid) as exc:
            return Response({"detail": str(exc) if isinstance(exc, P.WindowInvalid)
                             else "Dates are year-month-day."}, status=400)
        if scorecard is None:
            return Response({"company": {"id": str(reader.company.pk),
                                         "name": reader.company.name},
                             "exists": False, "pages": [], "kpis": [], "page": None,
                             "may_set_up": reader.sets_up, "may_enter": False,
                             "window": {"key": win.key, "label": win.label,
                                        "first": win.first.isoformat(),
                                        "last": win.last.isoformat(),
                                        "text": board.window_text(win, today, "monday")}})
        out = board.build(reader, scorecard, request.query_params.get("page"), win, today)
        out["exists"] = True
        out["notices"] = readings.notices(request, reader.company)
        from .views_bonus import views_for_board
        out["bonus_views"] = views_for_board(reader, scorecard)
        return Response(out)


class EntryView(Base):
    def get(self, request):
        reader = _reader(request, request.query_params.get("company"))
        scorecard = board.scorecard_for(reader.company)
        if scorecard is None:
            raise Http404
        today = _today(request)
        try:
            day = date.fromisoformat(request.query_params["day"]) \
                if request.query_params.get("day") else readings.default_day(
                    reader, scorecard, today)
        except ValueError:
            return Response({"detail": "Dates are year-month-day."}, status=400)
        try:
            out = readings.form(reader, scorecard, day, today)
        except readings.ReadingRefused as exc:
            return Response({"detail": str(exc)}, status=400)
        if not out["kpis"] and not reader.enters_any:
            return Response({"detail": "There are no readings for you to enter."}, status=403)
        out["notices"] = readings.notices(request, reader.company)
        return Response(out)


class ReadingsView(Base):
    def post(self, request):
        reader = _reader(request, request.data.get("company"))
        scorecard = board.scorecard_for(reader.company)
        if scorecard is None:
            raise Http404
        if reader.only_looks:
            return Response({"detail": "A viewer looks and changes nothing."}, status=403)
        result = readings.save(reader, scorecard, request.data.get("readings") or [], _today(request))
        return Response(result, status=400 if result["errors"] else 200)


class HistoryView(Base):
    def get(self, request, pk):
        _uuid_or_404(pk)
        reading = KpiReading.objects.filter(pk=pk).select_related(
            "kpi", "kpi__page", "kpi__page__team", "kpi__audience_team",
            "kpi__scorecard").first()
        if reading is None:
            raise Http404
        reader = _reader(request, reading.kpi.scorecard.company_id)
        if not reader.sees_kpi(reading.kpi):
            raise Http404
        out = readings.history(reader, reading)
        if out is None:
            raise Http404
        return Response(out)


class BulkView(Base):
    def get(self, request):
        reader = _reader(request, request.query_params.get("company"))
        scorecard = board.scorecard_for(reader.company)
        if scorecard is None:
            raise Http404
        cadence = request.query_params.get("cadence") or "weekly"
        if cadence not in Kpi.Cadence.values:
            return Response({"detail": "Not a cadence."}, status=400)
        try:
            count = max(2, min(26, int(request.query_params.get("count") or 6)))
        except ValueError:
            count = 6
        try:
            first = date.fromisoformat(request.query_params["from"]) \
                if request.query_params.get("from") else None
        except ValueError:
            return Response({"detail": "Dates are year-month-day."}, status=400)
        return Response(readings.bulk(reader, scorecard, cadence, count, _today(request),
                                      first=first))


class NoticesView(Base):
    def get(self, request):
        if getattr(request, "membership", None) is None:
            raise Http404
        company = None
        if request.query_params.get("company") or request.membership.role in CLIENT_ROLES:
            company = company_for(request, request.query_params.get("company"))
        return Response(readings.notices(request, company))


class SetupView(Base):
    def _state(self, reader):
        from apps.tenancy.models import Membership, Role
        from apps.work import portal, teams

        company = reader.company
        scorecard = board.scorecard_for(company)
        staff = Membership.objects.filter(role__in=(Role.FF, Role.CF, Role.VA),
                                          revoked_at__isnull=True).select_related("user")
        # The practice's own scorecard: its people are the practice's.
        portal_people = [] if company.is_practice else portal.access_rows(company)
        out = {
            "company": {"id": str(company.pk), "name": company.name},
            "practice": company.is_practice,
            "exists": scorecard is not None,
            "week_start": scorecard.week_start if scorecard else "monday",
            "pages": [], "kpis": [],
            "teams": teams.names_for(company),
            "owners": sorted(
                [{"id": str(m.user_id), "name": board.name_of(m.user), "side": "practice"}
                 for m in staff]
                + [{"id": str(m.user_id), "name": board.name_of(m.user), "side": "client"}
                   for m in portal_people], key=lambda r: (r["side"], r["name"].lower())),
            "people": sorted([{"id": str(m.pk), "name": board.name_of(m.user)}
                              for m in (staff if company.is_practice else portal_people)],
                             key=lambda r: r["name"].lower()),
            "starters": setup.starters(),
        }
        if scorecard is not None:
            out["pages"] = [{"id": str(p.pk), "name": p.name, "audience": p.audience,
                             "team": str(p.team_id) if p.team_id else None,
                             "archived": p.archived_at is not None, "position": p.position}
                            for p in ScorecardPage.objects.filter(scorecard=scorecard)]
            out["kpis"] = [setup.describe(k) for k in
                           Kpi.objects.filter(scorecard=scorecard)
                           .select_related("reading_owner")
                           .prefetch_related("month_targets", "people")]
        return out

    def get(self, request):
        reader = _reader(request, request.query_params.get("company"))
        refused = _refuse_setup(reader)
        return refused or Response(self._state(reader))

    def post(self, request):
        reader = _reader(request, request.data.get("company"))
        refused = _refuse_setup(reader)
        if refused:
            return refused
        setup.ensure(reader.company, request.user)
        return Response(self._state(reader), status=201)

    def patch(self, request):
        reader = _reader(request, request.data.get("company"))
        refused = _refuse_setup(reader)
        if refused:
            return refused
        scorecard = setup.ensure(reader.company, request.user)
        try:
            setup.set_week_start(scorecard, request.data.get("week_start"), request.user)
        except setup.SetupError as exc:
            return _setup_error(exc)
        return Response(self._state(reader))


def _page_or_404(request, pk):
    _uuid_or_404(pk)
    page = ScorecardPage.objects.filter(pk=pk).select_related("scorecard").first()
    if page is None:
        raise Http404
    return page, _reader(request, page.scorecard.company_id)


def _kpi_or_404(request, pk):
    _uuid_or_404(pk)
    kpi = Kpi.objects.filter(pk=pk).select_related("scorecard", "page").first()
    if kpi is None:
        raise Http404
    return kpi, _reader(request, kpi.scorecard.company_id)


class PagesView(Base):
    def post(self, request):
        reader = _reader(request, request.data.get("company"))
        refused = _refuse_setup(reader)
        if refused:
            return refused
        scorecard = setup.ensure(reader.company, request.user)
        try:
            page = setup.create_page(scorecard, request.data, request.user)
        except setup.SetupError as exc:
            return _setup_error(exc)
        return Response({"id": str(page.pk), "name": page.name}, status=201)


class PageView(Base):
    def patch(self, request, pk):
        page, reader = _page_or_404(request, pk)
        refused = _refuse_setup(reader)
        if refused:
            return refused
        try:
            page = setup.update_page(page, request.data, request.user)
        except setup.SetupError as exc:
            return _setup_error(exc)
        return Response({"id": str(page.pk), "name": page.name})


class PageArchiveView(Base):
    restore = False

    def post(self, request, pk):
        page, reader = _page_or_404(request, pk)
        refused = _refuse_setup(reader)
        if refused:
            return refused
        try:
            setup.archive_page(page, request.user, restore=self.restore)
        except setup.SetupError as exc:
            return _setup_error(exc)
        return Response({"id": str(page.pk), "archived": page.archived_at is not None})


class PageRestoreView(PageArchiveView):
    restore = True


class PageOrderView(Base):
    def post(self, request):
        reader = _reader(request, request.data.get("company"))
        refused = _refuse_setup(reader)
        if refused:
            return refused
        scorecard = board.scorecard_for(reader.company)
        if scorecard is None:
            raise Http404
        try:
            setup.order_pages(scorecard, [str(i) for i in request.data.get("ids") or []],
                              request.user)
        except setup.SetupError as exc:
            return _setup_error(exc)
        return Response({"ok": True})


class KpisView(Base):
    def post(self, request):
        reader = _reader(request, request.data.get("company"))
        refused = _refuse_setup(reader)
        if refused:
            return refused
        # All or nothing: a refused KPI leaves no new scorecard or page behind
        # (Bryan, 2026-10-22: nothing is made until Save, and only by it).
        try:
            with transaction.atomic():
                scorecard = setup.ensure(reader.company, request.user)
                data = dict(request.data)
                if not data.get("page"):
                    first = ScorecardPage.objects.filter(scorecard=scorecard,
                                                         archived_at__isnull=True).first()
                    data["page"] = str(first.pk) if first else ""
                kpi = setup.create_kpi(scorecard, data, request.user)
        except setup.SetupError as exc:
            return _setup_error(exc)
        return Response(setup.describe(kpi), status=201)


class KpiView(Base):
    def patch(self, request, pk):
        kpi, reader = _kpi_or_404(request, pk)
        refused = _refuse_setup(reader)
        if refused:
            return refused
        try:
            kpi = setup.update_kpi(kpi, request.data, request.user)
        except setup.SetupError as exc:
            return _setup_error(exc)
        return Response(setup.describe(kpi))


class KpiArchiveView(Base):
    restore = False

    def post(self, request, pk):
        kpi, reader = _kpi_or_404(request, pk)
        refused = _refuse_setup(reader)
        if refused:
            return refused
        try:
            setup.archive_kpi(kpi, request.user, restore=self.restore)
        except setup.SetupError as exc:
            return _setup_error(exc)
        return Response(setup.describe(kpi))


class KpiRestoreView(KpiArchiveView):
    restore = True


class KpiOrderView(Base):
    def post(self, request):
        page, reader = _page_or_404(request, request.data.get("page"))
        refused = _refuse_setup(reader)
        if refused:
            return refused
        try:
            setup.order_kpis(page, [str(i) for i in request.data.get("ids") or []],
                             request.user)
        except setup.SetupError as exc:
            return _setup_error(exc)
        return Response({"ok": True})


class StartersView(Base):
    def post(self, request):
        reader = _reader(request, request.data.get("company"))
        refused = _refuse_setup(reader)
        if refused:
            return refused
        try:
            kpi = setup.create_starter(reader.company, request.data.get("key"), request.user)
        except setup.SetupError as exc:
            return _setup_error(exc)
        return Response(setup.describe(kpi), status=201)


class CompaniesView(Base):
    """The practice's Scorecard menu (Bryan, 2026-10-22): the client companies
    this person reaches, a practice owner every one and an associate those
    assigned to them, each with whether it has a scorecard yet (one with a live
    KPI) and how many KPIs. Practice owners and associates only."""

    def get(self, request):
        from apps.crm import permissions as crm_perms
        from apps.crm.models import Company
        from apps.tenancy.models import Role

        membership = getattr(request, "membership", None)
        if membership is None or membership.role not in (Role.FF, Role.CF):
            return Response({"detail": "The scorecard menu is for the practice owner and "
                                       "associates."}, status=403)
        companies = crm_perms.company_queryset_for(request, Company.objects.filter(
            is_client_company=True, deleted_at__isnull=True)).order_by("name")
        live = dict(Kpi.objects.filter(archived_at__isnull=True,
                                       scorecard__company__in=companies)
                    .values("scorecard__company_id").annotate(n=Count("id"))
                    .values_list("scorecard__company_id", "n"))
        return Response([{"id": str(c.pk), "name": c.name, "kpis": live.get(c.pk, 0),
                          "has_scorecard": live.get(c.pk, 0) > 0} for c in companies])


def has_scorecard(request) -> bool:
    """For the portal's navigation: the client user sees at least one KPI."""
    membership = getattr(request, "membership", None)
    if membership is None or membership.role not in CLIENT_ROLES:
        return False
    scorecard = Scorecard.objects.filter(company_id=membership.client_company_id).first()
    if scorecard is None:
        return False
    return bool(board.visible_pages(Reader(request, scorecard.company), scorecard))


class ScorecardAiView(Base):
    """GET  /api/scorecard/ai/?company=     what the two buttons say before a press
    POST /api/scorecard/ai/                {company, purpose: explain | note}

    The practice owner's and associates' (spec, Claude), on the practice's key."""

    PURPOSES = {"explain": "scorecard_explain", "note": "scorecard_weekly_note"}

    def get(self, request):
        from . import ai

        reader = _reader(request, request.query_params.get("company"))
        if (refusal := _refuse_setup(reader)):
            return refusal
        return Response(ai.status(request.tenant))

    def post(self, request):
        from . import ai

        reader = _reader(request, request.data.get("company"))
        if (refusal := _refuse_setup(reader)):
            return refusal
        scorecard = board.scorecard_for(reader.company)
        if scorecard is None:
            return Response({"detail": "This company has no scorecard yet."}, status=404)
        purpose = self.PURPOSES.get(str(request.data.get("purpose") or ""))
        try:
            return Response(ai.ask(reader, scorecard, purpose, _today(request)))
        except ai.ScorecardAiRefused as exc:
            return Response({"detail": str(exc)}, status=exc.status)
