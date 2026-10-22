"""The missing-reading reminder in the next client digest (spec, "Missing
readings": "one reminder (in-app notice, and in the next digest)").

A digest goes to a contact; its line names the readings that contact's own
portal sign-in was reminded about and that are still not in. Within the
audience rules: a KPI the person may no longer see is left out, and the line
names the KPI and the period, never a colleague or a value. A digest is not
made for this alone (FR-3.31: no digest says nothing happened); the line
rides in the next one that goes out anyway, and once a digest has carried a
reminder it is not repeated, unless that digest expired or was skipped.
"""

from __future__ import annotations

from types import SimpleNamespace

from django.db.models import Q

from apps.tenancy.models import CLIENT_ROLES, Membership

from . import periods as P
from .access import Reader
from .models import KpiReminder


def lines_for(tenant, contact, digest=None) -> list:
    """[(reminder, text)] for this contact's next digest."""
    from apps.work.models import Digest

    dead = (Digest.State.EXPIRED, Digest.State.SKIPPED)
    out = []
    for membership in Membership.all_objects.filter(
            tenant=tenant, contact=contact, role__in=CLIENT_ROLES, revoked_at__isnull=True):
        free = Q(digest__isnull=True) | Q(digest__state__in=dead)
        if digest is not None and digest.pk:
            free |= Q(digest=digest)
        reminders = (KpiReminder.all_objects.filter(free, tenant=tenant,
                                                    recipient_id=membership.user_id,
                                                    kpi__archived_at__isnull=True,
                                                    kpi__scorecard__company_id=
                                                    membership.client_company_id)
                     .select_related("kpi__page__team", "kpi__audience_team",
                                     "kpi__scorecard__company")
                     .order_by("period_start", "kpi__position"))
        reader = None
        for reminder in reminders:
            from .readings import _missing

            kpi = reminder.kpi
            if not _missing(kpi, reminder.period_start):
                continue
            if reader is None:
                reader = Reader(SimpleNamespace(membership=membership), kpi.scorecard.company)
            if not reader.may_enter(kpi):
                continue
            out.append((reminder, f"{kpi.name}: no reading yet for "
                                  f"{P.long_label(reminder.period_start, kpi.cadence)}."))
    return out


def claim(digest, lines) -> None:
    """The digest that carried these lines, so they are not repeated."""
    KpiReminder.all_objects.filter(pk__in=[r.pk for r, _ in lines]).update(digest=digest)
