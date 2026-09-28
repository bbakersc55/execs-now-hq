"""Enrolment is explicit (owner, 2026-09-28).

No contact is put on a recurring email as a side effect. Referral touches are
drafted only for partners the FF or a CF enrolled; existing partners start
unenrolled. Digest stakeholders stay as they are, and the contact page shows
every enrolment in one list with the way off.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.crm.models import Enrollment, OutboxMessage
from apps.crm.services import enrollment, referral
from apps.tenancy.context import tenant_context
from apps.tenancy.models import AuditEvent

from . import registry_config  # noqa: F401
from .factories import ContactEmailFactory, ContactFactory, GoalFactory, StakeholderFactory

S = OutboxMessage.State
P = OutboxMessage.Producer


def _partner(tenant, ff, **kw):
    contact = ContactFactory(tenant=tenant, **kw)
    ContactEmailFactory(tenant=tenant, contact=contact)
    referral.add_type(contact, "referral_partner", actor=ff.user, onboard=False)
    return contact


@pytest.mark.django_db
def test_becoming_a_partner_enrols_nobody_and_the_job_drafts_nothing(
    seeded_tenant, referrals, ff, in_tenant_a
):
    contact = _partner(seeded_tenant, ff, referral_cadence="monthly",
                       referral_next_touch_at=timezone.now())
    assert not Enrollment.objects.exists()
    assert referral.draft_due_touches(seeded_tenant) == []


@pytest.mark.django_db
def test_enrolling_starts_touches_no_sooner_than_the_drafting_lead(
    seeded_tenant, referrals, ff, api, in_tenant_a
):
    # A date that went by while they were not enrolled is not "due".
    contact = _partner(seeded_tenant, ff,
                       referral_next_touch_at=timezone.now() - timezone.timedelta(days=40))

    response = api.as_(ff).post(f"/api/contacts/{contact.pk}/enroll/",
                                {"program": "referral_touches"})

    assert response.status_code == 201
    contact.refresh_from_db()
    assert contact.referral_cadence == "monthly"
    lead = timezone.timedelta(days=referral.DRAFT_LEAD_DAYS)
    assert contact.referral_next_touch_at >= timezone.now() + lead - timezone.timedelta(minutes=1)
    assert response.json()["contact"]["referral_enrolled"] is True
    assert AuditEvent.all_objects.filter(verb="enrollment.started").exists()
    # And the next run of the job drafts it.
    assert len(referral.draft_due_touches(seeded_tenant)) == 1


@pytest.mark.django_db
def test_enrolling_keeps_a_date_already_in_the_future(seeded_tenant, referrals, ff,
                                                     in_tenant_a):
    due = timezone.now() + timezone.timedelta(days=13)
    contact = _partner(seeded_tenant, ff, referral_cadence="quarterly",
                       referral_next_touch_at=due)
    enrollment.enroll(contact, "referral_touches", actor=ff.user)
    contact.refresh_from_db()
    assert (contact.referral_cadence, contact.referral_next_touch_at) == ("quarterly", due)


@pytest.mark.django_db
def test_enrolling_twice_is_one_enrolment(seeded_tenant, referrals, ff, in_tenant_a):
    contact = _partner(seeded_tenant, ff)
    assert enrollment.enroll(contact, "referral_touches", actor=ff.user)[1] is True
    assert enrollment.enroll(contact, "referral_touches", actor=ff.user)[1] is False
    assert Enrollment.objects.filter(contact=contact).count() == 1


@pytest.mark.django_db
def test_only_a_partner_can_be_enrolled_in_touches(seeded_tenant, referrals, ff, api):
    contact = ContactFactory(tenant=seeded_tenant)
    response = api.as_(ff).post(f"/api/contacts/{contact.pk}/enroll/",
                                {"program": "referral_touches"})
    assert response.status_code == 400
    assert "not a referral partner" in response.json()["detail"]


@pytest.mark.django_db
def test_unenrolling_withdraws_unapproved_touches_and_stops_the_job(
    seeded_tenant, referrals, ff, api, in_tenant_a
):
    contact = _partner(seeded_tenant, ff)
    enrollment.enroll(contact, "referral_touches", actor=ff.user)
    pending = referral.draft_touch_now(contact, actor=ff.user)
    sent = referral.draft_touch_now(contact, actor=ff.user)
    OutboxMessage.objects.filter(pk=sent.pk).update(state=S.SENT)

    response = api.as_(ff).post(f"/api/contacts/{contact.pk}/unenroll/",
                                {"program": "referral_touches"})

    assert response.status_code == 200
    pending.refresh_from_db(); sent.refresh_from_db()
    assert pending.state == S.REJECTED and "Withdrawn" in pending.warning
    assert sent.state == S.SENT                                # history is history
    row = Enrollment.objects.get(contact=contact)
    assert (row.ended_reason, row.ended_by_id) == ("unenrolled", ff.user.pk)
    contact.referral_next_touch_at = timezone.now()
    contact.save(update_fields=["referral_next_touch_at"])
    assert referral.draft_due_touches(seeded_tenant) == []
    # Coming back is a new period, so the old one stays on record.
    enrollment.enroll(contact, "referral_touches", actor=ff.user)
    assert Enrollment.objects.filter(contact=contact).count() == 2


@pytest.mark.django_db
def test_drafting_a_touch_for_an_unenrolled_partner_is_refused(seeded_tenant, referrals,
                                                               ff, api):
    contact = _partner(seeded_tenant, ff)
    response = api.as_(ff).post(f"/api/contacts/{contact.pk}/draft-touch/")
    assert response.status_code == 400
    assert "not enrolled" in response.json()["detail"]


@pytest.mark.django_db
def test_bulk_enrol_from_the_partner_table(seeded_tenant, referrals, ff, api, in_tenant_a):
    partners = [_partner(seeded_tenant, ff) for _ in range(3)]
    stranger = ContactFactory(tenant=seeded_tenant, first_name="Not", last_name="Partner")
    client = api.as_(ff)

    body = client.post("/api/contacts/enroll-selected/", {
        "ids": [str(c.pk) for c in partners] + [str(stranger.pk)],
        "program": "referral_touches"}, content_type="application/json").json()

    assert body["changed_count"] == 3
    assert body["skipped"][0]["name"] == "Not Partner"
    listed = {row["id"]: row["referral_enrolled"] for row in client.get("/api/contacts/").json()}
    assert all(listed[str(c.pk)] for c in partners) and listed[str(stranger.pk)] is False

    off = client.post("/api/contacts/enroll-selected/", {
        "ids": [str(partners[0].pk)], "unenroll": True}, content_type="application/json").json()
    assert off["changed_count"] == 1
    assert not enrollment.is_enrolled(partners[0], "referral_touches")


@pytest.mark.django_db
def test_the_enrolled_in_list_has_touches_and_digests_each_with_a_way_off(
    seeded_tenant, referrals, ff, api, in_tenant_a
):
    contact = _partner(seeded_tenant, ff)
    enrollment.enroll(contact, "referral_touches", actor=ff.user)
    goal = GoalFactory(tenant=seeded_tenant, title="Cut DSO")
    stake = StakeholderFactory(tenant=seeded_tenant, contact=contact, goal=goal, task=None)
    client = api.as_(ff)

    rows = client.get(f"/api/contacts/{contact.pk}/enrollments/").json()
    assert {r["kind"] for r in rows} == {"referral_touches", "digest"}
    digest = next(r for r in rows if r["kind"] == "digest")
    assert "Cut DSO" in digest["label"]

    after = client.post(f"/api/contacts/{contact.pk}/unenroll/",
                        {"stakeholder": digest["id"]}).json()["enrollments"]
    assert [r["kind"] for r in after] == ["referral_touches"]
    stake.refresh_from_db()
    assert stake.is_muted is True                         # muted, not deleted


@pytest.mark.django_db
def test_a_va_cannot_enrol_anyone(seeded_tenant, referrals, ff, va, api, in_tenant_a):
    contact = _partner(seeded_tenant, ff)
    client = api.as_(va)
    assert client.post(f"/api/contacts/{contact.pk}/enroll/").status_code == 403
    assert client.post("/api/contacts/enroll-selected/",
                       {"ids": [str(contact.pk)]}, content_type="application/json").status_code == 403
    assert not Enrollment.objects.exists()
