"""Demo visitors (Melissa's feedback W1, decisions 2026-10-17), each rule on
its own. The copy here is made without the seed (it is made for real in
`test_demo_visitors_seed.py`): the practice, its owner and nothing else.

1. Inviting: who may, and what is refused.
2. Role boundaries: the platform owner's list and actions; the visitor's own
   "Reset my demo".
3. Isolation: a copy is an ordinary practice, kept apart like any other.
4. Being set up, and ended: what a copy answers.
5. AI: the demo's key, the hard stop at $2 a day and $10 in all.
6. Mail: everything a copy sends goes to its visitor, and nobody else.
7. No Gmail or Drive of its own; no beta agreement; not on the Practices list.
8. The sweep: deleted a week after it ends, not before.
"""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.tenancy.context import tenant_context
from apps.tenancy.middleware import AREA_PLATFORM, AREA_SESSION_KEY

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import ContactFactory

VISITOR = "vera@visiting.invalid"


@pytest.fixture
def demo(settings):
    settings.APP_ENVIRONMENT, settings.IS_DEMO, settings.IS_LOCAL = "demo", True, False
    settings.DEMO_MAIL_REDIRECT = "redirect@demo-inbox.invalid"
    return settings


@pytest.fixture
def launched(monkeypatch):
    from apps.tenancy.demo import visitors

    calls = []
    monkeypatch.setattr(visitors, "launch", lambda action, pk=None: calls.append((action, pk)))
    monkeypatch.setattr(visitors, "maybe_sweep", lambda: None)
    return calls


@pytest.fixture
def platform_owner(seeded_tenant):
    """Summit's owner, who is also the platform owner."""
    owner = _member(seeded_tenant, "FF")
    owner.user.is_platform_owner = True
    owner.user.save()
    return owner


def practices_area(api, member):
    client = api.as_(member)
    session = client.session
    session[AREA_SESSION_KEY] = AREA_PLATFORM
    session.save()
    return client


def _ready(visitor):
    """What the setup leaves, without the seed: the practice's structure and
    its owner, ready."""
    from apps.accounts.models import User
    from apps.crm.seed import seed_tenant
    from apps.tenancy.models import DemoVisitor, Membership

    seed_tenant(visitor.tenant)
    user = User.objects.get(email=visitor.email)
    member = Membership.all_objects.create(tenant=visitor.tenant, user=user, role="FF")
    DemoVisitor.objects.filter(pk=visitor.pk).update(state="ready",
                                                     setup_finished_at=timezone.now(),
                                                     agreed_at=timezone.now())
    visitor.refresh_from_db()
    return member


@pytest.fixture
def copy(demo, launched, platform_owner):
    from apps.tenancy.demo import visitors

    visitor = visitors.invite(name="Vera Visitor", email=VISITOR, days=30,
                              actor=platform_owner.user)
    member = _ready(visitor)
    return SimpleNamespace(visitor=visitor, tenant=visitor.tenant, owner=member)


# ================================================================ inviting

@pytest.mark.django_db
def test_inviting_refuses_what_would_not_work(demo, launched, platform_owner):
    from apps.tenancy.demo import visitors

    with pytest.raises(visitors.VisitorRefused) as refused:
        visitors.invite(name="", email="not an address", days=0, actor=platform_owner.user)
    assert set(refused.value.errors) == {"name", "email", "days"}
    # An address that already signs in to a practice here has one practice.
    with pytest.raises(visitors.VisitorRefused) as refused:
        visitors.invite(name="Me", email=platform_owner.user.email.upper(), days=30,
                        actor=platform_owner.user)
    assert "plus address" in refused.value.errors["email"]


@pytest.mark.django_db
def test_visitors_are_made_only_on_the_demo(settings, launched, platform_owner):
    from apps.tenancy.demo import visitors

    settings.APP_ENVIRONMENT, settings.IS_DEMO = "production", False
    with pytest.raises(visitors.VisitorRefused):
        visitors.invite(name="Vera", email=VISITOR, days=30, actor=platform_owner.user)


@pytest.mark.django_db
def test_the_platform_owner_invites_and_the_setup_runs_elsewhere(
        demo, launched, platform_owner, api, django_capture_on_commit_callbacks):
    from apps.tenancy.models import DemoVisitor

    client = practices_area(api, platform_owner)
    with django_capture_on_commit_callbacks(execute=True):
        made = client.post("/api/platform/demo-visitors", json.dumps({
            "name": "Vera Visitor", "email": VISITOR, "days": 14, "note": "From the call"}),
            content_type="application/json")
    assert made.status_code == 201, made.json()
    row = made.json()
    visitor = DemoVisitor.objects.get()
    assert launched == [("setup", visitor.pk)]
    assert (row["name"], row["email"], row["note"], row["state"]) == (
        "Vera Visitor", VISITOR, "From the call", "setting_up")
    assert abs((visitor.expires_at - timezone.now()) - timedelta(days=14)) < timedelta(minutes=1)
    assert row["ai_spent_today_usd"] == "0.00" and row["invited_at"] is None


# ========================================================= role boundaries

@pytest.mark.django_db
def test_role_boundaries_only_the_platform_owner_in_practices_reaches_the_list(
        copy, platform_owner, api, seeded_tenant):
    paths = ["/api/platform/demo-visitors",
             f"/api/platform/demo-visitors/{copy.visitor.pk}/extend",
             f"/api/platform/demo-visitors/{copy.visitor.pk}/reset"]
    for member in (copy.owner, _member(seeded_tenant, "FF"), _member(seeded_tenant, "VA")):
        client = api.as_(member)
        assert client.get(paths[0]).status_code == 403
        for path in paths[1:]:
            assert client.post(path).status_code == 403
        assert client.delete(f"/api/platform/demo-visitors/{copy.visitor.pk}").status_code == 403
    # The platform owner, in their own practice: refused too.
    assert api.as_(platform_owner).get(paths[0]).status_code == 403
    listed = practices_area(api, platform_owner).get(paths[0])
    assert listed.status_code == 200 and listed.json()[0]["email"] == VISITOR


@pytest.mark.django_db
def test_extend_adds_days_from_the_end_or_from_today(copy, platform_owner, api):
    client = practices_area(api, platform_owner)
    before = copy.visitor.expires_at
    extended = client.post(f"/api/platform/demo-visitors/{copy.visitor.pk}/extend",
                           json.dumps({"days": 10}), content_type="application/json")
    assert extended.status_code == 200
    copy.visitor.refresh_from_db()
    assert copy.visitor.expires_at == before + timedelta(days=10)
    # Ended already: from today.
    copy.visitor.expires_at = timezone.now() - timedelta(days=3)
    copy.visitor.save()
    client.post(f"/api/platform/demo-visitors/{copy.visitor.pk}/extend",
                json.dumps({"days": 5}), content_type="application/json")
    copy.visitor.refresh_from_db()
    assert abs(copy.visitor.expires_at - (timezone.now() + timedelta(days=5))) < timedelta(
        minutes=1)


@pytest.mark.django_db
def test_reset_my_demo_is_the_copys_owners_alone(copy, api, launched, ff,
                                                 django_capture_on_commit_callbacks):
    assistant = _member(copy.tenant, "VA")
    assert api.as_(assistant).post("/api/demo/reset").status_code == 403
    # An ordinary practice has nothing to reset.
    assert api.as_(ff).post("/api/demo/reset").status_code == 404
    with django_capture_on_commit_callbacks(execute=True):
        done = api.as_(copy.owner).post("/api/demo/reset")
    assert done.status_code == 200 and done.json()["demo_visitor"]["state"] == "setting_up"
    assert launched == [("setup", copy.visitor.pk)]
    copy.visitor.refresh_from_db()
    assert copy.visitor.reset_count == 1
    # Not twice at once.
    assert api.as_(copy.owner).post("/api/demo/reset").status_code == 409


# ================================================================ isolation

@pytest.mark.django_db
def test_tenant_isolation_a_copy_and_another_practice_see_none_of_each_other(
        copy, api, ff, seeded_tenant):
    with tenant_context(seeded_tenant.pk):
        theirs = ContactFactory(tenant=seeded_tenant, first_name="Summitonly")
    with tenant_context(copy.tenant.pk):
        mine = ContactFactory(tenant=copy.tenant, first_name="Copyonly")
    seen_by_visitor = api.as_(copy.owner).get("/api/contacts/").content.decode()
    seen_by_summit = api.as_(ff).get("/api/contacts/").content.decode()
    assert "Copyonly" in seen_by_visitor and "Summitonly" not in seen_by_visitor
    assert "Summitonly" in seen_by_summit and "Copyonly" not in seen_by_summit
    assert api.as_(copy.owner).get(f"/api/contacts/{theirs.pk}/").status_code == 404
    assert api.as_(ff).get(f"/api/contacts/{mine.pk}/").status_code == 404


# ============================================== being set up, and ended

@pytest.mark.django_db
def test_while_it_is_set_up_only_me_answers(copy, api):
    from apps.tenancy.models import DemoVisitor

    DemoVisitor.objects.filter(pk=copy.visitor.pk).update(
        state="setting_up", setup_started_at=timezone.now())
    refused = api.as_(copy.owner).get("/api/contacts/")
    assert refused.status_code == 409 and refused.json()["demo_setting_up"]
    me = api.as_(copy.owner).get("/api/me").json()
    assert me["demo_visitor"]["state"] == "setting_up"
    # Stuck past the limit (a redeploy killed it): said so, not "being set up".
    DemoVisitor.objects.filter(pk=copy.visitor.pk).update(
        setup_started_at=timezone.now() - timedelta(hours=1))
    stuck = api.as_(copy.owner).get("/api/contacts/").json()
    assert "did not finish" in stuck["detail"]
    assert api.as_(copy.owner).get("/api/me").json()["demo_visitor"]["state"] == "failed"


@pytest.mark.django_db
def test_once_it_has_ended_it_is_read_only(copy, api):
    from apps.tenancy.models import DemoVisitor

    DemoVisitor.objects.filter(pk=copy.visitor.pk).update(
        expires_at=timezone.now() - timedelta(days=1))
    client = api.as_(copy.owner)
    assert client.get("/api/contacts/").status_code == 200
    refused = client.post("/api/contacts/", json.dumps({"first_name": "New"}),
                          content_type="application/json")
    assert refused.status_code == 403 and refused.json()["demo_read_only"]
    assert "Nothing in it can be changed" in refused.json()["detail"]
    me = client.get("/api/me").json()["demo_visitor"]
    assert me["read_only"] and me["ai_stop"]


# ======================================================================= AI

@pytest.fixture
def claude_key(monkeypatch):
    from apps.tenancy import claude

    keys = []

    def client(key):
        keys.append(key)
        return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(
            create=lambda **kw: SimpleNamespace(
                usage=SimpleNamespace(input_tokens=1000, output_tokens=100,
                                      server_tool_use=None),
                model="claude-opus-4-1", stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text="Drafted.")]))))
    monkeypatch.setattr(claude, "_client", client)
    return keys


@pytest.mark.django_db
def test_a_copy_spends_the_demos_key_and_stops_hard(copy, settings, claude_key, api):
    from apps.tenancy import claude
    from apps.tenancy.models import AiCall

    settings.DEMO_ANTHROPIC_API_KEY = "sk-ant-demo-key"
    with tenant_context(copy.tenant.pk):
        assert claude.complete(tenant=copy.tenant, purpose="test", system="s",
                               user_text="u") == "Drafted."
    assert claude_key == ["sk-ant-demo-key"]
    assert claude.key_source(copy.tenant) == "demo"

    # $2 today: stopped, and nothing is sent.
    AiCall.all_objects.create(tenant=copy.tenant, purpose="test", model="m",
                              cost_usd=Decimal("2.00"), succeeded=True)
    with tenant_context(copy.tenant.pk), pytest.raises(claude.ClaudeStopped) as stopped:
        claude.complete(tenant=copy.tenant, purpose="test", system="s", user_text="u")
    assert "for today ($2.00)" in str(stopped.value)
    assert len(claude_key) == 1
    me = api.as_(copy.owner).get("/api/me").json()["demo_visitor"]
    assert "for today" in me["ai_stop"]

    # $10 in all, over earlier days: stopped for good.
    AiCall.all_objects.all().update(created_at=timezone.now() - timedelta(days=3))
    AiCall.all_objects.create(tenant=copy.tenant, purpose="test", model="m",
                              cost_usd=Decimal("9.00"), succeeded=True)
    AiCall.all_objects.all().update(created_at=timezone.now() - timedelta(days=3))
    with tenant_context(copy.tenant.pk), pytest.raises(claude.ClaudeStopped) as stopped:
        claude.complete(tenant=copy.tenant, purpose="test", system="s", user_text="u")
    assert "$10.00 in all" in str(stopped.value)


@pytest.mark.django_db
def test_with_no_key_of_its_own_a_copy_uses_the_demo_practices(copy, settings, claude_key,
                                                               seeded_tenant):
    from apps.crm.services.secrets import write_secret
    from apps.tenancy import claude
    from apps.tenancy.demo import cast

    settings.DEMO_ANTHROPIC_API_KEY = ""
    assert claude.key_source(copy.tenant) is None
    seeded_tenant.slug = cast.SLUG
    seeded_tenant.save()
    write_secret(tenant=seeded_tenant, kind="anthropic_api_key", value="sk-ant-summits-own")
    with tenant_context(copy.tenant.pk):
        claude.complete(tenant=copy.tenant, purpose="test", system="s", user_text="u")
    assert claude_key == ["sk-ant-summits-own"]


# ===================================================================== mail

@pytest.fixture
def demo_connection(seeded_tenant, platform_owner, demo):
    """The demo's one send-only connection, held by Summit."""
    from apps.crm.services.secrets import write_secret

    from .factories import GmailConnectionFactory

    secret = write_secret(tenant=seeded_tenant, kind="gmail_refresh", value="refresh-token",
                          user=platform_owner.user)
    return GmailConnectionFactory(tenant=seeded_tenant, user=platform_owner.user,
                                  email_address="owner@getexecutivesnow.invalid",
                                  send_as_address=demo.DEMO_MAIL_FROM,
                                  send_as_verified_at=timezone.now(), secret=secret)


@pytest.mark.django_db
def test_everything_a_copy_sends_goes_to_its_visitor(copy, demo_connection, monkeypatch):
    from apps.crm.services import outbox, transport

    sent = []

    class Capture:
        def send(self, **kw):
            sent.append(kw)
            return {"provider": "gmail", "provider_message_id": "x"}
    monkeypatch.setattr(transport, "get_transport", lambda name=None: Capture())
    with tenant_context(copy.tenant.pk):
        contact = ContactFactory(tenant=copy.tenant, first_name="Bruce")
        outbox.create_message(tenant=copy.tenant, producer="magic_link",
                              to_address="bruce.wayne+tag@wayneindustries.example",
                              to_contact=contact, subject="Your digest", body_text="Hello")
    assert len(sent) == 1
    assert sent[0]["to_address"] == VISITOR
    assert sent[0]["from_address"] == copy.visitor.tenant.from_address
    assert "originally addressed to" in sent[0]["body_text"]
    # Summit's own mail still goes to the demo's one redirect.
    assert outbox._demo_recipient(demo_connection.tenant) == "redirect@demo-inbox.invalid"
    assert transport.sending_connection_for(copy.tenant) == demo_connection


@pytest.mark.django_db
def test_the_transport_refuses_any_other_address_for_a_copy(copy, demo_connection):
    from apps.crm.services import transport

    with pytest.raises(transport.TransportUnavailable, match="only to its redirect"):
        transport.GmailTransport().send(
            tenant=copy.tenant, to_address="redirect@demo-inbox.invalid", subject="s",
            body_text="b", thread=None)


@pytest.mark.django_db
def test_the_invitation_goes_to_the_visitor_with_the_link_unstored(copy, demo_connection,
                                                                   monkeypatch):
    from apps.crm.models import OutboxMessage
    from apps.crm.services import transport
    from apps.tenancy.demo import visitors

    sent = []

    class Capture:
        def send(self, **kw):
            sent.append(kw)
            return {"provider": "gmail", "provider_message_id": "x"}
    monkeypatch.setattr(transport, "get_transport", lambda name=None: Capture())
    visitors.send_invitation(copy.visitor)
    copy.visitor.refresh_from_db()
    assert copy.visitor.invited_at is not None
    assert sent[0]["to_address"] == VISITOR
    # Already for the person it goes to: no "originally addressed to" banner.
    assert "originally addressed" not in sent[0]["body_text"]
    assert "/auth/magic/" in sent[0]["body_text"]
    stored = OutboxMessage.all_objects.get(tenant=copy.tenant)
    assert stored.subject == "Your own demo of Execs NOW HQ"
    assert "/auth/magic/" not in stored.body_text and "private copy" in stored.body_text


# ======================================== connections, agreement, the list

@pytest.mark.django_db
def test_a_copy_connects_no_gmail(copy, api):
    started = api.as_(copy.owner).post("/api/gmail-connection/start/")
    assert started.status_code == 409 and "connects no Gmail or Drive" in started.json()["detail"]


@pytest.mark.django_db
def test_a_visitor_is_not_asked_to_accept_the_beta_agreement(copy, api, settings):
    settings.BETA_AGREEMENT_REQUIRED = True
    me = api.as_(copy.owner).get("/api/me").json()
    assert me["agreement_required"] is False


@pytest.mark.django_db
def test_copies_are_not_on_the_practices_list(copy, platform_owner, api):
    rows = practices_area(api, platform_owner).get("/api/platform/practices").json()
    assert str(copy.tenant.pk) not in {r["id"] for r in rows}


# =================================================================== sweep

@pytest.mark.django_db
def test_the_sweep_deletes_a_copy_a_week_after_it_ends_and_not_before(copy):
    from apps.accounts.models import User
    from apps.tenancy.demo import visitors
    from apps.tenancy.models import DemoVisitor, Tenant

    DemoVisitor.objects.filter(pk=copy.visitor.pk).update(
        expires_at=timezone.now() - timedelta(days=6))
    assert visitors.sweep() == {"deleted": 0}
    DemoVisitor.objects.filter(pk=copy.visitor.pk).update(
        expires_at=timezone.now() - timedelta(days=8))
    assert visitors.sweep() == {"deleted": 1}
    assert not Tenant.objects.filter(pk=copy.tenant.pk).exists()
    assert not User.objects.filter(email=VISITOR).exists()


@pytest.mark.django_db
def test_an_invitation_that_cannot_reach_the_visitor_is_not_marked_sent(copy, platform_owner,
                                                                        api):
    """No working connection on the demo: nothing is marked sent, and the list
    says why, with the way to send it once it is fixed."""
    from apps.tenancy.demo import visitors

    why = visitors.send_invitation(copy.visitor)
    copy.visitor.refresh_from_db()
    assert copy.visitor.invited_at is None
    assert "no working Gmail connection" in why and copy.visitor.state_error == why
    client = practices_area(api, platform_owner)
    row = client.get("/api/platform/demo-visitors").json()[0]
    assert row["invited_at"] is None and "no working Gmail connection" in row["state_error"]
    again = client.post(f"/api/platform/demo-visitors/{copy.visitor.pk}/invite")
    assert again.status_code == 409 and "no working Gmail connection" in again.json()["detail"]


@pytest.mark.django_db
def test_the_platform_owner_sends_the_invitation_again(copy, platform_owner, api,
                                                       demo_connection, monkeypatch):
    from apps.crm.services import transport

    monkeypatch.setattr(transport, "get_transport", lambda name=None: SimpleNamespace(
        send=lambda **kw: {"provider": "gmail", "provider_message_id": "x"}))
    sent = practices_area(api, platform_owner).post(
        f"/api/platform/demo-visitors/{copy.visitor.pk}/invite")
    assert sent.status_code == 200 and sent.json()["invited_at"]
    assert sent.json()["state_error"] == ""


@pytest.mark.django_db
def test_a_copy_is_not_asked_for_gmail_or_a_key_nor_told_its_unattended_ai_is_paused(copy):
    from apps.tenancy import ai_guard, getting_started

    keys = [item["key"] for item in getting_started.items(copy.tenant)]
    assert "gmail" not in keys and "anthropic" not in keys and "branding" in keys
    copy.tenant.ai_unattended_daily_cap_usd = Decimal("0")
    copy.tenant.save()
    assert ai_guard.status(copy.tenant, financial=True)["paused"] is False


# ===================================================== the visitor's one tick

@pytest.mark.django_db
def test_nothing_else_until_the_visitor_ticks_and_a_reset_does_not_ask_again(
        copy, api, launched, django_capture_on_commit_callbacks):
    from apps.platform import agreement
    from apps.tenancy.demo import visitors
    from apps.tenancy.models import AuditEvent, DemoVisitor

    DemoVisitor.objects.filter(pk=copy.visitor.pk).update(agreed_at=None)
    client = api.as_(copy.owner)
    me = client.get("/api/me").json()["demo_visitor"]
    assert me["agreement_required"] and me["days"] == 30
    refused = client.get("/api/contacts/")
    assert refused.status_code == 403 and refused.json()["demo_agreement_required"]
    assert client.post("/api/demo/reset").status_code == 403
    # The agreement itself can be read before ticking.
    assert client.get("/api/agreement").status_code == 200
    stale = client.post("/api/demo/agree", json.dumps({"version": "v0"}),
                        content_type="application/json")
    assert stale.status_code == 409
    before = timezone.now()
    ticked = client.post("/api/demo/agree", json.dumps({"version": agreement.VERSION}),
                         content_type="application/json")
    assert ticked.status_code == 200
    assert ticked.json()["demo_visitor"]["agreement_required"] is False
    copy.visitor.refresh_from_db()
    assert copy.visitor.agreed_at >= before and copy.visitor.agreed_version == agreement.VERSION
    assert AuditEvent.all_objects.filter(verb="demo_visitor.agreed").count() == 1
    assert client.get("/api/contacts/").status_code == 200
    # A reset empties the copy, not its record: no second question.
    with django_capture_on_commit_callbacks(execute=True):
        assert client.post("/api/demo/reset").status_code == 200
    agreed = copy.visitor.agreed_at
    visitors.empty_practice(copy.tenant, keep_user_email=copy.visitor.email, keep_ai_calls=True)
    copy.visitor.refresh_from_db()
    assert copy.visitor.agreed_at == agreed


@pytest.mark.django_db
def test_only_the_visitor_ticks_and_only_in_a_copy(copy, api, ff):
    from apps.platform import agreement
    from apps.tenancy.models import DemoVisitor

    DemoVisitor.objects.filter(pk=copy.visitor.pk).update(agreed_at=None)
    body = json.dumps({"version": agreement.VERSION})
    assert api.as_(ff).post("/api/demo/agree", body,
                            content_type="application/json").status_code == 404
    assistant = _member(copy.tenant, "VA")
    assert api.as_(assistant).post("/api/demo/agree", body,
                                   content_type="application/json").status_code == 403
