"""The modules a practice has (P6 M1, owner 2026-10-08).

A module is a part of the app a practice has or does not have. Which it has
is the platform's record of the practice, switched by the platform owner in
the Practices area; the price is P4's. A practice without a module gets 404
from its routes and does not see its screens.

Today there is one, **Bookkeeping**: sub-categories, combine, split and the
starting chart now; reconciliation, month close and the balance sheet as they
are built. Everything the books already did (entries, the import, the P&L,
1099, the export) is every practice's, module or not.
"""

from __future__ import annotations

from django.utils import timezone

BOOKKEEPING = "bookkeeping"
#: Code -> the name a person reads.
MODULES = {BOOKKEEPING: "Bookkeeping"}


def enabled(tenant) -> list[str]:
    """The codes of the modules this practice has, in a fixed order."""
    from apps.tenancy.models import PracticeModule

    on = set(PracticeModule.objects.filter(tenant=tenant, enabled_at__isnull=False,
                                           disabled_at__isnull=True)
             .values_list("module", flat=True))
    return [code for code in MODULES if code in on]


def enabled_by_practice(tenant_ids) -> dict:
    """`{practice id: {codes}}` for several practices at once: the Practices
    area's column."""
    from apps.tenancy.models import PracticeModule

    found: dict = {}
    for tenant_id, code in PracticeModule.objects.filter(
            tenant_id__in=list(tenant_ids), enabled_at__isnull=False,
            disabled_at__isnull=True).values_list("tenant_id", "module"):
        found.setdefault(tenant_id, set()).add(code)
    return found


def has(tenant, module: str) -> bool:
    return tenant is not None and module in enabled(tenant)


def set_enabled(tenant, module: str, on: bool, *, actor):
    """Switch one on or off. Audited in the practice's own trail, as its
    invitation and archiving are."""
    from apps.tenancy.models import AuditEvent, PracticeModule

    if module not in MODULES:
        raise ValueError("There is no such module.")
    row, _ = PracticeModule.objects.get_or_create(tenant=tenant, module=module)
    was = row.enabled_at is not None and row.disabled_at is None
    if was == bool(on):
        return row
    now = timezone.now()
    if on:
        row.enabled_at, row.enabled_by, row.disabled_at = now, actor, None
    else:
        row.disabled_at = now
    row.save()
    AuditEvent.all_objects.create(
        tenant=tenant, actor=actor,
        verb="practice.module_enabled" if on else "practice.module_disabled",
        target_type="tenant", target_id=tenant.pk, payload={"module": module})
    return row
