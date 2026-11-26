"""The fix round before Michael's test drive (owner, 2026-11-25), intake's
part: a test send's steps read in plain words, what would be created or set,
with none of Track's API paths on the screen and no line ending in a bare
"Would send". The call each step would make is kept in the saved run, as
`request`, never shown."""

from __future__ import annotations

import re

import pytest

from apps.intake import services
from apps.intake.models import IntakeForm, SendRun

from .test_intake_flow import as_, fake, ready, world  # noqa: F401

pytestmark = pytest.mark.django_db

#: Anything of Track's API: a path, a placeholder or a method.
TECHNICAL = re.compile(r"/(crm|pms)/|\{[a-z_]+\}|\b(GET|POST|PUT|PATCH|DELETE)\b")


def _test_send(world, fake):
    world["_fake"] = fake
    sub = ready(world)
    form = IntakeForm.all_objects.get(pk=world["form"].pk)
    form.settings = {**form.settings, "test_mode": True}
    form.save()
    r = as_(world["fcc"]).post(f"/api/intake/submissions/{sub.pk}/send")
    assert r.status_code == 202, r.content
    run = SendRun.all_objects.get(pk=r.json()["run"]["id"])
    assert run.test
    return sub, run


def test_each_step_says_in_plain_words_what_would_be_created_or_set(world, fake):
    sub, run = _test_send(world, fake)
    would = [s for s in run.steps if s["state"] == "would"]
    assert len(would) > 5
    for s in would:
        assert s["detail"].startswith("Would "), s
        assert not TECHNICAL.search(s["detail"]), s
        assert "Would send" not in s["detail"] and s["detail"].strip() != "Would", s
    by_key = {s["key"]: s for s in run.steps}
    assert by_key["contact:0"]["detail"] == "Would be created in Track"
    assert by_key["owner"]["detail"] == "Would be created in Track"
    assert by_key["unit"]["detail"] == "Would be created in Track"
    assert by_key["link:0"]["detail"] == "Would be linked in Track"
    assert by_key["details"]["detail"] == "Would be set on the unit in Track"
    assert by_key["ownership"]["detail"] == "Would be linked in Track"
    assert any(k.startswith("room:") and s["detail"] == "Would be added to the unit in Track"
               for k, s in by_key.items())
    # The one that used to end in a bare "Would send": the TVs, with no path of its own.
    assert by_key["count:tv"]["label"] == "Set the number of TVs (3)"
    assert by_key["count:tv"]["detail"] == "Would be set on the unit in Track"


def test_the_saved_run_keeps_the_call_each_step_would_make(world, fake):
    sub, run = _test_send(world, fake)
    by_key = {s["key"]: s for s in run.steps}
    assert by_key["contact:0"]["request"] == "POST /crm/contacts"
    assert by_key["owner"]["request"] == "POST /pms/owners"
    assert by_key["unit"]["request"] == "POST /pms/units"
    assert by_key["details"]["request"] == "PUT /pms/units/{unit}"
    assert by_key["ownership"]["request"] == "POST /pms/owners/{owner}/units"
    assert by_key["count:tv"]["request"].startswith("PATCH /pms/units/{unit}/amenities/")
    assert "count 3" in by_key["count:tv"]["request"]
    track = [s for s in run.steps if s["state"] == "would" and not s["key"].startswith("enhq:")]
    assert all(s["request"] for s in track)


def test_the_review_screen_receives_no_track_paths(world, fake):
    sub, _ = _test_send(world, fake)
    review = as_(world["fcc"]).get(f"/api/intake/submissions/{sub.pk}").json()
    shown = [s.get("detail") or "" for s in review["run"]["steps"]]
    assert shown and not any(TECHNICAL.search(d) for d in shown)
    assert not any(d.rstrip().endswith("Would send") for d in shown)


def test_a_step_of_a_kind_not_listed_still_reads_plainly():
    assert services.would({"key": "something:new", "kind": "create"}) == \
        "Would be created in Track"
    assert services.would({"key": "else", "kind": "brand_new_kind"}) == "Would be done in Track"
