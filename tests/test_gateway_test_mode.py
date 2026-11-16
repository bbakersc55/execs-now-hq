"""Knowing when the card processor is in Test Mode (2026-11-16,
`docs/p4_billing.md` §12).

The stub gateway stands in for the processor: `test_mode_on` is what its
Test Mode reads, `test_mode_unreadable` makes the read fail. NMI's sandbox
answers true for every account (proved 2026-11-16).
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.billing import (
    autopay, card_payments, gateway as gw, gateway_mode, payment_accounts, refunds, services,
    subscriptions, testmode,
)
from apps.billing.models import (
    CardRefund, ClientInvoice, ClientPayment, ClientPaymentMethod, PaymentAccount,
    PaymentAttempt, PracticeInvoice, PracticeSubscription,
)
from apps.crm.models import OutboxMessage
from apps.finance import forecast
from apps.finance.models import FinanceEntry
from apps.scorecard import practice as practice_kpis
from apps.tenancy.context import tenant_context

from . import registry_config  # noqa: F401
from .conftest import _member
from .test_autopay import save_card as save_client_card
from .test_autopay import turn_on
from .test_card_payments import _after_commit_now  # noqa: F401  (autouse)
from .test_card_payments import billing, pay  # noqa: F401  (a fixture)
from .test_client_invoicing import ready_to_bill  # noqa: F401  (a fixture)
from .test_client_invoicing import post
from .test_platform_practices import practices
from .test_subscriptions import _commit_now  # noqa: F401  (autouse)
from .test_subscriptions import carded, next_first, platform_practice  # noqa: F401
from .test_subscriptions import run as run_subscription

S = ClientInvoice.Status
BANNER = "The card processor is in Test Mode: no money moves."


def account_state(api, ff):
    return api.as_(ff).get("/api/payment-account/").json()


def press_test_connection(api, ff):
    return post(api, ff, "/api/payment-account/test/", {})


# ------------------------------------------------------------ reading it

@pytest.mark.django_db
def test_test_connection_reads_test_mode_and_billing_shows_the_banner(billing, ff, api,
                                                                     stub_gateway):
    assert account_state(api, ff)["gateway_mode"]["test_mode"] is False
    stub_gateway.test_mode_on = True
    shown = press_test_connection(api, ff).json()
    assert shown["gateway_mode"]["test_mode"] is True
    assert shown["gateway_mode"]["banner"] == BANNER
    assert [c[0] for c in stub_gateway.calls][-2:] == ["check_connection", "test_mode"]
    # The practice owner sees it on Invoices too; an associate does not.
    listed = api.as_(ff).get("/api/invoices/").json()
    assert listed["gateway_mode"]["banner"] == BANNER


@pytest.mark.django_db
def test_an_unreadable_setting_behaves_as_today_and_billing_says_so(billing, fcc, ff, api,
                                                                    stub_gateway):
    stub_gateway.test_mode_unreadable = True
    shown = press_test_connection(api, ff).json()
    assert shown["gateway_mode"]["test_mode"] is None and shown["gateway_mode"]["banner"] == ""
    assert shown["gateway_mode"]["unknown"].startswith("Couldn't read whether the card "
                                                      "processor is in Test Mode")
    assert pay(api, fcc, billing).status_code == 200
    payment = ClientPayment.all_objects.get(invoice=billing)
    assert payment.is_test is False
    assert FinanceEntry.all_objects.filter(client_payment=payment).exists()


@pytest.mark.django_db
def test_the_sandbox_switch_reads_a_sandbox_account_as_live_on_the_laptop_only(stub_gateway):
    sandbox = gw.Account(environment="sandbox", private_key="a", public_key="b", label="t")
    live = gw.Account(environment="live", private_key="a", public_key="b", label="t")
    stub_gateway.test_mode_on = True
    with override_settings(NMI_SANDBOX_IGNORE_TEST_MODE=True):
        assert gateway_mode.read(sandbox) == (False, "")
        assert gateway_mode.read(live) == (True, "")      # never a live account's
    assert gateway_mode.read(sandbox) == (True, "")


@pytest.mark.django_db
def test_with_real_calls_off_in_production_it_cannot_be_read(settings, stub_gateway):
    settings.APP_ENVIRONMENT = "production"
    account = gw.Account(environment="live", private_key="a", public_key="b", label="t")
    state, why = gateway_mode.read(account)
    assert state is None and "off" in why


# --------------------------------------------------- a payment in Test Mode

@pytest.fixture
def test_mode(billing, ff, api, stub_gateway):  # noqa: F811
    stub_gateway.test_mode_on = True
    return billing


@pytest.mark.django_db
def test_a_payment_in_test_mode_is_a_test_and_never_in_the_books(
        test_mode, fcc, ff, api, stub_gateway, seeded_tenant):
    assert pay(api, fcc, test_mode).status_code == 200
    attempt = PaymentAttempt.all_objects.get(invoice=test_mode)
    payment = ClientPayment.all_objects.get(invoice=test_mode)
    assert attempt.is_test and payment.is_test
    # Read before the sale, every time.
    names = [c[0] for c in stub_gateway.calls]
    assert names.index("test_mode") < names.index("sale")
    assert not FinanceEntry.all_objects.filter(client_payment=payment).exists()
    test_mode.refresh_from_db()
    # The invoice itself is paid, so the payer's pages read as they will...
    assert test_mode.status == S.PAID and test_mode.test_paid_cents == test_mode.total_cents
    # ...and nowhere else is it: the totals, the forecast and the KPI feed.
    with tenant_context(seeded_tenant.pk):
        totals = services.totals(ClientInvoice.all_objects.filter(tenant=seeded_tenant))
        known, _ = forecast._known(seeded_tenant, timezone.localdate(),
                                   date(2027, 12, 31), {})
        money = practice_kpis._invoice_money(seeded_tenant, timezone.now())
    assert totals["paid_cents"] == 0 and totals["outstanding_cents"] == test_mode.total_cents
    assert any(line["amount_cents"] == test_mode.total_cents for line in known)
    assert money[test_mode.pk][1] == 0
    # The pay page, the receipt and the owner's notice say no money moved.
    receipt = OutboxMessage.all_objects.get(producer="payment_receipt")
    assert "test mode: no real money moved" in receipt.body_text
    page = api.as_(ff).get(f"/api/invoices/{test_mode.pk}/").json()
    assert page["payments"][0]["is_test"] is True and page["test_paid_cents"] > 0


@pytest.mark.django_db
def test_a_live_account_in_test_mode_says_test_mode_to_the_payer(billing, fcc, api,  # noqa: F811
                                                                 stub_gateway, seeded_tenant):
    PaymentAccount.all_objects.filter(tenant=seeded_tenant).update(environment="live",
                                                                   gateway_test_mode=False)
    assert card_payments.is_test_mode(seeded_tenant) is False
    PaymentAccount.all_objects.filter(tenant=seeded_tenant).update(gateway_test_mode=True)
    assert card_payments.is_test_mode(seeded_tenant) is True
    row = api.as_(fcc).get("/api/portal-invoices/").json()[0]
    assert row["test_mode"] is True


@pytest.mark.django_db
def test_a_card_saved_in_test_mode_is_a_test_card(billing, fcc, api, stub_gateway):  # noqa: F811
    stub_gateway.test_mode_on = True
    assert save_client_card(api, fcc).status_code == 200
    card = ClientPaymentMethod.all_objects.get()
    assert card.is_test
    assert api.as_(fcc).get("/api/portal-autopay/").json()["card"]["is_test"] is True


# ------------------------------------------------- refunds and Test Mode

@pytest.mark.django_db
def test_a_test_payment_is_given_back_only_while_in_test_mode_and_never_booked(
        test_mode, fcc, ff, api, stub_gateway):
    assert pay(api, fcc, test_mode).status_code == 200
    payment = ClientPayment.all_objects.get(invoice=test_mode)
    url = f"/api/invoices/{test_mode.pk}/refund/"
    body = {"payment": str(payment.pk), "amount_cents": 1000, "reason": "Trying it."}
    done = post(api, ff, url, body)
    assert done.status_code == 200, done.content
    refund = CardRefund.all_objects.get()
    assert refund.is_test and "(a test: no money moved)" in done.json()["message"]
    assert not FinanceEntry.all_objects.filter(client_refund=refund).exists()
    test_mode.refresh_from_db()
    assert test_mode.paid_cents == test_mode.test_paid_cents == test_mode.total_cents - 1000
    # Back in live mode, a test payment has nothing to give back.
    stub_gateway.test_mode_on = False
    refused = post(api, ff, url, body)
    assert refused.status_code == 409 and refused.json()["detail"] == refunds.TEST_IN_LIVE_MODE


@pytest.mark.django_db
def test_a_real_payment_is_not_given_back_while_in_test_mode(billing, fcc, ff, api,  # noqa: F811
                                                            stub_gateway):
    assert pay(api, fcc, billing).status_code == 200
    payment = ClientPayment.all_objects.get(invoice=billing)
    stub_gateway.test_mode_on = True
    refused = post(api, ff, f"/api/invoices/{billing.pk}/refund/",
                   {"payment": str(payment.pk), "amount_cents": 1000, "reason": "x"})
    assert refused.status_code == 409 and refused.json()["detail"] == refunds.REAL_IN_TEST_MODE
    assert not CardRefund.all_objects.exists()
    assert not [c for c in stub_gateway.calls if c[0] in ("refund", "void")]


# ------------------------------------------------- clearing test payments

def clear(api, who, choice):
    return post(api, who, "/api/payment-account/clear-test-payments/", {"invoices": choice})


@pytest.fixture
def two_test_payments(test_mode, fcc, ff, api, stub_gateway):
    """Two invoices paid in Test Mode, one with a test refund, and a test
    card on file with auto-pay on."""
    from .test_card_payments import ContactEmailFactory, ContactFactory  # noqa: F401
    from .test_client_invoicing import sent

    assert pay(api, fcc, test_mode).status_code == 200
    contact = ClientInvoice.all_objects.get(pk=test_mode.pk).contact
    second = ClientInvoice.all_objects.get(pk=sent(api, ff, fcc.client_company, contact)["id"])
    assert pay(api, fcc, second, token="tok-2").status_code == 200
    first_payment = ClientPayment.all_objects.get(invoice=test_mode)
    assert post(api, ff, f"/api/invoices/{test_mode.pk}/refund/",
                {"payment": str(first_payment.pk), "amount_cents": 500,
                 "reason": "Trying it."}).status_code == 200
    assert save_client_card(api, fcc, token="tok-card").status_code == 200
    assert turn_on(api, fcc).status_code == 200
    return test_mode, second


@pytest.mark.django_db
def test_clear_test_payments_waits_for_live_mode(two_test_payments, ff, api, stub_gateway,
                                                 seeded_tenant):
    summary = account_state(api, ff)["test_payments"]
    assert (summary["payments"], summary["cards"], summary["can_clear"]) == (2, 1, False)
    still = clear(api, ff, "reopen")
    assert still.status_code == 409 and still.json()["detail"] == testmode.STILL_TEST
    stub_gateway.test_mode_unreadable = True
    assert clear(api, ff, "reopen").status_code == 503
    assert ClientPayment.all_objects.filter(removed_at__isnull=True).count() == 2


@pytest.mark.django_db
def test_clear_test_payments_reopens_and_deletes_the_test_card(two_test_payments, ff, api,
                                                               stub_gateway, seeded_tenant):
    first, second = two_test_payments
    stub_gateway.test_mode_on = False
    assert press_test_connection(api, ff).json()["test_payments"]["can_clear"] is True
    response = clear(api, ff, "reopen")
    assert response.status_code == 200, response.content
    done = response.json()["cleared"]
    assert (done["payments"], done["reopened"], done["voided"], done["cards"]) == (2, 2, 0, 1)
    for invoice in (first, second):
        invoice.refresh_from_db()
        assert (invoice.status, invoice.paid_cents, invoice.test_paid_cents) == (S.SENT, 0, 0)
    assert not ClientPayment.all_objects.filter(removed_at__isnull=True).exists()
    assert CardRefund.all_objects.get().cleared_at is not None
    card = ClientPaymentMethod.all_objects.get()
    assert card.removed_at is not None and card.vault_id not in stub_gateway.vault
    assert autopay.standing_consent(card.client_company) is None
    assert not FinanceEntry.all_objects.exists()       # there was nothing to take out
    assert response.json()["test_payments"]["payments"] == 0


@pytest.mark.django_db
def test_clear_test_payments_can_void_their_invoices(two_test_payments, ff, api, stub_gateway):
    first, second = two_test_payments
    stub_gateway.test_mode_on = False
    assert clear(api, ff, "void").json()["cleared"]["voided"] == 2
    for invoice in (first, second):
        invoice.refresh_from_db()
        assert invoice.status == S.VOID and invoice.void_reason.startswith("Test payments")
    assert clear(api, ff, "later").status_code == 400


@pytest.mark.django_db
def test_an_invoice_with_real_money_too_is_reopened_never_voided(billing, fcc, ff, api,  # noqa: F811
                                                                 stub_gateway):
    # A real part payment by hand, then the rest in Test Mode.
    with tenant_context(billing.tenant_id):
        services.record_payment(billing, actor=ff.user, amount_cents=100000,
                                paid_on=timezone.localdate(), method="check")
    stub_gateway.test_mode_on = True
    assert pay(api, fcc, billing).status_code == 200
    stub_gateway.test_mode_on = False
    assert clear(api, ff, "void").json()["cleared"]["voided"] == 0
    billing.refresh_from_db()
    assert (billing.status, billing.paid_cents, billing.test_paid_cents) == (
        S.PARTIALLY_PAID, 100000, 0)


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["CF", "VA", "FCC"])
def test_role_boundaries_only_the_practice_owner_clears(role, two_test_payments, api,
                                                       seeded_tenant, fcc, stub_gateway):
    who = fcc if role == "FCC" else _member(seeded_tenant, role)
    stub_gateway.test_mode_on = False
    assert clear(api, who, "reopen").status_code in (403, 404)
    assert ClientPayment.all_objects.filter(removed_at__isnull=True).count() == 2


@pytest.mark.django_db
def test_tenant_isolation_clearing_touches_only_the_practices_own(two_test_payments, tenant_b,
                                                                  api, stub_gateway):
    other = _member(tenant_b, "FF")
    stub_gateway.test_mode_on = False
    response = clear(api, other, "reopen")
    # Practice B has no account: refused; and A's test payments are untouched.
    assert response.status_code in (409, 503)
    assert ClientPayment.all_objects.filter(removed_at__isnull=True).count() == 2


# -------------------------------------------- the platform's account

@pytest.mark.django_db
def test_a_subscription_charge_in_test_mode_is_a_test_and_cleared_on_practices(
        seeded_tenant, ff, api, stub_gateway, platform_practice):
    from .test_subscriptions import save_card as save_subscription_card

    stub_gateway.test_mode_on = True
    assert save_subscription_card(api, ff).status_code == 200
    row = PracticeSubscription.all_objects.get(tenant=seeded_tenant)
    assert row.card_is_test
    run_subscription(seeded_tenant, next_first())
    invoice = PracticeInvoice.all_objects.get(tenant=seeded_tenant)
    assert invoice.status == PracticeInvoice.Status.PAID and invoice.is_test
    receipt = OutboxMessage.all_objects.get(producer="subscription_receipt")
    assert "Test mode: no real money moved." in receipt.body_text
    assert api.as_(ff).get("/api/subscription/").json()["invoices"][0]["is_test"] is True

    area = practices(api, platform_practice)
    state = area.get("/api/platform/card-payments/").json()
    assert state["gateway_mode"]["banner"] == BANNER
    assert state["test_payments"]["payments"] == 1 and not state["test_payments"]["can_clear"]
    still = area.post("/api/platform/card-payments/clear-test-payments/",
                      json.dumps({"invoices": "reopen"}), content_type="application/json")
    assert still.status_code == 409
    stub_gateway.test_mode_on = False
    read = area.post("/api/platform/card-payments/read-test-mode/", "{}",
                     content_type="application/json").json()
    assert read["gateway_mode"]["test_mode"] is False and read["test_payments"]["can_clear"]
    done = area.post("/api/platform/card-payments/clear-test-payments/",
                     json.dumps({"invoices": "reopen"}), content_type="application/json")
    assert done.status_code == 200, done.content
    invoice.refresh_from_db()
    assert invoice.status == PracticeInvoice.Status.OPEN and invoice.amount_paid_cents == 0
    assert invoice.charge_tries == 0 and not invoice.is_test
    row.refresh_from_db()
    assert row.nmi_vault_id == "" and row.status == PracticeSubscription.Status.NEEDS_CARD
    assert not stub_gateway.vault
    # A practice owner never reaches the platform's.
    assert post(api, ff, "/api/platform/card-payments/clear-test-payments/",
                {"invoices": "reopen"}).status_code == 403


@pytest.mark.django_db
def test_subscriptions_carry_on_as_before_when_test_mode_cannot_be_read(
        carded, platform_practice, stub_gateway):
    stub_gateway.test_mode_unreadable = True
    run_subscription(carded, next_first())
    invoice = PracticeInvoice.all_objects.get(tenant=carded)
    assert invoice.status == PracticeInvoice.Status.PAID and not invoice.is_test
    assert gateway_mode.platform_state()["unknown"]
