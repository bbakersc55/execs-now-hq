"""What a sync does on the **personal** side (`docs/p6_bank_feeds.md`,
"Personal finance").

A personal connection's accounts feed the owner's own ledger (P6 M4), never
the practice's books: nothing here makes, changes or removes a `FinanceEntry`,
and none of the practice's rules is read, so a split or a personal rule (or a
business one) never reaches these lines. Each transaction becomes a line of
the household account it is mapped to, decided as a statement's line with no
rule is (`apps.personal.imports`):

- a line already in the account (typed or imported) is not entered twice;
- the other side of a move between the household's own accounts is paired
  with it (decision 7);
- money in that is an owner draw from the practice is pay (decision 20; the
  draw is read, never written);
- otherwise, under the owner's threshold, Everything else; at or over it,
  To sort (decision 5).

**Pending** transactions make no line until they post (the ledger has no
pending lines). A line ticked on a finished statement is left as it is when
the bank changes or removes it, with a notice, as a closed month's entry is
on the practice's side.
"""

from __future__ import annotations

from django.utils import timezone

from apps.finance.models import BankConnection, BankFeedAccount, BankFeedTransaction

O = BankFeedTransaction.Outcome
#: The outcomes that made a line of their own.
MADE = (O.NEW, O.TRANSFER)
REMOVED_REASON = "The bank removed this transaction (bank feed)."


def is_personal(connection) -> bool:
    return connection.side == BankConnection.Side.PERSONAL


class PersonalPass:
    def __init__(self, connection, actor):
        from apps.personal.models import PersonalLine

        self.connection, self.actor = connection, actor
        self.tenant, self.ledger = connection.tenant, connection.ledger
        self.feeds = {f.provider_account_id: f for f in BankFeedAccount.all_objects.filter(
            connection=connection).select_related("personal_account")}
        self.known: dict = {}
        self.draws: set = set()
        self.made_any = False
        self.Line = PersonalLine
        self.counts = {"added": 0, "modified": 0, "removed": 0, "matched": 0,
                       "skipped": 0, "closed_month": 0, "pending": 0}

    # ----------------------------------------------------------- helpers

    def _row(self, transaction_id):
        return (BankFeedTransaction.all_objects
                .filter(feed_account__connection=self.connection,
                        provider_transaction_id=transaction_id)
                .select_related("personal_line__cleared_in",
                                "feed_account__personal_account").first())

    def _known(self, account):
        from apps.personal import imports

        if account.pk not in self.known:
            self.known[account.pk] = imports._Ledger(self.ledger, account, for_feed=True)
        return self.known[account.pk]

    def _notice(self, row, title, text):
        from . import connections

        connections.tell_owner(self.tenant, title=title, text=text,
                               source_type="bank.line", source_id=row.pk,
                               only=self.ledger.owner_id, url="/finance/personal/entries")

    @staticmethod
    def _finished(line) -> bool:
        return line.cleared_in_id is not None and line.cleared_in.state == "finished"

    # ------------------------------------------------------------- added

    def added(self, t) -> None:
        feed = self.feeds.get(t.provider_account_id)
        if feed is None or feed.personal_account_id is None:
            self.counts["skipped"] += 1               # an account not fed
            return
        row = self._row(t.provider_transaction_id)
        if row is None and t.pending_transaction_id:
            row = self._row(t.pending_transaction_id)
            if row is not None:
                row.provider_transaction_id = t.provider_transaction_id
        if row is not None:
            self._change(row, t)
            return
        row = BankFeedTransaction(
            tenant_id=self.tenant.pk, feed_account=feed,
            provider_transaction_id=t.provider_transaction_id, on_date=t.on_date,
            amount_cents=t.amount_cents, direction=t.direction,
            description=t.description[:255], bank_category=t.bank_category[:120],
            pending=t.pending)
        self._decide(row, feed.personal_account)
        row.save()

    def _decide(self, row, account) -> None:
        from apps.personal import paydays, services

        if row.amount_cents <= 0:
            row.outcome = O.IGNORE
            self.counts["skipped"] += 1
            return
        feed_from = row.feed_account.feed_from
        if feed_from and row.on_date < feed_from:
            row.outcome = O.BEFORE_FEED
            self.counts["skipped"] += 1
            return
        if row.pending:
            row.outcome = O.PENDING
            self.counts["pending"] += 1
            return
        line = {"bank_id": "", "on_date": row.on_date, "amount_cents": row.amount_cents,
                "direction": row.direction, "description": row.description}
        known = self._known(account)
        if known.duplicate(line):
            row.outcome = O.DUPLICATE
            self.counts["matched"] += 1
            return
        made = dict(ledger=self.ledger, account=account, on_date=row.on_date,
                    direction=row.direction, description=row.description,
                    amount_cents=row.amount_cents, source=self.Line.Source.BANK)
        other = known.transfer(line)
        if other is not None:
            row.personal_line = self.Line.objects.create(category=None, **made)
            services.pair(row.personal_line, other)
            row.outcome = O.TRANSFER
        else:
            category = services.threshold_category(self.ledger, row.amount_cents)
            if row.direction == "in" and account.kind != account.Kind.CARD:
                draw = paydays.draw_for(self.tenant, on_date=row.on_date,
                                        amount_cents=row.amount_cents, taken=self.draws)
                if draw is not None:
                    self.draws.add(draw.pk)
                    category = services.system_category(self.ledger,
                                                        services.PAY_FROM_PRACTICE)
            row.personal_line = self.Line.objects.create(category=category, **made)
            row.outcome = O.NEW
        self.made_any = True
        self.counts["added"] += 1

    # ---------------------------------------------------------- modified

    def modified(self, t) -> None:
        row = self._row(t.provider_transaction_id)
        if row is None:
            self.added(t)
            return
        self._change(row, t)

    def _change(self, row, t) -> None:
        was = row.description
        row.on_date, row.amount_cents, row.direction = t.on_date, t.amount_cents, t.direction
        row.description, row.pending = t.description[:255], t.pending
        row.bank_category = t.bank_category[:120] or row.bank_category
        line = row.personal_line if row.outcome in MADE else None
        account = row.feed_account.personal_account
        if line is not None and line.removed_at is None:
            self._change_line(row, line, was)
        elif account is not None and (
                (row.outcome == O.PENDING and not row.pending)
                or (row.outcome == O.BEFORE_FEED and row.feed_account.feed_from
                    and row.on_date >= row.feed_account.feed_from)):
            self._decide(row, account)               # posted, or now inside the feed
        row.save()
        self.counts["modified"] += 1

    def _change_line(self, row, line, was) -> None:
        changes = {}
        for field in ("on_date", "amount_cents", "direction"):
            if getattr(line, field) != getattr(row, field):
                changes[field] = getattr(row, field)
        if line.description == was and line.description != row.description:
            changes["description"] = row.description
        if not changes:
            return
        if self._finished(line):
            self._held(row, line, "changed")
            return
        self.Line.objects.filter(pk=line.pk).update(**changes, updated_at=timezone.now())

    def _held(self, row, line, what) -> None:
        self.counts["closed_month"] += 1
        self._notice(row, f"The bank {what} a line on a reconciled statement",
                     f"{line.description or 'A line'} ({_money(line.amount_cents)}, "
                     f"{line.on_date:%b %-d, %Y}) was {what} at the bank after it was ticked "
                     "on a finished statement. The line was left as it is; reopen that "
                     "reconciliation to change it.")

    # ----------------------------------------------------------- removed

    def removed(self, transaction_id: str) -> None:
        from apps.personal import services

        row = self._row(transaction_id)
        if row is None or row.removed_at is not None:
            return
        row.removed_at = timezone.now()
        row.save(update_fields=["removed_at", "updated_at"])
        self.counts["removed"] += 1
        line = row.personal_line if row.outcome in MADE else None
        if line is None or line.removed_at is not None:
            return
        if self._finished(line):
            self._held(row, line, "removed")
            return
        services.unpair(line)
        line.removed_at, line.remove_reason, line.cleared_in = \
            timezone.now(), REMOVED_REASON, None
        line.save(update_fields=["removed_at", "remove_reason", "cleared_in", "updated_at"])

    # ------------------------------------------------------------ finish

    def finish(self) -> None:
        if not self.made_any:
            return
        from apps.personal import paydays

        # Decision 20: link pay to the practice's draw it came from (read only).
        paydays.match(self.ledger, self.tenant)


def _money(cents: int) -> str:
    return f"${cents / 100:,.2f}"
