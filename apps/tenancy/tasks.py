"""Background tasks.

Every task is a plain module-level function taking primitives (assumption A1):
never a bound method, never an ORM object. That is what keeps a later swap to
Celery a decorator change rather than a rewrite.

Background jobs have no request, so each one takes a tenant_id and opens an
explicit `tenant_context` block — same manager, same fail-closed guarantees.
"""

from __future__ import annotations

from django.utils import timezone

from .claude import unattended_job
from .context import tenant_context


def heartbeat(tenant_id: str, label: str = "scheduled") -> str:
    """Writes one AuditEvent. Small, real, and observable in the database."""
    from .models import AuditEvent, Tenant

    with tenant_context(tenant_id):
        tenant = Tenant.objects.get(pk=tenant_id)
        event = AuditEvent.objects.create(
            tenant=tenant,
            verb="system.heartbeat",
            target_type="tenant",
            target_id=tenant.pk,
            payload={"label": label, "ran_at": timezone.now().isoformat()},
        )
    return str(event.pk)



@unattended_job("tenancy.keep_local_hours")
def keep_local_hours(tenant_id: str) -> int:
    """2026-11-17: the practice's daily jobs back on their practice-time hour
    after a daylight-saving change (`ensure_schedules.keep_local_hours`).
    Touches only the schedule table; no Claude, no mail."""
    from apps.tenancy.management.commands.ensure_schedules import (
        keep_local_hours as keep,
    )

    from .models import Tenant

    with tenant_context(tenant_id):
        return keep(Tenant.objects.get(pk=tenant_id))
