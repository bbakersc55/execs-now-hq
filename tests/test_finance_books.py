"""P5, the first stop — the books (`docs/p5_finance_accounting.md`).

1. Practice isolation, and role boundaries: the practice owner only.
2. Accounts, categories and entries; the lock; the audit trail.
3. Paid invoices become income.
4. The P&L, the balance view, the dashboard's figures and the CPA export.

The import, rules, matching and 1099 tracking are the second stop.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.billing import services as billing
from apps.finance import reports, services
from apps.finance.models import FinanceAccount, FinanceCategory, FinanceEntry
from apps.tenancy.context import tenant_context
from apps.tenancy.models import AuditEvent

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import ClientAssignmentFactory, ContactEmailFactory, ContactFactory
from .test_client_invoicing import (  # noqa: F401  (fixtures and helpers)
    LINES, TOTAL, a_client, acme, call, draft, ecc, get, patch, post, ready_to_bill, sent,
)
from .test_platform_isolation import in_practices_area

E = "/api/finance-entries/"
A = "/api/finance-accounts/"
C = "/api/finance-categories/"
R = "/api/finance-reports/"


#: The chart these tests of how the books work are written against: their
#: own, so the starting chart a new practice gets (the CPA's list, P6 M1 §5.4)
#: can change without rewriting them. The starting chart itself is tested in
#: `test_a_practice_starts_with_the_chart…` and in `test_finance_chart.py`.
WORKING_CHART = (
    ("income", (
        ("Client fees", ("Retainers", "Project fees", "Workshops and speaking")),
        ("Referral fees received", ()), ("Reimbursed expenses", ()),
        ("Interest income", ()), ("Other income", ()),
    )),
    ("expense", (
        ("Contractors and associates", ("Associates", "Assistants", "Other contractors")),
        ("Payroll", ("Wages", "Payroll taxes", "Benefits", "Payroll service fees")),
        ("Software and subscriptions", ("Software", "AI and API usage")),
        ("Marketing and advertising", ("Advertising", "Website", "Events and sponsorships")),
        ("Travel", ("Airfare", "Lodging", "Ground transport")),
        ("Meals", ()),
        ("Vehicle", ("Mileage and fuel", "Parking and tolls")),
        ("Professional services", ("Accounting", "Legal", "Coaching and consulting")),
        ("Insurance", ("Business liability", "Health")),
        ("Office", ("Supplies", "Equipment", "Postage and printing")),
        ("Rent and coworking", ()), ("Phone and internet", ()),
        ("Education and training", ()), ("Dues and memberships", ()),
        ("Bank and merchant fees", ()), ("Referral fees paid", ()),
        ("Taxes and licenses", ()), ("Interest paid", ()), ("Charitable giving", ()),
        ("Other expenses", ()),
    )),
    ("owner", (("Owner contribution", ()),
               ("Owner draw", ("Draws", "Estimated tax payments")))),
    ("held", (("Sales tax collected", ()),)),
)


def working_chart(tenant) -> None:
    from apps.finance import chart

    chart.create_starting_chart(tenant, WORKING_CHART,
                                contractor=("Contractors and associates",))


@pytest.fixture
def books(seeded_tenant, ff, api):
    """A practice with the working chart, a bank account and a card."""
    working_chart(seeded_tenant)
    bank = post(api, ff, A, {"name": "Checking", "kind": "bank", "last4": "4421",
                             "opening_balance_cents": 1000000,
                             "opening_on": "2026-01-01"}).json()
    card = post(api, ff, A, {"name": "Business card", "kind": "card",
                             "opening_balance_cents": 50000,
                             "opening_on": "2026-01-01"}).json()
    categories = {row["name"]: row for row in get(api, ff, C).json()}
    return {"tenant": seeded_tenant, "bank": bank, "card": card, "cat": categories}


def add(api, ff, books, kind, cents, on, category=None, account="bank", **more):
    body = {"kind": kind, "amount_cents": cents, "on_date": on,
            "account": books[account]["id"] if account else None, **more}
    if category:
        body["category"] = books["cat"][category]["id"]
    return post(api, ff, E, body)


def finance_calls(books, entry_id):
    return [
        ("get", E, None), ("get", f"{E}{entry_id}/history/", None),
        ("post", E, {"kind": "expense", "amount_cents": 100, "on_date": "2026-10-01",
                     "account": books["bank"]["id"]}),
        ("patch", f"{E}{entry_id}/", {"description": "Changed"}),
        ("post", f"{E}{entry_id}/remove/", {"reason": "Mistake"}),
        ("post", E + "recategorize/", {"entries": [entry_id],
                                       "category": books["cat"]["Travel"]["id"]}),
        ("get", A, None), ("post", A, {"name": "Savings"}),
        ("patch", f"{A}{books['bank']['id']}/", {"name": "Renamed"}),
        ("get", C, None), ("post", C, {"name": "Conferences", "type": "expense"}),
        ("patch", f"{C}{books['cat']['Travel']['id']}/", {"cpa_code": "24a"}),
        ("post", C + "reorder/", {"type": "owner", "ids": []}),
        ("get", "/api/finance-settings/", None),
        ("post", "/api/finance-settings/", {"locked_through": "2026-09-30"}),
        ("get", R + "pnl/?year=2026", None), ("get", R + "pnl/?year=2026&download=1", None),
        ("get", R + "balance/", None),
        ("get", R + "export-entries/?from=2026-01-01&to=2026-12-31", None),
        ("get", R + "export-summary/?from=2026-01-01&to=2026-12-31", None),
    ]


def snapshot(tenant):
    with tenant_context(tenant.pk):
        return json.dumps({
            "entries": list(FinanceEntry.objects.order_by("created_at").values(
                "pk", "kind", "amount_cents", "category_id", "account_id", "description",
                "removed_at")),
            "accounts": list(FinanceAccount.objects.order_by("created_at").values(
                "pk", "name", "closed_at")),
            "categories": list(FinanceCategory.objects.order_by("created_at").values(
                "pk", "name", "cpa_code", "position", "archived_at")),
            "exports": AuditEvent.objects.filter(verb__startswith="finance.").count(),
        }, default=str, sort_keys=True)


# ============================================== isolation and role boundaries

@pytest.mark.django_db
def test_tenant_isolation_another_practice_reaches_nothing_in_the_books(books, ff, tenant_b,
                                                                       api):
    mine = add(api, ff, books, "expense", 12500, "2026-10-01", "Travel",
               description="SECRET-TRIP").json()
    other = _member(tenant_b, "FF")
    before = snapshot(books["tenant"])
    # Their own books are their own: the chart, and nothing else.
    assert get(api, other, E).json()["entries"] == []
    assert get(api, other, A).json() == []
    assert len(get(api, other, C).json()) == 93      # its own starting chart, whole
    for method, url, body in finance_calls(books, mine["id"]):
        response = call(api.as_(other), method, url, body)
        assert b"SECRET-TRIP" not in response.content and b"Checking" not in response.content
        if mine["id"] in url or books["bank"]["id"] in url or \
                books["cat"]["Travel"]["id"] in url:
            assert response.status_code == 404, (method, url)
    # An entry of theirs cannot name an account, a category or a company of ours.
    theirs = post(api, other, A, {"name": "Their bank"}).json()
    their_cat = {row["name"]: row for row in get(api, other, C).json()}["Supplies"]
    for body in ({"account": books["bank"]["id"], "category": their_cat["id"]},
                 {"account": theirs["id"], "category": books["cat"]["Travel"]["id"]}):
        refused = post(api, other, E, {"kind": "expense", "amount_cents": 100,
                                       "on_date": "2026-10-01", **body})
        assert refused.status_code == 404
    assert get(api, other, R + "pnl/?year=2026").json()["expenses"]["total"] == 0
    assert get(api, other, R + "balance/").json()["cash_total_cents"] == 0
    assert "SECRET-TRIP" not in get(
        api, other, R + "export-entries/?from=2026-01-01&to=2026-12-31").content.decode()
    with tenant_context(tenant_b.pk):
        AuditEvent.objects.all().delete()
    assert json.loads(snapshot(books["tenant"]))["entries"] == json.loads(before)["entries"]


@pytest.mark.django_db
def test_tenant_isolation_the_platform_owner_reaches_nothing_in_the_books(books, ff, api):
    mine = add(api, ff, books, "expense", 12500, "2026-10-01", "Travel").json()
    owner = _member(books["tenant"], "FF")
    owner.user.is_platform_owner = True
    owner.user.save()
    client = in_practices_area(api.as_(owner))
    before = snapshot(books["tenant"])
    for method, url, body in finance_calls(books, mine["id"]):
        assert call(client, method, url, body).status_code in (403, 404), (method, url)
    assert snapshot(books["tenant"]) == before


@pytest.mark.django_db
def test_role_boundaries_the_books_are_the_practice_owners_alone(books, ff, cf, va, fcc, ecc,
                                                                api):
    """The non-negotiable family: an assistant and every financial endpoint.
    And an associate, who has invoices for assigned clients and nothing here."""
    company, contact = a_client(books["tenant"])
    ClientAssignmentFactory(tenant=books["tenant"], user=cf.user, company=company)
    mine = add(api, ff, books, "expense", 12500, "2026-10-01", "Travel",
               description="SECRET-TRIP", client_company=str(company.pk)).json()
    before = snapshot(books["tenant"])
    for who, status in ((va, 403), (cf, 403), (fcc, 404), (ecc, 404)):
        for method, url, body in finance_calls(books, mine["id"]):
            response = call(api.as_(who), method, url, body)
            assert response.status_code == status, (who.role, method, url)
            assert b"SECRET-TRIP" not in response.content
            assert b"12500" not in response.content
    assert snapshot(books["tenant"]) == before, "and nothing changed, not even an audit row"
    # Nor anywhere else an entry could surface.
    for who in (va, cf):
        for url in ("/api/dashboard/", "/api/activity/", "/api/contacts/search/?q=SECRET",
                    "/api/imports/", f"/api/companies/{company.pk}/timeline/"):
            body = get(api, who, url).content.decode()
            assert "SECRET-TRIP" not in body and "revenue_cents" not in body, (who.role, url)
        assert get(api, who, "/api/dashboard/").json()["finance"] is None
    assert get(api, ff, "/api/dashboard/").json()["finance"]["expenses_cents"] >= 0


@pytest.mark.django_db
def test_role_boundaries_an_associates_invoice_payment_gives_them_no_entry(
        ready_to_bill, ff, cf, api):
    """They keep what invoicing gave them and gain nothing of the books."""
    company, contact = a_client(ready_to_bill)
    ClientAssignmentFactory(tenant=ready_to_bill, user=cf.user, company=company)
    invoice = sent(api, ff, company, contact)
    post(api, ff, f"/api/invoices/{invoice['id']}/payments/",
         {"amount_cents": TOTAL, "paid_on": "2026-10-03"})
    assert get(api, cf, f"/api/invoices/{invoice['id']}/").json()["status"] == "paid"
    assert get(api, cf, E).status_code == 403
    assert get(api, ff, E).json()["entries"][0]["amount_cents"] == TOTAL


# ================================================== the chart and the accounts

@pytest.mark.django_db
def test_a_practice_starts_with_the_chart_and_edits_it_freely(seeded_tenant, ff, api):
    rows = get(api, ff, C).json()
    by_type = {}
    for row in rows:
        by_type.setdefault(row["type"], []).append(row["name"])
    # The starting chart of P6 M1 §5.4: categories, and sub-categories under some.
    top = {t: [row["name"] for row in rows if row["type"] == t and not row["parent"]]
           for t in by_type}
    assert [len(top[t]) for t in ("income", "expense", "owner", "held")] == [5, 30, 2, 1]
    assert [len(by_type[t]) for t in ("income", "expense", "owner", "held")] == [8, 81, 3, 1]
    assert top["income"][0] == "Client fees" and top["expense"][4] == "Contract labor"
    assert top["owner"] == ["Owner contribution", "Owner draw"]
    travel = next(row for row in rows if row["name"] == "Repairs")
    # Rename, a CPA code, a new one, and the order.
    assert patch(api, ff, f"{C}{travel['id']}/", {"name": "Repairs and upkeep",
                                                  "cpa_code": "24a"}).json()["cpa_code"] == "24a"
    made = post(api, ff, C, {"name": "Conferences", "type": "expense"})
    assert made.status_code == 201 and made.json()["position"] == 30
    assert post(api, ff, C, {"name": "conferences", "type": "expense"}).status_code == 409
    assert post(api, ff, C, {"name": " ", "type": "expense"}).status_code == 400
    assert post(api, ff, C, {"name": "Odd", "type": "asset"}).status_code == 400
    owner = [row["id"] for row in rows if row["type"] == "owner" and not row["parent"]]
    reordered = post(api, ff, C + "reorder/", {"type": "owner", "ids": owner[::-1]}).json()
    assert [row["name"] for row in reordered
            if row["type"] == "owner" and not row["parent"]] == [
        "Owner draw", "Owner contribution"]
    assert post(api, ff, C + "reorder/", {"type": "owner", "ids": owner[:1]}).status_code == 400
    # The chart is put there once: archiving every category does not bring it back.
    with tenant_context(seeded_tenant.pk):
        FinanceCategory.objects.update(archived_at=timezone.now())
    assert all(row["archived"] for row in get(api, ff, C).json())
    assert len(get(api, ff, C).json()) == 94


@pytest.mark.django_db
def test_a_used_category_keeps_its_type_and_is_archived_not_deleted(books, ff, api):
    # "Meals": a category with no sub-categories, as every one was before P6 M1.
    meals = books["cat"]["Meals"]
    entry = add(api, ff, books, "expense", 12500, "2026-10-01", "Meals").json()
    assert patch(api, ff, f"{C}{meals['id']}/", {"type": "income"}).status_code == 409
    gone = patch(api, ff, f"{C}{meals['id']}/", {"archived": True})
    assert gone.status_code == 200 and gone.json()["archived"] is True
    # Its entries keep it; new ones cannot take it.
    assert get(api, ff, E).json()["entries"][0]["category"]["name"] == "Meals"
    assert add(api, ff, books, "expense", 100, "2026-10-02", "Meals").status_code == 400
    assert patch(api, ff, f"{E}{entry['id']}/", {"description": "Still fine"}
                 ).status_code == 200
    # The two this module relies on stay.
    assert patch(api, ff, f"{C}{books['cat']['Client fees']['id']}/",
                 {"archived": True}).status_code == 409
    assert patch(api, ff, f"{C}{books['cat']['Sales tax collected']['id']}/",
                 {"archived": True}).status_code == 409
    # Unless paid invoices are pointed somewhere else first.
    assert post(api, ff, "/api/finance-settings/", {
        "invoice_income_category": books["cat"]["Other income"]["id"]}).status_code == 200
    # ... and (P6 M1) its sub-categories are archived first.
    assert patch(api, ff, f"{C}{books['cat']['Client fees']['id']}/",
                 {"archived": True}).status_code == 409
    # Recurring invoices go to Retainers and one-off ones to Project fees, so
    # those stay too until the owner sends each kind somewhere else.
    for sub, field in (("Retainers", "recurring_income_category"),
                       ("Project fees", "one_off_income_category")):
        held = patch(api, ff, f"{C}{books['cat'][sub]['id']}/", {"archived": True})
        assert held.status_code == 409 and "Paid invoices go to" in held.json()["detail"]
        assert post(api, ff, "/api/finance-settings/", {field: ""}).json()[field] == ""
    for sub in ("Retainers", "Project fees", "Workshops and speaking"):
        assert patch(api, ff, f"{C}{books['cat'][sub]['id']}/",
                     {"archived": True}).status_code == 200
    assert patch(api, ff, f"{C}{books['cat']['Client fees']['id']}/",
                 {"archived": True}).status_code == 200
    assert post(api, ff, "/api/finance-settings/", {
        "invoice_income_category": books["cat"]["Travel"]["id"]}).status_code == 400


@pytest.mark.django_db
def test_accounts_are_named_once_closed_not_deleted_and_keep_their_kind(books, ff, api):
    assert post(api, ff, A, {"name": "checking"}).status_code == 409
    for bad in ({"name": ""}, {"name": "X", "kind": "loan"}, {"name": "X", "last4": "12"},
                {"name": "X", "opening_balance_cents": 10.5},
                {"name": "X", "opening_on": "January"}):
        assert post(api, ff, A, bad).status_code == 400, bad
    add(api, ff, books, "expense", 12500, "2026-10-01", "Travel")
    bank = f"{A}{books['bank']['id']}/"
    assert patch(api, ff, bank, {"kind": "card"}).status_code == 409
    closed = patch(api, ff, bank, {"closed": True}).json()
    assert closed["closed"] is True
    assert add(api, ff, books, "expense", 100, "2026-10-02", "Travel").status_code == 400
    assert patch(api, ff, bank, {"closed": False}).json()["closed"] is False


# ==================================================================== entries

@pytest.mark.django_db
def test_an_entry_is_held_to_what_its_kind_means(books, ff, api):
    ok = add(api, ff, books, "income", 250000, "2026-10-02", "Project fees",
             description="  Strategy   workshop ", counterparty="Acme")
    assert ok.status_code == 201
    made = ok.json()
    assert (made["direction"], made["description"], made["source"]) == (
        "in", "Strategy workshop", "manual")
    assert add(api, ff, books, "expense", 4500, "2026-10-02", "Meals",
               account="card").json()["direction"] == "out"
    draw = add(api, ff, books, "owner", 300000, "2026-10-03", "Owner draw", direction="out")
    assert draw.status_code == 201 and draw.json()["direction"] == "out"
    move = add(api, ff, books, "transfer", 50000, "2026-10-04",
               to_account=books["card"]["id"])
    assert move.status_code == 201 and move.json()["category"] is None
    refusals = [
        dict(kind="income", cents=100, category="Travel"),            # an expense category
        dict(kind="expense", cents=100, category="Client fees"),
        dict(kind="expense", cents=0, category="Travel"),
        dict(kind="expense", cents=-5, category="Travel"),
        dict(kind="expense", cents=19.99, category="Travel"),
        dict(kind="owner", cents=100, category="Owner draw"),          # which way?
        dict(kind="owner", cents=100, direction="out"),                # no category
        dict(kind="transfer", cents=100),                              # to where?
        dict(kind="transfer", cents=100, to_account=books["bank"]["id"]),   # to itself
        dict(kind="transfer", cents=100, to_account=books["card"]["id"],
             category="Travel"),
        dict(kind="expense", cents=100, category="Travel", to_account=books["card"]["id"]),
        dict(kind="expense", cents=100, category="Travel", account=None),
        dict(kind="barter", cents=100, category="Travel"),
    ]
    for case in refusals:
        cents, category = case.pop("cents"), case.pop("category", None)
        kind = case.pop("kind")
        assert add(api, ff, books, kind, cents, "2026-10-05", category, **case
                   ).status_code == 400, (kind, cents, category, case)
    tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()
    assert add(api, ff, books, "expense", 100, tomorrow, "Travel").status_code == 400
    assert add(api, ff, books, "expense", 100, "soon", "Travel").status_code == 400
    assert get(api, ff, E).json()["count"] == 4


@pytest.mark.django_db
def test_changing_and_removing_an_entry_is_audited_with_before_and_after(books, ff, api):
    entry = add(api, ff, books, "expense", 12500, "2026-10-01", "Travel",
                description="Flight").json()
    one = f"{E}{entry['id']}/"
    changed = patch(api, ff, one, {"amount_cents": 13900, "category": books["cat"]["Meals"]["id"],
                                   "account": books["card"]["id"]}).json()
    assert (changed["amount_cents"], changed["category"]["name"],
            changed["account"]["name"]) == (13900, "Meals", "Business card")
    assert post(api, ff, one + "remove/", {"reason": " "}).status_code == 400
    gone = post(api, ff, one + "remove/", {"reason": "Entered twice"}).json()
    assert gone["removed"] and gone["remove_reason"] == "Entered twice"
    assert post(api, ff, one + "remove/", {"reason": "Again"}).status_code == 409
    assert patch(api, ff, one, {"description": "x"}).status_code == 409
    # Kept, and out of every figure.
    assert get(api, ff, E).json()["entries"] == []
    assert [row["id"] for row in get(api, ff, E + "?removed=1").json()["entries"]] == [
        entry["id"]]
    assert get(api, ff, R + "pnl/?year=2026").json()["expenses"]["total"] == 0
    history = get(api, ff, one + "history/").json()
    assert [row["what"] for row in history] == ["entry_added", "entry_changed",
                                                "entry_removed"]
    assert history[1]["before"]["amount_cents"] == 12500
    assert history[1]["after"]["amount_cents"] == 13900
    assert history[2]["reason"] == "Entered twice" and history[2]["by"]


@pytest.mark.django_db
def test_several_entries_are_recategorized_together_or_not_at_all(books, ff, api):
    one = add(api, ff, books, "expense", 1000, "2026-10-01", "Travel").json()
    two = add(api, ff, books, "expense", 2000, "2026-10-02", "Travel").json()
    income = add(api, ff, books, "income", 5000, "2026-10-02", "Client fees").json()
    refused = post(api, ff, E + "recategorize/", {
        "entries": [one["id"], income["id"]], "category": books["cat"]["Meals"]["id"]})
    assert refused.status_code == 400
    assert {row["category"]["name"] for row in get(api, ff, E).json()["entries"]} == {
        "Travel", "Client fees"}, "one that cannot take it refuses the lot"
    done = post(api, ff, E + "recategorize/", {
        "entries": [one["id"], two["id"]], "category": books["cat"]["Meals"]["id"]})
    assert done.status_code == 200 and done.json() == {"changed": 2}
    assert post(api, ff, E + "recategorize/", {"entries": [], "category": "x"}
                ).status_code == 400
    assert post(api, ff, E + "recategorize/", {
        "entries": ["00000000-0000-4000-8000-000000000000"],
        "category": books["cat"]["Meals"]["id"]}).status_code == 404


@pytest.mark.django_db
def test_the_list_filters_searches_and_totals_what_is_listed(books, ff, api):
    add(api, ff, books, "income", 500000, "2026-09-15", "Client fees", counterparty="Acme")
    add(api, ff, books, "expense", 12500, "2026-10-01", "Travel", description="Flight to DEN")
    add(api, ff, books, "expense", 4500, "2026-10-02", "Meals", account="card")
    add(api, ff, books, "transfer", 50000, "2026-10-03", to_account=books["card"]["id"])
    everything = get(api, ff, E).json()
    assert everything["count"] == 4
    assert everything["totals"] == {"income_cents": 500000, "expenses_cents": 17000,
                                    "net_cents": 483000}, "a transfer is in neither"
    q = lambda query: get(api, ff, E + query).json()  # noqa: E731
    assert q("?from=2026-10-01&to=2026-10-02")["count"] == 2
    assert q("?kind=expense")["totals"]["expenses_cents"] == 17000
    assert q(f"?category={books['cat']['Travel']['id']}")["count"] == 1
    assert q(f"?account={books['card']['id']}")["count"] == 2, "either side of a transfer"
    assert q("?q=den")["entries"][0]["description"] == "Flight to DEN"
    assert q("?q=acme")["count"] == 1 and q("?source=invoice")["count"] == 0
    assert get(api, ff, E + "?from=yesterday").status_code == 400


# ==================================================================== the lock

@pytest.mark.django_db
def test_nothing_in_a_locked_period_is_added_changed_or_removed(books, ff, api):
    old = add(api, ff, books, "expense", 12500, "2026-09-10", "Travel").json()
    new = add(api, ff, books, "expense", 4500, "2026-10-02", "Meals").json()
    locked = post(api, ff, "/api/finance-settings/", {"locked_through": "2026-09-30"})
    assert locked.status_code == 200
    before = snapshot(books["tenant"])
    refusals = [
        add(api, ff, books, "expense", 100, "2026-09-30", "Travel"),
        patch(api, ff, f"{E}{old['id']}/", {"amount_cents": 1}),
        post(api, ff, f"{E}{old['id']}/remove/", {"reason": "x"}),
        patch(api, ff, f"{E}{new['id']}/", {"on_date": "2026-09-29"}),   # moved into it
        post(api, ff, E + "recategorize/", {"entries": [old["id"], new["id"]],
                                            "category": books["cat"]["Insurance"]["id"]}),
    ]
    for response in refusals:
        assert response.status_code == 409 and "locked through September 30, 2026" in \
            response.json()["detail"]
    assert snapshot(books["tenant"]) == before
    # The day after is open, and moving the lock back opens the rest. Audited.
    assert add(api, ff, books, "expense", 100, "2026-10-01", "Travel").status_code == 201
    assert post(api, ff, "/api/finance-settings/", {"locked_through": None}).status_code == 200
    assert patch(api, ff, f"{E}{old['id']}/", {"amount_cents": 1}).status_code == 200
    with tenant_context(books["tenant"].pk):
        changes = AuditEvent.objects.filter(verb="finance.settings_changed").order_by(
            "created_at")
        assert [e.payload["after"]["locked_through"] for e in changes] == ["2026-09-30", None]
    ahead = (timezone.localdate() + timedelta(days=3)).isoformat()
    assert post(api, ff, "/api/finance-settings/", {"locked_through": ahead}).status_code == 400


# ==================================================== paid invoices are income

@pytest.mark.django_db
def test_a_payment_on_an_invoice_is_income_and_a_removed_one_is_not(acme, ff, api):
    invoice = sent(api, ff, *acme)
    assert get(api, ff, E).json()["entries"] == [], "nothing is income before it is paid"
    one = f"/api/invoices/{invoice['id']}/"
    post(api, ff, one + "payments/", {"amount_cents": 200000, "paid_on": "2026-10-03",
                                      "reference": "CHK 2231"})
    listed = get(api, ff, E).json()
    assert listed["totals"]["income_cents"] == 200000
    entry = listed["entries"][0]
    assert (entry["kind"], entry["on_date"], entry["amount_cents"], entry["source"]) == (
        "income", "2026-10-03", 200000, "invoice")
    assert entry["category"]["name"] == "Project fees", "a one-off invoice"
    assert entry["client_company"]["name"] == "Acme Facilities"
    assert entry["description"] == "Invoice INV-0001" and entry["reference"] == "CHK 2231"
    assert entry["invoice"] == {"id": invoice["id"], "number": "INV-0001"}
    assert entry["account"] is None, "not yet placed in a bank account"
    paid = post(api, ff, one + "payments/", {"amount_cents": TOTAL - 200000,
                                             "paid_on": "2026-10-05"}).json()
    assert paid["status"] == "paid"
    assert get(api, ff, E).json()["totals"]["income_cents"] == TOTAL
    # Its amount, date and client are the payment's; its category and account are yours.
    mine = f"{E}{entry['id']}/"
    for fixed in ({"amount_cents": 1}, {"on_date": "2026-10-01"}, {"kind": "expense"}):
        refused = patch(api, ff, mine, fixed)
        assert refused.status_code == 409 and "on the invoice" in refused.json()["detail"]
    assert post(api, ff, mine + "remove/", {"reason": "x"}).status_code == 409
    with tenant_context(acme[0].tenant_id):
        bank = services.save_account(acme[0].tenant, actor=ff.user, name="Checking")
    placed = patch(api, ff, mine, {"account": str(bank.pk), "description": "Acme, October"})
    assert placed.status_code == 200 and placed.json()["account"]["name"] == "Checking"
    # Removing the payment on the invoice takes its entry with it, with the reason.
    payment = paid["payments"][1]["id"]
    post(api, ff, one + "remove-payment/", {"payment": payment, "reason": "Bounced"})
    assert get(api, ff, E).json()["totals"]["income_cents"] == 200000
    removed = get(api, ff, E + "?removed=1").json()["entries"]
    assert [row["remove_reason"] for row in removed if row["removed"]] == ["Bounced"]


@pytest.mark.django_db
def test_sales_tax_on_a_paid_invoice_is_held_and_the_pieces_add_up(acme, ff, api):
    # $6,800.00 of fees and $333.33 of tax, paid in three uneven parts.
    invoice = sent(api, ff, *acme, tax_cents=33333)
    one = f"/api/invoices/{invoice['id']}/payments/"
    for cents, day in ((100000, "03"), (233333, "04"), (TOTAL + 33333 - 333333, "05")):
        assert post(api, ff, one, {"amount_cents": cents, "paid_on": f"2026-10-{day}"}
                    ).status_code == 200
    entries = get(api, ff, E).json()["entries"]
    income = sum(row["amount_cents"] for row in entries if row["kind"] == "income")
    held = sum(row["amount_cents"] for row in entries if row["kind"] == "held")
    assert (income, held) == (TOTAL, 33333), "to the cent, however the parts fell"
    assert {row["category"]["name"] for row in entries if row["kind"] == "held"} == {
        "Sales tax collected"}
    # Held, not earned: out of the P&L, on the balance view.
    assert get(api, ff, R + "pnl/?year=2026").json()["income"]["total"] == TOTAL
    balance = get(api, ff, R + "balance/?as_of=2026-10-31").json()
    assert balance["tax_held_cents"] == 33333
    assert balance["unplaced_cents"] == TOTAL + 33333
    # Each payment's two entries go together when it is removed.
    paid = get(api, ff, f"/api/invoices/{invoice['id']}/").json()
    post(api, ff, f"/api/invoices/{invoice['id']}/remove-payment/",
         {"payment": paid["payments"][0]["id"], "reason": "Reversed"})
    left = get(api, ff, E).json()["entries"]
    assert sum(row["amount_cents"] for row in left) == TOTAL + 33333 - 100000


@pytest.mark.django_db
def test_a_payment_dated_in_a_locked_period_is_refused_on_the_invoice(acme, ff, api):
    invoice = sent(api, ff, *acme, issue_date="2026-09-01", due_date="2026-09-16")
    post(api, ff, "/api/finance-settings/", {"locked_through": "2026-09-30"})
    refused = post(api, ff, f"/api/invoices/{invoice['id']}/payments/",
                   {"amount_cents": TOTAL, "paid_on": "2026-09-20"})
    assert refused.status_code == 409 and "locked through" in refused.json()["detail"]
    # And the payment was not recorded either: the two are one transaction.
    after = get(api, ff, f"/api/invoices/{invoice['id']}/").json()
    assert after["status"] == "sent" and after["payments"] == []
    assert get(api, ff, E).json()["entries"] == []


@pytest.mark.django_db
def test_payments_recorded_before_the_books_are_backfilled_once(acme, ff, api):
    from django.core.management import call_command

    invoice = sent(api, ff, *acme)
    post(api, ff, f"/api/invoices/{invoice['id']}/payments/",
         {"amount_cents": 200000, "paid_on": "2026-10-03"})
    with tenant_context(acme[0].tenant_id):
        FinanceEntry.objects.all().delete()          # as if the books came later
        assert services.backfill_payments(acme[0].tenant, apply=False) == 1
        assert not FinanceEntry.objects.exists(), "the dry run writes nothing"
    out = io.StringIO()
    call_command("backfill_invoice_income", stdout=out)
    assert "Would write entries for 1 payment(s). Nothing was written." in out.getvalue()
    call_command("backfill_invoice_income", "--apply", stdout=io.StringIO())
    call_command("backfill_invoice_income", "--apply", stdout=io.StringIO())
    listed = get(api, ff, E).json()
    assert listed["count"] == 1 and listed["totals"]["income_cents"] == 200000


# ======================================================================= P&L

@pytest.fixture
def a_year(books, ff, api):
    rows = [
        ("income", 500000, "2026-01-31", "Client fees"),      # the last day of a month
        ("income", 500000, "2026-02-01", "Client fees"),
        ("income", 250000, "2026-03-15", "Project fees"),
        ("income", 800000, "2026-07-01", "Client fees"),
        ("expense", 12500, "2026-01-10", "Travel"),
        ("expense", 4599, "2026-03-31", "Meals"),
        ("expense", 30000, "2026-04-01", "Software and subscriptions"),
        ("expense", 99999, "2026-12-31", "Insurance"),
        ("expense", 77700, "2025-12-31", "Travel"),            # another year
    ]
    for kind, cents, on, category in rows:
        if date.fromisoformat(on) <= timezone.localdate():
            assert add(api, ff, books, kind, cents, on, category).status_code == 201
        else:
            # Dated ahead of today: straight in, as an import of a statement would be.
            with tenant_context(books["tenant"].pk):
                FinanceEntry.objects.create(
                    tenant=books["tenant"], kind=kind, direction="out", amount_cents=cents,
                    on_date=on, account_id=books["bank"]["id"],
                    category_id=books["cat"][category]["id"])
    add(api, ff, books, "transfer", 50000, "2026-03-01", to_account=books["card"]["id"])
    add(api, ff, books, "owner", 300000, "2026-03-02", "Owner draw", direction="out")
    return books


@pytest.mark.django_db
def test_the_pnl_by_month_adds_up_and_leaves_out_what_is_not_earned(a_year, ff, api):
    report = get(api, ff, R + "pnl/?year=2026").json()
    assert report["periods"][0] == "January" and len(report["periods"]) == 12
    income, expenses = report["income"], report["expenses"]
    assert income["totals"][:3] == [500000, 500000, 250000] and income["total"] == 2050000
    assert expenses["totals"][0] == 12500 and expenses["totals"][2] == 4599
    assert expenses["totals"][11] == 99999 and expenses["total"] == 147098
    assert report["net"] == [i - e for i, e in zip(income["totals"], expenses["totals"])]
    assert report["net_total"] == 2050000 - 147098 == sum(report["net"])
    for section in (income, expenses):
        for row in section["rows"]:
            assert row["total"] == sum(row["amounts"])
        assert section["totals"] == [sum(row["amounts"][i] for row in section["rows"])
                                     for i in range(12)]
    # The transfer and the owner's draw are in no figure; last year is last year's.
    names = [row["name"] for row in income["rows"] + expenses["rows"]]
    assert "Owner draw" not in names and "Sales tax collected" not in names
    assert get(api, ff, R + "pnl/?year=2025").json()["expenses"]["total"] == 77700
    assert report["years"] == [2026, 2025]


@pytest.mark.django_db
def test_the_quarters_are_the_sums_of_their_months_and_the_year_of_its_quarters(a_year, ff,
                                                                              api):
    months = get(api, ff, R + "pnl/?year=2026").json()
    quarters = get(api, ff, R + "pnl/?year=2026&by=quarter").json()
    assert quarters["periods"] == ["Q1", "Q2", "Q3", "Q4"]
    for name in ("income", "expenses"):
        by_month = months[name]["totals"]
        assert quarters[name]["totals"] == [sum(by_month[q * 3:q * 3 + 3]) for q in range(4)]
        assert quarters[name]["total"] == months[name]["total"] == sum(
            quarters[name]["totals"])
    assert quarters["net"] == [sum(months["net"][q * 3:q * 3 + 3]) for q in range(4)]
    assert quarters["net_total"] == months["net_total"]
    assert get(api, ff, R + "pnl/?year=nineteen").status_code == 400
    assert get(api, ff, R + "pnl/?year=1850").status_code == 400


@pytest.mark.django_db
def test_entries_with_no_category_are_named_beside_the_pnl_never_dropped(books, ff, api):
    add(api, ff, books, "expense", 12500, "2026-10-01", "Travel")
    assert add(api, ff, books, "expense", 231044, "2026-10-02").status_code == 201
    assert add(api, ff, books, "income", 5000, "2026-10-02").status_code == 201
    report = get(api, ff, R + "pnl/?year=2026").json()
    assert report["uncategorized"] == {"count": 2, "amount_cents": 236044}
    assert report["expenses"]["total"] == 12500 and report["income"]["total"] == 0
    assert get(api, ff, E + "?category=none").json()["count"] == 2
    text = get(api, ff, R + "pnl/?year=2026&download=1").content.decode()
    assert "2 entries with no category are not in these figures: 2360.44" in text
    assert "Travel,,0.00" in text and "Net," in text


# ============================================================ the balance view

@pytest.mark.django_db
def test_the_balance_view_is_cash_less_what_is_owed(books, ff, api, acme):
    add(api, ff, books, "income", 500000, "2026-02-01", "Client fees")
    add(api, ff, books, "expense", 12500, "2026-02-10", "Travel")
    add(api, ff, books, "expense", 4500, "2026-02-11", "Meals", account="card")
    add(api, ff, books, "owner", 300000, "2026-02-12", "Owner draw", direction="out")
    add(api, ff, books, "owner", 20000, "2026-02-13", "Owner contribution", direction="in")
    view = get(api, ff, R + "balance/?as_of=2026-02-28").json()
    assert [row["amount_cents"] for row in view["cash"]] == [
        1000000 + 500000 - 12500 - 300000 + 20000]
    assert [row["amount_cents"] for row in view["cards"]] == [50000 + 4500]
    net = view["net_cents"]
    assert net == view["cash_total_cents"] - view["owed_total_cents"] == 1207500 - 54500
    # Paying the card from the bank moves money and changes nothing overall.
    add(api, ff, books, "transfer", 54500, "2026-02-20", to_account=books["card"]["id"])
    after = get(api, ff, R + "balance/?as_of=2026-02-28").json()
    assert after["cash"][0]["amount_cents"] == 1207500 - 54500
    assert after["cards"][0]["amount_cents"] == 0 and after["net_cents"] == net
    # As of an earlier day, later entries are not in it.
    assert get(api, ff, R + "balance/?as_of=2026-02-09").json()["cash"][0][
        "amount_cents"] == 1500000
    # Before an account's opening date it is not listed; an entry dated before
    # the opening balance is already inside it.
    assert get(api, ff, R + "balance/?as_of=2025-12-31").json()["cash"] == []
    add(api, ff, books, "expense", 99900, "2025-12-15", "Travel")
    assert get(api, ff, R + "balance/?as_of=2026-02-28").json()["cash"][0][
        "amount_cents"] == 1207500 - 54500
    assert get(api, ff, R + "balance/?as_of=someday").status_code == 400


@pytest.mark.django_db
def test_what_clients_owe_is_beside_the_balance_view_and_not_in_it(acme, ff, api):
    invoice = sent(api, ff, *acme)
    view = get(api, ff, R + "balance/").json()
    assert view["owed_to_you_cents"] == TOTAL
    assert view["net_cents"] == 0 and view["cash_total_cents"] == 0
    assert get(api, ff, R + f"pnl/?year={timezone.localdate().year}").json()[
        "income"]["total"] == 0
    post(api, ff, f"/api/invoices/{invoice['id']}/payments/",
         {"amount_cents": 200000, "paid_on": timezone.localdate().isoformat()})
    view = get(api, ff, R + "balance/").json()
    # Received, not yet placed in an account: counted once, and no longer owed.
    assert (view["unplaced_cents"], view["unplaced_count"]) == (200000, 1)
    assert view["cash_total_cents"] == 200000 == view["net_cents"]
    assert view["owed_to_you_cents"] == TOTAL - 200000


# =============================================================== the dashboard

@pytest.mark.django_db
def test_the_dashboard_shows_the_owner_this_months_revenue_expenses_and_margin(books, ff,
                                                                              api):
    today = timezone.localdate()
    first = today.replace(day=1)
    assert get(api, ff, "/api/dashboard/").json()["finance"]["margin_percent"] is None
    add(api, ff, books, "income", 800000, first.isoformat(), "Client fees")
    add(api, ff, books, "expense", 200000, first.isoformat(), "Contractors and associates")
    add(api, ff, books, "transfer", 50000, first.isoformat(),
        to_account=books["card"]["id"])
    add(api, ff, books, "income", 999999, (first - timedelta(days=1)).isoformat(),
        "Client fees")                                      # last month
    finance = get(api, ff, "/api/dashboard/").json()["finance"]
    assert (finance["revenue_cents"], finance["expenses_cents"], finance["net_cents"]) == (
        800000, 200000, 600000)
    assert finance["margin_percent"] == 75.0
    assert finance["year"] == today.year
    with tenant_context(books["tenant"].pk):
        assert reports.this_month(books["tenant"], today)["margin_percent"] == 75.0


# ============================================================== the CPA export

@pytest.mark.django_db
def test_the_cpa_export_is_two_files_that_agree_and_each_download_is_audited(a_year, ff, api,
                                                                            acme):
    patch(api, ff, f"{C}{a_year['cat']['Travel']['id']}/", {"cpa_code": "24a"})
    removed = add(api, ff, a_year, "expense", 55555, "2026-05-05", "Travel").json()
    post(api, ff, f"{E}{removed['id']}/remove/", {"reason": "Not ours"})
    add(api, ff, a_year, "expense", 1234, "2026-06-01")                   # no category yet
    span = "?from=2026-01-01&to=2026-06-30"
    entries = get(api, ff, R + "export-entries/" + span)
    assert entries["Content-Type"].startswith("text/csv")
    assert 'filename="entries-2026-01-01-to-2026-06-30.csv"' in entries["Content-Disposition"]
    rows = list(csv.DictReader(io.StringIO(entries.content.decode())))
    assert rows[0]["Date"] == "2026-01-10" and rows[-1]["Date"] == "2026-06-01"
    assert all("2026-01-01" <= row["Date"] <= "2026-06-30" for row in rows)
    assert "555.55" not in entries.content.decode(), "a removed entry is left out"
    travel = next(row for row in rows if row["Category"] == "Travel")
    assert (travel["CPA code"], travel["Money out"], travel["Money in"],
            travel["Account"], travel["Source"]) == ("24a", "125.00", "", "Checking",
                                                     "Typed in")
    assert rows[-1]["Category"] == "(no category yet)"
    transfer = next(row for row in rows if row["Kind"] == "Transfer")
    assert (transfer["To account"], transfer["Category"]) == ("Business card", "")

    summary = get(api, ff, R + "export-summary/" + span).content.decode()
    lines = list(csv.reader(io.StringIO(summary)))
    total = {line[1]: line[4] for line in lines[2:]}      # after "Parent category"
    cents = lambda text: round(float(text) * 100)  # noqa: E731
    money_in = sum(cents(row["Money in"]) for row in rows if row["Kind"] == "Income")
    money_out = sum(cents(row["Money out"]) for row in rows if row["Kind"] == "Expense")
    assert cents(total["Total income"]) == money_in == 1250000
    assert cents(total["Total expenses"]) == money_out == 12500 + 4599 + 30000 + 1234
    assert cents(total["Net"]) == money_in - money_out
    assert total["Travel"] == "125.00" and total["(no category yet)"] == "12.34"
    assert ["Expense", "Travel", "", "24a", "125.00"] in lines
    # The dates are inclusive, and the wrong way round is refused.
    one_day = get(api, ff, R + "export-entries/?from=2026-01-31&to=2026-01-31")
    assert len(list(csv.DictReader(io.StringIO(one_day.content.decode())))) == 1
    assert get(api, ff, R + "export-entries/?from=2026-06-30&to=2026-01-01"
               ).status_code == 400
    with tenant_context(a_year["tenant"].pk):
        events = AuditEvent.objects.filter(verb="finance.cpa_export_downloaded")
        assert events.count() == 3
        assert {e.payload["file"] for e in events} == {"entries", "summary"}
        assert events.first().actor_id == ff.user.pk


@pytest.mark.django_db
def test_an_invoice_payment_carries_its_invoice_number_into_the_export(acme, ff, api):
    invoice = sent(api, ff, *acme)
    post(api, ff, f"/api/invoices/{invoice['id']}/payments/",
         {"amount_cents": TOTAL, "paid_on": "2026-10-03"})
    text = get(api, ff, R + "export-entries/?from=2026-10-01&to=2026-10-31").content.decode()
    row = next(csv.DictReader(io.StringIO(text)))
    assert (row["Invoice"], row["Client company"], row["Money in"], row["Source"]) == (
        "INV-0001", "Acme Facilities", "6800.00", "From an invoice payment")


@pytest.mark.django_db
def test_removing_a_payment_follows_billing_into_a_voidable_invoice(acme, ff, api):
    """The hook leaves nothing behind that would block invoicing's own rules."""
    invoice = sent(api, ff, *acme)
    one = f"/api/invoices/{invoice['id']}/"
    paid = post(api, ff, one + "payments/", {"amount_cents": 100000,
                                             "paid_on": "2026-10-03"}).json()
    post(api, ff, one + "remove-payment/", {"payment": paid["payments"][0]["id"],
                                            "reason": "Wrong invoice"})
    assert post(api, ff, one + "void/", {"reason": "Duplicate"}).json()["status"] == "void"
    assert get(api, ff, E).json()["entries"] == []
    with tenant_context(acme[0].tenant_id):
        assert billing.totals(__import__("apps.billing.models", fromlist=["x"])
                              .ClientInvoice.objects.all())["invoiced_cents"] == 0


# ======================== the CPA's worksheet (owner, 2026-10-10)

def _sheet(api, ff, year=2026):
    response = get(api, ff, R + f"export-worksheet/?year={year}")
    assert response.status_code == 200
    assert f'filename="cpa-worksheet-{year}.csv"' in response["Content-Disposition"]
    return list(csv.reader(io.StringIO(response.content.decode())))


@pytest.fixture
def cpa_books(seeded_tenant, ff, api):
    """A new practice, with the CPA's chart as it starts, and a bank account."""
    bank = post(api, ff, A, {"name": "Checking", "kind": "bank",
                             "opening_balance_cents": 1000000,
                             "opening_on": "2026-01-01"}).json()
    card = post(api, ff, A, {"name": "Card", "kind": "card",
                             "opening_on": "2026-01-01"}).json()
    return {"tenant": seeded_tenant, "bank": bank, "card": card,
            "cat": {row["name"]: row for row in get(api, ff, C).json()}}


@pytest.mark.django_db
def test_the_worksheet_lists_a_line_a_category_in_the_worksheets_order(cpa_books, ff, api):
    from apps.finance import chart

    b = cpa_books
    add(api, ff, b, "income", 500000, "2026-02-01", "Retainers")
    add(api, ff, b, "income", 20000, "2026-02-03", "Client fees")
    add(api, ff, b, "expense", 45000, "2026-02-05", "Bookkeeping")
    add(api, ff, b, "expense", 185000, "2026-03-18", "Tax preparation")
    add(api, ff, b, "expense", 30000, "2026-03-04", "Airfare")
    add(api, ff, b, "expense", 9000, "2026-03-04", "Travel: airfare, rental car, hotel")
    add(api, ff, b, "expense", 2000, "2026-03-04", "Airfare", direction="in")     # a refund
    add(api, ff, b, "expense", 12000, "2026-04-02", "Education and training")
    add(api, ff, b, "expense", 3500, "2026-04-09", "Business gifts")
    add(api, ff, b, "expense", 700, "2026-04-10", "Miscellaneous (itemized)")
    add(api, ff, b, "expense", 99900, "2026-05-01", "Wages")
    add(api, ff, b, "expense", 1234, "2026-05-02")                    # no category yet
    add(api, ff, b, "expense", 77700, "2025-12-31", "Supplies")       # another year
    add(api, ff, b, "transfer", 5000, "2026-05-03", to_account=b["card"]["id"])
    add(api, ff, b, "owner", 250000, "2026-05-28", "Draws", direction="out")

    rows = _sheet(api, ff)
    assert rows[0] == ["Business income and expense worksheet, 2026, cash basis"]
    start, stop = rows.index(["Expenses", "Amount", "Note"]), rows.index(
        ["Total expenses", "3843.34", ""])
    expenses = rows[start + 1:stop]
    # Every category of the chart, in the worksheet's order, whether or not
    # anything was spent; a category's figure is its own and its sub-categories'.
    tops = [row for row in expenses if not row[0].startswith("  ")
            and row[0] != "(no category yet)"]
    assert [row[0] for row in tops] == [name for name, _ in chart.STARTING_CHART[1][1]]
    by_name = {row[0]: row for row in expenses}
    assert by_name["Accounting"] == ["Accounting", "2300.00", ""]
    assert by_name["Travel: airfare, rental car, hotel"][1] == "370.00"
    assert by_name["Supplies"][1] == "0.00" and by_name["Uniforms"][1] == "0.00"
    assert "  Bookkeeping" not in by_name, "sub-categories are ours, not the worksheet's"
    # Miscellaneous is itemized: each sub-category on its own line, under it.
    at = expenses.index(["Miscellaneous (itemized)", "162.00", "Itemized below"])
    assert expenses[at + 1:at + 6] == [
        ["  Education and training", "120.00", ""], ["  Business gifts", "35.00", ""],
        ["  Taxes and licenses", "0.00", ""], ["  Other (itemize)", "0.00", ""],
        ["  Miscellaneous (itemized), not itemized", "7.00", ""]]
    # The one category that is not a line of the worksheet says so, and is last.
    assert tops[-1] == ["Wages and payroll taxes", "999.00", "Not a line of the worksheet"]
    assert by_name["(no category yet)"][1] == "12.34"
    income = rows[rows.index(["Income", "Amount", "Note"]) + 1:start - 1]
    assert income[0] == ["Client fees", "5200.00", ""]
    assert income[-1] == ["Total income", "5200.00", ""]
    assert ["Net", "1356.66", ""] in rows
    # It agrees with the P&L: the same entries, grouped the worksheet's way.
    report = get(api, ff, R + "pnl/?year=2026").json()
    assert (report["income"]["total"], report["expenses"]["total"]
            + report["uncategorized"]["amount_cents"]) == (520000, 384334)
    assert rows[-1] == [DISCLAIMER_TEXT]
    with tenant_context(b["tenant"].pk):
        event = AuditEvent.objects.filter(verb="finance.cpa_export_downloaded").last()
        assert event.payload == {"file": "worksheet", "year": 2026}
    for bad in ("x", "1999", "2999"):
        assert get(api, ff, R + f"export-worksheet/?year={bad}").status_code == 400


DISCLAIMER_TEXT = ("Bookkeeping and projections only, not tax, legal or financial advice. "
                   "Confirm with your CPA.")


@pytest.mark.django_db
def test_an_owner_draw_is_marked_an_estimated_tax_payment_and_listed_by_date(
        cpa_books, ff, api):
    b = cpa_books
    state = add(api, ff, b, "owner", 80000, "2026-06-15", "Owner draw",
                direction="out", estimated_tax="state")
    assert state.status_code == 201 and state.json()["estimated_tax"] == "state"
    fed = add(api, ff, b, "owner", 450000, "2026-04-15", "Owner draw",
              direction="out", estimated_tax="Federal").json()
    assert fed["estimated_tax"] == "federal"
    plain = add(api, ff, b, "owner", 300000, "2026-04-28", "Draws", direction="out").json()
    assert plain["estimated_tax"] == ""
    add(api, ff, b, "owner", 100000, "2025-09-15", "Owner draw",
        direction="out", estimated_tax="federal")                     # another year
    # It is the owner's own money going out, and nothing else.
    for body in (dict(kind="expense", category="Supplies"),
                 dict(kind="owner", category="Owner contribution", direction="in"),
                 dict(kind="income", category="Client fees")):
        kind, category = body.pop("kind"), body.pop("category")
        refused = add(api, ff, b, kind, 100, "2026-06-01", category,
                      estimated_tax="federal", **body)
        assert refused.status_code == 400 and "owner took out" in refused.json()["detail"]
    assert add(api, ff, b, "owner", 100, "2026-06-01", "Draws", direction="out",
               estimated_tax="city").status_code == 400
    # Marked and unmarked afterwards; a marked draw cannot turn into money in.
    marked = patch(api, ff, f"{E}{plain['id']}/", {"estimated_tax": "state"})
    assert marked.status_code == 200 and marked.json()["estimated_tax"] == "state"
    assert patch(api, ff, f"{E}{plain['id']}/", {"direction": "in"}).status_code == 400
    assert patch(api, ff, f"{E}{plain['id']}/", {"estimated_tax": ""}).json()[
        "estimated_tax"] == ""
    with tenant_context(b["tenant"].pk):
        changes = AuditEvent.objects.filter(verb="finance.entry_changed",
                                            target_id=plain["id"]).order_by("created_at")
        assert [e.payload["after"].get("estimated_tax", "") for e in changes] == ["state", ""]

    rows = _sheet(api, ff)
    at = rows.index(["Estimated tax payments", "Federal", "State"])
    assert rows[at + 1:at + 4] == [["2026-04-15", "4500.00", ""], ["2026-06-15", "", "800.00"],
                                   ["Total", "4500.00", "800.00"]]
    # Not an expense: it is in no expense line and not in the P&L.
    assert ["Total expenses", "0.00", ""] in rows
    assert get(api, ff, R + "pnl/?year=2026").json()["expenses"]["total"] == 0


@pytest.mark.django_db
def test_year_end_facts_are_kept_per_year_and_carried_onto_the_worksheet(cpa_books, ff, api):
    Y = "/api/finance-settings/year-facts/"
    blank = {"total_miles": None, "business_miles": None, "home_square_feet": None,
             "office_square_feet": None}
    assert get(api, ff, Y + "?year=2026").json() == {"year": 2026, **blank}
    saved = post(api, ff, Y, {"year": 2026, "total_miles": 14820, "business_miles": 6310,
                              "home_square_feet": 2400, "office_square_feet": 180})
    assert saved.status_code == 200
    assert saved.json() == {"year": 2026, "total_miles": 14820, "business_miles": 6310,
                            "home_square_feet": 2400, "office_square_feet": 180}
    # Per year, and one fact at a time; a null is "not said".
    assert get(api, ff, Y + "?year=2025").json() == {"year": 2025, **blank}
    post(api, ff, Y, {"year": 2025, "total_miles": 9000})
    assert post(api, ff, Y, {"year": 2026, "business_miles": None}).json()[
        "business_miles"] is None
    assert get(api, ff, Y + "?year=2026").json()["total_miles"] == 14820
    for body in ({"year": 2026, "business_miles": 20000},        # more than the total
                 {"year": 2026, "office_square_feet": 5000},     # larger than the home
                 {"year": 2026, "total_miles": -1}, {"year": 2026, "total_miles": "many"},
                 {"year": 2026, "total_miles": 1.5}, {"year": 1999, "total_miles": 1},
                 {"year": "2026", "total_miles": 1}, {"total_miles": 1}):
        assert post(api, ff, Y, body).status_code == 400, body
    assert get(api, ff, Y + "?year=nope").status_code == 400
    with tenant_context(cpa_books["tenant"].pk):
        assert AuditEvent.objects.filter(verb="finance.year_facts_changed").count() == 3

    rows = _sheet(api, ff)
    at = rows.index(["Year-end facts", "", ""])
    assert rows[at + 1:at + 5] == [
        ["Total miles driven", "14820", ""], ["Business miles", "", ""],
        ["Home square footage", "2400", ""], ["Office square footage", "180", ""]]
    assert _sheet(api, ff, 2025)[-6][:2] == ["Total miles driven", "9000"]


@pytest.mark.django_db
def test_tenant_isolation_and_role_boundaries_on_the_worksheet_and_year_facts(
        cpa_books, ff, cf, va, fcc, ecc, tenant_b, api):
    Y = "/api/finance-settings/year-facts/"
    add(api, ff, cpa_books, "expense", 4242400, "2026-03-04", "Supplies")
    add(api, ff, cpa_books, "owner", 5151500, "2026-04-15", "Owner draw",
        direction="out", estimated_tax="federal")
    post(api, ff, Y, {"year": 2026, "total_miles": 31313})
    calls = [("get", R + "export-worksheet/?year=2026", None), ("get", Y + "?year=2026", None),
             ("post", Y, {"year": 2026, "total_miles": 7})]
    before = snapshot(cpa_books["tenant"])
    for who, status in ((va, 403), (cf, 403), (fcc, 404), (ecc, 404)):
        for method, url, body in calls:
            response = call(api.as_(who), method, url, body)
            assert response.status_code == status, (who.role, url)
            for secret in (b"42424", b"51515", b"31313"):
                assert secret not in response.content
    # Another practice's worksheet and facts are its own: none of ours in them.
    other = _member(tenant_b, "FF")
    theirs = get(api, other, R + "export-worksheet/?year=2026").content.decode()
    assert "42424.00" not in theirs and "51515.00" not in theirs and "31313" not in theirs
    assert get(api, other, Y + "?year=2026").json()["total_miles"] is None
    post(api, other, Y, {"year": 2026, "total_miles": 5})
    assert get(api, ff, Y + "?year=2026").json()["total_miles"] == 31313
    owner = _member(cpa_books["tenant"], "FF")
    owner.user.is_platform_owner = True
    owner.user.save()
    client = in_practices_area(api.as_(owner))
    for method, url, body in calls:
        assert call(client, method, url, body).status_code in (403, 404)
    with tenant_context(tenant_b.pk):
        AuditEvent.objects.all().delete()
    assert json.loads(snapshot(cpa_books["tenant"]))["entries"] == \
        json.loads(before)["entries"]


def test_the_note_above_the_chart_is_the_same_words_in_both_places():
    import re
    from pathlib import Path

    from apps.finance import chart

    source = (Path(__file__).resolve().parent.parent
              / "frontend/src/lib/finance.ts").read_text()
    found = re.search(r'CHART_NOTE\s*=\s*\n?\s*"([^"]+)"', source)
    assert found and found.group(1) == chart.NOTE
    assert "“Wages and payroll taxes” is the one that is not on the worksheet" in chart.NOTE


# ============ an estimated tax payment is a mark, not a category (2026-10-10)

@pytest.mark.django_db
def test_the_migration_moves_entries_off_the_sub_category_marks_them_and_lists_the_rest(
        books, ff, tenant_b, api, capsys):
    """`books` has the chart as it was, with "Estimated tax payments" under
    Owner draw; `tenant_b` starts with the chart as it is now."""
    from importlib import import_module

    from django.apps import apps as django_apps

    from apps.finance.models import FinanceCategoryChange, FinanceRule

    step = import_module("apps.finance.migrations.0006_estimated_tax_is_a_mark")
    sub, parent = books["cat"]["Estimated tax payments"], books["cat"]["Owner draw"]

    def draw(cents, on, description, **more):
        made = add(api, ff, books, "owner", cents, on, "Estimated tax payments",
                   description=description, **{"direction": "out", **more})
        assert made.status_code == 201, made.content
        return made.json()["id"]

    federal = draw(450000, "2026-04-15", "Q1 estimate, Federal (IRS)")
    state = draw(80000, "2026-04-15", "Colorado state estimated tax")
    unsaid = draw(120000, "2026-06-15", "Q2 estimate")
    both = draw(90000, "2026-09-15", "Federal and state together")
    statement = draw(1000, "2026-09-16", "Bank statement fee on the estimate")
    back = draw(5000, "2026-09-20", "Federal refund of an overpayment", direction="in")
    already = draw(70000, "2026-01-15", "January payment", estimated_tax="state")
    gone = draw(300, "2026-02-01", "Entered twice")
    post(api, ff, f"{E}{gone}/remove/", {"reason": "Entered twice"})
    elsewhere = add(api, ff, books, "owner", 250000, "2026-04-28", "Draws",
                    direction="out", description="Federal holiday draw").json()["id"]
    with tenant_context(books["tenant"].pk):
        rule = FinanceRule.objects.create(tenant=books["tenant"], contains="USATAXPYMT",
                                          category_id=sub["id"])
        totals = reports.balance(books["tenant"], as_of=date(2026, 12, 31))
        chart_before = FinanceCategory.objects.count()
    capsys.readouterr()

    step.remove_the_sub_category(django_apps, None)

    printed = capsys.readouterr().out
    with tenant_context(books["tenant"].pk):
        assert not FinanceCategory.objects.filter(pk=sub["id"]).exists(), "it is deleted"
        assert FinanceCategory.objects.count() == chart_before - 1
        rows = {str(e.pk): e for e in FinanceEntry.objects.all()}
        on_it = [federal, state, unsaid, both, statement, back, already, gone]
        # Every one moved to the parent; nothing else about any entry changed.
        assert {str(rows[pk].category_id) for pk in on_it} == {parent["id"]}
        assert {pk: rows[pk].estimated_tax for pk in on_it} == {
            federal: "federal", state: "state", already: "state",
            unsaid: "", both: "", back: "", gone: "",
            # "statement" is not the word "state".
            statement: ""}
        assert rows[elsewhere].estimated_tax == "" and \
            rows[elsewhere].category.name == "Draws", "only what sat on the sub-category"
        assert rows[federal].amount_cents == 450000 and rows[gone].removed_at is not None
        assert FinanceRule.objects.get(pk=rule.pk).category_id == rows[federal].category_id
        assert reports.balance(books["tenant"], as_of=date(2026, 12, 31)) == totals
        # Listed: printed as it ran, and kept in the practice's own trail.
        event = AuditEvent.objects.get(verb="finance.estimated_tax_category_removed")
        assert event.payload["marked"] == {"federal": 1, "state": 2}
        assert event.payload["moved_to"] == "Owner draw"
        assert event.payload["category"] == "deleted"
        assert [(row["id"], row["description"]) for row in event.payload["unmarked"]] == [
            (unsaid, "Q2 estimate"), (both, "Federal and state together"),
            (statement, "Bank statement fee on the estimate"),
            (back, "Federal refund of an overpayment")], "not the removed one"
    assert "1 marked federal, 2 marked state, 4 left unmarked:" in printed
    assert "2026-06-15  1200.00 out  Q2 estimate" in printed
    # A practice on the chart as it is now has nothing to move, and nothing is said.
    with tenant_context(tenant_b.pk):
        assert not AuditEvent.objects.filter(
            verb="finance.estimated_tax_category_removed").exists()
    assert str(tenant_b.pk) not in printed
    # Run again, there is nothing left to do.
    step.remove_the_sub_category(django_apps, None)
    with tenant_context(books["tenant"].pk):
        assert AuditEvent.objects.filter(
            verb="finance.estimated_tax_category_removed").count() == 1
    # Where a combine or split on record still names it, it is archived instead.
    with tenant_context(books["tenant"].pk):
        again = FinanceCategory.objects.create(
            tenant=books["tenant"], name="Estimated tax payments", type="owner",
            parent_id=parent["id"])
        FinanceCategoryChange.objects.create(
            tenant=books["tenant"], kind="split", from_category_id=parent["id"],
            to_category=again, entries_moved=0)
    step.remove_the_sub_category(django_apps, None)
    with tenant_context(books["tenant"].pk):
        again.refresh_from_db()
        assert again.archived_at is not None


@pytest.mark.django_db
def test_the_owner_draws_list_filters_on_the_estimated_tax_mark(cpa_books, ff, api):
    b = cpa_books
    assert "Estimated tax payments" not in b["cat"], "the mark is the only way to record one"
    add(api, ff, b, "owner", 450000, "2026-04-15", "Owner draw", direction="out",
        estimated_tax="federal", description="Q1 federal")
    add(api, ff, b, "owner", 80000, "2026-04-15", "Draws", direction="out",
        estimated_tax="state", description="Q1 state")
    add(api, ff, b, "owner", 300000, "2026-04-28", "Draws", direction="out",
        description="April draw")
    add(api, ff, b, "expense", 100, "2026-04-02", "Supplies", description="Pens")

    def listed(query):
        response = get(api, ff, E + query)
        assert response.status_code == 200
        return sorted(row["description"] for row in response.json()["entries"])

    assert listed("?kind=owner") == ["April draw", "Q1 federal", "Q1 state"]
    assert listed("?estimated_tax=any") == ["Q1 federal", "Q1 state"]
    assert listed("?kind=owner&estimated_tax=federal") == ["Q1 federal"]
    assert listed("?estimated_tax=state") == ["Q1 state"]
    assert get(api, ff, E + "?estimated_tax=city").status_code == 400
    marks = {row["description"]: row["estimated_tax"]
             for row in get(api, ff, E).json()["entries"]}
    assert marks == {"Q1 federal": "federal", "Q1 state": "state", "April draw": "",
                     "Pens": ""}


# =========== invoice income goes to a sub-category, by the kind of invoice

def _income(api, ff):
    """{description of the entry: its category} for every invoice payment."""
    return {row["description"]: row["category"]["name"]
            for row in get(api, ff, E + "?source=invoice").json()["entries"]}


def _pay(api, ff, invoice, on="2026-10-05"):
    paid = post(api, ff, f"/api/invoices/{invoice['id']}/payments/",
                {"amount_cents": invoice["total_cents"], "paid_on": on})
    assert paid.status_code in (200, 201), paid.content
    return invoice["number"]


@pytest.mark.django_db
def test_invoice_payments_post_by_kind_recurring_to_retainers_one_off_to_project_fees(
        acme, ff, api):
    """Owner, 2026-10-10: every payment posted to the "Client fees" parent,
    so the P&L showed it all as "not broken down" and Retainers at nothing."""
    tenant = acme[0].tenant
    config = get(api, ff, "/api/finance-settings/").json()
    cats = {row["name"]: row for row in get(api, ff, C).json()}
    assert config["invoice_income_category"] == cats["Client fees"]["id"]
    assert config["recurring_income_category"] == cats["Retainers"]["id"]
    assert config["one_off_income_category"] == cats["Project fees"]["id"]

    one_off = _pay(api, ff, sent(api, ff, *acme))
    schedule = post(api, ff, "/api/invoice-schedules/", {
        "client_company": str(acme[0].pk), "contact": str(acme[1].pk),
        "day_of_month": 1, "starts_on": "2026-10-01", "lines": LINES})
    assert schedule.status_code == 201 and schedule.json()["income_category"] == ""
    with tenant_context(tenant.pk):
        [written] = billing.run_schedules(tenant, today=date(2026, 10, 1))
    assert written.kind == "recurring" and written.income_category_id is None
    for step in ("make-ready", "send"):
        assert post(api, ff, f"/api/invoices/{written.pk}/{step}/").status_code == 200
    recurring = _pay(api, ff, get(api, ff, f"/api/invoices/{written.pk}/").json())
    # To a contact who is not a client: any invoice that is not recurring.
    person = ContactFactory(tenant=tenant, first_name="Wes", last_name="Welton")
    ContactEmailFactory(tenant=tenant, contact=person, is_primary=True,
                        address="wes@welton.invalid")
    made = post(api, ff, "/api/invoices/", {"kind": "contact", "contact": str(person.pk),
                                            "lines": LINES}).json()
    for step in ("make-ready", "send"):
        assert post(api, ff, f"/api/invoices/{made['id']}/{step}/").status_code == 200
    to_contact = _pay(api, ff, get(api, ff, f"/api/invoices/{made['id']}/").json())

    assert _income(api, ff) == {f"Invoice {one_off}": "Project fees",
                                f"Invoice {recurring}": "Retainers",
                                f"Invoice {to_contact}": "Project fees"}
    # The P&L breaks it down: nothing is left on the parent.
    row = next(r for r in get(api, ff, R + "pnl/?year=2026").json()["income"]["rows"]
               if r["name"] == "Client fees")
    assert row["total"] == 3 * TOTAL
    assert {c["name"]: c["total"] for c in row["children"]} == {
        "Retainers": TOTAL, "Project fees": 2 * TOTAL, "Workshops and speaking": 0}
    assert not any(c.get("direct") for c in row["children"]), "none 'not broken down'"


@pytest.mark.django_db
def test_an_invoice_or_its_schedule_can_choose_another_income_category(acme, ff, api):
    tenant = acme[0].tenant
    cats = {row["name"]: row for row in get(api, ff, C).json()}
    workshops, other = cats["Workshops and speaking"]["id"], cats["Other income"]["id"]
    # A one-off invoice that names its own.
    made = draft(api, ff, *acme, income_category=workshops)
    assert made.status_code == 201 and made.json()["income_category"] == workshops
    changed = patch(api, ff, f"/api/invoices/{made.json()['id']}/",
                    {"income_category": other})
    assert changed.status_code == 200 and changed.json()["income_category"] == other
    for step in ("make-ready", "send"):
        assert post(api, ff, f"/api/invoices/{made.json()['id']}/{step}/").status_code == 200
    chosen = _pay(api, ff, get(api, ff, f"/api/invoices/{made.json()['id']}/").json())
    # A schedule that names its own: every draft it writes carries it.
    schedule = post(api, ff, "/api/invoice-schedules/", {
        "client_company": str(acme[0].pk), "contact": str(acme[1].pk), "day_of_month": 1,
        "starts_on": "2026-10-01", "lines": LINES, "income_category": workshops}).json()
    assert schedule["income_category"] == workshops
    with tenant_context(tenant.pk):
        [written] = billing.run_schedules(tenant, today=date(2026, 10, 1))
    assert str(written.income_category_id) == workshops
    for step in ("make-ready", "send"):
        assert post(api, ff, f"/api/invoices/{written.pk}/{step}/").status_code == 200
    scheduled = _pay(api, ff, get(api, ff, f"/api/invoices/{written.pk}/").json())
    assert _income(api, ff) == {f"Invoice {chosen}": "Other income",
                                f"Invoice {scheduled}": "Workshops and speaking"}
    # Back to the default for its kind; and what cannot be chosen.
    cleared = patch(api, ff, f"/api/invoice-schedules/{schedule['id']}/",
                    {"income_category": ""})
    assert cleared.status_code == 200 and cleared.json()["income_category"] == ""
    again = draft(api, ff, *acme).json()
    for bad, status in ((cats["Travel"]["id"] if "Travel" in cats else cats["Supplies"]["id"],
                         400),
                        ("00000000-0000-4000-8000-000000000000", 404), ("nope", 404)):
        refused = patch(api, ff, f"/api/invoices/{again['id']}/", {"income_category": bad})
        assert refused.status_code == status, bad
    patch(api, ff, f"{C}{cats['Workshops and speaking']['id']}/", {"archived": True})
    assert patch(api, ff, f"/api/invoices/{again['id']}/",
                 {"income_category": workshops}).status_code == 400, "archived"
    # Chosen on a draft only, like the rest of it; after that the entry itself
    # is what is changed, in the books.
    assert patch(api, ff, f"/api/invoices/{made.json()['id']}/",
                 {"income_category": ""}).status_code == 409


@pytest.mark.django_db
def test_where_each_kind_goes_is_the_owners_to_change_in_the_finance_settings(
        acme, ff, api):
    cats = {row["name"]: row for row in get(api, ff, C).json()}
    S_ = "/api/finance-settings/"
    moved = post(api, ff, S_, {"one_off_income_category": cats["Other income"]["id"]})
    assert moved.status_code == 200
    assert moved.json()["one_off_income_category"] == cats["Other income"]["id"]
    assert moved.json()["recurring_income_category"] == cats["Retainers"]["id"]
    first = _pay(api, ff, sent(api, ff, *acme))
    # "" is "as anything else": the general category.
    assert post(api, ff, S_, {"one_off_income_category": ""}).json()[
        "one_off_income_category"] == ""
    second = _pay(api, ff, sent(api, ff, *acme), on="2026-10-06")
    assert _income(api, ff) == {f"Invoice {first}": "Other income",
                                f"Invoice {second}": "Client fees"}
    expense = next(row for row in cats.values() if row["type"] == "expense")
    assert post(api, ff, S_, {"recurring_income_category": expense["id"]}).status_code == 400
    with tenant_context(acme[0].tenant.pk):
        # The first of the two changes, by when it was made, not by chance.
        event = AuditEvent.objects.filter(verb="finance.settings_changed").order_by(
            "created_at").first()
        assert event.payload["before"]["one_off_income_category"] == cats["Project fees"]["id"]
        assert event.payload["after"]["one_off_income_category"] == cats["Other income"]["id"]


@pytest.mark.django_db
def test_role_boundaries_and_isolation_on_an_invoices_income_category(
        acme, ff, cf, va, tenant_b, api):
    """The chart is the practice owner's alone: an associate bills their
    client and neither sees nor chooses where it goes in the books."""
    company, contact = acme
    ClientAssignmentFactory(tenant=company.tenant, user=cf.user, company=company)
    cats = {row["name"]: row for row in get(api, ff, C).json()}
    workshops = cats["Workshops and speaking"]["id"]
    mine = draft(api, ff, company, contact, income_category=workshops).json()
    # An associate reads and writes the invoice, without the category in it.
    seen = get(api, cf, f"/api/invoices/{mine['id']}/")
    assert seen.status_code == 200 and "income_category" not in seen.json()
    assert workshops not in seen.content.decode()
    assert patch(api, cf, f"/api/invoices/{mine['id']}/", {"notes": "Thanks"}).status_code == 200
    for method, url, body in (
            ("patch", f"/api/invoices/{mine['id']}/", {"income_category": ""}),
            ("post", "/api/invoices/", {"client_company": str(company.pk),
                                        "contact": str(contact.pk), "lines": LINES,
                                        "income_category": workshops}),
            ("post", "/api/invoice-schedules/", {
                "client_company": str(company.pk), "contact": str(contact.pk),
                "day_of_month": 1, "lines": LINES, "income_category": workshops})):
        assert call(api.as_(cf), method, url, body).status_code == 403, url
        assert call(api.as_(va), method, url, body).status_code == 403, url
    theirs = post(api, cf, "/api/invoice-schedules/", {
        "client_company": str(company.pk), "contact": str(contact.pk), "day_of_month": 1,
        "lines": LINES})
    assert theirs.status_code == 201 and "income_category" not in theirs.json()
    assert all("income_category" not in row
               for row in get(api, cf, "/api/invoice-schedules/").json())
    with tenant_context(company.tenant.pk):
        from apps.billing.models import ClientInvoice

        assert str(ClientInvoice.objects.get(pk=mine["id"]).income_category_id) == workshops
    # Another practice's category is not one of ours to name.
    other = _member(tenant_b, "FF")
    foreign = {row["name"]: row for row in get(api, other, C).json()}["Retainers"]["id"]
    assert patch(api, ff, f"/api/invoices/{mine['id']}/",
                 {"income_category": foreign}).status_code == 404
    assert post(api, ff, "/api/finance-settings/",
                {"recurring_income_category": foreign}).status_code == 404


@pytest.mark.django_db
def test_combining_a_category_takes_what_named_it_along(acme, ff, api):
    from apps.tenancy import modules

    modules.set_enabled(acme[0].tenant, modules.BOOKKEEPING, True, actor=ff.user)
    cats = {row["name"]: row for row in get(api, ff, C).json()}
    made = draft(api, ff, *acme, income_category=cats["Retainers"]["id"]).json()
    merged = post(api, ff, f"{C}{cats['Retainers']['id']}/merge/",
                  {"into": cats["Other income"]["id"]})
    assert merged.status_code == 200, merged.content
    assert get(api, ff, "/api/finance-settings/").json()["recurring_income_category"] == \
        cats["Other income"]["id"]
    assert get(api, ff, f"/api/invoices/{made['id']}/").json()["income_category"] == \
        cats["Other income"]["id"]


@pytest.mark.django_db
def test_the_migration_gives_a_practice_that_exists_the_by_kind_start(
        seeded_tenant, tenant_b, ff, api):
    from importlib import import_module

    from django.apps import apps as django_apps

    from apps.finance.models import FinanceSettings

    step = import_module("apps.finance.migrations.0007_invoice_income_by_kind")
    get(api, ff, "/api/finance-settings/")           # the practice's books exist
    with tenant_context(seeded_tenant.pk):
        FinanceSettings.objects.update(recurring_income_category=None,
                                       one_off_income_category=None)
        general = FinanceSettings.objects.get().invoice_income_category_id
    # One whose chart has no such names keeps posting where it does today.
    other = _member(tenant_b, "FF")
    get(api, other, "/api/finance-settings/")
    with tenant_context(tenant_b.pk):
        FinanceSettings.objects.update(recurring_income_category=None,
                                       one_off_income_category=None)
        FinanceCategory.objects.filter(name="Retainers").update(name="Monthly")
        FinanceCategory.objects.filter(name="Project fees").update(
            archived_at=timezone.now())

    step.by_kind_for_practices_that_exist(django_apps, None)

    with tenant_context(seeded_tenant.pk):
        row = FinanceSettings.objects.get()
        assert (row.recurring_income_category.name, row.one_off_income_category.name) == \
            ("Retainers", "Project fees")
        assert row.invoice_income_category_id == general
    with tenant_context(tenant_b.pk):
        row = FinanceSettings.objects.get()
        assert row.recurring_income_category_id is None
        assert row.one_off_income_category_id is None


@pytest.mark.django_db
def test_the_migration_adds_retainers_to_a_practice_whose_chart_has_none(
        seeded_tenant, tenant_b, ff, api, capsys):
    """Production's chart was made with one level and no "Retainers" (owner,
    2026-10-11): recurring invoices would have gone on posting to the parent."""
    from importlib import import_module

    from django.apps import apps as django_apps

    from apps.finance.models import FinanceSettings

    step = import_module("apps.finance.migrations.0008_retainers_for_practices_that_exist")
    # A practice as production is: one level, "Client fees" and "Project fees"
    # side by side, paid invoices to "Client fees", nothing by kind for recurring.
    with tenant_context(seeded_tenant.pk):
        rows = {name: FinanceCategory.objects.create(
            tenant=seeded_tenant, name=name, type=kind, position=position,
            system_code="client_fees" if name == "Client fees" else "")
            for position, (name, kind) in enumerate((
                ("Client fees", "income"), ("Project fees", "income"),
                ("Other income", "income"), ("Travel", "expense"),
                ("Owner draw", "owner"), ("Sales tax collected", "held")))}
        bank = services.save_account(seeded_tenant, actor=ff.user, name="Checking")
        old = services.create_entry(
            seeded_tenant, actor=ff.user, kind="income", on_date="2026-03-01",
            amount_cents=500000, account=bank, category=rows["Client fees"])
        config = services.settings_for(seeded_tenant)
        FinanceSettings.objects.filter(pk=config.pk).update(
            recurring_income_category=None, one_off_income_category=rows["Project fees"])
        before = FinanceCategory.objects.count()
    # One that already has its own Retainers, chosen: left exactly as it is.
    other = _member(tenant_b, "FF")
    theirs = get(api, other, "/api/finance-settings/").json()
    with tenant_context(tenant_b.pk):
        theirs_before = FinanceCategory.objects.count()
    capsys.readouterr()

    step.add_retainers(django_apps, None)

    printed = capsys.readouterr().out
    with tenant_context(seeded_tenant.pk):
        made = FinanceCategory.objects.get(name="Retainers")
        assert (made.type, made.parent_id, made.archived_at) == \
            ("income", rows["Client fees"].pk, None)
        assert FinanceCategory.objects.count() == before + 1, "one category, and no more"
        config = FinanceSettings.objects.get()
        assert config.recurring_income_category_id == made.pk
        assert config.one_off_income_category_id == rows["Project fees"].pk
        assert config.invoice_income_category_id == rows["Client fees"].pk
        # Nothing already there is renamed or moved, and no entry moves.
        assert {c.name: c.parent_id for c in FinanceCategory.objects.exclude(pk=made.pk)} \
            == {name: None for name in rows}
        assert FinanceEntry.objects.get(pk=old.pk).category_id == rows["Client fees"].pk
        event = AuditEvent.objects.get(verb="finance.retainers_category_added")
        assert event.payload == {"created": True, "under": "Client fees",
                                 "recurring_invoices_go_to": "Retainers"}
    assert "recurring invoices now go to “Retainers”, under “Client fees” (added)." in printed
    with tenant_context(tenant_b.pk):
        assert FinanceCategory.objects.count() == theirs_before
        assert not AuditEvent.objects.filter(
            verb="finance.retainers_category_added").exists()
    assert get(api, other, "/api/finance-settings/").json() == theirs
    # Run again, there is nothing left to do.
    step.add_retainers(django_apps, None)
    with tenant_context(seeded_tenant.pk):
        assert FinanceCategory.objects.filter(name="Retainers").count() == 1
    # And from then on a recurring invoice's payment is entered under it.
    company, contact = a_client(seeded_tenant)
    with tenant_context(seeded_tenant.pk):
        billing.update_settings(seeded_tenant, {"pay_instructions": "Bank transfer."})
        billing.save_schedule(seeded_tenant, actor=ff.user, client_company=company,
                              contact=contact, day_of_month=1, starts_on="2026-10-01",
                              lines=LINES)
        [written] = billing.run_schedules(seeded_tenant, today=date(2026, 10, 1))
    for action in ("make-ready", "send"):
        assert post(api, ff, f"/api/invoices/{written.pk}/{action}/").status_code == 200
    number = _pay(api, ff, get(api, ff, f"/api/invoices/{written.pk}/").json())
    assert _income(api, ff) == {f"Invoice {number}": "Retainers"}
