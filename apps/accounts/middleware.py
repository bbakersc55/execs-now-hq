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
