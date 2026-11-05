"""Bank feeds on the personal side (`docs/p6_bank_feeds.md`, "Personal
finance"), with the fake provider.

The side isolation family: a personal connection's lines land in its owner's
personal ledger and nowhere else (no entry in the practice's books, nothing
in its P&L, none of the practice's rules applied, a practice account never a
target), and nobody but that owner reaches it, not even another owner of the
same practice. Then the sync's own cases: pending lines, changes, removals,
a finished statement, transfers, duplicates, pay from the practice, the
nightly job, the count across both sides and the demo's sample.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from apps.finance.bankfeeds import providers, sync
from apps.finance.bankfeeds.providers.base import Account
from apps.finance.bankfeeds.providers.fake import FakeProvider
from apps.finance.models import BankConnection, BankFeedTransaction, FinanceEntry
from apps.notify.models import Notice
from apps.personal.models import PersonalLine
from apps.tenancy.context import tenant_context

from . import registry_config  # noqa: F401
from .conftest import _member
from .test_bank_feeds import B, TODAY, connect, t, today  # noqa: F401
from .test_client_invoicing import call, get, post  # noqa: F401
from .test_finance_books import A, C, E, books  # noqa: F401
from .test_personal_accounts import P, household  # noqa: F401


@pytest.fixture
def fake():
    provider = FakeProvider()
    provider.accounts_list = [
        Account("acc-joint", "Joint checking", "ACU Share Draft", "2210", "depository",
                "checking", 500_000, 490_000, "USD"),
        Account("acc-save", "Joint savings", "ACU Share Savings", "7781", "depository",
                "savings", 1_000_000, None, "USD"),
    ]
    with providers.use(provider):
        yield provider


def connect_personal(api, ff, fake):
    made = post(api, ff, B + "connect/", {"public_token": "public-fake", "side": "personal"})
    assert made.status_code == 201, made.content
    assert made.json()["side"] == "personal"
    return made.json()


def map_personal(api, ff, household, connection, savings=False):
    feeds = {a["name"]: a["id"] for a in connection["accounts"]}
    body = {feeds["Joint checking"]: household["joint"]["id"],
            feeds["Joint savings"]: household["savings"]["id"] if savings else ""}
    response = post(api, ff, f"{B}{connection['id']}/mapping/", {"mapping": body})
    assert response.status_code == 200, response.content
    return response.json()


def feed_lines(**filters):
    return PersonalLine.objects.filter(source="bank", **filters)


def run(tenant, connection_id):
    with tenant_context(tenant.pk):
        return sync.run(BankConnection.objects.get(pk=connection_id))


def books_untouched(tenant):
    with tenant_context(tenant.pk):
        return not FinanceEntry.objects.filter(source="bank").exists()


# ================================================= side isolation, the books

@pytest.mark.django_db
def test_personal_lines_land_in_the_ledger_only_never_the_books_or_pnl(household, ff, api,
                                                                       fake, today):
    from apps.finance import reports

    tenant = household["tenant"]
    with tenant_context(tenant.pk):
        pnl_before = reports.pnl(tenant, year=TODAY.year)
    connection = map_personal(api, ff, household, connect_personal(api, ff, fake))
    assert connection["accounts"][0]["personal_account"]["name"] in ("Joint checking",
                                                                      "Joint savings")
    fake.pages = [{"added": [
        t(1, 1_850, text="SAFEWAY #1532", account="acc-joint"),
        t(2, 9_412, text="KING SOOPERS #0114", account="acc-joint"),
        t(3, 250_000, way="in", text="PAYROLL ACME", account="acc-joint"),
        t(4, 7_000, text="SAVINGS LINE", account="acc-save")]}]
    counts = run(tenant, connection["id"])
    assert counts["added"] == 3 and counts["skipped"] == 1
    lines = {line.description: line for line in feed_lines()}
    assert set(lines) == {"SAFEWAY #1532", "KING SOOPERS #0114", "PAYROLL ACME"}
    assert all(str(line.account_id) == household["joint"]["id"] for line in lines.values())
    assert all(line.finance_entry_id is None and line.paid_entry_id is None
               for line in lines.values())
    # Decision 5 by the threshold: small to Everything else, the rest To sort.
    assert lines["SAFEWAY #1532"].category.name == "Everything else"
    assert lines["KING SOOPERS #0114"].category is None
    # Nothing in the practice's books, its P&L or its reconcile.
    assert books_untouched(tenant)
    with tenant_context(tenant.pk):
        assert not BankFeedTransaction.objects.filter(entry__isnull=False).exists()
    with tenant_context(tenant.pk):
        assert reports.pnl(tenant, year=TODAY.year) == pnl_before


@pytest.mark.django_db
def test_the_practices_split_personal_and_business_rules_never_touch_them(household, ff, api,
                                                                          fake, today):
    """The household fixture's rules: Adobe is the practice's, Netflix
    personal, Verizon 60% business. On a fed personal line none applies."""
    tenant = household["tenant"]
    connection = map_personal(api, ff, household, connect_personal(api, ff, fake))
    fake.pages = [{"added": [t(1, 5_999, text="ADOBE *CREATIVE CLOUD", account="acc-joint"),
                             t(2, 2_299, text="NETFLIX.COM", account="acc-joint"),
                             t(3, 10_000, text="VERIZON WIRELESS", account="acc-joint")]}]
    run(tenant, connection["id"])
    lines = {line.description: line for line in feed_lines()}
    assert lines["ADOBE *CREATIVE CLOUD"].category is None            # To sort, not business
    assert lines["NETFLIX.COM"].category.name == "Everything else"     # the threshold only
    assert lines["VERIZON WIRELESS"].category is None                 # no split
    assert all(line.amount_cents in (5_999, 2_299, 10_000) for line in lines.values())
    assert not PersonalLine.objects.filter(paid_entry__isnull=False).exists()
    assert books_untouched(tenant)
    with tenant_context(tenant.pk):
        assert not FinanceEntry.objects.filter(description__in=list(lines)).exists()


@pytest.mark.django_db
def test_a_personal_connection_maps_to_household_accounts_only(household, ff, api, fake,
                                                               today):
    connection = connect_personal(api, ff, fake)
    feed = connection["accounts"][0]["id"]
    url = f"{B}{connection['id']}/mapping/"
    # Not the practice's ledger account.
    refused = post(api, ff, url, {"mapping": {feed: household["bank"]["id"]}})
    assert refused.status_code == 404 and "personal accounts" in refused.json()["detail"]
    # Nor a Mixed account (the practice's, listed on the personal side).
    mixed = post(api, ff, A, {"name": "Everyday Visa", "kind": "card",
                              "opening_balance_cents": 0, "opening_on": "2026-01-01"}).json()
    assert post(api, ff, url, {"mapping": {feed: mixed["id"]}}).status_code == 404
    # And the practice's connection cannot feed a household account.
    practice = post(api, ff, B + "connect/", {"public_token": "public-fake"}).json()
    assert practice["side"] == "practice"
    refused = post(api, ff, f"{B}{practice['id']}/mapping/",
                   {"mapping": {practice["accounts"][0]["id"]: household["joint"]["id"]}})
    assert refused.status_code == 404
    # Its own household account is fine, and feeds from after the newest line.
    mapped = post(api, ff, url, {"mapping": {feed: household["joint"]["id"]}}).json()
    row = next(a for a in mapped["accounts"] if a["id"] == feed)
    assert row["personal_account"]["id"] == household["joint"]["id"]
    assert row["finance_account"] is None and row["feed_from"] == "2026-09-01"


# ================================================ side isolation, the people

@pytest.mark.django_db
def test_nobody_but_its_owner_reaches_a_personal_connection(household, ff, api, fake, today,
                                                            tenant_b, fcc):
    tenant = household["tenant"]
    mine = map_personal(api, ff, household, connect_personal(api, ff, fake))
    calls = [("post", f"{B}{mine['id']}/mapping/", {"mapping": {}}),
             ("post", f"{B}{mine['id']}/check/", {}),
             ("post", f"{B}{mine['id']}/reconnected/", {}),
             ("post", f"{B}{mine['id']}/disconnect/", {}),
             ("post", B + "link-token/", {"connection": mine["id"]})]
    # Another owner of the same practice: not listed, and 404 everywhere.
    other = _member(tenant, "FF")
    listed = get(api, other, B).json()
    assert listed["personal"] == [] and mine["id"] not in json.dumps(listed)
    for method, url, body in calls:
        assert call(api.as_(other), method, url, body).status_code == 404, url
    # Another practice's owner.
    stranger = _member(tenant_b, "FF")
    assert mine["id"] not in get(api, stranger, B).content.decode()
    for method, url, body in calls:
        assert call(api.as_(stranger), method, url, body).status_code == 404, url
    # An associate and an assistant are refused bank connections outright; a
    # client user finds no route.
    for role in ("CF", "VA"):
        who = _member(tenant, role)
        for method, url, body in calls:
            assert call(api.as_(who), method, url, body).status_code == 403, (role, url)
    for method, url, body in calls:
        assert call(api.as_(fcc), method, url, body).status_code == 404, url
    # The owner sees it, under Personal and not among the practice's.
    listed = get(api, ff, B).json()
    assert [c["id"] for c in listed["personal"]] == [mine["id"]]
    assert listed["connections"] == [] and listed["personal_on"] is True


@pytest.mark.django_db
def test_without_personal_finance_no_personal_connection_is_made(books, ff, api, fake):
    refused = post(api, ff, B + "connect/", {"public_token": "public-fake", "side": "personal"})
    assert refused.status_code == 404
    assert "Personal finance" in refused.json()["detail"]
    assert get(api, ff, B).json()["personal_on"] is False
    assert post(api, ff, B + "connect/", {"public_token": "public-fake",
                                          "side": "elsewhere"}).status_code == 400
    with tenant_context(books["tenant"].pk):
        assert not BankConnection.objects.exists()


@pytest.mark.django_db
def test_the_count_covers_both_sides_together(household, ff, api, fake, today):
    connect_personal(api, ff, fake)
    assert post(api, ff, B + "connect/", {"public_token": "public-fake"}).status_code == 201
    listed = get(api, ff, B).json()
    assert (listed["count"], len(listed["connections"]), len(listed["personal"])) == (2, 1, 1)
    assert listed["price_line"] == "5 bank connections included, then $0.50 a month each"


# =========================================================== the sync

@pytest.mark.django_db
def test_a_pending_line_makes_no_line_until_it_posts(household, ff, api, fake, today):
    tenant = household["tenant"]
    connection = map_personal(api, ff, household, connect_personal(api, ff, fake))
    fake.pages = [{"added": [t(1, 6_000, text="SHELL OIL", account="acc-joint",
                               pending=True)]}]
    assert run(tenant, connection["id"])["pending"] == 1
    assert not feed_lines().exists()
    fake.pages.append({"added": [t(2, 6_150, text="SHELL OIL 5741", account="acc-joint",
                                   pending_id="txn-1")], "removed": ["txn-1"]})
    run(tenant, connection["id"])
    line = feed_lines().get()
    assert (line.amount_cents, line.description) == (6_150, "SHELL OIL 5741")
    with tenant_context(tenant.pk):
        row = BankFeedTransaction.objects.get()
        assert (row.provider_transaction_id, row.outcome, row.personal_line_id) == (
            "txn-2", "new", line.pk)
    assert books_untouched(tenant)


@pytest.mark.django_db
def test_changes_and_removals_follow_the_bank_but_not_past_a_finished_statement(
        household, ff, api, fake, today):
    tenant = household["tenant"]
    connection = map_personal(api, ff, household, connect_personal(api, ff, fake))
    fake.pages = [{"added": [t(1, 1_200, text="COFFEE", account="acc-joint"),
                             t(2, 4_000, text="HARDWARE", account="acc-joint"),
                             t(3, 3_000, text="BOOKS", account="acc-joint")]}]
    run(tenant, connection["id"])
    fake.pages.append({"modified": [t(1, 1_350, text="COFFEE BAR", account="acc-joint")],
                       "removed": ["txn-2"]})
    run(tenant, connection["id"])
    coffee = feed_lines().get(on_date=TODAY, amount_cents=1_350)
    assert coffee.description == "COFFEE BAR"
    hardware = feed_lines().get(description="HARDWARE")
    assert hardware.removed_at is not None and "bank removed" in hardware.remove_reason
    # Ticked on a finished statement: the bank's change waits, with a notice
    # for this owner only.
    books_line = feed_lines().get(description="BOOKS")
    rec = post(api, ff, f"{P}accounts/{household['joint']['id']}/reconciliations",
               {"statement_on": TODAY.isoformat(),
                "statement_balance_cents": 500_000 - 1_350 - 3_000}).json()
    post(api, ff, f"{P}reconciliations/{rec['id']}/tick",
         {"lines": [line["id"] for line in rec["lines"]], "cleared": True})
    assert post(api, ff, f"{P}reconciliations/{rec['id']}/finish", {}).json()["state"] \
        == "finished"
    other = _member(tenant, "FF")
    fake.pages.append({"removed": ["txn-3"]})
    assert run(tenant, connection["id"])["closed_month"] == 1
    books_line.refresh_from_db()
    assert books_line.removed_at is None
    with tenant_context(tenant.pk):
        told = Notice.objects.filter(kind="bank", title__contains="reconciled statement")
        assert [n.recipient_id for n in told] == [ff.user.pk]
        assert not Notice.objects.filter(recipient=other.user).exists()
    assert books_untouched(tenant)


@pytest.mark.django_db
def test_transfers_pair_lines_already_in_are_not_doubled_and_pay_is_recognized(
        household, ff, api, fake, today):
    tenant = household["tenant"]
    # Typed into savings before the feed: the other side of a move from checking.
    from apps.personal.models import PersonalLedger

    PersonalLine.objects.create(ledger=PersonalLedger.objects.get(owner=ff.user),
                                account_id=household["savings"]["id"], direction="in",
                                amount_cents=20_000, on_date=TODAY,
                                description="FROM CHECKING")
    connection = connect_personal(api, ff, fake)
    feeds = {a["name"]: a["id"] for a in connection["accounts"]}
    post(api, ff, f"{B}{connection['id']}/mapping/", {"mapping": {
        feeds["Joint checking"]: household["joint"]["id"], feeds["Joint savings"]: ""}})
    joint = PersonalLine.objects.get(description="FROM CHECKING")
    # The owner's draw from the practice, the day before it lands.
    with tenant_context(tenant.pk):
        from apps.finance.models import FinanceAccount

        from .test_personal_taxes import owner_draw

        draw = owner_draw(tenant, ff, FinanceAccount.objects.get(pk=household["bank"]["id"]),
                          TODAY - timedelta(days=1), 300_000)
    entries_before = FinanceEntry.all_objects.filter(tenant=tenant).count()
    fake.pages = [{"added": [t(1, 20_000, text="TRANSFER TO SAVINGS", account="acc-joint"),
                             t(2, 300_000, way="in", text="ACH SUMMIT OPS",
                               account="acc-joint"),
                             t(3, 900, text="GUM", account="acc-joint"),
                             t(4, 900, text="GUM", account="acc-joint")]}]
    run(tenant, connection["id"])
    moved = feed_lines().get(description="TRANSFER TO SAVINGS")
    joint.refresh_from_db()
    assert moved.transfer_pair_id == joint.pk and joint.transfer_pair_id == moved.pk
    assert moved.category.name == "Transfers"
    pay = feed_lines().get(description="ACH SUMMIT OPS")
    assert pay.draw_entry_id == draw.pk and pay.category.system_code == "pay_from_practice"
    # Two of the same on one day are two lines: the bank's ids tell them apart.
    assert feed_lines(description="GUM").count() == 2
    # Read, never written: the books have the same entries as before.
    assert FinanceEntry.all_objects.filter(tenant=tenant).count() == entries_before
    # Sent again (a sync started over): nothing doubles.
    run(tenant, connection["id"])
    BankConnection.all_objects.filter(pk=connection["id"]).update(cursor="")
    run(tenant, connection["id"])
    assert feed_lines().count() == 4


@pytest.mark.django_db
def test_the_nightly_job_and_check_now_cover_personal_connections(household, ff, api, fake,
                                                                  today):
    from apps.finance.tasks import sync_bank_feeds

    tenant = household["tenant"]
    connection = map_personal(api, ff, household, connect_personal(api, ff, fake))
    fake.pages = [{"added": [t(1, 1_000, text="NIGHT LINE", account="acc-joint")]}]
    with tenant_context(tenant.pk):
        done = sync_bank_feeds(tenant)
    assert done[connection["id"]]["added"] == 1
    fake.pages.append({"added": [t(2, 1_100, text="CHECKED LINE", account="acc-joint")]})
    checked = post(api, ff, f"{B}{connection['id']}/check/", {})
    assert checked.status_code == 200 and checked.json()["counts"]["added"] == 1
    assert post(api, ff, f"{B}{connection['id']}/check/", {}).status_code == 429
    # Disconnect: the lines stay, the sync stops.
    gone = post(api, ff, f"{B}{connection['id']}/disconnect/", {}).json()
    assert gone["status"] == "disconnected"
    assert feed_lines(removed_at__isnull=True).count() == 2
    listed = get(api, ff, B).json()
    assert listed["personal"] == [] and len(listed["personal_disconnected"]) == 1


@pytest.mark.django_db
def test_a_login_problem_on_a_personal_connection_tells_its_owner_only(household, ff, api,
                                                                       fake, today):
    from apps.finance.bankfeeds.providers.base import ProviderError

    tenant = household["tenant"]
    other = _member(tenant, "FF")
    connection = map_personal(api, ff, household, connect_personal(api, ff, fake))
    fake.fail_with = ProviderError("Sign in again.", code="ITEM_LOGIN_REQUIRED")
    with pytest.raises(ProviderError):
        run(tenant, connection["id"])
    listed = get(api, ff, B).json()["personal"][0]
    assert listed["reconnect"] is True
    with tenant_context(tenant.pk):
        assert Notice.objects.filter(kind="bank", recipient=ff.user).exists()
        assert not Notice.objects.filter(kind="bank", recipient=other.user).exists()


@pytest.mark.django_db
def test_the_demo_refuses_a_personal_connection(household, ff, api, fake, settings):
    settings.APP_ENVIRONMENT = "demo"
    refused = post(api, ff, B + "connect/", {"public_token": "public-fake", "side": "personal"})
    assert refused.status_code == 409 and "demo" in refused.json()["detail"]

