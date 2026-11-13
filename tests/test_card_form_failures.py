"""A card form that would not load is never silent (2026-11-13).

On 2026-11-13 a live pay page on the processor's white-label host showed
"The card form could not be loaded" and told no one: Collect.js had refused
a data attribute on its own script tag. The fix is in the frontend
(`NmiCardForm.tsx`, and its tests). These are the server's half: wherever a
card form is used, a form that fails is reported, the practice owner (or, for
a subscription card, the platform owner) gets one Notice a day for it, and
the payer is answered with words they can act on.

No test reaches NMI (the stub gateway, always).
"""

from __future__ import annotations

import json

import pytest
from django.core.cache import cache
from django.test import override_settings

from apps.accounts.ratelimit import RateLimit
from apps.billing import gateway as gw
from apps.billing import services, views_pay
from apps.notify import service as notify
from apps.notify.models import Kind, Notice
from apps.tenancy.models import AuditEvent
from config.branding import PRODUCT_NAME

from . import registry_config  # noqa: F401
from .conftest import _member
from .test_card_payments import billing  # noqa: F401  (a fixture)
from .test_card_payments import _after_commit_now  # noqa: F401  (autouse)
from .test_client_invoicing import ready_to_bill  # noqa: F401  (a fixture)
from .test_client_invoicing import post
from .test_pay_links import anyone, connected, linked  # noqa: F401  (fixtures)
from .test_subscriptions import platform_practice  # noqa: F401  (a fixture)

HOW_TO_PAY = "Bank transfer to Example Bank, account ending 4421."
#: What the live page's console said, with a key-shaped string in it.
LIVE_ERROR = ("Uncaught Error: You provided too many fields. Unexpected fields for "
              "collectJs (key abcdef-ghijkl-mnopqr-stuvwx)")


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    cache.clear()
    yield
    cache.clear()


def report_link(anyone, token, body=None):  # noqa: F811
    return anyone.post(f"/api/pay/{token}/form-failed",
                       data=json.dumps(body if body is not None else {
                           "form": "collect", "host": "secure.vaultixpay.com",
                           "reason": LIVE_ERROR}),
                       content_type="application/json")


def notices(tenant=None, **filters):
    rows = Notice.all_objects.filter(kind=Kind.PAYMENTS, **filters)
    return list(rows.filter(tenant=tenant) if tenant is not None else rows)


# ------------------------------------------------------------ the pay link

@pytest.mark.django_db
def test_a_pay_link_form_that_fails_tells_the_owner_once_a_day_and_the_payer_what_to_do(
        linked, anyone, ff, seeded_tenant, tenant_b):  # noqa: F811
    invoice, token = linked
    cf, va = _member(seeded_tenant, "CF"), _member(seeded_tenant, "VA")
    other_owner = _member(tenant_b, "FF")

    answer = report_link(anyone, token)
    assert answer.status_code == 200, answer.content
    said = answer.json()["message"]
    practice = services.practice_name(seeded_tenant)
    assert said == (f"The card form could not be loaded, so nothing was charged. {practice} "
                    f"has been told. Please try again later, or pay another way: {HOW_TO_PAY}")

    # The practice owner, and no one else: not an associate, not an
    # assistant, never another practice's owner.
    [notice] = notices()
    assert notice.tenant_id == seeded_tenant.pk and notice.recipient_id == ff.user_id
    assert notice.title == "A card form didn't load"
    assert notice.url == f"/invoices/{invoice.pk}"
    assert f"invoice {invoice.number}" in notice.text
    assert "Collect.js from secure.vaultixpay.com" in notice.text
    assert "Unexpected fields for collectJs" in notice.text and "Nothing was charged" in notice.text
    # What the browser said is kept as text, and nothing shaped like a key.
    assert "abcdef-ghijkl" not in notice.text and "[key]" in notice.text
    for nobody in (cf, va, other_owner):
        assert not Notice.all_objects.filter(recipient=nobody.user).exists()

    # Every report is in the audit; the Notice is once a day for the invoice.
    assert report_link(anyone, token).status_code == 200
    assert len(notices()) == 1
    audit = AuditEvent.all_objects.filter(verb="billing.card_form_failed")
    assert audit.count() == 2
    payload = audit.first().payload
    assert payload["where"] == "link" and payload["invoice"] == invoice.number
    assert "abcdef-ghijkl" not in json.dumps(payload)


@pytest.mark.django_db
def test_a_wrong_or_voided_link_is_the_same_404_and_tells_no_one(linked, anyone, ff,  # noqa: F811
                                                                 api):
    invoice, token = linked
    assert report_link(anyone, token[:-2] + "zz").status_code == 404
    assert post(api, ff, f"/api/invoices/{invoice.pk}/void/",
                {"reason": "Sent to the wrong person"}).status_code == 200
    assert report_link(anyone, token).status_code == 404
    assert notices() == []
    assert not AuditEvent.all_objects.filter(verb="billing.card_form_failed").exists()


@pytest.mark.django_db
def test_reports_on_a_link_are_counted_like_its_views(linked, anyone, monkeypatch):  # noqa: F811
    _, token = linked
    monkeypatch.setattr(views_pay, "_VIEWS_PER_LINK",
                        RateLimit(limit=2, window_seconds=3600, prefix="pay-link-test"))
    assert report_link(anyone, token).status_code == 200
    assert report_link(anyone, token).status_code == 200
    assert report_link(anyone, token).status_code == 429
    assert AuditEvent.all_objects.filter(verb="billing.card_form_failed").count() == 2


@pytest.mark.django_db
def test_what_the_browser_sends_is_only_ever_text(linked, anyone):  # noqa: F811
    _, token = linked
    assert report_link(anyone, token, {"form": "<script>", "host": "evil.example",
                                       "reason": "a\x00b\n" + "x" * 1000}).status_code == 200
    assert report_link(anyone, token, ["not", "an", "object"]).status_code == 200
    [notice] = notices()
    assert "(the card form)" in notice.text and "evil.example" not in notice.text
    reasons = [e.payload["reason"] for e in
               AuditEvent.all_objects.filter(verb="billing.card_form_failed")]
    assert all(len(r) <= 300 and "\x00" not in r for r in reasons)
    assert "No reason was given." in reasons


# ---------------------------------------------------------- the portal's Pay

@pytest.mark.django_db
def test_the_portals_pay_reports_for_either_client_role_and_no_one_else(
        billing, fcc, ff, seeded_tenant, api):  # noqa: F811
    from .factories import ClientCompanyFactory

    url = f"/api/portal-invoices/{billing.pk}/form-failed/"
    body = {"form": "collect", "host": "secure.vaultixpay.com", "reason": "no fields"}
    answer = post(api, fcc, url, body)
    assert answer.status_code == 200, answer.content
    assert answer.json()["message"].endswith(f"pay another way: {HOW_TO_PAY}")
    ecc = _member(seeded_tenant, "ECC", company=fcc.client_company)
    assert post(api, ecc, url, body).status_code == 200
    [notice] = notices(seeded_tenant)
    assert notice.recipient_id == ff.user_id and notice.url == f"/invoices/{billing.pk}"
    assert notice.text.startswith("A client in the portal couldn't load the card form")
    # Another company's client, and practice staff, have no such invoice here.
    stranger = _member(seeded_tenant, "FCC", company=ClientCompanyFactory(tenant=seeded_tenant))
    assert post(api, stranger, url, body).status_code == 404
    assert post(api, ff, url, body).status_code == 404


# ------------------------------------------------------ saving a card (auto-pay)

@pytest.mark.django_db
def test_saving_a_card_reports_for_the_client_owner_only(billing, fcc, ff, seeded_tenant,  # noqa: F811
                                                         api):
    url = "/api/portal-autopay/form-failed/"
    ecc = _member(seeded_tenant, "ECC", company=fcc.client_company)
    assert post(api, ecc, url, {"form": "collect"}).status_code == 403
    answer = post(api, fcc, url, {"form": "collect", "reason": "no fields"})
    assert answer.status_code == 200
    practice = services.practice_name(seeded_tenant)
    assert answer.json()["message"] == (
        f"The card form could not be loaded, so no card was saved. {practice} has been told. "
        "Please try again later.")
    [notice] = notices(seeded_tenant)
    assert notice.recipient_id == ff.user_id
    assert notice.url == f"/companies/{fcc.client_company_id}"
    assert "to save a card for auto-pay" in notice.text


# --------------------------------------------------- a practice's subscription card

@pytest.mark.django_db
def test_a_subscription_card_form_tells_the_platform_owner_not_the_practice(
        seeded_tenant, ff, api, platform_practice, tenant_b):  # noqa: F811
    url = "/api/subscription/form-failed/"
    assert post(api, _member(seeded_tenant, "VA"), url, {}).status_code == 403
    answer = post(api, ff, url, {"form": "collect", "host": "secure.vaultixpay.com",
                                 "reason": "no fields"})
    assert answer.status_code == 200
    assert answer.json()["message"] == (
        f"The card form could not be loaded, so no card was saved. {PRODUCT_NAME} has been "
        "told. Please try again later.")
    [notice] = notices()
    assert notice.tenant_id == tenant_b.pk and notice.recipient_id == platform_practice.user_id
    assert notice.title == "A subscription card form didn't load"
    assert services.practice_name(seeded_tenant) in notice.text
    assert notice.url == "/practices"


@pytest.mark.django_db
def test_a_signed_in_payer_is_limited_too(billing, fcc, api, monkeypatch):  # noqa: F811
    from apps.billing import views

    monkeypatch.setattr(views, "_FORM_FAILED",
                        RateLimit(limit=1, window_seconds=3600, prefix="form-failed-test"))
    url = f"/api/portal-invoices/{billing.pk}/form-failed/"
    assert post(api, fcc, url, {}).status_code == 200
    assert post(api, fcc, url, {}).status_code == 429


# ------------------------------------------------------- who can be told

@pytest.mark.django_db
def test_only_a_practice_owner_has_the_payments_kind(seeded_tenant, ff, fcc):
    assert "payments" in notify.kinds_for(ff)
    for role in ("CF", "VA"):
        assert "payments" not in notify.kinds_for(_member(seeded_tenant, role))
    assert "payments" not in notify.kinds_for(fcc)


# ---------------------------------------------- the proof's form, on the laptop

def test_a_sandbox_account_can_be_given_collect_js_for_a_proof():
    with override_settings(NMI_SANDBOX_CARD_FORM_HOST=""):
        assert gw.card_form("sandbox") == {"kind": "component"}
    for host in gw.API_HOSTS:
        with override_settings(NMI_SANDBOX_CARD_FORM_HOST=host):
            assert gw.card_form("sandbox") == {
                "kind": "collect", "script_url": f"https://{host}/token/Collect.js"}
    # A live account's form follows NMI_API_HOST alone.
    with override_settings(NMI_SANDBOX_CARD_FORM_HOST="secure.nmi.com",
                           NMI_API_HOST="secure.vaultixpay.com"):
        assert gw.card_form("live") == {
            "kind": "collect", "script_url": "https://secure.vaultixpay.com/token/Collect.js"}
    with override_settings(NMI_SANDBOX_CARD_FORM_HOST="evil.example"):
        assert gw.card_form("sandbox") == {"kind": "component"}
