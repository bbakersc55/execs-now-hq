"""The demo's mail (owner, 2026-10-08): it sends only through its redirect.

Every message has its recipient replaced by `DEMO_MAIL_REDIRECT` before it is
built, carries a banner naming who it was for, and leaves from
`DEMO_MAIL_FROM` through a send-only Gmail connection of the demo's own. No
message can carry a real recipient."""

from __future__ import annotations

import base64
import email
import os
import subprocess
import sys
from email import policy
from pathlib import Path

import pytest
from django.utils import timezone

from apps.crm.models import OutboxMessage
from apps.crm.services import outbox, transport
from config import environment

from . import registry_config  # noqa: F401
from .factories import ContactEmailFactory, ContactFactory, GmailConnectionFactory

ROOT = Path(__file__).resolve().parent.parent
REDIRECT = "redirect@demo-inbox.invalid"
SENDER = "demo@getexecutivesnow.com"
P = OutboxMessage.Producer


@pytest.fixture
def demo(settings, seeded_tenant, in_tenant_a, ff, monkeypatch):
    """The demo, with a redirect set and its own verified send-only connection.
    Every message handed to Gmail is caught here, parsed, and never sent."""
    settings.APP_ENVIRONMENT, settings.IS_DEMO, settings.IS_LOCAL = "demo", True, False
    settings.DEMO_MAIL_REDIRECT, settings.DEMO_MAIL_FROM = REDIRECT, SENDER
    settings.EMAIL_BACKEND = "django.core.mail.backends.dummy.EmailBackend"
    seeded_tenant.from_address = SENDER
    seeded_tenant.save(update_fields=["from_address"])
    connection = GmailConnectionFactory(
        tenant=seeded_tenant, user=ff.user, email_address="owner@getexecutivesnow.com",
        send_as_address=SENDER, send_as_verified_at=timezone.now())
    sent = []

    class Accepted:
        ok, status_code, text = True, 200, ""

        def json(self):
            return {"id": f"m{len(sent)}", "threadId": "t1"}

    def post(url, **kwargs):
        raw = base64.urlsafe_b64decode(kwargs["json"]["raw"])
        sent.append(email.message_from_bytes(raw, policy=policy.default))
        return Accepted()

    monkeypatch.setattr(transport, "access_token_for", lambda connection: "token")
    monkeypatch.setattr(transport.requests, "post", post)
    return type("Demo", (), {"tenant": seeded_tenant, "ff": ff, "sent": sent,
                             "connection": connection})


def _someone(tenant, address="dana.reyes@northwind.example"):
    contact = ContactFactory(tenant=tenant, first_name="Dana", last_name="Reyes")
    ContactEmailFactory(tenant=tenant, contact=contact, address=address, is_primary=True)
    return contact


def _addresses(mime) -> set[str]:
    """Every address in any recipient header of a built message."""
    found = set()
    for name in ("To", "Cc", "Bcc", "Resent-To", "Resent-Cc", "Resent-Bcc", "Delivered-To"):
        for header in mime.get_all(name, []):
            found.update(a.addr_spec.lower() for a in header.addresses)
    return found


def _send(demo, producer=P.MANUAL, contact=None, **fields):
    contact = contact or _someone(demo.tenant)
    return outbox.create_message(
        tenant=demo.tenant, producer=producer, to_contact=contact,
        to_address=contact.primary_email, subject="Your update",
        body_text="Hello Dana,\n\nHere is the week.", force_direct=True,
        actor=demo.ff.user, role="FF", **fields)


# ------------------------------------------------------------ the redirect

@pytest.mark.django_db
def test_a_demo_message_goes_to_the_redirect_and_says_who_it_was_for(demo):
    message = _send(demo, body_html="<html><body><p>Hello Dana,</p></body></html>")

    [mime] = demo.sent
    assert _addresses(mime) == {REDIRECT}
    assert mime["From"] == SENDER
    banner = "Demo: originally addressed to Dana Reyes <dana.reyes@northwind.example>"
    text = mime.get_body(preferencelist=("plain",)).get_content()
    html = mime.get_body(preferencelist=("html",)).get_content()
    assert text.startswith(banner), "the banner is the first thing in the text part"
    assert "Demo: originally addressed to Dana Reyes &lt;dana.reyes@northwind.example&gt;" \
        in html
    assert html.index("Demo: originally") < html.index("Hello Dana"), "and tops the HTML"

    # The Outbox still says who it was for: it is the log of the demo's story.
    message.refresh_from_db()
    assert message.state == OutboxMessage.State.SENT
    assert message.to_address == "dana.reyes@northwind.example"
    assert message.from_address == SENDER and message.sent_via == "gmail"


@pytest.mark.django_db
@pytest.mark.parametrize("producer", [p for p in P.values])
def test_no_demo_message_of_any_kind_carries_a_real_recipient(demo, producer):
    """Every producer the app has, to a real-looking address at a real domain."""
    contact = _someone(demo.tenant, "a.real.person@gmail.com")
    _send(demo, producer=producer, contact=contact)

    for mime in demo.sent:
        assert _addresses(mime) == {REDIRECT}
        assert "a.real.person@gmail.com" not in (mime["To"] or "")
    assert len(demo.sent) <= 1


@pytest.mark.django_db
def test_an_approved_draft_takes_the_same_road(demo):
    contact = _someone(demo.tenant)
    draft = outbox.create_message(
        tenant=demo.tenant, producer=P.REFERRAL_TOUCH, to_contact=contact,
        to_address=contact.primary_email, subject="Checking in", body_text="Hi Dana",
        actor=demo.ff.user, role="FF", from_address="owner@getexecutivesnow.com")
    assert draft.state == OutboxMessage.State.PENDING_APPROVAL and demo.sent == []

    outbox.approve(draft, actor=demo.ff.user, role="FF")

    [mime] = demo.sent
    assert _addresses(mime) == {REDIRECT}
    assert mime["From"] == SENDER, "never the owner's own address, whatever the draft said"


@pytest.mark.django_db
def test_the_transport_itself_refuses_any_other_recipient(demo):
    """The second lock: below the Outbox, whatever called it."""
    thread = outbox.thread_for(demo.tenant, subject="x")
    for to in ("dana.reyes@northwind.example", "", f"{REDIRECT}, other@gmail.com"):
        with pytest.raises(transport.TransportUnavailable, match="only to its redirect"):
            transport.GmailTransport().send(tenant=demo.tenant, to_address=to, subject="x",
                                            body_text="x", thread=thread)
    assert demo.sent == []


@pytest.mark.django_db
def test_the_transport_refuses_a_connection_that_is_not_the_demos_address(demo):
    demo.connection.send_as_address = "info@getexecutivesnow.com"
    demo.connection.save(update_fields=["send_as_address"])
    thread = outbox.thread_for(demo.tenant, subject="x")
    with pytest.raises(transport.TransportUnavailable, match="only from"):
        transport.GmailTransport().send(tenant=demo.tenant, to_address=REDIRECT,
                                        subject="x", body_text="x", thread=thread)
    assert demo.sent == []


# ------------------------------------------------- when it sends nothing

@pytest.mark.django_db
def test_with_no_redirect_set_the_demo_sends_nothing(demo, settings):
    settings.DEMO_MAIL_REDIRECT = ""
    message = _send(demo)
    assert demo.sent == [] and message.sent_via == "dev"


@pytest.mark.django_db
def test_with_no_connection_of_its_own_the_demo_sends_nothing(demo):
    demo.connection.delete()
    message = _send(demo)
    assert demo.sent == [] and message.sent_via == "dev"


@pytest.mark.django_db
def test_an_unverified_or_foreign_connection_sends_nothing(demo):
    demo.connection.send_as_address = "info@getexecutivesnow.com"
    demo.connection.save(update_fields=["send_as_address"])
    assert _send(demo).sent_via == "dev" and demo.sent == []


@pytest.mark.django_db
def test_nothing_leaves_while_the_seed_is_running(demo):
    with environment.quiet_mail():
        message = _send(demo)
    assert demo.sent == [] and message.sent_via == "dev"
    _send(demo)
    assert len(demo.sent) == 1, "and it is quiet only for as long as the seed runs"


# -------------------------------------------------- connecting, on the demo

@pytest.mark.django_db
def test_the_demo_connects_gmail_for_its_one_address_send_only(demo, api):
    client = api.as_(demo.ff)
    started = client.post("/api/gmail-connection/start/")
    assert started.status_code == 200
    url = started.json()["authorization_url"]
    assert "gmail.send" in url
    assert "gmail.readonly" not in url and "drive" not in url
    assert "include_granted_scopes" not in url, "nothing granted before rides along"

    refused = client.post("/api/gmail-connection/start/", {"inbound": True},
                          content_type="application/json")
    assert refused.status_code == 409 and "never reads a mailbox" in refused.json()["detail"]
    assert client.post("/api/drive-watch/consent/").status_code == 409


@pytest.mark.django_db
def test_the_demo_connects_for_no_other_address_and_cannot_change_its_own(demo, api):
    client = api.as_(demo.ff)
    changed = client.post("/api/gmail-connection/practice-address/",
                          {"address": "info@getexecutivesnow.com"},
                          content_type="application/json")
    assert changed.status_code == 409
    demo.tenant.refresh_from_db()
    assert demo.tenant.from_address == SENDER

    demo.tenant.from_address = "info@getexecutivesnow.com"
    demo.tenant.save(update_fields=["from_address"])
    refused = client.post("/api/gmail-connection/start/")
    assert refused.status_code == 409 and SENDER in refused.json()["detail"]


@pytest.mark.django_db
def test_only_the_demos_practice_owner_connects(demo, api, cf):
    assert api.as_(cf).post("/api/gmail-connection/start/").status_code == 409


@pytest.mark.django_db
def test_a_grant_that_could_read_is_not_kept(demo, api, monkeypatch):
    from apps.crm.models import GmailConnection
    from apps.crm.services import gmail_oauth

    demo.connection.delete()
    client = api.as_(demo.ff)
    client.post("/api/gmail-connection/start/")
    state = client.session[gmail_oauth.STATE_SESSION_KEY]
    monkeypatch.setattr(gmail_oauth, "exchange_code", lambda code, tenant=None: {
        "access_token": "a", "refresh_token": "r",
        "scope": " ".join(gmail_oauth.TIER1_SCOPES + gmail_oauth.TIER2_SCOPES)})
    monkeypatch.setattr(gmail_oauth, "account_email",
                        lambda token: "owner@getexecutivesnow.com")

    response = client.get("/accounts/gmail/callback", {"state": state, "code": "c"})

    assert response.status_code == 302 and "gmail_error" in response["Location"]
    assert not GmailConnection.all_objects.filter(tenant=demo.tenant).exists()


# ============================================== settings, booted for real

BOOT = {
    "PUBLIC_BASE_URL": "https://demo.getexecutivesnow.com", "DJANGO_SECRET_KEY": "k",
    "DJANGO_DEBUG": "False", "DJANGO_ALLOWED_HOSTS": "demo.getexecutivesnow.com",
    "DEV_REAL_SEND_ALLOWLIST": "", "ANTHROPIC_API_KEY": "", "APP_ENVIRONMENT": "demo",
    "GCS_BUCKET_MEDIA": "execs-now-hq-demo-media", "STORAGE_BACKEND": "gcs",
    "DEMO_MAIL_REDIRECT": "Someone@Example.invalid",
}
PROBE = ("import django; django.setup(); from django.conf import settings as s; "
         "print(s.DEMO_MAIL_REDIRECT, s.DEMO_MAIL_FROM)")


def _boot(**overrides):
    env = {**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings", **BOOT, **overrides}
    return subprocess.run([sys.executable, "-c", PROBE], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=60)


def test_the_demo_boots_with_its_redirect():
    done = _boot()
    assert done.returncode == 0, done.stderr[-1500:]
    assert done.stdout.split()[-2:] == ["someone@example.invalid", SENDER]


def test_a_redirect_anywhere_but_the_demo_is_refused():
    done = _boot(APP_ENVIRONMENT="production",
                 PUBLIC_BASE_URL="https://app.getexecutivesnow.com",
                 DJANGO_ALLOWED_HOSTS="app.getexecutivesnow.com",
                 GCS_BUCKET_MEDIA="execs-now-hq-media")
    assert done.returncode != 0 and "demo-only mechanism" in done.stderr


def test_a_redirect_that_is_not_one_address_is_refused():
    done = _boot(DEMO_MAIL_REDIRECT="a@example.invalid,b@example.invalid")
    assert done.returncode != 0 and "one exact address" in done.stderr
