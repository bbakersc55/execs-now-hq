"""`manage.py dev_va_login` — the local-only way to act as a VA (Phase 2 Check 2)."""

from __future__ import annotations

import io

import pytest
from django.core.management import CommandError, call_command
from django.test import Client

from apps.tenancy.models import Membership

from . import registry_config  # noqa: F401


def _run(*args):
    out = io.StringIO()
    call_command("dev_va_login", *args, stdout=out)
    return out.getvalue()


@pytest.mark.django_db
def test_it_refuses_off_localhost(seeded_tenant, settings):
    settings.IS_LOCAL = False
    with pytest.raises(CommandError, match="not localhost"):
        _run()
    assert not Membership.all_objects.filter(user__email="va.localtest@example.invalid").exists()


@pytest.mark.django_db
def test_it_refuses_a_remote_database(seeded_tenant, settings):
    settings.DATABASES["default"]["HOST"] = "db.railway.internal"
    try:
        with pytest.raises(CommandError, match="not local"):
            _run()
    finally:
        settings.DATABASES["default"]["HOST"] = ""


@pytest.mark.django_db
def test_the_link_signs_a_browser_in_as_a_va_and_lands_in_the_app(seeded_tenant, settings):
    output = _run()
    membership = Membership.all_objects.get(user__email="va.localtest@example.invalid")
    assert membership.role == "VA" and membership.tenant_id == seeded_tenant.pk

    path = output.split(settings.PUBLIC_BASE_URL.rstrip("/"))[1].split()[0]
    browser = Client()
    assert browser.get(path).status_code == 200  # the landing page; nothing consumed
    landed = browser.post(path, HTTP_ACCEPT="text/html,application/xhtml+xml")
    assert landed.status_code == 302 and landed["Location"] == settings.APP_ROOT_URL
    assert browser.get("/api/me").json()["role"] == "VA"
    assert browser.get("/api/staff/").status_code == 403  # a VA, not an FF


@pytest.mark.django_db
def test_rerunning_reuses_the_account_and_remove_revokes_it(seeded_tenant):
    _run()
    _run()
    assert Membership.all_objects.filter(user__email="va.localtest@example.invalid").count() == 1
    _run("--remove")
    assert Membership.all_objects.get(user__email="va.localtest@example.invalid").revoked_at is not None
    _run()  # can be brought back for another round of checks
    assert Membership.all_objects.get(user__email="va.localtest@example.invalid").revoked_at is None
