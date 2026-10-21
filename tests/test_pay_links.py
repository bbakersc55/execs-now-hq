"""P4 part 3: the signed pay link (`docs/p4_billing.md` §3.4).

Every test runs on the stub gateway (`conftest.stub_gateway`): no test
reaches NMI.
"""

from __future__ import annotations

import json
import re

import pytest
from django.core.cache import cache
from django.test import Client

from apps.billing import pay_links, pdf
from apps.billing.models import ClientInvoice, ClientPayment, PaymentAttempt
from apps.crm.models import OutboxMessage
from apps.crm.services import templates
from apps.tenancy.context import tenant_context

from . import registry_config  # noqa: F401
from .conftest import _member
from .test_card_payments import PRIVATE, PUBLIC, connect, producers, sales
from .test_card_payments import _after_commit_now  # noqa: F401  (autouse)
from .test_client_invoicing import ready_to_bill  # noqa: F401  (a fixture)
from .test_client_invoicing import LINES, ROOT, a_client, get, post, sent

LINK = re.compile(r"https?://\S+/pay/([A-Za-z0-9_-]+)")


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def anyone():
    """No one signed in: what the link is for."""
    return Client()


@pytest.fixture
def connected(ready_to_bill, ff):  # noqa: F811
    connect(ready_to_bill, ff)
    return ready_to_bill


def token_in(text: str) -> str:
    found = LINK.search(text)
    assert found, text
    return found.group(1)


def invoice_email(invoice) -> OutboxMessage:
    return (OutboxMessage.all_objects.filter(source_type="client_invoice",
                                             source_id=invoice.pk)
            .order_by("-created_at").first())


@pytest.fixture
def linked(connected, ff, api):
    """A sent invoice of $6,800.00, made ready once the practice could take
    cards; and its link's token, read from the email as the client gets it."""
    company, contact = a_client(connected)
    invoice = ClientInvoice.all_objects.get(pk=sent(api, ff, company, contact)["id"])
    return invoice, token_in(invoice_email(invoice).body_text)


# ------------------------------------------------------- issued, and stored

@pytest.mark.django_db
def test_made_ready_it_gets_a_link_stored_only_as_a_hash(connected, ff, api, monkeypatch):
    printed = {}

    def render_pdf(invoice):
        printed["html"] = pdf.render_html(invoice)
        return b"%PDF-1.4 test"

    monkeypatch.setattr(pdf, "render_pdf", render_pdf)
    company, contact = a_client(connected)
    invoice = ClientInvoice.all_objects.get(pk=sent(api, ff, company, contact)["id"])
    token = token_in(invoice_email(invoice).body_text)

    # The PDF printed it, and the email carries the same one.
    assert f"/pay/{token}" in printed["html"]
    assert "Pay it online: " in invoice_email(invoice).body_text
    # Only its hash is kept: no column of the invoice holds the token.
    row = ClientInvoice.all_objects.filter(pk=invoice.pk).values().get()
    assert row["pay_token_hash"] and row["pay_url"] == ""
    assert token not in json.dumps(row, default=str)
    assert "{PayLink}" in row["email_body"]
    # The practice owner sees the link and the email as it went.
    detail = get(api, ff, f"{ROOT}{invoice.pk}/").json()
    assert detail["pay_url"].endswith(f"/pay/{token}")
    assert f"/pay/{token}" in detail["email_body"]


@pytest.mark.django_db
def test_no_link_while_the_practice_cannot_take_cards(ready_to_bill, ff, api):  # noqa: F811
    company, contact = a_client(ready_to_bill)
    invoice = ClientInvoice.all_objects.get(pk=sent(api, ff, company, contact)["id"])
    body = invoice_email(invoice).body_text
    assert "/pay/" not in body and "Pay it online" not in body and "{PayLink}" not in body
    invoice.refresh_from_db()
    assert invoice.pay_token_hash == ""


@pytest.mark.django_db
def test_an_invoice_sent_before_links_gets_one_when_resent(ready_to_bill, ff, api,  # noqa: F811
                                                           anyone):
    company, contact = a_client(ready_to_bill)
    invoice = ClientInvoice.all_objects.get(pk=sent(api, ff, company, contact)["id"])
    assert "/pay/" not in invoice_email(invoice).body_text
    connect(ready_to_bill, ff)
    assert post(api, ff, f"{ROOT}{invoice.pk}/send/").status_code == 200
    resent = invoice_email(invoice)
    token = token_in(resent.body_text)
    assert resent.state == OutboxMessage.State.SENT
    assert anyone.get(f"/api/pay/{token}").status_code == 200
    # Resent again: the same link, not a new one.
    assert post(api, ff, f"{ROOT}{invoice.pk}/send/").status_code == 200
    assert token_in(invoice_email(invoice).body_text) == token


# ------------------------------------------------------------- the page

@pytest.mark.django_db
def test_the_page_shows_the_invoice_and_nothing_else(linked, anyone, seeded_tenant):
    invoice, token = linked
    response = anyone.get(f"/api/pay/{token}")
    assert response.status_code == 200
    page = response.json()
    assert page == {
        "practice": seeded_tenant.name, "number": invoice.number,
        "amount_due_cents": 680000, "due_date": invoice.due_date.isoformat(),
        "paid": False, "test_mode": True, "public_key": PUBLIC, "notice": ""}
    assert PRIVATE not in response.content.decode()
    pdf_response = anyone.get(f"/api/pay/{token}/pdf")
    assert pdf_response.status_code == 200
    assert pdf_response["Content-Type"] == "application/pdf"
    # The practice is found from the token: its branding too.
    brand = anyone.get(f"/api/branding?via=pay:{token}").json()
    assert brand["display_name"] == seeded_tenant.name


@pytest.mark.django_db
def test_paid_by_the_link_without_signing_in(linked, anyone, seeded_tenant, ff,
                                             stub_gateway):
    invoice, token = linked
    response = anyone.post(f"/api/pay/{token}", data=json.dumps({"payment_token": "tok-9"}),
                           content_type="application/json")
    assert response.status_code == 200, response.content
    assert response.json()["status"] == "approved"
    assert response.json()["invoice_status"] == "paid"

    [sale] = sales(stub_gateway)
    attempt = PaymentAttempt.all_objects.get(invoice=invoice)
    assert sale[1] == str(seeded_tenant.pk) and sale[2]["payment_token"] == "tok-9"
    assert attempt.via == "link" and attempt.payer_id is None
    payment = ClientPayment.all_objects.get(invoice=invoice)
    assert payment.method == "card" and "pay link" in payment.note
    # The receipt goes where the invoice went; the owner is told.
    mail = producers(seeded_tenant)
    assert ("payment_receipt", invoice.email_to, "sent") in mail
    assert ("payment_notice", ff.user.email, "sent") in mail
    notice = OutboxMessage.all_objects.get(producer="payment_notice")
    assert "by the pay link" in notice.body_text

    # Paid: the page says so, with no card form, and takes nothing more.
    page = anyone.get(f"/api/pay/{token}").json()
    assert page["paid"] is True and page["public_key"] == "" and page["amount_due_cents"] == 0
    again = anyone.post(f"/api/pay/{token}", data=json.dumps({"payment_token": "tok-10"}),
                        content_type="application/json")
    assert again.status_code == 409 and len(sales(stub_gateway)) == 1


@pytest.mark.django_db
def test_a_contact_invoice_is_paid_by_its_link(connected, ff, api, anyone, stub_gateway):
    _, contact = a_client(connected, name="Solo Consulting")
    made = post(api, ff, ROOT, {"kind": "contact", "contact": str(contact.pk),
                                "lines": LINES}).json()
    assert post(api, ff, f"{ROOT}{made['id']}/make-ready/").status_code == 200
    assert post(api, ff, f"{ROOT}{made['id']}/send/").status_code == 200
    invoice = ClientInvoice.all_objects.get(pk=made["id"])
    token = token_in(invoice_email(invoice).body_text)
    assert anyone.get(f"/api/pay/{token}").json()["public_key"] == PUBLIC
    paid = anyone.post(f"/api/pay/{token}", data=json.dumps({"payment_token": "tok-c"}),
                       content_type="application/json")
    assert paid.json()["status"] == "approved"
    invoice.refresh_from_db()
    assert invoice.status == "paid"


@pytest.mark.django_db
def test_a_decline_by_the_link_keeps_the_form(linked, anyone, stub_gateway):
    invoice, token = linked
    stub_gateway.refuse_next = ("300", "Card declined")
    response = anyone.post(f"/api/pay/{token}", data=json.dumps({"payment_token": "tok-d"}),
                           content_type="application/json")
    assert response.json()["status"] == "declined"
    assert anyone.get(f"/api/pay/{token}").json()["public_key"] == PUBLIC


# ------------------------------------------------- when it stops working

@pytest.mark.django_db
def test_voided_the_link_is_a_404(linked, anyone, ff, api, stub_gateway):
    invoice, token = linked
    assert post(api, ff, f"{ROOT}{invoice.pk}/void/", {"reason": "Wrong amount"}).status_code \
        == 200
    invoice.refresh_from_db()
    assert invoice.pay_token_hash == ""
    assert anyone.get(f"/api/pay/{token}").status_code == 404
    assert anyone.get(f"/api/pay/{token}/pdf").status_code == 404
    assert anyone.post(f"/api/pay/{token}", data=json.dumps({"payment_token": "t"}),
                       content_type="application/json").status_code == 404
    assert anyone.get(f"/api/branding?via=pay:{token}").json().get("display_name") != \
        invoice.tenant.name
    assert sales(stub_gateway) == []


@pytest.mark.django_db
def test_a_wrong_token_is_the_same_404(linked, anyone):
    _, token = linked
    for wrong in (token[:-1] + ("A" if token[-1] != "A" else "B"), "x", "a" * 200):
        response = anyone.get(f"/api/pay/{wrong}")
        assert response.status_code == 404
        assert response.json() == {"detail": "This payment link is not valid. Ask the "
                                             "practice that sent the invoice for a new one."}


@pytest.mark.django_db
def test_not_before_the_email_has_gone(connected, ff, api, anyone):
    company, contact = a_client(connected)
    made = post(api, ff, ROOT, {"client_company": str(company.pk), "contact": str(contact.pk),
                                "lines": LINES}).json()
    assert post(api, ff, f"{ROOT}{made['id']}/make-ready/").status_code == 200
    invoice = ClientInvoice.all_objects.get(pk=made["id"])
    token = token_in(invoice_email(invoice).body_text)
    assert invoice.status == "ready"
    assert anyone.get(f"/api/pay/{token}").status_code == 404


@pytest.mark.django_db
def test_a_payment_under_way_is_said_plainly(linked, anyone, stub_gateway):
    invoice, token = linked
    stub_gateway.lose_next_answer = True
    first = anyone.post(f"/api/pay/{token}", data=json.dumps({"payment_token": "tok-u"}),
                        content_type="application/json")
    assert first.json()["status"] == "unknown"
    page = anyone.get(f"/api/pay/{token}").json()
    assert page["public_key"] == "" and "checking" in page["notice"]


@pytest.mark.django_db
def test_rate_limited_per_link(linked, anyone, stub_gateway):
    _, token = linked
    for _ in range(10):
        stub_gateway.refuse_next = ("300", "Card declined")
        anyone.post(f"/api/pay/{token}", data=json.dumps({"payment_token": "tok-r"}),
                    content_type="application/json")
    refused = anyone.post(f"/api/pay/{token}", data=json.dumps({"payment_token": "tok-r"}),
                          content_type="application/json")
    assert refused.status_code == 429 and len(sales(stub_gateway)) == 10
    for _ in range(60 - 11):
        anyone.get(f"/api/pay/{token}")
    assert anyone.get(f"/api/pay/{token}").status_code == 429


@pytest.mark.django_db
def test_guessing_links_from_one_address_is_cut_off(anyone):
    for n in range(120):
        assert anyone.get(f"/api/pay/guess-{n}").status_code == 404
    assert anyone.get("/api/pay/guess-last").status_code == 429


# ------------------------------------------------------ across practices

@pytest.mark.django_db
def test_each_link_names_its_own_practice(linked, tenant_b, anyone, api, stub_gateway):
    from apps.billing import services

    invoice_a, token_a = linked
    with tenant_context(tenant_b.pk):
        services.update_settings(tenant_b, {"pay_instructions": "Check."})
    ff_b = _member(tenant_b, "FF")
    with tenant_context(tenant_b.pk):
        from apps.billing import payment_accounts

        payment_accounts.connect(tenant_b, environment="sandbox", private_key="b-private-0000",
                                 public_key="b-public-1111", actor=ff_b.user)
    company, contact = a_client(tenant_b, name="Bravo Builders")
    invoice_b = ClientInvoice.all_objects.get(pk=sent(api, ff_b, company, contact)["id"])
    token_b = token_in(invoice_email(invoice_b).body_text)
    page_a = anyone.get(f"/api/pay/{token_a}").json()
    page_b = anyone.get(f"/api/pay/{token_b}").json()
    assert (page_a["public_key"], page_b["public_key"]) == (PUBLIC, "b-public-1111")
    assert page_b["practice"] == "Tenant B" and page_b["number"] == invoice_b.number
    anyone.post(f"/api/pay/{token_b}", data=json.dumps({"payment_token": "tok-b"}),
                content_type="application/json")
    [sale] = sales(stub_gateway)
    assert sale[1] == str(tenant_b.pk)
    invoice_a.refresh_from_db()
    assert invoice_a.status == "sent"


# ------------------------------------------------------- the merge field

@pytest.mark.django_db
def test_paylink_is_a_merge_field_in_the_library_and_the_invoice_email(connected, ff, api):
    templates.check("Pay here: {PayLink}")
    # Anywhere but an invoice email it reads as nothing, and its line goes.
    assert templates.render("Hi {FirstName}\nPay here: {PayLink}\nBye",
                            {"FirstName": "Dana"}) == "Hi Dana\nBye"
    saved = post(api, ff, "/api/invoice-settings/",
                 {"email_body": "Hi {FirstName},\n\nPay: {PayLink}\n\nThanks"})
    assert saved.status_code == 200, saved.content
    assert "PayLink" in saved.json()["merge_fields"]
    company, contact = a_client(connected)
    invoice = ClientInvoice.all_objects.get(pk=sent(api, ff, company, contact)["id"])
    body = invoice_email(invoice).body_text
    assert body.count("/pay/") == 1 and "Pay: http" in body


@pytest.mark.django_db
def test_wording_without_paylink_still_gets_the_link(connected, ff, api):
    post(api, ff, "/api/invoice-settings/", {"email_body": "Hi {FirstName}, attached."})
    company, contact = a_client(connected)
    invoice = ClientInvoice.all_objects.get(pk=sent(api, ff, company, contact)["id"])
    body = invoice_email(invoice).body_text
    assert "Pay this invoice online: http" in body and body.count("/pay/") == 1


def test_the_token_is_never_the_hash():
    # A sanity check on the scheme: what is stored cannot be sent back.
    assert pay_links._hash("abc") != "abc" and len(pay_links._hash("abc")) == 64
