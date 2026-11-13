"""Claude's drafts for a plan (P11, "Drafts from sources").

"Draft from sources" on a horizon, and "Break this down" on an item, ask
Claude for proposed items on the practice's own key at the Deep tier. The
price is said before the press; each press is capped per practice per day,
and refused when the month's AI budget is spent, as the scorecard's buttons
are. What comes back lands in the plan's tray as proposals, each naming
the sources it drew on, for a person to accept, edit or discard. Nothing is
put on the plan by Claude.
"""

from __future__ import annotations

import json
import re
from datetime import timedelta
from decimal import Decimal

from . import periods as P
from .models import Horizon, PlanItem
from .sources import WHAT, gather

PURPOSE = "plan_draft"
#: About what one press sends and gets back, for the price said first.
TOKENS = (7000, 1600)
DAILY_CAP = 20
MAX_TOKENS = 4000
MOST_ITEMS = 8

SYSTEM = """You draft items for one company's plan, which a fractional executive
reviews before anything is kept. The plan has five horizons: the three-year
picture, the year's goals, the quarter's priorities, the month's plan and the
week's sprint. Each item serves the item above it.

Write in plain business English for an owner-led company. Never use a named
management system's own terms for priorities, meetings, roles or charts: say
"priority", "weekly meeting", "owner", "second-in-command" and "org chart".

Use only what the sources say. Do not invent numbers, names or dates that are
not in them. Each item has:
- "title": short, specific, starting with a verb for anything below the picture;
- "done_means": one sentence saying how anyone will know it is done;
- "serves": the id of the item above it that it serves, from the list given,
  or null;
- "drew_on": the source refs (like "S1") it came from; at least one.

Reply with JSON only, no prose: {"items": [ ... ]}. At most 8 items; fewer is
better than padding."""


class DraftRefused(ValueError):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def _used_today(tenant) -> int:
    from apps.scorecard.ai import _day_start
    from apps.tenancy.models import AiCall

    return AiCall.all_objects.filter(tenant=tenant, purpose=PURPOSE,
                                     created_at__gte=_day_start(tenant)).count()


def status(tenant) -> dict:
    """What the button says before it is pressed."""
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
        refused = (f"That is today's {DAILY_CAP} plan drafts. More from "
                   f"{resets:%-I:%M %p} tomorrow.")
    elif _over_budget(tenant):
        refused = ("This month's AI budget is spent. Raise it under AI usage, or wait "
                   "for next month.")
    return {"estimate_usd": str(Decimal(estimate).quantize(Decimal("0.0001"))),
            "used_today": used, "cap": DAILY_CAP, "resets_at": resets.isoformat(),
            "refused": refused}


def _chain(item) -> list:
    out, seen = [], set()
    while item is not None and item.pk not in seen:
        seen.add(item.pk)
        out.append(item)
        item = item.parent
    return out


def what_is_sent(access, horizon, period_start, parent, sources) -> tuple[str, dict]:
    """The prompt's user text, and {id: item} of the items it may serve."""
    from .read import horizon_names

    company = access.company
    names = horizon_names(company.tenant)
    lines = [f"Company: {company.name}",
             f"Draft: {WHAT[horizon]}. Horizon: {names[horizon]} "
             f"({P.label(horizon, period_start)})."]
    above = P.above(horizon)
    serves = {}
    if above is not None:
        candidates = PlanItem.all_objects.filter(
            company=company, horizon=above, state=PlanItem.State.ACCEPTED,
            period_start=P.start_of(above, period_start, company))
        for item in candidates:
            serves[str(item.pk)] = item
        if serves:
            lines.append(f"\nItems on {names[above]} it may serve (id: title):")
            lines += [f"- {k}: {v.title}" for k, v in serves.items()]
    if parent is not None:
        lines.append("\nBreak this item down into the items beneath it:")
        for node in _chain(parent):
            lines.append(f"- {names[node.horizon]}: {node.title}"
                         + (f" (done means: {node.done_means})" if node.done_means else ""))
        serves[str(parent.pk)] = parent
    here = PlanItem.all_objects.filter(company=company, horizon=horizon,
                                       period_start=period_start,
                                       state=PlanItem.State.ACCEPTED)
    if here.exists():
        lines.append(f"\nAlready on {names[horizon]} (don't repeat these):")
        lines += [f"- {i.title}" for i in here]
    if sources:
        lines.append("\nSources:")
        for ref, label, text in sources:
            lines.append(f"\n[{ref}] {label}\n{text}")
    return "\n".join(lines), serves


def _parse(text) -> list:
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        raise DraftRefused("Claude's answer couldn't be read. Try again.", 502)
    try:
        data = json.loads(match.group(0))
    except ValueError:
        raise DraftRefused("Claude's answer couldn't be read. Try again.", 502) from None
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise DraftRefused("Claude's answer couldn't be read. Try again.", 502)
    return items[:MOST_ITEMS]


def draft(access, *, horizon, period_start, parent=None, chosen=(), pasted="", actor,
          today) -> dict:
    """One press: proposals into the tray. Returns them with what it cost."""
    from apps.tenancy import claude

    if horizon not in Horizon.values:
        raise DraftRefused("Choose a horizon.", 400)
    if horizon == Horizon.WEEK and parent is None and PlanItem.all_objects.filter(
            company=access.company, horizon=Horizon.WEEK, period_start=period_start,
            state=PlanItem.State.ACCEPTED).exists():
        raise DraftRefused(f"{P.label(horizon, period_start)} already has its sprint.")
    company = access.company
    now = status(company.tenant)
    if now["refused"]:
        raise DraftRefused(now["refused"])
    sources = gather(access, list(chosen or []), pasted)
    if not sources and parent is None:
        raise DraftRefused("Choose at least one source, or paste some text.", 400)
    user_text, serves = what_is_sent(access, horizon, period_start, parent, sources)
    try:
        text, call = claude.complete_with_call(
            tenant=company.tenant, purpose=PURPOSE, system=claude.drafting(SYSTEM),
            user_text=user_text, trigger="button", max_tokens=MAX_TOKENS,
            target_type="company", target_id=company.pk)
    except claude.ClaudeRefused:
        raise DraftRefused("Claude declined to draft that.", 502) from None
    except claude.ClaudeUnavailable as exc:
        raise DraftRefused(str(exc), 502) from None
    labels = {ref: label for ref, label, _ in sources}
    made = []
    for raw in _parse(text):
        if not isinstance(raw, dict):
            continue
        title = " ".join(str(raw.get("title") or "").split())[:300]
        if not title:
            continue
        drew = [labels[r] for r in raw.get("drew_on") or [] if isinstance(r, str)
                and r in labels]
        if parent is not None and not drew:
            drew = [f"{parent.title} (the item above)"]
        serve = serves.get(str(raw.get("serves") or "")) or parent
        made.append(PlanItem.all_objects.create(
            tenant_id=company.tenant_id, company=company, horizon=horizon,
            period_start=period_start, title=title,
            done_means=str(raw.get("done_means") or "").strip()[:2000],
            parent=serve if serve is not None and serve.horizon == P.above(horizon) else None,
            state=PlanItem.State.PROPOSED,
            source=PlanItem.Source.BREAKDOWN if parent is not None else PlanItem.Source.DRAFT,
            drew_on=drew, ai_call=call, created_by=actor))
    return {"made": made, "cost_usd": str(call.cost_usd),
            "used_today": now["used_today"] + 1, "cap": DAILY_CAP}
