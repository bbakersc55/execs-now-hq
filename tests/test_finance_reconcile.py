"""P6 M1, the second stop (`docs/p6_m1_reconciliation_month_close.md`):
reconciliation, month close, guided mode and "Explain this step".

1. Practice isolation and role boundaries on every new route.
2. Reconciling: the arithmetic, finishing, carrying forward, transfers,
   imported lines, what a cleared entry keeps.
3. Closing: the checklist, the order, the lock, reopening.
4. The lock typed before month close existed.
5. Guided mode and "Explain this step".
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.finance import explain, reconcile, services
from apps.finance.disclaimer import DISCLAIMER
from apps.finance.models import (
    FinanceAccount, FinanceCleared, FinanceEntry, FinanceGuide, FinanceMonthClose,
    FinanceReconciliation, FinanceSettings,
)
from apps.tenancy import modules
from apps.tenancy.context import tenant_context
from apps.tenancy.models import AiCall, AuditEvent

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import ContactFactory
from .test_client_invoicing import (  # noqa: F401  (fixtures and helpers)
    TOTAL, a_client, acme, call, ecc, get, patch, post, ready_to_bill, sent,
)
from .test_finance_books import A, C, E, R, add, books  # noqa: F401
from .test_finance_chart import kept  # noqa: F401
from .test_finance_import import SIGNED, decide, dry, rows_of  # noqa: F401
from .test_platform_practices import platform_owner, practices  # noqa: F401

RC = "/api/finance-reconcile/"
M = "/api/finance-months/"
S = "/api/finance-settings/"

TODAY = timezone.localdate()
THIS = TODAY.replace(day=1)
LAST = (THIS - timedelta(days=1)).replace(day=1)
PRIOR = (LAST - timedelta(days=1)).replace(day=1)
OPENING = 1_000_000            # the `books` fixture's bank account
OWED = 50_000                  # and what its card owed


def on(month: date, day: int) -> str:
    return month.replace(day=day).isoformat()


def end(month: date) -> str:
    return reconcile.month_end(month).isoformat()


def ym(month: date) -> str:
    return month.isoformat()[:7]


def begin(api, ff, books, account, month, balance, **more):          # noqa: F811
    return post(api, ff, RC, {"account": books[account]["id"], "statement_on": end(month),
                              "statement_balance_cents": balance, **more})


def reconciled(api, ff, books, account, month, balance):          # noqa: F811
    """Start one, tick everything through the statement date, and finish."""
    rec = begin(api, ff, books, account, month, balance)
    assert rec.status_code == 201, rec.content
    url = f"{RC}{rec.json()['id']}/"
    assert post(api, ff, url + "tick/", {"all": True}).status_code == 200
    done = post(api, ff, url + "finish/")
    assert done.status_code == 200, done.content
    return done.json()


def close_month(api, ff, books, month, bank, card):          # noqa: F811
    reconciled(api, ff, books, "bank", month, bank)
    reconciled(api, ff, books, "card", month, card)
    closed = post(api, ff, f"{M}{ym(month)}/close/")
    assert closed.status_code == 200, closed.content
    return closed.json()


def new_calls(books, rec_id, entry_id):          # noqa: F811
    return [
        ("get", RC, None),
        ("post", RC, {"account": books["card"]["id"], "statement_on": end(PRIOR),
                      "statement_balance_cents": OWED}),
        ("get", f"{RC}{rec_id}/", None),
        ("patch", f"{RC}{rec_id}/", {"statement_balance_cents": 5}),
        ("post", f"{RC}{rec_id}/tick/", {"entries": [entry_id]}),
        ("post", f"{RC}{rec_id}/tick/", {"all": True, "cleared": False}),
        ("post", f"{RC}{rec_id}/place/", {"entry": entry_id}),
        ("post", f"{RC}{rec_id}/finish/", {}),
        ("post", f"{RC}{rec_id}/reopen/", {"reason": "Because"}),
        ("get", f"{RC}{rec_id}/report/", None),
        ("delete", f"{RC}{rec_id}/", None),
        ("post", RC + "guided/", {"on": False}),
        ("get", RC + "explain/", None),
        ("post", RC + "explain/", {"step": 5, "reconciliation": rec_id}),
        ("get", f"{M}{ym(PRIOR)}/", None),
        ("post", f"{M}{ym(PRIOR)}/close/", {}),
        ("post", f"{M}{ym(PRIOR)}/reopen/", {"reason": "Because", "preview": True}),
        ("post", f"{M}{ym(PRIOR)}/reopen/", {"reason": "Because"}),
        ("patch", f"{A}{books['bank']['id']}/", {"reconciled_monthly": False}),
    ]


def state(tenant) -> str:
    with tenant_context(tenant.pk):
        return json.dumps({
            "recs": list(FinanceReconciliation.objects.order_by("created_at").values(
                "pk", "state", "statement_balance_cents", "statement_on")),
            "cleared": FinanceCleared.objects.count(),
            "closes": list(FinanceMonthClose.objects.values("month", "reopened_at")),
            "guides": FinanceGuide.objects.count(),
            "lock": FinanceSettings.objects.values_list("locked_through", flat=True).first(),
            "accounts": list(FinanceAccount.objects.order_by("created_at").values(
                "pk", "reconciled_monthly", "reconciling_from")),
            "entries": list(FinanceEntry.objects.order_by("created_at").values(
                "pk", "account_id", "removed_at")),
            "audit": AuditEvent.objects.filter(verb__startswith="finance.").count(),
            "ai": AiCall.objects.count(),
        }, default=str, sort_keys=True)


@pytest.fixture
def started(kept, ff, api):          # noqa: F811
    """One expense in the bank two months ago, and its reconciliation begun."""
    entry = add(api, ff, kept, "expense", 12_500, on(PRIOR, 10), "Travel",
                description="SECRET-TRIP").json()
    rec = begin(api, ff, kept, "bank", PRIOR, OPENING - 12_500).json()
    return {**kept, "entry": entry, "rec": rec}


# ============================================== isolation and role boundaries

@pytest.mark.django_db
def test_tenant_isolation_another_practice_reaches_no_reconciliation_or_close(
        started, ff, tenant_b, api):
    other = _member(tenant_b, "FF")
    modules.set_enabled(tenant_b, modules.BOOKKEEPING, True, actor=other.user)
    before = state(started["tenant"])
    # Their own grid is their own: no account, no month of ours.
    grid = get(api, other, RC).json()
    assert grid["accounts"] == [] and grid["locked_through"] is None
    for method, url, body in new_calls(started, started["rec"]["id"], started["entry"]["id"]):
        response = call(api.as_(other), method, url, body)
        assert b"SECRET-TRIP" not in response.content and b"Checking" not in response.content
        if started["rec"]["id"] in url or started["bank"]["id"] in url \
                or method == "post" and url == RC:
            assert response.status_code == 404, (method, url)
    assert state(started["tenant"]) == before
    # Their own reconciliation cannot clear an entry of ours, by id or in a total.
    theirs = post(api, other, A, {"name": "Their bank", "opening_on": on(PRIOR, 1),
                                  "opening_balance_cents": 700}).json()
    rec = post(api, other, RC, {"account": theirs["id"], "statement_on": end(PRIOR),
                                "statement_balance_cents": 700}).json()
    refused = post(api, other, f"{RC}{rec['id']}/tick/",
                   {"entries": [started["entry"]["id"]]})
    assert refused.status_code == 404
    everything = post(api, other, f"{RC}{rec['id']}/tick/", {"all": True}).json()
    assert everything["lines"] == [] and everything["cleared_out_cents"] == 0
    assert everything["difference_cents"] == 0
    assert state(started["tenant"]) == before


@pytest.mark.django_db
def test_tenant_isolation_the_platform_owner_reaches_none_of_it(
        started, platform_owner, api):          # noqa: F811
    client = practices(api, platform_owner)
    before = state(started["tenant"])
    for method, url, body in new_calls(started, started["rec"]["id"], started["entry"]["id"]):
        response = call(client, method, url, body)
        assert response.status_code in (403, 404), (method, url)
        assert b"SECRET-TRIP" not in response.content
    assert state(started["tenant"]) == before
    # And the module switch returns nothing from inside the practice.
    listed = json.dumps(client.get("/api/platform/practices").json())
    assert "SECRET-TRIP" not in listed and "Checking" not in listed \
        and "locked_through" not in listed and "reconcil" not in listed.lower()


@pytest.mark.django_db
def test_role_boundaries_reconciling_and_closing_are_the_practice_owners(
        started, ff, cf, va, fcc, ecc, api, fake_claude):
    before = state(started["tenant"])
    for who, status in ((va, 403), (cf, 403), (fcc, 404), (ecc, 404)):
        for method, url, body in new_calls(started, started["rec"]["id"],
                                           started["entry"]["id"]):
            response = call(api.as_(who), method, url, body)
            assert response.status_code == status, (who.role, method, url)
            assert b"SECRET-TRIP" not in response.content
            assert b"12500" not in response.content
    assert state(started["tenant"]) == before, "nothing changed, not even an audit row"
    assert fake_claude.requests == [], "and nobody else's press reached Claude"


@pytest.mark.django_db
def test_a_practice_without_the_module_gets_404_and_keeps_typing_its_lock(
        books, ff, api, fake_claude):          # noqa: F811
    entry = add(api, ff, books, "expense", 12_500, on(PRIOR, 10), "Travel").json()
    before = state(books["tenant"])
    for method, url, body in new_calls(books, "00000000-0000-0000-0000-000000000000",
                                       entry["id"]):
        assert call(api.as_(ff), method, url, body).status_code == 404, (method, url)
    assert state(books["tenant"]) == before and fake_claude.requests == []
    # What P5 gave every practice stays: the lock is still typed (M1-1).
    locked = post(api, ff, S, {"locked_through": end(PRIOR)})
    assert locked.status_code == 200 and locked.json()["locked_through"] == end(PRIOR)
    refused = add(api, ff, books, "expense", 100, on(PRIOR, 3), "Travel")
    assert refused.status_code == 409 and "finance settings" in refused.json()["detail"]


# =============================================================== reconciling

@pytest.mark.django_db
def test_the_difference_is_the_arithmetic_for_a_bank_account(kept, ff, api):          # noqa: F811
    fee = add(api, ff, kept, "income", 200_000, on(PRIOR, 5), "Client fees").json()
    trip = add(api, ff, kept, "expense", 30_000, on(PRIOR, 10), "Travel").json()
    check = add(api, ff, kept, "expense", 4_500, on(PRIOR, 28), "Meals",
                description="Check 1041").json()
    add(api, ff, kept, "expense", 999, on(LAST, 2), "Meals")       # after the statement
    statement = OPENING + 200_000 - 30_000
    rec = begin(api, ff, kept, "bank", PRIOR, statement)
    assert rec.status_code == 201
    rec = rec.json()
    url = f"{RC}{rec['id']}/"
    assert rec["month"] == ym(PRIOR) and rec["state"] == "open" and rec["first"] is True
    assert [line["id"] for line in rec["lines"]] == [fee["id"], trip["id"], check["id"]]
    assert all(not line["cleared"] and not line["carried"] for line in rec["lines"])
    # Statement − (starting + cleared in − cleared out).
    assert (rec["starting_balance_cents"], rec["cleared_in_cents"],
            rec["cleared_out_cents"]) == (OPENING, 0, 0)
    assert rec["difference_cents"] == statement - OPENING == 170_000

    one = post(api, ff, url + "tick/", {"entries": [fee["id"]]}).json()
    assert one["cleared_in_cents"] == 200_000 and one["difference_cents"] == -30_000
    # Finishing is refused at any difference but zero, and says the difference.
    refused = post(api, ff, url + "finish/")
    assert refused.status_code == 409 and "-$300.00" in refused.json()["detail"]
    # The first of the four usual causes: an unticked entry of exactly that amount.
    assert one["hints"][0] == {"kind": "untick", "entry": trip["id"],
                               "text": one["hints"][0]["text"]}

    two = post(api, ff, url + "tick/", {"entries": [trip["id"]]}).json()
    assert (two["cleared_out_cents"], two["expected_cents"], two["difference_cents"]) == \
        (30_000, statement, 0)
    assert two["hints"] == []
    # Unticking puts the difference back; "tick all" and "untick all" do what they say.
    assert post(api, ff, url + "tick/", {"entries": [trip["id"]], "cleared": False}) \
        .json()["difference_cents"] == -30_000
    assert post(api, ff, url + "tick/", {"all": True}).json()["difference_cents"] == 4_500
    assert post(api, ff, url + "tick/", {"all": True, "cleared": False}) \
        .json()["cleared_in_cents"] == 0
    post(api, ff, url + "tick/", {"entries": [fee["id"], trip["id"]]})

    done = post(api, ff, url + "finish/")
    assert done.status_code == 200
    done = done.json()
    assert done["state"] == "finished" and done["finished_by"] == ff.user.full_name
    assert done["finished_at"]
    # Finished: nothing about it changes without reopening.
    for method, path, body in (("post", "tick/", {"entries": [check["id"]]}),
                               ("patch", "", {"statement_balance_cents": 1}),
                               ("post", "finish/", {}), ("delete", "", None)):
        assert call(api.as_(ff), method, url + path, body).status_code == 409, path
    with tenant_context(kept["tenant"].pk):
        verbs = list(AuditEvent.objects.filter(verb__startswith="finance.reconciliation")
                     .order_by("created_at").values_list("verb", flat=True))
    # Started and finished; and each time several were ticked or unticked at once.
    assert verbs[0] == "finance.reconciliation_started"
    assert verbs[-1] == "finance.reconciliation_finished"
    assert set(verbs[1:-1]) == {"finance.reconciliation_ticked",
                                "finance.reconciliation_unticked"}

    # The report a CPA asks for.
    report = get(api, ff, url + "report/").json()
    assert report["statement_balance_cents"] == statement
    assert [row["id"] for row in report["cleared"]] == [fee["id"], trip["id"]]
    assert [row["id"] for row in report["outstanding"]] == [check["id"]]
    assert report["outstanding_out_cents"] == 4_500 and report["disclaimer"] == DISCLAIMER
    assert report["finished_by"] == ff.user.full_name

    # Unticked entries carry forward, once; the next one starts where this ended.
    late = add(api, ff, kept, "expense", 2_000, on(LAST, 12), "Meals").json()
    nxt = begin(api, ff, kept, "bank", LAST, statement - 4_500 - 999 - 2_000).json()
    assert nxt["starting_balance_cents"] == statement and nxt["first"] is False
    carried = [line for line in nxt["lines"] if line["carried"]]
    assert [line["id"] for line in carried] == [check["id"]]
    assert [line["id"] for line in nxt["lines"]].count(check["id"]) == 1
    assert fee["id"] not in [line["id"] for line in nxt["lines"]], "cleared: not asked again"
    assert late["id"] in [line["id"] for line in nxt["lines"]]
    after = post(api, ff, f"{RC}{nxt['id']}/tick/", {"all": True}).json()
    assert after["difference_cents"] == 0
    # Something that is not an entry at all is refused in words, not with an error.
    assert post(api, ff, f"{RC}{nxt['id']}/tick/",
                {"entries": ["not-an-id"]}).status_code == 400
    # An entry an earlier statement cleared cannot be ticked again.
    assert post(api, ff, f"{RC}{nxt['id']}/tick/",
                {"entries": [fee["id"]]}).status_code == 404


@pytest.mark.django_db
def test_a_card_is_what_is_owed_and_a_transfer_clears_separately_in_each_account(
        kept, ff, api):          # noqa: F811
    charge = add(api, ff, kept, "expense", 12_000, on(PRIOR, 6), "Travel",
                 account="card").json()
    refund = add(api, ff, kept, "expense", 2_000, on(PRIOR, 9), "Travel", account="card",
                 direction="in").json()
    paid = post(api, ff, E, {"kind": "transfer", "amount_cents": OWED,
                             "on_date": on(PRIOR, 20), "account": kept["bank"]["id"],
                             "to_account": kept["card"]["id"]}).json()
    # Owed: what was owed, plus charges, less payments and credits.
    owed = OWED + 12_000 - 2_000 - OWED
    card = begin(api, ff, kept, "card", PRIOR, owed).json()
    ways = {line["id"]: line["way"] for line in card["lines"]}
    assert ways == {charge["id"]: "out", refund["id"]: "in", paid["id"]: "in"}
    assert card["difference_cents"] == owed - OWED
    card = post(api, ff, f"{RC}{card['id']}/tick/", {"all": True}).json()
    assert (card["cleared_in_cents"], card["cleared_out_cents"]) == (OWED + 2_000, 12_000)
    assert card["expected_cents"] == owed and card["difference_cents"] == 0
    assert post(api, ff, f"{RC}{card['id']}/finish/").status_code == 200

    # The same transfer, from the bank's side: still to be ticked there.
    bank = begin(api, ff, kept, "bank", PRIOR, OPENING - OWED).json()
    assert [(line["id"], line["way"], line["cleared"]) for line in bank["lines"]] == \
        [(paid["id"], "out", False)]
    assert bank["difference_cents"] == -OWED
    bank = post(api, ff, f"{RC}{bank['id']}/tick/", {"entries": [paid["id"]]}).json()
    assert bank["difference_cents"] == 0
    with tenant_context(kept["tenant"].pk):
        assert FinanceCleared.objects.filter(entry_id=paid["id"]).count() == 2


@pytest.mark.django_db
def test_the_usual_causes_of_a_difference_are_found_by_arithmetic(kept, ff, api):          # noqa: F811
    wrong = add(api, ff, kept, "income", 7_000, on(PRIOR, 5), "Client fees").json()
    add(api, ff, kept, "expense", 5_400, on(PRIOR, 8), "Meals")
    # The statement shows 7,000 going out and 45.00, where the books have it
    # coming in and 54.00.
    rec = begin(api, ff, kept, "bank", PRIOR, OPENING - 7_000 - 4_500).json()
    rec = post(api, ff, f"{RC}{rec['id']}/tick/", {"all": True}).json()
    assert rec["difference_cents"] == -14_000 + 900
    assert [hint["kind"] for hint in rec["hints"]] == ["missing"]
    half = patch(api, ff, f"{RC}{rec['id']}/",
                 {"statement_balance_cents": OPENING + 7_000 - 5_400 - 14_000}).json()
    assert half["difference_cents"] == -14_000
    assert [(h["kind"], h["entry"]) for h in half["hints"]] == \
        [("wrong_way", wrong["id"]), ("missing", None)]
    swapped = patch(api, ff, f"{RC}{rec['id']}/",
                    {"statement_balance_cents": OPENING + 7_000 - 4_500}).json()
    assert swapped["difference_cents"] == 900
    assert [h["kind"] for h in swapped["hints"]] == ["swapped", "missing"]


@pytest.mark.django_db
def test_reconciliations_of_an_account_go_month_by_month(kept, ff, api):          # noqa: F811
    assert begin(api, ff, kept, "bank", PRIOR, OPENING).status_code == 201
    # One at a time, one a month, and the next month next.
    again = begin(api, ff, kept, "bank", PRIOR, OPENING)
    assert again.status_code == 409 and "already has" in again.json()["detail"]
    waiting = begin(api, ff, kept, "bank", LAST, OPENING)
    assert waiting.status_code == 409 and "Finish" in waiting.json()["detail"]
    with tenant_context(kept["tenant"].pk):
        rec = FinanceReconciliation.objects.get()
    assert post(api, ff, f"{RC}{rec.pk}/finish/").status_code == 200
    skipped = post(api, ff, RC, {"account": kept["bank"]["id"],
                                 "statement_on": TODAY.isoformat(),
                                 "statement_balance_cents": OPENING})
    assert skipped.status_code == 409 and reconcile.month_name(LAST) in \
        skipped.json()["detail"]
    ahead = post(api, ff, RC, {"account": kept["card"]["id"],
                               "statement_on": (TODAY + timedelta(days=1)).isoformat(),
                               "statement_balance_cents": OWED})
    assert ahead.status_code == 400 and "future" in ahead.json()["detail"]
    # A statement is the month its date is in; another month is another one.
    assert patch(api, ff, f"{RC}{rec.pk}/", {"statement_on": on(LAST, 3)}).status_code == 409
    nxt = begin(api, ff, kept, "bank", LAST, OPENING).json()
    moved = patch(api, ff, f"{RC}{nxt['id']}/", {"statement_on": on(THIS, 1)})
    assert moved.status_code == 400 and reconcile.month_name(LAST) in moved.json()["detail"]
    # One started and never finished can be thrown away.
    assert call(api.as_(ff), "delete", f"{RC}{nxt['id']}/", None).status_code == 204
    grid = get(api, ff, RC).json()
    bank = next(row for row in grid["accounts"] if row["id"] == kept["bank"]["id"])
    assert bank["cells"][ym(PRIOR)]["state"] == "finished"
    assert bank["cells"][ym(LAST)]["state"] == "not_started"
    assert bank["next_month"] == ym(LAST)


@pytest.mark.django_db
def test_reconciling_may_begin_later_than_the_account_did(kept, ff, api):          # noqa: F811
    """M1-3: it asks once for that statement's starting balance, and entries
    before it are never asked about."""
    add(api, ff, kept, "expense", 40_000, on(PRIOR, 10), "Travel")       # before it began
    inside = add(api, ff, kept, "expense", 5_000, on(LAST, 10), "Travel").json()
    rec = begin(api, ff, kept, "bank", LAST, 955_000, starting_balance_cents=960_000)
    assert rec.status_code == 201
    rec = rec.json()
    assert rec["starting_balance_cents"] == 960_000 and rec["period_start"] == on(LAST, 1)
    assert [line["id"] for line in rec["lines"]] == [inside["id"]]
    done = post(api, ff, f"{RC}{rec['id']}/tick/", {"all": True}).json()
    assert done["difference_cents"] == 0
    grid = get(api, ff, RC).json()
    bank = next(row for row in grid["accounts"] if row["id"] == kept["bank"]["id"])
    assert bank["cells"][ym(PRIOR)]["state"] == "before"
    # Thrown away, the account is as it was: it can begin anywhere again.
    assert call(api.as_(ff), "delete", f"{RC}{rec['id']}/", None).status_code == 204
    with tenant_context(kept["tenant"].pk):
        assert FinanceAccount.objects.get(pk=kept["bank"]["id"]).reconciling_from is None


@pytest.mark.django_db
def test_lines_brought_in_by_the_bank_import_arrive_ticked(kept, ff, api):          # noqa: F811
    typed = add(api, ff, kept, "expense", 1_200, on(PRIOR, 3), "Meals",
                description="Typed in by hand").json()
    text = ("Date,Description,Amount,Balance\n"
            f"{PRIOR.replace(day=4):%m/%d/%Y},ADOBE *CREATIVE CLOUD,-59.99,9940.01\n"
            f"{PRIOR.replace(day=6):%m/%d/%Y},COFFEE BAR,-5.00,9935.01\n"
            f"{LAST.replace(day=2):%m/%d/%Y},COFFEE BAR,-7.00,9928.01\n")
    batch = dry(api, ff, kept, text)
    for row in batch["rows"]:
        decide(api, ff, batch, row, decision="entry", category=kept["cat"]["Meals"]["id"])
    assert post(api, ff, f"/api/finance-imports/{batch['id']}/commit/").status_code == 200

    rec = begin(api, ff, kept, "bank", PRIOR, OPENING - 5_999 - 500).json()
    by_text = {line["description"]: line for line in rec["lines"]}
    assert by_text["ADOBE *CREATIVE CLOUD"]["cleared"] and by_text["COFFEE BAR"]["cleared"]
    assert by_text["ADOBE *CREATIVE CLOUD"]["from_bank"] is True
    assert not by_text["Typed in by hand"]["cleared"], "only what the bank's file showed"
    assert rec["cleared_out_cents"] == 6_499 and rec["difference_cents"] == 0
    # The owner can untick any, and it stays unticked.
    coffee = by_text["COFFEE BAR"]["id"]
    post(api, ff, f"{RC}{rec['id']}/tick/", {"entries": [coffee], "cleared": False})
    again = get(api, ff, f"{RC}{rec['id']}/").json()
    assert not {line["id"]: line for line in again["lines"]}[coffee]["cleared"]
    # A file committed while a statement is being worked on: its lines arrive
    # ticked there too, and only its own.
    more = dry(api, ff, kept, "Date,Description,Amount,Balance\n"
               f"{PRIOR.replace(day=9):%m/%d/%Y},PARKING GARAGE,-18.00,9910.01\n")
    decide(api, ff, more, more["rows"][0], decision="entry",
           category=kept["cat"]["Meals"]["id"])
    assert post(api, ff, f"/api/finance-imports/{more['id']}/commit/").status_code == 200
    after = {line["description"]: line
             for line in get(api, ff, f"{RC}{rec['id']}/").json()["lines"]}
    assert after["PARKING GARAGE"]["cleared"] and not after["COFFEE BAR"]["cleared"]
    assert not after["Typed in by hand"]["cleared"] and typed["id"]


@pytest.mark.django_db
def test_an_invoice_payment_not_yet_placed_is_listed_and_placed_from_here(
        ready_to_bill, ff, api):
    modules.set_enabled(ready_to_bill, modules.BOOKKEEPING, True, actor=ff.user)
    bank = post(api, ff, A, {"name": "Checking", "kind": "bank",
                             "opening_balance_cents": OPENING,
                             "opening_on": on(PRIOR, 1)}).json()
    company, contact = a_client(ready_to_bill)
    invoice = sent(api, ff, company, contact)
    post(api, ff, f"/api/invoices/{invoice['id']}/payments/",
         {"amount_cents": TOTAL, "paid_on": TODAY.isoformat()})
    rec = post(api, ff, RC, {"account": bank["id"], "statement_on": TODAY.isoformat(),
                             "statement_balance_cents": OPENING + TOTAL}).json()
    assert rec["lines"] == [] and len(rec["unplaced"]) == 1
    assert rec["unplaced"][0]["amount_cents"] == TOTAL
    placed = post(api, ff, f"{RC}{rec['id']}/place/", {"entry": rec["unplaced"][0]["id"]})
    assert placed.status_code == 200
    placed = placed.json()
    assert placed["unplaced"] == [] and len(placed["lines"]) == 1
    assert post(api, ff, f"{RC}{rec['id']}/tick/", {"all": True}).json()[
        "difference_cents"] == 0
    assert post(api, ff, f"{RC}{rec['id']}/place/",
                {"entry": placed["lines"][0]["id"]}).status_code == 409


@pytest.mark.django_db
def test_a_cleared_entry_keeps_its_date_amount_account_and_direction(kept, ff, api):          # noqa: F811
    trip = add(api, ff, kept, "expense", 30_000, on(PRIOR, 10), "Travel").json()
    loose = add(api, ff, kept, "expense", 700, on(PRIOR, 12), "Meals").json()
    rec = begin(api, ff, kept, "bank", PRIOR, OPENING - 30_000).json()
    url = f"{RC}{rec['id']}/"
    post(api, ff, url + "tick/", {"all": True})
    # Ticked in one still open: a change that takes it out of the statement unticks it.
    moved = patch(api, ff, f"{E}{loose['id']}/", {"account": kept["card"]["id"]})
    assert moved.status_code == 200
    with tenant_context(kept["tenant"].pk):
        assert not FinanceCleared.objects.filter(entry_id=loose["id"]).exists()
    assert post(api, ff, url + "finish/").status_code == 200

    for body in ({"on_date": on(PRIOR, 11)}, {"amount_cents": 30_001},
                 {"account": kept["card"]["id"]}, {"direction": "in"},
                 {"kind": "income", "category": kept["cat"]["Client fees"]["id"]}):
        refused = patch(api, ff, f"{E}{trip['id']}/", body)
        assert refused.status_code == 409, body
        assert "Reopen that reconciliation" in refused.json()["detail"]
    removed = post(api, ff, f"{E}{trip['id']}/remove/", {"reason": "Mistake"})
    assert removed.status_code == 409
    # Its category, description and payee can still change while its month is open.
    fine = patch(api, ff, f"{E}{trip['id']}/",
                 {"description": "Flight to Tucson", "category": kept["cat"]["Meals"]["id"]})
    assert fine.status_code == 200 and fine.json()["category"]["name"] == "Meals"

    # Reopen: the practice owner, with a reason, audited.
    assert post(api, ff, url + "reopen/", {"reason": " "}).status_code == 400
    reopened = post(api, ff, url + "reopen/", {"reason": "The amount was wrong."})
    assert reopened.status_code == 200
    reopened = reopened.json()
    assert reopened["state"] == "open" and reopened["reopen_reason"] == "The amount was wrong."
    assert reopened["reopened_by"] == ff.user.full_name and reopened["can_discard"] is False
    with tenant_context(kept["tenant"].pk):
        event = AuditEvent.objects.get(verb="finance.reconciliation_reopened")
        assert event.payload["reason"] == "The amount was wrong." and event.actor == ff.user
    # Open again, the entry can change, and is unticked by a change that moves it out.
    changed = patch(api, ff, f"{E}{trip['id']}/", {"amount_cents": 30_500})
    assert changed.status_code == 200
    assert get(api, ff, url).json()["difference_cents"] == 500
    assert call(api.as_(ff), "delete", url, None).status_code == 409, "finished once: kept"


@pytest.mark.django_db
def test_a_cleared_line_is_not_removed_by_an_import_rollback_or_from_its_invoice(
        ready_to_bill, ff, api):
    tenant = ready_to_bill
    modules.set_enabled(tenant, modules.BOOKKEEPING, True, actor=ff.user)
    bank = post(api, ff, A, {"name": "Checking", "kind": "bank", "opening_on": on(PRIOR, 1),
                             "opening_balance_cents": OPENING}).json()
    kit = {"bank": bank, "cat": {row["name"]: row for row in get(api, ff, C).json()}}
    batch = dry(api, ff, kit, "Date,Description,Amount,Balance\n"
                f"{PRIOR.replace(day=6):%m/%d/%Y},COFFEE BAR,-5.00,9935.01\n")
    decide(api, ff, batch, batch["rows"][0], decision="entry",
           category=kit["cat"]["Meals"]["id"])
    post(api, ff, f"/api/finance-imports/{batch['id']}/commit/")
    company, contact = a_client(tenant)
    invoice = sent(api, ff, company, contact)
    paid = post(api, ff, f"/api/invoices/{invoice['id']}/payments/",
                {"amount_cents": TOTAL, "paid_on": on(PRIOR, 20)})
    assert paid.status_code in (200, 201)
    loose = get(api, ff, E + "?account=none").json()["entries"][0]
    patch(api, ff, f"{E}{loose['id']}/", {"account": bank["id"]})
    rec = post(api, ff, RC, {"account": bank["id"], "statement_on": end(PRIOR),
                             "statement_balance_cents": OPENING - 500 + TOTAL}).json()
    post(api, ff, f"{RC}{rec['id']}/tick/", {"all": True})
    assert post(api, ff, f"{RC}{rec['id']}/finish/").status_code == 200

    before = state(tenant)
    rolled = post(api, ff, f"/api/finance-imports/{batch['id']}/rollback/")
    assert rolled.status_code == 409 and "Reopen that reconciliation" in \
        rolled.json()["detail"]
    with tenant_context(tenant.pk):
        from apps.billing.models import ClientPayment

        payment = ClientPayment.objects.get()
    gone = post(api, ff, f"/api/invoices/{invoice['id']}/remove-payment/",
                {"payment": str(payment.pk), "reason": "Entered twice"})
    assert gone.status_code == 409 and "Reopen that reconciliation" in gone.json()["detail"]
    assert state(tenant) == before
    assert get(api, ff, f"/api/invoices/{invoice['id']}/").json()["status"] == "paid"


@pytest.mark.django_db
def test_only_the_newest_finished_reconciliation_reopens(kept, ff, api):          # noqa: F811
    first = reconciled(api, ff, kept, "bank", PRIOR, OPENING)
    second = reconciled(api, ff, kept, "bank", LAST, OPENING)
    refused = post(api, ff, f"{RC}{first['id']}/reopen/", {"reason": "A mistake"})
    assert refused.status_code == 409 and "newest" in refused.json()["detail"]
    assert get(api, ff, f"{RC}{first['id']}/").json()["cannot_reopen"]
    assert post(api, ff, f"{RC}{second['id']}/reopen/",
                {"reason": "A mistake"}).status_code == 200
    # An account's opening balance is what its first reconciliation started from.
    fixed = patch(api, ff, f"{A}{kept['bank']['id']}/", {"opening_balance_cents": 5})
    assert fixed.status_code == 409 and "reconciled" in fixed.json()["detail"]


@pytest.mark.django_db
def test_a_cash_account_is_left_out_of_the_close_unless_switched_in(kept, ff, api):          # noqa: F811
    cash = post(api, ff, A, {"name": "Petty cash", "kind": "cash", "opening_on": on(PRIOR, 1),
                             "opening_balance_cents": 20_000}).json()
    assert cash["reconciled_monthly"] is False and kept["bank"]["reconciled_monthly"] is True
    add(api, ff, kept, "expense", 100, on(PRIOR, 3), "Travel")
    grid = get(api, ff, RC).json()
    cells = next(row for row in grid["accounts"] if row["id"] == cash["id"])["cells"]
    assert cells[ym(PRIOR)]["state"] == "not_needed"
    names = get(api, ff, f"{M}{ym(PRIOR)}/").json()["checklist"][0]["detail"]
    assert "Petty cash" not in names and "Checking" in names
    # Reconciled to a count all the same, when the owner wants to.
    counted = post(api, ff, RC, {"account": cash["id"], "statement_on": end(PRIOR),
                                 "statement_balance_cents": 20_000})
    assert counted.status_code == 201 and counted.json()["difference_cents"] == 0
    assert counted.json()["lines"] == []
    switched = patch(api, ff, f"{A}{cash['id']}/", {"reconciled_monthly": True})
    assert switched.status_code == 200 and switched.json()["reconciled_monthly"] is True
    assert "Petty cash" in get(api, ff, f"{M}{ym(PRIOR)}/").json()["checklist"][0]["detail"]
    assert patch(api, ff, f"{A}{cash['id']}/",
                 {"reconciled_monthly": "yes"}).status_code == 400


@pytest.mark.django_db
def test_the_migration_leaves_cash_accounts_out_of_the_close(kept):          # noqa: F811
    from importlib import import_module

    from django.apps import apps as django_apps

    step = import_module("apps.finance.migrations.0004_reconciliation_and_close")
    with tenant_context(kept["tenant"].pk):
        cash = FinanceAccount.objects.create(tenant=kept["tenant"], name="Till", kind="cash",
                                             opening_on=PRIOR)
        assert cash.reconciled_monthly is True         # as the column's default adds it
        step.cash_is_not_reconciled_monthly(django_apps, None)
        assert dict(FinanceAccount.objects.values_list("kind", "reconciled_monthly")) == \
            {"bank": True, "card": True, "cash": False}


# ==================================================================== closing

def line(detail, code):
    return next(row for row in detail["checklist"] if row["code"] == code)


@pytest.mark.django_db
def test_each_checklist_line_ticks_itself_from_the_books(ready_to_bill, ff, api):
    tenant = ready_to_bill
    modules.set_enabled(tenant, modules.BOOKKEEPING, True, actor=ff.user)
    bank = post(api, ff, A, {"name": "Checking", "kind": "bank", "opening_on": on(PRIOR, 1),
                             "opening_balance_cents": OPENING}).json()
    cats = {row["name"]: row for row in get(api, ff, C).json()}
    kit = {"bank": bank, "cat": cats}
    url = f"{M}{ym(LAST)}/"

    def lines():
        return {row["code"]: row for row in get(api, ff, url).json()["checklist"]}

    start = lines()
    assert [row["code"] for row in get(api, ff, url).json()["checklist"]] == \
        ["reconciled", "categorized", "placed", "payees"]
    assert [start[c]["blocks"] for c in ("reconciled", "categorized", "placed", "payees")] \
        == [True, True, True, False]
    assert not start["reconciled"]["ok"] and "Checking" in start["reconciled"]["detail"]
    assert start["categorized"]["ok"] and start["placed"]["ok"] and start["payees"]["ok"]

    # 2. An income or expense entry without a category.
    bare = add(api, ff, kit, "expense", 900, on(LAST, 4)).json()
    assert (lines()["categorized"]["ok"], lines()["categorized"]["count"]) == (False, 1)
    assert "category=none" in lines()["categorized"]["link"]
    patch(api, ff, f"{E}{bare['id']}/", {"category": cats["Meals"]["id"]})
    assert lines()["categorized"]["ok"]
    # A transfer has no category and is not asked for one.
    card = post(api, ff, A, {"name": "Card", "kind": "card", "opening_on": on(PRIOR, 1)}).json()
    post(api, ff, E, {"kind": "transfer", "amount_cents": 100, "on_date": on(LAST, 5),
                      "account": bank["id"], "to_account": card["id"]})
    assert lines()["categorized"]["ok"]

    # 3. A payment received in the month and not yet placed in an account.
    company, contact = a_client(tenant)
    invoice = sent(api, ff, company, contact)
    post(api, ff, f"/api/invoices/{invoice['id']}/payments/",
         {"amount_cents": TOTAL, "paid_on": on(LAST, 20)})
    assert (lines()["placed"]["ok"], lines()["placed"]["count"]) == (False, 1)
    loose = get(api, ff, E + "?account=none").json()["entries"][0]
    patch(api, ff, f"{E}{loose['id']}/", {"account": bank["id"]})
    assert lines()["placed"]["ok"]

    # 4. Paid to contractors with nobody named: a warning, not a block.
    paid = add(api, ff, kit, "expense", 50_000, on(LAST, 25), "Associates").json()
    assert (lines()["payees"]["ok"], lines()["payees"]["count"]) == (False, 1)
    person = ContactFactory(tenant=tenant, first_name="Pat", last_name="Lee")
    patch(api, ff, f"{E}{paid['id']}/", {"payee_contact": str(person.pk)})
    assert lines()["payees"]["ok"]
    patch(api, ff, f"{E}{paid['id']}/", {"payee_contact": None})
    assert not lines()["payees"]["ok"], "and it unticks when the books change"

    # 1. Every account set to "reconciled each month" has a finished one in the month.
    for account, opening in ((bank, OPENING), (card, 0)):
        rec = post(api, ff, RC, {"account": account["id"], "statement_on": end(PRIOR),
                                 "statement_balance_cents": opening}).json()
        post(api, ff, f"{RC}{rec['id']}/finish/")
    assert not lines()["reconciled"]["ok"], "the month before is not this month"
    balances = {bank["id"]: OPENING - 900 - 100 + TOTAL - 50_000, card["id"]: -100}
    recs = {}
    for account in (bank, card):
        rec = post(api, ff, RC, {"account": account["id"], "statement_on": end(LAST),
                                 "statement_balance_cents": balances[account["id"]]}).json()
        recs[account["id"]] = post(api, ff, f"{RC}{rec['id']}/tick/", {"all": True}).json()
        assert recs[account["id"]]["difference_cents"] == 0
    post(api, ff, f"{RC}{recs[bank['id']]['id']}/finish/")
    assert not lines()["reconciled"]["ok"] and "Card" in lines()["reconciled"]["detail"]
    post(api, ff, f"{RC}{recs[card['id']]['id']}/finish/")
    assert lines()["reconciled"]["ok"]


@pytest.mark.django_db
def test_the_three_blocking_lines_block_and_months_close_in_order(kept, ff, api):          # noqa: F811
    bare = add(api, ff, kept, "expense", 900, on(PRIOR, 4)).json()
    # Not reconciled, and one uncategorized: refused, by name.
    refused = post(api, ff, f"{M}{ym(PRIOR)}/close/")
    assert refused.status_code == 409
    assert "every account reconciled" in refused.json()["detail"]
    assert "nothing uncategorized" in refused.json()["detail"]
    reconciled(api, ff, kept, "bank", PRIOR, OPENING - 900)
    reconciled(api, ff, kept, "card", PRIOR, OWED)
    still = post(api, ff, f"{M}{ym(PRIOR)}/close/")
    assert still.status_code == 409 and "reconciled" not in still.json()["detail"]
    patch(api, ff, f"{E}{bare['id']}/", {"category": kept["cat"]["Meals"]["id"]})
    # The current month can be closed only after its last day.
    early = post(api, ff, f"{M}{ym(THIS)}/close/")
    assert early.status_code == 409 and "after its last day" in early.json()["detail"]

    closed = post(api, ff, f"{M}{ym(PRIOR)}/close/")
    assert closed.status_code == 200
    closed = closed.json()
    assert closed["state"] == "closed" and closed["history"][0]["closed_by"] == \
        ff.user.full_name
    assert closed["history"][0]["warnings"] == []
    grid = get(api, ff, RC).json()
    assert grid["locked_through"] == end(PRIOR) and grid["next_to_close"] == ym(LAST)
    assert grid["locked_by"]["month"] == reconcile.month_name(PRIOR)
    assert {m["month"]: m["state"] for m in grid["months"]}[ym(PRIOR)] == "closed"
    assert post(api, ff, f"{M}{ym(PRIOR)}/close/").status_code == 409, "already closed"
    with tenant_context(kept["tenant"].pk):
        event = AuditEvent.objects.get(verb="finance.month_closed")
        assert event.payload["locked_through"] == end(PRIOR) and event.actor == ff.user


@pytest.mark.django_db
def test_a_later_month_cannot_close_while_an_earlier_one_is_open(kept, ff, api):          # noqa: F811
    before_prior = (PRIOR - timedelta(days=1)).replace(day=1)
    for month in (before_prior, PRIOR, LAST):
        reconciled(api, ff, kept, "bank", month, OPENING)
        reconciled(api, ff, kept, "card", month, OWED)
    assert post(api, ff, f"{M}{ym(before_prior)}/close/").status_code == 200
    skipped = post(api, ff, f"{M}{ym(LAST)}/close/")
    assert skipped.status_code == 409
    assert f"Months close in order. {reconcile.month_name(PRIOR)} is next." == \
        skipped.json()["detail"]
    assert post(api, ff, f"{M}{ym(PRIOR)}/close/").status_code == 200
    assert post(api, ff, f"{M}{ym(LAST)}/close/").status_code == 200


@pytest.mark.django_db
def test_closing_locks_everything_the_lock_refuses(kept, ff, api):          # noqa: F811
    inside = add(api, ff, kept, "expense", 30_000, on(PRIOR, 10), "Travel").json()
    text = ("Date,Description,Amount,Balance\n"
            f"{LAST.replace(day=3):%m/%d/%Y},COFFEE BAR,-5.00,9935.01\n")
    batch = dry(api, ff, kept, text)
    decide(api, ff, batch, batch["rows"][0], decision="entry",
           category=kept["cat"]["Meals"]["id"])
    post(api, ff, f"/api/finance-imports/{batch['id']}/commit/")
    close_month(api, ff, kept, PRIOR, OPENING - 30_000, OWED)
    close_month(api, ff, kept, LAST, OPENING - 30_000 - 500, OWED)

    said = "Reopen the month under Finance, Reconcile"
    for response in (
            add(api, ff, kept, "expense", 100, on(PRIOR, 3), "Travel"),
            patch(api, ff, f"{E}{inside['id']}/", {"description": "Changed"}),
            post(api, ff, f"{E}{inside['id']}/remove/", {"reason": "Mistake"}),
            post(api, ff, E + "recategorize/", {"entries": [inside["id"]],
                                                "category": kept["cat"]["Meals"]["id"]}),
            post(api, ff, f"/api/finance-imports/{batch['id']}/rollback/")):
        assert response.status_code == 409 and said in response.json()["detail"]
    late = dry(api, ff, kept, "Date,Description,Amount,Balance\n"
               f"{LAST.replace(day=9):%m/%d/%Y},PARKING,-18.00,9910.01\n")
    decide(api, ff, late, late["rows"][0], decision="entry",
           category=kept["cat"]["Meals"]["id"])
    assert post(api, ff, f"/api/finance-imports/{late['id']}/commit/").status_code == 409
    # The open month is open.
    assert add(api, ff, kept, "expense", 100, on(THIS, 1), "Travel").status_code == 201
    # The lock is not typed any more: not on the route, and not past a close.
    for value in (end(PRIOR), None):
        typed = post(api, ff, S, {"locked_through": value})
        assert typed.status_code == 409 and "closing a month" in typed.json()["detail"]
    with tenant_context(kept["tenant"].pk):
        with pytest.raises(services.FinanceError):
            services.update_settings(kept["tenant"], actor=ff.user, locked_through=None)
        assert FinanceSettings.objects.get().locked_through == reconcile.month_end(LAST)
    assert get(api, ff, S).json()["locked_through"] == end(LAST)
    # A reconciliation of a closed month stays finished until the month is reopened.
    with tenant_context(kept["tenant"].pk):
        newest = FinanceReconciliation.objects.filter(
            account_id=kept["bank"]["id"]).order_by("-statement_on").first()
    stuck = post(api, ff, f"{RC}{newest.pk}/reopen/", {"reason": "A mistake"})
    assert stuck.status_code == 409 and "Reopen the month first" in stuck.json()["detail"]


@pytest.mark.django_db
def test_reopening_needs_a_reason_moves_the_lock_back_and_reopens_later_months(
        kept, ff, api):          # noqa: F811
    close_month(api, ff, kept, PRIOR, OPENING, OWED)
    close_month(api, ff, kept, LAST, OPENING, OWED)
    url = f"{M}{ym(PRIOR)}/reopen/"
    # It names the later months first, and says what reopening is not for.
    plan = post(api, ff, url, {"preview": True}).json()
    assert plan["also"] == [reconcile.month_name(LAST)]
    assert plan["note"].startswith("If a later statement showed a mistake in this month, "
                                   "add a correcting entry in the open month instead.")
    assert post(api, ff, url, {"reason": ""}).status_code == 400
    assert get(api, ff, RC).json()["locked_through"] == end(LAST), "a preview moves nothing"

    done = post(api, ff, url, {"reason": "September's refund was never entered."})
    assert done.status_code == 200
    done = done.json()
    assert done["reopened"] == [ym(PRIOR), ym(LAST)] and done["state"] == "open"
    assert done["history"][0]["reopen_reason"] == "September's refund was never entered."
    assert done["history"][0]["reopened_by"] == ff.user.full_name
    grid = get(api, ff, RC).json()
    states = {m["month"]: m["state"] for m in grid["months"]}
    assert states[ym(PRIOR)] == "open" and states[ym(LAST)] == "open"
    assert grid["locked_through"] is None and grid["next_to_close"] == ym(PRIOR)
    bank = next(row for row in grid["accounts"] if row["id"] == kept["bank"]["id"])
    assert bank["cells"][ym(LAST)]["state"] == "finished", "reconciliations stay finished"
    with tenant_context(kept["tenant"].pk):
        event = AuditEvent.objects.get(verb="finance.month_reopened")
        assert event.payload["months"] == [ym(PRIOR), ym(LAST)]
        assert event.payload["reason"] == "September's refund was never entered."
        assert event.actor == ff.user
    assert add(api, ff, kept, "expense", 100, on(PRIOR, 3), "Travel").status_code == 201
    assert post(api, ff, url, {"reason": "Again"}).status_code == 409, "it is not closed"


@pytest.mark.django_db
def test_a_month_closed_reopened_and_closed_again_shows_all_three(kept, ff, api):          # noqa: F811
    close_month(api, ff, kept, PRIOR, OPENING, OWED)
    post(api, ff, f"{M}{ym(PRIOR)}/reopen/", {"reason": "Closed by mistake."})
    assert post(api, ff, f"{M}{ym(PRIOR)}/close/").status_code == 200
    history = get(api, ff, f"{M}{ym(PRIOR)}/").json()["history"]
    assert [(bool(row["reopened_at"]), row["reopen_reason"]) for row in history] == \
        [(True, "Closed by mistake."), (False, "")]
    assert all(row["closed_by"] == ff.user.full_name for row in history)
    with tenant_context(kept["tenant"].pk):
        assert FinanceMonthClose.objects.count() == 2


@pytest.mark.django_db
def test_a_month_closes_with_the_1099_warning_showing_and_records_it(kept, ff, api):          # noqa: F811
    add(api, ff, kept, "expense", 50_000, on(PRIOR, 25), "Associates")
    closed = close_month(api, ff, kept, PRIOR, OPENING - 50_000, OWED)
    assert closed["history"][0]["warnings"] == [
        {"code": "payees", "label": "1099 payees named", "count": 1}]


# ============================================================== the old lock

@pytest.mark.django_db
def test_a_lock_typed_before_month_close_is_kept_and_is_not_closed(kept, ff, api):          # noqa: F811
    add(api, ff, kept, "expense", 100, on(PRIOR, 3), "Travel")
    add(api, ff, kept, "expense", 100, on(LAST, 3), "Travel")
    with tenant_context(kept["tenant"].pk):
        services.update_settings(kept["tenant"], actor=ff.user,
                                 locked_through=reconcile.month_end(PRIOR))
    grid = get(api, ff, RC).json()
    states = {m["month"]: m["state"] for m in grid["months"]}
    assert states[ym(PRIOR)] == "locked_before" and states[ym(LAST)] == "open"
    assert grid["locked_through"] == end(PRIOR) and grid["locked_by"] is None
    assert grid["next_to_close"] == ym(LAST)
    # Locked: it refuses what the lock refuses. Not closed: no close is on record.
    assert add(api, ff, kept, "expense", 100, on(PRIOR, 4), "Travel").status_code == 409
    detail = get(api, ff, f"{M}{ym(PRIOR)}/").json()
    assert detail["state"] == "locked_before" and detail["history"] == []
    with tenant_context(kept["tenant"].pk):
        assert not FinanceMonthClose.objects.exists()
    # The owner can leave it, and close on from there…
    close_month(api, ff, kept, LAST, OPENING - 200, OWED)
    assert get(api, ff, RC).json()["locked_through"] == end(LAST)
    # …or reopen back through it and close it properly.
    back = post(api, ff, f"{M}{ym(PRIOR)}/reopen/", {"reason": "To reconcile it properly."})
    assert back.status_code == 200 and back.json()["reopened"] == [ym(LAST)]
    assert get(api, ff, RC).json()["locked_through"] is None
    assert add(api, ff, kept, "expense", 100, on(PRIOR, 4), "Travel").status_code == 201


# ================================================================ guided mode

@pytest.mark.django_db
def test_walk_me_through_it_is_on_until_a_first_close_and_then_the_persons_own(
        kept, ff, api):          # noqa: F811
    assert get(api, ff, RC).json()["guided"] is True
    close_month(api, ff, kept, PRIOR, OPENING, OWED)
    assert get(api, ff, RC).json()["guided"] is False, "their first month is closed"
    assert post(api, ff, RC + "guided/", {"on": True}).json() == {"guided": True}
    assert get(api, ff, RC).json()["guided"] is True
    # Remembered per person: a second practice owner has their own.
    second = _member(kept["tenant"], "FF")
    assert get(api, second, RC).json()["guided"] is True
    post(api, second, RC + "guided/", {"on": False})
    assert get(api, second, RC).json()["guided"] is False
    assert get(api, ff, RC).json()["guided"] is True
    assert post(api, ff, RC + "guided/", {"on": "yes"}).status_code == 400


# =========================================================== explain this step

@pytest.fixture
def working(kept, ff, api):          # noqa: F811
    """A bank statement half ticked: one line cleared, two left."""
    fee = add(api, ff, kept, "income", 200_000, on(PRIOR, 5), "Client fees",
              description="Invoice 1042", counterparty="Acme Facilities",
              reference="ACH 55512").json()
    add(api, ff, kept, "expense", 30_000, on(PRIOR, 10), "Travel",
        description="Flight to Tucson", counterparty="United Airlines")
    add(api, ff, kept, "expense", 4_500, on(PRIOR, 28), "Meals", description="Check 1041",
        counterparty="Rioja")
    add(api, ff, kept, "expense", 77_700, on(PRIOR, 9), "Travel", account="card",
        description="OTHER-ACCOUNT-LINE")
    rec = begin(api, ff, kept, "bank", PRIOR, OPENING + 200_000 - 30_000).json()
    post(api, ff, f"{RC}{rec['id']}/tick/", {"entries": [fee["id"]]})
    return {**kept, "rec": rec}


@pytest.mark.django_db
def test_explain_sends_nothing_until_pressed_and_only_what_the_spec_lists(
        working, ff, api, fake_claude):
    fake_claude.reply = "The difference is the flight: tick it."
    # Opening the screen, the reconciliation and the button's price asks nothing.
    get(api, ff, RC)
    get(api, ff, f"{RC}{working['rec']['id']}/")
    price = get(api, ff, RC + "explain/").json()
    assert fake_claude.requests == []
    assert price["used_today"] == 0 and price["cap"] == 20 and price["refused"] == ""
    assert Decimal(price["estimate_usd"]) > 0
    before = state(working["tenant"])

    answer = post(api, ff, RC + "explain/", {"step": 5, "reconciliation": working["rec"]["id"]})
    assert answer.status_code == 200
    answer = answer.json()
    assert answer["text"] == "The difference is the flight: tick it."
    assert answer["disclaimer"] == DISCLAIMER and answer["used_today"] == 1
    assert Decimal(answer["cost_usd"]) > 0
    assert len(fake_claude.requests) == 1
    sent_ = fake_claude.requests[0]["messages"][0]["content"]
    assert sent_.splitlines() == [
        "STEP 5 OF 8: Get the difference to zero",
        "Account kind: Bank account",
        f"Statement ending date: {end(PRIOR)}",
        "Statement ending balance: $11,700.00",
        "Starting balance: $10,000.00",
        "Cleared money in: $2,000.00",
        "Cleared money out: $0.00",
        "Difference: -$300.00",
        "UNTICKED LINES (2):",
        f"- {on(PRIOR, 10)} | out $300.00 | Flight to Tucson",
        f"- {on(PRIOR, 28)} | out $45.00 | Check 1041",
    ]
    # No other account, no client, no payee, no one's contact details.
    everything = json.dumps(fake_claude.requests[0], default=str)
    for absent in ("OTHER-ACCOUNT-LINE", "Acme", "United", "Rioja", "ACH 55512",
                   "Checking", "4421", ff.user.email, working["tenant"].name):
        assert absent not in everything, absent
    system = fake_claude.requests[0]["system"]
    assert "ask your CPA" in system and "tax" in system and "cannot tick" in system

    # It changed nothing but its own `ai_call`.
    after = json.loads(state(working["tenant"]))
    assert after.pop("ai") == 1 and {**json.loads(before), "ai": 1} == {**after, "ai": 1}
    with tenant_context(working["tenant"].pk):
        row = AiCall.objects.get()
        assert (row.purpose, row.trigger, row.succeeded) == \
            ("finance_explain_step", "button", True)
        assert row.cost_usd == Decimal(answer["cost_usd"])


@pytest.mark.django_db
def test_explain_sends_the_unticked_lines_on_steps_four_and_five_only(
        working, ff, api, fake_claude):
    for step in range(1, 9):
        assert post(api, ff, RC + "explain/",
                    {"step": step, "reconciliation": working["rec"]["id"]}).status_code == 200
        text = fake_claude.requests[-1]["messages"][0]["content"]
        assert ("Flight to Tucson" in text) == (step in (4, 5)), step
        assert "Difference: -$300.00" in text
    # Without a reconciliation it is the step alone.
    post(api, ff, RC + "explain/", {"step": 8})
    assert fake_claude.requests[-1]["messages"][0]["content"] == \
        "STEP 8 OF 8: Close the month"
    for bad in (0, 9, "five", None, True):
        assert post(api, ff, RC + "explain/", {"step": bad}).status_code == 400
    assert len(fake_claude.requests) == 9


@pytest.mark.django_db
def test_explain_is_capped_at_twenty_a_day_and_by_the_monthly_budget(
        working, ff, api, fake_claude):
    for _ in range(20):
        assert post(api, ff, RC + "explain/", {"step": 1}).status_code == 200
    refused = post(api, ff, RC + "explain/", {"step": 1})
    assert refused.status_code == 409 and "today's 20" in refused.json()["detail"]
    said = get(api, ff, RC + "explain/").json()
    assert said["used_today"] == 20 and "tomorrow" in said["refused"] and said["resets_at"]
    assert len(fake_claude.requests) == 20
    # Yesterday's do not count against today.
    with tenant_context(working["tenant"].pk):
        AiCall.objects.update(created_at=timezone.now() - timedelta(days=2))
    assert get(api, ff, RC + "explain/").json()["refused"] == ""

    # Never past the practice's monthly AI budget, where one is set.
    tenant = working["tenant"]
    with tenant_context(tenant.pk):
        AiCall.objects.update(cost_usd=Decimal("0"))
    tenant.ai_monthly_budget_usd = Decimal("1.00")
    tenant.save()
    assert post(api, ff, RC + "explain/", {"step": 1}).status_code == 200
    with tenant_context(tenant.pk):
        AiCall.objects.filter(created_at__gte=timezone.now() - timedelta(hours=1)) \
            .update(cost_usd=Decimal("1.00"))
    over = post(api, ff, RC + "explain/", {"step": 1})
    assert over.status_code == 409 and "budget" in over.json()["detail"]
    assert len(fake_claude.requests) == 21


@pytest.mark.django_db
def test_explain_says_so_when_there_is_no_key_and_asks_nothing(working, ff, api, settings):
    settings.ANTHROPIC_API_KEY = ""
    said = get(api, ff, RC + "explain/").json()
    assert said["refused"].startswith("No Anthropic API key is set.")
    refused = post(api, ff, RC + "explain/", {"step": 3})
    assert refused.status_code == 409 and "No Anthropic API key" in refused.json()["detail"]
    with tenant_context(working["tenant"].pk):
        assert not AiCall.objects.exists()


def test_the_steps_the_screen_shows_are_the_steps_the_prompt_names():
    """`frontend/src/lib/finance.ts` holds the written steps; the prompt names
    a step by the same title."""
    import re
    from pathlib import Path

    assert list(explain.STEPS) == list(range(1, 9))
    assert explain.WITH_LINES == (4, 5) and explain.DAILY_CAP == 20
    source = (Path(__file__).resolve().parent.parent
              / "frontend/src/lib/finance.ts").read_text()
    steps = source.split("GUIDE_STEPS", 1)[1]
    titles = re.findall(r'^  \["([^"]+)",$', steps, flags=re.M)
    assert titles == list(explain.STEPS.values())
