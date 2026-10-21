"""The stub gateway: what answers whenever real calls to NMI are off, and in
every test, as `fake_claude` stands in for Claude.

It behaves as the sandbox did on 2026-10-21 where that matters to a caller:
under $1.00 is declined, a refund cannot exceed what is left of the sale, a
token is used once. A private key that starts with "bad" fails the
connection test. It refuses card fields exactly as the real one does.
"""

from __future__ import annotations

import itertools

from apps.billing.gateway import (
    Account, Billing, ConnectionResult, GatewayError, Transaction, VaultRecord,
    refuse_card_fields,
)

DECLINE_BELOW_CENTS = 100


class StubGateway:
    _shared = None

    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []
        self.sales: dict[str, dict] = {}
        self.vault: dict[str, dict] = {}
        self.used_tokens: set[str] = set()
        self._ids = itertools.count(1000)

    @classmethod
    def shared(cls) -> "StubGateway":
        if cls._shared is None:
            cls._shared = cls()
        return cls._shared

    @classmethod
    def reset(cls) -> "StubGateway":
        cls._shared = cls()
        return cls._shared

    def _record(self, name: str, account: Account, body: dict):
        refuse_card_fields(body)
        self.calls.append((name, account.label, body))

    def check_connection(self, account: Account) -> ConnectionResult:
        self._record("check_connection", account, {})
        if not account.private_key or account.private_key.startswith("bad"):
            return ConnectionResult(False, "NMI refused the private key. Check that it is the "
                                           f"{account.environment} key for this account.")
        return ConnectionResult(True, f"Connected to the stub gateway ({account.environment}). "
                                      "Nothing reaches NMI on this server.")

    def sale(self, account: Account, *, amount_cents: int, reference: str,
             payment_token: str | None = None, vault_id: str | None = None) -> Transaction:
        if (payment_token is None) == (vault_id is None):
            raise GatewayError("A sale takes a payment token or a vault id, not both.")
        if amount_cents <= 0:
            raise GatewayError("A sale is for more than nothing.")
        self._record("sale", account, {"amount_cents": amount_cents, "reference": reference,
                                       "payment_token": payment_token, "vault_id": vault_id})
        if payment_token is not None:
            self._use(payment_token)
        elif vault_id not in self.vault:
            raise GatewayError("No such customer in the vault.")
        approved = amount_cents >= DECLINE_BELOW_CENTS
        tid = str(next(self._ids))
        self.sales[tid] = {"account": account.label, "amount_cents": amount_cents,
                           "refunded_cents": 0, "reference": reference, "approved": approved}
        return Transaction(id=tid, approved=approved,
                           status="pendingsettlement" if approved else "failed",
                           response_code="100" if approved else "200",
                           response_text="SUCCESS" if approved else "DECLINE",
                           amount_cents=amount_cents, card_type="Visa", last4="1111",
                           reference=reference)

    def refund(self, account: Account, *, transaction_id: str,
               amount_cents: int) -> Transaction:
        self._record("refund", account, {"transaction_id": transaction_id,
                                         "amount_cents": amount_cents})
        sale = self.sales.get(transaction_id)
        if sale is None or sale["account"] != account.label or not sale["approved"]:
            raise GatewayError("Transaction not found")
        if amount_cents <= 0 or sale["refunded_cents"] + amount_cents > sale["amount_cents"]:
            raise GatewayError("Refund amount may not exceed the transaction balance")
        sale["refunded_cents"] += amount_cents
        return Transaction(id=str(next(self._ids)), approved=True, status="pendingsettlement",
                           response_code="100", response_text="SUCCESS",
                           amount_cents=-amount_cents, card_type="Visa", last4="1111",
                           reference=sale["reference"])

    def get_transaction(self, account: Account, transaction_id: str) -> Transaction:
        self._record("get_transaction", account, {"transaction_id": transaction_id})
        sale = self.sales.get(transaction_id)
        if sale is None or sale["account"] != account.label:
            raise GatewayError("Transaction not found")
        return Transaction(id=transaction_id, approved=sale["approved"],
                           status="pendingsettlement" if sale["approved"] else "failed",
                           response_code="100" if sale["approved"] else "200",
                           response_text="SUCCESS" if sale["approved"] else "DECLINE",
                           amount_cents=sale["amount_cents"], card_type="Visa", last4="1111",
                           reference=sale["reference"])

    def vault_add(self, account: Account, *, payment_token: str,
                  billing: Billing) -> VaultRecord:
        self._record("vault_add", account, {"payment_token": payment_token,
                                            "first_name": billing.first_name,
                                            "last_name": billing.last_name})
        self._use(payment_token)
        vid = str(next(self._ids))
        self.vault[vid] = {"account": account.label}
        return VaultRecord(id=vid, last4="1111", card_exp="1029")

    def vault_delete(self, account: Account, vault_id: str) -> None:
        self._record("vault_delete", account, {"vault_id": vault_id})
        if self.vault.get(vault_id, {}).get("account") != account.label:
            raise GatewayError("Customer not found")
        del self.vault[vault_id]

    def _use(self, token: str):
        if not token or token in self.used_tokens:
            raise GatewayError("The payment token is missing or was already used.")
        self.used_tokens.add(token)
