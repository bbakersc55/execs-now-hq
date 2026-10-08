"""A practice's logo whose file is not there (2026-10-08).

The row can exist and the file not: a laptop's database is a copy of
production's, and production's bucket is not on the laptop. The sidebar showed
a broken-image icon beside the practice's name as alt text.

The path was never wrong. The pages Django renders itself now ask storage
first and show the practice's name as text; the app's own screens do the same
in the browser when the image fails (`frontend/src/screens/Shell.test.tsx`).
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.accounts.models import MagicLinkToken
from apps.tenancy import storage

from . import registry_config  # noqa: F401
from .factories import ClientCompanyFactory, MembershipFactory, StoredFileFactory

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture
def practice_with_logo(seeded_tenant, in_tenant_a):
    logo = StoredFileFactory(tenant=seeded_tenant, content=PNG, content_type="image/png",
                             purpose="email_logo", object_key="branding/logo.png")
    seeded_tenant.email_logo = logo
    seeded_tenant.save(update_fields=["email_logo"])
    return seeded_tenant


@pytest.fixture
def link(practice_with_logo):
    company = ClientCompanyFactory(tenant=practice_with_logo)
    member = MembershipFactory(tenant=practice_with_logo, role="FCC", client_company=company)
    _, raw = MagicLinkToken.issue(tenant=practice_with_logo, user=member.user)
    return member, raw


def lose_the_file(tenant):
    """What a scrubbed copy of production looks like: the row, and no object."""
    storage._backend().delete(tenant.email_logo.bucket, tenant.email_logo.object_key)
    assert tenant.email_logo_id and not storage.exists(tenant.email_logo)


@pytest.mark.django_db
def test_the_sign_in_page_draws_the_logo_when_its_file_is_there(link):
    _, raw = link
    html = Client().get(f"/auth/magic/{raw}").content.decode()
    assert '<img src="/api/branding/logo"' in html
    assert "<h1>" not in html


@pytest.mark.django_db
def test_the_sign_in_page_shows_the_name_as_text_when_the_file_is_missing(
    link, practice_with_logo
):
    lose_the_file(practice_with_logo)
    _, raw = link
    html = Client().get(f"/auth/magic/{raw}").content.decode()
    assert "<img" not in html, "It drew an image that cannot load."
    assert "<h1>Tenant A</h1>" in html


@pytest.mark.django_db
def test_the_logo_address_was_right_all_along_and_says_not_found_without_the_file(
    link, practice_with_logo, api
):
    member, _ = link
    # The app is still told where the logo is: the address is the same one
    # that serves it when the file exists.
    assert api.as_(member).get("/api/branding").json()["logo_url"] == "/api/branding/logo"
    served = api.as_(member).get("/api/branding/logo")
    assert served.status_code == 200 and served.content == PNG

    lose_the_file(practice_with_logo)
    assert api.as_(member).get("/api/branding").json()["logo_url"] == "/api/branding/logo"
    assert api.as_(member).get("/api/branding/logo").status_code == 404


@pytest.mark.django_db
def test_storage_being_unreachable_is_also_just_the_name(link, practice_with_logo,
                                                         monkeypatch):
    def down(stored_file):
        raise storage.StorageUnavailable("The bucket did not answer.")

    monkeypatch.setattr(storage, "exists", down)
    _, raw = link
    page = Client().get(f"/auth/magic/{raw}")
    assert page.status_code == 200
    assert "<img" not in page.content.decode() and "<h1>Tenant A</h1>" in page.content.decode()
