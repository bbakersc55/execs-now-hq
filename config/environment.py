"""Which of the three environments this is (owner, 2026-09-29).

- **local** — the laptop, debug.
- **demo** — demo.getexecutivesnow.com: deploys from `dev`, its own database
  seeded with a fictional practice (`manage.py seed_demo`). No worker, no
  Drive or mailbox reading. **It sends only through its redirect** (owner,
  2026-10-08): every message has its recipient replaced by
  `DEMO_MAIL_REDIRECT` before it is built, carries a banner naming who it was
  for, and leaves from `DEMO_MAIL_FROM` through a send-only Gmail connection
  of the demo's own. With no redirect set, or no such connection, it sends
  nothing, as before. A "Demo" banner for staff.
- **production** — app.getexecutivesnow.com: deploys from `main` on "release".

The demo's promises are kept in code, not by configuration alone: a demo with
a worker added by mistake still sends nothing and reads nothing.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

from django.conf import settings

LOCAL, DEMO, PRODUCTION = "local", "demo", "production"

DEMO_REFUSAL = ("This is the demo. It never reads a real mailbox or Drive, and sends "
                "only to its own redirect address, so this is switched off here.")


def is_demo() -> bool:
    return settings.APP_ENVIRONMENT == DEMO or bool(getattr(settings, "IS_DEMO", False))


# ------------------------------------------------------- the demo's mail

_quiet = ContextVar("demo_mail_quiet", default=False)


@contextmanager
def quiet_mail():
    """Nothing leaves while this is open, redirect or not. The seed runs
    inside it: it sends two years of invoices and digests through the app's
    own code, and none of them is for anyone's inbox."""
    token = _quiet.set(True)
    try:
        yield
    finally:
        _quiet.reset(token)


def mail_is_quiet() -> bool:
    return _quiet.get()


def demo_redirect() -> str:
    """The one address the demo may send to, or "" when it sends nothing."""
    if not is_demo() or mail_is_quiet():
        return ""
    return settings.DEMO_MAIL_REDIRECT


def demo_sender() -> str:
    return settings.DEMO_MAIL_FROM


def demo_banner(name: str, address: str) -> str:
    who = f"{name} <{address}>" if (name or "").strip() else address
    return f"Demo: originally addressed to {who}"
