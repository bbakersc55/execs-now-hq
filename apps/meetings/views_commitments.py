"""The "Waiting on others" API (owner, 2026-09-28). Staff only."""

from __future__ import annotations

from datetime import date

from django.db.models import Q
from django.http import Http404
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.crm import permissions as crm_perms
from apps.meetings import commitments
from apps.meetings.models import Commitment


class CommitmentViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated, crm_perms.IsTenantStaff]

    def _qs(self, request):
        qs = commitments.scoped(request, Commitment.objects.select_related(
            "company", "meeting", "task"))
        commitments.settle_portal(qs)
        return qs

    def list(self, request):
        """`?state=open|done|all` (open), `?overdue=1`, `?contact=`, `?company=`,
        `?q=` (person, company or what). Soonest to chase first."""
        qs = self._qs(request)
        state = request.query_params.get("state", "open")
        if state != "all":
            qs = qs.filter(state=state)
        if request.query_params.get("overdue"):
            qs = qs.filter(commitments.overdue_filter())
        for field in ("contact", "company"):
            if request.query_params.get(field):
                qs = qs.filter(**{f"{field}_id": request.query_params[field]})
        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(owner_name__icontains=q) | Q(text__icontains=q)
                           | Q(company__name__icontains=q))
        return Response([commitments.represent(row) for row in qs[:500]])

    def _load(self, request, pk):
        row = self._qs(request).filter(pk=pk).first()
        if row is None:
            raise Http404
        return row

    @action(detail=True, methods=["post"])
    def done(self, request, pk=None):
        row = self._load(request, pk)
        commitments.mark_done(row, actor=request.user, role=crm_perms.role_of(request))
        return Response(commitments.represent(row))

    @action(detail=True, methods=["post"])
    def snooze(self, request, pk=None):
        """`{"days": 7}` or `{"until": "YYYY-MM-DD"}`."""
        row = self._load(request, pk)
        until = request.data.get("until")
        try:
            until = date.fromisoformat(str(until)[:10]) if until else None
            days = int(request.data.get("days") or 7)
        except ValueError:
            return Response({"detail": "Snooze by a number of days, or to a date."},
                            status=400)
        commitments.snooze(row, actor=request.user, role=crm_perms.role_of(request),
                           days=days, until=until)
        return Response(commitments.represent(row))
