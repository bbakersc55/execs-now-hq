"""The tool builder (P12): the practice owner describes a worksheet, and
Claude, on the practice's own key, proposes its sections, fields and formulas.
The price is said first; a press is capped per day and refused when the
month's AI budget is spent. What comes back is checked against the engine
before it is shown, then previewed and edited in the form editor; nothing is
saved until the owner saves it as the practice's own tool."""

from __future__ import annotations

import json
import re
from datetime import timedelta
from decimal import Decimal

from . import definition as D

PURPOSE = "tool_builder"
TOKENS = (3500, 2500)
DAILY_CAP = 20
MAX_TOKENS = 6000

SYSTEM = """You design a worksheet tool for a fractional executive's practice. Reply
with JSON only: {"name": "...", "description": "...", "definition": {...}}.

The definition is {"sections": [...], "results": [...]}:
- a section is {"title", "fields": [...]};
- a field is {"key", "label", "type"} where key is lower_snake_case and type is
  one of: text, long_text, number, money, percent, date, choice (add "options":
  [...]), person, people, table, computed;
- a table field has "columns": [fields of those types, or computed];
- a computed field or column has "formula" and "format" (number, money,
  percent, text, list, hours, people);
- a result is {"key", "label", "formula", "format", "note"}.

Formulas use only: numbers, "strings", + - * / ^, parentheses, = != < <= > >=,
and, or, not, a field's key, a table's column as table.column, and inside a
table's computed column the row's own column keys; functions sum, average,
min, max, count, if(cond, a, b), round(x, places), abs, sumif(keys, match,
values), countif(values, match), argmax(labels, values), argmin(labels,
values), filter(labels, flags). Guard every division with if(), for example
if(b > 0, a / b, 0). Percent fields hold whole percents (25 means 25%).

Use plain words. Never use a named management system's own terms. Keep it
small: at most 6 sections, 30 fields and 8 results."""


class BuilderRefused(ValueError):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def _used_today(tenant) -> int:
    from apps.scorecard.ai import _day_start
    from apps.tenancy.models import AiCall

    return AiCall.all_objects.filter(tenant=tenant, purpose=PURPOSE,
                                     created_at__gte=_day_start(tenant)).count()


def status(tenant) -> dict:
    from apps.scorecard.ai import _day_start, _over_budget
    from apps.tenancy import ai_budget, claude
    from apps.tenancy.context import tenant_context
    from apps.tenancy.demo import visitors

    with tenant_context(tenant.pk):
        estimate = ai_budget.call_estimate(PURPOSE, TOKENS)
    used = _used_today(tenant)
    resets = _day_start(tenant) + timedelta(days=1)
    refused = ""
    stop = visitors.ai_stop(tenant)
    if stop:
        refused = stop
    elif claude.key_source(tenant) is None:
        refused = ("No Anthropic API key is set. The practice owner adds one under AI "
                   "usage.")
    elif used >= DAILY_CAP:
        refused = f"That is today's {DAILY_CAP} tool proposals. More tomorrow."
    elif _over_budget(tenant):
        refused = ("This month's AI budget is spent. Raise it under AI usage, or wait "
                   "for next month.")
    return {"estimate_usd": str(Decimal(estimate).quantize(Decimal("0.0001"))),
            "used_today": used, "cap": DAILY_CAP, "resets_at": resets.isoformat(),
            "refused": refused}


def propose(tenant, description: str) -> dict:
    """One press: a proposed tool, checked, not saved."""
    from apps.tenancy import claude

    description = (description or "").strip()
    if len(description) < 12:
        raise BuilderRefused("Say what the worksheet is for in a sentence or two.", 400)
    now = status(tenant)
    if now["refused"]:
        raise BuilderRefused(now["refused"])
    try:
        text, call = claude.complete_with_call(
            tenant=tenant, purpose=PURPOSE, system=claude.drafting(SYSTEM),
            user_text=f"The worksheet the owner wants:\n{description[:4000]}",
            trigger="button", max_tokens=MAX_TOKENS, target_type="tenant", target_id=tenant.pk)
    except claude.ClaudeRefused:
        raise BuilderRefused("Claude declined to design that.", 502) from None
    except claude.ClaudeUnavailable as exc:
        raise BuilderRefused(str(exc), 502) from None
    match = re.search(r"\{.*\}", text or "", re.S)
    try:
        data = json.loads(match.group(0)) if match else None
    except ValueError:
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("definition"), dict):
        raise BuilderRefused("Claude's answer couldn't be read as a tool. Try again.", 502)
    definition = data["definition"]
    return {"name": " ".join(str(data.get("name") or "New tool").split())[:120],
            "description": str(data.get("description") or "")[:2000],
            "definition": definition, "errors": D.check(definition),
            "cost_usd": str(call.cost_usd), "used_today": now["used_today"] + 1,
            "cap": DAILY_CAP}
