"""Turning a Command Center on and off (P8), and what Settings → Command
Centers shows.

Turning one on **only offers** its pieces: it writes the practice's switch
and, unless this is the platform owner's own practice, one $50 line on the
practice's subscription from the next 1st (D4: the rest of this month is
included). Nothing of a client's (scorecard, templates, goals) changes; each
piece is copied in when first used. All the lines together are capped at
$150 (`apps.billing.subscriptions.lines_for`). The demo never switches.
"""

from __future__ import annotations

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.centers import catalog
from apps.centers.models import CommandCenter, LibraryRecord, PracticeCenter


class CenterRefused(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


DEMO_REFUSAL = ("Command Centers are switched by Execs NOW HQ in the demo. Here the Operations "
                "Command Center is on, so you can see what it brings.")


def ensure_catalog() -> None:
    """The catalog's rows, put back from code if missing (a database emptied
    by a test; never a rewrite of a row that is there)."""
    if CommandCenter.objects.count() >= len(catalog.CENTERS):
        return
    for position, (code, name, short, discipline, status, description) in \
            enumerate(catalog.CENTERS):
        CommandCenter.objects.get_or_create(code=code, defaults={
            "name": name, "short_name": short, "discipline": discipline,
            "price_cents": catalog.PRICE_CENTS, "status": status,
            "description": description, "position": position})


def enabled(tenant_id) -> list[str]:
    """The codes of the modules this practice has on, in catalog order."""
    if tenant_id is None:
        return []
    on = set(PracticeCenter.all_objects.filter(
        tenant_id=getattr(tenant_id, "pk", tenant_id), enabled_at__isnull=False,
        disabled_at__isnull=True).values_list("center", flat=True))
    return [code for code in catalog.CODES if code in on]


def has(tenant_id, code: str) -> bool:
    return code in enabled(tenant_id)


def owners_practice(tenant) -> bool:
    from apps.billing.subscriptions import is_owners_practice

    return is_owners_practice(tenant)


def _next_first(day):
    from apps.billing.subscriptions import first_of_next_month

    return first_of_next_month(day)


def price_line(tenant) -> str:
    """What the switch confirms before turning one on."""
    if owners_practice(tenant):
        return "Included for your practice: nothing is added to a subscription."
    start = _next_first(timezone.localdate())
    return (f"$50 a month is added to your subscription from {start:%B} {start.day}; the rest "
            "of this month is included. All Command Centers together are capped at $150 a "
            "month.")


def can_switch() -> tuple[bool, str]:
    if settings.IS_DEMO:
        return False, DEMO_REFUSAL
    return True, ""


@transaction.atomic
def switch(tenant, code: str, on: bool, *, actor) -> PracticeCenter:
    from apps.billing.models import BillingAddon, PracticeSubscriptionAddon
    from apps.billing.subscriptions import subscription_for
    from apps.tenancy.models import AuditEvent

    allowed, why = can_switch()
    if not allowed:
        raise CenterRefused(why, 403)
    ensure_catalog()
    row = CommandCenter.objects.filter(code=code).first()
    if row is None:
        raise CenterRefused("There is no such Command Center.", 404)
    if on and row.status != CommandCenter.Status.AVAILABLE:
        raise CenterRefused(f"The {row.name} is not available yet.", 409)
    now = timezone.now()
    switch_row, _ = PracticeCenter.all_objects.get_or_create(tenant=tenant, center=code)
    was = switch_row.enabled_at is not None and switch_row.disabled_at is None
    if was == bool(on):
        return switch_row
    if on:
        switch_row.enabled_at, switch_row.enabled_by = now, actor
        switch_row.disabled_at = switch_row.disabled_by = None
    else:
        switch_row.disabled_at, switch_row.disabled_by = now, actor
    switch_row.save()

    if not owners_practice(tenant):
        subscription = subscription_for(tenant)
        addon, _ = BillingAddon.objects.get_or_create(
            code=catalog.addon_code(code),
            defaults={"name": row.name, "price_cents": row.price_cents, "is_placeholder": False})
        live = PracticeSubscriptionAddon.all_objects.filter(
            subscription=subscription, addon=addon, removed_at__isnull=True)
        if on and not live.exists():
            PracticeSubscriptionAddon.all_objects.create(
                tenant=tenant, subscription=subscription, addon=addon, added_at=now,
                charged_from=_next_first(timezone.localdate()))
        elif not on:
            live.update(removed_at=now)
    AuditEvent.all_objects.create(
        tenant=tenant, actor=actor,
        verb="command_center.enabled" if on else "command_center.disabled",
        target_type="command_center", target_id=row.pk, payload={"center": code})
    return switch_row


def state(tenant) -> dict:
    """Settings → Command Centers."""
    ensure_catalog()
    on = set(enabled(tenant.pk))
    allowed, why = can_switch()
    owners = owners_practice(tenant)
    return {
        "centers": [{
            "code": row.code, "name": row.name, "short_name": row.short_name,
            "discipline": row.discipline, "price_cents": row.price_cents,
            "description": row.description, "status": row.status,
            "next": row.code in catalog.NEXT, "on": row.code in on,
        } for row in CommandCenter.objects.order_by("position")],
        "cap_cents": catalog.CAP_CENTS,
        "owners_practice": owners,
        "price_line": price_line(tenant),
        "can_switch": allowed, "why_not": why,
        "library_count": LibraryRecord.all_objects.filter(tenant=tenant).count(),
    }
