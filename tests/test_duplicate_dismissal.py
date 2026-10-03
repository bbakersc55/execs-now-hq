"""Merge duplicates: "not duplicates" (backlog, 2026-10-03). A pair a person
dismissed stops reappearing; a genuinely new match can still bring it back
into a group, and the group says which pair was already dismissed."""

from __future__ import annotations

import json

import pytest

from apps.crm.models import Contact, DuplicateDismissal
from apps.crm.services import duplicates
from apps.tenancy.models import AuditEvent

from . import registry_config  # noqa: F401
from .conftest import _member
from .test_duplicates_and_matching import person


def post(client, body):
    return client.post("/api/contacts/not-duplicates/", json.dumps(body),
                       content_type="application/json")


def groups(api, member):
    return api.as_(member).get("/api/contacts/duplicate-groups/").json()


@pytest.mark.django_db
def test_a_dismissed_pair_stops_reappearing(seeded_tenant, in_tenant_a, ff, api):
    a = person(seeded_tenant, "Tim", "Walker", "tim@walker.test")
    b = person(seeded_tenant, "Tim", "Walker", "tim@other.test")
    assert len(groups(api, ff)) == 1
    response = post(api.as_(ff), {"contacts": [str(b.pk), str(a.pk)]})
    assert response.status_code == 200 and response.json() == {"dismissed": 1}
    assert groups(api, ff) == []
    # Stored once, in id order, and recorded.
    row = DuplicateDismissal.objects.get()
    assert str(row.contact_a_id) < str(row.contact_b_id)
    assert AuditEvent.objects.filter(verb="contacts.not_duplicates").exists()
    # Saying it again changes nothing.
    assert post(api.as_(ff), {"contacts": [str(a.pk), str(b.pk)]}).json() == {"dismissed": 0}


@pytest.mark.django_db
def test_a_group_of_three_dismissed_whole(seeded_tenant, in_tenant_a, ff, api):
    trio = [person(seeded_tenant, "Ann", "Lee") for _ in range(3)]
    post(api.as_(ff), {"contacts": [str(c.pk) for c in trio]})
    assert DuplicateDismissal.objects.count() == 3
    assert groups(api, ff) == []


@pytest.mark.django_db
def test_a_new_match_brings_them_back_and_says_which_pair_was_dismissed(
        seeded_tenant, in_tenant_a, ff, api):
    a = person(seeded_tenant, "Sam", "Ortiz", "sam@one.test")
    b = person(seeded_tenant, "Sam", "Ortiz", "sam@two.test")
    post(api.as_(ff), {"contacts": [str(a.pk), str(b.pk)]})
    c = person(seeded_tenant, "Sam", "Ortiz")
    [group] = groups(api, ff)
    assert {x["id"] for x in group["contacts"]} == {str(a.pk), str(b.pk), str(c.pk)}
    assert group["dismissed_pairs"] == [sorted([str(a.pk), str(b.pk)])]


@pytest.mark.django_db
def test_undo_puts_the_group_back(seeded_tenant, in_tenant_a, ff, api):
    a = person(seeded_tenant, "Lou", "Park", "lou@park.test")
    b = person(seeded_tenant, "Lou", "Park")
    post(api.as_(ff), {"contacts": [str(a.pk), str(b.pk)]})
    assert post(api.as_(ff), {"contacts": [str(a.pk), str(b.pk)], "undo": True}).json() == \
        {"undone": 1}
    assert len(groups(api, ff)) == 1


@pytest.mark.django_db
@pytest.mark.parametrize("role,code", [("VA", 200), ("CF", 403)])
def test_the_same_people_as_merge(seeded_tenant, in_tenant_a, api, role, code):
    a, b = person(seeded_tenant, "Jo", "Kim"), person(seeded_tenant, "Jo", "Kim")
    member = _member(seeded_tenant, role)
    assert post(api.as_(member), {"contacts": [str(a.pk), str(b.pk)]}).status_code == code


@pytest.mark.django_db
def test_another_practices_contacts_cannot_be_named(seeded_tenant, tenant_b, api, ff):
    from apps.tenancy.context import tenant_context

    with tenant_context(tenant_b.pk):
        x, y = person(tenant_b, "Ida", "Bell"), person(tenant_b, "Ida", "Bell")
    assert post(api.as_(ff), {"contacts": [str(x.pk), str(y.pk)]}).status_code == 404
    assert not DuplicateDismissal.all_objects.exists()


@pytest.mark.django_db
def test_without_dismissals_grouping_is_unchanged(seeded_tenant, in_tenant_a):
    a = person(seeded_tenant, "Dana", "Reyes", "dana@acme.test")
    b = person(seeded_tenant, "Dana", "Reyes")
    [group] = duplicates.groups(Contact.objects.all())
    assert group["dismissed_pairs"] == [] and len(group["contacts"]) == 2
    assert {str(a.pk), str(b.pk)} == {x["id"] for x in group["contacts"]}
