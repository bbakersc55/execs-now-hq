"""What the platform owner sees about a practice: numbers and dates, nothing
else (P2, owner 2026-10-02).

**The one module in `apps/platform` that reads across practices.**
`tests/test_platform_isolation.py` fails if any other module here touches a
practice-scoped model. Each value below is a count, a sum or a date, never a
row, a name from inside a practice, or an id of anything a practice holds.
The practice's own identity (its names, domain, status) is the `tenant` row,
which is the platform's record of the practice, not the practice's data.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db.models import Count, Max, Q, Sum
from django.utils import timezone

STAFF_ROLES = ("FF", "CF", "VA")

#: The keys a practice row carries. Tested: nothing else ever appears.
ROW_KEYS = ("id", "display_name", "legal_name", "domain", "status", "created_at",
            "archived_at", "oauth_client", "staff_count", "client_count",
            "ai_spend_this_month_usd", "last_activity_at", "modules")


def practice_rows() -> list[dict]:
    from apps.crm.models import Company
    from apps.tenancy import modules
    from apps.tenancy.models import AiCall, Membership, Tenant

    tenants = list(Tenant.objects.order_by("name"))
    ids = [t.pk for t in tenants]
    staff = dict(Membership.all_objects.filter(tenant_id__in=ids, role__in=STAFF_ROLES,
                                               revoked_at__isnull=True)
                 .values("tenant_id").annotate(n=Count("id")).values_list("tenant_id", "n"))
    clients = dict(Company.all_objects.filter(tenant_id__in=ids, is_client_company=True)
                   .values("tenant_id").annotate(n=Count("id"))
                   .values_list("tenant_id", "n"))
    seen = {
        row["tenant_id"]: max(filter(None, (row["a"], row["b"])), default=None)
        for row in Membership.all_objects.filter(tenant_id__in=ids)
        .values("tenant_id").annotate(a=Max("user__last_login"),
                                      b=Max("user__last_login_at"))
    }
    on = modules.enabled_by_practice(ids)
    rows = []
    for tenant in tenants:
        rows.append({
            "id": str(tenant.pk),
            "display_name": tenant.email_display_name or tenant.name,
            "legal_name": tenant.legal_name,
            "domain": tenant.domain,
            "status": tenant.status,
            "created_at": tenant.created_at.isoformat(),
            "archived_at": tenant.archived_at.isoformat() if tenant.archived_at else None,
            "oauth_client": tenant.oauth_client,
            "staff_count": staff.get(tenant.pk, 0),
            "client_count": clients.get(tenant.pk, 0),
            "ai_spend_this_month_usd": str(_spend_this_month(AiCall, tenant)),
            "last_activity_at": seen[tenant.pk].isoformat() if seen.get(tenant.pk) else None,
            # P6 M1: which modules it has. The platform's own record of the
            # practice (apps/tenancy/modules.py), not anything inside it.
            "modules": [{"code": code, "name": name, "enabled": code in on.get(tenant.pk, ())}
                        for code, name in modules.MODULES.items()],
        })
    return rows


def _spend_this_month(AiCall, tenant) -> Decimal:
    """This calendar month in the practice's own time zone."""
    zone = ZoneInfo(tenant.timezone or "UTC")
    local = timezone.now().astimezone(zone)
    start = datetime(local.year, local.month, 1, tzinfo=zone)
    total = (AiCall.all_objects.filter(Q(tenant_id=tenant.pk) & Q(created_at__gte=start))
             .aggregate(s=Sum("cost_usd"))["s"])
    return (total or Decimal("0")).quantize(Decimal("0.01"))
