"""Tax numbers on the intake form (owner, 2026-11-24): the owner's EIN, or
their Social Security number or ITIN, for the rental permit, or a call instead.
Encrypted, the last four everywhere, the full number only for someone ticked
"See full tax numbers" after a one-time code to their own email, for 60
seconds; never while acting; each viewing recorded and the editors told; a
real send needs a tick and removes it, a test send removes nothing, 30 days
unsent removes it; and it is never anywhere else."""

from __future__ import annotations

import json
import logging
from datetime import timedelta

import pytest
from django.core import mail as django_mail
from django.test import Client
from django.utils import timezone

from apps.crm.models import OutboxMessage
from apps.intake import services, taxnumbers, vault
from apps.intake.models import (
    SendRun, Submission, SubmissionEvent, SubmissionSecret, TaxCode, TaxNumberAccess,
)
from apps.notify.models import Notice
from apps.tenancy.context import tenant_context
from apps.tenancy.models import AuditEvent

from . import registry_config  # noqa: F401
from .test_intake_flow import as_, fake, owner_fills, ready, review, send, start, world  # noqa
from .test_intake_plan import answers as full_answers

pytestmark = pytest.mark.django_db

SSN = "123-45-6789"
DIGITS = "123456789"


def put(o, token, value, kind="tax_id", slot=""):
    return o.post(f"/api/f/{token}/secret", json.dumps({"kind": kind, "slot": slot,
                                                         "value": value}),
                  content_type="application/json")


def choose(o, token, kind, **more):
    r = o.patch(f"/api/f/{token}/answers", json.dumps({"section": "tax",
                                                       "value": {"kind": kind, **more}}),
                content_type="application/json")
    assert r.status_code == 200, r.content


def tick(world, who="manager", by="fcc"):
    c = as_(world[by])
    page = c.get(f"/api/agreements/companies/{world['company'].pk}/access").json()
    rows = [{**r, "tax_numbers": r["user_id"] == str(world[who].user_id) or
             r.get("tax_numbers", False)} for r in page["rows"]]
    r = c.put(f"/api/agreements/companies/{world['company'].pk}/access",
              json.dumps({"rows": rows}), content_type="application/json")
    assert r.status_code == 200, r.content
    return r.json()


def with_ssn(world):
    """An intake whose owner chose Social Security and entered one, submitted."""
    sub, token = start(world)
    a = full_answers()
    a["tax"] = {"kind": "ssn"}
    o = owner_fills(token, a)          # the helper enters the SSN the choice calls for
    assert o.post(f"/api/f/{token}/submit").json() == {"state": "submitted"}
    return sub, token, o


# ------------------------------------------------------------ B1: the choice and the format

def test_the_owner_chooses_and_the_format_is_checked(world):
    sub, token = start(world)
    o = Client()
    choose(o, token, "ssn")
    for bad, says in (("000-12-3456", "can be issued"), ("666-12-3456", "can be issued"),
                      ("123-00-4567", "can be issued"), ("123-45-0000", "can be issued"),
                      ("12-3456789", "looks like a business tax ID"),
                      ("1234", "9 digits")):
        r = put(o, token, bad)
        assert r.status_code == 400 and says in r.json()["detail"], bad
    assert put(o, token, "912 70 1234").json()["secrets"]["tax_id"] == {"last4": "1234"}  # ITIN
    assert vault.value(sub, "tax_id") == "912-70-1234"
    assert put(o, token, DIGITS).status_code == 200
    assert vault.value(sub, "tax_id") == SSN
    # Changing the choice removes the number entered for the other one.
    choose(o, token, "tax_id")
    assert vault.value(sub, "tax_id") is None
    r = put(o, token, SSN)
    assert r.status_code == 400 and "looks like a Social Security number" in r.json()["detail"]
    for bad in ("00-1234567", "000000000", "12-345678"):
        assert put(o, token, bad).status_code == 400, bad
    assert put(o, token, "123456789").status_code == 200
    assert vault.value(sub, "tax_id") == "12-3456789"
    # By phone: nothing is entered on the form.
    choose(o, token, "phone")
    assert vault.value(sub, "tax_id") is None
    r = put(o, token, "12-3456789")
    assert r.status_code == 400 and "Choose which number" in r.json()["detail"]


def test_the_number_is_required_unless_the_owner_asks_for_a_call(world):
    sub, token = start(world)
    a = full_answers()
    a["tax"] = {"kind": "ssn"}
    o = Client()
    for section, value in a.items():
        o.patch(f"/api/f/{token}/answers", json.dumps({"section": section, "value": value}),
                content_type="application/json")
    r = o.post(f"/api/f/{token}/submit")
    assert r.status_code == 400 and "your tax number" in r.json()["detail"]
    choose(o, token, "")
    r = o.post(f"/api/f/{token}/submit")
    assert r.status_code == 400 and "which number goes on your rental permit" in \
        r.json()["detail"]
    choose(o, token, "phone")
    assert o.post(f"/api/f/{token}/submit").json() == {"state": "submitted"}


def test_the_form_says_why_and_how_in_the_approved_words(world, settings):
    sub, token = start(world)
    form = Client().get(f"/api/f/{token}").json()["form"]
    assert [o["label"] for o in form["options"]["tax_kind"]] == [
        "My business tax ID (EIN)", "My Social Security number or ITIN",
        "I'd rather give it by phone"]
    assert form["tax_wording"] == {
        "why": "Mountain Stays needs this number once, to file your property's rental permit. "
               "It's also kept on your owner account with us, for your year-end tax forms.",
        # Owner, after the demo walk (2026-11-24), word for word; the third
        # sentence as he changed it that night.
        "how": "Your number is encrypted the moment you save it. Only the few people who file "
               "your rental permit can view it, and each viewing is recorded. Once it's saved "
               "to your owner account, our team sees only the last four digits. Entering it "
               "here means no one has to take it down by phone or on paper."}
    # The backups' days are no longer shown to owners, and the setting is gone.
    assert not hasattr(settings, "INTAKE_TAX_BACKUP_DAYS")
    assert "backup" not in json.dumps(form["tax_wording"]).lower()


def test_nothing_still_promises_the_social_security_number_isnt_asked(world):
    from apps.intake import defaults, links

    for text in (defaults.MESSAGE_INVITE["body"], defaults.MESSAGE_REMINDER["body"],
                 json.dumps(defaults.CHECKLIST)):
        assert "Social Security" not in text
    # A form that kept the old default words gets the new ones.
    old = defaults.OLD_DEFAULTS["message_invite"]
    world["form"].settings = {**world["form"].settings, "message_invite": old}
    world["form"].save()
    sub, _ = start(world)
    message = links.message(sub, reminder=False, user=world["fcc"].user,
                            membership=world["fcc"])
    assert "Social Security" not in message["body"]


# ------------------------------------------------------------ B2: the last four, everywhere

def test_everyone_sees_the_last_four_only(world):
    sub, token, o = with_ssn(world)
    row = SubmissionSecret.all_objects.get(submission=sub, kind="tax_id")
    assert DIGITS not in bytes(row.ciphertext).decode("latin-1") and row.last4 == "6789"
    for by in ("ff", "fcc", "manager"):
        p = as_(world[by]).get(f"/api/intake/submissions/{sub.pk}").json()
        assert p["secrets"]["tax_id"] == {"last4": "6789"}
        assert SSN not in json.dumps(p) and DIGITS not in json.dumps(p)
    # The old Reveal no longer shows a tax number, to anyone.
    r = as_(world["ff"]).post(f"/api/intake/submissions/{sub.pk}/reveal", {"name": "tax_id"},
                              content_type="application/json")
    assert r.status_code == 403 and "one-time code" in r.json()["detail"]


# ------------------------------------------------------------ B3: the tick

def test_the_tick_is_given_only_by_the_people_who_change_ticks(world):
    page = as_(world["fcc"]).get(f"/api/agreements/companies/{world['company'].pk}/access")
    data = page.json()
    assert data["columns"]["tax_numbers"] is True
    assert all(r["tax_numbers"] is False for r in data["rows"])        # nobody to start
    out = tick(world, "manager", by="fcc")
    assert {r["user_id"]: r["tax_numbers"] for r in out["rows"]}[str(world["manager"].user_id)]
    assert TaxNumberAccess.all_objects.filter(user=world["manager"].user).exists()
    # The practice owner ticks like anyone, themselves included.
    tick(world, "ff", by="ff")
    assert TaxNumberAccess.all_objects.filter(user=world["ff"].user).exists()
    # Someone who may not change ticks can't reach the screen.
    r = as_(world["manager"]).put(f"/api/agreements/companies/{world['company'].pk}/access",
                                  json.dumps({"rows": []}), content_type="application/json")
    assert r.status_code == 404
    audit = AuditEvent.all_objects.filter(verb="agreements.access_changed").last()
    assert any("tax_numbers" in json.dumps(c) for c in audit.payload["changed"])


# ------------------------------------------------------------ B4: seeing it in full

def test_seeing_the_full_number_takes_a_code_and_is_recorded(world, monkeypatch, settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    django_mail.outbox = []
    sub, token, o = with_ssn(world)
    monkeypatch.setattr(taxnumbers.pysecrets, "randbelow", lambda n: 482913)
    c = as_(world["manager"])
    # Not ticked: refused.
    r = c.post(f"/api/intake/submissions/{sub.pk}/tax-code")
    assert r.status_code == 403
    tick(world, "manager")
    r = c.post(f"/api/intake/submissions/{sub.pk}/tax-code")
    assert r.status_code == 200 and r.json()["sent_to"] == world["manager"].user.email
    stored = OutboxMessage.all_objects.get(producer="tax_number_code")
    assert stored.to_address == world["manager"].user.email
    assert "482913" not in stored.body_text + stored.body_html
    assert SSN not in stored.body_text + stored.body_html + stored.subject
    assert TaxCode.all_objects.get(submission=sub).code_hash != "482913"
    r = c.post(f"/api/intake/submissions/{sub.pk}/tax-show", {"code": "111111"},
               content_type="application/json")
    assert r.status_code == 400 and "4 tries left" in r.json()["detail"]
    r = c.post(f"/api/intake/submissions/{sub.pk}/tax-show", {"code": "482913"},
               content_type="application/json")
    assert r.status_code == 200 and r.json() == {"value": SSN, "seconds": 60}
    assert r["Cache-Control"] == "no-store"
    r = c.post(f"/api/intake/submissions/{sub.pk}/tax-show", {"code": "482913"},
               content_type="application/json")
    assert r.status_code == 409                                       # once only
    shown = SubmissionEvent.all_objects.get(submission=sub, kind="tax_shown")
    assert shown.actor_id == world["manager"].user_id and DIGITS not in shown.detail
    audit = AuditEvent.all_objects.get(verb="intake.tax_number_shown")
    assert audit.payload["intake"] == sub.number and SSN not in json.dumps(audit.payload)
    told = set(Notice.all_objects.filter(source_type__startswith="intake_tax_shown")
               .values_list("recipient_id", flat=True))
    assert told == {world["ff"].user_id, world["fcc"].user_id}       # who may change ticks
    history = as_(world["fcc"]).get(f"/api/intake/submissions/{sub.pk}").json()["events"]
    assert any("saw the full tax number" in e["detail"] for e in history)


def test_a_code_expires_tries_run_out_and_codes_are_limited(world, monkeypatch):
    sub, token, o = with_ssn(world)
    tick(world, "manager")
    c = as_(world["manager"])
    monkeypatch.setattr(taxnumbers.pysecrets, "randbelow", lambda n: 1)
    c.post(f"/api/intake/submissions/{sub.pk}/tax-code")
    TaxCode.all_objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    r = c.post(f"/api/intake/submissions/{sub.pk}/tax-show", {"code": "000001"},
               content_type="application/json")
    assert r.status_code == 409 and "expired" in r.json()["detail"]
    c.post(f"/api/intake/submissions/{sub.pk}/tax-code")
    for _ in range(5):
        c.post(f"/api/intake/submissions/{sub.pk}/tax-show", {"code": "999999"},
               content_type="application/json")
    r = c.post(f"/api/intake/submissions/{sub.pk}/tax-show", {"code": "000001"},
               content_type="application/json")
    assert r.status_code == 429
    for _ in range(3):
        c.post(f"/api/intake/submissions/{sub.pk}/tax-code")
    r = c.post(f"/api/intake/submissions/{sub.pk}/tax-code")
    assert r.status_code == 429


def test_never_while_acting_as_someone(world):
    sub, token, o = with_ssn(world)
    tick(world, "manager")
    tick(world, "ff", by="ff")
    c = as_(world["ff"])
    r = c.post("/api/act-as/", {"membership": str(world["manager"].pk)},
               content_type="application/json")
    assert r.status_code in (200, 201), r.content
    r = c.post(f"/api/intake/submissions/{sub.pk}/tax-code")
    assert r.status_code == 403 and "acting as" in r.json()["detail"]
    r = c.post(f"/api/intake/submissions/{sub.pk}/tax-show", {"code": "000000"},
               content_type="application/json")
    assert r.status_code == 403 and "acting as" in r.json()["detail"]
    assert not TaxCode.all_objects.exists()


# ------------------------------------------------------------ B6: kept as short as possible

def test_a_real_send_needs_the_tick_and_removes_it_a_test_send_removes_nothing(world, fake):
    world["_fake"] = fake
    sub, token, o = with_ssn(world)
    upload_ready = review(world, sub, node_id=24, shares={"1": 40})
    # Test mode: every check, nothing removed, no tick needed.
    form = world["form"]
    form.settings = {**form.settings, "test_mode": True}
    form.save()
    r = upload_ready.post(f"/api/intake/submissions/{sub.pk}/send")
    assert r.status_code == 202, r.content
    assert vault.value(sub, "tax_id") == SSN
    form.settings = {**form.settings, "test_mode": False}
    form.save()
    p = as_(world["fcc"]).get(f"/api/intake/submissions/{sub.pk}").json()
    assert p["tax"]["ack_needed"] is True
    r = upload_ready.post(f"/api/intake/submissions/{sub.pk}/send")
    assert r.status_code == 400 and "I have what I need from the full tax number" in \
        r.json()["detail"]
    run = send(world, sub)                                   # the helper ticks it
    assert run.state == "succeeded", run.error
    owner = next(x["body"] for x in fake.calls
                 if x["method"] == "POST" and x["path"] == "/pms/owners")
    owner = json.loads(owner) if isinstance(owner, (str, bytes)) else owner
    assert owner["taxId"] == SSN
    assert vault.value(sub, "tax_id") is None
    assert not SubmissionSecret.all_objects.filter(submission=sub, kind="tax_id").exists()


def test_an_existing_owner_gets_no_number_and_the_plan_says_so(world, fake):
    """Owner, 2026-11-24, later: an existing Track owner is never changed, so
    the number isn't sent, and the Send plan says what staff must do."""
    world["_fake"] = fake
    sub, token, o = with_ssn(world)
    c = review(world, sub, node_id=24, shares={"1": 40}, owner_mode="existing",
               existing_owner_id=900)
    p = c.get(f"/api/intake/submissions/{sub.pk}").json()
    said = [line for line in p["plan"]["summary"] if "tax number" in line]
    assert said == ["The owner's tax number is not sent to Track: this is an existing owner, "
                    "and nothing about them changes. Before sending, check that the owner in "
                    "Track already has a tax ID, or add it in Track by hand. The number is "
                    "removed from ENHQ after this send."]
    assert p["tax"]["ack_needed"] is True and p["may_send"] is True
    run = send(world, sub)
    assert run.state == "succeeded", run.error
    assert not any(SSN in json.dumps(w, default=str) or DIGITS in json.dumps(w, default=str)
                   for w in fake.writes())
    assert "taxId" not in fake.owners[900] and fake.owners[900]["taxIdMasked"] is None
    assert vault.value(sub, "tax_id") is None
    # A new owner's plan says nothing of the kind.
    sub2, t2, o2 = with_ssn(world)
    p2 = review(world, sub2, node_id=24, shares={"1": 40}).get(
        f"/api/intake/submissions/{sub2.pk}").json()
    assert not any("existing owner" in line and "tax" in line for line in p2["plan"]["summary"])


def test_unsent_it_goes_30_days_after_submitting_and_the_intake_says_so(world):
    sub, token, o = with_ssn(world)
    old = timezone.now() - timedelta(days=31)
    Submission.all_objects.filter(pk=sub.pk).update(submitted_at=old)
    SubmissionSecret.all_objects.filter(submission=sub).update(updated_at=old)
    keep, t2 = start(world, email="kept@samplehomes.net")
    o2 = Client()
    choose(o2, t2, "tax_id")
    put(o2, t2, "12-3456789")                                # entered today, never submitted
    assert taxnumbers.purge(world["practice"].pk) == 1
    assert vault.value(sub, "tax_id") is None and vault.value(keep, "tax_id") is not None
    p = as_(world["fcc"]).get(f"/api/intake/submissions/{sub.pk}").json()
    assert p["tax"]["removed"].startswith("Removed the tax number: 30 days after the owner "
                                          "submitted")
    assert vault.value(sub, "wifi_password") is not None     # only the tax number goes
    SubmissionSecret.all_objects.filter(submission=keep, kind="tax_id").update(updated_at=old)
    assert taxnumbers.purge(world["practice"].pk) == 1        # never submitted, 30 days on


def test_by_phone_staff_type_it_in_and_the_checklist_has_the_call(world, fake):
    world["_fake"] = fake
    sub, token = start(world)
    a = full_answers()
    a["tax"] = {"kind": "phone"}
    o = owner_fills(token, a)
    o.post(f"/api/f/{token}/submit")
    c = review(world, sub, node_id=24, shares={"1": 40})
    p = c.get(f"/api/intake/submissions/{sub.pk}").json()
    assert p["tax"]["by_phone"] is True
    assert any("tax number" in x for x in p["plan"]["problems"])
    # The reviewer says which number the owner gave, and types it straight in.
    r = c.patch(f"/api/intake/submissions/{sub.pk}/answers",
                json.dumps({"section": "tax", "value": {"kind": "phone", "phone_kind": "ssn"}}),
                content_type="application/json")
    assert r.status_code == 200, r.content
    r = c.post(f"/api/intake/submissions/{sub.pk}/secret",
               json.dumps({"kind": "tax_id", "slot": "", "value": SSN}),
               content_type="application/json")
    assert r.status_code == 200, r.content
    run = send(world, sub)
    assert run.state == "succeeded", run.error
    with tenant_context(world["practice"].pk):
        from apps.work.models import Task

        titles = list(Task.objects.filter(project_id=sub.project_id).values_list("title",
                                                                                   flat=True))
    assert not any("by phone" in t for t in titles)          # it went to Track: no call left
    # Marked as having none instead: the call is a task.
    sub2, t2 = start(world, email="second@samplehomes.net")
    o2 = owner_fills(t2, a)
    o2.post(f"/api/f/{t2}/submit")
    c2 = review(world, sub2, node_id=24, shares={"1": 40},
                no_value=["tax_id"])
    run = send(world, sub2)
    assert run.state == "succeeded", run.error
    with tenant_context(world["practice"].pk):
        titles = list(Task.objects.filter(project_id=Submission.all_objects.get(pk=sub2.pk)
                                          .project_id).values_list("title", flat=True))
    assert any("they asked to give it by phone" in t for t in titles)


def test_another_property_carries_the_choice_not_the_number(world):
    sub, token, o = with_ssn(world)
    r = o.post(f"/api/f/{token}/another")
    assert r.status_code in (200, 201), r.content
    new = Submission.all_objects.exclude(pk=sub.pk).get(carried_from=sub)
    assert (new.answers.get("tax") or {}).get("kind") == "ssn"
    assert not SubmissionSecret.all_objects.filter(submission=new).exists()


# ------------------------------------------------------------ B5: nowhere else

def test_the_full_number_is_never_anywhere_else(world, fake, caplog, monkeypatch, settings):
    """Email (stored and delivered), notices, history, audit, a Track refusal
    that repeats it, the send's steps and error, logs, search, the intake's
    stored JSON."""
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    django_mail.outbox = []
    caplog.set_level(logging.DEBUG)
    world["_fake"] = fake
    sub, token, o = with_ssn(world)
    tick(world, "manager")
    c = as_(world["manager"])
    monkeypatch.setattr(taxnumbers.pysecrets, "randbelow", lambda n: 314159)
    c.post(f"/api/intake/submissions/{sub.pk}/tax-code")
    assert c.post(f"/api/intake/submissions/{sub.pk}/tax-show", {"code": "314159"},
                  content_type="application/json").status_code == 200
    review(world, sub, node_id=24, shares={"1": 40})
    # Track refuses the owner once, repeating the number back.
    real = fake.send

    def repeat(method, url, headers, body):
        data = json.loads(body) if isinstance(body, (str, bytes)) and body else (body or {})
        if method == "POST" and url.endswith("/pms/owners") and not getattr(repeat, "done", 0):
            repeat.done = 1
            return 422, {"Content-Type": "application/problem+json"}, json.dumps(
                {"validation_messages": [f"taxId {data.get('taxId')} ({DIGITS}) is not valid"],
                 "status": 422})
        return real(method, url, headers, body)

    monkeypatch.setattr(fake, "send", repeat)
    run = send(world, sub)
    assert run.state == "failed"
    assert taxnumbers.MASK in run.error and SSN not in run.error and DIGITS not in run.error
    run = send(world, sub)                                     # "Try the rest again"
    assert run.state == "succeeded", run.error
    sub.refresh_from_db()

    def clean(text, where):
        for shape in (SSN, DIGITS, "123 45 6789"):
            assert shape not in text, f"the tax number reached {where}"

    for m in OutboxMessage.all_objects.all():
        clean(m.subject + m.body_text + m.body_html, f"the Outbox ({m.producer})")
    for m in django_mail.outbox:
        clean(m.subject + m.body + "".join(str(a[0]) for a in m.alternatives),
              "a delivered email")
    for n in Notice.all_objects.all():
        clean(n.title + n.text, "a notice")
    for e in SubmissionEvent.all_objects.all():
        clean(e.detail, "the intake's history")
    for e in AuditEvent.all_objects.all():
        clean(json.dumps(e.payload, default=str), "the audit log")
    for r in SendRun.all_objects.all():
        clean(json.dumps(r.steps) + r.error, "a send's steps")
    clean(json.dumps([sub.answers, sub.staff, sub.track, sub.track_check], default=str),
          "the intake's stored answers")
    for record in caplog.records:
        clean(record.getMessage(), "the log")
    r = as_(world["ff"]).get("/api/contacts/search/", {"q": SSN})
    clean(r.content.decode(), "search")


def test_the_laptop_refresh_scrub_removes_every_intake_secret(world):
    from apps.tenancy.management.commands import scrub_dev_data

    sub, token, o = with_ssn(world)
    assert SubmissionSecret.all_objects.exists()
    rows = scrub_dev_data.delete_intake_secrets()
    assert rows and not SubmissionSecret.all_objects.exists()
