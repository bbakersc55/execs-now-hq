"""Pin session v3 as released (P3 part two, phase 1, 2026-10-03).

Written **before any part-two code**, against `dev` while its code was what
Release 4 put in production (`main` at `0a07322`; the commits since are docs).
One builder template is made through the API and one session is run from it
end to end, with a fixed clock and a scripted Claude. Everything a person or
Claude would see is written to `tests/golden/strategy_v3/`: the builder's own
view of the template, the snapshot, the pre-call form and emails, the session
payload as the practice owner and as an assistant, every request sent to
Claude, the PDF's HTML and page count, the covering note, and the conversion.

**These files must stay byte-identical through part two** for a template that
uses none of its new features: that is what "existing v3 templates and
sessions keep working unchanged" means
(`docs/p3_part2_custom_sections_ai.md` §1, §9).

The files are rewritten only with `UPDATE_STRATEGY_GOLDEN=1`, and a rewrite is
a decision for the owner, never a way to make this test pass.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest import mock

import pytest

from apps.strategy import ai, conversion, diagnostic, emails, pdf as pdf_service, prep
from apps.strategy import services, style, tasks, v3
from apps.strategy.models import (
    StrategyDiagnosticProposal, StrategyMapRow, StrategyPathNote, StrategyQuestion,
    StrategySession, StrategyStyleExample, StrategyTemplate,
)
from apps.tenancy.models import AiCall

from . import registry_config  # noqa: F401
from .factories import (
    CompanyFactory, ContactEmailFactory, ContactFactory, MembershipFactory, UserFactory,
)
from .test_strategy_v2_golden import (  # noqa: F401  (`clock` is a fixture)
    CONSOLIDATE_REPLY, MIRROR_REPLY, MORE_ROWS_REPLY, PATHS_REPLY, ROWS_REPLY, SCHEDULED,
    UPDATE, Normalizer, _ok, _patch, _post, clock,
)

GOLDEN = Path(__file__).parent / "golden" / "strategy_v3"
ROOT = "/api/strategy-template-builder/"

# ---------------------------------------------------------------- stable keys

#: A builder question's key is its section's code and eight random characters;
#: an accepted diagnostic question's is `dx_` and ten.
TEMPLATE_KEY = re.compile(
    r"\b(snapshot|six_key_components|diagnostic|mirror|strategy_map|what_they_value|"
    r"two_paths|scope_agreement)_[0-9a-f]{8}\b")
DYNAMIC_KEY = re.compile(r"\bdx_[0-9a-f]{10}\b")


class Keys:
    """Random question keys, renamed by the order they were made in — and
    renamed **before** anything is sorted, because a key is also what answers
    and score tables are ordered by."""

    def __init__(self):
        self.names: dict = {}

    def register(self, key: str) -> None:
        if key in self.names:
            return
        if key.startswith("dx_"):
            ordinal = sum(1 for name in self.names.values() if name.startswith("dx<")) + 1
            self.names[key] = f"dx<{ordinal}>"
        else:
            code = key.rsplit("_", 1)[0]
            ordinal = sum(1 for name in self.names.values()
                          if name.startswith(f"{code}<")) + 1
            self.names[key] = f"{code}<{ordinal}>"

    def text(self, text: str) -> str:
        def named(match):
            self.register(match.group(0))
            return self.names[match.group(0)]

        return DYNAMIC_KEY.sub(named, TEMPLATE_KEY.sub(named, text))

    def stable(self, value):
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            out = {self.text(str(k)) if isinstance(k, str) else k: self.stable(v)
                   for k, v in value.items()}
            # The API returns answers in database order, which is not behavior.
            if isinstance(out.get("answers"), list):
                out["answers"] = sorted(out["answers"],
                                        key=lambda a: a.get("question_key", ""))
            return out
        if isinstance(value, (list, tuple)):
            return [self.stable(item) for item in value]
        return value

    def dump(self, value) -> str:
        if isinstance(value, str):
            return self.text(value)
        value = json.loads(json.dumps(value, default=str))
        return json.dumps(self.stable(value), indent=2, sort_keys=True,
                          ensure_ascii=False) + "\n"


# ----------------------------------------------------------- scripted Claude

def diagnostic_reply():
    return json.dumps([
        {"slot": 1, "question": "What has to be true before the second branch opens?",
         "basis": "open a second branch"},
        {"slot": "gap", "question": "What is in Jen's head that no system holds?",
         "basis": "Scheduling is in Jen's head"},
        {"slot": "gap", "question": "Who covers scheduling when Jen is away?",
         "basis": "Scheduling is in Jen's head"},
        {"slot": "gap", "question": "How do property managers find you today?",
         "basis": "to property managers"},
        {"slot": "gap", "question": "A fifth, past the template's number", "basis": "x"},
        {"slot": 9, "question": "A slot nobody asked for", "basis": "x"},
    ])


RATINGS_REPLY = json.dumps([
    {"slot": 1, "question": "Which numbers would you want every Monday?", "basis": "x"},
    {"slot": 2, "question": "Which seats are empty, and since when?", "basis": "x"},
    {"slot": "gap", "question": "Not asked for on this button", "basis": "x"},
])

#: A second run, after one row was discarded: the same header in other
#: capitals and the rejected bottleneck with other punctuation are both
#: dropped, and one new row is kept.
AFTER_REJECTION_REPLY = json.dumps([
    {"header": "THE MONDAY SCORECARD!", "statement": "Again.",
     "bottleneck": "Words nobody has used", "the_fix": "x", "horizon": 30},
    {"header": "Another Header", "statement": "Again.",
     "bottleneck": "pricing is, from MEMORY.", "the_fix": "x", "horizon": 30},
    {"header": "A Supervisor Bench", "statement": "Two supervisors ready to step up.",
     "bottleneck": "No cover for supervisors", "root_cause": "No bench",
     "the_fix": "Train two leads", "owner_text": "Jen Park", "horizon": 90,
     "measurable": "Leads signed off"},
])


def prep_reply(keys: list[str]) -> str:
    return json.dumps({
        "summary": "Their site says they clean offices across two counties.",
        "bottlenecks": ["Likely supervisor span of control", "Likely no-show cover"],
        "rewordings": [
            {"key": keys[0], "suggested": "What does {Company} clean, and for whom?",
             "why": "Their site says cleaning"},
            {"key": keys[1], "suggested": "How many work for {The Boss}?",
             "why": "Dropped: no such merge field"},
            {"key": "not_a_question", "suggested": "Ignored", "why": ""},
        ],
        "questions": [{"text": "How are night supervisors measured?",
                       "why": "Their site says nights"}],
    })


# ------------------------------------------------------------- the scenario

def run(tenant, api, fake_claude, keys: Keys) -> dict:
    """One builder template and one session from it, start to conversion.
    Returns `{file name: content}`, not yet made stable."""
    out: dict = {}
    owner = MembershipFactory(tenant=tenant, role="FF", user=UserFactory(
        email="pat.owner@golden.invalid", full_name="Pat Owner"))
    assistant = MembershipFactory(tenant=tenant, role="VA", user=UserFactory(
        email="riley.assistant@golden.invalid", full_name="Riley Assistant"))
    as_owner, as_assistant = api.as_(owner), api.as_(assistant)

    # ---- the template, made the way a practice owner makes it
    made = _ok(_post(as_owner, ROOT, {"name": "Our strategy session"}))
    template_id = made.json()["id"]
    base_t = f"{ROOT}{template_id}/"
    out["builder_blank.json"] = made.json()

    def add(section, prompt, **more):
        return _ok(_post(as_owner, base_t + "questions/",
                         {"section": section, "prompt": prompt, **more}), 201).json()

    add("snapshot", "What does {Company} sell, and to whom?", label="Sells")
    add("snapshot", "How many people work there?", label="Team", pdf_chip=True)
    add("snapshot", "What do you want from {Practice}?")
    add("snapshot", "A question that is taken back out")
    add("six_key_components", "Plan — Our plan is written down and shared.", label="Plan")
    add("six_key_components", "Team — The right people are in the right seats.",
        label="Team")
    add("six_key_components", "Numbers — We run the week from a few numbers.",
        label="Numbers")
    add("diagnostic", "Where does work get stuck waiting for you?")
    add("diagnostic", "What breaks when you take a week off?")
    add("mirror", "Three years from now, what does {Company} look like?", must_ask=True)
    add("what_they_value", "Value 1 — in their words, and why")
    add("what_they_value", "Value 2 — in their words, and why")
    add("scope_agreement", "Follow-up call booked")
    assert _post(as_owner, base_t + "questions/", {
        "section": "six_key_components", "prompt": "What is your plan?",
        "label": "Plan"}).status_code == 400

    def template_keys():
        return list(StrategyQuestion.objects.filter(template_id=template_id)
                    .order_by("section__position", "position", "created_at")
                    .values_list("key", flat=True))

    for key in template_keys():
        keys.register(key)

    def of(kind, live=True):
        questions = StrategyQuestion.objects.filter(template_id=template_id,
                                                    section__kind=kind)
        if live:
            questions = questions.filter(deleted_at__isnull=True)
        return list(questions.order_by("position").values_list("key", flat=True))

    _ok(_post(as_owner, base_t + "remove-question/", {"key": of("precall")[3]}))
    _ok(_post(as_owner, base_t + "question/", {
        "key": of("paths")[0], "prompt": "Path A — Keep running it yourselves"}))
    _ok(_post(as_owner, base_t + "reorder/", {
        "section": "what_they_value", "keys": of("values")[::-1]}))
    _ok(_post(as_owner, base_t + "section/", {
        "code": "six_key_components", "title": "Three things we rate",
        "time_budget_minutes": 8}))
    _ok(_post(as_owner, base_t + "settings/", {"settings": {
        "advisor_role": "business consultant", "diagnostic_size": 4,
        "rating_scale": "1 is not yet, 10 is every week",
        "path_b_title": "Work with {Practice}",
        "path_b_points": ["{Practice} works the map with you", "On site every week"]}}))
    assert _post(as_owner, base_t + "settings/",
                 {"settings": {"diagnostic_size": 9}}).status_code == 400
    assert _post(as_assistant, base_t + "questions/",
                 {"section": "snapshot", "prompt": "Theirs?"}).status_code == 403

    out["builder_template.json"] = _ok(as_owner.get(base_t)).json()
    out["builder_template_as_assistant.json"] = _ok(as_assistant.get(base_t)).json()
    out["template_list.json"] = _ok(as_owner.get("/api/strategy-templates/")).json()
    template = StrategyTemplate.objects.get(pk=template_id)
    out["template_snapshot.json"] = services.snapshot_of(template)

    # ---- the session
    company = CompanyFactory(tenant=tenant, name="Acme Facilities")
    dana = ContactFactory(tenant=tenant, first_name="Dana", last_name="Reyes",
                          company=company)
    ContactEmailFactory(tenant=tenant, contact=dana, address="dana@acme.invalid",
                        is_primary=True)
    jen = ContactFactory(tenant=tenant, first_name="Jen", last_name="Park", company=company)
    created = _ok(_post(as_owner, "/api/strategy-sessions/", {
        "contact": str(dana.pk), "template": template_id,
        "integrator_contact": str(jen.pk), "scheduled_at": SCHEDULED.isoformat()}))
    session_id = created.json()["id"]
    base = f"/api/strategy-sessions/{session_id}/"
    out["session_created.json"] = created.json()

    def session():
        return StrategySession.objects.get(pk=session_id)

    def section_keys(kind, **where):
        section = v3.section_of(session(), kind)
        return [q["key"] for q in section["questions"]
                if all(q.get(k) == v for k, v in where.items())]

    # ---- before the call: what a prospect is sent
    out["precall_question_blocks.json"] = emails.question_blocks(session())
    text, html = emails._questions_body(session(), emails.default_intro(session()))
    out["precall_questions_email.txt"] = text
    out["precall_questions_email.html"] = html
    out["precall_invite_email.json"] = list(emails._invite_body(
        session(), "https://app.invalid/strategy/precall/TOKEN"))

    sells, team, want = section_keys("precall")
    fake_claude.reply = prep_reply([sells, team])
    _ok(_post(as_owner, base + "prepare/", {
        "website_url": "https://acme.invalid", "notes": "Met Dana at the chamber lunch."}))
    assert _post(as_assistant, base + "prepare/", {}).status_code == 403

    token = services.issue_precall_token(session())
    form = f"/api/strategy/precall/{token}"
    out["precall_form_empty.json"] = _ok(as_owner.get(form)).json()
    for key, value in ((sells, "Office cleaning, to property managers"),
                       (team, "22 people. Scheduling is in Jen's head."),
                       (want, "Help to open a second branch next year")):
        _ok(_post(as_owner, form, {"question_key": key, "value": {"text": value}}))
    # A rating and a scope item are not the public form's to write.
    for live in (section_keys("ratings")[0], section_keys("scope")[0]):
        assert _post(as_owner, form, {"question_key": live,
                                      "value": {"rating": 9, "agreed": True}}).status_code == 403

    fake_claude.reply = diagnostic_reply()
    with mock.patch("django_q.tasks.async_task") as queued:
        _ok(_post(as_owner, form + "/complete"))
    out["precall_complete_queued.json"] = [list(call.args[:1])
                                           for call in queued.call_args_list]
    out["precall_form_complete.json"] = _ok(as_owner.get(form)).json()
    out["diagnostic_slots.json"] = v3.slots(session())
    out["diagnostic_proposed_count.json"] = tasks.propose_diagnostic(str(tenant.pk),
                                                                    session_id)
    proposals = list(StrategyDiagnosticProposal.objects.filter(session_id=session_id))
    root = "/api/strategy-diagnostic-proposals/"
    _ok(_patch(as_owner, f"{root}{proposals[1].pk}/", {"prompt": "What does only Jen know?"}))
    for proposal in proposals[:2]:
        _ok(_post(as_owner, f"{root}{proposal.pk}/accept/"))
    _ok(_post(as_owner, f"{root}{proposals[2].pk}/accept/"))
    _ok(_post(as_owner, f"{root}{proposals[2].pk}/remove/"))
    _ok(_post(as_owner, f"{root}{proposals[3].pk}/discard/"))
    assert _post(as_assistant, f"{root}{proposals[2].pk}/accept/").status_code == 403
    out["diagnostic_added_by_hand.json"] = _ok(_post(as_owner, root, {
        "session": session_id, "prompt": "Who decides on price?"}), 201).json()
    assert _post(as_assistant, root, {"session": session_id,
                                      "prompt": "Theirs?"}).status_code == 403
    out["session_after_precall.json"] = _ok(as_owner.get(base)).json()

    # ---- the call
    def say(key, value, note=None):
        body = {"question_key": key, "value": value}
        if note is not None:
            body["fractional_note"] = note
        return _ok(_post(as_owner, base + "answers/", body)).json()

    early = _post(as_owner, base + "propose-diagnostic/", {"from_ratings": True})
    out["propose_from_ratings_too_early.json"] = [early.status_code, early.json()]
    for key, rating, comment in zip(section_keys("ratings"), (7, 3, 2),
                                    ("Written, not shared", "Two seats empty", "")):
        say(key, {"rating": rating, "comment": comment})
    fake_claude.reply = RATINGS_REPLY
    out["propose_from_ratings.json"] = _ok(_post(
        as_owner, base + "propose-diagnostic/", {"from_ratings": True})).json()

    say(section_keys("mirror")[0], {"text": "Two branches, 6m, Dana out of the day to day"})
    dynamic = section_keys("diagnostic", dynamic=True)
    saved = [say(dynamic[0], {"said": "A second supervisor team", "cause": "", "tried": ""}),
             say(dynamic[1], {"said": "Who is off, and who can cover",
                              "cause": "No system of record", "tried": "A spreadsheet"},
                 note="PRIVATE-DIAGNOSTIC-NOTE")]
    fake_claude.reply = ROWS_REPLY
    saved.append(say(dynamic[2], {"said": "Dana, every time", "cause": "No price book",
                                  "tried": ""}))
    out["answers_saved_with_auto_draft.json"] = saved

    fake_claude.reply = MORE_ROWS_REPLY
    out["draft_rows_button.json"] = _post(as_owner, base + "draft-rows/").json()
    assert _post(as_assistant, base + "draft-rows/").status_code == 403

    rows = list(StrategyMapRow.objects.filter(session_id=session_id)
                .order_by("position", "created_at"))
    root = "/api/strategy-map-rows/"
    _ok(_patch(as_owner, f"{root}{rows[0].pk}/", {
        "header": "The Monday Scorecard", "statement": "Five numbers, every Monday.",
        "mechanics_note": "PRIVATE-MECHANICS-NOTE"}))
    for row in rows[:3]:
        _ok(_post(as_owner, f"{root}{row.pk}/accept/"))
    _ok(_post(as_owner, f"{root}{rows[3].pk}/discard/"))
    _ok(_patch(as_owner, f"{root}{rows[1].pk}/", {"statement": "The schedule, in a system."}))
    fake_claude.reply = AFTER_REJECTION_REPLY
    out["draft_rows_after_a_rejection.json"] = _post(as_owner, base + "draft-rows/").json()

    fake_claude.reply = CONSOLIDATE_REPLY
    out["consolidate.json"] = _post(as_owner, base + "consolidate/").json()

    fake_claude.reply = MIRROR_REPLY
    out["draft_mirror.json"] = _ok(_post(as_owner, base + "draft-mirror/")).json()
    _ok(_patch(as_owner, base, {
        "mirror_goal": "Two branches running without Dana in the room.",
        "mirror_unlocks": "Weekly numbers first. Everything else leans on them."}))

    value_1, value_2 = section_keys("values")
    say(value_1, {"value": "Straight talk", "why": "They have been oversold before"})
    say(value_2, {"value": "Someone on site", "why": ""})
    path_a, path_b = section_keys("paths")
    say(path_a, {"reaction": "We have tried", "risk": "It slips again", "leaning": ""})
    fake_claude.reply = PATHS_REPLY
    out["path_b_saved_with_auto_draft.json"] = say(
        path_b, {"reaction": "Interested", "risk": "Cost", "leaning": "Leaning this way"})
    notes = list(StrategyPathNote.objects.filter(session_id=session_id))
    root = "/api/strategy-path-notes/"

    def note_of(path, kind):
        return [n for n in notes if n.path == path and n.kind == kind]

    _ok(_patch(as_owner, f"{root}{note_of('a', 'pro')[0].pk}/", {"text": "You set the pace"}))
    for note in (*note_of("a", "pro"), note_of("a", "con")[0], *note_of("b", "pro"),
                 *note_of("b", "con")):
        _ok(_post(as_owner, f"{root}{note.pk}/accept/"))
    _ok(_post(as_owner, f"{root}{note_of('a', 'con')[1].pk}/discard/"))
    _ok(_post(as_owner, root, {"session": session_id, "path": "b", "kind": "pro",
                               "text": "We have done this for a company your size"}), 201)

    scope, start, money, follow_up = section_keys("scope")
    say(scope, {"agreed": True, "notes": "Rows 1 and 2"})
    say(start, {"agreed": True, "notes": "November 3"})
    say(follow_up, {"agreed": True, "notes": "Next Tuesday"})
    say(money, {"agreed": True, "notes": "PRIVATE-INVESTMENT-RANGE"})
    assert _post(as_assistant, base + "answers/", {
        "question_key": scope, "value": {"agreed": True}}).status_code == 403

    # ---- what the two roles see, and what the prospect is sent
    out["session_as_practice_owner.json"] = _ok(as_owner.get(base)).json()
    out["session_as_assistant.json"] = _ok(as_assistant.get(base)).json()
    out["sessions_list_as_practice_owner.json"] = _ok(
        as_owner.get("/api/strategy-sessions/")).json()

    out["pdf.html"] = pdf_service.render_html(session())
    out["pdf_page_count.json"] = pdf_service.page_count(session())
    out["pdf_cover_note.html"] = emails.default_pdf_cover(session())
    flags = {"mechanics": True, "investment": True, "diagnostic_observations": True}
    _ok(_patch(as_owner, base + "pdf-flags/", flags))
    out["pdf_all_three_flags_on.html"] = pdf_service.render_html(session())
    _ok(_patch(as_owner, base + "pdf-flags/", {flag: False for flag in flags}))

    # ---- a draft cannot go back to the seed, and conversion
    refused = _post(as_owner, base + "restore-seed/")
    out["restore_seed_refused.json"] = [refused.status_code, refused.json()]
    out["conversion_preview.json"] = _ok(as_owner.get(base + "conversion-preview/")).json()
    accepted = conversion.accepted_rows(session())
    choices = {str(accepted[0].pk): {"as": "goal", "baseline_unknown": True},
               str(accepted[1].pk): {"as": "project"},
               str(accepted[2].pk): {"as": "skip"}}
    out["convert.json"] = _ok(_post(as_owner, base + "convert/", {"choices": choices})).json()
    from apps.work.models import Goal, Project

    def fields(model):
        skip = {"id", "tenant", "created_at", "updated_at"}
        names = [f.attname for f in model._meta.concrete_fields if f.name not in skip]
        return [{name: getattr(obj, name) for name in names}
                for obj in model.objects.order_by("created_at")]

    out["converted_goals.json"] = fields(Goal)
    out["converted_projects.json"] = fields(Project)
    out["session_after_conversion.json"] = _ok(as_owner.get(base)).json()

    # ---- everything Claude was sent, and what each call was recorded as
    for key in section_keys("diagnostic", dynamic=True):
        keys.register(key)
    out["claude_requests.json"] = fake_claude.requests
    out["ai_calls.json"] = list(AiCall.objects.order_by("created_at").values(
        "purpose", "trigger", "unattended", "target_type", "succeeded", "model"))
    out["style_examples.json"] = list(
        StrategyStyleExample.objects.order_by("kind", "created_at").values(
            "kind", "proposed", "accepted", "source_type"))
    out["style_prompt_block.txt"] = style.prompt_block(
        tenant, [style.K.MAP_HEADER, style.K.MAP_STATEMENT, style.K.PRO, style.K.CON])
    out["prompt_constants.json"] = {
        "v3_diagnostic_system": v3.DIAGNOSTIC_SYSTEM,
        "rows_system_for_v3": v3.system(ai.ROWS_SYSTEM, session()),
        "mirror_system_for_v3": v3.system(ai.MIRROR_SYSTEM, session()),
        "paths_system_for_v3": v3.system(ai.PATHS_SYSTEM, session()),
        "consolidate_system_for_v3": v3.system(ai.CONSOLIDATE_SYSTEM, session()),
        "prep_system_for_v3": prep._system(session()),
        "v2_diagnostic_system_unused_by_v3": diagnostic.SYSTEM != v3.DIAGNOSTIC_SYSTEM}
    return out


# ------------------------------------------------------------------ the test

@pytest.mark.django_db
def test_a_v3_session_is_exactly_what_was_released(seeded_tenant, in_tenant_a, api,
                                                   fake_claude, clock, settings):
    # Pinned, so the files do not depend on this machine's `.env`.
    settings.ANTHROPIC_MODEL = "claude-golden"
    settings.PUBLIC_BASE_URL = "https://app.invalid"
    fake_claude.model = "claude-golden"
    keys, normalize = Keys(), Normalizer()
    raw = run(seeded_tenant, api, fake_claude, keys)
    produced = {name: normalize(keys.dump(content)) for name, content in raw.items()}
    folder = GOLDEN / "session"
    if UPDATE:
        folder.mkdir(parents=True, exist_ok=True)
        for stale in folder.iterdir():
            stale.unlink()
        for name, content in produced.items():
            (folder / name).write_text(content, encoding="utf-8")
        return
    on_disk = {path.name for path in folder.iterdir()} if folder.exists() else set()
    assert on_disk == set(produced), (
        "the golden files and what the scenario produces are different sets: "
        f"{sorted(on_disk ^ set(produced))}")
    different = [name for name, content in produced.items()
                 if (folder / name).read_text(encoding="utf-8") != content]
    if different:
        import difflib

        name = different[0]
        diff = "".join(list(difflib.unified_diff(
            (folder / name).read_text(encoding="utf-8").splitlines(keepends=True),
            produced[name].splitlines(keepends=True), "golden/" + name, "now/" + name))[:60])
        pytest.fail(f"v3: {len(different)} golden file(s) changed: {different}\n{diff}")


def test_the_private_markers_never_reach_what_a_v3_prospect_is_sent():
    """The goldens pin the right thing: with no flag on, no private marker is
    in the PDF, the covering note, an email or the form, and an assistant's
    payload holds no money."""
    folder = GOLDEN / "session"
    markers = ("PRIVATE-DIAGNOSTIC-NOTE", "PRIVATE-MECHANICS-NOTE",
               "PRIVATE-INVESTMENT-RANGE")
    for name in ("pdf.html", "pdf_cover_note.html", "precall_questions_email.txt",
                 "precall_questions_email.html", "precall_form_complete.json"):
        text = (folder / name).read_text(encoding="utf-8")
        for marker in markers:
            assert marker not in text, f"{marker} is in {name}"
    assistant = (folder / "session_as_assistant.json").read_text(encoding="utf-8")
    assert "PRIVATE-INVESTMENT-RANGE" not in assistant
    assert "Investment discussed" not in assistant
    assert json.loads((folder / "pdf_page_count.json").read_text()) == 2
    # And no file still carries a random key.
    for path in folder.iterdir():
        text = path.read_text(encoding="utf-8")
        assert not TEMPLATE_KEY.search(text) and not DYNAMIC_KEY.search(text), path.name
