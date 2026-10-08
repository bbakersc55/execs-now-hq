"""Portal invitations (2026-10-07): a week to use one, a way to send another,
and a way back in for whoever lets one run out.

- A grant sends an **invitation**, valid for 7 days. A link someone asks for on
  the sign-in page still lasts 20 minutes.
- "Resend invitation" sends a fresh one to a person who already has access, so
  revoking and granting again is never the way to get someone a link.
- A dead link's page, and the invitation email, both point at the sign-in page
  and its "Email me a sign-in link".
"""

from __future__ import annotations

import json
import re
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import (
    INVITATION_TTL, MAGIC_LINK_TTL, MagicLinkPurpose, MagicLinkToken,
)
from apps.tenancy.models import AuditEvent, Membership

from . import registry_config  # noqa: F401
from .factories import (
    ClientAssignmentFactory, ClientCompanyFactory, ContactEmailFactory, ContactFactory,
    MembershipFactory,
)

SIGN_IN_PAGE = "http://localhost:5200/"


def post(client, url, data=None):
    return client.post(url, json.dumps(data or {}), content_type="application/json")


def a_contact(tenant, company, first="Dana", email=None):
    contact = ContactFactory(tenant=tenant, first_name=first, last_name="Okafor",
                             company=company)
    ContactEmailFactory(tenant=tenant, contact=contact, is_primary=True,
                        address=email or f"{first.lower()}@northwind.invalid")
    return contact


def link_in(email) -> str:
    """The raw token in a delivered email."""
    return re.search(r"/auth/magic/([\w-]+)", email.body).group(1)


def html_of(email) -> str:
    return next(body for body, kind in email.alternatives if kind == "text/html")


@pytest.fixture
def company(seeded_tenant):
    return ClientCompanyFactory(tenant=seeded_tenant, name="Northwind Foods", seat_count=3)


@pytest.fixture
def invited(seeded_tenant, ff, api, company, dev_outbox, in_tenant_a):
    """Dana, granted access through the API, with her invitation in the outbox."""
    contact = a_contact(seeded_tenant, company, "Dana")
    made = post(api.as_(ff), "/api/portal-access/", {"contact": str(contact.pk)})
    assert made.status_code == 201, made.content
    return Membership.all_objects.get(pk=made.json()["id"])


def expire(token_filter):
    MagicLinkToken.all_objects.filter(**token_filter).update(
        expires_at=timezone.now() - timedelta(seconds=1))


# ------------------------------------------------------------------- expiry

@pytest.mark.django_db
def test_an_invitation_lasts_seven_days_and_a_requested_link_twenty_minutes(
    invited, seeded_tenant, client, dev_outbox
):
    assert INVITATION_TTL == timedelta(days=7) and MAGIC_LINK_TTL == timedelta(minutes=20)

    invitation = MagicLinkToken.all_objects.get(user=invited.user)
    assert invitation.purpose == MagicLinkPurpose.INVITE
    assert timedelta(days=7) - timedelta(minutes=1) \
        < invitation.expires_at - timezone.now() <= timedelta(days=7)

    client.post("/auth/magic/request", {"email": invited.user.email})
    asked_for = MagicLinkToken.all_objects.get(user=invited.user,
                                               purpose=MagicLinkPurpose.SIGNIN)
    assert timedelta(minutes=19) < asked_for.expires_at - timezone.now() <= timedelta(minutes=20)


@pytest.mark.django_db
def test_an_invitation_still_signs_in_on_its_sixth_day_and_not_after_its_seventh(
    invited, dev_outbox
):
    raw = link_in(dev_outbox[-1])
    token = MagicLinkToken.all_objects.get(user=invited.user)

    token.expires_at = timezone.now() + timedelta(days=1)       # six days in
    token.save(update_fields=["expires_at"])
    assert Client().get(f"/auth/magic/{raw}").context["valid"] is True

    expire({"pk": token.pk})
    dead = Client().post(f"/auth/magic/{raw}")
    assert dead.status_code == 400
    assert "_auth_user_id" not in dead.wsgi_request.session


@pytest.mark.django_db
def test_the_invitation_email_says_seven_days_and_links_to_the_sign_in_page(
    invited, dev_outbox
):
    email = dev_outbox[-1]
    html = html_of(email)
    assert email.subject == "Your invitation to Tenant A"
    for body in (html, email.body):
        assert "valid for 7 days" in body and "20 minutes" not in body
        assert "Email me a sign-in link" in body
    assert f'href="{SIGN_IN_PAGE}"' in html
    assert f"Sign-in page: {SIGN_IN_PAGE}" in email.body


@pytest.mark.django_db
def test_the_stored_copy_of_an_invitation_holds_no_link(invited, in_tenant_a):
    from apps.crm.models import OutboxMessage

    row = OutboxMessage.all_objects.get(producer="magic_link", to_address=invited.user.email)
    for stored in (row.body_html, row.body_text):
        assert "/auth/magic/" not in stored, "A stored copy held a working credential."
    assert "not stored" in row.body_html


@pytest.mark.django_db
def test_signing_in_ends_every_other_sign_in_link_the_person_holds(
    invited, client, dev_outbox
):
    """A week-long invitation left in an inbox must not outlive the sign-in."""
    invitation = link_in(dev_outbox[-1])
    client.post("/auth/magic/request", {"email": invited.user.email})
    asked_for = link_in(dev_outbox[-1])
    assert asked_for != invitation

    assert Client().post(f"/auth/magic/{asked_for}").status_code == 200
    assert Client().post(f"/auth/magic/{invitation}").status_code == 400


# ------------------------------------------------------------------- resend

@pytest.mark.django_db
def test_resend_sends_a_fresh_link_ends_the_old_one_and_changes_nothing_else(
    invited, ff, api, company, dev_outbox, in_tenant_a
):
    first = link_in(dev_outbox[-1])
    sent_before = len(dev_outbox)

    again = post(api.as_(ff), f"/api/portal-access/{invited.pk}/resend/")
    assert again.status_code == 200, again.content
    body = again.json()
    assert body["sent"] is True and body["id"] == str(invited.pk)
    assert body["invitation_expires_at"] is not None

    assert len(dev_outbox) == sent_before + 1
    second = link_in(dev_outbox[-1])
    assert dev_outbox[-1].to == [invited.user.email]
    assert dev_outbox[-1].subject == "Your invitation to Tenant A"
    assert second != first

    assert Client().post(f"/auth/magic/{first}").status_code == 400, "The old link still worked."
    signed_in = Client()
    assert signed_in.post(f"/auth/magic/{second}").status_code == 200
    assert signed_in.get("/api/me").json()["role"] == invited.role

    # Not a revoke and a grant: the same row, the same seat, nothing revoked.
    invited.refresh_from_db()
    assert invited.revoked_at is None
    assert Membership.all_objects.filter(contact=invited.contact).count() == 1
    assert company.seats_in_use == 1
    assert not AuditEvent.all_objects.filter(verb="portal.access_revoked").exists()


@pytest.mark.django_db
def test_resend_is_audited_with_who_to_whom_and_until_when(invited, ff, api, in_tenant_a):
    post(api.as_(ff), f"/api/portal-access/{invited.pk}/resend/")

    event = AuditEvent.all_objects.get(verb="portal.invitation_resent")
    assert event.actor_id == ff.user_id
    assert event.target_type == "membership" and str(event.target_id) == str(invited.pk)
    assert event.payload["to"] == invited.user.email and event.payload["sent"] is True
    assert event.payload["expires_at"]
    assert "/auth/magic/" not in json.dumps(event.payload)


@pytest.mark.django_db
def test_resend_shows_in_the_activity_log_in_words(invited, ff, api, in_tenant_a):
    post(api.as_(ff), f"/api/portal-access/{invited.pk}/resend/")

    rows = api.as_(ff).get("/api/activity/").json()
    row = next(r for r in rows if r["kind"] == "portal.invitation_resent")
    assert row["text"] == "sent Dana Okafor a new portal invitation"
    assert row["category"] == "portal" and row["company"]["name"] == "Northwind Foods"


@pytest.mark.django_db
def test_resend_works_for_an_invitation_that_already_expired(
    invited, ff, api, dev_outbox, in_tenant_a
):
    expire({"user": invited.user})
    row = api.as_(ff).get(
        f"/api/portal-access/?company={invited.client_company_id}").json()["people"][0]
    assert row["signed_in"] is False
    assert row["invitation_expires_at"] < timezone.now().isoformat()

    assert post(api.as_(ff), f"/api/portal-access/{invited.pk}/resend/").status_code == 200
    assert Client().post(f"/auth/magic/{link_in(dev_outbox[-1])}").status_code == 200

    row = api.as_(ff).get(
        f"/api/portal-access/?company={invited.client_company_id}").json()["people"][0]
    assert row["signed_in"] is True and row["invitation_expires_at"] is None


@pytest.mark.django_db
def test_resend_says_so_when_the_email_could_not_be_sent(
    invited, ff, api, monkeypatch, in_tenant_a
):
    from apps.crm.services import outbox
    from apps.crm.services.transport import TransportUnavailable

    def refuse(**kwargs):
        raise TransportUnavailable("Gmail is not connected.")

    monkeypatch.setattr(outbox, "create_message", refuse)
    again = post(api.as_(ff), f"/api/portal-access/{invited.pk}/resend/")
    assert again.status_code == 200 and again.json()["sent"] is False
    assert AuditEvent.all_objects.get(verb="portal.invitation_resent").payload["sent"] is False
    assert AuditEvent.all_objects.filter(verb="email.failed").exists()


# ------------------------------------------- resend: roles, companies, tenants

@pytest.mark.django_db
@pytest.mark.parametrize("role,expected", [("FF", 200), ("CF", 200), ("VA", 403),
                                           ("FCC", 403), ("ECC", 403)])
def test_only_the_practice_owner_and_an_assigned_associate_resend(
    role, expected, invited, seeded_tenant, api, company, dev_outbox, in_tenant_a
):
    member = MembershipFactory(
        tenant=seeded_tenant, role=role,
        client_company=company if role in ("FCC", "ECC") else None)
    if role == "CF":
        ClientAssignmentFactory(tenant=seeded_tenant, user=member.user, company=company)
    sent_before = len(dev_outbox)

    response = post(api.as_(member), f"/api/portal-access/{invited.pk}/resend/")

    assert response.status_code == expected
    assert len(dev_outbox) == sent_before + (1 if expected == 200 else 0)


@pytest.mark.django_db
def test_an_associate_cannot_resend_at_a_company_they_are_not_assigned(
    invited, cf, api, dev_outbox, in_tenant_a
):
    sent_before = len(dev_outbox)
    assert post(api.as_(cf), f"/api/portal-access/{invited.pk}/resend/").status_code == 404
    assert len(dev_outbox) == sent_before


@pytest.mark.django_db
def test_another_practice_cannot_resend_or_even_find_the_row(
    invited, tenant_b, api, dev_outbox
):
    their_owner = MembershipFactory(tenant=tenant_b, role="FF")
    sent_before = len(dev_outbox)
    link_before = MagicLinkToken.all_objects.get(user=invited.user)

    assert post(api.as_(their_owner),
                f"/api/portal-access/{invited.pk}/resend/").status_code == 404
    assert len(dev_outbox) == sent_before
    link_before.refresh_from_db()
    assert link_before.used_at is None, "Another practice ended this person's invitation."
    assert not AuditEvent.all_objects.filter(verb="portal.invitation_resent").exists()


@pytest.mark.django_db
def test_a_revoked_person_cannot_be_sent_an_invitation(invited, ff, api, dev_outbox,
                                                       in_tenant_a):
    api.as_(ff).delete(f"/api/portal-access/{invited.pk}/")
    sent_before = len(dev_outbox)
    assert post(api.as_(ff), f"/api/portal-access/{invited.pk}/resend/").status_code == 404
    assert len(dev_outbox) == sent_before


# ----------------------------------------------------- the self-serve path

@pytest.mark.django_db
def test_an_expired_invitation_page_says_so_and_links_to_the_sign_in_page(
    invited, dev_outbox
):
    raw = link_in(dev_outbox[-1])
    expire({"user": invited.user})

    page = Client().get(f"/auth/magic/{raw}")
    html = page.content.decode()
    assert page.status_code == 200 and page.context["valid"] is False
    assert "This invitation has expired" in html and "7 days" in html
    assert f'href="{SIGN_IN_PAGE}"' in html
    assert "Email me a sign-in link" in html
    assert "<form" not in html, "A dead link still offered its Sign in button."
    # It is still the practice's page: an expired link is no reason to lose the brand.
    assert "Tenant A" in html


@pytest.mark.django_db
def test_an_expired_sign_in_link_and_an_unknown_one_get_the_same_way_out(
    invited, client, dev_outbox
):
    client.post("/auth/magic/request", {"email": invited.user.email})
    raw = link_in(dev_outbox[-1])
    expire({"user": invited.user, "purpose": MagicLinkPurpose.SIGNIN})

    for token in (raw, "never-issued"):
        html = Client().get(f"/auth/magic/{token}").content.decode()
        assert "This link has expired" in html and "20 minutes" in html
        assert "invitation" not in html.lower()
        assert f'href="{SIGN_IN_PAGE}"' in html and "Email me a sign-in link" in html


@pytest.mark.django_db
def test_an_expired_invitation_is_recovered_from_the_sign_in_page_alone(
    invited, client, dev_outbox
):
    """The whole path, with nobody at the practice involved."""
    expired = link_in(dev_outbox[-1])
    expire({"user": invited.user})
    assert Client().post(f"/auth/magic/{expired}").status_code == 400

    # What the sign-in page's "Email me a sign-in link" posts.
    asked = client.post("/auth/magic/request", {"email": invited.user.email})
    assert asked.status_code == 200
    fresh = link_in(dev_outbox[-1])
    assert dev_outbox[-1].to == [invited.user.email] and fresh != expired

    theirs = Client()
    assert theirs.post(f"/auth/magic/{fresh}").status_code == 200
    me = theirs.get("/api/me").json()
    assert me["role"] == invited.role and me["client_company"] == str(invited.client_company_id)


@pytest.mark.django_db
def test_the_self_serve_path_is_closed_to_someone_whose_access_was_revoked(
    invited, ff, api, client, dev_outbox, in_tenant_a
):
    api.as_(ff).delete(f"/api/portal-access/{invited.pk}/")
    sent_before = len(dev_outbox)
    assert client.post("/auth/magic/request", {"email": invited.user.email}).status_code == 200
    assert len(dev_outbox) == sent_before, "A revoked person was sent a sign-in link."
