"""A reading the notes state, proposed for a KPI (owner, 2026-10-27; the
scorecard spec's "Meeting queue" tie, `docs/p6_m5_kpi_scorecard.md`).

"Occupancy was 78% last week" in a meeting's notes becomes a proposed
reading of the KPI called Occupancy, for the week before the meeting, for
someone to confirm. Nothing is entered until they do, and then through the
scorecard's own entry (`readings.save`), as the person approving it.

**Proposed only when nothing has to be guessed.** Claude reports a number,
what it measures, the period, and the sentence it came from; the app decides
the rest and drops anything doubtful rather than propose it:

- **One KPI.** The measure's words and the KPI's name match (one holds the
  other's words); a name more than one KPI answers to is narrowed to the
  meeting's companies, and dropped if it is still more than one.
- **Never a per-person or computed KPI.** A meeting's number is nobody's own
  row, and a computed KPI is never entered.
- **The KPI's own period.** A week for a weekly KPI, a month for a monthly
  one, worked out from the meeting's date; a period the notes name in some
  other size, or one not yet started, is dropped.
- **A value the KPI takes**, by the same rules as typing it in.

**Who sees it** is the scorecard's audience rules, asked as the reviewer:
someone who could not see the KPI on its scorecard is not shown the item
(`permissions.items_for`), and only someone who may enter that reading can
approve it (`approval.approve_reading`).
"""

from __future__ import annotations

import re
from datetime import date

#: The words a period is named in, to the KPI cadences they can be.
CADENCE_OF = {"day": "daily", "week": "weekly", "month": "monthly", "quarter": "quarterly"}
#: Words that do not tell one measure from another.
FILLER = {"the", "a", "an", "of", "our", "their", "total", "rate", "average", "avg", "number",
          "count", "percent", "percentage", "per", "in", "on", "for", "and", "%"}


def _one(word: str) -> str:
    """A plural's singular, roughly: deliveries, orders, hours."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def words(text: str) -> set[str]:
    return {_one(w) for w in re.findall(r"[a-z0-9]+", (text or "").lower())} - FILLER


def names_match(measure: str, kpi_name: str) -> bool:
    """One holds the other's words: "occupancy" and "Occupancy rate",
    "on-time delivery" and "On-time delivery %"."""
    a, b = words(measure), words(kpi_name)
    return bool(a) and bool(b) and (a <= b or b <= a)


def period_start(raw: dict, cadence: str, meeting_date: date | None, week_start: str):
    """The KPI period the notes name, or None when it is not one of the KPI's
    own size or cannot be placed without guessing."""
    from apps.scorecard import periods as P

    if not isinstance(raw, dict):
        return None
    if CADENCE_OF.get(str(raw.get("kind") or "").strip().lower()) != cadence:
        return None
    which = str(raw.get("which") or "").strip().lower()
    if which == "date":
        try:
            day = date.fromisoformat(str(raw.get("date"))[:10])
        except (TypeError, ValueError):
            return None
    elif which in ("last", "this") and meeting_date is not None:
        day = meeting_date
        if which == "last":
            day = P.previous_start(P.start_of(meeting_date, cadence, week_start), cadence,
                                   week_start)
    else:
        return None
    start = P.start_of(day, cadence, week_start)
    if meeting_date is not None and start > meeting_date:
        return None
    return start


def _kpis(tenant):
    from apps.scorecard.models import Kpi

    return list(Kpi.all_objects.filter(
        tenant=tenant, archived_at__isnull=True, per_person=False, formula="",
        page__archived_at__isnull=True, scorecard__company__deleted_at__isnull=True)
        .select_related("scorecard", "scorecard__company"))


def choose(kpis, measure: str, company_ids: set):
    matches = [k for k in kpis if names_match(measure, k.name)]
    if len(matches) > 1 and company_ids:
        matches = [k for k in matches if k.scorecard.company_id in company_ids]
    return matches[0] if len(matches) == 1 else None


def propose(tenant, raws, *, meeting_date, company_ids) -> list[dict]:
    """Each stated value that names exactly one KPI, in its period, in a
    value it takes: (excerpt, payload) pairs for `ProposalItem`s."""
    from apps.scorecard import periods as P
    from apps.scorecard import readings
    from apps.scorecard.bonus import fmt

    kpis = _kpis(tenant) if raws else []
    out, seen = [], set()
    for raw in raws or []:
        if not isinstance(raw, dict):
            continue
        measure = str(raw.get("measure") or "").strip()
        stated = str(raw.get("value") or "").strip()
        excerpt = str(raw.get("excerpt") or "").strip()
        if not measure or not stated or not excerpt:
            continue
        kpi = choose(kpis, measure, company_ids)
        if kpi is None:
            continue
        start = period_start(raw.get("period"), kpi.cadence, meeting_date,
                             kpi.scorecard.week_start)
        if start is None or (kpi.pk, start) in seen:
            continue
        try:
            value = readings.parse(kpi, stated)
        except readings.ReadingRefused:
            continue
        seen.add((kpi.pk, start))
        company = kpi.scorecard.company
        out.append((excerpt, {
            "measure": measure, "stated_value": stated,
            "kpi_id": str(kpi.pk), "kpi_name": kpi.name, "kind": kpi.kind,
            "cadence": kpi.cadence, "company_id": str(company.pk),
            "company_name": company.name,
            "period_start": start.isoformat(),
            "period_label": P.long_label(start, kpi.cadence),
            "value": str(value), "value_label": fmt(kpi, value),
        }))
    return out


def company_ids_of(items) -> set:
    """The companies the meeting's participants were matched or named to."""
    from apps.crm.models import Contact

    ids, contacts = set(), set()
    for item in items:
        payload = item.payload or {}
        for row in payload.get("company_candidates") or []:
            if row.get("company_id"):
                ids.add(str(row["company_id"]))
        for row in payload.get("existing_candidates") or []:
            if row.get("contact_id"):
                contacts.add(row["contact_id"])
    if contacts:
        ids |= {str(c) for c in Contact.all_objects.filter(pk__in=contacts).exclude(
            company_id=None).values_list("company_id", flat=True)}
    from uuid import UUID

    return {UUID(i) for i in ids}

