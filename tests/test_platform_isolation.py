"""P2, isolation family: the platform owner reaches nothing inside a practice.

In the Practices area no practice is bound to the request, so every
practice-scoped query fails closed. These tests plant recognizable data in a
practice and walk **every** API route that takes no parameter, plus the main
detail routes, as the platform owner in the Practices area: none may return
the planted data or a planted id. The same walk as that practice's own owner
does find it, so the test can tell the difference.
"""

from __future__ import annotations

import re

import pytest
from django.urls import URLPattern, URLResolver, get_resolver

from apps.tenancy.context import tenant_context
from apps.tenancy.middleware import AREA_PLATFORM, AREA_SESSION_KEY

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import (
    ClientCompanyFactory, ContactFactory, NoteFactory, TaskFactory,
)

MARK = "PLANTEDzq7"
#: Routes that are public by design, or the platform's own. They are walked
#: like the rest, but may answer 200: what they return is still checked.
PUBLIC_OK = {"/api/branding", "/api/me", "/api/platform/area"}


def _routes(resolver=None, prefix=""):
    resolver = resolver or get_resolver()
    for entry in resolver.url_patterns:
        pattern = prefix + str(entry.pattern).lstrip("^").rstrip("$")
        if isinstance(entry, URLResolver):
            yield from _routes(entry, pattern)
        elif isinstance(entry, URLPattern):
            yield pattern


def api_list_routes():
    out = set()
    for raw in _routes():
        if not raw.startswith("api/") or "<" in raw or "(?P" in raw or "\\" in raw:
            continue
        if raw.endswith(".(?P<format>[a-z0-9]+)/?") or "format" in raw:
            continue
        out.add("/" + raw)
    return sorted(out)


@pytest.fixture
def planted(seeded_tenant):
    with tenant_context(seeded_tenant.pk):
        company = ClientCompanyFactory(tenant=seeded_tenant, name=f"{MARK} Company")
        contact = ContactFactory(tenant=seeded_tenant, first_name=MARK, last_name="Contact")
        note = NoteFactory(tenant=seeded_tenant, title=f"{MARK} note", body=f"{MARK} body")
        task = TaskFactory(tenant=seeded_tenant, title=f"{MARK} task")
    return {"company": company, "contact": contact, "note": note, "task": task}


@pytest.fixture
def platform_owner(seeded_tenant):
    owner = _member(seeded_tenant, "FF")
    owner.user.is_platform_owner = True
    owner.user.save()
    return owner


def in_practices_area(client):
    session = client.session
    session[AREA_SESSION_KEY] = AREA_PLATFORM
    session.save()
    return client


def leaks(body: str, planted) -> list[str]:
    found = [MARK] if MARK in body else []
    found += [str(obj.pk) for obj in planted.values() if str(obj.pk) in body]
    return found


@pytest.mark.django_db
def test_the_walk_finds_the_planted_data_as_the_practice_owner(api, platform_owner, planted):
    """The control: without it, an empty walk would pass the real test."""
    client = api.as_(platform_owner)
    seen = [route for route in api_list_routes()
            if leaks(client.get(route).content.decode(errors="ignore"), planted)]
    assert len(seen) >= 3, seen


@pytest.mark.django_db
def test_in_the_practices_area_no_route_returns_practice_data(api, platform_owner, planted):
    client = in_practices_area(api.as_(platform_owner))
    assert client.get("/api/me").json()["area"] == "platform"
    leaked = {}
    for route in api_list_routes():
        response = client.get(route)
        found = leaks(response.content.decode(errors="ignore"), planted)
        if found:
            leaked[route] = (response.status_code, found)
        elif route not in PUBLIC_OK:
            assert response.status_code in (401, 403, 404, 405) or response.status_code < 300, route
    assert not leaked, leaked


@pytest.mark.django_db
@pytest.mark.parametrize("path", [
    "/api/contacts/{contact}/", "/api/notes/{note}/", "/api/tasks/{task}/",
    "/api/companies/{company}/",
])
def test_in_the_practices_area_detail_routes_refuse(api, platform_owner, planted, path):
    client = in_practices_area(api.as_(platform_owner))
    url = path.format(**{k: v.pk for k, v in planted.items()})
    response = client.get(url)
    assert response.status_code in (401, 403, 404)
    assert not leaks(response.content.decode(errors="ignore"), planted)


@pytest.mark.django_db
def test_the_session_key_grants_nothing_to_anyone_else(api, seeded_tenant, planted):
    """A practice owner who is not the platform owner, with the area forced in
    the session, is still bound to their practice and is not the platform."""
    ordinary = _member(seeded_tenant, "FF")
    client = in_practices_area(api.as_(ordinary))
    me = client.get("/api/me").json()
    assert me["area"] == "practice" and me["is_platform_owner"] is False
    assert client.post("/api/platform/area", {"area": "platform"}).status_code == 403


@pytest.mark.django_db
def test_switching_areas(api, platform_owner, planted):
    client = api.as_(platform_owner)
    assert client.post("/api/platform/area", {"area": "platform"}).json() == {"area": "platform"}
    assert client.get(f"/api/contacts/{planted['contact'].pk}/").status_code in (403, 404)
    assert client.post("/api/platform/area", {"area": "practice"}).json() == {"area": "practice"}
    assert client.get(f"/api/contacts/{planted['contact'].pk}/").status_code == 200
    assert client.post("/api/platform/area", {"area": "everything"}).status_code == 400


@pytest.mark.django_db
def test_in_the_practices_area_the_tab_and_branding_are_the_products(api, platform_owner):
    client = in_practices_area(api.as_(platform_owner))
    body = client.get("/api/branding").json()
    assert body["product_name"] and body["display_name"] == ""
    assert client.get("/api/branding/mark").status_code == 404


@pytest.mark.django_db
def test_the_flag_cannot_be_set_through_the_api(api, seeded_tenant):
    owner = _member(seeded_tenant, "FF")
    client = api.as_(owner)
    for path in ("/api/me", f"/api/staff/{owner.pk}/"):
        client.patch(path, '{"is_platform_owner": true}', content_type="application/json")
    owner.user.refresh_from_db()
    assert owner.user.is_platform_owner is False


@pytest.mark.django_db
def test_set_platform_owner_command(seeded_tenant):
    from django.core.management import CommandError, call_command

    owner = _member(seeded_tenant, "FF")
    call_command("set_platform_owner", owner.user.email)
    owner.user.refresh_from_db()
    assert owner.user.is_platform_owner
    call_command("set_platform_owner", owner.user.email, "--remove")
    owner.user.refresh_from_db()
    assert not owner.user.is_platform_owner
    with pytest.raises(CommandError, match="No user"):
        call_command("set_platform_owner", "nobody@example.invalid")
