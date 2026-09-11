"""Findings from manual checks 2-5.

Bug 1 turned out not to be a bug — only a `create_task` rule existed — so the
test here is a regression guard: drag a contact through the board endpoint with
BOTH rules configured and assert both fire.
"""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.crm.models import (
    ContactEmail, ContactPhone, MailPreference, OutboxAttachment, OutboxMessage, Task,
)
from apps.crm.services import merge, referral, sender
from apps.tenancy.context import tenant_context

from . import registry_config  # noqa: F401
from .factories import (
    CompanyFactory, ContactEmailFactory, ContactFactory, ContactPhoneFactory,
    EmailTemplateFactory, GmailConnectionFactory, StageAutomationFactory,
    StoredFileFactory,
)

S = OutboxMessage.State
P = OutboxMessage.Producer


def _contact(tenant, **kw):
    contact = ContactFactory(tenant=tenant, **kw)
    ContactEmailFactory(tenant=tenant, contact=contact)
    return contact


# ============================================ bug 1 — both rules on one stage

@pytest.mark.django_db
def test_a_board_move_fires_both_the_task_and_the_email_rule(
    seeded_tenant, sales, stages, ff, api, dev_outbox
):
    """The Check 3 report: only the task fired. The cause was that only a task
    rule existed — but nothing guarded the two-rule case, so here it is."""
    StageAutomationFactory(
        tenant=seeded_tenant, pipeline=sales, to_stage=stages["qualified"],
        action_type="create_task", task_title_template="Book strategy session",
        task_due_offset_days=3,
    )
    StageAutomationFactory(
        tenant=seeded_tenant, pipeline=sales, to_stage=stages["qualified"],
        action_type="draft_email",
        email_template=EmailTemplateFactory(tenant=seeded_tenant, kind="stage"),
    )
    contact = _contact(seeded_tenant, owner=ff.user)

    # Exactly what a drag does: the board's own change-stage call.
    response = api.as_(ff).post(
        f"/api/contacts/{contact.pk}/change-stage/",
        {"stage": str(stages["qualified"].pk)}, content_type="application/json",
    )
    assert response.status_code == 200

    with tenant_context(seeded_tenant.pk):
        assert Task.objects.filter(
            contact=contact, title="Book strategy session"
        ).count() == 1
        drafts = OutboxMessage.objects.filter(producer=P.STAGE_RULE)
        assert drafts.count() == 1
        assert drafts.first().state == S.PENDING_APPROVAL
    assert dev_outbox == [], "A stage rule sent an email. It must only queue."


@pytest.mark.django_db
def test_a_task_only_rule_fires_only_the_task(
    seeded_tenant, sales, stages, ff, api, dev_outbox
):
    """The state the owner's database was actually in — correct behaviour."""
    StageAutomationFactory(
        tenant=seeded_tenant, pipeline=sales, to_stage=stages["qualified"],
        action_type="create_task",
    )
    contact = _contact(seeded_tenant, owner=ff.user)
    api.as_(ff).post(
        f"/api/contacts/{contact.pk}/change-stage/",
        {"stage": str(stages["qualified"].pk)}, content_type="application/json",
    )
    with tenant_context(seeded_tenant.pk):
        assert Task.objects.filter(contact=contact).count() == 1
        assert OutboxMessage.objects.filter(producer=P.STAGE_RULE).count() == 0


# ======================================== bug 2 — the flyer IS on the message

@pytest.mark.django_db
def test_the_onboarding_draft_carries_the_flyer(seeded_tenant, referrals, ff, api):
    """The row existed all along; the Outbox just never rendered it."""
    flyer = StoredFileFactory(
        tenant=seeded_tenant, purpose="marketing_flyer",
        content_type="application/pdf", content=b"%PDF-1.4" + b"x" * 404702,
    )
    seeded_tenant.marketing_flyer = flyer
    seeded_tenant.save(update_fields=["marketing_flyer"])

    with tenant_context(seeded_tenant.pk):
        contact = _contact(seeded_tenant)
        referral.add_type(contact, "referral_partner", actor=ff.user)
        message = OutboxMessage.objects.get(producer=P.REFERRAL_ONBOARDING)
        assert message.attachments.count() == 1
        assert message.warning == ""

    row = next(
        m for m in api.as_(ff).get("/api/outbox/").json()
        if m["producer"] == P.REFERRAL_ONBOARDING
    )
    # The fix: the API now SAYS so, with a filename and a size.
    assert row["attachments"] == [{
        "id": row["attachments"][0]["id"], "filename": "Executives-Now.pdf",
        "byte_size": flyer.byte_size, "content_type": "application/pdf",
        "content_present": True,
    }]
    assert flyer.byte_size == 404710


@pytest.mark.django_db
def test_with_no_flyer_the_draft_omits_the_attached_sentence(
    seeded_tenant, referrals, ff
):
    """FR-1.23b — the draft is created either way, and must not claim an
    attachment it does not have."""
    assert seeded_tenant.marketing_flyer_id is None

    with tenant_context(seeded_tenant.pk):
        contact = _contact(seeded_tenant)
        referral.add_type(contact, "referral_partner", actor=ff.user)
        message = OutboxMessage.objects.get(producer=P.REFERRAL_ONBOARDING)

        assert message.attachments.count() == 0
        assert "No marketing flyer is uploaded" in message.warning
        assert "attached" not in message.body_text.lower()


# ================================================ bug 3 — merge deduplicates

@pytest.mark.django_db
def test_merge_deduplicates_phones_and_emails(seeded_tenant, ff):
    """Check 2: the survivor came out holding the same mobile number twice."""
    company = CompanyFactory(tenant=seeded_tenant)
    survivor = ContactFactory(tenant=seeded_tenant, first_name="Dana", company=company)
    absorbed = ContactFactory(tenant=seeded_tenant, first_name="Dana", company=company)

    ContactEmailFactory(tenant=seeded_tenant, contact=survivor,
                        address="dana@acme.invalid", is_primary=True)
    ContactEmailFactory(tenant=seeded_tenant, contact=absorbed,
                        address="DANA@acme.invalid", is_primary=True)
    ContactEmailFactory(tenant=seeded_tenant, contact=absorbed,
                        address="d.reyes@home.invalid", is_primary=False)
    ContactPhoneFactory(tenant=seeded_tenant, contact=survivor,
                        number="+1 555-0100", is_primary=True)
    ContactPhoneFactory(tenant=seeded_tenant, contact=absorbed,
                        number="15550100", is_primary=True)

    with tenant_context(seeded_tenant.pk):
        merge.merge_contacts(survivor, absorbed, actor=ff.user, role="FF")

        emails = ContactEmail.objects.filter(contact=survivor)
        assert emails.count() == 2, "the same address arrived twice"
        assert sum(1 for e in emails if e.is_primary) == 1
        assert {e.address for e in emails} == {
            "dana@acme.invalid", "d.reyes@home.invalid",
        }

        phones = ContactPhone.objects.filter(contact=survivor)
        # Same number, different formatting — one number.
        assert phones.count() == 1
        assert phones.first().is_primary is True


@pytest.mark.django_db
def test_merge_keeps_a_genuinely_different_number(seeded_tenant, ff):
    survivor = ContactFactory(tenant=seeded_tenant, first_name="Dana")
    absorbed = ContactFactory(tenant=seeded_tenant, first_name="Dana")
    ContactPhoneFactory(tenant=seeded_tenant, contact=survivor,
                        number="555-0100", is_primary=True)
    ContactPhoneFactory(tenant=seeded_tenant, contact=absorbed,
                        number="555-0199", is_primary=True)

    with tenant_context(seeded_tenant.pk):
        merge.merge_contacts(survivor, absorbed, actor=ff.user, role="FF")
        phones = ContactPhone.objects.filter(contact=survivor)
        assert phones.count() == 2
        assert sum(1 for p in phones if p.is_primary) == 1


@pytest.mark.django_db
def test_a_survivor_with_no_primary_gains_one_from_the_absorbed_record(
    seeded_tenant, ff
):
    survivor = ContactFactory(tenant=seeded_tenant, first_name="Dana")
    absorbed = ContactFactory(tenant=seeded_tenant, first_name="Dana")
    ContactPhoneFactory(tenant=seeded_tenant, contact=survivor,
                        number="555-0100", is_primary=False)
    ContactPhoneFactory(tenant=seeded_tenant, contact=absorbed,
                        number="555-0199", is_primary=True)

    with tenant_context(seeded_tenant.pk):
        merge.merge_contacts(survivor, absorbed, actor=ff.user, role="FF")
        phones = {p.number: p.is_primary for p in ContactPhone.objects.filter(contact=survivor)}
        assert phones == {"555-0100": False, "555-0199": True}


# ================================================ item 5 — who it comes from

@pytest.fixture
def connected_ff(seeded_tenant, ff):
    """An FF whose own address is a VERIFIED send-as — the only state in which
    Gmail would accept it."""
    from django.utils import timezone

    ff.user.email = "bryan@getexecutivesnow.com"
    ff.user.full_name = "Bryan Baker"
    ff.user.save(update_fields=["email", "full_name"])
    return GmailConnectionFactory(
        tenant=seeded_tenant, user=ff.user,
        email_address="bryan@getexecutivesnow.com",
        send_as_address=seeded_tenant.from_address,
        send_as_verified_at=timezone.now(),
    )


@pytest.mark.django_db
def test_touches_default_to_the_persons_own_address(seeded_tenant, ff, connected_ff):
    """A partner asked for introductions should hear from a person, not info@."""
    with tenant_context(seeded_tenant.pk):
        assert sender.resolve_from(seeded_tenant, ff.user, "referral_touch") == \
            "bryan@getexecutivesnow.com"
        assert sender.resolve_from(seeded_tenant, ff.user, "referral_onboarding") == \
            "bryan@getexecutivesnow.com"


@pytest.mark.django_db
def test_stage_rules_and_manual_default_to_the_alias(seeded_tenant, ff, connected_ff):
    with tenant_context(seeded_tenant.pk):
        assert sender.resolve_from(seeded_tenant, ff.user, "stage_rule") == \
            seeded_tenant.from_address
        assert sender.resolve_from(seeded_tenant, ff.user, "manual") == \
            seeded_tenant.from_address


@pytest.mark.django_db
def test_an_unverified_own_address_falls_back_to_the_alias(seeded_tenant, ff):
    """No Gmail connection: offering "my own address" would fail at send time."""
    with tenant_context(seeded_tenant.pk):
        assert sender.resolve_from(seeded_tenant, ff.user, "referral_touch") == \
            seeded_tenant.from_address


@pytest.mark.django_db
def test_a_stored_preference_overrides_the_default(seeded_tenant, ff, connected_ff, api):
    response = api.as_(ff).post("/api/mail-preference/", {
        "sender_by_producer": {"referral_touch": "alias", "stage_rule": "self"},
    }, content_type="application/json")
    assert response.status_code == 200
    assert response.json()["effective"]["referral_touch"] == "alias"

    with tenant_context(seeded_tenant.pk):
        assert sender.resolve_from(seeded_tenant, ff.user, "referral_touch") == \
            seeded_tenant.from_address
        assert sender.resolve_from(seeded_tenant, ff.user, "stage_rule") == \
            "bryan@getexecutivesnow.com"


@pytest.mark.django_db
def test_an_unknown_sender_choice_is_refused(seeded_tenant, ff, api):
    response = api.as_(ff).post("/api/mail-preference/", {
        "sender_by_producer": {"referral_touch": "somebody_else"},
    }, content_type="application/json")
    assert response.status_code == 400


@pytest.mark.django_db
def test_a_draft_records_the_from_address_it_resolved(
    seeded_tenant, referrals, ff, connected_ff, api
):
    with tenant_context(seeded_tenant.pk):
        contact = _contact(seeded_tenant)
        referral.add_type(contact, "referral_partner", actor=ff.user)

    body = api.as_(ff).post(f"/api/contacts/{contact.pk}/draft-touch/").json()
    assert body["from_address"] == "bryan@getexecutivesnow.com"
    assert {o["value"] for o in body["sender_options"]} == {"alias", "self"}


@pytest.mark.django_db
def test_the_per_draft_override_wins(seeded_tenant, referrals, ff, connected_ff, api):
    """The person reading the draft has more context than a setting does."""
    with tenant_context(seeded_tenant.pk):
        contact = _contact(seeded_tenant)
        referral.add_type(contact, "referral_partner", actor=ff.user)
    draft = api.as_(ff).post(f"/api/contacts/{contact.pk}/draft-touch/").json()

    edited = api.as_(ff).patch(
        f"/api/outbox/{draft['id']}/edit/", {"sender": "alias"},
        content_type="application/json",
    )
    assert edited.status_code == 200
    assert edited.json()["from_address"] == seeded_tenant.from_address


@pytest.mark.django_db
def test_a_sent_message_can_no_longer_be_edited(seeded_tenant, ff, api):
    from .factories import OutboxMessageFactory

    sent = OutboxMessageFactory(tenant=seeded_tenant, state=S.SENT)
    response = api.as_(ff).patch(
        f"/api/outbox/{sent.pk}/edit/", {"subject": "rewritten"},
        content_type="application/json",
    )
    assert response.status_code == 400
    assert "can no longer be edited" in str(response.json())


@pytest.mark.django_db
def test_the_signature_defaults_to_name_over_practice(seeded_tenant, ff):
    ff.user.full_name = "Bryan Baker"
    ff.user.save(update_fields=["full_name"])
    text, html = sender.signature(seeded_tenant, ff.user)
    assert text == f"Bryan Baker\n{seeded_tenant.name}"
    assert "Bryan Baker" in html


@pytest.mark.django_db
def test_a_configured_signature_replaces_the_default(seeded_tenant, ff, api):
    api.as_(ff).post("/api/mail-preference/", {
        "signature_text": "Bryan\nFractional COO\nExecutives Now",
    }, content_type="application/json")

    with tenant_context(seeded_tenant.pk):
        text, _ = sender.signature(seeded_tenant, ff.user)
    assert text == "Bryan\nFractional COO\nExecutives Now"


@pytest.mark.django_db
def test_a_touch_signs_off_with_the_signature(seeded_tenant, referrals, ff):
    ff.user.full_name = "Bryan Baker"
    ff.user.save(update_fields=["full_name"])
    with tenant_context(seeded_tenant.pk):
        contact = _contact(seeded_tenant)
        body, _, _ = referral.compose_touch(contact, actor=ff.user)
    assert body.rstrip().endswith(f"Bryan Baker\n{seeded_tenant.name}")


# ============================================== item 6 — bulk drafting

@pytest.mark.django_db
def test_drafting_touches_for_several_partners_makes_one_row_each(
    seeded_tenant, referrals, ff, api, dev_outbox
):
    """One row addressed to forty people would be a mailing list, and approval
    would stop being a per-recipient decision."""
    partners = []
    with tenant_context(seeded_tenant.pk):
        for _ in range(3):
            contact = _contact(seeded_tenant)
            referral.add_type(contact, "referral_partner", actor=ff.user)
            partners.append(contact)
        OutboxMessage.objects.filter(producer=P.REFERRAL_ONBOARDING).delete()

    response = api.as_(ff).post(
        "/api/contacts/draft-touches/", {"ids": [str(c.pk) for c in partners]},
        content_type="application/json",
    )

    assert response.status_code == 201
    assert response.json()["drafted_count"] == 3
    with tenant_context(seeded_tenant.pk):
        rows = OutboxMessage.objects.filter(producer=P.REFERRAL_TOUCH)
        assert rows.count() == 3
        assert {r.to_address for r in rows} == {c.primary_email for c in partners}
        assert all(r.state == S.PENDING_APPROVAL for r in rows)
    assert dev_outbox == []


@pytest.mark.django_db
def test_bulk_touches_skip_non_partners_and_say_which(seeded_tenant, referrals, ff, api):
    with tenant_context(seeded_tenant.pk):
        partner = _contact(seeded_tenant)
        referral.add_type(partner, "referral_partner", actor=ff.user)
        stranger = _contact(seeded_tenant, first_name="Notapartner")
        OutboxMessage.objects.all().delete()

    body = api.as_(ff).post(
        "/api/contacts/draft-touches/",
        {"ids": [str(partner.pk), str(stranger.pk)]},
        content_type="application/json",
    ).json()

    assert body["drafted_count"] == 1
    assert body["skipped"][0]["detail"] == "not a referral partner"


@pytest.mark.django_db
def test_bulk_emails_queue_for_approval_not_send(seeded_tenant, ff, api, dev_outbox):
    """Approval stays mandatory for anything reaching a contact's inbox, however
    it was composed."""
    contacts = [_contact(seeded_tenant) for _ in range(2)]

    response = api.as_(ff).post("/api/contacts/draft-emails/", {
        "ids": [str(c.pk) for c in contacts],
        "subject": "A quick update", "body_text": "Hi {first_name}, news below.",
    }, content_type="application/json")

    assert response.status_code == 201
    with tenant_context(seeded_tenant.pk):
        rows = OutboxMessage.objects.filter(producer=P.MANUAL)
        assert rows.count() == 2
        assert all(r.state == S.PENDING_APPROVAL for r in rows)
        # The merge field is filled per recipient, not left literal.
        assert all("{first_name}" not in r.body_text for r in rows)
    assert dev_outbox == [], "Bulk drafting sent mail. It must only queue."


@pytest.mark.django_db
def test_a_cf_cannot_bulk_draft_outside_their_universe(seeded_tenant, cf, ff, api):
    """FR-1.9c — the selection is filtered by what that role may see."""
    invisible = _contact(seeded_tenant, owner=ff.user)

    body = api.as_(cf).post(
        "/api/contacts/draft-emails/",
        {"ids": [str(invisible.pk)], "subject": "Hi", "body_text": "Hello"},
        content_type="application/json",
    ).json()
    assert body.get("drafted_count", 0) == 0


# ------------------------------------------------------- bulk approval

@pytest.mark.django_db
def test_approve_selected_approves_each_one_individually(
    seeded_tenant, ff, api, dev_outbox
):
    from .factories import OutboxMessageFactory

    rows = [
        OutboxMessageFactory(tenant=seeded_tenant, state=S.PENDING_APPROVAL,
                             to_address=f"p{i}@example.invalid")
        for i in range(3)
    ]
    response = api.as_(ff).post(
        "/api/outbox/approve-selected/", {"ids": [str(r.pk) for r in rows]},
        content_type="application/json",
    )

    assert response.status_code == 200, response.content
    assert response.json()["approved_count"] == 3, response.json()
    with tenant_context(seeded_tenant.pk):
        assert OutboxMessage.objects.filter(state=S.SENT).count() == 3


@pytest.mark.django_db
def test_a_va_cannot_approve_a_batch(seeded_tenant, va, api):
    """Matrix 5.3 — the H7 boundary holds for a batch exactly as for one."""
    from .factories import OutboxMessageFactory

    row = OutboxMessageFactory(tenant=seeded_tenant, state=S.PENDING_APPROVAL)
    assert api.as_(va).post(
        "/api/outbox/approve-selected/", {"ids": [str(row.pk)]},
        content_type="application/json",
    ).status_code == 403


@pytest.mark.django_db
def test_approve_selected_ignores_messages_not_pending(
    seeded_tenant, ff, api, dev_outbox
):
    from .factories import OutboxMessageFactory

    pending = OutboxMessageFactory(tenant=seeded_tenant, state=S.PENDING_APPROVAL)
    already = OutboxMessageFactory(tenant=seeded_tenant, state=S.SENT)

    body = api.as_(ff).post(
        "/api/outbox/approve-selected/",
        {"ids": [str(pending.pk), str(already.pk)]}, content_type="application/json",
    ).json()
    assert body["approved_count"] == 1
    assert body["skipped"] == 1


# ============================================ item 7 — draft attachments

@pytest.mark.django_db
def test_an_attachment_can_be_added_to_and_removed_from_a_draft(
    seeded_tenant, ff, api
):
    from .factories import OutboxMessageFactory

    draft = OutboxMessageFactory(tenant=seeded_tenant, state=S.PENDING_APPROVAL)
    upload = SimpleUploadedFile("brief.pdf", b"%PDF-1.4 fake", content_type="application/pdf")

    added = api.as_(ff).post(f"/api/outbox/{draft.pk}/attachments/", {"file": upload})
    assert added.status_code == 201
    assert added.json()["attachments"][0]["filename"] == "brief.pdf"
    attachment_id = added.json()["attachments"][0]["id"]

    removed = api.as_(ff).delete(
        f"/api/outbox/{draft.pk}/attachments/{attachment_id}/"
    )
    assert removed.status_code == 200
    assert removed.json()["attachments"] == []


@pytest.mark.django_db
def test_an_oversized_attachment_is_refused_with_the_limit(seeded_tenant, ff, api):
    from .factories import OutboxMessageFactory

    draft = OutboxMessageFactory(tenant=seeded_tenant, state=S.PENDING_APPROVAL)
    big = SimpleUploadedFile("big.pdf", b"x" * (11 * 1024 * 1024),
                             content_type="application/pdf")

    response = api.as_(ff).post(f"/api/outbox/{draft.pk}/attachments/", {"file": big})
    assert response.status_code == 400
    assert "10 MB" in str(response.json())


@pytest.mark.django_db
def test_a_sent_message_cannot_gain_an_attachment(seeded_tenant, ff, api):
    from .factories import OutboxMessageFactory

    sent = OutboxMessageFactory(tenant=seeded_tenant, state=S.SENT)
    upload = SimpleUploadedFile("late.pdf", b"x", content_type="application/pdf")
    response = api.as_(ff).post(f"/api/outbox/{sent.pk}/attachments/", {"file": upload})
    assert response.status_code == 400
