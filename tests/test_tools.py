"""P12: the worksheet engine, the four Operations tools and the tool builder
(`docs/p12_tools.md`).

- **The formula language:** arithmetic and precedence, every function, `if`
  taking only its branch, division by zero said in words, bad formulas and
  anything that looks like code refused.
- **Each tool's arithmetic** against numbers worked by hand.
- **Runs keep their snapshot** when the tool is edited.
- **Hand-offs:** a KPI reading "From a tool", tasks from flagged rows, a plan
  proposal, an SOP brainstorm, steps imported from an SOP, the calendar.
- **Practice isolation**, the **portal** (shared runs only, owner and senior
  leadership only), the **builder** with a fake Claude, the **MCP tools**,
  and the **EOS-term** check.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.tools import definition as D
from apps.tools import formula as F
from apps.tools import services, shipped
from apps.tools.models import Tool, ToolRun
from apps.tenancy.context import tenant_context

from .factories import ClientCompanyFactory, MembershipFactory, TenantFactory
from .test_plans import client, get, on  # noqa: F401  (fixtures)
from .test_scorecard import patch, post, sc  # noqa: F401  (the fixture)

RUNS = "/api/tool-runs/"
TOOLS = "/api/tools/"


def ev(text, **env):
    return F.evaluate(F.compile_(text), lambda name: env[name] if name in env else (
        (_ for _ in ()).throw(F.EvalError(f"no {name}"))))


# ------------------------------------------------------------------ the language

def test_arithmetic_precedence_and_functions():
    assert ev("2 + 3 * 4") == 14 and ev("(2 + 3) * 4") == 20 and ev("2 ^ 3 + 1") == 9
    assert ev("-2 * -3") == 6 and ev("10 / 4") == Decimal("2.5")
    assert ev("sum(a, b, 3)", a=Decimal(1), b=None) == 4
    assert ev("average(xs)", xs=[Decimal(2), None, Decimal(4)]) == 3
    assert ev("min(xs)", xs=[Decimal(5), Decimal(2)]) == 2 and ev("max(1, 7, 3)") == 7
    assert ev("count(xs)", xs=["a", "", None, Decimal(0)]) == 2
    assert ev("round(2 / 3, 2)") == Decimal("0.67") and ev("abs(-4)") == 4
    assert ev("sumif(k, \"a\", v)", k=["a", "b", "A"], v=[Decimal(1), Decimal(2), Decimal(3)]) == 4
    assert ev("countif(k, \"yes\")", k=["Yes", "no", "yes"]) == 2
    assert ev("argmax(n, v)", n=["x", "y"], v=[Decimal(1), Decimal(9)]) == "y"
    assert ev("argmin(n, v)", n=["x", "y"], v=[Decimal(1), Decimal(9)]) == "x"
    assert ev("filter(n, f)", n=["x", "y", "z"], f=[Decimal(1), Decimal(0), Decimal(1)]) == ["x", "z"]
    assert ev("if(a = \"No\" or b > 2, 1, 0)", a="no", b=Decimal(1)) == 1
    assert ev("not (1 > 2) and 3 >= 3") == 1


def test_if_takes_only_its_branch_and_division_by_zero_is_said():
    assert ev("if(c > 0, d / c, 0)", c=Decimal(0), d=Decimal(5)) == 0
    with pytest.raises(F.EvalError, match="Can't divide by zero"):
        ev("d / c", c=Decimal(0), d=Decimal(5))
    with pytest.raises(F.EvalError, match="isn't a number"):
        ev("\"x\" + 1")


@pytest.mark.parametrize("text,words", [
    ("2 +", "stops too soon"),
    ("sum(1,", "stops too soon"),
    ("open(\"x\")", "no function called"),
    ("__import__(\"os\")", "no function called"),
    ("steps.__class__", "no field called"),
    ("1 ; 2", "can't read"),
    ("if(1, 2)", "takes 3 values"),
    ("", "empty"),
    ("x" * 501, "at most 500"),
])
def test_bad_formulas_are_refused_in_words(text, words):
    with pytest.raises(F.FormulaError, match=words):
        F.compile_(text)


def test_a_definition_names_only_what_it_has():
    bad = {"sections": [{"title": "S", "fields": [
        {"key": "a", "label": "A", "type": "number"},
        {"key": "b", "label": "B", "type": "computed", "formula": "a * missing"}]}]}
    errors = D.check(bad)
    assert errors and "no field called “missing”" in errors[0]["message"]
    assert errors[0]["where"] == "sections.0.fields.1"
    for tool in shipped.SHIPPED.values():
        assert D.check(tool["definition"]) == [], tool["name"]


def test_an_error_lands_on_the_field_not_the_page():
    definition = {"sections": [{"title": "S", "fields": [
        {"key": "a", "label": "A", "type": "number"},
        {"key": "b", "label": "B", "type": "number"},
        {"key": "ratio", "label": "Ratio", "type": "computed", "formula": "a / b"}]}],
        "results": [{"key": "r", "label": "R", "formula": "ratio * 2"}]}
    out = D.evaluate(definition, {"a": "6", "b": "0"})
    assert out["computed"]["ratio"]["error"] == "Can't divide by zero."
    assert out["computed"]["ratio"]["text"] == "–"
    out = D.evaluate(definition, {"a": "6", "b": "3"})
    assert out["computed"]["ratio"]["value"] == 2 and out["results"][0]["value"] == 4


# ------------------------------------------------------------------ the four tools, by hand

def results(key, values):
    out = D.evaluate(shipped.SHIPPED[key]["definition"], values)
    return {r["key"]: r for r in out["results"]}, out


def test_bottleneck_finder_names_the_constraint_and_the_output():
    # Form: 80 units a week with 10% rework is 88 against 60, a load of 146.7%;
    # its good output is 60 / 1.1 = 54.5 a week, which holds the process there.
    r, out = results("ops_bottleneck", {"steps": [
        {"step": "Cut", "capacity": 100, "demand": 80, "rework": 0, "wait": 4},
        {"step": "Form", "capacity": 60, "demand": 80, "rework": 10, "wait": 8},
        {"step": "Pack", "capacity": 120, "demand": 80, "rework": 0, "wait": 2}]})
    assert r["constraint"]["value"] == "Form"
    assert r["constraint_load"]["text"] == "146.7%"
    assert r["output"]["value"] == pytest.approx(54.5454, abs=1e-3)
    assert r["shortfall"]["value"] == pytest.approx(25.4545, abs=1e-3)
    assert r["waiting"]["text"] == "14 hours"
    assert out["tables"]["steps"][0]["load"]["text"] == "80%"


def test_capacity_model_by_role_with_its_what_ifs():
    # Machinists: 4 × 40 × 75% = 120 hours against 300 parts × 0.5 = 150: 30
    # short, one person. Quality: 32 against 40: 8 short, a quarter of one.
    base = {"roles": [{"role": "Machinists", "people": 4, "hours": 40, "productive": 75,
                       "added": 0},
                      {"role": "Quality", "people": 1, "hours": 40, "productive": 80,
                       "added": 0}],
            "work": [{"item": "Parts", "role": "Machinists", "volume": 300,
                      "hours_per_unit": 0.5},
                     {"item": "Inspections", "role": "quality", "volume": 200,
                      "hours_per_unit": 0.2}]}
    r, out = results("ops_capacity", base)
    assert (r["capacity"]["value"], r["demand"]["value"], r["gap_hours"]["value"]) == (152, 190, 38)
    assert r["gap_people"]["value"] == pytest.approx(1.25)
    assert r["tightest"]["value"] == "Machinists"
    assert out["tables"]["roles"][0]["gap"]["text"] == "30 hours"
    # What if demand falls 10%: 135 and 36 against 120 and 32.
    r, _ = results("ops_capacity", {**base, "demand_change": -10})
    assert r["demand"]["value"] == 171 and r["gap_people"]["value"] == pytest.approx(0.625)
    # What if one machinist is hired: 5 × 40 × 75% = 150, no gap there.
    hired = json.loads(json.dumps(base))
    hired["roles"][0]["added"] = 1
    r, out = results("ops_capacity", hired)
    assert out["tables"]["roles"][0]["gap"]["value"] == 0


def test_meeting_cadence_adds_up_agendas_and_hours():
    r, out = results("ops_meetings", {
        "meetings": [{"name": "Weekly leadership meeting", "cadence": "Weekly", "day": "Monday",
                      "time": "09:00", "minutes": 60, "start": "2026-11-09"},
                     {"name": "Monthly review", "cadence": "Monthly", "day": "Thursday",
                      "time": "14:00", "minutes": 90, "start": "2026-11-13"}],
        "agenda": [{"meeting": "Weekly leadership meeting", "section": "Numbers", "minutes": 10},
                   {"meeting": "Weekly leadership meeting", "section": "Issues", "minutes": 30},
                   {"meeting": "Weekly leadership meeting", "section": "Actions", "minutes": 20},
                   {"meeting": "Monthly review", "section": "Results", "minutes": 100}]})
    assert r["count"]["value"] == 2
    assert r["hours"]["text"] == "5.8 hours"            # 60/60 × 4.33 + 90/60 × 1
    assert r["over"]["value"] == ["Monthly review"]
    assert out["tables"]["meetings"][0]["agenda_minutes"]["value"] == 60


def test_org_chart_by_seat_lists_open_seats_and_seats_with_a_no():
    r, _ = results("ops_org_chart", {"seats": [
        {"seat": "Owner", "person": "Wiley Coyote", "knows": "Yes", "wants": "Yes",
         "has_time": "Yes"},
        {"seat": "Plant manager", "reports_to": "Owner", "person": "Marvin Martian",
         "knows": "Yes", "wants": "Yes", "has_time": "No"},
        {"seat": "Quality lead", "reports_to": "Plant manager", "person": ""}]})
    assert r["seats"]["value"] == 3
    assert r["open"]["value"] == ["Quality lead"] and r["nos"]["value"] == ["Plant manager"]


def test_responsibilities_keep_five_lines():
    kept = D.clean_values(shipped.SHIPPED["ops_org_chart"]["definition"], {"seats": [
        {"seat": "Owner", "responsibilities": "1\n2\n3\n4\n5\n6\n7"}]})
    assert kept["seats"][0]["responsibilities"] == "1\n2\n3\n4\n5"


# ------------------------------------------------------------------ runs over the API

def start(sc, tool="ops_bottleneck", who="ff", company=None):
    r = post(client(sc, who), RUNS, {"company": company or str(sc["company"].pk), "tool": tool})
    assert r.status_code == 201, r.content
    return r.json()


def save_values(sc, run, values, who="ff"):
    r = patch(client(sc, who), f"{RUNS}{run['id']}/", {"values": values})
    assert r.status_code == 200, r.content
    return r.json()


def test_a_run_keeps_its_snapshot_when_the_tool_is_edited(on):
    sc = on
    made = post(client(sc, "ff"), TOOLS, {"name": "Margin check", "definition": {
        "sections": [{"title": "Numbers", "fields": [
            {"key": "price", "label": "Price", "type": "money"},
            {"key": "cost", "label": "Cost", "type": "money"}]}],
        "results": [{"key": "margin", "label": "Margin", "format": "percent",
                     "formula": "if(price > 0, (price - cost) / price * 100, 0)"}]}})
    assert made.status_code == 201, made.content
    run = start(sc, made.json()["id"])
    save_values(sc, run, {"price": 200, "cost": 150})
    # The tool changes: a new formula, a field gone.
    r = patch(client(sc, "ff"), f"{TOOLS}{made.json()['id']}/", {"definition": {
        "sections": [{"title": "Numbers", "fields": [
            {"key": "price", "label": "Price", "type": "money"}]}],
        "results": [{"key": "margin", "label": "Margin", "formula": "price * 2"}]}})
    assert r.status_code == 200, r.content
    again = get(sc, "ff", f"{RUNS}{run['id']}/").json()
    assert again["evaluation"]["results"][0]["text"] == "25%"
    assert [f["key"] for f in again["definition"]["sections"][0]["fields"]] == ["price", "cost"]
    # A new run takes the tool as it is now.
    fresh = start(sc, made.json()["id"])
    assert fresh["definition"]["results"][0]["formula"] == "price * 2"


def test_a_run_is_duplicated_and_renamed_and_dated(on):
    sc = on
    run = start(sc)
    save_values(sc, run, {"process": "Quoting"})
    r = patch(client(sc, "ff"), f"{RUNS}{run['id']}/", {"name": "Quoting, November",
                                                         "run_date": "2026-11-02"})
    assert r.json()["name"] == "Quoting, November" and r.json()["run_date"] == "2026-11-02"
    copy = post(client(sc, "ff"), f"{RUNS}{run['id']}/duplicate/").json()
    assert copy["name"] == "Quoting, November (copy)" and copy["values"]["process"] == "Quoting"


def test_the_kpi_reading_is_marked_from_a_tool(on):
    from apps.scorecard.models import KpiReading

    sc = on
    run = start(sc)
    save_values(sc, run, {"steps": [{"step": "Form", "capacity": 60, "demand": 80, "rework": 0}]})
    kpi = sc["kpis"]["all"]
    r = post(client(sc, "ff"), f"{RUNS}{run['id']}/reading/",
             {"result": "output", "kpi": str(kpi.pk), "day": timezone.localdate().isoformat()})
    assert r.status_code == 201, r.content
    with tenant_context(sc["tenant"].pk):
        reading = KpiReading.objects.filter(kpi=kpi, source="tool").get()
    assert reading.value == 60
    refused = post(client(sc, "ff"), f"{RUNS}{run['id']}/reading/",
                   {"result": "constraint", "kpi": str(kpi.pk)})
    assert refused.status_code == 400 and "Only a number" in refused.json()["detail"]


def test_tasks_come_from_flagged_rows_only(on):
    from apps.crm.models import Task
    from apps.work.models import TaskUpdate

    sc = on
    run = start(sc)
    assert post(client(sc, "ff"), f"{RUNS}{run['id']}/tasks/").status_code == 409
    save_values(sc, run, {"steps": [{"step": "Form", "_flag": True}, {"step": "Pack"}]})
    r = post(client(sc, "ff"), f"{RUNS}{run['id']}/tasks/")
    assert r.status_code == 201 and r.json()["titles"] == ["Form (Steps, in order)"]
    with tenant_context(sc["tenant"].pk):
        task = Task.objects.get(title="Form (Steps, in order)")
        assert task.client_company_id == sc["company"].pk
        assert TaskUpdate.objects.filter(task=task, source="tool").exists()


def test_a_run_proposes_to_the_plan_and_starts_an_sop_brainstorm(on):
    from apps.notes.models import Note
    from apps.plans.models import PlanItem

    sc = on
    run = start(sc)
    save_values(sc, run, {"process": "Quoting", "steps": [{"step": "Price it", "capacity": 10,
                                                           "demand": 12}]})
    r = post(client(sc, "ff"), f"{RUNS}{run['id']}/propose/",
             {"horizon": "quarter", "title": "Lift quoting capacity to 15 a week"})
    assert r.status_code == 201, r.content
    item = PlanItem.all_objects.get(pk=r.json()["proposed"])
    assert (item.state, item.source) == ("proposed", "tool")
    assert item.drew_on == [f"Bottleneck finder: {run['name']}"]
    note = post(client(sc, "ff"), f"{RUNS}{run['id']}/sop-brainstorm/").json()
    body = Note.all_objects.get(pk=note["note"]).body
    assert "Steps:" in body and "Price it" in body and "The constraint: Price it" in body


def test_steps_come_in_from_an_sop(on):
    from apps.notes.models import Note

    sc = on
    with tenant_context(sc["tenant"].pk):
        note = Note.objects.create(tenant=sc["tenant"], company=sc["company"],
                                   title="SOP draft: Picking",
                                   body="Purpose: pick right\n1. Read the order\n2. Pick the "
                                        "bins\n3. Scan and pack")
        locked = Note.objects.create(tenant=sc["tenant"], company=sc["company"],
                                     title="SOP draft: Pay", body="1. Secret",
                                     pin_hash="x", pin_set_at=timezone.now())
    run = start(sc)
    r = post(client(sc, "ff"), f"{RUNS}{run['id']}/import-sop/", {"source": f"note:{note.pk}"})
    assert r.status_code == 200, r.content
    assert [s["step"] for s in r.json()["run"]["values"]["steps"]] == [
        "Read the order", "Pick the bins", "Scan and pack"]
    assert post(client(sc, "ff"), f"{RUNS}{run['id']}/import-sop/",
                {"source": f"note:{locked.pk}"}).status_code == 404
    other = start(sc, "ops_capacity")
    assert post(client(sc, "ff"), f"{RUNS}{other['id']}/import-sop/",
                {"source": f"note:{note.pk}"}).status_code == 409


def test_the_cadence_makes_recurring_events_and_a_calendar_file(on):
    sc = on
    run = start(sc, "ops_meetings")
    save_values(sc, run, {"meetings": [
        {"name": "Weekly leadership meeting", "cadence": "Weekly", "day": "Monday",
         "time": "09:00", "minutes": 60, "start": "2026-11-09",
         "attendees": ["Mia Member", "Max Manager"]},
        {"name": "Monthly review", "cadence": "Monthly", "day": "Thursday", "time": "14:00",
         "minutes": 90, "start": "2026-11-13"}],
        "agenda": [{"meeting": "Weekly leadership meeting", "section": "Numbers", "minutes": 10},
                   {"meeting": "Weekly leadership meeting", "section": "Issues",
                    "minutes": 30}]})
    preview = get(sc, "ff", f"{RUNS}{run['id']}/files/calendar/").json()
    weekly, monthly = preview["events"]
    assert (weekly["first"], weekly["rrule"]) == ("2026-11-09", "FREQ=WEEKLY;BYDAY=MO")
    # The first Thursday on or after November 13 is December 3.
    assert (monthly["first"], monthly["rrule"]) == ("2026-12-03", "FREQ=MONTHLY;BYDAY=1TH")
    assert weekly["agenda"] == ["9:00 Numbers (10 min)", "9:10 Issues (30 min)"]
    ics = client(sc, "ff").get(f"{RUNS}{run['id']}/files/ics/")
    text = ics.content.decode()
    assert ics["Content-Type"] == "text/calendar"
    assert "RRULE:FREQ=WEEKLY;BYDAY=MO" in text and "SUMMARY:Monthly review" in text
    assert "Mia Member\\, Max Manager" in text
    # With no calendar connected the app says so, and creates nothing.
    r = post(client(sc, "ff"), f"{RUNS}{run['id']}/calendar/")
    assert r.status_code == 409 and "No calendar is connected" in r.json()["detail"]
    agenda = client(sc, "ff").get(f"{RUNS}{run['id']}/files/agenda/")
    assert agenda.status_code == 200 and agenda.content[:2] == b"PK"


def test_the_demo_shows_the_events_and_makes_none(on, settings):
    sc = on
    run = start(sc, "ops_meetings")
    save_values(sc, run, {"meetings": [{"name": "Weekly", "cadence": "Weekly", "day": "Monday",
                                        "time": "09:00", "minutes": 60,
                                        "start": "2026-11-09"}]})
    settings.APP_ENVIRONMENT = "demo"
    settings.IS_DEMO = True
    r = post(client(sc, "ff"), f"{RUNS}{run['id']}/calendar/")
    assert r.status_code == 409 and "would make" in r.json()["detail"]
    assert get(sc, "ff", f"{RUNS}{run['id']}/files/calendar/").json()["demo"] is True


def test_a_run_exports_to_word_and_pdf(on):
    sc = on
    run = start(sc, "ops_org_chart")
    save_values(sc, run, {"seats": [{"seat": "Owner", "person": "Olive Owner"},
                                    {"seat": "Ops", "reports_to": "Owner"}]})
    word = client(sc, "ff").get(f"{RUNS}{run['id']}/files/docx/")
    assert word.status_code == 200 and word.content[:2] == b"PK"
    pdf = client(sc, "ff").get(f"{RUNS}{run['id']}/files/pdf/")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


# ------------------------------------------------------------------ who reaches what

def test_practice_isolation(on):
    sc = on
    run = start(sc)
    tool = post(client(sc, "ff"), TOOLS, {"name": "Ours", "definition": {
        "sections": [{"title": "S", "fields": [{"key": "a", "label": "A",
                                                "type": "number"}]}]}}).json()
    stranger = sc["api"].as_(MembershipFactory(tenant=TenantFactory(), role="FF"))
    assert stranger.get(f"{RUNS}{run['id']}/").status_code == 404
    assert stranger.get(f"{TOOLS}{tool['id']}/").status_code == 404
    assert post(stranger, f"{TOOLS}{tool['id']}/duplicate/").status_code == 404
    assert stranger.get(f"{RUNS}?company={sc['company'].pk}").status_code == 404
    assert get(sc, "cf_other", f"{RUNS}{run['id']}/").status_code == 404
    elsewhere = ClientCompanyFactory(tenant=sc["tenant"], name="Elsewhere")
    them = sc["api"].as_(MembershipFactory(tenant=sc["tenant"], role="FCC",
                                           client_company=elsewhere))
    patch(client(sc, "ff"), f"{RUNS}{run['id']}/", {"shared_with_client": True})
    assert them.get(f"{RUNS}{run['id']}/").status_code == 404
    # Each practice's tools are its own.
    other_ff = MembershipFactory(tenant=TenantFactory(), role="FF")
    with tenant_context(other_ff.tenant_id):
        assert all(t["shipped"] for t in services.catalog(other_ff.tenant_id))


def test_no_command_center_means_no_tools(sc):
    assert get(sc, "ff", TOOLS).status_code == 404
    assert post(client(sc, "ff"), RUNS, {"company": str(sc["company"].pk),
                                         "tool": "ops_bottleneck"}).status_code == 404


def test_the_portal_sees_a_shared_run_read_only_and_only_its_owner_and_leaders(on):
    sc = on
    run = start(sc)
    for who in ("owner", "leader", "member"):
        assert get(sc, who, f"{RUNS}{run['id']}/").status_code == 404
    patch(client(sc, "ff"), f"{RUNS}{run['id']}/", {"shared_with_client": True})
    for who in ("owner", "leader"):
        seen = get(sc, who, f"{RUNS}{run['id']}/")
        assert seen.status_code == 200 and "choices" not in seen.json()
        assert [r["id"] for r in get(sc, who, f"{RUNS}?company=mine").json()["runs"]] == [run["id"]]
        assert patch(client(sc, who), f"{RUNS}{run['id']}/", {"name": "x"}).status_code == 403
        assert post(client(sc, who), f"{RUNS}{run['id']}/tasks/").status_code == 403
    for who in ("member", "manager", "viewer"):
        assert get(sc, who, f"{RUNS}{run['id']}/").status_code == 404
        assert get(sc, who, f"{RUNS}?company=mine").json()["runs"] == []
    assert client(sc, "owner").get("/api/me").json()["has_tool_runs"] is True
    assert client(sc, "member").get("/api/me").json()["has_tool_runs"] is False


def test_only_the_practice_owner_builds_tools(on):
    sc = on
    body = {"name": "X", "definition": {"sections": [{"title": "S", "fields": [
        {"key": "a", "label": "A", "type": "number"}]}]}}
    for who in ("cf", "va", "owner"):
        assert post(client(sc, who), TOOLS, body).status_code in (403, 404)
    assert post(client(sc, "ff"), f"{TOOLS}ops_capacity/duplicate/").status_code == 201
    assert post(client(sc, "cf"), f"{TOOLS}ops_capacity/duplicate/").status_code == 403


def test_a_duplicated_shipped_tool_is_the_practices_to_edit(on):
    sc = on
    copy = post(client(sc, "ff"), f"{TOOLS}ops_bottleneck/duplicate/").json()
    assert copy["name"] == "Bottleneck finder (our copy)" and copy["shipped"] is False
    definition = copy["definition"]
    definition["results"].append({"key": "steps_count", "label": "Steps",
                                  "formula": "count(steps.step)"})
    r = patch(client(sc, "ff"), f"{TOOLS}{copy['id']}/", {"definition": definition})
    assert r.status_code == 200
    assert shipped.SHIPPED["ops_bottleneck"]["definition"]["results"][-1]["key"] == "waiting"
    bad = patch(client(sc, "ff"), f"{TOOLS}{copy['id']}/", {"definition": {
        "sections": [{"title": "S", "fields": [{"key": "a", "label": "A", "type": "computed",
                                                "formula": "a +"}]}]}})
    assert bad.status_code == 400 and bad.json()["errors"][0]["where"] == "sections.0.fields.0"
    assert post(client(sc, "ff"), f"{TOOLS}validate/", {"definition": {"sections": []}}) \
        .json()["errors"]


# ------------------------------------------------------------------ the builder

def test_the_builder_says_its_price_first_and_proposes_without_saving(on, fake_claude):
    sc = on
    status = get(sc, "ff", f"{TOOLS}builder/").json()
    assert Decimal(status["estimate_usd"]) >= 0 and status["cap"] == 20
    fake_claude.reply = json.dumps({"name": "Quote turnaround", "description": "Quotes a week",
                                    "definition": {"sections": [{"title": "Quotes", "fields": [
                                        {"key": "asked", "label": "Asked", "type": "number"},
                                        {"key": "sent", "label": "Sent", "type": "number"}]}],
                                        "results": [{"key": "rate", "label": "Sent",
                                                     "format": "percent",
                                                     "formula": "if(asked > 0, sent / asked * 100, 0)"}]}})
    r = post(client(sc, "ff"), f"{TOOLS}builder/", {"description": "Track quotes asked and sent "
                                                                     "each week"})
    assert r.status_code == 200, r.content
    proposal = r.json()
    assert proposal["errors"] == [] and proposal["name"] == "Quote turnaround"
    assert fake_claude.requests[-1]["model"].startswith("claude-opus")
    assert not Tool.all_objects.filter(tenant=sc["tenant"]).exists()
    saved = post(client(sc, "ff"), TOOLS, {"name": proposal["name"],
                                           "definition": proposal["definition"],
                                           "from_ai": True})
    assert saved.status_code == 201 and Tool.all_objects.get().from_ai is True
    # A proposal that doesn't hold together comes back with its problems.
    fake_claude.reply = json.dumps({"name": "Bad", "definition": {"sections": [
        {"title": "S", "fields": [{"key": "x", "label": "X", "type": "computed",
                                   "formula": "y * 2"}]}]}})
    r = post(client(sc, "ff"), f"{TOOLS}builder/", {"description": "Something with a typo in it"})
    assert "no field called" in r.json()["errors"][0]["message"]
    assert post(client(sc, "cf"), f"{TOOLS}builder/", {"description": "x" * 20}).status_code == 403


# ------------------------------------------------------------------ MCP, terms

def test_mcp_lists_and_reads_runs_within_reach(on):
    from apps.aiconnect import tools as T

    from .test_plans import principal

    sc = on
    run = start(sc)
    save_values(sc, run, {"steps": [{"step": "Form", "capacity": 60, "demand": 80}]})
    with tenant_context(sc["tenant"].pk):
        listed = T.list_tool_runs(principal(sc, "cf"), str(sc["company"].pk))
        assert [r["id"] for r in listed["runs"]] == [run["id"]]
        read = T.get_tool_run(principal(sc, "va"), run["id"])
        assert {"label": "The constraint", "value": "Form"} in read["results"]
        for who in ("cf_other", "owner"):
            with pytest.raises(T.ToolRefused):
                T.list_tool_runs(principal(sc, who), str(sc["company"].pk))
            with pytest.raises(T.ToolRefused):
                T.get_tool_run(principal(sc, who), run["id"])


def test_no_eos_term_in_what_the_tools_ship():
    import re

    from apps.tools import builder

    from .test_command_centers import BANNED

    more = re.compile(r"\b(gwc|level 10|get it,? want it|accountability chart)\b", re.I)
    texts = [builder.SYSTEM]
    for tool in shipped.SHIPPED.values():
        texts += [tool["name"], tool["description"], json.dumps(tool["definition"])]
    for text in texts:
        assert not BANNED.search(text) and not more.search(text), text[:80]


def test_the_command_centers_tools_shelf_names_the_four():
    from apps.centers.content import operations

    assert operations.TOOLS == [t["name"] for t in shipped.SHIPPED.values()]


def test_runs_for_the_practice_itself(on):
    sc = on
    run = start(sc, "ops_capacity", company="practice")
    assert run["company"]["is_practice"] is True
    assert get(sc, "cf", f"{RUNS}?company=practice").json()["runs"][0]["id"] == run["id"]
    assert get(sc, "owner", f"{RUNS}?company=practice").status_code == 404
    assert date.fromisoformat(run["run_date"]) == timezone.localdate()
    assert ToolRun.all_objects.get(pk=run["id"]).company.is_practice
