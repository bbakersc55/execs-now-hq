"""The token path, end to end, in headless Chrome against NMI's sandbox (P4).

    .venv/bin/python scripts/nmi_token_proof.py            # the gateway (part 1)
    .venv/bin/python scripts/nmi_token_proof.py --portal   # the portal's Pay (part 2)
    .venv/bin/python scripts/nmi_token_proof.py --link     # the pay link (part 3)

**--portal** pays a real invoice through the real portal page, as a client
would: it builds the frontend, makes a fresh database `execsnowhq_nmi_proof`
(never `execsnowhq_local`), sets up a practice connected with the sandbox keys
and a sent invoice (`manage.py nmi_proof_setup`), signs in as the client
owner with a magic link, presses Pay, types NMI's test card into NMI's
fields, and prints the attempt, the payment and the receipt as the database
holds them. The database is left for a look and remade by the next run.

**--link** does the same through the signed pay link, signed in as no one:
the invoice is to a contact alone (in no portal), the page is opened at its
`/pay/<token>`, paid with the test card, then opened again to show Paid; a
wrong token is checked to be a 404.

Without --portal:

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
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8199
BASE = f"http://127.0.0.1:{PORT}"

#: NMI's published sandbox test card (docs.nmi.com, "Test and deploy").
TEST_CARD = ("4111111111111111", "10/29", "999")
PROOF_DB = "execsnowhq_nmi_proof"
PROOF_ENV = {"DATABASE_URL": f"postgres:///{PROOF_DB}", "APP_ROOT_URL": "/"}


def manage(*args, env_extra=None) -> str:
    env = {**os.environ, "NMI_LIVE_CALLS": "true", **(env_extra or {})}
    done = subprocess.run([str(ROOT / ".venv/bin/python"), "manage.py", *args], cwd=ROOT,
                          env=env, capture_output=True, text=True)
    if done.returncode != 0:
        sys.exit(f"manage.py {args[0]} failed:\n{done.stderr[-3000:]}")
    return done.stdout


def start_server(env_extra=None):
    env = {**os.environ, "NMI_LIVE_CALLS": "true", "PYTHONUNBUFFERED": "1",
           **(env_extra or {})}
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


def fill_card(page, button=re.compile(r"^Pay$")):
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
    page.get_by_role("button", name=button).click(timeout=60000)


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


def link_attempt(browser, setup) -> None:
    page = browser.new_page()
    try:
        page.goto(BASE + setup["pay_path"], wait_until="domcontentloaded", timeout=90000)
        page.get_by_role("heading", name=f"Invoice {setup['number']}").wait_for(timeout=90000)
        page.get_by_text("Test mode").first.wait_for(timeout=60000)
        fill_card(page, button=re.compile(r"^Pay \$"))
        page.get_by_role("status").filter(has_text="was paid on invoice").wait_for(
            timeout=120000)
    finally:
        page.close()


def link_after(browser, setup) -> dict:
    """The page opened again once paid, and a wrong token."""
    page = browser.new_page()
    try:
        page.goto(BASE + setup["pay_path"], wait_until="domcontentloaded", timeout=90000)
        page.get_by_role("heading", name=f"Invoice {setup['number']}").wait_for(timeout=90000)
        paid = page.get_by_text("Paid", exact=True).count() > 0
        form = page.get_by_text("Pay by card").count() > 0
    finally:
        page.close()
    wrong = setup["pay_path"][:-2] + ("xy" if not setup["pay_path"].endswith("xy") else "zz")
    try:
        status = urllib.request.urlopen(BASE + "/api" + wrong, timeout=30).status
    except urllib.error.HTTPError as exc:
        status = exc.code
    return {"shows_paid": paid, "card_form_shown": form, "wrong_token_status": status}


def portal_attempt(browser, setup) -> None:
    page = browser.new_page()
    try:
        page.goto(BASE + setup["sign_in_path"], wait_until="domcontentloaded", timeout=90000)
        page.get_by_role("button", name="Sign in").click()
        pay = page.get_by_role("button", name=f"Pay invoice {setup['number']}")
        pay.wait_for(timeout=90000)
        pay.click()
        page.get_by_text("Test mode").first.wait_for(timeout=60000)
        fill_card(page, button=re.compile(r"^Pay \$"))
        page.get_by_role("status").filter(has_text="was paid on invoice").wait_for(
            timeout=120000)
    finally:
        page.close()


READ_BACK = """
import json
from apps.billing.models import PaymentAttempt, ClientPayment
from apps.crm.models import OutboxMessage
a = PaymentAttempt.all_objects.select_related("invoice").get()
from apps.billing.models import ClientInvoice
row = ClientInvoice.all_objects.filter(pk=a.invoice_id).values("pay_url", "pay_token_hash").get()
p = ClientPayment.all_objects.filter(invoice=a.invoice).first()
mail = list(OutboxMessage.all_objects.filter(producer__in=["payment_receipt",
    "payment_notice"]).values_list("producer", "to_address", "state"))
print(json.dumps({"attempt": {"status": a.status, "nmi_transaction_id": a.nmi_transaction_id,
    "amount_cents": a.amount_cents, "card": f"{a.card_type} {a.last4}",
    "response_code": a.response_code, "environment": a.environment},
    "payment": p and {"method": p.method, "amount_cents": p.amount_cents,
                      "nmi_transaction_id": p.nmi_transaction_id, "reference": p.reference},
    "invoice": {"number": a.invoice.number, "kind": a.invoice.kind,
                "status": a.invoice.status, "balance_cents": a.invoice.balance_cents,
                "pay_url_column_empty": row["pay_url"] == "",
                "pay_token_hash_stored": bool(row["pay_token_hash"])},
    "via": a.via,
    "mail": mail,
    # The unknown-answer lookup's own code, against the sandbox: the sale found
    # by our reference alone, as `resolve_unknown` would find it.
    "lookup": (lambda t: t and {"nmi_transaction_id": t.id, "approved": t.approved,
                                "amount_cents": t.amount_cents})(
        __import__("apps.billing.gateway", fromlist=["gateway"]).gateway().find_by_reference(
            __import__("apps.billing.payment_accounts", fromlist=["x"]).practice_account(
                a.invoice.tenant), str(a.pk)))}))
"""


def portal(by_link=False) -> dict:
    from playwright.sync_api import sync_playwright

    print("Building the frontend…", file=sys.stderr)
    built = subprocess.run(["npm", "run", "build"], cwd=ROOT / "frontend",
                           capture_output=True, text=True)
    if built.returncode != 0:
        sys.exit("The frontend build failed:\n" + built.stdout[-3000:] + built.stderr[-3000:])
    subprocess.run(["dropdb", "--if-exists", PROOF_DB], check=True)
    subprocess.run(["createdb", PROOF_DB], check=True)
    print("Migrating the proof database…", file=sys.stderr)
    manage("migrate", "--noinput", env_extra=PROOF_ENV)
    setup = json.loads(manage("nmi_proof_setup", *(["--contact"] if by_link else []),
                              env_extra=PROOF_ENV).strip().splitlines()[-1])
    after = {}
    server = start_server(PROOF_ENV)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            for tries in range(1, 4):
                try:
                    (link_attempt if by_link else portal_attempt)(browser, setup)
                    break
                except Exception as exc:
                    # A try that never reached Pay spent no token and charged
                    # nothing; one that did is in the read-back below.
                    if tries == 3 or manage("shell", "-c", "from apps.billing.models import "
                                            "PaymentAttempt as P; print(P.all_objects.count())",
                                            env_extra=PROOF_ENV).strip() != "0":
                        raise
                    print(f"Try {tries}: {type(exc).__name__}", file=sys.stderr)
            if by_link:
                after = link_after(browser, setup)
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)
    result = json.loads(manage("shell", "-c", READ_BACK, env_extra=PROOF_ENV).strip().splitlines()[-1])
    result["ok"] = (result["attempt"]["status"] == "approved" and result["payment"] is not None
                    and result["invoice"]["status"] == "paid" and result["lookup"] is not None
                    and result["lookup"]["nmi_transaction_id"]
                    == result["attempt"]["nmi_transaction_id"])
    if by_link:
        result["after"] = after
        result["ok"] = (result["ok"] and result["via"] == "link"
                        and result["invoice"]["kind"] == "contact"
                        and result["invoice"]["pay_url_column_empty"]
                        and after.get("shows_paid") and not after.get("card_form_shown")
                        and after.get("wrong_token_status") == 404)
    return result


def main():
    if "--portal" in sys.argv or "--link" in sys.argv:
        result = portal(by_link="--link" in sys.argv)
    else:
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
