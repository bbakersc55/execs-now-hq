"""P6 M4 stop 1, the rest (`docs/p6_m4_personal_finance.md`, decisions 2, 3,
5–8): rules by hand, importing into a personal account, transfers between
the household's own accounts, optional reconcile, and Sort these with Claude.

1. **Isolation, extended to every new route**: another practice owner, the
   rest of the practice and a practice without the module reach none of it.
2. **Rules by hand**, with a side; the dry run's "remember" for a split
   saves the percent that line's split works out to.
3. **A personal account imports** (CSV, OFX, PDF) through the same dry run.
   A business line there is the practice's, paid personally: in the P&L and
   on the CPA's worksheet, in none of the practice's accounts. The rollback
   takes all of it back.
4. **Transfers** pair when both sides are in, and are never spending.
5. **Reconcile** is optional and has no close.
6. **Sort these with Claude**: priced first, costed, capped on Finance's 20
   a day; only merchant names, amounts and category names are sent.
"""

from __future__ import annotations

import json

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.finance.models import FinanceEntry, FinanceRule
from apps.personal.models import PersonalImport, PersonalLine
from apps.tenancy.models import AiCall

from . import registry_config  # noqa: F401
from .conftest import _member
from .test_client_invoicing import get, patch, post
from .test_finance_books import A, C, E, R, books  # noqa: F401
from .test_finance_import import I, READ, RULES, SIGNED, decide, dry, rows_of
from .test_finance_import import statement_pdf_bytes  # noqa: F401
from .test_personal_sides import CARD, chart_of, lines, switched_on

P = "/api/personal/"
SIGNED = {key: value for key, value in SIGNED.items() if key != "balance"}
JOINT = """Date,Description,Amount
10/01/2026,ADOBE *CREATIVE CLOUD,-59.99
10/02/2026,COFFEE BAR,-5.00
10/03/2026,COSTCO WHOLESALE,-312.40
10/04/2026,NETFLIX.COM,-22.99
10/05/2026,VERIZON WIRELESS,-100.00
10/06/2026,TRANSFER TO SAVINGS,-500.00
10/07/2026,SPOUSE PAYROLL ACME,"2,400.00"
"""
SAVINGS = """Date,Description,Amount
10/08/2026,TRANSFER FROM CHECKING,500.00
10/09/2026,INTEREST PAID,1.25
"""


@pytest.fixture
def household(books, ff, api):
    """A practice with Personal finance and the owner's rules (Adobe is the
    practice's, Netflix the owner's, Verizon 60% business), and two personal
    accounts: joint checking and savings."""
    switched_on(books["tenant"])
    mine = chart_of(api, ff)
    for body in ({"contains": "ADOBE", "category": books["cat"]["Software and subscriptions"]["id"]},
                 {"contains": "NETFLIX", "side": "personal",
                  "personal_category": mine["Entertainment and subscriptions"]["id"]},
                 {"contains": "VERIZON", "side": "split", "split_percent": 60,
                  "category": books["cat"]["Phone and internet"]["id"],
                  "personal_category": mine["Phone and internet"]["id"]}):
        made = post(api, ff, RULES, {"treat_as": "category", **body})
        assert made.status_code == 201, made.content
    accounts = {}
    for name, kind, opening in (("Joint checking", "bank", 500000),
                                ("Savings", "bank", 1000000)):
        made = post(api, ff, P + "accounts", {"name": name, "kind": kind,
                                              "opening_balance_cents": opening,
                                              "opening_on": "2026-09-01"})
        assert made.status_code == 201, made.content
        accounts[name] = made.json()
    return {**books, "mine": mine, "joint": accounts["Joint checking"],
            "savings": accounts["Savings"]}


def upload(api, who, url, account, content, mapping=None, name="joint.csv",
           kind="text/csv"):
    body = {"file": SimpleUploadedFile(name, content if isinstance(content, bytes)
                                       else content.encode(), content_type=kind),
            "account": account["id"]}
    if mapping is not None:
        body["mapping"] = json.dumps(mapping)
    return api.as_(who).post(url, body)


def pdry(api, ff, account, text=JOINT, mapping=SIGNED, name="joint.csv"):
    made = upload(api, ff, P + "imports/dry-run", account, text, mapping, name=name)
    assert made.status_code == 201, made.content
    return made.json()


def pdecide(api, ff, batch, row, **body):
    made = post(api, ff, f"{P}imports/{batch['id']}/rows/{row['id']}", body)
    assert made.status_code == 200, made.content
    return made.json()


def pcommit(api, ff, batch):
    made = post(api, ff, f"{P}imports/{batch['id']}/commit", {})
    assert made.status_code == 200, made.content
    return made.json()


def live_lines(**filters):
    return PersonalLine.objects.filter(removed_at__isnull=True, **filters)


# ================================================================ isolation

@pytest.mark.django_db
def test_nobody_else_reaches_a_personal_import_or_its_routes(household, ff, api, tenant_b):
    batch = pdry(api, ff, household["joint"])
    pcommit(api, ff, batch)
    rec = post(api, ff, f"{P}accounts/{household['joint']['id']}/reconciliations",
               {"statement_on": "2026-10-31", "statement_balance_cents": 0}).json()
    routes = [("get", P + "imports"), ("get", f"{P}imports/{batch['id']}"),
              ("post", f"{P}imports/{batch['id']}/rollback"),
              ("get", f"{P}accounts/{household['joint']['id']}/reconciliations"),
              ("get", f"{P}reconciliations/{rec['id']}"),
              ("post", f"{P}reconciliations/{rec['id']}/finish"),
              ("get", P + "sort-with-claude")]
    other = _member(tenant_b, "FF")
    switched_on(tenant_b)
    for method, url in routes:
        response = getattr(api.as_(other), method)(url, {}) if method == "post" \
            else api.as_(other).get(url)
        if url == P + "imports":
            assert response.status_code == 200 and response.json() == []
        elif url == P + "sort-with-claude":
            assert response.json()["lines"] == 0
        else:
            assert response.status_code == 404, (url, response.content)
    for role in ("CF", "VA"):
        someone = _member(household["tenant"], role)
        for method, url in routes:
            response = getattr(api.as_(someone), method)(url, {}) if method == "post" \
                else api.as_(someone).get(url)
            assert response.status_code == 404, (role, url)
    assert PersonalImport.objects.get(pk=batch["id"]).status == "committed"


# ============================================================ rules by hand

@pytest.mark.django_db
def test_a_rule_is_added_and_edited_by_hand_with_its_side(household, ff, api):
    rules = {rule["contains"]: rule for rule in get(api, ff, RULES).json()}
    assert rules["NETFLIX"]["side"] == "personal"
    assert rules["NETFLIX"]["personal_category"]["name"] == "Entertainment and subscriptions"
    assert (rules["VERIZON"]["side"], rules["VERIZON"]["split_percent"]) == ("split", 60)
    # Edited: Verizon is now 75% business; Netflix the practice's after all.
    changed = patch(api, ff, f"{RULES}{rules['VERIZON']['id']}/", {"split_percent": 75})
    assert changed.json()["split_percent"] == 75
    changed = patch(api, ff, f"{RULES}{rules['NETFLIX']['id']}/", {
        "side": "business", "category": household["cat"]["Software and subscriptions"]["id"]})
    assert changed.status_code == 200, changed.content
    assert (changed.json()["side"], changed.json()["personal_category"]) == ("", None)
    for body, why in (({"contains": "AMAZON", "treat_as": "category", "side": "split",
                        "split_percent": 100,
                        "category": household["cat"]["Supplies"]["id"]}, "1 and 99"),
                      ({"contains": "AMAZON", "treat_as": "category", "side": "split",
                        "split_percent": "half",
                        "category": household["cat"]["Supplies"]["id"]}, "whole number"),
                      ({"contains": "AM", "treat_as": "category", "side": "personal"},
                       "three characters")):
        refused = post(api, ff, RULES, body)
        assert refused.status_code == 400 and why in refused.json()["detail"], refused.content


@pytest.mark.django_db
def test_without_the_module_a_rule_has_no_side(books, ff, api):
    refused = post(api, ff, RULES, {"contains": "NETFLIX", "treat_as": "category",
                                    "side": "personal"})
    assert refused.status_code == 404
    plain = post(api, ff, RULES, {"contains": "ADOBE", "treat_as": "category",
                                  "category": books["cat"]["Supplies"]["id"]})
    assert plain.status_code == 201 and plain.json()["side"] == ""


@pytest.mark.django_db
def test_remembering_a_split_in_the_dry_run_keeps_its_percent(household, ff, api):
    patch(api, ff, f"{A}{household['card']['id']}/", {"side": "mixed"})
    text = "Date,Description,Amount\n10/01/2026,COMCAST CABLE,-200.00\n" \
           "11/01/2026,COMCAST CABLE,-180.00\n"
    batch = dry(api, ff, household, text, account="card", mapping=SIGNED)
    row = batch["rows"][0]
    batch = decide(api, ff, batch, row, decision="entry", side="split",
                   category=household["cat"]["Phone and internet"]["id"],
                   split_business_cents=5000,
                   personal_category=household["mine"]["Phone and internet"]["id"],
                   remember="COMCAST")
    rule = FinanceRule.all_objects.get(contains="COMCAST")
    assert (rule.side, rule.split_percent, rule.category.name, rule.personal_category.name) \
        == ("split", 25, "Phone and internet", "Phone and internet")
    # The other Comcast line of the import takes it at once: 25% of $180.
    second = [r for r in batch["rows"] if r["row_number"] == 3][0]
    assert (second["side"], second["split_business_cents"]) == ("split", 4500)


@pytest.mark.django_db
def test_a_rule_learned_on_the_personal_side_carries_its_side_and_category(
        household, ff, api):
    batch = pdry(api, ff, household["joint"])
    costco = rows_of(batch)["COSTCO WHOLESALE"]
    assert costco["side"] == "to_sort"
    pdecide(api, ff, batch, costco, decision="line", side="personal",
            category=household["mine"]["Groceries"]["id"], remember="COSTCO")
    rule = FinanceRule.all_objects.get(contains="COSTCO")
    assert (rule.side, rule.personal_category.name, rule.category) == \
        ("personal", "Groceries", None)


# ===================================================== importing personally

@pytest.mark.django_db
def test_the_dry_run_gives_each_line_of_a_personal_account_a_side(household, ff, api):
    detected = upload(api, ff, P + "imports/detect", household["joint"], JOINT).json()
    assert detected["header"] == ["Date", "Description", "Amount"]
    assert detected["mapping"]["amount"] == "Amount"
    batch = pdry(api, ff, household["joint"])
    rows = rows_of(batch)
    assert (rows["ADOBE *CREATIVE CLOUD"]["side"],
            rows["ADOBE *CREATIVE CLOUD"]["business_category"]["name"]) \
        == ("business", "Software and subscriptions")
    assert (rows["COFFEE BAR"]["side"], rows["COFFEE BAR"]["category"]["name"]) == \
        ("personal", "Everything else")                        # under the $25 threshold
    assert rows["COSTCO WHOLESALE"]["side"] == "to_sort"       # at or over it
    assert rows["NETFLIX.COM"]["category"]["name"] == "Entertainment and subscriptions"
    assert (rows["VERIZON WIRELESS"]["side"],
            rows["VERIZON WIRELESS"]["split_business_cents"]) == ("split", 6000)
    assert batch["counts"]["business"] == 1 and batch["counts"]["to_sort"] == 3
    # Nothing is written but the import and its rows.
    assert not PersonalLine.objects.exists()
    assert not FinanceEntry.all_objects.filter(side="paid_personally").exists()
    # The columns are remembered for this account.
    again = upload(api, ff, P + "imports/detect", household["joint"], JOINT).json()
    assert again["from_saved"] is True


@pytest.mark.django_db
def test_a_business_line_paid_personally_reaches_the_books_and_the_cpa(household, ff, api):
    batch = pdry(api, ff, household["joint"])
    pcommit(api, ff, batch)
    adobe = FinanceEntry.all_objects.get(description="ADOBE *CREATIVE CLOUD")
    assert (adobe.kind, adobe.side, adobe.account, adobe.category.name, adobe.amount_cents) \
        == ("expense", "paid_personally", None, "Software and subscriptions", 5999)
    verizon = FinanceEntry.all_objects.get(description="VERIZON WIRELESS")
    assert (verizon.side, verizon.amount_cents) == ("paid_personally", 6000)
    # The ledger keeps the bank's lines whole, in the account.
    paid = live_lines(description="ADOBE *CREATIVE CLOUD").get()
    assert (paid.category.name, paid.paid_entry_id, paid.account.name) == \
        ("Paid for the practice", adobe.pk, "Joint checking")
    split = sorted(live_lines(description="VERIZON WIRELESS").values_list(
        "amount_cents", "category__name"))
    assert split == [(4000, "Phone and internet"), (6000, "Paid for the practice")]
    # In the P&L and on the worksheet, in no account of the practice's.
    pnl = get(api, ff, R + "pnl/?year=2026").json()
    assert pnl["expenses"]["total"] == 5999 + 6000
    worksheet = get(api, ff, R + "export-worksheet/?year=2026").content.decode()
    assert "Expenses paid from a personal account,119.99,An owner contribution" in worksheet
    balance = get(api, ff, R + "balance/").json()
    assert balance["unplaced_cents"] == 0
    assert {row["amount_cents"] for row in balance["cash"]} == {1000000}
    # The household's account balance is the bank's.
    joint = [a for a in get(api, ff, P + "accounts").json() if a["name"] == "Joint checking"][0]
    assert joint["balance_cents"] == 500000 - 5999 - 500 - 31240 - 2299 - 10000 - 50000 \
        + 240000


@pytest.mark.django_db
def test_the_rollback_takes_back_both_sides_of_a_personal_import(household, ff, api):
    batch = pdry(api, ff, household["joint"])
    pcommit(api, ff, batch)
    assert live_lines().count() == 8                 # Verizon is two lines
    undone = post(api, ff, f"{P}imports/{batch['id']}/rollback", {})
    assert undone.status_code == 200, undone.content
    assert undone.json()["rolled_back"]["removed"] == 8
    assert not live_lines().exists()
    assert not FinanceEntry.all_objects.filter(side="paid_personally",
                                               removed_at__isnull=True).exists()
    # And the file can come in again.
    again = pdry(api, ff, household["joint"])
    assert again["counts"]["duplicate"] == 0


@pytest.mark.django_db
def test_lines_already_in_are_not_brought_in_twice(household, ff, api):
    pcommit(api, ff, pdry(api, ff, household["joint"]))
    again = pdry(api, ff, household["joint"])
    assert again["counts"]["duplicate"] == 7 and again["counts"]["new"] == 0


@pytest.mark.django_db
def test_an_ofx_file_and_a_pdf_statement_go_through_the_same_dry_run(
        household, ff, api, fake_claude, statement_pdf_bytes):
    ofx = (b"OFXHEADER:100\nDATA:OFXSGML\n\n<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS>"
           b"<BANKTRANLIST><STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20261003<TRNAMT>-312.40"
           b"<FITID>A1<NAME>COSTCO WHOLESALE</STMTTRN></BANKTRANLIST></STMTRS></STMTTRNRS>"
           b"</BANKMSGSRSV1></OFX>")
    batch = pdry(api, ff, household["joint"], ofx, mapping=None, name="joint.qfx")
    assert batch["source"] == "ofx" and rows_of(batch)["COSTCO WHOLESALE"]["side"] == \
        "to_sort"
    fake_claude.reply = json.dumps(READ)
    priced = upload(api, ff, P + "imports/detect", household["savings"], statement_pdf_bytes,
                    name="october.pdf", kind="application/pdf").json()
    assert priced["kind"] == "pdf" and float(priced["estimate_usd"]) > 0
    assert fake_claude.requests == []
    read = pdry(api, ff, household["savings"], statement_pdf_bytes, mapping=None,
                name="october.pdf")
    assert read["source"] == "pdf" and read["statement"]["cost_usd"] is not None
    assert len(fake_claude.requests) == 1
    assert rows_of(read)["ADOBE *CREATIVE CLOUD"]["side"] == "business"


@pytest.mark.django_db
def test_a_personal_account_line_is_sorted_to_either_side_afterwards(household, ff, api):
    pcommit(api, ff, pdry(api, ff, household["joint"]))
    costco = live_lines(description="COSTCO WHOLESALE").get()
    waiting = lines(api, ff, "?to_sort=1")
    assert any(line["id"] == str(costco.pk) for line in waiting["lines"])
    made = post(api, ff, P + "sort", {"line": str(costco.pk), "side": "business",
                                     "category": household["cat"]["Supplies"]["id"],
                                     "remember": "COSTCO"})
    assert made.status_code == 200, made.content
    assert made.json()["paid_for"]["category"] == "Supplies"
    entry = FinanceEntry.all_objects.get(description="COSTCO WHOLESALE")
    assert (entry.side, entry.account, entry.category.name) == ("paid_personally", None,
                                                               "Supplies")
    # Back to the household: the practice's entry goes, the line stays.
    back = post(api, ff, P + "sort", {"line": str(costco.pk), "side": "personal",
                                     "personal_category": household["mine"]["Groceries"]["id"]})
    assert back.status_code == 200, back.content
    entry.refresh_from_db()
    costco.refresh_from_db()
    assert entry.removed_at is not None
    assert (costco.category.name, costco.paid_entry, costco.removed_at) == \
        ("Groceries", None, None)


@pytest.mark.django_db
def test_editing_a_paid_personally_entry_into_an_account_sends_its_line_back(
        household, ff, api):
    pcommit(api, ff, pdry(api, ff, household["joint"]))
    adobe = FinanceEntry.all_objects.get(description="ADOBE *CREATIVE CLOUD")
    moved = patch(api, ff, f"{E}{adobe.pk}/", {"account": household["bank"]["id"]})
    assert moved.status_code == 200, moved.content
    adobe.refresh_from_db()
    assert (adobe.side, str(adobe.account_id)) == ("", household["bank"]["id"])
    line = live_lines(description="ADOBE *CREATIVE CLOUD").get()
    assert (line.paid_entry, line.category) == (None, None)        # To sort again


# ================================================================ transfers

@pytest.mark.django_db
def test_a_transfer_pairs_when_both_sides_are_in_and_is_never_spending(household, ff, api):
    pcommit(api, ff, pdry(api, ff, household["joint"]))
    out = live_lines(description="TRANSFER TO SAVINGS").get()
    assert out.category is None                        # $500 with no rule: To sort
    batch = pdry(api, ff, household["savings"], SAVINGS, name="savings.csv")
    row = rows_of(batch)["TRANSFER FROM CHECKING"]
    assert row["outcome"] == "transfer_match"
    assert (row["matched"]["description"], row["matched"]["account"]) == \
        ("TRANSFER TO SAVINGS", "Joint checking")
    pcommit(api, ff, batch)
    out.refresh_from_db()
    came = live_lines(description="TRANSFER FROM CHECKING").get()
    assert (out.transfer_pair_id, came.transfer_pair_id) == (came.pk, out.pk)
    assert out.category.name == came.category.name == "Transfers"
    assert out.category.type == "transfer"             # not spending
    # Rolled back: unpaired, and the checking line waits to be sorted again.
    post(api, ff, f"{P}imports/{batch['id']}/rollback", {})
    out.refresh_from_db()
    assert (out.transfer_pair, out.category) == (None, None)


@pytest.mark.django_db
def test_a_proposed_transfer_can_be_declined(household, ff, api):
    pcommit(api, ff, pdry(api, ff, household["joint"]))
    batch = pdry(api, ff, household["savings"], SAVINGS, name="savings.csv")
    row = rows_of(batch)["TRANSFER FROM CHECKING"]
    batch = pdecide(api, ff, batch, row, decision="not_a_match")
    row = rows_of(batch)["TRANSFER FROM CHECKING"]
    assert (row["outcome"], row["side"], row["matched"]) == ("new", "to_sort", None)


# ================================================================ reconcile

@pytest.mark.django_db
def test_reconciling_a_personal_account_is_optional_and_has_no_close(household, ff, api):
    pcommit(api, ff, pdry(api, ff, household["savings"], SAVINGS, name="savings.csv"))
    url = f"{P}accounts/{household['savings']['id']}/reconciliations"
    rec = post(api, ff, url, {"statement_on": "2026-10-31",
                              "statement_balance_cents": 1000000 + 50000 + 125})
    assert rec.status_code == 201, rec.content
    rec = rec.json()
    assert (rec["starting_balance_cents"], rec["difference_cents"]) == (1000000, 50125)
    refused = post(api, ff, f"{P}reconciliations/{rec['id']}/finish", {})
    assert refused.status_code == 409 and "$501.25" in refused.json()["detail"]
    ticked = post(api, ff, f"{P}reconciliations/{rec['id']}/tick",
                  {"lines": [line["id"] for line in rec["lines"]], "cleared": True}).json()
    assert ticked["difference_cents"] == 0
    done = post(api, ff, f"{P}reconciliations/{rec['id']}/finish", {}).json()
    assert done["state"] == "finished"
    savings = [a for a in get(api, ff, P + "accounts").json() if a["name"] == "Savings"][0]
    assert savings["reconciled_through"] == "2026-10-31"
    # A finished statement holds its lines: the import cannot be rolled back
    # under it until it is reopened.
    batch = get(api, ff, P + "imports").json()[0]
    held = post(api, ff, f"{P}imports/{batch['id']}/rollback", {})
    assert held.status_code == 409 and "Reopen" in held.json()["detail"]
    assert post(api, ff, f"{P}reconciliations/{rec['id']}/reopen", {}).json()["state"] \
        == "open"
    # Nothing in the books is locked by any of it.
    assert get(api, ff, "/api/finance-settings/").json().get("locked_through") is None


# ================================================== Sort these with Claude

@pytest.mark.django_db
def test_sort_with_claude_is_priced_first_and_sends_only_names_and_amounts(
        household, ff, api, fake_claude):
    patch(api, ff, f"{A}{household['card']['id']}/", {"side": "mixed"})
    batch = dry(api, ff, household, CARD, account="card", mapping=SIGNED)
    post(api, ff, f"{I}{batch['id']}/commit/", {})
    pcommit(api, ff, pdry(api, ff, household["joint"]))
    priced = get(api, ff, P + "sort-with-claude").json()
    assert priced["lines"] == 4 and float(priced["estimate_usd"]) > 0
    assert priced["refused"] == "" and priced["cap"] == 20
    assert fake_claude.requests == []
    from apps.personal import services, sort_ai

    _text, by_ref, personal, business = sort_ai.what_is_sent(
        services.ledger_for(ff.user), household["tenant"])
    refs = {row["description"]: ref for ref, row in by_ref.items()}
    groceries = next(ref for ref, c in personal.items() if c.name == "Groceries")
    supplies = next(ref for ref, c in business.items() if c.name == "Supplies")
    fake_claude.reply = json.dumps({"lines": [
        {"id": refs["COSTCO WHOLESALE"], "side": "personal", "category": groceries,
         "match": "COSTCO", "why": "A warehouse store."},
        {"id": refs["TRANSFER TO SAVINGS"], "side": "business", "category": supplies,
         "match": "NOT IN IT", "why": "?"},
        {"id": "L99", "side": "personal", "category": groceries},
        {"id": refs["SPOUSE PAYROLL ACME"], "side": "personal", "category": "P999"}]})
    answer = post(api, ff, P + "sort-with-claude", {})
    assert answer.status_code == 200, answer.content
    answer = answer.json()
    proposals = {p["description"]: p for p in answer["proposals"]}
    assert set(proposals) == {"COSTCO WHOLESALE", "TRANSFER TO SAVINGS"}
    assert proposals["COSTCO WHOLESALE"]["category"]["name"] == "Groceries"
    assert proposals["TRANSFER TO SAVINGS"]["match"] == "TRANSFER TO"   # the line's own
    assert float(answer["cost_usd"]) >= 0 and answer["used_today"] == 1
    [request] = fake_claude.requests
    sent = request["messages"][0]["content"]
    sent = sent if isinstance(sent, str) else " ".join(part.get("text", "") for part in sent)
    for never in ("Joint checking", "Business card", "4421", ff.user.email,
                  ff.user.full_name or "@"):
        assert never not in sent, never
    assert "COSTCO WHOLESALE" in sent and "$312.40" in sent
    assert AiCall.all_objects.filter(purpose="personal_sort_lines").count() == 1
    # Accepted through the ordinary route, it becomes a rule.
    costco = proposals["COSTCO WHOLESALE"]
    made = post(api, ff, P + "sort", {costco["kind"]: costco["id"], "side": "personal",
                                     "personal_category": costco["category"]["id"],
                                     "remember": costco["match"]})
    assert made.status_code == 200, made.content
    assert FinanceRule.all_objects.get(contains="COSTCO").side == "personal"


@pytest.mark.django_db
def test_sort_with_claude_counts_on_finances_twenty_a_day(household, ff, api, fake_claude):
    from apps.finance import explain

    pcommit(api, ff, pdry(api, ff, household["joint"]))
    assert "personal_sort_lines" in explain.PRESSED
    for _ in range(explain.DAILY_CAP):
        AiCall.all_objects.create(tenant=household["tenant"], purpose="finance_explain_step",
                                  model="m")
    priced = get(api, ff, P + "sort-with-claude").json()
    assert "20" in priced["refused"]
    refused = post(api, ff, P + "sort-with-claude", {})
    assert refused.status_code == 409
    assert fake_claude.requests == []


@pytest.mark.django_db
def test_sort_with_claude_stops_at_the_monthly_ai_budget(household, ff, api, fake_claude):
    from decimal import Decimal

    pcommit(api, ff, pdry(api, ff, household["joint"]))
    tenant = household["tenant"]
    tenant.ai_monthly_budget_usd = Decimal("1.00")
    tenant.save(update_fields=["ai_monthly_budget_usd"])
    AiCall.all_objects.create(tenant=tenant, purpose="meeting_parse", model="m",
                              cost_usd=Decimal("1.00"))
    assert "budget" in get(api, ff, P + "sort-with-claude").json()["refused"]
    assert post(api, ff, P + "sort-with-claude", {}).status_code == 409
    assert fake_claude.requests == []
