"""The demo's SOP studio (P10, docs/p10_sop_studio.md, "The demo"). No Claude:
every word is written here as a person (or, in the brainstorm, Claude) would
have written it, and no AI call is made or charged.

Acme Fasteners gets ten more people in the portal (the floor, quality and
shipping), so its twelve read what is published to the whole company:

- **Header line changeover**, published (version 1) with a process map, read
  by 7 of the 12, one of them late, with one change suggested.
- **Receiving a steel delivery**, published at version 2, a change that asks
  everyone to read it again: three have, the rest (Marvin among them) are
  asked again.
- **Quoting a custom fastener job**, a draft, with a saved brainstorm: a
  pasted notebook summary and a pasted transcript as its sources (the demo
  has no media key, so a recording is pasted as a transcript), the
  conversation, and Claude's revised draft waiting as a diff.
"""

from __future__ import annotations

from datetime import timedelta

from .clock import at, dice, moment

ACME = "Acme Fasteners"

#: The floor, in the portal: (first, last, title).
CREW = [
    ("Elmer", "Fudd", "Header line lead"), ("Yosemite", "Sam", "Machinist"),
    ("Foghorn", "Leghorn", "Machinist"), ("Pepe", "LePew", "Machinist"),
    ("Speedy", "Gonzales", "Shipping lead"), ("Sylvester", "Pussycat", "Shipping"),
    ("Tweety", "Bird", "Quality inspector"), ("Porky", "Pig", "Quality lead"),
    ("Petunia", "Pig", "Receiving"), ("Gossamer", "Hare", "Maintenance"),
]

CHANGEOVER_MAP = """flowchart TD
  start([Last part of the run off the header]) --> lock[Lock out the header and tag it]
  lock --> dies[Pull the dies and the punch]
  dies --> clean[Clean the die block and check for wear]
  clean --> worn{Worn past the gauge?}
  worn -->|Yes| swap[Swap in a reground set and log it]
  worn -->|No| set[Set the new dies to the setup sheet]
  swap --> set
  set --> first[Run five first pieces]
  first --> check{First pieces pass inspection?}
  check -->|No| adjust[Adjust to the setup sheet] --> first
  check -->|Yes| release([Release the run])"""

CHANGEOVER_STEPS = [
    {"text": "Run the last part of the order and stop the header at the top of its stroke.",
     "role": "Header line lead", "warning": ""},
    {"text": "Lock out the header and hang your tag on it.", "role": "Machinist",
     "warning": "Never reach into the die area until your own lock is on the disconnect."},
    {"text": "Pull the dies and the punch and set them on the cart, in order.",
     "role": "Machinist", "warning": ""},
    {"text": "Clean the die block and check each die against the wear gauge.",
     "role": "Machinist", "warning": ""},
    {"text": "If a die is worn past the gauge, swap in a reground set and write it in the "
             "die log.", "role": "Machinist", "warning": ""},
    {"text": "Set the new dies to the setup sheet for the next job: depth, stroke and feed.",
     "role": "Header line lead", "warning": "Use the sheet for this part number, not memory."},
    {"text": "Run five first pieces and take them to quality.", "role": "Machinist",
     "warning": ""},
    {"text": "Quality checks the first pieces against the drawing; adjust and rerun until they "
             "pass.", "role": "Quality inspector", "warning": ""},
    {"text": "Release the run on the board and remove your lock last.",
     "role": "Header line lead", "warning": ""},
]

RECEIVING_V1 = [
    {"text": "Check the delivery against the purchase order: grade, size and weight.",
     "role": "Receiving", "warning": ""},
    {"text": "Unload with the forklift onto the receiving rack, one heat number per bay.",
     "role": "Receiving", "warning": "Coils over 2,000 lb go on the floor cradle, never the rack."},
    {"text": "Tag each coil with its heat number and the PO.", "role": "Receiving",
     "warning": ""},
    {"text": "Enter the receipt in the system the same day.", "role": "Receiving", "warning": ""},
]
RECEIVING_V2 = [RECEIVING_V1[0],
                {"text": "Check the mill certificate matches the heat numbers on the coils "
                         "before anything is unloaded.", "role": "Quality inspector",
                 "warning": "No certificate, no unloading: call purchasing."}] + RECEIVING_V1[1:]

QUOTE_STEPS = [
    {"text": "Read the drawing and list the material, the size and the finish.",
     "role": "Purchasing lead", "warning": ""},
    {"text": "Price the steel from this week's supplier sheet.", "role": "Purchasing lead",
     "warning": ""},
    {"text": "Ask the header line lead how long the setup and the run will take.",
     "role": "Purchasing lead", "warning": ""},
    {"text": "Send the quote.", "role": "Purchasing lead", "warning": ""},
]
QUOTE_REVISED = {
    "title": "Quoting a custom fastener job",
    "purpose": "Every custom quote out within two working days, priced from current steel "
               "and real setup times, so jobs we win are jobs we make money on.",
    "applies_when": "Any request for a part that isn't in the catalog.",
    "roles": [{"name": "Purchasing lead", "does": "Owns the quote and sends it"},
              {"name": "Header line lead", "does": "Gives setup and run times"}],
    "steps": [
        {"text": "Log the request on the quote board the day it arrives.",
         "role": "Purchasing lead", "warning": ""},
        QUOTE_STEPS[0],
        QUOTE_STEPS[1],
        {"text": "Look up the setup and run times for the closest past job in the job log; "
                 "ask the header line lead only if there is none.",
         "role": "Purchasing lead", "warning": ""},
        {"text": "Add the header line's current wait to the promised date.",
         "role": "Purchasing lead",
         "warning": "The header line is the constraint: never promise its time twice."},
        {"text": "Send the quote within two working days and move the card to Sent.",
         "role": "Purchasing lead", "warning": ""},
    ],
    "category": "Sales",
}


def _crew(world, company):
    from apps.crm.models import Company
    from apps.work import portal

    from .foundation import address_for, contact

    Company.objects.filter(pk=company.pk).update(seat_count=14)
    company.refresh_from_db()
    members = []
    for first, last, title in CREW:
        row = contact(world, first, last, title, company, address_for(first, last, company.name))
        member = portal.grant(tenant=world.tenant, contact=row, actor=world.owner, role="ECC")
        seen = world.today - timedelta(days=dice("crew", first).randrange(1, 12))
        member.user.last_login_at = moment(seen, 7, 40)
        member.user.save(update_fields=["last_login_at"])
        members.append(member)
    return members


def _ack(sop, version, member, day, hour, late=False):
    from apps.sops.models import SopAck

    SopAck.objects.create(tenant_id=sop.tenant_id, sop=sop, version=version, membership=member,
                          user=member.user, acknowledged_at=moment(day, hour, 10), late=late)


def sops(world) -> dict:
    from apps.scorecard import library
    from apps.scorecard.models import Kpi
    from apps.sops import services
    from apps.sops.models import (Brainstorm, BrainstormMessage, BrainstormProposal,
                                  BrainstormSource, SopComment, SopVersion)

    company = world.companies[ACME]
    today = world.today
    with at(moment(today - timedelta(days=24), 8, 30)):
        crew = _crew(world, company)
    people = world.portal[ACME] + crew            # Wiley, Marvin, and the ten
    by_name = {m.user.full_name: m for m in people}
    owner = world.owner
    kpis = {k.name: k for k in Kpi.objects.filter(scorecard__company=company,
                                                  archived_at__isnull=True)}
    rework = kpis.get(library.shipped("rework_rate")["name"])
    on_time = kpis.get(library.shipped("on_time_completion")["name"])

    # -------------------------------------------- 1. published, 7 of 12 read
    published = today - timedelta(days=12)
    with at(moment(published - timedelta(days=2), 10, 0)):
        changeover = services.create(company, actor=owner, title="Header line changeover", data={
            "purpose": "Change the header over from one job to the next safely and in under "
                       "45 minutes, with first pieces right before the run starts.",
            "applies_when": "Every job change on the header line, on every shift.",
            "roles": [{"name": "Header line lead", "does": "Owns the changeover and releases "
                                                           "the run"},
                      {"name": "Machinist", "does": "Pulls and sets the dies"},
                      {"name": "Quality inspector", "does": "Passes the first pieces"}],
            "steps": CHANGEOVER_STEPS, "category": "Production",
            "owner": str(by_name["Elmer Fudd"].user_id),
            "review_date": (today + timedelta(days=80)).isoformat(),
            "process_map": CHANGEOVER_MAP,
            "kpis": [str(k.pk) for k in (rework, on_time) if k is not None]})
    with at(moment(published, 9, 0)):
        v1 = services.publish(changeover, actor=owner, change_note="First version.")
    readers = ["Wiley Coyote", "Marvin Martian", "Elmer Fudd", "Yosemite Sam", "Porky Pig",
               "Tweety Bird", "Foghorn Leghorn"]
    for i, name in enumerate(readers):
        late = name == "Foghorn Leghorn"
        day = published + timedelta(days=9 if late else i % 4)
        _ack(changeover, v1, by_name[name], day, 7 + i, late=late)
    with at(moment(published + timedelta(days=3), 14, 20)):
        SopComment.objects.create(
            tenant_id=changeover.tenant_id, sop=changeover, version_number=1,
            author=by_name["Yosemite Sam"].user,
            text="The setup sheets for the 3/8 bolts are still the old ones; step 6 sends us "
                 "to a sheet that's wrong for those.")

    # -------------------------------------------- 2. version 2, asking again
    first = today - timedelta(days=30)
    with at(moment(first - timedelta(days=1), 11, 0)):
        receiving = services.create(company, actor=owner, title="Receiving a steel delivery", data={
            "purpose": "Every coil we take in is the steel we ordered, tagged so it can be "
                       "traced to the parts made from it.",
            "applies_when": "Every steel delivery, whoever is on the dock.",
            "roles": [{"name": "Receiving", "does": "Checks, unloads and tags"},
                      {"name": "Quality inspector", "does": "Checks the mill certificate"}],
            "steps": RECEIVING_V1, "category": "Receiving",
            "owner": str(by_name["Petunia Pig"].user_id),
            "review_date": (today + timedelta(days=150)).isoformat()})
    with at(moment(first, 9, 0)):
        r1 = services.publish(receiving, actor=owner)
    for i, member in enumerate(people[:9]):
        _ack(receiving, r1, member, first + timedelta(days=1 + i % 5), 8 + i % 6)
    second = today - timedelta(days=3)
    with at(moment(second, 15, 0)):
        services.update(receiving, {"steps": RECEIVING_V2}, actor=owner)
        r2 = services.publish(receiving, actor=owner,
                              change_note="Check the mill certificate before anything is "
                                          "unloaded, after the wrong grade came in October.")
    for i, name in enumerate(("Wiley Coyote", "Petunia Pig", "Porky Pig")):
        _ack(receiving, r2, by_name[name], second + timedelta(days=1), 9 + i)

    # -------------------------------------------- 3. a draft, with a saved brainstorm
    with at(moment(today - timedelta(days=2), 13, 0)):
        quote = services.create(company, actor=owner, title="Quoting a custom fastener job",
                                data={"steps": QUOTE_STEPS, "category": "Sales",
                                      "owner": str(world.owner.pk)})
        storm = Brainstorm.objects.create(tenant_id=company.tenant_id, company=company,
                                          sop=quote, title="Quoting a custom fastener job",
                                          created_by=owner)
        BrainstormSource.objects.create(
            tenant_id=company.tenant_id, brainstorm=storm, kind=BrainstormSource.Kind.PASTED,
            title="Notebook summary: quoting", created_by=owner,
            text="From the notebook on Acme's quoting: quotes take 4 to 9 working days. "
                 "Daffy waits on Marvin or Elmer for setup times on almost every quote. Two "
                 "quotes last quarter promised header time that was already booked.")
        BrainstormSource.objects.create(
            tenant_id=company.tenant_id, brainstorm=storm, kind=BrainstormSource.Kind.PASTED,
            title="Transcript: Daffy walks through a quote", created_by=owner,
            text="Daffy: I get the drawing, usually by email. I list the material and price "
                 "it off the steel sheet. Then I walk out to the floor and ask Elmer how long "
                 "the setup is, and that's where it sits, sometimes a week. Elmer: Most of "
                 "them are like a job we've run before. It's in the job log. Daffy: I never "
                 "look there.")
    conversation = [
        ("user", "Help me tighten this quoting SOP. Quotes are slow and twice we promised "
                 "header time we didn't have."),
        ("claude", "From the transcript, the wait is the setup time: Daffy asks Elmer for "
                   "every quote, though most jobs match one in the job log. Two changes would "
                   "fix most of it: look up the closest past job first, and add the header "
                   "line's current wait to the promised date. Who keeps the job log, and is "
                   "it up to date?"),
        ("user", "Elmer keeps it; it's current. Aim for two working days."),
        ("claude", "Then the SOP can promise two working days and send Daffy to the job log "
                   "first. I'd also log each request on a quote board the day it arrives, so "
                   "the two days can be measured. Ready for a draft when you are."),
    ]
    for i, (role, text) in enumerate(conversation):
        with at(moment(today - timedelta(days=2), 13, 5 + 3 * i)):
            BrainstormMessage.objects.create(
                tenant_id=company.tenant_id, brainstorm=storm, role=role, text=text,
                author=owner if role == "user" else None)
    with at(moment(today - timedelta(days=2), 13, 20)):
        BrainstormProposal.objects.create(
            tenant_id=company.tenant_id, brainstorm=storm, kind=BrainstormProposal.Kind.DRAFT,
            payload=QUOTE_REVISED,
            why="From the transcript and the notebook summary: the setup-time wait and the "
                "double-booked header time.")
    return {"SOPs": 3, "Acme portal people": len(people),
            "versions": SopVersion.objects.filter(sop__company=company).count()}
