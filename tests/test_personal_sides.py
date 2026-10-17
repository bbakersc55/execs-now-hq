"""P6 M4 stop 1 — sides (`docs/p6_m4_personal_finance.md`, decisions 1–5).

1. **Isolation, extended to a person** (decision 24, the brief): a ledger is
   its owner's. Another practice owner, anyone else in the practice, the
   platform owner and a practice without the module reach none of it; and it
   survives its owner leaving the practice.
2. **One Mixed card imports once and both sides come out right**: rules and
   the threshold give each line a side in the dry run; the commit posts a
   personal line as an owner draw in the books and the spend in the ledger, a
   split as both; a rollback takes all of it back.
3. Sorting afterwards, and the books' own edits keeping sides true.
4. The personal chart, with the Tax-deductible marks.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.finance.models import FinanceEntry, FinanceRule
from apps.personal import models as personal_models
from apps.personal.models import PersonalCategory, PersonalLedger, PersonalLine
from apps.tenancy import modules

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import ClientCompanyFactory
from .test_client_invoicing import get, patch, post
from .test_finance_books import A, C, E, books  # noqa: F401
from .test_finance_import import I, SIGNED, decide, dry, rows_of
from .test_platform_isolation import in_practices_area, platform_owner  # noqa: F401

L = "/api/personal/lines"
SIGNED = {key: value for key, value in SIGNED.items() if key != "balance"}
CARD = """Date,Description,Amount
10/01/2026,ADOBE *CREATIVE CLOUD,-59.99
10/02/2026,COFFEE BAR,-5.00
10/03/2026,COSTCO WHOLESALE,-312.40
10/04/2026,NETFLIX.COM,-22.99
10/05/2026,VERIZON WIRELESS,-100.00
10/06/2026,REFUND COFFEE BAR,4.00
"""


def switched_on(tenant, actor=None):
    modules.set_enabled(tenant, modules.PERSONAL, True, actor=actor)


def chart_of(api, ff):
    return {row["name"]: row for row in get(api, ff, "/api/personal/categories")
            .json()["categories"]}


@pytest.fixture
def mixed(books, ff, api):
    """The practice's card, marked Mixed, with Personal finance switched on and
    three rules: Adobe is the practice's, Netflix the owner's, Verizon 60%
    business."""
    switched_on(books["tenant"])
    assert patch(api, ff, f"{A}{books['card']['id']}/", {"side": "mixed"}).json()["side"] \
        == "mixed"
    mine = chart_of(api, ff)
    assert post(api, ff, "/api/finance-rules/", {
        "contains": "ADOBE", "treat_as": "category",
        "category": books["cat"]["Software and subscriptions"]["id"]}).status_code == 201
    from apps.finance import rules as rule_service
    from apps.finance.models import FinanceCategory

    tenant = books["tenant"]
    rule_service.save_rule(tenant, actor=ff.user, contains="NETFLIX", treat_as="category",
                           side="personal",
                           personal_category=PersonalCategory.objects.get(
                               pk=mine["Entertainment and subscriptions"]["id"]))
    rule_service.save_rule(tenant, actor=ff.user, contains="VERIZON", treat_as="category",
                           category=FinanceCategory.all_objects.get(
                               pk=books["cat"]["Phone and internet"]["id"]),
                           side="split", split_percent=60,
                           personal_category=PersonalCategory.objects.get(
                               pk=mine["Phone and internet"]["id"]))
    return {**books, "mine": mine}


def lines(api, ff, query=""):
    return get(api, ff, L + query).json()


# ================================================ isolation, extended to a person

def test_every_personal_model_is_owned_and_registered():
    """The meta-test for the personal side: every model of the app hangs off a
    ledger and is in the family below, or this fails."""
    from django.apps import apps as django_apps

    found = {m for m in django_apps.get_app_config("personal").get_models()}
    assert found - {PersonalLedger} == set(personal_models.OWNED)
    for model in personal_models.OWNED:
        assert issubclass(model, personal_models.OwnedModel)


def make_owned(model, ledger):
    """One row of `model` in this ledger: every owned model has a way here,
    so a new one fails until it is given one."""
    m = personal_models
    today = timezone.localdate()

    def account():
        return m.PersonalAccount.objects.create(ledger=ledger, name="Joint checking",
                                                opening_on=today)

    def debt():
        return m.PersonalDebt.objects.create(ledger=ledger, name="Mortgage", kind="mortgage")

    def goal_envelope():
        goal = m.PersonalGoal.objects.create(ledger=ledger, name="Trip", target_cents=100)
        return m.PersonalEnvelope.objects.create(ledger=ledger, goal=goal,
                                                 start_month=today.replace(day=1))

    def batch():
        return m.PersonalImport.objects.create(ledger=ledger, account=account(),
                                               filename="joint.csv")

    ways = {
        m.PersonalCategory: lambda: PersonalCategory.objects.filter(ledger=ledger).first(),
        m.PersonalMember: lambda: m.PersonalMember.objects.create(ledger=ledger, name="Ann"),
        m.PersonalAccount: account,
        m.PersonalReconciliation: lambda: m.PersonalReconciliation.objects.create(
            ledger=ledger, account=account(), statement_on=today,
            statement_balance_cents=0, starting_balance_cents=0),
        m.PersonalLine: lambda: m.PersonalLine.objects.create(
            ledger=ledger, on_date=today, amount_cents=100, direction="out"),
        m.PersonalImport: batch,
        m.PersonalImportRow: lambda: m.PersonalImportRow.objects.create(
            ledger=ledger, batch=batch(), row_number=2, outcome="new"),
        m.PersonalDebt: debt,
        m.PersonalHolding: lambda: m.PersonalHolding.objects.create(
            ledger=ledger, name="401(k)", kind="retirement"),
        m.PersonalBalance: lambda: m.PersonalBalance.objects.create(
            ledger=ledger, debt=debt(), on_date=today, balance_cents=100),
        m.PersonalGoal: lambda: m.PersonalGoal.objects.create(
            ledger=ledger, name="Vacation", target_cents=100),
        m.PersonalSetAside: lambda: m.PersonalSetAside.objects.create(
            ledger=ledger, year=today.year),
        # Stop 2: the budget.
        m.PersonalEnvelope: lambda: m.PersonalEnvelope.objects.create(
            ledger=ledger, category=PersonalCategory.objects.filter(
                ledger=ledger, name="Groceries").first(), start_month=today.replace(day=1)),
        m.PersonalEnvelopeMove: lambda: m.PersonalEnvelopeMove.objects.create(
            ledger=ledger, month=today.replace(day=1), amount_cents=100,
            from_envelope=goal_envelope(), to_envelope=goal_envelope()),
        m.PersonalPlanned: lambda: m.PersonalPlanned.objects.create(
            ledger=ledger, name="Roof", on_date=today, amount_cents=100),
        m.PersonalQuestion: lambda: m.PersonalQuestion.objects.create(
            ledger=ledger, kind="coming", key=f"coming:{today}", text="Anything coming?"),
    }
    return ways[model]()


@pytest.mark.django_db
@pytest.mark.parametrize("model", personal_models.OWNED, ids=lambda m: m.__name__)
def test_one_persons_rows_are_never_anothers(model, seeded_tenant, tenant_b):
    """The isolation family's core promise, for a person: `of(user)` returns
    that person's rows and never another's."""
    a, b = _member(seeded_tenant, "FF").user, _member(tenant_b, "FF").user
    made = {}
    for user in (a, b):
        from apps.personal import services

        ledger = services.ledger_for(user)
        made[user] = make_owned(model, ledger)
    assert set(model.of(a).values_list("pk", flat=True)) & {made[b].pk} == set()
    assert made[a].pk in set(model.of(a).values_list("pk", flat=True))


@pytest.mark.django_db
def test_another_practice_owner_reaches_nothing_of_this_ledger(mixed, ff, api, tenant_b):
    batch = dry(api, ff, mixed, CARD, account="card", mapping=SIGNED)
    post(api, ff, f"{I}{batch['id']}/commit/")
    mine = lines(api, ff)["lines"]
    assert mine
    other = _member(tenant_b, "FF")
    switched_on(tenant_b)
    theirs = lines(api, other)
    assert theirs["lines"] == [] and theirs["to_sort"] == 0
    line = next(row for row in mine if row["kind"] == "line")
    assert patch(api, other, f"{L}/{line['id']}", {"category": None}).status_code == 404
    category = mixed["mine"]["Groceries"]["id"]
    assert patch(api, other, f"/api/personal/categories/{category}",
                 {"name": "Mine now"}).status_code == 404
    # Their ledger's category cannot be given to this owner's line either.
    their_groceries = chart_of(api, other)["Groceries"]["id"]
    assert patch(api, ff, f"{L}/{line['id']}",
                 {"category": their_groceries}).status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["CF", "VA", "FCC", "ECC"])
def test_nobody_else_in_the_practice_reaches_the_personal_side(mixed, api, role):
    company = ClientCompanyFactory(tenant=mixed["tenant"]) if role in ("FCC", "ECC") else None
    someone = _member(mixed["tenant"], role, company)
    for url in ("/api/personal/ledger", "/api/personal/categories", "/api/personal/accounts",
                L, L + "?to_sort=1"):
        assert get(api, someone, url).status_code == 404, url
    assert post(api, someone, "/api/personal/sort", {"side": "personal"}).status_code == 404
    assert PersonalLedger.objects.filter(owner=someone.user).count() == 0


@pytest.mark.django_db
def test_without_the_module_the_personal_side_is_not_there(books, ff, api):
    assert get(api, ff, L).status_code == 404
    # Nor can an account be made Mixed.
    assert patch(api, ff, f"{A}{books['card']['id']}/", {"side": "mixed"}).status_code == 404


@pytest.mark.django_db
def test_the_platform_owner_reaches_no_ledger(mixed, ff, api, platform_owner):
    client = in_practices_area(api.as_(platform_owner))
    for url in ("/api/personal/ledger", L, "/api/personal/accounts"):
        assert client.get(url).status_code == 404, url


@pytest.mark.django_db
def test_the_ledger_survives_its_owner_leaving_the_practice(mixed, ff, api):
    batch = dry(api, ff, mixed, CARD, account="card", mapping=SIGNED)
    post(api, ff, f"{I}{batch['id']}/commit/")
    before = PersonalLine.of(ff.user).filter(removed_at__isnull=True).count()
    assert before > 0
    ff.revoked_at = timezone.now()
    ff.save(update_fields=["revoked_at"])
    ledger = PersonalLedger.objects.get(owner=ff.user)
    assert PersonalLine.objects.filter(ledger=ledger, removed_at__isnull=True).count() == before


# ===================================== one Mixed card, imported once, both sides

@pytest.mark.django_db
def test_the_dry_run_shows_each_lines_side_beside_its_category(mixed, ff, api):
    batch = dry(api, ff, mixed, CARD, account="card", mapping=SIGNED)
    rows = rows_of(batch)
    assert rows["ADOBE *CREATIVE CLOUD"]["side"] == ""                       # a rule: business
    assert rows["ADOBE *CREATIVE CLOUD"]["category"]["name"] == "Software and subscriptions"
    assert rows["NETFLIX.COM"]["side"] == "personal"                         # a rule: personal
    assert rows["NETFLIX.COM"]["personal_category"]["name"] == "Entertainment and subscriptions"
    assert rows["VERIZON WIRELESS"]["side"] == "split"                       # a rule: 60/40
    assert rows["VERIZON WIRELESS"]["split_business_cents"] == 6000
    # No rule, under $25: personal, Everything else, without asking.
    assert rows["COFFEE BAR"]["side"] == "personal"
    assert rows["COFFEE BAR"]["personal_category"]["name"] == "Everything else"
    assert rows["REFUND COFFEE BAR"]["side"] == "personal"
    # No rule, $25 or more: it waits.
    assert rows["COSTCO WHOLESALE"]["side"] == "to_sort"
    assert batch["counts"]["to_sort"] == 1 and batch["counts"]["personal"] == 4
    assert FinanceEntry.all_objects.filter(tenant=mixed["tenant"]).count() == 0
    assert PersonalLine.objects.count() == 0


@pytest.mark.django_db
def test_commit_posts_each_side_to_its_place(mixed, ff, api):
    batch = dry(api, ff, mixed, CARD, account="card", mapping=SIGNED)
    assert post(api, ff, f"{I}{batch['id']}/commit/").status_code == 200
    live = FinanceEntry.all_objects.filter(tenant=mixed["tenant"], removed_at__isnull=True,
                                           account_id=mixed["card"]["id"])
    by = {(e.description, e.kind, e.side): e for e in live}
    # The practice's own line, as before.
    assert by[("ADOBE *CREATIVE CLOUD", "expense", "")].amount_cents == 5999
    # Personal lines are owner draws in the books (money in: a contribution).
    netflix = by[("NETFLIX.COM", "owner", "personal")]
    assert (netflix.direction, netflix.category.name, netflix.amount_cents) == (
        "out", "Owner draw", 2299)
    assert by[("REFUND COFFEE BAR", "owner", "personal")].category.name == \
        "Owner contribution"
    # A split is both: the business part an expense, the rest a draw.
    assert by[("VERIZON WIRELESS", "expense", "")].amount_cents == 6000
    assert by[("VERIZON WIRELESS", "owner", "personal")].amount_cents == 4000
    # To sort waits, uncategorized, outside the P&L's categories.
    assert by[("COSTCO WHOLESALE", "expense", "to_sort")].category is None
    # The card's balance is every line, whichever side: the bank's view.
    assert sum(e.amount_cents if e.direction == "out" else -e.amount_cents
               for e in live) == 5999 + 500 + 31240 + 2299 + 10000 - 400

    ledger = {row["description"]: row for row in lines(api, ff)["lines"]
              if row["kind"] == "line"}
    assert ledger["NETFLIX.COM"]["category"]["name"] == "Entertainment and subscriptions"
    assert ledger["NETFLIX.COM"]["account"]["name"] == "Business card"
    assert ledger["VERIZON WIRELESS"]["amount_cents"] == 4000
    assert ledger["COFFEE BAR"]["category"]["name"] == "Everything else"
    assert ledger["REFUND COFFEE BAR"]["direction"] == "in"
    assert "ADOBE *CREATIVE CLOUD" not in ledger and "COSTCO WHOLESALE" not in ledger
    waiting = lines(api, ff, "?to_sort=1")
    assert [row["description"] for row in waiting["lines"]] == ["COSTCO WHOLESALE"]
    assert waiting["to_sort"] == 1


@pytest.mark.django_db
def test_the_pnl_counts_only_the_business_side(mixed, ff, api):
    batch = dry(api, ff, mixed, CARD, account="card", mapping=SIGNED)
    post(api, ff, f"{I}{batch['id']}/commit/")
    pnl = get(api, ff, "/api/finance-reports/pnl/?year=2026").json()
    assert pnl["expenses"]["total"] == 5999 + 6000


@pytest.mark.django_db
def test_rollback_takes_back_both_sides(mixed, ff, api):
    batch = dry(api, ff, mixed, CARD, account="card", mapping=SIGNED)
    post(api, ff, f"{I}{batch['id']}/commit/")
    assert PersonalLine.objects.filter(removed_at__isnull=True).count() == 4
    assert post(api, ff, f"{I}{batch['id']}/rollback/").status_code == 200
    assert FinanceEntry.all_objects.filter(tenant=mixed["tenant"],
                                           removed_at__isnull=True).count() == 0
    assert PersonalLine.objects.filter(removed_at__isnull=True).count() == 0


@pytest.mark.django_db
def test_the_owner_sets_a_side_in_the_dry_run_and_it_is_remembered(mixed, ff, api):
    batch = dry(api, ff, mixed, CARD, account="card", mapping=SIGNED)
    costco = rows_of(batch)["COSTCO WHOLESALE"]
    groceries = mixed["mine"]["Groceries"]["id"]
    after = decide(api, ff, batch, costco, decision="entry", side="personal",
                   personal_category=groceries, remember="COSTCO")
    assert rows_of(after)["COSTCO WHOLESALE"]["side"] == "personal"
    rule = FinanceRule.all_objects.get(tenant=mixed["tenant"], contains="COSTCO")
    assert (rule.side, str(rule.personal_category_id)) == ("personal", groceries)
    # A split chosen by hand: the business part named in cents.
    adobe = rows_of(after)["ADOBE *CREATIVE CLOUD"]
    split = decide(api, ff, batch, adobe, decision="entry", side="split",
                   category=mixed["cat"]["Software and subscriptions"]["id"],
                   personal_category=mixed["mine"]["Entertainment and subscriptions"]["id"],
                   split_business_cents=3000)
    assert rows_of(split)["ADOBE *CREATIVE CLOUD"]["split_business_cents"] == 3000
    too_much = post(api, ff, f"{I}{batch['id']}/rows/{adobe['id']}/", {
        "decision": "entry", "side": "split",
        "category": mixed["cat"]["Software and subscriptions"]["id"],
        "split_business_cents": 5999})
    assert too_much.status_code == 400


@pytest.mark.django_db
def test_a_personal_rule_reaches_a_business_account_too(mixed, ff, api):
    """Decision 3: a personal line in a Business account is an owner draw."""
    text = "Date,Description,Amount\n10/07/2026,NETFLIX.COM,-22.99\n10/08/2026,LUNCH,-12.00\n"
    batch = dry(api, ff, mixed, text, account="bank", mapping=SIGNED)
    rows = rows_of(batch)
    assert rows["NETFLIX.COM"]["side"] == "personal"
    # A business account has no threshold: a line no rule placed is business.
    assert rows["LUNCH"]["side"] == ""
    post(api, ff, f"{I}{batch['id']}/commit/")
    assert FinanceEntry.all_objects.get(description="NETFLIX.COM").kind == "owner"


# ======================================================= sorting afterwards

@pytest.fixture
def committed(mixed, ff, api):
    batch = dry(api, ff, mixed, CARD, account="card", mapping=SIGNED)
    post(api, ff, f"{I}{batch['id']}/commit/")
    return mixed


@pytest.mark.django_db
def test_to_sort_is_sorted_to_either_side_and_learns(committed, ff, api):
    costco = FinanceEntry.all_objects.get(description="COSTCO WHOLESALE")
    sorted_ = post(api, ff, "/api/personal/sort", {
        "entry": str(costco.pk), "side": "personal",
        "personal_category": committed["mine"]["Groceries"]["id"], "remember": "COSTCO"})
    assert sorted_.status_code == 200, sorted_.content
    costco.refresh_from_db()
    assert (costco.kind, costco.side, costco.category.name) == ("owner", "personal",
                                                                "Owner draw")
    assert PersonalLine.objects.get(finance_entry=costco).category.name == "Groceries"
    assert lines(api, ff, "?to_sort=1")["to_sort"] == 0
    # Moved back to the practice's side: an expense again, and out of the ledger.
    back = post(api, ff, "/api/personal/sort", {
        "entry": str(costco.pk), "side": "business",
        "category": committed["cat"]["Supplies"]["id"]})
    assert back.status_code == 200, back.content
    costco.refresh_from_db()
    assert (costco.kind, costco.side) == ("expense", "")
    assert not PersonalLine.objects.filter(finance_entry=costco,
                                           removed_at__isnull=True).exists()
    # The next statement's Costco line goes personal by itself.
    text = "Date,Description,Amount\n11/03/2026,COSTCO WHOLESALE,-280.00\n"
    batch = dry(api, ff, committed, text, account="card", mapping=SIGNED)
    assert rows_of(batch)["COSTCO WHOLESALE"]["side"] == "personal"


@pytest.mark.django_db
def test_the_books_own_edits_keep_sides_true(committed, ff, api):
    netflix = FinanceEntry.all_objects.get(description="NETFLIX.COM")
    # A draw's amount changed in the books: its ledger line follows.
    assert patch(api, ff, f"{E}{netflix.pk}/", {"amount_cents": 2499}).status_code == 200
    assert PersonalLine.objects.get(finance_entry=netflix).amount_cents == 2499
    # Removed in the books: gone from the ledger, with the reason.
    assert post(api, ff, f"{E}{netflix.pk}/remove/", {"reason": "Duplicate"}).status_code == 200
    line = PersonalLine.objects.get(finance_entry=netflix)
    assert (line.removed_at is not None, line.remove_reason) == (True, "Duplicate")
    # To sort given a category in business Entries: the practice's now.
    costco = FinanceEntry.all_objects.get(description="COSTCO WHOLESALE")
    assert patch(api, ff, f"{E}{costco.pk}/", {
        "category": committed["cat"]["Supplies"]["id"]}).status_code == 200
    costco.refresh_from_db()
    assert costco.side == ""


@pytest.mark.django_db
def test_a_ledger_line_is_recategorized_alone_or_in_bulk(committed, ff, api):
    ledger = {row["description"]: row for row in lines(api, ff)["lines"]}
    dining = committed["mine"]["Dining"]["id"]
    one = patch(api, ff, f"{L}/{ledger['COFFEE BAR']['id']}",
                {"category": dining, "remember": "COFFEE BAR"})
    assert one.status_code == 200 and one.json()["category"]["name"] == "Dining"
    assert FinanceRule.all_objects.get(contains="COFFEE BAR").side == "personal"
    bulk = post(api, ff, f"{L}/bulk", {"lines": [ledger["COFFEE BAR"]["id"],
                                                  ledger["REFUND COFFEE BAR"]["id"]],
                                       "category": dining})
    assert bulk.json() == {"updated": 2}


# ================================================ the chart and the threshold

@pytest.mark.django_db
def test_the_personal_chart_carries_the_cpas_six_groups(mixed, ff, api):
    chart = chart_of(api, ff)
    for name, group in (("Prescriptions", "medical"), ("Medical premiums", "health_insurance"),
                        ("Mortgage interest", "interest"), ("Property taxes", "property_tax"),
                        ("Church", "charitable"), ("Non-cash donations", "non_cash"),
                        ("Groceries", "")):
        assert chart[name]["tax_group"] == group, name
    for top in ("Housing", "Utilities", "Giving", "Transfers", "Everything else", "Income"):
        assert chart[top]["parent"] is None
    assert chart["Pay from the practice"]["type"] == "income"
    marked = patch(api, ff, f"/api/personal/categories/{chart['Pets']['id']}",
                   {"tax_group": "charitable"})
    assert marked.json()["tax_group_label"] == "Charitable contributions"
    assert patch(api, ff, f"/api/personal/categories/{chart['Everything else']['id']}",
                 {"archived": True}).status_code == 409
    made = post(api, ff, "/api/personal/categories", {"name": "Lessons",
                                                      "parent": chart["Childcare and education"]["id"]})
    assert made.status_code == 201 and made.json()["type"] == "expense"


@pytest.mark.django_db
def test_the_threshold_is_the_owners(mixed, ff, api):
    assert get(api, ff, "/api/personal/ledger").json()["to_sort_threshold_cents"] == 2500
    patch(api, ff, "/api/personal/ledger", {"to_sort_threshold_cents": 400})
    rows = rows_of(dry(api, ff, mixed, CARD, account="card", mapping=SIGNED))
    assert rows["COFFEE BAR"]["side"] == "to_sort"          # $5 is over $4 now
    assert rows["REFUND COFFEE BAR"]["side"] == "to_sort"


@pytest.mark.django_db
def test_the_household_has_its_own_accounts_and_sees_the_mixed_ones(mixed, ff, api):
    made = post(api, ff, "/api/personal/accounts", {"name": "Joint checking", "kind": "bank",
                                                    "last4": "9911",
                                                    "opening_on": "2026-01-01"})
    assert made.status_code == 201, made.content
    listed = {row["name"]: row for row in get(api, ff, "/api/personal/accounts").json()}
    assert listed["Joint checking"]["side"] == "personal"
    assert listed["Business card"]["side"] == "mixed" and listed["Business card"]["in_books"]
    assert "Checking" not in listed                                  # business only
