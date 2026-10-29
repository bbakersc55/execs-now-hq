"""The Besty feed's routes (M5 part 6).

A company's Besty connection is the practice owner's to enter, on the
company page: a long-lived read-only MCP token, stored encrypted and never
shown again. Setting a KPI's Besty measure is the practice owner's and
associates', as the rest of the scorecard's setup is. Every route finds the
company through `access.company_for`, so another practice's company is 404.

GET    /api/scorecard/besty/connection/?company=     its state (no token)
PUT    /api/scorecard/besty/connection/              {company, token}
DELETE /api/scorecard/besty/connection/?company=
POST   /api/scorecard/besty/connection/test/         {company}: initialize, then tools/list
GET    /api/scorecard/besty/options/?company=        the menu, team members, owners
GET    /api/scorecard/besty/feed/?company=&kpi=
PUT    /api/scorecard/besty/feed/                    {company, kpi, measure, member_id?, member_name?, owner_id?, owner_name?, param?}
DELETE /api/scorecard/besty/feed/?company=&kpi=      stop it; its readings stay
"""

from __future__ import annotations

from django.http import Http404
from django.utils import timezone
from rest_framework.response import Response

from apps.tenancy.models import AuditEvent, Role

from . import besty, feeds
from .models import BestyConnection, Kpi, KpiBestyFeed
from .views import Base, _reader, _refuse_setup, _today, _uuid_or_404

OWNER_ONLY = "Only the practice owner connects a company's Besty account."


def _owner_only(request):
    if request.membership.role != Role.FF:
        return Response({"detail": OWNER_ONLY}, status=403)
    return None


def _connection_payload(connection):
    from config import environment

    if connection is None:
        return {"connected": False, "demo": environment.is_demo()}
    return {"connected": True, "token_last4": connection.token_last4,
            "checked_at": connection.checked_at.isoformat() if connection.checked_at else None,
            "check_ok": connection.check_ok, "check_detail": connection.check_detail,
            "demo": environment.is_demo()}


class BestyConnectionView(Base):
    def get(self, request):
        reader = _reader(request, request.query_params.get("company"))
        if (refusal := _refuse_setup(reader)):
            return refusal
        return Response(_connection_payload(
            BestyConnection.objects.filter(company=reader.company).first()))

    def put(self, request):
        from apps.crm.services import secrets
        from config import environment

        reader = _reader(request, request.data.get("company"))
        if (refusal := _refuse_setup(reader)) or (refusal := _owner_only(request)):
            return refusal
        if environment.is_demo():
            return Response({"detail": feeds.BESTY_DEMO_REFUSAL}, status=409)
        token = str(request.data.get("token") or "").strip()
        if not token:
            return Response({"token": "Paste the Besty MCP token."}, status=400)
        if len(token) < 20 or any(c.isspace() for c in token):
            return Response({"token": "That doesn't look like a Besty MCP token. Copy the "
                                      "whole token Besty gave for this account."}, status=400)
        company = reader.company
        existing = BestyConnection.objects.filter(company=company).first()
        connection = existing or BestyConnection(tenant_id=company.tenant_id, company=company,
                                                 created_by=request.user)
        # On the company's own row (see the model): one company's token can't
        # replace another's.
        connection.token_ciphertext, connection.token_last4 = secrets.encrypt(token), token[-4:]
        # A changed token re-earns its test.
        connection.checked_at, connection.check_ok, connection.check_detail = None, None, ""
        connection.save()
        AuditEvent.objects.create(
            tenant=request.tenant, actor=request.user,
            verb="scorecard.besty_connected" if existing is None else "scorecard.besty_changed",
            target_type="company", target_id=company.pk, payload={})
        return Response(_connection_payload(connection))

    def delete(self, request):
        reader = _reader(request, request.query_params.get("company"))
        if (refusal := _refuse_setup(reader)) or (refusal := _owner_only(request)):
            return refusal
        connection = BestyConnection.objects.filter(company=reader.company).first()
        if connection is not None:
            connection.delete()                     # the token with it
            AuditEvent.objects.create(
                tenant=request.tenant, actor=request.user, verb="scorecard.besty_removed",
                target_type="company", target_id=reader.company.pk, payload={})
        return Response(_connection_payload(None))


class BestyTestView(Base):
    def post(self, request):
        reader = _reader(request, request.data.get("company"))
        if (refusal := _refuse_setup(reader)) or (refusal := _owner_only(request)):
            return refusal
        connection = BestyConnection.objects.filter(company=reader.company).first()
        if connection is None:
            return Response({"detail": "Paste the Besty MCP token first."}, status=400)
        try:
            detail, ok = feeds.besty_client(reader.company).test(), True
        except (besty.BestyUnavailable, besty.BestyRefused) as exc:
            detail, ok = str(exc), False
        connection.checked_at, connection.check_ok, connection.check_detail = \
            timezone.now(), ok, detail
        connection.save(update_fields=["checked_at", "check_ok", "check_detail", "updated_at"])
        return Response(_connection_payload(connection))


class BestyOptionsView(Base):
    def get(self, request):
        reader = _reader(request, request.query_params.get("company"))
        if (refusal := _refuse_setup(reader)):
            return refusal
        out = {"measures": besty.menu(), "members": [], "owners": [],
               "upsell_types": [{"id": k, "name": v} for k, v in besty.UPSELL_TYPES.items()],
               "responders": [{"id": k, "name": v} for k, v in besty.RESPONDERS.items()],
               "error": ""}
        try:
            out.update(besty.options(feeds.besty_client(reader.company)))
        except (besty.BestyUnavailable, besty.BestyRefused) as exc:
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
    return {"measure": feed.measure, "label": besty.MEASURES.get(feed.measure, ("",))[0],
            "member_id": feed.member_id, "member_name": feed.member_name,
            "owner_id": feed.owner_id, "owner_name": feed.owner_name, "param": feed.param,
            "text": feeds.besty_source_text(feed),
            "last_success_at": feed.last_success_at.isoformat() if feed.last_success_at
            else None, "last_error": feed.last_error, **feeds.read_open_payload(feed)}


class BestyFeedView(Base):
    def get(self, request):
        reader, kpi = _kpi(request, request.query_params)
        if (refusal := _refuse_setup(reader)):
            return refusal
        connected = BestyConnection.objects.filter(company=reader.company).exists()
        return Response({"kpi": {"id": str(kpi.pk), "name": kpi.name, "kind": kpi.kind,
                                 "per_person": kpi.per_person,
                                 "read_open_default": feeds.reads_open_by_default(kpi)},
                         "connected": connected,
                         "feed": _feed_payload(KpiBestyFeed.objects.filter(kpi=kpi).first())})

    def put(self, request):
        reader, kpi = _kpi(request, request.data)
        if (refusal := _refuse_setup(reader)):
            return refusal
        measure = str(request.data.get("measure") or "")
        try:
            besty.check_fits(kpi, measure)
            member, owner, param = besty.scope_of(
                measure, member=str(request.data.get("member_id") or "").strip()[:64],
                owner=str(request.data.get("owner_id") or "").strip()[:24],
                param=str(request.data.get("param") or "").strip()[:40])
        except besty.BestyRefused as exc:
            return Response({"measure": str(exc)}, status=400)
        if not BestyConnection.objects.filter(company=reader.company).exists():
            return Response({"detail": f"{reader.company.name} has no Besty connection yet."},
                            status=409)
        # A KPI has one feed: switching to Besty stops the others (readings kept).
        feeds.stop_other_feeds(kpi, Kpi.Feed.BESTY)
        before = KpiBestyFeed.all_objects.filter(kpi=kpi).first()
        read_open = feeds.read_open_choice(request.data, before.read_open if before else None)
        feed, made = KpiBestyFeed.all_objects.update_or_create(
            kpi=kpi, defaults={
                "tenant_id": kpi.tenant_id, "measure": measure, "member_id": member,
                "member_name": str(request.data.get("member_name") or "")[:200]
                if member else "",
                "owner_id": owner,
                "owner_name": str(request.data.get("owner_name") or "")[:200] if owner else "",
                "param": param, "active": True, "last_error": "", "error_since": None,
                "created_by": request.user, "read_open": read_open})
        if made or feed.last_success_at is None:
            KpiBestyFeed.all_objects.filter(pk=feed.pk).update(last_success_at=None)
            feed.last_success_at = None
        AuditEvent.objects.create(
            tenant=request.tenant, actor=request.user, verb="scorecard.feed_set",
            target_type="company", target_id=reader.company.pk,
            payload={"kpi": str(kpi.pk), "name": kpi.name, "source": "besty",
                     "measure": measure})
        Kpi.objects.filter(pk=kpi.pk).update(feed=Kpi.Feed.BESTY)
        feed.refresh_from_db()
        result = feeds.run_besty(feed, _today(request))
        feed.refresh_from_db()
        return Response({"feed": _feed_payload(feed), "run": result})

    def delete(self, request):
        reader, kpi = _kpi(request, request.query_params)
        if (refusal := _refuse_setup(reader)):
            return refusal
        KpiBestyFeed.objects.filter(kpi=kpi).update(active=False, updated_at=timezone.now())
        Kpi.objects.filter(pk=kpi.pk).update(feed=Kpi.Feed.HAND)
        AuditEvent.objects.create(
            tenant=request.tenant, actor=request.user, verb="scorecard.feed_stopped",
            target_type="company", target_id=reader.company.pk,
            payload={"kpi": str(kpi.pk), "name": kpi.name, "source": "besty"})
        return Response({"feed": None})
