"""The employee records, walked in headless Chrome (2026-11-17).

    .venv/bin/python scripts/people_records_walk.py

The real `seed_demo` into a scratch database (`execsnowhq_walk`, never
`execsnowhq_local`), whose People seed makes Acme Fasteners' records; then
`manage.py people_records_walk_setup` (a session for each level, and Lola's
signing link); then this tree's pages on 127.0.0.1:8197, at 1366 and at 390
wide, as the practice owner, an HR Generalist, the client owner, senior
leadership, a manager, an employee and an assistant. Part 1's gates are
real: whoever holds an HR permission sets up two-factor on Profile with the
key read off the page, and a code is worked out from it (RFC 6238). Last,
Lola signs her offer from the link, signed out, and the owner sees her
onboarding start. One line per check; it exits 1 if any fails.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import people_security_walk as base  # noqa: E402  (its helpers: the server, codes, checks)
from people_security_walk import BASE, api_status, check, wide_enough  # noqa: E402

HR = ("owner", "client owner", "generalist")
#: The walk's own mail catcher (mailpit): a signature request, a signing's
#: notices and the signed copy really go out, to it.
MAIL_SMTP, MAIL_API = 8125, 8126


def start_mailpit():
    import shutil
    import subprocess
    import time
    import urllib.request

    found = shutil.which("mailpit")
    if not found:
        sys.exit("mailpit is not installed (docs/05_dev_environment.md).")
    proc = subprocess.Popen([found, "--smtp", f"127.0.0.1:{MAIL_SMTP}", "--listen",
                             f"127.0.0.1:{MAIL_API}"], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    for _ in range(40):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{MAIL_API}/api/v1/messages", timeout=2)
            return proc
        except Exception:
            if proc.poll() is not None:
                sys.exit(f"mailpit could not start on {MAIL_SMTP} or {MAIL_API}.")
            time.sleep(0.25)
    proc.terminate()
    sys.exit("mailpit did not answer.")


def body_rows(table) -> int:
    """A table's rows of people: on a phone its header row is hidden."""
    return table.locator("tbody tr").count()


#: Bugs's onboarding items done: six seeded, one more once the manager
#: finishes one of theirs at 1366.
DONE = {"bugs": 6}


def fits(page) -> tuple[bool, str]:
    """Whether the page fits its width, and if not, what sticks out."""
    if wide_enough(page):
        return True, ""
    found = page.evaluate("""() => [...document.querySelectorAll('body *')]
      .filter(e => e.getBoundingClientRect().right > window.innerWidth + 1)
      .slice(-4).map(e => e.tagName.toLowerCase() + (e.className ? '.' + e.className : '')
        + ' ' + Math.round(e.getBoundingClientRect().right))""")
    return False, "; sticking out: " + ", ".join(found)


def visit(page, path):
    page.goto(BASE + path, wait_until="domcontentloaded")


def text_of(page) -> str:
    return page.locator("main").inner_text(timeout=60000)


def ready(browser, setup, who, width, keys):
    """A page for this level; whoever holds HR sets up two-factor once."""
    person = setup["people"][who]
    context, page = base.page_for(browser, setup["cookie"], person["session"], width)
    if who in HR and who not in keys:
        keys[who] = base.enroll(page, who)
    return context, page


def walk(browser, setup, width, keys):
    acme = setup["acme"]
    r = setup["records"]
    people = f"/people/{acme}"

    # ------------------------------------------------ the practice owner
    context, page = ready(browser, setup, "owner", width, keys)
    visit(page, people)
    table = page.get_by_role("table", name="Directory")
    table.wait_for(timeout=60000)
    rows = body_rows(table)
    shown = text_of(page)
    check(rows == 15 and "Headcount" in shown and "Offer out: 1" in shown
          and "The next 30 days" in shown and "Client users here: 15" in shown,
          f"owner at {width}: Acme's directory of {rows} people, headcount by status, the "
          "next 30 days and client users (15, one block of 25)")
    check("31.50" not in shown and "home.example" not in shown,
          f"owner at {width}: the directory holds no sensitive field")
    page.get_by_label("Search people").fill("shipping")
    narrowed = body_rows(table)
    page.get_by_label("Search people").fill("")
    page.get_by_label("Employment type").select_option("contractor")
    contractors = body_rows(table)
    page.get_by_label("Employment type").select_option("")
    check(narrowed == 3 and contractors == 1,
          f"owner at {width}: search narrows to {narrowed} (shipping), the type filter to "
          f"{contractors} contractor")
    ok, why = fits(page)
    check(ok, f"owner at {width}: the People page fits the width{why}")
    page.get_by_role("tab", name="Org chart").click()
    chart = page.get_by_role("img", name="Org chart: 15 people, drawn from their managers "
                                         "(1 at the top).")
    chart.wait_for(timeout=30000)
    check(chart.is_visible(), f"owner at {width}: the org chart is drawn from managers "
                              "(15 people, Wiley at the top)")
    visit(page, f"{people}/{r['Sylvester']}")
    page.get_by_label("Pay", exact=True).wait_for(timeout=60000)
    shown = text_of(page)
    check("22.50 an hour" in shown and "home.example" in shown and "Masked" not in shown,
          f"owner at {width}: Sylvester's page shows pay and personal details in full")
    access = body_rows(page.get_by_role("table", name="Access list"))
    revoke = page.get_by_role("region", name="Offboarding: IT").inner_text()
    check(access == 5 and revoke.count("Revoke") == 5 and "This doesn't end anyone in payroll"
          in shown and page.get_by_role("button", name="Close the offboarding").is_disabled(),
          f"owner at {width}: his access list ({access}), a revoke task for each, the payroll "
          "note, and Close held until each is done or waived")
    ok, why = fits(page)
    check(ok, f"owner at {width}: a person's page fits the width{why}")
    visit(page, f"{people}/{r['Bugs']}")
    page.get_by_text("Onboarding, starting").wait_for(timeout=60000)
    shown = text_of(page)
    done = DONE["bugs"]
    check(f"{done} of 13 done" in shown,
          f"owner at {width}: Bugs's onboarding about half done ({done} of 13)")
    visit(page, f"{people}/{r['Lola']}")
    page.get_by_role("list", name="Their documents").wait_for(timeout=60000)
    shown = text_of(page)
    check("Offer of employment: Machinist" in shown and "Sent" in shown and "Offer out" in shown,
          f"owner at {width}: Lola is offer out, her offer letter sent for signature")
    plain = page.request.get(f"{BASE}/api/people/{acme}/export/")
    full = page.request.get(f"{BASE}/api/people/{acme}/export/?sensitive=1")
    check(plain.status == 200 and "Sylvester Pussycat" in plain.text()
          and "22.50" not in plain.text() and "22.50" in full.text(),
          f"owner at {width}: the spreadsheet holds no pay unless the HR Director asks for it")
    page.get_by_role("link", name="All people").click()
    page.get_by_role("tab", name="Access log").click()
    log = page.get_by_role("table", name="Access log entries")
    log.wait_for(timeout=60000)
    shown = log.inner_text()
    check("Sylvester Pussycat" in shown and "Exported" in shown and "Viewed" in shown,
          f"owner at {width}: the access log lists the views and the exports")
    context.close()

    # ------------------------------------------------ an HR Generalist
    context, page = ready(browser, setup, "generalist", width, keys)
    visit(page, f"{people}/{r['Sylvester']}")
    page.get_by_label("Pay", exact=True).wait_for(timeout=60000)
    shown = text_of(page)
    check("Masked" in shown and "22.50" not in shown and "•••••" in shown
          and page.get_by_role("button", name="Edit").count() == 0
          and page.get_by_role("button", name="Close the offboarding").count() == 1,
          f"generalist at {width}: Sylvester's sensitive fields masked, no Edit; runs his "
          "offboarding")
    sensitive = page.request.get(f"{BASE}/api/people/{acme}/export/?sensitive=1").status
    check(sensitive == 403, f"generalist at {width}: a sensitive export is refused ({sensitive})")
    context.close()

    # ------------------------------------------------ the client owner
    context, page = ready(browser, setup, "client owner", width, keys)
    visit(page, f"{people}/{r['Sylvester']}")
    page.get_by_label("Pay", exact=True).wait_for(timeout=60000)
    shown = text_of(page)
    check("22.50 an hour" in shown and "home.example" in shown and "Access list" in shown,
          f"client owner at {width}: everything for their company, pay and access list "
          "included")
    visit(page, people)
    page.get_by_role("table", name="Directory").wait_for(timeout=60000)
    check("Client users here" not in text_of(page),
          f"client owner at {width}: no client-user count (the practice's business)")
    context.close()

    # ------------------------------------------------ senior leadership
    context, page = ready(browser, setup, "senior leadership", width, keys)
    visit(page, people)
    page.get_by_role("table", name="Directory").wait_for(timeout=60000)
    headers = page.get_by_role("columnheader").all_inner_texts()
    visit(page, f"{people}/{r['Sylvester']}")
    page.get_by_label("Directory fields").wait_for(timeout=60000)
    shown = text_of(page)
    check("Status" not in headers and "Pay" not in shown and "Access list" not in shown,
          f"senior leadership at {width}: the directory of everyone, nothing more")
    context.close()

    # ------------------------------------------------ a manager
    context, page = ready(browser, setup, "manager", width, keys)
    visit(page, people)
    page.get_by_role("table", name="Directory").wait_for(timeout=60000)
    shown = text_of(page)
    mine = page.get_by_role("list", name="Your checklist items")
    check(f"Onboarding {DONE['bugs']} of 13" in shown and mine.count() == 1
          and "Bugs Bunny" in mine.inner_text(),
          f"manager at {width}: their reports, Bugs's onboarding progress, and their own items")
    if width == 1366:
        before = mine.get_by_role("listitem").count()
        mine.get_by_role("button").first.click()
        page.wait_for_function(
            "n => document.querySelectorAll('[aria-label=\"Your checklist items\"] li')"
            ".length < n", arg=before, timeout=30000)
        after = mine.get_by_role("listitem").count()
        check(after == before - 1, f"manager at {width}: marks one of their {before} items "
                                   f"done from the portal ({after} left)")
        DONE["bugs"] += 1
    blocked = api_status(page, f"/api/people/{acme}/records/{r['Sylvester']}/")
    check(blocked == 404, f"manager at {width}: someone not their report is 404 ({blocked})")
    context.close()

    # ------------------------------------------------ an employee
    context, page = ready(browser, setup, "employee", width, keys)
    visit(page, people)
    page.get_by_role("list", name="Documents to sign").wait_for(timeout=60000)
    rows = body_rows(page.get_by_role("table", name="Directory"))
    check(rows == 1 and "Employee handbook acknowledgment" in text_of(page),
          f"employee at {width}: their own record only, and the handbook to sign")
    visit(page, f"{people}/{r['Yosemite']}")
    page.get_by_label("Pay", exact=True).wait_for(timeout=60000)
    check("27.25 an hour" in text_of(page), f"employee at {width}: their own pay, in full")
    context.close()

    # ------------------------------------------------ no permission
    context, page = ready(browser, setup, "assistant", width, keys)
    visit(page, "/")
    page.wait_for_timeout(1500)
    menu = page.get_by_role("link", name="People").count()
    statuses = {api_status(page, "/api/people/"), api_status(page, f"/api/people/{acme}/"),
                api_status(page, f"/api/people/{acme}/setup/")}
    check(menu == 0 and statuses == {404},
          f"assistant (no permission) at {width}: no People in the menu; People's routes 404")
    context.close()


def hire(browser, setup, keys):
    """Lola signs her offer, signed out; her onboarding starts."""
    acme, lola = setup["acme"], setup["records"]["Lola"]
    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    page.goto(BASE + setup["lola_link"], wait_until="domcontentloaded")
    page.get_by_label("Type your signature").fill("Lola Bunny", timeout=60000)
    page.get_by_label("I agree to sign electronically").check()
    page.get_by_role("button", name="Sign").click()
    page.get_by_role("status").wait_for(timeout=60000)
    context.close()
    context, page = ready(browser, setup, "owner", 1366, keys)
    page.goto(f"{BASE}/people/{acme}/{lola}", wait_until="domcontentloaded")
    page.get_by_text("Onboarding, starting").wait_for(timeout=60000)
    shown = text_of(page)
    check("Onboarding" in shown and "0 of 13 done" in shown and "Signed" in shown,
          "Lola, signed out at 390, signs her offer from the link: her record moves to "
          "onboarding and its 13 items start")
    countersigned = page.request.post(
        f"{BASE}/api/documents/{setup['offer_document']}/countersign/",
        data={"agreed": True, "method": "typed", "typed": "Walk Owner"},
        headers={"X-CSRFToken": next((c["value"] for c in context.cookies()
                                      if c["name"] == "csrftoken"), "")})
    page.reload(wait_until="domcontentloaded")
    page.get_by_role("list", name="Their documents").wait_for(timeout=60000)
    check(countersigned.status == 200 and "Complete" in text_of(page),
          f"owner: countersigning works as it does today ({countersigned.status}); the offer "
          "is complete on her record")
    context.close()


def main():
    from playwright.sync_api import sync_playwright

    import subprocess

    print("Building the frontend…", file=sys.stderr)
    built = subprocess.run(["npm", "run", "build"], cwd=base.ROOT / "frontend",
                           capture_output=True, text=True)
    if built.returncode != 0:
        sys.exit("The frontend build failed:\n" + built.stdout[-2000:] + built.stderr[-2000:])
    subprocess.run(["dropdb", "--if-exists", base.DB], check=True)
    subprocess.run(["createdb", base.DB], check=True)
    print("Migrating and seeding the demo…", file=sys.stderr)
    base.manage("migrate", "--noinput")
    base.manage("collectstatic", "--noinput", "--clear")
    base.manage("seed_demo", "--database", base.DB, "--ff-email", "walk-owner@example.invalid",
                "--whole-database", env={"APP_ENVIRONMENT": "demo"})
    mail = start_mailpit()
    base.WALK.update({"EMAIL_HOST": "127.0.0.1", "EMAIL_PORT": str(MAIL_SMTP)})
    try:
        setup = base.last_json(base.manage("people_records_walk_setup"))
    except SystemExit:
        mail.terminate()
        raise
    keys: dict[str, str] = {}
    server = base.start_server()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            for width in (1366, 390):
                walk(browser, setup, width, keys)
            hire(browser, setup, keys)
            browser.close()
    finally:
        base.stop(server)
        mail.terminate()
    failed = [line for ok, line in base.RESULTS if not ok]
    print(f"\n{len(base.RESULTS) - len(failed)} of {len(base.RESULTS)} checks passed.")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
