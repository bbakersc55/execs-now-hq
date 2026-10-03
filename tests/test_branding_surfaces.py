"""P1: the practice's branding on the surfaces a client receives — the email
footer, links and buttons (D4, D5), the pre-call invite, and the value report
PDF (until P1: Executives Now's colors, no logo, no practice name, raw codes).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import RequestFactory
from django.utils import timezone

from apps.crm.models import OutboxMessage
from apps.crm.services import email_layout
from apps.tenancy import contrast
from apps.work import value_pdf
from apps.work.models import GoalResolution

from . import registry_config  # noqa: F401
from .factories import (
    ClientCompanyFactory, GoalFactory, GoalMilestoneFactory, GoalResolutionFactory,
)

FOOTER = "Blue Sky Business Consulting\n12 Main St, Denver\nhttps://bluesky.example · hi@bluesky.example"


@pytest.fixture
def blue_sky(seeded_tenant):
    seeded_tenant.email_display_name = "Blue Sky"
    seeded_tenant.email_header_color = "#2E7D32"
    seeded_tenant.email_accent_color = "#F9A825"
    seeded_tenant.brand_footer_text = FOOTER
    seeded_tenant.save()
    return seeded_tenant


def message(tenant, producer, text="Hello.\n\nSee https://example.com"):
    return OutboxMessage(tenant=tenant, producer=producer, subject="Hi", body_text=text,
                         body_html="", to_address="dana@client.invalid")


# ------------------------------------------------------------------ the footer

@pytest.mark.django_db
@pytest.mark.parametrize("producer", ["manual", "referral_touch", "digest"])
def test_client_mail_carries_the_footer_in_both_parts(blue_sky, producer):
    html, text = email_layout.for_delivery(message(blue_sky, producer))
    assert "12 Main St, Denver" in html and "12 Main St, Denver" in text
    assert 'href="https://bluesky.example"' in html
    assert 'href="mailto:hi@bluesky.example"' in html


@pytest.mark.django_db
@pytest.mark.parametrize("producer", sorted(email_layout.INTERNAL_PRODUCERS))
def test_mail_only_staff_receive_has_no_client_footer(blue_sky, producer):
    html, text = email_layout.for_delivery(message(blue_sky, producer))
    assert "12 Main St" not in html and "12 Main St" not in text


@pytest.mark.django_db
def test_the_sign_in_email_carries_it_and_the_pin_reset_does_not(blue_sky):
    sign_in, sign_in_text = email_layout.action_link_email(
        blue_sky, subject="Sign in", heading="Sign in", paragraphs=[], button_label="Sign in",
        url="https://app.example/l/x", expiry="An hour.")
    assert "12 Main St" in sign_in
    reset, _ = email_layout.action_link_email(
        blue_sky, subject="PIN", heading="PIN", paragraphs=[], button_label="Clear",
        url="https://app.example/p/x", expiry="An hour.", internal=True)
    assert "12 Main St" not in reset


@pytest.mark.django_db
def test_the_footer_is_escaped(seeded_tenant):
    seeded_tenant.brand_footer_text = "<script>alert(1)</script> & Co"
    seeded_tenant.save()
    html, _ = email_layout.for_delivery(message(seeded_tenant, "manual"))
    assert "<script>alert" not in html and "&lt;script&gt;" in html


@pytest.mark.django_db
def test_no_footer_set_leaves_the_practice_name(seeded_tenant):
    html, text = email_layout.for_delivery(message(seeded_tenant, "digest"))
    assert seeded_tenant.name in html
    # Nothing added between the words and the unsubscribe line.
    assert text.startswith("Hello.\n\nSee https://example.com\n\n—\nUnsubscribe")


# ------------------------------------------------- D4: the accent is decoration only

@pytest.mark.django_db
def test_links_take_the_primary_color_and_buttons_readable_text(blue_sky):
    html, _ = email_layout.for_delivery(message(blue_sky, "manual"))
    assert 'href="https://example.com" style="color:#2E7D32' in html
    button, _ = email_layout.action_link_email(
        blue_sky, subject="Sign in", heading="Sign in", paragraphs=[], button_label="Sign in",
        url="https://app.example/l/x", expiry="An hour.")
    assert "background-color:#F9A825" in button
    assert f"color:{contrast.text_on('#F9A825')};text-decoration:none" in button
    assert contrast.text_on("#F9A825") == contrast.NEAR_BLACK


@pytest.mark.django_db
def test_the_pre_call_invite_button_is_the_practices_not_executives_nows(blue_sky):
    from apps.strategy import emails

    from .factories import StrategySessionFactory

    session = StrategySessionFactory(tenant=blue_sky)
    *_, sent_html = emails._invite_body(session, "https://app.example/precall/t")
    assert "#F58220" not in sent_html and "background:#F9A825" in sent_html
    assert f"color:{contrast.NEAR_BLACK}" in sent_html


# ------------------------------------------------------------------ the value report

@pytest.fixture
def report_request(blue_sky, ff):
    request = RequestFactory().get("/")
    request.user, request.membership, request.tenant = ff.user, ff, blue_sky
    return request


@pytest.mark.django_db
def test_the_value_report_wears_the_practices_brand(blue_sky, report_request, in_tenant_a):
    company = ClientCompanyFactory(tenant=blue_sky, name="Acme Facilities")
    GoalFactory(tenant=blue_sky, client_company=company, title="Stop the invoice stall")
    html = value_pdf.render_html(report_request, company=company)
    assert '<span class="practice">Blue Sky</span>' in html
    assert "#2E7D32" in html and "#F9A825" in html
    assert "#0A3A65" not in html and "#F58220" not in html


@pytest.mark.django_db
def test_the_value_report_shows_labels_not_codes(blue_sky, report_request, in_tenant_a):
    company = ClientCompanyFactory(tenant=blue_sky)
    goal = GoalFactory(tenant=blue_sky, client_company=company, title="Hire a COO")
    GoalResolutionFactory(tenant=blue_sky, goal=goal,
                          resolution=GoalResolution.Resolution.CHANGED_COURSE,
                          reason="The board chose a part-time hire.")
    GoalMilestoneFactory(tenant=blue_sky, goal=goal, title="Shortlist",
                         due_date=timezone.localdate() - timedelta(days=3))
    html = value_pdf.render_html(report_request, company=company)
    assert "Changed course" in html and "changed_course" not in html
    assert ">Late<" in html and ">late<" not in html
