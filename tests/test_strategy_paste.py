"""P3 §9 phase 3 — "Paste several": a list of questions into one builder card.

1. The list is shown back and nothing is added until it is confirmed.
2. A refused line is marked and explained, and never stops the others.
3. Practice isolation and role boundaries.
"""

from __future__ import annotations

import pytest

from apps.strategy import builder, examples
from apps.strategy.models import StrategyQuestion
from apps.tenancy.context import tenant_context
from apps.tenancy.models import AuditEvent

from . import registry_config  # noqa: F401
from .conftest import _member
from .test_platform_isolation import in_practices_area
from .test_strategy_builder import (  # noqa: F401  (fixtures)
    ROOT, classic, fingerprint, focused, post, sections_of, url, v3,
)

PASTED = """
1. What does {Company} sell, and to whom?
2) How many people work there?

- Who runs the day to day?
•   What is the one number you watch every week?
"""
CLEAN = ["What does {Company} sell, and to whom?", "How many people work there?",
         "Who runs the day to day?", "What is the one number you watch every week?"]


def paste(api, who, template, section, text, **more):
    return post(api, who, url(template, "paste/"), {"section": section, "text": text, **more})


def prompts(template, code):
    with tenant_context(template.tenant_id):
        return list(StrategyQuestion.objects.filter(
            template=template, section__code=code, deleted_at__isnull=True)
            .order_by("position").values_list("prompt", flat=True))


def pasted_events(template):
    return AuditEvent.all_objects.filter(verb="strategy.template_questions_pasted",
                                         target_id=template.pk)


# ============================================ shown back, then confirmed

@pytest.mark.django_db
def test_a_pasted_list_is_shown_back_and_nothing_is_added_until_confirmed(v3, ff, api):
    before = fingerprint(v3)
    shown = paste(api, ff, v3, "snapshot", PASTED)
    assert shown.status_code == 200
    body = shown.json()
    # Blank lines dropped, list markers taken off, order kept.
    assert [line["prompt"] for line in body["lines"]] == CLEAN
    assert all(line["ok"] and line["why"] == "" for line in body["lines"])
    assert body["adding"] == 4 and body["added"] == []
    assert fingerprint(v3) == before, "showing the list writes nothing"
    assert sections_of(body["template"])["precall"]["questions"] == []
    assert not pasted_events(v3).exists()

    done = paste(api, ff, v3, "snapshot", PASTED, confirmed=CLEAN)
    assert done.status_code == 201
    assert prompts(v3, "snapshot") == CLEAN
    asked = sections_of(done.json()["template"])["precall"]["questions"]
    assert [q["prompt"] for q in asked] == CLEAN
    # Each is what a question added one at a time would be.
    assert {(q["ask_when"], q["response_schema"], q["has_fractional_note"], q["pdf_chip"],
             q["label"]) for q in asked} == {("precall", "free_text", True, False, "")}
    event = pasted_events(v3).get()
    assert event.actor_id == ff.user.pk
    assert event.payload == {"section": "snapshot", "keys": [q["key"] for q in asked]}


@pytest.mark.django_db
def test_pasted_questions_go_after_the_ones_already_there(v3, ff, api):
    post(api, ff, url(v3, "questions/"), {"section": "mirror", "prompt": "First of all"})
    paste(api, ff, v3, "mirror", "Second\nThird", confirmed=["Second", "Third"])
    assert prompts(v3, "mirror") == ["First of all", "Second", "Third"]


@pytest.mark.django_db
@pytest.mark.parametrize("code, kind, schema, flags", [
    ("snapshot", "precall", "free_text", {"ask_when": "precall"}),
    ("diagnostic", "diagnostic", "diagnostic_triple", {"is_diagnostic_fallback": True}),
    ("mirror", "mirror", "free_text", {"ask_when": "live"}),
    ("what_they_value", "values", "value_pair", {}),
    ("scope_agreement", "scope", "agreed_note", {"is_financial": False}),
])
def test_each_card_takes_a_list_in_its_own_shape(v3, ff, api, code, kind, schema, flags):
    held = prompts(v3, code)
    done = paste(api, ff, v3, code, "One of ours\nAnother of ours",
                 confirmed=["One of ours", "Another of ours"])
    assert done.status_code == 201, done.content
    assert prompts(v3, code) == held + ["One of ours", "Another of ours"]
    for question in sections_of(done.json()["template"])[kind]["questions"][-2:]:
        assert question["response_schema"] == schema
        assert all(question[flag] == value for flag, value in flags.items())


@pytest.mark.django_db
def test_a_pasted_rated_item_takes_its_label_from_the_start_of_the_line(v3, ff, api):
    text = ("Plan — Our plan is written down and shared.\n"
            "People: We have the right people in the right seats.\n"
            "Cash - We know our cash position every Monday.")
    shown = paste(api, ff, v3, "six_key_components", text).json()
    assert [(line["label"], line["ok"]) for line in shown["lines"]] == [
        ("Plan", True), ("People", True), ("Cash", True)]
    done = paste(api, ff, v3, "six_key_components", text,
                 confirmed=[line["prompt"] for line in shown["lines"]]).json()
    rated = sections_of(done["template"])["ratings"]["questions"]
    assert [(q["label"], q["prompt"]) for q in rated] == [
        ("Plan", "Plan — Our plan is written down and shared."),
        ("People", "People: We have the right people in the right seats."),
        ("Cash", "Cash - We know our cash position every Monday.")]
    assert done["template"]["ready"] is True, "three labeled rated items and two paths"


# ================================================= refused lines, explained

@pytest.mark.django_db
def test_refused_lines_are_marked_and_explained_and_the_rest_are_added(v3, ff, api):
    text = "\n".join([
        "Plan — Our plan is written down.",
        "People — Who runs each division, and where is the gap?",   # an open question
        "We review the numbers weekly.",                            # no label
        "Vision — " + "Our picture is clear and shared by everyone. " * 4,   # over 120
        "plan  —  our plan is WRITTEN down.",                       # the first again
        "Data — We run the week from {Scorecard}.",                 # no such merge field
        "Issues — Problems get raised openly and solved for good.",
    ])
    shown = paste(api, ff, v3, "six_key_components", text).json()
    marks = [(line["ok"], line["why"]) for line in shown["lines"]]
    assert [ok for ok, _why in marks] == [True, False, False, False, False, False, True]
    assert "asks for an explanation" in marks[1][1]
    assert "needs a short label" in marks[2][1]
    assert "120" in marks[3][1]
    assert "already in this part" in marks[4][1]
    assert "{Scorecard}" in marks[5][1]
    assert shown["adding"] == 2 and prompts(v3, "six_key_components") == []

    fine = [line["prompt"] for line in shown["lines"] if line["ok"]]
    done = paste(api, ff, v3, "six_key_components", text, confirmed=fine)
    assert done.status_code == 201
    assert prompts(v3, "six_key_components") == fine
    assert len(done.json()["added"]) == 2


@pytest.mark.django_db
def test_a_line_over_the_length_limit_is_refused(v3, ff, api):
    long = "Tell us about the business. " * 20
    shown = paste(api, ff, v3, "snapshot", f"What do you sell?\n{long}").json()
    assert [line["ok"] for line in shown["lines"]] == [True, False]
    assert "500 is the most" in shown["lines"][1]["why"]


@pytest.mark.django_db
def test_lines_past_what_the_part_holds_are_refused_not_the_whole_list(v3, ff, api):
    text = "\n".join(f"Value {n}" for n in range(1, 8))
    shown = paste(api, ff, v3, "what_they_value", text).json()
    assert [line["ok"] for line in shown["lines"]] == [True] * 5 + [False] * 2
    assert "holds 5 at most" in shown["lines"][5]["why"]
    paste(api, ff, v3, "what_they_value", text,
          confirmed=[f"Value {n}" for n in range(1, 6)])
    assert prompts(v3, "what_they_value") == [f"Value {n}" for n in range(1, 6)]


@pytest.mark.django_db
def test_a_question_already_in_the_part_is_not_added_twice(v3, ff, api):
    shown = paste(api, ff, v3, "scope_agreement", "start DATE\nWho signs").json()
    assert [(line["ok"]) for line in shown["lines"]] == [False, True]
    assert "already in this part" in shown["lines"][0]["why"]


@pytest.mark.django_db
def test_a_pasted_line_is_never_a_pdf_header_question(v3, ff, api):
    """A fourth header answer cannot arrive by pasting: a pasted line is not
    marked for the header, and marking it afterwards meets the usual limit."""
    for label in ("Revenue", "Team", "Sites"):
        assert post(api, ff, url(v3, "questions/"),
                    {"section": "snapshot", "prompt": f"{label}?", "label": label,
                     "pdf_chip": True}).status_code == 201
    done = paste(api, ff, v3, "snapshot", "A fourth", confirmed=["A fourth"]).json()
    fourth = sections_of(done["template"])["precall"]["questions"][-1]
    assert fourth["pdf_chip"] is False
    refused = post(api, ff, url(v3, "question/"),
                   {"key": fourth["key"], "label": "Fourth", "pdf_chip": True})
    assert refused.status_code == 400 and "3 answers at most" in refused.json()["detail"]


@pytest.mark.django_db
def test_nothing_is_added_when_the_list_changed_since_it_was_shown(v3, ff, api):
    shown = paste(api, ff, v3, "mirror", "One\nTwo\nThree").json()
    confirmed = [line["prompt"] for line in shown["lines"]]
    # Meanwhile the part fills up, in another tab.
    for n in range(4):
        post(api, ff, url(v3, "questions/"), {"section": "mirror", "prompt": f"Other {n}"})
    before = fingerprint(v3)
    stale = paste(api, ff, v3, "mirror", "One\nTwo\nThree", confirmed=confirmed)
    assert stale.status_code == 409
    body = stale.json()
    assert body["stale"] is True and body["added"] == []
    assert [line["ok"] for line in body["lines"]] == [True, False, False]
    assert fingerprint(v3) == before and not pasted_events(v3).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("text", ["", "  \n \n", None, 7, {"a": 1}])
def test_nothing_to_paste_is_said_so(v3, ff, api, text):
    assert paste(api, ff, v3, "snapshot", text).status_code == 400


@pytest.mark.django_db
def test_a_very_long_list_is_refused_whole(v3, ff, api):
    text = "\n".join(f"Question {n}" for n in range(builder.PASTE_MOST + 1))
    refused = paste(api, ff, v3, "snapshot", text)
    assert refused.status_code == 400 and "50 at most" in refused.json()["detail"]
    assert paste(api, ff, v3, "snapshot", "x", confirmed="x").status_code == 400


@pytest.mark.django_db
@pytest.mark.parametrize("code", ["two_paths", "strategy_map", "no_such_part"])
def test_the_paths_and_the_map_take_no_pasted_list(v3, ff, api, code):
    before = fingerprint(v3)
    refused = paste(api, ff, v3, code, "Path C — Something else", confirmed=[
        "Path C — Something else"])
    assert refused.status_code in (400, 404)
    assert fingerprint(v3) == before


@pytest.mark.django_db
def test_a_part_switched_off_takes_no_pasted_list(v3, ff, api):
    post(api, ff, url(v3, "include/"), {"kind": "values", "included": False})
    assert paste(api, ff, v3, "what_they_value", "Honesty",
                 confirmed=["Honesty"]).status_code == 404


@pytest.mark.django_db
def test_pasting_into_a_copy_of_the_example_takes_the_tag_off_nothing(ff, api, seeded_tenant,
                                                                      in_tenant_a):
    template, version = examples.create(seeded_tenant, name="Strategy session",
                                        start_from=examples.OPERATIONS)
    AuditEvent.all_objects.create(
        tenant=seeded_tenant, actor=ff.user, verb="strategy.template_created",
        target_type="strategy_template", target_id=template.pk,
        payload={"start_from": examples.OPERATIONS, "example_version": version})
    done = paste(api, ff, template, "mirror", "Ours entirely",
                 confirmed=["Ours entirely"]).json()
    marks = [q["from_example"] for q in sections_of(done["template"])["mirror"]["questions"]]
    assert marks == [True, True, True, True, False]


# ============================================== isolation and role boundaries

@pytest.mark.django_db
def test_tenant_isolation_another_practice_cannot_paste_or_preview(v3, tenant_b, api):
    other = _member(tenant_b, "FF")
    before = fingerprint(v3)
    for more in ({}, {"confirmed": CLEAN}):
        response = paste(api, other, v3, "snapshot", PASTED, **more)
        assert response.status_code == 404
        assert "Our session" not in response.content.decode()
    assert fingerprint(v3) == before and not pasted_events(v3).exists()


@pytest.mark.django_db
def test_tenant_isolation_the_platform_owner_cannot_paste(v3, seeded_tenant, api):
    import json

    owner = _member(seeded_tenant, "FF")
    owner.user.is_platform_owner = True
    owner.user.save()
    before = fingerprint(v3)
    response = in_practices_area(api.as_(owner)).post(
        url(v3, "paste/"), data=json.dumps({"section": "snapshot", "text": PASTED,
                                            "confirmed": CLEAN}),
        content_type="application/json")
    assert response.status_code in (403, 404)
    assert fingerprint(v3) == before


@pytest.mark.django_db
def test_role_boundaries_only_the_practice_owner_pastes_or_previews(v3, ff, cf, va, fcc,
                                                                    api):
    before = fingerprint(v3)
    for who, status in ((cf, 403), (va, 403), (fcc, 404)):
        for more in ({}, {"confirmed": CLEAN}):
            assert paste(api, who, v3, "snapshot", PASTED, **more).status_code == status
    assert fingerprint(v3) == before, "the rows are unchanged"
    assert not pasted_events(v3).exists()
    assert paste(api, ff, v3, "snapshot", PASTED, confirmed=CLEAN).status_code == 201


@pytest.mark.django_db
def test_a_classic_or_focused_template_takes_no_pasted_list(classic, focused, ff, api):
    for template in (classic, focused):
        before = fingerprint(template)
        assert paste(api, ff, template, "snapshot", PASTED,
                     confirmed=CLEAN).status_code == 409
        assert fingerprint(template) == before
