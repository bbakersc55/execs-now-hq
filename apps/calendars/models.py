"""A practice user's calendar (owner, 2026-10-27; post-beta list).

**One calendar per user**: their own, on the practice's provider (Google
Calendar through the practice's Google client, or Microsoft 365 through
Graph). What is kept of an event is what the screens show: its title, when,
and the link to open it. **Never its body or description**, which is not even
fetched, and never attendees' addresses: they are read once, to match the
practice's contacts and companies, and only the matches are kept.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.tenancy.models import TenantScopedModel


class CalendarConnection(TenantScopedModel):
    class Provider(models.TextChoices):
        GOOGLE = "google", "Google Calendar"
        MICROSOFT = "microsoft", "Microsoft 365"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="calendar_connections")
    provider = models.CharField(max_length=12, choices=Provider.choices)
    email_address = models.EmailField()
    scopes = models.JSONField(default=list, blank=True)
    secret = models.ForeignKey("tenancy.TenantSecret", null=True, blank=True,
                               on_delete=models.SET_NULL, related_name="+")
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")

    class Meta(TenantScopedModel.Meta):
        db_table = "calendar_connection"
        constraints = [models.UniqueConstraint(fields=["tenant", "user"],
                                               name="calendar_one_per_user")]


class CalendarEvent(TenantScopedModel):
    """One event on a connected calendar, from a day ago to two weeks ahead,
    kept after it passes so a company's page shows its recent meetings."""

    connection = models.ForeignKey(CalendarConnection, on_delete=models.CASCADE,
                                   related_name="events")
    provider_event_id = models.CharField(max_length=512)
    title = models.CharField(max_length=255, blank=True, default="")
    starts_at = models.DateTimeField(db_index=True)
    ends_at = models.DateTimeField()
    all_day = models.BooleanField(default=False)
    web_link = models.TextField(blank=True, default="")

    class Meta(TenantScopedModel.Meta):
        db_table = "calendar_event"
        constraints = [models.UniqueConstraint(fields=["connection", "provider_event_id"],
                                               name="calendar_event_once")]


class CalendarEventMatch(TenantScopedModel):
    """A contact, or a company, an event's attendees matched. The address
    that matched is not kept."""

    event = models.ForeignKey(CalendarEvent, on_delete=models.CASCADE, related_name="matches")
    contact = models.ForeignKey("crm.Contact", null=True, blank=True,
                                on_delete=models.CASCADE, related_name="+")
    company = models.ForeignKey("crm.Company", null=True, blank=True,
                                on_delete=models.CASCADE, related_name="+")

    class Meta(TenantScopedModel.Meta):
        db_table = "calendar_event_match"
        indexes = [models.Index(fields=["tenant", "company"], name="calendar_match_company")]


class CalendarEntry(TenantScopedModel):
    """An event the app put on someone's calendar: "Add to calendar" on a
    task or a follow-up step, or a stage rule's calendar event."""

    class Source(models.TextChoices):
        TASK = "task", "A task"
        FOLLOW_UP = "follow_up", "A follow-up step"
        STAGE_RULE = "stage_rule", "A stage rule"

    connection = models.ForeignKey(CalendarConnection, null=True, on_delete=models.SET_NULL,
                                   related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True,
                                   on_delete=models.SET_NULL, related_name="+")
    source_type = models.CharField(max_length=12, choices=Source.choices)
    source_id = models.UUIDField()
    contact = models.ForeignKey("crm.Contact", null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="+")
    provider_event_id = models.CharField(max_length=512)
    title = models.CharField(max_length=255)
    starts_at = models.DateTimeField()
    minutes = models.PositiveSmallIntegerField(default=30)
    web_link = models.TextField(blank=True, default="")

    class Meta(TenantScopedModel.Meta):
        db_table = "calendar_entry"
        indexes = [models.Index(fields=["tenant", "source_type", "source_id"],
                                name="calendar_entry_source")]
