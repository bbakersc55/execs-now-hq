"""The employee records (2026-11-17, `docs/p9_people_hris.md`, "Built: the
employee records"): every permission level against every sensitive field,
the record and its rules, the directory (org chart, headcount, anniversaries
and birthdays, client users), hiring through a real signature, onboarding and
offboarding as tasks in Work, the access list and its revoke tasks, exports
and the log, the portal, and AI apps still seeing nothing. Part 1's gates
(two-factor, the re-check, 404 for no access) hold throughout: every People
screen here goes through them.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from apps.crm.models import ContactPipelinePosition, OutboxMessage, Task
from apps.esign.models import Document
from apps.people import access as A
from apps.people import checklists, services
from apps.people.models import (
    AccessEntry, Checklist, ChecklistItem, HRGrant, PeopleAccessLog, PersonDocument,
    PersonRecord, TemplateItem,
)
from apps.tenancy.context import tenant_context

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import ClientAssignmentFactory, ClientCompanyFactory, ClientTeamMemberFactory
from .test_people_security import clock, people_on, post, ready  # noqa: F401  (clock: fixture)

ONBOARDING_ITEMS = 13
#: field -> the value each person's record holds, as it would show.
VALUES = {"pay_rate": "31.75", "pay_unit": "hour", "pay_effective_on": "2026-01-01",
          "home_address": "12 Canyon Road, Ogden", "date_of_birth": "1990-12-05",
          "personal_phone": "801-555-0199", "personal_email": "@home.invalid",
          "emergency_contact": "A sibling, 801-555-0111", "documents": "Annual review 2026"}


def url(company, rest=""):
    return f"/api/people/{company.pk}/{rest}"


def patch(client, path, body):
    return client.patch(path, data=json.dumps(body), content_type="application/json")


@pytest.fixture
def shop(seeded_tenant, ff, cf, va):
    """People on; Acme with its owner, a senior leader, a manager (Marvin)
    with two reports (Daffy, who signs in, and Elmer, who doesn't), someone
    with no record; Globex beside it. Every record full, with a document."""
    people_on(seeded_tenant, ff)
    t = seeded_tenant
    company = ClientCompanyFactory(tenant=t, name="Acme Fasteners")
    other = ClientCompanyFactory(tenant=t, name="Globex")
    ClientAssignmentFactory(tenant=t, user=cf.user, company=company)
    owner = _member(t, "FCC", company=company)
    leader = ClientTeamMemberFactory(tenant=t, level="leader",
                                     membership=_member(t, "ECC", company=company)).membership
    manager = _member(t, "ECC", company=company)
    employee = _member(t, "ECC", company=company)
    nobody = _member(t, "ECC", company=company)

    def person(first, last, *, user=None, boss=None, at=company, title="Machinist"):
        record = PersonRecord(
            tenant=t, client_company=at, first_name=first, last_name=last, title=title,
            department="Production", team="Floor", work_email=f"{first.lower()}@acme.invalid",
            work_phone="801-555-0100", user=user, manager=boss, employment_type="full_time",
            work_state="UT", start_date=date(2021, 12, 1), status="active",
            is_placeholder=False)
        services.write_sensitive(record, {**{k: v for k, v in VALUES.items()
                                             if k != "documents"},
                                          "personal_email": f"{first.lower()}@home.invalid"})
        record.save()
        PersonDocument.all_objects.create(tenant=t, person=record, kind="review",
                                          title="Annual review 2026")
        return record

    marvin = person("Marvin", "Martian", user=manager.user, title="Shop lead")
    daffy = person("Daffy", "Duck", user=employee.user, boss=marvin)
    elmer = person("Elmer", "Fudd", boss=marvin)
    hank = person("Hank", "Hill", at=other)
    return SimpleNamespace(t=t, company=company, other=other, owner=owner, leader=leader,
                           manager=manager, employee=employee, nobody=nobody, marvin=marvin,
                           daffy=daffy, elmer=elmer, hank=hank, ff=ff, cf=cf, va=va)


def grant(shop, member, level, company=None):
    HRGrant.all_objects.create(tenant=shop.t, user=member.user, level=level,
                               client_company=company or shop.company, granted_by=shop.ff.user)


def client_for(api, shop, level, clock):  # noqa: F811
    """(client, the record they open, whether it is their own) for a level."""
    if level == "practice owner":
        return ready(api, shop.ff, clock)[0], shop.daffy
    if level == "client owner":
        return ready(api, shop.owner, clock)[0], shop.daffy
    if level == "HR Director grant":
        grant(shop, shop.cf, "director")
        return ready(api, shop.cf, clock)[0], shop.daffy
    if level == "HR Generalist grant":
        grant(shop, shop.cf, "generalist")
        return ready(api, shop.cf, clock)[0], shop.daffy
    if level == "senior leadership":
        return api.as_(shop.leader), shop.daffy
    if level == "manager, a report":
        return api.as_(shop.manager), shop.daffy
    if level == "manager, own record":
        return api.as_(shop.manager), shop.marvin
    if level == "employee, own record":
        return api.as_(shop.employee), shop.daffy
    if level == "employee, someone else":
        return api.as_(shop.employee), shop.marvin
    if level == "client user with no record":
        return api.as_(shop.nobody), shop.daffy
    if level == "assistant":
        return api.as_(shop.va), shop.daffy
    if level == "associate with no HR permission":
        return api.as_(shop.cf), shop.daffy
    raise AssertionError(level)


# level -> "full", "masked", "none" (directory only) or 404.
LEVELS = {
    "practice owner": "full", "client owner": "full", "HR Director grant": "full",
    "HR Generalist grant": "masked", "senior leadership": "none",
    "manager, a report": "none", "manager, own record": "full",
    "employee, own record": "full", "employee, someone else": 404,
    "client user with no record": 404, "assistant": 404,
    "associate with no HR permission": 404,
}


# ============================================== every level, every sensitive field

@pytest.mark.django_db
@pytest.mark.parametrize("level", list(LEVELS))
def test_every_permission_level_against_every_sensitive_field(level, api, shop, clock):
    client, record = client_for(api, shop, level, clock)
    expected = LEVELS[level]
    page = client.get(url(shop.company, f"records/{record.pk}/"))
    if expected == 404:
        assert page.status_code == 404
        return
    assert page.status_code == 200, page.content
    text = json.dumps(page.json())
    body = page.json()
    for field, value in VALUES.items():
        if field == "personal_email":
            value = f"{record.first_name.lower()}@home.invalid"
        shown = value in text
        if expected == "full":
            assert shown, f"{level}: {field} should be shown"
        else:
            assert not shown, f"{level}: {field} should not be shown"
    if expected == "masked":
        assert body["masked"] is True
        assert body["sensitive"]["pay_rate"] == A.MASK and body["documents"] == "1 document"
    if expected == "none":
        assert "employment" not in body and "sensitive" not in body
    # The directory is everyone's who reaches them; the log has only full views.
    assert body["name"] == record.name and body["work_email"] == record.work_email
    with tenant_context(shop.t.pk):
        logged = PeopleAccessLog.objects.filter(person=record, action="view").exists()
    assert logged == (expected == "full")


@pytest.mark.django_db
def test_the_directory_never_carries_a_sensitive_field_at_any_level(api, shop, clock):
    owner, _ = ready(api, shop.ff, clock)
    page = owner.get(url(shop.company)).json()
    text = json.dumps(page)
    for value in ("31.75", "Ogden", "1990-12-05", "801-555-0199", "home.invalid", "A sibling"):
        assert value not in text
    with tenant_context(shop.t.pk):
        assert not PeopleAccessLog.objects.exists()


# ============================================================== the record

@pytest.mark.django_db
def test_a_director_adds_a_full_record_and_its_rules_hold(api, shop, clock):
    owner, _ = ready(api, shop.ff, clock)
    made = post(owner, url(shop.company, "records/"), {
        "first_name": "Wile", "last_name": "Coyote", "title": "Engineer", "department": "R&D",
        "team": "Lab", "work_email": "wile@acme.invalid", "work_phone": "801-555-0123",
        "manager": str(shop.marvin.pk), "employment_type": "contractor", "work_state": "ut",
        "start_date": "2026-12-01", "member": None,
        "sensitive": {"pay_rate": "85,000", "pay_unit": "year", "pay_effective_on": "2026-12-01",
                      "home_address": "1 Mesa Way", "date_of_birth": "1985-04-02",
                      "personal_phone": "801-555-0124", "personal_email": "wile@home.invalid",
                      "emergency_contact": "Road Runner"}})
    assert made.status_code == 201, made.content
    row = made.json()
    assert row["employment"]["work_state"] == "UT"
    assert row["employment"]["employment_type_label"] == "Contractor"
    assert row["sensitive"]["pay_unit"] == "year" and row["held_in_payroll"].startswith(
        "Social Security number")
    wile = row["id"]
    for bad, why in ((
            {"work_state": "ZZ"}, "two letters"), ({"employment_type": "intern"}, "full-time"),
            ({"start_date": "next week"}, "date"), ({"sensitive": {"pay_unit": "day"}}, "hour"),
            ({"manager": wile}, "own manager"), ({"status": "ended"}, "checklists")):
        refused = patch(owner, url(shop.company, f"records/{wile}/"), bad)
        assert refused.status_code == 400 and why in refused.json()["detail"], bad
    # Marvin can't report to his own report: a loop.
    assert "loop" in patch(owner, url(shop.company, f"records/{shop.marvin.pk}/"),
                           {"manager": str(shop.daffy.pk)}).json()["detail"]
    # Active and on leave, back and forth, by hand.
    assert patch(owner, url(shop.company, f"records/{wile}/"),
                 {"status": "on_leave"}).json()["employment"]["status"] == "on_leave"
    # No field for anything never stored: none in the model, none by a custom field.
    names = {f.name for f in PersonRecord._meta.get_fields()}
    assert not {n for n in names if any(w in n for w in ("ssn", "social", "bank", "i9",
                                                         "medical", "benefit", "background"))}
    for label in ("SSN", "Social Security number", "Bank account", "Routing number", "I-9 copy",
                  "Medical notes", "Benefits plan", "Background check result", "FMLA leave"):
        refused = post(owner, url(shop.company, "setup/fields/"), {"target": "record",
                                                                   "label": label})
        assert refused.status_code == 400 and "held in payroll" in refused.json()["detail"]


@pytest.mark.django_db
def test_custom_fields_are_the_companys_own_and_reorder(api, shop, clock):
    owner, _ = ready(api, shop.ff, clock)
    for label in ("Shirt size", "Locker", "Parking spot"):
        assert post(owner, url(shop.company, "setup/fields/"),
                    {"target": "record", "label": label}).status_code == 200
    setup = owner.get(url(shop.company, "setup/")).json()
    ids = [f["id"] for f in setup["fields"]["record"]]
    order = list(reversed(ids))
    after = post(owner, url(shop.company, "setup/fields/reorder/"),
                 {"target": "record", "ids": order}).json()
    assert [f["label"] for f in after["fields"]["record"]] == ["Parking spot", "Locker",
                                                               "Shirt size"]
    assert patch(owner, url(shop.company, f"records/{shop.daffy.pk}/"),
                 {"custom": {ids[0]: "Large"}}).status_code == 200
    page = owner.get(url(shop.company, f"records/{shop.daffy.pk}/")).json()
    assert {c["label"]: c["value"] for c in page["custom"]}["Shirt size"] == "Large"
    # Globex has none of Acme's.
    assert owner.get(url(shop.other, "setup/")).json()["fields"]["record"] == []
    assert patch(owner, url(shop.other, f"records/{shop.hank.pk}/"),
                 {"custom": {ids[0]: "Small"}}).status_code == 400


# ============================================================== the directory

@pytest.mark.django_db
def test_the_people_page_has_the_chart_headcount_and_client_users(api, shop, clock):
    owner, _ = ready(api, shop.ff, clock)
    page = owner.get(url(shop.company)).json()
    assert {r["name"] for r in page["records"]} == {"Marvin Martian", "Daffy Duck",
                                                    "Elmer Fudd"}
    assert {h["status"]: h["count"] for h in page["headcount"]}["active"] == 3
    chart = page["chart"]
    assert chart["svg"].startswith("<svg") and "Marvin Martian" in chart["svg"]
    assert chart["label"].startswith("Org chart: 3 people")
    # Five sign-ins at Acme, and Elmer without one: six client users, one block.
    users = page["client_users"]
    assert (users["sign_ins"], users["records_without_sign_in"], users["total"],
            users["blocks"], users["cents"]) == (5, 1, 6, 1, 1000)
    # The client owner sees the chart, not the count (the practice's business).
    client_owner, _ = ready(api, shop.owner, clock)
    theirs = client_owner.get(url(shop.company)).json()
    assert theirs["chart"]["svg"] and theirs["client_users"] is None


@pytest.mark.django_db
def test_anniversaries_and_birthdays_show_day_and_month_only(shop):
    with tenant_context(shop.t.pk):
        found = services.upcoming(PersonRecord.objects.filter(client_company=shop.company),
                                  today=date(2026, 11, 20))
    assert [a["years"] for a in found["anniversaries"]] == [5, 5, 5]
    assert found["anniversaries"][0]["on"] == "2026-12-01"
    assert found["birthdays"][0] == {"id": found["birthdays"][0]["id"],
                                     "name": found["birthdays"][0]["name"],
                                     "day": "December 5"}
    assert "1990" not in json.dumps(found["birthdays"])


@pytest.mark.django_db
def test_a_manager_sees_their_reports_directory_and_checklist_progress(api, shop, clock):
    with tenant_context(shop.t.pk):
        checklists.start(shop.elmer, "offboarding", actor=shop.ff.user,
                         anchor_date=date(2026, 12, 15), reason="resignation")
    page = api.as_(shop.manager).get(url(shop.company)).json()
    assert page["level"] == "reports" and page["chart"] is None and page["headcount"] is None
    rows = {r["first_name"]: r for r in page["records"]}
    assert set(rows) == {"Marvin", "Daffy", "Elmer"}
    assert rows["Elmer"]["progress"][0]["kind"] == "offboarding"
    assert rows["Elmer"]["progress"][0]["total"] == 9
    assert "status" not in rows["Elmer"] and "31.75" not in json.dumps(page)


# ============================================================== hiring

def _offer(api, shop, clock):  # noqa: F811
    owner, _ = ready(api, shop.ff, clock)
    made = post(owner, url(shop.company, "records/"), {
        "first_name": "Wile", "last_name": "Coyote", "title": "Engineer",
        "manager": str(shop.marvin.pk), "employment_type": "full_time", "work_state": "UT",
        "start_date": "2026-12-01", "offer": True,
        "sensitive": {"pay_rate": "$85,000", "pay_unit": "year",
                      "personal_email": "wile@home.invalid"}})
    assert made.status_code == 201 and made.json()["employment"]["status"] == "offer_out"
    wile = PersonRecord.all_objects.get(pk=made.json()["id"])
    sent = post(owner, url(shop.company, f"records/{wile.pk}/offer/"), {})
    assert sent.status_code == 201, sent.content
    return owner, wile, Document.all_objects.get(pk=sent.json()["document"])


@pytest.mark.django_db
def test_hiring_through_a_real_signature(api, shop, clock, dev_outbox, client):
    from apps.crm.services import outbox

    owner, wile, document = _offer(api, shop, clock)
    assert document.title == "Offer of employment: Engineer"
    assert document.fields["Pay"] == "$85,000 a year" and document.fields["Manager"] == \
        "Marvin Martian"
    assert document.signer_email == "wile@home.invalid" and wile.status == "offer_out"
    # It waits in the Outbox for approval, as every signature request does.
    message = document.request_message
    assert message.state == "pending_approval"
    with tenant_context(shop.t.pk):
        outbox.approve(message, actor=shop.ff.user, role="FF")
    token = dev_outbox[-1].body.split("/sign/")[1].split()[0].strip()
    # The candidate signs, signed out, from the emailed link.
    signed = client.post(f"/api/sign/{token}", json.dumps(
        {"agreed": True, "method": "typed", "typed": "Wile E. Coyote"}),
        content_type="application/json")
    assert signed.status_code == 200, signed.content
    wile.refresh_from_db()
    assert wile.status == "onboarding"
    onboarding = Checklist.all_objects.get(person=wile, kind="onboarding")
    assert onboarding.anchor_date == date(2026, 12, 1)
    assert ChecklistItem.all_objects.filter(checklist=onboarding).count() == ONBOARDING_ITEMS
    # Moved nobody on a pipeline, though signing moves a client to Closed Won.
    assert not ContactPipelinePosition.all_objects.filter(contact=document.signer).exists()
    # Countersigning works as it does today.
    counter = post(owner, f"/api/documents/{document.pk}/countersign/",
                   {"agreed": True, "method": "typed", "typed": "Bryan Baker"})
    assert counter.status_code == 200, counter.content
    document.refresh_from_db()
    assert document.state == "complete"
    page = owner.get(url(shop.company, f"records/{wile.pk}/")).json()
    [letter] = page["documents"]
    assert letter["kind"] == "offer_letter" and letter["signature"]["state"] == "complete"
    pdf = owner.get(url(shop.company, f"documents/{letter['id']}/"))
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    with tenant_context(shop.t.pk):
        actions = set(PeopleAccessLog.objects.filter(person=wile).values_list("action",
                                                                             flat=True))
    assert {"export", "view"} <= actions          # the pay into the letter; the opening


@pytest.mark.django_db
def test_an_offer_and_its_candidate_reach_only_hr_directors(api, shop, clock, dev_outbox):
    owner, wile, document = _offer(api, shop, clock)
    # In Documents for the practice owner; not for an associate with Acme and
    # no HR permission, nor an assistant.
    assert str(document.pk) in owner.get("/api/documents/").content.decode()
    for member in (shop.cf, shop.va):
        assert str(document.pk) not in api.as_(member).get("/api/documents/").content.decode()
    # Its request waits in the Sending queue for the practice owner only.
    assert "Coyote" in owner.get("/api/sending-queue/").content.decode()
    for member in (shop.cf, shop.va):
        assert "Coyote" not in api.as_(member).get("/api/sending-queue/").content.decode()
    # Never the candidate's contact in Contacts or search.
    contacts = owner.get("/api/contacts/?search=Coyote").content.decode()
    assert "Coyote" not in contacts
    assert "Coyote" not in owner.get("/api/search/?q=Coyote").content.decode()
    # Only an HR Director sends an offer: it carries pay.
    grant(shop, shop.cf, "generalist")
    generalist, _ = ready(api, shop.cf, clock)
    assert post(generalist, url(shop.company, f"records/{wile.pk}/offer/"),
                {}).status_code == 403
    # A second offer while one is out is refused.
    again = post(owner, url(shop.company, f"records/{wile.pk}/offer/"), {})
    assert again.status_code == 409 and "already out" in again.json()["detail"]


# ============================================================== checklists

@pytest.mark.django_db
def test_onboarding_items_become_tasks_with_owners_and_due_dates(api, shop, clock):
    owner, _ = ready(api, shop.ff, clock)
    started = post(owner, url(shop.company, f"records/{shop.elmer.pk}/checklists/"), {
        "kind": "onboarding", "anchor_date": "2026-12-01", "it_owner": str(shop.cf.user_id)})
    assert started.status_code == 201, started.content
    body = started.json()
    assert body["total"] == ONBOARDING_ITEMS and body["owners"]["it"]
    with tenant_context(shop.t.pk):
        items = list(ChecklistItem.objects.filter(checklist_id=body["id"]).select_related(
            "task"))
        standard = {t.title: t for t in TemplateItem.objects.filter(
            client_company=shop.company, kind="onboarding")}
    assert len(items) == ONBOARDING_ITEMS
    for item in items:
        task = item.task
        assert task is not None and task.due_date == item.due_date
        assert task.due_date == date(2026, 12, 1) + timedelta(days=standard[item.title].due_days)
        assert task.client_company_id == shop.company.pk and not task.is_client_visible
        assert task.title.startswith("Onboarding: Elmer Fudd · ")
        expected = {"it": shop.cf.user_id, "manager": shop.manager.user_id}.get(
            item.section, shop.ff.user_id)
        assert task.assignee_id == expected, item.title
    # Done in Work is done here.
    one = next(i for i in items if i.section == "people")
    done = patch(owner, f"/api/tasks/{one.task_id}/", {"status": "done"})
    assert done.status_code == 200, done.content
    page = owner.get(url(shop.company, f"records/{shop.elmer.pk}/")).json()
    row = next(i for i in page["checklists"][0]["items"] if i["id"] == str(one.pk))
    assert row["done"] is True
    # A waiver needs a note; then its task is cancelled.
    other = next(i for i in items if i.section == "manager")
    refused = post(owner, url(shop.company, f"items/{other.pk}/waive/"), {"note": " "})
    assert refused.status_code == 400 and "note" in refused.json()["detail"]
    assert post(owner, url(shop.company, f"items/{other.pk}/waive/"),
                {"note": "Elmer knows the floor already"}).json()["waived"] is True
    other.task.refresh_from_db()
    assert other.task.status == Task.Status.CANCELLED
    # It closes only when every item is done or waived, then they are active.
    closed = post(owner, url(shop.company, f"checklists/{body['id']}/close/"))
    assert closed.status_code == 409 and "still open" in closed.json()["detail"]
    for item in items:
        if item.pk not in (one.pk, other.pk):
            assert post(owner, url(shop.company, f"items/{item.pk}/done/")).status_code == 200
    assert post(owner, url(shop.company, f"checklists/{body['id']}/close/")).status_code == 200
    shop.elmer.refresh_from_db()
    assert shop.elmer.status == "active"


@pytest.mark.django_db
def test_checklist_tasks_reach_only_their_owner_and_hr_in_work(api, shop, clock):
    with tenant_context(shop.t.pk):
        checklist = checklists.start(shop.elmer, "onboarding", actor=shop.ff.user,
                                     anchor_date=date(2026, 12, 1),
                                     it_owner=str(shop.cf.user_id))
        task_ids = {str(i.task_id) for i in checklist.items.all()}
        it_ids = {str(i.task_id) for i in checklist.items.filter(section="it")}
        assert len(task_ids) == ONBOARDING_ITEMS

    def seen(member):
        rows = api.as_(member).get("/api/tasks/?page_size=500").json()
        rows = rows.get("results", rows) if isinstance(rows, dict) else rows
        return {r["id"] for r in rows} & task_ids

    assert seen(shop.ff) == task_ids
    assert seen(shop.cf) == it_ids               # the IT items are theirs
    assert seen(shop.va) == set()                 # an assistant without HR: none
    assert seen(shop.manager) == set()            # the practice's tasks, not the portal's
    grant(shop, shop.va, "generalist")
    assert seen(shop.va) == task_ids              # HR for Acme: all of Acme's


@pytest.mark.django_db
def test_offboarding_builds_a_revoke_task_for_every_access_entry(api, shop, clock):
    owner, _ = ready(api, shop.ff, clock)
    given = []
    for kind, name in (("system", "Slack"), ("email", "daffy@acme.invalid"),
                       ("equipment", "Laptop SN 4471"), ("key", "Front door key")):
        made = post(owner, url(shop.company, f"records/{shop.daffy.pk}/access/"),
                    {"kind": kind, "name": name, "given_on": "2025-01-06",
                     "given_by_name": "Acme IT"})
        assert made.status_code == 201, made.content
        given.append(made.json())
    assert given[0]["given_by"] == "Acme IT" and given[0]["given_on"] == "2025-01-06"
    started = post(owner, url(shop.company, f"records/{shop.daffy.pk}/checklists/"),
                   {"kind": "offboarding", "anchor_date": "2026-12-15"})
    assert started.status_code == 400 and "why" in started.json()["detail"]
    started = post(owner, url(shop.company, f"records/{shop.daffy.pk}/checklists/"),
                   {"kind": "offboarding", "anchor_date": "2026-12-15",
                    "reason": "resignation"})
    assert started.status_code == 201, started.content
    off = started.json()
    assert off["no_payroll"].startswith("This doesn't end anyone in payroll")
    revoke = [i for i in off["items"] if i["revokes"]]
    assert sorted(i["title"] for i in revoke) == [
        "Revoke email account: daffy@acme.invalid", "Revoke equipment: Laptop SN 4471",
        "Revoke key: Front door key", "Revoke system: Slack"]
    assert {i["due_date"] for i in revoke} == {"2026-12-15"}
    # One given while it is open gets its revoke task too.
    added = post(owner, url(shop.company, f"records/{shop.daffy.pk}/access/"),
                 {"kind": "phone", "name": "801-555-0177"})
    assert added.status_code == 201
    page = owner.get(url(shop.company, f"records/{shop.daffy.pk}/")).json()
    off = next(c for c in page["checklists"] if c["kind"] == "offboarding")
    revoke = [i for i in off["items"] if i["revokes"]]
    assert len(revoke) == 5 and all(
        ChecklistItem.all_objects.get(pk=i["id"]).task_id for i in revoke)
    # It closes only when each is done, or waived with a note.
    assert post(owner, url(shop.company, f"checklists/{off['id']}/close/")).status_code == 409
    for item in off["items"]:
        if item["title"] == "Revoke key: Front door key":
            assert post(owner, url(shop.company, f"items/{item['id']}/waive/"),
                        {"note": "Locks changed instead"}).status_code == 200
        else:
            assert post(owner, url(shop.company, f"items/{item['id']}/done/")).status_code == 200
    closed = post(owner, url(shop.company, f"checklists/{off['id']}/close/"))
    assert closed.status_code == 200, closed.content
    shop.daffy.refresh_from_db()
    assert shop.daffy.status == "ended" and shop.daffy.ended_on == date(2026, 12, 15)
    with tenant_context(shop.t.pk):
        entries = {e.name: e.revoked_at for e in AccessEntry.objects.filter(person=shop.daffy)}
    assert entries.pop("Front door key") is None and all(entries.values())
    # Nothing was sent to any payroll provider: the app has no such call.
    assert not OutboxMessage.all_objects.filter(subject__icontains="payroll").exists()


@pytest.mark.django_db
def test_each_company_adds_edits_reorders_and_archives_its_items(api, shop, clock):
    owner, _ = ready(api, shop.ff, clock)
    setup = owner.get(url(shop.company, "setup/")).json()
    assert len(setup["items"]["onboarding"]) == ONBOARDING_ITEMS
    added = post(owner, url(shop.company, "setup/items/"), {
        "kind": "onboarding", "section": "it", "title": "Add them to the ERP", "due_days": -1})
    rows = added.json()["items"]["onboarding"]
    new = next(r for r in rows if r["title"] == "Add them to the ERP")
    assert new["owner_role"] == "it" and not new["standard"]
    first = rows[0]
    edited = post(owner, url(shop.company, f"setup/items/{first['id']}/"),
                  {"title": "Send the welcome email", "due_days": -7}).json()
    assert edited["items"]["onboarding"][0]["title"] == "Send the welcome email"
    order = [r["id"] for r in reversed(edited["items"]["onboarding"])]
    reordered = post(owner, url(shop.company, "setup/items/reorder/"),
                     {"kind": "onboarding", "ids": order}).json()
    assert reordered["items"]["onboarding"][0]["title"] == "Add them to the ERP"
    archived = post(owner, url(shop.company, f"setup/items/{new['id']}/"),
                    {"archived": True}).json()
    assert len(archived["items"]["onboarding"]) == ONBOARDING_ITEMS
    # Globex keeps the standard ones; a generalist reads Acme's and changes nothing.
    assert owner.get(url(shop.other, "setup/")).json()["items"]["onboarding"][0]["title"] \
        == "Send the welcome email with first-day details"
    grant(shop, shop.va, "generalist")
    generalist, _ = ready(api, shop.va, clock)
    assert generalist.get(url(shop.company, "setup/")).status_code == 200
    assert post(generalist, url(shop.company, "setup/items/"), {
        "kind": "onboarding", "section": "it", "title": "X"}).status_code == 403
    # A checklist field of the company's own, filled at the start.
    fields = post(owner, url(shop.company, "setup/fields/"),
                  {"target": "onboarding", "label": "Laptop model"}).json()
    field = fields["fields"]["onboarding"][0]["id"]
    started = post(owner, url(shop.company, f"records/{shop.elmer.pk}/checklists/"),
                   {"kind": "onboarding", "custom": {field: "ThinkPad T14"}}).json()
    assert started["custom"] == [{"id": field, "label": "Laptop model",
                                  "value": "ThinkPad T14"}]
    assert started["total"] == ONBOARDING_ITEMS


# ============================================================== exports

@pytest.mark.django_db
def test_exports_hold_sensitive_fields_only_when_a_director_asks_and_all_are_logged(
        api, shop, clock):
    owner, _ = ready(api, shop.ff, clock)
    plain = owner.get(url(shop.company, "export/"))
    assert plain.status_code == 200 and b"Marvin Martian" in plain.content
    assert b"31.75" not in plain.content and b"Ogden" not in plain.content
    full = owner.get(url(shop.company, "export/?sensitive=1"))
    assert b"31.75" in full.content and b"Ogden" in full.content
    grant(shop, shop.cf, "generalist")
    generalist, _ = ready(api, shop.cf, clock)
    assert generalist.get(url(shop.company, "export/?sensitive=1")).status_code == 403
    theirs = generalist.get(url(shop.company, "export/"))
    assert theirs.status_code == 200 and b"31.75" not in theirs.content
    assert api.as_(shop.leader).get(url(shop.company, "export/")).status_code == 403
    with tenant_context(shop.t.pk):
        exports = list(PeopleAccessLog.objects.filter(action="export"))
    # Three exports of three people each, every one logged with what it held.
    assert len(exports) == 9
    plain_rows = [e for e in exports if "pay_rate" not in e.fields]
    assert len(plain_rows) == 6 and all("name" in e.fields for e in plain_rows)
    assert {e.actor_id for e in exports} == {shop.ff.user_id, shop.cf.user_id}


# ============================================================== documents

@pytest.mark.django_db
def test_documents_are_uploaded_by_a_director_and_opened_only_in_full(api, shop, clock):
    from django.core.files.uploadedfile import SimpleUploadedFile

    owner, _ = ready(api, shop.ff, clock)
    pdf = SimpleUploadedFile("review.pdf", b"%PDF-1.4 review", content_type="application/pdf")
    added = owner.post(url(shop.company, f"records/{shop.daffy.pk}/documents/"),
                       {"kind": "review", "title": "Mid-year review", "file": pdf})
    assert added.status_code == 201, added.content
    exe = SimpleUploadedFile("x.exe", b"MZ", content_type="application/x-msdownload")
    refused = owner.post(url(shop.company, f"records/{shop.daffy.pk}/documents/"),
                         {"kind": "other", "title": "x", "file": exe})
    assert refused.status_code == 400
    doc = added.json()["id"]
    got = owner.get(url(shop.company, f"documents/{doc}/"))
    assert got.status_code == 200 and got.content == b"%PDF-1.4 review"
    # Daffy opens their own; the generalist and the manager do not.
    assert api.as_(shop.employee).get(url(shop.company, f"documents/{doc}/")).status_code == 200
    assert api.as_(shop.manager).get(url(shop.company, f"documents/{doc}/")).status_code == 404
    grant(shop, shop.cf, "generalist")
    generalist, _ = ready(api, shop.cf, clock)
    assert generalist.get(url(shop.company, f"documents/{doc}/")).status_code == 404
    assert generalist.post(url(shop.company, f"records/{shop.daffy.pk}/documents/"),
                           {"kind": "review", "title": "x", "file": SimpleUploadedFile(
                               "r.pdf", b"%PDF", content_type="application/pdf")}
                           ).status_code == 403
    with tenant_context(shop.t.pk):
        opened = PeopleAccessLog.objects.filter(person=shop.daffy, fields=["documents"])
        assert opened.filter(action="view").count() == 2
        assert opened.filter(action="change").count() == 1


# ============================================================== the portal

@pytest.mark.django_db
def test_the_employee_sees_their_record_documents_to_sign_and_their_items(api, shop, clock,
                                                                          dev_outbox):
    from apps.crm.services import outbox

    owner, _ = ready(api, shop.ff, clock)
    sent = post(owner, url(shop.company, f"records/{shop.daffy.pk}/handbook/"), {})
    assert sent.status_code == 201, sent.content
    document = Document.all_objects.get(pk=sent.json()["document"])
    with tenant_context(shop.t.pk):
        outbox.approve(document.request_message, actor=shop.ff.user, role="FF")
        checklist = checklists.start(shop.daffy, "onboarding", actor=shop.ff.user,
                                     anchor_date=date(2026, 12, 1))
        mine = checklist.items.get(title="Complete payroll setup with the payroll provider")
        someone_elses = checklist.items.exclude(owner=shop.employee.user).first()
    assert mine.owner_id == shop.employee.user_id
    daffy = api.as_(shop.employee)
    page = daffy.get(url(shop.company)).json()
    assert page["level"] == "self" and [r["name"] for r in page["records"]] == ["Daffy Duck"]
    assert [d["title"] for d in page["to_sign"]] == ["Employee handbook acknowledgment"]
    assert [i["title"] for i in page["my_items"]] == [mine.title]
    # In their portal's Documents, their own; not the practice's others.
    portal = daffy.get("/api/portal-documents/").content.decode()
    assert str(document.pk) in portal
    # They finish their own item; they waive nothing, and touch no one else's.
    assert post(daffy, url(shop.company, f"items/{mine.pk}/done/")).status_code == 200
    assert post(daffy, url(shop.company, f"items/{mine.pk}/waive/"),
                {"note": "x"}).status_code == 403
    assert post(daffy, url(shop.company, f"items/{someone_elses.pk}/done/")).status_code == 404
    # Another employee's portal shows none of Daffy's documents.
    assert str(document.pk) not in api.as_(shop.nobody).get(
        "/api/portal-documents/").content.decode()


# ============================================================== AI apps

@pytest.mark.django_db
def test_ai_apps_still_see_nothing_of_people(api, shop, clock, dev_outbox):
    from apps.aiconnect import tools
    from apps.crm.services import search

    owner, wile, _document = _offer(api, shop, clock)
    with tenant_context(shop.t.pk):
        checklists.start(shop.elmer, "onboarding", actor=shop.ff.user,
                         anchor_date=date(2026, 12, 1))
        checklists.save_entry(shop.daffy, {"kind": "system", "name": "Zendesk-Acme"},
                              actor=shop.ff.user)
        checklists.start(shop.daffy, "offboarding", actor=shop.ff.user,
                         anchor_date=date(2026, 12, 15), reason="layoff")
    markers = ["Marvin", "Martian", "Daffy", "Elmer", "Fudd", "Coyote", "Wile", "Zendesk-Acme",
               "Onboarding:", "Offboarding:", "Revoke", "Offer of employment", "85,000",
               "31.75", "Ogden", "home.invalid", "801-555-01", "Annual review", "handbook"]
    p = tools.Principal(connection=SimpleNamespace(membership=shop.ff, user=shop.ff.user))
    company = str(shop.company.pk)
    seen = []
    with tenant_context(shop.t.pk):
        for tool in tools.READ_TOOLS:
            names = tool.__code__.co_varnames[:tool.__code__.co_argcount]
            args = {n: {"company_id": company, "query": "Coyote"}.get(n)
                    for n in names[1:]}
            try:
                result = tool(p, **{k: v for k, v in args.items() if v is not None})
            except Exception as exc:  # noqa: BLE001 — a refusal says nothing either
                result = str(exc)
            seen.append(json.dumps(result, default=str))
        for term in ("Coyote", "Wile", "Elmer"):
            seen.append(json.dumps(search.search(shop.t, term), default=str))
    text = " ".join(seen)
    for marker in markers:
        assert marker not in text, marker


# ============================================================== isolation and roles

@pytest.mark.django_db
def test_another_practice_reaches_nothing_by_id(api, shop, clock, tenant_b):
    from .factories import ClientCompanyFactory as Companies

    with tenant_context(shop.t.pk):
        checklist = checklists.start(shop.elmer, "onboarding", actor=shop.ff.user,
                                     anchor_date=date(2026, 12, 1))
        item = checklist.items.first()
        entry = checklists.save_entry(shop.elmer, {"kind": "key", "name": "Gate"},
                                      actor=shop.ff.user)
    theirs = _member(tenant_b, "FF")
    company_b = Companies(tenant=tenant_b, name="Initech")
    client = api.as_(theirs)
    for path in (url(shop.company), url(shop.company, f"records/{shop.elmer.pk}/"),
                 url(company_b, f"items/{item.pk}/done/"),
                 url(company_b, f"checklists/{checklist.pk}/close/"),
                 url(company_b, f"access/{entry.pk}/")):
        response = (client.post(path) if path.endswith(("done/", "close/")) else
                    patch(client, path, {"name": "x"}) if "/access/" in path else
                    client.get(path))
        assert response.status_code == 404, path


@pytest.mark.django_db
def test_nobody_without_access_reaches_any_new_route(api, shop, clock):
    with tenant_context(shop.t.pk):
        checklist = checklists.start(shop.elmer, "onboarding", actor=shop.ff.user,
                                     anchor_date=date(2026, 12, 1))
        item = checklist.items.first()
    for member in (shop.nobody, shop.va):
        client = api.as_(member)
        for path, method in ((url(shop.company, "setup/"), "get"),
                             (url(shop.company, f"items/{item.pk}/done/"), "post"),
                             (url(shop.company, f"records/{shop.elmer.pk}/access/"), "post"),
                             (url(shop.company, f"checklists/{checklist.pk}/close/"), "post"),
                             (url(shop.company, "export/"), "get")):
            assert getattr(client, method)(path).status_code == 404, (member, path)
    # Senior leadership reaches the directory, but runs nothing.
    leader = api.as_(shop.leader)
    assert post(leader, url(shop.company, f"items/{item.pk}/done/")).status_code == 404
    assert post(leader, url(shop.company, f"records/{shop.elmer.pk}/checklists/"),
                {"kind": "offboarding"}).status_code == 403


@pytest.mark.django_db
def test_the_foundations_gates_hold_on_every_new_route(api, shop, clock):
    """Two-factor before any People screen for an HR holder, and the code
    again after four hours: on the records' routes as on Part 1's."""
    import time

    from apps.accounts import two_factor as tf

    with tenant_context(shop.t.pk):
        item = checklists.start(shop.elmer, "onboarding", actor=shop.ff.user,
                                anchor_date=date(2026, 12, 1)).items.first()
    routes = [("get", url(shop.company, "setup/")),
              ("get", url(shop.company, f"records/{shop.daffy.pk}/")),
              ("post", url(shop.company, f"records/{shop.daffy.pk}/checklists/")),
              ("post", url(shop.company, f"records/{shop.daffy.pk}/access/")),
              ("post", url(shop.company, f"records/{shop.daffy.pk}/offer/")),
              ("post", url(shop.company, f"items/{item.pk}/done/")),
              ("get", url(shop.company, "export/?sensitive=1"))]
    client = api.as_(shop.ff)
    for method, path in routes:
        refused = getattr(client, method)(path)
        assert refused.status_code == 403 and refused.json()["two_factor"] == "enroll", path
    client, _ = ready(api, shop.ff, clock)
    session = client.session
    session[tf.SESSION_VERIFIED] = time.time() - 4 * 60 * 60 - 60
    session.save()
    for method, path in routes:
        asked = getattr(client, method)(path)
        assert asked.status_code == 403 and asked.json()["two_factor"] == "recheck", path
