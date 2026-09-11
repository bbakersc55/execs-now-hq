"""Import mapping targets found missing during Check 1: phone, tags, and the
contact_type value-mapping sub-step.

The value mapping is the consequential one: it is the only path by which a CSV
can put a contact into stage `client`, and FR-1.6a makes that stage the single
source of truth for "is a client" — so it has to fire the same invariant a
manual stage change fires, or the import creates clients the rest of the app
does not recognise.
"""

from __future__ import annotations

import pytest

from apps.crm.models import (
    Contact, ContactPhone, ContactTypeLink, OutboxMessage, StageChange, Task,
)
from apps.crm.services import importer
from apps.tenancy.context import tenant_context

from . import registry_config  # noqa: F401
from .factories import CompanyFactory, ContactEmailFactory, ContactFactory

HEADER = "first_name,last_name,email,company,phone,mobile,status,stage,tags\n"


def _csv(rows):
    return (HEADER + "".join(rows)).encode()


MAPPING = {
    "first_name": "first_name", "last_name": "last_name", "email": "email",
    "company": "company", "phone": "phone", "mobile": "phone",
    "status": "contact_type", "stage": "pipeline_stage", "tags": "tags",
}


def types_block(values, **extra):
    return {"contact_type": dict({"column": "status", "values": values}, **extra)}


def stage_block(pipeline_name, values):
    """A pipeline_stage block names its pipeline once, at the top."""
    return {"pipeline_stage": {"column": "stage", "pipeline": pipeline_name,
                               "values": values}}


def _stage_code(contact, pipeline_name):
    """Which stage this contact sits at in one named pipeline, or None."""
    position = contact.pipeline_positions.filter(pipeline__name=pipeline_name).first()
    return position.stage.code if position else None


def _run(tenant, rows, member, value_mapping=None, mapping=None):
    """`member` is a Membership fixture; the importer wants its User."""
    return importer.dry_run(
        tenant=tenant, filename="book.csv", file_bytes=_csv(rows),
        mapping=mapping if mapping is not None else MAPPING,
        value_mapping=value_mapping or {}, actor=member.user,
    )


# ------------------------------------------------------------------- phone

@pytest.mark.django_db
def test_first_phone_column_is_primary_and_the_second_is_not(seeded_tenant, ff):
    with tenant_context(seeded_tenant.pk):
        batch = _run(seeded_tenant, ["Dana,Reyes,d@a.invalid,Acme,555-0100,555-0199,,,\n"], ff)
        importer.commit(batch, actor=ff.user)

        contact = Contact.objects.get(first_name="Dana")
        phones = {p.number: p.is_primary for p in contact.phones.all()}
        assert phones == {"555-0100": True, "555-0199": False}


@pytest.mark.django_db
def test_a_single_phone_column_is_primary(seeded_tenant, ff):
    with tenant_context(seeded_tenant.pk):
        mapping = dict(MAPPING, mobile="")
        batch = _run(seeded_tenant, ["Dana,Reyes,d@a.invalid,Acme,555-0100,,,,\n"],
                     ff, mapping=mapping)
        importer.commit(batch, actor=ff.user)

        phone = Contact.objects.get(first_name="Dana").phones.get()
        assert phone.number == "555-0100"
        assert phone.is_primary is True


@pytest.mark.django_db
def test_an_existing_primary_phone_is_not_displaced(seeded_tenant, ff):
    """contact_phone_one_primary is a partial unique index — a second primary
    would fail the whole import, losing every good row with it."""
    contact = ContactFactory(tenant=seeded_tenant, first_name="Dana", last_name="Reyes")
    ContactEmailFactory(tenant=seeded_tenant, contact=contact, address="d@a.invalid")
    ContactPhone.all_objects.create(
        tenant=seeded_tenant, contact=contact, number="555-0000", is_primary=True
    )

    with tenant_context(seeded_tenant.pk):
        batch = _run(seeded_tenant, ["Dana,Reyes,d@a.invalid,Acme,555-0100,,,,\n"], ff)
        importer.commit(batch, actor=ff.user)

        contact.refresh_from_db()
        phones = {p.number: p.is_primary for p in contact.phones.all()}
        assert phones == {"555-0000": True, "555-0100": False}


@pytest.mark.django_db
def test_re_importing_the_same_number_does_not_stack_duplicates(seeded_tenant, ff):
    rows = ["Dana,Reyes,d@a.invalid,Acme,555-0100,,,,\n"]
    with tenant_context(seeded_tenant.pk):
        importer.commit(_run(seeded_tenant, rows, ff), actor=ff.user)
        importer.commit(_run(seeded_tenant, rows, ff), actor=ff.user)

        assert Contact.objects.get(first_name="Dana").phones.count() == 1


# -------------------------------------------------------------------- tags

@pytest.mark.django_db
@pytest.mark.parametrize("cell,expected", [
    ("vip,warm", ["vip", "warm"]),
    ("vip;warm", ["vip", "warm"]),
    ("vip, warm ; cold", ["vip", "warm", "cold"]),
    ("  spaced  ", ["spaced"]),
    ("dupe,dupe", ["dupe"]),
    ("VIP,vip", ["VIP"]),          # de-duped case-insensitively, first spelling wins
    (",,;,", []),
    ("", []),
])
def test_tag_splitting(cell, expected):
    assert importer.split_tags(cell) == expected


@pytest.mark.django_db
def test_tags_land_on_the_contact(seeded_tenant, ff):
    with tenant_context(seeded_tenant.pk):
        batch = _run(seeded_tenant, ['Dana,Reyes,d@a.invalid,Acme,,,,,"vip; warm,vip"\n'], ff)
        importer.commit(batch, actor=ff.user)

        assert Contact.objects.get(first_name="Dana").tags == ["vip", "warm"]


@pytest.mark.django_db
def test_an_update_unions_tags_rather_than_replacing_them(seeded_tenant, ff):
    """A CSV that omits a hand-added tag is not an instruction to delete it."""
    contact = ContactFactory(
        tenant=seeded_tenant, first_name="Dana", last_name="Reyes", tags=["by-hand"]
    )
    ContactEmailFactory(tenant=seeded_tenant, contact=contact, address="d@a.invalid")

    with tenant_context(seeded_tenant.pk):
        batch = _run(seeded_tenant, ["Dana,Reyes,d@a.invalid,Acme,,,,,vip\n"], ff)
        importer.commit(batch, actor=ff.user)

        contact.refresh_from_db()
        assert contact.tags == ["by-hand", "vip"]

        importer.rollback(batch, actor=ff.user)
        contact.refresh_from_db()
        assert contact.tags == ["by-hand"]


@pytest.mark.django_db
def test_an_over_long_tag_is_a_row_error_not_a_failed_import(seeded_tenant, ff):
    long_tag = "x" * 65
    with tenant_context(seeded_tenant.pk):
        batch = _run(seeded_tenant, [
            f"Dana,Reyes,d@a.invalid,Acme,,,,,{long_tag}\n",
            "Sam, Okoye,s@a.invalid,Acme,,,,,fine\n",
        ], ff)

        assert batch.counts["error"] == 1
        assert batch.counts["create"] == 1  # the good row survives
        row = batch.rows.filter(outcome="error").first()
        assert "tags" in row.error_text
        assert "65 characters" in row.error_text


# ------------------------------------------------- contact_type value mapping

@pytest.mark.django_db
def test_scan_values_counts_every_distinct_value(seeded_tenant, ff):
    rows = [
        "A,One,a@x.invalid,Acme,,,Client,,\n",
        "B,Two,b@x.invalid,Acme,,,Client,,\n",
        "C,Three,c@x.invalid,Acme,,,client ,,\n",   # same value, different spelling
        "D,Four,d@x.invalid,Acme,,,Prospect,,\n",
        "E,Five,e@x.invalid,Acme,,,,,\n",           # blank: not offered
    ]
    with tenant_context(seeded_tenant.pk):
        report = importer.scan_values(
            tenant=seeded_tenant, file_bytes=_csv(rows), mapping=MAPPING
        )

    block = next(t for t in report["targets"] if t["target"] == "contact_type")
    counts = {e["value"].strip().lower(): e["count"] for e in block["values"]}
    assert counts == {"client": 3, "prospect": 1}
    assert block["column"] == "status"
    assert {t["code"] for t in report["contact_types"]} >= {"client", "prospect", "vendor"}
    # Pipelines come back whole, so the wizard can ask "which pipeline?" first.
    names = {p["name"] for p in report["pipelines"]}
    assert names == {"Sales", "Referral partners"}
    sales_stages = next(p for p in report["pipelines"] if p["name"] == "Sales")["stages"]
    assert [s["code"] for s in sales_stages][:2] == ["initial_contact_made", "prospecting"]
    assert [s["semantic"] for s in sales_stages if s["code"] == "closed_won"] == ["won"]


@pytest.mark.django_db
def test_an_unmapped_value_is_a_row_error(seeded_tenant, ff):
    """Silently dropping a status column would lose the distinction the owner
    was trying to import."""
    with tenant_context(seeded_tenant.pk):
        batch = _run(seeded_tenant, ["Dana,Reyes,d@a.invalid,Acme,,,Client,,\n"], ff)

        assert batch.counts["error"] == 1
        assert "not mapped" in batch.rows.first().error_text


@pytest.mark.django_db
def test_a_value_maps_to_a_type_and_a_stage(seeded_tenant, sales, stages, types, ff):
    value_mapping = types_block(
        {"Prospect": {"contact_type": "prospect", "pipeline": "Sales",
                      "stage": "prospecting"}}
    )
    with tenant_context(seeded_tenant.pk):
        batch = _run(seeded_tenant, ["Dana,Reyes,d@a.invalid,Acme,,,Prospect,,\n"],
                     ff, value_mapping=value_mapping)
        importer.commit(batch, actor=ff.user)

        contact = Contact.objects.get(first_name="Dana")
        assert _stage_code(contact, "Sales") == "prospecting"
        assert [t.code for t in contact.types.all()] == ["prospect"]


@pytest.mark.django_db
def test_a_value_can_be_ignored(seeded_tenant, sales, stages, ff):
    value_mapping = types_block({"Archived": {"ignore": True}})
    with tenant_context(seeded_tenant.pk):
        batch = _run(seeded_tenant, ["Dana,Reyes,d@a.invalid,Acme,,,Archived,,\n"],
                     ff, value_mapping=value_mapping)
        assert batch.counts["create"] == 1
        importer.commit(batch, actor=ff.user)

        contact = Contact.objects.get(first_name="Dana")
        assert contact.types.count() == 0
        # An ignored value places them in no pipeline at all — an import must
        # not invent a position the file never stated.
        assert contact.pipeline_positions.count() == 0


@pytest.mark.django_db
def test_value_matching_is_trimmed_and_case_insensitive(seeded_tenant, sales, stages, ff):
    value_mapping = types_block(
        {"client": {"pipeline": "Sales", "stage": "closed_won"}}
    )
    with tenant_context(seeded_tenant.pk):
        batch = _run(seeded_tenant, ["Dana,Reyes,d@a.invalid,Acme,,,  CLIENT ,,\n"],
                     ff, value_mapping=value_mapping)
        assert batch.counts["error"] == 0
        importer.commit(batch, actor=ff.user)
        assert _stage_code(Contact.objects.get(first_name="Dana"), "Sales") == "closed_won"


@pytest.mark.django_db
def test_a_stage_code_that_does_not_exist_is_a_row_error(seeded_tenant, ff):
    value_mapping = types_block({"Client": {"pipeline": "Sales", "stage": "customer"}})
    with tenant_context(seeded_tenant.pk):
        batch = _run(seeded_tenant, ["Dana,Reyes,d@a.invalid,Acme,,,Client,,\n"],
                     ff, value_mapping=value_mapping)
        assert batch.counts["error"] == 1
        assert "no stage 'customer'" in batch.rows.first().error_text


# ------------------------------------------- FR-1.6a through the value mapping

@pytest.mark.django_db
def test_mapping_a_value_to_client_fires_the_client_invariant(
    seeded_tenant, sales, stages, types, ff
):
    """FR-1.6a, exactly as a manual stage change: client type added, company
    flagged, and a stage_change on the record."""
    company = CompanyFactory(tenant=seeded_tenant, name="Acme", is_client_company=False)
    value_mapping = types_block(
        {"Client": {"contact_type": "client", "pipeline": "Sales", "stage": "closed_won"}}
    )

    with tenant_context(seeded_tenant.pk):
        batch = _run(seeded_tenant, ["Dana,Reyes,d@a.invalid,Acme,,,Client,,\n"],
                     ff, value_mapping=value_mapping)
        assert batch.rows.first().preview["fires_client_invariant"] is True
        importer.commit(batch, actor=ff.user)

        contact = Contact.objects.get(first_name="Dana")
        assert _stage_code(contact, "Sales") == "closed_won"
        assert "client" in [t.code for t in contact.types.all()]
        company.refresh_from_db()
        assert company.is_client_company is True
        assert StageChange.objects.filter(
            contact=contact, to_stage__code="closed_won"
        ).exists()


@pytest.mark.django_db
def test_the_invariant_fires_even_when_only_the_stage_was_mapped(
    seeded_tenant, sales, stages, types, ff
):
    """The derivation is the stage's job, not the type column's — mapping the
    stage alone must still produce the client type."""
    value_mapping = types_block({"Client": {"pipeline": "Sales", "stage": "closed_won"}})
    with tenant_context(seeded_tenant.pk):
        batch = _run(seeded_tenant, ["Dana,Reyes,d@a.invalid,Acme,,,Client,,\n"],
                     ff, value_mapping=value_mapping)
        importer.commit(batch, actor=ff.user)

        contact = Contact.objects.get(first_name="Dana")
        assert "client" in [t.code for t in contact.types.all()]


@pytest.mark.django_db
def test_an_import_does_not_replay_stage_automations(
    seeded_tenant, sales, stages, types, ff
):
    """A backfill is a statement about history, not a transition happening now.
    Replaying the rules would queue a client-facing draft for every client in
    the file."""
    from .factories import EmailTemplateFactory, StageAutomationFactory

    StageAutomationFactory(
        tenant=seeded_tenant, pipeline=sales, to_stage=stages["closed_won"],
        action_type="create_task", task_title_template="Kick-off",
        task_due_offset_days=3,
    )
    StageAutomationFactory(
        tenant=seeded_tenant, pipeline=sales, to_stage=stages["closed_won"],
        action_type="draft_email",
        email_template=EmailTemplateFactory(tenant=seeded_tenant),
    )
    value_mapping = types_block({"Client": {"pipeline": "Sales", "stage": "closed_won"}})

    with tenant_context(seeded_tenant.pk):
        batch = _run(seeded_tenant, ["Dana,Reyes,d@a.invalid,Acme,,,Client,,\n"],
                     ff, value_mapping=value_mapping)
        importer.commit(batch, actor=ff.user)

        contact = Contact.objects.get(first_name="Dana")
        assert _stage_code(contact, "Sales") == "closed_won"   # the stage still moved
        assert "client" in [t.code for t in contact.types.all()]  # invariant still ran
        assert Task.objects.filter(contact=contact).count() == 0
        assert OutboxMessage.objects.count() == 0

        # Control: the same two rules DO fire on a manual stage change. Without
        # this the assertions above would pass just as well against a rule that
        # was never live.
        from apps.crm.services import pipeline

        manual = ContactFactory(
            tenant=seeded_tenant, first_name="Sam", last_name="Okoye",
        )
        pipeline.change_stage(manual, stages["closed_won"], actor=ff.user)
        assert Task.objects.filter(contact=manual).count() == 1
        assert OutboxMessage.objects.count() == 1


@pytest.mark.django_db
def test_rollback_restores_a_position_the_import_moved(
    seeded_tenant, sales, stages, types, ff
):
    """The contact was already in the pipeline: rollback puts them back where
    they were rather than deleting a position they held before the import."""
    from .factories import ContactPipelinePositionFactory

    contact = ContactFactory(tenant=seeded_tenant, first_name="Dana", last_name="Reyes")
    ContactEmailFactory(tenant=seeded_tenant, contact=contact, address="d@a.invalid")
    ContactPipelinePositionFactory(
        tenant=seeded_tenant, contact=contact, pipeline=sales,
        stage=stages["prospecting"],
    )
    value_mapping = types_block(
        {"Client": {"contact_type": "client", "pipeline": "Sales", "stage": "closed_won"}}
    )

    with tenant_context(seeded_tenant.pk):
        batch = _run(seeded_tenant, ["Dana,Reyes,d@a.invalid,Acme,555-0100,,Client,,vip\n"],
                     ff, value_mapping=value_mapping)
        importer.commit(batch, actor=ff.user)
        contact.refresh_from_db()
        assert _stage_code(contact, "Sales") == "closed_won"

        importer.rollback(batch, actor=ff.user)
        contact.refresh_from_db()
        assert _stage_code(contact, "Sales") == "prospecting"
        assert ContactTypeLink.objects.filter(contact=contact).count() == 0
        assert contact.phones.count() == 0
        assert contact.tags == []


@pytest.mark.django_db
def test_rollback_removes_a_position_the_import_created(
    seeded_tenant, sales, stages, ff
):
    """The contact was NOT in that pipeline before: the position goes entirely."""
    contact = ContactFactory(tenant=seeded_tenant, first_name="Dana", last_name="Reyes")
    ContactEmailFactory(tenant=seeded_tenant, contact=contact, address="d@a.invalid")
    value_mapping = types_block({"Client": {"pipeline": "Sales", "stage": "closed_won"}})

    with tenant_context(seeded_tenant.pk):
        batch = _run(seeded_tenant, ["Dana,Reyes,d@a.invalid,Acme,,,Client,,\n"],
                     ff, value_mapping=value_mapping)
        importer.commit(batch, actor=ff.user)
        assert contact.pipeline_positions.count() == 1

        importer.rollback(batch, actor=ff.user)
        assert contact.pipeline_positions.count() == 0


# ----------------------------------------------------------------- preview

@pytest.mark.django_db
def test_the_dry_run_preview_shows_all_three_effects(seeded_tenant, sales, stages, types, ff):
    """FR-1.28 — the preview is the whole point of a dry run."""
    value_mapping = types_block(
        {"Client": {"contact_type": "client", "pipeline": "Sales", "stage": "closed_won"}}
    )
    with tenant_context(seeded_tenant.pk):
        batch = _run(
            seeded_tenant,
            ['Dana,Reyes,d@a.invalid,Acme,555-0100,555-0199,Client,,"vip;warm"\n'],
            ff, value_mapping=value_mapping,
        )
        preview = batch.rows.first().preview

    assert preview["phones"] == [
        {"number": "555-0100", "is_primary": True},
        {"number": "555-0199", "is_primary": False},
    ]
    assert preview["tags"] == ["vip", "warm"]
    assert preview["contact_type"] == "client"
    assert preview["contact_type_label"] == "Client"
    assert preview["placements"] == [{
        "pipeline": "Sales", "stage": "Closed Won", "stage_code": "closed_won",
        "semantic": "won", "from_column": "contact_type",
        "fires_client_invariant": True,
    }]
    assert preview["fires_client_invariant"] is True


# ------------------------------------------------------------ the API surface

SCAN = "/api/imports/scan-values/"
PROFILES = "/api/import-profiles/"


def _upload(rows):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile("book.csv", _csv(rows), content_type="text/csv")


@pytest.mark.django_db
def test_scan_values_endpoint_returns_values_with_counts(seeded_tenant, ff, api):
    import json

    response = api.as_(ff).post(SCAN, {
        "file": _upload([
            "A,One,a@x.invalid,Acme,,,Client,,\n",
            "B,Two,b@x.invalid,Acme,,,Client,,\n",
        ]),
        "mapping": json.dumps(MAPPING),
    })

    assert response.status_code == 200
    body = response.json()
    block = next(t for t in body["targets"] if t["target"] == "contact_type")
    assert block["values"] == [{"value": "Client", "count": 2}]


@pytest.mark.django_db
def test_a_va_may_scan_values_and_save_a_profile(seeded_tenant, va, api):
    """Matrix 4.13 — a VA runs the import, so a VA maps it."""
    import json

    scan = api.as_(va).post(SCAN, {
        "file": _upload(["A,One,a@x.invalid,Acme,,,Client,,\n"]),
        "mapping": json.dumps(MAPPING),
    })
    assert scan.status_code == 200

    saved = api.as_(va).post(PROFILES, {
        "name": "Outlook", "mapping": MAPPING,
        "value_mapping": {"Client": {"stage": "client"}},
    }, content_type="application/json")
    assert saved.status_code == 201


@pytest.mark.django_db
def test_a_cf_cannot_import_or_save_a_mapping(seeded_tenant, cf, api):
    """Matrix 4.13 — import is FF or VA, and mapping profiles go with it."""
    import json

    assert api.as_(cf).post(SCAN, {
        "file": _upload(["A,One,a@x.invalid,Acme,,,Client,,\n"]),
        "mapping": json.dumps(MAPPING),
    }).status_code == 403
    assert api.as_(cf).get(PROFILES).status_code == 403


@pytest.mark.django_db
def test_client_users_reach_none_of_it(seeded_tenant, fcc, api):
    assert api.as_(fcc).get(PROFILES).status_code == 403
    assert api.as_(fcc).post(SCAN, {}).status_code == 403


@pytest.mark.django_db
def test_a_saved_profile_remembers_the_value_mapping(seeded_tenant, ff, api):
    created = api.as_(ff).post(PROFILES, {
        "name": "Outlook", "mapping": MAPPING,
        "value_mapping": {"Client": {"contact_type": "client", "stage": "client"}},
    }, content_type="application/json").json()

    reloaded = api.as_(ff).get(f"{PROFILES}{created['id']}/").json()

    assert reloaded["mapping"]["status"] == "contact_type"
    assert reloaded["value_mapping"] == {
        "Client": {"contact_type": "client", "stage": "client"}
    }


@pytest.mark.django_db
def test_a_profile_from_another_tenant_is_invisible(seeded_tenant, ff, api):
    from apps.crm.models import ImportMappingProfile

    from .factories import TenantFactory

    other = TenantFactory(name="Other", slug="other-import")
    ImportMappingProfile.all_objects.create(
        tenant=other, name="Theirs", mapping={}, value_mapping={}
    )

    names = [p["name"] for p in api.as_(ff).get(PROFILES).json()]
    assert "Theirs" not in names


@pytest.mark.django_db
def test_commit_uses_the_mapping_the_dry_run_reported(seeded_tenant, sales, stages, ff, api):
    """The preview and the write must not be able to disagree — the browser no
    longer gets to re-send a different mapping at commit time."""
    import json

    dry = api.as_(ff).post("/api/imports/dry-run/", {
        "file": _upload(["Dana,Reyes,d@a.invalid,Acme,555-0100,,Client,,vip\n"]),
        "mapping": json.dumps(MAPPING),
        "value_mapping": json.dumps(
            types_block({"Client": {"pipeline": "Sales", "stage": "closed_won"}})
        ),
    }).json()

    assert dry["rows"][0]["preview"]["placements"][0]["stage_code"] == "closed_won"
    assert dry["rows"][0]["preview"]["phones"][0]["is_primary"] is True

    # Commit sends nothing: the batch already knows.
    assert api.as_(ff).post(f"/api/imports/{dry['batch']['id']}/commit/").status_code == 200

    with tenant_context(seeded_tenant.pk):
        contact = Contact.objects.get(first_name="Dana")
        assert _stage_code(contact, "Sales") == "closed_won"
        assert contact.tags == ["vip"]
        assert contact.phones.get().is_primary is True
