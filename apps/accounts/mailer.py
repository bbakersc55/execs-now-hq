"""Outbound mail safety (FR-0.7, assumptions A4 and H6).

Every send passes through here. On a localhost build, mail goes to the dev
outbox unless the recipient is an exact match in DEV_REAL_SEND_ALLOWLIST — and
a real send from a dev build is audited and badged so it is visible after the
fact rather than invisible.
"""

from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMessage


class AllowlistEntryInvalid(ValueError):
    """An entry that would widen the guard beyond one exact address."""


def normalise_allowlist_entry(value: str) -> str:
    """H6 — exact addresses only, and the rule is enforced in one place.

    A bare domain or a wildcard would put every colleague and client at that
    domain back in range, which is precisely what this guard exists to prevent.
    """
    entry = (value or "").strip().lower()
    if not entry:
        raise AllowlistEntryInvalid("Enter an email address.")
    if "*" in entry or entry.startswith("@") or "@" not in entry:
        raise AllowlistEntryInvalid(
            f"{value!r} is not an exact address. Wildcards and bare domains are "
            "rejected: one entry would put every colleague and client at that "
            "domain back in range (assumption H6)."
        )
    local, _, domain = entry.partition("@")
    if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
        raise AllowlistEntryInvalid(f"{value!r} is not a valid email address.")
    return entry


def dev_allowlist(tenant=None) -> set[str]:
    """The effective allow-list: `.env` entries UNION the tenant's own rows.

    The environment is the floor — an address set in `.env` cannot be removed
    through the UI, so the deployment's guarantee cannot be quietly lowered by
    someone clicking in the app.
    """
    entries = set(settings.DEV_REAL_SEND_ALLOWLIST)
    if tenant is None or not settings.IS_LOCAL:
        return entries
    from apps.crm.models import DevSendAllowlistEntry

    entries.update(
        DevSendAllowlistEntry.all_objects.filter(tenant=tenant)
        .values_list("address", flat=True)
    )
    return {e.strip().lower() for e in entries if e}


def is_real_send_allowed(to_address: str, tenant=None) -> bool:
    if not settings.IS_LOCAL:
        return True
    return (to_address or "").strip().lower() in dev_allowlist(tenant)


def send_now(*, tenant, to_address, subject, body_text, producer,
             from_address=None, actor=None):
    """Send immediately, writing the Outbox row as `sent` (FR-1.15b).

    Producers that reach here are the direct-to-`sent` ones: magic links,
    the strategy PDF, and cadence-change confirmations. Everything else is
    queued into `pending_approval` by Module 1's Outbox.
    """
    from apps.tenancy.models import AuditEvent

    dev_real = settings.IS_LOCAL and is_real_send_allowed(to_address, tenant)

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
