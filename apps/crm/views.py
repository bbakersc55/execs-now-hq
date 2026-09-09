"""Module 1 API. Every queryset is scoped twice: by the fail-closed tenant
manager (B1), and by the role rules in `03_access_matrix.md`."""

from __future__ import annotations

from django.db import transaction
from django.http import Http404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.crm import permissions as crm_perms
from apps.crm import serializers as crm_serializers
from apps.crm.models import (
    Company, Contact, ContactType, ImportBatch, OutboxMessage, PipelineStage,
    ServiceCategory, StageAutomation, StageChange, Task,
)
from apps.crm.services import importer, merge, outbox, pipeline, referral, search
from apps.tenancy.models import AuditEvent, Role


class TenantStaffViewSet(viewsets.ModelViewSet):
    permission_classes = [crm_perms.IsTenantStaff]

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


class ContactViewSet(TenantStaffViewSet):
    serializer_class = crm_serializers.ContactSerializer

    def get_queryset(self):
        qs = Contact.objects.filter(deleted_at__isnull=True).prefetch_related(
            "emails", "phones", "type_links__contact_type"
        )
        return crm_perms.contact_queryset_for(self.request, qs)

    def perform_destroy(self, instance):
        """D2 — soft delete. VA may delete (matrix 4.4)."""
        from django.utils import timezone

        instance.deleted_at = timezone.now()
        instance.save(update_fields=["deleted_at", "updated_at"])
        AuditEvent.all_objects.create(
            tenant=instance.tenant, actor=self.request.user, verb="contact.deleted",
            target_type="contact", target_id=instance.pk, payload={},
        )

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        """Matrix 4.4a — soft delete exists so this is safe to delegate.

        Looks through the soft-delete filter (but NOT through tenant scoping:
        `objects` is still the fail-closed manager, so another tenant's deleted
        contact is invisible here).
        """
        contact = crm_perms.contact_queryset_for(
            request, Contact.objects.filter(pk=pk, deleted_at__isnull=False)
        ).first()
        if contact is None:
            raise Http404
        contact.deleted_at = None
        contact.save(update_fields=["deleted_at", "updated_at"])
        return Response(self.get_serializer(contact).data)

    @action(detail=True, methods=["post"], url_path="change-stage")
    def change_stage(self, request, pk=None):
        """FR-1.6a fires here."""
        contact = self.get_object()
        stage = PipelineStage.objects.filter(code=request.data.get("stage")).first()
        if stage is None:
            return Response({"detail": "Unknown stage."}, status=400)
        change = pipeline.change_stage(
            contact, stage, actor=request.user, reason=request.data.get("reason", "")
        )
        contact.refresh_from_db()
        return Response({
            "contact": self.get_serializer(contact).data,
            "changed": change is not None,
        })

    @action(detail=True, methods=["post"], url_path="add-type")
    def add_type(self, request, pk=None):
        """Adding `referral_partner` queues onboarding (FR-1.23a)."""
        contact = self.get_object()
        link = referral.add_type(contact, request.data.get("code"), actor=request.user)
        if link is None:
            return Response({"detail": "Unknown contact type."}, status=400)
        contact.refresh_from_db()
        return Response(self.get_serializer(contact).data)

    @action(detail=False, methods=["post"], permission_classes=[crm_perms.IsFFOrVA])
    def merge(self, request):
        """Matrix 4.5 — FF and VA, audited. CF gets 403."""
        survivor = self.get_queryset().filter(pk=request.data.get("survivor")).first()
        absorbed = self.get_queryset().filter(pk=request.data.get("absorbed")).first()
        if survivor is None or absorbed is None:
            raise Http404
        merge.merge_contacts(
            survivor, absorbed, actor=request.user,
            role=crm_perms.role_of(request),
            field_choices=request.data.get("fields") or {},
        )
        survivor.refresh_from_db()
        return Response(self.get_serializer(survivor).data)

    @action(detail=False, methods=["get"])
    def search(self, request):
        results = search.search(request.tenant, request.query_params.get("q", ""))
        return Response({
            "contacts": crm_serializers.ContactSerializer(
                crm_perms.contact_queryset_for(
                    request, Contact.objects.filter(
                        pk__in=[c.pk for c in results["contacts"]]
                    )
                ), many=True,
            ).data,
            "companies": crm_serializers.CompanySerializer(
                crm_perms.company_queryset_for(
                    request, Company.objects.filter(
                        pk__in=[c.pk for c in results["companies"]]
                    )
                ), many=True,
            ).data,
        })

    @action(detail=False, methods=["get"], url_path="by-category")
    def by_category(self, request):
        """FR-1.25 — vendors searchable by service category."""
        contacts = search.vendors_by_category(request.tenant, request.query_params.get("category", ""))
        qs = crm_perms.contact_queryset_for(
            request, Contact.objects.filter(pk__in=[c.pk for c in contacts])
        )
        return Response(self.get_serializer(qs, many=True).data)


class CompanyViewSet(TenantStaffViewSet):
    serializer_class = crm_serializers.CompanySerializer

    def get_queryset(self):
        qs = Company.objects.filter(deleted_at__isnull=True)
        return crm_perms.company_queryset_for(self.request, qs)

    def perform_destroy(self, instance):
        from django.utils import timezone

        instance.deleted_at = timezone.now()
        instance.save(update_fields=["deleted_at", "updated_at"])

    def get_permissions(self):
        # Matrix 4.12 — seat_count is FF-only.
        if self.action in ("update", "partial_update") and "seat_count" in (
            self.request.data or {}
        ):
            return [crm_perms.IsTenantStaff(), crm_perms.IsFF()]
        return super().get_permissions()


class PipelineStageViewSet(TenantStaffViewSet):
    """Matrix 3.15 — FF only. Stage codes are wired to automations and to the
    client invariant, so renaming or reordering them is a workflow change, not
    CRM hygiene."""

    serializer_class = crm_serializers.PipelineStageSerializer

    def get_queryset(self):
        return PipelineStage.objects.all()

    def get_permissions(self):
        if self.request.method in ("POST", "PUT", "PATCH", "DELETE"):
            return [crm_perms.IsTenantStaff(), crm_perms.IsFF()]
        return [crm_perms.IsTenantStaff()]


class ContactTypeViewSet(TenantStaffViewSet):
    """Matrix 3.14 — VA ✅. CRM hygiene is the VA's job."""

    serializer_class = crm_serializers.ContactTypeSerializer

    def get_queryset(self):
        return ContactType.objects.all()

    def get_permissions(self):
        if self.request.method in ("POST", "PUT", "PATCH", "DELETE"):
            return [crm_perms.IsTenantStaff(), crm_perms.IsFFOrVA()]
        return [crm_perms.IsTenantStaff()]


class ServiceCategoryViewSet(ContactTypeViewSet):
    serializer_class = crm_serializers.ServiceCategorySerializer

    def get_queryset(self):
        return ServiceCategory.objects.all()


class StageAutomationViewSet(TenantStaffViewSet):
    """Matrix 3.12 — FF only."""

    serializer_class = crm_serializers.StageAutomationSerializer
    permission_classes = [crm_perms.IsTenantStaff, crm_perms.IsFF]

    def get_queryset(self):
        return StageAutomation.objects.select_related("from_stage", "to_stage")


class OutboxViewSet(viewsets.ReadOnlyModelViewSet):
    """FR-1.15 — the approval queue AND the complete send log."""

    permission_classes = [crm_perms.IsTenantStaff]
    serializer_class = crm_serializers.OutboxMessageSerializer

    def get_queryset(self):
        return crm_perms.outbox_queryset_for(self.request, OutboxMessage.objects.all())

    @action(detail=True, methods=["post"], permission_classes=[
        crm_perms.IsTenantStaff, crm_perms.CanSend
    ])
    def approve(self, request, pk=None):
        """Matrix 5.3 — the H7 boundary. VA gets 403."""
        message = self.get_object()
        try:
            outbox.approve(message, actor=request.user, role=crm_perms.role_of(request))
        except outbox.SendNotPermitted as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        return Response(self.get_serializer(message).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        """Matrix 5.4 — rejecting sends nothing, so a VA may do it."""
        message = self.get_object()
        outbox.reject(message, actor=request.user)
        return Response(self.get_serializer(message).data)


class ImportViewSet(viewsets.ReadOnlyModelViewSet):
    """FR-1.26-1.32. Matrix 4.13-4.15 — VA may dry-run, commit, and roll back."""

    permission_classes = [crm_perms.IsTenantStaff, crm_perms.IsFFOrVA]
    serializer_class = crm_serializers.ImportBatchSerializer

    def get_queryset(self):
        return ImportBatch.objects.all()

    @action(detail=False, methods=["post"], url_path="dry-run")
    def dry_run(self, request):
        upload = request.FILES.get("file")
        if upload is None:
            return Response({"detail": "No file supplied."}, status=400)
        batch = importer.dry_run(
            tenant=request.tenant, filename=upload.name,
            file_bytes=upload.read(), mapping=request.data.get("mapping") or {},
            actor=request.user,
        )
        return Response({
            "batch": self.get_serializer(batch).data,
            "rows": crm_serializers.ImportRowSerializer(
                batch.rows.all()[:20], many=True
            ).data,
            "errors": crm_serializers.ImportRowSerializer(
                batch.rows.filter(outcome__in=["error", "ambiguous"]), many=True
            ).data,
        })

    @action(detail=True, methods=["post"])
    def commit(self, request, pk=None):
        batch = self.get_object()
        importer.commit(batch, actor=request.user, mapping=request.data.get("mapping") or {})
        return Response(self.get_serializer(batch).data)

    @action(detail=True, methods=["post"])
    def rollback(self, request, pk=None):
        batch = self.get_object()
        report = importer.rollback(batch, actor=request.user)
        return Response({"batch": self.get_serializer(batch).data, "report": report})


class TaskViewSet(TenantStaffViewSet):
    """Phase 1 subset. Module 3 owns this properly."""

    serializer_class = crm_serializers.TaskSerializer

    def get_queryset(self):
        return Task.objects.filter(deleted_at__isnull=True)
