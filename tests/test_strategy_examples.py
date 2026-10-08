"""P3 §9 phase 1 — "Start from the Operations example".

1. The example is the seed's industry-neutral wording, pinned, and the builder
   accepts every line of it.
2. `start_from` on create: what the copy holds, and the audit event.
3. Practice isolation and role boundaries.
4. The seed stays shut, a blank template is still blank, and a copy runs.

The pin (`tests/golden/strategy_examples/`) is rewritten only with
`UPDATE_STRATEGY_EXAMPLE_PIN=1`, and a rewrite is a decision for the owner.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from apps.strategy import builder, examples, rewording, seed, services
from apps.strategy.models import StrategyQuestion, StrategySession, StrategyTemplate
from apps.tenancy.context import tenant_context
from apps.tenancy.models import AuditEvent

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import ContactFactory
from .test_platform_isolation import in_practices_area
from .test_strategy_builder import ROOT, fingerprint, get, post, sections_of, url

PIN = Path(__file__).parent / "golden" / "strategy_examples"
UPDATE = os.environ.get("UPDATE_STRATEGY_EXAMPLE_PIN") == "1"
EXAMPLE = {"name": "Strategy session", "start_from": "operations_example"}

#: The three the owner named for the fixed fallback (E3), in the words the
#: builder accepts and a session asks.
FALLBACK = [
    "Where do decisions stall because they need {Visionary}?",
    "Turnover, time-to-fill, who recruits and how much of their week it takes",
    "Cash pinch points. Projects and supplies: profit centers or distractions?",
]


def content_of(payload) -> dict:
    """What a practice was given: every part's questions without their keys
    (which are made per template), and the settings."""
    return {
        "settings": payload["settings"],
        "sections": [{
            "kind": section["kind"], "title": section["title"],
            "time_budget_minutes": section["time_budget_minutes"],
            "included": section["included"],
            "questions": [{k: v for k, v in question.items() if k != "key"}
                          for question in section["questions"]],
        } for section in payload["sections"]],
    }


def make(api, who, **more):
    return post(api, who, ROOT, {**EXAMPLE, **more})


# ============================================================= the example

def test_the_example_is_the_seeds_neutral_wording_and_leaves_out_what_stays_yours():
    by_key = {question["key"]: question for _c, _t, _b, questions in seed.SECTIONS
              for question in questions}
    entries = [entry for items in examples.OPERATIONS_V1["questions"].values()
               for entry in items]
    for entry in entries:
        source = by_key[entry["seed_key"]]
        assert entry["prompt"] == seed.neutral_prompt(source["prompt"], source["key"])
        assert entry.get("is_financial", False) == source["is_financial"]
        assert entry.get("observation", False) == source["is_fractional_observation"]
    used = {entry["seed_key"] for entry in entries}
    assert not used & set(seed.SERVICE_BUSINESS_KEYS)
    assert "{Integrator}" not in json.dumps(examples.OPERATIONS_V1)
    counts = {kind: len(items) for kind, items in examples.OPERATIONS_V1["questions"].items()}
    assert counts == {"precall": 7, "ratings": 6, "diagnostic": 3, "mirror": 4,
                      "values": 5, "paths": 2, "scope": 9}
    assert [e["prompt"] for e in examples.OPERATIONS_V1["questions"]["diagnostic"]] == FALLBACK


def test_the_builder_would_refuse_none_of_the_example():
    """Checked line by line here, so a refusal names the line; creating from
    the example (below) is the same rules run for real."""
    for kind, items in examples.OPERATIONS_V1["questions"].items():
        rule = builder.RULES[kind]
        assert len(items) <= rule["most"], kind
        for entry in items:
            assert not builder.unknown_merge_fields(entry["prompt"]), entry
            assert not rewording.refusal("", rule["schema"], entry["prompt"]), entry
            assert len(entry.get("label", "")) <= 60
            if rule.get("needs_label") or entry.get("pdf_chip"):
                assert entry.get("label"), entry
    chips = [e for e in examples.OPERATIONS_V1["questions"]["precall"] if e.get("pdf_chip")]
    assert len(chips) == builder.CHIPS_MOST
    builder.clean_settings(examples.OPERATIONS_V1["settings"])


@pytest.mark.django_db
def test_the_builder_accepts_the_visionary_merge_field_in_a_v3_template(ff, api,
                                                                         seeded_tenant):
    blank = post(api, ff, ROOT, {"name": "Blank"}).json()
    assert "Visionary" in blank["merge_fields"]
    added = post(api, ff, f"{ROOT}{blank['id']}/questions/",
                 {"section": "diagnostic", "prompt": FALLBACK[0]})
    assert added.status_code == 201
    asked = sections_of(added.json())["diagnostic"]["questions"]
    assert [q["prompt"] for q in asked] == [FALLBACK[0]]
    # A field that does not exist is still refused, so this is not a gap.
    assert post(api, ff, f"{ROOT}{blank['id']}/questions/",
                {"section": "diagnostic",
                 "prompt": "Where do decisions stall because they need {Owner}?"}
                ).status_code == 400


@pytest.mark.django_db
def test_the_visionary_field_in_a_session_is_the_prospect_by_name(seeded_tenant,
                                                                         in_tenant_a, ff):
    template, _version = examples.create(seeded_tenant, name="Strategy session",
                                         start_from=examples.OPERATIONS)
    prospect = ContactFactory(tenant=seeded_tenant, first_name="Dana", last_name="Reyes")
    session = services.start(tenant=seeded_tenant, contact=prospect, template=template,
                             owner=ff.user)
    # The person the session is with is the Visionary unless someone else is named.
    assert services.render_prompt(FALLBACK[0], services.merge_context(session)) == \
        "Where do decisions stall because they need Dana Reyes?"
    session.visionary_contact = None
    session.save()
    assert services.render_prompt(FALLBACK[0], services.merge_context(session)).startswith(
        "Where do decisions stall because they need the Visionary?")


# ============================================================ start_from

@pytest.mark.django_db
def test_start_from_the_example_makes_the_practices_own_ready_template(ff, api,
                                                                       seeded_tenant):
    made = make(api, ff)
    assert made.status_code == 201
    body = made.json()
    assert body["name"] == "Strategy session" and body["format"] == "v3"
    assert body["ready"] is True and body["missing"] == []
    assert not body["is_default"]
    by = sections_of(body)
    assert [q["prompt"] for q in by["diagnostic"]["questions"]] == FALLBACK
    assert [(q["label"], q["pdf_chip"]) for q in by["precall"]["questions"][:3]] == [
        ("Revenue", True), ("Team", True), ("Sites", True)]
    assert [q["label"] for q in by["ratings"]["questions"]] == [
        "Vision", "People", "Data", "Issues", "Process", "Traction"]
    assert [q["is_fractional_observation"] for q in by["mirror"]["questions"]] == [
        False, False, False, True]
    assert [q["is_financial"] for q in by["scope"]["questions"]] == [
        False, False, False, True, True, False, False, False, False]
    assert by["values"]["included"] and len(by["values"]["questions"]) == 5
    assert body["settings"] == {**builder.default_settings(),
                                "advisor_role": "fractional operations executive"}
    assert sum(s["time_budget_minutes"] or 0 for s in body["sections"]) == 55
    with tenant_context(seeded_tenant.pk):
        template = StrategyTemplate.objects.get(pk=body["id"])
        assert template.tenant_id == seeded_tenant.pk
        # Reworded in place: the copy starts with nothing archived.
        assert not StrategyQuestion.objects.filter(
            template=template, deleted_at__isnull=False).exists()
        event = AuditEvent.all_objects.get(verb="strategy.template_created",
                                           target_id=template.pk)
        assert event.actor_id == ff.user.pk
        assert event.payload == {"name": "Strategy session",
                                 "start_from": "operations_example",
                                 "example_version": 1}


@pytest.mark.django_db
def test_the_example_is_pinned(ff, api, seeded_tenant):
    produced = json.dumps(content_of(make(api, ff).json()), indent=2, sort_keys=True,
                          ensure_ascii=False) + "\n"
    path = PIN / "operations_example_v1.json"
    if UPDATE:
        PIN.mkdir(parents=True, exist_ok=True)
        path.write_text(produced)
    assert path.exists(), "the pin is missing; it is written with UPDATE_STRATEGY_EXAMPLE_PIN=1"
    assert produced == path.read_text(), (
        "the Operations example changed. A change to it is a new version and a "
        "decision for the owner, not an edit to version 1.")


@pytest.mark.django_db
def test_absent_start_from_is_still_a_blank_template(ff, api, seeded_tenant, in_tenant_a):
    blank = post(api, ff, ROOT, {"name": "Blank"}).json()
    reference = builder.represent(builder.create_blank(seeded_tenant, name="Reference"))
    assert content_of(blank) == content_of(reference)
    assert blank["ready"] is False
    event = AuditEvent.all_objects.get(verb="strategy.template_created",
                                       target_id=blank["id"])
    assert event.payload == {"name": "Blank"}


@pytest.mark.django_db
@pytest.mark.parametrize("start_from", ["", "blank", "operations", "seed", 1, ["x"], False])
def test_an_unknown_start_is_refused_and_makes_nothing(ff, api, seeded_tenant, start_from):
    refused = make(api, ff, start_from=start_from)
    assert refused.status_code == 400 and "operations_example" in refused.json()["detail"]
    with tenant_context(seeded_tenant.pk):
        assert not StrategyTemplate.objects.exists()


@pytest.mark.django_db
def test_a_refused_name_leaves_no_half_made_template(ff, api, seeded_tenant):
    assert make(api, ff).status_code == 201
    assert make(api, ff, name="strategy SESSION").status_code == 409
    assert make(api, ff, name=" ").status_code == 400
    with tenant_context(seeded_tenant.pk):
        assert StrategyTemplate.objects.count() == 1


@pytest.mark.django_db
def test_a_copy_is_the_practices_to_edit_and_never_follows_the_example(ff, api,
                                                                       seeded_tenant):
    first = make(api, ff).json()
    key = sections_of(first)["diagnostic"]["questions"][0]["key"]
    edited = post(api, ff, f"{ROOT}{first['id']}/question/",
                  {"key": key, "prompt": "Where do decisions wait on the owner?"})
    assert edited.status_code == 200
    removed = post(api, ff, f"{ROOT}{first['id']}/remove-question/",
                   {"key": sections_of(first)["scope"]["questions"][8]["key"]})
    assert removed.status_code == 200
    # The next one made is the example again, not the edited copy.
    second = make(api, ff, name="A second one").json()
    assert [q["prompt"] for q in sections_of(second)["diagnostic"]["questions"]] == FALLBACK
    assert len(sections_of(second)["scope"]["questions"]) == 9
    assert content_of(get(api, ff, f"{ROOT}{first['id']}/").json()) != content_of(second)


# ============================================== isolation and role boundaries

@pytest.mark.django_db
def test_tenant_isolation_a_copy_of_the_example_is_invisible_to_another_practice(
        ff, api, seeded_tenant, tenant_b):
    mine = make(api, ff).json()
    other = _member(tenant_b, "FF")
    assert get(api, other, "/api/strategy-templates/").json() == []
    found = get(api, other, f"{ROOT}{mine['id']}/")
    assert found.status_code == 404 and mine["id"] not in found.content.decode()
    with tenant_context(seeded_tenant.pk):
        before = fingerprint(StrategyTemplate.objects.get(pk=mine["id"]))
    for verb, body in [
            ("settings/", {"settings": {"advisor_role": "consultant"}}),
            ("questions/", {"section": "snapshot", "prompt": "What do you sell?"}),
            ("question/", {"key": sections_of(mine)["diagnostic"]["questions"][0]["key"],
                           "prompt": "Theirs now"})]:
        assert post(api, other, f"{ROOT}{mine['id']}/{verb}", body).status_code == 404, verb
    with tenant_context(seeded_tenant.pk):
        assert fingerprint(StrategyTemplate.objects.get(pk=mine["id"])) == before
    # The same name is free there, and theirs is theirs.
    theirs = make(api, other)
    assert theirs.status_code == 201
    with tenant_context(tenant_b.pk):
        assert StrategyTemplate.objects.get(pk=theirs.json()["id"]).tenant_id == tenant_b.pk
        assert StrategyTemplate.objects.count() == 1
    assert [t["id"] for t in get(api, ff, "/api/strategy-templates/").json()] == [mine["id"]]


@pytest.mark.django_db
def test_tenant_isolation_the_example_does_not_read_executives_now(ff, api, seeded_tenant,
                                                                   tenant_b):
    """Practice A holds the seed, the focused template and a copy of the
    example, and rewords every question it owns. What practice B is then given
    is what it would have been given before."""
    other = _member(tenant_b, "FF")
    before = content_of(make(api, other, name="Before").json())
    with tenant_context(seeded_tenant.pk):
        seed.seed_tenant(seeded_tenant)
        seed.create_focused(seeded_tenant)
        template, _version = examples.create(seeded_tenant, name="Ours",
                                             start_from=examples.OPERATIONS)
        builder.update_settings(template, {"advisor_role": "EXECUTIVES NOW ONLY",
                                           "diagnostic_size": 7})
        StrategyQuestion.objects.exclude(response_schema="rating_1_10").update(
            prompt="EXECUTIVES NOW ONLY", label="OURS")
        StrategyTemplate.objects.update(is_default=False)
    after = make(api, other, name="After").json()
    assert content_of(after) == before
    assert "EXECUTIVES NOW" not in json.dumps(after) and "OURS" not in json.dumps(after)


@pytest.mark.django_db
def test_tenant_isolation_the_platform_owner_cannot_start_from_the_example(seeded_tenant,
                                                                           api):
    owner = _member(seeded_tenant, "FF")
    owner.user.is_platform_owner = True
    owner.user.save()
    response = in_practices_area(api.as_(owner)).post(
        ROOT, data=json.dumps(EXAMPLE), content_type="application/json")
    assert response.status_code in (403, 404)
    with tenant_context(seeded_tenant.pk):
        assert not StrategyTemplate.objects.exists()


@pytest.mark.django_db
def test_role_boundaries_only_the_practice_owner_starts_from_the_example(
        ff, cf, va, fcc, api, seeded_tenant):
    for who, status in ((cf, 403), (va, 403), (fcc, 404)):
        assert make(api, who).status_code == status
    with tenant_context(seeded_tenant.pk):
        assert not StrategyTemplate.objects.exists()
        assert not AuditEvent.all_objects.filter(verb="strategy.template_created").exists()
    assert make(api, ff).status_code == 201
    # Staff read it, as they read any template; a client has no route to it.
    made = get(api, ff, "/api/strategy-templates/").json()[0]["id"]
    assert get(api, cf, f"{ROOT}{made}/").status_code == 200
    assert get(api, va, f"{ROOT}{made}/").status_code == 200
    assert get(api, fcc, f"{ROOT}{made}/").status_code == 404


# ============================================== the seed, and a session

@pytest.mark.django_db
def test_restore_from_seed_is_still_refused_when_the_only_template_is_the_example(
        ff, api, seeded_tenant):
    assert make(api, ff).status_code == 201
    refused = post(api, ff, "/api/strategy-templates/restore-from-seed/", {"name": "Ops"})
    assert refused.status_code == 403
    with tenant_context(seeded_tenant.pk):
        assert list(StrategyTemplate.objects.values_list("name", "format")) == [
            ("Strategy session", "v3")]


@pytest.mark.django_db
def test_a_copy_of_the_example_starts_a_session_with_no_edits_and_freezes(
        ff, api, seeded_tenant, in_tenant_a):
    made = make(api, ff).json()
    template = StrategyTemplate.objects.get(pk=made["id"])
    prospect = ContactFactory(tenant=seeded_tenant)
    session = services.start(tenant=seeded_tenant, contact=prospect, template=template,
                             owner=ff.user)
    frozen = session.template_snapshot
    assert frozen["template"]["format"] == "v3"
    assert frozen["template"]["settings"]["advisor_role"] == "fractional operations executive"
    diagnostic = next(s for s in frozen["sections"] if s["kind"] == "diagnostic")
    assert [q["prompt"] for q in diagnostic["questions"]] == FALLBACK
    assert all(q["is_diagnostic_fallback"] for q in diagnostic["questions"])
    # Editing the copy afterwards never reaches the session.
    post(api, ff, f"{ROOT}{made['id']}/question/",
         {"key": diagnostic["questions"][0]["key"], "prompt": "Changed later"})
    assert StrategySession.objects.get(pk=session.pk).template_snapshot == frozen


@pytest.mark.django_db
def test_the_observation_stays_off_the_pdf_of_a_session_from_the_example(
        ff, seeded_tenant, in_tenant_a):
    from apps.strategy import pdf

    template, _version = examples.create(seeded_tenant, name="Strategy session",
                                         start_from=examples.OPERATIONS)
    session = services.start(tenant=seeded_tenant, contact=ContactFactory(
        tenant=seeded_tenant), template=template, owner=ff.user)
    mirror = next(s for s in session.template_snapshot["sections"] if s["kind"] == "mirror")
    for question in mirror["questions"]:
        services.save_answer(
            session, question_key=question["key"],
            value={"text": "PRIVATE-ALIGNMENT" if question["is_fractional_observation"]
                   else "Three sites by 2029"},
            answered_by="fractional")
    printed = json.dumps(pdf.context_for(session), default=str)
    assert "Three sites by 2029" in printed and "PRIVATE-ALIGNMENT" not in printed
    assert "PRIVATE-ALIGNMENT" not in pdf.render_html(session)


@pytest.mark.django_db
def test_only_a_mirror_question_can_be_an_observation_and_the_api_does_not_offer_it(
        ff, api, seeded_tenant, in_tenant_a):
    template = builder.create_blank(seeded_tenant, name="Blank")
    with pytest.raises(services.SessionError):
        builder.add_question(template, section="snapshot", prompt="Seen, not asked",
                             observation=True)
    added = post(api, ff, f"{ROOT}{template.pk}/questions/",
                 {"section": "mirror", "prompt": "Seen, not asked", "observation": True,
                  "is_fractional_observation": True})
    assert added.status_code == 201
    asked = sections_of(added.json())["mirror"]["questions"]
    assert [q["is_fractional_observation"] for q in asked] == [False]
