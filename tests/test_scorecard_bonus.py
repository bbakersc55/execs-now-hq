"""M5 part 2: bonus plans (`docs/p6_m5_kpi_scorecard.md`, "Per-person KPIs and
bonus plans", decisions 7 and 8).

- **The arithmetic**: tiers and the straight line, achievement against the
  target prorated to today, lower is better, proration for someone added
  mid-period, the sentence of what reaches the next tier.
- **Who sees whose** (decision 7), every level through the API: a person
  their own; a manager their own and their team's; senior leadership and the
  client owner everyone's; the practice owner and associates every plan of the
  companies they reach; assistants no dollar amounts; nobody else anything,
  and a plan they can see none of is 404.
- **The freeze**: a closed period shows what it was closed with, whatever
  happens to readings or the plan after; a correction waits for the client
  owner's confirmation, which is recorded.
- **Copy forward**, the Payroll list as a spreadsheet, and setup's rules.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.scorecard import bonus
from apps.scorecard import periods as P
from apps.scorecard.models import (BonusPlan, BonusReopen, BonusResult, KpiReading,
                                   default_tiers)
from apps.tenancy.context import tenant_context
from apps.tenancy.models import AuditEvent

from .factories import ClientCompanyFactory, MembershipFactory, TenantFactory
from .test_scorecard import post, sc  # noqa: F401  (the fixture)

B = "/api/scorecard/bonus/"


def month_start(day):
    return day.replace(day=1)


def last_month():
    return P.previous_start(month_start(timezone.localdate()), P.MONTHLY)


def weeks_of(start, end, week_start="monday"):
    return [s for s in P.starts_between(start, end, P.WEEKLY, week_start) if s >= start]


def make_plan(sc, start, *, people=("member", "colleague", "manager", "sales_member"),
              amount=600, **extra):
    who, k = sc["who"], sc["kpis"]
    data = {"name": "Floor bonus", "period": "monthly", "period_start": start.isoformat(),
            "amount": amount,
            "components": [{"kpi": str(k["calls"].pk), "weight": 60},
                           {"kpi": str(k["rating"].pk), "weight": 40}],
            "people": [{"membership": str(who[p].pk)} for p in people], **extra}
    with tenant_context(sc["tenant"].pk):
        card = k["calls"].scorecard
        return bonus.create_plan(card, data, sc["practice"]["ff"].user)


def read(sc, kpi, who, start, value):
    with tenant_context(sc["tenant"].pk):
        KpiReading.objects.update_or_create(
            tenant=sc["tenant"], kpi=sc["kpis"][kpi], period_start=start,
            membership=sc["who"][who],
            defaults={"value": value, "entered_by": sc["practice"]["ff"].user,
                      "entered_at": timezone.now()})


@pytest.fixture
def closed_month(sc):
    """Last month's plan with a reading for every week, ready to close."""
    start = last_month()
    plan = make_plan(sc, start)
    for week in weeks_of(start, P.end_of(start, P.MONTHLY)):
        for who, calls, rating in (("member", 12, 4.6), ("colleague", 7, 3.0),
                                   ("manager", 10, 4.5), ("sales_member", 15, 5)):
            read(sc, "calls", who, week, calls)
            if who != "manager":
                read(sc, "rating", who, week, rating)
    return plan


def get(sc, who, **params):
    client = sc["api"].as_(who if not isinstance(who, str) else sc["who"].get(who)
                           or sc["practice"][who])
    query = "&".join(f"{k}={v}" for k, v in {"company": sc["company"].pk, **params}.items())
    return client.get(f"{B}?{query}")


def names_in(response):
    return response.content.decode()


# ------------------------------------------------------------------ the arithmetic

def test_tiers_pick_the_share_and_the_straight_line_caps():
    tiers = default_tiers()
    plan_like = {"straight_line": False, "cap_pct": 120}
    assert bonus.share_of(plan_like, tiers, Decimal("79.9")) == 0
    assert bonus.share_of(plan_like, tiers, Decimal(80)) == 50
    assert bonus.share_of(plan_like, tiers, Decimal(100)) == 100
    assert bonus.share_of(plan_like, tiers, Decimal(114)) == 120
    line = {"straight_line": True, "cap_pct": 110}
    assert bonus.share_of(line, tiers, Decimal(87)) == 87
    assert bonus.share_of(line, tiers, Decimal(160)) == 110
    assert bonus.share_of(line, tiers, None) == 0


def test_a_tier_table_is_cleaned_and_refused_in_words():
    assert bonus.clean_tiers([{"from": 90, "share": 100}])[0] == {"from": 0, "share": 0}
    with pytest.raises(bonus.SetupError, match="same percent"):
        bonus.clean_tiers([{"from": 50, "share": 1}, {"from": 50, "share": 2}])
    with pytest.raises(bonus.SetupError, match="0% to 500%"):
        bonus.clean_tiers([{"from": 10, "share": 900}])


def test_achievement_to_date_uses_the_target_prorated_to_today(sc):
    """A summed KPI mid-month: readings so far against the full target times
    the share of the month gone, so a fair number, not a scary one."""
    start = date(2026, 10, 1)
    plan = make_plan(sc, start, people=("member",))
    weeks = weeks_of(start, date(2026, 10, 31))
    for week in weeks[:3]:                       # three weeks in by the 21st
        read(sc, "calls", "member", week, 12)
    with tenant_context(sc["tenant"].pk):
        loaded = bonus.Loaded([plan])
        row = bonus.live_result(plan, loaded.people[plan.pk][0], loaded, date(2026, 10, 21),
                                "monday")
    calls = row["components"][0]
    full = 10 * len(weeks)                        # the KPI's weekly 10, every week starting in October
    assert calls["target"] == full
    assert calls["expected"] == pytest.approx(full * 21 / 31, rel=1e-3)
    assert calls["value"] == 36
    assert calls["achievement"] == round(36 / (full * 21 / 31) * 100)


def test_lower_is_better_flips_achievement(sc):
    with tenant_context(sc["tenant"].pk):
        kpi = sc["kpis"]["rating"]
        kpi.direction = "lower"
        assert bonus._achievement(kpi, Decimal("9.4"), Decimal(15)) == pytest.approx(
            Decimal(15) / Decimal("9.4") * 100)
        kpi.direction = "higher"


def test_someone_added_mid_period_is_prorated_by_days(sc):
    start = date(2026, 9, 1)
    plan = make_plan(sc, start, people=("member",), amount=300)
    with tenant_context(sc["tenant"].pk):
        person = plan.people.get()
        person.joined_on = date(2026, 9, 16)      # 15 of 30 days
        person.save()
        for week in weeks_of(start, date(2026, 9, 30)):
            read(sc, "calls", "member", week, 40)
            read(sc, "rating", "member", week, 10)   # both summed: twice the prorated target
        loaded = bonus.Loaded([plan])
        row = bonus.live_result(plan, loaded.people[plan.pk][0], loaded, date(2026, 10, 5),
                                "monday")
    assert row["prorated"] and row["days_on"] == 15
    assert row["amount"] == 150.0
    assert row["earned"] == 180.0                 # both components at the top tier, 120% of 150


def test_the_next_tier_sentence_names_what_it_takes(sc):
    start = date(2026, 10, 1)
    plan = make_plan(sc, start, people=("member",))
    weeks = weeks_of(start, date(2026, 10, 31))
    for week in weeks[:3]:
        read(sc, "calls", "member", week, 4)
        read(sc, "rating", "member", week, 5)
    with tenant_context(sc["tenant"].pk):
        loaded = bonus.Loaded([plan])
        row = bonus.live_result(plan, loaded.people[plan.pk][0], loaded, date(2026, 10, 21),
                                "monday")
    text = row["components"][0]["next"]["text"]
    assert text.startswith(f"{int(10 * len(weeks) * 0.8) - 12} more in calls by October 31")
    assert "another $" in text and row["next"] == text


# ------------------------------------------------------------------ who sees whose

def test_a_member_sees_their_own_bonus_and_nothing_of_a_colleague(sc, closed_month):
    plan = make_plan(sc, month_start(timezone.localdate()))
    r = get(sc, "member")
    assert r.status_code == 200
    data = r.json()
    assert data["views"] == ["mine"] and data["view"] == "mine"
    assert data["me"]["name"] == "Mia Member"
    assert data["plan"]["id"] == str(plan.pk)
    body = names_in(r)
    for other in ("Cole Colleague", "Max Manager", "Sam Sales"):
        assert other not in body
    for view in ("team", "all"):
        assert get(sc, "member", view=view).json()["view"] is None
    assert get(sc, "member", view="mine", plan=str(closed_month.pk)).status_code == 200


def test_a_manager_sees_their_own_and_their_teams(sc, closed_month):
    data = get(sc, "manager", view="team").json()
    assert data["views"] == ["mine", "team"]
    names = {r["name"] for g in data["plans"] for r in g["rows"]}
    assert names == {"Mia Member", "Cole Colleague", "Max Manager"}
    assert "Sam Sales" not in json.dumps(data)
    assert all("earned" in r for g in data["plans"] for r in g["rows"])
    assert get(sc, "manager", view="all").json()["view"] is None


@pytest.mark.parametrize("who", ["leader", "leader_all", "owner"])
def test_senior_leadership_and_the_client_owner_see_everyone(sc, closed_month, who):
    data = get(sc, who, view="all").json()
    assert "all" in data["views"]
    names = {r["name"] for g in data["plans"] for r in g["rows"]}
    assert names == {"Mia Member", "Cole Colleague", "Max Manager", "Sam Sales"}


@pytest.mark.parametrize("who", ["viewer", "on_no_team", "ops_viewer"])
def test_someone_on_no_plan_and_leading_no_one_sees_no_bonus(sc, closed_month, who):
    data = get(sc, who).json()
    assert data["views"] == [] and data["view"] is None
    assert "plans" not in data and "me" not in data
    assert get(sc, who, view="all").json()["view"] is None
    assert get(sc, who, view="mine").json()["view"] is None


def test_a_member_of_another_team_sees_only_their_own(sc, closed_month):
    data = get(sc, "sales_member").json()
    assert data["views"] == ["mine"]
    assert "Mia Member" not in json.dumps(data)


@pytest.mark.parametrize("who", ["ff", "cf"])
def test_the_practice_owner_and_an_assigned_associate_see_every_plan(sc, closed_month, who):
    data = get(sc, who, view="all").json()
    assert data["views"] == ["all"] and data["may_build"]
    assert len({r["name"] for g in data["plans"] for r in g["rows"]}) == 4
    assert data["plans"][0]["rows"][0]["earned"] is not None


def test_an_assistant_sees_achievement_but_no_amounts(sc, closed_month):
    data = get(sc, "va", view="all").json()
    assert data["sees_amounts"] is False and not data["may_build"]
    row = data["plans"][0]["rows"][0]
    assert "earned" not in row and "amount" not in row
    assert all("earned" not in c for c in row["components"])
    assert row["components"][0]["achievement"] is not None
    assert "payroll" not in data
    client = sc["api"].as_(sc["practice"]["va"])
    assert client.get(f"{B}payroll/?company={sc['company'].pk}&period="
                      f"monthly:{closed_month.period_start}").status_code == 404


def test_an_unassigned_associate_and_another_practice_reach_nothing(sc, closed_month):
    assert get(sc, "cf_other").status_code == 404
    other = TenantFactory()
    stranger = MembershipFactory(tenant=other, role="FF")
    client = sc["api"].as_(stranger)
    assert client.get(f"{B}?company={sc['company'].pk}").status_code == 404
    assert client.get(f"{B}plans/{closed_month.pk}/").status_code == 404
    assert post(client, f"{B}plans/{closed_month.pk}/close/").status_code == 404


def test_a_client_of_another_company_reaches_nothing(sc, closed_month):
    other = ClientCompanyFactory(tenant=sc["tenant"], name="Elsewhere")
    outsider = MembershipFactory(tenant=sc["tenant"], role="FCC", client_company=other)
    client = sc["api"].as_(outsider)
    assert client.get(f"{B}?company={sc['company'].pk}").status_code == 404
    assert post(client, f"{B}plans/{closed_month.pk}/reopen/", {"confirm": True}) \
        .status_code == 404


def test_a_member_asking_for_a_plan_they_are_not_on_is_refused(sc):
    plan = make_plan(sc, last_month(), people=("colleague",))
    r = get(sc, "member", view="mine", plan=str(plan.pk))
    assert r.json()["view"] is None or r.status_code == 404
    assert "Cole Colleague" not in names_in(r)


def test_a_change_of_team_changes_whose_rows_a_manager_sees_at_once(sc, closed_month):
    from apps.work import teams
    from apps.work.models import ClientTeamMember

    ClientTeamMember.all_objects.filter(membership=sc["who"]["colleague"]).delete()
    teams.place(sc["teams"]["sales"], sc["who"]["colleague"], ClientTeamMember.Level.MEMBER)
    names = {r["name"] for g in get(sc, "manager", view="team").json()["plans"]
             for r in g["rows"]}
    assert "Cole Colleague" not in names


def test_the_board_lists_the_bonus_tabs_by_level(sc, closed_month):
    def tabs(who):
        client = sc["api"].as_(sc["who"].get(who) or sc["practice"][who])
        return client.get(f"/api/scorecard/?company={sc['company'].pk}&window=this_month") \
            .json()["bonus_views"]
    assert tabs("member") == ["mine"]
    assert tabs("manager") == ["mine", "team"]
    assert tabs("owner") == ["all"]
    assert tabs("viewer") == []
    assert tabs("ff") == ["all"]


# ------------------------------------------------------------------ the freeze

def test_a_period_closes_only_once_it_has_ended(sc):
    plan = make_plan(sc, month_start(timezone.localdate()))
    client = sc["api"].as_(sc["practice"]["ff"])
    r = post(client, f"{B}plans/{plan.pk}/close/")
    assert r.status_code == 400 and "hasn't ended" in r.json()["detail"]


def test_closing_freezes_readings_targets_and_the_plan(sc, closed_month):
    client = sc["api"].as_(sc["who"]["owner"])
    assert post(client, f"{B}plans/{closed_month.pk}/close/").status_code == 200
    frozen = {r["name"]: r for g in get(sc, "owner", view="all").json()["plans"]
              for r in g["rows"]}
    mia = frozen["Mia Member"]["earned"]
    assert BonusResult.all_objects.filter(plan=closed_month).count() == 4
    # A later correction, a new target and an edited plan move nothing.
    week = weeks_of(closed_month.period_start, bonus.period_end(closed_month))[0]
    read(sc, "calls", "member", week, 0)
    kpi = sc["kpis"]["calls"]
    kpi.target_value = 1
    kpi.save()
    ff = sc["api"].as_(sc["practice"]["ff"])
    r = ff.patch(f"{B}plans/{closed_month.pk}/", json.dumps({"amount": 9999}),
                 content_type="application/json")
    assert r.status_code == 400 and "closed" in r.json()["detail"]
    data = get(sc, "owner", view="all").json()
    again = {r["name"]: r for g in data["plans"] for r in g["rows"]}
    assert again["Mia Member"]["earned"] == mia
    assert data["plans"][0]["plan"]["corrections"][0]["name"] == "Mia Member"
    assert data["plans"][0]["plan"]["corrections"][0]["now"] == 0
    # The member's own view is the frozen one too.
    mine = get(sc, "member", view="mine", plan=str(closed_month.pk)).json()["me"]
    assert mine["earned"] == mia
    assert data["payroll"] and {p["name"] for p in data["payroll"]} == set(frozen)


def test_only_the_client_owner_reopens_with_confirmation_and_it_is_recorded(sc, closed_month):
    owner = sc["api"].as_(sc["who"]["owner"])
    post(owner, f"{B}plans/{closed_month.pk}/close/")
    week = weeks_of(closed_month.period_start, bonus.period_end(closed_month))[0]
    before = BonusResult.all_objects.get(plan=closed_month, membership=sc["who"]["member"])
    read(sc, "calls", "member", week, 0)
    for who in (sc["practice"]["ff"], sc["who"]["leader"], sc["who"]["member"]):
        r = post(sc["api"].as_(who), f"{B}plans/{closed_month.pk}/reopen/", {"confirm": True})
        assert r.status_code in (403, 404)
    assert post(owner, f"{B}plans/{closed_month.pk}/reopen/", {}).status_code == 400
    assert post(owner, f"{B}plans/{closed_month.pk}/reopen/", {"confirm": True}) \
        .status_code == 200
    after = BonusResult.all_objects.get(plan=closed_month, membership=sc["who"]["member"])
    assert after.earned <= before.earned
    record = BonusReopen.all_objects.get(plan=closed_month)
    assert record.confirmed_by == sc["who"]["owner"].user
    assert record.before[str(sc["who"]["member"].pk)] == str(before.earned)
    assert AuditEvent.all_objects.filter(verb="scorecard.bonus_period_reopened").exists()
    assert not bonus.corrections(BonusPlan.all_objects.get(pk=closed_month.pk),
                                 timezone.localdate())
    # Nothing left to reopen.
    assert post(owner, f"{B}plans/{closed_month.pk}/reopen/", {"confirm": True}) \
        .status_code == 400


def test_a_member_cannot_close_a_period(sc, closed_month):
    r = post(sc["api"].as_(sc["who"]["member"]), f"{B}plans/{closed_month.pk}/close/")
    assert r.status_code == 403
    assert BonusPlan.all_objects.get(pk=closed_month.pk).closed_at is None


# ------------------------------------------------------------------ copy forward, payroll

def test_copy_forward_makes_the_next_period_once(sc, closed_month):
    ff = sc["api"].as_(sc["practice"]["ff"])
    r = post(ff, f"{B}plans/{closed_month.pk}/copy-forward/")
    assert r.status_code == 201
    new = r.json()
    assert new["period_start"] == P.next_start(closed_month.period_start, "monthly").isoformat()
    assert len(new["components"]) == 2 and len(new["people"]) == 4
    assert new["components"][0]["tiers"] == default_tiers()
    again = post(ff, f"{B}plans/{closed_month.pk}/copy-forward/")
    assert again.status_code == 400 and "already" in again.json()["detail"]


def test_the_payroll_spreadsheet_has_the_people_and_the_readings(sc, closed_month):
    owner = sc["api"].as_(sc["who"]["owner"])
    post(owner, f"{B}plans/{closed_month.pk}/close/")
    r = owner.get(f"{B}payroll/?company={sc['company'].pk}&period=monthly:"
                  f"{closed_month.period_start}")
    assert r.status_code == 200
    assert r["Content-Type"].startswith("application/vnd.openxmlformats")
    book = zipfile.ZipFile(io.BytesIO(r.content))
    names = book.read("xl/workbook.xml").decode()
    assert 'name="Payroll"' in names and 'name="Readings and tiers"' in names
    sheet1 = book.read("xl/worksheets/sheet1.xml").decode()
    sheet2 = book.read("xl/worksheets/sheet2.xml").decode()
    assert "Mia Member" in sheet1 and "Amount earned" in sheet1
    assert "from 80%: 50%" in sheet2 and "Calls" in sheet2
    for who in ("member", "manager"):
        client = sc["api"].as_(sc["who"][who])
        assert client.get(f"{B}payroll/?company={sc['company'].pk}&period=monthly:"
                          f"{closed_month.period_start}").status_code == 404


def test_the_payroll_waits_for_the_close(sc, closed_month):
    owner = sc["api"].as_(sc["who"]["owner"])
    r = owner.get(f"{B}payroll/?company={sc['company'].pk}&period=monthly:"
                  f"{closed_month.period_start}")
    assert r.status_code == 404


# ------------------------------------------------------------------ setup

def test_only_the_practice_owner_and_associates_build_plans(sc):
    data = {"company": str(sc["company"].pk), "name": "X", "period": "monthly",
            "period_start": last_month().isoformat(), "amount": 100,
            "components": [{"kpi": str(sc["kpis"]["calls"].pk), "weight": 50},
                           {"kpi": str(sc["kpis"]["rating"].pk), "weight": 50}],
            "people": [{"membership": str(sc["who"]["member"].pk)}]}
    for who in (sc["who"]["owner"], sc["who"]["leader"], sc["practice"]["va"]):
        assert post(sc["api"].as_(who), f"{B}plans/", data).status_code == 403
    r = post(sc["api"].as_(sc["practice"]["cf"]), f"{B}plans/", data)
    assert r.status_code == 201, r.content
    assert AuditEvent.all_objects.filter(verb="scorecard.bonus_plan_created").exists()


@pytest.mark.parametrize("change,words", [
    ({"components": "one"}, "two to five"),
    ({"weights": (60, 30)}, "add to 100"),
    ({"kpi": "all"}, "per-person"),
    ({"people": []}, "at least one"),
])
def test_a_plan_is_refused_in_words(sc, change, words):
    k = sc["kpis"]
    comps = [{"kpi": str(k["calls"].pk), "weight": 60}, {"kpi": str(k["rating"].pk), "weight": 40}]
    if change.get("components") == "one":
        comps = comps[:1]
    if "weights" in change:
        comps[0]["weight"], comps[1]["weight"] = change["weights"]
    if change.get("kpi") == "all":
        comps[1]["kpi"] = str(k["all"].pk)
    data = {"company": str(sc["company"].pk), "name": "X", "period": "monthly",
            "period_start": last_month().isoformat(), "amount": 100, "components": comps,
            "people": change.get("people", [{"membership": str(sc["who"]["member"].pk)}])}
    r = post(sc["api"].as_(sc["practice"]["ff"]), f"{B}plans/", data)
    assert r.status_code == 400 and words in r.json()["detail"]


def test_someone_outside_the_company_cannot_be_put_on_a_plan(sc):
    other = ClientCompanyFactory(tenant=sc["tenant"], name="Elsewhere")
    outsider = MembershipFactory(tenant=sc["tenant"], role="ECC", client_company=other)
    k = sc["kpis"]
    data = {"company": str(sc["company"].pk), "name": "X", "period": "monthly",
            "period_start": last_month().isoformat(), "amount": 100,
            "components": [{"kpi": str(k["calls"].pk), "weight": 60},
                           {"kpi": str(k["rating"].pk), "weight": 40}],
            "people": [{"membership": str(outsider.pk)}]}
    r = post(sc["api"].as_(sc["practice"]["ff"]), f"{B}plans/", data)
    assert r.status_code == 400 and "portal user of the company" in r.json()["detail"]


def test_a_mid_period_start_date_must_be_inside_the_period(sc):
    k = sc["kpis"]
    start = last_month()
    data = {"company": str(sc["company"].pk), "name": "X", "period": "monthly",
            "period_start": start.isoformat(), "amount": 100,
            "components": [{"kpi": str(k["calls"].pk), "weight": 60},
                           {"kpi": str(k["rating"].pk), "weight": 40}],
            "people": [{"membership": str(sc["who"]["member"].pk),
                        "joined_on": (start - timedelta(days=3)).isoformat()}]}
    r = post(sc["api"].as_(sc["practice"]["ff"]), f"{B}plans/", data)
    assert r.status_code == 400 and "inside its period" in r.json()["detail"]


# ------------------------------------------------------------------ per-unit pay (2026-11-12)
#
# "$5 per five-star Google review, monthly": a fixed amount for each unit of
# a company KPI's reading for the period, each person in full or one pool
# split evenly, beside the components or on its own. "For everyone" is the
# fixture's company-level count, read weekly.

def unit_plan(sc, start, *, split="each", people=("member",), teams=(), components=False,
              rate=5, units=None, **extra):
    who, k = sc["who"], sc["kpis"]
    data = {"name": "Reviews bonus", "period": "monthly", "period_start": start.isoformat(),
            "units": units if units is not None else [{"kpi": str(k["all"].pk), "rate": rate}],
            "unit_split": split,
            "people": [{"membership": str(who[p].pk)} for p in people],
            "teams": [str(sc["teams"][t].pk) for t in teams], **extra}
    if components:
        data["amount"] = 600
        data["components"] = [{"kpi": str(k["calls"].pk), "weight": 60},
                              {"kpi": str(k["rating"].pk), "weight": 40}]
    with tenant_context(sc["tenant"].pk):
        return bonus.create_plan(k["all"].scorecard, data, sc["practice"]["ff"].user)


def company_read(sc, kpi, start, value):
    with tenant_context(sc["tenant"].pk):
        KpiReading.objects.update_or_create(
            tenant=sc["tenant"], kpi=sc["kpis"][kpi], period_start=start, membership=None,
            defaults={"value": value, "entered_by": sc["practice"]["ff"].user,
                      "entered_at": timezone.now()})


def four_units(sc, start):
    """Four units in the month: 3 in its first week, 1 in its second."""
    first, second = weeks_of(start, P.end_of(start, P.MONTHLY))[:2]
    company_read(sc, "all", first, 3)
    company_read(sc, "all", second, 1)


def mine(sc, who, plan):
    r = get(sc, who, view="mine", plan=str(plan.pk))
    assert r.status_code == 200, r.content
    return r.json()["me"]


def test_per_unit_pay_gives_each_person_the_full_amount(sc):
    start = last_month()
    plan = unit_plan(sc, start, people=("member", "colleague"))
    four_units(sc, start)
    for who in ("member", "colleague"):
        me = mine(sc, who, plan)
        unit = me["units"][0]
        assert unit["text"] == "4 × $5 = $20"
        assert (unit["units"], unit["total"], unit["earned"]) == (4, 20, 20)
        assert me["earned"] == 20 and me["earned_units"] == 20
        assert me["components"] == [] and me["amount"] == 0
        assert [r["value"] for r in unit["readings"]] == [3, 1]


def test_a_pool_is_split_evenly_among_the_people_on_the_plan(sc):
    start = last_month()
    plan = unit_plan(sc, start, split="pool", people=("member", "colleague"))
    four_units(sc, start)
    me = mine(sc, "member", plan)
    assert me["units"][0]["text"] == "4 × $5 = $20, split among 2: $10"
    assert me["earned"] == 10


def test_a_pool_splits_by_days_when_someone_joined_part_way(sc):
    start = last_month()
    days = (P.end_of(start, P.MONTHLY) - start).days + 1
    joined = start + timedelta(days=15)
    who = sc["who"]
    with tenant_context(sc["tenant"].pk):
        plan = bonus.create_plan(sc["kpis"]["all"].scorecard, {
            "name": "Pool", "period": "monthly", "period_start": start.isoformat(),
            "units": [{"kpi": str(sc["kpis"]["all"].pk), "rate": 5}], "unit_split": "pool",
            "people": [{"membership": str(who["member"].pk)},
                       {"membership": str(who["colleague"].pk),
                        "joined_on": joined.isoformat()}]}, sc["practice"]["ff"].user)
    four_units(sc, start)
    full, part = mine(sc, "member", plan), mine(sc, "colleague", plan)
    late_days = days - 15
    assert full["units"][0]["earned"] == pytest.approx(20 * days / (days + late_days), abs=0.01)
    assert full["earned"] + part["earned"] == pytest.approx(20, abs=0.01)
    assert "split among 2 by days on the plan" in part["units"][0]["text"]


def test_per_unit_pay_sits_beside_the_components(sc, closed_month):
    with tenant_context(sc["tenant"].pk):
        ff = sc["practice"]["ff"].user
        bonus.update_plan(closed_month, {"units": [{"kpi": str(sc["kpis"]["all"].pk),
                                                    "rate": "2.50"}]}, ff)
    four_units(sc, closed_month.period_start)
    me = mine(sc, "member", closed_month)
    assert len(me["components"]) == 2 and me["amount"] == 600
    assert me["units"][0]["text"] == "4 × $2.50 = $10"
    assert me["earned"] == pytest.approx(me["earned_components"] + 10, abs=0.001)


def test_a_per_unit_plan_needs_no_amount(sc):
    plan = unit_plan(sc, last_month())
    assert plan.amount == 0
    described = bonus.describe(plan)
    assert described["components"] == [] and described["units"][0]["rate"] == "5"
    assert described["unit_split"] == "each"


@pytest.mark.parametrize("case,words", [
    ("per_person", "reading per person"),
    ("lower", "more is better"),
    ("zero", "more than $0"),
    ("nothing", "two to five components, per-unit pay, or both"),
    ("one_component", "or none beside its per-unit pay"),
    ("four_rules", "up to three"),
    ("twice", "paid per unit twice"),
    ("split", "one pool split evenly"),
])
def test_per_unit_pay_is_refused_in_words(sc, case, words):
    from apps.scorecard import setup

    k = sc["kpis"]
    data = {"company": str(sc["company"].pk), "name": "X", "period": "monthly",
            "period_start": last_month().isoformat(),
            "units": [{"kpi": str(k["all"].pk), "rate": 5}],
            "people": [{"membership": str(sc["who"]["member"].pk)}]}
    if case == "per_person":
        data["units"] = [{"kpi": str(k["calls"].pk), "rate": 5}]
    if case == "lower":
        with tenant_context(sc["tenant"].pk):
            worse = setup.create_kpi(k["all"].scorecard, {
                "name": "Complaints", "kind": "count", "cadence": "weekly", "rollup": "sum",
                "direction": "lower", "target_value": 2,
                "page": str(sc["pages"]["weekly"].pk)}, sc["practice"]["ff"].user)
        data["units"] = [{"kpi": str(worse.pk), "rate": 5}]
    if case == "zero":
        data["units"] = [{"kpi": str(k["all"].pk), "rate": 0}]
    if case == "nothing":
        data["units"] = []
    if case == "one_component":
        data["components"] = [{"kpi": str(k["calls"].pk), "weight": 100}]
        data["amount"] = 100
    if case == "four_rules":
        data["units"] = [{"kpi": str(k[n].pk), "rate": 1} for n in ("all", "lead", "ops", "cash")]
    if case == "twice":
        data["units"] = [{"kpi": str(k["all"].pk), "rate": 1}] * 2
    if case == "split":
        data["unit_split"] = "halves"
    r = post(sc["api"].as_(sc["practice"]["ff"]), f"{B}plans/", data)
    assert r.status_code == 400 and words in r.json()["detail"], r.content


def test_a_kpi_of_another_companys_scorecard_cannot_be_paid_per_unit(sc):
    from apps.scorecard import setup

    other = ClientCompanyFactory(tenant=sc["tenant"], name="Elsewhere")
    with tenant_context(sc["tenant"].pk):
        card = setup.ensure(other, sc["practice"]["ff"].user)
        theirs = setup.create_kpi(card, {"name": "Their reviews", "kind": "count",
                                         "cadence": "monthly", "rollup": "sum",
                                         "page": str(card.pages.get().pk)},
                                  sc["practice"]["ff"].user)
    data = {"company": str(sc["company"].pk), "name": "X", "period": "monthly",
            "period_start": last_month().isoformat(),
            "units": [{"kpi": str(theirs.pk), "rate": 5}],
            "people": [{"membership": str(sc["who"]["member"].pk)}]}
    r = post(sc["api"].as_(sc["practice"]["ff"]), f"{B}plans/", data)
    assert r.status_code == 400 and "this scorecard's KPIs" in r.json()["detail"]


def test_an_assistant_sees_the_units_but_no_dollars(sc):
    plan = unit_plan(sc, last_month())
    four_units(sc, plan.period_start)
    data = get(sc, "va", view="all").json()
    row = next(r for g in data["plans"] if g["plan"]["id"] == str(plan.pk) for r in g["rows"])
    unit = row["units"][0]
    assert unit["units"] == 4
    for key in ("rate", "rate_text", "total", "earned", "text"):
        assert key not in unit
    assert "earned_units" not in row and "$" not in json.dumps(row)


def test_closing_freezes_per_unit_pay_and_a_correction_waits_for_the_owner(sc):
    start = last_month()
    plan = unit_plan(sc, start, people=("member", "colleague"))
    four_units(sc, start)
    owner = sc["api"].as_(sc["who"]["owner"])
    assert post(owner, f"{B}plans/{plan.pk}/close/").status_code == 200
    company_read(sc, "all", weeks_of(start, P.end_of(start, P.MONTHLY))[0], 9)
    assert mine(sc, "member", plan)["earned"] == 20          # frozen
    data = get(sc, "owner", view="all").json()
    group = next(g for g in data["plans"] if g["plan"]["id"] == str(plan.pk))
    fixes = group["plan"]["corrections"]
    assert [(c["name"], c["frozen"], c["now"]) for c in fixes] == [("Everyone on the plan", 3, 9)]
    assert post(owner, f"{B}plans/{plan.pk}/reopen/", {"confirm": True}).status_code == 200
    assert mine(sc, "member", plan)["units"][0]["text"] == "10 × $5 = $50"


def test_the_payroll_list_and_spreadsheet_say_how_per_unit_pay_is_worked_out(sc):
    start = last_month()
    plan = unit_plan(sc, start, split="pool", people=("member", "colleague"))
    four_units(sc, start)
    owner = sc["api"].as_(sc["who"]["owner"])
    post(owner, f"{B}plans/{plan.pk}/close/")
    data = get(sc, "owner", view="all", period=f"monthly:{start}").json()
    rows = [p for p in data["payroll"] if p["plan"] == "Reviews bonus"]
    assert {p["per_unit"] for p in rows} == {"For everyone: 4 × $5 = $20, split among 2: $10"}
    r = owner.get(f"{B}payroll/?company={sc['company'].pk}&period=monthly:{start}")
    book = zipfile.ZipFile(io.BytesIO(r.content))
    sheet1 = book.read("xl/worksheets/sheet1.xml").decode()
    sheet2 = book.read("xl/worksheets/sheet2.xml").decode()
    assert "Per unit" in sheet1 and "4 × $5 = $20, split among 2: $10" in sheet1
    assert "For everyone (per unit)" in sheet2
    assert "$5 per unit, one pool split among 2" in sheet2


def test_copy_forward_carries_per_unit_pay_its_split_and_the_teams(sc):
    plan = unit_plan(sc, last_month(), split="pool", people=(), teams=("ops",))
    r = post(sc["api"].as_(sc["practice"]["ff"]), f"{B}plans/{plan.pk}/copy-forward/")
    assert r.status_code == 201, r.content
    new = r.json()
    assert new["unit_split"] == "pool"
    assert [u["kpi"] for u in new["units"]] == [str(sc["kpis"]["all"].pk)]
    assert [t["name"] for t in new["teams"]] == ["Operations"] and new["people"] == []


# ------------------------------------------------------------------ whole teams on a plan

OPS_PEOPLE = {"Mia Member", "Cole Colleague", "Max Manager", "Lee Leader", "Otto Opsviewer"}


def all_rows(sc, plan, who="ff"):
    data = get(sc, who, view="all").json()
    return next(g["rows"] for g in data["plans"] if g["plan"]["id"] == str(plan.pk))


def test_a_team_puts_everyone_on_it_on_the_plan(sc):
    plan = unit_plan(sc, last_month(), people=(), teams=("ops",))
    rows = all_rows(sc, plan)
    assert {r["name"] for r in rows} == OPS_PEOPLE
    assert all(r["via"] == ["Operations"] for r in rows)
    assert "mine" in get(sc, "member").json()["views"]
    # Only the people on it see it as theirs.
    for who in ("sales_member", "viewer", "on_no_team"):
        assert get(sc, who).json()["views"] == []
        assert get(sc, who, view="mine", plan=str(plan.pk)).json()["view"] is None


def test_a_member_of_a_team_plan_sees_only_their_own_row(sc):
    plan = unit_plan(sc, last_month(), people=(), teams=("ops",))
    r = get(sc, "member", view="mine", plan=str(plan.pk))
    body = names_in(r)
    assert "Mia Member" in body
    for other in OPS_PEOPLE - {"Mia Member"}:
        assert other not in body


def test_a_manager_sees_their_teams_rows_on_a_team_plan(sc):
    plan = unit_plan(sc, last_month(), people=(), teams=("ops",))
    data = get(sc, "manager", view="team").json()
    names = {r["name"] for g in data["plans"] if g["plan"]["id"] == str(plan.pk)
             for r in g["rows"]}
    assert names == OPS_PEOPLE
    assert "Sam Sales" not in json.dumps(data)


def test_the_client_owner_is_on_a_plan_only_by_name(sc):
    from apps.work import teams

    teams.place(sc["teams"]["ops"], sc["who"]["owner"], teams.Level.MEMBER)
    plan = unit_plan(sc, last_month(), people=(), teams=("ops",))
    assert "Olive Owner" not in {r["name"] for r in all_rows(sc, plan)}
    named = unit_plan(sc, last_month(), people=("owner",), teams=("ops",), name="Named")
    assert "Olive Owner" in {r["name"] for r in all_rows(sc, named)}


def test_someone_named_and_on_the_team_is_on_once_by_their_own_row(sc):
    start = last_month()
    joined = start + timedelta(days=10)
    who = sc["who"]
    with tenant_context(sc["tenant"].pk):
        plan = bonus.create_plan(sc["kpis"]["all"].scorecard, {
            "name": "Both", "period": "monthly", "period_start": start.isoformat(),
            "units": [{"kpi": str(sc["kpis"]["all"].pk), "rate": 5}],
            "teams": [str(sc["teams"]["ops"].pk)],
            "people": [{"membership": str(who["member"].pk), "joined_on": joined.isoformat()}]},
            sc["practice"]["ff"].user)
    rows = all_rows(sc, plan)
    assert len(rows) == len(OPS_PEOPLE)
    mia = next(r for r in rows if r["name"] == "Mia Member")
    assert mia["prorated"] and mia["via"] == []


def test_a_team_plan_follows_the_team_until_the_close_freezes_it(sc):
    from apps.work import teams
    from apps.work.models import ClientTeamMember

    plan = unit_plan(sc, last_month(), people=(), teams=("ops",))
    teams.place(sc["teams"]["ops"], sc["who"]["sales_member"], teams.Level.MEMBER)
    assert "Sam Sales" in {r["name"] for r in all_rows(sc, plan)}
    owner = sc["api"].as_(sc["who"]["owner"])
    assert post(owner, f"{B}plans/{plan.pk}/close/").status_code == 200
    frozen = {r["name"] for r in all_rows(sc, plan)}
    # After the close: someone leaves the team, someone joins it.
    ClientTeamMember.all_objects.filter(membership=sc["who"]["colleague"]).delete()
    teams.place(sc["teams"]["ops"], sc["who"]["viewer"], teams.Level.MEMBER)
    assert {r["name"] for r in all_rows(sc, plan)} == frozen
    assert "mine" in get(sc, "colleague").json()["views"]
    assert get(sc, "colleague", view="mine", plan=str(plan.pk)).status_code == 200
    assert get(sc, "viewer").json()["views"] == []


def test_a_team_of_another_company_or_practice_is_refused(sc):
    from .factories import ClientTeamFactory

    other = ClientCompanyFactory(tenant=sc["tenant"], name="Elsewhere")
    theirs = ClientTeamFactory(tenant=sc["tenant"], client_company=other)
    stranger = ClientTeamFactory(tenant=TenantFactory())
    for team in (theirs, stranger):
        data = {"company": str(sc["company"].pk), "name": "X", "period": "monthly",
                "period_start": last_month().isoformat(),
                "units": [{"kpi": str(sc["kpis"]["all"].pk), "rate": 5}],
                "teams": [str(team.pk)]}
        r = post(sc["api"].as_(sc["practice"]["ff"]), f"{B}plans/", data)
        assert r.status_code == 400 and "company's own teams" in r.json()["detail"]


def test_a_plan_names_at_least_one_person_or_team(sc):
    data = {"company": str(sc["company"].pk), "name": "X", "period": "monthly",
            "period_start": last_month().isoformat(),
            "units": [{"kpi": str(sc["kpis"]["all"].pk), "rate": 5}], "people": [],
            "teams": []}
    r = post(sc["api"].as_(sc["practice"]["ff"]), f"{B}plans/", data)
    assert r.status_code == 400 and "person or team" in r.json()["detail"]


def test_the_editor_offers_teams_and_company_kpis_for_per_unit_pay(sc):
    editor = get(sc, "ff", view="all").json()["editor"]
    assert {t["name"] for t in editor["teams"]} >= {"Operations", "Sales"}
    ops = next(t for t in editor["teams"] if t["name"] == "Operations")
    assert ops["people"] == len(OPS_PEOPLE)
    names = {k["name"] for k in editor["unit_kpis"]}
    assert "For everyone" in names
    assert not names & {"Calls", "Rating"}                       # per person


# ------------------------------------------------------------------ the form's request (2026-11-13)

def form_body(sc, **over):
    """What the New bonus plan form sends for a plan of per-unit pay alone:
    no components, the amount left blank, the rate as typed."""
    return {"company": str(sc["company"].pk), "name": "Five-star review bonus",
            "period": "monthly", "period_start": last_month().isoformat(), "amount": "",
            "straight_line": False, "cap_pct": 120, "components": [],
            "units": [{"kpi": str(sc["kpis"]["all"].pk), "rate": "5"}], "unit_split": "each",
            "teams": [], "people": [{"membership": str(sc["who"]["member"].pk),
                                     "amount": None, "joined_on": None, "left_on": None}],
            **over}


def test_a_per_unit_only_plan_saves_from_the_forms_request(sc):
    r = post(sc["api"].as_(sc["practice"]["ff"]), f"{B}plans/", form_body(sc))
    assert r.status_code == 201, r.content
    made = r.json()
    assert made["components"] == [] and made["amount"] == "0.00"
    assert made["units"] == [{"kpi": str(sc["kpis"]["all"].pk), "name": "For everyone",
                              "rate": "5"}]
    four_units(sc, last_month())
    assert mine(sc, "member", BonusPlan.all_objects.get(pk=made["id"]))["units"][0]["text"] \
        == "4 × $5 = $20"


@pytest.mark.parametrize("part,rows,index", [
    ("components", "dup", 1),
    ("units", "bad_rate", 1),
    ("people", "bad_date", 0),
])
def test_a_refused_row_says_which_row_it_is(sc, part, rows, index):
    k = sc["kpis"]
    over = {}
    if rows == "dup":
        over = {"amount": 600, "components": [{"kpi": str(k["calls"].pk), "weight": 50},
                                              {"kpi": str(k["calls"].pk), "weight": 50}]}
    if rows == "bad_rate":
        over = {"units": [{"kpi": str(k["all"].pk), "rate": "5"},
                          {"kpi": str(k["lead"].pk), "rate": "0"}]}
    if rows == "bad_date":
        over = {"people": [{"membership": str(sc["who"]["member"].pk),
                            "joined_on": (last_month() - timedelta(days=2)).isoformat()}]}
    r = post(sc["api"].as_(sc["practice"]["ff"]), f"{B}plans/", form_body(sc, **over))
    assert r.status_code == 400
    assert (r.json()["field"], r.json()["row"]) == (part, index), r.content


# ------------------------------------------------------------------ private everywhere (2026-11-13)

def test_a_team_member_sees_no_one_elses_bonus_anywhere(sc, closed_month):
    """A team member sees their own bonus and nobody else's amount, plan or
    payout: not on any screen's payload, not in a task, a plan or a digest,
    and not through the API or an AI app (MCP)."""
    from types import SimpleNamespace

    from apps.aiconnect import tools as T
    from apps.centers.models import PracticeCenter
    from apps.work import digests
    from apps.work.models import Cadence

    from .factories import ContactFactory

    today = timezone.localdate()
    PracticeCenter.all_objects.create(tenant=sc["tenant"], center="operations",
                                      enabled_at=timezone.now())
    with tenant_context(sc["tenant"].pk):
        bonus.close(closed_month, sc["practice"]["ff"].user, today)
        theirs = {r.membership_id: r for r in BonusResult.objects.filter(plan=closed_month)}
    # A plan the member isn't on, with an amount and a name found nowhere else.
    secret = make_plan(sc, month_start(today), people=("colleague", "manager"), amount=9137,
                       name="Retention award for two")
    member = sc["who"]["member"]
    as_member = sc["api"].as_(member)
    company = sc["company"].pk
    pages = [f"{B}?company={company}", f"{B}?company={company}&view=team",
             f"{B}?company={company}&view=all", f"/api/scorecard/?company={company}",
             "/api/plans/mine/", "/api/plans/mine/week/", "/api/tasks/", "/api/goals/",
             "/api/notices/", "/api/me", "/api/sops/", "/api/tool-runs/?company=mine"]
    seen, codes = {}, {}
    for path in pages:
        r = as_member.get(path)
        codes[path] = r.status_code
        seen[path] = r.content.decode() if r.status_code == 200 else ""
    # The sweep reads real pages, not refusals.
    for path in (f"{B}?company={company}", f"/api/scorecard/?company={company}",
                 "/api/plans/mine/", "/api/plans/mine/week/", "/api/tasks/", "/api/me"):
        assert codes[path] == 200, (path, codes[path])
    # Their own bonus is there; nobody else's row, plan or payout is.
    mine = json.loads(seen[f"{B}?company={company}"])
    assert mine["views"] == ["mine"] and mine["me"]["name"] == "Mia Member"
    for view in ("team", "all"):
        assert json.loads(seen[f"{B}?company={company}&view={view}"])["view"] is None
    everything = "\n".join(seen.values())
    assert "Retention award for two" not in everything and "9137" not in everything
    bonus_payloads = seen[f"{B}?company={company}"] + seen[f"{B}?company={company}&view=team"] \
        + seen[f"{B}?company={company}&view=all"]
    for who in ("colleague", "manager", "sales_member"):
        row = theirs[sc["who"][who].pk]
        assert sc["who"][who].user.full_name not in bonus_payloads
        assert f'"earned": {float(row.earned)}' not in bonus_payloads or \
            float(row.earned) == float(theirs[member.pk].earned)
    # The plan they aren't on, the editor of the one they are, the payroll: 404.
    assert as_member.get(f"{B}plans/{secret.pk}/").status_code == 404
    assert as_member.get(f"{B}plans/{closed_month.pk}/").status_code == 404
    key = f"monthly:{closed_month.period_start.isoformat()}"
    assert as_member.get(f"{B}payroll/?company={company}&period={key}").status_code == 404
    assert as_member.get(f"{B}?company={company}&view=mine&plan={secret.pk}").status_code == 404
    # An AI app connected by the member: no tool carries a bonus.
    p = T.Principal(connection=SimpleNamespace(membership=member, user=member.user,
                                               app_name="Claude"))
    ran, refused = [], {}
    with tenant_context(sc["tenant"].pk):
        for tool in T.READ_TOOLS:
            code = tool.__code__
            params = code.co_varnames[1:code.co_argcount]
            required = params[:len(params) - len(tool.__defaults__ or ())]
            if set(required) - {"company_id"}:
                continue                       # needs an id of something else
            tries = [{"company_id": str(company)}] if "company_id" in params else []
            if "company_id" not in required:
                tries.append({})
            for args in tries:
                try:
                    out = json.dumps(tool(p, **args), default=str)
                except T.ToolRefused as exc:  # a refusal shows nothing
                    refused[tool.__name__] = str(exc)
                    continue
                assert "Retention award" not in out and "Floor bonus" not in out, tool.__name__
                assert "9137" not in out, tool.__name__
                ran.append(tool.__name__)
    assert {"scorecard_readings", "list_tasks", "list_goals", "list_sops"} <= set(ran), \
        (ran, refused)
    # The weekly digest drafted to them says nothing of bonuses.
    with tenant_context(sc["tenant"].pk):
        member.contact = ContactFactory(tenant=sc["tenant"], company=sc["company"])
        member.save(update_fields=["contact"])
        draft = SimpleNamespace(tenant=sc["tenant"], contact=member.contact,
                                cadence=Cadence.WEEKLY, pk=None, created_at=timezone.now(),
                                period_start=today - timedelta(days=7), period_end=today)
        text, html = digests.render(draft, [])
    for words in ("bonus", "Bonus", "Floor bonus", "Retention award", "9137"):
        assert words not in text and words not in html
