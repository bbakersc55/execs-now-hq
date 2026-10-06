"""P2: the invitation, the beta agreement, and the Getting started checklist."""

from __future__ import annotations

import hashlib
import json

import pytest

from apps.crm.models import OutboxMessage
from apps.platform import agreement, provisioning
from apps.platform.models import AgreementAcceptance
from apps.tenancy.middleware import AREA_PLATFORM, AREA_SESSION_KEY
from apps.tenancy.models import AuditEvent, Membership

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import (
    ClientCompanyFactory, ContactFactory, GmailConnectionFactory, StrategyTemplateFactory,
    TenantSecretFactory,
)

NEW = {"legal_name": "Blue Sky Business Consulting LLC",
       "display_name": "Blue Sky Business Consulting",
       "domain": "blueskybizconsulting.com", "owner_email": "owner@bluesky.invalid"}


@pytest.fixture(autouse=True)
def _agreement_gate_on(settings):
    settings.BETA_AGREEMENT_REQUIRED = True


@pytest.fixture
def platform_owner(seeded_tenant):
    owner = _member(seeded_tenant, "FF")
    owner.user.is_platform_owner = True
    owner.user.full_name = "Bryan Baker"
    owner.user.save()
    return owner


@pytest.fixture
def blue_sky(platform_owner):
    return provisioning.provision_practice(**NEW, actor=platform_owner.user)


def in_practices(api, membership):
    client = api.as_(membership)
    session = client.session
    session[AREA_SESSION_KEY] = AREA_PLATFORM
    session.save()
    return client


# ------------------------------------------------------------------ the invitation

@pytest.mark.django_db
def test_no_invitation_while_the_external_client_is_missing(api, platform_owner, blue_sky,
                                                            settings, dev_outbox):
    settings.GOOGLE_OAUTH_EXTERNAL_CLIENT_ID = ""
    response = in_practices(api, platform_owner).post(
        f"/api/platform/practices/{blue_sky.pk}/invite")
    assert response.status_code == 409 and "not configured" in response.json()["detail"]
    assert not dev_outbox


@pytest.mark.django_db
def test_the_invitation_goes_from_the_platform_owners_practice(api, platform_owner, blue_sky,
                                                               settings, dev_outbox,
                                                               seeded_tenant, monkeypatch):
    settings.GOOGLE_OAUTH_EXTERNAL_CLIENT_ID = "external-id"
    settings.GOOGLE_OAUTH_EXTERNAL_CLIENT_SECRET = "e-s"
    sent = []
    monkeypatch.setattr("apps.crm.services.outbox._deliver",
                        lambda message, **kw: sent.append(message), raising=False)
    response = in_practices(api, platform_owner).post(
        f"/api/platform/practices/{blue_sky.pk}/invite")
    assert response.status_code == 200, response.content
    message = OutboxMessage.all_objects.get(producer="practice_invite")
    assert message.tenant_id == seeded_tenant.pk, "sent from Executives Now (D2)"
    assert message.to_address == NEW["owner_email"]
    assert "Sign in with Google" in message.body_text and NEW["owner_email"] in message.body_text
    # It sends them to a heading on the sign-in page, so the two must agree
    # (beta feedback, 2026-10-05: "Staff" read as the client's staff).
    from pathlib import Path

    assert "Under Practice sign-in, enter" in message.body_text
    assert "Under Staff" not in message.body_text
    page = Path(settings.BASE_DIR, "frontend/src/components/SignedOut.tsx").read_text()
    assert ">Practice sign-in</h3>" in page
    assert AuditEvent.all_objects.filter(tenant=blue_sky, verb="practice.invited").exists()
    # Nothing about Blue Sky's own data travels; it has none yet, and the
    # invitation names only the practice and the owner's address.
    assert not OutboxMessage.all_objects.filter(tenant=blue_sky).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FF", "CF", "VA"])
def test_only_the_platform_owner_invites(api, seeded_tenant, blue_sky, role):
    member = _member(seeded_tenant, role)
    assert in_practices(api, member).post(
        f"/api/platform/practices/{blue_sky.pk}/invite").status_code == 403


@pytest.mark.django_db
def test_an_archived_practice_is_not_invited(api, platform_owner, blue_sky):
    provisioning.archive(blue_sky, actor=platform_owner.user)
    assert in_practices(api, platform_owner).post(
        f"/api/platform/practices/{blue_sky.pk}/invite").status_code == 409


# ------------------------------------------------------------------ the agreement

@pytest.fixture
def blue_sky_owner(blue_sky):
    return Membership.all_objects.get(tenant=blue_sky, role="FF")


@pytest.mark.django_db
def test_a_practice_owner_can_use_nothing_until_they_accept(api, blue_sky_owner):
    client = api.as_(blue_sky_owner)
    assert client.get("/api/me").json()["agreement_required"] is True
    blocked = client.get("/api/contacts/")
    assert blocked.status_code == 403 and blocked.json()["agreement_required"] is True

    terms = client.get("/api/agreement").json()
    assert "Whoever operates the servers can technically read the database" in terms["text"]
    assert terms["sha256"] == hashlib.sha256(agreement.PATH.read_text().encode()).hexdigest()

    wrong = client.post("/api/agreement", json.dumps({"version": "v1", "sha256": "0" * 64}),
                        content_type="application/json")
    assert wrong.status_code == 409
    assert client.get("/api/contacts/").status_code == 403

    ok = client.post("/api/agreement", json.dumps({"version": terms["version"],
                                                    "sha256": terms["sha256"]}),
                     content_type="application/json")
    assert ok.status_code == 200
    row = AgreementAcceptance.all_objects.get(user=blue_sky_owner.user)
    assert (row.version, row.text_sha256) == ("v1", terms["sha256"])
    assert row.tenant_id == blue_sky_owner.tenant_id
    assert client.get("/api/contacts/").status_code == 200
    assert client.get("/api/me").json()["agreement_required"] is False


@pytest.mark.django_db
def test_the_platform_owner_and_staff_are_not_asked(api, platform_owner, blue_sky):
    assert api.as_(platform_owner).get("/api/me").json()["agreement_required"] is False
    associate = _member(blue_sky, "CF")
    assert api.as_(associate).get("/api/me").json()["agreement_required"] is False
    assert api.as_(associate).get("/api/contacts/").status_code == 200


@pytest.mark.django_db
def test_a_new_version_asks_again(api, blue_sky_owner, monkeypatch):
    terms = agreement.current()
    AgreementAcceptance.all_objects.create(tenant=blue_sky_owner.tenant,
                                           user=blue_sky_owner.user, version="v1",
                                           text_sha256=terms["sha256"])
    assert api.as_(blue_sky_owner).get("/api/me").json()["agreement_required"] is False
    monkeypatch.setattr(agreement, "VERSION", "v2")
    assert api.as_(blue_sky_owner).get("/api/me").json()["agreement_required"] is True


# ------------------------------------------------------------------ the checklist

@pytest.mark.django_db
def test_a_new_practice_starts_with_everything_open(api, blue_sky_owner):
    AgreementAcceptance.all_objects.create(tenant=blue_sky_owner.tenant,
                                           user=blue_sky_owner.user, version="v1",
                                           text_sha256=agreement.current()["sha256"])
    items = api.as_(blue_sky_owner).get("/api/getting-started").json()
    assert [i["key"] for i in items] == ["branding", "gmail", "anthropic", "contacts",
                                         "staff", "client", "template"]
    assert not any(i["done"] for i in items)


@pytest.mark.django_db
def test_each_item_ticks_from_the_practices_own_data(api, blue_sky_owner, seeded_tenant):
    tenant = blue_sky_owner.tenant
    AgreementAcceptance.all_objects.create(tenant=tenant, user=blue_sky_owner.user,
                                           version="v1",
                                           text_sha256=agreement.current()["sha256"])
    # Another practice's data never ticks anything here.
    ContactFactory(tenant=seeded_tenant)
    ClientCompanyFactory(tenant=seeded_tenant)
    StrategyTemplateFactory(tenant=seeded_tenant)
    done = lambda: {i["key"] for i in api.as_(blue_sky_owner)  # noqa: E731
                    .get("/api/getting-started").json() if i["done"]}
    assert done() == set()

    from django.utils import timezone

    tenant.branding_updated_at = timezone.now()
    tenant.save()
    GmailConnectionFactory(tenant=tenant, send_as_verified_at=timezone.now())
    TenantSecretFactory(tenant=tenant)
    ContactFactory(tenant=tenant)
    _member(tenant, "VA")
    ClientCompanyFactory(tenant=tenant)
    StrategyTemplateFactory(tenant=tenant)
    assert done() == {"branding", "gmail", "anthropic", "contacts", "staff", "client",
                      "template"}


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["CF", "VA", "FCC"])
def test_only_the_practice_owner_has_a_checklist(api, blue_sky, role):
    company = ClientCompanyFactory(tenant=blue_sky) if role == "FCC" else None
    member = _member(blue_sky, role, company)
    assert api.as_(member).get("/api/getting-started").status_code == 403


@pytest.mark.django_db
def test_a_broken_sender_mailbox_is_said_plainly(api, platform_owner, blue_sky, settings,
                                                 monkeypatch):
    from apps.crm.services.transport import TransportUnavailable

    settings.GOOGLE_OAUTH_EXTERNAL_CLIENT_ID = "external-id"
    settings.GOOGLE_OAUTH_EXTERNAL_CLIENT_SECRET = "e-s"

    def refuse(message, **kw):
        raise TransportUnavailable("No Gmail account is connected for this practice.")

    monkeypatch.setattr("apps.crm.services.outbox._deliver", refuse)
    response = in_practices(api, platform_owner).post(
        f"/api/platform/practices/{blue_sky.pk}/invite")
    assert response.status_code == 409
    assert "No Gmail account is connected" in response.json()["detail"]
