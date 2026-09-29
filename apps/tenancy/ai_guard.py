"""What the worker may spend on Claude with nobody asking (owner, 2026-09-29).

Two rules, both applied before an **unattended** call is made, meaning a call
made inside a worker job (`claude.unattended`). A call a person caused from the
web is never counted and never stopped: the tray, Consolidate, prep, narrative
drafts, and the strategy rows that fire as a live session's answers land.

1. **The daily cap.** When today's unattended spend (practice time) has reached
   `tenant.ai_unattended_daily_cap_usd`, every further unattended call is
   skipped until midnight. The check comes before the call, so the day can run
   over the cap by at most the calls already in flight when it was reached.
2. **Twice on the same input.** An unattended call whose exact input (purpose,
   target, and a hash of the prompt) has already failed twice, **billed**, is
   skipped until a person re-runs it (`allow_again`) or it succeeds. A failure
   that cost nothing (no key, no network) does not count, so fixing the key or
   riding out an outage lets everything resume by itself.

Every skip is recorded once per item per day (`ai.unattended_skipped`), so the
banner can say what waited, and nothing is lost: each caller leaves its work
where the next run, or tomorrow's, picks it up.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db.models import Max, Sum
from django.utils import timezone

DAILY_CAP = "daily_cap"
FAILED_TWICE = "failed_twice"
FAILURES_ALLOWED = 2

SKIPPED_VERB = "ai.unattended_skipped"
RERUN_VERB = "ai.rerun_allowed"


def _day(tenant, now=None):
    zone = ZoneInfo(tenant.timezone)
    today = (now or timezone.now()).astimezone(zone).date()
    start = datetime.combine(today, time.min, tzinfo=zone)
    return today, start, start + timedelta(days=1)


def spent_today(tenant, now=None) -> Decimal:
    from apps.tenancy.models import AiCall

    _, start, end = _day(tenant, now)
    total = AiCall.all_objects.filter(
        tenant=tenant, unattended=True, created_at__gte=start, created_at__lt=end,
    ).aggregate(s=Sum("cost_usd"))["s"]
    return Decimal(total or 0)


def cap_reached(tenant, now=None) -> bool:
    return spent_today(tenant, now) >= tenant.ai_unattended_daily_cap_usd


def failures_since_reset(tenant, *, purpose, target_type, target_id, input_hash) -> int:
    """Billed unattended failures of this exact input since it last succeeded
    or a person last asked for it again."""
    from apps.tenancy.models import AiCall, AuditEvent

    same = AiCall.all_objects.filter(tenant=tenant, purpose=purpose,
                                     target_type=target_type, target_id=target_id)
    marks = [same.filter(succeeded=True).aggregate(m=Max("created_at"))["m"],
             AuditEvent.all_objects.filter(
                 tenant=tenant, verb=RERUN_VERB, target_type=target_type,
                 target_id=target_id, payload__purpose=purpose,
             ).aggregate(m=Max("created_at"))["m"]]
    since = max((m for m in marks if m), default=None)
    failed = same.filter(unattended=True, succeeded=False, output_tokens__gt=0,
                         input_hash=input_hash)
    if since:
        failed = failed.filter(created_at__gt=since)
    return failed.count()


def refusal(tenant, *, purpose, target_type, target_id, input_hash, now=None) -> str | None:
    """Why this unattended call must not be made, or None."""
    if cap_reached(tenant, now):
        return DAILY_CAP
    if target_id and failures_since_reset(
            tenant, purpose=purpose, target_type=target_type, target_id=target_id,
            input_hash=input_hash) >= FAILURES_ALLOWED:
        return FAILED_TWICE
    return None


def record_skip(tenant, *, reason, purpose, target_type, target_id, job, now=None):
    """Once per item, reason and day: the worker comes back every minute, and a
    thousand identical rows would bury the one line that matters."""
    from apps.tenancy.models import AuditEvent

    today, start, end = _day(tenant, now)
    already = AuditEvent.all_objects.filter(
        tenant=tenant, verb=SKIPPED_VERB, created_at__gte=start, created_at__lt=end,
        target_type=target_type, target_id=target_id,
        payload__purpose=purpose, payload__reason=reason).exists()
    if not already:
        AuditEvent.all_objects.create(
            tenant=tenant, actor=None, verb=SKIPPED_VERB, target_type=target_type,
            target_id=target_id,
            payload={"reason": reason, "purpose": purpose, "job": job,
                     "day": today.isoformat()})


def allow_again(tenant, *, purpose, target_type, target_id, actor=None):
    """A person re-runs it: its two failures no longer stop the worker."""
    from apps.tenancy.models import AuditEvent

    AuditEvent.all_objects.create(
        tenant=tenant, actor=actor, verb=RERUN_VERB, target_type=target_type,
        target_id=target_id, payload={"purpose": purpose})


def status(tenant, *, financial: bool, now=None) -> dict:
    """For the banners. `financial` (the FF) adds the amounts (FR-0.9: spend is
    the FF's); every staff role sees that automatic work is paused, because a
    queue that is empty and a queue that is paused look the same otherwise."""
    from apps.tenancy.models import AuditEvent

    today, start, end = _day(tenant, now)
    skips = AuditEvent.all_objects.filter(
        tenant=tenant, verb=SKIPPED_VERB, created_at__gte=start, created_at__lt=end)
    paused = cap_reached(tenant, now)
    out = {
        "paused": paused,
        "resumes_at": end.isoformat() if paused else None,
        "skipped_today": skips.filter(payload__reason=DAILY_CAP).count(),
        "stopped_after_two_failures": skips.filter(payload__reason=FAILED_TWICE).count(),
    }
    if financial:
        out.update({
            "cap_usd": str(tenant.ai_unattended_daily_cap_usd),
            "spent_today_usd": str(spent_today(tenant, now).quantize(Decimal("0.01"))),
            "skipped": [{"reason": e.payload.get("reason"), "purpose": e.payload.get("purpose"),
                         "job": e.payload.get("job"), "target_type": e.target_type,
                         "target_id": str(e.target_id) if e.target_id else None,
                         "at": e.created_at.isoformat()}
                        for e in skips.order_by("-created_at")[:50]],
        })
    return out
