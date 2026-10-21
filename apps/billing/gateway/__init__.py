"""The card gateway (P4, `docs/p4_billing.md` §1). The only door to NMI.

Everything else calls `gateway()` with an `Account` and never holds a key, a
URL or a request body. Three rules hold here, for every caller:

- **Card data never touches the app.** NMI's Payment Component turns a card
  into a one-time `payment_token` in the browser; a stored card is a vault id.
  No method takes a card field, and `refuse_card_fields` stops any body that
  carries one, at any depth, before it leaves.
- **Nothing reaches NMI unless `NMI_LIVE_CALLS` is on**, and never under the
  test runner, whatever the setting. Otherwise `gateway()` is the stub.
- **No key is ever logged or returned.** An `Account` does not print its keys,
  and errors carry NMI's own message, scrubbed of the account's keys.

Amounts are integer cents here and dollars ("12.34") only at NMI's edge.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

#: NMI's v5 REST API, by environment. Proved against the sandbox 2026-10-21.
BASE_URLS = {
    "sandbox": "https://sandbox.nmi.com/api/v5",
    "live": "https://secure.nmi.com/api/v5",
}

#: NMI's Query API, read-only. Used for one thing v5 cannot do: find a
#: transaction by our reference when the sale's answer was lost (v5 has no
#: search). It takes the same private key and never charges. Proved
#: 2026-10-21; a sandbox account must use the sandbox host.
QUERY_URLS = {
    "sandbox": "https://sandbox.nmi.com/api/query.php",
    "live": "https://secure.nmi.com/api/query.php",
}

#: Field names that hold card or bank data, in NMI's v5 and classic APIs. A
#: body carrying any of them is refused before it is sent.
CARD_FIELDS = frozenset({
    "card_number", "card_exp", "card_cvv", "ccnumber", "ccexp", "cvv",
    "account_number", "routing_number", "checkaccount", "checkaba", "checkname",
})


class GatewayError(Exception):
    """NMI refused, failed, or could not be reached. The message is safe to
    show to the practice owner: it never contains a key."""


class GatewayRefused(GatewayError):
    """NMI answered and refused the request (4xx): nothing was charged.
    `code` is NMI's own, e.g. "E_DUPLICATE" for the same card and amount
    again within minutes."""

    def __init__(self, message: str, code: str = ""):
        super().__init__(message)
        self.code = code

    @property
    def duplicate(self) -> bool:
        return self.code == "E_DUPLICATE"


class GatewayUnreachable(GatewayError):
    """No answer, or not a usable one (a timeout, a dropped connection, a 5xx):
    a charge may or may not have been made. Never retried; looked up instead."""


class CardDataRefused(GatewayError):
    """A request body carried a card or bank field. A bug, never a user error."""


class LiveCallsRefused(GatewayError):
    """A real call was attempted without `NMI_LIVE_CALLS`, or under test."""


@dataclass(frozen=True)
class Account:
    """One NMI merchant account: the platform's, or one practice's own."""

    environment: str
    private_key: str = field(repr=False)
    public_key: str = field(repr=False)
    #: For messages and logs: "platform" or the practice's id.
    label: str = ""

    def __post_init__(self):
        if self.environment not in BASE_URLS:
            raise GatewayError(f"Unknown NMI environment {self.environment!r}.")

    @property
    def base_url(self) -> str:
        return BASE_URLS[self.environment]

    @property
    def query_url(self) -> str:
        return QUERY_URLS[self.environment]

    def scrub(self, text: str) -> str:
        for key in (self.private_key, self.public_key):
            if key:
                text = text.replace(key, "[key]")
        return text


@dataclass(frozen=True)
class Billing:
    """The cardholder's name on a vault record. Nothing else is sent."""

    first_name: str
    last_name: str


@dataclass(frozen=True)
class Transaction:
    id: str
    approved: bool
    #: NMI's: pendingsettlement, failed, complete, …
    status: str
    response_code: str
    response_text: str
    #: Negative for a refund, as NMI reports it.
    amount_cents: int
    card_type: str = ""
    last4: str = ""
    reference: str = ""


@dataclass(frozen=True)
class VaultRecord:
    id: str
    last4: str
    #: MMYY, as NMI returns it.
    card_exp: str


@dataclass(frozen=True)
class ConnectionResult:
    ok: bool
    detail: str


def refuse_card_fields(body) -> None:
    """Raise if any key, at any depth, names card or bank data."""
    if isinstance(body, dict):
        for key, value in body.items():
            if str(key).lower() in CARD_FIELDS:
                raise CardDataRefused(f"A request to NMI carried the card field {key!r}. "
                                      "Card data never passes through this app.")
            refuse_card_fields(value)
    elif isinstance(body, (list, tuple)):
        for value in body:
            refuse_card_fields(value)


def under_test() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ


def live_calls_allowed() -> bool:
    from django.conf import settings

    return bool(settings.NMI_LIVE_CALLS) and not under_test()


def gateway():
    """NMI itself when real calls are allowed, else the stub."""
    if live_calls_allowed():
        from apps.billing.gateway.nmi import NmiGateway

        return NmiGateway()
    from apps.billing.gateway.stub import StubGateway

    return StubGateway.shared()


def mode() -> str:
    """"nmi" or "stub", for a screen to say which one answers."""
    return "nmi" if live_calls_allowed() else "stub"


def platform_account() -> Account:
    """Noble Rose LLC's account, from the environment only (§1.2). It never
    reads a `tenant_secret`."""
    from django.conf import settings

    if not settings.NMI_PRIVATE_API_KEY:
        raise GatewayError("The platform's NMI keys are not set.")
    return Account(environment=settings.NMI_ENVIRONMENT,
                   private_key=settings.NMI_PRIVATE_API_KEY,
                   public_key=settings.NMI_PUBLIC_TOKENIZATION_KEY, label="platform")


def to_dollars(cents: int) -> str:
    if not isinstance(cents, int) or isinstance(cents, bool):
        raise GatewayError("Amounts are integer cents.")
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{cents // 100}.{cents % 100:02d}"


def to_cents(dollars) -> int:
    from decimal import Decimal

    return int((Decimal(str(dollars)) * 100).quantize(Decimal("1")))
