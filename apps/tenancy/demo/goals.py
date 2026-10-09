"""What each client is working on: the goals, the number each is measured by,
and the projects and tasks under it. Fiction, written to read like a
practice's real work. `work.py` turns it into goals, readings, milestones,
projects and tasks with dates.

Each goal: the company, its title, the measurable, unit, baseline, target,
which way is good, the months after the engagement began that it started,
how far along it is (0 to 1), and its projects. Each task carries the line
the client read when it was finished.
"""

from __future__ import annotations


def goal(company, title, measurable, unit, baseline, target, good, after, progress,
         projects, **more):
    return {"company": company, "title": title, "measurable": measurable, "unit": unit,
            "baseline": baseline, "target": target, "good": good, "after": after,
            "progress": progress, "projects": projects, **more}


GOALS = [
    # ---------------------------------------------------------- Acme Fasteners
    goal("Acme Fasteners", "Ship on time, every time", "Orders shipped on the promised date",
         "%", 71, 95, "up", 0, 0.92, [
             ("One promise date the plant believes", [
                 ("Find where promise dates come from today",
                  "Three people were quoting dates from three different lists. Now there is one."),
                 ("Build the capacity board for the two header lines",
                  "The board is on the wall by the dock and is updated at 7 each morning."),
                 ("Sales quotes from the board, not from memory",
                  "Every quote this month used the board's date. None had to be walked back."),
             ]),
             ("A daily look at what is late", [
                 ("Start the ten-minute late-order huddle",
                  "The huddle has run every day for six weeks. Late orders are down by half."),
                 ("Give each late order one owner",
                  "Each late order now has a name next to it and a new date by noon."),
                 ("Review the month's misses with Marvin",
                  "Four misses in the month, all traced to one supplier. Purchasing has it."),
                 ("Agree the rule for expediting an order", ""),
             ]),
         ]),
    goal("Acme Fasteners", "Cut scrap on the header line", "Scrap as a share of material",
         "%", 6.8, 3.0, "down", 4, 0.7, [
             ("Know where the scrap comes from", [
                 ("Weigh and tag scrap by shift for two weeks",
                  "Two weeks of tags are in. Second shift makes 60% of the scrap."),
                 ("Chart scrap by cause", "Die changeovers cause more scrap than everything else together."),
                 ("Walk the findings with both shift leads",
                  "Both leads have seen the numbers and agree on where to start."),
             ]),
             ("A changeover that is the same every time", [
                 ("Film three changeovers and time each step",
                  "The slowest changeover took 52 minutes; the fastest 23. The steps are the same."),
                 ("Write the one-page changeover standard", "The standard is at each machine, with photos."),
                 ("Train second shift on the standard", ""),
                 ("Audit ten changeovers against it", ""),
             ]),
         ], overdue=1),
    goal("Acme Fasteners", "A second shift that runs without Wiley",
         "Hours a week Wiley spends on the floor after 5 pm", "hours", 30, 8, "down", 8, 0.45, [
             ("A shift lead who can decide", [
                 ("List the calls Wiley gets after 5 pm",
                  "Forty calls in a month. Thirty of them are the same six questions."),
                 ("Write the answers to the six questions",
                  "The six answers are in the lead's binder and on the shift board."),
                 ("Name the second-shift lead and agree what is theirs", ""),
             ]),
             ("A handover that takes ten minutes", [
                 ("Design the shift handover sheet", "First and second shift now hand over on one sheet."),
                 ("Run the handover for a month and fix what is missed", ""),
             ]),
         ], paused=True),

    # -------------------------------------------------------- Wayne Industries
    goal("Wayne Industries", "Close the month in five days", "Working days to close the books",
         "days", 14, 5, "down", 0, 1.0, [
             ("A close calendar everyone can see", [
                 ("Map the close as it runs today",
                  "The close had 61 steps across four sites. Nineteen were waiting on someone."),
                 ("Publish the close calendar with an owner for each step",
                  "Every step has a name and a day. It is on the shared calendar."),
                 ("Move accruals to a standing schedule",
                  "Recurring accruals now post on day one without anyone asking."),
             ]),
             ("Sites that report the same way", [
                 ("Agree one chart of accounts across the four sites",
                  "All four sites closed on the same chart of accounts for the first time."),
                 ("Train the site controllers on the day-two checklist",
                  "The site controllers ran the checklist themselves this month."),
                 ("Hold a ten-minute review after each close",
                  "Three closes in a row at five days. The review is now Lucius's to run."),
             ]),
         ], resolved=("achieved", "Three consecutive closes at five working days. Lucius "
                                  "runs the calendar now, and it no longer needs us.")),
    goal("Wayne Industries", "One operating rhythm across four sites",
         "Sites running the weekly scorecard meeting", "sites", 0, 4, "up", 3, 0.75, [
             ("A scorecard worth meeting about", [
                 ("Choose the eight numbers with the site leads",
                  "Eight numbers, agreed by all four sites. Nobody argued for a ninth."),
                 ("Build the scorecard and fill it for four weeks",
                  "Four weeks of numbers are in. Two sites had never seen their own overtime."),
                 ("Set a target and an owner for each number",
                  "Each number has a target and a name."),
             ]),
             ("The weekly meeting, site by site", [
                 ("Run the meeting at Gotham Central with Lucius",
                  "Gotham Central has met nine weeks running. It ends on time."),
                 ("Bring Bludhaven and Metropolis onto the same agenda",
                  "Both sites are meeting weekly. Metropolis solved its dock backlog in the room."),
                 ("Start the meeting at the Arkham Road plant", ""),
                 ("Hand each meeting to its site lead", ""),
             ]),
         ]),
    goal("Wayne Industries", "Fewer recordable incidents", "Recordable incidents per quarter",
         "incidents", 9, 3, "down", 9, 0.5, [
             ("Find the pattern", [
                 ("Review two years of incident reports",
                  "Most incidents happen in the first hour of a shift, at two of the four sites."),
                 ("Walk the first hour at both sites", "Both walks are done. The start-up checks are skipped when the line is behind."),
             ]),
             ("A start of shift that is never skipped", [
                 ("Write the five-minute start-up check with the crews", "The crews wrote the check themselves. It is five items."),
                 ("Make the check part of the weekly scorecard", ""),
                 ("Alfred to confirm budget for guarding on line 3", ""),
             ]),
         ], waiting=1),

    # -------------------------------------------------------- Globex Logistics
    goal("Globex Logistics", "Trucks leave full", "Average load factor", "%", 68, 85, "up",
         0, 0.8, [
             ("See every load before it leaves", [
                 ("Pull six months of load data by lane",
                  "Three lanes run at under 55% full. They carry a third of the miles."),
                 ("Build the daily load board", "Dispatch sees tomorrow's loads by 2 pm today."),
                 ("Set a floor: no truck leaves under 70% without a reason",
                  "Eleven trucks left under 70% this month, each with a reason written down."),
             ]),
             ("Fill the three thin lanes", [
                 ("Offer backhaul rates on the Cypress Creek lane",
                  "Two shippers took the backhaul rate. That lane is at 74%."),
                 ("Combine the Tuesday and Wednesday coastal runs",
                  "The combined run has gone out four weeks in a row, full."),
                 ("Review the thin-lane pricing with Hank", ""),
             ]),
         ], overdue=1),
    goal("Globex Logistics", "Dispatch that does not depend on one person",
         "Dispatch decisions sent up to Hank each week", "decisions", 40, 5, "down", 7, 0.55, [
             ("Write down how dispatch decides", [
                 ("Sit with dispatch for three days and note every call",
                  "Three days, 212 decisions. Nine in ten follow five rules nobody had written."),
                 ("Write the five rules and test them on last month",
                  "The five rules would have decided 188 of last month's 212 calls."),
             ]),
             ("A second dispatcher who can run a day", [
                 ("Choose and train the backup dispatcher", "The backup ran two full days with no calls to Hank."),
                 ("Frank to sign off the escalation list", ""),
                 ("Backup runs a full week alone", ""),
             ]),
         ], waiting=1),

    # -------------------------------------------------------- Initech Software
    goal("Initech Software", "Collect what we bill", "Days sales outstanding", "days", 63, 40,
         "down", 0, 0.85, [
             ("Invoices that go out right the first time", [
                 ("Find why invoices are sent back",
                  "One in five invoices was disputed. Most were missing the purchase order number."),
                 ("Add the purchase order check before sending",
                  "No invoice left without a purchase order number this month."),
                 ("Send invoices on the day the work is accepted",
                  "Invoices now go out the same day. It used to take eleven."),
             ]),
             ("A collections rhythm", [
                 ("Set the 30, 45 and 60 day follow-up script",
                  "Milton has the three scripts and has used each of them."),
                 ("Weekly aging review, fifteen minutes",
                  "The review has run eight weeks. Over-60 balances are down by two thirds."),
                 ("Agree when an account goes on hold", ""),
             ]),
         ]),
    goal("Initech Software", "Stop redoing the status reports", "Status reports redone each month",
         "reports", 22, 5, "down", 5, 0.4, [
             ("One cover sheet, one template", [
                 ("Collect every version of the report in use", "There were eight versions. Two were over five years old."),
                 ("Agree one template with the eight managers", "Six of eight managers signed off the template."),
                 ("Retire the old cover sheets", ""),
             ]),
             ("Fewer reports, read by someone", [
                 ("Ask each reader what they use the report for", ""),
             ]),
         ], resolved=("changed_course", "The reports are being replaced by the new project "
                                        "dashboard in the first quarter, so fixing them is "
                                        "wasted effort. Bill agreed to put the time into "
                                        "collections instead.")),

    # -------------------------------------------------- Pied Piper Compression
    goal("Pied Piper Compression", "Onboard a customer in ten days",
         "Days from signed contract to live", "days", 34, 10, "down", 0, 0.8, [
             ("One onboarding path", [
                 ("Map the last ten onboardings, step by step",
                  "No two of the ten followed the same order. The fastest took 12 days."),
                 ("Write the ten-day onboarding plan",
                  "The plan is one page. Each day has an owner on our side and theirs."),
                 ("Run it with the next three customers",
                  "Three customers through: 13, 11 and 10 days."),
             ]),
             ("Nothing waits on Richard", [
                 ("List the onboarding steps only Richard can do",
                  "Seven steps waited on Richard. Five did not need to."),
                 ("Hand the five steps to Jared's team",
                  "Jared's team has run the five steps for a month without a question."),
                 ("Automate the environment setup request", ""),
             ]),
         ]),
    goal("Pied Piper Compression", "Support that answers the same day",
         "Hours to a first response", "hours", 19, 4, "down", 6, 0.6, [
             ("Know what is being asked", [
                 ("Tag a month of tickets by cause",
                  "Four causes make up 70% of tickets. Two are missing documentation."),
                 ("Write the two missing help articles", "Both articles are live. Those tickets fell by a third."),
             ]),
             ("A queue with an owner each day", [
                 ("Set the daily support rota", "The rota has been kept for five weeks."),
                 ("Agree the response promise by severity", ""),
                 ("Review the queue every Monday with Jared", ""),
             ]),
         ]),

    # -------------------------------------------------------- Stark Tool & Die
    goal("Stark Tool & Die", "Quote in 48 hours", "Hours from request to quote", "hours",
         120, 48, "down", 0, 0.85, [
             ("A price book the estimators trust", [
                 ("Pull the last 200 quotes and what the jobs really cost",
                  "Quotes were within 10% of cost on two jobs in three. The misses were all tooling."),
                 ("Build the price book for the common jobs",
                  "The price book covers the forty jobs that make up most requests."),
                 ("Estimators quote from the book for a month",
                  "Average time to quote is 53 hours, down from 120."),
             ]),
             ("Requests that arrive complete", [
                 ("Write the request form with the three biggest customers",
                  "The three biggest customers use the form. Their quotes take a day."),
                 ("Send incomplete requests back the same day",
                  "Incomplete requests go back within four hours, with what is missing."),
                 ("Happy to review the one-off pricing rule", ""),
             ]),
         ], waiting=1),
    goal("Stark Tool & Die", "Machine uptime above 90%", "Uptime on the five CNC machines",
         "%", 78, 90, "up", 5, 0.6, [
             ("Know why machines stop", [
                 ("Log every stop over ten minutes for a month",
                  "A month of stops logged. Waiting for material beats breakdowns two to one."),
                 ("Rank the causes with the floor leads", "The floor leads ranked the causes. Material staging is first."),
             ]),
             ("Material at the machine before the job", [
                 ("Stage tomorrow's material by 3 pm", "Staging has been done by 3 pm on 18 of the last 20 days."),
                 ("Add a preventive maintenance hour each Friday", ""),
                 ("Review uptime weekly on the scorecard", ""),
             ]),
         ], overdue=1),

    # ------------------------------------------------------ Hooli Field Services
    goal("Hooli Field Services", "Fix it on the first visit", "Jobs fixed on the first visit",
         "%", 61, 85, "up", 0, 0.75, [
             ("The right part on the truck", [
                 ("Find the ten parts behind most return visits",
                  "Ten parts account for 58% of return visits."),
                 ("Set a standard truck stock with the lead technicians",
                  "Every truck now carries the ten parts. The list is checked on Mondays."),
                 ("Restock from the job ticket, not from memory",
                  "Restocking is driven by tickets. Stock-outs fell from 31 to 9 in a month."),
             ]),
             ("A better call before the visit", [
                 ("Write the five questions dispatch asks every caller",
                  "Dispatch asks the five questions on every call. Technicians arrive knowing the model."),
                 ("Send the answers to the technician's phone", ""),
                 ("Review return visits weekly with the leads", ""),
             ]),
         ]),
    goal("Hooli Field Services", "Technician turnover under 15%",
         "Technician turnover, trailing twelve months", "%", 38, 15, "down", 4, 0.5, [
             ("Know why technicians leave", [
                 ("Interview the last twelve who left",
                  "Nine of twelve left in their first year. Seven named the on-call schedule."),
                 ("Share what was heard with Gavin", "Gavin has the findings and agreed to change the on-call rota."),
             ]),
             ("A first year people stay through", [
                 ("Redesign the on-call rota", "The new rota halves weekend call-outs for first-year technicians."),
                 ("Pair each new technician with a lead for 90 days", ""),
                 ("Denpok to approve the retention bonus", ""),
             ]),
         ], waiting=1),

    # ---------------------------------------------------- Dunder Mifflin Paper
    goal("Dunder Mifflin Paper", "Deliver the next day", "Orders delivered the next day", "%",
         54, 90, "up", 0, 0.7, [
             ("Orders in by 3, out by 8", [
                 ("Time an order from phone call to truck",
                  "An order waits five hours between the sales desk and the warehouse."),
                 ("Move order entry to the moment of the call",
                  "Orders are entered while the customer is on the phone."),
                 ("Set the 3 pm cut-off and tell the customers",
                  "The cut-off is in place. Eight in ten orders now make the morning truck."),
             ]),
             ("Routes that make sense", [
                 ("Redraw the four delivery routes", "The new routes save 40 miles a day."),
                 ("Dwight to walk the warehouse pick path", ""),
                 ("Review late deliveries every Friday", ""),
             ]),
         ], overdue=1, waiting=1),

    # ------------------------------------------------- Vandelay Import-Export
    goal("Vandelay Import-Export", "Know what is in the warehouse", "Inventory accuracy", "%",
         82, 98, "up", 0, 0.65, [
             ("Count what matters, every week", [
                 ("Rank the items by value and movement",
                  "A fifth of the items are four fifths of the value."),
                 ("Start weekly cycle counts on the top fifth",
                  "Six weekly counts done. Accuracy on the top items is 96%."),
                 ("Fix the three causes the counts keep finding",
                  "Two of the three causes are fixed: mislabelled bins and unrecorded samples."),
             ]),
             ("A place for everything", [
                 ("Label every bin and aisle", "Every bin has a label that matches the system."),
                 ("Receive against the purchase order, at the dock", ""),
                 ("George to clear the returns cage", ""),
             ]),
         ], waiting=1),
    goal("Vandelay Import-Export", "Customs paperwork right the first time",
         "Shipments held at customs each month", "shipments", 7, 1, "down", 3, 0.5, [
             ("One checklist per shipment", [
                 ("Review the last twenty holds with the broker",
                  "Fourteen of twenty holds were a missing or wrong classification code."),
                 ("Build the pre-shipment checklist", "The checklist is in use on every shipment."),
             ]),
             ("Codes that are right at the source", [
                 ("Add classification codes to the item master", ""),
                 ("Agree a monthly review with the broker", ""),
             ]),
         ]),

    # ------------------------------------------------------ Cyberdyne Robotics
    goal("Cyberdyne Robotics", "Pass the safety audit", "Open audit findings", "findings", 31,
         0, "down", 0, 0.7, [
             ("Close the findings in order of risk", [
                 ("Rank the 31 findings with Sarah",
                  "Nine findings are high risk. All nine have an owner and a date."),
                 ("Close the nine high-risk findings",
                  "All nine high-risk findings are closed and photographed."),
                 ("Close the lockout and guarding findings",
                  "Lockout stations are installed on every cell."),
             ]),
             ("Keep them closed", [
                 ("Start the monthly safety walk", "Two safety walks done. Each found two things, fixed the same week."),
                 ("Add findings to the weekly scorecard", ""),
                 ("Book the re-audit", ""),
             ]),
         ], overdue=1),
    goal("Cyberdyne Robotics", "A production plan people trust", "Schedule attainment", "%",
         64, 90, "up", 2, 0.45, [
             ("A plan made from real capacity", [
                 ("Measure real cycle times on the three cells",
                  "Real cycle times are 20% longer than the plan assumed."),
                 ("Rebuild the weekly plan from measured times", "The plan was rebuilt. Attainment rose to 76% in two weeks."),
             ]),
             ("A daily check on the plan", [
                 ("Start the 8 am production meeting", ""),
                 ("Miles to decide the rule for rush orders", ""),
             ]),
         ], waiting=1),

    # ------------------------------------------------- Sterling Cooper Creative
    goal("Sterling Cooper Creative", "Jobs delivered on budget", "Jobs finished within the estimate",
         "%", 48, 85, "up", 0, 0.45, [
             ("Estimates built from what jobs cost", [
                 ("Compare estimates with actual hours on thirty jobs",
                  "Creative hours are estimated well. Revisions are not estimated at all."),
                 ("Add revision rounds to every estimate",
                  "Every estimate now states two revision rounds and the price of a third."),
                 ("Joan to load the new estimate template", ""),
             ]),
             ("See a job going over before it does", [
                 ("Weekly hours-against-estimate report", "The report goes to each account lead on Monday."),
                 ("Agree who can approve extra hours", ""),
                 ("Review the month's overruns with Don", ""),
             ]),
         ], waiting=1),
]

#: Milestones every goal has, as (title pattern, share of the way to the
#: target date). `{first}` and `{second}` are the goal's two project titles.
MILESTONES = [
    ("Baseline measured and agreed", 0.06),
    ("{first}: in daily use", 0.40),
    ("{second}: in daily use", 0.72),
    ("Target held for a month", 1.0),
]

#: Work the practice does for itself: (title, who, days from today, status).
INTERNAL = [
    ("Book travel for the Tucson on-site", "pam", 2, "in_progress"),
    ("Collect a W-9 from Aviato Web Studio", "pam", -3, "in_progress"),
    ("Update the partner list after the owners' breakfast", "radar", 4, "not_started"),
    ("Send the scorecard reminders for Monday", "radar", 1, "not_started"),
    ("File the signed engagement letter for Sterling Cooper", "pam", -12, "done"),
    ("Confirm the room for the quarterly planning day", "radar", 6, "in_progress"),
]
