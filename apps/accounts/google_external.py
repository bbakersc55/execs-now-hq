"""Staff sign-in with Google, for practices outside the Executives Now
Workspace (P2 D1, owner 2026-10-02).

The Workspace's OAuth client has an *Internal* consent screen, so Google turns
away any other domain's account before the app sees it. Practices on other
domains use a second client (External, in its own GCP project). Which client a
sign-in uses depends on whose account it is, so the staff sign-in is email
first: `google_start` takes the address, and

- a live staff member of an External practice goes to the External client,
  here, with the address as the login hint;
- everyone else (Executives Now staff, and any address the app does not
  know) goes to the existing Workspace sign-in, exactly as before. An unknown
  address gets the same redirect as a Workspace one, so the form says nothing
  about who has access.

The callback admits only a verified Google address that matches a live staff
membership of an External practice that is not archived. Clients never use
this: they sign in by magic link.
"""

from __future__ import annotations

from urllib.parse import urlencode

import requests
from django.conf import settings
from django.contrib.auth import login
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.crm.services import gmail_oauth

STATE_KEY = "enhq_external_signin_state"
SIGN_IN_SCOPES = "openid email profile"
STAFF_ROLES = ("FF", "CF", "VA")


def redirect_uri() -> str:
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/accounts/google/external/callback"


def _external_staff(email: str):
    from apps.tenancy.models import Membership

    if not email:
        return None
    return (Membership.all_objects.select_related("user", "tenant")
            .filter(user__email__iexact=email, revoked_at__isnull=True,
                    role__in=STAFF_ROLES, tenant__oauth_client="external")
            .exclude(tenant__status="archived").first())


@require_http_methods(["GET"])
def google_start(request):
    email = (request.GET.get("email") or "").strip().lower()
    membership = _external_staff(email)
    if membership is None:
        return HttpResponseRedirect("/accounts/google/login/")
    client_id, _ = gmail_oauth.client_for(membership.tenant)
    if not client_id:
        return _refuse(request, "Google sign-in for your practice isn't set up yet. "
                                "Contact support.")
    state = gmail_oauth.new_state()
    request.session[STATE_KEY] = state
    params = {"client_id": client_id, "redirect_uri": redirect_uri(),
              "response_type": "code", "scope": SIGN_IN_SCOPES, "access_type": "online",
              "prompt": "select_account", "login_hint": email, "state": state}
    return HttpResponseRedirect(f"{gmail_oauth.AUTH_URL}?{urlencode(params)}")


@require_http_methods(["GET"])
def google_external_callback(request):
    expected = request.session.pop(STATE_KEY, None)
    if not expected or request.GET.get("state") != expected:
        return _refuse(request, "That sign-in had expired. Start again.")
    if request.GET.get("error") or not request.GET.get("code"):
        return _refuse(request, "Google did not complete the sign-in. Start again.")

    client_id = settings.GOOGLE_OAUTH_EXTERNAL_CLIENT_ID
    client_secret = settings.GOOGLE_OAUTH_EXTERNAL_CLIENT_SECRET
    try:
        tokens = requests.post(gmail_oauth.TOKEN_URL, data={
            "client_id": client_id, "client_secret": client_secret,
            "code": request.GET["code"], "grant_type": "authorization_code",
            "redirect_uri": redirect_uri()}, timeout=20)
        tokens.raise_for_status()
        info = requests.get(gmail_oauth.USERINFO_URL, timeout=20, headers={
            "Authorization": f"Bearer {tokens.json()['access_token']}"})
        info.raise_for_status()
        profile = info.json()
    except (requests.RequestException, KeyError, ValueError):
        return _refuse(request, "Google could not confirm who you are. Start again.")

    email = (profile.get("email") or "").strip().lower()
    membership = _external_staff(email) if profile.get("email_verified") else None
    if membership is None or not membership.user.is_active:
        return _refuse(request, "That account has no access to this workspace. It is "
                                "invite-only; ask the practice owner to invite you.")
    user = membership.user
    user.last_login_at = timezone.now()
    user.save(update_fields=["last_login_at", "updated_at"])
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return HttpResponseRedirect(settings.APP_ROOT_URL)


def _refuse(request, message: str):
    from django.contrib import messages

    messages.error(request, message)
    return HttpResponseRedirect(reverse("login-refused"))
