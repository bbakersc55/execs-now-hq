"""The practice's own scorecard ("My practice") and its feed "From this app".

GET    /api/scorecard/practice/                      the practice's scorecard holder {id, name}
GET    /api/scorecard/app-feed/?company=&kpi=        the menu, the Sales stages, the feed
PUT    /api/scorecard/app-feed/                      {company, kpi, measure, param?}
DELETE /api/scorecard/app-feed/?company=&kpi=        stop it; the readings stay

Every practice user reaches the practice's scorecard; a client never does.
The money measures are the practice owner's alone to see and to set.
"""

from __future__ import annotations

from django.http import Http404
from django.utils import timezone
from rest_framework.response import Response

from apps.tenancy.models import CLIENT_ROLES, AuditEvent, Role

from . import feeds, practice
from .models import Kpi, KpiAppFeed
from .views import Base, _reader, _refuse_setup, _today, _uuid_or_404


class PracticeView(Base):
    def get(self, request):
        membership = getattr(request, "membership", None)
        if membership is None or membership.role in CLIENT_ROLES:
            raise Http404
        from . import setup

        company = practice.practice_company(request.tenant)
        # Made with its first page the first time anyone opens it.
        setup.ensure(company, request.user)
        return Response({"id": str(company.pk), "name": company.name})


def _kpi(request, data):
    reader = _reader(request, data.get("company"))
    kpi = Kpi.objects.filter(pk=_uuid_or_404(data.get("kpi")), scorecard__company=reader.company,
                             archived_at__isnull=True).select_related(
        "scorecard", "scorecard__company").first()
    if kpi is None or not reader.company.is_practice:
        raise Http404
    return reader, kpi


def _feed_payload(feed):
    if feed is None or not feed.active:
        return None
    return {"measure": feed.measure, "param": feed.param, "param_label": feed.param_label,
            "text": feeds.app_source_text(feed), "last_error": feed.last_error,
            "last_success_at": feed.last_success_at.isoformat() if feed.last_success_at
            else None}


class AppFeedView(Base):
    def get(self, request):
        from apps.crm.models import PipelineStage
        from apps.crm.services import pipeline

        reader, kpi = _kpi(request, request.query_params)
        if (refusal := _refuse_setup(reader)):
            return refusal
        sales = pipeline.sales_pipeline(request.tenant)
        stages = [{"id": str(s.pk), "label": s.label} for s in
                  PipelineStage.objects.filter(pipeline=sales).order_by("position")] \
            if sales else []
        return Response({
            "kpi": {"id": str(kpi.pk), "name": kpi.name, "kind": kpi.kind,
                    "per_person": kpi.per_person},
            "measures": practice.menu(money=request.membership.role == Role.FF),
            "stages": stages,
            "feed": _feed_payload(KpiAppFeed.objects.filter(kpi=kpi).first())})

    def put(self, request):
        from apps.crm.models import PipelineStage

        reader, kpi = _kpi(request, request.data)
        if (refusal := _refuse_setup(reader)):
            return refusal
        measure = str(request.data.get("measure") or "")
        try:
            practice.check_fits(kpi, measure, role=request.membership.role)
        except practice.MeasureRefused as exc:
            return Response({"measure": str(exc)}, status=400)
        param, label = "", ""
        if practice.MEASURES[measure][3] == "stage":
            stage = PipelineStage.objects.filter(
                pk=request.data.get("param")).first() if request.data.get("param") else None
            if stage is None or stage.pipeline.kind != "sales":
                return Response({"param": "Choose a stage of the Sales pipeline."}, status=400)
            param, label = str(stage.pk), stage.label
        # One feed a KPI: the others stop, their readings kept.
        feeds.stop_other_feeds(kpi, Kpi.Feed.APP)
        feed, made = KpiAppFeed.all_objects.update_or_create(
            kpi=kpi, defaults={"tenant_id": kpi.tenant_id, "measure": measure, "param": param,
                               "param_label": label, "active": True, "last_error": "",
                               "error_since": None, "created_by": request.user})
        KpiAppFeed.all_objects.filter(pk=feed.pk).update(last_success_at=None)
        feed.refresh_from_db()
        AuditEvent.objects.create(
            tenant=request.tenant, actor=request.user, verb="scorecard.feed_set",
            target_type="company", target_id=reader.company.pk,
            payload={"kpi": str(kpi.pk), "name": kpi.name, "source": "app", "measure": measure})
        Kpi.objects.filter(pk=kpi.pk).update(feed=Kpi.Feed.APP)
        result = feeds.run_app(feed, _today(request))
        feed.refresh_from_db()
        return Response({"feed": _feed_payload(feed), "run": result})

    def delete(self, request):
        reader, kpi = _kpi(request, request.query_params)
        if (refusal := _refuse_setup(reader)):
            return refusal
        feed = KpiAppFeed.objects.filter(kpi=kpi).first()
        if feed is not None and practice.is_money(feed.measure) \
                and request.membership.role != Role.FF:
            return Response({"detail": "The money measures are the practice owner's."},
                            status=403)
        KpiAppFeed.objects.filter(kpi=kpi).update(active=False, updated_at=timezone.now())
        Kpi.objects.filter(pk=kpi.pk).update(feed=Kpi.Feed.HAND)
        return Response({"feed": None})
