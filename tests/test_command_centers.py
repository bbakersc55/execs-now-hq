"""Command Centers (P8, docs/p8_command_centers.md): the catalog and the
switch, billing lines and the cap, the platform owner's exemption, copies on
first use kept apart between practices, the KPI library's "From the library",
starting a playbook, the plain-words check on everything shipped, the AI
actions, and the practice library."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.billing import subscriptions
from apps.billing.models import PracticeSubscriptionAddon
from apps.centers import catalog, playbooks, services
from apps.centers.content import operations
from apps.centers.models import CommandCenter, LibraryRecord, Playbook, PlaybookRun
from apps.scorecard import library
from apps.tenancy import ai_actions
from apps.tenancy.context import tenant_context

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import ClientCompanyFactory, ContactFactory, NoteFactory, TenantFactory
from .test_client_invoicing import patch, post

ROOT = "/api/command-centers/"


def turn_on(api, who, code="operations"):
    return post(api, who, f"{ROOT}{code}/", {"on": True})


@pytest.fixture
def on(seeded_tenant, ff, api):
    assert turn_on(api, ff).status_code == 200
    return seeded_tenant


def lines(tenant, period):
    row = subscriptions.subscription_for(tenant)
    return [(text, amount) for text, amount, _ in subscriptions.lines_for(row, period)]


# ============================================================ the switch

@pytest.mark.django_db
def test_the_catalog_has_eight_and_only_operations_is_available(seeded_tenant, ff, api):
    state = api.as_(ff).get(ROOT).json()
    assert [c["short_name"] for c in state["centers"]] == [
        "Operations", "People", "Technology", "Finance", "Sales", "Marketing", "Projects",
        "Training"]
    assert {c["code"]: c["status"] for c in state["centers"]}["operations"] == "available"
    assert all(c["status"] == "coming" for c in state["centers"] if c["code"] != "operations")
    assert [c["code"] for c in state["centers"] if c["next"]] == ["people", "technology"]
    assert all(c["name"].endswith("Command Center") and c["price_cents"] == 5000
               for c in state["centers"])
    assert state["cap_cents"] == 15000 and state["can_switch"] is True


@pytest.mark.django_db
def test_turning_one_on_adds_one_line_from_the_next_first(seeded_tenant, ff, api):
    assert "$50 a month is added" in api.as_(ff).get(ROOT).json()["price_line"]
    state = turn_on(api, ff).json()
    assert [c["code"] for c in state["centers"] if c["on"]] == ["operations"]
    [added] = PracticeSubscriptionAddon.all_objects.filter(tenant=seeded_tenant)
    first = subscriptions.first_of_next_month(timezone.localdate())
    assert added.charged_from == first and added.addon.price_cents == 5000
    assert ("Operations Command Center, " + first.strftime("%B %Y"), 5000) in lines(
        seeded_tenant, first)
    # Off: the line ends.
    post(api, ff, f"{ROOT}operations/", {"on": False})
    added.refresh_from_db()
    assert added.removed_at is not None


@pytest.mark.django_db
def test_four_on_are_billed_at_most_150(seeded_tenant, ff, api):
    services.ensure_catalog()   # a flushing test on this worker may have emptied it
    CommandCenter.objects.filter(code__in=["people", "technology", "finance"]).update(
        status="available")
    for code in ("operations", "people", "technology", "finance"):
        assert turn_on(api, ff, code).status_code == 200
    first = subscriptions.first_of_next_month(timezone.localdate())
    billed = lines(seeded_tenant, first)
    centers = [amount for text, amount in billed if "Command Center" in text]
    assert centers == [5000, 5000, 5000, 5000, -5000]
    assert ("Command Centers capped at $150 a month", -5000) in billed
    assert sum(centers) == 15000


@pytest.mark.django_db
def test_the_platform_owners_practice_pays_nothing(seeded_tenant, ff, api):
    ff.user.is_platform_owner = True
    ff.user.save()
    state = api.as_(ff).get(ROOT).json()
    assert state["owners_practice"] is True and "Included" in state["price_line"]
    assert turn_on(api, ff).status_code == 200
    assert services.has(seeded_tenant.pk, "operations")
    assert not PracticeSubscriptionAddon.all_objects.filter(tenant=seeded_tenant).exists()


@pytest.mark.django_db
def test_only_the_owner_switches_and_a_coming_one_is_refused(seeded_tenant, ff, cf, api):
    assert turn_on(api, cf).status_code == 403
    assert turn_on(api, ff, "people").status_code == 409
    assert not services.enabled(seeded_tenant.pk)


@pytest.mark.django_db
def test_the_demo_refuses_the_switch(settings, seeded_tenant, ff, api):
    settings.IS_DEMO = True
    state = api.as_(ff).get(ROOT).json()
    assert state["can_switch"] is False and "demo" in state["why_not"]
    refused = turn_on(api, ff)
    assert refused.status_code == 403 and "demo" in refused.json()["detail"]
    assert not services.enabled(seeded_tenant.pk)


@pytest.mark.django_db
def test_turning_one_on_changes_nothing_of_a_client(on, ff, api):
    from apps.esign.models import DocumentTemplate
    from apps.scorecard.models import Kpi
    from apps.strategy.models import StrategyTemplate
    from apps.work.models import Goal

    # Turned on in the fixture: nothing was copied or made by it.
    assert not Playbook.all_objects.filter(tenant=on).exists()
    assert not DocumentTemplate.all_objects.filter(tenant=on, original__startswith="ops_").exists()
    assert not Kpi.all_objects.filter(tenant=on).exists()
    assert not Goal.all_objects.filter(tenant=on).exists()
    assert not StrategyTemplate.all_objects.filter(tenant=on).exists()


# ======================================================= plain words

BANNED = re.compile(r"\b(rocks?|l10|integrator|visionary|accountability chart|"
                    r"six key components)\b", re.I)


def _texts(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _texts(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _texts(v)


def test_no_eos_term_in_anything_a_command_center_ships():
    shipped = [operations.session_template(), operations.KPIS, operations.PLAYBOOKS,
               operations.DOCUMENTS, operations.EMAILS, operations.TOOLS,
               operations.FEED_NAMES, catalog.CENTERS, library.BASE,
               [(a.label, a.prompt) for a in ai_actions.ACTIONS if a.center]]
    found = [text for text in _texts(shipped) if BANNED.search(text)]
    assert found == []


def test_the_check_would_catch_each_term():
    for text in ("Current Rocks", "the L10 meeting", "{Integrator}'s role", "the Visionary",
                 "Accountability Chart", "the Six Key Components"):
        assert BANNED.search(text), text


# ======================================================= session template

@pytest.mark.django_db
def test_the_command_center_template_is_offered_only_when_on(seeded_tenant, ff, api):
    from apps.strategy.models import StrategyQuestion

    body = {"name": "Ops", "start_from": "operations_command_center"}
    refused = post(api, ff, "/api/strategy-template-builder/", body)
    assert refused.status_code == 403 and "Turn on" in refused.json()["detail"]
    turn_on(api, ff)
    made = post(api, ff, "/api/strategy-template-builder/", body)
    assert made.status_code == 201, made.content
    prompts = list(StrategyQuestion.all_objects.filter(
        section__template_id=made.json()["id"], deleted_at__isnull=True)
        .values_list("prompt", flat=True))
    assert any("{Owner}" in p for p in prompts)
    assert any("weekly leadership meeting" in p for p in prompts)
    assert not [p for p in prompts if BANNED.search(p)]


@pytest.mark.django_db
def test_the_owner_merge_field_reads_the_owners_name(seeded_tenant):
    from apps.strategy import services as strategy

    assert strategy.MISSING_NAME["Owner"] == "the owner"


# ======================================================= copies stay apart

@pytest.mark.django_db
def test_a_copy_is_the_practices_own_and_never_reaches_another(on, ff, api, tenant_b):
    other_owner = _member(tenant_b, "FF")
    assert turn_on(api, other_owner).status_code == 200
    mine = post(api, ff, "/api/playbooks/copy/", {"key": "ops_hiring_round"}).json()
    patch(api, ff, f"/api/playbooks/{mine['id']}/",
          {"outline": "Goal: Our own way to hire\n## Find | week 1\n- Ask around | week 1\n"})
    theirs = post(api, other_owner, "/api/playbooks/copy/", {"key": "ops_hiring_round"}).json()
    assert theirs["id"] != mine["id"] and theirs["is_draft"] is True
    assert theirs["outline"] == operations.PLAYBOOKS["ops_hiring_round"][2]
    assert "Our own way" not in operations.PLAYBOOKS["ops_hiring_round"][2]
    # Neither sees the other's copy.
    assert mine["id"] not in json.dumps(api.as_(other_owner).get("/api/playbooks/").json())
    assert api.as_(other_owner).get(f"/api/playbooks/{mine['id']}/").status_code == 404


@pytest.mark.django_db
def test_module_documents_arrive_on_first_sight_marked_and_restorable(on, ff, api, tenant_b):
    from apps.esign.models import DocumentTemplate

    rows = api.as_(ff).get("/api/document-templates/").json()
    rows = rows.get("results", rows) if isinstance(rows, dict) else rows
    sop = next(r for r in rows if r["original"] == "ops_sop")
    assert sop["module_name"] == "Operations Command Center"
    assert {r["original"] for r in rows} >= {"ops_sop", "ops_weekly_note",
                                             "ops_quarterly_review", "proposal"}
    patch(api, ff, f"/api/document-templates/{sop['id']}/", {"body": "Ours now"})
    restored = post(api, ff, f"/api/document-templates/{sop['id']}/restore/").json()
    assert restored["body"] == operations.DOCUMENTS["ops_sop"][2]
    word = api.as_(ff).get(f"/api/document-templates/{sop['id']}/docx/")
    assert word.status_code == 200 and word.content[:2] == b"PK"
    # Another practice without the module has none of them.
    other = _member(tenant_b, "FF")
    api.as_(other).get("/api/document-templates/")
    assert not DocumentTemplate.all_objects.filter(tenant=tenant_b,
                                                   original__startswith="ops_").exists()


@pytest.mark.django_db
def test_module_email_template_arrives_marked(on, ff, api):
    rows = api.as_(ff).get("/api/email-templates/").json()
    rows = rows.get("results", rows) if isinstance(rows, dict) else rows
    mine = [r for r in rows if r["original"] == "ops_weekly_note_email"]
    assert mine and mine[0]["module_name"] == "Operations Command Center"


# ======================================================= the KPI library

@pytest.mark.django_db
def test_the_library_has_four_pages_and_the_module_adds_on_top(seeded_tenant, ff, api):
    base = api.as_(ff).get("/api/scorecard/library/").json()
    assert [p["label"] for p in base["pages"]] == ["Customers", "Operations", "Team", "Money"]
    names = {e["name"] for e in base["entries"]}
    assert {"Customer rating", "Net promoter score", "Safety incidents", "Time to fill",
            "Revenue per employee"} <= names
    assert not any(e["source"] == "center" for e in base["entries"])
    turn_on(api, ff)
    on = api.as_(ff).get("/api/scorecard/library/").json()["entries"]
    module = [e for e in on if e["source"] == "center"]
    assert {e["name"] for e in module} == {k["name"] for k in operations.KPIS}
    assert all(e["guidance"] and e["feeds"] for e in on)


@pytest.mark.django_db
def test_from_the_library_fills_a_kpi_that_saves_and_touches_no_other(seeded_tenant, ff, api):
    from apps.scorecard.models import Kpi

    company = ClientCompanyFactory(tenant=seeded_tenant)
    post(api, ff, "/api/scorecard/kpis/", {"company": str(company.pk), "name": "Existing"})
    existing = Kpi.all_objects.get(name="Existing")
    before = (existing.kind, existing.target_value, existing.updated_at)
    entry = next(e for e in api.as_(ff).get("/api/scorecard/library/").json()["entries"]
                 if e["key"] == "days_to_close_wo")
    fields = library.kpi_fields(entry)
    made = post(api, ff, "/api/scorecard/kpis/", {"company": str(company.pk), **fields})
    assert made.status_code == 201, made.content
    kpi = Kpi.all_objects.get(pk=made.json()["id"])
    assert (kpi.kind, kpi.direction, kpi.duration_unit) == ("duration", "lower", "days")
    assert kpi.note == entry["guidance"]
    existing.refresh_from_db()
    assert (existing.kind, existing.target_value, existing.updated_at) == before


@pytest.mark.django_db
def test_a_practice_adds_its_own_and_edits_a_shipped_one_for_itself(seeded_tenant, ff, va,
                                                                   api, tenant_b):
    made = post(api, ff, "/api/scorecard/library/",
                {"name": "Trucks on the road", "page": "operations", "kind": "count"})
    assert made.status_code == 201
    edited = post(api, ff, "/api/scorecard/library/",
                  {"source_key": "nps", "guidance": "On track at 60 or more."})
    entries = edited.json()["entries"]
    nps = [e for e in entries if e["key"] == "nps"]
    assert len(nps) == 1 and nps[0]["source"] == "practice"
    assert nps[0]["guidance"] == "On track at 60 or more."
    assert any(e["name"] == "Trucks on the road" for e in entries)
    # Assistants read the library but don't keep it.
    assert post(api, va, "/api/scorecard/library/", {"name": "x"}).status_code == 403
    # Another practice sees the shipped entry as it ships.
    other = _member(tenant_b, "FF")
    theirs = api.as_(other).get("/api/scorecard/library/").json()["entries"]
    assert next(e for e in theirs if e["key"] == "nps")["source"] == "base"
    assert not any(e["name"] == "Trucks on the road" for e in theirs)


# ======================================================= playbooks

def test_every_shipped_playbook_reads_and_is_a_draft():
    for key, (name, description, outline) in operations.PLAYBOOKS.items():
        parsed = playbooks.parse(outline)
        assert parsed.projects and parsed.task_count >= 5, key
    reset = playbooks.parse(operations.PLAYBOOKS["ops_90_day_reset"][2])
    assert [(p.title, p.first_week, p.last_week) for p in reset.projects] == [
        ("Discovery", 1, 2), ("Cadence", 3, 4), ("Fix the top two bottlenecks", 5, 8),
        ("Handover", 9, 12)]


def test_a_bad_outline_names_its_line():
    with pytest.raises(playbooks.PlaybookError, match="Line 3"):
        playbooks.parse("Goal: x\n## P | week 1\n- t | week 1 | the boss\n")
    with pytest.raises(playbooks.PlaybookError, match="Goal"):
        playbooks.parse("## P | week 1\n")


@pytest.mark.django_db
def test_start_a_playbook_makes_a_dated_goal_projects_and_tasks(on, ff, api):
    from apps.crm.models import Task
    from apps.work.models import Goal, Project, TaskUpdate

    company = ClientCompanyFactory(tenant=on)
    owner = ContactFactory(tenant=on, company=company, first_name="Dana")
    second = ContactFactory(tenant=on, company=company, first_name="Lee")
    copy = post(api, ff, "/api/playbooks/copy/", {"key": "ops_90_day_reset"}).json()
    start = date(2026, 11, 16)  # a Monday
    body = {"playbook": copy["id"], "company": str(company.pk), "start_date": start.isoformat(),
            "owner_contact": str(owner.pk), "second_contact": str(second.pk)}
    draft = post(api, ff, "/api/playbooks/start/", body)
    assert draft.status_code == 409 and "draft" in draft.json()["detail"]
    patch(api, ff, f"/api/playbooks/{copy['id']}/", {"ready": True})
    made = post(api, ff, "/api/playbooks/start/", body)
    assert made.status_code == 201, made.content
    goal = Goal.all_objects.get(pk=made.json()["goal"])
    assert goal.title == "The 90-day operations reset" and goal.client_company_id == company.pk
    assert goal.target_date == start + timedelta(weeks=11, days=4)
    projects = list(Project.all_objects.filter(goal=goal).order_by("start_date"))
    assert [p.title for p in projects][0] == "Discovery"
    assert projects[2].start_date == start + timedelta(weeks=4)
    assert projects[2].target_date == start + timedelta(weeks=7, days=4)
    tasks = Task.all_objects.filter(project__goal=goal)
    assert tasks.count() == made.json()["tasks"] == 22
    first = tasks.get(title="Interview the owner")
    assert first.due_date == date(2026, 11, 20) and first.owner_id == ff.user_id
    assert tasks.get(title="Set next quarter's priorities").client_owner_contact_id == owner.pk
    assert tasks.filter(client_owner_contact=second).exists()
    assert TaskUpdate.all_objects.filter(task__in=tasks,
                                         source=TaskUpdate.Source.PLAYBOOK).count() == 22
    assert PlaybookRun.all_objects.get(goal=goal).made == {"projects": 4, "tasks": 22}


@pytest.mark.django_db
def test_playbooks_are_only_offered_with_the_module_on(seeded_tenant, ff, va, api):
    assert api.as_(ff).get("/api/playbooks/").json()["playbooks"] == []
    refused = post(api, ff, "/api/playbooks/copy/", {"key": "ops_sop_sprint"})
    assert refused.status_code == 403
    turn_on(api, ff)
    keys = {p["key"] for p in api.as_(ff).get("/api/playbooks/").json()["playbooks"]}
    assert keys == set(operations.PLAYBOOKS)
    assert post(api, va, "/api/playbooks/copy/", {"key": "ops_sop_sprint"}).status_code == 403


# ======================================================= AI actions

@pytest.mark.django_db
def test_the_modules_ai_actions_show_only_when_on_and_run_in_the_ai_app(seeded_tenant, ff, api):
    def keys():
        return {row["key"]: row for row in ai_actions.table(seeded_tenant.pk)}

    assert not set(operations.AI_ACTIONS) & set(keys())
    turn_on(api, ff)
    rows = keys()
    for key in operations.AI_ACTIONS:
        assert rows[key]["runs_in"] == "ai_app" and rows[key]["fixed"] is True
    assert {rows[k]["tier"] for k in operations.AI_ACTIONS} == {"standard", "deep"}
    assert rows["ops_map_rows_from_meeting"]["tier"] == "deep"


# ======================================================= the practice library

@pytest.mark.django_db
def test_nothing_is_recorded_without_a_command_center(seeded_tenant):
    with tenant_context(seeded_tenant.pk):
        NoteFactory(tenant=seeded_tenant, body="Before any module.")
    assert not LibraryRecord.all_objects.exists()


@pytest.mark.django_db
def test_the_library_records_and_the_owner_exports_and_deletes(on, ff, va, api):
    with tenant_context(on.pk):
        note = NoteFactory(tenant=on, title="Scrap", body="Counted by hand at the press.")
        locked = NoteFactory(tenant=on, body="Private", pin_hash="x", pin_set_at=timezone.now())
    kinds = set(LibraryRecord.all_objects.filter(tenant=on).values_list("source_id", flat=True))
    assert note.pk in kinds and locked.pk not in kinds
    # Locked later, it leaves the library.
    with tenant_context(on.pk):
        note.pin_hash, note.pin_set_at = "y", timezone.now()
        note.save()
    assert not LibraryRecord.all_objects.filter(source_id=note.pk).exists()
    with tenant_context(on.pk):
        kept = NoteFactory(tenant=on, title="Kept", body="Weekly meeting moved to Tuesday.")
    assert api.as_(ff).get(ROOT).json()["library_count"] == 1
    export = api.as_(ff).get(f"{ROOT}library/export/")
    assert export.status_code == 200 and "attachment" in export["Content-Disposition"]
    assert json.loads(export.content)["records"][0]["source_id"] == str(kept.pk)
    assert api.as_(va).get(f"{ROOT}library/export/").status_code == 404
    gone = api.as_(ff).delete(f"{ROOT}library/")
    assert gone.status_code == 200 and gone.json()["library_count"] == 0


@pytest.mark.django_db
def test_map_rows_accepted_and_discarded_are_recorded(on, ff):
    from .factories import StrategyMapRowFactory

    with tenant_context(on.pk):
        row = StrategyMapRowFactory(tenant=on, bottleneck="Quotes take a week",
                                    state="accepted")
        other = StrategyMapRowFactory(tenant=on, bottleneck="No SOPs", state="discarded")
        pending = StrategyMapRowFactory(tenant=on, bottleneck="Maybe", state="proposed")
    kinds = dict(LibraryRecord.all_objects.values_list("source_id", "kind"))
    assert kinds[row.pk] == "map_row_accepted" and kinds[other.pk] == "map_row_rejected"
    assert pending.pk not in kinds


@pytest.mark.django_db
def test_a_practice_library_never_holds_another_practices_records(on, tenant_b):
    with tenant_context(tenant_b.pk):
        NoteFactory(tenant=tenant_b, body="Theirs.")
    assert not LibraryRecord.all_objects.filter(tenant=tenant_b).exists()
    assert not LibraryRecord.all_objects.filter(tenant=on).exists()


@pytest.mark.django_db
def test_the_me_endpoint_names_the_centers_and_their_feeds(on, ff, va, fcc, api):
    me = api.as_(ff).get("/api/me").json()
    assert me["command_centers"] == ["operations"]
    assert me["recommended_feeds"] == ["sheet", "track", "besty", "hubspot", "reviews"]
    assert api.as_(fcc).get("/api/me").json()["command_centers"] == []
    TenantFactory()  # another practice changes nothing here
    assert api.as_(va).get("/api/me").json()["command_centers"] == ["operations"]
