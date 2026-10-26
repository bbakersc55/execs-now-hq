"""The Notices list, and browser notifications from it (owner, 2026-10-26).

**The Notices list is the source of truth.** Everything that tells a person
something lands here first: a stage rule's notice, a client-facing message, a
reading waiting on them, a mention. A browser notification is sent only for a
row of this table, to that person's own browsers in that practice, and only
for the kinds they have switched on; so nothing ever arrives in a browser that
is not also in the list.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.tenancy.models import TenantScopedModel


class Kind(models.TextChoices):
    NOTICE = "notice", "Notices from the pipeline's stage rules"
    CLIENT_MESSAGE = "client_message", "A message on work you share with the client"
    READING = "reading", "A scorecard reading waiting on you"
    MENTION = "mention", "Someone mentions you in a comment"


class Notice(TenantScopedModel):
    """One thing one person is told, in one practice."""

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                  related_name="+")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    title = models.CharField(max_length=120)
    text = models.CharField(max_length=500)
    #: Where it opens in the app: a path, never another site.
    url = models.CharField(max_length=200, blank=True, default="", db_default="")
    #: What it is about, so the same thing is not told twice.
    source_type = models.CharField(max_length=40, blank=True, default="", db_default="")
    source_id = models.UUIDField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    #: When a browser notification went for it, if one did.
    pushed_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "notice"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["tenant", "recipient", "-created_at"])]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "recipient", "kind", "source_type", "source_id"],
                condition=Q(source_id__isnull=False), name="notice_once_per_source"),
        ]


class PushSubscription(TenantScopedModel):
    """One browser's Web Push subscription, for one person in one practice.
    **One per browser:** its endpoint is the browser's, so subscribing again
    from the same browser, as anyone, replaces the row rather than adding one."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="+")
    endpoint = models.TextField()
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    user_agent = models.CharField(max_length=300, blank=True, default="", db_default="")
    last_sent_at = models.DateTimeField(null=True, blank=True)
    failures = models.PositiveSmallIntegerField(default=0, db_default=0)

    class Meta(TenantScopedModel.Meta):
        db_table = "push_subscription"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "endpoint"], name="push_one_per_browser"),
        ]


class PushPreference(TenantScopedModel):
    """Which kinds one person wants in their browser, in one practice. Every
    kind is optional; turning notifications on starts with all of theirs."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="+")
    kinds = models.JSONField(default=list, blank=True)

    class Meta(TenantScopedModel.Meta):
        db_table = "push_preference"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "user"], name="push_preference_once"),
        ]
