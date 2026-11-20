"""Intake forms are SkyRun Park City's alone (owner, 2026-11-20): not a feature
offered to other clients or practices.

- **No switch in the app**, for any practice owner: `manage.py intake_forms
  <company-id> on|off`, run by the owner, is the only way on or off.
- **Nothing shows unless it is on for that company**: the notification
  choice is offered only to someone who runs a company with it on (the
  company card and the menu are the frontend's, tested there).
- **Off means gone**: the owner's links, form pages, logo and the form's own
  domain answer as if they never existed, white label still.
"""

from __future__ import annotations

import json
import uuid
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.test import Client

from apps.crm.services import secrets as cipher
from apps.intake.models import IntakeForm
from apps.notify import service as notify
from apps.scorecard.models import TrackConnection
from apps.tenancy.models import AuditEvent

from . import registry_config  # noqa: F401
from .factories import ClientCompanyFactory, CompanyFactory
from .test_intake_flow import as_, fake, start, world  # noqa: F401
from .test_intake_white_label import built, clean, domain  # noqa: F401

pytestmark = pytest.mark.django_db


def switch(company, *state) -> str:
    out = StringIO()
    call_command("intake_forms", str(company.pk), *state, stdout=out)
    return out.getvalue()


def connect_track(company):
    TrackConnection.all_objects.create(
        tenant_id=company.tenant_id, company=company,
        domain="https://skyrunparkcity.trackhs.com/api", key_ciphertext=cipher.encrypt("key"),
        secret_ciphertext=cipher.encrypt("secret"), key_last4="key")


# ---------------------------------------------------------------- the switch

def test_there_is_no_switch_in_the_app(world):
    other = ClientCompanyFactory(tenant=world["practice"])
    connect_track(other)
    for company in (world["company"], other):
        url = f"/api/intake/companies/{company.pk}/switch"
        for who in ("ff", "fcc"):
            c = as_(world[who])
            assert c.get(url).status_code == 404
            for enabled in (True, False):
                r = c.put(url, json.dumps({"enabled": enabled}), content_type="application/json")
                assert r.status_code == 404, (who, enabled)
    other.refresh_from_db()
    world["company"].refresh_from_db()
    assert not other.intake_forms_enabled and world["company"].intake_forms_enabled


def test_the_command_switches_one_company_on_and_off(world):
    other = ClientCompanyFactory(tenant=world["practice"], name="Other Stays")
    with pytest.raises(CommandError, match="no Track connection"):
        switch(other, "on")
    other.refresh_from_db()
    assert not other.intake_forms_enabled
    assert not IntakeForm.all_objects.filter(company=other).exists()

    connect_track(other)
    assert "now on for Other Stays (practice: Executives Now)" in switch(other, "on")
    other.refresh_from_db()
    assert other.intake_forms_enabled
    assert IntakeForm.all_objects.filter(company=other).exists()
    assert "are on for Other Stays" in switch(other)
    assert "already on" in switch(other, "on")

    assert "now off for Other Stays" in switch(other, "off")
    other.refresh_from_db()
    assert not other.intake_forms_enabled
    events = AuditEvent.all_objects.filter(target_id=other.pk, verb="intake.switched")
    assert sorted(e.payload["enabled"] for e in events) == [False, True]
    assert all(e.actor_id is None and e.payload["by"] == "manage.py intake_forms"
               for e in events)


def test_the_command_refuses_what_it_cannot_switch(world):
    prospect = CompanyFactory(tenant=world["practice"], name="Just A Lead")
    with pytest.raises(CommandError, match="isn't a client company"):
        switch(prospect, "on")
    with pytest.raises(CommandError, match="No company has that id"):
        call_command("intake_forms", str(uuid.uuid4()), "on", stdout=StringIO())
    with pytest.raises(CommandError, match="isn't a company id"):
        call_command("intake_forms", "skyrun", "on", stdout=StringIO())


# ---------------------------------------------------------------- notifications

def test_the_notification_choice_is_only_for_people_who_run_intakes(world):
    def offered(who):
        return "intake" in notify.kinds_for(world[who])

    assert offered("ff") and offered("fcc") and offered("manager")
    # A team member, an associate and an assistant never are told, so never asked.
    assert not offered("member") and not offered("cf") and not offered("va")
    # Another company of the same practice, without intake forms.
    from .factories import MembershipFactory

    elsewhere = MembershipFactory(tenant=world["practice"], role="FCC",
                                  client_company=ClientCompanyFactory(tenant=world["practice"]))
    assert "intake" not in notify.kinds_for(elsewhere)
    # Switched off, nobody is offered it, the practice owner included.
    switch(world["company"], "off")
    assert not any(offered(who) for who in ("ff", "fcc", "manager"))


def test_the_profile_lists_the_choice_only_while_it_is_on(world, settings):
    settings.VAPID_PUBLIC_KEY, settings.VAPID_PRIVATE_KEY = "BPub" + "k" * 80, "priv" + "k" * 39
    c = as_(world["ff"])
    labels = [k["label"] for k in c.get("/api/notify/push/").json()["kinds"]]
    assert "Owner intake forms" in labels
    switch(world["company"], "off")
    labels = [k["label"] for k in c.get("/api/notify/push/").json()["kinds"]]
    assert "Owner intake forms" not in labels


# ---------------------------------------------------------------- switched off

def test_switched_off_its_links_and_pages_are_gone(world, built):
    sub, token = start(world)
    slug = world["form"].slug
    client = Client()
    assert client.get(f"/api/f/{token}").status_code == 200
    switch(world["company"], "off")
    for method, path in (("get", f"/api/f/{token}"), ("post", f"/api/f/{token}/submit"),
                         ("post", f"/api/f/{token}/another"), ("get", f"/forms/{slug}/{token}"),
                         ("get", f"/forms/{slug}"), ("get", f"/api/forms/{slug}/logo")):
        r = getattr(client, method)(path)
        assert r.status_code == 404, path
        clean(world, r, path)
    r = client.patch(f"/api/f/{token}/answers",
                     json.dumps({"section": "about", "value": {"first_name": "Alex"}}),
                     content_type="application/json")
    assert r.status_code == 404
    # Back on, the same link opens again.
    switch(world["company"], "on")
    assert client.get(f"/api/f/{token}").status_code == 200


def test_switched_off_its_own_domain_answers_nothing(world, built, domain):
    sub, token = start(world)
    client = Client(HTTP_HOST=domain)
    assert client.get(f"/{token}").status_code == 200
    switch(world["company"], "off")
    for path in (f"/{token}", f"/api/f/{token}", f"/api/forms/{world['form'].slug}/icon",
                 "/static/forms/assets/forms-abc.js", "/"):
        r = client.get(path)
        assert r.status_code == 404, path
        clean(world, r, f"{domain}{path}")
