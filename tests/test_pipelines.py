"""Multiple pipelines (owner, Check 1).

The owner's real CRM runs a sales pipeline for prospects and a nurture pipeline
for referral partners, and carries both a Status (type) column and a separate
Stage column. The app had collapsed all of that into one fixed funnel.
"""

from __future__ import annotations

import pytest

from apps.crm.models import (
    ContactPipelinePosition, OutboxMessage, Pipeline, PipelineStage,
    StageChange, StageSemantic, Task,
)
from apps.crm.services import importer, pipeline, referral
from apps.tenancy.context import tenant_context

from . import registry_config  # noqa: F401
from .factories import (
    CompanyFactory, ContactEmailFactory, ContactFactory, ContactPhoneFactory,
    ContactPipelinePositionFactory, EmailTemplateFactory, PipelineStageFactory,
    StageAutomationFactory,
)


def _contact(tenant, **kw):
    contact = ContactFactory(tenant=tenant, **kw)
    ContactEmailFactory(tenant=tenant, contact=contact)
    return contact


# ------------------------------------------------------------------- seeding

@pytest.mark.django_db
def test_two_pipelines_are_seeded_with_the_owners_real_stages(seeded_tenant, sales, referrals):
    assert sales.kind == Pipeline.Kind.SALES
    assert referrals.kind == Pipeline.Kind.REFERRAL

    sales_stages = list(
        PipelineStage.all_objects.filter(pipeline=sales).order_by("position")
    )
    assert [s.label for s in sales_stages] == [
        "Initial Contact Made", "Prospecting", "Follow Up Needed", "Qualified",
        "Consult Given", "Proposal Given", "Decision Making", "Negotiation",
        "Closed Won", "Closed Lost", "Nurture",
    ]
    assert [s.semantic for s in sales_stages] == [
        "entry", "working", "working", "qualified", "qualified", "qualified",
        "qualified", "qualified", "won", "lost", "parked",
    ]

    referral_stages = list(
        PipelineStage.all_objects.filter(pipeline=referrals).order_by("position")
    )
    assert [s.label for s in referral_stages] == [
        "New Partner", "Follow-up Sent", "Flyer Sent", "Nurturing",
        "Active Referrer", "Dormant",
    ]
    assert [s.semantic for s in referral_stages] == [
        "entry", "working", "working", "working", "qualified", "parked",
    ]


@pytest.mark.django_db
def test_the_old_six_stage_seed_is_gone(seeded_tenant):
    """It was a guess, and it is not what the owner's CRM does."""
    codes = set(
        PipelineStage.all_objects.filter(tenant=seeded_tenant).values_list("code", flat=True)
    )
    assert not ({"contact", "lead", "qualified_lead", "client", "lost"} & codes)


@pytest.mark.django_db
def test_the_same_code_may_exist_in_two_pipelines(seeded_tenant, sales, referrals):
    """Codes are unique per pipeline, not per tenant — "Qualified" is a
    legitimate stage name in both."""
    PipelineStageFactory(
        tenant=seeded_tenant, pipeline=referrals, code="qualified", label="Qualified",
    )
    assert PipelineStage.all_objects.filter(
        tenant=seeded_tenant, code="qualified"
    ).count() == 2


# -------------------------------------------------------- semantics not labels

@pytest.mark.django_db
def test_renaming_the_won_stage_does_not_break_the_client_invariant(
    seeded_tenant, sales, stages, types, ff
):
    """The FF renames stages freely; behaviour keys on `semantic`, never the
    label. This is the whole reason `semantic` exists."""
    won = stages["closed_won"]
    won.label = "Signed and Sealed"
    won.code = "signed"
    won.save(update_fields=["label", "code", "updated_at"])

    with tenant_context(seeded_tenant.pk):
        company = CompanyFactory(tenant=seeded_tenant, is_client_company=False)
        contact = _contact(seeded_tenant, company=company)
        pipeline.change_stage(contact, won, actor=ff.user)

        company.refresh_from_db()
        assert company.is_client_company is True
        assert contact.type_links.filter(contact_type__code="client").exists()


@pytest.mark.django_db
def test_a_won_stage_in_the_referral_pipeline_is_not_a_sale(
    seeded_tenant, referrals, ff
):
    """FR-1.6a clause 5 — a nurture pipeline reaching its end state must never
    flag a company as a client company."""
    won = PipelineStageFactory(
        tenant=seeded_tenant, pipeline=referrals, code="won_partner",
        label="Won Partner", semantic=StageSemantic.WON,
    )
    with tenant_context(seeded_tenant.pk):
        company = CompanyFactory(tenant=seeded_tenant, is_client_company=False)
        contact = _contact(seeded_tenant, company=company)
        pipeline.change_stage(contact, won, actor=ff.user)

        company.refresh_from_db()
        assert company.is_client_company is False
        assert not contact.type_links.filter(contact_type__code="client").exists()


# --------------------------------------------------------- pipeline integrity

@pytest.mark.django_db
def test_a_sales_pipeline_may_hold_only_one_won_stage(seeded_tenant, sales):
    """Enforced by a partial unique index, not by hope."""
    from django.db.utils import IntegrityError

    with pytest.raises(IntegrityError):
        PipelineStageFactory(
            tenant=seeded_tenant, pipeline=sales, code="also_won", label="Also Won",
            semantic=StageSemantic.WON,
        )


@pytest.mark.django_db
def test_removing_the_only_won_stage_from_a_sales_pipeline_is_refused(
    seeded_tenant, sales, stages, ff, api
):
    """Without one, nothing can ever become a client — a failure that would
    otherwise surface at the worst possible moment."""
    response = api.as_(ff).delete(f"/api/pipeline-stages/{stages['closed_won'].pk}/")

    assert response.status_code == 400
    assert "exactly one stage marked won" in str(response.json())
    assert PipelineStage.all_objects.filter(pk=stages["closed_won"].pk).exists()


@pytest.mark.django_db
def test_a_stage_holding_contacts_cannot_be_deleted(seeded_tenant, sales, stages, ff, api):
    contact = _contact(seeded_tenant)
    ContactPipelinePositionFactory(
        tenant=seeded_tenant, contact=contact, pipeline=sales, stage=stages["qualified"],
    )
    response = api.as_(ff).delete(f"/api/pipeline-stages/{stages['qualified'].pk}/")

    assert response.status_code == 400
    assert "still holds 1 contacts" in str(response.json())


@pytest.mark.django_db
def test_an_ff_may_rename_and_reorder_stages(seeded_tenant, sales, stages, ff, api):
    response = api.as_(ff).patch(
        f"/api/pipeline-stages/{stages['prospecting'].pk}/",
        {"label": "Working It", "position": 0}, content_type="application/json",
    )
    assert response.status_code == 200
    stages["prospecting"].refresh_from_db()
    assert stages["prospecting"].label == "Working It"
    # Semantic is untouched by a rename, so behaviour is untouched too.
    assert stages["prospecting"].semantic == "working"


# ------------------------------------------------------- automations per pipeline

@pytest.mark.django_db
def test_an_automation_fires_only_in_its_own_pipeline(
    seeded_tenant, sales, referrals, stages, referral_stages, ff, dev_outbox
):
    """A "becomes Qualified" rule on Sales must not fire for the referral
    pipeline's own qualified stage."""
    StageAutomationFactory(
        tenant=seeded_tenant, pipeline=sales, to_stage=stages["qualified"],
        action_type="create_task", task_title_template="Sales follow-up",
    )

    with tenant_context(seeded_tenant.pk):
        partner = _contact(seeded_tenant)
        pipeline.change_stage(partner, referral_stages["active_referrer"], actor=ff.user)
        assert Task.objects.filter(contact=partner).count() == 0

        prospect = _contact(seeded_tenant)
        pipeline.change_stage(prospect, stages["qualified"], actor=ff.user)
        assert Task.objects.filter(contact=prospect).count() == 1

    assert dev_outbox == []


# --------------------------------------------------------- referral onboarding

@pytest.mark.django_db
def test_onboarding_places_a_partner_at_the_referral_entry_stage(
    seeded_tenant, referrals, referral_stages, ff
):
    """FR-1.23 — and as an ordinary stage_change, not a second hidden path."""
    with tenant_context(seeded_tenant.pk):
        contact = _contact(seeded_tenant)
        referral.add_type(contact, "referral_partner", actor=ff.user)

        position = pipeline.position_for(contact, referrals)
        assert position is not None
        assert position.stage.code == "new_partner"
        assert StageChange.objects.filter(
            contact=contact, pipeline=referrals, to_stage__code="new_partner"
        ).exists()


@pytest.mark.django_db
def test_onboarding_does_not_disturb_an_existing_sales_position(
    seeded_tenant, sales, stages, referrals, ff
):
    """A live prospect who becomes a referral partner keeps their sales stage."""
    with tenant_context(seeded_tenant.pk):
        contact = _contact(seeded_tenant)
        pipeline.change_stage(contact, stages["negotiation"], actor=ff.user)
        referral.add_type(contact, "referral_partner", actor=ff.user)

        positions = {p.pipeline.name: p.stage.code for p in pipeline.positions_of(contact)}
        assert positions == {"Sales": "negotiation", "Referral partners": "new_partner"}


@pytest.mark.django_db
def test_type_does_not_gate_pipeline_membership(seeded_tenant, referrals, referral_stages, ff):
    """A contact may sit in the referral pipeline without carrying the type,
    and vice versa: they are two different facts."""
    with tenant_context(seeded_tenant.pk):
        contact = _contact(seeded_tenant)
        pipeline.change_stage(contact, referral_stages["nurturing"], actor=ff.user)

        assert pipeline.position_for(contact, referrals) is not None
        assert not contact.type_links.filter(
            contact_type__code="referral_partner"
        ).exists()


# ---------------------------------------------------------------------- board

@pytest.mark.django_db
def test_the_board_endpoint_returns_one_column_per_stage(
    seeded_tenant, sales, stages, ff, api
):
    contact = _contact(seeded_tenant)
    ContactPipelinePositionFactory(
        tenant=seeded_tenant, contact=contact, pipeline=sales, stage=stages["qualified"],
    )
    body = api.as_(ff).get(f"/api/pipelines/{sales.pk}/board/").json()

    assert body["pipeline"]["name"] == "Sales"
    assert len(body["columns"]) == 11
    qualified = next(c for c in body["columns"] if c["stage"]["code"] == "qualified")
    assert qualified["count"] == 1
    assert qualified["contacts"][0]["id"] == str(contact.pk)


@pytest.mark.django_db
def test_a_board_shows_only_what_the_role_may_see(
    seeded_tenant, sales, stages, cf, ff, api
):
    """FR-1.9c — a CF's board is their assigned universe, not the tenant's."""
    contact = _contact(seeded_tenant)
    ContactPipelinePositionFactory(
        tenant=seeded_tenant, contact=contact, pipeline=sales, stage=stages["qualified"],
    )
    body = api.as_(cf).get(f"/api/pipelines/{sales.pk}/board/").json()

    assert sum(c["count"] for c in body["columns"]) == 0
    assert sum(c["count"] for c in api.as_(ff).get(
        f"/api/pipelines/{sales.pk}/board/").json()["columns"]) == 1


@pytest.mark.django_db
def test_board_cards_carry_the_company_name(seeded_tenant, sales, stages, ff, api):
    """The card shows the company; the contact payload only carries its id."""
    company = CompanyFactory(tenant=seeded_tenant, name="Acme Freight")
    with_company = _contact(seeded_tenant, last_name="Abbott", company=company)
    without = _contact(seeded_tenant, last_name="Baker")
    for contact in (with_company, without):
        ContactPipelinePositionFactory(
            tenant=seeded_tenant, contact=contact, pipeline=sales,
            stage=stages["qualified"],
        )
    body = api.as_(ff).get(f"/api/pipelines/{sales.pk}/board/").json()

    cards = next(
        c for c in body["columns"] if c["stage"]["code"] == "qualified")["contacts"]
    assert [c["company_name"] for c in cards] == ["Acme Freight", ""]


@pytest.mark.django_db
def test_board_cards_come_back_by_name(seeded_tenant, sales, stages, ff, api):
    for last, first in [("Reyes", "Dana"), ("Abbott", "Zoe"), ("Abbott", "Al")]:
        ContactPipelinePositionFactory(
            tenant=seeded_tenant, pipeline=sales, stage=stages["qualified"],
            contact=_contact(seeded_tenant, last_name=last, first_name=first),
        )
    body = api.as_(ff).get(f"/api/pipelines/{sales.pk}/board/").json()

    cards = next(
        c for c in body["columns"] if c["stage"]["code"] == "qualified")["contacts"]
    assert [(c["last_name"], c["first_name"]) for c in cards] == [
        ("Abbott", "Al"), ("Abbott", "Zoe"), ("Reyes", "Dana"),
    ]


def _fill(tenant, pipeline_row, stage, how_many):
    for n in range(how_many):
        ContactPipelinePositionFactory(
            tenant=tenant, pipeline=pipeline_row, stage=stage,
            contact=ContactFactory(tenant=tenant, last_name=f"Person{n:03d}"),
        )


def _column(body, code):
    return next(c for c in body["columns"] if c["stage"]["code"] == code)


@pytest.mark.django_db
def test_a_long_column_loads_100_until_it_is_expanded(seeded_tenant, sales, stages, ff, api):
    """The board's "Show more": `expand` lifts the cap for the columns named."""
    _fill(seeded_tenant, sales, stages["qualified"], 103)
    url = f"/api/pipelines/{sales.pk}/board/"

    capped = _column(api.as_(ff).get(url).json(), "qualified")
    assert (capped["count"], capped["matched"], len(capped["contacts"])) == (103, 103, 100)

    full = _column(
        api.as_(ff).get(url, {"expand": str(stages["qualified"].pk)}).json(), "qualified")
    assert len(full["contacts"]) == 103


@pytest.mark.django_db
def test_board_search_reaches_cards_that_are_not_loaded(seeded_tenant, sales, stages, ff, api):
    """Person102 sorts past the first 100, and the search still finds them."""
    _fill(seeded_tenant, sales, stages["qualified"], 103)
    body = api.as_(ff).get(
        f"/api/pipelines/{sales.pk}/board/", {"q": "person102"}).json()

    column = _column(body, "qualified")
    assert body["q"] == "person102"
    assert (column["count"], column["matched"]) == (103, 1)
    assert [c["last_name"] for c in column["contacts"]] == ["Person102"]


@pytest.mark.django_db
def test_board_search_matches_name_company_email_and_phone(
    seeded_tenant, sales, stages, ff, api
):
    company = CompanyFactory(tenant=seeded_tenant, name="Acme Freight")
    by_company = ContactFactory(tenant=seeded_tenant, last_name="A", company=company)
    by_name = ContactFactory(tenant=seeded_tenant, first_name="Dana", last_name="Reyes")
    by_email = ContactFactory(tenant=seeded_tenant, last_name="C")
    ContactEmailFactory(tenant=seeded_tenant, contact=by_email, address="zed@quux.invalid")
    # Two addresses that both match must still be one card.
    ContactEmailFactory(tenant=seeded_tenant, contact=by_email, address="zed2@quux.invalid",
                        is_primary=False)
    by_phone = ContactFactory(tenant=seeded_tenant, last_name="D")
    ContactPhoneFactory(tenant=seeded_tenant, contact=by_phone, number="18575550100")
    for contact in (by_company, by_name, by_email, by_phone):
        ContactPipelinePositionFactory(
            tenant=seeded_tenant, contact=contact, pipeline=sales,
            stage=stages["qualified"],
        )
    url = f"/api/pipelines/{sales.pk}/board/"

    def found(q):
        column = _column(api.as_(ff).get(url, {"q": q}).json(), "qualified")
        assert column["matched"] == len(column["contacts"])
        return [c["id"] for c in column["contacts"]]

    assert found("acme") == [str(by_company.pk)]
    assert found("dana rey") == [str(by_name.pk)]
    assert found("quux") == [str(by_email.pk)]
    assert found("5550100") == [str(by_phone.pk)]


@pytest.mark.django_db
def test_board_search_and_expand_stay_inside_what_the_role_may_see(
    seeded_tenant, sales, stages, cf, api
):
    """FR-1.9c holds for the new parameters too."""
    contact = _contact(seeded_tenant, last_name="Findable")
    ContactPipelinePositionFactory(
        tenant=seeded_tenant, contact=contact, pipeline=sales, stage=stages["qualified"],
    )
    body = api.as_(cf).get(
        f"/api/pipelines/{sales.pk}/board/",
        {"q": "findable", "expand": str(stages["qualified"].pk)},
    ).json()

    assert sum(len(c["contacts"]) for c in body["columns"]) == 0
    assert sum(c["matched"] for c in body["columns"]) == 0


# --------------------------------------------------------------------- import

@pytest.mark.django_db
def test_a_stage_column_maps_into_a_chosen_pipeline(seeded_tenant, sales, stages, ff):
    """The owner's file has a Stage column separate from Status; the wizard asks
    which pipeline it belongs to, once, for the whole column."""
    header = "first_name,last_name,email,stage\n"
    csv = (header + "Dana,Reyes,d@a.invalid,Negotiation\n").encode()
    mapping = {"first_name": "first_name", "last_name": "last_name",
               "email": "email", "stage": "pipeline_stage"}
    value_mapping = {"pipeline_stage": {
        "column": "stage", "pipeline": "Sales",
        "values": {"Negotiation": {"stage": "negotiation"}},
    }}

    with tenant_context(seeded_tenant.pk):
        batch = importer.dry_run(
            tenant=seeded_tenant, filename="c.csv", file_bytes=csv,
            mapping=mapping, value_mapping=value_mapping, actor=ff.user,
        )
        assert batch.counts["error"] == 0
        assert batch.rows.first().preview["placements"] == [{
            "pipeline": "Sales", "stage": "Negotiation", "stage_code": "negotiation",
            "semantic": "qualified", "from_column": "pipeline_stage",
            "fires_client_invariant": False,
        }]
        importer.commit(batch, actor=ff.user)

        from apps.crm.models import Contact

        contact = Contact.objects.get(first_name="Dana")
        assert contact.pipeline_positions.get().stage.code == "negotiation"


@pytest.mark.django_db
def test_status_and_stage_columns_place_a_contact_in_both_pipelines(
    seeded_tenant, sales, referrals, stages, referral_stages, ff
):
    """Both columns map at once, and a contact lands in both pipelines — the
    case the single fixed pipeline could not represent at all."""
    header = "first_name,last_name,email,status,stage\n"
    csv = (header + "Dana,Reyes,d@a.invalid,Referral Partner,Negotiation\n").encode()
    mapping = {"first_name": "first_name", "last_name": "last_name",
               "email": "email", "status": "contact_type", "stage": "pipeline_stage"}
    value_mapping = {
        "contact_type": {"column": "status", "values": {
            "Referral Partner": {"contact_type": "referral_partner",
                                 "pipeline": "Referral partners",
                                 "stage": "active_referrer"},
        }},
        "pipeline_stage": {"column": "stage", "pipeline": "Sales", "values": {
            "Negotiation": {"stage": "negotiation"},
        }},
    }

    with tenant_context(seeded_tenant.pk):
        batch = importer.dry_run(
            tenant=seeded_tenant, filename="c.csv", file_bytes=csv,
            mapping=mapping, value_mapping=value_mapping, actor=ff.user,
        )
        assert batch.counts["error"] == 0
        importer.commit(batch, actor=ff.user)

        from apps.crm.models import Contact

        contact = Contact.objects.get(first_name="Dana")
        positions = {p.pipeline.name: p.stage.code for p in pipeline.positions_of(contact)}
        assert positions == {"Sales": "negotiation",
                             "Referral partners": "active_referrer"}
        assert "referral_partner" in [t.code for t in contact.types.all()]


@pytest.mark.django_db
def test_an_unmapped_stage_value_is_a_row_error(seeded_tenant, sales, ff):
    header = "first_name,last_name,email,stage\n"
    csv = (header + "Dana,Reyes,d@a.invalid,Negotiation\n").encode()
    mapping = {"first_name": "first_name", "last_name": "last_name",
               "email": "email", "stage": "pipeline_stage"}

    with tenant_context(seeded_tenant.pk):
        batch = importer.dry_run(
            tenant=seeded_tenant, filename="c.csv", file_bytes=csv,
            mapping=mapping, value_mapping={}, actor=ff.user,
        )
        assert batch.counts["error"] == 1
        assert "pipeline_stage" in batch.rows.first().error_text


@pytest.mark.django_db
def test_a_stage_mapping_without_a_pipeline_is_a_row_error(seeded_tenant, sales, ff):
    """The wizard asks which pipeline first; a mapping that skipped it must not
    guess at one."""
    header = "first_name,last_name,email,stage\n"
    csv = (header + "Dana,Reyes,d@a.invalid,Negotiation\n").encode()
    mapping = {"first_name": "first_name", "last_name": "last_name",
               "email": "email", "stage": "pipeline_stage"}
    value_mapping = {"pipeline_stage": {
        "column": "stage", "values": {"Negotiation": {"stage": "negotiation"}},
    }}

    with tenant_context(seeded_tenant.pk):
        batch = importer.dry_run(
            tenant=seeded_tenant, filename="c.csv", file_bytes=csv,
            mapping=mapping, value_mapping=value_mapping, actor=ff.user,
        )
        assert batch.counts["error"] == 1
        assert "no pipeline was named" in batch.rows.first().error_text
