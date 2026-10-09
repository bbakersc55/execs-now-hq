"""The demo environment (owner, 2026-09-29): a seeded fictional practice that
reads nothing and runs no worker, and sends nothing unless it has its redirect
(tests/test_demo_mail_redirect.py)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import CommandError, call_command

from . import registry_config  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent


def _name():
    return settings.DATABASES["default"]["NAME"]


# ================================================================= the seed

@pytest.mark.django_db
def test_the_seed_refuses_outside_the_demo(settings):
    settings.APP_ENVIRONMENT = "local"
    with pytest.raises(CommandError, match="not 'demo'"):
        call_command("seed_demo", database=_name(), ff_email="ff@example.invalid")


@pytest.mark.django_db
def test_the_seed_refuses_the_laptops_production_database(settings, monkeypatch):
    settings.APP_ENVIRONMENT = "demo"
    monkeypatch.setitem(settings.DATABASES["default"], "NAME", "execsnowhq_dev")
    with pytest.raises(CommandError, match="production database"):
        call_command("seed_demo", database="execsnowhq_dev", ff_email="ff@example.invalid")


@pytest.mark.django_db
def test_the_seed_refuses_a_mistyped_database(settings, tenant_a):
    from apps.tenancy.models import Tenant

    settings.APP_ENVIRONMENT = "demo"
    with pytest.raises(CommandError, match="You typed"):
        call_command("seed_demo", database="somewhere_else", ff_email="ff@example.invalid")
    assert Tenant.objects.filter(pk=tenant_a.pk).exists(), "nothing was emptied"


# What the seed makes, and that a re-run resets it: tests/test_demo_seed.py.


# ============================================================ the guards

@pytest.mark.django_db
def test_the_demo_sends_nothing(settings, seeded_tenant, in_tenant_a, monkeypatch, ff):
    """Even an approved message goes to the dev transport, never Gmail."""
    from apps.crm.models import OutboxMessage
    from apps.crm.services import outbox, transport

    from .factories import OutboxMessageFactory

    settings.IS_DEMO, settings.IS_LOCAL = True, False
    settings.EMAIL_BACKEND = "django.core.mail.backends.dummy.EmailBackend"
    monkeypatch.setattr(transport.GmailTransport, "send",
                        lambda *a, **k: pytest.fail("the demo reached Gmail"))
    message = OutboxMessageFactory(tenant=seeded_tenant,
                                   state=OutboxMessage.State.PENDING_APPROVAL)
    outbox.approve(message, actor=ff.user, role="FF")
    message.refresh_from_db()
    assert message.state == OutboxMessage.State.SENT


@pytest.mark.django_db
def test_the_demo_reads_no_drive_and_no_mailbox(settings, seeded_tenant, in_tenant_a):
    from apps.crm.services import inbound_poll
    from apps.meetings import ingest

    settings.APP_ENVIRONMENT = "demo"
    with pytest.raises(ingest.NotConnected, match="This is the demo"):
        ingest.poll(seeded_tenant)
    with pytest.raises(inbound_poll.NotConnected, match="This is the demo"):
        inbound_poll.poll(seeded_tenant)


@pytest.mark.django_db
def test_the_demo_connects_no_google_account(settings, seeded_tenant, in_tenant_a, ff, api):
    settings.APP_ENVIRONMENT = "demo"
    client = api.as_(ff)
    assert client.post("/api/gmail-connection/start/").status_code == 409
    assert client.post("/api/drive-watch/consent/").status_code == 409


def test_the_demo_runs_no_worker(settings, monkeypatch):
    from config import checks

    settings.IS_DEMO = True
    monkeypatch.setattr(sys, "argv", ["manage.py", "qcluster"])
    [error] = checks.no_worker_in_the_demo(None)
    assert error.id == "execsnowhq.E002"
    monkeypatch.setattr(sys, "argv", ["manage.py", "runserver"])
    assert checks.no_worker_in_the_demo(None) == []


@pytest.mark.django_db
def test_staff_are_told_it_is_the_demo(settings, seeded_tenant, ff, api):
    settings.APP_ENVIRONMENT = "demo"
    assert api.as_(ff).get("/api/me").json()["environment"] == "demo"


# ============================================== settings, booted for real

BOOT = {
    "PUBLIC_BASE_URL": "https://demo.getexecutivesnow.com",
    "DJANGO_SECRET_KEY": "a-demo-key", "DJANGO_DEBUG": "False",
    "DJANGO_ALLOWED_HOSTS": "demo.getexecutivesnow.com",
    "DEV_REAL_SEND_ALLOWLIST": "", "ANTHROPIC_API_KEY": "",
    "APP_ENVIRONMENT": "demo", "GCS_BUCKET_MEDIA": "execs-now-hq-demo-media",
    # As the demo sets it (runbook A4). Unset, the boot inherits the laptop's
    # .env, which is STORAGE_BACKEND=local since B7.
    "STORAGE_BACKEND": "gcs",
}
PROBE = ("import django; django.setup(); from django.conf import settings as s; "
         "print(s.APP_ENVIRONMENT, s.IS_DEMO, s.EMAIL_BACKEND)")


def _boot(**overrides):
    env = {**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings", **BOOT, **overrides}
    return subprocess.run([sys.executable, "-c", PROBE], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=60)


def test_the_demo_boots_with_its_own_bucket_and_a_mail_backend_that_discards():
    done = _boot()
    assert done.returncode == 0, done.stderr[-1500:]
    assert done.stdout.split()[-3:] == ["demo", "True",
                                        "django.core.mail.backends.dummy.EmailBackend"]


def test_the_demo_refuses_the_production_media_bucket():
    done = _boot(GCS_BUCKET_MEDIA="execs-now-hq-media")
    assert done.returncode != 0 and "production media bucket" in done.stderr


def test_an_environment_that_contradicts_the_host_is_refused():
    assert "APP_ENVIRONMENT is local" in _boot(APP_ENVIRONMENT="local").stderr
    assert "must be local, demo or production" in _boot(APP_ENVIRONMENT="staging").stderr
