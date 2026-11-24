"""Intake forms (docs/p14_intake_forms.md).

One form type for now, "New owner and property": a client company's new
property owner fills it in on a personal link with no account, the company's
managers review it, and ENHQ writes it to the company's Track account.

What is kept where:

- Answers that are not sensitive live on the submission as JSON.
- The tax id, every access code and the Wi-Fi password live only in
  `SubmissionSecret`, encrypted, until Track confirms it has them; then the
  row is deleted, last four and all. A submission never sent loses them 90
  days after its last change, or at once when a manager discards it.
- Every reveal of a secret, and every copy of a link, is a `SubmissionEvent`,
  which is never changed after it is written.
"""

from __future__ import annotations

import hashlib
import secrets as pysecrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.tenancy.models import TenantScopedModel

#: A link is good for this long after the last thing anyone did with it.
LINK_LIFETIME = timedelta(days=30)
#: Secrets of a submission never sent are deleted this long after its last change.
SECRET_LIFETIME = timedelta(days=90)


class IntakeForm(TenantScopedModel):
    """A client company's form, with its own look, address and settings."""

    class Kind(models.TextChoices):
        NEW_OWNER = "new_owner_property", "New owner and property"

    company = models.ForeignKey("crm.Company", on_delete=models.CASCADE,
                                related_name="intake_forms")
    kind = models.CharField(max_length=32, choices=Kind.choices, default=Kind.NEW_OWNER)
    #: The page's title in the browser tab, and the heading on the welcome screen.
    title = models.CharField(max_length=120, default="New owner and property")
    #: Who the owner deals with, everywhere on the form ("SkyRun Park City").
    brand_name = models.CharField(max_length=120)
    #: In the address on ENHQ's host: /forms/<slug>/<token>.
    slug = models.SlugField(max_length=60, unique=True)
    #: The form's own host name ("owners.skyrunparkcity.com"); empty until set.
    domain = models.CharField(max_length=200, blank=True, default="", db_default="")
    logo = models.ForeignKey("tenancy.StoredFile", null=True, blank=True,
                             on_delete=models.SET_NULL, related_name="+")
    icon = models.ForeignKey("tenancy.StoredFile", null=True, blank=True,
                             on_delete=models.SET_NULL, related_name="+")
    #: primary, primary_dark, heading, text, background, accent, error.
    colors = models.JSONField(default=dict, blank=True)
    contact_phone = models.CharField(max_length=40, blank=True, default="")
    contact_email = models.EmailField(blank=True, default="")
    #: Everything else a manager sets: see `apps.intake.defaults.SETTING_KEYS`.
    settings = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "intake_form"
        constraints = [
            models.UniqueConstraint(fields=["company", "kind"], name="intake_form_one_per_kind"),
            models.UniqueConstraint(fields=["domain"], condition=~models.Q(domain=""),
                                    name="intake_form_domain_unique"),
        ]


class Submission(TenantScopedModel):
    """One owner's answers about one property, from the link to the send."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Link made, not opened"
        IN_PROGRESS = "in_progress", "Owner is filling it in"
        SUBMITTED = "submitted", "Submitted, waiting for review"
        SENDING = "sending", "Sending to Track"
        FAILED = "failed", "Send stopped part way"
        SENT = "sent", "Sent to Track"
        DISCARDED = "discarded", "Discarded"

    form = models.ForeignKey(IntakeForm, on_delete=models.CASCADE, related_name="submissions")
    company = models.ForeignKey("crm.Company", on_delete=models.CASCADE, related_name="+")
    #: Per company, from 1: "#42" in the list and in the onboarding project.
    number = models.PositiveIntegerField()
    token_hash = models.CharField(max_length=64, unique=True)
    #: The link's token, encrypted: staff copy the same link again for a
    #: reminder. Looked up only by its hash.
    token_ciphertext = models.BinaryField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT,
                              db_index=True)
    #: Who the manager started it for: shown to staff, prefilled for the owner.
    invite_first_name = models.CharField(max_length=80)
    invite_last_name = models.CharField(max_length=80, blank=True, default="")
    invite_email = models.EmailField(blank=True, default="")
    answers = models.JSONField(default=dict, blank=True)
    #: The reviewer's choices: area, contract, dates, overrides (`review.py`).
    staff = models.JSONField(default=dict, blank=True)
    #: Track's ids, step by step, saved the moment each is created.
    track = models.JSONField(default=dict, blank=True)
    #: The last pre-send look at Track (duplicates), and when.
    track_check = models.JSONField(default=dict, blank=True)
    checked_at = models.DateTimeField(null=True, blank=True)
    last_activity_at = models.DateTimeField(default=timezone.now)
    last_changed_at = models.DateTimeField(default=timezone.now)
    started_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    submitted_at = models.DateTimeField(null=True, blank=True)
    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="+")
    sent_at = models.DateTimeField(null=True, blank=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    discarded_at = models.DateTimeField(null=True, blank=True)
    discarded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name="+")
    #: "Add another property": the submission whose owner details were carried over.
    carried_from = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name="+")
    #: The onboarding project made after a successful send.
    project = models.ForeignKey("work.Project", null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "intake_submission"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["company", "number"],
                                    name="intake_submission_number_unique"),
        ]

    # ------------------------------------------------------------ the link
    @staticmethod
    def hash_token(raw: str) -> str:
        return hashlib.sha256((raw or "").encode()).hexdigest()

    @staticmethod
    def new_token() -> str:
        return pysecrets.token_urlsafe(32)

    @property
    def expires_at(self):
        return self.last_activity_at + LINK_LIFETIME

    @property
    def link_open(self) -> bool:
        """The owner's link answers: not discarded, not expired."""
        return self.discarded_at is None and timezone.now() < self.expires_at

    @property
    def owner_may_edit(self) -> bool:
        return self.link_open and self.status in (self.Status.DRAFT, self.Status.IN_PROGRESS)

    @property
    def locked(self) -> bool:
        return self.locked_at is not None


class SubmissionFile(TenantScopedModel):
    """A document the owner uploaded (the insurance declarations page)."""

    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="files")
    stored_file = models.ForeignKey("tenancy.StoredFile", on_delete=models.PROTECT,
                                    related_name="+")
    name = models.CharField(max_length=200)
    content_type = models.CharField(max_length=100)
    byte_size = models.BigIntegerField()
    uploaded_by_owner = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "intake_submission_file"
        ordering = ["created_at"]


class SubmissionSecret(TenantScopedModel):
    """One sensitive value, encrypted, until Track confirms it has it."""

    class Kind(models.TextChoices):
        TAX_ID = "tax_id", "Tax ID"
        WIFI_PASSWORD = "wifi_password", "Wi-Fi password"
        CODE = "code", "Access code"

    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="secrets")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    #: For a code: the slot it fills ("door", "owner_closet", "alarm", "extra-2").
    slot = models.CharField(max_length=24, blank=True, default="")
    ciphertext = models.BinaryField()
    #: The tax id's last four only; codes and the Wi-Fi password keep none.
    last4 = models.CharField(max_length=4, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "intake_submission_secret"
        constraints = [
            models.UniqueConstraint(fields=["submission", "kind", "slot"],
                                    name="intake_secret_one_per_slot"),
        ]


class SubmissionEvent(TenantScopedModel):
    """Something that happened to a submission, by whom, when. Written once."""

    class Kind(models.TextChoices):
        STARTED = "started", "Started"
        LINK_COPIED = "link_copied", "Link copied"
        MESSAGE_COPIED = "message_copied", "Message copied"
        EMAIL_OPENED = "email_opened", "Opened in email"
        REOPENED = "reopened", "Link reopened"
        SUBMITTED = "submitted", "Submitted"
        REVEALED = "revealed", "Secret revealed"
        SEND_STARTED = "send_started", "Send to Track started"
        SENT = "sent", "Sent to Track"
        SEND_FAILED = "send_failed", "Send stopped"
        DISCARDED = "discarded", "Discarded"
        SECRETS_DELETED = "secrets_deleted", "Sensitive values deleted"
        DATES = "dates", "Owner dates"

    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="+")
    #: Never a secret's value: which one, which link, what happened.
    detail = models.CharField(max_length=300, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "intake_submission_event"
        ordering = ["created_at"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("A submission's events are never changed.")
        super().save(*args, **kwargs)


class SendRun(TenantScopedModel):
    """One press of Send to Track (or "Try the rest again"), step by step."""

    class State(models.TextChoices):
        QUEUED = "queued", "Waiting for the worker"
        RUNNING = "running", "Sending"
        SUCCEEDED = "succeeded", "Done"
        FAILED = "failed", "Stopped"

    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="runs")
    state = models.CharField(max_length=12, choices=State.choices, default=State.QUEUED)
    started_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    #: [{key, label, state, detail, track_id}] in the order they run.
    steps = models.JSONField(default=list, blank=True)
    error = models.TextField(blank=True, default="")
    #: Test mode (owner, 2026-11-23): every check ran, each step shows "would
    #: send", nothing was written to Track and nothing changed in ENHQ.
    test = models.BooleanField(default=False, db_default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "intake_send_run"
        ordering = ["-created_at"]


class OwnerDate(TenantScopedModel):
    """A date range the owner wants held for their own stay. ENHQ holds it
    until the unit is bookable in Track, then places the block."""

    class State(models.TextChoices):
        HELD = "held", "Held in ENHQ"
        PLACED = "placed", "Placed in Track"
        REFUSED = "refused", "Track refused it"
        EXPIRED = "expired", "Passed before it could be placed"
        CANCELLED = "cancelled", "Cancelled"

    submission = models.ForeignKey(Submission, on_delete=models.CASCADE,
                                   related_name="owner_dates")
    start = models.DateField()
    end = models.DateField()
    state = models.CharField(max_length=12, choices=State.choices, default=State.HELD)
    block_id = models.CharField(max_length=40, blank=True, default="")
    #: Track's own words when it refused, or what happened, for the managers.
    message = models.CharField(max_length=500, blank=True, default="")
    placed_at = models.DateTimeField(null=True, blank=True)
    last_reminded_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "intake_owner_date"
        ordering = ["start"]


class TrackListSnapshot(TenantScopedModel):
    """The last copy of one of Track's lists for a company (bed types,
    amenities, …): the form reads from here, and still works if Track is down."""

    company = models.ForeignKey("crm.Company", on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=32)
    payload = models.JSONField(default=list, blank=True)
    fetched_at = models.DateTimeField(default=timezone.now)

    class Meta(TenantScopedModel.Meta):
        db_table = "intake_track_list"
        constraints = [
            models.UniqueConstraint(fields=["company", "kind"], name="intake_track_list_one"),
        ]
