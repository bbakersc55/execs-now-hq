""""Sort these with Claude" (P6 M4 decision 6): one button on To sort.

- **Priced first, costed after:** the button says about what a press costs
  before it is pressed, and the answer says what it did cost (an `ai_call`).
- **Capped** (the brief wins, 2026-10-15): one count on Finance's shared 20
  a day (`apps.finance.explain.PRESSED`), and never past the practice's
  monthly AI budget.
- **What is sent** (decisions 6 and 25): for each waiting line its
  description as the bank printed it (the merchant's name, which the button
  says), its amount and which way it went; and the names of the categories
  to choose from. Never an account's name or number, a balance, or the
  owner's name. `what_is_sent` is the whole of it, and the test reads it.
- **It proposes; the owner decides.** Nothing is stored or changed by the
  call. Each proposal is a side and a category the owner accepts (all at
  once, or after editing), through the ordinary sort route, and an accepted
  proposal becomes a rule.
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings

from apps.finance import explain
from apps.finance.disclaimer import DISCLAIMER
from apps.finance.models import FinanceCategory, FinanceEntry
from apps.finance.services import FinanceError
from apps.personal.models import PersonalCategory, PersonalLine
from apps.personal.services import PersonalError

PURPOSE = "personal_sort_lines"
MOST = 80
MAX_TOKENS = 16000

SYSTEM = (
    "You are helping the owner of a small professional practice sort lines from their "
    "bank and card statements in their own bookkeeping app. Each line is either "
    "PERSONAL (the household's own spending or income) or BUSINESS (the practice's). "
    "For each line, propose its side and one category from the list for that side, "
    "using only the ids given. Answer with one JSON object and nothing else:\n"
    "{\"lines\": [{\"id\": \"L1\", \"side\": \"personal\", \"category\": \"P4\", "
    "\"match\": \"COSTCO\", \"why\": \"…\"}]}\n"
    "side is personal or business. category is a P id for personal, a B id for "
    "business. match is a short piece of the line's own description, at least three "
    "characters, that names the merchant, so the choice can be remembered for lines "
    "like it. why is one plain sentence of at most 120 characters. Leave out a line "
    "you cannot judge. Do not give tax, legal or financial advice, and do not say "
    "whether anything is tax-deductible.")


def waiting(ledger, tenant) -> list[dict]:
    """What waits in To sort, as the screen lists it: a Mixed account's line
    with no side, and a ledger line with no category."""
    out = []
    for entry in FinanceEntry.all_objects.filter(
            tenant=tenant, side=FinanceEntry.Side.TO_SORT, removed_at__isnull=True
    ).order_by("-on_date")[:MOST]:
        out.append({"kind": "entry", "id": str(entry.pk), "description": entry.description,
                    "amount_cents": entry.amount_cents, "direction": entry.direction})
    for line in PersonalLine.objects.filter(
            ledger=ledger, removed_at__isnull=True, category__isnull=True
    ).order_by("-on_date")[:max(MOST - len(out), 0)]:
        out.append({"kind": "line", "id": str(line.pk), "description": line.description,
                    "amount_cents": line.amount_cents, "direction": line.direction})
    return out


def _choices(ledger, tenant):
    personal = list(PersonalCategory.objects.filter(
        ledger=ledger, archived_at__isnull=True,
        type__in=(PersonalCategory.Type.EXPENSE, PersonalCategory.Type.INCOME))
        .select_related("parent").order_by("type", "position", "name"))
    business = list(FinanceCategory.all_objects.filter(
        tenant=tenant, archived_at__isnull=True,
        type__in=(FinanceCategory.Type.INCOME, FinanceCategory.Type.EXPENSE))
        .select_related("parent").order_by("type", "position", "name"))
    return ({f"P{i}": c for i, c in enumerate(personal, start=1)},
            {f"B{i}": c for i, c in enumerate(business, start=1)})


def _name(category) -> str:
    return f"{category.parent.name}: {category.name}" if category.parent_id else category.name


def what_is_sent(ledger, tenant) -> tuple[str, dict, dict, dict]:
    """The whole of what goes to Claude, and the ids it was given."""
    rows = waiting(ledger, tenant)
    personal, business = _choices(ledger, tenant)
    by_ref = {f"L{i}": row for i, row in enumerate(rows, start=1)}
    parts = [f"LINES ({len(rows)}):"]
    for ref, row in by_ref.items():
        parts.append(f"- {ref} | {'in' if row['direction'] == 'in' else 'out'} "
                     f"${row['amount_cents'] / 100:,.2f} | {row['description']}")
    parts.append("PERSONAL CATEGORIES:")
    parts += [f"- {ref} | {c.get_type_display().lower()} | {_name(c)}"
              for ref, c in personal.items()]
    parts.append("BUSINESS CATEGORIES:")
    parts += [f"- {ref} | {c.get_type_display().lower()} | {_name(c)}"
              for ref, c in business.items()]
    return "\n".join(parts), by_ref, personal, business


def _tokens(count: int) -> tuple[int, int]:
    """Roughly what a press reads and writes, by the number of lines: the
    price shown on the button."""
    return 1500 + 30 * count, 300 + 60 * count


def status(ledger, tenant) -> dict:
    from apps.tenancy import claude

    count = len(waiting(ledger, tenant))
    base = explain.status(tenant, PURPOSE, _tokens(count))
    estimate = claude.cost_of(settings.ANTHROPIC_MODEL, *_tokens(count))
    refused = base["refused"] or ("" if count else "Nothing waits in To sort.")
    return {**base, "estimate_usd": str(Decimal(estimate).quantize(Decimal("0.0001"))),
            "lines": count, "most": MOST, "refused": refused}


def propose(ledger, tenant) -> dict:
    """One call. Returns a proposal per line it could judge; stores nothing
    and changes nothing."""
    from apps.finance import forecast_ai
    from apps.tenancy import claude

    now = status(ledger, tenant)
    if now["refused"]:
        raise PersonalError(now["refused"], status=409)
    text, by_ref, personal, business = what_is_sent(ledger, tenant)
    try:
        answer, call = claude.complete_with_call(
            tenant=tenant, purpose=PURPOSE, system=SYSTEM, user_text=text,
            trigger="button", max_tokens=MAX_TOKENS, effort="low")
    except claude.ClaudeRefused:
        raise PersonalError("Claude declined to sort these. Nothing was changed.",
                            status=502) from None
    except claude.ClaudeUnavailable as exc:
        raise PersonalError(str(exc), status=502) from None
    try:
        data = forecast_ai._read(answer)
    except FinanceError:
        raise PersonalError("Claude's answer could not be read, so there is nothing to "
                            "accept. Nothing was changed. It was still an AI call.",
                            status=502) from None
    proposals, seen = [], set()
    for item in data.get("lines") if isinstance(data.get("lines"), list) else []:
        if not isinstance(item, dict):
            continue
        ref = str(item.get("id", ""))
        side = item.get("side")
        cat = str(item.get("category", ""))
        if ref not in by_ref or ref in seen or side not in ("personal", "business"):
            continue
        chosen = (personal if side == "personal" else business).get(cat)
        if chosen is None:
            continue
        row = by_ref[ref]
        if row["direction"] == "out" and chosen.type == "income" and side == "personal":
            continue
        seen.add(ref)
        match = " ".join(str(item.get("match") or "").split())[:120]
        if len(match) < 3 or match.casefold() not in row["description"].casefold():
            match = " ".join(row["description"].split()[:2])
        proposals.append({
            "kind": row["kind"], "id": row["id"], "description": row["description"],
            "amount_cents": row["amount_cents"], "direction": row["direction"],
            "side": side, "category": {"id": str(chosen.pk), "name": _name(chosen)},
            "match": match, "why": " ".join(str(item.get("why") or "").split())[:200]})
    return {"proposals": proposals, "cost_usd": str(call.cost_usd),
            "used_today": now["used_today"] + 1, "cap": explain.DAILY_CAP,
            "disclaimer": DISCLAIMER}
