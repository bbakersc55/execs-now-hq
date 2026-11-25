"""Track's lists on the owner's form (owner, 2026-11-24, after the demo walk).

The form's choices (bed types, bathroom features, kinds of property, kinds of
code, amenities) come from ENHQ's copy of Track's lists, never from Track
while the owner waits. An owner never meets an empty dropdown with no
explanation: the last good copy of each list is used when there is one; when
there is none (Track never read for the company, as on the demo), the form
says so in plain words, takes the owner's own words instead, lets them carry
on, and the review flags it for staff.
"""

from __future__ import annotations

import json

import pytest
from django.test import Client

from apps.intake import schema, tracklists
from apps.intake.models import Submission, SubmissionEvent, TrackListSnapshot
from apps.scorecard import track

from . import intake_fake_track
from .test_intake_flow import as_, fake, start, world  # noqa: F401

pytestmark = pytest.mark.django_db

ALL = ["bed_types", "bathroom_fixtures", "lodging_types", "code_types", "amenity_groups"]
EVENT = ("The owner's form had no list from Track of bed types, bathroom features, kinds of "
         "property, kinds of code (garage, gate, pool…) and amenities, so the owner could only "
         "carry on and describe them in their own words")


def unreachable(monkeypatch):
    """As on the demo: no copy, and Track can't be read."""
    def refuse(client):
        raise track.TrackUnavailable("Track couldn't be reached.")
    monkeypatch.setattr(tracklists, "fetch", refuse)


def save(o, token, section, value):
    r = o.patch(f"/api/f/{token}/answers", json.dumps({"section": section, "value": value}),
                content_type="application/json")
    assert r.status_code == 200, r.content
    return r.json()


def review(world, sub):
    r = as_(world["fcc"]).get(f"/api/intake/submissions/{sub.pk}")
    assert r.status_code == 200, r.content
    return r.json()


def test_with_no_copy_the_owner_is_told_writes_in_words_carries_on_and_staff_are_told(
        world, monkeypatch):
    TrackListSnapshot.all_objects.filter(company=world["company"]).delete()
    unreachable(monkeypatch)
    sub, token = start(world)
    o = Client()
    form = o.get(f"/api/f/{token}").json()["form"]
    assert form["lists_missing"] == ALL
    for name in ALL:
        assert form[name] == [], name
    # Said once in the intake's history, however often the owner opens it.
    o.get(f"/api/f/{token}")
    events = SubmissionEvent.all_objects.filter(submission=sub, kind="lists_missing")
    assert [e.detail for e in events] == [EVENT]

    # The owner writes what they can't choose, and carries on to submit.
    save(o, token, "about", {"first_name": "Alex", "last_name": "Sample",
                             "email": "alex@samplehomes.net"})
    save(o, token, "tax", {"kind": "phone"})
    save(o, token, "property", {"street": "400 Lift Road", "city": "Park City",
                                "lodging_note": "A condo"})
    save(o, token, "bedrooms", [{"beds": [], "own_bath": True,
                                 "beds_note": "One king, two twins"}])
    save(o, token, "other_sleeping", {"has": "yes", "places": [
        {"where": "living", "label": "", "beds": [], "beds_note": "A queen sofa bed"}]})
    save(o, token, "bathrooms", [{"fixtures": {}, "note": "Toilet, two sinks, a shower"}])
    save(o, token, "amenities", {"common": [], "more_note": "A hot tub on the deck"})
    save(o, token, "access", {"door": "key", "extra_codes": [{"type": 0, "note": "Garage"}]})
    assert o.post(f"/api/f/{token}/submit").json() == {"state": "submitted"}
    sub.refresh_from_db()
    a = sub.answers
    assert a["property"]["lodging_note"] == "A condo"
    assert a["bedrooms"] == [{"beds": [], "own_bath": True, "beds_note": "One king, two twins"}]
    assert a["other_sleeping"]["places"][0]["beds_note"] == "A queen sofa bed"
    assert a["bathrooms"] == [{"fixtures": {}, "note": "Toilet, two sinks, a shower"}]
    assert a["amenities"]["more_note"] == "A hot tub on the deck"
    assert a["access"]["extra_codes"] == [{"type": 0, "note": "Garage"}]
    assert sub.status == Submission.Status.SUBMITTED

    # The review: when the owner's form lacked the lists, and that there is
    # still no copy; the owner's words are in the answers it shows.
    page = review(world, sub)
    flags = page["lists_flags"]
    assert len(flags) == 2
    assert flags[0].startswith(EVENT + " (on ") and "choose from Track's lists" in flags[0]
    assert flags[1] == ("ENHQ has no copy of Track's list of bed types, bathroom features, kinds "
                        "of property, kinds of code (garage, gate, pool…) and amenities for "
                        "Mountain Stays, so owners can't choose them on the form. Open the "
                        "form's settings and use Refresh from Track now.")
    assert page["answers"]["bedrooms"][0]["beds_note"] == "One king, two twins"
    assert page["owner_form"]["lists_missing"] == ALL
    assert EVENT in [e["detail"] for e in page["events"]]


def test_once_the_copy_is_there_new_forms_choose_and_the_old_flag_stays(world, monkeypatch):
    TrackListSnapshot.all_objects.filter(company=world["company"]).delete()
    sub, token = start(world)
    with monkeypatch.context() as m:
        unreachable(m)
        Client().get(f"/api/f/{token}")
    # Track can be read again: staff refresh, and the copy is back.
    tracklists.lists_for(world["company"], refresh=True)
    flags = review(world, sub)["lists_flags"]
    assert len(flags) == 1 and flags[0].startswith(EVENT)          # what the owner met
    other, other_token = start(world, email="sam@samplehomes.net")
    form = Client().get(f"/api/f/{other_token}").json()["form"]
    assert form["lists_missing"] == [] and form["bed_types"] and form["lodging_types"]
    assert not SubmissionEvent.all_objects.filter(submission=other,
                                                  kind="lists_missing").exists()
    assert review(world, other)["lists_flags"] == []


def test_a_list_track_sends_back_empty_never_replaces_the_last_good_copy(world, monkeypatch):
    company = world["company"]
    before = TrackListSnapshot.all_objects.get(company=company, kind="bed_types")
    assert before.payload
    monkeypatch.setitem(intake_fake_track.LISTS, "bed_types", [])
    lists, status = tracklists.lists_for(company, refresh=True)
    assert lists["bed_types"] == before.payload and not status["stale"]
    kept = TrackListSnapshot.all_objects.get(company=company, kind="bed_types")
    assert kept.payload == before.payload and kept.fetched_at == before.fetched_at
    # The other lists were read afresh.
    assert TrackListSnapshot.all_objects.get(company=company, kind="lodging_types") \
        .fetched_at > before.fetched_at
    # And the owner's form still offers the beds.
    sub, token = start(world)
    form = Client().get(f"/api/f/{token}").json()["form"]
    assert form["bed_types"] and form["lists_missing"] == []


def test_track_down_when_the_owner_opens_the_form_changes_nothing_for_them(world, monkeypatch):
    """Production: the owner's page reads ENHQ's copy only; Track being down
    (even long past the hour) is never seen by the owner."""
    from datetime import timedelta

    from django.utils import timezone

    TrackListSnapshot.all_objects.filter(company=world["company"]).update(
        fetched_at=timezone.now() - timedelta(days=3))
    calls = []
    monkeypatch.setattr(tracklists, "fetch", lambda client: calls.append(1) or 1 / 0)
    sub, token = start(world)
    form = Client().get(f"/api/f/{token}").json()["form"]
    assert form["lists_missing"] == [] and form["bed_types"]
    assert calls == []                               # the owner's page never asked Track


def test_answers_without_the_owners_words_keep_their_shape():
    assert schema.clean_bedrooms([{"beds": [{"type": 3, "count": 1}]}]) == [
        {"beds": [{"type": 3, "count": 1}], "own_bath": False}]
    assert "lodging_note" not in schema.clean_property({"street": "1 Main"})
    assert schema.clean_bathrooms([{"fixtures": {"11": 1}, "note": "  "}]) == [
        {"fixtures": {"11": 1}}]
    assert schema.clean_access({"extra_codes": [{"type": 2}]})["extra_codes"] == [{"type": 2}]
    long = schema.clean_amenities({"more_note": "x" * 5000})["more_note"]
    assert len(long) == schema.LONG
