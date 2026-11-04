"""Plaid, through plaid-python. The only module that reads PLAID_* settings.

- Never calls /transactions/refresh (the owner's instruction): a sync reads
  what Plaid already has, nightly, on Check now, and on Plaid's own
  SYNC_UPDATES_AVAILABLE webhook.
- Never logs or returns a key or an access token; a Plaid error is turned into
  its own code and message, which carry neither.
- The webhook is verified as Plaid documents it: the `Plaid-Verification`
  header is an ES256 JWT, signed by a key fetched by its id from
  /webhook_verification_key/get, issued within five minutes, whose
  `request_body_sha256` is the body's.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from decimal import Decimal

from django.conf import settings

from .base import (
    LOGIN_CODES, Account, Changes, Event, Linked, NotConfigured, Provider, ProviderError,
    Transaction, WebhookRefused,
)

log = logging.getLogger(__name__)

#: Pages of /transactions/sync a pass reads at most (500 each).
MOST_PAGES = 200
#: A pass is started again from its first cursor when Plaid says the data
#: changed under it (TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION).
RESTARTS = 3
DAYS_REQUESTED = 365
#: How old a webhook may be.
WEBHOOK_MAX_AGE = 5 * 60


def configured() -> bool:
    return bool(settings.PLAID_CLIENT_ID and settings.PLAID_SECRET)


def cents(amount) -> int:
    return int((Decimal(str(amount)) * 100).quantize(Decimal(1)))


def _words(code: str) -> str:
    return code.replace("_", " ").strip().capitalize()


def category_label(transaction: dict) -> str:
    """Plaid's category as a person reads it: "Food and drink: coffee"."""
    pfc = transaction.get("personal_finance_category") or {}
    primary, detailed = str(pfc.get("primary") or ""), str(pfc.get("detailed") or "")
    if primary:
        label = _words(primary)
        rest = detailed[len(primary):].strip("_") if detailed.startswith(primary) else detailed
        if rest and rest.lower() != "other":
            label += ": " + _words(rest).lower()
        return label[:120]
    legacy = transaction.get("category") or []
    return " / ".join(str(c) for c in legacy)[:120]


def read_transaction(t: dict) -> Transaction:
    amount = cents(t.get("amount") or 0)
    return Transaction(
        provider_transaction_id=str(t["transaction_id"]),
        provider_account_id=str(t["account_id"]),
        on_date=t["date"],
        # Plaid: positive is money out of the account (for a card, a charge).
        amount_cents=abs(amount), direction="out" if amount > 0 else "in",
        description=str(t.get("name") or t.get("merchant_name") or "")[:255],
        bank_category=category_label(t),
        pending=bool(t.get("pending")),
        pending_transaction_id=str(t.get("pending_transaction_id") or ""))


class PlaidProvider(Provider):
    name = "plaid"

    def __init__(self, client=None):
        self._client = client

    # ------------------------------------------------------------ the client

    @property
    def client(self):
        if self._client is None:
            if not configured():
                raise NotConfigured("Bank feeds are not set up on this server.")
            import plaid
            from plaid.api import plaid_api

            host = (plaid.Environment.Production if settings.PLAID_ENVIRONMENT == "production"
                    else plaid.Environment.Sandbox)
            configuration = plaid.Configuration(host=host, api_key={
                "clientId": settings.PLAID_CLIENT_ID, "secret": settings.PLAID_SECRET,
                "plaidVersion": "2020-09-14"})
            self._client = plaid_api.PlaidApi(plaid.ApiClient(configuration))
        return self._client

    def _call(self, method: str, request):
        import plaid

        try:
            return getattr(self.client, method)(request).to_dict()
        except plaid.ApiException as exc:
            try:
                body = json.loads(exc.body or "{}")
            except (TypeError, ValueError):
                body = {}
            code = str(body.get("error_code") or "")
            message = str(body.get("display_message") or body.get("error_message")
                          or f"Plaid answered {exc.status}.")
            log.warning("plaid %s refused: %s", method, code or exc.status)
            raise ProviderError(message[:300], code=code) from None
        except (OSError, ValueError) as exc:
            log.warning("plaid %s unreachable: %s", method, type(exc).__name__)
            raise ProviderError("Plaid could not be reached. Try again shortly.",
                                code="UNREACHABLE") from None

    # --------------------------------------------------------- the interface

    def link_token(self, *, user_ref: str, webhook_url: str, access_token: str = "") -> str:
        from plaid.model.country_code import CountryCode
        from plaid.model.link_token_create_request import LinkTokenCreateRequest
        from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
        from plaid.model.link_token_transactions import LinkTokenTransactions
        from plaid.model.products import Products
        from config.branding import PRODUCT_NAME

        fields = {"user": LinkTokenCreateRequestUser(client_user_id=user_ref),
                  "client_name": PRODUCT_NAME, "country_codes": [CountryCode("US")],
                  "language": "en", "webhook": webhook_url}
        if access_token:
            fields["access_token"] = access_token            # update mode
        else:
            fields["products"] = [Products("transactions")]
            fields["transactions"] = LinkTokenTransactions(days_requested=DAYS_REQUESTED)
        return self._call("link_token_create", LinkTokenCreateRequest(**fields))["link_token"]

    def exchange(self, public_token: str) -> Linked:
        from plaid.model.country_code import CountryCode
        from plaid.model.institutions_get_by_id_request import InstitutionsGetByIdRequest
        from plaid.model.item_get_request import ItemGetRequest
        from plaid.model.item_public_token_exchange_request import (
            ItemPublicTokenExchangeRequest,
        )

        made = self._call("item_public_token_exchange",
                          ItemPublicTokenExchangeRequest(public_token=public_token))
        linked = Linked(access_token=made["access_token"], item_id=made["item_id"])
        try:
            item = self._call("item_get", ItemGetRequest(access_token=linked.access_token))
            linked.institution_id = str(item["item"].get("institution_id") or "")
            if linked.institution_id:
                found = self._call("institutions_get_by_id", InstitutionsGetByIdRequest(
                    institution_id=linked.institution_id,
                    country_codes=[CountryCode("US")]))
                linked.institution_name = str(found["institution"].get("name") or "")
        except ProviderError:
            pass             # the bank's name is a nicety; the link stands without it
        return linked

    def accounts(self, access_token: str) -> list[Account]:
        from plaid.model.accounts_get_request import AccountsGetRequest

        out = []
        for a in self._call("accounts_get", AccountsGetRequest(access_token=access_token))[
                "accounts"]:
            balances = a.get("balances") or {}
            current, available = balances.get("current"), balances.get("available")
            out.append(Account(
                provider_account_id=str(a["account_id"]), name=str(a.get("name") or ""),
                official_name=str(a.get("official_name") or ""),
                mask=str(a.get("mask") or ""), type=str(a.get("type") or ""),
                subtype=str(a.get("subtype") or ""),
                balance_cents=cents(current) if current is not None else None,
                available_cents=cents(available) if available is not None else None,
                currency=str(balances.get("iso_currency_code") or "")))
        return out

    def changes(self, access_token: str, cursor: str) -> Changes:
        from plaid.model.transactions_sync_request import TransactionsSyncRequest
        from plaid.model.transactions_sync_request_options import (
            TransactionsSyncRequestOptions,
        )

        for _attempt in range(RESTARTS):
            out, at = Changes(cursor=cursor), cursor
            try:
                while True:
                    fields = {"access_token": access_token, "count": 500,
                              "options": TransactionsSyncRequestOptions(
                                  include_personal_finance_category=True)}
                    if at:
                        fields["cursor"] = at
                    page = self._call("transactions_sync", TransactionsSyncRequest(**fields))
                    out.pages += 1
                    out.added += [read_transaction(t) for t in page.get("added") or []]
                    out.modified += [read_transaction(t) for t in page.get("modified") or []]
                    out.removed += [str(r["transaction_id"]) for r in page.get("removed") or []]
                    at = out.cursor = page["next_cursor"]
                    if not page.get("has_more") or out.pages >= MOST_PAGES:
                        return out
            except ProviderError as exc:
                if exc.code != "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION":
                    raise
        raise ProviderError("The bank's data kept changing while it was read. It is "
                            "read again at the next sync.", code="MUTATION_DURING_PAGINATION")

    def remove(self, access_token: str) -> None:
        from plaid.model.item_remove_request import ItemRemoveRequest

        self._call("item_remove", ItemRemoveRequest(access_token=access_token))

    # ------------------------------------------------------------ webhooks

    _keys: dict = {}

    def _key(self, key_id: str) -> dict:
        from plaid.model.webhook_verification_key_get_request import (
            WebhookVerificationKeyGetRequest,
        )

        cached = self._keys.get(key_id)
        if cached is None:
            try:
                cached = self._call("webhook_verification_key_get",
                                    WebhookVerificationKeyGetRequest(key_id=key_id))["key"]
            except ProviderError as exc:
                raise WebhookRefused(f"The signing key was not found ({exc.code}).") from None
            self._keys[key_id] = cached
        if cached.get("expired_at"):
            raise WebhookRefused("The webhook was signed with an expired key.")
        return cached

    def read_webhook(self, body: bytes, headers) -> Event:
        import jwt
        from jwt.algorithms import ECAlgorithm

        token = headers.get("Plaid-Verification") or ""
        if not token:
            raise WebhookRefused("No Plaid-Verification header.")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise WebhookRefused("The Plaid-Verification header is not a JWT.") from None
        if header.get("alg") != "ES256" or not header.get("kid"):
            raise WebhookRefused("The webhook is not signed as Plaid signs them.")
        jwk = self._key(str(header["kid"]))
        public = ECAlgorithm.from_jwk(json.dumps(
            {k: jwk[k] for k in ("kty", "crv", "x", "y") if k in jwk}))
        try:
            claims = jwt.decode(token, key=public, algorithms=["ES256"],
                                options={"verify_aud": False, "require": ["iat"]})
        except jwt.PyJWTError:
            raise WebhookRefused("The webhook's signature does not verify.") from None
        if time.time() - float(claims["iat"]) > WEBHOOK_MAX_AGE:
            raise WebhookRefused("The webhook is more than five minutes old.")
        digest = hashlib.sha256(body).hexdigest()
        if not hmac.compare_digest(digest, str(claims.get("request_body_sha256") or "")):
            raise WebhookRefused("The webhook's body is not the one that was signed.")
        try:
            payload = json.loads(body)
        except ValueError:
            raise WebhookRefused("The webhook's body is not JSON.") from None
        return read_event(payload)


def read_event(payload: dict) -> Event:
    kind, code = str(payload.get("webhook_type") or ""), str(payload.get("webhook_code") or "")
    item = str(payload.get("item_id") or "")
    if kind == "TRANSACTIONS" and code == "SYNC_UPDATES_AVAILABLE":
        return Event("sync", item, code)
    if kind == "ITEM":
        if code == "ERROR":
            error = payload.get("error") or {}
            return Event("attention", item, str(error.get("error_code") or "ERROR"),
                         str(error.get("display_message") or error.get("error_message")
                             or "")[:300])
        if code in LOGIN_CODES or code in ("USER_PERMISSION_REVOKED", "USER_ACCOUNT_REVOKED"):
            return Event("attention", item, code)
        if code == "LOGIN_REPAIRED":
            return Event("repaired", item, code)
    return Event("other", item, code)
