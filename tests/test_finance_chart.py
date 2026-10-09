"""P6 M1, the first stop (`docs/p6_m1_reconciliation_month_close.md`): the
Bookkeeping switch, the two-level chart, combine, split, "Add the starting
chart", and the disclaimer.

1. The module: who has it, who switches it, and what a practice without it
   gets.
2. Practice isolation and role boundaries.
3. Sub-categories; removing; the P&L and the exports in two levels.
4. Combine and split, closed months included, with no total changed.
5. The starting chart: whole for a new practice, additive for an existing one.
"""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path

import pytest
from django.apps import apps as django_apps

from apps.finance import chart, services
from apps.finance.disclaimer import DISCLAIMER
from apps.finance.models import (
    FinanceCategory, FinanceCategoryChange, FinanceEntry, FinanceImportRow, FinanceRule,
)
from apps.tenancy import modules
from apps.tenancy.context import tenant_context
from apps.tenancy.models import AuditEvent, PracticeModule

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import (
    ClientCompanyFactory, FinanceImportBatchFactory, FinanceImportRowFactory, TenantFactory,
)
from .test_client_invoicing import get, patch, post  # noqa: F401
from .test_finance_books import A, C, E, R, a_year, add, books  # noqa: F401
from .test_platform_practices import platform_owner, practices  # noqa: F401
from .test_platform_practices import post as platform_post

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def kept(books, ff):          # noqa: F811
    """A practice with the Bookkeeping module, a bank account and its chart."""
    modules.set_enabled(books["tenant"], modules.BOOKKEEPING, True, actor=ff.user)
    return books


def cats(api, ff):
    return {row["name"]: row for row in get(api, ff, C).json()}


def pnl(api, ff, year=2026):
    return get(api, ff, R + f"pnl/?year={year}").json()


def row_of(report, name):
    for section in (report["income"], report["expenses"]):
        for row in section["rows"]:
            if row["name"] == name:
                return row
            for child in row["children"]:
                if child["name"] == name:
                    return child
    raise AssertionError(name)


def bookkeeping_calls(books):            # noqa: F811
    travel, meals = books["cat"]["Travel"]["id"], books["cat"]["Meals"]["id"]
    return [
        ("post", C, {"name": "Tolls", "parent": travel}),
        ("patch", f"{C}{meals}/", {"parent": travel}),
        ("post", f"{C}{meals}/merge/", {"into": travel, "preview": True}),
        ("post", f"{C}{meals}/merge/", {"into": travel}),
        ("post", f"{C}{travel}/split/", {"name": "Flights", "contains": "flight",
                                         "preview": True}),
        ("post", f"{C}{travel}/split/", {"name": "Flights", "contains": "flight"}),
        ("get", C + "starting-chart/", None),
        ("post", C + "starting-chart/", {}),
        ("get", C + "changes/", None),
    ]


def call(client, method, url, body):
    if method == "get":
        return client.get(url)
    return getattr(client, method)(url, json.dumps(body or {}),
                                   content_type="application/json")


# ================================================================ the module

@pytest.mark.django_db
def test_a_practice_without_the_module_keeps_its_books_and_gets_404_from_the_rest(
        books, ff, api):          # noqa: F811
    assert get(api, ff, "/api/me").json()["modules"] == []
    with tenant_context(books["tenant"].pk):
        before = FinanceCategory.objects.count()
    for method, url, body in bookkeeping_calls(books):
        assert call(api.as_(ff), method, url, body).status_code == 404, (method, url)
    with tenant_context(books["tenant"].pk):
        assert FinanceCategory.objects.count() == before
        assert not FinanceCategoryChange.objects.exists()
    # Everything the books did before is still there.
    assert add(api, ff, books, "expense", 100, "2026-10-01", "Travel").status_code == 201
    assert post(api, ff, C, {"name": "Conferences", "type": "expense"}).status_code == 201
    assert get(api, ff, R + "pnl/?year=2026").status_code == 200


@pytest.mark.django_db
def test_the_platform_owner_switches_a_module_and_sees_nothing_inside(
        api, seeded_tenant, platform_owner, tenant_b):          # noqa: F811
    client = practices(api, platform_owner)
    rows = {row["display_name"]: row for row in client.get("/api/platform/practices").json()}
    assert rows["Tenant B"]["modules"] == [
        {"code": "bookkeeping", "name": "Bookkeeping", "enabled": False}]

    url = f"/api/platform/practices/{tenant_b.pk}/modules"
    on = platform_post(client, url, {"module": "bookkeeping", "enabled": True})
    assert on.status_code == 200 and on.json()["modules"][0]["enabled"] is True
    assert modules.has(tenant_b, "bookkeeping")
    row = PracticeModule.objects.get(tenant=tenant_b)
    assert row.enabled_by == platform_owner.user and row.disabled_at is None
    with tenant_context(tenant_b.pk):
        assert AuditEvent.objects.filter(verb="practice.module_enabled").count() == 1
    # Pressing it again changes nothing; off is kept as a row, and audited.
    platform_post(client, url, {"module": "bookkeeping", "enabled": True})
    off = platform_post(client, url, {"module": "bookkeeping", "enabled": False})
    assert off.json()["modules"][0]["enabled"] is False and not modules.has(tenant_b,
                                                                           "bookkeeping")
    assert PracticeModule.objects.filter(tenant=tenant_b).count() == 1
    with tenant_context(tenant_b.pk):
        assert list(AuditEvent.objects.order_by("created_at").values_list(
            "verb", flat=True)) == ["practice.module_enabled", "practice.module_disabled"]
    for bad in ({"module": "payroll", "enabled": True}, {"module": "bookkeeping"},
                {"module": "bookkeeping", "enabled": "yes"}):
        assert platform_post(client, url, bad).status_code == 400
    assert platform_post(client, "/api/platform/practices/"
                         "00000000-0000-0000-0000-000000000000/modules",
                         {"module": "bookkeeping", "enabled": True}).status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FF", "CF", "VA", "FCC"])
def test_nobody_but_the_platform_owner_switches_a_module(api, seeded_tenant, tenant_b, role):
    company = ClientCompanyFactory(tenant=seeded_tenant) if role == "FCC" else None
    member = _member(seeded_tenant, role, company)
    for target in (seeded_tenant, tenant_b):
        refused = platform_post(practices(api, member),
                                f"/api/platform/practices/{target.pk}/modules",
                                {"module": "bookkeeping", "enabled": True})
        assert refused.status_code in (403, 404)
    assert not PracticeModule.objects.exists()


@pytest.mark.django_db
def test_me_names_the_modules_to_staff_and_not_to_a_client(kept, ff, cf, va, fcc, api):
    for member in (ff, cf, va):
        assert get(api, member, "/api/me").json()["modules"] == ["bookkeeping"]
    assert get(api, fcc, "/api/me").json()["modules"] == []


@pytest.mark.django_db
def test_the_migration_switches_bookkeeping_on_for_practices_that_exist(tenant_a, tenant_b):
    from importlib import import_module

    step = import_module("apps.tenancy.migrations.0012_practice_module")
    step.switch_on_for_existing(django_apps, None)
    assert modules.has(tenant_a, "bookkeeping") and modules.has(tenant_b, "bookkeeping")
    step.switch_on_for_existing(django_apps, None)           # and running it again is safe
    assert PracticeModule.objects.count() == 2
    # A practice made afterwards is without it.
    assert not modules.has(TenantFactory(name="Later", slug="later"), "bookkeeping")


# ============================================== isolation and role boundaries

@pytest.mark.django_db
def test_tenant_isolation_another_practice_reaches_none_of_the_chart(
        kept, ff, tenant_b, api):
    add(api, ff, kept, "expense", 12500, "2026-10-01", "Travel", description="SECRET flight")
    other = _member(tenant_b, "FF")
    modules.set_enabled(tenant_b, modules.BOOKKEEPING, True, actor=other.user)
    theirs = cats(api, other)
    mine = kept["cat"]
    refused = [
        # Our category as their parent, their target, or the thing they act on.
        ("post", C, {"name": "Tolls", "parent": mine["Travel"]["id"]}),
        ("patch", f"{C}{theirs['Meals']['id']}/", {"parent": mine["Travel"]["id"]}),
        ("patch", f"{C}{mine['Meals']['id']}/", {"parent": theirs["Travel"]["id"]}),
        ("post", f"{C}{theirs['Meals']['id']}/merge/", {"into": mine["Travel"]["id"]}),
        ("post", f"{C}{mine['Meals']['id']}/merge/", {"into": theirs["Travel"]["id"]}),
        ("post", f"{C}{mine['Travel']['id']}/split/", {"name": "X", "contains": "SECRET"}),
        ("post", f"{C}{theirs['Travel']['id']}/split/",
         {"to": mine["Meals"]["id"], "contains": "SECRET"}),
        ("delete", f"{C}{mine['Vehicle']['id']}/", None),
        ("post", C + "reorder/", {"type": "expense", "parent": mine["Travel"]["id"],
                                  "ids": []}),
    ]
    for method, url, body in refused:
        response = call(api.as_(other), method, url, body)
        assert response.status_code == 404, (method, url, response.status_code)
        assert b"SECRET" not in response.content
    # A change of ours is in our list and not in theirs.
    post(api, ff, f"{C}{mine['Travel']['id']}/split/", {"name": "Flights",
                                                        "contains": "flight"})
    assert len(get(api, ff, C + "changes/").json()) == 1
    assert get(api, other, C + "changes/").json() == []
    assert "Flights" not in cats(api, other)
    with tenant_context(kept["tenant"].pk):
        assert FinanceCategory.objects.filter(name="Vehicle").exists()
        assert FinanceEntry.objects.get().category.name == "Flights"


@pytest.mark.django_db
def test_role_boundaries_the_chart_is_the_practice_owners(kept, ff, cf, va, fcc, api):
    add(api, ff, kept, "expense", 12500, "2026-10-01", "Travel", description="A flight")
    with tenant_context(kept["tenant"].pk):
        before = sorted(FinanceCategory.objects.values_list("name", "parent_id",
                                                            "archived_at"))
    for member, status in ((va, 403), (cf, 403), (fcc, 404)):
        for method, url, body in bookkeeping_calls(kept) + [
                ("delete", f"{C}{kept['cat']['Vehicle']['id']}/", None)]:
            response = call(api.as_(member), method, url, body)
            assert response.status_code == status, (member.role, method, url)
            assert b"A flight" not in response.content
    with tenant_context(kept["tenant"].pk):
        assert sorted(FinanceCategory.objects.values_list(
            "name", "parent_id", "archived_at")) == before
        assert not FinanceCategoryChange.objects.exists()


@pytest.mark.django_db
def test_the_platform_owner_reaches_none_of_a_practices_chart(kept, platform_owner, api):  # noqa: F811
    client = practices(api, platform_owner)
    for method, url, body in bookkeeping_calls(kept) + [("get", C, None)]:
        assert call(client, method, url, body).status_code in (403, 404), (method, url)


# ============================================================ sub-categories

@pytest.mark.django_db
def test_a_sub_category_has_its_parents_type_and_there_are_two_levels(kept, ff, api):
    travel, meals = kept["cat"]["Travel"], kept["cat"]["Meals"]
    made = post(api, ff, C, {"name": "Tolls", "parent": travel["id"], "type": "income"})
    assert made.status_code == 201
    tolls = made.json()
    assert (tolls["parent"], tolls["type"]) == (travel["id"], "expense"), \
        "the parent's type, whatever was sent"
    assert tolls["position"] == 3, "last among Travel's sub-categories"
    # No third level, either way round.
    assert post(api, ff, C, {"name": "Bridges", "parent": tolls["id"]}).status_code == 400
    assert patch(api, ff, f"{C}{travel['id']}/", {"parent": meals["id"]}).status_code == 400
    # Not under another type, not under itself, not under an archived one.
    fees = kept["cat"]["Client fees"]
    assert patch(api, ff, f"{C}{meals['id']}/", {"parent": fees["id"]}).status_code == 400
    assert patch(api, ff, f"{C}{meals['id']}/", {"parent": meals["id"]}).status_code == 400
    patch(api, ff, f"{C}{kept['cat']['Charitable giving']['id']}/", {"archived": True})
    assert patch(api, ff, f"{C}{meals['id']}/", {
        "parent": kept["cat"]["Charitable giving"]["id"]}).status_code == 400
    # One the books rely on stays where it is.
    assert patch(api, ff, f"{C}{fees['id']}/", {
        "parent": kept["cat"]["Other income"]["id"]}).status_code == 409
    # A sub-category's type follows its parent and is not set by itself.
    assert patch(api, ff, f"{C}{tolls['id']}/", {"type": "income"}).status_code == 409

    # Moving: Meals under Travel, then Tolls out to the top level.
    moved = patch(api, ff, f"{C}{meals['id']}/", {"parent": travel["id"]}).json()
    assert moved["parent"] == travel["id"] and moved["position"] == 4
    out = patch(api, ff, f"{C}{tolls['id']}/", {"parent": None}).json()
    assert out["parent"] is None
    # The order within one parent, and it has to name every one at that level.
    subs = [row["id"] for row in get(api, ff, C).json() if row["parent"] == travel["id"]]
    assert len(subs) == 4
    done = post(api, ff, C + "reorder/", {"type": "expense", "parent": travel["id"],
                                          "ids": subs[::-1]})
    assert [row["id"] for row in sorted(
        (r for r in done.json() if r["parent"] == travel["id"]),
        key=lambda r: r["position"])] == subs[::-1]
    assert post(api, ff, C + "reorder/", {"type": "expense", "parent": travel["id"],
                                          "ids": subs[:2]}).status_code == 400


@pytest.mark.django_db
def test_an_entry_sits_on_a_parent_or_a_sub_category_and_the_pnl_adds_up(kept, ff, api):
    add(api, ff, kept, "expense", 40000, "2026-03-03", "Airfare")
    add(api, ff, kept, "expense", 25000, "2026-03-09", "Lodging")
    add(api, ff, kept, "expense", 5000, "2026-04-01", "Travel")          # on the parent
    add(api, ff, kept, "expense", 1200, "2026-04-02", "Meals")
    add(api, ff, kept, "income", 500000, "2026-03-01", "Retainers")
    report = pnl(api, ff)
    travel = row_of(report, "Travel")
    assert travel["total"] == 70000 and travel["amounts"][2:4] == [65000, 5000]
    assert [(c["name"], c["total"]) for c in travel["children"]] == [
        ("Airfare", 40000), ("Lodging", 25000), ("Ground transport", 0),
        ("Travel, not broken down", 5000)]
    assert travel["children"][-1].get("direct") is True
    assert sum(child["total"] for child in travel["children"]) == travel["total"]
    assert row_of(report, "Meals")["children"] == []
    assert row_of(report, "Client fees")["total"] == 500000
    assert report["expenses"]["total"] == 71200 and report["income"]["total"] == 500000
    assert report["net_total"] == 500000 - 71200
    assert report["expenses"]["total"] == sum(r["total"] for r in report["expenses"]["rows"])

    # The entries behind a category's figure are its own and its
    # sub-categories'; behind a line's, that line's only.
    travel_id = kept["cat"]["Travel"]["id"]
    assert get(api, ff, f"{E}?category={travel_id}&subs=1").json()["count"] == 3
    assert get(api, ff, f"{E}?category={travel_id}").json()["count"] == 1

    text = get(api, ff, R + "pnl/?year=2026&download=1").content.decode()
    lines = list(csv.reader(io.StringIO(text)))
    names = [line[0] for line in lines if line]
    assert "Travel" in names and "    Airfare" in names
    assert names.index("    Airfare") == names.index("Travel") + 1, "under its parent"

    span = "?from=2026-01-01&to=2026-12-31"
    rows = list(csv.DictReader(io.StringIO(
        get(api, ff, R + "export-entries/" + span).content.decode())))
    assert {(r["Category"], r["Parent category"]) for r in rows} == {
        ("Airfare", "Travel"), ("Lodging", "Travel"), ("Travel", ""), ("Meals", ""),
        ("Retainers", "Client fees")}
    summary = list(csv.reader(io.StringIO(
        get(api, ff, R + "export-summary/" + span).content.decode())))
    assert summary[1] == ["Type", "Category", "Parent category", "CPA code", "Total"]
    assert ["Expense", "Airfare", "Travel", "", "400.00"] in summary
    assert ["Expense", "Travel", "", "", "50.00"] in summary
    assert ["", "Total expenses", "", "", "712.00"] in summary


@pytest.mark.django_db
def test_removing_archiving_and_restoring_in_two_levels(kept, ff, api):
    travel, meals = kept["cat"]["Travel"], kept["cat"]["Meals"]
    add(api, ff, kept, "expense", 100, "2026-10-01", "Meals")
    # Unused: removed outright, and audited.
    assert api.as_(ff).delete(f"{C}{kept['cat']['Vehicle']['id']}/").status_code == 409, \
        "it still has sub-categories"
    for name in ("Mileage and fuel", "Parking and tolls", "Vehicle"):
        assert api.as_(ff).delete(f"{C}{kept['cat'][name]['id']}/").status_code == 204
    assert "Vehicle" not in cats(api, ff)
    with tenant_context(kept["tenant"].pk):
        assert AuditEvent.objects.filter(verb="finance.category_removed").count() == 3
    # Used, relied on, or pointed at by a rule: not removed.
    assert api.as_(ff).delete(f"{C}{meals['id']}/").status_code == 409
    assert api.as_(ff).delete(f"{C}{kept['cat']['Client fees']['id']}/").status_code == 409
    post(api, ff, "/api/finance-rules/", {"contains": "UBER", "treat_as": "category",
                                          "category": kept["cat"]["Lodging"]["id"]})
    assert api.as_(ff).delete(f"{C}{kept['cat']['Lodging']['id']}/").status_code == 409
    # A parent is archived only once its sub-categories are; a sub-category
    # is restored only once its parent is.
    assert patch(api, ff, f"{C}{travel['id']}/", {"archived": True}).status_code == 409
    for name in ("Airfare", "Lodging", "Ground transport"):
        patch(api, ff, f"{C}{kept['cat'][name]['id']}/", {"archived": True})
    assert patch(api, ff, f"{C}{travel['id']}/", {"archived": True}).status_code == 200
    assert patch(api, ff, f"{C}{kept['cat']['Airfare']['id']}/",
                 {"archived": False}).status_code == 409
    patch(api, ff, f"{C}{travel['id']}/", {"archived": False})
    assert patch(api, ff, f"{C}{kept['cat']['Airfare']['id']}/",
                 {"archived": False}).status_code == 200


# ================================================================== combine

@pytest.mark.django_db
def test_combining_moves_everything_and_changes_no_total_closed_months_included(
        kept, ff, api):
    tenant = kept["tenant"]
    add(api, ff, kept, "expense", 40000, "2025-11-03", "Meals", description="Team dinner")
    add(api, ff, kept, "expense", 2500, "2026-03-09", "Meals")
    gone = add(api, ff, kept, "expense", 999, "2026-03-10", "Meals").json()
    post(api, ff, f"{E}{gone['id']}/remove/", {"reason": "Entered twice"})
    add(api, ff, kept, "expense", 30000, "2026-03-11", "Travel")
    add(api, ff, kept, "income", 500000, "2026-03-01", "Client fees")
    rule = post(api, ff, "/api/finance-rules/", {
        "contains": "DINER", "treat_as": "category",
        "category": kept["cat"]["Meals"]["id"]}).json()
    with tenant_context(tenant.pk):
        line = FinanceImportRowFactory(
            tenant=tenant, batch=FinanceImportBatchFactory(
                tenant=tenant, account_id=kept["bank"]["id"]),
            category_id=kept["cat"]["Meals"]["id"], outcome="new", row_number=2)
        # 2025 is closed: nothing in it can be added, changed or removed.
        services.update_settings(tenant, actor=ff.user, locked_through="2025-12-31")
    meals, travel = kept["cat"]["Meals"]["id"], kept["cat"]["Travel"]["id"]
    before = {year: pnl(api, ff, year) for year in (2025, 2026)}

    counted = post(api, ff, f"{C}{meals}/merge/", {"into": travel, "preview": True})
    assert counted.status_code == 200
    assert counted.json() == {"entries": 2, "first_on": "2025-11-03", "last_on": "2026-03-09",
                              "rules": 1, "sub_categories": 0, "from": "Meals",
                              "to": "Travel"}
    with tenant_context(tenant.pk):
        assert FinanceEntry.objects.filter(category_id=meals).count() == 3, \
            "the count moved nothing"

    assert post(api, ff, f"{C}{meals}/merge/", {"into": travel}).status_code == 200
    with tenant_context(tenant.pk):
        assert not FinanceEntry.objects.filter(category_id=meals).exists()
        assert FinanceEntry.objects.filter(category_id=travel).count() == 4, \
            "the removed one too, so nothing is left pointing at an archived category"
        assert FinanceEntry.objects.get(description="Team dinner").on_date.year == 2025
        assert str(FinanceRule.objects.get(pk=rule["id"]).category_id) == travel
        assert str(FinanceImportRow.objects.get(pk=line.pk).category_id) == travel
        source = FinanceCategory.objects.get(pk=meals)
        assert source.archived_at is not None and str(source.merged_into_id) == travel
        change = FinanceCategoryChange.objects.get()
        assert (change.kind, change.entries_moved, change.first_on.isoformat(),
                change.last_on.isoformat(), change.by) == (
            "merge", 2, "2025-11-03", "2026-03-09", ff.user)
        assert AuditEvent.objects.filter(verb="finance.categories_combined").count() == 1
    row = cats(api, ff)["Meals"]
    assert row["archived"] is True and row["merged_into"] == travel

    for year in (2025, 2026):
        after = pnl(api, ff, year)
        for key in ("net", "net_total"):
            assert after[key] == before[year][key]
        for section in ("income", "expenses"):
            assert after[section]["totals"] == before[year][section]["totals"]
    assert row_of(pnl(api, ff, 2025), "Travel")["total"] == 40000
    listed = get(api, ff, C + "changes/").json()
    assert [(c["kind_label"], c["from"], c["to"], c["entries_moved"]) for c in listed] == [
        ("Combined", "Meals", "Travel", 2)]
    # The lock still holds for everything else.
    assert add(api, ff, kept, "expense", 100, "2025-12-01", "Travel").status_code == 409


@pytest.mark.django_db
def test_combining_takes_sub_categories_along_and_is_refused_where_it_makes_no_sense(
        kept, ff, api):
    cat = kept["cat"]
    add(api, ff, kept, "expense", 5000, "2026-03-03", "Supplies")

    def merge(source, into):
        return post(api, ff, f"{C}{cat[source]['id']}/merge/", {"into": cat[into]["id"]})

    assert merge("Travel", "Travel").status_code == 400
    assert merge("Travel", "Client fees").status_code == 400            # another type
    assert merge("Client fees", "Other income").status_code == 409     # relied on
    assert merge("Sales tax collected", "Sales tax collected").status_code == 400
    assert merge("Travel", "Airfare").status_code == 400               # into its own child
    assert merge("Travel", "Supplies").status_code == 400    # a parent into a sub-category
    patch(api, ff, f"{C}{cat['Meals']['id']}/", {"archived": True})
    assert merge("Travel", "Meals").status_code == 409                 # into an archived one
    assert merge("Meals", "Travel").status_code == 409                 # an archived one
    assert post(api, ff, f"{C}{cat['Travel']['id']}/merge/", {}).status_code == 404

    # A parent into a parent: its sub-categories go with it, after the others.
    assert merge("Office", "Travel").status_code == 200
    now = cats(api, ff)
    under = sorted((row for row in now.values() if row["parent"] == cat["Travel"]["id"]),
                   key=lambda row: row["position"])
    assert [row["name"] for row in under] == [
        "Airfare", "Lodging", "Ground transport", "Supplies", "Equipment",
        "Postage and printing"]
    assert row_of(pnl(api, ff), "Travel")["total"] == 5000
    # A sub-category into any category of its type; and where paid invoices
    # went follows a category that was combined away.
    assert merge("Other income", "Retainers").status_code == 200
    post(api, ff, "/api/finance-settings/", {
        "invoice_income_category": cat["Interest income"]["id"]})
    assert merge("Interest income", "Referral fees received").status_code == 200
    assert get(api, ff, "/api/finance-settings/").json()["invoice_income_category"] == \
        cat["Referral fees received"]["id"]


# ==================================================================== split

@pytest.mark.django_db
def test_splitting_moves_exactly_the_entries_chosen(kept, ff, api):
    tenant, travel = kept["tenant"], kept["cat"]["Travel"]["id"]
    uber = [add(api, ff, kept, "expense", cents, on, "Travel", description=text,
                counterparty=who).json()
            for cents, on, text, who in ((1800, "2025-10-02", "Ride to the plant", "Uber"),
                                         (2200, "2026-03-04", "UBER *TRIP", ""),
                                         (61000, "2026-03-05", "Flight to Tucson", "United"),
                                         (33000, "2026-03-06", "Hotel", "Hilton"))]
    with tenant_context(tenant.pk):
        services.update_settings(tenant, actor=ff.user, locked_through="2025-12-31")
    before = {year: pnl(api, ff, year) for year in (2025, 2026)}

    counted = post(api, ff, f"{C}{travel}/split/", {"name": "Rideshare", "contains": "uber",
                                                    "preview": True}).json()
    assert counted == {"entries": 2, "first_on": "2025-10-02", "last_on": "2026-03-04",
                       "from": "Travel", "to": "Rideshare", "new": True, "under": "Travel",
                       "contains": "uber", "left": 2}
    assert "Rideshare" not in cats(api, ff), "the count made nothing"

    assert post(api, ff, f"{C}{travel}/split/", {"name": "Rideshare",
                                                 "contains": "uber"}).status_code == 200
    made = cats(api, ff)["Rideshare"]
    assert made["parent"] == travel and made["type"] == "expense"
    with tenant_context(tenant.pk):
        assert sorted(FinanceEntry.objects.filter(category_id=made["id"]).values_list(
            "description", flat=True)) == ["Ride to the plant", "UBER *TRIP"], \
            "by description or by payee, whatever the case, the closed year included"
        assert FinanceEntry.objects.filter(category_id=travel).count() == 2
        change = FinanceCategoryChange.objects.get()
        assert (change.kind, change.entries_moved, change.contains) == ("split", 2, "uber")
        assert AuditEvent.objects.filter(verb="finance.category_split").count() == 1

    # By ticking: one entry to a category beside Travel, one to one that exists.
    assert post(api, ff, f"{C}{travel}/split/", {
        "name": "Client site visits", "as": "beside",
        "entries": [uber[2]["id"]]}).status_code == 200
    beside = cats(api, ff)["Client site visits"]
    assert beside["parent"] is None
    assert post(api, ff, f"{C}{travel}/split/", {
        "to": kept["cat"]["Lodging"]["id"], "entries": [uber[3]["id"]]}).status_code == 200
    with tenant_context(tenant.pk):
        assert not FinanceEntry.objects.filter(category_id=travel).exists()
        assert FinanceEntry.objects.get(pk=uber[3]["id"]).category.name == "Lodging"
        assert FinanceCategoryChange.objects.count() == 3

    for year in (2025, 2026):
        after = pnl(api, ff, year)
        assert after["net"] == before[year]["net"]
        assert after["expenses"]["totals"] == before[year]["expenses"]["totals"]
    assert row_of(pnl(api, ff), "Travel")["total"] == 2200 + 33000, \
        "what moved beside it left Travel's total; what stayed under it did not"


@pytest.mark.django_db
def test_a_split_is_refused_when_it_would_move_nothing_or_break_the_chart(kept, ff, api):
    cat = kept["cat"]
    entry = add(api, ff, kept, "expense", 1800, "2026-03-02", "Airfare",
                description="Flight").json()
    other = add(api, ff, kept, "expense", 900, "2026-03-02", "Meals").json()
    travel, airfare = cat["Travel"]["id"], cat["Airfare"]["id"]

    def split(source, body):
        return post(api, ff, f"{C}{source}/split/", body)

    new = {"name": "Red-eyes", "as": "beside"}
    assert split(airfare, new).status_code == 400                         # which entries?
    assert split(airfare, {**new, "contains": "x"}).status_code == 400
    assert split(airfare, {**new, "contains": "zeppelin"}).status_code == 409
    assert split(airfare, {**new, "name": "Lodging", "contains": "flight"}
                 ).status_code == 409
    assert split(airfare, {**new, "name": " ", "contains": "flight"}).status_code == 400
    # No third level: a new one from a sub-category goes beside it.
    assert split(airfare, {"name": "Red-eyes", "as": "sub",
                           "contains": "flight"}).status_code == 400
    assert split(airfare, {"to": airfare, "contains": "flight"}).status_code == 400
    assert split(airfare, {"to": cat["Client fees"]["id"],
                           "contains": "flight"}).status_code == 400       # another type
    # An entry that is not in this category is not moved by naming it.
    assert split(airfare, {"name": "Red-eyes", "as": "beside",
                           "entries": [other["id"]]}).status_code == 409
    with tenant_context(kept["tenant"].pk):
        assert not FinanceCategoryChange.objects.exists()
        assert str(FinanceEntry.objects.get(pk=entry["id"]).category_id) == airfare
    done = split(airfare, {"name": "Red-eyes", "as": "beside", "contains": "flight"})
    assert done.status_code == 200
    assert cats(api, ff)["Red-eyes"]["parent"] == travel, "beside Airfare is under Travel"


# ============================================================ the starting chart

@pytest.mark.django_db
def test_a_new_practice_starts_with_the_two_level_chart(kept, ff, api):
    rows = get(api, ff, C).json()
    by_id = {row["id"]: row for row in rows}
    tree = {}
    for row in sorted(rows, key=lambda r: r["position"]):
        if row["parent"]:
            tree.setdefault(by_id[row["parent"]]["name"], []).append(row["name"])
    assert tree["Client fees"] == ["Retainers", "Project fees", "Workshops and speaking"]
    assert tree["Travel"] == ["Airfare", "Lodging", "Ground transport"]
    assert tree["Owner draw"] == ["Draws", "Estimated tax payments"]
    assert len(tree) == 11 and sum(len(subs) for subs in tree.values()) == 30
    assert all(by_id[row["parent"]]["type"] == row["type"] for row in rows if row["parent"])
    names = [row["name"].casefold() for row in rows]
    assert len(names) == len(set(names)), "every name in the chart is its own"
    assert [row["name"] for row in rows if row["is_contractor"]] == [
        "Contractors and associates"]
    assert {row["name"] for row in rows if row["system"]} == {"Client fees",
                                                              "Sales tax collected"}
    # A practice that starts with it has nothing to add.
    plan = get(api, ff, C + "starting-chart/").json()
    assert plan["add"] == [] and plan["skipped"] == [] and "Ask your CPA" in plan["note"]


@pytest.fixture
def an_older_practice(seeded_tenant, ff):
    """A practice whose chart was made before P6 M1 and has been lived in:
    one level, some names its own, one archived, one moved."""
    modules.set_enabled(seeded_tenant, modules.BOOKKEEPING, True, actor=ff.user)
    with tenant_context(seeded_tenant.pk):
        rows = {}
        for position, (name, kind) in enumerate((
                ("Client fees", "income"), ("Consulting income", "income"),
                ("TRAVEL", "expense"), ("Meals", "expense"), ("Airfare", "expense"),
                ("Insurance", "expense"), ("Vehicle", "expense"),
                ("Contractors and associates", "expense"), ("Owner draw", "owner"),
                ("Sales tax collected", "held"))):
            rows[name] = FinanceCategory.objects.create(
                tenant=seeded_tenant, name=name, type=kind, position=position,
                cpa_code="X1" if name == "Meals" else "",
                system_code=chart.SYSTEM_CODES.get(name, ""))
        # "Airfare" is theirs, and under Meals: odd, and their business.
        rows["Airfare"].parent = rows["Meals"]
        rows["Airfare"].save()
        # They removed Vehicle on purpose; and Insurance sits under Meals too.
        rows["Vehicle"].archived_at = rows["Vehicle"].created_at
        rows["Vehicle"].save()
        rows["Insurance"].parent = rows["Meals"]
        rows["Insurance"].save()
    return seeded_tenant


def _chart_rows(tenant):
    with tenant_context(tenant.pk):
        return {str(row.pk): (row.name, row.type, row.position, row.cpa_code,
                              str(row.parent_id or ""), row.archived_at, row.system_code,
                              row.is_contractor)
                for row in FinanceCategory.objects.all()}


@pytest.mark.django_db
def test_add_the_starting_chart_adds_what_is_missing_and_touches_nothing_else(
        an_older_practice, ff, api):
    tenant = an_older_practice
    with tenant_context(tenant.pk):
        bank = services.save_account(tenant, actor=ff.user, name="Checking")
        entry = services.create_entry(
            tenant, actor=ff.user, kind="expense", on_date="2026-03-01", amount_cents=5000,
            account=bank, category=FinanceCategory.objects.get(name="TRAVEL"))
    before = _chart_rows(tenant)

    plan = get(api, ff, C + "starting-chart/").json()
    assert _chart_rows(tenant) == before, "looking adds nothing"
    adding = {(item["name"], item["parent"]) for item in plan["add"]}
    # Missing categories, and missing sub-categories under what they have.
    assert ("Payroll", None) in adding and ("Wages", "Payroll") in adding
    assert ("Retainers", "Client fees") in adding
    assert ("Lodging", "Travel") in adding, "matched to their TRAVEL, whatever the case"
    assert ("Draws", "Owner draw") in adding
    # What they have, by name and type, is not added again, wherever it sits.
    have = {name for name, _ in adding}
    assert not have & {"Client fees", "Travel", "TRAVEL", "Meals", "Airfare",
                       "Contractors and associates", "Owner draw", "Sales tax collected"}
    # Archived on purpose counts as theirs: not brought back, nor its sub-categories.
    assert "Vehicle" not in have
    assert {item["name"] for item in plan["skipped"]} == {
        "Mileage and fuel", "Parking and tolls",          # Vehicle is archived
        "Business liability", "Health"}                   # Insurance is a sub-category here
    assert "Consulting income" not in have

    done = post(api, ff, C + "starting-chart/", {})
    assert done.status_code == 200 and done.json()["added"] == len(plan["add"])
    after = _chart_rows(tenant)
    assert {pk: after[pk] for pk in before} == before, \
        "nothing that was there is renamed, moved, re-typed, archived or removed"
    assert len(after) == len(before) + len(plan["add"])
    now = cats(api, ff)
    assert now["Lodging"]["parent"] == now["TRAVEL"]["id"]
    assert now["Airfare"]["parent"] == now["Meals"]["id"], "theirs stays where they put it"
    assert now["Wages"]["parent"] == now["Payroll"]["id"]
    assert now["Payroll"]["position"] > now["Contractors and associates"]["position"]
    with tenant_context(tenant.pk):
        assert FinanceEntry.objects.get(pk=entry.pk).category.name == "TRAVEL"
        audit = AuditEvent.objects.get(verb="finance.starting_chart_added")
        assert "Payroll" in audit.payload["added"]
        assert sorted(audit.payload["skipped"]) == ["Business liability", "Health",
                                                    "Mileage and fuel", "Parking and tolls"]
    # Pressed again: nothing new in the chart, so nothing added, nothing audited.
    again = post(api, ff, C + "starting-chart/", {}).json()
    assert again["added"] == 0 and _chart_rows(tenant) == after
    with tenant_context(tenant.pk):
        assert AuditEvent.objects.filter(verb="finance.starting_chart_added").count() == 1


@pytest.mark.django_db
def test_the_migration_marks_the_contractor_category_and_nothing_else(an_older_practice):
    from importlib import import_module

    before = _chart_rows(an_older_practice)
    import_module("apps.finance.migrations.0003_category_tree").mark_contractor_category(
        django_apps, None)
    after = _chart_rows(an_older_practice)
    changed = [pk for pk in before if before[pk] != after[pk]]
    assert [after[pk][0] for pk in changed] == ["Contractors and associates"]
    assert after[changed[0]][-1] is True and after[changed[0]][:-1] == before[changed[0]][:-1]


# ============================================================ the disclaimer

def test_the_disclaimer_is_the_owners_words_in_both_places():
    assert DISCLAIMER == ("Bookkeeping and projections only, not tax, legal or financial "
                          "advice. Confirm with your CPA.")
    source = (ROOT / "frontend" / "src" / "lib" / "finance.ts").read_text()
    found = re.search(r'FINANCE_DISCLAIMER\s*=\s*\n?\s*"([^"]+)"', source)
    assert found and found.group(1) == DISCLAIMER
