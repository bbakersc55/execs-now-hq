"""The only backend probe of NMI: can this server reach it, and does NMI
accept the platform's private key. One authenticated read; nothing is
charged, stored or changed, and no card number is involved.

    NMI_LIVE_CALLS=true .venv/bin/python manage.py nmi_check

It prints the environment and the result, never a key. It also prints what
web and the worker last reported about their own real calls (2026-11-17)
and fails when the worker's are off or the two disagree. A charge with a
card is proved only through NMI's own card fields in a browser
(`scripts/nmi_token_proof.py`), never from here.
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.billing import gateway as gw


class Command(BaseCommand):
    help = "Check that the platform's NMI keys reach NMI and are accepted."

    def _services(self) -> str:
        """2026-11-17: both services' own reports, and whether they agree.
        Returns the problem, or ""."""
        from django.utils import timezone

        from apps.billing import worker_state
        from apps.billing.models import ServiceReport

        here = worker_state.this_service() or "this shell"
        self.stdout.write(f"Here ({here}): real calls "
                          f"{'on' if gw.live_calls_allowed() else 'OFF'}")
        now = timezone.now()
        rows = {row.service: row for row in ServiceReport.objects.all()}
        for service in worker_state.SERVICES:
            row = rows.get(service)
            if row is None:
                self.stdout.write(f"{service}: has not reported")
                continue
            minutes = int((now - row.reported_at).total_seconds() // 60)
            self.stdout.write(f"{service}: real calls {'on' if row.live_calls else 'OFF'} "
                              f"({row.app_environment}, reported {minutes} min ago)")
        web, worker = rows.get("web"), rows.get("worker")
        if worker is not None and not worker.live_calls:
            return ("The worker has real calls OFF: every scheduled card job is refused. "
                    "Set NMI_LIVE_CALLS=true on the qcluster service.")
        if web is not None and worker is not None and web.live_calls != worker.live_calls:
            return "Web and the worker disagree about NMI_LIVE_CALLS."
        return ""

    def handle(self, *args, **options):
        services = self._services()
        self.stdout.write(f"NMI environment: {settings.NMI_ENVIRONMENT} "
                          f"(https://{gw.api_host(settings.NMI_ENVIRONMENT)}/api/v5)")
        self.stdout.write("NMI_PRIVATE_API_KEY: "
                          + ("set" if settings.NMI_PRIVATE_API_KEY else "NOT SET"))
        self.stdout.write("NMI_PUBLIC_TOKENIZATION_KEY: "
                          + ("set" if settings.NMI_PUBLIC_TOKENIZATION_KEY else "NOT SET"))
        if not gw.live_calls_allowed():
            raise CommandError("NMI_LIVE_CALLS is off, so nothing reaches NMI. Run it as "
                               "NMI_LIVE_CALLS=true .venv/bin/python manage.py nmi_check"
                               + (f" {services}" if services else ""))
        try:
            result = gw.gateway().check_connection(gw.platform_account())
        except gw.GatewayError as exc:
            raise CommandError(str(exc)) from None
        if not result.ok:
            raise CommandError(result.detail)
        self.stdout.write(self.style.SUCCESS(f"OK: {result.detail}"))
        if services:
            raise CommandError(services)
