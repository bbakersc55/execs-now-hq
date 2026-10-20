"""Inbound referrals (owner, 2026-10-20): who sent the practice a prospect.

Staff only, like the rest of the CRM. A row is shown, made or changed only
when the person asking can see both the prospect and the referrer: an
associate's contacts are their assigned companies and their own (FR-1.9c),
and a referral must not show them anyone else.
"""

from __future__ import annotations

from django.http import Http404
from rest_framework import viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.crm import permissions as crm_perms
from apps.crm.models import Contact, Referral
from apps.crm.services import referrals
from apps.crm.views import _is_uuid


def _visible(request):
    return crm_perms.contact_queryset_for(
        request, Contact.objects.filter(deleted_at__isnull=True))


def _contact(request, value, field):
    if not value:
        raise ValidationError({field: "Choose a contact."})
    contact = _visible(request).filter(pk=value).first() if _is_uuid(value) else None
    if contact is None:
        raise ValidationError({field: "That contact is not available."})
    return contact


class ReferralViewSet(viewsets.ViewSet):
    permission_classes = [crm_perms.IsTenantStaff]

    def _rows(self, request):
        visible = _visible(request).values("pk")
        return (Referral.objects.filter(prospect__in=visible, referrer__in=visible)
                .select_related("referrer", "prospect__company", "pipeline"))

    def _get(self, request, pk):
        row = self._rows(request).filter(pk=pk).first() if _is_uuid(pk) else None
        if row is None:
            raise Http404
        return row

    def list(self, request):
        rows = self._rows(request)
        for param in ("referrer", "prospect"):
            value = request.query_params.get(param)
            if value:
                rows = (rows.filter(**{f"{param}_id": value}) if _is_uuid(value)
                        else rows.none())
        return Response([referrals.represent(row) for row in rows])

    def create(self, request):
        prospect = _contact(request, request.data.get("prospect"), "prospect")
        referrer = _contact(request, request.data.get("referrer"), "referrer")
        try:
            row = referrals.record(prospect, referrer, actor=request.user,
                                   note=(request.data.get("note") or "").strip())
        except referrals.ReferralRefused as exc:
            raise ValidationError({"referrer": str(exc)})
        return Response(referrals.represent(row), status=201)

    def partial_update(self, request, pk=None):
        row = self._get(request, pk)
        try:
            if "referrer" in request.data:
                referrals.change_referrer(
                    row, _contact(request, request.data.get("referrer"), "referrer"),
                    actor=request.user)
        except referrals.ReferralRefused as exc:
            raise ValidationError({"referrer": str(exc)})
        if "note" in request.data:
            row.note = (request.data.get("note") or "").strip()
            row.save(update_fields=["note", "updated_at"])
        return Response(referrals.represent(self._get(request, pk)))

    def destroy(self, request, pk=None):
        referrals.remove(self._get(request, pk), actor=request.user)
        return Response(status=204)
