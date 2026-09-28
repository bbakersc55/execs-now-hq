"""The Campaigns screen's API (owner, 2026-09-28).

Composing and queueing are open to the practice's staff, like drafting any
email: nothing here sends. What leaves is decided in the sending queue, where
only the FF or a CF may approve. The recipients a CF can choose are the
contacts they can see.
"""

from __future__ import annotations

from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.crm import permissions as crm_perms
from apps.crm.models import Campaign, CampaignRecipient, Contact
from apps.crm.services import campaigns, email_layout
from apps.tenancy.models import AuditEvent


class CampaignSerializer(serializers.ModelSerializer):
    stats = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Campaign
        fields = ["id", "name", "subject", "sender", "body_mode", "body_html",
                  "send_as_is", "created_at", "updated_at", "created_by_name", "stats"]
        read_only_fields = ["created_at", "updated_at"]

    def get_stats(self, obj):
        return campaigns.stats(obj)

    def get_created_by_name(self, obj):
        return (obj.created_by.full_name or obj.created_by.email) if obj.created_by_id else ""


class CampaignViewSet(viewsets.ModelViewSet):
    permission_classes = [crm_perms.IsTenantStaff]
    serializer_class = CampaignSerializer

    def get_queryset(self):
        return Campaign.objects.filter(archived_at__isnull=True).select_related("created_by")

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant, created_by=self.request.user)

    def perform_destroy(self, instance):
        """Archived, not deleted: its rows in the Outbox point back to it."""
        instance.archived_at = timezone.now()
        instance.save(update_fields=["archived_at", "updated_at"])
        AuditEvent.all_objects.create(
            tenant=instance.tenant, actor=self.request.user, verb="campaign.archived",
            target_type="campaign", target_id=instance.pk, payload={})

    def _contacts(self):
        return crm_perms.contact_queryset_for(self.request, Contact.objects.all())

    def _contact(self, ref):
        if not ref:
            return None
        return self._contacts().filter(pk=ref, deleted_at__isnull=True).first()

    @action(detail=True, methods=["post"])
    def preview(self, request, pk=None):
        """Exactly as it will land — merged for `contact`, in the layout, with
        the unsubscribe link — including edits not yet saved, so the preview
        beside the editor follows what is being typed."""
        campaign = self.get_object()
        for field in ("subject", "body_html", "body_mode", "send_as_is", "sender"):
            if field in request.data:
                setattr(campaign, field, request.data[field])
        contact = self._contact(request.data.get("contact"))
        html, text = campaigns.preview(campaign, contact, actor=request.user,
                                       to_address="" if contact else request.user.email)
        html, _ = email_layout.with_logo(html, campaign.tenant, as_data_uri=True)
        subject = campaigns.merge(campaign.subject, campaigns.merge_values(
            contact, campaigns.sender_name(campaign, request.user)), as_html=False)
        return Response({"subject": subject, "html": html, "text": text})

    @action(detail=True, methods=["get"])
    def candidates(self, request, pk=None):
        """Who the filters find, each marked sendable or with why not."""
        campaign = self.get_object()
        found = campaigns.candidates(
            self._contacts().select_related("company").prefetch_related("emails"),
            contact_type=request.query_params.get("type", ""),
            stage=request.query_params.get("stage", ""),
            tag=request.query_params.get("tag", ""),
            enrolled=request.query_params.get("enrolled", ""),
        ).order_by("last_name", "first_name")[:1000]
        return Response([{
            "id": str(c.pk), "name": f"{c.first_name} {c.last_name}".strip(),
            "email": c.primary_email or "",
            "company": c.company.name if c.company_id else "",
            "unsendable": campaigns.unsendable(c, campaign),
        } for c in found])

    @action(detail=True, methods=["post"])
    def queue(self, request, pk=None):
        """"Enrol and queue": one pending Outbox row per chosen person."""
        campaign = self.get_object()
        ids = request.data.get("ids") or []
        if not isinstance(ids, list) or not ids:
            return Response({"detail": "Choose at least one recipient."}, status=400)
        chosen = self._contacts().filter(pk__in=ids, deleted_at__isnull=True)
        try:
            result = campaigns.queue(campaign, chosen, actor=request.user)
        except campaigns.CampaignRefused as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        return Response({**result, "campaign": self.get_serializer(campaign).data},
                        status=201 if result["queued"] else 400)

    @action(detail=True, methods=["post"], url_path="test-send")
    def test_send(self, request, pk=None):
        """To the person composing it, now, subject marked [Test]."""
        campaign = self.get_object()
        try:
            message = campaigns.test_send(campaign, actor=request.user,
                                          contact=self._contact(request.data.get("contact")))
        except campaigns.CampaignRefused as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        return Response({"to": message.to_address, "state": message.state},
                        status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def recipients(self, request, pk=None):
        campaign = self.get_object()
        rows = CampaignRecipient.objects.filter(campaign=campaign).select_related(
            "contact", "outbox_message")
        return Response([{
            "id": str(r.pk), "contact": str(r.contact_id),
            "name": f"{r.contact.first_name} {r.contact.last_name}".strip(),
            "state": r.outbox_message.state if r.outbox_message_id else "",
            "ended_reason": r.ended_reason,
        } for r in rows])
