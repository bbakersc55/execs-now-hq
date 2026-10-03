"""The sending queue (owner, 2026-09-28): every pending item of every category
in one list, each previewed exactly as it lands, approved or skipped through
its own path — the rules about what waits are unchanged."""

from __future__ import annotations

import pytest

from apps.crm.models import EmailSuppression, OutboxMessage
from apps.crm.services import outbox
from apps.work.models import Digest

from . import registry_config  # noqa: F401
from .factories import (
    ClientAssignmentFactory, ClientCompanyFactory, ContactEmailFactory, ContactFactory,
    DigestFactory,
)

P = OutboxMessage.Producer
S = OutboxMessage.State


def person(tenant, first, company=None):
    contact = ContactFactory(tenant=tenant, first_name=first, last_name="Reyes",
                             company=company)
    ContactEmailFactory(tenant=tenant, contact=contact, address=f"{first.lower()}@x.invalid")
    return contact


def draft(tenant, contact, producer=P.REFERRAL_TOUCH, **kw):
    return outbox.create_message(tenant=tenant, producer=producer, to_contact=contact,
                                 to_address=contact.primary_email, subject="Checking in",
                                 body_text=f"Hi {contact.first_name}", **kw)


@pytest.fixture
def queue(seeded_tenant, ff, in_tenant_a):
    dana, priya = person(seeded_tenant, "Dana"), person(seeded_tenant, "Priya")
    touch = draft(seeded_tenant, dana)
    questions = draft(seeded_tenant, priya, P.PRECALL_QUESTIONS, role="VA")
    digest = DigestFactory(tenant=seeded_tenant, contact=priya, state="pending",
                           body_text="Dispatch is on schedule.")
    return {"touch": touch, "questions": questions, "digest": digest,
            "dana": dana, "priya": priya}


@pytest.mark.django_db
def test_one_list_of_every_category(seeded_tenant, ff, api, queue):
    rows = api.as_(ff).get("/api/sending-queue/").json()
    assert {(r["kind"], r["category"]) for r in rows} == {
        ("outbox", "marketing"), ("outbox", "transactional"), ("digest", "updates")}

    only = api.as_(ff).get("/api/sending-queue/?category=updates").json()
    assert [r["key"] for r in only] == [f"digest:{queue['digest'].pk}"]
    who = api.as_(ff).get("/api/sending-queue/?recipient=dana").json()
    assert [r["key"] for r in who] == [f"outbox:{queue['touch'].pk}"]


@pytest.mark.django_db
def test_each_preview_is_as_it_lands(seeded_tenant, ff, api, queue):
    client = api.as_(ff)
    touch = client.get(f"/api/sending-queue/preview/?key=outbox:{queue['touch'].pk}").json()
    assert "Unsubscribe from marketing emails" in touch["html"]
    assert touch["to"] == "dana@x.invalid"

    digest = client.get(f"/api/sending-queue/preview/?key=digest:{queue['digest'].pk}").json()
    assert "Unsubscribe from progress updates" in digest["html"]
    assert "Dispatch is on schedule." in digest["html"]

    questions = client.get(
        f"/api/sending-queue/preview/?key=outbox:{queue['questions'].pk}").json()
    assert "nsubscribe" not in questions["html"] and "nsubscribe" not in questions["text"]


@pytest.mark.django_db
def test_approving_selected_sends_drafts_and_approves_digests_for_their_window(
    seeded_tenant, ff, api, queue, dev_outbox
):
    keys = [f"outbox:{queue['touch'].pk}", f"digest:{queue['digest'].pk}"]
    body = api.as_(ff).post("/api/sending-queue/approve/", {"keys": keys},
                            content_type="application/json").json()

    assert body["done_count"] == 2 and body["failed"] == []
    queue["touch"].refresh_from_db(); queue["digest"].refresh_from_db()
    assert queue["touch"].state == S.SENT
    # Nothing changes about what waits: an approved digest goes at its window.
    assert queue["digest"].state == Digest.State.APPROVED
    assert len(dev_outbox) == 1


@pytest.mark.django_db
def test_a_va_prepares_but_never_approves(seeded_tenant, va, api, queue, dev_outbox):
    keys = [f"outbox:{queue['touch'].pk}", f"digest:{queue['digest'].pk}"]
    body = api.as_(va).post("/api/sending-queue/approve/", {"keys": keys},
                            content_type="application/json").json()
    assert body["done_count"] == 0 and len(body["failed"]) == 2
    assert dev_outbox == []
    # Skipping a draft is safe for a VA (it sends nothing); a digest is not.
    skipped = api.as_(va).post("/api/sending-queue/skip/", {"keys": keys},
                               content_type="application/json").json()
    assert skipped["done"] == [f"outbox:{queue['touch'].pk}"]
    assert "can't skip" in skipped["failed"][0]["detail"]


@pytest.mark.django_db
def test_an_unsubscribed_recipient_is_refused_with_the_reason(seeded_tenant, ff, api,
                                                              queue, dev_outbox):
    EmailSuppression.objects.create(tenant=seeded_tenant, contact=queue["dana"],
                                    category="marketing")
    body = api.as_(ff).post("/api/sending-queue/approve/",
                            {"keys": [f"outbox:{queue['touch'].pk}"]},
                            content_type="application/json").json()
    assert "unsubscribed from marketing emails" in body["failed"][0]["detail"]
    assert dev_outbox == []


@pytest.mark.django_db
def test_a_cf_sees_only_their_clients(seeded_tenant, ff, cf, api, in_tenant_a):
    theirs = ClientCompanyFactory(tenant=seeded_tenant)
    other = ClientCompanyFactory(tenant=seeded_tenant)
    ClientAssignmentFactory(tenant=seeded_tenant, user=cf.user, company=theirs)
    mine = draft(seeded_tenant, person(seeded_tenant, "Mine", theirs))
    draft(seeded_tenant, person(seeded_tenant, "Nope", other))
    DigestFactory(tenant=seeded_tenant, contact=person(seeded_tenant, "Digest", other),
                  state="pending")
    rows = api.as_(cf).get("/api/sending-queue/").json()
    assert [r["key"] for r in rows] == [f"outbox:{mine.pk}"]


@pytest.mark.django_db
def test_a_client_has_no_queue(seeded_tenant, fcc, api):
    assert api.as_(fcc).get("/api/sending-queue/").status_code == 403
