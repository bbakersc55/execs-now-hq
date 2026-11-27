"""The daily card page check (docs/p16_card_page_scripts.md), registered
once for the platform by `ensure_schedules` (`PLATFORM_SCHEDULES`)."""

from __future__ import annotations

import logging

from django.conf import settings

log = logging.getLogger(__name__)


def daily_check() -> str:
    """Production only: the live pages are production's. Elsewhere nothing
    is read (the laptop is not live; the demo has no worker)."""
    if settings.APP_ENVIRONMENT != "production":
        log.info("card pages: the daily check runs in production only (here: %s)",
                 settings.APP_ENVIRONMENT)
        return "skipped"
    from . import check

    row = check.run()
    log.info("card pages: daily check %s (%d difference(s))", row.outcome, len(row.differences))
    return row.outcome
