"""The owner-to-unit link's start date, made plain (owner, 2026-11-23): the
default stays the owner's ready date; a link that starts after the send day
says so on its send step and on the locked record; the review screen's
"Start today" is the practice's date and leaves the Contract Effective Date.
Against the fake Track (tests/intake_fake_track.py)."""

from __future__ import annotations

import json

import pytest

from apps.intake.models import SendRun

from .test_intake_dates import evening  # noqa: F401
from .test_intake_flow import as_, fake, ready, review, send, world  # noqa: F401

pytestmark = pytest.mark.django_db

# The sample owner is ready on 2030-01-10; `send` runs on 2026-11-20.
NOTE = ("Owner linked in Track. The link takes effect on January 10, 2030. Until then some "
        "Track screens won't show the owner on the unit.")


def page(world, sub):
    return as_(world["fcc"]).get(f"/api/intake/submissions/{sub.pk}").json()


def test_a_link_that_starts_later_says_so_on_its_step_and_the_locked_record(world, fake):
    world["_fake"] = fake
    sub = ready(world)
    assert page(world, sub)["link_note"] == ""            # no link yet
    run = send(world, sub)
    assert run.state == SendRun.State.SUCCEEDED, run.error
    sub.refresh_from_db()
    [ownership] = fake.ownerships.values()
    assert ownership["startDate"] == "2030-01-10"
    assert sub.track["link_start"] == "2030-01-10"
    step = next(s for s in run.steps if s["key"] == "ownership")
    assert step["detail"] == f"Track id {sub.track['ids']['ownership']}. {NOTE}"
    shown = page(world, sub)
    assert shown["locked"] and shown["link_note"] == NOTE
    assert any(s["detail"].endswith(NOTE) for s in shown["run"]["steps"])


def test_a_link_that_starts_on_the_send_day_says_nothing_more(world, fake):
    world["_fake"] = fake
    sub = ready(world)
    review(world, sub, start_date="2026-11-20")
    run = send(world, sub)
    assert run.state == SendRun.State.SUCCEEDED, run.error
    sub.refresh_from_db()
    step = next(s for s in run.steps if s["key"] == "ownership")
    assert step["detail"] == f"Track id {sub.track['ids']['ownership']}"
    assert sub.track["link_start"] == "2026-11-20"
    assert page(world, sub)["link_note"] == ""
    assert "takes effect" not in json.dumps(run.steps)


def test_an_intake_sent_before_the_date_was_kept_reads_the_reviewers_start(world, fake):
    """Intakes #1 and #2 (2026-11-20) were sent before `link_start` was kept."""
    world["_fake"] = fake
    sub = ready(world)
    send(world, sub)
    sub.refresh_from_db()
    sub.track = {k: v for k, v in sub.track.items() if k != "link_start"}
    sub.save(update_fields=["track"])
    assert page(world, sub)["link_note"] == NOTE


def test_start_today_is_the_practice_date_and_leaves_the_contract_effective_date(world,
                                                                                  evening):
    sub = ready(world)
    before = page(world, sub)
    # 18:30 MST on Nov 19: the server's UTC date is already the 20th.
    assert before["today"] == "2026-11-19"
    assert before["staff"]["start_date"] == "2030-01-10"
    assert before["staff"]["contract_effective_date"] == "2030-01-10"
    r = as_(world["fcc"]).patch(f"/api/intake/submissions/{sub.pk}/staff",
                                json.dumps({"changes": {"start_date": before["today"]}}),
                                content_type="application/json")
    assert r.status_code == 200, r.content
    after = r.json()
    assert after["staff"]["start_date"] == "2026-11-19"
    assert after["staff"]["contract_effective_date"] == "2030-01-10"
