"""P11: the plans engine (`docs/p11_plans_engine.md`).

- **Practice isolation:** another practice, an unassigned associate, a
  client of another company and a practice with no Command Center on reach
  nothing.
- **Who sees which horizons in the portal**, by level, and the team filter
  on a month's items; the sprint's tasks only where Work shows them.
- **Client-side proposals** at the year and quarter; adding at the month and
  week by Work's own rule.
- **Close the week**: done, not done, carried over (never automatic), the
  summary in the weekly digest draft; month and quarter alike.
- **The cascade:** a year's item is a goal; an item serves the one above;
  links to goals, projects, tasks and KPIs, with the KPI's status.
- **Drafts** with a fake Claude: price first, proposals naming their
  sources, accept and discard into the practice library, the excluded
  sources (mail, a PIN-locked note, another company's).
- **MCP tools'** scope, a playbook's goal on the year, a session's 30/60/90
  rows as the quarter's priorities, Home's week at a glance, the words.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.plans import periods as P
from apps.plans.models import PlanClose, PlanItem, PlanItemTask
from apps.tenancy.context import tenant_context

from .factories import ClientCompanyFactory, MembershipFactory, TenantFactory
from .test_scorecard import patch, post, sc  # noqa: F401  (the fixture)

PLANS = "/api/plans/"
ITEMS = "/api/plan-items/"


@pytest.fixture
def on(sc):
    """The practice has a Command Center on: the plan is there."""
    from apps.centers.models import PracticeCenter

    PracticeCenter.all_objects.create(tenant=sc["tenant"], center="operations",
                                      enabled_at=timezone.now())
    return sc


def client(sc, who):
    return sc["api"].as_(sc["who"].get(who) or sc["practice"][who])


def get(sc, who, path):
    return client(sc, who).get(path)


def today():
    return timezone.localdate()


def task(sc, title, *, team=None, assignee=None, status="not_started"):
    from apps.work import services as work

    with tenant_context(sc["tenant"].pk):
        made = work.create_task(tenant=sc["tenant"], actor=sc["practice"]["ff"].user, role="FF",
                                title=title, client_company=sc["company"],
                                owner=sc["practice"]["ff"].user,
                                client_team=sc["teams"][team] if team else None,
                                assignee=assignee.user if assignee else None)
        if status != "not_started":
            type(made).all_objects.filter(pk=made.pk).update(status=status)
        return made


def add(sc, who="ff", **data):
    return post(client(sc, who), ITEMS, {"company": str(sc["company"].pk), **data})


def plan_of(sc, who, **params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    r = get(sc, who, f"{PLANS}{sc['company'].pk}/" + (f"?{query}" if query else ""))
    assert r.status_code == 200, r.content
    return r.json()


def column(data, key):
    return next(c for c in data["horizons"] if c["key"] == key)


def titles(data, key):
    return [i["title"] for i in column(data, key)["items"]]


@pytest.fixture
def cascade(on):
    """A year's goal, a quarter's priority serving it, a month's item for
    the Operations team and one for Sales, and this week's sprint."""
    sc = on
    year = add(sc, horizon="year", title="Grow wholesale to 40% of sales").json()
    quarter = add(sc, horizon="quarter", title="Sign four new wholesale accounts",
                  parent=year["id"], done_means="Four signed agreements").json()
    month = add(sc, horizon="month", title="Ops: fix the picking errors", parent=quarter["id"],
                client_team=str(sc["teams"]["ops"].pk)).json()
    sales = add(sc, horizon="month", title="Sales: call twenty buyers", parent=quarter["id"],
                client_team=str(sc["teams"]["sales"].pk)).json()
    tasks = [task(sc, "Count the bins", team="ops", assignee=sc["who"]["member"]),
             task(sc, "Retrain the night shift", team="ops", status="done"),
             task(sc, "Call the buyer list", team="sales")]
    sprint = add(sc, horizon="week", title="Pick every order right the first time",
                 parent=month["id"], tasks=[str(t.pk) for t in tasks]).json()
    for r in (year, quarter, month, sales, sprint):
        assert "id" in r, r
    return {**sc, "items": {"year": year, "quarter": quarter, "month": month, "sales": sales,
                            "sprint": sprint}, "tasks": tasks}


# ------------------------------------------------------------------ isolation

def test_no_command_center_means_no_plan_anywhere(sc):
    task(sc, "Anything")
    for who in ("ff", "cf", "owner", "member"):
        assert get(sc, who, f"{PLANS}{sc['company'].pk}/").status_code == 404
    assert get(sc, "ff", PLANS).status_code == 404
    assert add(sc, horizon="month", title="X").status_code == 404
    me = client(sc, "ff").get("/api/me").json()
    assert me["has_plan"] is False


def test_another_practice_and_the_unassigned_reach_nothing(cascade):
    sc = cascade
    item = sc["items"]["quarter"]["id"]
    assert get(sc, "cf_other", f"{PLANS}{sc['company'].pk}/").status_code == 404
    stranger = MembershipFactory(tenant=TenantFactory(), role="FF")
    other = sc["api"].as_(stranger)
    for path in (f"{PLANS}{sc['company'].pk}/", f"{PLANS}{sc['company'].pk}/week/",
                 f"{PLANS}{sc['company'].pk}/sources/",
                 f"{PLANS}{sc['company'].pk}/close/?horizon=week"):
        assert other.get(path).status_code == 404
    assert patch(other, f"{ITEMS}{item}/", {"title": "Mine now"}).status_code == 404
    assert post(other, f"{ITEMS}{item}/accept/").status_code == 404
    # A client of another company of the same practice.
    elsewhere = ClientCompanyFactory(tenant=sc["tenant"], name="Elsewhere")
    outsider = MembershipFactory(tenant=sc["tenant"], role="FCC", client_company=elsewhere)
    them = sc["api"].as_(outsider)
    assert them.get(f"{PLANS}{sc['company'].pk}/").status_code == 404
    assert patch(them, f"{ITEMS}{item}/", {"status": "done"}).status_code == 404
    assert "Sign four" not in them.get(f"{PLANS}mine/").content.decode()
    # The associate assigned to Northwind reaches it, and the practice's own plan.
    assert get(sc, "cf", f"{PLANS}{sc['company'].pk}/").status_code == 200
    assert get(sc, "cf", f"{PLANS}practice/").status_code == 200
    assert get(sc, "owner", f"{PLANS}practice/").status_code == 404


def test_the_practice_owns_its_own_plan(on):
    sc = on
    r = post(client(sc, "ff"), ITEMS, {"company": "practice", "horizon": "year",
                                       "title": "Sign three new clients"})
    assert r.status_code == 201, r.content
    data = get(sc, "ff", f"{PLANS}practice/").json()
    assert data["company"]["is_practice"] is True
    assert titles(data, "year") == ["Sign three new clients"]
    from apps.work.models import Goal

    goal = Goal.all_objects.get(pk=data["horizons"][1]["items"][0]["goal"]["id"])
    assert goal.client_company_id is None          # the practice's internal work
    assert post(client(sc, "va"), ITEMS, {"company": "practice", "horizon": "year",
                                          "title": "X"}).status_code == 403


# ------------------------------------------------------------------ the portal, by level

@pytest.mark.parametrize("who", ["owner", "leader", "leader_all"])
def test_the_client_owner_and_senior_leadership_see_every_horizon(cascade, who):
    data = plan_of(cascade, who)
    assert [c["key"] for c in data["horizons"]] == ["picture", "year", "quarter", "month",
                                                   "week"]
    assert set(titles(data, "month")) == {"Ops: fix the picking errors",
                                          "Sales: call twenty buyers"}


@pytest.mark.parametrize("who", ["member", "manager", "ops_viewer"])
def test_managers_and_members_see_this_month_and_this_week_for_their_teams(cascade, who):
    data = plan_of(cascade, who)
    assert [c["key"] for c in data["horizons"]] == ["month", "week"]
    assert titles(data, "month") == ["Ops: fix the picking errors"]
    body = json.dumps(data)
    for hidden in ("Grow wholesale", "Sales: call twenty buyers"):
        assert hidden not in body
    # A month's item says what it serves only when the person may see it.
    assert column(data, "month")["items"][0]["serves"] is None


def test_the_sprint_shows_a_client_only_the_tasks_work_shows_them(cascade):
    # Work's own rule: a member sees their own tasks (P7-5); anyone above a
    # member, and the owner, every client-visible task of the company.
    def shown(who):
        sprint = column(plan_of(cascade, who), "week")["items"][0]
        return {t["title"] for t in sprint["tasks"]}
    assert shown("member") == {"Count the bins"}
    assert len(shown("manager")) == 3 and len(shown("owner")) == 3


def test_this_week_is_the_sprint_mine_my_teams_and_what_it_serves(cascade):
    r = get(cascade, "member", f"{PLANS}mine/week/")
    assert r.status_code == 200, r.content
    week = r.json()
    assert week["sprint"]["title"] == "Pick every order right the first time"
    assert [t["title"] for t in week["mine"]] == ["Count the bins"]
    # P11, 2026-11-13: their team's line, and their teammates' sprint tasks,
    # read only; never another team's.
    assert week["team_lines"] == [{"team": "Operations", "done": 1, "total": 2}]
    assert week["team"] == [{"title": "Retrain the night shift",
                             "owner": cascade["practice"]["ff"].user.full_name,
                             "status": "done", "status_label": "Done", "done": True,
                             "read_only": True}] and week["others"] == []
    manager = get(cascade, "manager", f"{PLANS}mine/week/").json()
    assert manager["mine"] == []
    assert {t["title"] for t in manager["team"]} == {"Count the bins",
                                                     "Retrain the night shift"}
    # The member sees the month it serves, not the quarter or the year.
    assert [s["title"] for s in week["serves"]] == ["Ops: fix the picking errors"]
    owner = get(cascade, "owner", f"{PLANS}mine/week/").json()
    assert [s["horizon"] for s in owner["serves"]] == ["month", "quarter", "year"]


def test_teammates_sprint_tasks_follow_the_switch_and_work_keeps_its_rule(cascade):
    from apps.crm.models import Task

    sc = cascade
    retrain = next(t for t in sc["tasks"] if t.title == "Retrain the night shift")
    Task.all_objects.filter(pk=retrain.pk).update(assignee=sc["who"]["colleague"].user)
    week = get(sc, "member", f"{PLANS}mine/week/").json()
    assert [(t["title"], t["owner"]) for t in week["team"]] == [
        ("Retrain the night shift", "Cole Colleague")]
    assert "id" not in week["team"][0]
    # The colleague sees the member's task the same way.
    theirs = get(sc, "colleague", f"{PLANS}mine/week/").json()
    assert [t["title"] for t in theirs["mine"]] == ["Retrain the night shift"]
    assert [(t["title"], t["owner"]) for t in theirs["team"]] == [("Count the bins", "Mia Member")]
    # Sales sees Sales: its own line and nothing of Operations.
    sales = get(sc, "sales_member", f"{PLANS}mine/week/").json()
    assert sales["team_lines"] == [{"team": "Sales", "done": 0, "total": 1}]
    assert "Count the bins" not in json.dumps(sales)
    # The Tasks area keeps its rule: a member opens only their own tasks.
    assert get(sc, "member", f"/api/tasks/{retrain.pk}/").status_code == 404
    listed = get(sc, "member", "/api/tasks/").json()
    rows = listed.get("results", listed) if isinstance(listed, dict) else listed
    assert "Retrain the night shift" not in json.dumps(rows)
    # Off, per client: own tasks and the team line only.
    assert patch(client(sc, "owner"), f"{PLANS}{sc['company'].pk}/",
                 {"sprint_team_tasks": False}).status_code == 403
    r = patch(client(sc, "ff"), f"{PLANS}{sc['company'].pk}/", {"sprint_team_tasks": False})
    assert r.status_code == 200 and r.json()["company"]["sprint_team_tasks"] is False
    off = get(sc, "member", f"{PLANS}mine/week/").json()
    assert [t["title"] for t in off["mine"]] == ["Count the bins"]
    assert off["team"] == [] and off["teammates"] is False
    assert off["team_lines"] == [{"team": "Operations", "done": 1, "total": 2}]
    assert patch(client(sc, "ff"), f"{PLANS}practice/", {"sprint_team_tasks": False}) \
        .status_code == 400


def test_only_this_weeks_sprint_shows_teammates_tasks(cascade):
    sc = cascade
    last = add(sc, horizon="week", title="Last week's sprint",
               period_start=(today() - timedelta(days=7)).isoformat()).json()
    older = task(sc, "Label last week's bins", team="ops", assignee=sc["who"]["colleague"])
    from apps.plans.models import PlanItemTask

    with tenant_context(sc["tenant"].pk):
        PlanItemTask.objects.create(tenant=sc["tenant"], item_id=last["id"], task=older)
    week = get(sc, "member", f"{PLANS}mine/week/").json()
    assert "Label last week's bins" not in json.dumps(week)


# ------------------------------------------------------------------ client-side adding

def test_client_additions_at_the_year_and_quarter_are_proposals(cascade):
    sc = cascade
    r = add(sc, "owner", horizon="quarter", title="Open a second warehouse")
    assert r.status_code == 201, r.content
    proposal = r.json()
    assert proposal["state"] == "proposed" and proposal["source"] == "client"
    # It waits for the practice: on the owner's own plan as theirs, in the tray.
    owner = column(plan_of(sc, "owner"), "quarter")
    assert [p["title"] for p in owner["proposals"]] == ["Open a second warehouse"]
    assert "Open a second warehouse" not in titles(plan_of(sc, "owner"), "quarter")
    assert "Open a second warehouse" not in json.dumps(plan_of(sc, "leader"))
    tray = column(plan_of(sc, "ff"), "quarter")["proposals"]
    assert tray[0]["proposed_by"] == "Olive Owner"
    # The client can't accept it; the practice does.
    assert post(client(sc, "owner"), f"{ITEMS}{proposal['id']}/accept/").status_code == 403
    assert post(client(sc, "ff"), f"{ITEMS}{proposal['id']}/accept/").status_code == 200
    assert "Open a second warehouse" in titles(plan_of(sc, "owner"), "quarter")
    # A year's proposal becomes a goal when it is accepted.
    year = add(sc, "leader", horizon="year", title="Double the margin").json()
    assert year["state"] == "proposed" and year["goal"] is None
    accepted = post(client(sc, "cf"), f"{ITEMS}{year['id']}/accept/").json()
    assert accepted["goal"]["title"] == "Double the margin"


def test_client_adding_at_the_month_and_week_follows_works_own_rule(cascade):
    sc = cascade
    # A member who may create tasks adds straight onto the month.
    r = add(sc, "member", horizon="month", title="Label every shelf",
            client_team=str(sc["teams"]["ops"].pk))
    assert r.status_code == 201 and r.json()["state"] == "accepted", r.content
    # A viewer may create nothing in Work, so nothing here.
    assert add(sc, "ops_viewer", horizon="month", title="X").status_code == 403
    # Nobody short of senior leadership adds or proposes at the year or quarter.
    assert add(sc, "member", horizon="quarter", title="X").status_code == 404
    assert add(sc, "manager", horizon="year", title="X").status_code == 404
    # A member edits their team's month item, not another team's.
    month, sales = sc["items"]["month"]["id"], sc["items"]["sales"]["id"]
    assert patch(client(sc, "member"), f"{ITEMS}{month}/", {"status": "off_track"}) \
        .status_code == 200
    assert patch(client(sc, "member"), f"{ITEMS}{sales}/", {"status": "done"}) \
        .status_code == 404
    assert patch(client(sc, "owner"), f"{ITEMS}{sc['items']['year']['id']}/",
                 {"title": "X"}).status_code == 403


# ------------------------------------------------------------------ close the week

def test_close_the_week_suggests_never_carries_by_itself_and_carries_when_chosen(cascade):
    sc = cascade
    company = sc["company"].pk
    week = P.start_of("week", today(), sc["company"])
    walk = get(sc, "ff", f"{PLANS}{company}/close/?horizon=week&period={week}").json()
    suggested = {r["title"]: r["suggested"] for r in walk["rows"]}
    assert suggested == {"Count the bins": "not_done", "Retrain the night shift": "done",
                         "Call the buyer list": "not_done"}
    bins = str(sc["tasks"][0].pk)
    r = post(client(sc, "ff"), f"{PLANS}{company}/close/",
             {"horizon": "week", "period_start": week.isoformat(),
              "outcomes": {bins: "carried"}})
    assert r.status_code == 201, r.content
    summary = r.json()["summary"]
    assert summary.startswith(f"Week of {P.MONTHS[week.month - 1]} {week.day}: “Pick every")
    assert "1 of 3 tasks done; 1 carried over to next week." in summary
    following = PlanItem.all_objects.get(company_id=company, horizon="week",
                                         period_start=week + timedelta(days=7))
    assert following.title == "Pick every order right the first time"
    assert [str(t) for t in PlanItemTask.all_objects.filter(item=following)
            .values_list("task_id", flat=True)] == [bins]
    # Not done is not carried: the buyer list stays on last week's sprint only.
    assert PlanItemTask.all_objects.filter(item=following).count() == 1
    again = post(client(sc, "ff"), f"{PLANS}{company}/close/",
                 {"horizon": "week", "period_start": week.isoformat()})
    assert again.status_code == 409


def test_closing_without_choosing_carries_nothing(cascade):
    sc = cascade
    week = P.start_of("week", today(), sc["company"])
    r = post(client(sc, "ff"), f"{PLANS}{sc['company'].pk}/close/",
             {"horizon": "week", "period_start": week.isoformat()})
    assert r.status_code == 201
    assert "carried" not in r.json()["summary"]
    assert not PlanItem.all_objects.filter(horizon="week",
                                           period_start=week + timedelta(days=7)).exists()


def test_a_client_cannot_close_and_a_month_close_carries_items_and_offers_a_draft(cascade):
    sc = cascade
    company = sc["company"].pk
    month = P.start_of("month", today(), sc["company"])
    assert post(client(sc, "owner"), f"{PLANS}{company}/close/",
                {"horizon": "month", "period_start": month.isoformat()}).status_code == 403
    r = post(client(sc, "ff"), f"{PLANS}{company}/close/",
             {"horizon": "month", "period_start": month.isoformat(),
              "outcomes": {sc["items"]["month"]["id"]: "done",
                           sc["items"]["sales"]["id"]: "carried"}})
    assert r.status_code == 201, r.content
    body = r.json()
    assert body["offer_draft"] is True and body["next"]["horizon"] == "month"
    assert "1 of 2 done; 1 carried over to" in body["summary"]
    nxt = P.next_start("month", month)
    copy = PlanItem.all_objects.get(company_id=company, horizon="month", period_start=nxt)
    assert copy.title == "Sales: call twenty buyers" and copy.source == "carried"
    assert copy.parent_id is not None
    assert PlanItem.all_objects.get(pk=sc["items"]["month"]["id"]).status == "done"


def test_the_weeks_summary_goes_into_the_weekly_digest_draft(cascade):
    from apps.work import digests
    from apps.work.models import Digest

    from .factories import ContactFactory

    sc = cascade
    with tenant_context(sc["tenant"].pk):
        contact = ContactFactory(tenant=sc["tenant"], company=sc["company"])
        draft = Digest.objects.create(
            tenant=sc["tenant"], contact=contact, cadence="weekly",
            period_start=timezone.now() - timedelta(days=6), period_end=timezone.now(),
            send_window_at=timezone.now() + timedelta(days=1), body_text="Before")
    week = P.start_of("week", today(), sc["company"])
    post(client(sc, "ff"), f"{PLANS}{sc['company'].pk}/close/",
         {"horizon": "week", "period_start": week.isoformat()})
    draft.refresh_from_db()
    assert draft.is_stale and "plan" in draft.stale_reason
    with tenant_context(sc["tenant"].pk):
        text, html = digests.render(draft, [])
    assert "From the plan" in text and "Pick every order right the first time" in text
    assert "From the plan" in html


# ------------------------------------------------------------------ the cascade

def test_a_years_item_is_one_of_the_companys_goals(cascade):
    from apps.work.models import Goal

    sc = cascade
    year = sc["items"]["year"]
    goal = Goal.all_objects.get(pk=year["goal"]["id"])
    assert goal.client_company_id == sc["company"].pk and goal.title == year["title"]
    # Or an existing goal, linked.
    with tenant_context(sc["tenant"].pk):
        existing = Goal.objects.create(tenant=sc["tenant"], client_company=sc["company"],
                                       title="Win back the Smith account")
    linked = add(sc, horizon="year", title="Win back Smith", goal=str(existing.pk)).json()
    assert linked["goal"]["id"] == str(existing.pk)
    other = ClientCompanyFactory(tenant=sc["tenant"], name="Other Co")
    with tenant_context(sc["tenant"].pk):
        theirs = Goal.objects.create(tenant=sc["tenant"], client_company=other, title="Theirs")
    r = add(sc, horizon="year", title="X", goal=str(theirs.pk))
    assert r.status_code == 400 and "this company's" in r.json()["detail"]


def test_each_item_says_what_it_serves_and_what_serves_it(cascade):
    data = plan_of(cascade, "ff")
    quarter = column(data, "quarter")["items"][0]
    assert quarter["serves"]["title"] == "Grow wholesale to 40% of sales"
    assert {c["title"] for c in quarter["served_by"]} == {"Ops: fix the picking errors",
                                                         "Sales: call twenty buyers"}
    week = column(data, "week")["items"][0]
    assert week["serves"]["title"] == "Ops: fix the picking errors"
    # An item serves only the horizon just above it.
    r = add(cascade, horizon="month", title="X", parent=cascade["items"]["year"]["id"])
    assert r.status_code == 400 and "just above" in r.json()["detail"]


def test_a_linked_kpi_shows_its_current_status(cascade):
    sc = cascade
    kpi = sc["kpis"]["all"]
    r = patch(client(sc, "ff"), f"{ITEMS}{sc['items']['quarter']['id']}/",
              {"kpis": [str(kpi.pk)]})
    assert r.status_code == 200, r.content
    shown = r.json()["kpis"][0]
    assert shown["name"] == "For everyone" and "target_text" in shown
    # A KPI the person may not see is left off, and another company's refused.
    lead = sc["kpis"]["lead"]
    patch(client(sc, "ff"), f"{ITEMS}{sc['items']['month']['id']}/", {"kpis": [str(lead.pk)]})
    month = column(plan_of(sc, "member"), "month")["items"][0]
    assert month["kpis"] == []


def test_one_sprint_a_week(cascade):
    r = add(cascade, horizon="week", title="Another sprint")
    assert r.status_code == 409 and "already has its sprint" in r.json()["detail"]


# ------------------------------------------------------------------ drafts from sources

def rows_reply(*items):
    return json.dumps({"items": list(items)})


@pytest.fixture
def sources(cascade, fake_claude):
    """A session with an accepted row, an approved meeting, an SOP note, a
    locked note and an email thread at Northwind; a session elsewhere."""
    from apps.notes.models import Note
    from apps.strategy.models import StrategyMapRow

    from .factories import ContactFactory, StrategySessionFactory

    sc = cascade
    with tenant_context(sc["tenant"].pk):
        contact = ContactFactory(tenant=sc["tenant"], company=sc["company"])
        session = StrategySessionFactory(tenant=sc["tenant"], contact=contact,
                                         company=sc["company"])
        StrategyMapRow.objects.create(tenant=sc["tenant"], session=session, position=1,
                                      state="accepted", bottleneck="Orders picked wrong",
                                      the_fix="Bin labels and a count", horizon=30)
        Note.objects.create(tenant=sc["tenant"], company=sc["company"],
                            title="SOP draft: Picking", body="Scan every bin.")
        Note.objects.create(tenant=sc["tenant"], company=sc["company"], title="SOP draft: Pay",
                            body="SECRET PAY SCALE", pin_hash="x", pin_set_at=timezone.now())
        elsewhere = ClientCompanyFactory(tenant=sc["tenant"], name="Elsewhere")
        theirs = StrategySessionFactory(tenant=sc["tenant"], company=elsewhere,
                                        contact=ContactFactory(tenant=sc["tenant"],
                                                               company=elsewhere))
    fake_claude.reply = rows_reply(
        {"title": "Label every bin", "done_means": "Every bin has a label",
         "serves": sc["items"]["month"]["id"], "drew_on": ["S1", "S2"]},
        {"title": "Count the top fifty bins weekly", "done_means": "", "drew_on": ["S9"]})
    return {**sc, "session": session, "theirs": theirs, "fake": fake_claude}


def test_the_draft_says_its_price_first_and_offers_only_this_companys_sources(sources):
    sc = sources
    r = get(sc, "ff", f"{PLANS}{sc['company'].pk}/sources/")
    assert r.status_code == 200
    data = r.json()
    assert Decimal(data["ai"]["estimate_usd"]) >= 0 and data["ai"]["cap"] == 20
    labels = {s["label"] for s in data["sources"]}
    assert "SOP draft: Picking" in labels
    assert "SOP draft: Pay" not in labels                     # PIN-locked
    assert not any("Elsewhere" in s["label"] for s in data["sources"])
    assert {s["type"] for s in data["sources"]} <= {"session", "sop", "meeting", "scorecard",
                                                    "document"}
    for who in ("owner", "va"):
        assert get(sc, who, f"{PLANS}{sc['company'].pk}/sources/").status_code == 404


def test_a_draft_lands_in_the_tray_naming_what_it_drew_on(sources):
    sc = sources
    sop = next(s for s in get(sc, "ff", f"{PLANS}{sc['company'].pk}/sources/").json()["sources"]
               if s["type"] == "sop")
    week = P.start_of("week", today(), sc["company"])
    r = post(client(sc, "ff"), f"{PLANS}{sc['company'].pk}/draft/",
             {"horizon": "week", "period_start": (week + timedelta(days=7)).isoformat(),
              "sources": [{"type": "session", "id": str(sc["session"].pk)}, sop],
              "pasted": "Notebook: the night shift misses scans."})
    assert r.status_code == 201, r.content
    proposals = r.json()["proposals"]
    assert [p["title"] for p in proposals] == ["Label every bin",
                                              "Count the top fifty bins weekly"]
    assert proposals[0]["drew_on"][0].startswith("Strategy session")
    assert proposals[0]["drew_on"][1] == "SOP draft: Picking"
    assert all(p["state"] == "proposed" and p["from_ai"] for p in proposals)
    sent = sc["fake"].requests[-1]
    text = json.dumps(sent["messages"])
    assert "Bin labels and a count" in text and "Scan every bin." in text
    assert "night shift misses scans" in text
    assert "SECRET PAY SCALE" not in text
    assert sent["model"].startswith("claude-opus")                # Deep
    # Nothing is on the plan until someone accepts.
    nxt = plan_of(sc, "ff", week=(week + timedelta(days=7)).isoformat())
    assert column(nxt, "week")["items"] == []
    assert len(column(nxt, "week")["proposals"]) == 2


def test_accepts_and_discards_go_to_the_practice_library(sources):
    from apps.centers.models import LibraryRecord

    sc = sources
    r = post(client(sc, "ff"), f"{PLANS}{sc['company'].pk}/draft/",
             {"horizon": "month", "sources": [{"type": "session", "id": str(sc["session"].pk)}]})
    first, second = r.json()["proposals"]
    assert post(client(sc, "ff"), f"{ITEMS}{first['id']}/accept/").status_code == 200
    assert post(client(sc, "ff"), f"{ITEMS}{second['id']}/discard/").status_code == 200
    kinds = dict(LibraryRecord.all_objects.filter(source_type="plan_item")
                 .values_list("title", "kind"))
    assert kinds == {"Label every bin": "plan_item_accepted",
                     "Count the top fifty bins weekly": "plan_item_rejected"}
    assert "Label every bin" in titles(plan_of(sc, "ff"), "month")


@pytest.mark.parametrize("bad", ["locked_note", "other_company", "mail"])
def test_excluded_sources_are_refused(sources, bad):
    from apps.notes.models import Note

    sc = sources
    if bad == "locked_note":
        note = Note.all_objects.get(title="SOP draft: Pay")
        chosen = {"type": "sop", "id": f"note:{note.pk}"}
    elif bad == "other_company":
        chosen = {"type": "session", "id": str(sc["theirs"].pk)}
    else:
        chosen = {"type": "mail", "id": "anything"}
    r = post(client(sc, "ff"), f"{PLANS}{sc['company'].pk}/draft/",
             {"horizon": "month", "sources": [chosen]})
    assert r.status_code == 400
    assert sc["fake"].requests == []


def test_break_this_down_proposes_the_items_beneath(sources):
    sc = sources
    r = post(client(sc, "ff"), f"{PLANS}{sc['company'].pk}/draft/",
             {"parent": sc["items"]["quarter"]["id"]})
    assert r.status_code == 201, r.content
    proposals = r.json()["proposals"]
    assert {p["horizon"] for p in proposals} == {"month"}
    assert all(p["serves"]["id"] == sc["items"]["quarter"]["id"] for p in proposals)
    assert "Sign four new wholesale accounts" in json.dumps(sc["fake"].requests[-1]["messages"])


def test_only_the_practice_drafts(sources):
    for who in ("va", "owner", "member"):
        r = post(client(sources, who), f"{PLANS}{sources['company'].pk}/draft/",
                 {"horizon": "month", "pasted": "x"})
        assert r.status_code in (403, 404)


# ------------------------------------------------------------------ MCP

def principal(sc, who):
    from apps.aiconnect import tools as T

    from .factories import AiAppConnectionFactory

    member = sc["who"].get(who) or sc["practice"][who]
    return T.Principal(AiAppConnectionFactory(tenant=sc["tenant"], membership=member))


def test_mcp_reads_a_plan_by_horizon_within_the_persons_reach(cascade):
    from apps.aiconnect import tools as T

    sc = cascade
    with tenant_context(sc["tenant"].pk):
        got = T.company_plan(principal(sc, "cf"), str(sc["company"].pk), "quarter")
        assert [h["horizon"] for h in got["horizons"]] == ["quarter"]
        assert got["horizons"][0]["items"][0]["serves"] == "Grow wholesale to 40% of sales"
        with pytest.raises(T.ToolRefused):
            T.company_plan(principal(sc, "cf_other"), str(sc["company"].pk))
        with pytest.raises(T.ToolRefused):
            T.company_plan(principal(sc, "owner"), str(sc["company"].pk))
        with pytest.raises(T.ToolRefused):
            T.company_plan(principal(sc, "ff"), str(sc["company"].pk), "rocks")


def test_mcp_proposals_land_in_the_tray_marked_as_an_ai_apps(cascade):
    from apps.aiconnect import tools as T

    sc = cascade
    with tenant_context(sc["tenant"].pk):
        got = T.propose_plan_items(principal(sc, "ff"), str(sc["company"].pk), "month",
                                   [{"title": "Audit the returns shelf",
                                     "serves_id": sc["items"]["quarter"]["id"]}])
        item = PlanItem.objects.get(pk=got["ids"][0])
        assert (item.state, item.from_ai_app, item.source) == ("proposed", True, "ai_app")
        assert item.parent_id is not None
        for who in ("va", "owner"):
            with pytest.raises(T.ToolRefused):
                T.propose_plan_items(principal(sc, who), str(sc["company"].pk), "month",
                                     [{"title": "X"}])
        with pytest.raises(T.ToolRefused):
            T.propose_plan_items(principal(sc, "ff"), str(sc["company"].pk), "month",
                                 [{"title": "X", "serves_id": sc["items"]["year"]["id"]}])
    tray = column(plan_of(sc, "ff"), "month")["proposals"]
    assert tray[0]["from_ai_app"] is True
    assert "Audit the returns shelf" not in json.dumps(plan_of(sc, "owner"))


# ------------------------------------------------------------------ from other modules

def test_a_playbook_started_puts_its_goal_on_the_years_plan(on):
    from apps.centers import playbooks

    sc = on
    with tenant_context(sc["tenant"].pk):
        book = playbooks.copy_shipped(sc["tenant"], "ops_90_day_reset")
        playbooks.save(book, name=book.name, description=book.description,
                       outline=book.outline, ready=True, actor=sc["practice"]["ff"].user)
        run = playbooks.start(book, company=sc["company"], start_date=today(),
                              lead=sc["practice"]["ff"].user, actor=sc["practice"]["ff"].user,
                              role="FF")
    year = column(plan_of(sc, "ff"), "year")["items"]
    assert [i["goal"]["id"] for i in year] == [str(run.goal_id)]
    assert year[0]["source"] == "playbook"


def test_a_converted_sessions_30_60_90_rows_become_the_quarters_priorities(on):
    from apps.strategy.models import StrategyMapRow
    from apps.work.models import Goal

    from .factories import ContactFactory, StrategySessionFactory

    sc = on
    with tenant_context(sc["tenant"].pk):
        contact = ContactFactory(tenant=sc["tenant"], company=sc["company"])
        session = StrategySessionFactory(tenant=sc["tenant"], contact=contact,
                                         company=sc["company"], converted_at=timezone.now(),
                                         state="converted")
        row = StrategyMapRow.objects.create(
            tenant=sc["tenant"], session=session, position=1, state="accepted",
            bottleneck="Quotes take a week", the_fix="A price book for the top 50 parts",
            horizon=60, measurable="Quotes out in 48 hours", converted_to="goal")
        StrategyMapRow.objects.create(tenant=sc["tenant"], session=session, position=2,
                                      state="accepted", bottleneck="No horizon")
        Goal.objects.create(tenant=sc["tenant"], client_company=sc["company"],
                            title="Quotes take a week", source_map_row=row)
    r = post(client(sc, "ff"), f"{PLANS}from-session/", {"session": str(session.pk)})
    assert r.status_code == 201, r.content
    assert r.json()["titles"] == ["A price book for the top 50 parts"]
    data = plan_of(sc, "ff")
    quarter = column(data, "quarter")["items"][0]
    assert quarter["done_means"] == "Quotes out in 48 hours"
    assert quarter["serves"]["title"] == "Quotes take a week"
    assert titles(data, "year") == ["Quotes take a week"]
    assert post(client(sc, "ff"), f"{PLANS}from-session/",
                {"session": str(session.pk)}).status_code == 409
    assert post(client(sc, "owner"), f"{PLANS}from-session/",
                {"session": str(session.pk)}).status_code in (403, 404)


def test_home_shows_each_clients_week_at_a_glance(cascade):
    sc = cascade
    patch(client(sc, "ff"), f"{ITEMS}{sc['items']['month']['id']}/", {"status": "off_track"})
    rows = client(sc, "ff").get("/api/dashboard/").json()["clients"]
    row = next(r for r in rows if r["name"] == "Northwind Foods")
    assert row["week"] == {"sprint": "Pick every order right the first time", "done": 1,
                           "total": 3, "off_track": 1}
    index = get(sc, "ff", PLANS).json()["plans"]
    assert index[0]["is_practice"] is True
    assert any(p["name"] == "Northwind Foods" and p["week"]["total"] == 3 for p in index)


# ------------------------------------------------------------------ words, periods, terms

def test_the_horizon_names_are_the_practices_own_words(on):
    sc = on
    ff = client(sc, "ff")
    r = ff.put("/api/settings/words", json.dumps({"words": {}, "horizons": {
        "quarter": "Quarter's big three", "week": "This week"}}),
        content_type="application/json")
    assert r.status_code == 200, r.content
    names = r.json()["horizons"]
    assert names["quarter"] == "Quarter's big three" and names["year"] == "This year's goals"
    assert column(plan_of(sc, "ff"), "quarter")["name"] == "Quarter's big three"
    assert ff.get("/api/me").json()["horizons"]["week"] == "This week"
    bad = ff.put("/api/settings/words", json.dumps({"words": {}, "horizons": {
        "year": "Year 2027 goals"}}), content_type="application/json")
    assert bad.status_code == 400 and "horizons.year" in bad.json()["errors"]
    # Saving the four words alone keeps the horizon names.
    ff.put("/api/settings/words", json.dumps({"words": {"task": {"singular": "action",
                                                                  "plural": "actions"}}}),
           content_type="application/json")
    assert ff.get("/api/me").json()["horizons"]["quarter"] == "Quarter's big three"


def test_a_fiscal_year_moves_the_year_and_its_quarters(on):
    sc = on
    r = patch(client(sc, "ff"), f"{PLANS}{sc['company'].pk}/", {"fiscal_year_start": 7})
    assert r.status_code == 200, r.content
    company = sc["company"]
    company.refresh_from_db()
    assert P.start_of("year", date(2026, 11, 13), company) == date(2026, 7, 1)
    assert P.start_of("quarter", date(2026, 11, 13), company) == date(2026, 10, 1)
    assert P.label("year", date(2026, 7, 1)) == "July 2026 to June 2027"
    assert P.label("quarter", date(2026, 10, 1)) == "October to December 2026"
    assert patch(client(sc, "owner"), f"{PLANS}{sc['company'].pk}/",
                 {"fiscal_year_start": 1}).status_code == 403
    assert patch(client(sc, "ff"), f"{PLANS}{sc['company'].pk}/",
                 {"fiscal_year_start": 13}).status_code == 400


def test_no_eos_term_in_what_the_plan_ships():
    from apps.plans import ai, sources
    from apps.plans.models import Horizon, PlanItem
    from apps.tenancy import words

    from .test_command_centers import BANNED

    shipped = [ai.SYSTEM, *words.HORIZON_DEFAULTS.values(), *dict(Horizon.choices).values(),
               *dict(PlanItem.Source.choices).values(), *sources.WHAT.values(),
               *sources.KIND_LABEL.values()]
    for text in shipped:
        assert not BANNED.search(text), text
    assert re.search(r"\bpriorit", ai.SYSTEM)


def test_a_sprint_task_names_its_client_owner(cascade):
    from apps.crm.models import Task

    from .factories import ContactFactory

    sc = cascade
    with tenant_context(sc["tenant"].pk):
        who = ContactFactory(tenant=sc["tenant"], company=sc["company"], first_name="Marvin",
                             last_name="Martian")
    Task.all_objects.filter(pk=sc["tasks"][0].pk).update(client_owner_contact=who)
    sprint = column(plan_of(sc, "ff"), "week")["items"][0]
    row = next(t for t in sprint["tasks"] if t["title"] == "Count the bins")
    assert row["client_owner"] == "Marvin Martian"
