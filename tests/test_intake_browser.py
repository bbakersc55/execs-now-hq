"""Intake forms in a real browser (owner, 2026-11-20, after intake #1 lost its
door code to a Save button nobody pressed): Chrome, driven by Playwright,
against a live server with both bundles built from this tree and the fake
Track (tests/intake_fake_track.py) behind it.

The owner types each sensitive value and presses nothing else, no Save, no
Tab, no Enter: straight on to Continue, to the end, and Submit. A reviewer
then picks the area and presses Send to Track, and the fake Track holds every
value as typed. A second walk: a closet that opens with a key asks for no
code, and no code step is planned for it.

Needs the laptop's Google Chrome and the frontend's node_modules, like the
production proof (scripts/nmi_token_proof.py).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
from django.conf import settings as dj_settings
from django.test import Client

from apps.intake import links, tasks
from apps.intake.models import SendRun, Submission, SubmissionSecret

from . import registry_config  # noqa: F401
from .test_intake_flow import fake, world  # noqa: F401
from .test_intake_plan import answers as full_answers

pytestmark = pytest.mark.django_db(transaction=True)
FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
TITLES = {"tax": "Tax details", "property": "The property", "bedrooms": "Bedrooms",
          "other_sleeping": "Other places people sleep", "bathrooms": "Bathrooms",
          "amenities": "Amenities", "home": "Home details", "access": "Getting in",
          "stays": "Your own stays", "documents": "Documents", "review": "Review and submit"}


@pytest.fixture(scope="module")
def bundles(tmp_path_factory):
    """The app and the owner's form, built from this tree (about 10 s): a
    bundle left in frontend/dist could be any age."""
    out = tmp_path_factory.mktemp("bundles")
    for args in (["--outDir", str(out)], ["--config", "vite.forms.config.ts",
                                          "--outDir", str(out / "forms")]):
        done = subprocess.run(["npx", "vite", "build", *args, "--emptyOutDir",
                               "--logLevel", "warn"], cwd=FRONTEND, capture_output=True,
                              text=True, timeout=300)
        assert done.returncode == 0, done.stdout + done.stderr
    return out


@pytest.fixture
def browser(bundles, settings, live_server, monkeypatch):
    from playwright.sync_api import sync_playwright

    settings.STATIC_ROOT = str(bundles)
    settings.STATICFILES_DIRS = [str(bundles)]
    settings.APP_ROOT_URL = "/"              # serve the built app, not the Vite dev server
    # Playwright's sync API runs an event loop on this thread; the test's own
    # database calls are still plain synchronous ones.
    monkeypatch.setenv("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    # The worker, at once and in the request: Send returns once the send ran.
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


def start(world, live_server, access):
    """An intake with every answer in but the sensitive ones and getting in."""
    c = Client()
    c.force_login(world["fcc"].user)
    r = c.post(f"/api/intake/companies/{world['company'].pk}/submissions",
               {"first_name": "Alex", "last_name": "Sample", "email": "alex@samplehomes.net"},
               content_type="application/json")
    sub = Submission.all_objects.get(pk=r.json()["id"])
    token = links.token_of(sub)
    a = full_answers()
    a["access"] = access
    for section, value in a.items():
        r = Client().patch(f"/api/f/{token}/answers",
                           json.dumps({"section": section, "value": value}),
                           content_type="application/json")
        assert r.status_code == 200, r.content
    return sub, f"{live_server.url}/forms/{world['form'].slug}/{token}"


def heading(page):
    return page.get_by_role("heading", level=1)


def type_in(page, label, value):
    """Typed key by key, and nothing pressed after it."""
    page.get_by_label(label, exact=True).press_sequentially(value, delay=20)


def go_on(page, to):
    from playwright.sync_api import expect

    page.get_by_role("button", name="Continue").click()
    expect(heading(page)).to_have_text(TITLES[to])


def submit(page):
    from playwright.sync_api import expect

    page.get_by_role("button", name="Submit").click()
    expect(heading(page)).to_have_text(re.compile(r"^Thank you"))


def review_and_send(browser, world, live_server, sub):
    """The reviewer, signed in: picks the area, presses Send to Track."""
    from playwright.sync_api import expect

    c = Client()
    c.force_login(world["fcc"].user)
    context = browser.new_context(service_workers="block")
    context.add_cookies([{"name": dj_settings.SESSION_COOKIE_NAME,
                          "value": c.cookies[dj_settings.SESSION_COOKIE_NAME].value,
                          "url": live_server.url}])
    page = context.new_page()
    page.goto(f"{live_server.url}/intake/{sub.pk}")
    page.get_by_label("Area (Track's node)").select_option("24")
    send = page.get_by_role("button", name="Send to Track")
    expect(send).to_be_enabled()
    send.click()
    expect(page.get_by_role("heading", name="Sent to Track")).to_be_visible(timeout=20000)
    context.close()


def test_codes_typed_and_nothing_else_pressed_reach_track(world, fake, browser, live_server):
    sub, url = start(world, live_server, {"door": "keypad", "owner_closet": "code",
                                          "alarm": "code", "extra_codes": []})
    page = browser.new_page()
    page.goto(url + "#tax")
    type_in(page, "Business Tax ID (EIN)", "12-3456789")
    for step in ("property", "bedrooms", "other_sleeping", "bathrooms", "amenities", "home"):
        go_on(page, step)
    type_in(page, "Wi-Fi password", "powder-day")
    go_on(page, "access")
    type_in(page, "Door code", "4821")
    type_in(page, "Owner's closet code", "7730")
    type_in(page, "Alarm code", "1199")
    go_on(page, "stays")                         # straight from the last key to Continue
    go_on(page, "documents")
    go_on(page, "review")
    assert "Not entered yet" not in page.inner_text("main")
    submit(page)
    page.close()
    sub.refresh_from_db()
    assert sub.status == Submission.Status.SUBMITTED
    assert SubmissionSecret.all_objects.filter(submission=sub).count() == 5

    review_and_send(browser, world, live_server, sub)
    run = SendRun.all_objects.get(submission=sub)
    assert run.state == SendRun.State.SUCCEEDED, run.error
    [unit] = [u for u in fake.units.values() if u["name"] == "400 Lift Road"]
    codes = sorted((x["codeTypeId"], x["code"]) for x in fake.codes.values()
                   if x["unitId"] == unit["id"])
    assert codes == [(1, "4821"), (6, "1199"), (7, "7730")]   # door, alarm, owner closet
    [owner] = [o for o in fake.owners.values() if o["name"] == "Sample Homes LLC"]
    assert owner["taxIdMasked"] == "**-***6789"
    assert unit["custom"]["pms_units_wifi_password"] == "powder-day"
    assert not SubmissionSecret.all_objects.filter(submission=sub).exists()


def test_a_closet_that_opens_with_a_key_asks_for_no_code(world, fake, browser, live_server):
    from playwright.sync_api import expect

    sub, url = start(world, live_server, {"door": "keypad", "extra_codes": []})
    page = browser.new_page()
    page.goto(url + "#tax")
    type_in(page, "Business Tax ID (EIN)", "12-3456789")
    for step in ("property", "bedrooms", "other_sleeping", "bathrooms", "amenities", "home"):
        go_on(page, step)
    type_in(page, "Wi-Fi password", "powder-day")
    go_on(page, "access")
    type_in(page, "Door code", "4821")
    page.get_by_label("Yes, it opens with a key").check()
    expect(page.get_by_label("Owner's closet code", exact=True)).to_have_count(0)
    page.get_by_role("group", name="Does the property have an alarm?") \
        .get_by_label("No", exact=True).check()
    go_on(page, "stays")
    go_on(page, "documents")
    go_on(page, "review")
    assert "Not entered yet" not in page.inner_text("main")
    submit(page)
    page.close()
    sub.refresh_from_db()
    assert sub.answers["access"]["owner_closet"] == "key"

    review_and_send(browser, world, live_server, sub)
    run = SendRun.all_objects.get(submission=sub)
    assert run.state == SendRun.State.SUCCEEDED, run.error
    assert [s["key"] for s in run.steps if s["key"].startswith("code:")] == ["code:door"]
    assert [x["code"] for x in fake.codes.values()] == ["4821"]
