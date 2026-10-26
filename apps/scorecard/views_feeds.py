"""The Google Sheet feed's routes (M5 part 3). Only the practice owner and
associates set a feed up, as they set up the scorecard; the KPI is found
through the company the asker reaches, so another practice's KPI is 404.

GET    /api/scorecard/feeds/?company=&kpi=      the Google state, the KPI, its feed
POST   /api/scorecard/feeds/consent/            {company, kpi}: Reconnect Google
POST   /api/scorecard/feeds/open/               {company, kpi, spreadsheet, tab?}: the tabs and first rows
POST   /api/scorecard/feeds/preview/            {company, kpi, …mapping}: what it would make
PUT    /api/scorecard/feeds/                    {company, kpi, …mapping}: save, then read once
DELETE /api/scorecard/feeds/?company=&kpi=      stop it; the readings stay
POST   /api/scorecard/feeds/run/                {company, kpi}: read it now
"""

from __future__ import annotations

from django.http import Http404
from rest_framework.response import Response

from apps.tenancy.models import AuditEvent

from . import feeds, sheets
from . import periods as P
from .models import Kpi, KpiFeed
from .views import Base, _reader, _refuse_setup, _today, _uuid_or_404


def _kpi(request, data):
    reader = _reader(request, data.get("company"))
    kpi = Kpi.objects.filter(pk=_uuid_or_404(data.get("kpi")),
                             scorecard__company=reader.company,
                             archived_at__isnull=True).select_related("scorecard").first()
    if kpi is None:
        raise Http404
    return reader, kpi


def _feed_payload(feed):
    if feed is None:
        return None
    return {"spreadsheet_id": feed.spreadsheet_id, "spreadsheet_name": feed.spreadsheet_name,
            "tab": feed.tab, "mode": feed.mode, "refresh": feed.refresh, "active": feed.active,
            "date_column": feed.date_column, "date_header": feed.date_header,
            "value_column": feed.value_column, "value_header": feed.value_header,
            "name_column": feed.name_column, "name_header": feed.name_header,
            "header_row": feed.header_row, "cell": feed.cell, "people": feed.people,
            "last_run_at": feed.last_run_at.isoformat() if feed.last_run_at else None,
            "last_success_at": feed.last_success_at.isoformat() if feed.last_success_at else None,
            "last_error": feed.last_error, "account": feed.connection.email_address
            if feed.connection_id else ""}


def _refused(exc):
    return Response({"detail": str(exc)}, status=400)


class FeedsView(Base):
    def get(self, request):
        reader, kpi = _kpi(request, request.query_params)
        if (refusal := _refuse_setup(reader)):
            return refusal
        feed = KpiFeed.objects.filter(kpi=kpi, active=True).select_related("connection").first()
        people = [{"id": str(m), "name": n} for m, n in sorted(
            feeds.tracked_names(kpi).items(), key=lambda kv: kv[1].lower())]
        return Response({
            "google": feeds.connection_state(request.tenant.pk, request.user),
            "kpi": {"id": str(kpi.pk), "name": kpi.name, "per_person": kpi.per_person,
                    "cadence": kpi.cadence, "cadence_noun": P.noun(kpi.cadence),
                    "kind": kpi.kind, "duration_unit": kpi.duration_unit,
                    "people": people},
            "feed": _feed_payload(feed),
        })

    def put(self, request):
        reader, kpi = _kpi(request, request.data)
        if (refusal := _refuse_setup(reader)):
            return refusal
        try:
            config = feeds.clean(kpi, request.data)
            client, connection = feeds.client_for(request.tenant.pk, request.user)
        except sheets.FeedRefused as exc:
            return _refused(exc)
        except feeds.NoSheetsAccess as exc:
            return Response({"detail": str(exc), "reconnect": exc.reconnect}, status=409)
        today = _today(request)
        before = KpiFeed.all_objects.filter(kpi=kpi).first()
        cell_from = None
        if config["mode"] == KpiFeed.Mode.CELL:
            # A cell holds the open period's number: the first reading it
            # gives is this period's, at its close.
            same = before is not None and before.active and before.mode == config["mode"] \
                and before.cell == config["cell"] and before.tab == config["tab"] \
                and before.spreadsheet_id == config["spreadsheet_id"]
            cell_from = before.cell_from if same else \
                P.start_of(today, kpi.cadence, kpi.scorecard.week_start)
        # A KPI has one feed: switching to a sheet stops the others.
        feeds.stop_other_feeds(kpi, Kpi.Feed.SHEET)
        feed, made = KpiFeed.all_objects.update_or_create(
            kpi=kpi, defaults={**config, "tenant_id": kpi.tenant_id, "cell_from": cell_from,
                               "connection": connection, "active": True,
                               "last_error": "", "error_since": None,
                               "created_by": request.user})
        AuditEvent.objects.create(
            tenant_id=kpi.tenant_id, actor=request.user,
            verb="scorecard.feed_set" if made else "scorecard.feed_changed",
            target_type="company", target_id=kpi.scorecard.company_id,
            payload={"kpi": str(kpi.pk), "name": kpi.name, "mode": feed.mode,
                     "spreadsheet": feed.spreadsheet_name or feed.spreadsheet_id,
                     "tab": feed.tab})
        Kpi.objects.filter(pk=kpi.pk).update(feed=Kpi.Feed.SHEET)
        result = feeds.run(feed, today, client=client)
        return Response({"feed": _feed_payload(feed), "run": result})

    def delete(self, request):
        reader, kpi = _kpi(request, request.query_params)
        if (refusal := _refuse_setup(reader)):
            return refusal
        feed = KpiFeed.objects.filter(kpi=kpi, active=True).first()
        if feed is None:
            return Response({"detail": f"{kpi.name} has no feed to stop."}, status=400)
        feed.active = False
        feed.save(update_fields=["active", "updated_at"])
        Kpi.objects.filter(pk=kpi.pk).update(feed=Kpi.Feed.HAND)
        AuditEvent.objects.create(
            tenant_id=kpi.tenant_id, actor=request.user, verb="scorecard.feed_stopped",
            target_type="company", target_id=kpi.scorecard.company_id,
            payload={"kpi": str(kpi.pk), "name": kpi.name})
        return Response({"feed": None})


class FeedConsentView(Base):
    def post(self, request):
        reader, kpi = _kpi(request, request.data)
        if (refusal := _refuse_setup(reader)):
            return refusal
        try:
            url = feeds.consent_url(request, kpi)
        except feeds.NoSheetsAccess as exc:
            return Response({"detail": str(exc)}, status=409)
        return Response({"authorization_url": url})


class FeedOpenView(Base):
    def post(self, request):
        reader, kpi = _kpi(request, request.data)
        if (refusal := _refuse_setup(reader)):
            return refusal
        spreadsheet_id = sheets.spreadsheet_id_from(str(request.data.get("spreadsheet") or ""))
        if not spreadsheet_id:
            return Response({"detail": "That doesn't look like a Google Sheet. Open the sheet "
                                       "and paste the address from the browser's address bar."},
                            status=400)
        try:
            client, connection = feeds.client_for(request.tenant.pk, request.user)
            meta = client.spreadsheet(spreadsheet_id)
            names = [t["title"] for t in meta["tabs"]]
            if not names:
                return Response({"detail": "That spreadsheet has no tabs."}, status=400)
            tab = str(request.data.get("tab") or "")
            tab = tab if tab in names else names[0]
            rows = client.rows(spreadsheet_id, tab)
        except feeds.NoSheetsAccess as exc:
            return Response({"detail": str(exc), "reconnect": exc.reconnect}, status=409)
        except sheets.SheetUnavailable as exc:
            return _refused(exc)
        shown = [r[:sheets.GRID_COLUMNS] for r in rows[:sheets.GRID_ROWS]]
        return Response({"spreadsheet_id": spreadsheet_id, "title": meta["title"],
                         "tabs": meta["tabs"], "tab": tab, "rows": shown,
                         "more_rows": max(0, len(rows) - sheets.GRID_ROWS),
                         "header_row": sheets.guess_header_row(rows),
                         "account": connection.email_address})


class FeedPreviewView(Base):
    def post(self, request):
        reader, kpi = _kpi(request, request.data)
        if (refusal := _refuse_setup(reader)):
            return refusal
        config = None
        try:
            config = feeds.clean(kpi, request.data)
            client, _ = feeds.client_for(request.tenant.pk, request.user)
            rows = client.rows(config["spreadsheet_id"], config["tab"])
            shown = feeds.preview(kpi, config, rows, _today(request))
        except feeds.NoSheetsAccess as exc:
            return Response({"detail": str(exc), "reconnect": exc.reconnect}, status=409)
        except sheets.FeedRefused as exc:
            text = str(exc)
            if text[:1].islower() and config:
                text = f"The tab '{config['tab']}' {text}."
            return Response({"detail": text}, status=400)
        except sheets.SheetUnavailable as exc:
            return _refused(exc)
        return Response(shown)


class FeedRunView(Base):
    def post(self, request):
        reader, kpi = _kpi(request, request.data)
        if (refusal := _refuse_setup(reader)):
            return refusal
        feed = KpiFeed.objects.filter(kpi=kpi, active=True).first()
        if feed is None:
            return Response({"detail": f"{kpi.name} has no feed."}, status=400)
        return Response({"run": feeds.run(feed, _today(request)),
                         "feed": _feed_payload(feed)})
