"""Digests on the demo (owner, 2026-10-10). The demo runs no worker, so
nothing there sends an approved digest at its window or marks a missed one
late. Two things are different there, and only there:

1. Approving a digest sends it at once, inside the request, down the same
   path as Send now. Every send on the demo goes to its one redirect address.
2. A digest still waiting when its send time has passed is expired when a
   page that lists digests is loaded.

And production is as it was: approval is a promise the timer keeps.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.crm.models import Task
from apps.tenancy.models import AuditEvent
from apps.work import digests as digest_service
from apps.work.models import Digest, DigestItem

from . import registry_config  # noqa: F401
from .test_digest_send_now import drafted, post
from .test_module3_digests import (  # noqa: F401  (fixtures)
    a_task, company, generate_weekly, goal, move, project, recipient, stake,
)

from .test_demo_mail_redirect import REDIRECT, SENDER, _addresses, demo  # noqa: F401


def past_its_window(digest):
    Digest.all_objects.filter(pk=digest.pk).update(
        send_window_at=timezone.now() - timedelta(minutes=5))
    digest.refresh_from_db()
    return digest


# ------------------------------------------------------ approving sends

@pytest.mark.django_db
def test_on_the_demo_approving_a_digest_sends_it_at_once_to_the_redirect(
        demo, seeded_tenant, ff, api, company, recipient, project, in_tenant_a):
    _, digest = drafted(seeded_tenant, ff, company, recipient, project)
    assert digest.send_window_at > timezone.now(), "well before its send time"

    response = post(api.as_(ff), digest, "approve")

    assert response.status_code == 200, response.content
    assert response.json()["state"] == "sent"
    digest.refresh_from_db()
    assert digest.state == Digest.State.SENT
    assert digest.approved_by_id == ff.user.pk and digest.approved_at is not None
    assert digest.outbox_message_id is not None
    # One message handed to Gmail, to the demo's one address and from its own,
    # not to the client; and it says who it was for.
    [mime] = demo.sent
    assert _addresses(mime) == {REDIRECT} and mime["From"] == SENDER
    text = mime.get_body(preferencelist=("plain",)).get_content()
    assert "First week." in text
    assert text.startswith("Demo: originally addressed to ") and "dana@northwind.invalid" \
        in text.splitlines()[0]
    # The same path as Send now: the approval is that person's, and it is on record.
    approved = AuditEvent.all_objects.get(verb="digest.approved", target_id=digest.pk)
    assert approved.actor_id == ff.user.pk and approved.payload["by"] == "send_now"
    assert AuditEvent.all_objects.filter(verb="digest.sent", target_id=digest.pk).count() == 1
    assert AuditEvent.all_objects.get(verb="digest.sent_by_hand",
                                      target_id=digest.pk).payload["was"] == "pending"
    # Sent is final: approving or sending again sends nothing more.
    assert post(api.as_(ff), digest, "approve").status_code == 409
    assert post(api.as_(ff), digest, "send-now").status_code == 409
    assert len(demo.sent) == 1
    # Its updates are claimed, exactly as for a timed send: never sent twice.
    assert DigestItem.objects.filter(digest=digest).exists()


@pytest.mark.django_db
def test_on_the_demo_approving_several_sends_each(
        demo, seeded_tenant, ff, api, company, recipient, project, in_tenant_a):
    _, digest = drafted(seeded_tenant, ff, company, recipient, project)
    response = api.as_(ff).post("/api/digests/approve-selected/",
                                json.dumps({"ids": [str(digest.pk)]}),
                                content_type="application/json")
    assert response.status_code == 200, response.content
    digest.refresh_from_db()
    assert digest.state == Digest.State.SENT and len(demo.sent) == 1
    assert _addresses(demo.sent[0]) == {REDIRECT}


@pytest.mark.django_db
def test_role_boundaries_on_the_demo_an_assistant_still_approves_and_sends_nothing(
        demo, seeded_tenant, ff, va, api, company, recipient, project, in_tenant_a):
    _, digest = drafted(seeded_tenant, ff, company, recipient, project)
    assert post(api.as_(va), digest, "approve").status_code == 403
    digest.refresh_from_db()
    assert digest.state == Digest.State.PENDING and demo.sent == []
    assert not AuditEvent.all_objects.filter(verb__in=("digest.approved", "digest.sent"),
                                             target_id=digest.pk).exists()


@pytest.mark.django_db
def test_tenant_isolation_on_the_demo_another_practice_approves_and_expires_nothing(
        demo, seeded_tenant, tenant_b, ff, api, company, recipient, project, in_tenant_a):
    from .conftest import _member

    _, digest = drafted(seeded_tenant, ff, company, recipient, project)
    other = _member(tenant_b, "FF")
    assert post(api.as_(other), digest, "approve").status_code == 404
    past_its_window(digest)
    assert api.as_(other).get("/api/digests/?state=all").json() == []
    assert api.as_(other).get("/api/dashboard/").status_code == 200
    digest.refresh_from_db()
    assert digest.state == Digest.State.PENDING and demo.sent == []


@pytest.mark.django_db
def test_the_seed_building_the_demos_history_approves_without_sending(
        demo, seeded_tenant, ff, company, recipient, project, in_tenant_a):
    """The seed runs on the demo with mail quiet and the clock moved: it
    approves a digest and sends it later, at the time a worker would have."""
    from config import environment

    _, digest = drafted(seeded_tenant, ff, company, recipient, project)
    with environment.quiet_mail():
        digest_service.approve(digest, actor=ff.user, role="FF")
        digest.refresh_from_db()
        assert digest.state == Digest.State.APPROVED
        digest_service.send(digest, actor=ff.user)
    digest.refresh_from_db()
    assert digest.state == Digest.State.SENT and demo.sent == []


@pytest.mark.django_db
def test_production_is_unchanged_approving_waits_for_the_timer(
        seeded_tenant, ff, api, company, recipient, project, dev_outbox, in_tenant_a,
        settings):
    assert settings.APP_ENVIRONMENT != "demo" and not settings.IS_DEMO
    _, digest = drafted(seeded_tenant, ff, company, recipient, project)

    assert post(api.as_(ff), digest, "approve").json()["state"] == "approved"
    digest.refresh_from_db()
    assert digest.state == Digest.State.APPROVED and dev_outbox == []
    assert "by" not in AuditEvent.all_objects.get(verb="digest.approved",
                                                  target_id=digest.pk).payload
    # It goes at its window, by the timer, and not before.
    digest_service.send_due(seeded_tenant, now=digest.send_window_at - timedelta(minutes=1))
    assert dev_outbox == []
    digest_service.send_due(seeded_tenant, now=digest.send_window_at + timedelta(minutes=1))
    assert len(dev_outbox) == 1 and dev_outbox[0].to == ["dana@northwind.invalid"]


# ------------------------------------------- past its window, on a page load

@pytest.mark.django_db
@pytest.mark.parametrize("page", ["/api/digests/", "/api/digests/?state=all",
                                  "/api/dashboard/"])
def test_on_the_demo_a_digest_past_its_window_is_expired_when_a_page_loads(
        page, demo, seeded_tenant, ff, api, company, recipient, project, in_tenant_a):
    task, digest = drafted(seeded_tenant, ff, company, recipient, project)
    held = DigestItem.objects.filter(digest=digest).count()
    assert held >= 1
    # Still ahead of its window: a page load leaves it waiting.
    assert api.as_(ff).get(page).status_code == 200
    digest.refresh_from_db()
    assert digest.state == Digest.State.PENDING

    past_its_window(digest)
    response = api.as_(ff).get(page)
    assert response.status_code == 200
    digest.refresh_from_db()
    assert digest.state == Digest.State.EXPIRED, "not left sitting pending"
    # Expired as any digest is: its updates are released, so they are owed again.
    assert not DigestItem.objects.filter(digest=digest).exists()
    event = AuditEvent.all_objects.get(verb="digest.expired", target_id=digest.pk)
    assert event.payload["by"] == "demo_page_load" and event.payload["was"] == "pending"
    assert demo.sent == [], "nothing is sent late"
    if page == "/api/digests/":
        assert response.json() == [], "and it is not in the list of what is waiting"
    # Loading again changes nothing more, and it cannot be approved or sent.
    api.as_(ff).get(page)
    assert AuditEvent.all_objects.filter(verb="digest.expired",
                                         target_id=digest.pk).count() == 1
    assert post(api.as_(ff), digest, "approve").status_code == 409
    assert post(api.as_(ff), digest, "send-now").status_code == 409
    assert Task.objects.filter(pk=task.pk).exists()


@pytest.mark.django_db
def test_off_the_demo_a_page_load_expires_nothing(
        seeded_tenant, ff, api, company, recipient, project, dev_outbox, in_tenant_a):
    _, digest = drafted(seeded_tenant, ff, company, recipient, project)
    past_its_window(digest)
    for page in ("/api/digests/", "/api/digests/?state=all", "/api/dashboard/"):
        assert api.as_(ff).get(page).status_code == 200
    digest.refresh_from_db()
    assert digest.state == Digest.State.PENDING, "the worker's tick marks it late, not a page"
    assert digest_service.demo_expire_passed(seeded_tenant) == []
    assert not AuditEvent.all_objects.filter(verb="digest.expired").exists()
