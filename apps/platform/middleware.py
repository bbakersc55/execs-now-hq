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
