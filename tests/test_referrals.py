"""Inbound referrals (owner, 2026-10-20).

1. A prospect someone refers enters Sales at its first stage, with the
   referrer recorded; someone already in Sales keeps their stage. Any contact
   may refer, and doing so does not make them a referral partner.
2. One referral per prospect per pipeline: the first recorded has the credit,
   and the practice may change who.
3. The outcome: written the first time the prospect is won or lost, and kept;
   a lost referral that comes back and is won becomes won.
4. Thank-you drafts at three moments (recorded, won, lost), each a practice
   setting, each waiting in the Outbox, once per referrer and moment; the lost
   one gives no reason; approved, one counts as the referrer's next touch.
5. The referrer's Referrals list, the prospect's "Referred by", the board card.
6. The CSV import's "Referred by" column, as history, undone by a rollback.
7. Merges, isolation and role boundaries.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.crm.models import Contact, ContactTypeLink, OutboxMessage, Referral
from apps.crm.services import importer, merge, outbox, pipeline
from apps.crm.services import referrals as referral_service
from apps.tenancy.context import tenant_context

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import (
    ClientAssignmentFactory, ClientCompanyFactory, ContactEmailFactory, ContactFactory,
)

S = OutboxMessage.State


def person(tenant, first, last="Reyes", *, email=True, company=None):
    contact = ContactFactory(tenant=tenant, first_name=first, last_name=last, company=company)
    if email:
        ContactEmailFactory(tenant=tenant, contact=contact, is_primary=True,
                            address=f"{first.lower()}@x.invalid")
    return contact


def thanks(tenant, **filters):
    return OutboxMessage.all_objects.filter(
        tenant=tenant, producer=OutboxMessage.Producer.REFERRAL_THANKS, **filters)


def move(contact, stages, code, actor, reason=""):
    return pipeline.change_stage(contact, stages[code], actor=actor, reason=reason)


def code_of(semantic, stages):
    return next(code for code, s in stages.items() if s.semantic == semantic)


@pytest.fixture
def mark(seeded_tenant):
    return person(seeded_tenant, "Mark", "Ellis")


# ------------------------------------------------------------- recording

@pytest.mark.django_db
def test_a_referred_prospect_enters_sales_at_the_first_stage(
        seeded_tenant, ff, api, mark, stages, dev_outbox):
    response = api.as_(ff).post("/api/contacts/", {
        "first_name": "Dana", "last_name": "Cole",
        "emails": [{"address": "dana@x.invalid", "is_primary": True}],
        "referrer": str(mark.pk),
    }, content_type="application/json")
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["referred_by"]["referrer"] == str(mark.pk)
    assert body["referred_by"]["referrer_name"] == "Mark Ellis"
    [position] = body["pipeline_positions"]
    assert position["pipeline_kind"] == "sales"
    with tenant_context(seeded_tenant.pk):
        entry = pipeline.entry_stage(pipeline.sales_pipeline(seeded_tenant))
    assert position["stage_code"] == entry.code

    referral = Referral.all_objects.get()
    assert (referral.referrer_id, referral.direction, referral.outcome) == (
        mark.pk, "inbound", "")
    # A thank-you waits for approval; nothing left.
    [message] = thanks(seeded_tenant)
    assert (message.state, message.to_contact_id, message.subject) == (
        S.PENDING_APPROVAL, mark.pk, "Thank you for the introduction")
    assert "Dana Cole" in message.body_text
    assert dev_outbox == []
    # Referring someone does not make Mark a referral partner, and queues no
    # onboarding.
    assert not ContactTypeLink.all_objects.filter(
        contact=mark, contact_type__code="referral_partner").exists()
    assert not OutboxMessage.all_objects.filter(producer="referral_onboarding").exists()


@pytest.mark.django_db
def test_someone_already_in_sales_keeps_their_stage(seeded_tenant, ff, mark, stages):
    dana = person(seeded_tenant, "Dana")
    qualified = code_of("qualified", stages)
    with tenant_context(seeded_tenant.pk):
        move(dana, stages, qualified, ff.user)
        referral_service.record(dana, mark, actor=ff.user)
    sales = pipeline.sales_pipeline(seeded_tenant)
    assert pipeline.position_for(dana, sales).stage.code == qualified
    assert Referral.all_objects.get().prospect_id == dana.pk


@pytest.mark.django_db
def test_the_first_recorded_has_the_credit_and_the_practice_may_change_it(
        seeded_tenant, ff, api, mark):
    dana = person(seeded_tenant, "Dana")
    lucia = person(seeded_tenant, "Lucia", "Park")
    lucia.referral_fee_terms = "10% of the first three months"
    lucia.save()
    client = api.as_(ff)
    first = client.post("/api/referrals/", {"prospect": str(dana.pk), "referrer": str(mark.pk)},
                        content_type="application/json")
    assert first.status_code == 201
    # Recording a second referrer for the same prospect moves the credit; it
    # never makes a second row.
    again = client.post("/api/referrals/", {"prospect": str(dana.pk),
                                            "referrer": str(lucia.pk)},
                        content_type="application/json")
    assert again.status_code == 201
    assert Referral.all_objects.count() == 1
    row = Referral.all_objects.get()
    assert (row.referrer_id, row.fee_terms) == (lucia.pk, "10% of the first three months")
    # Each referrer is thanked once for it.
    assert sorted(m.to_contact_id for m in thanks(seeded_tenant)) == sorted([mark.pk, lucia.pk])

    back = client.patch(f"/api/referrals/{row.pk}/", {"referrer": str(mark.pk),
                                                      "note": "Met at BNI"},
                        content_type="application/json")
    assert back.status_code == 200, back.json()
    assert (back.json()["referrer"]["id"], back.json()["note"]) == (str(mark.pk), "Met at BNI")
    assert thanks(seeded_tenant).count() == 2  # Mark was thanked already
    assert client.patch(f"/api/referrals/{row.pk}/", {"referrer": str(dana.pk)},
                        content_type="application/json").status_code == 400


@pytest.mark.django_db
def test_removing_a_referral_withdraws_its_unsent_thanks_and_keeps_the_stage(
        seeded_tenant, ff, api, mark):
    dana = person(seeded_tenant, "Dana")
    with tenant_context(seeded_tenant.pk):
        row = referral_service.record(dana, mark, actor=ff.user)
    assert api.as_(ff).delete(f"/api/referrals/{row.pk}/").status_code == 204
    assert Referral.all_objects.count() == 0
    assert [m.state for m in thanks(seeded_tenant)] == [S.REJECTED]
    assert pipeline.position_for(dana, pipeline.sales_pipeline(seeded_tenant)) is not None


# --------------------------------------------------------------- outcome

@pytest.mark.django_db
def test_won_is_recorded_once_and_thanked(seeded_tenant, ff, mark, stages):
    dana = person(seeded_tenant, "Dana", "Cole")
    won, lost = code_of("won", stages), code_of("lost", stages)
    with tenant_context(seeded_tenant.pk):
        row = referral_service.record(dana, mark, actor=ff.user)
        move(dana, stages, won, ff.user)
        row.refresh_from_db()
        assert row.outcome == "won" and row.outcome_at is not None
        at = row.outcome_at
        move(dana, stages, lost, ff.user)
        move(dana, stages, won, ff.user)
    row.refresh_from_db()
    assert (row.outcome, row.outcome_at) == ("won", at)
    assert [m.subject for m in thanks(seeded_tenant).order_by("created_at")] == [
        "Thank you for the introduction", "Good news, and thank you"]
    assert "Dana Cole has decided to work with us" in thanks(
        seeded_tenant, source_type="referral_won").get().body_text


@pytest.mark.django_db
def test_lost_gives_no_reason_and_a_later_win_still_counts(seeded_tenant, ff, mark, stages):
    dana = person(seeded_tenant, "Dana", "Cole")
    with tenant_context(seeded_tenant.pk):
        row = referral_service.record(dana, mark, actor=ff.user)
        move(dana, stages, code_of("lost", stages), ff.user,
             reason="Budget went to a full-time hire")
        row.refresh_from_db()
        assert row.outcome == "lost"
        lost_note = thanks(seeded_tenant, source_type="referral_lost").get()
        assert "Budget" not in lost_note.body_text
        assert "full-time" not in lost_note.body_text
        assert "didn't turn into an engagement this time" in lost_note.body_text
        move(dana, stages, code_of("won", stages), ff.user)
    row.refresh_from_db()
    assert row.outcome == "won"
    assert thanks(seeded_tenant, source_type="referral_won").count() == 1


@pytest.mark.django_db
def test_recorded_after_the_fact_takes_the_outcome_without_a_thanks_for_it(
        seeded_tenant, ff, mark, stages):
    from apps.crm.models import StageChange

    dana = person(seeded_tenant, "Dana")
    with tenant_context(seeded_tenant.pk):
        move(dana, stages, code_of("won", stages), ff.user)
        won_at = timezone.now() - timezone.timedelta(days=40)
        StageChange.all_objects.filter(contact=dana).update(created_at=won_at)
        row = referral_service.record(dana, mark, actor=ff.user)
    # The day they were won, not the day the referral was written down.
    assert (row.outcome, row.outcome_at) == ("won", won_at)
    assert [m.source_type for m in thanks(seeded_tenant)] == ["referral_recorded"]


@pytest.mark.django_db
def test_a_move_in_another_pipeline_is_not_an_outcome(
        seeded_tenant, ff, mark, referral_stages):
    dana = person(seeded_tenant, "Dana")
    with tenant_context(seeded_tenant.pk):
        row = referral_service.record(dana, mark, actor=ff.user)
        # "Active Referrer" is the referral pipeline's own end, not a sale.
        active = next(s for s in referral_stages.values() if s.semantic == "qualified")
        pipeline.change_stage(dana, active, actor=ff.user)
        dormant = next(s for s in referral_stages.values() if s.semantic == "parked")
        pipeline.change_stage(dana, dormant, actor=ff.user)
    row.refresh_from_db()
    assert row.outcome == ""


# ---------------------------------------------------------------- thanks

@pytest.mark.django_db
def test_each_moment_is_a_setting_the_practice_owner_turns_off(
        seeded_tenant, ff, va, api, mark, stages):
    assert api.as_(va).post("/api/referral-settings/thanks/", {"won": False},
                            content_type="application/json").status_code == 403
    response = api.as_(ff).post("/api/referral-settings/thanks/",
                                {"recorded": False, "lost": False},
                                content_type="application/json")
    assert response.status_code == 200
    assert response.json()["thanks"] == {"recorded": False, "won": True, "lost": False}
    assert api.as_(ff).post("/api/referral-settings/thanks/", {"won": "no"},
                            content_type="application/json").status_code == 400

    seeded_tenant.refresh_from_db()
    dana, eli = person(seeded_tenant, "Dana"), person(seeded_tenant, "Eli")
    with tenant_context(seeded_tenant.pk):
        referral_service.record(dana, mark, actor=ff.user)
        referral_service.record(eli, mark, actor=ff.user)
        move(dana, stages, code_of("won", stages), ff.user)
        move(eli, stages, code_of("lost", stages), ff.user)
    assert [m.source_type for m in thanks(seeded_tenant)] == ["referral_won"]


@pytest.mark.django_db
def test_an_approved_thanks_is_the_partners_next_touch(seeded_tenant, ff, mark, dev_outbox):
    mark.referral_cadence = "monthly"
    mark.referral_next_touch_at = timezone.now() + timezone.timedelta(days=3)
    mark.save()
    dana = person(seeded_tenant, "Dana")
    with tenant_context(seeded_tenant.pk):
        referral_service.record(dana, mark, actor=ff.user)
        message = thanks(seeded_tenant).get()
        assert dev_outbox == []
        outbox.approve(message, actor=ff.user, role="FF")
    message.refresh_from_db()
    mark.refresh_from_db()
    assert message.state == S.SENT and len(dev_outbox) == 1
    expected = message.sent_at + timezone.timedelta(days=30)
    assert abs((mark.referral_next_touch_at - expected).total_seconds()) < 5


@pytest.mark.django_db
def test_a_thanks_to_someone_off_the_touch_schedule_sets_no_schedule(
        seeded_tenant, ff, mark, dev_outbox):
    dana = person(seeded_tenant, "Dana")
    with tenant_context(seeded_tenant.pk):
        referral_service.record(dana, mark, actor=ff.user)
        outbox.approve(thanks(seeded_tenant).get(), actor=ff.user, role="FF")
    mark.refresh_from_db()
    assert mark.referral_next_touch_at is None


@pytest.mark.django_db
def test_a_thanks_is_correspondence_from_the_person(seeded_tenant, ff, mark):
    from apps.crm.services import email_layout, unsubscribe

    dana = person(seeded_tenant, "Dana")
    with tenant_context(seeded_tenant.pk):
        referral_service.record(dana, mark, actor=ff.user)
    message = thanks(seeded_tenant).get()
    assert message.category == unsubscribe.CORRESPONDENCE
    assert "referral_thanks" in email_layout.PERSONAL_PRODUCERS
    no_email = person(seeded_tenant, "Nora", email=False)
    eli = person(seeded_tenant, "Eli")
    with tenant_context(seeded_tenant.pk):
        referral_service.record(eli, no_email, actor=ff.user)
    assert "has no email address" in thanks(seeded_tenant, to_contact=no_email).get().warning


# --------------------------------------------------------------- reading

@pytest.mark.django_db
def test_the_referrers_list_shows_each_prospects_stage_and_outcome(
        seeded_tenant, ff, va, api, mark, stages):
    dana, eli = person(seeded_tenant, "Dana", "Cole"), person(seeded_tenant, "Eli", "Park")
    with tenant_context(seeded_tenant.pk):
        referral_service.record(dana, mark, actor=ff.user)
        referral_service.record(eli, mark, actor=ff.user)
        move(eli, stages, code_of("won", stages), ff.user)
    for member in (ff, va):
        rows = api.as_(member).get(f"/api/referrals/?referrer={mark.pk}").json()
        assert sorted((r["prospect"]["name"], r["stage"]["semantic"], r["outcome"])
                      for r in rows) == [("Dana Cole", "entry", ""), ("Eli Park", "won", "won")]
    assert api.as_(ff).get("/api/referrals/?referrer=nonsense").json() == []
    assert api.as_(ff).get(f"/api/referrals/?prospect={dana.pk}").json()[0][
        "referrer"]["name"] == "Mark Ellis"
    detail = api.as_(ff).get(f"/api/contacts/{dana.pk}/").json()
    assert detail["referred_by"]["referrer_name"] == "Mark Ellis"
    # The board card says who referred them.
    sales = pipeline.sales_pipeline(seeded_tenant)
    board = api.as_(ff).get(f"/api/pipelines/{sales.pk}/board/").json()
    cards = [c for col in board["columns"] for c in col["contacts"]]
    assert {c["first_name"]: (c["referred_by"] or {}).get("referrer_name")
            for c in cards} == {"Dana": "Mark Ellis", "Eli": "Mark Ellis"}


# ---------------------------------------------------------------- import

def _csv(lines):
    return ("first_name,last_name,email,referred_by\n" + "".join(lines)).encode()


MAPPING = {"first_name": "first_name", "last_name": "last_name", "email": "email",
           "referred_by": "referred_by"}


@pytest.mark.django_db
def test_the_import_records_who_referred_each_row_as_history(seeded_tenant, ff, mark):
    person(seeded_tenant, "Sam", "Twin")
    ContactFactory(tenant=seeded_tenant, first_name="Sam", last_name="Twin")
    with tenant_context(seeded_tenant.pk):
        batch = importer.dry_run(
            tenant=seeded_tenant, filename="book.csv", mapping=MAPPING, actor=ff.user,
            file_bytes=_csv(["Dana,Cole,dana@x.invalid,mark@x.invalid\n",
                             "Eli,Park,eli@x.invalid,mark ellis\n",
                             "Fay,Lin,fay@x.invalid,Sam Twin\n",
                             "Gus,Ray,gus@x.invalid,Nobody Known\n"]))
        previews = {r.preview["first_name"]: r.preview for r in batch.rows.all()}
        assert previews["Dana"]["referrer_name"] == "Mark Ellis"
        assert previews["Eli"]["referrer_name"] == "Mark Ellis"
        assert "more than one contact is called Sam Twin" in previews["Fay"]["referrer_problem"]
        assert "no contact is called Nobody Known" in previews["Gus"]["referrer_problem"]
        assert batch.counts["error"] == 0
        importer.commit(batch, actor=ff.user)

        rows = Referral.objects.select_related("prospect").order_by("prospect__first_name")
        assert [(r.prospect.first_name, r.referrer_id) for r in rows] == [
            ("Dana", mark.pk), ("Eli", mark.pk)]
        # History: no thank-you.
        assert thanks(seeded_tenant).count() == 0
        sales = pipeline.sales_pipeline(seeded_tenant)
        dana = Contact.objects.get(first_name="Dana")
        assert pipeline.position_for(dana, sales) is not None

        batch.refresh_from_db()
        importer.rollback(batch, actor=ff.user)
        assert Referral.objects.count() == 0


@pytest.mark.django_db
def test_an_import_update_keeps_an_earlier_credit_and_rolls_back_its_own(
        seeded_tenant, ff, mark, stages):
    lucia = person(seeded_tenant, "Lucia", "Park")
    dana = person(seeded_tenant, "Dana", "Cole")
    eli = person(seeded_tenant, "Eli", "Ross")
    with tenant_context(seeded_tenant.pk):
        referral_service.record(dana, lucia, actor=ff.user)
        batch = importer.dry_run(
            tenant=seeded_tenant, filename="book.csv", mapping=MAPPING, actor=ff.user,
            file_bytes=_csv(["Dana,Cole,dana@x.invalid,mark@x.invalid\n",
                             "Eli,Ross,eli@x.invalid,mark@x.invalid\n"]))
        importer.commit(batch, actor=ff.user)
        assert Referral.objects.get(prospect=dana).referrer_id == lucia.pk
        assert Referral.objects.get(prospect=eli).referrer_id == mark.pk
        sales = pipeline.sales_pipeline(seeded_tenant)
        assert pipeline.position_for(eli, sales) is not None
        batch.refresh_from_db()
        importer.rollback(batch, actor=ff.user)
        assert list(Referral.objects.values_list("prospect_id", flat=True)) == [dana.pk]
        assert pipeline.position_for(eli, sales) is None


# ----------------------------------------------------------------- merge

@pytest.mark.django_db
def test_a_merge_carries_referrals_both_ways(seeded_tenant, ff, mark):
    mark_again = person(seeded_tenant, "Mark2", "Ellis", email=False)
    dana, dana_again = person(seeded_tenant, "Dana"), person(seeded_tenant, "Dana2", email=False)
    eli = person(seeded_tenant, "Eli")
    lucia = person(seeded_tenant, "Lucia")
    with tenant_context(seeded_tenant.pk):
        referral_service.record(eli, mark_again, actor=ff.user)
        referral_service.record(dana, lucia, actor=ff.user)
        referral_service.record(dana_again, mark, actor=ff.user)
        merge.merge_contacts(mark, mark_again, actor=ff.user)
        merge.merge_contacts(dana, dana_again, actor=ff.user)
        assert Referral.objects.get(prospect=eli).referrer_id == mark.pk
        # Dana's own referral (Lucia's) stands; the absorbed one stays behind.
        assert Referral.objects.get(prospect=dana).referrer_id == lucia.pk
        # Merging someone into the person they referred records nothing.
        merge.merge_contacts(eli, mark, actor=ff.user)
        assert not Referral.objects.filter(prospect=eli, referrer=eli).exists()


# ------------------------------------------------- isolation and roles

@pytest.mark.django_db
def test_an_associate_sees_only_referrals_inside_their_contacts(
        seeded_tenant, ff, cf, api, mark):
    acme = ClientCompanyFactory(tenant=seeded_tenant, name="Acme")
    ClientAssignmentFactory(tenant=seeded_tenant, user=cf.user, company=acme)
    dana = person(seeded_tenant, "Dana", company=acme)
    eli = person(seeded_tenant, "Eli", company=acme)
    theirs = person(seeded_tenant, "Theo", company=acme)
    with tenant_context(seeded_tenant.pk):
        referral_service.record(dana, mark, actor=ff.user)   # Mark is not theirs
        referral_service.record(eli, theirs, actor=ff.user)
    client = api.as_(cf)
    rows = client.get("/api/referrals/").json()
    assert [r["prospect"]["name"] for r in rows] == ["Eli Reyes"]
    assert client.get(f"/api/contacts/{dana.pk}/").json()["referred_by"] is None
    assert client.get(f"/api/contacts/{eli.pk}/").json()["referred_by"][
        "referrer_name"] == "Theo Reyes"
    # Nor may they record someone outside their contacts as the referrer.
    refused = client.post("/api/referrals/", {"prospect": str(theirs.pk),
                                              "referrer": str(mark.pk)},
                          content_type="application/json")
    assert refused.status_code == 400
    assert client.post("/api/contacts/", {"first_name": "New", "referrer": str(mark.pk)},
                       content_type="application/json").status_code == 400
    assert not Contact.all_objects.filter(first_name="New").exists()


@pytest.mark.django_db
def test_clients_never_reach_referrals(seeded_tenant, ff, fcc, api, mark):
    dana = person(seeded_tenant, "Dana")
    with tenant_context(seeded_tenant.pk):
        row = referral_service.record(dana, mark, actor=ff.user)
    ecc = _member(seeded_tenant, "ECC", company=fcc.client_company)
    for member in (fcc, ecc):
        client = api.as_(member)
        assert client.get("/api/referrals/").status_code == 403
        assert client.post("/api/referrals/", {"prospect": str(dana.pk),
                                               "referrer": str(mark.pk)},
                           content_type="application/json").status_code == 403
        assert client.delete(f"/api/referrals/{row.pk}/").status_code == 403
        assert client.get("/api/referral-settings/").status_code == 403


@pytest.mark.django_db
def test_another_practices_referrals_are_invisible(seeded_tenant, tenant_b, ff, api, mark):
    from .factories import ReferralFactory

    other = ReferralFactory(tenant=tenant_b)
    client = api.as_(ff)
    assert client.get("/api/referrals/").json() == []
    assert client.delete(f"/api/referrals/{other.pk}/").status_code == 404
    refused = client.post("/api/referrals/", {"prospect": str(other.prospect_id),
                                              "referrer": str(mark.pk)},
                          content_type="application/json")
    assert refused.status_code == 400
    assert Referral.all_objects.filter(tenant=tenant_b).count() == 1


@pytest.mark.django_db
def test_no_sales_pipeline_is_said_not_guessed(seeded_tenant, ff, api, mark):
    from apps.crm.models import Pipeline

    dana = person(seeded_tenant, "Dana")
    Pipeline.all_objects.filter(tenant=seeded_tenant, kind="sales").update(kind="custom")
    response = api.as_(ff).post("/api/referrals/", {"prospect": str(dana.pk),
                                                    "referrer": str(mark.pk)},
                                content_type="application/json")
    assert response.status_code == 400
    assert "no sales pipeline" in str(response.json()["referrer"])
