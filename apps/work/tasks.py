"""Scheduled work for Module 3 — one tick, so the order of operations is
visible in one place rather than spread across five schedules.

Plain module-level functions taking primitives (assumption A1), each opening an
explicit tenant_context because a background job has no request.
"""

from __future__ import annotations

from django.utils import timezone

from apps.tenancy.context import tenant_context

CLIENT_ACTIVITY_QUIET = timezone.timedelta(minutes=30)   # FR-3.40, same window


def tick(tenant_id: str, now=None) -> dict:
    """Every minute: close quiet windows, generate, expire, send, notify.

    Expiry runs before sending so that a digest which reached its window
    unapproved can never be picked up by the same tick as if it were approved.
    `now` exists for tests that run the real tick past a window; the scheduler
    never passes it.
    """
    from apps.tenancy.models import Tenant
    from apps.work import digests
    from apps.work.models import Cadence

    now = now or timezone.now()
    with tenant_context(tenant_id):
        tenant = Tenant.objects.get(pk=tenant_id)
        every_update = digests.close_quiet_windows(tenant, now=now)
        scheduled = []
        for cadence in (Cadence.WEEKLY, Cadence.MONTHLY):
            scheduled += digests.generate_scheduled(tenant, cadence=cadence, now=now)
        expired = digests.expire_due(tenant, now=now)
        sent = digests.send_due(tenant, now=now)
        notified = notify_client_activity(tenant, now=now)
    return {
        "every_update_generated": len(every_update),
        "scheduled_generated": len(scheduled),
        "expired": len(expired),
        "sent": len(sent),
        "client_activity_notices": notified,
    }


TICK_STALE_AFTER = timezone.timedelta(minutes=5)


def tick_health(tenant, *, now=None) -> dict:
    """Whether this tenant's tick is actually running — read from Django-Q's
    own result rows, so there is no second record to keep in step.

    Check 3 looked like expiry failing; the first question was whether the tick
    was running at all. This puts that answer on the screen that depends on it.
    Django-Q keeps its most recent results (250 by default), so the newest run
    is always there to read.
    """
    from django_q.models import Task as QueuedTask

    now = now or timezone.now()
    rows = [r for r in QueuedTask.objects.filter(func="apps.work.tasks.tick")
            .order_by("-stopped")[:60]
            if r.args and str(r.args[0]) == str(tenant.pk)]
    ok = next((r for r in rows if r.success), None)
    failed = next((r for r in rows if not r.success), None)
    return {
        "last_success_at": ok.stopped.isoformat() if ok else None,
        "last_failure_at": failed.stopped.isoformat() if failed else None,
        "last_failure": str(failed.result)[:300] if failed else "",
        "stale": ok is None or now - ok.stopped > TICK_STALE_AFTER,
        "stale_after_minutes": int(TICK_STALE_AFTER.total_seconds() // 60),
    }


def client_activity_email(tenant, rows) -> tuple[str, str, str]:
    """`(subject, html, text)` — who did what, and when, in tenant time."""
    from zoneinfo import ZoneInfo

    from django.template.loader import render_to_string

    from apps.crm.services import email_layout

    zone = ZoneInfo(tenant.timezone)
    items = []
    for row in rows:
        who = (row.actor.full_name or row.actor.email) if row.actor else "A client user"
        verb = {"comment_added": "commented on", "created": "created",
                "status_changed": "changed the status of"}.get(
                    row.kind, row.kind.replace("_", " ") + " on")
        local = row.created_at.astimezone(zone)
        when = f"{local:%a} {local.day} {local:%b}, {local:%I:%M %p}".replace(" 0", " ")
        items.append({"who": who, "when": when,
                      "what": f"{verb} “{row.task.title if row.task else 'work'}”"})
    count = len(items)
    subject = f"Client activity — {count} update{'s' if count != 1 else ''}"
    intro = "Your clients have been active in the portal."
    closing = "Open Work in Execs NOW HQ to reply."
    content = render_to_string("email/client_activity_content.html",
                               email_layout.template_context(tenant, intro=intro, rows=items,
                                                             closing=closing))
    html = email_layout.document(tenant, content_html=content, subject=subject,
                                 preheader=f"{count} update{'s' if count != 1 else ''} "
                                           "from your clients")
    text = (intro + "\n\n" + "\n".join(f"- {i['who']} {i['what']} — {i['when']}" for i in items)
            + "\n\n" + closing)
    return subject, html, text


def notify_client_activity(tenant, *, now=None) -> int:
    """FR-3.40 — tell the practice when a client comments or creates a task,
    batched on the same 30-minute quiet window.

    The in-app half is a feed built from these same `task_update` rows (owner
    decision, 2026-09-11), so the only state this needs is how far it has got,
    which it keeps as an audit event.
    """
    from apps.crm.models import OutboxMessage
    from apps.crm.services import outbox
    from apps.tenancy.models import AuditEvent, Membership, Role
    from apps.work.models import TaskUpdate

    now = now or timezone.now()
    marker = (AuditEvent.objects.filter(verb="client_activity.notified")
              .order_by("-created_at").first())
    since = marker.payload.get("through") if marker else None

    # FR-3.42 — nothing done while acting as another user is announced by email.
    rows = TaskUpdate.objects.filter(is_client_actor=True, acting_user__isnull=True) \
        .select_related("task", "actor")
    if since:
        rows = rows.filter(created_at__gt=since)
    rows = list(rows.order_by("created_at"))
    if not rows:
        return 0
    # Still inside the burst: wait, so one editing session is one email.
    if now - rows[-1].created_at < CLIENT_ACTIVITY_QUIET:
        return 0

    subject, html, body = client_activity_email(tenant, rows)

    recipients = {
        member.user.email
        for member in Membership.objects.filter(
            role__in=[Role.FF, Role.CF], revoked_at__isnull=True
        ).select_related("user")
        if member.user.email
    }
    for address in sorted(recipients):
        outbox.create_message(
            tenant=tenant, producer=OutboxMessage.Producer.CLIENT_ACTIVITY,
            to_address=address, subject=subject,
            body_text=body, body_html=html, force_direct=True,
        )
    AuditEvent.objects.create(
        tenant=tenant, verb="client_activity.notified", target_type="tenant",
        target_id=tenant.pk,
        payload={"through": rows[-1].created_at.isoformat(), "updates": len(rows),
                 "recipients": len(recipients)},
    )
    return len(recipients)
