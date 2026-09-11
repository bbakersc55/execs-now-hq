"""Outbound mail safety (FR-0.7, assumptions A4 and H6).

The allow-list rules that the Outbox's one delivery path consults. Nothing here
sends: `send_now`, which delivered magic links and PIN resets straight through
Django's mail backend — past the Outbox and the Gmail transport — was removed
in Phase 2. Every email now leaves through `outbox._deliver`.

On a localhost build, mail goes to the dev outbox unless the recipient is an
exact match in DEV_REAL_SEND_ALLOWLIST — and a real send from a dev build is
audited and badged so it is visible after the fact rather than invisible.
"""

from __future__ import annotations

from django.conf import settings


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
