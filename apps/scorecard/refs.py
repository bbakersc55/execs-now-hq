"""Live targets and computed operands: what a KPI's target or a computed
KPI's operand is taken from, beyond a typed number or another KPI's
readings.

A **reference** is a small dict, stored as JSON on the KPI:

- ``{"kind": "kpi", "kpi": <id>}``: another KPI's latest reading (a live
  target only), on the same scorecard;
- ``{"kind": "target"}``: a source KPI's own target (an operand only);
- ``{"kind": "sheet_column", "column": "D", "header": "Total Homeowners"}``
  and ``{"kind": "sheet_cell", "cell": "B2"}``: a column or cell of the KPI's
  own Google Sheet feed, read with its reading;
- ``{"kind": "track", "measure": ...}`` and ``{"kind": "hubspot", "measure":
  ...}``: another field of its Track or HubSpot feed, worked out the same way.

A feed reference's numbers are read by that KPI's own feed run, one per
period, into `KpiFeedValue` under the reference's key; nothing else writes
them, and they are read only for KPIs of the same scorecard. A live target
holds its last value until the next one: the target of a period is the
latest value on or before its last day.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.utils import timezone

from . import periods as P

FEED_KINDS = ("sheet_column", "sheet_cell", "track", "hubspot")
_FOUR = Decimal("0.0001")
TARGET_KINDS = ("kpi",) + FEED_KINDS
OPERAND_KINDS = ("value", "target") + FEED_KINDS


class RefRefused(ValueError):
    """A reference that cannot be, said in words, with the field it is about."""

    def __init__(self, message, field=None):
        super().__init__(message)
        self.field = field


# ------------------------------------------------------------- naming them

def kind_of(ref) -> str:
    return (ref or {}).get("kind") or ""


def is_feed(ref) -> bool:
    return kind_of(ref) in FEED_KINDS


def key_of(ref, rule="last") -> str:
    """Where a feed reference's numbers are kept. A column is known by its
    heading where it has one (a column inserted moves nothing), and by how
    rows in one period combine, so two KPIs reading it differently don't
    share one number."""
    kind = kind_of(ref)
    if kind == "sheet_column":
        name = (ref.get("header") or "").strip().lower() or (ref.get("column") or "").upper()
        return f"column:{name}:{rule}"[:240]
    if kind == "sheet_cell":
        return f"cell:{(ref.get('cell') or '').upper()}"
    if kind in ("track", "hubspot"):
        return f"{kind}:{ref.get('measure') or ''}"
    return ""


def target_key(kpi) -> str:
    return key_of(kpi.target_live, "last") if is_feed(kpi.target_live) else ""


def operand_key(source, ref) -> str:
    """An operand column combines its rows as the source KPI's readings do."""
    return key_of(ref, source.rollup) if is_feed(ref) else ""


def words(ref, kpi=None) -> str:
    """"the sheet's Total Homeowners column", "Calls target's latest reading"."""
    kind = kind_of(ref)
    if kind == "kpi":
        from .models import Kpi

        other = Kpi.all_objects.filter(pk=ref.get("kpi")).only("name").first()
        return f"{other.name if other else 'another KPI'}'s latest reading"
    if kind == "target":
        return f"{kpi.name}'s target" if kpi is not None else "its target"
    if kind == "sheet_column":
        if ref.get("header"):
            return f"the sheet's {ref['header']} column"
        return f"column {ref.get('column')} of the sheet"
    if kind == "sheet_cell":
        return f"cell {ref.get('cell')} of the sheet"
    if kind in ("track", "hubspot"):
        from . import hubspot, track

        menu = track.MEASURES if kind == "track" else hubspot.MEASURES
        label = menu.get(ref.get("measure"), (ref.get("measure"),))[0]
        return f"{'Track' if kind == 'track' else 'HubSpot'}: {label}"
    return ""


# ------------------------------------------------------------- checking them

def _active_feed(kpi):
    """("sheet", feed) / ("track", feed) / ("hubspot", feed) / (None, None)."""
    from .models import KpiFeed, KpiHubSpotFeed, KpiTrackFeed

    for name, model in (("sheet", KpiFeed), ("track", KpiTrackFeed),
                        ("hubspot", KpiHubSpotFeed)):
        feed = model.all_objects.filter(kpi_id=kpi.pk, active=True).first() \
            if kpi.pk else None
        if feed is not None:
            return name, feed
    return None, None


def clean_feed_ref(kpi, raw, field) -> dict:
    """A column, cell or field of `kpi`'s own feed, as saved. A KPI with no
    feed yet may name one: its value comes with the feed's first read. A
    reference that doesn't fit the feed it has is refused in words."""
    from . import hubspot, sheets, track

    kind = kind_of(raw)
    if kind == "sheet_column":
        letter = str(raw.get("column") or "").strip().upper()[:3]
        header = " ".join(str(raw.get("header") or "").split())[:200]
        if not letter and not header:
            raise RefRefused("Name the sheet's column: its heading, or its letter.", field)
        if letter:
            try:
                sheets.column_index(letter)
            except sheets.FeedRefused as exc:
                raise RefRefused(str(exc), field) from None
        out = {"kind": kind, "column": letter, "header": header}
    elif kind == "sheet_cell":
        try:
            r, c = sheets.parse_cell(str(raw.get("cell") or ""))
        except sheets.FeedRefused as exc:
            raise RefRefused(str(exc), field) from None
        out = {"kind": kind, "cell": sheets.cell_name(r, c)}
    elif kind in ("track", "hubspot"):
        menu = track.MEASURES if kind == "track" else hubspot.MEASURES
        measure = str(raw.get("measure") or "")
        if measure not in menu:
            raise RefRefused("Choose a field from the list.", field)
        out = {"kind": kind, "measure": measure}
    else:
        raise RefRefused("Choose where the number comes from.", field)
    has, feed = _active_feed(kpi)
    if has is not None:
        wanted = "sheet" if kind.startswith("sheet") else kind
        said = {"sheet": "a Google Sheet", "track": "Track", "hubspot": "HubSpot"}
        if has != wanted:
            raise RefRefused(f"{kpi.name} reads from {said[has]}, so the number comes from "
                             f"its {said[has]} feed.", field)
        if has == "sheet" and feed.mode == "row" and kind == "sheet_column":
            raise RefRefused(f"{kpi.name}'s sheet is read by row, a column per period, so "
                             "name a cell.", field)
        if has == "sheet" and feed.mode != "row" and (feed.mode == "cell") != (kind == "sheet_cell"):
            raise RefRefused(f"{kpi.name}'s sheet is read "
                             f"{'from one cell' if feed.mode == 'cell' else 'by column'}, "
                             f"so name a {'cell' if feed.mode == 'cell' else 'column'}.",
                             field)
    return out


def clean_target(scorecard, kpi_id, raw, *, name, per_person, direction, computed):
    """A live target as saved, or None for a typed one."""
    from .models import Kpi

    if not raw or not kind_of(raw):
        return None
    if not isinstance(raw, dict) or kind_of(raw) not in TARGET_KINDS:
        raise RefRefused("A live target is another KPI's latest reading, or a column, cell "
                         "or field of this KPI's own feed.", "target_live")
    if direction == "range":
        raise RefRefused("A KPI judged by a range has no target to take live.", "target_live")
    if kind_of(raw) == "kpi":
        other = Kpi.objects.filter(scorecard=scorecard, pk=raw.get("kpi"),
                                   archived_at__isnull=True).first() \
            if _is_uuid(raw.get("kpi")) else None
        if other is None:
            raise RefRefused("Choose a KPI of this scorecard to take the target from.",
                             "target_live")
        if kpi_id is not None and other.pk == kpi_id:
            raise RefRefused("A KPI's target can't be its own reading.", "target_live")
        if other.per_person or other.is_computed:
            raise RefRefused(f"{other.name} is {'per person' if other.per_person else 'computed'}"
                             "; a live target is taken from a company KPI's own readings.",
                             "target_live")
        return {"kind": "kpi", "kpi": str(other.pk)}
    if computed:
        raise RefRefused(f"{name} is worked out from two other KPIs, so it has no feed to "
                         "take a target from.", "target_live")
    return clean_feed_ref(SimpleNamespace(pk=kpi_id, name=name), raw, "target_live")


def clean_operand(source, raw, field):
    """What of `source` a computed KPI uses: None for its readings."""
    if not raw or kind_of(raw) in ("", "value"):
        return None
    if not isinstance(raw, dict) or kind_of(raw) not in OPERAND_KINDS:
        raise RefRefused("Choose its value, its target, or a column, cell or field of its "
                         "feed.", field)
    if kind_of(raw) == "target":
        return {"kind": "target"}
    return clean_feed_ref(source, raw, field)


def _is_uuid(value) -> bool:
    from apps.work.views import _is_uuid as check

    return value is not None and check(str(value))


# ------------------------------------------------------------- reading them

def extras_of(kpi) -> list[tuple[str, dict, str]]:
    """What `kpi`'s feed reads beside its reading: (key, reference, rule) for
    its own live target and for every computed KPI's operand on it."""
    from django.db.models import Q

    from .models import Kpi

    out = {}
    if is_feed(kpi.target_live):
        out[target_key(kpi)] = (kpi.target_live, "last")
    for user in Kpi.all_objects.filter(Q(source_a=kpi) | Q(source_b=kpi),
                                       archived_at__isnull=True):
        for source_id, ref in ((user.source_a_id, user.operand_a),
                               (user.source_b_id, user.operand_b)):
            if source_id == kpi.pk and is_feed(ref):
                out[key_of(ref, kpi.rollup)] = (ref, kpi.rollup)
    return [(k, ref, rule) for k, (ref, rule) in out.items()]


class _Column:
    """What `sheets.plan_columns` asks of a KPI, for a column read beside it:
    a plain number, combined by `rule`."""

    def __init__(self, kpi, rule):
        self.name, self.cadence, self.rollup = kpi.name, kpi.cadence, rule
        self.per_person, self.kind = False, "number"
        self.duration_unit, self.rating_scale, self.target_value = "", None, None
        self.scorecard = kpi.scorecard


def read_sheet(feed, rows, today, now=None) -> int:
    """The columns or cells the KPI's sheet feed reads beside its reading.
    A column follows the sheet, as a reading does; a cell is read for the
    open period at each refresh and kept once its period has closed."""
    from . import sheets

    kpi = feed.kpi
    week_start = kpi.scorecard.week_start
    written = 0
    for key, ref, rule in extras_of(kpi):
        if kind_of(ref) == "sheet_column":
            if feed.mode != "column":
                how = "from one cell" if feed.mode == "cell" else "by row"
                raise sheets.FeedRefused(f"is read {how}, so it has no {words(ref)}")
            plan = sheets.plan_columns(_Column(kpi, rule), week_start, rows, {
                "date_column": feed.date_column, "date_header": feed.date_header,
                "value_column": ref.get("column", ""), "value_header": ref.get("header", ""),
                "header_row": feed.header_row})
            written += store(kpi, key, {s: v for (s, _), v in plan.values.items()}, today,
                             now=now)
        elif kind_of(ref) == "sheet_cell":
            value = sheets.read_cell(rows, ref["cell"])
            if value is None:
                continue
            values = {P.start_of(today, kpi.cadence, week_start): value,
                      sheets.cell_period(kpi, week_start, today): value}
            written += store(kpi, key, values, today, keep_closed=True, now=now)
    return written


def read_measures(kpi, kind, plan, today, *, snapshot=frozenset(), now=None) -> int:
    """The Track or HubSpot fields the KPI's feed reads beside its reading.
    `plan(measure)` gives {(start, None): value} for that field, the open
    period included."""
    written = 0
    for key, ref, _ in extras_of(kpi):
        if kind_of(ref) != kind:
            continue
        values = {s: v for (s, _), v in plan(ref["measure"]).items()}
        written += store(kpi, key, values, today, keep_closed=ref["measure"] in snapshot,
                         now=now)
    return written


def store(kpi, key, values: dict, today, *, keep_closed=False, now=None) -> int:
    """Write {start: value}. The open period's always follows; a closed
    period's follows too unless it is `keep_closed` (read at the close and
    kept). Nothing is deleted."""
    from .models import KpiFeedValue

    now = now or timezone.now()
    have = {v.period_start: v for v in KpiFeedValue.all_objects.filter(
        kpi=kpi, key=key, period_start__in=list(values))}
    written = 0
    for start, value in values.items():
        value = value.quantize(_FOUR)
        row = have.get(start)
        if row is None:
            KpiFeedValue.all_objects.create(tenant_id=kpi.tenant_id, kpi=kpi, key=key,
                                            period_start=start, value=value, read_at=now)
            written += 1
        elif row.value != value and not (keep_closed and P.closed(start, kpi.cadence, today)):
            KpiFeedValue.all_objects.filter(pk=row.pk).update(value=value, read_at=now,
                                                              updated_at=now)
            written += 1
    return written



def values_of(kpi_ids, keys) -> dict:
    """{(kpi_id, key): {start: value}} for these KPIs' feed values."""
    from .models import KpiFeedValue

    out = {}
    if not kpi_ids or not keys:
        return out
    for v in KpiFeedValue.all_objects.filter(kpi_id__in=list(kpi_ids), key__in=list(keys)):
        out.setdefault((v.kpi_id, v.key), {})[v.period_start] = v.value
    return out


def live_series(kpi, reader=None):
    """{start: value} a KPI's live target is taken from, or None when its
    target is typed. Another KPI's readings only from the same scorecard, and
    only when the reader may see that KPI: a target never shows what its
    source would not."""
    from .models import Kpi, KpiReading

    ref = kpi.target_live
    if not kind_of(ref):
        return None
    if kind_of(ref) == "kpi":
        other = Kpi.all_objects.filter(
            pk=ref.get("kpi"), scorecard_id=kpi.scorecard_id, archived_at__isnull=True
        ).select_related("page", "page__team", "audience_team").first() \
            if _is_uuid(ref.get("kpi")) else None
        if other is None or (reader is not None and not reader.sees_kpi(other)):
            return {}
        return {r.period_start: r.value for r in KpiReading.all_objects.filter(
            kpi=other, membership__isnull=True)}
    return values_of([kpi.pk], [target_key(kpi)]).get((kpi.pk, target_key(kpi)), {})


def latest_on(series: dict, day: date):
    """The latest value of `series` on or before `day`."""
    known = [s for s in series if s <= day]
    return series[max(known)] if known else None
