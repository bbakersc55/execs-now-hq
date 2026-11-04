"""What a sync does to the books (`docs/p6_bank_feeds.md`, "Sync").

One pass per connection: the balances from the provider's accounts call, then
every change since the stored cursor (all pages), applied in one transaction,
and only then the new cursor stored. A pass that fails stores nothing, so the
next one reads the same changes again.

- **Added** transactions become entries marked as from the bank feed, decided
  the way a CSV import's lines are (`importer._Books`, the owner's rules):
  a line already in the books is not entered twice, a deposit that is an
  invoice payment already recorded places that payment in the account, and a
  line that is the other side of a transfer already in the books is matched
  to it. Otherwise it is a new entry, in the category a rule gives it, or in
  none with the bank's own category beside it as the suggestion.
- **Modified** ones change their entry's date, amount and direction (and its
  description, unless the owner has changed it); the category is the owner's.
- **Removed** ones remove their entry, with a reason, unless it is dated in a
  closed month (or ticked in a finished reconciliation), which raises a notice
  instead and leaves the entry alone.
- **Pending** ones are entries marked pending, never ticked or counted in a
  reconciliation until they post. A posted transaction that names its pending
  one takes over that one's entry.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

from django.db import transaction
from django.utils import timezone

from apps.finance import services
from apps.finance.models import (
    BankConnection, BankFeedAccount, BankFeedTransaction, FinanceEntry, FinanceRule,
)
from apps.finance.services import FinanceError

from . import providers

log = logging.getLogger(__name__)

O = BankFeedTransaction.Outcome
K = FinanceEntry.Kind
D = FinanceEntry.Direction
#: The outcomes that made an entry of their own.
MADE = (O.NEW, O.TRANSFER)
#: The outcomes whose entry the bank showed (for Reconcile's "from the bank").
SHOWN = (O.NEW, O.TRANSFER, O.TRANSFER_MATCH, O.INVOICE_PAYMENT)
REMOVED_REASON = "The bank removed this transaction (bank feed)."


class SyncRefused(Exception):
    pass


def undecided(connection) -> int:
    """Accounts the owner has neither mapped nor chosen not to feed. While any
    is, no transaction is read: reading moves the cursor past their lines."""
    return BankFeedAccount.all_objects.filter(
        connection=connection, finance_account__isnull=True, skipped=False).count()


#: Account types that are not where a practice's money moves day to day. They
#: arrive set not to feed (the owner can still map one); a bank or card arrives
#: undecided, and waits for the owner.
NOT_FED_AT_FIRST = ("investment", "loan", "brokerage", "other")


def store_accounts(connection, found) -> list[BankFeedAccount]:
    """The provider's accounts, with their balances, onto the connection. A
    new account arrives undecided; one no longer listed is left as it was."""
    now = timezone.now()
    out = []
    for account in found:
        row, made = BankFeedAccount.all_objects.get_or_create(
            tenant_id=connection.tenant_id, connection=connection,
            provider_account_id=account.provider_account_id)
        if made and account.type in NOT_FED_AT_FIRST:
            row.skipped = True
        row.name, row.official_name = account.name[:160], account.official_name[:200]
        row.mask, row.type, row.subtype = account.mask[:8], account.type[:24], \
            account.subtype[:40]
        row.balance_cents, row.available_cents = account.balance_cents, \
            account.available_cents
        row.currency, row.balance_at = account.currency[:3], now
        row.save()
        out.append(row)
    return out


def run(connection, *, actor=None) -> dict:
    """One pass. Returns the counts; raises SyncRefused (nothing to do) or
    providers.ProviderError (after marking the connection where the login is
    the trouble)."""
    from . import connections

    connection = BankConnection.all_objects.get(pk=connection.pk)
    if connection.status == BankConnection.Status.DISCONNECTED:
        raise SyncRefused("This bank connection is disconnected.")
    token = connections.token_of(connection)
    if not token:
        raise SyncRefused("This connection's key cannot be read. Disconnect it and "
                          "connect the bank again.")
    provider = providers.get(connection.provider)
    try:
        store_accounts(connection, provider.accounts(token))
        waiting = undecided(connection)
        changes = None if waiting else provider.changes(token, connection.cursor)
    except providers.ProviderError as exc:
        connections.failed(connection, exc)
        raise
    if changes is None:
        counts = {"waiting": waiting}
    else:
        counts = apply(connection, changes, actor=actor)
    BankConnection.all_objects.filter(pk=connection.pk).update(
        last_synced_at=timezone.now(), last_sync_counts=counts, last_error="",
        updated_at=timezone.now())
    # A sync that worked shows the login works, unless Plaid has only warned
    # that it will stop (PENDING_*), which still needs the owner's Reconnect.
    if connection.status == BankConnection.Status.NEEDS_ATTENTION \
            and not connection.attention_code.startswith("PENDING_"):
        connections.repaired(connection)
    return counts


@transaction.atomic
def apply(connection, changes, *, actor=None) -> dict:
    connection = BankConnection.all_objects.select_for_update().get(pk=connection.pk)
    pass_ = _Pass(connection, actor)
    for t in changes.added:
        pass_.added(t)
    for t in changes.modified:
        pass_.modified(t)
    for transaction_id in changes.removed:
        pass_.removed(transaction_id)
    connection.cursor = changes.cursor
    connection.save(update_fields=["cursor", "updated_at"])
    pass_.finish()
    return pass_.counts


class _Pass:
    def __init__(self, connection, actor):
        self.connection, self.actor = connection, actor
        self.tenant = connection.tenant
        self.feeds = {f.provider_account_id: f for f in BankFeedAccount.all_objects.filter(
            connection=connection).select_related("finance_account")}
        self.books: dict = {}
        self.rules = list(FinanceRule.all_objects.filter(
            tenant=self.tenant, is_active=True).select_related("category", "other_account"))
        self.locked = services.settings_for(self.tenant).locked_through
        self.counts = {"added": 0, "modified": 0, "removed": 0, "matched": 0,
                       "skipped": 0, "closed_month": 0, "pending": 0}
        self.made: dict = {}                 # finance account id -> [entry ids]

    # ----------------------------------------------------------- helpers

    def _closed(self, day) -> bool:
        return self.locked is not None and day is not None and day <= self.locked

    def _row(self, transaction_id):
        # The connection is locked for the pass, which keeps its rows still.
        return (BankFeedTransaction.all_objects
                .filter(feed_account__connection=self.connection,
                        provider_transaction_id=transaction_id)
                .select_related("entry", "feed_account__finance_account").first())

    def _books(self, account):
        from apps.finance import importer

        if account.pk not in self.books:
            self.books[account.pk] = importer._Books(self.tenant, account, for_feed=True)
        return self.books[account.pk]

    def _notice(self, row, title, text):
        from . import connections

        connections.tell_owner(self.tenant, title=title, text=text,
                               source_type="bank.entry", source_id=row.pk)

    # ------------------------------------------------------------- added

    def added(self, t) -> None:
        feed = self.feeds.get(t.provider_account_id)
        if feed is None or feed.finance_account_id is None:
            self.counts["skipped"] += 1               # an account not fed
            return
        row = self._row(t.provider_transaction_id)
        if row is None and t.pending_transaction_id:
            # Posted: it takes over its pending transaction's row and entry.
            row = self._row(t.pending_transaction_id)
            if row is not None:
                row.provider_transaction_id = t.provider_transaction_id
        if row is not None:
            # Seen before (a pending one posting, or a sync started over).
            self._change(row, t)
            return
        row = BankFeedTransaction(
            tenant_id=self.tenant.pk, feed_account=feed,
            provider_transaction_id=t.provider_transaction_id, on_date=t.on_date,
            amount_cents=t.amount_cents, direction=t.direction,
            description=t.description[:255], bank_category=t.bank_category[:120],
            pending=t.pending)
        self._decide(row, feed.finance_account)
        row.save()
        if row.entry_id and row.outcome in MADE:
            self.made.setdefault(feed.finance_account_id, []).append(row.entry_id)

    def _decide(self, row, account) -> None:
        from apps.finance import importer

        if row.amount_cents <= 0:
            row.outcome = O.IGNORE                  # a line for nothing is no entry
            self.counts["skipped"] += 1
            return
        if feed_from := row.feed_account.feed_from:
            if row.on_date < feed_from:
                row.outcome = O.BEFORE_FEED
                self.counts["skipped"] += 1
                return
        if self._closed(row.on_date):
            row.outcome = O.CLOSED_MONTH
            self.counts["closed_month"] += 1
            self._notice(row, "A bank line in a closed month",
                         f"{account.name}: {row.description or 'a line'} for "
                         f"{_money(row.amount_cents)} on {row.on_date:%b %-d, %Y} arrived "
                         "after that month was closed. It was not entered; reopen the "
                         "month to add it by hand.")
            return
        line = {"bank_id": "", "on_date": row.on_date, "amount_cents": row.amount_cents,
                "direction": row.direction, "description": row.description}
        books = self._books(account)
        if books.duplicate(line):
            row.outcome = O.DUPLICATE
            self.counts["matched"] += 1
            return
        if (payment := books.invoice_payment(line)) is not None:
            FinanceEntry.all_objects.filter(
                tenant=self.tenant, client_payment_id=payment.client_payment_id,
                removed_at__isnull=True, account__isnull=True).update(
                    account=account, updated_at=timezone.now())
            services.audit(self.tenant, "entry_matched", self.actor, payment,
                           account=str(account.pk), line=row.description, by="bank_feed")
            row.outcome, row.entry = O.INVOICE_PAYMENT, payment
            self.counts["matched"] += 1
            return
        if (other := books.transfer(line)) is not None:
            row.outcome, row.entry = O.TRANSFER_MATCH, other
            self.counts["matched"] += 1
            return
        decided = SimpleNamespace(
            description=row.description, direction=row.direction,
            amount_cents=row.amount_cents, outcome="new", category=None,
            payee_contact=None, side="", personal_category=None,
            split_business_cents=None, other_account=None, rule=None)
        importer._apply_rule(decided, self.rules, account)
        if decided.outcome == importer.O.IGNORE:
            row.outcome = O.IGNORE
            self.counts["skipped"] += 1
            return
        mixed = account.side == account.Side.MIXED
        if decided.outcome == importer.O.TRANSFER and decided.other_account is not None:
            out = row.direction == D.OUT
            entry = FinanceEntry.all_objects.create(
                tenant=self.tenant, kind=K.TRANSFER, direction=D.OUT, on_date=row.on_date,
                amount_cents=row.amount_cents,
                account=account if out else decided.other_account,
                to_account=decided.other_account if out else account,
                description=row.description, source=FinanceEntry.Source.BANK,
                pending=row.pending, bank_category=row.bank_category,
                created_by=self.actor)
            row.outcome = O.TRANSFER
        else:
            # A personal or split rule needs the owner's own ledger, which a
            # feed does not write: such a line waits uncategorized (or To sort).
            category = decided.category if decided.side in ("", None) else None
            payee = decided.payee_contact if category is not None else None
            entry = FinanceEntry.all_objects.create(
                tenant=self.tenant, kind=importer._kind_for(category, row.direction),
                direction=row.direction, on_date=row.on_date,
                amount_cents=row.amount_cents, category=category, account=account,
                description=row.description, payee_contact=payee,
                source=FinanceEntry.Source.BANK, pending=row.pending,
                bank_category=row.bank_category,
                side=(FinanceEntry.Side.TO_SORT if mixed and category is None
                      else FinanceEntry.Side.BUSINESS),
                created_by=self.actor)
            row.outcome = O.NEW
        row.entry = entry
        services.audit(self.tenant, "entry_added", self.actor, entry,
                       after=services._state(entry), by="bank_feed")
        self.counts["added"] += 1
        self.counts["pending"] += int(row.pending)

    # ---------------------------------------------------------- modified

    def modified(self, t) -> None:
        row = self._row(t.provider_transaction_id)
        if row is None:
            self.added(t)                    # never seen: as if it were new
            return
        self._change(row, t)

    def _change(self, row, t) -> None:
        was = SimpleNamespace(on_date=row.on_date, amount_cents=row.amount_cents,
                              direction=row.direction, description=row.description,
                              pending=row.pending)
        row.on_date, row.amount_cents, row.direction = t.on_date, t.amount_cents, t.direction
        row.description, row.pending = t.description[:255], t.pending
        row.bank_category = t.bank_category[:120] or row.bank_category
        entry = row.entry if row.outcome in MADE else None
        if entry is not None and entry.removed_at is None:
            self._change_entry(row, entry, was)
        elif row.outcome == O.BEFORE_FEED and row.feed_account.feed_from \
                and row.on_date >= row.feed_account.feed_from:
            self._decide(row, row.feed_account.finance_account)
        row.save()
        self.counts["modified"] += 1

    def _change_entry(self, row, entry, was) -> None:
        changes = {}
        if entry.on_date != row.on_date:
            changes["on_date"] = row.on_date
        if entry.amount_cents != row.amount_cents:
            changes["amount_cents"] = row.amount_cents
        if entry.kind != K.TRANSFER and entry.direction != row.direction:
            changes["direction"] = row.direction
        if entry.description == was.description and entry.description != row.description:
            changes["description"] = row.description
        posted = entry.pending and not row.pending
        if changes:
            if self._closed(entry.on_date) or self._closed(row.on_date):
                self._closed_change(row, entry, "changed")
                return
            try:
                services.update_entry(entry, actor=self.actor, **changes)
            except FinanceError as exc:
                self._notice(row, "The bank changed a reconciled line",
                             f"{entry.description or 'A line'} ({_money(entry.amount_cents)}, "
                             f"{entry.on_date:%b %-d, %Y}) changed at the bank and was left "
                             f"as it is. {exc}")
                return
        if entry.pending != row.pending:
            FinanceEntry.all_objects.filter(pk=entry.pk).update(
                pending=row.pending, updated_at=timezone.now())
        if posted and entry.account_id:
            self.made.setdefault(entry.account_id, []).append(entry.pk)

    def _closed_change(self, row, entry, what) -> None:
        self.counts["closed_month"] += 1
        self._notice(row, f"The bank {what} a line in a closed month",
                     f"{entry.description or 'A line'} ({_money(entry.amount_cents)}, "
                     f"{entry.on_date:%b %-d, %Y}) was {what} at the bank after its month "
                     "was closed. The entry was left as it is; reopen the month to "
                     "change it.")

    # ----------------------------------------------------------- removed

    def removed(self, transaction_id: str) -> None:
        row = self._row(transaction_id)
        if row is None or row.removed_at is not None:
            return
        row.removed_at = timezone.now()
        row.save(update_fields=["removed_at", "updated_at"])
        self.counts["removed"] += 1
        entry = row.entry if row.outcome in MADE else None
        if entry is None or entry.removed_at is not None:
            return
        if self._closed(entry.on_date):
            self._closed_change(row, entry, "removed")
            return
        try:
            services.remove_entry(entry, actor=self.actor, reason=REMOVED_REASON)
        except FinanceError as exc:
            self._notice(row, "The bank removed a reconciled line",
                         f"{entry.description or 'A line'} ({_money(entry.amount_cents)}, "
                         f"{entry.on_date:%b %-d, %Y}) was removed at the bank and kept "
                         f"in the books. {exc}")

    # ------------------------------------------------------------ finish

    def finish(self) -> None:
        if not self.made:
            return
        from apps.finance import reconcile

        for account_id, ids in self.made.items():
            reconcile.fed(self.tenant, account_id, ids)
        from apps.personal import paydays

        paydays.match_for_practice(self.tenant)


def _money(cents: int) -> str:
    return f"${cents / 100:,.2f}"
