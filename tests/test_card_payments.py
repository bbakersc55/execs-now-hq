"""P4 part 2: paying an invoice by card in the portal (`docs/p4_billing.md` §3.4).

Every test runs on the stub gateway (`conftest.stub_gateway`): no test
reaches NMI. Its sales, refusals and lost answers stand for NMI's, as the
sandbox showed them on 2026-10-21.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.billing import card_payments, payment_accounts
from apps.billing.models import ClientInvoice, ClientPayment, PaymentAttempt
from apps.crm.models import OutboxMessage
from apps.finance.models import FinanceEntry
from apps.tenancy.context import acting_context, tenant_context

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import ContactEmailFactory, ContactFactory
from .test_client_invoicing import ready_to_bill  # noqa: F401  (a fixture)
from .test_client_invoicing import a_client, post, sent

PRIVATE, PUBLIC = "practice-private-0000aaaa", "practice-public-1111bbbb"
A = PaymentAttempt.Status


@pytest.fixture(autouse=True)
def _after_commit_now(monkeypatch):
    """The receipt and the notice are sent once the payment commits. A test
    runs inside one transaction that never commits, so they run at once."""
    monkeypatch.setattr(card_payments.transaction, "on_commit", lambda fn, **kw: fn())


def connect(tenant, ff):
    with tenant_context(tenant.pk):
        payment_accounts.connect(tenant, environment="sandbox", private_key=PRIVATE,
                                 public_key=PUBLIC, actor=ff.user)


@pytest.fixture
def billing(ready_to_bill, ff, fcc, api):  # noqa: F811
    """A practice whose NMI account is ready, and a sent invoice of $6,800.00
    to the client owner's company."""
    connect(ready_to_bill, ff)
    contact = ContactFactory(tenant=ready_to_bill, first_name="Dana", last_name="Reyes",
                             company=fcc.client_company)
    ContactEmailFactory(tenant=ready_to_bill, contact=contact, is_primary=True,
                        address="dana@client.invalid")
    invoice = sent(api, ff, fcc.client_company, contact)
    return ClientInvoice.all_objects.get(pk=invoice["id"])


def pay(api, who, invoice, token="tok-1"):
    return post(api, who, f"/api/portal-invoices/{invoice.pk}/pay/", {"payment_token": token})


def portal_row(api, who, invoice):
    rows = api.as_(who).get("/api/portal-invoices/").json()
    return next(r for r in rows if r["id"] == str(invoice.pk))


def sales(stub):
    return [c for c in stub.calls if c[0] == "sale"]


def producers(tenant):
    return list(OutboxMessage.all_objects.filter(
        tenant=tenant, producer__in=["payment_receipt", "payment_notice"]).values_list(
            "producer", "to_address", "state"))


# ------------------------------------------------------------ Pay, and when

@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FCC", "ECC"])
def test_both_client_roles_see_pay_and_test_mode(role, billing, fcc, seeded_tenant, api):
    who = fcc if role == "FCC" else _member(seeded_tenant, "ECC", company=fcc.client_company)
    row = portal_row(api, who, billing)
    assert row["can_pay"] is True and row["test_mode"] is True
    config = api.as_(who).get(f"/api/portal-invoices/{billing.pk}/pay/").json()
    # The practice's own public key, at runtime; never the platform's.
    assert config == {"public_key": PUBLIC, "test_mode": True,
                      "amount_cents": billing.balance_cents, "number": billing.number}
    assert PRIVATE not in json.dumps(config)


@pytest.mark.django_db
def test_no_pay_until_the_practices_account_is_ready(ready_to_bill, ff, fcc, api):  # noqa: F811
    contact = ContactFactory(tenant=ready_to_bill, company=fcc.client_company)
    ContactEmailFactory(tenant=ready_to_bill, contact=contact, is_primary=True,
                        address="x@client.invalid")
    invoice = ClientInvoice.all_objects.get(pk=sent(api, ff, fcc.client_company,
                                                    contact)["id"])
    assert portal_row(api, fcc, invoice)["can_pay"] is False
    assert api.as_(fcc).get(f"/api/portal-invoices/{invoice.pk}/pay/").status_code == 409
    assert pay(api, fcc, invoice).status_code == 409


# ------------------------------------------------------------- approved

@pytest.mark.django_db
def test_a_card_payment_pays_the_balance_on_the_practices_own_account(
        billing, fcc, ff, seeded_tenant, api, stub_gateway):
    response = pay(api, fcc, billing)
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["status"] == "approved" and body["balance_cents"] == 0
    assert body["invoice_status"] == "paid" and "was paid on invoice" in body["message"]

    [sale] = sales(stub_gateway)
    attempt = PaymentAttempt.all_objects.get(invoice=billing)
    # The practice's account (its label is its id), our reference, the balance.
    assert sale[1] == str(seeded_tenant.pk)
    assert sale[2]["reference"] == str(attempt.pk)
    assert sale[2]["amount_cents"] == 680000 and sale[2]["payment_token"] == "tok-1"

    payment = ClientPayment.all_objects.get(invoice=billing)
    assert (payment.method, payment.amount_cents, payment.recorded_by_id) == (
        "card", 680000, fcc.user_id)
    assert payment.nmi_transaction_id == attempt.nmi_transaction_id != ""
    assert attempt.status == A.APPROVED and attempt.payment_id == payment.pk
    assert (attempt.card_type, attempt.last4) == ("Visa", "1111")
    # Into the books exactly as a payment recorded by hand.
    assert FinanceEntry.all_objects.filter(client_payment=payment).exists()
    billing.refresh_from_db()
    assert billing.status == "paid" and billing.paid_cents == 680000

    sent_mail = producers(seeded_tenant)
    assert ("payment_receipt", fcc.user.email, "sent") in sent_mail
    assert ("payment_notice", ff.user.email, "sent") in sent_mail
    receipt = OutboxMessage.all_objects.get(producer="payment_receipt")
    assert "Transaction: " + attempt.nmi_transaction_id in receipt.body_text
    assert "test mode" in receipt.body_text and receipt.thread.is_financial
    assert portal_row(api, fcc, billing)["can_pay"] is False


@pytest.mark.django_db
def test_a_partly_paid_invoice_is_paid_in_full_by_card(billing, fcc, ff, api, stub_gateway):
    from apps.billing import services

    with tenant_context(billing.tenant_id):
        services.record_payment(billing, actor=ff.user, amount_cents=100000,
                                paid_on=timezone.localdate(), method="check")
    assert portal_row(api, fcc, billing)["can_pay"] is True
    assert pay(api, fcc, billing).json()["status"] == "approved"
    assert sales(stub_gateway)[0][2]["amount_cents"] == 580000


# ------------------------------------------------------------- declined

@pytest.mark.django_db
def test_a_decline_keeps_nmis_text_and_changes_nothing(
        ready_to_bill, ff, fcc, api, stub_gateway):  # noqa: F811
    connect(ready_to_bill, ff)
    company, contact = fcc.client_company, ContactFactory(tenant=ready_to_bill,
                                                          company=fcc.client_company)
    ContactEmailFactory(tenant=ready_to_bill, contact=contact, is_primary=True,
                        address="y@client.invalid")
    small = ClientInvoice.all_objects.get(pk=sent(api, ff, company, contact, lines=[
        {"description": "Postage", "quantity": "1", "unit_price_cents": 50}])["id"])
    body = pay(api, fcc, small).json()
    assert body["status"] == "declined" and "declined, and nothing was charged" in body["message"]
    attempt = PaymentAttempt.all_objects.get(invoice=small)
    assert (attempt.response_code, attempt.response_text) == ("200", "DECLINE")
    assert not ClientPayment.all_objects.filter(invoice=small).exists()
    assert producers(ready_to_bill) == []
    assert portal_row(api, fcc, small)["can_pay"] is True


@pytest.mark.django_db
def test_a_duplicate_gets_a_plain_message_and_no_second_attempt(
        billing, fcc, api, stub_gateway):
    stub_gateway.refuse_next = ("E_DUPLICATE", "Duplicate transaction")
    body = pay(api, fcc, billing).json()
    assert body["status"] == "declined" and body["message"] == card_payments.DUPLICATE_MESSAGE
    assert len(sales(stub_gateway)) == 1
    attempt = PaymentAttempt.all_objects.get(invoice=billing)
    assert (attempt.status, attempt.response_code) == (A.DECLINED, "E_DUPLICATE")
    assert not ClientPayment.all_objects.filter(invoice=billing).exists()


# ------------------------------------------------------- the lost answer

@pytest.mark.django_db
def test_a_lost_answer_is_unknown_blocks_paying_again_and_is_settled_once(
        billing, fcc, ff, seeded_tenant, api, stub_gateway):
    stub_gateway.lose_next_answer = True  # charged at NMI; the answer never came
    body = pay(api, fcc, billing).json()
    assert body["status"] == "unknown" and body["message"] == card_payments.UNKNOWN_MESSAGE
    assert not ClientPayment.all_objects.filter(invoice=billing).exists()
    row = portal_row(api, fcc, billing)
    assert row["can_pay"] is False and row["payment_in_progress"] is True
    again = pay(api, fcc, billing, token="tok-2")
    assert again.status_code == 409 and len(sales(stub_gateway)) == 1

    with tenant_context(seeded_tenant.pk):
        assert card_payments.resolve_unknown(seeded_tenant) == 1
        assert card_payments.resolve_unknown(seeded_tenant) == 0
    attempt = PaymentAttempt.all_objects.get(invoice=billing)
    assert attempt.status == A.APPROVED and attempt.looked_up_at is not None
    assert ClientPayment.all_objects.filter(invoice=billing).count() == 1
    assert len([p for p in producers(seeded_tenant) if p[0] == "payment_receipt"]) == 1
    billing.refresh_from_db()
    assert billing.status == "paid"


@pytest.mark.django_db
def test_no_sale_at_nmi_is_failed_after_an_hour(billing, fcc, seeded_tenant, api,
                                                 stub_gateway):
    stub_gateway.lose_next_answer = "uncharged"
    assert pay(api, fcc, billing).json()["status"] == "unknown"
    with tenant_context(seeded_tenant.pk):
        assert card_payments.resolve_unknown(seeded_tenant) == 0
        assert PaymentAttempt.all_objects.get(invoice=billing).status == A.UNKNOWN
        later = timezone.now() + timedelta(hours=2)
        assert card_payments.resolve_unknown(seeded_tenant, now=later) == 1
    assert PaymentAttempt.all_objects.get(invoice=billing).status == A.FAILED
    assert portal_row(api, fcc, billing)["can_pay"] is True


@pytest.mark.django_db
def test_nmi_not_answering_the_lookup_leaves_it_unknown(billing, fcc, seeded_tenant, api,
                                                         stub_gateway):
    stub_gateway.lose_next_answer = True
    pay(api, fcc, billing)
    stub_gateway.lookup_unreachable = True
    with tenant_context(seeded_tenant.pk):
        later = timezone.now() + timedelta(hours=2)
        assert card_payments.resolve_unknown(seeded_tenant, now=later) == 0
    assert PaymentAttempt.all_objects.get(invoice=billing).status == A.UNKNOWN


@pytest.mark.django_db
def test_a_stalled_pending_attempt_is_looked_up_too(billing, fcc, seeded_tenant,
                                                    stub_gateway):
    with tenant_context(seeded_tenant.pk):
        attempt = card_payments.start(billing, payer=fcc.user)
        later = timezone.now() + timedelta(minutes=10)
        assert card_payments.resolve_unknown(seeded_tenant, now=later + timedelta(hours=1)) == 1
    assert PaymentAttempt.all_objects.get(pk=attempt.pk).status == A.FAILED


@pytest.mark.django_db
def test_a_charge_the_invoice_can_no_longer_take_is_flagged_to_the_owner(
        billing, fcc, ff, seeded_tenant, api, stub_gateway):
    from apps.billing import services

    stub_gateway.lose_next_answer = True
    pay(api, fcc, billing)
    with tenant_context(seeded_tenant.pk):
        services.void(billing, actor=ff.user, reason="Sent to the wrong company")
        card_payments.resolve_unknown(seeded_tenant)
    attempt = PaymentAttempt.all_objects.get(invoice=billing)
    assert attempt.status == A.APPROVED and attempt.payment_id is None
    assert "not recorded on the invoice" in attempt.problem
    mail = producers(seeded_tenant)
    assert [p[0] for p in mail] == ["payment_notice"]
    notice = OutboxMessage.all_objects.get(producer="payment_notice")
    assert "Refund it in NMI" in notice.body_text


# ------------------------------------------------- one in flight, guarded

@pytest.mark.django_db
def test_the_database_holds_one_in_flight_per_invoice(billing, fcc, seeded_tenant):
    with tenant_context(seeded_tenant.pk):
        card_payments.start(billing, payer=fcc.user)
        with pytest.raises(card_payments.PaymentRefused):
            card_payments.start(billing, payer=fcc.user)
        with pytest.raises(IntegrityError):
            PaymentAttempt.all_objects.create(tenant=seeded_tenant, invoice=billing,
                                              amount_cents=100, status=A.UNKNOWN)


@pytest.mark.django_db
def test_nothing_is_paid_while_acting_as_the_client(billing, fcc, ff, seeded_tenant,
                                                    stub_gateway):
    with tenant_context(seeded_tenant.pk), acting_context(ff.user_id, fcc.user_id):
        with pytest.raises(card_payments.PaymentRefused, match="acting"):
            card_payments.pay(billing, payer=fcc.user, payment_token="tok-1")
    assert sales(stub_gateway) == []


@pytest.mark.django_db
def test_an_empty_token_is_refused_before_anything(billing, fcc, api, stub_gateway):
    assert post(api, fcc, f"/api/portal-invoices/{billing.pk}/pay/", {}).status_code == 400
    assert stub_gateway.calls[-1][0] != "sale" and not PaymentAttempt.all_objects.exists()


# ---------------------------------------------- role boundaries, isolation

@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FF", "CF", "VA"])
def test_practice_staff_never_pay_through_the_portal(role, billing, seeded_tenant, api,
                                                     stub_gateway):
    who = _member(seeded_tenant, role)
    assert pay(api, who, billing).status_code == 404
    assert api.as_(who).get(f"/api/portal-invoices/{billing.pk}/pay/").status_code == 404
    assert sales(stub_gateway) == []


@pytest.mark.django_db
def test_another_companys_client_cannot_see_or_pay_it(billing, seeded_tenant, api,
                                                      stub_gateway):
    other_company, _ = a_client(seeded_tenant, name="Other Co")
    other = _member(seeded_tenant, "FCC", company=other_company)
    assert pay(api, other, billing).status_code == 404
    assert api.as_(other).get(f"/api/portal-invoices/{billing.pk}/pay/").status_code == 404
    assert sales(stub_gateway) == []


@pytest.mark.django_db
def test_another_practices_client_cannot_pay_it(billing, tenant_b, api, stub_gateway):
    company, _ = a_client(tenant_b, name="Elsewhere LLC")
    stranger = _member(tenant_b, "FCC", company=company)
    assert pay(api, stranger, billing).status_code == 404
    assert sales(stub_gateway) == []


@pytest.mark.django_db
def test_receipts_and_notices_never_reach_an_assistant(billing, fcc, seeded_tenant, api):
    pay(api, fcc, billing)
    va = _member(seeded_tenant, "VA")
    listing = api.as_(va).get("/api/outbox/")
    assert listing.status_code == 200
    text = listing.content.decode()
    assert "Receipt:" not in text and "Card payment:" not in text


@pytest.mark.django_db
def test_a_receipt_that_cannot_go_never_undoes_the_payment(billing, fcc, api, monkeypatch):
    from apps.crm.services import outbox
    from apps.crm.services.transport import TransportUnavailable

    def down(**kwargs):
        raise TransportUnavailable("Gmail is not connected.")

    monkeypatch.setattr(outbox, "create_message", down)
    body = pay(api, fcc, billing).json()
    assert body["status"] == "approved"
    assert ClientPayment.all_objects.filter(invoice=billing).count() == 1


@pytest.mark.django_db
def test_the_proof_setup_refuses_anywhere_but_its_own_sandbox_database(settings):
    from django.core.management import CommandError, call_command

    settings.NMI_LIVE_CALLS = True  # still refused: under test, and not *_nmi_proof
    with pytest.raises(CommandError, match="_nmi_proof"):
        call_command("nmi_proof_setup")
