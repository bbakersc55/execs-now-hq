"""scripts/track_definitions.py, the read-only look at the bed types and unit
custom fields in SkyRun's Track, run here against the fake Track on the test
database: it reads ENHQ once and changes nothing, sends Track nothing but GETs,
and prints the definitions asked about with what ENHQ holds for them.

Set TRACK_DEFS_OUT to a path to keep what the script printed."""

from __future__ import annotations

import os
import runpy
from pathlib import Path

import pytest
from django.db import connection

from apps.intake.models import IntakeForm, TrackListSnapshot

from . import intake_fake_track
from .test_intake_flow import fake, world  # noqa: F401

pytestmark = pytest.mark.django_db(transaction=True)
SCRIPT = str(Path(__file__).resolve().parent.parent / "scripts" / "track_definitions.py")


def _run(monkeypatch, company):
    monkeypatch.setenv("TRACK_DEFS_COMPANY", str(company.pk))
    try:
        return runpy.run_path(SCRIPT)
    finally:
        connection.execute_wrappers.clear()


def _new_in_track(monkeypatch):
    lists = intake_fake_track.LISTS
    monkeypatch.setitem(lists, "bed_types", lists["bed_types"] + [
        {"id": 9101, "name": "King Sofa Sleeper", "isActive": True},
        {"id": 9102, "name": "Rollaway", "isActive": True}])
    monkeypatch.setitem(lists, "custom_fields", lists["custom_fields"] + [
        {"id": 9201, "name": "Water Softener", "reference": "pms_units_water_softener",
         "type": "select", "subType": "", "values": [
             {"id": 1, "handle": "yes", "name": "Yes"}, {"id": 2, "handle": "no", "name": "No"}]},
        {"id": 9202, "name": "Landscaping", "reference": "pms_units_landscaping",
         "type": "text", "subType": "textarea", "values": []}])


def test_prints_the_new_definitions_and_writes_nothing(world, fake, monkeypatch, capsys):
    _new_in_track(monkeypatch)
    before = ([(s.kind, s.fetched_at, s.payload) for s in TrackListSnapshot.all_objects.all()],
              [(f.pk, f.settings) for f in IntakeForm.all_objects.all()])
    writes = len(fake.writes())

    g = _run(monkeypatch, world["company"])
    out = capsys.readouterr().out
    if os.environ.get("TRACK_DEFS_OUT"):
        Path(os.environ["TRACK_DEFS_OUT"]).write_text(out)

    after = ([(s.kind, s.fetched_at, s.payload) for s in TrackListSnapshot.all_objects.all()],
             [(f.pk, f.settings) for f in IntakeForm.all_objects.all()])
    assert after == before and len(fake.writes()) == writes
    assert "one read-only transaction, rolled back" in out and ", 0 writes." in out
    assert "id=9101 active=True name='King Sofa Sleeper'" in out
    assert "name='Rollaway'" in out and "in ENHQ's copy=False  <== new" in out
    assert "rule today for 'Rollaway': sleeps 1, known" in out           # owner, 2026-11-23
    assert "ref=pms_units_water_softener type=select" in out
    assert "choice id=1 handle='yes' name='Yes'" in out
    assert "ref=pms_units_landscaping type=text" in out
    assert "pms_units_other_maintenance_or_service_notes" in out
    assert "name='Standard 30'" in out                  # the contracts, for the split
    assert "== Field names (no values) on test unit 222 and test owner 266 ==" in out
    assert "Jackie: 0 user(s)" in out                   # first names only, by count

    with pytest.raises(SystemExit, match="never writes"):
        g["client"].send("POST", "/pms/units/bed-types", {"name": "x"})
    assert len(fake.writes()) == writes


def test_stops_before_track_for_a_company_that_isnt_skyrun(world, fake, monkeypatch):
    conn = world["company"].track_connection
    conn.domain = "otherplace.trackhs.com"
    conn.save()
    calls = len(fake.calls)
    with pytest.raises(SystemExit, match="isn't SkyRun Park City's"):
        _run(monkeypatch, world["company"])
    assert len(fake.calls) == calls
