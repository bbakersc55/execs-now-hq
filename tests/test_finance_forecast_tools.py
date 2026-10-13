"""P6 M2, the second stop (`docs/p6_m2_cash_forecast.md` §2.4, §3, §4, §6,
§6a): planned lines, the what-if, adjustments, how good it has been,
"Explain this forecast" and "Review with Claude".

1. Practice isolation and role boundaries on what the owner says.
2. Planned lines and the what-if: a look that saves nothing.
3. Adjustments: each does what it says from its date, and can be undone.
4. How good it has been.
5. The two Claude buttons: what is sent, the cap, and that nothing enters
   the forecast unconfirmed.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.billing import services as billing
from apps.finance import forecast, forecast_ai, reconcile
from apps.finance.disclaimer import DISCLAIMER
from apps.finance.models import (
    FinanceEntry, FinanceForecastAdjustment, FinanceForecastPlanned,
    FinanceForecastSnapshot,
)
from apps.tenancy import modules
from apps.tenancy.context import tenant_context
from apps.tenancy.models import AiCall, AuditEvent

from . import registry_config  # noqa: F401
from .conftest import _member
from .test_client_invoicing import (  # noqa: F401  (fixtures and helpers)
    LINES, TOTAL, a_client, acme, call, draft, ecc, get, patch, post, ready_to_bill, sent,
)
from .test_finance_books import A, C, E, R, add, books, snapshot  # noqa: F401
from .test_finance_forecast import (  # noqa: F401
    F, OPENING, OWED, THIS, TODAY, back, billing_ready, build, cash, closed, invoice, line,
    on,
)
from .test_finance_reconcile import RC, begin
from .test_finance_reconcile import M as MONTHS_URL

RENT = "Larimer Square Cowork"
RENT_CATEGORY = "Rent and coworking"


@pytest.fixture
def running(cash, ff, api):          # noqa: F811
    """Three closed months with a rent that is the same each month, a draw,
    and an advertising cost that varies."""
    closed(cash["tenant"], back(3), back(2), back(1))
    for month, ads in ((back(3), 10_000), (back(2), 30_000), (back(1), 20_000)):
        add(api, ff, cash, "expense", 69_500, on(month, 1), "Rent and coworking",
            counterparty=RENT)
        add(api, ff, cash, "expense", ads, on(month, 12), "Advertising",
            counterparty="LinkedIn Ads")
        add(api, ff, cash, "owner", 100_000, on(month, 28), "Draws", direction="out",
            counterparty="John Carter")
    return cash


def group_of(result, label):
    return next(row["group"] for row in result["lines"] if row["label"] == label)


def said(tenant) -> str:
    """Everything the owner has said about the forecast, and the books."""
    with tenant_context(tenant.pk):
        return json.dumps({
            "planned": list(FinanceForecastPlanned.objects.order_by("created_at").values(
                "pk", "description", "amount_cents", "removed_at", "happened_at")),
            "adjusted": list(FinanceForecastAdjustment.objects.order_by("created_at")
                             .values("pk", "line_key", "kind", "undone_at")),
            "entries": FinanceEntry.objects.count(),
            "audit": AuditEvent.objects.filter(verb__startswith="finance.").count(),
            "ai": AiCall.objects.count(),
        }, default=str, sort_keys=True)


# ============================================== isolation and role boundaries

@pytest.mark.django_db
def test_tenant_isolation_what_one_practice_says_is_not_in_anothers_forecast(
        running, ff, tenant_b, api, fake_claude):
    mine = get(api, ff, F).json()
    rent = group_of(mine, RENT)
    planned = post(api, ff, F + "planned/", {
        "description": "SECRET-HIRE", "amount_cents": 650_000,
        "on_date": (TODAY + timedelta(days=40)).isoformat()}).json()["planned"][0]
    adjusted = post(api, ff, F + "adjust/", {"line": rent, "kind": "amount",
                                             "amount_cents": 75_000}).json()
    adjustment = adjusted["adjustments"][0]["id"]
    before = said(running["tenant"])

    other = _member(tenant_b, "FF")
    for module in (modules.BOOKKEEPING, modules.FORECAST):
        modules.set_enabled(tenant_b, module, True, actor=other.user)
    closed(tenant_b, back(2), back(1))
    theirs = get(api, other, F)
    assert "SECRET-HIRE" not in theirs.content.decode() and RENT not in \
        theirs.content.decode()
    assert theirs.json()["planned"] == [] and theirs.json()["adjustments"] == []
    # Ours, by id, from theirs: not there.
    for method, url, body in (
            ("patch", f"{F}planned/{planned['id']}/", {"amount_cents": 1}),
            ("delete", f"{F}planned/{planned['id']}/", None),
            ("post", f"{F}planned/{planned['id']}/happened/", {}),
            ("post", f"{F}adjust/{adjustment}/undo/", {}),
            ("post", F + "adjust/", {"line": rent, "kind": "end"})):
        assert call(api.as_(other), method, url, body).status_code == 404, url
    # A what-if of theirs naming our line or our planned line changes nothing of theirs.
    looked = post(api, other, F + "what-if/", {"off": [rent], "on": [planned["id"]]}).json()
    assert looked["what_if"]["weeks"] == looked["weeks"]
    # And neither Claude button of theirs is sent anything of ours.
    fake_claude.reply = json.dumps({"one_offs": [], "missed": [], "questions": []})
    assert post(api, other, F + "explain/", {"view": "90"}).status_code == 200
    assert post(api, other, F + "review/", {}).status_code == 200
    everything = json.dumps(fake_claude.requests, default=str)
    assert "SECRET-HIRE" not in everything and RENT not in everything
    with tenant_context(tenant_b.pk):
        AiCall.objects.all().delete()
        AuditEvent.objects.all().delete()
    assert said(running["tenant"]) == before


@pytest.mark.django_db
def test_role_boundaries_only_the_practice_owner_says_anything_to_the_forecast(
        running, ff, cf, va, fcc, ecc, api, fake_claude):
    rent = group_of(get(api, ff, F).json(), RENT)
    planned = post(api, ff, F + "planned/", {
        "description": "SECRET-HIRE", "amount_cents": 650_000,
        "on_date": (TODAY + timedelta(days=40)).isoformat()}).json()["planned"][0]
    adjustment = post(api, ff, F + "adjust/", {
        "line": rent, "kind": "end"}).json()["adjustments"][0]["id"]
    before = said(running["tenant"])
    calls = [
        ("post", F + "what-if/", {"off": [rent]}),
        ("post", F + "planned/", {"description": "x", "amount_cents": 5,
                                  "on_date": TODAY.isoformat()}),
        ("patch", f"{F}planned/{planned['id']}/", {"amount_cents": 1}),
        ("delete", f"{F}planned/{planned['id']}/", None),
        ("post", f"{F}planned/{planned['id']}/happened/", {}),
        ("post", F + "adjust/", {"line": rent, "kind": "not_regular"}),
        ("post", f"{F}adjust/{adjustment}/undo/", {}),
        ("post", F + "client-names/", {"include": True}),
        ("get", F + "explain/", None), ("post", F + "explain/", {"view": "90"}),
        ("post", F + "review/", {})]
    for who, status in ((va, 403), (cf, 403), (fcc, 404), (ecc, 404)):
        for method, url, body in calls:
            response = call(api.as_(who), method, url, body)
            assert response.status_code == status, (who.role, method, url)
            assert b"SECRET-HIRE" not in response.content
    assert said(running["tenant"]) == before
    assert fake_claude.requests == [], "and nobody else's press reached Claude"


# ================================================== planned lines, the what-if

@pytest.mark.django_db
def test_a_planned_line_is_in_the_forecast_until_it_happens_or_is_removed(
        running, ff, api):
    tenant = running["tenant"]
    start = get(api, ff, F).json()
    with tenant_context(tenant.pk):
        entries = FinanceEntry.objects.count()
    when = TODAY + timedelta(days=20)
    made = post(api, ff, F + "planned/", {
        "description": "  New laptops ", "amount_cents": 480_000, "on_date": when.isoformat()})
    assert made.status_code == 201
    made = made.json()
    assert [(row["description"], row["state"], row["next_on"]) for row in made["planned"]] \
        == [("New laptops", "planned", when.isoformat())]
    [laptops] = line(made, "New laptops")
    assert (laptops["kind"], laptops["direction"], laptops["amount_cents"], laptops["counted"],
            laptops["detail"]) == ("planned", "out", 480_000, True, "Planned by you.")
    week = next(row for row in made["weeks"] if laptops["id"] in row["lines"])
    was = next(row for row in start["weeks"] if row["start"] == week["start"])
    assert week["out_cents"] == was["out_cents"] + 480_000
    assert made["weeks"][-1]["end_cents"] == start["weeks"][-1]["end_cents"] - 480_000
    # It never becomes an entry.
    with tenant_context(tenant.pk):
        assert FinanceEntry.objects.count() == entries

    # Every month until a date; every three months; money in.
    first = forecast._add_months(THIS, 2).replace(day=1)
    hire = post(api, ff, F + "planned/", {
        "description": "Operations analyst", "amount_cents": 650_000,
        "on_date": first.isoformat(), "repeat": "monthly",
        "until": forecast._add_months(first, 2).isoformat()}).json()
    assert [row["on_date"] for row in line(hire, "Operations analyst")] == [
        forecast._add_months(first, n).isoformat() for n in (0, 1, 2)]
    open_ended = post(api, ff, F + "planned/", {
        "description": "Insurance review", "amount_cents": 90_000,
        "on_date": first.isoformat(), "repeat": "quarterly"}).json()
    assert len(line(open_ended, "Insurance review")) == 4, "to the end of the 12 months"
    deposit = post(api, ff, F + "planned/", {
        "description": "Project deposit", "amount_cents": 500_000, "direction": "in",
        "on_date": when.isoformat()}).json()
    assert line(deposit, "Project deposit")[0]["direction"] == "in"

    planned = {row["description"]: row for row in deposit["planned"]}
    changed = patch(api, ff, f"{F}planned/{planned['New laptops']['id']}/",
                    {"amount_cents": 520_000})
    assert changed.status_code == 200
    assert line(changed.json(), "New laptops")[0]["amount_cents"] == 520_000
    # It happened: the real thing is in the books, so it leaves the forecast.
    done = post(api, ff, f"{F}planned/{planned['New laptops']['id']}/happened/").json()
    assert line(done, "New laptops") == []
    assert {row["description"]: row["state"] for row in done["planned"]}[
        "New laptops"] == "happened"
    # Not going to happen: removed, and not listed.
    gone = call(api.as_(ff), "delete", f"{F}planned/{planned['Project deposit']['id']}/",
                None).json()
    assert line(gone, "Project deposit") == []
    assert "Project deposit" not in [row["description"] for row in gone["planned"]]
    for method, tail in (("patch", ""), ("delete", ""), ("post", "happened/")):
        assert call(api.as_(ff), method, f"{F}planned/{planned['New laptops']['id']}/{tail}",
                    {"amount_cents": 1}).status_code == 409
    with tenant_context(tenant.pk):
        verbs = list(AuditEvent.objects.filter(verb__startswith="finance.forecast_planned")
                     .order_by("created_at").values_list("verb", flat=True))
    assert verbs == ["finance.forecast_planned_added"] * 4 + [
        "finance.forecast_planned_changed", "finance.forecast_planned_happened",
        "finance.forecast_planned_removed"]


@pytest.mark.django_db
def test_a_planned_line_can_repeat_every_year(running, ff, api):
    first = forecast._add_months(THIS, 5).replace(day=18)
    made = post(api, ff, F + "planned/", {
        "description": "Tax preparation", "amount_cents": 185_000,
        "on_date": first.isoformat(), "repeat": "yearly"})
    assert made.status_code == 201
    [row] = made.json()["planned"]
    assert (row["repeat"], row["next_on"]) == ("yearly", first.isoformat())
    assert [found["on_date"] for found in line(made.json(), "Tax preparation")] == [
        first.isoformat()], "once in the 12 months the forecast covers"
    refused = post(api, ff, F + "planned/", {
        "description": "Tax preparation", "amount_cents": 185_000,
        "on_date": first.isoformat(), "repeat": "weekly"})
    assert refused.status_code == 400
    assert refused.json()["detail"] == "repeat is monthly, quarterly, yearly, or nothing."


@pytest.mark.django_db
def test_a_planned_line_whose_date_passed_a_week_ago_is_asked_about_not_forecast(
        running, ff, api):
    with tenant_context(running["tenant"].pk):
        for days, text in ((3, "Just past"), (10, "Long past")):
            forecast.save_planned(running["tenant"], actor=ff.user, description=text,
                                  amount_cents=10_000,
                                  on_date=TODAY - timedelta(days=days))
    result = get(api, ff, F).json()
    assert {row["description"]: row["state"] for row in result["planned"]} == {
        "Just past": "planned", "Long past": "lapsed"}
    assert line(result, "Just past")[0]["on_date"] == TODAY.isoformat()
    assert line(result, "Long past") == []


@pytest.mark.django_db
def test_a_planned_line_is_refused_when_it_is_not_one(running, ff, api):
    good = {"description": "A hire", "amount_cents": 5_000, "on_date": TODAY.isoformat()}
    for change in ({"amount_cents": 0}, {"amount_cents": -5}, {"amount_cents": "5000"},
                   {"description": " "}, {"on_date": "soon"}, {"direction": "sideways"},
                   {"repeat": "weekly"}, {"is_what_if": "yes"},
                   {"until": (TODAY + timedelta(days=30)).isoformat()},      # does not repeat
                   {"repeat": "monthly", "until": (TODAY - timedelta(days=1)).isoformat()}):
        assert post(api, ff, F + "planned/", {**good, **change}).status_code == 400, change
    for missing in ("description", "amount_cents", "on_date"):
        body = {key: value for key, value in good.items() if key != missing}
        assert post(api, ff, F + "planned/", body).status_code == 400, missing
    assert get(api, ff, F).json()["planned"] == []


@pytest.mark.django_db
def test_a_what_if_is_a_look_that_recomputes_and_saves_nothing(
        running, billing_ready, ff, api):
    tenant = running["tenant"]
    globex, contact = a_client(tenant, name="Globex Logistics")
    acme_co, acme_contact = a_client(tenant, name="Acme Fasteners", first="Ann")
    for company, person in ((globex, contact), (acme_co, acme_contact)):
        made = post(api, ff, "/api/invoice-schedules/", {
            "client_company": str(company.pk), "contact": str(person.pk), "day_of_month": 1,
            "starts_on": forecast._add_months(THIS, 1).isoformat(), "lines": LINES})
        assert made.status_code == 201
    what_if_line = post(api, ff, F + "planned/", {
        "description": "A second associate", "amount_cents": 400_000, "repeat": "monthly",
        "on_date": forecast._add_months(THIS, 1).isoformat(), "is_what_if": True}).json()
    planned = what_if_line["planned"][0]
    assert planned["state"] == "what_if"
    base = get(api, ff, F).json()
    # A what-if planned line is drawn, and not counted, until it is switched on.
    assert all(not row["counted"] and row["what_if"]
               for row in line(base, "A second associate"))
    assert base["what_if"] is None
    assert [row["name"] for row in base["clients"]] == ["Acme Fasteners", "Globex Logistics"]
    before = said(tenant)

    def look(**body):
        response = post(api, ff, F + "what-if/", body)
        assert response.status_code == 200, response.content
        result = response.json()
        # The forecast as it stands is the same, whatever is tried.
        for key in ("weeks", "months", "views", "lines"):
            assert result[key] == base[key], key
        return result["what_if"]

    months = 11                      # the invoices of 11 schedule runs are due in the year
    # Remove a client: every line of theirs.
    without = look(off=[f"client:{globex.pk}"])
    assert without["months"][-1]["end_cents"] == base["months"][-1]["end_cents"] \
        - months * TOTAL
    assert without["difference_at_low"]["months"] == \
        without["views"]["months"]["low_cents"] - base["views"]["months"]["low_cents"]
    # Add a recurring cost: the what-if line, switched on.
    with_hire = look(on=[planned["id"]])
    hired = len(line(base, "A second associate"))
    assert with_hire["months"][-1]["end_cents"] == base["months"][-1]["end_cents"] \
        - hired * 400_000
    # Change a draw: another amount for the line, tried and not kept.
    draw = group_of(base, "John Carter")
    draws = len(line(base, "John Carter"))
    smaller = look(amounts={draw: 60_000})
    assert smaller["months"][-1]["end_cents"] == base["months"][-1]["end_cents"] \
        + draws * 40_000
    # One regular line switched off; and all three at once.
    rent, rents = group_of(base, RENT), len(line(base, RENT))
    assert look(off=[rent])["months"][-1]["end_cents"] == \
        base["months"][-1]["end_cents"] + rents * 69_500
    all_three = look(off=[f"client:{globex.pk}"], on=[planned["id"]],
                     amounts={draw: 60_000})
    assert all_three["months"][-1]["end_cents"] == base["months"][-1]["end_cents"] \
        - months * TOTAL - hired * 400_000 + draws * 40_000
    for rows in (all_three["weeks"], all_three["months"]):
        for index, row in enumerate(rows):
            assert row["end_cents"] == row["start_cents"] + row["in_cents"] - row["out_cents"]
            assert not index or row["start_cents"] == rows[index - 1]["end_cents"]
    # Nothing was saved by any of it.
    assert said(tenant) == before
    assert get(api, ff, F).json()["what_if"] is None
    for bad in ({"off": "everything"}, {"amounts": [1, 2]}, {"amounts": {draw: -5}}):
        assert post(api, ff, F + "what-if/", bad).status_code == 400, bad


@pytest.mark.django_db
def test_a_what_if_on_a_card_charge_moves_the_cards_payment(running, ff, api):
    cash_kit = running
    for month in (back(3), back(2), back(1)):
        add(api, ff, cash_kit, "expense", 9_900, on(month, 11), "Software", account="card",
            counterparty="Intuit")
        post(api, ff, E, {"kind": "transfer", "amount_cents": 9_900, "on_date": on(month, 20),
                          "account": cash_kit["bank"]["id"],
                          "to_account": cash_kit["card"]["id"]})
    base = get(api, ff, F).json()
    intuit = group_of(base, "Intuit")
    looked = post(api, ff, F + "what-if/", {"off": [intuit]}).json()["what_if"]
    paid = sum(row["amount_cents"] for row in line(base, "Business card payment")[1:])
    assert paid > 0
    assert looked["months"][-1]["end_cents"] == base["months"][-1]["end_cents"] + paid


# ================================================================ adjustments

@pytest.mark.django_db
def test_each_adjustment_does_what_it_says_from_its_date_and_can_be_undone(
        running, ff, api):
    tenant = running["tenant"]
    base = get(api, ff, F).json()
    rent, ads, draw = (group_of(base, name) for name in (RENT, "LinkedIn Ads", "John Carter"))
    january = forecast._add_months(THIS, 3)

    def adjust(**body):
        response = post(api, ff, F + "adjust/", body)
        assert response.status_code == 201, response.content
        return response.json()

    # The rent goes to $750 in three months' time: before that, as it was.
    raised = adjust(line=rent, kind="amount", amount_cents=75_000,
                    from_date=january.isoformat())
    rows = line(raised, RENT)
    assert {row["amount_cents"] for row in rows if row["on_date"] < january.isoformat()} \
        == {69_500}
    assert {row["amount_cents"] for row in rows if row["on_date"] >= january.isoformat()} \
        == {75_000}
    later = next(row for row in rows if row["on_date"] >= january.isoformat())
    assert later["adjusted"] == f"You set it to $750.00 from {forecast._long(january)}."
    assert raised["adjustments"][0]["text"] == later["adjusted"]
    assert raised["adjustments"][0]["by"] == ff.user.full_name
    assert raised["adjustments"][0]["label"] == RENT
    # Advertising moves to the 25th, from now.
    moved = adjust(line=ads, kind="day", day_of_month=25)
    assert {date.fromisoformat(row["on_date"]).day for row in line(moved, "LinkedIn Ads")
            if row["on_date"] > TODAY.replace(day=28).isoformat()} == {25}
    # Draws are paused for two months, then resume.
    resume = forecast._add_months(THIS, 2).replace(day=27)
    paused = adjust(line=draw, kind="pause", from_date=TODAY.isoformat(),
                    until_date=resume.isoformat())
    days = [row["on_date"] for row in line(paused, "John Carter")]
    assert days and min(days) > resume.isoformat()
    assert len(days) == len(line(base, "John Carter")) - len(
        [row for row in line(base, "John Carter") if row["on_date"] <= resume.isoformat()])
    # Advertising ends in six months.
    stop = forecast._add_months(THIS, 6)
    ended = adjust(line=ads, kind="end", from_date=stop.isoformat())
    assert max(row["on_date"] for row in line(ended, "LinkedIn Ads")) < stop.isoformat()
    # "This is not regular": it is gone.
    assert line(adjust(line=rent, kind="not_regular"), RENT) == []

    # Each is kept, shown beside its line with when and by whom, and undone.
    now = get(api, ff, F).json()
    assert [(row["label"], row["kind"]) for row in now["adjustments"]] == [
        (RENT, "not_regular"), ("LinkedIn Ads", "end"), ("John Carter", "pause"),
        ("LinkedIn Ads", "day"), (RENT, "amount")]
    for row in now["adjustments"]:
        assert post(api, ff, f"{F}adjust/{row['id']}/undo/").status_code == 200
        assert post(api, ff, f"{F}adjust/{row['id']}/undo/").status_code == 409
    back_to = get(api, ff, F).json()
    assert back_to["adjustments"] == []
    for key in ("weeks", "months", "lines"):
        assert back_to[key] == base[key], "undone, the forecast is as the books give it"
    with tenant_context(tenant.pk):
        assert AuditEvent.objects.filter(verb="finance.forecast_adjusted").count() == 5
        assert AuditEvent.objects.filter(
            verb="finance.forecast_adjustment_undone").count() == 5
        assert FinanceForecastAdjustment.objects.count() == 5, "kept, not deleted"


@pytest.mark.django_db
def test_an_adjustment_outlives_the_next_close(running, ff, api):
    tenant = running["tenant"]
    rent = group_of(get(api, ff, F).json(), RENT)
    post(api, ff, F + "adjust/", {"line": rent, "kind": "amount", "amount_cents": 75_000})
    # Another month is entered and closed: the cost is found again, and what
    # the owner said still holds.
    with tenant_context(tenant.pk):
        future = forecast.build(tenant, forecast._add_months(TODAY, 1), snapshot=False)
    assert {row["amount_cents"] for row in line(future, RENT)} == {75_000}
    add(api, ff, running, "expense", 69_500, on(THIS, 1), "Rent and coworking",
        counterparty=RENT)
    closed(tenant, THIS)
    with tenant_context(tenant.pk):
        after = forecast.build(tenant, forecast._add_months(TODAY, 1), snapshot=False)
    rows = line(after, RENT)
    assert rows and {row["amount_cents"] for row in rows} == {75_000}
    assert "the same amount of 3 of the last 3 closed months" in rows[0]["detail"]


@pytest.mark.django_db
def test_an_invoice_is_moved_left_out_and_put_back(running, billing_ready, ff, api):
    company, contact = a_client(running["tenant"])
    due = TODAY + timedelta(days=10)
    coming = invoice(api, ff, company, contact, TODAY, due)
    old = invoice(api, ff, company, contact, TODAY - timedelta(days=90),
                  TODAY - timedelta(days=75))
    base = get(api, ff, F).json()
    assert [row["id"] for row in base["left_out"]] == [old["id"]]
    # "She told me the 25th."
    told = TODAY + timedelta(days=25)
    moved = post(api, ff, F + "adjust/", {"line": f"invoice:{coming['id']}",
                                          "kind": "expected",
                                          "expected_on": told.isoformat()}).json()
    row = next(row for row in moved["lines"] if row["id"] == f"invoice:{coming['id']}")
    assert row["on_date"] == told.isoformat()
    assert row["adjusted"] == f"You expect it on {forecast._long(told)}."
    # One long overdue is put back, with a date.
    put_back = post(api, ff, F + "adjust/", {"line": f"invoice:{old['id']}",
                                             "kind": "expected",
                                             "expected_on": told.isoformat()}).json()
    assert put_back["left_out"] == []
    assert any(row["id"] == f"invoice:{old['id']}" and row["on_date"] == told.isoformat()
               for row in put_back["lines"])
    # And one that is coming is left out.
    left = post(api, ff, F + "adjust/", {"line": f"invoice:{coming['id']}",
                                         "kind": "leave_out"}).json()
    assert [(row["id"], row["why"]) for row in left["left_out"]] == [
        (coming["id"], "left out by you")]
    assert left["left_out"][0]["adjustment"]
    undone = post(api, ff, f"{F}adjust/{left['left_out'][0]['adjustment']}/undo/").json()
    assert undone["left_out"] == []


@pytest.mark.django_db
def test_an_adjustment_is_refused_when_the_line_cannot_take_it(
        running, billing_ready, ff, api):
    company, contact = a_client(running["tenant"])
    coming = invoice(api, ff, company, contact, TODAY, TODAY + timedelta(days=10))
    rent = group_of(get(api, ff, F).json(), RENT)
    bill = f"invoice:{coming['id']}"
    for body, status in (
            ({"line": "pattern:nothing|of|ours", "kind": "end"}, 404),
            ({"line": "", "kind": "end"}, 404),
            ({"line": rent, "kind": "expected", "expected_on": TODAY.isoformat()}, 400),
            ({"line": rent, "kind": "leave_out"}, 400),
            ({"line": bill, "kind": "amount", "amount_cents": 5}, 400),
            ({"line": bill, "kind": "expected"}, 400),
            ({"line": rent, "kind": "amount"}, 400),
            ({"line": rent, "kind": "amount", "amount_cents": 0}, 400),
            ({"line": rent, "kind": "day", "day_of_month": 32}, 400),
            ({"line": rent, "kind": "pause", "from_date": TODAY.isoformat(),
              "until_date": (TODAY - timedelta(days=1)).isoformat()}, 400),
            ({"line": rent, "kind": "resize"}, 400)):
        assert post(api, ff, F + "adjust/", body).status_code == status, body
    assert get(api, ff, F).json()["adjustments"] == []


# ===================================================== how good it has been

@pytest.mark.django_db
def test_the_forecast_for_a_month_is_kept_once_and_set_beside_what_happened(
        running, ff, api):
    tenant = running["tenant"]
    # The first time the forecast is worked out in the month, it is kept.
    assert get(api, ff, F).json()["history"] == []
    with tenant_context(tenant.pk):
        kept = FinanceForecastSnapshot.objects.get()
        assert (kept.month, kept.taken_on, kept.actual) == (THIS, TODAY, None)
        first = dict(kept.forecast)
    result = get(api, ff, F).json()
    last = reconcile.month_end(THIS).isoformat()
    mine = [row for row in result["lines"] if row["counted"] and row["on_date"] <= last]
    assert first["start_cents"] == result["cash_today_cents"]
    assert first["out_cents"] == sum(r["amount_cents"] for r in mine if r["direction"] == "out")
    assert first["end_cents"] == first["start_cents"] + first["in_cents"] - first["out_cents"]
    assert first["by"]["Rent and coworking"] == {"in": 0, "out": 69_500}
    # Looked at again, with the books and the plans changed: it is not changed.
    post(api, ff, F + "planned/", {"description": "Laptops", "amount_cents": 480_000,
                                   "on_date": TODAY.isoformat()})
    add(api, ff, running, "expense", 5_000, TODAY.isoformat(), "Meals")
    get(api, ff, F)
    with tenant_context(tenant.pk):
        assert FinanceForecastSnapshot.objects.get().forecast == first
        assert FinanceForecastSnapshot.objects.count() == 1


@pytest.mark.django_db
def test_the_job_keeps_the_months_forecast_and_the_first_look_is_the_fallback(
        running, ff, api, monkeypatch):
    from django.core.management import call_command
    from zoneinfo import ZoneInfo

    from django_q.models import Schedule

    from apps.finance import tasks

    tenant = running["tenant"]
    # Registered for the practice, daily, at its own midnight.
    call_command("ensure_schedules", stdout=open("/dev/null", "w"))
    schedule = Schedule.objects.get(name=f"finance.keep_month_forecast:{tenant.slug}")
    assert schedule.func == "apps.finance.tasks.keep_month_forecast"
    assert schedule.schedule_type == Schedule.DAILY
    assert schedule.next_run.astimezone(ZoneInfo(tenant.timezone)).hour == 0

    # On the 1st, before anyone has looked: the month's forecast is kept, from
    # the 1st, by the practice's own date.
    monkeypatch.setattr(tasks, "_today", lambda practice: THIS)
    assert tasks.keep_month_forecast(str(tenant.pk)) is True
    with tenant_context(tenant.pk):
        kept = FinanceForecastSnapshot.objects.get()
        assert (kept.month, kept.taken_on, kept.actual) == (THIS, THIS, None)
        first = dict(kept.forecast)
        assert first == forecast_as_looked_at(tenant, THIS)
    # The next day's run, and a look at the screen, leave it as it was.
    monkeypatch.setattr(tasks, "_today", lambda practice: THIS + timedelta(days=1))
    assert tasks.keep_month_forecast(str(tenant.pk)) is False
    get(api, ff, F)
    with tenant_context(tenant.pk):
        assert FinanceForecastSnapshot.objects.get().forecast == first

    # A 1st the worker missed is made up by its next run, with its real day.
    with tenant_context(tenant.pk):
        FinanceForecastSnapshot.objects.all().delete()
    assert tasks.keep_month_forecast(str(tenant.pk)) is True
    with tenant_context(tenant.pk):
        assert FinanceForecastSnapshot.objects.get().taken_on == THIS + timedelta(days=1)

    # And a practice the job has not reached: the first look still keeps it.
    with tenant_context(tenant.pk):
        FinanceForecastSnapshot.objects.all().delete()
    get(api, ff, F)
    with tenant_context(tenant.pk):
        assert FinanceForecastSnapshot.objects.get().taken_on == TODAY


def forecast_as_looked_at(tenant, day):
    """What a look at the forecast on this day would have kept."""
    result = forecast.build(tenant, day, snapshot=False)
    last = reconcile.month_end(day.replace(day=1)).isoformat()
    mine = [row for row in result["lines"] if row["counted"] and row["on_date"] <= last]
    money_in = sum(r["amount_cents"] for r in mine if r["direction"] == "in")
    money_out = sum(r["amount_cents"] for r in mine if r["direction"] == "out")
    by: dict = {}
    for row in mine:
        name = ("Client invoices" if row["kind"] == "known"
                else row["category"] or row["label"])
        by.setdefault(name, {"in": 0, "out": 0})[row["direction"]] += row["amount_cents"]
    start = result["cash_today_cents"]
    return {"start_cents": start, "in_cents": money_in, "out_cents": money_out,
            "end_cents": start + money_in - money_out, "by": by}


@pytest.mark.django_db
def test_the_job_leaves_alone_a_practice_without_the_module_or_the_months(
        cash, ff, api):          # noqa: F811
    from apps.finance import tasks

    tenant = cash["tenant"]
    # The module, and not yet the closed months a forecast needs.
    assert tasks.keep_month_forecast(str(tenant.pk)) is False
    closed(tenant, back(3), back(2), back(1))
    modules.set_enabled(tenant, modules.FORECAST, False, actor=ff.user)
    assert tasks.keep_month_forecast(str(tenant.pk)) is False
    with tenant_context(tenant.pk):
        assert not FinanceForecastSnapshot.objects.exists()
    modules.set_enabled(tenant, modules.FORECAST, True, actor=ff.user)
    assert tasks.keep_month_forecast(str(tenant.pk)) is True


@pytest.mark.django_db
def test_tenant_isolation_the_job_keeps_only_its_own_practices_forecast(
        running, tenant_b):
    from apps.finance import tasks

    mine = running["tenant"]
    other = _member(tenant_b, "FF")
    for module in (modules.BOOKKEEPING, modules.FORECAST):
        modules.set_enabled(tenant_b, module, True, actor=other.user)
    closed(tenant_b, back(2), back(1))
    assert tasks.keep_month_forecast(str(mine.pk)) is True
    assert list(FinanceForecastSnapshot.all_objects.values_list("tenant_id", flat=True)) \
        == [mine.pk], "the other practice's is not kept by this one's run"
    kept = FinanceForecastSnapshot.all_objects.get(tenant=mine).forecast
    assert kept["start_cents"] > 0 and RENT_CATEGORY in kept["by"]
    assert tasks.keep_month_forecast(str(tenant_b.pk)) is True
    theirs = FinanceForecastSnapshot.all_objects.get(tenant=tenant_b).forecast
    assert theirs["start_cents"] == 0 and theirs["by"] == {}, "none of this one's books"
    assert FinanceForecastSnapshot.all_objects.get(tenant=mine).forecast == kept


@pytest.mark.django_db
def test_how_good_it_has_been_is_the_differences_with_no_score(running, ff, api):
    tenant = running["tenant"]
    month = back(1)
    # As it stood when last month began: rent, advertising, the card, a draw.
    with tenant_context(tenant.pk):
        from apps.finance.models import FinanceMonthClose

        FinanceMonthClose.objects.filter(month=month).delete()
        closed(tenant, back(4))
        stood = forecast.build(tenant, month)          # looked at on the 1st
        kept = FinanceForecastSnapshot.objects.get(month=month)
        assert kept.taken_on == month
        closed(tenant, month)
        forecast.month_closed(tenant, month)
        kept.refresh_from_db()
        assert kept.actual is not None
    [shown] = get(api, ff, F).json()["history"]
    assert (shown["month"], shown["label"], shown["taken_on"]) == (
        month.isoformat()[:7], reconcile.month_name(month), month.isoformat())
    # What happened, from the books, after it was taken. (The rent of the 1st
    # was already in the books that morning: in the cash it started from, and
    # so neither forecast nor counted again.)
    assert shown["actual"] == {"in_cents": 0, "out_cents": 20_000 + 100_000,
                               "end_cents": OPENING - 3 * (69_500 + 100_000)
                               - (10_000 + 30_000 + 20_000)}
    assert shown["forecast"]["out_cents"] == sum(
        row["amount_cents"] for row in stood["lines"]
        if row["counted"] and row["direction"] == "out"
        and row["on_date"] <= reconcile.month_end(month).isoformat())
    # The largest differences, by line, biggest first; nothing that agreed.
    names = [row["name"] for row in shown["largest"]]
    assert "Rent and coworking" not in names, "forecast and actual agreed"
    assert len(shown["largest"]) <= 3
    gaps = [abs(row["difference_cents"]) for row in shown["largest"]]
    assert gaps == sorted(gaps, reverse=True) and all(gaps)
    for row in shown["largest"]:
        assert row["difference_cents"] == row["actual_cents"] - row["forecast_cents"]
    assert "score" not in json.dumps(shown) and "accuracy" not in json.dumps(shown)


@pytest.mark.django_db
def test_closing_a_month_sets_what_happened_beside_its_forecast(cash, ff, api):          # noqa: F811
    """Through the close itself: the hook, not the function."""
    tenant = cash["tenant"]
    last, before = back(1), back(2)
    closed(tenant, back(4), back(3))
    add(api, ff, cash, "expense", 12_000, on(before, 5), "Travel")
    with tenant_context(tenant.pk):
        from .factories import FinanceForecastSnapshotFactory

        FinanceForecastSnapshotFactory(
            tenant=tenant, month=before, taken_on=before,
            forecast={"start_cents": OPENING, "in_cents": 0, "out_cents": 10_000,
                      "end_cents": OPENING - 10_000,
                      "by": {"Travel": {"in": 0, "out": 10_000}}})
    for account, balance in (("bank", OPENING - 12_000), ("card", OWED)):
        rec = begin(api, ff, cash, account, before, balance).json()
        post(api, ff, f"{RC}{rec['id']}/tick/", {"all": True})
        assert post(api, ff, f"{RC}{rec['id']}/finish/").status_code == 200
    assert post(api, ff, f"{MONTHS_URL}{before.isoformat()[:7]}/close/").status_code == 200
    with tenant_context(tenant.pk):
        kept = FinanceForecastSnapshot.objects.get(month=before)
    assert kept.actual == {"in_cents": 0, "out_cents": 12_000, "end_cents": OPENING - 12_000,
                           "by": {"Travel": {"in": 0, "out": 12_000}}}
    shown = get(api, ff, F).json()["history"]
    assert shown[0]["largest"] == [{"name": "Travel", "forecast_cents": -10_000,
                                    "actual_cents": -12_000, "difference_cents": -2_000}]
    assert last > before


@pytest.mark.django_db
def test_how_good_it_has_been_shows_the_last_six_closed_months(running, ff, api):
    tenant = running["tenant"]
    with tenant_context(tenant.pk):
        from .factories import FinanceForecastSnapshotFactory

        closed(tenant, *[back(n) for n in range(10, 3, -1)])
        for n in range(10, 0, -1):
            FinanceForecastSnapshotFactory(tenant=tenant, month=back(n), taken_on=back(n))
        FinanceForecastSnapshotFactory(tenant=tenant, month=THIS, taken_on=THIS)
    shown = get(api, ff, F).json()["history"]
    assert [row["month"] for row in shown] == [back(n).isoformat()[:7] for n in range(1, 7)]
    assert all(row["actual"]["end_cents"] is not None for row in shown), \
        "this month is open, and is not among them"


# =========================================================== a likely annual

@pytest.mark.django_db
def test_a_likely_annual_item_enters_the_forecast_only_when_confirmed(cash, ff, api):          # noqa: F811
    closed(cash["tenant"], *[back(n) for n in range(13, 0, -1)])
    add(api, ff, cash, "expense", 119_900, on(back(12), 8), "Software",
        counterparty="Adobe annual plan")
    [found] = get(api, ff, F).json()["likely_annual"]
    assert line(get(api, ff, F).json(), "Adobe annual plan") == []
    # Confirmed, with the amount and date the owner chose: a planned line.
    confirmed = post(api, ff, F + "planned/", {
        "description": "Adobe annual plan", "amount_cents": 131_900,
        "on_date": (TODAY + timedelta(days=5)).isoformat(), "source": "annual",
        "line": found["group"]})
    assert confirmed.status_code == 201
    confirmed = confirmed.json()
    assert confirmed["likely_annual"] == [], "no longer to confirm"
    [row] = line(confirmed, "Adobe annual plan")
    assert (row["kind"], row["amount_cents"], row["detail"]) == (
        "planned", 131_900, "Planned by you. Confirmed as annual.")
    assert confirmed["planned"][0]["source"] == "annual"
    # Or it is said not to be regular, and is not listed again.
    add(api, ff, cash, "expense", 30_000, on(back(12), 9), "Supplies",
        counterparty="Trade show booth")
    [other] = get(api, ff, F).json()["likely_annual"]
    said_no = post(api, ff, F + "adjust/", {"line": other["group"], "kind": "not_regular"})
    assert said_no.status_code == 201 and said_no.json()["likely_annual"] == []


# ======================================================= explain this forecast

@pytest.fixture
def with_clients(running, billing_ready, ff, api):
    tenant = running["tenant"]
    company, contact = a_client(tenant, name="Globex Logistics")
    made = invoice(api, ff, company, contact, TODAY, TODAY + timedelta(days=10))
    other, other_contact = a_client(tenant, name="Acme Fasteners", first="Ann")
    post(api, ff, "/api/invoice-schedules/", {
        "client_company": str(other.pk), "contact": str(other_contact.pk), "day_of_month": 1,
        "starts_on": forecast._add_months(THIS, 1).isoformat(), "lines": LINES})
    for month in (back(3), back(2), back(1)):
        add(api, ff, running, "income", 12_300, on(month, 9), "Referral fees received",
            counterparty="Welton Partners")
    post(api, ff, F + "floor/", {"floor_cents": 200_000})
    return {**running, "invoice": made, "contact": contact}


@pytest.mark.django_db
def test_explain_sends_nothing_until_pressed_and_never_a_clients_name(
        with_clients, ff, api, fake_claude):
    tenant = with_clients["tenant"]
    fake_claude.reply = "The low point is the week the card and the draw both go out."
    get(api, ff, F)
    price = get(api, ff, F + "explain/").json()
    assert fake_claude.requests == []
    assert price["refused"] == "" and price["cap"] == 20 and price["used_today"] == 0
    assert Decimal(price["estimate_usd"]) > 0 and Decimal(price["review_estimate_usd"]) > 0
    assert price["include_client_names"] is False
    before = said(tenant)

    answer = post(api, ff, F + "explain/", {"view": "90"})
    assert answer.status_code == 200
    answer = answer.json()
    assert answer["text"].startswith("The low point is the week")
    assert answer["disclaimer"] == DISCLAIMER and answer["used_today"] == 1
    assert Decimal(answer["cost_usd"]) > 0
    [request] = fake_claude.requests
    text = request["messages"][0]["content"]
    result = get(api, ff, F).json()
    lines_ = text.splitlines()
    assert lines_[0] == f"CASH FORECAST, the next 90 days, as of {TODAY.isoformat()}"
    assert lines_[1] == f"Cash today: ${result['cash_today_cents'] / 100:,.2f}"
    assert lines_[2] == "Floor the owner wants to stay above: $2,000.00"
    assert lines_[3].startswith("Low point: ")
    weeks = lines_[lines_.index("WEEKS (start | cash at start | in | out | cash at end):") + 1:]
    assert len([row for row in weeks if row.startswith(f"- {TODAY.year}") and
                row.count("|") == 4]) == 13
    # An expense's payee and category go by name...
    assert f"| regular | out | $695.00 | {RENT} (Rent and coworking) | monthly" in text
    assert "LinkedIn Ads (Marketing and advertising: Advertising)" in text
    # ...a client never does: a letter, the same for the same client throughout.
    for name in ("Globex", "Acme", "Welton", "Dana", with_clients["invoice"]["number"],
                 "INV-", ff.user.email, tenant.name, "Checking"):
        assert name not in json.dumps(request, default=str), name
    assert "| known | in | $6,800.00 | Client B: invoice" in text
    assert text.count("Client A: recurring invoice | monthly") >= 2
    assert "Client C (Referral fees received)" in text, "anyone money comes in from"
    system = request["system"]
    assert "ask your CPA" in system and "must not say you did" in system
    assert "Do not invent, estimate or suggest any amount of money" in system
    # It changed nothing but its own `ai_call`.
    after = json.loads(said(tenant))
    assert after.pop("ai") == 1 and {**json.loads(before), "ai": 1} == {**after, "ai": 1}
    with tenant_context(tenant.pk):
        row = AiCall.objects.get()
        assert (row.purpose, row.trigger, row.succeeded) == (
            "finance_explain_forecast", "button", True)
    for bad in ("7", "months", ""):
        refused = post(api, ff, F + "explain/", {"view": bad})
        assert refused.status_code == (200 if bad == "" else 400), bad


@pytest.mark.django_db
def test_explain_and_review_leave_room_for_the_models_reasoning(
        with_clients, ff, api, fake_claude):
    """Found on the demo, 2026-10-13: "Explain this forecast" came back "cut
    off or empty" every time. The model reasons before it writes, the
    reasoning is counted against `max_tokens`, and 800 did not hold both. The
    double answers as the API does: a thinking block, then the text."""
    fake_claude.thinking_tokens = 3000
    fake_claude.reply = (
        "The low point is the week of the 26th, when the card's payment and your draw "
        "both go out before Client A's recurring invoice lands. Rent and the card move "
        "it most. Moving the draw a week later would lift it above your floor.")
    answer = post(api, ff, F + "explain/", {"view": "90"})
    assert answer.status_code == 200, answer.json()
    assert answer.json()["text"] == fake_claude.reply
    assert fake_claude.requests[-1]["output_config"] == {"effort": "low"}

    fake_claude.reply = json.dumps({"one_offs": [], "missed": [], "questions": [
        {"topic": "hire", "question": "Are you planning to hire in the next six months?"}]})
    answer = post(api, ff, F + "review/", {})
    assert answer.status_code == 200, answer.json()
    assert [row["topic"] for row in answer.json()["questions"]] == ["hire"]

    # An answer that truly does not fit is still refused, not shown in part.
    fake_claude.thinking_tokens = 20000
    cut = post(api, ff, F + "explain/", {"view": "90"})
    assert cut.status_code == 502 and "cut off or empty" in json.dumps(cut.json())


@pytest.mark.django_db
def test_the_setting_lifts_the_letters_and_is_the_owners_and_audited(
        with_clients, ff, api, fake_claude):
    tenant = with_clients["tenant"]
    assert get(api, ff, F).json()["include_client_names"] is False
    on_ = post(api, ff, F + "client-names/", {"include": True})
    assert on_.status_code == 200 and on_.json()["include_client_names"] is True
    assert get(api, ff, F + "explain/").json()["include_client_names"] is True
    post(api, ff, F + "explain/", {"view": "90"})
    text = fake_claude.requests[-1]["messages"][0]["content"]
    assert "Globex Logistics: invoice" in text and "Acme Fasteners: recurring invoice" in text
    assert "Welton Partners (Referral fees received)" in text and "Client A" not in text
    # Still no invoice number and no one's contact details.
    for never in (with_clients["invoice"]["number"], "INV-", "Dana", "@"):
        assert never not in text, never
    post(api, ff, F + "client-names/", {"include": False})
    post(api, ff, F + "explain/", {"view": "30"})
    assert "Globex" not in fake_claude.requests[-1]["messages"][0]["content"]
    assert post(api, ff, F + "client-names/", {"include": "yes"}).status_code == 400
    with tenant_context(tenant.pk):
        changes = [(e.payload["before"], e.payload["after"]) for e in AuditEvent.objects
                   .filter(verb="finance.forecast_client_names_changed")
                   .order_by("created_at")]
    assert changes == [(False, True), (True, False)]


@pytest.mark.django_db
def test_the_pressed_buttons_share_twenty_a_day_and_the_workers_cap_is_not_theirs(
        with_clients, ff, api, fake_claude):
    tenant = with_clients["tenant"]
    fake_claude.reply = json.dumps({"one_offs": [], "missed": [], "questions": []})
    # The worker's own daily cap is for what nobody asked for: at $0 it stops
    # every unattended call and none of these.
    tenant.ai_unattended_daily_cap_usd = Decimal("0")
    tenant.save()
    from apps.tenancy import ai_guard

    assert ai_guard.cap_reached(tenant) is True
    for index in range(20):
        url, body = [(F + "explain/", {"view": "90"}), (F + "review/", {}),
                     (RC + "explain/", {"step": 1})][index % 3]
        assert post(api, ff, url, body).status_code == 200, (index, url)
    # The twenty-first, whichever button it is.
    for url, body in ((F + "explain/", {"view": "90"}), (F + "review/", {}),
                      (RC + "explain/", {"step": 1})):
        refused = post(api, ff, url, body)
        assert refused.status_code == 409 and "today's 20" in refused.json()["detail"], url
    assert len(fake_claude.requests) == 20
    assert get(api, ff, F + "explain/").json()["used_today"] == 20
    with tenant_context(tenant.pk):
        assert not AiCall.objects.filter(unattended=True).exists()
        AiCall.objects.update(created_at=timezone.now() - timedelta(days=2),
                              cost_usd=Decimal("0"))
    # Never past the monthly AI budget, where one is set.
    tenant.ai_monthly_budget_usd = Decimal("1.00")
    tenant.save()
    assert post(api, ff, F + "explain/", {"view": "90"}).status_code == 200
    with tenant_context(tenant.pk):
        AiCall.objects.filter(created_at__gte=timezone.now() - timedelta(hours=1)).update(
            cost_usd=Decimal("1.00"))
    for url in (F + "explain/", F + "review/"):
        over = post(api, ff, url, {"view": "90"})
        assert over.status_code == 409 and "budget" in over.json()["detail"]


@pytest.mark.django_db
def test_with_no_key_both_buttons_say_so_and_ask_nothing(with_clients, ff, api, settings):
    settings.ANTHROPIC_API_KEY = ""
    assert get(api, ff, F + "explain/").json()["refused"].startswith(
        "No Anthropic API key is set.")
    for url in (F + "explain/", F + "review/"):
        refused = post(api, ff, url, {"view": "90"})
        assert refused.status_code == 409 and "No Anthropic API key" in \
            refused.json()["detail"]
    with tenant_context(with_clients["tenant"].pk):
        assert not AiCall.objects.exists()


# ========================================================= review with Claude

@pytest.mark.django_db
def test_review_proposes_and_asks_and_nothing_enters_the_forecast_unconfirmed(
        with_clients, ff, api, fake_claude):
    tenant = with_clients["tenant"]
    kit = with_clients
    # Something that looks recurring and was not picked up: in one month of
    # the three under each of two descriptions.
    add(api, ff, kit, "expense", 185_000, on(back(1), 18), "Accounting",
        counterparty="Ledger & Quill")
    for n in (3, 1):
        add(api, ff, kit, "expense", 4_500, on(back(n), 15), "Bank and merchant fees",
            counterparty="Front Range Bank")
    add(api, ff, kit, "expense", 2_500, on(back(2), 20), "Software",
        counterparty="Zoom one-time webinar add-on")
    with tenant_context(tenant.pk):
        text, regular, missed = forecast_ai.review_input(tenant)
    by_who = {item["who"]: item["ref"] for item in regular + missed}
    assert by_who[RENT].startswith("R") and by_who["Ledger & Quill"].startswith("N")
    base = get(api, ff, F).json()
    before = said(tenant)

    fake_claude.reply = "Here is my review:\n```json\n" + json.dumps({
        "one_offs": [{"id": by_who["Front Range Bank"], "why": "Seen twice only."},
                     {"id": "R999", "why": "Not one we sent."},
                     {"id": by_who["Front Range Bank"], "why": "Said twice."}],
        "missed": [{"id": by_who["Ledger & Quill"], "cadence": "yearly",
                    "why": "A tax return once a year looks annual.  " + "x" * 400},
                   {"id": by_who[RENT], "why": "A regular id in the wrong list."}],
        "questions": [{"topic": "hire", "question": "Are you taking anyone on?"},
                      {"topic": "moon", "question": "Any trips planned?"},
                      {"topic": "tax", "question": ""}] + [
            {"topic": "other", "question": f"Question {n}?"} for n in range(9)],
        "amount": 99999}) + "\n```"
    reviewed = post(api, ff, F + "review/", {})
    assert reviewed.status_code == 200
    reviewed = reviewed.json()
    # What is sent: the names rule, and the books' own figures by id.
    [request] = fake_claude.requests
    sent_text = request["messages"][0]["content"]
    assert sent_text == text
    assert f"| out | {RENT} (Rent and coworking) | monthly | $695.00 |" in sent_text
    assert "NOT PICKED UP" in sent_text and "Ledger & Quill (Professional services: " \
        "Accounting)" in sent_text
    assert "Welton" not in sent_text and "Client A (Referral fees received)" in sent_text
    for never in ("Globex", "Acme", "INV-", "Dana"):
        assert never not in json.dumps(request, default=str), never
    assert "names no amount of money" in request["system"]
    # Three lists: only what we sent, each once, each with the books' figures.
    assert [(row["who"], row["why"]) for row in reviewed["one_offs"]] == [
        ("Front Range Bank", "Seen twice only.")]
    assert reviewed["one_offs"][0]["amount_cents"] == 4_500
    assert reviewed["one_offs"][0]["cadence"] == "monthly"
    [missed_one] = reviewed["missed"]
    assert missed_one["who"] == "Ledger & Quill" and len(missed_one["why"]) <= 240
    assert missed_one["months"] == [{"month": back(1).isoformat()[:7],
                                     "amount_cents": 185_000}]
    assert missed_one["last_amount_cents"] == 185_000, "from the books, not from Claude"
    # The form it opens follows the proposal: yearly, from when it next falls.
    assert missed_one["cadence"] == "yearly"
    assert missed_one["next_on"] == forecast._add_months(
        date.fromisoformat(on(back(1), 18)), 12).isoformat()
    assert "cadence it looks to have: monthly, quarterly or yearly" in request["system"]
    assert [row["topic"] for row in reviewed["questions"]] == [
        "hire", "other", "other", "other", "other", "other"]
    assert reviewed["questions"][1]["question"] == "Any trips planned?"
    assert "99999" not in json.dumps(reviewed) and "ref" not in reviewed["missed"][0]
    assert Decimal(reviewed["cost_usd"]) > 0 and reviewed["disclaimer"] == DISCLAIMER
    # Reviewing changed nothing: only its `ai_call`.
    after = json.loads(said(tenant))
    assert after.pop("ai") == 1 and {**json.loads(before), "ai": 1} == {**after, "ai": 1}
    now = get(api, ff, F).json()
    for key in ("weeks", "months", "lines", "planned", "adjustments"):
        assert now[key] == base[key], key

    # The owner answers, and each answer is theirs: "it is a one-off"...
    one_off = post(api, ff, F + "adjust/", {"line": reviewed["one_offs"][0]["group"],
                                            "kind": "not_regular", "source": "review"})
    assert one_off.status_code == 201
    assert line(one_off.json(), "Front Range Bank") == []
    assert one_off.json()["adjustments"][0]["source"] == "review"
    # ..."add it", with an amount and a cadence the owner typed...
    added = post(api, ff, F + "planned/", {
        "description": "Ledger & Quill, tax return", "amount_cents": 195_000,
        "on_date": forecast._add_months(THIS, 5).isoformat(), "source": "review"}).json()
    assert line(added, "Ledger & Quill, tax return")[0]["detail"] == \
        "Planned by you. From a review."
    # ...and a question answered with a date and an amount.
    hire = post(api, ff, F + "planned/", {
        "description": "Operations analyst", "amount_cents": 650_000, "repeat": "monthly",
        "on_date": forecast._add_months(THIS, 2).isoformat(), "source": "review"}).json()
    assert {row["description"]: row["source"] for row in hire["planned"]} == {
        "Ledger & Quill, tax return": "review", "Operations analyst": "review"}
    with tenant_context(tenant.pk):
        assert AiCall.objects.count() == 1, "the answers ask Claude nothing"


@pytest.mark.django_db
@pytest.mark.parametrize("proposed, months, cadence, months_on", [
    ("yearly", [1], "yearly", 12),              # found on the demo: tax preparation
    ("quarterly", [4, 1], "quarterly", 3),
    ("monthly", [1], "monthly", 1),
    # Not a cadence a planned line can have, or none given: from the books.
    ("weekly", [1], "yearly", 12),
    (None, [4, 1], "quarterly", 3),
    (None, [2, 1], "monthly", 1),
])
def test_a_line_the_review_adds_starts_from_the_cadence_proposed_and_its_next_date(
        proposed, months, cadence, months_on):
    """Found on the demo, 2026-10-13: a yearly item opened as "Every month"
    from today. The cadence is the proposal's; the date is arithmetic on the
    day the books last show it, and is never today."""
    last = date.fromisoformat(on(back(months[-1]), 18))
    item = {"ref": "N1", "who": "Ledger & Quill", "last_on": last.isoformat(),
            "months": [{"month": back(n).isoformat()[:7], "amount_cents": 185_000}
                       for n in months]}
    row = {"id": "N1", "why": "Looks recurring."}
    if proposed is not None:
        row["cadence"] = proposed
    [picked] = forecast_ai._pick([row], {"N1": item}, TODAY)
    assert picked["cadence"] == cadence
    expected = forecast._add_months(last, months_on)
    if expected <= TODAY:                       # this month's has already passed
        expected = forecast._add_months(last, months_on * 2)
    assert picked["next_on"] == expected.isoformat() and expected > TODAY


@pytest.mark.django_db
@pytest.mark.parametrize("reply", ["I could not find anything to say.", "{not json}",
                                   "[1, 2, 3]"])
def test_a_review_that_cannot_be_read_changes_nothing_and_says_it_cost(
        with_clients, ff, api, fake_claude, reply):
    fake_claude.reply = reply
    before = json.loads(said(with_clients["tenant"]))
    refused = post(api, ff, F + "review/", {})
    assert refused.status_code == 502
    assert "could not be read" in refused.json()["detail"]
    assert "It was still an AI call" in refused.json()["detail"]
    after = json.loads(said(with_clients["tenant"]))
    assert after.pop("ai") == 1 and before.pop("ai") == 0 and after == before


@pytest.mark.django_db
def test_review_needs_two_closed_months_and_asks_nothing_without_them(
        cash, ff, api, fake_claude):          # noqa: F811
    closed(cash["tenant"], back(1))
    refused = post(api, ff, F + "review/", {})
    assert refused.status_code == 409 and "Close two months" in refused.json()["detail"]
    assert fake_claude.requests == []
