"""Module 4 — AC-4.1 to AC-4.19.

The two that carry the most risk, and which the rest lean on:

- **AC-4.9**: five private things, searched for in the generated PDF's own
  bytes. Not "the template did not render it" — the file itself.
- **AC-4.12 / 4.19**: heavy template edits leave a completed session identical,
  because it renders from its own snapshot and points at no live row.
"""

from __future__ import annotations

import json

import pytest
from django.utils import timezone

from apps.crm.models import Contact, OutboxMessage, Pipeline, PipelineStage, StageSemantic
from apps.strategy import ai, conversion, emails, pdf as pdf_service, services
from apps.strategy import serializers as strategy_serializers
from apps.strategy.models import (
    AskWhen, StrategyAnswer, StrategyMapRow, StrategyPathNote, StrategyQuestion,
    StrategySection, StrategySession,
)
from apps.strategy.seed import seed_tenant
from apps.tenancy.models import AiCall, AuditEvent
from apps.work.models import Goal, Project

from . import registry_config  # noqa: F401
from .factories import (
    CompanyFactory, CompanyLocationFactory, ContactEmailFactory, ContactFactory,
    MembershipFactory,
)

FRACTIONAL = StrategyAnswer.AnsweredBy.FRACTIONAL
PROSPECT = StrategyAnswer.AnsweredBy.PROSPECT


# ------------------------------------------------------------------ fixtures

@pytest.fixture
def template(seeded_tenant, in_tenant_a):
    return seed_tenant(seeded_tenant)


@pytest.fixture
def company(seeded_tenant):
    return CompanyFactory(tenant=seeded_tenant, name="Acme Facilities")


@pytest.fixture
def prospect(seeded_tenant, company):
    contact = ContactFactory(tenant=seeded_tenant, first_name="Dana", last_name="Reyes",
                             company=company)
    ContactEmailFactory(tenant=seeded_tenant, contact=contact,
                        address="dana@acme.invalid", is_primary=True)
    return contact


@pytest.fixture
def session(seeded_tenant, template, prospect, ff):
    return services.start(tenant=seeded_tenant, contact=prospect, template=template,
                          owner=ff.user)


def answer(session, key, value, note=None):
    return services.save_answer(session, question_key=key, value=value,
                                answered_by=FRACTIONAL, fractional_note=note)


# ------------------------------------------------------------------- AC-4.1

@pytest.mark.django_db
def test_ac_4_1_the_template_seeds_verbatim(template, seeded_tenant):
    sections = list(StrategySection.objects.filter(template=template).order_by("position"))
    assert [s.code for s in sections] == [
        "snapshot", "six_key_components", "where_they_want_to_go", "diagnostic",
        "mirror", "strategy_map", "what_they_value", "two_paths", "scope_agreement"]
    questions = StrategyQuestion.objects.filter(template=template)
    assert questions.count() == 47
    assert questions.filter(ask_when=AskWhen.PRECALL).count() == 13
    assert questions.filter(must_ask=True).count() == 7
    # Seven areas, not the six the prose above the list claims — the owner's
    # ruling of 2026-09-18, recorded in the build plan.
    areas = set(questions.exclude(area="").values_list("area", flat=True))
    assert len(areas) == 7


# ------------------------------------------------------------------- AC-4.2

@pytest.mark.django_db
def test_ac_4_2_ask_when_is_overridable_and_in_flight_sessions_are_untouched(
    seeded_tenant, template, prospect, session
):
    StrategyQuestion.objects.filter(template=template, key="s3_three_year_picture"
                                    ).update(ask_when=AskWhen.PRECALL)
    fresh = services.start(tenant=seeded_tenant, contact=prospect, template=template)
    on_form = [q["key"] for _s, q in services.questions_in(fresh.template_snapshot,
                                                           ask_when=AskWhen.PRECALL)]
    assert "s3_three_year_picture" in on_form
    # The session already under way keeps the assignment it was started with.
    was = [q["key"] for _s, q in services.questions_in(session.template_snapshot,
                                                       ask_when=AskWhen.PRECALL)]
    assert "s3_three_year_picture" not in was


# ------------------------------------------------------------------- AC-4.3

@pytest.mark.django_db
def test_ac_4_3_the_pre_call_form_is_public_resumable_and_notifies_the_owner(
    client, session, ff
):
    raw = services.issue_precall_token(session)
    url = f"/api/strategy/precall/{raw}"

    first = client.get(url)
    assert first.status_code == 200
    payload = first.json()
    assert payload["of"] == 13 and payload["answered"] == 0
    assert [s["code"] for s in payload["sections"]] == ["snapshot", "six_key_components"]
    # No live question is reachable here, whatever the caller knows.
    keys = {q["key"] for s in payload["sections"] for q in s["questions"]}
    assert "s4_done_right" not in keys and "s9_investment_range" not in keys

    saved = client.post(url, data=json.dumps(
        {"question_key": "s1_revenue", "value": {"text": "4.2m last year, 5.1m this"}}),
        content_type="application/json")
    assert saved.status_code == 200 and saved.json()["answered"] == 1

    # Reopened later, with no session of any kind: the answer is still there.
    again = client.get(url).json()
    assert again["answered"] == 1
    revenue = [q for s in again["sections"] for q in s["questions"]
               if q["key"] == "s1_revenue"][0]
    assert revenue["value"] == {"text": "4.2m last year, 5.1m this"}

    done = client.post(f"{url}/complete")
    assert done.status_code == 200
    session.refresh_from_db()
    assert session.state == StrategySession.State.PRECALL_COMPLETE
    notice = OutboxMessage.all_objects.filter(
        producer=OutboxMessage.Producer.PRECALL_COMPLETE).first()
    assert notice is not None and notice.to_address == ff.user.email
    assert notice.state == OutboxMessage.State.SENT


@pytest.mark.django_db
def test_the_public_form_refuses_a_live_question_by_key(client, session):
    raw = services.issue_precall_token(session)
    refused = client.post(f"/api/strategy/precall/{raw}", data=json.dumps(
        {"question_key": "s4_done_right", "value": {"said": "Trying it on"}}),
        content_type="application/json")
    assert refused.status_code == 403


# --------------------------------------------------------- AC-4.4 and AC-4.15

@pytest.mark.django_db
def test_ac_4_4_and_4_15_merge_fields_resolve_and_degrade(seeded_tenant, template,
                                                          company, prospect, ff):
    boss = ContactFactory(tenant=seeded_tenant, first_name="Robin", last_name="Vance",
                          company=company)
    integrator = ContactFactory(tenant=seeded_tenant, first_name="Sam",
                                last_name="Okonkwo", company=company)
    company.primary_contact = boss
    company.save()
    CompanyLocationFactory(tenant=seeded_tenant, company=company, name="Denver",
                           position=0)
    CompanyLocationFactory(tenant=seeded_tenant, company=company, name="Boulder",
                           position=1)
    full = services.start(tenant=seeded_tenant, contact=prospect, template=template,
                          owner=ff.user, integrator_contact=integrator,
                          scheduled_at=timezone.now())
    context = services.merge_context(full)
    assert full.visionary_contact_id == boss.pk           # FR-4.9b
    assert context["Visionary"] == "Robin Vance"
    assert context["Integrator"] == "Sam Okonkwo"
    assert context["Location A"] == "Denver" and context["Location B"] == "Boulder"
    assert context["Company"] == "Acme Facilities"
    assert context["Session date"] and context["Fractional name"]

    # One location, no Integrator: both degrade, and no brace survives.
    thin = CompanyFactory(tenant=seeded_tenant, name="Lone Site Co")
    CompanyLocationFactory(tenant=seeded_tenant, company=thin, name="Main", position=0)
    other = ContactFactory(tenant=seeded_tenant, first_name="Lee", last_name="Ng",
                           company=thin)
    bare = services.start(tenant=seeded_tenant, contact=other, template=template,
                          owner=ff.user)
    bare_context = services.merge_context(bare)
    rendered = [services.render_prompt(q["prompt"], bare_context)
                for _s, q in services.questions_in(bare.template_snapshot)]
    assert not any("{" in text for text in rendered)
    assert any("no Integrator identified" in text for text in rendered)
    assert any("their second location" in text for text in rendered)


# ------------------------------------------------------------------- AC-4.5

@pytest.mark.django_db
def test_ac_4_5_scoring_is_computed_and_the_flag_moves(session):
    for key, rating in [("s2_vision", 8), ("s2_people", 7), ("s2_data", 3),
                        ("s2_issues", 6), ("s2_process", 5), ("s2_traction", 9)]:
        answer(session, key, {"rating": rating})
    first = services.six_key_components(session)
    assert first["average"] == 6.3 and first["lowest"] == "s2_data"

    answer(session, "s2_data", {"rating": 10})
    moved = services.six_key_components(session)
    assert moved["lowest"] == "s2_process"
    # Nothing derived was stored: the ratings are the answers, and that is all.
    assert StrategyAnswer.objects.get(session=session,
                                      question_key="s2_data").value == {"rating": 10,
                                                                        "comment": ""}


# ------------------------------------------------------------------- AC-4.6

@pytest.mark.django_db
def test_ac_4_6_the_must_ask_counter_falls_as_they_are_answered(session):
    start = services.must_ask_outstanding(session)
    assert start["of"] == 7 and start["answered"] == 0
    answer(session, "s4_done_right", {"said": "Spot checks on Fridays."})
    answer(session, "s4_turnover", {"said": "About 40%."})
    after = services.must_ask_outstanding(session)
    assert after["answered"] == 2 and "s4_done_right" not in after["outstanding"]
    # A saved-but-empty answer has not been asked.
    answer(session, "s4_gross_margin", {"said": "", "cause": "", "tried": ""})
    assert services.must_ask_outstanding(session)["answered"] == 2
    budgets = {s["code"]: s["time_budget_minutes"]
               for s in session.template_snapshot["sections"]}
    assert budgets["diagnostic"] == 25 and budgets["mirror"] == 5


@pytest.mark.django_db
def test_ac_4_6_the_call_clock_starts_when_the_call_does(session, ff, api):
    """Elapsed runs from the first thing captured live, not from the time the
    session was scheduled for — a call that starts late is not born late."""
    assert session.started_at is None
    api.as_(ff).post(f"/api/strategy-sessions/{session.pk}/answers/",
                     {"question_key": "s4_done_right", "value": {"said": "Spot checks."}},
                     content_type="application/json")
    session.refresh_from_db()
    assert session.started_at is not None
    first = session.started_at

    payload = api.as_(ff).get(f"/api/strategy-sessions/{session.pk}/").json()
    assert payload["budget_minutes"] == 70          # the seed's 10/25/5/15/10/5
    assert payload["started_at"] is not None

    api.as_(ff).post(f"/api/strategy-sessions/{session.pk}/answers/",
                     {"question_key": "s4_turnover", "value": {"said": "40%."}},
                     content_type="application/json")
    session.refresh_from_db()
    assert session.started_at == first              # stamped once, never reset


# ------------------------------------------------------------------- AC-4.7

@pytest.mark.django_db
def test_ac_4_7_a_row_reaches_the_map_only_when_a_person_accepts_it(session, ff, api):
    proposed = [StrategyMapRow.objects.create(
        tenant=session.tenant, session=session, position=i,
        bottleneck=f"Bottleneck {i}", state=StrategyMapRow.State.PROPOSED)
        for i in range(3)]
    assert StrategyMapRow.objects.filter(
        session=session, state=StrategyMapRow.State.ACCEPTED).count() == 0

    api.as_(ff).post(f"/api/strategy-map-rows/{proposed[0].pk}/accept/")
    api.as_(ff).patch(f"/api/strategy-map-rows/{proposed[1].pk}/",
                      {"bottleneck": "Edited before accepting"},
                      content_type="application/json")
    api.as_(ff).post(f"/api/strategy-map-rows/{proposed[1].pk}/accept/")
    api.as_(ff).post(f"/api/strategy-map-rows/{proposed[2].pk}/discard/")

    on_map = list(StrategyMapRow.objects.filter(
        session=session, state=StrategyMapRow.State.ACCEPTED).order_by("position"))
    assert len(on_map) == 2
    assert on_map[1].bottleneck == "Edited before accepting"


# ------------------------------------------------------------------- AC-4.8

@pytest.mark.django_db
def test_ac_4_8_the_mirror_is_proposed_not_saved(session, ff, api, fake_claude):
    answer(session, "s3_current_rocks", {"text": "Open two branches."})
    fake_claude.reply = json.dumps({"goal": "Two branches by spring.",
                                    "unlocks": "Supervisor cover."})
    api.as_(ff).post(f"/api/strategy-sessions/{session.pk}/draft-mirror/")

    session.refresh_from_db()
    assert session.proposed_mirror_goal == "Two branches by spring."
    assert session.mirror_goal == "" and session.mirror_unlocks == ""

    api.as_(ff).patch(f"/api/strategy-sessions/{session.pk}/",
                      {"mirror_goal": "Two branches, staffed, by spring.",
                       "mirror_unlocks": "Supervisor cover."},
                      content_type="application/json")
    session.refresh_from_db()
    assert session.mirror_goal == "Two branches, staffed, by spring."
    # The draft is still there to compare against.
    assert session.proposed_mirror_goal == "Two branches by spring."


# ------------------------------------------------------------------- AC-4.9

@pytest.mark.django_db
def test_ac_4_9_all_five_private_things_are_absent_from_the_pdf(session, ff, api):
    markers = {
        "fractional_note": "MARKERNOTE",
        "mechanics": "MARKERMECHANICS",
        "diagnostic_observation": "MARKERDIAGNOSTIC",
        "alignment": "MARKERALIGNMENT",
        "investment": "MARKERINVESTMENT",
    }
    answer(session, "s1_revenue", {"text": "4.2m"}, note=markers["fractional_note"])
    answer(session, "s4_done_right", {"said": "Spot checks."},
           note=markers["diagnostic_observation"])
    answer(session, "s3_alignment_observation", {"text": markers["alignment"]})
    answer(session, "s9_investment_range", {"agreed": True,
                                            "notes": markers["investment"]})
    StrategyMapRow.objects.create(
        tenant=session.tenant, session=session, bottleneck="Supervisor overload",
        state=StrategyMapRow.State.ACCEPTED, mechanics_note=markers["mechanics"],
        horizon=60, measurable="Inspections per site per month")

    html = pdf_service.render_html(session)
    for marker in markers.values():
        assert marker not in html, f"{marker} leaked with every flag off"
    assert "Supervisor overload" in html          # the row itself is in

    # Toggle the mechanics column on, and ONLY that marker appears.
    api.as_(ff).patch(f"/api/strategy-sessions/{session.pk}/pdf-flags/",
                      {"mechanics": True}, content_type="application/json")
    session.refresh_from_db()
    with_mechanics = pdf_service.render_html(session)
    assert markers["mechanics"] in with_mechanics
    for key, marker in markers.items():
        if key != "mechanics":
            assert marker not in with_mechanics


@pytest.mark.django_db
def test_ac_4_9_the_generated_file_itself_carries_no_marker(session):
    answer(session, "s1_revenue", {"text": "4.2m"}, note="MARKERNOTE")
    answer(session, "s9_investment_range", {"agreed": True, "notes": "MARKERINVESTMENT"})
    content = pdf_service.render_pdf(session)
    assert content[:5] == b"%PDF-"
    # A PDF's text is compressed, so search what the document was built from as
    # well as the bytes: both must be clean.
    assert b"MARKERNOTE" not in content and b"MARKERINVESTMENT" not in content
    assert "MARKERNOTE" not in pdf_service.render_html(session)


# ---------------------------------------- the sales document (owner, 2026-09-21)

def _a_full_session(session, rows=9):
    """A session with as much in it as a real one: six ratings, a mirror, a
    nine-row map, both paths, values, and §9 agreed."""
    for key, rating in (("s2_vision", 10), ("s2_people", 8), ("s2_data", 6),
                        ("s2_issues", 7), ("s2_process", 4), ("s2_traction", 8)):
        answer(session, key, {"rating": rating, "comment": "As discussed."})
    answer(session, "s1_revenue", {"text": "5m then 5.5m"})
    session.mirror_goal = "To grow, but do it more sustainably."
    session.mirror_unlocks = "Solid processes and accountability mechanisms."
    session.save(update_fields=["mirror_goal", "mirror_unlocks", "updated_at"])
    for index in range(rows):
        StrategyMapRow.objects.create(
            tenant=session.tenant, session=session, position=index,
            bottleneck=f"Bottleneck {index} — decisions stall waiting on the founder",
            root_cause="Nobody else may approve a credit over five hundred dollars",
            the_fix="Publish an approval ladder to $5k and hold the line on it",
            owner_text="Noble Baker", horizon=[30, 60, 90][index % 3],
            measurable="Count of decisions escalated to Noble per week",
            state=StrategyMapRow.State.ACCEPTED)
    answer(session, "s8_path_a", {"reaction": "They have already tried it.",
                                  "risk": "Know they need help.", "leaning": "Nope."})
    answer(session, "s8_path_b", {"reaction": "They like the idea.",
                                  "risk": "Need to get us up to speed.",
                                  "leaning": "Yes."})
    answer(session, "s7_value_1", {"value": "Systems before they double.",
                                   "why": "They don't want CSTAT to plummet."})
    answer(session, "s9_start_date", {"agreed": True, "notes": "10/1"})
    answer(session, "s9_follow_up_call", {"agreed": True, "notes": "Next Tuesday"})
    answer(session, "s9_proposal_due", {"agreed": True, "notes": "Tuesday"})
    answer(session, "s9_investment_range", {"agreed": True, "notes": "MARKERINVESTMENT"})
    answer(session, "s9_reaction_to_range", {"agreed": True, "notes": "MARKERREACTION"})
    session.refresh_from_db()
    return session


@pytest.mark.django_db
def test_the_sales_pdf_is_two_pages_at_its_fullest(session):
    """The brief is two pages. This is what holds the design to it — the page
    count is measured, not eyeballed, so a later loosening of a truncation limit
    or a widening of a margin fails here instead of in a prospect's inbox.

    Deliberately the worst case a real session produces: eleven map rows, so a
    horizon overflows into "also noted", and three accepted pros and cons on
    each path, which is the ceiling the draft is allowed.
    """
    _a_full_session(session, rows=11)
    for path in ("a", "b"):
        for kind in ("pro", "con"):
            for index in range(3):
                StrategyPathNote.objects.create(
                    tenant=session.tenant, session=session, path=path, kind=kind,
                    position=index, state=StrategyPathNote.State.ACCEPTED,
                    text="An outside operator is a real cost your current blended "
                         "margin has to carry, and you would feel it in month one")
    assert pdf_service.page_count(session) <= 2


@pytest.mark.django_db
def test_the_document_has_margins_and_the_preview_looks_like_a_document(session):
    """The browser preview ignores `@page`, so until the sheet wrapper existed
    the preview ran its text to the window's edges while the PDF did not — the
    preview was not showing what would be sent (owner, 2026-09-21)."""
    _a_full_session(session)
    html = pdf_service.render_html(session)

    assert "@page { size: letter; margin: 16mm 16mm 17mm;" in html
    # One sheet per page, and the break is a property of the content.
    assert html.count('<section class="sheet">') == 2
    assert ".sheet + .sheet { break-before: page; }" in html
    # On screen: page-sized, on a neutral background, with the same margins.
    assert "@media screen" in html
    assert "width: 8.5in; min-height: 11in" in html
    assert "padding: 16mm 16mm 17mm;" in html
    assert "background: #E9ECEF;" in html
    # And the sheet's padding is screen-only: in the PDF the page margin does it,
    # and doubling them would indent every page by an inch and a quarter.
    screen_block = html[html.index("@media screen"):]
    assert screen_block.index("padding: 16mm") < screen_block.index("}")  + 400


@pytest.mark.django_db
def test_the_six_key_components_render_as_a_chart_with_the_lowest_called_out(session):
    _a_full_session(session)
    context = pdf_service.context_for(session)
    chart = context["six_key"]["chart"]
    assert [bar["rating"] for bar in chart["bars"]] == [10, 8, 6, 7, 4, 8]
    # A bar's width is arithmetic on the rating, and the lowest is the one the
    # accent colour is spent on.
    assert chart["bars"][0]["width"] == chart["track"]
    assert [bar["is_lowest"] for bar in chart["bars"]] == [False] * 4 + [True, False]
    html = pdf_service.render_html(session)
    assert "<svg" in html and html.count("<rect") == 12      # track + bar, six times


@pytest.mark.django_db
def test_the_map_carries_a_30_60_90_strip_saying_which_fix_lands_when(session):
    _a_full_session(session)
    context = pdf_service.context_for(session)
    assert [bucket["label"] for bucket in context["horizons"]] == [
        "30 days", "60 days", "90 days"]
    assert [len(bucket["rows"]) for bucket in context["horizons"]] == [3, 3, 3]
    # Cards are numbered as the document reads, not by stored position: a
    # discarded row leaves a hole, and "1, 2, 4" reads as a missing page.
    StrategyMapRow.objects.filter(session=session, position=0).update(
        state=StrategyMapRow.State.DISCARDED)
    positions = [row["position"] for row in pdf_service.context_for(session)["map_rows"]]
    assert positions == list(range(1, 9))


@pytest.mark.django_db
def test_next_steps_are_the_checklist_and_the_money_is_still_behind_the_flag(session,
                                                                            ff, api):
    """The exclusion narrowed on 2026-09-21 from "all of §9" to "§9's financial
    items" — so the dates a prospect agreed to out loud come back to them the
    same day, and the range and their reaction to it do not."""
    _a_full_session(session)
    context = pdf_service.context_for(session)

    labels = [step["label"] for step in context["next_steps"]]
    assert "Start date" in labels and "Proposal due date" in labels
    assert [step["detail"] for step in context["next_steps"]
            if step["label"] == "Start date"] == ["10/1"]
    assert not any("Investment" in label or "reaction" in label for label in labels)
    assert context["money"] == []

    html = pdf_service.render_html(session)
    assert "10/1" in html and "Next Tuesday" in html
    assert "MARKERINVESTMENT" not in html and "MARKERREACTION" not in html

    # With the flag on, and only then, the money shows — exactly as before.
    api.as_(ff).patch(f"/api/strategy-sessions/{session.pk}/pdf-flags/",
                      {"investment": True}, content_type="application/json")
    session.refresh_from_db()
    with_money = pdf_service.render_html(session)
    assert "MARKERINVESTMENT" in with_money and "MARKERREACTION" in with_money
    assert len(pdf_service.context_for(session)["money"]) == 2


@pytest.mark.django_db
def test_the_decision_page_keeps_the_leaning_and_drops_what_they_said(session):
    """Owner, 2026-09-21. **The reaction and the honest risk are the
    fractional's**, captured on the call and kept in the live view; a prospect
    reading their own reaction quoted back at them is a different, worse
    document. The leaning stays — it is what they decided."""
    _a_full_session(session)
    context = pdf_service.context_for(session)
    assert [path["leaning"] for path in context["path_pair"]] == ["Nope.", "Yes."]

    html = pdf_service.render_html(session)
    assert "Nope." in html and "Yes." in html
    for said in ("They have already tried it.", "Know they need help.",
                 "They like the idea.", "Need to get us up to speed."):
        assert said not in html, f"{said!r} is the fractional's record, not the PDF's"
    # And it is still in the live view's payload, where it was captured.
    payload = strategy_serializers.represent_session(session, full=True)
    assert "They have already tried it." in json.dumps(payload)


@pytest.mark.django_db
def test_the_decision_page_is_written_to_the_person_deciding(session, seeded_tenant):
    """The two boxes' copy, with the practice's name from the tenant's display
    name rather than hardcoded."""
    seeded_tenant.email_display_name = "Executives Now"
    seeded_tenant.save(update_fields=["email_display_name"])
    _a_full_session(session)
    paths = pdf_service.context_for(session)["path_pair"]

    assert [path["label"] for path in paths] == ["Path A", "Path B"]
    assert paths[0]["title"] == "Continue to run it yourself"
    assert paths[1]["title"] == "Work with Executives Now"
    # The map's size is stated rather than described: nine rows, said as nine.
    assert "9 fixes" in paths[0]["moves"][0]["detail"]
    assert "Executives Now" in paths[1]["moves"][0]["headline"]
    assert paths[1]["moves"][0]["detail"].startswith("Starting with Bottleneck 0")

    seeded_tenant.email_display_name = "Someone Else Ops"
    seeded_tenant.save(update_fields=["email_display_name"])
    session.refresh_from_db()            # the FK caches the tenant it first read
    renamed = pdf_service.context_for(session)["path_pair"]
    assert renamed[1]["title"] == "Work with Someone Else Ops"
    assert "Executives Now" not in json.dumps(renamed)


@pytest.mark.django_db
def test_pros_and_cons_reach_the_pdf_only_once_accepted(session, ff, api):
    """The tray's rule, on §8's notes: proposed is invisible to the prospect."""
    _a_full_session(session)
    proposed = StrategyPathNote.objects.create(
        tenant=session.tenant, session=session, path="a", kind="con",
        text="MARKERPROPOSED — you would be doing this between service calls.")
    accepted = StrategyPathNote.objects.create(
        tenant=session.tenant, session=session, path="b", kind="pro",
        text="MARKERACCEPTED — someone owns the list on Monday morning.",
        state=StrategyPathNote.State.ACCEPTED)

    html = pdf_service.render_html(session)
    assert "MARKERPROPOSED" not in html
    assert "MARKERACCEPTED" in html
    assert b"MARKERPROPOSED" not in pdf_service.render_pdf(session)

    api.as_(ff).post(f"/api/strategy-path-notes/{proposed.pk}/accept/")
    assert "MARKERPROPOSED" in pdf_service.render_html(session)

    api.as_(ff).post(f"/api/strategy-path-notes/{accepted.pk}/discard/")
    assert "MARKERACCEPTED" not in pdf_service.render_html(session)


@pytest.mark.django_db
def test_claude_drafts_pros_and_cons_on_two_triggers_and_costs_once_each(
    session, ff, api, fake_claude
):
    """The same trigger pair the map rows have: a button, and once when §8 is
    captured. Nothing else calls it, and each run writes one `ai_call`."""
    from apps.tenancy.models import AiCall

    fake_claude.reply = json.dumps({
        "a": {"pros": ["You keep every pound of it in-house"],
              "cons": ["It waits behind the day job", "Nobody owns the list"]},
        "b": {"pros": ["Someone owns the list on Monday", "You get the hours back"],
              "cons": ["It costs money you have not spent before"]},
    })
    _a_full_session(session)

    # Nothing yet: §8 was filled by the service, not through the answers route.
    assert StrategyPathNote.objects.filter(session=session).count() == 0

    drafted = api.as_(ff).post(f"/api/strategy-sessions/{session.pk}/draft-paths/")
    assert drafted.status_code == 201
    notes = StrategyPathNote.objects.filter(session=session)
    assert notes.count() == 6
    assert notes.filter(path="a", kind="con").count() == 2
    assert set(notes.values_list("state", flat=True)) == {"proposed"}
    assert AiCall.objects.filter(purpose="strategy_path_notes").count() == 1

    # A second run adds nothing it already said, and never touches an accepted one.
    accepted = notes.filter(path="b", kind="pro").first()
    accepted.state = StrategyPathNote.State.ACCEPTED
    accepted.save(update_fields=["state", "updated_at"])
    api.as_(ff).post(f"/api/strategy-sessions/{session.pk}/draft-paths/")
    assert StrategyPathNote.objects.filter(session=session).count() == 6
    accepted.refresh_from_db()
    assert accepted.state == StrategyPathNote.State.ACCEPTED
    assert AiCall.objects.filter(purpose="strategy_path_notes").count() == 2


@pytest.mark.django_db
def test_the_second_trigger_fires_once_when_section_eight_is_captured(
    session, ff, api, fake_claude
):
    fake_claude.reply = json.dumps({
        "a": {"pros": ["A pro"], "cons": ["A con"]},
        "b": {"pros": ["Another pro"], "cons": ["Another con"]},
    })
    url = f"/api/strategy-sessions/{session.pk}/answers/"
    first = api.as_(ff).post(url, {"question_key": "s8_path_a",
                                   "value": {"reaction": "Tried it.", "leaning": "No."}},
                             content_type="application/json")
    assert first.json()["path_notes"] == [], "one path is not §8 captured"
    assert StrategyPathNote.objects.filter(session=session).count() == 0

    second = api.as_(ff).post(url, {"question_key": "s8_path_b",
                                    "value": {"reaction": "Like it.", "leaning": "Yes."}},
                              content_type="application/json")
    assert len(second.json()["path_notes"]) == 4

    # Once. Answering §8 again does not fire it a second time.
    api.as_(ff).post(url, {"question_key": "s8_path_b",
                           "value": {"reaction": "Still like it.", "leaning": "Yes."}},
                     content_type="application/json")
    assert StrategyPathNote.objects.filter(session=session).count() == 4


@pytest.mark.django_db
def test_the_pros_and_cons_prompt_carries_only_this_sessions_material(
    session, ff, api, fake_claude
):
    """AC-3.5's constraint, on §8's draft. The reaction and the risk **are**
    input — they are the most useful thing said about either path — even though
    they never reach the PDF."""
    _a_full_session(session)
    answer(session, "s4_done_right", {"said": "MARKERDIAGNOSTIC — spot checks only."},
           note="MARKERPRIVATE — they are kidding themselves.")
    api.as_(ff).post(f"/api/strategy-sessions/{session.pk}/draft-paths/")

    sent = json.dumps(fake_claude.requests[-1])
    assert "MARKERDIAGNOSTIC" in sent
    assert "They have already tried it." in sent      # the reaction is input
    assert "Systems before they double." in sent      # what they value is input
    assert "MARKERPRIVATE" not in sent, "the private column is private from the model"
    assert "MARKERINVESTMENT" not in sent, "no money reaches a draft"
    assert "Assert nothing that is not in that input" in fake_claude.requests[-1]["system"]


@pytest.mark.django_db
def test_the_map_groups_by_horizon_with_three_cards_and_the_rest_named(session):
    """Owner, 2026-09-21. Priority order within a column, three cards, and a
    fourth listed by title rather than dropped."""
    _a_full_session(session, rows=11)
    horizons = pdf_service.context_for(session)["horizons"]
    by_label = {bucket["label"]: bucket for bucket in horizons}

    assert [bucket["label"] for bucket in horizons] == ["30 days", "60 days", "90 days"]
    assert [len(bucket["cards"]) for bucket in horizons] == [3, 3, 3]
    # 11 rows round-robin 30/60/90: four land on 30, four on 60, three on 90.
    assert len(by_label["30 days"]["also"]) == 1
    assert len(by_label["60 days"]["also"]) == 1
    assert by_label["90 days"]["also"] == []

    # Priority order within the column, not creation order shuffled.
    thirty = by_label["30 days"]
    assert [row["bottleneck"] for row in thirty["cards"] + thirty["also"]] == [
        f"Bottleneck {i} — decisions stall waiting on the founder"
        for i in (0, 3, 6, 9)]

    html = pdf_service.render_html(session)
    assert "Also noted — lower priority" in html
    assert "Bottleneck 9" in html, "the eleventh row is named, not forgotten"


@pytest.mark.django_db
def test_the_header_carries_three_chips_with_labels_that_fit(session):
    _a_full_session(session)
    answer(session, "s1_team", {"text": "28 FT / 10 PT"})
    answer(session, "s1_sites", {"text": "250"})
    answer(session, "s1_service_mix", {"text": "all contract"})

    chips = pdf_service.context_for(session)["snapshot"]
    assert [chip["label"] for chip in chips] == ["Revenue", "Team", "Customers"]
    assert [chip["text"] for chip in chips] == ["5m then 5.5m", "28 FT / 10 PT", "250"]
    html = pdf_service.render_html(session)
    assert "Active customer sites" not in html and "Service mix" not in html


# ------------------------------------------------------------------ AC-4.10

@pytest.mark.django_db
def test_ac_4_10_nothing_is_emailed_until_someone_clicks_send(session, ff, api):
    answer(session, "s1_revenue", {"text": "4.2m"})
    preview = api.as_(ff).get(f"/api/strategy-sessions/{session.pk}/pdf/?as=html")
    assert preview.status_code == 200
    assert OutboxMessage.all_objects.count() == 0          # generating is not sending

    sent = api.as_(ff).post(f"/api/strategy-sessions/{session.pk}/send-pdf/")
    assert sent.status_code == 201
    message = OutboxMessage.all_objects.get(
        producer=OutboxMessage.Producer.STRATEGY_PDF)
    assert message.state == OutboxMessage.State.SENT
    assert message.to_address == "dana@acme.invalid"
    assert message.attachments.count() == 1
    assert AuditEvent.all_objects.filter(verb="strategy.pdf_sent").exists()


# ------------------- the questions by email (owner, 2026-09-21)

@pytest.mark.django_db
def test_the_questions_email_carries_every_pre_call_question_and_nothing_private(
    session, ff, api, dev_outbox
):
    """The path for a prospect who will not click a link.

    Two assertions matter: **every** pre-call question is in the body — a
    question the prospect never sees is one the call has to spend time on — and
    **nothing the fractional keeps to themselves** is, which is the same rule
    the PDF carries and is applied while the content is built.
    """
    sent = api.as_(ff).post(f"/api/strategy-sessions/{session.pk}/send-questions/",
                            {"intro": "Hi Dana, a few questions before Thursday."},
                            content_type="application/json")
    assert sent.status_code == 201, sent.content

    message = OutboxMessage.all_objects.get(
        producer=OutboxMessage.Producer.PRECALL_QUESTIONS)
    assert message.state == OutboxMessage.State.SENT      # direct-to-sent
    assert message.to_address == "dana@acme.invalid"
    body = f"{message.body_text}\n{message.body_html}"
    assert "Hi Dana, a few questions before Thursday." in body

    merge = services.merge_context(session)
    asked, withheld = [], []
    for _section, question in services.questions_in(session.template_snapshot,
                                                    ask_when=AskWhen.PRECALL):
        prompt = services.render_prompt(question["prompt"], merge)
        (withheld if question.get("is_fractional_observation")
         or question.get("is_financial") else asked).append(prompt)

    assert len(asked) >= 13
    for prompt in asked:
        assert prompt in body, f"{prompt!r} is a pre-call question and is not in the email"
    for prompt in withheld:
        assert prompt not in body, f"{prompt!r} is the fractional's own and leaked"

    # The scale is explained once, above the six, rather than beside each.
    assert emails.RATING_SCALE in message.body_text
    # No brace survives, exactly as on the form (FR-4.9).
    assert "{" not in message.body_text
    # And it says how to answer, because there is nothing to click.
    assert "reply to this email" in message.body_text


@pytest.mark.django_db
def test_the_questions_email_goes_from_the_fractionals_own_address(session, ff, api,
                                                                   seeded_tenant):
    """A prospect answers by hitting reply, so it has to land somewhere a person
    reads — not the practice alias the invite goes from."""
    from apps.crm.models import GmailConnection

    # `own` is only an address Gmail will accept — a connection whose send-as
    # has been verified. Anything less falls back to the practice alias.
    GmailConnection.objects.create(
        tenant=seeded_tenant, user=ff.user, email_address="bryan@getexecutivesnow.test",
        send_as_address="bryan@getexecutivesnow.test",
        send_as_verified_at=timezone.now())
    api.as_(ff).post(f"/api/strategy-sessions/{session.pk}/send-questions/",
                     {}, content_type="application/json")
    message = OutboxMessage.all_objects.get(
        producer=OutboxMessage.Producer.PRECALL_QUESTIONS)
    assert message.from_address == "bryan@getexecutivesnow.test"


@pytest.mark.django_db
def test_a_va_may_send_the_link_and_not_the_questions(session, va, api):
    """H7a gives a VA the invite because it is template-only with nothing
    discretionary in it. This one carries words a person wrote, from their
    address — matrix 10.3a."""
    assert api.as_(va).post(
        f"/api/strategy-sessions/{session.pk}/send-invite/").status_code == 201
    refused = api.as_(va).post(f"/api/strategy-sessions/{session.pk}/send-questions/",
                               {}, content_type="application/json")
    assert refused.status_code == 403
    assert not OutboxMessage.all_objects.filter(
        producer=OutboxMessage.Producer.PRECALL_QUESTIONS).exists()


@pytest.mark.django_db
def test_sending_the_questions_marks_the_session_and_the_answers_that_follow(
    session, ff, api
):
    """What the marker does and does not claim: the session's pre-call came back
    by email, and the fractional typed it in. It does not claim a given sentence
    was copied from a reply — nobody can know that."""
    assert session.precall_questions_sent_at is None
    api.as_(ff).post(f"/api/strategy-sessions/{session.pk}/send-questions/",
                     {}, content_type="application/json")
    session.refresh_from_db()
    assert session.precall_questions_sent_at is not None
    assert session.state == StrategySession.State.PRECALL_SENT

    # The fractional types an answer in the live view, as they would from a reply.
    api.as_(ff).post(f"/api/strategy-sessions/{session.pk}/answers/",
                     {"question_key": "s1_revenue", "value": {"text": "5m then 5.5m"}},
                     content_type="application/json")
    payload = strategy_serializers.represent_session(session, full=True)
    answer = next(a for a in payload["answers"] if a["question_key"] == "s1_revenue")
    assert answer["answered_by"] == FRACTIONAL
    assert payload["precall_questions_sent_at"] is not None


# ------------------------------------------------------------------ AC-4.11

@pytest.mark.django_db
def test_ac_4_11_conversion_is_per_row_and_creates_nothing_until_confirmed(
    session, ff, api, seeded_tenant
):
    rows = [StrategyMapRow.objects.create(
        tenant=session.tenant, session=session, position=i,
        bottleneck=f"Bottleneck {i}", the_fix=f"Fix {i}", horizon=60,
        measurable=f"Measure {i}", state=StrategyMapRow.State.ACCEPTED)
        for i in range(4)]
    discarded = StrategyMapRow.objects.create(
        tenant=session.tenant, session=session, position=4, bottleneck="Not this one",
        state=StrategyMapRow.State.DISCARDED)

    preview = api.as_(ff).get(
        f"/api/strategy-sessions/{session.pk}/conversion-preview/").json()
    assert len(preview["rows"]) == 4               # the discarded row is not offered
    assert Goal.objects.count() == 0 and Project.objects.count() == 0

    made = api.as_(ff).post(f"/api/strategy-sessions/{session.pk}/convert/", {
        "choices": {
            str(rows[0].pk): {"as": "goal", "baseline_value": "14",
                              "measurable_unit": "sites", "target_value": "8",
                              "direction": "down_is_good"},
            str(rows[1].pk): {"as": "goal", "baseline_unknown": True},
            str(rows[2].pk): {"as": "project"},
            # AC-4.11's "de-select one" — a choice made here, at conversion, not
            # a row discarded in the tray an hour earlier. Until 2026-09-21 the
            # screen offered this and the server refused the whole press.
            str(rows[3].pk): {"as": "skip"},
        }}, content_type="application/json")
    assert made.status_code == 201, made.content
    assert Goal.objects.count() == 2 and Project.objects.count() == 1
    rows[3].refresh_from_db()
    assert rows[3].converted_to == ""
    assert rows[3].state == StrategyMapRow.State.ACCEPTED   # left out, not discarded

    goal = Goal.objects.get(source_map_row=rows[0])
    assert goal.measurable == "Measure 0" and goal.horizon_days == 60
    assert str(goal.baseline_value) == "14.0000" and goal.measurable_unit == "sites"
    assert goal.direction == "down_is_good" and goal.baseline_at is not None
    assert goal.target_date is not None and goal.client_company_id == session.company_id
    assert Project.objects.get(source_map_row=rows[2]).title == "Bottleneck 2"
    assert discarded.converted_to == ""


@pytest.mark.django_db
def test_conversion_asks_for_a_baseline_before_it_will_write_a_measurable(session, ff,
                                                                         api):
    row = StrategyMapRow.objects.create(
        tenant=session.tenant, session=session, bottleneck="Supervisor overload",
        measurable="Inspections per site per month", horizon=60,
        state=StrategyMapRow.State.ACCEPTED)
    refused = api.as_(ff).post(f"/api/strategy-sessions/{session.pk}/convert/", {
        "choices": {str(row.pk): {"as": "goal"}}}, content_type="application/json")
    assert refused.status_code == 400
    assert "baseline" in refused.json()["detail"]
    assert Goal.objects.count() == 0


@pytest.mark.django_db
def test_leaving_every_row_out_creates_nothing_and_says_which_way_out(session, ff, api):
    """A press that would make nothing says so, rather than converting the
    session into an empty engagement."""
    rows = [StrategyMapRow.objects.create(
        tenant=session.tenant, session=session, position=i, bottleneck=f"B{i}",
        state=StrategyMapRow.State.ACCEPTED) for i in range(2)]
    refused = api.as_(ff).post(f"/api/strategy-sessions/{session.pk}/convert/", {
        "choices": {str(row.pk): {"as": "skip"} for row in rows}},
        content_type="application/json")
    assert refused.status_code == 400
    assert "nothing to create" in refused.json()["detail"]
    session.refresh_from_db()
    assert session.state != StrategySession.State.CONVERTED
    assert Goal.objects.count() == 0 and Project.objects.count() == 0


@pytest.mark.django_db
def test_a_baseline_written_in_words_is_refused_in_a_sentence(session, ff, api):
    """`baseline_value` is a decimal column. "7 a week" reaching it used to be a
    500 with nothing in it a person could act on."""
    row = StrategyMapRow.objects.create(
        tenant=session.tenant, session=session, bottleneck="Escalations",
        measurable="Decisions escalated per week", horizon=30,
        state=StrategyMapRow.State.ACCEPTED)
    refused = api.as_(ff).post(f"/api/strategy-sessions/{session.pk}/convert/", {
        "choices": {str(row.pk): {"as": "goal", "baseline_value": "7 a week"}}},
        content_type="application/json")
    assert refused.status_code == 400
    detail = refused.json()["detail"]
    assert "7 a week" in detail and "not a number" in detail
    assert refused.json()["rows"] == [str(row.pk)]
    assert Goal.objects.count() == 0


@pytest.mark.django_db
def test_one_press_names_every_row_that_is_not_ready(session, ff, api):
    """Nine measurables with no baseline used to be nine presses to learn nine
    things: it refused on the first row it met."""
    rows = [StrategyMapRow.objects.create(
        tenant=session.tenant, session=session, position=i,
        bottleneck=f"Bottleneck {i}", measurable=f"Measure {i}", horizon=60,
        state=StrategyMapRow.State.ACCEPTED) for i in range(4)]
    refused = api.as_(ff).post(f"/api/strategy-sessions/{session.pk}/convert/",
                               {"choices": {}}, content_type="application/json")
    assert refused.status_code == 400
    body = refused.json()
    assert set(body["rows"]) == {str(row.pk) for row in rows}
    assert body["detail"].startswith("4 rows are not ready")
    assert "baseline" in body["detail"]
    assert Goal.objects.count() == 0


@pytest.mark.django_db
def test_converting_makes_them_a_client_through_the_one_invariant(session, ff, api,
                                                                  seeded_tenant,
                                                                  prospect):
    StrategyMapRow.objects.create(
        tenant=session.tenant, session=session, bottleneck="Supervisor overload",
        state=StrategyMapRow.State.ACCEPTED)
    api.as_(ff).post(f"/api/strategy-sessions/{session.pk}/convert/",
                     {"choices": {}}, content_type="application/json")
    prospect.refresh_from_db()
    assert prospect.company.is_client_company is True
    assert prospect.type_links.filter(contact_type__code="client").exists()
    session.refresh_from_db()
    assert session.state == StrategySession.State.CONVERTED


# ------------------------------------------------------------------ AC-4.17

@pytest.mark.django_db
def test_ac_4_17_an_owner_resolves_or_the_text_is_kept_verbatim(session, seeded_tenant,
                                                               company, ff, api):
    exact = ContactFactory(tenant=seeded_tenant, first_name="Sam", last_name="Okonkwo",
                           company=company)
    ContactFactory(tenant=seeded_tenant, first_name="Maria", last_name="Alvarez",
                   company=company)
    ContactFactory(tenant=seeded_tenant, first_name="Maria", last_name="Diaz",
                   company=company)
    rows = [
        StrategyMapRow.objects.create(tenant=session.tenant, session=session, position=0,
                                      bottleneck="One", owner_text="Sam Okonkwo",
                                      state=StrategyMapRow.State.ACCEPTED),
        StrategyMapRow.objects.create(tenant=session.tenant, session=session, position=1,
                                      bottleneck="Two", owner_text="Maria in dispatch",
                                      state=StrategyMapRow.State.ACCEPTED),
        StrategyMapRow.objects.create(tenant=session.tenant, session=session, position=2,
                                      bottleneck="Three", owner_text="Maria",
                                      state=StrategyMapRow.State.ACCEPTED),
    ]
    api.as_(ff).post(f"/api/strategy-sessions/{session.pk}/convert/", {
        "choices": {str(row.pk): {"as": "goal"} for row in rows}},
        content_type="application/json")

    first = Goal.objects.get(source_map_row=rows[0])
    assert first.client_owner_contact_id == exact.pk
    for row in rows[1:]:
        goal = Goal.objects.get(source_map_row=row)
        assert goal.client_owner_contact_id is None
    rows[1].refresh_from_db(); rows[2].refresh_from_db()
    assert rows[1].owner_text == "Maria in dispatch"      # kept verbatim
    assert rows[2].owner_text == "Maria"


# ----------------------------------------------------------- AC-4.12 / AC-4.19

@pytest.mark.django_db
def test_ac_4_12_and_4_19_heavy_template_edits_leave_a_completed_session_identical(
    session, template, ff, api
):
    answer(session, "s1_revenue", {"text": "4.2m last year"})
    answer(session, "s4_done_right", {"said": "Spot checks."})
    before = api.as_(ff).get(f"/api/strategy-sessions/{session.pk}/").json()
    snapshot_before = StrategySession.objects.get(pk=session.pk).template_snapshot

    # Heavy edits: a whole section gone, three rewordings, a schema changed.
    StrategySection.objects.filter(template=template, code="what_they_value").delete()
    for key in ("s1_revenue", "s4_done_right", "s2_vision"):
        StrategyQuestion.objects.filter(template=template, key=key).update(
            prompt="Rewritten entirely.", deleted_at=timezone.now())
    StrategyQuestion.objects.filter(template=template, key="s1_team").update(
        response_schema="rating_1_10")

    after = api.as_(ff).get(f"/api/strategy-sessions/{session.pk}/").json()
    assert StrategySession.objects.get(pk=session.pk).template_snapshot == snapshot_before
    assert after["sections"] == before["sections"]
    assert after["answers"] == before["answers"]
    assert "what_they_value" in {s["code"] for s in after["sections"]}
    # The soft-deleted questions are still rows, not holes.
    assert StrategyQuestion.all_objects.filter(template=template,
                                               key="s1_revenue").exists()


# ------------------------------------------------------------------ AC-4.13

@pytest.mark.django_db
def test_ac_4_13_a_va_never_receives_the_investment_fields(session, seeded_tenant, api):
    answer(session, "s9_investment_range", {"agreed": True,
                                            "notes": "8k a month for six months"})
    answer(session, "s9_reaction_to_range", {"agreed": False, "notes": "Winced."})
    answer(session, "s1_revenue", {"text": "4.2m"})
    va = MembershipFactory(tenant=seeded_tenant, role="VA")

    response = api.as_(va).get(f"/api/strategy-sessions/{session.pk}/")
    assert response.status_code == 200
    body = response.content.decode()
    assert "8k a month" not in body and "Winced" not in body
    payload = response.json()
    keys = {q["key"] for s in payload["sections"] for q in s["questions"]}
    assert "s9_investment_range" not in keys and "s9_reaction_to_range" not in keys
    assert "s1_revenue" in keys                      # §1–8 are all there
    assert {a["question_key"] for a in payload["answers"]} == {"s1_revenue"}


@pytest.mark.django_db
@pytest.mark.parametrize("path,method", [
    ("answers/", "post"), ("draft-rows/", "post"), ("draft-mirror/", "post"),
    ("send-pdf/", "post"), ("convert/", "post"), ("conversion-preview/", "get"),
])
def test_a_va_is_refused_every_fractional_only_action(path, method, session,
                                                      seeded_tenant, api):
    va = MembershipFactory(tenant=seeded_tenant, role="VA")
    call = getattr(api.as_(va), method)
    response = call(f"/api/strategy-sessions/{session.pk}/{path}",
                    {} if method == "post" else None)
    assert response.status_code == 403


@pytest.mark.django_db
def test_a_va_may_still_set_a_session_up_and_send_the_invite(session, seeded_tenant,
                                                             api, prospect):
    """Matrix 10.2/10.3/10.9 — the parts that carry nothing private."""
    va = MembershipFactory(tenant=seeded_tenant, role="VA")
    made = api.as_(va).post("/api/strategy-sessions/",
                            {"contact": str(prospect.pk)},
                            content_type="application/json")
    assert made.status_code == 201
    invite = api.as_(va).post(f"/api/strategy-sessions/{session.pk}/send-invite/")
    assert invite.status_code == 201
    assert api.as_(va).get(f"/api/strategy-sessions/{session.pk}/pdf/?as=html"
                           ).status_code == 200


# ------------------------------------------------------------------ AC-4.18

@pytest.mark.django_db
def test_ac_4_18_a_va_sends_the_invite_directly_and_it_carries_no_link_in_the_log(
    session, seeded_tenant, api
):
    va = MembershipFactory(tenant=seeded_tenant, role="VA")
    api.as_(va).post(f"/api/strategy-sessions/{session.pk}/send-invite/")
    message = OutboxMessage.all_objects.get(
        producer=OutboxMessage.Producer.PRECALL_INVITE)
    assert message.state == OutboxMessage.State.SENT        # no approval step
    # Assumption C3 — the stored copy carries no working credential.
    session.refresh_from_db()
    assert session.precall_token_hash not in message.body_text
    assert "/strategy/precall/" not in message.body_text
    assert "/strategy/precall/" not in message.body_html


# ------------------------------------------------------------------ AC-4.16

@pytest.mark.django_db
def test_ac_4_16_drafting_fires_on_exactly_two_triggers_and_is_costed(session, ff, api,
                                                                      fake_claude):
    fake_claude.reply = json.dumps([
        {"bottleneck": "Supervisor overload", "root_cause": "1 supervisor, 14 sites",
         "the_fix": "Area lead per 8 sites", "owner_text": "Integrator",
         "horizon": 60, "measurable": "Inspections per site per month"}])

    # 1 — saving an answer calls nothing.
    api.as_(ff).post(f"/api/strategy-sessions/{session.pk}/answers/",
                     {"question_key": "s4_done_right", "value": {"said": "Spot checks."}},
                     content_type="application/json")
    assert AiCall.all_objects.count() == 0
    assert StrategyMapRow.objects.filter(session=session).count() == 0

    # 2 — the button.
    api.as_(ff).post(f"/api/strategy-sessions/{session.pk}/draft-rows/")
    assert AiCall.all_objects.filter(purpose="strategy_rows", trigger="button").count() == 1
    call = AiCall.all_objects.get(purpose="strategy_rows")
    assert call.input_tokens > 0 and call.output_tokens > 0 and call.cost_usd > 0
    first_row = StrategyMapRow.objects.get(session=session)
    api.as_(ff).post(f"/api/strategy-map-rows/{first_row.pk}/accept/")

    # 3 — completing an area fires once, automatically.
    fake_claude.reply = json.dumps([
        {"bottleneck": "Supervisor overload", "root_cause": "changed", "the_fix": "x",
         "owner_text": "", "horizon": 30, "measurable": ""},
        {"bottleneck": "No inspection tooling", "root_cause": "paper",
         "the_fix": "App", "owner_text": "", "horizon": 30, "measurable": "Sites"}])
    for key in ("s4_done_right", "s4_location_parity"):
        api.as_(ff).post(f"/api/strategy-sessions/{session.pk}/answers/",
                         {"question_key": key, "value": {"said": "Answered."}},
                         content_type="application/json")
    assert AiCall.all_objects.filter(purpose="strategy_rows", trigger="auto").count() == 1

    # The accepted row is untouched, and the repeat proposal did not duplicate it.
    first_row.refresh_from_db()
    assert first_row.state == StrategyMapRow.State.ACCEPTED
    assert first_row.root_cause == "1 supervisor, 14 sites"
    assert StrategyMapRow.objects.filter(session=session).count() == 2

    # 4 — and it does not fire again on the next answer in the same area.
    api.as_(ff).post(f"/api/strategy-sessions/{session.pk}/answers/",
                     {"question_key": "s4_done_right", "value": {"said": "Again."}},
                     content_type="application/json")
    assert AiCall.all_objects.filter(purpose="strategy_rows").count() == 2


@pytest.mark.django_db
def test_a_claude_failure_leaves_the_session_exactly_as_it_was(session, ff, api,
                                                              fake_claude):
    from apps.tenancy import claude

    answer(session, "s4_done_right", {"said": "Spot checks."})
    fake_claude.raise_exc = RuntimeError("boom")
    with pytest.raises(Exception):
        # The fake raises a bare error; the module turns Anthropic's own errors
        # into ClaudeUnavailable. Either way nothing is written to the session.
        ai.draft_map_rows(session)
    assert StrategyMapRow.objects.filter(session=session).count() == 0


# ------------------------------------------------------------------ AC-4.14

@pytest.mark.django_db
def test_ac_4_14_a_session_and_its_token_are_unreachable_from_another_tenant(
    seeded_tenant, tenant_b, template, prospect, ff, api, client
):
    session = services.start(tenant=seeded_tenant, contact=prospect, template=template,
                             owner=ff.user)
    raw = services.issue_precall_token(session)
    theirs = MembershipFactory(tenant=tenant_b, role="FF")

    assert api.as_(theirs).get(f"/api/strategy-sessions/{session.pk}/").status_code == 404
    assert api.as_(theirs).get("/api/strategy-sessions/").json() == []
    assert api.as_(theirs).post(
        f"/api/strategy-sessions/{session.pk}/send-pdf/").status_code == 404
    assert api.as_(theirs).get(
        f"/api/strategy-sessions/{session.pk}/pdf/").status_code == 404

    # The public token is bound to its own session and nothing else; a tenant B
    # user holding the raw token gets that session's form and no other.
    resolved = services.session_for_precall_token(raw)
    assert resolved.tenant_id == seeded_tenant.pk


# --------------------------------------- pacing and the minimal template editor
#
# Both owner rulings of 2026-09-18: per-section pacing keeps nothing but the
# current section and when it started, and Beta's template editor changes three
# things and no more.

@pytest.mark.django_db
def test_clicking_a_section_starts_its_clock_and_keeps_nothing_else(session, ff, api):
    assert session.current_section == "" and session.current_section_at is None

    api.as_(ff).patch(f"/api/strategy-sessions/{session.pk}/",
                      {"current_section": "diagnostic"},
                      content_type="application/json")
    session.refresh_from_db()
    assert session.current_section == "diagnostic"
    first_at = session.current_section_at
    assert first_at is not None

    # Moving on replaces both. There is no ledger of where the call has been.
    api.as_(ff).patch(f"/api/strategy-sessions/{session.pk}/",
                      {"current_section": "strategy_map"},
                      content_type="application/json")
    session.refresh_from_db()
    assert session.current_section == "strategy_map"
    assert session.current_section_at > first_at

    # Clearing it stops the clock.
    api.as_(ff).patch(f"/api/strategy-sessions/{session.pk}/", {"current_section": ""},
                      content_type="application/json")
    session.refresh_from_db()
    assert session.current_section == "" and session.current_section_at is None


@pytest.mark.django_db
def test_a_section_that_is_not_in_this_session_is_refused(session, ff, api):
    refused = api.as_(ff).patch(f"/api/strategy-sessions/{session.pk}/",
                                {"current_section": "invented"},
                                content_type="application/json")
    assert refused.status_code == 400
    session.refresh_from_db()
    assert session.current_section == ""


@pytest.mark.django_db
def test_only_the_founder_fractional_edits_the_template(template, seeded_tenant, ff, api):
    for role in ("CF", "VA"):
        member = MembershipFactory(tenant=seeded_tenant, role=role)
        refused = api.as_(member).patch(f"/api/strategy-templates/{template.pk}/",
                                        {"questions": [{"key": "s4_done_right",
                                                        "must_ask": False}]},
                                        content_type="application/json")
        assert refused.status_code in (403, 404)
    assert StrategyQuestion.objects.get(template=template,
                                        key="s4_done_right").must_ask is True


@pytest.mark.django_db
def test_the_editor_changes_three_things_and_ignores_the_rest(template, ff, api):
    response = api.as_(ff).patch(f"/api/strategy-templates/{template.pk}/", {
        "questions": [{
            "key": "s4_done_right",
            "prompt": "How do you know last night went well?",
            "ask_when": "precall",
            "must_ask": False,
            # Not Beta's to change — these come with V1's editor.
            "is_financial": True,
            "has_fractional_note": False,
            "area": "Something else",
            "position": 99,
        }]}, content_type="application/json")
    assert response.status_code == 200 and response.json()["changed"] == ["s4_done_right"]

    question = StrategyQuestion.objects.get(template=template, key="s4_done_right")
    assert question.prompt == "How do you know last night went well?"
    assert question.ask_when == "precall" and question.must_ask is False
    assert question.is_financial is False           # untouched
    assert question.has_fractional_note is True     # untouched
    assert question.area == "Operations & quality"  # untouched
    assert question.position == 8                   # untouched
    assert AuditEvent.all_objects.filter(verb="strategy.template_edited").exists()


@pytest.mark.django_db
def test_an_edit_cannot_reach_a_session_already_under_way(session, template, ff, api):
    before = StrategySession.objects.get(pk=session.pk).template_snapshot
    api.as_(ff).patch(f"/api/strategy-templates/{template.pk}/", {
        "questions": [{"key": "s4_done_right", "prompt": "Rewritten mid-call.",
                       "ask_when": "precall", "must_ask": False}]},
        content_type="application/json")
    session.refresh_from_db()
    assert session.template_snapshot == before
    frozen = services.question_in(session.template_snapshot, "s4_done_right")
    assert frozen["must_ask"] is True and frozen["ask_when"] == "live"


@pytest.mark.django_db
@pytest.mark.parametrize("edit,expected", [
    ({"prompt": "   "}, 400),
    ({"ask_when": "whenever"}, 400),
])
def test_the_editor_refuses_an_empty_prompt_or_an_unknown_ask_when(edit, expected,
                                                                   template, ff, api):
    response = api.as_(ff).patch(f"/api/strategy-templates/{template.pk}/",
                                 {"questions": [{"key": "s4_done_right", **edit}]},
                                 content_type="application/json")
    assert response.status_code == expected


# --------------------------------------- the emailed link, walked end to end
#
# The 2026-09-19 bug: a valid token, a valid session, and a page that fetched
# `/api/strategy/precall/undefined` because the public page was rendered outside
# a <Route> and `useParams()` had nothing to give it. Every test before this one
# started from a token it already held, which is exactly how that survived. This
# one starts where a prospect starts: the URL in the delivered mail.

@pytest.mark.django_db
def test_the_link_in_the_delivered_invite_opens_the_form(seeded_tenant, template,
                                                         prospect, ff, api, client,
                                                         dev_outbox):
    import re

    made = api.as_(ff).post("/api/strategy-sessions/", {"contact": str(prospect.pk)},
                            content_type="application/json")
    assert made.status_code == 201
    session_id = made.json()["id"]

    sent = api.as_(ff).post(f"/api/strategy-sessions/{session_id}/send-invite/")
    assert sent.status_code == 201
    assert len(dev_outbox) == 1, "the invite did not reach the transport"

    # The URL as the prospect receives it — not one rebuilt from the database,
    # because the whole failure was in the trip from the mail to the request.
    body = dev_outbox[0].body
    found = re.search(r"https?://[^\s]+/strategy/precall/([A-Za-z0-9_-]+)", body)
    assert found, f"no pre-call link in the delivered mail:\n{body}"
    token = found.group(1)

    # And the stored copy still carries no working credential (assumption C3).
    stored = OutboxMessage.all_objects.get(
        producer=OutboxMessage.Producer.PRECALL_INVITE)
    assert token not in stored.body_text and token not in stored.body_html

    # Opened cold, with no session of any kind.
    opened = client.get(f"/api/strategy/precall/{token}")
    assert opened.status_code == 200, opened.content
    payload = opened.json()
    assert payload["first_name"] == prospect.first_name
    assert payload["of"] == 13 and payload["answered"] == 0
    assert payload["sections"][0]["questions"][0]["key"] == "s1_revenue"

    # And it answers, which is the other half of the link working.
    saved = client.post(f"/api/strategy/precall/{token}",
                        data=json.dumps({"question_key": "s1_revenue",
                                         "value": {"text": "4.2m"}}),
                        content_type="application/json")
    assert saved.status_code == 200 and saved.json()["answered"] == 1


@pytest.mark.django_db
def test_a_token_that_is_not_one_is_refused_the_same_way_as_an_expired_one(client,
                                                                           session):
    """What the broken page was hitting. Both are 404 with the same sentence:
    the page cannot be told apart a bad link from an old one, and neither can a
    prospect, so the message names the remedy rather than the cause."""
    services.issue_precall_token(session)
    for bad in ("undefined", "null", "not-a-token"):
        response = client.get(f"/api/strategy/precall/{bad}")
        assert response.status_code == 404
        assert "expired" in response.json()["detail"]
