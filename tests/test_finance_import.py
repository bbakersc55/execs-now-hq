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


# ============================================ a bank's own file: OFX, QFX, QBO

#: OFX 1.x, as most banks still write it: SGML, where a value's tag is not
#: closed. The same six lines as `BANK`, with the bank's own id for each.
OFX_SGML = """OFXHEADER:100
DATA:OFXSGML
VERSION:102
SECURITY:NONE
ENCODING:USASCII
CHARSET:1252
COMPRESSION:NONE
OLDFILEUID:NONE
NEWFILEUID:NONE

<OFX>
<SIGNONMSGSRSV1><SONRS><STATUS><CODE>0<SEVERITY>INFO</STATUS>
<DTSERVER>20261005120000<LANGUAGE>ENG<FI><ORG>Example Bank<FID>9999</FI></SONRS></SIGNONMSGSRSV1>
<BANKMSGSRSV1><STMTTRNRS><TRNUID>1<STATUS><CODE>0<SEVERITY>INFO</STATUS>
<STMTRS><CURDEF>USD
<BANKACCTFROM><BANKID>123456789<ACCTID>000987654321<ACCTTYPE>CHECKING</BANKACCTFROM>
<BANKTRANLIST><DTSTART>20261001<DTEND>20261005
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20261001120000.000[-7:MST]<TRNAMT>-59.99<FITID>2026100101<NAME>ADOBE *CREATIVE CLOUD
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20261001<TRNAMT>-5.00<FITID>2026100102<NAME>COFFEE BAR
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20261001<TRNAMT>-5.00<FITID>2026100103<NAME>COFFEE BAR
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20261002<TRNAMT>6800.00<FITID>2026100201<NAME>DEPOSIT<MEMO>ACME FACILITIES &amp; CO
<STMTTRN><TRNTYPE>CHECK<DTPOSTED>20261003<TRNAMT>-500.00<FITID>2026100301<CHECKNUM>1042<NAME>CHECK 1042
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20261004<TRNAMT>-3000.00<FITID>2026100401<NAME>OWNER DRAW<MEMO>OWNER DRAW
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>notaday<TRNAMT>-1.00<FITID>2026100501<NAME>BROKEN LINE
</BANKTRANLIST>
<LEDGERBAL><BALAMT>13230.01<DTASOF>20261005120000</LEDGERBAL>
<AVAILBAL><BALAMT>13000.00<DTASOF>20261005120000</AVAILBAL>
</STMTRS></STMTTRNRS></BANKMSGSRSV1>
</OFX>
"""

#: OFX 2.x, which is XML: every tag closed. A card's statement.
OFX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<?OFX OFXHEADER="200" VERSION="211" SECURITY="NONE" OLDFILEUID="NONE" NEWFILEUID="NONE"?>
<OFX><CREDITCARDMSGSRSV1><CCSTMTTRNRS><CCSTMTRS><CURDEF>USD</CURDEF>
<CCACCTFROM><ACCTID>4111111111111111</ACCTID></CCACCTFROM>
<BANKTRANLIST><DTSTART>20261001</DTSTART><DTEND>20261031</DTEND>
<STMTTRN><TRNTYPE>DEBIT</TRNTYPE><DTPOSTED>20261006</DTPOSTED><TRNAMT>-212.40</TRNAMT>
<FITID>C-1</FITID><NAME>HOTEL ALPINE</NAME><MEMO>DENVER CO</MEMO></STMTTRN>
<STMTTRN><TRNTYPE>CREDIT</TRNTYPE><DTPOSTED>20261020</DTPOSTED><TRNAMT>500.00</TRNAMT>
<FITID>C-2</FITID><NAME>PAYMENT THANK YOU</NAME></STMTTRN>
</BANKTRANLIST>
<LEDGERBAL><BALAMT>-212.40</BALAMT><DTASOF>20261031</DTASOF></LEDGERBAL>
</CCSTMTRS></CCSTMTTRNRS></CREDITCARDMSGSRSV1></OFX>
"""


@pytest.mark.django_db
def test_an_ofx_file_is_read_into_the_same_import_with_nothing_to_map(books, ff, api):
    """Owner, 2026-10-14: OFX, QFX and QBO beside CSV, parsed without AI.
    Same mapping, dry run, rules and commit."""
    tenant = books["tenant"]
    dry(api, ff, books)                              # the account's CSV columns, remembered
    with tenant_context(tenant.pk):
        saved = FinanceImportProfile.objects.get().mapping
        FinanceImportBatch.objects.all().delete()
    post(api, ff, RULES, {"contains": "adobe", "treat_as": "category",
                          "category": books["cat"]["Software"]["id"]})

    found = upload(api, ff, I + "detect/", books["bank"], OFX_SGML, name="export.ofx")
    assert found.status_code == 200, found.content
    found = found.json()
    assert (found["kind"], found["fixed"], found["from_saved"], found["lines"]) == (
        "ofx", True, False, 7)
    assert found["header"] == ["Date", "Description", "Amount", "Transaction ID",
                               "Check number"]
    assert found["sample"][0] == {
        "Date": "2026-10-01", "Description": "ADOBE *CREATIVE CLOUD", "Amount": "-59.99",
        "Transaction ID": "2026100101", "Check number": ""}
    assert found["mapping"]["bank_id"] == "Transaction ID"
    with tenant_context(tenant.pk):
        assert not FinanceImportBatch.objects.exists(), "detecting writes nothing"

    before = snapshot(tenant)
    # Whatever mapping is sent with it, the format's own is the one used.
    made = upload(api, ff, I + "dry-run/", books["bank"], OFX_SGML,
                  mapping={"date": "Nonsense"}, name="export.ofx")
    assert made.status_code == 201, made.content
    batch = made.json()
    assert snapshot(tenant) == before, "the dry run writes nothing to the books"
    rows = batch["rows"]
    assert [(r["on_date"], r["amount_cents"], r["direction"], r["description"])
            for r in rows[:6]] == [
        ("2026-10-01", 5999, "out", "ADOBE *CREATIVE CLOUD"),
        ("2026-10-01", 500, "out", "COFFEE BAR"), ("2026-10-01", 500, "out", "COFFEE BAR"),
        ("2026-10-02", 680000, "in", "DEPOSIT ACME FACILITIES & CO"),
        ("2026-10-03", 50000, "out", "CHECK 1042"),
        ("2026-10-04", 300000, "out", "OWNER DRAW")]
    assert [r["outcome"] for r in rows] == ["new"] * 6 + ["error"]
    assert "notaday" in rows[6]["error"]
    # The practice's own rules decide, as for a CSV.
    assert rows[0]["category"]["name"] == "Software" and rows[0]["rule"]["contains"] == "adobe"
    # The statement's closing balance, checked against the account as a CSV's is.
    assert (batch["last_balance_cents"], batch["last_balance_on"]) == (1323001, "2026-10-05")
    # No account or routing number is anywhere in what was kept.
    with tenant_context(tenant.pk):
        kept = json.dumps([FinanceImportBatch.objects.get().mapping]
                          + list(FinanceImportRow.objects.values_list("raw", flat=True)))
        assert "000987654321" not in kept and "123456789" not in kept
        assert FinanceImportProfile.objects.get().mapping == saved, \
            "and the account's CSV columns are still the ones remembered"

    done = post(api, ff, f"{I}{batch['id']}/commit/")
    assert done.status_code == 200, done.content
    with tenant_context(tenant.pk):
        made_entries = {e.description: e for e in FinanceEntry.objects.filter(
            source=FinanceEntry.Source.IMPORT)}
        assert len(made_entries) == 5          # the two coffees share a description
        assert made_entries["CHECK 1042"].reference == "1042"
        assert made_entries["CHECK 1042"].bank_id == "2026100301"
        assert FinanceEntry.objects.filter(source=FinanceEntry.Source.IMPORT).count() == 6
    # What the balance view and the Reconcile screen set beside the books.
    from apps.finance import importer
    with tenant_context(tenant.pk):
        [said] = importer.bank_said(tenant).values()
    assert (said["cents"], said["on"].isoformat()) == (1323001, "2026-10-05")

    # The same statement again, as Quicken's file and as a CSV: nothing new.
    again = upload(api, ff, I + "dry-run/", books["bank"], OFX_SGML, name="export.QFX").json()
    assert [r["outcome"] for r in again["rows"]] == ["duplicate"] * 6 + ["error"]
    as_csv = dry(api, ff, books, text=(
        "Date,Description,Amount\n10/01/2026,ADOBE *CREATIVE CLOUD,-59.99\n"
        "10/03/2026,CHECK 1042,-500.00\n10/09/2026,NEW ONE,-1.00\n"),
        mapping={"date": "Date", "description": "Description", "amount": "Amount",
                 "date_format": "%m/%d/%Y", "sign": "negative_is_out"})
    assert [r["outcome"] for r in as_csv["rows"]] == ["duplicate", "duplicate", "new"]


@pytest.mark.django_db
def test_an_xml_ofx_card_file_reads_and_its_balance_is_what_is_owed(books, ff, api):
    for name in ("card.qbo", "card.ofx", "statement.txt"):       # by what it is, not its name
        made = upload(api, ff, I + "dry-run/", books["card"], OFX_XML, name=name)
        assert made.status_code == 201, (name, made.content)
    batch = made.json()
    assert [(r["on_date"], r["amount_cents"], r["direction"], r["description"], r["outcome"])
            for r in batch["rows"]] == [
        ("2026-10-06", 21240, "out", "HOTEL ALPINE DENVER CO", "new"),
        ("2026-10-20", 50000, "in", "PAYMENT THANK YOU", "new")]
    # The file writes what is owed as a negative number; the books, as a positive one.
    assert (batch["last_balance_cents"], batch["last_balance_on"]) == (21240, "2026-10-31")
    with tenant_context(books["tenant"].pk):
        assert "4111111111111111" not in json.dumps(
            list(FinanceImportRow.objects.values_list("raw", flat=True)))
        assert not FinanceImportProfile.objects.exists(), "nothing to remember: no columns chosen"


@pytest.mark.django_db
@pytest.mark.parametrize("text, name, why", [
    ("Date,Description\n", "export.ofx", "not a bank file this import reads"),
    ("<OFX><BANKMSGSRSV1><STMTRS><BANKTRANLIST></BANKTRANLIST></STMTRS></BANKMSGSRSV1></OFX>",
     "empty.ofx", "no transactions"),
    (OFX_SGML.replace("</STMTRS>", "</STMTRS><STMTRS><BANKTRANLIST></BANKTRANLIST></STMTRS>"),
     "two.qfx", "more than one account"),
    ("", "nothing.qbo", "empty"),
])
def test_a_bank_file_that_cannot_be_read_is_refused_in_words(books, ff, api, text, name, why):
    for step in ("detect/", "dry-run/"):
        refused = upload(api, ff, I + step, books["bank"], text, name=name)
        assert refused.status_code == 400 and why in refused.json()["detail"], refused.content
    with tenant_context(books["tenant"].pk):
        assert not FinanceImportBatch.objects.exists()


# ======================================================== a PDF statement

STATEMENT_HTML = """<html><body style="font-family: sans-serif; font-size: 10pt">
<h1>Example Bank</h1><p>Statement for account ending 4421, October 1 to October 31, 2026.
Account number 000987654321. Bryan Baker, 12 Elm Street, Denver CO.</p>
<p>Beginning balance $10,000.00. Ending balance $16,235.01.</p>
<table>{rows}</table></body></html>"""
READ = {
    "period_start": "2026-10-01", "period_end": "2026-10-31",
    "opening_balance": "10000.00", "closing_balance": "16,235.01",
    # What a model might add unasked: there is nowhere for it to be kept.
    "account_number": "000987654321", "account_holder": "Bryan Baker",
    "transactions": [
        {"date": "2026-10-01", "description": "ADOBE *CREATIVE  CLOUD", "amount": "59.99",
         "direction": "out"},
        {"date": "2026-10-02", "description": "DEPOSIT ACME FACILITIES", "amount": "6800.00",
         "direction": "in"},
        {"date": "2026-10-03", "description": "ONLINE TRANSFER TO ACCT 000987654321 REF 12",
         "amount": "500.00", "direction": "out"},
        {"date": "2026-10-04", "description": "CHECK 1042", "amount": "5.00",
         "direction": "out", "account": "000987654321"},
        {"date": "soon", "description": "SMUDGED LINE", "amount": "1.00", "direction": "out"},
        {"date": "2026-10-06", "description": "NO DIRECTION", "amount": "2.00"},
        {"date": "2026-10-07", "description": "UNREADABLE AMOUNT", "amount": "",
         "direction": "out"},
    ]}


def a_pdf(html: str) -> bytes:
    from weasyprint import HTML

    return HTML(string=html).write_pdf()


@pytest.fixture(scope="module")
def statement_pdf_bytes():
    rows = "".join(f"<tr><td>10/0{n}</td><td>Line {n} of the statement</td><td>{n}.00</td></tr>"
                   for n in range(1, 8))
    return a_pdf(STATEMENT_HTML.format(rows=rows))


@pytest.fixture(scope="module")
def scanned_pdf_bytes():
    # A picture of a statement: a page with an image on it and no text.
    pixel = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
             "2mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
    return a_pdf(f'<html><body><img src="{pixel}" style="width:15cm;height:20cm"></body></html>')


def upload_pdf(api, who, url, account, content, name="october.pdf"):
    return api.as_(who).post(url, {
        "file": SimpleUploadedFile(name, content, content_type="application/pdf"),
        "account": account["id"]})


@pytest.mark.django_db
def test_a_pdf_statement_is_priced_first_read_by_claude_and_goes_through_the_dry_run(
        books, ff, api, fake_claude, statement_pdf_bytes):
    """Owner, 2026-10-14."""
    import base64

    from apps.finance import importer, reconcile, statement_pdf
    from apps.tenancy.models import AiCall, StoredFile

    tenant = books["tenant"]
    post(api, ff, RULES, {"contains": "adobe", "treat_as": "category",
                          "category": books["cat"]["Software"]["id"]})
    fake_claude.reply = "Here it is:\n```json\n" + json.dumps(READ) + "\n```"

    # Choosing the file says how long it is and about what it costs. It asks
    # Claude nothing and writes nothing.
    found = upload_pdf(api, ff, I + "detect/", books["bank"], statement_pdf_bytes)
    assert found.status_code == 200, found.content
    found = found.json()
    assert (found["kind"], found["pages"], found["refused"]) == ("pdf", 1, "")
    assert float(found["estimate_usd"]) > 0
    assert fake_claude.requests == []
    with tenant_context(tenant.pk):
        assert not FinanceImportBatch.objects.exists() and not AiCall.objects.exists()
        entries_before = FinanceEntry.objects.count()

    made = upload_pdf(api, ff, I + "dry-run/", books["bank"], statement_pdf_bytes)
    assert made.status_code == 201, made.content
    batch = made.json()

    # One call, with the statement itself and a prompt that forbids what
    # must never be kept.
    [request] = fake_claude.requests
    document, text = request["messages"][0]["content"]
    assert document["type"] == "document"
    assert document["source"]["media_type"] == "application/pdf"
    assert base64.standard_b64decode(document["source"]["data"]) == statement_pdf_bytes
    assert text == {"type": "text", "text": "Read this statement."}
    for words in ("Do NOT include the account number", "holder's name or address",
                  "Do not work out, estimate or correct any figure"):
        assert words in request["system"], words

    # The ordinary dry run: every line with what would happen to it, and
    # nothing in the books.
    rows = batch["rows"]
    assert (batch["source"], batch["status"], batch["filename"]) == (
        "pdf", "dry_run", "october.pdf")
    assert [(r["on_date"], r["amount_cents"], r["direction"], r["description"], r["outcome"])
            for r in rows[:4]] == [
        ("2026-10-01", 5999, "out", "ADOBE *CREATIVE CLOUD", "new"),
        ("2026-10-02", 680000, "in", "DEPOSIT ACME FACILITIES", "new"),
        ("2026-10-03", 50000, "out", "ONLINE TRANSFER TO ACCT …4321 REF 12", "new"),
        ("2026-10-04", 500, "out", "CHECK 1042", "new")]
    assert [r["outcome"] for r in rows[4:]] == ["error"] * 3
    assert "soon" in rows[4]["error"] and "is not an amount" in rows[5]["error"]
    assert rows[0]["category"]["name"] == "Software", "the practice's own rules decide"
    with tenant_context(tenant.pk):
        assert FinanceEntry.objects.count() == entries_before

    # The statement's own facts, and arithmetic on what was read: it adds up.
    statement = batch["statement"]
    assert (statement["period_start"], statement["period_end"]) == ("2026-10-01", "2026-10-31")
    assert (statement["opening_balance_cents"], statement["closing_balance_cents"]) == (
        1000000, 1623501)
    assert statement["adds_up"] == {"in_cents": 680000, "out_cents": 56499,
                                    "expected_cents": 1623501, "difference_cents": 0}
    assert (batch["last_balance_cents"], batch["last_balance_on"]) == (1623501, "2026-10-31")
    # Costed after: the call that read it, on the import.
    with tenant_context(tenant.pk):
        call = AiCall.objects.get()
        assert (call.purpose, call.trigger, call.succeeded) == (
            "finance_read_statement", "button", True)
        assert float(statement["cost_usd"]) == float(call.cost_usd) and call.cost_usd > 0

        # Kept: the PDF itself, with the import. Not kept: whose it is.
        row = FinanceImportBatch.objects.get()
        stored = StoredFile.objects.get(pk=row.statement_file_id)
        assert (stored.purpose, stored.content_type) == ("bank_statement", "application/pdf")
        kept = json.dumps([row.mapping, row.counts, row.filename]
                          + list(FinanceImportRow.objects.values_list("raw", "description")))
        for never in ("000987654321", "Bryan Baker", "account_holder", "Elm Street"):
            assert never not in kept, never
        assert not FinanceImportProfile.objects.exists()
    served = api.as_(ff).get(statement["pdf"])
    assert served.status_code == 200 and served["Content-Type"] == "application/pdf"
    assert served.content == statement_pdf_bytes

    # Commit, as any import; then it is the statement for its month.
    assert post(api, ff, f"{I}{batch['id']}/commit/").status_code == 200
    with tenant_context(tenant.pk):
        assert FinanceEntry.objects.filter(source=FinanceEntry.Source.IMPORT).count() == 4
        [said] = importer.bank_said(tenant).values()
        assert (said["cents"], said["on"].isoformat()) == (1623501, "2026-10-31")
        [(key, [shown])] = reconcile.statements(tenant).items()
        assert key == (row.account_id, reconcile.month_start(row.period_end))
        assert (shown["filename"], shown["pdf"], shown["closing_balance_cents"]) == (
            "october.pdf", statement["pdf"], 1623501)
        account = [a for a in reconcile.grid(tenant, ff.user)["accounts"]
                   if a["id"] == books["bank"]["id"]][0]
        assert list(account["statements"]) == ["2026-10"]

    # The same statement again is read again, and adds nothing.
    again = upload_pdf(api, ff, I + "dry-run/", books["bank"], statement_pdf_bytes).json()
    assert [r["outcome"] for r in again["rows"]] == ["duplicate"] * 4 + ["error"] * 3
    assert len(fake_claude.requests) == 2
    assert statement_pdf.scrub("CARD 4111 1111 1111 1111 PURCHASE") == "CARD …1111 PURCHASE"
    assert statement_pdf.scrub("CHECK 1042 10/04") == "CHECK 1042 10/04"


@pytest.mark.django_db
def test_a_pdf_whose_lines_do_not_add_up_says_by_how_much_and_a_cards_balance_is_owed(
        books, ff, api, fake_claude, statement_pdf_bytes):
    fake_claude.reply = json.dumps({**READ, "closing_balance": "16000.00"})
    batch = upload_pdf(api, ff, I + "dry-run/", books["bank"], statement_pdf_bytes).json()
    assert batch["statement"]["adds_up"]["difference_cents"] == 1600000 - 1623501
    # A card: purchases add to what is owed, a payment takes away.
    fake_claude.reply = json.dumps({
        "period_start": "2026-10-01", "period_end": "2026-10-31",
        "opening_balance": "500.00", "closing_balance": "212.40",
        "transactions": [
            {"date": "2026-10-06", "description": "HOTEL", "amount": "212.40",
             "direction": "out"},
            {"date": "2026-10-20", "description": "PAYMENT THANK YOU", "amount": "500.00",
             "direction": "in"}]})
    card = upload_pdf(api, ff, I + "dry-run/", books["card"], statement_pdf_bytes).json()
    assert card["statement"]["adds_up"]["difference_cents"] == 0
    assert card["last_balance_cents"] == 21240
    # A statement that prints no balances has nothing to add up to.
    fake_claude.reply = json.dumps({**READ, "opening_balance": None, "closing_balance": None})
    bare = upload_pdf(api, ff, I + "dry-run/", books["bank"], statement_pdf_bytes).json()
    assert bare["statement"]["adds_up"] is None and bare["last_balance_cents"] is None


@pytest.mark.django_db
def test_a_pdf_that_cannot_be_read_is_refused_in_plain_words(
        books, ff, api, fake_claude, statement_pdf_bytes, scanned_pdf_bytes, settings):
    from decimal import Decimal

    from apps.tenancy.models import AiCall

    tenant = books["tenant"]

    def both(content, name="october.pdf"):
        return [upload_pdf(api, ff, I + step, books["bank"], content, name=name)
                for step in ("detect/", "dry-run/")]

    # A scan: a picture of a statement, with no text in it.
    for refused in both(scanned_pdf_bytes):
        assert refused.status_code == 400
        assert refused.json()["detail"].startswith("This PDF is a scan")
    for refused in both(b"%PDF-1.7 this is not really one"):
        assert refused.status_code == 400 and "not a PDF" in refused.json()["detail"]
    assert fake_claude.requests == [], "and Claude was asked nothing"

    # What Claude sends back cannot be used: nothing is imported, and it still cost.
    for reply, words in (("I could not read it.", "could not be used"),
                         (json.dumps({"transactions": []}), "found no transactions")):
        fake_claude.reply = reply
        refused = upload_pdf(api, ff, I + "dry-run/", books["bank"], statement_pdf_bytes)
        assert refused.status_code == 502 and words in refused.json()["detail"]
        assert "still an AI call" in refused.json()["detail"]
    fake_claude.stop_reason = "max_tokens"
    long_one = upload_pdf(api, ff, I + "dry-run/", books["bank"], statement_pdf_bytes)
    assert long_one.status_code == 502
    assert "more on it than can be read in one go" in long_one.json()["detail"]
    fake_claude.stop_reason = "end_turn"
    with tenant_context(tenant.pk):
        assert AiCall.objects.count() == 3, "each read is on the record, failed or not"
        assert not FinanceImportBatch.objects.exists()
        assert not FinanceEntry.objects.filter(source=FinanceEntry.Source.IMPORT).exists()

    # Counted against the practice's AI budget: spent, it is refused before it is read.
    asked = len(fake_claude.requests)
    with tenant_context(tenant.pk):
        AiCall.objects.update(cost_usd=Decimal("2.00"))
    tenant.ai_monthly_budget_usd = Decimal("5.00")
    tenant.save()
    found, made = both(statement_pdf_bytes)
    assert found.status_code == 200 and "AI budget is spent" in found.json()["refused"]
    assert made.status_code == 409 and "AI budget is spent" in made.json()["detail"]
    tenant.ai_monthly_budget_usd = Decimal("50.00")
    tenant.save()
    assert both(statement_pdf_bytes)[0].json()["refused"] == ""
    # No key: said before, and refused.
    settings.ANTHROPIC_API_KEY = ""
    found, made = both(statement_pdf_bytes)
    assert "No Anthropic API key" in found.json()["refused"]
    assert made.status_code == 409 and "No Anthropic API key" in made.json()["detail"]
    assert len(fake_claude.requests) == asked + 1, "only the one read the budget allowed"


@pytest.mark.django_db
def test_role_boundaries_and_isolation_the_statement_is_the_practice_owners_alone(
        books, ff, va, cf, fcc, tenant_b, api, fake_claude, statement_pdf_bytes):
    fake_claude.reply = json.dumps(READ)
    batch = upload_pdf(api, ff, I + "dry-run/", books["bank"], statement_pdf_bytes).json()
    pdf = batch["statement"]["pdf"]
    assert api.as_(ff).get(pdf).status_code == 200
    for who in (va, cf):
        assert api.as_(who).get(pdf).status_code == 403
        assert upload_pdf(api, who, I + "dry-run/", books["bank"],
                          statement_pdf_bytes).status_code == 403
    assert api.as_(fcc).get(pdf).status_code == 404
    stranger = _member(tenant_b, "FF")
    assert api.as_(stranger).get(pdf).status_code == 404
    assert upload_pdf(api, stranger, I + "dry-run/", books["bank"],
                      statement_pdf_bytes).status_code == 404
    assert len(fake_claude.requests) == 1
    # A CSV's import has no statement to serve.
    plain = dry(api, ff, books)
    assert plain["statement"] is None and plain["source"] == "csv"
    assert api.as_(ff).get(f"{I}{plain['id']}/statement/").status_code == 404
