"""The fix round before Michael's test drive (owner, 2026-11-25), owner
agreements' part:

- the standing authorization's consent names the signer ("I, Michael LeClerc,
  adopt…"), and the words shown on the screen are exactly the words recorded;
- a list holding two people of one name says each one's role: the
  authorization in force with Bryan's practice-owner and Client-owner
  accounts reads "Bryan Baker (Practice owner), Bryan Baker (Client owner)"
  on screen (the screen adds the roles; the payload carries them)."""

from __future__ import annotations

import json

import pytest

from apps.agreements.models import CountersignAuthority

from .factories import MembershipFactory, UserFactory
from .test_agreements import as_, aw, fake, record_authority, world  # noqa: F401

pytestmark = pytest.mark.django_db


def _page(w, who="michael"):
    r = as_(w[who]).get(f"/api/agreements/companies/{w['company'].pk}/authority")
    assert r.status_code == 200, r.content
    return r.json()


def _named(w, key, name):
    w[key].user.full_name = name
    w[key].user.save()


def test_the_consent_shown_names_the_signer_and_is_exactly_the_consent_stored(aw):
    _named(aw, "michael", "Michael LeClerc")
    shown = _page(aw)["wording"]
    assert shown.startswith("I, Michael LeClerc, adopt the signature shown here as ")
    assert "I, , " not in shown
    after = record_authority(aw, [aw["jackie"].user])
    row = CountersignAuthority.all_objects.get(company=aw["company"], ended_at__isnull=True)
    assert row.wording == shown                       # the words ticked are the words kept
    assert after["authority"]["wording"] == shown     # and the page shows them so afterwards
    assert after["wording"] == shown                  # a new one would be worded the same


def test_the_consent_follows_the_account_name_on_the_day(aw):
    _named(aw, "michael", "Michael LeClerc")
    record_authority(aw, [])
    _named(aw, "michael", "Michael J. LeClerc")
    shown = _page(aw)["wording"]
    assert shown.startswith("I, Michael J. LeClerc, adopt")
    record_authority(aw, [])
    now = CountersignAuthority.all_objects.get(company=aw["company"], ended_at__isnull=True)
    assert now.wording == shown
    before = CountersignAuthority.all_objects.filter(company=aw["company"],
                                                     ended_at__isnull=False).get()
    assert before.wording.startswith("I, Michael LeClerc, adopt")    # the old record unchanged


def test_two_people_of_one_name_come_with_their_roles(aw):
    _named(aw, "ff", "Bryan Baker")
    bryan = MembershipFactory(tenant=aw["practice"], role="FCC", client_company=aw["company"],
                              user=UserFactory(full_name="Bryan Baker"))
    page = _page(aw)
    offered = {p["user_id"]: (p["name"], p["role"]) for p in page["people"]}
    assert offered[str(aw["ff"].user_id)] == ("Bryan Baker", "Practice owner")
    assert offered[str(bryan.user_id)] == ("Bryan Baker", "Client owner")
    assert offered[str(aw["jackie"].user_id)][1] == "Client team member"

    after = record_authority(aw, [aw["jackie"].user, aw["ff"].user, bryan.user])
    in_force = [(p["name"], p["role"]) for p in after["authority"]["people"]]
    assert ("Bryan Baker", "Practice owner") in in_force
    assert ("Bryan Baker", "Client owner") in in_force
    # The record keeps ids and names, as before: the roles are for the screen.
    row = CountersignAuthority.all_objects.get(company=aw["company"], ended_at__isnull=True)
    assert all(set(p) == {"user_id", "name"} for p in row.people)
    assert json.dumps(after).count("FCC") == 0       # roles by name, never by code


def test_someone_no_longer_active_keeps_their_name_with_no_role(aw):
    record_authority(aw, [aw["jackie"].user])
    from django.utils import timezone

    aw["jackie"].revoked_at = timezone.now()
    aw["jackie"].save()
    people = _page(aw)["authority"]["people"]
    assert people == [{"user_id": str(aw["jackie"].user_id),
                       "name": aw["jackie"].user.full_name, "role": ""}]
