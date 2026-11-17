"""This service says whether it can reach the card processor (2026-11-17).

Run by each start script (`scripts/start_web.sh`, `scripts/start_qcluster.sh`)
with `APP_SERVICE` set, so Practices and Settings → Billing can warn when web
and the worker disagree. Writes one row; reads nothing from the processor.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.billing import gateway as gw
from apps.billing import worker_state


class Command(BaseCommand):
    help = "Record whether this service has real calls to the card processor on."

    def handle(self, *args, **options):
        service = worker_state.this_service()
        if not service:
            self.stdout.write("APP_SERVICE is not web or worker here: nothing reported.")
            return
        worker_state.report()
        self.stdout.write(f"{service}: real calls to the card processor "
                          f"{'on' if gw.live_calls_allowed() else 'OFF'}.")
