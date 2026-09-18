"""Module 4 — the session, its frozen snapshot, its merge fields and its answers.

The guarantee under test, above all others, is **AC-4.12**: a completed session
renders from its own snapshot, so the live template can be edited, reordered or
emptied without changing a byte of what a past session shows.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.strategy import services
from apps.strategy.models import StrategyAnswer, StrategyQuestion
from apps.strategy.seed import seed_tenant

from . import registry_config  # noqa: F401
from .factories import CompanyFactory, CompanyLocationFactory, ContactFactory

PROSPECT = StrategyAnswer.AnsweredBy.PROSPECT
FRACTIONAL = StrategyAnswer.AnsweredBy.FRACTIONAL


@pytest.fixture
def template(tenant_a, in_tenant_a):
    return seed_tenant(tenant_a)


@pytest.fixture
def company(tenant_a):
    return CompanyFactory(tenant=tenant_a, name="Acme Facilities")


@pytest.fixture
def prospect(tenant_a, company):
    return ContactFactory(tenant=tenant_a, first_name="Dana", last_name="Reyes",
                          company=company)


@pytest.fixture
def session(tenant_a, template, prospect):
    return services.start(tenant=tenant_a, contact=prospect, template=template)


# ------------------------------------------------------------------ AC-4.12

@pytest.mark.django_db
def test_the_snapshot_is_the_whole_template_as_it_was_run(session, template):
    snapshot = session.template_snapshot
    assert snapshot["template"]["name"] == template.name
    assert [s["code"] for s in snapshot["sections"]][:3] == [
        "snapshot", "six_key_components", "where_they_want_to_go"]
    assert sum(len(s["questions"]) for s in snapshot["sections"]) == 47
    asked = services.question_in(snapshot, "s4_done_right")
    assert asked["must_ask"] is True and asked["response_schema"] == "diagnostic_triple"
    assert asked["area"] == "Operations & quality"


@pytest.mark.django_db
def test_editing_the_live_template_afterwards_changes_nothing_in_the_session(
    session, template, tenant_a
):
    before = session.template_snapshot

    question = StrategyQuestion.objects.get(template=template, key="s4_done_right")
    question.prompt = "Completely different wording now."
    question.must_ask = False
    question.save()
    StrategyQuestion.objects.filter(template=template, key="s1_revenue").update(
        deleted_at=timezone.now())
    StrategyQuestion.objects.filter(template=template, key="s2_vision").delete()

    session.refresh_from_db()
    assert session.template_snapshot == before
    frozen = services.question_in(session.template_snapshot, "s4_done_right")
    assert frozen["prompt"] == ("How do you know a site (job) was done right last "
                                "night? Inspection cadence and tooling")
    assert frozen["must_ask"] is True
    assert services.question_in(session.template_snapshot, "s2_vision") is not None


@pytest.mark.django_db
def test_a_question_deleted_before_the_session_is_never_in_it(tenant_a, template, prospect):
    StrategyQuestion.objects.filter(template=template, key="s1_revenue").update(
        deleted_at=timezone.now())
    session = services.start(tenant=tenant_a, contact=prospect, template=template)
    assert services.question_in(session.template_snapshot, "s1_revenue") is None
    assert sum(len(s["questions"]) for s in session.template_snapshot["sections"]) == 46


# ----------------------------------------------------------- the merge fields

@pytest.mark.django_db
def test_merge_fields_fill_from_the_session(session, company, tenant_a):
    CompanyLocationFactory(tenant=tenant_a, company=company, name="Denver", position=0)
    CompanyLocationFactory(tenant=tenant_a, company=company, name="Boulder", position=1)
    integrator = ContactFactory(tenant=tenant_a, first_name="Sam", last_name="Okonkwo",
                                company=company)
    session.integrator_contact = integrator
    session.save()

    context = services.merge_context(session)
    assert context["Integrator"] == "Sam Okonkwo"
    assert context["Company"] == "Acme Facilities"
    assert services.render_prompt("Is {Location B} run the way {Location A} is?",
                                  context) == "Is Boulder run the way Denver is?"
    assert services.render_prompt("What does {Integrator} own outright?", context) == (
        "What does Sam Okonkwo own outright?")


@pytest.mark.django_db
def test_a_missing_merge_field_is_named_rather_than_left_blank(session):
    """FR-4.9a — a blank reads as a bug and gets skipped mid-call."""
    context = services.merge_context(session)
    assert services.render_prompt("What does {Integrator} own outright?", context) == (
        "What does no Integrator identified own outright?")
    assert "{" not in services.render_prompt(
        "Is {Location B} run the way {Location A} is?", context)


@pytest.mark.django_db
def test_the_visionary_defaults_to_the_companys_primary_contact(tenant_a, template,
                                                                company, prospect):
    boss = ContactFactory(tenant=tenant_a, first_name="Robin", last_name="Vance",
                          company=company)
    company.primary_contact = boss
    company.save()
    session = services.start(tenant=tenant_a, contact=prospect, template=template)
    assert session.visionary_contact_id == boss.pk
    # With no primary contact, the prospect in front of you is the Visionary.
    company.primary_contact = None
    company.save()
    other = services.start(tenant=tenant_a, contact=prospect, template=template)
    assert other.visionary_contact_id == prospect.pk


# ------------------------------------------------------------ the public token

@pytest.mark.django_db
def test_the_precall_token_resolves_to_one_session_and_expires(session):
    raw = services.issue_precall_token(session)
    session.refresh_from_db()
    assert session.precall_token_hash and raw not in session.precall_token_hash
    assert services.session_for_precall_token(raw).pk == session.pk

    session.precall_expires_at = timezone.now() - timedelta(seconds=1)
    session.save()
    assert services.session_for_precall_token(raw) is None


@pytest.mark.django_db
def test_reissuing_the_token_invalidates_the_old_link(session):
    first = services.issue_precall_token(session)
    second = services.issue_precall_token(session)
    assert services.session_for_precall_token(first) is None
    assert services.session_for_precall_token(second).pk == session.pk


@pytest.mark.django_db
def test_a_made_up_token_resolves_to_nothing(session):
    services.issue_precall_token(session)
    assert services.session_for_precall_token("not-a-real-token") is None
    assert services.session_for_precall_token("") is None


# ---------------------------------------------------------------- the answers

@pytest.mark.django_db
@pytest.mark.parametrize("key,value,expected", [
    ("s1_revenue", {"text": " 4.2m / 5.1m "}, {"text": "4.2m / 5.1m"}),
    ("s2_vision", {"rating": 7, "comment": "Clear enough."},
     {"rating": 7, "comment": "Clear enough."}),
    ("s4_done_right", {"said": "Spot checks.", "cause": "No app.", "tried": "A binder."},
     {"said": "Spot checks.", "cause": "No app.", "tried": "A binder."}),
    ("s7_value_1", {"value": "Being called first.", "why": "Trust."},
     {"value": "Being called first.", "why": "Trust."}),
    ("s9_start_date", {"agreed": True, "notes": "1 October."},
     {"agreed": True, "notes": "1 October."}),
    ("s8_path_a", {"path": "A", "reaction": "Tempted.", "risk": "No time.",
                   "leaning": "B"},
     {"path": "A", "reaction": "Tempted.", "risk": "No time.", "leaning": "B"}),
])
def test_an_answer_is_validated_against_the_schema_in_the_snapshot(session, key, value,
                                                                   expected):
    answer = services.save_answer(session, question_key=key, value=value,
                                  answered_by=FRACTIONAL)
    assert answer.value == expected


@pytest.mark.django_db
@pytest.mark.parametrize("key,value", [
    ("s2_vision", {"rating": 11}),
    ("s2_vision", {"rating": 0}),
    ("s2_vision", {"rating": "seven"}),
    ("s2_vision", {"comment": "No rating at all."}),
    ("s1_revenue", {"text": "   "}),
    ("s9_start_date", {"agreed": "yes"}),
    ("s7_value_1", {"why": "Only the why."}),
])
def test_a_malformed_answer_is_refused(session, key, value):
    with pytest.raises(services.AnswerInvalid):
        services.save_answer(session, question_key=key, value=value,
                             answered_by=FRACTIONAL)


@pytest.mark.django_db
def test_an_answer_to_a_question_this_session_never_asked_is_refused(session):
    with pytest.raises(services.AnswerInvalid):
        services.save_answer(session, question_key="s9_invented",
                             value={"agreed": True}, answered_by=FRACTIONAL)


@pytest.mark.django_db
def test_saving_the_same_question_twice_updates_rather_than_duplicates(session):
    services.save_answer(session, question_key="s1_revenue", value={"text": "First"},
                         answered_by=PROSPECT)
    services.save_answer(session, question_key="s1_revenue", value={"text": "Second"},
                         answered_by=PROSPECT)
    answers = StrategyAnswer.objects.filter(session=session, question_key="s1_revenue")
    assert answers.count() == 1 and answers.first().value == {"text": "Second"}


@pytest.mark.django_db
def test_a_prospect_may_only_answer_the_pre_call_form(session):
    """The public token grants one capability, and it is not the live session."""
    with pytest.raises(services.AnswerInvalid) as refused:
        services.save_answer(session, question_key="s4_done_right",
                             value={"said": "Anything"}, answered_by=PROSPECT)
    assert refused.value.status == 403


@pytest.mark.django_db
def test_a_prospect_cannot_write_a_fractional_note(session):
    with pytest.raises(services.AnswerInvalid) as refused:
        services.save_answer(session, question_key="s1_revenue", value={"text": "4.2m"},
                             answered_by=PROSPECT, fractional_note="Sounds inflated.")
    assert refused.value.status == 403


@pytest.mark.django_db
def test_a_fractional_note_only_lands_where_the_question_allows_one(session):
    with_note = services.save_answer(session, question_key="s1_revenue",
                                     value={"text": "4.2m"}, answered_by=FRACTIONAL,
                                     fractional_note="Check against the P&L.")
    assert with_note.fractional_note == "Check against the P&L."
    without = services.save_answer(session, question_key="s2_vision",
                                   value={"rating": 6}, answered_by=FRACTIONAL,
                                   fractional_note="Nowhere to put this.")
    assert without.fractional_note == ""


# -------------------------------------------------------- Six Key Components

@pytest.mark.django_db
def test_six_key_components_averages_and_flags_the_lowest(session):
    for key, rating in [("s2_vision", 8), ("s2_people", 4), ("s2_data", 3),
                        ("s2_issues", 7), ("s2_process", 5), ("s2_traction", 6)]:
        services.save_answer(session, question_key=key, value={"rating": rating},
                             answered_by=PROSPECT)
    result = services.six_key_components(session)
    assert result["average"] == 5.5
    assert result["lowest"] == "s2_data"
    assert result["complete"] is True and result["answered"] == 6


@pytest.mark.django_db
def test_a_partly_answered_self_rating_names_no_lowest(session):
    """"Your lowest is Data" is a lie while three of them are blank."""
    services.save_answer(session, question_key="s2_vision", value={"rating": 9},
                         answered_by=PROSPECT)
    services.save_answer(session, question_key="s2_people", value={"rating": 4},
                         answered_by=PROSPECT)
    result = services.six_key_components(session)
    assert result["answered"] == 2 and result["of"] == 6
    assert result["complete"] is False and result["lowest"] is None
    assert result["average"] == 6.5          # of what was answered, and labelled so


# ---------------------------------------------------------------- matrix 10.8

@pytest.mark.django_db
def test_the_financial_questions_can_be_withheld_from_the_payload(session):
    keys = [q["key"] for _s, q in services.questions_in(session.template_snapshot,
                                                        include_financial=False)]
    assert "s9_investment_range" not in keys and "s9_reaction_to_range" not in keys
    assert "s9_start_date" in keys and len(keys) == 45
