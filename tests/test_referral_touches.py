"""Referral touches could not be triggered (Check 4).

Two separate failures, found together: imported partners had no cadence and no
`next_touch_at`, so the scheduled job could never see them; and there was no way
to draft a touch on demand for anyone.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.crm.models import Contact, OutboxMessage
from apps.crm.services import importer, referral
from apps.tenancy.context import tenant_context

from . import registry_config  # noqa: F401
from .factories import ContactEmailFactory, ContactFactory

S = OutboxMessage.State
P = OutboxMessage.Producer


def _partner(tenant, **kw):
    contact = ContactFactory(tenant=tenant, **kw)
    ContactEmailFactory(tenant=tenant, contact=contact)
    return contact


# ------------------------------------------- (a) the schedule gets set at all

@pytest.mark.django_db
def test_assigning_the_type_by_hand_sets_cadence_and_next_touch(
    seeded_tenant, referrals, ff
):
    with tenant_context(seeded_tenant.pk):
        contact = _partner(seeded_tenant)
        referral.add_type(contact, "referral_partner", actor=ff.user)

        contact.refresh_from_db()
        assert contact.referral_cadence == "monthly"
        assert contact.referral_next_touch_at is not None
        assert contact.referral_onboarded_at is not None  # onboarding still fires


@pytest.mark.django_db
def test_an_imported_partner_gets_a_cadence_but_no_onboarding_email(
    seeded_tenant, referrals, ff, dev_outbox
):
    """THE Check 4 bug: the importer wrote type links directly, so 40 partners
    arrived invisible to the scheduler.

    It still must not queue a first-touch email to partners met years ago — a
    backfill is a statement about history.
    """
    header = "first_name,last_name,email,status\n"
    csv = (header + "Dana,Reyes,dana@a.invalid,Referral Partner\n").encode()
    mapping = {"first_name": "first_name", "last_name": "last_name",
               "email": "email", "status": "contact_type"}
    value_mapping = {"contact_type": {"column": "status", "values": {
        "Referral Partner": {"contact_type": "referral_partner"},
    }}}

    with tenant_context(seeded_tenant.pk):
        batch = importer.dry_run(
            tenant=seeded_tenant, filename="c.csv", file_bytes=csv,
            mapping=mapping, value_mapping=value_mapping, actor=ff.user,
        )
        importer.commit(batch, actor=ff.user)

        contact = Contact.objects.get(first_name="Dana")
        assert "referral_partner" in [t.code for t in contact.types.all()]
        # The fix: the scheduler can now see them.
        assert contact.referral_cadence == "monthly"
        assert contact.referral_next_touch_at is not None
        # And the restraint: no onboarding email, no onboarding clock.
        assert contact.referral_onboarded_at is None
        assert OutboxMessage.objects.filter(producer=P.REFERRAL_ONBOARDING).count() == 0
    assert dev_outbox == []


@pytest.mark.django_db
def test_the_scheduler_now_finds_an_imported_partner(seeded_tenant, referrals, ff):
    """The whole point: a partner with a cadence is one the job can draft for."""
    with tenant_context(seeded_tenant.pk):
        contact = _partner(seeded_tenant)
        referral.add_type(contact, "referral_partner", actor=ff.user, onboard=False)
        # Bring their next touch inside the 3-day drafting horizon.
        contact.referral_next_touch_at = timezone.now() + timezone.timedelta(days=1)
        contact.save(update_fields=["referral_next_touch_at"])

        drafted = referral.draft_due_touches(seeded_tenant)

        assert len(drafted) == 1
        assert drafted[0].state == S.PENDING_APPROVAL


@pytest.mark.django_db
def test_an_existing_cadence_is_never_overwritten(seeded_tenant, referrals, ff):
    with tenant_context(seeded_tenant.pk):
        due = timezone.now() + timezone.timedelta(days=90)
        contact = _partner(
            seeded_tenant, referral_cadence="quarterly", referral_next_touch_at=due,
        )
        referral.ensure_touch_schedule(contact)

        contact.refresh_from_db()
        assert contact.referral_cadence == "quarterly"
        assert contact.referral_next_touch_at == due


# ------------------------------------------------- (b) draft a touch on demand

@pytest.mark.django_db
def test_draft_touch_now_queues_a_pending_draft(seeded_tenant, referrals, ff, api, dev_outbox):
    with tenant_context(seeded_tenant.pk):
        contact = _partner(seeded_tenant)
        referral.add_type(contact, "referral_partner", actor=ff.user)
        OutboxMessage.objects.all().delete()  # clear the onboarding draft

    response = api.as_(ff).post(f"/api/contacts/{contact.pk}/draft-touch/")

    assert response.status_code == 201
    assert response.json()["state"] == S.PENDING_APPROVAL
    assert response.json()["producer"] == P.REFERRAL_TOUCH
    with tenant_context(seeded_tenant.pk):
        assert OutboxMessage.objects.filter(producer=P.REFERRAL_TOUCH).count() == 1
    assert dev_outbox == [], "Drafting a touch sent mail. It must only queue."


@pytest.mark.django_db
def test_drafting_now_does_not_move_the_scheduled_touch(seeded_tenant, referrals, ff, api):
    """An extra touch now is not a replacement for the one already due."""
    with tenant_context(seeded_tenant.pk):
        contact = _partner(seeded_tenant)
        referral.add_type(contact, "referral_partner", actor=ff.user)
        contact.refresh_from_db()
        due_before = contact.referral_next_touch_at

    api.as_(ff).post(f"/api/contacts/{contact.pk}/draft-touch/")

    contact.refresh_from_db()
    assert contact.referral_next_touch_at == due_before


@pytest.mark.django_db
def test_the_on_demand_draft_uses_the_same_composer(seeded_tenant, referrals, ff, api):
    """A manual trigger on a different path could produce a different email,
    which would make the scheduled one untestable."""
    seeded_tenant.referral_blurb = "Shipped a new ops playbook this month."
    seeded_tenant.save(update_fields=["referral_blurb"])
    with tenant_context(seeded_tenant.pk):
        contact = _partner(seeded_tenant, referral_fee_terms="10% of first 3 months")
        referral.add_type(contact, "referral_partner", actor=ff.user)
        # Same actor the endpoint will use, so the signature matches.
        expected, _, _ = referral.compose_touch(contact, actor=ff.user)

    body = api.as_(ff).post(f"/api/contacts/{contact.pk}/draft-touch/").json()
    assert body["body_text"] == expected


@pytest.mark.django_db
def test_a_va_may_draft_a_touch(seeded_tenant, referrals, va, ff, api):
    """Matrix 5.6 — drafting is not sending. A VA prepares; the FF approves."""
    with tenant_context(seeded_tenant.pk):
        contact = _partner(seeded_tenant)
        referral.add_type(contact, "referral_partner", actor=ff.user)

    assert api.as_(va).post(f"/api/contacts/{contact.pk}/draft-touch/").status_code == 201


@pytest.mark.django_db
def test_drafting_for_a_non_partner_is_refused(seeded_tenant, ff, api):
    contact = _partner(seeded_tenant)
    response = api.as_(ff).post(f"/api/contacts/{contact.pk}/draft-touch/")
    assert response.status_code == 400
    assert "not a referral partner" in str(response.json())


@pytest.mark.django_db
def test_drafting_for_a_partner_with_no_email_says_so(seeded_tenant, referrals, ff, api):
    contact = ContactFactory(tenant=seeded_tenant, first_name="Noemail")
    with tenant_context(seeded_tenant.pk):
        referral.add_type(contact, "referral_partner", actor=ff.user)

    response = api.as_(ff).post(f"/api/contacts/{contact.pk}/draft-touch/")
    assert response.status_code == 400
    assert "no email address" in str(response.json())


@pytest.mark.django_db
def test_a_client_user_cannot_draft_a_touch(seeded_tenant, referrals, fcc, ff, api):
    with tenant_context(seeded_tenant.pk):
        contact = _partner(seeded_tenant)
        referral.add_type(contact, "referral_partner", actor=ff.user)

    assert api.as_(fcc).post(f"/api/contacts/{contact.pk}/draft-touch/").status_code == 403
