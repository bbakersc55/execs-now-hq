"""The "Website leads" pipeline (owner, 2026-11-09): a third pipeline beside
Sales and Referral partners, for requests from the marketing site's form.

Stages New, Contacted, Demo access given, Call booked, Converted, Not a fit.
A website lead lands in New; Converted puts the contact in the sales
pipeline's entry stage. Stage rules and follow-ups work on it as on the
others. New practices get it from the seed; a practice that already exists
adds it with one click (Settings → Stage rules)."""

from __future__ import annotations

import json

import pytest

from apps.crm.models import (
    ContactPipelinePosition, ContactType, ContactTypeLink, Pipeline, PipelineStage,
    StageAutomation, StageChange, Task,
)
from apps.crm.services import pipeline as pipeline_service
from apps.tenancy.context import tenant_context

from .factories import ContactEmailFactory, ContactFactory, ContactPipelinePositionFactory

pytestmark = pytest.mark.django_db

URL = "/api/pipelines/website-leads/"
SECRET = "site-lead-secret-for-tests"
STAGES = [("new", "New", "entry"), ("contacted", "Contacted", "working"),
          ("demo_access_given", "Demo access given", "working"),
          ("call_booked", "Call booked", "qualified"), ("converted", "Converted", "won"),
          ("not_a_fit", "Not a fit", "lost")]


def website_of(tenant):
    return Pipeline.all_objects.filter(tenant=tenant, kind=Pipeline.Kind.WEBSITE).first()


def stage_of(pipeline, code):
    return PipelineStage.all_objects.get(pipeline=pipeline, code=code)


def remove_website(tenant):
    """A practice from before 2026-11-09: Sales and Referral partners only."""
    Pipeline.all_objects.filter(tenant=tenant, kind=Pipeline.Kind.WEBSITE).delete()


def post_lead(client, settings, tenant, **over):
    settings.SITE_LEAD_TOKEN = SECRET
    settings.SITE_LEAD_PRACTICE = tenant.slug
    data = {"name": "Dana Rivera", "email": "dana@rivera-ops.com",
            "practice_name": "Rivera Operations", "wants": "demo_copy", **over}
    return client.post("/api/public/leads", json.dumps(data), content_type="application/json",
                       headers={"X-Site-Lead-Token": SECRET, "X-Lead-Client-IP": "203.0.113.5"})


def contact_named(tenant, address):
    from apps.crm.models import ContactEmail

    return ContactEmail.all_objects.get(tenant=tenant, address=address).contact


# ------------------------------------------------------------------ the seed

def test_a_new_practice_has_it_third_with_the_six_stages(seeded_tenant):
    website = website_of(seeded_tenant)
    assert website.name == "Website leads"
    names = list(Pipeline.all_objects.filter(tenant=seeded_tenant)
                 .order_by("position").values_list("name", flat=True))
    assert names == ["Sales", "Referral partners", "Website leads"]
    assert [(s.code, s.label, s.semantic) for s in PipelineStage.all_objects.filter(pipeline=website).order_by("position")] == STAGES


# --------------------------------------------------------- the one click

def test_the_practice_owner_adds_it_with_one_click_once(seeded_tenant, ff, api):
    remove_website(seeded_tenant)
    response = api.as_(ff).post(URL)
    assert response.status_code == 201
    assert response.json()["kind"] == "website"
    assert response.json()["kind_label"] == "Website leads"
    website = website_of(seeded_tenant)
    assert [(s.code, s.label, s.semantic) for s in PipelineStage.all_objects.filter(pipeline=website).order_by("position")] == STAGES
    assert website.position > pipeline_service.referral_pipeline(seeded_tenant).position

    again = api.as_(ff).post(URL)
    assert again.status_code == 200 and again.json()["id"] == str(website.pk)
    assert Pipeline.all_objects.filter(tenant=seeded_tenant, kind="website").count() == 1


def test_a_pipeline_already_named_website_leads_is_said_plainly(seeded_tenant, ff, api):
    remove_website(seeded_tenant)
    Pipeline.all_objects.create(tenant=seeded_tenant, name="Website leads", position=5)
    response = api.as_(ff).post(URL)
    assert response.status_code == 400
    assert "already has a pipeline named" in response.json()["detail"]
    assert website_of(seeded_tenant) is None


@pytest.mark.parametrize("who", ["cf", "va"])
def test_only_the_practice_owner_may_add_it(seeded_tenant, who, request, api):
    remove_website(seeded_tenant)
    assert api.as_(request.getfixturevalue(who)).post(URL).status_code == 403
    assert website_of(seeded_tenant) is None


def test_a_client_user_cannot_add_it(seeded_tenant, fcc, api):
    remove_website(seeded_tenant)
    assert api.as_(fcc).post(URL).status_code == 403
    assert website_of(seeded_tenant) is None


def test_adding_it_touches_no_other_practice(seeded_tenant, tenant_b, ff, api):
    from apps.crm.seed import seed_tenant

    seed_tenant(tenant_b)
    remove_website(seeded_tenant)
    remove_website(tenant_b)
    assert api.as_(ff).post(URL).status_code == 201
    assert website_of(seeded_tenant) is not None
    assert website_of(tenant_b) is None


def test_another_practices_website_pipeline_is_not_visible(seeded_tenant, tenant_b, ff, api):
    from apps.crm.seed import seed_tenant

    seed_tenant(tenant_b)
    theirs = website_of(tenant_b)
    ids = [p["id"] for p in api.as_(ff).get("/api/pipelines/").json()]
    assert str(theirs.pk) not in ids
    assert str(website_of(seeded_tenant).pk) in ids
    assert api.as_(ff).get(f"/api/pipelines/{theirs.pk}/board/").status_code == 404


# ------------------------------------------------------ where a lead lands

def test_a_website_lead_lands_in_new(seeded_tenant, ff, client, settings):
    assert post_lead(client, settings, seeded_tenant).status_code == 201
    dana = contact_named(seeded_tenant, "dana@rivera-ops.com")
    positions = ContactPipelinePosition.all_objects.filter(contact=dana)
    assert [(p.pipeline.kind, p.stage.code) for p in positions] == [("website", "new")]


def test_someone_already_in_new_is_not_moved_and_one_further_along_stays(
        seeded_tenant, ff, client, settings):
    website = website_of(seeded_tenant)
    with tenant_context(seeded_tenant.pk):
        dana = ContactFactory(tenant=seeded_tenant, first_name="Dana", last_name="R.")
        ContactEmailFactory(tenant=seeded_tenant, contact=dana, address="dana@rivera-ops.com")
        ContactPipelinePositionFactory(tenant=seeded_tenant, contact=dana, pipeline=website,
                                       stage=stage_of(website, "call_booked"))
    assert post_lead(client, settings, seeded_tenant).status_code == 201
    assert ContactPipelinePosition.all_objects.get(contact=dana).stage.code == "call_booked"


def test_a_sales_contact_who_asks_lands_in_new_and_keeps_their_sales_stage(
        seeded_tenant, ff, stages, sales, client, settings):
    with tenant_context(seeded_tenant.pk):
        dana = ContactFactory(tenant=seeded_tenant, first_name="Dana", last_name="R.")
        ContactEmailFactory(tenant=seeded_tenant, contact=dana, address="dana@rivera-ops.com")
        ContactPipelinePositionFactory(tenant=seeded_tenant, contact=dana, pipeline=sales,
                                       stage=stages["proposal_given"])
    assert post_lead(client, settings, seeded_tenant).status_code == 201
    held = {p.pipeline.kind: p.stage.code
            for p in ContactPipelinePosition.all_objects.filter(contact=dana)}
    assert held == {"sales": "proposal_given", "website": "new"}


def test_without_the_pipeline_a_lead_still_lands_in_sales(seeded_tenant, ff, stages, client,
                                                          settings):
    remove_website(seeded_tenant)
    assert post_lead(client, settings, seeded_tenant).status_code == 201
    dana = contact_named(seeded_tenant, "dana@rivera-ops.com")
    assert ContactPipelinePosition.all_objects.get(contact=dana).stage_id \
        == stages["initial_contact_made"].pk


def test_a_received_lead_is_logged_by_id_only(seeded_tenant, ff, client, settings, caplog):
    caplog.set_level("INFO", logger="apps.crm.services.site_leads")
    assert post_lead(client, settings, seeded_tenant).status_code == 201
    dana = contact_named(seeded_tenant, "dana@rivera-ops.com")
    line = next(r.getMessage() for r in caplog.records if "Website lead received" in r.getMessage())
    assert str(dana.pk) in line and "New in Website leads" in line and "new contact" in line
    assert "dana@" not in line and "Rivera" not in line


def test_the_honeypot_drop_is_logged(seeded_tenant, ff, client, settings, caplog):
    caplog.set_level("WARNING", logger="apps.crm.views_site_leads")
    assert post_lead(client, settings, seeded_tenant, website="https://x.example").status_code == 201
    assert any("hidden field" in r.getMessage() for r in caplog.records)


# ------------------------------------------------------------- Converted

def test_converted_puts_them_in_sales_entry_and_does_not_make_a_client(seeded_tenant, ff,
                                                                      stages, sales):
    website = website_of(seeded_tenant)
    with tenant_context(seeded_tenant.pk):
        dana = ContactFactory(tenant=seeded_tenant)
        pipeline_service.change_stage(dana, stage_of(website, "new"))
        pipeline_service.change_stage(dana, stage_of(website, "converted"), actor=ff.user)
    held = {p.pipeline.kind: p.stage.code
            for p in ContactPipelinePosition.all_objects.filter(contact=dana)}
    assert held == {"website": "converted", "sales": "initial_contact_made"}
    entry = StageChange.all_objects.get(contact=dana, pipeline=sales)
    assert entry.from_stage is None and entry.reason == "Converted in Website leads"
    assert entry.actor_id == ff.user_id
    client_type = ContactType.all_objects.get(tenant=seeded_tenant, code="client")
    assert not ContactTypeLink.all_objects.filter(contact=dana, contact_type=client_type).exists()


def test_converted_leaves_someone_already_in_sales_where_they_are(seeded_tenant, stages, sales):
    website = website_of(seeded_tenant)
    with tenant_context(seeded_tenant.pk):
        dana = ContactFactory(tenant=seeded_tenant)
        pipeline_service.change_stage(dana, stages["negotiation"])
        pipeline_service.change_stage(dana, stage_of(website, "converted"))
    assert pipeline_service.position_for(dana, sales).stage_id == stages["negotiation"].pk


def test_not_a_fit_puts_them_nowhere_else(seeded_tenant, sales):
    website = website_of(seeded_tenant)
    with tenant_context(seeded_tenant.pk):
        dana = ContactFactory(tenant=seeded_tenant)
        pipeline_service.change_stage(dana, stage_of(website, "not_a_fit"))
    assert pipeline_service.position_for(dana, sales) is None


def test_converted_runs_the_sales_entry_stage_rules(seeded_tenant, ff, stages):
    """The sales pipeline's own "enters Initial Contact Made" rule fires on the
    move Converted makes, as it would on any other way in."""
    website = website_of(seeded_tenant)
    with tenant_context(seeded_tenant.pk):
        StageAutomation.all_objects.create(
            tenant=seeded_tenant, pipeline=stages["initial_contact_made"].pipeline,
            trigger="enters", to_stage=stages["initial_contact_made"],
            action_type="create_task", task_title_template="Call {FirstName}",
            task_due_offset_days=1)
        dana = ContactFactory(tenant=seeded_tenant, first_name="Dana", owner=ff.user)
        pipeline_service.change_stage(dana, stage_of(website, "converted"), actor=ff.user)
    assert Task.all_objects.filter(tenant=seeded_tenant, title="Call Dana").exists()


# -------------------------------------------------- rules and follow-ups

def test_its_starter_rules_are_offered_and_fire(seeded_tenant, ff, api):
    website = website_of(seeded_tenant)
    offered = api.as_(ff).get(f"/api/stage-automations/examples/?pipeline={website.pk}").json()
    keys = {e["key"] for e in offered}
    assert {"website_reply_task", "demo_check_in", "contacted_quiet"} <= keys
    assert api.as_(ff).post("/api/stage-automations/examples/",
                        json.dumps({"pipeline": str(website.pk), "key": "website_reply_task"}),
                        content_type="application/json").status_code == 201
    with tenant_context(seeded_tenant.pk):
        dana = ContactFactory(tenant=seeded_tenant, first_name="Dana", last_name="Rivera",
                              owner=ff.user)
        pipeline_service.change_stage(dana, stage_of(website, "new"))
    assert Task.all_objects.filter(tenant=seeded_tenant,
                                   title="Reply to Dana Rivera's website request").exists()


def test_a_follow_up_can_be_set_on_its_stage(seeded_tenant, ff, api):
    website = website_of(seeded_tenant)
    contacted = stage_of(website, "contacted")
    response = api.as_(ff).get(f"/api/pipeline-stages/{contacted.pk}/follow-up/")
    assert response.status_code == 200
