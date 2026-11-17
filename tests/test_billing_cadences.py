"""Every schedule for recurring invoices, both kinds (2026-11-17, `timing.py`).

Each preset's dates across month ends, year ends and a leap year; the stop
rule on each; the agreement's words; the invoice emailed never more than the
gap between dates ahead; "You send each invoice" on a cadence; and the owner's
case exactly: every Friday at $2,000, notice on Monday November 16, 2026.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from apps.billing import recurring, services, timing
from apps.billing.models import BillingAgreement, ClientInvoice, ClientInvoiceSchedule
from apps.tenancy.context import tenant_context
from apps.tenancy.demo.clock import at, moment

from . import registry_config  # noqa: F401
from .test_automatic_billing import (  # noqa: F401  (fixtures)
    agree, charge, connected, contact, get, make, owner_of, post, ready_to_bill, save_card,
)
from .test_card_payments import _after_commit_now  # noqa: F401  (autouse)
from .test_card_payments import sales

ROOT = "/api/invoice-schedules/"
PORTAL = "/api/portal-billing/"
MON, TUE, WED, FRI = 0, 1, 2, 4


class S:
    """Only what `timing` reads."""

    def __init__(self, cadence, first, *, every=1, weekday=None, days=(), term=None):
        self.cadence, self.first_billing_on, self.every = cadence, first, every
        self.weekday, self.days_of_month, self.term_ends_on = weekday, list(days), term


def d(text):
    return date.fromisoformat(text)


def between(s, start, end):
    return [x.isoformat() for x in timing.dates(s, d(start), d(end))]


# --------------------------------------------------------- the dates

def test_weekly_across_a_month_end_and_a_year_end():
    s = S("weekly", d("2026-11-20"), weekday=FRI)
    assert between(s, "2026-12-20", "2027-01-16") == [
        "2026-12-25", "2027-01-01", "2027-01-08", "2027-01-15"]
    assert timing.next_date(s, d("2026-11-21")) == d("2026-11-27")


def test_weekly_through_february_29_of_a_leap_year():
    s = S("weekly", d("2028-02-15"), weekday=TUE)
    assert between(s, "2028-02-20", "2028-03-08") == ["2028-02-22", "2028-02-29", "2028-03-07"]


def test_every_two_weeks_counts_from_its_first_date_across_the_year():
    s = S("weekly", d("2026-12-04"), every=2, weekday=FRI)
    assert between(s, "2026-11-01", "2027-01-31") == [
        "2026-12-04", "2026-12-18", "2027-01-01", "2027-01-15", "2027-01-29"]
    assert timing.next_date(s, d("2026-12-05")) == d("2026-12-18")


def test_twice_a_month_across_the_year_end():
    s = S("monthly", d("2026-12-01"), days=(1, 15))
    assert between(s, "2026-12-10", "2027-02-01") == [
        "2026-12-15", "2027-01-01", "2027-01-15", "2027-02-01"]


def test_monthly_on_the_28th_through_a_leap_february():
    s = S("monthly", d("2028-01-28"), days=(28,))
    assert between(s, "2028-01-01", "2028-03-31") == ["2028-01-28", "2028-02-28", "2028-03-28"]


def test_quarterly_from_its_first_month_across_the_year_end():
    s = S("monthly", d("2026-12-01"), every=3, days=(1,))
    assert between(s, "2026-11-01", "2027-12-31") == [
        "2026-12-01", "2027-03-01", "2027-06-01", "2027-09-01", "2027-12-01"]
    jan = S("monthly", d("2027-01-15"), every=3, days=(15,))
    assert between(jan, "2027-01-01", "2028-01-31") == [
        "2027-01-15", "2027-04-15", "2027-07-15", "2027-10-15", "2028-01-15"]


def test_yearly_on_any_date_but_february_29():
    s = S("yearly", d("2027-03-31"))
    assert between(s, "2026-01-01", "2029-12-31") == ["2027-03-31", "2028-03-31", "2029-03-31"]
    feb = S("yearly", d("2027-02-28"))
    assert between(feb, "2027-01-01", "2028-12-31") == ["2027-02-28", "2028-02-28"]
    with pytest.raises(timing.TimingError, match="February 29"):
        timing.check(S("yearly", d("2028-02-29")))


def test_custom_every_n_weeks_or_months():
    weeks = S("weekly", d("2026-11-18"), every=3, weekday=WED)
    assert between(weeks, "2026-11-01", "2027-01-15") == [
        "2026-11-18", "2026-12-09", "2026-12-30"]
    months = S("monthly", d("2026-11-28"), every=2, days=(28,))
    assert between(months, "2026-11-01", "2027-05-31") == [
        "2026-11-28", "2027-01-28", "2027-03-28", "2027-05-28"]


@pytest.mark.parametrize("schedule, message", [
    (S("weekly", d("2026-11-19"), weekday=FRI), "is a Friday"),
    (S("weekly", d("2026-11-20"), weekday=7), "weekday"),
    (S("weekly", d("2026-11-20"), weekday=FRI, every=53), "Every 1 to 52 weeks"),
    (S("monthly", d("2026-12-01"), every=3, days=(1, 15)), "one day of the month"),
    (S("monthly", d("2026-12-01"), every=13, days=(1,)), "Every 1 to 12 months"),
    (S("monthly", d("2026-12-02"), days=(1, 15)), "one of its days"),
    (S("monthly", d("2026-12-29"), days=(29,)), "1 to 28"),
    (S("hourly", d("2026-12-01")), "how often"),
])
def test_a_timing_that_cant_be_billed_is_refused_in_words(schedule, message):
    with pytest.raises(timing.TimingError, match=message):
        timing.check(schedule)


# ------------------------------------------------------ never more than the gap

@pytest.mark.parametrize("schedule, most", [
    (S("weekly", d("2026-11-20"), weekday=FRI), 7),
    (S("weekly", d("2026-11-20"), every=2, weekday=FRI), 14),
    (S("monthly", d("2026-12-01"), days=(1, 15)), 14),        # Feb 15 to Mar 1
    (S("monthly", d("2026-12-01"), days=(1, 28)), 1),         # Feb 28 to Mar 1
    (S("monthly", d("2026-12-01"), every=3, days=(1,)), 90),   # Dec 1 to Mar 1
])
def test_the_invoice_is_emailed_never_more_than_the_gap_ahead(schedule, most):
    assert timing.shortest_gap(schedule) == most
    timing.check_lead(schedule, min(most, 14))
    if most < 14:
        with pytest.raises(timing.TimingError, match=f"at most {most} day"):
            timing.check_lead(schedule, most + 1)


# --------------------------------------------------------- the words

@pytest.mark.parametrize("schedule, words", [
    (S("weekly", d("2026-11-20"), weekday=FRI), "every Friday"),
    (S("weekly", d("2026-12-04"), every=2, weekday=FRI), "every two weeks on Friday"),
    (S("weekly", d("2026-11-18"), every=3, weekday=WED), "every three weeks on Wednesday"),
    (S("monthly", d("2026-12-01"), days=(1, 15)), "on the 1st and 15th of each month"),
    (S("monthly", d("2027-01-01"), every=3, days=(1,)),
     "on the 1st of January, April, July and October"),
    (S("monthly", d("2026-12-01"), every=3, days=(1,)),
     "on the 1st of March, June, September and December"),
    (S("monthly", d("2026-11-10"), every=5, days=(10,)), "every five months on the 10th"),
    (S("yearly", d("2027-03-31")), "every year on March 31"),
])
def test_each_schedule_in_plain_words(schedule, words):
    assert timing.describe(schedule) == words


# --------------------------------------------------- the stop rule, on each

@pytest.mark.parametrize("schedule, last", [
    (S("weekly", d("2026-11-20"), weekday=FRI), "2026-12-25"),
    (S("weekly", d("2026-12-04"), every=2, weekday=FRI), "2026-12-18"),
    (S("monthly", d("2026-12-01"), days=(1, 15)), "2026-12-15"),
    (S("monthly", d("2026-12-10"), days=(10,)), "2026-12-10"),
    (S("monthly", d("2026-12-01"), every=3, days=(1,)), "2026-12-01"),
    (S("yearly", d("2027-03-31")), None),
])
def test_notice_on_november_16_bills_through_december_31_on_every_schedule(schedule, last):
    ends = timing.notice_end(d("2026-11-16"), schedule.term_ends_on)
    assert ends == d("2026-12-31")
    found = timing.last_date(schedule, d("2026-11-16"), ends)
    assert (found.isoformat() if found else None) == last


def test_a_later_contract_end_wins_on_a_quarterly_and_a_yearly_schedule():
    quarterly = S("monthly", d("2026-12-01"), every=3, days=(1,), term=d("2027-06-30"))
    ends = timing.notice_end(d("2026-11-16"), quarterly.term_ends_on)
    assert ends == d("2027-06-30")
    assert between(quarterly, "2026-11-16", ends.isoformat()) == [
        "2026-12-01", "2027-03-01", "2027-06-01"]
    yearly = S("yearly", d("2027-03-31"), term=d("2028-04-30"))
    ends = timing.notice_end(d("2027-05-02"), yearly.term_ends_on)
    assert timing.last_date(yearly, d("2027-05-02"), ends) == d("2028-03-31")


# ---------------------------------------------- through the app, both kinds

def set_up(api, ff, fcc, person, *, lines=2_000_00, lead=3, **timing_fields):
    body = {"mode": "auto", "client_company": str(fcc.client_company_id),
            "contact": str(person.pk), "lead_days": lead,
            "lines": [{"description": "Weekly operations support", "quantity": "1",
                       "unit_price_cents": lines}], **timing_fields}
    return post(api, ff, ROOT, body)


@pytest.mark.django_db
def test_every_friday_at_2000_with_notice_on_monday_november_16_2026(
        owner_of, api, ff, fcc, connected, stub_gateway):
    """The owner's case, exactly."""
    with at(date(2026, 11, 12)):
        made = set_up(api, ff, fcc, owner_of, cadence="weekly", every=1, weekday=FRI,
                      first_billing_on="2026-11-20")
        assert made.status_code == 201, made.content
        assert made.json()["timing_words"] == "every Friday"
        schedule = ClientInvoiceSchedule.all_objects.get(pk=made.json()["id"])
        save_card(api, fcc)
        [row] = get(api, fcc, PORTAL).json()
        assert "When: every Friday, starting November 20, 2026." in row["words"]
        assert "Total each time: $2,000.00." in row["words"]
        assert agree(api, fcc, schedule).status_code == 200
    with at(moment(date(2026, 11, 16), 10)):              # a Monday
        assert date(2026, 11, 16).weekday() == MON
        preview = get(api, fcc, f"{PORTAL}{schedule.pk}/stop-preview/").json()
        assert preview["text"].startswith(
            "Billing continues through December 31, 2026. Your last charge will be on "
            "December 25, 2026.")
        assert preview["last_charge_on"] == "2026-12-25"
        stopped = post(api, fcc, f"{PORTAL}{schedule.pk}/stop/")
    [row] = stopped.json()
    assert (row["ends_on"], row["last_charge_on"]) == ("2026-12-31", "2026-12-25")
    day = date(2026, 11, 13)
    while day <= date(2027, 1, 20):
        make(connected, day)
        charge(connected, day)
        day += timedelta(days=1)
    charged = sorted(i.billing_date.isoformat() for i in ClientInvoice.all_objects.filter(
        schedule=schedule, status="paid"))
    assert charged == ["2026-11-20", "2026-11-27", "2026-12-04", "2026-12-11", "2026-12-18",
                       "2026-12-25"]
    assert not ClientInvoice.all_objects.filter(schedule=schedule,
                                                billing_date__gt=date(2026, 12, 31)).exists()
    assert len(sales(stub_gateway)) == 6
    assert all(s[2]["amount_cents"] == 2_000_00 for s in sales(stub_gateway))
    assert recurring.state_of(schedule, date(2027, 1, 2)) == "ended"


@pytest.mark.django_db
def test_every_two_weeks_and_quarterly_say_their_schedule_in_the_agreement(
        owner_of, api, ff, fcc, connected):
    with at(date(2026, 11, 17)):
        two = set_up(api, ff, fcc, owner_of, cadence="weekly", every=2, weekday=FRI,
                     first_billing_on="2026-12-04")
        quarterly = set_up(api, ff, fcc, owner_of, cadence="monthly", every=3,
                           days_of_month=[1], first_billing_on="2027-01-01", lead=7)
        yearly = set_up(api, ff, fcc, owner_of, cadence="yearly", first_billing_on="2027-03-31")
        assert two.status_code == quarterly.status_code == yearly.status_code == 201
        words = {r["id"]: r["words"] for r in get(api, fcc, PORTAL).json()}
    assert "When: every two weeks on Friday, starting December 4, 2026." in \
        words[two.json()["id"]]
    assert ("When: on the 1st of January, April, July and October, starting January 1, 2027."
            in words[quarterly.json()["id"]])
    assert "When: every year on March 31, starting March 31, 2027." in \
        words[yearly.json()["id"]]


@pytest.mark.django_db
def test_a_lead_longer_than_the_gap_is_refused_on_set_up(owner_of, api, ff, fcc):
    with at(date(2026, 11, 17)):
        weekly = set_up(api, ff, fcc, owner_of, cadence="weekly", weekday=FRI,
                        first_billing_on="2026-11-20", lead=8)
        tight = set_up(api, ff, fcc, owner_of, cadence="monthly", days_of_month=[1, 28],
                       first_billing_on="2026-12-01", lead=3)
    assert weekly.status_code == 400 and "at most 7 days before" in weekly.json()["detail"]
    assert tight.status_code == 400 and "at most 1 day before" in tight.json()["detail"]


@pytest.mark.django_db
def test_a_quarterly_subscription_bills_its_quarters_and_a_later_term_holds(
        owner_of, api, ff, fcc, connected, stub_gateway):
    with at(date(2026, 11, 17)):
        made = set_up(api, ff, fcc, owner_of, cadence="monthly", every=3, days_of_month=[1],
                      first_billing_on="2026-12-01", term_ends_on="2027-06-30", lead=7)
        schedule = ClientInvoiceSchedule.all_objects.get(pk=made.json()["id"])
        save_card(api, fcc)
        agree(api, fcc, schedule)
        post(api, fcc, f"{PORTAL}{schedule.pk}/stop/")
    agreement = BillingAgreement.all_objects.get(schedule=schedule)
    assert agreement.ends_on == date(2027, 6, 30)
    for day in (date(2026, 11, 24), date(2026, 12, 1), date(2027, 2, 22), date(2027, 3, 1),
                date(2027, 5, 25), date(2027, 6, 1), date(2027, 8, 25), date(2027, 9, 1)):
        make(connected, day)
        charge(connected, day)
    assert sorted(i.billing_date.isoformat() for i in ClientInvoice.all_objects.filter(
        schedule=schedule, status="paid")) == ["2026-12-01", "2027-03-01", "2027-06-01"]
    assert recurring.state_of(schedule, date(2027, 7, 1)) == "ended"


@pytest.mark.django_db
def test_the_agreed_schedule_cant_change_while_in_force(owner_of, api, ff, fcc, connected):
    from .test_client_invoicing import patch

    with at(date(2026, 11, 12)):
        made = set_up(api, ff, fcc, owner_of, cadence="weekly", weekday=FRI,
                      first_billing_on="2026-11-20")
        schedule = ClientInvoiceSchedule.all_objects.get(pk=made.json()["id"])
        save_card(api, fcc)
        agree(api, fcc, schedule)
        api._clients.pop(str(ff.pk), None)
        same = patch(api, ff, f"{ROOT}{schedule.pk}/", {
            "cadence": "weekly", "every": 1, "weekday": FRI, "days_of_month": [],
            "first_billing_on": "2026-11-20", "lead_days": 2})
        moved = patch(api, ff, f"{ROOT}{schedule.pk}/", {"weekday": MON,
                                                          "first_billing_on": "2026-11-23"})
    assert same.status_code == 200, same.content
    assert moved.status_code == 400 and "agreed to this schedule" in moved.json()["detail"]


@pytest.mark.django_db
def test_you_send_each_invoice_on_a_weekly_schedule_writes_a_draft_each_friday(
        owner_of, api, ff, fcc, connected):
    with at(date(2026, 11, 17)):
        made = post(api, ff, ROOT, {
            "client_company": str(fcc.client_company_id), "contact": str(owner_of.pk),
            "cadence": "weekly", "every": 1, "weekday": FRI, "first_billing_on": "2026-11-20",
            "lines": [{"description": "Weekly support", "quantity": "1",
                       "unit_price_cents": 50000}]})
    assert made.status_code == 201, made.content
    assert made.json()["mode"] == "send" and made.json()["next_on"] == "2026-11-20"
    schedule = ClientInvoiceSchedule.all_objects.get(pk=made.json()["id"])
    written = []
    day = date(2026, 11, 17)
    while day <= date(2027, 1, 2):
        with at(moment(day, 5)), tenant_context(connected.pk):
            written += services.run_schedules(connected, today=day)
        day += timedelta(days=1)
    assert [i.issue_date.isoformat() for i in written] == [
        "2026-11-20", "2026-11-27", "2026-12-04", "2026-12-11", "2026-12-18", "2026-12-25",
        "2027-01-01"]
    assert all(i.status == "draft" and i.billing_date is None for i in written)
    schedule.refresh_from_db()
    assert schedule.next_on == date(2027, 1, 8)


@pytest.mark.django_db
def test_a_you_send_each_invoice_made_before_cadences_keeps_its_day(owner_of, api, ff, fcc,
                                                                    connected):
    with at(date(2026, 11, 17)):
        made = post(api, ff, ROOT, {
            "client_company": str(fcc.client_company_id), "contact": str(owner_of.pk),
            "day_of_month": 5, "lines": [{"description": "Retainer", "quantity": "1",
                                          "unit_price_cents": 50000}]})
    row = made.json()
    assert row["next_on"] == "2026-12-05" and row["first_billing_on"] is None
    assert row["timing_words"] == ""
    schedule = ClientInvoiceSchedule.all_objects.get(pk=row["id"])
    with at(date(2026, 12, 5)), tenant_context(connected.pk):
        [draft] = services.run_schedules(connected, today=date(2026, 12, 5))
    schedule.refresh_from_db()
    assert draft.issue_date == date(2026, 12, 5) and schedule.next_on == date(2027, 1, 5)
