"""P16's proof (docs/p16_card_page_scripts.md): with the card page policy
enforced, both card forms still load and produce a token on all five card
screens, in headless Chrome against NMI's sandbox, on the laptop.

    .venv/bin/python scripts/card_pages_proof.py

**Laptop only, sandbox only, no payment.** It builds this tree's frontend as
production does (with the entry script's integrity hash), makes the
throwaway database `execsnowhq_nmi_proof` afresh (never `execsnowhq_local`),
sets up the sandbox proof practice (`manage.py nmi_proof_setup`), and runs
the server built from this tree twice: once with NMI's Payment Component,
once with Collect.js from secure.nmi.com (`NMI_SANDBOX_CARD_FORM_HOST`). On
each of the five screens it types NMI's published test card into the
gateway's frames and presses the button; the browser's request carrying the
one-time token is caught at the server's door and answered "nothing charged
or saved", so no sale and no vault record is made. Every policy violation the
browser raises is recorded; there must be none.

It also proves:
- each page's response carries the enforced policy (not report-only);
- the bank page carries the bank policy and Plaid's script loads there;
- moving inside the app from that bank page to a card screen reloads the page
  as a card page (Plaid gone), where the card form then works;
- a script from elsewhere (Plaid's) injected into a card page is blocked;
- Collect.js from the white-label host (secure.vaultixpay.com) loads under
  the policy with no violation (the sandbox key is unknown there, so no token);
- the daily check reads the real built pages: every script, the Payment
  Component's chunk and Collect.js included, and finds them as approved.

Prints the results as JSON and keeps them, with a screenshot of each screen,
in ~/enhq-walks/card-page-scripts/.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nmi_token_proof as base  # noqa: E402

OUT = Path.home() / "enhq-walks" / "card-page-scripts"
PLAID = "https://cdn.plaid.com/link/v2/stable/link-initialize.js"
#: Collect.js asks for it every time it starts; the policy blocks it, as
#: docs/card_page_scripts.md says. Counted apart, as expected.
APPLE = "https://applepay.cdn-apple.com/jsapi/"
WATCH = """
window.__csp = [];
document.addEventListener("securitypolicyviolation", (e) => window.__csp.push({
  directive: e.effectiveDirective, blocked: e.blockedURI, disposition: e.disposition,
  source: e.sourceFile, line: e.lineNumber}));
"""


def env(form: str) -> dict:
    extra = dict(base.PROOF_ENV)
    if form == "collect":
        extra["NMI_SANDBOX_CARD_FORM_HOST"] = "secure.nmi.com"
    elif form == "white-label":
        extra["NMI_SANDBOX_CARD_FORM_HOST"] = "secure.vaultixpay.com"
    return extra


class Tokens:
    """Each request that carries a payment token, caught and answered."""

    def __init__(self):
        self.seen: list[dict] = []

    def handle(self, route, request):
        body = request.post_data or ""
        if request.method == "POST" and "payment_token" in body:
            token = json.loads(body).get("payment_token", "")
            self.seen.append({"path": re.sub(r"/pay/[^/]+", "/pay/…", request.url.split(
                "127.0.0.1")[-1]), "token_length": len(token), "token_kind": token[:4] + "…"})
            route.fulfill(status=400, content_type="application/json", body=json.dumps(
                {"detail": "Proof: the token reached the server; nothing was charged or saved."}))
            return
        route.continue_()


def page_for(context, tokens):
    page = context.new_page()
    page.add_init_script(WATCH)
    page.route("**/api/**", tokens.handle)
    return page


def policy_of(response) -> dict:
    h = response.headers
    csp = h.get("content-security-policy", "")
    return {"enforced": bool(csp), "report_only": "content-security-policy-report-only" in h,
            "plaid_allowed": PLAID in csp, "script_src": next(
                (p.strip() for p in csp.split(";") if p.strip().startswith("script-src")), "")}


def screen(page, tokens, name, *, open_it, button, results):
    """Open a card screen, type the test card, press the button, and wait
    for the token at the server's door."""
    before = len(tokens.seen)
    started = time.time()
    try:
        response = open_it(page)
        base.fill_card(page, button=button)
        for _ in range(240):
            if len(tokens.seen) > before:
                break
            page.wait_for_timeout(250)
        seen = page.evaluate("window.__csp")
        expected = [v for v in seen if (v["blocked"] or "").startswith(APPLE)
                    and (v["source"] or "").endswith("/token/Collect.js")]
        violations = [v for v in seen if v not in expected]
        meta = page.evaluate("document.querySelector('meta[name=enhq-page-policy]')"
                             "?.content ?? null")
        form = "collect" if page.evaluate(
            "!!document.querySelector('script[src$=\"/token/Collect.js\"]')") else "component"
        page.screenshot(path=str(OUT / f"{name}.png"), full_page=False)
    except Exception as exc:                               # noqa: BLE001
        results.append({"screen": name, "ok": False, "error": f"{type(exc).__name__}: {exc}"[:400]})
        page.screenshot(path=str(OUT / f"{name}-failed.png"), full_page=False)
        return
    token = tokens.seen[-1] if len(tokens.seen) > before else None
    row = {"screen": name, "form": form, "page_policy": meta,
           "policy": policy_of(response) if response is not None else None,
           "token": token, "violations": violations,
           "expected_blocks": [v["blocked"] for v in expected],
           "seconds": round(time.time() - started, 1)}
    row["ok"] = bool(token and token["token_length"] > 10 and not violations and meta == "card"
                     and row["policy"] and row["policy"]["enforced"]
                     and not row["policy"]["report_only"] and not row["policy"]["plaid_allowed"])
    results.append(row)


def shell(snippet: str, form: str) -> dict:
    return json.loads(base.manage("shell", "-c", snippet, env_extra=env(form))
                      .strip().splitlines()[-1])


PAY_LINK = """
import json
from django.db import transaction
from apps.billing import pay_links
from apps.billing.models import ClientInvoice
from apps.tenancy.context import tenant_context
inv = ClientInvoice.all_objects.get(pk="{id}")
with tenant_context(inv.tenant_id), transaction.atomic():
    locked = ClientInvoice.all_objects.select_for_update().get(pk=inv.pk)
    pay_links.ensure(locked)
link = pay_links.url_of(ClientInvoice.all_objects.get(pk=inv.pk))
print(json.dumps({{"pay_path": link[link.index("/pay/"):] if link else ""}}))
"""

NO_SCHEDULE = """
import json
from apps.billing.models import ClientInvoiceSchedule
n = ClientInvoiceSchedule.all_objects.count()
ClientInvoiceSchedule.all_objects.all().delete()
print(json.dumps({"schedules_removed": n}))
"""

FACTS = """
import json
from apps.billing.models import (ClientPayment, ClientPaymentMethod, PaymentAttempt,
    PracticeSubscription)
print(json.dumps({"payment_attempts": PaymentAttempt.all_objects.count(),
    "payments": ClientPayment.all_objects.count(),
    "cards_on_file": ClientPaymentMethod.all_objects.count(),
    "subscription_cards": PracticeSubscription.all_objects.exclude(nmi_vault_id="").count()}))
"""


def recurring(owner, first) -> None:
    """The practice owner's clicks: a recurring invoice that bills
    automatically, waiting for the client to agree (and save its card)."""
    owner.goto(f"{base.BASE}/invoices", wait_until="domcontentloaded", timeout=90000)
    owner.get_by_role("button", name="New recurring invoice").click(timeout=90000)
    form = owner.get_by_role("dialog", name="The new recurring invoice")
    form.get_by_label("Client company for the recurring invoice").select_option(
        label="Proof Client Co")
    form.get_by_label("Recurring invoice addressed to").select_option(
        label="Casey Client", timeout=30000)
    form.get_by_label("Bill automatically").check()
    form.get_by_label("Billing day 1", exact=True).fill("1")
    form.get_by_label("First billing date").fill(first)
    form.get_by_label("Description of line 1").fill("Operations support (proof)")
    form.get_by_label("Price of line 1").fill("75")
    form.get_by_role("button", name="Save the recurring invoice").click()
    try:
        owner.get_by_text("Waiting for Proof Client Co to agree").wait_for(timeout=60000)
    except Exception:
        owner.screenshot(path=str(OUT / "recurring-failed.png"), full_page=True)
        raise


def run_form(browser, form: str, setup: dict, session: dict) -> list[dict]:
    from datetime import date, timedelta  # noqa: F401

    results: list[dict] = []
    server = base.start_server(env(form))
    try:
        tokens = Tokens()
        sign_in = json.loads(base.manage("nmi_proof_setup", "--client-link",
                                         env_extra=env(form)).strip().splitlines()[-1])
        # 1. The pay link, signed in as no one.
        anyone = browser.new_context()
        page = page_for(anyone, tokens)
        screen(page, tokens, f"{form}-1-pay-link",
               open_it=lambda p: p.goto(base.BASE + setup["pay_path"],
                                        wait_until="domcontentloaded", timeout=90000),
               button=re.compile(r"^Pay \$"), results=results)
        # A script from elsewhere, put on a card page: blocked.
        page.evaluate(f"""() => {{ const s = document.createElement("script");
            s.src = "{PLAID}"; document.head.appendChild(s); }}""")
        page.wait_for_timeout(3000)
        blocked = [v for v in page.evaluate("window.__csp") if "plaid" in (v["blocked"] or "")]
        results.append({"screen": f"{form}-plaid-put-on-a-card-page",
                        "blocked": blocked, "plaid_ran": page.evaluate("!!window.Plaid"),
                        "ok": bool(blocked) and not page.evaluate("!!window.Plaid")})
        anyone.close()
        # 2 and 3. Signed in as the client owner: paying an invoice, saving a card.
        client = browser.new_context()
        page = page_for(client, tokens)
        page.goto(base.BASE + sign_in["sign_in_path"], wait_until="domcontentloaded",
                  timeout=90000)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url(re.compile(r"/invoices"), timeout=90000)

        def pay_invoice(p):
            response = p.goto(base.BASE + "/invoices", wait_until="domcontentloaded",
                              timeout=90000)
            p.get_by_role("button", name=f"Pay invoice {setup['number']}").click(timeout=90000)
            return response
        screen(page, tokens, f"{form}-2-in-app-payment", open_it=pay_invoice,
               button=re.compile(r"^Pay \$"), results=results)

        def save_card(p):
            response = p.goto(base.BASE + "/invoices", wait_until="domcontentloaded",
                              timeout=90000)
            p.get_by_role("button", name="Save a card").click(timeout=90000)
            return response
        screen(page, tokens, f"{form}-3-saving-a-card", open_it=save_card,
               button=re.compile(r"^Save this card$"), results=results)
        # 4. Automatic billing's card: a recurring invoice waiting to be agreed.
        owner_context = browser.new_context()
        owner_context.add_cookies([{"name": session["cookie"], "value": session["session"],
                                    "url": base.BASE}])
        first = (date.today().replace(day=1) + timedelta(days=32)).replace(day=1)
        made = True
        try:
            recurring(owner_context.new_page(), first.isoformat())
        except Exception as exc:                           # noqa: BLE001
            made = False
            results.append({"screen": f"{form}-4-auto-pay-setup", "ok": False,
                            "error": f"the recurring invoice wasn't made: {exc}"[:400]})

        def automatic(p):
            response = p.goto(base.BASE + "/invoices", wait_until="domcontentloaded",
                              timeout=90000)
            p.get_by_text("First, save the card it is charged to.").wait_for(timeout=90000)
            return response
        if made:
            screen(page, tokens, f"{form}-4-auto-pay-setup", open_it=automatic,
                   button=re.compile(r"^Save this card$"), results=results)
        shell(NO_SCHEDULE, form)
        client.close()
        # 5. The practice's own subscription card, reached by moving inside
        # the app from a bank page: the page reloads as a card page.
        page = page_for(owner_context, tokens)
        bank = page.goto(base.BASE + "/finance/import", wait_until="domcontentloaded",
                         timeout=90000)
        page.wait_for_timeout(1500)
        page.evaluate(f"""() => new Promise((ok) => {{ const s = document.createElement("script");
            s.src = "{PLAID}"; s.onload = ok; s.onerror = ok; document.head.appendChild(s); }})""")
        bank_facts = {"policy": policy_of(bank),
                      "page_policy": page.evaluate("document.querySelector("
                                                   "'meta[name=enhq-page-policy]').content"),
                      "plaid_loaded": page.evaluate("!!window.Plaid"),
                      "violations": page.evaluate("window.__csp")}
        page.evaluate("window.__marker = 'the bank page'")
        holder: dict = {}

        def move_inside(p):
            # React Router's own move (no request to the server); the app
            # must then reload the page itself, as a card page.
            with p.expect_response(lambda r: r.request.resource_type == "document"
                                   and r.url.endswith("/settings/billing"),
                                   timeout=60000) as reloaded:
                p.evaluate("""() => { window.history.pushState({}, "", "/settings/billing");
                    window.dispatchEvent(new PopStateEvent("popstate")); }""")
            p.wait_for_load_state("domcontentloaded")
            add = p.get_by_role("button", name="Add a card")
            add.wait_for(timeout=90000)
            holder["reloaded"] = p.evaluate("window.__marker === undefined")
            holder["plaid_after"] = p.evaluate("!!window.Plaid")
            add.click()
            p.locator("[data-testid=card-form]").scroll_into_view_if_needed(timeout=30000)
            return reloaded.value
        screen(page, tokens, f"{form}-5-subscription-card-from-a-bank-page",
               open_it=move_inside, button=re.compile(r"^Save this card$"), results=results)
        last = results[-1]
        last["from_the_bank_page"] = {**bank_facts, **holder}
        last["ok"] = bool(last.get("ok") and bank_facts["policy"]["plaid_allowed"]
                          and bank_facts["page_policy"] == "bank"
                          and bank_facts["plaid_loaded"] and not bank_facts["violations"]
                          and holder.get("reloaded") and not holder.get("plaid_after"))
        owner_context.close()
    finally:
        server.terminate()
        server.wait(timeout=10)
    return results


def white_label(browser, setup) -> dict:
    """Collect.js from the processor's white-label host: it loads under the
    policy with no violation. The sandbox key is unknown there, so no token."""
    server = base.start_server(env("white-label"))
    try:
        context = browser.new_context()
        page = page_for(context, Tokens())
        response = page.goto(base.BASE + setup["pay_path"], wait_until="domcontentloaded",
                             timeout=90000)
        page.wait_for_timeout(12000)
        facts = {"policy": policy_of(response),
                 "collect_js_loaded": page.evaluate("!!window.CollectJS"),
                 "script": page.evaluate("document.querySelector('script[src$="
                                         "\"/token/Collect.js\"]')?.src ?? null"),
                 "frames": page.evaluate("[...document.querySelectorAll('iframe')]"
                                         ".map(f => new URL(f.src).host)"),
                 "violations": [v for v in page.evaluate("window.__csp")
                                if not ((v["blocked"] or "").startswith(APPLE)
                                        and (v["source"] or "").endswith("/token/Collect.js"))],
                 "expected_blocks": [v["blocked"] for v in page.evaluate("window.__csp")
                                     if (v["blocked"] or "").startswith(APPLE)]}
        page.screenshot(path=str(OUT / "white-label-collect-js.png"))
        context.close()
    finally:
        server.terminate()
        server.wait(timeout=10)
    facts["ok"] = bool(facts["collect_js_loaded"] and not facts["violations"]
                       and "secure.vaultixpay.com" in (facts["script"] or ""))
    return facts


def daily_check_reads_the_real_pages() -> dict:
    server = base.start_server(env("component"))
    try:
        approved = base.manage("card_pages", "approve", "--note", "proof", "--by", "proof",
                               "--base", base.BASE, env_extra=env("component"))
        checked = base.manage("card_pages", "check", "--base", base.BASE, "--no-alert",
                              env_extra=env("component"))
        state = json.loads(base.manage("card_pages", "state", "--base", base.BASE,
                                       env_extra=env("component")))
    finally:
        server.terminate()
        server.wait(timeout=10)
    scripts = state["scripts"]
    return {"approve": approved.strip().splitlines(), "check": checked.strip().splitlines(),
            "scripts": {u.replace(base.BASE, ""): v["bytes"] for u, v in scripts.items()},
            "entry_integrity": state["pages"]["/invoices"]["integrity"],
            "ok": checked.strip().startswith("As approved") and len(scripts) >= 2
            and all(v["status"] == 200 for v in scripts.values())}


def main():
    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    base.build_frontend()
    base.fresh_proof_db()
    setup = json.loads(base.manage("nmi_proof_setup", env_extra=env("component"))
                       .strip().splitlines()[-1])
    if not setup.get("pay_path"):
        setup.update(shell(PAY_LINK.format(id=setup["invoice_id"]), "component"))
    session = json.loads(base.manage("nmi_proof_setup", "--subscription",
                                     env_extra=env("component")).strip().splitlines()[-1])
    out = {"screens": []}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        for form in ("component", "collect"):
            out["screens"] += run_form(browser, form, setup, session)
        out["white_label"] = white_label(browser, setup)
        browser.close()
    out["daily_check"] = daily_check_reads_the_real_pages()
    out["nothing_charged_or_saved"] = shell(FACTS, "component")
    out["ok"] = (all(r.get("ok") for r in out["screens"]) and out["white_label"]["ok"]
                 and out["daily_check"]["ok"]
                 and not any(out["nothing_charged_or_saved"].values()))
    (OUT / "proof.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))
    sys.exit(0 if out["ok"] else 1)


if __name__ == "__main__":
    main()
