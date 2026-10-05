"""Sign out, and the staff session rules (docs/ui3_top_bar_settings_profile.md
§2 and §2a): closing the browser, and 12 hours without activity. Client portal
sessions are deliberately untouched."""

from __future__ import annotations

import time

import pytest
from django.conf import settings

from apps.accounts.middleware import IDLE_HEADER, LAST_ACTIVE_KEY
from apps.tenancy.models import AuditEvent

from . import registry_config  # noqa: F401
from .factories import ClientCompanyFactory, MembershipFactory

HOURS = 60 * 60


def idle(client, path, seconds):
    return client.get(path, headers={IDLE_HEADER: str(seconds)})


def backdate(client, seconds):
    session = client.session
    session[LAST_ACTIVE_KEY] = time.time() - seconds
    session.save()


@pytest.fixture
def client_user(seeded_tenant, api):
    """A client owner signed in the way the emailed link does it."""
    company = ClientCompanyFactory(tenant=seeded_tenant)
    membership = MembershipFactory(tenant=seeded_tenant, role="FCC", client_company=company)
    client = api.as_(membership)
    session = client.session
    session.set_expiry(settings.CLIENT_SESSION_AGE)
    session.save()
    return client


# ----------------------------------------------------------------- sign out

@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FF", "CF", "VA", "FCC", "ECC"])
def test_sign_out_ends_the_session_for_every_role(seeded_tenant, api, role):
    company = ClientCompanyFactory(tenant=seeded_tenant) if role in ("FCC", "ECC") else None
    client = api.as_(MembershipFactory(tenant=seeded_tenant, role=role, client_company=company))
    assert client.get("/api/me").status_code == 200

    assert client.post("/auth/sign-out").json() == {"signed_out": True}

    assert client.get("/api/me").status_code == 401
    assert client.get("/api/tasks/").status_code in (401, 403)


@pytest.mark.django_db
def test_sign_out_is_a_post_and_harmless_when_signed_out(client):
    assert client.get("/auth/sign-out").status_code == 405
    assert client.post("/auth/sign-out").status_code == 200


@pytest.mark.django_db
def test_sign_out_needs_the_csrf_token(seeded_tenant, ff):
    from django.test import Client

    strict = Client(enforce_csrf_checks=True)
    strict.force_login(ff.user)
    assert strict.post("/auth/sign-out").status_code == 403
    assert strict.get("/api/me").status_code == 200


@pytest.mark.django_db
def test_signing_out_while_acting_as_ends_and_records_it(seeded_tenant, ff, api):
    company = ClientCompanyFactory(tenant=seeded_tenant)
    target = MembershipFactory(tenant=seeded_tenant, role="FCC", client_company=company)
    client = api.as_(ff)
    started = client.post("/api/act-as/", {"membership": str(target.pk)},
                          content_type="application/json")
    assert started.status_code == 201, started.content

    client.post("/auth/sign-out")

    ended = AuditEvent.all_objects.get(tenant=seeded_tenant, verb="act_as.ended")
    assert ended.actor_id == ff.user.pk and ended.payload["reason"] == "signed out"
    assert client.get("/api/me").status_code == 401


# ------------------------------------------------------- closing the browser

@pytest.mark.django_db
def test_a_staff_cookie_ends_with_the_browser_and_a_clients_does_not(
    seeded_tenant, ff, api, client_user
):
    staff_cookie = api.as_(ff).get("/api/me").cookies[settings.SESSION_COOKIE_NAME]
    assert staff_cookie["max-age"] == "" and staff_cookie["expires"] == ""

    client_cookie = client_user.get("/api/me").cookies[settings.SESSION_COOKIE_NAME]
    assert int(client_cookie["max-age"]) == settings.CLIENT_SESSION_AGE


# ------------------------------------------------- twelve hours of inactivity

@pytest.mark.django_db
def test_twelve_hours_without_activity_signs_staff_out(seeded_tenant, ff, api):
    client = api.as_(ff)
    assert client.get("/api/me").status_code == 200

    backdate(client, 12 * HOURS + 60)
    refused = client.get("/api/me")

    assert refused.status_code == 401
    assert "12 hours" in refused.json()["detail"]
    # Signed out on the server, not just refused once.
    assert client.get("/api/me", headers={IDLE_HEADER: "0"}).status_code == 401


@pytest.mark.django_db
def test_just_under_twelve_hours_is_still_signed_in(seeded_tenant, ff, api):
    client = api.as_(ff)
    client.get("/api/me")
    backdate(client, 12 * HOURS - 60)
    assert client.get("/api/me").status_code == 200


@pytest.mark.django_db
def test_background_refreshes_do_not_count_as_activity(seeded_tenant, ff, api):
    """A screen left open refreshes itself. Those requests say how long the
    person has been idle, and must not move the clock."""
    client = api.as_(ff)
    client.get("/api/me")
    backdate(client, 11 * HOURS)
    before = client.session[LAST_ACTIVE_KEY]

    for _ in range(3):
        assert idle(client, "/api/me", 11 * HOURS).status_code == 200
    # Still the moment they last did something (to the second), not now.
    assert abs(client.session[LAST_ACTIVE_KEY] - before) < 5

    # ...so an hour later the same refresh is what signs them out.
    backdate(client, 12 * HOURS + 60)
    assert idle(client, "/api/me", 12 * HOURS + 60).status_code == 401


@pytest.mark.django_db
def test_real_activity_moves_the_clock_forward(seeded_tenant, ff, api):
    client = api.as_(ff)
    client.get("/api/me")
    backdate(client, 11 * HOURS)

    assert idle(client, "/api/me", 5).status_code == 200

    assert time.time() - client.session[LAST_ACTIVE_KEY] < 60
    # A request that does not say (a page load) counts as activity too.
    backdate(client, 11 * HOURS)
    client.get("/api/me")
    assert time.time() - client.session[LAST_ACTIVE_KEY] < 60


@pytest.mark.django_db
def test_a_nonsense_idle_header_cannot_break_or_extend_a_session(seeded_tenant, ff, api):
    client = api.as_(ff)
    client.get("/api/me")
    for value in ("soon", "-99999", ""):
        assert client.get("/api/me", headers={IDLE_HEADER: value}).status_code == 200
    assert client.session[LAST_ACTIVE_KEY] <= time.time()


@pytest.mark.django_db
def test_a_page_request_after_twelve_hours_comes_back_signed_out(seeded_tenant, ff, api):
    client = api.as_(ff)
    client.get("/api/me")
    backdate(client, 13 * HOURS)

    response = client.get("/contacts")

    assert response.status_code == 302 and response["Location"] == "/contacts"
    assert client.get("/api/me").status_code == 401


@pytest.mark.django_db
def test_client_portal_sessions_are_left_as_they_were(client_user):
    """Thirty days, and no idle rule, until the owner decides otherwise."""
    assert client_user.get("/api/me").status_code == 200
    backdate(client_user, 5 * 24 * HOURS)

    assert idle(client_user, "/api/me", 5 * 24 * HOURS).status_code == 200
    assert client_user.session.get_expiry_age() > 29 * 24 * HOURS


@pytest.mark.django_db
def test_idling_out_while_acting_as_ends_and_records_it(seeded_tenant, ff, api):
    company = ClientCompanyFactory(tenant=seeded_tenant)
    target = MembershipFactory(tenant=seeded_tenant, role="FCC", client_company=company)
    client = api.as_(ff)
    client.post("/api/act-as/", {"membership": str(target.pk)},
                content_type="application/json")
    backdate(client, 13 * HOURS)

    assert client.get("/api/me").status_code == 401
    assert AuditEvent.all_objects.filter(tenant=seeded_tenant, verb="act_as.ended").exists()
