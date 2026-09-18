"""Module 4 — the Operations template, seeded verbatim (Phase 4, done-means 1).

Verbatim is the requirement: this is the owner's real session structure, and a
reworded prompt is a different question. These tests pin the counts, the flags
that carry behaviour (`must_ask`, `is_financial`, `is_fractional_observation`),
and a sample of prompts *including their merge fields* — the place a silent
rewording would show up first.
"""

from __future__ import annotations

import pytest

from apps.strategy.models import StrategyQuestion, StrategySection, StrategyTemplate
from apps.strategy.seed import SECTIONS, TEMPLATE_NAME, seed_tenant

from . import registry_config  # noqa: F401


@pytest.fixture
def seeded(tenant_a, in_tenant_a):
    return seed_tenant(tenant_a)


@pytest.mark.django_db
def test_the_operations_template_seeds_nine_sections_and_every_question(seeded):
    assert seeded.name == TEMPLATE_NAME
    assert seeded.discipline == "operations" and seeded.is_default is True

    sections = StrategySection.objects.filter(template=seeded).order_by("position")
    assert [s.code for s in sections] == [code for code, _t, _b, _q in SECTIONS]
    assert len(sections) == 9

    questions = StrategyQuestion.objects.filter(template=seeded)
    assert questions.count() == 47
    # The pre-call form is 13 items — the number the build plan's manual check 2
    # asks about, because it is a real completion risk.
    assert questions.filter(ask_when="precall").count() == 13
    assert questions.filter(ask_when="live").count() == 34


@pytest.mark.django_db
def test_every_section_holds_the_questions_the_seed_document_gives_it(seeded):
    counts = {
        s.code: StrategyQuestion.objects.filter(section=s).count()
        for s in StrategySection.objects.filter(template=seeded)
    }
    assert counts == {
        "snapshot": 7, "six_key_components": 6, "where_they_want_to_go": 4,
        "diagnostic": 14,
        # The mirror's two fields and the map's rows are columns and rows of
        # their own, not answers — so these sections carry no questions.
        "mirror": 0, "strategy_map": 0,
        "what_they_value": 5, "two_paths": 2, "scope_agreement": 9,
    }


@pytest.mark.django_db
def test_the_flags_that_carry_behaviour(seeded):
    questions = StrategyQuestion.objects.filter(template=seeded)

    # The seed's ★, seven of them.
    assert set(questions.filter(must_ask=True).values_list("key", flat=True)) == {
        "s4_decisions_stall", "s4_integrator_owns",     # Leadership & succession
        "s4_turnover", "s4_span_of_control",            # People & labor
        "s4_done_right",                                # Operations & quality
        "s4_gross_margin",                              # Money
        "s4_double_customers",                          # Scaling stress test
    }

    # AC-4.13 — what a VA never sees.
    assert sorted(questions.filter(is_financial=True).values_list("key", flat=True)) == [
        "s9_investment_range", "s9_reaction_to_range",
    ]
    # FR-4.17 — shown to the fractional, never asked aloud.
    assert list(questions.filter(is_fractional_observation=True)
                .values_list("key", flat=True)) == ["s3_alignment_observation"]
    # A private note field on all seven Snapshot items, and on every diagnostic
    # question: AC-4.9's "§4 internal observation" is one of the five markers
    # the PDF excludes, and it has its own toggle.
    assert questions.filter(has_fractional_note=True).count() == 21

    by_schema = {}
    for schema in questions.values_list("response_schema", flat=True):
        by_schema[schema] = by_schema.get(schema, 0) + 1
    assert by_schema == {"free_text": 11, "rating_1_10": 6, "diagnostic_triple": 14,
                         "value_pair": 5, "path_reaction": 2, "agreed_note": 9}


@pytest.mark.django_db
def test_prompts_and_merge_fields_are_the_seed_documents_own_words(seeded):
    prompts = dict(StrategyQuestion.objects.filter(template=seeded)
                   .values_list("key", "prompt"))
    assert prompts["s1_software"] == (
        "Software stack — and what lives in someone's head instead of a system")
    assert prompts["s3_three_year_picture"] == (
        "3-year picture — revenue, locations, {Visionary}'s role, "
        "{Integrator}'s role")
    assert prompts["s4_done_right"] == (
        "How do you know a site (job) was done right last night? "
        "Inspection cadence and tooling")
    assert prompts["s4_location_parity"] == "Is {Location B} run the way {Location A} is?"
    assert prompts["s9_investment_range"] == "Investment range discussed ($/month × months)"


@pytest.mark.django_db
def test_the_six_areas_the_diagnostic_is_grouped_by(seeded):
    diagnostic = StrategySection.objects.get(template=seeded, code="diagnostic")
    areas = list(dict.fromkeys(
        StrategyQuestion.objects.filter(section=diagnostic).order_by("position")
        .values_list("area", flat=True)))
    # Seven headings, in the seed document's order. The prose above them says
    # "six places"; the list itself has seven, and verbatim wins. Raised with
    # the owner 2026-09-18.
    assert areas == ["Leadership & succession", "People & labor", "Sales engine",
                     "Operations & quality", "Money", "Customer loss",
                     "Scaling stress test"]


@pytest.mark.django_db
def test_seeding_twice_changes_nothing(tenant_a, in_tenant_a):
    first = seed_tenant(tenant_a)
    again = seed_tenant(tenant_a)
    assert again.pk == first.pk
    assert StrategySection.objects.filter(template=first).count() == 9
    assert StrategyQuestion.objects.filter(template=first).count() == 47


@pytest.mark.django_db
def test_a_seeded_template_belongs_to_its_own_tenant_only(tenant_a, tenant_b, in_tenant_a):
    seed_tenant(tenant_a)
    seed_tenant(tenant_b)
    mine = StrategyTemplate.objects.filter(name=TEMPLATE_NAME)
    assert mine.count() == 1 and mine.first().tenant_id == tenant_a.pk
    assert StrategyQuestion.objects.filter(template__tenant=tenant_b).count() == 0
