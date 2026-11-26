"""The intake changes that came with owner agreements (owner, 2026-11-23):
test mode, square footage and the emergency contact, and intake access moved
from team levels to a tick (with the data migration that keeps today's
people in)."""

from __future__ import annotations

import importlib

from django.apps import apps as django_apps

import pytest

from apps.agreements.models import StaffAccess
from apps.intake import checklist, defaults, derive, plan
from apps.intake.models import IntakeForm, SendRun, Submission
from apps.work import teams

from .factories import MembershipFactory
from .test_intake_flow import as_, fake, ready, send, world  # noqa: F401
from .test_intake_plan import LISTS, SETTINGS, TODAY, answers, staff

pytestmark = pytest.mark.django_db


def _test_mode(world, on=True):
    form = IntakeForm.all_objects.get(pk=world["form"].pk)
    form.settings = {**form.settings, "test_mode": on}
    form.save()


def test_test_mode_checks_everything_and_writes_nothing(world, fake):
    world["_fake"] = fake
    sub = ready(world)
    _test_mode(world, True)
    writes = len(fake.writes())
    r = as_(world["fcc"]).post(f"/api/intake/submissions/{sub.pk}/send")
    assert r.status_code == 202, r.content
    run = SendRun.all_objects.get(pk=r.json()["run"]["id"])
    assert run.test and run.state == SendRun.State.SUCCEEDED
    assert run.steps[0]["key"] == "test:check" and run.steps[0]["state"] == "done"
    assert all(s["state"] == "would" for s in run.steps[1:])
    # Plain words on the screen; the call kept in the saved run (owner, 2026-11-25).
    assert any(s.get("request", "").startswith("POST /pms/units") for s in run.steps)
    assert not any("/pms/" in s["detail"] for s in run.steps)
    assert len(fake.writes()) == writes                       # nothing written to Track
    sub.refresh_from_db()
    assert sub.locked_at is None and sub.project_id is None and sub.status == "submitted"
    from apps.intake.models import SubmissionSecret
    assert SubmissionSecret.all_objects.filter(submission=sub).exists()     # nothing deleted
    rows = as_(world["fcc"]).get(f"/api/intake/companies/{world['company'].pk}/submissions")
    assert rows.json()["test_mode"] and rows.json()["submissions"][0]["tested"]
    review = as_(world["fcc"]).get(f"/api/intake/submissions/{sub.pk}").json()
    assert review["test_mode"] and review["run"]["test"]
    # Off: the same intake goes for real.
    _test_mode(world, False)
    run = send(world, sub)
    assert run.state == SendRun.State.SUCCEEDED and not run.test
    assert len(fake.writes()) > writes


def test_a_form_made_before_test_mode_existed_is_in_test_mode(world):
    form = IntakeForm.all_objects.get(pk=world["form"].pk)
    settings = dict(form.settings)
    settings.pop("test_mode", None)
    from apps.intake import services

    assert services.test_mode(settings) is True
    assert defaults.build(LISTS)["test_mode"] is True


def test_square_footage_goes_to_the_units_area_and_the_emergency_contact_to_new_owner_notes():
    a = answers()
    a["property"]["square_feet"] = 1850
    a["about"]["emergency"] = {"name": "Jamie Sample", "phone": "435-555-0188", "address": ""}
    the_plan = plan.build(answers=a, staff=staff(), settings=SETTINGS, lists=LISTS,
                          brand="Mountain Stays", held={"tax_id", "wifi_password",
                                                        "code:door", "code:owner_closet",
                                                        "code:alarm", "code:extra-0"},
                          sent=set(), today=TODAY)
    unit = next(s for s in the_plan["steps"] if s["key"] == "unit")
    assert unit["body"]["area"] == 1850
    owner = next(s for s in the_plan["steps"] if s["key"] == "owner")
    assert "Emergency contact: Jamie Sample, 435-555-0188." in owner["body"]["notes"]
    assert derive.owner_notes({"about": {}}, "x") == ""


def test_an_existing_owner_gets_a_task_for_the_emergency_contact(world):
    from .factories import IntakeSubmissionFactory

    from apps.tenancy.context import tenant_context

    sub = IntakeSubmissionFactory(tenant=world["practice"], form=world["form"],
                                  answers={"about": {"emergency": {"name": "Jamie"}}})
    with tenant_context(world["practice"].pk):
        assert "existing_owner_emergency" in checklist.conditions(sub, mode="existing")
        assert "existing_owner_emergency" not in checklist.conditions(sub, mode="new")
    item = next(i for i in defaults.CHECKLIST if i["key"] == "emergency_contact")
    assert "Jamie" not in item["title"]                       # titles never carry a name
    refreshed = defaults.refreshed({**SETTINGS, "checklist": [{"key": "portal"}],
                                    "checklist_offered": []}, LISTS)
    assert [i["key"] for i in refreshed["checklist"]] == ["portal", "emergency_contact",
                                                          "tax_by_phone"]
    again = defaults.refreshed({**refreshed, "checklist": [{"key": "portal"}]}, LISTS)
    assert [i["key"] for i in again["checklist"]] == ["portal"]   # removed stays removed


def test_the_migration_ticks_intake_for_everyone_the_old_rule_let_in(world):
    company, practice = world["company"], world["practice"]
    StaffAccess.all_objects.filter(company=company).delete()
    leader = MembershipFactory(tenant=practice, role="ECC", client_company=company)
    leader.leads_all_teams = True
    leader.save()
    revoked = MembershipFactory(tenant=practice, role="ECC", client_company=company)
    teams.place(teams.default_team(practice.pk, company.pk), revoked, "manager")
    from django.utils import timezone
    revoked.revoked_at = timezone.now()
    revoked.save()
    migration = importlib.import_module("apps.agreements.migrations.0002_intake_ticks_from_levels")
    migration.forwards(django_apps, None)
    ticked = set(StaffAccess.all_objects.filter(company=company, intake=True)
                 .values_list("user_id", flat=True))
    assert ticked == {world["fcc"].user_id, world["manager"].user_id, leader.user_id}
    assert world["member"].user_id not in ticked and revoked.user_id not in ticked
    migration.backwards(django_apps, None)
    assert not StaffAccess.all_objects.filter(company=company).exists()
