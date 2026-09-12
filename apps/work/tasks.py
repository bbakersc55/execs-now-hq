"""Scheduled work for Module 3 — one tick, so the order of operations is
visible in one place rather than spread across five schedules.

Plain module-level functions taking primitives (assumption A1), each opening an
explicit tenant_context because a background job has no request.
"""

from __future__ import annotations

from django.utils import timezone

from apps.tenancy.context import tenant_context

CLIENT_ACTIVITY_QUIET = timezone.timedelta(minutes=30)   # FR-3.40, same window


def tick(tenant_id: str) -> dict:
    """Every minute: close quiet windows, generate, expire, send, notify.

    Expiry runs before sending so that a digest which reached its window
    unapproved can never be picked up by the same tick as if it were approved.
    """
    from apps.tenancy.models import Tenant
    from apps.work import digests
    from apps.work.models import Cadence

    with tenant_context(tenant_id):
        tenant = Tenant.objects.get(pk=tenant_id)
        every_update = digests.close_quiet_windows(tenant)
        scheduled = []
        for cadence in (Cadence.WEEKLY, Cadence.MONTHLY):
            scheduled += digests.generate_scheduled(tenant, cadence=cadence)
        expired = digests.expire_due(tenant)
        sent = digests.send_due(tenant)
        notified = notify_client_activity(tenant)
    return {
        "every_update_generated": len(every_update),
        "scheduled_generated": len(scheduled),
        "expired": len(expired),
        "sent": len(sent),
        "client_activity_notices": notified,
    }


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

    rows = TaskUpdate.objects.filter(is_client_actor=True).select_related("task", "actor")
    if since:
        rows = rows.filter(created_at__gt=since)
    rows = list(rows.order_by("created_at"))
    if not rows:
        return 0
    # Still inside the burst: wait, so one editing session is one email.
    if now - rows[-1].created_at < CLIENT_ACTIVITY_QUIET:
        return 0

    lines = []
    for row in rows:
        who = row.actor.full_name or row.actor.email if row.actor else "A client user"
        what = {"comment_added": "commented on", "created": "created",
                "status_changed": "changed the status of"}.get(row.kind, row.kind + " on")
        lines.append(f"- {who} {what} “{row.task.title if row.task else 'work'}”")
    body = ("Your clients have been active in the portal:\n\n" + "\n".join(lines)
            + "\n\nOpen Work in Execs NOW HQ to reply.")

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
            to_address=address, subject=f"Client activity — {len(rows)} update"
                                        f"{'s' if len(rows) != 1 else ''}",
            body_text=body, force_direct=True,
        )
    AuditEvent.objects.create(
        tenant=tenant, verb="client_activity.notified", target_type="tenant",
        target_id=tenant.pk,
        payload={"through": rows[-1].created_at.isoformat(), "updates": len(rows),
                 "recipients": len(recipients)},
    )
    return len(recipients)
