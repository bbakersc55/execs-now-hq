"""Connecting a Microsoft 365 work account (docs/m365_transport.md §7) — the
OAuth half, the twin of `gmail_oauth`.

The Microsoft identity platform (v2.0 endpoints) against the Entra app
registration whose values are in the environment. Multi-tenant, work accounts
only: the authority is `organizations`, so a personal Outlook.com account is
turned away by Microsoft before it reaches us.

Three things differ from Google and are easy to get wrong:

1. **Refresh tokens rotate.** Every refresh returns a new one, and the new one
   is stored (`refresh`). Google's stays the same for the life of the grant.
2. **There is no send-as list.** So the sending grant carries
   `Mail.ReadBasic`, a read of a message's envelope without its body, which is
   what lets the practice address be checked by a test send read back from
   Sent Items (D3).
3. **A practice's directory may forbid users to consent.** Then Microsoft
   answers with an error naming admin approval, and the screen gives the link
   an administrator approves the app with, once (§7 step 6).
"""

from __future__ import annotations

import base64
import json
import secrets
from urllib.parse import urlencode

import requests
from django.conf import settings

LOGIN = "https://login.microsoftonline.com"
GRAPH = "https://graph.microsoft.com/v1.0"
GRAPH_RESOURCE = "https://graph.microsoft.com/"

#: Sending, and checking the practice address. `offline_access` is what
#: makes Microsoft return a refresh token; without it the connection would
#: work for an hour.
SEND_SCOPES = ["openid", "email", "profile", "offline_access", "User.Read",
               "Mail.Send", "Mail.ReadBasic"]
#: Collecting replies (FR-6.5). Like `gmail.readonly`, **a read over the whole
#: mailbox**: Graph has no narrower grant, and the boundary is in
#: `GraphReader`, which asks only for conversations the app stored.
READ_SCOPES = ["Mail.Read"]
#: The two without which nothing can be sent or checked.
REQUIRED = ["Mail.Send", "Mail.ReadBasic"]

STATE_SESSION_KEY = "microsoft_oauth_state"
INBOUND_SESSION_KEY = "microsoft_oauth_inbound"


class MicrosoftOAuthError(Exception):
    """Consent or token exchange failed. Always surfaced, never swallowed."""


def is_configured() -> bool:
    return bool(settings.MICROSOFT_CLIENT_ID and settings.MICROSOFT_CLIENT_SECRET)


def authority() -> str:
    return settings.MICROSOFT_AUTHORITY or "organizations"


def redirect_uri() -> str:
    """Must match a Web redirect URI on the app registration exactly."""
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/accounts/microsoft/callback"


def new_state() -> str:
    return secrets.token_urlsafe(24)


def scopes_for(*, inbound: bool = False) -> list[str]:
    return SEND_SCOPES + (READ_SCOPES if inbound else [])


def authorization_url(state: str, *, login_hint: str = "", inbound: bool = False) -> str:
    """The consent URL. `prompt=select_account` so the right work account can
    be picked when the browser is signed in to several; Microsoft shows the
    consent screen by itself for anything not yet granted."""
    params = {
        "client_id": settings.MICROSOFT_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": redirect_uri(),
        "response_mode": "query",
        "scope": " ".join(scopes_for(inbound=inbound)),
        "state": state,
        "prompt": "select_account",
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{LOGIN}/{authority()}/oauth2/v2.0/authorize?" + urlencode(params)


def admin_consent_url(directory: str = "") -> str:
    """The link a practice's Microsoft 365 administrator approves the app
    with, once, when their directory lets only admins consent (§7 step 6)."""
    params = {
        "client_id": settings.MICROSOFT_CLIENT_ID,
        "scope": " ".join(f"{GRAPH_RESOURCE}{s}" for s in REQUIRED + READ_SCOPES),
        "redirect_uri": redirect_uri(),
    }
    return f"{LOGIN}/{directory or authority()}/v2.0/adminconsent?" + urlencode(params)


def _token_url() -> str:
    return f"{LOGIN}/{authority()}/oauth2/v2.0/token"


def _refused(response, what: str) -> str:
    try:
        body = response.json()
    except ValueError:
        body = {}
    said = (body.get("error_description") or body.get("error") or "").split("\r\n")[0]
    return f"Microsoft refused {what} ({response.status_code}){': ' + said if said else ''}."


def exchange_code(code: str, *, inbound: bool = False) -> dict:
    """Authorization code -> tokens. Raises rather than returning a partial."""
    response = requests.post(_token_url(), data={
        "client_id": settings.MICROSOFT_CLIENT_ID,
        "client_secret": settings.MICROSOFT_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri(),
        "scope": " ".join(scopes_for(inbound=inbound)),
    }, timeout=20)
    if not response.ok:
        raise MicrosoftOAuthError(
            _refused(response, "the authorization code")
            + f" Check that the app registration's redirect URI is {redirect_uri()} "
            "exactly, then connect again.")
    payload = response.json()
    if not payload.get("refresh_token"):
        raise MicrosoftOAuthError(
            "Microsoft returned no refresh token, so the connection would stop "
            "within the hour. Connect again; if it repeats, the app registration "
            "is missing the offline_access permission.")
    return payload


def refresh(refresh_token: str, scopes: list[str]) -> dict:
    """A fresh access token, and the rotated refresh token that came with it."""
    response = requests.post(_token_url(), data={
        "client_id": settings.MICROSOFT_CLIENT_ID,
        "client_secret": settings.MICROSOFT_CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
        "scope": " ".join(scopes),
    }, timeout=20)
    if not response.ok:
        raise MicrosoftOAuthError(_refused(response, "the stored credential"))
    return response.json()


def short(scope: str) -> str:
    """`https://graph.microsoft.com/Mail.Send` and `Mail.Send` are the same
    grant; Microsoft may answer with either. Compared without case."""
    return scope.removeprefix(GRAPH_RESOURCE).lower()


def granted_scopes(payload: dict) -> list[str]:
    """The grant as Microsoft reports it, in the short form. The token
    response lists the Graph scopes; the OpenID ones (openid, profile, email,
    offline_access) it may leave out, and they are not needed to send."""
    return sorted({scope.removeprefix(GRAPH_RESOURCE)
                   for scope in (payload.get("scope") or "").split() if scope})


def holds(scopes, wanted) -> bool:
    have = {short(s) for s in scopes or []}
    return {short(s) for s in wanted} <= have


def missing_scopes(payload: dict) -> list[str]:
    have = {short(s) for s in granted_scopes(payload)}
    return [s for s in REQUIRED if short(s) not in have]


def inbound_granted(payload_or_scopes) -> bool:
    scopes = (granted_scopes(payload_or_scopes) if isinstance(payload_or_scopes, dict)
              else payload_or_scopes)
    return holds(scopes, READ_SCOPES)


def id_claims(payload: dict) -> dict:
    """The ID token's claims, unverified: it came straight from Microsoft's
    token endpoint over TLS in exchange for our own code, and nothing here
    is used to decide who is signed in, only to name the directory."""
    token = payload.get("id_token") or ""
    try:
        body = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except (IndexError, ValueError):
        return {}


def account(access_token: str) -> str:
    """The work account's primary address: `mail`, or the sign-in name when
    the account has no mailbox address (which then cannot send)."""
    response = requests.get(f"{GRAPH}/me", params={"$select": "mail,userPrincipalName"},
                            headers={"Authorization": f"Bearer {access_token}"}, timeout=20)
    if not response.ok:
        raise MicrosoftOAuthError(
            f"Connected, but Microsoft would not say which account ({response.status_code}). "
            "Disconnect and try again.")
    data = response.json()
    address = (data.get("mail") or data.get("userPrincipalName") or "").strip()
    if not address:
        raise MicrosoftOAuthError("Microsoft returned no email address for the account.")
    return address
