"""The Oct 26 polish (owner): a goal's figures said the way a person reads
them; an introduction as one email to both, with one recipient check per
address; and the NMI read-back of the platform's own account, for the
practices' subscription charges.
"""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.billing import readback, subscriptions
from apps.billing.gateway import Account
from apps.billing.models import NmiEvent, PracticeInvoice
from apps.crm.models import OutboxMessage
from apps.crm.services import outbox, unsubscribe
from apps.tenancy.context import tenant_context
from apps.work.figures import figure, unit_after

from . import registry_config  # noqa: F401
from .test_introductions import cast, introduce, person, post  # noqa: F401
from .test_subscriptions import carded, next_first, platform_practice, run  # noqa: F401

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------- figures

def test_a_goals_figures_read_as_a_person_says_them():
    assert figure("54.0000", "%") == "54%" and figure("90.0000", "%") == "90%"
    assert figure("1250.5000", "sites") == "1,250.5" and unit_after("sites") == "sites"
    assert figure("1200", "$") == "$1,200" and unit_after("$") == ""
    assert figure(None) == "" and figure("0.3333") == "0.33"


def test_the_value_report_carries_the_figures_as_text(seeded_tenant, in_tenant_a, ff):
    from apps.work.models import Goal, GoalMeasurement
    from apps.work.value_report import measure_block

    goal = Goal.objects.create(tenant=seeded_tenant, title="Next-day delivery", owner=ff.user,
                               measurable_kind="numeric", measurable="Next day", direction="up_is_good",
                               measurable_unit="%", baseline_value=Decimal("54"),
                               target_value=Decimal("90"))
    GoalMeasurement.objects.create(tenant=seeded_tenant, goal=goal, value=Decimal("71.5"),
                                   measured_at=timezone.localdate())
    goal.refresh_from_db()
    m = measure_block(goal)
    assert (m["baseline"]["text"], m["current"]["text"], m["target_text"]) == ("54%", "71.5%", "90%")
    assert m["unit_after"] == "" and m["baseline"]["value"] == "54.0000"   # the API keeps its decimals


# ---------------------------------------------------------------- one email to both

def test_one_email_to_both_is_one_draft_with_two_recipients(cast, ff, api, dev_outbox):  # noqa: F811
    made = post(api.as_(ff), "/api/introductions/", {
        "partner": str(cast["maya"].pk), "to": str(cast["dana"].pk), "together": True,
        "note": "Dana is launching in the spring."})
    assert made.status_code == 201, made.content
    assert made.json()["drafts"] == 1
    [draft] = OutboxMessage.all_objects.filter(producer="introduction")
    assert (draft.to_address, draft.also_to_address) == ("maya@chen.invalid", "dana@reyes.invalid")
    assert draft.subject == "Introducing Maya and Dana"
    assert "Maya, meet Dana Reyes." in draft.body_text and "Dana, meet Maya Chen." in draft.body_text
    assert "Maya has launched more products" in draft.body_text
    assert "Her work focuses on Go to market, Social media ads." in draft.body_text
    # Both shown where it waits.
    row = api.as_(ff).get(f"/api/outbox/{draft.pk}/").json()
    assert row["also_to_address"] == "dana@reyes.invalid"
    with tenant_context(cast["t"].pk):
        outbox.approve(draft, actor=ff.user, role="FF")
    [sent] = dev_outbox
    assert sent.to == ["maya@chen.invalid", "dana@reyes.invalid"]


def test_each_address_is_checked_on_its_own(cast, ff, api, settings, dev_outbox):  # noqa: F811
    post(api.as_(ff), "/api/introductions/", {
        "partner": str(cast["maya"].pk), "to": str(cast["dana"].pk), "together": True})
    draft = OutboxMessage.all_objects.get(producer="introduction")
    # On the laptop, one address on the allow-list is not enough to send for real.
    settings.DEV_REAL_SEND_ALLOWLIST = ["maya@chen.invalid"]
    delivery = api.as_(ff).get(f"/api/outbox/{draft.pk}/").json()["delivery"]
    assert delivery["target"] == "dev" and "dana@reyes.invalid is not on" in delivery["detail"]
    # One person's unsubscribe stops an email to the two.
    from apps.crm.models import EmailSuppression

    OutboxMessage.all_objects.filter(pk=draft.pk).update(category="marketing")
    draft.refresh_from_db()
    EmailSuppression.all_objects.create(tenant=cast["t"], contact=cast["dana"],
                                        category="marketing")
    assert "Dana Reyes unsubscribed" in unsubscribe.refusal(draft)


def test_the_demo_sends_one_email_to_both_only_to_its_redirect(cast, ff, api, monkeypatch):  # noqa: F811
    from apps.crm.services import transport
    from config import environment

    post(api.as_(ff), "/api/introductions/", {
        "partner": str(cast["maya"].pk), "to": str(cast["dana"].pk), "together": True})
    draft = OutboxMessage.all_objects.get(producer="introduction")
    sent = []

    class Capture:
        def send(self, **kw):
            sent.append(kw)
            return {"provider": "gmail", "provider_message_id": "m1"}

    monkeypatch.setattr(environment, "is_demo", lambda: True)
    monkeypatch.setattr(outbox, "_demo_recipient", lambda tenant: "redirect@demo.invalid")
    monkeypatch.setattr(transport, "get_transport", lambda name=None: Capture())
    with tenant_context(cast["t"].pk):
        outbox.approve(draft, actor=ff.user, role="FF")
    [kw] = sent
    assert kw["to_address"] == "redirect@demo.invalid" and kw["also_to"] == ()
    # And the Gmail transport refuses a second address on the demo outright.
    gmail = transport.GmailTransport()
    with pytest.raises(transport.TransportUnavailable):
        monkeypatch.setattr(environment, "demo_redirect", lambda t: "redirect@demo.invalid")
        gmail.send(tenant=cast["t"], to_address="redirect@demo.invalid", subject="s",
                   body_text="b", thread=None, also_to=("dana@reyes.invalid",))


def test_two_emails_stay_the_default(cast, ff, api):  # noqa: F811
    assert introduce(api, ff, cast["maya"], cast["dana"]).json()["drafts"] == 2
    assert not OutboxMessage.all_objects.exclude(also_to_address="").exists()


# ---------------------------------------------------------------- the platform's read-back

def _charged(carded):  # noqa: F811
    run(carded, next_first())
    return PracticeInvoice.all_objects.get(tenant=carded)


PLATFORM = Account(environment="sandbox", private_key="x", public_key="y", label="platform")


def test_a_refund_of_a_subscription_charge_is_read_back_for_the_platform_owner(
        carded, ff, api, platform_practice, stub_gateway):  # noqa: F811
    invoice = _charged(carded)
    stub_gateway.portal_refund(PLATFORM, invoice.nmi_transaction_id, 500)
    counts = readback.read_back_platform()
    assert counts["matched"] == 1 and counts["flagged"] == 0
    [event] = NmiEvent.all_objects.filter(platform=True)
    assert event.tenant_id == carded.pk and event.practice_invoice_id == invoice.pk
    assert f"against subscription invoice {invoice.number}" in event.note
    # Once only.
    assert readback.read_back_platform()["matched"] == 0
    # Not in the practice's own list; on the platform owner's Practices screen.
    assert api.as_(ff).get("/api/nmi-events/").json() == []
    assert subscriptions.platform_summary(carded)["nmi_events"][0]["id"] == str(event.pk)
    # Marked as seen by the platform owner only.
    with tenant_context(platform_practice.tenant_id):
        from apps.platform.views import PlatformNmiEventView  # noqa: F401
    assert api.as_(ff).post(f"/api/platform/nmi-events/{event.pk}/seen").status_code in (403, 404)


def test_our_own_subscription_sale_is_not_an_event_and_an_unknown_one_is_flagged(
        carded, platform_practice, stub_gateway):  # noqa: F811
    _charged(carded)
    stub_gateway._act("platform", "999001", "sale", 2000, "sub-not-an-invoice")
    counts = readback.read_back_platform()
    assert counts["matched"] == 0 and counts["flagged"] == 1
    [event] = NmiEvent.all_objects.filter(platform=True)
    assert event.tenant_id == platform_practice.tenant_id and event.practice_invoice_id is None


def test_the_owners_practice_runs_the_platform_read_back_once_a_day(
        carded, platform_practice, stub_gateway):  # noqa: F811
    from apps.billing.tasks import read_back_nmi

    assert "platform" in read_back_nmi(str(platform_practice.tenant_id))
    assert "platform" not in read_back_nmi(str(carded.pk))
