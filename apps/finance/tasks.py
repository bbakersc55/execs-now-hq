"""Scheduled work for Finance. One job: the month's forecast, kept."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from django.utils import timezone

from apps.tenancy.claude import unattended_job
from apps.tenancy.context import tenant_context


# The worker's own, like every scheduled job. It makes no Claude call.
@unattended_job("finance.keep_month_forecast")
def keep_month_forecast(tenant_id: str) -> bool:
    """Keeps this month's forecast for "how good it has been", if it is not
    kept yet. It runs every day at the practice's midnight, so on the 1st it
    keeps the forecast as the month begins, and "what happened" is the whole
    month; a 1st the worker missed is made up the next day it runs. A practice
    without the Cash forecast, or without the closed months a forecast needs,
    is left alone (`docs/p6_m2_cash_forecast.md`, "As built: after stop 2")."""
    from apps.finance import forecast
    from apps.tenancy import modules
    from apps.tenancy.models import Tenant

    with tenant_context(tenant_id):
        tenant = Tenant.objects.get(pk=tenant_id)
        if not modules.has(tenant, modules.FORECAST):
            return False
        return forecast.keep_month(tenant, _today(tenant))


def _today(tenant):
    """The practice's own date: at its midnight the server's may be a day
    behind or ahead."""
    return timezone.localdate(timezone=ZoneInfo(tenant.timezone))
