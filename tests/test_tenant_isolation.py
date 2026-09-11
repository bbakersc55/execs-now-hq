"""Mandatory test family 1 — tenant isolation (CLAUDE.md, assumption B3).

Non-negotiable. Every registered model is exercised by the same parametrised
cases, so coverage cannot silently lapse when a module is added in a hurry.
"""

from __future__ import annotations

import pytest

from apps.tenancy.context import no_tenant_context, tenant_context
from apps.tenancy.models import TenantScopedModel
from apps.tenancy.registry import registered, registered_models

from . import registry_config  # noqa: F401

REGISTERED = registered()
IDS = sorted(REGISTERED)


def _make(entry, tenant):
    return entry.factory(tenant=tenant)


@pytest.mark.django_db
@pytest.mark.parametrize("key", IDS)
def test_tenant_a_cannot_see_tenant_b_rows(key, tenant_a, tenant_b):
    """The core promise: a user in tenant A can never see tenant B rows."""
    entry = REGISTERED[key]
    row_b = _make(entry, tenant_b)

    with tenant_context(tenant_a.pk):
        assert not entry.model.objects.filter(pk=row_b.pk).exists()
        assert entry.model.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize("key", IDS)
def test_tenant_sees_only_its_own_rows(key, tenant_a, tenant_b):
    entry = REGISTERED[key]
    row_a = _make(entry, tenant_a)
    _make(entry, tenant_b)

    with tenant_context(tenant_a.pk):
        pks = set(entry.model.objects.values_list("pk", flat=True))
    assert pks == {row_a.pk}


@pytest.mark.django_db
@pytest.mark.parametrize("key", IDS)
def test_update_cannot_cross_tenants(key, tenant_a, tenant_b):
    entry = REGISTERED[key]
    row_b = _make(entry, tenant_b)

    with tenant_context(tenant_a.pk):
        assert entry.model.objects.filter(pk=row_b.pk).update(**{}) == 0


@pytest.mark.django_db
@pytest.mark.parametrize("key", IDS)
def test_delete_cannot_cross_tenants(key, tenant_a, tenant_b):
    entry = REGISTERED[key]
    row_b = _make(entry, tenant_b)

    with tenant_context(tenant_a.pk):
        deleted, _ = entry.model.objects.filter(pk=row_b.pk).delete()
    assert deleted == 0
    assert entry.model.all_objects.filter(pk=row_b.pk).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("key", IDS)
def test_unscoped_query_raises_rather_than_leaking(key, tenant_b):
    """Assumption B1's whole point.

    With no tenant bound the manager RAISES. It does not return everything and
    it does not return nothing — either would let a forgotten filter ship.
    """
    from apps.tenancy.context import TenantContextMissing

    entry = REGISTERED[key]
    _make(entry, tenant_b)

    with no_tenant_context(), pytest.raises(TenantContextMissing):
        list(entry.model.objects.all())


@pytest.mark.django_db
def test_registry_completeness():
    """The meta-test. Fails when a model is added but not registered.

    This is what stops `03_access_matrix.md` and the code drifting apart.
    """
    from django.apps import apps as django_apps

    concrete = {
        f"{m._meta.app_label}.{m.__name__}"
        for m in django_apps.get_models()
        if issubclass(m, TenantScopedModel) and not m._meta.abstract
    }
    missing = concrete - set(REGISTERED)
    assert not missing, (
        "These tenant-scoped models are not in tests/registry_config.py and are "
        f"therefore untested for isolation: {sorted(missing)}"
    )


@pytest.mark.django_db
def test_registered_models_all_inherit_the_scoped_base():
    for model in registered_models():
        assert issubclass(model, TenantScopedModel)


@pytest.mark.django_db
def test_cross_tenant_foreign_key_is_rejected(tenant_a, tenant_b):
    """A task can never be assigned to a contact in another tenant."""
    from django.core.exceptions import ValidationError

    from .factories import ClientCompanyFactory, MembershipFactory

    company_b = ClientCompanyFactory(tenant=tenant_b)
    membership = MembershipFactory.build(
        tenant=tenant_a, role="FCC", client_company=company_b,
    )
    membership.user.save()
    with pytest.raises(ValidationError):
        membership.clean()


# ------------------------------------------------------ Module 2 — note API
# The registry tests above prove the managers. These prove the HTTP routes,
# including the ones that act on a note rather than read it.

@pytest.mark.django_db
def test_note_routes_are_isolated_across_tenants(tenant_a, tenant_b, api):
    import json

    from .factories import MembershipFactory, NoteFactory

    a_ff = MembershipFactory(tenant=tenant_a, role="FF")
    b_note = NoteFactory(tenant=tenant_b, title="Bravo", body="bravo body text")
    client = api.as_(a_ff)
    base = f"/api/notes/{b_note.pk}/"
    for method, path in [
        ("get", base), ("patch", base), ("delete", base),
        ("post", base + "pin/"), ("delete", base + "pin/"), ("post", base + "unlock/"),
        ("post", base + "lock/"), ("post", base + "pin-reset/"),
        ("post", base + "recording/"), ("post", base + "retry-transcription/"),
        ("post", base + "discard-audio/"), ("post", base + "summary/accept/"),
        ("post", base + "summary/discard/"), ("post", base + "summary/redraft/"),
    ]:
        response = client.generic(method.upper(), path, json.dumps({"pin": "1234"}),
                                  content_type="application/json")
        assert response.status_code == 404, (method, path, response.status_code)
    assert client.get("/api/notes/?q=bravo").json() == []
    b_note.refresh_from_db()
    assert b_note.deleted_at is None and b_note.body == "bravo body text"


@pytest.mark.django_db
def test_a_pin_reset_token_from_tenant_b_does_nothing_in_tenant_a(tenant_a, tenant_b, api):
    from django.utils import timezone

    from .factories import MembershipFactory, NoteFactory

    from apps.accounts.models import MagicLinkPurpose, MagicLinkToken

    b_ff = MembershipFactory(tenant=tenant_b, role="FF")
    b_note = NoteFactory(tenant=tenant_b, title="Bravo", body="x",
                         pin_hash="h", pin_set_at=timezone.now())
    _, raw = MagicLinkToken.issue(tenant=tenant_b, user=b_ff.user,
                                  purpose=MagicLinkPurpose.PIN_RESET,
                                  redirect_to=f"note:{b_note.pk}")
    a_ff = MembershipFactory(tenant=tenant_a, role="FF")
    for method in ("get", "post"):
        response = (api.as_(a_ff).get(f"/api/notes/pin-reset/confirm/?token={raw}")
                    if method == "get" else
                    api.as_(a_ff).post("/api/notes/pin-reset/confirm/", {"token": raw},
                                       content_type="application/json"))
        assert response.status_code in (400, 403, 404)
        assert "Bravo" not in response.content.decode()
    b_note.refresh_from_db()
    assert b_note.is_locked
