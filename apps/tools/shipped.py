"""The four Operations tools (P12), shipped in code. A practice runs them as
they are, or duplicates one into a tool of its own and edits it there. Plain
words only: nothing here borrows a named management system's terms.
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
             "note": "The step with the highest load against its capacity"},
            {"key": "constraint_load", "label": "Its load", "format": "percent",
             "formula": "max(steps.load)"},
            {"key": "output", "label": "The process can produce a week", "format": "number",
             "formula": "min(steps.good)",
             "note": "Good units a week, held there by the constraint"},
            {"key": "shortfall", "label": "Short of demand a week", "format": "number",
             "formula": "max(0, max(steps.demand) - min(steps.good))"},
            {"key": "waiting", "label": "Waiting between steps", "format": "hours",
             "formula": "sum(steps.wait)"},
        ],
        "actions": ["import_sop"],
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
             "formula": "sum(roles.capacity)"},
            {"key": "demand", "label": "Demand a week", "format": "hours",
             "formula": "sum(roles.demand)"},
            {"key": "gap_hours", "label": "Hours short (a minus is spare)", "format": "hours",
             "formula": "sum(roles.demand) - sum(roles.capacity)"},
            {"key": "gap_people", "label": "People short (a minus is spare)", "format": "number",
             "formula": "sum(roles.gap_people)"},
            {"key": "tightest", "label": "Most stretched role", "format": "text",
             "formula": "argmax(roles.role, roles.gap_people)"},
        ],
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
             "formula": "count(meetings.name)"},
            {"key": "hours", "label": "Meeting hours a month, for someone in all of them",
             "format": "hours", "formula": "sum(meetings.hours_month)"},
            {"key": "over", "label": "Agendas that run over", "format": "list",
             "formula": "filter(meetings.name, meetings.over)"},
        ],
        "views": [{"type": "cadence", "table": "meetings", "agenda": "agenda"}],
        "actions": ["calendar"],
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
             "formula": "count(seats.seat)"},
            {"key": "open", "label": "Open seats", "format": "list",
             "formula": "filter(seats.seat, seats.is_open)"},
            {"key": "nos", "label": "Seats with a no", "format": "list",
             "formula": "filter(seats.seat, seats.has_no)"},
        ],
        "views": [{"type": "org_chart", "table": "seats", "name": "seat", "parent": "reports_to",
                   "person": "person"}],
    },
}

SHIPPED = {"ops_bottleneck": BOTTLENECK, "ops_capacity": CAPACITY, "ops_meetings": MEETINGS,
           "ops_org_chart": ORG_CHART}
ORDER = list(SHIPPED)


def get(key) -> dict | None:
    found = SHIPPED.get(key)
    return copy.deepcopy(found) if found else None
