"""P4 part 4: a card on file and auto-pay (`docs/p4_billing.md` §3.4).

Every test runs on the stub gateway (`conftest.stub_gateway`): no test
reaches NMI. The stub's vault is per practice account, as NMI's is.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.billing import autopay
from apps.billing.models import (
    AutopayConsent, ClientInvoice, ClientPayment, ClientPaymentMethod, PaymentAttempt,
)
from apps.crm.models import OutboxMessage
from apps.tenancy.context import acting_context, tenant_context

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import ContactEmailFactory, ContactFactory
from .test_card_payments import PRIVATE, connect, sales
from .test_card_payments import _after_commit_now  # noqa: F401  (autouse)
from .test_client_invoicing import ready_to_bill  # noqa: F401  (a fixture)
from .test_client_invoicing import a_client, draft, post, sent

ROOT = "/api/portal-autopay/"
A = PaymentAttempt.Status


@pytest.fixture
def connected(ready_to_bill, ff):  # noqa: F811
    connect(ready_to_bill, ff)
    return ready_to_bill


@pytest.fixture
def contact(connected, fcc):
    person = ContactFactory(tenant=connected, first_name="Dana", last_name="Reyes",
                            company=fcc.client_company)
    ContactEmailFactory(tenant=connected, contact=person, is_primary=True,
                        address="dana@client.invalid")
    return person


def save_card(api, who, token="tok-card"):
    return post(api, who, ROOT + "card/", {"payment_token": token})


def turn_on(api, who):
    return post(api, who, ROOT + "consent/",
                {"agree": True, "version": autopay.WORDING_VERSION})


def send_invoice(api, ff, fcc, contact, **more) -> ClientInvoice:
    invoice = ClientInvoice.all_objects.get(
        pk=sent(api, ff, fcc.client_company, contact, **more)["id"])
    return invoice


def due_today(invoice):
    today = timezone.localdate()
    ClientInvoice.all_objects.filter(pk=invoice.pk).update(due_date=today)
    invoice.refresh_from_db()
    return today


def run(tenant, today=None):
    with tenant_context(tenant.pk):
        return autopay.run(tenant, today=today or timezone.localdate())


def invoice_email(invoice):
    return (OutboxMessage.all_objects.filter(source_type="client_invoice",
                                             source_id=invoice.pk).order_by("-created_at")
            .first())


@pytest.fixture
def on(connected, fcc, contact, api):
    """A client owner has saved a card and turned auto-pay on."""
    assert save_card(api, fcc).status_code == 200
    assert turn_on(api, fcc).status_code == 200
    return fcc


# ------------------------------------------------------------- the card

@pytest.mark.django_db
def test_a_client_owner_saves_a_card_into_the_practices_vault(connected, fcc, api,
                                                              stub_gateway, seeded_tenant):
    response = save_card(api, fcc)
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["card"]["last4"] == "1111" and body["card"]["brand"] == "Visa"
    assert body["card"]["expires"] == "10/29" and body["autopay"] is None
    [call] = [c for c in stub_gateway.calls if c[0] == "vault_add"]
    assert call[1] == str(seeded_tenant.pk) and call[2]["payment_token"] == "tok-card"
    card = ClientPaymentMethod.all_objects.get()
    assert (card.client_company_id, card.added_by_id, card.exp_month, card.exp_year) == (
        fcc.client_company_id, fcc.user_id, 10, 2029)
    assert card.vault_id in stub_gateway.vault and PRIVATE not in json.dumps(body)


@pytest.mark.django_db
def test_a_new_card_replaces_the_old_which_leaves_the_vault(connected, fcc, api, stub_gateway):
    save_card(api, fcc, "tok-a")
    old = ClientPaymentMethod.all_objects.get()
    save_card(api, fcc, "tok-b")
    old.refresh_from_db()
    assert old.removed_at is not None and old.removed_by_id == fcc.user_id
    assert old.vault_id not in stub_gateway.vault
    assert ClientPaymentMethod.all_objects.filter(removed_at__isnull=True).count() == 1


@pytest.mark.django_db
def test_removing_the_card_turns_auto_pay_off_and_is_kept(on, api, stub_gateway):
    card = ClientPaymentMethod.all_objects.get()
    response = post(api, on, ROOT + "remove-card/")
    assert response.status_code == 200 and response.json()["card"] is None
    card.refresh_from_db()
    consent = AutopayConsent.all_objects.get()
    assert card.removed_at is not None and card.vault_id not in stub_gateway.vault
    assert consent.revoked_at is not None and consent.revoke_reason == "Card removed"


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["ECC"])
def test_a_client_team_member_cannot_save_a_card_or_consent(role, on, seeded_tenant, fcc,
                                                            api, stub_gateway):
    member = _member(seeded_tenant, role, company=fcc.client_company)
    assert api.as_(member).get(ROOT).status_code == 403
    assert save_card(api, member, "tok-x").status_code == 403
    assert post(api, member, ROOT + "revoke/").status_code == 403
    post(api, on, ROOT + "revoke/")
    assert turn_on(api, member).status_code == 403
    assert AutopayConsent.all_objects.filter(revoked_at__isnull=True).count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FF", "CF", "VA"])
def test_practice_staff_never_reach_it(role, connected, seeded_tenant, api, stub_gateway):
    staff = _member(seeded_tenant, role)
    assert api.as_(staff).get(ROOT).status_code == 404
    assert save_card(api, staff).status_code == 404
    assert ClientPaymentMethod.all_objects.count() == 0


@pytest.mark.django_db
def test_nothing_saved_or_agreed_while_acting_as_the_client(connected, fcc, ff, api,
                                                            stub_gateway):
    with tenant_context(fcc.tenant_id), acting_context(ff.user_id, fcc.user_id):
        with pytest.raises(autopay.AutopayRefused):
            autopay.save_card(fcc.client_company, user=fcc.user, payment_token="tok-z")
    assert [c for c in stub_gateway.calls if c[0] == "vault_add"] == []


@pytest.mark.django_db
def test_the_pay_link_never_saves_a_card(connected, ff, fcc, contact, api, stub_gateway):
    from django.test import Client

    invoice = send_invoice(api, ff, fcc, contact)
    token = invoice_email(invoice).body_text.split("/pay/")[1].split()[0]
    anyone = Client()
    assert anyone.post(f"/api/pay/{token}/card",
                       data=json.dumps({"payment_token": "t"}),
                       content_type="application/json").status_code == 404
    assert anyone.get(ROOT).status_code in (401, 403, 404)
    assert [c for c in stub_gateway.calls if c[0] == "vault_add"] == []


# ---------------------------------------------------------- the consent

@pytest.mark.django_db
def test_consent_keeps_who_when_the_words_their_version_address_and_browser(
        connected, fcc, contact, api):
    save_card(api, fcc)
    response = api.as_(fcc).post(ROOT + "consent/", data=json.dumps(
        {"agree": True, "version": autopay.WORDING_VERSION}),
        content_type="application/json", HTTP_USER_AGENT="Firefox/131", REMOTE_ADDR="203.0.113.9")
    assert response.status_code == 200 and response.json()["autopay"] is not None
    row = AutopayConsent.all_objects.get()
    assert row.consented_by_id == fcc.user_id and row.wording_version == "2026-10-21"
    assert row.wording == response.json()["wording"]
    assert fcc.client_company.name in row.wording and "due date" in row.wording
    assert (row.ip_address, row.user_agent) == ("203.0.113.9", "Firefox/131")


@pytest.mark.django_db
def test_consent_needs_the_box_the_current_wording_and_a_card(connected, fcc, api):
    assert post(api, fcc, ROOT + "consent/", {"version": autopay.WORDING_VERSION}
                ).status_code == 400
    assert turn_on(api, fcc).status_code == 409          # no card yet
    save_card(api, fcc)
    assert post(api, fcc, ROOT + "consent/", {"agree": True, "version": "2020-01-01"}
                ).status_code == 409
    assert turn_on(api, fcc).status_code == 200
    assert turn_on(api, fcc).status_code == 409          # already on


@pytest.mark.django_db
def test_revoking_is_kept(on, api):
    response = post(api, on, ROOT + "revoke/")
    assert response.status_code == 200 and response.json()["autopay"] is None
    row = AutopayConsent.all_objects.get()
    assert row.revoked_by_id == on.user_id and row.revoke_reason == "Turned off"


# ------------------------------------------------------------ the charge

@pytest.mark.django_db
def test_an_invoice_sent_after_consent_says_so_and_is_charged_on_its_due_date(
        on, ff, contact, api, seeded_tenant, stub_gateway):
    invoice = send_invoice(api, ff, on, contact)
    assert invoice.autopay_consent_id == AutopayConsent.all_objects.get().pk
    due = invoice.due_date
    assert (f"will be charged to the card ending 1111 on {due:%B} {due.day}, {due.year}"
            in invoice_email(invoice).body_text)
    # Not before its due date.
    assert run(seeded_tenant, due - timedelta(days=1))["charged"] == 0
    assert sales(stub_gateway) == []
    today = due_today(invoice)
    assert run(seeded_tenant, today)["charged"] == 1
    [sale] = sales(stub_gateway)
    card = ClientPaymentMethod.all_objects.get()
    assert sale[1] == str(seeded_tenant.pk) and sale[2]["vault_id"] == card.vault_id
    assert sale[2]["payment_token"] is None and sale[2]["amount_cents"] == 680000
    invoice.refresh_from_db()
    attempt = PaymentAttempt.all_objects.get(invoice=invoice)
    assert invoice.status == "paid" and attempt.via == "autopay"
    assert attempt.payment_method_id == card.pk
    assert "auto-pay" in ClientPayment.all_objects.get(invoice=invoice).note
    assert OutboxMessage.all_objects.filter(producer="payment_receipt",
                                            to_address=invoice.email_to).exists()


@pytest.mark.django_db
def test_the_job_is_safe_to_run_twice(on, ff, contact, api, seeded_tenant, stub_gateway):
    invoice = send_invoice(api, ff, on, contact)
    today = due_today(invoice)
    run(seeded_tenant, today)
    run(seeded_tenant, today)
    assert len(sales(stub_gateway)) == 1
    # Twice on a failure day too: one try that day.
    other = send_invoice(api, ff, on, contact)
    due_today(other)
    stub_gateway.refuse_next = ("300", "Do not honor")
    run(seeded_tenant, today)
    run(seeded_tenant, today)
    assert PaymentAttempt.all_objects.filter(invoice=other).count() == 1


@pytest.mark.django_db
def test_no_charge_for_an_invoice_sent_before_consent(connected, ff, fcc, contact, api,
                                                      seeded_tenant, stub_gateway):
    invoice = send_invoice(api, ff, fcc, contact)
    save_card(api, fcc)
    turn_on(api, fcc)
    assert "will be charged" not in invoice_email(invoice).body_text
    run(seeded_tenant, due_today(invoice))
    assert sales(stub_gateway) == []


@pytest.mark.django_db
def test_no_charge_without_consent(connected, ff, fcc, contact, api, seeded_tenant,
                                   stub_gateway):
    save_card(api, fcc)
    invoice = send_invoice(api, ff, fcc, contact)
    assert invoice.autopay_consent_id is None
    assert "will be charged" not in invoice_email(invoice).body_text
    run(seeded_tenant, due_today(invoice))
    assert sales(stub_gateway) == []


@pytest.mark.django_db
def test_no_charge_after_revocation(on, ff, contact, api, seeded_tenant, stub_gateway):
    invoice = send_invoice(api, ff, on, contact)
    post(api, on, ROOT + "revoke/")
    # Agreeing again later does not bring back an invoice sent under the old one.
    turn_on(api, on)
    run(seeded_tenant, due_today(invoice))
    assert sales(stub_gateway) == []
    invoice.refresh_from_db()
    assert invoice.status == "sent"


@pytest.mark.django_db
def test_the_practice_still_approves_every_send(on, ff, contact, api, seeded_tenant,
                                                stub_gateway):
    made = post(api, ff, "/api/invoices/", {"client_company": str(on.client_company_id),
                                           "contact": str(contact.pk), "lines": [
        {"description": "Retainer", "quantity": "1", "unit_price_cents": 500000}]}).json()
    assert post(api, ff, f"/api/invoices/{made['id']}/make-ready/").status_code == 200
    invoice = ClientInvoice.all_objects.get(pk=made["id"])
    assert invoice.status == "ready" and invoice_email(invoice).state == "pending_approval"
    run(seeded_tenant, due_today(invoice))
    assert sales(stub_gateway) == []


@pytest.mark.django_db
def test_one_companys_card_is_never_used_for_another(on, ff, contact, api, seeded_tenant,
                                                     stub_gateway):
    from apps.billing import card_payments

    other_company, other_contact = a_client(seeded_tenant, name="Other Co")
    other_owner = _member(seeded_tenant, "FCC", company=other_company)
    theirs = ClientInvoice.all_objects.get(
        pk=sent(api, ff, other_company, other_contact)["id"])
    # Their company has no card and no consent: the first company's is not used.
    assert theirs.autopay_consent_id is None
    run(seeded_tenant, due_today(theirs))
    assert sales(stub_gateway) == []
    card = ClientPaymentMethod.all_objects.get(client_company=on.client_company)
    with tenant_context(seeded_tenant.pk), pytest.raises(card_payments.PaymentRefused):
        card_payments.charge_on_file(theirs, card=card)
    # With their own card and consent, each is charged on its own card.
    save_card(api, other_owner, "tok-other")
    turn_on(api, other_owner)
    mine = send_invoice(api, ff, on, contact)
    theirs2 = ClientInvoice.all_objects.get(pk=sent(api, ff, other_company, other_contact)["id"])
    today = due_today(mine)
    due_today(theirs2)
    run(seeded_tenant, today)
    used = {s[2]["reference"]: s[2]["vault_id"] for s in sales(stub_gateway)}
    by_invoice = {a.invoice_id: str(a.pk) for a in PaymentAttempt.all_objects.all()}
    assert used[by_invoice[mine.pk]] == card.vault_id
    assert used[by_invoice[theirs2.pk]] == ClientPaymentMethod.all_objects.get(
        client_company=other_company, removed_at__isnull=True).vault_id


@pytest.mark.django_db
def test_another_practices_vault_is_never_charged(on, ff, contact, api, seeded_tenant,
                                                  tenant_b, stub_gateway):
    """A card is in its practice's own vault: the job of one practice never
    sees another's, and NMI (the stub) refuses a vault id from elsewhere."""
    invoice = send_invoice(api, ff, on, contact)
    today = due_today(invoice)
    with tenant_context(tenant_b.pk):
        assert autopay.run(tenant_b, today=today) == {"charged": 0, "expiry_notices": 0}
    assert sales(stub_gateway) == []


# -------------------------------------------------------------- failure

@pytest.mark.django_db
def test_a_failure_leaves_it_open_tells_both_sides_and_is_tried_once_more(
        on, ff, contact, api, seeded_tenant, stub_gateway):
    invoice = send_invoice(api, ff, on, contact)
    today = due_today(invoice)
    stub_gateway.refuse_next = ("300", "Do not honor")
    run(seeded_tenant, today)
    invoice.refresh_from_db()
    assert invoice.status == "sent" and invoice.balance_cents == 680000
    notices = list(OutboxMessage.all_objects.filter(
        producer__in=["autopay_notice", "payment_notice"]).values_list(
            "producer", "to_address", "body_text"))
    to_client = [n for n in notices if n[0] == "autopay_notice"]
    to_owner = [n for n in notices if n[0] == "payment_notice"]
    assert {n[1] for n in to_client} == {invoice.email_to, on.user.email}
    assert to_owner and to_owner[0][1] == ff.user.email
    assert all("tried once more tomorrow" in n[2] and "Do not honor" in n[2]
               for n in to_client + to_owner)

    # The next day, once more; and it goes through.
    first = PaymentAttempt.all_objects.get(invoice=invoice)
    PaymentAttempt.all_objects.filter(pk=first.pk).update(
        created_at=first.created_at - timedelta(days=1))
    run(seeded_tenant, today)
    invoice.refresh_from_db()
    assert invoice.status == "paid" and len(sales(stub_gateway)) == 2


@pytest.mark.django_db
def test_never_a_third_try(on, ff, contact, api, seeded_tenant, stub_gateway):
    invoice = send_invoice(api, ff, on, contact)
    today = due_today(invoice)
    for _ in range(3):
        stub_gateway.refuse_next = ("300", "Do not honor")
        run(seeded_tenant, today)
        PaymentAttempt.all_objects.update(created_at=timezone.now() - timedelta(days=2))
    assert PaymentAttempt.all_objects.filter(invoice=invoice).count() == 2
    last = OutboxMessage.all_objects.filter(producer="autopay_notice").order_by(
        "-created_at").first()
    assert "will not be tried again" in last.body_text
    invoice.refresh_from_db()
    assert invoice.status == "sent"


# --------------------------------------------------------------- expiry

@pytest.mark.django_db
def test_the_client_is_told_once_before_the_card_expires(connected, fcc, api, seeded_tenant,
                                                         stub_gateway):
    stub_gateway.vault_card_exp = "1126"          # ends November 30, 2026
    save_card(api, fcc)
    assert run(seeded_tenant, date(2026, 10, 30))["expiry_notices"] == 0
    assert run(seeded_tenant, date(2026, 11, 1))["expiry_notices"] == 1
    assert run(seeded_tenant, date(2026, 11, 2))["expiry_notices"] == 0
    notice = OutboxMessage.all_objects.get(producer="autopay_notice")
    assert notice.to_address == fcc.user.email
    assert "card ending 1111" in notice.body_text and "November 2026" in notice.body_text


@pytest.mark.django_db
def test_auto_pay_mail_never_reaches_an_assistant(on, ff, contact, api, seeded_tenant,
                                                  stub_gateway):
    invoice = send_invoice(api, ff, on, contact)
    stub_gateway.refuse_next = ("300", "Do not honor")
    run(seeded_tenant, due_today(invoice))
    va = _member(seeded_tenant, "VA")
    text = api.as_(va).get("/api/outbox/").content.decode()
    assert "Auto-pay" not in text and "could not charge" not in text


# ------------------------------------------- finding B5 (demo, 2026-10-22)

@pytest.mark.django_db
def test_the_practice_sees_auto_pay_on_the_form_the_preview_and_the_sent_invoice(
        on, ff, contact, api):
    """On the demo the email went with the sentence, but the invoice page's
    "The email as it will be sent" did not show it, and the practice had no
    line of its own saying the invoice would be charged."""
    made = draft(api, ff, on.client_company, contact).json()
    line = (f"Auto-pay is on for {on.client_company.name}: charged to Visa …1111 on the "
            "due date")
    assert made["autopay"]["line"] == line
    assert made["autopay"]["email_line"].startswith(
        "This invoice will be charged to the card ending 1111 on ")
    ready = post(api, ff, f"/api/invoices/{made['id']}/make-ready/").json()
    assert ready["autopay"]["line"] == line
    queued = invoice_email(ClientInvoice.all_objects.get(pk=made["id"]))
    assert ready["autopay"]["email_line"] in queued.body_text, "the preview is the email"
    done = post(api, ff, f"/api/invoices/{made['id']}/send/").json()
    assert done["status"] == "sent" and done["autopay"] == {"line": line, "email_line": ""}
    # Turned off: the sent invoice will not be charged, and no longer says so.
    post(api, on, ROOT + "revoke/")
    assert api.as_(ff).get(f"/api/invoices/{made['id']}/").json()["autopay"] is None


@pytest.mark.django_db
def test_no_line_without_a_card_and_consent(connected, ff, fcc, contact, api):
    made = draft(api, ff, fcc.client_company, contact).json()
    assert made["autopay"] is None
    save_card(api, fcc)
    assert api.as_(ff).get(f"/api/invoices/{made['id']}/").json()["autopay"] is None


@pytest.mark.django_db
def test_auto_pay_turned_on_while_the_email_waits_is_said_when_it_is_sent(
        connected, ff, fcc, contact, api, seeded_tenant, stub_gateway):
    """Ready before consent, sent after: the waiting email is queued again, so
    it says when the card will be charged, and the invoice is charged."""
    made = draft(api, ff, fcc.client_company, contact).json()
    post(api, ff, f"/api/invoices/{made['id']}/make-ready/")
    invoice = ClientInvoice.all_objects.get(pk=made["id"])
    assert "will be charged" not in invoice_email(invoice).body_text
    save_card(api, fcc)
    turn_on(api, fcc)
    assert post(api, ff, f"/api/invoices/{made['id']}/send/").status_code == 200
    invoice.refresh_from_db()
    assert "will be charged to the card ending 1111" in invoice_email(invoice).body_text
    assert invoice_email(invoice).state == OutboxMessage.State.SENT
    assert invoice.autopay_consent_id == AutopayConsent.all_objects.get().pk
    run(seeded_tenant, due_today(invoice))
    assert len(sales(stub_gateway)) == 1
