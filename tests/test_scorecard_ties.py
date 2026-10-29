"""M5: the scorecard's ties into the rest of the app (spec, "How it ties into
the rest of the app").

- A goal links to a KPI of its own company and shows its latest reading and
  status, to whoever may see that KPI and to nobody else.
- A strategy map row names the KPI its move is meant to move; conversion
  carries it to the goal.
- **The client digest's Scorecard section keeps to the audience rules: a
  member's digest never carries a colleague's row**, a manager's carries
  their team's total, a KPI they may not see is absent.
- "Make a task" makes a task that references the KPI; three periods Off track
  offers it unprompted.
- **What Claude is sent leaves out** every person's name and row, every bonus
  figure, other companies, archived KPIs; the prompts forbid bonus talk; the
  buttons are the practice's and stop at a demo copy's allowance.
"""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from unittest import mock

import pytest
from django.utils import timezone

from apps.scorecard import ai, setup, ties
from apps.scorecard import periods as P
from apps.scorecard.models import Kpi, KpiReading
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Membership
from apps.work.models import Goal

from . import registry_config  # noqa: F401
from .factories import ClientCompanyFactory
from .test_scorecard import board, digest_world, patch, post, sc  # noqa: F401

pytestmark = pytest.mark.django_db

def shows(text: str, number: str) -> bool:
    """`number` as a value in `text`: never as part of a timestamp's
    fraction, an id or a longer number, which are what made a bare substring
    check fail now and then."""
    import re

    return re.search(rf"(?<![\w.-]){re.escape(number)}(?!\w)", text) is not None



def weeks_back(sc, n):
    return P.last_n(sc["week"], P.WEEKLY, n, "monday")


def reading(sc, kpi, start, value, membership=None):
    with tenant_context(sc["tenant"].pk):
        KpiReading.objects.update_or_create(
            kpi=kpi, period_start=start, membership=membership,
            defaults={"tenant": sc["tenant"], "value": value,
                      "entered_by": sc["practice"]["ff"].user, "entered_at": timezone.now()})


def a_goal(sc, **extra):
    with tenant_context(sc["tenant"].pk):
        return Goal.objects.create(tenant=sc["tenant"], title="Grow the cold-chain business",
                                   client_company=sc["company"],
                                   owner=sc["practice"]["ff"].user, **extra)


def contact_for(sc, key):
    from apps.crm.models import Contact

    m = sc["who"][key]
    contact = Contact.all_objects.create(tenant=sc["tenant"], first_name=key.title(),
                                         last_name="Person", company=sc["company"])
    Membership.all_objects.filter(pk=m.pk).update(contact=contact)
    return contact


# ---------------------------------------------------------------- goals

def test_a_goal_links_a_kpi_of_its_own_company_and_shows_its_latest_reading(sc):
    ff = sc["api"].as_(sc["practice"]["ff"])
    goal = a_goal(sc)
    reading(sc, sc["kpis"]["all"], sc["week"], 4)
    saved = patch(ff, f"/api/goals/{goal.pk}/", {"kpi": str(sc["kpis"]["all"].pk)})
    assert saved.status_code == 200, saved.content
    shown = saved.json()["kpi"]
    assert shown["name"] == "For everyone" and shown["value_text"] == "4"
    assert shown["status"] == P.OFF_TRACK and shown["status_label"] == "Off track"
    assert shown["target_text"] == "target 10"
    assert shown["period"] == P.long_label(sc["week"], P.WEEKLY)
    # Another company's KPI is refused in words.
    other = ClientCompanyFactory(tenant=sc["tenant"], name="Elsewhere Co.")
    with tenant_context(sc["tenant"].pk):
        card = setup.ensure(other, sc["practice"]["ff"].user)
        theirs = setup.create_kpi(card, {"name": "Theirs", "kind": "count",
                                         "cadence": "weekly", "page": str(card.pages.get().pk)},
                                  sc["practice"]["ff"].user)
    refused = patch(ff, f"/api/goals/{goal.pk}/", {"kpi": str(theirs.pk)})
    assert refused.status_code == 400 and "isn't on this company's scorecard" in \
        refused.json()["kpi"][0]
    # Unlinked again.
    assert "kpi" not in patch(ff, f"/api/goals/{goal.pk}/", {"kpi": None}).json()


def test_the_portal_shows_a_goals_kpi_only_to_whoever_may_see_it(sc):
    goal = a_goal(sc, kpi=sc["kpis"]["lead"])                   # "Cash", leadership only
    for key, sees in (("owner", True), ("leader", True), ("member", False),
                      ("viewer", False)):
        got = sc["api"].as_(sc["who"][key]).get(f"/api/goals/{goal.pk}/").json()
        if sees:
            assert got["kpi"]["name"] == "Cash" and got["kpi"]["value_text"] == "777,001"
        else:
            assert got["kpi"] is None, key
            assert not shows(json.dumps(got), "777"), key
    # A per-person KPI: a member is shown their own row, said to be theirs.
    Goal.all_objects.filter(pk=goal.pk).update(kpi=sc["kpis"]["calls"])
    mine = sc["api"].as_(sc["who"]["member"]).get(f"/api/goals/{goal.pk}/").json()["kpi"]
    assert mine["value_text"] == "12" and mine["whose"] == "yours"
    team = sc["api"].as_(sc["who"]["manager"]).get(f"/api/goals/{goal.pk}/").json()["kpi"]
    assert team["value_text"] == "28" and team["whose"] == "your team's total"


def test_a_client_cannot_set_a_goals_kpi(sc):
    goal = a_goal(sc)
    refused = patch(sc["api"].as_(sc["who"]["owner"]), f"/api/goals/{goal.pk}/",
                    {"kpi": str(sc["kpis"]["all"].pk)})
    assert refused.status_code == 403
    goal.refresh_from_db()
    assert goal.kpi_id is None


# ---------------------------------------------------------------- the strategy map

def test_a_map_row_names_a_kpi_and_conversion_carries_it(sc):
    from apps.strategy import services as strategy_services
    from apps.strategy.models import StrategyMapRow
    from apps.strategy.seed import seed_tenant as seed_strategy
    from apps.crm.models import Contact

    ff = sc["api"].as_(sc["practice"]["ff"])
    with tenant_context(sc["tenant"].pk):
        template = seed_strategy(sc["tenant"])
        prospect = Contact.objects.create(tenant=sc["tenant"], first_name="Nora",
                                          last_name="West", company=sc["company"])
        session = strategy_services.start(tenant=sc["tenant"], contact=prospect,
                                          template=template, owner=sc["practice"]["ff"].user)
        row = StrategyMapRow.objects.create(
            tenant=sc["tenant"], session=session, bottleneck="Cold room counts are late",
            horizon=30, state=StrategyMapRow.State.ACCEPTED)
    payload = ff.get(f"/api/strategy-sessions/{session.pk}/").json()
    assert {c["name"] for c in payload["kpi_choices"]} >= {"For everyone", "Calls"}
    saved = patch(ff, f"/api/strategy-map-rows/{row.pk}/", {"kpi": str(sc["kpis"]["all"].pk)})
    assert saved.status_code == 200, saved.content
    assert saved.json()["kpi_name"] == "For everyone"
    other = ClientCompanyFactory(tenant=sc["tenant"], name="Elsewhere Co.")
    with tenant_context(sc["tenant"].pk):
        card = setup.ensure(other, sc["practice"]["ff"].user)
        theirs = setup.create_kpi(card, {"name": "Theirs", "kind": "count",
                                         "cadence": "weekly", "page": str(card.pages.get().pk)},
                                  sc["practice"]["ff"].user)
    assert patch(ff, f"/api/strategy-map-rows/{row.pk}/",
                 {"kpi": str(theirs.pk)}).status_code == 400
    made = post(ff, f"/api/strategy-sessions/{session.pk}/convert/",
                {"choices": {str(row.pk): {"as": "goal", "baseline_unknown": True}}})
    assert made.status_code == 201, made.content
    assert Goal.all_objects.get(source_map_row=row).kpi_id == sc["kpis"]["all"].pk


# ---------------------------------------------------------------- the digest

def section(sc, key, **kw):
    return ties.digest_section(sc["tenant"], contact_for(sc, key), **kw)


def test_a_members_digest_carries_their_own_row_and_never_a_colleagues(sc):
    got = section(sc, "member")
    text = json.dumps(got)
    week = P.long_label(sc["week"], P.WEEKLY)
    assert f"Calls (yours), {week}: 12 (target 10). On track." in got["readings"]
    # Cole's 7, Max's 9, Sam's 15, their total, and their names: none of it.
    for leak in ("Cole", "Max", "Sam", ": 7 ", ": 9 ", ": 15 ", ": 28 ", ": 43 "):
        assert leak not in text, leak
    # What they may not see is absent: Cash (leadership), Margin (leaders' page).
    assert "Cash" not in text and not shows(text, "777") and "Margin" not in text
    # A rating per person: their own, under each person sees their own.
    assert any(line.startswith("Rating (yours)") and ": 4 " in line
               for line in got["readings"])
    assert not any("Rating" in line and (": 2 " in line or ": 5 " in line)
                   for line in got["readings"])


def test_a_managers_digest_carries_their_teams_total_and_the_owners_the_whole(sc):
    manager = json.dumps(section(sc, "manager"))
    assert "Calls (your team's total)" in manager and ": 28 (target 30)" in manager
    assert ": 43" not in manager and "Sam" not in manager
    owner = section(sc, "owner")
    assert any(line.startswith("Calls, ") and ": 43 " in line for line in owner["readings"])
    assert any("Cash" in line and "777,001" in line for line in owner["readings"])


def test_status_changes_since_last_time_and_missing_readings(sc):
    two, one = weeks_back(sc, 2)
    reading(sc, sc["kpis"]["all"], two, 2)                      # Off track
    reading(sc, sc["kpis"]["all"], one, 12)                     # On track
    got = section(sc, "owner")
    assert "For everyone moved from Off track to On track." in got["changes"]
    # A closed week with no reading is said, for a KPI they see.
    assert f"Ops only: no reading yet for {P.long_label(sc['week'], P.WEEKLY)}." \
        in got["missing"]
    # Since the last digest: periods closed before it are not reported again.
    later = timezone.now() + timedelta(days=1)
    assert section(sc, "owner", since=later) is None


def test_no_sign_in_no_scorecard_section(sc):
    from apps.crm.models import Contact

    stranger = Contact.all_objects.create(tenant=sc["tenant"], first_name="No",
                                          last_name="Login", company=sc["company"])
    assert ties.digest_section(sc["tenant"], stranger) is None


def test_the_generated_digest_carries_the_section_and_its_audience(sc):
    from .test_module3_digests import generate_weekly

    digest_world(sc)                                            # Mia, the member
    with tenant_context(sc["tenant"].pk):
        [digest] = generate_weekly(sc["tenant"])
    week = P.long_label(sc["week"], P.WEEKLY)
    assert "Scorecard\n  Readings" in digest.body_text
    assert f"Calls (yours), {week}: 12 (target 10). On track." in digest.body_text
    assert "Calls (yours)" in digest.body_html and "Readings" in digest.body_html
    for leak in ("Cole", "777", "Cash", ": 7 ", ": 43 "):
        assert leak not in digest.body_text and leak not in digest.body_html, leak
    # The reminder line is said once, under "Waiting on you", not again as missing.
    reminder = f"For everyone: no reading yet for {week}."
    assert digest.body_text.count(reminder) == 1


# ---------------------------------------------------------------- tasks

def test_make_a_task_references_the_kpi_and_three_off_track_periods_offer_it(sc):
    ff = sc["api"].as_(sc["practice"]["ff"])
    kpi = sc["kpis"]["all"]
    for start in weeks_back(sc, 3):
        reading(sc, kpi, start, 1)                              # three weeks Off track
    tile = next(t for t in board(ff, sc["company"], window="this_week")["kpis"]
                if t["name"] == "For everyone")
    assert tile["off_track_run"] == 3 and tile["offer_task"] and tile["may_make_task"]
    assert tile["task_draft"]["title"] == "For everyone: Off track 3 weeks running"
    made = post(ff, "/api/tasks/", {**tile["task_draft"], "client_company": str(sc["company"].pk),
                                    "kpi": str(kpi.pk)})
    assert made.status_code == 201, made.content
    assert made.json()["kpi"] == str(kpi.pk)
    tile = next(t for t in board(ff, sc["company"], window="this_week")["kpis"]
                if t["name"] == "For everyone")
    assert tile["open_task"]["id"] == made.json()["id"] and not tile["offer_task"]
    # Two weeks Off track is not three.
    reading(sc, kpi, sc["week"], 12)
    tile = next(t for t in board(ff, sc["company"], window="this_week")["kpis"]
                if t["name"] == "For everyone")
    assert tile["off_track_run"] == 0


def test_a_task_names_only_a_kpi_its_maker_sees_on_its_own_company(sc):
    owner = sc["api"].as_(sc["who"]["owner"])
    ok = post(owner, "/api/tasks/", {"title": "Chase the counts", "kpi": str(sc["kpis"]["all"].pk)})
    assert ok.status_code == 201, ok.content
    member = sc["api"].as_(sc["who"]["member"])
    refused = post(member, "/api/tasks/", {"title": "Look at cash",
                                           "kpi": str(sc["kpis"]["lead"].pk)})
    assert refused.status_code in (400, 403) and "777" not in refused.content.decode()
    other = ClientCompanyFactory(tenant=sc["tenant"], name="Elsewhere Co.")
    crossed = post(sc["api"].as_(sc["practice"]["ff"]), "/api/tasks/", {
        "title": "Wrong company", "client_company": str(other.pk),
        "kpi": str(sc["kpis"]["all"].pk)})
    assert crossed.status_code == 400 and "own company" in crossed.content.decode()


def test_a_per_person_kpis_task_carries_no_ones_number(sc):
    member = sc["api"].as_(sc["who"]["member"])
    tile = next(t for t in board(member, sc["company"], window="this_week")["kpis"]
                if t["name"] == "Calls")
    assert "12" not in tile["task_draft"]["description"]


# ---------------------------------------------------------------- Claude

@pytest.fixture
def with_bonus_and_notes(sc):
    """A bonus plan with an amount, a meeting of this company and one of
    another, an archived KPI, and another company's KPI: none but this
    company's meeting may reach Claude."""
    from apps.meetings.models import Meeting
    from apps.scorecard.models import BonusComponent, BonusPerson, BonusPlan

    t, ff = sc["tenant"], sc["practice"]["ff"]
    with tenant_context(t.pk):
        import uuid

        plan = BonusPlan.objects.create(tenant=t, scorecard=sc["card"], name="Q4 bonus",
                                        series=uuid.uuid4(),
                                        period="quarterly",
                                        period_start=P.start_of(sc["week"], P.QUARTERLY),
                                        amount=Decimal("4321.00"))
        BonusComponent.objects.create(tenant=t, plan=plan, kpi=sc["kpis"]["calls"],
                                      weight=100)
        BonusPerson.objects.create(tenant=t, plan=plan, membership=sc["who"]["member"],
                                   amount=Decimal("1234.00"))
        Meeting.objects.create(tenant=t, client_company=sc["company"], title="Weekly L10",
                               meeting_date=timezone.localdate(),
                               summary="Cold room counts slipped because Max was out.")
        other = ClientCompanyFactory(tenant=t, name="Elsewhere Co.")
        Meeting.objects.create(tenant=t, client_company=other, title="Elsewhere sync",
                               meeting_date=timezone.localdate(),
                               summary="Elsewhere's secret expansion plan.")
        card = setup.ensure(other, ff.user)
        setup.create_kpi(card, {"name": "Elsewhere revenue", "kind": "money",
                                "cadence": "weekly", "page": str(card.pages.get().pk)}, ff.user)
        gone = setup.create_kpi(sc["card"], {"name": "Retired KPI", "kind": "count",
                                             "cadence": "weekly",
                                             "page": str(sc["pages"]["weekly"].pk)}, ff.user)
        Kpi.objects.filter(pk=gone.pk).update(archived_at=timezone.now())
    return sc


def sent_for(sc):
    from types import SimpleNamespace

    from apps.scorecard.access import Reader

    with tenant_context(sc["tenant"].pk):
        reader = Reader(SimpleNamespace(membership=sc["practice"]["ff"]), sc["company"])
        return ai.what_is_sent(reader, sc["card"], timezone.localdate())


def test_what_claude_is_sent_leaves_out_people_bonuses_and_everything_else(with_bonus_and_notes):
    sc = with_bonus_and_notes
    sent = sent_for(sc)
    # What it is: this company's KPIs, totals, targets, notes, the last meeting.
    assert "COMPANY: Northwind Foods" in sent and "- For everyone" in sent
    assert "- Calls (Count, weekly, higher is better), the team's total" in sent
    assert ": 43, target 40, On track" in sent                 # the total, never a row
    assert "Cold room counts slipped" in sent
    # What it never is.
    for name in ("Mia", "Cole", "Max Manager", "Sam", "Olive", "Lee Leader"):
        assert name not in sent.replace("Max was out", ""), name
    for figure in (": 12", ": 7,", ": 9,", ": 15,"):            # nobody's own row
        assert figure not in sent, figure
    for bonus in ("4321", "4,321", "1234", "1,234", "Q4 bonus", "bonus"):
        assert bonus.lower() not in sent.lower(), bonus
    assert "Elsewhere" not in sent and "Retired KPI" not in sent


def test_the_prompts_forbid_bonus_talk_and_ask_for_hedged_reasons():
    for purpose in ai.PURPOSES:
        system = ai.SYSTEM[purpose]
        assert "Never mention bonuses, pay, commission" in system
        assert "as a possibility" in system and "Never name or single out" in system


def test_both_buttons_are_the_practices_priced_and_capped(with_bonus_and_notes):
    sc = with_bonus_and_notes
    ff = sc["api"].as_(sc["practice"]["ff"])
    url = f"/api/scorecard/ai/?company={sc['company'].pk}"
    status = ff.get(url).json()
    assert Decimal(status["explain_estimate_usd"]) > 0 and status["cap"] == ai.DAILY_CAP
    for who in (sc["practice"]["va"], sc["who"]["owner"], sc["who"]["member"]):
        assert sc["api"].as_(who).get(url).status_code == 403
        assert post(sc["api"].as_(who), "/api/scorecard/ai/",
                    {"company": str(sc["company"].pk), "purpose": "note"}).status_code == 403

    class Call:
        cost_usd = Decimal("0.02")

    with mock.patch("apps.tenancy.claude.key_source", return_value="tenant"), \
            mock.patch("apps.tenancy.claude.complete_with_call",
                       return_value=("Calls held up; For everyone slipped.", Call())) as called:
        got = post(ff, "/api/scorecard/ai/", {"company": str(sc["company"].pk),
                                              "purpose": "explain"})
    assert got.status_code == 200, got.content
    assert got.json()["text"].startswith("Calls held up")
    kwargs = called.call_args.kwargs
    assert kwargs["purpose"] == ai.EXPLAIN and kwargs["trigger"] == "button"
    assert "4321" not in kwargs["user_text"] and "Never mention bonuses" in kwargs["system"]


def test_a_demo_copy_past_its_allowance_is_refused_before_any_call(with_bonus_and_notes):
    sc = with_bonus_and_notes
    ff = sc["api"].as_(sc["practice"]["ff"])
    stop = "Your demo's AI allowance is used up."
    with mock.patch("apps.tenancy.demo.visitors.ai_stop", return_value=stop), \
            mock.patch("apps.tenancy.claude.complete_with_call") as called:
        assert ff.get(f"/api/scorecard/ai/?company={sc['company'].pk}").json()["refused"] == stop
        refused = post(ff, "/api/scorecard/ai/", {"company": str(sc["company"].pk),
                                                  "purpose": "note"})
    assert refused.status_code == 409 and refused.json()["detail"] == stop
    called.assert_not_called()
