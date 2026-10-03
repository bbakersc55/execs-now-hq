"""P3 phase 2 — the template builder: schema, the v3 template and its API.

1. A blank v3 template, and what each part may hold.
2. Practice isolation and role boundaries on every builder verb.
3. The builder leaves classic and focused templates alone, and the editor
   leaves builder templates alone.
4. Settings, merge fields, the rating wording rule, the PDF header chips.
5. Ready to run, and the v3 snapshot a session freezes.
"""

from __future__ import annotations

import json

import pytest

from apps.strategy import builder, seed, services
from apps.strategy.models import (
    StrategyQuestion, StrategySection, StrategySession, StrategyTemplate,
)
from apps.tenancy.context import tenant_context
from apps.tenancy.models import AuditEvent

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import ContactFactory
from .test_platform_isolation import in_practices_area

ROOT = "/api/strategy-template-builder/"
V3_ONLY_SECTION_KEYS = {"kind", "intro", "show_in_pdf"}
V3_ONLY_QUESTION_KEYS = {"label", "pdf_chip"}


def post(api, who, url, body=None):
    return api.as_(who).post(url, data=json.dumps(body or {}),
                             content_type="application/json")


def get(api, who, url):
    return api.as_(who).get(url)


@pytest.fixture
def v3(seeded_tenant, in_tenant_a):
    return builder.create_blank(seeded_tenant, name="Our session")


@pytest.fixture
def classic(seeded_tenant, in_tenant_a):
    return seed.seed_tenant(seeded_tenant)


@pytest.fixture
def focused(seeded_tenant, classic):
    return seed.create_focused(seeded_tenant, make_default=False)


def url(template, verb=""):
    return f"{ROOT}{template.pk}/{verb}"


def add(api, who, template, section, prompt, **more):
    return post(api, who, url(template, "questions/"),
                {"section": section, "prompt": prompt, **more})


def sections_of(payload):
    return {section["kind"]: section for section in payload["sections"]}


def make_ready(api, ff, template):
    for label in ("Plan", "People"):
        assert add(api, ff, template, "six_key_components",
                   f"{label} — We have this written down.", label=label).status_code == 201


# The write verbs, each with a body that would succeed for the practice owner.
def write_calls(template):
    path_key = StrategyQuestion.all_objects.filter(
        template=template, section__kind="paths").order_by("position").first().key
    scope = list(StrategyQuestion.all_objects.filter(
        template=template, section__kind="scope").order_by("position")
        .values_list("key", flat=True))
    return [
        ("settings/", {"settings": {"advisor_role": "business consultant"}}),
        ("section/", {"code": "diagnostic", "title": "Where it breaks"}),
        ("include/", {"kind": "values", "included": False}),
        ("questions/", {"section": "snapshot", "prompt": "What do you sell?"}),
        ("question/", {"key": path_key, "prompt": "Path A — Carry on yourselves"}),
        ("reorder/", {"section": "scope_agreement", "keys": list(reversed(scope))}),
        ("remove-question/", {"key": scope[0]}),
    ]


def fingerprint(template):
    """Everything a builder verb could change, for "nothing changed"."""
    with tenant_context(template.tenant_id):
        template = StrategyTemplate.objects.get(pk=template.pk)
        return json.dumps({
            "template": [template.name, template.format, template.settings],
            "sections": list(StrategySection.objects.filter(template=template)
                             .order_by("position").values(
                                 "code", "kind", "title", "intro", "show_in_pdf",
                                 "deleted_at", "time_budget_minutes")),
            "questions": list(StrategyQuestion.objects.filter(template=template)
                              .order_by("section__position", "position", "key").values(
                                  "key", "prompt", "label", "pdf_chip", "position",
                                  "deleted_at", "is_financial", "must_ask")),
        }, sort_keys=True, default=str)


# ================================================================== a blank one

@pytest.mark.django_db
def test_a_new_template_is_the_eight_parts_with_neutral_paths_and_scope(ff, api,
                                                                         seeded_tenant):
    made = post(api, ff, ROOT, {"name": "  Our   session "})
    assert made.status_code == 201
    body = made.json()
    assert body["name"] == "Our session" and body["format"] == "v3"
    assert not body["is_default"], "making a template changes no practice's default"
    assert [(s["kind"], s["code"], s["time_budget_minutes"]) for s in body["sections"]] == [
        ("precall", "snapshot", None), ("ratings", "six_key_components", 5),
        ("diagnostic", "diagnostic", 15), ("mirror", "mirror", 10),
        ("map", "strategy_map", 10), ("values", "what_they_value", 5),
        ("paths", "two_paths", 5), ("scope", "scope_agreement", 5)]
    by = sections_of(body)
    assert [len(by[k]["questions"]) for k in ("precall", "ratings", "diagnostic", "mirror",
                                              "map", "values")] == [0] * 6
    assert [q["prompt"] for q in by["paths"]["questions"]] == [
        "Path A — Continue to run it yourselves", "Path B — Work with us"]
    assert [(q["prompt"], q["is_financial"]) for q in by["scope"]["questions"]] == [
        ("Scope — what is in the first 90 days", False), ("Start date", False),
        ("Investment discussed", True)]
    assert body["settings"] == builder.default_settings()
    assert body["settings"]["diagnostic_size"] == 3
    assert body["ready"] is False and any("rated items" in m for m in body["missing"])
    with tenant_context(seeded_tenant.pk):
        template = StrategyTemplate.objects.get(pk=body["id"])
        assert AuditEvent.all_objects.filter(
            verb="strategy.template_created", target_id=template.pk).count() == 1


@pytest.mark.django_db
def test_a_name_is_needed_and_cannot_be_taken(ff, api, v3):
    assert post(api, ff, ROOT, {"name": " "}).status_code == 400
    assert post(api, ff, ROOT, {"name": "our SESSION"}).status_code == 409


# ============================================== isolation and role boundaries

@pytest.mark.django_db
def test_tenant_isolation_another_practices_template_is_not_found(v3, tenant_b, api):
    other = _member(tenant_b, "FF")
    before = fingerprint(v3)
    assert get(api, other, url(v3)).status_code == 404
    for verb, body in write_calls(v3):
        response = post(api, other, url(v3, verb), body)
        assert response.status_code == 404, verb
        assert str(v3.pk) not in response.content.decode() and "Our session" not in \
            response.content.decode()
    assert fingerprint(v3) == before, "and nothing in it changed"
    # Their own list never shows it, and a name taken here is free there.
    assert get(api, other, "/api/strategy-templates/").json() == []
    assert post(api, other, ROOT, {"name": "Our session"}).status_code == 201


@pytest.mark.django_db
def test_tenant_isolation_the_platform_owner_sees_no_template(v3, seeded_tenant, api):
    owner = _member(seeded_tenant, "FF")
    owner.user.is_platform_owner = True
    owner.user.save()
    client = in_practices_area(api.as_(owner))
    before = fingerprint(v3)
    response = client.get(url(v3))
    assert response.status_code in (403, 404)
    assert "Our session" not in response.content.decode()
    for verb, body in [("", {"name": "From outside"}), *write_calls(v3)]:
        path = ROOT if verb == "" else url(v3, verb)
        response = client.post(path, data=json.dumps(body),
                               content_type="application/json")
        assert response.status_code in (403, 404), verb
    assert fingerprint(v3) == before
    with tenant_context(seeded_tenant.pk):
        assert not StrategyTemplate.objects.filter(name="From outside").exists()


@pytest.mark.django_db
def test_role_boundaries_only_the_practice_owner_builds(v3, ff, cf, va, fcc, api):
    before = fingerprint(v3)
    for who in (cf, va):
        assert get(api, who, url(v3)).status_code == 200, "staff read, as the list"
        assert post(api, who, ROOT, {"name": "Theirs"}).status_code == 403
        for verb, body in write_calls(v3):
            assert post(api, who, url(v3, verb), body).status_code == 403, verb
    # A client has no route to a template at all.
    assert get(api, fcc, url(v3)).status_code == 404
    assert post(api, fcc, ROOT, {"name": "Theirs"}).status_code == 404
    for verb, body in write_calls(v3):
        assert post(api, fcc, url(v3, verb), body).status_code == 404, verb
    assert fingerprint(v3) == before
    assert not StrategyTemplate.objects.filter(name="Theirs").exists()
    # The practice owner can do every one of them.
    for verb, body in write_calls(v3):
        response = post(api, ff, url(v3, verb), body)
        assert response.status_code in (200, 201), (verb, response.content)
    assert fingerprint(v3) != before


@pytest.mark.django_db
def test_signed_out_there_is_nothing(v3, client):
    assert client.get(url(v3)).status_code in (401, 403)
    assert client.post(ROOT, data="{}", content_type="application/json").status_code \
        in (401, 403)


# ================================== the builder and the editor keep to their own

@pytest.mark.django_db
def test_the_builder_refuses_a_classic_and_a_focused_template(classic, focused, v3, ff,
                                                               api):
    calls = write_calls(v3)
    for template in (classic, focused):
        before = fingerprint(template)
        assert get(api, ff, url(template)).status_code == 409
        for verb, body in calls:
            response = post(api, ff, url(template, verb), body)
            assert response.status_code == 409, (template.name, verb)
            assert "template editor" in response.json()["detail"]
        assert fingerprint(template) == before
    # None of the builder's columns is set on either, ever.
    for template in (classic, focused):
        assert template.settings == {}
        assert not StrategySection.objects.filter(template=template).exclude(
            kind="", intro="", show_in_pdf=False, deleted_at__isnull=True).exists()
        assert not StrategyQuestion.objects.filter(template=template).exclude(
            label="", pdf_chip=False).exists()


@pytest.mark.django_db
def test_the_service_refuses_them_too(classic, focused):
    for template in (classic, focused):
        for call in (lambda t: builder.update_settings(t, {"diagnostic_size": 4}),
                     lambda t: builder.add_question(t, section="snapshot", prompt="x"),
                     lambda t: builder.set_included(t, kind="values", included=False),
                     lambda t: builder.update_section(t, code="diagnostic", title="x"),
                     lambda t: builder.duplicate(t, name="copy")):
            with pytest.raises(services.SessionError) as refused:
                call(template)
            assert refused.value.status == 409


@pytest.mark.django_db
def test_the_editors_question_verbs_refuse_a_builder_template(v3, ff, api):
    before = fingerprint(v3)
    base = f"/api/strategy-templates/{v3.pk}/"
    scope = list(StrategyQuestion.objects.filter(template=v3, section__kind="scope")
                 .values_list("key", flat=True))
    assert post(api, ff, base + "questions/", {
        "section": "six_key_components", "prompt": "What is your plan?",
        "response_schema": "free_text"}).status_code == 409
    assert post(api, ff, base + "remove-question/", {"key": scope[0]}).status_code == 409
    assert post(api, ff, base + "reorder/", {"section": "scope_agreement",
                                             "keys": scope[::-1]}).status_code == 409
    patch = api.as_(ff).patch(base, data=json.dumps({
        "questions": [{"key": scope[0], "ask_when": "precall"}]}),
        content_type="application/json")
    assert patch.status_code == 409
    assert fingerprint(v3) == before
    # Renaming, the default, archiving and duplicating are the same for all.
    renamed = api.as_(ff).patch(base, data=json.dumps({"name": "Renamed"}),
                                content_type="application/json")
    assert renamed.status_code == 200 and renamed.json()["template"]["name"] == "Renamed"


@pytest.mark.django_db
def test_duplicating_a_builder_template_gives_a_builder_template(v3, ff, api):
    make_ready(api, ff, v3)
    post(api, ff, url(v3, "settings/"), {"settings": {"diagnostic_size": 6}})
    post(api, ff, url(v3, "include/"), {"kind": "values", "included": False})
    made = post(api, ff, f"/api/strategy-templates/{v3.pk}/duplicate/", {"name": "Copy"})
    assert made.status_code == 201
    copy = StrategyTemplate.objects.get(name="Copy")
    assert copy.format == "v3" and copy.settings["diagnostic_size"] == 6
    assert builder.snapshot(copy)["sections"] == builder.snapshot(v3)["sections"]
    assert builder.represent(copy)["ready"]
    assert not sections_of(builder.represent(copy))["values"]["included"]
    # The copy is its own: editing it leaves the original alone.
    before = fingerprint(v3)
    assert add(api, ff, copy, "snapshot", "A new one").status_code == 201
    assert fingerprint(v3) == before


@pytest.mark.django_db
def test_a_classic_and_a_focused_snapshot_gain_no_key(classic, focused, v3):
    for template in (classic, focused):
        snap = services.snapshot_of(template)
        assert snap["snapshot_version"] == 1
        assert "settings" not in snap["template"]
        for section in snap["sections"]:
            assert not V3_ONLY_SECTION_KEYS & set(section), section["code"]
            for question in section["questions"]:
                assert not V3_ONLY_QUESTION_KEYS & set(question)


@pytest.mark.django_db
def test_the_template_list_marks_only_a_builder_template(classic, v3, ff, va, api):
    rows = {row["name"]: row for row in get(api, va, "/api/strategy-templates/").json()}
    assert rows["Our session"]["format"] == "v3" and rows["Our session"]["ready"] is False
    assert rows["Our session"]["missing"]
    assert not {"format", "ready", "missing"} & set(rows[seed.TEMPLATE_NAME])


# ======================================================== what each part holds

@pytest.mark.django_db
def test_each_part_gives_its_questions_one_shape(v3, ff, api):
    expected = {
        "snapshot": ("free_text", "precall"),
        "diagnostic": ("diagnostic_triple", "live"),
        "mirror": ("free_text", "live"),
        "what_they_value": ("value_pair", "live"),
        "scope_agreement": ("agreed_note", "live"),
    }
    for code, (schema, when) in expected.items():
        made = add(api, ff, v3, code, f"Something for {code}",
                   # The caller does not get to choose the shape.
                   response_schema="rating_1_10", ask_when="precall")
        assert made.status_code == 201, (code, made.content)
        section = next(s for s in made.json()["sections"] if s["code"] == code)
        question = section["questions"][-1]
        assert (question["response_schema"], question["ask_when"]) == (schema, when), code
    fallback = StrategyQuestion.objects.get(template=v3, section__kind="diagnostic")
    assert fallback.is_diagnostic_fallback and fallback.has_fractional_note
    # The map holds rows, not questions; and there are always two paths.
    assert add(api, ff, v3, "strategy_map", "A question").status_code == 400
    assert add(api, ff, v3, "two_paths", "Path C").status_code == 400
    path = StrategyQuestion.objects.filter(template=v3, section__kind="paths").first()
    assert post(api, ff, url(v3, "remove-question/"), {"key": path.key}).status_code == 400
    assert post(api, ff, url(v3, "question/"), {
        "key": path.key, "prompt": "Path A — Keep going alone"}).status_code == 200
    assert add(api, ff, v3, "no_such_section", "A question").status_code == 404


@pytest.mark.django_db
def test_a_part_holds_only_so_many(v3, ff, api):
    for n in range(8):
        assert add(api, ff, v3, "six_key_components", f"Item {n} — It is in place.",
                   label=f"Item {n}").status_code == 201
    refused = add(api, ff, v3, "six_key_components", "Item 9 — It is in place.",
                  label="Item 9")
    assert refused.status_code == 400 and "8 at most" in refused.json()["detail"]
    # Removing one makes room, and its key is never used again.
    first = StrategyQuestion.objects.filter(template=v3, section__kind="ratings").order_by(
        "position").first()
    assert post(api, ff, url(v3, "remove-question/"), {"key": first.key}).status_code == 200
    again = add(api, ff, v3, "six_key_components", "Item 9 — It is in place.",
                label="Item 9")
    assert again.status_code == 201
    keys = list(StrategyQuestion.objects.filter(template=v3, section__kind="ratings")
                .values_list("key", flat=True))
    assert len(keys) == len(set(keys)) == 9 and first.key in keys, "archived, key spent"


@pytest.mark.django_db
def test_a_rated_item_is_a_statement_with_a_label(v3, ff, api):
    no_label = add(api, ff, v3, "six_key_components", "Plan — Our plan is written down.")
    assert no_label.status_code == 400 and "label" in no_label.json()["detail"]
    essay = add(api, ff, v3, "six_key_components", "What does your plan look like?",
                label="Plan")
    assert essay.status_code == 400 and "rated 1–10" in essay.json()["detail"]
    long = add(api, ff, v3, "six_key_components", "Plan — " + "x" * 130, label="Plan")
    assert long.status_code == 400
    assert not StrategyQuestion.objects.filter(template=v3, section__kind="ratings").exists()
    good = add(api, ff, v3, "six_key_components", "Plan — Our plan is written down.",
               label="Plan")
    assert good.status_code == 201
    question = StrategyQuestion.objects.get(template=v3, section__kind="ratings")
    assert question.label == "Plan" and question.response_schema == "rating_1_10"
    # The rule holds on an edit as well: the wording, and losing the label.
    assert post(api, ff, url(v3, "question/"), {
        "key": question.key, "prompt": "How good is the plan?"}).status_code == 400
    assert post(api, ff, url(v3, "question/"), {
        "key": question.key, "label": ""}).status_code == 400
    question.refresh_from_db()
    assert question.prompt == "Plan — Our plan is written down." and question.label == "Plan"
    assert add(api, ff, v3, "six_key_components", "Team — The seats are filled.",
               label="Team", must_ask=True).status_code == 400, "a rating is not a must-ask"


@pytest.mark.django_db
def test_the_pdf_header_takes_three_labelled_precall_answers(v3, ff, api):
    assert add(api, ff, v3, "snapshot", "Revenue last year?", pdf_chip=True) \
        .status_code == 400, "a chip needs a label"
    assert add(api, ff, v3, "mirror", "Where to?", label="Goal", pdf_chip=True) \
        .status_code == 400, "only a pre-call question"
    for label in ("Revenue", "Team", "Customers"):
        assert add(api, ff, v3, "snapshot", f"{label}?", label=label,
                   pdf_chip=True).status_code == 201
    fourth = add(api, ff, v3, "snapshot", "Sites?", label="Sites", pdf_chip=True)
    assert fourth.status_code == 400 and "3 answers at most" in fourth.json()["detail"]
    plain = add(api, ff, v3, "snapshot", "Sites?", label="Sites")
    assert plain.status_code == 201
    sites = StrategyQuestion.objects.get(template=v3, label="Sites")
    assert post(api, ff, url(v3, "question/"), {"key": sites.key, "pdf_chip": True}) \
        .status_code == 400
    team = StrategyQuestion.objects.get(template=v3, label="Team")
    assert post(api, ff, url(v3, "question/"), {"key": team.key, "pdf_chip": False}) \
        .status_code == 200
    assert post(api, ff, url(v3, "question/"), {"key": sites.key, "pdf_chip": True}) \
        .status_code == 200
    assert sorted(StrategyQuestion.objects.filter(template=v3, pdf_chip=True)
                  .values_list("label", flat=True)) == ["Customers", "Revenue", "Sites"]


@pytest.mark.django_db
def test_money_is_a_scope_item_and_nothing_else(v3, ff, api):
    assert add(api, ff, v3, "snapshot", "Budget?", is_financial=True).status_code == 400
    made = add(api, ff, v3, "scope_agreement", "Their reaction to the range",
               is_financial=True)
    assert made.status_code == 201
    assert StrategyQuestion.objects.filter(template=v3, is_financial=True).count() == 2


@pytest.mark.django_db
def test_reordering_and_section_edits(v3, ff, api):
    keys = list(StrategyQuestion.objects.filter(template=v3, section__kind="scope")
                .order_by("position").values_list("key", flat=True))
    moved = post(api, ff, url(v3, "reorder/"), {"section": "scope_agreement",
                                                "keys": keys[::-1]})
    assert moved.status_code == 200
    assert [q["key"] for q in sections_of(moved.json())["scope"]["questions"]] == keys[::-1]
    assert post(api, ff, url(v3, "reorder/"), {"section": "scope_agreement",
                                               "keys": keys[:2]}).status_code == 400
    edited = post(api, ff, url(v3, "section/"), {"code": "six_key_components",
                                                 "title": "Five things that matter",
                                                 "time_budget_minutes": 8})
    assert edited.status_code == 200
    ratings = sections_of(edited.json())["ratings"]
    assert (ratings["title"], ratings["time_budget_minutes"]) == \
        ("Five things that matter", 8)
    assert ratings["code"] == "six_key_components", "the code is not the practice's to change"
    assert post(api, ff, url(v3, "section/"), {"code": "diagnostic",
                                               "title": " "}).status_code == 400
    assert post(api, ff, url(v3, "section/"), {"code": "snapshot",
                                               "time_budget_minutes": 5}).status_code == 400
    assert post(api, ff, url(v3, "section/"), {"code": "diagnostic",
                                               "time_budget_minutes": 999}).status_code == 400


# ===================================================== what they value, on / off

@pytest.mark.django_db
def test_what_they_value_can_be_switched_off_and_back_on(v3, ff, api):
    assert add(api, ff, v3, "what_they_value", "Value 1 — and why").status_code == 201
    key = StrategyQuestion.objects.get(template=v3, section__kind="values").key
    off = post(api, ff, url(v3, "include/"), {"kind": "values", "included": False})
    assert off.status_code == 200
    values = sections_of(off.json())["values"]
    assert values["included"] is False and values["optional"] is True
    assert "what_they_value" not in [s["code"] for s in builder.snapshot(v3)["sections"]]
    assert add(api, ff, v3, "what_they_value", "Value 2").status_code == 404
    assert post(api, ff, url(v3, "question/"), {"key": key, "prompt": "x"}).status_code == 404
    on = post(api, ff, url(v3, "include/"), {"kind": "values", "included": True})
    assert [q["key"] for q in sections_of(on.json())["values"]["questions"]] == [key], \
        "back as it was"
    # Only that part, in the first cut (D1).
    for kind in ("ratings", "diagnostic", "mirror", "map", "paths", "scope", "precall", ""):
        assert post(api, ff, url(v3, "include/"), {"kind": kind, "included": False}) \
            .status_code == 400, kind
    assert post(api, ff, url(v3, "include/"), {"kind": "values",
                                               "included": "no"}).status_code == 400


# ==================================================================== settings

@pytest.mark.django_db
def test_settings_are_a_fixed_list_validated_on_save(v3, ff, api):
    def save(**settings):
        return post(api, ff, url(v3, "settings/"), {"settings": settings})

    good = save(advisor_role="  business   consultant ", diagnostic_size=5,
                path_b_title="Work with {Practice} and {Fractional name}",
                path_a_points=["Keep the map", "Your team carries it"])
    assert good.status_code == 200
    saved = good.json()["settings"]
    assert saved["advisor_role"] == "business consultant" and saved["diagnostic_size"] == 5
    assert saved["path_a_points"] == ["Keep the map", "Your team carries it"]
    assert saved["rating_scale"] == builder.default_settings()["rating_scale"], \
        "what was not sent keeps its value"
    before = fingerprint(v3)
    for bad in (dict(colour="red"), dict(advisor_role=""), dict(advisor_role="x" * 81),
                dict(path_a_points=["only one"]), dict(path_a_points=["one", ""]),
                dict(path_b_points="two lines"), dict(rating_scale="Ask {Nobody}"),
                dict(diagnostic_size=0), dict(diagnostic_size=9),
                dict(diagnostic_size="3"), dict(diagnostic_size=True),
                dict(diagnostic_size=2.5)):
        assert save(**bad).status_code == 400, bad
    assert post(api, ff, url(v3, "settings/"), {"settings": "x"}).status_code == 400
    assert fingerprint(v3) == before, "a refused save changes nothing"
    for size in (1, 8):
        assert save(diagnostic_size=size).json()["settings"]["diagnostic_size"] == size


@pytest.mark.django_db
def test_an_unknown_merge_field_is_refused_in_a_question(v3, ff, api):
    bad = add(api, ff, v3, "snapshot", "How long has {Founder} run {Company}?")
    assert bad.status_code == 400 and "{Founder}" in bad.json()["detail"]
    assert "{Company}" in bad.json()["detail"], "and it lists the ones that exist"
    good = add(api, ff, v3, "snapshot", "How long has {Visionary} run {Company}?")
    assert good.status_code == 201
    key = sections_of(good.json())["precall"]["questions"][0]["key"]
    assert post(api, ff, url(v3, "question/"), {
        "key": key, "prompt": "Who is {The Boss}?"}).status_code == 400


# ======================================================= ready to run, and Start

@pytest.mark.django_db
def test_a_template_that_is_not_ready_cannot_start_a_session(v3, ff, api, seeded_tenant):
    contact = ContactFactory(tenant=seeded_tenant, first_name="Dana", last_name="Reyes")
    start = {"contact": str(contact.pk), "template": str(v3.pk)}
    refused = post(api, ff, "/api/strategy-sessions/", start)
    assert refused.status_code == 409
    assert "not ready to run" in refused.json()["detail"]
    assert "at least 2 rated items" in refused.json()["detail"]
    assert not StrategySession.objects.exists()
    assert add(api, ff, v3, "six_key_components", "Plan — It is written down.",
               label="Plan").status_code == 201
    assert get(api, ff, url(v3)).json()["ready"] is False, "one is not two"
    assert post(api, ff, "/api/strategy-sessions/", start).status_code == 409
    assert add(api, ff, v3, "six_key_components", "Team — The seats are filled.",
               label="Team").status_code == 201
    ready = get(api, ff, url(v3)).json()
    assert ready["ready"] is True and ready["missing"] == []
    assert post(api, ff, "/api/strategy-sessions/", start).status_code == 201


@pytest.mark.django_db
def test_a_session_freezes_the_v3_template(v3, ff, api, seeded_tenant):
    make_ready(api, ff, v3)
    add(api, ff, v3, "snapshot", "Revenue last year?", label="Revenue", pdf_chip=True)
    add(api, ff, v3, "what_they_value", "Value 1 — and why")
    post(api, ff, url(v3, "settings/"), {"settings": {"advisor_role": "business consultant",
                                                      "diagnostic_size": 4}})
    contact = ContactFactory(tenant=seeded_tenant, first_name="Dana", last_name="Reyes")
    made = post(api, ff, "/api/strategy-sessions/",
                {"contact": str(contact.pk), "template": str(v3.pk)})
    assert made.status_code == 201 and made.json()["format"] == "v3"
    session = StrategySession.objects.get(pk=made.json()["id"])
    snap = session.template_snapshot
    assert snap["snapshot_version"] == 2
    assert snap["template"]["format"] == "v3"
    assert snap["template"]["settings"]["advisor_role"] == "business consultant"
    assert snap["template"]["settings"]["diagnostic_size"] == 4
    assert [s["kind"] for s in snap["sections"]] == list(builder.KINDS)
    rated = next(s for s in snap["sections"] if s["kind"] == "ratings")["questions"]
    assert [(q["label"], q["response_schema"], q["ask_when"]) for q in rated] == [
        ("Plan", "rating_1_10", "live"), ("People", "rating_1_10", "live")]
    chip = next(s for s in snap["sections"] if s["kind"] == "precall")["questions"][0]
    assert chip["pdf_chip"] is True and chip["label"] == "Revenue"

    # Nothing done to the template afterwards reaches the session (FR-4.5).
    frozen = json.dumps(snap, sort_keys=True)
    post(api, ff, url(v3, "include/"), {"kind": "values", "included": False})
    post(api, ff, url(v3, "settings/"), {"settings": {"advisor_role": "coach"}})
    post(api, ff, url(v3, "remove-question/"), {"key": chip["key"]})
    post(api, ff, url(v3, "section/"), {"code": "diagnostic", "title": "Changed"})
    session.refresh_from_db()
    assert json.dumps(session.template_snapshot, sort_keys=True) == frozen
    # And the next session takes the template as it now is.
    after = post(api, ff, "/api/strategy-sessions/",
                 {"contact": str(contact.pk), "template": str(v3.pk)}).json()
    later = StrategySession.objects.get(pk=after["id"]).template_snapshot
    assert "values" not in [s["kind"] for s in later["sections"]]
    assert later["template"]["settings"]["advisor_role"] == "coach"


@pytest.mark.django_db
def test_making_a_builder_template_leaves_the_practice_default_alone(focused, ff, api,
                                                                      seeded_tenant):
    seed.create_focused(seeded_tenant)                 # the default, as in production
    made = post(api, ff, ROOT, {"name": "Ours"}).json()
    make_ready(api, ff, StrategyTemplate.objects.get(pk=made["id"]))
    contact = ContactFactory(tenant=seeded_tenant)
    session = post(api, ff, "/api/strategy-sessions/", {"contact": str(contact.pk)}).json()
    assert session["format"] == "focused" and session["template"]["name"] == seed.FOCUSED_NAME


# ============================================================ D3: the seed

@pytest.mark.django_db
def test_a_practice_never_given_the_seed_cannot_restore_from_it(ff, api, seeded_tenant,
                                                                in_tenant_a):
    assert not StrategyTemplate.objects.exists()
    refused = post(api, ff, "/api/strategy-templates/restore-from-seed/", {"name": "Ops"})
    assert refused.status_code == 403 and "builds its own" in refused.json()["detail"]
    # Having built its own does not open the seed either.
    post(api, ff, ROOT, {"name": "Ours"})
    assert post(api, ff, "/api/strategy-templates/restore-from-seed/",
                {"name": "Ops"}).status_code == 403
    assert list(StrategyTemplate.objects.values_list("name", flat=True)) == ["Ours"]


@pytest.mark.django_db
def test_a_practice_that_has_the_seed_keeps_restore_from_seed(classic, ff, api):
    made = post(api, ff, "/api/strategy-templates/restore-from-seed/", {"name": "Ops again"})
    assert made.status_code == 201
