"""P3 part two — sections of a practice's own in the builder.

1. Add, move, remove and put back; what a custom section holds.
2. Practice isolation and role boundaries on every new verb.
3. A session: the frozen snapshot, the live payload, Claude's input, the PDF.
"""

from __future__ import annotations

import json

import pytest

from apps.strategy import builder, pdf, services, v3
from apps.strategy.models import StrategyQuestion, StrategySection, StrategySession
from apps.tenancy.context import tenant_context
from apps.tenancy.models import AuditEvent

from . import registry_config  # noqa: F401
from .conftest import _member
from .test_platform_isolation import in_practices_area
from .test_strategy_builder import (  # noqa: F401  (fixtures)
    ROOT, classic, fingerprint, focused, get, post, sections_of, url,
)
from .test_strategy_builder import v3 as blank  # noqa: F401  (fixture)
from .test_strategy_v3_pdf import run
from .test_strategy_v3_session import (  # noqa: F401  (fixtures)
    answer, base, build, prospect, template,
)

LIVE = ["six_key_components", "diagnostic", "mirror", "strategy_map", "what_they_value",
        "two_paths", "scope_agreement"]


def order(payload):
    return [section["code"] for section in payload["sections"]]


def add_section(api, who, template, title="Leadership bench", **more):
    return post(api, who, url(template, "sections/"), {"title": title, **more})


def custom(payload, title="Leadership bench"):
    return next(s for s in payload["sections"] if s["title"] == title)


def full_fingerprint(template):
    """`fingerprint`, plus the order of sections and what prints."""
    with tenant_context(template.tenant_id):
        return fingerprint(template) + json.dumps(list(
            StrategySection.objects.filter(template=template).order_by("position")
            .values_list("code", "position", "show_in_pdf")))


# ========================================================== adding a section

@pytest.mark.django_db
def test_a_section_of_your_own_is_added_last_empty_and_off_the_document(blank, ff, api):
    made = add_section(api, ff, blank, "  Leadership   bench ", time_budget_minutes=10)
    assert made.status_code == 201
    body = made.json()
    section = body["sections"][-1]
    assert section["code"].startswith("custom_") and len(section["code"]) == 15
    assert order(body) == ["snapshot", *LIVE, section["code"]]
    assert (section["kind"], section["title"], section["time_budget_minutes"]) == (
        "custom", "Leadership bench", 10)
    assert section["questions"] == [] and section["most"] == 12
    assert section["show_in_pdf"] is False and section["included"] and section["optional"]
    assert section["schemas"] == ["free_text", "diagnostic_triple", "agreed_note"]
    # The eight parts' entries are as they were.
    assert all("custom" not in s and "schemas" not in s for s in body["sections"][:-1])
    event = AuditEvent.all_objects.get(verb="strategy.template_section_added",
                                       target_id=blank.pk)
    assert event.payload == {"code": section["code"], "title": "Leadership bench"}
    # It changes nothing about whether the template can run.
    assert body["missing"] == builder.readiness(blank)


@pytest.mark.django_db
def test_a_section_goes_after_the_part_named(blank, ff, api):
    first = add_section(api, ff, blank, "After the ratings", after="six_key_components").json()
    code = custom(first, "After the ratings")["code"]
    assert order(first)[:3] == ["snapshot", "six_key_components", code]
    # After the part before the call is first on the call.
    second = add_section(api, ff, blank, "Opening", after="snapshot").json()
    assert order(second)[:2] == ["snapshot", custom(second, "Opening")["code"]]
    assert add_section(api, ff, blank, "Nowhere", after="no_such").status_code == 404


@pytest.mark.django_db
def test_a_section_needs_a_title_and_a_template_holds_eight_of_your_own(blank, ff, api):
    assert add_section(api, ff, blank, " ").status_code == 400
    assert add_section(api, ff, blank, "x" * 256).status_code == 400
    assert add_section(api, ff, blank, "T", time_budget_minutes=999).status_code == 400
    with tenant_context(blank.tenant_id):
        assert not StrategySection.objects.filter(template=blank, kind="custom").exists(), \
            "a refused budget leaves no section behind"
    for n in range(8):
        assert add_section(api, ff, blank, f"Section {n}").status_code == 201
    refused = add_section(api, ff, blank, "A ninth")
    assert refused.status_code == 400 and "8 sections of your own" in refused.json()["detail"]


@pytest.mark.django_db
def test_a_custom_question_takes_one_of_three_kinds_of_answer(blank, ff, api):
    code = custom(add_section(api, ff, blank).json())["code"]
    add = lambda prompt, **more: post(api, ff, url(blank, "questions/"),  # noqa: E731
                                      {"section": code, "prompt": prompt, **more})
    assert add("Who is on the leadership team?").status_code == 201
    assert add("Where does hiring stall?", response_schema="diagnostic_triple",
               must_ask=True).status_code == 201
    done = add("Org chart shared", response_schema="agreed_note")
    assert done.status_code == 201
    asked = custom(done.json())["questions"]
    assert [(q["response_schema"], q["must_ask"]) for q in asked] == [
        ("free_text", False), ("diagnostic_triple", True), ("agreed_note", False)]
    for question in asked:
        assert question["ask_when"] == "live" and question["has_fractional_note"]
        assert not question["is_diagnostic_fallback"] and not question["is_financial"]
        assert question["key"].startswith(code)
    # No rating, value, path or money item, and nothing for the PDF header.
    for refused in ({"response_schema": "rating_1_10"}, {"response_schema": "value_pair"},
                    {"response_schema": "path_reaction"}, {"is_financial": True},
                    {"pdf_chip": True, "label": "Team"}):
        assert add("Not here", **refused).status_code == 400, refused
    assert len(custom(get(api, ff, url(blank)).json())["questions"]) == 3


@pytest.mark.django_db
def test_a_custom_section_holds_twelve_questions(blank, ff, api):
    code = custom(add_section(api, ff, blank).json())["code"]
    lines = [f"Question {n}" for n in range(1, 14)]
    shown = post(api, ff, url(blank, "paste/"),
                 {"section": code, "text": "\n".join(lines)}).json()
    assert [line["ok"] for line in shown["lines"]] == [True] * 12 + [False]
    assert "holds 12 at most" in shown["lines"][12]["why"]


# ================================================================== moving

@pytest.mark.django_db
def test_any_section_on_the_call_moves_up_and_down_and_the_first_part_stays(blank, ff, api):
    move = lambda code, by: post(api, ff, url(blank, "move-section/"),  # noqa: E731
                                 {"code": code, "by": by})
    up = move("diagnostic", -1)
    assert up.status_code == 200
    assert order(up.json())[:3] == ["snapshot", "diagnostic", "six_key_components"]
    # The map, the paths and the scope move like any other.
    assert order(move("scope_agreement", -1).json())[-2:] == ["scope_agreement", "two_paths"]
    assert order(move("strategy_map", 1).json())[4:6] == ["what_they_value", "strategy_map"]
    # Already first on the call, already last, and the part before the call.
    before = full_fingerprint(blank)
    for code, by in (("diagnostic", -1), ("two_paths", 1), ("snapshot", 1),
                     ("snapshot", -1), ("diagnostic", 2), ("diagnostic", "up"),
                     ("no_such", 1)):
        assert move(code, by).status_code in (400, 404), (code, by)
    assert full_fingerprint(blank) == before
    assert AuditEvent.all_objects.filter(verb="strategy.template_section_moved",
                                         target_id=blank.pk).count() == 3


@pytest.mark.django_db
def test_moving_steps_over_a_section_that_is_out(blank, ff, api):
    post(api, ff, url(blank, "include/"), {"kind": "values", "included": False})
    moved = post(api, ff, url(blank, "move-section/"), {"code": "two_paths", "by": -1})
    live = [s["code"] for s in moved.json()["sections"] if s["included"]]
    assert live[-3:] == ["two_paths", "strategy_map", "scope_agreement"]


# ================================================= removing and putting back

@pytest.mark.django_db
def test_a_removed_section_keeps_its_questions_and_comes_back_with_them(blank, ff, api):
    code = custom(add_section(api, ff, blank).json())["code"]
    key = custom(post(api, ff, url(blank, "questions/"),
                      {"section": code, "prompt": "Who decides?"}).json())["questions"][0]["key"]
    out = post(api, ff, url(blank, "include/"), {"code": code, "included": False})
    assert out.status_code == 200
    gone = custom(out.json())
    assert gone["included"] is False and gone["questions"] == []
    assert code not in [s["code"] for s in builder.snapshot(blank)["sections"]]
    # Its questions cannot be added to or edited while it is out.
    assert post(api, ff, url(blank, "questions/"),
                {"section": code, "prompt": "Another"}).status_code == 404
    assert post(api, ff, url(blank, "question/"),
                {"key": key, "prompt": "Changed"}).status_code == 404
    back = post(api, ff, url(blank, "include/"), {"code": code, "included": True})
    assert [q["key"] for q in custom(back.json())["questions"]] == [key]
    with tenant_context(blank.tenant_id):
        assert StrategyQuestion.objects.get(key=key).deleted_at is None


@pytest.mark.django_db
def test_only_your_own_sections_and_what_they_value_can_be_taken_out(blank, ff, api):
    before = full_fingerprint(blank)
    for code in ("strategy_map", "snapshot", "six_key_components", "diagnostic", "mirror",
                 "two_paths", "scope_agreement"):
        refused = post(api, ff, url(blank, "include/"), {"code": code, "included": False})
        assert refused.status_code == 400, code
    assert post(api, ff, url(blank, "include/"),
                {"code": "no_such", "included": False}).status_code == 404
    assert full_fingerprint(blank) == before
    # What they value still goes out by its kind, as before, and by its code.
    assert post(api, ff, url(blank, "include/"),
                {"kind": "values", "included": False}).status_code == 200
    assert post(api, ff, url(blank, "include/"),
                {"code": "what_they_value", "included": True}).status_code == 200


@pytest.mark.django_db
def test_putting_back_respects_the_limit_of_eight(blank, ff, api):
    first = custom(add_section(api, ff, blank, "First").json(), "First")["code"]
    post(api, ff, url(blank, "include/"), {"code": first, "included": False})
    for n in range(8):
        add_section(api, ff, blank, f"Section {n}")
    refused = post(api, ff, url(blank, "include/"), {"code": first, "included": True})
    assert refused.status_code == 400 and "8 sections" in refused.json()["detail"]


# =========================================================== the document

@pytest.mark.django_db
def test_the_document_takes_two_of_your_sections_of_four_questions(blank, ff, api):
    codes = [custom(add_section(api, ff, blank, f"S{n}").json(), f"S{n}")["code"]
             for n in range(3)]
    show = lambda code, on=True: post(api, ff, url(blank, "section/"),  # noqa: E731
                                      {"code": code, "show_in_pdf": on})
    for n in range(5):
        post(api, ff, url(blank, "questions/"), {"section": codes[0], "prompt": f"Q{n}"})
    too_many = show(codes[0])
    assert too_many.status_code == 400 and "room for 4 questions" in too_many.json()["detail"]
    assert show(codes[1]).status_code == 200 and show(codes[2]).status_code == 200
    third = post(api, ff, url(blank, "section/"), {"code": codes[0], "show_in_pdf": True})
    assert third.status_code == 400
    # A printing section stops at four questions.
    for n in range(4):
        assert post(api, ff, url(blank, "questions/"),
                    {"section": codes[1], "prompt": f"P{n}"}).status_code == 201
    fifth = post(api, ff, url(blank, "questions/"), {"section": codes[1], "prompt": "P4"})
    assert fifth.status_code == 400 and "prints on the document" in fifth.json()["detail"]
    assert show(codes[1], False).status_code == 200
    assert post(api, ff, url(blank, "questions/"),
                {"section": codes[1], "prompt": "P4"}).status_code == 201
    # Not a switch on the eight parts, and not a word.
    assert show("diagnostic").status_code == 400
    assert show("diagnostic", False).status_code == 400
    assert show(codes[2], "yes").status_code == 400


# ============================================== isolation and role boundaries

def section_calls(code):
    return [
        ("sections/", {"title": "Theirs"}),
        ("move-section/", {"code": code, "by": -1}),
        ("section/", {"code": code, "show_in_pdf": True}),
        ("section/", {"code": code, "title": "Renamed"}),
        ("questions/", {"section": code, "prompt": "Theirs", "response_schema": "agreed_note"}),
        ("include/", {"code": code, "included": False}),
    ]


@pytest.mark.django_db
def test_tenant_isolation_another_practice_cannot_touch_a_templates_sections(
        blank, ff, tenant_b, api):
    code = custom(add_section(api, ff, blank).json())["code"]
    other = _member(tenant_b, "FF")
    before = full_fingerprint(blank)
    for verb, body in section_calls(code):
        response = post(api, other, url(blank, verb), body)
        assert response.status_code == 404, verb
        assert "Leadership bench" not in response.content.decode()
    assert full_fingerprint(blank) == before
    # A code from here means nothing in their own template.
    theirs = post(api, other, ROOT, {"name": "Theirs"}).json()
    for verb, body in section_calls(code)[1:]:
        assert post(api, other, f"{ROOT}{theirs['id']}/{verb}", body).status_code == 404, verb


@pytest.mark.django_db
def test_tenant_isolation_the_platform_owner_cannot_touch_sections(blank, ff, seeded_tenant,
                                                                   api):
    code = custom(add_section(api, ff, blank).json())["code"]
    owner = _member(seeded_tenant, "FF")
    owner.user.is_platform_owner = True
    owner.user.save()
    client = in_practices_area(api.as_(owner))
    before = full_fingerprint(blank)
    for verb, body in section_calls(code):
        response = client.post(url(blank, verb), data=json.dumps(body),
                               content_type="application/json")
        assert response.status_code in (403, 404), verb
    assert full_fingerprint(blank) == before


@pytest.mark.django_db
def test_role_boundaries_only_the_practice_owner_changes_sections(blank, ff, cf, va, fcc,
                                                                  api):
    code = custom(add_section(api, ff, blank).json())["code"]
    before = full_fingerprint(blank)
    for who, status in ((cf, 403), (va, 403), (fcc, 404)):
        for verb, body in section_calls(code):
            assert post(api, who, url(blank, verb), body).status_code == status, verb
    assert full_fingerprint(blank) == before, "the rows are unchanged"
    # Staff read it, as they read the rest of the template.
    assert custom(get(api, va, url(blank)).json())["kind"] == "custom"
    for verb, body in section_calls(code):
        assert post(api, ff, url(blank, verb), body).status_code in (200, 201), verb


@pytest.mark.django_db
def test_a_classic_or_focused_template_takes_no_section_verbs(classic, focused, ff, api):
    for seeded in (classic, focused):
        before = fingerprint(seeded)
        for verb, body in section_calls("diagnostic"):
            assert post(api, ff, url(seeded, verb), body).status_code == 409, verb
        assert fingerprint(seeded) == before
        with tenant_context(seeded.tenant_id):
            assert not StrategySection.objects.filter(template=seeded,
                                                      kind="custom").exists()


# ================================================================ a session

@pytest.fixture
def with_custom(template):
    """The v3 session tests' template, with a section of the practice's own
    after the diagnostic, holding one of each kind of answer."""
    section = builder.add_section(template, title="Leadership bench", time_budget_minutes=5,
                                  after="diagnostic")
    builder.add_question(template, section=section.code, prompt="Who runs {Company} day to day?")
    builder.add_question(template, section=section.code, prompt="Where does hiring stall?",
                         response_schema="diagnostic_triple")
    builder.add_question(template, section=section.code, prompt="Org chart shared",
                         response_schema="agreed_note")
    return section


@pytest.fixture
def session(seeded_tenant, template, with_custom, prospect, ff):
    return services.start(tenant=seeded_tenant, contact=prospect, template=template,
                          owner=ff.user)


def custom_keys(session):
    section = next(s for s in session.template_snapshot["sections"] if s["kind"] == "custom")
    return [q["key"] for q in section["questions"]]


def fill(session):
    written, triple, agreed = custom_keys(session)
    answer(session, written, {"text": "CUSTOM-WRITTEN Jen, since March"},
           note="CUSTOM-PRIVATE-NOTE")
    answer(session, triple, {"said": "CUSTOM-SAID", "cause": "CUSTOM-CAUSE",
                             "tried": "CUSTOM-TRIED"})
    answer(session, agreed, {"agreed": True, "notes": "CUSTOM-AGREED by Friday"})


@pytest.mark.django_db
def test_the_session_freezes_the_section_and_later_changes_never_reach_it(
        session, template, with_custom, ff, api):
    frozen = json.loads(json.dumps(session.template_snapshot))
    assert [s["code"] for s in frozen["sections"]][:4] == [
        "snapshot", "six_key_components", "diagnostic", with_custom.code]
    section = frozen["sections"][3]
    assert (section["kind"], section["title"], section["show_in_pdf"]) == (
        "custom", "Leadership bench", False)
    # Renamed, moved, printed, added to, and taken out, after the session began.
    for verb, body in (("section/", {"code": with_custom.code, "title": "Changed"}),
                       ("move-section/", {"code": with_custom.code, "by": -1}),
                       ("section/", {"code": with_custom.code, "show_in_pdf": True}),
                       ("sections/", {"title": "Another"}),
                       ("include/", {"code": with_custom.code, "included": False})):
        assert post(api, ff, url(template, verb), body).status_code in (200, 201), verb
    assert StrategySession.objects.get(pk=session.pk).template_snapshot == frozen


@pytest.mark.django_db
def test_the_live_view_asks_the_section_in_the_templates_order(session, with_custom, ff, va,
                                                               api):
    fill(session)
    for who in (ff, va):
        payload = api.as_(who).get(base(session)).json()
        codes = [s["code"] for s in payload["sections"]]
        assert codes.index(with_custom.code) == codes.index("diagnostic") + 1
        section = payload["sections"][codes.index(with_custom.code)]
        assert section["time_budget_minutes"] == 5
        assert [q["response_schema"] for q in section["questions"]] == [
            "free_text", "diagnostic_triple", "agreed_note"]
        assert section["questions"][0]["prompt"] == "Who runs Acme Facilities day to day?"
        saved = {a["question_key"]: a for a in payload["answers"]}
        assert saved[custom_keys(session)[0]]["value"]["text"].startswith("CUSTOM-WRITTEN")
    # Answered through the API like any other question.
    done = post(api, ff, base(session) + "answers/",
                {"question_key": custom_keys(session)[0], "value": {"text": "Jen"},
                 "fractional_note": "Private"})
    assert done.status_code in (200, 201), done.content


@pytest.mark.django_db
def test_a_custom_section_is_not_on_the_form_or_in_the_email_and_not_rated(session, client):
    from apps.strategy import emails

    fill(session)
    token = services.issue_precall_token(session)
    form = client.get(f"/api/strategy/precall/{token}").content.decode()
    text, html = emails._questions_body(session, emails.default_intro(session))
    body = json.dumps(emails.question_blocks(session), default=str) + text + html
    assert "What does Acme Facilities sell" in form and "What does Acme Facilities sell" in body
    for private in ("Leadership bench", "Who runs", "hiring stall", "Org chart", "custom"):
        assert private not in form and private not in body, private
    assert all(row["label"] in ("Plan", "Team", "Numbers") for row in v3.ratings(session))


@pytest.mark.django_db
def test_claude_reads_nothing_from_a_custom_section(session):
    """Captured and nothing else: the switch that lets Claude read one is not
    built, so no custom answer reaches the input the rows, the mirror and the
    pros and cons are drafted from."""
    run(session)
    fill(session)
    drafted_from = v3.drafting_input(session)
    assert "Pricing waits for Dana" in drafted_from, "the diagnostic is still read"
    assert "CUSTOM-" not in drafted_from and "Leadership bench" not in drafted_from


@pytest.mark.django_db
def test_a_custom_section_prints_only_when_marked_and_only_what_may_print(
        session, template, with_custom, ff, seeded_tenant, prospect):
    run(session)
    fill(session)
    html = pdf.render_html(session)
    assert "CUSTOM-" not in html and "Leadership bench" not in html, "off the document by default"

    builder.update_section(template, code=with_custom.code, show_in_pdf=True)
    assert "CUSTOM-" not in pdf.render_html(session), "a session keeps what it started with"
    printing = services.start(tenant=seeded_tenant, contact=prospect, template=template,
                              owner=ff.user)
    run(printing)
    fill(printing)
    html = pdf.render_html(printing)
    assert "Leadership bench" in html and "Who runs Acme Facilities day to day?" in html
    assert "CUSTOM-WRITTEN Jen, since March" in html and "CUSTOM-AGREED by Friday" in html
    # Said / cause / tried never prints, and the private note waits for its flag.
    for private in ("CUSTOM-SAID", "CUSTOM-CAUSE", "CUSTOM-TRIED", "hiring stall",
                    "CUSTOM-PRIVATE-NOTE", "MARKER-MONEY", "MARKER-PRIVATE-NOTE"):
        assert private not in html, private
    assert html.index("What you told us matters") < html.index("Leadership bench") < html.index(
        "What happens next")
    from weasyprint import HTML
    assert len(HTML(string=html).render().pages) == 2
    printing.pdf_include_flags = {"fractional_notes": True}
    printing.save()
    assert "CUSTOM-PRIVATE-NOTE" in pdf.render_html(printing)


@pytest.mark.django_db
def test_a_printing_section_with_no_answers_prints_nothing(seeded_tenant, template,
                                                           with_custom, prospect, ff):
    builder.update_section(template, code=with_custom.code, show_in_pdf=True)
    session = services.start(tenant=seeded_tenant, contact=prospect, template=template,
                             owner=ff.user)
    run(session)
    assert "Leadership bench" not in pdf.render_html(session)


@pytest.mark.django_db
def test_two_full_printing_sections_still_fit_two_pages(seeded_tenant, template, prospect, ff):
    for title in ("Leadership bench", "Your systems"):
        section = builder.add_section(template, title=title)
        for n in range(4):
            builder.add_question(template, section=section.code,
                                 prompt=f"{title}: a question of ordinary length, number {n}?")
        builder.update_section(template, code=section.code, show_in_pdf=True)
    session = services.start(tenant=seeded_tenant, contact=prospect, template=template,
                             owner=ff.user)
    run(session)
    for section in session.template_snapshot["sections"]:
        if section["kind"] == "custom":
            for question in section["questions"]:
                answer(session, question["key"],
                       {"text": "An answer of a sentence or so, as written on a call."})
    html = pdf.render_html(session)
    assert html.count("An answer of a sentence or so") == 8
    from weasyprint import HTML
    assert len(HTML(string=html).render().pages) == 2


@pytest.mark.django_db
def test_a_template_with_a_custom_section_duplicates_with_it(template, with_custom, ff, api):
    copy = post(api, ff, f"/api/strategy-templates/{template.pk}/duplicate/",
                {"name": "A copy"}).json()
    copied = get(api, ff, f"{ROOT}{copy['id']}/").json()
    assert order(copied) == order(get(api, ff, url(template)).json())
    assert len(custom(copied)["questions"]) == 3
