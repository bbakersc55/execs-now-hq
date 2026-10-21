"""The beta agreement gate (P2): a practice owner who has not accepted the
current version can use nothing but the agreement itself.

Enforced on the server, not only by a screen in front of the app: every API
call but the few the agreement page needs answers 403 until it is accepted.
"""

from __future__ import annotations

from django.http import JsonResponse

#: What the agreement page itself needs.
ALLOWED = ("/api/me", "/api/agreement", "/api/branding")


class AgreementGate:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if path.startswith("/api/") and not path.startswith(ALLOWED):
            from apps.platform import agreement

            if agreement.required(request):
                return JsonResponse({"detail": "Read and accept the beta agreement first.",
                                     "agreement_required": True}, status=403)
        return self.get_response(request)


#: What a suspended practice's staff still reach (P4 part 5): who they are,
#: the branding, signing out, and the practice's subscription, to pay it.
SUSPENDED_ALLOWED = ("/api/me", "/api/branding", "/api/subscription/")
SUSPENDED = ("Your practice is suspended until its Execs NOW HQ invoice is paid. The "
             "practice owner can pay it under Settings → Billing.")


class SuspendedGate:
    """A suspended practice (P4 part 5, D2): its staff reach nothing but the
    billing screen, on the server as well as on screen. Its clients are not
    stopped from reading what they have; nothing new reaches them, because
    nothing in the practice runs or sends."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        membership = getattr(request, "membership", None)
        if (path.startswith("/api/") and not path.startswith(SUSPENDED_ALLOWED)
                and membership is not None and membership.role in ("FF", "CF", "VA")
                and membership.tenant.status == "suspended"):
            return JsonResponse({"detail": SUSPENDED, "suspended": True}, status=403)
        return self.get_response(request)
