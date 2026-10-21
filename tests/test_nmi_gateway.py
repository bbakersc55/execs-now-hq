"""P4 part 1: the NMI gateway and Settings → Billing (`docs/p4_billing.md` §1).

No test here reaches NMI. The real client is exercised through a recording
transport that stands where the network would be; everything else runs on
the stub gateway (`conftest.stub_gateway`). Keys are made-up strings, never
a real value.
"""

from __future__ import annotations

import inspect
import json
import logging

import pytest
from django.core.management import CommandError, call_command

from apps.billing import gateway as gw
from apps.billing import payment_accounts
from apps.billing.gateway.nmi import NmiGateway, http_transport
from apps.billing.gateway.stub import StubGateway
from apps.billing.models import PaymentAccount
from apps.tenancy.models import AuditEvent, TenantSecret

from .factories import ClientCompanyFactory, MembershipFactory

PRIVATE = "priv-7f3a9c1e5b2d4a6f8e0c1b3d5f7a9c2e"
PUBLIC = "pub-Q2w3E4-r5T6y7-U8i9O0"
ACCOUNT = gw.Account(environment="sandbox", private_key=PRIVATE, public_key=PUBLIC,
                     label="test")


class Recorder:
    """Stands where the network would be: records each request, answers
    with what the test queued."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests = []

    def __call__(self, method, url, headers, body):
        self.requests.append({"method": method, "url": url, "headers": headers, "body": body})
        return self.answers.pop(0)


SALE_OK = {"object": "transaction", "id": "12707835156", "amount": "12.34",
           "status": "pendingsettlement", "response": "1", "response_text": "SUCCESS",
           "response_code": "100", "payment_details": {"card_number": "411111******1111",
                                                       "card_type": "Visa"},
           "merchant_defined_fields": {"field_1": "inv-1"}}


def _post(client, url, data=None):
    return client.post(url, json.dumps(data or {}), content_type="application/json")


# ---------------------------------------------------------------- the guard

def test_tests_always_get_the_stub_even_with_live_calls_on(settings):
    settings.NMI_LIVE_CALLS = True
    assert isinstance(gw.gateway(), StubGateway)
    assert gw.mode() == "stub"


def test_the_network_refuses_under_test_even_with_live_calls_on(settings):
    settings.NMI_LIVE_CALLS = True
    with pytest.raises(gw.LiveCallsRefused):
        http_transport("GET", "https://sandbox.nmi.com/api/v5/payments/1", {}, None)


def test_the_real_client_refuses_without_live_calls():
    with pytest.raises(gw.LiveCallsRefused):
        NmiGateway().check_connection(ACCOUNT)


@pytest.mark.parametrize("cls", [NmiGateway, StubGateway])
def test_no_method_takes_a_card_field(cls):
    for name, method in inspect.getmembers(cls, inspect.isfunction):
        if name.startswith("_"):
            continue
        for param in inspect.signature(method).parameters:
            assert param not in gw.CARD_FIELDS, f"{cls.__name__}.{name}({param})"
            assert "card" not in param and "cvv" not in param, f"{cls.__name__}.{name}({param})"


@pytest.mark.parametrize("body", [
    {"payment_details": {"card_number": "x"}},
    {"billing": [{"payment_details": {"cvv": "x"}}]},
    {"ccnumber": "x"},
    {"deep": {"deeper": [{"routing_number": "x"}]}},
])
def test_a_body_carrying_card_data_never_leaves(body):
    transport = Recorder()
    with pytest.raises(gw.CardDataRefused):
        NmiGateway(transport)._send(ACCOUNT, "POST", "/payments/sale", body)
    assert transport.requests == []


def test_the_stub_refuses_card_data_too(stub_gateway):
    with pytest.raises(gw.CardDataRefused):
        stub_gateway._record("sale", ACCOUNT, {"payment_details": {"card_cvv": "x"}})


def test_an_account_never_prints_its_keys():
    assert PRIVATE not in repr(ACCOUNT) and PUBLIC not in repr(ACCOUNT)
    assert ACCOUNT.scrub(f"bad key {PRIVATE} and {PUBLIC}") == "bad key [key] and [key]"


def test_amounts_are_integer_cents_and_dollars_only_at_the_edge():
    assert gw.to_dollars(1234) == "12.34" and gw.to_dollars(5) == "0.05"
    assert gw.to_dollars(-200) == "-2.00"
    assert gw.to_cents("-10.34") == -1034 and gw.to_cents(12.34) == 1234
    with pytest.raises(gw.GatewayError):
        gw.to_dollars(12.34)


# ------------------------------------------------- the v5 shapes, as proved

def test_a_sale_on_a_token():
    transport = Recorder((200, SALE_OK))
    txn = NmiGateway(transport).sale(ACCOUNT, amount_cents=1234, reference="inv-1",
                                     payment_token="tok-1")
    sent = transport.requests[0]
    assert sent["method"] == "POST"
    assert sent["url"] == "https://sandbox.nmi.com/api/v5/payments/sale"
    assert sent["headers"]["Authorization"] == PRIVATE
    assert sent["body"] == {"amount": "12.34", "currency": "USD",
                            "merchant_defined_fields": {"field_1": "inv-1"},
                            "payment_details": {"payment_token": "tok-1"}}
    assert (txn.id, txn.approved, txn.amount_cents, txn.last4, txn.card_type, txn.reference) \
        == ("12707835156", True, 1234, "1111", "Visa", "inv-1")


def test_a_sale_on_a_vault_record_uses_customer_vault_id():
    transport = Recorder((200, SALE_OK))
    NmiGateway(transport).sale(ACCOUNT, amount_cents=111, reference="inv-2", vault_id="146")
    body = transport.requests[0]["body"]
    assert body["customer_vault"] == {"id": "146"} and "payment_details" not in body


def test_a_sale_takes_one_source():
    with pytest.raises(gw.GatewayError):
        NmiGateway(Recorder()).sale(ACCOUNT, amount_cents=100, reference="r",
                                    payment_token="t", vault_id="v")
    with pytest.raises(gw.GatewayError):
        NmiGateway(Recorder()).sale(ACCOUNT, amount_cents=100, reference="r")


def test_a_decline_is_a_200_with_response_2():
    declined = {**SALE_OK, "status": "failed", "response": "2", "response_text": "DECLINE",
                "response_code": "200", "amount": "0.50"}
    txn = NmiGateway(Recorder((200, declined))).sale(ACCOUNT, amount_cents=50,
                                                     reference="r", vault_id="146")
    assert not txn.approved and txn.response_code == "200"


def test_a_partial_refund():
    refund = {**SALE_OK, "id": "12707835302", "amount": "-2.00"}
    transport = Recorder((200, refund))
    txn = NmiGateway(transport).refund(ACCOUNT, transaction_id="12707835156", amount_cents=200)
    assert transport.requests[0]["url"].endswith("/payments/12707835156/refund")
    assert transport.requests[0]["body"] == {"amount": "2.00"}
    assert txn.amount_cents == -200 and txn.reference == "inv-1"


def test_a_card_into_the_vault():
    stored = {"object": "customer", "id": "1464180327",
              "billing": [{"payment_details": {"card_number": "411111******1111",
                                               "card_exp": "1029"}}]}
    transport = Recorder((200, stored))
    record = NmiGateway(transport).vault_add(ACCOUNT, payment_token="tok-2",
                                             billing=gw.Billing("Ada", "Lovelace"))
    assert transport.requests[0]["url"].endswith("/customers")
    assert transport.requests[0]["body"] == {"billing": {
        "first_name": "Ada", "last_name": "Lovelace",
        "payment_details": {"payment_token": "tok-2"}}}
    assert (record.id, record.last4, record.card_exp) == ("1464180327", "1111", "1029")


@pytest.mark.parametrize("status,ok", [(404, True), (200, True), (401, False), (403, False),
                                       (500, False)])
def test_the_connection_test(status, ok):
    transport = Recorder((status, {"message": "x"}))
    result = NmiGateway(transport).check_connection(ACCOUNT)
    assert result.ok is ok
    assert transport.requests[0]["method"] == "GET"
    assert transport.requests[0]["url"].endswith("/payments/1")


def test_live_goes_to_secure_nmi():
    live = gw.Account(environment="live", private_key=PRIVATE, public_key=PUBLIC)
    transport = Recorder((404, None))
    NmiGateway(transport).check_connection(live)
    assert transport.requests[0]["url"].startswith("https://secure.nmi.com/api/v5/")
    with pytest.raises(gw.GatewayError):
        gw.Account(environment="production", private_key=PRIVATE, public_key=PUBLIC)


def test_no_key_reaches_a_log_or_an_error(caplog):
    caplog.set_level(logging.DEBUG)
    refused = {"type": "validationError", "message": f"Bad key {PRIVATE}",
               "details": [{"fieldName": "extraParameters", "message": "Unexpected 'x'"}]}
    gateway = NmiGateway(Recorder((200, SALE_OK), (422, refused)))
    gateway.sale(ACCOUNT, amount_cents=1234, reference="inv-1", payment_token="tok-1")
    with pytest.raises(gw.GatewayError) as caught:
        gateway.sale(ACCOUNT, amount_cents=1234, reference="inv-1", payment_token="tok-3")
    assert PRIVATE not in str(caught.value) and "extraParameters" in str(caught.value)
    assert caplog.records, "the client logs each call"
    for secret in (PRIVATE, PUBLIC, "tok-1", "tok-3"):
        assert secret not in caplog.text


# ----------------------------------------------------- the platform account

def test_the_platform_account_comes_from_the_environment_only(settings, tenant_a):
    account = gw.platform_account()
    assert (account.label, account.private_key, account.environment) == (
        "platform", "platform-private-test-value", "sandbox")
    settings.NMI_PRIVATE_API_KEY = ""
    with pytest.raises(gw.GatewayError):
        gw.platform_account()


@pytest.mark.django_db
def test_nmi_check_refuses_without_live_calls():
    with pytest.raises(CommandError, match="NMI_LIVE_CALLS is off"):
        call_command("nmi_check")


@pytest.mark.django_db
def test_the_proof_page_is_not_there_without_live_calls(client):
    assert client.get("/dev/nmi-proof").status_code == 404
    assert client.post("/dev/nmi-proof/run", "{}",
                       content_type="application/json").status_code == 404


# ------------------------------------------------------ Settings → Billing

def _owner(tenant):
    return MembershipFactory(tenant=tenant, role="FF")


@pytest.mark.django_db
def test_the_owner_connects_and_no_response_holds_a_key(seeded_tenant, api, stub_gateway):
    client = api.as_(_owner(seeded_tenant))
    response = _post(client, "/api/payment-account/",
                     {"environment": "sandbox", "private_key": PRIVATE, "public_key": PUBLIC})
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["ready"] and body["private_key_last4"] == PRIVATE[-4:]
    assert body["public_key_last4"] == PUBLIC[-4:] and body["gateway"] == "stub"
    shown = client.get("/api/payment-account/").content.decode()
    for secret in (PRIVATE, PUBLIC):
        assert secret not in response.content.decode() and secret not in shown
    assert [c[0] for c in stub_gateway.calls] == ["check_connection"]
    row = PaymentAccount.all_objects.get(tenant=seeded_tenant)
    assert row.check_ok and row.environment == "sandbox"
    stored = TenantSecret.all_objects.filter(tenant=seeded_tenant,
                                             kind__in=["nmi_private_key", "nmi_public_key"])
    assert stored.count() == 2
    assert all(PRIVATE.encode() not in bytes(s.ciphertext) for s in stored)
    event = AuditEvent.all_objects.get(tenant=seeded_tenant,
                                       verb="payments.account_connected")
    assert PRIVATE not in json.dumps(event.payload) and PUBLIC not in json.dumps(event.payload)
    account = payment_accounts.practice_account(seeded_tenant)
    assert (account.private_key, account.public_key) == (PRIVATE, PUBLIC)


@pytest.mark.django_db
def test_refused_keys_change_nothing(seeded_tenant, api):
    client = api.as_(_owner(seeded_tenant))
    assert _post(client, "/api/payment-account/", {"environment": "sandbox",
                 "private_key": PRIVATE, "public_key": PUBLIC}).status_code == 200
    refused = _post(client, "/api/payment-account/", {"environment": "sandbox",
                    "private_key": "bad-key-value", "public_key": "pub-new"})
    assert refused.status_code == 400 and "Nothing was changed" in refused.json()["detail"]
    account = payment_accounts.practice_account(seeded_tenant)
    assert (account.private_key, account.public_key) == (PRIVATE, PUBLIC)


@pytest.mark.django_db
@pytest.mark.parametrize("data,needle", [
    ({"environment": "live", "private_key": PRIVATE, "public_key": PUBLIC}, "production"),
    ({"environment": "test", "private_key": PRIVATE, "public_key": PUBLIC}, "sandbox or live"),
    ({"environment": "sandbox", "private_key": PRIVATE}, "both keys"),
    ({"environment": "sandbox", "private_key": PRIVATE, "public_key": PRIVATE}, "the same"),
])
def test_what_is_refused_before_nmi_is_asked(data, needle, seeded_tenant, api, stub_gateway):
    response = _post(api.as_(_owner(seeded_tenant)), "/api/payment-account/", data)
    assert response.status_code == 400 and needle in response.json()["detail"]
    assert stub_gateway.calls == []
    assert not PaymentAccount.all_objects.filter(tenant=seeded_tenant).exists()


@pytest.mark.django_db
def test_live_is_accepted_only_in_production(settings, seeded_tenant, api):
    settings.APP_ENVIRONMENT = "production"
    response = _post(api.as_(_owner(seeded_tenant)), "/api/payment-account/",
                     {"environment": "live", "private_key": PRIVATE, "public_key": PUBLIC})
    assert response.status_code == 200 and response.json()["environment"] == "live"


@pytest.mark.django_db
def test_switching_environment_takes_both_keys(settings, seeded_tenant, api):
    settings.APP_ENVIRONMENT = "production"
    client = api.as_(_owner(seeded_tenant))
    _post(client, "/api/payment-account/",
          {"environment": "sandbox", "private_key": PRIVATE, "public_key": PUBLIC})
    response = _post(client, "/api/payment-account/",
                     {"environment": "live", "private_key": "live-private-value"})
    assert response.status_code == 400 and "both" in response.json()["detail"]
    assert PaymentAccount.all_objects.get(tenant=seeded_tenant).environment == "sandbox"


@pytest.mark.django_db
def test_one_key_can_be_replaced_alone(seeded_tenant, api):
    client = api.as_(_owner(seeded_tenant))
    _post(client, "/api/payment-account/",
          {"environment": "sandbox", "private_key": PRIVATE, "public_key": PUBLIC})
    response = _post(client, "/api/payment-account/",
                     {"environment": "sandbox", "public_key": "pub-replaced-9X8y"})
    assert response.status_code == 200 and response.json()["public_key_last4"] == "9X8y"
    assert payment_accounts.practice_account(seeded_tenant).private_key == PRIVATE


@pytest.mark.django_db
def test_test_connection_records_a_failure(seeded_tenant, api, stub_gateway, monkeypatch):
    client = api.as_(_owner(seeded_tenant))
    _post(client, "/api/payment-account/",
          {"environment": "sandbox", "private_key": PRIVATE, "public_key": PUBLIC})
    monkeypatch.setattr(StubGateway, "check_connection",
                        lambda self, account: gw.ConnectionResult(False, "NMI refused it."))
    body = _post(client, "/api/payment-account/test/").json()
    assert body["check_ok"] is False and body["ready"] is False
    assert body["check_detail"] == "NMI refused it."
    assert not payment_accounts.is_ready(seeded_tenant)


@pytest.mark.django_db
def test_the_pricing_program_shows_read_only_to_the_practice(seeded_tenant, api):
    seeded_tenant.pricing_program = "dual_pricing"
    seeded_tenant.save()
    client = api.as_(_owner(seeded_tenant))
    body = client.get("/api/payment-account/").json()
    assert (body["pricing_program"], body["pricing_program_label"]) == (
        "dual_pricing", "Dual pricing")
    _post(client, "/api/payment-account/", {"environment": "sandbox", "private_key": PRIVATE,
                                            "public_key": PUBLIC, "pricing_program": "x"})
    seeded_tenant.refresh_from_db()
    assert seeded_tenant.pricing_program == "dual_pricing"


# -------------------------------------------- role boundaries (matrix 12.1)

@pytest.mark.django_db
@pytest.mark.parametrize("role", ["CF", "VA", "FCC", "ECC"])
def test_only_the_practice_owner_reaches_the_nmi_account(role, seeded_tenant, api,
                                                         stub_gateway):
    company = ClientCompanyFactory(tenant=seeded_tenant) if role in ("FCC", "ECC") else None
    client = api.as_(MembershipFactory(tenant=seeded_tenant, role=role,
                                       client_company=company))
    assert client.get("/api/payment-account/").status_code == 403
    assert _post(client, "/api/payment-account/", {"environment": "sandbox",
                 "private_key": PRIVATE, "public_key": PUBLIC}).status_code == 403
    assert _post(client, "/api/payment-account/test/").status_code == 403
    assert stub_gateway.calls == []
    assert not PaymentAccount.all_objects.filter(tenant=seeded_tenant).exists()


# ------------------------------------------------------- practice isolation

@pytest.mark.django_db
def test_each_practice_uses_only_its_own_keys(tenant_a, tenant_b, api):
    a, b = _owner(tenant_a), _owner(tenant_b)
    _post(api.as_(a), "/api/payment-account/",
          {"environment": "sandbox", "private_key": PRIVATE, "public_key": PUBLIC})
    shown_to_b = api.as_(b).get("/api/payment-account/").json()
    assert shown_to_b["private_key_last4"] == "" and shown_to_b["ready"] is False
    with pytest.raises(payment_accounts.PaymentAccountError):
        payment_accounts.practice_account(tenant_b)
    _post(api.as_(b), "/api/payment-account/",
          {"environment": "sandbox", "private_key": "priv-b-0000", "public_key": "pub-b-1111"})
    assert payment_accounts.practice_account(tenant_a).private_key == PRIVATE
    assert payment_accounts.practice_account(tenant_b).private_key == "priv-b-0000"
    assert payment_accounts.practice_account(tenant_a).label == str(tenant_a.pk)


# ------------------------------------------- the private key and the bundle

def test_no_nmi_key_name_reaches_the_frontend():
    """The private key is read only by the server; the public one reaches a
    page at runtime from the server, never from the build. So no NMI setting
    name, and no Vite variable for one, appears in the frontend's source or
    in a built bundle."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "frontend"
    places = [root / "src", root / "dist", root / "index.html", root / "vite.config.ts"]
    names = ("NMI_PRIVATE", "NMI_PUBLIC", "VITE_NMI", "NMI_ENVIRONMENT")
    for place in places:
        files = [place] if place.is_file() else (
            [f for f in place.rglob("*") if f.is_file()] if place.exists() else [])
        for path in files:
            if path.suffix not in (".ts", ".tsx", ".js", ".html", ".json", ".map"):
                continue
            text = path.read_text(errors="ignore")
            for name in names:
                assert name not in text, f"{name} in {path}"
