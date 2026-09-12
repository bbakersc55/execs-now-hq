"""The cadence link in every digest footer — FR-3.33a/b.

Authenticated by a **signed, expiring token bound to one stakeholder row**, not
by a session: most stakeholders have no login and never will (FR-3.20). The
token grants exactly one capability — read and change the cadence on that one
row. It cannot read a task, a digest, or anything else, which is why this view
touches nothing but that row.
"""

from __future__ import annotations

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.tenancy.context import tenant_context
from apps.tenancy.models import AuditEvent
from apps.work.models import Cadence, StakeholderToken

CHOICES = [c for c, _ in Cadence.choices]


def _payload(row):
    return {
        "name": f"{row.contact.first_name} {row.contact.last_name}".strip(),
        "cadence": row.cadence,
        "is_muted": row.is_muted,
        "choices": [{"value": value, "label": label} for value, label in Cadence.choices],
    }


@csrf_exempt
@require_http_methods(["GET", "POST"])
def cadence_link(request, token: str):
    record = StakeholderToken.resolve(token)
    if record is None:
        return JsonResponse(
            {"detail": "This link has expired or is no longer in use. Ask your "
                       "contact at the practice for a new one."}, status=404)
    row = record.stakeholder
    with tenant_context(record.tenant_id):
        if request.method == "POST":
            import json

            try:
                body = json.loads(request.body or "{}")
            except ValueError:
                return JsonResponse({"detail": "Unreadable request."}, status=400)
            cadence = body.get("cadence")
            stop = bool(body.get("stop"))
            if not stop and cadence not in CHOICES:
                return JsonResponse({"detail": "Choose how often to hear from us."},
                                    status=400)
            row.is_muted = stop
            if not stop:
                row.cadence = cadence
            row.save(update_fields=["cadence", "is_muted", "updated_at"])
            AuditEvent.all_objects.create(
                tenant_id=record.tenant_id, verb="stakeholder.cadence_changed",
                target_type="stakeholder", target_id=row.pk,
                payload={"cadence": row.cadence, "is_muted": row.is_muted,
                         "by": "recipient via emailed link",
                         "at": timezone.now().isoformat()},
            )
        return JsonResponse(_payload(row))
