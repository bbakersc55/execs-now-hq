"""What a reader is sent for a scorecard page: the tiles, the grid and the
meeting view are three drawings of this one payload (spec, "The scorecard
page and the tiles").

Everything here has already been through `access.Reader`: a KPI the reader
may not see is never looked at, and a per-person KPI carries only the rows
the reader may see. A total is made from those rows alone, and none is made
for someone sent only their own.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from . import periods as P
from .models import Kpi, KpiMonthTarget, KpiPerson, KpiReading, Scorecard, ScorecardPage


def num(value):
    """A decimal as the JSON number the screens format."""
    if value is None:
        return None
    return float(round(Decimal(value), 4))


def name_of(user) -> str:
    if user is None:
        return ""
    return user.full_name or user.email


class Targets:
    """A KPI's target in a period: its month's, when it has one, else fixed."""

    def __init__(self, kpi, months):
        self.kpi = kpi
        self.months = months

    def of(self, start):
        return self.months.get(start.month, self.kpi.target_value)

    @property
    def seasonal(self) -> bool:
        return bool(self.months)


def _kpi_status(kpi, value, target):
    return P.status(value, target, kpi.direction, kpi.behind_band_pct,
                    low=kpi.range_low, high=kpi.range_high)


def _combined_target(targets, starts, rule):
    values = [targets.of(s) for s in starts]
    if any(v is None for v in values):
        return None
    if not values:
        return None
    return P.combine(values, rule)


class Series:
    """One line of readings: the KPI's own, one person's, or a total."""

    def __init__(self, kpi, targets, by_start, *, scale=1):
        self.kpi = kpi
        self.targets = targets
        self.by_start = by_start                   # start -> (value, reading or None)
        self.scale = scale                         # a summed total's target is per person × n

    def value(self, start):
        got = self.by_start.get(start)
        return got[0] if got else None

    def target(self, start):
        t = self.targets.of(start)
        return None if t is None else t * self.scale

    def status(self, start):
        if self.kpi.direction == "range":
            return _kpi_status(self.kpi, self.value(start), None)
        return _kpi_status(self.kpi, self.value(start), self.target(start))

    def rolled(self, starts):
        have = [s for s in starts if self.value(s) is not None]
        value = P.combine([self.value(s) for s in have], self.kpi.rollup)
        if self.kpi.direction == "range":
            target = None
        else:
            target = P.combine([self.target(s) for s in have], self.kpi.rollup) \
                if have and all(self.target(s) is not None for s in have) else None
        return value, target, have

    def last_before(self, day):
        known = sorted(s for s in self.by_start if s <= day and self.value(s) is not None)
        return known[-1] if known else None


def _point(series, start, cadence, today, *, people_names=None):
    value = series.value(start)
    got = series.by_start.get(start)
    reading = got[1] if got else None
    return {
        "period_start": start.isoformat(),
        "label": P.short_label(start, cadence),
        "value": num(value),
        "target": num(series.target(start)) if series.kpi.direction != "range" else None,
        "status": series.status(start),
        "missing": value is None and P.closed(start, cadence, today),
        "edited": bool(reading and reading.times_changed),
        "reading": str(reading.pk) if reading else None,
        "entered_by": name_of(reading.entered_by) if reading else "",
        "entered_at": reading.entered_at.isoformat() if reading else None,
        "source": reading.source if reading else "",
    }


def _summary(series, kpi, win, today, week_start):
    """The window's value, target and status, and what a missing reading or
    an open period means for it."""
    cadence = kpi.cadence
    starts = P.periods_in(win, cadence, today, week_start)
    value, target, have = series.rolled(starts)
    closed_in = [s for s in starts if P.closed(s, cadence, today)]
    out = {"value": num(value), "target": num(target), "stale": False, "missing": None,
           "periods": len(starts), "periods_in": len(have)}
    if kpi.direction == "range":
        out["status"] = _kpi_status(kpi, value, None)
    else:
        out["status"] = _kpi_status(kpi, value, target)
    if closed_in and series.value(closed_in[-1]) is None:
        out["missing"] = f"No reading for {P.long_label(closed_in[-1], cadence)}"
    # The full-window goal, for the Progress tile.
    every = P.starts_between(win.first, win.last, cadence, week_start)
    if kpi.rollup == P.SUM and kpi.direction != "range":
        full = [series.target(s) for s in every]
        out["full_target"] = num(sum(full, Decimal(0))) if every and None not in full else None
    else:
        out["full_target"] = out["target"]
    out["days_left"] = max(0, (win.last - today).days + 1) if today <= win.last else 0
    total_days = (win.last - win.first).days + 1
    out["elapsed"] = round(min(1.0, max(0.0, ((today - win.first).days + 1) / total_days)), 4)
    if value is None:
        # Nothing in the window: the last known value and the status it had,
        # never a false zero. While the window is only a period still open,
        # the one just closed is shown as it is ("this week's isn't in yet");
        # a period that closed without a value greys it.
        last = series.last_before(win.last)
        if last is not None:
            open_only = bool(starts) and not closed_in
            just_closed = open_only and last == P.previous_start(starts[0], cadence, week_start)
            out.update(value=num(series.value(last)), status=series.status(last),
                       target=num(series.target(last)) if kpi.direction != "range" else None,
                       stale=not just_closed, carried=just_closed,
                       stale_from=P.long_label(last, cadence), open_period=open_only)
            if just_closed:
                out["missing"] = f"This {P.noun(cadence)}'s reading isn't in yet"
                out.update(full_target=out["target"], days_left=0, elapsed=1.0)
            elif not out["missing"]:
                gap = P.previous_start(starts[0], cadence, week_start) if starts else None
                out["missing"] = (f"No reading for {P.long_label(gap, cadence)}"
                                  if open_only and gap else f"No reading for {win.label.lower()}")
    return out


def _delta(series, kpi, end_day):
    """The latest reading against the one before it, for the trend arrow."""
    known = sorted(s for s in series.by_start if s <= end_day and series.value(s) is not None)
    if len(known) < 2:
        return None
    now, before = series.value(known[-1]), series.value(known[-2])
    change = now - before
    if change == 0:
        better = None
    elif kpi.direction == "lower":
        better = change < 0
    elif kpi.direction == "range":
        better = None
    else:
        better = change > 0
    return {"change": num(change), "better": better}


def _drawn_to(series, kpi, win, today, week_start):
    """The last period a trend or the grid draws: the window's last, unless
    that is still open with nothing in it, when the one before (a Monday
    meeting looks at the week that has just closed)."""
    end = min(win.last, today)
    start = P.start_of(end, kpi.cadence, week_start)
    if series.value(start) is None and not P.closed(start, kpi.cadence, today):
        return P.previous_start(start, kpi.cadence, week_start)
    return end


def _spark(series, kpi, win, today, week_start):
    starts = P.periods_in(win, kpi.cadence, today, week_start)
    if len(starts) < 2:
        starts = P.last_n(_drawn_to(series, kpi, win, today, week_start), kpi.cadence,
                          P.HISTORY, week_start)
    starts = starts[-P.MOST_DRAWN:]
    return [_point(series, s, kpi.cadence, today) for s in starts]


def _history(series, kpi, win, today, week_start):
    """The grid's columns. A window of more than one of the KPI's periods (a
    quarter, the year so far, custom dates) is drawn as its own periods, weeks
    for a weekly KPI and months for a monthly one, so the grid follows the
    window as the tiles do (Bryan, 2026-10-22); a window of one period, the
    last thirteen up to it."""
    starts = P.periods_in(win, kpi.cadence, today, week_start)
    if len(starts) < 2:
        starts = P.last_n(_drawn_to(series, kpi, win, today, week_start), kpi.cadence,
                          P.HISTORY, week_start)
    return [_point(series, s, kpi.cadence, today) for s in starts[-P.MOST_DRAWN:]]


def unit_of(kpi) -> str:
    if kpi.kind == Kpi.Kind.DURATION:
        return kpi.duration_unit or "hours"
    if kpi.kind == Kpi.Kind.RATING:
        return f"of {kpi.rating_scale or 5}"
    return ""


def definition(kpi, *, reader=None) -> dict:
    """What every drawing of a KPI needs to know about it."""
    return {
        "id": str(kpi.pk), "name": kpi.name, "kind": kpi.kind,
        "direction": kpi.direction, "cadence": kpi.cadence, "rollup": kpi.rollup,
        "tile": kpi.tile, "unit": unit_of(kpi), "duration_unit": kpi.duration_unit,
        "rating_scale": kpi.rating_scale, "note": kpi.note,
        "component": kpi.strategy_component, "per_person": kpi.per_person,
        "leaderboard": kpi.leaderboard, "page": str(kpi.page_id),
        "range_low": num(kpi.range_low), "range_high": num(kpi.range_high),
        "fixed_target": num(kpi.target_value), "band": num(kpi.behind_band_pct),
        "owner": "" if kpi.is_computed else name_of(kpi.reading_owner),
        "owner_id": str(kpi.reading_owner_id) if kpi.reading_owner_id else None,
        "computed": formula_text(kpi),
        "may_enter": reader.may_enter(kpi) if reader else False,
    }


def _person_series(kpi, targets, readings):
    per = defaultdict(dict)
    for r in readings:
        if r.membership_id is not None:
            per[r.membership_id][r.period_start] = (r.value, r)
    return per


def _total(kpi, targets, per, rows):
    """A total of the rows given, per period: summed or averaged."""
    by_start = {}
    starts = {s for m in rows for s in per.get(m, {})}
    for s in starts:
        values = [per[m][s][0] for m in rows if s in per.get(m, {})]
        by_start[s] = (P.combine(values, kpi.person_total), None)
    scale = len(rows) if kpi.person_total == "sum" else 1
    return Series(kpi, targets, by_start, scale=scale)


def computed_values(kpi, readings_a, readings_b) -> dict:
    """A computed KPI's value in each period both its sources have one:
    start -> (value, None). A ratio over a zero has no value."""
    a = {r.period_start: r.value for r in readings_a if r.membership_id is None}
    b = {r.period_start: r.value for r in readings_b if r.membership_id is None}
    out = {}
    for start in a.keys() & b.keys():
        x, y = a[start], b[start]
        if kpi.formula == Kpi.Formula.SUM:
            value = x + y
        elif kpi.formula == Kpi.Formula.DIFFERENCE:
            value = x - y
        elif kpi.formula == Kpi.Formula.AVERAGE:
            value = (x + y) / 2
        else:
            value = (x / y) if y else None
        if value is not None:
            out[start] = (value, None)
    return out


FORMULA_SIGN = {"sum": "+", "difference": "−", "ratio": "÷", "average": "and"}


def formula_text(kpi) -> str:
    """"Revenue ÷ Bookings", "average of A and B"."""
    if not kpi.is_computed or kpi.source_a is None or kpi.source_b is None:
        return ""
    if kpi.formula == Kpi.Formula.AVERAGE:
        return f"average of {kpi.source_a.name} and {kpi.source_b.name}"
    return f"{kpi.source_a.name} {FORMULA_SIGN[kpi.formula]} {kpi.source_b.name}"


def tile(kpi, reader, targets, readings, people, win, today, week_start,
         sources=None) -> dict:
    """One KPI as the reader may see it. `sources` holds the readings of a
    computed KPI's two sources."""
    out = definition(kpi, reader=reader)
    if not kpi.per_person:
        values = computed_values(kpi, *sources) if kpi.is_computed else {
            r.period_start: (r.value, r) for r in readings if r.membership_id is None}
        series = Series(kpi, targets, values)
        out.update(shape=kpi.tile, summary=_summary(series, kpi, win, today, week_start),
                   delta=_delta(series, kpi, min(win.last, today)),
                   spark=_spark(series, kpi, win, today, week_start),
                   history=_history(series, kpi, win, today, week_start),
                   rows=[], total=True)
        return out

    tracked = [p.membership_id for p in people]
    rows = reader.rows_of(kpi, tracked)
    per = _person_series(kpi, targets, readings)
    names = {p.membership_id: name_of(p.membership.user) for p in people}
    you = reader.membership.pk
    only_own = reader.sees_only_own_row(kpi, tracked)
    row_out = []
    for m in sorted(rows, key=lambda m: names.get(m, "").lower()):
        s = Series(kpi, targets, per.get(m, {}))
        summary = _summary(s, kpi, win, today, week_start)
        row_out.append({"membership": str(m), "name": names.get(m, ""), "you": m == you,
                        "value": summary["value"], "target": summary["target"],
                        "status": summary["status"], "stale": summary["stale"],
                        "summary": summary,
                        "delta": _delta(s, kpi, min(win.last, today)) if only_own else None,
                        "spark": _spark(s, kpi, win, today, week_start) if only_own else [],
                        "history": _history(s, kpi, win, today, week_start)})
    if only_own:
        mine = row_out[0] if row_out else None
        out.update(shape="my_row", rows=row_out, total=False,
                   summary=mine["summary"] if mine else None,
                   delta=mine["delta"] if mine else None,
                   spark=mine["spark"] if mine else [],
                   history=mine["history"] if mine else [])
        return out
    total = _total(kpi, targets, per, rows)
    if kpi.leaderboard or kpi.tile in (Kpi.Tile.LEADERBOARD, Kpi.Tile.MY_ROW):
        shape = Kpi.Tile.LEADERBOARD
        better_low = kpi.direction == "lower"
        ranked = sorted((r for r in row_out if r["value"] is not None),
                        key=lambda r: r["value"], reverse=not better_low)
        unranked = [r for r in row_out if r["value"] is None]
        row_out = ranked + unranked
        for i, r in enumerate(row_out):
            r["rank"] = i + 1 if r["value"] is not None else None
    else:
        shape = kpi.tile
    out.update(shape=shape, rows=row_out, total=True,
               total_label="team total" if rows == set(tracked) else "your team's total",
               summary=_summary(total, kpi, win, today, week_start),
               delta=_delta(total, kpi, min(win.last, today)),
               spark=_spark(total, kpi, win, today, week_start),
               history=_history(total, kpi, win, today, week_start))
    # The per-person target of the latest period, for "target 10 each".
    out["each_target"] = num(targets.of(P.start_of(min(win.last, today), kpi.cadence,
                                                   week_start)))
    return out


def load(kpis, first_day):
    """Readings, month targets and tracked people of these KPIs, in three
    queries."""
    ids = [k.pk for k in kpis]
    readings = defaultdict(list)
    for r in (KpiReading.objects.filter(kpi_id__in=ids, period_start__gte=first_day)
              .select_related("entered_by").order_by("period_start")):
        readings[r.kpi_id].append(r)
    months = defaultdict(dict)
    for t in KpiMonthTarget.objects.filter(kpi_id__in=ids):
        months[t.kpi_id][t.month] = t.value
    people = defaultdict(list)
    for p in (KpiPerson.objects.filter(kpi_id__in=ids, membership__revoked_at__isnull=True)
              .select_related("membership__user")):
        people[p.kpi_id].append(p)
    return readings, months, people


def earliest_needed(win, kpis, today, week_start):
    """The first day any drawing of these KPIs reads from."""
    firsts = [win.first]
    for k in kpis:
        # One more than the trend draws: it ends a period early while the
        # current one is still empty (`_drawn_to`), and the arrow compares
        # with the reading before.
        firsts.append(P.last_n(min(win.last, today), k.cadence, P.HISTORY + 1, week_start)[0])
    return min(firsts)


def visible_pages(reader, scorecard):
    pages = list(ScorecardPage.objects.filter(scorecard=scorecard, archived_at__isnull=True)
                 .select_related("team"))
    kpis = list(Kpi.objects.filter(scorecard=scorecard, archived_at__isnull=True)
                .select_related("page", "page__team", "audience_team", "reading_owner",
                                "source_a__page__team", "source_a__audience_team",
                                "source_b__page__team", "source_b__audience_team"))
    by_page = defaultdict(list)
    for k in kpis:
        by_page[k.page_id].append(k)
    shown = [(p, [k for k in by_page[p.pk] if reader.sees_kpi(k)]) for p in pages
             if reader.sees_page(p, by_page[p.pk])]
    return shown


def build(reader, scorecard, page_id, win, today) -> dict:
    """The page a reader asked for, or their first."""
    week_start = scorecard.week_start
    shown = visible_pages(reader, scorecard)
    chosen = next(((p, ks) for p, ks in shown if str(p.pk) == str(page_id)), None) \
        or (shown[0] if shown else None)
    out = {
        "company": {"id": str(scorecard.company_id), "name": scorecard.company.name},
        "week_start": week_start,
        "window": {"key": win.key, "label": win.label, "first": win.first.isoformat(),
                   "last": win.last.isoformat(), "text": window_text(win, today, week_start)},
        "pages": [{"id": str(p.pk), "name": p.name, "audience": p.audience}
                  for p, _ in shown],
        "page": str(chosen[0].pk) if chosen else None,
        "kpis": [],
        "may_set_up": reader.sets_up,
        "may_enter": False,
    }
    every_kpi = [k for _, ks in shown for k in ks]
    out["may_enter"] = any(reader.may_enter(k) for k in every_kpi)
    if not chosen:
        return out
    kpis = chosen[1]
    sources = [s for k in kpis if k.is_computed for s in (k.source_a, k.source_b)]
    readings, months, people = load(kpis + sources,
                                    earliest_needed(win, kpis, today, week_start))
    tiles = [tile(k, reader, Targets(k, months[k.pk]), readings[k.pk], people[k.pk], win,
                  today, week_start,
                  sources=(readings[k.source_a_id], readings[k.source_b_id])
                  if k.is_computed else None) for k in kpis]
    for t, k in zip(tiles, kpis):
        # The grid draws this window's own periods, and its roll-up beside
        # them (the tile's value), when the window holds more than one.
        t["history_is_window"] = len(P.periods_in(win, k.cadence, today, week_start)) >= 2
    out["kpis"] = tiles
    out["counts"] = counts(tiles)
    summaries = [t["summary"] for t in tiles if t.get("summary") and
                 t["summary"]["value"] is not None]
    if win.key == "this_week" and summaries and all(x.get("carried") for x in summaries):
        # Early in the week: what is shown is the week just closed.
        last = P.previous_start(win.first, P.WEEKLY, week_start)
        label = P.long_label(last, P.WEEKLY)
        out["window"]["text"] = f"{label[0].upper()}{label[1:]} · this week's readings " \
                                "aren't in yet"
    return out


def counts(tiles) -> dict:
    """"7 of 8 readings in · 2 behind, 1 off track": over the tiles drawn."""
    status = defaultdict(int)
    in_, of = 0, 0
    for t in tiles:
        summary = t.get("summary") or {}
        of += 1
        if summary.get("value") is not None and not summary.get("stale"):
            in_ += 1
        if summary.get("status"):
            status[summary["status"]] += 1
    return {"in": in_, "of": of, "on_track": status[P.ON_TRACK],
            "behind": status[P.BEHIND], "off_track": status[P.OFF_TRACK]}


def window_text(win, today, week_start) -> str:
    if win.key == "this_week":
        return P.long_label(win.first, P.WEEKLY)[0].upper() + P.long_label(
            win.first, P.WEEKLY)[1:]
    if win.key == "this_month":
        return f"{P.MONTHS[win.first.month - 1]} {win.first.year}, to date"
    if win.key == "this_quarter":
        return f"{P.long_label(win.first, P.QUARTERLY)}, to date"
    if win.key == "year_to_date":
        return f"{win.first.year}, to date"
    if win.key == "last_year":
        return str(win.first.year)
    return win.label


def today_for(tenant):
    """Today in the practice's own time zone: a week closes at its midnight."""
    from zoneinfo import ZoneInfo

    from django.utils import timezone

    if tenant is None or not getattr(tenant, "timezone", ""):
        return timezone.localdate()
    return timezone.now().astimezone(ZoneInfo(tenant.timezone)).date()


def scorecard_for(company):
    return Scorecard.objects.filter(company=company).select_related("company").first()
