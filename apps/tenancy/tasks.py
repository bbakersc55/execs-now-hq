"""Background tasks.

Every task is a plain module-level function taking primitives (assumption A1):
never a bound method, never an ORM object. That is what keeps a later swap to
Celery a decorator change rather than a rewrite.

Background jobs have no request, so each one takes a tenant_id and opens an
explicit `tenant_context` block — same manager, same fail-closed guarantees.
"""

from __future__ import annotations

from django.utils import timezone

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


def purge_expired_audio(tenant_id: str) -> int:
    """FR-2.19 — delete recording audio past the tenant's retention window.

    Registered as a schedule in Phase 2; defined here so Phase 0.5 proves the
    scheduling path with something the product actually needs.
    """
    from .models import StoredFile, Tenant

    with tenant_context(tenant_id):
        tenant = Tenant.objects.get(pk=tenant_id)
        cutoff = timezone.now() - timezone.timedelta(days=tenant.audio_retention_days)
        stale = StoredFile.objects.filter(
            purpose="recording_audio", created_at__lt=cutoff
        )
        count = stale.count()
        # Blob deletion lands in Phase 2; the row-level sweep is proven now.
        stale.update(delete_after=timezone.now())
    return count
