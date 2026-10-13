"""LinkedIn and Alignable addresses on contacts and companies, and changing
a contact tag everywhere it is used (owner, 2026-10-12)."""

from __future__ import annotations

import pytest

from apps.crm.models import Company, Contact
from apps.tenancy.context import tenant_context
from apps.tenancy.models import AuditEvent

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import CompanyFactory, ContactFactory

JSON = "application/json"


def patch(api, member, path, body):
    return api.as_(member).patch(path, body, content_type=JSON)


def post(api, member, path, body):
    return api.as_(member).post(path, body, content_type=JSON)


# ------------------------------------------------------------------ the links

@pytest.mark.django_db
def test_a_contact_and_a_company_keep_their_linkedin_and_alignable_addresses(
        seeded_tenant, in_tenant_a, ff, api):
    contact = ContactFactory(tenant=seeded_tenant)
    company = CompanyFactory(tenant=seeded_tenant)
    for path, model, row in ((f"/api/contacts/{contact.pk}/", Contact, contact),
                             (f"/api/companies/{company.pk}/", Company, company)):
        # Pasted as people paste them: no scheme on one, a full address on the other.
        response = patch(api, ff, path, {
            "linkedin_url": "linkedin.com/in/dana-reyes",
            "alignable_url": "https://www.alignable.com/denver-co/acme"})
        assert response.status_code == 200, response.json()
        assert response.json()["linkedin_url"] == "https://linkedin.com/in/dana-reyes"
        assert response.json()["alignable_url"] == "https://www.alignable.com/denver-co/acme"
        row.refresh_from_db()
        assert row.linkedin_url == "https://linkedin.com/in/dana-reyes"
        # Cleared by sending it empty.
        assert patch(api, ff, path, {"linkedin_url": ""}).json()["linkedin_url"] == ""


@pytest.mark.django_db
@pytest.mark.parametrize("field,value", [
    ("linkedin_url", "https://example.com/in/dana"),          # not that network
    ("linkedin_url", "https://notlinkedin.com/in/dana"),      # a look-alike host
    ("linkedin_url", "javascript:alert(1)"),
    ("alignable_url", "https://linkedin.com/in/dana"),        # the other network's
    ("alignable_url", "not an address"),
])
def test_an_address_that_is_not_on_that_network_is_refused(
        seeded_tenant, in_tenant_a, ff, api, field, value):
    contact = ContactFactory(tenant=seeded_tenant)
    response = patch(api, ff, f"/api/contacts/{contact.pk}/", {field: value})
    assert response.status_code == 400, response.json()
    assert "address" in response.json()[field][0]
    contact.refresh_from_db()
    assert getattr(contact, field) == ""


# -------------------------------------------------------------------- the tags

@pytest.fixture
def tagged(seeded_tenant, in_tenant_a):
    return [ContactFactory(tenant=seeded_tenant, tags=tags)
            for tags in (["board", "Denver"], ["board"], ["Denver", "golf"], [])]


@pytest.mark.django_db
def test_the_tags_are_listed_with_how_many_contacts_have_each(tagged, ff, api):
    assert api.as_(ff).get("/api/contact-tags/").json() == [
        {"tag": "board", "contacts": 2}, {"tag": "Denver", "contacts": 2},
        {"tag": "golf", "contacts": 1}]


@pytest.mark.django_db
def test_renaming_a_tag_changes_it_on_every_contact_and_is_audited(tagged, ff, api):
    response = post(api, ff, "/api/contact-tags/rename/", {"tag": "board", "to": "Board member"})
    assert response.status_code == 200 and response.json()["changed"] == 2
    for contact in tagged:
        contact.refresh_from_db()
    assert [c.tags for c in tagged] == [
        ["Board member", "Denver"], ["Board member"], ["Denver", "golf"], []]
    event = AuditEvent.objects.get(verb="contact_tag.renamed")
    assert event.payload == {"tag": "board", "to": "Board member", "contacts": 2}
    assert event.actor_id == ff.user_id


@pytest.mark.django_db
def test_renaming_onto_a_tag_that_exists_makes_them_one(tagged, ff, api):
    response = post(api, ff, "/api/contact-tags/rename/", {"tag": "board", "to": "Denver"})
    assert response.json()["tags"] == [{"tag": "Denver", "contacts": 3},
                                       {"tag": "golf", "contacts": 1}]
    tagged[0].refresh_from_db()
    assert tagged[0].tags == ["Denver"], "not there twice"


@pytest.mark.django_db
def test_removing_a_tag_takes_it_off_every_contact_and_keeps_the_contacts(tagged, ff, api):
    response = post(api, ff, "/api/contact-tags/remove/", {"tag": "Denver"})
    assert response.status_code == 200 and response.json()["changed"] == 2
    for contact in tagged:
        contact.refresh_from_db()
    assert [c.tags for c in tagged] == [["board"], ["board"], ["golf"], []]
    assert Contact.objects.count() == 4
    assert AuditEvent.objects.filter(verb="contact_tag.removed").count() == 1
    # A tag nobody has changes nothing and writes no audit row.
    assert post(api, ff, "/api/contact-tags/remove/", {"tag": "nobody"}).json()["changed"] == 0
    assert AuditEvent.objects.filter(verb="contact_tag.removed").count() == 1
    for body in ({}, {"tag": "  "}, {"tag": "x" * 65}):
        assert post(api, ff, "/api/contact-tags/remove/", body).status_code == 400


@pytest.mark.django_db
def test_tenant_isolation_one_practices_tags_are_not_anothers(tagged, tenant_b, ff, api):
    with tenant_context(tenant_b.pk):
        theirs = ContactFactory(tenant=tenant_b, tags=["board", "SECRET-TAG"])
    other = _member(tenant_b, "FF")
    assert "SECRET-TAG" not in str(api.as_(ff).get("/api/contact-tags/").json())
    post(api, ff, "/api/contact-tags/rename/", {"tag": "board", "to": "renamed"})
    post(api, ff, "/api/contact-tags/remove/", {"tag": "SECRET-TAG"})
    theirs.refresh_from_db()
    assert theirs.tags == ["board", "SECRET-TAG"]
    assert api.as_(other).get("/api/contact-tags/").json() == [
        {"tag": "board", "contacts": 1}, {"tag": "SECRET-TAG", "contacts": 1}]


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["CF", "VA", "FCC", "ECC"])
def test_role_boundaries_only_the_practice_owner_changes_a_tag_everywhere(
        role, tagged, seeded_tenant, api):
    from .factories import ClientCompanyFactory

    company = ClientCompanyFactory(tenant=seeded_tenant) if role in ("FCC", "ECC") else None
    member = _member(seeded_tenant, role, company)
    assert api.as_(member).get("/api/contact-tags/").status_code == 403
    for verb, body in (("rename", {"tag": "board", "to": "x"}), ("remove", {"tag": "board"})):
        assert post(api, member, f"/api/contact-tags/{verb}/", body).status_code == 403
    tagged[0].refresh_from_db()
    assert tagged[0].tags == ["board", "Denver"]
