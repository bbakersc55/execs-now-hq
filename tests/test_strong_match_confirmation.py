"""Creating a new contact over a strong email match needs a confirmation
that names the match (owner, 2026-09-29).

On 2026-09-28 a second Mike Eller was created from a meeting whose proposal
offered the first one, matched by email at 0.98. Matching still proposes and
never decides (AC-5.3, AC-5.4): the reviewer may always create someone new.
What changes is that, over a match this strong, they have to say which contact
they are declining, by id.
"""

from __future__ import annotations

import pytest

from apps.crm.models import Contact
from apps.meetings import ingest
from apps.meetings.models import DriveWatch, ProposalItem
from apps.tenancy.models import AuditEvent

from . import registry_config  # noqa: F401
from .factories import ContactEmailFactory, ContactFactory, MembershipFactory
from .test_module5_acceptance import NOTES, PARSED, FakeDrive, a_file, one_page


@pytest.fixture
def watch(seeded_tenant, in_tenant_a):
    return DriveWatch.objects.create(tenant=seeded_tenant, folder_id="folder-1")


def _dana(tenant):
    dana = ContactFactory(tenant=tenant, first_name="Dana", last_name="Reyes")
    ContactEmailFactory(tenant=tenant, contact=dana, address="dana@acme.invalid",
                        is_primary=True)
    return dana


def _read(tenant):
    ingest.poll(tenant, client=FakeDrive(pages=one_page([a_file("f1")]),
                                         texts={"f1": NOTES}))
    return ProposalItem.objects.get(kind=ProposalItem.Kind.PARTICIPANT,
                                    payload__parsed_name="Dana Reyes")


def _approve(api, member, item, **body):
    return api.as_(member).post(f"/api/proposal-items/{item.pk}/approve/",
                                {"contact_type": "client", "company_id": "", **body},
                                content_type="application/json")


def _danas():
    return Contact.objects.filter(first_name="Dana", last_name="Reyes").count()


@pytest.mark.django_db
def test_creating_new_over_an_email_match_is_refused_naming_the_match(
    seeded_tenant, watch, fake_claude, ff, api
):
    fake_claude.reply = PARSED
    dana = _dana(seeded_tenant)
    item = _read(seeded_tenant)

    response = _approve(api, ff, item)
    assert response.status_code == 409
    body = response.json()
    assert body["match"]["contact_id"] == str(dana.pk)
    assert body["match"]["match_reason"] == "email"
    assert "Dana Reyes (dana@acme.invalid) is already a contact" in body["detail"]
    item.refresh_from_db()
    assert item.state == ProposalItem.State.PENDING
    assert _danas() == 1, "nothing was created"


@pytest.mark.django_db
def test_a_confirmation_naming_someone_else_is_not_a_confirmation(
    seeded_tenant, watch, fake_claude, ff, api
):
    fake_claude.reply = PARSED
    _dana(seeded_tenant)
    other = ContactFactory(tenant=seeded_tenant)
    item = _read(seeded_tenant)
    assert _approve(api, ff, item, create_despite_match=str(other.pk)).status_code == 409
    assert _approve(api, ff, item, create_despite_match="yes").status_code == 409
    assert _danas() == 1


@pytest.mark.django_db
def test_confirmed_by_name_it_creates_and_is_audited(
    seeded_tenant, watch, fake_claude, ff, api
):
    fake_claude.reply = PARSED
    dana = _dana(seeded_tenant)
    item = _read(seeded_tenant)
    response = _approve(api, ff, item, create_despite_match=str(dana.pk))
    assert response.status_code == 201, response.content
    assert _danas() == 2, "the reviewer may still always create someone new (AC-5.4)"
    event = AuditEvent.objects.get(verb="meeting.contact_created_despite_match")
    assert event.payload["matched_contact"] == str(dana.pk)
    assert event.target_id == item.pk


@pytest.mark.django_db
def test_linking_to_the_match_needs_no_confirmation(seeded_tenant, watch, fake_claude, ff, api):
    fake_claude.reply = PARSED
    dana = _dana(seeded_tenant)
    item = _read(seeded_tenant)
    assert _approve(api, ff, item, contact_id=str(dana.pk)).status_code == 201
    assert _danas() == 1


@pytest.mark.django_db
def test_a_match_created_after_the_parse_is_still_found(
    seeded_tenant, watch, fake_claude, ff, api
):
    """The check looks now, not at the candidates stored when the notes were
    read — which is how two proposals for one meeting made two contacts."""
    fake_claude.reply = PARSED
    item = _read(seeded_tenant)
    assert not [c for c in item.payload["existing_candidates"]
                if c["match_reason"] == "email"]
    _dana(seeded_tenant)
    assert _approve(api, ff, item).status_code == 409


@pytest.mark.django_db
def test_a_weaker_match_needs_no_confirmation(seeded_tenant, watch, fake_claude, ff, api):
    """Domain and name (0.71) is below the line: a colleague at the same firm
    is often a different person."""
    fake_claude.reply = PARSED
    priya = ContactFactory(tenant=seeded_tenant, first_name="Priya", last_name="Shah")
    ContactEmailFactory(tenant=seeded_tenant, contact=priya, address="p.shah@acme.invalid",
                        is_primary=True)
    _read(seeded_tenant)
    item = ProposalItem.objects.get(kind=ProposalItem.Kind.PARTICIPANT,
                                    payload__parsed_name="Priya Shah")
    assert _approve(api, ff, item).status_code == 201


@pytest.mark.django_db
def test_the_vendor_path_of_a_dismissal_asks_too(seeded_tenant, watch, fake_claude, ff, api):
    fake_claude.reply = PARSED
    dana = _dana(seeded_tenant)
    item = _read(seeded_tenant)
    url = f"/api/meeting-proposals/{item.proposal_id}/dismiss/"
    vendor = {"item": str(item.pk), "service_categories": ["Dispatch"]}
    refused = api.as_(ff).post(url, {"reason": "vendor_pitch", "vendor": vendor},
                               content_type="application/json")
    assert refused.status_code == 409
    assert refused.json()["match"]["contact_id"] == str(dana.pk)
    assert _danas() == 1
    done = api.as_(ff).post(url, {"reason": "vendor_pitch", "vendor": {
        **vendor, "create_despite_match": str(dana.pk)}}, content_type="application/json")
    assert done.status_code == 200, done.content


# ---------------------------------------------- the two mandatory families

@pytest.mark.django_db
def test_tenant_isolation_another_practices_contact_is_never_a_match(
    tenant_a, tenant_b, seeded_tenant, watch, fake_claude, ff, api
):
    from apps.tenancy.context import tenant_context

    fake_claude.reply = PARSED
    with tenant_context(tenant_b.pk):
        _dana(tenant_b)
    item = _read(seeded_tenant)
    response = _approve(api, ff, item)
    assert response.status_code == 201, "tenant B's Dana is not ours to match"
    assert "match" not in response.json()


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FF", "VA"])
def test_role_boundaries_every_role_that_approves_is_asked(
    role, seeded_tenant, watch, fake_claude, api
):
    """Matrix 11.3 — FF and VA both approve participants, and neither skips
    the confirmation. (CF is covered by proposal-scope; clients reach no
    part of this module.)"""
    fake_claude.reply = PARSED
    _dana(seeded_tenant)
    member = MembershipFactory(tenant=seeded_tenant, role=role)
    item = _read(seeded_tenant)
    assert _approve(api, member, item).status_code == 409
