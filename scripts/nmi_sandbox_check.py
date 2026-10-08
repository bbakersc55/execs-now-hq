"""P4 Phase 0: what NMI's sandbox actually does (`docs/p4_billing.md` §0, §6).

The spec assumes eight things about NMI (A1–A8), written from its public
documentation. This asks the sandbox about the ones that can be asked from a
script, prints what came back, and removes everything it made:

    .venv/bin/python scripts/nmi_sandbox_check.py            # every step
    .venv/bin/python scripts/nmi_sandbox_check.py vault      # one step

**Not product code, and not run by any test.** It reads only the three
`NMI_SANDBOX_*` names from the laptop's `.env`, and refuses to start if a live
name (`NMI_PLATFORM_*`) is set beside them, so it can never be pointed at a
real account by accident. It uses NMI's published test card and a test email
address; nothing here is a real person's.

The steps, and the assumption each one tests:

    vault         A2  store a card, get a vault id back
    sale          A2  charge that vault record, with our own reference on it
    subscription  A3  a subscription with its own amount, on day 1; then
                      **change its amount**, which the spec could not confirm
    invoice       A4  NMI's hosted invoice: what comes back, and whether its
                      own email can be turned off
    query         A6  read the sale back by id and by our reference
    services      A7  which of Vault, Recurring and Invoicing answered at all

A1 (Collect.js) needs a browser and A5/A8 (webhooks) need an address NMI can
reach; neither is here. The parameter names below are the documentation's as
read on 2026-10-08. **A name that is wrong is itself a finding**: the raw
response is printed for every call so it can be seen.
"""

from __future__ import annotations

import sys
import urllib.parse
import urllib.request
import uuid
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRANSACT = "https://secure.nmi.com/api/transact.php"
QUERY = "https://secure.nmi.com/api/query.php"

#: NMI's published test card. A sandbox account accepts no real one.
TEST_CARD = {"ccnumber": "4111111111111111", "ccexp": "1030", "cvv": "999"}
TEST_PERSON = {"first_name": "Sandbox", "last_name": "Check",
               "email": "sandbox-check@example.invalid"}

SANDBOX = ("NMI_SANDBOX_SECURITY_KEY", "NMI_SANDBOX_TOKENIZATION_KEY",
           "NMI_SANDBOX_WEBHOOK_KEY")
LIVE = ("NMI_PLATFORM_SECURITY_KEY", "NMI_PLATFORM_TOKENIZATION_KEY",
        "NMI_PLATFORM_WEBHOOK_KEY")


def env() -> dict:
    values = {}
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            name, found, value = line.partition("=")
            if found and not name.lstrip().startswith("#"):
                values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def post(url: str, key: str, **fields) -> tuple[dict, str]:
    """One call. Returns the response as fields, and as it arrived (which for
    the Query API is XML, not fields)."""
    body = urllib.parse.urlencode({"security_key": key, **fields}).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=30) as reply:
        raw = reply.read().decode()
    return {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}, raw


def show(title: str, sent: dict, raw: str) -> None:
    safe = {k: ("…" + v[-4:] if k == "ccnumber" else "***" if k == "cvv" else v)
            for k, v in sent.items()}
    print(f"\n--- {title}\n    sent:     {safe}\n    received: {raw[:1500]}")


def call(title: str, key: str, url: str = TRANSACT, **fields) -> dict:
    try:
        parsed, raw = post(url, key, **fields)
    except Exception as exc:  # noqa: BLE001 — a failure to connect is a finding too
        print(f"\n--- {title}\n    FAILED TO CALL: {exc}")
        return {}
    show(title, fields, raw)
    return parsed


def ok(reply: dict) -> bool:
    return reply.get("response") == "1"


def main(steps: list[str]) -> int:
    values = env()
    missing = [name for name in SANDBOX[:1] if not values.get(name)]
    if missing:
        print(f"Not started: {', '.join(missing)} is not set in .env. "
              "Nothing was sent to NMI.")
        return 2
    live = [name for name in LIVE if values.get(name)]
    if live:
        print(f"Not started: a live name is set beside the sandbox ones ({', '.join(live)}). "
              "This script only ever uses a sandbox account. Nothing was sent to NMI.")
        return 2
    key = values["NMI_SANDBOX_SECURITY_KEY"]
    wanted = lambda step: not steps or step in steps  # noqa: E731
    reference = f"sandbox-check-{uuid.uuid4().hex[:10]}"
    findings: list[str] = []
    made = {"vault": "", "subscription": "", "invoice": "", "transaction": ""}

    try:
        if wanted("vault") or wanted("sale") or wanted("subscription"):
            reply = call("A2 vault: store a card", key, customer_vault="add_customer",
                         **TEST_CARD, **TEST_PERSON)
            made["vault"] = reply.get("customer_vault_id", "")
            findings.append(f"A2 vault add: {'OK, id returned' if made['vault'] else 'NO id'}"
                            f" ({reply.get('responsetext', 'no response')})")

        if wanted("sale") and made["vault"]:
            reply = call("A2 sale: charge the vault record, with our reference", key,
                         type="sale", amount="20.00", customer_vault_id=made["vault"],
                         orderid=reference)
            made["transaction"] = reply.get("transactionid", "")
            findings.append(f"A2 sale against the vault: {'OK' if ok(reply) else 'REFUSED'}"
                            f" ({reply.get('responsetext', 'no response')})")

        if wanted("subscription") and made["vault"]:
            first = (date.today().replace(day=1) + timedelta(days=32)).replace(day=1)
            reply = call("A3 subscription: its own amount, monthly, on day 1", key,
                         recurring="add_subscription", plan_payments="0",
                         plan_amount="20.00", month_frequency="1", day_of_month="1",
                         start_date=first.strftime("%Y%m%d"),
                         customer_vault_id=made["vault"], orderid=reference)
            made["subscription"] = reply.get("subscription_id", "")
            findings.append("A3 subscription without a shared plan: "
                            f"{'OK' if made['subscription'] else 'NOT created'}"
                            f" ({reply.get('responsetext', 'no response')})")
            if made["subscription"]:
                reply = call("A3 the open point: change a live subscription's amount", key,
                             recurring="update_subscription",
                             subscription_id=made["subscription"], plan_amount="35.00")
                findings.append("A3 change the amount of a live subscription: "
                                f"{'ACCEPTED' if ok(reply) else 'REFUSED'}"
                                f" ({reply.get('responsetext', 'no response')}). "
                                "Check the amount in the query below, or in NMI's portal.")
                call("A3 read the subscription back", key, QUERY,
                     report_type="recurring", subscription_id=made["subscription"])

        if wanted("invoice"):
            reply = call("A4 invoice: NMI's hosted invoice", key, invoicing="add_invoice",
                         amount="150.00", email=TEST_PERSON["email"], orderid=reference,
                         payment_terms="upon_receipt")
            made["invoice"] = reply.get("invoice_id", "")
            fields = sorted(reply)
            findings.append(f"A4 hosted invoice: {'OK' if made['invoice'] else 'NOT created'}"
                            f" ({reply.get('responsetext', 'no response')}). "
                            f"Fields returned: {fields}. A pay page address among them: "
                            f"{'yes' if any('url' in f.lower() for f in fields) else 'no'}.")
            findings.append("A4 whether NMI's own email can be turned off: NOT ANSWERED by "
                            "this script. It sent one to the test address; look for a "
                            "setting in the portal's Invoicing options.")

        if wanted("query") and made["transaction"]:
            call("A6 query: the sale, by its id", key, QUERY,
                 transaction_id=made["transaction"])
            call("A6 query: the sale, by our reference", key, QUERY, order_id=reference)
            findings.append("A6 query: see the two responses above for the condition "
                            "field and whether our reference found it.")

        if wanted("services"):
            findings.append(
                "A7 services on this account: Vault "
                f"{'answered' if made['vault'] else 'did not answer'}, Recurring "
                f"{'answered' if made['subscription'] else 'did not answer'}, Invoicing "
                f"{'answered' if made['invoice'] else 'did not answer'}.")
    finally:
        # Everything this made, removed, whatever happened above.
        if made["subscription"]:
            call("clean up: cancel the subscription", key, recurring="delete_subscription",
                 subscription_id=made["subscription"])
        if made["invoice"]:
            call("clean up: close the invoice", key, invoicing="close_invoice",
                 invoice_id=made["invoice"])
        if made["transaction"]:
            call("clean up: void the sale", key, type="void",
                 transactionid=made["transaction"])
        if made["vault"]:
            call("clean up: remove the vault record", key, customer_vault="delete_customer",
                 customer_vault_id=made["vault"])

    print("\n=== Findings ===")
    for line in findings:
        print(" - " + line)
    print(" - A1 (card fields in a browser), A5 and A8 (webhooks): not tested here.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
