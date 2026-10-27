"""Reading a connected calendar into the app, and matching its events.

**The window** is a day back to two weeks ahead, read whole every time (like
Gmail's threads and Graph's conversations), so a laptop shut for a week
catches up by the same call that keeps up. An event in the window the
calendar no longer has is removed; one that has passed stays, so a company's
page keeps its recent meetings.

**Matching** is by attendee address only, and the address is dropped once
matched: a contact holding it, and the contact's company; otherwise a
company by the address's domain, never the practice's own or a public mail
domain. A private or cancelled event is not kept at all.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.calendars import providers
from apps.calendars.models import CalendarConnection, CalendarEvent, CalendarEventMatch

BACK = timedelta(days=1)
AHEAD = timedelta(days=14)
#: Home reads the calendar again itself when the last read is older than this
#: (the worker reads it every fifteen minutes; the demo has no worker).
STALE = timedelta(minutes=30)
#: Never matched to a company by domain: anyone can hold an address there.
PUBLIC_DOMAINS = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com",
                  "yahoo.com", "icloud.com", "me.com", "aol.com", "proton.me",
                  "protonmail.com", "msn.com"}


def match(tenant, emails) -> tuple[set, set]:
    """(contact ids, company ids) for these addresses, in this practice."""
    from apps.crm.models import Company, CompanyDomain, ContactEmail
    from apps.tenancy.models import CLIENT_ROLES, Membership

    emails = {e.lower() for e in emails if e and "@" in e}
    if not emails:
        return set(), set()
    # The practice's own team; a client with portal access is still a client.
    staff = {e.lower() for e in Membership.all_objects.filter(
        tenant=tenant, revoked_at__isnull=True).exclude(role__in=CLIENT_ROLES)
        .values_list("user__email", flat=True)}
    emails -= staff
    contacts, companies, matched = set(), set(), set()
    for row in (ContactEmail.all_objects.filter(tenant=tenant, address__in=emails,
                                                contact__deleted_at__isnull=True)
                .values("address", "contact_id", "contact__company_id")):
        contacts.add(row["contact_id"])
        matched.add(row["address"].lower())
        if row["contact__company_id"]:
            companies.add(row["contact__company_id"])
    own = {(tenant.from_address or "").rsplit("@", 1)[-1].lower(),
           (tenant.domain or "").lower()} | {e.rsplit("@", 1)[-1] for e in staff}
    domains = {e.rsplit("@", 1)[-1] for e in emails - matched} - own - PUBLIC_DOMAINS - {""}
    if domains:
        companies |= set(CompanyDomain.all_objects.filter(
            tenant=tenant, domain__in=domains).values_list("company_id", flat=True))
    live = set(Company.all_objects.filter(tenant=tenant, pk__in=companies).values_list(
        "pk", flat=True)) if companies else set()
    return contacts, live


def sync(connection, *, now=None) -> dict:
    """Read the window and keep it. Returns counts; records an error on the
    connection rather than raising, so Home still shows what it had."""
    now = now or timezone.now()
    start, end = now - BACK, now + AHEAD
    try:
        events = providers.list_events(connection, start, end)
    except providers.CalendarUnavailable as exc:
        connection.last_error = str(exc)
        connection.save(update_fields=["last_error", "updated_at"])
        return {"error": str(exc)}
    kept = _keep(connection, events, start, end)
    connection.last_synced_at = now
    connection.last_error = ""
    connection.save(update_fields=["last_synced_at", "last_error", "updated_at"])
    return {"events": kept}


@transaction.atomic
def _keep(connection, events, start, end) -> int:
    tenant = connection.tenant
    seen = set()
    for item in events:
        if item["skip"] or not item["id"]:
            continue
        seen.add(item["id"])
        event, _ = CalendarEvent.all_objects.update_or_create(
            tenant=tenant, connection=connection, provider_event_id=item["id"][:512],
            defaults={"title": item["title"][:255], "starts_at": item["starts_at"],
                      "ends_at": item["ends_at"], "all_day": item["all_day"],
                      "web_link": item["web_link"]})
        contacts, companies = match(tenant, item["emails"])
        CalendarEventMatch.all_objects.filter(event=event).delete()
        CalendarEventMatch.all_objects.bulk_create(
            [CalendarEventMatch(tenant=tenant, event=event, contact_id=c) for c in contacts]
            + [CalendarEventMatch(tenant=tenant, event=event, company_id=c) for c in companies])
    # Gone from the calendar (or now private, or cancelled), within the window.
    CalendarEvent.all_objects.filter(connection=connection, starts_at__gte=start,
                                     starts_at__lt=end).exclude(
        provider_event_id__in=seen).delete()
    return len(seen)


def sync_if_stale(connection) -> None:
    from config import environment

    if environment.is_demo():
        return
    if connection.last_synced_at is None or timezone.now() - connection.last_synced_at > STALE:
        sync(connection)


def represent(event, *, contacts=None, companies=None) -> dict:
    matches = list(event.matches.all())
    return {
        "id": str(event.pk), "title": event.title, "starts_at": event.starts_at,
        "ends_at": event.ends_at, "all_day": event.all_day, "web_link": event.web_link,
        "contacts": [{"id": str(m.contact_id),
                      "name": f"{m.contact.first_name} {m.contact.last_name}".strip()}
                     for m in matches if m.contact_id
                     and (contacts is None or m.contact_id in contacts)],
        "companies": [{"id": str(m.company_id), "name": m.company.name}
                      for m in matches if m.company_id
                      and (companies is None or m.company_id in companies)],
    }


def connections_for_tenant(tenant):
    return CalendarConnection.all_objects.filter(tenant=tenant)
