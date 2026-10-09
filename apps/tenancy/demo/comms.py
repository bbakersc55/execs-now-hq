"""Meetings, commitments, notes and the practice's email: the meeting queue
with proposals at each stage of review, the commitments other people made
("Waiting on others"), a dozen notes, a campaign drafted and one sent, touch
drafts waiting in the Sending queue, replies nobody could file, and an
unsubscribe.

A proposal is built by the same function a real parse uses, with the payload
written here instead of by Claude, and reviewed through
`apps.meetings.approval`.
"""

from __future__ import annotations

from datetime import timedelta

from .clock import at, moment


def everything(world) -> None:
    _meetings(world)
    _notes(world)
    _email(world)


# ----------------------------------------------------------------- meetings

def _who(world, company, index=0):
    return world.people[company][index]


def _person(contact, kind):
    return (f"{contact.first_name} {contact.last_name}", contact.primary_email, contact.title,
            contact.company.name if contact.company_id else "", kind)


def _meetings(world) -> None:
    """Eight sets of notes: three waiting, two part reviewed, two reviewed,
    one dismissed. Twelve commitments come out of the reviewed ones."""
    from apps.meetings import approval, dismissal, parsing
    from apps.meetings.models import MeetingProposal, MeetingSourceFile, ProposalItem

    today, owner = world.today, world.owner
    partner = next(p for p in world.partners if p.last_name == "Wyatt")
    vendor = world.vendors["Maurice Moss"]
    selina = world.prospects["Selina Kyle"]

    # (title, days ago, summary, participants, actions, deliverables, review)
    # An action is (text, owner name, side, kind, days until due, outcome).
    # `review` is how far the review got: "", "part", "all" or "dismiss".
    plan = [
        ("Acme Fasteners weekly operations review", 1,
         "Weekly review with Acme. Second shift ran the new changeover standard on three "
         "nights. Wiley wants the late-order huddle moved to 7:15. Marvin will send the "
         "scrap tags for the week.",
         [_person(_who(world, "Acme Fasteners"), "client"),
          _person(_who(world, "Acme Fasteners", 1), "client")],
         [("Send this week's scrap tags", "Marvin Martian", "other", "client", 3, ""),
          ("Move the late-order huddle to 7:15", "Wiley Coyote", "other", "client", 2, ""),
          ("Update the changeover standard with second shift's notes", "", "practice", "",
           4, "")],
         [("Audit sheet for ten changeovers", "", 9)], ""),
        ("Introduction: Kyle Jewelers", 2,
         "First conversation with Selina Kyle. Three stores, one buyer, and stock counts "
         "that never match. Her operations manager Holly joined late. She would like a "
         "strategy session this month.",
         [_person(selina, "prospect"),
          ("Holly Robinson", "holly.robinson@kylejewelers.example", "Operations manager",
           "Kyle Jewelers", "prospect")],
         [("Book the strategy session", "", "practice", "", 2, ""),
          ("Send last quarter's stock count sheets", "Selina Kyle", "other", "prospect",
           5, "")], [], ""),
        ("Reynholm IT Support: quarterly check-in", 3,
         "Quarterly check-in with Reynholm. Laptops are due for replacement in January. "
         "Moss will quote three options. A referral partner, Ben Wyatt, joined to talk "
         "about the shared client folder.",
         [_person(vendor, "vendor"), _person(partner, "referral_partner")],
         [("Quote three laptop options", "Maurice Moss", "other", "vendor", 10, ""),
          ("Set up the shared client folder", "Ben Wyatt", "other", "third_party", 7, ""),
          ("Confirm how many laptops we need", "", "practice", "", 6, "")], [], ""),
        ("Wayne Industries monthly review", 6,
         "Monthly review with Bruce and Lucius. Arkham Road held its first scorecard "
         "meeting. Bruce wants safety ahead of the scorecard work after last month's "
         "injury. Lucius will send the overtime report for all four sites.",
         [_person(_who(world, "Wayne Industries"), "client"),
          _person(_who(world, "Wayne Industries", 1), "client"),
          _person(_who(world, "Wayne Industries", 2), "client")],
         [("Send the overtime report for all four sites", "Lucius Fox", "other", "client",
           -2, "follow_up"),
          ("Confirm the budget for guarding on line 3", "Alfred Pennyworth", "other",
           "client", 8, "follow_up"),
          ("Decide whether safety moves ahead of the scorecard", "Bruce Wayne", "other",
           "client", 5, ""),
          ("Draft the revised goal order for Bruce", "", "practice", "", 3, "")],
         [("Start-up check for the Arkham Road crews", "", 12)], "part"),
        ("Stark Tool & Die quoting review", 8,
         "Reviewed a month of quotes with Pepper and Happy. Average time to quote is 53 "
         "hours. One-off tooling jobs are the ones that run long. Happy will review the "
         "pricing rule for them.",
         [_person(_who(world, "Stark Tool & Die"), "client"),
          _person(_who(world, "Stark Tool & Die", 1), "client")],
         [("Review the one-off pricing rule", "Happy Hogan", "other", "client", 4,
           "portal"),
          ("Share the list of one-off jobs from last quarter", "Pepper Potts", "other",
           "client", 6, "record_only"),
          ("Add one-off jobs to the price book", "", "practice", "", 10, "")], [], "part"),
        ("Globex Logistics dispatch walk-through", 12,
         "Walked a full dispatch day with Hank and the backup dispatcher. The five rules "
         "decided nearly every call. Frank still has to sign off the escalation list. "
         "Hank will review thin-lane pricing.",
         [_person(_who(world, "Globex Logistics"), "client"),
          _person(_who(world, "Globex Logistics", 1), "client")],
         [("Sign off the escalation list", "Frank Grimes", "other", "client", -5,
           "follow_up"),
          ("Review the thin-lane pricing", "Hank Scorpio", "other", "client", 6,
           "follow_up"),
          ("Send the backhaul contract to the two new shippers", "Hank Scorpio", "other",
           "client", 9, "record_only"),
          ("Share the fuel card report", "Frank Grimes", "other", "client", 11,
           "record_only"),
          ("Write up the dispatch day for the file", "", "practice", "", 3, "")],
         [("One-page escalation list", "", 5)], "all"),
        ("Hooli Field Services on-call review", 15,
         "Reviewed the new on-call rota with Gavin. Weekend call-outs for first-year "
         "technicians are down by half. Denpok has not approved the retention bonus. "
         "A recruiter Gavin uses, Jerry Maguire, joined for the last ten minutes.",
         [_person(_who(world, "Hooli Field Services"), "client"),
          _person(_who(world, "Hooli Field Services", 1), "client"),
          _person(next(p for p in world.partners if p.last_name == "Maguire"),
                  "referral_partner")],
         [("Approve the retention bonus", "Denpok Singh", "other", "client", 3,
           "follow_up"),
          ("Pull the on-call logs for the last quarter", "Gavin Belson", "other",
           "client", 4, "record_only"),
          ("Send three technician candidates", "Jerry Maguire", "other", "third_party",
           7, "follow_up"),
          ("Send the revised rota to the lead technicians", "Denpok Singh", "other",
           "client", 6, "record_only"),
          ("Share the exit interview notes with Gavin", "", "practice", "", 2, "")],
         [], "all"),
        ("Lunch and learn: payroll software", 9,
         "A vendor webinar on payroll software. No client or prospect attended and "
         "nothing was agreed.",
         [("Dwayne Hoover", "dwayne@ninesteps.example", "Sales", "Nine Steps Payroll",
           "vendor")],
         [("Book a follow-up demo", "Dwayne Hoover", "other", "vendor", 5, "")], [],
         "dismiss"),
    ]

    for index, (title, ago, summary, people, actions, deliverables, review) in enumerate(plan):
        day = today - timedelta(days=ago)
        first = summary.split(". ")[0] + "."
        payload = {
            "title": title, "meeting_date": day.isoformat(), "summary": summary,
            "participants": [{"name": name, "email": email, "title": job, "company": company,
                              "contact_type": kind, "excerpt": f"Attendees: {name}"}
                             for name, email, job, company, kind in people]
            + [{"name": owner.full_name, "email": owner.email, "title": "",
                "company": world.tenant.name, "contact_type": "coworker",
                "excerpt": f"Attendees: {owner.full_name}"}],
            "action_items": [{"text": text, "owner": who, "owner_side": side,
                              "owner_kind": kind,
                              "due_date": (today + timedelta(days=days)).isoformat(),
                              "excerpt": first}
                             for text, who, side, kind, days, _ in actions],
            "deliverables": [{"text": text, "owner": who,
                              "due_date": (today + timedelta(days=days)).isoformat(),
                              "excerpt": first}
                             for text, who, days in deliverables],
        }
        with at(moment(day, 17, 30)):
            source = MeetingSourceFile.objects.create(
                tenant=world.tenant, drive_file_id=f"demo-notes-{index + 1:02d}",
                drive_version="1", name=f"{title} - Notes by Gemini",
                mime_type="application/vnd.google-apps.document",
                drive_file_owner_email=owner.email, text=_transcript(title, summary, people,
                                                                    actions, owner),
                state=MeetingSourceFile.State.PARSING, fetched_at=moment(day, 17, 30))
            proposal = parsing._build(source, payload, None)
        if not review:
            continue
        with at(moment(day + timedelta(days=1), 8, 45)):
            if review == "dismiss":
                dismissal.dismiss(proposal, actor=owner,
                                  reason=MeetingProposal.DismissReason.VENDOR_PITCH,
                                  note="A sales webinar. Nothing to keep.")
                continue
            items = list(ProposalItem.objects.filter(proposal=proposal).order_by(
                "kind", "position"))
            by_email = {p.primary_email: p for group in world.people.values() for p in group}
            by_email.update({p.primary_email: p for p in world.partners})
            for item in items:
                if item.kind != ProposalItem.Kind.PARTICIPANT or \
                        item.state != ProposalItem.State.PENDING:
                    continue
                known = by_email.get(item.payload.get("parsed_email"))
                if known is None:
                    continue
                approval.approve_participant(
                    item, actor=owner, role="FF",
                    choice={"contact_id": str(known.pk),
                            "contact_type": item.payload["proposed_contact_type"]})
                approval.create_meeting(proposal, actor=owner)
            by_name = {f"{p.first_name} {p.last_name}": p for p in by_email.values()}
            for item in items:
                if item.kind == ProposalItem.Kind.PARTICIPANT:
                    continue
                spec = next((a for a in actions if a[0] == item.payload.get("text")), None)
                if item.kind == ProposalItem.Kind.DELIVERABLE:
                    if review == "all":
                        approval.approve_task_item(item, actor=owner, role="FF", choice={})
                    continue
                if spec is None or (review == "part" and not spec[5]):
                    continue                     # left for the reviewer
                text, who, side, kind, _days, outcome = spec
                if side != "other":
                    approval.approve_task_item(item, actor=owner, role="FF", choice={})
                    continue
                approval.approve_action_item(
                    item, actor=owner, role="FF",
                    choice={"owner_side": "other", "owner_kind": kind, "outcome": outcome,
                            "owner_contact_id": str(by_name[who].pk)})
            approval.settle(proposal)


def _transcript(title, summary, people, actions, owner) -> str:
    """The notes as the file would read: who was there, what was said, what
    was agreed."""
    names = ", ".join(name for name, *_ in people) + f", {owner.full_name}"
    lines = [title, "", f"Attendees: {names}", "", "Summary", summary, "", "Next steps"]
    lines += [f"- {who or owner.full_name}: {text}" for text, who, *_ in actions]
    return "\n".join(lines)


# -------------------------------------------------------------------- notes

def _notes(world) -> None:
    """A dozen notes: on people, on companies, on a task, on nothing; one
    behind a PIN, and one that began as a recording."""
    from django.contrib.auth.hashers import make_password

    from apps.crm.models import Task
    from apps.notes.models import Note

    owner, today = world.owner, world.today
    ripley, pam = world.staff["ripley"], world.staff["pam"]
    a_task = Task.objects.filter(client_company=world.companies["Acme Fasteners"],
                                 status="in_progress").first()
    plan = [
        ("Call with Wiley about second shift", "Wiley is ready to name a second-shift lead. "
         "He is choosing between two people and wants my view by Friday. Lean: the one who "
         "already covers handovers.", owner, 2, {"contact": _who(world, "Acme Fasteners")}),
        ("Bruce on the safety incident", "He is shaken by the Arkham Road injury and wants "
         "safety ahead of everything else. Do not argue the order; reorder and show how "
         "the scorecard work serves it.", owner, 5,
         {"contact": _who(world, "Wayne Industries")}),
        ("Globex: what Hank will not say in the room", "The backup dispatcher is his "
         "nephew. He will not hear that the role needs someone else until the numbers say "
         "it. Let the numbers say it.", owner, 9,
         {"company": world.companies["Globex Logistics"]}),
        ("Stark: quoting notes from the floor", "Estimators trust the price book for "
         "repeat jobs and ignore it for one-offs. The fix is a rule for one-offs, not a "
         "bigger book.", ripley, 7, {"company": world.companies["Stark Tool & Die"]}),
        ("Hooli: exit interview themes", "On-call, on-call, on-call. Then pay. Nobody "
         "mentioned the work itself, which is good news.", ripley, 14,
         {"contact": _who(world, "Hooli Field Services")}),
        ("Changeover standard: what second shift said", "Step 4 assumes a second person. "
         "After 10 pm there is only one. Rewrite step 4 for one person and a cart.",
         owner, 1, {"task": a_task}),
        ("Jack Donaghy after the session", "He will sign if the proposal names Kenneth as "
         "the owner on their side. He wants to promote from inside and be seen doing it.",
         owner, 5, {"contact": world.prospects["Jack Donaghy"]}),
        ("Rocky Balboa: before the call", "Six gyms, two new. Adrian runs the money. Ask "
         "who decides trainer pay; I think it is not him.", owner, 3,
         {"contact": world.prospects["Rocky Balboa"]}),
        ("Ben Wyatt: what he looks for in a referral", "Owner-led, $2m to $20m, and a "
         "books problem that is really an operations problem. Send him two a quarter.",
         owner, 20, {"contact": next(p for p in world.partners if p.last_name == "Wyatt")}),
        ("Ideas for the owners' breakfast talk", "Title: 'The meeting that ends on time'. "
         "Three stories: Wayne's close, Acme's huddle, Pied Piper's ten days.", owner, 11,
         {}),
        ("Travel checklist for on-site days", "Badge request a week ahead. Steel-toe "
         "boots in the car. Print the scorecard; plants do not like laptops.", pam, 25, {}),
    ]
    for title, body, author, ago, link in plan:
        with at(moment(today - timedelta(days=ago), 16, 40)):
            Note.objects.create(tenant=world.tenant, title=title, body=body,
                                created_by=author, **link)
    with at(moment(today - timedelta(days=30), 12)):
        Note.objects.create(
            tenant=world.tenant, title="Dunder Mifflin: the regional manager",
            body="Michael will agree to anything in a meeting and forget it by lunch. "
                 "Dwight is who makes things happen. Route every action through Dwight "
                 "and copy Michael.", created_by=owner,
            contact=_who(world, "Dunder Mifflin Paper"),
            # The PIN is 2468. It gates the view; it is not encryption.
            pin_hash=make_password("2468"), pin_set_at=moment(today - timedelta(days=30), 12))
    with at(moment(today - timedelta(days=4), 18, 5)):
        Note.objects.create(
            tenant=world.tenant, title="Drive home after Vandelay", title_is_auto=False,
            created_by=owner, company=world.companies["Vandelay Import-Export"],
            source=Note.Source.RECORDING, audio_duration_seconds=214,
            transcription_state=Note.TranscriptionState.DONE,
            transcript=("Okay, notes from Vandelay while I remember. The cycle counts are "
                        "working, accuracy on the top items is ninety six percent. Art "
                        "is happy. The returns cage is the problem, George keeps saying "
                        "he will clear it and it has been three weeks. I think it needs "
                        "a date and a second person. Also the broker wants a monthly "
                        "review and I said yes, first Tuesday. Remind me to put the "
                        "classification codes on next week's list."),
            summary_state=Note.SummaryState.ACCEPTED,
            proposed_summary=("Cycle counts are working: 96% accuracy on the top items. "
                              "The returns cage is stuck with George after three weeks; "
                              "it needs a date and a second person. Monthly review with "
                              "the broker agreed for the first Tuesday. Add "
                              "classification codes to next week's list."),
            summary=("Cycle counts are working: 96% accuracy on the top items. The "
                     "returns cage is stuck with George after three weeks; it needs a "
                     "date and a second person. Monthly review with the broker agreed "
                     "for the first Tuesday. Add classification codes to next week's "
                     "list."))


# -------------------------------------------------------------------- email

TOUCHES = [
    ("Wyatt", "A quick one from Denver",
     "Ben,\n\nTwo of your clients came up in conversation this month, both with the same "
     "problem: books that close late because the plant reports late. If that sounds like "
     "anyone else you look after, I am glad to have a first conversation.\n\nHope the "
     "quarter-end was kind to you."),
    ("Bailey", "Thinking of your manufacturing clients",
     "George,\n\nWe helped a four-site company get its month-end close from fourteen days "
     "to five this year. If a borrower of yours is always late with their numbers, that "
     "is usually an operations problem, and it is the kind we fix.\n\nCoffee next time I "
     "am near the bank?"),
    ("Woods", "One thing I am seeing",
     "Elle,\n\nThree owners in a row have told me their turnover problem is a pay "
     "problem. In each case it was the schedule. If a client of yours is losing people "
     "in their first year, I would be glad to take a look.\n\nThank you for the "
     "introduction to Lucille, by the way."),
    ("Flax", "Checking in",
     "Holly,\n\nIt has been a couple of months. We are full on the manufacturing side "
     "but have room for one more field-services company this quarter. If you meet an "
     "owner who is still the dispatcher, send them my way."),
    ("Welton", "After the workshop",
     "Rebecca,\n\nThank you again for having me at the forum. Two members have already "
     "asked for the meeting agenda; it is attached to this note for the rest. I would "
     "happily do the next one on scorecards."),
]


def _email(world) -> None:
    from apps.crm.models import Campaign, OutboxMessage, UnmatchedInbound
    from apps.crm.services import campaigns, outbox, unsubscribe

    tenant, owner, today = world.tenant, world.owner, world.today
    partners = {p.last_name: p for p in world.partners}

    # One campaign sent last month to the partners on the touches.
    with at(moment(today - timedelta(days=24), 10)):
        sent = Campaign.objects.create(
            tenant=tenant, name="Autumn note to referral partners", created_by=owner,
            subject="What we are seeing in owner-led companies this autumn",
            body_html=("<p>Hi {FirstName},</p><p>Three things came up again and again in "
                       "our work this quarter: closes that run late because plants "
                       "report late, schedules built on capacity nobody has measured, "
                       "and owners who are still the approval step for everything.</p>"
                       "<p>If any of that sounds like a client of yours, I am glad to "
                       "have a first conversation with them, with no obligation.</p>"
                       "<p>{FractionalName}</p>"))
        enrolled = [p for p in world.partners if p.referral_next_touch_at is not None][:24]
        result = campaigns.queue(sent, enrolled, actor=owner)
    with at(moment(today - timedelta(days=23), 9, 15)):
        for message in OutboxMessage.objects.filter(pk__in=result["queued"]):
            outbox.approve(message, actor=owner, role="FF")
    # One of them left marketing emails from the link in it.
    leaver = partners["Howell"] if "Howell" in partners else enrolled[-1]
    with at(moment(today - timedelta(days=22), 7, 50)):
        unsubscribe.unsubscribe(unsubscribe.read_token(unsubscribe.token_for(
            tenant_id=tenant.pk, category="marketing", contact_id=leaver.pk)))

    # One campaign still being written.
    with at(moment(today - timedelta(days=2), 15)):
        Campaign.objects.create(
            tenant=tenant, name="Invitation: the meeting that ends on time",
            created_by=owner, subject="A breakfast talk for owners, next month in Denver",
            body_html=("<p>Hi {FirstName},</p><p>Next month I am giving a short talk for "
                       "owners at the Denver Metro Chamber: how to run a weekly "
                       "leadership meeting that ends on time and solves something.</p>"
                       "<p>If you or a client would like a seat, reply and I will hold "
                       "one.</p><p>{FractionalName}</p>"))

    # Touch drafts waiting for approval in the Sending queue.
    for index, (last_name, subject, body) in enumerate(TOUCHES):
        partner = partners[last_name]
        with at(moment(today - timedelta(days=index % 3), 6, 30)):
            outbox.create_message(
                tenant=tenant, producer=OutboxMessage.Producer.REFERRAL_TOUCH,
                to_contact=partner, to_address=partner.primary_email, subject=subject,
                body_text=f"{body}\n\n{owner.full_name}\n{tenant.name}",
                actor=owner, role="FF", is_ai_generated=index != 4,
                send_by=moment(today + timedelta(days=7 - index), 6, 30),
                source_type="contact", source_id=partner.pk)

    # Two replies the app could not file by itself.
    for index, (name, address, subject, body, why) in enumerate((
            ("Lucius Fox", "lfox.personal@foxmail.example", "Re: Weekly update from "
             "Summit Operations Partners",
             "Sending from my own address as I am travelling. The overtime report is "
             "attached. Arkham Road is the outlier, as you guessed.",
             "The sender's address is not on any contact."),
            ("Accounts Payable", "ap@sheinhardtwig.example", "Re: Your strategy map",
             "Jack asked me to confirm we have your W-9 on file before the proposal is "
             "signed. Could you send a current copy?",
             "It answers a thread the app did not start."))):
        UnmatchedInbound.objects.create(
            tenant=tenant, provider="gmail", provider_message_id=f"demo-unmatched-{index}",
            gmail_thread_id=f"demo-thread-{index}", from_address=address, from_name=name,
            to_addresses=[tenant.from_address], subject=subject, body_text=body,
            body_stripped=body, reason=why,
            received_at=moment(today - timedelta(days=1 + index), 13, 20 + index))
