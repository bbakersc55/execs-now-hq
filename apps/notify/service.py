"""The Notices list and its browser notifications (owner, 2026-10-26).

`tell` is the one way a notice is made. It writes the row (once per thing it
is about), and once the row is committed asks `push` to send it to the
person's browsers. `push` sends only a row of the list, only to that person's
own subscriptions **in that practice**, only for a kind they switched on,
only while they are still a member, never on a demo visitor's copy, and only
where the server has its Web Push keys. It sends at once rather than through
the worker, so the demo (which has no worker) behaves as production does.
"""

from __future__ import annotations

import json
import logging

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Kind, Notice, PushPreference, PushSubscription

log = logging.getLogger(__name__)

#: Which kinds each side of the app can receive.
STAFF_KINDS = [Kind.NOTICE, Kind.CLIENT_MESSAGE, Kind.READING, Kind.MENTION]
CLIENT_KINDS = [Kind.CLIENT_MESSAGE, Kind.READING, Kind.MENTION]
#: How long a push service keeps a notification for a browser that is off.
TTL_SECONDS = 24 * 3600
TIMEOUT_SECONDS = 5
#: Failures in a row before a subscription is given up on.
MOST_FAILURES = 5


def kinds_for(membership) -> list[str]:
    from apps.tenancy.models import CLIENT_ROLES

    kinds = CLIENT_KINDS if membership.role in CLIENT_ROLES else STAFF_KINDS
    return [str(k) for k in kinds]


def tell(*, tenant_id, recipient_id, kind, title, text, url="", source_type="",
         source_id=None):
    """Put one thing on one person's Notices list, and push it once committed.
    The same source is told once; a second call returns None."""
    if recipient_id is None:
        return None
    fields = {"tenant_id": tenant_id, "recipient_id": recipient_id, "kind": kind,
              "title": title[:120], "text": text[:500], "url": url[:200],
              "source_type": source_type, "source_id": source_id}
    try:
        with transaction.atomic():
            notice = Notice.all_objects.create(**fields)
    except IntegrityError:
        return None                                   # told already
    transaction.on_commit(lambda: _push_quietly(notice.pk))
    return notice


def _push_quietly(notice_id):
    try:
        push(notice_id)
    except Exception:                                 # a push never breaks what told it
        log.exception("push of notice %s failed", notice_id)


def configured() -> bool:
    return bool(getattr(settings, "VAPID_PUBLIC_KEY", "")
                and getattr(settings, "VAPID_PRIVATE_KEY", ""))


def refusal(tenant) -> str:
    """Why browser notifications can't be had here, or ""."""
    from apps.tenancy.demo import visitors

    if visitors.is_copy(tenant):
        return "Browser notifications are not part of a demo copy."
    if not configured():
        return "Browser notifications aren't set up on this server yet."
    return ""


def _member(tenant_id, user_id):
    from apps.tenancy.models import Membership

    return Membership.all_objects.filter(tenant_id=tenant_id, user_id=user_id,
                                         revoked_at__isnull=True).first()


def _webpush():
    """The sender, looked up when used, so a test's stand-in applies."""
    from pywebpush import webpush

    return webpush


def push(notice_id) -> int:
    """Send one notice to its recipient's browsers. Returns how many took it."""
    notice = Notice.all_objects.select_related("tenant").filter(pk=notice_id).first()
    if notice is None or notice.pushed_at is not None or refusal(notice.tenant):
        return 0
    membership = _member(notice.tenant_id, notice.recipient_id)
    if membership is None or notice.kind not in kinds_for(membership):
        return 0
    preference = PushPreference.all_objects.filter(tenant_id=notice.tenant_id,
                                                   user_id=notice.recipient_id).first()
    if preference is None or notice.kind not in (preference.kinds or []):
        return 0
    payload = json.dumps({"title": notice.title, "body": notice.text,
                          "url": notice.url or "/", "tag": str(notice.pk)})
    sent = 0
    for sub in PushSubscription.all_objects.filter(tenant_id=notice.tenant_id,
                                                   user_id=notice.recipient_id):
        if _send(sub, payload):
            sent += 1
    if sent:
        Notice.all_objects.filter(pk=notice.pk).update(pushed_at=timezone.now())
    return sent


def _send(sub, payload) -> bool:
    from pywebpush import WebPushException

    try:
        _webpush()(subscription_info={"endpoint": sub.endpoint,
                                      "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
                   data=payload, vapid_private_key=settings.VAPID_PRIVATE_KEY,
                   vapid_claims={"sub": settings.VAPID_SUBJECT}, ttl=TTL_SECONDS,
                   timeout=TIMEOUT_SECONDS)
    except WebPushException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (404, 410):
            sub.delete()                              # the browser let it go
            return False
        _failed(sub)
        return False
    except Exception:                                 # the push service didn't answer
        _failed(sub)
        return False
    PushSubscription.all_objects.filter(pk=sub.pk).update(last_sent_at=timezone.now(),
                                                          failures=0)
    return True


def _failed(sub):
    sub.failures += 1
    if sub.failures >= MOST_FAILURES:
        sub.delete()
    else:
        PushSubscription.all_objects.filter(pk=sub.pk).update(failures=sub.failures)


def represent(notice) -> dict:
    return {"id": str(notice.pk), "kind": notice.kind, "title": notice.title,
            "text": notice.text, "url": notice.url,
            "created_at": notice.created_at.isoformat(),
            "read": notice.read_at is not None}
