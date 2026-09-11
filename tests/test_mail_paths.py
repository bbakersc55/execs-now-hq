"""Every email leaves through the Outbox (Phase 2 manual check 3 finding).

The PIN reset and magic links were sent straight through Django's mail
backend: never logged in the Outbox, never seen by the dev allow-list, and
never carried by the practice's Gmail. On the laptop that meant an
allow-listed reset landed in Mailpit instead of the owner's inbox.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from apps.crm.models import OutboxMessage
from apps.crm.services import transport

from . import registry_config  # noqa: F401
from .factories import MembershipFactory, UserFactory

APPS = Path(__file__).resolve().parent.parent / "apps"
# The dev outbox transport is the one sanctioned user of Django's mail backend:
# it is the branch INSIDE outbox._deliver for recipients not on the allow-list.
SANCTIONED = {APPS / "crm" / "services" / "transport.py"}


def test_no_code_path_sends_mail_except_through_the_outbox():
    offenders = []
    for path in APPS.rglob("*.py"):
        if "migrations" in path.parts or path in SANCTIONED:
            continue
        text = path.read_text()
        if re.search(r"django\.core\.mail|send_mail\(|EmailMultiAlternatives", text):
            offenders.append(str(path.relative_to(APPS.parent)))
    assert offenders == [], f"Direct sends outside the Outbox: {offenders}"


class RecordingTransport:
    """Stands in for the Gmail transport; records exactly what it was handed."""

    name = "gmail"

    def __init__(self):
        self.sent = []

    def send(self, **kwargs):
        self.sent.append(kwargs)
        return {"provider": "gmail", "provider_message_id": "g1", "gmail_message_id": "g1",
                "gmail_thread_id": "t1", "message_id_header": "<x@y>",
                "from_address": kwargs["tenant"].from_address}


@pytest.fixture
def gmail(monkeypatch):
    fake = RecordingTransport()
    monkeypatch.setattr(transport, "get_transport", lambda name=None: fake)
    return fake


def _locked_note(api, ff):
    client = api.as_(ff)
    note = client.post("/api/notes/", json.dumps({"title": "HR matter", "body": "private"}),
                       content_type="application/json").json()
    client.post(f"/api/notes/{note['id']}/pin/", json.dumps({"pin": "4821"}),
                content_type="application/json")
    return note


@pytest.mark.django_db
def test_a_pin_reset_is_a_sent_outbox_row_addressed_to_the_ff(seeded_tenant, api, settings,
                                                              gmail, dev_outbox):
    """The owner's scenario: an allow-listed FF requests a reset. It must go
    through the configured transport (Gmail), logged in the Outbox as sent."""
    ff = MembershipFactory(tenant=seeded_tenant, role="FF",
                           user=UserFactory(email="owner@example.invalid"))
    settings.DEV_REAL_SEND_ALLOWLIST = ["owner@example.invalid"]
    note = _locked_note(api, ff)

    response = api.as_(ff).post(f"/api/notes/{note['id']}/pin-reset/")
    assert response.status_code == 200

    row = OutboxMessage.all_objects.get(producer="note_pin_reset")
    assert row.state == "sent" and row.to_address == "owner@example.invalid"
    assert row.sent_via == "gmail" and row.dev_real_send is True
    assert dev_outbox == [], "The reset bypassed the configured transport."

    assert len(gmail.sent) == 1
    delivered = gmail.sent[0]["body_text"]
    assert "/notes/pin-reset/" in delivered and "4821" not in delivered
    # The row every tenant user can read holds no working link.
    assert "/notes/pin-reset/" not in row.body_text
    assert "not stored" in row.body_text


@pytest.mark.django_db
def test_a_non_allowlisted_reset_goes_to_the_dev_outbox_and_is_still_logged(
    seeded_tenant, ff, api, gmail, dev_outbox
):
    note = _locked_note(api, ff)
    api.as_(ff).post(f"/api/notes/{note['id']}/pin-reset/")
    row = OutboxMessage.all_objects.get(producer="note_pin_reset")
    assert row.state == "sent" and row.sent_via == "dev"
    assert gmail.sent == [] and len(dev_outbox) == 1
    assert "/notes/pin-reset/" in dev_outbox[0].body


@pytest.mark.django_db
def test_a_reset_that_cannot_be_sent_says_so_and_leaves_no_token(seeded_tenant, api, settings,
                                                                monkeypatch):
    from apps.accounts.models import MagicLinkToken

    class Down:
        name = "gmail"

        def send(self, **kwargs):
            raise transport.TransportUnavailable("No Gmail account is connected.")

    monkeypatch.setattr(transport, "get_transport", lambda name=None: Down())
    ff = MembershipFactory(tenant=seeded_tenant, role="FF",
                           user=UserFactory(email="owner@example.invalid"))
    settings.DEV_REAL_SEND_ALLOWLIST = ["owner@example.invalid"]
    note = _locked_note(api, ff)
    response = api.as_(ff).post(f"/api/notes/{note['id']}/pin-reset/")
    assert response.status_code == 503 and "No Gmail account" in response.json()["detail"]
    assert not MagicLinkToken.all_objects.filter(purpose="pin_reset").exists()
    assert not OutboxMessage.all_objects.filter(producer="note_pin_reset").exists()


@pytest.mark.django_db
def test_a_magic_link_is_a_sent_outbox_row_with_no_stored_link(seeded_tenant, fcc, settings,
                                                               gmail, dev_outbox):
    from django.test import Client

    settings.DEV_REAL_SEND_ALLOWLIST = [fcc.user.email]
    Client().post("/auth/magic/request", {"email": fcc.user.email})
    row = OutboxMessage.all_objects.get(producer="magic_link")
    assert row.state == "sent" and row.to_address == fcc.user.email and row.sent_via == "gmail"
    assert "/auth/magic/" in gmail.sent[0]["body_text"]
    assert "/auth/magic/" not in row.body_text, (
        "A stored magic link would let any tenant user reading the Outbox sign in as the client."
    )


@pytest.mark.django_db
def test_a_magic_link_send_failure_keeps_the_response_opaque(seeded_tenant, fcc, monkeypatch,
                                                            settings):
    from django.test import Client

    from apps.tenancy.models import AuditEvent

    class Down:
        name = "gmail"

        def send(self, **kwargs):
            raise transport.TransportUnavailable("Gmail refused the stored credential.")

    monkeypatch.setattr(transport, "get_transport", lambda name=None: Down())
    settings.DEV_REAL_SEND_ALLOWLIST = [fcc.user.email]
    known = Client().post("/auth/magic/request", {"email": fcc.user.email})
    unknown = Client().post("/auth/magic/request", {"email": "nobody@example.invalid"})
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()
    assert AuditEvent.all_objects.filter(verb="email.failed").count() == 1
