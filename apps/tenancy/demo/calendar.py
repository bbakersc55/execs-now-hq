"""The demo's calendar: the practice owner's, with today's and tomorrow's
meetings and a past one, made up like everything else (2026-10-27).

Matched the same way a real calendar is (`apps.calendars.sync.match`), from
the cast's own addresses, which are then dropped as a real sync drops them.
Nothing is connected: the demo never reads a calendar.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


def meetings(world) -> None:
    from apps.calendars.models import CalendarConnection, CalendarEvent, CalendarEventMatch
    from apps.calendars.sync import match
    from django.utils import timezone


    tenant = world.tenant
    zone = ZoneInfo(tenant.timezone or "America/Denver")
    connection = CalendarConnection.objects.create(
        tenant=tenant, user=world.owner, provider="google",
        email_address=world.owner.email, last_synced_at=timezone.now())
    clients = list(world.people)
    first_client = clients[0] if clients else None
    people = world.people.get(first_client, [])
    prospect = next(iter(world.prospects.values()), None)

    def at(day_offset, hour, minute=0):
        day = world.today + timedelta(days=day_offset)
        return datetime.combine(day, time(hour, minute), tzinfo=zone)

    def emails(*contacts):
        return [c.emails.first().address for c in contacts if c is not None]

    plan = [
        (0, 10, 0, 45, f"Weekly check-in, {first_client}", emails(*people[:2])),
        (0, 14, 30, 30, f"Intro call with {prospect.first_name} {prospect.last_name}"
         if prospect else "Intro call", emails(prospect)),
        (1, 9, 30, 60, f"Quarterly review prep, {first_client}", emails(*people[:1])),
        (1, 15, 0, 30, "Team planning", []),
        (-7, 11, 0, 60, f"Operations review, {first_client}", emails(*people[:3])),
    ]
    for index, (day, hour, minute, length, title, addresses) in enumerate(plan):
        starts = at(day, hour, minute)
        event = CalendarEvent.objects.create(
            tenant=tenant, connection=connection, provider_event_id=f"demo-event-{index}",
            title=title, starts_at=starts, ends_at=starts + timedelta(minutes=length),
            web_link="")
        contacts, companies = match(tenant, addresses)
        CalendarEventMatch.objects.bulk_create(
            [CalendarEventMatch(tenant=tenant, event=event, contact_id=c) for c in contacts]
            + [CalendarEventMatch(tenant=tenant, event=event, company_id=c) for c in companies])
