"""What the Operations Command Center ships (P8). Plain words throughout:
no Rocks, L10, Integrator, Visionary, Accountability Chart or Six Key
Components (`tests/test_command_centers.py` checks every line here).

Each piece is copied into a practice on first use and edited there:
the session template through `apps.strategy.examples`, the KPI entries
through the scorecard library, playbooks into `centers.Playbook`, document
and email templates through their own seeds.
"""

from __future__ import annotations

CODE = "operations"


def item(seed_key, prompt, **fields):
    return {"seed_key": seed_key, "prompt": prompt, **fields}


# ----------------------------------------------------- 1. session template

#: "Start from the Operations Command Center": the v3 template of the
#: Operations example (version 2), with every EOS term in plain words.
#: Section kinds are the builder's (`apps.strategy.builder`).
def session_template() -> dict:
    from apps.strategy import builder

    return {
        "settings": {"advisor_role": "fractional operations executive"},
        "questions": {
            builder.PRECALL: [
                item("s1_revenue", "Revenue — last year / this year",
                     label="Revenue", pdf_chip=True),
                item("s1_team", "Team — full-time / part-time / admin & management",
                     label="Team", pdf_chip=True),
                item("s1_sites", "Active customer sites (or active accounts)",
                     label="Sites", pdf_chip=True),
                item("s1_service_mix", "Service mix — contract / projects / supplies / other"),
                item("s1_branches",
                     "Branches or locations — established vs. finding footing"),
                item("s1_top_accounts", "Top 5 accounts as % of revenue"),
                item("s1_software", "Software stack — and what lives in someone's head "
                                    "instead of a system"),
            ],
            # The six areas: vision, people, data, issues, process, results.
            builder.RATINGS: [
                item("s2_vision", "Vision — Our 3-year picture is clear, written down, and "
                                  "shared by the whole leadership team.", label="Vision"),
                item("s2_people", "People — We have the right people in the right roles, "
                                  "and every role on the org chart is filled.",
                     label="People"),
                item("s2_data", "Data — We run the week from a short scorecard of numbers.",
                     label="Data"),
                item("s2_issues", "Issues — Problems get raised openly and solved for good, "
                                  "not worked around.", label="Issues"),
                item("s2_process", "Process — Our core processes are documented, "
                                   "simplified, and followed by everyone.", label="Process"),
                item("s2_results", "Results — Everyone has quarterly priorities and a weekly "
                                   "leadership meeting that keeps them on track.",
                     label="Results"),
            ],
            builder.DIAGNOSTIC: [
                item("s4_decisions_stall", "Where do decisions stall because they need {Owner}?"),
                item("s4_turnover", "Turnover, time-to-fill, who recruits and how much of "
                                    "their week it takes"),
                item("s4_cash_pinch", "Cash pinch points: which parts of the business make "
                                      "money, and which are distractions?"),
            ],
            builder.MIRROR: [
                item("s3_three_year_picture",
                     "3-year picture — revenue, locations, {Owner}'s role, "
                     "{Second-in-command}'s role"),
                item("s3_current_priorities",
                     "Current quarterly priorities — which is most at risk?"),
                item("s3_stalled_goal", "A goal that has been on the list for over a year — "
                                        "what has been in the way?"),
                item("s3_alignment_observation",
                     "Do {Owner} and {Second-in-command} describe the destination the same "
                     "way?", observation=True),
            ],
            builder.VALUES: [
                item(f"s7_value_{n}", f"Value {n} — in their words, and why it matters to them")
                for n in range(1, 6)
            ],
            builder.PATHS: [
                item("s8_path_a",
                     "Path A — They run it: {Second-in-command} owns the map; rows become "
                     "next quarter's priorities; reviewed at every weekly leadership "
                     "meeting; progress depends on capacity they already have."),
                item("s8_path_b",
                     "Path B — Run it together: fractional operator alongside "
                     "{Second-in-command}; weekly working sessions plus on-site days; "
                     "90-day sprints with measurables; execution load carried, not just "
                     "advised."),
            ],
            builder.SCOPE: [
                item("s9_scope", "Scope — which map rows are in the first 90 days"),
                item("s9_start_date", "Start date"),
                item("s9_cadence", "Sprint length / check-in cadence"),
                item("s9_investment_range", "Investment range discussed ($/month × months)",
                     is_financial=True),
                item("s9_reaction_to_range", "Their reaction to the range", is_financial=True),
                item("s9_who_else", "Who else needs to weigh in, and by when"),
                item("s9_follow_up_call", "Follow-up call booked (date/time)"),
                item("s9_map_sent", "Strategy Map sent (same day) — time"),
                item("s9_proposal_due", "Proposal due date"),
            ],
        },
    }


# --------------------------------------------------------- 2. KPI entries

def kpi(key, page, name, kind, direction, cadence, rollup, guidance, feeds, **more):
    return {"key": key, "page": page, "name": name, "kind": kind, "direction": direction,
            "cadence": cadence, "rollup": rollup, "guidance": guidance, "feeds": feeds, **more}


#: The module's list, on top of the base library (`apps.scorecard.library`).
KPIS = [
    kpi("ops_first_time_fix", "operations", "First-time fix rate", "percent", "higher",
        "weekly", "average", "On track at 90% or more; behind within 5 points.",
        ["sheet", "track", "besty"], behind_band_pct=5),
    kpi("ops_schedule_adherence", "operations", "Schedule adherence", "percent", "higher",
        "weekly", "average", "On track at 95% of jobs started as scheduled; behind within 5%.",
        ["sheet", "track", "besty"], behind_band_pct=5),
    kpi("ops_backlog_weeks", "operations", "Backlog in weeks of work", "number", "range",
        "weekly", "last", "Healthy between 2 and 6 weeks; below is thin, above is late.",
        ["sheet"], range_low=2, range_high=6),
    kpi("ops_preventive_on_time", "operations", "Preventive maintenance done on time",
        "percent", "higher", "monthly", "average",
        "On track at 90% or more; behind within 10%.", ["sheet", "track"]),
    kpi("ops_quality_escapes", "operations", "Quality escapes to the customer", "count",
        "lower", "weekly", "sum", "On track at zero; any is worth a look.",
        ["sheet", "reviews"]),
    kpi("ops_throughput_per_hour", "operations", "Output per labor hour", "number", "higher",
        "weekly", "average", "Set the target from the last 13 weeks; behind within 10%.",
        ["sheet"]),
]


# ------------------------------------------------------------ 3. playbooks

DRAFT_NOTE = "Draft, edit before first use."

#: key -> (name, description, outline). The outline's grammar is
#: `apps.centers.playbooks`: "Goal:", "## project | weeks a-b", "- task |
#: week n | owner, second-in-command or practice".
PLAYBOOKS = {
    "ops_90_day_reset": (
        "The 90-day operations reset",
        "Discovery, a management cadence, the two biggest bottlenecks fixed, and a handover "
        "the second-in-command runs.",
        """Goal: The 90-day operations reset
Why: Find what is breaking, install a weekly rhythm, fix the two worst bottlenecks, and hand the running of it to the client's own leaders.

## Discovery | weeks 1-2
- Interview the owner | week 1 | practice
- Interview each member of the leadership team | week 1 | practice
- Pull the numbers: revenue, margin, jobs, overtime, backlog | week 1 | second-in-command
- Set the scorecard baseline | week 2 | practice
- Draw the org chart as it is today | week 2 | practice
- Name the three biggest bottlenecks | week 2 | practice

## Cadence | weeks 3-4
- Start the weekly leadership meeting | week 3 | practice
- Put the scorecard live and review it in the meeting | week 3 | second-in-command
- Write the quarterly priorities, each with one owner | week 4 | owner
- Ship the quick wins found in discovery | week 4 | second-in-command

## Fix the top two bottlenecks | weeks 5-8
- Map the process behind bottleneck one | week 5 | practice
- Write its SOP | week 6 | practice
- Name its owner | week 6 | owner
- Put its measure on the scorecard | week 6 | second-in-command
- Map the process behind bottleneck two | week 7 | practice
- Write its SOP | week 8 | practice
- Name its owner | week 8 | owner
- Put its measure on the scorecard | week 8 | second-in-command

## Handover | weeks 9-12
- The second-in-command runs the weekly leadership meeting | week 9 | second-in-command
- Review every measurable with the leadership team | week 10 | second-in-command
- Set next quarter's priorities | week 11 | owner
- The practice steps back a level: agree the new check-in rhythm | week 12 | practice
"""),
    "ops_management_cadence": (
        "Install the management cadence",
        "A weekly leadership meeting, a scorecard review, a monthly close and quarterly "
        "planning.",
        """Goal: Install the management cadence
Why: The business runs on a rhythm the leaders keep without the practice in the room.

## The weekly leadership meeting | weeks 1-4
- Agree the agenda, the time and who attends | week 1 | practice
- Run the first meeting together | week 1 | practice
- The second-in-command runs it, the practice watches | week 3 | second-in-command
- Review how it went and tighten it | week 4 | practice

## The scorecard review | weeks 1-4
- Choose the 5 to 15 numbers the week is run on | week 1 | owner
- Name who enters each number and by when | week 2 | second-in-command
- Review the scorecard in every weekly meeting | week 4 | second-in-command

## The monthly close | weeks 3-6
- Set the close checklist and its dates | week 3 | practice
- Hold the first month-end review of the numbers | week 5 | owner
- Write down what changes next month | week 6 | second-in-command

## Quarterly planning | weeks 9-12
- Book the quarterly planning day | week 9 | owner
- Review last quarter's priorities: done or not done | week 12 | second-in-command
- Set next quarter's priorities, each with one owner | week 12 | owner
"""),
    "ops_owner_steps_away": (
        "Owner steps away from the day to day",
        "A decisions inventory, a delegation plan, a bi-weekly accountability meeting with "
        "senior leaders and a 60-day test.",
        """Goal: The owner steps away from the day to day
Why: Decisions get made without the owner, and the owner's time goes to what only the owner can do.

## Decisions inventory | weeks 1-2
- List every decision the owner makes in a normal month | week 1 | owner
- Sort each: keep, delegate, or stop making | week 2 | practice

## Delegation plan | weeks 3-4
- Name who takes each delegated decision | week 3 | owner
- Write the limits for each: money, risk, when to ask | week 3 | practice
- Tell the team who decides what from now on | week 4 | owner

## Accountability meeting | weeks 3-8
- Start a bi-weekly accountability meeting with the senior leaders | week 3 | practice
- The senior leaders report on their delegated decisions | week 5 | second-in-command
- Review what came back to the owner and why | week 7 | practice

## The 60-day test | weeks 5-12
- The owner stays out of the delegated decisions for 60 days | week 5 | owner
- Review the test at the halfway mark | week 8 | practice
- Decide what stays delegated for good | week 12 | owner
"""),
    "ops_sop_sprint": (
        "Process mapping and SOP sprint",
        "Pick five processes; map, write, assign and measure each.",
        """Goal: Five core processes mapped and written down
Why: The work is done the same way whoever does it, and new people learn it from a page.

## Pick the five | week 1
- List the processes that break most or cost most when they do | week 1 | practice
- Choose five with the leadership team | week 1 | owner

## Map | weeks 2-3
- Map processes one to three as they are done today | week 2 | practice
- Map processes four and five | week 3 | practice

## Write | weeks 3-5
- Write the SOPs for processes one to three | week 4 | practice
- Write the SOPs for processes four and five | week 5 | practice

## Assign | week 6
- Name one owner for each process | week 6 | owner
- Train the people who do the work | week 6 | second-in-command

## Measure | weeks 6-8
- Put one measure for each process on the scorecard | week 6 | second-in-command
- Review the first month of measures | week 8 | practice
"""),
    "ops_software_consolidation": (
        "Software consolidation",
        "An inventory, then a phased replace, test and train for each tool, with a success "
        "standard for each phase.",
        """Goal: Fewer tools, each used properly
Why: Less paid for, less copied between systems, and one place to look for each answer.

## Inventory | weeks 1-2
- List every tool, what it costs and who uses it | week 1 | second-in-command
- Note what lives in someone's head or a spreadsheet instead | week 1 | practice
- Choose what to keep, replace and retire | week 2 | owner

## Phase one: the first tool | weeks 3-6
- Write the success standard for this phase | week 3 | practice
- Replace the tool and move its data | week 4 | second-in-command
- Test it with the people who use it | week 5 | second-in-command
- Train everyone and retire the old tool | week 6 | practice

## Phase two: the next tool | weeks 7-10
- Write the success standard for this phase | week 7 | practice
- Replace, test and train | week 9 | second-in-command
- Retire the old tool | week 10 | second-in-command

## Close out | weeks 11-12
- Check each phase against its standard | week 11 | practice
- Cancel the retired subscriptions | week 12 | owner
"""),
    "ops_hiring_round": (
        "A hiring round",
        "A role scorecard, the posting, screening, interviews, the offer and a 90-day plan.",
        """Goal: The right person hired into the role
Why: A role filled by someone who fits it, with a plan for their first 90 days.

## The role | week 1
- Write the role scorecard: purpose, outcomes, skills | week 1 | practice
- Agree the pay range and who decides | week 1 | owner

## Find | weeks 2-3
- Write and post the role | week 2 | second-in-command
- Screen the applicants against the scorecard | week 3 | second-in-command

## Choose | weeks 4-5
- Hold the first interviews | week 4 | second-in-command
- Hold the final interviews with the owner | week 5 | owner
- Check references | week 5 | practice

## Offer and start | weeks 6-8
- Make the offer | week 6 | owner
- Write the 90-day plan for the new hire | week 7 | practice
- First day: the plan walked through with them | week 8 | second-in-command
"""),
}


# ------------------------------------------------- 4. document templates

#: Document templates (Settings → Documents): original key -> (name, title, body).
DOCUMENTS = {
    "ops_sop": (
        "SOP",
        "Standard operating procedure",
        "Prepared for {Company} by {FractionalName}, {PracticeName}, on {Today}\n\n"
        "# Purpose\nWhat this procedure is for, and what goes wrong without it.\n\n"
        "# Roles\nWho does each part, and who owns the procedure.\n\n"
        "# Steps\n1. \n2. \n3. \n\n"
        "# Measures\nThe number that says it is working, and where it is on the "
        "scorecard.\n\n"
        "# Review date\nWhen the owner reads this again and updates it.",
    ),
    "ops_weekly_note": (
        "Weekly note",
        "Weekly note",
        "{Company}, week of {Today}\n\n"
        "# What went well\n\n"
        "# What needs attention\n\n"
        "# The numbers\nThe scorecard's week, in a sentence or two.\n\n"
        "# What happens next\n\n"
        "{FractionalName}\n{PracticeName}",
    ),
    "ops_quarterly_review": (
        "Quarterly review",
        "Quarterly review",
        "Prepared for {FirstName} {LastName}, {Company}\n"
        "Prepared by {FractionalName}, {PracticeName}, on {Today}\n\n"
        "# The quarter in brief\n\n"
        "# Quarterly priorities: done and not done\n\n"
        "# The scorecard over the quarter\n\n"
        "# What we fixed\n\n"
        "# Next quarter's priorities\n\n"
        "# What we need from you",
    ),
}

#: Email templates (Settings → Email templates): original key -> (name, subject, body).
EMAILS = {
    "ops_weekly_note_email": (
        "Weekly note (Operations)",
        "This week at {Company}",
        "Hi {FirstName},\n\n"
        "What went well this week:\n\n"
        "What needs attention:\n\n"
        "What happens next:\n",
    ),
}


# ------------------------------------------------ 5–7. tools, feeds, AI

#: The coming tools (the worksheet engine is next), by name only.
#: P12: the four tools, built (`apps.tools.shipped`), named as they ship.
TOOLS = ["Bottleneck finder", "Capacity model", "Meeting cadence builder", "Org chart by seat"]

#: Recommended feeds, shown first in a company's feed picker when the module
#: is on: KPI feed codes (`scorecard.Kpi.Feed`), and bank feeds, which feed
#: the practice's books rather than a KPI.
FEEDS = ["sheet", "track", "besty", "hubspot", "reviews", "bank"]
FEED_NAMES = {"sheet": "Google Sheets", "track": "Track", "besty": "Besty",
              "hubspot": "HubSpot", "reviews": "Google reviews", "bank": "Bank feeds"}

#: The module's AI actions (`apps.tenancy.ai_actions`, `center="operations"`).
AI_ACTIONS = ["ops_sop_from_note", "ops_map_rows_from_meeting", "ops_weekly_note"]
