"""Script controls on the card pages (docs/p16_card_page_scripts.md). The
platform's own records, not a practice's: no tenant on any of them."""

from __future__ import annotations

from django.db import models


class Mode(models.TextChoices):
    ENFORCE = "enforce", "Enforced"
    REPORT_ONLY = "report-only", "Report only"


class Setting(models.Model):
    """One row (pk 1): whether the pages' policies are enforced or only
    reported. The switch is `manage.py card_pages mode …`."""

    mode = models.CharField(max_length=12, choices=Mode.choices, default=Mode.ENFORCE)
    changed_at = models.DateTimeField(null=True, blank=True)
    changed_by = models.CharField(max_length=120, blank=True, default="")
    note = models.CharField(max_length=300, blank=True, default="")

    class Meta:
        db_table = "card_page_setting"


class Baseline(models.Model):
    """An approved state of the card pages: their security headers and every
    script on them, with a hash of each. The newest is the one in force."""

    approved_at = models.DateTimeField(auto_now_add=True)
    approved_by = models.CharField(max_length=120, blank=True, default="")
    note = models.CharField(max_length=300, blank=True, default="")
    #: Where the state was read: the public address of the server.
    base_url = models.CharField(max_length=200)
    state = models.JSONField()

    class Meta:
        db_table = "card_page_baseline"
        ordering = ["-approved_at"]


class Check(models.Model):
    """One look at the live card pages, compared with the approved state."""

    class Outcome(models.TextChoices):
        SAME = "same", "As approved"
        CHANGED = "changed", "Changed"
        NO_BASELINE = "no_baseline", "Nothing approved yet"
        ERROR = "error", "Could not be read"

    ran_at = models.DateTimeField(auto_now_add=True)
    base_url = models.CharField(max_length=200)
    outcome = models.CharField(max_length=12, choices=Outcome.choices)
    baseline = models.ForeignKey(Baseline, null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name="+")
    state = models.JSONField(null=True, blank=True)
    #: The differences, in words, one per line item.
    differences = models.JSONField(default=list, blank=True)
    #: What the differences come to, for "is this one new?".
    fingerprint = models.CharField(max_length=64, blank=True, default="")
    error = models.TextField(blank=True, default="")
    alerted = models.BooleanField(default=False)

    class Meta:
        db_table = "card_page_check"
        ordering = ["-ran_at"]


class Violation(models.Model):
    """One kind of policy violation a browser reported, counted. Nothing in
    it identifies the person: the page's path with tokens and ids masked, no
    query strings, no IP address."""

    fingerprint = models.CharField(max_length=64, unique=True)
    #: "card" or "bank": the policy the page was served with.
    policy = models.CharField(max_length=8, blank=True, default="")
    disposition = models.CharField(max_length=8, blank=True, default="")
    document = models.CharField(max_length=300)
    directive = models.CharField(max_length=60)
    blocked = models.CharField(max_length=300, blank=True, default="")
    source = models.CharField(max_length=300, blank=True, default="")
    line = models.PositiveIntegerField(null=True, blank=True)
    sample = models.CharField(max_length=80, blank=True, default="")
    user_agent = models.CharField(max_length=200, blank=True, default="")
    #: A browser extension's doing, or a block the inventory expects
    #: (`reports.EXPECTED`): kept, never alerted.
    noise = models.BooleanField(default=False)
    count = models.PositiveIntegerField(default=1)
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)
    alerted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "card_page_violation"
        ordering = ["-last_seen"]
