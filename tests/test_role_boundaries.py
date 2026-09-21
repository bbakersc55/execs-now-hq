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


@pytest.mark.django_db
@pytest.mark.parametrize("role,sees_usage", [("FF", True), ("CF", True), ("VA", False)])
def test_9_5_the_companies_api_gives_seat_usage_to_ff_and_cf_only(role, sees_usage,
                                                                 seeded_tenant, api):
    """Matrix 9.5 — a VA reads companies (4.7) but not how many seats are in
    use, on every route that serializes a company: list, detail and search."""
    from .factories import ClientAssignmentFactory, ClientCompanyFactory

    company = ClientCompanyFactory(tenant=seeded_tenant, name="Seatholder Foods", seat_count=3)
    MembershipFactory(tenant=seeded_tenant, role="ECC", client_company=company)
    member = _as(role, seeded_tenant)
    if role == "CF":
        ClientAssignmentFactory(tenant=seeded_tenant, user=member.user, company=company)
    client = api.as_(member)

    listed = [c for c in client.get("/api/companies/").json() if c["id"] == str(company.pk)]
    detail = client.get(f"/api/companies/{company.pk}/").json()
    found = [c for c in client.get("/api/contacts/search/?q=Seatholder").json()["companies"]
             if c["id"] == str(company.pk)]
    assert len(listed) == 1 and len(found) == 1, "The company must be reachable to test this."

    for row in (listed[0], detail, found[0]):
        if sees_usage:
            assert row["seats_in_use"] == 1 and row["seats_available"] == 2
        else:
            assert "seats_in_use" not in row and "seats_available" not in row


# ------------------------------------- the company filter obeys role scope

@pytest.mark.django_db
def test_the_company_filter_cannot_widen_what_a_cf_may_see(seeded_tenant, ff, cf, api):
    """Matrix 7.1 — the filter narrows a queryset that role scoping has already
    decided. Naming an unassigned company asks for nothing, not for more: a
    filter that could reach past the scope would be the scope. What the CF does
    keep across that line is `own-work`, asserted at the end."""
    from .factories import ClientAssignmentFactory, ClientCompanyFactory

    assigned = ClientCompanyFactory(tenant=seeded_tenant, name="Assigned")
    unassigned = ClientCompanyFactory(tenant=seeded_tenant, name="Not assigned")
    ClientAssignmentFactory(tenant=seeded_tenant, user=cf.user, company=assigned)

    staff = api.as_(ff)
    _post(staff, "/api/tasks/", {"title": "Mine", "client_company": str(assigned.pk)})
    _post(staff, "/api/tasks/", {"title": "Theirs", "client_company": str(unassigned.pk)})
    _post(staff, "/api/tasks/", {"title": "Internal, and assigned to me",
                                 "assignee": str(cf.user_id)})
    _post(staff, "/api/tasks/", {"title": "Internal, and nothing to do with me"})

    viewer = api.as_(cf)
    assert sorted(t["title"] for t in viewer.get("/api/tasks/").json()) == [
        "Internal, and assigned to me", "Mine",
    ]
    assert viewer.get(f"/api/tasks/?client_company={unassigned.pk}").json() == []
    assert [t["title"] for t in
            viewer.get(f"/api/tasks/?client_company={assigned.pk}").json()] == ["Mine"]
    # Internal is a real side of the dimension for a CF, not a dead option: a
    # task with no company still reaches them by matrix 7.1's `own-work` arm.
    # One that reaches them by neither does not.
    assert [t["title"] for t in viewer.get("/api/tasks/?client_company=internal").json()] == [
        "Internal, and assigned to me",
    ]


@pytest.mark.django_db
def test_a_client_user_naming_another_company_still_sees_only_their_own(seeded_tenant, ff,
                                                                        fcc, api):
    """FR-0.2 — the portal sends no company filter, but the route is open to a
    client user and a hand-written one must not become a way out of the company."""
    from .factories import ClientCompanyFactory

    other = ClientCompanyFactory(tenant=seeded_tenant, name="Somebody else")
    staff = api.as_(ff)
    _post(staff, "/api/tasks/", {"title": "Ours", "client_company": str(fcc.client_company_id),
                                 "is_client_visible": True})
    _post(staff, "/api/tasks/", {"title": "Not ours", "client_company": str(other.pk),
                                 "is_client_visible": True})
    _post(staff, "/api/tasks/", {"title": "The practice's own"})

    viewer = api.as_(fcc)
    assert [t["title"] for t in viewer.get("/api/tasks/").json()] == ["Ours"]
    assert viewer.get(f"/api/tasks/?client_company={other.pk}").json() == []
    assert viewer.get("/api/tasks/?client_company=internal").json() == []


# ================================================ §10A — Module 4B, value report
#
# The line this section draws, and the sixth weighted case in the matrix's
# §14.2: **a VA may administer and may not judge.** Both halves are asserted in
# the same test, against the API response body, so the boundary is shown to be a
# line and not a blanket refusal.

def _a_client_goal(tenant, company, **kwargs):
    from .factories import GoalFactory

    kwargs.setdefault("title", "Decisions stall waiting on the founder")
    return GoalFactory(tenant=tenant, client_company=company, **kwargs)


@pytest.mark.django_db
def test_10a_a_va_may_administer_and_may_not_judge(seeded_tenant, api, fake_claude):
    """Rows 10A.4, 10A.6, 10A.10, 10A.13 and 10A.15 in one case."""
    import json

    company = ClientCompanyFactory(tenant=seeded_tenant)
    ff = MembershipFactory(tenant=seeded_tenant, role=Role.FF)
    va = MembershipFactory(tenant=seeded_tenant, role=Role.VA)
    goal = _a_client_goal(seeded_tenant, company)
    api.as_(ff).post(f"/api/value-report/{goal.pk}/draft-narrative/")

    # Administration: a reading and an export are the VA's.
    assert api.as_(va).post("/api/goal-measurements/", json.dumps(
        {"goal": str(goal.pk), "value": "9"}),
        content_type="application/json").status_code == 201
    assert api.as_(va).post("/api/value-report-exports/", json.dumps(
        {"goal": str(goal.pk)}), content_type="application/json").status_code == 201

    # Judgement: three refusals, in the response body.
    resolved = api.as_(va).post("/api/goal-resolutions/", json.dumps(
        {"goal": str(goal.pk), "resolution": "achieved", "reason": "Done."}),
        content_type="application/json")
    assert resolved.status_code == 403 and "fractional's call" in resolved.json()["detail"]

    accepted = api.as_(va).post(f"/api/value-report/{goal.pk}/accept-narrative/",
                                json.dumps({"body": "A VA's verdict."}),
                                content_type="application/json")
    assert accepted.status_code == 403

    statement = api.as_(va).patch(f"/api/goals/{goal.pk}/", json.dumps(
        {"outcome_statement": "A VA's sentence."}), content_type="application/json")
    assert statement.status_code == 400
    assert "fractional's sentence" in json.dumps(statement.json())

    from apps.work.models import GoalNarrativeVersion, GoalResolution

    assert GoalResolution.all_objects.filter(tenant=seeded_tenant).count() == 0
    assert GoalNarrativeVersion.all_objects.filter(tenant=seeded_tenant).count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize("role", sorted(CLIENT_ROLES))
def test_10a_client_roles_are_read_only_throughout(role, seeded_tenant, api):
    """Every row of §10A: a client reads the report and writes nothing in it.

    FR-3.35a gives them tasks and projects of their own precisely so the portal
    is a working tool; the value report is the opposite kind of artifact — the
    practice's account of the engagement, which a client reads and does not
    co-author.
    """
    import json

    company = ClientCompanyFactory(tenant=seeded_tenant)
    ff = MembershipFactory(tenant=seeded_tenant, role=Role.FF)
    client_user = MembershipFactory(tenant=seeded_tenant, role=role,
                                    client_company=company)
    goal = _a_client_goal(seeded_tenant, company)

    assert api.as_(client_user).get("/api/value-report/").status_code == 200
    assert api.as_(client_user).get(f"/api/value-report/{goal.pk}/").status_code == 200

    writes = [
        ("/api/goal-measurements/", {"goal": str(goal.pk), "value": "9"}),
        ("/api/goal-milestones/", {"goal": str(goal.pk), "title": "A beat"}),
        ("/api/goal-resolutions/", {"goal": str(goal.pk), "resolution": "achieved",
                                    "reason": "Done."}),
        ("/api/value-report-exports/", {"goal": str(goal.pk)}),
        (f"/api/value-report/{goal.pk}/draft-narrative/", {}),
        (f"/api/value-report/{goal.pk}/accept-narrative/", {"body": "Mine now."}),
    ]
    for url, payload in writes:
        response = api.as_(client_user).post(url, json.dumps(payload),
                                             content_type="application/json")
        assert response.status_code == 403, f"{url} as {role}: {response.status_code}"

    # And the exports list is not theirs to read: the portal is their copy.
    assert api.as_(client_user).get("/api/value-report-exports/").status_code == 403
    assert api.as_(ff).get(
        f"/api/value-report-exports/?client_company={company.pk}").status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("role", sorted(CLIENT_ROLES))
def test_10a_a_client_reaches_nothing_of_another_company_in_the_same_tenant(
    role, seeded_tenant, api
):
    """Matrix §14.2 case 3, extended to rows 10A.1–10A.2. **404, never 403.**"""
    mine = ClientCompanyFactory(tenant=seeded_tenant, name="Mine")
    theirs = ClientCompanyFactory(tenant=seeded_tenant, name="Theirs")
    client_user = MembershipFactory(tenant=seeded_tenant, role=role, client_company=mine)
    their_goal = _a_client_goal(seeded_tenant, theirs, title="Not yours")

    assert api.as_(client_user).get(
        f"/api/value-report/{their_goal.pk}/").status_code == 404
    # Naming their company returns the client's own report, never an empty one
    # and never theirs.
    mine_report = api.as_(client_user).get(
        f"/api/value-report/?client_company={theirs.pk}/")
    assert mine_report.status_code == 200
    assert "Not yours" not in mine_report.content.decode()


@pytest.mark.django_db
def test_10a_9_nobody_edits_a_derived_milestone_or_a_narrative_version(
    seeded_tenant, api, fake_claude, in_tenant_a
):
    """Rows 10A.9 and 10A.11a — the two "nobody, ever" rows in §10A."""
    import json

    from apps.work.models import GoalMilestone

    company = ClientCompanyFactory(tenant=seeded_tenant)
    ff = MembershipFactory(tenant=seeded_tenant, role=Role.FF)
    goal = _a_client_goal(seeded_tenant, company)

    from apps.work.services import create_task

    task = create_task(tenant=seeded_tenant, actor=ff.user, role="FF",
                       title="Area lead hired", client_company=company, goal=goal)
    made = api.as_(ff).post("/api/goal-milestones/", json.dumps(
        {"goal": str(goal.pk), "source_task": str(task.pk)}),
        content_type="application/json")
    assert made.status_code == 201

    refused = api.as_(ff).patch(f"/api/goal-milestones/{made.json()['id']}/",
                                json.dumps({"title": "Renamed"}),
                                content_type="application/json")
    assert refused.status_code == 409, "even an FF: the fact belongs to the task"
    assert GoalMilestone.all_objects.get(
        pk=made.json()["id"]).title == "Area lead hired"

    api.as_(ff).post(f"/api/value-report/{goal.pk}/draft-narrative/")
    api.as_(ff).post(f"/api/value-report/{goal.pk}/accept-narrative/",
                     json.dumps({"body": "What they were told."}),
                     content_type="application/json")
    versions = api.as_(ff).get(
        f"/api/value-report/{goal.pk}/narrative-versions/").json()
    assert len(versions) == 1
    for method in ("post", "patch", "delete"):
        response = getattr(api.as_(ff), method)(
            f"/api/value-report/{goal.pk}/narrative-versions/")
        assert response.status_code in (404, 405), method


@pytest.mark.django_db
@pytest.mark.parametrize("role,expected", [("FF", 200), ("CF", 404), ("VA", 403)])
def test_10a_6a_only_the_fractional_accepts_a_pro_or_a_con(role, expected, seeded_tenant,
                                                            api, in_tenant_a):
    """Matrix 10.6a — the decision page is judgement, like the map rows.

    A CF unassigned to the session's prospect gets 404, not 403: the row exists,
    and saying so would confirm it.
    """
    from apps.strategy.models import StrategyPathNote
    from apps.strategy.seed import seed_tenant
    from apps.strategy import services

    from .factories import ContactFactory

    template = seed_tenant(seeded_tenant)
    ff = MembershipFactory(tenant=seeded_tenant, role=Role.FF)
    prospect = ContactFactory(tenant=seeded_tenant)
    session = services.start(tenant=seeded_tenant, contact=prospect, template=template,
                             owner=ff.user)
    note = StrategyPathNote.objects.create(tenant=seeded_tenant, session=session,
                                           path="a", kind="pro", text="A pro.")
    membership = ff if role == "FF" else MembershipFactory(tenant=seeded_tenant, role=role)
    response = api.as_(membership).post(f"/api/strategy-path-notes/{note.pk}/accept/")
    assert response.status_code == expected
    note.refresh_from_db()
    assert (note.state == "accepted") is (expected == 200)
