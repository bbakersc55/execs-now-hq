"""Scheduled work for Module 5 — the poll (FR-5.2).

Every ten minutes, and it does exactly what "Sync now" does. A plain
module-level function taking primitives (assumption A1), opening its own tenant
context because a background job has no request.

**It swallows nothing.** A Drive outage, a bad Anthropic key or an unreadable
document all leave the folder's cursor where it was and a visible reason on the
health screen; the next run picks up from the same place.
"""

from __future__ import annotations

from apps.tenancy.context import tenant_context


def poll_drive(tenant_id: str) -> dict:
    from apps.meetings import ingest
    from apps.tenancy.models import Tenant

    with tenant_context(tenant_id):
        tenant = Tenant.objects.get(pk=tenant_id)
        try:
            report = ingest.poll(tenant)
        except ingest.NotConnected:
            # Not every tenant watches a folder. That is not an error.
            return {"connected": False}
    return {
        "connected": True,
        "recorded": len(report["recorded"]),
        "skipped": len(report["skipped"]),
        "failed": len(report["failed"]),
        "error": report["error"],
    }
