"""The token path, end to end, in headless Chrome against NMI's sandbox (P4).

    .venv/bin/python scripts/nmi_token_proof.py            # the gateway (part 1)
    .venv/bin/python scripts/nmi_token_proof.py --portal   # the portal's Pay (part 2)
    .venv/bin/python scripts/nmi_token_proof.py --link     # the pay link (part 3)
    .venv/bin/python scripts/nmi_token_proof.py --autopay  # card on file, auto-pay (part 4)
    .venv/bin/python scripts/nmi_token_proof.py --subscription  # practice subscription (part 5)
    .venv/bin/python scripts/nmi_token_proof.py --collect secure.nmi.com         # Collect.js
    .venv/bin/python scripts/nmi_token_proof.py --collect secure.vaultixpay.com  # its host
    .venv/bin/python scripts/nmi_token_proof.py --link-collect secure.nmi.com         # the real
    .venv/bin/python scripts/nmi_token_proof.py --link-collect secure.vaultixpay.com  # pay page
    .venv/bin/python scripts/nmi_token_proof.py --bank-fees   # bank payments, card category, surcharge
    .venv/bin/python scripts/nmi_token_proof.py --refunds     # void and refund from the app
    .venv/bin/python scripts/nmi_token_proof.py --test-mode   # the processor's own Test Mode
    .venv/bin/python scripts/nmi_token_proof.py --automatic   # recurring, billed automatically
    .venv/bin/python scripts/nmi_token_proof.py --run-now     # "Run the next billing now"
    .venv/bin/python scripts/nmi_token_proof.py --beside      # auto-pay beside automatic billing

**--automatic** (2026-11-17) walks automatic billing through the real pages
built from this tree, with the worker's two daily jobs run with the clock
moved (`nmi_proof_setup --billing-run DAY`): the practice owner sets up a
recurring invoice that bills automatically on the 1st and the 15th and emails
the client owner the link; the client owner, signed in, saves NMI's test card
in the portal and agrees; three days before the first date the invoice is made
and emailed by itself, and on the date the card is charged (a real sandbox
sale on the vault record); the owner changes the price; the client presses
Stop automatic billing, reads the dates and confirms; every billing date
through the end is billed (the last at the new price), nothing after, and the
day after the end it is Ended. Like --refunds it reads the sandbox as live.

**--refunds** (2026-11-16) is the pay link with money given back, through the
real pages built from this tree: the payer pays; the practice owner, signed in,
presses "Refund or cancel this payment" for the whole amount and the sale is
voided (it has not settled); the payer pays again (with NMI's Mastercard test
card, since the same card for the same amount within minutes is a duplicate);
the owner refunds $2.00 and then the rest, voiding the invoice; the morning
read-back runs and flags none of them. Then a second invoice is paid and $1.00
of it refunded straight at NMI (the merchant portal's stand-in): the read-back
flags it and the owner presses "Record this refund". The sandbox always says
it is in Test Mode, so this run reads it as live (`NMI_SANDBOX_IGNORE_TEST_MODE`,
laptop only) to take the books path; the facts printed come from the database.

**--test-mode** (2026-11-16) takes the sandbox's own answer, Test Mode on: the
owner sees the banner on Billing and Invoices; a payment and a part refund are
tests and stay out of the books; the client saves a card, a test card. Then
the server restarts reading the sandbox as live ("back in live mode"), the
owner presses Test connection, sees "1 test payment" and presses "Clear test
payments": the payment comes off, the invoice reopens, the card is deleted
from the sandbox's vault.

**--bank-fees** (2026-11-14) proves, on the sandbox only and with no app code,
what bank payments and a card fee would stand on. It serves its own page on
127.0.0.1:8198 with Collect.js from secure.nmi.com and the sandbox's public
key, and makes its own v5 and Query API calls with the sandbox's private key
(it refuses to run on anything but sandbox.nmi.com):
- NMI's published test bank account typed into Collect.js's check frames,
  the token and what Collect.js says about it;
- a bank sale on a token with no SEC code, then WEB and CCD (each place a SEC
  code might go is tried; a refused one charges nothing), read back through
  the Query API;
- a bank account stored in the Customer Vault, a sale on it, the record
  deleted;
- the sandbox's amount trigger on a bank sale, which action names the Query
  API knows for a return, every bank transaction the account has, and how a
  date-window query reports an action made today on a sale older than seven
  days (a $0.01 refund on an old sandbox card sale: the sandbox makes no
  returns, so this is the nearest action it can make);
- the credit/debit category for test cards, from `lookUpCallback` and from
  the token response, with and without `price`/`currency`/`country` (the
  settings that also stop Collect.js's Apple Pay console error);
- a card sale with a surcharge at the top of the body and in
  `order_details`, each read back from v5 and the Query API, then refunded.

**--link-collect HOST** (2026-11-13) is --link with the card form a live
white-label account gets: the real pay page, built from this tree, loads
Collect.js from HOST with the page's own configuration
(`NMI_SANDBOX_CARD_FORM_HOST`, laptop only). On secure.nmi.com the sandbox
key works there, so it goes all the way. First the boxes' own checks
(2026-11-14): nothing said in a box not yet left; the number left empty; Pay
with every box empty; a wrong number left; each said beside its box in plain
words, with no banner and none of Collect.js's own text, and Pay free again
at once. Then NMI's test card typed into Collect.js's frames, a real token, a
real sandbox sale, the Paid page, the receipt and the payment on the invoice. On secure.vaultixpay.com the sandbox
key is unknown, so it shows how far the page gets: Collect.js loaded, the
configuration accepted (no "too many fields"), what the host's token API
answered, and that the page then tells the payer and the practice owner. It
never types a card there. Every console message and page error is printed.

**--form-host HOST** with --portal, --autopay or --subscription runs that
proof with Collect.js from HOST in place of the Payment Component; the
result says which form each card was typed into.

**--collect HOST** (2026-11-10) is the gateway proof with Collect.js loaded
from HOST (one of `gateway.API_HOSTS`) instead of NMI's Payment Component:
the same two tokens, the same sale, refunds and vault on the sandbox's v5.
A sandbox key is refused by the white-label host's token API (404: the
sandbox's merchants are not on it), so that run stops at the first token
and says so; it completes only with that host's own keys.

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

**--autopay** signs in as the client owner, saves the test card from the
Invoices page into the practice's sandbox vault and turns auto-pay on; then
a new invoice is sent through the practice's approval, made due today, and
the auto-pay job is run twice; the sale on the vault record is read back and
looked up by our reference, the invoice sent before consent is shown not
charged, and the vault record is deleted at the end.

**--subscription** signs in as the practice owner (a session made in the
proof database), saves the test card under Settings → Billing, "Your
subscription", into the **platform's** sandbox vault (the NMI_* keys), then
runs the subscription job the day before the card's first 1st (nothing) and
on that 1st, twice; the sale, the invoice and its PDF, the receipt with the
PDF attached, and the lookup by the invoice's reference are read back, and
the vault record is deleted at the end.

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


def _manage_py(clock=None) -> list[str]:
    """manage.py, or (2026-11-17) manage.py with the app's clock moved to
    `clock` (`scripts/moved_clock.py`)."""
    python = str(ROOT / ".venv/bin/python")
    if clock is None:
        return [python, "manage.py"]
    return [python, str(ROOT / "scripts/moved_clock.py"), clock.isoformat()]


def manage(*args, env_extra=None, clock=None) -> str:
    env = {**os.environ, "NMI_LIVE_CALLS": "true", **(env_extra or {})}
    done = subprocess.run([*_manage_py(clock), *args], cwd=ROOT,
                          env=env, capture_output=True, text=True)
    if done.returncode != 0:
        sys.exit(f"manage.py {args[0]} failed:\n{done.stderr[-3000:]}")
    return done.stdout


def start_server(env_extra=None, clock=None):
    env = {**os.environ, "NMI_LIVE_CALLS": "true", "PYTHONUNBUFFERED": "1",
           **(env_extra or {})}
    server = subprocess.Popen(
        [*_manage_py(clock), "runserver", f"127.0.0.1:{PORT}",
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


#: Which card form each card was typed into (2026-11-13): True for Collect.js.
FORMS_SEEN: list[bool] = []


def build_frontend() -> None:
    """This tree's frontend, built and collected into STATIC_ROOT as
    production's build does: the server reads index.html from STATIC_ROOT
    first, so a build left there earlier would otherwise be served."""
    print("Building the frontend…", file=sys.stderr)
    built = subprocess.run(["npm", "run", "build"], cwd=ROOT / "frontend",
                           capture_output=True, text=True)
    if built.returncode != 0:
        sys.exit("The frontend build failed:\n" + built.stdout[-3000:] + built.stderr[-3000:])
    manage("collectstatic", "--noinput", "--clear")


def fill_card(page, button=re.compile(r"^Pay$"), card=None):
    """Type the test card into NMI's frames, waiting for them to settle: the
    component re-renders its frames a few times while it loads."""
    frames = "iframe[src*='inline.php']"
    for selector, value in zip(("#ccnumber", "#ccexp", "#cvv"), card or TEST_CARD):
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
    FORMS_SEEN.append(page.evaluate(
        "() => !!document.querySelector('script[src$=\"/token/Collect.js\"]')"))
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


def collect_attempt(browser, host) -> dict:
    """The proof page with Collect.js from `host`: the test card typed into
    the host's frames twice; the page runs the sandbox path on the tokens."""
    page = browser.new_page()
    token_api = []
    page.on("response", lambda r: token_api.append(r.status)
            if r.url.split("?")[0].endswith("/token/api/create") else None)
    try:
        page.goto(f"{BASE}/dev/nmi-proof?form=collect&host={host}",
                  wait_until="domcontentloaded", timeout=90000)
        try:
            fill_card(page)
        except RuntimeError:
            return {"ok": False, "host": host, "stopped": "the card fields never appeared",
                    "token_api_statuses": sorted(set(token_api))}
        page.get_by_text("Card 2 of 2").wait_for(timeout=60000)
        page.wait_for_timeout(2000)
        fill_card(page)
        page.locator("#result").filter(has_text="steps").wait_for(timeout=120000)
        text = page.locator("#result").inner_text()
        try:
            result = json.loads(text)
        except ValueError:
            result = {"ok": False, "answer": text[:1500]}
        result["host"] = host
        result["token_api_statuses"] = sorted(set(token_api))
        return result
    finally:
        page.close()


def run_collect(host) -> dict:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        try:
            return collect_attempt(browser, host)
        finally:
            browser.close()


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


def link_attempt(browser, setup, card=None) -> None:
    page = browser.new_page()
    try:
        page.goto(BASE + setup["pay_path"], wait_until="domcontentloaded", timeout=90000)
        page.get_by_role("heading", name=f"Invoice {setup['number']}").wait_for(timeout=90000)
        page.get_by_text("Test mode").first.wait_for(timeout=60000)
        fill_card(page, button=re.compile(r"^Pay \$"), card=card)
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


def autopay_attempt(browser, setup) -> None:
    page = browser.new_page()
    try:
        page.goto(BASE + setup["sign_in_path"], wait_until="domcontentloaded", timeout=90000)
        page.get_by_role("button", name="Sign in").click()
        page.get_by_role("button", name="Save a card").click(timeout=90000)
        fill_card(page, button=re.compile(r"^Save this card$"))
        page.get_by_text(re.compile(r"ending 1111")).first.wait_for(timeout=120000)
        page.get_by_label("I agree").check(timeout=30000)
        page.get_by_role("button", name="Turn auto-pay on").click()
        page.get_by_text("Auto-pay on", exact=True).wait_for(timeout=60000)
    finally:
        page.close()


AUTOPAY_READ_BACK = """
import json
from apps.billing import gateway as gw, payment_accounts
from apps.billing.models import (AutopayConsent, ClientInvoice, ClientPayment,
    ClientPaymentMethod, PaymentAttempt)
from apps.crm.models import OutboxMessage
card = ClientPaymentMethod.all_objects.get(removed_at__isnull=True)
consent = AutopayConsent.all_objects.select_related("consented_by").get()
a = PaymentAttempt.all_objects.select_related("invoice").get(via="autopay")
p = ClientPayment.all_objects.filter(invoice=a.invoice).first()
before = ClientInvoice.all_objects.exclude(pk=a.invoice_id).get()
account = payment_accounts.practice_account(a.invoice.tenant)
found = gw.gateway().find_by_reference(account, str(a.pk))
gw.gateway().vault_delete(account, card.vault_id)
print(json.dumps({
    "card": {"brand": card.brand, "last4": card.last4,
             "expires": f"{card.exp_month:02d}/{card.exp_year}", "vault_id_kept": bool(card.vault_id),
             "environment": card.environment, "added_by": card.added_by.email},
    "consent": {"by": consent.consented_by.email, "version": consent.wording_version,
                "address_kept": bool(consent.ip_address),
                "browser_kept": "Chrome" in consent.user_agent,
                "wording_starts": consent.wording[:60]},
    "attempt": {"status": a.status, "via": a.via, "nmi_transaction_id": a.nmi_transaction_id,
                "amount_cents": a.amount_cents, "card": f"{a.card_type} {a.last4}",
                "on_the_card_on_file": a.payment_method_id == card.pk,
                "environment": a.environment},
    "payment": p and {"method": p.method, "amount_cents": p.amount_cents,
                      "nmi_transaction_id": p.nmi_transaction_id, "note": p.note},
    "invoice": {"number": a.invoice.number, "status": a.invoice.status,
                "balance_cents": a.invoice.balance_cents},
    "sent_before_consent": {"number": before.number, "status": before.status,
        "attempts": PaymentAttempt.all_objects.filter(invoice=before).count()},
    "mail": list(OutboxMessage.all_objects.filter(producer__in=["payment_receipt",
        "payment_notice", "autopay_notice"]).values_list("producer", "to_address", "state")),
    "lookup": found and {"nmi_transaction_id": found.id, "approved": found.approved},
    "vault_record_deleted": True}))
"""


def autopay_proof() -> dict:
    from playwright.sync_api import sync_playwright

    build_frontend()
    fresh_proof_db()
    setup = json.loads(manage("nmi_proof_setup", env_extra=PROOF_ENV).strip().splitlines()[-1])
    server = start_server(PROOF_ENV)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            for tries in range(1, 4):
                try:
                    autopay_attempt(browser, setup)
                    break
                except Exception as exc:
                    if tries == 3:
                        raise
                    print(f"Try {tries}: {type(exc).__name__}", file=sys.stderr)
                    # A fresh sign-in link for the next try.
                    setup["sign_in_path"] = manage(
                        "shell", "-c", "from apps.accounts.models import MagicLinkToken, User; "
                        "from apps.tenancy.models import Tenant; "
                        "u = User.objects.get(email='casey@proof-client.invalid'); "
                        "t = Tenant.objects.get(legal_name='Proof Practice LLC'); "
                        "_, raw = MagicLinkToken.issue(tenant=t, user=u, redirect_to='/invoices'); "
                        "print('/auth/magic/' + raw)", env_extra=PROOF_ENV).strip().splitlines()[-1]
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)
    charged = json.loads(manage("nmi_proof_setup", "--autopay-charge",
                                env_extra=PROOF_ENV).strip().splitlines()[-1])
    result = json.loads(manage("shell", "-c", AUTOPAY_READ_BACK,
                               env_extra=PROOF_ENV).strip().splitlines()[-1])
    result["send"] = charged
    result["ok"] = (result["attempt"]["status"] == "approved"
                    and result["attempt"]["on_the_card_on_file"]
                    and result["payment"] is not None and result["invoice"]["status"] == "paid"
                    and result["sent_before_consent"]["attempts"] == 0
                    and charged["job"]["charged"] == 1 and charged["job_again"]["charged"] == 0
                    and "will be charged to the card ending 1111" in charged["email_says"]
                    and result["lookup"] is not None
                    and result["lookup"]["nmi_transaction_id"]
                    == result["attempt"]["nmi_transaction_id"])
    return result


def subscription_attempt(browser, session) -> None:
    context = browser.new_context()
    context.add_cookies([{"name": session["cookie"], "value": session["session"],
                          "url": BASE}])
    page = context.new_page()
    try:
        page.goto(BASE + "/settings/billing", wait_until="domcontentloaded", timeout=90000)
        page.get_by_role("button", name="Add a card").click(timeout=90000)
        # Below the fold on this page: NMI's frames load once in view.
        page.locator("[data-testid=card-form]").scroll_into_view_if_needed(timeout=30000)
        fill_card(page, button=re.compile(r"^Save this card$"))
        page.get_by_text(re.compile(r"ending 1111")).first.wait_for(timeout=120000)
    finally:
        context.close()


SUBSCRIPTION_READ_BACK = """
import json
from apps.billing import gateway as gw
from apps.billing.models import ClientPayment, PracticeInvoice, PracticeSubscription
from apps.crm.models import OutboxAttachment, OutboxMessage
from apps.tenancy import storage
row = PracticeSubscription.all_objects.select_related("tenant").get(
    tenant__legal_name="Proof Practice LLC")
inv = PracticeInvoice.all_objects.get(tenant=row.tenant)
receipt = OutboxMessage.all_objects.filter(producer="subscription_receipt").first()
attached = list(OutboxAttachment.all_objects.filter(outbox_message=receipt)) if receipt else []
found = gw.gateway().find_by_reference(gw.platform_account(), inv.reference)
gw.gateway().vault_delete(gw.platform_account(), row.nmi_vault_id)
print(json.dumps({
    "subscription": {"status": row.status, "card": f"{row.card_brand} {row.card_last4}",
                     "expires": row.card_expires, "environment": row.card_environment,
                     "first_charge_on": row.first_charge_on.isoformat()},
    "invoice": {"number": inv.number, "status": inv.status, "total_cents": inv.total_cents,
                "tax_cents": inv.tax_cents, "period": f"{inv.period_start}..{inv.period_end}",
                "nmi_transaction_id": inv.nmi_transaction_id, "reference": inv.reference,
                "pdf_bytes": len(storage.read(inv.pdf)) if inv.pdf_id else 0},
    "receipt": receipt and {"to": receipt.to_address, "state": receipt.state,
        "sent_from": receipt.tenant.legal_name, "attachments": [a.filename for a in attached],
        "attachment_bytes": [len(storage.read(a.stored_file)) for a in attached]},
    "client_payments": ClientPayment.all_objects.count(),
    "lookup": found and {"nmi_transaction_id": found.id, "approved": found.approved,
                         "amount_cents": found.amount_cents, "reference": found.reference},
    "vault_record_deleted": True}))
"""


def subscription_proof() -> dict:
    from playwright.sync_api import sync_playwright

    build_frontend()
    subprocess.run(["dropdb", "--if-exists", PROOF_DB], check=True)
    subprocess.run(["createdb", PROOF_DB], check=True)
    print("Migrating the proof database…", file=sys.stderr)
    manage("migrate", "--noinput", env_extra=PROOF_ENV)
    manage("nmi_proof_setup", env_extra=PROOF_ENV)
    session = json.loads(manage("nmi_proof_setup", "--subscription",
                                env_extra=PROOF_ENV).strip().splitlines()[-1])
    server = start_server(PROOF_ENV)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            for tries in range(1, 4):
                try:
                    subscription_attempt(browser, session)
                    break
                except Exception as exc:
                    saved = manage("shell", "-c", "from apps.billing.models import "
                                   "PracticeSubscription as S; print(S.all_objects.exclude("
                                   "nmi_vault_id='').count())", env_extra=PROOF_ENV).strip()
                    if tries == 3 or saved.splitlines()[-1] != "0":
                        raise
                    print(f"Try {tries}: {type(exc).__name__}", file=sys.stderr)
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)
    charged = json.loads(manage("nmi_proof_setup", "--subscription-charge",
                                env_extra=PROOF_ENV).strip().splitlines()[-1])
    result = json.loads(manage("shell", "-c", SUBSCRIPTION_READ_BACK,
                               env_extra=PROOF_ENV).strip().splitlines()[-1])
    result["job"] = charged
    inv = result["invoice"]
    result["ok"] = (inv["status"] == "paid" and inv["nmi_transaction_id"] != ""
                    and inv["pdf_bytes"] > 0
                    and charged["day_before"]["charged"] == 0
                    and charged["job"]["charged"] == 1 and charged["job_again"]["charged"] == 0
                    and result["receipt"] is not None
                    and result["receipt"]["attachments"] == [f"Invoice-{inv['number']}.pdf"]
                    and result["client_payments"] == 0
                    and result["lookup"] is not None
                    and result["lookup"]["nmi_transaction_id"] == inv["nmi_transaction_id"])
    return result


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


# ------------------------------------------ refunds and Test Mode (2026-11-16)

#: NMI's published Mastercard test card: the second payment of one amount.
SECOND_CARD = ("5431111111111111", "10/29", "999")
IGNORE_TEST_MODE = {"NMI_SANDBOX_IGNORE_TEST_MODE": "true"}


def facts(env) -> dict:
    return json.loads(manage("nmi_proof_setup", "--refund-facts",
                             env_extra=env).strip().splitlines()[-1])


def owner_page(browser, session):
    context = browser.new_context()
    context.add_cookies([{"name": session["cookie"], "value": session["session"],
                          "url": BASE}])
    return context, context.new_page()


def give_back(page, invoice_id, *, reason, amount=None, void=False, expect="") -> str:
    """The practice owner's "Refund or cancel this payment", as clicked."""
    page.goto(f"{BASE}/invoices/{invoice_id}", wait_until="domcontentloaded", timeout=90000)
    page.get_by_role("button", name=re.compile(r"^Refund or cancel the payment of")).click(
        timeout=90000)
    form = page.get_by_role("form", name="Refund or cancel this payment")
    if amount is not None:
        form.get_by_label("Amount to give back").fill(amount)
    form.get_by_label("Why the money is given back").fill(reason)
    if void:
        form.get_by_label("and void the invoice").check()
    form.get_by_role("button", name=re.compile(r"^Give back \$")).click()
    said = page.get_by_role("status").filter(has_text=expect)
    said.wait_for(timeout=120000)
    return said.inner_text()


def refunds_proof() -> dict:
    from playwright.sync_api import sync_playwright

    env = {**PROOF_ENV, **IGNORE_TEST_MODE}
    build_frontend()
    fresh_proof_db()
    setup = json.loads(manage("nmi_proof_setup", "--contact",
                              env_extra=env).strip().splitlines()[-1])
    session = json.loads(manage("nmi_proof_setup", "--subscription",
                                env_extra=env).strip().splitlines()[-1])
    steps, said = [], {}
    server = start_server(env)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            context, owner = owner_page(browser, session)
            link_attempt(browser, setup)
            steps.append(("paid by the link", facts(env)["invoices"][0]["status"]))
            said["cancel"] = give_back(owner, setup["invoice_id"], reason="Charged twice "
                                       "by mistake (proof).", expect="Cancelled before it "
                                       "settled")
            steps.append(("cancelled in full", facts(env)["invoices"][0]["refunds"][-1]))
            link_attempt(browser, setup, card=SECOND_CARD)
            steps.append(("paid again", facts(env)["invoices"][0]["status"]))
            said["part"] = give_back(owner, setup["invoice_id"], amount="2.00",
                                     reason="A goodwill credit (proof).", expect="Refunded")
            said["rest"] = give_back(owner, setup["invoice_id"], reason="Engagement ended "
                                     "(proof).", void=True, expect="Refunded")
            steps.append(("read-back, next run", json.loads(manage(
                "nmi_proof_setup", "--read-back", env_extra=env).strip().splitlines()[-1])))
            # A second invoice, refunded in part straight at NMI.
            second = json.loads(manage("nmi_proof_setup", "--another-invoice",
                                       env_extra=env).strip().splitlines()[-1])
            link_attempt(browser, second)
            portal = json.loads(manage("nmi_proof_setup", "--portal-refund",
                                       second["invoice_id"], "100",
                                       env_extra=env).strip().splitlines()[-1])
            steps.append(("refunded at NMI, not here", portal["approved"]))
            steps.append(("read-back after it", json.loads(manage(
                "nmi_proof_setup", "--read-back", env_extra=env).strip().splitlines()[-1])))
            owner.goto(f"{BASE}/invoices", wait_until="domcontentloaded", timeout=90000)
            owner.get_by_role("button", name=re.compile(r"^Record this refund")).click(
                timeout=90000)
            owner.get_by_role("button", name=re.compile(r"^Record this refund")).wait_for(
                state="detached", timeout=60000)
            context.close()
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)
    result = {"steps": steps, "said": said, "facts": facts(env)}
    first, second_invoice = result["facts"]["invoices"]
    # The sandbox's last week holds other runs' transactions too, which this
    # fresh database never made: the read-back rightly flags those. What
    # matters is that none of this run's own were, but the portal's refund.
    ours = {t for inv in result["facts"]["invoices"]
            for t in [p["nmi_transaction_id"] for p in inv["payments"]]
            + [r["nmi_transaction_id"] for r in inv["refunds"]]}
    flagged_ours = [f for f in result["facts"]["flags"] if f[3] in ours]
    result["flagged_of_this_run"] = flagged_ours
    result["flagged_from_earlier_runs"] = len(result["facts"]["flags"]) - len(flagged_ours)
    result["facts"]["flags"] = flagged_ours
    kinds = [(r["kind"], r["status"], r["amount_cents"]) for r in first["refunds"]]
    pays = first["payments"]
    result["ok"] = bool(
        len(kinds) == 3 and kinds[0][0] == "void" and kinds[1][:2] == ("refund", "done")
        and kinds[1][2] == 200 and kinds[2][:2] == ("refund", "done")
        and kinds[2][2] == pays[1]["amount_cents"] - 200
        and first["status"] == "void" and first["paid_cents"] == 0
        and all(not row[3] is None for row in pays[0]["books"])        # the void took it out
        and all(row[3] is None for row in pays[1]["books"])            # the second stays
        and sum(r["books"][0][2] for r in first["refunds"][1:]) == pays[1]["amount_cents"]
        and flagged_ours == [["refund", "matched", 100, second_invoice["refunds"][0][
            "nmi_transaction_id"]]]
        and steps[5][1]["matched"] == 1
        and second_invoice["refunds"][0]["source"] == "portal"
        and second_invoice["refunds"][0]["amount_cents"] == 100
        and second_invoice["refunds"][0]["books"])
    return result


def billing_run(env, day) -> dict:
    return json.loads(manage("nmi_proof_setup", "--billing-run", day.isoformat(),
                             env_extra=env).strip().splitlines()[-1])


def _billing_days(start, through, days=(1, 15)):
    from datetime import timedelta

    day, found = start, []
    while day <= through:
        if day.day in days:
            found.append(day)
        day += timedelta(days=1)
    return found


def set_up_automatic(owner, first, price) -> str:
    """The practice owner's clicks: a recurring invoice that bills
    automatically on the 1st and the 15th, and the link emailed."""
    owner.goto(f"{BASE}/invoices", wait_until="domcontentloaded", timeout=90000)
    owner.get_by_role("button", name="New recurring invoice").click(timeout=90000)
    form = owner.get_by_role("dialog", name="The new recurring invoice")
    form.get_by_label("Client company for the recurring invoice").select_option(
        label="Proof Client Co")
    form.get_by_label("Recurring invoice addressed to").select_option(
        label="Casey Client", timeout=30000)
    form.get_by_label("Bill automatically").check()
    form.get_by_label("Billing day 1", exact=True).fill("1")
    form.get_by_role("button", name="Add a day").click()
    form.get_by_label("Billing day 2", exact=True).fill("15")
    form.get_by_label("First billing date").fill(first.isoformat())
    form.get_by_label("Description of line 1").fill("Operations support (proof)")
    form.get_by_label("Price of line 1").fill(price)
    form.get_by_role("button", name="Save the recurring invoice").click()
    owner.get_by_text("Waiting for Proof Client Co to agree").wait_for(timeout=60000)
    owner.get_by_role("button", name="Details of automatic billing for Proof "
                                      "Client Co").click()
    owner.get_by_role("button", name="Email Proof Client Co the link to agree").click()
    return owner.get_by_role("status").filter(has_text="link was emailed").inner_text(
        timeout=60000)


def agree_in_portal(browser, setup):
    """The client owner's clicks: sign in, save NMI's test card in the
    automatic billing card, tick I agree, agree."""
    client_context = browser.new_context()
    client = client_context.new_page()
    client.goto(BASE + setup["sign_in_path"], wait_until="domcontentloaded", timeout=90000)
    client.get_by_role("button", name="Sign in").click()
    client.get_by_text("First, save the card it is charged to.").wait_for(timeout=90000)
    terms = client.get_by_label("The terms").inner_text()
    fill_card(client, button=re.compile(r"^Save this card$"))
    client.get_by_text(re.compile(r"Visa ending\s+1111")).first.wait_for(timeout=120000)
    client.get_by_label("I agree to these terms").check()
    client.get_by_role("button", name="Agree and start automatic billing").click()
    client.get_by_role("button", name="Stop automatic billing").wait_for(timeout=60000)
    return client_context, client, terms


def run_now_proof() -> dict:
    """2026-11-17: with the sandbox's own Test Mode on (it always says so),
    the practice owner's "Run the next billing now" makes, sends and charges
    the next invoice at once, twice; each is a test, out of the books."""
    from datetime import datetime, timedelta, timezone

    from playwright.sync_api import sync_playwright

    build_frontend()
    fresh_proof_db()
    setup = json.loads(manage("nmi_proof_setup", env_extra=PROOF_ENV).strip().splitlines()[-1])
    session = json.loads(manage("nmi_proof_setup", "--subscription",
                                env_extra=PROOF_ENV).strip().splitlines()[-1])
    today = datetime.now(timezone.utc).date()
    first = _billing_days(today + timedelta(days=1), today + timedelta(days=20))[0]
    cents = 2000 + int(time.time() * 1000) % 2900
    said = {}
    server = start_server(PROOF_ENV)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            context, owner = owner_page(browser, session)
            said["link"] = set_up_automatic(owner, first, f"{cents / 100:.2f}")
            client_context, client, _terms = agree_in_portal(browser, setup)
            owner.goto(f"{BASE}/invoices", wait_until="domcontentloaded", timeout=90000)
            owner.get_by_role("button", name="Details of automatic billing for Proof "
                                              "Client Co").click(timeout=90000)
            # INV-0001 is the setup's own invoice: these are the next two. The
            # second is the same card for the same amount seconds after the
            # first: what NMI says to that is printed, not assumed. Each waits
            # for its own invoice's answer, so the server is never stopped
            # while a charge is still being asked.
            for n, number in ((1, "INV-0002"), (2, "INV-0003")):
                owner.get_by_role("button", name="Run the next billing now").click(
                    timeout=60000)
                said[f"run {n}"] = owner.get_by_role("status").filter(
                    has_text=f"Invoice {number}").inner_text(timeout=120000)
            client.close()
            client_context.close()
            context.close()
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)
    result = {"said": said, "facts": json.loads(manage(
        "nmi_proof_setup", "--billing-facts", env_extra=PROOF_ENV).strip().splitlines()[-1])}
    invoices = result["facts"]["invoices"]
    result["ok"] = bool(
        len(invoices) >= 1 and invoices[0]["status"] == "paid"
        and invoices[0]["attempts"][0][0] == "approved" and invoices[0]["attempts"][0][4]
        and invoices[0]["billing_date"] == first.isoformat()
        and "Thank you" in said["run 1"])
    return result


def automatic_proof() -> dict:
    """2026-11-17: set up, agree in the portal, the invoice sent by itself,
    the charge, a price change, stop, the last charge, Ended."""
    import calendar
    from datetime import date, datetime, timedelta, timezone

    from playwright.sync_api import sync_playwright

    env = {**PROOF_ENV, **IGNORE_TEST_MODE}
    build_frontend()
    fresh_proof_db()
    setup = json.loads(manage("nmi_proof_setup", env_extra=env).strip().splitlines()[-1])
    session = json.loads(manage("nmi_proof_setup", "--subscription",
                                env_extra=env).strip().splitlines()[-1])
    # The server's day (UTC, as the app counts it), and the dates that follow.
    today = datetime.now(timezone.utc).date()
    first = _billing_days(today + timedelta(days=1), today + timedelta(days=20))[0]
    year, month = (today.year + (today.month == 12), today.month % 12 + 1)
    ends = date(year, month, calendar.monthrange(year, month)[1])   # notice given today
    billed = _billing_days(first, ends)
    after = _billing_days(ends + timedelta(days=1), ends + timedelta(days=20))[0]
    cents = 2000 + int(time.time() * 1000) % 2900
    price, new_price = f"{cents / 100:.2f}", f"{(cents + 111) / 100:.2f}"
    steps, said = [], {}
    server = start_server(env)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            context, owner = owner_page(browser, session)
            said["link"] = set_up_automatic(owner, first, price)
            steps.append(("set up, waiting", "Waiting for Proof Client Co to agree"))
            client_context, client, said["terms"] = agree_in_portal(browser, setup)
            steps.append(("agreed in the portal", True))
            # Three days before the first date, then on it (the worker's jobs).
            steps.append(("made and emailed by itself", billing_run(env, first - timedelta(
                days=3))))
            steps.append(("charged on the date", billing_run(env, first)))
            # The owner changes the price: from a date at least 7 days out.
            owner.goto(f"{BASE}/invoices", wait_until="domcontentloaded", timeout=90000)
            owner.get_by_role("button", name="Edit the recurring invoice for Proof "
                                              "Client Co").click(timeout=90000)
            edit = owner.get_by_role("dialog", name=re.compile(r"^Editing"))
            edit.get_by_label("Price of line 1").fill(new_price)
            edit.get_by_role("button", name="Save the changes").click()
            edit.wait_for(state="detached", timeout=60000)
            steps.append(("price changed", new_price))
            # The client stops it, reading the dates first.
            client.goto(f"{BASE}/invoices", wait_until="domcontentloaded", timeout=90000)
            client.get_by_role("button", name="Stop automatic billing").click(timeout=90000)
            dialog = client.get_by_role("dialog", name="Stop automatic billing?")
            said["stop"] = dialog.inner_text(timeout=60000)
            dialog.get_by_role("button", name="Confirm: stop automatic billing").click()
            client.get_by_role("button", name="Withdraw my notice").wait_for(timeout=60000)
            said["ending"] = client.get_by_text(re.compile(r"^Billing continues through")) \
                .first.inner_text()
            steps.append(("notice given", True))
            # Every billing date through the end; then the day after; then
            # the next billing date, which is not billed.
            for day in billed[1:]:
                steps.append((f"made {day}", billing_run(env, day - timedelta(days=3))))
                steps.append((f"charged {day}", billing_run(env, day)))
            steps.append(("the day after the end", billing_run(env, ends + timedelta(days=1))))
            steps.append(("the next date, after the end", billing_run(env, after)))
            # Ended, on both sides.
            owner.goto(f"{BASE}/invoices", wait_until="domcontentloaded", timeout=90000)
            owner.get_by_text("Ended", exact=True).first.wait_for(timeout=60000)
            client.goto(f"{BASE}/invoices", wait_until="domcontentloaded", timeout=90000)
            said["ended"] = client.get_by_text(re.compile(r"^Automatic billing ended")) \
                .first.inner_text(timeout=60000)
            steps.append(("Ended on both pages", True))
            client.close()
            client_context.close()
            context.close()
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)
    result = {"dates": {"today": today.isoformat(), "first": first.isoformat(),
                        "billed": [d.isoformat() for d in billed], "ends": ends.isoformat(),
                        "not_billed": after.isoformat()},
              "steps": steps, "said": said,
              "facts": json.loads(manage("nmi_proof_setup", "--billing-facts",
                                         env_extra=env).strip().splitlines()[-1])}
    facts_ = result["facts"]
    invoices = facts_["invoices"]
    [agreement] = facts_["agreements"]
    result["ok"] = bool(
        facts_["state"] == "ended"
        and [i["billing_date"] for i in invoices] == [d.isoformat() for d in billed]
        and all(i["status"] == "paid" and len(i["attempts"]) == 1
                and i["attempts"][0][0] == "approved" and i["attempts"][0][1] == "autopay"
                and i["attempts"][0][2] for i in invoices)
        and invoices[0]["total_cents"] == cents and invoices[-1]["total_cents"] == cents + 111
        and invoices[0]["issue_date"] == (first - timedelta(days=3)).isoformat()
        and invoices[0]["email"]["state"] == "sent"
        and "will be charged to the card ending 1111 on" in invoices[0]["email"]["says_charged"]
        and agreement["browser_kept"] and agreement["address_kept"]
        and agreement["card"] == "1111" and agreement["notice_given"]
        and agreement["ends_on"] == ends.isoformat() and agreement["ends_set_by"] == "client"
        and agreement["ended"]
        and said["ended"].startswith("Automatic billing ended")
        and said["stop"].startswith(f"Billing continues through ")
        and "Your last charge will be on" in said["stop"]
        and dict(steps)["the next date, after the end"]["made"] == []
        and dict(steps)["the next date, after the end"]["charged"] == 0)
    return result


def _long(day) -> str:
    return f"{day:%B} {day.day}, {day.year}"


def beside_proof() -> dict:
    """2026-11-17: what the client owner sees of automatic billing and auto-pay
    beside it, in the portal built from this tree, as a client owner: the
    schedule on its own line and the stop rule before Stop, in the box and the
    terms; saving the card to agree puts no second "I agree" in front of them;
    "Auto-pay for other invoices" offered only when asked for, and what its
    sentence and "Turn auto-pay off" say keeps running; "Remove the card" off
    with a reason that fits the state; the practice owner's end and last
    charge once notice is given; and, with the server's clock moved to the day
    after the end date, before the 5:00 job has closed the agreement, the card
    can go."""
    import calendar
    from datetime import date, datetime, timedelta, timezone

    from playwright.sync_api import sync_playwright

    env = {**PROOF_ENV, **IGNORE_TEST_MODE}
    build_frontend()
    fresh_proof_db()
    setup = json.loads(manage("nmi_proof_setup", env_extra=env).strip().splitlines()[-1])
    session = json.loads(manage("nmi_proof_setup", "--subscription",
                                env_extra=env).strip().splitlines()[-1])
    today = datetime.now(timezone.utc).date()
    first = _billing_days(today + timedelta(days=1), today + timedelta(days=20))[0]
    year, month = (today.year + (today.month == 12), today.month % 12 + 1)
    ends = date(year, month, calendar.monthrange(year, month)[1])   # notice given today
    last = _billing_days(first, ends)[-1]
    cents = 2000 + int(time.time() * 1000) % 2900
    checks: list[tuple[str, bool, str]] = []
    shots = Path(os.environ.get("PROOF_SHOTS", "/tmp"))

    def check(label, ok, detail=""):
        checks.append((label, bool(ok), detail))

    def visible(page, text, exact=True):
        try:
            page.get_by_text(text, exact=exact).first.wait_for(timeout=30000)
            return True
        except Exception:
            return False

    stop_rule = "If you stop, billing continues through the end of the following month."
    on_hold = ("Automatic billing is on, so the card on file can't be removed. Replace it with "
               "another card, or stop automatic billing first.")
    ending_hold = (f"Automatic billing continues through {_long(ends)}, so the card stays on "
                   "file until then. You can replace it with another card.")
    server = start_server(env)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            context, owner = owner_page(browser, session)
            set_up_automatic(owner, first, f"{cents / 100:.2f}")
            client_context = browser.new_context(viewport={"width": 1366, "height": 900})
            client = client_context.new_page()
            client.goto(BASE + setup["sign_in_path"], wait_until="domcontentloaded",
                        timeout=90000)
            client.get_by_role("button", name="Sign in").click()
            client.get_by_text("First, save the card it is charged to.").wait_for(timeout=90000)
            # 5: the schedule on its own line and the stop rule, before Stop.
            check("box: the schedule on its own line",
                  visible(client, "Billed on the 1st and 15th of each month"))
            check("box: the stop rule, before anyone presses Stop", visible(client, stop_rule))
            terms = client.get_by_label("The terms").inner_text()
            check("terms: the schedule on its own line",
                  "\nBilled on the 1st and 15th of each month.\n" in terms, terms)
            check("terms: the stop rule",
                  f"\n{stop_rule} Every billing date through then is billed, and nothing "
                  "after." in terms)
            # 1: the card saved to agree; no second "I agree" in front of them.
            fill_card(client, button=re.compile(r"^Save this card$"))
            try:
                client.get_by_text(re.compile(r"Visa ending\s+1111")).first.wait_for(
                    timeout=120000)
            except Exception:
                client.screenshot(path=str(shots / "beside_failed_card.png"), full_page=True)
                raise
            client.get_by_role("button", name="Also pay other invoices automatically?").wait_for(
                timeout=60000)
            check("card saved to agree: no auto-pay \"I agree\" shown, only the link",
                  client.get_by_label("I agree", exact=True).count() == 0
                  and client.get_by_text("I authorize").count() == 0
                  and client.get_by_label("I agree to these terms").count() == 1)
            client.screenshot(path=str(shots / "beside_1_waiting.png"), full_page=True)
            client.get_by_label("I agree to these terms").check()
            client.get_by_role("button", name="Agree and start automatic billing").click()
            client.get_by_role("button", name="Stop automatic billing").wait_for(timeout=60000)
            check("agreed: the stop rule still said before Stop", visible(client, stop_rule))
            region = client.get_by_role("region", name="Auto-pay for other invoices")
            check("agreed: auto-pay is \"for other invoices\", apart from the agreement",
                  region.get_by_text("Automatic billing is charged under its own agreement")
                  .count() == 1
                  and client.get_by_role("heading", name="Card on file", exact=True).count() == 1)
            remove = client.get_by_role("button", name="Remove the card")
            # The reason first: the card's state is read again after agreeing.
            check("agreed: Remove the card is off, with why",
                  visible(client, on_hold) and remove.is_disabled(), on_hold)
            # 1-2: asked for, turned on; what it says keeps running.
            region.get_by_role("button", name="Also pay other invoices automatically?").click()
            check("asked: the auto-pay wording, and that it doesn't cover automatic billing",
                  visible(client, "This doesn't cover automatic billing, which is charged under "
                          "its own agreement."))
            region.get_by_label("I agree", exact=True).check()
            region.get_by_role("button", name="Turn auto-pay on for other invoices").click()
            check("on: the sentence says other invoices",
                  visible(client, "turned on by Casey Client. Other invoices from Proof Practice "
                          "are charged to the card on file on their due dates.", exact=False))
            check("on: Turn auto-pay off says automatic billing keeps running",
                  region.get_by_role("button", name="Turn auto-pay off for other invoices")
                  .count() == 1
                  and visible(client, "Automatic billing keeps running under its agreement; to "
                              "end it, press Stop automatic billing above."))
            client.screenshot(path=str(shots / "beside_2_active.png"), full_page=True)
            # 3: stop; the card held through the end date, said so.
            client.get_by_role("button", name="Stop automatic billing").click()
            dialog = client.get_by_role("dialog", name="Stop automatic billing?")
            said_stop = dialog.inner_text(timeout=60000)
            dialog.get_by_role("button", name="Confirm: stop automatic billing").click()
            client.get_by_role("button", name="Withdraw my notice").wait_for(timeout=60000)
            check("notice: Remove the card off, through the end date",
                  visible(client, ending_hold) and remove.is_disabled(), ending_hold)
            check("notice: Turn auto-pay off says billing continues through the end",
                  visible(client, f"Automatic billing continues through {_long(ends)}."))
            # 2: turning auto-pay off leaves automatic billing as it was.
            region.get_by_role("button", name="Turn auto-pay off for other invoices").click()
            region.get_by_role("button", name="Also pay other invoices automatically?").wait_for(
                timeout=60000)
            client.reload(wait_until="domcontentloaded")
            check("auto-pay off: automatic billing still ending on its date, its last charge "
                  "kept", visible(client, f"Billing continues through {_long(ends)}. Your last "
                                          f"charge will be on {_long(last)}.", exact=False)
                  and client.get_by_role("button", name="Withdraw my notice").count() == 1)
            client.screenshot(path=str(shots / "beside_3_ending.png"), full_page=True)
            # 5: the practice owner sees the end and the last charge.
            owner.goto(f"{BASE}/invoices", wait_until="domcontentloaded", timeout=90000)
            check("owner: the end and the last charge once notice is given",
                  visible(owner, f"Billing ends {_long(ends)}. Last charge {_long(last)}."))
            owner.screenshot(path=str(shots / "beside_4_owner.png"), full_page=True)
            client.close()
            client_context.close()
            context.close()
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)
    # The day after the end date, at 9:00 Denver; the 5:00 job has not run.
    after = datetime(ends.year, ends.month, ends.day, 16, tzinfo=timezone.utc) + timedelta(days=1)
    before_close = json.loads(manage("nmi_proof_setup", "--billing-facts", env_extra=env,
                                     clock=after).strip().splitlines()[-1])
    check("day after the end: the agreement not yet closed by the 5:00 job",
          not before_close["agreements"][0]["ended"])
    link = json.loads(manage("nmi_proof_setup", "--client-link", env_extra=env,
                             clock=after).strip().splitlines()[-1])
    server = start_server(env, clock=after)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            client_context = browser.new_context(viewport={"width": 1366, "height": 900})
            client = client_context.new_page()
            client.goto(BASE + link["sign_in_path"], wait_until="domcontentloaded",
                        timeout=90000)
            client.get_by_role("button", name="Sign in").click()
            client.get_by_text(re.compile(r"^Automatic billing ended")).first.wait_for(
                timeout=90000)
            remove = client.get_by_role("button", name="Remove the card")
            check("day after the end: Remove the card is on",
                  remove.is_enabled() and client.get_by_text(ending_hold).count() == 0)
            remove.click()
            check("day after the end: the card removed", visible(client, "No card on file.",
                                                                 exact=False))
            client.screenshot(path=str(shots / "beside_5_after.png"), full_page=True)
            client.close()
            client_context.close()
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)
    facts_ = json.loads(manage("nmi_proof_setup", "--billing-facts", env_extra=env,
                               clock=after).strip().splitlines()[-1])
    [agreement] = facts_["agreements"]
    check("facts: agreeing made no consent; the one asked for was turned off",
          [c["reason"] for c in facts_["consents"]] == ["Turned off"])
    check("facts: the agreement kept its notice and end", agreement["notice_given"]
          and agreement["ends_on"] == ends.isoformat() and agreement["ends_set_by"] == "client"
          and agreement["version"] == "2026-11-17.2")
    check("facts: the card removed only the day after", facts_["cards"] == [
        {"last4": "1111", "removed": True}])
    return {"dates": {"today": today.isoformat(), "first": first.isoformat(),
                      "ends": ends.isoformat(), "last_charge": last.isoformat(),
                      "clock_moved_to": after.isoformat()},
            "checks": [f"{'PASS' if ok else 'FAIL'}  {label}" for label, ok, _ in checks],
            "said_stop": said_stop, "terms": terms,
            "ok": all(ok for _, ok, _ in checks)}


def test_mode_proof() -> dict:
    from playwright.sync_api import sync_playwright

    build_frontend()
    fresh_proof_db()
    setup = json.loads(manage("nmi_proof_setup", "--contact",
                              env_extra=PROOF_ENV).strip().splitlines()[-1])
    session = json.loads(manage("nmi_proof_setup", "--subscription",
                                env_extra=PROOF_ENV).strip().splitlines()[-1])
    seen = {}
    server = start_server(PROOF_ENV)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            context, owner = owner_page(browser, session)
            for where in ("/settings/billing", "/invoices"):
                owner.goto(BASE + where, wait_until="domcontentloaded", timeout=90000)
                seen[where] = owner.get_by_role("alert").filter(
                    has_text="Test Mode").first.inner_text(timeout=90000)
            link_attempt(browser, setup)
            seen["refund"] = give_back(owner, setup["invoice_id"], amount="1.00",
                                       reason="Trying a refund in Test Mode (proof).",
                                       expect="a test: no money moved")
            autopay_attempt(browser, setup)       # the client saves a card: a test card
            seen["while_test_mode"] = facts(PROOF_ENV)
            context.close()
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)
    # Back in live mode: the same sandbox, read as live from here on.
    env = {**PROOF_ENV, **IGNORE_TEST_MODE}
    server = start_server(env)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            context, owner = owner_page(browser, session)
            owner.goto(BASE + "/settings/billing", wait_until="domcontentloaded", timeout=90000)
            owner.get_by_role("button", name="Test connection").click(timeout=90000)
            owner.get_by_role("heading", name="1 test payment").wait_for(timeout=90000)
            # No default since 2026-11-17 (INV-0005): Clear waits for a choice.
            clear = owner.get_by_role("button", name="Clear test payments")
            seen["clear_waits_for_a_choice"] = clear.is_disabled()
            # The radio, not the question above it ("Reopen their invoices, or …").
            owner.get_by_role("radio", name="Reopen their invoices").check()
            clear.click()
            seen["cleared"] = owner.get_by_text(re.compile(r"test payment cleared")).first \
                .inner_text(timeout=90000)
            context.close()
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)
    after = facts(env)
    during = seen["while_test_mode"]
    paid = during["invoices"][0]
    result = {"seen": seen, "after": after}
    result["ok"] = bool(
        during["gateway_mode"]["test_mode"] is True
        and all("Test Mode" in seen[w] for w in ("/settings/billing", "/invoices"))
        and paid["payments"][0]["is_test"] and not paid["payments"][0]["books"]
        and paid["test_paid_cents"] == paid["paid_cents"] > 0
        and paid["refunds"][0]["is_test"] and not paid["refunds"][0]["books"]
        and during["cards"][0]["is_test"] and during["receipts_saying_test"] >= 1
        and after["gateway_mode"]["test_mode"] is False
        and seen["clear_waits_for_a_choice"] is True
        and after["invoices"][0]["status"] == "sent"
        and after["invoices"][0]["payments"][0]["removed"]
        and after["invoices"][0]["refunds"][0]["cleared"]
        and after["cards"][0]["removed"] and after["cards"][0]["vault_answers"] != 200)
    return result


def fresh_proof_db() -> None:
    """The proof's own database, made afresh: never `execsnowhq_local`."""
    subprocess.run(["dropdb", "--if-exists", PROOF_DB], check=True)
    subprocess.run(["createdb", PROOF_DB], check=True)
    print("Migrating the proof database…", file=sys.stderr)
    manage("migrate", "--noinput", env_extra=PROOF_ENV)


def portal(by_link=False) -> dict:
    from playwright.sync_api import sync_playwright

    build_frontend()
    fresh_proof_db()
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


def _watch(page) -> dict:
    """Every console message, page error and request to a gateway host."""
    seen = {"console": [], "page_errors": [], "gateway": []}
    page.on("console", lambda m: seen["console"].append(f"{m.type}: {m.text[:300]}"))
    page.on("pageerror", lambda e: seen["page_errors"].append(str(e)[:300]))
    page.on("response", lambda r: seen["gateway"].append(
        f"{r.status} {r.url.split('?')[0]}") if any(
            h in r.url for h in ("secure.nmi.com", "secure.vaultixpay.com")) else None)
    return seen


def _form_facts(page) -> dict:
    """What the page's card form is, as the browser has it."""
    return page.evaluate("""() => {
      const tag = document.querySelector('script[src$="/token/Collect.js"]');
      const boxes = [...document.querySelectorAll('.collect-field[id^="cj-"]')];
      return {
        script: tag ? tag.getAttribute('src') : null,
        script_attributes: tag ? tag.getAttributeNames().sort() : [],
        collectjs_defined: !!window.CollectJS,
        payment_component: !!document.querySelector('nmi-pay-widget, nmi-payments'),
        field_frames: boxes.map((b) => ({ box: b.id.replace(/-\\d+$/, ''),
          frames: [...b.querySelectorAll('iframe')].map((f) => (f.getAttribute('src') || '')
            .split('?')[0]) })),
        pay_button_enabled: [...document.querySelectorAll('button')]
          .some((b) => /^Pay \\$/.test(b.textContent) && !b.disabled),
        alert: (document.querySelector('[role="alert"]') || {}).textContent || '',
      };
    }""")


FAILURE_READ = """
import json
from apps.notify.models import Notice
from apps.tenancy.models import AuditEvent
print(json.dumps({
  "notices": list(Notice.all_objects.filter(kind="payments").values_list("title", "text", "url")),
  "audit": [e.payload for e in AuditEvent.all_objects.filter(verb="billing.card_form_failed")]}))
"""


MAIL_SMTP, MAIL_API = 1125, 8126


def start_mailpit():
    """The project's dev mail catcher (docs/05_dev_environment.md) on its
    own ports for this run, so the receipt really goes out and can be read
    back. None when mailpit is not installed."""
    import shutil

    found = shutil.which("mailpit")
    if not found:
        return None
    proc = subprocess.Popen([found, "--smtp", f"127.0.0.1:{MAIL_SMTP}",
                             "--listen", f"127.0.0.1:{MAIL_API}"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        if proc.poll() is not None:
            sys.exit(f"mailpit could not start: is something else on {MAIL_SMTP} or {MAIL_API}?")
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{MAIL_API}/api/v1/messages", timeout=2)
            time.sleep(0.5)
            if proc.poll() is None:          # it is this run's, not one shutting down
                return proc
        except Exception:
            time.sleep(0.25)
    proc.terminate()
    return None


def caught_mail() -> list:
    with urllib.request.urlopen(f"http://127.0.0.1:{MAIL_API}/api/v1/messages",
                                timeout=10) as answer:
        data = json.loads(answer.read())
    return [{"subject": m.get("Subject", ""),
             "to": [t.get("Address", "") for t in m.get("To") or []]}
            for m in data.get("messages", [])]


#: Collect.js's own words for a box (2026-11-14), which the page never shows.
COLLECT_RAW = ("Field is empty", "Card number must be", "Expiration date must be", "CVV must be")
PLAIN = {"ccnumber": "Enter your card number", "ccexp": "Enter the expiry date as MM/YY",
         "cvv": "Enter the security code", "wrong_number": "That card number doesn't look right"}
PAY_FREE = """() => { const b = [...document.querySelectorAll('button')]
  .find((x) => /^Pay \\$/.test(x.textContent)); return !!b && !b.disabled; }"""


def box_checks(page) -> dict:
    """The card boxes' checks on the real pay page (2026-11-14), before the
    good card is typed: in a box and not yet left, nothing is said; the
    number left empty; Pay with every box empty; a wrong number left. Each
    time, what is said is read from beside each box, with any banner or
    alert and any of Collect.js's own words on the page. After the empty
    Pay, how long until Pay can be pressed again (Collect.js holds a failed
    attempt for its 15 s timeout unless the form ends it)."""
    page.wait_for_function(PAY_FREE, timeout=60000)
    heading = page.get_by_role("heading", name=re.compile(r"^Invoice "))
    number = page.frame_locator("#CollectJSInlineccnumber").locator("#ccnumber")

    def facts(step):
        page.wait_for_timeout(1500)
        body = page.locator("body").inner_text()
        return {"step": step,
                "said": page.evaluate("""() => Object.fromEntries([...document
                  .querySelectorAll('.collect-said')].map((p) => [p.dataset.field,
                  p.textContent]))"""),
                "banner": page.locator(".banner").all_inner_texts(),
                "alert": page.locator("[role=alert]").all_inner_texts(),
                "collect_js_words_on_page": [w for w in COLLECT_RAW if w in body],
                "processor_banner": "did not answer" in body}

    steps = []
    number.click()
    steps.append(facts("in the number box, nothing typed, not left"))
    heading.click()
    steps.append(facts("left the number box empty"))
    started = time.time()
    page.get_by_role("button", name=re.compile(r"^Pay \$")).click()
    page.wait_for_function("""() => [...document.querySelectorAll('.collect-said')]
      .filter((p) => p.textContent).length === 3""", timeout=20000)
    page.wait_for_function(PAY_FREE, timeout=20000)
    free_after = round(time.time() - started, 1)
    steps.append(facts("Pay pressed with every box empty"))
    steps[-1]["pay_free_again_after_s"] = free_after
    steps[-1]["collect_js_still_holding"] = page.evaluate("() => window.CollectJS.inSubmission")
    number.fill("4111111111111112")
    heading.click()
    steps.append(facts("a wrong number typed (4111 1111 1111 1112) and left"))

    clean = all(not s["banner"] and not s["alert"] and not s["collect_js_words_on_page"]
                and not s["processor_banner"] for s in steps)
    said = [s["said"] for s in steps]
    ok = (clean
          and said[0] == {"ccnumber": "", "ccexp": "", "cvv": ""}
          and said[1] == {"ccnumber": PLAIN["ccnumber"], "ccexp": "", "cvv": ""}
          and said[2] == {k: PLAIN[k] for k in ("ccnumber", "ccexp", "cvv")}
          and said[3] == {"ccnumber": PLAIN["wrong_number"], "ccexp": PLAIN["ccexp"],
                          "cvv": PLAIN["cvv"]}
          and free_after < 5 and steps[2]["collect_js_still_holding"] is False)
    return {"steps": steps, "ok": ok}


def link_collect(host) -> dict:
    """The real pay page with Collect.js from `host` (see the docstring)."""
    from playwright.sync_api import sync_playwright

    build_frontend()
    fresh_proof_db()
    env = {**PROOF_ENV, "NMI_SANDBOX_CARD_FORM_HOST": host}
    setup = json.loads(manage("nmi_proof_setup", "--contact", env_extra=env)
                       .strip().splitlines()[-1])
    result = {"host": host}
    server = start_server(env)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            page = browser.new_page()
            seen = _watch(page)
            page.goto(BASE + setup["pay_path"], wait_until="domcontentloaded", timeout=90000)
            page.get_by_role("heading", name=f"Invoice {setup['number']}").wait_for(
                timeout=90000)
            if host == "secure.vaultixpay.com":
                # No card is typed here: wait for the fields or for the page to
                # give up on them (FIELDS_WITHIN, 20 s), whichever comes first.
                for _ in range(60):
                    facts = _form_facts(page)
                    if facts["alert"] or facts["pay_button_enabled"]:
                        break
                    page.wait_for_timeout(500)
                page.wait_for_timeout(2000)       # the report's answer
                result["form"] = _form_facts(page)
                result["seen"] = seen
                page.close()
                browser.close()
            else:
                page.locator("iframe[src*='inline.php']").first.wait_for(timeout=60000)
                result["form_before_paying"] = _form_facts(page)
                page.get_by_text("Test mode").first.wait_for(timeout=60000)
                result["boxes"] = box_checks(page)
                fill_card(page, button=re.compile(r"^Pay \$"))
                page.get_by_role("status").filter(has_text="was paid on invoice").wait_for(
                    timeout=120000)
                result["paid_message"] = page.get_by_role("status").inner_text()
                result["seen"] = seen
                page.close()
                result["after"] = link_after(browser, setup)
                browser.close()
        result["mail_caught"] = (caught_mail() if "EMAIL_PORT" in PROOF_ENV
                                 else "mailpit is not installed")
    finally:
        server.terminate()
        server.wait(timeout=10)

    refused = [m for m in result["seen"]["console"] + result["seen"]["page_errors"]
               if "too many fields" in m]
    result["config_refused"] = refused
    # Collect.js's "Could not create PaymentRequestAbstraction" (2026-11-14):
    # gone once the form gives it currency, country and price.
    result["apple_pay_errors"] = sum(APPLE_PAY_ERROR in m for m in result["seen"]["console"])
    if host == "secure.vaultixpay.com":
        result["reported"] = json.loads(manage("shell", "-c", FAILURE_READ, env_extra=env)
                                        .strip().splitlines()[-1])
        form = result["form"]
        result["ok"] = (not refused and form["collectjs_defined"]
                        and form["script"] == f"https://{host}/token/Collect.js"
                        and form["script_attributes"] == sorted(
                            ["src", "data-tokenization-key", "data-variant"]
                            + (["async"] if "async" in form["script_attributes"] else []))
                        and (form["pay_button_enabled"]
                             or (bool(form["alert"]) and bool(result["reported"]["notices"]))))
        return result
    read = json.loads(manage("shell", "-c", READ_BACK, env_extra=env).strip().splitlines()[-1])
    result.update(read)
    before = result["form_before_paying"]
    result["ok"] = (not refused and before["collectjs_defined"]
                    and result["apple_pay_errors"] == 0
                    and result["boxes"]["ok"]
                    and not before["payment_component"]
                    and before["script"] == f"https://{host}/token/Collect.js"
                    and all(f["frames"] for f in before["field_frames"])
                    and read["attempt"]["status"] == "approved" and read["via"] == "link"
                    and read["payment"] is not None and read["payment"]["method"] == "card"
                    and read["invoice"]["status"] == "paid"
                    and any(m[0] == "payment_receipt" and m[2] == "sent" for m in read["mail"])
                    and any(m["subject"].startswith("Receipt: ")
                            for m in result["mail_caught"] if isinstance(m, dict))
                    and read["lookup"] is not None
                    and read["lookup"]["nmi_transaction_id"]
                    == read["attempt"]["nmi_transaction_id"]
                    and result["after"].get("shows_paid")
                    and not result["after"].get("card_form_shown"))
    return result


# ------------------------------------------------- bank payments and card fees

BANK_PORT = 8198
BANK_BASE = f"http://127.0.0.1:{BANK_PORT}"
#: NMI's published sandbox bank account (docs.nmi.com/reference/testing-methods).
TEST_BANK = ("Sandbox Proof", "490000018", "24413815")
#: For the category: NMI's published test cards, and public test numbers on
#: BINs the card networks list as debit and prepaid. Only ever typed into
#: Collect.js's frames on the sandbox.
CATEGORY_CARDS = [
    ("Visa, NMI's test card", "4111111111111111", "999"),
    ("Mastercard, NMI's test card", "5431111111111111", "999"),
    ("Discover, NMI's test card", "6011601160116611", "999"),
    ("Amex, NMI's test card", "341111111111111", "1234"),
    ("Visa on a debit BIN", "4000056655665556", "999"),
    ("Mastercard on a debit BIN", "5200828282828210", "999"),
    ("Mastercard on a prepaid BIN", "5105105105105100", "999"),
]
#: The settings that give Collect.js's Apple Pay request what it validates
#: (ApplePayRequest.getOptionErrors), and are Surcharge Plus's inputs too.
PRICED = {"price": "10.00", "currency": "USD", "country": "US"}
APPLE_PAY_ERROR = "Could not create PaymentRequestAbstraction"

PROOF_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Bank and fee proof</title>
<script src="https://secure.nmi.com/token/Collect.js" data-tokenization-key="%(key)s"
        data-variant="inline"></script></head>
<body style="font-family: sans-serif; max-width: 40rem; margin: 2rem auto">
<h1>Bank and fee proof (sandbox, %(kind)s)</h1>
<div id="f1" style="border:1px solid #ccc;height:2.6rem"></div>
<div id="f2" style="border:1px solid #ccc;height:2.6rem"></div>
<div id="f3" style="border:1px solid #ccc;height:2.6rem"></div>
<script>
const kind = "%(kind)s";
const extra = JSON.parse('%(extra)s');
window.made = []; window.lookups = []; window.checks = []; window.ready = false;
window.timedOut = 0;
const fields = kind === "bank"
  ? {checkname: {selector: "#f1"}, checkaba: {selector: "#f2"}, checkaccount: {selector: "#f3"}}
  : {ccnumber: {selector: "#f1"}, ccexp: {selector: "#f2"}, cvv: {selector: "#f3"}};
CollectJS.configure(Object.assign({
  variant: "inline", paymentType: kind === "bank" ? "ck" : "cc", fields,
  fieldsAvailableCallback: () => { window.ready = true; },
  timeoutDuration: 20000, timeoutCallback: () => { window.timedOut += 1; },
  validationCallback: (f, ok, m) => { window.checks.push([f, ok, m]); },
  lookUpCallback: (card) => { window.lookups.push(card); },
  callback: (r) => { window.made.push({tokenType: r.tokenType, token: r.token,
                                       card: r.card || null, check: r.check || null}); },
}, extra));
window.nextToken = () => new Promise((resolve, reject) => {
  const n = window.made.length, t0 = window.timedOut;
  CollectJS.startPaymentRequest();
  const tick = setInterval(() => {
    if (window.made.length > n) { clearInterval(tick); resolve(window.made[n]); }
    else if (window.timedOut > t0) { clearInterval(tick); reject(new Error("timeout")); }
  }, 100);
});
</script></body></html>"""


def sandbox_account():
    """The platform's sandbox account, read in this process from `.env`.
    Anything but NMI's sandbox host stops the run before a call is made."""
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from apps.billing import gateway as gw

    account = gw.platform_account()
    if (account.environment != "sandbox"
            or not account.base_url.startswith("https://sandbox.nmi.com/")
            or not account.query_url.startswith("https://sandbox.nmi.com/")):
        sys.exit("--bank-fees runs on NMI's sandbox only: NMI_ENVIRONMENT must be sandbox.")
    return account


def serve_proof_pages(public_key: str):
    """This run's own pages, from memory, on 127.0.0.1 only."""
    import html
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    pages = {"/bank": ("bank", {}), "/card": ("card", {}), "/card-priced": ("card", PRICED)}

    class Pages(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/favicon.ico":           # none, and no 404 in the console
                self.send_response(204)
                self.end_headers()
                return
            found = pages.get(self.path.split("?")[0])
            if not found:
                self.send_error(404)
                return
            kind, extra = found
            body = (PROOF_PAGE % {"key": html.escape(public_key), "kind": kind,
                                  "extra": json.dumps(extra)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", BANK_PORT), Pages)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def v5(account, method: str, path: str, body=None):
    """One v5 call on the sandbox: (status, answer). The key goes only in the
    header, and any answer text is scrubbed of it."""
    import requests

    answer = requests.request(method, account.base_url + path, timeout=30,
                              headers={"Authorization": account.private_key,
                                       "Content-Type": "application/json",
                                       "Accept": "application/json"},
                              data=json.dumps(body) if body is not None else None)
    try:
        payload = answer.json() if answer.text else None
    except ValueError:
        payload = {"text": account.scrub(answer.text[:300])}
    return answer.status_code, payload


def query(account, **params):
    """The classic Query API (read-only) on the sandbox: the parsed XML."""
    import xml.etree.ElementTree as ET

    import requests

    answer = requests.post(account.query_url, timeout=60,
                           data={"security_key": account.private_key, **params})
    return ET.fromstring(answer.text)


#: What the Query API says of a transaction, for these proofs.
QUERY_FIELDS = ("transaction_id", "transaction_type", "condition", "order_id", "sec_code",
                "account_holder_type", "account_type", "check_account", "check_aba",
                "check_name", "cc_type", "cc_number", "surcharge", "convenience_fee",
                "original_transaction_id", "customerid")


def query_facts(node) -> dict:
    facts = {k: node.findtext(k) for k in QUERY_FIELDS if node.find(k) is not None}
    facts["actions"] = [{k: a.findtext(k) for k in ("action_type", "amount", "date", "success",
                                                       "response_text")}
                        for a in node.findall("action")]
    return facts


def query_one(account, transaction_id: str) -> dict:
    root = query(account, transaction_id=transaction_id)
    node = root.find("transaction")
    if node is None:
        return {"error": (root.findtext("error_response") or "not found").strip()}
    return query_facts(node)


def picked(payload, *, keys=("id", "response", "response_code", "response_text", "status",
                            "amount", "error_code", "message", "details", "type")) -> dict:
    """The answer's own words that matter here, plus every key anywhere in it
    that names a surcharge, a fee, a SEC code, an account type or a check."""
    if not isinstance(payload, dict):
        return {"answer": payload}
    out = {k: payload[k] for k in keys if k in payload}
    hits = {}

    def walk(obj, path):
        if isinstance(obj, dict):
            for k, v in obj.items():
                here = f"{path}.{k}" if path else k
                if any(w in k for w in ("surcharge", "fee", "sec_code", "account_type",
                                        "holder", "check", "card_type", "category")):
                    hits[here] = v
                walk(v, here)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{path}[{i}]")

    walk(payload, "")
    if hits:
        out["named"] = hits
    return out


def fill_frame(page, element: str, value: str) -> None:
    """Type into Collect.js's frame for one field (its iframe is
    `#CollectJSInline<field>`), waiting for it to load."""
    frame = page.frame_locator(f"#CollectJSInline{element}")
    for _ in range(120):
        for selector in (f"#{element}", "input"):
            box = frame.locator(selector).first
            try:
                if box.count() and box.is_visible():
                    box.fill(value, timeout=5000)
                    box.blur()
                    return
            except Exception:
                pass
        page.wait_for_timeout(500)
    raise RuntimeError(f"Collect.js's {element} field never appeared.")


def open_proof_page(browser, path: str):
    page = browser.new_page()
    console = []
    page.on("console", lambda m: console.append(f"{m.type}: {m.text[:300]}"))
    page.on("pageerror", lambda e: console.append(f"pageerror: {str(e)[:300]}"))
    page.goto(BANK_BASE + path, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_function("window.ready === true", timeout=60000)
    return page, console


def bank_token(page) -> dict:
    for element, value in zip(("checkname", "checkaba", "checkaccount"), TEST_BANK):
        fill_frame(page, element, value)
    page.wait_for_timeout(500)
    return page.evaluate("() => window.nextToken()")


def card_token(page, number: str, cvv: str) -> dict:
    """The card typed in, what lookUpCallback said once the number was valid,
    and the token response."""
    before = page.evaluate("() => window.lookups.length")
    fill_frame(page, "ccnumber", number)
    lookup = None
    for _ in range(30):
        if page.evaluate("() => window.lookups.length") > before:
            lookup = page.evaluate("() => window.lookups[window.lookups.length - 1]")
            break
        page.wait_for_timeout(500)
    fill_frame(page, "ccexp", TEST_CARD[1])
    fill_frame(page, "cvv", cvv)
    page.wait_for_timeout(500)
    made = page.evaluate("() => window.nextToken()")
    return {"lookup": lookup, "token": made}


def no_token(made: dict) -> dict:
    """A token response without the token itself, for printing."""
    return {k: v for k, v in made.items() if k != "token"}


def ref_for(label: str) -> str:
    import uuid

    return f"proof-{label}-{uuid.uuid4().hex[:8]}"


def sale_body(amount: str, reference: str, *, token=None, vault_id=None, top=None,
              details=None, order=None) -> dict:
    body = {"amount": amount, "currency": "USD",
            "order_details": {"id": reference, **(order or {})},
            "merchant_defined_fields": {"field_1": reference}, **(top or {})}
    if token is not None:
        body["payment_details"] = {"payment_token": token, **(details or {})}
    else:
        body["customer_vault"] = {"id": vault_id}
    return body


def bank_section(account, browser, steps) -> dict:
    """Bank account tokens, sales with and without a SEC code, the vault."""
    import random

    out = {}
    page, console = open_proof_page(browser, "/bank")
    try:
        first = bank_token(page)
        out["token_response"] = no_token(first)
        tokens = [first["token"]] + [bank_token(page)["token"] for _ in range(6)]
    finally:
        page.close()
    out["console_on_bank_page"] = console
    base = random.randint(2000, 3999)

    def amount(k):
        return f"{(base + 37 * k) // 100}.{(base + 37 * k) % 100:02d}"

    # 1. No SEC code.
    ref = ref_for("ach")
    status, answer = v5(account, "POST", "/payments/sale",
                        sale_body(amount(0), ref, token=tokens[0]))
    out["sale_no_sec_code"] = {"http": status, **picked(answer)}
    steps.append(("bank sale, no SEC code", status))

    # 2. WEB: each place a SEC code might go, until one is accepted.
    places = [("payment_details.sec_code", lambda code: {"details": {"sec_code": code}}),
              ("top-level sec_code", lambda code: {"top": {"sec_code": code}})]
    tried, accepted = [], None
    for name, where in places:
        status, answer = v5(account, "POST", "/payments/sale",
                            sale_body(amount(1), ref_for("web"), token=tokens[1], **where("WEB")))
        tried.append({"where": name, "http": status, **picked(answer)})
        if status < 300 and isinstance(answer, dict) and answer.get("id"):
            accepted = (name, where)
            break
    out["sale_web"] = tried
    steps.append(("bank sale, WEB", tried[-1]["http"]))

    # 3. CCD where WEB was accepted; with the account holder as a business if refused.
    ccd = []
    if accepted:
        name, where = accepted
        status, answer = v5(account, "POST", "/payments/sale",
                            sale_body(amount(2), ref_for("ccd"), token=tokens[2], **where("CCD")))
        ccd.append({"where": name, "http": status, **picked(answer)})
        if not (status < 300 and isinstance(answer, dict) and answer.get("id")):
            spot = where("CCD")
            for part in spot.values():
                part["account_holder_type"] = "business"
            status, answer = v5(account, "POST", "/payments/sale",
                                sale_body(amount(3), ref_for("ccd"), token=tokens[3], **spot))
            ccd.append({"where": name + " with account_holder_type business",
                        "http": status, **picked(answer)})
    out["sale_ccd"] = ccd
    steps.append(("bank sale, CCD", ccd[-1]["http"] if ccd else None))

    # Each approved bank sale as the Query API reports it.
    approved = [r for r in [out["sale_no_sec_code"], *tried, *ccd] if r.get("id")]
    out["query_read_back"] = {r["id"]: query_one(account, str(r["id"])) for r in approved}

    # 4. The Customer Vault: stored from a token, charged, charged with a SEC code, deleted.
    status, answer = v5(account, "POST", "/customers",
                        {"billing": {"first_name": "Sandbox", "last_name": "Proof",
                                     "payment_details": {"payment_token": tokens[4]}}})
    vault = {"stored": {"http": status, **picked(answer, keys=("id", "message", "details")),
                        "billing": (answer or {}).get("billing") if isinstance(answer, dict)
                        else None}}
    vault_id = str(answer.get("id", "")) if isinstance(answer, dict) else ""
    steps.append(("bank account stored in the vault", status))
    if vault_id:
        status, answer = v5(account, "POST", "/payments/sale",
                            sale_body(amount(4), ref_for("vault"), vault_id=vault_id))
        vault["sale"] = {"http": status, **picked(answer)}
        steps.append(("sale on the vault record", status))
        status, answer = v5(account, "POST", "/payments/sale",
                            sale_body(amount(5), ref_for("vault-ccd"), vault_id=vault_id,
                                      top={"sec_code": "CCD"}))
        vault["sale_with_top_level_ccd"] = {"http": status, **picked(answer)}
        body = sale_body(amount(6), ref_for("vault-ccd"), vault_id=vault_id)
        body["payment_details"] = {"sec_code": "CCD"}
        status, answer = v5(account, "POST", "/payments/sale", body)
        vault["sale_with_payment_details_ccd"] = {"http": status, **picked(answer)}
        for key in ("sale", "sale_with_top_level_ccd", "sale_with_payment_details_ccd"):
            if vault[key].get("id"):
                vault[key]["query"] = query_one(account, str(vault[key]["id"]))
        status, _ = v5(account, "DELETE", f"/customers/{vault_id}")
        vault["deleted"] = status
    # A record stored as a business account with CCD, then charged as it is.
    status, answer = v5(account, "POST", "/customers",
                        {"billing": {"first_name": "Sandbox", "last_name": "Proof",
                                     "payment_details": {"payment_token": tokens[6],
                                                         "sec_code": "CCD",
                                                         "account_holder_type": "business"}}})
    ccd_vault = {"stored": {"http": status, **picked(answer, keys=("id", "message", "details"))}}
    ccd_id = str(answer.get("id", "")) if isinstance(answer, dict) and status < 300 else ""
    if ccd_id:
        status, answer = v5(account, "POST", "/payments/sale",
                            sale_body(amount(7), ref_for("vault-ccd"), vault_id=ccd_id))
        ccd_vault["sale"] = {"http": status, **picked(answer)}
        if ccd_vault["sale"].get("id"):
            ccd_vault["sale"]["query"] = query_one(account, str(ccd_vault["sale"]["id"]))
        ccd_vault["deleted"] = v5(account, "DELETE", f"/customers/{ccd_id}")[0]
    vault["stored_as_ccd"] = ccd_vault
    out["vault"] = vault

    # 5. The sandbox's amount trigger, on a bank sale.
    status, answer = v5(account, "POST", "/payments/sale",
                        sale_body("0.50", ref_for("ach-low"), token=tokens[5]))
    out["sale_under_one_dollar"] = {"http": status, **picked(answer)}
    return out


def returns_section(account) -> dict:
    """Returns: which action names the Query API takes, every bank
    transaction on the account, and how a date window reports an action made
    today on a sale older than seven days."""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)

    def stamp(t):
        return t.strftime("%Y%m%d%H%M%S")

    since = stamp(now - timedelta(days=90))
    every = len(query(account, start_date=since).findall("transaction"))
    out = {"transactions_in_90_days_with_no_filter": every, "action_type_filter": {}}
    # A name the Query API does not know may be ignored (every transaction
    # back) rather than refused, so each count is read against `every`.
    for name in ("check_return", "check_late_return", "return", "chargeback", "refund",
                 "not_an_action_type"):
        root = query(account, action_type=name, start_date=since)
        error = (root.findtext("error_response") or "").strip()
        found = root.findall("transaction")
        kinds = sorted({a.findtext("action_type") or "" for n in found
                        for a in n.findall("action")})
        out["action_type_filter"][name] = error or {"found": len(found),
                                                    "action_types_on_them": kinds}
    root = query(account, transaction_type="ck", start_date=stamp(now - timedelta(days=90)))
    checks = [query_facts(n) for n in root.findall("transaction")]
    out["bank_transactions_on_the_account"] = {
        "count": len(checks),
        "conditions": sorted({c.get("condition") or "" for c in checks}),
        "action_types": sorted({a["action_type"] or "" for c in checks for a in c["actions"]}),
    }

    # A settled card sale from 8 to 45 days ago with nothing refunded (a v5
    # refund is a transaction of its own, naming the sale as its original),
    # given a $0.01 refund now; then today's window is asked for it.
    listed = [query_facts(n) for n in query(
        account, start_date=stamp(now - timedelta(days=45))).findall("transaction")]
    refunded = {t.get("original_transaction_id") for t in listed} | {
        t["transaction_id"] for t in listed
        if {"refund", "void", "credit"} & {a["action_type"] for a in t["actions"]}}
    # The sandbox settles nothing (2026-11-14): every approved sale stays
    # pendingsettlement and no settle action is ever listed, so a return,
    # which follows settlement, never comes.
    approved = [t for t in listed if any(a["action_type"] == "sale" and a["success"] == "1"
                                         for a in t["actions"])]
    out["settlement_in_45_days"] = {
        "approved_sales": len(approved),
        "their_conditions": sorted({t.get("condition") or "" for t in approved}),
        "settle_actions": sum(a["action_type"] == "settle" for t in listed for a in t["actions"]),
        "oldest_sale": min((a["date"] for t in approved for a in t["actions"]
                            if a["action_type"] == "sale"), default=""),
    }
    cutoff = stamp(now - timedelta(days=8))
    old = None
    for t in approved:
        sale = [a for a in t["actions"] if a["action_type"] == "sale"]
        if (t.get("transaction_type") == "cc"
                and t.get("condition") in ("complete", "pendingsettlement")
                and sale[0]["date"] < cutoff and t["transaction_id"] not in refunded):
            old = t
            break
    if old is None:
        out["old_sale"] = "no unrefunded card sale from 8 to 45 days ago on the sandbox"
        return out
    status, answer = v5(account, "POST", f"/payments/{old['transaction_id']}/refund",
                        {"amount": "0.01"})
    refund = {"http": status, **picked(answer)}
    time.sleep(5)
    window = query(account, start_date=stamp(now - timedelta(hours=2)),
                   end_date=stamp(datetime.now(timezone.utc) + timedelta(minutes=5)))
    listed = [query_facts(n) for n in window.findall("transaction")]
    as_itself = [t for t in listed if t.get("transaction_id") == old["transaction_id"]]
    as_new = [t for t in listed if t.get("original_transaction_id") == old["transaction_id"]
              or (refund.get("id") and t.get("transaction_id") == str(refund["id"]))]
    out["old_sale"] = {
        "transaction_id": old["transaction_id"],
        "sale_dated": next((a["date"] for a in old["actions"] if a["action_type"] == "sale"), ""),
        "refund_today": refund,
        "todays_window_lists_the_old_transaction": bool(as_itself),
        "its_actions_in_todays_window": as_itself[0]["actions"] if as_itself else [],
        "refund_listed_as_its_own_transaction": as_new[:1],
    }
    return out


def card_section(account, browser, steps) -> dict:
    """The category Collect.js reports for test cards, with and without the
    priced settings; then where a surcharge goes on a v5 sale."""
    import random

    out = {}
    for path, label in (("/card", "as the app configures it"),
                        ("/card-priced", "with price, currency and country")):
        rows, errors, other = [], [], []
        # A page of its own for each card: a second number on one page is
        # looked up against the token Collect.js has just made afresh, which
        # answers empty or with the card before.
        for name, number, cvv in CATEGORY_CARDS:
            page, console = open_proof_page(browser, path)
            try:
                got = card_token(page, number, cvv)
            finally:
                page.close()
            rows.append({"card": name, "lookUpCallback": got["lookup"],
                         "token_response": no_token(got["token"])})
            errors.append(sum(APPLE_PAY_ERROR in m for m in console))
            other += [m for m in console if APPLE_PAY_ERROR not in m]
        out[label] = {"cards": rows, "apple_pay_errors_per_page": errors,
                      "other_console": sorted(set(other))}
    page, _ = open_proof_page(browser, "/card-priced")
    try:
        surcharge_tokens = [card_token(page, TEST_CARD[0], TEST_CARD[2])["token"]["token"]
                            for _ in range(4)]
    finally:
        page.close()
    steps.append(("category for test cards", len(CATEGORY_CARDS)))

    # Where a surcharge is accepted and reported.
    base = random.randint(1000, 1899)
    tries = [
        ("no surcharge (control)", {}, 0),
        ("top-level surcharge, a string", {"top": {"surcharge": "0.30"}}, 30),
        ("order_details.surcharge, a string", {"order": {"surcharge": "0.30"}}, 30),
        ("top-level surcharge, a number", {"top": {"surcharge": 0.30}}, 30),
    ]
    sales = []
    for k, (name, where, extra_cents) in enumerate(tries):
        cents = base + 41 * k + extra_cents
        amount = f"{cents // 100}.{cents % 100:02d}"
        status, answer = v5(account, "POST", "/payments/sale",
                            sale_body(amount, ref_for("fee"), token=surcharge_tokens[k], **where))
        row = {"where": name, "amount_sent": amount, "http": status, **picked(answer)}
        if row.get("id"):
            got_status, got = v5(account, "GET", f"/payments/{row['id']}")
            row["v5_read_back"] = {"http": got_status, **picked(got)}
            row["query_read_back"] = query_one(account, str(row["id"]))
            row["refunded"] = v5(account, "POST", f"/payments/{row['id']}/refund",
                                 {"amount": amount})[0]
        sales.append(row)
        steps.append((f"card sale, {name}", status))
    out["surcharge_sales"] = sales
    return out


def bank_fees() -> dict:
    from playwright.sync_api import sync_playwright

    account = sandbox_account()
    server = serve_proof_pages(account.public_key)
    steps = []
    result = {"environment": account.environment, "api": account.base_url}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            try:
                result["bank"] = bank_section(account, browser, steps)
                result["cards"] = card_section(account, browser, steps)
            finally:
                browser.close()
        result["returns"] = returns_section(account)
    finally:
        server.shutdown()
    result["steps"] = steps
    result["ok"] = all(s[1] is not None for s in steps) and bool(
        result["bank"].get("token_response", {}).get("check"))
    return result


def main():
    # Every mode's mail (invoices, receipts, notices) goes to a catcher of its
    # own for the run (2026-11-13): with no SMTP server on the laptop a send
    # failed, and a proof stopped or missed its receipt.
    mailpit = start_mailpit()
    if mailpit:
        PROOF_ENV.update({"EMAIL_HOST": "127.0.0.1", "EMAIL_PORT": str(MAIL_SMTP)})
    try:
        run_mode()
    finally:
        if mailpit:
            mailpit.terminate()
            mailpit.wait(timeout=10)


def run_mode():
    if "--form-host" in sys.argv:
        # --portal, --autopay or --subscription with Collect.js from this host
        # in place of the Payment Component (2026-11-13).
        host = sys.argv[sys.argv.index("--form-host") + 1]
        if host not in ("secure.nmi.com", "secure.vaultixpay.com"):
            sys.exit("--form-host takes secure.nmi.com or secure.vaultixpay.com")
        PROOF_ENV["NMI_SANDBOX_CARD_FORM_HOST"] = host
    if "--bank-fees" in sys.argv:
        result = bank_fees()
    elif "--refunds" in sys.argv:
        result = refunds_proof()
    elif "--test-mode" in sys.argv:
        result = test_mode_proof()
    elif "--automatic" in sys.argv:
        result = automatic_proof()
    elif "--run-now" in sys.argv:
        result = run_now_proof()
    elif "--beside" in sys.argv:
        result = beside_proof()
    elif "--link-collect" in sys.argv:
        host = sys.argv[sys.argv.index("--link-collect") + 1]
        if host not in ("secure.nmi.com", "secure.vaultixpay.com"):
            sys.exit("--link-collect takes secure.nmi.com or secure.vaultixpay.com")
        result = link_collect(host)
    elif "--collect" in sys.argv:
        host = sys.argv[sys.argv.index("--collect") + 1]
        # The gateway reads the pause switch from the database (2026-11-10).
        fresh_proof_db()
        server = start_server(PROOF_ENV)
        try:
            result = run_collect(host)
        finally:
            server.terminate()
            server.wait(timeout=10)
    elif "--subscription" in sys.argv:
        result = subscription_proof()
    elif "--autopay" in sys.argv:
        result = autopay_proof()
    elif "--portal" in sys.argv or "--link" in sys.argv:
        result = portal(by_link="--link" in sys.argv)
    else:
        fresh_proof_db()
        server = start_server(PROOF_ENV)
        try:
            result = run()
        finally:
            server.terminate()
            server.wait(timeout=10)
    if FORMS_SEEN:
        result["typed_into_collect_js"] = FORMS_SEEN
    if "EMAIL_PORT" in PROOF_ENV and "mail_caught" not in result:
        result["mail_caught"] = caught_mail()
    print(json.dumps(result, indent=2))
    if not result.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
