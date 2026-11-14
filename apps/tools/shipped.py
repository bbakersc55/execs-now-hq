"""The four Operations tools (P12), shipped in code. A practice runs them as
they are, or duplicates one into a tool of its own and edits it there. Plain
words only: nothing here borrows a named management system's terms.

Each has a "How to use this" (`how_to`), a sample to load (`sample`) and a
sentence on every result card (`says`), 2026-11-14. A run keeps a snapshot of
its definition; a run made before these existed takes them from here by its
tool's key (`services.definition_for`).
"""

from __future__ import annotations

import copy

BOTTLENECK = {
    "name": "Bottleneck finder",
    "description": "The steps of a process with their capacity and demand: each step's load, "
                   "the constraint, and what the whole process can produce a week because of it.",
    "definition": {
        "sections": [{"title": "The process", "fields": [
            {"key": "process", "label": "Process", "type": "text"},
            {"key": "steps", "label": "Steps, in order", "type": "table", "columns": [
                {"key": "step", "label": "Step", "type": "text"},
                {"key": "who", "label": "Who does it", "type": "person"},
                {"key": "capacity", "label": "Capacity a week (units)", "type": "number"},
                {"key": "demand", "label": "Demand a week (units)", "type": "number"},
                {"key": "minutes", "label": "Time per unit (minutes)", "type": "number"},
                {"key": "wait", "label": "Wait before it (hours)", "type": "number"},
                {"key": "rework", "label": "Rework", "type": "percent"},
                {"key": "load", "label": "Load", "type": "computed", "format": "percent",
                 "formula": "if(capacity > 0, demand * (1 + rework / 100) / capacity * 100, 0)"},
                {"key": "good", "label": "Good units a week", "type": "computed",
                 "format": "number", "formula": "capacity / (1 + rework / 100)"},
            ]},
        ]}],
        "results": [
            {"key": "constraint", "label": "The constraint", "format": "text",
             "formula": "argmax(steps.step, steps.load)",
             "note": "The step with the highest load against its capacity",
             "says": "{constraint} is the constraint: it holds up the whole process, so it "
                     "is the step to fix first."},
            {"key": "constraint_load", "label": "Its load", "format": "percent",
             "formula": "max(steps.load)",
             "says": "{constraint} is asked for {constraint_load} of what it can do. Over "
                     "100% means work piles up in front of it."},
            {"key": "output", "label": "The process can produce a week", "format": "number",
             "formula": "min(steps.good)",
             "note": "Good units a week, held there by the constraint",
             "says": "Because of {constraint}, the whole process finishes about {output} good "
                     "units a week."},
            {"key": "shortfall", "label": "Short of demand a week", "format": "number",
             "formula": "max(0, max(steps.demand) - min(steps.good))",
             "says": "That is {shortfall} units a week short of what is asked for."},
            {"key": "waiting", "label": "Waiting between steps", "format": "hours",
             "formula": "sum(steps.wait)",
             "says": "Work spends {waiting} waiting between steps, on top of the work itself."},
        ],
        "actions": ["import_sop"],
        "how_to": [
            "Name the process, then add its steps in order, one row each, with who does it.",
            "For each step, put what it can handle a week and what is asked of it a week, in "
            "the same units, with the wait before it and the share that is redone.",
            "Read the results: the step with the highest load is the constraint, and it sets "
            "what the whole process can produce.",
            "Flag the steps to act on and press Tasks from flagged rows, or send the output "
            "to a KPI.",
        ],
        "sample": {"process": "Order to shipment", "steps": [
            {"step": "Take the order", "who": "Order desk", "capacity": 120, "demand": 90,
             "minutes": 10, "wait": 4, "rework": 2},
            {"step": "Schedule the job", "who": "Planner", "capacity": 100, "demand": 90,
             "minutes": 15, "wait": 8, "rework": 0},
            {"step": "Make the parts", "who": "Production", "capacity": 80, "demand": 90,
             "minutes": 45, "wait": 24, "rework": 6},
            {"step": "Inspect", "who": "Quality", "capacity": 110, "demand": 90,
             "minutes": 12, "wait": 6, "rework": 0},
            {"step": "Pack and ship", "who": "Shipping", "capacity": 140, "demand": 90,
             "minutes": 8, "wait": 2, "rework": 0}]},
    },
}

CAPACITY = {
    "name": "Capacity model",
    "description": "Roles and the work they do: capacity against demand by role, the gap in "
                   "hours and in people, and a what-if for demand or hires.",
    "definition": {
        "sections": [
            {"title": "The team", "fields": [
                {"key": "roles", "label": "Roles", "type": "table", "columns": [
                    {"key": "role", "label": "Role", "type": "text"},
                    {"key": "people", "label": "People", "type": "number"},
                    {"key": "hours", "label": "Hours a week each", "type": "number"},
                    {"key": "productive", "label": "Productive", "type": "percent"},
                    {"key": "added", "label": "What if we hire (people)", "type": "number"},
                    {"key": "capacity", "label": "Capacity (hours a week)", "type": "computed",
                     "format": "hours", "formula": "(people + added) * hours * productive / 100"},
                    {"key": "demand", "label": "Demand (hours a week)", "type": "computed",
                     "format": "hours",
                     "formula": "sumif(work.role, role, work.hours_week) * (1 + demand_change / 100)"},
                    {"key": "gap", "label": "Gap (hours)", "type": "computed", "format": "hours",
                     "formula": "demand - capacity"},
                    {"key": "gap_people", "label": "Gap (people)", "type": "computed",
                     "format": "number",
                     "formula": "if(hours * productive > 0, (demand - capacity) / (hours * productive / 100), 0)"},
                ]},
            ]},
            {"title": "The work", "fields": [
                {"key": "work", "label": "Work a week", "type": "table", "columns": [
                    {"key": "item", "label": "Work", "type": "text"},
                    {"key": "role", "label": "Done by (role)", "type": "text"},
                    {"key": "volume", "label": "Volume a week", "type": "number"},
                    {"key": "hours_per_unit", "label": "Hours per unit", "type": "number"},
                    {"key": "hours_week", "label": "Hours a week", "type": "computed",
                     "format": "hours", "formula": "volume * hours_per_unit"},
                ]},
            ]},
            {"title": "What if", "fields": [
                {"key": "demand_change", "label": "Demand up or down by (a minus is down)",
                 "type": "percent"},
            ]},
        ],
        "results": [
            {"key": "capacity", "label": "Capacity a week", "format": "hours",
             "formula": "sum(roles.capacity)",
             "says": "The team has {capacity} of productive time a week."},
            {"key": "demand", "label": "Demand a week", "format": "hours",
             "formula": "sum(roles.demand)",
             "says": "The work coming in needs {demand} a week."},
            {"key": "gap_hours", "label": "Hours short (a minus is spare)", "format": "hours",
             "formula": "sum(roles.demand) - sum(roles.capacity)",
             "says": "So the team is {gap_hours} a week short of the work. A minus means that "
                     "many hours to spare."},
            {"key": "gap_people", "label": "People short (a minus is spare)", "format": "number",
             "formula": "sum(roles.gap_people)",
             "says": "In people, that is {gap_people} short across the roles. A minus means "
                     "spare people."},
            {"key": "tightest", "label": "Most stretched role", "format": "text",
             "formula": "argmax(roles.role, roles.gap_people)",
             "says": "{tightest} is the most stretched role: the first place to hire or to "
                     "move work away from."},
        ],
        "how_to": [
            "Fill in the roles: one row a role, with how many people, the hours a week each "
            "works, and the share of those hours that is productive.",
            "Fill in the work: one row for each kind of work, how much comes in a week, the "
            "hours each one takes, and which role does it, spelled as in the roles.",
            "Read the gap: each role's capacity against its demand, in hours and in people. "
            "A plus is short; a minus is spare.",
            "Try the what-ifs: a percent in Demand up or down, or a number in What if we hire "
            "on a role, and watch the gap move.",
        ],
        "sample": {"demand_change": 0, "roles": [
            {"role": "Production", "people": 5, "hours": 40, "productive": 75, "added": 0},
            {"role": "Quality", "people": 1, "hours": 40, "productive": 80, "added": 0},
            {"role": "Office", "people": 2, "hours": 40, "productive": 70, "added": 0}],
            "work": [
                {"item": "Parts made", "role": "Production", "volume": 320,
                 "hours_per_unit": 0.5},
                {"item": "Changeovers", "role": "Production", "volume": 10,
                 "hours_per_unit": 1.5},
                {"item": "Inspections", "role": "Quality", "volume": 150,
                 "hours_per_unit": 0.25},
                {"item": "Orders entered and invoiced", "role": "Office", "volume": 90,
                 "hours_per_unit": 0.5}]},
    },
}

MEETINGS = {
    "name": "Meeting cadence builder",
    "description": "The client's standing meetings: who attends, when, how long, and an agenda "
                   "in timed sections. The cadence on one page, an agenda document, and the "
                   "recurring calendar events.",
    "definition": {
        "sections": [
            {"title": "Standing meetings", "fields": [
                {"key": "meetings", "label": "Meetings", "type": "table", "columns": [
                    {"key": "name", "label": "Meeting", "type": "text"},
                    {"key": "cadence", "label": "How often", "type": "choice",
                     "options": ["Weekly", "Every two weeks", "Monthly", "Quarterly"]},
                    {"key": "day", "label": "Day", "type": "choice",
                     "options": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]},
                    {"key": "time", "label": "Time (like 09:00)", "type": "text"},
                    {"key": "minutes", "label": "Length (minutes)", "type": "number"},
                    {"key": "start", "label": "First one on or after", "type": "date"},
                    {"key": "attendees", "label": "Who attends", "type": "people"},
                    {"key": "agenda_minutes", "label": "Agenda adds up to (minutes)",
                     "type": "computed", "format": "number",
                     "formula": "sumif(agenda.meeting, name, agenda.minutes)"},
                    {"key": "over", "label": "Agenda runs over", "type": "computed",
                     "format": "number", "formula": "if(agenda_minutes > minutes, 1, 0)"},
                    {"key": "hours_month", "label": "Hours a month", "type": "computed",
                     "format": "hours",
                     "formula": "minutes / 60 * if(cadence = \"Weekly\", 4.33, if(cadence = \"Every two weeks\", 2.17, if(cadence = \"Monthly\", 1, if(cadence = \"Quarterly\", 0.33, 0))))"},
                ]},
            ]},
            {"title": "Agendas", "fields": [
                {"key": "agenda", "label": "Agenda, in timed sections", "type": "table",
                 "columns": [
                     {"key": "meeting", "label": "Meeting", "type": "text"},
                     {"key": "section", "label": "Section", "type": "text"},
                     {"key": "minutes", "label": "Minutes", "type": "number"},
                 ]},
            ]},
        ],
        "results": [
            {"key": "count", "label": "Standing meetings", "format": "number",
             "formula": "count(meetings.name)",
             "says": "The company keeps {count} standing meetings."},
            {"key": "hours", "label": "Meeting hours a month, for someone in all of them",
             "format": "hours", "formula": "sum(meetings.hours_month)",
             "says": "Someone in all of them spends {hours} a month in these meetings."},
            {"key": "over", "label": "Agendas that run over", "format": "list",
             "formula": "filter(meetings.name, meetings.over)",
             "says": "Agendas longer than their meeting: {over}."},
        ],
        "views": [{"type": "cadence", "table": "meetings", "agenda": "agenda"}],
        "actions": ["calendar"],
        "how_to": [
            "List each standing meeting: how often, the day, the time (like 09:00), how long, "
            "the first date, and who attends. Pick people or a whole team.",
            "Add each meeting's agenda below in timed sections, naming the meeting as it is "
            "written above.",
            "Read the results: the hours a month the meetings take, and any agenda longer "
            "than its meeting.",
            "Save, then download the agenda document or a calendar file, or add the events "
            "to your own calendar.",
        ],
        "sample": {"meetings": [
            {"name": "Weekly leadership meeting", "cadence": "Weekly", "day": "Monday",
             "time": "09:00", "minutes": 60, "start": "2026-11-16",
             "attendees": ["The owner", "Operations lead", "Sales lead"]},
            {"name": "Monthly review", "cadence": "Monthly", "day": "Thursday",
             "time": "14:00", "minutes": 90, "start": "2026-11-16",
             "attendees": ["The owner", "Operations lead", "Sales lead", "Office manager"]},
            {"name": "Quarterly planning", "cadence": "Quarterly", "day": "Friday",
             "time": "09:00", "minutes": 240, "start": "2026-11-16",
             "attendees": ["The owner", "Operations lead", "Sales lead", "Office manager"]}],
            "agenda": [
                {"meeting": "Weekly leadership meeting", "section": "The week's numbers",
                 "minutes": 10},
                {"meeting": "Weekly leadership meeting", "section": "Wins and issues",
                 "minutes": 35},
                {"meeting": "Weekly leadership meeting", "section": "Actions and who owns them",
                 "minutes": 15},
                {"meeting": "Monthly review", "section": "The month's numbers", "minutes": 30},
                {"meeting": "Monthly review", "section": "The plan's month", "minutes": 30},
                {"meeting": "Monthly review", "section": "Next month", "minutes": 30},
                {"meeting": "Quarterly planning", "section": "The quarter behind us",
                 "minutes": 60},
                {"meeting": "Quarterly planning", "section": "Next quarter's priorities",
                 "minutes": 120},
                {"meeting": "Quarterly planning", "section": "Who owns what", "minutes": 60}]},
    },
}

ORG_CHART = {
    "name": "Org chart by seat",
    "description": "Seats first, people second: each seat, what it reports to, its "
                   "responsibilities and who is in it, with three plain checks. The chart, "
                   "the open seats and the seats with a no.",
    "definition": {
        "sections": [{"title": "Seats", "fields": [
            {"key": "seats", "label": "Seats", "type": "table", "columns": [
                {"key": "seat", "label": "Seat", "type": "text"},
                {"key": "department", "label": "Department", "type": "text"},
                {"key": "reports_to", "label": "Reports to (a seat)", "type": "text"},
                {"key": "responsibilities", "label": "Responsibilities (up to five, one a line)",
                 "type": "long_text", "max_lines": 5},
                {"key": "person", "label": "Who is in it (blank is open)", "type": "person"},
                {"key": "knows", "label": "Knows the job", "type": "choice",
                 "options": ["Yes", "No"]},
                {"key": "wants", "label": "Wants the job", "type": "choice",
                 "options": ["Yes", "No"]},
                {"key": "has_time", "label": "Has the time and skill", "type": "choice",
                 "options": ["Yes", "No"]},
                {"key": "is_open", "label": "Open", "type": "computed", "format": "number",
                 "formula": "if(person = \"\" or person = \"open\", 1, 0)"},
                {"key": "has_no", "label": "A no", "type": "computed", "format": "number",
                 "formula": "if(knows = \"No\" or wants = \"No\" or has_time = \"No\", 1, 0)"},
            ]},
        ]}],
        "results": [
            {"key": "seats", "label": "Seats", "format": "number",
             "formula": "count(seats.seat)",
             "says": "The company has {seats} seats on the chart."},
            {"key": "open", "label": "Open seats", "format": "list",
             "formula": "filter(seats.seat, seats.is_open)",
             "says": "Seats nobody is in yet: {open}."},
            {"key": "nos", "label": "Seats with a no", "format": "list",
             "formula": "filter(seats.seat, seats.has_no)",
             "says": "Seats where the person got a no on one of the three checks: {nos}."},
        ],
        "views": [{"type": "org_chart", "table": "seats", "name": "seat", "parent": "reports_to",
                   "person": "person", "department": "department",
                   "checks": ["knows", "wants", "has_time"]}],
        "how_to": [
            "Add the seats the company needs, one row each, with the seat it reports to. The "
            "top seat reports to no seat.",
            "Give each seat its department and up to five responsibilities, then who is in "
            "it. Leave that blank when the seat is open.",
            "Answer the three checks for the person in each seat: knows the job, wants the "
            "job, has the time and skill.",
            "Read the chart: open seats are dashed and a seat with a no is marked. Zoom in or "
            "out, or download the PDF to print it.",
        ],
        "sample": {"seats": [
            {"seat": "Owner", "department": "Leadership", "reports_to": "",
             "responsibilities": "Where the company is going\nKey customers\nCash",
             "person": "Jordan Lee", "knows": "Yes", "wants": "Yes", "has_time": "Yes"},
            {"seat": "Operations manager", "department": "Operations", "reports_to": "Owner",
             "responsibilities": "The weekly schedule\nThe floor's people\nOn-time delivery",
             "person": "Sam Patel", "knows": "Yes", "wants": "Yes", "has_time": "No"},
            {"seat": "Sales lead", "department": "Sales", "reports_to": "Owner",
             "responsibilities": "New customers\nQuotes\nThe sales numbers",
             "person": "Riley Chen", "knows": "Yes", "wants": "Yes", "has_time": "Yes"},
            {"seat": "Office manager", "department": "Finance and office", "reports_to": "Owner",
             "responsibilities": "Invoices and bills\nPayroll\nThe books",
             "person": "Morgan Diaz", "knows": "Yes", "wants": "No", "has_time": "Yes"},
            {"seat": "Production supervisor", "department": "Operations",
             "reports_to": "Operations manager", "person": "",
             "responsibilities": "The day's output\nSafety on the floor"},
            {"seat": "Quality lead", "department": "Quality", "reports_to": "Operations manager",
             "person": "", "responsibilities": "Inspections\nReturns"}]},
    },
}

SHIPPED = {"ops_bottleneck": BOTTLENECK, "ops_capacity": CAPACITY, "ops_meetings": MEETINGS,
           "ops_org_chart": ORG_CHART}
ORDER = list(SHIPPED)


def get(key) -> dict | None:
    found = SHIPPED.get(key)
    return copy.deepcopy(found) if found else None
