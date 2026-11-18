""""Set up KPIs from a sheet", walked in headless Chrome (2026-11-17).

    .venv/bin/python scripts/scorecard_sheet_walk.py

**A recorded sheet, not a real one**: the laptop has no Google connection
(its database is a scrubbed copy of production), so the server reads a
recorded sheet (`SCORECARD_RECORDED_SHEETS`, laptop only) shaped like the
first real one: "Week ending" in column A (Sundays, for a company whose week
starts Monday), an unnamed column B, and 39 KPI columns with $ and % in their
headers and values such as 1,530,000, some cells blank.

The real `seed_demo` into a scratch database (`execsnowhq_walk`, never
`execsnowhq_local`), then `manage.py scorecard_sheet_walk_setup` (a Google
connection row with the Sheets scope and no tokens, and the practice owner's
session), then this tree's pages on 127.0.0.1:8198 at 1366 wide. One line per
check; it exits 1 if any fails.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORT = 8198
BASE = f"http://127.0.0.1:{PORT}"
DB = "execsnowhq_walk"
SHEET_ID = "1RecordedWeeklyNumbersForTheSheetWalk00000000"
ADDRESS = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit#gid=0"
WALK = {"DATABASE_URL": f"postgres:///{DB}", "STORAGE_BACKEND": "local",
        "GCS_BUCKET_MEDIA": "execsnowhq-walk", "APP_ROOT_URL": "/",
        "NMI_LIVE_CALLS": "false", "APP_ENVIRONMENT": "local"}
RESULTS: list[tuple[bool, str]] = []
WEEKS = 26

#: 39 columns: (header, value in week n, or "" for a blank).
HEADERS = ["Revenue ($)", "Gross margin %", "Leads", "Cost per lead ($)",
           "Open pipeline ($)", "Close rate %", "Ad spend ($)", "Churn %", "New customers",
           "Average order ($)", "Refunds ($)", "Website visits", "Conversion rate %",
           "Payroll ($)", "Overtime hours", "On-time delivery %", "Backorders",
           "Inventory on hand ($)", "Cash in bank ($)", "AR over 60 days ($)", "DSO",
           "Support tickets", "First response hours", "NPS", "Reviews", "Referrals",
           "Quotes sent", "Quotes won", "Win rate %", "Gross profit ($)", "Net profit ($)",
           "EBITDA ($)", "Headcount", "Turnover %", "Training hours", "Safety incidents",
           "Scrap rate %", "Units shipped", "Latest month AR ($)"]


def value(header: str, column: int, n: int) -> str:
    if (n * 7 + column) % 23 == 0:
        return ""                                         # a blank cell: no reading
    base = 1_530_000 if "$" in header else 40 if "%" in header else 120
    number = base + (column + 1) * (n % 9) * (1000 if "$" in header else 1)
    if "%" in header:
        return f"{min(99.9, 30 + column / 2 + n / 10):.1f}%"
    return f"{number:,}"


def recorded_sheet() -> dict:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    rows = [["Week ending", ""] + HEADERS]
    for n in range(WEEKS, 0, -1):
        sunday = monday - timedelta(weeks=n) + timedelta(days=6)
        rows.append([f"{sunday.month}/{sunday.day}/{sunday.year}",
                     "Inventory count" if n % 6 == 0 else ""]
                    + [value(h, c, n) for c, h in enumerate(HEADERS)])
    return {SHEET_ID: {"title": "Northwind weekly numbers",
                       "tabs": {"Weekly": rows, "Read me": [["Notes for the team"]]}}}


def manage(*args, env=None) -> str:
    done = subprocess.run([str(ROOT / ".venv/bin/python"), "manage.py", *args], cwd=ROOT,
                          env={**os.environ, **WALK, **(env or {})}, capture_output=True,
                          text=True)
    if done.returncode != 0:
        sys.exit(f"manage.py {args[0]} failed:\n{done.stderr[-3000:]}")
    return done.stdout


def check(ok: bool, line: str) -> bool:
    RESULTS.append((bool(ok), line))
    print(("PASS  " if ok else "FAIL  ") + line, flush=True)
    return bool(ok)


def start_server(recorded: str):
    env = {**os.environ, **WALK, "PYTHONUNBUFFERED": "1",
           "SCORECARD_RECORDED_SHEETS": recorded}
    server = subprocess.Popen([str(ROOT / ".venv/bin/python"), "manage.py", "runserver",
                               f"127.0.0.1:{PORT}", "--noreload"], cwd=ROOT, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    for _ in range(80):
        try:
            urllib.request.urlopen(f"{BASE}/healthz", timeout=2)
            return server
        except Exception:
            if server.poll() is not None:
                sys.exit("The server did not start: " + server.stderr.read().decode()[-2000:])
            time.sleep(0.5)
    server.terminate()
    sys.exit("The server did not answer.")


def walk(browser, setup):
    context = browser.new_context(viewport={"width": 1366, "height": 900})
    context.add_cookies([{"name": setup["cookie"], "value": setup["session"], "url": BASE}])
    page = context.new_page()
    page.goto(f"{BASE}/companies/{setup['company']}", wait_until="domcontentloaded")
    page.get_by_role("button", name="Set up KPIs from a sheet").first.click(timeout=90000)
    page.get_by_label("The sheet's address").fill(ADDRESS)
    page.get_by_role("button", name="Open the sheet").click()
    table = page.get_by_role("table", name="Columns proposed as KPIs")
    table.wait_for(timeout=60000)
    rows = table.locator("tbody tr").count()
    dates_are = page.get_by_label("Its dates are").input_value()
    check(rows == 39 and page.get_by_label("Tab").input_value() == "Weekly"
          and page.get_by_label("Date column").input_value() == "A" and dates_are == "end",
          f"owner: the sheet opens through {setup['account']}: tab Weekly, date column A "
          f"(Week ending), its dates the last day of each period, {rows} columns proposed")
    shown = page.get_by_role("dialog").inner_text() if page.get_by_role("dialog").count() \
        else page.locator("body").inner_text()
    check("Column B: No header, so it is skipped." in shown and "26 dates" in shown
          and "Weekly" in shown, "owner: column B (no header) skipped; 26 weekly dates")
    units = {h: page.get_by_label(f"Unit for {h}").input_value()
             for h in ("Revenue ($)", "Gross margin %", "Leads")}
    rollups = {h: page.get_by_label(f"Roll-up for {h}").input_value()
               for h in ("Revenue ($)", "Cost per lead ($)", "Open pipeline ($)")}
    directions = {h: page.get_by_label(f"Direction for {h}").input_value()
                  for h in ("Ad spend ($)", "Revenue ($)")}
    check(units == {"Revenue ($)": "money", "Gross margin %": "percent", "Leads": "number"}
          and rollups == {"Revenue ($)": "sum", "Cost per lead ($)": "average",
                          "Open pipeline ($)": "last"}
          and directions == {"Ad spend ($)": "lower", "Revenue ($)": "higher"},
          f"owner: units {list(units.values())}, roll-ups {list(rollups.values())}, "
          f"directions {list(directions.values())} proposed from the headers")
    # The clicks: rename one, skip one, a new page for two, the rest on the first.
    page.get_by_label("Name for Revenue ($)").fill("Net revenue")
    page.get_by_label("Make Training hours").uncheck()
    page.get_by_label("New page name").fill("Money")
    page.get_by_label("New page audience").select_option("leadership")
    page.get_by_role("button", name="Add the page").click()
    page.get_by_label("Page for Revenue ($)").select_option(label="Money (new)")
    page.get_by_label("Page for Cash in bank ($)").select_option(label="Money (new)")
    make = page.get_by_role("button", name="Make 38 KPIs")
    check(make.is_enabled(), "owner: renamed Revenue to Net revenue, skipped Training hours, "
                             "a new page Money (senior leadership) for two")
    make.click()
    done = page.get_by_role("status", name="What was set up")
    done.wait_for(timeout=120000)
    summary = done.inner_text()
    check("38 KPIs made" in summary and "readings loaded" in summary
          and "blank cell" in summary and "Column B: No header" in summary
          and "Column AK: Skipped by you." in summary,
          "owner: the summary: " + " ".join(summary.split())[:220])
    page.get_by_role("button", name="Done").click()
    page.goto(f"{BASE}/companies/{setup['company']}/scorecard", wait_until="domcontentloaded")
    page.get_by_text("Gross margin").first.wait_for(timeout=60000)
    board = page.locator("main").inner_text()
    check("Gross margin" in board and "Leads" in board,
          "owner: the scorecard's first page shows the new KPIs, with their history read "
          "from the sheet")
    api = page.request.get(f"{BASE}/api/scorecard/setup/?company={setup['company']}").json()
    kpis = {k["name"]: k for k in api["kpis"]}
    money = next((p for p in api["pages"] if p["name"] == "Money"), {})
    check(len(kpis) >= 38 and money.get("audience") == "leadership"
          and kpis["Net revenue"]["page"] == money.get("id"),
          f"owner: {len(kpis)} KPIs on the scorecard; Net revenue on the new page Money "
          "(senior leadership and up)")
    # Again on the same sheet: only the column not set up is offered.
    page.goto(f"{BASE}/companies/{setup['company']}", wait_until="domcontentloaded")
    page.get_by_role("button", name="Set up KPIs from a sheet").first.click(timeout=90000)
    page.get_by_label("The sheet's address").fill(ADDRESS)
    page.get_by_role("button", name="Open the sheet").click()
    again = page.get_by_role("table", name="Columns proposed as KPIs")
    again.wait_for(timeout=60000)
    offered = again.locator("tbody tr").count()
    text = page.get_by_role("dialog").inner_text() if page.get_by_role("dialog").count() \
        else page.locator("body").inner_text()
    check(offered == 1 and page.get_by_label("Name for Training hours").count() == 1
          and "Already set up" in text and text.count("(") >= 38,
          f"owner: run again, only the column not set up is offered ({offered}); the 38 are "
          "listed as set up already, never made twice")
    context.close()


def main():
    from playwright.sync_api import sync_playwright

    print("Building the frontend…", file=sys.stderr)
    built = subprocess.run(["npm", "run", "build"], cwd=ROOT / "frontend", capture_output=True,
                           text=True)
    if built.returncode != 0:
        sys.exit("The frontend build failed:\n" + built.stdout[-2000:] + built.stderr[-2000:])
    subprocess.run(["dropdb", "--if-exists", DB], check=True)
    subprocess.run(["createdb", DB], check=True)
    print("Migrating and seeding the demo…", file=sys.stderr)
    manage("migrate", "--noinput")
    manage("collectstatic", "--noinput", "--clear")
    manage("seed_demo", "--database", DB, "--ff-email", "walk-owner@example.invalid",
           "--whole-database", env={"APP_ENVIRONMENT": "demo"})
    setup = json.loads(manage("scorecard_sheet_walk_setup").strip().splitlines()[-1])
    folder = tempfile.mkdtemp(prefix="sheet-walk-")
    recorded = os.path.join(folder, "recorded-sheet.json")
    with open(recorded, "w", encoding="utf-8") as out:
        json.dump(recorded_sheet(), out)
    print(f"Recorded sheet: {recorded} (no Google connection on this laptop)", file=sys.stderr)
    server = start_server(recorded)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            walk(browser, setup)
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)
    failed = [line for ok, line in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)} of {len(RESULTS)} checks passed (a recorded sheet).")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
