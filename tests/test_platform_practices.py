"""P2: the Practices area — the list, creating a practice, archiving one.

Role boundaries first: only the platform owner, and only in the Practices
area. Then provisioning's defaults (owner, 2026-10-02), archiving, and the
source guard that keeps `apps/platform` away from what a practice holds.
"""

from __future__ import annotations

import ast
import json
import pathlib

import pytest
from django.contrib.auth.signals import user_logged_in
from django.test import RequestFactory
from django_q.models import Schedule

from apps.crm.models import Pipeline, StageAutomation
from apps.platform import provisioning, stats
from apps.strategy.models import StrategyTemplate
from apps.tenancy.middleware import AREA_PLATFORM, AREA_SESSION_KEY
from apps.tenancy.models import AuditEvent, Membership, Tenant

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import ClientCompanyFactory, ContactFactory

NEW = {"legal_name": "Blue Sky Business Consulting LLC",
       "display_name": "Blue Sky Business Consulting",
       "domain": "blueskybizconsulting.com", "owner_email": "owner@bluesky.invalid"}


@pytest.fixture
def platform_owner(seeded_tenant):
    owner = _member(seeded_tenant, "FF")
    owner.user.is_platform_owner = True
    owner.user.save()
    return owner


def practices(api, membership):
    client = api.as_(membership)
    session = client.session
    session[AREA_SESSION_KEY] = AREA_PLATFORM
    session.save()
    return client


def post(client, url, body):
    return client.post(url, json.dumps(body), content_type="application/json")


# ------------------------------------------------------------------ boundaries

@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FF", "CF", "VA", "FCC"])
def test_nobody_but_the_platform_owner_reaches_the_practices_list(api, seeded_tenant, role):
    company = ClientCompanyFactory(tenant=seeded_tenant) if role == "FCC" else None
    member = _member(seeded_tenant, role, company)
    client = practices(api, member)           # even with the area forced in the session
    assert client.get("/api/platform/practices").status_code == 403
    assert post(client, "/api/platform/practices", NEW).status_code == 403
    assert not Tenant.objects.filter(domain=NEW["domain"]).exists()


@pytest.mark.django_db
def test_the_platform_owner_only_in_the_practices_area(api, platform_owner):
    assert api.as_(platform_owner).get("/api/platform/practices").status_code == 403
    assert practices(api, platform_owner).get("/api/platform/practices").status_code == 200


@pytest.mark.django_db
def test_the_list_carries_numbers_and_never_what_a_practice_holds(api, platform_owner,
                                                                  seeded_tenant):
    ClientCompanyFactory(tenant=seeded_tenant, name="Zebrafish Holdings")
    ContactFactory(tenant=seeded_tenant, first_name="Quillon", last_name="Marsh")
    response = practices(api, platform_owner).get("/api/platform/practices")
    body = response.content.decode()
    assert "Zebrafish" not in body and "Quillon" not in body
    [row] = response.json()
    assert tuple(row) == stats.ROW_KEYS
    assert row["client_count"] == 1 and row["staff_count"] == 1
    assert row["ai_spend_this_month_usd"] == "0.00"


# ------------------------------------------------------------------ provisioning

@pytest.mark.django_db
def test_a_new_practice_gets_structure_and_none_of_anyone_elses(api, platform_owner):
    response = post(practices(api, platform_owner), "/api/platform/practices", NEW)
    assert response.status_code == 201, response.content
    tenant = Tenant.objects.get(pk=response.json()["id"])

    assert (tenant.name, tenant.legal_name, tenant.email_display_name, tenant.domain) == (
        NEW["display_name"], NEW["legal_name"], NEW["display_name"], NEW["domain"])
    assert tenant.status == "invited" and tenant.oauth_client == "external"
    assert tenant.hold_all_digests is True
    assert str(tenant.ai_monthly_budget_usd) == "50.00"
    assert str(tenant.ai_unattended_daily_cap_usd) == "5.00"
    assert tenant.from_address == "info@blueskybizconsulting.com"
    assert tenant.inbound_domain == ""
    assert "getexecutivesnow" not in tenant.from_address + tenant.inbound_domain
    assert tenant.branding_updated_at is None and tenant.email_logo_id is None
    assert Pipeline.all_objects.filter(tenant=tenant).exists()
    assert not StageAutomation.all_objects.filter(tenant=tenant).exists()
    assert not StrategyTemplate.all_objects.filter(tenant=tenant).exists()
    owner = Membership.all_objects.get(tenant=tenant)
    assert owner.role == "FF" and owner.user.email == NEW["owner_email"]
    assert owner.invited_at is not None and owner.invited_by == platform_owner.user
    assert Schedule.objects.filter(name__endswith=f":{tenant.slug}").count() > 0
    assert AuditEvent.all_objects.filter(tenant=tenant, verb="practice.created").exists()


@pytest.mark.django_db
def test_an_executives_now_domain_practice_uses_the_internal_client(platform_owner):
    tenant = provisioning.provision_practice(**{**NEW, "domain": "getexecutivesnow.com"},
                                             actor=platform_owner.user)
    assert tenant.oauth_client == "internal"


@pytest.mark.django_db
@pytest.mark.parametrize("field,value,needle", [
    ("domain", "not a domain", "domain"),
    ("owner_email", "nobody", "email"),
    ("legal_name", "  ", "legal name"),
    ("display_name", "", "clients will see"),
])
def test_bad_details_are_refused_and_nothing_is_made(api, platform_owner, field, value, needle):
    before = Tenant.objects.count()
    response = post(practices(api, platform_owner), "/api/platform/practices",
                    {**NEW, field: value})
    assert response.status_code == 400 and needle in response.json()["errors"][field]
    assert Tenant.objects.count() == before


@pytest.mark.django_db
def test_an_address_already_in_a_practice_is_refused(api, platform_owner, seeded_tenant):
    taken = _member(seeded_tenant, "VA")
    response = post(practices(api, platform_owner), "/api/platform/practices",
                    {**NEW, "owner_email": taken.user.email})
    assert response.status_code == 400 and "already belongs" in response.json()["detail"]


@pytest.mark.django_db
def test_a_failure_part_way_leaves_nothing_behind(platform_owner, monkeypatch):
    import apps.crm.seed as seed

    monkeypatch.setattr(seed, "seed_tenant", lambda tenant: (_ for _ in ()).throw(
        RuntimeError("seed failed")))
    before = Tenant.objects.count()
    with pytest.raises(RuntimeError):
        provisioning.provision_practice(**NEW, actor=platform_owner.user)
    assert Tenant.objects.count() == before
    assert not Membership.all_objects.filter(user__email=NEW["owner_email"]).exists()


@pytest.mark.django_db
def test_the_owner_signing_in_makes_the_practice_active(platform_owner):
    tenant = provisioning.provision_practice(**NEW, actor=platform_owner.user)
    owner = Membership.all_objects.get(tenant=tenant).user
    user_logged_in.send(sender=type(owner), request=RequestFactory().get("/"), user=owner)
    tenant.refresh_from_db()
    assert tenant.status == "active"


@pytest.mark.django_db
def test_the_platform_record_can_be_corrected(api, platform_owner, seeded_tenant):
    client = practices(api, platform_owner)
    response = client.patch(f"/api/platform/practices/{seeded_tenant.pk}",
                            json.dumps({"legal_name": "Noble Rose LLC",
                                        "domain": "getexecutivesnow.com"}),
                            content_type="application/json")
    assert response.status_code == 200
    assert response.json()["legal_name"] == "Noble Rose LLC"
    bad = client.patch(f"/api/platform/practices/{seeded_tenant.pk}",
                       json.dumps({"domain": "no spaces.com"}), content_type="application/json")
    assert bad.status_code == 400


# ------------------------------------------------------------------ archiving

@pytest.mark.django_db
def test_archiving_signs_everyone_out_stops_the_jobs_and_keeps_the_data(api, platform_owner,
                                                                        dev_outbox):
    tenant = provisioning.provision_practice(**NEW, actor=platform_owner.user)
    owner = Membership.all_objects.get(tenant=tenant)
    pipelines = Pipeline.all_objects.filter(tenant=tenant).count()
    client = practices(api, platform_owner)

    assert post(client, f"/api/platform/practices/{tenant.pk}/archive", {}).status_code == 200
    tenant.refresh_from_db()
    assert tenant.status == "archived" and tenant.archived_at is not None
    assert not Schedule.objects.filter(name__endswith=f":{tenant.slug}").exists()
    assert Pipeline.all_objects.filter(tenant=tenant).count() == pipelines, "data kept"

    # Signed in already: bound to nothing now.
    me = api.as_(owner).get("/api/me").json()
    assert me["role"] is None and me["tenant"] is None
    # No sign-in link is sent for an archived practice.
    from django.test import Client

    Client().post("/auth/magic/request", {"email": owner.user.email})
    assert not dev_outbox

    # ensure_schedules, run after every pull, does not bring the jobs back.
    from django.core.management import call_command

    call_command("ensure_schedules")
    assert not Schedule.objects.filter(name__endswith=f":{tenant.slug}").exists()

    assert post(client, f"/api/platform/practices/{tenant.pk}/unarchive", {}).status_code == 200
    tenant.refresh_from_db()
    # The owner signed in above (a session is a sign-in), so it comes back
    # active rather than invited.
    assert tenant.status == "active" and tenant.archived_at is None
    assert Schedule.objects.filter(name__endswith=f":{tenant.slug}").exists()
    assert api.as_(owner).get("/api/me").json()["role"] == "FF"


@pytest.mark.django_db
def test_you_cannot_archive_your_own_practice(api, platform_owner, seeded_tenant):
    response = post(practices(api, platform_owner),
                    f"/api/platform/practices/{seeded_tenant.pk}/archive", {})
    assert response.status_code == 400
    seeded_tenant.refresh_from_db()
    assert seeded_tenant.status == "active"


# ------------------------------------------------------------------ the source guard

#: What `apps/platform` may name. Everything a practice holds (contacts,
#: notes, tasks, email, meetings, sessions) is absent on purpose.
ALLOWED_MODELS = {"Tenant", "Membership", "Role", "AiCall", "Company", "AuditEvent",
                  "User", "StoredFile", "Feedback", "AgreementAcceptance", "TenantScopedModel"}


def test_apps_platform_names_nothing_a_practice_holds():
    root = pathlib.Path(__file__).resolve().parent.parent / "apps" / "platform"
    found = []
    for path in root.rglob("*.py"):
        if "migrations" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("apps.") \
                    and node.module.endswith(".models"):
                for alias in node.names:
                    if alias.name not in ALLOWED_MODELS:
                        found.append(f"{path.name}: {node.module}.{alias.name}")
    assert not found, found
