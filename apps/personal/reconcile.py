"""Reconciling a personal account (P6 M4 decision 8): optional, and no month
close on the personal side.

The books' way, simpler: a statement's ending date and balance; tick each
line the statement shows until the difference is zero; finish. A finished
statement's ticks are fixed until it is reopened. Nothing is locked by it,
and nothing asks for it: it is there to keep a balance honest for the
forecast. A Mixed account is reconciled once, in the books, with the
business month.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.personal.models import PersonalAccount, PersonalLine, PersonalReconciliation
from apps.personal.services import PersonalError

R = PersonalReconciliation.State


def balance(account, as_of=None) -> int:
    """What the account holds (for a card, what is owed), from its opening
    balance and its lines."""
    lines = PersonalLine.objects.filter(account=account, removed_at__isnull=True,
                                        on_date__gte=account.opening_on)
    if as_of is not None:
        lines = lines.filter(on_date__lte=as_of)
    sums = lines.aggregate(i=Sum("amount_cents", filter=Q(direction="in")),
                           o=Sum("amount_cents", filter=Q(direction="out")))
    flow = (sums["i"] or 0) - (sums["o"] or 0)
    if account.kind == PersonalAccount.Kind.CARD:
        return account.opening_balance_cents - flow
    return account.opening_balance_cents + flow


def _last_finished(account, *, before=None):
    rows = PersonalReconciliation.objects.filter(account=account, state=R.FINISHED)
    if before is not None:
        rows = rows.exclude(pk=before.pk).filter(statement_on__lte=before.statement_on)
    return rows.order_by("-statement_on", "-created_at").first()


@transaction.atomic
def start(account, *, statement_on, statement_balance_cents) -> PersonalReconciliation:
    if account.closed_at is not None:
        raise PersonalError(f"“{account.name}” is closed.")
    if PersonalReconciliation.objects.filter(account=account, state=R.OPEN).exists():
        raise PersonalError("This account has a statement in progress. Finish it first.",
                            status=409)
    last = _last_finished(account)
    if last is not None and statement_on <= last.statement_on:
        raise PersonalError(f"The last statement finished ends {last.statement_on:%B} "
                            f"{last.statement_on.day}. This one ends after it.")
    if statement_on < account.opening_on:
        raise PersonalError("That is before the account's opening date.")
    return PersonalReconciliation.objects.create(
        ledger=account.ledger, account=account, statement_on=statement_on,
        statement_balance_cents=statement_balance_cents,
        starting_balance_cents=last.statement_balance_cents if last
        else account.opening_balance_cents)


def lines(rec) -> list[PersonalLine]:
    """Every line it could tick: the account's, to the statement's date, not
    ticked on another statement."""
    return list(PersonalLine.objects.filter(
        account=rec.account, removed_at__isnull=True, on_date__gte=rec.account.opening_on,
        on_date__lte=rec.statement_on).filter(
            Q(cleared_in__isnull=True) | Q(cleared_in=rec))
        .order_by("on_date", "created_at"))


def totals(rec, rows=None) -> dict:
    rows = lines(rec) if rows is None else rows
    cleared = [line for line in rows if line.cleared_in_id == rec.pk]
    money_in = sum(line.amount_cents for line in cleared if line.direction == "in")
    money_out = sum(line.amount_cents for line in cleared if line.direction == "out")
    flow = money_in - money_out
    if rec.account.kind == PersonalAccount.Kind.CARD:
        flow = -flow
    return {"starting_balance_cents": rec.starting_balance_cents,
            "cleared_in_cents": money_in, "cleared_out_cents": money_out,
            "difference_cents": rec.statement_balance_cents
            - (rec.starting_balance_cents + flow)}


@transaction.atomic
def tick(rec, *, line_ids, cleared: bool) -> None:
    rec = PersonalReconciliation.objects.select_for_update().get(pk=rec.pk)
    if rec.state != R.OPEN:
        raise PersonalError("That statement is finished. Reopen it to change its ticks.",
                            status=409)
    allowed = {line.pk for line in lines(rec)}
    wanted = set(line_ids)
    if not wanted or not {str(pk) for pk in allowed} >= {str(pk) for pk in wanted}:
        raise PersonalError("One of those lines is not on this statement.", status=404)
    PersonalLine.objects.filter(pk__in=wanted).update(
        cleared_in=rec if cleared else None, updated_at=timezone.now())


@transaction.atomic
def finish(rec) -> PersonalReconciliation:
    rec = PersonalReconciliation.objects.select_for_update().get(pk=rec.pk)
    if rec.state != R.OPEN:
        raise PersonalError("That statement is already finished.", status=409)
    left = totals(rec)["difference_cents"]
    if left:
        raise PersonalError(f"The difference is ${abs(left) / 100:,.2f}. It is zero when "
                            "every line the statement shows is ticked.", status=409)
    rec.state, rec.finished_at = R.FINISHED, timezone.now()
    rec.save(update_fields=["state", "finished_at", "updated_at"])
    return rec


@transaction.atomic
def reopen(rec) -> PersonalReconciliation:
    rec = PersonalReconciliation.objects.select_for_update().get(pk=rec.pk)
    if rec.state != R.FINISHED:
        raise PersonalError("That statement is not finished.", status=409)
    if PersonalReconciliation.objects.filter(account=rec.account,
                                             statement_on__gt=rec.statement_on).exists():
        raise PersonalError("A later statement of this account is in. Reopen that one "
                            "first.", status=409)
    if PersonalReconciliation.objects.filter(account=rec.account, state=R.OPEN).exists():
        raise PersonalError("This account has a statement in progress.", status=409)
    rec.state, rec.reopened_at = R.OPEN, timezone.now()
    rec.save(update_fields=["state", "reopened_at", "updated_at"])
    return rec


@transaction.atomic
def discard(rec) -> None:
    """A statement in progress, thrown away: its ticks come off. A finished
    one is reopened, never discarded."""
    rec = PersonalReconciliation.objects.select_for_update().get(pk=rec.pk)
    if rec.state != R.OPEN:
        raise PersonalError("A finished statement is reopened, not thrown away.",
                            status=409)
    PersonalLine.objects.filter(cleared_in=rec).update(cleared_in=None,
                                                       updated_at=timezone.now())
    rec.delete()
