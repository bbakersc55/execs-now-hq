"""Owner agreements' worker entry point (Django-Q2), run inside its practice."""

from __future__ import annotations

from apps.tenancy.claude import unattended_job
from apps.tenancy.context import tenant_context


@unattended_job("agreements.tick")
def tick(tenant_id):
    """Hourly: the reminders to owners and to countersigners."""
    from . import services

    with tenant_context(tenant_id):
        services.tick(tenant_id=tenant_id)
