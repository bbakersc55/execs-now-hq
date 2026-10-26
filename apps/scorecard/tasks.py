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
    # Also part 4: a Track feed's readings, once a day each, rate-limit aware.
    """M5 part 3: every hour, read the practice's sheet feeds that are due
    (hourly ones, daily ones a day after their last read, a cell feed as its
    period closes). It writes readings for closed periods only, never over
    one typed by hand, and deletes nothing."""
    from apps.scorecard import board, feeds
    from apps.tenancy.models import Tenant

    with tenant_context(tenant_id):
        tenant = Tenant.objects.get(pk=tenant_id)
        today = board.today_for(tenant)
        sheets_done = feeds.run_due(tenant.pk, today)
        # Part 4: each Track feed once a day, on the same hourly pass.
        track_done = feeds.run_due_track(tenant.pk, today)
        # And the practice's own scorecard, "From this app", once a day each.
        app_done = feeds.run_due_app(tenant.pk, today)
        # Part 5: each HubSpot feed once a day, rate-limit aware.
        hubspot_done = feeds.run_due_hubspot(tenant.pk, today)
        return {"sheets": sheets_done, "track": track_done, "app": app_done,
                "hubspot": hubspot_done}
