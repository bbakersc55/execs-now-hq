"""Claude maps a number to an MCP server's tool (P13, "Any MCP server").

The person describes the number they want; Claude, on the practice's own key
with the price said first, proposes the tool, its arguments (with period
placeholders) and the path to the number in the answer. The app then runs it
once, live, and shows what came back; nothing is saved until the person
confirms. After that the nightly read is the saved tool call, with no AI.
"""

from __future__ import annotations

import json
import re
from datetime import timedelta
from decimal import Decimal

from .rails import PLACEHOLDERS, RailRefused

PURPOSE = "rail_mcp_map"
TOKENS = (5000, 700)
DAILY_CAP = 20
MAX_TOKENS = 2000

SYSTEM = """You map one business number to a call of an MCP server's tool, so an app can
read it for each period without asking you again. You are given the server's tools
(name, description and input schema), the number wanted, and the KPI's cadence.

Reply with JSON only: {"tool": "...", "arguments": {...}, "path": "...", "why": "..."}.
- "tool" is one of the listed tools' names, exactly.
- "arguments" fill the tool's input schema. Where a date or period belongs, write a
  placeholder, which the app fills for each period: {period_start} and {period_end}
  (YYYY-MM-DD), {period_start_iso} and {period_end_iso} (date and time, UTC), {year},
  {month} (two digits), {quarter}.
- "path" says where the number is in the tool's answer, as a dotted path with [n]
  for a list's item: "total", "data.count", "rows[0].value". Guess the likeliest
  from the description; the app shows the real answer before anything is saved.
- "why" is one plain sentence.
Use only the tools listed. If none can give the number, reply {"tool": "", "why": "..."}."""


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
    refused = ""
    stop = visitors.ai_stop(tenant)
    if stop:
        refused = stop
    elif claude.key_source(tenant) is None:
        refused = ("No Anthropic API key is set. The practice owner adds one under AI "
                   "usage.")
    elif used >= DAILY_CAP:
        refused = f"That is today's {DAILY_CAP} proposals. More tomorrow, or set it by hand."
    elif _over_budget(tenant):
        refused = ("This month's AI budget is spent. Set the tool by hand, or raise the "
                   "budget under AI usage.")
    return {"estimate_usd": str(Decimal(estimate).quantize(Decimal("0.0001"))),
            "used_today": used, "cap": DAILY_CAP,
            "resets_at": (_day_start(tenant) + timedelta(days=1)).isoformat(),
            "refused": refused}


def propose(tenant, kpi, tools: list[dict], description: str) -> dict:
    from apps.tenancy import claude

    description = (description or "").strip()
    if len(description) < 6:
        raise RailRefused("Say what number you want, in a sentence.")
    if not tools:
        raise RailRefused("Test the connection first: it lists the server's tools.", 409)
    now = status(tenant)
    if now["refused"]:
        raise RailRefused(now["refused"], 409)
    listing = json.dumps([{"name": t["name"], "description": t.get("description", ""),
                           "input_schema": t.get("input_schema", {})} for t in tools])[:20000]
    user = (f"The number wanted: {description[:1000]}\nThe KPI: {kpi.name} "
            f"({kpi.get_kind_display()}, read {kpi.cadence}).\nPlaceholders: "
            + ", ".join("{" + p + "}" for p in PLACEHOLDERS) + f"\nThe tools: {listing}")
    try:
        text, call = claude.complete_with_call(
            tenant=tenant, purpose=PURPOSE, system=claude.drafting(SYSTEM), user_text=user,
            trigger="button", max_tokens=MAX_TOKENS, target_type="kpi", target_id=kpi.pk)
    except claude.ClaudeRefused:
        raise RailRefused("Claude declined to map that.", 502) from None
    except claude.ClaudeUnavailable as exc:
        raise RailRefused(str(exc), 502) from None
    match = re.search(r"\{.*\}", text or "", re.S)
    try:
        data = json.loads(match.group(0)) if match else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise RailRefused("Claude's answer couldn't be read. Try again, or set it by hand.", 502)
    names = {t["name"] for t in tools}
    tool = str(data.get("tool") or "")
    if tool and tool not in names:
        raise RailRefused(f"Claude named a tool the server doesn't have ({tool}). Try again, "
                          "or set it by hand.", 502)
    arguments = data.get("arguments") if isinstance(data.get("arguments"), dict) else {}
    return {"tool": tool, "arguments": arguments, "path": str(data.get("path") or "")[:200],
            "why": str(data.get("why") or "")[:500], "cost_usd": str(call.cost_usd),
            "used_today": now["used_today"] + 1, "cap": DAILY_CAP}
