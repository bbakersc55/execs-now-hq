"""Reading a bank's own file formats: OFX, and QFX and QBO, which are OFX
under Quicken's and QuickBooks' names (owner, 2026-10-14).

**No AI is used.** The file says exactly which value is the date, the amount
and the bank's id for the line, so there is nothing to interpret: it is
turned into the same columns a CSV has, and from there it is the same
import, with the same dry run, the same rules and the same commit.

What is read from each transaction: the day it posted, its name and memo, its
amount as the bank signs it (money out is negative, for a card too), the
bank's own id for it, and a check number. And the statement's closing
balance and its date. **Nothing else is read**: the account and routing
numbers in the file are never copied anywhere.

OFX 1.x is SGML, where a value's tag is not closed (`<TRNAMT>-12.50`); 2.x is
XML, where it is. One reader takes both: a value runs from its tag to the
next `<`.
"""

from __future__ import annotations

import html
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from apps.finance.services import FinanceError

KIND = "ofx"
EXTENSIONS = (".ofx", ".qfx", ".qbo")
#: The columns an OFX file is read into, and the mapping that reads them.
HEADER = ["Date", "Description", "Amount", "Transaction ID", "Check number"]
MAPPING = {"date": "Date", "date_format": "%Y-%m-%d", "description": "Description",
           "amount": "Amount", "sign": "negative_is_out", "debit": "", "credit": "",
           "balance": "", "reference": "Check number", "bank_id": "Transaction ID"}

_STATEMENT = re.compile(r"<(?:CC)?STMTRS>", re.I)
_TRANSACTION = re.compile(r"<STMTTRN>(.*?)(?=<STMTTRN>|</BANKTRANLIST>|</STMTTRN>|\Z)",
                          re.I | re.S)
_LEDGER = re.compile(r"<LEDGERBAL>(.*?)(?=</LEDGERBAL>|<AVAILBAL>|</(?:CC)?STMTRS>|\Z)",
                     re.I | re.S)


def is_ofx(file_bytes: bytes, filename: str = "") -> bool:
    start = file_bytes[:4096].upper()
    return b"<OFX" in start or b"OFXHEADER" in start \
        or (filename or "").lower().endswith(EXTENSIONS)


def _value(block: str, tag: str) -> str:
    found = re.search(rf"<{tag}>([^<\r\n]*)", block, re.I)
    return html.unescape(found.group(1)).strip() if found else ""


def _day(text: str) -> date | None:
    """`20261005`, `20261005120000`, or `20261005120000.000[-7:MST]`."""
    digits = re.match(r"\d{8}", text or "")
    if not digits:
        return None
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return None


def _amount(text: str) -> Decimal | None:
    clean = (text or "").replace(" ", "")
    # A few banks write the decimal with a comma, and none write thousands.
    if "," in clean and "." not in clean:
        clean = clean.replace(",", ".")
    clean = clean.replace(",", "")
    try:
        return Decimal(clean).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def read(file_bytes: bytes) -> dict:
    """`{header, rows, closing}`: the transactions as a CSV's rows would be,
    and the statement's closing balance as `(day, cents as the bank signs
    it)` or None."""
    try:
        text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = file_bytes.decode("cp1252", errors="replace")
    start = text.upper().find("<OFX")
    if start < 0:
        raise FinanceError("That is not a bank file this import reads. It takes a CSV, or "
                           "an OFX, QFX or QBO file as the bank gives it.")
    text = text[start:]
    if len(_STATEMENT.findall(text)) > 1:
        raise FinanceError("That file holds more than one account. Download one account "
                           "at a time, and import each into its own account here.")
    rows = []
    for number, block in enumerate(_TRANSACTION.findall(text), start=1):
        on, amount = _day(_value(block, "DTPOSTED")), _amount(_value(block, "TRNAMT"))
        name, memo = _value(block, "NAME"), _value(block, "MEMO")
        described = name if not memo or memo.casefold() in name.casefold() \
            else f"{name} {memo}".strip()
        rows.append({
            # Left as the file wrote them when they cannot be read, so the
            # dry run names the line and says why, as it does for a CSV.
            "Date": on.isoformat() if on else _value(block, "DTPOSTED"),
            "Description": described or _value(block, "TRNTYPE").title() or "(no description)",
            "Amount": f"{amount:.2f}" if amount is not None else _value(block, "TRNAMT"),
            "Transaction ID": _value(block, "FITID"),
            "Check number": _value(block, "CHECKNUM"),
        })
    if not rows:
        raise FinanceError("That file has no transactions in it.")
    closing = None
    ledger = _LEDGER.search(text)
    if ledger:
        on, amount = _day(_value(ledger.group(1), "DTASOF")), \
            _amount(_value(ledger.group(1), "BALAMT"))
        if on and amount is not None:
            closing = (on, int(amount * 100))
    return {"header": list(HEADER), "rows": rows, "closing": closing}
