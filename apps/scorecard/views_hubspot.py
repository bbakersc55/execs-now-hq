"""The HubSpot feed's routes (M5 part 5).

A company's HubSpot connection is the practice owner's to enter, on the
company page: a private app's access token, stored encrypted and never shown
again. Setting a KPI's HubSpot measure is the practice owner's and
associates', as the rest of the scorecard's setup is. Every route finds the
company through `access.company_for`, so another practice's company is 404.

GET    /api/scorecard/hubspot/connection/?company=     its state (no token)
PUT    /api/scorecard/hubspot/connection/              {company, token}
DELETE /api/scorecard/hubspot/connection/?company=
POST   /api/scorecard/hubspot/connection/test/         {company}: one read-only call
GET    /api/scorecard/hubspot/options/?company=        the menu, owners, open stages
GET    /api/scorecard/hubspot/feed/?company=&kpi=
PUT    /api/scorecard/hubspot/feed/                    {company, kpi, measure, owner_id?, owner_name?, stage_id?, stage_name?}
DELETE /api/scorecard/hubspot/feed/?company=&kpi=      stop it; its readings stay
"""

from __future__ import annotations

from django.http import Http404
from django.utils import timezone
from rest_framework.response import Response

from apps.tenancy.models import AuditEvent, Role

from . import feeds, hubspot
from .models import HubSpotConnection, Kpi, KpiHubSpotFeed
from .views import Base, _reader, _refuse_setup, _today, _uuid_or_404

OWNER_ONLY = "Only the practice owner connects a company's HubSpot account."


def _owner_only(request):
    if request.membership.role != Role.FF:
        return Response({"detail": OWNER_ONLY}, status=403)
    return None


def _connection_payload(connection):
    from config import environment

    if connection is None:
        return {"connected": False, "demo": environment.is_demo(),
                "scopes": list(hubspot.SCOPES)}
    return {"connected": True, "token_last4": connection.token_last4,
            "checked_at": connection.checked_at.isoformat() if connection.checked_at else None,
            "check_ok": connection.check_ok, "check_detail": connection.check_detail,
            "demo": environment.is_demo(), "scopes": list(hubspot.SCOPES)}


class HubSpotConnectionView(Base):
    def get(self, request):
        reader = _reader(request, request.query_params.get("company"))
        if (refusal := _refuse_setup(reader)):
            return refusal
        return Response(_connection_payload(
            HubSpotConnection.objects.filter(company=reader.company).first()))

    def put(self, request):
        from apps.crm.services import secrets
        from config import environment

        reader = _reader(request, request.data.get("company"))
        if (refusal := _refuse_setup(reader)) or (refusal := _owner_only(request)):
            return refusal
        if environment.is_demo():
            return Response({"detail": feeds.HUBSPOT_DEMO_REFUSAL}, status=409)
        token = str(request.data.get("token") or "").strip()
        if not token:
            return Response({"token": "Paste the private app's access token."}, status=400)
        if len(token) < 20 or any(c.isspace() for c in token):
            return Response({"token": "That doesn't look like a HubSpot access token. Copy it "
                                      "from the private app's Auth tab."}, status=400)
        company = reader.company
        existing = HubSpotConnection.objects.filter(company=company).first()
        connection = existing or HubSpotConnection(tenant_id=company.tenant_id, company=company,
                                                   created_by=request.user)
        # On the company's own row (see the model): one company's token can't
        # replace another's.
        connection.token_ciphertext, connection.token_last4 = secrets.encrypt(token), token[-4:]
        # A changed token re-earns its test.
        connection.checked_at, connection.check_ok, connection.check_detail = None, None, ""
        connection.save()
        AuditEvent.objects.create(
            tenant=request.tenant, actor=request.user,
            verb="scorecard.hubspot_connected" if existing is None
            else "scorecard.hubspot_changed",
            target_type="company", target_id=company.pk, payload={})
        return Response(_connection_payload(connection))

    def delete(self, request):
        reader = _reader(request, request.query_params.get("company"))
        if (refusal := _refuse_setup(reader)) or (refusal := _owner_only(request)):
            return refusal
        connection = HubSpotConnection.objects.filter(company=reader.company).first()
        if connection is not None:
            connection.delete()                     # the token with it
            AuditEvent.objects.create(
                tenant=request.tenant, actor=request.user, verb="scorecard.hubspot_removed",
                target_type="company", target_id=reader.company.pk, payload={})
        return Response(_connection_payload(None))


class HubSpotTestView(Base):
    def post(self, request):
        reader = _reader(request, request.data.get("company"))
        if (refusal := _refuse_setup(reader)) or (refusal := _owner_only(request)):
            return refusal
        connection = HubSpotConnection.objects.filter(company=reader.company).first()
        if connection is None:
            return Response({"detail": "Paste the HubSpot access token first."}, status=400)
        try:
            detail, ok = feeds.hubspot_client(reader.company).test(), True
        except (hubspot.HubSpotUnavailable, hubspot.HubSpotRefused) as exc:
            detail, ok = str(exc), False
        connection.checked_at, connection.check_ok, connection.check_detail = \
            timezone.now(), ok, detail
        connection.save(update_fields=["checked_at", "check_ok", "check_detail", "updated_at"])
        return Response(_connection_payload(connection))


class HubSpotOptionsView(Base):
    def get(self, request):
        reader = _reader(request, request.query_params.get("company"))
        if (refusal := _refuse_setup(reader)):
            return refusal
        out = {"measures": hubspot.menu(), "owners": [], "stages": [], "error": ""}
        try:
            out.update(hubspot.options(feeds.hubspot_client(reader.company)))
        except (hubspot.HubSpotUnavailable, hubspot.HubSpotRefused) as exc:
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
    return {"measure": feed.measure, "label": hubspot.MEASURES.get(feed.measure, ("",))[0],
            "owner_id": feed.owner_id, "owner_name": feed.owner_name,
            "stage_id": feed.stage_id, "stage_name": feed.stage_name,
            "text": feeds.hubspot_source_text(feed),
            "last_success_at": feed.last_success_at.isoformat() if feed.last_success_at
            else None, "last_error": feed.last_error, **feeds.read_open_payload(feed)}


class HubSpotFeedView(Base):
    def get(self, request):
        reader, kpi = _kpi(request, request.query_params)
        if (refusal := _refuse_setup(reader)):
            return refusal
        connected = HubSpotConnection.objects.filter(company=reader.company).exists()
        return Response({"kpi": {"id": str(kpi.pk), "name": kpi.name, "kind": kpi.kind,
                                 "per_person": kpi.per_person,
                                 "read_open_default": feeds.reads_open_by_default(kpi)},
                         "connected": connected,
                         "feed": _feed_payload(
                             KpiHubSpotFeed.objects.filter(kpi=kpi).first())})

    def put(self, request):
        reader, kpi = _kpi(request, request.data)
        if (refusal := _refuse_setup(reader)):
            return refusal
        measure = str(request.data.get("measure") or "")
        try:
            hubspot.check_fits(kpi, measure)
        except hubspot.HubSpotRefused as exc:
            return Response({"measure": str(exc)}, status=400)
        owner = str(request.data.get("owner_id") or "").strip()[:24]
        stage = str(request.data.get("stage_id") or "").strip()[:64] \
            if measure == "pipeline_value" else ""
        if not HubSpotConnection.objects.filter(company=reader.company).exists():
            return Response({"detail": f"{reader.company.name} has no HubSpot connection yet."},
                            status=409)
        # A KPI has one feed: switching to HubSpot stops the others (readings kept).
        feeds.stop_other_feeds(kpi, Kpi.Feed.HUBSPOT)
        before = KpiHubSpotFeed.all_objects.filter(kpi=kpi).first()
        read_open = feeds.read_open_choice(request.data, before.read_open if before else None)
        feed, made = KpiHubSpotFeed.all_objects.update_or_create(
            kpi=kpi, defaults={
                "tenant_id": kpi.tenant_id, "measure": measure, "owner_id": owner,
                "owner_name": str(request.data.get("owner_name") or "")[:200] if owner else "",
                "stage_id": stage,
                "stage_name": str(request.data.get("stage_name") or "")[:200] if stage else "",
                "active": True, "last_error": "", "error_since": None,
                "created_by": request.user, "read_open": read_open})
        if made or feed.last_success_at is None:
            KpiHubSpotFeed.all_objects.filter(pk=feed.pk).update(last_success_at=None)
            feed.last_success_at = None
        AuditEvent.objects.create(
            tenant=request.tenant, actor=request.user, verb="scorecard.feed_set",
            target_type="company", target_id=reader.company.pk,
            payload={"kpi": str(kpi.pk), "name": kpi.name, "source": "hubspot",
                     "measure": measure})
        Kpi.objects.filter(pk=kpi.pk).update(feed=Kpi.Feed.HUBSPOT)
        feed.refresh_from_db()
        result = feeds.run_hubspot(feed, _today(request))
        feed.refresh_from_db()
        return Response({"feed": _feed_payload(feed), "run": result})

    def delete(self, request):
        reader, kpi = _kpi(request, request.query_params)
        if (refusal := _refuse_setup(reader)):
            return refusal
        KpiHubSpotFeed.objects.filter(kpi=kpi).update(active=False, updated_at=timezone.now())
        Kpi.objects.filter(pk=kpi.pk).update(feed=Kpi.Feed.HAND)
        AuditEvent.objects.create(
            tenant=request.tenant, actor=request.user, verb="scorecard.feed_stopped",
            target_type="company", target_id=reader.company.pk,
            payload={"kpi": str(kpi.pk), "name": kpi.name, "source": "hubspot"})
        return Response({"feed": None})
