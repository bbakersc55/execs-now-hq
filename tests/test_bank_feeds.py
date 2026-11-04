"""Bank feeds, version one (`docs/p6_bank_feeds.md`), with a fake provider.

1. Practice isolation and role boundaries on every route and on the webhook.
2. Connecting: the token is encrypted and never shown; accounts wait to be mapped.
3. Sync: the cursor across pages and passes; added, modified, removed, pending.
4. The closed-month rule.
5. Webhook verification (Plaid's own JWT scheme, with a key made here).
6. Disconnect stops the sync and keeps the entries; Check now once an hour.
7. Balances feed the forecast's cash today and Reconcile; the demo refuses.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import date, timedelta
from unittest import mock

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.finance.bankfeeds import connections, providers, sync
from apps.finance.bankfeeds.providers.base import Account, ProviderError, Transaction
from apps.finance.bankfeeds.providers.fake import FakeProvider
from apps.finance.models import (
    BankConnection, BankFeedAccount, BankFeedTransaction, FinanceEntry, FinanceSettings,
)
from apps.notify.models import Notice
from apps.tenancy.context import tenant_context

from . import registry_config  # noqa: F401
from .conftest import _member
from .test_client_invoicing import call, get, post  # noqa: F401
from .test_finance_books import A, C, E, books  # noqa: F401

B = "/api/finance-bank/"
TODAY = date(2026, 10, 20)


@pytest.fixture
def fake():
    provider = FakeProvider()
    provider.accounts_list = [
        Account("acc-chk", "Checking", "Plaid Checking", "0000", "depository", "checking",
                1_000_000, 990_000, "USD"),
        Account("acc-card", "Credit Card", "Plaid Credit Card", "3333", "credit",
                "credit card", 41_000, None, "USD"),
    ]
    with providers.use(provider):
        yield provider


def t(n, cents, way="out", on=TODAY, account="acc-chk", text=None, pending=False,
      pending_id="", category="Food and drink: coffee"):
    return Transaction(f"txn-{n}", account, on, cents, way, text or f"LINE {n}", category,
                       pending, pending_id)


def connect(api, ff, fake):
    made = post(api, ff, B + "connect/", {"public_token": "public-fake"})
    assert made.status_code == 201, made.content
    return made.json()


def map_all(api, ff, books, connection, card=True):
    feeds = {a["name"]: a["id"] for a in connection["accounts"]}
    body = {feeds["Checking"]: books["bank"]["id"],
            feeds["Credit Card"]: books["card"]["id"] if card else ""}
    response = post(api, ff, f"{B}{connection['id']}/mapping/", {"mapping": body})
    assert response.status_code == 200, response.content
    return response.json()


def bank_entries(tenant):
    with tenant_context(tenant.pk):
        return {e.description: e for e in FinanceEntry.objects.filter(source="bank")}


def run(tenant, connection_id):
    with tenant_context(tenant.pk):
        return sync.run(BankConnection.objects.get(pk=connection_id))


@pytest.fixture
def today():
    with mock.patch("django.utils.timezone.localdate", return_value=TODAY):
        yield TODAY


# ============================================== isolation and role boundaries

def bank_calls(connection_id):
    return [("get", B, None), ("post", B + "link-token/", {}),
            ("post", B + "connect/", {"public_token": "public-fake"}),
            ("post", f"{B}{connection_id}/mapping/", {"mapping": {}}),
            ("post", f"{B}{connection_id}/check/", {}),
            ("post", f"{B}{connection_id}/reconnected/", {}),
            ("post", f"{B}{connection_id}/disconnect/", {})]


@pytest.mark.django_db
def test_tenant_isolation_another_practice_reaches_no_bank_connection(books, ff, tenant_b,
                                                                      api, fake):
    mine = connect(api, ff, fake)
    other = _member(tenant_b, "FF")
    listed = get(api, other, B).json()
    assert listed["connections"] == [] and listed["count"] == 0
    assert mine["id"] not in json.dumps(listed)
    for method, url, body in bank_calls(mine["id"])[3:]:
        response = call(api.as_(other), method, url, body)
        assert response.status_code == 404, (url, response.status_code)
    with tenant_context(books["tenant"].pk):
        assert BankConnection.objects.get(pk=mine["id"]).status == "connected"


@pytest.mark.django_db
def test_tenant_isolation_a_webhook_for_one_practices_item_touches_no_other(books, ff,
                                                                            tenant_b, api,
                                                                            fake):
    from apps.finance.bankfeeds.providers.base import Event

    mine = connect(api, ff, fake)
    with tenant_context(tenant_b.pk):
        theirs = BankConnection.objects.create(tenant=tenant_b, item_id="item-b")
    with tenant_context(books["tenant"].pk):
        item = BankConnection.objects.get(pk=mine["id"]).item_id
    fake.events["sig"] = Event("attention", item, "ITEM_LOGIN_REQUIRED")
    response = api.as_(ff).post("/webhooks/plaid", data=b"{}", content_type="application/json",
                                HTTP_PLAID_VERIFICATION="sig")
    assert response.status_code == 200
    theirs.refresh_from_db()
    assert theirs.status == "connected"
    with tenant_context(books["tenant"].pk):
        assert BankConnection.objects.get(pk=mine["id"]).status == "needs_attention"


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["CF", "VA"])
def test_role_boundaries_only_the_owner_reaches_bank_connections(books, ff, api, fake, role):
    mine = connect(api, ff, fake)
    who = _member(books["tenant"], role)
    for method, url, body in bank_calls(mine["id"]):
        assert call(api.as_(who), method, url, body).status_code == 403, url


@pytest.mark.django_db
def test_role_boundaries_a_client_user_finds_no_bank_route(books, ff, fcc, api, fake):
    mine = connect(api, ff, fake)
    for method, url, body in bank_calls(mine["id"]):
        assert call(api.as_(fcc), method, url, body).status_code == 404, url


@pytest.mark.django_db
def test_the_bank_notice_kind_is_offered_to_the_owner_only(books, ff, cf):
    from apps.notify.service import kinds_for

    assert "bank" in kinds_for(ff)
    assert "bank" not in kinds_for(cf)


# =========================================================== connecting

@pytest.mark.django_db
def test_connecting_keeps_the_token_encrypted_and_never_shows_it(books, ff, api, fake):
    token = post(api, ff, B + "link-token/", {}).json()
    assert token == {"link_token": "link-fake-new", "update": False}
    assert fake.calls[0] == ("link_token", "new", "http://localhost:8100/webhooks/plaid")
    made = connect(api, ff, fake)
    assert made["institution"] == "First Fake Bank" and made["waiting"] == 2
    # A loan or an investment account arrives set not to feed.
    fake.accounts_list.append(Account("acc-loan", "Mortgage", "", "8888", "loan", "mortgage",
                                      5_000_000, None, "USD"))
    loan = connect(api, ff, fake)
    assert loan["waiting"] == 2
    assert next(a for a in loan["accounts"] if a["name"] == "Mortgage")["skipped"] is True
    fake.accounts_list.pop()
    post(api, ff, f"{B}{loan['id']}/disconnect/", {})
    with tenant_context(books["tenant"].pk):
        row = BankConnection.objects.get(pk=made["id"])
        assert b"access-fake" not in bytes(row.access_token_ciphertext)
        assert connections.token_of(row) == "access-fake-item-fake-1"
    listed = get(api, ff, B).content.decode()
    assert "access-fake" not in listed and "ciphertext" not in listed
    assert json.loads(listed)["price_line"] == ("5 bank connections included, then $0.50 a "
                                                "month each")
    assert json.loads(listed)["count"] == 1
    # Nothing is read while an account waits to be mapped.
    assert [c for c in fake.calls if c[0] == "changes"] == []
    assert post(api, ff, B + "connect/", {"public_token": "nope"}).status_code == 502


@pytest.mark.django_db
def test_mapping_feeds_from_after_the_books_own_newest_entry(books, ff, api, fake, today):
    from .test_finance_books import add

    assert add(api, ff, books, "expense", 500, "2026-10-15", "Travel").status_code == 201
    made = map_all(api, ff, books, connect(api, ff, fake))
    feeds = {a["name"]: a for a in made["accounts"]}
    assert feeds["Checking"]["feed_from"] == "2026-10-16"
    assert feeds["Credit Card"]["feed_from"] == "2026-01-01"
    # The same ledger account cannot be fed twice.
    other = connect(api, ff, fake)
    refused = post(api, ff, f"{B}{other['id']}/mapping/", {"mapping": {
        other["accounts"][0]["id"]: books["bank"]["id"]}})
    assert refused.status_code == 409


# ================================================================ sync

@pytest.mark.django_db
def test_cursor_is_carried_across_pages_and_passes(books, ff, api, fake, today):
    fake.pages = [{"added": [t(1, 450)]}, {"added": [t(2, 1200, "in", text="DEPOSIT")]},
                  {"added": [t(3, 3000, account="acc-card", text="AIRLINE")]}]
    made = map_all(api, ff, books, connect(api, ff, fake))
    assert [c for c in fake.calls if c[0] == "changes"] == [("changes", "")]
    with tenant_context(books["tenant"].pk):
        row = BankConnection.objects.get(pk=made["id"])
        assert row.cursor == "3" and row.last_sync_counts["added"] == 3
    fake.pages.append({"added": [t(4, 75)]})
    counts = run(books["tenant"], made["id"])
    assert fake.calls[-1] == ("changes", "3") and counts["added"] == 1
    # A pass with nothing new reads from where it stopped and adds nothing.
    assert run(books["tenant"], made["id"])["added"] == 0
    assert fake.calls[-1] == ("changes", "4")
    found = bank_entries(books["tenant"])
    assert set(found) == {"LINE 1", "DEPOSIT", "AIRLINE", "LINE 4"}
    assert found["DEPOSIT"].kind == "income" and found["DEPOSIT"].direction == "in"
    assert str(found["AIRLINE"].account_id) == books["card"]["id"]
    assert found["LINE 1"].category_id is None
    assert found["LINE 1"].bank_category == "Food and drink: coffee"
    shown = get(api, ff, E).json()["entries"]
    line = next(e for e in shown if e["description"] == "LINE 1")
    assert line["source"] == "bank" and line["source_label"] == "From the bank feed"
    assert line["bank_category"] == "Food and drink: coffee"


@pytest.mark.django_db
def test_a_failed_pass_keeps_the_cursor_and_reads_the_same_changes_again(books, ff, api,
                                                                         fake, today):
    made = map_all(api, ff, books, connect(api, ff, fake))
    fake.pages = [{"added": [t(1, 450)]}]
    fake.fail_with = ProviderError("Plaid could not be reached.", code="UNREACHABLE")
    with pytest.raises(ProviderError):
        run(books["tenant"], made["id"])
    with tenant_context(books["tenant"].pk):
        row = BankConnection.objects.get(pk=made["id"])
    assert row.cursor == "" and row.last_error and row.status == "connected"
    assert run(books["tenant"], made["id"])["added"] == 1


@pytest.mark.django_db
def test_rules_decide_a_fed_line_as_they_decide_an_imported_one(books, ff, api, fake, today):
    from .test_finance_import import RULES

    post(api, ff, RULES, {"contains": "ADOBE", "treat_as": "category",
                          "category": books["cat"]["Software"]["id"]})
    post(api, ff, RULES, {"contains": "SPAM", "treat_as": "ignore"})
    post(api, ff, RULES, {"contains": "CARD PAYMENT", "treat_as": "transfer",
                          "other_account": books["card"]["id"]})
    fake.pages = [{"added": [t(1, 5999, text="ADOBE *CC"), t(2, 100, text="SPAM CO"),
                             t(3, 20000, text="CARD PAYMENT THANK YOU"),
                             t(4, 20000, "in", account="acc-card", text="PAYMENT RECEIVED")]}]
    map_all(api, ff, books, connect(api, ff, fake))
    found = bank_entries(books["tenant"])
    assert found["ADOBE *CC"].category.name == "Software"
    assert "SPAM CO" not in found
    transfer = found["CARD PAYMENT THANK YOU"]
    assert transfer.kind == "transfer" and str(transfer.to_account_id) == books["card"]["id"]
    # The card's side of it is the same transfer, not a second entry.
    assert "PAYMENT RECEIVED" not in found
    with tenant_context(books["tenant"].pk):
        match = BankFeedTransaction.objects.get(provider_transaction_id="txn-4")
    assert match.outcome == "transfer_match" and match.entry_id == transfer.pk


@pytest.mark.django_db
def test_a_line_already_typed_in_is_not_entered_twice(books, ff, api, fake, today):
    made = map_all(api, ff, books, connect(api, ff, fake))
    from .test_finance_books import add

    add(api, ff, books, "expense", 450, TODAY.isoformat(), "Travel", description="LINE 1")
    fake.pages = [{"added": [t(1, 450), t(2, 450, text="LINE 1 AGAIN")]}]
    run(books["tenant"], made["id"])
    with tenant_context(books["tenant"].pk):
        assert BankFeedTransaction.objects.get(provider_transaction_id="txn-1").outcome \
            == "duplicate"
    assert set(bank_entries(books["tenant"])) == {"LINE 1 AGAIN"}


@pytest.mark.django_db
def test_modified_and_removed_transactions_change_and_remove_their_entries(books, ff, api,
                                                                           fake, today):
    fake.pages = [{"added": [t(1, 450), t(2, 900, text="HOTEL")]}]
    made = map_all(api, ff, books, connect(api, ff, fake))
    entry = bank_entries(books["tenant"])["LINE 1"]
    # The owner gives it a category; the bank then changes its amount and date.
    from .test_client_invoicing import patch

    assert patch(api, ff, f"{E}{entry.pk}/", {
        "category": books["cat"]["Meals"]["id"]}).status_code == 200
    fake.pages.append({"modified": [t(1, 475, on=TODAY - timedelta(days=1))],
                       "removed": ["txn-2"]})
    counts = run(books["tenant"], made["id"])
    assert counts["modified"] == 1 and counts["removed"] == 1
    entry.refresh_from_db()
    assert (entry.amount_cents, entry.on_date) == (475, TODAY - timedelta(days=1))
    assert entry.category.name == "Meals"                 # the owner's, kept
    hotel = FinanceEntry.all_objects.get(description="HOTEL")
    assert hotel.removed_at is not None and "bank removed" in hotel.remove_reason


@pytest.mark.django_db
def test_pending_lines_never_count_in_a_reconcile_until_they_post(books, ff, api, fake, today):
    from apps.finance import reconcile
    from apps.finance.models import FinanceAccount

    fake.pages = [{"added": [t(1, 4000, text="PENDING HOTEL", pending=True),
                             t(2, 100, text="POSTED COFFEE")]}]
    made = map_all(api, ff, books, connect(api, ff, fake))
    with tenant_context(books["tenant"].pk):
        account = FinanceAccount.objects.get(pk=books["bank"]["id"])
        rec = reconcile.start(books["tenant"], actor=ff.user, account=account,
                              statement_on=TODAY, statement_balance_cents=1_000_000)
        shown = {line["description"]: line for line in reconcile.lines(rec)}
    assert "PENDING HOTEL" not in shown
    assert shown["POSTED COFFEE"]["from_bank"] and shown["POSTED COFFEE"]["cleared"]
    pending = bank_entries(books["tenant"])["PENDING HOTEL"]
    assert pending.pending
    listed = next(e for e in get(api, ff, E).json()["entries"] if e["id"] == str(pending.pk))
    assert listed["pending"] is True
    # It posts: a new id naming the pending one, and the pending one removed.
    fake.pages.append({"added": [t(3, 4125, text="HOTEL POSTED", pending_id="txn-1")],
                       "removed": ["txn-1"]})
    run(books["tenant"], made["id"])
    pending.refresh_from_db()
    assert not pending.pending and pending.removed_at is None
    assert pending.amount_cents == 4125
    with tenant_context(books["tenant"].pk):
        rec.refresh_from_db()
        shown = {line["id"]: line for line in reconcile.lines(rec)}
    assert shown[str(pending.pk)]["cleared"]            # arrived ticked once posted
    assert FinanceEntry.all_objects.filter(source="bank").count() == 2


# ============================================================ closed months

@pytest.mark.django_db
def test_a_removal_in_a_closed_month_raises_a_notice_and_keeps_the_entry(books, ff, api,
                                                                         fake, today):
    fake.pages = [{"added": [t(1, 450, on=date(2026, 9, 28), text="SEPT LINE")]}]
    made = map_all(api, ff, books, connect(api, ff, fake))
    entry = bank_entries(books["tenant"])["SEPT LINE"]
    with tenant_context(books["tenant"].pk):
        FinanceSettings.objects.filter().update(locked_through=date(2026, 9, 30))
    fake.pages.append({"removed": ["txn-1"],
                       "modified": [],
                       "added": [t(2, 300, on=date(2026, 9, 29), text="LATE SEPT")]})
    counts = run(books["tenant"], made["id"])
    assert counts["closed_month"] == 2
    entry.refresh_from_db()
    assert entry.removed_at is None
    assert "LATE SEPT" not in bank_entries(books["tenant"])
    with tenant_context(books["tenant"].pk):
        told = list(Notice.objects.filter(recipient=ff.user, kind="bank"))
    assert len(told) == 2
    assert any("closed" in n.title for n in told)


# ================================================================ webhooks

def _signed(body: bytes, key, *, kid="k1", iat=None, sha=None):
    import jwt

    return jwt.encode({"iat": int(iat if iat is not None else time.time()),
                       "request_body_sha256": sha or hashlib.sha256(body).hexdigest()},
                      key, algorithm="ES256", headers={"kid": kid})


@pytest.fixture
def plaid_key():
    import jwt
    from cryptography.hazmat.primitives.asymmetric import ec

    from apps.finance.bankfeeds.providers.plaid import PlaidProvider

    private = ec.generate_private_key(ec.SECP256R1())
    jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(private.public_key()))
    jwk.update({"kid": "k1", "alg": "ES256", "use": "sig", "expired_at": None})
    with mock.patch.object(PlaidProvider, "_key", lambda self, kid: jwk if kid == "k1"
                           else (_ for _ in ()).throw(providers.WebhookRefused("no key"))):
        yield private


@pytest.mark.django_db
@override_settings(PLAID_CLIENT_ID="id", PLAID_SECRET="secret")
def test_webhook_verification_accepts_plaid_and_refuses_everything_else(books, ff, api,
                                                                        plaid_key, client):
    made = BankConnection.all_objects.create(tenant=books["tenant"], item_id="item-w")
    body = json.dumps({"webhook_type": "TRANSACTIONS", "webhook_code": "SYNC_UPDATES_AVAILABLE",
                       "item_id": "item-w"}).encode()

    def send(signature, payload=body):
        return client.post("/webhooks/plaid", data=payload, content_type="application/json",
                           HTTP_PLAID_VERIFICATION=signature)

    with mock.patch("django_q.tasks.async_task") as queued:
        assert send(_signed(body, plaid_key)).status_code == 200
        assert queued.call_args.args == ("apps.finance.tasks.sync_bank_connection",
                                         str(made.tenant_id), str(made.pk))
        queued.reset_mock()
        # Every refusal is a 400 and does nothing.
        from cryptography.hazmat.primitives.asymmetric import ec

        stranger = ec.generate_private_key(ec.SECP256R1())
        for signature in ("", "not-a-jwt", _signed(body, stranger),
                          _signed(body, plaid_key, iat=time.time() - 600),
                          _signed(body, plaid_key, sha="0" * 64),
                          _signed(body, plaid_key, kid="unknown")):
            assert send(signature).status_code == 400, signature[:20]
        import jwt

        unsigned = jwt.encode({"iat": int(time.time()),
                               "request_body_sha256": hashlib.sha256(body).hexdigest()},
                              "x" * 32, algorithm="HS256", headers={"kid": "k1"})
        assert send(unsigned).status_code == 400
        queued.assert_not_called()


@pytest.mark.django_db
@override_settings(PLAID_CLIENT_ID="id", PLAID_SECRET="secret")
@pytest.mark.parametrize("payload, code", [
    ({"webhook_type": "ITEM", "webhook_code": "ERROR",
      "error": {"error_code": "ITEM_LOGIN_REQUIRED", "error_message": "sign in again"}},
     "ITEM_LOGIN_REQUIRED"),
    ({"webhook_type": "ITEM", "webhook_code": "PENDING_DISCONNECT"}, "PENDING_DISCONNECT"),
    ({"webhook_type": "ITEM", "webhook_code": "ERROR",
      "error": {"error_code": "INTERNAL_SERVER_ERROR"}}, "INTERNAL_SERVER_ERROR"),
])
def test_item_webhooks_mark_the_connection_and_tell_the_owner(books, ff, api, plaid_key,
                                                              client, payload, code):
    made = BankConnection.all_objects.create(tenant=books["tenant"], item_id="item-w",
                                             institution_name="Chase")
    body = json.dumps({**payload, "item_id": "item-w"}).encode()
    assert client.post("/webhooks/plaid", data=body, content_type="application/json",
                       HTTP_PLAID_VERIFICATION=_signed(body, plaid_key)).status_code == 200
    made.refresh_from_db()
    assert (made.status, made.attention_code) == ("needs_attention", code)
    notice = Notice.all_objects.get(recipient=ff.user, kind="bank")
    assert "Reconnect" in notice.text and f"reconnect={made.pk}" in notice.url
    shown = get(api, ff, B).json()["connections"][0]
    assert shown["reconnect"] is True and shown["status_label"] == "Needs attention"


@pytest.mark.django_db
def test_reconnect_uses_update_mode_and_clears_the_attention(books, ff, api, fake, today):
    made = map_all(api, ff, books, connect(api, ff, fake))
    with tenant_context(books["tenant"].pk):
        connections.needs_attention(BankConnection.objects.get(pk=made["id"]),
                                    "ITEM_LOGIN_REQUIRED")
    token = post(api, ff, B + "link-token/", {"connection": made["id"]}).json()
    assert token == {"link_token": "link-fake-update", "update": True}
    done = post(api, ff, f"{B}{made['id']}/reconnected/", {}).json()
    assert done["status"] == "connected" and not done["reconnect"]


@pytest.mark.django_db
def test_a_login_error_during_sync_marks_needs_attention(books, ff, api, fake, today):
    made = map_all(api, ff, books, connect(api, ff, fake))
    fake.fail_with = ProviderError("Sign in again.", code="ITEM_LOGIN_REQUIRED")
    with pytest.raises(ProviderError):
        run(books["tenant"], made["id"])
    with tenant_context(books["tenant"].pk):
        assert BankConnection.objects.get(pk=made["id"]).status == "needs_attention"
        assert Notice.objects.filter(kind="bank").count() == 1


# ======================================================= disconnect, Check now

@pytest.mark.django_db
def test_disconnect_removes_the_item_stops_the_sync_and_keeps_the_entries(books, ff, api,
                                                                         fake, today):
    from apps.finance.tasks import sync_bank_feeds

    fake.pages = [{"added": [t(1, 450)]}]
    made = map_all(api, ff, books, connect(api, ff, fake))
    done = post(api, ff, f"{B}{made['id']}/disconnect/", {})
    assert done.status_code == 200 and done.json()["status"] == "disconnected"
    assert fake.removed_items == ["access-fake-item-fake-1"]
    with tenant_context(books["tenant"].pk):
        row = BankConnection.objects.get(pk=made["id"])
        assert row.access_token_ciphertext is None and connections.count(books["tenant"]) == 0
        fake.pages.append({"added": [t(2, 99)]})
        calls = len(fake.calls)
        assert sync_bank_feeds(books["tenant"]) == {}
        assert len(fake.calls) == calls                      # nothing asked of the bank
        with pytest.raises(sync.SyncRefused):
            sync.run(row)
    assert post(api, ff, f"{B}{made['id']}/check/", {}).status_code == 409
    assert set(bank_entries(books["tenant"])) == {"LINE 1"}
    listed = get(api, ff, B).json()
    assert listed["connections"] == [] and len(listed["disconnected"]) == 1


@pytest.mark.django_db
def test_check_now_runs_once_an_hour(books, ff, api, fake, today):
    made = map_all(api, ff, books, connect(api, ff, fake))
    fake.pages = [{"added": [t(1, 450)]}]
    first = post(api, ff, f"{B}{made['id']}/check/", {})
    assert first.status_code == 200 and first.json()["counts"]["added"] == 1
    again = post(api, ff, f"{B}{made['id']}/check/", {})
    assert again.status_code == 429 and "minute" in again.json()["detail"]
    with tenant_context(books["tenant"].pk):
        BankConnection.objects.filter(pk=made["id"]).update(
            last_checked_at=timezone.now() - timedelta(minutes=61))
    assert post(api, ff, f"{B}{made['id']}/check/", {}).status_code == 200


@pytest.mark.django_db
def test_the_nightly_job_syncs_each_connected_bank(books, ff, api, fake, today):
    from apps.finance.tasks import keep_month_forecast

    made = map_all(api, ff, books, connect(api, ff, fake))
    fake.pages = [{"added": [t(1, 450)]}]
    keep_month_forecast(str(books["tenant"].pk))
    assert set(bank_entries(books["tenant"])) == {"LINE 1"}
    assert fake.calls[-1] == ("changes", "")
    with tenant_context(books["tenant"].pk):
        assert BankConnection.objects.get(pk=made["id"]).cursor == "1"


# ============================================== balances, the demo, unset keys

@pytest.mark.django_db
def test_the_feeds_balance_is_cash_today_and_the_banks_word_on_reconcile(books, ff, api,
                                                                         fake):
    from apps.finance import forecast, importer

    map_all(api, ff, books, connect(api, ff, fake))
    today = timezone.localdate()
    with tenant_context(books["tenant"].pk):
        rows, total = forecast._accounts(books["tenant"], today)
        said = importer.bank_said(books["tenant"])
    checking = next(r for r in rows if r["id"] == books["bank"]["id"])
    assert checking["amount_cents"] == 1_000_000 and checking["from_bank"]
    assert checking["books_cents"] == 1_000_000 and not checking["stale"]
    assert {k: v for k, v in said.items() if str(k) == books["bank"]["id"]}.popitem()[1] == {
        "on": today, "cents": 1_000_000, "source": "feed"}
    grid = get(api, ff, "/api/finance-reconcile/")
    if grid.status_code == 200:                     # Bookkeeping practices only
        row = next(a for a in grid.json()["accounts"] if a["id"] == books["bank"]["id"])
        assert row["bank_said"]["source"] == "feed"


@pytest.mark.django_db
def test_the_demo_refuses_to_connect_or_touch_a_bank(books, ff, api, fake):
    made = connect(api, ff, fake)
    with override_settings(APP_ENVIRONMENT="demo"):
        listed = get(api, ff, B).json()
        assert listed["demo"] and "demo" in listed["refusal"]
        for method, url, body in bank_calls(made["id"])[1:]:
            response = call(api.as_(ff), method, url, body)
            assert response.status_code == 409, url
            assert "demo" in response.json()["detail"]


@pytest.mark.django_db
@override_settings(PLAID_CLIENT_ID="", PLAID_SECRET="", APP_ENVIRONMENT="production")
def test_with_the_keys_unset_the_feature_is_hidden(books, ff, api):
    listed = get(api, ff, B).json()
    assert listed["available"] is False and listed["refusal"] == connections.NOT_SET_UP
    assert post(api, ff, B + "link-token/", {}).status_code == 409


# ========================================================= the Plaid provider

def test_plaid_amounts_and_categories_are_read_as_the_books_want_them():
    from apps.finance.bankfeeds.providers.plaid import read_transaction

    out = read_transaction({"transaction_id": "t", "account_id": "a", "date": TODAY,
                            "amount": 12.5, "name": "Starbucks", "pending": True,
                            "personal_finance_category": {
                                "primary": "FOOD_AND_DRINK",
                                "detailed": "FOOD_AND_DRINK_COFFEE"}})
    assert (out.amount_cents, out.direction, out.pending) == (1250, "out", True)
    assert out.bank_category == "Food and drink: coffee"
    back = read_transaction({"transaction_id": "t", "account_id": "a", "date": TODAY,
                             "amount": -500.1, "name": "Payroll"})
    assert (back.amount_cents, back.direction) == (50010, "in")


def test_plaid_sync_starts_the_pass_over_when_the_data_moves_under_it():
    from apps.finance.bankfeeds.providers.plaid import PlaidProvider

    pages = iter([
        {"added": [], "modified": [], "removed": [], "next_cursor": "c1", "has_more": True},
        ProviderError("moved", code="TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION"),
        {"added": [], "modified": [], "removed": [{"transaction_id": "gone"}],
         "next_cursor": "c1", "has_more": True},
        {"added": [], "modified": [], "removed": [], "next_cursor": "c2", "has_more": False},
    ])
    seen = []

    def fake_call(self, method, request):
        seen.append(request.get("cursor"))
        page = next(pages)
        if isinstance(page, Exception):
            raise page
        return page

    with mock.patch.object(PlaidProvider, "_call", fake_call):
        out = PlaidProvider(client=object()).changes("access", "c0")
    assert seen == ["c0", "c1", "c0", "c1"]
    assert out.cursor == "c2" and out.removed == ["gone"]
