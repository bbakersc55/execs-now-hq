"""The card gateway (P4, `docs/p4_billing.md` §1). The only door to NMI.

Everything else calls `gateway()` with an `Account` and never holds a key, a
URL or a request body. Four rules hold here, for every caller:

- **Card data never touches the app.** NMI's Payment Component turns a card
  into a one-time `payment_token` in the browser; a stored card is a vault id.
  No method takes a card field, and `refuse_card_fields` stops any body that
  carries one, at any depth, before it leaves.
- **Nothing reaches NMI unless `NMI_LIVE_CALLS` is on**, and never under the
  test runner, whatever the setting. Otherwise `gateway()` is the stub.
- **Production never takes the stub's answer**, and the platform owner can
  pause card payments (`paused()`, 2026-11-10): then nothing that charges or
  stores a card leaves, and nothing is marked paid.
- **No key is ever logged or returned.** An `Account` does not print its keys,
  and errors carry NMI's own message, scrubbed of the account's keys.

Amounts are integer cents here and dollars ("12.34") only at NMI's edge.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

#: The hosts a live account's calls may go to (2026-11-10): NMI's own, and the
#: processor's white-label host for the same gateway. A value from this list
#: and nothing else, chosen by `NMI_API_HOST` (settings refuses any other at
#: start, and `api_host` refuses again here). Each serves v5 REST
#: (`/api/v5`), the Query API (`/api/query.php`) and Collect.js
#: (`/token/Collect.js`).
API_HOSTS = ("secure.nmi.com", "secure.vaultixpay.com")
#: NMI's sandbox gateway, for every sandbox account whatever `NMI_API_HOST`
#: says. Proved 2026-11-10 with the sandbox keys: secure.nmi.com answers
#: "Sandbox accounts must use a sandbox domain", secure.vaultixpay.com "User
#: not found", and Vaultix's token API 404 for the sandbox tokenization key.
SANDBOX_HOST = "sandbox.nmi.com"
#: The host NMI's Payment Component is built for: its card fields, its
#: tokens and its message checks name it and nothing else (@nmipayments/
#: nmi-pay 1.1.1, the latest). Any other host takes Collect.js from itself.
COMPONENT_HOST = "secure.nmi.com"
ENVIRONMENTS = ("sandbox", "live")


def api_host(environment: str) -> str:
    """The host an account's v5 calls and Query API reads go to."""
    from django.conf import settings

    if environment == "sandbox":
        return SANDBOX_HOST
    host = settings.NMI_API_HOST
    if host not in API_HOSTS:
        raise GatewayError(f"NMI_API_HOST {host!r} is not one of {', '.join(API_HOSTS)}.")
    return host


def card_form(environment: str = "live") -> dict:
    """Which card form a page mounts for an account. Live: from
    `NMI_API_HOST`, NMI's Payment Component on NMI's own host, Collect.js
    from the host itself otherwise. Sandbox: the Payment Component always,
    since NMI's host tokenizes sandbox keys and Vaultix's knows none. Either
    form hands the same one-time `payment_token` to the same v5 sale."""
    if environment == "sandbox":
        return {"kind": "component"}
    host = api_host("live")
    if host == COMPONENT_HOST:
        return {"kind": "component"}
    return {"kind": "collect", "script_url": f"https://{host}/token/Collect.js"}


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


#: What a pay button, a pay link and a card form say while payments are paused.
PAUSED_MESSAGE = "Card payments are paused. Please try again later."


class CardPaymentsPaused(GatewayError):
    """Card payments are paused (`paused()`): nothing was sent to NMI and
    nothing was charged. Not a decline: a caller undoes what it wrote and
    shows `PAUSED_MESSAGE`."""

    def __init__(self, message: str = PAUSED_MESSAGE):
        super().__init__(message)


@dataclass(frozen=True)
class Account:
    """One NMI merchant account: the platform's, or one practice's own."""

    environment: str
    private_key: str = field(repr=False)
    public_key: str = field(repr=False)
    #: For messages and logs: "platform" or the practice's id.
    label: str = ""

    def __post_init__(self):
        if self.environment not in ENVIRONMENTS:
            raise GatewayError(f"Unknown NMI environment {self.environment!r}.")

    @property
    def base_url(self) -> str:
        return f"https://{api_host(self.environment)}/api/v5"

    @property
    def query_url(self) -> str:
        return f"https://{api_host(self.environment)}/api/query.php"

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
class Action:
    """One thing that happened to a transaction at NMI, for the daily
    read-back (§4): a sale, a refund, a void, a chargeback… as NMI's Query
    API lists it. Amounts are positive cents; `kind` says which way."""

    transaction_id: str
    action_type: str
    amount_cents: int
    at: object                      # an aware datetime
    reference: str = ""
    original_transaction_id: str = ""
    success: bool = True


@dataclass(frozen=True)
class VaultRecord:
    id: str
    last4: str
    #: MMYY, as NMI returns it.
    card_exp: str
    #: From the masked number's leading digits: NMI's answer names no brand.
    brand: str = ""


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


def stand_in_refused() -> bool:
    """Production never takes an answer from the stub (2026-11-10): with real
    calls off there, every call is refused instead."""
    from django.conf import settings

    return settings.APP_ENVIRONMENT == "production" and not live_calls_allowed()


def held() -> bool:
    """The platform owner's "Pause card payments" switch."""
    from apps.billing.models import CardPaymentHold

    return CardPaymentHold.objects.filter(paused=True).exists()


def paused() -> bool:
    """No charge, and no card saved, may start: the stub would answer in
    production, or the platform owner has paused card payments."""
    return stand_in_refused() or held()


def paused_reason() -> str:
    """"off" (production with real calls off), "held" (the switch), or ""."""
    if stand_in_refused():
        return "off"
    return "held" if held() else ""


def gateway():
    """NMI itself when real calls are allowed, else the stub; never the stub
    in production. While the switch is on, anything that charges or stores a
    card is refused and the read-only calls still answer."""
    if live_calls_allowed():
        from apps.billing.gateway.nmi import NmiGateway

        inner = NmiGateway()
    elif stand_in_refused():
        return RefusingGateway()
    else:
        from apps.billing.gateway.stub import StubGateway

        inner = StubGateway.shared()
    return HeldGateway(inner) if held() else inner


class RefusingGateway:
    """Production with real calls off: every call refused, nothing answered."""

    def __getattr__(self, name):
        def refuse(*args, **kwargs):
            raise CardPaymentsPaused()
        return refuse


class HeldGateway:
    """The switch is on: a sale, a refund or a card stored is refused before
    it leaves; reads (the connection test, lookups, the read-back) and a
    card's deletion pass through to the gateway underneath."""

    MOVES = frozenset({"sale", "refund", "vault_add"})

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        if name in self.MOVES:
            def refuse(*args, **kwargs):
                raise CardPaymentsPaused()
            return refuse
        return getattr(self._inner, name)


def mode() -> str:
    """"nmi", "stub" or "off" (production with real calls off), for a screen
    to say which one answers."""
    if live_calls_allowed():
        return "nmi"
    return "off" if stand_in_refused() else "stub"


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
