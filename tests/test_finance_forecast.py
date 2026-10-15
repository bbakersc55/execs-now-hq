"""P6 M2, the first stop (`docs/p6_m2_cash_forecast.md`): the cash forecast
from known and regular lines, the card, the floor, and the module switch.

1. The module, practice isolation and role boundaries.
2. Where it starts, and the arithmetic of the table.
3. Known lines: invoices, how each client pays, what is left out.
4. Regular lines: monthly, quarterly, estimated tax, "likely annual".
5. The card. The floor and below zero. The dashboard and the download.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.billing import services as billing
from apps.finance import forecast, reconcile, reports, services
from apps.finance.disclaimer import DISCLAIMER
from apps.finance.models import FinanceAccount, FinanceForecastSettings
from apps.tenancy import modules
from apps.tenancy.context import tenant_context
from apps.tenancy.models import AuditEvent

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import FinanceMonthCloseFactory
from .test_client_invoicing import (  # noqa: F401  (fixtures and helpers)
    LINES, TOTAL, a_client, acme, call, draft, ecc, get, patch, post, ready_to_bill, sent,
)
from .test_finance_books import (  # noqa: F401
    A, C, E, R, add, books, snapshot, working_chart,
)
from .test_platform_practices import platform_owner, practices  # noqa: F401
from .test_platform_practices import post as platform_post

F = "/api/finance-forecast/"
TODAY = timezone.localdate()
THIS = TODAY.replace(day=1)
OPENING, OWED = 1_000_000, 50_000          # the `books` fixture's bank and card


def back(months: int) -> date:
    """The first day of the month this many months before this one."""
    return forecast._add_months(THIS, -months)


def on(month: date, day: int) -> str:
    return month.replace(day=day).isoformat()


def closed(tenant, *months) -> None:
    """These months are closed, as the close would have left them."""
    for month in months:
        FinanceMonthCloseFactory(tenant=tenant, month=month)


def line(result, label, cadence=None):
    found = [row for row in result["lines"] if row["label"] == label
             and (cadence is None or row["cadence"] == cadence)]
    return sorted(found, key=lambda row: row["on_date"])


@pytest.fixture
def cash(books, ff):          # noqa: F811
    """A practice with Bookkeeping and the Cash forecast, a bank and a card."""
    for module in (modules.BOOKKEEPING, modules.FORECAST):
        modules.set_enabled(books["tenant"], module, True, actor=ff.user)
    return books


def build(kit):
    with tenant_context(kit["tenant"].pk):
        return forecast.build(kit["tenant"], TODAY)


NOBODY = "00000000-0000-4000-8000-000000000000"
CALLS = [("get", F, None), ("post", F + "floor/", {"floor_cents": 100}),
         ("get", F + "export/", None),
         # Stop 2.
         ("post", F + "what-if/", {"off": [], "on": []}),
         ("post", F + "planned/", {"description": "A hire", "amount_cents": 5,
                                   "on_date": "2027-01-01"}),
         ("patch", f"{F}planned/{NOBODY}/", {"amount_cents": 6}),
         ("delete", f"{F}planned/{NOBODY}/", None),
         ("post", f"{F}planned/{NOBODY}/happened/", {}),
         ("post", F + "adjust/", {"line": "pattern:x", "kind": "not_regular"}),
         ("post", f"{F}adjust/{NOBODY}/undo/", {}),
         ("post", F + "client-names/", {"include": True}),
         ("get", F + "explain/", None), ("post", F + "explain/", {"view": "90"}),
         ("post", F + "review/", {})]


# ======================================= the module, isolation, role boundaries

@pytest.mark.django_db
def test_the_forecast_is_a_module_of_its_own_that_needs_bookkeeping(
        books, ff, api, platform_owner, seeded_tenant):          # noqa: F811
    add(api, ff, books, "expense", 100, on(back(1), 3), "Travel")
    before = snapshot(seeded_tenant)
    # A practice without it: no route, no dashboard line, nothing in /api/me.
    for method, url, body in CALLS:
        assert call(api.as_(ff), method, url, body).status_code == 404, url
    assert get(api, ff, "/api/me").json()["modules"] == []
    assert get(api, ff, "/api/dashboard/").json()["finance"]["forecast"] is None
    assert snapshot(seeded_tenant) == before

    client = practices(api, platform_owner)
    url = f"/api/platform/practices/{seeded_tenant.pk}/modules"
    # It reads closed months, which only Bookkeeping makes.
    refused = platform_post(client, url, {"module": "forecast", "enabled": True})
    assert refused.status_code == 409 and "needs Bookkeeping" in refused.json()["detail"]
    assert not modules.has(seeded_tenant, modules.FORECAST)
    assert platform_post(client, url, {"module": "bookkeeping", "enabled": True}) \
        .status_code == 200
    switched = platform_post(client, url, {"module": "forecast", "enabled": True})
    assert switched.status_code == 200
    assert switched.json()["modules"] == [
        {"code": "bookkeeping", "name": "Bookkeeping", "enabled": True},
        {"code": "forecast", "name": "Cash forecast", "enabled": True},
        {"code": "personal", "name": "Personal finance", "enabled": False}]
    assert get(api, ff, "/api/me").json()["modules"] == ["bookkeeping", "forecast"]
    assert get(api, ff, F).status_code == 200
    # And Bookkeeping stays while the forecast rests on it.
    held = platform_post(client, url, {"module": "bookkeeping", "enabled": False})
    assert held.status_code == 409 and "Cash forecast needs Bookkeeping" in \
        held.json()["detail"]
    assert platform_post(client, url, {"module": "forecast", "enabled": False}) \
        .status_code == 200
    assert get(api, ff, F).status_code == 404
    with tenant_context(seeded_tenant.pk):
        assert list(AuditEvent.objects.filter(verb__startswith="practice.module")
                    .order_by("created_at").values_list("verb", "payload__module")) == [
            ("practice.module_enabled", "bookkeeping"),
            ("practice.module_enabled", "forecast"),
            ("practice.module_disabled", "forecast")]


@pytest.mark.django_db
def test_role_boundaries_the_forecast_is_the_practice_owners(
        cash, ff, cf, va, fcc, ecc, platform_owner, api):          # noqa: F811
    add(api, ff, cash, "expense", 4242400, on(back(1), 3), "Travel",
        description="SECRET-RENT")
    post(api, ff, F + "floor/", {"floor_cents": 3131300})
    before = snapshot(cash["tenant"])
    for who, status in ((va, 403), (cf, 403), (fcc, 404), (ecc, 404)):
        for method, url, body in CALLS:
            response = call(api.as_(who), method, url, body)
            assert response.status_code == status, (who.role, url)
            for secret in (b"SECRET-RENT", b"42424", b"31313"):
                assert secret not in response.content
        # And no forecast figure in anything else they are sent.
        board = get(api, who, "/api/dashboard/")
        if board.status_code == 200:
            assert board.json().get("finance") is None
    client = practices(api, platform_owner)
    for method, url, body in CALLS:
        assert call(client, method, url, body).status_code in (403, 404)
    assert snapshot(cash["tenant"]) == before
    with tenant_context(cash["tenant"].pk):
        assert FinanceForecastSettings.objects.get().floor_cents == 3131300


@pytest.mark.django_db
def test_tenant_isolation_a_forecast_is_made_of_its_own_practice_only(
        cash, ff, tenant_b, api):          # noqa: F811
    closed(cash["tenant"], back(2), back(1))
    for month in (back(2), back(1)):
        add(api, ff, cash, "expense", 69500, on(month, 1), "Rent and coworking",
            counterparty="SECRET-LANDLORD")
    company, contact = a_client(cash["tenant"], name="SecretCo Holdings")
    with tenant_context(cash["tenant"].pk):
        billing.update_settings(cash["tenant"], {"pay_instructions": "Bank transfer."})
    sent(api, ff, company, contact)
    post(api, ff, F + "floor/", {"floor_cents": 7777700})
    mine = get(api, ff, F).json()
    assert line(mine, "SECRET-LANDLORD") and mine["floor_cents"] == 7777700
    # Another practice, with both modules, two closed months and its own books.
    other = _member(tenant_b, "FF")
    for module in (modules.BOOKKEEPING, modules.FORECAST):
        modules.set_enabled(tenant_b, module, True, actor=other.user)
    closed(tenant_b, back(2), back(1))
    post(api, other, A, {"name": "Their bank", "opening_on": on(back(3), 1),
                         "opening_balance_cents": 12300})
    theirs = get(api, other, F)
    assert theirs.status_code == 200
    body = theirs.content.decode()
    for secret in ("SECRET-LANDLORD", "SecretCo", "69500", "7777700", "Checking"):
        assert secret not in body, secret
    theirs = theirs.json()
    assert theirs["cash_today_cents"] == 12300 and theirs["lines"] == []
    assert theirs["floor_cents"] is None and theirs["ready"] is True
    assert all(row["end_cents"] == 12300 for row in theirs["weeks"])
    assert "SECRET-LANDLORD" not in get(api, other, F + "export/").content.decode()
    # Their floor is theirs, and ours is as we set it.
    post(api, other, F + "floor/", {"floor_cents": 500})
    assert get(api, ff, F).json()["floor_cents"] == 7777700


# ======================================== where it starts, and the arithmetic

@pytest.mark.django_db
def test_it_starts_from_cash_today_and_a_card_is_not_cash(cash, ff, api):          # noqa: F811
    add(api, ff, cash, "expense", 25_000, on(back(1), 5), "Travel")
    add(api, ff, cash, "expense", 9_000, on(back(1), 6), "Travel", account="card")
    till = post(api, ff, A, {"name": "Petty cash", "kind": "cash", "opening_on": on(back(3), 1),
                             "opening_balance_cents": 20_000}).json()
    shut = post(api, ff, A, {"name": "Old savings", "kind": "bank", "opening_on": on(back(3), 1),
                             "opening_balance_cents": 99_900}).json()
    patch(api, ff, f"{A}{shut['id']}/", {"closed": True})
    result = build(cash)
    assert result["cash_today_cents"] == OPENING - 25_000 + 20_000
    assert [(row["name"], row["amount_cents"]) for row in result["accounts"]] == [
        ("Checking", OPENING - 25_000), ("Petty cash", 20_000)], "no card, no closed account"
    with tenant_context(cash["tenant"].pk):
        board = reports.balance(cash["tenant"], as_of=TODAY)
    assert result["cash_today_cents"] == board["cash_total_cents"] - 99_900
    # How fresh each is: its last entry, how far it is reconciled, and stale or not.
    by_name = {row["name"]: row for row in result["accounts"]}
    assert by_name["Checking"]["last_entry_on"] == on(back(1), 5)
    assert by_name["Checking"]["reconciled_through"] is None
    assert by_name["Checking"]["stale"] is ((TODAY - back(1).replace(day=5)).days > 14)
    assert by_name["Petty cash"]["stale"] is True and by_name["Petty cash"][
        "last_entry_on"] is None and till["id"]
    # A payment received and not yet placed in an account is cash the practice has.
    assert result["unplaced_cents"] == 0


@pytest.mark.django_db
def test_each_weeks_end_is_its_start_plus_in_less_out_and_the_next_weeks_start(
        cash, ff, api):          # noqa: F811
    closed(cash["tenant"], back(3), back(2), back(1))
    for month in (back(3), back(2), back(1)):
        add(api, ff, cash, "expense", 69_500, on(month, 1), "Rent and coworking",
            counterparty="Larimer Square Cowork")
        add(api, ff, cash, "owner", 400_000, on(month, 28), "Draws", direction="out",
            counterparty="John Carter")
        add(api, ff, cash, "income", 12_300, on(month, 9), "Referral fees received",
            counterparty="Welton Partners")
    result = build(cash)
    assert len(result["weeks"]) == 26 and len(result["months"]) == 12
    counted = {row["id"]: row for row in result["lines"] if row["counted"]}
    for rows in (result["weeks"], result["months"]):
        assert rows[0]["start_cents"] == result["cash_today_cents"]
        for index, row in enumerate(rows):
            assert row["end_cents"] == row["start_cents"] + row["in_cents"] - row["out_cents"]
            if index:
                assert row["start_cents"] == rows[index - 1]["end_cents"]
                assert row["start"] == (date.fromisoformat(rows[index - 1]["end"])
                                        + timedelta(days=1)).isoformat()
            mine = [counted[i] for i in row["lines"]]
            assert all(row["start"] <= each["on_date"] <= row["end"] for each in mine)
            assert row["in_cents"] == sum(m["amount_cents"] for m in mine
                                          if m["direction"] == "in")
            assert row["out_cents"] == sum(m["amount_cents"] for m in mine
                                           if m["direction"] == "out")
    assert result["weeks"][0]["start"] == TODAY.isoformat()
    assert result["months"][0]["start"] == TODAY.isoformat()
    assert result["months"][0]["end"] == reconcile.month_end(THIS).isoformat()
    # No line is in two weeks, and none in the weekly span is in no week.
    in_weeks = [i for row in result["weeks"] for i in row["lines"]]
    assert len(in_weeks) == len(set(in_weeks))
    last = result["weeks"][-1]["end"]
    assert set(in_weeks) == {i for i, row in counted.items() if row["on_date"] <= last}
    # The three views are the first 5, 13 and 26 weeks: their low points are the table's.
    for days, count in (("30", 5), ("90", 13), ("180", 26)):
        rows = result["weeks"][:count]
        low = min(rows, key=lambda row: row["end_cents"])
        assert result["views"][days]["low_cents"] == low["end_cents"]
        assert result["views"][days]["low_start"] == low["start"]
        assert result["views"][days]["end_cents"] == rows[-1]["end_cents"]
    assert result["views"]["months"]["low_cents"] == min(
        row["end_cents"] for row in result["months"])
    assert result["disclaimer"] == DISCLAIMER


@pytest.mark.django_db
def test_with_fewer_than_two_closed_months_it_is_invoices_only_and_says_so(
        cash, ff, api):          # noqa: F811
    for month in (back(3), back(2), back(1)):
        add(api, ff, cash, "expense", 69_500, on(month, 1), "Rent and coworking",
            counterparty="Larimer Square Cowork")
    company, contact = a_client(cash["tenant"])
    with tenant_context(cash["tenant"].pk):
        billing.update_settings(cash["tenant"], {"pay_instructions": "Bank transfer."})
    sent(api, ff, company, contact)
    closed(cash["tenant"], back(1))
    one = build(cash)
    assert (one["ready"], one["closed_months"]) == (False, 1)
    assert one["note"] == ("Close two months and your regular costs will be forecast from "
                           "them. Until then this is only your invoices.")
    assert {row["kind"] for row in one["lines"]} == {"known", "card"}
    assert one["likely_annual"] == []
    # A month "locked before month close began" is locked, not closed (M1-9).
    with tenant_context(cash["tenant"].pk):
        FinanceForecastSettings.objects.all().delete()
        services.settings_for(cash["tenant"])
        from apps.finance.models import FinanceSettings

        FinanceSettings.objects.update(locked_through=reconcile.month_end(back(1)))
    assert build(cash)["ready"] is False
    assert get(api, ff, "/api/dashboard/").json()["finance"]["forecast"] is None
    closed(cash["tenant"], back(2))
    two = build(cash)
    assert (two["ready"], two["note"], two["closed_through"]) == (
        True, "", reconcile.month_end(back(1)).isoformat())
    assert line(two, "Larimer Square Cowork")


# ================================================================ known lines

@pytest.fixture
def billing_ready(cash):
    with tenant_context(cash["tenant"].pk):
        billing.update_settings(cash["tenant"], {"pay_instructions": "Bank transfer.",
                                                 "terms_days": 15})
    return cash


def invoice(api, ff, company, contact, issued: date, due: date, paid_on=None, amount=None):
    made = sent(api, ff, company, contact, issue_date=issued.isoformat(),
                due_date=due.isoformat())
    if paid_on is not None:
        paid = post(api, ff, f"/api/invoices/{made['id']}/payments/",
                    {"amount_cents": amount or made["total_cents"],
                     "paid_on": paid_on.isoformat()})
        assert paid.status_code in (200, 201), paid.content
    return made


@pytest.mark.django_db
def test_an_invoice_lands_when_that_client_usually_pays_never_before_it_is_due(
        billing_ready, ff, api):
    tenant = billing_ready["tenant"]
    slow, slow_contact = a_client(tenant, name="Slow Payers Inc")
    early, early_contact = a_client(tenant, name="Early Birds LLC", first="Eve")
    new, new_contact = a_client(tenant, name="New Client Co", first="Ned")
    # Slow pays 9, 12 and 30 days late: the median is 12, not the average of 17.
    for months, late in ((4, 9), (3, 12), (2, 30)):
        due = back(months).replace(day=5)
        invoice(api, ff, slow, slow_contact, due - timedelta(days=15), due,
                paid_on=due + timedelta(days=late))
    # Early pays a week before it is due, every time: forecast on the due date.
    for months in (4, 3, 2):
        due = back(months).replace(day=20)
        invoice(api, ff, early, early_contact, due - timedelta(days=15), due,
                paid_on=due - timedelta(days=7))
    # New has paid twice: not enough to go on.
    for months in (3, 2):
        due = back(months).replace(day=10)
        invoice(api, ff, new, new_contact, due - timedelta(days=15), due,
                paid_on=due + timedelta(days=40))
    due = TODAY + timedelta(days=20)
    open_ = {name: invoice(api, ff, company, contact, TODAY, due)
             for name, company, contact in (("slow", slow, slow_contact),
                                            ("early", early, early_contact),
                                            ("new", new, new_contact))}
    result = build(billing_ready)
    found = {row["id"]: row for row in result["lines"] if row["kind"] == "known"}
    expected = {"slow": due + timedelta(days=12), "early": due, "new": due}
    for name, made in open_.items():
        row = found[f"invoice:{made['id']}"]
        assert row["on_date"] == expected[name].isoformat(), name
        assert (row["direction"], row["amount_cents"], row["counted"]) == ("in", TOTAL, True)
        assert row["link"] == f"/invoices/{made['id']}"
    assert "12 days after its due date, as this client usually pays" in \
        found[f"invoice:{open_['slow']['id']}"]["detail"]
    assert "on its due date, as this client usually pays" in \
        found[f"invoice:{open_['early']['id']}"]["detail"]
    assert "fewer than 3 paid invoices to go on" in \
        found[f"invoice:{open_['new']['id']}"]["detail"]
    assert found[f"invoice:{open_['slow']['id']}"]["label"] == \
        f"Slow Payers Inc: Invoice {open_['slow']['number']}"
    assert len(found) == 3, "a paid invoice is not forecast"


@pytest.mark.django_db
def test_part_paid_overdue_unsent_and_long_overdue_invoices(billing_ready, ff, api):
    company, contact = a_client(billing_ready["tenant"])
    # Part paid: what is left.
    part = invoice(api, ff, company, contact, TODAY - timedelta(days=5),
                   TODAY + timedelta(days=10), paid_on=TODAY - timedelta(days=1),
                   amount=100_000)
    # A little overdue: it lands today, not in the past.
    recent = invoice(api, ff, company, contact, TODAY - timedelta(days=40),
                     TODAY - timedelta(days=25))
    # More than 60 days overdue: hoped for, not forecast.
    old = invoice(api, ff, company, contact, TODAY - timedelta(days=90),
                  TODAY - timedelta(days=75))
    # Written and not sent: as if sent today.
    unsent = draft(api, ff, company, contact, issue_date=(TODAY - timedelta(days=30))
                   .isoformat(), due_date=(TODAY - timedelta(days=15)).isoformat()).json()
    result = build(billing_ready)
    found = {row["id"]: row for row in result["lines"] if row["kind"] == "known"}
    assert found[f"invoice:{part['id']}"]["amount_cents"] == TOTAL - 100_000
    assert "what is left" in found[f"invoice:{part['id']}"]["detail"]
    assert found[f"invoice:{recent['id']}"]["on_date"] == TODAY.isoformat()
    assert f"invoice:{old['id']}" not in found
    assert result["left_out"] == [{
        "id": old["id"], "group": f"invoice:{old['id']}",
        "label": f"Acme Facilities: Invoice {old['number']}",
        "amount_cents": TOTAL, "due_date": (TODAY - timedelta(days=75)).isoformat(),
        "days_overdue": 75, "why": "more than 60 days overdue", "adjustment": "",
        "link": f"/invoices/{old['id']}"}]
    waiting = found[f"invoice:{unsent['id']}"]
    assert waiting["on_date"] == TODAY.isoformat() and waiting["amount_cents"] == TOTAL
    assert waiting["detail"].startswith("Not sent yet. As if sent today")
    assert waiting["label"] == "Acme Facilities: A draft invoice"
    # What is left out is in no week's money in.
    assert sum(row["in_cents"] for row in result["weeks"]) == (TOTAL - 100_000) + 2 * TOTAL


@pytest.mark.django_db
def test_a_recurring_schedule_is_forecast_each_month_to_its_end_and_no_further(
        billing_ready, ff, api):
    company, contact = a_client(billing_ready["tenant"])
    first = forecast._add_months(THIS, 1)
    ends = forecast._add_months(THIS, 3).replace(day=10)
    made = post(api, ff, "/api/invoice-schedules/", {
        "client_company": str(company.pk), "contact": str(contact.pk), "day_of_month": 1,
        "starts_on": first.isoformat(), "ends_on": ends.isoformat(), "lines": LINES})
    assert made.status_code == 201
    paused = post(api, ff, "/api/invoice-schedules/", {
        "client_company": str(company.pk), "contact": str(contact.pk), "day_of_month": 1,
        "starts_on": first.isoformat(), "lines": LINES}).json()
    patch(api, ff, f"/api/invoice-schedules/{paused['id']}/", {"is_active": False})
    result = build(billing_ready)
    lines_ = line(result, "Acme Facilities: recurring invoice")
    # Written on the 1st of each of three months, due 15 days later.
    assert [row["on_date"] for row in lines_] == [
        (forecast._add_months(THIS, n) + timedelta(days=15)).isoformat() for n in (1, 2, 3)]
    assert all(row["amount_cents"] == TOTAL and row["kind"] == "known" for row in lines_)
    assert "Its schedule writes it on" in lines_[0]["detail"]


# ============================================================== regular lines

@pytest.mark.django_db
def test_a_monthly_cost_is_found_in_two_of_the_last_three_closed_months(cash, ff, api):          # noqa: F811
    closed(cash["tenant"], back(3), back(2), back(1))
    for month in (back(3), back(2), back(1)):
        add(api, ff, cash, "expense", 69_500, on(month, 1), "Rent and coworking",
            counterparty="Larimer Square Cowork")
    # A different amount each month: the median.
    for month, cents in ((back(3), 10_000), (back(2), 30_000), (back(1), 20_000)):
        add(api, ff, cash, "expense", cents, on(month, 12), "Advertising",
            counterparty="LinkedIn Ads")
    # In two of the three: regular. In one: not.
    for month in (back(3), back(1)):
        add(api, ff, cash, "expense", 4_500, on(month, 15), "Bank and merchant fees",
            description="Monthly service fee 0041")
    add(api, ff, cash, "expense", 185_000, on(back(1), 18), "Accounting",
        counterparty="Ledger & Quill")
    # An open month is not read: twice this month does not make it regular.
    for _ in range(2):
        add(api, ff, cash, "expense", 7_700, on(THIS, 1), "Meals", counterparty="Rioja")

    result = build(cash)
    rent = line(result, "Larimer Square Cowork")
    assert [row["amount_cents"] for row in rent] == [69_500] * len(rent)
    # Not yet entered this month: still expected, today at the earliest; then the 1st.
    assert rent[0]["on_date"] == TODAY.isoformat()
    assert rent[1]["on_date"] == forecast._add_months(THIS, 1).isoformat()
    assert len(rent) == 12 and rent[0]["cadence"] == "monthly" and rent[0]["counted"]
    assert rent[0]["category"] == "Rent and coworking" and rent[0]["direction"] == "out"
    assert rent[0]["detail"] == ("$695.00 on the 1st, monthly: the same amount of 3 of the "
                                 "last 3 closed months.")
    ads = line(result, "LinkedIn Ads")
    assert {row["amount_cents"] for row in ads} == {20_000}
    assert "the median of 3 of the last 3 closed months" in ads[0]["detail"]
    assert ads[0]["category"] == "Marketing and advertising: Advertising"
    fee = line(result, "Monthly service fee 0041")
    assert fee and fee[0]["amount_cents"] == 4_500 and "2 of the last 3" in fee[0]["detail"]
    assert line(result, "Ledger & Quill") == [] and line(result, "Rioja") == []

    # Entered for this month already: not forecast again for it.
    add(api, ff, cash, "expense", 69_500, on(THIS, 1), "Rent and coworking",
        counterparty="Larimer Square Cowork")
    again = line(build(cash), "Larimer Square Cowork")
    assert len(again) == 11 and again[0]["on_date"] == forecast._add_months(THIS, 1).isoformat()


@pytest.mark.django_db
def test_a_quarterly_cost_estimated_tax_and_a_likely_annual_one(cash, ff, api):          # noqa: F811
    months = [back(n) for n in range(9, 0, -1)]
    closed(cash["tenant"], *months)
    # Quarterly: seen three times, three months apart.
    for n in (7, 4, 1):
        add(api, ff, cash, "expense", 75_000, on(back(n), 12), "Events and sponsorships",
            counterparty="Denver Metro Chamber")
    # Monthly too (so two cadences sit side by side).
    for month in months[-3:]:
        add(api, ff, cash, "expense", 69_500, on(month, 1), "Rent and coworking",
            counterparty="Larimer Square Cowork")
    # Irregular: twice, a month apart and then never. Neither monthly nor quarterly.
    for n in (8, 7):
        add(api, ff, cash, "expense", 5_000, on(back(n), 9), "Supplies",
            counterparty="Office Depot")
    # Estimated tax, marked: quarterly by definition, on the dates it is due.
    add(api, ff, cash, "owner", 450_000, on(back(5), 15), "Estimated tax payments",
        direction="out", estimated_tax="federal", counterparty="IRS")
    add(api, ff, cash, "owner", 480_000, on(back(2), 15), "Estimated tax payments",
        direction="out", estimated_tax="federal", counterparty="IRS")
    add(api, ff, cash, "owner", 90_000, on(back(2), 15), "Estimated tax payments",
        direction="out", estimated_tax="state", counterparty="State")

    result = build(cash)
    chamber = line(result, "Denver Metro Chamber")
    assert chamber and all(row["cadence"] == "quarterly" and row["amount_cents"] == 75_000
                           for row in chamber)
    assert [row["on_date"] for row in chamber][:3] == [
        forecast._add_months(back(1).replace(day=12), 3 * k).isoformat() for k in (1, 2, 3)]
    assert "quarterly: seen 3 times in the last 9 closed months" in chamber[0]["detail"]
    assert line(result, "Office Depot") == []
    # The last amount of each mark, on each of the dates still ahead.
    end = date.fromisoformat(result["months"][-1]["end"])
    due = sorted(d for year in (TODAY.year, TODAY.year + 1)
                 for d in (date(year, m, 15) for m in (1, 4, 6, 9)) if TODAY <= d <= end)
    federal = line(result, "Estimated tax, federal")
    assert [row["on_date"] for row in federal] == [d.isoformat() for d in due]
    assert {row["amount_cents"] for row in federal} == {480_000}, "the last, not the first"
    assert {row["amount_cents"] for row in line(result, "Estimated tax, state")} == {90_000}
    assert federal[0]["cadence"] == "quarterly" and federal[0]["direction"] == "out"
    # A marked payment is not also found as an ordinary regular line.
    assert line(result, "IRS") == [] and line(result, "State") == []
    assert result["likely_annual"] == []


@pytest.mark.django_db
def test_something_seen_once_a_year_ago_is_listed_and_not_forecast(cash, ff, api):          # noqa: F811
    closed(cash["tenant"], *[back(n) for n in range(13, 0, -1)])
    renewal = add(api, ff, cash, "expense", 119_900, on(back(12), 8), "Software",
                  counterparty="Adobe annual plan")
    assert renewal.status_code == 201
    add(api, ff, cash, "expense", 30_000, on(back(6), 8), "Software",
        counterparty="Six months ago")                   # once, but not a year ago
    for n in (12, 6):
        add(api, ff, cash, "expense", 8_000, on(back(n), 3), "Supplies",
            counterparty="Twice a year")                 # seen since: not "once"
    result = build(cash)
    assert [(row["label"], row["amount_cents"], row["last_on"], row["likely_on"])
            for row in result["likely_annual"]] == [
        ("Adobe annual plan", 119_900, on(back(12), 8), on(THIS, 8))]
    assert "it is not in the forecast until you confirm it" in \
        result["likely_annual"][0]["detail"]
    assert result["likely_annual"][0]["category"] == "Software and subscriptions: Software"
    # Listed, and in no week, month or line: the only money out is the card's.
    assert line(result, "Adobe annual plan") == []
    assert {row["kind"] for row in result["lines"]} == {"card"}
    assert sum(row["out_cents"] for row in result["months"]) == OWED


# ===================================================================== the card

@pytest.mark.django_db
def test_what_is_owed_on_a_card_leaves_the_bank_on_its_usual_day(cash, ff, api):          # noqa: F811
    closed(cash["tenant"], back(3), back(2), back(1))
    for month in (back(3), back(2), back(1)):
        add(api, ff, cash, "expense", 9_900, on(month, 11), "Software", account="card",
            counterparty="Intuit")
        post(api, ff, E, {"kind": "transfer", "amount_cents": 9_900, "on_date": on(month, 20),
                          "account": cash["bank"]["id"], "to_account": cash["card"]["id"]})
    result = build(cash)
    with tenant_context(cash["tenant"].pk):
        card = FinanceAccount.objects.get(pk=cash["card"]["id"])
        owed = reports.account_balance(cash["tenant"], card, TODAY)
    assert owed == OWED
    # A charge on the card is a regular line that is not cash...
    charges = line(result, "Intuit")
    assert charges and all(not row["counted"] and row["on_card"] == cash["card"]["id"]
                           for row in charges)
    # ...and the card's payments are: what is owed today, on the 20th; then
    # what is forecast to be charged, the month after it is charged.
    payments = line(result, "Business card payment")
    first = TODAY.replace(day=20) if TODAY.day <= 20 else forecast._add_months(TODAY, 1, 20)
    assert payments[0]["on_date"] == first.isoformat()
    assert payments[0]["amount_cents"] == OWED and payments[0]["kind"] == "card"
    assert payments[0]["counted"] and payments[0]["direction"] == "out"
    assert "What is owed on Business card today, $500.00" in payments[0]["detail"]
    assert payments[1]["on_date"] == forecast._add_months(first, 1, 20).isoformat()
    assert all(row["amount_cents"] == 9_900 for row in payments[2:])
    # Every forecast charge is paid once, by the payment after it.
    last_paid_through = forecast._add_months(
        date.fromisoformat(payments[-1]["on_date"]), -1, 20)
    assert sum(row["amount_cents"] for row in payments[1:]) == sum(
        row["amount_cents"] for row in charges
        if date.fromisoformat(row["on_date"]) <= last_paid_through)
    # The transfer that pays the card is not itself found as a regular cost.
    assert [row for row in result["lines"] if "transfer" in row["label"].lower()] == []
    week_out = sum(row["out_cents"] for row in result["weeks"])
    assert week_out == sum(row["amount_cents"] for row in payments
                           if row["on_date"] <= result["weeks"][-1]["end"])


# ======================================================= the floor, below zero

@pytest.mark.django_db
def test_the_floor_is_the_owners_to_set_and_below_zero_is_always_marked(cash, ff, api):          # noqa: F811
    closed(cash["tenant"], back(3), back(2), back(1))
    for month in (back(3), back(2), back(1)):
        add(api, ff, cash, "owner", 150_000, on(month, 28), "Draws", direction="out",
            counterparty="John Carter")
    start = get(api, ff, F).json()
    assert start["floor_cents"] is None, "empty until the owner sets it"
    assert not any(row["below_floor"] for row in start["weeks"])
    assert start["views"]["90"]["first_below_floor"] is None
    # $5,500 today, $500 to the card and $1,500 out a month: under nothing
    # at the fourth draw, and marked with no floor set at all.
    under = [row for row in start["months"] if row["below_zero"]]
    assert under and under[0]["end_cents"] < 0 <= start["months"][
        start["months"].index(under[0]) - 1]["end_cents"]
    assert start["views"]["months"]["first_below_zero"] == under[0]["start"]
    assert start["views"]["180"]["first_below_zero"] == next(
        row["start"] for row in start["weeks"] if row["end_cents"] < 0)
    assert start["views"]["30"]["first_below_zero"] is None

    floored = post(api, ff, F + "floor/", {"floor_cents": 500_000})
    assert floored.status_code == 200
    floored = floored.json()
    assert floored["floor_cents"] == 500_000
    first = next(row for row in floored["weeks"] if row["end_cents"] < 500_000)
    assert floored["views"]["180"]["first_below_floor"] == first["start"]
    assert [row["below_floor"] for row in floored["weeks"]] == [
        row["end_cents"] < 500_000 for row in floored["weeks"]]
    assert [row["below_zero"] for row in floored["weeks"]] == [
        row["end_cents"] < 0 for row in floored["weeks"]]
    assert floored["weeks"] == [{**a, "below_floor": b["below_floor"]}
                                for a, b in zip(start["weeks"], floored["weeks"])], \
        "the floor changes what is marked and no figure"
    # None is no floor; it is a whole number of cents, and not negative.
    assert post(api, ff, F + "floor/", {"floor_cents": None}).json()["floor_cents"] is None
    for bad in (-1, "5000", 12.5, True):
        assert post(api, ff, F + "floor/", {"floor_cents": bad}).status_code == 400, bad
    with tenant_context(cash["tenant"].pk):
        changes = [(e.payload["before"], e.payload["after"]) for e in AuditEvent.objects
                   .filter(verb="finance.forecast_floor_changed").order_by("created_at")]
    assert changes == [(None, 500_000), (500_000, None)]


# ============================================ the dashboard and the download

@pytest.mark.django_db
def test_the_owners_dashboard_has_the_low_point_of_the_next_13_weeks(cash, ff, api):          # noqa: F811
    assert get(api, ff, "/api/dashboard/").json()["finance"]["forecast"] is None, \
        "not until two months are closed"
    closed(cash["tenant"], back(2), back(1))
    for month in (back(2), back(1)):
        add(api, ff, cash, "owner", 100_000, on(month, 28), "Draws", direction="out",
            counterparty="John Carter")
    post(api, ff, F + "floor/", {"floor_cents": 900_000})
    shown = get(api, ff, "/api/dashboard/").json()["finance"]["forecast"]
    view = get(api, ff, F).json()["views"]["90"]
    assert shown == {"low_cents": view["low_cents"], "week_of": view["low_start"],
                     "below_zero": False, "below_floor": True}
    assert shown["low_cents"] < OPENING
    # The month's own figures are still there beside it.
    assert "revenue_cents" in get(api, ff, "/api/dashboard/").json()["finance"]


@pytest.mark.django_db
def test_the_download_is_the_weekly_table_and_its_lines_and_is_recorded(
        billing_ready, ff, api):
    tenant = billing_ready["tenant"]
    closed(tenant, back(3), back(2), back(1))
    for month in (back(3), back(2), back(1)):
        add(api, ff, billing_ready, "expense", 69_500, on(month, 1), "Rent and coworking",
            counterparty="Larimer Square Cowork")
    company, contact = a_client(tenant)
    old = invoice(api, ff, company, contact, TODAY - timedelta(days=90),
                  TODAY - timedelta(days=75))
    post(api, ff, F + "floor/", {"floor_cents": 250_000})
    response = get(api, ff, F + "export/")
    assert response.status_code == 200 and response["Content-Type"].startswith("text/csv")
    assert f'filename="cash-forecast-{TODAY.isoformat()}.csv"' in \
        response["Content-Disposition"]
    rows = list(csv.reader(io.StringIO(response.content.decode())))
    result = get(api, ff, F).json()
    assert rows[0] == [f"Cash forecast as of {TODAY.isoformat()}, 180 days by week"]
    assert rows[1] == ["Cash today", f"{result['cash_today_cents'] / 100:.2f}"]
    assert rows[2] == ["Floor", "2500.00"]
    head = rows.index(["Week starting", "Cash at the start", "Money in", "Money out",
                       "Cash at the end", "Under the floor", "Under zero"])
    table = rows[head + 1:head + 27]
    assert [row[0] for row in table] == [week["start"] for week in result["weeks"]]
    assert [row[4] for row in table] == [f"{week['end_cents'] / 100:.2f}"
                                         for week in result["weeks"]]
    rent = [row for row in rows if len(row) > 2 and row[2] == "Larimer Square Cowork"]
    assert rent and rent[0][1] == "Regular" and rent[0][6] == "695.00" and rent[0][4] == \
        "monthly" and rent[0][3] == "Rent and coworking"
    at = rows.index(["Not counted"])
    assert rows[at + 1][1] == f"Acme Facilities: Invoice {old['number']}"
    assert rows[-1] == [DISCLAIMER]
    with tenant_context(tenant.pk):
        event = AuditEvent.objects.get(verb="finance.forecast_downloaded")
        assert event.actor == ff.user and event.payload == {"as_of": TODAY.isoformat()}


@pytest.mark.django_db
def test_the_forecast_reads_the_books_and_writes_nothing_to_them(billing_ready, ff, api):
    tenant = billing_ready["tenant"]
    closed(tenant, back(2), back(1))
    for month in (back(2), back(1)):
        add(api, ff, billing_ready, "expense", 69_500, on(month, 1), "Rent and coworking",
            counterparty="Larimer Square Cowork")
    company, contact = a_client(tenant)
    sent(api, ff, company, contact)
    before = snapshot(tenant)
    with tenant_context(tenant.pk):
        events = AuditEvent.objects.count()
    for _ in range(2):
        assert get(api, ff, F).status_code == 200
        assert get(api, ff, "/api/dashboard/").status_code == 200
    assert json.loads(snapshot(tenant))["entries"] == json.loads(before)["entries"]
    with tenant_context(tenant.pk):
        assert AuditEvent.objects.count() == events, "looking at it records nothing"
