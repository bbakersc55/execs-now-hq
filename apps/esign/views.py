"""E-signature's API (owner, 2026-10-29).

GET/POST         /api/document-templates/              Settings → Documents
PATCH/DELETE     /api/document-templates/<id>/
POST             /api/document-templates/<id>/restore/
GET              /api/document-templates/fields/       the merge fields
GET/POST         /api/documents/?company=<id>          a company's documents; make one
GET              /api/documents/<id>/
POST             /api/documents/preview/               a template's PDF, not kept
PATCH            /api/documents/<id>/fields/           a draft filled in again
POST             /api/documents/<id>/send/             {mailbox}: its email into the Outbox
POST             /api/documents/<id>/countersign/      {agreed, method, typed, drawn}
POST             /api/documents/<id>/void/             {reason}
GET              /api/documents/<id>/pdf/?which=       sent | signed | final
POST             /api/documents/<id>/demo-link/        the demo only
GET              /api/portal-documents/                a client's own company's
GET              /api/portal-documents/<id>/pdf/

Who: practice owners and associates (an associate for their assigned
companies) make, send, countersign and void; an assistant sees each
document's title, signer and state, and nothing in it; a client sees their
own company's, from Sent on, in the portal; nobody else anything.
"""

from __future__ import annotations

from django.http import Http404, HttpResponse
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.crm import permissions as crm_perms
from apps.crm.models import Company, Contact
from apps.esign import consent, services
from apps.esign.models import Document, DocumentTemplate
from apps.tenancy.models import CLIENT_ROLES, Role

SENDERS = (Role.FF, Role.CF)


class DocumentTemplateSerializer(serializers.ModelSerializer):
    is_original = serializers.SerializerMethodField()
    changed = serializers.SerializerMethodField()
    used_for = serializers.SerializerMethodField()
    fields_used = serializers.SerializerMethodField()

    class Meta:
        model = DocumentTemplate
        fields = ["id", "name", "title", "body", "original", "is_original", "changed",
                  "used_for", "fields_used", "updated_at"]
        read_only_fields = ["original", "updated_at"]

    def get_is_original(self, obj):
        return bool(obj.original)

    def get_changed(self, obj):
        return services.is_changed(obj)

    def get_used_for(self, obj):
        return services.used_for(obj)

    def get_fields_used(self, obj):
        return services.fields_used(obj)

    def validate(self, attrs):
        title = attrs.get("title", getattr(self.instance, "title", ""))
        body = attrs.get("body", getattr(self.instance, "body", ""))
        if not (title or "").strip():
            raise ValidationError({"title": "Give the document a title."})
        try:
            services.check_template(title, body)
        except services.DocumentRefused as refused:
            raise ValidationError({"body": str(refused)}) from None
        return attrs


class DocumentTemplateViewSet(viewsets.ModelViewSet):
    """Settings → Documents. Anyone in the practice may read the library (a
    document is made from it); the practice owner writes it, as the email
    templates, and never deletes a built-in or one in use."""

    serializer_class = DocumentTemplateSerializer
    permission_classes = [crm_perms.IsTenantStaff]
    http_method_names = ["get", "post", "patch", "delete"]

    def get_queryset(self):
        from django.db.models import Case, IntegerField, Value, When

        return DocumentTemplate.objects.annotate(
            builtin=Case(When(original="", then=Value(1)), default=Value(0),
                         output_field=IntegerField())).order_by("builtin", "name")

    def get_permissions(self):
        if self.request.method in ("POST", "PATCH", "DELETE"):
            return [crm_perms.IsTenantStaff(), crm_perms.IsFF()]
        return [crm_perms.IsTenantStaff()]

    def list(self, request, *args, **kwargs):
        from apps.esign import seed

        seed.seed_tenant(request.tenant)
        return super().list(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)

    def destroy(self, request, *args, **kwargs):
        template = self.get_object()
        if template.original:
            return Response({"detail": "A built-in template can be changed or restored to "
                                       "its original, not deleted."}, status=409)
        used = services.used_for(template)
        if used:
            return Response({"detail": "This template is in use: " + "; ".join(used)
                             + ". Choose another there first."}, status=409)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        template = self.get_object()
        try:
            services.restore(template, actor=request.user)
        except services.DocumentRefused as refused:
            return Response({"detail": str(refused)}, status=400)
        return Response(self.get_serializer(template).data)

    @action(detail=False, methods=["get"])
    def fields(self, request):
        return Response([{"field": f"{{{name}}}", "label": label}
                         for name, label in services.FIELDS])


# ------------------------------------------------------------- documents

def _when(value):
    return value.isoformat() if value else None


def represent(document, *, full: bool) -> dict:
    """A document for the company card. `full` is for those who send and
    countersign; an assistant gets its state and nothing in it."""
    out = {
        "id": str(document.pk), "title": document.title, "state": document.state,
        "state_label": document.get_state_display(),
        "signer": {"id": str(document.signer_id), "name": document.signer_name,
                   "email": document.signer_email},
        "sent_at": _when(document.sent_at), "viewed_at": _when(document.viewed_at),
        "signed_at": _when(document.signed_at), "declined_at": _when(document.declined_at),
        "countersigned_at": _when(document.countersigned_at),
        "completed_at": _when(document.completed_at), "voided_at": _when(document.voided_at),
        "expires_at": _when(document.expires_at), "created_at": _when(document.created_at),
    }
    if not full:
        return out
    message = document.request_message
    out.update({
        "source": document.source, "template": str(document.template_id or "") or None,
        "template_name": document.template.name if document.template_id else "",
        "fields": document.fields or {},
        "fields_used": services.fields_used(document.template) if document.template_id else [],
        "decline_reason": document.decline_reason, "void_reason": document.void_reason,
        "countersigned_by": (document.countersigned_by.full_name or document.countersigned_by.email)
        if document.countersigned_by_id else "",
        "request": {"id": str(message.pk), "state": message.state,
                    "state_label": message.get_state_display(), "from": message.from_address}
        if message is not None else None,
        "pdf_sha256": document.pdf_sha256, "final_sha256": document.final_sha256,
        "has_signed_pdf": bool(document.signed_pdf_id), "has_final_pdf": bool(document.final_pdf_id),
        "from_rule": bool(document.from_rule_id),
        # The line the countersigner ticks, exactly as it is kept.
        "countersign_consent": consent.countersign_wording(practice=document.tenant.name),
    })
    waiting = message is not None and message.state in ("draft", "pending_approval", "approved")
    out["can"] = {
        "send": document.state == Document.State.DRAFT and not waiting,
        "refill": document.state == Document.State.DRAFT and document.template_id is not None
        and (message is None or message.state in ("pending_approval", "rejected", "expired")),
        "countersign": document.state == Document.State.SIGNED,
        "void": document.state in services.VOIDABLE,
    }
    return out


def _bool(value) -> bool:
    return value is True or str(value).lower() in ("true", "1", "yes", "on")


class DocumentViewSet(viewsets.ViewSet):
    permission_classes = [crm_perms.IsTenantStaff]

    def _full(self) -> bool:
        return crm_perms.role_of(self.request) in SENDERS

    def _companies(self):
        return crm_perms.company_queryset_for(
            self.request, Company.objects.filter(deleted_at__isnull=True))

    def _documents(self):
        return Document.objects.filter(company__in=self._companies()).select_related(
            "template", "request_message", "countersigned_by", "signer")

    def _get(self, pk):
        document = self._documents().filter(pk=pk).first()
        if document is None:
            raise Http404
        return document

    def _sender_only(self):
        if not self._full():
            raise _Refused("Only the practice owner or an associate can do this.", 403)

    def list(self, request):
        rows = self._documents()
        company = request.query_params.get("company")
        if company:
            rows = rows.filter(company_id=company)
        full = self._full()
        return Response([represent(d, full=full) for d in rows.order_by("-created_at")])

    def retrieve(self, request, pk=None):
        return Response(represent(self._get(pk), full=self._full()))

    def _company_and_signer(self, data):
        company = self._companies().filter(pk=data.get("company")).first()
        if company is None:
            raise _Refused("That company is not available to you.", 404)
        signer = Contact.objects.filter(pk=data.get("signer"), company=company,
                                        deleted_at__isnull=True).first() \
            if data.get("signer") else None
        return company, signer

    def _template(self, data):
        template = DocumentTemplate.objects.filter(pk=data.get("template")).first() \
            if data.get("template") else None
        if template is None:
            raise _Refused("Choose a document template.")
        return template

    def create(self, request):
        """JSON {company, signer, template, fields}, or a form with {company,
        signer, title, file} for an uploaded PDF."""
        self._sender_only()
        data = request.data
        company, signer = self._company_and_signer(data)
        try:
            if "file" in request.FILES:
                upload = request.FILES["file"]
                if upload.size > services.pdfs.MAX_UPLOAD_BYTES:
                    raise services.DocumentRefused("The file is larger than 15 MB.")
                document = services.from_upload(company, signer, title=data.get("title", ""),
                                                content=upload.read(), actor=request.user)
            else:
                document = services.from_template(company, self._template(data), signer,
                                                  fields=data.get("fields") or {},
                                                  actor=request.user)
        except services.DocumentRefused as exc:
            raise _Refused(str(exc), exc.status) from None
        return Response(represent(document, full=True), status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"])
    def preview(self, request):
        self._sender_only()
        company, signer = self._company_and_signer(request.data)
        try:
            content = services.preview(company, self._template(request.data), signer,
                                       fields=request.data.get("fields") or {},
                                       actor=request.user)
        except services.DocumentRefused as exc:
            raise _Refused(str(exc), exc.status) from None
        return _pdf(content, "preview.pdf")

    @action(detail=True, methods=["patch"], url_path="fields")
    def refill(self, request, pk=None):
        self._sender_only()
        try:
            document = services.refill(self._get(pk), fields=request.data.get("fields") or {},
                                       actor=request.user)
        except services.DocumentRefused as exc:
            raise _Refused(str(exc), exc.status) from None
        return Response(represent(document, full=True))

    @action(detail=True, methods=["post"])
    def send(self, request, pk=None):
        from apps.crm.models import Mailbox

        self._sender_only()
        document = self._get(pk)
        mailbox = None
        if request.data.get("mailbox"):
            mailbox = Mailbox.objects.filter(pk=request.data["mailbox"]).first()
            if mailbox is None:
                raise _Refused("That mailbox is not this practice's.")
        try:
            services.queue_request(document, actor=request.user,
                                   role=crm_perms.role_of(request), mailbox=mailbox)
        except services.DocumentRefused as exc:
            raise _Refused(str(exc), exc.status) from None
        return Response(represent(self._get(pk), full=True))

    @action(detail=True, methods=["post"])
    def countersign(self, request, pk=None):
        from apps.accounts.ratelimit import client_ip
        from apps.crm.services.transport import TransportUnavailable

        self._sender_only()
        data = request.data
        try:
            document = services.countersign(
                self._get(pk), actor=request.user, method=data.get("method", ""),
                typed=data.get("typed", ""), drawn=data.get("drawn", ""),
                agreed=_bool(data.get("agreed")), ip=client_ip(request),
                user_agent=request.META.get("HTTP_USER_AGENT", ""))
        except services.DocumentRefused as exc:
            raise _Refused(str(exc), exc.status) from None
        except TransportUnavailable as exc:
            raise _Refused(f"Countersigned copy could not be emailed, so nothing was "
                           f"saved: {exc}", 503) from None
        return Response(represent(document, full=True))

    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        self._sender_only()
        try:
            document = services.void(self._get(pk), actor=request.user,
                                     reason=request.data.get("reason", ""))
        except services.DocumentRefused as exc:
            raise _Refused(str(exc), exc.status) from None
        return Response(represent(document, full=True))

    @action(detail=True, methods=["get"])
    def pdf(self, request, pk=None):
        self._sender_only()
        document = self._get(pk)
        which = request.query_params.get("which", "sent")
        stored = {"sent": document.pdf, "signed": document.signed_pdf,
                  "final": document.final_pdf}.get(which)
        if stored is None:
            raise Http404
        return _stored_pdf(stored, document.title, which)

    @action(detail=True, methods=["post"], url_path="demo-link")
    def demo_link(self, request, pk=None):
        self._sender_only()
        try:
            return Response({"url": services.demo_link(self._get(pk))})
        except services.DocumentRefused as exc:
            raise _Refused(str(exc), exc.status) from None


class PortalDocumentViewSet(viewsets.ViewSet):
    """A client owner's and a client team member's own company's documents,
    from Sent on: never a draft, never another company's."""

    permission_classes = [IsAuthenticated]
    SEEN = (Document.State.SENT, Document.State.VIEWED, Document.State.SIGNED,
            Document.State.DECLINED, Document.State.COUNTERSIGNED, Document.State.COMPLETE,
            Document.State.VOID, Document.State.EXPIRED)

    def _documents(self):
        membership = getattr(self.request, "membership", None)
        if membership is None or membership.role not in CLIENT_ROLES \
                or membership.client_company_id is None:
            raise Http404
        return Document.objects.filter(company_id=membership.client_company_id,
                                       state__in=self.SEEN)

    def list(self, request):
        return Response([{
            **represent(d, full=False),
            "has_pdf": bool(d.final_pdf_id or d.signed_pdf_id or d.pdf_id),
        } for d in self._documents().order_by("-sent_at", "-created_at")])

    @action(detail=True, methods=["get"])
    def pdf(self, request, pk=None):
        document = self._documents().filter(pk=pk).first()
        if document is None:
            raise Http404
        stored = document.final_pdf or document.signed_pdf or document.pdf
        return _stored_pdf(stored, document.title, "final" if document.final_pdf_id else "sent")


# ------------------------------------------------------------- helpers

class _Refused(APIException):
    """A refusal in words, with its status: {"detail": "..."}."""

    def __init__(self, message, status_code=400):
        super().__init__(detail=message)
        self.status_code = status_code


def _pdf(content: bytes, filename: str) -> HttpResponse:
    response = HttpResponse(content, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    response["Cache-Control"] = "no-store"
    return response


def _stored_pdf(stored, title, which):
    from apps.tenancy import storage

    try:
        content = storage.read(stored)
    except storage.StorageError as exc:
        return Response({"detail": f"The file could not be read just now: {exc}"}, status=503)
    return _pdf(content, services._filename(f"{title} {which}" if which != "sent" else title))
