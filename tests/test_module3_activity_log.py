"""FR-3.41 / 3.41a / matrix 7.16–7.17 — the practice's activity feed.

**This file was the client portal's activity log until 2026-09-16.** The owner
reversed the ruling after using it: the feed is the practice's view across every
account, a client is refused it outright, and the client's window into the work
is the value report (Module 4B). What survives unchanged from the old file is
the part that was never about who owns it — read-only for everybody, acting-as
attribution, and no leak across tenants.
"""

from __future__ import annotations

import json

import pytest
from django.utils import timezone

from apps.work.services import add_comment, add_narrative, apply_task_changes, create_task

from . import registry_config  # noqa: F401
from .factories import (
    ClientAssignmentFactory, ClientCompanyFactory, ContactEmailFactory, ContactFactory,
    MembershipFactory, ProjectFactory, UserFactory,
)

URL = "/api/activity/"
SECRET = "INTERNAL-ONLY: their AP clerk is the bottleneck"


def client_user(tenant, company, role, first):
    user = UserFactory(email=f"{first.lower()}@{company.name.split()[0].lower()}.invalid",
                       full_name=f"{first} Client")
    contact = ContactFactory(tenant=tenant, first_name=first, last_name="Client", company=company)
    ContactEmailFactory(tenant=tenant, contact=contact, address=user.email, is_primary=True)
    return MembershipFactory(tenant=tenant, user=user, role=role, client_company=company,
                             contact=contact)


@pytest.fixture
def world(seeded_tenant, tenant_b, ff, cf, va, api, dev_outbox, in_tenant_a):
    acme = ClientCompanyFactory(tenant=seeded_tenant, name="Acme Facilities", seat_count=5)
    northwind = ClientCompanyFactory(tenant=seeded_tenant, name="Northwind Foods", seat_count=5)
    fcc = client_user(seeded_tenant, acme, "FCC", "Dana")
    ecc = client_user(seeded_tenant, acme, "ECC", "Priya")

    # The CF is assigned to Acme and owns one prospect at no company (FR-1.9c).
    ClientAssignmentFactory(tenant=seeded_tenant, user=cf.user, company=acme)
    theirs = ContactFactory(tenant=seeded_tenant, first_name="Owen", last_name="Prospect",
                            company=None, owner=cf.user)

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

    northwind_task = create_task(tenant=seeded_tenant, actor=ff.user, role="FF",
                                 title="NORTHWIND recipe costing", client_company=northwind)
    add_comment(northwind_task, author=ff.user, role="FF", body="NORTHWIND shared",
                visibility="shared")

    doomed = create_task(tenant=seeded_tenant, actor=ff.user, role="FF",
                         title="Old signage", client_company=acme)
    assert api.as_(ff).delete(f"/api/tasks/{doomed.pk}/").status_code == 204

    b_co = ClientCompanyFactory(tenant=tenant_b, name="Tenant B Co", seat_count=1)
    return {"acme": acme, "northwind": northwind, "fcc": fcc, "ecc": ecc, "dock": dock,
            "ff": ff, "cf": cf, "va": va, "cf_contact": theirs, "b_co": b_co}


def entries(api, member, query=""):
    response = api.as_(member).get(f"{URL}{query}")
    assert response.status_code == 200, response.content
    return response.json()


def blob(rows):
    return "\n".join(e["text"] for e in rows)


# ------------------------------------------------- what the practice now sees

@pytest.mark.django_db
def test_the_feed_shows_work_across_every_account(api, world):
    text = blob(entries(api, world["ff"]))
    assert "created “Fix the loading dock”" in text
    assert "moved “Fix the loading dock” from Not started to In progress — Parts are ordered." in text
    assert "added a note on “Safer site”: Audit booked." in text
    assert "deleted a task" in text
    # Across accounts, which is the whole point of the reversal.
    assert "NORTHWIND recipe costing" in text
    # And the practice's own hidden work, which the client's log never showed.
    assert "HIDDEN renegotiate their fee" in text


@pytest.mark.django_db
def test_internal_comments_are_shown_to_the_practice(api, world):
    """The clearest single difference from the client's version, which never saw
    them. Staff read internal comments everywhere else; hiding them here would be
    lying by omission rather than protecting anything."""
    rows = entries(api, world["ff"])
    assert SECRET in blob(rows)
    kinds = {e["kind"] for e in rows}
    assert {"internal", "shared"} <= kinds


@pytest.mark.django_db
def test_newest_first(api, world):
    ats = [e["at"] for e in entries(api, world["ff"])]
    assert ats == sorted(ats, reverse=True)


# --------------------------------------------------------------- matrix 7.16

@pytest.mark.django_db
@pytest.mark.parametrize("who", ["fcc", "ecc"])
def test_matrix_7_16_a_client_is_refused_the_feed(who, api, world):
    """FR-3.41a — reversed. It was theirs; it is now refused to them, and the
    refusal does not describe what they are missing."""
    response = api.as_(world[who]).get(URL)
    assert response.status_code == 403
    assert "Not available." == response.json()["detail"]


@pytest.mark.django_db
@pytest.mark.parametrize("who", ["ff", "va"])
def test_matrix_7_16_ff_and_va_see_the_whole_tenant(who, api, world):
    text = blob(entries(api, world[who]))
    assert "Fix the loading dock" in text and "NORTHWIND recipe costing" in text


@pytest.mark.django_db
def test_matrix_7_16_a_cf_sees_assigned_companies_and_contacts_they_own(api, world):
    rows = entries(api, world["cf"])
    text = blob(rows)
    assert "Fix the loading dock" in text, "Acme is assigned to them"
    assert "NORTHWIND" not in text, "Northwind is not"
    companies = {e["company"]["id"] for e in rows if e["company"]}
    assert str(world["northwind"].pk) not in companies


@pytest.mark.django_db
def test_a_cf_is_not_shown_the_practices_own_tenant_wide_events(api, world, seeded_tenant):
    """An event attached to no company and no contact — a Gmail connection, the
    API key rotated — is the practice's business, not one of their accounts."""
    from .factories import AuditEventFactory

    AuditEventFactory(tenant=seeded_tenant, verb="gmail.connected", actor=world["ff"].user)
    assert "connected Gmail" in blob(entries(api, world["ff"]))
    assert "connected Gmail" not in blob(entries(api, world["cf"]))


# --------------------------------------------------------------- matrix 7.17

@pytest.mark.django_db
@pytest.mark.parametrize("who", ["ff", "cf", "va", "fcc", "ecc"])
def test_matrix_7_17_nobody_can_write_to_the_feed(who, api, world):
    client = api.as_(world[who])
    for method, path in (("post", URL), ("patch", f"{URL}a-1/"), ("delete", f"{URL}a-1/")):
        response = getattr(client, method)(path, {}, content_type="application/json")
        assert response.status_code in (403, 404, 405), (who, method, response.status_code)


# ------------------------------------------------------------------- filters

@pytest.mark.django_db
def test_filtering_by_company_contact_actor_type_and_dates(api, world, seeded_tenant):
    ff = world["ff"]
    only_acme = entries(api, ff, f"?company={world['acme'].pk}")
    assert only_acme and all(e["company"]["id"] == str(world["acme"].pk) for e in only_acme)
    assert "NORTHWIND" not in blob(only_acme)

    by_type = entries(api, ff, "?category=comment")
    assert by_type and {e["category"] for e in by_type} == {"comment"}

    by_actor = entries(api, ff, f"?actor={ff.user_id}")
    assert by_actor
    assert not entries(api, ff, f"?actor={world['fcc'].user_id}")

    assert not entries(api, ff, "?since=2030-01-01T00:00:00Z")
    assert entries(api, ff, "?since=2020-01-01T00:00:00Z")
    assert not entries(api, ff, "?until=2020-01-01T00:00:00Z")


@pytest.mark.django_db
def test_a_nonsense_filter_is_refused_rather_than_ignored(api, world):
    """Ignoring an unparseable filter answers a different question than the one
    asked, which on a feed like this reads as 'nothing happened'."""
    client = api.as_(world["ff"])
    assert client.get(f"{URL}?company=not-a-uuid").status_code == 400
    assert client.get(f"{URL}?category=invented").status_code == 400
    assert client.get(f"{URL}?since=yesterday").status_code == 400


# --------------------------------------------------------------------- notes

@pytest.mark.django_db
def test_a_pin_gated_note_gives_up_neither_its_body_nor_its_title(api, world, seeded_tenant):
    """The PIN is a screen over the note (FR-2.8). A feed printing the title
    beside the author and the time would be the way around it."""
    from apps.notes.models import Note

    Note.all_objects.create(tenant=seeded_tenant, title="Open note", body="plain",
                            created_by=world["ff"].user)
    Note.all_objects.create(tenant=seeded_tenant, title="SECRET TITLE", body="SECRET BODY",
                            created_by=world["ff"].user, pin_hash="x" * 60,
                            pin_set_at=timezone.now())   # The pair is a CHECK.

    raw = json.dumps(entries(api, world["ff"]))
    assert "Open note" in raw
    assert "SECRET TITLE" not in raw and "SECRET BODY" not in raw
    assert "a PIN-protected note" in raw
    # No note body reaches the feed, PIN or not.
    assert "plain" not in blob(entries(api, world["ff"]))


# ------------------------------------------------------------ attribution etc.

@pytest.mark.django_db
def test_work_done_while_acting_reads_by_x_on_behalf_of_y(ff, api, world):
    """FR-3.42, unchanged by the reversal: the real person is named first, and
    the act-as session is itself in the feed — now for the practice to read
    about its own team rather than for the client to read about the practice."""
    client = api.as_(ff)
    assert client.post("/api/act-as/", json.dumps({"membership": str(world["ecc"].pk)}),
                       content_type="application/json").status_code == 201
    assert client.post("/api/comments/", json.dumps(
        {"task": str(world["dock"].pk), "body": "Posted while acting."}),
        content_type="application/json").status_code == 201
    client.post("/api/act-as/stop/")

    rows = entries(api, ff)
    acted = next(e for e in rows if "Posted while acting." in e["text"])
    assert acted["by"] == ff.user.full_name or acted["by"] == ff.user.email
    assert acted["on_behalf_of"] == "Priya Client"
    began = next(e for e in rows if e["kind"] == "act_as.started")
    assert began["text"] == "began acting as Priya Client" and began["on_behalf_of"] is None
    assert any(e["kind"] == "act_as.stopped" for e in rows)
    plain = next(e for e in rows if "Shared: install is Tuesday." in e["text"])
    assert plain["on_behalf_of"] is None


@pytest.mark.django_db
def test_another_tenants_activity_is_never_in_this_ones_feed(tenant_b, api, world):
    b_ff = MembershipFactory(tenant=tenant_b, role="FF")
    assert "Fix the loading dock" not in blob(entries(api, b_ff))
    assert "Acme Facilities" not in json.dumps(entries(api, b_ff))
