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
from .factories import ClientAssignmentFactory
from .test_client_invoicing import (  # noqa: F401  (fixtures and helpers)
    LINES, TOTAL, a_client, acme, call, ecc, get, patch, post, ready_to_bill, sent,
)
from .test_platform_isolation import in_practices_area

E = "/api/finance-entries/"
A = "/api/finance-accounts/"
C = "/api/finance-categories/"
R = "/api/finance-reports/"


@pytest.fixture
def books(seeded_tenant, ff, api):
    """A practice with its chart, a bank account and a card."""
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
    assert len(get(api, other, C).json()) == 58      # its own starting chart, whole
    for method, url, body in finance_calls(books, mine["id"]):
        response = call(api.as_(other), method, url, body)
        assert b"SECRET-TRIP" not in response.content and b"Checking" not in response.content
        if mine["id"] in url or books["bank"]["id"] in url or \
                books["cat"]["Travel"]["id"] in url:
            assert response.status_code == 404, (method, url)
    # An entry of theirs cannot name an account, a category or a company of ours.
    theirs = post(api, other, A, {"name": "Their bank"}).json()
    their_cat = {row["name"]: row for row in get(api, other, C).json()}["Travel"]
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
    assert [len(top[t]) for t in ("income", "expense", "owner", "held")] == [5, 20, 2, 1]
    assert [len(by_type[t]) for t in ("income", "expense", "owner", "held")] == [8, 45, 4, 1]
    assert top["income"][0] == "Client fees" and top["expense"][4] == "Travel"
    assert top["owner"] == ["Owner contribution", "Owner draw"]
    travel = next(row for row in rows if row["name"] == "Travel")
    # Rename, a CPA code, a new one, and the order.
    assert patch(api, ff, f"{C}{travel['id']}/", {"name": "Travel and lodging",
                                                  "cpa_code": "24a"}).json()["cpa_code"] == "24a"
    made = post(api, ff, C, {"name": "Conferences", "type": "expense"})
    assert made.status_code == 201 and made.json()["position"] == 20
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
    assert len(get(api, ff, C).json()) == 59


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
    assert entry["category"]["name"] == "Client fees"
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
