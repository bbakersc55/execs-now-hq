"""The only backend probe of NMI: can this server reach it, and does NMI
accept the platform's private key. One authenticated read; nothing is
charged, stored or changed, and no card number is involved.

    NMI_LIVE_CALLS=true .venv/bin/python manage.py nmi_check

It prints the environment and the result, never a key. A charge with a
card is proved only through NMI's own card fields in a browser
(`scripts/nmi_token_proof.py`), never from here.
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.billing import gateway as gw


class Command(BaseCommand):
    help = "Check that the platform's NMI keys reach NMI and are accepted."

    def handle(self, *args, **options):
        self.stdout.write(f"NMI environment: {settings.NMI_ENVIRONMENT} "
                          f"({gw.BASE_URLS[settings.NMI_ENVIRONMENT]})")
        self.stdout.write("NMI_PRIVATE_API_KEY: "
                          + ("set" if settings.NMI_PRIVATE_API_KEY else "NOT SET"))
        self.stdout.write("NMI_PUBLIC_TOKENIZATION_KEY: "
                          + ("set" if settings.NMI_PUBLIC_TOKENIZATION_KEY else "NOT SET"))
        if not gw.live_calls_allowed():
            raise CommandError("NMI_LIVE_CALLS is off, so nothing reaches NMI. Run it as "
                               "NMI_LIVE_CALLS=true .venv/bin/python manage.py nmi_check")
        try:
            result = gw.gateway().check_connection(gw.platform_account())
        except gw.GatewayError as exc:
            raise CommandError(str(exc)) from None
        if not result.ok:
            raise CommandError(result.detail)
        self.stdout.write(self.style.SUCCESS(f"OK: {result.detail}"))
