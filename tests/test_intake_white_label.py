"""White label (owner, 2026-11-19): an owner sees nothing of Execs NOW HQ,
Executives Now, Noble Rose, the practice or anyone in it, on any page or
response the owner's form reaches: the form, its API, page titles, the tab
icon, error, expired-link, rate-limit and upload answers, the address, and the
form's own domain, where nothing else answers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone

from apps.intake import hosts, links, views_public
from apps.intake.models import Submission

from . import registry_config  # noqa: F401
from .test_intake_flow import fake, owner_fills, start, world  # noqa: F401

pytestmark = pytest.mark.django_db
DOMAIN = "owners.mountainstays.net"
BUILT = ('<!doctype html><html><head><meta charset="utf-8" /><title>Forms</title>'
         '<link rel="icon" href="/static/forms/x.svg" /><script type="module" '
         'src="/static/forms/assets/forms-abc.js"></script></head><body><div id="root">'
         '</div></body></html>')


def forbidden(world) -> list[str]:
    ff = world["ff"].user
    return ["execs now", "execsnow", "executives now", "noble rose", "getexecutivesnow",
            world["practice"].name.lower(), ff.full_name.lower(), ff.email.lower(),
            "execs-now"]


def clean(world, response, where):
    text = response.content.decode("utf-8", "replace").lower()
    headers = " ".join(f"{k}: {v}" for k, v in response.items()).lower()
    for word in forbidden(world):
        assert word not in text, f"{where}: {word!r} in the body"
        assert word not in headers, f"{where}: {word!r} in a header"


@pytest.fixture
def built(monkeypatch):
    monkeypatch.setattr(hosts, "_built_index", lambda: BUILT)


def walk(world, client, token, base):
    """Every owner-facing request the form makes, in the order an owner would."""
    seen = []

    def go(method, path, **kw):
        r = getattr(client, method)(path, **kw)
        seen.append((f"{method.upper()} {path}", r))
        return r

    go("get", f"{base}{token}")
    go("get", f"/api/f/{token}")
    go("patch", f"/api/f/{token}/answers",
       data=json.dumps({"section": "about", "value": {"first_name": "Alex"}}),
       content_type="application/json")
    go("patch", f"/api/f/{token}/answers", data=json.dumps({"section": "nope", "value": {}}),
       content_type="application/json")
    go("post", f"/api/f/{token}/secret",
       data=json.dumps({"kind": "tax_id", "value": "123-45-6789"}),
       content_type="application/json")
    go("post", f"/api/f/{token}/secret",
       data=json.dumps({"kind": "code", "slot": "door", "value": "4821"}),
       content_type="application/json")
    r = go("post", f"/api/f/{token}/files",
           data={"file": SimpleUploadedFile("page.pdf", b"%PDF-1.4 page")})
    go("post", f"/api/f/{token}/files",
       data={"file": SimpleUploadedFile("page.exe", b"MZ not allowed")})
    go("delete", f"/api/f/{token}/files/{r.json()['id']}")
    go("post", f"/api/f/{token}/submit")
    owner_fills(token)
    go("post", f"/api/f/{token}/submit")
    go("get", f"/api/f/{token}")
    go("post", f"/api/f/{token}/another")
    go("get", "/api/f/this-is-not-a-real-token-0000000000000")
    go("get", f"/api/forms/{world['form'].slug}/logo")
    go("get", f"/api/forms/{world['form'].slug}/icon")
    return seen


def test_every_owner_page_on_enhqs_host_is_white_label(world, built):
    sub, token = start(world)
    client = Client()
    for where, response in walk(world, client, token, f"/forms/{world['form'].slug}/"):
        clean(world, response, where)
    clean(world, client.get(f"/forms/{world['form'].slug}"), "the form with no token")
    clean(world, client.get(f"/forms/no-such-form/{token}"), "a slug that isn't a form")
    page = client.get(f"/forms/{world['form'].slug}/{token}").content.decode()
    assert "<title>New owner and property · Mountain Stays</title>" in page
    assert '<link rel="icon" href="data:image/svg+xml' in page and "Forms</title>" not in page


def test_expired_and_rate_limited_answers_are_white_label(world, built, monkeypatch):
    sub, token = start(world)
    Submission.all_objects.filter(pk=sub.pk).update(
        last_activity_at=timezone.now() - timezone.timedelta(days=40))
    r = Client().get(f"/api/f/{token}")
    assert r.status_code == 410
    clean(world, r, "an expired link")
    monkeypatch.setattr(views_public, "too_many_shared", lambda *a, **k: True)
    r = Client().get(f"/api/f/{token}")
    assert r.status_code == 429
    clean(world, r, "too many tries")


def test_the_unbuilt_page_is_white_label_too(world, monkeypatch):
    monkeypatch.setattr(hosts, "_built_index", lambda: None)
    sub, token = start(world)
    r = Client().get(f"/forms/{world['form'].slug}/{token}")
    assert r.status_code == 503
    clean(world, r, "the page before a build")


@pytest.fixture
def domain(world, settings):
    settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, DOMAIN]
    settings.INTAKE_FORM_HOSTS = [DOMAIN]
    world["form"].domain = DOMAIN
    world["form"].save(update_fields=["domain"])
    hosts.forget()
    yield DOMAIN
    hosts.forget()


def test_on_its_own_domain_only_the_form_answers(world, built, domain):
    sub, token = start(world)
    assert links.url_for(sub) == f"https://{DOMAIN}/{token}"
    client = Client(HTTP_HOST=DOMAIN)
    for where, response in walk(world, client, token, "/"):
        clean(world, response, f"{DOMAIN} {where}")
    for path in ("/", "/dashboard", "/api/me", "/api/branding", "/admin/", "/static/brand/favicon.ico",
                 "/favicon.ico", "/sw.js", "/accounts/login/", "/sign/abc", "/healthz",
                 f"/forms/{world['form'].slug}/{token}", "/api/intake/companies"):
        r = client.get(path)
        assert r.status_code == 404, path
        clean(world, r, f"{DOMAIN}{path}")
        assert "Mountain Stays" in r.content.decode()
    shell = client.get(f"/{token}")
    assert shell.status_code == 200
    assert "default-src 'self'" in shell["Content-Security-Policy"]


def test_another_forms_token_does_not_open_on_this_domain(world, built, domain):
    from .factories import ClientCompanyFactory, IntakeFormFactory

    other_form = IntakeFormFactory(tenant=world["practice"],
                                   company=ClientCompanyFactory(tenant=world["practice"],
                                                                intake_forms_enabled=True))
    from apps.intake import services

    other = services.start(other_form, first_name="Sam")
    token = links.token_of(other)
    assert Client(HTTP_HOST=DOMAIN).get(f"/api/f/{token}").status_code == 404


def test_the_built_owner_bundle_names_nobody():
    root = Path(settings.BASE_DIR) / "frontend" / "dist" / "forms"
    if not root.is_dir():
        pytest.skip("The owner's bundle isn't built here; the source scan covers it.")
    words = ["execs now", "execsnow", "executives now", "noble rose", "getexecutivesnow"]
    for path in root.rglob("*"):
        if path.is_file() and path.suffix in (".html", ".js", ".css", ".svg", ".json"):
            text = path.read_text("utf-8", "replace").lower()
            for word in words:
                assert word not in text, f"{path.name}: {word!r}"
