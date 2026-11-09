"""`POST /api/public/leads`: the marketing site's "Request demo access" form
(2026-11-09).

The browser never calls this. It posts to the site's own server, which
forwards the form here with the shared secret in `X-Site-Lead-Token` and the
visitor's address in `X-Lead-Client-IP`. So:

- **The secret is the whole of the authentication.** No session, no CSRF
  (a plain Django view, so neither DRF's SessionAuthentication nor the CSRF
  middleware applies). Missing or wrong: 403 and nothing written. No secret
  set on the server: 503 for everything, never open.
- **Rate limited in the database**, so all workers count together: per
  visitor address (only believed once the secret checks out) and a daily cap
  on leads overall. Over either: 429.
- **The honeypot** (`website`): filled in, the answer is exactly a success's
  and nothing is written.
- **CORS** names only `https://www.execsnowhq.com`, and only when that is the
  request's Origin; any other origin gets no CORS header at all.

What a valid lead does is `apps/crm/services/site_leads.py`. The answer never
carries an id: `{"ok": true}`.
"""

from __future__ import annotations

import hmac
import ipaddress
import json
import logging

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils.cache import patch_vary_headers
from django.views.decorators.csrf import csrf_exempt
from rest_framework import serializers

from apps.accounts.ratelimit import RateLimit, client_ip, too_many_shared
from apps.crm.services import site_leads

log = logging.getLogger(__name__)

#: The one origin that ever gets a CORS header. Nothing wider, ever.
SITE_ORIGIN = "https://www.execsnowhq.com"
TOKEN_HEADER = "HTTP_X_SITE_LEAD_TOKEN"
IP_HEADER = "HTTP_X_LEAD_CLIENT_IP"

#: Per visitor address, every request with the right secret; and leads
#: overall, counted only for one that will be written.
PER_ADDRESS = RateLimit(limit=5, window_seconds=3600, prefix="site-lead-ip")
PER_DAY = RateLimit(limit=100, window_seconds=86400, prefix="site-lead-all")

MESSAGE_LONGEST = 1000
OK = {"ok": True}
NOT_ALLOWED = {"detail": "Not allowed."}
NOT_SET_UP = {"detail": "Website requests can't be received here right now."}
SLOW_DOWN = {"detail": "Too many requests. Please try again later."}
UNREADABLE = {"detail": "The request could not be read."}

_CHOOSE = {"invalid_choice": "Choose one of the options given."}


class LeadSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200, error_messages={
        "required": "Please enter your name.", "blank": "Please enter your name.",
        "null": "Please enter your name.",
        "max_length": "Please keep your name under 200 characters."})
    email = serializers.EmailField(max_length=254, error_messages={
        "required": "Please enter your email address.",
        "blank": "Please enter your email address.",
        "null": "Please enter your email address.",
        "invalid": "Please enter a valid email address.",
        "max_length": "Please enter a valid email address."})
    practice_name = serializers.CharField(max_length=200, required=False, allow_blank=True,
                                          default="", error_messages={
        "max_length": "Please keep the practice name under 200 characters."})
    discipline = serializers.ChoiceField(choices=["coo", "cfo", "cmo", "chro", "other"],
                                         required=False, allow_blank=True, default="",
                                         error_messages=_CHOOSE)
    email_platform = serializers.ChoiceField(choices=["google", "microsoft"], required=False,
                                             allow_blank=True, default="",
                                             error_messages=_CHOOSE)
    wants = serializers.ChoiceField(choices=["demo_copy", "call"], required=False,
                                    allow_blank=True, default="", error_messages=_CHOOSE)
    message = serializers.CharField(max_length=MESSAGE_LONGEST, required=False,
                                    allow_blank=True, default="", trim_whitespace=True,
                                    error_messages={
        "max_length": f"Please keep the message under {MESSAGE_LONGEST:,} characters."})

    def validate_name(self, value):
        value = " ".join(value.split())
        if not value:
            raise serializers.ValidationError("Please enter your name.")
        return value

    def validate_email(self, value):
        return value.strip().lower()

    def validate_practice_name(self, value):
        return " ".join(value.split())

    def validate_message(self, value):
        # One line: whatever line breaks it came with become spaces.
        return " ".join(value.split())


def _cors(request, response):
    patch_vary_headers(response, ("Origin",))
    if request.META.get("HTTP_ORIGIN") == SITE_ORIGIN:
        response["Access-Control-Allow-Origin"] = SITE_ORIGIN
    return response


def _answer(request, body, status):
    return _cors(request, JsonResponse(body, status=status))


def _secret_ok(request) -> bool:
    expected = settings.SITE_LEAD_TOKEN
    given = request.META.get(TOKEN_HEADER, "")
    return bool(given) and hmac.compare_digest(given.encode(), expected.encode())


def _visitor(request) -> str | None:
    """The visitor's address as the site's server saw it; failing that, ours."""
    given = (request.META.get(IP_HEADER) or "").strip()
    try:
        return str(ipaddress.ip_address(given))
    except ValueError:
        return client_ip(request)


def _data(request):
    if (request.content_type or "").startswith("application/x-www-form-urlencoded") \
            or (request.content_type or "").startswith("multipart/form-data"):
        return request.POST.dict()
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _plain(errors) -> str:
    for messages in errors.values():
        for message in messages:
            return str(message)
    return "Please check the form and try again."


@csrf_exempt
def leads(request):
    if request.method == "OPTIONS":
        response = HttpResponse(status=204)
        if request.META.get("HTTP_ORIGIN") == SITE_ORIGIN:
            response["Access-Control-Allow-Methods"] = "POST, OPTIONS"
            response["Access-Control-Allow-Headers"] = "Content-Type"
            response["Access-Control-Max-Age"] = "600"
        return _cors(request, response)
    if request.method != "POST":
        response = _answer(request, {"detail": "Only POST is accepted here."}, 405)
        response["Allow"] = "POST, OPTIONS"
        return response

    if not settings.SITE_LEAD_TOKEN:
        return _answer(request, NOT_SET_UP, 503)
    if not _secret_ok(request):
        return _answer(request, NOT_ALLOWED, 403)
    if too_many_shared(PER_ADDRESS, _visitor(request)):
        return _answer(request, SLOW_DOWN, 429)

    data = _data(request)
    if data is None:
        return _answer(request, UNREADABLE, 400)
    if str(data.get("website") or "").strip():
        return _answer(request, OK, 201)              # the honeypot: as a success would

    serializer = LeadSerializer(data=data)
    if not serializer.is_valid():
        errors = serializer.errors
        return _answer(request, {"detail": _plain(errors),
                                 "errors": {k: [str(m) for m in v] for k, v in errors.items()}},
                       400)
    if too_many_shared(PER_DAY, "all"):
        return _answer(request, SLOW_DOWN, 429)

    try:
        site_leads.receive(site_leads.Lead(**serializer.validated_data))
    except site_leads.NoPractice:
        log.error("Website lead refused: no active practice to receive it "
                  "(SITE_LEAD_PRACTICE=%r).", settings.SITE_LEAD_PRACTICE)
        return _answer(request, NOT_SET_UP, 503)
    return _answer(request, OK, 201)
