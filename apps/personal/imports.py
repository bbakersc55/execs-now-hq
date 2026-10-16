"""Importing a statement into a **personal** account (P6 M4 stop 1, decisions
2, 3, 5 and 7): the books' import, on the household's side.

The same file types as the books (a CSV, the bank's OFX, QFX or QBO, or a PDF
statement read by Claude, priced first) and the same three steps: the dry
run writes only this import and its rows; the commit writes what it showed;
a committed import can be rolled back. The reading is the books' own
(`apps.finance.importer`); what differs is where each line goes:

- **Personal** (every line with no rule, as decision 5 has it: under the
  owner's threshold to Everything else without asking, at or over it to
  To sort): a line of the ledger, in its category.
- **Business** (a rule of the practice's, or the owner's choice): the
  practice's, **paid personally**. In the books, an income or expense in its
  category and in none of the practice's accounts; in the ledger, the line
  stays in its account, in "Paid for the practice", because the bank shows
  it. A **split** is both, the business part as above and the rest personal.
- **A transfer** between the household's own accounts (decision 7): a line
  that matches one already in the ledger, the other way, from another of
  the household's accounts, is proposed as its other side and paired with
  it on commit. Both are then Transfers, which is never spending.

Each posting is reversible from the import's rollback: its lines leave the
ledger, its books entries leave the books, and its pairings are undone.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.finance import importer as books_import
from apps.finance import services as books
from apps.finance.models import FinanceCategory, FinanceRule
from apps.personal import services
from apps.personal.models import (
    PersonalAccount, PersonalCategory, PersonalImport, PersonalImportRow, PersonalLine,
)
from apps.personal.services import PersonalError

O = PersonalImportRow.Outcome
SIDE = PersonalImportRow.Side
S = PersonalImport.Status


def _refused(exc) -> PersonalError:
    return PersonalError(str(exc), status=getattr(exc, "status", 400))


def parse(tenant, *, file_bytes, filename):
    """The file, read as the books read one. A PDF costs, and is read by
    Claude on the practice's key and budget, priced first."""
    from apps.finance import statement_pdf

    try:
        if file_bytes and statement_pdf.is_pdf(file_bytes, filename):
            return statement_pdf.read(tenant, file_bytes=file_bytes)
        return books_import.parse(file_bytes, filename)
    except books.FinanceError as exc:
        raise _refused(exc) from None


class _Ledger:
    """What is already in this account, for one dry run: each line can be
    matched once, as the books' import has it."""

    def __init__(self, ledger, account):
        self.ledger, self.account = ledger, account
        live = PersonalLine.objects.filter(ledger=ledger, account=account,
                                           removed_at__isnull=True)
        self.bank_ids: set = set()
        self.same: dict = {}
        # Brought in by an earlier import of this account: known by the line
        # as the bank wrote it, for as long as what it made still stands.
        earlier = PersonalImportRow.objects.filter(
            ledger=ledger, batch__account=account, batch__status=S.COMMITTED,
            outcome__in=(O.NEW, O.TRANSFER_MATCH)).select_related("line")
        for row in earlier:
            if row.line is None or row.line.removed_at is not None:
                continue
            if row.bank_id:
                self.bank_ids.add(row.bank_id)
            self._count(row.on_date, row.amount_cents, row.direction, row.description)
        for line in live.exclude(source=PersonalLine.Source.IMPORT):
            self._count(line.on_date, line.amount_cents, line.direction, line.description)
        self.taken: set = set()

    def _count(self, *key_parts):
        key = (key_parts[0], key_parts[1], key_parts[2], books_import._same(key_parts[3]))
        self.same[key] = self.same.get(key, 0) + 1

    def duplicate(self, line) -> bool:
        if line["bank_id"] and line["bank_id"] in self.bank_ids:
            return True
        key = (line["on_date"], line["amount_cents"], line["direction"],
               books_import._same(line["description"]))
        if self.same.get(key, 0) > 0:
            self.same[key] -= 1
            return True
        return False

    def transfer(self, line):
        for found in services.transfer_candidates(
                self.ledger, account=self.account, on_date=line["on_date"],
                amount_cents=line["amount_cents"], direction=line["direction"]):
            if found.pk not in self.taken:
                self.taken.add(found.pk)
                return found
        return None


def _apply_rule(row, rules) -> None:
    """The practice's rules, as they reach a line of a personal account: a
    personal rule puts it in its category; a business rule makes it the
    practice's, paid personally; a split, both. A rule for one of the
    practice's own accounts, a transfer rule and an ignore rule do not
    reach it (their accounts are the practice's)."""
    text = books_import._same(row.description)
    for rule in rules:
        if not rule.is_active or books_import._same(rule.contains) not in text:
            continue
        if rule.account_id or rule.treat_as != FinanceRule.As.CATEGORY:
            continue
        if rule.side == "personal":
            row.side, row.category, row.business_category = SIDE.PERSONAL, \
                rule.personal_category, None
        elif rule.category is None or rule.category.archived_at is not None:
            continue
        elif rule.side == "split" and rule.split_percent:
            row.side, row.business_category = SIDE.SPLIT, rule.category
            row.category = rule.personal_category
            row.split_business_cents = round(row.amount_cents * rule.split_percent / 100)
        else:
            row.side, row.business_category, row.category = SIDE.BUSINESS, rule.category, None
        row.rule = rule
        return


def _by_threshold(row, ledger) -> None:
    """Decision 5: a line no rule decided is the household's; under the
    threshold, Everything else without asking; at or over it, To sort."""
    if row.rule_id or row.outcome != O.NEW:
        return
    if row.amount_cents < ledger.to_sort_threshold_cents:
        row.side = SIDE.PERSONAL
        row.category = services.system_category(ledger, services.EVERYTHING_ELSE)
    else:
        row.side, row.category = SIDE.TO_SORT, None


def counts(batch) -> dict:
    rows = PersonalImportRow.objects.filter(batch=batch)
    out = {outcome: rows.filter(outcome=outcome).count() for outcome in O.values}
    new = rows.filter(outcome=O.NEW)
    out["personal"] = new.filter(side=SIDE.PERSONAL).count()
    out["business"] = new.filter(side=SIDE.BUSINESS).count()
    out["split"] = new.filter(side=SIDE.SPLIT).count()
    out["to_sort"] = new.filter(side=SIDE.TO_SORT).count()
    out["total"] = rows.count()
    return out


def adds_up(batch) -> dict | None:
    """As the books' PDF check: do the lines read come to the statement's
    own ending balance?"""
    if batch.opening_balance_cents is None or batch.last_balance_cents is None:
        return None
    rows = PersonalImportRow.objects.filter(batch=batch, amount_cents__isnull=False)
    money_in = rows.filter(direction="in").aggregate(t=Sum("amount_cents"))["t"] or 0
    money_out = rows.filter(direction="out").aggregate(t=Sum("amount_cents"))["t"] or 0
    flow = money_in - money_out
    if batch.account.kind == PersonalAccount.Kind.CARD:
        flow = -flow
    expected = batch.opening_balance_cents + flow
    return {"in_cents": money_in, "out_cents": money_out, "expected_cents": expected,
            "difference_cents": batch.last_balance_cents - expected}


def dry_run(tenant, *, ledger, account, filename, file_bytes, mapping):
    """Read every line and decide what would happen to it. Writes this
    import and its rows, and nothing else. A PDF is read first, outside the
    transaction, so its cost stands whatever happens after."""
    if account.ledger_id != ledger.pk:
        raise PersonalError("That account is not yours.", status=404)
    if account.closed_at is not None:
        raise PersonalError(f"“{account.name}” is closed.")
    parsed = parse(tenant, file_bytes=file_bytes, filename=filename)
    return _dry_run(tenant, ledger=ledger, account=account, filename=filename,
                    mapping=mapping, parsed=parsed)


@transaction.atomic
def _dry_run(tenant, *, ledger, account, filename, mapping, parsed):
    from apps.finance import bank_files, statement_pdf

    try:
        mapping = books_import.clean_mapping(parsed["mapping"] or mapping, parsed["header"])
    except books.FinanceError as exc:
        raise _refused(exc) from None
    batch = PersonalImport.objects.create(
        ledger=ledger, account=account, tenant=tenant,
        filename=(filename or "export.csv")[:255], source=parsed["kind"], mapping=mapping)
    if parsed["kind"] == statement_pdf.KIND:
        # What was read, never whose it is; the PDF itself is not kept here.
        batch.period_start, batch.period_end = parsed["period_start"], parsed["period_end"]
        batch.opening_balance_cents = parsed["opening"]
        batch.cost_usd = parsed["call"].cost_usd if parsed.get("call") else None
    here = _Ledger(ledger, account)
    rules = list(FinanceRule.all_objects.filter(tenant=tenant, is_active=True)
                 .select_related("category", "personal_category"))
    last_balance = None
    for number, raw in enumerate(parsed["rows"], start=2):
        row = PersonalImportRow(ledger=ledger, batch=batch, row_number=number, raw=raw,
                                outcome=O.NEW)
        line = books_import._read_row(raw, mapping)
        if "error" in line:
            row.outcome, row.error_text = O.ERROR, line["error"][:255]
            row.save()
            continue
        row.on_date, row.amount_cents = line["on_date"], line["amount_cents"]
        row.direction, row.description = line["direction"], line["description"]
        row.bank_id = line["bank_id"]
        if mapping["balance"]:
            balance = books_import.parse_amount(raw.get(mapping["balance"], ""))
            if balance is not None and (last_balance is None
                                        or line["on_date"] >= last_balance[0]):
                last_balance = (line["on_date"], balance)
        if here.duplicate(line):
            row.outcome = O.DUPLICATE
        else:
            other = here.transfer(line)
            if other is not None:
                row.outcome, row.matched_line = O.TRANSFER_MATCH, other
                row.side = SIDE.PERSONAL
                row.category = services.system_category(ledger, services.TRANSFERS)
            else:
                _apply_rule(row, rules)
                _by_threshold(row, ledger)
        row.save()
    if parsed["closing"] is not None:
        on, cents = parsed["closing"]
        owed_as_negative = parsed["kind"] == bank_files.KIND \
            and account.kind == PersonalAccount.Kind.CARD
        last_balance = (on, -cents if owed_as_negative else cents)
    if last_balance is not None:
        batch.last_balance_on, batch.last_balance_cents = last_balance
    batch.counts = counts(batch)
    batch.save()
    if parsed["mapping"] is None:
        account.import_mapping = mapping
        account.save(update_fields=["import_mapping", "updated_at"])
    return batch


def _only_dry_run(batch) -> None:
    if batch.status != S.DRY_RUN:
        raise PersonalError("This import is already "
                            f"{batch.get_status_display().lower()}; its lines are fixed.",
                            status=409)


@transaction.atomic
def decide(row, *, tenant, actor, decision, side=None, category=None,
           business_category=None, split_business_cents=None, remember=None):
    """What the owner says a line is, while the import is a dry run.

    `decision`: "line" (with a `side`: personal, business, split or to_sort),
    "ignore", or "not_a_match" (a proposed transfer declined).
    `remember`: the text to keep the choice by, as a rule of the practice's.
    """
    batch = PersonalImport.objects.select_for_update().get(pk=row.batch_id)
    _only_dry_run(batch)
    if row.outcome in (O.ERROR, O.DUPLICATE):
        raise PersonalError("That line is not going in, so there is nothing to decide "
                            "about it.", status=409)
    if business_category is not None and (business_category.tenant_id != tenant.pk
                                          or business_category.archived_at is not None):
        raise PersonalError("Choose a category of the practice's that is in use.")
    if category is not None and category.ledger_id != batch.ledger_id:
        raise PersonalError("That personal category is not yours.", status=404)
    if decision == "line":
        side = side or SIDE.PERSONAL
        if side not in SIDE.values:
            raise PersonalError("side is personal, business, split or to_sort.")
        if side in (SIDE.BUSINESS, SIDE.SPLIT) and (
                business_category is None or business_category.type not in (
                    FinanceCategory.Type.INCOME, FinanceCategory.Type.EXPENSE)):
            raise PersonalError("Choose the practice's income or expense category for the "
                                "business part.")
        if side == SIDE.SPLIT and (split_business_cents is None
                                   or not 0 < split_business_cents < row.amount_cents):
            raise PersonalError("The business part of a split is more than nothing and "
                                "less than the whole line.")
        row.outcome, row.side, row.matched_line = O.NEW, side, None
        row.category = category if side in (SIDE.PERSONAL, SIDE.SPLIT) else None
        row.business_category = business_category if side in (SIDE.BUSINESS, SIDE.SPLIT) \
            else None
        row.split_business_cents = split_business_cents if side == SIDE.SPLIT else None
    elif decision == "ignore":
        row.outcome, row.matched_line = O.IGNORE, None
    elif decision == "not_a_match":
        if row.outcome != O.TRANSFER_MATCH:
            raise PersonalError("That line was not matched to anything.", status=409)
        row.outcome, row.matched_line, row.category = O.NEW, None, None
        row.side = SIDE.TO_SORT
    else:
        raise PersonalError("decision is line, ignore or not_a_match.")
    row.rule = None
    row.save()
    if remember and decision == "line" and row.side != SIDE.TO_SORT:
        split_percent = (round(row.split_business_cents * 100 / row.amount_cents)
                         if row.side == SIDE.SPLIT else None)
        try:
            rule = services.remember_rule(
                tenant, actor=actor, contains=remember,
                side={"personal": "personal", "business": "business",
                      "split": "split"}[row.side],
                category=row.business_category, personal_category=row.category,
                split_percent=split_percent if split_percent and 0 < split_percent < 100
                else None)
        except books.FinanceError as exc:
            raise _refused(exc) from None
        row.rule = rule
        row.save(update_fields=["rule", "updated_at"])
        # The other undecided lines of this import take it at once.
        for other in PersonalImportRow.objects.filter(
                batch=batch, outcome=O.NEW, rule__isnull=True).exclude(pk=row.pk):
            if other.side == SIDE.TO_SORT or (other.side == SIDE.PERSONAL
                                              and other.category is not None
                                              and other.category.system_code
                                              == services.EVERYTHING_ELSE):
                _apply_rule(other, [rule])
                if other.rule_id:
                    other.save()
    batch.counts = counts(batch)
    batch.save(update_fields=["counts", "updated_at"])
    return row


@transaction.atomic
def commit(batch, *, tenant, actor) -> PersonalImport:
    """Write what the dry run showed, in one transaction."""
    batch = PersonalImport.objects.select_for_update().get(pk=batch.pk)
    _only_dry_run(batch)
    ledger, account = batch.ledger, batch.account
    rows = list(PersonalImportRow.objects.filter(batch=batch).select_related(
        "category", "business_category", "matched_line"))
    stale = PersonalError("This account has changed since this import was shown. Run the "
                          "dry run again, so what is written is what you saw.", status=409)
    now = _Ledger(ledger, account)
    if any(row.side in (SIDE.BUSINESS, SIDE.SPLIT) for row in rows if row.outcome == O.NEW):
        try:
            books._unlocked(tenant, *[row.on_date for row in rows if row.outcome == O.NEW
                                      and row.side in (SIDE.BUSINESS, SIDE.SPLIT)])
        except books.FinanceError as exc:
            raise _refused(exc) from None
    for row in rows:
        if row.outcome not in (O.NEW, O.TRANSFER_MATCH):
            continue
        if now.duplicate({"bank_id": row.bank_id, "on_date": row.on_date,
                          "amount_cents": row.amount_cents, "direction": row.direction,
                          "description": row.description}):
            raise stale
        made = dict(ledger=ledger, account=account, on_date=row.on_date,
                    direction=row.direction, description=row.description,
                    source=PersonalLine.Source.IMPORT)
        if row.outcome == O.TRANSFER_MATCH:
            other = row.matched_line
            if other is None or other.removed_at is not None or other.transfer_pair_id:
                raise stale
            row.matched_category_before = other.category
            row.line = PersonalLine.objects.create(amount_cents=row.amount_cents,
                                                   category=row.category, **made)
            services.pair(row.line, other)
        elif row.side in (SIDE.BUSINESS, SIDE.SPLIT):
            business = row.amount_cents if row.side == SIDE.BUSINESS \
                else row.split_business_cents
            row.paid_line = PersonalLine.objects.create(
                amount_cents=business,
                category=services.system_category(ledger, services.FOR_THE_PRACTICE),
                **made)
            try:
                row.paid_entry = services.paid_personally(
                    tenant, actor=actor, line=row.paid_line, category=row.business_category)
            except books.FinanceError as exc:
                raise _refused(exc) from None
            row.paid_line.paid_entry = row.paid_entry
            row.paid_line.save(update_fields=["paid_entry", "updated_at"])
            if row.side == SIDE.SPLIT:
                row.line = PersonalLine.objects.create(
                    amount_cents=row.amount_cents - business, category=row.category, **made)
            else:
                row.line = row.paid_line
        else:
            row.line = PersonalLine.objects.create(
                amount_cents=row.amount_cents,
                category=None if row.side == SIDE.TO_SORT else row.category, **made)
        row.save(update_fields=["line", "paid_line", "paid_entry", "matched_category_before",
                                "updated_at"])
    batch.status, batch.committed_at = S.COMMITTED, timezone.now()
    batch.counts = counts(batch)
    batch.save()
    return batch


@transaction.atomic
def rollback(batch, *, actor) -> dict:
    """Undo a committed import: its lines leave the ledger, the practice's
    entries it made leave the books (one edited there since is kept, and
    named), and its transfers are unpaired. A line ticked on a finished
    statement holds it back until that statement is reopened."""
    batch = PersonalImport.objects.select_for_update().get(pk=batch.pk)
    if batch.status != S.COMMITTED:
        raise PersonalError("Only a committed import can be rolled back.", status=409)
    rows = list(PersonalImportRow.objects.filter(batch=batch).select_related(
        "line", "paid_line", "paid_entry", "matched_line", "matched_category_before"))
    made = [line for row in rows for line in (row.line, row.paid_line) if line is not None]
    if any(line.cleared_in_id and line.cleared_in.state == "finished" for line in made):
        raise PersonalError("Some of its lines are ticked on a finished statement. Reopen "
                            "that reconciliation first.", status=409)
    from apps.tenancy.models import AuditEvent

    entries = [row.paid_entry for row in rows if row.paid_entry is not None]
    edited = set(AuditEvent.all_objects.filter(
        verb="finance.entry_changed", target_type="finance_entry",
        target_id__in=[entry.pk for entry in entries],
        created_at__gt=batch.committed_at).values_list("target_id", flat=True))
    removed, kept = 0, []
    reason = f"Import of {batch.filename} rolled back."
    for entry in entries:
        if entry.removed_at is not None:
            continue
        if entry.pk in edited:
            kept.append({"on_date": entry.on_date.isoformat(),
                         "amount_cents": entry.amount_cents, "description": entry.description})
            continue
        try:
            books.remove_entry(entry, actor=actor, reason=reason)
        except books.FinanceError as exc:
            raise _refused(exc) from None
    for row in rows:
        if row.matched_line is not None and row.line is not None:
            services.unpair(row.line)
            other = row.matched_line
            other.refresh_from_db()
            other.category = row.matched_category_before
            other.save(update_fields=["category", "updated_at"])
    for line in made:
        line.refresh_from_db()
        if line.removed_at is None and not (line.paid_entry_id
                                            and line.paid_entry_id in edited):
            line.removed_at, line.remove_reason = timezone.now(), reason
            line.cleared_in = None
            line.save(update_fields=["removed_at", "remove_reason", "cleared_in",
                                     "updated_at"])
            removed += 1
    batch.status, batch.rolled_back_at = S.ROLLED_BACK, timezone.now()
    batch.save(update_fields=["status", "rolled_back_at", "updated_at"])
    return {"removed": removed, "kept": kept}


__all__ = ["parse", "dry_run", "decide", "commit", "rollback", "counts", "adds_up"]
