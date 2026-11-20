"""Intake's dates are the practice's dates, never the server's (owner,
2026-11-19). The server runs on UTC, so from 17:00 to midnight in Utah its
date is already tomorrow: the proof on SkyRun's Track at 18:30 MST on
2026-11-19 started its ownership and its codes on the 20th.

Every test here runs at that evening (the clock pinned), for a practice in
Mountain time, with no ready date, so each date falls back to "today".
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from django.conf import settings as dj
from django.utils import timezone

from apps.crm.models import Task
from apps.intake import ownerdates, services, tracklists
from apps.intake.models import OwnerDate, SendRun
from apps.tenancy.context import tenant_context

from .intake_fake_track import client as fake_client
from .test_intake_flow import fake, owner_fills, review, start, world  # noqa: F401
from .test_intake_plan import answers as full_answers

pytestmark = pytest.mark.django_db

EVENING = datetime(2026, 11, 20, 1, 30, tzinfo=UTC)          # 18:30 MST, Nov 19
AFTER_MIDNIGHT = datetime(2026, 11, 20, 7, 30, tzinfo=UTC)   # 00:30 MST, Nov 20
PRACTICE_TODAY = date(2026, 11, 19)


@pytest.fixture
def evening(monkeypatch, world):
    world["practice"].timezone = "America/Denver"
    world["practice"].save(update_fields=["timezone"])
    monkeypatch.setattr(timezone, "now", lambda: EVENING)
    return monkeypatch


def submitted(world):
    sub, token = start(world)
    a = full_answers()
    a["property"].update({"ready": "unsure", "ready_date": ""})
    o = owner_fills(token, a)
    o.post(f"/api/f/{token}/submit")
    review(world, sub, node_id=24, shares={"1": 40})
    sub.refresh_from_db()
    return sub


def test_the_review_defaults_and_the_plan_use_the_practice_date(world, evening):
    sub = submitted(world)
    lists, _ = tracklists.stored(sub.company)
    form_settings = services.settings_of(sub.form, lists)
    with tenant_context(sub.tenant_id):
        staff = services.staff_choices(sub, form_settings, lists)
        the_plan = services.build_plan(sub, lists, form_settings)
    assert staff["start_date"] == staff["contract_effective_date"] == "2026-11-19"
    codes = [s for s in the_plan["steps"] if s["key"].startswith("code:")]
    assert codes and {s["body"]["startDate"] for s in codes} == {"2026-11-19"}
    [ownership] = [s for s in the_plan["steps"] if s["key"] == "ownership"]
    assert ownership["body"]["startDate"] == "2026-11-19"
    # And the review screen shows the same.
    c = review(world, sub)
    shown = c.get(f"/api/intake/submissions/{sub.pk}").json()["staff"]
    assert shown["start_date"] == shown["contract_effective_date"] == "2026-11-19"


def test_a_send_in_the_evening_starts_everything_on_the_practice_date(world, fake, evening):
    sub = submitted(world)
    c = review(world, sub)
    r = c.post(f"/api/intake/submissions/{sub.pk}/send")
    assert r.status_code == 202, r.content
    run = SendRun.all_objects.get(pk=r.json()["run"]["id"])
    services.run_send(run, client=fake_client(fake))  # no `today`: the worker's way
    run.refresh_from_db()
    assert run.state == SendRun.State.SUCCEEDED, run.error
    assert {c["startDate"] for c in fake.codes.values()} == {"2026-11-19"}
    assert {o["startDate"] for o in fake.ownerships.values()} == {"2026-11-19"}
    sub.refresh_from_db()
    assert sub.project.start_date == PRACTICE_TODAY
    tasks = list(Task.all_objects.filter(project=sub.project))
    portal = next(t for t in tasks if t.title.startswith("Invite everyone"))
    assert portal.due_date == PRACTICE_TODAY
    assert min(t.due_date for t in tasks) == PRACTICE_TODAY


def test_held_dates_expire_at_the_practices_midnight_not_utcs(world, fake, evening):
    sub = submitted(world)
    sub.track = {"ids": {"unit": 900}}
    sub.save(update_fields=["track"])
    fake.units[900] = {"id": 900, "name": "x", "isActive": False, "isBookable": False}
    row = OwnerDate.all_objects.create(tenant=sub.tenant, submission=sub,
                                       start=date(2026, 11, 15), end=PRACTICE_TODAY)
    lists, _ = tracklists.stored(sub.company)
    with tenant_context(sub.tenant_id):
        result = ownerdates.place(sub, fake_client(fake), lists)  # the hourly job's way
    row.refresh_from_db()
    assert result["expired"] == 0 and row.state == OwnerDate.State.HELD
    evening.setattr(timezone, "now", lambda: AFTER_MIDNIGHT)
    with tenant_context(sub.tenant_id):
        result = ownerdates.place(sub, fake_client(fake), lists)
    row.refresh_from_db()
    assert result["expired"] == 1 and row.state == OwnerDate.State.EXPIRED


SERVER_DATE = re.compile(
    r"date\.today\(|datetime\.(now|today|utcnow)\(|localdate\(\s*\)|now\(\)\.date\(")


def test_no_intake_code_reads_the_servers_date():
    """Moments (timezone.now()) are fine; a date of "today" must come from
    services.practice_today or be passed in."""
    root = Path(dj.BASE_DIR)
    found = []
    for path in sorted((root / "apps" / "intake").rglob("*.py")):
        if "migrations" in path.parts:
            continue
        for number, line in enumerate(path.read_text().splitlines(), 1):
            code = line.split("#", 1)[0]
            if SERVER_DATE.search(code):
                found.append(f"{path.relative_to(root)}:{number}: {line.strip()}")
    proof = root / "scripts" / "intake_track_proof.py"
    for number, line in enumerate(proof.read_text().splitlines(), 1):
        if SERVER_DATE.search(line.split("#", 1)[0]):
            found.append(f"{proof.relative_to(root)}:{number}: {line.strip()}")
    assert not found, "\n".join(found)
