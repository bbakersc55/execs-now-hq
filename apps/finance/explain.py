""""Explain this step" (`docs/p6_m1_reconciliation_month_close.md` §4.3).

Guided mode's steps are written in the app and always shown. This is the one
thing in the books that asks Claude, and only when its button is pressed.

- **What is sent (M1-10):** which step; the account's kind; the statement
  date and balance; the starting balance; the totals cleared in and out; the
  difference; and, on steps 4 and 5 only, the unticked lines of that one
  account and period (date, amount, description). Nothing else: no other
  account, no client list, no one's contact details. `what_is_sent` is the
  whole of it, and the test reads it.
- **It changes nothing.** It writes its `ai_call` and returns words.
- **Capped:** `DAILY_CAP` a day per practice, shared with the forecast's two
  pressed buttons, and never past the practice's monthly AI budget where one
  is set.
- **Not kept.** The answer is not stored here; the browser keeps its own copy
  for the session.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.utils import timezone

from apps.finance import reconcile
from apps.finance.disclaimer import DISCLAIMER
from apps.finance.services import FinanceError

PURPOSE = "finance_explain_step"
#: The three things in Finance that ask Claude when a person presses them
#: (owner, 2026-10-11): this, and the forecast's "Explain" and "Review"
#: (`forecast_ai.py`). They share one limit a day per practice. The worker's
#: own daily cap is for what nobody asked for, and does not count these.
PRESSED = (PURPOSE, "finance_explain_forecast", "finance_review_forecast",
           # P6 M4 decision 6, the brief winning: "Sort these with Claude".
           "personal_sort_lines",
           # P6 M4 decision 25: "Explain this budget".
           "personal_explain_budget")
DAILY_CAP = 20
#: Only these steps send the unticked lines.
WITH_LINES = (4, 5)
MAX_LINES = 60
#: Roughly what one press reads and writes, until the practice has its own
#: average: the price shown on the button before it is pressed.
TOKENS = (900, 400)
#: The ceiling on one answer: room for the model's reasoning, which is counted
#: as output, and then the answer (see `forecast_ai.MAX_TOKENS`).
MAX_TOKENS = 16000

#: The steps of guided mode, as the screen numbers them (§4.2).
STEPS = {
    1: "Get your statement",
    2: "Type its ending date and ending balance",
    3: "Tick what the statement shows",
    4: "Look at what is left",
    5: "Get the difference to zero",
    6: "Finish, and do the next account",
    7: "Check the list",
    8: "Close the month",
}

SYSTEM = (
    "You are helping the owner of a small professional practice reconcile an account "
    "in their own bookkeeping app and close the month. They may never have reconciled "
    "before. Explain the one step they are on, in plain words, in at most 150 words, "
    "using the numbers given. Say what the numbers mean and what to look at next.\n\n"
    "The books are single-entry and cash-basis. Reconciling is ticking each line of the "
    "books that the statement also shows until the difference is zero: statement balance "
    "minus (starting balance plus cleared money in minus cleared money out). For a credit "
    "card the balance is what is owed, so a charge adds to it and a payment takes away. "
    "An unticked line is usually fine: a check not yet cashed, a charge not yet posted. "
    "It carries forward to the next statement. If a later statement shows a closed month "
    "was wrong, the fix is a correcting entry in the open month, not reopening.\n\n"
    "You cannot tick, add, categorize or close anything, and must not say you did. Do "
    "not give tax, legal or financial advice: where the question is one for an "
    "accountant, say \"ask your CPA\". Do not guess at anything not in the numbers "
    "given. Plain sentences, no headings, no lists longer than three items."
)


def _dollars(cents: int) -> str:
    return f"{'-' if cents < 0 else ''}${abs(cents) / 100:,.2f}"


def what_is_sent(step: int, rec=None) -> str:
    """The whole of what goes to Claude for a step. Kept in one place so it
    can be read, and tested, as a list."""
    parts = [f"STEP {step} OF 8: {STEPS[step]}"]
    if rec is not None:
        rows = reconcile.lines(rec)
        sums = reconcile.totals(rec, rows)
        parts += [
            f"Account kind: {rec.account.get_kind_display()}",
            f"Statement ending date: {rec.statement_on.isoformat()}",
            f"Statement ending balance: {_dollars(rec.statement_balance_cents)}",
            f"Starting balance: {_dollars(sums['starting_balance_cents'])}",
            f"Cleared money in: {_dollars(sums['cleared_in_cents'])}",
            f"Cleared money out: {_dollars(sums['cleared_out_cents'])}",
            f"Difference: {_dollars(sums['difference_cents'])}",
        ]
        if step in WITH_LINES:
            left = [row for row in rows if not row["cleared"]]
            parts.append(f"UNTICKED LINES ({len(left)}):" if left else "UNTICKED LINES: none")
            for row in left[:MAX_LINES]:
                parts.append(f"- {row['on_date']} | {'in' if row['way'] == 'in' else 'out'} "
                             f"{_dollars(row['amount_cents'])} | {row['description']}")
            if len(left) > MAX_LINES:
                parts.append(f"(the first {MAX_LINES} of {len(left)})")
    return "\n".join(parts)


def _day_start(tenant) -> datetime:
    zone = ZoneInfo(tenant.timezone)
    return datetime.combine(timezone.localdate(timezone=zone), time.min, tzinfo=zone)


def _used_today(tenant) -> int:
    from apps.tenancy.models import AiCall

    return AiCall.all_objects.filter(tenant=tenant, purpose__in=PRESSED,
                                     created_at__gte=_day_start(tenant)).count()


def _over_budget(tenant) -> bool:
    from apps.tenancy import ai_budget
    from apps.tenancy.models import AiCall
    from django.db.models import Sum

    budget = tenant.ai_monthly_budget_usd
    if not budget:
        return False
    zone = ZoneInfo(tenant.timezone)
    month = timezone.localdate(timezone=zone).replace(day=1)
    spent = AiCall.all_objects.filter(
        tenant=tenant, created_at__gte=ai_budget._start_of(tenant, month)
    ).aggregate(s=Sum("cost_usd"))["s"] or Decimal("0")
    return spent >= budget


def status(tenant, purpose=PURPOSE, tokens=TOKENS) -> dict:
    """What the button says before it is pressed: about what a press costs,
    how many are left today, and why it cannot be pressed when it cannot."""
    from apps.tenancy import ai_budget, claude
    from apps.tenancy.context import tenant_context

    with tenant_context(tenant.pk):
        estimate = ai_budget.call_estimate(purpose, tokens)
    used = _used_today(tenant)
    resets = _day_start(tenant) + timedelta(days=1)
    refused = ""
    if claude.key_source(tenant) is None:
        refused = ("No Anthropic API key is set. The practice owner adds one under AI "
                   "usage.")
    elif used >= DAILY_CAP:
        refused = (f"That is today's {DAILY_CAP} explanations. More from "
                   f"{resets:%-I:%M %p} tomorrow.")
    elif _over_budget(tenant):
        refused = ("This month's AI budget is spent. Raise it under AI usage, or wait "
                   "for next month.")
    return {"estimate_usd": str(Decimal(estimate).quantize(Decimal("0.0001"))),
            "used_today": used, "cap": DAILY_CAP, "resets_at": resets.isoformat(),
            "refused": refused, "disclaimer": DISCLAIMER}


def explain(tenant, *, step, rec=None) -> dict:
    """Ask Claude about one step. Writes nothing but its `ai_call`."""
    from apps.tenancy import claude

    if isinstance(step, bool) or not isinstance(step, int) or step not in STEPS:
        raise FinanceError("step is a number from 1 to 8.")
    now = status(tenant)
    if now["refused"]:
        raise FinanceError(now["refused"], status=409)
    try:
        text, call = claude.complete_with_call(
            tenant=tenant, purpose=PURPOSE, system=SYSTEM,
            user_text=what_is_sent(step, rec), trigger="button", max_tokens=MAX_TOKENS,
            target_type="finance_reconciliation" if rec is not None else "",
            target_id=rec.pk if rec is not None else None)
    except claude.ClaudeRefused:
        raise FinanceError("Claude declined to answer that. The written step above is "
                           "what there is.", status=502) from None
    except claude.ClaudeUnavailable as exc:
        raise FinanceError(str(exc), status=502) from None
    return {"text": text, "cost_usd": str(call.cost_usd), "disclaimer": DISCLAIMER,
            "used_today": now["used_today"] + 1, "cap": DAILY_CAP}
