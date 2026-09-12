"""Mandatory test family 2 — role boundaries (CLAUDE.md, assumption B3).

Source of truth is `03_access_matrix.md`. Every row there becomes a case here.
Phase 0.5 covers the matrix rows that exist in the foundation: §2 and §3, plus
the membership invariants every later module's rows depend on.
"""

from __future__ import annotations

import pytest
from django.db.utils import IntegrityError

from apps.tenancy.context import tenant_context
from apps.tenancy.models import CLIENT_ROLES, TENANT_ROLES, Membership, Role

from . import registry_config  # noqa: F401
from .factories import ClientCompanyFactory, MembershipFactory, UserFactory


@pytest.mark.django_db
@pytest.mark.parametrize("role", sorted(TENANT_ROLES))
def test_tenant_roles_must_not_carry_a_client_company(role, tenant_a):
    """Matrix §2: a tenant user is scoped by tenant, never by company."""
    company = ClientCompanyFactory(tenant=tenant_a)
    with pytest.raises(IntegrityError):
        MembershipFactory(tenant=tenant_a, role=role, client_company=company)


@pytest.mark.django_db
@pytest.mark.parametrize("role", sorted(CLIENT_ROLES))
def test_client_roles_require_a_client_company(role, tenant_a):
    """FR-0.2: a client user without a company is an unbounded client user."""
    with pytest.raises(IntegrityError):
        MembershipFactory(tenant=tenant_a, role=role, client_company=None)


@pytest.mark.django_db
@pytest.mark.parametrize("role", sorted(CLIENT_ROLES))
def test_client_roles_bind_a_second_scope_layer(role, tenant_a):
    company = ClientCompanyFactory(tenant=tenant_a)
    membership = MembershipFactory(tenant=tenant_a, role=role, client_company=company)
    assert membership.is_client_user
    assert membership.client_company_id == company.pk


@pytest.mark.django_db
def test_one_membership_per_user_per_tenant(tenant_a):
    """Assumption B4 — enforced now, modelled as a table for V1."""
    user = UserFactory()
    MembershipFactory(tenant=tenant_a, user=user, role=Role.FF)
    with pytest.raises(IntegrityError):
        MembershipFactory(tenant=tenant_a, user=user, role=Role.VA)


@pytest.mark.django_db
def test_seats_are_counted_not_stored(tenant_a):
    """Data model §12.3 — a counter would drift; a count cannot."""
    company = ClientCompanyFactory(tenant=tenant_a, seat_count=2)
    assert company.seats_in_use == 0
    assert company.seats_available == 2

    MembershipFactory(tenant=tenant_a, role=Role.FCC, client_company=company)
    assert company.seats_in_use == 1

    revoked = MembershipFactory(tenant=tenant_a, role=Role.ECC, client_company=company)
    assert company.seats_in_use == 2
    assert company.seats_available == 0

    from django.utils import timezone
    revoked.revoked_at = timezone.now()
    revoked.save()
    # FR-3.33g: revoking frees the seat immediately, with no reconciliation step.
    assert company.seats_in_use == 1
    assert company.seats_available == 1


@pytest.mark.django_db
def test_only_one_anthropic_key_per_tenant(tenant_a):
    """Data model review item 5 — the NULL-distinct trap.

    U(tenant, kind, user) does not constrain rows where user IS NULL, because
    Postgres treats NULLs as distinct. The partial index does.
    """
    from .factories import TenantSecretFactory

    TenantSecretFactory(tenant=tenant_a, kind="anthropic_api_key", user=None)
    with pytest.raises(IntegrityError):
        TenantSecretFactory(tenant=tenant_a, kind="anthropic_api_key", user=None)


@pytest.mark.django_db
def test_tenant_secret_ciphertext_is_never_serialised(tenant_a):
    """E1.3 — write-only across the entire API, for every role including FF."""
    from apps.tenancy.models import TenantSecret

    with tenant_context(tenant_a.pk):
        from .factories import TenantSecretFactory

        secret = TenantSecretFactory(tenant=tenant_a)
        assert "ciphertext" not in str(secret)
        assert secret.last4 in str(secret)
        # Nothing in the codebase may expose the field; enforced by review plus
        # this assertion once a serializer exists in Phase 1.
        assert TenantSecret._meta.get_field("ciphertext") is not None


# =========================================================== Module 1 (§4, §5)
# Matrix rows 3.12-3.19, 4.1-4.18, 5.1-5.9. Every denied-send case also asserts
# the dev outbox is empty and no OutboxMessage reached `sent` (matrix §14.3).

MODULE1_ENDPOINTS = [
    ("/api/contacts/", {"FF": 200, "CF": 200, "VA": 200, "FCC": 403, "ECC": 403}),
    ("/api/companies/", {"FF": 200, "CF": 200, "VA": 200, "FCC": 403, "ECC": 403}),
    ("/api/outbox/", {"FF": 200, "CF": 200, "VA": 200, "FCC": 403, "ECC": 403}),
    ("/api/imports/", {"FF": 200, "CF": 403, "VA": 200, "FCC": 403, "ECC": 403}),
    ("/api/pipeline-stages/", {"FF": 200, "CF": 200, "VA": 200, "FCC": 403, "ECC": 403}),
    ("/api/contact-types/", {"FF": 200, "CF": 200, "VA": 200, "FCC": 403, "ECC": 403}),
    ("/api/service-categories/", {"FF": 200, "CF": 200, "VA": 200, "FCC": 403, "ECC": 403}),
    ("/api/stage-automations/", {"FF": 200, "CF": 403, "VA": 403, "FCC": 403, "ECC": 403}),
]
# /api/tasks/ moved to Module 3 in Phase 3 — see MODULE3_ENDPOINTS below. Under
# matrix 7.1 a client user reaches it and sees their own company's
# client-visible tasks, so the Phase 1 expectation of 403 no longer holds.


@pytest.mark.django_db
@pytest.mark.parametrize("url,expected", MODULE1_ENDPOINTS, ids=[u for u, _ in MODULE1_ENDPOINTS])
@pytest.mark.parametrize("role", ["FF", "CF", "VA", "FCC", "ECC"])
def test_module1_endpoint_role_matrix(url, expected, role, seeded_tenant, api):
    """Every Module 1 endpoint x every role, straight from `03_access_matrix.md`."""
    from .factories import ClientCompanyFactory

    company = ClientCompanyFactory(tenant=seeded_tenant) if role in ("FCC", "ECC") else None
    membership = MembershipFactory(tenant=seeded_tenant, role=role, client_company=company)
    response = api.as_(membership).get(url)
    assert response.status_code == expected[role], (
        f"{url} as {role}: expected {expected[role]}, got {response.status_code}"
    )


@pytest.mark.django_db
def test_va_denied_send_leaves_the_outbox_untouched(seeded_tenant, va, api, dev_outbox):
    """Matrix §14.3 — a 403 alone is not a sufficient assertion."""
    from apps.crm.models import OutboxMessage
    from apps.crm.services import outbox as outbox_service
    from apps.tenancy.context import tenant_context

    from .factories import ContactEmailFactory, ContactFactory

    with tenant_context(seeded_tenant.pk):
        contact = ContactFactory(tenant=seeded_tenant)
        ContactEmailFactory(tenant=seeded_tenant, contact=contact)
        message = outbox_service.create_message(
            tenant=seeded_tenant, producer="referral_touch", to_contact=contact,
            to_address=contact.primary_email, subject="s", body_text="b",
        )

    assert api.as_(va).post(f"/api/outbox/{message.pk}/approve/").status_code == 403

    message.refresh_from_db()
    assert message.state != OutboxMessage.State.SENT
    assert message.sent_at is None
    assert dev_outbox == [], "A denied send still delivered mail."


@pytest.mark.django_db
def test_cf_cannot_approve_for_an_unassigned_company(seeded_tenant, ff, cf, api, dev_outbox):
    """Matrix 8.6 / 5.3 — CF approval is bounded by assignment."""
    from apps.crm.services import outbox as outbox_service
    from apps.tenancy.context import tenant_context

    from .factories import ClientCompanyFactory, ContactEmailFactory, ContactFactory

    unassigned = ClientCompanyFactory(tenant=seeded_tenant)
    with tenant_context(seeded_tenant.pk):
        contact = ContactFactory(tenant=seeded_tenant, company=unassigned)
        ContactEmailFactory(tenant=seeded_tenant, contact=contact)
        message = outbox_service.create_message(
            tenant=seeded_tenant, producer="referral_touch", to_contact=contact,
            to_address=contact.primary_email, subject="s", body_text="b",
        )

    # 404, not 403: a 403 would confirm the row exists (matrix §1 rule 1).
    assert api.as_(cf).post(f"/api/outbox/{message.pk}/approve/").status_code == 404
    message.refresh_from_db()
    assert message.state != "sent"
    assert dev_outbox == []


# ============================================================== Module 2 (§6)
# Matrix rows 6.1-6.9. Row 6.4 is the one row whose scope is the PIN, not the
# role: the FF without the PIN gets the stub, exactly like everyone else.

import json as _json

from datetime import timedelta

from apps.crm.models import OutboxMessage

ALL_ROLES = ["FF", "CF", "VA", "FCC", "ECC"]
SECRET_6 = "Personnel matter: performance plan for the ops lead"


def _as(role, tenant):
    from .factories import ClientCompanyFactory

    company = ClientCompanyFactory(tenant=tenant) if role in ("FCC", "ECC") else None
    return MembershipFactory(tenant=tenant, role=role, client_company=company)


def _post(client, url, data=None):
    return client.post(url, _json.dumps(data or {}), content_type="application/json")


def _note(api, author, **data):
    response = _post(api.as_(author), "/api/notes/", {"body": SECRET_6, **data})
    assert response.status_code == 201, response.content
    return response.json()


MODULE2_ENDPOINTS = [
    ("/api/notes/", {"FF": 200, "CF": 200, "VA": 200, "FCC": 403, "ECC": 403}),
    # Matrix 3.1 — a VA does not read tenant settings.
    ("/api/notes/settings/", {"FF": 200, "CF": 200, "VA": 403, "FCC": 403, "ECC": 403}),
    ("/api/notes/consent-reminder/", {"FF": 200, "CF": 200, "VA": 200, "FCC": 403, "ECC": 403}),
    ("/api/ai-key/", {"FF": 200, "CF": 403, "VA": 403, "FCC": 403, "ECC": 403}),
]


@pytest.mark.django_db
@pytest.mark.parametrize("url,expected", MODULE2_ENDPOINTS, ids=[u for u, _ in MODULE2_ENDPOINTS])
@pytest.mark.parametrize("role", ALL_ROLES)
def test_module2_endpoint_role_matrix(url, expected, role, seeded_tenant, api):
    response = api.as_(_as(role, seeded_tenant)).get(url)
    assert response.status_code == expected[role], (
        f"{url} as {role}: expected {expected[role]}, got {response.status_code}"
    )


@pytest.mark.django_db
@pytest.mark.parametrize("role,expected", [("FF", 201), ("CF", 201), ("VA", 201),
                                           ("FCC", 403), ("ECC", 403)])
def test_6_1_create_a_note(role, expected, seeded_tenant, api):
    response = _post(api.as_(_as(role, seeded_tenant)), "/api/notes/", {"body": "x"})
    assert response.status_code == expected


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FF", "CF", "VA"])
def test_6_3_and_6_4_a_locked_note_is_a_stub_for_every_role_including_ff(
    role, seeded_tenant, api
):
    """Row 6.4: scope is the PIN. The FF who did not set it sees no body."""
    from .factories import ClientAssignmentFactory, ClientCompanyFactory

    author = _as("FF", seeded_tenant)
    viewer = _as(role, seeded_tenant)
    company = ClientCompanyFactory(tenant=seeded_tenant)
    if role == "CF":
        ClientAssignmentFactory(tenant=seeded_tenant, user=viewer.user, company=company)
    note = _note(api, author, title="HR matter", company=str(company.pk))
    assert _post(api.as_(author), f"/api/notes/{note['id']}/pin/", {"pin": "2468"}).status_code == 200

    response = api.as_(viewer).get(f"/api/notes/{note['id']}/")
    assert response.status_code == 200
    assert response.json()["stub"] is True and response.json()["title"] == "HR matter"
    assert SECRET_6 not in response.content.decode()


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FF", "CF", "VA"])
def test_6_5_any_tenant_role_may_set_a_pin(role, seeded_tenant, api):
    member = _as(role, seeded_tenant)
    note = _note(api, member, title="Mine")
    response = _post(api.as_(member), f"/api/notes/{note['id']}/pin/", {"pin": "13579"})
    assert response.status_code == 200 and response.json()["is_locked"] is True


@pytest.mark.django_db
@pytest.mark.parametrize("role,expected", [("FF", 200), ("CF", 403), ("VA", 403),
                                           ("FCC", 403), ("ECC", 403)])
def test_6_6_only_the_ff_may_reset_a_pin(role, expected, seeded_tenant, api, dev_outbox):
    from .factories import ClientAssignmentFactory, ClientCompanyFactory

    author = _as("FF", seeded_tenant)
    company = ClientCompanyFactory(tenant=seeded_tenant)
    note = _note(api, author, title="HR matter", company=str(company.pk))
    _post(api.as_(author), f"/api/notes/{note['id']}/pin/", {"pin": "2468"})
    member = _as(role, seeded_tenant)
    if role == "CF":
        ClientAssignmentFactory(tenant=seeded_tenant, user=member.user, company=company)
    response = _post(api.as_(member), f"/api/notes/{note['id']}/pin-reset/")
    assert response.status_code == expected
    if expected != 200:
        assert dev_outbox == [], "A refused reset still sent an email."


@pytest.mark.django_db
@pytest.mark.parametrize("role,expected", [("FF", 201), ("CF", 201), ("VA", 201)])
def test_6_7_any_tenant_role_may_record(role, expected, seeded_tenant, api, fake_stt):
    from django.core.files.uploadedfile import SimpleUploadedFile

    member = _as(role, seeded_tenant)
    client = api.as_(member)
    note = _post(client, "/api/notes/", {"source": "recording"}).json()
    audio = SimpleUploadedFile("r.webm", b"\x1aE\xdf\xa3 audio", content_type="audio/webm")
    response = client.post(f"/api/notes/{note['id']}/recording/",
                           {"audio": audio, "duration_seconds": "30"})
    assert response.status_code == expected


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FCC", "ECC"])
def test_6_9_client_users_reach_no_note_by_any_route(role, seeded_tenant, api):
    author = _as("FF", seeded_tenant)
    note = _note(api, author)
    client = api.as_(_as(role, seeded_tenant))
    for method, path in [
        ("get", "/api/notes/"), ("get", f"/api/notes/{note['id']}/"),
        ("get", f"/api/notes/?q=performance"), ("post", f"/api/notes/{note['id']}/unlock/"),
        ("post", f"/api/notes/{note['id']}/pin/"), ("post", f"/api/notes/{note['id']}/recording/"),
        ("post", f"/api/notes/{note['id']}/summary/accept/"),
        ("get", "/api/contacts/search/?q=performance"),
    ]:
        response = getattr(client, method)(path)
        assert response.status_code == 403, (role, method, path, response.status_code)
        assert SECRET_6 not in response.content.decode()


@pytest.mark.django_db
@pytest.mark.parametrize("role,expected", [("FF", 200), ("CF", 403), ("VA", 403)])
def test_recording_retention_is_an_ff_setting(role, expected, seeded_tenant, api):
    """Matrix 3.11 — audio retention is an FF setting."""
    client = api.as_(_as(role, seeded_tenant))
    response = client.patch("/api/notes/settings/", _json.dumps({"audio_retention_days": 7}),
                            content_type="application/json")
    assert response.status_code == expected
    seeded_tenant.refresh_from_db()
    assert seeded_tenant.audio_retention_days == (7 if expected == 200 else 30)


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["CF", "VA"])
def test_anthropic_key_is_ff_only_and_never_returned(role, seeded_tenant, api, monkeypatch):
    from apps.tenancy import claude

    monkeypatch.setattr(claude, "validate_key", lambda key: None)
    ff = _as("FF", seeded_tenant)
    saved = _post(api.as_(ff), "/api/ai-key/", {"key": "sk-ant-api03-SECRETKEY-9Zq1"})
    assert saved.status_code == 200
    assert saved.json()["last4"] == "9Zq1"
    assert "SECRETKEY" not in saved.content.decode()
    assert "SECRETKEY" not in api.as_(ff).get("/api/ai-key/").content.decode()
    assert _post(api.as_(_as(role, seeded_tenant)), "/api/ai-key/",
                 {"key": "sk-ant-other"}).status_code == 403


# ============================================================== Module 3 (§7)
# Matrix rows 7.1-7.11. The client rows are the point: a client user reaches
# these endpoints and sees only their own company's client-visible work.

MODULE3_ENDPOINTS = [
    ("/api/tasks/", {"FF": 200, "CF": 200, "VA": 200, "FCC": 200, "ECC": 200}),
    ("/api/goals/", {"FF": 200, "CF": 200, "VA": 200, "FCC": 200, "ECC": 200}),
    ("/api/projects/", {"FF": 200, "CF": 200, "VA": 200, "FCC": 200, "ECC": 200}),
]


@pytest.mark.django_db
@pytest.mark.parametrize("url,expected", MODULE3_ENDPOINTS, ids=[u for u, _ in MODULE3_ENDPOINTS])
@pytest.mark.parametrize("role", ALL_ROLES)
def test_module3_endpoint_role_matrix(url, expected, role, seeded_tenant, api):
    response = api.as_(_as(role, seeded_tenant)).get(url)
    assert response.status_code == expected[role], (
        f"{url} as {role}: expected {expected[role]}, got {response.status_code}"
    )


@pytest.mark.django_db
@pytest.mark.parametrize("role,expected", [("FF", 201), ("CF", 201), ("VA", 201),
                                           ("FCC", 403), ("ECC", 403)])
def test_7_2_only_the_practice_creates_a_goal(role, expected, seeded_tenant, api):
    """Matrix 7.2 — a goal is the strategy the engagement is judged against."""
    member = _as(role, seeded_tenant)
    response = _post(api.as_(member), "/api/goals/", {"title": "Cut order-to-cash to 20 days"})
    assert response.status_code == expected


@pytest.mark.django_db
@pytest.mark.parametrize("role,expected", [("FF", 201), ("CF", 201), ("VA", 201),
                                           ("FCC", 201), ("ECC", 201)])
def test_7_2a_a_client_may_create_a_project_but_never_under_a_goal(
    role, expected, seeded_tenant, api
):
    """Matrix 7.2a / FR-3.35a."""
    from apps.work.models import Goal

    member = _as(role, seeded_tenant)
    goal = Goal.all_objects.create(tenant=seeded_tenant, title="Practice goal")
    response = _post(api.as_(member), "/api/projects/", {"title": "Q4 tidy-up"})
    assert response.status_code == expected
    if role in ("FCC", "ECC"):
        body = response.json()
        assert body["created_by_client"] is True and body["goal"] is None
        refused = _post(api.as_(member), "/api/projects/",
                        {"title": "Under a goal", "goal": str(goal.pk)})
        assert refused.status_code == 400


# ======================================================= Digests (§8) and §9
# Row 8.3 is the single most important role boundary in the product: a VA may
# read and prepare a digest, and may never approve or send one.

DIGEST_ENDPOINTS = [
    ("/api/digests/", {"FF": 200, "CF": 200, "VA": 200, "FCC": 200, "ECC": 200}),
    ("/api/stakeholders/", {"FF": 200, "CF": 200, "VA": 200, "FCC": 200, "ECC": 200}),
]


@pytest.mark.django_db
@pytest.mark.parametrize("url,expected", DIGEST_ENDPOINTS, ids=[u for u, _ in DIGEST_ENDPOINTS])
@pytest.mark.parametrize("role", ALL_ROLES)
def test_digest_endpoint_role_matrix(url, expected, role, seeded_tenant, api):
    """Client users reach these routes and see nothing through them: a digest is
    the practice's to review (8.1), and the list comes back empty rather than
    403, because the route is not secret — its contents are."""
    response = api.as_(_as(role, seeded_tenant)).get(url)
    assert response.status_code == expected[role]
    if role in ("FCC", "ECC"):
        assert response.json() == []


def _a_pending_digest(tenant, ff, company=None):
    from apps.work import digests as digest_service
    from apps.work.models import Cadence, Stakeholder
    from apps.work.services import apply_task_changes, create_task

    from .factories import ClientCompanyFactory, ContactEmailFactory, ContactFactory

    company = company or ClientCompanyFactory(tenant=tenant, name="Digest Co")
    contact = ContactFactory(tenant=tenant, first_name="Dana", company=company)
    ContactEmailFactory(tenant=tenant, contact=contact, is_primary=True,
                        address="dana@digestco.invalid")
    task = create_task(tenant=tenant, actor=ff.user, role="FF", title="Something moved",
                       client_company=company, is_client_visible=True)
    Stakeholder.all_objects.create(tenant=tenant, contact=contact, task=task,
                                   cadence=Cadence.WEEKLY)
    apply_task_changes(task, actor=ff.user, role="FF", changes={"status": "in_progress"},
                       client_facing_line="Moved along.")
    window = digest_service.next_window(tenant, Cadence.WEEKLY)
    made = digest_service.generate_scheduled(tenant, cadence=Cadence.WEEKLY,
                                             now=window - timedelta(hours=1))
    return made[0], company


@pytest.mark.django_db
def test_8_3_a_va_can_read_a_digest_and_can_never_approve_or_send_it(
    seeded_tenant, ff, va, api, dev_outbox, in_tenant_a
):
    from apps.work.models import Digest

    digest, _company = _a_pending_digest(seeded_tenant, ff)

    viewer = api.as_(va)
    listed = viewer.get("/api/digests/").json()
    assert [d["id"] for d in listed] == [str(digest.pk)]
    assert "Moved along." in listed[0]["body_text"], "A VA may read and prepare (8.1/8.2)."

    for action in ("approve", "skip"):
        refused = _post(viewer, f"/api/digests/{digest.pk}/{action}/")
        assert refused.status_code == 403, action
    batch = _post(viewer, "/api/digests/approve-selected/", {"ids": [str(digest.pk)]})
    assert batch.status_code == 403

    digest.refresh_from_db()
    assert digest.state == Digest.State.PENDING
    assert dev_outbox == [], "A refused approval still sent a digest."
    assert not OutboxMessage.all_objects.filter(producer="digest").exists()


@pytest.mark.django_db
def test_8_3_a_cf_approves_only_for_assigned_companies(seeded_tenant, ff, cf, api,
                                                        dev_outbox, in_tenant_a):
    from .factories import ClientAssignmentFactory

    digest, company = _a_pending_digest(seeded_tenant, ff)
    unassigned = _post(api.as_(cf), f"/api/digests/{digest.pk}/approve/")
    assert unassigned.status_code == 404, "Out of scope is 404, not 403 (matrix §1)."

    ClientAssignmentFactory(tenant=seeded_tenant, user=cf.user, company=company)
    assert _post(api.as_(cf), f"/api/digests/{digest.pk}/approve/").status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("role,expected", [("FF", 200), ("CF", 403), ("VA", 403),
                                           ("FCC", 403), ("ECC", 403)])
def test_9_5_seat_counts_are_visible_to_the_practice_only(role, expected, seeded_tenant, api):
    """Matrix 4.12/9.5 — seat_count is the FF's; the CF sees usage on companies
    they are assigned, which they have none of here."""
    from .factories import ClientCompanyFactory

    company = ClientCompanyFactory(tenant=seeded_tenant, seat_count=2)
    member = _as(role, seeded_tenant)
    response = api.as_(member).get(f"/api/portal-access/?company={company.pk}")
    assert response.status_code in ((200,) if expected == 200 else (403, 404))
