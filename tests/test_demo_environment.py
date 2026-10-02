"""The demo environment (owner, 2026-09-29): a seeded fictional practice that
sends nothing, reads nothing, and runs no worker."""

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


@pytest.mark.django_db
def test_the_seed_builds_a_plausible_practice_and_resets_on_a_rerun(settings, tenant_a):
    from apps.crm.models import Company, Contact, ContactEmail
    from apps.meetings.models import MeetingProposal, ProposalItem
    from apps.strategy.models import StrategySession
    from apps.tenancy.models import Membership, StoredFile, Tenant
    from apps.work.models import Digest, Goal, Project
    from apps.crm.models import Task

    settings.APP_ENVIRONMENT = "demo"
    for _ in range(2):          # the second run is the reset
        call_command("seed_demo", database=_name(), ff_email="Founder@Example.invalid")

        assert list(Tenant.objects.values_list("slug", flat=True)) == ["summit-demo"], \
            "the reset emptied everything first, including what was there before"
        tenant = Tenant.objects.get()
        assert Membership.all_objects.filter(role="FF", user__email="founder@example.invalid"
                                             ).exists()
        assert Company.all_objects.filter(is_client_company=True).count() == 3
        assert Goal.all_objects.count() == 3 and Project.all_objects.count() == 5
        statuses = set(Task.all_objects.values_list("status", flat=True))
        assert {"done", "in_progress", "not_started", "blocked",
                "waiting_on_client"} <= statuses
        assert Digest.all_objects.filter(state="pending").count() >= 3, \
            "digests wait for approval (hold_all_digests is on)"
        session = StrategySession.all_objects.get()
        assert session.state == "complete"
        assert StoredFile.all_objects.filter(purpose="strategy_pdf").exists()
        assert MeetingProposal.all_objects.filter(state="pending").count() == 2
        assert ProposalItem.all_objects.filter(kind="action_item").count() == 4
        assert all(a.endswith((".example", ".invalid"))
                   for a in ContactEmail.all_objects.values_list("address", flat=True)), \
            "every address is at a domain that cannot receive mail"
        assert tenant.hold_all_digests is True
        assert Contact.all_objects.count() >= 10


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
