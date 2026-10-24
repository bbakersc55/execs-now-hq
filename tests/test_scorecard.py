"""M5 part 1: the KPI scorecard by hand (`docs/p6_m5_kpi_scorecard.md`).

- **Who sees what**, every rule of the spec's table, asked through the API
  the person calls: Everyone at the company (Viewers included), Senior
  leadership and up, One team, Each person sees their own; a KPI narrows its
  page and never widens it; practice users see every KPI of the companies
  they reach; a page a person can't see isn't listed, and the API refuses a
  KPI they can't see, not just the screen.
- **The leak cases**: a per-person KPI never shows a member a colleague's
  value, in the tile, the trend, the total, the entry form, the bulk table
  or a reading's history, unless the practice has switched its leaderboard
  on, which shares the ranked list within the KPI's audience and nothing more.
- **Computed KPIs**, one step only, and the reminder line in the next digest.
- **Entering**: who may, which rows, units refused with a reason, a future
  period refused, saving again keeps the history.
- **Isolation**: another practice, and another company of the same practice.
- **Setup**: only the practice owner and associates; audited, in Activity.
- **The arithmetic**: periods, week start, roll-up, seasonal targets, status.
- **Reminders**: once per closed period, cleared by the reading.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.scorecard import periods as P
from apps.scorecard import readings, setup
from apps.scorecard.models import Kpi, KpiReading, KpiReminder, Scorecard
from apps.tenancy.context import tenant_context
from apps.tenancy.models import AuditEvent, ClientAssignment, Membership
from apps.work import teams
from apps.work.models import ClientTeam, ClientTeamMember

from . import registry_config  # noqa: F401
from .factories import ClientCompanyFactory, MembershipFactory, TenantFactory

L = ClientTeamMember.Level
B = "/api/scorecard/"


def post(client, url, data=None):
    return client.post(url, json.dumps(data or {}), content_type="application/json")


def patch(client, url, data):
    return client.patch(url, json.dumps(data), content_type="application/json")


def only(membership, team, level):
    ClientTeamMember.all_objects.filter(membership=membership).delete()
    if team is not None:
        teams.place(team, membership, level)
    return membership


def last_week(week_start="monday"):
    today = timezone.localdate()
    return P.previous_start(P.start_of(today, P.WEEKLY, week_start), P.WEEKLY, week_start)


@pytest.fixture
def sc(seeded_tenant, ff, api):
    """Northwind Foods: a person at each level, two teams beside the default
    one, and a scorecard with a KPI for every audience."""
    tenant = seeded_tenant
    company = ClientCompanyFactory(tenant=tenant, name="Northwind Foods", seat_count=30)

    def person(role="ECC", name=""):
        m = MembershipFactory(tenant=tenant, role=role, client_company=company)
        if name:
            m.user.full_name = name
            m.user.save(update_fields=["full_name"])
        return m

    everyone = teams.default_team(tenant.pk, company.pk)
    ops = ClientTeam.all_objects.create(tenant=tenant, client_company=company, name="Operations")
    sales = ClientTeam.all_objects.create(tenant=tenant, client_company=company, name="Sales")
    who = {
        "owner": person("FCC", "Olive Owner"),
        "viewer": only(person(name="Vic Viewer"), everyone, L.VIEWER),
        "member": only(person(name="Mia Member"), ops, L.MEMBER),
        "colleague": only(person(name="Cole Colleague"), ops, L.MEMBER),
        "manager": only(person(name="Max Manager"), ops, L.MANAGER),
        "leader": only(person(name="Lee Leader"), ops, L.LEADER),
        "leader_all": only(person(name="Ada Allteams"), None, None),
        "on_no_team": only(person(name="Nobody Noteam"), None, None),
        "sales_member": only(person(name="Sam Sales"), sales, L.MEMBER),
        "ops_viewer": only(person(name="Otto Opsviewer"), ops, L.VIEWER),
    }
    Membership.all_objects.filter(pk=who["leader_all"].pk).update(leads_all_teams=True)
    who["leader_all"].refresh_from_db()

    cf_assigned = MembershipFactory(tenant=tenant, role="CF")
    ClientAssignment.all_objects.create(tenant=tenant, user=cf_assigned.user, company=company,
                                        assigned_by=ff.user)
    practice = {"ff": ff, "cf": cf_assigned,
                "cf_other": MembershipFactory(tenant=tenant, role="CF"),
                "va": MembershipFactory(tenant=tenant, role="VA")}

    with tenant_context(tenant.pk):
        card = setup.ensure(company, ff.user)
        weekly = card.pages.get()
        leaders = setup.create_page(card, {"name": "Leaders", "audience": "leadership"}, ff.user)
        ops_page = setup.create_page(card, {"name": "Ops page", "audience": "team",
                                            "team": str(ops.pk)}, ff.user)
        each = setup.create_page(card, {"name": "Each", "audience": "each_person"}, ff.user)

        def kpi(name, page, **extra):
            return setup.create_kpi(card, {"name": name, "kind": "count", "cadence": "weekly",
                                           "rollup": "sum", "target_value": 10,
                                           "page": str(page.pk), **extra}, ff.user)

        kpis = {
            "all": kpi("For everyone", weekly, reading_owner=str(who["owner"].user_id)),
            "lead": kpi("Cash", weekly, audience="leadership"),
            "ops": kpi("Ops only", weekly, audience="team", audience_team=str(ops.pk)),
            "calls": kpi("Calls", weekly, per_person=True, leaderboard=False,
                         tile="leaderboard", reading_owner=str(who["manager"].user_id),
                         people=[str(who[k].pk) for k in
                                 ("member", "colleague", "manager", "sales_member")]),
            "cash": kpi("Margin", leaders),
            "opspage": kpi("Ops page KPI", ops_page),
            "rating": kpi("Rating", each, per_person=True, audience="each_person",
                          people=[str(who[k].pk) for k in ("member", "colleague", "sales_member")]),
            "va_owned": kpi("Assistant's", weekly, reading_owner=str(practice["va"].user_id)),
        }
        week = last_week()
        values = {"member": 12, "colleague": 7, "manager": 9, "sales_member": 15}
        for key, value in values.items():
            KpiReading.objects.create(tenant=tenant, kpi=kpis["calls"], period_start=week,
                                      membership=who[key], value=value, entered_by=ff.user,
                                      entered_at=timezone.now())
        for key, value in (("member", 4), ("colleague", 2), ("sales_member", 5)):
            KpiReading.objects.create(tenant=tenant, kpi=kpis["rating"], period_start=week,
                                      membership=who[key], value=value, entered_by=ff.user,
                                      entered_at=timezone.now())
        KpiReading.objects.create(tenant=tenant, kpi=kpis["lead"], period_start=week,
                                  value=777001, entered_by=ff.user, entered_at=timezone.now())
    return {"tenant": tenant, "company": company, "who": who, "practice": practice, "card": card,
            "api": api, "kpis": kpis, "week": week, "teams": {"ops": ops, "sales": sales},
            "pages": {"weekly": weekly, "leaders": leaders, "ops": ops_page, "each": each}}


def board(client, company, page=None, window="this_month"):
    url = f"{B}?company={company.pk}&window={window}"
    if page:
        url += f"&page={page}"
    response = client.get(url)
    assert response.status_code == 200, response.content
    return response.json()


def seen(sc, membership):
    """Every KPI name the person is sent, over every page they are listed."""
    client = sc["api"].as_(membership)
    first = board(client, sc["company"])
    names = {}
    for page in first["pages"]:
        data = board(client, sc["company"], page["id"])
        for t in data["kpis"]:
            names[t["name"]] = t
    return {p["name"] for p in first["pages"]}, names


ALL = {"For everyone", "Cash", "Ops only", "Calls", "Margin", "Ops page KPI", "Rating",
       "Assistant's"}
EXPECTED = {
    # Senior leadership and up, and the practice: everything.
    "owner": ALL, "leader": ALL, "leader_all": ALL,
    # A viewer sees what is for everyone, and nothing per person that isn't theirs.
    "viewer": {"For everyone", "Assistant's"},
    "on_no_team": {"For everyone", "Assistant's"},
    # On Operations: its KPIs; their own row on per-person ones.
    "member": {"For everyone", "Assistant's", "Ops only", "Calls", "Ops page KPI", "Rating"},
    "colleague": {"For everyone", "Assistant's", "Ops only", "Calls", "Ops page KPI", "Rating"},
    "manager": {"For everyone", "Assistant's", "Ops only", "Calls", "Ops page KPI", "Rating"},
    # A viewer on the team sees the team's KPIs, and no per-person row.
    "ops_viewer": {"For everyone", "Assistant's", "Ops only", "Ops page KPI"},
    "sales_member": {"For everyone", "Assistant's", "Calls", "Rating"},
}
PAGES = {
    "viewer": {"Weekly scorecard"}, "on_no_team": {"Weekly scorecard"},
    "member": {"Weekly scorecard", "Ops page", "Each"},
    "colleague": {"Weekly scorecard", "Ops page", "Each"},
    "manager": {"Weekly scorecard", "Ops page", "Each"},
    "ops_viewer": {"Weekly scorecard", "Ops page"},
    "sales_member": {"Weekly scorecard", "Each"},
}


@pytest.mark.django_db
@pytest.mark.parametrize("key", sorted(EXPECTED))
def test_who_sees_what_every_client_level(sc, key):
    pages, names = seen(sc, sc["who"][key])
    assert set(names) == EXPECTED[key], key
    if key in PAGES:
        assert pages == PAGES[key], "a page a person can't see isn't listed"
    else:
        assert pages == {"Weekly scorecard", "Leaders", "Ops page", "Each"}


@pytest.mark.django_db
@pytest.mark.parametrize("key", ["ff", "cf", "va"])
def test_practice_users_see_every_kpi_of_a_company_they_reach(sc, key):
    _, names = seen(sc, sc["practice"][key])
    assert set(names) == ALL
    calls = names["Calls"]
    assert {r["name"] for r in calls["rows"]} == {"Mia Member", "Cole Colleague",
                                                  "Max Manager", "Sam Sales"}


@pytest.mark.django_db
def test_an_associate_not_assigned_finds_nothing(sc):
    client = sc["api"].as_(sc["practice"]["cf_other"])
    assert client.get(f"{B}?company={sc['company'].pk}").status_code == 404
    assert client.get(f"{B}setup/?company={sc['company'].pk}").status_code == 404
    assert client.get(f"{B}entry/?company={sc['company'].pk}").status_code == 404
    reading = KpiReading.all_objects.filter(kpi=sc["kpis"]["calls"]).first()
    assert client.get(f"{B}readings/{reading.pk}/history/").status_code == 404
    assert patch(client, f"{B}kpis/{sc['kpis']['all'].pk}/", {"name": "x"}).status_code == 404


@pytest.mark.django_db
def test_the_api_refuses_a_kpi_the_reader_cannot_see_not_only_the_screen(sc):
    member = sc["api"].as_(sc["who"]["member"])
    text = json.dumps([board(member, sc["company"], p) for p in
                       [x["id"] for x in board(member, sc["company"])["pages"]]])
    assert "Cash" not in text and "777001" not in text and "Margin" not in text
    lead = KpiReading.all_objects.get(kpi=sc["kpis"]["lead"])
    assert member.get(f"{B}readings/{lead.pk}/history/").status_code == 404
    # Asking for a page they can't see gives them their first one instead.
    data = board(member, sc["company"], str(sc["pages"]["leaders"].pk))
    assert data["page"] != str(sc["pages"]["leaders"].pk)
    saved = post(member, f"{B}readings/", {"company": str(sc["company"].pk), "readings": [
        {"kpi": str(sc["kpis"]["lead"].pk), "period_start": str(sc["week"]), "value": "1"}]})
    assert saved.status_code == 400
    assert "isn't on a scorecard you can see" in json.dumps(saved.json())
    assert KpiReading.all_objects.get(kpi=sc["kpis"]["lead"]).value == Decimal("777001")


@pytest.mark.django_db
def test_a_kpi_narrows_its_page_and_never_widens_it(sc):
    """A KPI on a senior-leadership page set to "same as its page" or to a
    team stays senior leadership and up."""
    with tenant_context(sc["tenant"].pk):
        widened = setup.create_kpi(Scorecard.objects.get(company=sc["company"]), {
            "name": "Tries to widen", "kind": "count", "audience": "team",
            "audience_team": str(sc["teams"]["ops"].pk),
            "page": str(sc["pages"]["leaders"].pk)}, sc["practice"]["ff"].user)
    for key in ("member", "manager", "viewer"):
        _, names = seen(sc, sc["who"][key])
        assert widened.name not in names, key
    _, names = seen(sc, sc["who"]["leader"])
    assert widened.name in names


# ----------------------------------------------------------- the leak cases

@pytest.mark.django_db
def test_a_member_is_sent_their_own_row_and_nothing_of_a_colleague(sc):
    member = sc["api"].as_(sc["who"]["member"])
    pages = board(member, sc["company"])["pages"]
    everything = [board(member, sc["company"], p["id"]) for p in pages]
    text = json.dumps(everything)
    # Max manages the team and is named as Calls' reading owner, which is not
    # a value; his row is.
    for name in ("Cole Colleague", "Sam Sales"):
        assert name not in text, f"{name} leaked to a member"
    assert '"Max Manager", "you"' not in text and "9.0" not in text
    calls = next(t for d in everything for t in d["kpis"] if t["name"] == "Calls")
    assert calls["shape"] == "my_row" and calls["total"] is False
    assert [(r["name"], r["value"]) for r in calls["rows"]] == [("Mia Member", 12.0)]
    assert calls["summary"]["value"] == 12.0, "their own value, never the total"
    assert all(p["value"] in (None, 12.0) for p in calls["history"] + calls["spark"])
    rating = next(t for d in everything for t in d["kpis"] if t["name"] == "Rating")
    assert [r["name"] for r in rating["rows"]] == ["Mia Member"]


@pytest.mark.django_db
def test_a_manager_is_sent_their_teams_rows_and_a_total_of_those_alone(sc):
    manager = sc["api"].as_(sc["who"]["manager"])
    _, names = seen(sc, sc["who"]["manager"])
    calls = names["Calls"]
    assert calls["shape"] == "leaderboard"
    assert [(r["name"], r["value"], r["rank"]) for r in calls["rows"]] == [
        ("Mia Member", 12.0, 1), ("Max Manager", 9.0, 2), ("Cole Colleague", 7.0, 3)]
    assert calls["total_label"] == "your team's total"
    assert calls["summary"]["value"] == 28.0, "12 + 9 + 7: Sam on Sales is not in it"
    assert "Sam Sales" not in json.dumps(board(manager, sc["company"]))
    rating = names["Rating"]
    assert {r["name"] for r in rating["rows"]} == {"Mia Member", "Cole Colleague"}


@pytest.mark.django_db
def test_the_entry_form_and_bulk_table_never_carry_a_colleagues_row(sc):
    member = sc["api"].as_(sc["who"]["member"])
    form = member.get(f"{B}entry/?company={sc['company'].pk}&day={sc['week']}").json()
    calls = next(k for k in form["kpis"] if k["name"] == "Calls")
    assert [f["name"] for f in calls["fields"]] == ["Mia Member"]
    text = json.dumps(form)
    assert "Cole Colleague" not in text and "Sam Sales" not in text
    sheet = member.get(f"{B}bulk/?company={sc['company'].pk}&cadence=weekly").json()
    assert {line["person"] for line in sheet["lines"] if line["per_person"]} == {"Mia Member"}

    manager = sc["api"].as_(sc["who"]["manager"])
    form = manager.get(f"{B}entry/?company={sc['company'].pk}&day={sc['week']}").json()
    calls = next(k for k in form["kpis"] if k["name"] == "Calls")
    assert {f["name"] for f in calls["fields"]} == {"Mia Member", "Cole Colleague", "Max Manager"}


@pytest.mark.django_db
def test_a_member_cannot_read_or_write_a_colleagues_reading(sc):
    member = sc["api"].as_(sc["who"]["member"])
    theirs = KpiReading.all_objects.get(kpi=sc["kpis"]["calls"],
                                        membership=sc["who"]["colleague"])
    assert member.get(f"{B}readings/{theirs.pk}/history/").status_code == 404
    mine = KpiReading.all_objects.get(kpi=sc["kpis"]["calls"], membership=sc["who"]["member"])
    assert member.get(f"{B}readings/{mine.pk}/history/").status_code == 200
    refused = post(member, f"{B}readings/", {"company": str(sc["company"].pk), "readings": [
        {"kpi": str(sc["kpis"]["calls"].pk), "period_start": str(sc["week"]),
         "membership": str(sc["who"]["colleague"].pk), "value": "99"}]})
    assert refused.status_code == 400
    assert "You can't enter this person's reading." in json.dumps(refused.json())
    theirs.refresh_from_db()
    assert theirs.value == 7


@pytest.mark.django_db
def test_a_level_changed_on_the_teams_card_changes_the_scorecard_at_once(sc):
    member = sc["who"]["member"]
    _, names = seen(sc, member)
    assert "Ops only" in names
    teams.set_level(sc["teams"]["ops"], member, None, actor=sc["practice"]["ff"].user)
    teams.set_level(sc["teams"]["sales"], member, L.MEMBER, actor=sc["practice"]["ff"].user)
    _, names = seen(sc, member)
    assert "Ops only" not in names and "Ops page KPI" not in names
    teams.set_level(sc["teams"]["sales"], member, L.LEADER, actor=sc["practice"]["ff"].user)
    _, names = seen(sc, member)
    assert set(names) == ALL


# ------------------------------------------------------------------ entering

def enter(client, sc, kpi, value, week=None, membership=None):
    return post(client, f"{B}readings/", {"company": str(sc["company"].pk), "readings": [
        {"kpi": str(sc["kpis"][kpi].pk), "period_start": str(week or sc["week"]),
         "membership": str(membership.pk) if membership else None, "value": value}]})


@pytest.mark.django_db
def test_who_may_enter_which_reading(sc):
    who, practice, api = sc["who"], sc["practice"], sc["api"]
    # The client owner and senior leadership enter any reading.
    for key in ("owner", "leader", "leader_all"):
        assert enter(api.as_(who[key]), sc, "all", "3").status_code == 200, key
    # The practice owner and associates always may.
    for key in ("ff", "cf"):
        assert enter(api.as_(practice[key]), sc, "lead", "5").status_code == 200, key
    # An assistant enters what they own, and nothing else.
    assert enter(api.as_(practice["va"]), sc, "va_owned", "4").status_code == 200
    assert enter(api.as_(practice["va"]), sc, "all", "4").status_code == 400
    # A member enters their own row of a per-person KPI, and not a company KPI
    # someone else owns.
    assert enter(api.as_(who["member"]), sc, "calls", "13",
                 membership=who["member"]).status_code == 200
    assert enter(api.as_(who["member"]), sc, "all", "1").status_code == 400
    # A viewer never enters anything, even one named as a reading owner.
    with tenant_context(sc["tenant"].pk):
        Kpi.objects.filter(pk=sc["kpis"]["all"].pk).update(reading_owner=who["viewer"].user)
    viewer = api.as_(who["viewer"])
    assert enter(viewer, sc, "all", "1").status_code == 403
    assert board(viewer, sc["company"])["may_enter"] is False
    assert viewer.get(f"{B}entry/?company={sc['company'].pk}").status_code == 403


@pytest.mark.django_db
def test_the_entry_button_shows_only_for_people_who_may_enter_something(sc):
    api = sc["api"]
    for key, expected in (("owner", True), ("leader", True), ("member", True),
                          ("viewer", False), ("on_no_team", False), ("ops_viewer", False)):
        assert board(api.as_(sc["who"][key]), sc["company"])["may_enter"] is expected, key
    for key in ("ff", "cf", "va"):
        assert board(api.as_(sc["practice"][key]), sc["company"])["may_enter"] is True, key


@pytest.mark.django_db
def test_saving_again_replaces_the_value_and_keeps_its_history(sc):
    owner = sc["api"].as_(sc["who"]["owner"])
    assert enter(owner, sc, "all", "8").status_code == 200
    second = enter(owner, sc, "all", "9")
    assert second.json() == {"saved": 0, "changed": 1, "errors": {}}
    reading = KpiReading.all_objects.get(kpi=sc["kpis"]["all"], period_start=sc["week"])
    assert reading.value == 9 and reading.times_changed == 1
    history = owner.get(f"{B}readings/{reading.pk}/history/").json()
    assert [(c["value"], c["previous"]) for c in history["changes"]] == [(8.0, None), (9.0, 8.0)]
    assert all(c["by"] == "Olive Owner" for c in history["changes"])
    point = next(p for p in board(owner, sc["company"], window="this_month")["kpis"][0]["history"]
                 if p["period_start"] == str(sc["week"]))
    assert point["edited"] is True
    # Saving the same value again changes nothing.
    assert enter(owner, sc, "all", "9").json()["changed"] == 0


@pytest.mark.django_db
def test_a_future_period_and_a_mid_week_date_are_refused(sc):
    owner = sc["api"].as_(sc["who"]["owner"])
    future = sc["week"] + timedelta(days=14)
    refused = enter(owner, sc, "all", "1", week=future)
    assert refused.status_code == 400 and "future period" in json.dumps(refused.json())
    tuesday = enter(owner, sc, "all", "1", week=sc["week"] + timedelta(days=1))
    assert "isn't the start of a week" in json.dumps(tuesday.json())
    form = owner.get(f"{B}entry/?company={sc['company'].pk}&day={future}")
    assert form.status_code == 400


@pytest.mark.django_db
def test_the_field_refuses_the_wrong_shape_and_says_why(sc):
    with tenant_context(sc["tenant"].pk):
        kpi = sc["kpis"]["all"]
        for kind, raw, said in (("count", "2.5", "A count is a whole number"),
                                ("count", "abc", "That isn't a number"),
                                ("percent", "0.82", "Type the percent as 82, not 0.82."),
                                ("money", "12.345", "at most two places"),
                                ("rating", "7", "A rating is from 0 to 5"),
                                ("duration", "-3", "can't be negative")):
            kpi.kind, kpi.target_value = kind, Decimal(80)
            kpi.rating_scale = 5 if kind == "rating" else None
            with pytest.raises(readings.ReadingRefused, match=said):
                readings.parse(kpi, raw)
        kpi.kind = "percent"
        assert readings.parse(kpi, "82%") == Decimal("82")
        kpi.kind = "money"
        assert readings.parse(kpi, "$12,400.50") == Decimal("12400.50")


@pytest.mark.django_db
def test_a_week_follows_the_companys_week_start(sc):
    owner = sc["api"].as_(sc["who"]["owner"])
    ff = sc["api"].as_(sc["practice"]["ff"])
    assert patch(ff, f"{B}setup/", {"company": str(sc["company"].pk),
                                    "week_start": "sunday"}).status_code == 200
    sunday = last_week("sunday")
    assert sunday.weekday() == 6
    assert enter(owner, sc, "all", "1", week=sunday).status_code == 200
    assert enter(owner, sc, "all", "1", week=sc["week"]).status_code == 400, "a Monday now"
    form = owner.get(f"{B}entry/?company={sc['company'].pk}&day={sunday}").json()
    assert form["period"]["week_start"] == "sunday"
    assert AuditEvent.all_objects.filter(verb="scorecard.week_start_changed").exists()


# -------------------------------------------------------------------- setup

@pytest.mark.django_db
def test_only_the_practice_owner_and_associates_set_a_scorecard_up(sc):
    api, company = sc["api"], sc["company"]
    body = {"company": str(company.pk), "name": "New KPI", "kind": "count",
            "page": str(sc["pages"]["weekly"].pk)}
    for key in ("ff", "cf"):
        made = post(api.as_(sc["practice"][key]), f"{B}kpis/", {**body, "name": f"By {key}"})
        assert made.status_code == 201, made.content
    refused = post(api.as_(sc["practice"]["va"]), f"{B}kpis/", body)
    assert refused.status_code == 403 and "Assistants don't set up" in refused.json()["detail"]
    for key in ("owner", "leader", "member"):
        refused = post(api.as_(sc["who"][key]), f"{B}kpis/", body)
        assert refused.status_code == 403, key
        assert "sets up the scorecard" in refused.json()["detail"]
        assert "FF" not in refused.json()["detail"]
    owner = api.as_(sc["who"]["owner"])
    assert patch(owner, f"{B}kpis/{sc['kpis']['all'].pk}/", {"name": "Mine"}).status_code == 403
    assert post(owner, f"{B}pages/", {"company": str(company.pk), "name": "x"}).status_code == 403
    assert owner.get(f"{B}setup/?company={company.pk}").status_code == 403


@pytest.mark.django_db
def test_setting_up_is_audited_and_shows_in_activity_in_the_practices_words(sc):
    from apps.tenancy import words

    ff = sc["api"].as_(sc["practice"]["ff"])
    words.save(sc["tenant"], actor=sc["practice"]["ff"].user, data={
        "kpi": {"singular": "metric", "plural": "metrics"},
        "scorecard": {"singular": "dashboard", "plural": "dashboards"}})
    made = post(ff, f"{B}kpis/", {"company": str(sc["company"].pk), "name": "Occupancy",
                                  "kind": "percent", "page": str(sc["pages"]["weekly"].pk)})
    kpi = made.json()["id"]
    assert patch(ff, f"{B}kpis/{kpi}/", {"target_value": "82"}).status_code == 200
    assert post(ff, f"{B}kpis/{kpi}/archive/").status_code == 200
    assert post(ff, f"{B}kpis/{kpi}/restore/").status_code == 200
    verbs = list(AuditEvent.all_objects.filter(verb__startswith="scorecard.kpi_",
                                               payload__name="Occupancy")
                 .values_list("verb", flat=True))
    assert sorted(verbs) == ["scorecard.kpi_archived", "scorecard.kpi_changed",
                             "scorecard.kpi_created", "scorecard.kpi_restored"]
    feed = ff.get("/api/activity/?category=scorecard").json()
    texts = [e["text"] for e in (feed.get("results", feed) if isinstance(feed, dict) else feed)]
    assert "added the metric “Occupancy” to Northwind Foods's dashboard" in texts
    assert "archived the metric “Occupancy” on Northwind Foods's dashboard" in texts


@pytest.mark.django_db
def test_an_archived_kpi_leaves_the_page_and_keeps_its_readings(sc):
    ff = sc["api"].as_(sc["practice"]["ff"])
    calls = sc["kpis"]["calls"]
    assert post(ff, f"{B}kpis/{calls.pk}/archive/").status_code == 200
    _, names = seen(sc, sc["practice"]["ff"])
    assert "Calls" not in names
    assert KpiReading.all_objects.filter(kpi=calls).count() == 4
    assert post(ff, f"{B}kpis/{calls.pk}/restore/").status_code == 200
    _, names = seen(sc, sc["practice"]["ff"])
    assert "Calls" in names


@pytest.mark.django_db
def test_kpis_reorder_on_a_page(sc):
    ff = sc["api"].as_(sc["practice"]["ff"])
    page = sc["pages"]["weekly"]
    ids = [str(k.pk) for k in Kpi.all_objects.filter(page=page, archived_at__isnull=True)
           .order_by("position")]
    assert post(ff, f"{B}kpis/order/", {"page": str(page.pk), "ids": ids[::-1]}).status_code == 200
    assert [t["id"] for t in board(ff, sc["company"], str(page.pk))["kpis"]] == ids[::-1]
    assert post(ff, f"{B}kpis/order/", {"page": str(page.pk), "ids": ids[:1]}).status_code == 400


@pytest.mark.django_db
def test_the_setup_refuses_what_cannot_be(sc):
    ff = sc["api"].as_(sc["practice"]["ff"])
    base = {"company": str(sc["company"].pk), "kind": "count",
            "page": str(sc["pages"]["weekly"].pk)}
    for body, said in (({"name": ""}, "needs a name"),
                       ({"name": "x", "tile": "leaderboard"}, "for per-person KPIs"),
                       ({"name": "x", "audience": "each_person"}, "for per-person KPIs"),
                       ({"name": "x", "direction": "range"}, "needs a low and a high"),
                       ({"name": "x", "direction": "range", "range_low": 5, "range_high": 1},
                        "low end"),
                       ({"name": "x", "kind": "rating", "rating_scale": 7}, "out of 5 or"),
                       ({"name": "x", "per_person": True, "people": [
                           str(MembershipFactory(tenant=sc["tenant"], role="ECC",
                                                 client_company=ClientCompanyFactory(
                                                     tenant=sc["tenant"])).pk)]},
                        "portal user of the company")):
        refused = post(ff, f"{B}kpis/", {**base, **body})
        assert refused.status_code == 400 and said in refused.json()["detail"], body


@pytest.mark.django_db
def test_the_empty_scorecard_offers_the_starter_kpis_one_click_each(seeded_tenant, ff, api):
    company = ClientCompanyFactory(tenant=seeded_tenant, name="Fresh Co")
    client = api.as_(ff)
    empty = client.get(f"{B}?company={company.pk}").json()
    assert empty["exists"] is False and empty["may_set_up"] is True
    state = client.get(f"{B}setup/?company={company.pk}").json()
    names = {g["name"]: [k["name"] for k in g["kpis"]] for g in state["starters"]}
    assert names == {
        "Operations": ["On-time delivery", "Cycle time", "Overtime hours"],
        "Sales": ["New leads", "Proposals sent", "Close rate"],
        "Finance": ["Cash on hand", "Days sales outstanding", "Gross margin"],
        "Service": ["Response time", "Customer rating", "First-contact resolution"]}
    made = post(client, f"{B}starters/", {"company": str(company.pk), "key": "close_rate"})
    assert made.status_code == 201 and made.json()["name"] == "Close rate"
    data = client.get(f"{B}?company={company.pk}").json()
    assert [p["name"] for p in data["pages"]] == ["Weekly scorecard"]
    assert [t["name"] for t in data["kpis"]] == ["Close rate"]
    assert data["kpis"][0]["summary"]["value"] is None, "no readings yet, said, never zero"


# ---------------------------------------------------------------- isolation

@pytest.mark.django_db
def test_tenant_isolation_another_practice_finds_nothing(sc, api):
    other = TenantFactory()
    stranger = MembershipFactory(tenant=other, role="FF")
    client = api.as_(stranger)
    assert client.get(f"{B}?company={sc['company'].pk}").status_code == 404
    assert patch(client, f"{B}kpis/{sc['kpis']['all'].pk}/", {"name": "x"}).status_code == 404
    assert post(client, f"{B}kpis/{sc['kpis']['all'].pk}/archive/").status_code == 404
    reading = KpiReading.all_objects.filter(kpi=sc["kpis"]["calls"]).first()
    assert client.get(f"{B}readings/{reading.pk}/history/").status_code == 404
    page = sc["pages"]["weekly"]
    assert patch(client, f"{B}pages/{page.pk}/", {"name": "x"}).status_code == 404
    saved = post(client, f"{B}readings/", {"company": str(sc["company"].pk), "readings": []})
    assert saved.status_code == 404


@pytest.mark.django_db
def test_a_client_user_reaches_only_their_own_companys_scorecard(sc):
    other_company = ClientCompanyFactory(tenant=sc["tenant"], name="Contoso")
    with tenant_context(sc["tenant"].pk):
        card = setup.ensure(other_company, sc["practice"]["ff"].user)
        setup.create_kpi(card, {"name": "Contoso secret", "kind": "count",
                                "page": str(card.pages.get().pk)}, sc["practice"]["ff"].user)
    owner = sc["api"].as_(sc["who"]["owner"])
    assert owner.get(f"{B}?company={other_company.pk}").status_code == 404
    mine = owner.get(B).json()
    assert mine["company"]["name"] == "Northwind Foods"
    assert "Contoso secret" not in json.dumps(mine)
    contoso_owner = MembershipFactory(tenant=sc["tenant"], role="FCC", client_company=other_company)
    theirs = sc["api"].as_(contoso_owner)
    reading = KpiReading.all_objects.filter(kpi=sc["kpis"]["calls"]).first()
    assert theirs.get(f"{B}readings/{reading.pk}/history/").status_code == 404
    assert "For everyone" not in json.dumps(theirs.get(B).json())


@pytest.mark.django_db
def test_the_portal_entry_shows_only_to_someone_who_sees_a_kpi(sc, seeded_tenant, api):
    assert api.as_(sc["who"]["member"]).get("/api/me").json()["has_scorecard"] is True
    elsewhere = MembershipFactory(tenant=seeded_tenant, role="FCC",
                                  client_company=ClientCompanyFactory(tenant=seeded_tenant))
    assert api.as_(elsewhere).get("/api/me").json()["has_scorecard"] is False
    assert api.as_(sc["practice"]["ff"]).get("/api/me").json()["has_scorecard"] is False


# --------------------------------------------------------------- arithmetic

def test_periods_follow_the_cadence_and_the_week_start():
    wed = date(2026, 10, 21)
    assert P.start_of(wed, P.WEEKLY) == date(2026, 10, 19)
    assert P.start_of(wed, P.WEEKLY, "sunday") == date(2026, 10, 18)
    assert P.start_of(wed, P.MONTHLY) == date(2026, 10, 1)
    assert P.start_of(wed, P.QUARTERLY) == date(2026, 10, 1)
    assert P.start_of(date(2026, 8, 9), P.QUARTERLY) == date(2026, 7, 1)
    assert P.end_of(date(2026, 10, 1), P.QUARTERLY) == date(2026, 12, 31)
    assert P.next_start(date(2026, 12, 1), P.MONTHLY) == date(2027, 1, 1)
    assert P.long_label(date(2026, 10, 12), P.WEEKLY) == "the week of October 12 to 18, 2026"
    assert P.long_label(date(2026, 9, 28), P.WEEKLY) == \
        "the week of September 28 to October 4, 2026"
    win = P.window("this_week", wed)
    assert (win.first, win.last) == (date(2026, 10, 19), date(2026, 10, 25))
    assert P.window("year_to_date", wed).first == date(2026, 1, 1)
    assert P.window("last_year", wed).last == date(2025, 12, 31)
    with pytest.raises(P.WindowInvalid):
        P.window("custom", wed, first=date(2026, 2, 1), last=date(2026, 1, 1))
    assert P.periods_in(P.window("this_month", wed), P.WEEKLY, wed) == [
        date(2026, 9, 28), date(2026, 10, 5), date(2026, 10, 12), date(2026, 10, 19)]


def test_status_bands_are_ten_percent_by_default_and_flip_for_lower_is_better():
    s = P.status
    assert s(Decimal(82), Decimal(82), "higher", 10) == P.ON_TRACK
    assert s(Decimal(74), Decimal(82), "higher", 10) == P.BEHIND      # within 10%
    assert s(Decimal(73), Decimal(82), "higher", 10) == P.OFF_TRACK
    assert s(Decimal(36), Decimal(40), "lower", 10) == P.ON_TRACK
    assert s(Decimal(44), Decimal(40), "lower", 10) == P.BEHIND
    assert s(Decimal(45), Decimal(40), "lower", 10) == P.OFF_TRACK
    assert s(Decimal(60), None, "range", 10, low=Decimal(48), high=Decimal(72)) == P.ON_TRACK
    assert s(Decimal(76), None, "range", 10, low=Decimal(48), high=Decimal(72)) == P.BEHIND
    assert s(Decimal(90), None, "range", 10, low=Decimal(48), high=Decimal(72)) == P.OFF_TRACK
    assert s(Decimal(5), None, "higher", 10) is None, "no target, no status"
    assert s(None, Decimal(5), "higher", 10) is None
    assert P.combine([Decimal(1), Decimal(2), Decimal(6)], "sum") == 9
    assert P.combine([Decimal(1), Decimal(2), Decimal(6)], "average") == 3
    assert P.combine([Decimal(1), Decimal(2), Decimal(6)], "last") == 6


@pytest.mark.django_db
def test_readings_roll_up_over_the_window_against_seasonal_targets(sc):
    """A summed KPI over a month adds its weeks and their targets, each week
    its own month's target; an average averages; Last takes the latest."""
    ff = sc["practice"]["ff"]
    tenant = sc["tenant"]
    first = date(2026, 9, 28)                       # weeks of Sep 28, Oct 5, Oct 12
    with tenant_context(tenant.pk):
        card = Scorecard.objects.get(company=sc["company"])
        made = {}
        for rule in ("sum", "average", "last"):
            made[rule] = setup.create_kpi(card, {
                "name": f"Rolled {rule}", "kind": "count", "cadence": "weekly", "rollup": rule,
                "target_value": 100, "month_targets": {"9": 50, "10": 80},
                "page": str(sc["pages"]["weekly"].pk)}, ff.user)
            for i, value in enumerate((40, 90, 70)):
                KpiReading.objects.create(tenant=tenant, kpi=made[rule],
                                          period_start=first + timedelta(days=7 * i),
                                          value=value, entered_at=timezone.now())
    data = sc["api"].as_(ff).get(
        f"{B}?company={sc['company'].pk}&window=custom&from=2026-09-28&to=2026-10-18").json()
    tiles = {t["name"]: t for t in data["kpis"]}
    s = tiles["Rolled sum"]["summary"]
    assert (s["value"], s["target"], s["status"]) == (200.0, 210.0, "behind")  # 50 + 80 + 80
    s = tiles["Rolled average"]["summary"]
    assert (s["value"], s["target"], s["status"]) == (pytest.approx(66.6667), 70.0, "behind")
    s = tiles["Rolled last"]["summary"]
    assert (s["value"], s["target"], s["status"]) == (70.0, 80.0, "off_track")
    assert [p["target"] for p in tiles["Rolled sum"]["spark"]] == [50.0, 80.0, 80.0]


@pytest.mark.django_db
def test_a_missing_reading_holds_the_last_status_and_is_never_a_zero(sc):
    ff = sc["api"].as_(sc["practice"]["ff"])
    week = sc["week"]
    with tenant_context(sc["tenant"].pk):
        KpiReading.objects.create(tenant=sc["tenant"], kpi=sc["kpis"]["all"],
                                  period_start=week - timedelta(days=7), value=4,
                                  entered_at=timezone.now())
    url = f"{B}?company={sc['company'].pk}&window=custom&from={week}&to={week + timedelta(days=6)}"
    tile = next(t for t in ff.get(url).json()["kpis"] if t["name"] == "For everyone")
    s = tile["summary"]
    assert s["value"] == 4.0 and s["stale"] is True and s["status"] == "off_track"
    assert s["missing"].startswith("No reading for the week of")


# ---------------------------------------------------------------- reminders

@pytest.mark.django_db
def test_the_reading_owner_is_reminded_once_and_the_reading_clears_it(sc):
    today = timezone.localdate()
    owner = sc["who"]["owner"]
    with tenant_context(sc["tenant"].pk):
        Kpi.objects.filter(scorecard__company=sc["company"]).update(
            created_at=timezone.now() - timedelta(days=60))
        first = readings.remind(sc["tenant"], today)
        again = readings.remind(sc["tenant"], today)
    assert first >= 1 and again == 0, "a period is reminded once"
    reminder = KpiReminder.all_objects.get(kpi=sc["kpis"]["all"])
    assert reminder.recipient_id == owner.user_id
    assert reminder.period_start == sc["week"]
    # The manager owns Calls; every tracked row is in, so no reminder.
    assert not KpiReminder.all_objects.filter(kpi=sc["kpis"]["calls"]).exists()
    client = sc["api"].as_(owner)
    notices = client.get(f"{B}notices/").json()
    assert [n["kpi"] for n in notices] == ["For everyone"]
    assert board(client, sc["company"])["notices"][0]["kpi"] == "For everyone"
    assert sc["api"].as_(sc["who"]["member"]).get(f"{B}notices/").json() == []
    assert enter(client, sc, "all", "10").status_code == 200
    assert client.get(f"{B}notices/").json() == []


@pytest.mark.django_db
def test_the_reminder_job_is_scheduled_for_every_practice(seeded_tenant):
    from django.core.management import call_command
    from django_q.models import Schedule

    call_command("ensure_schedules")
    assert Schedule.objects.filter(name__startswith="scorecard.remind_missing:").exists()


# ----------------------------------------- the leaderboard is consent to share

def shared_board(sc, audience="team", **extra):
    with tenant_context(sc["tenant"].pk):
        return setup.create_kpi(Scorecard.objects.get(company=sc["company"]), {
            "name": "Shared calls", "kind": "count", "rollup": "sum", "target_value": 10,
            "per_person": True, "leaderboard": True, "tile": "leaderboard",
            "audience": audience, "page": str(sc["pages"]["weekly"].pk),
            "reading_owner": str(sc["who"]["manager"].user_id),
            "people": [str(sc["who"][k].pk) for k in ("member", "colleague", "manager")],
            **extra}, sc["practice"]["ff"].user)


def with_readings(sc, kpi):
    with tenant_context(sc["tenant"].pk):
        for key, value in (("member", 12), ("colleague", 7), ("manager", 9)):
            KpiReading.objects.create(tenant=sc["tenant"], kpi=kpi, period_start=sc["week"],
                                      membership=sc["who"][key], value=value,
                                      entered_at=timezone.now())


@pytest.mark.django_db
def test_with_the_leaderboard_on_everyone_in_the_audience_sees_the_ranked_list(sc):
    kpi = shared_board(sc, audience="team", audience_team=str(sc["teams"]["ops"].pk))
    with_readings(sc, kpi)
    for key in ("member", "colleague", "ops_viewer", "manager"):
        _, names = seen(sc, sc["who"][key])
        board_ = names["Shared calls"]
        assert board_["shape"] == "leaderboard", key
        assert [(r["name"], r["value"], r["rank"]) for r in board_["rows"]] == [
            ("Mia Member", 12.0, 1), ("Max Manager", 9.0, 2), ("Cole Colleague", 7.0, 3)], key
    for key in ("viewer", "sales_member", "on_no_team"):
        _, names = seen(sc, sc["who"][key])
        assert "Shared calls" not in names, f"{key} is outside the KPI's audience"


@pytest.mark.django_db
def test_the_leaderboard_shares_what_is_shown_and_nothing_more(sc):
    kpi = shared_board(sc, audience="page")
    with_readings(sc, kpi)
    member = sc["api"].as_(sc["who"]["member"])
    form = member.get(f"{B}entry/?company={sc['company'].pk}&day={sc['week']}").json()
    shared = next(k for k in form["kpis"] if k["name"] == "Shared calls")
    assert [f["name"] for f in shared["fields"]] == ["Mia Member"]
    theirs = KpiReading.all_objects.get(kpi=kpi, membership=sc["who"]["colleague"])
    assert member.get(f"{B}readings/{theirs.pk}/history/").status_code == 404
    refused = post(member, f"{B}readings/", {"company": str(sc["company"].pk), "readings": [
        {"kpi": str(kpi.pk), "period_start": str(sc["week"]),
         "membership": str(sc["who"]["colleague"].pk), "value": "1"}]})
    assert refused.status_code == 400


@pytest.mark.django_db
def test_with_the_leaderboard_off_a_member_is_back_to_their_own_row(sc):
    kpi = shared_board(sc, audience="page")
    with_readings(sc, kpi)
    ff = sc["api"].as_(sc["practice"]["ff"])
    assert patch(ff, f"{B}kpis/{kpi.pk}/", {"leaderboard": False}).status_code == 200
    _, names = seen(sc, sc["who"]["member"])
    assert names["Shared calls"]["shape"] == "my_row"
    assert [r["name"] for r in names["Shared calls"]["rows"]] == ["Mia Member"]
    assert "Cole Colleague" not in json.dumps(names["Shared calls"])


@pytest.mark.django_db
def test_under_each_person_sees_their_own_the_board_goes_to_the_tracked_and_their_managers(sc):
    kpi = shared_board(sc, audience="each_person")
    with_readings(sc, kpi)
    _, names = seen(sc, sc["who"]["colleague"])
    assert len(names["Shared calls"]["rows"]) == 3
    for key in ("ops_viewer", "on_no_team", "sales_member", "viewer"):
        _, names = seen(sc, sc["who"][key])
        assert "Shared calls" not in names, key


# ------------------------------------------------------------- computed KPIs

def computed_world(sc, **extra):
    ff = sc["practice"]["ff"]
    with tenant_context(sc["tenant"].pk):
        card = Scorecard.objects.get(company=sc["company"])
        page = str(sc["pages"]["weekly"].pk)
        revenue = setup.create_kpi(card, {"name": "Revenue", "kind": "money", "page": page,
                                          "rollup": "sum"}, ff.user)
        bookings = setup.create_kpi(card, {"name": "Bookings", "kind": "count", "page": page,
                                           "rollup": "sum"}, ff.user)
        first = sc["week"] - timedelta(days=7)
        for week, r, b in ((first, 1000, 4), (sc["week"], 1500, 5)):
            KpiReading.objects.create(tenant=sc["tenant"], kpi=revenue, period_start=week,
                                      value=r, entered_at=timezone.now())
            KpiReading.objects.create(tenant=sc["tenant"], kpi=bookings, period_start=week,
                                      value=b, entered_at=timezone.now())
        per = setup.create_kpi(card, {"name": "Revenue per booking", "kind": "money",
                                      "page": page, "rollup": "average", "formula": "ratio",
                                      "source_a": str(revenue.pk), "source_b": str(bookings.pk),
                                      "target_value": 260, **extra}, ff.user)
    return revenue, bookings, per


@pytest.mark.django_db
def test_a_computed_kpi_is_worked_out_from_its_two_sources_each_period(sc):
    revenue, bookings, per = computed_world(sc)
    first = sc["week"] - timedelta(days=7)
    url = (f"{B}?company={sc['company'].pk}&window=custom&from={first}"
           f"&to={sc['week'] + timedelta(days=6)}")
    tile = next(t for t in sc["api"].as_(sc["practice"]["ff"]).get(url).json()["kpis"]
                if t["name"] == "Revenue per booking")
    assert [p["value"] for p in tile["spark"]] == [250.0, 300.0]
    assert tile["summary"]["value"] == 275.0, "averaged over the window, as its roll-up says"
    assert tile["summary"]["status"] == "on_track"
    assert tile["computed"] == "Revenue ÷ Bookings" and tile["may_enter"] is False
    with tenant_context(sc["tenant"].pk):
        assert setup.describe(per)["formula"] == "ratio"


@pytest.mark.django_db
def test_nobody_enters_a_computed_kpi_and_nobody_is_reminded_about_one(sc):
    _, _, per = computed_world(sc)
    owner = sc["api"].as_(sc["who"]["owner"])
    refused = post(owner, f"{B}readings/", {"company": str(sc["company"].pk), "readings": [
        {"kpi": str(per.pk), "period_start": str(sc["week"]), "value": "1"}]})
    assert refused.status_code == 400
    form = owner.get(f"{B}entry/?company={sc['company'].pk}&day={sc['week']}").json()
    assert "Revenue per booking" not in [k["name"] for k in form["kpis"]]
    with tenant_context(sc["tenant"].pk):
        Kpi.objects.filter(pk=per.pk).update(created_at=timezone.now() - timedelta(days=60))
        readings.remind(sc["tenant"], timezone.localdate())
    assert not KpiReminder.all_objects.filter(kpi=per).exists()


@pytest.mark.django_db
def test_a_computed_kpi_is_hidden_from_anyone_who_cannot_see_both_sources(sc):
    revenue, _, _ = computed_world(sc)
    _, names = seen(sc, sc["who"]["member"])
    assert "Revenue per booking" in names
    with tenant_context(sc["tenant"].pk):
        Kpi.objects.filter(pk=revenue.pk).update(audience="leadership")
    _, names = seen(sc, sc["who"]["member"])
    assert "Revenue" not in names and "Revenue per booking" not in names
    _, names = seen(sc, sc["who"]["leader"])
    assert "Revenue per booking" in names


@pytest.mark.django_db
def test_a_computed_kpi_is_one_step_only_and_keeps_its_sources(sc):
    revenue, bookings, per = computed_world(sc)
    ff = sc["api"].as_(sc["practice"]["ff"])
    base = {"company": str(sc["company"].pk), "name": "x", "kind": "number",
            "page": str(sc["pages"]["weekly"].pk), "formula": "sum"}
    monthly = post(ff, f"{B}kpis/", {**base, "name": "Monthly", "cadence": "monthly",
                                     "kind": "count", "formula": ""}).json()["id"]
    for body, said in (
            ({"source_a": str(per.pk), "source_b": str(revenue.pk)}, "one step only"),
            ({"source_a": str(sc["kpis"]["calls"].pk), "source_b": str(revenue.pk)},
             "per person"),
            ({"source_a": monthly, "source_b": str(revenue.pk)}, "computed KPI's cadence"),
            ({"source_a": str(revenue.pk), "source_b": str(revenue.pk)}, "two different"),
            ({"source_a": str(revenue.pk)}, "Choose two KPIs"),
            ({"source_a": str(revenue.pk), "source_b": str(bookings.pk), "formula": "product"},
             "sum, difference, ratio or average")):
        refused = post(ff, f"{B}kpis/", {**base, **body})
        assert refused.status_code == 400 and said in refused.json()["detail"], body
    archived = post(ff, f"{B}kpis/{revenue.pk}/archive/")
    assert archived.status_code == 400 and "worked out from Revenue" in archived.json()["detail"]
    recadenced = patch(ff, f"{B}kpis/{bookings.pk}/", {"cadence": "monthly"})
    assert recadenced.status_code == 400


# ------------------------------------------- the reminder in the next digest

def digest_world(sc):
    """Mia (a member) owns "For everyone"'s reading, has a contact that is a
    stakeholder of a project, and missed last week."""
    from apps.crm.models import Contact

    from .test_module3_digests import a_task, move, stake

    tenant, member = sc["tenant"], sc["who"]["member"]
    contact = Contact.all_objects.create(tenant=tenant, first_name="Mia", last_name="Member",
                                         company=sc["company"])
    Membership.all_objects.filter(pk=member.pk).update(contact=contact)
    with tenant_context(tenant.pk):
        Kpi.objects.filter(pk=sc["kpis"]["all"].pk).update(
            reading_owner=member.user, created_at=timezone.now() - timedelta(days=60))
        readings.remind(tenant, timezone.localdate())
        task = a_task(tenant, sc["company"], ff=sc["practice"]["ff"], title="Count the cold room")
        stake(tenant, contact, task=task)
        move(task, sc["practice"]["ff"], "in_progress")
    return contact


@pytest.mark.django_db
def test_the_next_digest_carries_the_missing_reading_once(sc):
    from .test_module3_digests import generate_weekly

    digest_world(sc)
    with tenant_context(sc["tenant"].pk):
        made = generate_weekly(sc["tenant"])
    assert len(made) == 1
    digest = made[0]
    line = f"For everyone: no reading yet for {P.long_label(sc['week'], P.WEEKLY)}."
    assert "Waiting on you, for the scorecard" in digest.body_text
    assert line in digest.body_text and line in digest.body_html
    assert KpiReminder.all_objects.get(kpi=sc["kpis"]["all"]).digest_id == digest.pk
    # Not repeated in the next one; given back if this one is skipped.
    from apps.scorecard import digest as scorecard_digest

    assert scorecard_digest.lines_for(sc["tenant"], digest.contact) == []
    with tenant_context(sc["tenant"].pk):
        from apps.work import digests

        digests.skip(digest, actor=sc["practice"]["ff"].user, role="FF")
    assert [t for _, t in scorecard_digest.lines_for(sc["tenant"], digest.contact)] == [line]


@pytest.mark.django_db
def test_the_digest_line_keeps_to_the_audience_and_leaves_once_the_reading_is_in(sc):
    from apps.scorecard import digest as scorecard_digest

    contact = digest_world(sc)
    assert len(scorecard_digest.lines_for(sc["tenant"], contact)) == 1
    with tenant_context(sc["tenant"].pk):
        Kpi.objects.filter(pk=sc["kpis"]["all"].pk).update(audience="leadership")
    assert scorecard_digest.lines_for(sc["tenant"], contact) == [], \
        "a KPI they may no longer see is not named to them"
    with tenant_context(sc["tenant"].pk):
        Kpi.objects.filter(pk=sc["kpis"]["all"].pk).update(audience="page")
        KpiReading.objects.create(tenant=sc["tenant"], kpi=sc["kpis"]["all"],
                                  period_start=sc["week"], value=3, entered_at=timezone.now())
    assert scorecard_digest.lines_for(sc["tenant"], contact) == []


# -------------------------------- after the demo checks (Bryan, 2026-10-22)

def _grid(sc, window, extra=""):
    client = sc["api"].as_(sc["practice"]["ff"])
    url = f"{B}?company={sc['company'].pk}&window={window}{extra}"
    data = client.get(url).json()
    return {t["name"]: t for t in data["kpis"]}, data


@pytest.mark.django_db
def test_the_grid_follows_the_window_as_the_tiles_do(sc):
    """This quarter, year to date and custom dates: the grid's columns are the
    periods inside the window, and the roll-up beside them is the tile's."""
    today = timezone.localdate()
    with tenant_context(sc["tenant"].pk):
        monthly = setup.create_kpi(sc["kpis"]["all"].scorecard, {
            "name": "Monthly revenue", "kind": "money", "cadence": "monthly",
            "rollup": "sum", "target_value": 1000, "page": str(sc["pages"]["weekly"].pk)},
            sc["practice"]["ff"].user)
    win = P.window("this_quarter", today, "monday")
    tiles, data = _grid(sc, "this_quarter")
    weeks = [s.isoformat() for s in P.periods_in(win, P.WEEKLY, today, "monday")]
    months = [s.isoformat() for s in P.periods_in(win, P.MONTHLY, today, "monday")]
    weekly = tiles["For everyone"]
    assert [p["period_start"] for p in weekly["history"]] == weeks[-P.MOST_DRAWN:]
    assert weekly["history_is_window"] is (len(weeks) >= 2)
    drawn = [p["period_start"] for p in tiles[monthly.name]["history"]]
    if len(months) >= 2:
        assert drawn == months
    else:  # The quarter's first month: one period, so the last thirteen up to it.
        assert len(drawn) == P.HISTORY and drawn[-1] <= months[0]
    # Year to date: every month of the year so far, for the monthly KPI.
    tiles, _ = _grid(sc, "year_to_date")
    ytd = P.window("year_to_date", today, "monday")
    expect = [s.isoformat() for s in P.periods_in(ytd, P.MONTHLY, today, "monday")]
    assert [p["period_start"] for p in tiles[monthly.name]["history"]] == expect
    assert tiles[monthly.name]["history_is_window"] is (len(expect) >= 2)
    # Custom dates: their weeks, and the roll-up is the tile's own.
    first = sc["week"] - timedelta(weeks=3)
    tiles, data = _grid(sc, "custom", f"&from={first.isoformat()}&to={sc['week'].isoformat()}")
    calls = tiles["Calls"]
    assert [p["period_start"] for p in calls["history"]] == [
        (first + timedelta(weeks=i)).isoformat() for i in range(4)]
    assert calls["history_is_window"] is True
    assert calls["summary"]["value"] == 43.0, "the window's sum, as the tile shows"


@pytest.mark.django_db
def test_a_window_of_one_period_keeps_the_last_thirteen(sc):
    tiles, _ = _grid(sc, "this_week")
    assert len(tiles["For everyone"]["history"]) == P.HISTORY
    assert tiles["For everyone"]["history_is_window"] is False


@pytest.mark.django_db
def test_the_practice_menu_lists_each_reachable_client_with_its_scorecard(sc, api):
    tenant, ff = sc["tenant"], sc["practice"]["ff"]
    bare = ClientCompanyFactory(tenant=tenant, name="Acme Tools", is_client_company=True)
    ClientCompanyFactory(tenant=tenant, name="A prospect", is_client_company=False)
    ClientCompanyFactory(tenant=TenantFactory(), name="Elsewhere", is_client_company=True)
    rows = api.as_(ff).get(f"{B}companies/").json()
    by = {r["name"]: r for r in rows}
    assert "A prospect" not in by and "Elsewhere" not in by
    assert by["Northwind Foods"]["has_scorecard"] is True and by["Northwind Foods"]["kpis"] == 8
    assert by["Acme Tools"] == {"id": str(bare.pk), "name": "Acme Tools", "kpis": 0,
                                "has_scorecard": False}
    # An associate: the clients assigned to them, and only those.
    assert [r["name"] for r in api.as_(sc["practice"]["cf"]).get(f"{B}companies/").json()] == [
        "Northwind Foods"]
    assert api.as_(sc["practice"]["cf_other"]).get(f"{B}companies/").json() == []
    # Nobody else.
    assert api.as_(sc["practice"]["va"]).get(f"{B}companies/").status_code == 403
    assert api.as_(sc["who"]["owner"]).get(f"{B}companies/").status_code == 403


def test_a_refused_kpi_leaves_nothing_behind_and_save_alone_makes_one(seeded_tenant, ff, api):
    """Bryan, 2026-10-22: nothing is made until Save. A KPI refused on Save
    leaves no scorecard or page behind; one saved without a page chosen
    lands on the first page."""
    from apps.scorecard.models import ScorecardPage

    company = ClientCompanyFactory(tenant=seeded_tenant, name="Brand New Co")
    client = api.as_(ff)
    r = post(client, f"{B}kpis/", {"company": str(company.pk), "name": "", "kind": "count"})
    assert r.status_code == 400
    with tenant_context(seeded_tenant.pk):
        assert not Scorecard.objects.filter(company=company).exists()
        assert not ScorecardPage.objects.filter(scorecard__company=company).exists()
    r = post(client, f"{B}kpis/", {"company": str(company.pk), "name": "Calls", "kind": "count",
                                   "cadence": "weekly", "rollup": "sum"})
    assert r.status_code == 201, r.content
    with tenant_context(seeded_tenant.pk):
        kpi = Kpi.objects.get(scorecard__company=company)
        assert kpi.page.name == setup.FIRST_PAGE


def test_a_percent_ratio_is_a_percentage_everywhere(seeded_tenant, ff, api):
    """Bryan, 2026-10-23: Delivered ÷ Shipped of kind Percent showed 0.93.
    It is 93.4, in the tile, its trend and the window's roll-up, and judged
    against a target typed as 90."""
    company = ClientCompanyFactory(tenant=seeded_tenant, name="Ratio Co")
    with tenant_context(seeded_tenant.pk):
        card = setup.ensure(company, ff.user)
        page = card.pages.get()

        def count(name):
            return setup.create_kpi(card, {"name": name, "kind": "count", "cadence": "weekly",
                                           "rollup": "sum", "page": str(page.pk)}, ff.user)
        shipped, delivered = count("Shipped"), count("Delivered")
        rate = setup.create_kpi(card, {
            "name": "Delivery rate", "kind": "percent", "cadence": "weekly",
            "rollup": "average", "target_value": 90, "formula": "ratio",
            "source_a": str(delivered.pk), "source_b": str(shipped.pk),
            "page": str(page.pk)}, ff.user)
        week = last_week()
        for kpi, value in ((shipped, 500), (delivered, 467)):
            KpiReading.objects.create(tenant=seeded_tenant, kpi=kpi, period_start=week,
                                      value=value, entered_by=ff.user, entered_at=timezone.now())
    data = board(api.as_(ff), company, window="this_month")
    tile = next(t for t in data["kpis"] if t["name"] == "Delivery rate")
    point = next(p for p in tile["history"] if p["period_start"] == week.isoformat())
    assert point["value"] == pytest.approx(93.4)
    assert point["status"] == "on_track"
    if tile["summary"]["value"] is not None:
        assert tile["summary"]["value"] == pytest.approx(93.4)
        assert tile["summary"]["target"] == 90
    # A ratio of another kind stays a plain ratio.
    with tenant_context(seeded_tenant.pk):
        Kpi.objects.filter(pk=rate.pk).update(kind="number", target_value=None)
    tile = next(t for t in board(api.as_(ff), company)["kpis"] if t["name"] == "Delivery rate")
    point = next(p for p in tile["history"] if p["period_start"] == week.isoformat())
    assert point["value"] == pytest.approx(0.934)


def test_the_catch_up_table_starts_from_any_past_period_and_the_pickers_reach_two_years(sc):
    client = sc["api"].as_(sc["practice"]["ff"])
    url = f"{B}bulk/?company={sc['company'].pk}&cadence=weekly&count=6"
    latest = client.get(url).json()
    assert len(latest["periods"]) == 6 and len(latest["choices"]) >= 105
    earliest = date.fromisoformat(latest["earliest"])
    assert (timezone.localdate() - earliest).days >= 2 * 365
    old = sc["week"] - timedelta(weeks=60)
    back = client.get(f"{url}&from={old.isoformat()}").json()
    assert back["periods"][0]["start"] == old.isoformat() and len(back["periods"]) == 6
    assert back["from"] == old.isoformat()
    # Never past the current period, and a daily table takes a date, not a list.
    near = client.get(f"{url}&from={sc['week'].isoformat()}").json()
    assert len(near["periods"]) <= 3
    daily = client.get(f"{B}bulk/?company={sc['company'].pk}&cadence=daily").json()
    assert daily["choices"] == [] and daily["earliest"]
    assert client.get(f"{url}&from=not-a-date").status_code == 400
    form = client.get(f"{B}entry/?company={sc['company'].pk}").json()
    assert len(form["choices"]) >= 105


def test_the_pickers_reach_january_2025_whatever_today_is_and_step_a_table_at_a_time(sc):
    """Bryan, 2026-10-24: any month back to January 2025 can be chosen, for a
    monthly KPI too; the single-period dropdown reaches as far, by month."""
    for today in (date(2026, 10, 24), date(2028, 6, 15)):
        months = readings.reach(today, P.MONTHLY)
        assert months[-1] <= date(2025, 1, 1) and months[0] == today.replace(day=1)
        weeks = readings.reach(today, P.WEEKLY)
        assert weeks[-1] <= date(2025, 1, 1)
        quarters = readings.reach(today, P.QUARTERLY)
        assert quarters[-1] <= date(2025, 1, 1)

    client = sc["api"].as_(sc["practice"]["ff"])
    with tenant_context(sc["tenant"].pk):
        setup.create_kpi(sc["card"], {"name": "Monthly revenue", "kind": "money",
                                      "cadence": "monthly", "page": str(sc["pages"]["weekly"].pk)},
                         sc["practice"]["ff"].user)
    url = f"{B}bulk/?company={sc['company'].pk}&cadence=monthly&count=6"
    latest = client.get(url).json()
    labels = [c["label"] for c in latest["choices"]]
    assert "January 2025" in labels
    assert latest["later"] is None and latest["earlier"]
    january = client.get(f"{url}&from=2025-01-01").json()
    assert [p["label"] for p in january["periods"]][:2] == ["Jan 2025", "Feb 2025"]
    assert any(line["name"] == "Monthly revenue" for line in january["lines"])
    assert january["later"] == "2025-07-01"
    # Earlier from January 2025 stops at the earliest offered, never before it.
    assert january["earlier"] is None or january["earlier"] >= latest["earliest"]
    form = client.get(f"{B}entry/?company={sc['company'].pk}").json()
    assert "January 2025" in {c["month"] for c in form["choices"]}
