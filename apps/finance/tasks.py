"""Scheduled work for Finance. One daily job: the bank feeds' nightly sync
(`docs/p6_bank_feeds.md`), then the month's forecast, kept. And the one queued
job: a bank connection's sync, when its provider says there is news."""

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
        # The bank feeds first, so the forecast kept today starts from them.
        sync_bank_feeds(tenant)
        if not modules.has(tenant, modules.FORECAST):
            return False
        return forecast.keep_month(tenant, _today(tenant))


def _today(tenant):
    """The practice's own date: at its midnight the server's may be a day
    behind or ahead."""
    return timezone.localdate(timezone=ZoneInfo(tenant.timezone))


def sync_bank_feeds(tenant) -> dict:
    """Every live connection of the practice, once (nightly). One that fails
    is marked and the rest still run. Never in the demo, which has no bank."""
    import logging

    from config import environment

    from apps.finance.bankfeeds import connections, providers
    from apps.finance.bankfeeds.sync import SyncRefused, run

    if environment.is_demo():
        return {}
    done = {}
    # A connection that needs attention is tried too: a warned one still
    # works, and a broken one says so again (once a day).
    for connection in connections.live(tenant):
        try:
            done[str(connection.pk)] = run(connection)
        except (SyncRefused, providers.ProviderError) as exc:
            logging.getLogger(__name__).info("nightly bank sync: %s", type(exc).__name__)
            done[str(connection.pk)] = {"error": str(exc)[:200]}
        except Exception:                       # noqa: BLE001 — the forecast still runs
            logging.getLogger(__name__).exception("nightly bank sync failed")
            done[str(connection.pk)] = {"error": "failed"}
    return done


@unattended_job("finance.sync_bank_connection")
def sync_bank_connection(tenant_id: str, connection_id: str) -> dict:
    """Queued by the provider's webhook (SYNC_UPDATES_AVAILABLE)."""
    from config import environment

    from apps.finance.bankfeeds import providers
    from apps.finance.bankfeeds.sync import SyncRefused, run
    from apps.finance.models import BankConnection

    if environment.is_demo():
        return {}
    with tenant_context(tenant_id):
        connection = BankConnection.objects.filter(pk=connection_id).first()
        if connection is None:
            return {}
        try:
            return run(connection)
        except (SyncRefused, providers.ProviderError) as exc:
            return {"error": str(exc)[:200]}
