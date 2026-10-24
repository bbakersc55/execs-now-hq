"""The Google Sheet feed (M5 part 3, spec "Feeds"): reading a client's sheet
into a KPI's readings, in column mode or cell mode.

The rules that hold for every feed, and here first:

- **Closed periods only.** A feed writes the reading of a period once it has
  ended; an open period waits for its close.
- **The hand wins.** A reading someone typed is never overwritten; the run
  counts it as kept, and the tile's back says the reading was entered by hand.
- **Never deletes.** A row that disappears from the sheet leaves its reading.
- **A failed read keeps the last readings** and tells the reading owner once,
  in plain words, until a read succeeds again.

Everything that decides anything is in plain functions over a grid of cell
text (`rows`), so the tests that matter run against a fake client, not
against Google. `SheetsClient` is thin on purpose, like `meetings.drive`.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from django.db import transaction
from django.utils import timezone

from . import periods as P

#: How much of a tab the mapping screen shows: enough to see the shape of a
#: messy sheet without paging through it.
GRID_ROWS, GRID_COLUMNS = 40, 26
#: Where a header row is looked for, from the top.
HEADER_SEARCH = 20
#: How many rows a column read takes in: years of weeks, with room.
MOST_ROWS = 5000
#: The preview lists at most this many periods and this many skipped rows.
PREVIEW_PERIODS, PREVIEW_SKIPPED = 60, 30

ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{20,128}")
CELL_PATTERN = re.compile(r"^\$?([A-Za-z]{1,3})\$?([1-9][0-9]{0,6})$")


class SheetUnavailable(Exception):
    """Google could not be reached, or refused. Said in words."""


class FeedRefused(ValueError):
    """The mapping asked for something that cannot be, said in words."""


# ------------------------------------------------------------- addresses

def spreadsheet_id_from(value: str) -> str:
    """The spreadsheet's id out of whatever was pasted: the address bar's
    whole address, or the id alone. `""` when neither."""
    value = (value or "").strip().strip("<>")
    if not value:
        return ""
    if "/" in value or ":" in value:
        parsed = urlparse(value if "//" in value else f"https://{value}")
        parts = [p for p in parsed.path.split("/") if p]
        if "d" in parts and parts.index("d") + 1 < len(parts):
            value = parts[parts.index("d") + 1]
        else:
            return ""
    value = value.split("?")[0].split("#")[0]
    return value if ID_PATTERN.fullmatch(value) else ""


def column_letter(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    out = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        out = chr(65 + rem) + out
    return out


def column_index(letter: str) -> int:
    n = 0
    for ch in letter.upper():
        if not "A" <= ch <= "Z":
            raise FeedRefused(f"{letter} isn't a column.")
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def parse_cell(ref: str) -> tuple[int, int]:
    """'C4' -> (row index 3, column index 2)."""
    match = CELL_PATTERN.match((ref or "").strip())
    if not match:
        raise FeedRefused("Choose the one cell that holds the number, like C4.")
    return int(match.group(2)) - 1, column_index(match.group(1))


def cell_name(row: int, col: int) -> str:
    return f"{column_letter(col)}{row + 1}"


def a1_tab(tab: str) -> str:
    """A tab's name as A1 notation wants it: quoted, quotes doubled."""
    return "'" + tab.replace("'", "''") + "'"


# ------------------------------------------------------------- cell text

_EXCEL_EPOCH = date(1899, 12, 30)
_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y", "%Y/%m/%d",
                 "%b %d, %Y", "%B %d, %Y", "%b %d %Y", "%B %d %Y", "%d %b %Y", "%d %B %Y",
                 "%a, %b %d, %Y", "%A, %B %d, %Y", "%b %Y", "%B %Y", "%b-%y", "%b-%Y",
                 "%m/%Y", "%Y-%m")
_QUARTER = re.compile(r"^(?:q([1-4])\s*[-/ ]?\s*(\d{4})|(\d{4})\s*[-/ ]?\s*q([1-4]))$", re.I)


def text_of(cell) -> str:
    return "" if cell is None else str(cell).strip()


def parse_date(cell) -> date | None:
    """A date out of a cell as people type them: 10/19/2026, 2026-10-19,
    Oct 19, 2026, October 2026, Q4 2026, or a spreadsheet's day number.
    `None` for anything else (a heading, a note, a total row)."""
    text = text_of(cell)
    if not text:
        return None
    if re.fullmatch(r"\d{5}(\.\d+)?", text):
        serial = int(float(text))
        if 20000 <= serial <= 80000:                   # 1954 to 2119
            return _EXCEL_EPOCH + timedelta(days=serial)
        return None
    quarter = _QUARTER.match(text)
    if quarter:
        q = int(quarter.group(1) or quarter.group(4))
        year = int(quarter.group(2) or quarter.group(3))
        return date(year, 3 * (q - 1) + 1, 1)
    cleaned = re.sub(r"\s+", " ", text.replace(".", "").replace("Sept ", "Sep "))
    # "Week of 10/19/2026", "w/e 10/25/2026": the date in it.
    found = re.search(r"\d{1,4}[/-]\d{1,2}([/-]\d{2,4})?", cleaned)
    candidates = [cleaned] + ([found.group(0)] if found and found.group(0) != cleaned else [])
    for candidate in candidates:
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(candidate, fmt).date()
            except ValueError:
                continue
    return None


def parse_number(cell) -> Decimal | None:
    """A number out of a cell as a sheet shows it: 1,234.50, $1,234, (1,200),
    82%, 3.5 hrs. `None` for a blank cell. Text that holds no number raises
    `FeedRefused` with the words the preview shows."""
    text = text_of(cell)
    if not text or text in ("-", "—", "–"):
        return None
    negative = text.startswith("(") and text.endswith(")")
    core = text.strip("()").replace(",", "").replace("$", "").replace("€", "") \
        .replace("£", "").replace("%", "").strip()
    core = re.sub(r"\s*(hrs?|hours?|mins?|minutes?|days?)$", "", core, flags=re.I)
    if core.startswith("-"):
        negative, core = not negative, core[1:].strip()
    try:
        value = Decimal(core)
    except InvalidOperation:
        raise FeedRefused(f'"{text}" isn\'t a number.') from None
    if not value.is_finite():
        raise FeedRefused(f'"{text}" isn\'t a number.')
    return -value if negative else value


def as_reading(kpi, value: Decimal) -> Decimal:
    """The number, checked against the KPI's kind the way a typed one is."""
    from .readings import ReadingRefused, parse

    try:
        return parse(kpi, format(value, "f"))
    except ReadingRefused as exc:
        raise FeedRefused(str(exc)) from None


# ------------------------------------------------------------- the header

def normal(text) -> str:
    return re.sub(r"\s+", " ", text_of(text)).casefold()


def guess_header_row(rows) -> int | None:
    """The row that names the columns: the first, within the top rows, with
    two or more text cells and a row with a date in it somewhere below.
    `None` when the data has no header (it starts at the top)."""
    for i, row in enumerate(rows[:HEADER_SEARCH]):
        texts = [c for c in row if text_of(c) and parse_date(c) is None
                 and _is_text(c)]
        if len(texts) < 2:
            continue
        below = rows[i + 1:i + 6]
        if any(parse_date(c) for r in below for c in r):
            return i
    return None


def _is_text(cell) -> bool:
    try:
        return parse_number(cell) is None and bool(text_of(cell))
    except FeedRefused:
        return True


def header_names(rows, header_row) -> list[str]:
    if header_row is None or header_row >= len(rows):
        return []
    return [text_of(c) for c in rows[header_row]]


def locate(rows, header_row, columns: dict) -> tuple[int | None, dict]:
    """Where the mapped columns are today. `columns` is {role: (letter,
    header)}. A column is found by its header when it has one, so a column
    inserted in the sheet moves nothing; else by its letter. Raises the
    failure the spec quotes when a named column is gone."""
    named = {role: normal(h) for role, (_, h) in columns.items() if h}
    if named:
        # The row holding the most of the headings; one it lacks is gone.
        best, found_in = -1, None
        for i, row in enumerate(rows[:HEADER_SEARCH]):
            cells = [normal(c) for c in row]
            have = sum(want in cells for want in named.values())
            if have > best:
                best, found_in = have, i
        cells = [normal(c) for c in rows[found_in]] if found_in is not None else []
        missing = [h for _, (_, h) in columns.items() if h and normal(h) not in cells]
        if missing:
            raise FeedRefused(f"has no column called {missing[0]}")
        header_row = found_in
    found = {}
    for role, (letter, header) in columns.items():
        if header and header_row is not None:
            found[role] = [normal(c) for c in rows[header_row]].index(normal(header))
        else:
            found[role] = column_index(letter)
    return header_row, found


# ------------------------------------------------------------- column mode

@dataclass
class Plan:
    """What a read of the sheet would write: one value per period (and
    person), each with the rows it came from; and the rows left out, why."""

    values: dict = field(default_factory=dict)          # (start, member) -> Decimal
    rows_of: dict = field(default_factory=lambda: defaultdict(list))
    skipped: list = field(default_factory=list)          # (row number, reason)
    unmatched: dict = field(default_factory=dict)        # sheet name -> row count
    header_row: int | None = None


def people_of(kpi) -> dict:
    """The people a per-person KPI tracks: membership id -> the ways a sheet
    might name them (full name, first name, email)."""
    from .models import KpiPerson

    out = {}
    for p in KpiPerson.all_objects.filter(kpi=kpi, membership__revoked_at__isnull=True) \
            .select_related("membership__user"):
        user = p.membership.user
        full = normal(getattr(user, "full_name", "") or "")
        names = {n for n in (full, normal(user.email)) if n}
        if full:
            names.add(full.split(" ")[0])
        out[p.membership_id] = names
    return out


def match_person(name: str, people: dict, chosen: dict):
    """The membership a sheet's name means: one chosen on the mapping screen
    first, then a full name or email, then a first name that only one person
    has. `None` when nobody, or more than one, fits."""
    key = normal(name)
    if key in chosen:
        return chosen[key]
    exact = [m for m, names in people.items() if key in names and " " in key or
             key in names and "@" in key]
    if len(exact) == 1:
        return exact[0]
    first = [m for m, names in people.items() if key in names]
    return first[0] if len(first) == 1 else None


def plan_columns(kpi, week_start, rows, config) -> Plan:
    """Column mode: a date column, a value column and, for a per-person KPI,
    a name column. Rows that are not readings (blank, headings, totals,
    notes) are left out and said why; several rows in one period combine by
    the KPI's roll-up."""
    columns = {"date": (config.get("date_column", ""), config.get("date_header", "")),
               "value": (config.get("value_column", ""), config.get("value_header", ""))}
    if kpi.per_person:
        if not (config.get("name_column") or config.get("name_header")):
            raise FeedRefused(f"{kpi.name} has a reading per person: choose the column "
                              "with their names.")
        columns["name"] = (config.get("name_column", ""), config.get("name_header", ""))
    for role, (letter, header) in columns.items():
        if not letter and not header:
            raise FeedRefused(f"Choose the {role} column.")
    header_row, at = locate(rows, config.get("header_row"), columns)
    plan = Plan(header_row=header_row)
    people = people_of(kpi) if kpi.per_person else {}
    chosen = {normal(k): uuid.UUID(str(v)) for k, v in (config.get("people") or {}).items() if v}
    gathered = defaultdict(list)
    first = 0 if header_row is None else header_row + 1
    for i in range(first, min(len(rows), first + MOST_ROWS)):
        row = rows[i]
        cell = (lambda role: row[at[role]] if at[role] < len(row) else "")
        if not any(text_of(c) for c in row):
            continue                                   # a blank row says nothing
        day = parse_date(cell("date"))
        if day is None:
            if text_of(cell("date")):
                plan.skipped.append((i + 1, f'"{text_of(cell("date"))}" isn\'t a date.'))
            continue
        try:
            raw = parse_number(cell("value"))
        except FeedRefused as exc:
            plan.skipped.append((i + 1, str(exc)))
            continue
        if raw is None:
            continue                                   # no number yet for that date
        try:
            value = as_reading(kpi, raw)
        except FeedRefused as exc:
            plan.skipped.append((i + 1, str(exc)))
            continue
        member = None
        if kpi.per_person:
            name = text_of(cell("name"))
            if not name:
                plan.skipped.append((i + 1, "No name in the name column."))
                continue
            member = match_person(name, people, chosen)
            if member is None:
                plan.unmatched[name] = plan.unmatched.get(name, 0) + 1
                continue
        start = P.start_of(day, kpi.cadence, week_start)
        gathered[(start, member)].append(value)
        plan.rows_of[(start, member)].append(i + 1)
    for key, values in gathered.items():
        plan.values[key] = combine(kpi, values)
    return plan


def combine(kpi, values):
    """Several rows in one period, by the KPI's roll-up: daily rows feeding a
    weekly KPI add up, average, or the last one stands."""
    from .models import Kpi

    if len(values) == 1 or kpi.rollup == Kpi.Rollup.LAST:
        return values[-1]
    if kpi.rollup == Kpi.Rollup.AVERAGE:
        return (sum(values) / len(values)).quantize(Decimal("0.0001"))
    return sum(values)


# ------------------------------------------------------------- cell mode

def read_cell(rows, ref):
    """The cell's number now, or `None` when it is blank."""
    r, c = parse_cell(ref)
    raw = rows[r][c] if r < len(rows) and c < len(rows[r]) else ""
    return parse_number(raw)


def cell_period(kpi, week_start, today):
    """The period a cell read today stands for: the one that closed most
    recently. A cell is read at each period's close, so it is that period's
    reading."""
    return P.previous_start(P.start_of(today, kpi.cadence, week_start), kpi.cadence,
                            week_start)


# ------------------------------------------------------------- what it would do

def outcome(kpi, plan_values: dict, today, week_start, source=None) -> list[dict]:
    """For each period the read gives, what writing it would do: new, an
    update of the feed's own earlier reading, the same, kept as typed by
    hand, or waiting for the period to close."""
    from .models import KpiReading

    existing = {(r.period_start, r.membership_id): r for r in
                KpiReading.all_objects.filter(kpi=kpi, period_start__in={
                    s for s, _ in plan_values})}
    out = []
    for (start, member), value in sorted(plan_values.items(), key=lambda kv: (
            kv[0][0], str(kv[0][1] or ""))):
        have = existing.get((start, member))
        if not P.closed(start, kpi.cadence, today):
            what = "open"
        elif have is None:
            what = "new"
        elif have.source != (source or have.Source.SHEET):   # another feed's, or the hand's
            what = "kept"
        elif have.value == value:
            what = "same"
        else:
            what = "update"
        out.append({"start": start, "member": member, "value": value, "what": what,
                    "had": have.value if have is not None else None})
    return out


WHAT_SAYS = {"new": "New reading", "update": "Replaces the sheet's earlier value",
             "same": "Already in", "kept": "Kept: entered by hand",
             "open": "Waits until the period closes"}


@transaction.atomic
def write(feed, results, now=None, source=None) -> dict:
    """Write what `outcome` said: new and update rows only. Nothing typed by
    hand is touched and nothing is deleted."""
    from .models import KpiReading, KpiReadingChange

    now = now or timezone.now()
    kpi = feed.kpi
    counts = {"new": 0, "update": 0, "kept": 0, "same": 0, "open": 0}
    for r in results:
        counts[r["what"]] += 1
        if r["what"] == "new":
            try:
                with transaction.atomic():
                    reading = KpiReading.all_objects.create(
                        tenant_id=kpi.tenant_id, kpi=kpi, period_start=r["start"],
                        membership_id=r["member"], value=r["value"],
                        source=source or KpiReading.Source.SHEET, entered_at=now)
            except Exception:                              # typed by hand meanwhile
                counts["new"] -= 1
                counts["kept"] += 1
                continue
            KpiReadingChange.all_objects.create(tenant_id=kpi.tenant_id, reading=reading,
                                                value=r["value"])
        elif r["what"] == "update":
            reading = KpiReading.all_objects.select_for_update().get(
                kpi=kpi, period_start=r["start"], membership_id=r["member"])
            if reading.source != (source or KpiReading.Source.SHEET):   # the hand won meanwhile
                counts["update"] -= 1
                counts["kept"] += 1
                continue
            KpiReadingChange.all_objects.create(
                tenant_id=kpi.tenant_id, reading=reading, value=r["value"],
                previous_value=reading.value)
            reading.value, reading.entered_at = r["value"], now
            reading.save(update_fields=["value", "entered_at", "updated_at"])
    return counts


# ------------------------------------------------------------- Google

class SheetsClient:
    """The real one, on the practice's Google connection, which already
    holds the refresh token: Sheets is one more read-only scope on it."""

    def __init__(self, connection):
        self.connection = connection

    def _service(self):
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        from apps.crm.services import transport

        try:
            token = transport.access_token_for(self.connection)
        except transport.TransportUnavailable as exc:
            raise SheetUnavailable(
                f"Google refused the practice's connection ({self.connection.email_address}). "
                "Reconnect Google on the scorecard.") from exc
        return build("sheets", "v4", credentials=Credentials(token), cache_discovery=False)

    def _refusal(self, exc) -> SheetUnavailable:
        status = getattr(getattr(exc, "resp", None), "status", None)
        account = self.connection.email_address
        if status in (401, 403):
            return SheetUnavailable(
                f"{account} can't open that spreadsheet. Ask whoever owns it to share it "
                f"with {account} (Viewer is enough).")
        if status == 404:
            return SheetUnavailable("That spreadsheet doesn't exist any more, or the "
                                    "address is wrong.")
        if status == 400:
            return SheetUnavailable("Google couldn't read that tab. It may have been "
                                    "renamed or removed.")
        return SheetUnavailable(f"Google Sheets didn't answer ({status or exc}). "
                                "It will be tried again at the next refresh.")

    def spreadsheet(self, spreadsheet_id) -> dict:
        """{title, tabs: [{title, id}]}"""
        try:
            got = self._service().spreadsheets().get(
                spreadsheetId=spreadsheet_id,
                fields="properties.title,sheets.properties(title,sheetId)").execute()
        except SheetUnavailable:
            raise
        except Exception as exc:                          # pragma: no cover - network
            raise self._refusal(exc) from exc
        return {"title": got["properties"]["title"],
                "tabs": [{"title": s["properties"]["title"], "id": s["properties"]["sheetId"]}
                         for s in got.get("sheets", [])]}

    def rows(self, spreadsheet_id, tab, *, last_row=MOST_ROWS) -> list[list[str]]:
        """The tab's cells as the sheet shows them, top-left first."""
        try:
            got = self._service().spreadsheets().values().get(
                spreadsheetId=spreadsheet_id, range=f"{a1_tab(tab)}!A1:ZZ{last_row}",
                valueRenderOption="FORMATTED_VALUE").execute()
        except SheetUnavailable:
            raise
        except Exception as exc:                          # pragma: no cover - network
            raise self._refusal(exc) from exc
        return [[text_of(c) for c in row] for row in got.get("values", [])]
