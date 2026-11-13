"""The demo's tools (P12, docs/p12_tools.md, "The demo"). No Claude: every
value is written here as a person would have typed it.

- **Acme Fasteners:** one run of each of the four Operations tools, from the
  reset's discovery weeks. The org chart and the bottleneck finder are shared
  with Wiley in the portal.
- **Summit:** one tool of its own, "Client health check", made as if with the
  builder, and one run of it on the practice itself.
"""

from __future__ import annotations

from datetime import timedelta

from .clock import at, moment

ACME = "Acme Fasteners"

BOTTLENECK = {"process": "Order to shipment", "steps": [
    {"step": "Quote the order", "who": "Daffy Duckworth", "capacity": 60, "demand": 45,
     "minutes": 25, "wait": 16, "rework": 5},
    {"step": "Schedule the job", "who": "Marvin Martian", "capacity": 80, "demand": 45,
     "minutes": 10, "wait": 8, "rework": 0},
    {"step": "Cut the blanks", "who": "Saw cell", "capacity": 70, "demand": 45, "minutes": 30,
     "wait": 12, "rework": 4},
    {"step": "Head and thread", "who": "Header line", "capacity": 40, "demand": 45,
     "minutes": 50, "wait": 30, "rework": 9, "_flag": True},
    {"step": "Inspect", "who": "Quality", "capacity": 65, "demand": 45, "minutes": 15,
     "wait": 6, "rework": 0},
    {"step": "Pack and ship", "who": "Shipping", "capacity": 90, "demand": 45, "minutes": 8,
     "wait": 4, "rework": 0}]}

CAPACITY = {"demand_change": 10, "roles": [
    {"role": "Machinists", "people": 6, "hours": 40, "productive": 75, "added": 1},
    {"role": "Quality", "people": 2, "hours": 40, "productive": 80, "added": 0},
    {"role": "Shipping", "people": 2, "hours": 40, "productive": 85, "added": 0}],
    "work": [
        {"item": "Production parts", "role": "Machinists", "volume": 360, "hours_per_unit": 0.5},
        {"item": "Changeovers", "role": "Machinists", "volume": 12, "hours_per_unit": 1.5},
        {"item": "Inspections", "role": "Quality", "volume": 220, "hours_per_unit": 0.25},
        {"item": "Orders shipped", "role": "Shipping", "volume": 45, "hours_per_unit": 1.2}]}

ORG = {"seats": [
    {"seat": "Owner", "reports_to": "", "person": "Wiley Coyote", "knows": "Yes",
     "wants": "Yes", "has_time": "Yes",
     "responsibilities": "Where the company is going\nKey customers\nCash and pricing"},
    {"seat": "Plant manager", "reports_to": "Owner", "person": "Marvin Martian",
     "knows": "Yes", "wants": "Yes", "has_time": "No", "_flag": True,
     "responsibilities": "Runs the weekly meeting\nScheduling\nThe floor's people\n"
                         "Scrap and on-time numbers"},
    {"seat": "Purchasing lead", "reports_to": "Owner", "person": "Daffy Duckworth",
     "knows": "Yes", "wants": "No", "has_time": "Yes",
     "responsibilities": "Steel and wire buying\nSupplier prices\nStock levels"},
    {"seat": "Quality lead", "reports_to": "Plant manager", "person": "",
     "responsibilities": "Inspection plans\nScrap tags\nCustomer returns", "_flag": True},
    {"seat": "Second-shift supervisor", "reports_to": "Plant manager", "person": "",
     "responsibilities": "Night shift output\nNight shift safety"}]}


def _meetings(start):
    first = start.isoformat()
    people = ["Wiley Coyote", "Marvin Martian", "Daffy Duckworth"]
    return {"meetings": [
        {"name": "Weekly leadership meeting", "cadence": "Weekly", "day": "Monday",
         "time": "08:30", "minutes": 60, "start": first, "attendees": people},
        {"name": "Every-two-weeks actions check", "cadence": "Every two weeks",
         "day": "Wednesday", "time": "15:00", "minutes": 30, "start": first,
         "attendees": ["Marvin Martian", "Daffy Duckworth"]},
        {"name": "Monthly review", "cadence": "Monthly", "day": "Thursday", "time": "10:00",
         "minutes": 90, "start": first, "attendees": people},
        {"name": "Quarterly planning", "cadence": "Quarterly", "day": "Friday", "time": "09:00",
         "minutes": 240, "start": first, "attendees": people}],
        "agenda": [
            {"meeting": "Weekly leadership meeting", "section": "The scorecard", "minutes": 10},
            {"meeting": "Weekly leadership meeting", "section": "This week's sprint",
             "minutes": 10},
            {"meeting": "Weekly leadership meeting", "section": "Issues, solved one at a time",
             "minutes": 30},
            {"meeting": "Weekly leadership meeting", "section": "Actions and who owns them",
             "minutes": 10},
            {"meeting": "Every-two-weeks actions check", "section": "Open actions",
             "minutes": 20},
            {"meeting": "Every-two-weeks actions check", "section": "Anything stuck",
             "minutes": 10},
            {"meeting": "Monthly review", "section": "The month's numbers", "minutes": 30},
            {"meeting": "Monthly review", "section": "The plan's month, closed", "minutes": 30},
            {"meeting": "Monthly review", "section": "Next month", "minutes": 40},
            {"meeting": "Quarterly planning", "section": "The quarter behind us",
             "minutes": 60},
            {"meeting": "Quarterly planning", "section": "The year's goals", "minutes": 60},
            {"meeting": "Quarterly planning", "section": "Next quarter's priorities",
             "minutes": 120}]}


HEALTH = {
    "name": "Client health check",
    "description": "A few signals, scored one to five and weighted, for how an engagement "
                   "is going.",
    "definition": {
        "sections": [{"title": "The engagement", "fields": [
            {"key": "client", "label": "Client", "type": "text"},
            {"key": "signals", "label": "Signals", "type": "table", "columns": [
                {"key": "signal", "label": "Signal", "type": "text"},
                {"key": "score", "label": "Score (1 to 5)", "type": "number"},
                {"key": "weight", "label": "Weight", "type": "percent"},
                {"key": "weighted", "label": "Weighted", "type": "computed",
                 "format": "number", "formula": "score * weight / 100"}]}]}],
        "results": [
            {"key": "health", "label": "Health (out of 5)", "format": "number",
             "formula": "if(sum(signals.weight) > 0, sum(signals.weighted) / sum(signals.weight) * 100, 0)"},
            {"key": "weakest", "label": "Weakest signal", "format": "text",
             "formula": "argmin(signals.signal, signals.score)"}]},
}


def tools(world) -> dict:
    from apps.scorecard.practice import practice_company
    from apps.tools import services

    company = world.companies[ACME]
    owner = world.owner
    today = world.today
    started = today - timedelta(weeks=2)
    made = []
    with at(moment(started, 11, 0)):
        for key, values, name, shared in (
                ("ops_bottleneck", BOTTLENECK, "Order to shipment, discovery", True),
                ("ops_capacity", CAPACITY, "Floor capacity, with one more machinist", False),
                ("ops_org_chart", ORG, "Acme's seats", True)):
            run = services.start_run(company, key, actor=owner, name=name, run_date=started,
                                     values=values)
            if shared:
                services.update_run(run, {"shared_with_client": True}, actor=owner)
            made.append(run)
    with at(moment(today - timedelta(days=3), 14, 0)):
        monday = today + timedelta(days=(7 - today.weekday()) % 7 or 7)
        made.append(services.start_run(company, "ops_meetings", actor=owner,
                                       name="Acme's meeting rhythm",
                                       run_date=today - timedelta(days=3),
                                       values=_meetings(monday)))
    practice = practice_company(world.tenant)
    with at(moment(today - timedelta(days=10), 16, 0)):
        tool = services.save_tool(world.tenant, HEALTH, actor=owner)
        services.start_run(practice, str(tool.pk), actor=owner, name="Acme, mid-reset",
                           run_date=today - timedelta(days=10), values={
                               "client": "Acme Fasteners", "signals": [
                                   {"signal": "Weekly meeting held", "score": 4, "weight": 30},
                                   {"signal": "Numbers in on time", "score": 3, "weight": 25},
                                   {"signal": "Owner's time freed", "score": 2, "weight": 25},
                                   {"signal": "Team takes actions", "score": 4, "weight": 20}]})
    return {"acme tool runs": len(made), "summit tools": 1}
