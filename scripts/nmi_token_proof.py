"""The token path, end to end, in headless Chrome against NMI's sandbox (P4).

    .venv/bin/python scripts/nmi_token_proof.py

It starts its own server on 127.0.0.1:8199 with NMI_LIVE_CALLS=true for this
run only, opens `/dev/nmi-proof` (laptop and sandbox only), types NMI's
published test card into **NMI's own card fields** twice, and prints what the
server did with the two tokens: a sale, a partial refund, the sale read back
by our reference, a card stored in the vault, a sale on it, its refund, and
the record deleted. Transaction ids are printed; keys never are.

The card number goes only into NMI's frames, as a person's would. This app's
server never sees it: that is what this proves. Needs Google Chrome and the
`playwright` package (requirements-dev.txt); it uses the installed Chrome and
downloads no browser.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8199
BASE = f"http://127.0.0.1:{PORT}"

#: NMI's published sandbox test card (docs.nmi.com, "Test and deploy").
TEST_CARD = ("4111111111111111", "10/29", "999")


def start_server():
    env = {**os.environ, "NMI_LIVE_CALLS": "true", "PYTHONUNBUFFERED": "1"}
    server = subprocess.Popen(
        [str(ROOT / ".venv/bin/python"), "manage.py", "runserver", f"127.0.0.1:{PORT}",
         "--noreload"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    for _ in range(60):
        try:
            urllib.request.urlopen(f"{BASE}/healthz", timeout=2)
            return server
        except Exception:
            if server.poll() is not None:
                sys.exit("The server did not start: " + server.stderr.read().decode()[-2000:])
            time.sleep(0.5)
    server.terminate()
    sys.exit("The server did not answer on /healthz.")


def fill_card(page):
    """Type the test card into NMI's frames, waiting for them to settle: the
    component re-renders its frames a few times while it loads."""
    frames = "iframe[src*='inline.php']"
    for selector, value in zip(("#ccnumber", "#ccexp", "#cvv"), TEST_CARD):
        for _ in range(120):
            done = False
            for k in range(page.locator(frames).count()):
                field = page.frame_locator(frames).nth(k).locator(selector)
                try:
                    if field.count() and field.is_visible():
                        field.fill(value, timeout=5000)
                        done = True
                        break
                except Exception:
                    pass
            if done:
                break
            page.wait_for_timeout(500)
        else:
            raise RuntimeError(f"NMI's {selector} field never appeared.")
    page.wait_for_timeout(1000)
    page.get_by_role("button", name="Pay").click(timeout=60000)


def attempt(browser) -> dict:
    page = browser.new_page()
    try:
        response = page.goto(f"{BASE}/dev/nmi-proof", wait_until="domcontentloaded",
                             timeout=90000)
        if response is None or response.status != 200:
            sys.exit("The proof page is not here: it needs APP_ENVIRONMENT local and "
                     "NMI_ENVIRONMENT sandbox.")
        fill_card(page)
        page.get_by_text("Card 2 of 2").wait_for(timeout=60000)
        page.wait_for_timeout(3000)
        fill_card(page)
        page.locator("#result").filter(has_text="steps").wait_for(timeout=120000)
        return json.loads(page.locator("#result").inner_text())
    finally:
        page.close()


def run() -> dict:
    """NMI's frames sometimes load slowly; a page that never shows them is
    tried again from the start with fresh tokens, up to three times."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        for tries in range(1, 4):
            try:
                return attempt(browser)
            except Exception as exc:
                if tries == 3:
                    raise
                print(f"Try {tries}: {type(exc).__name__}: {str(exc).splitlines()[0]}",
                      file=sys.stderr)
        browser.close()
    return {}


def main():
    server = start_server()
    try:
        result = run()
    finally:
        server.terminate()
        server.wait(timeout=10)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
