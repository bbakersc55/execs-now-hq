"""Importing a bank or card export (`docs/p5_finance_accounting.md` §4).

Three steps, as the contact import has them:

1. **Map the columns.** Saved per account.
2. **The dry run.** Every line is read and given an outcome, and **nothing is
   written to the books**: only this batch and its rows exist. The owner fixes
   categories, marks transfers and accepts or declines each proposed match.
3. **Commit**, in one transaction, writing what the dry run showed. A
   committed import can be **rolled back**.

Why matching is here at all: without it the same money is counted twice, once
when a payment is recorded on an invoice and again when the bank's deposit is
imported; and a card payment is an expense in both the bank's file and the
card's. Every match is proposed with both sides shown and is the owner's to
decline.

No AI is used. Rules are the owner's own, remembered (`rules.py`).

The file is a CSV, or the bank's own OFX, QFX or QBO (`bank_files.py`), which
is read into the same columns and from there is the same import. A PDF
statement is the one exception to "no AI": Claude reads it
(`statement_pdf.py`), and what it reads then goes through this same dry run.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.finance import services
from apps.finance.models import (
    FinanceAccount, FinanceCategory, FinanceEntry, FinanceImportBatch,
    FinanceImportProfile, FinanceImportRow, FinanceRule,
)
from apps.finance.services import FinanceError

K = FinanceEntry.Kind
D = FinanceEntry.Direction
T = FinanceCategory.Type
O = FinanceImportRow.Outcome
S = FinanceImportBatch.Status

ROWS_MOST = 5000
#: A deposit is an invoice payment when it is for the same amount and within
#: this many days of the day the payment was recorded as paid (F4).
PAYMENT_DAYS = 7
#: The two sides of a transfer rarely post on the same day.
TRANSFER_DAYS = 5

DATE_FORMATS = (("%m/%d/%Y", "MM/DD/YYYY"), ("%Y-%m-%d", "YYYY-MM-DD"),
                ("%m/%d/%y", "MM/DD/YY"), ("%d/%m/%Y", "DD/MM/YYYY"),
                ("%m-%d-%Y", "MM-DD-YYYY"), ("%b %d, %Y", "Mon D, YYYY"))
SIGNS = ("negative_is_out", "positive_is_out")
MAPPING_KEYS = ("date", "date_format", "description", "amount", "sign", "debit", "credit",
                "balance", "reference", "bank_id")


# ------------------------------------------------------------ reading a file

def read(file_bytes: bytes) -> tuple[list[str], list[dict]]:
    """The header and the rows. UTF-8, or Windows-1252 as Excel saves it."""
    if not file_bytes or not file_bytes.strip():
        raise FinanceError("That file is empty.")
    try:
        text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = file_bytes.decode("cp1252", errors="replace")
    rows = [row for row in csv.reader(io.StringIO(text)) if any(cell.strip() for cell in row)]
    if len(rows) < 2:
        raise FinanceError("That file has no lines under its header.")
    header = [cell.strip() for cell in rows[0]]
    # A first line of figures is data, not names for the columns.
    looks_like_data = any(
        cell and (parse_amount(cell) is not None
                  or any(parse_date(cell, fmt) for fmt, _label in DATE_FORMATS))
        for cell in header)
    if looks_like_data or len(set(header)) < 2 or not any(
            re.search(r"[A-Za-z]", cell) for cell in header):
        raise FinanceError("The first line has to name the columns (Date, Description, "
                           "Amount). This file starts straight in with its figures.")
    if len(rows) - 1 > ROWS_MOST:
        raise FinanceError(f"That file has {len(rows) - 1:,} lines; {ROWS_MOST:,} is the "
                           "most at a time. Export a shorter range of dates.")
    return header, [{name: (row[i].strip() if i < len(row) else "")
                     for i, name in enumerate(header) if name} for row in rows[1:]]


def parse(file_bytes: bytes, filename: str = "") -> dict:
    """Any file this import takes, as `{kind, header, rows, mapping, closing}`.

    For a CSV the mapping is the owner's to choose, so it is None here. For
    an OFX, QFX or QBO file the columns are the format's own and so is the
    mapping; `closing` is the statement's closing balance where it gives one.
    """
    from apps.finance import bank_files

    if not file_bytes or not file_bytes.strip():
        raise FinanceError("That file is empty.")
    if bank_files.is_ofx(file_bytes, filename):
        found = bank_files.read(file_bytes)
        if len(found["rows"]) > ROWS_MOST:
            raise FinanceError(f"That file has {len(found['rows']):,} lines; {ROWS_MOST:,} "
                               "is the most at a time. Download a shorter range of dates.")
        return {"kind": bank_files.KIND, "mapping": dict(bank_files.MAPPING), **found}
    header, rows = read(file_bytes)
    return {"kind": "csv", "header": header, "rows": rows, "mapping": None, "closing": None}


def parse_amount(text: str) -> int | None:
    """Cents, signed, from "$1,234.56", "(45.00)", "-12.5" or "12.50-"."""
    clean = (text or "").strip().replace("$", "").replace(",", "").replace(" ", "")
    if not clean:
        return None
    negative = clean.startswith("(") and clean.endswith(")")
    clean = clean.strip("()")
    if clean.endswith("-"):
        negative, clean = True, clean[:-1]
    if clean.endswith("CR") or clean.endswith("DR"):
        clean = clean[:-2]
    try:
        value = Decimal(clean)
    except InvalidOperation:
        return None
    cents = int((value * 100).to_integral_value())
    return -abs(cents) if negative else cents


def parse_date(text: str, fmt: str) -> date | None:
    try:
        on = datetime.strptime((text or "").strip(), fmt).date()
    except ValueError:
        return None
    # "%Y" takes "26" as the year 26; a two-figure year is "%y"'s to read.
    return on if on.year >= 1900 else None


#: Formats whose order of day and month cannot be misread.
FIXED_ORDER = ("%Y-%m-%d", "%b %d, %Y")


def read_date(text: str, fmt: str) -> tuple[date | None, str]:
    """The date in the saved format, or in whichever format reads it beyond
    doubt: 2026-10-03, Oct 3, 2026, or 10/13/2026 (no month 13). Only a date
    that reads two ways, such as 01/02/2026, needs the format to be chosen.
    Returns the date, or None and why."""
    on = parse_date(text, fmt)
    if on is not None:
        return on, ""
    for other in FIXED_ORDER:
        on = parse_date(text, other)
        if on is not None:
            return on, ""
    found = {parse_date(text, other) for other, _label in DATE_FORMATS} - {None}
    if len(found) == 1:
        on = found.pop()
        if on.day > 12 or on.day == on.month:
            return on, ""
        found = {on, on.replace(month=on.day, day=on.month)}
    if len(found) > 1:
        first, second = sorted(found)
        return None, (f"“{text.strip()}” could be {first:%B} {first.day} or {second:%B} "
                      f"{second.day}, {second.year}. Choose the date format.")
    return None, f"“{text}” is not a date this import reads."


def detect_date_format(values: list[str]) -> str:
    """The first format every non-empty sample reads in."""
    samples = [value for value in values if value.strip()][:50]
    for fmt, _label in DATE_FORMATS:
        if samples and all(parse_date(value, fmt) for value in samples):
            return fmt
    return DATE_FORMATS[0][0]


def suggest(header: list[str], rows: list[dict]) -> dict:
    """A first guess at the mapping, from what the columns are called."""
    def find(*words):
        for name in header:
            if any(word in name.lower() for word in words):
                return name
        return ""

    date_col = find("date", "posted", "when")
    mapping = {
        "date": date_col, "description": find("description", "memo", "payee", "name",
                                              "merchant", "details"),
        "amount": find("amount"), "debit": find("debit", "withdrawal"),
        "credit": find("credit", "deposit"), "balance": find("balance"),
        "reference": find("check", "reference", "ref"),
        "bank_id": find("transaction id", "trans id", "fitid", "id"),
        "sign": "negative_is_out",
    }
    if mapping["amount"]:
        mapping["debit"] = mapping["credit"] = ""
    mapping["date_format"] = detect_date_format([row.get(date_col, "") for row in rows])
    return mapping


def clean_mapping(mapping, header: list[str]) -> dict:
    if not isinstance(mapping, dict):
        raise FinanceError("The mapping says which column is which.")
    out = {key: str(mapping.get(key) or "") for key in MAPPING_KEYS}
    for key in ("date", "description", "amount", "debit", "credit", "balance", "reference",
                "bank_id"):
        if out[key] and out[key] not in header:
            raise FinanceError(f"This file has no column called “{out[key]}”.")
    if not out["date"] or not out["description"]:
        raise FinanceError("Say which column is the date and which is the description.")
    if not out["amount"] and not (out["debit"] or out["credit"]):
        raise FinanceError("Say which column is the amount, or which are money out and "
                           "money in.")
    if out["amount"]:
        out["debit"] = out["credit"] = ""
    if out["date_format"] not in dict(DATE_FORMATS):
        raise FinanceError("That is not a date format this import reads.")
    out["sign"] = out["sign"] if out["sign"] in SIGNS else "negative_is_out"
    return out


def profile_for(account) -> dict | None:
    row = FinanceImportProfile.all_objects.filter(account=account).first()
    return row.mapping if row else None


# ------------------------------------------------------------- the dry run

def _same(text: str) -> str:
    return " ".join((text or "").split()).casefold()


def _read_row(raw: dict, mapping: dict) -> dict:
    """One line as date, amount and direction, or why it cannot be read."""
    on, why = read_date(raw.get(mapping["date"], ""), mapping["date_format"])
    if on is None:
        return {"error": why}
    if mapping["amount"]:
        typed = raw.get(mapping["amount"], "")
        signed = parse_amount(typed)
        if signed is None:
            return {"error": f"“{typed}” is not an amount." if typed.strip()
                    else "This line has no amount."}
        out = signed < 0 if mapping["sign"] == "negative_is_out" else signed > 0
        cents = abs(signed)
    else:
        debit = parse_amount(raw.get(mapping["debit"], "")) if mapping["debit"] else None
        credit = parse_amount(raw.get(mapping["credit"], "")) if mapping["credit"] else None
        if debit:
            out, cents = True, abs(debit)
        elif credit:
            out, cents = False, abs(credit)
        else:
            return {"error": "This line has no amount in either column."}
    if cents == 0:
        return {"error": "This line is for nothing."}
    return {"on_date": on, "amount_cents": cents, "direction": D.OUT if out else D.IN,
            "description": " ".join(raw.get(mapping["description"], "").split())[:255],
            "bank_id": raw.get(mapping["bank_id"], "")[:120] if mapping["bank_id"] else "",
            "reference": raw.get(mapping["reference"], "") if mapping["reference"] else ""}


class _Books:
    """What is already in the books, for one dry run: each thing can be
    matched once, so two identical lines are two entries, not one seen twice."""

    def __init__(self, tenant, account):
        self.tenant, self.account = tenant, account
        live = FinanceEntry.all_objects.filter(tenant=tenant, removed_at__isnull=True)
        # Typed in by hand: known by what the entry itself says.
        here = live.filter(account=account).exclude(kind=K.TRANSFER).exclude(
            source=FinanceEntry.Source.IMPORT)
        self.bank_ids = set(here.exclude(bank_id="").values_list("bank_id", flat=True))
        self.same: dict = {}
        for entry in here:
            key = (entry.on_date, entry.amount_cents, entry.direction,
                   _same(entry.description))
            self.same[key] = self.same.get(key, 0) + 1
        # Brought in by an earlier import of this account: known by **the line
        # as the bank wrote it**, for as long as what it made still stands. So
        # a description tidied up afterwards does not let the same line in
        # twice, and neither does a line that became a transfer or a match.
        earlier = FinanceImportRow.all_objects.filter(
            tenant=tenant, batch__account=account,
            batch__status__in=(S.COMMITTED, S.ROLLED_BACK),
            outcome__in=(O.NEW, O.TRANSFER, O.TRANSFER_MATCH, O.INVOICE_PAYMENT),
        ).select_related("entry", "matched_entry", "batch")
        for row in earlier:
            made = row.entry or row.matched_entry
            if made is None or made.removed_at is not None:
                continue
            if row.outcome in (O.TRANSFER_MATCH, O.INVOICE_PAYMENT):
                # A rollback undid these; a kept, edited entry is the only
                # thing of a rolled-back import that still stands.
                if row.batch.status != S.COMMITTED:
                    continue
                if row.outcome == O.INVOICE_PAYMENT and made.account_id != account.pk:
                    continue
            if row.bank_id:
                self.bank_ids.add(row.bank_id)
            key = (row.on_date, row.amount_cents, row.direction, _same(row.description))
            self.same[key] = self.same.get(key, 0) + 1
        # Transfers already in the books that touch this account, and whether
        # each has been seen from this account's side.
        seen = set(FinanceImportRow.all_objects.filter(
            tenant=tenant, batch__account=account, batch__status=S.COMMITTED,
            outcome__in=(O.TRANSFER, O.TRANSFER_MATCH)).values_list(
                "matched_entry_id", "entry_id"))
        seen_ids = {pk for pair in seen for pk in pair if pk}
        self.transfers = [t for t in live.filter(kind=K.TRANSFER).filter(
            Q(account=account) | Q(to_account=account)).order_by("on_date")
            if t.pk not in seen_ids]
        # Invoice payments not yet placed in an account, whole (fee and tax).
        self.payments = []
        if account.kind != FinanceAccount.Kind.CARD:
            loose = live.filter(source=FinanceEntry.Source.INVOICE, account__isnull=True,
                                client_payment__isnull=False)
            for row in (loose.values("client_payment_id", "on_date")
                        .annotate(total=Sum("amount_cents")).order_by("on_date")):
                entry = loose.filter(client_payment_id=row["client_payment_id"]).order_by(
                    "kind").first()          # the income entry, where there is one
                self.payments.append({"total": row["total"], "on": row["on_date"],
                                      "entry": entry})

    def duplicate(self, line) -> bool:
        if line["bank_id"] and line["bank_id"] in self.bank_ids:
            return True
        key = (line["on_date"], line["amount_cents"], line["direction"],
               _same(line["description"]))
        if self.same.get(key, 0) > 0:
            self.same[key] -= 1
            return True
        return False

    def invoice_payment(self, line):
        if line["direction"] != D.IN:
            return None
        for payment in self.payments:
            if payment["total"] == line["amount_cents"] and \
                    abs((line["on_date"] - payment["on"]).days) <= PAYMENT_DAYS:
                self.payments.remove(payment)
                return payment["entry"]
        return None

    def transfer(self, line):
        """A transfer already in the books from its other side: money out of
        this account matches one that left it; money in, one that reached it."""
        for entry in self.transfers:
            side = entry.account_id if line["direction"] == D.OUT else entry.to_account_id
            if side == self.account.pk and entry.amount_cents == line["amount_cents"] \
                    and abs((line["on_date"] - entry.on_date).days) <= TRANSFER_DAYS:
                self.transfers.remove(entry)
                return entry
        return None


def _fits(category, direction) -> bool:
    """A category a line can take. An income or expense category takes either
    direction (the other way is a refund); owner and held take either too."""
    return category is not None and category.archived_at is None


def _apply_rule(row, rules, account) -> None:
    text = _same(row.description)
    for rule in rules:
        if not rule.is_active or _same(rule.contains) not in text:
            continue
        if rule.account_id and rule.account_id != account.pk:
            continue
        if rule.treat_as == FinanceRule.As.IGNORE:
            row.outcome = O.IGNORE
        elif rule.treat_as == FinanceRule.As.TRANSFER:
            if rule.other_account_id in (None, account.pk):
                continue
            row.outcome, row.other_account = O.TRANSFER, rule.other_account
        elif rule.side == "personal":
            # P6 M4 decision 2: the owner's own spending, whatever the account.
            row.side, row.personal_category = "personal", rule.personal_category
            row.category = row.payee_contact = None
        elif _fits(rule.category, row.direction):
            row.category, row.payee_contact = rule.category, rule.payee_contact
            if rule.side == "split" and rule.split_percent:
                row.side, row.personal_category = "split", rule.personal_category
                row.split_business_cents = round(row.amount_cents * rule.split_percent / 100)
            else:
                row.side = ""
        else:
            continue
        row.rule = rule
        return


def _side_by_threshold(row, account, ledger) -> None:
    """P6 M4 decision 5, for a line of a Mixed account no rule decided: under
    the owner's threshold it is personal, in Everything else, without asking;
    at or over it, it waits in To sort."""
    if account.side != FinanceAccount.Side.MIXED or row.outcome != O.NEW or row.rule_id:
        return
    from apps.personal import services as personal

    small = ledger is not None and row.amount_cents < ledger.to_sort_threshold_cents
    if small:
        row.side = "personal"
        row.personal_category = personal.system_category(ledger, personal.EVERYTHING_ELSE)
    else:
        row.side = "to_sort"
    row.category = None


def _counts(batch) -> dict:
    rows = FinanceImportRow.all_objects.filter(batch=batch)
    counts = {outcome: rows.filter(outcome=outcome).count() for outcome in O.values}
    counts["needs_category"] = rows.filter(outcome=O.NEW, category__isnull=True,
                                           side="").count()
    # P6 M4: the personal side of a Mixed (or Business) account's lines.
    counts["to_sort"] = rows.filter(outcome=O.NEW, side="to_sort").count()
    counts["personal"] = rows.filter(outcome=O.NEW, side__in=("personal", "split")).count()
    counts["total"] = rows.count()
    return counts


def dry_run(tenant, *, account, filename, file_bytes, mapping, actor=None):
    """Read every line and decide what would happen to it. Writes this batch
    and its rows, and nothing to the books.

    A PDF statement is read by Claude first, outside the transaction that
    writes the batch: that read costs whatever happens after it, so its
    `ai_call` must stand even if the rest fails."""
    from apps.finance import statement_pdf

    if account.closed_at is not None:
        raise FinanceError(f"“{account.name}” is closed.")
    if file_bytes and statement_pdf.is_pdf(file_bytes, filename):
        parsed = statement_pdf.read(tenant, file_bytes=file_bytes)
    else:
        parsed = parse(file_bytes, filename)
    return _dry_run(tenant, account=account, filename=filename, file_bytes=file_bytes,
                    mapping=mapping, parsed=parsed, actor=actor)


@transaction.atomic
def _dry_run(tenant, *, account, filename, file_bytes, mapping, parsed, actor=None):
    from apps.finance import bank_files, statement_pdf

    header, raws = parsed["header"], parsed["rows"]
    # A bank's own file format says which value is which: nothing to choose.
    mapping = clean_mapping(parsed["mapping"] or mapping, header)
    services.ensure_chart(tenant)
    batch = FinanceImportBatch.all_objects.create(
        tenant=tenant, account=account, filename=(filename or "export.csv")[:255],
        mapping=mapping, created_by=actor, source=parsed["kind"])
    if parsed["kind"] == statement_pdf.KIND:
        from apps.tenancy import storage

        # The PDF is the statement, so it is kept with the import. From it:
        # the period and the two balances, and nothing about whose it is.
        batch.statement_file = storage.save(
            tenant=tenant, content=file_bytes,
            object_key=storage.object_key("statements", batch.filename),
            purpose=statement_pdf.STORED_AS, content_type="application/pdf")
        batch.period_start, batch.period_end = parsed["period_start"], parsed["period_end"]
        batch.opening_balance_cents = parsed["opening"]
        batch.ai_call = parsed["call"]
    books = _Books(tenant, account)
    rules = list(FinanceRule.all_objects.filter(tenant=tenant, is_active=True)
                 .select_related("category", "other_account", "payee_contact",
                                 "personal_category"))
    ledger = None
    if account.side == FinanceAccount.Side.MIXED and actor is not None:
        from apps.personal import services as personal

        ledger = personal.ledger_for(actor)
    last_balance = None
    for number, raw in enumerate(raws, start=2):          # line 1 is the header
        row = FinanceImportRow(tenant=tenant, batch=batch, row_number=number, raw=raw,
                               outcome=O.NEW)
        line = _read_row(raw, mapping)
        if "error" in line:
            row.outcome, row.error_text = O.ERROR, line["error"][:255]
            row.save()
            continue
        row.on_date, row.amount_cents = line["on_date"], line["amount_cents"]
        row.direction, row.description = line["direction"], line["description"]
        row.bank_id = line["bank_id"]
        if mapping["balance"]:
            balance = parse_amount(raw.get(mapping["balance"], ""))
            if balance is not None and (last_balance is None
                                        or line["on_date"] >= last_balance[0]):
                last_balance = (line["on_date"], balance)
        if books.duplicate(line):
            row.outcome = O.DUPLICATE
        else:
            payment = books.invoice_payment(line)
            other_side = None if payment else books.transfer(line)
            if payment is not None:
                row.outcome, row.matched_entry = O.INVOICE_PAYMENT, payment
            elif other_side is not None:
                row.outcome, row.matched_entry = O.TRANSFER_MATCH, other_side
            else:
                _apply_rule(row, rules, account)
                _side_by_threshold(row, account, ledger)
        row.save()
    if parsed["closing"] is not None:
        # The statement's own closing balance. A card's is what is owed,
        # which an OFX file writes as a negative number and the books as a
        # positive one; a PDF's is asked for as what is owed.
        on, cents = parsed["closing"]
        owed_as_negative = parsed["kind"] == bank_files.KIND \
            and account.kind == FinanceAccount.Kind.CARD
        last_balance = (on, -cents if owed_as_negative else cents)
    if last_balance is not None:
        batch.last_balance_on, batch.last_balance_cents = last_balance
    batch.counts = _counts(batch)
    batch.save()
    if parsed["mapping"] is None:
        # Only a CSV's columns are the owner's choice, and worth remembering.
        FinanceImportProfile.all_objects.update_or_create(
            account=account, defaults={"tenant": tenant, "mapping": mapping})
    return batch


# ------------------------------------------- the owner's decisions on a row

def _only_dry_run(batch) -> None:
    if batch.status != S.DRY_RUN:
        raise FinanceError("This import is already "
                           f"{batch.get_status_display().lower()}; its lines are fixed.",
                           status=409)


@transaction.atomic
def decide(row, *, decision, category=None, other_account=None, payee_contact=...,
           remember=None, actor=None, side=None, personal_category=None,
           split_business_cents=None) -> FinanceImportRow:
    """What the owner says a line is, while the import is still a dry run.

    `decision`: "entry" (with a category, or none yet), "transfer" (with the
    other account), "ignore", or "not_a_match" (a proposed match declined: the
    line becomes a new entry).

    `remember`: text to remember the choice by, for lines that contain it.

    P6 M4: an "entry" has a `side` too: "business" (as before), "personal"
    (the owner's own, in `personal_category` of their ledger), "split"
    (`split_business_cents` of it business, in `category`) or "to_sort".
    """
    batch = FinanceImportBatch.all_objects.select_for_update().get(pk=row.batch_id)
    _only_dry_run(batch)
    if row.outcome in (O.ERROR, O.DUPLICATE):
        raise FinanceError("That line is not going into the books, so there is nothing "
                           "to decide about it.", status=409)
    account = batch.account
    if decision == "entry":
        if category is not None and (category.tenant_id != row.tenant_id
                                     or category.archived_at is not None):
            raise FinanceError("Choose a category that is in use.")
        row.outcome, row.category = O.NEW, category
        row.other_account = row.matched_entry = None
        _decide_side(row, side=side, actor=actor, personal_category=personal_category,
                     split_business_cents=split_business_cents)
    elif decision == "transfer":
        if other_account is None or other_account.tenant_id != row.tenant_id \
                or other_account.pk == account.pk or other_account.closed_at is not None:
            raise FinanceError("A transfer is to or from another of your open accounts.")
        row.outcome, row.other_account = O.TRANSFER, other_account
        row.category = row.matched_entry = None
    elif decision == "ignore":
        row.outcome, row.category = O.IGNORE, None
        row.other_account = row.matched_entry = None
    elif decision == "not_a_match":
        if row.outcome not in (O.INVOICE_PAYMENT, O.TRANSFER_MATCH):
            raise FinanceError("That line was not matched to anything.", status=409)
        row.outcome, row.matched_entry = O.NEW, None
    else:
        raise FinanceError("decision is entry, transfer, ignore or not_a_match.")
    if payee_contact is not ...:
        if payee_contact is not None and payee_contact.tenant_id != row.tenant_id:
            raise FinanceError("That person is not in this practice.", status=404)
        row.payee_contact = payee_contact
    if decision != "entry":
        row.side, row.personal_category, row.split_business_cents = "", None, None
    row.rule = None
    row.save()

    if remember is not None and decision in ("entry", "transfer", "ignore") \
            and row.side != "to_sort":
        from apps.finance import rules as rule_service

        split_percent = (round(row.split_business_cents * 100 / row.amount_cents)
                         if row.side == "split" else None)
        rule = rule_service.save_rule(
            row.tenant, actor=actor, contains=remember,
            treat_as={"entry": "category", "transfer": "transfer",
                      "ignore": "ignore"}[decision],
            category=category, other_account=other_account,
            payee_contact=row.payee_contact if decision == "entry" else None,
            side=row.side if decision == "entry" else "",
            personal_category=row.personal_category if decision == "entry" else None,
            split_percent=split_percent if split_percent and 0 < split_percent < 100
            else None)
        row.rule = rule
        row.save(update_fields=["rule", "updated_at"])
        # The other undecided lines of this import take it at once.
        waiting = FinanceImportRow.all_objects.filter(
            batch=batch, outcome=O.NEW, category__isnull=True, rule__isnull=True)
        for other in waiting.exclude(pk=row.pk):
            if other.side not in ("", "to_sort") and other.personal_category_id:
                continue                      # already decided as personal
            _apply_rule(other, [rule], account)
            if other.rule_id:
                other.save()
    batch.counts = _counts(batch)
    batch.save(update_fields=["counts", "updated_at"])
    return row


def _decide_side(row, *, side, actor, personal_category, split_business_cents) -> None:
    """The owner's side for a line (P6 M4 decision 2). With no side said, a
    line keeps the side it had, unless a category was chosen: that is a
    business line."""
    if side is None:
        side = "business" if row.category_id else (row.side or "business")
    if side not in ("business", "personal", "split", "to_sort"):
        raise FinanceError("side is business, personal, split or to_sort.")
    if side in ("personal", "split"):
        from apps.personal import services as personal

        if actor is None:
            raise FinanceError("A personal line needs whose ledger it goes to.")
        ledger = personal.ledger_for(actor)
        if personal_category is not None and personal_category.ledger_id != ledger.pk:
            raise FinanceError("That personal category is not yours.", status=404)
    if side == "split":
        if row.category_id is None:
            raise FinanceError("Choose the business category for the business part.")
        if split_business_cents is None or not 0 < split_business_cents < row.amount_cents:
            raise FinanceError("The business part of a split is more than nothing and less "
                               "than the whole line.")
    row.side = "" if side == "business" else side
    row.personal_category = personal_category if side in ("personal", "split") else None
    row.split_business_cents = split_business_cents if side == "split" else None
    if side in ("personal", "to_sort"):
        row.category = row.payee_contact = None


# -------------------------------------------------------- commit and rollback

def _kind_for(category, direction):
    if category is None:
        return K.EXPENSE if direction == D.OUT else K.INCOME
    return {T.INCOME: K.INCOME, T.EXPENSE: K.EXPENSE, T.OWNER: K.OWNER,
            T.HELD: K.HELD}[category.type]


@transaction.atomic
def commit(batch, *, actor=None) -> FinanceImportBatch:
    """Write what the dry run showed, in one transaction. If the books have
    moved under a match since it was shown, nothing is written and the owner is
    asked to run it again."""
    batch = FinanceImportBatch.all_objects.select_for_update().get(pk=batch.pk)
    _only_dry_run(batch)
    account, tenant = batch.account, batch.tenant
    rows = list(FinanceImportRow.all_objects.filter(batch=batch).select_related(
        "category", "other_account", "matched_entry", "payee_contact"))
    writing = [row for row in rows
               if row.outcome in (O.NEW, O.TRANSFER, O.INVOICE_PAYMENT, O.TRANSFER_MATCH)]
    services._unlocked(tenant, *[row.on_date for row in writing])
    stale = FinanceError("The books have changed since this import was shown. Run the dry "
                         "run again, so what is written is what you saw.", status=409)
    # A line that has reached the books some other way since it was shown (the
    # same file committed from another dry run) is not written a second time.
    now = _Books(tenant, account)
    for row in writing:
        if row.outcome in (O.NEW, O.TRANSFER) and now.duplicate(
                {"bank_id": row.bank_id, "on_date": row.on_date,
                 "amount_cents": row.amount_cents, "direction": row.direction,
                 "description": row.description}):
            raise stale
    ledger = None
    if any(row.outcome == O.NEW and row.side in ("personal", "split") for row in writing):
        from apps.personal import services as personal

        if actor is None:
            raise FinanceError("Personal lines need whose ledger they go to.")
        ledger = personal.ledger_for(actor)
    for row in writing:
        if row.outcome == O.NEW and row.side in ("personal", "split"):
            _commit_personal(row, batch=batch, account=account, ledger=ledger, actor=actor)
        elif row.outcome == O.NEW:
            entry = FinanceEntry.all_objects.create(
                tenant=tenant, kind=_kind_for(row.category, row.direction),
                direction=row.direction, on_date=row.on_date,
                amount_cents=row.amount_cents, category=row.category, account=account,
                description=row.description, bank_id=row.bank_id,
                reference=str(row.raw.get(batch.mapping.get("reference") or "", ""))[:120],
                payee_contact=row.payee_contact, source=FinanceEntry.Source.IMPORT,
                # A Mixed account's line no rule placed waits to be sorted.
                side=(FinanceEntry.Side.TO_SORT if row.side == "to_sort"
                      else FinanceEntry.Side.BUSINESS),
                created_by=actor)
            row.entry = entry
        elif row.outcome == O.TRANSFER:
            if row.other_account is None:
                raise stale
            out = row.direction == D.OUT
            row.entry = FinanceEntry.all_objects.create(
                tenant=tenant, kind=K.TRANSFER, direction=D.OUT, on_date=row.on_date,
                amount_cents=row.amount_cents,
                account=account if out else row.other_account,
                to_account=row.other_account if out else account,
                description=row.description, bank_id=row.bank_id,
                source=FinanceEntry.Source.IMPORT, created_by=actor)
        elif row.outcome == O.INVOICE_PAYMENT:
            matched = row.matched_entry
            if matched is None or matched.removed_at is not None \
                    or matched.account_id is not None:
                raise stale
            # The payment's fee and its tax land in the same account.
            FinanceEntry.all_objects.filter(
                tenant=tenant, client_payment_id=matched.client_payment_id,
                removed_at__isnull=True, account__isnull=True).update(
                    account=account, updated_at=timezone.now())
            services.audit(tenant, "entry_matched", actor, matched,
                           account=str(account.pk), batch=str(batch.pk),
                           line=row.description)
        elif row.outcome == O.TRANSFER_MATCH:
            if row.matched_entry is None or row.matched_entry.removed_at is not None:
                raise stale
        row.save(update_fields=["entry", "draw_entry", "updated_at"])
        for made in (row.entry, row.draw_entry):
            if made is not None and row.outcome in (O.NEW, O.TRANSFER):
                services.audit(tenant, "entry_added", actor, made,
                               after=services._state(made), batch=str(batch.pk))
    batch.status = S.COMMITTED
    batch.committed_at = timezone.now()
    batch.counts = _counts(batch)
    batch.save()
    services.audit(tenant, "import_committed", actor, batch, account=account.name,
                   filename=batch.filename, counts=batch.counts)
    # They came from the bank, so the statement shows them (P6 M1-4).
    from apps.finance import reconcile

    reconcile.imported(batch)
    # P6 M4 decision 20: a draw that came in is matched to the pay it was.
    from apps.personal import paydays

    paydays.match_for_practice(tenant)
    return batch


def _commit_personal(row, *, batch, account, ledger, actor) -> None:
    """P6 M4 decision 3: the personal part of a line is an owner draw in the
    books (money in: a contribution) and the spend itself in the owner's
    ledger. A split's business part is an ordinary entry beside it."""
    from apps.personal import services as personal

    tenant = batch.tenant
    personal_cents = row.amount_cents
    if row.side == "split":
        row.entry = FinanceEntry.all_objects.create(
            tenant=tenant, kind=_kind_for(row.category, row.direction),
            direction=row.direction, on_date=row.on_date,
            amount_cents=row.split_business_cents, category=row.category, account=account,
            description=row.description, bank_id=row.bank_id,
            payee_contact=row.payee_contact, source=FinanceEntry.Source.IMPORT,
            created_by=actor)
        personal_cents = row.amount_cents - row.split_business_cents
    draw = FinanceEntry.all_objects.create(
        tenant=tenant, kind=K.OWNER, direction=row.direction, on_date=row.on_date,
        amount_cents=personal_cents, category=personal.owner_category(tenant, row.direction),
        account=account, description=row.description,
        bank_id="" if row.side == "split" else row.bank_id,
        source=FinanceEntry.Source.IMPORT, side=FinanceEntry.Side.PERSONAL,
        created_by=actor)
    personal.line_for_entry(draw, ledger=ledger, category=row.personal_category)
    if row.side == "split":
        row.draw_entry = draw
    else:
        row.entry = draw


@transaction.atomic
def rollback(batch, *, actor=None) -> dict:
    """Undo a committed import: every entry it made that has not been changed
    since is removed, and every match it made is undone. An entry edited since
    is kept, and named."""
    batch = FinanceImportBatch.all_objects.select_for_update().get(pk=batch.pk)
    if batch.status != S.COMMITTED:
        raise FinanceError("Only a committed import can be rolled back.", status=409)
    tenant = batch.tenant
    rows = list(FinanceImportRow.all_objects.filter(batch=batch).select_related(
        "entry", "matched_entry", "draw_entry"))
    services._unlocked(tenant, *[row.on_date for row in rows
                                 if row.entry_id or row.matched_entry_id or row.draw_entry_id])
    from apps.finance import reconcile
    from apps.tenancy.models import AuditEvent

    edited = set(AuditEvent.all_objects.filter(
        tenant=tenant, verb="finance.entry_changed", target_type="finance_entry",
        target_id__in=[pk for row in rows for pk in (row.entry_id, row.draw_entry_id) if pk],
        created_at__gt=batch.committed_at).values_list("target_id", flat=True))
    removed, kept, unmatched = 0, [], 0
    # A split's owner draw goes with its business part (P6 M4 decision 3).
    rows = rows + [FinanceImportRow(outcome=row.outcome, entry=row.draw_entry)
                   for row in rows if row.draw_entry_id]
    for row in rows:
        entry = row.entry
        if entry is not None and row.outcome in (O.NEW, O.TRANSFER):
            if entry.removed_at is not None:
                continue
            if entry.pk in edited:
                kept.append({"on_date": entry.on_date.isoformat(),
                             "amount_cents": entry.amount_cents,
                             "description": entry.description})
                continue
            services.remove_entry(entry, actor=actor,
                                  reason=f"Import of {batch.filename} rolled back.")
            removed += 1
        elif row.outcome == O.INVOICE_PAYMENT and row.matched_entry is not None:
            matched = row.matched_entry
            placed = FinanceEntry.all_objects.filter(
                tenant=tenant, client_payment_id=matched.client_payment_id,
                removed_at__isnull=True, account=batch.account)
            for entry in placed:
                # One ticked off on a finished statement stays in its account.
                held = reconcile.snapshot(entry)
                entry.account = None
                reconcile.hold(entry, held)
            if placed.update(account=None, updated_at=timezone.now()):
                unmatched += 1
    batch.status = S.ROLLED_BACK
    batch.rolled_back_at = timezone.now()
    batch.save(update_fields=["status", "rolled_back_at", "updated_at"])
    result = {"removed": removed, "kept": kept, "unmatched": unmatched}
    services.audit(tenant, "import_rolled_back", actor, batch, filename=batch.filename,
                   **result)
    return result


def bank_said(tenant) -> dict:
    """For each account, the bank's own balance on the last line of its newest
    committed import that carried one: a check beside the balance view."""
    out = {}
    for batch in (FinanceImportBatch.all_objects.filter(
            tenant=tenant, status=S.COMMITTED, last_balance_cents__isnull=False)
            .order_by("last_balance_on", "committed_at")):
        out[batch.account_id] = {"on": batch.last_balance_on,
                                 "cents": batch.last_balance_cents}
    return out
