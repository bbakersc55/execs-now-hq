"""More than one template (owner, 2026-09-26).

Duplicate, restore from seed, rename, set default, archive; the picker on
Start a session; and the rule every one of them keeps — **a session renders
from its own snapshot**, so none of this reaches a session already started.
"""

from __future__ import annotations

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.strategy import services
from apps.strategy.models import StrategyQuestion, StrategySection, StrategyTemplate
from apps.strategy.seed import (
    SECTIONS, SERVICE_BUSINESS_KEYS, TEMPLATE_NAME, neutral_prompt, seed_tenant,
)
from apps.tenancy.models import AuditEvent

from . import registry_config  # noqa: F401
from .factories import CompanyFactory, ContactFactory, MembershipFactory


@pytest.fixture
def template(seeded_tenant, in_tenant_a):
    return seed_tenant(seeded_tenant)


@pytest.fixture
def prospect(seeded_tenant):
    company = CompanyFactory(tenant=seeded_tenant, name="Acme Facilities")
    return ContactFactory(tenant=seeded_tenant, first_name="Dana", last_name="Reyes",
                          company=company)


def post(api, who, url, body=None):
    return api.as_(who).post(url, body or {}, content_type="application/json")


def seed_shape(template):
    """Every live question as the seed would have it, for comparison."""
    return sorted(
        (q.section.code, q.key, q.prompt, q.ask_when, q.response_schema, q.must_ask,
         q.area, q.has_fractional_note, q.is_fractional_observation, q.is_financial,
         q.position)
        for q in StrategyQuestion.objects.filter(template=template,
                                                 deleted_at__isnull=True)
        .select_related("section"))


# ------------------------------------------------------------ restore from seed

@pytest.mark.django_db
def test_restore_from_seed_makes_a_new_template_and_never_overwrites(template, ff, api):
    StrategyQuestion.objects.filter(template=template, key="s1_revenue").update(
        prompt="Revenue, in their words")

    made = post(api, ff, "/api/strategy-templates/restore-from-seed/",
                {"name": "Operations — generic"})
    assert made.status_code == 201, made.json()
    fresh = StrategyTemplate.objects.get(pk=made.json()["id"])

    # Exactly the seed: nine sections with their budgets, 47 questions.
    sections = StrategySection.objects.filter(template=fresh).order_by("position")
    assert [(s.code, s.title, s.time_budget_minutes) for s in sections] == [
        (code, title, budget) for code, title, budget, _q in SECTIONS]
    assert StrategyQuestion.objects.filter(template=fresh).count() == 47
    # Every seed question, industry-neutral (dry run 2): the service-business
    # three archived, and {Integrator} called {Second-in-command}.
    for code, _t, _b, questions in SECTIONS:
        for question in questions:
            row = StrategyQuestion.objects.get(template=fresh, key=question["key"])
            assert row.section.code == code
            assert row.prompt == neutral_prompt(question["prompt"], question["key"])
            assert (row.deleted_at is not None) == (question["key"] in
                                                     SERVICE_BUSINESS_KEYS)
    assert fresh.is_default is False

    # And the edited one is untouched.
    assert StrategyQuestion.objects.get(template=template, key="s1_revenue").prompt == \
        "Revenue, in their words"
    assert AuditEvent.all_objects.filter(
        verb="strategy.template_restored_from_seed", target_id=fresh.pk).exists()


@pytest.mark.django_db
def test_a_name_already_taken_is_refused(template, ff, api):
    refused = post(api, ff, "/api/strategy-templates/restore-from-seed/",
                   {"name": TEMPLATE_NAME.upper()})
    assert refused.status_code == 409
    assert "already a template" in refused.json()["detail"]
    assert StrategyTemplate.objects.count() == 1


# -------------------------------------------------------------------- duplicate

@pytest.mark.django_db
def test_duplicate_is_a_full_copy_under_a_new_name(template, ff, api):
    StrategyQuestion.objects.filter(template=template, key="s4_no_show").update(
        prompt="Edited, so the copy has something of its own to carry")
    gone = StrategyQuestion.objects.get(template=template, key="s7_value_5")
    from django.utils import timezone
    gone.deleted_at = timezone.now()
    gone.save()
    StrategySection.objects.filter(template=template, code="diagnostic").update(
        time_budget_minutes=30)

    made = post(api, ff, f"/api/strategy-templates/{template.pk}/duplicate/",
                {"name": "Grime Fighters (copy)"})
    assert made.status_code == 201
    copy = StrategyTemplate.objects.get(pk=made.json()["id"])
    assert copy.name == "Grime Fighters (copy)" and not copy.is_default

    assert seed_shape(copy) == seed_shape(template)
    assert StrategySection.objects.get(template=copy, code="diagnostic") \
        .time_budget_minutes == 30
    # The archived question comes across archived: its key stays spent.
    copied = StrategyQuestion.objects.get(template=copy, key="s7_value_5")
    assert copied.deleted_at is not None
    # Two templates, two sets of rows: editing the copy leaves the source alone.
    StrategyQuestion.objects.filter(template=copy, key="s1_revenue").update(prompt="X")
    assert StrategyQuestion.objects.get(template=template, key="s1_revenue").prompt != "X"


# ------------------------------------------------------ rename, default, archive

@pytest.mark.django_db
def test_rename_set_default_and_archive(template, ff, api):
    other = post(api, ff, "/api/strategy-templates/restore-from-seed/",
                 {"name": "Operations — generic"}).json()

    renamed = api.as_(ff).patch(f"/api/strategy-templates/{template.pk}/",
                                {"name": "Grime Fighters (Brett Murray)"},
                                content_type="application/json")
    assert renamed.status_code == 200
    template.refresh_from_db()
    assert template.name == "Grime Fighters (Brett Murray)"
    assert AuditEvent.all_objects.get(verb="strategy.template_renamed").payload == {
        "was": TEMPLATE_NAME, "now": "Grime Fighters (Brett Murray)"}

    # The default cannot be archived — something has to take its place first.
    refused = post(api, ff, f"/api/strategy-templates/{template.pk}/archive/")
    assert refused.status_code == 400
    assert "default" in refused.json()["detail"]

    assert post(api, ff, f"/api/strategy-templates/{other['id']}/set-default/"
                ).status_code == 200
    template.refresh_from_db()
    assert not template.is_default
    assert StrategyTemplate.objects.filter(is_default=True).count() == 1

    assert post(api, ff, f"/api/strategy-templates/{template.pk}/archive/"
                ).status_code == 200
    template.refresh_from_db()
    assert template.archived_at is not None
    # An archived template cannot be made the default, and cannot be started from.
    assert post(api, ff, f"/api/strategy-templates/{template.pk}/set-default/"
                ).status_code == 400
    assert post(api, ff, f"/api/strategy-templates/{template.pk}/unarchive/"
                ).status_code == 200
    template.refresh_from_db()
    assert template.archived_at is None


@pytest.mark.django_db
def test_only_the_ff_manages_templates(template, cf, va, api):
    for who in (cf, va):
        assert post(api, who, "/api/strategy-templates/restore-from-seed/").status_code \
            == 403
        assert post(api, who, f"/api/strategy-templates/{template.pk}/duplicate/"
                    ).status_code == 403
        assert post(api, who, f"/api/strategy-templates/{template.pk}/set-default/"
                    ).status_code == 403
        assert post(api, who, f"/api/strategy-templates/{template.pk}/archive/"
                    ).status_code == 403
        assert api.as_(who).patch(f"/api/strategy-templates/{template.pk}/",
                                  {"name": "Mine"}, content_type="application/json"
                                  ).status_code == 403
    # They still read them: the start form offers a choice.
    assert api.as_(va).get("/api/strategy-templates/").status_code == 200


@pytest.mark.django_db
def test_another_tenants_templates_are_unreachable(template, tenant_b, api):
    theirs = MembershipFactory(tenant=tenant_b, role="FF")
    assert api.as_(theirs).get("/api/strategy-templates/").json() == []
    for url in (f"/api/strategy-templates/{template.pk}/duplicate/",
                f"/api/strategy-templates/{template.pk}/set-default/",
                f"/api/strategy-templates/{template.pk}/archive/"):
        assert post(api, theirs, url).status_code == 404


# ------------------------------------------------------------- the start picker

@pytest.mark.django_db
def test_starting_from_template_a_never_reads_template_b(template, prospect, ff, api):
    b = post(api, ff, "/api/strategy-templates/restore-from-seed/",
             {"name": "Template B"}).json()
    StrategyQuestion.objects.filter(template_id=b["id"], key="s1_revenue").update(
        prompt="MARKER-B")
    post(api, ff, f"/api/strategy-templates/{b['id']}/set-default/")
    StrategyQuestion.objects.filter(template=template, key="s1_revenue").update(
        prompt="MARKER-A")

    with CaptureQueriesContext(connection) as queries:
        started = post(api, ff, "/api/strategy-sessions/",
                       {"contact": str(prospect.pk), "template": str(template.pk)})
    assert started.status_code == 201
    session = services.StrategySession.objects.get(pk=started.json()["id"])
    assert session.template_id == template.pk
    assert session.template_snapshot["template"]["id"] == str(template.pk)
    assert services.question_in(session.template_snapshot, "s1_revenue")["prompt"] == \
        "MARKER-A"
    assert "MARKER-B" not in str(session.template_snapshot)
    # B — the default — was not so much as looked up.
    assert not any(b["id"].replace("-", "") in q["sql"].replace("-", "")
                   for q in queries.captured_queries)
    assert not any('"strategy_template"."is_default"' in q["sql"].partition(" WHERE ")[2]
                   for q in queries.captured_queries)
    assert started.json()["template"]["name"] == TEMPLATE_NAME


@pytest.mark.django_db
def test_without_a_choice_the_practice_default_is_used(template, prospect, ff, api):
    b = post(api, ff, "/api/strategy-templates/restore-from-seed/",
             {"name": "Template B"}).json()
    post(api, ff, f"/api/strategy-templates/{b['id']}/set-default/")
    started = post(api, ff, "/api/strategy-sessions/", {"contact": str(prospect.pk)})
    assert started.json()["template"]["id"] == b["id"]


@pytest.mark.django_db
def test_an_archived_or_unknown_template_is_refused_not_swapped(template, prospect, ff,
                                                                api):
    b = post(api, ff, "/api/strategy-templates/restore-from-seed/",
             {"name": "Template B"}).json()
    post(api, ff, f"/api/strategy-templates/{b['id']}/archive/")
    refused = post(api, ff, "/api/strategy-sessions/",
                   {"contact": str(prospect.pk), "template": b["id"]})
    assert refused.status_code == 409
    assert "archived" in refused.json()["detail"]

    import uuid
    unknown = post(api, ff, "/api/strategy-sessions/",
                   {"contact": str(prospect.pk), "template": str(uuid.uuid4())})
    assert unknown.status_code == 404
    assert services.StrategySession.objects.count() == 0


@pytest.mark.django_db
def test_managing_templates_moves_no_session(template, prospect, ff, api):
    session = services.start(tenant=template.tenant, contact=prospect, template=template,
                             owner=ff.user)
    before = session.template_snapshot
    other = post(api, ff, "/api/strategy-templates/restore-from-seed/",
                 {"name": "Operations — generic"}).json()
    api.as_(ff).patch(f"/api/strategy-templates/{template.pk}/", {"name": "Renamed"},
                      content_type="application/json")
    post(api, ff, f"/api/strategy-templates/{other['id']}/set-default/")
    post(api, ff, f"/api/strategy-templates/{template.pk}/archive/")
    session.refresh_from_db()
    assert session.template_snapshot == before
    # And it still says what it was started from, in the name of the day.
    body = api.as_(ff).get(f"/api/strategy-sessions/{session.pk}/").json()
    assert body["template"]["name"] == TEMPLATE_NAME


@pytest.mark.django_db
def test_reseeding_a_tenant_that_chose_a_default_keeps_its_choice(template, ff, api):
    other = post(api, ff, "/api/strategy-templates/restore-from-seed/",
                 {"name": "Operations — generic"}).json()
    post(api, ff, f"/api/strategy-templates/{other['id']}/set-default/")
    api.as_(ff).patch(f"/api/strategy-templates/{template.pk}/", {"name": "Renamed"},
                      content_type="application/json")
    seed_tenant(template.tenant)
    assert StrategyTemplate.objects.get(is_default=True).pk == \
        StrategyTemplate.objects.get(pk=other["id"]).pk
