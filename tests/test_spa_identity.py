"""P1: the server writes the tab's title and icon into index.html per session,
so a client never sees the product's name or icon, not even while the app
loads (config/spa.py `with_identity`)."""

from __future__ import annotations

import pytest
from django.test import RequestFactory

from config.branding import PRODUCT_NAME
from config.spa import with_identity

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import ClientCompanyFactory

SHELL = ('<html><head><title>Portal</title>'
         '<link rel="icon" href="/api/branding/mark" /></head><body></body></html>')


def page(membership=None):
    request = RequestFactory().get("/work")
    request.membership = membership
    return with_identity(SHELL, request)


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FF", "CF", "VA"])
def test_staff_get_the_product_name_and_icon(seeded_tenant, role):
    html = page(_member(seeded_tenant, role))
    assert f"<title>{PRODUCT_NAME}</title>" in html
    assert "/static/brand/favicon.ico" in html and "/api/branding/mark" not in html


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FCC", "ECC"])
def test_a_client_gets_the_practice_name_and_mark_and_never_the_product(seeded_tenant, role):
    seeded_tenant.email_display_name = "Acme Advisory"
    seeded_tenant.save()
    html = page(_member(seeded_tenant, role, ClientCompanyFactory(tenant=seeded_tenant)))
    assert "<title>Acme Advisory</title>" in html
    assert '<link rel="icon" href="/api/branding/mark" />' in html
    assert PRODUCT_NAME not in html and "/static/brand/" not in html


@pytest.mark.django_db
def test_each_practice_gets_its_own_name(seeded_tenant, tenant_b):
    tenant_b.email_display_name = "Blue Sky"
    tenant_b.save()
    html = page(_member(tenant_b, "FCC", ClientCompanyFactory(tenant=tenant_b)))
    assert "<title>Blue Sky</title>" in html and "Tenant A" not in html


@pytest.mark.django_db
def test_a_signed_out_visitor_never_gets_the_product(seeded_tenant):
    html = page(None)
    assert PRODUCT_NAME not in html and "/static/brand/" not in html


@pytest.mark.django_db
def test_a_practice_name_is_escaped(seeded_tenant):
    seeded_tenant.email_display_name = "<script>x</script> & Co"
    seeded_tenant.save()
    html = page(_member(seeded_tenant, "FCC", ClientCompanyFactory(tenant=seeded_tenant)))
    assert "<script>x" not in html and "&lt;script&gt;" in html


@pytest.mark.django_db
def test_the_practices_area_gets_the_product_name_and_icon(seeded_tenant):
    owner = _member(seeded_tenant, "FF")
    request = RequestFactory().get("/practices")
    request.membership, request.area = None, "platform"
    html = with_identity(SHELL, request)
    assert f"<title>{PRODUCT_NAME}</title>" in html and "/static/brand/favicon.ico" in html
    assert owner  # the practice exists; the Practices area still names none of it
