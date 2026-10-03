"""Pin the strategy session as it is today (P3 phase 1, 2026-10-03).

Written **before any P3 code**, against `dev` as it stood. One classic session
and one "Operations — focused" (v2) session are run end to end with a fixed
clock and a scripted Claude, and everything a person or Claude would see is
written to `tests/golden/strategy_v2/`: the template snapshot, the pre-call
form and emails, the session payload as the practice owner and as an
assistant, every request sent to Claude, the PDF's HTML and page count, the
covering note, and the conversion.

**These files must stay byte-identical through P3.** A difference here is a
change to how an existing session behaves, which P3 is not allowed to make
(`docs/p3_strategy_templates_session_v3.md` §6).

The files are rewritten only with `UPDATE_STRATEGY_GOLDEN=1`, and a rewrite is
a decision for the owner, never a way to make this test pass.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from unittest import mock

import pytest

from apps.strategy import ai, conversion, emails, pdf as pdf_service, prep, seed, services
from apps.strategy import style
from apps.strategy.models import (
    StrategyAnswer, StrategyDiagnosticProposal, StrategyMapRow, StrategyPathNote,
    StrategyStyleExample,
)
from apps.tenancy.models import AiCall

from . import registry_config  # noqa: F401
from .factories import (
    CompanyFactory, ContactEmailFactory, ContactFactory, MembershipFactory, UserFactory,
)

GOLDEN = Path(__file__).parent / "golden" / "strategy_v2"
UPDATE = os.environ.get("UPDATE_STRATEGY_GOLDEN") == "1"
PROSPECT = StrategyAnswer.AnsweredBy.PROSPECT

START = datetime(2026, 10, 1, 15, 0, tzinfo=dt_timezone.utc)
SCHEDULED = datetime(2026, 10, 8, 16, 0, tzinfo=dt_timezone.utc)


# ------------------------------------------------------------------ the clock

@pytest.fixture
def clock(monkeypatch):
    """Every `timezone.now()` is a millisecond after the last, from a fixed
    instant: dates are stable, and rows made in order stay in order."""
    state = {"at": START}

    def now():
        state["at"] += timedelta(milliseconds=1)
        return state["at"]

    monkeypatch.setattr("django.utils.timezone.now", now)
    return state


# ---------------------------------------------------------------- normalizing

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
DYNAMIC_KEY = re.compile(r"dx_[0-9a-f]{10}")
STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:\+00:00|Z)?")


class Normalizer:
    """Ids and timestamps differ run to run; which is which does not. Each is
    replaced by its order of first appearance across the whole scenario."""

    def __init__(self):
        self.ids: dict = {}
        self.keys: dict = {}

    def __call__(self, text: str) -> str:
        text = UUID.sub(lambda m: f"<id-{self.ids.setdefault(m.group(0), len(self.ids) + 1)}>",
                        text)
        text = DYNAMIC_KEY.sub(
            lambda m: f"dx_<{self.keys.setdefault(m.group(0), len(self.keys) + 1)}>", text)
        return STAMP.sub("<time>", text)


def stable(payload):
    """A session payload with its answers in key order. The API returns them
    in whatever order the database does (`answers_of` has no ordering, and the
    screen looks each one up by key), so that order is not behavior to pin."""
    if isinstance(payload, dict) and isinstance(payload.get("answers"), list):
        # An accepted proposal's key is random, so those sort by their content.
        payload = {**payload, "answers": sorted(payload["answers"], key=lambda a: (
            DYNAMIC_KEY.sub("dx_", a["question_key"]),
            json.dumps(a["value"], sort_keys=True)))}
    return payload


def as_json(value) -> str:
    value = stable(value)
    return json.dumps(value, indent=2, sort_keys=True, default=str, ensure_ascii=False) + "\n"


# ----------------------------------------------------------- scripted Claude

DIAGNOSTIC_REPLY = json.dumps([
    {"slot": 1, "question": "Where do the weekly numbers come from today?",
     "basis": "Data: 2/10"},
    {"slot": 2, "question": "Which seat is hardest to keep filled, and why?",
     "basis": "People: 4/10"},
    {"slot": 3, "question": "What has to be true before the second branch opens?",
     "basis": "growth"},
    {"slot": "snapshot", "question": "What lives in Jen's head that no system holds?",
     "basis": "Scheduling is in Jen's head"},
])

ROWS_REPLY = json.dumps([
    {"header": "A Weekly Scorecard", "statement": "Run the week from five numbers.",
     "bottleneck": "No weekly numbers", "root_cause": "Reports are built by hand",
     "the_fix": "A five-line scorecard reviewed every Monday", "owner_text": "Jen Park",
     "horizon": 30, "measurable": "Scorecard reviewed 4 weeks in a row"},
    {"header": "Scheduling Out Of One Head", "statement": "Put the schedule in a system.",
     "bottleneck": "Scheduling lives in one person's head", "root_cause": "No system",
     "the_fix": "Move scheduling into the dispatch tool", "owner_text": "",
     "horizon": "60", "measurable": "Schedule published by Friday noon"},
    {"header": "Supervisors Who Audit", "statement": "Inspect every site monthly.",
     "bottleneck": "Quality is checked by complaint", "root_cause": "No inspection cadence",
     "the_fix": "A monthly inspection per site", "owner_text": "Nobody Named",
     "horizon": 120, "measurable": "Inspections per month"},
])

MORE_ROWS_REPLY = json.dumps({"rows": [
    # The same bottleneck again: dropped, a second run does not duplicate.
    {"header": "Numbers Again", "statement": "Again.", "bottleneck": "No weekly numbers",
     "the_fix": "Again", "horizon": 30, "measurable": ""},
    {"header": "A Price Book", "statement": "Price every job the same way.",
     "bottleneck": "Pricing is from memory", "root_cause": "No price book",
     "the_fix": "Write the price book", "owner_text": "Dana Reyes", "horizon": 90,
     "measurable": "Quotes priced from the book"},
    {"header": "No Bottleneck", "statement": "Dropped: a row needs one.", "bottleneck": ""},
]})

CONSOLIDATE_REPLY = json.dumps([
    {"header": "Run On Numbers", "statement": "One scorecard and one schedule.",
     "bottleneck": "The week is run from memory", "root_cause": "No systems",
     "the_fix": "Scorecard and dispatch tool", "owner_text": "Jen Park", "horizon": 60,
     "measurable": "Scorecard reviewed weekly", "merges": [1, "2"]},
    {"header": "Cites Nothing", "statement": "Dropped.", "bottleneck": "A new claim",
     "merges": []},
])

MIRROR_REPLY = json.dumps({"goal": "Two branches running without Dana in the room.",
                           "unlocks": "Weekly numbers first. Everything else leans on them."})

PATHS_REPLY = json.dumps({
    "a": {"pros": ["You keep full control of the pace", "No new cost"],
          "cons": ["Your team carries it on top of the day job", "No outside push",
                   "A third", "A fourth is padding"]},
    "b": {"pros": ["Someone owns the list every week"],
          "cons": ["A monthly cost before results show"]},
})

PREP_REPLY = json.dumps({
    "summary": "Their site says they clean offices across two counties.",
    "bottlenecks": ["Likely supervisor span of control", "Likely no-show cover"],
    "rewordings": [
        {"key": "s1_revenue", "suggested": "Revenue last year and this year, in contracts",
         "why": "Their site says contracts"},
        {"key": "s2_vision", "suggested": "What does your 3-year picture look like?",
         "why": "Refused: a rating cannot become an essay"},
        {"key": "not_a_question", "suggested": "Ignored", "why": ""},
    ],
    "questions": [{"text": "How are night supervisors measured?", "why": "Their site says nights"}],
})


# ------------------------------------------------------------- the scenario

def _post(client, url, body=None):
    return client.post(url, data=json.dumps(body or {}), content_type="application/json")


def _patch(client, url, body):
    return client.patch(url, data=json.dumps(body), content_type="application/json")


def _ok(response, *statuses):
    assert response.status_code in (statuses or (200, 201)), \
        (response.status_code, getattr(response, "content", b"")[:400])
    return response


def run(kind: str, tenant, api, fake_claude) -> dict:
    """One session, start to conversion. Returns `{file name: content}`."""
    out: dict = {}
    owner = MembershipFactory(tenant=tenant, role="FF", user=UserFactory(
        email="pat.owner@golden.invalid", full_name="Pat Owner"))
    assistant = MembershipFactory(tenant=tenant, role="VA", user=UserFactory(
        email="riley.assistant@golden.invalid", full_name="Riley Assistant"))
    as_owner, as_assistant = api.as_(owner), api.as_(assistant)

    classic = seed.seed_tenant(tenant)
    template = seed.create_focused(tenant) if kind == "focused" else classic
    out["template_snapshot.json"] = as_json(services.snapshot_of(template))

    company = CompanyFactory(tenant=tenant, name="Acme Facilities")
    dana = ContactFactory(tenant=tenant, first_name="Dana", last_name="Reyes",
                          company=company)
    ContactEmailFactory(tenant=tenant, contact=dana, address="dana@acme.invalid",
                        is_primary=True)
    jen = ContactFactory(tenant=tenant, first_name="Jen", last_name="Park", company=company)

    created = _ok(_post(as_owner, "/api/strategy-sessions/", {
        "contact": str(dana.pk), "template": str(template.pk),
        "integrator_contact": str(jen.pk), "scheduled_at": SCHEDULED.isoformat()}))
    session_id = created.json()["id"]
    base = f"/api/strategy-sessions/{session_id}/"
    from apps.strategy.models import StrategySession

    def session():
        return StrategySession.objects.get(pk=session_id)

    out["session_created.json"] = as_json(created.json())

    # ---- before the call: what a prospect is sent
    out["precall_question_blocks.json"] = as_json(emails.question_blocks(session()))
    text, html = emails._questions_body(session(), emails.default_intro(session()))
    out["precall_questions_email.txt"] = text
    out["precall_questions_email.html"] = html
    invite = emails._invite_body(session(), "https://app.invalid/strategy/precall/TOKEN")
    out["precall_invite_email.json"] = as_json(list(invite))

    fake_claude.reply = PREP_REPLY
    _ok(_post(as_owner, base + "prepare/", {
        "website_url": "https://acme.invalid", "notes": "Met Dana at the chamber lunch."}))
    assert _post(as_assistant, base + "prepare/", {}).status_code == 403

    token = services.issue_precall_token(session())
    form = f"/api/strategy/precall/{token}"
    out["precall_form_empty.json"] = as_json(_ok(as_owner.get(form)).json())
    precall_answers = [
        ("s1_revenue", {"text": "3m last year, 3.4m this year"}),
        ("s1_team", {"text": "22 full-time, 9 part-time, 4 in the office"}),
        ("s1_sites", {"text": "61 sites"}),
        ("s1_software", {"text": "Spreadsheets. Scheduling is in Jen's head."}),
        ("s1_branches", {"text": "One, and we want to open a second branch next year"}),
        ("s2_vision", {"rating": 7, "comment": "Written, not shared"}),
        ("s2_people", {"rating": 4, "comment": ""}),
        ("s2_data", {"rating": 2, "comment": "We have no weekly numbers"}),
        ("s2_issues", {"rating": 6, "comment": ""}),
        ("s2_process", {"rating": 5, "comment": ""}),
    ]
    if kind == "classic":
        precall_answers.append(("s2_traction", {"rating": 3, "comment": "No rhythm"}))
    for key, value in precall_answers:
        _ok(_post(as_owner, form, {"question_key": key, "value": value}))
    # A live question is not the public form's to write.
    assert _post(as_owner, form, {"question_key": "s9_scope",
                                  "value": {"agreed": True}}).status_code == 403

    fake_claude.reply = DIAGNOSTIC_REPLY
    with mock.patch("django_q.tasks.async_task") as queued:
        _ok(_post(as_owner, form + "/complete"))
    out["precall_complete_queued.json"] = as_json(
        [list(call.args[:1]) for call in queued.call_args_list])
    out["precall_form_complete.json"] = as_json(_ok(as_owner.get(form)).json())

    from apps.strategy import diagnostic, tasks

    out["diagnostic_slots.json"] = as_json(diagnostic.slots(session()))
    proposed = tasks.propose_diagnostic(str(tenant.pk), session_id)
    out["diagnostic_proposed_count.json"] = as_json(proposed)
    proposals = list(StrategyDiagnosticProposal.objects.filter(session_id=session_id))
    if proposals:
        root = "/api/strategy-diagnostic-proposals/"
        _ok(_patch(as_owner, f"{root}{proposals[1].pk}/",
                   {"prompt": "Which seat is hardest to keep filled?"}))
        for proposal in proposals[:2]:
            _ok(_post(as_owner, f"{root}{proposal.pk}/accept/"))
        _ok(_post(as_owner, f"{root}{proposals[2].pk}/accept/"))
        _ok(_post(as_owner, f"{root}{proposals[2].pk}/remove/"))
        _ok(_post(as_owner, f"{root}{proposals[3].pk}/discard/"))
        assert _post(as_assistant, f"{root}{proposals[2].pk}/accept/").status_code == 403
    out["session_after_precall.json"] = as_json(_ok(as_owner.get(base)).json())

    # ---- the call
    def say(key, value, note=None, statuses=()):
        body = {"question_key": key, "value": value}
        if note is not None:
            body["fractional_note"] = note
        return _ok(_post(as_owner, base + "answers/", body), *statuses).json()

    saved = []
    if kind == "focused":
        say("n1_why_now", {"text": "We keep losing supervisors. In 90 days: a full bench."})
        say("n1_tried", {"text": "A bonus scheme. Nobody tracked it."})
        say("n1_this_seat", {"text": "Own the weekly rhythm."})
        dynamic = [q["key"] for section in session().template_snapshot["sections"]
                   if section["code"] == "diagnostic"
                   for q in section["questions"] if q.get("dynamic")]
        fake_claude.reply = ROWS_REPLY
        saved.append(say(dynamic[0], {"said": "Dana builds them on Sunday night",
                                      "cause": "No system of record", "tried": ""},
                         note="PRIVATE-DIAGNOSTIC-NOTE"))
        saved.append(say(dynamic[1], {"said": "Night supervisors", "cause": "Pay",
                                      "tried": "A bonus"}))
    else:
        say("s3_three_year_picture", {"text": "Two branches, 6m, Dana out of the day to day"})
        say("s3_alignment_observation", {"text": "PRIVATE-ALIGNMENT-OBSERVATION"})
        fake_claude.reply = ROWS_REPLY
        saved.append(say("s4_decisions_stall", {"said": "Pricing waits for Dana",
                                                "cause": "No price book", "tried": ""},
                         note="PRIVATE-DIAGNOSTIC-NOTE"))
        saved.append(say("s4_integrator_owns", {"said": "Scheduling", "cause": "",
                                                "tried": ""}))
        saved.append(say("s4_accountability_chart", {"said": "Two seats empty",
                                                     "cause": "Turnover", "tried": "Ads"}))
    out["answers_saved_with_auto_draft.json"] = as_json(saved)

    fake_claude.reply = MORE_ROWS_REPLY
    out["draft_rows_button.json"] = as_json(_post(as_owner, base + "draft-rows/").json())
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

    fake_claude.reply = CONSOLIDATE_REPLY
    out["consolidate.json"] = as_json(_post(as_owner, base + "consolidate/").json())

    fake_claude.reply = MIRROR_REPLY
    out["draft_mirror.json"] = as_json(_ok(_post(as_owner, base + "draft-mirror/")).json())
    _ok(_patch(as_owner, base, {
        "mirror_goal": "Two branches running without Dana in the room.",
        "mirror_unlocks": "Weekly numbers first. Everything else leans on them."}))

    say("s7_value_1", {"value": "Straight talk", "why": "They have been oversold before"})
    say("s7_value_2", {"value": "Someone on site", "why": ""})
    say("s8_path_a", {"reaction": "We have tried", "risk": "It slips again", "leaning": ""})
    fake_claude.reply = PATHS_REPLY
    out["path_b_saved_with_auto_draft.json"] = as_json(
        say("s8_path_b", {"reaction": "Interested", "risk": "Cost",
                          "leaning": "Leaning this way"}))
    notes = list(StrategyPathNote.objects.filter(session_id=session_id))
    root = "/api/strategy-path-notes/"

    def of(path, kind):
        return [n for n in notes if n.path == path and n.kind == kind]

    # Edited, then accepted: a pair for "learn from my edits".
    _ok(_patch(as_owner, f"{root}{of('a', 'pro')[0].pk}/", {"text": "You set the pace"}))
    for note in (*of("a", "pro"), of("a", "con")[0], *of("b", "pro"), *of("b", "con")):
        _ok(_post(as_owner, f"{root}{note.pk}/accept/"))
    _ok(_post(as_owner, f"{root}{of('a', 'con')[1].pk}/discard/"))
    # One the practice wrote itself, and one edited after it was accepted.
    _ok(_post(as_owner, root, {"session": session_id, "path": "b", "kind": "pro",
                               "text": "We have done this for a company your size"}), 201)
    _ok(_patch(as_owner, f"{root}{of('b', 'con')[0].pk}/",
               {"text": "A monthly cost before the results show"}))
    assert _post(as_assistant, f"{root}{of('a', 'con')[2].pk}/accept/").status_code == 403

    say("s9_scope", {"agreed": True, "notes": "Rows 1 and 2"})
    say("s9_start_date", {"agreed": True, "notes": "November 3"})
    say("s9_follow_up_call", {"agreed": True, "notes": "Next Tuesday"})
    say("s9_proposal_due", {"agreed": False, "notes": "10/15"})
    say("s9_investment_range", {"agreed": True, "notes": "PRIVATE-INVESTMENT-RANGE"})
    assert _post(as_assistant, base + "answers/", {
        "question_key": "s9_who_else", "value": {"agreed": True}}).status_code == 403

    # ---- what the two roles see, and what the prospect is sent
    out["session_as_practice_owner.json"] = as_json(_ok(as_owner.get(base)).json())
    out["session_as_assistant.json"] = as_json(_ok(as_assistant.get(base)).json())
    out["sessions_list_as_practice_owner.json"] = as_json(
        _ok(as_owner.get("/api/strategy-sessions/")).json())

    out["pdf.html"] = pdf_service.render_html(session())
    out["pdf_page_count.json"] = as_json(pdf_service.page_count(session()))
    out["pdf_cover_note.html"] = emails.default_pdf_cover(session())
    _ok(_patch(as_owner, base + "pdf-flags/", {"mechanics": True, "investment": True,
                                               "diagnostic_observations": True}))
    out["pdf_all_three_flags_on.html"] = pdf_service.render_html(session())
    _ok(_patch(as_owner, base + "pdf-flags/", {"mechanics": False, "investment": False,
                                               "diagnostic_observations": False}))

    # ---- conversion
    out["conversion_preview.json"] = as_json(
        _ok(as_owner.get(base + "conversion-preview/")).json())
    accepted = conversion.accepted_rows(session())
    choices = {str(accepted[0].pk): {"as": "goal", "baseline_unknown": True},
               str(accepted[1].pk): {"as": "project"},
               str(accepted[2].pk): {"as": "skip"}}
    out["convert.json"] = as_json(
        _ok(_post(as_owner, base + "convert/", {"choices": choices})).json())
    from apps.work.models import Goal, Project

    def fields(model):
        skip = {"id", "tenant", "created_at", "updated_at"}
        names = [f.attname for f in model._meta.concrete_fields if f.name not in skip]
        return [{name: getattr(obj, name) for name in names}
                for obj in model.objects.order_by("created_at")]

    out["converted_goals.json"] = as_json(fields(Goal))
    out["converted_projects.json"] = as_json(fields(Project))
    out["session_after_conversion.json"] = as_json(_ok(as_owner.get(base)).json())

    # ---- everything Claude was sent, and what each call was recorded as
    out["claude_requests.json"] = as_json(fake_claude.requests)
    out["ai_calls.json"] = as_json(list(
        AiCall.objects.order_by("created_at").values(
            "purpose", "trigger", "unattended", "target_type", "succeeded", "model")))
    out["style_examples.json"] = as_json(list(
        StrategyStyleExample.objects.order_by("kind", "created_at").values(
            "kind", "proposed", "accepted", "source_type")))
    out["style_prompt_block.txt"] = style.prompt_block(
        tenant, [style.K.MAP_HEADER, style.K.MAP_STATEMENT, style.K.PRO, style.K.CON])
    out["prompt_constants.json"] = as_json({
        "rows_system": ai.ROWS_SYSTEM, "mirror_system": ai.MIRROR_SYSTEM,
        "paths_system": ai.PATHS_SYSTEM, "consolidate_system": ai.CONSOLIDATE_SYSTEM,
        "diagnostic_system": diagnostic.SYSTEM, "prep_system": prep.SYSTEM})
    return out


# ------------------------------------------------------------------ the test

@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["classic", "focused"])
def test_a_session_is_exactly_what_it_was_before_p3(kind, seeded_tenant, in_tenant_a, api,
                                                    fake_claude, clock, settings):
    # Pinned, so the files do not depend on this machine's `.env`.
    settings.ANTHROPIC_MODEL = "claude-golden"
    settings.PUBLIC_BASE_URL = "https://app.invalid"
    fake_claude.model = "claude-golden"
    normalize = Normalizer()
    produced = {name: normalize(content)
                for name, content in run(kind, seeded_tenant, api, fake_claude).items()}
    folder = GOLDEN / kind
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
        pytest.fail(f"{kind}: {len(different)} golden file(s) changed: {different}\n{diff}")


def test_the_private_markers_never_reach_what_a_prospect_is_sent():
    """The goldens are only worth pinning if they pin the right thing: with no
    flag on, none of the private markers is in the PDF, the covering note or
    any email, for either format."""
    markers = ("PRIVATE-DIAGNOSTIC-NOTE", "PRIVATE-MECHANICS-NOTE",
               "PRIVATE-ALIGNMENT-OBSERVATION", "PRIVATE-INVESTMENT-RANGE")
    for kind in ("classic", "focused"):
        for name in ("pdf.html", "pdf_cover_note.html", "precall_questions_email.txt",
                     "precall_questions_email.html", "precall_form_complete.json",
                     "session_as_assistant.json"):
            text = (GOLDEN / kind / name).read_text(encoding="utf-8")
            for marker in markers:
                if name == "session_as_assistant.json" and marker != "PRIVATE-INVESTMENT-RANGE":
                    continue                 # an assistant sees sections 1–8
                assert marker not in text, f"{marker} is in {kind}/{name}"
        assert json.loads((GOLDEN / kind / "pdf_page_count.json").read_text()) == 2
