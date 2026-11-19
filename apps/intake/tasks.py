"""The worker's entry points (Django-Q2), each run inside its practice."""

from __future__ import annotations

from apps.tenancy.claude import unattended_job
from apps.tenancy.context import tenant_context


def run_send(tenant_id, run_id):
    from . import services
    from .models import SendRun

    with tenant_context(tenant_id):
        run = SendRun.all_objects.select_related("submission").filter(
            pk=run_id, tenant_id=tenant_id).first()
        if run is None or run.state not in (SendRun.State.QUEUED, SendRun.State.RUNNING):
            return
        services.run_send(run)


@unattended_job("intake.place_owner_dates")
def place_owner_dates(tenant_id):
    """Hourly: owner dates that are held, placed once their unit is bookable."""
    from . import services

    with tenant_context(tenant_id):
        services.hourly(tenant_id)


@unattended_job("intake.purge")
def purge(tenant_id):
    """Daily: sensitive values of intakes never sent, 90 days after their last change."""
    from . import services

    with tenant_context(tenant_id):
        services.daily(tenant_id)
