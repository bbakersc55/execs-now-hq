"""Strategy templates and sessions: one session at each point in its life.

- a **draft** with prep run from website text pasted in;
- one **in the call**, part answered, with rows waiting in the tray;
- one **complete**, with pros and cons, its call notes attached and its PDF
  sent;
- one **converted**: its map became a client's goal and project.

The templates are made by the builder's own functions; the sessions by
`apps.strategy.services`. What Claude would have drafted (prep, tray rows,
pros and cons) is written here in the shape Claude's drafts are stored in,
because the demo makes no AI call while it is seeded.
"""

from __future__ import annotations

from datetime import timedelta

from .clock import at, moment

CALL_NOTES = """\
Sheinhardt Wig Company - strategy session - notes

Jack: We make about eleven thousand units a month across two plants. Orders are fine. \
The problem is we promise four weeks and deliver in seven.
John: Where does the time go?
Jack: Every custom order waits for me to approve the spec. I approve forty a week, \
usually on Sunday night.
Jack: The second plant runs on a spreadsheet that one person understands, and she is \
retiring in March.
John: What have you tried?
Jack: We hired a scheduler last year. He left after five months because nobody would \
give him the real capacity numbers.
Jack: If I could get lead time back to four weeks I would win the two department store \
accounts we lost last spring.
John: Who would own this day to day?
Jack: Kenneth could, if someone showed him how. He has never run anything bigger than \
the mail room.
"""


def strategy(world) -> None:
    templates = _templates(world)
    world.extra["templates"] = templates
    _converted(world, templates[0])
    _complete(world, templates[0])
    _in_call(world, templates[0])
    _draft(world, templates[1])


# ---------------------------------------------------------------- templates

def _templates(world):
    from apps.strategy import builder, examples
    from apps.strategy.models import StrategyTemplate

    with at(moment(world.today - timedelta(days=400), 10)):
        standard, _ = examples.create(world.tenant, name="Operations strategy session",
                                      start_from=examples.OPERATIONS)
        StrategyTemplate.objects.filter(pk=standard.pk).update(is_default=True)
        standard.refresh_from_db()
    with at(moment(world.today - timedelta(days=60), 14)):
        own, _ = examples.create(world.tenant, name="Operations, with systems and tools",
                                 start_from=examples.OPERATIONS)
        diagnostic = builder._sections(own).get(kind=builder.DIAGNOSTIC)
        section = builder.add_section(own, title="Systems and tools",
                                      time_budget_minutes=8, after=diagnostic.code)
        for prompt in (
                "Which system does the team trust least, and what do they keep beside it?",
                "What gets typed into two places?",
                "If your main system went down for a day, what would stop first?"):
            builder.add_question(own, section=section.code, prompt=prompt)
        builder.update_section(own, code=section.code, show_in_pdf=True)
    return standard, own


# ------------------------------------------------------------ the answering

class Call:
    """One session and the keys of its questions, by part."""

    def __init__(self, session):
        from apps.strategy.models import StrategyAnswer

        self.session = session
        self.keys = {section["kind"]: [q["key"] for q in section["questions"]]
                     for section in session.template_snapshot["sections"]}
        self.fractional = StrategyAnswer.AnsweredBy.FRACTIONAL
        self.prospect = StrategyAnswer.AnsweredBy.PROSPECT

    def answer(self, kind, index, value, *, by=None, note=None):
        from apps.strategy import services

        services.save_answer(self.session, question_key=self.keys[kind][index], value=value,
                             answered_by=by or self.fractional, fractional_note=note)

    def precall(self, *texts):
        for index, text in enumerate(texts):
            if text:
                self.answer("precall", index, {"text": text}, by=self.prospect)

    def ratings(self, *numbers):
        for index, number in enumerate(numbers):
            if number is not None:
                # Taken on the call: in this template the ratings are asked live.
                self.answer("ratings", index, {"rating": number, "comment": ""})

    def row(self, position, header, statement, owner, horizon, measurable, state, **more):
        from apps.strategy.models import StrategyMapRow

        drafted = "added_by" not in more
        return StrategyMapRow.objects.create(
            tenant=self.session.tenant, session=self.session, position=position,
            header=header, statement=statement, bottleneck=header, owner_text=owner,
            horizon=horizon, measurable=measurable, state=state,
            proposed_header=header if drafted else "",
            proposed_statement=statement if drafted else "", **more)

    def note(self, path, kind, text, state="accepted", from_ai=True, position=0):
        from apps.strategy.models import StrategyPathNote

        return StrategyPathNote.objects.create(
            tenant=self.session.tenant, session=self.session, path=path, kind=kind,
            text=text, proposed_text=text if from_ai else "", from_ai=from_ai, state=state,
            position=position)


def _start(world, contact, template, when, *, owner=None, visionary=None, integrator=None):
    from apps.strategy import services

    return Call(services.start(
        tenant=world.tenant, contact=contact, template=template,
        owner=owner or world.owner, company=contact.company, scheduled_at=when,
        visionary_contact=visionary, integrator_contact=integrator))


def _state(session, state, **fields):
    session.state = state
    for name, value in fields.items():
        setattr(session, name, value)
    session.save(update_fields=["state", *fields, "updated_at"])


# ----------------------------------------------------------- the four sessions

def _draft(world, template) -> None:
    """Booked for next week; prep has been run from the website text."""
    from apps.strategy.models import StrategyPrepQuestion, StrategySessionPrep

    contact = world.prospects["Gustavo Fring"]
    with at(moment(world.today - timedelta(days=1), 16)):
        call = _start(world, contact, template, moment(world.today + timedelta(days=4), 10))
        prep = StrategySessionPrep.objects.create(
            tenant=world.tenant, session=call.session,
            state=StrategySessionPrep.State.READY,
            notes=("From their website, pasted: Los Pollos Hermanos. Fourteen restaurants "
                   "across the Southwest, family recipes since 1989, and our own "
                   "distribution center serving every location daily. Now hiring general "
                   "managers in Albuquerque, El Paso and Tucson. Franchise enquiries "
                   "welcome. Owner-operated: Gus still visits every store each month."),
            summary=("Fourteen owner-operated restaurants with their own distribution "
                     "center. Hiring general managers in three cities at once, and open to "
                     "franchising, while the owner still visits every store monthly: the "
                     "business is growing faster than its management layer."),
            bottlenecks=[
                "Three general manager openings at once suggests turnover or thin bench.",
                "The owner visiting every store monthly is the quality system.",
                "One distribution center serving fourteen stores daily is a single point "
                "of failure.",
                "Franchising needs written standards that may live in the owner's head.",
            ],
            rewordings=[], dropped_rewordings=[])
        for position, (text, why) in enumerate((
                ("What happens in a store in the weeks you do not visit?",
                 "His monthly visit appears to be how standards are kept."),
                ("How long does a new general manager take to run a store alone?",
                 "Three openings at once; the answer sizes the bench problem."),
                ("If a franchisee opened tomorrow, what would you hand them?",
                 "Tests whether the standards are written down."),
                ("What would stop first if the distribution center lost a day?",
                 "One center serves every location daily."))):
            StrategyPrepQuestion.objects.create(
                tenant=world.tenant, prep=prep, session=call.session, text=text, why=why,
                position=position, is_pinned=position < 2)


def _in_call(world, template) -> None:
    """On the call now: the pre-call form came back, the ratings are in, two
    diagnostic questions are answered and rows are waiting in the tray."""
    from apps.strategy.models import StrategyMapRow, StrategySession

    contact = world.prospects["Rocky Balboa"]
    began = moment(world.today, 9, 30)
    with at(moment(world.today - timedelta(days=5), 11)):
        call = _start(world, contact, template, began)
    with at(moment(world.today - timedelta(days=2), 20, 15)):
        call.precall("$2.4m last year, $2.9m this year",
                     "22 full-time, 31 part-time trainers, 4 in the office",
                     "Six gyms", "Memberships 70%, personal training 25%, retail 5%",
                     "Four established, two opened this year and still finding their feet",
                     "", "Mindbody for bookings. Payroll is a spreadsheet Paulie keeps.")
        call.ratings(8, 4, 3, 6, 4, 5)
    with at(began + timedelta(minutes=25)):
        _state(call.session, StrategySession.State.IN_CALL, started_at=began,
               current_section="strategy_map",
               current_section_at=began + timedelta(minutes=22))
        call.answer("diagnostic", 0, {
            "said": "Every new-member discount over 10% comes to me. So does every "
                    "trainer's schedule change.",
            "cause": "The gym managers were trainers last year. Nobody told them what "
                     "they can decide.",
            "tried": "A managers' group chat. It turned into forty messages a day, all "
                     "for me."})
        call.answer("diagnostic", 1, {
            "said": "We lose a third of the trainers every year. Each gym manager "
                    "recruits their own, in their own way.",
            "cause": "", "tried": ""})
        call.row(0, "Managers who can decide",
                 "Gym managers send every discount and schedule change to Rocky because "
                 "nobody has said what is theirs to decide.",
                 "Rocky, then each gym manager", 30,
                 "Decisions sent to Rocky each week", StrategyMapRow.State.ACCEPTED)
        call.row(1, "Keep the trainers you train",
                 "A third of the trainers leave each year, and each gym recruits its own "
                 "way.", "Adrian", 60, "Trainer turnover, trailing twelve months",
                 StrategyMapRow.State.PROPOSED)
        call.row(2, "Payroll out of Paulie's spreadsheet",
                 "Payroll for 53 people runs from one spreadsheet that one person keeps.",
                 "Paulie", 60, "Payroll corrections each month",
                 StrategyMapRow.State.PROPOSED)
        call.row(3, "Two new gyms on their feet",
                 "The two gyms opened this year are still finding their feet.",
                 "", 90, "", StrategyMapRow.State.PROPOSED)


def _complete(world, template) -> None:
    """Last week's session: everything answered, pros and cons weighed, the
    call notes attached and the PDF sent the same day."""
    from apps.strategy import call_notes, emails
    from apps.strategy.models import StrategyCallNotes, StrategyMapRow, StrategySession

    contact = world.prospects["Jack Donaghy"]
    day = world.today - timedelta(days=6)
    began = moment(day, 13)
    with at(moment(day - timedelta(days=6), 9)):
        call = _start(world, contact, template, began)
    with at(moment(day - timedelta(days=2), 18)):
        call.precall("$9.8m last year, $10.4m this year",
                     "86 full-time, 12 part-time, 9 in the office",
                     "About 240 retail accounts", "Stock styles 60%, custom 35%, repairs 5%",
                     "Two plants: Scranton is established, Hoboken opened in 2023",
                     "Top five are 38% of revenue",
                     "An old ERP at Scranton. Hoboken runs on one planner's spreadsheet.")
        call.ratings(7, 5, 3, 6, 3, 4)
    with at(began + timedelta(minutes=70)):
        session = call.session
        _state(session, StrategySession.State.IN_CALL, started_at=began)
        call.answer("diagnostic", 0, {
            "said": "Every custom order waits for me to approve the spec. Forty a week, "
                    "usually on Sunday night.",
            "cause": "There is no written rule for what a planner may approve.",
            "tried": "Delegating to the plant managers, who sent them back anyway."})
        call.answer("diagnostic", 1, {
            "said": "We hired a scheduler last year. He left after five months.",
            "cause": "Nobody would give him the real capacity numbers.", "tried": ""})
        call.answer("diagnostic", 2, {
            "said": "Custom makes the margin. Repairs lose money on every unit.",
            "cause": "Repairs are priced at what they cost in 2015.", "tried": ""})
        call.answer("mirror", 0, {"text": "$15m in three years, both plants at four-week "
                                          "lead time, and Jack out of spec approvals."})
        call.answer("mirror", 1, {"text": "Win back the two department store accounts. "
                                          "Most at risk: Hoboken's schedule."})
        call.answer("mirror", 2, {"text": "A real production schedule. On the list since "
                                          "Hoboken opened."})
        call.answer("mirror", 3, {"text": "Jack talks about growth; the plant managers "
                                          "talk about getting through the week."},
                    note="Not for the document.")
        session.proposed_mirror_goal = ("Get lead time back to four weeks and win back "
                                        "the two department store accounts.")
        session.mirror_goal = session.proposed_mirror_goal
        session.proposed_mirror_unlocks = ("A schedule built on real capacity, and spec "
                                           "approvals that do not wait for Jack.")
        session.mirror_unlocks = session.proposed_mirror_unlocks
        session.save(update_fields=["proposed_mirror_goal", "mirror_goal",
                                    "proposed_mirror_unlocks", "mirror_unlocks",
                                    "updated_at"])
        notes = call_notes.attach(session, actor=world.owner,
                                  source=StrategyCallNotes.Source.PASTED, text=CALL_NOTES)
        accepted = StrategyMapRow.State.ACCEPTED
        call.row(0, "Spec approvals that do not wait for Jack",
                 "Every custom order waits for Jack to approve the spec, forty a week.",
                 "Jack, then the planners", 30, "Custom orders approved without Jack",
                 accepted)
        call.row(1, "A schedule built on real capacity",
                 "Lead time is promised at four weeks and runs at seven.",
                 "Kenneth", 60, "Lead time in weeks", accepted, from_call_notes=True,
                 source_passage="The problem is we promise four weeks and deliver in seven.")
        call.row(2, "Hoboken off one person's spreadsheet",
                 "The second plant runs on a spreadsheet that one person understands, and "
                 "she is retiring in March.", "Plant manager, Hoboken", 60,
                 "Planners who can run the Hoboken schedule", accepted,
                 from_call_notes=True,
                 source_passage="The second plant runs on a spreadsheet that one person "
                                "understands, and she is retiring in March.")
        call.row(3, "Repairs priced at what they cost",
                 "Repairs lose money on every unit; the prices are from 2015.",
                 "Jack", 90, "Margin on repairs", accepted, added_by=world.owner)
        call.row(4, "A sales plan for department stores",
                 "Two department store accounts were lost last spring.", "", 90, "",
                 StrategyMapRow.State.DISCARDED)
        for index, (value, why) in enumerate((
                ("Someone who has run a plant", "He has had advice. He wants hands."),
                ("Numbers he can check himself", "The last scheduler worked in a black box."),
                ("Kenneth growing into the role", "He wants to promote from inside."))):
            call.answer("values", index, {"value": value, "why": why})
        call.answer("paths", 0, {"reaction": "Likes keeping it in house.",
                                 "risk": "Kenneth has never run anything this size.",
                                 "leaning": ""})
        call.answer("paths", 1, {"reaction": "Wants someone beside Kenneth for the first "
                                             "two quarters.", "risk": "The monthly fee.",
                                 "leaning": "Leaning this way"})
        for position, (path, kind, text, state, from_ai) in enumerate((
                ("a", "pro", "You keep every decision and every dollar.", "accepted", True),
                ("a", "con", "It waits behind the day job, which is what happened with "
                             "the scheduler.", "accepted", True),
                ("a", "con", "Kenneth learns by trial and error on live orders.",
                 "accepted", False),
                ("b", "pro", "Someone owns the schedule every Monday from week one.",
                 "accepted", True),
                ("b", "pro", "Kenneth learns it beside someone who has done it.",
                 "accepted", True),
                ("b", "con", "A monthly fee from the first month.", "accepted", True),
                ("b", "con", "Staff may see an outsider as a threat.", "discarded", True))):
            call.note(path, kind, text, state=state, from_ai=from_ai, position=position)
        for index, (agreed, text) in enumerate((
                (True, "Rows 1 and 2 in the first 90 days; Hoboken follows."),
                (True, "The first of next month"),
                (True, "90-day sprints, a working session every Tuesday"),
                (True, "$4,500 a month for six months"),
                (False, "Thought it fair. Wants to see it in writing."),
                (True, "His CFO, by the end of next week"),
                (True, "Next Tuesday at 10"),
                (True, "Same day, 5 pm"),
                (True, "Friday"))):
            call.answer("scope", index, {"agreed": agreed, "notes": text})
        _state(session, StrategySession.State.COMPLETE)
    with at(moment(day, 17, 5)):
        emails.send_strategy_pdf(
            call.session, actor=world.owner, role="FF",
            note="Jack, thank you for the time today. The map is attached: four things, "
                 "in the order we agreed. I will have the proposal to you by Friday.")
    world.extra["complete_session"], world.extra["call_notes"] = call.session, notes


def _converted(world, template) -> None:
    """Sterling Cooper's session, from before they were a client. Its map
    became the goal and the first project they are working on now."""
    from apps.strategy import conversion, pdf
    from apps.strategy.models import StrategyMapRow, StrategySession

    name = "Sterling Cooper Creative"
    don, joan = world.people[name][0], world.people[name][1]
    lead, start = world.lead[name], world.start[name]
    began = moment(start - timedelta(days=21), 11)
    with at(began - timedelta(days=5)):
        call = _start(world, don, template, began, owner=lead, visionary=don,
                      integrator=joan)
    with at(began - timedelta(days=1)):
        call.precall("$4.1m last year, $4.3m this year", "28 full-time, 6 freelancers",
                     "31 active accounts", "Campaigns 65%, retainers 30%, production 5%",
                     "One office", "Top five are 52% of revenue",
                     "Timesheets in one tool, estimates in a spreadsheet, invoices in a third.")
        call.ratings(8, 6, 3, 5, 4, 5)
    with at(began + timedelta(minutes=75)):
        session = call.session
        _state(session, StrategySession.State.IN_CALL, started_at=began)
        call.answer("diagnostic", 0, {
            "said": "Every job that goes over comes to me after the fact.",
            "cause": "Nobody sees hours against the estimate until the invoice.",
            "tried": "A monthly review. By then the job is finished."})
        call.answer("diagnostic", 2, {
            "said": "Half our jobs go over the estimate, and we eat it.",
            "cause": "Revisions are never estimated.", "tried": ""})
        session.mirror_goal = "Jobs that make the margin they were sold at."
        session.mirror_unlocks = "Estimates built from what jobs really cost."
        session.save(update_fields=["mirror_goal", "mirror_unlocks", "updated_at"])
        accepted = StrategyMapRow.State.ACCEPTED
        on_budget = call.row(0, "Jobs delivered on budget",
                             "Half the jobs go over the estimate, and the agency absorbs it.",
                             "Don", 90, "Jobs finished within the estimate", accepted)
        estimates = call.row(1, "Estimates built from what jobs cost",
                             "Revisions are never estimated, so every revised job overruns.",
                             "Joan", 30, "", accepted)
        call.answer("paths", 1, {"reaction": "This one.", "risk": "", "leaning":
                                 "Leaning this way"})
        call.note("b", "pro", "Someone watches hours against estimates every week.")
        call.note("a", "con", "The monthly review has not caught an overrun in time yet.")
        call.answer("scope", 0, {"agreed": True, "notes": "Both rows, from the first month."})
        _state(session, StrategySession.State.COMPLETE)
        pdf.store_pdf(session)
    with at(moment(start - timedelta(days=5), 15)):
        conversion.convert(call.session, actor=lead, role="CF", choices={
            str(on_budget.pk): {"as": "goal", "baseline_value": "48", "target_value": "85",
                                "measurable_unit": "%", "direction": "up_is_good",
                                "baseline_at": start},
            str(estimates.pk): {"as": "project"}})
    world.extra["converted_session"] = call.session
