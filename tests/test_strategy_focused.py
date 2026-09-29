"""Strategy session v2 — "Operations — focused" (owner, 2026-09-29).

1. The template, and the dynamic diagnostic with its three guardrails.
2. Map rows as a header and a focus statement; the map capped at five.
3. The PDF for a 3–5 row map, and the mirror as bullets.
4. Learning from the practice's edits, and never from another practice's.
"""

from __future__ import annotations

import json
from unittest import mock

import pytest
from django.core.management import call_command

from apps.strategy import ai, diagnostic, pdf as pdf_service, seed, services, style
from apps.strategy.models import (
    StrategyAnswer, StrategyDiagnosticProposal, StrategyMapRow, StrategyPathNote,
    StrategySession, StrategyStyleExample, StrategyTemplate,
)
from apps.tenancy.models import AiCall

from . import registry_config  # noqa: F401
from .factories import ContactEmailFactory, ContactFactory, MembershipFactory

PROSPECT = StrategyAnswer.AnsweredBy.PROSPECT
FRACTIONAL = StrategyAnswer.AnsweredBy.FRACTIONAL


@pytest.fixture
def classic(seeded_tenant, in_tenant_a):
    return seed.seed_tenant(seeded_tenant)


@pytest.fixture
def focused(seeded_tenant, classic):
    return seed.create_focused(seeded_tenant)


@pytest.fixture
def prospect(seeded_tenant):
    contact = ContactFactory(tenant=seeded_tenant, first_name="Dana", last_name="Reyes")
    ContactEmailFactory(tenant=seeded_tenant, contact=contact, address="dana@acme.invalid",
                        is_primary=True)
    return contact


@pytest.fixture
def session(seeded_tenant, focused, prospect, ff):
    return services.start(tenant=seeded_tenant, contact=prospect, template=focused,
                          owner=ff.user)


def answer(session, key, value, by=FRACTIONAL):
    return services.save_answer(session, question_key=key, value=value, answered_by=by)


def precall(session, ratings=(("s2_vision", 7), ("s2_people", 4), ("s2_data", 2),
                               ("s2_issues", 6), ("s2_process", 5)), revenue="3m, 3.4m"):
    answer(session, "s1_revenue", {"text": revenue}, PROSPECT)
    answer(session, "s1_software", {"text": "Spreadsheets. Scheduling is in Jen's head."},
           PROSPECT)
    for key, rating in ratings:
        answer(session, key, {"rating": rating, "comment": ""}, PROSPECT)


def codes(snapshot, **kw):
    return [(s["code"], q["key"]) for s, q in services.questions_in(snapshot, **kw)]


# ================================================================ the template

@pytest.mark.django_db
def test_the_focused_template_is_the_default_and_shaped_as_specified(focused, classic):
    classic.refresh_from_db()
    assert focused.is_default and not classic.is_default
    assert focused.format == StrategyTemplate.Format.FOCUSED
    snap = services.snapshot_of(focused)
    pre = codes(snap, ask_when="precall")
    assert [k for c, k in pre if c == "snapshot"] == [
        "s1_revenue", "s1_team", "s1_sites", "s1_service_mix", "s1_branches",
        "s1_top_accounts", "s1_software"]
    assert [k for c, k in pre if c == "six_key_components"] == list(seed.FOCUSED_RATING_KEYS)
    assert "s2_traction" not in dict(pre).values()

    live = [s for s in snap["sections"] if s["code"] not in ("snapshot", "six_key_components")]
    assert [(s["code"], s["time_budget_minutes"]) for s in live] == [
        ("what_you_need", 10), ("diagnostic", 15), ("mirror", 5), ("strategy_map", 10),
        ("what_they_value", 5), ("two_paths", 5), ("scope_agreement", 5)]
    assert sum(s["time_budget_minutes"] for s in live) == 55
    need = next(s for s in live if s["code"] == "what_you_need")["questions"]
    assert [(q["key"], q["must_ask"]) for q in need] == [
        ("n1_why_now", True), ("n1_tried", True), ("n1_this_seat", True),
        ("s3_stalled_goal", False)]
    diag = next(s for s in live if s["code"] == "diagnostic")["questions"]
    assert [q["key"] for q in diag] == list(seed.FOCUSED_FALLBACK_KEYS)
    assert all(q["is_diagnostic_fallback"] and not q["must_ask"] for q in diag)
    assert len(next(s for s in live if s["code"] == "what_they_value")["questions"]) == 3
    assert snap["template"]["format"] == "focused"


@pytest.mark.django_db
def test_sessions_already_started_are_untouched(seeded_tenant, classic, prospect, ff):
    before = services.start(tenant=seeded_tenant, contact=prospect, template=classic,
                            owner=ff.user)
    frozen = json.dumps(before.template_snapshot, sort_keys=True)
    seed.create_focused(seeded_tenant)
    before.refresh_from_db()
    assert json.dumps(before.template_snapshot, sort_keys=True) == frozen
    assert services.format_of(before) == "classic"
    after = services.start(tenant=seeded_tenant, contact=prospect, owner=ff.user)
    assert services.format_of(after) == "focused", "the next session takes the new default"


@pytest.mark.django_db
def test_the_command_is_a_dry_run_until_applied(seeded_tenant, classic):
    call_command("add_focused_template", tenant=seeded_tenant.slug)
    assert not StrategyTemplate.objects.filter(name=seed.FOCUSED_NAME).exists()
    call_command("add_focused_template", tenant=seeded_tenant.slug, apply=True)
    assert StrategyTemplate.objects.get(name=seed.FOCUSED_NAME).is_default
    call_command("add_focused_template", tenant=seeded_tenant.slug, apply=True)   # idempotent
    assert StrategyTemplate.objects.filter(name=seed.FOCUSED_NAME).count() == 1


# ============================================== the dynamic diagnostic

@pytest.mark.django_db
def test_slots_come_from_the_answers_not_from_claude(session):
    precall(session)
    answer(session, "s1_branches", {"text": "One site; we want to expand to Boise next year"},
           PROSPECT)
    planned = diagnostic.slots(session)
    assert [p["rule"] for p in planned] == ["lowest_rating", "lowest_rating", "growth"], \
        "three already: no third-lowest rating added"
    assert "Data" in planned[0]["reason"] and "People" in planned[1]["reason"]
    assert "expand" in planned[2]["basis"]


@pytest.mark.django_db
def test_with_too_few_slots_the_third_lowest_rating_gets_one(session):
    precall(session)
    assert [p["rule"] for p in diagnostic.slots(session)] == ["lowest_rating"] * 3


REPLY = json.dumps([
    {"slot": 1, "question": "Where does the week's data come from today?", "basis": "Data 2"},
    {"slot": 2, "question": "Which seat is hardest to fill?", "basis": "People 4"},
    {"slot": 3, "question": "What stops the process being written down?", "basis": "x"},
    {"slot": 9, "question": "A question for a slot nobody asked for?", "basis": "x"},
    {"slot": "snapshot", "question": "What would break if Jen were out for a week?",
     "basis": "Scheduling is in Jen's head"},
    {"slot": "snapshot", "question": "Second gap?", "basis": "y"},
    {"slot": "snapshot", "question": "Third gap, one too many?", "basis": "z"},
])


@pytest.mark.django_db
def test_claude_words_the_slots_and_nothing_is_asked_until_accepted(session, fake_claude):
    precall(session)
    fake_claude.reply = REPLY
    before = json.dumps(session.template_snapshot, sort_keys=True)
    made = diagnostic.propose(session)
    assert [p.rule for p in made] == ["lowest_rating"] * 3 + ["snapshot_gap"] * 2, \
        "the unasked-for slot and the third gap are dropped; five at most"
    assert all(p.state == "proposed" for p in made)
    session.refresh_from_db()
    assert json.dumps(session.template_snapshot, sort_keys=True) == before, \
        "guardrail 1: proposed, never asked"
    # The fixed five are still what the diagnostic asks.
    assert [k for c, k in codes(session.template_snapshot) if c == "diagnostic"] == \
        list(seed.FOCUSED_FALLBACK_KEYS)


@pytest.mark.django_db
def test_claude_is_given_only_the_precall_answers(session, fake_claude):
    """Guardrail 2: the input is the answers and the slots, nothing else."""
    precall(session)
    answer(session, "n1_why_now", {"text": "MARKERLIVEANSWER"})
    fake_claude.reply = "[]"
    diagnostic.propose(session)
    sent = fake_claude.requests[-1]
    assert "Assert nothing that is not in the answers" in sent["system"]
    user = sent["messages"][0]["content"]
    assert "Jen's head" in user and "MARKERLIVEANSWER" not in user


@pytest.mark.django_db
def test_accepting_adds_it_to_the_session_and_never_displaces_the_must_asks(
    session, fake_claude, ff, api
):
    precall(session)
    fake_claude.reply = REPLY
    made = diagnostic.propose(session)
    client = api.as_(ff)
    edited = client.patch(f"/api/strategy-diagnostic-proposals/{made[0].pk}/",
                          {"prompt": "Where do this week's numbers come from?"},
                          content_type="application/json")
    assert edited.status_code == 200
    assert client.post(f"/api/strategy-diagnostic-proposals/{made[0].pk}/accept/"
                       ).status_code == 200
    session.refresh_from_db()
    diag = [k for c, k in codes(session.template_snapshot) if c == "diagnostic"]
    made[0].refresh_from_db()
    assert diag == [made[0].question_key] and diag[0].startswith("dx_"), \
        "the accepted question is the section; the fixed five step aside"
    question = services.question_in(session.template_snapshot, diag[0])
    assert question["prompt"] == "Where do this week's numbers come from?"
    # Guardrail 3: §1's must-asks are exactly as they were.
    assert [k for c, k in codes(session.template_snapshot) if c == "what_you_need"] == [
        "n1_why_now", "n1_tried", "n1_this_seat", "s3_stalled_goal"]
    assert services.must_ask_outstanding(session)["of"] == 3
    # And it is answered like any other question.
    answer(session, diag[0], {"said": "From the office manager's sheet",
                              "cause": "", "tried": ""})
    assert services.answers_of(session)[diag[0]].value["said"]


@pytest.mark.django_db
def test_the_diagnostic_holds_five(session, fake_claude, ff, api):
    precall(session)
    client = api.as_(ff)
    for n in range(6):
        StrategyDiagnosticProposal.objects.create(
            tenant=session.tenant, session=session, rule="lowest_rating",
            prompt=f"Question {n}?")
    ids = list(StrategyDiagnosticProposal.objects.values_list("pk", flat=True))
    codes_ = [client.post(f"/api/strategy-diagnostic-proposals/{pk}/accept/").status_code
              for pk in ids]
    assert codes_ == [200] * 5 + [409]


@pytest.mark.django_db
def test_completing_the_form_queues_the_proposal_on_the_worker(session, fake_claude):
    raw = services.issue_precall_token(session)
    precall(session)
    with mock.patch("django_q.tasks.async_task") as queued:
        from django.test import Client

        assert Client().post(f"/api/strategy/precall/{raw}/complete").status_code == 200
    queued.assert_called_once_with("apps.strategy.tasks.propose_diagnostic",
                                   str(session.tenant_id), str(session.pk))
    assert fake_claude.requests == [], "the prospect is not kept waiting on Claude"

    from apps.strategy import tasks

    fake_claude.reply = REPLY
    assert tasks.propose_diagnostic(str(session.tenant_id), str(session.pk)) == 5
    assert AiCall.objects.get(purpose=diagnostic.PURPOSE).unattended is True, \
        "worker spend counts against the daily cap"


@pytest.mark.django_db
def test_a_classic_session_gets_no_proposals(seeded_tenant, classic, prospect, ff,
                                             fake_claude):
    old = services.start(tenant=seeded_tenant, contact=prospect, template=classic,
                         owner=ff.user)
    assert diagnostic.propose(old) == []
    assert fake_claude.requests == []


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["VA", "CF"])
def test_role_boundaries_only_the_fractional_runs_the_diagnostic_tray(
    role, session, seeded_tenant, api
):
    proposal = StrategyDiagnosticProposal.objects.create(
        tenant=session.tenant, session=session, rule="growth", prompt="Q?")
    client = api.as_(MembershipFactory(tenant=seeded_tenant, role=role))
    status = client.post(f"/api/strategy-diagnostic-proposals/{proposal.pk}/accept/"
                         ).status_code
    assert status in (403, 404)
    proposal.refresh_from_db()
    assert proposal.state == "proposed"


@pytest.mark.django_db
def test_tenant_isolation_another_practices_proposal_is_not_reachable(session, tenant_b, api):
    from apps.tenancy.context import tenant_context

    proposal = StrategyDiagnosticProposal.objects.create(
        tenant=session.tenant, session=session, rule="growth", prompt="Q?")
    with tenant_context(tenant_b.pk):
        outsider = MembershipFactory(tenant=tenant_b, role="FF")
    assert api.as_(outsider).post(
        f"/api/strategy-diagnostic-proposals/{proposal.pk}/accept/").status_code == 404


# ============================================== map rows, header and statement

ROWS_REPLY = json.dumps([{"header": "Weekend Sites Need a Lead", "statement":
                          "Every weekend site has a named lead, so nothing is missed.",
                          "bottleneck": "Weekend sites have no lead", "root_cause": "",
                          "the_fix": "", "owner_text": "", "horizon": 30,
                          "measurable": ""}])


@pytest.mark.django_db
def test_a_drafted_row_carries_a_header_and_a_statement(session, fake_claude):
    answer(session, "n1_why_now", {"text": "Weekend sites keep getting missed."})
    fake_claude.reply = ROWS_REPLY
    [row] = ai.draft_map_rows(session)
    assert (row.header, row.proposed_header) == ("Weekend Sites Need a Lead",) * 2
    assert row.statement.startswith("Every weekend site") and row.proposed_statement


@pytest.mark.django_db
def test_the_focused_map_holds_five_and_a_classic_one_does_not(session, seeded_tenant,
                                                               classic, prospect, ff, api):
    def rows_for(s, n):
        return [StrategyMapRow.objects.create(tenant=s.tenant, session=s, position=i,
                                              bottleneck=f"B{i}") for i in range(n)]

    client = api.as_(ff)
    statuses = [client.post(f"/api/strategy-map-rows/{r.pk}/accept/").status_code
                for r in rows_for(session, 6)]
    assert statuses == [200] * 5 + [409]
    old = services.start(tenant=seeded_tenant, contact=prospect, template=classic,
                         owner=ff.user)
    assert {client.post(f"/api/strategy-map-rows/{r.pk}/accept/").status_code
            for r in rows_for(old, 6)} == {200}


@pytest.mark.django_db
def test_consolidate_on_a_focused_map_aims_for_three_to_five(session, fake_claude):
    for i in range(8):
        StrategyMapRow.objects.create(tenant=session.tenant, session=session, position=i,
                                      bottleneck=f"Bottleneck {i}")
    fake_claude.reply = json.dumps([{"header": f"Target {i}", "statement": "s",
                                     "bottleneck": f"Merged {i}", "merges": [i + 1]}
                                    for i in range(7)])
    made = ai.consolidate_map_rows(session)
    assert len(made) == 5
    assert "never more than five" in fake_claude.requests[-1]["system"]


# ================================================================== the PDF

LONG = ("This is a long focus statement that must never be cut short, because a "
        "prospect reading the map deserves the whole sentence and not an ellipsis. " * 3)


@pytest.mark.django_db
def test_three_rows_are_three_full_width_cards_with_nothing_truncated(session):
    for i, horizon in enumerate((90, 30, 60)):
        StrategyMapRow.objects.create(
            tenant=session.tenant, session=session, position=i, horizon=horizon,
            bottleneck=f"Bottleneck {i}", header=f"Header {i}", statement=LONG,
            state=StrategyMapRow.State.ACCEPTED)
    session.mirror_goal = "Win two contracts. Stop working weekends."
    session.mirror_unlocks = "Supervisors who audit. A price book."
    session.save()
    html = pdf_service.render_html(session)
    assert html.count('class="fcard"') == 3
    assert html.count(LONG.strip()) == 3, "every statement in full"
    assert "…" not in html.split("The strategy map")[1].split("</section>")[0]
    assert html.index("30 days") < html.index("60 days") < html.index("90 days")
    assert "<li>Win two contracts.</li><li>Stop working weekends.</li>" in html
    assert "<li>Supervisors who audit.</li><li>A price book.</li>" in html
    assert pdf_service.render_pdf(session).startswith(b"%PDF"), "WeasyPrint renders it"


@pytest.mark.django_db
def test_a_classic_pdf_is_laid_out_as_before(seeded_tenant, classic, prospect, ff):
    old = services.start(tenant=seeded_tenant, contact=prospect, template=classic,
                         owner=ff.user)
    StrategyMapRow.objects.create(tenant=old.tenant, session=old, bottleneck="B",
                                  horizon=30, state=StrategyMapRow.State.ACCEPTED)
    old.mirror_goal = "One. Two."
    old.save()
    html = pdf_service.render_html(old)
    assert 'class="lanes"' in html and 'class="fcard"' not in html
    assert '<p class="said">One. Two.</p>' in html


# ============================================== learning from the practice's edits

@pytest.mark.django_db
def test_an_edit_before_acceptance_is_kept_and_reaches_the_next_prompt(
    session, fake_claude, ff, api
):
    row = StrategyMapRow.objects.create(
        tenant=session.tenant, session=session, bottleneck="B",
        header="Missed Weekend Inspections", proposed_header="Missed Weekend Inspections",
        statement="Claude's statement.", proposed_statement="Claude's statement.")
    client = api.as_(ff)
    client.patch(f"/api/strategy-map-rows/{row.pk}/",
                 {"header": "Weekends Get a Lead", "statement": "Their own statement."},
                 content_type="application/json")
    client.post(f"/api/strategy-map-rows/{row.pk}/accept/")
    pairs = {(e.kind, e.proposed, e.accepted) for e in StrategyStyleExample.objects.all()}
    assert pairs == {("map_header", "Missed Weekend Inspections", "Weekends Get a Lead"),
                     ("map_statement", "Claude's statement.", "Their own statement.")}

    answer(session, "n1_why_now", {"text": "Something is breaking."})
    fake_claude.reply = "[]"
    ai.draft_map_rows(session)
    prompt = fake_claude.requests[-1]["messages"][0]["content"]
    assert 'drafted "Missed Weekend Inspections" → kept "Weekends Get a Lead"' in prompt


@pytest.mark.django_db
def test_an_edit_after_acceptance_updates_the_pair_and_editing_back_removes_it(
    session, ff, api
):
    note = StrategyPathNote.objects.create(
        tenant=session.tenant, session=session, path="b", kind="con",
        text="Claude's con.", proposed_text="Claude's con.")
    client = api.as_(ff)
    client.post(f"/api/strategy-path-notes/{note.pk}/accept/")
    assert not StrategyStyleExample.objects.exists(), "unedited: nothing to learn"
    client.patch(f"/api/strategy-path-notes/{note.pk}/", {"text": "Their con."},
                 content_type="application/json")
    assert StrategyStyleExample.objects.get().accepted == "Their con."
    client.patch(f"/api/strategy-path-notes/{note.pk}/", {"text": "Claude's con."},
                 content_type="application/json")
    assert not StrategyStyleExample.objects.exists()


@pytest.mark.django_db
def test_pros_and_cons_prompts_carry_the_twelve_most_recent_pairs(session, fake_claude):
    for n in range(15):
        StrategyStyleExample.objects.create(
            tenant=session.tenant, kind="pro", proposed=f"drafted {n:02}",
            accepted=f"kept {n:02}", source_type="strategy_path_note",
            source_id=__import__("uuid").uuid4())
    block = style.prompt_block(session.tenant, [style.K.PRO, style.K.CON])
    kept = [line for line in block.splitlines() if line.startswith("- ")]
    assert len(kept) == 12
    assert "kept 14" in block and "kept 02" not in block, "the most recent twelve"


@pytest.mark.django_db
def test_tenant_isolation_nothing_from_another_practice_reaches_a_prompt(
    session, tenant_b, fake_claude
):
    from apps.tenancy.context import tenant_context

    with tenant_context(tenant_b.pk):
        StrategyStyleExample.all_objects.create(
            tenant=tenant_b, kind="map_header", proposed="THEIRS-DRAFTED",
            accepted="THEIRS-KEPT", source_type="strategy_map_row",
            source_id=__import__("uuid").uuid4())
    StrategyStyleExample.objects.create(
        tenant=session.tenant, kind="map_header", proposed="OURS-DRAFTED",
        accepted="OURS-KEPT", source_type="strategy_map_row",
        source_id=__import__("uuid").uuid4())
    answer(session, "n1_why_now", {"text": "Something is breaking."})
    fake_claude.reply = "[]"
    ai.draft_map_rows(session)
    prompt = fake_claude.requests[-1]["messages"][0]["content"]
    assert "OURS-KEPT" in prompt
    assert "THEIRS" not in prompt
