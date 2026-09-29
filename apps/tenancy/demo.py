"""The demo practice (owner, 2026-09-29): what demo.getexecutivesnow.com shows.

A plausible fractional operations practice, **entirely fictional**: three
client companies with goals, projects and tasks moving; digests waiting for
approval; prospects in the pipeline; one strategy session run end to end with
its PDF; and a meeting queue with proposals to review. Every address is at
`.example`, a reserved domain that cannot receive mail, and the demo sends
nothing anyway (config/environment.py).

Built through the app's own code wherever a person's action would have made
the thing (tasks and their updates, stage changes, digests, the strategy
session, meeting proposals), so the demo shows what the app really produces
rather than rows arranged to look like it. Dates are relative to the day it
is seeded.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.utils import timezone

PRACTICE = "Summit Operations Partners"
SLUG = "summit-demo"

CLIENTS = [
    {
        "company": "Northwind Facility Services",
        "people": [("Dana", "Reyes", "COO", "dana.reyes@northwind.example"),
                   ("Priya", "Shah", "Operations lead", "priya.shah@northwind.example")],
        "goal": ("Cut missed inspections to zero by year end",
                 "Missed inspections per month", Decimal("14"), Decimal("0"), "decrease"),
        "projects": [
            ("Rebuild the inspection checklist", [
                ("Audit last quarter's missed inspections", "done",
                 "Found the pattern: 9 of 14 misses were weekend sites with no named lead."),
                ("Draft the new checklist with site leads", "in_progress",
                 "First draft is with the site leads for comment."),
                ("Train weekend crews on the checklist", "not_started", ""),
            ]),
            ("Weekly dispatch review", [
                ("Set up the Monday dispatch huddle", "done",
                 "The huddle ran twice; overtime calls are down already."),
                ("Agree escalation rules for no-shows", "waiting_on_client", ""),
            ]),
        ],
    },
    {
        "company": "Bluebird HVAC",
        "people": [("Marcus", "Lee", "Owner", "marcus@bluebird.example"),
                   ("Jen", "Ortiz", "Dispatch manager", "jen.ortiz@bluebird.example")],
        "goal": ("Grow maintenance agreements to 400 households",
                 "Active maintenance agreements", Decimal("260"), Decimal("400"), "increase"),
        "projects": [
            ("Renewal reminders that go out on time", [
                ("Map every agreement's renewal date", "done",
                 "All 260 agreements now have a renewal date on file."),
                ("Write the 30-day renewal script", "in_progress",
                 "Script drafted; testing it with two technicians this week."),
            ]),
            ("Technician-led upsell", [
                ("Choose the three offers techs can make on site", "blocked", ""),
                ("Pilot with the east-side crew", "not_started", ""),
            ]),
        ],
    },
    {
        "company": "Cedar Ridge Landscaping",
        "people": [("Tom", "Okafor", "Founder", "tom@cedarridge.example")],
        "goal": ("Get the founder out of daily scheduling",
                 "Hours a week the founder spends scheduling", Decimal("12"), Decimal("2"),
                 "decrease"),
        "projects": [
            ("Hand scheduling to the office manager", [
                ("Write down how the schedule is really built", "done",
                 "Tom's rules are written down: weather, crew skills, travel time."),
                ("Office manager runs the schedule with Tom watching", "in_progress",
                 "Two weeks run with Tom watching; only one change needed."),
                ("Tom stops touching the schedule", "not_started", ""),
            ]),
        ],
    },
]

PROSPECTS = [
    ("Brianna", "Castillo", "Owner", "brianna@castillocleaning.example",
     "Castillo Commercial Cleaning", "consult_given"),
    ("Owen", "Hart", "General manager", "owen.hart@hartplumbing.example",
     "Hart & Sons Plumbing", "qualified"),
    ("Lena", "Moreau", "Founder", "lena@moreaubakery.example",
     "Moreau Bakery Group", "prospecting"),
]


def reset_database() -> int:
    """Empty every table the app has, so a re-run starts clean. Demo only —
    the command that calls this refuses anywhere else."""
    tables = [t for t in connection.introspection.table_names()
              if t != "django_migrations"]
    with connection.cursor() as cursor:
        # Django's foreign keys are deferred; Postgres will not truncate a
        # table with checks still pending in this transaction.
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute("TRUNCATE " + ", ".join(f'"{t}"' for t in tables)
                       + " RESTART IDENTITY CASCADE")
    return len(tables)


def build(*, ff_email: str, ff_name: str) -> dict:
    from apps.accounts.models import User
    from apps.crm.seed import seed_tenant as seed_crm
    from apps.strategy.seed import seed_tenant as seed_strategy
    from apps.tenancy.context import tenant_context
    from apps.tenancy.models import Membership, Role, Tenant

    tenant = Tenant.objects.create(
        name=PRACTICE, slug=SLUG, timezone="America/Denver",
        from_address="hello@summitops.example", hold_all_digests=True,
        # No Claude in the demo's own content: its prose is deterministic.
        digest_ai_prose_default=False, ai_unattended_daily_cap_usd=Decimal("0"),
        email_display_name=PRACTICE)
    counts: dict[str, int] = {}
    with tenant_context(tenant.pk):
        seed_crm(tenant)
        template = seed_strategy(tenant)
        ff_user = User.objects.create(email=ff_email.strip().lower(), full_name=ff_name)
        va_user = User.objects.create(email="riley.chen@summitops.example",
                                      full_name="Riley Chen")
        Membership.objects.create(tenant=tenant, user=ff_user, role=Role.FF)
        Membership.objects.create(tenant=tenant, user=va_user, role=Role.VA)
        counts["clients"] = _clients(tenant, ff_user)
        counts["prospects"] = _prospects(tenant, ff_user)
        counts["digests"] = _digests(tenant)
        counts["strategy_sessions"] = _strategy_session(tenant, template, ff_user)
        counts["meeting_proposals"] = _meeting_queue(tenant, ff_user)
    return {"tenant": tenant, **counts}


def _person(tenant, company, first, last, title, email):
    from apps.crm.models import Contact, ContactEmail

    contact = Contact.objects.create(tenant=tenant, first_name=first, last_name=last,
                                     title=title, company=company, source="demo")
    ContactEmail.objects.create(tenant=tenant, contact=contact, address=email,
                                is_primary=True)
    return contact


def _stage(contact, code):
    from apps.crm.models import PipelineStage
    from apps.crm.services import pipeline

    stage = PipelineStage.objects.get(pipeline=pipeline.sales_pipeline(contact.tenant),
                                      code=code)
    pipeline.change_stage(contact, stage, reason="demo", run_automations=False)


def _clients(tenant, ff_user) -> int:
    from apps.crm.models import Company
    from apps.crm.services import referral
    from apps.work import services as work
    from apps.work.models import Cadence, Goal, Project, Stakeholder

    today = timezone.localdate()
    for index, spec in enumerate(CLIENTS):
        company = Company.objects.create(tenant=tenant, name=spec["company"],
                                         is_client_company=True, seat_count=3,
                                         digest_ai_prose=False)
        people = [_person(tenant, company, *p) for p in spec["people"]]
        for person in people:
            referral.add_type(person, "client", onboard=False)
        _stage(people[0], "closed_won")

        title, measurable, baseline, target, direction = spec["goal"]
        goal = Goal.objects.create(
            tenant=tenant, title=title, client_company=company, owner=ff_user,
            client_owner_contact=people[0], target_date=today + timedelta(days=90),
            measurable=measurable, baseline_value=baseline, target_value=target,
            baseline_at=today - timedelta(days=30), direction=direction, horizon_days=90)
        Stakeholder.objects.create(tenant=tenant, contact=people[0], goal=goal,
                                   cadence=Cadence.WEEKLY)
        for p_index, (p_title, tasks) in enumerate(spec["projects"]):
            project = Project.objects.create(
                tenant=tenant, title=p_title, goal=goal, client_company=company,
                owner=ff_user, start_date=today - timedelta(days=21),
                target_date=today + timedelta(days=30 * (p_index + 1)))
            for t_index, (t_title, status, line) in enumerate(tasks):
                task = work.create_task(
                    tenant=tenant, actor=ff_user, role="FF", title=t_title,
                    project=project, client_company=company, owner=ff_user,
                    due_date=today + timedelta(days=7 * (t_index + 1) - 10 * (status == "done")))
                if status != "not_started":
                    work.apply_task_changes(task, actor=ff_user, role="FF",
                                            changes={"status": status},
                                            client_facing_line=line)
        if index == 0 and len(people) > 1:
            # A second person who follows every update, for the other cadence.
            Stakeholder.objects.create(tenant=tenant, contact=people[1], goal=goal,
                                       cadence=Cadence.EVERY_UPDATE)
    return len(CLIENTS)


def _prospects(tenant, ff_user) -> int:
    from apps.crm.models import Company, ServiceCategory, ContactServiceCategory
    from apps.crm.services import referral

    for first, last, title, email, company_name, stage in PROSPECTS:
        company = Company.objects.create(tenant=tenant, name=company_name)
        contact = _person(tenant, company, first, last, title, email)
        referral.add_type(contact, "prospect", onboard=False)
        _stage(contact, stage)
    partner = _person(tenant, None, "Sam", "Whitaker", "CPA", "sam@whitakercpa.example")
    referral.add_type(partner, "referral_partner", onboard=False)
    vendor = _person(tenant, None, "Ava", "Lindqvist", "Owner", "ava@clearlinecomms.example")
    referral.add_type(vendor, "vendor", onboard=False)
    category = ServiceCategory.objects.create(tenant=tenant, name="Phone systems")
    ContactServiceCategory.objects.create(tenant=tenant, contact=vendor,
                                          service_category=category)
    return len(PROSPECTS)


def _digests(tenant) -> int:
    """Digests waiting for the FF's approval, generated the way the Thursday
    run makes them, from the week's real updates."""
    from apps.work import digests
    from apps.work.models import Cadence, Stakeholder

    now = timezone.now()
    made = 0
    for row in Stakeholder.objects.filter(cadence=Cadence.WEEKLY).select_related("contact"):
        window = digests.next_window(tenant, Cadence.WEEKLY, now)
        start, end = digests.period_for(tenant, Cadence.WEEKLY, window)
        if digests.generate(tenant=tenant, contact=row.contact, cadence=Cadence.WEEKLY,
                            period_start=start, period_end=end, send_window_at=window,
                            until=now):
            made += 1
    return made


def _strategy_session(tenant, template, ff_user) -> int:
    from apps.crm.models import Contact
    from apps.strategy import pdf as pdf_service
    from apps.strategy import services
    from apps.strategy.models import (
        StrategyAnswer, StrategyMapRow, StrategyPathNote, StrategySession,
    )

    contact = Contact.objects.get(first_name="Brianna", last_name="Castillo")
    session = services.start(tenant=tenant, contact=contact, template=template,
                             owner=ff_user, company=contact.company,
                             scheduled_at=timezone.now() - timedelta(days=1))
    by = StrategyAnswer.AnsweredBy.FRACTIONAL

    def answer(key, value):
        services.save_answer(session, question_key=key, value=value, answered_by=by)

    answer("s1_revenue", {"text": "$3.1m last year, $3.6m this year"})
    answer("s1_team", {"text": "48 cleaners, 5 supervisors"})
    answer("s1_sites", {"text": "62 contracted buildings"})
    for key, rating in (("s2_vision", 7), ("s2_people", 5), ("s2_data", 3),
                        ("s2_issues", 6), ("s2_process", 4), ("s2_traction", 6)):
        answer(key, {"rating": rating, "comment": ""})
    session.mirror_goal = "Win two more hospital contracts without Brianna working weekends"
    session.mirror_unlocks = "Supervisors who can run a site audit without her"
    rows = [
        ("Quality checks depend on Brianna walking the building",
         "No written standard a supervisor can audit against",
         "A one-page site standard and a monthly supervisor audit", "Supervisors", 30,
         "Sites audited by a supervisor each month"),
        ("Bids take a week because pricing lives in her head",
         "No price book for square footage and frequency",
         "Build a price book from the last 20 bids", "Brianna, then office", 60,
         "Days from walk-through to bid"),
        ("Supervisors leave within a year",
         "No path from cleaner to supervisor to area lead",
         "Publish the ladder and the pay step at each rung", "Brianna", 90,
         "Supervisor turnover, trailing 12 months"),
    ]
    for position, (bottleneck, cause, fix, owner, horizon, measurable) in enumerate(rows):
        StrategyMapRow.objects.create(
            tenant=tenant, session=session, position=position, bottleneck=bottleneck,
            root_cause=cause, the_fix=fix, owner_text=owner, horizon=horizon,
            measurable=measurable, state=StrategyMapRow.State.ACCEPTED)
    answer("s8_path_a", {"reaction": "", "risk": "", "leaning": ""})
    answer("s8_path_b", {"reaction": "", "risk": "", "leaning": "Leaning this way"})
    for path, kind, text in (
            ("a", "pro", "You keep every decision and every dollar."),
            ("a", "con", "It waits behind the day job, which is what happened last year."),
            ("b", "pro", "Someone owns the list every Monday."),
            ("b", "con", "A monthly fee from the first month.")):
        StrategyPathNote.objects.create(tenant=tenant, session=session, path=path,
                                        kind=kind, text=text, from_ai=False,
                                        state=StrategyPathNote.State.ACCEPTED)
    answer("s9_follow_up_call", {"agreed": True, "notes": "Next Tuesday, 10am"})
    answer("s9_proposal_due", {"agreed": True, "notes": "Friday"})
    session.state = StrategySession.State.COMPLETE
    session.save(update_fields=["mirror_goal", "mirror_unlocks", "state", "updated_at"])
    pdf_service.store_pdf(session)
    return 1


MEETINGS = [
    {
        "name": "Northwind weekly ops - Notes by Gemini",
        "summary": "Weekly operations check-in with Northwind. The new inspection "
                   "checklist is nearly ready; weekend crews are the gap. Dana will "
                   "confirm which sites need a named weekend lead.",
        "participants": [("Dana Reyes", "dana.reyes@northwind.example", "COO",
                          "Northwind Facility Services", "client")],
        "actions": [("Confirm which weekend sites need a named lead", "Dana Reyes",
                     "other", "client", 5),
                    ("Send the final checklist to site leads", "", "practice", "", 3)],
        "deliverables": [("Training plan for weekend crews", "", 10)],
    },
    {
        "name": "Intro call - Hart & Sons Plumbing - Notes by Gemini",
        "summary": "First conversation with Owen Hart. Dispatch is run from one "
                   "person's phone and jobs are lost when she is off. He would like "
                   "a strategy session next week.",
        "participants": [("Owen Hart", "owen.hart@hartplumbing.example", "General manager",
                          "Hart & Sons Plumbing", "prospect"),
                         ("Maria Hart", "", "Office manager", "Hart & Sons Plumbing",
                          "prospect")],
        "actions": [("Book the strategy session", "", "practice", "", 2),
                    ("Send over last month's job list", "Owen Hart", "other",
                     "prospect", 4)],
        "deliverables": [],
    },
]


def _meeting_queue(tenant, ff_user) -> int:
    """Proposals waiting for review, made by the same builder a real parse
    uses — with the payload written here instead of by Claude."""
    from apps.meetings import parsing
    from apps.meetings.models import MeetingSourceFile

    today = timezone.localdate()
    for index, meeting in enumerate(MEETINGS):
        excerpt = meeting["summary"].split(". ")[0] + "."
        payload = {
            "title": meeting["name"].split(" - Notes")[0],
            "meeting_date": (today - timedelta(days=index + 1)).isoformat(),
            "summary": meeting["summary"],
            "participants": [{"name": name, "email": email, "title": title,
                              "company": company, "contact_type": kind,
                              "excerpt": f"Attendees: {name}"}
                             for name, email, title, company, kind in meeting["participants"]]
            + [{"name": ff_user.full_name, "email": ff_user.email, "title": "",
                "company": PRACTICE, "contact_type": "coworker",
                "excerpt": f"Attendees: {ff_user.full_name}"}],
            "action_items": [{"text": text, "owner": owner, "owner_side": side,
                              "owner_kind": kind,
                              "due_date": (today + timedelta(days=days)).isoformat(),
                              "excerpt": excerpt}
                             for text, owner, side, kind, days in meeting["actions"]],
            "deliverables": [{"text": text, "owner": owner,
                              "due_date": (today + timedelta(days=days)).isoformat(),
                              "excerpt": excerpt}
                             for text, owner, days in meeting["deliverables"]],
        }
        source = MeetingSourceFile.objects.create(
            tenant=tenant, drive_file_id=f"demo-{index}", drive_version="1",
            name=meeting["name"], mime_type="application/vnd.google-apps.document",
            drive_file_owner_email=ff_user.email, text=meeting["summary"],
            state=MeetingSourceFile.State.PARSING, fetched_at=timezone.now())
        parsing._build(source, payload, None)
    return len(MEETINGS)
