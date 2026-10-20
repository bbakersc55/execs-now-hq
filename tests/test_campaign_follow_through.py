"""Campaign follow-through (owner, 2026-10-19).

1. The campaign's own files: up to three, within the size limit, copied onto
   every draft it makes from then on.
2. "When this campaign is sent": a stage move and referral touches at a
   cadence, per person, only when their draft is approved and sent; never at
   enrolment, never for a draft refused or suppressed, and **never for anyone
   unsubscribed**. Each lands on the contact's history and on Activity.
3. Replies that ask to leave: marked "Asked to leave", and one click does
   exactly what the email's link does. Nothing happens without the click.
4. The audience list's count (the screen; `Campaigns.test.tsx`).
5. Isolation and role boundaries.
"""

from __future__ import annotations

import base64

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.crm.models import (
    CampaignAttachment, CampaignRecipient, EmailMessage, EmailSuppression, Enrollment,
    OutboxAttachment, OutboxMessage, StageChange,
)
from apps.crm.services import campaigns, enrollment, inbound, leaving, outbox, pipeline, timeline
from apps.tenancy.models import AuditEvent, Role

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import CampaignFactory, ContactEmailFactory, ContactFactory
from .test_campaigns import person

S = OutboxMessage.State


@pytest.fixture
def campaign(seeded_tenant, ff):
    return CampaignFactory(tenant=seeded_tenant, created_by=ff.user)


def a_file(name="flyer.pdf", size=1000):
    return SimpleUploadedFile(name, b"%PDF" + b"x" * (size - 4),
                              content_type="application/pdf")


def upload(api, user, campaign, name="flyer.pdf", size=1000):
    return api.as_(user).post(f"/api/campaigns/{campaign.pk}/attachments/",
                              {"file": a_file(name, size)})


def partner(tenant, first, ff):
    from apps.crm.services import referral

    contact = person(tenant, first)
    referral.add_type(contact, "referral_partner", actor=ff.user, onboard=False)
    return contact


def second_stage(tenant):
    """The sales pipeline's second stage: somewhere a new contact is not."""
    from apps.crm.models import PipelineStage

    sales = pipeline.sales_pipeline(tenant)
    return PipelineStage.all_objects.filter(pipeline=sales).order_by("position")[1]


def draft_for(contact):
    return CampaignRecipient.objects.get(contact=contact).outbox_message


# ========================================================== 1. the files

@pytest.mark.django_db
def test_up_to_three_files_within_the_limit_are_copied_onto_every_draft(
        seeded_tenant, ff, api, campaign, in_tenant_a, monkeypatch):
    for n in range(3):
        assert upload(api, ff, campaign, f"file{n}.pdf").status_code == 201
    fourth = upload(api, ff, campaign, "file3.pdf")
    assert fourth.status_code == 400 and "at most 3" in fourth.json()["detail"]
    from apps.crm import views

    monkeypatch.setattr(views, "MAX_ATTACHMENT_BYTES", 500)
    gone = CampaignAttachment.objects.filter(campaign=campaign).first()
    api.as_(ff).delete(f"/api/campaigns/{campaign.pk}/attachments/{gone.pk}/")
    too_big = upload(api, ff, campaign, "big.pdf", size=600)
    assert too_big.status_code == 400 and "limit" in too_big.json()["detail"]
    monkeypatch.undo()

    dana, priya = person(seeded_tenant, "Dana"), person(seeded_tenant, "Priya")
    campaigns.queue(campaign, [dana, priya], actor=ff.user)
    kept = set(CampaignAttachment.objects.filter(campaign=campaign)
               .values_list("stored_file_id", flat=True))
    for contact in (dana, priya):
        files = OutboxAttachment.objects.filter(outbox_message=draft_for(contact))
        assert set(files.values_list("stored_file_id", flat=True)) == kept
        assert len(kept) == 2
    shown = api.as_(ff).get(f"/api/campaigns/{campaign.pk}/").json()["attachments"]
    assert sorted(f["filename"] for f in shown) == ["file1.pdf", "file2.pdf"]
    # Removing one from the campaign leaves the drafts already made alone.
    one = CampaignAttachment.objects.filter(campaign=campaign).first()
    api.as_(ff).delete(f"/api/campaigns/{campaign.pk}/attachments/{one.pk}/")
    assert OutboxAttachment.objects.filter(outbox_message=draft_for(dana)).count() == 2


@pytest.mark.django_db
def test_the_files_go_out_with_the_email(seeded_tenant, ff, api, campaign, dev_outbox,
                                         in_tenant_a):
    upload(api, ff, campaign, "flyer.pdf")
    dana = person(seeded_tenant, "Dana")
    campaigns.queue(campaign, [dana], actor=ff.user)
    outbox.approve(draft_for(dana), actor=ff.user, role=Role.FF)
    assert draft_for(dana).state == S.SENT
    assert [a[0] for a in dev_outbox[-1].attachments] == ["flyer.pdf"]


# ================================================= 2. when it is sent

@pytest.fixture
def following(seeded_tenant, ff, campaign, in_tenant_a):
    campaign.on_sent_stage = second_stage(seeded_tenant)
    campaign.on_sent_cadence = "quarterly"
    campaign.save()
    return campaign


@pytest.mark.django_db
def test_nothing_happens_at_enrolment_and_both_happen_when_the_draft_is_sent(
        seeded_tenant, ff, api, following, referrals, dev_outbox, in_tenant_a):
    rosa = partner(seeded_tenant, "Rosa", ff)
    campaigns.queue(following, [rosa], actor=ff.user)
    assert not StageChange.objects.filter(contact=rosa, to_stage=following.on_sent_stage)
    assert not enrollment.is_enrolled(rosa, "referral_touches")

    outbox.approve(draft_for(rosa), actor=ff.user, role=Role.FF)
    rosa.refresh_from_db()
    change = StageChange.objects.get(contact=rosa, to_stage=following.on_sent_stage)
    assert change.reason == f"Campaign “{following.name}” was sent"
    assert change.actor == ff.user
    assert enrollment.is_enrolled(rosa, "referral_touches")
    assert rosa.referral_cadence == "quarterly"
    # On the contact's history, and on Activity.
    history = [e["text"] for e in timeline.for_contact(rosa)]
    assert any(following.name in t and following.on_sent_stage.label in t for t in history)
    assert any(t.startswith("Enrolled in referral touches (quarterly), when campaign")
               for t in history)
    feed = api.as_(ff).get("/api/activity/?category=pipeline").json()
    texts = [e["text"] for e in feed if (e["contact"] or {}).get("id") == str(rosa.pk)]
    assert any("moved Rosa Reyes to a new stage" in t for t in texts)
    assert any(t.startswith("put Rosa Reyes on referral touches, as campaign") for t in texts)


@pytest.mark.django_db
def test_someone_not_a_partner_is_moved_but_not_enrolled_and_it_says_so(
        seeded_tenant, ff, api, following, referrals, dev_outbox, in_tenant_a):
    dana = person(seeded_tenant, "Dana")
    campaigns.queue(following, [dana], actor=ff.user)
    outbox.approve(draft_for(dana), actor=ff.user, role=Role.FF)
    assert StageChange.objects.filter(contact=dana, to_stage=following.on_sent_stage)
    assert not Enrollment.objects.filter(contact=dana).exists()
    assert any("Not enrolled in referral touches" in e["text"]
               and "not a referral partner" in e["text"] for e in timeline.for_contact(dana))
    feed = api.as_(ff).get("/api/activity/?category=pipeline").json()
    assert any("did not put Dana Reyes on referral touches" in e["text"]
               and "not a referral partner" in e["text"] for e in feed)


@pytest.mark.django_db
def test_someone_already_on_touches_keeps_their_cadence(
        seeded_tenant, ff, following, referrals, dev_outbox, in_tenant_a):
    rosa = partner(seeded_tenant, "Rosa", ff)
    rosa.referral_cadence = "monthly"
    rosa.save()
    enrollment.enroll(rosa, "referral_touches", actor=ff.user)
    campaigns.queue(following, [rosa], actor=ff.user)
    outbox.approve(draft_for(rosa), actor=ff.user, role=Role.FF)
    rosa.refresh_from_db()
    assert rosa.referral_cadence == "monthly"
    assert Enrollment.objects.filter(contact=rosa).count() == 1


@pytest.mark.django_db
def test_a_draft_refused_or_deleted_does_nothing(
        seeded_tenant, ff, api, following, referrals, in_tenant_a):
    rosa, theo = partner(seeded_tenant, "Rosa", ff), partner(seeded_tenant, "Theo", ff)
    campaigns.queue(following, [rosa, theo], actor=ff.user)
    outbox.reject(draft_for(rosa), actor=ff.user)
    draft_for(theo).delete()
    for contact in (rosa, theo):
        assert not StageChange.objects.filter(contact=contact,
                                              to_stage=following.on_sent_stage)
        assert not enrollment.is_enrolled(contact, "referral_touches")


@pytest.mark.django_db
def test_an_unsubscribed_recipient_is_never_moved_or_enrolled(
        seeded_tenant, ff, following, referrals, dev_outbox, in_tenant_a):
    """Unsubscribed after the draft was queued: the draft is suppressed, its
    approval refused, and nothing follows through."""
    from apps.crm.services import unsubscribe

    rosa = partner(seeded_tenant, "Rosa", ff)
    campaigns.queue(following, [rosa], actor=ff.user)
    message = draft_for(rosa)
    unsubscribe.unsubscribe({"t": str(seeded_tenant.pk), "k": "marketing",
                             "c": str(rosa.pk), "a": ""})
    message.refresh_from_db()
    with pytest.raises(outbox.SendNotPermitted):
        outbox.approve(message, actor=ff.user, role=Role.FF)
    assert not StageChange.objects.filter(contact=rosa, to_stage=following.on_sent_stage)
    assert not enrollment.is_enrolled(rosa, "referral_touches")
    assert dev_outbox == []
    # Even called directly on a sent row, someone who left marketing is left alone.
    message.state = S.SENT
    message.save()
    CampaignRecipient.objects.filter(contact=rosa).update(ended_at=None)
    assert campaigns.after_sent(message, actor=ff.user) == {
        "moved": False, "enrolled": False, "skipped": ""}


@pytest.mark.django_db
def test_with_no_follow_through_chosen_a_send_changes_nothing(
        seeded_tenant, ff, campaign, referrals, dev_outbox, in_tenant_a):
    rosa = partner(seeded_tenant, "Rosa", ff)
    before = StageChange.objects.filter(contact=rosa).count()
    campaigns.queue(campaign, [rosa], actor=ff.user)
    outbox.approve(draft_for(rosa), actor=ff.user, role=Role.FF)
    assert StageChange.objects.filter(contact=rosa).count() == before
    assert not enrollment.is_enrolled(rosa, "referral_touches")


@pytest.mark.django_db
def test_the_choices_are_saved_and_checked(seeded_tenant, tenant_b, ff, api, campaign,
                                           in_tenant_a):
    stage = second_stage(seeded_tenant)
    saved = api.as_(ff).patch(f"/api/campaigns/{campaign.pk}/",
                              {"on_sent_stage": str(stage.pk), "on_sent_cadence": "bimonthly"},
                              content_type="application/json")
    assert saved.status_code == 200, saved.json()
    body = saved.json()
    assert body["on_sent_stage"] == str(stage.pk)
    assert body["on_sent_pipeline"] == str(stage.pipeline_id)
    assert body["on_sent_cadence"] == "bimonthly"
    from .factories import PipelineFactory, PipelineStageFactory

    theirs = PipelineStageFactory(tenant=tenant_b,
                                  pipeline=PipelineFactory(tenant=tenant_b))
    refused = api.as_(ff).patch(f"/api/campaigns/{campaign.pk}/",
                                {"on_sent_stage": str(theirs.pk)},
                                content_type="application/json")
    assert refused.status_code == 400
    assert api.as_(ff).patch(f"/api/campaigns/{campaign.pk}/", {"on_sent_cadence": "weekly"},
                             content_type="application/json").status_code == 400


# ========================================================= 3. asked to leave

@pytest.mark.parametrize("text, asks", [
    ("STOP", True), ("Unsubscribe.", True), ("unsubscribe me please", True),
    ("Please remove me from your list", True), ("opt-out", True), ("Opt out", True),
    ("Stop emailing me.", True), ("Hi Bryan,\n\nUnsubscribe\n\nThanks", True),
    ("Thanks Bryan — Friday works.", False),
    ("I can't stop thinking about your idea, let's talk next week about it.", False),
    ("Can we talk about how to remove menu items from the site, and the pricing "
     "for the second phase of the work?", False),
    ("> Unsubscribe from marketing emails: https://x/unsubscribe/abc\nSounds good", False),
])
def test_what_counts_as_asking_to_leave(text, asks):
    assert leaving.asks_to_leave(text) is asks


def gmail_reply(text, *, thread_id, msg_id, from_address="dana@x.invalid"):
    data = base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")
    return {"id": msg_id, "threadId": thread_id, "internalDate": "1790000000000",
            "payload": {"mimeType": "text/plain", "body": {"data": data, "size": len(text)},
                        "headers": [{"name": "From", "value": f"Dana <{from_address}>"},
                                    {"name": "To", "value": "info@x.test"},
                                    {"name": "Subject", "value": "Re: Hello Dana"},
                                    {"name": "Date", "value": "Mon, 19 Oct 2026 10:05:00 +0000"},
                                    {"name": "Message-ID", "value": f"<{msg_id}@x.invalid>"}]}}


@pytest.fixture
def sent_to_dana(seeded_tenant, ff, campaign, dev_outbox, in_tenant_a):
    """A campaign email sent to Dana, on a thread Gmail knows."""
    dana = person(seeded_tenant, "Dana")
    campaigns.queue(campaign, [dana], actor=ff.user)
    message = draft_for(dana)
    outbox.approve(message, actor=ff.user, role=Role.FF)
    message.refresh_from_db()
    thread = message.thread
    thread.gmail_thread_id = "g-thread-dana"
    thread.save()
    OutboxMessage.objects.filter(pk=message.pk).update(
        sent_at=message.sent_at.replace(year=2026, month=10, day=1))
    return dana


@pytest.mark.django_db
def test_a_stop_reply_to_a_marketing_email_is_marked_and_nothing_else_happens(
        seeded_tenant, ff, api, sent_to_dana, in_tenant_a):
    dana = sent_to_dana
    inbound.ingest_message(seeded_tenant, gmail_reply("STOP", thread_id="g-thread-dana",
                                                      msg_id="r1"))
    reply = EmailMessage.objects.get(direction="inbound")
    assert reply.leave_request == "asked"
    assert not EmailSuppression.objects.filter(contact=dana).exists()
    [row] = api.as_(ff).get("/api/leave-requests/").json()
    assert row["contact"]["name"] == "Dana Reyes" and row["said"].strip() == "STOP"
    assert row["answered"]["subject"] == "Hello Dana"


@pytest.mark.django_db
def test_one_click_does_exactly_what_the_link_does(
        seeded_tenant, ff, api, sent_to_dana, referrals, in_tenant_a):
    dana = sent_to_dana
    from apps.crm.services import referral

    referral.add_type(dana, "referral_partner", actor=ff.user, onboard=False)
    enrollment.enroll(dana, "referral_touches", actor=ff.user)
    inbound.ingest_message(seeded_tenant, gmail_reply("Please remove me from your list",
                                                      thread_id="g-thread-dana", msg_id="r2"))
    reply = EmailMessage.objects.get(direction="inbound")
    done = api.as_(ff).post(f"/api/leave-requests/{reply.pk}/unsubscribe/")
    assert done.status_code == 200 and done.json()["leave_request"] == "unsubscribed"
    row = EmailSuppression.objects.get(contact=dana)
    assert (row.category, row.source) == ("marketing", "reply")
    assert not enrollment.is_enrolled(dana, "referral_touches")
    assert AuditEvent.all_objects.filter(verb="email.unsubscribed").exists()
    assert api.as_(ff).get("/api/leave-requests/").json() == []
    # Pressed again: refused, nothing doubled.
    assert api.as_(ff).post(f"/api/leave-requests/{reply.pk}/unsubscribe/").status_code \
        == 404


@pytest.mark.django_db
def test_not_a_request_to_leave_changes_nothing(seeded_tenant, ff, api, sent_to_dana,
                                                in_tenant_a):
    inbound.ingest_message(seeded_tenant, gmail_reply("Stop", thread_id="g-thread-dana",
                                                      msg_id="r3"))
    reply = EmailMessage.objects.get(direction="inbound")
    assert api.as_(ff).post(f"/api/leave-requests/{reply.pk}/keep/").status_code == 200
    reply.refresh_from_db()
    assert reply.leave_request == "kept"
    assert not EmailSuppression.objects.exists()


@pytest.mark.django_db
def test_a_stop_reply_to_mail_that_is_not_marketing_is_not_marked(
        seeded_tenant, ff, in_tenant_a, dev_outbox):
    dana = person(seeded_tenant, "Dana")
    message = outbox.create_manual_draft(dana, subject="Friday", body_text="See you.",
                                         actor=ff.user)
    outbox.approve(message, actor=ff.user, role=Role.FF)
    message.refresh_from_db()
    message.thread.gmail_thread_id = "g-thread-one"
    message.thread.save()
    OutboxMessage.objects.filter(pk=message.pk).update(
        sent_at=message.sent_at.replace(year=2026, month=10, day=1))
    inbound.ingest_message(seeded_tenant, gmail_reply("stop", thread_id="g-thread-one",
                                                      msg_id="r4"))
    assert EmailMessage.objects.get(direction="inbound").leave_request == ""


@pytest.mark.django_db
def test_a_filed_reply_is_marked_too(seeded_tenant, ff, sent_to_dana, in_tenant_a):
    from apps.crm.models import UnmatchedInbound

    inbound.ingest_message(seeded_tenant, gmail_reply("Unsubscribe", thread_id="g-other",
                                                      msg_id="r5",
                                                      from_address="someone@y.invalid"))
    row = UnmatchedInbound.objects.get()
    thread = draft_for(sent_to_dana).thread
    message = inbound.file_to_contact(row, contact=sent_to_dana, actor=ff.user, thread=thread)
    message.refresh_from_db()
    assert message.leave_request == "asked"


# ================================================ 5. isolation and roles

@pytest.mark.django_db
def test_role_boundaries_an_assistant_sees_the_list_but_does_not_click(
        seeded_tenant, ff, va, api, sent_to_dana, in_tenant_a):
    inbound.ingest_message(seeded_tenant, gmail_reply("STOP", thread_id="g-thread-dana",
                                                      msg_id="r6"))
    reply = EmailMessage.objects.get(direction="inbound")
    assert len(api.as_(va).get("/api/leave-requests/").json()) == 1
    assert api.as_(va).post(f"/api/leave-requests/{reply.pk}/unsubscribe/").status_code == 403
    assert not EmailSuppression.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FCC", "ECC"])
def test_role_boundaries_a_client_reaches_none_of_it(seeded_tenant, api, role, campaign,
                                                     in_tenant_a):
    from .factories import ClientCompanyFactory

    someone = _member(seeded_tenant, role, ClientCompanyFactory(tenant=seeded_tenant))
    assert api.as_(someone).get("/api/leave-requests/").status_code in (403, 404)
    assert api.as_(someone).post(f"/api/campaigns/{campaign.pk}/attachments/",
                                 {"file": a_file()}).status_code in (403, 404)


@pytest.mark.django_db
def test_tenant_isolation_another_practice_reaches_none_of_it(
        seeded_tenant, tenant_b, ff, api, campaign, sent_to_dana, in_tenant_a):
    upload(api, ff, campaign)
    inbound.ingest_message(seeded_tenant, gmail_reply("STOP", thread_id="g-thread-dana",
                                                      msg_id="r7"))
    reply = EmailMessage.objects.get(direction="inbound")
    attachment = CampaignAttachment.objects.get()
    other = _member(tenant_b, "FF")
    theirs = api.as_(other)
    assert theirs.get("/api/leave-requests/").json() == []
    assert theirs.post(f"/api/leave-requests/{reply.pk}/unsubscribe/").status_code == 404
    assert theirs.post(f"/api/campaigns/{campaign.pk}/attachments/",
                       {"file": a_file()}).status_code == 404
    assert theirs.delete(
        f"/api/campaigns/{campaign.pk}/attachments/{attachment.pk}/").status_code == 404
    assert CampaignAttachment.objects.count() == 1
    assert not EmailSuppression.objects.exists()
