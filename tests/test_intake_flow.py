"""Intake forms end to end, against the fake Track (tests/intake_fake_track.py):
the owner's link, the review, the send (new owner, existing owner, a failed
step resumed, an answer lost and found), owner dates, secrets, access.

Set INTAKE_FAKE_RUN_LOG to a path to write the runs' step-by-step record.
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone

from apps.crm.models import OutboxMessage, Task
from apps.crm.services import secrets as cipher
from apps.intake import links, ownerdates, services, tracklists, vault
from apps.intake.models import OwnerDate, SendRun, Submission, SubmissionEvent, SubmissionSecret
from apps.notify.models import Notice
from apps.scorecard import track
from apps.scorecard.models import TrackConnection
from apps.tenancy.context import tenant_context
from apps.work import teams

from . import registry_config  # noqa: F401
from .factories import ClientCompanyFactory, MembershipFactory, TenantFactory, UserFactory
from .intake_fake_track import FakeTrack
from .intake_fake_track import client as fake_client
from .test_intake_plan import answers as full_answers

pytestmark = pytest.mark.django_db
LOG = os.environ.get("INTAKE_FAKE_RUN_LOG")


def _log(title, run):
    if not LOG:
        return
    with open(LOG, "a") as fh:
        fh.write(f"\n=== {title}: {run.state}\n")
        for step in run.steps:
            fh.write(f"  {step['state']:8} {step['label']}"
                     + (f" ({step['detail']})" if step.get("detail") else "") + "\n")
        if run.error:
            fh.write(f"  error: {run.error}\n")


@pytest.fixture
def fake(monkeypatch):
    fake = FakeTrack()
    monkeypatch.setattr(track, "http_transport", fake.get)
    monkeypatch.setattr(track, "http_send", fake.send)
    monkeypatch.setattr("django_q.tasks.async_task", lambda *a, **k: None)
    return fake


@pytest.fixture
def world(fake, settings):
    settings.STORAGE_BACKEND = "local"
    practice = TenantFactory(name="Executives Now")
    owner_user = UserFactory(full_name="Pat Practiceowner", email="pat@practice-staff.test")
    ff = MembershipFactory(tenant=practice, role="FF", user=owner_user)
    company = ClientCompanyFactory(tenant=practice, name="Mountain Stays",
                                   intake_forms_enabled=True)
    TrackConnection.all_objects.create(
        tenant=practice, company=company, domain="https://skyrunparkcity.trackhs.com/api",
        key_ciphertext=cipher.encrypt("key"), secret_ciphertext=cipher.encrypt("secret"),
        key_last4="key")
    fcc = MembershipFactory(tenant=practice, role="FCC", client_company=company)
    manager = MembershipFactory(tenant=practice, role="ECC", client_company=company)
    member = MembershipFactory(tenant=practice, role="ECC", client_company=company)
    team = teams.default_team(practice.pk, company.pk)
    teams.place(team, member, "member")
    teams.place(team, manager, "manager")
    # Owner, 2026-11-23: intake is a tick on the permissions screen.
    from apps.agreements.models import StaffAccess

    for m in (fcc, manager):
        StaffAccess.all_objects.create(tenant=practice, company=company, user=m.user, intake=True)
    cf = MembershipFactory(tenant=practice, role="CF")
    va = MembershipFactory(tenant=practice, role="VA")
    with tenant_context(practice.pk):
        tracklists.lists_for(company, refresh=True)
        form = services.form_for(company)
    form.brand_name, form.contact_phone, form.contact_email = (
        "Mountain Stays", "435-555-0100", "hello@mountainstays.net")
    # These tests send for real (to the fake Track); test mode has its own.
    form.settings = {**form.settings, "test_mode": False}
    form.save()
    return {"practice": practice, "company": company, "ff": ff, "fcc": fcc,
            "manager": manager, "member": member, "cf": cf, "va": va, "form": form}


def as_(membership):
    client = Client()
    client.force_login(membership.user)
    return client


def start(world, by="fcc", email="alex@samplehomes.net"):
    c = as_(world[by])
    r = c.post(f"/api/intake/companies/{world['company'].pk}/submissions",
               {"first_name": "Alex", "last_name": "Sample", "email": email},
               content_type="application/json")
    assert r.status_code == 201, r.content
    sub = Submission.all_objects.get(pk=r.json()["id"])
    return sub, links.token_of(sub)


def owner_fills(token, a=None):
    """The owner fills in every section on the link, and the secrets."""
    o = Client()
    a = a or full_answers()
    for section, value in a.items():
        r = o.patch(f"/api/f/{token}/answers", json.dumps({"section": section, "value": value}),
                    content_type="application/json")
        assert r.status_code == 200, (section, r.content)
    # The tax number the owner's choice calls for (owner, 2026-11-24): none
    # when they would rather give it by phone.
    tax = {"tax_id": "12-3456789", "ssn": "123-45-6789"}.get((a.get("tax") or {}).get("kind"))
    for kind, slot, value in ((("tax_id", "", tax),) if tax else ()) + (
            ("wifi_password", "", "powder-day"),
            ("code", "door", "4821"), ("code", "owner_closet", "7730"),
            ("code", "alarm", "1199"), ("code", "extra-0", "5501")):
        r = o.post(f"/api/f/{token}/secret", json.dumps({"kind": kind, "slot": slot,
                                                         "value": value}),
                   content_type="application/json")
        assert r.status_code == 200, r.content
    return o


def review(world, sub, by="fcc", **changes):
    c = as_(world[by])
    if changes:
        r = c.patch(f"/api/intake/submissions/{sub.pk}/staff", json.dumps({"changes": changes}),
                    content_type="application/json")
        assert r.status_code == 200, r.content
    return c


def send(world, sub, by="fcc"):
    c = as_(world[by])
    # A real send while a tax number is held needs the tick (owner, 2026-11-24).
    r = c.post(f"/api/intake/submissions/{sub.pk}/send", {"tax_ack": True},
               content_type="application/json")
    assert r.status_code == 202, r.content
    run = SendRun.all_objects.get(pk=r.json()["run"]["id"])
    services.run_send(run, client=fake_client(world["_fake"]) if "_fake" in world else None,
                      today=date(2026, 11, 20))
    run.refresh_from_db()
    return run


# ------------------------------------------------------------ the owner's link

def test_owner_link_saves_as_it_goes_and_masks_secrets(world):
    sub, token = start(world)
    o = owner_fills(token)
    page = o.get(f"/api/f/{token}").json()
    assert page["state"] == "open" and page["answers"]["about"]["last_name"] == "Sample"
    assert page["secrets"]["tax_id"] == {"last4": "6789"}
    assert page["secrets"]["wifi_password"] is True and page["secrets"]["codes"]["door"] is True
    text = json.dumps(page)
    for secret in ("4821", "7730", "powder-day", "3456789"):
        assert secret not in text
    assert bytes(SubmissionSecret.all_objects.get(submission=sub, kind="tax_id").ciphertext) \
        and b"3456789" not in bytes(SubmissionSecret.all_objects.get(
            submission=sub, kind="tax_id").ciphertext)
    sub.refresh_from_db()
    assert sub.status == Submission.Status.IN_PROGRESS


def test_a_social_security_shaped_tax_id_is_refused(world):
    """Under the EIN choice (owner, 2026-11-24: the Social Security number or
    ITIN is its own choice now, tests/test_tax_numbers.py)."""
    sub, token = start(world)
    Client().patch(f"/api/f/{token}/answers", json.dumps({"section": "tax",
                                                          "value": {"kind": "tax_id"}}),
                   content_type="application/json")
    r = Client().post(f"/api/f/{token}/secret", json.dumps({"kind": "tax_id", "value":
                                                            "123-45-6789"}),
                      content_type="application/json")
    assert r.status_code == 400 and "looks like a Social Security number" in r.json()["detail"]


def test_submit_tells_managers_and_the_practice_owner_by_app_and_email(world):
    sub, token = start(world)
    o = owner_fills(token)
    assert o.post(f"/api/f/{token}/submit").json() == {"state": "submitted"}
    told = Notice.all_objects.filter(source_type="intake_submitted")
    assert {n.recipient_id for n in told} == {world["fcc"].user_id, world["manager"].user_id,
                                               world["ff"].user_id}
    mails = OutboxMessage.all_objects.filter(producer="intake_notice")
    assert {m.to_address for m in mails} == {world["fcc"].user.email,
                                             world["manager"].user.email,
                                             world["ff"].user.email}
    # Owner, 2026-11-23: the email and the notice name the owner and the
    # property's address, and nothing else from the answers.
    for mail in mails:
        assert mail.subject == f"New owner intake #{sub.number}: Sample Homes LLC, " \
            "400 Lift Road, Park City"
        assert "Sample Homes LLC finished the new owner and property form for 400 Lift Road, " \
            "Park City." in mail.body_text
        for private in ("samplehomes.net", "555", "4821", "powder-day", "12-3456789"):
            assert private not in mail.body_text and private not in mail.subject
    for notice in told:
        assert notice.title.startswith(f"New owner intake #{sub.number}: Sample Homes LLC")
    assert o.get(f"/api/f/{token}").json()["state"] == "submitted"
    r = o.patch(f"/api/f/{token}/answers", json.dumps({"section": "tax", "value": {}}),
                content_type="application/json")
    assert r.status_code == 409


def test_add_another_property_carries_the_owner_over(world):
    sub, token = start(world)
    o = owner_fills(token)
    o.post(f"/api/f/{token}/submit")
    r = o.post(f"/api/f/{token}/another")
    assert r.status_code == 201
    new_token = r.json()["link"].rsplit("/", 1)[1]
    new = links.resolve(new_token)
    assert new.carried_from_id == sub.pk and new.number == sub.number + 1
    assert new.answers["about"]["account_name"] == "Sample Homes LLC"
    assert new.answers["property"]["street"] == ""
    # Owner, 2026-11-24: the choice comes along, the number doesn't.
    assert new.answers["tax"]["kind"] == "tax_id" and vault.masked(new)["tax_id"] is None


def test_links_expire_after_30_days_and_a_manager_can_reopen(world):
    sub, token = start(world)
    Submission.all_objects.filter(pk=sub.pk).update(
        last_activity_at=timezone.now() - timedelta(days=31))
    r = Client().get(f"/api/f/{token}")
    assert r.status_code == 410 and "Mountain Stays" in r.json()["detail"]
    assert as_(world["manager"]).post(f"/api/intake/submissions/{sub.pk}/reopen").status_code \
        == 200
    assert Client().get(f"/api/f/{token}").status_code == 200
    assert Client().get("/api/f/not-a-real-token-at-all-0000000000").status_code == 404


def test_copy_link_message_and_mailto_are_logged_and_signed_by_the_company(world):
    sub, _ = start(world)
    c = as_(world["ff"])
    r = c.post(f"/api/intake/submissions/{sub.pk}/link",
               json.dumps({"action": "email", "reminder": False}),
               content_type="application/json").json()
    assert r["mailto"].startswith("mailto:alex%40samplehomes.net?subject=")
    assert "Pat" not in r["body"] and r["body"].rstrip().endswith("Mountain Stays")
    assert "never asks for your bank details" in r["body"]
    assert "Social Security" not in r["body"]                 # owner, 2026-11-24
    staff = as_(world["fcc"]).post(f"/api/intake/submissions/{sub.pk}/link",
                                   json.dumps({"action": "message", "reminder": True}),
                                   content_type="application/json").json()
    assert world["fcc"].user.full_name in staff["body"]
    kinds = list(SubmissionEvent.all_objects.filter(submission=sub).values_list("kind",
                                                                                flat=True))
    assert "email_opened" in kinds and "message_copied" in kinds
    assert not OutboxMessage.all_objects.filter(to_address="alex@samplehomes.net").exists()


# ------------------------------------------------------------ access

@pytest.mark.parametrize("who", ["member", "cf", "va"])
def test_only_managers_and_the_practice_owner_reach_intakes(world, who):
    sub, _ = start(world)
    c = as_(world[who])
    assert c.get(f"/api/intake/submissions/{sub.pk}").status_code == 404
    assert c.get(f"/api/intake/companies/{world['company'].pk}/submissions").status_code == 404
    assert c.get("/api/intake/companies").json()["companies"] == []


def test_another_companys_owner_cannot_reach_it(world):
    sub, _ = start(world)
    other = ClientCompanyFactory(tenant=world["practice"], intake_forms_enabled=True)
    stranger = MembershipFactory(tenant=world["practice"], role="FCC", client_company=other)
    assert as_(stranger).get(f"/api/intake/submissions/{sub.pk}").status_code == 404


def test_reveal_is_logged_and_discard_deletes_secrets(world):
    sub, token = start(world)
    owner_fills(token)
    c = as_(world["manager"])
    r = c.post(f"/api/intake/submissions/{sub.pk}/reveal", {"name": "code:door"},
               content_type="application/json")
    assert r.json() == {"value": "4821"}
    event = SubmissionEvent.all_objects.get(submission=sub, kind="revealed")
    assert event.actor_id == world["manager"].user_id and "4821" not in event.detail
    payload = c.get(f"/api/intake/submissions/{sub.pk}").json()
    assert "4821" not in json.dumps(payload) and payload["secrets"]["tax_id"]["last4"] == "6789"
    c.post(f"/api/intake/submissions/{sub.pk}/discard")
    assert not SubmissionSecret.all_objects.filter(submission=sub).exists()
    assert Client().get(f"/api/f/{token}").status_code == 404


# ------------------------------------------------------------ sending

def ready(world, mode_changes=None):
    sub, token = start(world)
    o = owner_fills(token)
    upload = SimpleUploadedFile("declarations.pdf", b"%PDF-1.4 declarations page",
                                content_type="application/pdf")
    assert o.post(f"/api/f/{token}/files", {"file": upload}).status_code == 201
    o.post(f"/api/f/{token}/submit")
    review(world, sub, node_id=24, shares={"1": 40}, **(mode_changes or {}))
    return sub


def test_new_owner_send_writes_everything_then_locks(world, fake):
    world["_fake"] = fake
    sub = ready(world)
    run = send(world, sub)
    _log("New owner", run)
    assert run.state == SendRun.State.SUCCEEDED, run.error
    sub.refresh_from_db()
    assert sub.status == Submission.Status.SENT and sub.locked
    [owner] = [o for o in fake.owners.values() if o["name"] == "Sample Homes LLC"]
    assert owner["isActive"] is True and owner["taxIdMasked"] == "**-***6789"
    [unit] = [u for u in fake.units.values() if u["name"] == "400 Lift Road"]
    assert unit["isActive"] is False and unit["isBookable"] is False
    out = fake._unit_out(unit["id"])
    assert (out["bedrooms"], out["fullBathrooms"], out["threeQuarterBathrooms"],
            out["halfBathrooms"]) == (2, 1, 1, 1)
    assert unit["maxOccupancy"] == 8
    assert unit["custom"]["pms_units_wifi_password"] == "powder-day"
    assert unit["custom"]["pms_units_coffee_maker_type"] == "keurig_coffee"
    assert len([c for c in fake.codes.values() if c["unitId"] == unit["id"]]) == 4
    links_ = fake.links[owner["companyId"]]
    assert links_[0]["isPrimaryContact"] is True and links_[1]["ownerSplit"] == 40.0
    [ownership] = fake.ownerships.values()
    assert (ownership["contractType"], ownership["taxMode"], ownership["contractId"]) == \
        ("standard", "pmc", 1)
    # Every call said Accept: application/json and named ENHQ.
    assert all(c["accept"] == "application/json" and "ExecsNowHQ" in c["agent"]
               for c in fake.calls)
    # Nothing of any secret is kept once Track has it.
    assert not SubmissionSecret.all_objects.filter(submission=sub).exists()
    assert "4821" not in json.dumps(run.steps) + json.dumps(sub.track)
    # The checklist: one project with the street, generic titles, due from the ready date.
    tasks = list(Task.all_objects.filter(project=sub.project))
    assert sub.project.title.endswith("400 Lift Road")
    assert {t.assignee_id for t in tasks} == {world["fcc"].user_id}
    for t in tasks:
        assert "Sample" not in t.title and "samplehomes" not in t.title
    portal = next(t for t in tasks if t.title.startswith("Invite everyone"))
    assert portal.due_date == date(2030, 1, 10)
    assert any(t.title.startswith("Upload the insurance") for t in tasks)
    assert any("Right after the listing is made bookable" in t.title for t in tasks)
    assert not any(t.title.startswith("Get or confirm the nightly") for t in tasks)
    [held] = OwnerDate.all_objects.filter(submission=sub)
    assert held.state == OwnerDate.State.HELD
    # A locked record: no more changes in ENHQ.
    r = as_(world["fcc"]).patch(f"/api/intake/submissions/{sub.pk}/answers",
                                json.dumps({"section": "tax", "value": {}}),
                                content_type="application/json")
    assert r.status_code == 409


def test_existing_owner_is_left_untouched(world, fake):
    world["_fake"] = fake
    sub = ready(world, {"owner_mode": "existing", "existing_owner_id": 900})
    run = send(world, sub)
    _log("Existing owner", run)
    assert run.state == SendRun.State.SUCCEEDED, run.error
    writes = fake.writes()
    assert not any(w["path"].startswith(("/crm/contacts", "/crm/companies")) for w in writes)
    assert not any(w["path"] == "/pms/owners" for w in writes)
    assert fake.owners[900]["notes"] == "" and fake.links[7900] == []
    [ownership] = fake.ownerships.values()
    assert ownership["ownerId"] == 900
    sub.refresh_from_db()
    titles = [t.title for t in Task.all_objects.filter(project=sub.project)]
    assert any(t.startswith("Add the new additional owners") for t in titles)


def test_a_failed_step_is_resumed_without_duplicates(world, fake):
    world["_fake"] = fake
    sub = ready(world)
    fake.fail_once[("POST", "/pms/units/{n}/security-codes")] = "refuse"
    first = send(world, sub)
    _log("Failed at a code", first)
    assert first.state == SendRun.State.FAILED and "Simulated refusal" in first.error
    sub.refresh_from_db()
    assert sub.status == Submission.Status.FAILED and not sub.locked
    rooms_before = len(fake.rooms)
    second = send(world, sub)
    _log("Try the rest again", second)
    assert second.state == SendRun.State.SUCCEEDED, second.error
    assert len(fake.units) == 1 and len(fake.rooms) == rooms_before
    assert len([o for o in fake.owners.values() if o["name"] == "Sample Homes LLC"]) == 1
    assert sum(1 for s in second.steps if s["state"] == "skipped") >= 6


def test_an_answer_lost_after_track_created_the_unit_is_found_again(world, fake):
    world["_fake"] = fake
    sub = ready(world)
    fake.fail_once[("POST", "/pms/units")] = "lose"
    first = send(world, sub)
    assert first.state == SendRun.State.FAILED
    assert len(fake.units) == 1                      # Track made it; ENHQ never heard
    second = send(world, sub)
    _log("Lost answer, found again", second)
    assert second.state == SendRun.State.SUCCEEDED, second.error
    assert len(fake.units) == 1
    assert next(s for s in second.steps if s["key"] == "unit")["detail"] == \
        "Found in Track from the last try"


def test_an_example_com_email_never_reaches_track(world, fake):
    world["_fake"] = fake
    sub, token = start(world, email="alex@example.com")
    a = full_answers()
    a["about"]["email"] = "alex@example.com"
    owner_fills(token, a)
    review(world, sub, node_id=24)
    r = as_(world["fcc"]).post(f"/api/intake/submissions/{sub.pk}/send")
    assert r.status_code == 400 and "firewall" in r.json()["detail"]
    assert fake.writes() == []


def test_owner_dates_held_then_placed_once_bookable(world, fake):
    world["_fake"] = fake
    sub = ready(world)
    assert send(world, sub).state == SendRun.State.SUCCEEDED
    sub.refresh_from_db()
    lists, _ = tracklists.stored(sub.company)
    with tenant_context(sub.tenant_id):
        held = ownerdates.place(sub, fake_client(fake), lists, today=date(2026, 12, 1))
    assert held["held"] == 1 and "isn't bookable" in held["text"]
    unit_id = sub.track["ids"]["unit"]
    fake.units[unit_id]["isBookable"] = True
    c = as_(world["manager"])
    r = c.post(f"/api/intake/submissions/{sub.pk}/dates/place").json()
    assert r["result"]["placed"] == 1
    [block] = fake.blocks.values()
    assert block["reasonId"] == 17 and block["startDate"] == "2030-02-01"
    assert OwnerDate.all_objects.get(submission=sub).state == OwnerDate.State.PLACED
    assert Notice.all_objects.filter(source_type="intake_dates_placed").exists()
    if LOG:
        with open(LOG, "a") as fh:
            fh.write(f"\n=== Owner dates: held while not bookable ({held['text']}), then "
                     f"placed: {r['result']['text']} Block reason id {block['reasonId']}, "
                     f"{block['startDate']} to {block['endDate']}.\n")


def test_owner_dates_that_pass_while_held_expire_and_managers_are_told(world, fake):
    world["_fake"] = fake
    sub = ready(world)
    send(world, sub)
    lists, _ = tracklists.stored(sub.company)
    with tenant_context(sub.tenant_id):
        result = ownerdates.place(sub, fake_client(fake), lists, today=date(2031, 1, 1))
    assert result["expired"] == 1
    assert Notice.all_objects.filter(source_type="intake_dates_expired").count() == 3


def test_held_dates_get_a_weekly_reminder_after_30_days_and_can_be_cancelled(world, fake):
    world["_fake"] = fake
    sub = ready(world)
    send(world, sub)
    row = OwnerDate.all_objects.get(submission=sub)
    OwnerDate.all_objects.filter(pk=row.pk).update(created_at=timezone.now() - timedelta(days=31))
    with tenant_context(sub.tenant_id):
        assert ownerdates.remind(sub) == 1
        assert ownerdates.remind(sub) == 0           # not again within the week
    c = as_(world["fcc"])
    r = c.post(f"/api/intake/submissions/{sub.pk}/dates/{row.pk}/cancel").json()
    assert r["owner_dates"][0]["state"] == "cancelled"


def test_secrets_of_an_unsent_intake_go_after_90_days(world):
    sub, token = start(world)
    owner_fills(token)
    Submission.all_objects.filter(pk=sub.pk).update(
        last_changed_at=timezone.now() - timedelta(days=91))
    assert vault.purge_stale(sub.tenant_id) == 6
    assert not SubmissionSecret.all_objects.filter(submission=sub).exists()
