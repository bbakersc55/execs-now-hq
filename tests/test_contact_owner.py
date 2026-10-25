"""A contact's owner is a person (their user), set by the practice owner
(FR-1.1). Bryan, 2026-10-24: choosing a team member failed with "owner:
Invalid pk", because the picker sent their membership's id."""

from __future__ import annotations

import json

import pytest

from apps.crm.models import Contact

from . import registry_config  # noqa: F401
from .factories import ContactFactory, MembershipFactory

pytestmark = pytest.mark.django_db


def test_the_practice_owner_hands_a_contact_to_a_team_member(seeded_tenant, ff, api):
    contact = ContactFactory(tenant=seeded_tenant, owner=ff.user)
    va = MembershipFactory(tenant=seeded_tenant, role="VA")
    url = f"/api/contacts/{contact.pk}/"
    # Their place in the practice is not a person: refused, nothing changes.
    wrong = api.as_(ff).patch(url, json.dumps({"owner": str(va.pk)}),
                              content_type="application/json")
    assert wrong.status_code == 400
    assert Contact.all_objects.get(pk=contact.pk).owner_id == ff.user.pk
    # The person, as the staff list's `user` gives it.
    staff = {m["id"]: m["user"] for m in api.as_(ff).get("/api/staff/").json()}
    right = api.as_(ff).patch(url, json.dumps({"owner": staff[str(va.pk)]}),
                              content_type="application/json")
    assert right.status_code == 200
    assert Contact.all_objects.get(pk=contact.pk).owner_id == va.user_id
