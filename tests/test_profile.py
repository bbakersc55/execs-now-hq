"""Profile (docs/ui3_top_bar_settings_profile.md §5): a person changes their
own name, and only their own. Not the sign-in email, and not from inside an
acting-as session."""

from __future__ import annotations

import json

import pytest

from apps.accounts.models import User

from . import registry_config  # noqa: F401
from .factories import ClientCompanyFactory, MembershipFactory

URL = "/api/me/profile"


def patch(client, data):
    return client.patch(URL, json.dumps(data), content_type="application/json")


def member(tenant, role, **user):
    company = ClientCompanyFactory(tenant=tenant) if role in ("FCC", "ECC") else None
    membership = MembershipFactory(tenant=tenant, role=role, client_company=company)
    if user:
        User.objects.filter(pk=membership.user_id).update(**user)
        membership.user.refresh_from_db()
    return membership


@pytest.mark.django_db
@pytest.mark.parametrize("role,label", [
    ("FF", "Practice owner"), ("CF", "Associate"), ("VA", "Assistant"),
    ("FCC", "Client owner"), ("ECC", "Client team member"),
])
def test_every_role_reads_its_own_profile_with_the_role_by_name(seeded_tenant, api, role, label):
    membership = member(seeded_tenant, role, full_name="Pat Example")

    body = api.as_(membership).get(URL).json()

    assert body["full_name"] == "Pat Example" and body["email"] == membership.user.email
    assert body["role_label"] == label and body["editable"] is True
    assert (body["client_company_name"] is not None) == (role in ("FCC", "ECC"))
    assert role not in json.dumps(body)


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FF", "CF", "VA", "FCC", "ECC"])
def test_every_role_changes_its_own_name_and_nobody_elses(seeded_tenant, api, role):
    membership = member(seeded_tenant, role, full_name="Old Name")
    bystander = member(seeded_tenant, "VA", full_name="Someone Else")

    response = patch(api.as_(membership), {"full_name": "  New   Name "})

    assert response.status_code == 200 and response.json()["full_name"] == "New Name"
    membership.user.refresh_from_db()
    bystander.user.refresh_from_db()
    assert membership.user.full_name == "New Name"
    assert bystander.user.full_name == "Someone Else"
    # /api/me, which names them everywhere else, follows.
    assert api.as_(membership).get("/api/me").json()["full_name"] == "New Name"


@pytest.mark.django_db
def test_the_sign_in_email_cannot_be_changed(seeded_tenant, ff, api):
    before = ff.user.email

    response = patch(api.as_(ff), {"full_name": "Fine", "email": "other@example.invalid"})

    assert response.status_code == 400 and "cannot be changed" in response.json()["email"]
    ff.user.refresh_from_db()
    # Refused whole: the name sent with it is not applied either.
    assert ff.user.email == before and ff.user.full_name != "Fine"


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [
    {"full_name": ""}, {"full_name": "   "}, {"full_name": None}, {"full_name": 7},
    {"full_name": "x" * 201}, {"is_platform_owner": True}, {"role": "FF"},
    {"full_name": "Ok", "is_staff": True},
])
def test_a_bad_or_overreaching_change_is_refused(seeded_tenant, va, api, payload):
    before = (va.user.full_name, va.user.is_platform_owner, va.user.is_staff, va.role)

    assert patch(api.as_(va), payload).status_code == 400

    va.user.refresh_from_db()
    va.refresh_from_db()
    assert (va.user.full_name, va.user.is_platform_owner, va.user.is_staff, va.role) == before


@pytest.mark.django_db
def test_a_profile_is_read_only_while_acting_as_its_owner(seeded_tenant, ff, api):
    """The practice owner can see a client's profile from inside their session
    and cannot rename them: a person's profile is theirs."""
    target = member(seeded_tenant, "FCC", full_name="Dana Reyes")
    client = api.as_(ff)
    started = client.post("/api/act-as/", json.dumps({"membership": str(target.pk)}),
                          content_type="application/json")
    assert started.status_code == 201, started.content

    seen = client.get(URL).json()
    assert seen["full_name"] == "Dana Reyes" and seen["editable"] is False

    refused = patch(client, {"full_name": "Renamed By Someone Else"})
    assert refused.status_code == 403
    target.user.refresh_from_db()
    ff.user.refresh_from_db()
    assert target.user.full_name == "Dana Reyes"
    assert ff.user.full_name != "Renamed By Someone Else"


@pytest.mark.django_db
def test_a_profile_never_reaches_into_another_practice(tenant_a, tenant_b, api):
    a = MembershipFactory(tenant=tenant_a, role="FF")
    b = MembershipFactory(tenant=tenant_b, role="FF")
    User.objects.filter(pk=b.user_id).update(full_name="Bravo Owner")

    body = api.as_(a).get(URL).json()
    patch(api.as_(a), {"full_name": "Alpha Owner"})

    assert "Bravo" not in json.dumps(body)
    b.user.refresh_from_db()
    assert b.user.full_name == "Bravo Owner"
    assert api.as_(b).get(URL).json()["full_name"] == "Bravo Owner"


@pytest.mark.django_db
def test_signed_out_gets_nothing_and_changes_nothing(client):
    assert client.get(URL).status_code == 401
    assert patch(client, {"full_name": "Nobody"}).status_code == 401


@pytest.mark.django_db
def test_changing_a_name_needs_the_csrf_token(seeded_tenant, ff):
    from django.test import Client

    strict = Client(enforce_csrf_checks=True)
    strict.force_login(ff.user)
    assert patch(strict, {"full_name": "Forged"}).status_code == 403
