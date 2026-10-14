"""Importing from a PDF statement (owner, 2026-10-14).

A PDF has no columns to map, so this is the one part of the import that asks
Claude: it reads the statement and returns its lines (date, description,
amount, direction), its opening and closing balance and its period. From
there it is the ordinary import: the extracted lines go through the same dry
run before anything is written, the practice's own rules decide them, and the
closing balance is set beside the account as a CSV's is.

- **Priced before and costed after.** Before: a figure from the number of
  pages, shown on the button. After: the `ai_call` the read wrote, on the
  import. It counts against the practice's monthly AI budget, and is refused
  when that is spent.
- **Pressed only.** Choosing the file reads nothing; "Read it with Claude"
  does.
- **What is kept from the PDF:** its lines, its period and its two balances.
  **Never** an account or routing number, a name or an address: the prompt
  forbids them, nothing here has a place to put them, and a long run of
  digits in a description is cut to its last four before it is stored.
- **The PDF itself is kept with the import,** because it is the statement:
  it is shown on the Reconcile screen for its month. It is sent to Anthropic
  as it is, which is what reading it means.
- **Claude supplies no figure the statement does not print.** Whether the
  lines add up to the closing balance is arithmetic done here, and shown.
- **A scan is refused for now:** a PDF with no text in it.
"""

from __future__ import annotations

import io
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from apps.finance.services import FinanceError

KIND = "pdf"
PURPOSE = "finance_read_statement"
STORED_AS = "bank_statement"
BYTES_MOST = 20 * 1024 * 1024
PAGES_MOST = 40
#: Fewer characters of text than this on every page, and it is a picture of a
#: statement, not a statement.
TEXT_LEAST = 200
#: Roughly what a page costs to read and to write out, until it is known.
TOKENS_A_PAGE = (2600, 900)
TOKENS_ONCE = (700, 300)
MAX_TOKENS = 16000

HEADER = ["Date", "Description", "Amount"]
MAPPING = {"date": "Date", "date_format": "%Y-%m-%d", "description": "Description",
           "amount": "Amount", "sign": "negative_is_out", "debit": "", "credit": "",
           "balance": "", "reference": "", "bank_id": ""}

SCAN = ("This PDF is a scan: it is a picture of the statement, with no text in it to "
        "read. Download the statement from your bank's website instead, as a PDF, a CSV "
        "or an OFX file.")

SYSTEM = (
    "You are reading one bank or credit card statement, a PDF, for the bookkeeping app "
    "of a small professional practice. Copy out what the statement prints. Reply with "
    "one JSON object and nothing else:\n"
    "{\"period_start\": \"YYYY-MM-DD\", \"period_end\": \"YYYY-MM-DD\",\n"
    " \"opening_balance\": \"1234.56\", \"closing_balance\": \"1234.56\",\n"
    " \"transactions\": [{\"date\": \"YYYY-MM-DD\", \"description\": \"...\", "
    "\"amount\": \"12.34\", \"direction\": \"out\"}]}\n"
    "transactions: every line of activity on the statement, in the order it prints "
    "them, each once. amount is the figure printed, as a positive number with two "
    "decimals and no currency sign or commas. direction is \"in\" for money into the "
    "account (a deposit, a credit, interest earned; on a card, a payment or a refund) "
    "and \"out\" for money leaving it (a withdrawal, a check, a fee; on a card, a "
    "purchase, a fee or interest charged). description is the line's own wording, on "
    "one line. Use the statement's year for dates that print without one.\n"
    "opening_balance and closing_balance are the statement's own beginning and ending "
    "balance as printed, with a minus sign if it prints one; on a card, the previous "
    "balance and the new balance owed. Use null for anything the statement does not "
    "print. Do not work out, estimate or correct any figure: if a line cannot be read, "
    "give what you can read and leave its amount as an empty string.\n"
    "Do NOT include the account number, a routing number, a card number, the account "
    "holder's name or address, or any other detail of a person, anywhere in your "
    "answer. Leave them out of descriptions too. Summary rows, running balances and "
    "totals are not transactions.")
ASK = "Read this statement."


def is_pdf(file_bytes: bytes, filename: str = "") -> bool:
    return file_bytes[:1024].lstrip().startswith(b"%PDF") \
        or (filename or "").lower().endswith(".pdf")


def inspect(file_bytes: bytes) -> dict:
    """`{pages}` for a PDF that can be read, or a refusal in words: not a
    PDF, locked, too long, or a scan."""
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    if len(file_bytes) > BYTES_MOST:
        raise FinanceError("That PDF is larger than 20 MB. A statement is usually far "
                           "smaller: download it again from your bank.")
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        if reader.is_encrypted:
            raise FinanceError("That PDF is locked with a password. Download it from your "
                               "bank without one, or use its CSV or OFX file.")
        pages = len(reader.pages)
        if pages > PAGES_MOST:
            raise FinanceError(f"That PDF has {pages} pages; {PAGES_MOST} is the most at a "
                               "time. A statement for one month is what this reads.")
        text = max((len((page.extract_text() or "").strip()) for page in reader.pages),
                   default=0)
    except FinanceError:
        raise
    except (PyPdfError, ValueError, KeyError, TypeError, OSError, RecursionError):
        raise FinanceError("That file is not a PDF this import can open.") from None
    if pages == 0 or text < TEXT_LEAST:
        raise FinanceError(SCAN)
    return {"pages": pages}


def estimate(pages: int) -> Decimal:
    """About what reading this many pages costs, at the model's price."""
    from django.conf import settings

    from apps.tenancy import claude

    return claude.cost_of(settings.ANTHROPIC_MODEL,
                          TOKENS_ONCE[0] + TOKENS_A_PAGE[0] * pages,
                          TOKENS_ONCE[1] + TOKENS_A_PAGE[1] * pages)


def status(tenant, pages: int) -> dict:
    """What the button says before it is pressed: about what it costs, and
    why it cannot be pressed when it cannot."""
    from apps.finance import explain
    from apps.tenancy import claude

    refused = ""
    if claude.key_source(tenant) is None:
        refused = ("No Anthropic API key is set, and a PDF statement is read by Claude. "
                   "The practice owner adds one under AI usage. A CSV or an OFX file "
                   "needs none.")
    elif explain._over_budget(tenant):
        refused = ("This month's AI budget is spent, and a PDF statement is read by "
                   "Claude. Raise it under AI usage, or use the bank's CSV or OFX file, "
                   "which needs none.")
    return {"pages": pages,
            "estimate_usd": str(estimate(pages).quantize(Decimal("0.0001"))),
            "refused": refused}


# ------------------------------------------------------ reading the answer

def _a_day(value) -> date | None:
    try:
        return date.fromisoformat(str(value or "").strip()[:10])
    except ValueError:
        return None


def _cents(value) -> int | None:
    text = str(value if value is not None else "").replace("$", "").replace(",", "").strip()
    if not text:
        return None
    try:
        return int((Decimal(text) * 100).to_integral_value())
    except InvalidOperation:
        return None


_DIGITS = re.compile(r"\d[\d\- ]{6,}\d")


def scrub(text) -> str:
    """A description as it is kept: on one line, and with any long run of
    digits (an account or card number a line happens to quote) cut to its
    last four."""
    text = " ".join(str(text or "").split())

    def cut(match: re.Match) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        return match.group(0) if len(digits) < 8 else f"…{digits[-4:]}"

    return _DIGITS.sub(cut, text)[:255]


def _rows(transactions) -> list[dict]:
    """The lines as the import's columns: a signed amount, money out
    negative. One that cannot be read keeps what was there, so the dry run
    names it and says why, as it does for a CSV's."""
    out = []
    for item in transactions if isinstance(transactions, list) else []:
        if not isinstance(item, dict):
            continue
        on, cents = _a_day(item.get("date")), _cents(item.get("amount"))
        direction = str(item.get("direction") or "").strip().lower()
        if cents is not None and direction in ("in", "out"):
            amount = f"{(-abs(cents) if direction == 'out' else abs(cents)) / 100:.2f}"
        else:
            amount = " ".join(f"{item.get('amount') or ''} {direction}".split())
            amount = amount if cents is None else f"{amount} (in or out?)"
        out.append({"Date": on.isoformat() if on else scrub(item.get("date")),
                    "Description": scrub(item.get("description")) or "(no description)",
                    "Amount": amount})
    return out


def parse_answer(answer: str) -> dict:
    """Claude's answer as `{rows, period_start, period_end, opening, closing}`,
    holding only what this import keeps."""
    found = re.search(r"\{.*\}", answer or "", flags=re.S)
    try:
        data = json.loads(found.group(0)) if found else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise FinanceError("Claude's reading of the statement could not be used, so "
                           "nothing was imported. It was still an AI call. Try once more, "
                           "or use the bank's CSV or OFX file.", status=502)
    rows = _rows(data.get("transactions"))
    if not rows:
        raise FinanceError("Claude found no transactions on that statement, so there is "
                           "nothing to import. It was still an AI call.", status=502)
    return {"rows": rows, "period_start": _a_day(data.get("period_start")),
            "period_end": _a_day(data.get("period_end")),
            "opening": _cents(data.get("opening_balance")),
            "closing": _cents(data.get("closing_balance"))}


def read(tenant, *, file_bytes: bytes) -> dict:
    """Ask Claude to read the statement. Writes nothing but its `ai_call`,
    and that is written whatever happens next: a read that fails still cost.

    Returns what `importer.parse` returns for any other file, with the
    statement's own facts beside it."""
    from apps.tenancy import claude

    found = inspect(file_bytes)
    now = status(tenant, found["pages"])
    if now["refused"]:
        raise FinanceError(now["refused"], status=409)
    try:
        answer, call = claude.complete_with_call(
            tenant=tenant, purpose=PURPOSE, system=SYSTEM, user_text=ASK,
            trigger="button", max_tokens=MAX_TOKENS, effort="low", document=file_bytes)
    except claude.ClaudeRefused:
        raise FinanceError("Claude declined to read that statement. Nothing was imported. "
                           "Use the bank's CSV or OFX file.", status=502) from None
    except claude.ClaudeUnavailable as exc:
        cut_off = "cut off" in str(exc)
        raise FinanceError(
            "That statement has more on it than can be read in one go, so nothing was "
            "imported. It was still an AI call. Use the bank's CSV or OFX file for this one."
            if cut_off else str(exc), status=502) from None
    parsed = parse_answer(answer)
    closing = None
    if parsed["closing"] is not None and parsed["period_end"] is not None:
        closing = (parsed["period_end"], parsed["closing"])
    return {"kind": KIND, "header": list(HEADER), "rows": parsed["rows"],
            "mapping": dict(MAPPING), "closing": closing, "call": call,
            "pages": found["pages"], "period_start": parsed["period_start"],
            "period_end": parsed["period_end"], "opening": parsed["opening"]}


def adds_up(batch) -> dict | None:
    """Whether the lines read add up to the statement's own closing balance:
    opening, and money in, less money out (the other way round for a card,
    whose balance is what is owed). Arithmetic on what was read, so that a
    misread line shows before anything is written. None when the statement
    printed no opening or closing balance."""
    from django.db.models import Sum

    from apps.finance.models import FinanceAccount, FinanceImportRow

    if batch.opening_balance_cents is None or batch.last_balance_cents is None:
        return None
    rows = FinanceImportRow.all_objects.filter(batch=batch, amount_cents__isnull=False)
    money_in = rows.filter(direction="in").aggregate(t=Sum("amount_cents"))["t"] or 0
    money_out = rows.filter(direction="out").aggregate(t=Sum("amount_cents"))["t"] or 0
    flow = money_in - money_out
    if batch.account.kind == FinanceAccount.Kind.CARD:
        flow = -flow
    expected = batch.opening_balance_cents + flow
    return {"in_cents": money_in, "out_cents": money_out, "expected_cents": expected,
            "difference_cents": batch.last_balance_cents - expected}
