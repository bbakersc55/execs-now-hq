"""Microsoft 365 as a practice's mail transport (docs/m365_transport.md).

The two mandatory families (CLAUDE.md): role boundaries (the practice owner
switches; the owner and associates connect their own; an assistant and client
users reach nothing) and tenant isolation (a connection, a conversation or a
switch in one practice never reaches another). Then the transport against
Graph's documented shapes (`tests/fixtures/graph/`), and that a Gmail
practice's path is exactly what it was.

Every test stubs Microsoft's network. Nothing here reaches the internet, and
nothing here was checked against a real Microsoft 365 tenant: what only a
real one can confirm is listed in docs/m365_transport.md §10.
"""

from __future__ import annotations

import base64
import json
from email import message_from_bytes, policy
from pathlib import Path
from unittest import mock

import pytest
from django.utils import timezone

from apps.crm.models import (
    EmailMessage, EmailSuppression, EmailThread, GmailConnection, MicrosoftConnection,
    OutboxMessage, UnmatchedInbound,
)
from apps.crm.services import (
    graph, inbound, inbound_poll, microsoft_oauth, outbox, sender, transport,
)
from apps.tenancy.context import tenant_context
from apps.tenancy.models import AuditEvent, Role, TenantSecret

from . import registry_config  # noqa: F401
from .factories import (
    ContactEmailFactory, ContactFactory, GmailConnectionFactory, MembershipFactory,
    MicrosoftConnectionFactory, OutboxMessageFactory, TenantFactory,
)

FIXTURES = Path(__file__).parent / "fixtures" / "graph"
ALIAS = "info@contoso.example"
OWN = "bryan@contoso.example"
STATUS = "/api/microsoft-connection/"
START = "/api/microsoft-connection/start/"
VERIFY = "/api/microsoft-connection/verify/"
DISCONNECT = "/api/microsoft-connection/disconnect/"
ADDRESS = "/api/microsoft-connection/practice-address/"
PROVIDER = "/api/mail-provider/"
SWITCH = "/api/mail-provider/switch/"
CALLBACK = "/accounts/microsoft/callback"
S = OutboxMessage.State
P = OutboxMessage.Producer


DIRECTORY = "9188040d-6c67-4c5b-b112-36a304b66dad"


def id_token():
    """An ID token in the identity platform's shape, made here rather than
    kept in a fixture: a token-shaped string in the repository is what
    GitHub's push protection stops, made-up or not."""
    def part(data):
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    claims = {"aud": "client-id", "tid": DIRECTORY, "ver": "2.0",
              "iss": f"https://login.microsoftonline.com/{DIRECTORY}/v2.0",
              "preferred_username": OWN, "email": OWN, "name": "Bryan Baker"}
    return ".".join([part({"alg": "none"}), part(claims), "unsigned"])


def fixture(name):
    path = FIXTURES / name
    if name.endswith(".eml"):
        return path.read_bytes()
    data = json.loads(path.read_text())
    if "id_token" in data:
        data["id_token"] = id_token()
    return data


class Reply:
    def __init__(self, status=200, payload=None, content=b"", headers=None):
        self.status_code = status
        self.ok = status < 400
        self._payload = payload
        self.content = content
        self.text = json.dumps(payload) if payload is not None else content.decode("latin-1")
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON")
        return self._payload


class FakeMicrosoft:
    """Microsoft's two hosts, answering from the fixtures. Each route is
    (method, a piece of the URL, a Reply or a list of them, served in turn);
    the last match wins, so a test overrides a default by adding one."""

    def __init__(self):
        self.calls = []
        self.routes = []
        self.on("POST", "/oauth2/v2.0/token", Reply(payload=fixture("refreshed.json")))
        self.on("GET", "/v1.0/me?", Reply(payload=fixture("me.json")))
        self.on("GET", "/v1.0/me", Reply(payload=fixture("me.json")))
        self.on("POST", "/me/messages", Reply(201, fixture("draft_created.json")))
        self.on("POST", "/send", Reply(202))
        self.on("GET", "/me/messages/AAkAL", Reply(payload=fixture("sent_item.json")))
        self.on("DELETE", "/me/messages/", Reply(204))

    def on(self, method, piece, reply):
        self.routes.append((method, piece, reply if isinstance(reply, list) else [reply]))

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method.upper(), "url": url, **kwargs})
        for want, piece, replies in reversed(self.routes):
            if want == method.upper() and piece in url:
                return replies.pop(0) if len(replies) > 1 else replies[0]
        raise AssertionError(f"No fake for {method} {url}")

    def of(self, method, piece):
        return [c for c in self.calls if c["method"] == method and piece in c["url"]]


@pytest.fixture
def ms(settings):
    settings.MICROSOFT_CLIENT_ID = "client-id"
    settings.MICROSOFT_CLIENT_SECRET = "client-secret"
    fake = FakeMicrosoft()
    oauth = mock.Mock()
    oauth.post.side_effect = lambda url, **kw: fake.request("POST", url, **kw)
    oauth.get.side_effect = lambda url, **kw: fake.request("GET", url, **kw)
    with mock.patch("apps.crm.services.graph.requests.request", side_effect=fake.request), \
            mock.patch("apps.crm.services.microsoft_oauth.requests", oauth), \
            mock.patch("apps.crm.services.graph.time.sleep"):
        yield fake


@pytest.fixture
def ms_practice(seeded_tenant):
    seeded_tenant.mail_provider = "microsoft"
    seeded_tenant.from_address = ALIAS
    seeded_tenant.save()
    return seeded_tenant


def _connect(tenant, membership, *, address=OWN, verified=True, read=False):
    from apps.crm.services.secrets import write_secret
    from apps.tenancy.models import SecretKind

    secret = write_secret(tenant=tenant, kind=SecretKind.MICROSOFT_REFRESH,
                          value="0.AAAA-refresh-1", user=membership.user)
    return MicrosoftConnectionFactory(
        tenant=tenant, user=membership.user, email_address=address, secret=secret,
        scopes=["Mail.Send", "Mail.ReadBasic", "User.Read"] + (["Mail.Read"] if read else []),
        send_as_address=tenant.from_address if verified else "",
        send_as_verified_at=timezone.now() if verified else None)


def _mime_sent(fake):
    """The MIME of the one draft Graph was handed, parsed."""
    drafts = [c for c in fake.of("POST", "/me/messages") if c["url"].endswith("/me/messages")]
    assert len(drafts) == 1
    assert drafts[0]["headers"]["Content-Type"] == "text/plain"
    return message_from_bytes(base64.b64decode(drafts[0]["data"]), policy=policy.default)


# ============================================================ role boundaries

@pytest.mark.django_db
@pytest.mark.parametrize("path", [STATUS, START, VERIFY, DISCONNECT, ADDRESS, PROVIDER, SWITCH])
def test_an_assistant_reaches_nothing(path, ms_practice, va, api, ms):
    """H7: an assistant connects no mailbox and switches nothing."""
    client = api.as_(va)
    response = client.get(path) if path in (STATUS, PROVIDER) else client.post(path)
    assert response.status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("path", [STATUS, START, VERIFY, DISCONNECT, ADDRESS, PROVIDER, SWITCH])
def test_client_users_reach_nothing(path, ms_practice, fcc, api, ms):
    client = api.as_(fcc)
    response = client.get(path) if path in (STATUS, PROVIDER) else client.post(path)
    assert response.status_code == 403


@pytest.mark.django_db
def test_only_the_practice_owner_switches_the_transport(seeded_tenant, ff, cf, api, ms):
    said = api.as_(cf).get(PROVIDER).json()
    assert said["provider"] == "google" and said["can_switch"] is False
    assert api.as_(cf).post(SWITCH, {"provider": "microsoft"},
                            content_type="application/json").status_code == 403
    seeded_tenant.refresh_from_db()
    assert seeded_tenant.mail_provider == "google"

    said = api.as_(ff).post(SWITCH, {"provider": "microsoft"},
                            content_type="application/json").json()
    assert said["provider"] == "microsoft" and said["label"] == "Microsoft 365"
    seeded_tenant.refresh_from_db()
    assert seeded_tenant.mail_provider == "microsoft"
    event = AuditEvent.all_objects.get(verb="practice.mail_provider_changed")
    assert event.payload == {"from": "google", "to": "microsoft"}


@pytest.mark.django_db
def test_a_switch_names_one_of_the_two(seeded_tenant, ff, api, ms):
    response = api.as_(ff).post(SWITCH, {"provider": "postmark"}, content_type="application/json")
    assert response.status_code == 400


@pytest.mark.django_db
def test_a_switch_waits_for_an_empty_outbox_and_says_how_many(seeded_tenant, ff, api, ms):
    """Nothing waiting may go out through a transport nobody chose for it.
    Sent, rejected, expired and suppressed rows are history, not waiting; and
    another practice's queue is not this one's."""
    for state in ("draft", "pending_approval", "approved"):
        OutboxMessageFactory(tenant=seeded_tenant, state=state)
    for state in ("sent", "rejected", "expired", "suppressed"):
        OutboxMessageFactory(tenant=seeded_tenant, state=state)
    OutboxMessageFactory(tenant=TenantFactory(), state="pending_approval")

    response = api.as_(ff).post(SWITCH, {"provider": "microsoft"},
                                content_type="application/json")
    assert response.status_code == 409
    assert "The Outbox has 3 messages waiting" in response.json()["detail"]
    seeded_tenant.refresh_from_db()
    assert seeded_tenant.mail_provider == "google"

    OutboxMessage.all_objects.filter(tenant=seeded_tenant, state__in=[
        "draft", "approved"]).update(state="rejected")
    response = api.as_(ff).post(SWITCH, {"provider": "microsoft"},
                                content_type="application/json")
    assert "The Outbox has 1 message waiting" in response.json()["detail"]

    OutboxMessage.all_objects.filter(tenant=seeded_tenant).update(state="sent")
    response = api.as_(ff).post(SWITCH, {"provider": "microsoft"},
                                content_type="application/json")
    assert response.status_code == 200 and response.json()["provider"] == "microsoft"
    # Choosing the one it already has is no switch, waiting or not.
    OutboxMessageFactory(tenant=seeded_tenant, state="draft")
    assert api.as_(ff).post(SWITCH, {"provider": "microsoft"},
                            content_type="application/json").status_code == 200


@pytest.mark.django_db
def test_switching_deletes_no_connection(seeded_tenant, ff, api, ms):
    gmail = GmailConnectionFactory(tenant=seeded_tenant, user=ff.user)
    microsoft = MicrosoftConnectionFactory(tenant=seeded_tenant, user=ff.user)
    for provider in ("microsoft", "google"):
        api.as_(ff).post(SWITCH, {"provider": provider}, content_type="application/json")
    assert GmailConnection.all_objects.filter(pk=gmail.pk).exists()
    assert MicrosoftConnection.all_objects.filter(pk=microsoft.pk).exists()


@pytest.mark.django_db
def test_an_associate_does_not_see_the_owners_connection_as_their_own(
        ms_practice, ff, cf, api, ms):
    _connect(ms_practice, ff)
    body = api.as_(cf).get(STATUS).json()
    assert body["connected"] is False and body["email_address"] == ""
    # The practice-level fact is visible: their mail rides on it too.
    assert body["practice_sending"] == {"ok": True, "detail": "", "account": OWN}


@pytest.mark.django_db
def test_an_associate_cannot_disconnect_the_owners_connection(ms_practice, ff, cf, api, ms):
    mine = _connect(ms_practice, ff)
    assert api.as_(cf).post(DISCONNECT).status_code == 400
    assert MicrosoftConnection.all_objects.filter(pk=mine.pk).exists()


@pytest.mark.django_db
def test_only_the_practice_owner_sets_the_practice_address(ms_practice, cf, api, ms):
    response = api.as_(cf).post(ADDRESS, {"address": "hello@contoso.example"},
                                content_type="application/json")
    assert response.status_code == 403


@pytest.mark.django_db
def test_an_assistant_cannot_store_a_connection_through_the_callback(
        ms_practice, va, api, ms):
    client = api.as_(va)
    session = client.session
    session[microsoft_oauth.STATE_SESSION_KEY] = "st"
    session.save()
    response = client.get(CALLBACK, {"code": "c", "state": "st"})
    assert response.status_code == 302 and "ms_error" in response["Location"]
    assert not MicrosoftConnection.all_objects.exists()
    assert ms.of("POST", "/oauth2/v2.0/token") == []


# ============================================================ tenant isolation

@pytest.mark.django_db
def test_another_practices_connection_is_invisible(ms_practice, ff, api, ms):
    other = TenantFactory(name="Other practice", slug="other-ms", mail_provider="microsoft",
                          from_address=ALIAS)
    _connect(other, MembershipFactory(tenant=other, role=Role.FF))
    body = api.as_(ff).get(STATUS).json()
    assert body["connected"] is False
    assert body["practice_sending"]["ok"] is False


@pytest.mark.django_db
def test_disconnect_cannot_reach_another_practices_row(ms_practice, ff, api, ms):
    other = TenantFactory(name="Other practice", slug="other-ms-2", mail_provider="microsoft")
    theirs = _connect(other, MembershipFactory(tenant=other, role=Role.FF))
    assert api.as_(ff).post(DISCONNECT).status_code == 400
    assert MicrosoftConnection.all_objects.filter(pk=theirs.pk).exists()


@pytest.mark.django_db
def test_a_person_in_two_practices_sends_each_through_its_own(ms_practice, ff, ms):
    """The same work account connected in practice B is not practice A's: A
    has no connection, and says so, rather than borrowing B's."""
    other = TenantFactory(name="Other practice", slug="other-ms-3", mail_provider="microsoft",
                          from_address=ALIAS)
    MembershipFactory(tenant=other, role=Role.FF, user=ff.user)
    _connect(other, MembershipFactory.build(tenant=other, user=ff.user))
    with pytest.raises(transport.TransportUnavailable, match="No Microsoft 365 account"):
        graph.sending_connection_for(ms_practice)
    assert graph.sending_connection_for(other).tenant_id == other.pk


@pytest.mark.django_db
def test_a_switch_in_one_practice_leaves_another_alone(seeded_tenant, ff, api, ms):
    other = TenantFactory(name="Other practice", slug="other-ms-4")
    api.as_(ff).post(SWITCH, {"provider": "microsoft"}, content_type="application/json")
    other.refresh_from_db()
    assert other.mail_provider == "google"


@pytest.mark.django_db
def test_the_poll_reads_only_this_practices_conversations(ms_practice, ff, ms):
    other = TenantFactory(name="Other practice", slug="other-ms-5", mail_provider="microsoft")
    EmailThread.all_objects.create(tenant=other, thread_token="theirs",
                                   graph_conversation_id="THEIR-CONVERSATION")
    EmailThread.all_objects.create(tenant=ms_practice, thread_token="ours",
                                   graph_conversation_id="OUR-CONVERSATION")
    _connect(ms_practice, ff, read=True)
    ms.on("GET", "/me/messages?", Reply(payload=fixture("conversation_empty.json")))
    ms.on("GET", "/me/messages", Reply(payload=fixture("conversation_empty.json")))
    with tenant_context(ms_practice.pk):
        inbound_poll.poll(ms_practice)
    asked = [c["params"]["$filter"] for c in ms.calls if c.get("params")
             and "$filter" in c["params"]]
    assert asked == ["conversationId eq 'OUR-CONVERSATION'"]


@pytest.mark.django_db
def test_the_callback_stores_the_connection_in_the_signed_in_practice(
        ms_practice, ff, api, ms):
    ms.on("POST", "/oauth2/v2.0/token", Reply(payload=fixture("token.json")))
    other = TenantFactory(name="Other practice", slug="other-ms-6", mail_provider="microsoft")
    client = api.as_(ff)
    session = client.session
    session[microsoft_oauth.STATE_SESSION_KEY] = "st"
    session.save()
    client.get(CALLBACK, {"code": "c", "state": "st"})
    row = MicrosoftConnection.all_objects.get()
    assert row.tenant_id == ms_practice.pk
    assert not MicrosoftConnection.all_objects.filter(tenant=other).exists()
    assert TenantSecret.all_objects.get(pk=row.secret_id).tenant_id == ms_practice.pk


# ======================================================== connecting (OAuth)

@pytest.mark.django_db
def test_start_refuses_while_the_practice_is_on_gmail(seeded_tenant, ff, api, ms):
    response = api.as_(ff).post(START)
    assert response.status_code == 409
    assert "goes through Gmail" in response.json()["detail"]


@pytest.mark.django_db
def test_start_says_when_the_server_has_no_app_registration(ms_practice, ff, api, settings):
    settings.MICROSOFT_CLIENT_ID = ""
    response = api.as_(ff).post(START)
    assert response.status_code == 400 and "isn't set up" in response.json()["detail"]
    assert api.as_(ff).get(STATUS).json()["configured"] is False


@pytest.mark.django_db
def test_start_asks_to_read_mail_only_when_ticked(ms_practice, ff, api, ms):
    from urllib.parse import parse_qs, urlparse

    send_only = parse_qs(urlparse(api.as_(ff).post(START).json()["authorization_url"]).query)
    assert send_only["scope"][0].split() == microsoft_oauth.SEND_SCOPES
    assert "Mail.Read" not in send_only["scope"][0].split()
    assert send_only["redirect_uri"] == ["http://testserver/accounts/microsoft/callback"] \
        or send_only["redirect_uri"][0].endswith("/accounts/microsoft/callback")
    url = api.as_(ff).post(START, {"inbound": True}, content_type="application/json").json()
    with_read = parse_qs(urlparse(url["authorization_url"]).query)
    assert "Mail.Read" in with_read["scope"][0].split()
    assert urlparse(url["authorization_url"]).netloc == "login.microsoftonline.com"
    assert urlparse(url["authorization_url"]).path == "/organizations/oauth2/v2.0/authorize"


@pytest.mark.django_db
def test_the_callback_stores_the_account_and_checks_the_address(ms_practice, ff, api, ms):
    ms.on("POST", "/oauth2/v2.0/token", [Reply(payload=fixture("token.json")),
                                         Reply(payload=fixture("refreshed.json"))])
    client = api.as_(ff)
    session = client.session
    session[microsoft_oauth.STATE_SESSION_KEY] = "st"
    session.save()
    response = client.get(CALLBACK, {"code": "c", "state": "st"})

    assert response.status_code == 302
    assert "ms_connected=bryan%40contoso.example" in response["Location"]
    assert "ms_warning" not in response["Location"]
    row = MicrosoftConnection.all_objects.get()
    assert row.email_address == OWN
    assert row.directory_id == DIRECTORY
    assert row.scopes == ["Mail.ReadBasic", "Mail.Send", "User.Read", "email", "openid",
                          "profile"]
    assert row.send_as_verified_at is not None and row.send_as_address == ALIAS
    # The check was a real test send from the alias to the account's own inbox.
    mime = _mime_sent(ms)
    assert mime["From"] == ALIAS and mime["To"] == OWN


@pytest.mark.django_db
def test_consent_without_sending_stores_nothing(ms_practice, ff, api, ms):
    ms.on("POST", "/oauth2/v2.0/token", Reply(payload=fixture("token_without_send.json")))
    client = api.as_(ff)
    session = client.session
    session[microsoft_oauth.STATE_SESSION_KEY] = "st"
    session.save()
    response = client.get(CALLBACK, {"code": "c", "state": "st"})
    assert "Mail.Send" in response["Location"] and "ms_error" in response["Location"]
    assert not MicrosoftConnection.all_objects.exists()


@pytest.mark.django_db
def test_a_directory_that_needs_its_admin_gets_the_admin_link(ms_practice, ff, api, ms):
    client = api.as_(ff)
    session = client.session
    session[microsoft_oauth.STATE_SESSION_KEY] = "st"
    session.save()
    response = client.get(CALLBACK, {
        "state": "st", "error": "access_denied",
        "error_description": "AADSTS90094: Admin approval required for this app."})
    from urllib.parse import parse_qs, urlparse

    said = parse_qs(urlparse(response["Location"]).query)["ms_error"][0]
    assert "AADSTS90094" in said and "administrator approves the app once" in said
    assert "/organizations/v2.0/adminconsent?client_id=client-id" in said
    assert not MicrosoftConnection.all_objects.exists()


@pytest.mark.django_db
def test_a_consent_this_browser_did_not_start_is_refused(ms_practice, ff, api, ms):
    client = api.as_(ff)
    session = client.session
    session[microsoft_oauth.STATE_SESSION_KEY] = "mine"
    session.save()
    response = client.get(CALLBACK, {"code": "c", "state": "forged"})
    assert "did+not+match" in response["Location"]
    assert ms.calls == []


@pytest.mark.django_db
def test_the_scope_names_compare_in_either_form():
    assert microsoft_oauth.missing_scopes(fixture("token_with_read.json")) == []
    assert microsoft_oauth.inbound_granted(fixture("token_with_read.json"))
    assert not microsoft_oauth.inbound_granted(fixture("token.json"))


@pytest.mark.django_db
def test_disconnect_deletes_the_token_with_the_row(ms_practice, ff, api, ms):
    row = _connect(ms_practice, ff)
    secret_id = row.secret_id
    body = api.as_(ff).post(DISCONNECT).json()
    assert body["connected"] is False
    assert not TenantSecret.all_objects.filter(pk=secret_id).exists()


@pytest.mark.django_db
def test_removing_a_member_removes_their_microsoft_connection(ms_practice, cf, ms):
    from apps.tenancy.services import remove_member

    row = _connect(ms_practice, cf)
    remove_member(cf)
    assert not MicrosoftConnection.all_objects.filter(pk=row.pk).exists()
    assert not TenantSecret.all_objects.filter(pk=row.secret_id).exists()


# ===================================================== the practice address (D3)

@pytest.mark.django_db
def test_the_own_address_passes_without_a_test_send(ms_practice, ff, ms):
    row = _connect(ms_practice, ff, verified=False)
    assert graph.verify_send_as(row, OWN) is True
    assert ms.calls == []


@pytest.mark.django_db
def test_an_alias_passes_when_sent_items_shows_it(ms_practice, ff, ms):
    row = _connect(ms_practice, ff, verified=False)
    assert graph.verify_send_as(row, ALIAS) is True
    row.refresh_from_db()
    assert row.send_as_address == ALIAS and row.send_as_error == ""
    assert ms.of("GET", "/me/messages/AAkAL")[0]["params"] == {"$select": "from,sender,isDraft"}


@pytest.mark.django_db
def test_a_quiet_rewrite_to_the_own_address_fails_the_check(ms_practice, ff, ms):
    """The failure that matters: Microsoft sends it, from the wrong address."""
    ms.on("GET", "/me/messages/AAkAL", Reply(payload=fixture("sent_item_rewritten.json")))
    row = _connect(ms_practice, ff, verified=False)
    with pytest.raises(transport.SendAsNotVerified, match=f"sent the check from {OWN}"):
        graph.verify_send_as(row, ALIAS)
    row.refresh_from_db()
    assert row.send_as_verified_at is None and "Send as" in row.send_as_error


@pytest.mark.django_db
def test_a_refused_alias_says_how_to_allow_it(ms_practice, ff, ms):
    ms.on("POST", "/send", Reply(403, fixture("error_send_as_denied.json")))
    row = _connect(ms_practice, ff, verified=False)
    with pytest.raises(transport.SendAsNotVerified, match="would not let"):
        graph.verify_send_as(row, ALIAS)
    assert ms.of("DELETE", "/me/messages/")      # the half-made draft is removed


@pytest.mark.django_db
def test_a_copy_not_yet_in_sent_items_is_not_a_pass(ms_practice, ff, ms):
    draft = dict(fixture("sent_item.json"), isDraft=True)
    ms.on("GET", "/me/messages/AAkAL", Reply(payload=draft))
    row = _connect(ms_practice, ff, verified=False)
    with pytest.raises(transport.SendAsNotVerified, match="Check again in a minute"):
        graph.verify_send_as(row, ALIAS)
    assert len(ms.of("GET", "/me/messages/AAkAL")) == graph.READ_BACK_TRIES


@pytest.mark.django_db
def test_changing_the_practice_address_checks_it_again(ms_practice, ff, api, ms):
    _connect(ms_practice, ff)
    body = api.as_(ff).post(ADDRESS, {"address": "hello@contoso.example"},
                            content_type="application/json").json()
    ms_practice.refresh_from_db()
    assert ms_practice.from_address == "hello@contoso.example"
    assert body["alias"] == "hello@contoso.example"
    # The fixture's Sent Items copy is from info@, so the new address fails.
    assert body["alias_verified"] is False and "verify_error" in body


# ================================================================== sending

def _approve(tenant, ff, settings, **kw):
    settings.DEV_REAL_SEND_ALLOWLIST = ["dana@acme.invalid"]
    message = OutboxMessageFactory(tenant=tenant, state=S.PENDING_APPROVAL,
                                   to_address="dana@acme.invalid", **kw)
    with tenant_context(tenant.pk):
        outbox.approve(message, actor=ff.user, role="FF")
    message.refresh_from_db()
    return message


@pytest.mark.django_db
def test_an_approved_message_goes_through_graph(ms_practice, ff, ms, settings):
    _connect(ms_practice, ff)
    message = _approve(ms_practice, ff, settings, subject="Your progress report")

    mime = _mime_sent(ms)
    assert mime["From"] == ALIAS and mime["To"] == "dana@acme.invalid"
    assert mime["Subject"] == "Your progress report"
    assert mime[transport.THREAD_HEADER] == message.thread.thread_token
    assert mime["Message-ID"].startswith(f"<{message.thread.thread_token}.")
    assert len(ms.of("POST", "/send")) == 1
    # Immutable ids on every call, so the draft's id is the sent copy's.
    assert all(c["headers"].get("Prefer") == 'IdType="ImmutableId"'
               for c in ms.calls if "graph.microsoft.com" in c["url"])

    assert message.state == S.SENT and message.sent_via == "microsoft"
    assert message.provider_message_id == fixture("draft_created.json")["id"]
    thread = EmailThread.all_objects.get(pk=message.thread_id)
    assert thread.graph_conversation_id == fixture("draft_created.json")["conversationId"]
    assert thread.gmail_thread_id == ""
    sent = EmailMessage.all_objects.get(thread=thread)
    assert sent.provider == "microsoft"
    assert sent.message_id_header == fixture("draft_created.json")["internetMessageId"]


@pytest.mark.django_db
def test_a_rotated_refresh_token_is_kept(ms_practice, ff, ms, settings):
    from apps.crm.services.secrets import read_secret

    row = _connect(ms_practice, ff)
    _approve(ms_practice, ff, settings)
    row.refresh_from_db()
    assert read_secret(row.secret) == "0.AAAA-refresh-2"


@pytest.mark.django_db
def test_a_refused_credential_says_reconnect(ms_practice, ff, ms):
    ms.on("POST", "/oauth2/v2.0/token", Reply(400, fixture("token_invalid_grant.json")))
    row = _connect(ms_practice, ff)
    with pytest.raises(transport.TransportUnavailable, match="Reconnect Microsoft 365") as exc:
        graph.access_token_for(row)
    assert "AADSTS70000" in str(exc.value) and "Trace ID" not in str(exc.value)


@pytest.mark.django_db
def test_marketing_carries_the_one_click_unsubscribe_headers(ms_practice, ff, ms, settings):
    _connect(ms_practice, ff)
    contact = ContactFactory(tenant=ms_practice)
    ContactEmailFactory(tenant=ms_practice, contact=contact, address="dana@acme.invalid")
    settings.DEV_REAL_SEND_ALLOWLIST = ["dana@acme.invalid"]
    with tenant_context(ms_practice.pk):
        message = outbox.create_message(
            tenant=ms_practice, producer=P.STAGE_RULE, to_contact=contact,
            to_address="dana@acme.invalid", subject="Checking in", body_text="Hi")
        outbox.approve(message, actor=ff.user, role="FF")
    mime = _mime_sent(ms)
    assert mime["List-Unsubscribe"].startswith("<") and "/one-click>" in mime["List-Unsubscribe"]
    assert mime["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    # Exactly as sent, unparsed: one line each, no encoded-words.
    drafts = [c for c in ms.of("POST", "/me/messages") if c["url"].endswith("/me/messages")]
    head = base64.b64decode(drafts[0]["data"]).split(b"\n\n", 1)[0].decode("ascii")
    lines = head.splitlines()
    with tenant_context(ms_practice.pk):
        from apps.crm.services import unsubscribe
        expected = unsubscribe.headers_for(message)["List-Unsubscribe"]
    assert f"List-Unsubscribe: {expected}" in lines
    assert "List-Unsubscribe-Post: List-Unsubscribe=One-Click" in lines


@pytest.mark.django_db
def test_an_unsubscribed_address_never_reaches_graph(ms_practice, ff, ms, settings):
    _connect(ms_practice, ff)
    contact = ContactFactory(tenant=ms_practice)
    ContactEmailFactory(tenant=ms_practice, contact=contact, address="dana@acme.invalid")
    EmailSuppression.all_objects.create(tenant=ms_practice, contact=contact,
                                        category="marketing")
    settings.DEV_REAL_SEND_ALLOWLIST = ["dana@acme.invalid"]
    with tenant_context(ms_practice.pk):
        message = outbox.create_message(
            tenant=ms_practice, producer=P.STAGE_RULE, to_contact=contact,
            to_address="dana@acme.invalid", subject="Checking in", body_text="Hi")
        with pytest.raises(Exception):
            outbox.approve(message, actor=ff.user, role="FF")
    message.refresh_from_db()
    assert message.state == S.SUPPRESSED
    assert ms.of("POST", "/me/messages") == []


@pytest.mark.django_db
def test_the_laptop_allow_list_still_decides(ms_practice, ff, ms, settings, dev_outbox):
    """On a localhost build, an address not on the allow-list goes to the dev
    outbox, whichever transport the practice has."""
    _connect(ms_practice, ff)
    settings.IS_LOCAL = True
    settings.DEV_REAL_SEND_ALLOWLIST = []
    message = OutboxMessageFactory(tenant=ms_practice, state=S.PENDING_APPROVAL,
                                   to_address="someone@acme.invalid")
    with tenant_context(ms_practice.pk):
        outbox.approve(message, actor=ff.user, role="FF")
    assert len(dev_outbox) == 1
    assert ms.calls == []


@pytest.mark.django_db
def test_a_joint_introduction_is_one_message_to_both(ms_practice, ff, ms, settings):
    _connect(ms_practice, ff)
    settings.DEV_REAL_SEND_ALLOWLIST = ["dana@acme.invalid", "lee@acme.invalid"]
    message = OutboxMessageFactory(tenant=ms_practice, state=S.PENDING_APPROVAL,
                                   to_address="dana@acme.invalid",
                                   also_to_address="lee@acme.invalid")
    with tenant_context(ms_practice.pk):
        outbox.approve(message, actor=ff.user, role="FF")
    assert _mime_sent(ms)["To"] == "dana@acme.invalid, lee@acme.invalid"


@pytest.mark.django_db
def test_an_associates_own_address_goes_through_their_own_account(
        ms_practice, ff, cf, ms, settings):
    _connect(ms_practice, ff)
    _connect(ms_practice, cf, address="casey@contoso.example")
    _approve(ms_practice, ff, settings, from_address="casey@contoso.example")
    assert _mime_sent(ms)["From"] == "casey@contoso.example"


@pytest.mark.django_db
def test_an_associates_own_address_is_offered_from_their_microsoft_connection(
        ms_practice, cf, ms):
    _connect(ms_practice, cf, address="casey@contoso.example")
    assert sender.verified_addresses(ms_practice, cf.user) == (ALIAS, "casey@contoso.example")


@pytest.mark.django_db
def test_a_refused_alias_fails_the_send_and_leaves_no_draft(ms_practice, ff, ms, settings):
    ms.on("POST", "/send", Reply(403, fixture("error_send_as_denied.json")))
    _connect(ms_practice, ff)
    with pytest.raises(transport.SendAsNotVerified, match="Send as"):
        _approve(ms_practice, ff, settings)
    assert len(ms.of("DELETE", "/me/messages/")) == 1


@pytest.mark.django_db
def test_no_connection_says_so(ms_practice, ff, ms, settings):
    with pytest.raises(transport.TransportUnavailable, match="No Microsoft 365 account"):
        _approve(ms_practice, ff, settings)


@pytest.mark.django_db
def test_a_short_throttle_is_waited_out(ms_practice, ff, ms, settings):
    ms.on("POST", "/send", [Reply(429, fixture("error_throttled.json"), headers={"Retry-After": "2"}),
                            Reply(202)])
    _connect(ms_practice, ff)
    message = _approve(ms_practice, ff, settings)
    assert message.state == S.SENT
    assert len(ms.of("POST", "/send")) == 2
    graph.time.sleep.assert_called_once_with(2)


@pytest.mark.django_db
def test_a_long_throttle_fails_the_send_with_graphs_words(ms_practice, ff, ms, settings):
    ms.on("POST", "/send", Reply(429, fixture("error_throttled.json"),
                                 headers={"Retry-After": "120"}))
    _connect(ms_practice, ff)
    with pytest.raises(transport.TransportUnavailable, match="ApplicationThrottled"):
        _approve(ms_practice, ff, settings)
    graph.time.sleep.assert_not_called()


@pytest.mark.django_db
def test_a_small_attachment_rides_in_the_mime(ms_practice, ff, ms):
    _connect(ms_practice, ff)
    thread = EmailThread.all_objects.create(tenant=ms_practice, thread_token="t-small")
    graph.GraphTransport().send(
        tenant=ms_practice, to_address="dana@acme.invalid", subject="Plan",
        body_text="Attached.", thread=thread,
        attachments=[("plan.pdf", b"%PDF-1.4 small", "application/pdf")])
    mime = _mime_sent(ms)
    part = next(p for p in mime.walk() if p.get_filename() == "plan.pdf")
    assert part.get_payload(decode=True) == b"%PDF-1.4 small"
    assert ms.of("POST", "/attachments") == []


@pytest.mark.django_db
def test_an_attachment_that_would_push_the_request_over_4_mb_is_added_after(
        ms_practice, ff, ms):
    """2.5 MB of file is about 4.4 MB of request once the MIME and Graph have
    each base64'd it: the draft goes without it, and the file follows in one
    POST of its own (under 3 MB, so no upload session)."""
    _connect(ms_practice, ff)
    thread = EmailThread.all_objects.create(tenant=ms_practice, thread_token="t-mid")
    middling = b"y" * int(2.5 * 1024 * 1024)
    graph.GraphTransport().send(
        tenant=ms_practice, to_address="dana@acme.invalid", subject="Plan",
        body_text="Attached.", thread=thread,
        attachments=[("deck.pdf", middling, "application/pdf")])
    drafts = [c for c in ms.of("POST", "/me/messages") if c["url"].endswith("/me/messages")]
    assert len(drafts[0]["data"]) <= graph.REQUEST_LIMIT
    added = ms.of("POST", "/attachments")
    assert len(added) == 1 and added[0]["json"]["name"] == "deck.pdf"
    assert base64.b64decode(added[0]["json"]["contentBytes"]) == middling
    assert ms.of("POST", "/createUploadSession") == []


@pytest.mark.django_db
def test_a_large_attachment_goes_up_in_an_upload_session(ms_practice, ff, ms):
    """Over 3 MB the draft is made without it and it is uploaded in 320 KiB
    multiples, to a URL that carries its own authorization."""
    ms.on("POST", "/createUploadSession", Reply(payload=fixture("upload_session.json")))
    ms.on("PUT", "AttachmentSessions", Reply(200))
    _connect(ms_practice, ff)
    thread = EmailThread.all_objects.create(tenant=ms_practice, thread_token="t-big")
    big = b"x" * (5 * 1024 * 1024)
    graph.GraphTransport().send(
        tenant=ms_practice, to_address="dana@acme.invalid", subject="Plan",
        body_text="Attached.", thread=thread,
        attachments=[("flyer.pdf", big, "application/pdf")])

    mime = _mime_sent(ms)
    assert not any(p.get_filename() == "flyer.pdf" for p in mime.walk())
    session = ms.of("POST", "/createUploadSession")[0]["json"]["AttachmentItem"]
    assert session == {"attachmentType": "file", "name": "flyer.pdf",
                       "size": len(big), "contentType": "application/pdf"}
    puts = ms.of("PUT", "AttachmentSessions")
    assert b"".join(p["data"] for p in puts) == big
    assert all("Authorization" not in p["headers"] for p in puts)
    assert all(len(p["data"]) % (320 * 1024) == 0 for p in puts[:-1])
    assert puts[0]["headers"]["Content-Range"] == f"bytes 0-{graph.CHUNK - 1}/{len(big)}"
    # Attachments first, then the send.
    order = [c["url"] for c in ms.calls]
    assert max(i for i, u in enumerate(order) if "AttachmentSessions" in u) < \
        next(i for i, u in enumerate(order) if u.endswith("/send"))


@pytest.mark.django_db
def test_the_demo_never_sends_through_microsoft(ms_practice, ff, ms, settings):
    settings.APP_ENVIRONMENT, settings.IS_DEMO, settings.IS_LOCAL = "demo", True, False
    _connect(ms_practice, ff)
    thread = EmailThread.all_objects.create(tenant=ms_practice, thread_token="t-demo")
    with pytest.raises(transport.TransportUnavailable, match="This is the demo"):
        graph.GraphTransport().send(tenant=ms_practice, to_address="dana@acme.invalid",
                                    subject="x", body_text="x", thread=thread)
    assert ms.calls == []


@pytest.mark.django_db
def test_the_demo_cannot_be_switched_or_connected(seeded_tenant, ff, api, ms, settings):
    settings.APP_ENVIRONMENT, settings.IS_DEMO, settings.IS_LOCAL = "demo", True, False
    said = api.as_(ff).get(PROVIDER).json()
    assert said["can_switch"] is False and "This is the demo" in said["refusal"]
    response = api.as_(ff).post(SWITCH, {"provider": "microsoft"},
                                content_type="application/json")
    assert response.status_code == 409
    seeded_tenant.refresh_from_db()
    assert seeded_tenant.mail_provider == "google"


# ================================================================== replies

def _sent_thread(tenant, contact=None):
    draft = fixture("draft_created.json")
    thread = EmailThread.all_objects.create(
        tenant=tenant, thread_token="TOKEN", contact=contact,
        graph_conversation_id=draft["conversationId"])
    EmailMessage.all_objects.create(
        tenant=tenant, thread=thread, direction="outbound", provider="microsoft",
        provider_message_id=draft["id"], from_address=ALIAS,
        to_addresses=["dana@acme.invalid"], message_id_header=draft["internetMessageId"])
    return thread


def _serve_conversation(fake):
    fake.on("GET", "/me/messages", Reply(payload=fixture("conversation.json")))
    fake.on("GET", "/$value", Reply(content=fixture("reply.eml")))


@pytest.mark.django_db
def test_a_reply_is_read_from_the_stored_conversation(ms_practice, ff, ms):
    contact = ContactFactory(tenant=ms_practice)
    thread = _sent_thread(ms_practice, contact)
    _connect(ms_practice, ff, read=True)
    _serve_conversation(ms)

    with tenant_context(ms_practice.pk):
        totals = inbound_poll.poll(ms_practice)

    assert totals["matched"] == 1 and totals["skipped_outbound"] == 1
    reply = EmailMessage.all_objects.get(direction="inbound")
    assert reply.thread_id == thread.pk and reply.contact_id == contact.pk
    assert reply.provider == "microsoft"
    assert reply.matched_by == inbound.BY_CONVERSATION
    assert reply.provider_message_id == "AAkALgAAAAAAHYQDEapmEc2byACqAC-EWg0AImmutable-reply"
    assert reply.gmail_message_id == "" and reply.gmail_thread_id == ""
    # windows-1252 on the wire, UTF-8 here; the quoted history trimmed.
    assert reply.body_stripped == "Thanks – the numbers look right. One question on the hiring plan."
    assert reply.in_reply_to == fixture("draft_created.json")["internetMessageId"]
    with tenant_context(ms_practice.pk):
        assert [a.filename for a in reply.attachments.all()] == ["hiring-plan.pdf"]
    # Only the unknown message's MIME was fetched: not ours, not the draft.
    assert len(ms.of("GET", "/$value")) == 1
    assert "/AAkALgAAAAAAHYQDEapmEc2byACqAC-EWg0AImmutable-reply/$value" in \
        ms.of("GET", "/$value")[0]["url"]


@pytest.mark.django_db
def test_a_second_poll_files_nothing_twice_and_fetches_no_mime(ms_practice, ff, ms):
    _sent_thread(ms_practice, ContactFactory(tenant=ms_practice))
    _connect(ms_practice, ff, read=True)
    _serve_conversation(ms)
    with tenant_context(ms_practice.pk):
        inbound_poll.poll(ms_practice)
        EmailThread.objects.update(last_polled_at=None)
        again = inbound_poll.poll(ms_practice)
    assert again["matched"] == 0 and again["already_had"] == 1
    assert EmailMessage.all_objects.filter(direction="inbound").count() == 1
    assert len(ms.of("GET", "/$value")) == 1


@pytest.mark.django_db
def test_a_reply_outside_the_conversation_matches_by_in_reply_to(ms_practice, ff, ms):
    """Exchange may start a new conversation for a reply from another client;
    the Message-ID it quotes still brings it home (FR-6.6)."""
    thread = _sent_thread(ms_practice)
    raw = fixture("reply.eml")
    payload = graph.mime_to_payload(raw, message_id="m-x", conversation_id="ANOTHER",
                                    received="2026-10-27T16:30:00Z")
    with tenant_context(ms_practice.pk):
        result = inbound.ingest_message(ms_practice, payload)
    assert result["outcome"] == "matched" and result["matched_by"] == inbound.BY_IN_REPLY_TO
    assert result["message"].thread_id == thread.pk


@pytest.mark.django_db
def test_an_unmatched_reply_waits_and_files_into_its_conversation(ms_practice, ff, ms):
    raw = fixture("reply.eml").replace(b"In-Reply-To", b"X-Was-In-Reply-To") \
        .replace(b"References:", b"X-Was-References:")
    payload = graph.mime_to_payload(raw, message_id="m-u", conversation_id="CONV-U")
    with tenant_context(ms_practice.pk):
        result = inbound.ingest_message(ms_practice, payload)
        row = result["unmatched"]
        assert row.provider == "microsoft" and row.graph_conversation_id == "CONV-U"
        contact = ContactFactory(tenant=ms_practice)
        message = inbound.file_to_contact(row, contact=contact, actor=ff.user)
    assert message.provider == "microsoft" and message.gmail_message_id == ""
    assert message.thread.graph_conversation_id == "CONV-U"
    assert UnmatchedInbound.all_objects.get(pk=row.pk).state == "filed"


@pytest.mark.django_db
def test_a_poll_without_mail_read_says_reconnect(ms_practice, ff, ms):
    _connect(ms_practice, ff, read=False)
    with tenant_context(ms_practice.pk), \
            pytest.raises(inbound_poll.NotConnected, match="Also collect replies"):
        inbound_poll.poll(ms_practice)


@pytest.mark.django_db
def test_a_deleted_conversation_is_not_an_error(ms_practice, ff, ms):
    _sent_thread(ms_practice)
    _connect(ms_practice, ff, read=True)
    ms.on("GET", "/me/messages", Reply(payload=fixture("conversation_empty.json")))
    with tenant_context(ms_practice.pk):
        totals = inbound_poll.poll(ms_practice)
    assert totals["errors"] == 0 and totals["threads"] == 1


@pytest.mark.django_db
def test_a_practice_on_microsoft_reads_no_gmail_thread(ms_practice, ff, ms):
    EmailThread.all_objects.create(tenant=ms_practice, thread_token="g",
                                   gmail_thread_id="gmail-thread")
    with tenant_context(ms_practice.pk):
        assert inbound_poll.due(ms_practice) == []


# ====================================================== the Gmail path unchanged

@pytest.mark.django_db
def test_a_gmail_practice_gets_the_gmail_transport(seeded_tenant):
    assert seeded_tenant.mail_provider == "google"
    assert isinstance(transport.get_transport(tenant=seeded_tenant), transport.GmailTransport)
    assert isinstance(transport.get_transport(), transport.GmailTransport)
    seeded_tenant.mail_provider = "microsoft"
    assert isinstance(transport.get_transport(tenant=seeded_tenant), graph.GraphTransport)
    # A transport named outright is still that transport.
    assert isinstance(transport.get_transport("postmark", tenant=seeded_tenant),
                      transport.PostmarkTransport)


@pytest.mark.django_db
def test_a_gmail_send_is_exactly_what_it_was(seeded_tenant, ff, settings):
    """Through `outbox.approve` on a Gmail practice: the one request Google
    receives has the same shape as before, and Microsoft hears nothing."""
    settings.DEV_REAL_SEND_ALLOWLIST = ["dana@acme.invalid"]
    GmailConnectionFactory(tenant=seeded_tenant, user=ff.user,
                           email_address="bryan@getexecutivesnow.com",
                           send_as_address=seeded_tenant.from_address,
                           send_as_verified_at=timezone.now())
    MicrosoftConnectionFactory(tenant=seeded_tenant, user=ff.user,
                               send_as_address=seeded_tenant.from_address,
                               send_as_verified_at=timezone.now())
    posts = []

    def fake_post(url, **kwargs):
        posts.append((url, kwargs))
        stub = mock.Mock(ok=True, status_code=200)
        stub.json.return_value = ({"id": "m1", "threadId": "t1"} if "messages/send" in url
                                  else {"access_token": "at"})
        return stub

    message = OutboxMessageFactory(tenant=seeded_tenant, state=S.PENDING_APPROVAL,
                                   to_address="dana@acme.invalid")
    with mock.patch("apps.crm.services.transport.requests.post", side_effect=fake_post), \
            mock.patch("apps.crm.services.secrets.read_secret", return_value="refresh"), \
            mock.patch("apps.crm.services.graph.requests.request",
                       side_effect=AssertionError("Microsoft was called")), \
            tenant_context(seeded_tenant.pk):
        outbox.approve(message, actor=ff.user, role="FF")

    sends = [kw["json"] for url, kw in posts if url.endswith("/messages/send")]
    assert [url for url, _ in posts] == [transport.TOKEN_URL,
                                         f"{transport.GMAIL_API}/messages/send"]
    assert set(sends[0]) == {"raw"}
    message.refresh_from_db()
    assert message.sent_via == "gmail"
    thread = EmailThread.all_objects.get(pk=message.thread_id)
    assert thread.gmail_thread_id == "t1" and thread.graph_conversation_id == ""


@pytest.mark.django_db
def test_gmail_replies_are_read_as_they_were(seeded_tenant, ff):
    """A Gmail practice polls Gmail threads, with Gmail's reader, and files
    what it finds as Gmail's."""
    from pathlib import Path as _P

    fixture_path = _P(__file__).parent / "fixtures" / "inbound" / "thread_id_match.json"
    payload = json.loads(fixture_path.read_text())
    EmailThread.all_objects.create(tenant=seeded_tenant, thread_token="g1",
                                   gmail_thread_id=payload["id"])
    EmailThread.all_objects.create(tenant=seeded_tenant, thread_token="m1",
                                   graph_conversation_id="CONV")
    GmailConnectionFactory(tenant=seeded_tenant, user=ff.user,
                           scopes=["https://www.googleapis.com/auth/gmail.readonly"])
    reader = mock.Mock()
    reader.thread.return_value = payload
    with tenant_context(seeded_tenant.pk):
        assert len(inbound_poll.due(seeded_tenant)) == 1
        inbound_poll.poll(seeded_tenant, client=reader)
        assert isinstance(inbound_poll.reading_connection(seeded_tenant), GmailConnection)
    reader.thread.assert_called_once_with(payload["id"])
    filed = EmailMessage.all_objects.filter(direction="inbound")
    assert filed.exists()
    assert {m.provider for m in filed} == {"gmail"}
    assert {m.matched_by for m in filed} == {inbound.BY_THREAD_ID}
    assert all(m.gmail_message_id == m.provider_message_id for m in filed)


@pytest.mark.django_db
def test_the_gmail_settings_payload_is_unchanged(seeded_tenant, ff, api):
    with mock.patch("apps.crm.services.transport.requests"):
        body = api.as_(ff).get("/api/gmail-connection/").json()
    assert set(body) == {
        "connected", "email_address", "scopes", "connected_at", "tier2_enabled", "alias",
        "alias_verified", "alias_verified_at", "alias_listed", "send_as", "send_as_error",
        "is_sending_connection", "transport", "transport_label", "practice_sending",
        "oauth_configured", "is_local_build"}
