"""E-signature, version one (owner, 2026-10-29; `docs/p6_esign.md`).

A **document** is one PDF sent to one client signer and countersigned by
someone in the practice: a proposal or an engagement letter made from a
**document template**, or any PDF uploaded. Its life:

    Draft → Sent → Viewed → Signed or Declined → Countersigned → Complete

and Void (the practice withdraws it) or Expired (30 days after it was sent,
unsigned). Each signature is a **signature** row: who, when, from where, by
which consent wording, and the SHA-256 of the exact PDF they signed.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.tenancy.models import TenantScopedModel


class DocumentTemplate(TenantScopedModel):
    """Settings → Documents: plain text with merge fields, like an email
    template, rendered into a PDF. `original` names a built-in one
    (`apps/esign/seed.py`), which "Restore the original" puts back."""

    name = models.CharField(max_length=120)
    #: The heading on the document's first page.
    title = models.CharField(max_length=160)
    body = models.TextField()
    original = models.CharField(max_length=40, blank=True, default="", db_default="")

    class Meta(TenantScopedModel.Meta):
        db_table = "document_template"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "original"], condition=~models.Q(original=""),
                name="document_template_one_original_each"),
        ]


class Document(TenantScopedModel):
    class State(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENT = "sent", "Sent"
        VIEWED = "viewed", "Viewed"
        SIGNED = "signed", "Signed"
        DECLINED = "declined", "Declined"
        COUNTERSIGNED = "countersigned", "Countersigned"
        COMPLETE = "complete", "Complete"
        VOID = "void", "Void"
        EXPIRED = "expired", "Expired"

    class Source(models.TextChoices):
        TEMPLATE = "template", "From a template"
        UPLOAD = "upload", "An uploaded PDF"

    company = models.ForeignKey("crm.Company", on_delete=models.PROTECT, related_name="documents")
    title = models.CharField(max_length=160)
    source = models.CharField(max_length=10, choices=Source.choices)
    template = models.ForeignKey(DocumentTemplate, null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="documents")
    #: What the template's fields were filled with: {"Scope": "...", ...}.
    fields = models.JSONField(default=dict, blank=True)
    state = models.CharField(max_length=14, choices=State.choices, default=State.DRAFT,
                             db_default=State.DRAFT, db_index=True)

    #: The PDF as sent: what the signer sees, and what its hash is of.
    pdf = models.ForeignKey("tenancy.StoredFile", null=True, blank=True,
                            on_delete=models.PROTECT, related_name="+")
    pdf_sha256 = models.CharField(max_length=64, blank=True, default="", db_default="")
    #: The PDF with the signature page, once signed; then countersigned (final).
    signed_pdf = models.ForeignKey("tenancy.StoredFile", null=True, blank=True,
                                   on_delete=models.PROTECT, related_name="+")
    final_pdf = models.ForeignKey("tenancy.StoredFile", null=True, blank=True,
                                  on_delete=models.PROTECT, related_name="+")
    final_sha256 = models.CharField(max_length=64, blank=True, default="", db_default="")

    signer = models.ForeignKey("crm.Contact", on_delete=models.PROTECT, related_name="documents")
    signer_name = models.CharField(max_length=200)
    signer_email = models.EmailField()
    mailbox = models.ForeignKey("crm.Mailbox", null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="+")
    #: The email that carries the link, in the Outbox until approved.
    request_message = models.ForeignKey("crm.OutboxMessage", null=True, blank=True,
                                        on_delete=models.SET_NULL, related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    #: A stage rule that made it, if one did.
    from_rule = models.ForeignKey("crm.StageAutomation", null=True, blank=True,
                                  on_delete=models.SET_NULL, related_name="+")

    #: The signing link: only its hash is kept. The token is an HMAC of the
    #: document and this moment (`links.py`), cleared once it is used.
    link_issued_at = models.DateTimeField(null=True, blank=True)
    link_hash = models.CharField(max_length=64, blank=True, default="", db_default="")

    sent_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    reminded_at = models.DateTimeField(null=True, blank=True)
    viewed_at = models.DateTimeField(null=True, blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    declined_at = models.DateTimeField(null=True, blank=True)
    decline_reason = models.TextField(blank=True, default="", db_default="")
    countersigned_at = models.DateTimeField(null=True, blank=True)
    countersigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                         on_delete=models.SET_NULL, related_name="+")
    completed_at = models.DateTimeField(null=True, blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                  on_delete=models.SET_NULL, related_name="+")
    void_reason = models.TextField(blank=True, default="", db_default="")

    class Meta(TenantScopedModel.Meta):
        db_table = "document"
        indexes = [models.Index(fields=["tenant", "company", "-created_at"])]
        constraints = [
            # A token that finds two documents is a security bug, not a collision.
            models.UniqueConstraint(fields=["link_hash"], condition=~models.Q(link_hash=""),
                                    name="document_one_live_link"),
        ]


class Signature(TenantScopedModel):
    """One signature on one document: the signer's, or the countersignature."""

    class Role(models.TextChoices):
        SIGNER = "signer", "Signer"
        COUNTERSIGNER = "countersigner", "Countersigner"

    class Method(models.TextChoices):
        TYPED = "typed", "Typed"
        DRAWN = "drawn", "Drawn"

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="signatures")
    role = models.CharField(max_length=14, choices=Role.choices)
    name = models.CharField(max_length=200)
    email = models.EmailField()
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                             on_delete=models.SET_NULL, related_name="+")
    method = models.CharField(max_length=6, choices=Method.choices)
    #: Typed: the name as typed, drawn in the cursive face. Drawn: the PNG.
    typed_text = models.CharField(max_length=200, blank=True, default="", db_default="")
    drawn_png = models.BinaryField(null=True, blank=True)
    #: Which consent wording they ticked (`consent.VERSIONS`), and its words.
    consent_version = models.CharField(max_length=20)
    consent_text = models.TextField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True, default="", db_default="")
    signed_at = models.DateTimeField()
    #: The SHA-256 of the exact PDF in front of them when they signed.
    pdf_sha256 = models.CharField(max_length=64)

    class Meta(TenantScopedModel.Meta):
        db_table = "document_signature"
        constraints = [
            models.UniqueConstraint(fields=["document", "role"],
                                    name="document_signature_one_per_role"),
        ]
