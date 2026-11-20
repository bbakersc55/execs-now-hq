"""Sensitive values and the send (owner, 2026-11-20, after intake #1 stopped at
"Add the door code": the code was never saved, because the form wanted its
own Save, and the plan made the step anyway).

- Never start a send that can't finish: every value the plan needs is held,
  already in Track, or marked by the reviewer as having none; otherwise Send
  is refused before any write, and the worker checks again.
- The owner can still submit without a code.
- Once Track has a value and ENHQ deleted it, the review screen and "Try the
  rest again" treat it as done: no warning, no problem.
"""

from __future__ import annotations

import json

import pytest
from django.test import Client

from apps.intake import services, vault
from apps.intake.models import SendRun, Submission, SubmissionSecret

from . import registry_config  # noqa: F401
from .test_intake_flow import as_, fake, review, send, start, world  # noqa: F401
from .test_intake_plan import answers as full_answers

pytestmark = pytest.mark.django_db


def owner_answers(token, a=None):
    o = Client()
    for section, value in (a or full_answers()).items():
        r = o.patch(f"/api/f/{token}/answers", json.dumps({"section": section, "value": value}),
                    content_type="application/json")
        assert r.status_code == 200, (section, r.content)
    return o


def owner_secret(o, token, kind, slot, value):
    r = o.post(f"/api/f/{token}/secret", json.dumps({"kind": kind, "slot": slot,
                                                     "value": value}),
               content_type="application/json")
    assert r.status_code == 200, r.content


def payload(world, sub, by="fcc"):
    return as_(world[by]).get(f"/api/intake/submissions/{sub.pk}").json()


def states(p):
    return {x["name"]: x["state"] for x in p["plan"]["secrets"]}


def test_the_owner_submits_without_codes_and_send_waits_for_each(world, fake):
    world["_fake"] = fake
    sub, token = start(world)
    o = owner_answers(token)
    owner_secret(o, token, "tax_id", "", "12-3456789")
    owner_secret(o, token, "wifi_password", "", "powder-day")
    assert o.post(f"/api/f/{token}/submit").json() == {"state": "submitted"}
    c = review(world, sub, node_id=24, shares={"1": 40})

    p = payload(world, sub)
    assert p["may_send"] is False
    assert states(p) == {"tax_id": "held", "wifi_password": "held", "code:door": "missing",
                         "code:owner_closet": "missing", "code:alarm": "missing",
                         "code:extra-0": "missing"}
    assert "The door code isn't in ENHQ: enter it beside its question, or mark that there is " \
        "none." in p["plan"]["problems"]
    assert not any(s["key"].startswith("code:") for s in p["plan"]["steps"])
    r = c.post(f"/api/intake/submissions/{sub.pk}/send")
    assert r.status_code == 400 and "isn't in ENHQ" in r.json()["detail"]
    assert fake.writes() == [] and not SendRun.all_objects.filter(submission=sub).exists()

    # The reviewer enters the door code, and marks the others as having none.
    r = c.post(f"/api/intake/submissions/{sub.pk}/secret",
               json.dumps({"kind": "code", "slot": "door", "value": "4821"}),
               content_type="application/json")
    assert r.status_code == 200 and r.json()["secrets"]["codes"] == {"door": True}
    r = c.patch(f"/api/intake/submissions/{sub.pk}/staff", json.dumps({"changes": {
        "no_value": ["code:owner_closet", "code:alarm", "code:extra-0", "not a value"]}}),
        content_type="application/json")
    p = r.json()
    assert p["staff"]["no_value"] == ["code:owner_closet", "code:alarm", "code:extra-0"]
    assert p["may_send"] is True and p["plan"]["problems"] == []
    assert states(p)["code:door"] == "held" and states(p)["code:alarm"] == "none"
    assert "No alarm code is sent: marked as having none." in p["plan"]["summary"]

    run = send(world, sub)
    assert run.state == SendRun.State.SUCCEEDED, run.error
    [unit] = [u for u in fake.units.values() if u["name"] == "400 Lift Road"]
    codes = [x for x in fake.codes.values() if x["unitId"] == unit["id"]]
    assert [(x["codeTypeId"], x["code"]) for x in codes] == [(1, "4821")]
    assert not SubmissionSecret.all_objects.filter(submission=sub).exists()


def test_a_value_removed_after_send_was_pressed_stops_before_any_write(world, fake):
    from .intake_fake_track import client as fake_client
    from .test_intake_flow import ready

    sub = ready(world)
    r = as_(world["fcc"]).post(f"/api/intake/submissions/{sub.pk}/send")
    assert r.status_code == 202
    vault.clear(sub, "code", "alarm")              # gone before the worker started
    run = SendRun.all_objects.get(pk=r.json()["run"]["id"])
    services.run_send(run, client=fake_client(fake))
    run.refresh_from_db()
    assert run.state == SendRun.State.FAILED
    assert run.error.startswith("Not ready to send: The alarm code isn't in ENHQ")
    assert run.error.endswith("Nothing was written to Track.")
    assert fake.writes() == []
    sub.refresh_from_db()
    assert sub.status == Submission.Status.FAILED and not sub.locked


def test_try_the_rest_again_treats_what_track_has_as_done(world, fake):
    from .test_intake_flow import ready

    world["_fake"] = fake
    sub = ready(world)
    fake.fail_once[("POST", "/pms/units/{n}/security-codes")] = "refuse"
    first = send(world, sub)
    assert first.state == SendRun.State.FAILED and "Simulated refusal" in first.error
    sub.refresh_from_db()
    # Track confirmed the Tax ID and the Wi-Fi password; ENHQ deleted both, and
    # recorded that Track has them.
    assert sub.track["sent"] == ["tax_id", "wifi_password"]
    assert vault.held_names(sub) == {"code:door", "code:owner_closet", "code:alarm",
                                     "code:extra-0"}
    p = payload(world, sub)
    assert states(p)["tax_id"] == "sent" and states(p)["wifi_password"] == "sent"
    assert p["plan"]["problems"] == [] and p["may_send"] is True
    assert not any("Tax ID" in w for w in p["plan"]["warnings"])
    # Intake #1 stopped before ENHQ recorded what Track had: its finished
    # steps are enough.
    Submission.all_objects.filter(pk=sub.pk).update(
        track={k: v for k, v in sub.track.items() if k != "sent"})
    sub.refresh_from_db()
    p = payload(world, sub)
    assert p["plan"]["problems"] == [] and states(p)["tax_id"] == "sent"

    second = send(world, sub)
    assert second.state == SendRun.State.SUCCEEDED, second.error
    steps = {s["key"]: s for s in second.steps}
    assert steps["owner"]["state"] == "skipped" and steps["details"]["state"] == "skipped"
    [owner] = [x for x in fake.owners.values() if x["name"] == "Sample Homes LLC"]
    assert owner["taxIdMasked"] == "**-***6789"
    [unit] = [u for u in fake.units.values() if u["name"] == "400 Lift Road"]
    assert unit["custom"]["pms_units_wifi_password"] == "powder-day"
    assert len([x for x in fake.codes.values() if x["unitId"] == unit["id"]]) == 4


def test_a_closet_that_opens_with_a_key_plans_no_code(world, fake):
    world["_fake"] = fake
    sub, token = start(world)
    a = full_answers()
    a["access"] = {"door": "keypad", "owner_closet": "key", "alarm": "no_code",
                   "extra_codes": []}
    o = owner_answers(token, a)
    owner_secret(o, token, "tax_id", "", "12-3456789")
    owner_secret(o, token, "wifi_password", "", "powder-day")
    owner_secret(o, token, "code", "door", "4821")
    o.post(f"/api/f/{token}/submit")
    review(world, sub, node_id=24)
    p = payload(world, sub)
    assert [x["name"] for x in p["plan"]["secrets"]] == ["tax_id", "wifi_password", "code:door"]
    assert p["may_send"] is True
    run = send(world, sub)
    assert run.state == SendRun.State.SUCCEEDED, run.error
    assert [s["key"] for s in run.steps if s["key"].startswith("code:")] == ["code:door"]
    assert [x["code"] for x in fake.codes.values()] == ["4821"]


def test_the_owners_closet_answer_from_before_the_rewording_still_asks_for_its_code(world):
    sub, token = start(world)
    owner_answers(token)                       # access: owner_closet "yes", alarm "yes"
    sub.refresh_from_db()
    assert sub.answers["access"]["owner_closet"] == "code"
    assert sub.answers["access"]["alarm"] == "code"
