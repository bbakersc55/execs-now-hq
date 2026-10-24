"""A KPI's feed (M5 part 3): setting one up, previewing it and running it.
The arithmetic of a sheet is in `sheets.py`; this is the connection, the
saved mapping, the schedule and the failure notice.

**One practice's feed reads only through that practice's Google connection.**
The connection is looked up inside the practice (`GmailConnection` is
tenant-scoped), stored on the feed, and checked against the feed's practice
again before every read; a feed whose connection belongs to anyone else is
refused, not read.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from . import periods as P
from . import sheets
from .models import Kpi, KpiFeed

#: How often each refresh reads: the hourly job runs them all and a daily
#: feed is read when its last read is this old.
DAILY_AFTER = timedelta(hours=23)


class NoSheetsAccess(Exception):
    """The practice's Google connection can't read Sheets, said in words, with
    whether reconnecting fixes it."""

    def __init__(self, message, *, reconnect=False):
        super().__init__(message)
        self.reconnect = reconnect


# ------------------------------------------------------------- the connection

def has_sheets(connection) -> bool:
    from apps.crm.services.gmail_oauth import SHEETS_SCOPES

    return set(SHEETS_SCOPES) <= set(connection.scopes or [])


def connection_state(tenant_id, user) -> dict:
    """What the feed screen says about Google: connected or not, and whether
    the grant predates the Sheets permission ("Reconnect Google")."""
    from apps.crm.models import GmailConnection

    connections = list(GmailConnection.all_objects.filter(tenant_id=tenant_id))
    ready = next((c for c in connections if has_sheets(c)), None)
    mine = next((c for c in connections if c.user_id == user.pk), None)
    from config import environment

    demo = environment.is_demo()
    return {"ready": ready is not None and not demo,
            "account": ready.email_address if ready else (mine.email_address if mine else ""),
            "connected": bool(connections),
            "reconnect": bool(connections) and ready is None and not demo,
            "refusal": DEMO_REFUSAL if demo else ""}


DEMO_REFUSAL = ("This is the demo. It never reads a Google account, so a spreadsheet "
                "can't be connected here. Paste rows into the catch-up table instead.")


def sheets_connection(tenant_id, user=None):
    """The practice's connection that may read Sheets: the asker's own when it
    holds the scope, else any in the practice that does."""
    from apps.crm.models import GmailConnection
    from config import environment

    if environment.is_demo():
        raise NoSheetsAccess(DEMO_REFUSAL)

    connections = list(GmailConnection.all_objects.filter(tenant_id=tenant_id)
                       .order_by("created_at"))
    ready = [c for c in connections if has_sheets(c)]
    if user is not None:
        own = [c for c in ready if c.user_id == user.pk]
        if own:
            return own[0]
    if ready:
        return ready[0]
    if connections:
        raise NoSheetsAccess(
            "The practice's Google connection was made before the scorecard could read "
            "spreadsheets. Reconnect Google to add read-only access to Google Sheets.",
            reconnect=True)
    raise NoSheetsAccess("No Google account is connected for this practice. Connect "
                         "Google to read a spreadsheet.", reconnect=True)


def client_for(feed_or_tenant, user=None, *, factory=None):
    """The Sheets client for a feed (its own stored connection) or for the
    practice asking. Never another practice's connection."""
    factory = factory or sheets.SheetsClient
    if isinstance(feed_or_tenant, KpiFeed):
        feed = feed_or_tenant
        connection = feed.connection
        if connection is None or connection.tenant_id != feed.tenant_id \
                or not has_sheets(connection):
            connection = sheets_connection(feed.tenant_id)
            if connection.tenant_id != feed.tenant_id:          # pragma: no cover
                raise NoSheetsAccess("That connection belongs to another practice.")
        return factory(connection), connection
    connection = sheets_connection(feed_or_tenant, user)
    return factory(connection), connection


# ------------------------------------------------------------- the mapping

MODES = (KpiFeed.Mode.COLUMN, KpiFeed.Mode.CELL)


def clean(kpi, data) -> dict:
    """The mapping as saved, checked. Raises `sheets.FeedRefused`."""
    if kpi.is_computed:
        raise sheets.FeedRefused(f"{kpi.name} is worked out from two other KPIs, so it "
                                 "has no feed of its own.")
    spreadsheet_id = sheets.spreadsheet_id_from(str(data.get("spreadsheet") or
                                                    data.get("spreadsheet_id") or ""))
    if not spreadsheet_id:
        raise sheets.FeedRefused("Paste the spreadsheet's address from the browser's "
                                 "address bar.")
    tab = str(data.get("tab") or "").strip()
    if not tab:
        raise sheets.FeedRefused("Choose the tab the numbers are on.")
    mode = data.get("mode") or KpiFeed.Mode.COLUMN
    if mode not in MODES:
        raise sheets.FeedRefused("A sheet is read by column or from one cell.")
    refresh = data.get("refresh") or KpiFeed.Refresh.DAILY
    if refresh not in KpiFeed.Refresh.values:
        raise sheets.FeedRefused("Refresh hourly or daily.")
    out = {"spreadsheet_id": spreadsheet_id, "tab": tab[:200], "mode": mode,
           "refresh": refresh,
           "spreadsheet_name": str(data.get("spreadsheet_name") or "")[:200],
           "date_column": "", "date_header": "", "value_column": "", "value_header": "",
           "name_column": "", "name_header": "", "header_row": None, "cell": "",
           "people": {}}
    if mode == KpiFeed.Mode.CELL:
        if kpi.per_person:
            raise sheets.FeedRefused(f"{kpi.name} has a reading per person, so it is read "
                                     "by column: one cell holds one number.")
        r, c = sheets.parse_cell(str(data.get("cell") or ""))
        out["cell"] = sheets.cell_name(r, c)
        return out
    for role in ("date", "value", "name"):
        letter = str(data.get(f"{role}_column") or "").strip().upper()
        if letter:
            sheets.column_index(letter)
        out[f"{role}_column"] = letter[:3]
        out[f"{role}_header"] = str(data.get(f"{role}_header") or "").strip()[:200]
    header = data.get("header_row")
    out["header_row"] = int(header) if header not in (None, "") else None
    if out["header_row"] is not None and not 0 <= out["header_row"] < sheets.HEADER_SEARCH:
        raise sheets.FeedRefused(f"The header row is one of the top {sheets.HEADER_SEARCH}.")
    people = data.get("people") or {}
    if not isinstance(people, dict):
        raise sheets.FeedRefused("People are matched by name.")
    allowed = {str(m) for m in sheets.people_of(kpi)}
    for name, member in people.items():
        if member and str(member) not in allowed:
            raise sheets.FeedRefused(f"{name} is matched to someone {kpi.name} doesn't track.")
    out["people"] = {str(k)[:120]: str(v) for k, v in people.items() if v}
    if out["date_column"] == out["value_column"] and out["date_column"]:
        raise sheets.FeedRefused("The date and the number come from different columns.")
    return out


def plan_for(kpi, config, rows, today):
    """{start, member} -> value for what a read of these rows gives, and
    the plan itself for the preview."""
    week_start = kpi.scorecard.week_start
    if config["mode"] == KpiFeed.Mode.CELL:
        value = sheets.read_cell(rows, config["cell"])
        start = sheets.cell_period(kpi, week_start, today)
        plan = sheets.Plan()
        if value is not None:
            plan.values[(start, None)] = sheets.as_reading(kpi, value)
        return plan
    columns_config = dict(config)
    columns_config["people"] = {k: v for k, v in (config.get("people") or {}).items()}
    return sheets.plan_columns(kpi, week_start, rows, columns_config)


def describe_preview(kpi, plan, results) -> dict:
    """The preview as the mapping screen shows it."""
    from .board import name_of, num
    from apps.tenancy.models import Membership

    members = {m.pk: name_of(m.user) for m in Membership.all_objects.filter(
        pk__in={r["member"] for r in results if r["member"]}).select_related("user")}
    counts = {w: sum(1 for r in results if r["what"] == w) for w in sheets.WHAT_SAYS}
    return {
        "header_row": plan.header_row,
        "periods": [{"start": r["start"].isoformat(),
                     "label": P.long_label(r["start"], kpi.cadence),
                     "person": members.get(r["member"], "") if r["member"] else "",
                     "value": num(r["value"]), "had": num(r["had"]),
                     "what": r["what"], "says": sheets.WHAT_SAYS[r["what"]],
                     "rows": plan.rows_of.get((r["start"], r["member"]), [])}
                    for r in results[-sheets.PREVIEW_PERIODS:]],
        "more": max(0, len(results) - sheets.PREVIEW_PERIODS),
        "counts": counts,
        "skipped": [{"row": n, "why": why} for n, why in plan.skipped[:sheets.PREVIEW_SKIPPED]],
        "skipped_more": max(0, len(plan.skipped) - sheets.PREVIEW_SKIPPED),
        "unmatched": [{"name": n, "rows": c} for n, c in sorted(plan.unmatched.items())],
    }


def preview(kpi, config, rows, today) -> dict:
    """What saving this mapping would make, before anything is saved."""
    if config["mode"] == KpiFeed.Mode.CELL:
        value = sheets.read_cell(rows, config["cell"])
        if value is not None:
            value = sheets.as_reading(kpi, value)
        week_start = kpi.scorecard.week_start
        open_start = P.start_of(today, kpi.cadence, week_start)
        from .board import num

        return {"header_row": None, "periods": [], "more": 0, "skipped": [],
                "skipped_more": 0, "unmatched": [],
                "counts": {w: 0 for w in sheets.WHAT_SAYS},
                "cell": {"ref": config["cell"], "value": num(value),
                         "period": P.long_label(open_start, kpi.cadence),
                         "closes": P.end_of(open_start, kpi.cadence).isoformat()}}
    plan = plan_for(kpi, config, rows, today)
    results = sheets.outcome(kpi, plan.values, today, kpi.scorecard.week_start)
    return describe_preview(kpi, plan, results)


# ------------------------------------------------------------- running

def due(feed, now, today) -> bool:
    """Hourly feeds every pass, daily ones once a day; a cell feed whatever
    its refresh as soon as a period has closed without its reading, since
    the cell is read at each period's close."""
    if not feed.active:
        return False
    if feed.refresh == KpiFeed.Refresh.HOURLY or feed.last_run_at is None:
        return True
    if feed.mode == KpiFeed.Mode.CELL and _cell_waiting(feed, today):
        return True
    return now - feed.last_run_at >= DAILY_AFTER


def _cell_waiting(feed, today) -> bool:
    from .models import KpiReading

    start = sheets.cell_period(feed.kpi, feed.kpi.scorecard.week_start, today)
    return (feed.cell_from is None or start >= feed.cell_from) and not \
        KpiReading.all_objects.filter(kpi=feed.kpi, period_start=start,
                                      membership__isnull=True).exists()


def results_for(feed, plan, today) -> list[dict]:
    """What writing the plan would do. A cell's reading is the number read at
    its period's close: once stored it stays, and a period that closed
    before the feed was set up is not given today's number."""
    kpi = feed.kpi
    results = sheets.outcome(kpi, plan.values, today, kpi.scorecard.week_start)
    if feed.mode == KpiFeed.Mode.CELL:
        results = [dict(r, what="same") if r["what"] == "update" else r for r in results
                   if feed.cell_from is None or r["start"] >= feed.cell_from]
    return results


def run(feed, today, *, client=None, now=None) -> dict:
    """Read the sheet and write what it gives. A failure keeps every reading
    and is noted on the feed; its reading owner is told once, and the notice
    stays until a read succeeds."""
    now = now or timezone.now()
    kpi = feed.kpi
    feed.last_run_at = now
    try:
        if client is None:
            client, connection = client_for(feed)
            feed.connection = connection
        rows = client.rows(feed.spreadsheet_id, feed.tab)
        plan = plan_for(kpi, feed.config(), rows, today)
        if feed.mode == KpiFeed.Mode.COLUMN and not plan.values and not plan.unmatched \
                and not plan.skipped:
            raise sheets.FeedRefused("has no rows with a date and a number")
        counts = sheets.write(feed, results_for(feed, plan, today), now)
    except (sheets.SheetUnavailable, sheets.FeedRefused, NoSheetsAccess) as exc:
        message = failure_words(feed, exc)
        if feed.last_error != message:
            feed.last_error, feed.error_since = message, now
        feed.save(update_fields=["last_run_at", "last_error", "error_since", "connection",
                                 "updated_at"])
        return {"ok": False, "error": message}
    feed.last_error, feed.error_since = "", None
    feed.last_success_at, feed.last_counts = now, counts
    feed.save(update_fields=["last_run_at", "last_success_at", "last_error", "error_since",
                             "last_counts", "connection", "updated_at"])
    if kpi.feed != Kpi.Feed.SHEET:
        Kpi.all_objects.filter(pk=kpi.pk).update(feed=Kpi.Feed.SHEET)
    return {"ok": True, **counts}


def failure_words(feed, exc) -> str:
    """What went wrong, in the words the reading owner reads. A refusal of
    the mapping ("has no column called Occupancy") is said of the sheet."""
    text = str(exc)
    if isinstance(exc, sheets.FeedRefused) and text[:1].islower():
        where = f"The sheet '{feed.spreadsheet_name or 'the spreadsheet'}'"
        if feed.tab:
            where += f" (tab '{feed.tab}')"
        return f"{where} {text}."
    return text


def run_due(tenant_id, today, *, now=None) -> dict:
    """The worker's hourly pass over one practice's feeds, and only its own:
    each is read through the practice's connection (`client_for`)."""
    now = now or timezone.now()
    ran = failed = 0
    for feed in KpiFeed.all_objects.filter(
            tenant_id=tenant_id, active=True, kpi__archived_at__isnull=True,
            kpi__scorecard__company__deleted_at__isnull=True).select_related(
            "kpi", "kpi__scorecard", "connection"):
        if not due(feed, now, today):
            continue
        result = run(feed, today, now=now)
        ran += 1
        failed += int(not result["ok"])
    return {"ran": ran, "failed": failed}


# ------------------------------------------------------------- what people see

def source_text(feed) -> str:
    """For the tile's back: where the readings come from."""
    every = "every hour" if feed.refresh == KpiFeed.Refresh.HOURLY else "once a day"
    where = f"From the Google Sheet '{feed.spreadsheet_name or 'untitled'}', tab '{feed.tab}'"
    if feed.mode == KpiFeed.Mode.CELL:
        return f"{where}, cell {feed.cell}, read as each period closes"
    return f"{where}, read {every}"


def notices_for(user, company=None) -> list:
    """A failing feed, told to its KPI's reading owner: one notice per
    failure, there until a read succeeds."""
    rows = KpiFeed.objects.filter(active=True, kpi__archived_at__isnull=True,
                                  kpi__reading_owner_id=user.pk).exclude(last_error="") \
        .select_related("kpi", "kpi__scorecard__company")
    if company is not None:
        rows = rows.filter(kpi__scorecard__company=company)
    return [{"kind": "feed", "kpi": f.kpi.name, "kpi_id": str(f.kpi_id),
             "company": f.kpi.scorecard.company.name,
             "company_id": str(f.kpi.scorecard.company_id), "period_start": None,
             "text": f.last_error,
             "reminded_at": f.error_since.isoformat() if f.error_since else None}
            for f in rows.order_by("-error_since")]


def tracked_names(kpi) -> dict:
    from .board import name_of
    from .models import KpiPerson

    return {p.membership_id: name_of(p.membership.user) for p in
            KpiPerson.all_objects.filter(kpi=kpi, membership__revoked_at__isnull=True)
            .select_related("membership__user")}


def consent_url(request, kpi) -> str:
    """Reconnect Google with the Sheets permission added. Everything the
    asker's connection already holds (Drive, reading replies) is asked for
    again, so adding Sheets takes nothing away."""
    from apps.crm.models import GmailConnection
    from apps.crm.services import gmail_oauth

    from config import environment

    if environment.is_demo():
        raise NoSheetsAccess(DEMO_REFUSAL)
    if not gmail_oauth.is_configured(request.tenant):
        raise NoSheetsAccess("Google sign-in isn't configured on this server, so there is "
                             "nothing to connect to. Contact support.")
    mine = GmailConnection.objects.filter(user=request.user).first()
    held = set(mine.scopes or []) if mine else set()
    state = gmail_oauth.new_state()
    session = request.session
    session[gmail_oauth.STATE_SESSION_KEY] = state
    session[gmail_oauth.RETURN_SESSION_KEY] = f"scorecard:{kpi.scorecard.company_id}"
    session[gmail_oauth.DRIVE_SESSION_KEY] = False
    session[gmail_oauth.INBOUND_SESSION_KEY] = False
    session[gmail_oauth.SHEETS_SESSION_KEY] = True
    email = request.user.email
    return gmail_oauth.authorization_url(
        state, login_hint=email, hd=gmail_oauth.workspace_domain(email),
        drive=set(gmail_oauth.DRIVE_SCOPES) <= held,
        inbound=set(gmail_oauth.TIER2_SCOPES) <= held, sheets=True, tenant=request.tenant)
