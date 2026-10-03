"""P3 phase 3 — session v3: the engine.

1. Before the call: the form and the questions email, on the practice's own
   questions; ratings are taken on the call.
2. The diagnostic: proposed from the pre-call answers, never asked until a
   person accepts; its size, its ceiling, a question added by hand.
3. The mirror with its own questions; map rows without duplicates.
4. What Claude is given and what it costs; isolation and role boundaries.
"""

from __future__ import annotations

import json
from decimal import Decimal
from unittest import mock

import pytest

from apps.strategy import ai, builder, diagnostic, seed, services, tasks, v3
from apps.strategy.models import (
    StrategyAnswer, StrategyDiagnosticProposal, StrategyMapRow, StrategyQuestion,
    StrategySession,
)
from apps.tenancy.context import tenant_context
from apps.tenancy.models import AiCall

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import CompanyFactory, ContactEmailFactory, ContactFactory

PROSPECT = StrategyAnswer.AnsweredBy.PROSPECT
FRACTIONAL = StrategyAnswer.AnsweredBy.FRACTIONAL
P = StrategyDiagnosticProposal.State


def post(api, who, url, body=None):
    return api.as_(who).post(url, data=json.dumps(body or {}),
                             content_type="application/json")


def patch(api, who, url, body):
    return api.as_(who).patch(url, data=json.dumps(body), content_type="application/json")


def build(tenant, name="Our session", *, values=True, size=3):
    template = builder.create_blank(tenant, name=name)
    add = lambda section, prompt, **more: builder.add_question(  # noqa: E731
        template, section=section, prompt=prompt, **more)
    add("snapshot", "What does {Company} sell, and to whom?", label="Sells")
    add("snapshot", "How many people work there?", label="Team", pdf_chip=True)
    add("snapshot", "What do you want from {Practice}?")
    add("six_key_components", "Plan — Our plan is written down and shared.", label="Plan")
    add("six_key_components", "Team — The right people are in the right seats.",
        label="Team")
    add("six_key_components", "Numbers — We run the week from a few numbers.",
        label="Numbers")
    add("diagnostic", "Where does work get stuck waiting for you?")
    add("diagnostic", "What breaks when you take a week off?")
    add("mirror", "Three years from now, what does {Company} look like?")
    add("what_they_value", "Value 1 — in their words, and why")
    builder.update_settings(template, {"advisor_role": "business consultant",
                                       "diagnostic_size": size})
    if not values:
        builder.set_included(template, kind="values", included=False)
    return template


@pytest.fixture
def template(seeded_tenant, in_tenant_a):
    return build(seeded_tenant)


@pytest.fixture
def prospect(seeded_tenant):
    company = CompanyFactory(tenant=seeded_tenant, name="Acme Facilities")
    contact = ContactFactory(tenant=seeded_tenant, first_name="Dana", last_name="Reyes",
                             company=company)
    ContactEmailFactory(tenant=seeded_tenant, contact=contact, address="dana@acme.invalid",
                        is_primary=True)
    return contact


@pytest.fixture
def session(seeded_tenant, template, prospect, ff):
    return services.start(tenant=seeded_tenant, contact=prospect, template=template,
                          owner=ff.user)


def keys(session, kind, **where):
    section = v3.section_of(session, kind)
    return [q["key"] for q in section["questions"]
            if all(q.get(k) == v for k, v in where.items())]


def answer(session, key, value, by=FRACTIONAL, note=None):
    return services.save_answer(session, question_key=key, value=value, answered_by=by,
                                fractional_note=note)


def precall(session, growth=True):
    sells, team, want = keys(session, "precall")
    answer(session, sells, {"text": "Office cleaning, to property managers"}, PROSPECT)
    answer(session, team, {"text": "22 people. Scheduling is in Jen's head."}, PROSPECT)
    answer(session, want, {"text": "We want to open a second branch next year"
                           if growth else "A calmer week"}, PROSPECT)


def rate(session, plan=7, team=3, numbers=2):
    for key, rating, comment in zip(keys(session, "ratings"), (plan, team, numbers),
                                    ("", "Two seats empty", "")):
        answer(session, key, {"rating": rating, "comment": comment})


def reply(*items):
    return json.dumps([{"slot": slot, "question": question, "basis": "what they wrote"}
                       for slot, question in items])


def sent(fake_claude, index=-1):
    request = fake_claude.requests[index]
    return request["system"], request["messages"][0]["content"]


def base(session):
    return f"/api/strategy-sessions/{session.pk}/"


def fresh(session):
    return StrategySession.objects.get(pk=session.pk)


# ============================================================ before the call

@pytest.mark.django_db
def test_the_form_asks_only_the_practices_own_precall_questions(session, client):
    token = services.issue_precall_token(session)
    payload = client.get(f"/api/strategy/precall/{token}").json()
    assert [s["code"] for s in payload["sections"]] == ["snapshot"]
    section = payload["sections"][0]
    assert section["scale"] == "", "no ratings on a v3 form"
    assert [q["response_schema"] for q in section["questions"]] == ["free_text"] * 3
    assert section["questions"][0]["prompt"] == "What does Acme Facilities sell, and to whom?"
    assert "{Practice}" not in section["questions"][2]["prompt"]
    assert "Tenant A" in section["questions"][2]["prompt"], "{Practice} is the practice"
    assert payload["of"] == 3
    body = json.dumps(payload)
    for private in ("label", "pdf_chip", "advisor_role", "business consultant", "kind"):
        assert private not in body, f"{private} is the practice's, not the prospect's"


@pytest.mark.django_db
def test_the_prospect_can_answer_those_and_nothing_else(session, client):
    token = services.issue_precall_token(session)
    form = f"/api/strategy/precall/{token}"
    sells = keys(session, "precall")[0]
    ok = client.post(form, data=json.dumps({"question_key": sells,
                                            "value": {"text": "Cleaning"}}),
                     content_type="application/json")
    assert ok.status_code == 200
    for live in (keys(session, "ratings")[0], keys(session, "scope")[0]):
        refused = client.post(form, data=json.dumps({
            "question_key": live, "value": {"rating": 9, "agreed": True}}),
            content_type="application/json")
        assert refused.status_code == 403
    assert StrategyAnswer.objects.filter(session=session).count() == 1


@pytest.mark.django_db
def test_the_questions_email_carries_the_same_three(session):
    from apps.strategy import emails

    blocks = emails.question_blocks(session)
    assert len(blocks) == 1 and not blocks[0]["is_rating"]
    assert len(blocks[0]["questions"]) == 3
    text, html = emails._questions_body(session, emails.default_intro(session))
    assert "What does Acme Facilities sell" in text and "Rate each one" not in text
    assert "Our plan is written down" not in text + html, "a rated item is asked on the call"


@pytest.mark.django_db
def test_completing_the_form_queues_the_proposal_on_the_worker(session, client):
    token = services.issue_precall_token(session)
    with mock.patch("django_q.tasks.async_task") as queued:
        client.post(f"/api/strategy/precall/{token}/complete")
    queued.assert_called_once_with("apps.strategy.tasks.propose_diagnostic",
                                   str(session.tenant_id), str(session.pk))


# ================================================================== the ratings

@pytest.mark.django_db
def test_ratings_are_taken_on_the_call_under_the_templates_scale(session, ff, api):
    plan, team, numbers = keys(session, "ratings")
    for key, rating in ((plan, 7), (team, 3)):
        assert post(api, ff, base(session) + "answers/", {
            "question_key": key, "value": {"rating": rating, "comment": ""}}).status_code == 200
    payload = api.as_(ff).get(base(session)).json()
    assert payload["format"] == "v3"
    assert payload["rating_scale"] == "1 means not true today, 10 means completely true"
    assert payload["diagnostic"] == {"size": 3, "most": 8}
    scores = payload["six_key_components"]
    assert (scores["answered"], scores["of"], scores["complete"]) == (2, 3, False)
    assert scores["lowest"] is None, "not until every one is rated"
    post(api, ff, base(session) + "answers/",
         {"question_key": numbers, "value": {"rating": 2, "comment": ""}})
    scores = api.as_(ff).get(base(session)).json()["six_key_components"]
    assert scores["lowest"] == numbers and scores["average"] == 4.0
    rated = next(s for s in payload["sections"] if s["kind"] == "ratings")
    assert [q["label"] for q in rated["questions"]] == ["Plan", "Team", "Numbers"]


# =============================================================== the diagnostic

@pytest.mark.django_db
def test_claude_words_the_slots_and_nothing_is_asked_until_accepted(session, fake_claude):
    precall(session)
    fake_claude.reply = reply((1, "What has to be true before the second branch opens?"),
                              ("gap", "What is in Jen's head that no system holds?"),
                              ("gap", "Who covers scheduling when Jen is away?"),
                              ("gap", "A third gap, past the template's number"),
                              (7, "A slot nobody asked for"))
    before = json.dumps(session.template_snapshot, sort_keys=True)
    made = diagnostic.propose(session)
    assert [p.rule for p in made] == ["growth", "precall_gap", "precall_gap"], \
        "the template's three: one growth slot, and the gaps fill what is left"
    assert all(p.state == "proposed" and p.ai_call_id for p in made)
    assert json.dumps(fresh(session).template_snapshot, sort_keys=True) == before, \
        "proposed, never asked"
    # Until one is accepted, the template's fixed questions are what is asked.
    asked = [q["prompt"] for q in services.visible_questions(
        v3.section_of(fresh(session), "diagnostic"))]
    assert asked == ["Where does work get stuck waiting for you?",
                     "What breaks when you take a week off?"]


@pytest.mark.django_db
def test_claude_is_given_only_what_they_wrote_before_the_call(session, fake_claude):
    precall(session)
    answer(session, keys(session, "mirror")[0], {"text": "MARKER-LIVE-ANSWER"})
    answer(session, keys(session, "scope")[2], {"agreed": True, "notes": "MARKER-MONEY"})
    # Typed in from an emailed reply, with the practice's own note beside it.
    answer(session, keys(session, "precall")[0], {"text": "Office cleaning"}, FRACTIONAL,
           note="MARKER-PRIVATE-NOTE")
    fake_claude.reply = "[]"
    diagnostic.propose(session)
    system, user = sent(fake_claude)
    assert "for a business consultant to ask" in system
    assert "fractional operations executive" not in system
    assert "Assert nothing that is not in what you were given" in system
    assert "Jen's head" in user and "second branch" in user
    for marker in ("MARKER-LIVE-ANSWER", "MARKER-MONEY", "MARKER-PRIVATE-NOTE"):
        assert marker not in user, marker
    assert "at most 2" in system and "1. They mentioned growth or expansion" in user


@pytest.mark.django_db
def test_without_precall_answers_nothing_is_proposed_and_nothing_is_spent(session,
                                                                         fake_claude):
    assert diagnostic.propose(session) == []
    assert not fake_claude.requests and not AiCall.objects.exists()


@pytest.mark.django_db
def test_the_templates_number_is_how_many_are_proposed(seeded_tenant, in_tenant_a, prospect,
                                                       ff, fake_claude):
    for size, expected in ((1, 1), (6, 6)):
        template = build(seeded_tenant, name=f"Size {size}", size=size)
        session = services.start(tenant=seeded_tenant, contact=prospect, template=template,
                                 owner=ff.user)
        precall(session, growth=False)
        fake_claude.reply = reply(*[("gap", f"Gap question number {n}") for n in range(9)])
        assert len(diagnostic.propose(session)) == expected
        assert f"at most {size}" in sent(fake_claude)[0]


@pytest.mark.django_db
def test_accepting_puts_it_in_the_session_and_hides_the_fixed_questions(session, fake_claude,
                                                                        ff, api, template):
    precall(session)
    fake_claude.reply = reply((1, "What has to be true before the second branch opens?"),
                              ("gap", "What is in Jen's head that no system holds?"))
    first, second = diagnostic.propose(session)
    root = "/api/strategy-diagnostic-proposals/"
    assert patch(api, ff, f"{root}{second.pk}/",
                 {"prompt": "What does only Jen know?"}).status_code == 200
    assert post(api, ff, f"{root}{second.pk}/accept/").status_code == 200
    asked = services.visible_questions(v3.section_of(fresh(session), "diagnostic"))
    assert [q["prompt"] for q in asked] == ["What does only Jen know?"]
    assert asked[0]["response_schema"] == "diagnostic_triple" and asked[0]["dynamic"]
    assert post(api, ff, f"{root}{first.pk}/discard/").status_code == 200
    # The template is not touched by anything a session does.
    assert StrategyQuestion.objects.filter(template=template,
                                           section__kind="diagnostic").count() == 2
    # A discarded question is not proposed again, in any capitals.
    fake_claude.reply = reply(("gap", "what has to be TRUE before the second branch opens"),
                              ("gap", "Something new entirely?"))
    again = diagnostic.propose(fresh(session))
    assert [p.prompt for p in again] == ["Something new entirely?"]
    assert "What has to be true before the second branch opens?" in sent(fake_claude)[1], \
        "and Claude is told what was already asked, proposed or rejected"


@pytest.mark.django_db
def test_propose_from_the_ratings_takes_the_two_lowest(session, fake_claude, ff, api):
    precall(session)
    early = post(api, ff, base(session) + "propose-diagnostic/", {"from_ratings": True})
    assert early.status_code == 409 and "two ratings" in early.json()["detail"]
    assert not fake_claude.requests
    rate(session, plan=7, team=3, numbers=2)
    fake_claude.reply = reply((1, "Which numbers would you want every Monday?"),
                              (2, "Which seats are empty, and since when?"),
                              ("gap", "A gap, not asked for on this button"))
    made = post(api, ff, base(session) + "propose-diagnostic/", {"from_ratings": True})
    assert made.status_code == 201
    assert [(p["rule"], p["state"]) for p in made.json()["proposed"]] == [
        ("lowest_rating", "proposed"), ("lowest_rating", "proposed")]
    by_prompt = {p.prompt: p.basis for p in StrategyDiagnosticProposal.objects.all()}
    assert by_prompt["Which numbers would you want every Monday?"] == "Numbers: 2/10"
    assert by_prompt["Which seats are empty, and since when?"] == \
        'Team: 3/10 — "Two seats empty"'
    _system, user = sent(fake_claude)
    assert "Team: 3 — \"Two seats empty\"" in user and "Slots:\n1. Numbers is one of" in user
    assert "gap. None this time" in user


@pytest.mark.django_db
def test_a_question_added_by_hand_joins_the_session_not_the_template(session, ff, api,
                                                                    template, fake_claude):
    root = "/api/strategy-diagnostic-proposals/"
    made = post(api, ff, root, {"session": str(session.pk),
                                "prompt": "  Who decides   on price? "})
    assert made.status_code == 201
    body = made.json()
    assert (body["prompt"], body["state"], body["rule"], body["from_ai"]) == \
        ("Who decides on price?", "accepted", "manual", False)
    assert body["rule_label"] == "Added by hand during the session"
    asked = services.visible_questions(v3.section_of(fresh(session), "diagnostic"))
    assert [q["prompt"] for q in asked] == ["Who decides on price?"]
    assert asked[0]["key"] == body["question_key"]
    assert not fake_claude.requests and not AiCall.objects.exists(), "no Claude call"
    assert StrategyQuestion.objects.filter(template=template,
                                           section__kind="diagnostic").count() == 2
    assert not StrategyQuestion.objects.filter(prompt="Who decides on price?").exists()
    # It is answered like any other, and an unanswered one can come back out.
    assert post(api, ff, base(session) + "answers/", {
        "question_key": body["question_key"],
        "value": {"said": "The owner", "cause": "", "tried": ""}}).status_code == 200
    assert post(api, ff, f"{root}{body['id']}/remove/").status_code == 409, "answered: it stays"
    other = post(api, ff, root, {"session": str(session.pk), "prompt": "And who signs?"})
    assert post(api, ff, f"{root}{other.json()['id']}/remove/").status_code == 200
    assert post(api, ff, root, {"session": str(session.pk), "prompt": " "}).status_code == 400
    assert post(api, ff, root, {"session": str(session.pk),
                                "prompt": "x" * 501}).status_code == 400


@pytest.mark.django_db
def test_a_session_holds_eight_diagnostic_questions(session, ff, api, fake_claude):
    root = "/api/strategy-diagnostic-proposals/"
    for n in range(8):
        assert post(api, ff, root, {"session": str(session.pk),
                                    "prompt": f"Question {n}?"}).status_code == 201
    ninth = post(api, ff, root, {"session": str(session.pk), "prompt": "Question 9?"})
    assert ninth.status_code == 409 and "8 diagnostic questions at most" in \
        ninth.json()["detail"]
    assert StrategyDiagnosticProposal.objects.filter(state=P.ACCEPTED).count() == 8
    assert not StrategyDiagnosticProposal.objects.filter(prompt="Question 9?").exists(), \
        "a refused question leaves nothing behind"
    # And Claude is not called to propose into a full session.
    precall(session)
    full = post(api, ff, base(session) + "propose-diagnostic/")
    assert full.status_code == 409 and not fake_claude.requests


@pytest.mark.django_db
def test_nothing_is_added_once_the_session_is_finished(session, ff, api):
    session.state = StrategySession.State.COMPLETE
    session.save()
    refused = post(api, ff, "/api/strategy-diagnostic-proposals/",
                   {"session": str(session.pk), "prompt": "Too late?"})
    assert refused.status_code == 409 and "finished" in refused.json()["detail"]


@pytest.mark.django_db
def test_adding_by_hand_is_for_a_builder_session_only(seeded_tenant, in_tenant_a, prospect,
                                                     ff, api):
    classic = seed.seed_tenant(seeded_tenant)
    focused = seed.create_focused(seeded_tenant)
    for source in (classic, focused):
        old = services.start(tenant=seeded_tenant, contact=prospect, template=source,
                             owner=ff.user)
        before = json.dumps(old.template_snapshot, sort_keys=True)
        refused = post(api, ff, "/api/strategy-diagnostic-proposals/",
                       {"session": str(old.pk), "prompt": "By hand?"})
        assert refused.status_code == 409
        assert json.dumps(fresh(old).template_snapshot, sort_keys=True) == before


# =========================================================== mirror and the map

ROW = {"header": "A Weekly Scorecard", "statement": "Run the week from five numbers.",
       "bottleneck": "No weekly numbers", "root_cause": "Built by hand",
       "the_fix": "A five-line scorecard", "owner_text": "", "horizon": 30,
       "measurable": "Reviewed weekly"}


def rows_reply(*overrides):
    return json.dumps([{**ROW, **override} for override in overrides])


def diagnose(session):
    """A fixed diagnostic question, answered: enough for a draft to have input."""
    answer(session, keys(session, "diagnostic")[0],
           {"said": "Pricing waits for Dana", "cause": "No price book", "tried": ""},
           note="MARKER-PRIVATE-NOTE")


@pytest.mark.django_db
def test_drafting_reads_the_precall_the_ratings_the_destination_and_the_diagnostic(
        session, fake_claude):
    precall(session)
    rate(session)
    answer(session, keys(session, "mirror")[0], {"text": "Two branches, Dana off the tools"})
    diagnose(session)
    answer(session, keys(session, "values")[0], {"value": "Straight talk", "why": ""})
    answer(session, keys(session, "scope")[2], {"agreed": True, "notes": "MARKER-MONEY"})
    fake_claude.reply = rows_reply({})
    made = ai.draft_map_rows(session)
    assert [(r.state, r.header) for r in made] == [("proposed", "A Weekly Scorecard")]
    system, user = sent(fake_claude)
    assert "for a business consultant's Strategy Map" in system
    assert "fractional operations executive" not in system
    assert "You must not" in system and "assert any fact" in system, "the rules are unchanged"
    for expected in ("Before the call, they wrote:", "Office cleaning, to property managers",
                     "How they rated themselves, 1 to 10",
                     "Team: 3 — \"Two seats empty\"", "Where they want to go:",
                     "Two branches, Dana off the tools", "Pricing waits for Dana"):
        assert expected in user, expected
    for marker in ("MARKER-PRIVATE-NOTE", "MARKER-MONEY", "Straight talk"):
        assert marker not in user, marker


@pytest.mark.django_db
def test_the_mirror_is_proposed_from_its_own_questions_and_never_overwrites(session, ff, api,
                                                                           fake_claude):
    answer(session, keys(session, "mirror")[0], {"text": "Two branches, Dana off the tools"})
    session.mirror_goal = "What a person wrote."
    session.save()
    fake_claude.reply = json.dumps({"goal": "Two branches.", "unlocks": "Weekly numbers."})
    drafted = post(api, ff, base(session) + "draft-mirror/")
    assert drafted.json()["proposed_mirror"] == {"goal": "Two branches.",
                                                 "unlocks": "Weekly numbers."}
    assert fresh(session).mirror_goal == "What a person wrote.", "accepting is a person's act"
    system, user = sent(fake_claude)
    assert "for a business consultant: two sentences" in system
    assert "near the start" not in system and "in a strategy session" in system
    assert "Where they want to go:" in user and "Dana off the tools" in user


@pytest.mark.django_db
def test_a_rejected_row_is_told_to_claude_and_a_duplicate_is_dropped(session, ff, api,
                                                                    fake_claude):
    diagnose(session)
    fake_claude.reply = rows_reply({}, {"header": "A Price Book",
                                        "bottleneck": "Pricing is from memory"})
    scorecard, price = ai.draft_map_rows(session)
    assert post(api, ff, f"/api/strategy-map-rows/{price.pk}/discard/").status_code == 200
    fake_claude.reply = rows_reply(
        {"header": "a weekly scorecard!", "bottleneck": "Different words entirely"},
        {"header": "Other Header", "bottleneck": "pricing is, from MEMORY."},
        {"header": "Supervisors Who Audit", "bottleneck": "Quality is checked by complaint"})
    made = ai.draft_map_rows(session)
    assert [r.header for r in made] == ["Supervisors Who Audit"], \
        "the same header and the rejected bottleneck are both dropped"
    _system, user = sent(fake_claude)
    assert "Rows already rejected for this map — do not propose these themes again:" in user
    assert "- Pricing is from memory" in user.split("already rejected")[1]
    assert "(in the tray) No weekly numbers" in user


@pytest.mark.django_db
def test_a_run_proposes_no_more_than_the_map_has_room_for(session, ff, api, fake_claude):
    diagnose(session)
    for n in range(3):
        StrategyMapRow.objects.create(tenant=session.tenant, session=session, position=n,
                                      bottleneck=f"Accepted {n}",
                                      state=StrategyMapRow.State.ACCEPTED)
    fake_claude.reply = rows_reply(*[{"header": f"Header {n}", "bottleneck": f"New {n}"}
                                     for n in range(5)])
    assert len(ai.draft_map_rows(session)) == 2, "five less the three accepted"
    for row in StrategyMapRow.objects.filter(state="proposed"):
        assert post(api, ff, f"/api/strategy-map-rows/{row.pk}/accept/").status_code == 200
    calls = AiCall.objects.count()
    full = post(api, ff, base(session) + "draft-rows/")
    assert full.status_code == 200 and full.json()["drafted"] == []
    assert "it is full" in full.json()["detail"]
    assert AiCall.objects.count() == calls, "a full map makes no call"
    sixth = StrategyMapRow.objects.create(tenant=session.tenant, session=session,
                                          bottleneck="A sixth")
    assert post(api, ff, f"/api/strategy-map-rows/{sixth.pk}/accept/").status_code == 409
    # Consolidate aims for three to five, as on a focused map.
    fake_claude.reply = "[]"
    ai.consolidate_map_rows(session)
    assert "never more than five" in sent(fake_claude)[0]
    assert "a business consultant's Strategy Map" in sent(fake_claude)[0]


@pytest.mark.django_db
def test_the_automatic_draft_fires_once_when_the_accepted_questions_are_answered(
        session, ff, api, fake_claude):
    root = "/api/strategy-diagnostic-proposals/"
    made = [post(api, ff, root, {"session": str(session.pk), "prompt": f"Question {n}?"})
            .json() for n in range(2)]
    fake_claude.reply = rows_reply({})
    first = post(api, ff, base(session) + "answers/", {
        "question_key": made[0]["question_key"],
        "value": {"said": "One", "cause": "", "tried": ""}}).json()
    assert first["drafted"] == [] and not fake_claude.requests, "saving does not call Claude"
    second = post(api, ff, base(session) + "answers/", {
        "question_key": made[1]["question_key"],
        "value": {"said": "Two", "cause": "", "tried": ""}}).json()
    assert len(second["drafted"]) == 1 and len(fake_claude.requests) == 1
    assert AiCall.objects.get().trigger == "auto"
    post(api, ff, base(session) + "answers/", {
        "question_key": made[1]["question_key"],
        "value": {"said": "Two, again", "cause": "", "tried": ""}})
    assert len(fake_claude.requests) == 1, "and never again for the same area"


# ============================================================= what they value

@pytest.mark.django_db
def test_a_template_without_what_they_value_runs_without_it(seeded_tenant, in_tenant_a,
                                                           prospect, ff, api, fake_claude):
    template = build(seeded_tenant, name="No values", values=False)
    session = services.start(tenant=seeded_tenant, contact=prospect, template=template,
                             owner=ff.user)
    payload = api.as_(ff).get(base(session)).json()
    assert [s["kind"] for s in payload["sections"]] == [
        "precall", "ratings", "diagnostic", "mirror", "map", "paths", "scope"]
    assert payload["budget_minutes"] == 50
    path_a, path_b = keys(session, "paths")
    answer(session, path_a, {"reaction": "Tried it", "risk": "It slips", "leaning": ""})
    diagnose(session)
    fake_claude.reply = json.dumps({"a": {"pros": ["You keep control"], "cons": ["It slips"]},
                                    "b": {"pros": ["Someone owns it"], "cons": ["A cost"]}})
    saved = post(api, ff, base(session) + "answers/", {
        "question_key": path_b,
        "value": {"reaction": "Interested", "risk": "Cost", "leaning": "This one"}}).json()
    assert [(n["path"], n["kind"], n["state"]) for n in saved["path_notes"]] == [
        ("a", "pro", "proposed"), ("a", "con", "proposed"),
        ("b", "pro", "proposed"), ("b", "con", "proposed")]
    system, user = sent(fake_claude)
    assert "What they told us they value" not in user
    assert "with a business consultant" in system and "Tenant A" in system


# ==================================================== cost, caps and boundaries

@pytest.mark.django_db
def test_every_call_is_recorded_against_this_practice(session, ff, api, fake_claude,
                                                     tenant_b):
    precall(session)
    diagnose(session)
    fake_claude.reply = reply(("gap", "A question?"))
    post(api, ff, base(session) + "propose-diagnostic/")
    fake_claude.reply = rows_reply({})
    post(api, ff, base(session) + "draft-rows/")
    fake_claude.reply = json.dumps({"goal": "G.", "unlocks": "U."})
    post(api, ff, base(session) + "draft-mirror/")
    calls = list(AiCall.all_objects.order_by("created_at"))
    assert [(c.purpose, c.trigger, c.unattended) for c in calls] == [
        ("strategy_diagnostic_questions", "button", False),
        ("strategy_rows", "button", False), ("strategy_mirror", "button", False)]
    assert all(c.tenant_id == session.tenant_id and c.target_id == session.pk
               and c.cost_usd > 0 for c in calls)
    assert not AiCall.all_objects.filter(tenant=tenant_b).exists()


@pytest.mark.django_db
def test_the_workers_proposal_is_unattended_and_obeys_the_daily_cap(session, fake_claude,
                                                                   seeded_tenant):
    precall(session)
    fake_claude.reply = reply(("gap", "A question?"))
    seeded_tenant.ai_unattended_daily_cap_usd = Decimal("0")
    seeded_tenant.save()
    assert tasks.propose_diagnostic(str(seeded_tenant.pk), str(session.pk)) == 0
    assert not fake_claude.requests and not StrategyDiagnosticProposal.objects.exists()
    seeded_tenant.ai_unattended_daily_cap_usd = Decimal("5")
    seeded_tenant.save()
    assert tasks.propose_diagnostic(str(seeded_tenant.pk), str(session.pk)) == 1
    call = AiCall.objects.get()
    assert call.unattended and call.trigger == "auto"
    assert StrategyDiagnosticProposal.objects.get().state == "proposed"


@pytest.mark.django_db
def test_role_boundaries_an_assistant_reads_but_does_not_run_or_see_money(session, ff, va,
                                                                         api, fake_claude):
    precall(session)
    answer(session, keys(session, "scope")[2], {"agreed": True, "notes": "MARKER-MONEY"})
    fake_claude.reply = reply(("gap", "A question?"))
    proposal = diagnostic.propose(session)[0]
    root = "/api/strategy-diagnostic-proposals/"
    for url, body in ((root, {"session": str(session.pk), "prompt": "Mine?"}),
                      (f"{root}{proposal.pk}/accept/", {}),
                      (base(session) + "propose-diagnostic/", {}),
                      (base(session) + "propose-diagnostic/", {"from_ratings": True}),
                      (base(session) + "draft-rows/", {}),
                      (base(session) + "draft-mirror/", {}),
                      (base(session) + "answers/", {
                          "question_key": keys(session, "ratings")[0],
                          "value": {"rating": 5, "comment": ""}})):
        assert post(api, va, url, body).status_code == 403, url
    seen = api.as_(va).get(base(session))
    assert seen.status_code == 200
    body = seen.content.decode()
    assert "MARKER-MONEY" not in body and "Investment discussed" not in body
    assert seen.json()["diagnostic_proposals"] == [], "the tray is the practitioner's"
    owner = api.as_(ff).get(base(session)).content.decode()
    assert "MARKER-MONEY" in owner and "Investment discussed" in owner


@pytest.mark.django_db
def test_tenant_isolation_another_practice_cannot_reach_the_session(session, tenant_b, api,
                                                                   fake_claude):
    other = _member(tenant_b, "FF")
    before = json.dumps(session.template_snapshot, sort_keys=True)
    for url, body in (("/api/strategy-diagnostic-proposals/",
                       {"session": str(session.pk), "prompt": "Theirs?"}),
                      (base(session) + "propose-diagnostic/", {}),
                      (base(session) + "draft-rows/", {}),
                      (base(session) + "answers/", {
                          "question_key": keys(session, "ratings")[0],
                          "value": {"rating": 1, "comment": ""}})):
        assert post(api, other, url, body).status_code == 404, url
    assert api.as_(other).get(base(session)).status_code == 404
    assert not fake_claude.requests
    with tenant_context(session.tenant_id):
        assert json.dumps(fresh(session).template_snapshot, sort_keys=True) == before
        assert not StrategyDiagnosticProposal.objects.exists()
        assert not StrategyAnswer.objects.exists()


@pytest.mark.django_db
def test_tenant_isolation_claude_is_given_nothing_from_another_practice(
        session, tenant_b, fake_claude):
    with tenant_context(tenant_b.pk):
        theirs = build(tenant_b, name="Theirs")
        contact = ContactFactory(tenant=tenant_b, first_name="Other", last_name="Person")
        other = services.start(tenant=tenant_b, contact=contact, template=theirs)
        sells = keys(other, "precall")[0]
        answer(other, sells, {"text": "MARKER-OTHER-PRACTICE"}, PROSPECT)
        answer(other, keys(other, "diagnostic")[0],
               {"said": "MARKER-OTHER-PRACTICE", "cause": "", "tried": ""})
        StrategyMapRow.objects.create(tenant=tenant_b, session=other,
                                      bottleneck="MARKER-OTHER-PRACTICE",
                                      state=StrategyMapRow.State.DISCARDED)
    precall(session)
    diagnose(session)
    fake_claude.reply = "[]"
    diagnostic.propose(session)
    ai.draft_map_rows(session)
    ai.draft_mirror(session)
    assert len(fake_claude.requests) == 3
    for request in fake_claude.requests:
        assert "MARKER-OTHER-PRACTICE" not in json.dumps(request, default=str)


# ============================================================== resetting a draft

@pytest.mark.django_db
def test_a_v3_draft_reloads_from_its_template_and_never_from_the_seed(session, template, ff,
                                                                     api):
    refused = post(api, ff, base(session) + "restore-seed/")
    assert refused.status_code == 409 and "builder" in refused.json()["detail"]
    assert services.is_v3(fresh(session))
    builder.add_question(template, section="snapshot", prompt="A new one?")
    reloaded = post(api, ff, base(session) + "reset-questions/",
                    {"template": str(template.pk)})
    assert reloaded.status_code == 200
    assert len(keys(fresh(session), "precall")) == 4
    # A template that is no longer ready cannot be reloaded from.
    for question in StrategyQuestion.objects.filter(template=template,
                                                    section__kind="ratings")[:2]:
        builder.remove_question(template, key=question.key)
    again = post(api, ff, base(session) + "reset-questions/", {"template": str(template.pk)})
    assert again.status_code == 409 and "not ready to run" in again.json()["detail"]
