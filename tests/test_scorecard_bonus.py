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
