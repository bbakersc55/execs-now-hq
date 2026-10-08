"""P5, the second stop — the import, rules, matching and 1099 tracking
(`docs/p5_finance_accounting.md` §4).

1. Practice isolation and role boundaries on every new route.
2. Reading a bank's file; the dry run writes nothing to the books.
3. No double counting: duplicates, invoice payments, the two sides of a transfer.
4. Rules; commit; rollback; the lock.
5. 1099 payees.
"""

from __future__ import annotations

import csv
import io
import json

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.finance.models import (
    FinanceEntry, FinanceImportBatch, FinanceImportProfile, FinanceImportRow, FinanceRule,
)
from apps.tenancy.context import tenant_context
from apps.tenancy.models import AuditEvent

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import ContactFactory
from .test_client_invoicing import (  # noqa: F401  (fixtures and helpers)
    TOTAL, a_client, acme, call, ecc, get, patch, post, ready_to_bill, sent,
)
from .test_finance_books import A, C, E, R, add, books, snapshot  # noqa: F401
from .test_platform_isolation import in_practices_area

I = "/api/finance-imports/"
RULES = "/api/finance-rules/"
P = "/api/finance-payees/"
SIGNED = {"date": "Date", "description": "Description", "amount": "Amount",
          "date_format": "%m/%d/%Y", "sign": "negative_is_out", "balance": "Balance"}

BANK = """Date,Description,Amount,Balance
10/01/2026,ADOBE *CREATIVE CLOUD,-59.99,9940.01
10/01/2026,COFFEE BAR,-5.00,9935.01
10/01/2026,COFFEE BAR,-5.00,9930.01
10/02/2026,DEPOSIT ACME FACILITIES,"6,800.00","16,730.01"
10/03/2026,PAYMENT TO CARD 1234,(500.00),"16,230.01"
10/04/2026,OWNER DRAW,"-3,000.00","13,230.01"
not a date,BROKEN LINE,-1.00,
10/05/2026,NO AMOUNT,,
"""


def upload(api, who, url, account, text, mapping=None, name="checking.csv"):
    body = {"file": SimpleUploadedFile(name, text if isinstance(text, bytes)
                                       else text.encode(), content_type="text/csv"),
            "account": account["id"]}
    if mapping is not None:
        body["mapping"] = json.dumps(mapping)
    return api.as_(who).post(url, body)


def dry(api, ff, books, text=BANK, account="bank", mapping=SIGNED):
    response = upload(api, ff, I + "dry-run/", books[account], text, mapping)
    assert response.status_code == 201, response.content
    return response.json()


def rows_of(batch):
    return {row["description"] or f"line {row['row_number']}": row for row in batch["rows"]}


def decide(api, ff, batch, row, **body):
    response = post(api, ff, f"{I}{batch['id']}/rows/{row['id']}/", body)
    assert response.status_code == 200, response.content
    return response.json()


def entries(api, ff, query=""):
    return get(api, ff, E + query).json()["entries"]


def import_calls(books, batch, row, rule):
    return [
        ("get", I, None), ("get", f"{I}{batch}/", None),
        ("post", f"{I}{batch}/rows/{row}/", {"decision": "ignore"}),
        ("post", f"{I}{batch}/commit/", {}), ("post", f"{I}{batch}/rollback/", {}),
        ("get", RULES, None),
        ("post", RULES, {"contains": "ADOBE", "treat_as": "ignore"}),
        ("patch", f"{RULES}{rule}/", {"is_active": False}),
        ("delete", f"{RULES}{rule}/", None),
        ("get", P, None), ("get", P + "export/?year=2026", None),
        ("post", P, {"contact": "00000000-0000-4000-8000-000000000000", "is_payee": True}),
    ]


# ============================================== isolation and role boundaries

@pytest.fixture
def an_import(books, ff, api):
    batch = dry(api, ff, books)
    rule = post(api, ff, RULES, {"contains": "COFFEE BAR", "treat_as": "category",
                                 "category": books["cat"]["Meals"]["id"]}).json()
    return {"books": books, "batch": batch, "rule": rule,
            "row": rows_of(batch)["ADOBE *CREATIVE CLOUD"]}


def import_state(tenant):
    with tenant_context(tenant.pk):
        return snapshot(tenant) + json.dumps({
            "batches": list(FinanceImportBatch.objects.order_by("created_at").values(
                "pk", "status")),
            "rows": list(FinanceImportRow.objects.order_by("row_number").values(
                "pk", "outcome", "category_id")),
            "rules": list(FinanceRule.objects.values("pk", "contains", "is_active")),
        }, default=str, sort_keys=True)


@pytest.mark.django_db
def test_tenant_isolation_another_practice_reaches_no_import_rule_or_payee(an_import, ff,
                                                                          tenant_b, api):
    books_ = an_import["books"]
    other = _member(tenant_b, "FF")
    theirs = post(api, other, A, {"name": "Their bank"}).json()
    before = import_state(books_["tenant"])
    assert get(api, other, I).json() == [] and get(api, other, RULES).json() == []
    assert get(api, other, P).json()["payees"] == []
    for method, url, body in import_calls(books_, an_import["batch"]["id"],
                                          an_import["row"]["id"], an_import["rule"]["id"]):
        response = call(api.as_(other), method, url, body)
        assert b"ADOBE" not in response.content or method == "post" and url == RULES
        if an_import["batch"]["id"] in url or an_import["rule"]["id"] in url:
            assert response.status_code == 404, (method, url)
    # An import of theirs cannot name an account of ours, nor a rule a category.
    assert upload(api, other, I + "dry-run/", books_["bank"], BANK, SIGNED).status_code == 404
    assert upload(api, other, I + "detect/", books_["bank"], BANK).status_code == 404
    assert post(api, other, RULES, {"contains": "ANYTHING", "treat_as": "category",
                                    "category": books_["cat"]["Meals"]["id"]}
                ).status_code == 404
    # Nor flag a contact of ours as a payee.
    with tenant_context(books_["tenant"].pk):
        person = ContactFactory(tenant=books_["tenant"])
    assert post(api, other, P, {"contact": str(person.pk), "is_payee": True}
                ).status_code == 404
    with tenant_context(tenant_b.pk):
        AuditEvent.objects.all().delete()
        FinanceRule.objects.all().delete()
    assert import_state(books_["tenant"]) == before
    assert upload(api, other, I + "dry-run/", theirs, BANK, SIGNED).status_code == 201


@pytest.mark.django_db
def test_tenant_isolation_the_platform_owner_reaches_no_import(an_import, api):
    books_ = an_import["books"]
    owner = _member(books_["tenant"], "FF")
    owner.user.is_platform_owner = True
    owner.user.save()
    client = in_practices_area(api.as_(owner))
    before = import_state(books_["tenant"])
    for method, url, body in import_calls(books_, an_import["batch"]["id"],
                                          an_import["row"]["id"], an_import["rule"]["id"]):
        assert call(client, method, url, body).status_code in (403, 404), (method, url)
    assert import_state(books_["tenant"]) == before


@pytest.mark.django_db
def test_role_boundaries_the_import_rules_and_payees_are_the_practice_owners(
        an_import, ff, cf, va, fcc, ecc, api):
    """An assistant runs the contact import. This one is not theirs, and no
    bank line is anywhere they can read."""
    books_ = an_import["books"]
    before = import_state(books_["tenant"])
    for who, status in ((va, 403), (cf, 403), (fcc, 404), (ecc, 404)):
        for method, url, body in import_calls(books_, an_import["batch"]["id"],
                                              an_import["row"]["id"],
                                              an_import["rule"]["id"]):
            response = call(api.as_(who), method, url, body)
            assert response.status_code == status, (who.role, method, url)
            assert b"ADOBE" not in response.content and b"COFFEE" not in response.content
        for url in (I + "dry-run/", I + "detect/"):
            assert upload(api, who, url, books_["bank"], BANK, SIGNED).status_code == status
    assert import_state(books_["tenant"]) == before
    for who in (va, cf):
        for url in ("/api/imports/", "/api/import-profiles/", "/api/activity/",
                    "/api/dashboard/", "/api/contacts/search/?q=ADOBE"):
            body = get(api, who, url).content.decode()
            assert "ADOBE" not in body and "checking.csv" not in body, (who.role, url)


@pytest.mark.django_db
def test_the_1099_flag_is_on_no_contact_payload(books, ff, va, api):
    with tenant_context(books["tenant"].pk):
        person = ContactFactory(tenant=books["tenant"], first_name="Casey",
                                last_name="Contractor")
    assert post(api, ff, P, {"contact": str(person.pk), "is_payee": True}).status_code == 200
    for who in (ff, va):
        for url in (f"/api/contacts/{person.pk}/", "/api/contacts/"):
            assert "1099" not in get(api, who, url).content.decode()


# ============================================================= reading a file

@pytest.mark.django_db
def test_detect_reads_the_columns_and_guesses_and_the_dry_run_remembers(books, ff, api):
    found = upload(api, ff, I + "detect/", books["bank"], BANK)
    assert found.status_code == 200
    body = found.json()
    assert body["header"] == ["Date", "Description", "Amount", "Balance"]
    assert body["lines"] == 8 and len(body["sample"]) == 5 and body["from_saved"] is False
    assert body["mapping"]["date"] == "Date" and body["mapping"]["amount"] == "Amount"
    assert body["mapping"]["balance"] == "Balance"
    with tenant_context(books["tenant"].pk):
        assert not FinanceImportBatch.objects.exists(), "detecting writes nothing"
    dry(api, ff, books, mapping={**SIGNED, "sign": "negative_is_out"})
    again = upload(api, ff, I + "detect/", books["bank"], BANK).json()
    assert again["from_saved"] is True and again["mapping"]["date_format"] == "%m/%d/%Y"
    # Saved for this account only; a file with other columns gets a fresh guess.
    assert upload(api, ff, I + "detect/", books["card"], BANK).json()["from_saved"] is False
    other = "Posted,Payee,Debit,Credit\n2026-10-01,ADOBE,59.99,\n"
    fresh = upload(api, ff, I + "detect/", books["bank"], other).json()
    assert fresh["from_saved"] is False
    assert (fresh["mapping"]["debit"], fresh["mapping"]["credit"],
            fresh["mapping"]["date_format"]) == ("Debit", "Credit", "%Y-%m-%d")


@pytest.mark.django_db
def test_the_dry_run_reads_every_line_and_writes_nothing_to_the_books(books, ff, api):
    before = snapshot(books["tenant"])
    batch = dry(api, ff, books)
    assert snapshot(books["tenant"]) == before, "not an entry, not an audit row"
    assert batch["status"] == "dry_run" and batch["counts"]["total"] == 8
    rows = batch["rows"]
    assert [(r["on_date"], r["amount_cents"], r["direction"]) for r in rows[:6]] == [
        ("2026-10-01", 5999, "out"), ("2026-10-01", 500, "out"), ("2026-10-01", 500, "out"),
        ("2026-10-02", 680000, "in"), ("2026-10-03", 50000, "out"),
        ("2026-10-04", 300000, "out")]
    assert [r["outcome"] for r in rows] == ["new"] * 6 + ["error", "error"]
    assert "not a date" in rows[6]["error"] and "no amount" in rows[7]["error"]
    assert rows[6]["raw"]["Description"] == "BROKEN LINE"
    assert batch["counts"]["needs_category"] == 6 and batch["counts"]["error"] == 2
    assert (batch["last_balance_cents"], batch["last_balance_on"]) == (1323001, "2026-10-04")
    assert get(api, ff, I).json()[0]["filename"] == "checking.csv"


@pytest.mark.django_db
@pytest.mark.parametrize("text, mapping, expected", [
    # Debit and credit in their own columns.
    ("Date,Memo,Debit,Credit\n2026-10-01,RENT,1500.00,\n2026-10-02,DEPOSIT,,250.5\n",
     {"date": "Date", "description": "Memo", "debit": "Debit", "credit": "Credit",
      "date_format": "%Y-%m-%d"}, [(150000, "out"), (25050, "in")]),
    # A card's file: a charge is a positive number.
    ("Date,Description,Amount\n10/01/26,HOTEL,212.40\n10/02/26,PAYMENT THANK YOU,-500\n",
     {"date": "Date", "description": "Description", "amount": "Amount",
      "date_format": "%m/%d/%y", "sign": "positive_is_out"},
     [(21240, "out"), (50000, "in")]),
    # Dollar signs, brackets, a trailing minus, and day first.
    ("Date,Description,Amount\n31/01/2026,A,$(12.00)\n01/02/2026,B,7.5-\n02/02/2026,C,\"$1,000\"\n",
     {"date": "Date", "description": "Description", "amount": "Amount",
      "date_format": "%d/%m/%Y"}, [(1200, "out"), (750, "out"), (100000, "in")]),
    ("Date,Description,Amount\n\"Oct 01, 2026\",A,-3\n",
     {"date": "Date", "description": "Description", "amount": "Amount",
      "date_format": "%b %d, %Y"}, [(300, "out")]),
])
def test_the_ways_a_bank_writes_dates_and_amounts(books, ff, api, text, mapping, expected):
    batch = dry(api, ff, books, text, mapping=mapping)
    assert [(r["amount_cents"], r["direction"]) for r in batch["rows"]] == expected
    assert all(r["outcome"] == "new" for r in batch["rows"])


@pytest.mark.django_db
def test_a_file_saved_by_excel_reads_and_a_file_that_is_not_a_statement_is_refused(
        books, ff, api):
    excel = "Date,Description,Amount\n10/01/2026,CAF\xc9 R\xd6STI,-5.00\n".encode("cp1252")
    plain = {**SIGNED, "balance": ""}
    assert dry(api, ff, books, excel, mapping=plain)["rows"][0]["description"] == "CAFÉ RÖSTI"
    bom = "﻿Date,Description,Amount\n10/01/2026,X,-5.00\n".encode("utf-8")
    assert dry(api, ff, books, bom, mapping=plain)["rows"][0]["amount_cents"] == 500
    refusals = {
        "10/01/2026,ADOBE,-59.99\n10/02/2026,X,-1\n": "name the columns",
        "Date,Description,Amount\n": "no lines under its header",
        "": "empty",
        "Date,Description,Amount\n" + "10/01/2026,X,-1\n" * 5001: "5,000 is the most",
    }
    for text, reason in refusals.items():
        refused = upload(api, ff, I + "dry-run/", books["bank"], text, plain)
        assert refused.status_code == 400 and reason in refused.json()["detail"], reason
    for bad in ({**SIGNED, "date": "When"}, {**SIGNED, "description": ""},
                {"date": "Date", "description": "Description", "date_format": "%m/%d/%Y"},
                {**SIGNED, "date_format": "%Y"}, "nonsense"):
        assert upload(api, ff, I + "dry-run/", books["bank"], BANK, bad).status_code == 400
    assert api.as_(ff).post(I + "dry-run/", {"account": books["bank"]["id"]}
                            ).status_code == 400
    with tenant_context(books["tenant"].pk):
        assert FinanceImportBatch.objects.count() == 2, "the two that read; no refused one"


# ============================================ deciding, and what commit writes

@pytest.fixture
def decided(books, ff, api):
    """The bank file, with every line decided as an owner would."""
    batch = dry(api, ff, books)
    rows = rows_of(batch)
    cat = books["cat"]
    batch = decide(api, ff, batch, rows["ADOBE *CREATIVE CLOUD"], decision="entry",
                   category=cat["Software and subscriptions"]["id"])
    for row in [r for r in batch["rows"] if r["description"] == "COFFEE BAR"]:
        batch = decide(api, ff, batch, row, decision="entry", category=cat["Meals"]["id"])
    batch = decide(api, ff, batch, rows["DEPOSIT ACME FACILITIES"], decision="entry",
                   category=cat["Client fees"]["id"])
    batch = decide(api, ff, batch, rows["PAYMENT TO CARD 1234"], decision="transfer",
                   other_account=books["card"]["id"])
    batch = decide(api, ff, batch, rows["OWNER DRAW"], decision="entry",
                   category=cat["Owner draw"]["id"])
    return {"books": books, "batch": batch}


@pytest.mark.django_db
def test_commit_writes_what_the_dry_run_showed_in_one_go(decided, ff, api):
    books_, batch = decided["books"], decided["batch"]
    assert batch["counts"]["needs_category"] == 0
    assert entries(api, ff) == [], "still nothing in the books"
    done = post(api, ff, f"{I}{batch['id']}/commit/")
    assert done.status_code == 200 and done.json()["status"] == "committed"
    made = {(e["description"], e["kind"], e["direction"], e["amount_cents"])
            for e in entries(api, ff)}
    assert made == {
        ("ADOBE *CREATIVE CLOUD", "expense", "out", 5999),
        ("COFFEE BAR", "expense", "out", 500),
        ("DEPOSIT ACME FACILITIES", "income", "in", 680000),
        ("PAYMENT TO CARD 1234", "transfer", "out", 50000),
        ("OWNER DRAW", "owner", "out", 300000)}
    listed = entries(api, ff)
    assert len(listed) == 6, "two identical coffees are two entries"
    assert all(e["source"] == "import" and e["account"] for e in listed)
    transfer = next(e for e in listed if e["kind"] == "transfer")
    assert (transfer["account"]["name"], transfer["to_account"]["name"]) == (
        "Checking", "Business card")
    # The books agree with the bank's own last balance, to the cent... less the
    # two lines that could not be read, which the batch says.
    view = get(api, ff, R + "balance/?as_of=2026-10-31").json()
    said = view["cash"][0]["bank_said"]
    assert (said["on"], said["cents"]) == ("2026-10-04", 1323001)
    assert said["books_cents"] == 1000000 - 5999 - 1000 + 680000 - 50000 - 300000
    assert said["difference_cents"] == said["books_cents"] - 1323001
    # A committed import's lines are fixed.
    row = get(api, ff, f"{I}{batch['id']}/").json()["rows"][0]
    assert post(api, ff, f"{I}{batch['id']}/rows/{row['id']}/",
                {"decision": "ignore"}).status_code == 409
    assert post(api, ff, f"{I}{batch['id']}/commit/").status_code == 409
    with tenant_context(books_["tenant"].pk):
        event = AuditEvent.objects.get(verb="finance.import_committed")
        assert event.payload["filename"] == "checking.csv" and event.actor_id == ff.user.pk
        assert AuditEvent.objects.filter(verb="finance.entry_added").count() == 6


@pytest.mark.django_db
def test_the_same_file_again_adds_nothing(decided, ff, api):
    post(api, ff, f"{I}{decided['batch']['id']}/commit/")
    again = dry(api, ff, decided["books"])
    assert [r["outcome"] for r in again["rows"]] == ["duplicate"] * 6 + ["error"] * 2
    assert post(api, ff, f"{I}{again['id']}/commit/").status_code == 200
    assert len(entries(api, ff)) == 6
    # An overlapping file adds only what is new, and a third coffee is a third.
    overlap = ("Date,Description,Amount,Balance\n10/01/2026,COFFEE BAR,-5.00,\n"
               "10/01/2026,COFFEE BAR,-5.00,\n10/01/2026,COFFEE BAR,-5.00,\n"
               "10/06/2026,PARKING,-12.00,\n")
    third = dry(api, ff, decided["books"], overlap)
    assert [r["outcome"] for r in third["rows"]] == ["duplicate", "duplicate", "new", "new"]
    # A duplicate is not something to decide about.
    assert post(api, ff, f"{I}{third['id']}/rows/{third['rows'][0]['id']}/",
                {"decision": "ignore"}).status_code == 409


@pytest.mark.django_db
def test_a_bank_id_marks_a_line_as_seen_whatever_its_wording(books, ff, api):
    mapping = {**SIGNED, "bank_id": "Id", "balance": ""}
    first = "Date,Description,Amount,Id\n10/01/2026,POS 1234 ADOBE,-59.99,TX-1\n"
    batch = dry(api, ff, books, first, mapping=mapping)
    post(api, ff, f"{I}{batch['id']}/commit/")
    reworded = "Date,Description,Amount,Id\n10/02/2026,ADOBE SYSTEMS INC,-59.99,TX-1\n"
    assert dry(api, ff, books, reworded, mapping=mapping)["rows"][0]["outcome"] == "duplicate"


@pytest.mark.django_db
def test_a_money_in_line_in_an_expense_category_is_a_refund(books, ff, api):
    card = ("Date,Description,Amount\n10/01/2026,HOTEL DENVER,212.40\n"
            "10/03/2026,HOTEL DENVER REFUND,-40.00\n")
    mapping = {"date": "Date", "description": "Description", "amount": "Amount",
               "date_format": "%m/%d/%Y", "sign": "positive_is_out"}
    batch = dry(api, ff, books, card, account="card", mapping=mapping)
    for row in batch["rows"]:
        batch = decide(api, ff, batch, row, decision="entry",
                       category=books["cat"]["Travel"]["id"])
    post(api, ff, f"{I}{batch['id']}/commit/")
    refund = next(e for e in entries(api, ff) if "REFUND" in e["description"])
    assert (refund["kind"], refund["direction"]) == ("expense", "in")
    report = get(api, ff, R + "pnl/?year=2026").json()
    travel = next(row for row in report["expenses"]["rows"] if row["name"] == "Travel")
    assert travel["total"] == 21240 - 4000 == report["expenses"]["total"]
    assert get(api, ff, E).json()["totals"]["expenses_cents"] == 17240
    # The card is owed the charge less the refund.
    view = get(api, ff, R + "balance/?as_of=2026-10-31").json()
    assert view["cards"][0]["amount_cents"] == 50000 + 21240 - 4000


# ====================================================== no double counting

@pytest.mark.django_db
def test_a_deposit_is_matched_to_the_invoice_payment_it_is(acme, ff, api):
    tenant = acme[0].tenant
    invoice = sent(api, ff, *acme)
    post(api, ff, f"/api/invoices/{invoice['id']}/payments/",
         {"amount_cents": TOTAL, "paid_on": "2026-10-01"})
    bank = post(api, ff, A, {"name": "Checking", "opening_on": "2026-01-01"}).json()
    books_ = {"bank": bank, "tenant": tenant}
    text = ("Date,Description,Amount\n10/02/2026,DEPOSIT ACME FACILITIES,6800.00\n"
            "10/02/2026,DEPOSIT SOMEONE ELSE,6800.00\n10/20/2026,DEPOSIT LATE,6800.00\n")
    batch = dry(api, ff, books_, text, mapping={**SIGNED, "balance": ""})
    first, second, late = batch["rows"]
    assert first["outcome"] == "invoice_payment"
    # Both sides are shown, so the match can be judged.
    assert first["matched"]["description"] == "Invoice INV-0001"
    assert first["matched"]["counterparty"] == "Acme Facilities"
    # One payment is matched once; and not to a deposit weeks away.
    assert second["outcome"] == "new" and late["outcome"] == "new"
    for row in (second, late):
        batch = decide(api, ff, batch, row, decision="ignore")
    assert post(api, ff, f"{I}{batch['id']}/commit/").status_code == 200
    listed = entries(api, ff)
    assert len(listed) == 1, "no second income entry"
    assert listed[0]["account"]["name"] == "Checking" and listed[0]["source"] == "invoice"
    assert get(api, ff, E).json()["totals"]["income_cents"] == TOTAL
    view = get(api, ff, R + "balance/?as_of=2026-10-31").json()
    assert view["unplaced_cents"] == 0 and view["cash"][0]["amount_cents"] == TOTAL
    # And the same file again sees the deposit as already there.
    again = dry(api, ff, books_, text, mapping={**SIGNED, "balance": ""})
    assert again["rows"][0]["outcome"] == "duplicate"
    with tenant_context(tenant.pk):
        assert AuditEvent.objects.filter(verb="finance.entry_matched").count() == 1


@pytest.mark.django_db
def test_a_proposed_match_can_be_declined_and_a_tax_split_payment_lands_whole(acme, ff, api):
    invoice = sent(api, ff, *acme, tax_cents=33333)
    post(api, ff, f"/api/invoices/{invoice['id']}/payments/",
         {"amount_cents": TOTAL + 33333, "paid_on": "2026-10-01"})
    bank = post(api, ff, A, {"name": "Checking", "opening_on": "2026-01-01"}).json()
    books_ = {"bank": bank}
    text = "Date,Description,Amount\n10/03/2026,DEPOSIT,7133.33\n"
    mapping = {**SIGNED, "balance": ""}
    declined = dry(api, ff, books_, text, mapping=mapping)
    assert declined["rows"][0]["outcome"] == "invoice_payment"
    batch = decide(api, ff, declined, declined["rows"][0], decision="not_a_match")
    assert batch["rows"][0]["outcome"] == "new" and batch["rows"][0]["matched"] is None
    assert post(api, ff, f"{I}{batch['id']}/rows/{batch['rows'][0]['id']}/",
                {"decision": "not_a_match"}).status_code == 409
    # Left as a dry run and never committed. A fresh one proposes it again.
    accepted = dry(api, ff, books_, text, mapping=mapping)
    post(api, ff, f"{I}{accepted['id']}/commit/")
    placed = entries(api, ff)
    assert {e["kind"] for e in placed} == {"income", "held"}
    assert all(e["account"]["name"] == "Checking" for e in placed), "fee and tax together"


@pytest.mark.django_db
def test_a_card_payment_seen_from_both_files_is_one_transfer(decided, ff, api):
    books_ = decided["books"]
    post(api, ff, f"{I}{decided['batch']['id']}/commit/")
    net = get(api, ff, R + "balance/?as_of=2026-10-31").json()["net_cents"]
    card = ("Date,Description,Amount\n10/04/2026,PAYMENT THANK YOU,-500.00\n"
            "10/05/2026,HOTEL,100.00\n")
    mapping = {"date": "Date", "description": "Description", "amount": "Amount",
               "date_format": "%m/%d/%Y", "sign": "positive_is_out"}
    batch = dry(api, ff, books_, card, account="card", mapping=mapping)
    payment, hotel = batch["rows"]
    assert payment["outcome"] == "transfer_match"
    assert payment["matched"]["description"] == "PAYMENT TO CARD 1234"
    batch = decide(api, ff, batch, hotel, decision="entry",
                   category=books_["cat"]["Travel"]["id"])
    post(api, ff, f"{I}{batch['id']}/commit/")
    transfers = [e for e in entries(api, ff) if e["kind"] == "transfer"]
    assert len(transfers) == 1, "not one from each file"
    after = get(api, ff, R + "balance/?as_of=2026-10-31").json()
    assert after["cards"][0]["amount_cents"] == 50000 - 50000 + 10000
    assert after["net_cents"] == net - 10000, "only the hotel changed anything"
    # Either file again finds its side already there.
    assert dry(api, ff, books_, card, account="card", mapping=mapping)["rows"][0][
        "outcome"] == "duplicate"
    assert rows_of(dry(api, ff, books_))["PAYMENT TO CARD 1234"]["outcome"] == "duplicate"


@pytest.mark.django_db
def test_nothing_is_written_if_the_books_moved_under_a_match(acme, ff, api):
    invoice = sent(api, ff, *acme)
    post(api, ff, f"/api/invoices/{invoice['id']}/payments/",
         {"amount_cents": TOTAL, "paid_on": "2026-10-01"})
    bank = post(api, ff, A, {"name": "Checking", "opening_on": "2026-01-01"}).json()
    text = ("Date,Description,Amount\n10/02/2026,DEPOSIT,6800.00\n"
            "10/02/2026,PARKING,-12.00\n")
    batch = dry(api, ff, {"bank": bank}, text, mapping={**SIGNED, "balance": ""})
    # Meanwhile the payment is placed by hand.
    entry = entries(api, ff)[0]
    patch(api, ff, f"{E}{entry['id']}/", {"account": bank["id"]})
    refused = post(api, ff, f"{I}{batch['id']}/commit/")
    assert refused.status_code == 409 and "Run the dry run again" in refused.json()["detail"]
    assert len(entries(api, ff)) == 1, "not even the parking: one transaction"
    assert get(api, ff, f"{I}{batch['id']}/").json()["status"] == "dry_run"


@pytest.mark.django_db
def test_two_dry_runs_of_one_file_cannot_both_be_committed(books, ff, api):
    text = "Date,Description,Amount\n10/01/2026,PARKING,-12.00\n10/01/2026,PARKING,-12.00\n"
    mapping = {**SIGNED, "balance": ""}
    first = dry(api, ff, books, text, mapping=mapping)
    second = dry(api, ff, books, text, mapping=mapping)
    assert post(api, ff, f"{I}{first['id']}/commit/").status_code == 200
    refused = post(api, ff, f"{I}{second['id']}/commit/")
    assert refused.status_code == 409 and "Run the dry run again" in refused.json()["detail"]
    assert len(entries(api, ff)) == 2, "the two lines, once"


# ====================================================================== rules

@pytest.mark.django_db
def test_a_choice_is_remembered_for_this_import_and_the_next(books, ff, api):
    batch = dry(api, ff, books)
    coffee = [r for r in batch["rows"] if r["description"] == "COFFEE BAR"]
    batch = decide(api, ff, batch, coffee[0], decision="entry",
                   category=books["cat"]["Meals"]["id"], remember="coffee bar")
    both = [r for r in batch["rows"] if r["description"] == "COFFEE BAR"]
    # The other coffee took it at once, and says which rule decided it.
    assert [r["category"]["name"] for r in both] == ["Meals", "Meals"]
    assert all(r["rule"]["contains"] == "coffee bar" for r in both)
    assert batch["counts"]["needs_category"] == 4
    batch = decide(api, ff, batch, rows_of(batch)["PAYMENT TO CARD 1234"],
                   decision="transfer", other_account=books["card"]["id"],
                   remember="PAYMENT TO CARD")
    batch = decide(api, ff, batch, rows_of(batch)["OWNER DRAW"], decision="ignore",
                   remember="OWNER DRAW")
    rules = get(api, ff, RULES).json()
    assert [(r["contains"], r["treat_as"]) for r in rules] == [
        ("coffee bar", "category"), ("PAYMENT TO CARD", "transfer"),
        ("OWNER DRAW", "ignore")]
    # Next month's file: decided before the owner touches it.
    november = ("Date,Description,Amount\n11/02/2026,Coffee Bar #2,-6.00\n"
                "11/03/2026,PAYMENT TO CARD 1234,-200.00\n11/04/2026,OWNER DRAW,-900.00\n"
                "11/05/2026,UNKNOWN,-1.00\n")
    nxt = dry(api, ff, books, november, mapping={**SIGNED, "balance": ""})["rows"]
    assert [(r["outcome"], (r["category"] or {}).get("name"),
             (r["other_account"] or {}).get("name")) for r in nxt] == [
        ("new", "Meals", None), ("transfer", None, "Business card"),
        ("ignore", None, None), ("new", None, None)]
    assert nxt[3]["rule"] is None


@pytest.mark.django_db
def test_commit_writes_what_was_shown_even_if_the_rules_changed_since(books, ff, api):
    rule = post(api, ff, RULES, {"contains": "ADOBE", "treat_as": "category",
                                 "category": books["cat"]["Software and subscriptions"]["id"]}
                ).json()
    batch = dry(api, ff, books)
    assert rows_of(batch)["ADOBE *CREATIVE CLOUD"]["category"]["name"] == \
        "Software and subscriptions"
    assert patch(api, ff, f"{RULES}{rule['id']}/",
                 {"category": books["cat"]["Travel"]["id"]}).status_code == 200
    for row in batch["rows"]:
        if row["outcome"] == "new" and not row["category"]:
            batch = decide(api, ff, batch, row, decision="ignore")
    post(api, ff, f"{I}{batch['id']}/commit/")
    adobe = entries(api, ff)[0]
    assert adobe["category"]["name"] == "Software and subscriptions"
    # The changed rule is what the next dry run uses.
    later = "Date,Description,Amount\n11/01/2026,ADOBE *CREATIVE CLOUD,-59.99\n"
    assert dry(api, ff, books, later, mapping={**SIGNED, "balance": ""})["rows"][0][
        "category"]["name"] == "Travel"


@pytest.mark.django_db
def test_rules_are_the_practices_own_to_list_change_and_delete(books, ff, api):
    cat = books["cat"]
    made = post(api, ff, RULES, {"contains": "  adobe  ", "treat_as": "category",
                                 "category": cat["Software and subscriptions"]["id"]})
    assert made.status_code == 201 and made.json()["contains"] == "adobe"
    for bad in ({"contains": "ab", "treat_as": "ignore"},              # matches too much
                {"contains": "x" * 121, "treat_as": "ignore"},
                {"contains": "uber", "treat_as": "category"},           # no category
                {"contains": "uber", "treat_as": "transfer"},           # no account
                {"contains": "uber", "treat_as": "guess"}, {"treat_as": "ignore"}):
        assert post(api, ff, RULES, bad).status_code == 400, bad
    other = post(api, ff, RULES, {"contains": "uber", "treat_as": "ignore"}).json()
    assert patch(api, ff, f"{RULES}{other['id']}/", {"contains": "ADOBE"}).status_code == 409
    off = patch(api, ff, f"{RULES}{made.json()['id']}/", {"is_active": False}).json()
    assert off["is_active"] is False
    text = "Date,Description,Amount\n10/01/2026,ADOBE,-59.99\n10/02/2026,UBER TRIP,-20\n"
    rows = dry(api, ff, books, text, mapping={**SIGNED, "balance": ""})["rows"]
    assert rows[0]["category"] is None and rows[0]["rule"] is None, "a rule switched off"
    assert rows[1]["outcome"] == "ignore"
    assert api.as_(ff).delete(f"{RULES}{other['id']}/").status_code == 204
    assert [r["contains"] for r in get(api, ff, RULES).json()] == ["adobe"]
    # A rule for one account leaves the others alone.
    patch(api, ff, f"{RULES}{made.json()['id']}/", {"is_active": True,
                                                    "account": books["card"]["id"]})
    assert dry(api, ff, books, text, mapping={**SIGNED, "balance": ""})["rows"][0][
        "category"] is None


@pytest.mark.django_db
def test_a_line_left_without_a_category_is_entered_and_named_not_dropped(books, ff, api):
    text = "Date,Description,Amount\n10/01/2026,MYSTERY CHARGE,-23.10\n"
    batch = dry(api, ff, books, text, mapping={**SIGNED, "balance": ""})
    post(api, ff, f"{I}{batch['id']}/commit/")
    entry = entries(api, ff, "?category=none")[0]
    assert (entry["kind"], entry["category"], entry["amount_cents"]) == ("expense", None, 2310)
    report = get(api, ff, R + "pnl/?year=2026").json()
    assert report["uncategorized"] == {"count": 1, "amount_cents": 2310}
    assert report["expenses"]["total"] == 0


# ================================================================== rollback

@pytest.mark.django_db
def test_a_committed_import_rolls_back_and_keeps_what_was_edited_since(decided, ff, api):
    books_, batch = decided["books"], decided["batch"]
    assert post(api, ff, f"{I}{batch['id']}/rollback/").status_code == 409, "not committed"
    post(api, ff, f"{I}{batch['id']}/commit/")
    adobe = next(e for e in entries(api, ff) if e["description"].startswith("ADOBE"))
    patch(api, ff, f"{E}{adobe['id']}/", {"description": "Adobe, the design licence"})
    done = post(api, ff, f"{I}{batch['id']}/rollback/")
    assert done.status_code == 200
    result = done.json()["rolled_back"]
    assert result["removed"] == 5
    assert result["kept"] == [{"on_date": "2026-10-01", "amount_cents": 5999,
                               "description": "Adobe, the design licence"}]
    assert [e["description"] for e in entries(api, ff)] == ["Adobe, the design licence"]
    assert done.json()["status"] == "rolled_back"
    assert post(api, ff, f"{I}{batch['id']}/rollback/").status_code == 409
    # Removed, with the reason, and kept in the history.
    removed = [e for e in entries(api, ff, "?removed=1") if e["removed"]]
    assert len(removed) == 5 and all("rolled back" in e["remove_reason"] for e in removed)
    # The file can be imported again: only the kept line is already there.
    again = dry(api, ff, books_)
    assert [r["outcome"] for r in again["rows"][:6]].count("new") == 5
    with tenant_context(books_["tenant"].pk):
        assert AuditEvent.objects.get(verb="finance.import_rolled_back").payload[
            "removed"] == 5


@pytest.mark.django_db
def test_rolling_back_undoes_a_match_and_the_payment_is_unplaced_again(acme, ff, api):
    invoice = sent(api, ff, *acme)
    post(api, ff, f"/api/invoices/{invoice['id']}/payments/",
         {"amount_cents": TOTAL, "paid_on": "2026-10-01"})
    bank = post(api, ff, A, {"name": "Checking", "opening_on": "2026-01-01"}).json()
    text = "Date,Description,Amount\n10/02/2026,DEPOSIT,6800.00\n"
    mapping = {**SIGNED, "balance": ""}
    batch = dry(api, ff, {"bank": bank}, text, mapping=mapping)
    post(api, ff, f"{I}{batch['id']}/commit/")
    result = post(api, ff, f"{I}{batch['id']}/rollback/").json()["rolled_back"]
    assert result == {"removed": 0, "kept": [], "unmatched": 1}
    entry = entries(api, ff)[0]
    assert entry["account"] is None and not entry["removed"], "the income is still income"
    assert get(api, ff, f"/api/invoices/{invoice['id']}/").json()["status"] == "paid"
    assert dry(api, ff, {"bank": bank}, text, mapping=mapping)["rows"][0][
        "outcome"] == "invoice_payment"


@pytest.mark.django_db
def test_a_locked_period_refuses_the_commit_and_the_rollback(decided, ff, api):
    books_, batch = decided["books"], decided["batch"]
    post(api, ff, "/api/finance-settings/", {"locked_through": "2026-10-02"})
    refused = post(api, ff, f"{I}{batch['id']}/commit/")
    assert refused.status_code == 409 and "locked through" in refused.json()["detail"]
    assert entries(api, ff) == [], "none of it, not only the locked lines"
    post(api, ff, "/api/finance-settings/", {"locked_through": None})
    assert post(api, ff, f"{I}{batch['id']}/commit/").status_code == 200
    post(api, ff, "/api/finance-settings/", {"locked_through": "2026-10-02"})
    assert post(api, ff, f"{I}{batch['id']}/rollback/").status_code == 409
    assert len(entries(api, ff)) == 6
    # A dry run is always allowed: it writes nothing.
    assert dry(api, ff, books_)["status"] == "dry_run"


# ================================================================ 1099 payees

@pytest.fixture
def payees(books, ff, api):
    tenant = books["tenant"]
    with tenant_context(tenant.pk):
        casey = ContactFactory(tenant=tenant, first_name="Casey", last_name="Contractor")
        lee = ContactFactory(tenant=tenant, first_name="Lee", last_name="Designer")
        sam = ContactFactory(tenant=tenant, first_name="Sam", last_name="Smallwork")
    for person in (casey, lee, sam):
        assert post(api, ff, P, {"contact": str(person.pk), "is_payee": True}
                    ).status_code == 200
    return {"books": books, "casey": casey, "lee": lee, "sam": sam}


def pay(api, ff, books_, who, cents, on, account="bank", **more):
    return add(api, ff, books_, "expense", cents, on, "Contractors and associates",
               account=account, payee_contact=str(who.pk), **more)


@pytest.mark.django_db
def test_payees_are_totaled_by_calendar_year_and_marked_over_the_threshold(payees, ff, api):
    b = payees["books"]
    for cents, on in ((150000, "2026-02-01"), (60000, "2026-06-01")):
        assert pay(api, ff, b, payees["casey"], cents, on).status_code == 201
    pay(api, ff, b, payees["casey"], 500000, "2025-12-31")              # last year
    pay(api, ff, b, payees["lee"], 250000, "2026-03-01", account="card")   # by card
    pay(api, ff, b, payees["lee"], 50000, "2026-03-02")
    pay(api, ff, b, payees["sam"], 30000, "2026-04-01")
    add(api, ff, b, "expense", 99999, "2026-05-01", "Travel")              # no payee
    report = get(api, ff, P + "?year=2026").json()
    assert (report["threshold_cents"], report["default_threshold_cents"]) == (200000, 200000)
    rows = {row["name"]: row for row in report["payees"]}
    assert (rows["Casey Contractor"]["total_cents"],
            rows["Casey Contractor"]["reportable_cents"],
            rows["Casey Contractor"]["over_threshold"]) == (210000, 210000, True)
    # Paid by card is shown and left out of the reportable figure.
    assert (rows["Lee Designer"]["total_cents"], rows["Lee Designer"]["by_card_cents"],
            rows["Lee Designer"]["reportable_cents"],
            rows["Lee Designer"]["over_threshold"]) == (300000, 250000, 50000, False)
    assert rows["Sam Smallwork"]["over_threshold"] is False
    assert report["over"] == 1
    assert [row["name"] for row in report["payees"]][0] == "Casey Contractor"
    # The year before had the lower threshold, and its own total.
    last = get(api, ff, P + "?year=2025").json()
    assert last["threshold_cents"] == 60000
    assert {r["name"]: r["total_cents"] for r in last["payees"]}["Casey Contractor"] == 500000
    # Another threshold, if the CPA says so.
    lower = get(api, ff, P + "?year=2026&threshold_cents=30000").json()
    assert lower["over"] == 3 and lower["default_threshold_cents"] == 200000
    assert get(api, ff, P + "?year=soon").status_code == 400
    assert get(api, ff, P + "?year=2026&threshold_cents=-1").status_code == 400


@pytest.mark.django_db
def test_a_refund_takes_away_from_a_payees_total_and_a_removed_entry_is_out(payees, ff, api):
    b = payees["books"]
    pay(api, ff, b, payees["casey"], 250000, "2026-02-01")
    gone = pay(api, ff, b, payees["casey"], 70000, "2026-02-02").json()
    post(api, ff, f"{E}{gone['id']}/remove/", {"reason": "Entered twice"})
    assert pay(api, ff, b, payees["casey"], 60000, "2026-02-03", direction="in"
               ).status_code == 201                                   # a refund
    rows = {r["name"]: r for r in get(api, ff, P + "?year=2026").json()["payees"]}
    assert rows["Casey Contractor"]["total_cents"] == 190000
    assert rows["Casey Contractor"]["over_threshold"] is False


@pytest.mark.django_db
def test_someone_paid_as_a_payee_and_since_unflagged_is_still_shown(payees, ff, api):
    b = payees["books"]
    pay(api, ff, b, payees["sam"], 250000, "2026-02-01")
    post(api, ff, P, {"contact": str(payees["sam"].pk), "is_payee": False})
    rows = {r["name"]: r for r in get(api, ff, P + "?year=2026").json()["payees"]}
    assert rows["Sam Smallwork"]["is_payee"] is False
    assert rows["Sam Smallwork"]["over_threshold"] is True
    assert post(api, ff, P, {"contact": str(payees["sam"].pk), "is_payee": "yes"}
                ).status_code == 400
    with tenant_context(b["tenant"].pk):
        assert [e.verb for e in AuditEvent.objects.filter(
            target_id=payees["sam"].pk).order_by("created_at")] == [
            "finance.payee_flagged", "finance.payee_unflagged"]


@pytest.mark.django_db
def test_the_payee_report_exports_and_the_download_is_audited(payees, ff, api):
    b = payees["books"]
    pay(api, ff, b, payees["casey"], 250000, "2026-02-01")
    pay(api, ff, b, payees["lee"], 100000, "2026-02-01", account="card")
    export = get(api, ff, P + "export/?year=2026")
    assert export["Content-Type"].startswith("text/csv")
    assert 'filename="1099-payees-2026.csv"' in export["Content-Disposition"]
    lines = list(csv.reader(io.StringIO(export.content.decode())))
    assert lines[0] == ["1099 payees, 2026, threshold 2000.00"]
    assert lines[2] == ["Casey Contractor", "", "2500.00", "0.00", "2500.00", "yes"]
    assert ["Lee Designer", "", "1000.00", "1000.00", "0.00", ""] in lines
    with tenant_context(b["tenant"].pk):
        assert AuditEvent.objects.get(verb="finance.payees_downloaded").payload == {
            "year": 2026}


@pytest.mark.django_db
def test_an_import_names_the_payee_and_a_rule_remembers_them(payees, ff, api):
    b = payees["books"]
    text = ("Date,Description,Amount\n10/01/2026,ZELLE TO CASEY CONTRACTOR,-2500.00\n"
            "10/15/2026,ZELLE TO CASEY CONTRACTOR,-800.00\n")
    batch = dry(api, ff, b, text, mapping={**SIGNED, "balance": ""})
    batch = decide(api, ff, batch, batch["rows"][0], decision="entry",
                   category=b["cat"]["Contractors and associates"]["id"],
                   payee_contact=str(payees["casey"].pk), remember="CASEY CONTRACTOR")
    assert [r["payee_contact"] for r in batch["rows"]] == [str(payees["casey"].pk)] * 2
    post(api, ff, f"{I}{batch['id']}/commit/")
    rows = {r["name"]: r for r in get(api, ff, P + "?year=2026").json()["payees"]}
    assert rows["Casey Contractor"]["total_cents"] == 330000
    assert rows["Casey Contractor"]["over_threshold"] is True


@pytest.mark.django_db
def test_merging_a_payee_into_another_contact_keeps_the_flag_and_the_total(payees, ff, api):
    from apps.crm.services import merge

    b = payees["books"]
    pay(api, ff, b, payees["casey"], 250000, "2026-02-01")
    with tenant_context(b["tenant"].pk):
        keeper = ContactFactory(tenant=b["tenant"], first_name="Casey",
                                last_name="Contractor")
        payees["casey"].refresh_from_db()      # as a merge loads it: flagged
        merge.merge_contacts(keeper, payees["casey"])
    rows = get(api, ff, P + "?year=2026").json()["payees"]
    assert [(r["contact"], r["total_cents"], r["is_payee"]) for r in rows
            if r["name"] == "Casey Contractor"] == [(str(keeper.pk), 250000, True)]
