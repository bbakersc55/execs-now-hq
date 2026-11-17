"""Whether web and the worker can each reach the card processor (2026-11-17).

On 2026-11-16 auto-pay passed over an invoice in production because real
calls (`NMI_LIVE_CALLS`) were on in web and off in the worker, and nothing
said so: every scheduled job that charges or looks up a card ran in the worker
and was refused quietly. So:

- **Each service reports itself.** Its start script sets `APP_SERVICE` (web
  or worker) and runs `manage.py report_service`; the worker's billing jobs
  report again on each run (the ten-minute lookup keeps it fresh), and web
  reports whenever it shows the state. A shell or a test reports nothing.
- **A red warning, in production**, on Practices (the platform owner) and
  Settings → Billing (each practice owner), when the worker has real calls
  off, when web and the worker disagree, or when the worker hasn't reported
  for half an hour.
- **A refused job is recorded** (`RefusedJob`, per job, practice and day,
  counted) when a scheduled job that needs the processor runs where real
  calls are off, for a practice that takes cards; and the platform owner is
  told once a day, by a Notice and an email.
- `manage.py nmi_check` prints both services' reports and fails when they
  disagree or the worker's calls are off.

Nothing here changes a setting or a Railway variable.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, F, Sum
from django.utils import timezone
from django.utils.html import escape

from apps.billing import gateway as gw

log = logging.getLogger(__name__)

SERVICES = ("web", "worker")
#: The worker's ten-minute lookup reports; three missed is a warning.
STALE = timedelta(minutes=30)
_NAMESPACE = uuid.UUID("a3f6b4d2-7c1e-4b8a-9d20-5e6f7a8b9c01")

#: What the jobs are called on screen.
JOBS = {
    "billing.run_autopay": "Auto-pay and automatic billing charges (9:00)",
    "billing.resolve_card_payments": "Lookups of lost card answers (every 10 minutes)",
    "billing.read_back_nmi": "The daily read-back of the processor (6:00)",
    "billing.charge_subscription": "Practice subscription charges (7:00)",
    "billing.run_invoice_schedules": "Automatic invoices made and emailed (5:00)",
}


def this_service() -> str:
    service = getattr(settings, "APP_SERVICE", "") or ""
    return service if service in SERVICES else ""


def report() -> None:
    """This process's own row: whether it can reach the processor. Never
    raises: a report that can't be written is only logged."""
    from apps.billing.models import ServiceReport

    service = this_service()
    if not service:
        return
    fields = {"live_calls": gw.live_calls_allowed(),
              "app_environment": settings.APP_ENVIRONMENT, "reported_at": timezone.now()}
    try:
        with transaction.atomic():
            if not ServiceReport.objects.filter(service=service).update(**fields):
                ServiceReport.objects.create(service=service, **fields)
    except IntegrityError:
        ServiceReport.objects.filter(service=service).update(**fields)
    except Exception as exc:  # noqa: BLE001 — a report never breaks what it rides on
        log.warning("service report for %s not written (%s)", service, type(exc).__name__)


def _row(row, now) -> dict | None:
    if row is None:
        return None
    return {"live_calls": row.live_calls, "app_environment": row.app_environment,
            "reported_at": row.reported_at.isoformat(),
            "minutes_ago": int((now - row.reported_at).total_seconds() // 60)}


def _problem(web, worker, now) -> str:
    """The platform owner's words for what is wrong, or ""."""
    if worker is None:
        return ("The worker has not reported whether it can reach the card processor. Until it "
                "does, auto-pay, automatic billing and subscription charges may be refused "
                "without anyone being told.")
    if now - worker.reported_at > STALE:
        minutes = int((now - worker.reported_at).total_seconds() // 60)
        return (f"The worker last reported {minutes} minutes ago. If it is stopped, nothing "
                "is charged by schedule: auto-pay, automatic billing and subscriptions wait.")
    if not worker.live_calls:
        return ("Real calls to the card processor are OFF in the worker (NMI_LIVE_CALLS is not "
                "true on qcluster). Every scheduled card job is refused: auto-pay, automatic "
                "billing, subscription charges, lookups of lost answers and the daily "
                "read-back." + (" Web has them on." if web is True else ""))
    if web is False:
        return ("Web and the worker disagree: real calls to the card processor are on in the "
                "worker and OFF in web (NMI_LIVE_CALLS), so pay buttons and card saves are "
                "paused while scheduled charges go ahead.")
    return ""


PRACTICE_WARNING = (
    "Scheduled card charges aren't running: the app's background worker can't reach the card "
    "processor. Auto-pay and automatic billing won't charge any card, and lost answers and "
    "the daily read-back wait, until this is fixed. {product} has been told.")


def state(*, for_practice: bool = False) -> dict:
    """What Practices (and, shorter, Settings → Billing) shows. The warning
    is given in production only."""
    from apps.billing.models import ServiceReport
    from config.branding import PRODUCT_NAME

    report()
    now = timezone.now()
    rows = {row.service: row for row in ServiceReport.objects.all()}
    web = rows.get("web")
    # The page is served by web: its own setting is the truth for it.
    web_live = gw.live_calls_allowed() if this_service() == "web" else (
        web.live_calls if web is not None else None)
    production = settings.APP_ENVIRONMENT == "production"
    problem = _problem(web_live, rows.get("worker"), now) if production else ""
    answer = {"production": production, "warning": problem}
    if for_practice:
        answer["warning"] = PRACTICE_WARNING.format(product=PRODUCT_NAME) if problem else ""
        return answer
    return {**answer, "web": _row(web, now), "worker": _row(rows.get("worker"), now),
            "web_live_calls": web_live, "refused_today": refused_today()}


# ------------------------------------------------------------ refused jobs

def refused_today() -> list[dict]:
    from apps.billing.models import RefusedJob

    rows = (RefusedJob.objects.filter(day=timezone.localdate()).values("job")
            .annotate(practices=Count("tenant"), runs=Sum("count")).order_by("job"))
    return [{"job": row["job"], "label": JOBS.get(row["job"], row["job"]),
             "practices": row["practices"], "runs": row["runs"]} for row in rows]


def job_refused(job: str, tenant) -> bool:
    """Record that `job` needed the processor for `tenant` and real calls
    are off here; tell the platform owner once a day. True if recorded."""
    from apps.billing.models import RefusedJob

    if not gw.stand_in_refused():
        return False
    today, now = timezone.localdate(), timezone.now()
    try:
        with transaction.atomic():
            counted = RefusedJob.objects.filter(job=job, tenant=tenant, day=today).update(
                count=F("count") + 1, last_at=now)
            if not counted:
                RefusedJob.objects.create(job=job, tenant=tenant, day=today, first_at=now,
                                          last_at=now)
    except IntegrityError:
        RefusedJob.objects.filter(job=job, tenant=tenant, day=today).update(
            count=F("count") + 1, last_at=now)
    log.warning("%s refused for practice %s: real calls to the card processor are off in "
                "this service (%s)", job, tenant.pk, this_service() or "no service")
    try:
        tell_platform_owner(today)
    except Exception as exc:  # noqa: BLE001 — recorded either way
        log.warning("platform owner not told of refused jobs (%s)", type(exc).__name__)
    return True


def tell_platform_owner(today) -> bool:
    """A Notice and an email to the platform owner, once a day."""
    from apps.billing.subscriptions import owners_practice
    from apps.crm.models import OutboxMessage
    from apps.crm.services import email_layout, outbox
    from apps.notify import service as notify
    from apps.notify.models import Kind
    from apps.tenancy.context import tenant_context
    from apps.tenancy.models import Membership, Role

    home = owners_practice()
    if home is None:
        return False
    title = "Scheduled card jobs are being refused"
    text = ("Real calls to the card processor are off where the scheduled jobs run (the worker, "
            "NMI_LIVE_CALLS). Auto-pay, automatic billing, subscription charges, lookups and "
            "the read-back are refused. See Practices, Card payments.")
    source_id = uuid.uuid5(_NAMESPACE, f"refused:{today:%Y-%m-%d}")
    owners = list(Membership.all_objects.filter(tenant=home, role=Role.FF,
                                                revoked_at__isnull=True).select_related("user"))
    told = [o for o in owners if notify.tell(
        tenant_id=home.pk, recipient_id=o.user_id, kind=Kind.PAYMENTS, title=title, text=text,
        url="/practices", source_type="refused_jobs", source_id=source_id)]
    if not told:
        return False
    lines = [text, "Set NMI_LIVE_CALLS to true on the qcluster service in Railway, as it is on "
                   "web. Until then nothing is charged by schedule. This is sent once a day."]
    with tenant_context(home.pk):
        for owner in told:
            if not owner.user.email:
                continue
            outbox.create_message(
                tenant=home, producer=OutboxMessage.Producer.PAYMENT_NOTICE,
                to_address=owner.user.email, subject=title, body_text="\n\n".join(lines),
                body_html=email_layout.document(
                    home, subject=title, preheader=lines[0], internal=True,
                    content_html="".join(f"<p>{escape(line)}</p>" for line in lines)),
                source_type="refused_jobs", source_id=source_id, force_direct=True)
    return True
