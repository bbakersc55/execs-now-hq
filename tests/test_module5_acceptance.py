"""Module 5 — AC-5.1 to AC-5.16.

The three that carry the most risk, and which the rest lean on:

- **AC-5.1 / AC-5.10** — the cursor. Three days of a closed laptop must lose
  nothing, and a parse failure must not advance it past unprocessed work.
- **AC-5.3 / AC-5.4** — matching proposes and never decides, and the reviewer
  can always reject every candidate and create new.
- **AC-5.8 / AC-5.14** — approval creates records and **authorises no send**,
  which is the promise the whole module's design rests on.
"""

from __future__ import annotations

import json
from urllib.parse import quote

import pytest
from django.utils import timezone

from apps.crm.models import Contact, ContactEmail, OutboxMessage, Task
from apps.meetings import approval, drive, ingest, matching, parsing
from apps.meetings.models import (
    DriveWatch, Meeting, MeetingParticipant, MeetingProposal, MeetingSourceFile,
    ProposalItem,
)
from apps.tenancy.models import AuditEvent

from . import registry_config  # noqa: F401
from .factories import (
    ClientCompanyFactory, CompanyFactory, ContactEmailFactory, ContactFactory,
    GmailConnectionFactory, MembershipFactory,
)

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"

FF_EMAIL = "bryan@getexecutivesnow.test"
CF_EMAIL = "cf@getexecutivesnow.test"


# ------------------------------------------------------------------ the double

class FakeDrive:
    """Drive at its boundary: pages in, text out. Nothing in these tests talks
    to Google, and nothing about the cursor is simulated — the real `ingest`
    decides when it moves."""

    def __init__(self, pages=None, texts=None):
        self.pages = pages or []
        self.texts = texts or {}
        self.calls = []
        self.fail = None
        self.described = []
        self.folder_fail = None

    def start_token(self):
        return "start"

    def changes(self, page_token, *, folder_id):
        self.calls.append(page_token)
        if self.fail:
            raise drive.DriveUnavailable(self.fail)
        for token, page in self.pages:
            if token == page_token:
                return page
        return drive.DrivePage(files=[], new_start_page_token=page_token)

    def text_of(self, drive_file):
        return self.texts.get(drive_file.file_id, "")

    def describe_folder(self, folder_id):
        self.described.append(folder_id)
        if self.folder_fail:
            raise drive.DriveUnavailable(self.folder_fail)
        return drive.FolderInfo(folder_id=folder_id, name="Gemini meeting notes",
                                files=14, readable=12)


def a_file(file_id, *, version="1", name=None, mime=drive.GOOGLE_DOC,
           owner=FF_EMAIL):
    return drive.DriveFile(file_id=file_id, version=version,
                           name=name or f"{file_id} notes", mime_type=mime,
                           owner_email=owner, web_view_link=f"https://d/{file_id}")


def one_page(files, *, token="start", next_token=""):
    return [(token, drive.DrivePage(files=files, next_page_token=next_token,
                                    new_start_page_token="after"))]


NOTES = """Attendees: Dana Reyes (dana@acme.invalid), Priya Shah, Tom Okafor.
Dana said she would send the Q3 margin breakdown by Friday.
We promised to rebuild the inspection checklist for Acme."""

PARSED = json.dumps({
    "title": "Acme operations review",
    "meeting_date": "2026-09-20",
    "summary": "A review of Acme's operations. Dispatch and margin reporting "
               "came up, and two things were agreed.",
    "participants": [
        {"name": "Dana Reyes", "email": "dana@acme.invalid", "title": "COO",
         "company": "Acme Facilities", "contact_type": "client",
         "excerpt": "Attendees: Dana Reyes (dana@acme.invalid)"},
        {"name": "Priya Shah", "email": "priya@acme.invalid", "title": "Ops lead",
         "company": "Acme Facilities", "contact_type": "client",
         "excerpt": "Attendees: Dana Reyes (dana@acme.invalid), Priya Shah"},
        {"name": "Tom Okafor", "email": "", "title": "", "company": "",
         "contact_type": "prospect", "excerpt": "Priya Shah, Tom Okafor."},
    ],
    "action_items": [
        {"text": "Send the Q3 margin breakdown", "owner": "Dana Reyes",
         "due_date": "2026-09-25",
         "excerpt": "Dana said she would send the Q3 margin breakdown by Friday."},
    ],
    "deliverables": [
        {"text": "Rebuild the inspection checklist", "owner": "", "due_date": None,
         "excerpt": "We promised to rebuild the inspection checklist for Acme."},
    ],
})


@pytest.fixture
def watch(seeded_tenant, in_tenant_a):
    return DriveWatch.objects.create(tenant=seeded_tenant, folder_id="folder-1")


@pytest.fixture
def ff_user(seeded_tenant):
    membership = MembershipFactory(tenant=seeded_tenant, role="FF")
    membership.user.email = FF_EMAIL
    membership.user.save(update_fields=["email"])
    return membership


# ------------------------------------------------------------------- AC-5.1

@pytest.mark.django_db
def test_ac_5_1_the_cursor_survives_three_days_of_a_closed_laptop(
    seeded_tenant, watch, fake_claude
):
    """Nothing polls for three days; three documents land; everything is
    ingested, in order, exactly once."""
    fake_claude.reply = PARSED
    client = FakeDrive(
        pages=one_page([a_file("f1"), a_file("f2"), a_file("f3")]),
        texts={"f1": NOTES, "f2": NOTES, "f3": NOTES})

    report = ingest.poll(seeded_tenant, client=client)
    assert len(report["recorded"]) == 3
    assert [f.drive_file_id for f in
            MeetingSourceFile.objects.order_by("created_at")] == ["f1", "f2", "f3"]
    assert MeetingProposal.objects.count() == 3
    watch.refresh_from_db()
    assert watch.page_token == "after", "the cursor moved once everything was safe"
    assert watch.last_error == ""


# ------------------------------------------------------------------- AC-5.2

@pytest.mark.django_db
def test_ac_5_2_three_polls_over_an_unchanged_folder_make_no_duplicates(
    seeded_tenant, watch, fake_claude
):
    fake_claude.reply = PARSED
    client = FakeDrive(pages=one_page([a_file("f1")]) + [
        ("after", drive.DrivePage(files=[a_file("f1")], new_start_page_token="after"))],
        texts={"f1": NOTES})

    for _ in range(3):
        ingest.poll(seeded_tenant, client=client)

    assert MeetingSourceFile.objects.count() == 1
    assert MeetingProposal.objects.count() == 1


# ------------------------------------------------------------- AC-5.3 / AC-5.4

@pytest.mark.django_db
def test_ac_5_3_matching_is_ranked_shown_and_never_guessed(seeded_tenant, watch,
                                                            fake_claude, in_tenant_a):
    """One known by email, one by domain + name, one unknown — and **nothing
    created or modified** at this point."""
    fake_claude.reply = PARSED
    acme = CompanyFactory(tenant=seeded_tenant, name="Acme Facilities")
    known = ContactFactory(tenant=seeded_tenant, first_name="Dana", last_name="Reyes",
                           company=acme)
    ContactEmailFactory(tenant=seeded_tenant, contact=known,
                        address="dana@acme.invalid", is_primary=True)
    colleague = ContactFactory(tenant=seeded_tenant, first_name="Priya",
                               last_name="Shah", company=acme)
    ContactEmailFactory(tenant=seeded_tenant, contact=colleague,
                        address="p.shah@acme.invalid", is_primary=True)
    before = Contact.objects.count()

    ingest.poll(seeded_tenant, client=FakeDrive(pages=one_page([a_file("f1")]),
                                                texts={"f1": NOTES}))

    items = {item.payload["parsed_name"]: item for item in ProposalItem.objects.filter(
        kind=ProposalItem.Kind.PARTICIPANT)}
    assert items["Dana Reyes"].payload["existing_candidates"][0]["match_reason"] == "email"
    assert items["Priya Shah"].payload["existing_candidates"][0]["match_reason"] == (
        "email_domain_and_name")
    assert items["Tom Okafor"].payload["existing_candidates"] == []
    # Both paths, always (FR-5.11).
    for item in items.values():
        assert item.payload["new_contact_candidate"]["first_name"]
    # AC-5.3's last line, and the whole point of the queue.
    assert Contact.objects.count() == before
    assert not Contact.objects.filter(first_name="Tom").exists()


@pytest.mark.django_db
def test_ac_5_4_a_rejected_match_creates_new_and_leaves_the_candidate_alone(
    seeded_tenant, ff_user, api, watch, fake_claude, in_tenant_a
):
    fake_claude.reply = PARSED
    acme = CompanyFactory(tenant=seeded_tenant, name="Acme Facilities")
    colleague = ContactFactory(tenant=seeded_tenant, first_name="Priya",
                               last_name="Shah", company=acme, title="Ops lead")
    ContactEmailFactory(tenant=seeded_tenant, contact=colleague,
                        address="p.shah@acme.invalid", is_primary=True)
    ingest.poll(seeded_tenant, client=FakeDrive(pages=one_page([a_file("f1")]),
                                                texts={"f1": NOTES}))
    item = ProposalItem.objects.get(kind=ProposalItem.Kind.PARTICIPANT,
                                    payload__parsed_name="Priya Shah")

    # The reviewer rejects the candidate and takes the "create new" path.
    made = api.as_(ff_user).post(f"/api/proposal-items/{item.pk}/approve/",
                                 {"contact_type": "client"},
                                 content_type="application/json")
    assert made.status_code == 201, made.content

    created = Contact.objects.filter(first_name="Priya").exclude(pk=colleague.pk).first()
    assert created is not None
    colleague.refresh_from_db()
    assert colleague.title == "Ops lead", "the candidate was not modified"


# ------------------------------------------------------------- AC-5.5 / AC-5.6

@pytest.mark.django_db
def test_ac_5_5_and_5_6_partial_approval_and_rejections_that_stay_rejected(
    seeded_tenant, ff_user, api, watch, fake_claude, in_tenant_a
):
    fake_claude.reply = json.dumps({
        "title": "A meeting", "meeting_date": None, "summary": "",
        "participants": [],
        "action_items": [
            {"text": f"Do thing {i}", "owner": "", "due_date": None,
             "excerpt": f"thing {i}"} for i in range(4)],
        "deliverables": [],
    })
    client = FakeDrive(pages=one_page([a_file("f1")]), texts={"f1": NOTES})
    ingest.poll(seeded_tenant, client=client)
    items = list(ProposalItem.objects.filter(kind=ProposalItem.Kind.ACTION_ITEM
                                             ).order_by("position"))
    assert len(items) == 4

    for item in items[:2]:
        assert api.as_(ff_user).post(f"/api/proposal-items/{item.pk}/approve/", {},
                                     content_type="application/json").status_code == 201
    for item in items[2:]:
        assert api.as_(ff_user).post(
            f"/api/proposal-items/{item.pk}/reject/").status_code == 200

    assert Task.objects.count() == 2
    assert ProposalItem.objects.filter(state=ProposalItem.State.REJECTED).count() == 2
    assert MeetingProposal.objects.first().state == MeetingProposal.State.ACTIONED

    # AC-5.6 — re-poll: the rejected items do not come back, and the unchanged
    # file yields no second proposal.
    ingest.poll(seeded_tenant, client=client)
    assert ProposalItem.objects.filter(state=ProposalItem.State.PENDING).count() == 0
    assert MeetingProposal.objects.count() == 1
    assert Task.objects.count() == 2


# ------------------------------------------------------------------- AC-5.7

@pytest.mark.django_db
def test_ac_5_7_every_item_shows_the_passage_it_came_from(seeded_tenant, watch,
                                                           fake_claude, in_tenant_a):
    fake_claude.reply = PARSED
    ingest.poll(seeded_tenant, client=FakeDrive(pages=one_page([a_file("f1")]),
                                                texts={"f1": NOTES}))
    for item in ProposalItem.objects.all():
        assert item.source_excerpt, f"{item.kind} has no excerpt"
        # And it is the document's own words, not a paraphrase.
        assert item.source_excerpt[:24] in NOTES


# ------------------------------------------------------------------- AC-5.8

@pytest.mark.django_db
def test_ac_5_8_approval_creates_records_and_authorises_no_send(
    seeded_tenant, ff_user, api, watch, fake_claude, dev_outbox, in_tenant_a
):
    """The promise the whole module rests on."""
    from apps.work.models import Stakeholder

    company = ClientCompanyFactory(tenant=seeded_tenant, name="Acme Facilities")
    watcher = ContactFactory(tenant=seeded_tenant, first_name="Nina", last_name="Ruiz",
                             company=company)
    ContactEmailFactory(tenant=seeded_tenant, contact=watcher,
                        address="nina@acme.invalid", is_primary=True)
    fake_claude.reply = json.dumps({
        "title": "A meeting", "meeting_date": None, "summary": "", "participants": [],
        "action_items": [],
        "deliverables": [{"text": "Rebuild the inspection checklist", "owner": "",
                          "due_date": None, "excerpt": "We promised to rebuild it."}],
    })
    ingest.poll(seeded_tenant, client=FakeDrive(pages=one_page([a_file("f1")]),
                                                texts={"f1": NOTES}))
    item = ProposalItem.objects.get(kind=ProposalItem.Kind.DELIVERABLE)

    made = api.as_(ff_user).post(f"/api/proposal-items/{item.pk}/approve/", {
        "client_company": str(company.pk),
        "stakeholders": [{"contact_id": str(watcher.pk), "cadence": "every_update"}],
    }, content_type="application/json")
    assert made.status_code == 201, made.content

    task = Task.objects.get()
    assert Stakeholder.objects.filter(task=task, contact=watcher,
                                      cadence="every_update").exists()
    # **Nothing left the building.**
    assert dev_outbox == []
    assert OutboxMessage.all_objects.filter(state="sent").count() == 0


# ------------------------------------------------------------------- AC-5.9

@pytest.mark.django_db
def test_ac_5_9_unsupported_files_are_recorded_and_skipped_with_a_reason(
    seeded_tenant, watch, fake_claude, in_tenant_a
):
    fake_claude.reply = PARSED
    client = FakeDrive(
        pages=one_page([a_file("pdf1", mime="application/pdf"),
                        a_file("mp4", mime="video/mp4"),
                        a_file("good")]),
        texts={"good": NOTES})

    report = ingest.poll(seeded_tenant, client=client)

    skipped = {f.drive_file_id: f for f in report["skipped"]}
    assert set(skipped) == {"pdf1", "mp4"}
    assert "PDF" in skipped["pdf1"].skip_reason
    assert "video" in skipped["mp4"].skip_reason.lower()
    # Neither blocked the good one dropped alongside them.
    good = MeetingSourceFile.objects.get(drive_file_id="good")
    assert good.state == MeetingSourceFile.State.PARSED
    assert MeetingProposal.objects.count() == 1


# ------------------------------------------------------------------ AC-5.10

@pytest.mark.django_db
def test_ac_5_10_a_parse_failure_is_retryable_and_keeps_its_place(
    seeded_tenant, watch, fake_claude, in_tenant_a
):
    from apps.tenancy import claude

    fake_claude.raise_exc = claude.ClaudeUnavailable("Anthropic rejected the key.")
    client = FakeDrive(pages=one_page([a_file("f1")]), texts={"f1": NOTES})

    report = ingest.poll(seeded_tenant, client=client)
    source = MeetingSourceFile.objects.get()
    assert source.state == MeetingSourceFile.State.FAILED
    assert "key" in source.error
    assert len(report["failed"]) == 1
    assert MeetingProposal.objects.count() == 0
    # The file is still pending work, and the health screen says so.
    assert ingest.health(seeded_tenant)["files_failed"] == 1
    assert source.is_pending

    # Put the key back and retry: the same file parses, from the text already
    # fetched, and no second trip to Drive is needed.
    fake_claude.raise_exc = None
    fake_claude.reply = PARSED
    ingest.poll(seeded_tenant, client=client)
    source.refresh_from_db()
    assert source.state == MeetingSourceFile.State.PARSED
    assert MeetingProposal.objects.count() == 1


# ------------------------------------------------------------------ AC-5.12

@pytest.mark.django_db
def test_ac_5_12_approval_puts_the_meeting_on_every_participants_timeline(
    seeded_tenant, ff_user, api, watch, fake_claude, in_tenant_a
):
    fake_claude.reply = PARSED
    ClientCompanyFactory(tenant=seeded_tenant, name="Acme Facilities")
    ingest.poll(seeded_tenant, client=FakeDrive(pages=one_page([a_file("f1")]),
                                                texts={"f1": NOTES}))
    proposal = MeetingProposal.objects.get()

    # The drafted summary is reviewed with the proposal, and edited (R11a).
    edited = api.as_(ff_user).patch(f"/api/meeting-proposals/{proposal.pk}/",
                                    {"summary": "Dispatch and margin reporting, and "
                                                "two things agreed."},
                                    content_type="application/json")
    assert edited.status_code == 200

    for item in ProposalItem.objects.filter(kind=ProposalItem.Kind.PARTICIPANT):
        assert api.as_(ff_user).post(f"/api/proposal-items/{item.pk}/approve/",
                                     {"contact_type": "client"},
                                     content_type="application/json").status_code == 201

    assert Meeting.objects.count() == 1, "one meeting, however many participants"
    meeting = Meeting.objects.get()
    assert meeting.summary.startswith("Dispatch and margin reporting")
    assert meeting.web_view_link == "https://d/f1"
    assert MeetingParticipant.objects.filter(meeting=meeting).count() == 3
    assert meeting.client_company is not None


@pytest.mark.django_db
def test_ac_5_12_a_discarded_summary_still_makes_the_meeting(
    seeded_tenant, ff_user, api, watch, fake_claude, in_tenant_a
):
    fake_claude.reply = PARSED
    ingest.poll(seeded_tenant, client=FakeDrive(pages=one_page([a_file("f1")]),
                                                texts={"f1": NOTES}))
    proposal = MeetingProposal.objects.get()
    api.as_(ff_user).patch(f"/api/meeting-proposals/{proposal.pk}/",
                           {"summary_discarded": True}, content_type="application/json")
    item = ProposalItem.objects.filter(kind=ProposalItem.Kind.PARTICIPANT).first()
    api.as_(ff_user).post(f"/api/proposal-items/{item.pk}/approve/",
                          {"contact_type": "client"}, content_type="application/json")

    meeting = Meeting.objects.get()
    assert meeting.summary == ""
    assert MeetingParticipant.objects.filter(meeting=meeting).count() == 1


# ------------------------------------------------------------------ AC-5.13

@pytest.mark.django_db
def test_ac_5_13_a_contact_type_is_proposed_confirmed_and_added_never_replaced(
    seeded_tenant, ff_user, api, watch, fake_claude, in_tenant_a
):
    from apps.crm.models import ContactTypeLink
    from apps.crm.services import pipeline as pipeline_service

    fake_claude.reply = PARSED
    acme = CompanyFactory(tenant=seeded_tenant, name="Acme Facilities")
    existing = ContactFactory(tenant=seeded_tenant, first_name="Dana", last_name="Reyes",
                              company=acme)
    ContactEmailFactory(tenant=seeded_tenant, contact=existing,
                        address="dana@acme.invalid", is_primary=True)
    from apps.crm.services import referral

    referral.add_type(existing, "client")
    stage_before = list(existing.pipeline_positions.values_list("stage_id", flat=True))

    ingest.poll(seeded_tenant, client=FakeDrive(pages=one_page([a_file("f1")]),
                                                texts={"f1": NOTES}))
    items = {i.payload["parsed_name"]: i for i in ProposalItem.objects.filter(
        kind=ProposalItem.Kind.PARTICIPANT)}
    # Every participant arrives with a proposed type.
    assert items["Tom Okafor"].payload["proposed_contact_type"] == "prospect"

    # Changed before approving, and the created contact carries what was chosen.
    api.as_(ff_user).post(f"/api/proposal-items/{items['Tom Okafor'].pk}/approve/",
                          {"contact_type": "coworker"}, content_type="application/json")
    tom = Contact.objects.get(first_name="Tom")
    assert [link.contact_type.code for link in
            ContactTypeLink.objects.filter(contact=tom)] == ["coworker"]

    # Matched to an existing client: the new type is **added**, `client` stays,
    # and the pipeline stage is untouched (FR-5.9d).
    api.as_(ff_user).post(f"/api/proposal-items/{items['Dana Reyes'].pk}/approve/",
                          {"contact_id": str(existing.pk), "contact_type": "prospect"},
                          content_type="application/json")
    codes = set(ContactTypeLink.objects.filter(contact=existing).values_list(
        "contact_type__code", flat=True))
    assert codes == {"client", "prospect"}
    assert list(existing.pipeline_positions.values_list("stage_id", flat=True)) == \
        stage_before
    assert pipeline_service is not None


# ------------------------------------------------------------------ AC-5.14

@pytest.mark.django_db
def test_ac_5_14_confirming_a_referral_partner_queues_onboarding_and_sends_nothing(
    seeded_tenant, ff_user, api, watch, fake_claude, dev_outbox, in_tenant_a
):
    fake_claude.reply = PARSED
    ingest.poll(seeded_tenant, client=FakeDrive(pages=one_page([a_file("f1")]),
                                                texts={"f1": NOTES}))
    item = ProposalItem.objects.get(kind=ProposalItem.Kind.PARTICIPANT,
                                    payload__parsed_name="Tom Okafor")

    made = api.as_(ff_user).post(f"/api/proposal-items/{item.pk}/approve/",
                                 {"contact_type": "referral_partner"},
                                 content_type="application/json")
    assert made.status_code == 201, made.content

    tom = Contact.objects.get(first_name="Tom")
    draft = OutboxMessage.all_objects.filter(
        producer=OutboxMessage.Producer.REFERRAL_ONBOARDING, to_contact=tom).first()
    assert draft is not None
    assert draft.state == OutboxMessage.State.PENDING_APPROVAL
    tom.refresh_from_db()
    assert tom.referral_next_touch_at is not None, "the cadence clock started"
    # **Nothing sent.** Approving queues; the send is its own gate.
    assert dev_outbox == []


# ------------------------------------------------------------------ AC-5.15

@pytest.mark.django_db
def test_ac_5_15_a_vendor_is_not_created_without_the_categories_that_find_them(
    seeded_tenant, ff_user, api, watch, fake_claude, in_tenant_a
):
    from apps.crm.models import ContactServiceCategory

    fake_claude.reply = PARSED
    ingest.poll(seeded_tenant, client=FakeDrive(pages=one_page([a_file("f1")]),
                                                texts={"f1": NOTES}))
    item = ProposalItem.objects.get(kind=ProposalItem.Kind.PARTICIPANT,
                                    payload__parsed_name="Tom Okafor")

    refused = api.as_(ff_user).post(f"/api/proposal-items/{item.pk}/approve/",
                                    {"contact_type": "vendor"},
                                    content_type="application/json")
    assert refused.status_code == 400
    assert "service category" in refused.json()["detail"]
    assert not Contact.objects.filter(first_name="Tom").exists()

    made = api.as_(ff_user).post(
        f"/api/proposal-items/{item.pk}/approve/",
        {"contact_type": "vendor", "service_categories": ["Grease trap cleaning",
                                                          "Duct cleaning"]},
        content_type="application/json")
    assert made.status_code == 201
    tom = Contact.objects.get(first_name="Tom")
    assert ContactServiceCategory.objects.filter(contact=tom).count() == 2
    # Searchable by what they do, the moment they exist.
    found = api.as_(ff_user).get("/api/contacts/by-category/?category=Duct cleaning")
    assert found.status_code == 200
    assert "Tom" in found.content.decode()


# ------------------------------------------------------------------ AC-5.16

@pytest.mark.django_db
def test_ac_5_16_the_cf_proposal_scope_has_exactly_two_limbs(
    seeded_tenant, ff_user, api, watch, fake_claude, in_tenant_a
):
    """(a) matched to an assigned company, (b) the CF's own file, (c) the FF's
    prospect meeting — which is **404** to the CF."""
    from .factories import ClientAssignmentFactory

    cf = MembershipFactory(tenant=seeded_tenant, role="CF")
    cf.user.email = CF_EMAIL
    cf.user.save(update_fields=["email"])
    company = ClientCompanyFactory(tenant=seeded_tenant, name="Acme Facilities")
    ClientAssignmentFactory(tenant=seeded_tenant, user=cf.user, company=company)
    known = ContactFactory(tenant=seeded_tenant, first_name="Dana", last_name="Reyes",
                           company=company)
    ContactEmailFactory(tenant=seeded_tenant, contact=known,
                        address="dana@acme.invalid", is_primary=True)
    va = MembershipFactory(tenant=seeded_tenant, role="VA")

    fake_claude.reply = PARSED
    ingest.poll(seeded_tenant, client=FakeDrive(
        pages=one_page([a_file("matched", owner=FF_EMAIL)]), texts={"matched": NOTES}))
    # (b) and (c) have no matched participants at all.
    bare = json.dumps({"title": "A meeting", "meeting_date": None, "summary": "",
                       "participants": [{"name": "Nobody Known", "email": "",
                                         "title": "", "company": "",
                                         "contact_type": "prospect", "excerpt": "x"}],
                       "action_items": [], "deliverables": []})
    fake_claude.reply = bare
    ingest.poll(seeded_tenant, client=FakeDrive(
        pages=[("after", drive.DrivePage(
            files=[a_file("cfown", owner=CF_EMAIL), a_file("ffonly", owner=FF_EMAIL)],
            new_start_page_token="later"))],
        texts={"cfown": NOTES, "ffonly": NOTES}))

    # Everything was captured with its owner, which is what the second limb
    # reads.
    owners = {f.drive_file_id: f.drive_file_owner_email
              for f in MeetingSourceFile.objects.all()}
    assert owners == {"matched": FF_EMAIL, "cfown": CF_EMAIL, "ffonly": FF_EMAIL}

    def visible(member):
        body = api.as_(member).get("/api/meeting-proposals/?state=all").json()
        return {row["source_file"]["name"].split(" ")[0] for row in body}

    assert visible(cf) == {"matched", "cfown"}
    assert visible(ff_user) == {"matched", "cfown", "ffonly"}
    assert visible(va) == {"matched", "cfown", "ffonly"}

    # And the FF's prospect meeting is 404 to the CF, not 403.
    ff_only = MeetingProposal.objects.get(source_file__drive_file_id="ffonly")
    assert api.as_(cf).get(f"/api/meeting-proposals/{ff_only.pk}/").status_code == 404


# ------------------------------------------------------------------ AC-5.11

@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FCC", "ECC"])
def test_ac_5_11_a_client_role_reaches_none_of_it(role, seeded_tenant, api, watch,
                                                   in_tenant_a):
    company = ClientCompanyFactory(tenant=seeded_tenant)
    member = MembershipFactory(tenant=seeded_tenant, role=role, client_company=company)
    for url in ("/api/meeting-proposals/", "/api/drive-watch/", "/api/proposal-items/"):
        assert api.as_(member).get(url).status_code == 403, url
    assert api.as_(member).post("/api/drive-watch/sync/").status_code == 403
    # And there is nothing to navigate to: no route in this module answers a
    # client role with anything but a refusal.


@pytest.mark.django_db
def test_ac_5_11_another_tenants_queue_is_404(seeded_tenant, ff_user, api, tenant_b,
                                               in_tenant_a):
    from .factories import MeetingProposalFactory

    theirs = MeetingProposalFactory(tenant=tenant_b)
    assert api.as_(ff_user).get(
        f"/api/meeting-proposals/{theirs.pk}/").status_code == 404


# --------------------------------------------------------------------- FR-5.17

@pytest.mark.django_db
def test_a_reparse_supersedes_and_leaves_approved_items_alone(
    seeded_tenant, ff_user, api, watch, fake_claude, in_tenant_a
):
    fake_claude.reply = PARSED
    ingest.poll(seeded_tenant, client=FakeDrive(pages=one_page([a_file("f1")]),
                                                texts={"f1": NOTES}))
    proposal = MeetingProposal.objects.get()
    approved = ProposalItem.objects.get(kind=ProposalItem.Kind.ACTION_ITEM)
    api.as_(ff_user).post(f"/api/proposal-items/{approved.pk}/approve/", {},
                          content_type="application/json")

    fresh = api.as_(ff_user).post(f"/api/meeting-proposals/{proposal.pk}/reparse/")
    assert fresh.status_code == 201
    proposal.refresh_from_db()
    approved.refresh_from_db()
    assert proposal.state == MeetingProposal.State.SUPERSEDED
    assert approved.state == ProposalItem.State.APPROVED, "a decision already made stands"
    assert Task.objects.count() == 1, "and its record was not made twice"
    assert MeetingProposal.objects.count() == 2


# ================================================ connecting the folder (FR-5.1a)
#
# The gap this closes: Module 5 shipped with a queue and no way to point it at
# a folder. Connecting has **two steps that fail separately** — granting the
# app `drive.readonly`, and naming the folder — so the screen and the API both
# keep them apart, and a practice stuck on one is never told about the other.


@pytest.fixture
def fake_client(monkeypatch):
    """Stand in for Drive at `ingest.client_for`, which is the one place the
    views reach Google through."""
    client = FakeDrive()
    monkeypatch.setattr(ingest, "client_for", lambda tenant: client)
    return client


@pytest.fixture
def drive_granted(seeded_tenant, ff_user):
    """A Google connection that has actually been granted Drive."""
    return GmailConnectionFactory(
        tenant=seeded_tenant, user=ff_user.user, email_address=FF_EMAIL,
        scopes=["https://www.googleapis.com/auth/gmail.send", DRIVE_SCOPE])


@pytest.mark.parametrize("pasted,expected", [
    # The address bar, which is what a person actually has.
    ("https://drive.google.com/drive/folders/1AbCdEfGh_1", "1AbCdEfGh_1"),
    ("https://drive.google.com/drive/folders/1AbCdEfGh_1?usp=sharing", "1AbCdEfGh_1"),
    ("https://drive.google.com/drive/u/0/folders/1AbCdEfGh_1", "1AbCdEfGh_1"),
    ("https://drive.google.com/drive/folders/1AbCdEfGh_1/", "1AbCdEfGh_1"),
    ("drive.google.com/drive/folders/1AbCdEfGh_1", "1AbCdEfGh_1"),
    # The older "Get link" form.
    ("https://drive.google.com/open?id=1AbCdEfGh_1", "1AbCdEfGh_1"),
    # The id on its own still works.
    ("1AbCdEfGh_1", "1AbCdEfGh_1"),
    ("  1AbCdEfGh_1  ", "1AbCdEfGh_1"),
    # And what is not a folder at all fails here, before anything is saved.
    ("", ""),
    ("https://drive.google.com/file/d/1AbCdEfGh_1/view", ""),
    ("my meeting notes", ""),
    ("https://example.invalid/", ""),
])
def test_the_folder_id_comes_out_of_whatever_was_pasted(pasted, expected):
    """FR-5.1a. **Nobody has the id; everybody has the address.** Asking a
    person to cut the id out of a URL by hand is asking for `?usp=sharing` to
    come with it."""
    assert drive.folder_id_from(pasted) == expected


@pytest.mark.django_db
def test_checking_a_folder_reads_it_and_saves_nothing(
    seeded_tenant, ff_user, api, fake_client, drive_granted, in_tenant_a
):
    """Step two, dry. The whole pasted URL goes to the server, which is why the
    id never has to survive a copy-paste."""
    response = api.as_(ff_user).post("/api/drive-watch/check/", {
        "folder": "https://drive.google.com/drive/folders/1AbCdEfGh_1?usp=sharing"})

    assert response.status_code == 200, response.data
    assert response.data == {"folder_id": "1AbCdEfGh_1", "name": "Gemini meeting notes",
                             "files": 14, "readable": 12, "truncated": False}
    assert fake_client.described == ["1AbCdEfGh_1"]
    # Checking is not connecting.
    assert not DriveWatch.objects.exists()


@pytest.mark.django_db
def test_connecting_verifies_the_folder_before_it_saves_the_watch(
    seeded_tenant, ff_user, api, fake_client, drive_granted, in_tenant_a
):
    """FR-5.1a — a watch is never created on an unread folder. The name shown
    on the screen afterwards is the one Drive gave, not one we invented."""
    response = api.as_(ff_user).post("/api/drive-watch/", {
        "folder": "https://drive.google.com/drive/folders/1AbCdEfGh_1"})

    assert response.status_code == 201, response.data
    watch = DriveWatch.objects.get()
    assert watch.folder_id == "1AbCdEfGh_1"
    assert watch.folder_name == "Gemini meeting notes"
    assert watch.is_active
    assert response.data["connected"] is True
    assert response.data["folder_name"] == "Gemini meeting notes"
    assert AuditEvent.all_objects.filter(verb="drive.folder_connected").exists()


@pytest.mark.django_db
def test_a_folder_drive_refuses_is_refused_here(
    seeded_tenant, ff_user, api, fake_client, drive_granted, in_tenant_a
):
    """The failure this whole step exists to prevent: a watch that quietly
    returns nothing every ten minutes because the id was a typo."""
    fake_client.folder_fail = "That folder is in the Drive bin."

    response = api.as_(ff_user).post("/api/drive-watch/", {"folder": "1AbCdEfGh_1"})

    assert response.status_code == 400
    assert response.data["detail"] == "That folder is in the Drive bin."
    assert not DriveWatch.objects.exists()


@pytest.mark.django_db
def test_nonsense_is_refused_without_troubling_drive(
    seeded_tenant, ff_user, api, fake_client, drive_granted, in_tenant_a
):
    response = api.as_(ff_user).post("/api/drive-watch/", {"folder": "my notes folder"})

    assert response.status_code == 400
    assert "Drive folder" in response.data["detail"]
    assert fake_client.described == []


@pytest.mark.django_db
def test_without_the_drive_scope_connecting_says_which_half_is_missing(
    seeded_tenant, ff_user, api, in_tenant_a
):
    """A connection that sends mail perfectly well and cannot see a single
    file. **The two halves fail separately**, so the message names the half."""
    GmailConnectionFactory(tenant=seeded_tenant, user=ff_user.user,
                           email_address=FF_EMAIL, scopes=["gmail.send"])

    response = api.as_(ff_user).post("/api/drive-watch/", {"folder": "1AbCdEfGh_1"})

    assert response.status_code == 409
    assert "has not granted access to Drive" in response.data["detail"]

    health = api.as_(ff_user).get("/api/drive-watch/").data
    assert health["google_connected"] is True
    assert health["drive_access"] is False


@pytest.mark.django_db
def test_health_names_the_account_that_holds_the_drive_grant(
    seeded_tenant, ff_user, api, drive_granted, in_tenant_a
):
    """In a practice with several connected accounts, the one that granted
    Drive is not necessarily the first one made."""
    GmailConnectionFactory(tenant=seeded_tenant, email_address="cf@x.test",
                           scopes=["gmail.send"])

    health = api.as_(ff_user).get("/api/drive-watch/").data

    assert health["drive_access"] is True
    assert health["drive_account"] == FF_EMAIL
    assert health["connected"] is False           # Drive, yes. A folder, not yet.


@pytest.mark.django_db
def test_the_consent_url_asks_for_drive_and_keeps_gmail_send(
    seeded_tenant, ff_user, api, settings, in_tenant_a
):
    """Re-consenting for Drive must not cost the practice its ability to send
    mail halfway through the afternoon."""
    settings.GOOGLE_OAUTH_CLIENT_ID = "client-id"
    settings.GOOGLE_OAUTH_CLIENT_SECRET = "secret"

    response = api.as_(ff_user).post("/api/drive-watch/consent/")

    assert response.status_code == 200
    url = response.data["authorization_url"]
    assert quote(DRIVE_SCOPE, safe="") in url
    assert quote("https://www.googleapis.com/auth/gmail.send", safe="") in url
    assert "include_granted_scopes=true" in url


@pytest.mark.django_db
def test_disconnecting_stops_looking_and_forgets_nothing(
    seeded_tenant, ff_user, api, watch, in_tenant_a
):
    """"Stop looking", not "forget what you read": the cursor and every
    proposal already made survive, so reconnecting the same folder picks up
    where it left off instead of replaying it."""
    watch.page_token = "cursor-42"
    watch.save(update_fields=["page_token"])

    response = api.as_(ff_user).post("/api/drive-watch/disconnect/")

    assert response.status_code == 200
    assert response.data["connected"] is False
    watch.refresh_from_db()
    assert watch.is_active is False
    assert watch.page_token == "cursor-42"
    assert AuditEvent.all_objects.filter(verb="drive.folder_disconnected").exists()


@pytest.mark.django_db
def test_reconnecting_the_same_folder_keeps_its_place_a_different_one_starts_over(
    seeded_tenant, ff_user, api, watch, fake_client, drive_granted, in_tenant_a
):
    """An old cursor describes a run we are still doing only if the folder is
    the same one."""
    watch.page_token = "cursor-42"
    watch.is_active = False
    watch.save(update_fields=["page_token", "is_active"])

    api.as_(ff_user).post("/api/drive-watch/", {"folder": watch.folder_id})
    watch.refresh_from_db()
    assert watch.page_token == "cursor-42"
    assert watch.is_active is True

    api.as_(ff_user).post("/api/drive-watch/", {"folder": "1AbCdEfGh_1"})
    watch.refresh_from_db()
    assert watch.folder_id == "1AbCdEfGh_1"
    assert watch.page_token == ""


@pytest.mark.django_db
@pytest.mark.parametrize("role,expected", [("FF", 201), ("CF", 403), ("VA", 403)])
def test_11_10_connecting_the_folder_is_the_founders(
    role, expected, seeded_tenant, ff_user, api, fake_client, drive_granted, in_tenant_a
):
    """Matrix 11.10 — narrower than *using* the queue, which is the VA's job.
    Pointing the app at a folder grants it a standing read of a Drive, and that
    decision belongs with the person who answers for the practice's data."""
    membership = ff_user if role == "FF" else MembershipFactory(tenant=seeded_tenant,
                                                                role=role)
    response = api.as_(membership).post("/api/drive-watch/", {"folder": "1AbCdEfGh_1"})
    assert response.status_code == expected
    assert DriveWatch.objects.exists() is (expected == 201)


@pytest.mark.django_db
@pytest.mark.parametrize("url", ["/api/drive-watch/", "/api/drive-watch/check/",
                                 "/api/drive-watch/consent/",
                                 "/api/drive-watch/disconnect/"])
@pytest.mark.parametrize("role", ["CF", "VA"])
def test_only_the_founder_reaches_any_connect_route(
    url, role, seeded_tenant, api, in_tenant_a
):
    membership = MembershipFactory(tenant=seeded_tenant, role=role)
    assert api.as_(membership).post(url, {"folder": "1AbCdEfGh_1"}).status_code == 403
