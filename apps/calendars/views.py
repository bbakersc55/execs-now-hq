"""The calendar's API: one's own connection, Home's two days, a company's
meetings, and "Add to calendar".

**Who:** the practice's staff (practice owner, associates, assistants), each
for their own calendar. Clients never reach any of it. What one person sees
of another's calendar is a company's page: its meetings, by anyone in the
practice, only for a company that person may see, and only the contacts in
them that person may see.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings as dj_settings
from django.http import Http404, HttpResponseRedirect
from django.utils import timezone
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.calendars import providers, sync
from apps.calendars.models import (
    CalendarConnection, CalendarEntry, CalendarEvent, CalendarEventMatch,
)
from apps.crm import permissions as crm_perms
from apps.tenancy.models import AuditEvent, SecretKind

STAFF = ("FF", "CF", "VA")
ACTING = "While acting as someone, their calendar isn't yours to change."
RETURN = "/profile"


def _acting() -> bool:
    from apps.tenancy.context import get_acting

    return get_acting() is not None


def _refusal(tenant) -> str:
    from apps.tenancy.demo import visitors
    from config import environment

    if visitors.is_copy(tenant):
        return ("This is your own copy of the demo, so it connects no calendar. Home "
                "shows the demo's own meetings.")
    if environment.is_demo():
        return ("This is the demo. It connects no calendar; Home shows the demo's own "
                "meetings, made up like everything else here.")
    return ""


def provider_of(tenant) -> str:
    return "microsoft" if tenant.mail_provider == "microsoft" else "google"


def zone_of(request) -> ZoneInfo:
    name = getattr(request.user, "timezone", "") or request.tenant.timezone or "UTC"
    try:
        return ZoneInfo(name)
    except Exception:                                   # pragma: no cover - bad zone
        return ZoneInfo("UTC")


class IsStaff(permissions.BasePermission):
    message = "The calendar is the practice's team's."

    def has_permission(self, request, view):
        membership = getattr(request, "membership", None)
        return membership is not None and membership.role in STAFF


def _mine(request):
    return CalendarConnection.objects.filter(user=request.user).first()


def _status(request):
    tenant, mine = request.tenant, _mine(request)
    provider = provider_of(tenant)
    refusal = _refusal(tenant)
    if refusal:
        # The demo's meetings hang off a connection the seed made; it is not
        # anyone's calendar, so it is never shown as one, or offered to undo.
        mine = None
    return {
        "provider": provider,
        "provider_label": "Microsoft 365" if provider == "microsoft" else "Google Calendar",
        "configured": providers.configured(provider, tenant),
        "refusal": refusal,
        "connected": mine is not None,
        "email_address": mine.email_address if mine else "",
        "connected_provider": mine.provider if mine else "",
        "last_synced_at": mine.last_synced_at if mine else None,
        "last_error": mine.last_error if mine else "",
    }


class CalendarViewSet(viewsets.ViewSet):
    permission_classes = [crm_perms.IsTenantStaff, IsStaff]

    # ----------------------------------------------------------- connection

    def list(self, request):
        return Response(_status(request))

    @action(detail=False, methods=["post"])
    def start(self, request):
        tenant = request.tenant
        if _acting():
            return Response({"detail": ACTING}, status=403)
        if refusal := _refusal(tenant):
            return Response({"detail": refusal}, status=409)
        provider = provider_of(tenant)
        if not providers.configured(provider, tenant):
            return Response({"detail": (
                f"{'Microsoft 365' if provider == 'microsoft' else 'Google'} isn't set up "
                "on this server, so there is no calendar to connect. Contact support.")},
                status=400)
        state = providers.new_state()
        request.session[providers.STATE_KEY] = {"state": state, "provider": provider}
        return Response({"authorization_url": providers.consent_url(
            provider, tenant, state, login_hint=request.user.email)})

    @action(detail=False, methods=["post"])
    def sync(self, request):
        mine = _mine(request)
        if mine is None:
            return Response({"detail": "No calendar is connected."}, status=400)
        if refusal := _refusal(request.tenant):
            return Response({"detail": refusal}, status=409)
        sync.sync(mine)
        return Response(_status(request))

    @action(detail=False, methods=["post"])
    def disconnect(self, request):
        if _acting():
            return Response({"detail": ACTING}, status=403)
        if refusal := _refusal(request.tenant):
            return Response({"detail": refusal}, status=409)
        mine = _mine(request)
        if mine is None:
            return Response({"detail": "No calendar is connected."}, status=400)
        address = mine.email_address
        if mine.secret_id:
            mine.secret.delete()
        mine.delete()          # its kept events and their matches go with it
        AuditEvent.all_objects.create(
            tenant=request.tenant, actor=request.user, verb="calendar.disconnected",
            target_type="calendar_connection", target_id=None,
            payload={"email_address": address})
        return Response(_status(request))

    # ------------------------------------------------------------ reading

    @action(detail=False, methods=["get"])
    def upcoming(self, request):
        """Home: today's and tomorrow's meetings on one's own calendar, in
        one's own time zone, each with the contacts and companies it matched
        that one may see."""
        mine = _mine(request)
        zone = zone_of(request)
        today = timezone.now().astimezone(zone).date()
        if mine is not None:
            sync.sync_if_stale(mine)
            mine.refresh_from_db()
        start = datetime.combine(today, datetime.min.time(), tzinfo=zone)
        # A day either side, so an all-day event (its date at midnight UTC)
        # is in hand whatever the zone; each is placed on its day below.
        events = (CalendarEvent.objects.filter(
            connection__user=request.user, starts_at__gte=start - timedelta(days=1),
            starts_at__lt=start + timedelta(days=3))
            .prefetch_related("matches__contact", "matches__company").order_by("starts_at"))
        contacts, companies = _visible(request)
        days = []
        for offset, label in ((0, "Today"), (1, "Tomorrow")):
            day = today + timedelta(days=offset)
            days.append({"label": label, "date": day.isoformat(), "events": [
                sync.represent(e, contacts=contacts, companies=companies) for e in events
                if on_day(e, zone) == day]})
        return Response({**_status(request), "days": days, "time_zone": str(zone)})

    @action(detail=False, methods=["get"], url_path=r"company/(?P<company_id>[0-9a-f-]{36})")
    def company(self, request, company_id=None):
        """A company's meetings, on anyone's calendar in the practice: the
        last 30 days and the next 14."""
        from apps.crm.models import Company

        visible = crm_perms.company_queryset_for(
            request, Company.objects.filter(deleted_at__isnull=True))
        if not visible.filter(pk=company_id).exists():
            raise Http404
        now = timezone.now()
        events = (CalendarEvent.objects.filter(
            matches__company_id=company_id, starts_at__gte=now - timedelta(days=30),
            starts_at__lt=now + sync.AHEAD).distinct()
            .select_related("connection__user")
            .prefetch_related("matches__contact", "matches__company").order_by("starts_at"))
        contacts, companies = _visible(request)
        return Response([{**sync.represent(e, contacts=contacts, companies=companies),
                          "on_calendar_of": e.connection.user.full_name or e.connection.user.email,
                          "past": e.ends_at < now} for e in events])

    # ------------------------------------------------------- adding events

    @action(detail=False, methods=["post"])
    def add(self, request):
        """"Add to calendar": a task, a follow-up step, or a stage rule's
        event, at the day and time the person picked, on their own calendar."""
        if _acting():
            return Response({"detail": ACTING}, status=403)
        if refusal := _refusal(request.tenant):
            return Response({"detail": refusal}, status=409)
        mine = _mine(request)
        if mine is None:
            return Response({"detail": "Connect your calendar first, on your Profile."},
                            status=409)
        data = request.data
        source = str(data.get("source") or "")
        if source not in CalendarEntry.Source.values:
            return Response({"detail": "Say what the event is for."}, status=400)
        try:
            found = _source(request, source, str(data.get("source_id") or ""))
        except Http404:
            return Response({"detail": "Not found."}, status=404)
        zone = zone_of(request)
        try:
            day = datetime.fromisoformat(str(data.get("date") or ""))
            hour, minute = (int(x) for x in str(data.get("time") or "09:00").split(":")[:2])
            starts_at = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone)
        except (TypeError, ValueError):
            return Response({"detail": "Give a day and a time."}, status=400)
        try:
            minutes = max(5, min(int(data.get("minutes") or 30), 480))
        except (TypeError, ValueError):
            minutes = 30
        title = (str(data.get("title") or "").strip() or found["title"])[:255]
        link = f"{dj_settings.APP_ROOT_URL.rstrip('/')}{found['path']}"
        try:
            made = providers.create_event(mine, title=title, starts_at=starts_at,
                                          minutes=minutes, tz_name=str(zone),
                                          note=f"From {request.tenant.name}: {link}")
        except providers.CalendarUnavailable as exc:
            return Response({"detail": str(exc)}, status=502)
        entry = CalendarEntry.objects.create(
            tenant=request.tenant, connection=mine, created_by=request.user,
            source_type=source, source_id=found["id"], contact_id=found.get("contact"),
            provider_event_id=made["id"][:512], title=title, starts_at=starts_at,
            minutes=minutes, web_link=made["web_link"])
        AuditEvent.all_objects.create(
            tenant=request.tenant, actor=request.user, verb="calendar.event_added",
            target_type=source, target_id=found["id"],
            payload={"title": title, "starts_at": starts_at.isoformat(), "minutes": minutes})
        return Response({"id": str(entry.pk), "title": title, "starts_at": starts_at,
                         "minutes": minutes, "web_link": made["web_link"]}, status=201)


def on_day(event, zone):
    """The day an event is on, for the person reading: an all-day event's
    own date (kept as midnight UTC), any other in their zone."""
    from datetime import timezone as dt_timezone

    if event.all_day:
        return event.starts_at.astimezone(dt_timezone.utc).date()
    return event.starts_at.astimezone(zone).date()


def _visible(request):
    from apps.crm.models import Company, Contact

    contacts = set(crm_perms.contact_queryset_for(
        request, Contact.objects.filter(deleted_at__isnull=True)).values_list("pk", flat=True))
    companies = set(crm_perms.company_queryset_for(
        request, Company.objects.filter(deleted_at__isnull=True)).values_list("pk", flat=True))
    return contacts, companies


def _source(request, source: str, source_id: str) -> dict:
    """What the event is for, if this person may see it: {id, title, path,
    contact}. 404 for anything else, as everywhere."""
    import uuid

    try:
        pk = uuid.UUID(source_id)
    except ValueError:
        raise Http404
    if source == CalendarEntry.Source.TASK:
        from apps.work import permissions as work_perms
        from apps.work.models import Task

        task = work_perms.task_queryset_for(
            request, Task.objects.filter(deleted_at__isnull=True)).filter(pk=pk).first()
        if task is None:
            raise Http404
        return {"id": task.pk, "title": task.title, "path": f"/tasks/{task.pk}"}
    from apps.crm.models import Contact, FollowUpRun, StageAutomation

    visible = crm_perms.contact_queryset_for(request, Contact.objects.filter(
        deleted_at__isnull=True))
    if source == CalendarEntry.Source.FOLLOW_UP:
        run = FollowUpRun.objects.filter(pk=pk, contact__in=visible).select_related(
            "contact", "stage").first()
        if run is None:
            raise Http404
        name = f"{run.contact.first_name} {run.contact.last_name}".strip()
        return {"id": run.pk, "contact": run.contact_id, "path": f"/contacts/{run.contact_id}",
                "title": f"Follow up with {name} ({run.stage.label})"}
    rule = StageAutomation.objects.filter(
        pk=pk, action_type=StageAutomation.Action.CALENDAR_EVENT, is_active=True).first()
    contact = visible.filter(pk=request.data.get("contact")).first() \
        if _is_uuid(request.data.get("contact")) else None
    if rule is None or contact is None:
        raise Http404
    from apps.crm.services import stage_rules

    return {"id": rule.pk, "contact": contact.pk, "path": f"/contacts/{contact.pk}",
            "title": stage_rules.merged(rule.task_title_template, contact, rule) or "Follow up"}


def _is_uuid(value) -> bool:
    import uuid

    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, TypeError):
        return False


# ----------------------------------------------------------------- callbacks

def is_calendar_consent(request) -> bool:
    """Whether this redirect answers a calendar consent this browser started
    (Google's comes back to Gmail's callback, Microsoft's to the mail
    connection's, so neither registration gains a redirect URI)."""
    started = request.session.get(providers.STATE_KEY) or {}
    return bool(started.get("state")) and request.GET.get("state") == started.get("state")


def callback(request):
    """The consent's answer: the calendar connection, or why not."""
    from apps.crm.services import secrets

    started = request.session.pop(providers.STATE_KEY, None) or {}
    provider = started.get("provider") or "google"
    root = dj_settings.APP_ROOT_URL.rstrip("/")

    def back(**params):
        from urllib.parse import urlencode

        return HttpResponseRedirect(f"{root}{RETURN}?{urlencode(params)}")

    membership = getattr(request, "membership", None)
    if membership is None or membership.role not in STAFF:
        return back(calendar_error="You are not signed in as the practice's team, so no "
                                   "calendar was connected.")
    tenant = membership.tenant
    if refusal := _refusal(tenant):
        return back(calendar_error=refusal)
    if request.GET.get("error") or not request.GET.get("code"):
        return back(calendar_error="The calendar was not connected: the consent did not "
                                   "complete. Nothing was stored.")
    try:
        tokens, address = providers.exchange(provider, tenant, request.GET["code"])
    except providers.CalendarUnavailable as exc:
        return back(calendar_error=str(exc))
    if not providers.granted(provider, tokens):
        return back(calendar_error="Consent was given without access to your calendar. "
                                   "Nothing was stored. Connect again and allow it.")
    secret = secrets.write_secret(tenant=tenant, kind=SecretKind.CALENDAR_REFRESH,
                                  value=tokens["refresh_token"], user=request.user)
    connection, _ = CalendarConnection.all_objects.update_or_create(
        tenant=tenant, user=request.user,
        defaults={"provider": provider, "email_address": address, "secret": secret,
                  "scopes": providers.scopes_of(provider, tokens), "last_error": "",
                  "last_synced_at": None})
    AuditEvent.all_objects.create(
        tenant=tenant, actor=request.user, verb="calendar.connected",
        target_type="calendar_connection", target_id=connection.pk,
        payload={"email_address": address, "provider": provider})
    sync.sync(connection)
    return back(calendar_connected=address)
