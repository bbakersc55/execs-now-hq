"""Bank feeds against Plaid's sandbox, through the app's own provider code
(`apps/finance/bankfeeds/providers/plaid.py`; docs/p6_bank_feeds.md).

    .venv/bin/python scripts/plaid_proof.py

1. Makes a sandbox public token for First Platypus Bank (ins_109508) with
   Plaid's test login user_good / pass_good, transactions, 365 days. This is
   the step Plaid Link does in the browser.
2. Exchanges it server-side, as "Connect a bank" does.
3. Reads the accounts and their balances (/accounts/get).
4. Two sync passes (/transactions/sync): the first from no cursor, waiting
   for the sandbox to finish its first pull; the second from the cursor the
   first one ended with.
5. Removes the item at Plaid, as Disconnect does.

Prints counts, names and masks only: never a key, a token, an item id or a
cursor. Refuses unless PLAID_ENVIRONMENT is sandbox. Writes nothing to any
database. Never calls /transactions/refresh.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402

from apps.finance.bankfeeds.providers.base import ProviderError  # noqa: E402
from apps.finance.bankfeeds.providers.plaid import (  # noqa: E402
    DAYS_REQUESTED, PlaidProvider, configured,
)

INSTITUTION = "ins_109508"          # First Platypus Bank, Plaid's sandbox bank
#: How long the first pass waits for the sandbox's first pull.
READY_WAIT_SECONDS = 90


def say(text: str) -> None:
    print(text, flush=True)


def sandbox_public_token(provider: PlaidProvider) -> str:
    from plaid.model.products import Products
    from plaid.model.sandbox_public_token_create_request import (
        SandboxPublicTokenCreateRequest,
    )
    from plaid.model.sandbox_public_token_create_request_options import (
        SandboxPublicTokenCreateRequestOptions,
    )
    from plaid.model.sandbox_public_token_create_request_options_transactions import (
        SandboxPublicTokenCreateRequestOptionsTransactions,
    )

    made = provider._call("sandbox_public_token_create", SandboxPublicTokenCreateRequest(
        institution_id=INSTITUTION, initial_products=[Products("transactions")],
        options=SandboxPublicTokenCreateRequestOptions(
            override_username="user_good", override_password="pass_good",
            transactions=SandboxPublicTokenCreateRequestOptionsTransactions(
                days_requested=DAYS_REQUESTED))))
    return made["public_token"]


def describe(changes) -> str:
    pending = sum(1 for t in changes.added if t.pending)
    money_in = sum(t.amount_cents for t in changes.added if t.direction == "in")
    money_out = sum(t.amount_cents for t in changes.added if t.direction == "out")
    categorized = sum(1 for t in changes.added if t.bank_category)
    return (f"{changes.pages} page(s): {len(changes.added)} added ({pending} pending, "
            f"{categorized} with a category; in ${money_in / 100:,.2f}, "
            f"out ${money_out / 100:,.2f}), {len(changes.modified)} modified, "
            f"{len(changes.removed)} removed")


def main() -> int:
    if settings.PLAID_ENVIRONMENT != "sandbox":
        say("Refused: PLAID_ENVIRONMENT is not sandbox. This proof runs on the sandbox only.")
        return 2
    if not configured():
        say("Refused: PLAID_CLIENT_ID and PLAID_SECRET are not both set in .env.")
        return 2
    provider = PlaidProvider()
    token = ""
    try:
        say(f"1. Sandbox public token for {INSTITUTION} (user_good / pass_good, "
            f"{DAYS_REQUESTED} days) ...")
        public = sandbox_public_token(provider)
        say("   made.")
        say("2. Exchange, server-side ...")
        linked = provider.exchange(public)
        token = linked.access_token
        say(f"   linked: {linked.institution_name or '(no name)'} "
            f"({linked.institution_id or 'no id'}).")
        say("3. Accounts and balances ...")
        for account in provider.accounts(token):
            balance = ("—" if account.balance_cents is None
                       else f"${account.balance_cents / 100:,.2f}")
            say(f"   {account.name} ·· {account.mask}  {account.type}/{account.subtype}  "
                f"{balance} {account.currency}")
        say("4. Sync, first pass (from no cursor) ...")
        started, first = time.monotonic(), None
        while True:
            first = provider.changes(token, "")
            if first.added or time.monotonic() - started > READY_WAIT_SECONDS:
                break
            say("   the sandbox has not finished its first pull; asking again in 5 s ...")
            time.sleep(5)
        say(f"   first pass: {describe(first)}.")
        if first.added:
            sample = first.added[0]
            say(f"   e.g. {sample.on_date} {sample.direction} "
                f"${sample.amount_cents / 100:,.2f} \"{sample.description}\" "
                f"[{sample.bank_category or 'no category'}]")
        say("   Sync, second pass (from the first pass's cursor) ...")
        second = provider.changes(token, first.cursor)
        say(f"   second pass: {describe(second)}.")
        ok = bool(first.added) and first.cursor and second.cursor
        say("RESULT: " + ("passed — the token exchanged, the accounts read and two "
                          "sync passes carried the cursor." if ok else
                          "FAILED — see the counts above."))
        return 0 if ok else 1
    except ProviderError as exc:
        say(f"RESULT: FAILED — Plaid said {exc.code or 'an error'}: {exc}")
        return 1
    finally:
        if token:
            try:
                provider.remove(token)
                say("5. Item removed at Plaid.")
            except ProviderError as exc:
                say(f"5. Item removal failed: {exc.code or exc}")


if __name__ == "__main__":
    sys.exit(main())
