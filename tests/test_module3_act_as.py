"""FR-3.42 / matrix 9.6–9.10 — acting as another user.

What these hold down, in order of consequence:

1. No email of any kind leaves while acting: logged as suppressed, never sent.
2. Everything written carries both people.
3. It never crosses a company or tenant boundary, a VA cannot do it at all, and
   it ends the moment it is no longer permitted.
4. Entering and leaving are explicit and audited.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.crm.models import OutboxMessage, Task
from apps.tenancy.models import AuditEvent
from apps.work.models import Cadence, Comment, Digest, Stakeholder, TaskUpdate

from . import registry_config  # noqa: F401
from .factories import (
    ClientAssignmentFactory, ClientCompanyFactory, ContactEmailFactory, ContactFactory,
    MembershipFactory, UserFactory,
)


def post(client, url, data=None):
    return client.post(url, json.dumps(data or {}), content_type="application/json")


def start(client, membership):
    return post(client, "/api/act-as/", {"membership": str(membership.pk)})


def client_user(tenant, company, role, first):
    user = UserFactory(email=f"{first.lower()}@{company.name.split()[0].lower()}.invalid",
                       full_name=f"{first} Client")
    contact = ContactFactory(tenant=tenant, first_name=first, last_name="Client",
                             company=company)
    ContactEmailFactory(tenant=tenant, contact=contact, address=user.email, is_primary=True)
    return MembershipFactory(tenant=tenant, user=user, role=role, client_company=company,
                             contact=contact)


@pytest.fixture
def acme(seeded_tenant):
    return ClientCompanyFactory(tenant=seeded_tenant, name="Acme Facilities", seat_count=5,
                                digest_ai_prose=False)


@pytest.fixture
def northwind(seeded_tenant):
    return ClientCompanyFactory(tenant=seeded_tenant, name="Northwind Foods", seat_count=5)


@pytest.fixture
def acme_fcc(seeded_tenant, acme):
    return client_user(seeded_tenant, acme, "FCC", "Dana")


@pytest.fixture
def acme_ecc(seeded_tenant, acme):
    return client_user(seeded_tenant, acme, "ECC", "Priya")


@pytest.fixture
def northwind_ecc(seeded_tenant, northwind):
    return client_user(seeded_tenant, northwind, "ECC", "Sam")


# ------------------------------------------------------------- entering

@pytest.mark.django_db
def test_an_ff_acts_as_a_client_user_and_is_scoped_exactly_as_them(
    ff, api, acme, acme_ecc, in_tenant_a
):
    client = api.as_(ff)
    started = start(client, acme_ecc)
    assert started.status_code == 201, started.content
    assert started.json()["as_email"] == acme_ecc.user.email

    me = client.get("/api/me").json()
    assert me["role"] == "ECC" and me["email"] == acme_ecc.user.email
    assert me["client_company"] == str(acme.pk)
    assert me["acting"]["real_email"] == ff.user.email and me["acting"]["real_role"] == "FF"
    assert me["acting"]["as_name"] == "Priya Client"
    assert me["acting"]["company_name"] == "Acme Facilities"
    # The practice's own screens are closed to them, as to the client (matrix 4.18).
    assert client.get("/api/contacts/").status_code == 403

    event = AuditEvent.all_objects.get(verb="act_as.started")
    assert event.actor == ff.user and event.target_id == acme_ecc.pk
    assert event.payload["acting_role"] == "FF" and event.payload["acted_as_role"] == "ECC"


@pytest.mark.django_db
@pytest.mark.parametrize("role,assigned,expected", [
    ("FF", False, 201), ("CF", True, 201), ("CF", False, 404),
    ("VA", False, 403), ("ECC", False, 403),
])
def test_matrix_9_6_who_may_act_as_a_client_user(role, assigned, expected, seeded_tenant,
                                                  api, acme, acme_ecc, in_tenant_a):
    member = MembershipFactory(tenant=seeded_tenant, role=role,
                               client_company=acme if role in ("FCC", "ECC") else None)
    if assigned:
        ClientAssignmentFactory(tenant=seeded_tenant, user=member.user, company=acme)
    assert start(api.as_(member), acme_ecc).status_code == expected
    if expected != 201:
        assert not AuditEvent.all_objects.filter(verb="act_as.started").exists()


@pytest.mark.django_db
def test_an_fcc_acts_as_another_user_in_their_own_company_only(
    api, acme_fcc, acme_ecc, northwind_ecc, in_tenant_a
):
    client = api.as_(acme_fcc)
    assert start(client, northwind_ecc).status_code == 404, "Across a company."
    assert start(client, acme_fcc).status_code == 404, "As themselves."
    assert start(client, acme_ecc).status_code == 201
    assert client.get("/api/me").json()["acting"]["real_role"] == "FCC"


@pytest.mark.django_db
def test_acting_as_never_crosses_a_tenant_or_reaches_staff_or_a_non_client(
    seeded_tenant, tenant_b, ff, va, api, acme, acme_ecc, in_tenant_a
):
    client = api.as_(ff)
    other_co = ClientCompanyFactory(tenant=tenant_b, name="Tenant B Co", seat_count=1)
    other_tenant_user = MembershipFactory(tenant=tenant_b, role="ECC", client_company=other_co)
    assert start(client, other_tenant_user).status_code == 404
    assert start(client, va).status_code == 404, "Tenant staff are never acted as."
    assert start(client, ff).status_code == 404

    prospect = ClientCompanyFactory(tenant=seeded_tenant, name="Former Client")
    former = client_user(seeded_tenant, prospect, "ECC", "Olu")
    prospect.is_client_company = False
    prospect.save()
    assert start(client, former).status_code == 404, "Not a company they could grant."

    acme_ecc.revoked_at = timezone.now()
    acme_ecc.save()
    assert start(client, acme_ecc).status_code == 404, "A revoked login."
    assert post(client, "/api/act-as/", {"membership": "not-a-uuid"}).status_code == 404


@pytest.mark.django_db
def test_acting_as_is_never_nested(ff, api, acme_fcc, acme_ecc, in_tenant_a):
    client = api.as_(ff)
    assert start(client, acme_fcc).status_code == 201
    nested = start(client, acme_ecc)
    assert nested.status_code == 409 and "first" in nested.json()["detail"]
    assert client.get("/api/me").json()["acting"]["as_email"] == acme_fcc.user.email


# -------------------------------------------------- what is written while acting

@pytest.mark.django_db
def test_every_update_comment_and_audit_event_carries_both_people(
    ff, api, acme, acme_ecc, in_tenant_a
):
    client = api.as_(ff)
    start(client, acme_ecc)
    task = post(client, "/api/tasks/", {"title": "Order the new dock plate"}).json()
    assert post(client, "/api/comments/", {"task": task["id"], "body": "Quote attached."}
                ).status_code == 201

    created = TaskUpdate.all_objects.get(task_id=task["id"], kind="created")
    assert created.actor == acme_ecc.user
    assert created.acting_user == ff.user and created.acted_as_user == acme_ecc.user
    comment = Comment.all_objects.get(task_id=task["id"])
    assert comment.author == acme_ecc.user
    assert comment.acting_user == ff.user and comment.acted_as_user == acme_ecc.user

    assert client.delete(f"/api/tasks/{task['id']}/").status_code == 204
    deleted = AuditEvent.all_objects.get(verb="task.deleted")
    assert deleted.acting_user == ff.user and deleted.acted_as_user == acme_ecc.user

    # The API names the real person too, for "by X on behalf of Y".
    updates = api.as_(ff).get(f"/api/tasks/{task['id']}/updates/")
    # (deleted, so read the row directly)
    assert updates.status_code in (200, 404)
    from apps.work.serializers import represent_update

    shown = represent_update(created)
    assert shown["actor"]["name"] == "Priya Client"
    assert shown["acting_user"]["id"] == str(ff.user.pk)


@pytest.mark.django_db
def test_nothing_written_outside_acting_is_stamped(ff, api, acme_ecc, in_tenant_a):
    client = api.as_(ff)
    start(client, acme_ecc)
    post(client, "/api/act-as/stop/")
    task = api.as_(acme_ecc).post("/api/tasks/", json.dumps({"title": "Mine"}),
                                  content_type="application/json").json()
    row = TaskUpdate.all_objects.get(task_id=task["id"], kind="created")
    assert row.acting_user_id is None and row.acted_as_user_id is None


# --------------------------------------------------------------- no email

@pytest.mark.django_db
def test_a_magic_link_requested_while_acting_is_logged_suppressed_and_never_sent(
    ff, api, acme_ecc, dev_outbox, in_tenant_a
):
    client = api.as_(ff)
    start(client, acme_ecc)
    dev_outbox.clear()
    client.post("/auth/magic/request", {"email": acme_ecc.user.email})

    assert dev_outbox == [], "An email left while acting."
    message = OutboxMessage.all_objects.get(producer="magic_link")
    assert message.state == "suppressed"
    assert "/auth/magic/" not in message.body_text, "A one-time link must never be stored."
    event = AuditEvent.all_objects.get(verb="email.suppressed", target_id=message.pk)
    assert event.payload["producer"] == "magic_link"
    assert event.acting_user == ff.user


@pytest.mark.django_db
def test_changes_made_while_acting_never_reach_a_digest_or_a_client_activity_notice(
    seeded_tenant, ff, api, acme, acme_ecc, dev_outbox, in_tenant_a
):
    from apps.work.services import apply_task_changes
    from apps.work.tasks import notify_client_activity, tick

    watcher = ContactFactory(tenant=seeded_tenant, first_name="Wes", last_name="Watcher",
                             company=acme)
    ContactEmailFactory(tenant=seeded_tenant, contact=watcher, address="wes@acme.invalid",
                        is_primary=True)
    client = api.as_(ff)
    start(client, acme_ecc)
    task = post(client, "/api/tasks/", {"title": "Replace the gate"}).json()
    Stakeholder.all_objects.create(tenant=seeded_tenant, contact=watcher, cadence="every_update",
                                   task_id=task["id"],
                                   created_at=timezone.now() - timedelta(minutes=5))
    assert client.patch(f"/api/tasks/{task['id']}/", json.dumps({"status": "in_progress"}),
                        content_type="application/json").status_code == 200
    suppressed = AuditEvent.all_objects.filter(verb="email.suppressed",
                                               target_type="task_update")
    assert suppressed.count() >= 2, "Each update written while acting is logged as suppressed."

    later = timezone.now() + timedelta(minutes=45)
    assert notify_client_activity(seeded_tenant, now=later) == 0
    tick(str(seeded_tenant.pk), now=later)
    assert not Digest.all_objects.exists(), "A change made while acting was put in a digest."
    assert dev_outbox == []

    # Not a blanket off-switch: the same change made for real is reported.
    post(client, "/api/act-as/stop/")
    real_task = Task.all_objects.get(pk=task["id"])
    apply_task_changes(real_task, actor=ff.user, role="FF", changes={"status": "blocked"})
    tick(str(seeded_tenant.pk), now=timezone.now() + timedelta(minutes=31))
    digest = Digest.all_objects.get(contact=watcher)
    assert digest.items.count() == 1


# --------------------------------------------------------------- leaving

@pytest.mark.django_db
def test_stop_acting_as_is_explicit_and_audited(ff, api, acme, acme_ecc, in_tenant_a):
    client = api.as_(ff)
    start(client, acme_ecc)
    stopped = post(client, "/api/act-as/stop/")
    assert stopped.status_code == 200
    assert stopped.json()["return_to"] == f"/companies/{acme.pk}"

    me = client.get("/api/me").json()
    assert me["acting"] is None and me["role"] == "FF"
    event = AuditEvent.all_objects.get(verb="act_as.stopped")
    assert event.actor == ff.user and event.target_id == acme_ecc.pk
    assert post(client, "/api/act-as/stop/").status_code == 409


@pytest.mark.django_db
def test_acting_ends_the_moment_it_is_no_longer_permitted(
    seeded_tenant, cf, api, acme, acme_ecc, in_tenant_a
):
    assignment = ClientAssignmentFactory(tenant=seeded_tenant, user=cf.user, company=acme)
    client = api.as_(cf)
    assert start(client, acme_ecc).status_code == 201
    assert client.get("/api/me").json()["acting"] is not None

    assignment.removed_at = timezone.now()
    assignment.save()
    me = client.get("/api/me").json()
    assert me["acting"] is None and me["role"] == "CF"
    ended = AuditEvent.all_objects.get(verb="act_as.ended")
    assert ended.payload["reason"] == "no longer permitted"


@pytest.mark.django_db
def test_revoking_the_acted_as_user_ends_the_session(ff, api, acme_ecc, in_tenant_a):
    client = api.as_(ff)
    start(client, acme_ecc)
    acme_ecc.revoked_at = timezone.now()
    acme_ecc.save()
    assert client.get("/api/me").json()["acting"] is None
    assert AuditEvent.all_objects.filter(verb="act_as.ended").exists()


# ------------------------------------------------------------- candidates

@pytest.mark.django_db
def test_candidates_are_exactly_who_the_real_person_may_act_as(
    seeded_tenant, tenant_b, ff, cf, va, api, acme, northwind, acme_fcc, acme_ecc,
    northwind_ecc, in_tenant_a
):
    def emails(member):
        response = api.as_(member).get("/api/act-as/candidates/")
        assert response.status_code == 200, response.content
        return sorted(r["email"] for r in response.json())

    other_co = ClientCompanyFactory(tenant=tenant_b, name="Tenant B Co", seat_count=1)
    MembershipFactory(tenant=tenant_b, role="ECC", client_company=other_co)

    assert emails(ff) == sorted([acme_fcc.user.email, acme_ecc.user.email,
                                 northwind_ecc.user.email])
    ClientAssignmentFactory(tenant=seeded_tenant, user=cf.user, company=northwind)
    assert emails(cf) == [northwind_ecc.user.email]
    assert emails(acme_fcc) == [acme_ecc.user.email]
    for member in (va, acme_ecc):
        assert api.as_(member).get("/api/act-as/candidates/").status_code == 403

    client = api.as_(ff)
    start(client, acme_ecc)
    assert client.get("/api/act-as/candidates/").status_code == 409


@pytest.mark.django_db
def test_signing_out_while_acting_ends_it_and_is_logged_like_any_other_end(
    ff, api, acme, acme_ecc, in_tenant_a
):
    client = api.as_(ff)
    start(client, acme_ecc)
    assert client.post("/accounts/logout/").status_code in (200, 302)

    ended = AuditEvent.all_objects.get(verb="act_as.ended")
    assert ended.actor == ff.user and ended.target_id == acme_ecc.pk
    assert ended.payload["reason"] == "signed out"
    assert client.get("/api/me").status_code == 401
    # Signing back in does not resume it.
    client.force_login(ff.user)
    assert client.get("/api/me").json()["acting"] is None

    # And the practice's feed says why it ended. This read the client's log until
    # 2026-09-16; the reason line is the same, the audience is not (FR-3.41a).
    rows = api.as_(ff).get("/api/activity/").json()
    assert any(r["text"] == "stopped acting as Priya Client (signed out)" for r in rows)


@pytest.mark.django_db
def test_signing_out_when_not_acting_logs_no_act_as_end(ff, api, in_tenant_a):
    assert api.as_(ff).post("/accounts/logout/").status_code in (200, 302)
    assert not AuditEvent.all_objects.filter(verb__startswith="act_as").exists()
