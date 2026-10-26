"""The scorecard as the rest of the app reads it (spec, "How it ties into the
rest of the app"): a goal's KPI on its card and in the portal, a tile's
"Make a task" and the nudge after three periods Off track, and the client
digest's Scorecard section.

**Everything here reads a KPI through `board.tile`, for one reader**, so the
audience rules are the scorecard's own and are written once: a KPI the reader
may not see is absent; on a per-person KPI a member gets their own row, a
manager their team's total, senior leadership and up the whole total, and
**nobody is ever given a colleague's row** (the leak rule). A digest is read
as the recipient's own portal sign-in would read it; a contact with no
sign-in gets no Scorecard section at all, since nothing says what they may
see.
"""

from __future__ import annotations

from types import SimpleNamespace

from . import board
from . import periods as P
from .access import Reader
from .bonus import fmt
from .models import Kpi

#: Off track this many closed periods running, and the tile offers a task.
OFF_TRACK_RUN = 3


def reader_for_membership(membership, company) -> Reader:
    """The reader a portal sign-in is, without a request: what a digest uses."""
    return Reader(SimpleNamespace(membership=membership), company)


def tiles_for(reader, kpis, today) -> dict:
    """{kpi.pk: tile} for the KPIs this reader sees, drawn over the last
    thirteen periods (a window of one period draws that many)."""
    kpis = [k for k in kpis if k.archived_at is None and reader.sees_kpi(k)]
    if not kpis:
        return {}
    week_start = kpis[0].scorecard.week_start
    win = P.window("this_week", today, week_start)
    sources = [s for k in kpis if k.is_computed for s in (k.source_a, k.source_b)]
    readings, months, people = board.load(
        kpis + sources, board.earliest_needed(win, kpis, today, week_start))
    return {k.pk: board.tile(k, reader, board.Targets(k, months[k.pk]), readings[k.pk],
                             people[k.pk], win, today, week_start,
                             sources=(readings[k.source_a_id], readings[k.source_b_id])
                             if k.is_computed else None)
            for k in kpis}


def _kpi_query():
    return Kpi.objects.select_related(
        "scorecard", "scorecard__company", "page", "page__team", "audience_team",
        "reading_owner", "source_a__page__team", "source_a__audience_team",
        "source_b__page__team", "source_b__audience_team")


def _whose(tile) -> str:
    """Whose number a per-person tile's line is: said, never left to guess."""
    if tile.get("shape") == "my_row":
        return "yours"
    if tile.get("total_label") == "your team's total":
        return "your team's total"
    return ""


def latest(kpi, tile, today) -> dict | None:
    """The KPI's latest reading as this reader sees it, with its status."""
    points = [p for p in tile.get("history") or [] if p["value"] is not None]
    if not points:
        return None
    point = points[-1]
    start = _date(point["period_start"])
    value = point["value"]
    status = point["status"]
    return {"kpi": str(kpi.pk), "name": kpi.name, "kind": kpi.kind,
            "duration_unit": kpi.duration_unit, "value": value,
            "value_text": fmt(kpi, value), "target": point["target"],
            "target_text": _target_text(kpi, point["target"]),
            "status": status, "status_label": P.STATUS_LABEL.get(status, "") if status else "",
            "period": P.long_label(start, kpi.cadence), "whose": _whose(tile),
            "off_track_run": off_track_run(tile, today)}


def _date(text):
    from datetime import date

    return date.fromisoformat(text)


def _target_text(kpi, target) -> str:
    if kpi.direction == "range":
        if kpi.range_low is None or kpi.range_high is None:
            return ""
        return f"range {fmt(kpi, kpi.range_low)} to {fmt(kpi, kpi.range_high)}"
    if target is None:
        return ""
    return f"keep under {fmt(kpi, target)}" if kpi.direction == "lower" \
        else f"target {fmt(kpi, target)}"


def off_track_run(tile, today) -> int:
    """Closed periods running, newest first, that were Off track. A period
    with no reading ends the run: it says nothing either way."""
    run = 0
    for point in reversed(tile.get("history") or []):
        start = _date(point["period_start"])
        if not P.closed(start, tile["cadence"], today):
            continue
        if point["value"] is None or point["status"] != P.OFF_TRACK:
            break
        run += 1
    return run


# ------------------------------------------------------------- goals

def goal_kpi(request, goal, today=None) -> dict | None:
    """What a goal's card shows of its KPI, for whoever is asking, or None
    when it has none or they may not see it."""
    if not goal.kpi_id:
        return None
    kpi = _kpi_query().filter(pk=goal.kpi_id, archived_at__isnull=True).first()
    if kpi is None or getattr(request, "membership", None) is None:
        return None
    if kpi.scorecard.company_id != goal.client_company_id:
        return None              # the goal moved company: its old KPI is not this one's
    company = kpi.scorecard.company
    reader = Reader(request, company)
    today = today or board.today_for(company.tenant)
    tile = tiles_for(reader, [kpi], today).get(kpi.pk)
    if tile is None:
        return None
    found = latest(kpi, tile, today)
    return found or {"kpi": str(kpi.pk), "name": kpi.name, "value": None,
                     "value_text": "", "status": None, "status_label": "",
                     "period": "", "whose": _whose(tile), "target_text": "",
                     "off_track_run": 0}


def kpi_choices(company) -> list[dict]:
    """The company's live KPIs, for a picker: a goal's, a map row's."""
    return [{"id": str(k.pk), "name": k.name}
            for k in Kpi.objects.filter(scorecard__company=company, archived_at__isnull=True)
            .order_by("page__position", "position", "name")]


# ------------------------------------------------------------- the digest

def digest_section(tenant, contact, **kw) -> dict | None:
    """Within the practice, whoever calls: the worker and a test alike."""
    from apps.tenancy.context import tenant_context

    with tenant_context(tenant.pk):
        return _digest_section(tenant, contact, **kw)


def _digest_section(tenant, contact, *, since=None, today=None, waiting=()) -> dict | None:
    """The client digest's Scorecard section for one contact, read as their
    own portal sign-in reads the scorecard: the latest reading of each KPI
    whose period closed since the last digest, the status changes since then,
    and readings still missing. `waiting` are the reminder lines already
    carried, so a missing reading is not said twice. None when there is
    nothing to say, or no sign-in to read it as."""
    from apps.tenancy.models import CLIENT_ROLES, Membership

    from .models import Scorecard

    today = today or board.today_for(tenant)
    since_day = since.date() if since is not None else None
    said = {(r.kpi_id, r.period_start) for r, _ in waiting}
    readings, changes, missing = [], [], []
    for membership in Membership.all_objects.filter(
            tenant=tenant, contact=contact, role__in=CLIENT_ROLES, revoked_at__isnull=True,
            client_company__isnull=False).select_related("client_company"):
        scorecard = Scorecard.all_objects.filter(company=membership.client_company).first()
        if scorecard is None:
            continue
        reader = reader_for_membership(membership, membership.client_company)
        kpis = list(_kpi_query().filter(scorecard=scorecard, archived_at__isnull=True)
                    .order_by("page__position", "position"))
        for kpi in kpis:
            tile = tiles_for(reader, [kpi], today).get(kpi.pk)
            if tile is None:
                continue
            lines = _kpi_lines(kpi, tile, today, since_day, said)
            readings += lines["readings"]
            changes += lines["changes"]
            missing += lines["missing"]
    if not (readings or changes or missing):
        return None
    from apps.tenancy import words as practice_words

    return {"heading": practice_words.of(tenant).Scorecard, "readings": readings, "changes": changes,
            "missing": missing}


def _closed_since(start, cadence, since_day, today) -> bool:
    if not P.closed(start, cadence, today):
        return False
    return since_day is None or P.end_of(start, cadence) >= since_day


def _kpi_lines(kpi, tile, today, since_day, said) -> dict:
    out = {"readings": [], "changes": [], "missing": []}
    closed = [(_date(p["period_start"]), p) for p in tile.get("history") or []
              if P.closed(_date(p["period_start"]), kpi.cadence, today)]
    if not closed:
        return out
    whose = _whose(tile)
    name = f"{kpi.name} ({whose})" if whose else kpi.name
    new = [(s, p) for s, p in closed if _closed_since(s, kpi.cadence, since_day, today)]
    if since_day is None:
        new = new[-1:]                         # a first digest: the latest period only
    with_value = [(s, p) for s, p in new if p["value"] is not None]
    if with_value:
        start, point = with_value[-1]
        parts = [fmt(kpi, point["value"])]
        target = _target_text(kpi, point["target"])
        if target:
            parts.append(f"({target})")
        status = P.STATUS_LABEL.get(point["status"], "") if point["status"] else ""
        out["readings"].append(
            f"{name}, {P.long_label(start, kpi.cadence)}: {' '.join(parts)}"
            + (f". {status}." if status else "."))
        before = [p for s, p in closed if s < (new[0][0] if new else start)
                  and p["status"]]
        if before and point["status"] and before[-1]["status"] != point["status"]:
            out["changes"].append(
                f"{name} moved from {P.STATUS_LABEL[before[-1]['status']]} to "
                f"{P.STATUS_LABEL[point['status']]}.")
    if not kpi.is_computed:
        for start, point in new:
            if point["value"] is None and (kpi.pk, start) not in said:
                out["missing"].append(
                    f"{name}: no reading yet for {P.long_label(start, kpi.cadence)}.")
    return out


# ------------------------------------------------------------- tasks

def task_title(kpi, tile, today) -> str:
    run = off_track_run(tile, today)
    if run >= OFF_TRACK_RUN:
        return f"{kpi.name}: Off track {run} {P.noun(kpi.cadence)}s running"[:255]
    return f"Look into {kpi.name}"[:255]


def task_description(kpi, tile, today) -> str:
    """The KPI's latest reading, for the task. Not on a per-person KPI: a
    task is seen by colleagues, and the reading the maker sees is their own
    row or their team's."""
    if kpi.per_person:
        return f"From the {kpi.scorecard.company.name} scorecard: {kpi.name}."
    found = latest(kpi, tile, today)
    if found is None:
        return f"From the {kpi.scorecard.company.name} scorecard: {kpi.name} has no reading yet."
    line = f"{found['name']}, {found['period']}: {found['value_text']}"
    if found["target_text"]:
        line += f" ({found['target_text']})"
    if found["status_label"]:
        line += f", {found['status_label']}"
    return f"From the {kpi.scorecard.company.name} scorecard. {line}."
