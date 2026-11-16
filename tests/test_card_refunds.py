"""Void and refund from the app (2026-11-16, `docs/p4_billing.md` §11).

Every test runs on the stub gateway (`conftest.stub_gateway`), which behaves
as NMI's sandbox did on 2026-11-16: a sale pending settlement voids, a voided
sale cannot be refunded nor a refunded one voided, a refund is its own
transaction pointing back to the sale, and never more than the sale.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.billing import readback, refunds, services, tasks
from apps.billing.models import (
    CardPaymentHold, CardRefund, ClientInvoice, ClientPayment, NmiEvent, PaymentAttempt,
    PracticeInvoice,
)
from apps.crm.models import OutboxMessage
from apps.finance.models import FinanceEntry
from apps.tenancy.context import tenant_context
from apps.tenancy.models import AuditEvent

from . import registry_config  # noqa: F401
from .conftest import _member
from .test_card_payments import _after_commit_now  # noqa: F401  (autouse)
from .test_card_payments import billing, pay  # noqa: F401  (a fixture)
from .test_client_invoicing import ready_to_bill  # noqa: F401  (a fixture)
from .test_client_invoicing import post
from .test_platform_practices import practices
from .test_subscriptions import _commit_now  # noqa: F401  (autouse)
from .test_subscriptions import carded, next_first, platform_practice  # noqa: F401
from .test_subscriptions import run as run_subscription

R = CardRefund
S = ClientInvoice.Status


@pytest.fixture
def paid(billing, fcc, api):  # noqa: F811
    """The $6,800.00 invoice, paid by card in the portal."""
    assert pay(api, fcc, billing).status_code == 200
    billing.refresh_from_db()
    assert billing.status == S.PAID
    return ClientPayment.all_objects.get(invoice=billing)


def give_back(api, who, payment, amount, reason="Agreed with the client.", **more):
    return post(api, who, f"/api/invoices/{payment.invoice_id}/refund/",
                {"payment": str(payment.pk), "amount_cents": amount, "reason": reason, **more})


def entries(payment):
    return FinanceEntry.all_objects.filter(client_payment=payment, removed_at__isnull=True)


def calls(stub, *names):
    return [c for c in stub.calls if c[0] in names]


# ----------------------------------------------------------- void or refund

@pytest.mark.django_db
def test_a_full_refund_before_it_settles_is_a_void_and_takes_the_entry_out(
        paid, ff, fcc, api, stub_gateway, seeded_tenant):
    assert entries(paid).exists()
    page = api.as_(ff).get(f"/api/invoices/{paid.invoice_id}/").json()
    [row] = page["payments"]
    assert row["can_refund"] and row["refundable_cents"] == 680000 and row["can_void_invoice"]

    response = give_back(api, ff, paid, 680000)
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["message"].startswith("Cancelled before it settled")
    refund = R.all_objects.get(payment=paid)
    assert (refund.kind, refund.status, refund.amount_cents) == (R.Kind.VOID, R.Status.DONE,
                                                                 680000)
    # The processor was asked the sale's state, then the void went: nothing else.
    assert [c[0] for c in calls(stub_gateway, "get_transaction", "void", "refund")] == [
        "get_transaction", "void"]
    assert refund.nmi_transaction_id == paid.nmi_transaction_id == refund.against_transaction_id
    # The books: the payment's own entry is taken out, and no refund entry made.
    assert not entries(paid).exists()
    assert not FinanceEntry.all_objects.filter(client_refund=refund).exists()
    invoice = ClientInvoice.all_objects.get(pk=paid.invoice_id)
    assert (invoice.status, invoice.paid_cents) == (S.SENT, 0)
    assert body["status"] == S.SENT and body["refunds"][0]["kind"] == "void"
    receipt = OutboxMessage.all_objects.get(producer="payment_receipt", source_type="card_refund")
    assert receipt.to_address == fcc.user.email and "cancelled your card payment" in \
        receipt.body_text
    notice = OutboxMessage.all_objects.get(producer="payment_notice", source_type="card_refund")
    assert notice.to_address == ff.user.email and "Agreed with the client." in notice.body_text
    assert AuditEvent.all_objects.filter(verb="billing.payment_cancelled").exists()


@pytest.mark.django_db
def test_a_settled_payment_is_refunded_with_an_entry_of_its_own(paid, ff, api, stub_gateway):
    stub_gateway.settle(paid.nmi_transaction_id)
    response = give_back(api, ff, paid, 680000)
    assert response.status_code == 200, response.content
    refund = R.all_objects.get(payment=paid)
    assert refund.kind == R.Kind.REFUND and refund.nmi_transaction_id not in (
        "", paid.nmi_transaction_id)
    assert entries(paid).exists()          # the payment stays in the books
    [entry] = FinanceEntry.all_objects.filter(client_refund=refund)
    assert (entry.kind, entry.direction, entry.amount_cents) == ("income", "out", 680000)
    assert entry.on_date == timezone.localdate() and entry.source == "invoice"
    assert response.json()["message"] == "Refunded $6,800.00."


@pytest.mark.django_db
def test_a_part_then_the_rest_both_refunds_and_the_invoice_reopens_by_each(
        paid, ff, api, stub_gateway):
    first = give_back(api, ff, paid, 100000)
    assert first.status_code == 200 and first.json()["status"] == S.PARTIALLY_PAID
    assert R.all_objects.get(payment=paid).kind == R.Kind.REFUND   # a part is never a void
    invoice = ClientInvoice.all_objects.get(pk=paid.invoice_id)
    assert invoice.paid_cents == 580000 and invoice.balance_cents == 100000
    assert refunds.refundable_cents(paid) == 580000
    rest = give_back(api, ff, paid, 580000)
    assert rest.status_code == 200
    kinds = list(R.all_objects.filter(payment=paid).values_list("kind", flat=True))
    assert kinds == ["refund", "refund"]   # refunded before, so never voided
    invoice.refresh_from_db()
    assert (invoice.status, invoice.paid_cents) == (S.SENT, 0)
    assert refunds.payment_options(paid)["can_refund"] is False
    assert sum(FinanceEntry.all_objects.filter(client_refund__payment=paid)
               .values_list("amount_cents", flat=True)) == 680000


@pytest.mark.django_db
def test_never_more_than_was_paid(paid, ff, api, stub_gateway):
    assert give_back(api, ff, paid, 680001).status_code == 400
    assert give_back(api, ff, paid, 0).status_code == 400
    assert give_back(api, ff, paid, 600000).status_code == 200
    over = give_back(api, ff, paid, 80001)
    assert over.status_code == 400 and "$800.00" in over.json()["detail"]
    assert R.all_objects.filter(payment=paid).count() == 1
    assert not calls(stub_gateway, "refund")[1:]   # the refused ones never left
    # The database refuses a refund for nothing.
    with pytest.raises(IntegrityError), transaction.atomic():
        R.all_objects.create(tenant_id=paid.tenant_id, payment=paid, invoice_id=paid.invoice_id,
                             kind="refund", amount_cents=0, reason="x",
                             against_transaction_id="1")


@pytest.mark.django_db
def test_a_reason_is_required_and_only_a_card_payment_the_app_took(paid, ff, api, billing):
    assert give_back(api, ff, paid, 1000, reason="  ").status_code == 400
    by_hand = ClientPayment.all_objects.create(
        tenant_id=paid.tenant_id, invoice=paid.invoice, amount_cents=1000,
        paid_on=timezone.localdate(), method="check")
    assert refunds.payment_options(by_hand)["can_refund"] is False
    assert give_back(api, ff, by_hand, 1000).status_code == 409


@pytest.mark.django_db
def test_one_at_a_time_and_a_lost_answer_is_found_by_the_lookup(
        paid, ff, api, stub_gateway, seeded_tenant):
    stub_gateway.settle(paid.nmi_transaction_id)
    stub_gateway.lose_next_refund_answer = True     # refunded, the answer lost
    lost = give_back(api, ff, paid, 50000)
    assert lost.status_code == 200 and "did not hear back" in lost.json()["message"]
    refund = R.all_objects.get(payment=paid)
    assert refund.status == R.Status.UNKNOWN and refund.nmi_transaction_id == ""
    # While it is unknown nothing else is given back on it, by the screen or by
    # the database.
    assert refunds.payment_options(paid)["can_refund"] is False
    assert give_back(api, ff, paid, 1000).status_code == 409
    with pytest.raises(IntegrityError), transaction.atomic():
        R.all_objects.create(tenant_id=paid.tenant_id, payment=paid,
                             invoice_id=paid.invoice_id, kind="refund", amount_cents=1,
                             reason="x", against_transaction_id="1", status="pending")
    assert len(calls(stub_gateway, "refund")) == 1
    # The ten-minute job finds it by our reference, and never refunds again.
    assert tasks.resolve_card_payments(str(seeded_tenant.pk)) == 1
    refund.refresh_from_db()
    assert refund.status == R.Status.DONE and refund.nmi_transaction_id
    assert len(calls(stub_gateway, "refund")) == 1
    assert FinanceEntry.all_objects.filter(client_refund=refund).exists()
    invoice = ClientInvoice.all_objects.get(pk=paid.invoice_id)
    assert invoice.paid_cents == 630000


@pytest.mark.django_db
def test_a_lost_answer_with_no_refund_at_the_processor_ends_as_not_done(
        paid, ff, api, stub_gateway, seeded_tenant):
    stub_gateway.settle(paid.nmi_transaction_id)
    stub_gateway.lose_next_refund_answer = "unsent"   # it never reached the processor
    give_back(api, ff, paid, 50000)
    refund = R.all_objects.get(payment=paid)
    assert tasks.resolve_card_payments(str(seeded_tenant.pk)) == 0   # too soon to say
    R.all_objects.filter(pk=refund.pk).update(created_at=timezone.now() - timedelta(hours=2))
    assert tasks.resolve_card_payments(str(seeded_tenant.pk)) == 1
    refund.refresh_from_db()
    assert refund.status == R.Status.FAILED and "nothing was given back" in refund.response_text
    invoice = ClientInvoice.all_objects.get(pk=paid.invoice_id)
    assert invoice.status == S.PAID and refunds.refundable_cents(paid) == 680000


@pytest.mark.django_db
def test_refused_by_the_processor_is_recorded_and_changes_nothing(paid, ff, api, stub_gateway):
    stub_gateway.refuse_next_refund = ("E_INVALID_TRANS_SPECIFIED",
                                       "Only transactions pending settlement can be voided")
    response = give_back(api, ff, paid, 680000)
    assert response.status_code == 200
    assert "try again: it will be refunded instead" in response.json()["message"]
    refund = R.all_objects.get(payment=paid)
    assert refund.status == R.Status.FAILED and refund.response_code == "E_INVALID_TRANS_SPECIFIED"
    assert entries(paid).exists()
    invoice = ClientInvoice.all_objects.get(pk=paid.invoice_id)
    assert invoice.status == S.PAID and refunds.refundable_cents(paid) == 680000
    assert not OutboxMessage.all_objects.filter(source_type="card_refund").exists()


@pytest.mark.django_db
def test_and_void_the_invoice_on_a_full_refund_only(paid, ff, api, stub_gateway):
    part = give_back(api, ff, paid, 1000, void_invoice=True)
    assert part.status_code == 400 and not R.all_objects.exists()
    whole = give_back(api, ff, paid, 680000, void_invoice=True)
    assert whole.status_code == 200, whole.content
    invoice = ClientInvoice.all_objects.get(pk=paid.invoice_id)
    assert invoice.status == S.VOID and invoice.pay_token_hash == ""
    assert invoice.void_reason.startswith("Refunded in full: ")
    assert "voided" in OutboxMessage.all_objects.get(
        producer="payment_receipt", source_type="card_refund").body_text


@pytest.mark.django_db
def test_a_refunded_payment_stays_on_its_invoice(paid, ff, api, stub_gateway):
    give_back(api, ff, paid, 1000)
    with pytest.raises(services.BillingError):
        services.remove_payment(paid, actor=ff.user, reason="Oops")


@pytest.mark.django_db
def test_refunds_still_go_while_card_payments_are_paused(paid, ff, api, stub_gateway):
    CardPaymentHold.objects.create(paused=True, changed_at=timezone.now())
    response = give_back(api, ff, paid, 680000)
    assert response.status_code == 200, response.content
    assert R.all_objects.get(payment=paid).status == R.Status.DONE


# ---------------------------------------------------- role and practice

@pytest.mark.django_db
def test_role_boundaries_only_the_practice_owner_gives_money_back(paid, cf, va, fcc, api,
                                                                  seeded_tenant, stub_gateway):
    ecc = _member(seeded_tenant, "ECC", company=fcc.client_company)
    assert give_back(api, cf, paid, 1000).status_code == 403
    assert give_back(api, va, paid, 1000).status_code == 403
    for client in (fcc, ecc):
        assert give_back(api, client, paid, 1000).status_code == 404
    page = api.as_(cf).get(f"/api/invoices/{paid.invoice_id}/")
    if page.status_code == 200:      # an associate sees no refund action
        assert "can_refund" not in page.json()["payments"][0]
    assert not R.all_objects.exists() and not calls(stub_gateway, "refund", "void")


@pytest.mark.django_db
def test_tenant_isolation_another_practice_reaches_no_payment(paid, tenant_b, api,
                                                              stub_gateway):
    other = _member(tenant_b, "FF")
    assert give_back(api, other, paid, 1000).status_code == 404
    # Its own invoice id with this payment: still not found.
    assert post(api, other, f"/api/nmi-events/{paid.pk}/record/", {}).status_code == 404
    assert not R.all_objects.exists()


# ------------------------------------------------------- the read-back

@pytest.mark.django_db
def test_the_read_back_knows_the_apps_own_voids_and_refunds(paid, ff, api, stub_gateway,
                                                           seeded_tenant):
    give_back(api, ff, paid, 100000)                 # a refund, then
    with tenant_context(seeded_tenant.pk):
        counts = readback.read_back(seeded_tenant)
    assert counts["flagged"] == counts["matched"] == 0
    assert not NmiEvent.all_objects.exists()


@pytest.mark.django_db
def test_a_void_made_here_is_not_flagged(paid, ff, api, stub_gateway, seeded_tenant):
    give_back(api, ff, paid, 680000)
    with tenant_context(seeded_tenant.pk):
        readback.read_back(seeded_tenant)
    assert not NmiEvent.all_objects.exists()


@pytest.mark.django_db
def test_one_made_in_the_portal_is_flagged_and_recorded_with_one_click(
        paid, ff, cf, api, stub_gateway, seeded_tenant):
    from .test_nmi_read_back import account_of

    at = timezone.now() - timedelta(days=1)
    stub_gateway.portal_refund(account_of(seeded_tenant), paid.nmi_transaction_id, 25000,
                               at=at, separate=True)
    with tenant_context(seeded_tenant.pk):
        readback.read_back(seeded_tenant)
    event = NmiEvent.all_objects.get()
    assert event.kind == "refund" and event.payment_id == paid.pk
    listed = api.as_(ff).get("/api/nmi-events/?open=1").json()
    assert listed[0]["can_record"] is True and listed[0]["recorded"] is False
    assert post(api, cf, f"/api/nmi-events/{event.pk}/record/", {}).status_code == 403

    response = post(api, ff, f"/api/nmi-events/{event.pk}/record/", {})
    assert response.status_code == 200, response.content
    assert response.json()["recorded"] is True and response.json()["reviewed"] is True
    refund = R.all_objects.get(payment=paid)
    assert (refund.source, refund.kind, refund.amount_cents, refund.nmi_transaction_id) == (
        R.Source.PORTAL, R.Kind.REFUND, 25000, event.transaction_id)
    # Its own entry, on the day it was made in the portal; no email to anyone.
    [entry] = FinanceEntry.all_objects.filter(client_refund=refund)
    assert entry.on_date == timezone.localtime(at).date() and entry.direction == "out"
    assert not OutboxMessage.all_objects.filter(source_type="card_refund").exists()
    invoice = ClientInvoice.all_objects.get(pk=paid.invoice_id)
    assert invoice.paid_cents == 655000 and invoice.status == S.PARTIALLY_PAID
    # Once only, and the next read-back adds nothing.
    assert post(api, ff, f"/api/nmi-events/{event.pk}/record/", {}).status_code == 409
    with tenant_context(seeded_tenant.pk):
        readback.read_back(seeded_tenant)
    assert NmiEvent.all_objects.count() == 1 and R.all_objects.count() == 1


@pytest.mark.django_db
def test_a_portal_void_is_recorded_by_taking_the_entry_out(paid, ff, api, stub_gateway,
                                                          seeded_tenant):
    from .test_nmi_read_back import account_of

    stub_gateway.portal_void(account_of(seeded_tenant), paid.nmi_transaction_id)
    with tenant_context(seeded_tenant.pk):
        readback.read_back(seeded_tenant)
    event = NmiEvent.all_objects.get(kind="void")
    assert readback.represent(event)["full"] is True
    assert post(api, ff, f"/api/nmi-events/{event.pk}/record/",
                {"void_invoice": True}).status_code == 200
    assert not entries(paid).exists()
    assert ClientInvoice.all_objects.get(pk=paid.invoice_id).status == S.VOID


# --------------------------------------------- a practice's subscription

@pytest.fixture
def charged(carded, platform_practice, stub_gateway):  # noqa: F811
    """The practice's first month, charged on the 1st: $20.00, paid."""
    run_subscription(carded, next_first())
    invoice = PracticeInvoice.all_objects.get(tenant=carded)
    assert invoice.status == PracticeInvoice.Status.PAID
    return invoice


def refund_charge(api, who, invoice, amount, **more):
    return practices(api, who).post(
        f"/api/platform/practices/{invoice.tenant_id}/charges/{invoice.pk}/refund",
        json.dumps({"amount_cents": amount, "reason": "Beta credit.", **more}),
        content_type="application/json")


@pytest.mark.django_db
def test_the_platform_owner_cancels_a_subscription_charge_before_it_settles(
        charged, platform_practice, ff, api, stub_gateway):
    row = practices(api, platform_practice).get("/api/platform/practices").json()
    shown = next(p for p in (row if isinstance(row, list) else row["practices"])
                 if p["subscription"]["charges"])
    assert shown["subscription"]["charges"][0]["can_refund"] is True
    response = refund_charge(api, platform_practice, charged, 2000)
    assert response.status_code == 200, response.content
    refund = R.all_objects.get(practice_invoice=charged)
    assert refund.kind == R.Kind.VOID and refund.tenant_id == charged.tenant_id
    [void] = calls(stub_gateway, "void")
    assert void[1] == "platform"        # the platform's account, never the practice's
    charged.refresh_from_db()
    assert charged.status == PracticeInvoice.Status.OPEN and charged.amount_paid_cents == 0
    sent_to = set(OutboxMessage.all_objects.filter(
        producer__in=["subscription_receipt", "subscription_notice"],
        subject__contains=charged.number).values_list("to_address", flat=True))
    assert ff.user.email in sent_to and platform_practice.user.email in sent_to


@pytest.mark.django_db
def test_a_subscription_refund_in_part_then_voided_in_full(charged, platform_practice, api,
                                                           stub_gateway):
    stub_gateway.settle(charged.nmi_transaction_id)
    assert refund_charge(api, platform_practice, charged, 500).status_code == 200
    charged.refresh_from_db()
    assert charged.amount_paid_cents == 1500 and charged.status == PracticeInvoice.Status.OPEN
    over = refund_charge(api, platform_practice, charged, 1501)
    assert over.status_code == 400
    assert refund_charge(api, platform_practice, charged, 1500,
                         void_invoice=True).status_code == 200
    charged.refresh_from_db()
    assert charged.status == PracticeInvoice.Status.VOID and charged.amount_paid_cents == 0
    assert list(R.all_objects.values_list("kind", flat=True)) == ["refund", "refund"]


@pytest.mark.django_db
def test_only_the_platform_owner_in_the_practices_area_refunds_a_charge(
        charged, platform_practice, ff, api, stub_gateway):
    url = f"/api/platform/practices/{charged.tenant_id}/charges/{charged.pk}/refund"
    body = json.dumps({"amount_cents": 2000, "reason": "x"})
    # The practice's own owner, and the platform owner outside the area.
    assert api.as_(ff).post(url, body, content_type="application/json").status_code == 403
    assert api.as_(platform_practice).post(
        url, body, content_type="application/json").status_code == 403
    assert not R.all_objects.exists()


@pytest.mark.django_db
def test_the_platform_read_back_knows_its_own_and_records_a_portal_one(
        charged, platform_practice, api, stub_gateway):
    from apps.billing import gateway as gw

    stub_gateway.settle(charged.nmi_transaction_id)
    assert refund_charge(api, platform_practice, charged, 500).status_code == 200
    stub_gateway.portal_refund(gw.platform_account(), charged.nmi_transaction_id, 300,
                               separate=True)
    readback.read_back_platform()
    [event] = NmiEvent.all_objects.filter(platform=True)
    assert event.amount_cents == 300 and event.practice_invoice_id == charged.pk
    recorded = practices(api, platform_practice).post(
        f"/api/platform/nmi-events/{event.pk}/record", "{}", content_type="application/json")
    assert recorded.status_code == 200, recorded.content
    charged.refresh_from_db()
    assert charged.amount_paid_cents == 1200
    assert R.all_objects.get(nmi_event=event).source == R.Source.PORTAL


@pytest.mark.django_db
def test_tenant_isolation_a_charge_is_found_only_under_its_own_practice(
        charged, platform_practice, tenant_b, api, stub_gateway):
    wrong = practices(api, platform_practice).post(
        f"/api/platform/practices/{tenant_b.pk}/charges/{charged.pk}/refund",
        json.dumps({"amount_cents": 100, "reason": "x"}), content_type="application/json")
    assert wrong.status_code == 404 and not R.all_objects.exists()


@pytest.mark.django_db
def test_a_payment_attempt_reference_is_what_the_refund_is_looked_up_by(paid, ff, api,
                                                                        stub_gateway):
    stub_gateway.settle(paid.nmi_transaction_id)
    give_back(api, ff, paid, 1000)
    refund = R.all_objects.get()
    assert refund.sale_reference == str(PaymentAttempt.all_objects.get(payment=paid).pk)
