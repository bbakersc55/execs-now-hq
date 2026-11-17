"""People's security foundation, walked in headless Chrome (2026-11-17).

    .venv/bin/python scripts/people_security_walk.py

The real `seed_demo` into a scratch database (`execsnowhq_walk`, never
`execsnowhq_local`), then `manage.py people_walk_setup` (People on,
placeholder people at Acme Fasteners, signed-in sessions for the practice
owner, an associate, a manager, an employee and an assistant), then this
tree's pages on 127.0.0.1:8197, at 1366 and at 390 wide. Codes are real: the
key is read off the Profile page as a person would type it into an app, and
each code is worked out from it (RFC 6238), a new 30-second step each time.
At the end the server is started as the demo, where nobody is asked for a
code. One line per check; it exits 1 if any fails.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from apps.accounts import totp  # noqa: E402  (pure: no Django)

PORT = 8197
BASE = f"http://127.0.0.1:{PORT}"
DB = "execsnowhq_walk"
WALK = {"DATABASE_URL": f"postgres:///{DB}", "STORAGE_BACKEND": "local",
        "GCS_BUCKET_MEDIA": "execsnowhq-walk", "APP_ROOT_URL": "/",
        "NMI_LIVE_CALLS": "false", "APP_ENVIRONMENT": "local"}
RESULTS: list[tuple[bool, str]] = []
LAST_STEP: dict[str, int] = {}


def manage(*args, env=None) -> str:
    done = subprocess.run([str(ROOT / ".venv/bin/python"), "manage.py", *args], cwd=ROOT,
                          env={**os.environ, **WALK, **(env or {})}, capture_output=True,
                          text=True)
    if done.returncode != 0:
        sys.exit(f"manage.py {args[0]} failed:\n{done.stderr[-3000:]}")
    return done.stdout


def last_json(text: str) -> dict:
    return json.loads(text.strip().splitlines()[-1])


def check(ok: bool, line: str) -> bool:
    RESULTS.append((bool(ok), line))
    print(("PASS  " if ok else "FAIL  ") + line, flush=True)
    return bool(ok)


def code_for(secret: str) -> str:
    """A code from the app, in a step this person has not used yet."""
    step = totp.step_of()
    while LAST_STEP.get(secret, -1) >= step:
        time.sleep(1)
        step = totp.step_of()
    LAST_STEP[secret] = step
    return totp.code_at(secret, step)


def start_server(extra=None):
    env = {**os.environ, **WALK, "PYTHONUNBUFFERED": "1", **(extra or {})}
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


def stop(server):
    server.terminate()
    server.wait(timeout=10)


def page_for(browser, cookie, session, width):
    context = browser.new_context(viewport={"width": width, "height": 900 if width > 500
                                            else 844})
    context.add_cookies([{"name": cookie, "value": session, "url": BASE}])
    return context, context.new_page()


def api_status(page, path) -> int:
    return page.request.get(BASE + path).status


def wide_enough(page) -> bool:
    return page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1")


def enroll(page, who) -> str:
    """Profile → Set up → read the key → a code → on; returns the key."""
    page.goto(f"{BASE}/profile", wait_until="domcontentloaded")
    page.get_by_role("button", name="Set up two-factor sign-in").click(timeout=60000)
    page.get_by_label("QR code").wait_for(timeout=30000)
    key = page.get_by_label("Key to type").inner_text().replace(" ", "")
    page.get_by_label("Code from your authenticator app").fill(code_for(key))
    page.get_by_role("button", name="Turn it on").click()
    shown = page.get_by_label("Your backup codes")
    shown.wait_for(timeout=30000)
    count = shown.get_by_role("listitem").count()
    check(count == 10, f"{who}: enrolled on Profile with the QR code's key and a real code; "
                       f"{count} backup codes shown once")
    page.get_by_role("button", name="I have saved them").click()
    return key


def prompt_then_in(page, who, key, width):
    page.goto(f"{BASE}/", wait_until="domcontentloaded")
    prompt = page.get_by_role("heading", name="Two-factor sign-in")
    prompt.wait_for(timeout=60000)
    blocked = api_status(page, "/api/contacts/")
    page.get_by_label("Code from your authenticator app").fill(code_for(key))
    page.get_by_role("button", name="Continue").click()
    page.get_by_role("heading", name="Two-factor sign-in").wait_for(state="detached",
                                                                    timeout=60000)
    check(blocked == 403 and api_status(page, "/api/contacts/") == 200,
          f"{who} at {width}: a new sign-in shows the code prompt and nothing else answers "
          f"({blocked}) until a real code is entered (then 200)")


def walk(browser, setup, width, keys):
    from playwright.sync_api import Error as PlaywrightError  # noqa: F401

    cookie, acme = setup["cookie"], setup["acme"]
    people = setup["people"]
    fresh = {w: last_json(manage("people_walk_setup", "--session", people[w]["email"]))["session"]
             for w in people} if width != 1366 else {w: people[w]["session"] for w in people}

    # The assistant: no permission, no People at all.
    ctx, page = page_for(browser, cookie, fresh["assistant"], width)
    page.goto(f"{BASE}/dashboard", wait_until="domcontentloaded")
    page.locator("main").wait_for(timeout=60000)
    page.wait_for_timeout(1500)
    in_menu = page.locator("a[href='/people']").count()
    check(in_menu == 0 and api_status(page, "/api/people/") == 404
          and api_status(page, f"/api/people/{acme}/") == 404,
          f"assistant (no permission) at {width}: no People in the menu; /api/people/ and "
          "Acme's are 404")
    ctx.close()

    # The practice owner: two-factor, then People as HR Director.
    ctx, page = page_for(browser, cookie, fresh["owner"], width)
    if "owner" not in keys:
        page.goto(f"{BASE}/people", wait_until="domcontentloaded")
        page.get_by_role("link", name="Go to Profile").wait_for(timeout=60000)
        check(True, f"owner at {width}: People asks for two-factor first (HR Director by "
                    "being the practice owner)")
        keys["owner"] = enroll(page, "owner")
    else:
        prompt_then_in(page, "owner", keys["owner"], width)
    page.goto(f"{BASE}/people/{acme}", wait_until="domcontentloaded")
    page.get_by_text("Your access: HR Director").wait_for(timeout=60000)
    text = page.locator("main").inner_text()
    check("$41.25 an hour" in text and "HR guidance, not legal advice." in text,
          f"owner at {width}: Acme's People page as HR Director shows pay rates, and says "
          "\"HR guidance, not legal advice\"")
    check(wide_enough(page), f"owner at {width}: the People page fits the width (no sideways "
                             "scroll)")
    if width == 1366:
        page.get_by_role("tab", name="Permissions").click()
        form = page.get_by_role("form", name="Give an HR permission")
        form.get_by_label("Who").select_option(label=people["generalist"]["name"])
        form.get_by_label("Level").select_option("generalist")
        form.get_by_role("button", name="Give it").click()
        page.get_by_text("Two-factor not set up yet").wait_for(timeout=30000)
        check(True, f"owner at {width}: gave {people['generalist']['name']} HR Generalist for "
                    "Acme on the Permissions tab")
    ctx.close()

    # The Generalist: must enroll first; masked; asked again after four hours.
    ctx, page = page_for(browser, cookie, fresh["generalist"], width)
    if "generalist" not in keys:
        page.goto(f"{BASE}/people/{acme}", wait_until="domcontentloaded")
        page.get_by_role("link", name="Go to Profile").wait_for(timeout=60000)
        check(True, f"generalist at {width}: People refused until two-factor is set up "
                    "(required for an HR permission)")
        keys["generalist"] = enroll(page, "generalist")
    else:
        prompt_then_in(page, "generalist", keys["generalist"], width)
    page.goto(f"{BASE}/people/{acme}", wait_until="domcontentloaded")
    page.get_by_text("Your access: HR Generalist").wait_for(timeout=60000)
    text = page.locator("main").inner_text()
    check("Masked" in text and "$41.25" not in text and "Tucson" not in text,
          f"generalist at {width}: Acme's people with sensitive fields masked (no pay, no "
          "address)")
    session = ctx.cookies()[0]["value"]
    manage("people_walk_setup", "--age-code", session)
    page.goto(f"{BASE}/people/{acme}", wait_until="domcontentloaded")
    page.get_by_text("Enter your code again").wait_for(timeout=60000)
    page.get_by_label("Code from your authenticator app").fill(code_for(keys["generalist"]))
    page.get_by_role("button", name="Continue").click()
    page.get_by_text("Your access: HR Generalist").wait_for(timeout=60000)
    check(True, f"generalist at {width}: with the last code over four hours old, People asks "
                "for it again; a real code opens the page")
    ctx.close()

    # The manager: their reports' directory and their own record.
    ctx, page = page_for(browser, cookie, fresh["manager"], width)
    page.goto(f"{BASE}/people/{acme}", wait_until="domcontentloaded")
    page.get_by_text("Your access: Manager (direct reports)").wait_for(timeout=60000)
    text = page.locator("main").inner_text()
    check("Marvin Martian" in text and "Elmer Fudd" in text and "Yosemite Sam" in text
          and "Foghorn" not in text and "$41.25 an hour" in text and "$32.50" not in text,
          f"manager at {width}: their own record in full, their reports' directory only, "
          "nobody else")
    ctx.close()

    # The employee: their own record.
    ctx, page = page_for(browser, cookie, fresh["employee"], width)
    page.goto(f"{BASE}/people/{acme}", wait_until="domcontentloaded")
    page.get_by_text("Your access: Your own record").wait_for(timeout=60000)
    text = page.locator("main").inner_text()
    rows = page.locator("main tbody tr").count()
    # Their own record names their manager (Marvin): that is theirs to see.
    check(rows == 1 and "Elmer Fudd" in text and "$32.50 an hour" in text
          and "$41.25" not in text and "Yosemite" not in text and "Foghorn" not in text,
          f"employee at {width}: their own record only ({rows} row, with their own pay)")
    ctx.close()

    # The access log, read by the owner.
    if width == 1366:
        ctx, page = page_for(browser, cookie, last_json(manage(
            "people_walk_setup", "--session", people["owner"]["email"]))["session"], width)
        prompt_then_in(page, "owner", keys["owner"], width)
        page.goto(f"{BASE}/people/{acme}", wait_until="domcontentloaded")
        page.get_by_role("tab", name="Access log").click(timeout=60000)
        log = page.get_by_role("table", name="Access log entries")
        log.wait_for(timeout=30000)
        text = log.inner_text()
        check("Viewed" in text and "Marvin Martian" in text and "Pay rate" in text
              and "127.0.0.1" in text,
              f"owner at {width}: the access log lists each view of sensitive fields: who, "
              "whose, which fields, from where")
        ctx.close()

    # The twelve hours: the warning, and the sign-out.
    nearly = setup["assistant_nearly_12h"] if width == 1366 else last_json(manage(
        "people_walk_setup", "--session", people["assistant"]["email"]))["session"]
    if width == 1366:
        ctx, page = page_for(browser, cookie, nearly, width)
        page.goto(f"{BASE}/dashboard", wait_until="domcontentloaded")
        page.get_by_role("status", name="Signing out soon").wait_for(timeout=60000)
        check(True, f"assistant at {width}: five minutes before the 12 hours, the warning "
                    "says when and to save")
        ctx.close()
        ctx, page = page_for(browser, cookie, setup["assistant_past_12h"], width)
        page.goto(f"{BASE}/dashboard", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        check(api_status(page, "/api/me") == 401,
              f"assistant at {width}: 12 hours after signing in, signed out (401)")
        ctx.close()


def demo_check(browser, setup, keys):
    """The server as the demo: nobody is asked for a code."""
    session = last_json(manage("people_walk_setup", "--session",
                               setup["people"]["owner"]["email"]))["session"]
    server = start_server({"APP_ENVIRONMENT": "demo"})
    try:
        ctx, page = page_for(browser, setup["cookie"], session, 1366)
        me = page.request.get(f"{BASE}/api/me").json()
        people = api_status(page, f"/api/people/{setup['acme']}/")
        check(me.get("two_factor_pending") is False and people == 200,
              "demo: an owner with two-factor on signs in with no code asked for, and People "
              "opens without one (never locked out)")
        ctx.close()
    finally:
        stop(server)


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
    setup = last_json(manage("people_walk_setup"))
    keys: dict[str, str] = {}
    server = start_server()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            for width in (1366, 390):
                walk(browser, setup, width, keys)
            stop(server)
            server = None
            demo_check(browser, setup, keys)
            browser.close()
    finally:
        if server is not None:
            stop(server)
    failed = [line for ok, line in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)} of {len(RESULTS)} checks passed.")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
