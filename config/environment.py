"""Which of the three environments this is (owner, 2026-09-29).

- **local** — the laptop, debug.
- **demo** — demo.getexecutivesnow.com: deploys from `dev`, its own database
  seeded with a fictional practice (`manage.py seed_demo`), and nothing that
  reaches anyone. No worker, no outbound email, no Drive or mailbox reading,
  no Google connection. A "Demo" banner for staff.
- **production** — app.getexecutivesnow.com: deploys from `main` on "release".

The demo's promises are kept in code, not by configuration alone: a demo with
a worker added by mistake still sends nothing and reads nothing.
"""

from __future__ import annotations

from django.conf import settings

LOCAL, DEMO, PRODUCTION = "local", "demo", "production"

DEMO_REFUSAL = ("This is the demo. It sends no email and never reads a real mailbox "
                "or Drive, so this is switched off here.")


def is_demo() -> bool:
    return settings.APP_ENVIRONMENT == DEMO
