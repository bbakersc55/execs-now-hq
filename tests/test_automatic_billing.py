"""Recurring invoices that bill automatically (2026-11-17, `docs/p4_billing.md` §14).

The date rules first (no database), then the whole path on the stub gateway:
set up, no billing before the client agrees, the agreement, the invoice made
and emailed by itself, the charge on the billing date, no usable card, a
decline and its one retry, a price change, notice and its withdrawal, the
practice owner's end date (earlier only, or at once), Ended and a new
agreement, a test card once live, and "Run the next billing now".
"""

from __future__ import annotations

from datetime import date

import pytest

from apps.billing import autopay, recurring, timing
from apps.billing.models import (
    AutopayConsent, BillingAgreement, ClientInvoice, ClientInvoiceSchedule, ClientPaymentMethod,
    PaymentAttempt,
)
from apps.crm.models import OutboxMessage
from apps.notify.models import Notice
from apps.tenancy.context import tenant_context
from apps.tenancy.demo.clock import at, moment
from apps.tenancy.models import AuditEvent

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import ClientCompanyFactory, ContactEmailFactory, ContactFactory
from .test_autopay import connected, contact, save_card  # noqa: F401  (fixtures, helper)
from .test_card_payments import _after_commit_now  # noqa: F401  (autouse)
from .test_card_payments import sales
from .test_client_invoicing import patch as _patch
from .test_client_invoicing import post as _post
from .test_client_invoicing import ready_to_bill  # noqa: F401

ROOT = "/api/invoice-schedules/"
PORTAL = "/api/portal-billing/"
LINES = [{"description": "Operations support", "quantity": "1", "unit_price_cents": 150000}]
A = PaymentAttempt.Status


def _fresh(api, who):
    """Signed in again at the clock's moment: a session made weeks earlier on
    the moved clock has expired by the billing dates these tests visit."""
    api._clients.pop(str(who.pk), None)
    return api


def post(api, who, url, body=None):
    return _post(_fresh(api, who), who, url, body)


def patch(api, who, url, body):
    return _patch(_fresh(api, who), who, url, body)


def get(api, who, url):
    return _fresh(api, who).as_(who).get(url)


class Schedule:
    """Only what `timing` reads."""

    def __init__(self, days, first, every=1, cadence="monthly", term=None):
        self.days_of_month, self.first_billing_on = days, first
        self.every, self.cadence, self.term_ends_on = every, cadence, term


# ----------------------------------------------------------- the date rules

@pytest.mark.parametrize("notice, ends", [
    (date(2026, 11, 16), date(2026, 12, 31)),     # the owner's own example
    (date(2026, 11, 1), date(2026, 12, 31)),
    (date(2026, 11, 30), date(2026, 12, 31)),
    (date(2026, 12, 5), date(2027, 1, 31)),       # December: into the next year
    (date(2026, 12, 31), date(2027, 1, 31)),
    (date(2027, 1, 20), date(2027, 2, 28)),       # January: February's last day
    (date(2028, 1, 20), date(2028, 2, 29)),       # in a leap year
    (date(2027, 2, 10), date(2027, 3, 31)),       # February: March's
])
def test_billing_ends_on_the_last_day_of_the_month_after_notice(notice, ends):
    assert timing.notice_end(notice) == ends


def test_a_contract_end_later_than_the_rule_wins_and_an_earlier_one_does_not():
    notice = date(2026, 11, 16)
    assert timing.notice_end(notice, date(2027, 6, 30)) == date(2027, 6, 30)
    assert timing.notice_end(notice, date(2026, 12, 15)) == date(2026, 12, 31)
    assert timing.notice_end(notice, date(2026, 12, 31)) == date(2026, 12, 31)


def test_the_billing_dates_of_the_1st_and_15th_from_the_first_date():
    s = Schedule([15, 1], date(2026, 12, 15))
    assert timing.dates(s, date(2026, 11, 1), date(2027, 2, 1)) == [
        date(2026, 12, 15), date(2027, 1, 1), date(2027, 1, 15), date(2027, 2, 1)]
    assert timing.next_date(s, date(2027, 1, 2)) == date(2027, 1, 15)
    assert timing.last_date(s, date(2026, 12, 1), date(2026, 12, 31)) == date(2026, 12, 15)
    assert timing.describe(Schedule([1, 15], date(2026, 12, 1))) == \
        "on the 1st and 15th of each month"
    assert timing.describe(Schedule([2, 3, 21, 22], date(2026, 12, 2))) == \
        "on the 2nd, 3rd, 21st and 22nd of each month"


@pytest.mark.parametrize("days", [[], [0], [29], [31], ["x"], [1.5], [True]])
def test_a_day_of_the_month_is_1_to_28(days):
    with pytest.raises(timing.TimingError):
        timing.clean_days(days)


def test_days_are_sorted_and_once_each():
    assert timing.clean_days([15, "1", 15]) == [1, 15]


# ----------------------------------------------------------------- set up

@pytest.fixture
def owner_of(connected, fcc):  # noqa: F811
    """The client owner, with a contact the invoices are addressed to."""
    person = ContactFactory(tenant=connected, first_name="Wile", last_name="Coyote",
                            company=fcc.client_company)
    ContactEmailFactory(tenant=connected, contact=person, is_primary=True,
                        address="wile@acme.invalid")
    return person


def set_up(api, ff, fcc, person, *, first="2026-12-01", days=(1, 15), term=None, lead=3,
           lines=LINES):
    body = {"mode": "auto", "client_company": str(fcc.client_company_id),
            "contact": str(person.pk), "days_of_month": list(days), "first_billing_on": first,
            "lead_days": lead, "lines": lines}
    if term:
        body["term_ends_on"] = term
    return post(api, ff, ROOT, body)


@pytest.fixture
def waiting(owner_of, api, ff, fcc):
    with at(date(2026, 11, 16)):
        made = set_up(api, ff, fcc, owner_of)
    assert made.status_code == 201, made.content
    return ClientInvoiceSchedule.all_objects.get(pk=made.json()["id"])


def agree(api, fcc, schedule):
    shown = get(api, fcc, PORTAL).json()
    [row] = [r for r in shown if r["id"] == str(schedule.pk)]
    return post(api, fcc, f"{PORTAL}{schedule.pk}/agree/",
                {"agree": True, "version": row["version"], "key": row["key"]})


@pytest.fixture
def active(waiting, api, fcc):
    with at(date(2026, 11, 16)):
        assert save_card(api, fcc).status_code == 200
        done = agree(api, fcc, waiting)
    assert done.status_code == 200, done.content
    waiting.refresh_from_db()
    return waiting


def make(tenant, day):
    with at(day), tenant_context(tenant.pk):
        return recurring.make_due(tenant, today=day)


def charge(tenant, day):
    with at(day), tenant_context(tenant.pk):
        return recurring.charge_due(tenant, today=day)


def emails_to(address, **more):
    return OutboxMessage.all_objects.filter(to_address=address, **more).order_by("created_at")


@pytest.mark.django_db
def test_the_practice_owner_sets_up_automatic_billing_and_it_waits(waiting, api, ff, cf, fcc):
    shown = get(api, ff, ROOT).json()
    [row] = [r for r in shown if r["id"] == str(waiting.pk)]
    assert row["mode"] == "auto" and row["days_of_month"] == [1, 15]
    assert row["automatic"]["state"] == "waiting"
    assert row["automatic"]["state_label"] == f"Waiting for {fcc.client_company.name} to agree"
    assert row["automatic"]["next_billing_on"] == "2026-12-01"
    # Only the practice owner: it charges a card.
    refused = set_up(api, cf, fcc, waiting.contact)
    assert refused.status_code in (403, 404)


@pytest.mark.django_db
def test_a_first_date_off_its_days_or_in_the_past_is_refused(owner_of, api, ff, fcc):
    with at(date(2026, 11, 16)):
        assert set_up(api, ff, fcc, owner_of, first="2026-12-02").status_code == 400
        assert set_up(api, ff, fcc, owner_of, first="2026-11-01").status_code == 400
        assert set_up(api, ff, fcc, owner_of, days=(1, 29)).status_code == 400
        assert set_up(api, ff, fcc, owner_of, lead=15).status_code == 400
        assert set_up(api, ff, fcc, owner_of, term="2026-11-30").status_code == 400


@pytest.mark.django_db
def test_nothing_is_billed_before_the_client_agrees(waiting, connected, stub_gateway):
    for day in (date(2026, 11, 28), date(2026, 12, 1), date(2026, 12, 15)):
        assert make(connected, day) == [] and charge(connected, day) == 0
    assert not ClientInvoice.all_objects.filter(schedule=waiting).exists()
    assert sales(stub_gateway) == []


@pytest.mark.django_db
def test_the_owner_emails_the_client_owner_the_link(waiting, api, ff, fcc):
    sent = post(api, ff, f"{ROOT}{waiting.pk}/send-link/")
    assert sent.status_code == 200, sent.content
    [mail] = emails_to(fcc.user.email)
    assert "/invoices" in mail.body_text and "Nothing is billed until you agree" in mail.body_text


# -------------------------------------------------------------- agreement

@pytest.mark.django_db
def test_the_client_reads_short_terms_and_must_save_a_card_to_agree(waiting, api, fcc):
    [row] = get(api, fcc, PORTAL).json()
    words = row["words"]
    assert "What is billed: Operations support ($1,500.00)." in words
    assert "Total each time: $1,500.00." in words
    # 2026-11-17.2: the schedule on its own line, and the standing sentence.
    assert "\nBilled on the 1st and 15th of each month.\n" in words
    assert "\nFirst billing date: December 1, 2026.\n" in words
    assert "Month to month." in words and "Stop automatic billing" in words
    assert ("\nIf you stop, billing continues through the end of the following month. Every "
            "billing date through then is billed, and nothing after.") in words
    no_card = agree(api, fcc, waiting)
    assert no_card.status_code == 409 and "Save a card first" in no_card.json()["detail"]


@pytest.mark.django_db
def test_a_contract_end_is_said_as_term_ends_then_month_to_month(owner_of, api, ff, fcc):
    with at(date(2026, 11, 16)):
        made = set_up(api, ff, fcc, owner_of, term="2027-06-30").json()
        [row] = get(api, fcc, PORTAL).json()
    assert row["id"] == made["id"]
    assert "Term ends June 30, 2027, then month to month." in row["words"]
    assert row["stop_rule"] == (
        "If you stop, billing continues through the end of the following month. If the term "
        "ends later than that, on June 30, 2027, billing continues through the term's end.")
    assert row["stop_rule"] in row["words"]


@pytest.mark.django_db
def test_the_agreement_is_kept_as_given(active, fcc):
    agreement = BillingAgreement.all_objects.get(schedule=active)
    assert agreement.agreed_by_id == fcc.user_id and agreement.wording_version == "2026-11-17.2"
    assert "Total each time: $1,500.00." in agreement.wording
    assert agreement.card.last4 == "1111" and agreement.ip_address
    assert recurring.state_of(active, date(2026, 11, 16)) == "active"


@pytest.mark.django_db
def test_changed_terms_must_be_read_again(waiting, api, fcc):
    with at(date(2026, 11, 16)):
        save_card(api, fcc)
        [row] = get(api, fcc, PORTAL).json()
        stale = post(api, fcc, f"{PORTAL}{waiting.pk}/agree/",
                     {"agree": True, "version": row["version"], "key": "0" * 16})
    assert stale.status_code == 409 and "read them again" in stale.json()["detail"]
    assert not BillingAgreement.all_objects.exists()


@pytest.mark.django_db
def test_only_the_client_owner_of_that_company_reaches_it(waiting, api, connected):
    team = _member(connected, "ECC", company=waiting.client_company)
    assert get(api, team, PORTAL).status_code == 403
    other = _member(connected, "FCC", company=ClientCompanyFactory(tenant=connected))
    assert get(api, other, PORTAL).json() == []
    assert post(api, other, f"{PORTAL}{waiting.pk}/agree/", {"agree": True}).status_code == 404


@pytest.mark.django_db
def test_the_only_card_cant_be_removed_while_billing_but_can_be_replaced(active, api, fcc):
    removed = post(api, fcc, "/api/portal-autopay/remove-card/")
    assert removed.status_code == 409 and "can't be removed" in removed.json()["detail"]
    assert save_card(api, fcc, "tok-new").status_code == 200
    assert ClientPaymentMethod.all_objects.filter(removed_at__isnull=True).count() == 1


# ------------------------------------------------- sent by itself, charged

@pytest.mark.django_db
def test_the_invoice_is_made_and_emailed_lead_days_before_with_no_approval(active, connected,
                                                                            fcc, owner_of):
    assert make(connected, date(2026, 11, 27)) == []
    [invoice] = make(connected, date(2026, 11, 28))
    assert make(connected, date(2026, 11, 28)) == []          # once
    assert (invoice.status, invoice.billing_date, invoice.due_date, invoice.issue_date) == (
        "sent", date(2026, 12, 1), date(2026, 12, 1), date(2026, 11, 28))
    assert invoice.number and invoice.total_cents == 150000
    mail = OutboxMessage.all_objects.get(source_type="client_invoice", source_id=invoice.pk)
    assert mail.state == "sent" and mail.to_address == "wile@acme.invalid"
    assert ("$1,500.00 will be charged to the card ending 1111 on December 1, 2026."
            in mail.body_text)


@pytest.mark.django_db
def test_the_card_is_charged_on_the_billing_date_and_the_receipt_sent(active, connected,
                                                                       stub_gateway):
    [invoice] = make(connected, date(2026, 11, 28))
    assert charge(connected, date(2026, 11, 30)) == 0 and sales(stub_gateway) == []
    assert charge(connected, date(2026, 12, 1)) == 1
    invoice.refresh_from_db()
    assert invoice.status == "paid"
    [attempt] = PaymentAttempt.all_objects.filter(invoice=invoice)
    assert attempt.via == "autopay" and attempt.status == A.APPROVED
    assert emails_to("wile@acme.invalid", producer="payment_receipt").count() == 1
    assert charge(connected, date(2026, 12, 1)) == 0          # never twice


@pytest.mark.django_db
def test_with_lead_days_zero_it_is_made_on_the_day(owner_of, api, ff, fcc, connected):
    with at(date(2026, 11, 16)):
        schedule = ClientInvoiceSchedule.all_objects.get(
            pk=set_up(api, ff, fcc, owner_of, lead=0).json()["id"])
        save_card(api, fcc)
        agree(api, fcc, schedule)
    assert make(connected, date(2026, 11, 30)) == []
    [invoice] = make(connected, date(2026, 12, 1))
    assert invoice.issue_date == invoice.due_date == date(2026, 12, 1)


@pytest.mark.django_db
def test_with_no_usable_card_it_still_goes_with_its_pay_link_and_the_owner_is_told(
        active, connected, ff, stub_gateway):
    ClientPaymentMethod.all_objects.update(removed_at=date(2026, 11, 20))
    [invoice] = make(connected, date(2026, 11, 28))
    mail = OutboxMessage.all_objects.get(source_type="client_invoice", source_id=invoice.pk)
    assert mail.state == "sent" and "will be charged" not in mail.body_text
    assert "/pay/" in mail.body_text
    assert Notice.all_objects.filter(recipient=ff.user,
                                     title__startswith="Sent without a card").count() == 1
    assert charge(connected, date(2026, 12, 1)) == 0 and sales(stub_gateway) == []
    event = AuditEvent.all_objects.get(verb="billing.autopay_passed_over", target_id=invoice.pk)
    assert "no card on file" in event.payload["reason"]
    # Nothing to the client about it.
    assert not emails_to("wile@acme.invalid", producer="autopay_notice").exists()


@pytest.mark.django_db
def test_a_decline_is_tried_once_more_on_a_later_day_and_both_sides_told(owner_of, api, ff,
                                                                          fcc, connected,
                                                                          stub_gateway):
    cheap = [{"description": "Tiny", "quantity": "1", "unit_price_cents": 50}]
    with at(date(2026, 11, 16)):
        schedule = ClientInvoiceSchedule.all_objects.get(
            pk=set_up(api, ff, fcc, owner_of, lines=cheap).json()["id"])
        save_card(api, fcc)
        agree(api, fcc, schedule)
    [invoice] = make(connected, date(2026, 11, 28))
    assert charge(connected, date(2026, 12, 1)) == 1
    assert charge(connected, date(2026, 12, 1)) == 0          # not twice in a day
    told = emails_to(fcc.user.email, producer="autopay_notice")
    assert told.count() == 1 and "tried once more" in told[0].body_text
    assert emails_to(ff.user.email, subject__startswith="Auto-pay failed").count() == 1
    assert charge(connected, date(2026, 12, 2)) == 1          # the one retry
    assert charge(connected, date(2026, 12, 3)) == 0          # never a third
    assert PaymentAttempt.all_objects.filter(invoice=invoice, status=A.DECLINED).count() == 2


# --------------------------------------------------------------- changes

@pytest.mark.django_db
def test_a_price_change_applies_from_the_next_billing_date_7_days_out(active, api, ff, fcc,
                                                                       connected):
    new = [{"description": "Operations support", "quantity": "1", "unit_price_cents": 175000}]
    with at(date(2026, 11, 27)):
        changed = patch(api, ff, f"{ROOT}{active.pk}/", {"lines": new})
    assert changed.status_code == 200, changed.content
    # Dec 1 is 4 days out: unchanged. Dec 15 is the first at least 7 days out.
    assert changed.json()["automatic"]["pending"] == {"from": "2026-12-15",
                                                      "total_cents": 175000}
    [mail] = emails_to(fcc.user.email, subject__startswith="Automatic billing changes")
    assert "From December 15, 2026" in mail.body_text and "$1,750.00" in mail.body_text
    [first] = make(connected, date(2026, 11, 28))
    [second] = make(connected, date(2026, 12, 12))
    assert (first.total_cents, second.total_cents) == (150000, 175000)
    active.refresh_from_db()
    assert active.lines[0]["unit_price_cents"] == 175000 and active.pending_lines is None


@pytest.mark.django_db
def test_the_agreed_days_cant_change_while_it_is_in_force(active, api, ff):
    refused = patch(api, ff, f"{ROOT}{active.pk}/", {"days_of_month": [1]})
    assert refused.status_code == 400 and "agreed to these billing days" in \
        refused.json()["detail"]


# --------------------------------------------------------------- stopping

@pytest.mark.django_db
def test_notice_on_november_16_bills_through_december_and_nothing_after(active, api, fcc, ff,
                                                                        connected,
                                                                        stub_gateway):
    with at(date(2026, 11, 16)):
        preview = get(api, fcc, f"{PORTAL}{active.pk}/stop-preview/").json()
        assert preview["text"].startswith(
            "Billing continues through December 31, 2026. Your last charge will be on "
            "December 15, 2026. For an exception, contact ")
        assert ff.user.email in preview["text"]
        stopped = post(api, fcc, f"{PORTAL}{active.pk}/stop/")
    assert stopped.status_code == 200, stopped.content
    [row] = stopped.json()
    assert (row["state"], row["ends_on"], row["last_charge_on"], row["can_withdraw"]) == (
        "ending", "2026-12-31", "2026-12-15", True)
    [mail] = emails_to(fcc.user.email, subject="Automatic billing ends December 31, 2026")
    assert "Your last charge will be on December 15, 2026" in mail.body_text
    assert Notice.all_objects.filter(recipient=ff.user, title__contains="gave notice").exists()
    assert emails_to(ff.user.email, subject__contains="gave notice").count() == 1
    billed = []
    for day in (date(2026, 11, 28), date(2026, 12, 1), date(2026, 12, 12), date(2026, 12, 15),
                date(2026, 12, 29), date(2027, 1, 1), date(2027, 1, 15)):
        billed += make(connected, day)
        charge(connected, day)
    assert [i.billing_date for i in billed] == [date(2026, 12, 1), date(2026, 12, 15)]
    assert len(sales(stub_gateway)) == 2
    assert recurring.state_of(active, date(2027, 1, 1)) == "ended"
    assert BillingAgreement.all_objects.get().ended_at is not None


@pytest.mark.django_db
def test_notice_in_december_bills_through_january(active, api, fcc, connected):
    with at(date(2026, 12, 20)):
        post(api, fcc, f"{PORTAL}{active.pk}/stop/")
    agreement = BillingAgreement.all_objects.get()
    assert agreement.ends_on == date(2027, 1, 31)
    assert recurring.last_charge_on(active, agreement, agreement.ends_on) == date(2027, 1, 15)


@pytest.mark.django_db
def test_notice_in_february_and_a_later_contract_end(owner_of, api, ff, fcc):
    with at(date(2026, 11, 16)):
        schedule = ClientInvoiceSchedule.all_objects.get(
            pk=set_up(api, ff, fcc, owner_of, term="2027-06-30").json()["id"])
        save_card(api, fcc)
        agree(api, fcc, schedule)
    with at(date(2027, 2, 10)):
        preview = get(api, fcc, f"{PORTAL}{schedule.pk}/stop-preview/").json()
    assert preview["ends_on"] == "2027-06-30" and preview["last_charge_on"] == "2027-06-15"


@pytest.mark.django_db
def test_a_contract_end_earlier_than_the_rule_does_not_shorten_it(owner_of, api, ff, fcc):
    with at(date(2026, 11, 16)):
        schedule = ClientInvoiceSchedule.all_objects.get(
            pk=set_up(api, ff, fcc, owner_of, term="2026-12-15").json()["id"])
        save_card(api, fcc)
        agree(api, fcc, schedule)
    with at(date(2027, 2, 10)):
        preview = get(api, fcc, f"{PORTAL}{schedule.pk}/stop-preview/").json()
    assert preview["ends_on"] == "2027-03-31"


@pytest.mark.django_db
def test_the_client_can_withdraw_notice_before_the_end(active, api, fcc, ff, connected):
    with at(date(2026, 11, 16)):
        post(api, fcc, f"{PORTAL}{active.pk}/stop/")
    with at(date(2026, 12, 20)):
        back = post(api, fcc, f"{PORTAL}{active.pk}/withdraw/")
    assert back.status_code == 200, back.content
    assert back.json()[0]["state"] == "active" and back.json()[0]["ends_on"] is None
    assert Notice.all_objects.filter(recipient=ff.user, title__contains="withdrew").exists()
    assert [i.billing_date for i in make(connected, date(2026, 12, 29))] == [
        date(2026, 12, 1), date(2026, 12, 15), date(2027, 1, 1)]


@pytest.mark.django_db
def test_the_owner_moves_the_end_earlier_and_is_refused_later(active, api, ff, fcc, connected):
    with at(date(2026, 11, 16)):
        post(api, fcc, f"{PORTAL}{active.pk}/stop/")              # ends Dec 31
    [dec1] = make(connected, date(2026, 11, 28))
    with at(date(2026, 11, 28)):
        later = post(api, ff, f"{ROOT}{active.pk}/set-end/", {"ends_on": "2027-01-31"})
        same = post(api, ff, f"{ROOT}{active.pk}/set-end/", {"ends_on": "2026-12-31"})
        past = post(api, ff, f"{ROOT}{active.pk}/set-end/", {"ends_on": "2026-11-20"})
        earlier = post(api, ff, f"{ROOT}{active.pk}/set-end/", {"ends_on": "2026-12-10"})
    assert later.status_code == same.status_code == past.status_code == 400
    assert "never later" in later.json()["detail"]
    assert earlier.status_code == 200, earlier.content
    assert earlier.json()["automatic"]["ends_on"] == "2026-12-10"
    [mail] = emails_to(fcc.user.email, subject="Automatic billing now ends December 10, 2026")
    assert "Your last charge will be on December 1, 2026" in mail.body_text
    with at(date(2026, 12, 5)):
        withdraw = post(api, fcc, f"{PORTAL}{active.pk}/withdraw/")
    assert withdraw.status_code == 409          # the owner set it
    assert make(connected, date(2026, 12, 12)) == []
    dec1.refresh_from_db()
    assert dec1.status == "sent"


@pytest.mark.django_db
def test_an_invoice_already_made_after_a_new_end_is_voided(active, api, ff, connected):
    make(connected, date(2026, 11, 28))
    [dec15] = make(connected, date(2026, 12, 12))
    with at(date(2026, 12, 12)):
        done = post(api, ff, f"{ROOT}{active.pk}/set-end/", {"ends_on": "2026-12-13"})
    assert done.status_code == 200, done.content
    dec15.refresh_from_db()
    assert dec15.status == "void" and "is not billed" in dec15.void_reason


@pytest.mark.django_db
def test_the_owner_stops_at_once_and_nothing_more_is_charged(active, api, ff, fcc, connected,
                                                             stub_gateway):
    [dec1] = make(connected, date(2026, 11, 28))
    with at(date(2026, 11, 29)):
        stopped = post(api, ff, f"{ROOT}{active.pk}/set-end/", {"now": True})
    assert stopped.status_code == 200, stopped.content
    assert stopped.json()["automatic"]["state"] == "ended"
    dec1.refresh_from_db()
    assert dec1.status == "void"
    assert charge(connected, date(2026, 12, 1)) == 0 and sales(stub_gateway) == []
    assert make(connected, date(2026, 12, 12)) == []
    [mail] = emails_to(fcc.user.email, subject="Automatic billing stopped")
    assert "No card will be charged again" in mail.body_text


@pytest.mark.django_db
def test_after_ended_billing_again_needs_a_new_agreement(active, api, ff, fcc, connected):
    with at(date(2026, 11, 16)):
        post(api, fcc, f"{PORTAL}{active.pk}/stop/")
    make(connected, date(2027, 1, 1))                         # ends it
    with at(date(2027, 1, 5)):
        [row] = get(api, fcc, PORTAL).json()
        assert row["state"] == "ended"
        refused = agree(api, fcc, active)
        assert refused.status_code == 409 and "send the link again" in refused.json()["detail"]
        assert post(api, ff, f"{ROOT}{active.pk}/send-link/").status_code == 200
        again = agree(api, fcc, active)
    assert again.status_code == 200, again.content
    assert BillingAgreement.all_objects.filter(schedule=active).count() == 2
    assert recurring.state_of(active, date(2027, 1, 5)) == "active"
    [jan15] = make(connected, date(2027, 1, 12))
    assert jan15.billing_date == date(2027, 1, 15)


# ------------------------------------------------- test cards, Test Mode

@pytest.mark.django_db
def test_a_test_card_is_never_charged_once_the_processor_is_live(active, connected, ff,
                                                                 stub_gateway):
    ClientPaymentMethod.all_objects.update(is_test=True)
    [invoice] = make(connected, date(2026, 11, 28))
    stub_gateway.test_mode_on = False
    assert charge(connected, date(2026, 12, 1)) == 0
    assert sales(stub_gateway) == [] and not PaymentAttempt.all_objects.exists()
    event = AuditEvent.all_objects.get(verb="billing.autopay_passed_over", target_id=invoice.pk)
    assert "saved while the card processor was in Test Mode" in event.payload["reason"]
    assert not emails_to("wile@acme.invalid", producer="autopay_notice").exists()
    assert Notice.all_objects.filter(recipient=ff.user, source_type="autopay_passed_over").exists()


@pytest.mark.django_db
def test_a_test_card_on_auto_pay_is_refused_the_same_way(connected, fcc, api, ff, stub_gateway):
    from .test_autopay import due_today, run, send_invoice, turn_on

    person = ContactFactory(tenant=connected, company=fcc.client_company)
    ContactEmailFactory(tenant=connected, contact=person, is_primary=True,
                        address="pay@acme.invalid")
    save_card(api, fcc)
    turn_on(api, fcc)
    ClientPaymentMethod.all_objects.update(is_test=True)
    invoice = send_invoice(api, ff, fcc, person)
    today = due_today(invoice)
    assert run(connected, today)["charged"] == 0 and sales(stub_gateway) == []
    assert AuditEvent.all_objects.filter(verb="billing.autopay_passed_over",
                                         target_id=invoice.pk).count() == 1


@pytest.mark.django_db
def test_run_the_next_billing_now_only_in_test_mode(active, api, ff, connected, stub_gateway):
    with at(date(2026, 11, 20)):
        refused = post(api, ff, f"{ROOT}{active.pk}/run-now/")
    assert refused.status_code == 409 and "Test Mode" in refused.json()["detail"]
    stub_gateway.test_mode_on = True
    with at(date(2026, 11, 20)):
        ran = post(api, ff, f"{ROOT}{active.pk}/run-now/")
    assert ran.status_code == 200, ran.content
    invoice = ClientInvoice.all_objects.get(schedule=active, billing_date=date(2026, 12, 1))
    assert invoice.status == "paid" and invoice.test_paid_cents == invoice.total_cents
    # Pressed again at once: the same card for the same amount would be a
    # duplicate at NMI, and its decline would email the client.
    with at(date(2026, 11, 20)):
        again = post(api, ff, f"{ROOT}{active.pk}/run-now/")
    assert again.status_code == 409 and "duplicate" in again.json()["detail"]
    assert not ClientInvoice.all_objects.filter(schedule=active,
                                                billing_date=date(2026, 12, 15)).exists()
    with at(moment(date(2026, 11, 20), 9, 25)):
        assert post(api, ff, f"{ROOT}{active.pk}/run-now/").status_code == 200
    assert ClientInvoice.all_objects.filter(
        schedule=active, billing_date=date(2026, 12, 15), status="paid").exists()


CLEAR = "/api/payment-account/clear-test-payments/"
AFTER_END = ("Test payments cleared: no money moved. Automatic billing ended {}, before this "
             "billing date, so it is not billed.")


def _run_twice_in_test_mode(api, ff, schedule, stub_gateway):
    """Two billing dates run now in Test Mode: December 1 and 15, both paid
    by test payments."""
    stub_gateway.test_mode_on = True
    with at(date(2026, 11, 17)):
        assert post(api, ff, f"{ROOT}{schedule.pk}/run-now/").status_code == 200
    with at(moment(date(2026, 11, 17), 9, 25)):
        assert post(api, ff, f"{ROOT}{schedule.pk}/run-now/").status_code == 200
    return [ClientInvoice.all_objects.get(schedule=schedule, billing_date=date(2026, 12, day))
            for day in (1, 15)]


def _cleared(api, ff, stub_gateway, choice):
    stub_gateway.test_mode_on = False
    with at(moment(date(2026, 11, 17), 10, 0)):
        done = post(api, ff, CLEAR, {"invoices": choice})
    assert done.status_code == 200, done.content
    return {k: done.json()["cleared"][k] for k in ("payments", "reopened", "voided")}


@pytest.mark.django_db
@pytest.mark.parametrize("choice", ["reopen", "void"])
def test_clearing_voids_an_invoice_dated_after_the_end_whichever_choice(
        choice, active, api, ff, connected, stub_gateway):
    """An end moved earlier voids the invoices already made for later dates,
    but not one a test payment made look paid. Once that payment is cleared,
    the invoice is voided even with "reopen": nothing will ever charge it.
    One dated within the agreement follows the choice."""
    dec1, dec15 = _run_twice_in_test_mode(api, ff, active, stub_gateway)
    with at(moment(date(2026, 11, 17), 9, 30)):
        moved = post(api, ff, f"{ROOT}{active.pk}/set-end/", {"ends_on": "2026-12-10"})
    assert moved.status_code == 200, moved.content
    dec15.refresh_from_db()
    assert dec15.status == "paid"                   # kept: its test payment looked like money
    assert _cleared(api, ff, stub_gateway, choice) == {
        "payments": 2, "reopened": 1 if choice == "reopen" else 0,
        "voided": 1 if choice == "reopen" else 2}
    dec1.refresh_from_db()
    dec15.refresh_from_db()
    assert (dec15.status, dec15.paid_cents) == ("void", 0)
    assert dec15.void_reason == AFTER_END.format("December 10, 2026")
    assert dec1.status == ("sent" if choice == "reopen" else "void")
    if choice == "void":
        assert dec1.void_reason == "Test payments cleared: no money moved."
    event = AuditEvent.all_objects.get(verb="billing.test_payments_cleared", target_id=dec15.pk)
    assert event.payload == {"number": dec15.number, "choice": choice, "after_end": "2026-12-10"}


@pytest.mark.django_db
def test_inv_0005_stop_now_then_cleared_with_reopen_is_voided(active, api, ff, connected,
                                                             stub_gateway):
    """Production, 2026-11-17: run now in Test Mode, "Stop now", then "Clear
    test payments" sent "reopen" (the dialog's default then), which reopened
    an invoice for December 1, after the end, for the owner to void by hand."""
    dec1, dec15 = _run_twice_in_test_mode(api, ff, active, stub_gateway)
    with at(moment(date(2026, 11, 17), 9, 40)):
        assert post(api, ff, f"{ROOT}{active.pk}/set-end/", {"now": True}).status_code == 200
    assert _cleared(api, ff, stub_gateway, "reopen") == {"payments": 2, "reopened": 0,
                                                         "voided": 2}
    for invoice in (dec1, dec15):
        invoice.refresh_from_db()
        assert invoice.status == "void"
        assert invoice.void_reason == AFTER_END.format("November 17, 2026")
    assert charge(connected, date(2026, 12, 1)) == 0


@pytest.mark.django_db
def test_you_send_each_invoice_is_unchanged(owner_of, api, ff, fcc, connected):
    from apps.billing import services

    with at(date(2026, 11, 16)):
        made = post(api, ff, ROOT, {"client_company": str(fcc.client_company_id),
                                    "contact": str(owner_of.pk), "day_of_month": 1,
                                    "lines": LINES})
    assert made.status_code == 201 and made.json()["mode"] == "send"
    assert made.json()["automatic"] is None
    with at(date(2026, 12, 1)), tenant_context(connected.pk):
        [draft] = services.run_schedules(connected, today=date(2026, 12, 1))
        assert recurring.make_due(connected, today=date(2026, 12, 1)) == []
    assert draft.status == "draft" and draft.billing_date is None


# ------------------------------- the portal box, and auto-pay beside it (2026-11-17)

AUTOPAY = "/api/portal-autopay/"


@pytest.mark.django_db
def test_the_box_says_the_schedule_and_the_stop_rule_before_anyone_presses_stop(waiting, api,
                                                                                  fcc):
    with at(date(2026, 11, 16)):
        [row] = get(api, fcc, PORTAL).json()
    assert row["billed_words"] == "Billed on the 1st and 15th of each month"
    assert row["stop_rule"] == "If you stop, billing continues through the end of the following month."


@pytest.mark.django_db
def test_agreeing_never_turns_auto_pay_on(active, api, fcc):
    assert not AutopayConsent.all_objects.exists()
    with at(date(2026, 11, 16)):
        state = get(api, fcc, AUTOPAY).json()
    assert state["autopay"] is None
    assert state["automatic"] == {"billing": True, "through": None}
    assert state["card_hold"].startswith("Automatic billing is on, so the card on file can't "
                                         "be removed.")


@pytest.mark.django_db
def test_turning_auto_pay_off_leaves_automatic_billing_charging(active, api, fcc, connected,
                                                                stub_gateway):
    with at(date(2026, 11, 20)):
        on = post(api, fcc, AUTOPAY + "consent/",
                  {"agree": True, "version": autopay.WORDING_VERSION})
        assert on.status_code == 200, on.content
        off = post(api, fcc, AUTOPAY + "revoke/")
        assert off.status_code == 200 and off.json()["autopay"] is None
    agreement = BillingAgreement.all_objects.get(schedule=active)
    assert (agreement.ends_on, agreement.stopped_at, agreement.ended_at) == (None, None, None)
    [invoice] = make(connected, date(2026, 11, 28))
    assert invoice.autopay_consent_id is None             # never tied to the consent
    assert charge(connected, date(2026, 12, 1)) == 1
    invoice.refresh_from_db()
    assert invoice.status == "paid" and len(sales(stub_gateway)) == 1


@pytest.mark.django_db
def test_the_card_stays_through_the_end_date_and_can_go_the_day_after(active, api, fcc,
                                                                      connected):
    with at(date(2026, 11, 16)):
        assert post(api, fcc, f"{PORTAL}{active.pk}/stop/").status_code == 200
    held = ("Automatic billing continues through December 31, 2026, so the card stays on file "
            "until then. You can replace it with another card.")
    with at(date(2026, 12, 31)):
        assert get(api, fcc, AUTOPAY).json()["card_hold"] == held
        refused = post(api, fcc, AUTOPAY + "remove-card/")
        assert refused.status_code == 409 and refused.json()["detail"] == held
    # The day after, by the end date itself: the 5:00 job has not closed it yet.
    assert BillingAgreement.all_objects.get(schedule=active).ended_at is None
    with at(date(2027, 1, 1)):
        state = get(api, fcc, AUTOPAY).json()
        assert state["card_hold"] == "" and state["automatic"] is None
        assert post(api, fcc, AUTOPAY + "remove-card/").status_code == 200
    assert not ClientPaymentMethod.all_objects.filter(removed_at__isnull=True).exists()


@pytest.mark.django_db
def test_a_one_off_invoice_is_charged_only_under_a_consent_given_separately(
        active, api, ff, fcc, owner_of, connected, stub_gateway):
    from .test_autopay import send_invoice

    def one_off():
        invoice = send_invoice(_fresh(api, ff), ff, fcc, owner_of)
        ClientInvoice.all_objects.filter(pk=invoice.pk).update(due_date=date(2026, 11, 20))
        invoice.refresh_from_db()
        return invoice

    def run_autopay():
        with tenant_context(connected.pk):
            return autopay.run(connected, today=date(2026, 11, 20))

    with at(date(2026, 11, 20)):
        first = one_off()
        assert first.autopay_consent_id is None
        assert run_autopay()["charged"] == 0
        assert post(api, fcc, AUTOPAY + "consent/",
                    {"agree": True, "version": autopay.WORDING_VERSION}).status_code == 200
        second = one_off()
        assert second.autopay_consent_id is not None
        assert run_autopay()["charged"] == 1
    first.refresh_from_db(), second.refresh_from_db()
    assert (first.status, second.status) == ("sent", "paid")


@pytest.mark.django_db
def test_once_notice_is_given_the_owner_sees_the_end_and_the_last_charge(active, api, ff,
                                                                         fcc):
    with at(date(2026, 11, 16)):
        [before] = get(api, ff, ROOT).json()
        assert before["automatic"]["last_charge_on"] is None
        assert post(api, fcc, f"{PORTAL}{active.pk}/stop/").status_code == 200
        [row] = get(api, ff, ROOT).json()
    assert (row["automatic"]["ends_on"], row["automatic"]["last_charge_on"]) == (
        "2026-12-31", "2026-12-15")
