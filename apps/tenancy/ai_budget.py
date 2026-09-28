"""What is left on the Anthropic account, and whether the next thing fits
(owner, 2026-09-28).

**An estimate, always said to be one.** Anthropic's API does not report the
account balance, so the FF enters the credits on the account when they top up,
with the date, and the app subtracts every call it has logged since the start
of that day (practice time). Calls made with the same key outside this app are
invisible to it, which is one reason it is an estimate.

**Warnings, not blocks.** Passing 80% of the monthly budget, or an estimated
balance below what the running import still needs, is a banner. Only an import
or a Consolidate that would itself run past the estimate asks first — and then
it is a question, not a refusal: the balance is a guess, and the FF may know
better.
"""

from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Avg, Sum
from django.utils import timezone

CONSOLE_URL = "https://console.anthropic.com/"
#: Where the monthly-budget banner starts.
BUDGET_WARN_AT = Decimal("0.8")


def _start_of(tenant, day) -> datetime:
    return datetime.combine(day, time.min, tzinfo=ZoneInfo(tenant.timezone))


def _spent_since(since: datetime) -> Decimal:
    from apps.tenancy.models import AiCall

    total = AiCall.objects.filter(created_at__gte=since).aggregate(s=Sum("cost_usd"))["s"]
    return Decimal(total or 0)


def call_estimate(purpose: str, tokens: tuple[int, int]) -> Decimal:
    """What one call of this kind costs: this practice's own average once it
    has one, the model's price for `tokens` until then."""
    from apps.tenancy import claude
    from apps.tenancy.models import AiCall

    average = AiCall.objects.filter(purpose=purpose, succeeded=True,
                                    cost_usd__gt=0).aggregate(a=Avg("cost_usd"))["a"]
    if average:
        return Decimal(average)
    return claude.cost_of(settings.ANTHROPIC_MODEL, *tokens)


def next_import(tenant) -> dict | None:
    """The folder import still running, and what the rest of it should cost."""
    from apps.meetings.backfill import per_note_estimate
    from apps.meetings.models import DriveBackfill

    running = DriveBackfill.objects.filter(state=DriveBackfill.State.RUNNING).first()
    if running is None or running.remaining == 0:
        return None
    per_note, _ = per_note_estimate(tenant)
    return {"remaining": running.remaining,
            "cost_usd": (per_note * running.remaining).quantize(Decimal("0.01"))}


def estimated_balance(tenant) -> Decimal | None:
    if tenant.ai_credits_usd is None or tenant.ai_credits_as_of is None:
        return None
    return (tenant.ai_credits_usd
            - _spent_since(_start_of(tenant, tenant.ai_credits_as_of))).quantize(
                Decimal("0.01"))


def state(tenant) -> dict:
    """Everything the AI usage screen and the dashboard say about money left."""
    today = timezone.localdate(timezone=ZoneInfo(tenant.timezone))
    month_start = today.replace(day=1)
    month_spend = _spent_since(_start_of(tenant, month_start)).quantize(Decimal("0.01"))
    balance = estimated_balance(tenant)
    coming = next_import(tenant)
    budget = tenant.ai_monthly_budget_usd

    warnings = []
    if budget and month_spend >= budget * BUDGET_WARN_AT:
        share = int(month_spend / budget * 100)
        warnings.append({
            "kind": "budget",
            "message": (f"AI spend this month is ${month_spend} — {share}% of the "
                        f"${budget} monthly budget."),
        })
    if balance is not None and coming and balance < coming["cost_usd"]:
        warnings.append({
            "kind": "balance",
            "message": (f"The estimated balance (${balance}) is less than the "
                        f"${coming['cost_usd']} the running import still needs "
                        f"for {coming['remaining']} notes. Top up, or it may stop "
                        "part-way."),
        })
    elif balance is not None and balance <= 0:
        warnings.append({
            "kind": "balance",
            "message": f"The estimated balance is ${balance}. Claude calls may start "
                       "failing until the account is topped up.",
        })

    return {
        "console_url": CONSOLE_URL,
        "credits_usd": str(tenant.ai_credits_usd) if tenant.ai_credits_usd is not None else None,
        "credits_as_of": tenant.ai_credits_as_of.isoformat() if tenant.ai_credits_as_of else None,
        "spent_since_credits": (str((tenant.ai_credits_usd - balance).quantize(Decimal("0.01")))
                                if balance is not None else None),
        "estimated_balance": str(balance) if balance is not None else None,
        "monthly_budget_usd": str(budget) if budget is not None else None,
        "month_spend": str(month_spend),
        "month_start": month_start.isoformat(),
        "next_import": ({"remaining": coming["remaining"], "cost_usd": str(coming["cost_usd"])}
                        if coming else None),
        "warnings": warnings,
    }


def over_balance(tenant, cost: Decimal) -> dict | None:
    """When `cost` would run past the estimated balance: what to ask the
    person before going ahead. `None` when it fits, or when no credits have
    been entered (there is nothing to measure against)."""
    balance = estimated_balance(tenant)
    if balance is None or cost <= balance:
        return None
    return {"needs_confirmation": True, "estimated_balance": str(balance),
            "estimated_cost": str(cost.quantize(Decimal("0.01")))}
