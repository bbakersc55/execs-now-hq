"""Staff session rules (docs/ui3_top_bar_settings_profile.md §2a).

A staff session ends after `STAFF_IDLE_SECONDS` without the person doing
anything. "Doing anything" cannot be "made a request": Digests, Activity and an
open recording refresh themselves, so a screen left open would stay signed in
for ever. Each request from the app carries how long ago the person last
clicked, typed or scrolled in that tab, and only that moves the clock.

Client portal sessions are left alone. They are the ones given an explicit
30-day life at sign-in (`request.session.set_expiry`), which is how they are
told apart here: whoever is being acted as, the session is the real person's.
"""

from __future__ import annotations

import time

from django.conf import settings
from django.contrib.auth import logout
from django.http import HttpResponseRedirect, JsonResponse

#: Session key: when the person was last seen doing something (epoch seconds).
LAST_ACTIVE_KEY = "last_active_at"
#: Request header, set by the app: seconds since the last click, key or scroll.
IDLE_HEADER = "X-Idle-Seconds"

SIGNED_OUT = "You were signed out after 12 hours without activity. Sign in again to continue."


def _idle_seconds(request) -> float:
    """A request that does not say counts as activity: a page load, a sign-in
    redirect. Only the app's own background refreshes report a long idle."""
    try:
        return max(0.0, float(request.headers.get(IDLE_HEADER, "0")))
    except ValueError:
        return 0.0


class StaffIdleSignOut:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        session = request.session
        if (user is None or not user.is_authenticated
                # A client session: 30 days, set at sign-in. Not ours to end.
                or session.get("_session_expiry") is not None):
            return self.get_response(request)

        now = time.time()
        last = session.get(LAST_ACTIVE_KEY)
        if last is not None and now - last > settings.STAFF_IDLE_SECONDS:
            # Ends acting as too, audited, through the sign-out signal.
            logout(request)
            if request.path.startswith("/api/") or request.path.startswith("/auth/"):
                return JsonResponse({"authenticated": False, "detail": SIGNED_OUT}, status=401)
            # Anything else is a page: ask for it again, signed out this time.
            return HttpResponseRedirect(request.get_full_path())

        seen = now - _idle_seconds(request)
        if last is None or seen > last:
            session[LAST_ACTIVE_KEY] = seen
        return self.get_response(request)


# ------------------------------------------------ 2026-11-17: twelve hours

#: Session key: when the person signed in (epoch seconds).
SIGNED_IN_KEY = "signed_in_at"
SIGNED_IN_SECONDS = 60 * 60 * 12
SIGNED_OUT_12H = ("You were signed out: it has been 12 hours since you signed in. Sign in again "
                  "to continue.")


def stamp_sign_in(sender, request, user, **kwargs):
    """`user_logged_in`: every sign-in, whatever the method, starts the
    twelve hours, and a new session has entered no code yet."""
    from apps.accounts.two_factor import SESSION_VERIFIED

    if request is None or not hasattr(request, "session"):
        return
    request.session[SIGNED_IN_KEY] = time.time()
    request.session.pop(SESSION_VERIFIED, None)


def session_ends_at(request) -> float | None:
    started = request.session.get(SIGNED_IN_KEY) if hasattr(request, "session") else None
    return float(started) + SIGNED_IN_SECONDS if started else None


class SignInLifetime:
    """Everyone, staff and client users alike, is signed out twelve hours
    after signing in (2026-11-17). A session from before this rule is given
    its twelve hours from the first request it makes after it. Token routes
    (connected AI apps, pay and signing links) carry no session and are not
    touched."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return self.get_response(request)
        session = request.session
        started = session.get(SIGNED_IN_KEY)
        now = time.time()
        if started is None:
            session[SIGNED_IN_KEY] = now
        elif now - float(started) > SIGNED_IN_SECONDS:
            logout(request)
            if request.path.startswith("/api/") or request.path.startswith("/auth/"):
                return JsonResponse({"authenticated": False, "detail": SIGNED_OUT_12H},
                                    status=401)
            return HttpResponseRedirect(request.get_full_path())
        return self.get_response(request)


#: What answers while the code after sign-in is still to be entered.
TWO_FACTOR_OPEN = ("/api/me", "/api/branding", "/api/me/two-factor/verify")
TWO_FACTOR_PENDING = "Enter the code from your authenticator app to finish signing in."


class TwoFactorGate:
    """After any sign-in, a person with two-factor on reaches nothing but
    who they are, the branding, the code prompt and signing out until a code
    is entered (`two_factor.pending`). Pages (an AI app's consent page among
    them) go back to the app, which shows the prompt."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from apps.accounts import two_factor

        path = request.path
        if (path.startswith("/api/") or path.startswith("/oauth/")) and \
                not (path in TWO_FACTOR_OPEN or path.startswith("/api/branding")) and \
                two_factor.pending(request):
            if path.startswith("/api/"):
                return JsonResponse({"detail": TWO_FACTOR_PENDING, "two_factor_pending": True},
                                    status=403)
            return HttpResponseRedirect(settings.APP_ROOT_URL)
        return self.get_response(request)
