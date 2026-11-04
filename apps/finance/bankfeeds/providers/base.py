"""What every bank-data provider gives the rest of the app.

Nothing outside `providers/` knows which provider a connection uses beyond its
name. Money is integer cents; a transaction's amount is always positive and
its `direction` says which way it went, as a Finance entry's does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


class ProviderError(Exception):
    """The provider refused or failed. `code` is its own error code where it
    gave one (ITEM_LOGIN_REQUIRED, ...); the message never carries a secret."""

    def __init__(self, message: str, code: str = ""):
        super().__init__(message)
        self.code = code


class NotConfigured(ProviderError):
    pass


class WebhookRefused(ProviderError):
    """The webhook did not prove it came from the provider."""


#: The codes that mean the bank login itself needs the owner: Reconnect, in
#: the provider's update mode, fixes them.
LOGIN_CODES = ("ITEM_LOGIN_REQUIRED", "PENDING_DISCONNECT", "PENDING_EXPIRATION")


@dataclass
class Account:
    provider_account_id: str
    name: str = ""
    official_name: str = ""
    mask: str = ""
    type: str = ""
    subtype: str = ""
    #: For a bank account what it holds; for a card what is owed.
    balance_cents: int | None = None
    available_cents: int | None = None
    currency: str = ""


@dataclass
class Transaction:
    provider_transaction_id: str
    provider_account_id: str
    on_date: date
    amount_cents: int
    direction: str               # "in" or "out"
    description: str = ""
    bank_category: str = ""
    pending: bool = False
    #: A posted transaction's pending one, where it had one.
    pending_transaction_id: str = ""


@dataclass
class Changes:
    """Everything since a cursor, every page of it, and the cursor after."""

    added: list[Transaction] = field(default_factory=list)
    modified: list[Transaction] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    cursor: str = ""
    pages: int = 0


@dataclass
class Linked:
    access_token: str
    item_id: str
    institution_id: str = ""
    institution_name: str = ""


@dataclass
class Event:
    """A webhook, read. `kind`: "sync" (new transactions to fetch),
    "attention" (the login needs the owner), "repaired", or "other"."""

    kind: str
    item_id: str
    code: str = ""
    detail: str = ""


class Provider:
    """The interface. Each method is one thing the app asks of a provider."""

    name = ""

    def link_token(self, *, user_ref: str, webhook_url: str,
                   access_token: str = "") -> str:
        """A token for the provider's browser widget. With an access token,
        update mode: the same login, repaired."""
        raise NotImplementedError

    def exchange(self, public_token: str) -> Linked:
        raise NotImplementedError

    def accounts(self, access_token: str) -> list[Account]:
        """The login's accounts, with their balances."""
        raise NotImplementedError

    def changes(self, access_token: str, cursor: str) -> Changes:
        """Everything since `cursor` ("" for the beginning), all pages."""
        raise NotImplementedError

    def remove(self, access_token: str) -> None:
        """End the login at the provider. Polling stops with it."""
        raise NotImplementedError

    def read_webhook(self, body: bytes, headers) -> Event:
        """Verify that the provider sent it, then read it. Raises
        WebhookRefused for anything unproven."""
        raise NotImplementedError
