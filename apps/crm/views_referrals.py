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
        # Inbound only: R3's outbound introductions have their own route.
        return (Referral.objects.filter(prospect__in=visible, referrer__in=visible,
                                        direction=Referral.Direction.INBOUND)
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


class IntroductionViewSet(viewsets.ViewSet):
    """R3, outbound introductions (owner, 2026-10-24). Staff only; an
    associate sees, makes and changes only those between two contacts they
    can see, as with inbound referrals.

    GET   /api/introductions/?contact=<id>      every introduction it is on, and the partner's counts
    POST  /api/introductions/                   {partner, to, note}: record it and draft it to both
    PATCH /api/introductions/<id>/              {outcome}: no_reply, met, client, not_fit, or ""
    """

    permission_classes = [crm_perms.IsTenantStaff]

    def _rows(self, request):
        visible = _visible(request).values("pk")
        return (Referral.objects.filter(direction=Referral.Direction.OUTBOUND,
                                        prospect__in=visible, referrer__in=visible)
                .select_related("referrer__company", "prospect__company", "created_by",
                                "outbox_message"))

    def list(self, request):
        from django.db.models import Q

        from apps.crm.services import introductions

        contact = _contact(request, request.query_params.get("contact"), "contact")
        rows = self._rows(request).filter(Q(referrer=contact) | Q(prospect=contact)) \
            .order_by("-referred_on", "-created_at")
        return Response({"introductions": [introductions.represent(r) for r in rows],
                         "counts": introductions.counts_for(contact),
                         "counts_text": introductions.counts_text(
                             introductions.counts_for(contact))})

    def create(self, request):
        from apps.crm.services import introductions

        partner = _contact(request, request.data.get("partner"), "partner")
        other = _contact(request, request.data.get("to"), "to")
        try:
            row, drafts = introductions.introduce(
                partner, other, actor=request.user, note=request.data.get("note") or "",
                together=request.data.get("together") in (True, "true", "1", 1))
        except introductions.IntroductionRefused as exc:
            raise ValidationError({"to": str(exc)})
        return Response({**introductions.represent(row), "drafts": len(drafts)}, status=201)

    def partial_update(self, request, pk=None):
        from apps.crm.services import introductions

        row = self._rows(request).filter(pk=pk).first() if _is_uuid(pk) else None
        if row is None:
            raise Http404
        try:
            introductions.set_outcome(row, str(request.data.get("outcome") or ""),
                                      actor=request.user)
        except introductions.IntroductionRefused as exc:
            raise ValidationError({"outcome": str(exc)})
        return Response(introductions.represent(row))
