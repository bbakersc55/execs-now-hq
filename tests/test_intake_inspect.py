"""scripts/intake_inspect.py, the read-only look at a company's intakes and
what they made in Track, run here against the fake Track on the test database:
it reads ENHQ once and writes nothing, sends Track nothing but GETs, finds a
link Track made that ENHQ never heard about, and prints no name, address,
email, phone or sensitive value.

Set INTAKE_INSPECT_OUT to a path to keep what the script printed."""

from __future__ import annotations

import os
import runpy
from pathlib import Path

import pytest
from django.db import connection

from apps.intake.models import SendRun, Submission

from .test_intake_flow import fake, ready, send, start, world  # noqa: F401

pytestmark = pytest.mark.django_db(transaction=True)
SCRIPT = str(Path(__file__).resolve().parent.parent / "scripts" / "intake_inspect.py")

NEVER_PRINTED = ("Alex", "Sample", "samplehomes", "Lift Road", "Pine Way", "Denver", "555",
                 "4821", "7730", "1199", "5501", "powder-day", "6789", "@")


def _run(monkeypatch, company):
    monkeypatch.setenv("INTAKE_INSPECT_COMPANY", str(company.pk))
    try:
        return runpy.run_path(SCRIPT)
    finally:
        connection.execute_wrappers.clear()


def _rows():
    return [(s.pk, s.status, s.track, s.staff, s.answers) for s in
            Submission.all_objects.order_by("number")], \
        [(r.pk, r.state, r.steps, r.error) for r in SendRun.all_objects.order_by("created_at")]


def test_reads_every_intake_and_finds_what_track_holds(world, fake, monkeypatch, capsys):
    world["_fake"] = fake
    sent = ready(world)
    assert send(world, sent).state == SendRun.State.SUCCEEDED
    lost = ready(world)
    fake.fail_once[("POST", "/pms/owners/{n}/units")] = "lose"   # Track made it, ENHQ never heard
    assert send(world, lost).state == SendRun.State.FAILED
    start(world)                                                  # a third, never sent
    sent.refresh_from_db()
    lost.refresh_from_db()
    before, writes = _rows(), len(fake.writes())

    g = _run(monkeypatch, world["company"])
    out = capsys.readouterr().out
    if os.environ.get("INTAKE_INSPECT_OUT"):
        Path(os.environ["INTAKE_INSPECT_OUT"]).write_text(out)

    assert _rows() == before and len(fake.writes()) == writes
    assert "one read-only transaction, rolled back" in out and "0 writes. DONE." in out
    for n in (1, 2, 3):
        assert f"=== INTAKE #{n} " in out
    # The sent one: its link, with the start date it was sent with, and Track's row.
    ownership = sent.track["ids"]["ownership"]
    assert "[start date sent: 2030-01-10]" in out
    assert f"link {ownership}: unitId={sent.track['ids']['unit']}" in out
    assert "startDate=2030-01-10" in out
    # The lost one: the link isn't recorded in ENHQ, but Track has it.
    assert "ownership" not in lost.track["ids"]
    assert "attempted, not done: ownership" in out and "TRACK DIDN'T ANSWER" in out
    lost_part = out.split(f"=== INTAKE #{lost.number} ")[1].split("=== INTAKE")[0]
    assert f"1 to unit {lost.track['ids']['unit']}" in lost_part
    for text in NEVER_PRINTED:
        assert text not in out, text
    assert "code=" not in out

    # The client it built can't write, and a write never reaches Track.
    with pytest.raises(SystemExit, match="never writes"):
        g["client"].send("POST", "/crm/contacts", {"firstName": "x"})
    assert len(fake.writes()) == writes
    # Free text is reduced to its kind, or withheld.
    assert g["said"]("Track refused it: name: Alex Sample is taken; email: in use") == \
        "TRACK REFUSED, fields: name, email"
    assert g["said"]("Alex Sample, 400 Lift Road") == "[withheld, 26 chars]"
    assert g["said"]("A sensitive value this step needs is no longer in ENHQ (code:door). "
                     "Enter it again on the review screen.") == "MISSING VALUE code:door"
    # The link's step while it starts later (services.LINK_NOTE), as the send writes it.
    assert "Track id " + str(ownership) + "; the link takes effect on January 10, 2030" in out


def test_stops_before_track_for_a_company_that_isnt_skyrun(world, fake, monkeypatch):
    conn = world["company"].track_connection
    conn.domain = "otherplace.trackhs.com"
    conn.save()
    calls = len(fake.calls)
    with pytest.raises(SystemExit, match="isn't SkyRun Park City's"):
        _run(monkeypatch, world["company"])
    assert len(fake.calls) == calls
