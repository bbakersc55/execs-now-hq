"""Telling the platform owner (docs/p16_card_page_scripts.md): a Notice in
the app, in their own practice ("Card payments that need you"), and an email
through platform mail (Outbox producer `card_page_alert`). The same `key` is
told once: a Notice per source, an email per Notice."""

from __future__ import annotations

import logging
import uuid

log = logging.getLogger(__name__)

_NAMESPACE = uuid.UUID("3e0b8a1c-5d2f-4a7e-9c41-6b8d2f0a7e13")


def owners():
    """(user, practice) for each platform owner with a practice to be told in."""
    from apps.accounts.models import User
    from apps.tenancy.models import Membership

    out = []
    for user in User.objects.filter(is_platform_owner=True, is_active=True).order_by("created_at"):
        membership = (Membership.all_objects.select_related("tenant")
                      .filter(user=user, revoked_at__isnull=True).first())
        out.append((user, membership.tenant if membership else None))
    return out


def tell(*, key: str, title: str, text: str) -> int:
    """Tell every platform owner; returns how many were told (0 if they all
    were already). Never raises: an alert that can't go is logged."""
    from apps.notify import service as notify
    from apps.notify.models import Kind
    from apps.tenancy.context import tenant_context

    source_id = uuid.uuid5(_NAMESPACE, key)
    told = 0
    for user, practice in owners():
        try:
            if practice is not None:
                with tenant_context(practice.pk):
                    notice = notify.tell(tenant_id=practice.pk, recipient_id=user.pk,
                                         kind=Kind.PAYMENTS, title=title, text=text,
                                         source_type="card_pages", source_id=source_id)
                if notice is None:
                    continue                                   # told already
            told += 1
            _email(user, title, text)
        except Exception:                                      # noqa: BLE001
            log.exception("card pages: the alert to user %s did not go", user.pk)
    if not told:
        log.warning("card pages alert (nobody new to tell): %s: %s", title, text)
    return told


def _email(user, title, text) -> None:
    from apps.crm.models import OutboxMessage
    from apps.platform import mail

    if not (user.email or "").strip():
        return
    try:
        mail.send_platform_mail(
            to=user.email, subject=title, producer=OutboxMessage.Producer.CARD_PAGE_ALERT,
            paragraphs=[text, "Card page scripts: docs/card_page_scripts.md. What is in "
                              "force: python manage.py card_pages status."])
    except mail.PlatformMailUnavailable as exc:
        log.error("card pages: the alert email to %s could not go: %s", user.pk, exc)
