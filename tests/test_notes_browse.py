"""The Notes grid: `GET /api/notes/browse/` (docs/ui1_pipeline_board.md §9).

The rule that needs proving is the locked one: a card is a name and a date,
and no filter may be a way to learn what a locked note says or is linked to.
"""

from __future__ import annotations

import json

import pytest
from django.utils import timezone

from apps.notes.models import Note

from . import registry_config  # noqa: F401
from .factories import (
    ClientAssignmentFactory, ClientCompanyFactory, CompanyFactory, ContactFactory,
    MembershipFactory,
)

URL = "/api/notes/browse/"
SECRET = "CONFIDENTIAL SEVERANCE DISCUSSION"


def post(client, url, data=None):
    return client.post(url, json.dumps(data or {}), content_type="application/json")


def note(client, **data):
    response = post(client, "/api/notes/", {"body": "Some text.", **data})
    assert response.status_code == 201, response.content
    return response.json()


def lock(client, note_id, pin="4821"):
    assert post(client, f"/api/notes/{note_id}/pin/", {"pin": pin}).status_code == 200


def titles(client, **params):
    return [n["title"] for n in client.get(URL, params).json()["results"]]


def backdate(note_id, days):
    Note.all_objects.filter(pk=note_id).update(
        created_at=timezone.now() - timezone.timedelta(days=days))


@pytest.mark.django_db
def test_the_grid_opens_with_the_latest_twenty_newest_first(seeded_tenant, ff, api):
    client = api.as_(ff)
    for n in range(23):
        backdate(note(client, title=f"Note {n:02d}")["id"], days=n)

    body = client.get(URL).json()

    assert body["total"] == 23
    assert [n["title"] for n in body["results"]] == [f"Note {n:02d}" for n in range(20)]
    # "Show older" asks for more of the same list.
    assert len(client.get(URL, {"limit": 40}).json()["results"]) == 23


@pytest.mark.django_db
def test_a_card_is_a_name_a_date_and_a_lock_and_nothing_else(seeded_tenant, ff, api):
    client = api.as_(ff)
    contact = ContactFactory(tenant=seeded_tenant)
    note(client, title="Kickoff", contact=str(contact.pk))

    card = client.get(URL).json()["results"][0]

    assert set(card) == {"id", "title", "is_locked", "created_at"}


@pytest.mark.django_db
def test_a_search_returns_every_match_not_the_latest_twenty(seeded_tenant, ff, api):
    client = api.as_(ff)
    for n in range(25):
        note(client, title=f"Dispatch review {n}")
    note(client, title="Unrelated")

    body = client.get(URL, {"q": "dispatch", "limit": 200}).json()

    assert body["total"] == 25 and len(body["results"]) == 25


@pytest.mark.django_db
def test_filters_by_company_contact_name_and_date(seeded_tenant, ff, api):
    client = api.as_(ff)
    acme = CompanyFactory(tenant=seeded_tenant, name="Acme Freight")
    dana = ContactFactory(tenant=seeded_tenant, first_name="Dana", last_name="Reyes",
                          company=acme)
    other = ContactFactory(tenant=seeded_tenant)
    note(client, title="On the company", company=str(acme.pk))
    note(client, title="On Dana", contact=str(dana.pk))
    note(client, title="On someone else", contact=str(other.pk))
    backdate(note(client, title="Old and loose")["id"], days=40)

    # A note on a contact counts for that contact's company.
    assert set(titles(client, company=str(acme.pk))) == {"On the company", "On Dana"}
    assert titles(client, contact=str(dana.pk)) == ["On Dana"]
    assert titles(client, name="loose") == ["Old and loose"]
    week_ago = (timezone.now() - timezone.timedelta(days=7)).isoformat()
    assert "Old and loose" not in titles(client, after=week_ago)
    assert titles(client, before=week_ago) == ["Old and loose"]

    body = client.get(URL).json()
    assert body["companies"] == [{"id": str(acme.pk), "name": "Acme Freight"}]
    assert {"id": str(dana.pk), "name": "Dana Reyes"} in body["contacts"]


@pytest.mark.django_db
def test_a_bad_filter_is_refused_rather_than_ignored(seeded_tenant, ff, api):
    client = api.as_(ff)
    for params in ({"company": "acme"}, {"contact": "1"}, {"after": "yesterday"},
                   {"limit": "lots"}):
        assert client.get(URL, params).status_code == 400, params


@pytest.mark.django_db
def test_a_locked_note_is_found_by_every_filter_as_a_card(seeded_tenant, ff, va, api):
    """Owner, 2026-10-05: filters are for finding a note you half remember, so
    a locked one must come up; the PIN is what stops you opening it."""
    acme = CompanyFactory(tenant=seeded_tenant, name="Acme Freight")
    dana = ContactFactory(tenant=seeded_tenant, first_name="Dana", last_name="Reyes",
                          company=acme)
    locked = note(api.as_(ff), title="HR matter", contact=str(dana.pk), body=SECRET)
    lock(api.as_(ff), locked["id"])
    note(api.as_(ff), title="Open one")
    viewer = api.as_(va)

    body = viewer.get(URL).json()
    # A company or contact with only a locked note is still an option.
    assert body["companies"] == [{"id": str(acme.pk), "name": "Acme Freight"}]
    assert body["contacts"] == [{"id": str(dana.pk), "name": "Dana Reyes"}]

    today = (timezone.now() - timezone.timedelta(hours=1)).isoformat()
    for params in ({"contact": str(dana.pk)}, {"company": str(acme.pk)},
                   {"name": "hr mat"}, {"after": today, "name": "HR"}, {"locked": "only"}):
        cards = viewer.get(URL, params).json()["results"]
        assert [(c["title"], c["is_locked"]) for c in cards] == [("HR matter", True)], params
        # Still only a card: nothing of the note comes with it.
        assert set(cards[0]) == {"id", "title", "is_locked", "created_at"}

    assert viewer.get(URL, {"locked": "sometimes"}).status_code == 400


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FF", "CF", "VA"])
def test_whoever_gets_a_locked_card_already_sees_its_links_on_the_note(
    seeded_tenant, ff, api, role
):
    """Why the filters reveal nothing new: for every role that is served a
    locked note's card, the note's own page already names what it is linked to
    (the stub), and nothing else."""
    theirs = ClientCompanyFactory(tenant=seeded_tenant, name="Theirs Ltd")
    dana = ContactFactory(tenant=seeded_tenant, first_name="Dana", last_name="Reyes",
                          company=theirs)
    on_contact = note(api.as_(ff), title="HR matter", contact=str(dana.pk), body=SECRET)
    on_company = note(api.as_(ff), title="Board matter", company=str(theirs.pk), body=SECRET)
    for made in (on_contact, on_company):
        lock(api.as_(ff), made["id"])
    viewer_membership = MembershipFactory(tenant=seeded_tenant, role=role)
    if role == "CF":
        ClientAssignmentFactory(tenant=seeded_tenant, user=viewer_membership.user,
                                company=theirs)
    viewer = api.as_(viewer_membership)

    cards = viewer.get(URL, {"company": str(theirs.pk)}).json()["results"]
    assert {c["id"] for c in cards} == {on_contact["id"], on_company["id"]}

    for card in cards:
        stub = viewer.get(f"/api/notes/{card['id']}/").json()
        assert stub["stub"] is True
        assert stub["contact_name"] == "Dana Reyes" or stub["company_name"] == "Theirs Ltd"
        assert "body" not in stub
    assert SECRET not in viewer.get(URL, {"company": str(theirs.pk)}).content.decode()


@pytest.mark.django_db
def test_no_filter_or_search_gives_away_a_locked_notes_content(seeded_tenant, ff, va, api):
    """Contents never leak; links may be used by the filters."""
    dana = ContactFactory(tenant=seeded_tenant, first_name="Dana", last_name="Reyes")
    locked = note(api.as_(ff), title="HR matter", contact=str(dana.pk),
                  body=SECRET + " The ops lead is leaving.")
    lock(api.as_(ff), locked["id"])
    viewer = api.as_(va)

    # Body words find nothing, alone or combined with a filter that does match.
    for params in ({"q": "severance"}, {"q": "confidential"}, {"name": "severance"},
                   {"q": "severance", "contact": str(dana.pk)},
                   {"q": "leaving", "locked": "only"}):
        assert titles(viewer, **params) == [], params
    # The title does, by search as well as by name.
    assert titles(viewer, q="HR") == ["HR matter"]
    assert titles(viewer, q="HR", contact=str(dana.pk), locked="only") == ["HR matter"]

    for params in ({}, {"contact": str(dana.pk)}, {"locked": "only"}, {"q": "HR"}):
        blob = viewer.get(URL, params).content.decode()
        assert SECRET not in blob and "ops lead" not in blob, params


@pytest.mark.django_db
def test_a_locked_notes_hidden_title_and_body_match_nothing(seeded_tenant, ff, va, api):
    """FR-2.11b on the grid: an auto title is the first line of the body."""
    auto = note(api.as_(ff), body="Severance terms for the ops lead.")
    lock_response = post(api.as_(ff), f"/api/notes/{auto['id']}/pin/", {"pin": "4821"})
    if lock_response.status_code != 200:
        # The workflow refuses a PIN on an auto-titled note; force the state
        # the API bypass tests cover, so the grid is proven against it too.
        Note.all_objects.filter(pk=auto["id"]).update(
            pin_hash="h", pin_set_at=timezone.now(), title_is_auto=True)
    typed = note(api.as_(ff), title="HR matter", body="Severance, in detail.")
    lock(api.as_(ff), typed["id"])
    viewer = api.as_(va)

    assert sorted(titles(viewer)) == ["HR matter", "Locked note"]
    assert titles(viewer, name="severance") == []
    assert titles(viewer, name="locked") == []
    assert titles(viewer, q="severance") == []
    # Found by its typed title, as today, by search and by name.
    assert titles(viewer, q="HR") == ["HR matter"]
    assert titles(viewer, name="hr mat") == ["HR matter"]
    assert "everance" not in viewer.get(URL).content.decode()


@pytest.mark.django_db
def test_an_associate_sees_and_filters_only_their_own_scope(seeded_tenant, ff, api):
    """Role visibility is the list's: the grid adds no way round it."""
    theirs = ClientCompanyFactory(tenant=seeded_tenant, name="Theirs Ltd")
    not_theirs = CompanyFactory(tenant=seeded_tenant, name="Someone Else Inc")
    cf = MembershipFactory(tenant=seeded_tenant, role="CF")
    ClientAssignmentFactory(tenant=seeded_tenant, user=cf.user, company=theirs)
    note(api.as_(ff), title="In scope", company=str(theirs.pk))
    note(api.as_(ff), title="Out of scope", company=str(not_theirs.pk))

    body = api.as_(cf).get(URL).json()

    assert [n["title"] for n in body["results"]] == ["In scope"]
    assert [c["name"] for c in body["companies"]] == ["Theirs Ltd"]
    assert titles(api.as_(cf), company=str(not_theirs.pk)) == []


@pytest.mark.django_db
def test_a_contacts_company_is_not_given_to_someone_who_cannot_see_the_contact(
    seeded_tenant, ff, api
):
    """An associate keeps a note they wrote on a contact that has since left
    their scope. The note names the contact; the filters must not add where
    that contact works."""
    elsewhere = CompanyFactory(tenant=seeded_tenant, name="Someone Else Inc")
    cf = MembershipFactory(tenant=seeded_tenant, role="CF")
    contact = ContactFactory(tenant=seeded_tenant, company=elsewhere, owner=cf.user)
    written = note(api.as_(cf), title="My note", contact=str(contact.pk))
    type(contact).all_objects.filter(pk=contact.pk).update(owner=ff.user)

    body = api.as_(cf).get(URL).json()

    assert [n["id"] for n in body["results"]] == [written["id"]]
    assert body["companies"] == []
    assert titles(api.as_(cf), company=str(elsewhere.pk)) == []
    # The practice owner sees the contact, so for them it counts.
    assert titles(api.as_(ff), company=str(elsewhere.pk)) == ["My note"]
