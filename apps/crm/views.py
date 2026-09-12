"""Module 1 API. Every queryset is scoped twice: by the fail-closed tenant
manager (B1), and by the role rules in `03_access_matrix.md`."""

from __future__ import annotations

from django.conf import settings as dj_settings
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from rest_framework import status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.crm import permissions as crm_perms
from apps.crm import serializers as crm_serializers
from apps.crm.models import (
    Company, Contact, ContactType, ImportBatch, ImportMappingProfile,
    DevSendAllowlistEntry, EmailTemplate, OutboxMessage, Pipeline, PipelineStage,
    ServiceCategory, StageAutomation, StageChange, StageSemantic, Task,
)
from apps.crm.services import importer, merge, outbox, pipeline, referral, search, timeline
from apps.notes.serializers import represent_many as note_representations
from apps.notes.views import search_notes
from apps.tenancy import storage
from apps.tenancy.models import AuditEvent, Role

#: FR-1.23b — per-file cap on a draft attachment.
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024


def _is_uuid(value):
    import uuid as _uuid

    try:
        _uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def _json_field(request, name):
    """A multipart upload carries JSON fields as strings; a JSON body does not."""
    import json

    raw = request.data.get(name)
    if isinstance(raw, str):
        try:
            return json.loads(raw or "{}")
        except ValueError:
            return {}
    return raw or {}


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

    @action(detail=True, methods=["get"])
    def timeline(self, request, pk=None):
        """FR-1.5 — stage changes, notes, emails, and tasks in one view."""
        return Response(timeline.for_contact(self.get_object()))

    @action(detail=True, methods=["post"], url_path="change-stage")
    def change_stage(self, request, pk=None):
        """FR-1.6a fires here, for a move within ONE pipeline.

        `stage` is a stage id, or a code plus `pipeline` — codes are only unique
        within a pipeline now, so a bare code is ambiguous by itself.
        """
        contact = self.get_object()
        reference = request.data.get("stage") or ""
        stages = PipelineStage.objects.select_related("pipeline")
        pipeline_ref = request.data.get("pipeline") or ""
        if pipeline_ref:
            stages = stages.filter(
                Q(pipeline_id=pipeline_ref) | Q(pipeline__name__iexact=pipeline_ref)
            )
        stage = stages.filter(Q(pk=reference) if _is_uuid(reference)
                              else Q(code=reference)).first()
        if stage is None:
            return Response(
                {"detail": "Unknown stage. Give a stage id, or a code with its pipeline."},
                status=400,
            )
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

    @action(detail=True, methods=["post"], url_path="draft-touch")
    def draft_touch(self, request, pk=None):
        """FR-1.21/1.22 — draft this partner's touch now, into the Outbox.

        Drafting is not sending, so this is open to every tenant user: a VA may
        prepare the touch and the FF or CF approves it (matrix 5.3/5.6).
        """
        contact = self.get_object()
        if not contact.type_links.filter(
            contact_type__code="referral_partner"
        ).exists():
            return Response(
                {"detail": "That contact is not a referral partner."}, status=400,
            )
        if not contact.primary_email:
            return Response(
                {"detail": f"{contact.first_name} has no email address to send to."},
                status=400,
            )
        message = referral.draft_touch_now(contact, actor=request.user)
        return Response(
            crm_serializers.OutboxMessageSerializer(
                message, context={"request": request}
            ).data,
            status=201,
        )

    @action(detail=False, methods=["post"], url_path="draft-touches")
    def draft_touches(self, request):
        """FR-1.21 — draft a touch for each selected partner.

        Each recipient gets its OWN Outbox row. One row addressed to forty
        people would be a mailing list, and the approval step would stop being a
        per-recipient decision.
        """
        return self._bulk_draft(request, kind="touch")

    @action(detail=False, methods=["post"], url_path="draft-emails")
    def draft_emails(self, request):
        """A one-off email to each selected contact, from a template or blank.

        Still `pending_approval`: approval stays mandatory for anything reaching
        a contact's inbox, however it was composed (assumption F3).
        """
        return self._bulk_draft(request, kind="email")

    def _bulk_draft(self, request, *, kind):
        ids = request.data.get("ids") or []
        if not isinstance(ids, list) or not ids:
            return Response({"detail": "Select at least one contact."}, status=400)

        contacts = crm_perms.contact_queryset_for(
            request, Contact.objects.filter(pk__in=ids, deleted_at__isnull=True)
        )
        template = None
        if kind == "email":
            template_id = request.data.get("template")
            if template_id:
                template = EmailTemplate.objects.filter(pk=template_id).first()

        drafted, skipped = [], []
        for contact in contacts:
            if not contact.primary_email:
                skipped.append({"contact": str(contact.pk),
                                "name": f"{contact.first_name} {contact.last_name}",
                                "detail": "no email address"})
                continue
            if kind == "touch":
                if not contact.type_links.filter(
                    contact_type__code="referral_partner"
                ).exists():
                    skipped.append({"contact": str(contact.pk),
                                    "name": f"{contact.first_name} {contact.last_name}",
                                    "detail": "not a referral partner"})
                    continue
                message = referral.draft_touch_now(contact, actor=request.user)
            else:
                message = outbox.create_manual_draft(
                    contact,
                    subject=(request.data.get("subject") or "").strip()
                    or (template.subject if template else ""),
                    body_text=(request.data.get("body_text") or "").strip()
                    or (template.body if template else ""),
                    actor=request.user,
                )
            drafted.append(str(message.pk))

        return Response({
            "drafted": drafted, "drafted_count": len(drafted),
            "skipped": skipped,
        }, status=201 if drafted else 400)

    @action(detail=True, methods=["get"])
    def duplicates(self, request, pk=None):
        """Likely duplicates of this contact, using the same rules as import
        matching (FR-1.29): shared email, then same name at the same company,
        then same name anywhere. Ranked, with the reason shown — the reviewer
        chooses; the app never merges on its own."""
        contact = self.get_object()
        qs = self.get_queryset().exclude(pk=contact.pk)

        seen, ranked = set(), []

        addresses = [e.address.lower() for e in contact.emails.all()]
        if addresses:
            for other in qs.filter(emails__address__in=addresses).distinct():
                if other.pk not in seen:
                    seen.add(other.pk)
                    ranked.append((other, "shares an email address", 1))

        same_name = qs.filter(
            first_name__iexact=contact.first_name, last_name__iexact=contact.last_name
        )
        if contact.company_id:
            for other in same_name.filter(company_id=contact.company_id):
                if other.pk not in seen:
                    seen.add(other.pk)
                    ranked.append((other, "same name at the same company", 2))
        for other in same_name:
            if other.pk not in seen:
                seen.add(other.pk)
                ranked.append((other, "same name", 3))

        ranked.sort(key=lambda row: row[2])
        return Response([
            {
                "contact": self.get_serializer(other).data,
                "match_reason": reason,
                "rank": rank,
            }
            for other, reason, rank in ranked
        ])

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
            # FR-2.7 — one search box. Locked notes match on a typed title
            # only and come back as stubs.
            "notes": note_representations(
                search_notes(request, request.query_params.get("q", "")), request=request,
            ) if (request.query_params.get("q") or "").strip() else [],
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

    @action(detail=True, methods=["get"])
    def timeline(self, request, pk=None):
        return Response(timeline.for_company(self.get_object()))

    def get_permissions(self):
        # Matrix 4.12 — seat_count is FF-only. `create` is included: a VA who
        # may not change a seat count may not set one on the way in either.
        if self.action in ("create", "update", "partial_update") and (
            self.request.data or {}
        ).get("seat_count") not in (None, ""):
            return [crm_perms.IsTenantStaff(), crm_perms.IsFF()]
        return super().get_permissions()


class PipelineViewSet(TenantStaffViewSet):
    """Matrix 3.14a — pipelines are FF-only to change, readable by all staff."""

    serializer_class = crm_serializers.PipelineSerializer

    def get_queryset(self):
        return Pipeline.objects.prefetch_related("stages")

    def get_permissions(self):
        if self.request.method in ("POST", "PUT", "PATCH", "DELETE"):
            return [crm_perms.IsTenantStaff(), crm_perms.IsFF()]
        return [crm_perms.IsTenantStaff()]

    def perform_destroy(self, instance):
        """A pipeline holding contacts is PROTECTed at the database; say so
        rather than letting a 500 explain it."""
        if instance.positions.exists():
            raise ValidationError(
                f"“{instance.name}” still holds {instance.positions.count()} "
                "contacts. Move them out first."
            )
        instance.delete()

    @action(detail=True, methods=["get"])
    def board(self, request, pk=None):
        """FR-1.9 — one board per pipeline: a column per stage with its contacts."""
        pipeline_row = self.get_object()
        visible = crm_perms.contact_queryset_for(
            request, Contact.objects.filter(deleted_at__isnull=True)
        )
        columns = []
        for stage in pipeline_row.stages.order_by("position"):
            contacts = visible.filter(pipeline_positions__stage=stage)
            columns.append({
                "stage": crm_serializers.PipelineStageSerializer(stage).data,
                "count": contacts.count(),
                "contacts": crm_serializers.ContactSerializer(
                    contacts.prefetch_related(
                        "emails", "phones", "type_links__contact_type",
                        "pipeline_positions__stage", "pipeline_positions__pipeline",
                    )[:100], many=True,
                ).data,
            })
        return Response({
            "pipeline": crm_serializers.PipelineSerializer(pipeline_row).data,
            "columns": columns,
        })


class PipelineStageViewSet(TenantStaffViewSet):
    """Matrix 3.14a — FF only to change. Stages are wired to automations and to
    the client invariant, so renaming or reordering them is a workflow change,
    not CRM hygiene.

    Renaming is safe by design: behaviour keys on `semantic`, never on the label.
    """

    serializer_class = crm_serializers.PipelineStageSerializer

    def get_queryset(self):
        qs = PipelineStage.objects.select_related("pipeline")
        pipeline_ref = self.request.query_params.get("pipeline")
        return qs.filter(pipeline_id=pipeline_ref) if pipeline_ref else qs

    def get_permissions(self):
        if self.request.method in ("POST", "PUT", "PATCH", "DELETE"):
            return [crm_perms.IsTenantStaff(), crm_perms.IsFF()]
        return [crm_perms.IsTenantStaff()]

    def perform_create(self, serializer):
        stage = serializer.save(tenant=self.request.tenant)
        self._validate(stage.pipeline)

    def perform_update(self, serializer):
        stage = serializer.save()
        self._validate(stage.pipeline)

    def perform_destroy(self, instance):
        """Both checks run BEFORE the delete.

        Validating afterwards and raising left the row already gone: the
        response said "refused" while the stage had in fact been destroyed.
        """
        if instance.positions.exists():
            raise ValidationError(
                f"“{instance.label}” still holds {instance.positions.count()} "
                "contacts. Move them to another stage first."
            )
        if (instance.pipeline.kind == Pipeline.Kind.SALES
                and instance.semantic == StageSemantic.WON):
            raise ValidationError(
                f"“{instance.pipeline.name}” is a sales pipeline and must have "
                f"exactly one stage marked won. Mark another stage won before "
                f"removing “{instance.label}”."
            )
        instance.delete()

    @staticmethod
    def _validate(pipeline_row):
        """FR-1.6 — a sales pipeline must keep exactly one `won` stage."""
        try:
            pipeline.validate_pipeline(pipeline_row)
        except pipeline.PipelineConfigError as exc:
            raise ValidationError(str(exc)) from exc


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
        qs = StageAutomation.objects.select_related("from_stage", "to_stage", "pipeline")
        pipeline_ref = self.request.query_params.get("pipeline")
        return qs.filter(pipeline_id=pipeline_ref) if pipeline_ref else qs


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

    def _editable(self, message):
        return message.state in (
            OutboxMessage.State.PENDING_APPROVAL, OutboxMessage.State.DRAFT,
        )

    @action(detail=True, methods=["patch"], url_path="edit")
    def edit(self, request, pk=None):
        """Review & edit — subject, body, and the per-draft sender override.

        Only while the draft is still pending: a sent message is a log entry and
        editing one would make the Outbox stop being a record of what went out.
        """
        message = self.get_object()
        if not self._editable(message):
            return Response(
                {"detail": f"This message is {message.state} and can no longer be edited."},
                status=400,
            )
        for field in ("subject", "body_text", "body_html"):
            if field in request.data:
                setattr(message, field, request.data[field] or "")
        sender_choice = request.data.get("sender")
        if sender_choice:
            from apps.crm.services import sender as sender_service

            message.from_address = sender_service.resolve_from(
                message.tenant, request.user, message.producer, override=sender_choice,
            )
        message.save(update_fields=[
            "subject", "body_text", "body_html", "from_address", "updated_at",
        ])
        return Response(self.get_serializer(message).data)

    @action(detail=True, methods=["post"], url_path="attachments")
    def add_attachment(self, request, pk=None):
        """FR-1.23b — add a file to a draft. Size-capped; PROTECTed once used."""
        message = self.get_object()
        if not self._editable(message):
            return Response(
                {"detail": f"This message is {message.state}; attachments are fixed."},
                status=400,
            )
        upload = request.FILES.get("file")
        if upload is None:
            return Response({"detail": "No file supplied."}, status=400)
        if upload.size > MAX_ATTACHMENT_BYTES:
            return Response({"detail": (
                f"{upload.name} is {upload.size // 1024} KB. The limit is "
                f"{MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB per file."
            )}, status=400)
        from apps.crm.models import OutboxAttachment
        from apps.tenancy.models import StoredFile

        stored = storage.save(
            tenant=request.tenant, content=upload.read(),
            object_key=storage.object_key(
                f"outbox/{request.tenant.slug}/{message.pk}", upload.name
            ),
            content_type=upload.content_type or "application/octet-stream",
            purpose="outbox_attachment",
        )
        OutboxAttachment.all_objects.create(
            tenant=request.tenant, outbox_message=message,
            stored_file=stored, filename=upload.name,
        )
        message.refresh_from_db()
        return Response(self.get_serializer(message).data, status=201)

    @action(detail=True, methods=["delete"], url_path="attachments/(?P<attachment_id>[^/.]+)")
    def remove_attachment(self, request, pk=None, attachment_id=None):
        from apps.crm.models import OutboxAttachment

        message = self.get_object()
        if not self._editable(message):
            return Response(
                {"detail": f"This message is {message.state}; attachments are fixed."},
                status=400,
            )
        attachment = OutboxAttachment.objects.filter(
            pk=attachment_id, outbox_message=message
        ).first()
        if attachment is None:
            raise Http404
        attachment.delete()
        message.refresh_from_db()
        return Response(self.get_serializer(message).data)

    @action(detail=False, methods=["post"], url_path="approve-selected", permission_classes=[
        crm_perms.IsTenantStaff, crm_perms.CanSend
    ])
    def approve_selected(self, request):
        """FR-1.15 — one review pass over a batch of templated drafts.

        This is a batch of approvals, NOT a bypass: every id is approved
        individually through the same `outbox.approve`, and each one still had
        to be selected by a human. A failure on one does not silently take the
        rest with it — the response names what went out and what did not.
        """
        ids = request.data.get("ids") or []
        if not isinstance(ids, list) or not ids:
            return Response({"detail": "Select at least one message."}, status=400)
        queryset = self.get_queryset().filter(
            pk__in=ids, state=OutboxMessage.State.PENDING_APPROVAL,
        )
        approved, failed = [], []
        for message in queryset:
            try:
                outbox.approve(
                    message, actor=request.user, role=crm_perms.role_of(request),
                )
                approved.append(str(message.pk))
            except Exception as exc:  # surfaced per message, never swallowed
                failed.append({"id": str(message.pk), "to": message.to_address,
                               "detail": str(exc)})
        return Response({
            "approved": approved, "approved_count": len(approved),
            "failed": failed,
            "skipped": len(set(map(str, ids)) - set(approved)
                           - {f["id"] for f in failed}),
        })


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
            file_bytes=upload.read(),
            mapping=_json_field(request, "mapping"),
            value_mapping=_json_field(request, "value_mapping"),
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

    @action(detail=False, methods=["post"], url_path="scan-values")
    def scan_values(self, request):
        """Step 2b — every distinct value in the contact_type column, counted.

        Takes the file again rather than a stashed copy: the dry run has not run
        yet at this point, so there is nothing on the server to read.
        """
        upload = request.FILES.get("file")
        if upload is None:
            return Response({"detail": "No file supplied."}, status=400)
        return Response(importer.scan_values(
            tenant=request.tenant, file_bytes=upload.read(),
            mapping=_json_field(request, "mapping"),
        ))

    @action(detail=True, methods=["get"])
    def ambiguous(self, request, pk=None):
        """The rows a human must resolve, each with its persisted candidates."""
        batch = self.get_object()
        rows = batch.rows.filter(outcome="ambiguous").order_by("row_number")
        payload = []
        for row in rows:
            candidates = Contact.objects.filter(
                pk__in=row.candidate_ids, deleted_at__isnull=True
            )
            payload.append({
                "row": crm_serializers.ImportRowSerializer(row).data,
                "candidates": crm_serializers.ContactSerializer(candidates, many=True).data,
            })
        return Response(payload)

    @action(detail=True, methods=["post"])
    def commit(self, request, pk=None):
        """Commits with the mapping the DRY RUN used unless one is supplied —
        the preview and the write must not be able to disagree."""
        batch = self.get_object()
        importer.commit(batch, actor=request.user)
        return Response(self.get_serializer(batch).data)

    @action(detail=True, methods=["post"])
    def rollback(self, request, pk=None):
        batch = self.get_object()
        report = importer.rollback(batch, actor=request.user)
        return Response({"batch": self.get_serializer(batch).data, "report": report})


class ImportMappingProfileViewSet(TenantStaffViewSet):
    """FR-1.27 — remembered column AND value mappings. Matrix 4.13: FF or VA."""

    serializer_class = crm_serializers.ImportMappingProfileSerializer

    def get_permissions(self):
        return [crm_perms.IsTenantStaff(), crm_perms.IsFFOrVA()]

    def get_queryset(self):
        return ImportMappingProfile.objects.order_by("name")


class MailPreferenceView(viewsets.ViewSet):
    """FR-1.15c/d — the signed-in user's own sender defaults and signature.

    Per user, not per tenant: "my own address" and a signature are personal, and
    a CF's touches should not sign off as the FF.
    """

    permission_classes = [crm_perms.IsTenantStaff, crm_perms.CanConnectMailbox]

    def list(self, request):
        from apps.crm.services import sender as sender_service

        preference = sender_service.preference_for(request.tenant, request.user)
        return Response(crm_serializers.MailPreferenceSerializer(preference).data)

    def create(self, request):
        from apps.crm.services import sender as sender_service

        preference = sender_service.preference_for(request.tenant, request.user)
        serializer = crm_serializers.MailPreferenceSerializer(
            preference, data=request.data, partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class DevSendAllowlistViewSet(viewsets.ModelViewSet):
    """FR-0.7 / H6 — who may receive REAL mail from a localhost build.

    **The whole viewset 404s on a non-localhost build.** Not 403: on a
    production deployment this mechanism does not exist at all, and a 403 would
    advertise a switch that is not there. `settings.py` already refuses to start
    with a populated `.env` allow-list outside localhost; this is the same rule
    applied to the API.
    """

    permission_classes = [crm_perms.IsTenantStaff, crm_perms.IsFF]
    serializer_class = crm_serializers.DevSendAllowlistEntrySerializer

    def initial(self, request, *args, **kwargs):
        if not dj_settings.IS_LOCAL:
            raise Http404("The dev send allow-list exists only on localhost builds.")
        return super().initial(request, *args, **kwargs)

    def get_queryset(self):
        return DevSendAllowlistEntry.objects.order_by("address")

    def perform_create(self, serializer):
        entry = serializer.save(tenant=self.request.tenant, added_by=self.request.user)
        AuditEvent.all_objects.create(
            tenant=self.request.tenant, actor=self.request.user,
            verb="dev_allowlist.added", target_type="dev_send_allowlist_entry",
            target_id=entry.pk, payload={"address": entry.address},
        )

    def perform_destroy(self, instance):
        address = instance.address
        instance.delete()
        AuditEvent.all_objects.create(
            tenant=self.request.tenant, actor=self.request.user,
            verb="dev_allowlist.removed", target_type="dev_send_allowlist_entry",
            target_id=None, payload={"address": address},
        )

    @action(detail=False, methods=["get"])
    def effective(self, request):
        """The list actually in force: `.env` entries unioned with these rows.

        `.env` entries are shown as locked — they are the deployment's floor and
        cannot be removed from inside the app.
        """
        from apps.accounts.mailer import dev_allowlist

        from_env = sorted(dj_settings.DEV_REAL_SEND_ALLOWLIST)
        rows = {e.address: e for e in self.get_queryset()}
        return Response({
            "is_local": dj_settings.IS_LOCAL,
            "from_env": from_env,
            "entries": [
                {"id": str(e.pk), "address": a, "note": e.note,
                 "source": "database", "removable": True}
                for a, e in sorted(rows.items())
            ],
            "effective": sorted(dev_allowlist(request.tenant)),
            "env_locked": from_env,
        })


class EmailTemplateViewSet(TenantStaffViewSet):
    """Matrix 3.13 — a VA may edit body copy; the FF creates and deletes."""

    serializer_class = crm_serializers.EmailTemplateSerializer

    def get_queryset(self):
        from apps.crm.models import EmailTemplate

        return EmailTemplate.objects.all()

    def get_permissions(self):
        if self.request.method in ("POST", "DELETE"):
            return [crm_perms.IsTenantStaff(), crm_perms.IsFF()]
        return [crm_perms.IsTenantStaff()]


class ReferralSettingsView(viewsets.ViewSet):
    """FR-1.21a / FR-1.23b — the blurb and the flyer. FF only (matrix 3.6, 3.7)."""

    permission_classes = [crm_perms.IsTenantStaff, crm_perms.IsFF]

    def list(self, request):
        tenant = request.tenant
        age = None
        if tenant.referral_blurb_updated_at:
            from django.utils import timezone

            age = (timezone.now() - tenant.referral_blurb_updated_at).days
        return Response({
            "referral_blurb": tenant.referral_blurb,
            "referral_blurb_updated_at": tenant.referral_blurb_updated_at,
            "blurb_age_days": age,
            "marketing_flyer": str(tenant.marketing_flyer_id) if tenant.marketing_flyer_id else None,
            "marketing_flyer_name": (
                tenant.marketing_flyer.object_key.rsplit("/", 1)[-1]
                if tenant.marketing_flyer_id else ""
            ),
            "marketing_flyer_bytes": (
                tenant.marketing_flyer.byte_size if tenant.marketing_flyer_id else 0
            ),
            # A flyer uploaded before storage wrote content is a row with
            # nothing behind it. Saying so here is how the FF finds out before a
            # client would have.
            "marketing_flyer_present": (
                storage.present_or_unknown(tenant.marketing_flyer)
                if tenant.marketing_flyer_id else False
            ),
        })

    def create(self, request):
        from django.utils import timezone

        tenant = request.tenant
        tenant.referral_blurb = request.data.get("referral_blurb", "")
        tenant.referral_blurb_updated_at = timezone.now()
        tenant.save(update_fields=[
            "referral_blurb", "referral_blurb_updated_at", "updated_at"
        ])
        AuditEvent.all_objects.create(
            tenant=tenant, actor=request.user, verb="referral.blurb_updated",
            target_type="tenant", target_id=tenant.pk, payload={},
        )
        return self.list(request)

    @action(detail=False, methods=["post"])
    def flyer(self, request):
        from django.conf import settings as dj_settings

        from apps.tenancy.models import StoredFile

        upload = request.FILES.get("flyer")
        if upload is None:
            return Response({"detail": "No file supplied."}, status=400)
        # The bytes and the row are written together (tenancy.storage) — the
        # flyer was previously recorded at its full size with no content behind
        # it, so it arrived as a 0-byte attachment.
        stored = storage.save(
            tenant=request.tenant, content=upload.read(),
            # Unique per upload: a re-upload under the same name used to
            # overwrite the bytes behind the previous flyer's row.
            object_key=storage.object_key(f"flyers/{request.tenant.slug}", upload.name),
            content_type=upload.content_type or "application/pdf",
            purpose="marketing_flyer",
        )
        request.tenant.marketing_flyer = stored
        request.tenant.save(update_fields=["marketing_flyer", "updated_at"])
        return self.list(request)


# The task API moved to apps/work/views.py in Phase 3, where Module 3 owns it.
# Phase 1's read-only stand-in is gone; the table stays in this app because
# stage automations create tasks (FR-1.11).
