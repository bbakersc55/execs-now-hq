"""Outbound mail safety (FR-0.7, assumptions A4 and H6).

Every send passes through here. On a localhost build, mail goes to the dev
outbox unless the recipient is an exact match in DEV_REAL_SEND_ALLOWLIST — and
a real send from a dev build is audited and badged so it is visible after the
fact rather than invisible.
"""

from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMessage


def is_real_send_allowed(to_address: str) -> bool:
    if not settings.IS_LOCAL:
        return True
    return (to_address or "").strip().lower() in settings.DEV_REAL_SEND_ALLOWLIST


def send_now(*, tenant, to_address, subject, body_text, producer,
             from_address=None, actor=None):
    """Send immediately, writing the Outbox row as `sent` (FR-1.15b).

    Producers that reach here are the direct-to-`sent` ones: magic links,
    the strategy PDF, and cadence-change confirmations. Everything else is
    queued into `pending_approval` by Module 1's Outbox.
    """
    from apps.tenancy.models import AuditEvent

    dev_real = settings.IS_LOCAL and is_real_send_allowed(to_address)

    message = EmailMessage(
        subject=subject,
        body=body_text,
        from_email=from_address or tenant.from_address,
        to=[to_address],
    )
    message.send(fail_silently=False)

    AuditEvent.all_objects.create(
        tenant=tenant,
        actor=actor,
        verb="email.sent",
        target_type="outbox_message",
        payload={
            "producer": producer,
            "to": to_address,
            "dev_real_send": dev_real,
            "public_base_url": settings.PUBLIC_BASE_URL,
        },
    )
    return dev_real
