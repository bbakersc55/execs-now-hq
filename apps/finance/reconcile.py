"""Reconciling an account and closing a month
(`docs/p6_m1_reconciliation_month_close.md` §1–§4.1).

Reconciling is ticking off each line of the books that a statement also
shows, until the two agree to the cent. Closing a month locks the books
through its last day.

What this module keeps true:

- **The difference is arithmetic**, the same sum everywhere it is shown:
  statement balance − (starting balance + cleared money in − cleared money
  out). For a card the balance is what is owed, so money in takes away.
- **A reconciliation finishes only at a difference of exactly zero.**
- **An entry cleared in a finished reconciliation keeps its date, amount,
  account and direction** (`hold`, called by every write to an entry).
- **The lock is set here and nowhere else** for a practice that closes
  months: closing moves it forward, reopening moves it back.
- **Every write is audited.**
"""

from __future__ import annotations

from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.finance.models import (
    FinanceAccount, FinanceCleared, FinanceEntry, FinanceGuide, FinanceImportBatch,
    FinanceImportRow, FinanceMonthClose, FinanceReconciliation, FinanceSettings,
)
from apps.finance.services import FinanceError, _a_date, _cents, audit, settings_for

K = FinanceEntry.Kind
D = FinanceEntry.Direction
S = FinanceReconciliation.State
CARD = FinanceAccount.Kind.CARD

#: What stays as the statement showed it, once an entry is cleared (§1.5).
HELD = ("on_date", "amount_cents", "direction", "account_id", "to_account_id")


# -------------------------------------------------------------------- months

def month_start(day: date) -> date:
    return day.replace(day=1)


def next_month(day: date) -> date:
    return date(day.year + (day.month == 12), day.month % 12 + 1, 1)


def month_end(day: date) -> date:
    return next_month(day) - timedelta(days=1)


def month_name(day: date) -> str:
    return f"{day:%B} {day.year}"


def a_month(value) -> date:
    """`2026-09` (or a date in it) as the month's first day."""
    if isinstance(value, date):
        return month_start(value)
    text = str(value or "")
    try:
        return date.fromisoformat(text + "-01" if len(text) == 7 else text).replace(day=1)
    except ValueError:
        raise FinanceError("A month is written YYYY-MM.") from None


def _who(user) -> str:
    return (user.full_name or user.email) if user else ""


def _money(cents: int) -> str:
    return f"{'-' if cents < 0 else ''}${abs(cents) / 100:,.2f}"


def _long(day: date) -> str:
    return f"{day:%B} {day.day}, {day.year}"


# ------------------------------------------------------ one account's lines

def _way(entry, account) -> str:
    """Into the account, or out of it. A transfer leaves `account` and
    reaches `to_account`."""
    if entry.kind == K.TRANSFER:
        return D.OUT if entry.account_id == account.pk else D.IN
    return entry.direction


def _effect(way: str, cents: int, account) -> int:
    """What ticking it does to the balance the books expect. A card's balance
    is what is owed: a charge (out) adds to it and a payment (in) takes away."""
    up = (way == D.IN) != (account.kind == CARD)
    return cents if up else -cents


def began(account) -> date:
    """Entries before this are inside the starting balance, and never asked
    about."""
    return account.reconciling_from or account.opening_on


def _touching(account):
    return FinanceEntry.all_objects.filter(
        Q(account=account) | Q(to_account=account), tenant_id=account.tenant_id,
        removed_at__isnull=True)


def previous(rec):
    return (FinanceReconciliation.all_objects
            .filter(tenant_id=rec.tenant_id, account_id=rec.account_id,
                    statement_on__lt=rec.statement_on)
            .order_by("-statement_on").first())


def starting_balance(rec) -> int:
    """The statement before this one's ending balance; for an account's first,
    what was typed or the account's opening balance. Never stale: an open one
    follows the one before it."""
    before = previous(rec)
    if before is not None and rec.state == S.OPEN \
            and rec.starting_balance_cents != before.statement_balance_cents:
        rec.starting_balance_cents = before.statement_balance_cents
        rec.save(update_fields=["starting_balance_cents", "updated_at"])
    return rec.starting_balance_cents


def _candidates(rec):
    """Every entry this statement could show: in the account, dated on or
    before the statement date, and not cleared by an earlier statement."""
    earlier = FinanceCleared.all_objects.filter(
        tenant_id=rec.tenant_id, account_id=rec.account_id,
        reconciliation__statement_on__lt=rec.statement_on).values("entry_id")
    return (_touching(rec.account)
            .filter(on_date__lte=rec.statement_on, on_date__gte=began(rec.account))
            .exclude(pk__in=earlier))


def _cleared_ids(rec) -> set:
    return set(FinanceCleared.all_objects.filter(reconciliation=rec)
               .values_list("entry_id", flat=True))


def lines(rec) -> list[dict]:
    account = rec.account
    before = previous(rec)
    period_start = before.statement_on + timedelta(days=1) if before else began(account)
    cleared = _cleared_ids(rec)
    bank = from_the_bank(account)
    out = []
    for entry in _candidates(rec).order_by("on_date", "created_at"):
        out.append({
            "id": str(entry.pk), "on_date": entry.on_date.isoformat(),
            "amount_cents": entry.amount_cents, "way": _way(entry, account),
            "description": entry.description, "counterparty": entry.counterparty,
            "kind": entry.kind, "kind_label": entry.get_kind_display(),
            "cleared": entry.pk in cleared,
            # Left unticked by an earlier statement: "From earlier statements".
            "carried": entry.on_date < period_start,
            "from_bank": entry.pk in bank,
        })
    return out


def totals(rec, rows=None) -> dict:
    rows = lines(rec) if rows is None else rows
    start = starting_balance(rec)
    money_in = sum(r["amount_cents"] for r in rows if r["cleared"] and r["way"] == D.IN)
    money_out = sum(r["amount_cents"] for r in rows if r["cleared"] and r["way"] == D.OUT)
    expected = start + _effect(D.IN, money_in, rec.account) \
        + _effect(D.OUT, money_out, rec.account)
    return {"starting_balance_cents": start, "cleared_in_cents": money_in,
            "cleared_out_cents": money_out, "expected_cents": expected,
            "difference_cents": rec.statement_balance_cents - expected}


def hints(rec, rows, difference: int) -> list[dict]:
    """The four things a difference usually is (§1.4), each checked by
    arithmetic. No AI."""
    if difference == 0:
        return []
    account, found = rec.account, []
    for row in rows:
        effect = _effect(row["way"], row["amount_cents"], account)
        if not row["cleared"] and effect == difference:
            found.append({"kind": "untick", "entry": row["id"],
                          "text": "An unticked entry is for exactly the difference."})
            break
    for row in rows:
        effect = _effect(row["way"], row["amount_cents"], account)
        if row["cleared"] and -2 * effect == difference:
            found.append({"kind": "wrong_way", "entry": row["id"],
                          "text": "A ticked entry is for exactly half the difference. "
                                  "It may be entered the wrong way round: money in "
                                  "as money out, or the reverse."})
            break
    if difference % 9 == 0:
        found.append({"kind": "swapped", "entry": None,
                      "text": "The difference divides by 9, which is what two digits "
                              "swapped in an amount look like (54 typed as 45). Check "
                              "the amounts of the ticked entries against the statement."})
    found.append({"kind": "missing", "entry": None,
                  "text": "Something on the statement may not be in the books yet: a "
                          "fee, interest, a charge you did not enter. Add it here."})
    return found


# ------------------------------------------------- what came from the bank

def from_the_bank(account, batch=None) -> set:
    """The entries this account's own bank import showed: the lines it made,
    and the transfers and invoice payments it matched (M1-4)."""
    rows = FinanceImportRow.all_objects.filter(
        tenant_id=account.tenant_id, batch__account=account,
        batch__status=FinanceImportBatch.Status.COMMITTED)
    if batch is not None:
        rows = rows.filter(batch=batch)
    O = FinanceImportRow.Outcome
    found = set(rows.filter(outcome__in=(O.NEW, O.TRANSFER), entry__isnull=False)
                .values_list("entry_id", flat=True))
    found |= set(rows.filter(outcome=O.TRANSFER_MATCH, matched_entry__isnull=False)
                 .values_list("matched_entry_id", flat=True))
    payments = rows.filter(outcome=O.INVOICE_PAYMENT, matched_entry__isnull=False) \
        .values_list("matched_entry__client_payment_id", flat=True)
    # A deposit is one line at the bank and two in the books: fee and tax.
    found |= set(FinanceEntry.all_objects.filter(
        tenant_id=account.tenant_id, account=account, removed_at__isnull=True,
        client_payment_id__in=[p for p in payments if p]).values_list("pk", flat=True))
    return found


def _tick(rec, entries) -> int:
    made = 0
    for entry in entries:
        _, new = FinanceCleared.all_objects.get_or_create(
            tenant_id=rec.tenant_id, entry=entry, account_id=rec.account_id,
            defaults={"reconciliation": rec})
        made += new
    return made


def _arrive_ticked(rec, *, only=None, after=None) -> int:
    """Lines the bank's own file brought in arrive ticked. Done once, when a
    statement is started or a file is committed, so unticking one stays."""
    bank = from_the_bank(rec.account) if only is None else only
    entries = _candidates(rec).filter(pk__in=bank).exclude(pk__in=_cleared_ids(rec))
    if after is not None:
        entries = entries.filter(on_date__gt=after)
    return _tick(rec, entries)


def imported(batch) -> None:
    """A committed import: its lines arrive ticked in the statement being
    worked on, where there is one."""
    rec = FinanceReconciliation.all_objects.filter(
        tenant_id=batch.tenant_id, account_id=batch.account_id, state=S.OPEN).first()
    if rec is not None:
        _arrive_ticked(rec, only=from_the_bank(batch.account, batch))


# ------------------------------------------------------- start, tick, finish

def _locked(rec) -> None:
    rec.refresh_from_db()
    if rec.state != S.OPEN:
        raise FinanceError(f"The {month_name(rec.month)} reconciliation of "
                           f"{rec.account.name} is finished. Reopen it to change it.",
                           status=409)


@transaction.atomic
def start(tenant, *, actor, account, statement_on, statement_balance_cents,
          starting_balance_cents=None, starting_on=None) -> FinanceReconciliation:
    account = FinanceAccount.all_objects.select_for_update().get(pk=account.pk)
    if account.tenant_id != tenant.pk:
        raise FinanceError("That account is not in this practice.", status=404)
    statement_on = _a_date(statement_on, "The statement date")
    balance = _cents(statement_balance_cents, "The statement balance", signed=True)
    if statement_on > timezone.localdate():
        raise FinanceError("A statement cannot end in the future.")
    month = month_start(statement_on)
    mine = FinanceReconciliation.all_objects.filter(tenant=tenant, account=account)
    if mine.filter(month=month).exists():
        raise FinanceError(f"{account.name} already has a reconciliation for "
                           f"{month_name(month)}.", status=409)
    waiting = mine.filter(state=S.OPEN).first()
    if waiting is not None:
        raise FinanceError(f"Finish the {month_name(waiting.month)} reconciliation of "
                           f"{account.name} first.", status=409)
    newest = mine.order_by("-statement_on").first()
    if newest is not None:
        due = next_month(newest.month)
        if month != due:
            raise FinanceError(f"{account.name} is reconciled through "
                               f"{month_name(newest.month)}. {month_name(due)} is next.",
                               status=409)
        starting = newest.statement_balance_cents
    elif starting_balance_cents is not None:
        # Reconciling begins later than the account did (M1-3): this
        # statement's own starting balance, and nothing before it is asked for.
        starting = _cents(starting_balance_cents, "The starting balance", signed=True)
        starting_on = _a_date(starting_on, "The statement's first day") if starting_on \
            else month
        if starting_on > statement_on or starting_on < account.opening_on:
            raise FinanceError("The statement's first day is on or after the account's "
                               "opening date, and before its ending date.")
        account.reconciling_from = starting_on
        account.save(update_fields=["reconciling_from", "updated_at"])
    else:
        starting = account.opening_balance_cents
    if statement_on < began(account):
        raise FinanceError(f"{account.name} starts on {_long(began(account))}. A "
                           "statement ends on or after that.")
    rec = FinanceReconciliation.all_objects.create(
        tenant=tenant, account=account, month=month, statement_on=statement_on,
        statement_balance_cents=balance, starting_balance_cents=starting)
    _arrive_ticked(rec)
    audit(tenant, "reconciliation_started", actor, rec, account=account.name,
          month=month.isoformat(), statement_on=statement_on.isoformat(),
          statement_balance_cents=balance, starting_balance_cents=starting)
    return rec


@transaction.atomic
def update(rec, *, actor, statement_on=None, statement_balance_cents=None):
    _locked(rec)
    was = rec.statement_on
    if statement_on is not None:
        day = _a_date(statement_on, "The statement date")
        if month_start(day) != rec.month:
            raise FinanceError(f"This is the {month_name(rec.month)} reconciliation, so "
                               "its statement ends in that month. Discard it to "
                               "reconcile another month.")
        if day > timezone.localdate():
            raise FinanceError("A statement cannot end in the future.")
        if day < began(rec.account):
            raise FinanceError(f"{rec.account.name} starts on "
                               f"{_long(began(rec.account))}.")
        rec.statement_on = day
    if statement_balance_cents is not None:
        rec.statement_balance_cents = _cents(statement_balance_cents,
                                             "The statement balance", signed=True)
    rec.save()
    if rec.statement_on < was:
        FinanceCleared.all_objects.filter(reconciliation=rec,
                                          entry__on_date__gt=rec.statement_on).delete()
    elif rec.statement_on > was:
        _arrive_ticked(rec, after=was)
    audit(rec.tenant, "reconciliation_changed", actor, rec,
          statement_on=rec.statement_on.isoformat(),
          statement_balance_cents=rec.statement_balance_cents)
    return rec


@transaction.atomic
def tick(rec, *, actor, entry_ids=None, everything=False, cleared=True) -> int:
    """Tick or untick entries. All or nothing: one that this statement could
    not show refuses the lot."""
    _locked(rec)
    if everything:
        entries = list(_candidates(rec))
    else:
        if not isinstance(entry_ids, list) or not entry_ids:
            raise FinanceError("entries is a list of entries.")
        try:
            entries = list(_candidates(rec).filter(pk__in=entry_ids))
        except (ValueError, TypeError, ValidationError):
            raise FinanceError("entries is a list of entries.") from None
        if len(entries) != len({str(pk) for pk in entry_ids}):
            raise FinanceError("One of those entries is not in this account on or before "
                               "the statement date, or an earlier statement cleared it.",
                               status=404)
    if cleared:
        count = _tick(rec, entries)
    else:
        count, _ = FinanceCleared.all_objects.filter(
            reconciliation=rec, entry__in=entries).delete()
    if len(entries) > 1 and count:
        # Several at once is recorded, as any bulk change to the books is.
        audit(rec.tenant, "reconciliation_ticked" if cleared
              else "reconciliation_unticked", actor, rec, account=rec.account.name,
              month=rec.month.isoformat()[:7], count=count, asked=len(entries),
              everything=bool(everything))
    return count


@transaction.atomic
def finish(rec, *, actor) -> FinanceReconciliation:
    _locked(rec)
    before = previous(rec)
    if before is not None and before.state != S.FINISHED:
        raise FinanceError(f"Finish the {month_name(before.month)} reconciliation of "
                           f"{rec.account.name} first: this one starts from its ending "
                           "balance.", status=409)
    result = totals(rec)
    if result["difference_cents"] != 0:
        raise FinanceError(f"The difference is {_money(result['difference_cents'])}. A "
                           "reconciliation is finished when it is exactly zero.",
                           status=409)
    rec.state, rec.finished_by, rec.finished_at = S.FINISHED, actor, timezone.now()
    rec.save()
    audit(rec.tenant, "reconciliation_finished", actor, rec, account=rec.account.name,
          month=rec.month.isoformat(), statement_on=rec.statement_on.isoformat(),
          statement_balance_cents=rec.statement_balance_cents,
          cleared_in_cents=result["cleared_in_cents"],
          cleared_out_cents=result["cleared_out_cents"])
    return rec


def can_reopen(rec) -> str:
    """Why this finished reconciliation cannot be reopened, or ""."""
    if rec.state != S.FINISHED:
        return "It is not finished."
    if FinanceReconciliation.all_objects.filter(
            tenant_id=rec.tenant_id, account_id=rec.account_id, state=S.FINISHED,
            statement_on__gt=rec.statement_on).exists():
        return ("Only the newest finished reconciliation of an account can be reopened, "
                "so the starting balances after it stay true.")
    locked = settings_for(rec.tenant).locked_through
    if locked is not None and rec.statement_on <= locked:
        return f"{month_name(rec.month)} is closed. Reopen the month first."
    return ""


@transaction.atomic
def reopen(rec, *, actor, reason) -> FinanceReconciliation:
    reason = str(reason or "").strip()
    if not reason:
        raise FinanceError("Say why the reconciliation is being reopened.")
    rec = FinanceReconciliation.all_objects.select_for_update().get(pk=rec.pk)
    refused = can_reopen(rec)
    if refused:
        raise FinanceError(refused, status=409)
    rec.state, rec.finished_by, rec.finished_at = S.OPEN, None, None
    rec.reopened_by, rec.reopened_at, rec.reopen_reason = actor, timezone.now(), reason
    rec.save()
    audit(rec.tenant, "reconciliation_reopened", actor, rec, account=rec.account.name,
          month=rec.month.isoformat(), reason=reason)
    return rec


@transaction.atomic
def discard(rec, *, actor) -> None:
    """Throw away one that was started and never finished."""
    _locked(rec)
    if rec.reopened_at is not None:
        raise FinanceError("This reconciliation was finished once, so it is kept. "
                           "Finish it again instead.", status=409)
    account = rec.account
    audit(rec.tenant, "reconciliation_discarded", actor, rec, account=account.name,
          month=rec.month.isoformat())
    rec.delete()
    if account.reconciling_from is not None and not FinanceReconciliation.all_objects \
            .filter(tenant_id=account.tenant_id, account=account).exists():
        account.reconciling_from = None
        account.save(update_fields=["reconciling_from", "updated_at"])


# ------------------------------------------------ what a cleared entry keeps

def _finished_clearing(entry):
    return (FinanceCleared.all_objects.select_related("reconciliation__account")
            .filter(entry=entry, reconciliation__state=S.FINISHED).first())


def snapshot(entry) -> tuple:
    return tuple(getattr(entry, name) for name in HELD)


def hold(entry, before=None, *, removing=False) -> None:
    """Called by every write to an entry (§1.5). One cleared in a finished
    reconciliation keeps its date, amount, account and direction, and is not
    removed. One ticked in a reconciliation still open is simply unticked
    where the change takes it out of that statement."""
    if entry.pk is None:
        return
    changed = removing or (before is not None and before != snapshot(entry))
    if not changed:
        return
    cleared = _finished_clearing(entry)
    if cleared is not None:
        rec = cleared.reconciliation
        raise FinanceError(
            f"This entry was ticked off in the {month_name(rec.month)} reconciliation of "
            f"{rec.account.name}. Its date, amount, account and direction stay as the "
            "statement showed them, and it cannot be removed. Reopen that reconciliation "
            "first.", status=409)
    stale = FinanceCleared.all_objects.filter(entry=entry)
    if not removing:
        stale = stale.exclude(
            Q(account_id__in=[pk for pk in (entry.account_id, entry.to_account_id) if pk])
            & Q(reconciliation__statement_on__gte=entry.on_date))
    stale.delete()


# ------------------------------------------------------------- representing

def unplaced(rec) -> list[dict]:
    """Invoice payments received and not yet placed in an account (§1.4):
    they cannot be ticked until they are."""
    if rec.account.kind == CARD:
        return []
    loose = FinanceEntry.all_objects.filter(
        tenant_id=rec.tenant_id, removed_at__isnull=True, account__isnull=True,
        source=FinanceEntry.Source.INVOICE, on_date__lte=rec.statement_on).order_by("on_date")
    return [{"id": str(entry.pk), "on_date": entry.on_date.isoformat(),
             "amount_cents": entry.amount_cents, "description": entry.description,
             "counterparty": entry.counterparty} for entry in loose]


def statements(tenant) -> dict:
    """`{(account id, month): [the PDF statements imported for it]}` (owner,
    2026-10-14): a statement read from a PDF is kept with its import, and is
    shown here for its month, since it is what the month is reconciled to."""
    from apps.finance.models import FinanceImportBatch

    out: dict = {}
    for batch in (FinanceImportBatch.all_objects.filter(
            tenant=tenant, statement_file__isnull=False,
            status=FinanceImportBatch.Status.COMMITTED).order_by("committed_at")):
        ended = batch.period_end or batch.last_balance_on
        if ended is None:
            continue
        out.setdefault((batch.account_id, month_start(ended)), []).append({
            "id": str(batch.pk), "filename": batch.filename,
            "pdf": f"/api/finance-imports/{batch.pk}/statement/",
            "period_start": batch.period_start.isoformat() if batch.period_start else None,
            "period_end": ended.isoformat(),
            "closing_balance_cents": batch.last_balance_cents})
    return out


def represent(rec, *, detail=False) -> dict:
    account = rec.account
    out = {
        "id": str(rec.pk),
        "account": {"id": str(account.pk), "name": account.name, "kind": account.kind,
                    "kind_label": account.get_kind_display()},
        "month": rec.month.isoformat()[:7], "month_label": month_name(rec.month),
        "statement_on": rec.statement_on.isoformat(),
        "statement_balance_cents": rec.statement_balance_cents,
        "state": rec.state, "state_label": rec.get_state_display(),
        "finished_at": rec.finished_at.isoformat() if rec.finished_at else None,
        "finished_by": _who(rec.finished_by),
        "reopened_at": rec.reopened_at.isoformat() if rec.reopened_at else None,
        "reopened_by": _who(rec.reopened_by), "reopen_reason": rec.reopen_reason,
    }
    if not detail:
        return out
    rows = lines(rec)
    sums = totals(rec, rows)
    before = previous(rec)
    out.update({
        **sums, "lines": rows,
        "statements": statements(rec.tenant).get((account.pk, rec.month), []),
        "first": before is None,
        "period_start": (before.statement_on + timedelta(days=1) if before
                         else began(account)).isoformat(),
        "hints": hints(rec, rows, sums["difference_cents"]) if rec.state == S.OPEN else [],
        "unplaced": unplaced(rec) if rec.state == S.OPEN else [],
        "cannot_reopen": can_reopen(rec) if rec.state == S.FINISHED else "",
        "can_discard": rec.state == S.OPEN and rec.reopened_at is None,
    })
    return out


# --------------------------------------------------------------- the months

def standing(tenant) -> dict:
    """`{month: its close}` for every month closed and not reopened."""
    return {row.month: row for row in FinanceMonthClose.all_objects.filter(
        tenant=tenant, reopened_at__isnull=True).select_related("closed_by")}


def state_of(month: date, closes: dict, locked) -> str:
    if month in closes:
        return "closed"
    if locked is not None and month_end(month) <= locked:
        # A lock typed before month close existed, or the months before the
        # first one closed (M1-9): locked, not reconciled, not "closed".
        return "locked_before"
    return "open"


def first_month(tenant) -> date:
    today = timezone.localdate()
    earliest = [month_start(today)]
    entry = FinanceEntry.all_objects.filter(tenant=tenant, removed_at__isnull=True) \
        .order_by("on_date").values_list("on_date", flat=True).first()
    if entry:
        earliest.append(month_start(entry))
    rec = FinanceReconciliation.all_objects.filter(tenant=tenant).order_by("month") \
        .values_list("month", flat=True).first()
    if rec:
        earliest.append(rec)
    return min(earliest)


def months_through(first: date, last: date) -> list[date]:
    out, day = [], month_start(first)
    while day <= last:
        out.append(day)
        day = next_month(day)
    return out


def next_to_close(tenant, locked=...) -> date | None:
    """Months close in order (§3.3): the one after the lock. With no lock
    yet, the first month that has a reconciliation, since reconciling may
    begin at any month (M1-3)."""
    if locked is ...:
        locked = settings_for(tenant).locked_through
    if locked is not None:
        return month_start(locked + timedelta(days=1))
    return FinanceReconciliation.all_objects.filter(tenant=tenant).order_by("month") \
        .values_list("month", flat=True).first()


def _needs_reconciling(tenant, month: date):
    """The accounts the close asks about: switched to "reconciled each
    month", begun on or before the month's last day, and not closed (unless
    money still moved through them in the month)."""
    last = month_end(month)
    for account in FinanceAccount.all_objects.filter(
            tenant=tenant, reconciled_monthly=True).order_by("kind", "name"):
        if account.opening_on > last:
            continue
        if account.closed_at is not None and not _touching(account).filter(
                on_date__gte=month, on_date__lte=last).exists():
            continue
        yield account


def checklist(tenant, month: date) -> list[dict]:
    """The four lines of §3.2, each ticked from the books as they are now."""
    last = month_end(month)
    live = FinanceEntry.all_objects.filter(
        tenant=tenant, removed_at__isnull=True, on_date__gte=month, on_date__lte=last)
    done = set(FinanceReconciliation.all_objects.filter(
        tenant=tenant, month=month, state=S.FINISHED).values_list("account_id", flat=True))
    waiting = [a.name for a in _needs_reconciling(tenant, month) if a.pk not in done]
    bare = live.filter(kind__in=FinanceEntry.EARNED, category__isnull=True).count()
    loose = live.filter(account__isnull=True, source=FinanceEntry.Source.INVOICE).count()
    unnamed = live.filter(kind=K.EXPENSE, payee_contact__isnull=True).filter(
        Q(category__is_contractor=True) | Q(category__parent__is_contractor=True)).count()
    span = f"from={month.isoformat()}&to={last.isoformat()}"
    return [
        {"code": "reconciled", "label": "Every account reconciled", "blocks": True,
         "ok": not waiting, "count": len(waiting),
         "detail": ("Still to reconcile: " + ", ".join(waiting) + ".") if waiting else "",
         "link": "/finance/reconcile"},
        {"code": "categorized", "label": "Nothing uncategorized", "blocks": True,
         "ok": bare == 0, "count": bare,
         "detail": f"{bare} without a category." if bare else "",
         "link": f"/finance?category=none&{span}"},
        {"code": "placed", "label": "Invoice payments placed", "blocks": True,
         "ok": loose == 0, "count": loose,
         "detail": f"{loose} received and not yet placed in an account." if loose else "",
         "link": f"/finance?account=none&{span}"},
        {"code": "payees", "label": "1099 payees named", "blocks": False,
         "ok": unnamed == 0, "count": unnamed,
         "detail": (f"{unnamed} paid to contractors with nobody named. This is a warning: "
                    "the month can close with it showing.") if unnamed else "",
         "link": "/finance/1099"},
    ]


def cannot_close(tenant, month: date, lines_=None) -> str:
    """Why this month cannot be closed now, or ""."""
    locked = settings_for(tenant).locked_through
    if state_of(month, standing(tenant), locked) != "open":
        return f"{month_name(month)} is already closed."
    if month_end(month) >= timezone.localdate():
        return f"{month_name(month)} can be closed after its last day."
    due = next_to_close(tenant, locked)
    if locked is not None and month != due:
        return f"Months close in order. {month_name(due)} is next."
    blocked = [line["label"] for line in (lines_ or checklist(tenant, month))
               if line["blocks"] and not line["ok"]]
    if blocked:
        return "Still on the checklist: " + "; ".join(blocked).lower() + "."
    return ""


@transaction.atomic
def close(tenant, *, actor, month: date) -> FinanceMonthClose:
    config = FinanceSettings.all_objects.select_for_update().get(pk=settings_for(tenant).pk)
    lines_ = checklist(tenant, month)
    refused = cannot_close(tenant, month, lines_)
    if refused:
        raise FinanceError(refused, status=409)
    warnings = [{"code": line["code"], "label": line["label"], "count": line["count"]}
                for line in lines_ if not line["ok"]]
    row = FinanceMonthClose.all_objects.create(
        tenant=tenant, month=month, closed_by=actor, closed_at=timezone.now(),
        warnings=warnings)
    was = config.locked_through
    config.locked_through = month_end(month)
    config.save(update_fields=["locked_through", "updated_at"])
    audit(tenant, "month_closed", actor, row, month=month.isoformat()[:7],
          locked_through=config.locked_through.isoformat(),
          locked_before=was.isoformat() if was else None, warnings=warnings)
    # P6 M2 §4: what happened is set beside what was forecast for the month.
    from apps.finance import forecast

    forecast.month_closed(tenant, month)
    return row


def reopen_plan(tenant, month: date) -> dict:
    locked = settings_for(tenant).locked_through
    if locked is None or month > locked:
        raise FinanceError(f"{month_name(month)} is not closed.", status=409)
    later = [m for m in sorted(standing(tenant)) if m > month]
    return {"month": month.isoformat()[:7], "label": month_name(month),
            "also": [month_name(m) for m in later],
            "locked_through_after": (month - timedelta(days=1)).isoformat(),
            "note": REOPEN_NOTE}


#: What the reopen screen says first (§3.4).
REOPEN_NOTE = ("If a later statement showed a mistake in this month, add a correcting "
               "entry in the open month instead. Reopen only if the month should not have "
               "been closed.")


@transaction.atomic
def reopen_month(tenant, *, actor, month: date, reason) -> dict:
    """Move the lock back to the end of the month before. Every later closed
    month reopens with it (M1-7); their reconciliations stay finished."""
    reason = str(reason or "").strip()
    if not reason:
        raise FinanceError("Say why the month is being reopened.")
    config = FinanceSettings.all_objects.select_for_update().get(pk=settings_for(tenant).pk)
    plan = reopen_plan(tenant, month)
    now = timezone.now()
    rows = FinanceMonthClose.all_objects.filter(
        tenant=tenant, reopened_at__isnull=True, month__gte=month)
    reopened = [row.month.isoformat()[:7] for row in rows.order_by("month")]
    rows.update(reopened_by=actor, reopened_at=now, reopen_reason=reason, updated_at=now)
    was = config.locked_through
    back = month - timedelta(days=1)
    # Nothing left to keep locked: no month before it is closed or holds an entry.
    if not FinanceEntry.all_objects.filter(tenant=tenant, on_date__lte=back).exists() \
            and not FinanceMonthClose.all_objects.filter(
                tenant=tenant, reopened_at__isnull=True).exists():
        back = None
    config.locked_through = back
    config.save(update_fields=["locked_through", "updated_at"])
    audit(tenant, "month_reopened", actor, config, month=month.isoformat()[:7],
          reason=reason, months=reopened, locked_before=was.isoformat(),
          locked_through=back.isoformat() if back else None)
    return {**plan, "reopened": reopened}


def _close_row(row) -> dict:
    return {"closed_at": row.closed_at.isoformat(), "closed_by": _who(row.closed_by),
            "warnings": row.warnings,
            "reopened_at": row.reopened_at.isoformat() if row.reopened_at else None,
            "reopened_by": _who(row.reopened_by), "reopen_reason": row.reopen_reason}


def month_detail(tenant, month: date) -> dict:
    closes, locked = standing(tenant), settings_for(tenant).locked_through
    lines_ = checklist(tenant, month)
    history = FinanceMonthClose.all_objects.filter(tenant=tenant, month=month) \
        .select_related("closed_by", "reopened_by").order_by("closed_at")
    state = state_of(month, closes, locked)
    return {"month": month.isoformat()[:7], "label": month_name(month), "state": state,
            "checklist": lines_,
            "cannot_close": cannot_close(tenant, month, lines_) if state == "open" else "",
            "history": [_close_row(row) for row in history],
            "reopen_note": REOPEN_NOTE}


# ----------------------------------------------------------------- the grid

def grid(tenant, user) -> dict:
    """Accounts down and months across (§2), from the first month with
    entries; and the months themselves, closed or open."""
    today = timezone.localdate()
    closes, locked = standing(tenant), settings_for(tenant).locked_through
    months = months_through(first_month(tenant), month_start(today))
    recs: dict = {}
    for rec in FinanceReconciliation.all_objects.filter(tenant=tenant) \
            .select_related("account", "finished_by"):
        recs[(rec.account_id, rec.month)] = rec
    accounts = []
    kept = statements(tenant)
    for account in FinanceAccount.all_objects.filter(tenant=tenant).order_by("kind", "name"):
        mine = {month: rec for (pk, month), rec in recs.items() if pk == account.pk}
        if account.closed_at is not None and not mine:
            continue
        cells = {}
        for month in months:
            rec = mine.get(month)
            if rec is not None:
                cell = {"state": rec.state, "id": str(rec.pk),
                        "statement_on": rec.statement_on.isoformat(),
                        "finished_at": rec.finished_at.isoformat() if rec.finished_at
                        else None}
                if rec.state == S.OPEN:
                    cell["difference_cents"] = totals(rec)["difference_cents"]
            elif month_end(month) < began(account):
                cell = {"state": "before"}
            elif not account.reconciled_monthly:
                cell = {"state": "not_needed"}
            else:
                cell = {"state": "not_started"}
            cells[month.isoformat()[:7]] = cell
        newest = max(mine) if mine else None
        accounts.append({
            "id": str(account.pk), "name": account.name, "kind": account.kind,
            "kind_label": account.get_kind_display(), "last4": account.last4,
            "reconciled_monthly": account.reconciled_monthly,
            "opening_on": account.opening_on.isoformat(),
            "opening_balance_cents": account.opening_balance_cents,
            # What starting a reconciliation here would be: the next month, or
            # any month for an account's first.
            "next_month": next_month(newest).isoformat()[:7] if newest else None,
            # The PDF statements imported for each month: the statement itself.
            "statements": {month.isoformat()[:7]: found
                           for (pk, month), found in kept.items() if pk == account.pk},
            "cells": cells})
    due = next_to_close(tenant, locked)
    setter = closes.get(month_start(locked)) if locked is not None else None
    return {
        "months": [{"month": m.isoformat()[:7], "label": month_name(m),
                    "state": state_of(m, closes, locked),
                    "closed_at": closes[m].closed_at.isoformat() if m in closes else None,
                    "closed_by": _who(closes[m].closed_by) if m in closes else ""}
                   for m in months],
        "accounts": accounts,
        "locked_through": locked.isoformat() if locked else None,
        # Which close set the lock; none when it was typed before closing existed.
        "locked_by": ({"month": month_name(setter.month), "by": _who(setter.closed_by),
                       "at": setter.closed_at.isoformat()} if setter else None),
        "next_to_close": due.isoformat()[:7] if due and due <= months[-1] else None,
        "guided": guided(tenant, user),
        "today": today.isoformat(),
    }


# ---------------------------------------------------------- guided mode

def guided(tenant, user) -> bool:
    """"Walk me through it" (§4.1): the person's own choice once they have
    made one; until then, on until they have closed a month."""
    row = FinanceGuide.all_objects.filter(tenant=tenant, user=user).first()
    if row is not None:
        return row.guided
    return not FinanceMonthClose.all_objects.filter(tenant=tenant, closed_by=user).exists()


def set_guided(tenant, user, on: bool) -> bool:
    FinanceGuide.all_objects.update_or_create(tenant=tenant, user=user,
                                              defaults={"guided": bool(on)})
    return bool(on)
