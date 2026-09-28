"""The unsubscribe link (owner, 2026-09-28).

No login: the signed token is the whole of the authority, and it grants one
thing — leave, or rejoin, the categories of email this app sends one person.
It reveals nothing else: the page shows the practice's name and which of the
two categories the person is out of.

GET reads; POST changes. Opening the link does not unsubscribe anyone by
itself — the page does that when a person lands on it — so a mail scanner
that fetches every link in an email cannot take someone off a list.
"""

from __future__ import annotations

import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.crm.services import unsubscribe
from apps.tenancy.context import tenant_context

GONE = {"detail": "This link is not one we recognise. If you meant to unsubscribe, "
                  "reply to the email and ask; we will take you off."}


@csrf_exempt
@require_http_methods(["GET", "POST"])
def unsubscribe_link(request, token: str):
    data = unsubscribe.read_token(token)
    if data is None:
        return JsonResponse(GONE, status=404)
    with tenant_context(data["t"]):
        if request.method == "POST":
            try:
                body = json.loads(request.body or "{}")
            except ValueError:
                return JsonResponse({"detail": "Unreadable request."}, status=400)
            category = body.get("category") or data["k"]
            if category not in (unsubscribe.MARKETING, unsubscribe.UPDATES):
                return JsonResponse({"detail": "Unknown kind of email."}, status=400)
            if body.get("action") == "resubscribe":
                unsubscribe.resubscribe(data, category=category)
            else:
                unsubscribe.unsubscribe(data, category=category)
        return JsonResponse(unsubscribe.state_for(data))
