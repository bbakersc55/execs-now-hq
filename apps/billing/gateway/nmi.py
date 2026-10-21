"""NMI's v5 REST API. Only `apps/billing/gateway` imports this.

The request and response shapes below were proved against NMI's sandbox on
2026-10-21, where the documentation disagreed with itself
(`docs/p4_billing.md` §0):

- The private key is the whole `Authorization` header, with no scheme.
- A sale takes the browser's token as `payment_details.payment_token`, or a
  stored card as a top-level `customer_vault.id`
  (`payment_details.customer_vault_id` is refused).
- Our reference travels as `merchant_defined_fields.field_1` and as the
  order id (`order_details.id`), comes back on the transaction, and is
  carried onto its refunds. The order id is what the lookup searches.
- A field v5 does not know is refused (422), so nothing extra is ever sent.
- A decline is HTTP 200 with `response` "2"; validation errors are 422; the
  same card for the same amount again within minutes is 400 `E_DUPLICATE`.
- A vault record is `billing.payment_details.payment_token` with the
  cardholder's name beside it; the record's card comes back masked.
- A refund (`/payments/{id}/refund`) takes a partial amount, also on a sale
  that has not settled yet; more than the balance is refused (400).
- `GET /payments/{id}` answers 401 for a bad key and 404 for an unknown id,
  which makes it the connection test.
- v5 cannot search. Finding a sale whose answer was lost is the read-only
  Query API (`query.php`, form-posted, XML back) by order id.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import xml.etree.ElementTree as ET

import requests

from apps.billing.gateway import (
    Account, Billing, ConnectionResult, GatewayError, GatewayRefused, GatewayUnreachable,
    LiveCallsRefused, Transaction, VaultRecord, live_calls_allowed, refuse_card_fields,
    to_cents, to_dollars,
)

log = logging.getLogger(__name__)

TIMEOUT_SECONDS = 30
#: An id no account has: the connection test asks for it and expects 404.
PROBE_ID = "1"


def http_transport(method: str, url: str, headers: dict, data: str | None):
    """The network: (status, text). Refused unless real calls are allowed
    (`NMI_LIVE_CALLS`, and never under the test runner)."""
    if not live_calls_allowed():
        raise LiveCallsRefused("Real calls to NMI are off on this server (NMI_LIVE_CALLS).")
    response = requests.request(method, url, headers=headers, data=data,
                                timeout=TIMEOUT_SECONDS)
    return response.status_code, response.text


class NmiGateway:
    def __init__(self, transport=http_transport):
        self._transport = transport

    # --- the calls -----------------------------------------------------------

    def check_connection(self, account: Account) -> ConnectionResult:
        """One authenticated read. Proves the private key, not the public one."""
        status, payload = self._send(account, "GET", f"/payments/{PROBE_ID}", None,
                                     raise_for_status=False)
        if status in (200, 404):
            return ConnectionResult(True, f"Connected to NMI ({account.environment}).")
        if status in (401, 403):
            return ConnectionResult(False, "NMI refused the private key. Check that it is the "
                                           f"{account.environment} key for this account.")
        return ConnectionResult(False, f"NMI answered {status}: {self._message(account, payload)}")

    def sale(self, account: Account, *, amount_cents: int, reference: str,
             payment_token: str | None = None, vault_id: str | None = None) -> Transaction:
        if (payment_token is None) == (vault_id is None):
            raise GatewayError("A sale takes a payment token or a vault id, not both.")
        if amount_cents <= 0:
            raise GatewayError("A sale is for more than nothing.")
        body = {"amount": to_dollars(amount_cents), "currency": "USD",
                "order_details": {"id": reference[:50]},
                "merchant_defined_fields": {"field_1": reference}}
        if payment_token is not None:
            body["payment_details"] = {"payment_token": payment_token}
        else:
            body["customer_vault"] = {"id": vault_id}
        _, payload = self._send(account, "POST", "/payments/sale", body)
        return self._transaction(payload)

    def refund(self, account: Account, *, transaction_id: str,
               amount_cents: int) -> Transaction:
        if amount_cents <= 0:
            raise GatewayError("A refund is for more than nothing.")
        _, payload = self._send(account, "POST", f"/payments/{transaction_id}/refund",
                                {"amount": to_dollars(amount_cents)})
        return self._transaction(payload)

    def get_transaction(self, account: Account, transaction_id: str) -> Transaction:
        _, payload = self._send(account, "GET", f"/payments/{transaction_id}", None)
        return self._transaction(payload)

    def find_by_reference(self, account: Account, reference: str) -> Transaction | None:
        """The sale made with our reference as its order id, or None if NMI
        has none. Read-only (the Query API); nothing is charged."""
        form = {"order_id": reference[:50]}
        refuse_card_fields(form)
        data = urllib.parse.urlencode({"security_key": account.private_key, **form})
        status, text = self._call(account, "POST", account.query_url, data, "query",
                                  {"Content-Type": "application/x-www-form-urlencoded"})
        if status >= 300:
            raise GatewayUnreachable(f"NMI's lookup answered {status}.")
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            raise GatewayUnreachable("NMI's lookup answer could not be read.") from None
        error = root.findtext("error_response")
        if error:
            raise GatewayError(account.scrub(error.strip()))
        for node in root.findall("transaction"):
            sales = [a for a in node.findall("action") if a.findtext("action_type") == "sale"]
            if not sales:
                continue
            sale = sales[0]
            approved = sale.findtext("success") == "1"
            return Transaction(
                id=node.findtext("transaction_id", ""), approved=approved,
                status=node.findtext("condition", ""),
                response_code=sale.findtext("response_code", ""),
                response_text=sale.findtext("response_text", ""),
                amount_cents=to_cents(sale.findtext("amount") or 0),
                card_type=node.findtext("cc_type", ""),
                last4=_last4(node.findtext("cc_number", "")),
                reference=node.findtext("order_id", ""))
        return None

    def vault_add(self, account: Account, *, payment_token: str,
                  billing: Billing) -> VaultRecord:
        body = {"billing": {"first_name": billing.first_name[:50],
                            "last_name": billing.last_name[:50],
                            "payment_details": {"payment_token": payment_token}}}
        _, payload = self._send(account, "POST", "/customers", body)
        cards = [b.get("payment_details") or {} for b in (payload or {}).get("billing") or []]
        card = cards[0] if cards else {}
        return VaultRecord(id=str(payload.get("id", "")),
                           last4=_last4(card.get("card_number", "")),
                           card_exp=str(card.get("card_exp", "")))

    def vault_delete(self, account: Account, vault_id: str) -> None:
        self._send(account, "DELETE", f"/customers/{vault_id}", None)

    # --- the edge --------------------------------------------------------------

    def _call(self, account: Account, method: str, url: str, data, label: str,
              headers: dict):
        try:
            status, text = self._transport(method, url, headers, data)
        except LiveCallsRefused:
            raise
        except requests.RequestException as exc:
            # The exception's text can include the URL, never the headers.
            log.warning("nmi %s %s for %s: no answer (%s)", method, label, account.label,
                        type(exc).__name__)
            raise GatewayUnreachable("NMI did not answer.") from None
        return status, text

    def _send(self, account: Account, method: str, path: str, body, *,
              raise_for_status: bool = True):
        refuse_card_fields(body)
        headers = {"Authorization": account.private_key, "Content-Type": "application/json",
                   "Accept": "application/json"}
        status, text = self._call(account, method, account.base_url + path,
                                  json.dumps(body) if body is not None else None,
                                  _shape(path), headers)
        try:
            payload = json.loads(text) if text else None
        except ValueError:
            payload = None
        ref = (payload.get("ref_id") or payload.get("refId")) if isinstance(payload, dict) else ""
        log.info("nmi %s %s for %s: %s ref %s", method, _shape(path), account.label, status,
                 ref or "-")
        if raise_for_status and status >= 500:
            raise GatewayUnreachable(f"NMI answered {status}.")
        if raise_for_status and status >= 300:
            code = ""
            if isinstance(payload, dict):
                code = str(payload.get("error_code") or payload.get("errorCode") or "")
            raise GatewayRefused(self._message(account, payload) or f"NMI answered {status}.",
                                 code=code)
        return status, payload

    @staticmethod
    def _message(account: Account, payload) -> str:
        if not isinstance(payload, dict):
            return ""
        parts = [str(payload.get("message", ""))]
        for detail in payload.get("details") or []:
            if isinstance(detail, dict):
                parts.append(f"{detail.get('fieldName', '')}: {detail.get('message', '')}")
        return account.scrub(" ".join(p for p in parts if p).strip())

    @staticmethod
    def _transaction(payload) -> Transaction:
        if not isinstance(payload, dict) or not payload.get("id"):
            raise GatewayUnreachable("NMI's answer had no transaction in it.")
        card = payload.get("payment_details") or {}
        fields = payload.get("merchant_defined_fields") or {}
        return Transaction(
            id=str(payload["id"]),
            approved=str(payload.get("response")) == "1",
            status=str(payload.get("status", "")),
            response_code=str(payload.get("response_code", "")),
            response_text=str(payload.get("response_text", "")),
            amount_cents=to_cents(payload.get("amount") or 0),
            card_type=str(card.get("card_type", "")),
            last4=_last4(card.get("card_number", "")),
            reference=str(fields.get("field_1", "")) if isinstance(fields, dict) else "",
        )


def _last4(masked: str) -> str:
    digits = "".join(ch for ch in str(masked) if ch.isdigit())
    return digits[-4:] if str(masked)[-4:].isdigit() else ""


def _shape(path: str) -> str:
    """The route without its ids, for a log line."""
    return "/".join("{id}" if part.isdigit() or len(part) > 20 else part
                    for part in path.split("/"))
