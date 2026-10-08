"""P4A — client invoicing without a processor (`docs/p4a_client_invoicing.md`).

1. Practice isolation.
2. Role boundaries: the matrix of §5.1, and every place of §5.2 where an
   invoice could reach an assistant.
3. Numbers, money, sending, the frozen document, recurring drafts, payments,
   void and overdue.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.billing import services
from apps.billing.models import (
    ClientInvoice, ClientInvoiceSchedule, ClientPayment, InvoiceSettings,
)
from apps.crm.models import EmailMessage, EmailThread, OutboxMessage
from apps.tenancy.context import tenant_context
from apps.tenancy.models import AuditEvent

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import (
    ClientAssignmentFactory, ClientCompanyFactory, ContactEmailFactory, ContactFactory,
)
from .test_platform_isolation import in_practices_area

ROOT = "/api/invoices/"
LINES = [{"description": "Monthly retainer", "quantity": "1", "unit_price_cents": 500000},
         {"description": "Workshop, half day", "quantity": "1.5", "unit_price_cents": 120000}]
TOTAL = 500000 + 180000


def post(api, who, url, body=None):
    return api.as_(who).post(url, data=json.dumps(body or {}),
                             content_type="application/json")


def patch(api, who, url, body):
    return api.as_(who).patch(url, data=json.dumps(body), content_type="application/json")


def get(api, who, url):
    return api.as_(who).get(url)


def a_client(tenant, name="Acme Facilities", first="Dana", address=None):
    company = ClientCompanyFactory(tenant=tenant, name=name)
    contact = ContactFactory(tenant=tenant, first_name=first, last_name="Reyes",
                             company=company)
    ContactEmailFactory(tenant=tenant, contact=contact, is_primary=True,
                        address=address or f"{first.lower()}@{name.split()[0].lower()}.invalid")
    return company, contact


@pytest.fixture
def ready_to_bill(seeded_tenant):
    with tenant_context(seeded_tenant.pk):
        services.update_settings(seeded_tenant, {
            "pay_instructions": "Bank transfer to Example Bank, account ending 4421."})
    return seeded_tenant


@pytest.fixture
def acme(ready_to_bill):
    return a_client(ready_to_bill)


@pytest.fixture
def ecc(seeded_tenant, fcc):
    return _member(seeded_tenant, "ECC", company=fcc.client_company)


def draft(api, who, company, contact, **more):
    return post(api, who, ROOT, {"client_company": str(company.pk), "contact": str(contact.pk),
                                 "lines": LINES, **more})


def sent(api, ff, company, contact, **more):
    """An invoice written, made ready and sent by the practice owner."""
    made = draft(api, ff, company, contact, **more).json()
    assert post(api, ff, f"{ROOT}{made['id']}/make-ready/").status_code == 200
    done = post(api, ff, f"{ROOT}{made['id']}/send/")
    assert done.status_code == 200, done.content
    return done.json()


def staff_calls(invoice_id):
    """Every staff route, with a body the practice owner could send."""
    one = f"{ROOT}{invoice_id}/"
    return [
        ("get", ROOT, None), ("get", ROOT + "export/", None), ("get", one, None),
        ("get", one + "pdf/", None), ("get", one + "preview/", None),
        ("get", one + "history/", None),
        ("patch", one, {"notes": "Changed"}), ("post", one + "make-ready/", {}),
        ("post", one + "back-to-draft/", {}), ("post", one + "queue-again/", {}),
        ("post", one + "send/", {}),
        ("post", one + "payments/", {"amount_cents": 100, "paid_on": "2026-10-02"}),
        ("post", one + "remove-payment/", {"payment": "x", "reason": "y"}),
        ("post", one + "void/", {"reason": "Mistake"}),
        ("delete", one, None),
        ("get", "/api/invoice-settings/", None),
        ("post", "/api/invoice-settings/", {"prefix": "X-"}),
        ("get", "/api/invoice-schedules/", None),
        ("post", "/api/invoice-schedules/", {"day_of_month": 1, "lines": LINES}),
    ]


def call(client, method, url, body):
    if method == "get":
        return client.get(url)
    if method == "delete":
        return client.delete(url)
    return getattr(client, method)(url, data=json.dumps(body or {}),
                                   content_type="application/json")


def snapshot(tenant):
    """Everything invoicing holds for a practice, for "nothing changed"."""
    with tenant_context(tenant.pk):
        return json.dumps({
            "invoices": list(ClientInvoice.objects.order_by("created_at").values(
                "pk", "status", "number", "total_cents", "paid_cents", "notes")),
            "payments": list(ClientPayment.objects.order_by("created_at").values(
                "pk", "amount_cents", "removed_at")),
            "settings": list(InvoiceSettings.objects.values("prefix", "next_value")),
            "schedules": ClientInvoiceSchedule.objects.count(),
            "outbox": list(OutboxMessage.objects.filter(producer="client_invoice")
                           .order_by("created_at").values("pk", "state")),
        }, default=str, sort_keys=True)


# ========================================================= practice isolation

@pytest.mark.django_db
def test_tenant_isolation_another_practice_reaches_no_invoice(acme, ff, tenant_b, api):
    invoice = sent(api, ff, *acme)
    other = _member(tenant_b, "FF")
    with tenant_context(tenant_b.pk):
        services.update_settings(tenant_b, {"pay_instructions": "By check."})
    before = snapshot(acme[0].tenant)
    listed = get(api, other, ROOT).json()
    assert listed["invoices"] == [] and listed["totals"]["invoiced_cents"] == 0
    for method, url, body in staff_calls(invoice["id"]):
        if url in (ROOT, ROOT + "export/") or "settings" in url or "schedules" in url:
            continue
        response = call(api.as_(other), method, url, body)
        assert response.status_code == 404, (method, url)
        assert invoice["number"].encode() not in response.content
    assert "Acme" not in get(api, other, ROOT + "export/").content.decode()
    assert snapshot(acme[0].tenant) == before
    # Their own first invoice is their own INV-0001, to their own client.
    theirs = sent(api, other, *a_client(tenant_b, "Bravo Works", "Sam"))
    assert theirs["number"] == "INV-0001" == invoice["number"]
    # And a company or a contact from here cannot be billed from there.
    assert draft(api, other, *acme).status_code == 404


@pytest.mark.django_db
def test_tenant_isolation_the_platform_owner_reaches_no_invoice(acme, ff, seeded_tenant, api):
    invoice = sent(api, ff, *acme)
    owner = _member(seeded_tenant, "FF")
    owner.user.is_platform_owner = True
    owner.user.save()
    client = in_practices_area(api.as_(owner))
    before = snapshot(seeded_tenant)
    for method, url, body in staff_calls(invoice["id"]) + [
            ("get", "/api/portal-invoices/", None)]:
        response = call(client, method, url, body)
        assert response.status_code in (403, 404), (method, url)
        assert b"Acme" not in response.content
    assert snapshot(seeded_tenant) == before


@pytest.mark.django_db
def test_tenant_isolation_a_clients_portal_shows_only_its_own_company(acme, ff, fcc, tenant_b,
                                                                     api):
    sent(api, ff, *acme)
    other_company, other_contact = a_client(tenant_b, "Bravo Works", "Sam")
    stranger = _member(tenant_b, "FCC", company=other_company)
    assert get(api, stranger, "/api/portal-invoices/").json() == []


# ============================================================ role boundaries

@pytest.mark.django_db
def test_role_boundaries_an_assistant_reaches_no_invoice_route(acme, ff, va, api):
    """The non-negotiable family: an assistant and any financial endpoint."""
    invoice = draft(api, ff, *acme).json()
    before = snapshot(acme[0].tenant)
    for method, url, body in staff_calls(invoice["id"]) + [
            ("post", ROOT, {"client_company": str(acme[0].pk), "contact": str(acme[1].pk),
                            "lines": LINES})]:
        response = call(api.as_(va), method, url, body)
        assert response.status_code == 403, (method, url)
        assert b"500000" not in response.content and b"Monthly retainer" not in response.content
    assert get(api, va, "/api/portal-invoices/").status_code == 404
    assert snapshot(acme[0].tenant) == before


@pytest.mark.django_db
def test_role_boundaries_an_assistant_sees_no_invoice_email_anywhere(acme, ff, va, cf, api):
    """§5.2, row by row. One invoice waiting to be sent and one sent."""
    company, contact = acme
    waiting = draft(api, ff, company, contact).json()
    post(api, ff, f"{ROOT}{waiting['id']}/make-ready/")
    done = sent(api, ff, company, contact)
    with tenant_context(company.tenant_id):
        messages = list(OutboxMessage.objects.filter(producer="client_invoice"))
        assert len(messages) == 2
        thread = EmailThread.objects.get(is_financial=True)
        assert EmailMessage.objects.filter(thread=thread).count() == 1
    marks = ("INV-0001", "INV-0002", "Invoice INV", "6,800")

    def clean(who, url):
        body = get(api, who, url).content.decode()
        return not any(mark in body for mark in marks)

    for who in (va, cf):      # an assistant, and an associate not assigned here
        # The Outbox, the send log and the Sending queue.
        assert clean(who, "/api/outbox/")
        assert clean(who, "/api/sending-queue/")
        for message in messages:
            assert get(api, who, f"/api/outbox/{message.pk}/").status_code == 404
            assert post(api, who, f"/api/outbox/{message.pk}/reject/").status_code == 404
        # The client's shared history: threads, the contact's and the company's.
        assert clean(who, "/api/email-threads/")
        assert get(api, who, f"/api/email-threads/{thread.pk}/").status_code == 404
        assert clean(who, f"/api/contacts/{contact.pk}/timeline/")
        assert clean(who, f"/api/companies/{company.pk}/timeline/")
        # The activity feed, the dashboard and search.
        assert clean(who, "/api/activity/")
        assert clean(who, "/api/dashboard/")
        assert clean(who, "/api/contacts/?search=INV-0001")
        assert clean(who, "/api/contacts/?search=Invoice")
    # The practice owner sees all of it, so the checks above are not vacuous.
    assert not clean(ff, "/api/outbox/") and not clean(ff, "/api/sending-queue/")
    assert not clean(ff, f"/api/contacts/{contact.pk}/timeline/")
    assert get(api, ff, f"/api/email-threads/{thread.pk}/").status_code == 200
    assert done["status"] == "sent"


@pytest.mark.django_db
def test_role_boundaries_ordinary_mail_never_lands_on_an_invoices_thread(acme, ff, va, api):
    """Otherwise an ordinary email to the same contact would vanish from an
    assistant's view of the client."""
    from apps.crm.services import outbox

    company, contact = acme
    sent(api, ff, company, contact)
    with tenant_context(company.tenant_id):
        message = outbox.create_message(
            tenant=company.tenant, producer=OutboxMessage.Producer.MANUAL,
            to_address="dana@acme.invalid", to_contact=contact, subject="Thursday's agenda",
            body_text="See you then.", role="FF", actor=ff.user)
        assert message.thread.is_financial is False
    assert "Thursday's agenda" in get(api, va, "/api/outbox/").content.decode()
    assert "Thursday's agenda" in get(
        api, va, f"/api/contacts/{contact.pk}/timeline/").content.decode()


@pytest.mark.django_db
def test_role_boundaries_an_associate_has_assigned_client_companies_only(acme, ff, cf, api):
    company, contact = acme
    elsewhere = a_client(company.tenant, "Bravo Works", "Sam")
    ClientAssignmentFactory(tenant=company.tenant, user=cf.user, company=company)
    mine = sent(api, ff, company, contact)
    theirs = sent(api, ff, *elsewhere)
    to_a_contact = post(api, ff, ROOT, {"kind": "contact", "contact": str(contact.pk),
                                        "lines": LINES}).json()
    # The list, its totals and its export are what they may see, no more.
    listed = get(api, cf, ROOT).json()
    assert [row["id"] for row in listed["invoices"]] == [mine["id"]]
    assert listed["totals"]["invoiced_cents"] == TOTAL
    assert get(api, ff, ROOT).json()["totals"]["invoiced_cents"] == 2 * TOTAL
    assert "Bravo" not in get(api, cf, ROOT + "export/").content.decode()
    for hidden in (theirs, to_a_contact):
        for suffix in ("", "pdf/", "history/", "preview/"):
            assert get(api, cf, f"{ROOT}{hidden['id']}/{suffix}").status_code == 404
    assert get(api, cf, f"{ROOT}{mine['id']}/pdf/").status_code == 200
    # They draft and make ready for an assigned company, and never send.
    own = draft(api, cf, company, contact)
    assert own.status_code == 201
    assert draft(api, cf, *elsewhere).status_code == 404
    assert post(api, cf, ROOT, {"kind": "contact", "contact": str(contact.pk),
                                "lines": LINES}).status_code == 403
    one = f"{ROOT}{own.json()['id']}/"
    ready = post(api, cf, one + "make-ready/")
    assert ready.status_code == 200 and ready.json()["status"] == "ready"
    before = snapshot(company.tenant)
    assert post(api, cf, one + "send/").status_code == 403
    paid = f"{ROOT}{mine['id']}/"
    assert post(api, cf, paid + "payments/", {"amount_cents": 100,
                                              "paid_on": "2026-10-02"}).status_code == 403
    assert post(api, cf, paid + "void/", {"reason": "x"}).status_code == 403
    assert post(api, cf, "/api/invoice-settings/", {"prefix": "X-"}).status_code == 403
    assert snapshot(company.tenant) == before
    # Nor through the Sending queue or the Outbox: 13.4c is the practice owner's.
    with tenant_context(company.tenant_id):
        message = ClientInvoice.objects.get(pk=own.json()["id"]).outbox_message
    assert post(api, cf, f"/api/outbox/{message.pk}/approve/").status_code == 403
    assert snapshot(company.tenant) == before
    assert post(api, ff, f"/api/outbox/{message.pk}/approve/").status_code == 200
    assert get(api, cf, one).json()["status"] == "sent"


@pytest.mark.django_db
def test_role_boundaries_client_users_see_their_companys_sent_invoices(ready_to_bill, ff, fcc,
                                                                      ecc, api):
    tenant, company = ready_to_bill, fcc.client_company
    contact = ContactFactory(tenant=tenant, first_name="Dana", company=company)
    ContactEmailFactory(tenant=tenant, contact=contact, address="dana@client.invalid")
    elsewhere = a_client(tenant, "Bravo Works", "Sam")
    mine = sent(api, ff, company, contact)
    void = sent(api, ff, company, contact)
    post(api, ff, f"{ROOT}{void['id']}/void/", {"reason": "Wrong month"})
    still_draft = draft(api, ff, company, contact).json()
    only_ready = draft(api, ff, company, contact).json()
    post(api, ff, f"{ROOT}{only_ready['id']}/make-ready/")
    other = sent(api, ff, *elsewhere)
    # Written to the person, not the company: in no portal, even theirs.
    personal = post(api, ff, ROOT, {"kind": "contact", "contact": str(contact.pk),
                                    "lines": LINES}).json()
    post(api, ff, f"{ROOT}{personal['id']}/make-ready/")
    post(api, ff, f"{ROOT}{personal['id']}/send/")
    post(api, ff, f"{ROOT}{mine['id']}/payments/",
         {"amount_cents": 100000, "paid_on": "2026-10-02", "reference": "CHK 2231",
          "note": "PRACTICE-ONLY-NOTE"})

    for who in (fcc, ecc):       # D8: a client team member as well
        rows = get(api, who, "/api/portal-invoices/")
        assert rows.status_code == 200
        shown = {row["id"]: row for row in rows.json()}
        assert set(shown) == {mine["id"], void["id"]}
        assert shown[mine["id"]]["status"] == "partially_paid"
        assert shown[mine["id"]]["balance_cents"] == TOTAL - 100000
        assert shown[void["id"]]["status"] == "void"
        # The balance and the status; never the payments or the practice's notes (I9).
        body = rows.content.decode()
        assert "CHK 2231" not in body and "PRACTICE-ONLY-NOTE" not in body
        assert "payments" not in body and "email_body" not in body
        pdf = get(api, who, f"/api/portal-invoices/{mine['id']}/pdf/")
        assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
        for hidden in (still_draft, only_ready, other, personal):
            assert get(api, who, f"/api/portal-invoices/{hidden['id']}/pdf/"
                       ).status_code == 404, hidden["status"]
        # And nothing of the practice's own side.
        for method, url, body in staff_calls(mine["id"]):
            assert call(api.as_(who), method, url, body).status_code == 404, (method, url)


# ==================================================================== numbers

@pytest.mark.django_db
def test_a_draft_has_no_number_and_ready_gives_the_next_one_for_good(acme, ff, api):
    first = draft(api, ff, *acme).json()
    thrown = draft(api, ff, *acme).json()
    assert first["number"] == "" and first["status"] == "draft"
    # A draft thrown away never had a number, so it leaves no gap.
    assert api.as_(ff).delete(f"{ROOT}{thrown['id']}/").status_code == 204
    ready = post(api, ff, f"{ROOT}{first['id']}/make-ready/").json()
    assert ready["number"] == "INV-0001" and ready["status"] == "ready"
    second = draft(api, ff, *acme).json()
    assert post(api, ff, f"{ROOT}{second['id']}/make-ready/").json()["number"] == "INV-0002"
    # Reopened, it keeps its number; made ready again, it has the same one.
    reopened = post(api, ff, f"{ROOT}{first['id']}/back-to-draft/").json()
    assert (reopened["status"], reopened["number"]) == ("draft", "INV-0001")
    assert patch(api, ff, f"{ROOT}{first['id']}/", {"notes": "Now with a note"}
                 ).status_code == 200
    again = post(api, ff, f"{ROOT}{first['id']}/make-ready/").json()
    assert again["number"] == "INV-0001"
    # A numbered invoice is never deleted, draft or not.
    post(api, ff, f"{ROOT}{first['id']}/back-to-draft/")
    refused = api.as_(ff).delete(f"{ROOT}{first['id']}/")
    assert refused.status_code == 409 and "Void it" in refused.json()["detail"]
    third = draft(api, ff, *acme).json()
    assert post(api, ff, f"{ROOT}{third['id']}/make-ready/").json()["number"] == "INV-0003"


@pytest.mark.django_db
def test_twenty_made_ready_take_twenty_consecutive_numbers(acme, ff, api):
    ids = [draft(api, ff, *acme).json()["id"] for _ in range(20)]
    numbers = [post(api, ff, f"{ROOT}{pk}/make-ready/").json()["number"]
               for pk in reversed(ids)]
    assert numbers == [f"INV-{n:04d}" for n in range(1, 21)]
    with tenant_context(acme[0].tenant_id):
        assert InvoiceSettings.objects.get().next_value == 21
        assert ClientInvoice.objects.exclude(number=None).count() == 20


@pytest.mark.django_db(transaction=True)
def test_numbers_do_not_repeat_when_made_ready_at_the_same_moment(tenant_a):
    """Real concurrency, on real connections: the lock on the practice's
    counter is what this proves."""
    import threading

    from django.db import connection

    with tenant_context(tenant_a.pk):
        services.update_settings(tenant_a, {"pay_instructions": "By check."})
        company, contact = a_client(tenant_a)
        owner = _member(tenant_a, "FF")
        invoices = [services.create_draft(tenant_a, actor=owner.user, client_company=company,
                                          contact=contact, lines=LINES) for _ in range(6)]
    failures = []

    def ready(invoice):
        try:
            with tenant_context(tenant_a.pk):
                services.make_ready(invoice, actor=owner.user, role="FF")
        except Exception as exc:  # noqa: BLE001
            failures.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=ready, args=(invoice,)) for invoice in invoices]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert failures == []
    with tenant_context(tenant_a.pk):
        numbers = sorted(ClientInvoice.objects.values_list("number", flat=True))
    assert numbers == [f"INV-{n:04d}" for n in range(1, 7)]


@pytest.mark.django_db
def test_the_prefix_changes_and_the_next_number_is_raised_never_lowered(acme, ff, api):
    assert post(api, ff, "/api/invoice-settings/",
                {"prefix": "EN-", "next_value": 250}).json()["next_number"] == "EN-0250"
    made = draft(api, ff, *acme).json()
    assert post(api, ff, f"{ROOT}{made['id']}/make-ready/").json()["number"] == "EN-0250"
    lower = post(api, ff, "/api/invoice-settings/", {"next_value": 100})
    assert lower.status_code == 400 and "not lowered" in lower.json()["detail"]
    for bad in ({"prefix": "way too long a prefix"}, {"prefix": "a b"}, {"next_value": 0},
                {"next_value": "9"}, {"terms_days": 400}, {"email_body": "Hi {Nobody}"},
                {"nonsense": 1}):
        assert post(api, ff, "/api/invoice-settings/", bad).status_code == 400, bad


# ====================================================================== money

@pytest.mark.django_db
def test_amounts_are_whole_cents_and_add_up(acme, ff, api):
    made = draft(api, ff, *acme, tax_cents=1234, lines=[
        {"description": "Hours", "quantity": "2.75", "unit_price_cents": 19999},
        {"description": "A third of a day", "quantity": "0.33", "unit_price_cents": 100001},
    ]).json()
    # 2.75 x 199.99 = 549.9725, and 0.33 x 1000.01 = 330.0033: each rounded once.
    assert [line["amount_cents"] for line in made["lines"]] == [54997, 33000]
    assert (made["subtotal_cents"], made["tax_cents"], made["total_cents"]) == (
        87997, 1234, 89231)
    assert made["balance_cents"] == 89231
    for bad in ({"quantity": "1", "unit_price_cents": 19.99},
                {"quantity": "1", "unit_price_cents": "1999"},
                {"quantity": "1", "unit_price_cents": -1},
                {"quantity": "-1", "unit_price_cents": 100},
                {"quantity": "lots", "unit_price_cents": 100}):
        refused = draft(api, ff, *acme, lines=[{"description": "x", **bad}])
        assert refused.status_code == 400, bad
    assert draft(api, ff, *acme, lines=[{"description": " ", "quantity": "1",
                                         "unit_price_cents": 1}]).status_code == 400
    assert draft(api, ff, *acme, tax_cents=1.5).status_code == 400
    assert draft(api, ff, *acme, lines=[{"description": "x", "quantity": "1",
                                         "unit_price_cents": 1}] * 51).status_code == 400


@pytest.mark.django_db
def test_an_invoice_needs_a_line_an_amount_a_recipient_and_how_to_pay(seeded_tenant, ff, api):
    company, contact = a_client(seeded_tenant)
    nothing = draft(api, ff, company, contact, lines=[]).json()
    one = f"{ROOT}{nothing['id']}/make-ready/"
    assert "at least one line" in post(api, ff, one).json()["detail"]
    patch(api, ff, f"{ROOT}{nothing['id']}/", {"lines": [
        {"description": "Free", "quantity": "1", "unit_price_cents": 0}]})
    assert "for nothing" in post(api, ff, one).json()["detail"]
    patch(api, ff, f"{ROOT}{nothing['id']}/", {"lines": LINES})
    # I6: no payment instructions, no invoice.
    refused = post(api, ff, one)
    assert refused.status_code == 400 and "how to pay" in refused.json()["detail"]
    post(api, ff, "/api/invoice-settings/", {"pay_instructions": "By check."})
    assert post(api, ff, one).status_code == 200
    # Someone with no email address cannot be sent one.
    silent = ContactFactory(tenant=seeded_tenant, company=company)
    other = draft(api, ff, company, silent).json()
    assert "no email address" in post(api, ff, f"{ROOT}{other['id']}/make-ready/"
                                      ).json()["detail"]
    # Addressed to someone at that client company, which is a client company.
    stranger = ContactFactory(tenant=seeded_tenant)
    assert draft(api, ff, company, stranger).status_code == 400
    from .factories import CompanyFactory
    prospect_company = CompanyFactory(tenant=seeded_tenant, name="Not a client")
    prospect = ContactFactory(tenant=seeded_tenant, company=prospect_company)
    refused = draft(api, ff, prospect_company, prospect)
    assert refused.status_code == 400 and "not a client company" in refused.json()["detail"]
    assert draft(api, ff, company, contact, due_date="2020-01-01").status_code == 400


# ==================================================================== sending

@pytest.mark.django_db
def test_making_ready_sends_nothing_and_the_owners_send_does(acme, ff, api, dev_outbox):
    company, contact = acme
    made = draft(api, ff, company, contact).json()
    ready = post(api, ff, f"{ROOT}{made['id']}/make-ready/").json()
    assert ready["status"] == "ready" and ready["send_state"] == "waiting"
    assert ready["has_pdf"] and ready["sent_at"] is None
    assert len(dev_outbox) == 0, "making ready sends nothing"
    with tenant_context(company.tenant_id):
        invoice = ClientInvoice.objects.get(pk=made["id"])
        message = invoice.outbox_message
        assert message.state == "pending_approval" and message.producer == "client_invoice"
        assert message.to_address == "dana@acme.invalid"
        assert message.subject == "Invoice INV-0001 from Tenant A"
        assert "Hi Dana," in message.body_text and "$6,800.00" in message.body_text
        assert "October" in message.body_text and "{" not in message.body_text
        # The PDF attached is the PDF stored, with real bytes in it.
        attached = message.attachments.get()
        assert attached.stored_file_id == invoice.pdf_id
        assert attached.filename == "Invoice-INV-0001.pdf"
        assert message.thread.is_financial and message.thread.client_company_id == company.pk
    # It shows in the Sending queue for the practice owner to approve.
    assert "INV-0001" in get(api, ff, "/api/sending-queue/").content.decode()
    done = post(api, ff, f"{ROOT}{made['id']}/send/").json()
    assert done["status"] == "sent" and done["sent_at"] and done["send_state"] == ""
    assert len(dev_outbox) == 1
    mail = dev_outbox[0]
    assert mail.to == ["dana@acme.invalid"]
    name, content, mimetype = mail.attachments[0]
    assert name == "Invoice-INV-0001.pdf" and mimetype == "application/pdf"
    assert content[:4] == b"%PDF" and len(content) > 2000
    assert get(api, ff, f"{ROOT}{made['id']}/pdf/").content == content
    history = [row["what"] for row in get(api, ff, f"{ROOT}{made['id']}/history/").json()]
    assert history == ["invoice_created", "invoice_ready", "invoice_sent"]


@pytest.mark.django_db
def test_approving_in_the_sending_queue_marks_the_invoice_sent(acme, ff, api, dev_outbox):
    made = draft(api, ff, *acme).json()
    post(api, ff, f"{ROOT}{made['id']}/make-ready/")
    with tenant_context(acme[0].tenant_id):
        message = ClientInvoice.objects.get(pk=made["id"]).outbox_message
    assert post(api, ff, f"/api/outbox/{message.pk}/approve/").status_code == 200
    assert get(api, ff, f"{ROOT}{made['id']}/").json()["status"] == "sent"
    assert len(dev_outbox) == 1


@pytest.mark.django_db
def test_a_send_that_is_sent_back_leaves_the_invoice_ready_and_unsent(acme, ff, api,
                                                                    dev_outbox):
    made = draft(api, ff, *acme).json()
    post(api, ff, f"{ROOT}{made['id']}/make-ready/")
    with tenant_context(acme[0].tenant_id):
        message = ClientInvoice.objects.get(pk=made["id"]).outbox_message
    assert post(api, ff, f"/api/outbox/{message.pk}/reject/").status_code == 200
    back = get(api, ff, f"{ROOT}{made['id']}/").json()
    assert (back["status"], back["send_state"], back["number"]) == (
        "ready", "sent_back", "INV-0001")
    assert len(dev_outbox) == 0
    # Queued again with the same PDF, or reopened; either way one number.
    again = post(api, ff, f"{ROOT}{made['id']}/queue-again/").json()
    assert again["send_state"] == "waiting"
    assert post(api, ff, f"{ROOT}{made['id']}/back-to-draft/").json()["status"] == "draft"
    with tenant_context(acme[0].tenant_id):
        states = list(OutboxMessage.objects.filter(producer="client_invoice")
                      .order_by("created_at").values_list("state", flat=True))
    assert states == ["rejected", "rejected"], "the waiting message is withdrawn"


@pytest.mark.django_db
def test_an_invoices_message_cannot_be_edited_in_the_outbox(acme, ff, api):
    made = draft(api, ff, *acme).json()
    post(api, ff, f"{ROOT}{made['id']}/make-ready/")
    with tenant_context(acme[0].tenant_id):
        message = ClientInvoice.objects.get(pk=made["id"]).outbox_message
    refused = patch(api, ff, f"/api/outbox/{message.pk}/edit/", {"subject": "Pay up"})
    assert refused.status_code == 409 and "back to draft" in refused.json()["detail"]
    with tenant_context(acme[0].tenant_id):
        assert OutboxMessage.objects.get(pk=message.pk).subject != "Pay up"


@pytest.mark.django_db
def test_a_resend_goes_to_another_address_and_makes_no_new_invoice(acme, ff, api, dev_outbox):
    invoice = sent(api, ff, *acme)
    again = post(api, ff, f"{ROOT}{invoice['id']}/send/",
                 {"to_address": "accounts@acme.invalid"}).json()
    assert again["number"] == "INV-0001" and again["status"] == "sent"
    assert [mail.to for mail in dev_outbox] == [["dana@acme.invalid"],
                                                ["accounts@acme.invalid"]]
    assert dev_outbox[0].attachments[0][1] == dev_outbox[1].attachments[0][1]
    with tenant_context(acme[0].tenant_id):
        assert ClientInvoice.objects.count() == 1
    assert get(api, ff, f"{ROOT}{invoice['id']}/history/").json()[-1]["what"] == \
        "invoice_resent"


@pytest.mark.django_db
def test_nothing_is_made_ready_or_sent_while_acting_as_someone(acme, ff, api, dev_outbox):
    from apps.tenancy.context import acting_context

    made = draft(api, ff, *acme).json()
    with tenant_context(acme[0].tenant_id):
        invoice = ClientInvoice.objects.get(pk=made["id"])
        with acting_context(ff.user.pk, ff.user.pk):
            with pytest.raises(services.BillingError):
                services.make_ready(invoice, actor=ff.user, role="FF")
        assert ClientInvoice.objects.get(pk=made["id"]).number is None
    assert len(dev_outbox) == 0


# ===================================================== the document as sent

@pytest.mark.django_db
def test_the_invoice_and_its_pdf_do_not_change_after_it_is_ready(acme, ff, api):
    company, contact = acme
    invoice = sent(api, ff, company, contact, bill_to_address="12 Main Street\nDenver, CO")
    one = f"{ROOT}{invoice['id']}/"
    before, pdf_before = get(api, ff, one).json(), get(api, ff, one + "pdf/").content
    assert before["bill_to"] == {"name": "Dana Reyes", "company": "Acme Facilities",
                                 "email": "dana@acme.invalid",
                                 "address": "12 Main Street\nDenver, CO"}
    # The contact, the company, the practice's name and the settings all change.
    with tenant_context(company.tenant_id):
        contact.first_name, contact.last_name = "Danielle", "Reyes-Okafor"
        contact.save()
        company.name = "Acme Holdings"
        company.save()
        company.tenant.name = "Renamed Practice"
        company.tenant.save()
        services.update_settings(company.tenant, {
            "pay_instructions": "Something else entirely.", "default_terms": "Net 60"})
    after = get(api, ff, one).json()
    for field in ("bill_to", "pay_instructions", "terms", "email_subject", "email_body",
                  "lines", "total_cents", "number", "due_date"):
        assert after[field] == before[field], field
    assert get(api, ff, one + "pdf/").content == pdf_before, "stored once, never remade"
    # And it cannot be edited: it is voided and a new one written.
    refused = patch(api, ff, one, {"notes": "Slipped in later"})
    assert refused.status_code == 409 and "Void it" in refused.json()["detail"]
    assert api.as_(ff).delete(one).status_code == 409


@pytest.mark.django_db
def test_the_pdf_prints_what_the_invoice_says_and_no_pay_link(acme, ff, api):
    from apps.billing import pdf

    invoice = sent(api, ff, *acme, tax_cents=5000, notes="Thank you for your business.",
                   terms="Net 15.")
    with tenant_context(acme[0].tenant_id):
        html = pdf.render_html(ClientInvoice.objects.get(pk=invoice["id"]))
    for text in ("INV-0001", "Acme Facilities", "Dana Reyes", "Monthly retainer",
                 "$5,000.00", "1.5", "$1,200.00", "$1,800.00", "$6,800.00", "$50.00",
                 "$6,850.00", "How to pay", "Example Bank", "Thank you for your business.",
                 "Net 15.", "Tenant A"):
        assert text in html, text
    assert "Pay this invoice online" not in html, "the pay link stays empty until P4"
    assert "Paid" not in html and "Balance" not in html, "status is not printed on it"
    from weasyprint import HTML
    assert len(HTML(string=html).render().pages) == 1


@pytest.mark.django_db
def test_a_draft_previews_without_taking_a_number(acme, ff, api):
    made = draft(api, ff, *acme).json()
    preview = get(api, ff, f"{ROOT}{made['id']}/preview/")
    assert preview.status_code == 200 and preview.content[:4] == b"%PDF"
    assert get(api, ff, f"{ROOT}{made['id']}/").json()["number"] == ""
    with tenant_context(acme[0].tenant_id):
        assert InvoiceSettings.objects.get().next_value == 1
    assert get(api, ff, f"{ROOT}{made['id']}/pdf/").status_code == 404


# ==================================================================== to a contact

@pytest.mark.django_db
def test_an_invoice_to_a_contact_is_emailed_and_is_in_no_portal(ready_to_bill, ff, api,
                                                                dev_outbox):
    person = ContactFactory(tenant=ready_to_bill, first_name="Lee", last_name="Okafor")
    ContactEmailFactory(tenant=ready_to_bill, contact=person, address="lee@elsewhere.invalid")
    made = post(api, ff, ROOT, {"kind": "contact", "contact": str(person.pk),
                                "lines": LINES})
    assert made.status_code == 201 and made.json()["client_company"] is None
    post(api, ff, f"{ROOT}{made.json()['id']}/make-ready/")
    done = post(api, ff, f"{ROOT}{made.json()['id']}/send/").json()
    assert done["status"] == "sent" and done["bill_to"]["company"] == ""
    assert dev_outbox[0].to == ["lee@elsewhere.invalid"]
    with tenant_context(ready_to_bill.pk):
        thread = EmailThread.objects.get(is_financial=True)
        assert thread.client_company_id is None


# ================================================================== recurring

@pytest.mark.django_db
def test_a_schedule_writes_one_draft_on_its_day_and_sends_nothing(acme, ff, api, dev_outbox):
    company, contact = acme
    made = post(api, ff, "/api/invoice-schedules/", {
        "client_company": str(company.pk), "contact": str(contact.pk), "day_of_month": 5,
        "starts_on": "2026-10-08", "lines": LINES, "notes": "Retainer for the month."})
    assert made.status_code == 201
    schedule = made.json()
    assert schedule["next_on"] == "2026-11-05" and schedule["total_cents"] == TOTAL
    with tenant_context(company.tenant_id):
        assert services.run_schedules(company.tenant, today=date(2026, 11, 4)) == []
        first = services.run_schedules(company.tenant, today=date(2026, 11, 5))
        assert len(first) == 1
        assert services.run_schedules(company.tenant, today=date(2026, 11, 5)) == [], \
            "not twice on the same day"
        invoice = first[0]
        assert (invoice.status, invoice.number, invoice.kind) == ("draft", None, "recurring")
        assert invoice.issue_date == date(2026, 11, 5) and invoice.total_cents == TOTAL
        assert invoice.notes == "Retainer for the month."
        assert invoice.due_date == date(2026, 11, 20)
        assert not OutboxMessage.objects.filter(producer="client_invoice").exists()
        assert InvoiceSettings.objects.get().next_value == 1, "it numbers nothing"
        assert ClientInvoiceSchedule.objects.get().next_on == date(2026, 12, 5)
        # The worker was down for three months: made up once, not three times.
        late = services.run_schedules(company.tenant, today=date(2027, 3, 9))
        assert len(late) == 1
        assert ClientInvoiceSchedule.objects.get().next_on == date(2027, 4, 5)
    assert len(dev_outbox) == 0
    listed = get(api, ff, ROOT).json()
    assert listed["drafts_from_schedules"] == 2
    assert all(row["from_schedule"] for row in listed["invoices"])


@pytest.mark.django_db
def test_a_schedule_stops_at_its_last_date_and_for_a_company_no_longer_a_client(acme, ff,
                                                                              api):
    company, contact = acme
    body = {"client_company": str(company.pk), "contact": str(contact.pk), "day_of_month": 1,
            "starts_on": "2026-10-08", "lines": LINES}
    ending = post(api, ff, "/api/invoice-schedules/", {**body, "ends_on": "2026-11-15"}).json()
    other_company, other_contact = a_client(company.tenant, "Bravo Works", "Sam")
    post(api, ff, "/api/invoice-schedules/", {
        **body, "client_company": str(other_company.pk), "contact": str(other_contact.pk)})
    with tenant_context(company.tenant_id):
        other_company.deleted_at = timezone.now()
        other_company.save()
        made = services.run_schedules(company.tenant, today=date(2026, 11, 1))
        assert [invoice.client_company_id for invoice in made] == [company.pk]
        assert services.run_schedules(company.tenant, today=date(2026, 12, 1)) == []
        assert not ClientInvoiceSchedule.objects.filter(is_active=True).exists()
    for bad in ({"day_of_month": 31}, {"day_of_month": 0}, {"lines": []},
                {"lines": [{"description": "", "quantity": "1", "unit_price_cents": 1}]}):
        assert post(api, ff, "/api/invoice-schedules/", {**body, **bad}).status_code == 400
    paused = patch(api, ff, f"/api/invoice-schedules/{ending['id']}/", {"is_active": False})
    assert paused.status_code == 200 and paused.json()["is_active"] is False


@pytest.mark.django_db
def test_the_scheduled_job_is_registered_and_runs_for_a_practice(acme, ff, api):
    from apps.billing import tasks
    from apps.tenancy.management.commands.ensure_schedules import SCHEDULES

    assert "apps.billing.tasks.run_invoice_schedules" in [row[1] for row in SCHEDULES]
    company, contact = acme
    post(api, ff, "/api/invoice-schedules/", {
        "client_company": str(company.pk), "contact": str(contact.pk),
        "day_of_month": timezone.localdate().day if timezone.localdate().day <= 28 else 1,
        "lines": LINES})
    made = tasks.run_invoice_schedules(str(company.tenant_id))
    assert made in (0, 1)


# ========================================================= payments and void

@pytest.mark.django_db
def test_part_paid_then_paid_and_a_removed_payment_reverses_it(acme, ff, api):
    invoice = sent(api, ff, *acme)
    one = f"{ROOT}{invoice['id']}/"
    pay = lambda cents, **more: post(api, ff, one + "payments/", {  # noqa: E731
        "amount_cents": cents, "paid_on": "2026-10-03", "method": "check", **more})
    part = pay(200000, reference="CHK 2231").json()
    assert (part["status"], part["paid_cents"], part["balance_cents"]) == (
        "partially_paid", 200000, TOTAL - 200000)
    over = pay(TOTAL)
    assert over.status_code == 400 and "$4,800.00" in over.json()["detail"]
    full = pay(TOTAL - 200000, method="ach").json()
    assert (full["status"], full["balance_cents"]) == ("paid", 0)
    assert pay(100).status_code == 409, "already paid in full"
    for bad in ({"amount_cents": 0}, {"amount_cents": 10.5}, {"method": "barter"},
                {"paid_on": "tomorrow"},
                {"paid_on": (timezone.localdate() + timedelta(days=2)).isoformat()}):
        assert post(api, ff, one + "payments/", {"amount_cents": 1, "paid_on": "2026-10-03",
                                                  **bad}).status_code in (400, 409), bad
    # Removed in error: it stops counting, it is kept, and it needs a reason.
    second = full["payments"][1]["id"]
    assert post(api, ff, one + "remove-payment/", {"payment": second}).status_code == 400
    back = post(api, ff, one + "remove-payment/",
                {"payment": second, "reason": "Entered against the wrong invoice"}).json()
    assert (back["status"], back["paid_cents"]) == ("partially_paid", 200000)
    assert [p["removed"] for p in back["payments"]] == [False, True]
    assert post(api, ff, one + "remove-payment/",
                {"payment": second, "reason": "Again"}).status_code == 409
    history = get(api, ff, one + "history/").json()
    assert [row["what"] for row in history][-3:] == [
        "payment_recorded", "payment_recorded", "payment_removed"]
    removed = [row for row in history if row["what"] == "payment_removed"][0]
    assert removed["reason"] == "Entered against the wrong invoice"
    assert (removed["before"], removed["after"]) == ("paid", "partially_paid")
    assert removed["by"] and removed["amount_cents"] == TOTAL - 200000


@pytest.mark.django_db
def test_a_void_needs_a_reason_and_never_hides_money_received(acme, ff, api):
    invoice = sent(api, ff, *acme)
    one = f"{ROOT}{invoice['id']}/"
    assert post(api, ff, one + "void/", {"reason": " "}).status_code == 400
    post(api, ff, one + "payments/", {"amount_cents": 100000, "paid_on": "2026-10-03"})
    refused = post(api, ff, one + "void/", {"reason": "Billed twice"})
    assert refused.status_code == 409 and "$1,000.00" in refused.json()["detail"]
    payment = get(api, ff, one).json()["payments"][0]["id"]
    post(api, ff, one + "remove-payment/", {"payment": payment, "reason": "Not ours"})
    done = post(api, ff, one + "void/", {"reason": "Billed twice"}).json()
    assert (done["status"], done["void_reason"], done["number"]) == (
        "void", "Billed twice", "INV-0001")
    assert post(api, ff, one + "void/", {"reason": "Again"}).status_code == 409
    assert post(api, ff, one + "payments/", {"amount_cents": 100,
                                             "paid_on": "2026-10-03"}).status_code == 409
    assert post(api, ff, one + "send/").status_code == 409
    # Its PDF is kept, and its number is not given to anyone else.
    assert get(api, ff, one + "pdf/").status_code == 200
    following = draft(api, ff, *acme).json()
    assert post(api, ff, f"{ROOT}{following['id']}/make-ready/").json()["number"] == "INV-0002"
    with tenant_context(acme[0].tenant_id):
        event = AuditEvent.objects.get(verb="billing.invoice_voided")
        assert event.payload["reason"] == "Billed twice" and event.actor_id == ff.user.pk
        assert (event.payload["before"], event.payload["after"]) == ("sent", "void")


@pytest.mark.django_db
def test_voiding_a_ready_invoice_withdraws_its_waiting_email(acme, ff, api, dev_outbox):
    made = draft(api, ff, *acme).json()
    post(api, ff, f"{ROOT}{made['id']}/make-ready/")
    assert post(api, ff, f"{ROOT}{made['id']}/void/", {"reason": "Not needed"}
                ).json()["status"] == "void"
    with tenant_context(acme[0].tenant_id):
        message = OutboxMessage.objects.get(producer="client_invoice")
        assert message.state == "rejected"
    assert post(api, ff, f"/api/outbox/{message.pk}/approve/").status_code == 403
    assert len(dev_outbox) == 0
    # A draft with no number is deleted, not voided.
    plain = draft(api, ff, *acme).json()
    assert post(api, ff, f"{ROOT}{plain['id']}/void/", {"reason": "x"}).status_code == 409


# ========================================================= overdue and totals

@pytest.mark.django_db
def test_overdue_is_the_day_after_the_due_date_and_never_for_paid_or_void(acme, ff, api):
    today = timezone.localdate()
    due_today = sent(api, ff, *acme, issue_date=(today - timedelta(days=15)).isoformat(),
                     due_date=today.isoformat())
    late = sent(api, ff, *acme, issue_date=(today - timedelta(days=30)).isoformat(),
                due_date=(today - timedelta(days=1)).isoformat())
    late_paid = sent(api, ff, *acme, issue_date=(today - timedelta(days=30)).isoformat(),
                     due_date=(today - timedelta(days=1)).isoformat())
    post(api, ff, f"{ROOT}{late_paid['id']}/payments/",
         {"amount_cents": TOTAL, "paid_on": today.isoformat()})
    late_void = sent(api, ff, *acme, issue_date=(today - timedelta(days=30)).isoformat(),
                     due_date=(today - timedelta(days=1)).isoformat())
    post(api, ff, f"{ROOT}{late_void['id']}/void/", {"reason": "Duplicate"})
    late_part = sent(api, ff, *acme, issue_date=(today - timedelta(days=30)).isoformat(),
                     due_date=(today - timedelta(days=1)).isoformat())
    post(api, ff, f"{ROOT}{late_part['id']}/payments/",
         {"amount_cents": 80000, "paid_on": today.isoformat()})
    still_draft = draft(api, ff, *acme, issue_date=(today - timedelta(days=30)).isoformat(),
                        due_date=(today - timedelta(days=1)).isoformat()).json()
    listed = get(api, ff, ROOT).json()
    overdue = {row["id"] for row in listed["invoices"] if row["overdue"]}
    assert overdue == {late["id"], late_part["id"]}
    assert due_today["id"] not in overdue and still_draft["id"] not in overdue
    assert {row["id"] for row in get(api, ff, ROOT + "?status=overdue").json()["invoices"]
            } == overdue
    # Totals: a draft and a void one are not money owed.
    assert listed["totals"] == {
        "invoiced_cents": 4 * TOTAL, "paid_cents": TOTAL + 80000,
        "outstanding_cents": 3 * TOTAL - 80000,
        "overdue_cents": TOTAL + (TOTAL - 80000)}
    # The filters narrow the totals with the list.
    assert get(api, ff, ROOT + "?status=paid").json()["totals"]["invoiced_cents"] == TOTAL
    assert get(api, ff, ROOT + "?status=draft").json()["totals"]["invoiced_cents"] == 0
    assert get(api, ff, f"{ROOT}?from={today.isoformat()}").json()["invoices"] == []
    export = get(api, ff, ROOT + "export/")
    assert export["Content-Type"].startswith("text/csv")
    text = export.content.decode()
    assert "INV-0001" in text and "Acme Facilities" in text
    assert f"Outstanding,{(3 * TOTAL - 80000) / 100:.2f}" in text


@pytest.mark.django_db
def test_merging_two_contacts_keeps_their_invoices_and_what_was_printed(acme, ff, api):
    from apps.crm.services import merge

    company, contact = acme
    invoice = sent(api, ff, company, contact)
    with tenant_context(company.tenant_id):
        keeper = ContactFactory(tenant=company.tenant, first_name="Dana", last_name="Reyes",
                                company=company)
        merge.merge_contacts(keeper, contact)
        row = ClientInvoice.objects.get(pk=invoice["id"])
        assert row.contact_id == keeper.pk
        assert row.bill_to["email"] == "dana@acme.invalid"
