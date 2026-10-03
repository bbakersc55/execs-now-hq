"""P2 §7: feedback, the one thing that crosses the practice boundary, and only
because a person wrote it."""

from __future__ import annotations

import io

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.crm.models import OutboxMessage
from apps.platform.models import Feedback
from apps.tenancy.middleware import AREA_PLATFORM, AREA_SESSION_KEY

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import ClientCompanyFactory, ContactFactory

ANSWERS = {"doing": "Approving a digest", "happened": "The button spun forever",
           "expected": "The digest to be approved", "page_url": "/digests"}


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    cache.clear()


@pytest.fixture
def platform_owner(seeded_tenant):
    owner = _member(seeded_tenant, "FF")
    owner.user.is_platform_owner = True
    owner.user.save()
    return owner


def png():
    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 10, 10)).save(buffer, "PNG")
    return buffer.getvalue()


def send(client, **extra):
    return client.post("/api/feedback/", {**ANSWERS, **extra})


def in_practices(api, membership):
    client = api.as_(membership)
    session = client.session
    session[AREA_SESSION_KEY] = AREA_PLATFORM
    session.save()
    return client


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FF", "CF", "VA"])
def test_staff_send_feedback_and_the_platform_owner_is_told(api, seeded_tenant, platform_owner,
                                                            role, monkeypatch):
    monkeypatch.setattr("apps.crm.services.outbox._deliver", lambda m, **kw: None)
    member = _member(seeded_tenant, role)
    ContactFactory(tenant=seeded_tenant, first_name="Secretname")
    response = send(api.as_(member), screenshot=SimpleUploadedFile("s.png", png()))
    assert response.status_code == 201, response.content
    row = Feedback.all_objects.get()
    assert (row.tenant_id, row.role, row.practice_name) == (seeded_tenant.pk, role,
                                                            seeded_tenant.name)
    assert row.screenshot_id is not None
    notice = OutboxMessage.all_objects.get(producer="feedback_notice")
    assert notice.to_address == platform_owner.user.email
    assert "The button spun forever" in notice.body_text
    assert "Secretname" not in notice.body_text, "the notice carries the words, nothing else"


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FCC", "ECC"])
def test_clients_cannot_send_feedback(api, seeded_tenant, role):
    member = _member(seeded_tenant, role, ClientCompanyFactory(tenant=seeded_tenant))
    assert send(api.as_(member)).status_code == 403


@pytest.mark.django_db
def test_staff_see_only_what_they_sent(api, seeded_tenant, tenant_b):
    mine, colleague = _member(seeded_tenant, "CF"), _member(seeded_tenant, "VA")
    other_practice = _member(tenant_b, "FF")
    send(api.as_(mine))
    send(api.as_(colleague), happened="Something else")
    send(api.as_(other_practice), happened="Tenant B's problem")
    seen = api.as_(mine).get("/api/feedback/").json()
    assert [r["happened"] for r in seen] == ["The button spun forever"]
    assert all("Tenant B" not in r["happened"] for r in api.as_(colleague).get(
        "/api/feedback/").json())


@pytest.mark.django_db
def test_the_platform_owner_reads_all_of_it_and_only_it(api, platform_owner, seeded_tenant,
                                                        tenant_b):
    send(api.as_(_member(seeded_tenant, "VA")), screenshot=SimpleUploadedFile("s.png", png()))
    send(api.as_(_member(tenant_b, "CF")), happened="Tenant B's problem")
    client = in_practices(api, platform_owner)
    rows = client.get("/api/platform/feedback").json()
    assert {r["practice_name"] for r in rows} == {seeded_tenant.name, tenant_b.name}
    assert {r["role"] for r in rows} == {"Assistant", "Associate"}
    assert set(rows[0]) == {"id", "doing", "happened", "expected", "page_url", "status",
                            "has_screenshot", "created_at", "practice_name", "role"}
    with_shot = next(r for r in rows if r["has_screenshot"])
    shot = client.get(f"/api/platform/feedback/{with_shot['id']}")
    assert shot.status_code == 200 and shot.content == png()
    assert client.patch(f"/api/platform/feedback/{with_shot['id']}", {"status": "seen"},
                        content_type="application/json").json()["status"] == "seen"


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FF", "CF", "VA"])
def test_nobody_else_reads_the_platform_feedback(api, seeded_tenant, role):
    member = _member(seeded_tenant, role)
    send(api.as_(member))
    row = Feedback.all_objects.get()
    client = in_practices(api, member)
    assert client.get("/api/platform/feedback").status_code == 403
    assert client.get(f"/api/platform/feedback/{row.pk}").status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("extra,needle", [
    ({"happened": "  "}, "what happened"),
    ({"screenshot": SimpleUploadedFile("s.txt", b"not an image")}, "PNG or a JPEG"),
])
def test_incomplete_or_wrong_feedback_is_refused(api, seeded_tenant, extra, needle):
    response = send(api.as_(_member(seeded_tenant, "FF")), **extra)
    assert response.status_code == 400 and needle in response.json()["detail"]
    assert not Feedback.all_objects.exists()


@pytest.mark.django_db
def test_ten_an_hour(api, seeded_tenant):
    client = api.as_(_member(seeded_tenant, "VA"))
    codes = [send(client).status_code for _ in range(11)]
    assert codes[:10] == [201] * 10 and codes[10] == 429


@pytest.mark.django_db
def test_feedback_is_kept_when_there_is_no_platform_owner_to_tell(api, seeded_tenant):
    assert send(api.as_(_member(seeded_tenant, "FF"))).status_code == 201
    assert Feedback.all_objects.count() == 1
    assert not OutboxMessage.all_objects.filter(producer="feedback_notice").exists()
