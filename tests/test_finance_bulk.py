"""Several entries at once (owner, 2026-10-10): change their category, or
remove them, counted first and recorded; and several ticks at once on a
statement.

1. Practice isolation and role boundaries.
2. The count says what it will do and what it leaves out, and why.
3. It then does exactly that: nothing in a locked month, and one record.
"""

from __future__ import annotations

import json

import pytest

from apps.finance import services
from apps.finance.models import FinanceEntry
from apps.tenancy import modules
from apps.tenancy.context import tenant_context
from apps.tenancy.models import AuditEvent

from . import registry_config  # noqa: F401
from .conftest import _member
from .test_client_invoicing import (  # noqa: F401  (fixtures and helpers)
    TOTAL, a_client, acme, call, ecc, get, patch, post, ready_to_bill, sent,
)
from .test_finance_books import (  # noqa: F401
    A, C, E, R, add, books, snapshot, working_chart,
)
from .test_finance_reconcile import LAST, OPENING, OWED, PRIOR, RC, begin, end, on
from .test_platform_practices import platform_owner, practices  # noqa: F401

B = E + "bulk/"


def bulk_calls(books, ids):          # noqa: F811
    meals = books["cat"]["Meals"]["id"]
    return [
        ("get", B, None),
        ("post", B, {"action": "recategorize", "entries": ids, "category": meals,
                     "preview": True}),
        ("post", B, {"action": "recategorize", "entries": ids, "category": meals}),
        ("post", B, {"action": "remove", "entries": ids, "preview": True}),
        ("post", B, {"action": "remove", "entries": ids, "reason": "Entered twice"}),
    ]


@pytest.fixture
def three(books, ff, api):          # noqa: F811
    ids = [add(api, ff, books, "expense", cents, "2026-10-01", "Travel",
               description="SECRET-TRIP").json()["id"] for cents in (1000, 2000, 3000)]
    return {**books, "ids": ids}


# ============================================== isolation and role boundaries

@pytest.mark.django_db
def test_tenant_isolation_another_practice_cannot_count_or_change_our_entries(
        three, ff, tenant_b, api):
    other = _member(tenant_b, "FF")
    their_meals = {row["name"]: row for row in get(api, other, C).json()}["Supplies"]["id"]
    before = snapshot(three["tenant"])
    assert get(api, other, B).json() == []
    for body in ({"action": "recategorize", "category": their_meals},
                 {"action": "recategorize", "category": three["cat"]["Meals"]["id"]},
                 {"action": "remove", "reason": "Entered twice"}):
        for preview in (True, False):
            response = post(api, other, B, {**body, "entries": three["ids"],
                                            "preview": preview})
            assert response.status_code == 404, body
            assert b"SECRET-TRIP" not in response.content
    assert snapshot(three["tenant"]) == before
    # And a bulk change of ours is not in their list of them.
    post(api, ff, B, {"action": "remove", "entries": three["ids"][:1],
                      "reason": "SECRET-REASON"})
    assert get(api, other, B).json() == []
    assert len(get(api, ff, B).json()) == 1


@pytest.mark.django_db
def test_role_boundaries_bulk_changes_are_the_practice_owners(
        three, ff, cf, va, fcc, ecc, platform_owner, api):          # noqa: F811
    before = snapshot(three["tenant"])
    for who, status in ((va, 403), (cf, 403), (fcc, 404), (ecc, 404)):
        for method, url, body in bulk_calls(three, three["ids"]):
            response = call(api.as_(who), method, url, body)
            assert response.status_code == status, (who.role, method, body)
            assert b"SECRET-TRIP" not in response.content
    client = practices(api, platform_owner)
    for method, url, body in bulk_calls(three, three["ids"]):
        assert call(client, method, url, body).status_code in (403, 404)
    assert snapshot(three["tenant"]) == before, "nothing changed, not even an audit row"


# ====================================================== counted, then done

@pytest.mark.django_db
def test_changing_category_counts_first_then_moves_exactly_those(books, ff, api):          # noqa: F811
    moved = [add(api, ff, books, "expense", 1000, "2026-10-01", "Travel").json()["id"],
             add(api, ff, books, "expense", 2000, "2026-10-09", "Travel").json()["id"]]
    there = add(api, ff, books, "expense", 300, "2026-10-02", "Meals").json()["id"]
    income = add(api, ff, books, "income", 5000, "2026-10-02", "Client fees").json()["id"]
    transfer = add(api, ff, books, "transfer", 700, "2026-10-03",
                   to_account=books["card"]["id"]).json()["id"]
    old = add(api, ff, books, "expense", 4000, "2026-08-10", "Travel").json()["id"]
    with tenant_context(books["tenant"].pk):
        services.update_settings(books["tenant"], actor=ff.user, locked_through="2026-08-31")
        events = AuditEvent.objects.count()
    ids = [*moved, there, income, transfer, old]
    body = {"action": "recategorize", "entries": ids, "category": books["cat"]["Meals"]["id"]}

    counted = post(api, ff, B, {**body, "preview": True})
    assert counted.status_code == 200
    assert counted.json() == {
        "action": "recategorize", "chosen": 6, "count": 2, "to": "Meals",
        "first_on": "2026-10-01", "last_on": "2026-10-09",
        "left_out": [
            {"why": "locked", "label": "in a closed or locked month", "count": 1},
            {"why": "transfer", "label": "a transfer, which has no category", "count": 1},
            {"why": "type", "label": "of a kind that category cannot take", "count": 1},
            {"why": "same", "label": "already in that category", "count": 1}]}
    with tenant_context(books["tenant"].pk):
        assert AuditEvent.objects.count() == events, "a count writes nothing"
        assert set(FinanceEntry.objects.filter(pk__in=moved).values_list(
            "category__name", flat=True)) == {"Travel"}

    done = post(api, ff, B, body)
    assert done.status_code == 200 and done.json() == counted.json()
    with tenant_context(books["tenant"].pk):
        names = dict(FinanceEntry.objects.values_list("pk", "category__name"))
        assert {str(pk): name for pk, name in names.items()} == {
            moved[0]: "Meals", moved[1]: "Meals", there: "Meals", income: "Client fees",
            transfer: None, old: "Travel"}
        # Recorded as a combine is: one event for the action, and each entry's own.
        record = AuditEvent.objects.get(verb="finance.entries_recategorized")
        assert record.actor == ff.user
        assert (record.payload["count"], record.payload["chosen"], record.payload["to"],
                record.payload["first_on"], record.payload["last_on"]) == \
            (2, 6, "Meals", "2026-10-01", "2026-10-09")
        assert AuditEvent.objects.filter(verb="finance.entry_changed",
                                         target_id__in=moved).count() == 2
    listed = get(api, ff, B).json()
    assert [(row["action"], row["count"], row["to"], row["by"]) for row in listed] == \
        [("recategorize", 2, "Meals", ff.user.full_name)]
    # Done again there is nothing left to move, and it says so.
    again = post(api, ff, B, body)
    assert again.status_code == 409 and "None of the chosen entries" in again.json()["detail"]
    assert post(api, ff, B, {**body, "preview": True}).json()["count"] == 0


@pytest.mark.django_db
def test_deleting_counts_first_needs_a_reason_and_leaves_locked_months_alone(
        ready_to_bill, ff, api):
    tenant = ready_to_bill
    working_chart(tenant)
    modules.set_enabled(tenant, modules.BOOKKEEPING, True, actor=ff.user)
    bank = post(api, ff, A, {"name": "Checking", "kind": "bank", "opening_on": on(PRIOR, 1),
                             "opening_balance_cents": OPENING}).json()
    card = post(api, ff, A, {"name": "Card", "kind": "card", "opening_on": on(PRIOR, 1),
                             "opening_balance_cents": OWED}).json()
    kit = {"tenant": tenant, "bank": bank, "card": card,
           "cat": {row["name"]: row for row in get(api, ff, C).json()}}
    closed = add(api, ff, kit, "expense", 4000, on(PRIOR, 10), "Travel").json()["id"]
    for account, balance in (("bank", OPENING - 4000), ("card", OWED)):
        rec = begin(api, ff, kit, account, PRIOR, balance).json()
        post(api, ff, f"{RC}{rec['id']}/tick/", {"all": True})
        assert post(api, ff, f"{RC}{rec['id']}/finish/").status_code == 200
    assert post(api, ff, f"/api/finance-months/{PRIOR.isoformat()[:7]}/close/") \
        .status_code == 200
    # An open month: two plain entries, one ticked off on a finished statement,
    # and an invoice payment.
    plain = [add(api, ff, kit, "expense", cents, on(LAST, 5), "Travel").json()["id"]
             for cents in (1000, 2000)]
    ticked = add(api, ff, kit, "expense", 500, on(LAST, 6), "Meals").json()["id"]
    rec = begin(api, ff, kit, "bank", LAST, OPENING - 4000 - 500).json()
    post(api, ff, f"{RC}{rec['id']}/tick/", {"entries": [ticked]})
    assert post(api, ff, f"{RC}{rec['id']}/finish/").status_code == 200
    company, contact = a_client(tenant)
    invoice = sent(api, ff, company, contact)
    post(api, ff, f"/api/invoices/{invoice['id']}/payments/",
         {"amount_cents": TOTAL, "paid_on": on(LAST, 20)})
    paid = get(api, ff, E + "?account=none").json()["entries"][0]["id"]
    ids = [closed, *plain, ticked, paid]

    counted = post(api, ff, B, {"action": "remove", "entries": ids, "preview": True}).json()
    assert (counted["chosen"], counted["count"], counted["to"]) == (5, 2, "")
    assert [(row["why"], row["count"]) for row in counted["left_out"]] == [
        ("locked", 1), ("invoice", 1), ("cleared", 1)]
    assert post(api, ff, B, {"action": "remove", "entries": ids}).status_code == 400
    assert post(api, ff, B, {"action": "remove", "entries": ids,
                             "reason": " "}).status_code == 400

    done = post(api, ff, B, {"action": "remove", "entries": ids, "reason": "Entered twice"})
    assert done.status_code == 200 and done.json()["count"] == 2
    with tenant_context(tenant.pk):
        gone = set(str(pk) for pk in FinanceEntry.objects.filter(
            removed_at__isnull=False).values_list("pk", flat=True))
        assert gone == set(plain), "only the ones in an unlocked month, and nothing held"
        assert set(FinanceEntry.objects.filter(pk__in=plain).values_list(
            "remove_reason", flat=True)) == {"Entered twice"}
        record = AuditEvent.objects.get(verb="finance.entries_removed")
        assert (record.payload["count"], record.payload["reason"]) == (2, "Entered twice")
        assert AuditEvent.objects.filter(verb="finance.entry_removed").count() == 2
    assert get(api, ff, B).json()[0]["reason"] == "Entered twice"
    # Removed entries are not chosen again.
    assert post(api, ff, B, {"action": "remove", "entries": plain,
                             "preview": True}).status_code == 404


@pytest.mark.django_db
def test_a_bulk_change_refuses_what_is_not_a_choice(three, ff, api):
    meals = three["cat"]["Meals"]["id"]
    for body in ({"action": "archive", "entries": three["ids"]},
                 {"action": "recategorize", "entries": three["ids"]},
                 {"action": "recategorize", "entries": [], "category": meals},
                 {"action": "recategorize", "entries": "all", "category": meals},
                 {"action": "recategorize", "entries": ["not-an-id"], "category": meals}):
        assert post(api, ff, B, {**body, "preview": True}).status_code == 400, body
    missing = post(api, ff, B, {"action": "remove", "preview": True, "entries": [
        *three["ids"], "00000000-0000-4000-8000-000000000000"]})
    assert missing.status_code == 404
    patch(api, ff, f"{C}{meals}/", {"archived": True})
    archived = post(api, ff, B, {"action": "recategorize", "entries": three["ids"],
                                 "category": meals, "preview": True})
    assert archived.status_code == 400 and "in use" in archived.json()["detail"]


@pytest.mark.django_db
def test_several_ticks_at_once_are_recorded_and_one_is_not(books, ff, api):          # noqa: F811
    modules.set_enabled(books["tenant"], modules.BOOKKEEPING, True, actor=ff.user)
    ids = [add(api, ff, books, "expense", cents, on(PRIOR, 5), "Travel").json()["id"]
           for cents in (1000, 2000, 3000)]
    rec = begin(api, ff, books, "bank", PRIOR, OPENING - 6000).json()
    url = f"{RC}{rec['id']}/tick/"
    post(api, ff, url, {"entries": ids[:1]})
    post(api, ff, url, {"entries": ids[1:]})
    post(api, ff, url, {"all": True, "cleared": False})
    with tenant_context(books["tenant"].pk):
        events = [(e.verb.removeprefix("finance."), e.payload["count"], e.payload["everything"])
                  for e in AuditEvent.objects.filter(
                      verb__in=("finance.reconciliation_ticked",
                                "finance.reconciliation_unticked")).order_by("created_at")]
    assert events == [("reconciliation_ticked", 2, False),
                      ("reconciliation_unticked", 3, True)]
    assert json.dumps(events) and end(PRIOR)
