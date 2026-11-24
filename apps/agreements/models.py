"""Owner agreements (docs/p15_owner_agreements.md).

A client company's new property owner signs the company's rental management
agreement on a personal link, the company countersigns it, and the owner's
answers start the owner's intake (apps/intake). SkyRun Park City's alone,
switched on per company by `manage.py owner_agreements`.

What is kept where:

- `Program`: one per company with the feature; its sender and its signer.
- `StaffAccess`: who may do what for the company (agreements, signed PDFs,
  intake). It replaced intake's "Manager or above" rule (owner, 2026-11-23).
- `OwnerAgreement`: one per owner and property. Its link always opens the
  current version.
- `AgreementVersion`: the terms staff set, frozen once the owner signs.
- `AgreementSignature`: the owner's and the countersignature, with who
  applied it and under which authorization.
- `CountersignAuthority`: the signer's standing authorization; a new row for
  every change, none ever edited.
- `AgreementEvent` and `OwnerEmail`: written once, never changed.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.tenancy.models import TenantScopedModel


class Program(TenantScopedModel):
    """The company's owner agreements: on or off, the sender, the signer."""

    class Sender(models.TextChoices):
        TESTING = "testing", "ENHQ's own sender (testing)"
        DOMAIN = "domain", "Our own domain"

    company = models.OneToOneField("crm.Company", on_delete=models.CASCADE, related_name="+")
    enabled = models.BooleanField(default=False)
    #: Who "Michael LeClerc, President" is in ENHQ: the one person who may
    #: record the standing authorization, and who may always countersign.
    signer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                               on_delete=models.SET_NULL, related_name="+")
    sender = models.CharField(max_length=8, choices=Sender.choices, default=Sender.TESTING)
    #: Our own domain: the domain, the from-address on it, its name, the reply-to.
    sender_domain = models.CharField(max_length=200, blank=True, default="")
    from_address = models.EmailField(blank=True, default="")
    from_name = models.CharField(max_length=120, blank=True, default="")
    reply_to = models.EmailField(blank=True, default="")
    #: The last "Send a test to me" that worked, and the domain/from it proved.
    tested_at = models.DateTimeField(null=True, blank=True)
    tested_for = models.CharField(max_length=320, blank=True, default="")
    #: Owner emails pause on a sending failure until someone resumes them.
    paused_at = models.DateTimeField(null=True, blank=True)
    pause_reason = models.CharField(max_length=300, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "agreement_program"


class StaffAccess(TenantScopedModel):
    """One person's ticks for one company (owner, 2026-11-23)."""

    company = models.ForeignKey("crm.Company", on_delete=models.CASCADE, related_name="+")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    #: a. Owner agreements: create and send, see agreements and their documents.
    agreements = models.BooleanField(default=False)
    #: b. Receives signed agreement PDFs.
    signed_pdfs = models.BooleanField(default=False)
    #: c. Owner intake: review, edit and send to Track, and the team notices.
    intake = models.BooleanField(default=False)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "agreement_staff_access"
        constraints = [models.UniqueConstraint(fields=["company", "user"],
                                               name="agreement_staff_access_one")]


class OwnerAgreement(TenantScopedModel):
    """One owner and property: the link, the owner's details, the status."""

    company = models.ForeignKey("crm.Company", on_delete=models.CASCADE, related_name="+")
    number = models.PositiveIntegerField()
    template_key = models.CharField(max_length=40)
    #: As staff entered them: a name, and an email and/or a phone.
    owner_name = models.CharField(max_length=200)
    owner_email = models.EmailField(blank=True, default="")
    owner_phone = models.CharField(max_length=40, blank=True, default="")
    #: The link: only the hash of an HMAC token, re-made from `link_issued_at`.
    link_hash = models.CharField(max_length=64, blank=True, default="")
    link_issued_at = models.DateTimeField(null=True, blank=True)
    #: The owner's section, as the owner filled it in (page 8 of the 2014 PDF).
    details = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    last_activity_at = models.DateTimeField(null=True, blank=True)
    owner_signed_at = models.DateTimeField(null=True, blank=True)
    countersigned_at = models.DateTimeField(null=True, blank=True)
    #: The agreement's date: the day it was countersigned, in the practice's time.
    agreement_date = models.DateField(null=True, blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    #: "now" or "later", the owner's answer after signing.
    onboarding_choice = models.CharField(max_length=5, blank=True, default="")
    submission = models.OneToOneField("intake.Submission", null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name="owner_agreement")
    #: Reminders already sent: {"owner": [3, 7], "countersign": [1, 3], "form": [3]}.
    reminders = models.JSONField(default=dict, blank=True)
    owner_pdf = models.ForeignKey("tenancy.StoredFile", null=True, blank=True,
                                  on_delete=models.SET_NULL, related_name="+")
    owner_pdf_sha256 = models.CharField(max_length=64, blank=True, default="")
    final_pdf = models.ForeignKey("tenancy.StoredFile", null=True, blank=True,
                                  on_delete=models.SET_NULL, related_name="+")
    final_pdf_sha256 = models.CharField(max_length=64, blank=True, default="")

    class Meta(TenantScopedModel.Meta):
        db_table = "owner_agreement"
        constraints = [
            models.UniqueConstraint(fields=["company", "number"], name="owner_agreement_number"),
            models.UniqueConstraint(fields=["link_hash"], condition=~models.Q(link_hash=""),
                                    name="owner_agreement_one_link"),
        ]


class AgreementVersion(TenantScopedModel):
    """The terms staff set. A correction before the owner signs is a new
    version; the old one stays, marked replaced."""

    agreement = models.ForeignKey(OwnerAgreement, on_delete=models.CASCADE,
                                  related_name="versions")
    revision = models.PositiveIntegerField()
    template_key = models.CharField(max_length=40)
    template_version = models.CharField(max_length=40)
    template_sha256 = models.CharField(max_length=64)
    #: owner_percent, manager_percent, fees {period: {threshold, fee}},
    #: additional_items, property_address {street, unit, city, state, zip}.
    terms = models.JSONField(default=dict)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    replaced_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "owner_agreement_version"
        constraints = [models.UniqueConstraint(fields=["agreement", "revision"],
                                               name="owner_agreement_version_revision")]


class CountersignAuthority(TenantScopedModel):
    """The signer's standing authorization: their adopted signature, and the
    people who may apply it to new-owner agreements. Recorded by the signer,
    signed in as themselves. Changing it records a new row; withdrawing it
    ends it. Never edited."""

    class Method(models.TextChoices):
        TYPED = "typed", "Typed"
        DRAWN = "drawn", "Drawn"

    company = models.ForeignKey("crm.Company", on_delete=models.CASCADE, related_name="+")
    principal = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                  related_name="+")
    #: The full name of the signed-in account that recorded it, as it was that
    #: day (owner, 2026-11-24): the record prints this, never the template's.
    recorded_by_name = models.CharField(max_length=200, blank=True, default="",
                                        db_default="")
    #: The name in the agreement's signature block ("Michael LeClerc").
    principal_name = models.CharField(max_length=200)
    principal_title = models.CharField(max_length=120)
    method = models.CharField(max_length=6, choices=Method.choices)
    typed_text = models.CharField(max_length=200, blank=True, default="")
    drawn_png = models.BinaryField(null=True, blank=True)
    #: [{"user_id": "...", "name": "..."}], the names as they were that day.
    people = models.JSONField(default=list)
    wording_version = models.CharField(max_length=20)
    wording = models.TextField()
    recorded_at = models.DateTimeField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True, default="")
    #: Set when a newer authorization took its place, or it was withdrawn.
    ended_at = models.DateTimeField(null=True, blank=True)
    withdrawn = models.BooleanField(default=False)
    ended_ip = models.GenericIPAddressField(null=True, blank=True)
    ended_user_agent = models.CharField(max_length=500, blank=True, default="")

    class Meta(TenantScopedModel.Meta):
        db_table = "owner_agreement_authority"


class AgreementSignature(TenantScopedModel):
    """The owner's signature, or SkyRun's. SkyRun's records who pressed the
    button (`applied_by`) and, when that wasn't the signer, the authorization
    it was applied under: never as if the signer pressed it."""

    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        MANAGER = "manager", "Manager"

    agreement = models.ForeignKey(OwnerAgreement, on_delete=models.CASCADE,
                                  related_name="signatures")
    version = models.ForeignKey(AgreementVersion, on_delete=models.PROTECT, related_name="+")
    role = models.CharField(max_length=8, choices=Role.choices)
    printed_name = models.CharField(max_length=200)
    printed_title = models.CharField(max_length=120, blank=True, default="")
    method = models.CharField(max_length=6, choices=CountersignAuthority.Method.choices)
    typed_text = models.CharField(max_length=200, blank=True, default="")
    drawn_png = models.BinaryField(null=True, blank=True)
    consent_version = models.CharField(max_length=20)
    consent_text = models.TextField()
    signed_at = models.DateTimeField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True, default="")
    #: The SHA-256 of the agreement's words as the owner signed them (the
    #: date line left out: it is filled in on countersigning).
    text_sha256 = models.CharField(max_length=64)
    #: The owner's: those words, exactly, as one text (owner, 2026-11-24). Kept
    #: unchanged; its SHA-256 is `text_sha256` and the record's "Words signed".
    signed_text = models.TextField(blank=True, default="", db_default="")
    applied_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    applied_by_name = models.CharField(max_length=200, blank=True, default="")
    authority = models.ForeignKey(CountersignAuthority, null=True, blank=True,
                                  on_delete=models.PROTECT, related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "owner_agreement_signature"
        constraints = [models.UniqueConstraint(fields=["agreement", "role"],
                                               name="owner_agreement_signature_one_per_role")]


class AgreementEvent(TenantScopedModel):
    """Something that happened to an agreement. Written once."""

    agreement = models.ForeignKey(OwnerAgreement, on_delete=models.CASCADE,
                                  related_name="events")
    kind = models.CharField(max_length=24)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="+")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True, default="")
    detail = models.CharField(max_length=300, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "owner_agreement_event"
        ordering = ["created_at"]


class OwnerEmail(TenantScopedModel):
    """One email to an owner, by either sender. The body is not kept: it
    carries the owner's link."""

    class State(models.TextChoices):
        HELD = "held", "Held (sending paused)"
        SENT = "sent", "Sent"
        CAPTURED = "captured", "Kept on this computer (never sent)"
        FAILED = "failed", "Failed"

    company = models.ForeignKey("crm.Company", on_delete=models.CASCADE, related_name="+")
    agreement = models.ForeignKey(OwnerAgreement, null=True, blank=True,
                                  on_delete=models.CASCADE, related_name="emails")
    kind = models.CharField(max_length=24)
    to_address = models.EmailField()
    subject = models.CharField(max_length=300)
    sender = models.CharField(max_length=8, choices=Program.Sender.choices)
    state = models.CharField(max_length=8, choices=State.choices)
    provider_id = models.CharField(max_length=100, blank=True, default="")
    error = models.CharField(max_length=300, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "owner_agreement_email"
        ordering = ["created_at"]
