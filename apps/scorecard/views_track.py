"""The Track PMS feed's routes (M5 part 4).

A company's Track connection is the practice owner's to enter, on the
company page: the address, and the key and secret, which are stored
encrypted and never shown again (the practice never sees the client's
credentials). Setting a KPI's Track measure is the practice owner's and
associates', as the rest of the scorecard's setup is. Every route finds the
company through `access.company_for`, so another practice's company is 404.

GET    /api/scorecard/track/connection/?company=       its state (no secrets)
PUT    /api/scorecard/track/connection/                {company, domain, key, secret}
DELETE /api/scorecard/track/connection/?company=
POST   /api/scorecard/track/connection/test/           {company}: one read-only call
GET    /api/scorecard/track/options/?company=          the menu, properties, assignees
GET    /api/scorecard/track/feed/?company=&kpi=
PUT    /api/scorecard/track/feed/                      {company, kpi, measure, unit_id?, unit_name?, assignee_id?}
DELETE /api/scorecard/track/feed/?company=&kpi=        stop it; its readings stay
"""

from __future__ import annotations

from django.http import Http404
from django.utils import timezone
from rest_framework.response import Response

from apps.tenancy.models import AuditEvent, Role

from . import feeds, track
from .models import Kpi, KpiTrackFeed, TrackConnection
from .views import Base, _reader, _refuse_setup, _today, _uuid_or_404

OWNER_ONLY = "Only the practice owner connects a company's Track account."


def _owner_only(request):
    if request.membership.role != Role.FF:
        return Response({"detail": OWNER_ONLY}, status=403)
    return None


def _connection_payload(connection):
    from config import environment

    if connection is None:
        return {"connected": False, "demo": environment.is_demo()}
    return {"connected": True, "domain": connection.domain,
            "key_last4": connection.key_last4,
            "checked_at": connection.checked_at.isoformat() if connection.checked_at else None,
            "check_ok": connection.check_ok, "check_detail": connection.check_detail,
            "demo": environment.is_demo()}


class TrackConnectionView(Base):
    def get(self, request):
        reader = _reader(request, request.query_params.get("company"))
        if (refusal := _refuse_setup(reader)):
            return refusal
        return Response(_connection_payload(
            TrackConnection.objects.filter(company=reader.company).first()))

    def put(self, request):
        from apps.crm.services import secrets
        from config import environment

        reader = _reader(request, request.data.get("company"))
        if (refusal := _refuse_setup(reader)) or (refusal := _owner_only(request)):
            return refusal
        if environment.is_demo():
            return Response({"detail": feeds.TRACK_DEMO_REFUSAL}, status=409)
        try:
            domain = track.base_url(str(request.data.get("domain") or ""))
        except track.TrackRefused as exc:
            return Response({"domain": str(exc)}, status=400)
        key = str(request.data.get("key") or "").strip()
        secret = str(request.data.get("secret") or "").strip()
        company = reader.company
        existing = TrackConnection.objects.filter(company=company).first()
        if existing is None and (not key or not secret):
            return Response({"detail": "Enter the API key and the secret."}, status=400)
        connection = existing or TrackConnection(tenant_id=company.tenant_id, company=company,
                                                 created_by=request.user)
        connection.domain = domain.removesuffix("/api").removeprefix("https://")
        # On the company's own row (see the model): one company's key can't
        # replace another's.
        if key:
            connection.key_ciphertext, connection.key_last4 = secrets.encrypt(key), key[-4:]
        if secret:
            connection.secret_ciphertext = secrets.encrypt(secret)
        # A changed key or address re-earns its test.
        connection.checked_at, connection.check_ok, connection.check_detail = None, None, ""
        connection.save()
        AuditEvent.objects.create(
            tenant=request.tenant, actor=request.user,
            verb="scorecard.track_connected" if existing is None else "scorecard.track_changed",
            target_type="company", target_id=company.pk,
            payload={"domain": connection.domain, "key_changed": bool(key)})
        return Response(_connection_payload(connection))

    def delete(self, request):
        reader = _reader(request, request.query_params.get("company"))
        if (refusal := _refuse_setup(reader)) or (refusal := _owner_only(request)):
            return refusal
        connection = TrackConnection.objects.filter(company=reader.company).first()
        if connection is not None:
            connection.delete()                     # the key and secret with it
            AuditEvent.objects.create(
                tenant=request.tenant, actor=request.user, verb="scorecard.track_removed",
                target_type="company", target_id=reader.company.pk, payload={})
        return Response(_connection_payload(None))


class TrackTestView(Base):
    def post(self, request):
        reader = _reader(request, request.data.get("company"))
        if (refusal := _refuse_setup(reader)) or (refusal := _owner_only(request)):
            return refusal
        connection = TrackConnection.objects.filter(company=reader.company).first()
        if connection is None:
            return Response({"detail": "Enter the Track address, key and secret first."},
                            status=400)
        try:
            detail, ok = feeds.track_client(reader.company).test(), True
        except (track.TrackUnavailable, track.TrackRefused) as exc:
            detail, ok = str(exc), False
        connection.checked_at, connection.check_ok, connection.check_detail = \
            timezone.now(), ok, detail
        connection.save(update_fields=["checked_at", "check_ok", "check_detail", "updated_at"])
        return Response(_connection_payload(connection))


class TrackOptionsView(Base):
    def get(self, request):
        reader = _reader(request, request.query_params.get("company"))
        if (refusal := _refuse_setup(reader)):
            return refusal
        out = {"measures": track.menu(), "units": [], "assignees": [], "error": ""}
        try:
            out.update(track.options(feeds.track_client(reader.company)))
        except (track.TrackUnavailable, track.TrackRefused) as exc:
            out["error"] = str(exc)
        return Response(out)


def _kpi(request, data):
    reader = _reader(request, data.get("company"))
    kpi = Kpi.objects.filter(pk=_uuid_or_404(data.get("kpi")), scorecard__company=reader.company,
                             archived_at__isnull=True).select_related(
        "scorecard", "scorecard__company").first()
    if kpi is None:
        raise Http404
    return reader, kpi


def _feed_payload(feed):
    if feed is None or not feed.active:
        return None
    return {"measure": feed.measure, "label": track.MEASURES.get(feed.measure, ("",))[0],
            "unit_id": feed.unit_id, "unit_name": feed.unit_name,
            "assignee_id": feed.assignee_id, "text": feeds.track_source_text(feed),
            "last_success_at": feed.last_success_at.isoformat() if feed.last_success_at
            else None, "last_error": feed.last_error, **feeds.read_open_payload(feed)}


class TrackFeedView(Base):
    def get(self, request):
        reader, kpi = _kpi(request, request.query_params)
        if (refusal := _refuse_setup(reader)):
            return refusal
        connected = TrackConnection.objects.filter(company=reader.company).exists()
        return Response({"kpi": {"id": str(kpi.pk), "name": kpi.name, "kind": kpi.kind,
                                 "per_person": kpi.per_person,
                                 "read_open_default": feeds.reads_open_by_default(kpi)},
                         "connected": connected,
                         "feed": _feed_payload(KpiTrackFeed.objects.filter(kpi=kpi).first())})

    def put(self, request):
        reader, kpi = _kpi(request, request.data)
        if (refusal := _refuse_setup(reader)):
            return refusal
        measure = str(request.data.get("measure") or "")
        try:
            track.check_fits(kpi, measure)
        except track.TrackRefused as exc:
            return Response({"measure": str(exc)}, status=400)
        unit = str(request.data.get("unit_id") or "").strip()[:20]
        user = str(request.data.get("assignee_id") or "").strip()[:20]
        scope = track.MEASURES[measure][3]
        if scope == "property":
            user = ""
        else:
            unit = ""
        if not TrackConnection.objects.filter(company=reader.company).exists():
            return Response({"detail": f"{reader.company.name} has no Track connection yet."},
                            status=409)
        # A KPI has one feed: switching to Track stops the others (readings kept).
        feeds.stop_other_feeds(kpi, Kpi.Feed.TRACK)
        before = KpiTrackFeed.all_objects.filter(kpi=kpi).first()
        read_open = feeds.read_open_choice(request.data, before.read_open if before else None)
        feed, made = KpiTrackFeed.all_objects.update_or_create(
            kpi=kpi, defaults={"tenant_id": kpi.tenant_id, "measure": measure, "unit_id": unit,
                               "unit_name": str(request.data.get("unit_name") or "")[:200]
                               if unit else "", "assignee_id": user, "active": True,
                               "last_error": "", "error_since": None,
                               "created_by": request.user, "read_open": read_open})
        if made or feed.last_success_at is None:
            KpiTrackFeed.all_objects.filter(pk=feed.pk).update(last_success_at=None)
            feed.last_success_at = None
        AuditEvent.objects.create(
            tenant=request.tenant, actor=request.user, verb="scorecard.feed_set",
            target_type="company", target_id=reader.company.pk,
            payload={"kpi": str(kpi.pk), "name": kpi.name, "source": "track",
                     "measure": measure})
        Kpi.objects.filter(pk=kpi.pk).update(feed=Kpi.Feed.TRACK)
        feed.refresh_from_db()
        result = feeds.run_track(feed, _today(request))
        feed.refresh_from_db()
        return Response({"feed": _feed_payload(feed), "run": result})

    def delete(self, request):
        reader, kpi = _kpi(request, request.query_params)
        if (refusal := _refuse_setup(reader)):
            return refusal
        KpiTrackFeed.objects.filter(kpi=kpi).update(active=False, updated_at=timezone.now())
        Kpi.objects.filter(pk=kpi.pk).update(feed=Kpi.Feed.HAND)
        AuditEvent.objects.create(
            tenant=request.tenant, actor=request.user, verb="scorecard.feed_stopped",
            target_type="company", target_id=reader.company.pk,
            payload={"kpi": str(kpi.pk), "name": kpi.name, "source": "track"})
        return Response({"feed": None})
