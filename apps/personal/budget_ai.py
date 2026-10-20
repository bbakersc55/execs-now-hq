""""Explain this budget" (P6 M4 decisions 13 and 25): Claude reads the
budget, pressed only, priced before it is pressed, as M2's "Explain this
forecast" is.

- **What is sent** is `explain_input` and nothing else: the month; planned
  and received income; each envelope's name, kind, Planned, Spent and Left;
  Unassigned; the goals (name, target, date, saved, monthly); the yearly
  bills spread; and six months of totals by category. Never the owner's name,
  an account's name or number, a merchant, or a retirement balance.
- **It changes nothing:** it writes its `ai_call` and returns words. The
  budget's numbers are arithmetic; Claude supplies none.
- **Costed and capped:** one count on Finance's shared 20 a day
  (`explain.PRESSED`), and never past the practice's monthly AI budget.
"""

from __future__ import annotations

from apps.finance import explain
from apps.personal import budget
from apps.personal.models import PersonalGoal
from apps.personal.services import PersonalError

PURPOSE = "personal_explain_budget"
TOKENS = (1800, 400)
MAX_TOKENS = 16000
DISCLAIMER = ("Budgeting, forecasting and tax estimates only, not tax, legal or financial "
              "advice. Confirm with your CPA.")

SYSTEM = (
    "You are helping someone read their household budget in their own app. The budget "
    "is arithmetic on their own spending: each envelope's monthly amount came from the "
    "median of their last months, or they set it. In at most 180 words and plain "
    "sentences, say where the money goes, which envelopes are over or close to it and "
    "why that may be, what Unassigned means for them this month, and how the goals and "
    "yearly bills fit. Use the numbers given and no others. You cannot change anything "
    "and must not say you did. Do not give tax, legal or financial advice: where the "
    "question is one for an accountant, say \"ask your CPA\". Do not recommend borrowing "
    "or investing. Do not invent, estimate or suggest any amount of money that is not in "
    "what you are given. No headings, no lists longer than three items.")


def _dollars(cents: int) -> str:
    return f"{'-' if cents < 0 else ''}${abs(cents) / 100:,.2f}"


def explain_input(ledger) -> str:
    """The whole of what goes to Claude. The tests read it."""
    view = budget.month_view(ledger)
    flow = budget.cash_flow(ledger)
    parts = [f"HOUSEHOLD BUDGET, {view['month_label']}",
             f"Income planned: {_dollars(view['income_planned_cents'])}; received so far: "
             f"{_dollars(view['income_received_cents'])}",
             f"Envelopes planned: {_dollars(view['planned_cents'])}; spent so far: "
             f"{_dollars(view['spent_cents'])}",
             f"Unassigned (income planned less every envelope): "
             f"{_dollars(view['unassigned_cents'])}",
             "ENVELOPES (name | kind | rolls over | planned | spent | left):"]
    for row in view["envelopes"]:
        parts.append(f"- {row['name']} | {row['kind_label']} | "
                     f"{'yes' if row['rolls'] else 'no'} | {_dollars(row['planned_cents'])} "
                     f"| {_dollars(row['spent_cents'])} | {_dollars(row['left_cents'])}"
                     + (f" | a yearly bill of {_dollars(row['yearly_cents'])}"
                        if row["yearly_cents"] else ""))
    if view["unbudgeted"]:
        parts.append("SPENT IN CATEGORIES WITH NO ENVELOPE (name | spent):")
        parts += [f"- {r['name']} | {_dollars(r['spent_cents'])}" for r in view["unbudgeted"]]
    goals = PersonalGoal.of(ledger.owner).filter(archived_at__isnull=True)
    if goals:
        parts.append("GOALS (name | target | by | saved and set aside | a month):")
        for goal in goals:
            row = budget.represent_goal(goal, view)
            parts.append(f"- {row['name']} | {_dollars(row['target_cents'])} | "
                         f"{row['target_on'] or 'no date'} | "
                         f"{_dollars(row['progress_cents'])} | "
                         f"{_dollars(row['monthly_cents'])}")
    parts.append("CASH FLOW BY MONTH, the last six and this one so far "
                 f"({', '.join(flow['labels'])}):")
    for row in flow["rows"]:
        parts.append(f"- {row['name']} ({'in' if row['type'] == 'income' else 'out'}): "
                     + ", ".join(_dollars(c) for c in row["cents"]))
    from apps.personal.services import for_claude

    return for_claude(ledger, "\n".join(parts))


def status(tenant) -> dict:
    """What the button says before it is pressed. Asks Claude nothing."""
    return explain.status(tenant, PURPOSE, TOKENS)


def explain_budget(ledger, tenant) -> dict:
    from apps.tenancy import claude

    if not budget.has_budget(ledger):
        raise PersonalError("There is no budget to explain yet.", status=409)
    now = status(tenant)
    if now["refused"]:
        raise PersonalError(now["refused"], status=409)
    try:
        text, call = claude.complete_with_call(
            tenant=tenant, purpose=PURPOSE, system=claude.drafting(SYSTEM), user_text=explain_input(ledger),
            trigger="button", max_tokens=MAX_TOKENS, effort="low")
    except claude.ClaudeRefused:
        raise PersonalError("Claude declined to answer that. Nothing was changed.",
                            status=502) from None
    except claude.ClaudeUnavailable as exc:
        raise PersonalError(str(exc), status=502) from None
    return {"text": text, "cost_usd": str(call.cost_usd), "disclaimer": DISCLAIMER,
            "used_today": now["used_today"] + 1, "cap": explain.DAILY_CAP}
