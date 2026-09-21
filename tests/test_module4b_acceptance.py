"""Module 4B — AC-4B.1 to AC-4B.23, with the rulings' sub-items.

The three that carry the most risk, and which the rest lean on:

- **AC-4B.7 / AC-4B.8** — percent-of-tasks-done is never a headline, in the
  portal or in the PDF's own text. It is the thing most likely to creep back in.
- **AC-4B.15 / 15a / 15b** — an unaccepted narrative is *absent* from a client's
  response, one living narrative per goal, and every acceptance appends a
  snapshot an export can cite.
- **AC-4B.14 / 14a** — the draft asserts nothing outside its input, and the
  input now includes what the goal set out to change.
"""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.crm.models import Task
from apps.work import narratives as narrative_service
from apps.work import value_report
from apps.work.models import (
    Goal, GoalMeasurement, GoalMilestone, GoalNarrative, GoalNarrativeVersion,
    GoalReportExport, GoalResolution,
)

from . import registry_config  # noqa: F401
from .factories import (
    ClientCompanyFactory, ContactFactory, GoalFactory, MembershipFactory,
    ProjectFactory, StrategyMapRowFactory,
)

TODAY = timezone.localdate()


# ------------------------------------------------------------------ fixtures

@pytest.fixture
def company(seeded_tenant):
    return ClientCompanyFactory(tenant=seeded_tenant, name="Acme Facilities")


@pytest.fixture
def client_user(seeded_tenant, company):
    return MembershipFactory(tenant=seeded_tenant, role="FCC", client_company=company)


@pytest.fixture
def assigned_cf(seeded_tenant, company):
    from .factories import ClientAssignmentFactory

    membership = MembershipFactory(tenant=seeded_tenant, role="CF")
    ClientAssignmentFactory(tenant=seeded_tenant, user=membership.user,
                            company=company)
    return membership


def a_goal(tenant, company, **kwargs):
    kwargs.setdefault("title", "Decisions stall waiting on the founder")
    kwargs.setdefault("outcome_statement",
                      "The founder stops being the bottleneck on day-to-day calls.")
    return GoalFactory(tenant=tenant, client_company=company, **kwargs)


def a_numeric_goal(tenant, company, **kwargs):
    kwargs.setdefault("measurable_kind", Goal.MeasurableKind.NUMERIC)
    kwargs.setdefault("measurable", "Decisions escalated per week")
    kwargs.setdefault("measurable_unit", "per week")
    kwargs.setdefault("direction", Goal.Direction.DOWN_IS_GOOD)
    kwargs.setdefault("baseline_value", Decimal("14"))
    kwargs.setdefault("baseline_at", TODAY - timedelta(days=60))
    kwargs.setdefault("target_value", Decimal("4"))
    return a_goal(tenant, company, **kwargs)


def reading(goal, value, days_ago, **kwargs):
    return GoalMeasurement.objects.create(
        tenant=goal.tenant, goal=goal, value=Decimal(str(value)),
        measured_at=TODAY - timedelta(days=days_ago), **kwargs)


def a_task(tenant, company, ff, *, goal=None, project=None, title="Publish a decision list",
           visible=True, status=Task.Status.NOT_STARTED):
    from apps.work.services import create_task

    return create_task(tenant=tenant, actor=ff.user, role="FF", title=title,
                       client_company=company, goal=goal, project=project,
                       is_client_visible=visible, status=status)


# ------------------------------------------------------------------- AC-4B.1

@pytest.mark.django_db
def test_ac_4b_1_the_report_is_anchored_on_goals_not_on_a_period(
    seeded_tenant, ff, api, company, in_tenant_a
):
    old = a_numeric_goal(seeded_tenant, company, title="An old goal")
    reading(old, 9, days_ago=200)
    a_goal(seeded_tenant, company, title="A new goal")

    report = api.as_(ff).get(f"/api/value-report/?client_company={company.pk}")
    assert report.status_code == 200
    body = report.json()
    titles = [b["title"] for b in body["current"]]
    assert titles == ["An old goal", "A new goal"]
    # Anchored on goals: no window to choose, and a goal whose only activity is
    # 200 days old is still on the page with its measure and its history.
    assert "since" not in body and "until" not in body and "days" not in body
    measure = body["current"][0]["measure"]
    assert measure["current"]["value"] == "9.0000"
    assert body["current"][0]["is_historical"] is False


@pytest.mark.django_db
def test_ac_4b_2_a_single_goal_opens_on_its_own(seeded_tenant, ff, api, company,
                                                 client_user, in_tenant_a):
    goal = a_numeric_goal(seeded_tenant, company)
    other = a_goal(seeded_tenant, company, title="Somebody else's problem")

    block = api.as_(client_user).get(f"/api/value-report/{goal.pk}/")
    assert block.status_code == 200
    assert block.json()["title"] == goal.title
    assert other.title not in block.content.decode()


# ------------------------------------------------------------------- AC-4B.3

@pytest.mark.django_db
def test_ac_4b_3_internal_goals_never_appear(seeded_tenant, ff, api, company,
                                              in_tenant_a):
    """Ruling 10. Absent from the response, not unrendered — and still on the
    Work screen, because this is a filter on the report, not a permission."""
    internal = GoalFactory(tenant=seeded_tenant, title="Our own hiring",
                           client_company=None)
    a_goal(seeded_tenant, company, title="The client's goal")

    report = api.as_(ff).get(f"/api/value-report/?client_company={company.pk}")
    assert "Our own hiring" not in report.content.decode()
    assert [b["title"] for b in report.json()["current"]] == ["The client's goal"]
    # Not reachable by id either, for any role.
    assert api.as_(ff).get(f"/api/value-report/{internal.pk}/").status_code == 404
    # And untouched on the Work screen.
    assert "Our own hiring" in api.as_(ff).get("/api/goals/").content.decode()


# ------------------------------------------------------------------- AC-4B.4

@pytest.mark.django_db
def test_ac_4b_4_direction_is_stored_never_inferred(seeded_tenant, ff, api, company,
                                                     in_tenant_a):
    """A goal can be to hold a number steady: baseline and target equal, and a
    later reading below both is better only because the goal says so."""
    goal = a_goal(seeded_tenant, company,
                  measurable_kind=Goal.MeasurableKind.NUMERIC,
                  measurable="Overtime hours", direction=Goal.Direction.DOWN_IS_GOOD,
                  baseline_value=Decimal("10"), baseline_at=TODAY - timedelta(days=30),
                  target_value=Decimal("10"))
    reading(goal, 6, days_ago=1)

    assert value_report.measure_block(goal)["movement"] == "better"

    goal.direction = Goal.Direction.UP_IS_GOOD
    goal.save(update_fields=["direction", "updated_at"])
    assert value_report.measure_block(goal)["movement"] == "worse"


@pytest.mark.django_db
def test_a_numeric_goal_will_not_save_without_a_direction(seeded_tenant, ff, api,
                                                           company, in_tenant_a):
    refused = api.as_(ff).post("/api/goals/", json.dumps({
        "title": "Escalations", "client_company": str(company.pk),
        "measurable_kind": "numeric", "measurable": "Escalations per week"}),
        content_type="application/json")
    assert refused.status_code == 400
    assert "up is good" in json.dumps(refused.json())


# ------------------------------------------------------------- AC-4B.5 / 5a

@pytest.mark.django_db
def test_ac_4b_5_the_current_value_is_read_never_stored(seeded_tenant, ff, api,
                                                         company, in_tenant_a):
    goal = a_numeric_goal(seeded_tenant, company)
    reading(goal, 12, days_ago=30)
    middle = reading(goal, 9, days_ago=20)
    reading(goal, 7, days_ago=10)

    assert not any(f.name == "current_value" for f in Goal._meta.get_fields())

    block = api.as_(ff).get(f"/api/value-report/{goal.pk}/").json()
    assert block["measure"]["current"]["value"] == "7.0000"

    api.as_(ff).patch(f"/api/goal-measurements/{middle.pk}/",
                      json.dumps({"value": "11"}), content_type="application/json")
    after = api.as_(ff).get(f"/api/value-report/{goal.pk}/").json()
    assert after["measure"]["current"]["value"] == "7.0000", "the headline is unmoved"
    assert [p["value"] for p in after["measure"]["series"]] == [
        "14.0000", "12.0000", "11.0000", "7.0000"], "the chart moved"


@pytest.mark.django_db
def test_ac_4b_5a_two_readings_on_one_date_are_both_kept(seeded_tenant, ff, api,
                                                          company, in_tenant_a):
    """Ruling C — latest is by recording order, never by value."""
    goal = a_numeric_goal(seeded_tenant, company)
    day = (TODAY - timedelta(days=3)).isoformat()
    for value in ("9", "6"):
        made = api.as_(ff).post("/api/goal-measurements/", json.dumps({
            "goal": str(goal.pk), "value": value, "measured_at": day}),
            content_type="application/json")
        assert made.status_code == 201, made.content

    assert GoalMeasurement.objects.filter(goal=goal).count() == 2
    assert value_report.current_measurement(goal).value == Decimal("6")

    # Record the higher one last: it becomes current, because "latest" is when
    # it was recorded and not which way it points.
    api.as_(ff).post("/api/goal-measurements/", json.dumps({
        "goal": str(goal.pk), "value": "21", "measured_at": day}),
        content_type="application/json")
    assert value_report.current_measurement(goal).value == Decimal("21")


# ------------------------------------------------------------------- AC-4B.6

@pytest.mark.django_db
def test_ac_4b_6_the_chart_appears_at_three_readings_and_the_baseline_is_one(
    seeded_tenant, ff, api, company, in_tenant_a
):
    goal = a_numeric_goal(seeded_tenant, company)          # dated baseline
    reading(goal, 11, days_ago=20)

    measure = api.as_(ff).get(f"/api/value-report/{goal.pk}/").json()["measure"]
    assert measure["reading_count"] == 2 and measure["show_chart"] is False

    # The PDF agrees with the screen, because both read the same decision.
    pdf = api.as_(ff).get(f"/api/value-report/{goal.pk}/pdf/?as=html").content.decode()
    assert "<svg" not in pdf and "14.0000" in pdf and "11.0000" in pdf

    reading(goal, 8, days_ago=10)
    measure = api.as_(ff).get(f"/api/value-report/{goal.pk}/").json()["measure"]
    assert measure["reading_count"] == 3 and measure["show_chart"] is True
    pdf = api.as_(ff).get(f"/api/value-report/{goal.pk}/pdf/?as=html").content.decode()
    assert "<svg" in pdf and pdf.count("<circle") == 3

    # Ruling D's other half: an undated point cannot be placed on an axis.
    goal.baseline_at = None
    goal.save(update_fields=["baseline_at", "updated_at"])
    measure = api.as_(ff).get(f"/api/value-report/{goal.pk}/").json()["measure"]
    assert measure["reading_count"] == 2 and measure["show_chart"] is False


# ------------------------------------------------------------- AC-4B.7 / 4B.8

@pytest.mark.django_db
def test_ac_4b_7_a_numeric_goal_leads_with_its_measure_and_never_with_a_percentage(
    seeded_tenant, ff, api, company, client_user, in_tenant_a
):
    goal = a_numeric_goal(seeded_tenant, company)
    reading(goal, 8, days_ago=5)
    project = ProjectFactory(tenant=seeded_tenant, goal=goal, client_company=company)
    a_task(seeded_tenant, company, ff, project=project, title="One",
           status=Task.Status.DONE)
    a_task(seeded_tenant, company, ff, project=project, title="Two")
    a_task(seeded_tenant, company, ff, project=project, title="Three")

    block = api.as_(client_user).get(f"/api/value-report/{goal.pk}/").json()
    assert block["headline"] == {"kind": "measure",
                                 "text": "Decisions escalated per week"}
    assert block["completion"] == {"done": 1, "of": 3, "percent": 33}

    pdf_text = api.as_(ff).get(
        f"/api/value-report/{goal.pk}/pdf/?as=html").content.decode()
    headline_at = pdf_text.index("Decisions escalated per week")
    percent_at = pdf_text.index("1 of 3")
    assert headline_at < percent_at, "the measure leads; the count is subordinate"
    assert "33%" not in pdf_text.split("Work completed")[0]


@pytest.mark.django_db
@pytest.mark.parametrize("kind,expected_text", [
    ("qualitative", "The founder stops being the bottleneck on day-to-day calls."),
    ("none", "The founder stops being the bottleneck on day-to-day calls."),
    ("", "The founder stops being the bottleneck on day-to-day calls."),
])
def test_ac_4b_8_everything_without_a_number_leads_with_the_outcome_statement(
    kind, expected_text, seeded_tenant, ff, api, company, client_user, in_tenant_a
):
    goal = a_goal(seeded_tenant, company, measurable_kind=kind,
                  how_we_will_know="Nobody waits on the founder to sign off a route.")
    project = ProjectFactory(tenant=seeded_tenant, goal=goal, client_company=company)
    for index in range(5):
        a_task(seeded_tenant, company, ff, project=project, title=f"Task {index}",
               status=Task.Status.DONE if index < 3 else Task.Status.NOT_STARTED)

    block = api.as_(client_user).get(f"/api/value-report/{goal.pk}/").json()
    assert block["headline"] == {"kind": "outcome", "text": expected_text}
    # The bar is present and stays subordinate — it is not promoted into the
    # headline just because the numeric slot is empty.
    assert block["completion"] == {"done": 3, "of": 5, "percent": 60}


# ------------------------------------------------------------ AC-4B.9 / 4B.9a

@pytest.mark.django_db
def test_ac_4b_9_a_goal_created_by_hand_gets_the_measurable_prompt_three_ways(
    seeded_tenant, ff, api, company, in_tenant_a
):
    """Ruling A — `none` is a decision, null is the absence of one."""
    made = api.as_(ff).post("/api/goals/", json.dumps({
        "title": "Culture", "client_company": str(company.pk),
        "measurable_kind": "none"}), content_type="application/json")
    assert made.status_code == 201 and made.json()["measurable_kind"] == "none"

    # Choosing the sentence and leaving it blank still saves: prompting is not
    # blocking (FR-4B.13a).
    qualitative = api.as_(ff).post("/api/goals/", json.dumps({
        "title": "Supervisor overload", "client_company": str(company.pk),
        "measurable_kind": "qualitative"}), content_type="application/json")
    assert qualitative.status_code == 201
    assert qualitative.json()["how_we_will_know"] == ""

    omitted = api.as_(ff).post("/api/goals/", json.dumps({
        "title": "Nobody has looked at this one",
        "client_company": str(company.pk)}), content_type="application/json")
    assert omitted.status_code == 201
    assert omitted.json()["measurable_kind"] is None, "null is not 'none'"
    assert Goal.objects.get(pk=omitted.json()["id"]).measurable_kind == ""


@pytest.mark.django_db
def test_ac_4b_9a_an_undecided_kind_nudges_the_practice_and_only_the_practice(
    seeded_tenant, ff, api, company, client_user, in_tenant_a
):
    undecided = a_goal(seeded_tenant, company, title="Undecided")
    decided = a_goal(seeded_tenant, company, title="Decided", measurable_kind="none")

    staff = api.as_(ff).get(f"/api/value-report/?client_company={company.pk}").json()
    flags = {b["title"]: b["measure"]["kind_is_undecided"] for b in staff["current"]}
    assert flags == {"Undecided": True, "Decided": False}

    client_body = api.as_(client_user).get("/api/value-report/").json()
    for block in client_body["current"]:
        assert block["measure"]["kind_is_undecided"] is False, \
            "the nudge is the practice's, and never reaches a client"

    # And it blocks nothing: the goal renders, converts, and takes a milestone.
    assert api.as_(ff).post("/api/goal-milestones/", json.dumps({
        "goal": str(undecided.pk), "title": "A beat",
        "due_date": TODAY.isoformat()}), content_type="application/json"
    ).status_code == 201


# --------------------------------------------------------- AC-4B.10 / 10a / 11

@pytest.mark.django_db
def test_ac_4b_10_a_resolution_cannot_be_stored_without_its_reason(
    seeded_tenant, ff, api, company, in_tenant_a
):
    from django.db import transaction
    from django.db.utils import IntegrityError

    goal = a_goal(seeded_tenant, company)
    # The database itself refuses it — not the serializer. The savepoint is so
    # the poisoned transaction does not take the rest of the test with it.
    with pytest.raises(IntegrityError), transaction.atomic():
        GoalResolution.objects.create(tenant=seeded_tenant, goal=goal,
                                      resolution="achieved", reason="")

    refused = api.as_(ff).post("/api/goal-resolutions/", json.dumps({
        "goal": str(goal.pk), "resolution": "achieved", "reason": "   "}),
        content_type="application/json")
    assert refused.status_code == 400
    assert "Say why in one line" in json.dumps(refused.json())


@pytest.mark.django_db
def test_ac_4b_10a_the_client_reads_the_resolution_and_its_reason(
    seeded_tenant, ff, api, company, client_user, in_tenant_a
):
    """Ruling G — a reason the client cannot read cannot make "changed course"
    read as judgement rather than as giving up."""
    goal = a_goal(seeded_tenant, company)
    api.as_(ff).post("/api/goal-resolutions/", json.dumps({
        "goal": str(goal.pk), "resolution": "changed_course",
        "reason": "The second branch mattered more than the dispatch rewrite."}),
        content_type="application/json")

    body = api.as_(client_user).get("/api/value-report/").json()
    block = body["historical"][0]
    assert block["resolution"]["resolution"] == "changed_course"
    assert block["resolution"]["reason"] == (
        "The second branch mattered more than the dispatch rewrite.")
    assert not any(f.name == "is_internal" for f in GoalResolution._meta.get_fields())


@pytest.mark.django_db
def test_ac_4b_11_resolutions_append_and_the_first_survives(
    seeded_tenant, ff, api, company, in_tenant_a
):
    goal = a_goal(seeded_tenant, company)
    steps = [("paused", "Their CFO left."), ("resumed", "New CFO started Monday."),
             ("achieved", "Escalations are down and holding."),
             ("changed_course", "It regressed; we are taking another run at it.")]
    for resolution, reason in steps:
        made = api.as_(ff).post("/api/goal-resolutions/", json.dumps({
            "goal": str(goal.pk), "resolution": resolution, "reason": reason}),
            content_type="application/json")
        assert made.status_code == 201, made.content

    rows = api.as_(ff).get(f"/api/goal-resolutions/?goal={goal.pk}").json()
    assert [r["resolution"] for r in rows] == [s[0] for s in reversed(steps)]
    assert [r["reason"] for r in rows] == [s[1] for s in reversed(steps)]

    # No route edits or deletes one.
    # No route edits or deletes one: the viewset has no detail methods at all,
    # so the router never generated a detail URL to reach.
    first = rows[-1]["id"]
    assert api.as_(ff).patch(f"/api/goal-resolutions/{first}/", json.dumps(
        {"reason": "rewritten"}), content_type="application/json"
    ).status_code in (404, 405)
    assert api.as_(ff).delete(
        f"/api/goal-resolutions/{first}/").status_code in (404, 405)


@pytest.mark.django_db
def test_ac_4b_12_current_versus_historical_follows_the_latest_resolution(
    seeded_tenant, ff, api, company, in_tenant_a
):
    goal = a_numeric_goal(seeded_tenant, company)
    reading(goal, 8, days_ago=4)
    GoalMilestone.objects.create(tenant=seeded_tenant, goal=goal, title="Area lead hired",
                                 occurred_at=TODAY - timedelta(days=9))

    def where():
        body = api.as_(ff).get(f"/api/value-report/?client_company={company.pk}").json()
        return ("historical" if any(b["id"] == str(goal.pk) for b in body["historical"])
                else "current")

    api.as_(ff).post("/api/goal-resolutions/", json.dumps({
        "goal": str(goal.pk), "resolution": "paused", "reason": "Their CFO left."}),
        content_type="application/json")
    assert where() == "historical"

    api.as_(ff).post("/api/goal-resolutions/", json.dumps({
        "goal": str(goal.pk), "resolution": "resumed", "reason": "New CFO started."}),
        content_type="application/json")
    assert where() == "current"

    block = api.as_(ff).get(f"/api/value-report/{goal.pk}/").json()
    assert block["measure"]["current"]["value"] == "8.0000"
    assert [m["title"] for m in block["milestones"]] == ["Area lead hired"]
    assert len(block["resolutions"]) == 2


# ---------------------------------------------------------- AC-4B.13 / 4B.13a

@pytest.mark.django_db
def test_ac_4b_13_a_task_marked_as_a_milestone_derives_its_date(
    seeded_tenant, ff, api, company, in_tenant_a
):
    from apps.work.services import apply_task_changes

    goal = a_goal(seeded_tenant, company)
    task = a_task(seeded_tenant, company, ff, goal=goal, title="Area lead hired")
    made = api.as_(ff).post("/api/goal-milestones/", json.dumps({
        "goal": str(goal.pk), "source_task": str(task.pk)}),
        content_type="application/json")
    assert made.status_code == 201
    milestone_id = made.json()["id"]
    assert made.json()["occurred_at"] is None and made.json()["is_derived"] is True

    apply_task_changes(task, actor=ff.user, role="FF",
                       changes={"status": Task.Status.DONE})
    block = api.as_(ff).get(f"/api/value-report/{goal.pk}/").json()
    assert block["milestones"][0]["occurred_at"] == TODAY.isoformat()

    # Un-complete it: the milestone claims nothing, because it never stored it.
    apply_task_changes(task, actor=ff.user, role="FF",
                       changes={"status": Task.Status.IN_PROGRESS})
    block = api.as_(ff).get(f"/api/value-report/{goal.pk}/").json()
    assert block["milestones"][0]["occurred_at"] is None
    assert GoalMilestone.objects.get(pk=milestone_id).occurred_at is None

    refused = api.as_(ff).patch(f"/api/goal-milestones/{milestone_id}/", json.dumps(
        {"title": "Renamed", "occurred_at": TODAY.isoformat()}),
        content_type="application/json")
    assert refused.status_code == 409
    assert "belong to the task" in refused.json()["detail"]


@pytest.mark.django_db
def test_ac_4b_13a_only_a_client_visible_task_in_the_goals_tree_is_eligible(
    seeded_tenant, ff, api, company, client_user, in_tenant_a
):
    """Ruling E, both halves: what may be marked, and what happens after."""
    goal = a_goal(seeded_tenant, company)
    other_goal = a_goal(seeded_tenant, company, title="Another goal")

    hidden = a_task(seeded_tenant, company, ff, goal=goal, title="Fee review",
                    visible=False)
    elsewhere = a_task(seeded_tenant, company, ff, goal=other_goal, title="Not ours")
    eligible = a_task(seeded_tenant, company, ff, goal=goal, title="Area lead hired")

    def mark(task):
        return api.as_(ff).post("/api/goal-milestones/", json.dumps({
            "goal": str(goal.pk), "source_task": str(task.pk)}),
            content_type="application/json")

    refused_hidden = mark(hidden)
    assert refused_hidden.status_code == 400
    assert "hidden from the client" in refused_hidden.json()["detail"]

    refused_elsewhere = mark(elsewhere)
    assert refused_elsewhere.status_code == 400
    assert "not under this goal" in refused_elsewhere.json()["detail"]

    assert mark(eligible).status_code == 201

    # Hide it afterwards: absent from the client's body, still the practice's.
    client_body = api.as_(client_user).get(f"/api/value-report/{goal.pk}/")
    assert "Area lead hired" in client_body.content.decode()

    eligible.is_client_visible = False
    eligible.save(update_fields=["is_client_visible", "updated_at"])
    client_body = api.as_(client_user).get(f"/api/value-report/{goal.pk}/")
    assert "Area lead hired" not in client_body.content.decode()
    assert client_body.json()["milestones"] == []
    staff_body = api.as_(ff).get(f"/api/value-report/{goal.pk}/").json()
    assert [m["title"] for m in staff_body["milestones"]] == ["Area lead hired"]

    eligible.is_client_visible = True
    eligible.save(update_fields=["is_client_visible", "updated_at"])
    assert len(api.as_(client_user).get(
        f"/api/value-report/{goal.pk}/").json()["milestones"]) == 1


# --------------------------------------------------------- AC-4B.14 / 14a / 15

@pytest.mark.django_db
def test_ac_4b_14_the_narrative_asserts_nothing_absent_from_its_input(
    seeded_tenant, ff, api, company, fake_claude, in_tenant_a
):
    from apps.work.services import apply_task_changes

    goal = a_goal(seeded_tenant, company, measurable_kind="qualitative")
    task = a_task(seeded_tenant, company, ff, goal=goal)
    apply_task_changes(task, actor=ff.user, role="FF",
                       changes={"status": Task.Status.IN_PROGRESS},
                       client_facing_line="Two of the four routes now dispatch "
                                          "without a call to you.")

    drafted = api.as_(ff).post(f"/api/value-report/{goal.pk}/draft-narrative/")
    assert drafted.status_code == 200
    sent = fake_claude.requests[-1]
    prompt = json.dumps(sent)
    assert "Two of the four routes now dispatch without a call to you." in prompt
    # With no readings, the model is told it may not claim distance travelled.
    assert "do not describe a trend" in sent["system"]
    assert "Reading on" not in prompt

    reading(goal, 9, days_ago=10)
    reading(goal, 6, days_ago=3)
    api.as_(ff).post(f"/api/value-report/{goal.pk}/draft-narrative/")
    assert "Reading on" in json.dumps(fake_claude.requests[-1])


@pytest.mark.django_db
def test_ac_4b_14a_the_draft_may_say_what_the_goal_set_out_to_change(
    seeded_tenant, ff, api, company, fake_claude, in_tenant_a
):
    """The owner's addition, 2026-09-21: what a goal set out to change is part
    of what the goal is, and a narrative forbidden to refer to it can only
    describe motion."""
    row = StrategyMapRowFactory(
        tenant=seeded_tenant, bottleneck="Decisions stall waiting on Noble",
        root_cause="Nobody else may approve a credit",
        the_fix="Publish an approval ladder to $5k")
    goal = a_goal(seeded_tenant, company, source_map_row=row)
    api.as_(ff).post("/api/goal-resolutions/", json.dumps({
        "goal": str(goal.pk), "resolution": "changed_course",
        "reason": "The second branch mattered more."}),
        content_type="application/json")

    api.as_(ff).post(f"/api/value-report/{goal.pk}/draft-narrative/")
    prompt = json.dumps(fake_claude.requests[-1])
    assert "Decisions stall waiting on Noble" in prompt
    assert "Nobody else may approve a credit" in prompt
    assert "Publish an approval ladder to $5k" in prompt
    assert "The second branch mattered more." in prompt
    assert goal.outcome_statement in prompt

    # And the boundary still binds: things that are not inputs are not sent.
    from apps.notes.models import Note
    from apps.work.services import add_comment

    sibling = a_numeric_goal(seeded_tenant, company, title="Somebody else's measure",
                             measurable="MARKER-SIBLING-MEASURABLE")
    reading(sibling, 3, days_ago=1)
    task = a_task(seeded_tenant, company, ff, goal=goal)
    add_comment(task, author=ff.user, role="FF", body="MARKER-INTERNAL-COMMENT",
                visibility="internal")
    Note.objects.create(tenant=seeded_tenant, title="Locked", body="MARKER-LOCKED-NOTE",
                        task=task, pin_hash="x" * 64, pin_set_at=timezone.now())

    api.as_(ff).post(f"/api/value-report/{goal.pk}/draft-narrative/")
    prompt = json.dumps(fake_claude.requests[-1])
    for marker in ("MARKER-SIBLING-MEASURABLE", "MARKER-INTERNAL-COMMENT",
                   "MARKER-LOCKED-NOTE"):
        assert marker not in prompt, f"{marker} is not this goal's own material"


@pytest.mark.django_db
def test_ac_4b_15_an_unaccepted_narrative_is_invisible_to_the_client(
    seeded_tenant, ff, api, company, client_user, fake_claude, in_tenant_a
):
    goal = a_goal(seeded_tenant, company)
    fake_claude.reply = "MARKER-DRAFT — the routes are moving."
    api.as_(ff).post(f"/api/value-report/{goal.pk}/draft-narrative/")

    client_body = api.as_(client_user).get(f"/api/value-report/{goal.pk}/")
    assert "MARKER-DRAFT" not in client_body.content.decode()
    assert client_body.json()["narrative"] is None

    accepted = api.as_(ff).post(
        f"/api/value-report/{goal.pk}/accept-narrative/",
        json.dumps({"body": "The routes are moving, in my words."}),
        content_type="application/json")
    assert accepted.status_code == 200
    client_body = api.as_(client_user).get(f"/api/value-report/{goal.pk}/").json()
    assert client_body["narrative"] == {"body": "The routes are moving, in my words."}
    assert "MARKER-DRAFT" not in json.dumps(client_body)


@pytest.mark.django_db
def test_ac_4b_15a_one_living_narrative_versioned_on_every_acceptance(
    seeded_tenant, ff, api, company, client_user, fake_claude, in_tenant_a
):
    """Ruling B — what the client reads is replaced; what they were told is not."""
    goal = a_goal(seeded_tenant, company)
    for text in ("First account.", "Second account."):
        api.as_(ff).post(f"/api/value-report/{goal.pk}/draft-narrative/")
        api.as_(ff).post(f"/api/value-report/{goal.pk}/accept-narrative/",
                         json.dumps({"body": text}), content_type="application/json")

    assert GoalNarrative.objects.filter(goal=goal).count() == 1
    versions = api.as_(ff).get(
        f"/api/value-report/{goal.pk}/narrative-versions/").json()
    assert [v["body"] for v in versions] == ["Second account.", "First account."]
    assert all(v["accepted_at"] and v["accepted_by"] for v in versions)

    assert api.as_(client_user).get(
        f"/api/value-report/{goal.pk}/").json()["narrative"]["body"] == "Second account."

    # No route updates or deletes a version, and none is keyed to a period.
    version_id = versions[0]["id"]
    for method in ("patch", "delete"):
        response = getattr(api.as_(ff), method)(
            f"/api/value-report/{goal.pk}/narrative-versions/{version_id}/")
        assert response.status_code in (404, 405)
    assert not any(f.name.startswith("period")
                   for f in GoalNarrativeVersion._meta.get_fields())
    assert not any(f.name.startswith("period") for f in GoalNarrative._meta.get_fields())


@pytest.mark.django_db
def test_ac_4b_15b_an_export_cites_the_version_current_at_export(
    seeded_tenant, ff, api, company, fake_claude, in_tenant_a
):
    goal = a_goal(seeded_tenant, company)
    api.as_(ff).post(f"/api/value-report/{goal.pk}/draft-narrative/")
    api.as_(ff).post(f"/api/value-report/{goal.pk}/accept-narrative/",
                     json.dumps({"body": "What we told them in March."}),
                     content_type="application/json")
    export = api.as_(ff).post("/api/value-report-exports/", json.dumps(
        {"goal": str(goal.pk)}), content_type="application/json")
    assert export.status_code == 201

    api.as_(ff).post(f"/api/value-report/{goal.pk}/accept-narrative/",
                     json.dumps({"body": "What we tell them now."}),
                     content_type="application/json")

    row = GoalReportExport.objects.get(pk=export.json()["id"])
    assert row.narrative_version.body == "What we told them in March."
    pdf = api.as_(ff).get(f"/api/value-report-exports/{row.pk}/file/")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


@pytest.mark.django_db
def test_ac_4b_16_the_structural_half_shows_regardless(
    seeded_tenant, ff, api, company, client_user, fake_claude, in_tenant_a
):
    goal = a_numeric_goal(seeded_tenant, company)
    reading(goal, 9, days_ago=20)
    reading(goal, 6, days_ago=5)
    GoalMilestone.objects.create(tenant=seeded_tenant, goal=goal, title="Ladder published",
                                 occurred_at=TODAY - timedelta(days=15))
    project = ProjectFactory(tenant=seeded_tenant, goal=goal, client_company=company)
    a_task(seeded_tenant, company, ff, project=project, status=Task.Status.DONE)
    api.as_(ff).post(f"/api/value-report/{goal.pk}/draft-narrative/")   # not accepted

    block = api.as_(client_user).get(f"/api/value-report/{goal.pk}/").json()
    assert block["narrative"] is None
    assert block["measure"]["current"]["value"] == "6.0000"
    assert block["measure"]["show_chart"] is True
    assert block["completion"]["of"] == 1
    assert len(block["milestones"]) == 1


# ------------------------------------------------------------ AC-4B.17 / 4B.18

@pytest.mark.django_db
def test_ac_4b_17_a_va_may_measure_and_export_and_may_not_judge(
    seeded_tenant, ff, va, api, company, fake_claude, in_tenant_a
):
    goal = a_numeric_goal(seeded_tenant, company)
    api.as_(ff).post(f"/api/value-report/{goal.pk}/draft-narrative/")

    assert api.as_(va).post("/api/goal-measurements/", json.dumps({
        "goal": str(goal.pk), "value": "9"}),
        content_type="application/json").status_code == 201
    assert api.as_(va).post("/api/value-report-exports/", json.dumps({
        "goal": str(goal.pk)}), content_type="application/json").status_code == 201

    outcome = api.as_(va).patch(f"/api/goals/{goal.pk}/", json.dumps(
        {"outcome_statement": "A VA's sentence."}), content_type="application/json")
    assert outcome.status_code == 400
    assert "the fractional's sentence" in json.dumps(outcome.json())
    goal.refresh_from_db()
    assert goal.outcome_statement != "A VA's sentence."

    resolved = api.as_(va).post("/api/goal-resolutions/", json.dumps({
        "goal": str(goal.pk), "resolution": "achieved", "reason": "Done."}),
        content_type="application/json")
    assert resolved.status_code == 403
    assert "the fractional's call" in resolved.json()["detail"]

    accepted = api.as_(va).post(f"/api/value-report/{goal.pk}/accept-narrative/",
                                json.dumps({"body": "Published by a VA."}),
                                content_type="application/json")
    assert accepted.status_code == 403
    assert GoalNarrativeVersion.objects.count() == 0


@pytest.mark.django_db
def test_ac_4b_17_an_unassigned_cf_gets_404_on_all_of_it(seeded_tenant, ff, cf, api,
                                                          company, in_tenant_a):
    goal = a_numeric_goal(seeded_tenant, company)
    assert api.as_(cf).get(f"/api/value-report/{goal.pk}/").status_code == 404
    assert api.as_(cf).post("/api/goal-measurements/", json.dumps({
        "goal": str(goal.pk), "value": "9"}),
        content_type="application/json").status_code == 404
    assert api.as_(cf).post("/api/goal-resolutions/", json.dumps({
        "goal": str(goal.pk), "resolution": "achieved", "reason": "Done."}),
        content_type="application/json").status_code == 404


@pytest.mark.django_db
def test_an_assigned_cf_may_judge(seeded_tenant, assigned_cf, api, company,
                                  fake_claude, in_tenant_a):
    goal = a_goal(seeded_tenant, company)
    assert api.as_(assigned_cf).post("/api/goal-resolutions/", json.dumps({
        "goal": str(goal.pk), "resolution": "achieved",
        "reason": "Escalations are down and holding."}),
        content_type="application/json").status_code == 201
    assert api.as_(assigned_cf).patch(f"/api/goals/{goal.pk}/", json.dumps(
        {"outcome_statement": "Mine to write."}),
        content_type="application/json").status_code == 200


@pytest.mark.django_db
def test_ac_4b_18_client_company_isolation_both_ways(seeded_tenant, ff, api, company,
                                                      client_user, in_tenant_a):
    other = ClientCompanyFactory(tenant=seeded_tenant, name="Company B")
    b_goal = a_goal(seeded_tenant, other, title="B's goal")
    reading_b = GoalMeasurement.objects.create(
        tenant=seeded_tenant, goal=b_goal, value=Decimal("3"), measured_at=TODAY)
    export_b = api.as_(ff).post("/api/value-report-exports/", json.dumps(
        {"goal": str(b_goal.pk)}), content_type="application/json").json()

    for path in (f"/api/value-report/{b_goal.pk}/",
                 f"/api/goal-resolutions/?goal={b_goal.pk}",
                 f"/api/value-report-exports/{export_b['id']}/file/"):
        assert api.as_(client_user).get(path).status_code in (403, 404), path
    # Writes against another company's rows are 404, never 403: a 403 would
    # confirm the row exists.
    assert api.as_(client_user).patch(
        f"/api/goal-measurements/{reading_b.pk}/", json.dumps({"value": "1"}),
        content_type="application/json").status_code == 404
    assert api.as_(client_user).delete(
        f"/api/goal-measurements/{reading_b.pk}/").status_code == 404

    # A client naming another company still gets their own, never an empty one.
    mine = api.as_(client_user).get(f"/api/value-report/?client_company={other.pk}")
    assert mine.status_code == 200
    assert mine.json()["company"]["id"] == str(company.pk)


# ------------------------------------------------------- AC-4B.19 / 20 / 20a / 21

@pytest.mark.django_db
def test_ac_4b_19_the_pdf_is_a_snapshot_and_every_one_is_kept(
    seeded_tenant, ff, api, company, in_tenant_a
):
    goal = a_numeric_goal(seeded_tenant, company)
    reading(goal, 9, days_ago=20)
    first = api.as_(ff).post("/api/value-report-exports/", json.dumps(
        {"goal": str(goal.pk)}), content_type="application/json").json()
    first_bytes = api.as_(ff).get(
        f"/api/value-report-exports/{first['id']}/file/").content

    reading(goal, 5, days_ago=2)
    goal.outcome_statement = "A different sentence entirely."
    goal.save(update_fields=["outcome_statement", "updated_at"])
    second = api.as_(ff).post("/api/value-report-exports/", json.dumps(
        {"goal": str(goal.pk)}), content_type="application/json").json()

    again = api.as_(ff).get(f"/api/value-report-exports/{first['id']}/file/").content
    assert again == first_bytes, "an export is what it was on the day"
    assert api.as_(ff).get(
        f"/api/value-report-exports/{second['id']}/file/").content != first_bytes

    listed = api.as_(ff).get(
        f"/api/value-report-exports/?client_company={company.pk}").json()
    assert {row["id"] for row in listed} == {first["id"], second["id"]}
    assert all(row["client_company"] == str(company.pk) for row in listed)

    # Ruling F — nothing reaches these rows on a schedule.
    from apps.tenancy.models import StoredFile

    assert StoredFile.objects.filter(purpose="value_report_pdf",
                                     delete_after__isnull=False).count() == 0


@pytest.mark.django_db
def test_ac_4b_20_exporting_is_not_sending(seeded_tenant, ff, api, company,
                                            dev_outbox, in_tenant_a):
    from apps.crm.models import OutboxMessage

    goal = a_goal(seeded_tenant, company)
    api.as_(ff).get(f"/api/value-report/{goal.pk}/pdf/")
    api.as_(ff).post("/api/value-report-exports/", json.dumps(
        {"goal": str(goal.pk)}), content_type="application/json")

    assert OutboxMessage.objects.count() == 0
    assert dev_outbox == []


@pytest.mark.django_db
def test_ac_4b_20a_the_engagement_timeline_spans_the_whole_company(
    seeded_tenant, ff, api, company, client_user, in_tenant_a
):
    from_map = a_goal(seeded_tenant, company, title="Approval ladder")
    from_map.baseline_at = TODAY - timedelta(days=120)
    from_map.baseline_value = Decimal("14")
    from_map.save(update_fields=["baseline_at", "baseline_value", "updated_at"])
    hidden_task = a_task(seeded_tenant, company, ff, goal=from_map,
                         title="MARKER-HIDDEN", visible=False)
    shown_task = a_task(seeded_tenant, company, ff, goal=from_map, title="Ladder drafted")
    GoalMilestone.objects.create(tenant=seeded_tenant, goal=from_map,
                                 title="Ladder published",
                                 occurred_at=TODAY - timedelta(days=60))
    GoalMilestone.objects.create(tenant=seeded_tenant, goal=from_map,
                                 title="Area lead hired",
                                 occurred_at=TODAY - timedelta(days=30))

    measured = a_numeric_goal(seeded_tenant, company, title="Escalations")
    for days, value in ((50, 12), (30, 9), (10, 6)):
        reading(measured, value, days_ago=days)

    resolved = a_goal(seeded_tenant, company, title="Dispatch rewrite")
    api.as_(ff).post("/api/goal-resolutions/", json.dumps({
        "goal": str(resolved.pk), "resolution": "changed_course",
        "reason": "The second branch mattered more."}),
        content_type="application/json")

    internal = GoalFactory(tenant=seeded_tenant, title="MARKER-INTERNAL",
                           client_company=None)

    body = api.as_(client_user).get("/api/value-report/").json()
    timeline = body["timeline"]
    assert {span["title"] for span in timeline["spans"]} == {
        "Approval ladder", "Escalations", "Dispatch rewrite"}
    assert "MARKER-INTERNAL" not in json.dumps(body)
    assert str(internal.pk) not in json.dumps(body)

    kinds = [(m["kind"], m["label"]) for m in timeline["marks"]]
    assert ("milestone", "Ladder published") in kinds
    assert ("milestone", "Area lead hired") in kinds
    assert len([k for k in kinds if k[0] == "reading"]) == 3
    assert ("resolution", "Changed course") in kinds
    resolution_mark = next(m for m in timeline["marks"] if m["kind"] == "resolution")
    assert resolution_mark["detail"] == "The second branch mattered more."

    # In date order, and the resolved goal's span ends where it was resolved.
    assert [m["at"] for m in timeline["marks"]] == sorted(
        m["at"] for m in timeline["marks"])
    span = {s["title"]: s for s in timeline["spans"]}
    assert span["Dispatch rewrite"]["end"] == TODAY.isoformat()   # resolved today
    assert span["Escalations"]["end"] == TODAY.isoformat()
    assert span["Approval ladder"]["start"] == (TODAY - timedelta(days=120)).isoformat()

    # In the all-goals PDF, and absent from a single goal's page.
    all_goals_pdf = api.as_(ff).get(
        f"/api/value-report/pdf/?client_company={company.pk}&as=html").content.decode()
    assert "The engagement, in order" in all_goals_pdf
    assert "Ladder published" in all_goals_pdf
    one_goal_pdf = api.as_(ff).get(
        f"/api/value-report/{from_map.pk}/pdf/?as=html").content.decode()
    assert "The engagement, in order" not in one_goal_pdf
    single = api.as_(client_user).get(f"/api/value-report/{from_map.pk}/").json()
    assert "timeline" not in single

    # A hidden task's milestone is not a mark on the client's timeline.
    api.as_(ff).post("/api/goal-milestones/", json.dumps({
        "goal": str(from_map.pk), "source_task": str(shown_task.pk)}),
        content_type="application/json")
    shown_task.is_client_visible = False
    shown_task.save(update_fields=["is_client_visible", "updated_at"])
    after = api.as_(client_user).get("/api/value-report/").json()
    assert "Ladder drafted" not in json.dumps(after)
    assert "MARKER-HIDDEN" not in json.dumps(after)
    assert hidden_task.title not in json.dumps(after)


@pytest.mark.django_db
def test_ac_4b_21_the_report_requires_a_login(seeded_tenant, ff, api, company,
                                               client_user, client, in_tenant_a):
    from apps.work.models import Stakeholder, StakeholderToken

    a_goal(seeded_tenant, company)
    contact = ContactFactory(tenant=seeded_tenant, company=company)
    goal = Goal.objects.filter(client_company=company).first()
    stakeholder = Stakeholder.objects.create(tenant=seeded_tenant, contact=contact,
                                             goal=goal)
    token = StakeholderToken.issue(stakeholder)[0] if hasattr(
        StakeholderToken, "issue") else None

    path = f"/api/value-report/?client_company={company.pk}"
    assert client.get(path).status_code in (401, 403)
    if token:
        assert client.get(path, HTTP_AUTHORIZATION=f"Bearer {token}"
                          ).status_code in (401, 403)
    assert api.as_(client_user).get("/api/value-report/").status_code == 200


@pytest.mark.django_db
def test_ac_4b_22_every_narrative_draft_is_costed(seeded_tenant, ff, api, company,
                                                   fake_claude, in_tenant_a):
    from apps.tenancy.models import AiCall

    goal = a_goal(seeded_tenant, company)
    api.as_(ff).post(f"/api/value-report/{goal.pk}/draft-narrative/")
    calls = AiCall.objects.filter(purpose="goal_narrative")
    assert calls.count() == 1
    call = calls.first()
    assert call.input_tokens and call.output_tokens and call.cost_usd is not None

    api.as_(ff).post(f"/api/value-report/{goal.pk}/accept-narrative/",
                     json.dumps({"body": "Accepted."}), content_type="application/json")
    api.as_(ff).post("/api/value-report-exports/", json.dumps({"goal": str(goal.pk)}),
                     content_type="application/json")
    api.as_(ff).get(f"/api/value-report/{goal.pk}/")
    assert AiCall.objects.filter(purpose="goal_narrative").count() == 1


@pytest.mark.django_db
def test_ac_4b_23_fr_3_38_is_gone_not_shadowed(seeded_tenant, ff, api, in_tenant_a):
    from django.urls import NoReverseMatch, reverse

    assert api.as_(ff).get("/api/progress-report/").status_code == 404
    with pytest.raises(NoReverseMatch):
        reverse("progress-report-list")
    from apps.work import digests, views

    assert not hasattr(views, "ProgressReportView")
    assert not hasattr(digests, "report_for_company")
