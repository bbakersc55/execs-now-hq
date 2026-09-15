"""Phase 3 manual checks, item 3 — who "Who hears about this" offers.

The picker searched every contact in the tenant, so a client's task offered
other clients' people. For work with a client company it now defaults to that
company's contacts, with an explicit "someone outside" search; internal work
searches anyone; tenant staff who are also contacts are marked as the practice.
"""

from __future__ import annotations

import pytest

from apps.work.services import create_task

from . import registry_config  # noqa: F401
from .factories import (
    ClientAssignmentFactory, ClientCompanyFactory, ContactEmailFactory, ContactFactory,
    GoalFactory, MembershipFactory, ProjectFactory,
)

URL = "/api/stakeholders/candidates/"


def person(tenant, first, last, company=None, email=None):
    contact = ContactFactory(tenant=tenant, first_name=first, last_name=last, company=company)
    if email:
        ContactEmailFactory(tenant=tenant, contact=contact, address=email, is_primary=True)
    return contact


@pytest.fixture
def acme(seeded_tenant):
    return ClientCompanyFactory(tenant=seeded_tenant, name="Acme Facilities", seat_count=3)


@pytest.fixture
def people(seeded_tenant, acme):
    other = ClientCompanyFactory(tenant=seeded_tenant, name="Northwind Foods", seat_count=3)
    return {
        "dana": person(seeded_tenant, "Dana", "Reyes", acme, "dana@acme.invalid"),
        "ben": person(seeded_tenant, "Ben", "Orji", acme, "ben@acme.invalid"),
        "priya": person(seeded_tenant, "Priya", "Shah", other, "priya@northwind.invalid"),
        "board": person(seeded_tenant, "Boris", "Board", None, "boris@board.invalid"),
    }


def names(response):
    assert response.status_code == 200, response.content
    return [p["name"] for p in response.json()["people"]]


@pytest.fixture
def acme_task(seeded_tenant, ff, acme, in_tenant_a):
    return create_task(tenant=seeded_tenant, actor=ff.user, role="FF",
                       title="Fix the loading dock", client_company=acme)


@pytest.mark.django_db
def test_work_at_a_client_company_offers_that_companys_contacts_without_typing(
    ff, api, acme_task, people, in_tenant_a
):
    body = api.as_(ff).get(f"{URL}?task={acme_task.pk}")
    assert names(body) == ["Ben Orji", "Dana Reyes"]
    assert body.json()["company_name"] == "Acme Facilities" and body.json()["outside"] is False
    assert names(api.as_(ff).get(f"{URL}?task={acme_task.pk}&q=Da")) == ["Dana Reyes"]


@pytest.mark.django_db
def test_someone_outside_the_company_is_explicit_typed_and_excludes_the_company(
    ff, api, acme_task, people, in_tenant_a
):
    client = api.as_(ff)
    # Nothing is listed until a name is typed: the tenant is never listed unasked.
    assert names(client.get(f"{URL}?task={acme_task.pk}&outside=1")) == []
    assert names(client.get(f"{URL}?task={acme_task.pk}&outside=1&q=B")) == []
    assert names(client.get(f"{URL}?task={acme_task.pk}&outside=1&q=Bo")) == ["Boris Board"]
    # Acme's own people are the default list, not the "outside" one.
    assert names(client.get(f"{URL}?task={acme_task.pk}&outside=1&q=Be")) == []
    assert names(client.get(f"{URL}?task={acme_task.pk}&outside=1&q=Pri")) == ["Priya Shah"]


@pytest.mark.django_db
def test_internal_work_searches_any_contact(seeded_tenant, ff, api, people, in_tenant_a):
    internal = create_task(tenant=seeded_tenant, actor=ff.user, role="FF", title="Books")
    client = api.as_(ff)
    body = client.get(f"{URL}?task={internal.pk}")
    assert names(body) == [] and body.json()["company"] is None
    assert names(client.get(f"{URL}?task={internal.pk}&q=Pri")) == ["Priya Shah"]
    assert names(client.get(f"{URL}?task={internal.pk}&q=Da")) == ["Dana Reyes"]


@pytest.mark.django_db
def test_projects_and_goals_are_scoped_the_same_way(seeded_tenant, ff, api, acme, people,
                                                    in_tenant_a):
    goal = GoalFactory(tenant=seeded_tenant, title="Safer site", client_company=acme)
    project = ProjectFactory(tenant=seeded_tenant, title="Dock", client_company=acme, goal=goal)
    for target in (f"goal={goal.pk}", f"project={project.pk}"):
        assert names(api.as_(ff).get(f"{URL}?{target}")) == ["Ben Orji", "Dana Reyes"]


@pytest.mark.django_db
def test_tenant_staff_who_are_contacts_are_marked_as_the_practice(
    seeded_tenant, ff, api, acme, acme_task, people, in_tenant_a
):
    # The owner's own contact row, matched by address...
    own = person(seeded_tenant, "Bryan", "Baker", None, ff.user.email)
    # ...a VA linked to their contact row directly...
    va_contact = person(seeded_tenant, "Vera", "Assist", None, "vera@practice.invalid")
    MembershipFactory(tenant=seeded_tenant, role="VA", contact=va_contact)
    # ...and a client user, who is not the practice even with a login.
    MembershipFactory(tenant=seeded_tenant, role="ECC", client_company=acme,
                      contact=people["dana"])

    rows = {p["name"]: p["is_practice"] for p in api.as_(ff).get(
        f"{URL}?task={acme_task.pk}&outside=1&q=Br").json()["people"]}
    assert rows == {"Bryan Baker": True}
    rows = {p["name"]: p["is_practice"] for p in api.as_(ff).get(
        f"{URL}?task={acme_task.pk}&outside=1&q=Ve").json()["people"]}
    assert rows == {"Vera Assist": True}
    rows = {p["name"]: p["is_practice"] for p in api.as_(ff).get(
        f"{URL}?task={acme_task.pk}").json()["people"]}
    assert rows == {"Ben Orji": False, "Dana Reyes": False}


@pytest.mark.django_db
@pytest.mark.parametrize("role,expected", [("FF", 200), ("CF", 200), ("VA", 200),
                                           ("FCC", 403), ("ECC", 403)])
def test_who_may_use_the_picker(role, expected, seeded_tenant, api, acme, acme_task, people,
                                in_tenant_a):
    member = MembershipFactory(tenant=seeded_tenant, role=role,
                               client_company=acme if role in ("FCC", "ECC") else None)
    if role == "CF":
        ClientAssignmentFactory(tenant=seeded_tenant, user=member.user, company=acme)
    assert api.as_(member).get(f"{URL}?task={acme_task.pk}").status_code == expected


@pytest.mark.django_db
def test_the_picker_is_blind_to_unassigned_companies_and_other_tenants(
    seeded_tenant, tenant_b, ff, cf, api, acme_task, people, in_tenant_a
):
    # A CF not assigned to Acme cannot see the task, so cannot list its people.
    assert api.as_(cf).get(f"{URL}?task={acme_task.pk}").status_code == 404

    # Another tenant's contacts never appear, even searching outside.
    theirs = ClientCompanyFactory(tenant=tenant_b, name="Tenant B Co", seat_count=1)
    person(tenant_b, "Bonnie", "Elsewhere", theirs, "bonnie@b.invalid")
    assert names(api.as_(ff).get(f"{URL}?task={acme_task.pk}&outside=1&q=Bo")) == [
        "Boris Board"]
    other_tenant_task_id = "00000000-0000-4000-8000-000000000000"
    assert api.as_(ff).get(f"{URL}?task={other_tenant_task_id}").status_code == 404
    assert api.as_(ff).get(URL).status_code == 400
