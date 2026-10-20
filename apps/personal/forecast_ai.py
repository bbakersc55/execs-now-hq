"""The personal forecast's two buttons that ask Claude (P6 M4 decision 25, M2's
pattern in `apps/finance/forecast_ai.py`): "Explain this forecast" and
"Review with Claude".

- **Pressed only**, priced before they are pressed, one count each on
  Finance's shared 20 a day (`explain.PRESSED`), never past the practice's
  monthly AI budget.
- **What is sent** is `explain_input` or `review_input` and nothing else:
  amounts, dates and category names. A line is named by its category, never
  by the merchant or payee the bank printed; a debt by its kind ("Mortgage
  payment"), never the lender. Never an account's name or number, a
  retirement or investment balance, or the owner's name.
- **Claude supplies no number.** The review proposes from ids this module
  gave it: a Regular line that looks like a one-off, a line not picked up
  that looks like it recurs, and questions. Each becomes an adjustment or a
  planned line only when the owner confirms it, through the ordinary routes.
"""

from __future__ import annotations

import json
import re
from datetime import date

from django.utils import timezone

from apps.finance import explain
from apps.finance.forecast import REPEAT_MONTHS, VIEWS, _add_months, _months_between
from apps.personal import forecast
from apps.personal.budget_ai import DISCLAIMER
from apps.personal.models import PersonalDebt
from apps.personal.services import PersonalError, for_claude

EXPLAIN = "personal_explain_forecast"
REVIEW = "personal_review_forecast"
EXPLAIN_TOKENS = (2200, 450)
REVIEW_TOKENS = (6500, 1400)
MAX_TOKENS = 16000
MAX_LINES = 120

NO_ADVICE = (
    "Do not give tax, legal or financial advice: where the question is one for an "
    "accountant, say \"ask your CPA\". Do not recommend borrowing or investing. Do not "
    "invent, estimate or suggest any amount of money that is not in what you are given.")

EXPLAIN_SYSTEM = (
    "You are helping someone read their household's cash forecast in their own app. "
    "The forecast is arithmetic on their own accounts: cash today, then money in and out "
    "week by week from what is known (their pay from their practice, debt payments, "
    "yearly bills, estimated tax), what is regular (found in their past months), and what "
    "they planned (goals and one-offs). In at most 180 words and plain sentences, say "
    "where the low point comes from, which few lines move it most, and what would change "
    "it. Use the numbers given. You cannot change anything and must not say you did. "
    + NO_ADVICE + " No headings, no lists longer than three items.")

REVIEW_SYSTEM = (
    "You are reviewing how a household's own app has read its past months for a cash "
    "forecast and a budget. The app found REGULAR lines (it forecasts these) and NOT "
    "PICKED UP lines (it does not); it also lists ENVELOPES (monthly amounts the household "
    "planned, beside what was spent), GOALS and the TAX SET-ASIDE. Each has an id. Your "
    "job is to propose and to ask; the person decides, and the app supplies every "
    "amount. Answer with one JSON object and nothing else:\n"
    "{\"one_offs\": [{\"id\": \"R3\", \"why\": \"…\"}],\n"
    " \"missed\": [{\"id\": \"N7\", \"cadence\": \"yearly\", \"why\": \"…\"}],\n"
    " \"envelopes\": [{\"id\": \"E2\", \"why\": \"…\"}],\n"
    " \"goals\": [{\"id\": \"G1\", \"why\": \"…\"}],\n"
    " \"set_aside\": [{\"id\": \"S1\", \"why\": \"…\"}],\n"
    " \"questions\": [{\"question\": \"…\"}]}\n"
    "one_offs: REGULAR lines that look like one-off spending, not recurring. missed: NOT "
    "PICKED UP lines that look recurring, each with the cadence it looks to have: "
    "monthly, quarterly or yearly. envelopes: ENVELOPES whose planned amount looks out of "
    "line with what has been spent, to be set to the recent amount the app shows. goals: "
    "GOALS that look out of reach at their monthly amount, or set aside for faster than "
    "needed. set_aside: the TAX SET-ASIDE, if its percent of each draw looks out of line "
    "with the app's suggested percent. questions: up to six short questions about what "
    "the past months cannot show in the next six (a trip, a large purchase, a change in "
    "pay, a school or medical cost). Use only ids you were given. Each \"why\" and "
    "\"question\" is one plain sentence of at most 200 characters, and names no amount of "
    "money. An empty list is a fine answer. KNOWN is already in the forecast: do not ask "
    "about it. " + NO_ADVICE)


def _dollars(cents: int) -> str:
    return f"{'-' if cents < 0 else ''}${abs(cents) / 100:,.2f}"


def _name(ledger, row: dict) -> str:
    """A line as it is sent: by category or kind, never a merchant."""
    group = row["group"]
    if group.startswith("debt:"):
        debt = PersonalDebt.objects.filter(ledger=ledger, pk=group.split(":", 1)[1]).first()
        return f"{debt.get_kind_display() if debt else 'Debt'} payment"
    if row["kind"] == "planned":
        return row["label"]
    if row["category"] in ("Transfers", "") and row["direction"] == "out":
        return "Card payment or transfer out" if row["category"] else "(not sorted yet)"
    return row["category"] or "(not sorted yet)"


def explain_input(ledger, view: str = "90", today: date | None = None) -> str:
    if view not in VIEWS:
        raise PersonalError("view is 30, 90 or 180.")
    result = forecast.build(ledger, today, snapshot=False)
    rows = result["weeks"][:VIEWS[view]]
    summary = result["views"][view]
    parts = [
        f"HOUSEHOLD CASH FORECAST, the next {view} days, as of {result['as_of']}",
        f"Cash today in the household's accounts: {_dollars(result['cash_today_cents'])}",
        "Floor they want to stay above: " + (_dollars(result["floor_cents"])
                                             if result["floor_cents"] is not None
                                             else "not set"),
        f"Low point: {_dollars(summary['low_cents'])}, the week starting "
        f"{summary['low_start']}",
        "First week under the floor: " + (summary["first_below_floor"] or "none"),
        "First week under zero: " + (summary["first_below_zero"] or "none"),
    ]
    if result["note"]:
        parts.append(result["note"])
    parts.append("WEEKS (start | cash at start | in | out | cash at end):")
    for row in rows:
        parts.append(f"- {row['start']} | {_dollars(row['start_cents'])} | "
                     f"{_dollars(row['in_cents'])} | {_dollars(row['out_cents'])} | "
                     f"{_dollars(row['end_cents'])}")
    last = rows[-1]["end"]
    counted = [row for row in result["lines"] if row["counted"] and row["on_date"] <= last]
    parts.append(f"LINES ({len(counted)}) (date | kind | in or out | amount | what):")
    for row in counted[:MAX_LINES]:
        parts.append(f"- {row['on_date']} | {row['kind']} | {row['direction']} | "
                     f"{_dollars(row['amount_cents'])} | {_name(ledger, row)}"
                     + (f" | {row['cadence']}" if row["cadence"] else ""))
    if len(counted) > MAX_LINES:
        parts.append(f"(the first {MAX_LINES} of {len(counted)})")
    return for_claude(ledger, "\n".join(parts))


def status(tenant) -> dict:
    base = explain.status(tenant, EXPLAIN, EXPLAIN_TOKENS)
    review = explain.status(tenant, REVIEW, REVIEW_TOKENS)
    return {**base, "review_estimate_usd": review["estimate_usd"]}


def _ask(tenant, *, purpose, system, text, effort=None):
    from apps.tenancy import claude

    now = explain.status(tenant, purpose)
    if now["refused"]:
        raise PersonalError(now["refused"], status=409)
    try:
        answer, call = claude.complete_with_call(
            tenant=tenant, purpose=purpose, system=system, user_text=text,
            trigger="button", max_tokens=MAX_TOKENS, effort=effort)
    except claude.ClaudeRefused:
        raise PersonalError("Claude declined to answer that. Nothing was changed.",
                            status=502) from None
    except claude.ClaudeUnavailable as exc:
        raise PersonalError(str(exc), status=502) from None
    return answer, call, now["used_today"] + 1


def explain_forecast(ledger, tenant, *, view: str = "90") -> dict:
    answer, call, used = _ask(tenant, purpose=EXPLAIN, system=EXPLAIN_SYSTEM,
                              text=explain_input(ledger, view), effort="low")
    return {"text": answer, "cost_usd": str(call.cost_usd), "disclaimer": DISCLAIMER,
            "used_today": used, "cap": explain.DAILY_CAP}


# ----------------------------------------------------------------- review

def _candidates(ledger, today: date) -> tuple[list[dict], list[dict], list[dict]]:
    parts = forecast._gather(ledger, today, adjusted={})
    if not parts["ready"]:
        raise PersonalError(forecast.NOT_READY, status=409)
    months = parts["months"]
    found = forecast.patterns(ledger, months)
    regular_groups = {}
    for row in parts["regular"]:
        regular_groups.setdefault(row["group"], row)
    regular, missed = [], []
    for key, pattern in sorted(found.items(), key=lambda item: str(item[0])):
        group = forecast._group(key)
        line = pattern.line
        item = {"group": group, "label": forecast._label(line),
                "category": forecast.category_name(line.category) or "(not sorted yet)",
                "direction": line.direction,
                "months": [{"month": m.isoformat()[:7], "amount_cents": pattern.by_month[m]}
                           for m in sorted(pattern.by_month)],
                "last_on": pattern.last_on.isoformat(),
                "last_amount_cents": pattern.last_amount}
        if group in regular_groups:
            found_row = regular_groups[group]
            regular.append({**item, "cadence": found_row["cadence"],
                            "amount_cents": found_row["amount_cents"],
                            "detail": found_row["detail"]})
        else:
            missed.append(item)
    for index, item in enumerate(regular, start=1):
        item["ref"] = f"R{index}"
    for index, item in enumerate(missed, start=1):
        item["ref"] = f"N{index}"
    return regular, missed, parts["known"]


def review_input(ledger, today: date | None = None) -> tuple:
    today = today or timezone.localdate()
    regular, missed, known = _candidates(ledger, today)

    def seen(item) -> str:
        return ", ".join(f"{m['month']} {_dollars(m['amount_cents'])}"
                         for m in item["months"])

    months = forecast.complete_months(ledger, today)
    parts = [f"MONTHS READ: {months[0].isoformat()[:7]} to {months[-1].isoformat()[:7]} "
             f"({len(months)})",
             f"REGULAR ({len(regular)}) (id | in or out | category | cadence | forecast "
             "amount | months seen):"]
    for item in regular[:MAX_LINES]:
        parts.append(f"- {item['ref']} | {item['direction']} | {item['category']} | "
                     f"{item['cadence']} | {_dollars(item['amount_cents'])} | {seen(item)}")
    parts.append(f"NOT PICKED UP ({len(missed)}) (id | in or out | category | months seen):")
    for item in missed[:MAX_LINES]:
        parts.append(f"- {item['ref']} | {item['direction']} | {item['category']} | "
                     f"{seen(item)}")
    groups: dict = {}
    for row in known:
        groups.setdefault(row["group"], []).append(row)
    parts.append(f"KNOWN, already in the forecast ({len(groups)}) (what | how often | "
                 "amount):")
    for rows in groups.values():
        parts.append(f"- {_name(ledger, rows[0])} | {rows[0]['cadence'] or 'once'} | "
                     f"{_dollars(rows[0]['amount_cents'])}")
    budget_parts, envelopes, goals, aside = _budget_candidates(ledger, today)
    parts += budget_parts
    return (for_claude(ledger, "\n".join(parts)), regular[:MAX_LINES], missed[:MAX_LINES],
            envelopes, goals, aside)


def _budget_candidates(ledger, today: date):
    """Decision 25: envelopes, goals and the set-aside, as the review sees
    them, each with an id and the amount the app would propose. Claude picks
    ids and says why; the amounts are the app's."""
    from statistics import median

    from apps.personal import budget, debts, taxes
    from apps.personal.models import PersonalEnvelope

    parts, envelopes, goals, aside = [], [], [], []
    if budget.has_budget(ledger):
        view = budget.month_view(ledger)
        this = budget.month_of(today)
        months = [budget.add_months(this, -n) for n in (3, 2, 1)]
        totals = {str(pk): by for pk, by in budget.totals_by_month(ledger, months).items()}
        for row in view["envelopes"]:
            if row["goal"] or row["source"] in (PersonalEnvelope.Source.TAX,
                                                PersonalEnvelope.Source.DEBT) \
                    or not row["category"]:
                continue
            spent = [totals.get(row["category"], {}).get(m, 0) for m in months]
            recent = budget.to_ten(median(spent)) if any(spent) else 0
            envelopes.append({"id": row["id"], "name": row["name"],
                              "planned_cents": row["planned_cents"], "kind": row["kind"],
                              "months": [{"month": m.isoformat()[:7], "amount_cents": c}
                                         for m, c in zip(months, spent)],
                              "proposed_cents": recent})
        for index, item in enumerate(envelopes, start=1):
            item["ref"] = f"E{index}"
        if envelopes:
            parts.append(f"ENVELOPES ({len(envelopes)}) (id | name | planned a month | "
                         "spent in the last three months | recent amount the app would "
                         "propose):")
            for item in envelopes:
                spent = ", ".join(_dollars(m["amount_cents"]) for m in item["months"])
                parts.append(f"- {item['ref']} | {item['name']} | "
                             f"{_dollars(item['planned_cents'])} | {spent} | "
                             f"{_dollars(item['proposed_cents'])}")
        for goal in budget.PersonalGoal.of(ledger.owner).filter(archived_at__isnull=True):
            shown = budget.represent_goal(goal, view)
            goals.append({"id": str(goal.pk), "name": goal.name,
                          "target_cents": shown["target_cents"],
                          "progress_cents": shown.get("progress_cents", 0),
                          "monthly_cents": shown.get("monthly_cents", 0),
                          "target_on": goal.target_on.isoformat() if goal.target_on
                          else None})
        for index, item in enumerate(goals, start=1):
            item["ref"] = f"G{index}"
        if goals:
            parts.append(f"GOALS ({len(goals)}) (id | name | target | saved so far | a "
                         "month | by):")
            for item in goals:
                parts.append(f"- {item['ref']} | {item['name']} | "
                             f"{_dollars(item['target_cents'])} | "
                             f"{_dollars(item['progress_cents'])} | "
                             f"{_dollars(item['monthly_cents'])} | "
                             f"{item['target_on'] or 'no date'}")
    found = taxes.estimate(ledger, services_practice(ledger), today=today)
    suggested = (found.get("draws") or {}).get("suggested_percent")
    # A share past every draw is not a percent to propose; the Taxes page says so.
    if found.get("ready") and suggested is not None and suggested <= 100:
        aside.append({"ref": "S1", "id": "set_aside", "year": found["year"],
                      "percent_now": found["set_aside"]["percent_per_draw"],
                      "suggested_percent": suggested,
                      "still_needed_cents": found["still_needed_cents"],
                      "saved_cents": found["set_aside"]["saved_cents"]})
        parts.append("TAX SET-ASIDE (id | percent of each draw now | the app's suggested "
                     "percent | still needed for the year | set aside so far): "
                     f"S1 | {found['set_aside']['percent_per_draw'] or 'not set'}% | "
                     f"{suggested}% | {_dollars(found['still_needed_cents'])} | "
                     f"{_dollars(found['set_aside']['saved_cents'])} "
                     "(an estimate; the person confirms it with their CPA)")
    if debts.open_debts(ledger).exists():
        parts.append(f"PAYOFF PLAN: {debts.ORDER_NAMES[ledger.payoff_order]}, "
                     f"{_dollars(ledger.payoff_extra_cents)} extra a month (not for review)")
    return parts, envelopes, goals, aside


def services_practice(ledger):
    from apps.personal import services

    return services.practice_of(ledger)


def _read(answer: str) -> dict:
    found = re.search(r"\{.*\}", answer, flags=re.S)
    try:
        data = json.loads(found.group(0)) if found else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise PersonalError("Claude's answer could not be read, so there is nothing to "
                            "review. Nothing was changed. It was still an AI call.",
                            status=502)
    return data


def _sentence(value) -> str:
    return " ".join(str(value or "").split())[:240]


def _cadence(proposed, item: dict) -> str:
    if proposed in REPEAT_MONTHS:
        return proposed
    months = [date.fromisoformat(m["month"] + "-01") for m in item["months"]]
    gap = min((_months_between(a, b) for a, b in zip(months, months[1:])), default=12)
    return "yearly" if gap >= 11 else "quarterly" if gap >= 3 else "monthly"


def _next_on(item: dict, cadence: str, today: date) -> str:
    last = date.fromisoformat(item["last_on"])
    step, on, n = REPEAT_MONTHS[cadence], last, 0
    while on <= today:
        n += 1
        on = _add_months(last, step * n, last.day)
    return on.isoformat()


def _pick(rows, by_ref: dict, today: date | None = None) -> list[dict]:
    out, seen = [], set()
    for row in rows if isinstance(rows, list) else []:
        ref = str(row.get("id", "")) if isinstance(row, dict) else ""
        if ref in by_ref and ref not in seen:
            seen.add(ref)
            item = by_ref[ref]
            picked = ({key: item[key] for key in item if key != "ref"}
                      | {"why": _sentence(row.get("why"))})
            if today is not None:
                picked["cadence"] = _cadence(row.get("cadence"), item)
                picked["next_on"] = _next_on(item, picked["cadence"], today)
            out.append(picked)
    return out


def review(ledger, tenant) -> dict:
    today = timezone.localdate()
    text, regular, missed, envelopes, goals, aside = review_input(ledger, today)
    answer, call, used = _ask(tenant, purpose=REVIEW, system=REVIEW_SYSTEM, text=text)
    data = _read(answer)
    questions = []
    for row in data.get("questions") if isinstance(data.get("questions"), list) else []:
        if isinstance(row, dict) and _sentence(row.get("question")):
            questions.append({"question": _sentence(row.get("question"))})
    return {
        "one_offs": _pick(data.get("one_offs"), {item["ref"]: item for item in regular}),
        "missed": _pick(data.get("missed"), {item["ref"]: item for item in missed}, today),
        "envelopes": _pick(data.get("envelopes"), {item["ref"]: item for item in envelopes}),
        "goals": _pick(data.get("goals"), {item["ref"]: item for item in goals}),
        "set_aside": _pick(data.get("set_aside"), {item["ref"]: item for item in aside}),
        "questions": questions[:6],
        "cost_usd": str(call.cost_usd), "disclaimer": DISCLAIMER, "used_today": used,
        "cap": explain.DAILY_CAP}
