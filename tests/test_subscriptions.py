"""P4 part 5: practice subscriptions (`docs/p4_billing.md` §2, §5.1).

Every test runs on the stub gateway (`conftest.stub_gateway`): no test
reaches NMI. The platform account is the stub's "platform" label (the
NMI_* settings); a practice's own account is labeled by its id.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from django.test import RequestFactory, override_settings
from django.utils import timezone

from apps.billing import card_payments, gateway as gw, subscriptions
from apps.billing.models import (
    ClientPayment, PaymentAttempt, PracticeInvoice, PracticeSubscription,
)
from apps.crm.models import OutboxMessage, OutboxAttachment
from apps.tenancy.context import acting_context, tenant_context
from apps.tenancy.models import Tenant

from . import registry_config  # noqa: F401
from .conftest import _member
from .test_card_payments import _after_commit_now  # noqa: F401  (autouse)
from .test_card_payments import connect, sales
from .test_client_invoicing import ready_to_bill  # noqa: F401  (a fixture)
from .test_client_invoicing import a_client, post, sent

ROOT = "/api/subscription/"
I = PracticeInvoice.Status


@pytest.fixture(autouse=True)
def _commit_now(monkeypatch):
    monkeypatch.setattr(subscriptions.transaction, "on_commit", lambda fn, **kw: fn())


@pytest.fixture
def platform_practice(tenant_b):
    """The platform owner's own practice: platform mail is sent from it."""
    owner = _member(tenant_b, "FF")
    owner.user.is_platform_owner = True
    owner.user.save()
    return owner


def save_card(api, who, token="tok-sub"):
    return post(api, who, ROOT + "card/", {"payment_token": token})


def run(tenant, day):
    with tenant_context(tenant.pk):
        return subscriptions.run(tenant, today=day)


def next_first(day=None):
    return subscriptions.first_of_next_month(day or timezone.localdate())


def platform_sales(stub):
    return [c for c in sales(stub) if c[1] == "platform"]


@pytest.fixture
def carded(seeded_tenant, ff, api, platform_practice):
    assert save_card(api, ff).status_code == 200
    return seeded_tenant


# ------------------------------------------------------------- the card

@pytest.mark.django_db
def test_the_owner_saves_the_practices_card_in_the_platforms_vault(seeded_tenant, ff, api,
                                                                   stub_gateway):
    shown = api.as_(ff).get(ROOT).json()
    assert shown["status"] == "needs_card" and shown["amount_cents"] == 2000
    assert shown["public_key"] == "platform-public-test-value"
    response = save_card(api, ff)
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["card"] == {"brand": "Visa", "last4": "1111", "expires": "10/29"}
    assert body["status"] == "active" and body["next_charge_on"] == next_first().isoformat()
    [call] = [c for c in stub_gateway.calls if c[0] == "vault_add"]
    assert call[1] == "platform"
    assert "platform-private-test-value" not in json.dumps(body)
    row = PracticeSubscription.all_objects.get(tenant=seeded_tenant)
    assert row.nmi_vault_id in stub_gateway.vault and row.first_charge_on == next_first()


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["CF", "VA"])
def test_only_the_practice_owner_has_the_subscription(role, seeded_tenant, api, stub_gateway):
    who = _member(seeded_tenant, role)
    assert api.as_(who).get(ROOT).status_code == 403
    assert save_card(api, who).status_code == 403
    assert post(api, who, ROOT + "pay-now/").status_code == 403


@pytest.mark.django_db
def test_a_client_never_reaches_it(seeded_tenant, fcc, api, stub_gateway):
    assert api.as_(fcc).get(ROOT).status_code in (403, 404)
    assert save_card(api, fcc).status_code in (403, 404)


@pytest.mark.django_db
def test_the_owners_own_practice_is_never_billed(platform_practice, api, stub_gateway):
    tenant = platform_practice.tenant
    assert api.as_(platform_practice).get(ROOT).json()["not_billed"] is True
    assert save_card(api, platform_practice).status_code == 409
    PracticeSubscription.all_objects.filter(tenant=tenant).update(
        nmi_vault_id="1", first_charge_on=date(2026, 1, 1))
    assert run(tenant, date(2026, 12, 1))["charged"] == 0
    assert not PracticeInvoice.all_objects.filter(tenant=tenant).exists()


# ------------------------------------------------------------ the charge

@pytest.mark.django_db
def test_no_charge_before_a_card(seeded_tenant, platform_practice, stub_gateway):
    assert run(seeded_tenant, next_first())["charged"] == 0
    assert platform_sales(stub_gateway) == []
    assert not PracticeInvoice.all_objects.exists()


@pytest.mark.django_db
def test_no_part_month_then_the_1st_is_charged_with_its_own_invoice_and_receipt(
        carded, ff, api, platform_practice, stub_gateway):
    today = timezone.localdate()
    assert run(carded, today)["charged"] == 0          # the rest of this month is free
    first = next_first()
    assert run(carded, first)["charged"] == 1
    [sale] = platform_sales(stub_gateway)
    invoice = PracticeInvoice.all_objects.get(tenant=carded)
    assert sale[2]["reference"] == f"sub-{invoice.pk}" and sale[2]["vault_id"]
    assert sale[2]["amount_cents"] == 2000
    assert (invoice.status, invoice.total_cents, invoice.tax_cents) == ("paid", 2000, 0)
    assert invoice.period_start == first and invoice.nmi_transaction_id
    assert invoice.pdf_id is not None and invoice.number.startswith(f"ENH-{first:%Y%m}")
    # The receipt, with the PDF, from the platform owner's practice.
    receipt = OutboxMessage.all_objects.get(producer="subscription_receipt")
    assert receipt.tenant_id == platform_practice.tenant_id and receipt.state == "sent"
    assert receipt.to_address == ff.user.email and invoice.number in receipt.body_text
    [attached] = OutboxAttachment.all_objects.filter(outbox_message=receipt)
    assert attached.filename == f"Invoice-{invoice.number}.pdf"
    # The owner sees it and downloads it.
    shown = api.as_(ff).get(ROOT).json()["invoices"]
    assert shown[0]["number"] == invoice.number and shown[0]["status"] == "paid"
    pdf = api.as_(ff).get(f"{ROOT}{invoice.pk}/pdf/")
    assert pdf.status_code == 200 and pdf["Content-Type"] == "application/pdf"


@pytest.mark.django_db
def test_the_job_is_safe_to_run_twice(carded, stub_gateway):
    run(carded, next_first())
    run(carded, next_first())
    run(carded, next_first() + timedelta(days=3))
    assert len(platform_sales(stub_gateway)) == 1


@pytest.mark.django_db
def test_an_override_applies_from_the_next_period(carded, ff, api, platform_practice,
                                                  stub_gateway):
    first = next_first()
    run(carded, first)
    from apps.platform import billing

    billing.set_amount(carded, 3500, actor=platform_practice.user)
    run(carded, first + timedelta(days=5))
    second = subscriptions.first_of_next_month(first)
    run(carded, second)
    amounts = [s[2]["amount_cents"] for s in platform_sales(stub_gateway)]
    assert amounts == [2000, 3500]


@pytest.mark.django_db
def test_an_addon_added_mid_month_is_charged_from_the_next_period(carded, stub_gateway):
    from .factories import PracticeSubscriptionAddonFactory

    first = next_first()
    row = PracticeSubscription.all_objects.get(tenant=carded)
    PracticeSubscriptionAddonFactory(tenant=carded, subscription=row,
                                     charged_from=subscriptions.first_of_next_month(first))
    run(carded, first)
    run(carded, subscriptions.first_of_next_month(first))
    assert [s[2]["amount_cents"] for s in platform_sales(stub_gateway)] == [2000, 4500]


@pytest.mark.django_db
def test_a_failure_leaves_it_open_tells_the_owner_and_pay_now_pays_it(
        carded, ff, api, platform_practice, stub_gateway):
    stub_gateway.refuse_next = ("300", "Do not honor")
    run(carded, next_first())
    invoice = PracticeInvoice.all_objects.get(tenant=carded)
    assert invoice.status == "open" and invoice.last_charge_text == "Do not honor"
    assert PracticeSubscription.all_objects.get(tenant=carded).status == "past_due"
    notice = OutboxMessage.all_objects.get(producer="subscription_notice")
    assert notice.to_address == ff.user.email and "/settings/billing" in notice.body_text
    assert not OutboxMessage.all_objects.filter(producer="subscription_receipt").exists()
    # The monthly job does not try again by itself.
    run(carded, next_first() + timedelta(days=1))
    assert len(platform_sales(stub_gateway)) == 1
    paid = post(api, ff, ROOT + "pay-now/")
    assert paid.status_code == 200 and "Thank you" in paid.json()["message"]
    invoice.refresh_from_db()
    assert invoice.status == "paid"
    assert PracticeSubscription.all_objects.get(tenant=carded).status == "active"
    assert OutboxMessage.all_objects.filter(producer="subscription_receipt").count() == 1


@pytest.mark.django_db
def test_a_lost_answer_is_looked_up_and_never_charged_twice(carded, ff, api, stub_gateway):
    stub_gateway.lose_next_answer = True
    run(carded, next_first())
    invoice = PracticeInvoice.all_objects.get(tenant=carded)
    assert invoice.charge_state == "unknown" and invoice.status == "open"
    assert post(api, ff, ROOT + "pay-now/").status_code == 409
    run(carded, next_first() + timedelta(days=1))
    invoice.refresh_from_db()
    assert invoice.status == "paid" and len(platform_sales(stub_gateway)) == 1


# ----------------------------------------------------------- suspension

def _overdue(tenant):
    invoice = PracticeInvoice.all_objects.get(tenant=tenant)
    PracticeInvoice.all_objects.filter(pk=invoice.pk).update(
        issued_at=timezone.now() - timedelta(days=31))
    return invoice


@pytest.fixture
def overdue(carded, stub_gateway):
    stub_gateway.refuse_next = ("300", "Do not honor")
    run(carded, next_first())
    return _overdue(carded)


@pytest.fixture
def in_practices_area(api, platform_practice):
    from apps.tenancy.middleware import AREA_PLATFORM, AREA_SESSION_KEY

    client = api.as_(platform_practice)
    session = client.session
    session[AREA_SESSION_KEY] = AREA_PLATFORM
    session.save()
    return client


@pytest.mark.django_db
def test_thirty_days_unpaid_is_flagged_and_never_suspends_by_itself(overdue, carded,
                                                                    in_practices_area):
    rows = in_practices_area.get("/api/platform/practices").json()
    row = next(r for r in rows if r["id"] == str(carded.pk))
    assert row["subscription"]["eligible_for_suspension"] is True
    assert row["subscription"]["oldest_open_days"] >= 30
    run(carded, next_first() + timedelta(days=40))
    carded.refresh_from_db()
    assert carded.status == "active"


@pytest.mark.django_db
def test_not_suspended_before_thirty_days(carded, stub_gateway, in_practices_area):
    stub_gateway.refuse_next = ("300", "Do not honor")
    run(carded, next_first())
    response = in_practices_area.post(f"/api/platform/practices/{carded.pk}/suspend")
    assert response.status_code == 409


@pytest.mark.django_db
def test_suspended_staff_see_only_billing_and_paying_lifts_it(
        overdue, carded, ff, fcc, api, in_practices_area, stub_gateway):
    from django_q.models import Schedule
    from django.core.management import call_command

    call_command("ensure_schedules", stdout=open("/dev/null", "w"))
    before = {name: value for name, value in carded.__dict__.items()
              if name in ("name", "legal_name", "domain")}
    response = in_practices_area.post(f"/api/platform/practices/{carded.pk}/suspend")
    assert response.status_code == 200, response.content
    carded.refresh_from_db()
    assert carded.status == "suspended" and carded.suspended_at is not None
    # Its jobs stop, but the subscription charge.
    names = set(Schedule.objects.filter(name__endswith=f":{carded.slug}").values_list(
        "name", flat=True))
    assert names == {f"billing.charge_subscription:{carded.slug}"}
    call_command("ensure_schedules", stdout=open("/dev/null", "w"))
    assert set(Schedule.objects.filter(name__endswith=f":{carded.slug}").values_list(
        "name", flat=True)) == names
    # Staff: the billing screen only.
    cf = _member(carded, "CF")
    for who in (ff, cf):
        refused = api.as_(who).get("/api/contacts/")
        assert refused.status_code == 403 and refused.json()["suspended"] is True
        assert api.as_(who).get("/api/me").json()["suspended"] is True
    assert api.as_(ff).get(ROOT).json()["suspended"] is True
    # Clients are not stopped from reading what they have.
    assert api.as_(fcc).get("/api/me").json()["suspended"] is False
    assert api.as_(fcc).get("/api/portal-invoices/").status_code == 200
    # No data touched.
    assert {k: getattr(carded, k) for k in before} == before

    paid = post(api, ff, ROOT + "pay-now/")
    assert paid.status_code == 200 and "no longer suspended" in paid.json()["message"]
    carded.refresh_from_db()
    assert carded.status == "active" and carded.suspended_at is None
    assert api.as_(ff).get("/api/contacts/").status_code == 200
    assert Schedule.objects.filter(name=f"notes.process:{carded.slug}").exists()


@pytest.mark.django_db
def test_the_monthly_charge_lifts_it_too(overdue, carded, platform_practice, stub_gateway):
    subscriptions.suspend(carded, actor=platform_practice.user)
    with tenant_context(carded.pk):
        subscriptions.resolve_unknown(carded)
        subscriptions.charge(overdue)
    carded.refresh_from_db()
    assert carded.status == "active"


@pytest.mark.django_db
def test_the_platform_owner_sets_the_amount_and_never_sees_the_card(
        carded, in_practices_area):
    response = in_practices_area.patch(
        f"/api/platform/practices/{carded.pk}",
        data=json.dumps({"subscription_amount_cents": 1500}), content_type="application/json")
    assert response.status_code == 200, response.content
    sub = response.json()["subscription"]
    assert sub["amount_cents"] == 1500 and sub["overridden"] and sub["card_on_file"] is True
    text = json.dumps(response.json())
    row = PracticeSubscription.all_objects.get(tenant=carded)
    assert row.nmi_vault_id not in text and "1111" not in text
    bad = in_practices_area.patch(f"/api/platform/practices/{carded.pk}",
                                  data=json.dumps({"subscription_amount_cents": -5}),
                                  content_type="application/json")
    assert bad.status_code == 400


@pytest.mark.django_db
def test_archiving_cancels_and_unarchiving_starts_from_the_next_1st(
        carded, platform_practice, stub_gateway):
    from apps.platform import provisioning

    provisioning.archive(carded, actor=platform_practice.user)
    assert PracticeSubscription.all_objects.get(tenant=carded).status == "canceled"
    assert run(carded, next_first())["charged"] == 0
    provisioning.unarchive(carded, actor=platform_practice.user)
    row = PracticeSubscription.all_objects.get(tenant=carded)
    assert row.status == "active" and row.first_charge_on == next_first()


# --------------------------------------------------------- separation

@pytest.mark.django_db
def test_a_client_payment_never_marks_a_subscription_invoice_paid(
        ready_to_bill, carded, ff, fcc, api, stub_gateway):  # noqa: F811
    """§1.2: told apart by our reference, never by the account."""
    stub_gateway.refuse_next = ("300", "Do not honor")
    run(carded, next_first())
    sub_invoice = PracticeInvoice.all_objects.get(tenant=carded)
    # A client of the same practice pays their invoice by card.
    connect(carded, ff)
    from .factories import ContactEmailFactory, ContactFactory

    contact = ContactFactory(tenant=carded, company=fcc.client_company)
    ContactEmailFactory(tenant=carded, contact=contact, is_primary=True,
                        address="c@client.invalid")
    from apps.billing.models import ClientInvoice

    client_invoice = ClientInvoice.all_objects.get(
        pk=sent(api, ff, fcc.client_company, contact)["id"])
    post(api, fcc, f"/api/portal-invoices/{client_invoice.pk}/pay/", {"payment_token": "t1"})
    attempt = PaymentAttempt.all_objects.get(invoice=client_invoice)
    assert attempt.status == "approved"
    sub_invoice.refresh_from_db()
    assert sub_invoice.status == "open"
    # The client's sale, handed to the subscription side, is refused.
    client_txn = stub_gateway.get_transaction(
        gw.Account(environment="sandbox", private_key="x", public_key="y",
                   label=str(carded.pk)), attempt.nmi_transaction_id)
    with tenant_context(carded.pk), pytest.raises(subscriptions.SubscriptionRefused):
        subscriptions.settle(sub_invoice, client_txn)
    sub_invoice.refresh_from_db()
    assert sub_invoice.status == "open"


@pytest.mark.django_db
def test_a_subscription_charge_never_marks_a_client_invoice_paid(
        ready_to_bill, carded, ff, fcc, api, stub_gateway):  # noqa: F811
    run(carded, next_first())
    sub_invoice = PracticeInvoice.all_objects.get(tenant=carded)
    assert sub_invoice.status == "paid"
    connect(carded, ff)
    from .factories import ContactEmailFactory, ContactFactory
    from apps.billing.models import ClientInvoice

    contact = ContactFactory(tenant=carded, company=fcc.client_company)
    ContactEmailFactory(tenant=carded, contact=contact, is_primary=True,
                        address="c@client.invalid")
    client_invoice = ClientInvoice.all_objects.get(
        pk=sent(api, ff, fcc.client_company, contact)["id"])
    assert not ClientPayment.all_objects.filter(invoice=client_invoice).exists()
    # A pending client attempt, settled from the subscription's sale: refused.
    with tenant_context(carded.pk):
        attempt = card_payments.start(client_invoice, payer=fcc.user)
        sub_txn = stub_gateway.get_transaction(gw.platform_account(),
                                               sub_invoice.nmi_transaction_id)
        assert sub_txn.reference == sub_invoice.reference
        card_payments.settle(attempt, sub_txn)
    attempt.refresh_from_db()
    client_invoice.refresh_from_db()
    assert attempt.status == "pending" and client_invoice.status == "sent"
    assert not ClientPayment.all_objects.filter(invoice=client_invoice).exists()


@pytest.mark.django_db
def test_one_practices_subscription_is_never_anothers(carded, tenant_b, platform_practice,
                                                      api, stub_gateway):
    other = _member(tenant_b, "FF")
    shown = api.as_(other).get(ROOT).json()
    assert shown["card"] is None or shown["not_billed"]
    run(carded, next_first())
    assert api.as_(other).get(ROOT).json()["invoices"] == []
    invoice = PracticeInvoice.all_objects.get(tenant=carded)
    assert api.as_(other).get(f"{ROOT}{invoice.pk}/pdf/").status_code == 404


# ------------------------------------------------------------ v4, proxy

@pytest.mark.django_db
def test_the_agreement_is_v4_and_says_the_card_is_charged_on_the_1st(seeded_tenant, ff, api,
                                                                    settings):
    from apps.platform import agreement

    settings.BETA_AGREEMENT_REQUIRED = True
    agreement.current.cache_clear()
    terms = agreement.current()
    assert terms["version"] == "v4"
    assert "charged on the first day of each month" in terms["text"]
    assert "8. Personal finance and the demo." in terms["text"]
    from .factories import AgreementAcceptanceFactory

    AgreementAcceptanceFactory(tenant=seeded_tenant, user=ff.user, version="v3")
    refused = api.as_(ff).get("/api/contacts/")
    assert refused.status_code == 403 and refused.json()["agreement_required"] is True


@pytest.mark.parametrize("hops, forwarded, expected", [
    (0, "198.51.100.7", "10.0.0.1"),
    (1, "198.51.100.7", "198.51.100.7"),
    (1, "6.6.6.6, 198.51.100.7", "198.51.100.7"),     # a forged left entry is ignored
    (1, "", "10.0.0.1"),
    (1, "not-an-address", "10.0.0.1"),
    (2, "198.51.100.7, 203.0.113.2", "198.51.100.7"),
])
def test_the_visitors_address_behind_a_trusted_proxy(hops, forwarded, expected):
    from apps.accounts.ratelimit import client_ip

    request = RequestFactory().get("/", REMOTE_ADDR="10.0.0.1",
                                   HTTP_X_FORWARDED_FOR=forwarded)
    with override_settings(TRUSTED_PROXY_HOPS=hops):
        assert client_ip(request) == expected


# --------------------------------------------- card on file, staff side

@pytest.mark.django_db
def test_card_on_file_line_for_the_owner_and_an_assigned_associate(
        seeded_tenant, ff, fcc, api, stub_gateway):
    from apps.billing import autopay

    connect(seeded_tenant, ff)
    company = fcc.client_company
    url = f"/api/invoices/card-on-file/?company={company.pk}"
    assert api.as_(ff).get(url).json() == {"card": None, "autopay_since": None}
    post(api, fcc, "/api/portal-autopay/card/", {"payment_token": "tok-c"})
    post(api, fcc, "/api/portal-autopay/consent/",
         {"agree": True, "version": autopay.WORDING_VERSION})
    shown = api.as_(ff).get(url).json()
    assert shown["card"] == {"brand": "Visa", "last4": "1111", "expires": "10/29"}
    assert shown["autopay_since"]
    cf = _member(seeded_tenant, "CF")
    assert api.as_(cf).get(url).status_code == 404
    from .factories import ClientAssignmentFactory

    ClientAssignmentFactory(tenant=seeded_tenant, user=cf.user, company=company)
    assert api.as_(cf).get(url).json()["card"]["last4"] == "1111"
    va = _member(seeded_tenant, "VA")
    assert api.as_(va).get(url).status_code == 403
    assert api.as_(fcc).get(url).status_code == 404
