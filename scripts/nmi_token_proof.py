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

**--link-collect HOST** (2026-11-13) is --link with the card form a live
white-label account gets: the real pay page, built from this tree, loads
Collect.js from HOST with the page's own configuration
(`NMI_SANDBOX_CARD_FORM_HOST`, laptop only). On secure.nmi.com the sandbox
key works there, so it goes all the way: NMI's test card typed into
Collect.js's frames, a real token, a real sandbox sale, the Paid page, the
receipt and the payment on the invoice. On secure.vaultixpay.com the sandbox
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
      const boxes = [...document.querySelectorAll('[id^="cj-"]')];
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
    if "--link-collect" in sys.argv:
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
