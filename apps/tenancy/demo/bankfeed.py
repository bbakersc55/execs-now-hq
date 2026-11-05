"""The demo's bank connection (`docs/p6_bank_feeds.md`, "Demo").

The demo never talks to a bank: connecting one is refused there, as Gmail is.
So that the Bank connections card and the feed's entries have something to
show, the seed makes one connection, Front Range Bank, with three accounts
(checking and the Visa fed, savings not), and runs one sync through the real
sync code with the test provider standing in for Plaid: today's lines, one of
them still pending. They are dated today, after the bank reconciliation in
progress ends, so it is unchanged.

And one **personal** connection, Aspen Credit Union, on the owner's
household side: joint checking fed into the personal ledger, joint savings
not, with today's lines (one small, one for To sort, one pending), through
the same sync code. Nothing of it reaches the practice's books.
"""

from __future__ import annotations

from datetime import timedelta

from .clock import at, moment

INSTITUTION = "Front Range Bank"
PERSONAL_INSTITUTION = "Aspen Credit Union"


def connect(world) -> None:
    from apps.crm.services import secrets
    from apps.finance import reports
    from apps.finance.bankfeeds import providers, sync
    from apps.finance.bankfeeds.providers.base import Account, Transaction
    from apps.finance.bankfeeds.providers.fake import FakeProvider
    from apps.finance.models import BankConnection, BankFeedAccount

    books = world.extra["books"]
    bank, card, today = books["bank"], books["card"], world.today
    lines = {
        "demo-checking": [
            ("in", 312, "INTEREST PAID", "Income: interest earned", False),
            ("out", 4_250, "SQ *DENVER BEAN CO", "Food and drink: coffee", False),
            ("out", 18_900, "UNITED AIRLINES 0162", "Travel: flights", True),
        ],
        "demo-visa": [
            ("out", 6_480, "OFFICE DEPOT #1123", "General merchandise: office supplies",
             False),
            ("out", 1_499, "CANVA* PRO 04412", "General services: other", True),
        ],
    }

    def flow(account_key):
        return sum((c if way == "in" else -c) for way, c, *_r, pending in lines[account_key]
                   if not pending)

    when = moment(today, 7, 5)
    with at(when):
        bank_now = reports.account_balance(world.tenant, bank, today)
        card_now = reports.account_balance(world.tenant, card, today)
        fake = FakeProvider()
        fake.accounts_list = [
            Account("demo-checking", "Business checking", "FRB Business Checking", "4417",
                    "depository", "checking", bank_now + flow("demo-checking"),
                    bank_now + flow("demo-checking") - 18_900, "USD"),
            Account("demo-savings", "Business savings", "FRB Business Savings", "4419",
                    "depository", "savings", 2_500_000, 2_500_000, "USD"),
            # A card's balance is what is owed: charges add to it.
            Account("demo-visa", "Business Visa", "FRB Business Visa", "0932", "credit",
                    "credit card", card_now - flow("demo-visa"), None, "USD"),
        ]
        number = 0
        added = []
        for key, rows in lines.items():
            for way, cents, text, category, pending in rows:
                number += 1
                added.append(Transaction(
                    provider_transaction_id=f"demo-{world.tenant.pk}-{number}",
                    provider_account_id=key, on_date=today, amount_cents=cents,
                    direction=way, description=text, bank_category=category,
                    pending=pending))
        fake.pages = [{"added": added}]
        connection = BankConnection.objects.create(
            tenant=world.tenant, provider="plaid", item_id=f"demo-{world.tenant.pk}",
            institution_id="ins_demo", institution_name=INSTITUTION,
            # Never a real token: the demo refuses everything that would use it.
            access_token_ciphertext=secrets.encrypt("demo-no-bank"),
            created_by=world.owner)
        feeds = {f.provider_account_id: f
                 for f in sync.store_accounts(connection, fake.accounts_list)}
        for key, ledger in (("demo-checking", bank), ("demo-visa", card)):
            BankFeedAccount.objects.filter(pk=feeds[key].pk).update(
                finance_account=ledger, feed_from=today)
        BankFeedAccount.objects.filter(pk=feeds["demo-savings"].pk).update(skipped=True)
        with providers.use(fake):
            sync.run(connection, actor=world.owner)
        BankConnection.objects.filter(pk=connection.pk).update(
            last_checked_at=when - timedelta(hours=3))
    world.extra["bank_connection"] = connection
    if "household" in world.extra:
        personal(world)


def personal(world) -> None:
    from apps.crm.services import secrets
    from apps.finance.bankfeeds import providers, sync
    from apps.finance.bankfeeds.providers.base import Account, Transaction
    from apps.finance.bankfeeds.providers.fake import FakeProvider
    from apps.finance.models import BankConnection, BankFeedAccount
    from apps.personal import reconcile

    house, today = world.extra["household"], world.today
    joint = house["joint"]
    lines = [("out", 1_850, "SAFEWAY #1532", "Food and drink: groceries", False),
             ("out", 9_412, "KING SOOPERS #0114", "Food and drink: groceries", False),
             ("out", 6_000, "SHELL OIL 5741", "Transportation: gas", True)]
    when = moment(today, 7, 10)
    with at(when):
        joint_now = reconcile.balance(joint, today) - sum(
            c for _w, c, _t, _c, pending in lines if not pending)
        fake = FakeProvider()
        fake.accounts_list = [
            Account("demo-joint", "Joint checking", "ACU Share Draft", joint.last4,
                    "depository", "checking", joint_now, joint_now - 6_000, "USD"),
            Account("demo-joint-savings", "Joint savings", "ACU Share Savings",
                    house["savings"].last4, "depository", "savings",
                    reconcile.balance(house["savings"], today), None, "USD"),
        ]
        fake.pages = [{"added": [
            Transaction(provider_transaction_id=f"demo-personal-{world.tenant.pk}-{n}",
                        provider_account_id="demo-joint", on_date=today, amount_cents=cents,
                        direction=way, description=text, bank_category=category,
                        pending=pending)
            for n, (way, cents, text, category, pending) in enumerate(lines, start=1)]}]
        connection = BankConnection.objects.create(
            tenant=world.tenant, provider="plaid", item_id=f"demo-personal-{world.tenant.pk}",
            institution_id="ins_demo_personal", institution_name=PERSONAL_INSTITUTION,
            access_token_ciphertext=secrets.encrypt("demo-no-bank"),
            created_by=world.owner, side="personal", ledger=house["ledger"])
        feeds = {f.provider_account_id: f
                 for f in sync.store_accounts(connection, fake.accounts_list)}
        BankFeedAccount.objects.filter(pk=feeds["demo-joint"].pk).update(
            personal_account=joint, feed_from=today)
        BankFeedAccount.objects.filter(pk=feeds["demo-joint-savings"].pk).update(skipped=True)
        with providers.use(fake):
            sync.run(connection, actor=world.owner)
        BankConnection.objects.filter(pk=connection.pk).update(
            last_checked_at=when - timedelta(hours=2))
    world.extra["personal_bank_connection"] = connection
