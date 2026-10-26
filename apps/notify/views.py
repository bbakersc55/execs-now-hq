"""The Notices list and browser notifications (owner, 2026-10-26). Everyone
signed in to a practice, its staff and its clients alike, sees only their own
notices and their own browsers in that practice.

GET    /api/notify/notices/             mine: the latest and how many are unread
POST   /api/notify/notices/read/        {ids: [...]} or {all: true}
GET    /api/notify/push/                whether it can be had here, the key, my kinds
PUT    /api/notify/push/                {kinds: [...]}
POST   /api/notify/push/subscribe/      {endpoint, keys: {p256dh, auth}}: this browser
POST   /api/notify/push/unsubscribe/    {endpoint}: this browser no longer
"""

from __future__ import annotations

from urllib.parse import urlparse

from django.conf import settings
from django.utils import timezone
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from . import service
from .models import Kind, Notice, PushPreference, PushSubscription

LATEST = 50
#: The browsers' own push services: the only places this server will post to.
PUSH_HOSTS = (".googleapis.com", ".mozilla.com", ".push.apple.com", ".notify.windows.com",
              ".mozaws.net")
ACTING = "While acting as someone, their notifications aren't yours to change."


class Base(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if getattr(request, "membership", None) is None:
            self.permission_denied(request, message="You're not a member of this practice.")


def _mine(request):
    return Notice.objects.filter(recipient_id=request.user.pk)


class NoticesView(Base):
    def get(self, request):
        rows = list(_mine(request)[:LATEST])
        return Response({"unread": _mine(request).filter(read_at__isnull=True).count(),
                         "notices": [service.represent(n) for n in rows]})


class ReadView(Base):
    def post(self, request):
        rows = _mine(request).filter(read_at__isnull=True)
        if not request.data.get("all"):
            ids = [str(i) for i in (request.data.get("ids") or [])][:200]
            rows = rows.filter(pk__in=[i for i in ids if _uuid(i)])
        done = rows.update(read_at=timezone.now(), updated_at=timezone.now())
        return Response({"read": done, "unread": _mine(request).filter(
            read_at__isnull=True).count()})


def _uuid(value) -> bool:
    import uuid

    try:
        uuid.UUID(str(value))
    except ValueError:
        return False
    return True


def _acting() -> bool:
    from apps.tenancy.context import get_acting

    return get_acting() is not None


def _state(request) -> dict:
    allowed = service.kinds_for(request.membership)
    pref = PushPreference.objects.filter(user_id=request.user.pk).first()
    on = set(pref.kinds) if pref else set()
    return {"refusal": service.refusal(request.tenant),
            "public_key": getattr(settings, "VAPID_PUBLIC_KEY", ""),
            "kinds": [{"key": k, "label": Kind(k).label, "on": k in on} for k in allowed],
            "browsers": PushSubscription.objects.filter(user_id=request.user.pk).count()}


def _endpoint_refusal(endpoint) -> str:
    parsed = urlparse(endpoint or "")
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not any(host.endswith(h) or host == h.lstrip(".")
                                           for h in PUSH_HOSTS):
        return "That isn't a browser's push address."
    return ""


class PushView(Base):
    def get(self, request):
        return Response(_state(request))

    def put(self, request):
        if _acting():
            return Response({"detail": ACTING}, status=403)
        allowed = service.kinds_for(request.membership)
        kinds = [str(k) for k in (request.data.get("kinds") or [])]
        unknown = [k for k in kinds if k not in allowed]
        if unknown:
            return Response({"kinds": f"Not something you can be told: {', '.join(unknown)}."},
                            status=400)
        PushPreference.all_objects.update_or_create(
            tenant_id=request.tenant.pk, user_id=request.user.pk,
            defaults={"kinds": [k for k in allowed if k in kinds]})
        return Response(_state(request))


class SubscribeView(Base):
    def post(self, request):
        if _acting():
            return Response({"detail": ACTING}, status=403)
        if (refusal := service.refusal(request.tenant)):
            return Response({"detail": refusal}, status=409)
        endpoint = str(request.data.get("endpoint") or "")
        keys = request.data.get("keys") or {}
        p256dh, auth = str(keys.get("p256dh") or ""), str(keys.get("auth") or "")
        if (refusal := _endpoint_refusal(endpoint)) or not (p256dh and auth):
            return Response({"detail": refusal or "The browser's keys are missing."},
                            status=400)
        # One per browser: the same endpoint, whoever had it, is now this person's.
        PushSubscription.all_objects.update_or_create(
            tenant_id=request.tenant.pk, endpoint=endpoint,
            defaults={"user_id": request.user.pk, "p256dh": p256dh[:200], "auth": auth[:100],
                      "user_agent": (request.META.get("HTTP_USER_AGENT") or "")[:300],
                      "failures": 0})
        # Turning it on starts with every kind of theirs; each can be switched off.
        PushPreference.all_objects.get_or_create(
            tenant_id=request.tenant.pk, user_id=request.user.pk,
            defaults={"kinds": service.kinds_for(request.membership)})
        return Response(_state(request), status=201)


class UnsubscribeView(Base):
    def post(self, request):
        PushSubscription.objects.filter(user_id=request.user.pk,
                                        endpoint=str(request.data.get("endpoint") or "")).delete()
        return Response(_state(request))
