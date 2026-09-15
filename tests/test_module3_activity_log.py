"""FR-3.41 / matrix 7.16–7.17 — the client portal's activity log.

Read-only for everyone; FCC and ECC only; their company's history and shared
comments, and never an internal comment, a hidden task, another company's work
or another tenant's. Work done while acting as reads "by X on behalf of Y".
"""

from __future__ import annotations

import json

import pytest

from apps.work.services import add_comment, add_narrative, apply_task_changes, create_task

from . import registry_config  # noqa: F401
from .factories import (
    ClientCompanyFactory, ContactEmailFactory, ContactFactory, MembershipFactory,
    ProjectFactory, UserFactory,
)

URL = "/api/portal-activity/"
SECRET = "INTERNAL-ONLY: their AP clerk is the bottleneck"


def client_user(tenant, company, role, first):
    user = UserFactory(email=f"{first.lower()}@{company.name.split()[0].lower()}.invalid",
                       full_name=f"{first} Client")
    contact = ContactFactory(tenant=tenant, first_name=first, last_name="Client", company=company)
    ContactEmailFactory(tenant=tenant, contact=contact, address=user.email, is_primary=True)
    return MembershipFactory(tenant=tenant, user=user, role=role, client_company=company,
                             contact=contact)


@pytest.fixture
def world(seeded_tenant, tenant_b, ff, api, dev_outbox, in_tenant_a):
    acme = ClientCompanyFactory(tenant=seeded_tenant, name="Acme Facilities", seat_count=5)
    northwind = ClientCompanyFactory(tenant=seeded_tenant, name="Northwind Foods", seat_count=5)
    fcc = client_user(seeded_tenant, acme, "FCC", "Dana")
    ecc = client_user(seeded_tenant, acme, "ECC", "Priya")

    dock = create_task(tenant=seeded_tenant, actor=ff.user, role="FF",
                       title="Fix the loading dock", client_company=acme)
    apply_task_changes(dock, actor=ff.user, role="FF", changes={"status": "in_progress"},
                       client_facing_line="Parts are ordered.")
    add_comment(dock, author=ff.user, role="FF", body="Shared: install is Tuesday.",
                visibility="shared")
    add_comment(dock, author=ff.user, role="FF", body=SECRET, visibility="internal")

    hidden = create_task(tenant=seeded_tenant, actor=ff.user, role="FF",
                         title="HIDDEN renegotiate their fee", client_company=acme,
                         is_client_visible=False)
    add_narrative(hidden, actor=ff.user, role="FF", line="HIDDEN note")

    project = ProjectFactory(tenant=seeded_tenant, title="Safer site", client_company=acme)
    add_narrative(project, actor=ff.user, role="FF", line="Audit booked.")

    theirs = create_task(tenant=seeded_tenant, actor=ff.user, role="FF",
                         title="NORTHWIND recipe costing", client_company=northwind)
    add_comment(theirs, author=ff.user, role="FF", body="NORTHWIND shared", visibility="shared")

    doomed = create_task(tenant=seeded_tenant, actor=ff.user, role="FF",
                         title="Old signage", client_company=acme)
    assert api.as_(ff).delete(f"/api/tasks/{doomed.pk}/").status_code == 204

    b_co = ClientCompanyFactory(tenant=tenant_b, name="Tenant B Co", seat_count=1)
    return {"acme": acme, "northwind": northwind, "fcc": fcc, "ecc": ecc, "dock": dock,
            "b_co": b_co}


def entries(api, member):
    response = api.as_(member).get(URL)
    assert response.status_code == 200, response.content
    return response.json()


@pytest.mark.django_db
def test_the_log_shows_the_companys_history_and_shared_comments(api, world):
    texts = [e["text"] for e in entries(api, world["ecc"])]
    blob = "\n".join(texts)
    assert "created “Fix the loading dock”" in blob
    assert "changed “Fix the loading dock” from Not started to In progress — Parts are ordered." in blob
    assert "commented on “Fix the loading dock”: Shared: install is Tuesday." in blob
    assert "added a note on “Safer site”: Audit booked." in blob
    assert "deleted “Old signage”" in blob
    # Newest first.
    ats = [e["at"] for e in entries(api, world["ecc"])]
    assert ats == sorted(ats, reverse=True)
    # FCC and ECC see the same log.
    assert [e["id"] for e in entries(api, world["fcc"])] == [e["id"] for e in entries(api, world["ecc"])]


@pytest.mark.django_db
def test_internal_comments_never_appear_in_any_form(api, world):
    raw = json.dumps(entries(api, world["fcc"]))
    assert SECRET not in raw
    assert "internal" not in raw.lower()
    kinds = {e["kind"] for e in entries(api, world["fcc"])}
    assert "comment_added" not in kinds, "No bare 'someone commented' rows either."


@pytest.mark.django_db
def test_hidden_work_and_other_companies_never_appear(api, world):
    raw = json.dumps(entries(api, world["ecc"]))
    assert "HIDDEN" not in raw
    assert "NORTHWIND" not in raw and "Northwind" not in raw


@pytest.mark.django_db
def test_portal_events_are_only_their_companys(seeded_tenant, ff, api, world):
    acme_contact = ContactFactory(tenant=seeded_tenant, first_name="Ola", last_name="New",
                                  company=world["acme"])
    ContactEmailFactory(tenant=seeded_tenant, contact=acme_contact, address="ola@acme.invalid",
                        is_primary=True)
    nw_contact = ContactFactory(tenant=seeded_tenant, first_name="Nia", last_name="Other",
                                company=world["northwind"])
    ContactEmailFactory(tenant=seeded_tenant, contact=nw_contact, address="nia@nw.invalid",
                        is_primary=True)
    for contact in (acme_contact, nw_contact):
        assert api.as_(ff).post("/api/portal-access/", json.dumps({"contact": str(contact.pk)}),
                                content_type="application/json").status_code == 201
    blob = "\n".join(e["text"] for e in entries(api, world["ecc"]))
    assert "gave Ola New access to the portal" in blob
    assert "Nia" not in blob


@pytest.mark.django_db
def test_work_done_while_acting_reads_by_x_on_behalf_of_y(ff, api, world):
    client = api.as_(ff)
    assert client.post("/api/act-as/", json.dumps({"membership": str(world["ecc"].pk)}),
                       content_type="application/json").status_code == 201
    assert client.post("/api/comments/", json.dumps(
        {"task": str(world["dock"].pk), "body": "Posted while acting."}),
        content_type="application/json").status_code == 201
    client.post("/api/act-as/stop/")

    rows = entries(api, world["fcc"])
    acted = next(e for e in rows if "Posted while acting." in e["text"])
    assert acted["by"] == ff.user.full_name or acted["by"] == ff.user.email
    assert acted["on_behalf_of"] == "Priya Client"
    began = next(e for e in rows if e["kind"] == "act_as.started")
    assert began["text"] == "began acting as Priya Client" and began["on_behalf_of"] is None
    assert any(e["kind"] == "act_as.stopped" for e in rows)
    plain = next(e for e in rows if "Shared: install is Tuesday." in e["text"])
    assert plain["on_behalf_of"] is None


@pytest.mark.django_db
@pytest.mark.parametrize("role,expected", [("FF", 403), ("CF", 403), ("VA", 403),
                                           ("FCC", 200), ("ECC", 200)])
def test_matrix_7_16_the_log_is_for_client_users_only(role, expected, seeded_tenant, api, world):
    member = MembershipFactory(tenant=seeded_tenant, role=role,
                               client_company=world["acme"] if role in ("FCC", "ECC") else None)
    assert api.as_(member).get(URL).status_code == expected


@pytest.mark.django_db
@pytest.mark.parametrize("who", ["fcc", "ecc", "ff"])
def test_matrix_7_17_nobody_can_edit_or_delete_the_log(who, ff, api, world):
    member = ff if who == "ff" else world[who]
    client = api.as_(member)
    for method in ("post", "put", "patch", "delete"):
        response = getattr(client, method)(URL, json.dumps({"text": "rewritten"}),
                                           content_type="application/json")
        assert response.status_code == 405, (who, method, response.status_code)


@pytest.mark.django_db
def test_another_tenants_client_sees_none_of_this(tenant_b, api, world):
    theirs = MembershipFactory(tenant=tenant_b, role="FCC", client_company=world["b_co"])
    response = api.as_(theirs).get(URL)
    assert response.status_code == 200
    assert "Acme" not in json.dumps(response.json())
    assert "loading dock" not in json.dumps(response.json())
