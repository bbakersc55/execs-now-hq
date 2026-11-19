"""Set up KPIs from a sheet (2026-11-17, `docs/p6_m5_kpi_scorecard.md`,
"Set up KPIs from a sheet").

A practice owner or associate opens a Google Sheet through the practice's
Google connection, chooses its tab, the date column and whether those dates
are the first or the last day of each period. Every other column with a
header is proposed as a KPI:

- **the name** from the header, its unit marks taken off ("Revenue ($)" is
  Revenue);
- **the unit** from the header: $ is money, % is percent, otherwise a number;
- **the cadence** from the spacing of the dates;
- **a direction**: lower is better for costs, spend, cost-per figures (CPC),
  losses ("closed lost"), churn and the like; higher otherwise;
- **the roll-up** for longer views: average for rates and cost-per figures,
  last for balances (open pipeline, cash, "latest month"), sum for counts
  ("conversions") and the rest;
- **a priority**, Medium until changed (2026-11-18).

Each can be renamed, skipped or changed, and put on an existing page or a new
one with its audience; then they are made at once, **each KPI with a Sheets
feed on its own column** (`KpiFeed`, by column, `date_is` set), read straight
away so the history loads, and again by the nightly read. A blank cell is no
reading, never zero; a column with no header is skipped. Run again on the same
sheet, only the columns not yet set up are offered, and a KPI is never made
twice. It ends with a summary: KPIs made, readings loaded, cells skipped and
why.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from datetime import timedelta

from django.db import transaction

from . import feeds, sheets, setup
from . import periods as P
from .models import Audience, Kpi, KpiFeed, ScorecardPage

#: Below the header row, how many rows are looked at to propose.
LOOK = sheets.MOST_ROWS
#: Words that make lower better.
LOWER = re.compile(r"\b(cost|costs|spend|spent|expense|expenses|churn|cancel\w*|refund\w*|"
                   r"return\w*|complaint\w*|defect\w*|error\w*|late|overdue|turnover|"
                   r"attrition|downtime|scrap|rework|waste|days to|time to|dso|cpl|cpa|cac|"
                   r"cpc|cpm|cpv|cost per|lost|"
                   r"discount\w*|write.?off\w*|bad debt|no.?show\w*|vacan\w*)\b", re.I)
#: Rates and cost-per figures average over a longer view.
AVERAGE = re.compile(r"(\bper\b|/|\bavg\b|average|\brate\b|ratio|\bcpl\b|\bcpa\b|\bcac\b|"
                     r"\bcpc\b|\bcpm\b|\bcpv\b|"
                     r"\baov\b|margin|score|\bnps\b|occupancy|utili[sz]ation|conversion rate|"
                     r"\bmean\b)", re.I)
#: Counts add up over a longer view, whatever else the header says
#: ("Google Ads conversions"), unless it is a rate of them ("Calls per day").
COUNTS = re.compile(r"\b(conversions|clicks|impressions|leads|calls|sessions|visits|visitors|"
                    r"views|sign.?ups|bookings|orders|deals|sales|reviews|sends|opens|"
                    r"downloads|installs|transactions|units|tickets|jobs|appointments)\b", re.I)
RATE = re.compile(r"(\bper\b|/|\bavg\b|average|\brate\b|ratio|\bmean\b)", re.I)
#: Balances: the last reading of a longer view stands.
LAST = re.compile(r"(\bopen\b|pipeline|balance|backlog|outstanding|on hand|\bcash\b|"
                  r"headcount|inventory|latest|to date|\bytd\b|\bmtd\b|\bqtd\b|ending|"
                  r"\ba/?r\b|receivable|payable|active (clients|customers|members)|"
                  r"open (jobs|orders|tickets)|\bbank\b|runway)", re.I)
END_WORDS = re.compile(r"(ending|\bend\b|\bw/?e\b|through|thru|closing)", re.I)
START_WORDS = re.compile(r"(starting|\bstart\b|beginning|week of|month of|\bfrom\b)", re.I)


class SheetSetupRefused(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# ------------------------------------------------------------ proposing

def name_of(header: str) -> str:
    """The KPI's name from its header, its unit marks taken off: "Revenue
    ($)" is Revenue, "Gross margin %" is Gross margin."""
    text = re.sub(r"\(\s*(in\s+)?[$%#]\s*\)", " ", header or "")
    text = text.replace("$", " ").replace("%", " ")
    return " ".join(text.split()).strip(" -:")[:120] or " ".join((header or "").split())[:120]


def kind_of(header: str) -> str:
    if "$" in (header or ""):
        return Kpi.Kind.MONEY
    if "%" in (header or ""):
        return Kpi.Kind.PERCENT
    return Kpi.Kind.NUMBER


def direction_of(name: str) -> str:
    return Kpi.Direction.LOWER if LOWER.search(name or "") else Kpi.Direction.HIGHER


def rollup_of(name: str, kind: str) -> str:
    if LAST.search(name or ""):
        return Kpi.Rollup.LAST
    if kind == Kpi.Kind.PERCENT:
        return Kpi.Rollup.AVERAGE
    if COUNTS.search(name or "") and not RATE.search(name or ""):
        return Kpi.Rollup.SUM
    if AVERAGE.search(name or ""):
        return Kpi.Rollup.AVERAGE
    return Kpi.Rollup.SUM


def cadence_of(dates) -> str:
    """From the spacing of the dates: the middle gap between them."""
    days = sorted(set(dates))
    gaps = [(b - a).days for a, b in zip(days, days[1:])]
    if not gaps:
        return P.WEEKLY
    gap = statistics.median(gaps)
    if gap <= 2:
        return P.DAILY
    if gap <= 10:
        return P.WEEKLY
    if gap <= 45:
        return P.MONTHLY
    return P.QUARTERLY


def date_is_of(header: str, dates, cadence: str, week_start: str) -> str:
    """What the dates are: the header says so ("Week ending"), else the
    dates do (every one a Sunday for a Monday-start week is a week's last
    day; every one the 1st of a month is a month's first)."""
    if END_WORDS.search(header or ""):
        return KpiFeed.DateIs.END
    if START_WORDS.search(header or ""):
        return KpiFeed.DateIs.START
    if not dates:
        return KpiFeed.DateIs.ANY
    if cadence == P.WEEKLY:
        first = P.week_offset(week_start)
        days = {d.weekday() for d in dates}
        if days == {(first + 6) % 7}:
            return KpiFeed.DateIs.END
        if days == {first}:
            return KpiFeed.DateIs.START
    if cadence in (P.MONTHLY, P.QUARTERLY):
        if all(d.day == 1 for d in dates):
            return KpiFeed.DateIs.START
        if all((d + timedelta(days=1)).day == 1 for d in dates):
            return KpiFeed.DateIs.END
    return KpiFeed.DateIs.ANY


def _cells(rows, header_row, index):
    first = 0 if header_row is None else header_row + 1
    for i in range(first, min(len(rows), first + LOOK)):
        row = rows[i]
        yield i, (row[index] if index < len(row) else "")


def date_column_of(rows, header_row) -> int | None:
    """The column whose cells under the header are most often dates."""
    width = max((len(r) for r in rows), default=0)
    best, best_count = None, 0
    for c in range(width):
        count = sum(1 for _, cell in _cells(rows, header_row, c) if sheets.parse_date(cell))
        if count > best_count:
            best, best_count = c, count
    return best


def set_up_already(scorecard, spreadsheet_id, tab) -> dict:
    """{normalised header or column letter: KPI name} of the columns of this
    tab already feeding a live KPI of this scorecard."""
    out = {}
    for feed in (KpiFeed.objects.filter(kpi__scorecard=scorecard, kpi__archived_at__isnull=True,
                                        spreadsheet_id=spreadsheet_id, tab=tab, active=True,
                                        mode=KpiFeed.Mode.COLUMN)
                 .select_related("kpi")):
        if feed.value_header:
            out[sheets.normal(feed.value_header)] = feed.kpi.name
        if feed.value_column:
            out[f"#{feed.value_column}"] = feed.kpi.name
    return out


def _taken(scorecard) -> set:
    return {sheets.normal(n) for n in Kpi.objects.filter(
        scorecard=scorecard, archived_at__isnull=True).values_list("name", flat=True)}


def propose(scorecard, *, rows, header_row=None, date_column="", date_is=None,
            spreadsheet_id="", tab="") -> dict:
    """The proposal: the date column, what its dates are, the cadence, and a
    KPI for every other column with a header not yet set up."""
    if header_row is None:
        header_row = sheets.guess_header_row(rows)
    headers = sheets.header_names(rows, header_row)
    if not headers:
        raise SheetSetupRefused("This tab has no row of headers: put a header over each "
                                "column, then open it again.")
    at = sheets.column_index(date_column) if date_column else date_column_of(rows, header_row)
    if at is None:
        raise SheetSetupRefused("This tab has no column of dates.")
    date_header = headers[at] if at < len(headers) else ""
    dates = [d for _, cell in _cells(rows, header_row, at) if (d := sheets.parse_date(cell))]
    if not dates:
        raise SheetSetupRefused(f"Column {sheets.column_letter(at)} has no dates under it.")
    cadence = cadence_of(dates)
    if date_is is None:
        date_is = date_is_of(date_header, dates, cadence, scorecard.week_start)
    done = set_up_already(scorecard, spreadsheet_id, tab)
    taken = _taken(scorecard)
    columns, skipped, already = [], [], []
    width = max(len(headers), max((len(r) for r in rows), default=0))
    for c in range(width):
        if c == at:
            continue
        letter = sheets.column_letter(c)
        header = headers[c] if c < len(headers) else ""
        if not header:
            if any(sheets.text_of(cell) for _, cell in _cells(rows, header_row, c)):
                skipped.append({"column": letter, "reason": "No header, so it is skipped."})
            continue
        name_done = done.get(sheets.normal(header)) or done.get(f"#{letter}")
        if name_done:
            already.append({"column": letter, "header": header, "kpi": name_done})
            continue
        numbers, blanks, words = [], 0, 0
        for i, cell in _cells(rows, header_row, c):
            if not sheets.parse_date(rows[i][at] if at < len(rows[i]) else ""):
                continue
            try:
                value = sheets.parse_number(cell)
            except sheets.FeedRefused:
                words += 1
                continue
            if value is None:
                blanks += 1
            else:
                numbers.append(value)
        name = name_of(header)
        kind = kind_of(header)
        clash = sheets.normal(name) in taken
        columns.append({
            "column": letter, "header": header, "name": name, "kind": kind,
            "cadence": cadence, "direction": direction_of(name),
            "rollup": rollup_of(name, kind), "priority": Kpi.Priority.MEDIUM,
            "numbers": len(numbers), "blanks": blanks,
            "not_numbers": words,
            "sample": [format(v.normalize(), "f") for v in numbers[-3:]],
            "skip": clash or not numbers,
            "why_skip": (f"A KPI called {name} is on this scorecard already." if clash
                         else "No numbers under it." if not numbers else ""),
        })
    return {"header_row": header_row, "date_column": sheets.column_letter(at),
            "date_header": date_header, "date_is": date_is, "cadence": cadence,
            "dates": {"count": len(dates), "first": min(dates).isoformat(),
                      "last": max(dates).isoformat()},
            "columns": columns, "skipped": skipped, "already": already,
            "pages": [{"id": str(p.pk), "name": p.name, "audience": p.audience,
                       "audience_label": p.get_audience_display()}
                      for p in ScorecardPage.objects.filter(scorecard=scorecard,
                                                            archived_at__isnull=True)
                      .order_by("position")]}


# ------------------------------------------------------------ making them

class _Once:
    """The tab read once for every feed made: 39 reads of one tab would be
    39 calls to Google for the same cells."""

    def __init__(self, client, spreadsheet_id, tab, rows):
        self.client, self.key, self.rows_read = client, (spreadsheet_id, tab), rows

    def rows(self, spreadsheet_id, tab, **kwargs):
        if (spreadsheet_id, tab) == self.key:
            return [list(r) for r in self.rows_read]
        return self.client.rows(spreadsheet_id, tab, **kwargs)


def _pages(scorecard, wanted, actor) -> dict:
    """{key: page}: the existing pages named, and the new ones made."""
    out = {}
    for page in wanted or []:
        key = str(page.get("key") or "")
        if not key:
            raise SheetSetupRefused("A new page needs a key.")
        try:
            out[key] = setup.create_page(scorecard, {"name": page.get("name"),
                                                     "audience": page.get("audience")
                                                     or Audience.EVERYONE,
                                                     "team": page.get("team")}, actor)
        except setup.SetupError as exc:
            raise SheetSetupRefused(f"{page.get('name') or 'A new page'}: {exc}") from None
    return out


def create(scorecard, actor, data, *, client, connection, rows, today) -> dict:
    """Make the KPIs chosen, each with its feed, then read each once. Never
    a KPI twice: a column already set up, or a name already used, is not
    made again."""
    spreadsheet_id = sheets.spreadsheet_id_from(str(data.get("spreadsheet") or ""))
    tab = str(data.get("tab") or "").strip()
    if not spreadsheet_id or not tab:
        raise SheetSetupRefused("Open the sheet and choose its tab first.")
    header_row = data.get("header_row")
    try:
        header_row = int(header_row) if header_row not in (None, "") else None
    except (TypeError, ValueError):
        raise SheetSetupRefused("The header row is a number.") from None
    proposal = propose(scorecard, rows=rows, header_row=header_row,
                       date_column=str(data.get("date_column") or ""),
                       date_is=str(data.get("date_is") or ""),
                       spreadsheet_id=spreadsheet_id, tab=tab)
    if proposal["date_is"] not in KpiFeed.DateIs.values:
        raise SheetSetupRefused("A date is the first or the last day of its period.")
    offered = {c["column"]: c for c in proposal["columns"]}
    chosen = [c for c in data.get("columns") or [] if not c.get("skip")]
    names = Counter(sheets.normal(c.get("name") or "") for c in chosen)
    twice = sorted(n for n, k in names.items() if k > 1 and n)
    if twice:
        raise SheetSetupRefused(f"Two columns would both be called {twice[0]}: rename one.")
    taken = _taken(scorecard)
    already = list(proposal["already"])
    made, feeds_made = [], []
    with transaction.atomic():
        pages = _pages(scorecard, data.get("new_pages"), actor)
        for column in chosen:
            letter = str(column.get("column") or "").upper()
            found = offered.get(letter)
            if found is None:
                if letter not in {a["column"] for a in already}:
                    already.append({"column": letter, "header": column.get("header", ""),
                                    "kpi": "not in the sheet now"})
                continue
            name = " ".join(str(column.get("name") or "").split())
            if sheets.normal(name) in taken:
                raise SheetSetupRefused(f"A KPI called {name} is on this scorecard already: "
                                        "rename it or skip the column.")
            page = pages.get(str(column.get("new_page") or "")) if column.get("new_page") \
                else None
            page_id = str(page.pk) if page else str(column.get("page") or "")
            try:
                kpi = setup.create_kpi(scorecard, {
                    "name": name, "kind": column.get("kind") or found["kind"],
                    "cadence": column.get("cadence") or found["cadence"],
                    "direction": column.get("direction") or found["direction"],
                    "rollup": column.get("rollup") or found["rollup"],
                    "priority": column.get("priority") or found["priority"], "page": page_id,
                    "note": f"From {data.get('spreadsheet_name') or 'the sheet'}, "
                            f"{tab}, column {letter}."[:200]}, actor)
            except setup.SetupError as exc:
                raise SheetSetupRefused(f"{name or found['header']}: {exc}") from None
            feed = KpiFeed.objects.create(
                tenant_id=scorecard.tenant_id, kpi=kpi, connection=connection,
                spreadsheet_id=spreadsheet_id,
                spreadsheet_name=str(data.get("spreadsheet_name") or "")[:200], tab=tab[:200],
                mode=KpiFeed.Mode.COLUMN, date_column=proposal["date_column"],
                date_header=proposal["date_header"][:200], date_is=proposal["date_is"],
                value_column=letter, value_header=found["header"][:200],
                header_row=proposal["header_row"], created_by=actor)
            Kpi.objects.filter(pk=kpi.pk).update(feed=Kpi.Feed.SHEET)
            taken.add(sheets.normal(name))
            made.append(kpi)
            feeds_made.append(feed)
        setup.audit(scorecard.company, actor, "scorecard.kpis_from_sheet",
                    spreadsheet=data.get("spreadsheet_name") or spreadsheet_id, tab=tab,
                    kpis=[k.name for k in made])
    once = _Once(client, spreadsheet_id, tab, rows)
    loaded, reasons, failed = 0, Counter(), []
    blanks = sum(c["blanks"] for c in proposal["columns"]
                 if c["column"] in {f.value_column for f in feeds_made})
    for feed in feeds_made:
        feed.refresh_from_db()
        result = feeds.run(feed, today, client=once)
        if not result.get("ok"):
            failed.append({"kpi": feed.kpi.name, "error": result.get("error", "")})
            continue
        loaded += result.get("new", 0) + result.get("update", 0) + result.get("provisional", 0)
        plan = feeds.plan_for(feed.kpi, feed.config(), rows, today)
        for _row, why in plan.skipped:
            reasons[why if len(why) < 80 else why[:77] + "…"] += 1
    skipped_columns = proposal["skipped"] + [
        {"column": c.get("column"), "reason": "Skipped by you."}
        for c in data.get("columns") or [] if c.get("skip")]
    return {"created": [{"id": str(k.pk), "name": k.name, "page": k.page.name} for k in made],
            "readings": loaded, "blank_cells": blanks,
            "cells_skipped": [{"why": w, "count": n} for w, n in reasons.most_common()],
            "columns_skipped": skipped_columns, "already": already, "failed": failed}
