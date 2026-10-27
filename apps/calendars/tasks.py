"""The worker's half: every connected calendar read every fifteen minutes."""

from __future__ import annotations

from apps.tenancy.claude import unattended_job
from apps.tenancy.context import tenant_context


@unattended_job("calendars.sync")
def sync_calendars(tenant_id: str) -> dict:
    """Each connection's window, read whole. A refused one records its error
    on itself and the rest still run."""
    from apps.calendars import sync
    from apps.calendars.models import CalendarConnection

    with tenant_context(tenant_id):
        done = {}
        for connection in CalendarConnection.objects.select_related("tenant", "user", "secret"):
            done[connection.email_address] = sync.sync(connection)
        return done
