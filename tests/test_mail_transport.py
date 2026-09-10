"""The Gmail transport (owner decision: no Postmark in Beta).

All app-originated mail goes through the FF's connected Gmail with From set to
the tenant's send-as alias. These tests stub Google's network and exercise
everything on this side of it.
"""

from __future__ import annotations

from unittest import mock

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.crm.models import GmailConnection
from apps.crm.services import outbox, transport
from apps.tenancy.context import tenant_context

from . import registry_config  # noqa: F401
from .factories import ContactEmailFactory, ContactFactory, GmailConnectionFactory

ALIAS = "info@getexecutivesnow.com"


def _response(ok=True, status=200, payload=None, text=""):
    stub = mock.Mock()
    stub.ok = ok
    stub.status_code = status
    stub.json.return_value = payload or {}
    stub.text = text
    return stub


def _send_as(*addresses, status="accepted"):
    return {"sendAs": [
        {"sendAsEmail": a, "verificationStatus": status} for a in addresses
    ]}


@pytest.fixture
def ff_gmail(seeded_tenant, ff):
    """A connected, verified FF Gmail account."""
    return GmailConnectionFactory(
        tenant=seeded_tenant, user=ff.user, email_address="bryan@getexecutivesnow.com",
        scopes=["gmail.send", "gmail.settings.basic"],
        send_as_address=ALIAS, send_as_verified_at=timezone.now(),
    )


# ------------------------------------------------------------ transport pick

def test_default_transport_is_gmail():
    assert transport.get_transport().name == "gmail"


@override_settings(APP_MAIL_TRANSPORT="postmark")
def test_postmark_transport_is_a_v1_option_and_says_so():
    with pytest.raises(transport.TransportUnavailable, match="V1 option"):
        transport.get_transport().send()


# --------------------------------------------------------- send-as verifying

@pytest.mark.django_db
def test_verify_send_as_accepts_a_listed_alias(seeded_tenant, ff, ff_gmail):
    ff_gmail.send_as_verified_at = None
    ff_gmail.save()
    with mock.patch.object(transport, "access_token_for", return_value="tok"), \
         mock.patch("apps.crm.services.transport.requests.get",
                    return_value=_response(payload=_send_as("bryan@x.invalid", ALIAS))):
        assert transport.verify_send_as(ff_gmail, ALIAS) is True

    ff_gmail.refresh_from_db()
    assert ff_gmail.send_as_address == ALIAS
    assert ff_gmail.send_as_verified_at is not None
    assert ff_gmail.send_as_error == ""


@pytest.mark.django_db
def test_unlisted_alias_fails_with_an_actionable_message(seeded_tenant, ff, ff_gmail):
    """The error has to tell the owner what to actually do in Gmail."""
    with mock.patch.object(transport, "access_token_for", return_value="tok"), \
         mock.patch("apps.crm.services.transport.requests.get",
                    return_value=_response(payload=_send_as("bryan@x.invalid"))):
        with pytest.raises(transport.SendAsNotVerified) as exc:
            transport.verify_send_as(ff_gmail, ALIAS)

    message = str(exc.value)
    assert ALIAS in message
    assert "Send mail as" in message
    assert "bryan@x.invalid" in message  # says what IS available

    ff_gmail.refresh_from_db()
    assert ff_gmail.send_as_verified_at is None
    assert ALIAS in ff_gmail.send_as_error


@pytest.mark.django_db
def test_pending_alias_is_refused(seeded_tenant, ff, ff_gmail):
    """Listed but unconfirmed is not good enough — Gmail would reject the send."""
    with mock.patch.object(transport, "access_token_for", return_value="tok"), \
         mock.patch("apps.crm.services.transport.requests.get",
                    return_value=_response(payload=_send_as(ALIAS, status="pending"))):
        with pytest.raises(transport.SendAsNotVerified, match="not confirmed|pending"):
            transport.verify_send_as(ff_gmail, ALIAS)


@pytest.mark.django_db
def test_missing_settings_scope_says_to_reconnect(seeded_tenant, ff, ff_gmail):
    with mock.patch.object(transport, "access_token_for", return_value="tok"), \
         mock.patch("apps.crm.services.transport.requests.get",
                    return_value=_response(ok=False, status=403)):
        with pytest.raises(transport.SendAsNotVerified, match="gmail.settings.basic"):
            transport.verify_send_as(ff_gmail, ALIAS)


# -------------------------------------------------------- choosing a sender

@pytest.mark.django_db
def test_no_connection_is_a_clear_error_not_a_silent_drop(seeded_tenant, ff):
    with tenant_context(seeded_tenant.pk):
        with pytest.raises(transport.TransportUnavailable, match="No Gmail account"):
            transport.sending_connection_for(seeded_tenant)


@pytest.mark.django_db
def test_unverified_connection_is_refused(seeded_tenant, ff, ff_gmail):
    ff_gmail.send_as_verified_at = None
    ff_gmail.send_as_error = "alias not verified"
    ff_gmail.save()
    with tenant_context(seeded_tenant.pk):
        with pytest.raises(transport.SendAsNotVerified):
            transport.sending_connection_for(seeded_tenant)


@pytest.mark.django_db
def test_a_vas_connection_is_never_used_to_send(seeded_tenant, ff, va, ff_gmail):
    """H7 — a VA cannot connect Gmail at all, and app mail must never pick one
    up even if a row somehow existed."""
    GmailConnectionFactory(
        tenant=seeded_tenant, user=va.user, email_address="va@getexecutivesnow.com",
        send_as_address=ALIAS, send_as_verified_at=timezone.now(),
    )
    with tenant_context(seeded_tenant.pk):
        chosen = transport.sending_connection_for(seeded_tenant)
    assert chosen.user_id == ff.user_id


# ------------------------------------------------------------------ sending

@pytest.mark.django_db
def test_gmail_send_sets_from_to_the_alias_and_records_thread_ids(
    seeded_tenant, ff, ff_gmail, settings
):
    """The client sees the tenant alias, not the fractional's personal address."""
    settings.DEV_REAL_SEND_ALLOWLIST = ["partner@example.invalid"]

    sent = _response(payload={"id": "msg-1", "threadId": "gthread-1"})
    with tenant_context(seeded_tenant.pk):
        contact = ContactFactory(tenant=seeded_tenant)
        ContactEmailFactory(tenant=seeded_tenant, contact=contact,
                            address="partner@example.invalid")
        with mock.patch.object(transport, "access_token_for", return_value="tok"), \
             mock.patch("apps.crm.services.transport.requests.post", return_value=sent) as post:
            message = outbox.create_message(
                tenant=seeded_tenant, producer=outbox.P.STRATEGY_PDF,
                to_contact=contact, to_address="partner@example.invalid",
                subject="Your strategy map", body_text="Attached.", actor=ff.user,
            )

    assert message.state == outbox.S.SENT
    assert message.sent_via == "gmail"
    assert message.from_address == ALIAS
    assert message.provider_message_id == "msg-1"
    assert message.dev_real_send is True

    raw = post.call_args.kwargs["json"]["raw"]
    import base64
    mime = base64.urlsafe_b64decode(raw).decode()
    assert f"From: {ALIAS}" in mime
    assert transport.THREAD_HEADER in mime
    assert message.thread.thread_token in mime

    message.thread.refresh_from_db()
    assert message.thread.gmail_thread_id == "gthread-1"


@pytest.mark.django_db
def test_reply_uses_the_stored_gmail_thread_id(seeded_tenant, ff, ff_gmail, settings):
    """A second message joins the existing Gmail conversation."""
    settings.DEV_REAL_SEND_ALLOWLIST = ["partner@example.invalid"]
    sent = _response(payload={"id": "msg-2", "threadId": "gthread-1"})

    with tenant_context(seeded_tenant.pk):
        contact = ContactFactory(tenant=seeded_tenant)
        ContactEmailFactory(tenant=seeded_tenant, contact=contact,
                            address="partner@example.invalid")
        thread = outbox.thread_for(seeded_tenant, contact=contact)
        thread.gmail_thread_id = "gthread-1"
        thread.save()

        with mock.patch.object(transport, "access_token_for", return_value="tok"), \
             mock.patch("apps.crm.services.transport.requests.post", return_value=sent) as post:
            outbox.create_message(
                tenant=seeded_tenant, producer=outbox.P.STRATEGY_PDF, to_contact=contact,
                to_address="partner@example.invalid", subject="Follow-up",
                body_text="More.", actor=ff.user, thread=thread,
            )

    assert post.call_args.kwargs["json"]["threadId"] == "gthread-1"


@pytest.mark.django_db
def test_dev_outbox_guard_is_unchanged_by_the_transport_switch(
    seeded_tenant, ff, ff_gmail, dev_outbox, settings
):
    """FR-0.7 / H6 — the guard governs WHO may receive real mail, not which
    service carries it. A non-allow-listed address must never reach Gmail."""
    settings.DEV_REAL_SEND_ALLOWLIST = ["bryan@getexecutivesnow.com"]

    with tenant_context(seeded_tenant.pk):
        contact = ContactFactory(tenant=seeded_tenant)
        ContactEmailFactory(tenant=seeded_tenant, contact=contact,
                            address="realclient@acme.invalid")
        with mock.patch("apps.crm.services.transport.requests.post") as post:
            message = outbox.create_message(
                tenant=seeded_tenant, producer=outbox.P.STRATEGY_PDF, to_contact=contact,
                to_address="realclient@acme.invalid", subject="Map",
                body_text="x", actor=ff.user,
            )
        post.assert_not_called()

    assert message.sent_via == "dev"
    assert message.dev_real_send is False
    assert len(dev_outbox) == 1
    assert dev_outbox[0].to == ["realclient@acme.invalid"]


@pytest.mark.django_db
def test_a_revoked_token_names_the_consequence(seeded_tenant, ff, ff_gmail, settings):
    """Magic links now ride on this credential (accepted trade-off), so the
    failure has to say so rather than surfacing as a generic error."""
    settings.DEV_REAL_SEND_ALLOWLIST = ["partner@example.invalid"]

    with tenant_context(seeded_tenant.pk):
        contact = ContactFactory(tenant=seeded_tenant)
        ContactEmailFactory(tenant=seeded_tenant, contact=contact,
                            address="partner@example.invalid")
        with mock.patch("apps.crm.services.transport.requests.post",
                        return_value=_response(ok=False, status=400)), \
             mock.patch("apps.crm.services.secrets.read_secret", return_value="refresh"):
            with pytest.raises(transport.TransportUnavailable) as exc:
                outbox.create_message(
                    tenant=seeded_tenant, producer=outbox.P.STRATEGY_PDF,
                    to_contact=contact, to_address="partner@example.invalid",
                    subject="Map", body_text="x", actor=ff.user,
                )
    assert "magic links" in str(exc.value).lower()


# ---------------------------------------------------------------- threading

def test_thread_token_survives_a_round_trip_through_the_message_id():
    class FakeTenant: from_address = "info@getexecutivesnow.com"
    class FakeThread: thread_token = "abc123XYZ_token"

    message_id = transport.message_id_for(FakeTenant(), FakeThread())
    assert transport.token_from_message_id(message_id) == "abc123XYZ_token"
    assert message_id.startswith("<") and message_id.endswith(">")
    assert "getexecutivesnow.com" in message_id


def test_unknown_message_id_yields_no_token():
    assert transport.token_from_message_id("") == ""
    assert transport.token_from_message_id("<random@elsewhere.com>") == ""
