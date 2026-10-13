"""The forecast's two buttons that ask Claude (`docs/p6_m2_cash_forecast.md`
§6 and §6a): "Explain this forecast" and "Review with Claude".

The forecast's numbers are arithmetic on the books. **Claude never supplies
one.** It explains what is there, and it proposes and asks; what it proposes
is a list of things already in the books, named by ids this module gave it,
so every amount the owner then sees comes from the books and every amount
that enters the forecast is one the owner typed or confirmed.

- **Pressed only.** Nothing is sent by opening the screen.
- **Names (M2-12).** Payee and category names are sent for expenses. A client
  is "Client A", "Client B", the same letter for the same client throughout
  one call, unless the practice owner has switched on "Include client names
  in AI explanations". No invoice number and no one's contact details, ever.
  `explain_input` and `review_input` are the whole of what goes, and the
  tests read them.
- **Costed and capped:** an `ai_call` each; the 20 a day that Finance's
  pressed buttons share (`explain.PRESSED`); never past the monthly AI budget.
- **Nothing here changes anything.** The review's answers become adjustments
  and planned lines only when the owner confirms each, through the ordinary
  routes.
"""

from __future__ import annotations

import json
import re
from datetime import date

from django.utils import timezone

from apps.finance import explain, forecast
from apps.finance.disclaimer import DISCLAIMER
from apps.finance.services import FinanceError

EXPLAIN = "finance_explain_forecast"
REVIEW = "finance_review_forecast"
EXPLAIN_TOKENS = (2500, 500)
REVIEW_TOKENS = (6000, 1200)
MAX_LINES = 120
#: The ceiling on one answer. The model reasons before it writes, and that
#: reasoning is counted as output: at 800 it used the whole of it on a
#: forecast's lines and "Explain this forecast" came back cut off every time
#: (2026-10-13). The answer's length is set by the prompt, not by this.
MAX_TOKENS = 16000
#: What a question in the review may be about.
TOPICS = ("client", "hire", "equipment", "tax", "trip", "other")

NO_ADVICE = (
    "Do not give tax, legal or financial advice: where the question is one for an "
    "accountant, say \"ask your CPA\". Do not recommend borrowing, investing, or letting "
    "anyone go. Do not invent, estimate or suggest any amount of money that is not in "
    "what you are given.")

EXPLAIN_SYSTEM = (
    "You are helping the owner of a small professional practice read the cash forecast "
    "in their own bookkeeping app. The forecast is arithmetic on their books: cash today, "
    "then money in and out week by week from invoices (known), from costs found in their "
    "closed months (regular), from what they typed (planned), and from their card's "
    "payment. In at most 180 words and plain sentences, say where the low point comes "
    "from, which few lines move it most, and what would change it. Use the numbers given. "
    "Clients may be given as \"Client A\", \"Client B\": call them that. You cannot change "
    "anything and must not say you did. " + NO_ADVICE + " No headings, no lists longer "
    "than three items.")

REVIEW_SYSTEM = (
    "You are reviewing how a small professional practice's bookkeeping app has read its "
    "own books for a cash forecast. The app found REGULAR lines (it forecasts these) and "
    "NOT PICKED UP lines (it does not). Each has an id. Your job is to propose and to "
    "ask; the owner decides. Answer with one JSON object and nothing else:\n"
    "{\"one_offs\": [{\"id\": \"R3\", \"why\": \"…\"}],\n"
    " \"missed\": [{\"id\": \"N7\", \"why\": \"…\"}],\n"
    " \"questions\": [{\"topic\": \"hire\", \"question\": \"…\"}]}\n"
    "one_offs: REGULAR lines that look like one-off costs, not recurring ones. "
    "missed: NOT PICKED UP lines that look recurring. questions: up to six short "
    "questions about what the books cannot know in the next six months; topic is one of "
    "client, hire, equipment, tax, trip, other. Use only ids you were given. Each \"why\" "
    "and \"question\" is one plain sentence of at most 200 characters, and names no "
    "amount of money. An empty list is a fine answer. " + NO_ADVICE)


def _dollars(cents: int) -> str:
    return f"{'-' if cents < 0 else ''}${abs(cents) / 100:,.2f}"


def _letters(names: list[str]) -> dict:
    """`{name: "Client A"}`, the same letter for the same client, in the
    order of their names so a call can be read against the screen."""
    out = {}
    for index, name in enumerate(sorted(set(names))):
        letters, n = "", index
        while True:
            letters = chr(ord("A") + n % 26) + letters
            n = n // 26 - 1
            if n < 0:
                break
        out[name] = f"Client {letters}"
    return out


class _Names:
    """Who a line is sent as. An expense's payee and category go by name. A
    client, and anyone money comes in from, goes by letter unless the
    practice owner has switched client names on."""

    def __init__(self, tenant, lines: list[dict]):
        self.include = forecast.settings_for(tenant).include_client_names
        payers = [row["who"] for row in lines
                  if row["kind"] == "known" or (row["kind"] == "regular"
                                                and row["direction"] == "in")]
        self.letter = _letters(payers)

    def of(self, row: dict) -> str:
        if row["kind"] == "known":
            who = row["who"] if self.include else self.letter[row["who"]]
            return f"{who}: {'recurring invoice' if row['cadence'] else 'invoice'}"
        if row["kind"] == "regular" and row["direction"] == "in":
            who = row["who"] if self.include else self.letter[row["who"]]
            return f"{who} ({row['category']})" if row["category"] else who
        if row["kind"] in ("planned", "card"):
            return row["label"]
        return f"{row['who']} ({row['category']})" if row["category"] else row["who"]


def explain_input(tenant, view: str = "90", today: date | None = None) -> str:
    """The whole of what goes to Claude for "Explain this forecast"."""
    if view not in forecast.VIEWS:
        raise FinanceError("view is 30, 90 or 180.")
    result = forecast.build(tenant, today, snapshot=False)
    rows = result["weeks"][:forecast.VIEWS[view]]
    summary = result["views"][view]
    names = _Names(tenant, result["lines"])
    parts = [
        f"CASH FORECAST, the next {view} days, as of {result['as_of']}",
        f"Cash today: {_dollars(result['cash_today_cents'])}",
        "Floor the owner wants to stay above: "
        + (_dollars(result["floor_cents"]) if result["floor_cents"] is not None
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
                     f"{_dollars(row['amount_cents'])} | {names.of(row)}"
                     + (f" | {row['cadence']}" if row["cadence"] else ""))
    if len(counted) > MAX_LINES:
        parts.append(f"(the first {MAX_LINES} of {len(counted)})")
    return "\n".join(parts)


def status(tenant) -> dict:
    """What the two buttons say before they are pressed. Asks Claude nothing."""
    base = explain.status(tenant, EXPLAIN, EXPLAIN_TOKENS)
    review = explain.status(tenant, REVIEW, REVIEW_TOKENS)
    return {**base, "review_estimate_usd": review["estimate_usd"],
            "include_client_names": forecast.settings_for(tenant).include_client_names}


def _ask(tenant, *, purpose, system, text, effort=None):
    from apps.tenancy import claude

    now = explain.status(tenant, purpose)
    if now["refused"]:
        raise FinanceError(now["refused"], status=409)
    try:
        answer, call = claude.complete_with_call(
            tenant=tenant, purpose=purpose, system=system, user_text=text,
            trigger="button", max_tokens=MAX_TOKENS, effort=effort)
    except claude.ClaudeRefused:
        raise FinanceError("Claude declined to answer that. Nothing was changed.",
                           status=502) from None
    except claude.ClaudeUnavailable as exc:
        raise FinanceError(str(exc), status=502) from None
    return answer, call, now["used_today"] + 1


def explain_forecast(tenant, *, view: str = "90") -> dict:
    """Ask Claude to read the forecast. Writes nothing but its `ai_call`."""
    answer, call, used = _ask(tenant, purpose=EXPLAIN, system=EXPLAIN_SYSTEM,
                              text=explain_input(tenant, view), effort="low")
    return {"text": answer, "cost_usd": str(call.cost_usd), "disclaimer": DISCLAIMER,
            "used_today": used, "cap": explain.DAILY_CAP}


# ----------------------------------------------------------- the review

def _candidates(tenant, today: date) -> tuple[list[dict], list[dict]]:
    """What the review is shown, from the books: the regular lines as found,
    and every other category-and-payee of the last 12 closed months. Each
    carries its own figures, so what the owner then sees is the books'."""
    parts = forecast._gather(tenant, today, adjusted={})
    closed = parts["closed"]
    if not parts["ready"]:
        raise FinanceError(forecast.NOT_READY, status=409)
    last12 = closed[-12:]
    patterns = forecast._patterns(tenant, last12)
    regular_groups = {}
    for row in parts["regular"]:
        regular_groups.setdefault(row["group"], row)
    regular, missed = [], []
    for key, pattern in sorted(patterns.items(), key=lambda item: str(item[0])):
        group = forecast._pattern_group(key)
        months = sorted(pattern.by_month)
        entry = pattern.entry
        item = {
            "group": group, "who": forecast._name(entry),
            "category": forecast._category_name(entry.category),
            "direction": entry.direction, "entry_kind": entry.kind,
            "months": [{"month": m.isoformat()[:7], "amount_cents": pattern.by_month[m]}
                       for m in months],
            "last_on": pattern.last_on.isoformat(), "last_amount_cents": pattern.last_amount}
        if group in regular_groups:
            found = regular_groups[group]
            regular.append({**item, "cadence": found["cadence"],
                            "amount_cents": found["amount_cents"],
                            "detail": found["detail"]})
        else:
            missed.append(item)
    for index, item in enumerate(regular, start=1):
        item["ref"] = f"R{index}"
    for index, item in enumerate(missed, start=1):
        item["ref"] = f"N{index}"
    return regular, missed


def review_input(tenant, today: date | None = None) -> tuple[str, list[dict], list[dict]]:
    """The whole of what goes to Claude for "Review with Claude", and the two
    lists its answer is read against."""
    today = today or timezone.localdate()
    regular, missed = _candidates(tenant, today)
    include = forecast.settings_for(tenant).include_client_names
    letters = _letters([item["who"] for item in regular + missed
                        if item["direction"] == "in"])

    def who(item) -> str:
        name = item["who"]
        if item["direction"] == "in" and not include:
            name = letters[name]
        return f"{name} ({item['category']})" if item["category"] else name

    def seen(item) -> str:
        return ", ".join(f"{m['month']} {_dollars(m['amount_cents'])}"
                         for m in item["months"])

    closed = forecast.closed_months(tenant)[-12:]
    parts = [f"CLOSED MONTHS READ: {closed[0].isoformat()[:7]} to "
             f"{closed[-1].isoformat()[:7]} ({len(closed)})",
             f"REGULAR ({len(regular)}) (id | in or out | who (category) | cadence | "
             "forecast amount | months seen):"]
    for item in regular[:MAX_LINES]:
        parts.append(f"- {item['ref']} | {item['direction']} | {who(item)} | "
                     f"{item['cadence']} | {_dollars(item['amount_cents'])} | {seen(item)}")
    parts.append(f"NOT PICKED UP ({len(missed)}) (id | in or out | who (category) | "
                 "months seen):")
    for item in missed[:MAX_LINES]:
        parts.append(f"- {item['ref']} | {item['direction']} | {who(item)} | {seen(item)}")
    return "\n".join(parts), regular[:MAX_LINES], missed[:MAX_LINES]


def _read(answer: str) -> dict:
    found = re.search(r"\{.*\}", answer, flags=re.S)
    try:
        data = json.loads(found.group(0)) if found else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise FinanceError("Claude's answer could not be read, so there is nothing to "
                           "review. Nothing was changed. It was still an AI call.",
                           status=502)
    return data


def _sentence(value) -> str:
    return " ".join(str(value or "").split())[:240]


def _pick(rows, by_ref: dict) -> list[dict]:
    out, seen = [], set()
    for row in rows if isinstance(rows, list) else []:
        ref = str(row.get("id", "")) if isinstance(row, dict) else ""
        if ref in by_ref and ref not in seen:      # only what we sent, each once
            seen.add(ref)
            item = by_ref[ref]
            out.append({key: item[key] for key in item if key != "ref"}
                       | {"why": _sentence(row.get("why"))})
    return out


def review(tenant) -> dict:
    """One call. Returns three lists for the owner to answer; stores nothing
    and changes nothing."""
    text, regular, missed = review_input(tenant)
    answer, call, used = _ask(tenant, purpose=REVIEW, system=REVIEW_SYSTEM, text=text)
    data = _read(answer)
    questions = []
    for row in data.get("questions") if isinstance(data.get("questions"), list) else []:
        if isinstance(row, dict) and _sentence(row.get("question")):
            topic = row.get("topic") if row.get("topic") in TOPICS else "other"
            questions.append({"topic": topic, "question": _sentence(row.get("question"))})
    return {
        "one_offs": _pick(data.get("one_offs"), {item["ref"]: item for item in regular}),
        "missed": _pick(data.get("missed"), {item["ref"]: item for item in missed}),
        "questions": questions[:6],
        "cost_usd": str(call.cost_usd), "disclaimer": DISCLAIMER, "used_today": used,
        "cap": explain.DAILY_CAP}


__all__ = ["explain_input", "explain_forecast", "review_input", "review", "status"]
