"""The gateway's host, the card form it picks, and card payments paused
(2026-11-10, `docs/p4_billing.md` §1.4).

- `NMI_API_HOST` is one of two hosts in code, and every live call goes to it:
  v5 REST, the Query API (lookups and the read-back) and `nmi_check`.
- The card form follows it: NMI's Payment Component on NMI's own host,
  Collect.js from the white-label host.
- In production the stub never answers: with real calls off, card payments
  are paused. The platform owner's switch pauses them with real calls on.
  Either way nothing is marked paid without a real gateway answer.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from apps.billing import autopay, card_payments, gateway as gw, readback, subscriptions
from apps.billing.gateway.nmi import NmiGateway
from apps.billing.gateway.stub import StubGateway
from apps.billing.models import (
    CardPaymentHold, ClientInvoice, ClientPayment, ClientPaymentMethod, NmiEvent,
    PaymentAttempt, PracticeInvoice, PracticeSubscription,
)
from apps.crm.models import OutboxMessage
from apps.tenancy.context import tenant_context

from . import registry_config  # noqa: F401
from .test_autopay import due_today, send_invoice
from .test_autopay import save_card as save_client_card
from .test_autopay import turn_on
from .test_card_payments import _after_commit_now  # noqa: F401  (autouse)
from .test_card_payments import billing, pay, portal_row, sales  # noqa: F401  (fixtures)
from .test_client_invoicing import ready_to_bill  # noqa: F401  (a fixture)
from .test_client_invoicing import a_client, post, sent
from .test_pay_links import anyone, connected, invoice_email, token_in  # noqa: F401
from .test_platform_practices import platform_owner, practices  # noqa: F401
from .test_subscriptions import _commit_now  # noqa: F401  (autouse)
from .test_subscriptions import carded, next_first, platform_practice  # noqa: F401
from .test_subscriptions import save_card as save_subscription_card

ROOT = Path(__file__).resolve().parent.parent
A = PaymentAttempt.Status
LIVE = gw.Account(environment="live", private_key="live-private-0000", public_key="live-pub",
                  label="t")
SANDBOX = gw.Account(environment="sandbox", private_key="sb-private-0000", public_key="sb-pub",
                     label="t")


class Wire:
    """The network, faked: records each request, answers like NMI."""

    def __init__(self):
        self.urls = []

    def __call__(self, method, url, headers, data):
        self.urls.append(url)
        if url.endswith("query.php"):
            return 200, "<nm_response></nm_response>"
        if url.endswith("/payments/1"):
            return 404, "{}"
        return 200, json.dumps({"id": "txn-1", "response": "1", "amount": "1.00",
                                "merchant_defined_fields": {"field_1": "ref"}})


def held_on():
    CardPaymentHold.objects.create(paused=True, changed_at=timezone.now())


# ===================================================================== host

def test_the_default_host_is_nmis_own(settings):
    assert settings.NMI_API_HOST == "secure.nmi.com"
    assert LIVE.base_url == "https://secure.nmi.com/api/v5"
    assert LIVE.query_url == "https://secure.nmi.com/api/query.php"
    assert gw.card_form() == {"kind": "component"}


def test_the_white_label_host_takes_every_live_call(settings):
    settings.NMI_API_HOST = "secure.vaultixpay.com"
    wire = Wire()
    nmi = NmiGateway(transport=wire)
    nmi.check_connection(LIVE)
    nmi.sale(LIVE, amount_cents=100, reference="ref", payment_token="tok")
    nmi.find_by_reference(LIVE, "ref")
    now = timezone.now()
    nmi.actions_between(LIVE, now, now)
    assert wire.urls == ["https://secure.vaultixpay.com/api/v5/payments/1",
                         "https://secure.vaultixpay.com/api/v5/payments/sale",
                         "https://secure.vaultixpay.com/api/query.php",
                         "https://secure.vaultixpay.com/api/query.php"]


def test_a_sandbox_account_stays_on_nmis_sandbox_whatever_the_host(settings):
    settings.NMI_API_HOST = "secure.vaultixpay.com"
    wire = Wire()
    NmiGateway(transport=wire).check_connection(SANDBOX)
    NmiGateway(transport=wire).find_by_reference(SANDBOX, "ref")
    assert wire.urls == ["https://sandbox.nmi.com/api/v5/payments/1",
                         "https://sandbox.nmi.com/api/query.php"]


def test_a_host_off_the_list_is_refused_before_anything_is_sent(settings):
    settings.NMI_API_HOST = "secure.evil.example"
    wire = Wire()
    with pytest.raises(gw.GatewayError, match="not one of"):
        NmiGateway(transport=wire).sale(LIVE, amount_cents=100, reference="r",
                                        payment_token="t")
    assert wire.urls == []
    with pytest.raises(gw.GatewayError):
        gw.card_form()


def test_settings_refuse_a_host_off_the_list_at_start():
    env = {**os.environ, "NMI_API_HOST": "secure.evil.example"}
    env.pop("PYTEST_CURRENT_TEST", None)
    done = subprocess.run([sys.executable, "-c", "import config.settings"], cwd=ROOT, env=env,
                          capture_output=True, text=True)
    assert done.returncode != 0 and "NMI_API_HOST must be" in done.stderr
    ok = subprocess.run([sys.executable, "-c", "import config.settings"], cwd=ROOT,
                        env={**env, "NMI_API_HOST": "secure.vaultixpay.com"},
                        capture_output=True, text=True)
    assert ok.returncode == 0, ok.stderr[-500:]


def test_the_settings_list_and_the_gateways_are_the_same():
    line = next(x for x in (ROOT / "config/settings.py").read_text().splitlines()
                if x.startswith("if NMI_API_HOST not in"))
    assert line == "if NMI_API_HOST not in (%s):" % ", ".join(f'"{h}"' for h in gw.API_HOSTS)


@pytest.mark.django_db
def test_nmi_check_names_the_host(settings, capsys):
    settings.NMI_ENVIRONMENT = "live"
    settings.NMI_API_HOST = "secure.vaultixpay.com"
    with pytest.raises(CommandError):  # real calls are off under test
        call_command("nmi_check")
    assert "https://secure.vaultixpay.com/api/v5" in capsys.readouterr().out


# ================================================================ card form

def test_the_white_label_host_takes_collect_js_from_itself(settings):
    settings.NMI_API_HOST = "secure.vaultixpay.com"
    assert gw.card_form() == {"kind": "collect",
                              "script_url": "https://secure.vaultixpay.com/token/Collect.js"}


def test_a_sandbox_account_keeps_the_component_whatever_the_host(settings):
    settings.NMI_API_HOST = "secure.vaultixpay.com"
    assert gw.card_form("sandbox") == {"kind": "component"}


@pytest.mark.django_db
def test_every_card_form_is_told_which_form(settings, billing, fcc, ff, api,  # noqa: F811
                                            seeded_tenant):
    from apps.billing.models import PaymentAccount

    settings.NMI_API_HOST = "secure.vaultixpay.com"
    component = {"kind": "component"}
    portal = f"/api/portal-invoices/{billing.pk}/pay/"
    assert api.as_(fcc).get(portal).json()["card_form"] == component     # sandbox account
    assert api.as_(fcc).get("/api/portal-autopay/").json()["card_form"] == component
    assert api.as_(ff).get("/api/subscription/").json()["card_form"] == component
    PaymentAccount.all_objects.filter(tenant=seeded_tenant).update(environment="live")
    settings.NMI_ENVIRONMENT = "live"
    want = gw.card_form("live")
    assert want["kind"] == "collect"
    assert api.as_(fcc).get(portal).json()["card_form"] == want
    assert api.as_(fcc).get("/api/portal-autopay/").json()["card_form"] == want
    assert api.as_(ff).get("/api/subscription/").json()["card_form"] == want


@pytest.mark.django_db
def test_a_collect_js_token_goes_to_the_same_sale(settings, billing, fcc, api,  # noqa: F811
                                                  stub_gateway):
    settings.NMI_API_HOST = "secure.vaultixpay.com"
    response = pay(api, fcc, billing, token="collect-js-token")
    assert response.status_code == 200 and response.json()["status"] == A.APPROVED
    [sale] = sales(stub_gateway)
    assert sale[2]["payment_token"] == "collect-js-token"


# ============================================= production never gets the stub

@pytest.mark.django_db
def test_production_with_real_calls_off_never_gets_the_stub(settings, stub_gateway):
    settings.APP_ENVIRONMENT = "production"
    settings.NMI_ENVIRONMENT = "live"
    assert not isinstance(gw.gateway(), StubGateway)
    assert gw.paused() and gw.paused_reason() == "off" and gw.mode() == "off"
    for call in (lambda g: g.sale(LIVE, amount_cents=100, reference="r", payment_token="t"),
                 lambda g: g.check_connection(LIVE),
                 lambda g: g.find_by_reference(LIVE, "r")):
        with pytest.raises(gw.CardPaymentsPaused):
            call(gw.gateway())
    assert stub_gateway.calls == []


@pytest.mark.django_db
def test_the_demo_and_the_laptop_keep_the_stub(settings):
    for where in ("local", "demo"):
        settings.APP_ENVIRONMENT = where
        assert isinstance(gw.gateway(), StubGateway) and not gw.paused()


@pytest.mark.django_db
def test_paused_portal_shows_the_words_and_charges_nothing(settings, billing, fcc,  # noqa: F811
                                                           api, stub_gateway):
    before = list(stub_gateway.calls)
    settings.APP_ENVIRONMENT = "production"
    row = portal_row(api, fcc, billing)
    assert row["can_pay"] is False and row["pay_paused"] is True
    config = api.as_(fcc).get(f"/api/portal-invoices/{billing.pk}/pay/")
    assert config.status_code == 409 and config.json()["detail"] == gw.PAUSED_MESSAGE
    response = pay(api, fcc, billing)
    assert response.status_code == 409 and response.json()["detail"] == gw.PAUSED_MESSAGE
    billing.refresh_from_db()
    assert billing.status != ClientInvoice.Status.PAID
    assert not PaymentAttempt.all_objects.exists() and not ClientPayment.all_objects.exists()
    assert stub_gateway.calls == before


@pytest.mark.django_db
def test_paused_pay_link_shows_the_words_and_charges_nothing(settings, connected, ff, api,
                                                             anyone, stub_gateway):  # noqa: F811
    company, contact = a_client(connected)
    invoice = ClientInvoice.all_objects.get(pk=sent(api, ff, company, contact)["id"])
    token = token_in(invoice_email(invoice).body_text)
    before = list(stub_gateway.calls)
    settings.APP_ENVIRONMENT = "production"
    page = anyone.get(f"/api/pay/{token}").json()
    assert page["notice"] == gw.PAUSED_MESSAGE and page["public_key"] == ""
    response = anyone.post(f"/api/pay/{token}", json.dumps({"payment_token": "tok"}),
                           content_type="application/json")
    assert response.status_code == 409 and response.json()["detail"] == gw.PAUSED_MESSAGE
    invoice.refresh_from_db()
    assert invoice.status != ClientInvoice.Status.PAID
    assert not PaymentAttempt.all_objects.exists() and stub_gateway.calls == before


@pytest.mark.django_db
def test_paused_auto_pay_charges_nothing_and_tells_no_one(settings, connected, fcc, ff, api,
                                                          stub_gateway):  # noqa: F811
    from .test_autopay import contact as _  # noqa: F401
    from .factories import ContactEmailFactory, ContactFactory

    person = ContactFactory(tenant=connected, first_name="Dana", last_name="Reyes",
                            company=fcc.client_company)
    ContactEmailFactory(tenant=connected, contact=person, is_primary=True,
                        address="dana@client.invalid")
    assert save_client_card(api, fcc).status_code == 200
    assert turn_on(api, fcc).status_code == 200
    invoice = send_invoice(api, ff, fcc, person)
    today = due_today(invoice)
    before = OutboxMessage.all_objects.count()
    settings.APP_ENVIRONMENT = "production"
    with tenant_context(connected.pk):
        assert autopay.run(connected, today=today)["charged"] == 0
    assert not PaymentAttempt.all_objects.exists() and sales(stub_gateway) == []
    assert OutboxMessage.all_objects.count() == before
    shown = api.as_(fcc).get("/api/portal-autopay/").json()
    assert shown["paused"] is True and shown["public_key"] == ""
    refused = save_client_card(api, fcc, "tok-new")
    assert refused.status_code == 503 and refused.json()["detail"] == gw.PAUSED_MESSAGE
    assert ClientPaymentMethod.all_objects.filter(removed_at__isnull=True).count() == 1


@pytest.mark.django_db
def test_paused_subscription_is_not_charged_failed_or_past_due(settings, carded, ff, api,
                                                               stub_gateway):  # noqa: F811
    settings.APP_ENVIRONMENT = "production"
    day = next_first()
    with tenant_context(carded.pk):
        assert subscriptions.run(carded, today=day)["charged"] == 0
    invoice = PracticeInvoice.all_objects.get(tenant=carded)
    assert invoice.status == PracticeInvoice.Status.OPEN and invoice.charge_tries == 0
    assert invoice.charge_state == "" and invoice.last_charge_text == ""
    row = PracticeSubscription.all_objects.get(tenant=carded)
    assert row.status == PracticeSubscription.Status.ACTIVE
    assert sales(stub_gateway) == []
    refused = post(api, ff, "/api/subscription/pay-now/")
    assert refused.status_code == 503 and refused.json()["detail"] == gw.PAUSED_MESSAGE
    assert save_subscription_card(api, ff, "tok-2").status_code == 503
    shown = api.as_(ff).get("/api/subscription/").json()
    assert shown["paused"] is True and shown["public_key"] == ""
    # Resumed, the next daily run charges it.
    settings.APP_ENVIRONMENT = "local"
    with tenant_context(carded.pk):
        assert subscriptions.run(carded, today=day)["charged"] == 1


@pytest.mark.django_db
def test_paused_lookups_and_read_back_settle_nothing(settings, billing, fcc, api,  # noqa: F811
                                                     seeded_tenant, stub_gateway):
    with tenant_context(seeded_tenant.pk):
        attempt = card_payments.start(billing, payer=fcc.user)
        PaymentAttempt.all_objects.filter(pk=attempt.pk).update(status=A.UNKNOWN)
    before = list(stub_gateway.calls)
    settings.APP_ENVIRONMENT = "production"
    with tenant_context(seeded_tenant.pk):
        assert card_payments.resolve_unknown(seeded_tenant) == 0
        readback.read_back(seeded_tenant)
    attempt.refresh_from_db()
    assert attempt.status == A.UNKNOWN and not ClientPayment.all_objects.exists()
    assert not NmiEvent.all_objects.exists() and stub_gateway.calls == before


@pytest.mark.django_db
def test_paused_connection_test_says_why_and_saves_nothing(settings, seeded_tenant, ff, api):
    settings.APP_ENVIRONMENT = "production"
    response = post(api, ff, "/api/payment-account/",
                    {"environment": "live", "private_key": "a-private", "public_key": "a-public"})
    assert response.status_code == 400 and "Real calls to NMI are off" in response.json()["detail"]
    state = api.as_(ff).get("/api/payment-account/").json()
    assert state["paused"] == "off" and state["gateway"] == "off" and state["ready"] is False


@pytest.mark.django_db
def test_nothing_is_marked_paid_without_a_real_answer_when_live(settings, billing, fcc, ff,
                                                                api, carded, stub_gateway,
                                                                anyone):  # noqa: F811
    """Every path that could mark something paid, in production with the
    environment live and real calls off: none does, and the stub is never
    asked anything."""
    company, contact = a_client(billing.tenant)
    linked = ClientInvoice.all_objects.get(pk=sent(api, ff, company, contact)["id"])
    token = token_in(invoice_email(linked).body_text)
    before = list(stub_gateway.calls)
    settings.APP_ENVIRONMENT = "production"
    settings.NMI_ENVIRONMENT = "live"
    tenant = billing.tenant
    pay(api, fcc, billing)
    anyone.post(f"/api/pay/{token}", json.dumps({"payment_token": "t"}),
                content_type="application/json")
    with tenant_context(tenant.pk):
        autopay.run(tenant, today=timezone.localdate())
        card_payments.resolve_unknown(tenant)
        subscriptions.run(tenant, today=next_first())
        subscriptions.resolve_unknown(tenant)
        readback.read_back(tenant)
    post(api, ff, "/api/subscription/pay-now/")
    assert not ClientInvoice.all_objects.filter(status=ClientInvoice.Status.PAID).exists()
    assert not ClientPayment.all_objects.exists()
    assert not PracticeInvoice.all_objects.filter(status=PracticeInvoice.Status.PAID).exists()
    assert not PaymentAttempt.all_objects.filter(status=A.APPROVED).exists()
    assert stub_gateway.calls == before


# ============================================================ the switch

@pytest.mark.django_db
def test_the_switch_holds_charges_while_reads_go_on(settings, billing, fcc, api,  # noqa: F811
                                                    stub_gateway, real_calls):
    settings.APP_ENVIRONMENT = "production"
    held_on()
    before = len(stub_gateway.calls)
    assert gw.paused() and gw.paused_reason() == "held"
    g = gw.gateway()
    with pytest.raises(gw.CardPaymentsPaused):
        g.sale(LIVE, amount_cents=100, reference="r", payment_token="t")
    with pytest.raises(gw.CardPaymentsPaused):
        g.vault_add(LIVE, payment_token="t", billing=gw.Billing("A", "B"))
    with pytest.raises(gw.CardPaymentsPaused):
        g.refund(LIVE, transaction_id="1", amount_cents=100)
    assert g.check_connection(LIVE).ok
    g.find_by_reference(LIVE, "r")
    assert [c[0] for c in stub_gateway.calls[before:]] == ["check_connection",
                                                           "find_by_reference"]
    assert portal_row(api, fcc, billing)["pay_paused"] is True
    assert pay(api, fcc, billing).json()["detail"] == gw.PAUSED_MESSAGE
    assert sales(stub_gateway) == [] and not PaymentAttempt.all_objects.exists()


@pytest.mark.django_db
def test_paused_between_the_check_and_the_sale_leaves_no_attempt(settings, billing, fcc,  # noqa: F811
                                                                 seeded_tenant, monkeypatch,
                                                                 stub_gateway):
    with tenant_context(seeded_tenant.pk):
        attempt = card_payments.start(billing, payer=fcc.user)
    held_on()   # the switch goes on after the attempt was written
    with tenant_context(seeded_tenant.pk), pytest.raises(card_payments.PaymentRefused) as exc:
        card_payments._charge(attempt, payment_token="tok")
    assert str(exc.value) == gw.PAUSED_MESSAGE
    assert not PaymentAttempt.all_objects.filter(pk=attempt.pk).exists()
    billing.refresh_from_db()
    assert billing.status != ClientInvoice.Status.PAID and sales(stub_gateway) == []


@pytest.mark.django_db
def test_only_the_platform_owner_in_the_practices_area_turns_the_switch(api, platform_owner,
                                                                        seeded_tenant):  # noqa: F811
    from .conftest import _member

    url = "/api/platform/card-payments/"
    assert post(api, _member(seeded_tenant, "FF"), url, {"paused": True}).status_code == 403
    assert api.as_(platform_owner).post(url, {"paused": True},
                                        content_type="application/json").status_code == 403
    client = practices(api, platform_owner)
    assert client.get(url).json()["paused"] == ""
    on = client.post(url, json.dumps({"paused": True}), content_type="application/json").json()
    assert on["paused"] == "held" and on["held"] is True and on["changed_by"]
    assert on["api_host"] == "secure.nmi.com" and on["card_form"] == "component"
    assert gw.paused()
    off = client.post(url, json.dumps({"paused": False}), content_type="application/json")
    assert off.json()["paused"] == "" and not gw.paused()
    assert client.post(url, json.dumps({"paused": "yes"}),
                       content_type="application/json").status_code == 400
