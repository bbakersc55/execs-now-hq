"""Session and template management (owner, 2026-09-26).

Reset a draft's questions, archive and delete sessions, add / remove / reorder
questions and edit section budgets, and the 60-minute Operations template.
Through all of it the snapshot rule holds: **a session renders from the
questions it took at start**, and the only thing that re-takes them is a reset
of a draft nobody has been asked.
"""

from __future__ import annotations

import json

import pytest

from apps.strategy import emails, services
from apps.strategy.models import (
    StrategyAnswer, StrategyQuestion, StrategySection, StrategySession, StrategyTemplate,
)
from apps.strategy.seed import seed_tenant
from apps.tenancy.models import AuditEvent

from . import registry_config  # noqa: F401
from .factories import CompanyFactory, ContactEmailFactory, ContactFactory, MembershipFactory

PROSPECT = StrategyAnswer.AnsweredBy.PROSPECT


@pytest.fixture
def template(seeded_tenant, in_tenant_a):
    return seed_tenant(seeded_tenant)


@pytest.fixture
def prospect(seeded_tenant):
    company = CompanyFactory(tenant=seeded_tenant, name="Acme Facilities")
    contact = ContactFactory(tenant=seeded_tenant, first_name="Dana", last_name="Reyes",
                             company=company)
    ContactEmailFactory(tenant=seeded_tenant, contact=contact,
                        address="dana@acme.invalid", is_primary=True)
    return contact


@pytest.fixture
def session(seeded_tenant, template, prospect, ff):
    return services.start(tenant=seeded_tenant, contact=prospect, template=template,
                          owner=ff.user)


@pytest.fixture
def other(template, ff, api):
    """A second template, visibly different from the first."""
    made = post(api, ff, "/api/strategy-templates/restore-from-seed/",
                {"name": "Template B"}).json()
    StrategyQuestion.objects.filter(template_id=made["id"], key="s1_revenue").update(
        prompt="MARKER-B revenue")
    return StrategyTemplate.objects.get(pk=made["id"])


def post(api, who, url, body=None):
    return api.as_(who).post(url, body or {}, content_type="application/json")


def snapshot_prompt(session, key):
    session.refresh_from_db()
    question = services.question_in(session.template_snapshot, key)
    return question["prompt"] if question else None


# ------------------------------------------------------- 1. reset the questions

@pytest.mark.django_db
def test_a_draft_nobody_has_been_asked_can_be_reset_to_another_template(
        session, other, ff, api):
    body = api.as_(ff).get(f"/api/strategy-sessions/{session.pk}/").json()
    assert body["reset_refusal"] == ""

    reset = post(api, ff, f"/api/strategy-sessions/{session.pk}/reset-questions/",
                 {"template": str(other.pk)})
    assert reset.status_code == 200, reset.json()
    assert snapshot_prompt(session, "s1_revenue") == "MARKER-B revenue"
    session.refresh_from_db()
    assert session.template_id == other.pk
    assert reset.json()["template"]["name"] == "Template B"
    event = AuditEvent.all_objects.get(verb="strategy.session_questions_reset")
    assert event.payload["now"] == "Template B"


@pytest.mark.parametrize("how", ["invite", "questions_email", "prospect_answer",
                                 "not_draft"])
@pytest.mark.django_db
def test_once_a_real_person_has_been_asked_the_reset_is_refused_and_audited(
        how, session, other, ff, api):
    if how == "invite":
        services.issue_precall_token(session)
    elif how == "questions_email":
        from django.utils import timezone
        session.precall_questions_sent_at = timezone.now()
        session.save()
    elif how == "prospect_answer":
        services.save_answer(session, question_key="s1_revenue", value={"text": "4m"},
                             answered_by=PROSPECT)
    else:
        session.state = StrategySession.State.IN_CALL
        session.save()
    before = StrategySession.objects.get(pk=session.pk).template_snapshot

    body = api.as_(ff).get(f"/api/strategy-sessions/{session.pk}/").json()
    assert "what a real person was asked" in body["reset_refusal"]

    refused = post(api, ff, f"/api/strategy-sessions/{session.pk}/reset-questions/",
                   {"template": str(other.pk)})
    assert refused.status_code == 409
    assert "what a real person was asked" in refused.json()["detail"]
    assert StrategySession.objects.get(pk=session.pk).template_snapshot == before
    assert AuditEvent.all_objects.filter(
        verb="strategy.session_questions_reset_refused", target_id=session.pk).exists()


@pytest.mark.django_db
def test_a_va_cannot_reset_questions(session, va, api):
    assert post(api, va, f"/api/strategy-sessions/{session.pk}/reset-questions/"
                ).status_code == 403


# ----------------------------------------------------- 2. archive and delete

@pytest.mark.django_db
def test_archive_moves_a_session_to_the_archived_list_and_back(session, ff, api):
    assert [s["id"] for s in api.as_(ff).get("/api/strategy-sessions/").json()] == \
        [str(session.pk)]
    session.state = StrategySession.State.COMPLETE
    session.save()

    assert post(api, ff, f"/api/strategy-sessions/{session.pk}/archive/").status_code \
        == 200
    assert api.as_(ff).get("/api/strategy-sessions/").json() == []
    archived = api.as_(ff).get("/api/strategy-sessions/?archived=1").json()
    assert [s["id"] for s in archived] == [str(session.pk)]
    # Any state; archiving does not change it.
    assert archived[0]["state"] == "complete"

    assert post(api, ff, f"/api/strategy-sessions/{session.pk}/unarchive/"
                ).status_code == 200
    assert api.as_(ff).get("/api/strategy-sessions/?archived=1").json() == []
    verbs = set(AuditEvent.all_objects.filter(target_id=session.pk)
                .values_list("verb", flat=True))
    assert {"strategy.session_archived", "strategy.session_unarchived"} <= verbs


@pytest.mark.django_db
def test_a_cf_archives_their_own_sessions_and_not_others(seeded_tenant, template,
                                                         prospect, cf, va, ff, api):
    theirs = services.start(tenant=seeded_tenant, contact=prospect, template=template,
                            owner=cf.user)
    not_theirs = services.start(tenant=seeded_tenant, contact=prospect,
                                template=template, owner=ff.user)
    assert post(api, cf, f"/api/strategy-sessions/{theirs.pk}/archive/").status_code \
        == 200
    assert post(api, cf, f"/api/strategy-sessions/{not_theirs.pk}/archive/"
                ).status_code in (403, 404)
    assert post(api, va, f"/api/strategy-sessions/{not_theirs.pk}/archive/"
                ).status_code == 403
    not_theirs.refresh_from_db()
    assert not_theirs.archived_at is None
    # And a CF never deletes, even their own.
    assert api.as_(cf).delete(f"/api/strategy-sessions/{theirs.pk}/").status_code == 403


@pytest.mark.django_db
def test_delete_is_the_ffs_from_archived_only_and_audited(session, ff, api):
    services.save_answer(session, question_key="s1_revenue", value={"text": "4m"},
                         answered_by=PROSPECT)
    refused = api.as_(ff).delete(f"/api/strategy-sessions/{session.pk}/")
    assert refused.status_code == 409
    assert "Archive the session first" in refused.json()["detail"]

    post(api, ff, f"/api/strategy-sessions/{session.pk}/archive/")
    assert api.as_(ff).delete(f"/api/strategy-sessions/{session.pk}/").status_code == 204
    assert not StrategySession.objects.filter(pk=session.pk).exists()
    assert not StrategyAnswer.objects.filter(session_id=session.pk).exists()
    event = AuditEvent.all_objects.get(verb="strategy.session_deleted")
    assert event.target_id == session.pk
    assert event.payload["contact"] == "Dana Reyes" and event.payload["answers"] == 1


@pytest.mark.django_db
def test_a_converted_session_cannot_be_deleted_and_says_why(session, ff, api):
    session.state = StrategySession.State.CONVERTED
    session.save()
    post(api, ff, f"/api/strategy-sessions/{session.pk}/archive/")
    body = api.as_(ff).get(f"/api/strategy-sessions/{session.pk}/").json()
    assert "link back" in body["delete_refusal"]
    refused = api.as_(ff).delete(f"/api/strategy-sessions/{session.pk}/")
    assert refused.status_code == 409
    assert "goals, projects and tasks link back" in refused.json()["detail"]
    assert StrategySession.objects.filter(pk=session.pk).exists()
    assert AuditEvent.all_objects.filter(verb="strategy.session_delete_refused").exists()


@pytest.mark.django_db
def test_another_tenant_cannot_archive_or_delete(session, tenant_b, api):
    theirs = MembershipFactory(tenant=tenant_b, role="FF")
    assert post(api, theirs, f"/api/strategy-sessions/{session.pk}/archive/"
                ).status_code == 404
    assert api.as_(theirs).delete(f"/api/strategy-sessions/{session.pk}/"
                                  ).status_code == 404
    assert post(api, theirs, f"/api/strategy-sessions/{session.pk}/reset-questions/"
                ).status_code == 404


# ----------------------------------- 4. add, remove, reorder, budgets

@pytest.mark.django_db
def test_add_remove_reorder_and_budgets_never_reach_an_existing_snapshot(
        session, template, ff, api, prospect, seeded_tenant):
    before = json.loads(json.dumps(session.template_snapshot))
    url = f"/api/strategy-templates/{template.pk}/"

    added = post(api, ff, f"{url}questions/", {
        "section": "diagnostic", "prompt": "Who signs off a new hire?",
        "response_schema": "diagnostic_triple", "ask_when": "live", "must_ask": True,
        "area": "People & labor", "is_financial": False, "has_fractional_note": True})
    assert added.status_code == 201, added.json()
    new = StrategyQuestion.objects.get(template=template, prompt="Who signs off a new hire?")
    assert new.must_ask and new.has_fractional_note and new.area == "People & labor"
    assert new.section.code == "diagnostic"

    assert post(api, ff, f"{url}remove-question/", {"key": "s4_no_show"}
                ).status_code == 200
    gone = StrategyQuestion.objects.get(template=template, key="s4_no_show")
    assert gone.deleted_at is not None, "archived, never hard-deleted"

    keys = list(StrategyQuestion.objects.filter(
        template=template, section__code="snapshot", deleted_at__isnull=True)
        .order_by("position").values_list("key", flat=True))
    assert post(api, ff, f"{url}reorder/", {"section": "snapshot",
                                            "keys": list(reversed(keys))}
                ).status_code == 200
    # A partial list is refused rather than half-applied.
    assert post(api, ff, f"{url}reorder/", {"section": "snapshot", "keys": keys[:2]}
                ).status_code == 400

    assert api.as_(ff).patch(url, {"sections": [{"code": "diagnostic",
                                                 "time_budget_minutes": 20}]},
                             content_type="application/json").status_code == 200
    assert StrategySection.objects.get(template=template, code="diagnostic") \
        .time_budget_minutes == 20

    # The session already started is byte for byte what it was.
    session.refresh_from_db()
    assert session.template_snapshot == before

    # A new one takes all four changes.
    fresh = services.start(tenant=seeded_tenant, contact=prospect, template=template)
    snap = fresh.template_snapshot
    assert services.question_in(snap, new.key) is not None
    assert services.question_in(snap, "s4_no_show") is None
    by_code = {s["code"]: s for s in snap["sections"]}
    assert [q["key"] for q in by_code["snapshot"]["questions"]] == list(reversed(keys))
    assert by_code["diagnostic"]["time_budget_minutes"] == 20
    # And the old session still resolves the removed question's key.
    assert services.question_in(session.template_snapshot, "s4_no_show") is not None


@pytest.mark.django_db
def test_an_added_rating_is_held_to_the_rewording_guard(template, ff, api):
    url = f"/api/strategy-templates/{template.pk}/questions/"
    refused = post(api, ff, url, {"section": "six_key_components", "ask_when": "precall",
                                  "response_schema": "rating_1_10",
                                  "prompt": "Culture — What does a good week feel like?"})
    assert refused.status_code == 400
    assert "explanation" in refused.json()["detail"]
    ok = post(api, ff, url, {"section": "six_key_components", "ask_when": "precall",
                             "response_schema": "rating_1_10",
                             "prompt": "Culture — Do people say the values out loud?"})
    assert ok.status_code == 201


@pytest.mark.django_db
def test_added_keys_are_never_reused(template, ff, api):
    url = f"/api/strategy-templates/{template.pk}/"
    keys = set()
    for _ in range(3):
        post(api, ff, f"{url}questions/", {"section": "snapshot", "prompt": "Anything else?"})
        key = StrategyQuestion.objects.filter(template=template, prompt="Anything else?",
                                              deleted_at__isnull=True).get().key
        assert key not in keys
        keys.add(key)
        post(api, ff, f"{url}remove-question/", {"key": key})


@pytest.mark.django_db
def test_only_the_ff_edits_questions(template, cf, va, api):
    url = f"/api/strategy-templates/{template.pk}/"
    for who in (cf, va):
        assert post(api, who, f"{url}questions/", {"section": "snapshot",
                                                   "prompt": "x"}).status_code == 403
        assert post(api, who, f"{url}remove-question/", {"key": "s1_revenue"}
                    ).status_code == 403
        assert post(api, who, f"{url}reorder/", {"section": "snapshot", "keys": []}
                    ).status_code == 403


# ------------------------------------------------ 5. the 60-minute template

@pytest.mark.django_db
def test_the_sixty_minute_template(template, ff, api, prospect, seeded_tenant):
    made = post(api, ff, "/api/strategy-templates/restore-from-seed/",
                {"name": "60-minute Operations", "variant": "sixty"})
    assert made.status_code == 201
    sixty = StrategyTemplate.objects.get(pk=made.json()["id"])
    budgets = dict(StrategySection.objects.filter(template=sixty)
                   .values_list("code", "time_budget_minutes"))
    assert [budgets[c] for c in ("where_they_want_to_go", "diagnostic", "mirror",
                                 "strategy_map", "two_paths", "what_they_value",
                                 "scope_agreement")] == [10, 20, 5, 10, 5, 10, 5]
    # The call's 60, plus Scope agreement's 5 (dry run 2).
    assert sum(b or 0 for b in budgets.values()) == 65

    live = StrategyQuestion.objects.filter(template=sixty, deleted_at__isnull=True)
    # Seven ★ in the seed; two of them are service-business questions the
    # industry-neutral templates archive (dry run 2), so five are live.
    assert live.filter(must_ask=True).count() == 5
    # Every live unstarred diagnostic question is ask-if-time, and nothing else.
    diagnostic = live.filter(section__code="diagnostic")
    assert diagnostic.filter(must_ask=False).count() == 6
    assert diagnostic.filter(ask_if_time=True).count() == 6
    assert not diagnostic.filter(ask_if_time=True, must_ask=True).exists()
    assert live.filter(ask_if_time=True).count() == 6
    assert sorted(live.filter(section__code="what_they_value")
                  .values_list("key", flat=True)) == ["s7_value_1", "s7_value_2",
                                                      "s7_value_3"]
    # The generic seed is untouched by any of it.
    assert StrategyQuestion.objects.filter(template=template, ask_if_time=True).count() == 0

    # The flag reaches the snapshot, and so the live view.
    s = services.start(tenant=seeded_tenant, contact=prospect, template=sixty)
    assert services.question_in(s.template_snapshot, "s4_no_show")["ask_if_time"] is True
    assert s.template_snapshot["sections"][3]["time_budget_minutes"] == 20


@pytest.mark.django_db
def test_an_ask_if_time_question_stays_out_of_the_precall_email(template, session):
    # Put one on the pre-call form so the email would otherwise carry it.
    StrategyQuestion.objects.filter(template=template, key="s3_stalled_goal").update(
        ask_when="precall", ask_if_time=True)
    StrategyQuestion.objects.filter(template=template, key="s3_current_rocks").update(
        ask_when="precall")
    fresh = services.start(tenant=session.tenant, contact=session.contact,
                           template=template)
    prompts = [p for block in emails.question_blocks(fresh) for p in block["questions"]]
    assert any("Current Rocks" in p for p in prompts)
    assert not any("on the list for over a year" in p for p in prompts)


@pytest.mark.django_db
def test_a_client_user_reaches_none_of_it(session, template, fcc, api):
    for url in (f"/api/strategy-sessions/{session.pk}/archive/",
                f"/api/strategy-sessions/{session.pk}/unarchive/",
                f"/api/strategy-sessions/{session.pk}/reset-questions/"):
        assert post(api, fcc, url).status_code == 404
    assert api.as_(fcc).delete(f"/api/strategy-sessions/{session.pk}/").status_code == 404
    for suffix in ("questions/", "remove-question/", "reorder/", "duplicate/"):
        assert post(api, fcc, f"/api/strategy-templates/{template.pk}/{suffix}"
                    ).status_code in (403, 404)
    assert api.as_(fcc).get("/api/strategy-sessions/?archived=1").json() == []


# ------------------- reload from template vs restore seed wording (dry run)

@pytest.mark.django_db
def test_reload_from_template_counts_what_changes_and_takes_todays_wording(
        session, template, ff, api):
    StrategyQuestion.objects.filter(template=template, key="s1_revenue").update(
        prompt="Revenue, in their words")
    StrategyQuestion.objects.filter(template=template, key="s1_sites").update(
        prompt="How many sites?")
    base = f"/api/strategy-sessions/{session.pk}/"

    preview = api.as_(ff).get(f"{base}reset-preview/?template={template.pk}").json()
    assert preview["changed_wording"] == ["s1_revenue", "s1_sites"]
    assert preview["added"] == [] and preview["removed"] == []
    assert preview["source"] == template.name and preview["refusal"] == ""
    # The preview writes nothing.
    assert snapshot_prompt(session, "s1_revenue") == "Revenue — last year / this year"

    assert post(api, ff, f"{base}reset-questions/", {"template": str(template.pk)}
                ).status_code == 200
    assert snapshot_prompt(session, "s1_revenue") == "Revenue, in their words"


@pytest.mark.django_db
def test_restore_seed_wording_is_the_seed_not_the_edited_template(session, template,
                                                                  ff, api):
    from apps.strategy.seed import SEED_SOURCE_NAME, SERVICE_BUSINESS_KEYS
    base = f"/api/strategy-sessions/{session.pk}/"
    # The template was edited, and the draft reloaded from it...
    StrategyQuestion.objects.filter(template=template, key="s1_revenue").update(
        prompt="Revenue, in their words")
    post(api, ff, f"{base}reset-questions/", {"template": str(template.pk)})
    assert snapshot_prompt(session, "s1_revenue") == "Revenue, in their words"

    # ...and "back to the seed" means the seed.
    preview = api.as_(ff).get(f"{base}reset-preview/?source=seed").json()
    # The edited question, and — since the seed went industry-neutral — the
    # five that name the Integrator; the three service-business ones go.
    assert "s1_revenue" in preview["changed_wording"]
    assert "s4_integrator_owns" in preview["changed_wording"]
    assert len(preview["changed_wording"]) == 6
    assert preview["removed"] == sorted(SERVICE_BUSINESS_KEYS)
    assert preview["source"] == SEED_SOURCE_NAME

    restored = post(api, ff, f"{base}restore-seed/")
    assert restored.status_code == 200, restored.json()
    assert snapshot_prompt(session, "s1_revenue") == "Revenue — last year / this year"
    session.refresh_from_db()
    assert session.template_id is None
    assert session.template_snapshot["template"]["name"] == SEED_SOURCE_NAME
    # The seed, industry-neutral: 47 less the three service-business questions.
    assert len(list(services.questions_in(session.template_snapshot))) == 44
    assert services.question_in(session.template_snapshot, "s4_done_right") is None
    # The template itself is untouched by a restore on a session.
    assert StrategyQuestion.objects.get(template=template, key="s1_revenue").prompt == \
        "Revenue, in their words"
    assert AuditEvent.all_objects.filter(verb="strategy.session_seed_restored",
                                         target_id=session.pk).exists()


@pytest.mark.django_db
def test_restore_seed_wording_is_refused_once_someone_has_been_asked(session, ff, va,
                                                                     api):
    services.issue_precall_token(session)
    before = StrategySession.objects.get(pk=session.pk).template_snapshot
    refused = post(api, ff, f"/api/strategy-sessions/{session.pk}/restore-seed/")
    assert refused.status_code == 409
    assert "what a real person was asked" in refused.json()["detail"]
    assert StrategySession.objects.get(pk=session.pk).template_snapshot == before
    assert AuditEvent.all_objects.filter(
        verb="strategy.session_seed_restore_refused").exists()
    assert post(api, va, f"/api/strategy-sessions/{session.pk}/restore-seed/"
                ).status_code == 403
    assert api.as_(va).get(f"/api/strategy-sessions/{session.pk}/reset-preview/"
                           ).status_code == 403


@pytest.mark.django_db
def test_a_reloaded_draft_shows_the_templates_new_wording_in_the_live_view(
        session, template, ff, api):
    """Dry run 2: change a template's wording, reload the draft, and the
    session the live view reads carries the new wording."""
    api.as_(ff).patch(f"/api/strategy-templates/{template.pk}/", {"questions": [
        {"key": "s4_done_right", "prompt": "How do you know the work was right?"}]},
        content_type="application/json")
    base = f"/api/strategy-sessions/{session.pk}/"
    view = lambda: {q["key"]: q["prompt"] for sec in api.as_(ff).get(base).json()["sections"]
                    for q in sec["questions"]}
    assert view()["s4_done_right"].startswith("How do you know a site")

    assert api.as_(ff).get(f"{base}reset-preview/?template={template.pk}").json()[
        "changed_wording"] == ["s4_done_right"]
    reloaded = post(api, ff, f"{base}reset-questions/", {"template": str(template.pk)})
    # The response itself carries it, so the screen can show it at once...
    assert {q["key"]: q["prompt"] for sec in reloaded.json()["sections"]
            for q in sec["questions"]}["s4_done_right"] == \
        "How do you know the work was right?"
    # ...and so does a fresh read.
    assert view()["s4_done_right"] == "How do you know the work was right?"



@pytest.mark.django_db
def test_every_live_section_has_a_budget_and_no_precall_one_does(template, ff, api):
    sixty = post(api, ff, "/api/strategy-templates/restore-from-seed/",
                 {"name": "60-minute Operations", "variant": "sixty"}).json()
    for t in (template, StrategyTemplate.objects.get(pk=sixty["id"])):
        s = services.snapshot_of(t)
        for section in s["sections"]:
            precall = bool(section["questions"]) and all(
                q["ask_when"] == "precall" for q in section["questions"])
            if precall:
                assert section["time_budget_minutes"] is None, section["code"]
            else:
                assert section["time_budget_minutes"], (t.name, section["code"])
        assert {x["code"]: x["time_budget_minutes"] for x in s["sections"]}[
            "scope_agreement"] == 5



# --------------------------------------------- industry-neutral (dry run 2)

@pytest.mark.django_db
def test_the_templates_from_the_seed_are_industry_neutral(template, ff, api,
                                                          seeded_tenant, prospect):
    from apps.strategy.seed import SERVICE_BUSINESS_KEYS
    for variant in ("", "sixty"):
        made = post(api, ff, "/api/strategy-templates/restore-from-seed/",
                    {"name": f"Neutral {variant or 'generic'}", "variant": variant}).json()
        t = StrategyTemplate.objects.get(pk=made["id"])
        live = StrategyQuestion.objects.filter(template=t, deleted_at__isnull=True)
        # The three service-business questions are archived, not deleted.
        for key in SERVICE_BUSINESS_KEYS:
            assert not live.filter(key=key).exists()
            assert StrategyQuestion.objects.get(template=t, key=key).deleted_at
        assert not live.filter(prompt__contains="{Integrator}").exists()
        assert live.filter(prompt__contains="{Second-in-command}").count() == 5
    # The template seeded for the tenant — Grime Fighters' ancestor — keeps them.
    assert StrategyQuestion.objects.get(template=template, key="s4_done_right"
                                        ).deleted_at is None

    # With nobody named, the merge field reads "your second-in-command".
    s = services.start(tenant=seeded_tenant, contact=prospect, template=t)
    body = api.as_(ff).get(f"/api/strategy-sessions/{s.pk}/").json()
    prompts = {q["key"]: q["prompt"] for sec in body["sections"] for q in sec["questions"]}
    assert prompts["s4_integrator_owns"] == (
        "What does your second-in-command own outright? Is your second-in-command "
        "empowered to say no? (no second-in-command identified yet)")
    # With someone named, their name.
    s.integrator_contact = ContactFactory(tenant=seeded_tenant, first_name="Sam",
                                          last_name="Lee")
    s.save()
    body = api.as_(ff).get(f"/api/strategy-sessions/{s.pk}/").json()
    prompts = {q["key"]: q["prompt"] for sec in body["sections"] for q in sec["questions"]}
    assert prompts["s3_three_year_picture"].endswith("Sam Lee's role")


def test_the_integrator_template_still_reads_as_it_did():
    """Brett Murray's session (Grime Fighters) keeps its own words on the call."""
    assert services.render_prompt("{Integrator}'s role", {}) == (
        "the Integrator's role (no Integrator identified yet)")


@pytest.mark.django_db
def test_the_six_statements_pass_the_guard_through_the_editor(template, ff, api):
    from apps.strategy.seed import RATING_LEAD_INS
    for key, prompt in RATING_LEAD_INS.items():
        assert "?" not in prompt
        assert api.as_(ff).patch(f"/api/strategy-templates/{template.pk}/",
                                 {"questions": [{"key": key, "prompt": prompt}]},
                                 content_type="application/json").status_code == 200
    # Statement form, same refusal words.
    refused = api.as_(ff).patch(f"/api/strategy-templates/{template.pk}/", {"questions": [
        {"key": "s2_data", "prompt": "Data — We track the numbers and know why they move."}]},
        content_type="application/json")
    assert refused.status_code == 400 and "“why”" in refused.json()["detail"]
