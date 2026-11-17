"""Web and the worker each say whether they can reach the card processor
(2026-11-17, `apps/billing/worker_state.py`).

On 2026-11-16 auto-pay passed over an invoice in production because real
calls were on in web and off in the worker, and nothing said so. These are
the guards: each service reports itself, a red warning shows in production
when the worker's calls are off or the two disagree, a refused job is
recorded and the platform owner told once a day, and `nmi_check` checks both.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from apps.billing import tasks, worker_state
from apps.billing.models import RefusedJob, ServiceReport
from apps.crm.models import OutboxMessage
from apps.notify.models import Notice

from . import registry_config  # noqa: F401
from .test_autopay import connected  # noqa: F401  (a fixture)
from .test_client_invoicing import ready_to_bill  # noqa: F401  (a fixture)
from .test_platform_practices import platform_owner, practices  # noqa: F401


def as_service(settings, service, *, live):
    settings.APP_SERVICE = service
    settings.NMI_LIVE_CALLS = live
    # The tests never reach the processor; this one only reads the setting.
    import apps.billing.gateway as gw

    return gw


@pytest.fixture
def live_reads(monkeypatch):
    """`live_calls_allowed` is always False under test; here it reads the
    setting, as it does in a running service."""
    import apps.billing.gateway as gw
    from django.conf import settings

    monkeypatch.setattr(gw, "under_test", lambda: False)
    monkeypatch.setattr(gw, "live_calls_allowed", lambda: bool(settings.NMI_LIVE_CALLS))


@pytest.mark.django_db
def test_each_service_reports_itself_and_a_shell_reports_nothing(settings, live_reads):
    settings.APP_SERVICE = ""
    worker_state.report()
    assert not ServiceReport.objects.exists()
    as_service(settings, "worker", live=False)
    worker_state.report()
    as_service(settings, "web", live=True)
    worker_state.report()
    rows = {r.service: r.live_calls for r in ServiceReport.objects.all()}
    assert rows == {"worker": False, "web": True}


@pytest.mark.django_db
def test_no_warning_off_production(settings, live_reads):
    settings.APP_ENVIRONMENT = "local"
    assert worker_state.state()["warning"] == ""


@pytest.mark.django_db
def test_the_warnings_in_production(settings, live_reads):
    settings.APP_ENVIRONMENT = "production"
    as_service(settings, "web", live=True)
    assert "has not reported" in worker_state.state()["warning"]
    now = timezone.now()
    ServiceReport.objects.create(service="worker", live_calls=False,
                                 app_environment="production", reported_at=now)
    off = worker_state.state()
    assert "OFF in the worker" in off["warning"] and "Web has them on" in off["warning"]
    assert off["worker"]["live_calls"] is False and off["web_live_calls"] is True
    ServiceReport.objects.filter(service="worker").update(live_calls=True)
    assert worker_state.state()["warning"] == ""
    as_service(settings, "web", live=False)
    assert "disagree" in worker_state.state()["warning"]
    as_service(settings, "web", live=True)
    ServiceReport.objects.filter(service="worker").update(
        reported_at=now - timedelta(minutes=45))
    assert "last reported 45 minutes ago" in worker_state.state()["warning"]


@pytest.mark.django_db
def test_settings_billing_and_practices_show_it(settings, live_reads, api, ff, platform_owner):
    settings.APP_ENVIRONMENT = "production"
    as_service(settings, "web", live=True)
    ServiceReport.objects.create(service="worker", live_calls=False,
                                 app_environment="production", reported_at=timezone.now())
    billing = api.as_(ff).get("/api/payment-account/").json()
    assert billing["worker"]["warning"].startswith("Scheduled card charges aren't running")
    assert "NMI_LIVE_CALLS" not in billing["worker"]["warning"]    # the owner's words
    area = practices(api, platform_owner).get("/api/platform/card-payments/").json()
    assert "NMI_LIVE_CALLS" in area["worker"]["warning"]


@pytest.mark.django_db
def test_a_refused_job_is_recorded_and_the_platform_owner_told_once_a_day(
        settings, connected, platform_owner):
    """Production with real calls off where the job runs: what the worker
    was on 2026-11-16."""
    settings.APP_ENVIRONMENT = "production"
    settings.APP_SERVICE = "worker"
    before = OutboxMessage.all_objects.count()
    tasks.run_autopay(str(connected.pk))
    tasks.run_autopay(str(connected.pk))
    tasks.read_back_nmi(str(connected.pk))
    [autopay_row] = RefusedJob.objects.filter(job="billing.run_autopay")
    assert autopay_row.count == 2 and autopay_row.tenant_id == connected.pk
    assert RefusedJob.objects.filter(job="billing.read_back_nmi").count() == 1
    assert ServiceReport.objects.get(service="worker").live_calls is False
    # Once a day: one Notice for each owner of the platform owner's practice.
    notices = Notice.all_objects.filter(source_type="refused_jobs")
    assert platform_owner.user_id in {n.recipient_id for n in notices}
    assert len(notices) == len({n.recipient_id for n in notices})
    assert {n.url for n in notices} == {"/practices"}
    told = OutboxMessage.all_objects.order_by("created_at")[before:]
    assert {m.subject for m in told} == {"Scheduled card jobs are being refused"}
    assert platform_owner.user.email in {m.to_address for m in told}
    assert len(told) == len(notices) and "qcluster" in told[0].body_text
    listed = worker_state.refused_today()
    assert {r["job"]: r["runs"] for r in listed} == {"billing.read_back_nmi": 1,
                                                     "billing.run_autopay": 2}


@pytest.mark.django_db
def test_a_practice_that_takes_no_cards_is_not_counted(settings, seeded_tenant, platform_owner):
    settings.APP_ENVIRONMENT = "production"
    settings.APP_SERVICE = "worker"
    tasks.run_autopay(str(seeded_tenant.pk))
    assert not RefusedJob.objects.exists()


@pytest.mark.django_db
def test_nothing_is_recorded_while_real_calls_are_allowed(settings, connected, live_reads):
    settings.APP_ENVIRONMENT = "production"
    as_service(settings, "worker", live=True)
    assert worker_state.job_refused("billing.run_autopay", connected) is False
    assert not RefusedJob.objects.exists()


@pytest.mark.django_db
def test_nmi_check_prints_both_services_and_fails_when_the_worker_is_off(settings, capsys):
    now = timezone.now()
    ServiceReport.objects.create(service="web", live_calls=True,
                                 app_environment="production", reported_at=now)
    ServiceReport.objects.create(service="worker", live_calls=False,
                                 app_environment="production", reported_at=now)
    with pytest.raises(CommandError) as refused:
        call_command("nmi_check")
    out = capsys.readouterr().out
    assert "web: real calls on" in out and "worker: real calls OFF" in out
    assert "qcluster" in str(refused.value)


@pytest.mark.django_db
def test_report_service_writes_this_services_row(settings, capsys):
    settings.APP_SERVICE = "worker"
    call_command("report_service")
    assert ServiceReport.objects.get(service="worker").live_calls is False
    assert "worker: real calls" in capsys.readouterr().out
