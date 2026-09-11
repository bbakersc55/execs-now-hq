"""Tier 1 Gmail connect (FR-6.3b) — the OAuth half.

Deliberately separate from sign-in. `SOCIALACCOUNT_PROVIDERS` asks for
`openid email profile` with `access_type: online`: signing in with Google tells
us who you are and nothing more. Sending mail as you is a second, explicit
consent (C2), which is what this module runs.

Two consequences worth stating, because both are easy to get wrong:

1. **`access_type=offline` with `prompt=consent`.** Google returns a refresh
   token only on the first consent for a given client/user pair. A reconnect
   after a revoked token would otherwise come back with an access token and no
   refresh token, and the connection would look healthy until the access token
   expired an hour later. Forcing the consent screen every time costs one extra
   click and removes that failure mode.
2. **Tier 1 asks for `gmail.send` + `gmail.settings.basic` only.** Not
   `gmail.readonly` — that is Tier 2's restricted read over the whole mailbox
   and is opt-in per user (FR-6.3g). A VA gets neither (H7).
"""

from __future__ import annotations

import secrets
from urllib.parse import urlencode

import requests
from django.conf import settings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

# `openid`/`email` are not restricted scopes and cost nothing at the consent
# screen. They are here so we can name the account that was actually connected:
# Gmail's `users.getProfile` needs a read scope Tier 1 deliberately does not ask
# for, so userinfo is how we learn the address without widening the grant.
TIER1_SCOPES = [
    "openid",
    "email",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.settings.basic",
]

STATE_SESSION_KEY = "gmail_oauth_state"


class GmailOAuthError(Exception):
    """Consent or token exchange failed. Always surfaced, never swallowed."""


def is_configured() -> bool:
    return bool(settings.GOOGLE_OAUTH_CLIENT_ID and settings.GOOGLE_OAUTH_CLIENT_SECRET)


def redirect_uri() -> str:
    """Must match an Authorised redirect URI on the OAuth client exactly."""
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/accounts/gmail/callback"


def new_state() -> str:
    return secrets.token_urlsafe(24)


def workspace_domain(email: str) -> str:
    """The Workspace domain to confine the account picker to.

    Taken from the signing-in user's own address rather than hardcoded or read
    off the tenant alias: §5a makes the consent screen **Internal**, so every
    fractional who can sign in already holds an account in the practice's
    Workspace domain — and a V1 tenant on a different domain gets the right
    answer without a second setting to keep in sync.
    """
    return email.split("@", 1)[-1].strip().lower() if "@" in (email or "") else ""


def authorization_url(state: str, *, login_hint: str = "", hd: str = "") -> str:
    """The consent URL.

    `login_hint` + `hd` exist because the browser, not the app, chooses which
    Google account answers this: without them Google silently offers whatever
    personal account was last used, and the owner connects the wrong mailbox —
    a failure that surfaces later as mail sent from the wrong address.

    `prompt=select_account consent` asks for **both** — the account chooser so
    the right account can be picked, and the consent screen so Google reissues
    a refresh token. `consent` alone re-consents as the already-signed-in
    account and never shows the picker.
    """
    params = {
        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": " ".join(TIER1_SCOPES),
        "access_type": "offline",
        "prompt": "select_account consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    if login_hint:
        params["login_hint"] = login_hint
    if hd:
        # A hint, not a control: Google may still show other accounts. The
        # send-as check is what actually refuses a wrong mailbox.
        params["hd"] = hd
    return f"{AUTH_URL}?" + urlencode(params)


def exchange_code(code: str) -> dict:
    """Authorisation code -> tokens. Raises rather than returning a partial."""
    response = requests.post(TOKEN_URL, data={
        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
        "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri(),
    }, timeout=20)
    if not response.ok:
        raise GmailOAuthError(
            f"Google refused the authorisation code ({response.status_code}). "
            "Check that the redirect URI on the OAuth client matches "
            f"{redirect_uri()} exactly, then try connecting again."
        )
    payload = response.json()
    if not payload.get("refresh_token"):
        # Without this the connection would work for an hour and then stop.
        raise GmailOAuthError(
            "Google returned no refresh token. Remove Execs NOW HQ at "
            "https://myaccount.google.com/permissions and connect again."
        )
    return payload


def account_email(access_token: str) -> str:
    response = requests.get(
        USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}, timeout=20,
    )
    if not response.ok:
        raise GmailOAuthError(
            f"Connected, but Google would not say which account ({response.status_code}). "
            "Disconnect and try again."
        )
    email = (response.json().get("email") or "").strip()
    if not email:
        raise GmailOAuthError("Google returned no email address for the account.")
    return email


def granted_scopes(payload: dict) -> list[str]:
    return [s for s in (payload.get("scope") or "").split(" ") if s]


def missing_scopes(payload: dict) -> list[str]:
    """What consent did NOT grant. Google lets a user untick individual scopes."""
    granted = set(granted_scopes(payload))
    required = {s for s in TIER1_SCOPES if s.startswith("https://")}
    return sorted(required - granted)
