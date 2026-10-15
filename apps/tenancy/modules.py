"""The modules a practice has (P6 M1, owner 2026-10-08).

A module is a part of the app a practice has or does not have. Which it has
is the platform's record of the practice, switched by the platform owner in
the Practices area; the price is P4's. A practice without a module gets 404
from its routes and does not see its screens.

**Bookkeeping**: sub-categories, combine, split, the starting chart,
reconciliation and month close; the balance sheet when it is built.
Everything the books already did (entries, the import, the P&L, 1099, the
export) is every practice's, module or not. **Cash forecast** (P6 M2): its
own module, which a practice has only with Bookkeeping.
"""

from __future__ import annotations

from django.utils import timezone

BOOKKEEPING = "bookkeeping"
#: The cash forecast (P6 M2). It reads closed months, which only Bookkeeping
#: makes, so a practice has it only with Bookkeeping (M2-13).
FORECAST = "forecast"
#: Personal finance (P6 M4): the owner's household money, on its own side of
#: Finance. Off for every practice until switched on (decision 27).
PERSONAL = "personal"
#: Code -> the name a person reads.
MODULES = {BOOKKEEPING: "Bookkeeping", FORECAST: "Cash forecast",
           PERSONAL: "Personal finance"}
#: A module, and the one it cannot be had without.
NEEDS = {FORECAST: BOOKKEEPING}


class ModuleRefused(ValueError):
    """A switch that cannot be made, with a sentence for whoever asked."""


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
    have = enabled(tenant)
    if on and module in NEEDS and NEEDS[module] not in have:
        raise ModuleRefused(f"{MODULES[module]} needs {MODULES[NEEDS[module]]}: it reads "
                            "the months that are closed there. Switch that on first.")
    resting = [MODULES[code] for code, needed in NEEDS.items()
               if needed == module and code in have]
    if not on and resting:
        raise ModuleRefused(f"{' and '.join(resting)} needs {MODULES[module]}. Switch "
                            "that off first.")
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
