"""Google Calendar and Microsoft 365's calendar, at their boundary.

Thin on purpose, like the mail transports: consent, a token, a listing of
events in a window, and creating one. Everything that decides anything (what
is kept, what matches) is in `sync.py`.

**What is asked for, and nothing more.** Google: `calendar.events` (read and
write events, no calendar settings, no sharing). Microsoft:
`Calendars.ReadWrite`. **What is read of an event** is named field by field
in each listing (`GOOGLE_FIELDS`, `GRAPH_SELECT`): its id, title, times,
link, whether it is cancelled or private, and attendees' addresses for
matching. Never the description or body, so it cannot reach a prompt.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone as dt_timezone
from urllib.parse import urlencode

import requests
from django.conf import settings

from apps.crm.services import gmail_oauth, microsoft_oauth

GOOGLE_API = "https://www.googleapis.com/calendar/v3"
GOOGLE_SCOPES = ["openid", "email", "https://www.googleapis.com/auth/calendar.events"]
#: What Google returns of each event: no `description`, no `attachments`.
GOOGLE_FIELDS = ("nextPageToken,items(id,status,summary,start,end,htmlLink,visibility,"
                 "attendees(email,self),organizer(email,self))")
MICROSOFT_SCOPES = ["openid", "email", "profile", "offline_access", "User.Read",
                    "Calendars.ReadWrite"]
#: What Graph returns of each event: no `body`, no `bodyPreview`.
GRAPH_SELECT = ("id,subject,start,end,isAllDay,isCancelled,sensitivity,webLink,"
                "attendees,organizer")
MAX_PAGES = 10

STATE_KEY = "enhq_calendar_state"


class CalendarUnavailable(Exception):
    """The calendar could not be reached or refused. Said, never swallowed."""


# ------------------------------------------------------------------ consent

def new_state() -> str:
    return secrets.token_urlsafe(24)


def configured(provider: str, tenant) -> bool:
    if provider == "microsoft":
        return microsoft_oauth.is_configured()
    return gmail_oauth.is_configured(tenant)


def consent_url(provider: str, tenant, state: str, *, login_hint: str = "") -> str:
    """Each through the redirect URI its client already has: Gmail's for
    Google, the mail connection's for Microsoft. Told apart there by state."""
    if provider == "microsoft":
        params = {"client_id": settings.MICROSOFT_CLIENT_ID, "response_type": "code",
                  "redirect_uri": microsoft_oauth.redirect_uri(), "response_mode": "query",
                  "scope": " ".join(MICROSOFT_SCOPES), "state": state,
                  "prompt": "select_account"}
        if login_hint:
            params["login_hint"] = login_hint
        return (f"{microsoft_oauth.LOGIN}/{microsoft_oauth.authority()}/oauth2/v2.0/authorize?"
                + urlencode(params))
    params = {"client_id": gmail_oauth.client_for(tenant)[0],
              "redirect_uri": gmail_oauth.redirect_uri(), "response_type": "code",
              "scope": " ".join(GOOGLE_SCOPES), "access_type": "offline",
              "prompt": "select_account consent", "state": state}
    if login_hint:
        params["login_hint"] = login_hint
    return f"{gmail_oauth.AUTH_URL}?{urlencode(params)}"


def exchange(provider: str, tenant, code: str) -> tuple[dict, str]:
    """The code for tokens, and the account's address."""
    if provider == "microsoft":
        try:
            tokens = microsoft_oauth.exchange_code(code, scopes=MICROSOFT_SCOPES)
        except microsoft_oauth.MicrosoftOAuthError as exc:
            raise CalendarUnavailable(str(exc)) from exc
        if not tokens.get("refresh_token"):
            raise CalendarUnavailable("Microsoft returned no refresh token. Connect again.")
        try:
            return tokens, microsoft_oauth.account(tokens["access_token"])
        except microsoft_oauth.MicrosoftOAuthError as exc:
            raise CalendarUnavailable(str(exc)) from exc
    try:
        tokens = gmail_oauth.exchange_code(code, tenant=tenant)
        return tokens, gmail_oauth.account_email(tokens["access_token"])
    except gmail_oauth.GmailOAuthError as exc:
        raise CalendarUnavailable(str(exc)) from exc


def granted(provider: str, tokens: dict) -> bool:
    scopes = (tokens.get("scope") or "").split()
    if provider == "microsoft":
        return microsoft_oauth.holds(scopes, ["Calendars.ReadWrite"])
    return GOOGLE_SCOPES[-1] in scopes


def scopes_of(provider: str, tokens: dict) -> list[str]:
    if provider == "microsoft":
        return microsoft_oauth.granted_scopes(tokens)
    return gmail_oauth.granted_scopes(tokens)


# ------------------------------------------------------------------ tokens

def access_token(connection) -> str:
    """A fresh access token; Microsoft's rotated refresh token is kept."""
    from apps.crm.services.secrets import read_secret, write_secret
    from apps.tenancy.models import SecretKind

    stored = read_secret(connection.secret)
    if not stored:
        raise CalendarUnavailable("No calendar credential is stored. Connect your calendar again.")
    if connection.provider == "microsoft":
        try:
            tokens = microsoft_oauth.refresh(stored, MICROSOFT_SCOPES)
        except microsoft_oauth.MicrosoftOAuthError as exc:
            raise CalendarUnavailable(f"{exc} Connect your calendar again.") from exc
        rotated = tokens.get("refresh_token")
        if rotated and rotated != stored:
            connection.secret = write_secret(tenant=connection.tenant,
                                             kind=SecretKind.CALENDAR_REFRESH,
                                             value=rotated, user=connection.user)
            connection.save(update_fields=["secret", "updated_at"])
        return tokens["access_token"]
    client_id, client_secret = gmail_oauth.client_for(connection.tenant)
    response = requests.post(gmail_oauth.TOKEN_URL, data={
        "client_id": client_id, "client_secret": client_secret, "refresh_token": stored,
        "grant_type": "refresh_token"}, timeout=20)
    if not response.ok:
        raise CalendarUnavailable(
            f"Google refused the calendar credential ({response.status_code}). "
            "Connect your calendar again.")
    return response.json()["access_token"]


# ------------------------------------------------------------------ events

def _iso(value: datetime) -> str:
    return value.astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(value: str, *, tz_name: str = "UTC") -> datetime:
    """A provider's time as an aware datetime. Google gives an offset; Graph
    gives a naive time in the zone it was asked for (UTC here)."""
    from zoneinfo import ZoneInfo

    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(tz_name or "UTC"))
    return parsed


def list_events(connection, start: datetime, end: datetime) -> list[dict]:
    """Events from `start` to `end`, each as {id, title, starts_at, ends_at,
    all_day, web_link, emails, skip}. `emails` is attendees and organizer,
    the account's own address left out."""
    token = access_token(connection)
    own = connection.email_address.lower()
    if connection.provider == "microsoft":
        return _graph_events(connection, token, start, end, own)
    return _google_events(token, start, end, own)


def _google_events(token, start, end, own) -> list[dict]:
    out, page = [], None
    for _ in range(MAX_PAGES):
        params = {"timeMin": _iso(start), "timeMax": _iso(end), "singleEvents": "true",
                  "orderBy": "startTime", "maxResults": "250", "fields": GOOGLE_FIELDS}
        if page:
            params["pageToken"] = page
        response = requests.get(f"{GOOGLE_API}/calendars/primary/events", params=params,
                                headers={"Authorization": f"Bearer {token}"}, timeout=30)
        if not response.ok:
            raise CalendarUnavailable(
                f"Google Calendar would not list events ({response.status_code}).")
        data = response.json()
        for item in data.get("items") or []:
            start_v, end_v = item.get("start") or {}, item.get("end") or {}
            all_day = "date" in start_v and "dateTime" not in start_v
            starts = _parse(start_v.get("dateTime") or f"{start_v.get('date')}T00:00:00+00:00")
            ends = _parse(end_v.get("dateTime") or f"{end_v.get('date')}T00:00:00+00:00")
            people = [*(item.get("attendees") or []), item.get("organizer") or {}]
            out.append({
                "id": item.get("id", ""), "title": item.get("summary") or "(no title)",
                "starts_at": starts, "ends_at": ends, "all_day": all_day,
                "web_link": item.get("htmlLink", ""),
                "emails": sorted({(p.get("email") or "").lower() for p in people
                                  if p.get("email") and not p.get("self")} - {own}),
                "skip": item.get("status") == "cancelled"
                or item.get("visibility") in ("private", "confidential"),
            })
        page = data.get("nextPageToken")
        if not page:
            break
    return out


def _graph_events(connection, token, start, end, own) -> list[dict]:
    from apps.crm.services import graph

    out = []
    url, params = f"{graph.GRAPH}/me/calendarView", {
        "startDateTime": _iso(start), "endDateTime": _iso(end), "$select": GRAPH_SELECT,
        "$top": "100", "$orderby": "start/dateTime"}
    headers = {"Authorization": f"Bearer {token}", "Prefer": 'outlook.timezone="UTC"'}
    for _ in range(MAX_PAGES):
        response = graph._call("GET", url, headers=headers, params=params)
        if not response.ok:
            raise CalendarUnavailable(
                f"Microsoft 365 would not list events ({response.status_code}): "
                f"{graph._said(response)[:200]}")
        data = response.json()
        for item in data.get("value") or []:
            people = [*(a.get("emailAddress") or {} for a in item.get("attendees") or []),
                      (item.get("organizer") or {}).get("emailAddress") or {}]
            out.append({
                "id": item.get("id", ""), "title": item.get("subject") or "(no title)",
                "starts_at": _parse((item.get("start") or {}).get("dateTime", ""),
                                    tz_name=(item.get("start") or {}).get("timeZone", "UTC")),
                "ends_at": _parse((item.get("end") or {}).get("dateTime", ""),
                                  tz_name=(item.get("end") or {}).get("timeZone", "UTC")),
                "all_day": bool(item.get("isAllDay")), "web_link": item.get("webLink", ""),
                "emails": sorted({(p.get("address") or "").lower() for p in people
                                  if p.get("address")} - {own}),
                "skip": bool(item.get("isCancelled"))
                or item.get("sensitivity") in ("private", "confidential"),
            })
        url, params = data.get("@odata.nextLink"), None
        if not url:
            break
    return out


def create_event(connection, *, title: str, starts_at: datetime, minutes: int,
                 tz_name: str, note: str = "") -> dict:
    """One event on the person's own calendar, with no attendees: nobody is
    invited by the app. Returns {id, web_link}."""
    token = access_token(connection)
    ends_at = starts_at + timedelta(minutes=minutes)
    if connection.provider == "microsoft":
        from apps.crm.services import graph

        local = "%Y-%m-%dT%H:%M:%S"
        response = graph._call("POST", f"{graph.GRAPH}/me/events", token=token, json={
            "subject": title[:255],
            "body": {"contentType": "text", "content": note},
            "start": {"dateTime": starts_at.strftime(local), "timeZone": tz_name},
            "end": {"dateTime": ends_at.strftime(local), "timeZone": tz_name}})
        if not response.ok:
            raise CalendarUnavailable(
                f"Microsoft 365 would not add the event ({response.status_code}): "
                f"{graph._said(response)[:200]}")
        data = response.json()
        return {"id": data.get("id", ""), "web_link": data.get("webLink", "")}
    response = requests.post(f"{GOOGLE_API}/calendars/primary/events",
                             headers={"Authorization": f"Bearer {token}"}, timeout=30, json={
                                 "summary": title[:255], "description": note,
                                 "start": {"dateTime": starts_at.isoformat(), "timeZone": tz_name},
                                 "end": {"dateTime": ends_at.isoformat(), "timeZone": tz_name}})
    if not response.ok:
        raise CalendarUnavailable(
            f"Google Calendar would not add the event ({response.status_code}).")
    data = response.json()
    return {"id": data.get("id", ""), "web_link": data.get("htmlLink", "")}
