"""Settings → Words (2026-10-15, Melissa's feedback): what a practice calls its
goals, projects, tasks and steps.

The two non-negotiable families first: only the practice owner changes them,
a client user reaches nothing here, and one practice's words never reach
another. Then the rules: the defaults stand until set, an emptied pair goes
back to the default, what is saved is checked, and saving moves no data.
"""

from __future__ import annotations

import json

import pytest

from apps.crm.models import Task
from apps.tenancy import words
from apps.tenancy.models import AuditEvent, Tenant

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import ClientCompanyFactory

ACTIONS = {"goal": {"singular": "Objective", "plural": "Objectives"},
           "project": {"singular": "initiative", "plural": "initiatives"},
           "task": {"singular": "action", "plural": "actions"},
           "step": {"singular": "", "plural": ""}}


def put(client, body):
    return client.put("/api/settings/words", json.dumps({"words": body}),
                      content_type="application/json")


@pytest.fixture
def ecc(seeded_tenant):
    return _member(seeded_tenant, "ECC", company=ClientCompanyFactory(tenant=seeded_tenant))


# ---------------------------------------------------------------- role boundaries

@pytest.mark.django_db
@pytest.mark.parametrize("who", ["cf", "va"])
def test_the_practice_owner_changes_them_and_staff_read_them(request, api, who, ff):
    client = api.as_(request.getfixturevalue(who))
    assert client.get("/api/settings/words").status_code == 200
    assert put(client, ACTIONS).status_code == 403
    assert put(api.as_(ff), ACTIONS).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("who", ["fcc", "ecc"])
def test_a_client_user_reaches_nothing_here(request, api, who):
    client = api.as_(request.getfixturevalue(who))
    assert client.get("/api/settings/words").status_code == 403
    assert put(client, ACTIONS).status_code == 403


@pytest.mark.django_db
def test_signed_out_reaches_nothing(client):
    assert client.get("/api/settings/words").status_code in (401, 403)


# ---------------------------------------------------------------- isolation

@pytest.mark.django_db
def test_one_practices_words_never_reach_another(api, ff, tenant_b):
    assert put(api.as_(ff), ACTIONS).status_code == 200
    other = _member(tenant_b, "FF")
    assert api.as_(other).get("/api/me").json()["words"] == words.DEFAULT.as_dict()
    assert api.as_(other).get("/api/settings/words").json()["words"]["task"] == {
        "singular": "task", "plural": "tasks"}


# ---------------------------------------------------------------- the rules

@pytest.mark.django_db
def test_the_defaults_stand_until_set_and_everyone_in_the_practice_is_told(api, ff, ecc):
    assert api.as_(ff).get("/api/me").json()["words"] == words.DEFAULT.as_dict()
    saved = put(api.as_(ff), ACTIONS).json()["words"]
    # Lower case for the middle of a sentence; an emptied pair is the default.
    assert saved["goal"] == {"singular": "objective", "plural": "objectives"}
    assert saved["step"] == {"singular": "step", "plural": "steps"}
    # The portal reads the practice's words too.
    assert api.as_(ecc).get("/api/me").json()["words"]["task"] == {
        "singular": "action", "plural": "actions"}
    tenant = Tenant.objects.get(pk=ff.tenant_id)
    assert "step" not in tenant.work_words
    w = words.of(tenant)
    assert (w.task, w.Tasks, w.a_task, w.a_project, w.Goal) == (
        "action", "Actions", "an action", "an initiative", "Objective")


@pytest.mark.django_db
def test_an_acronym_is_kept_as_typed(api, ff):
    saved = put(api.as_(ff), {"goal": {"singular": "OKR", "plural": "OKRs"}}).json()
    assert saved["words"]["goal"] == {"singular": "OKR", "plural": "OKRs"}
    assert words.of(Tenant.objects.get(pk=ff.tenant_id)).a_goal == "an OKR"


@pytest.mark.django_db
@pytest.mark.parametrize("pair", [
    {"singular": "action", "plural": ""},           # half a pair
    {"singular": "x" * 31, "plural": "xs"},          # too long
    {"singular": "task2", "plural": "tasks2"},       # digits
    {"singular": "a b c d", "plural": "a b c ds"},   # four words
    {"singular": "<b>", "plural": "<b>s"},           # not letters
])
def test_what_is_saved_is_checked(api, ff, pair):
    response = put(api.as_(ff), {"task": pair})
    assert response.status_code == 400
    assert response.json()["errors"]
    assert Tenant.objects.get(pk=ff.tenant_id).work_words == {}


@pytest.mark.django_db
def test_saving_is_audited_and_moves_no_data(api, ff):
    before = Task.all_objects.filter(tenant_id=ff.tenant_id).count()
    assert put(api.as_(ff), ACTIONS).status_code == 200
    assert put(api.as_(ff), ACTIONS).status_code == 200        # the same again
    assert list(AuditEvent.all_objects.filter(
        tenant_id=ff.tenant_id, verb="practice.words_changed").values_list(
        "payload__to__task", flat=True)) == [["action", "actions"]]
    assert Task.all_objects.filter(tenant_id=ff.tenant_id).count() == before
    # Back to the defaults: nothing stored.
    assert put(api.as_(ff), words.DEFAULT.as_dict()).status_code == 200
    assert Tenant.objects.get(pk=ff.tenant_id).work_words == {}


def test_the_frontend_defaults_match():
    import pathlib
    import re

    source = (pathlib.Path(__file__).resolve().parent.parent
              / "frontend/src/lib/words.ts").read_text()
    for kind, (one, many) in words.DEFAULTS.items():
        assert re.search(rf'{kind}: {{ singular: "{one}", plural: "{many}" }}', source), kind
