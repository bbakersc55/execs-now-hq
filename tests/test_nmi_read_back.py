"""P4 §4: the daily read-back of a practice's NMI account.

Refunds, voids and chargebacks made in NMI's portal are recorded against the
payment they match; anything that can't be matched (a charge made in the
portal included) is flagged for the practice owner; the app's own sales and
the platform's subscription charges are not events; an action is recorded
once; nothing is ever charged; one practice's read-back never touches
another's account or rows; only the practice owner sees them.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.billing import readback
from apps.billing.gateway import Account
from apps.billing.models import ClientPayment, NmiEvent, PaymentAttempt
from apps.tenancy.context import tenant_context

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import MembershipFactory, TenantFactory
from .test_card_payments import billing, connect, pay  # noqa: F401  (fixtures)
from .test_client_invoicing import ready_to_bill  # noqa: F401

pytestmark = pytest.mark.django_db


def account_of(tenant):
    return Account(environment="sandbox", private_key="x", public_key="y", label=str(tenant.pk))


def paid(api, fcc, invoice, stub):
    assert pay(api, fcc, invoice).status_code == 200
    payment = ClientPayment.all_objects.get(invoice=invoice)
    return payment, payment.nmi_transaction_id


def charges(stub):
    return [c for c in stub.calls if c[0] in ("sale", "refund", "vault_add")]


def test_a_refund_and_a_chargeback_in_nmis_portal_are_recorded_against_the_payment(
        billing, fcc, ff, seeded_tenant, api, stub_gateway):  # noqa: F811
    payment, tid = paid(api, fcc, billing, stub_gateway)
    account = account_of(seeded_tenant)
    stub_gateway.portal_refund(account, tid, 20000)
    stub_gateway.portal_refund(account, tid, 5000, separate=True,
                               at=timezone.now() - timedelta(hours=1))
    stub_gateway.portal_chargeback(account, tid, 680000)
    before = len(charges(stub_gateway))
    counts = readback.read_back(seeded_tenant)
    assert counts["matched"] == 3 and counts["flagged"] == 0
    events = NmiEvent.all_objects.filter(tenant=seeded_tenant).order_by("happened_at")
    assert {(e.kind, e.amount_cents) for e in events} == {
        ("refund", 20000), ("refund", 5000), ("chargeback", 680000)}
    assert all(e.payment_id == payment.pk and e.invoice_id == billing.pk for e in events)
    assert all(e.outcome == "matched" for e in events)
    # Read-only: nothing charged or refunded by the read-back.
    assert len(charges(stub_gateway)) == before
    # The invoice's money is not changed by it; the invoice shows what happened.
    billing.refresh_from_db()
    assert billing.status == "paid"
    shown = api.as_(ff).get(f"/api/invoices/{billing.pk}/").json()["nmi_events"]
    assert [e["kind"] for e in shown] == ["refund", "refund", "chargeback"]
    assert "Refunded $200.00 in NMI" in shown[1]["note"]


def test_each_action_is_recorded_once_and_our_own_sale_is_not_an_event(
        billing, fcc, seeded_tenant, api, stub_gateway):  # noqa: F811
    _, tid = paid(api, fcc, billing, stub_gateway)
    stub_gateway.portal_refund(account_of(seeded_tenant), tid, 1000)
    assert readback.read_back(seeded_tenant)["matched"] == 1
    assert readback.read_back(seeded_tenant)["matched"] == 0
    assert readback.read_back(seeded_tenant, now=timezone.now() + timedelta(days=1))[
        "matched"] == 0
    assert NmiEvent.all_objects.filter(tenant=seeded_tenant).count() == 1
    assert not NmiEvent.all_objects.filter(kind="sale").exists()


def test_what_cant_be_matched_is_flagged_for_the_practice_owner_only(
        billing, fcc, ff, seeded_tenant, api, stub_gateway):  # noqa: F811
    connect(seeded_tenant, ff)
    account = account_of(seeded_tenant)
    stranger = stub_gateway.portal_sale(account, 25000)            # made in NMI's portal
    stub_gateway.portal_refund(account, stranger, 25000)            # and refunded there
    stub_gateway.portal_sale(account, 9900, reference="sub-0000")   # the platform's
    counts = readback.read_back(seeded_tenant)
    assert counts["flagged"] == 2 and counts["matched"] == 0
    flagged = NmiEvent.all_objects.filter(tenant=seeded_tenant, outcome="unmatched")
    assert {e.kind for e in flagged} == {"sale", "refund"}
    sale = flagged.get(kind="sale")
    assert sale.note.startswith("A charge of $250.00 made in NMI") and sale.payment_id is None
    assert not NmiEvent.all_objects.filter(reference__startswith="sub-").exists()

    rows = api.as_(ff).get("/api/nmi-events/?open=1").json()
    assert len(rows) == 2
    seen = api.as_(ff).post(f"/api/nmi-events/{rows[0]['id']}/seen/")
    assert seen.status_code == 200 and seen.json()["reviewed"] is True
    assert len(api.as_(ff).get("/api/nmi-events/?open=1").json()) == 1
    for role in ("CF", "VA"):
        other = _member(seeded_tenant, role)
        assert api.as_(other).get("/api/nmi-events/").status_code == 403
        assert api.as_(other).post(f"/api/nmi-events/{rows[1]['id']}/seen/").status_code == 403
    assert api.as_(fcc).get("/api/nmi-events/").status_code == 404


def test_a_practice_with_no_account_or_nmi_silent_is_left_for_the_next_day(
        seeded_tenant, stub_gateway):
    assert readback.read_back(seeded_tenant)["skipped"] == "not connected"
    ff = _member(seeded_tenant, "FF")
    connect(seeded_tenant, ff)
    stub_gateway.actions_unreachable = True
    assert readback.read_back(seeded_tenant)["skipped"] == "NMI did not answer"
    assert not NmiEvent.all_objects.exists()


def test_one_practices_read_back_never_reaches_another_practices_account_or_rows(
        billing, fcc, ff, seeded_tenant, api, stub_gateway):  # noqa: F811
    _, tid = paid(api, fcc, billing, stub_gateway)
    other = TenantFactory()
    other_ff = MembershipFactory(tenant=other, role="FF")
    connect(other, other_ff)
    stub_gateway.portal_refund(account_of(seeded_tenant), tid, 1000)
    stub_gateway.portal_sale(account_of(other), 5000)
    stub_gateway.calls.clear()
    readback.read_back(other)
    assert {c[1] for c in stub_gateway.calls} == {str(other.pk)}
    assert NmiEvent.all_objects.filter(tenant=other).count() == 1
    assert NmiEvent.all_objects.filter(tenant=other, payment__isnull=False).count() == 0
    readback.read_back(seeded_tenant)
    mine = NmiEvent.all_objects.get(tenant=seeded_tenant)
    assert api.as_(other_ff).get("/api/nmi-events/").json()[0]["id"] != str(mine.pk)
    assert api.as_(other_ff).post(f"/api/nmi-events/{mine.pk}/seen/").status_code == 404


def test_the_read_back_is_scheduled_daily():
    from apps.tenancy.management.commands.ensure_schedules import SCHEDULES

    assert ("billing.read_back_nmi", "apps.billing.tasks.read_back_nmi") in {
        (name, func) for name, func, *_ in SCHEDULES}
