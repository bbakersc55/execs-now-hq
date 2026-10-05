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
def test_filters_do_not_reveal_what_a_locked_note_is_linked_to(seeded_tenant, ff, va, api):
    """The stub shows a locked note's links; a filter must not confirm them."""
    acme = CompanyFactory(tenant=seeded_tenant, name="Acme Freight")
    dana = ContactFactory(tenant=seeded_tenant, first_name="Dana", last_name="Reyes",
                          company=acme)
    locked = note(api.as_(ff), title="HR matter", contact=str(dana.pk))
    lock(api.as_(ff), locked["id"])
    viewer = api.as_(va)

    body = viewer.get(URL).json()
    # It is on the grid, by its typed title, and marked.
    assert [(n["title"], n["is_locked"]) for n in body["results"]] == [("HR matter", True)]
    # It offers no filter option, and matches neither filter.
    assert body["companies"] == [] and body["contacts"] == []
    assert titles(viewer, contact=str(dana.pk)) == []
    assert titles(viewer, company=str(acme.pk)) == []
    assert "Dana" not in viewer.get(URL).content.decode()


@pytest.mark.django_db
def test_an_unlocked_note_filters_like_any_other_for_that_session_only(
    seeded_tenant, ff, va, api
):
    dana = ContactFactory(tenant=seeded_tenant, first_name="Dana", last_name="Reyes")
    locked = note(api.as_(ff), title="HR matter", contact=str(dana.pk))
    lock(api.as_(ff), locked["id"])

    opener = api.as_(va)
    assert post(opener, f"/api/notes/{locked['id']}/unlock/", {"pin": "4821"}).status_code == 200
    assert titles(opener, contact=str(dana.pk)) == ["HR matter"]

    someone_else = api.as_(MembershipFactory(tenant=seeded_tenant, role="VA"))
    assert titles(someone_else, contact=str(dana.pk)) == []


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
