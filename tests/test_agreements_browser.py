"""Owner agreements in a real browser (docs/p15_owner_agreements.md): Chrome,
driven by Playwright, against a live server with both bundles built from this
tree, and the fake Track behind it (nothing is written to it).

Walk 1, at phone width: a staff member with the agreements tick makes a new
owner's agreement, previews it and sends it by email; the owner opens the link,
reads it, fills in their section, consents, signs and chooses "Complete
onboarding now", and the intake form opens with their details in it. The
signer records a standing authorization; the staff member then applies the
signer's signature under it. Walk 2: another owner signs and chooses "Later".

Set AGREEMENT_WALK_DIR to a folder to keep a screenshot of every step (at
phone and desktop width) and the final signed PDF.
"""

from __future__ import annotations

import io
import os
import re
from pathlib import Path

import pytest
from django.conf import settings as dj_settings
from django.core.management import call_command
from django.test import Client

from apps.agreements import links
from apps.agreements.models import AgreementSignature, OwnerAgreement, OwnerEmail, Program, \
    StaffAccess
from apps.intake import tasks
from apps.tenancy.context import tenant_context

from . import registry_config  # noqa: F401
from .test_intake_browser import bundles  # noqa: F401
from .test_intake_flow import fake, world  # noqa: F401

pytestmark = pytest.mark.django_db(transaction=True)
PHONE = {"width": 390, "height": 844}
DESKTOP = {"width": 1280, "height": 900}
OUT = os.environ.get("AGREEMENT_WALK_DIR", "")


def shot(page, name):
    if OUT:
        Path(OUT).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(OUT) / f"{name}.png"), full_page=True)


@pytest.fixture
def browser(bundles, settings, live_server, monkeypatch):  # noqa: F811
    from playwright.sync_api import sync_playwright

    settings.STATIC_ROOT = str(bundles)
    settings.STATICFILES_DIRS = [str(bundles)]
    settings.APP_ROOT_URL = "/"
    # Links are made on the public address; here that is the live server.
    settings.PUBLIC_BASE_URL = live_server.url
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    monkeypatch.setenv("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    monkeypatch.setattr("django_q.tasks.async_task",
                        lambda name, tenant_id, run_id, **kw: tasks.run_send(tenant_id, run_id))
    # The form page is cached once per process; another test on this worker
    # may have cached one from a different build.
    from apps.intake import hosts

    hosts._built_index.cache_clear()
    with sync_playwright() as p:
        chrome = p.chromium.launch(channel="chrome", headless=True)
        yield chrome
        chrome.close()
    hosts._built_index.cache_clear()


@pytest.fixture
def people(world):
    company = world["company"]
    call_command("owner_agreements", str(company.pk), "on", stdout=io.StringIO())
    program = Program.all_objects.get(company=company)
    program.signer = world["fcc"].user
    program.save()
    world["fcc"].user.full_name = "Michael LeClerc"
    world["fcc"].user.save()
    world["manager"].user.full_name = "Jackie Example"
    world["manager"].user.save()
    StaffAccess.all_objects.filter(company=company, user=world["manager"].user).update(
        agreements=True, signed_pdfs=True, intake=True)
    return world


def staff(browser, live_server, membership, viewport):
    c = Client()
    c.force_login(membership.user)
    context = browser.new_context(service_workers="block", viewport=viewport)
    context.add_cookies([{"name": dj_settings.SESSION_COOKIE_NAME,
                          "value": c.cookies[dj_settings.SESSION_COOKIE_NAME].value,
                          "url": live_server.url}])
    return context, context.new_page()


def owner_page(browser, viewport):
    context = browser.new_context(service_workers="block", viewport=viewport)
    return context, context.new_page()


def fill_details(page):
    page.get_by_label("Phone", exact=True).fill("435-555-0123")
    page.get_by_label("Street", exact=True).fill("9 Elm St")
    page.get_by_label("City", exact=True).fill("Denver")
    page.get_by_label("State", exact=True).fill("CO")
    page.get_by_label("ZIP", exact=True).fill("80202")
    page.get_by_label("Bedrooms").fill("3")
    page.get_by_label("Bathrooms").fill("2.5")
    page.get_by_label("Square footage").fill("1850")
    page.get_by_label("Their name").fill("Jamie Sample")
    page.get_by_label("Their phone").fill("435-555-0188")


def sign(page):
    from playwright.sync_api import expect

    page.get_by_label("Your name, as your signature").fill("Alex Sample")
    page.get_by_label("I agree to sign electronically").check()
    shot(page, "05-owner-sign-phone")
    page.get_by_role("button", name="Sign the agreement").click()
    expect(page.get_by_role("heading", name="Thank you for signing!")).to_be_visible(
        timeout=30000)


def test_walk_new_owner_signs_now_then_jackie_countersigns_under_michaels_authority(
        people, fake, browser, live_server):
    from playwright.sync_api import expect

    w = people
    company = w["company"]
    writes = len(fake.writes())

    # Jackie, on a phone: a new owner, the terms, the preview, Send by email.
    context, page = staff(browser, live_server, w["manager"], PHONE)
    page.goto(f"{live_server.url}/agreements/new?company={company.pk}")
    page.get_by_label("Name", exact=True).fill("Alex Sample")
    page.get_by_label("Email", exact=True).fill("alex@samplehomes.net")
    page.get_by_label("Street", exact=True).fill("400 Lift Road")
    page.get_by_label("City", exact=True).fill("Park City")
    page.get_by_label("State", exact=True).fill("UT")
    page.get_by_label("ZIP", exact=True).fill("84060")
    page.get_by_label("Revenue threshold $").first.fill("4000")
    page.get_by_label("Fee $").first.fill("250")
    shot(page, "01-staff-new-owner-phone")
    page.get_by_role("button", name="Preview the agreement").click()
    expect(page.get_by_text("Preview: exactly what the owner reads")).to_be_visible()
    expect(page.get_by_text("MINIMUM REVENUE MANAGEMENT FEE: For each calendar month",
                            exact=False)).to_be_visible()
    shot(page, "02-staff-preview-phone")
    page.get_by_role("button", name="Send by email").click()
    expect(page.get_by_text("Emailed to the owner.")).to_be_visible()
    shot(page, "03-staff-sent-phone")
    context.close()
    a = OwnerAgreement.all_objects.get(company=company)
    assert OwnerEmail.all_objects.filter(agreement=a, kind="invite").exists()
    with tenant_context(a.tenant_id):
        url = f"{live_server.url}/forms/{w['form'].slug}/a/{links.ensure(a)}"

    # The owner, on a phone.
    context, page = owner_page(browser, PHONE)
    page.goto(url)
    expect(page.get_by_role("heading", name="Welcome, Alex!")).to_be_visible()
    expect(page.get_by_text("congratulations on your decision to rent it")).to_be_visible()
    shot(page, "04a-owner-welcome-phone")
    page.get_by_role("button", name="Read the agreement").click()
    expect(page.get_by_role("region", name="Your terms")).to_contain_text("70%")
    shot(page, "04b-owner-agreement-phone")
    page.get_by_role("button", name="Fill in your details").click()
    fill_details(page)
    shot(page, "04c-owner-details-phone")
    page.get_by_role("button", name="Continue to sign").click()
    sign(page)
    shot(page, "06-owner-signed-phone")
    page.get_by_role("button", name="Complete onboarding now").click()
    expect(page.get_by_role("heading", name="Welcome, Alex!")).to_be_visible(timeout=20000)
    assert "/a/" not in page.url                                    # the intake form now
    page.get_by_role("button", name="Let's start").click()
    expect(page.get_by_label("First name", exact=True)).to_have_value("Alex")
    expect(page.get_by_label("Mobile", exact=False).first).to_have_value("435-555-0123")
    shot(page, "07-owner-intake-prefilled-phone")
    context.close()

    # The same owner's pages at desktop width.
    context, page = owner_page(browser, DESKTOP)
    page.goto(url)
    expect(page.get_by_role("heading", name="Thank you for signing!")).to_be_visible()
    shot(page, "08-owner-after-signing-desktop")
    context.close()

    # Michael records his standing authorization (desktop).
    context, page = staff(browser, live_server, w["fcc"], DESKTOP)
    page.goto(f"{live_server.url}/agreements/authority/{company.pk}")
    page.get_by_label(re.compile(r"^Jackie Example")).check()
    page.get_by_label("Type your signature").fill("Michael LeClerc")
    page.get_by_label("I agree to sign electronically").check()
    shot(page, "09-michael-authorization-desktop")
    page.get_by_role("button", name="Record the authorization").click()
    expect(page.get_by_text("Recorded.")).to_be_visible()
    shot(page, "10-michael-recorded-desktop")
    context.close()

    # Jackie countersigns under it, on a phone.
    context, page = staff(browser, live_server, w["manager"], PHONE)
    page.goto(f"{live_server.url}/agreements/{a.pk}")
    button = page.get_by_role("button", name="Apply Michael LeClerc's signature")
    expect(button).to_be_disabled()
    page.get_by_label("I agree").check()
    shot(page, "11-jackie-countersign-phone")
    button.click()
    expect(page.get_by_text("Countersigned. The final copy went to the owner.")).to_be_visible(
        timeout=30000)
    shot(page, "12-jackie-countersigned-phone")
    context.close()
    context, page = staff(browser, live_server, w["manager"], DESKTOP)
    page.goto(f"{live_server.url}/agreements?company={company.pk}")
    shot(page, "13-staff-list-desktop")
    context.close()

    a.refresh_from_db()
    sig = AgreementSignature.all_objects.get(agreement=a, role="manager")
    assert sig.applied_by_id == w["manager"].user_id and sig.authority_id is not None
    if OUT:
        from apps.tenancy import storage

        Path(OUT, "sample_signed_agreement.pdf").write_bytes(storage.read(a.final_pdf))
        Path(OUT, "sample_owner_copy_awaiting.pdf").write_bytes(storage.read(a.owner_pdf))
    assert len(fake.writes()) == writes                            # nothing written to Track


def test_walk_owner_chooses_later(people, browser, live_server):
    from playwright.sync_api import expect

    w = people
    c = Client()
    c.force_login(w["manager"].user)
    import json

    r = c.post(f"/api/agreements/companies/{w['company'].pk}/agreements", json.dumps({
        "name": "Robin Later", "email": "robin@example.net", "phone": "",
        "terms": {"property_address": {"street": "12 Ridge Way", "city": "Park City",
                                       "state": "UT", "zip": "84060"}}}),
        content_type="application/json")
    a = OwnerAgreement.all_objects.get(pk=r.json()["id"])
    with tenant_context(a.tenant_id):
        url = f"{live_server.url}/forms/{w['form'].slug}/a/{links.ensure(a)}"
    context, page = owner_page(browser, PHONE)
    page.goto(url)
    page.get_by_role("button", name="Read the agreement").click()
    page.get_by_role("button", name="Fill in your details").click()
    fill_details(page)
    page.get_by_role("button", name="Continue to sign").click()
    sign(page)
    page.get_by_role("button", name="Later: email me the link").click()
    expect(page.get_by_text("We've emailed you the link")).to_be_visible()
    shot(page, "14-owner-later-phone")
    context.close()
    assert OwnerEmail.all_objects.filter(agreement=a, kind="intake_link").count() == 1
