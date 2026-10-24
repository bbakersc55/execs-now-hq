"""Module 1 API. Every queryset is scoped twice: by the fail-closed tenant
manager (B1), and by the role rules in `03_access_matrix.md`."""

from __future__ import annotations

from django.conf import settings as dj_settings
from django.db import transaction
from django.db.models import Q, Value
from django.db.models.functions import Concat
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
from apps.crm.services import (
    clients, importer, merge, outbox, pipeline, referral, referrals, search, timeline,
)
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


#: What a one-click group merge fills on the survivor when the survivor has it
#: empty (2026-09-29). The two-record screen asks field by field instead.
MERGE_FILL_FIELDS = ("title", "source", "background", "referral_fee_terms", "company_id",
                     "linkedin_url", "alignable_url")

class TenantStaffViewSet(viewsets.ModelViewSet):
    permission_classes = [crm_perms.IsTenantStaff]

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


def _thanks_drafted(contact, change):
    """{"to", "label"} of the referral thank-you a stage move drafted, or None."""
    from apps.crm.models import Referral
    from apps.crm.services import referrals

    if change is None:
        return None
    ids = Referral.all_objects.filter(tenant_id=contact.tenant_id, prospect=contact,
                                      pipeline_id=change.pipeline_id).values_list("pk", flat=True)
    message = (OutboxMessage.all_objects.filter(
        tenant_id=contact.tenant_id, producer=OutboxMessage.Producer.REFERRAL_THANKS,
        source_id__in=list(ids), source_type__in=[referrals.SOURCE_TYPE[referrals.WON],
                                                  referrals.SOURCE_TYPE[referrals.LOST]],
        created_at__gte=change.created_at).select_related("to_contact").first())
    if message is None:
        return None
    return {"to": referrals.full_name(message.to_contact) if message.to_contact else
            message.to_address, "label": referrals.label_of(message)}


class ContactViewSet(TenantStaffViewSet):
    serializer_class = crm_serializers.ContactSerializer

    def get_queryset(self):
        from django.db.models import Exists, OuterRef

        from apps.crm.models import Enrollment

        qs = Contact.objects.filter(deleted_at__isnull=True).prefetch_related(
            "emails", "phones", "type_links__contact_type",
            "referrals_received__referrer", "referrals_received__pipeline",
        ).annotate(referral_enrolled_annotated=Exists(Enrollment.objects.filter(
            contact=OuterRef("pk"), program=Enrollment.Program.REFERRAL_TOUCHES,
            ended_at__isnull=True)))
        return crm_perms.contact_queryset_for(self.request, qs)

    # ---------------------------------------------------------- enrolment

    def _may_enroll(self, request):
        """The FF or a CF (owner, 2026-09-28): putting someone on a recurring
        email is a decision about the relationship, not data entry."""
        if crm_perms.role_of(request) not in ("FF", "CF"):
            self.permission_denied(request, message=(
                "Enrolling someone in email is for the practice owner or an associate."))

    @action(detail=True, methods=["get"])
    def enrollments(self, request, pk=None):
        """Everything this person is enrolled in — touches, digests — in one
        list, each with the way off."""
        from apps.crm.services import enrollment

        return Response(enrollment.enrollments_for(self.get_object()))

    @action(detail=True, methods=["get"])
    def suppressions(self, request, pk=None):
        """What this person has unsubscribed from (owner, 2026-09-28). Shown,
        not editable: only the recipient's own link takes them back."""
        from django.utils import timezone

        from apps.crm.models import EmailSuppression
        from apps.crm.services import unsubscribe

        rows = EmailSuppression.objects.filter(contact=self.get_object(),
                                               lifted_at__isnull=True)
        return Response([{"category": row.category,
                          "label": unsubscribe.LABELS[row.category],
                          "since": row.created_at.isoformat(),
                          "date": timezone.localdate(row.created_at).isoformat()}
                         for row in rows])

    @action(detail=True, methods=["post"])
    def enroll(self, request, pk=None):
        from apps.crm.services import enrollment

        self._may_enroll(request)
        contact = self.get_object()
        try:
            _row, created = enrollment.enroll(
                contact, request.data.get("program") or "referral_touches",
                actor=request.user)
        except enrollment.EnrollmentRefused as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        # Fresh, so the enrolled flag is read after the change, not before.
        contact = self.get_queryset().get(pk=contact.pk)
        return Response({"created": created,
                         "enrollments": enrollment.enrollments_for(contact),
                         "contact": self.get_serializer(contact).data},
                        status=201 if created else 200)

    @action(detail=True, methods=["post"])
    def unenroll(self, request, pk=None):
        """Off one program — or, with `stakeholder`, off one digest."""
        from apps.crm.services import enrollment
        from apps.work.models import Stakeholder

        self._may_enroll(request)
        contact = self.get_object()
        stakeholder_id = request.data.get("stakeholder")
        recipient_id = request.data.get("campaign_recipient")
        if recipient_id:
            from apps.crm.models import CampaignRecipient
            from apps.crm.services import campaigns

            row = CampaignRecipient.objects.filter(pk=recipient_id, contact=contact,
                                                   ended_at__isnull=True).first()
            if row is None:
                return Response({"detail": "Not one of their campaigns."}, status=404)
            campaigns.end(row, actor=request.user)
        elif stakeholder_id:
            row = Stakeholder.objects.filter(pk=stakeholder_id, contact=contact).first()
            if row is None:
                return Response({"detail": "Not one of their digests."}, status=404)
            enrollment.unenroll_digest(row, actor=request.user)
        else:
            enrollment.unenroll(contact, request.data.get("program") or "referral_touches",
                                actor=request.user)
        contact = self.get_queryset().get(pk=contact.pk)
        return Response({"enrollments": enrollment.enrollments_for(contact),
                         "contact": self.get_serializer(contact).data})

    @action(detail=False, methods=["post"], url_path="enroll-selected")
    def enroll_selected(self, request):
        """Bulk, from the partner table. Each contact on its own terms: one who
        is not a partner is skipped and named, not a reason to fail the rest."""
        from apps.crm.services import enrollment

        self._may_enroll(request)
        ids = request.data.get("ids") or []
        if not isinstance(ids, list) or not ids:
            return Response({"detail": "Select at least one contact."}, status=400)
        program = request.data.get("program") or "referral_touches"
        leave = bool(request.data.get("unenroll"))
        done, skipped = [], []
        for contact in self.get_queryset().filter(pk__in=ids):
            try:
                if leave:
                    changed = enrollment.unenroll(contact, program, actor=request.user)
                else:
                    changed = enrollment.enroll(contact, program, actor=request.user,
                                                source="bulk")[1]
            except enrollment.EnrollmentRefused as exc:
                skipped.append({"contact": str(contact.pk),
                                "name": f"{contact.first_name} {contact.last_name}".strip(),
                                "detail": str(exc)})
                continue
            if changed:
                done.append(str(contact.pk))
        return Response({"changed": done, "changed_count": len(done), "skipped": skipped})

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
        contact = self.get_object()
        return Response(timeline.for_contact(
            contact, money=crm_perms.sees_money(request, contact.company_id)))

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
        from apps.crm.services import follow_ups

        return Response({
            # Part 3: "Start the <stage> follow-up?", unless a rule started it.
            "follow_up_offer": follow_ups.offer(contact, stage) if change is not None else None,
            "contact": self.get_serializer(contact).data,
            "changed": change is not None,
            # A referred prospect won or lost: the thank-you this move drafted,
            # so the board can say where it is (finding T2, 2026-10-22).
            "thanks_drafted": _thanks_drafted(contact, change),
        })

    @action(detail=True, methods=["post"], url_path="follow-up")
    def follow_up(self, request, pk=None):
        """Part 3: {stage} starts that stage's follow-up (the move's question
        answered yes); {stop: run id} stops one, withdrawing a waiting draft."""
        from apps.crm.models import FollowUpRun
        from apps.crm.services import follow_ups

        contact = self.get_object()
        if request.data.get("stop"):
            run = follow_ups.running(contact).filter(pk=request.data["stop"]).first() \
                if _is_uuid(str(request.data["stop"])) else None
            if run is None:
                return Response({"detail": "That follow-up isn't running."}, status=400)
            follow_ups.stop(run, reason="stopped", actor=request.user)
        else:
            ref = str(request.data.get("stage") or "")
            stage = PipelineStage.objects.filter(pk=ref).first() if _is_uuid(ref) else None
            if stage is None:
                return Response({"detail": "Unknown stage."}, status=400)
            try:
                follow_ups.start(contact, stage, actor=request.user, via="asked")
            except follow_ups.FollowUpRefused as exc:
                return Response({"detail": str(exc)}, status=400)
        contact.refresh_from_db()
        return Response({"contact": self.get_serializer(contact).data,
                         "running": FollowUpRun.all_objects.filter(
                             contact=contact, status=FollowUpRun.Status.ACTIVE).count()})

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
        if not contact.enrollments.filter(program="referral_touches",
                                          ended_at__isnull=True).exists():
            return Response({"detail": (
                f"{contact.first_name} is not enrolled in referral touches. "
                "Enroll them first.")}, status=400)
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

    @action(detail=False, methods=["post"], url_path="draft-emails/preview")
    def draft_emails_preview(self, request):
        """The email "Email these contacts" would draft, for the first person
        picked, and every field that has nothing for any of them, by name
        (finding T5, 2026-10-22). Writes nothing."""
        from apps.crm.services import templates

        ids = request.data.get("ids") or []
        if not isinstance(ids, list) or not ids:
            return Response({"detail": "Select at least one contact."}, status=400)
        contacts = list(crm_perms.contact_queryset_for(
            request, Contact.objects.filter(pk__in=ids, deleted_at__isnull=True))
            .select_related("company"))
        if not contacts:
            return Response({"detail": "Select at least one contact."}, status=400)
        subject = str(request.data.get("subject") or "").replace("{first_name}", "{FirstName}")
        body = str(request.data.get("body_text") or "").replace("{first_name}", "{FirstName}")
        try:
            templates.check(subject, body)
        except templates.TemplateRefused as refused:
            return Response({"detail": str(refused)}, status=400)
        fallback = (str(request.data.get("fallback") or "").strip()
                    or templates.DEFAULT_FALLBACK)
        empty = {}
        for contact in contacts:
            values = templates.values_for(contact, tenant=request.tenant, sender=request.user)
            for name in templates.empty_fields(values, subject, body):
                empty.setdefault(name, []).append(
                    f"{contact.first_name} {contact.last_name}".strip())
        first = contacts[0]
        values = templates.values_for(first, tenant=request.tenant, sender=request.user)
        labels = dict(templates.FIELDS)
        return Response({
            "to": f"{first.first_name} {first.last_name}".strip(),
            "subject": templates.render_subject(subject, values, fallback=fallback),
            "body": templates.render(body, values, fallback=fallback),
            "empty": [{
                "field": name, "label": labels[name],
                "why": templates.ONLY_IN.get(name, ""),
                "people": len(people), "of": len(contacts),
            } for name, people in empty.items()],
        })

    def _bulk_draft(self, request, *, kind):
        ids = request.data.get("ids") or []
        if not isinstance(ids, list) or not ids:
            return Response({"detail": "Select at least one contact."}, status=400)

        contacts = crm_perms.contact_queryset_for(
            request, Contact.objects.filter(pk__in=ids, deleted_at__isnull=True)
        )
        template = None
        if kind == "email":
            from apps.crm.services import templates

            template_id = request.data.get("template")
            if template_id and _is_uuid(template_id):
                template = EmailTemplate.objects.filter(pk=template_id).first()
            try:
                templates.check(*(str(request.data.get(k) or "").replace(
                    "{first_name}", "{FirstName}") for k in ("subject", "body_text")))
            except templates.TemplateRefused as refused:
                return Response({"detail": str(refused)}, status=400)

        drafted, skipped = [], []
        # One-off to one person: correspondence. To several at once: marketing,
        # with the link, and stopped by a marketing unsubscribe (2026-09-28).
        many = contacts.count() > 1
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
                if not contact.enrollments.filter(program="referral_touches",
                                                  ended_at__isnull=True).exists():
                    skipped.append({"contact": str(contact.pk),
                                    "name": f"{contact.first_name} {contact.last_name}",
                                    "detail": "not enrolled in referral touches"})
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
                    category="marketing" if many else None,
                    fallback=template.first_name_fallback if template else None,
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

    @action(detail=False, methods=["get"], url_path="duplicate-groups",
            permission_classes=[crm_perms.IsFFOrVA])
    def duplicate_groups(self, request):
        """Likely duplicates across the whole book (owner, 2026-09-29): same
        email address, or the same normalized full name. Proposed, never
        merged — the person picks the survivor. FF and VA, as merge (4.5)."""
        from apps.crm.services import duplicates

        return Response(duplicates.groups(self.get_queryset()))

    @action(detail=False, methods=["post"], url_path="not-duplicates",
            permission_classes=[crm_perms.IsFFOrVA])
    def not_duplicates(self, request):
        """POST {contacts: [ids], undo?: bool}: these are not duplicates of
        each other (backlog, 2026-10-03), or take that back. Only contacts the
        person can see; FF and VA, as merge."""
        from apps.crm.services import duplicates

        ids = [str(i) for i in (request.data.get("contacts") or [])]
        visible = list(self.get_queryset().filter(pk__in=ids))
        if len(ids) < 2 or len(visible) != len(set(ids)):
            raise Http404
        if request.data.get("undo"):
            return Response({"undone": duplicates.undo_dismissal(visible, actor=request.user)})
        return Response({"dismissed": duplicates.dismiss(visible, actor=request.user)})

    @action(detail=False, methods=["post"], url_path="merge-group",
            permission_classes=[crm_perms.IsFFOrVA])
    def merge_group(self, request):
        """One click: every other contact in the group into the survivor,
        through the same merge as the two-record screen, in one transaction.
        The survivor's own values stand; a field it has empty takes the first
        value an absorbed record holds, so nothing typed is lost."""
        visible = self.get_queryset()
        survivor = visible.filter(pk=request.data.get("survivor")).first()
        ids = [str(i) for i in (request.data.get("absorbed") or [])]
        absorbed = list(visible.filter(pk__in=ids))
        if survivor is None or not ids or len(absorbed) != len(set(ids)):
            raise Http404
        if any(c.pk == survivor.pk for c in absorbed):
            return Response({"detail": "The survivor cannot also be merged away."},
                            status=400)
        with transaction.atomic():
            for other in absorbed:
                blanks = {f: getattr(other, f) for f in MERGE_FILL_FIELDS
                          if not getattr(survivor, f) and getattr(other, f)}
                merge.merge_contacts(survivor, other, actor=request.user,
                                     role=crm_perms.role_of(request),
                                     field_choices=blanks)
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
                ), many=True, context={"request": request},
            ).data,
            "companies": crm_serializers.CompanySerializer(
                crm_perms.company_queryset_for(
                    request, Company.objects.filter(
                        pk__in=[c.pk for c in results["companies"]]
                    )
                ), many=True, context={"request": request},
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


def _client_status(company) -> dict:
    return {
        "id": str(company.pk),
        "is_client_company": company.is_client_company,
        # Empty while it is not a client, or when the mark can be undone.
        "undo_blockers": clients.blockers(company) if company.is_client_company else [],
    }


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

    @action(detail=True, methods=["get"], url_path="client-status")
    def client_status(self, request, pk=None):
        """Whether it is a client company, and what would stop that being
        undone. Read by the Company page, for anyone who may see the company."""
        company = self.get_object()
        return Response(_client_status(company))

    @action(detail=True, methods=["post"], url_path="mark-client")
    def mark_client(self, request, pk=None):
        """Practice owner only. Flags the company and nothing else: no stage
        changes, so no stage automation runs (services/clients.py)."""
        company = clients.mark(self.get_object(), actor=request.user)
        return Response(_client_status(company))

    @action(detail=True, methods=["post"], url_path="unmark-client")
    def unmark_client(self, request, pk=None):
        """Practice owner only, and only while nothing has been built on it."""
        company = self.get_object()
        try:
            clients.unmark(company, actor=request.user)
        except clients.ClientMarkRefused as exc:
            return Response({"detail": str(exc), **_client_status(company)}, status=409)
        return Response(_client_status(company))

    def get_permissions(self):
        if self.action in ("mark_client", "unmark_client"):
            return [crm_perms.IsTenantStaff(), crm_perms.IsFF()]
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
        """FR-1.9 — one board per pipeline: a column per stage with its contacts.

        A column carries its first 100 cards. `expand` (stage ids, comma
        separated) lifts that for the columns named: the board's "Show more".
        `q` narrows every column to the cards matching it, on the server, so a
        search reaches the cards a long column has not loaded. `count` is
        always the whole column; `matched` is how many of it match `q`.
        """
        pipeline_row = self.get_object()
        visible = crm_perms.contact_queryset_for(
            request, Contact.objects.filter(deleted_at__isnull=True)
        )
        q = (request.query_params.get("q") or "").strip()
        expand = {
            ref for ref in (request.query_params.get("expand") or "").split(",") if ref
        }
        columns = []
        for stage in pipeline_row.stages.order_by("position"):
            contacts = visible.filter(pipeline_positions__stage=stage)
            count = contacts.count()
            matching, matched = contacts, count
            if q:
                # The same four things the card shows, and the board filters on.
                matching = contacts.annotate(
                    _full_name=Concat("first_name", Value(" "), "last_name"),
                ).filter(
                    Q(_full_name__icontains=q) | Q(company__name__icontains=q)
                    | Q(emails__address__icontains=q) | Q(phones__number__icontains=q)
                ).distinct()
                matched = matching.count()
            # Ordered, so the 100 a long column shows are the same 100 each time.
            ordered = matching.select_related("company").prefetch_related(
                "emails", "phones", "type_links__contact_type",
                "pipeline_positions__stage", "pipeline_positions__pipeline",
                "referrals_received__referrer", "referrals_received__pipeline",
            ).order_by("last_name", "first_name", "pk")
            shown = list(ordered if str(stage.pk) in expand else ordered[:100])
            cards = crm_serializers.ContactSerializer(
                shown, many=True, context={"request": request}).data
            # The card names the company; the contact payload only carries its
            # id. Added here, not on the serializer, so no other payload moves.
            for card, contact in zip(cards, shown):
                card["company_name"] = contact.company.name if contact.company else ""
            columns.append({
                "stage": crm_serializers.PipelineStageSerializer(stage).data,
                "count": count,
                "matched": matched,
                "contacts": cards,
            })
        return Response({
            "pipeline": crm_serializers.PipelineSerializer(pipeline_row).data,
            "q": q,
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

    @action(detail=False, methods=["post"])
    def order(self, request):
        """Stage rules, part 2: the stage cards in a new order. `ids` is every
        stage of one pipeline, first to last."""
        pipeline_row = Pipeline.objects.filter(pk=request.data.get("pipeline")).first()
        if pipeline_row is None:
            raise ValidationError("Choose a pipeline.")
        ids = [str(i) for i in (request.data.get("ids") or [])]
        stages = {str(s.pk): s for s in PipelineStage.objects.filter(pipeline=pipeline_row)}
        if sorted(ids) != sorted(stages):
            raise ValidationError("Send every stage of the pipeline, in the new order.")
        with transaction.atomic():
            for position, stage_id in enumerate(ids):
                stage = stages[stage_id]
                if stage.position != position:
                    stage.position = position
                    stage.save(update_fields=["position", "updated_at"])
        AuditEvent.objects.create(
            tenant=request.tenant, actor=request.user, verb="pipeline.stages_reordered",
            target_type="pipeline", target_id=pipeline_row.pk,
            payload={"order": [stages[i].label for i in ids]})
        return Response(crm_serializers.PipelineStageSerializer(
            PipelineStage.objects.filter(pipeline=pipeline_row).order_by("position"),
            many=True).data)

    @action(detail=True, methods=["get", "put", "delete"], url_path="follow-up")
    def follow_up(self, request, pk=None):
        """Part 3: the stage's follow-up. PUT {steps: [{template, days_after}],
        is_active}; DELETE removes it (stopping nothing already running is
        not allowed: runs are stopped first, their drafts withdrawn)."""
        from apps.crm.models import FollowUp
        from apps.crm.services import follow_ups

        stage = self.get_object()
        if request.method == "GET":
            return Response({"follow_up": follow_ups.describe(stage)})
        if request.method == "DELETE":
            found = FollowUp.objects.filter(stage=stage).first()
            if found is not None:
                for run in found.runs.filter(status="active"):
                    follow_ups.stop(run, reason="stopped", actor=request.user)
                found.delete()
                AuditEvent.objects.create(
                    tenant=request.tenant, actor=request.user, verb="follow_up.removed",
                    target_type="pipeline_stage", target_id=stage.pk,
                    payload={"stage": stage.label})
            return Response({"follow_up": None})
        try:
            follow_ups.save(stage, request.data.get("steps") or [], actor=request.user,
                            is_active=request.data.get("is_active", True) is not False)
        except follow_ups.FollowUpRefused as exc:
            raise ValidationError(str(exc)) from exc
        return Response({"follow_up": follow_ups.describe(stage)})

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


class ContactTagViewSet(viewsets.GenericViewSet):
    """The practice's contact tags, for Settings (owner, 2026-10-12).

    A tag is added on a contact, as it always was: it is a word on a contact
    and has no row of its own. What was missing is changing one everywhere:
    `rename` (onto a tag that exists already merges the two) and `remove`.
    The practice owner's, and audited, because one press changes many
    contacts.
    """

    permission_classes = [crm_perms.IsTenantStaff, crm_perms.IsFF]

    def _counts(self) -> list[dict]:
        counts: dict = {}
        for tags in Contact.objects.exclude(tags=[]).values_list("tags", flat=True):
            for tag in tags:
                counts[tag] = counts.get(tag, 0) + 1
        return [{"tag": tag, "contacts": n}
                for tag, n in sorted(counts.items(), key=lambda row: row[0].lower())]

    def _tag(self, request, key):
        tag = str(request.data.get(key) or "").strip()
        if not tag:
            raise ValidationError({key: "Say which tag."})
        if len(tag) > 64:
            raise ValidationError({key: "A tag is 64 characters at most."})
        return tag

    def list(self, request):
        return Response(self._counts())

    @transaction.atomic
    def _rewrite(self, request, old, new, verb):
        changed = 0
        for contact in Contact.objects.filter(tags__contains=[old]):
            kept = []
            for tag in contact.tags:
                tag = new if tag == old else tag
                if tag and tag not in kept:
                    kept.append(tag)
            contact.tags = kept
            contact.save(update_fields=["tags", "updated_at"])
            changed += 1
        if changed:
            AuditEvent.objects.create(
                tenant=request.tenant, actor=request.user, verb=verb,
                target_type="contact_tag", target_id=None,
                payload={"tag": old, "to": new, "contacts": changed})
        return Response({"changed": changed, "tags": self._counts()})

    @action(detail=False, methods=["post"])
    def rename(self, request):
        old, new = self._tag(request, "tag"), self._tag(request, "to")
        return self._rewrite(request, old, new, "contact_tag.renamed")

    @action(detail=False, methods=["post"])
    def remove(self, request):
        return self._rewrite(request, self._tag(request, "tag"), "", "contact_tag.removed")


class StageAutomationViewSet(TenantStaffViewSet):
    """Matrix 3.12 — FF only."""

    serializer_class = crm_serializers.StageAutomationSerializer
    permission_classes = [crm_perms.IsTenantStaff, crm_perms.IsFF]

    def get_queryset(self):
        qs = StageAutomation.objects.select_related(
            "from_stage", "to_stage", "pipeline", "move_to_stage", "email_template",
            "task_assignee").order_by("position", "created_at")
        pipeline_ref = self.request.query_params.get("pipeline")
        return qs.filter(pipeline_id=pipeline_ref) if pipeline_ref else qs

    @action(detail=False, methods=["get", "post"])
    def examples(self, request):
        """Stage rules, part 2: the starter rules, one click each. GET lists
        what this pipeline can take; POST {pipeline, key} adds one."""
        from apps.crm.services import stage_rules

        ref = request.query_params.get("pipeline") if request.method == "GET" \
            else request.data.get("pipeline")
        pipeline_row = Pipeline.objects.filter(pk=ref).first() if ref else None
        if pipeline_row is None:
            raise ValidationError("Choose a pipeline.")
        from apps.crm.services import follow_ups

        offered = stage_rules.examples_for(pipeline_row)
        sequences = follow_ups.starters_for(pipeline_row)
        if request.method == "GET":
            return Response([{**{k: v for k, v in e.items() if k != "fields"}, "kind": "rule"}
                             for e in offered]
                            + [{"key": s["key"], "summary": s["summary"], "added": s["added"],
                                "kind": "follow_up", "stage": str(s["stage"].pk)}
                               for s in sequences])
        if request.data.get("key") in follow_ups.STARTERS:
            try:
                found = follow_ups.add_starter(pipeline_row, request.data["key"],
                                               actor=request.user)
            except follow_ups.FollowUpRefused as exc:
                raise ValidationError(str(exc)) from exc
            AuditEvent.objects.create(
                tenant=request.tenant, actor=request.user, verb="follow_up.example_added",
                target_type="pipeline", target_id=pipeline_row.pk,
                payload={"key": request.data["key"]})
            return Response(follow_ups.describe(found.stage), status=status.HTTP_201_CREATED)
        example = next((e for e in offered if e["key"] == request.data.get("key")), None)
        if example is None:
            raise ValidationError("That example isn't offered for this pipeline.")
        rule = StageAutomation.objects.create(
            tenant=request.tenant, pipeline=pipeline_row, **example["fields"])
        AuditEvent.objects.create(
            tenant=request.tenant, actor=request.user, verb="stage_rule.example_added",
            target_type="pipeline", target_id=pipeline_row.pk,
            payload={"key": example["key"], "rule": str(rule.pk)})
        return Response(self.get_serializer(rule).data, status=status.HTTP_201_CREATED)


class PipelineNoticeViewSet(viewsets.GenericViewSet):
    """Stage rules' notices to the person asking, for Home. Each person sees
    their own and dismisses their own."""

    permission_classes = [crm_perms.IsTenantStaff]

    def get_queryset(self):
        from apps.crm.models import PipelineNotice

        return PipelineNotice.objects.filter(recipient=self.request.user,
                                             dismissed_at__isnull=True) \
            .select_related("contact", "pipeline")

    def list(self, request):
        return Response([{
            "id": str(n.pk), "text": n.text, "created_at": n.created_at.isoformat(),
            "contact": str(n.contact_id) if n.contact_id else None,
            "contact_name": f"{n.contact.first_name} {n.contact.last_name}".strip()
            if n.contact_id else "",
            "pipeline": n.pipeline.name if n.pipeline_id else "",
        } for n in self.get_queryset()[:50]])

    @action(detail=True, methods=["post"])
    def dismiss(self, request, pk=None):
        from django.utils import timezone

        notice = self.get_queryset().filter(pk=pk).first() if _is_uuid(str(pk)) else None
        if notice is None:
            raise Http404
        notice.dismissed_at = timezone.now()
        notice.save(update_fields=["dismissed_at", "updated_at"])
        return Response({"dismissed": True})


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
        # An invoice's message is the invoice's own: its words and its PDF
        # are frozen with it, and changed only by sending it back to draft.
        if message.producer == OutboxMessage.Producer.CLIENT_INVOICE:
            return False
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
        if message.producer == OutboxMessage.Producer.CLIENT_INVOICE:
            # Its words are the invoice's own, frozen with its PDF.
            return Response({"detail": "An invoice's email is changed on the invoice: "
                                       "send it back to draft there."}, status=409)
        if not self._editable(message):
            return Response(
                {"detail": f"This message is {message.get_state_display().lower()} and can no longer be edited."},
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

    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        """Development only — this message rendered exactly as it sends, from the
        same function delivery uses. `?part=text` shows the plain-text part. A
        one-time link shows its stored copy, which never holds the link."""
        from django.conf import settings
        from django.http import Http404, HttpResponse

        from apps.crm.services import email_layout

        if not settings.IS_LOCAL:
            raise Http404
        message = self.get_object()
        html, text = email_layout.for_delivery(message)
        if request.query_params.get("part") == "text":
            return HttpResponse(text, content_type="text/plain; charset=utf-8")
        # The logo embedded: a browser cannot resolve the cid: the send uses.
        html, _ = email_layout.with_logo(html, message.tenant, as_data_uri=True)
        return HttpResponse(html, content_type="text/html; charset=utf-8")

    @action(detail=True, methods=["post"], url_path="attachments")
    def add_attachment(self, request, pk=None):
        """FR-1.23b — add a file to a draft. Size-capped; PROTECTed once used."""
        message = self.get_object()
        if not self._editable(message):
            return Response(
                {"detail": f"This message is {message.get_state_display().lower()}; attachments are fixed."},
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
                {"detail": f"This message is {message.get_state_display().lower()}; attachments are fixed."},
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
                "candidates": crm_serializers.ContactSerializer(
                    candidates, many=True, context={"request": request}).data,
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
    """Matrix 3.13 — a VA may edit body copy; the FF creates and deletes.

    The library (owner, 2026-10-20): built-in templates are listed first and
    can be restored but not deleted; a template in use cannot be deleted
    either, and the refusal says where it is used. `uses` is which template
    each practice-wide email uses."""

    serializer_class = crm_serializers.EmailTemplateSerializer

    def get_queryset(self):
        from django.db.models import Case, IntegerField, Value, When

        from apps.crm.models import EmailTemplate

        return EmailTemplate.objects.annotate(
            builtin=Case(When(original="", then=Value(1)), default=Value(0),
                         output_field=IntegerField()),
        ).order_by("builtin", "name")

    def get_permissions(self):
        if self.request.method == "DELETE" or (
                self.request.method == "POST" and self.action in ("create", "uses")):
            return [crm_perms.IsTenantStaff(), crm_perms.IsFF()]
        return [crm_perms.IsTenantStaff()]

    def list(self, request, *args, **kwargs):
        from apps.crm import template_seed

        # A practice made before the library, or a test's, gets it on first
        # sight rather than an empty page.
        template_seed.seed_tenant(request.tenant)
        return super().list(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        from apps.crm.services import templates

        template = self.get_object()
        if template.original:
            return Response({"detail": "A built-in template can be changed or restored to "
                                       "its original, not deleted."}, status=409)
        used = templates.used_for(template)
        if used:
            return Response({"detail": "This template is in use: " + "; ".join(used)
                             + ". Choose another there first."}, status=409)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        from apps.crm.services import templates

        template = self.get_object()
        try:
            templates.restore(template, actor=request.user)
        except templates.TemplateRefused as refused:
            return Response({"detail": str(refused)}, status=400)
        return Response(self.get_serializer(template).data)

    @action(detail=False, methods=["get", "post"])
    def uses(self, request):
        """GET: {use: template id} for every use. POST {use, template}: choose."""
        from apps.crm import template_seed
        from apps.crm.models import EmailTemplate, EmailTemplateUse
        from apps.tenancy.models import AuditEvent

        template_seed.seed_tenant(request.tenant)
        if request.method == "POST":
            use = request.data.get("use")
            if use not in EmailTemplateUse.Use.values:
                return Response({"detail": "There is no such use."}, status=400)
            template_id = request.data.get("template")
            template = (EmailTemplate.objects.filter(pk=template_id).first()
                        if _is_uuid(template_id) else None)
            if template is None:
                return Response({"detail": "Choose one of the practice's templates."},
                                status=400)
            row = EmailTemplateUse.objects.get(use=use)
            row.template = template
            row.save(update_fields=["template", "updated_at"])
            AuditEvent.all_objects.create(
                tenant=request.tenant, actor=request.user, verb="email_template.use_chosen",
                target_type="email_template", target_id=template.pk, payload={"use": use})
        rows = EmailTemplateUse.objects.all()
        return Response({
            "uses": [{"use": row.use, "label": EmailTemplateUse.Use(row.use).label,
                      "template": str(row.template_id)} for row in rows],
        })


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
            # A thank-you to a referrer at each moment (owner, 2026-10-20).
            "thanks": {moment: getattr(tenant, field)
                       for moment, field in referrals.SETTING.items()},
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
    def thanks(self, request):
        """{"recorded": bool, "won": bool, "lost": bool}, any of them."""
        tenant = request.tenant
        changed = {}
        for moment, field in referrals.SETTING.items():
            if moment in request.data:
                value = request.data[moment]
                if not isinstance(value, bool):
                    raise ValidationError({moment: "On or off: true or false."})
                setattr(tenant, field, value)
                changed[moment] = value
        if changed:
            tenant.save(update_fields=[referrals.SETTING[m] for m in changed] + ["updated_at"])
            AuditEvent.all_objects.create(
                tenant=tenant, actor=request.user, verb="referral.thanks_settings",
                target_type="tenant", target_id=tenant.pk, payload=changed,
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
