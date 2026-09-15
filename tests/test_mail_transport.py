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


# ------------------------------------------- the From is the row's (FR-1.15c)

@pytest.fixture
def own_connections(seeded_tenant, ff, cf):
    for member, address in ((ff, "bryan@getexecutivesnow.com"), (cf, "cf@getexecutivesnow.com")):
        GmailConnectionFactory(tenant=seeded_tenant, user=member.user, email_address=address,
                               send_as_address=ALIAS, send_as_verified_at=timezone.now())


def _gmail_send(tenant, *, actor, role, from_address):
    """A direct send through the real Gmail transport, faked at the HTTP edge.
    Returns the row, the From header Gmail was handed, and the connection used."""
    import base64
    from email import message_from_bytes

    sent = _response(payload={"id": "msg-1", "threadId": "gthread-1"})
    with tenant_context(tenant.pk), \
         mock.patch.object(transport, "access_token_for", return_value="tok") as token, \
         mock.patch("apps.crm.services.transport.requests.post", return_value=sent) as post:
        message = outbox.create_message(
            tenant=tenant, producer=outbox.P.MANUAL, role=role, actor=actor,
            to_address="partner@example.invalid", subject="Hello", body_text="Hi",
            from_address=from_address)
    mime = message_from_bytes(base64.urlsafe_b64decode(post.call_args.kwargs["json"]["raw"]))
    return message, mime["From"], token.call_args.args[0]


@pytest.mark.django_db
def test_mail_from_a_persons_own_address_goes_out_from_it(seeded_tenant, ff, own_connections,
                                                          settings):
    """This was the defect: the choice was recorded on the row, then the
    transport sent every message as the alias and overwrote the row to match."""
    settings.DEV_REAL_SEND_ALLOWLIST = ["partner@example.invalid"]
    message, sent_from, used = _gmail_send(seeded_tenant, actor=ff.user, role="FF",
                                           from_address="bryan@getexecutivesnow.com")
    assert sent_from == "bryan@getexecutivesnow.com"
    assert message.from_address == "bryan@getexecutivesnow.com", "The row says what went out."
    assert used.user_id == ff.user_id


@pytest.mark.django_db
def test_a_cfs_own_address_goes_through_the_cfs_own_connection(seeded_tenant, cf,
                                                               own_connections, settings):
    settings.DEV_REAL_SEND_ALLOWLIST = ["partner@example.invalid"]
    message, sent_from, used = _gmail_send(seeded_tenant, actor=cf.user, role="CF",
                                           from_address="cf@getexecutivesnow.com")
    assert sent_from == "cf@getexecutivesnow.com" and message.from_address == sent_from
    assert used.user_id == cf.user_id, "A CF's mail never rides on the FF's account."


@pytest.mark.django_db
@pytest.mark.parametrize("address", [
    ALIAS, "stranger@example.invalid", "va@getexecutivesnow.com", "b@tenant-b.invalid",
    "unverified@getexecutivesnow.com",
])
def test_anything_but_a_verified_ff_or_cf_address_goes_out_as_the_alias(
    address, seeded_tenant, tenant_b, ff, cf, va, own_connections, settings
):
    from .factories import UserFactory

    settings.DEV_REAL_SEND_ALLOWLIST = ["partner@example.invalid"]
    # A VA's connection (H7: a VA never sends), another tenant's, and an unverified one.
    GmailConnectionFactory(tenant=seeded_tenant, user=va.user, email_address="va@getexecutivesnow.com",
                           send_as_address=ALIAS, send_as_verified_at=timezone.now())
    GmailConnectionFactory(tenant=tenant_b, user=UserFactory(), email_address="b@tenant-b.invalid",
                           send_as_address="info@tenant-b.invalid",
                           send_as_verified_at=timezone.now())
    GmailConnection.all_objects.filter(user=cf.user).update(
        email_address="unverified@getexecutivesnow.com", send_as_verified_at=None)

    message, sent_from, used = _gmail_send(seeded_tenant, actor=ff.user, role="FF",
                                           from_address=address)
    assert sent_from == ALIAS and message.from_address == ALIAS
    assert used.user_id == ff.user_id
