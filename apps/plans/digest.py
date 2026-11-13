"""A closed period's summary in the weekly digest draft (P11, "Close the
week"). A digest is drafted per recipient, so the summary goes into the
weekly drafts of the company's people:

- a draft made after the close carries it (`lines_for`, read by
  `apps.work.digests.render`);
- a draft already waiting is marked out of date, so its "Update" button
  (the existing one) re-renders it with the summary. It is never rewritten
  behind the back of whoever may have edited it.

A summary is carried once: by the drafts after the close, up to the next one
sent to that person.
"""

from __future__ import annotations

from datetime import timedelta

HEADING = "From the plan"
STALE = "The plan's week, month or quarter was closed. Update this draft to include its summary."


def lines_for(digest) -> list[str]:
    from apps.work.models import Cadence, Digest

    from .access import available
    from .models import PlanClose

    contact = getattr(digest, "contact", None)
    company = getattr(contact, "company", None)
    if company is None or getattr(digest, "cadence", None) != Cadence.WEEKLY \
            or not available(company.tenant_id):
        return []
    last = (Digest.objects.filter(contact=contact, state=Digest.State.SENT)
            .exclude(pk=digest.pk).order_by("-period_end")
            .values_list("period_end", flat=True).first())
    since = last or (digest.created_at or digest.period_start) - timedelta(days=14)
    return [c.summary for c in PlanClose.all_objects.filter(
        company=company, created_at__gt=since).order_by("period_start", "horizon")]


def flag_drafts(company) -> int:
    from apps.work.digests import UNSENT_DRAFTS
    from apps.work.models import Cadence, Digest

    return Digest.all_objects.filter(
        tenant_id=company.tenant_id, contact__company=company,
        cadence=Cadence.WEEKLY, state__in=UNSENT_DRAFTS).update(
        is_stale=True, stale_reason=STALE)
