"""Scheduled work for the scorecard."""

from __future__ import annotations

from apps.tenancy.claude import unattended_job
from apps.tenancy.context import tenant_context


# The worker's own, like every scheduled job. It makes no Claude call.
@unattended_job("scorecard.remind_missing")
def remind_missing(tenant_id: str) -> int:
    """One reminder to each reading owner whose KPI's period closed without a
    value (M5 part 1). It changes no reading."""
    from apps.scorecard import board, readings
    from apps.tenancy.models import Tenant

    with tenant_context(tenant_id):
        tenant = Tenant.objects.get(pk=tenant_id)
        return readings.remind(tenant, board.today_for(tenant))


# The worker's own. It makes no Claude call.
@unattended_job("scorecard.read_feeds")
def read_feeds(tenant_id: str) -> dict:
    """M5 part 3: every hour, read the practice's sheet feeds that are due
    (hourly ones, daily ones a day after their last read, a cell feed as its
    period closes). It writes readings for closed periods only, never over
    one typed by hand, and deletes nothing."""
    from apps.scorecard import board, feeds
    from apps.tenancy.models import Tenant

    with tenant_context(tenant_id):
        tenant = Tenant.objects.get(pk=tenant_id)
        return feeds.run_due(tenant.pk, board.today_for(tenant))
