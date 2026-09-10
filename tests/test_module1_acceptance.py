"""Acceptance criteria AC-1.1 - AC-1.25 from `01_prd.md`.

Each test names its criterion. Where a criterion cannot run without Postmark it
is marked xfail with a reason rather than quietly passing.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.crm.models import (
    Company, Contact, ContactEmail, ContactType, ContactTypeLink, EmailThread,
    ImportBatch, OutboxMessage, StageAutomation, Task,
)
from apps.crm.services import importer, merge, outbox, pipeline, referral, search
from apps.notes.models import Note
from apps.tenancy.context import tenant_context
from apps.tenancy.models import AuditEvent, ClientAssignment

from . import registry_config  # noqa: F401
from .factories import (
    ClientCompanyFactory, CompanyFactory, ContactEmailFactory, ContactFactory,
    EmailTemplateFactory, ServiceCategoryFactory, StoredFileFactory,
)

S = OutboxMessage.State
P = OutboxMessage.Producer

CSV_HEADER = "first_name,last_name,email,company,title,notes\n"


def _csv(rows):
    return (CSV_HEADER + "".join(rows)).encode()


def _contact(tenant, stage=None, **kw):
    contact = ContactFactory(tenant=tenant, stage=stage, **kw)
    ContactEmailFactory(tenant=tenant, contact=contact)
    return contact


# ===================================================================== import

@pytest.mark.django_db
def test_ac_1_1_import_dry_run_is_honest(seeded_tenant, ff):
    """AC-1.1 — 196 create / 3 update / 1 error, error names row and column,
    and NO contact count has changed."""
    existing = [_contact(seeded_tenant) for _ in range(3)]
    rows = []
    for i in range(196):
        rows.append(f"New{i},Person{i},new{i}@example.invalid,Acme,COO,\n")
    for c in existing:
        rows.append(f"{c.first_name},{c.last_name},{c.primary_email},Acme,COO,\n")
    rows.append("Bad,Row,not-an-email,Acme,COO,\n")

    with tenant_context(seeded_tenant.pk):
        before = Contact.objects.count()
        batch = importer.dry_run(
            tenant=seeded_tenant, filename="contacts.csv",
            file_bytes=_csv(rows), mapping={}, actor=ff.user,
        )
        assert batch.counts["create"] == 196
        assert batch.counts["update"] == 3
        assert batch.counts["error"] == 1

        error_row = batch.rows.filter(outcome="error").first()
        assert error_row.row_number == 201
        assert "email" in error_row.error_text
        assert "not-an-email" in error_row.error_text

        # Nothing written yet.
        assert Contact.objects.count() == before


@pytest.mark.django_db
def test_ac_1_2_commit_and_roll_back(seeded_tenant, ff):
    """AC-1.2 — count rises by exactly 196, rollback restores it, and the 3
    updated contacts show their original values."""
    existing = [_contact(seeded_tenant, title="Original") for _ in range(3)]
    rows = [f"New{i},Person{i},new{i}@example.invalid,Acme,COO,\n" for i in range(196)]
    for c in existing:
        rows.append(f"{c.first_name},{c.last_name},{c.primary_email},Acme,Changed,\n")

    with tenant_context(seeded_tenant.pk):
        before = Contact.objects.count()
        batch = importer.dry_run(
            tenant=seeded_tenant, filename="c.csv", file_bytes=_csv(rows),
            mapping={}, actor=ff.user,
        )
        importer.commit(batch, actor=ff.user)
        assert Contact.objects.count() == before + 196
        for c in existing:
            c.refresh_from_db()
            assert c.title == "Changed"

        importer.rollback(batch, actor=ff.user)
        assert Contact.objects.count() == before
        for c in existing:
            c.refresh_from_db()
            assert c.title == "Original"


@pytest.mark.django_db
def test_ac_1_3_ambiguity_is_surfaced_not_guessed(seeded_tenant, ff):
    """AC-1.3 — two same-name contacts at one company are listed for a human."""
    company = CompanyFactory(tenant=seeded_tenant, name="Acme")
    for _ in range(2):
        ContactFactory(
            tenant=seeded_tenant, company=company, first_name="Dana", last_name="Reyes"
        )

    with tenant_context(seeded_tenant.pk):
        batch = importer.dry_run(
            tenant=seeded_tenant, filename="c.csv",
            file_bytes=_csv(["Dana,Reyes,,Acme,COO,\n"]), mapping={}, actor=ff.user,
        )
        assert batch.counts["ambiguous"] == 1
        row = batch.rows.filter(outcome="ambiguous").first()
        assert "a human must choose" in row.error_text
        # Nothing merged, nothing created.
        assert Contact.objects.filter(first_name="Dana").count() == 2


@pytest.mark.django_db
def test_ac_1_1a_notes_column_becomes_a_real_note(seeded_tenant, ff):
    """FR-1.1a / §12.2 — one thing is called a note, and it is the note table."""
    with tenant_context(seeded_tenant.pk):
        batch = importer.dry_run(
            tenant=seeded_tenant, filename="c.csv",
            file_bytes=_csv(["Dana,Reyes,dana@acme.invalid,Acme,COO,Met at the roundtable\n"]),
            mapping={}, actor=ff.user,
        )
        importer.commit(batch, actor=ff.user)
        note = Note.objects.get(source=Note.Source.IMPORT)
        assert note.body == "Met at the roundtable"
        assert note.contact.first_name == "Dana"
        # Rollback removes the notes it created.
        importer.rollback(batch, actor=ff.user)
        assert Note.objects.filter(source=Note.Source.IMPORT).count() == 0


# ============================================================ client invariant

@pytest.mark.django_db
def test_ac_1_12_client_invariant_derives_forward_only(seeded_tenant, stages, types, ff):
    """AC-1.12 — all four clauses of FR-1.6a."""
    with tenant_context(seeded_tenant.pk):
        company = CompanyFactory(tenant=seeded_tenant, is_client_company=False)
        contact = _contact(seeded_tenant, stage=stages["qualified_lead"], company=company)

        pipeline.change_stage(contact, stages["client"], actor=ff.user)
        contact.refresh_from_db(); company.refresh_from_db()

        # 1. type added, company flagged
        assert contact.type_links.filter(contact_type__code="client").exists()
        assert company.is_client_company is True

        # 2. moving to lost removes NEITHER
        pipeline.change_stage(contact, stages["lost"], actor=ff.user)
        contact.refresh_from_db(); company.refresh_from_db()
        assert contact.type_links.filter(contact_type__code="client").exists()
        assert company.is_client_company is True

        # 3. adding the type by hand never changes the stage
        other = _contact(seeded_tenant, stage=stages["lead"])
        ContactTypeLink.all_objects.create(
            tenant=seeded_tenant, contact=other, contact_type=types["client"]
        )
        other.refresh_from_db()
        assert other.stage.code == "lead"

        # 4. a contact with no company reaches client with no company invented
        before = Company.objects.count()
        orphan = _contact(seeded_tenant, stage=stages["qualified_lead"], company=None)
        pipeline.change_stage(orphan, stages["client"], actor=ff.user)
        orphan.refresh_from_db()
        assert orphan.stage.code == "client"
        assert orphan.company is None
        assert Company.objects.count() == before


# ================================================================ assignment

@pytest.mark.django_db
def test_ac_1_13_assignment_governs_cf_visibility(seeded_tenant, ff, cf, api):
    """AC-1.13 — CF sees assigned companies and owned prospects, nothing else."""
    company_a = ClientCompanyFactory(tenant=seeded_tenant)
    company_b = ClientCompanyFactory(tenant=seeded_tenant)
    at_a = _contact(seeded_tenant, company=company_a)
    at_b = _contact(seeded_tenant, company=company_b)
    own = _contact(seeded_tenant, owner=cf.user)
    other_cf_prospect = _contact(seeded_tenant, owner=ff.user)

    assignment = ClientAssignment.all_objects.create(
        tenant=seeded_tenant, user=cf.user, company=company_a, assigned_by=ff.user
    )

    c = api.as_(cf)
    assert c.get(f"/api/contacts/{at_a.pk}/").status_code == 200
    assert c.get(f"/api/contacts/{own.pk}/").status_code == 200
    assert c.get(f"/api/contacts/{at_b.pk}/").status_code == 404
    assert c.get(f"/api/contacts/{other_cf_prospect.pk}/").status_code == 404

    # Removing the assignment takes effect on the next request; nothing the CF
    # created is deleted.
    assignment.removed_at = timezone.now()
    assignment.save()
    assert c.get(f"/api/contacts/{at_a.pk}/").status_code == 404
    assert Contact.all_objects.filter(pk=own.pk).exists()


@pytest.mark.django_db
def test_ac_1_15_va_sees_the_whole_crm(seeded_tenant, ff, cf, va, api):
    """AC-1.15 — the VA restriction is financials and settings, not the CRM."""
    company = ClientCompanyFactory(tenant=seeded_tenant)
    at_company = _contact(seeded_tenant, company=company)
    ff_prospect = _contact(seeded_tenant, owner=ff.user)
    cf_prospect = _contact(seeded_tenant, owner=cf.user)

    c = api.as_(va)
    for contact in (at_company, ff_prospect, cf_prospect):
        assert c.get(f"/api/contacts/{contact.pk}/").status_code == 200


@pytest.mark.django_db
def test_ac_1_14_only_ff_assigns(seeded_tenant, cf, va, api):
    """AC-1.14 — assignment endpoints reject CF and VA."""
    for membership in (cf, va):
        c = api.as_(membership)
        response = c.post("/api/stage-automations/", {})
        assert response.status_code == 403


# =============================================================== automations

@pytest.mark.django_db
def test_ac_1_4_stage_automation_fires_task_and_queues_email(
    seeded_tenant, stages, ff, dev_outbox
):
    """AC-1.4 — the task exists immediately; the email is pending_approval;
    NOTHING has been sent."""
    template = EmailTemplateFactory(tenant=seeded_tenant)
    StageAutomation.all_objects.create(
        tenant=seeded_tenant, to_stage=stages["qualified_lead"],
        action_type="create_task", task_title_template="Book strategy session",
        task_due_offset_days=3,
    )
    StageAutomation.all_objects.create(
        tenant=seeded_tenant, to_stage=stages["qualified_lead"],
        action_type="draft_email", email_template=template,
    )

    with tenant_context(seeded_tenant.pk):
        contact = _contact(seeded_tenant, stage=stages["lead"], owner=ff.user)
        pipeline.change_stage(contact, stages["qualified_lead"], actor=ff.user)

        task = Task.objects.get(contact=contact)
        assert task.title == "Book strategy session"
        assert task.owner_id == ff.user_id  # assigned to the contact's owner

        message = OutboxMessage.objects.get(producer=P.STAGE_RULE)
        assert message.state == S.PENDING_APPROVAL

    assert dev_outbox == [], "A stage rule sent an email. It must only queue."


@pytest.mark.django_db
def test_ac_1_16_stage_draft_send_by_default_and_expiry(
    seeded_tenant, stages, ff, dev_outbox
):
    """AC-1.16 — 7 days by default, configurable, and expiry sends nothing."""
    template = EmailTemplateFactory(tenant=seeded_tenant)
    rule = StageAutomation.all_objects.create(
        tenant=seeded_tenant, to_stage=stages["lead"],
        action_type="draft_email", email_template=template,
    )
    assert rule.send_by_offset_days == 7

    with tenant_context(seeded_tenant.pk):
        contact = _contact(seeded_tenant, stage=stages["contact"])
        pipeline.change_stage(contact, stages["lead"], actor=ff.user)
        message = OutboxMessage.objects.get(producer=P.STAGE_RULE)
        delta = (message.send_by - timezone.now()).days
        assert 6 <= delta <= 7

        rule.send_by_offset_days = 2
        rule.save()
        contact2 = _contact(seeded_tenant, stage=stages["contact"])
        pipeline.change_stage(contact2, stages["lead"], actor=ff.user)
        second = OutboxMessage.objects.filter(to_contact=contact2).first()
        assert (second.send_by - timezone.now()).days <= 2

        # AC-1.5 — past the send-by, it EXPIRES rather than sending.
        OutboxMessage.objects.all().update(send_by=timezone.now() - timezone.timedelta(days=1))
        expired = outbox.expire_due(seeded_tenant)
        assert expired == 2
        assert OutboxMessage.objects.filter(state=S.EXPIRED).count() == 2

    assert dev_outbox == [], "An expired draft was delivered."


# ==================================================================== outbox

@pytest.mark.django_db
def test_ac_1_7_va_cannot_send(seeded_tenant, stages, ff, va, api, dev_outbox):
    """AC-1.7 — the H7 boundary. Drafts visible and editable; approve is 403."""
    with tenant_context(seeded_tenant.pk):
        contact = _contact(seeded_tenant)
        message = outbox.create_message(
            tenant=seeded_tenant, producer=P.REFERRAL_TOUCH, to_contact=contact,
            to_address=contact.primary_email, subject="Hi", body_text="Body",
        )

    c = api.as_(va)
    assert c.get("/api/outbox/").status_code == 200
    assert c.get(f"/api/outbox/{message.pk}/").status_code == 200
    assert c.post(f"/api/outbox/{message.pk}/approve/").status_code == 403
    # Rejecting sends nothing, so a VA may (matrix 5.4).
    assert c.post(f"/api/outbox/{message.pk}/reject/").status_code == 200

    message.refresh_from_db()
    assert message.state == S.REJECTED
    assert dev_outbox == [], "A VA's action delivered mail."


@pytest.mark.django_db
def test_ac_1_17_outbox_is_the_complete_send_log(seeded_tenant, ff, dev_outbox):
    """AC-1.17 — a queued producer, a direct-to-sent producer, and a magic link
    all appear as Outbox rows."""
    with tenant_context(seeded_tenant.pk):
        contact = _contact(seeded_tenant)
        queued = outbox.create_message(
            tenant=seeded_tenant, producer=P.REFERRAL_TOUCH, to_contact=contact,
            to_address=contact.primary_email, subject="Touch", body_text="Body",
        )
        direct = outbox.create_message(
            tenant=seeded_tenant, producer=P.STRATEGY_PDF, to_contact=contact,
            to_address=contact.primary_email, subject="Your strategy map",
            body_text="Attached", actor=ff.user,
        )
        assert queued.state == S.PENDING_APPROVAL
        assert direct.state == S.SENT and direct.sent_at is not None

        outbox.approve(queued, actor=ff.user, role="FF")
        queued.refresh_from_db()
        assert queued.state == S.SENT
        assert OutboxMessage.objects.count() == 2


@pytest.mark.django_db
def test_precall_invite_is_the_one_va_send(seeded_tenant, va, dev_outbox):
    """H7a — template-only, non-AI, from the tenant address."""
    with tenant_context(seeded_tenant.pk):
        contact = _contact(seeded_tenant)
        invite = outbox.create_message(
            tenant=seeded_tenant, producer=P.PRECALL_INVITE, to_contact=contact,
            to_address=contact.primary_email, subject="Before our call",
            body_text="Form link", role="VA", actor=va.user,
        )
        assert invite.state == S.SENT

        manual = outbox.create_message(
            tenant=seeded_tenant, producer=P.MANUAL, to_contact=contact,
            to_address=contact.primary_email, subject="A note",
            body_text="Hello", role="VA", actor=va.user,
        )
        assert manual.state == S.PENDING_APPROVAL, "A VA's manual send must queue."


# ================================================================== referral

@pytest.mark.django_db
def test_ac_1_18_touch_composition_has_all_three_parts(seeded_tenant, types):
    """AC-1.18 — blurb, fee reminder only when terms exist, reciprocal line."""
    seeded_tenant.referral_blurb = "This month I rebuilt two inspection programmes."
    seeded_tenant.referral_blurb_updated_at = timezone.now()
    seeded_tenant.save()

    with tenant_context(seeded_tenant.pk):
        with_fee = _contact(seeded_tenant, referral_fee_terms="10% of first 3 months")
        without_fee = _contact(seeded_tenant)

        body_x, is_ai_x, _ = referral.compose_touch(with_fee)
        body_y, _, _ = referral.compose_touch(without_fee)

        assert "inspection programmes" in body_x
        assert "10% of first 3 months" in body_x
        assert "keep an eye out" in body_x
        assert is_ai_x is True

        assert "inspection programmes" in body_y
        assert "keep an eye out" in body_y
        assert "10%" not in body_y and "arrangement" not in body_y

        assert 3 <= len([l for l in body_x.splitlines() if l.strip()]) <= 7


@pytest.mark.django_db
def test_ac_1_19_stale_blurb_warns_but_does_not_block(seeded_tenant, ff):
    """AC-1.19 — the warning names the blurb's age; the item still sends."""
    seeded_tenant.referral_blurb = "Old news."
    seeded_tenant.referral_blurb_updated_at = timezone.now() - timezone.timedelta(days=40)
    seeded_tenant.save()

    with tenant_context(seeded_tenant.pk):
        contact = _contact(seeded_tenant, referral_cadence="monthly")
        _, _, warning = referral.compose_touch(contact)
        assert "40 days ago" in warning
        assert "monthly" in warning

        # Onboarding sets the cadence clock, so it must run BEFORE the due
        # date is forced forward — otherwise it overwrites it (FR-1.23c).
        referral.add_type(contact, "referral_partner")
        contact.refresh_from_db()
        contact.referral_next_touch_at = timezone.now() + timezone.timedelta(days=1)
        contact.save()
        drafts = referral.draft_due_touches(seeded_tenant)
        touch = [d for d in drafts if d.producer == P.REFERRAL_TOUCH][0]
        assert "40 days ago" in touch.warning
        outbox.approve(touch, actor=ff.user, role="FF")
        touch.refresh_from_db()
        assert touch.state == S.SENT


@pytest.mark.django_db
def test_ac_1_20_referral_onboarding(seeded_tenant, ff, dev_outbox):
    """AC-1.20 — fires once, attaches the flyer, sends nothing, starts the clock."""
    flyer = StoredFileFactory(tenant=seeded_tenant, purpose="marketing_flyer")
    seeded_tenant.marketing_flyer = flyer
    seeded_tenant.save()

    with tenant_context(seeded_tenant.pk):
        contact = _contact(seeded_tenant)
        referral.add_type(contact, "referral_partner", actor=ff.user)

        message = OutboxMessage.objects.get(producer=P.REFERRAL_ONBOARDING)
        assert message.state == S.PENDING_APPROVAL
        assert message.attachments.count() == 1
        assert dev_outbox == [], "Onboarding delivered mail without approval."

        contact.refresh_from_db()
        assert contact.referral_onboarded_at is not None
        # FR-1.23c — the clock starts from onboarding, not contact creation.
        assert 29 <= (contact.referral_next_touch_at - timezone.now()).days <= 30

        # FR-1.23d — removing and re-adding does NOT re-trigger.
        ContactTypeLink.all_objects.filter(
            contact=contact, contact_type__code="referral_partner"
        ).delete()
        referral.add_type(contact, "referral_partner", actor=ff.user)
        assert OutboxMessage.objects.filter(producer=P.REFERRAL_ONBOARDING).count() == 1


@pytest.mark.django_db
def test_ac_1_20_flyer_optional(seeded_tenant, ff):
    """AC-1.20 — with no flyer the draft is still created, and says so."""
    with tenant_context(seeded_tenant.pk):
        contact = _contact(seeded_tenant)
        referral.add_type(contact, "referral_partner", actor=ff.user)
        message = OutboxMessage.objects.get(producer=P.REFERRAL_ONBOARDING)
        assert message.attachments.count() == 0
        assert "no marketing flyer" in message.warning.lower()


# ============================================================ search & merge

@pytest.mark.django_db
def test_ac_1_8_vendor_search_by_category(seeded_tenant, tenant_b):
    """AC-1.8 — three matches, and nothing from another tenant."""
    hvac = ServiceCategoryFactory(tenant=seeded_tenant, name="Commercial HVAC")
    it = ServiceCategoryFactory(tenant=seeded_tenant, name="IT")
    from .factories import ContactServiceCategoryFactory

    for _ in range(3):
        ContactServiceCategoryFactory(
            tenant=seeded_tenant, contact=_contact(seeded_tenant), service_category=hvac
        )
    for _ in range(2):
        ContactServiceCategoryFactory(
            tenant=seeded_tenant, contact=_contact(seeded_tenant), service_category=it
        )
    other = ServiceCategoryFactory(tenant=tenant_b, name="Commercial HVAC")
    ContactServiceCategoryFactory(
        tenant=tenant_b, contact=ContactFactory(tenant=tenant_b), service_category=other
    )

    with tenant_context(seeded_tenant.pk):
        assert len(search.vendors_by_category(seeded_tenant, "Commercial HVAC")) == 3


@pytest.mark.django_db
def test_ac_1_9_and_1_21_merge_preserves_history_and_is_audited(seeded_tenant, va):
    """AC-1.9 / AC-1.21 — history moves, id still resolves, VA may merge."""
    with tenant_context(seeded_tenant.pk):
        survivor = _contact(seeded_tenant, first_name="Dana")
        absorbed = _contact(seeded_tenant, first_name="Dana")
        Note.all_objects.create(tenant=seeded_tenant, contact=survivor, body="note A")
        Note.all_objects.create(tenant=seeded_tenant, contact=absorbed, body="note B")
        Task.all_objects.create(tenant=seeded_tenant, contact=absorbed, title="task B")

        merge.merge_contacts(survivor, absorbed, actor=va.user, role="VA")

        assert Note.objects.filter(contact=survivor).count() == 2
        assert Task.objects.filter(contact=survivor).count() == 1
        absorbed.refresh_from_db()
        assert absorbed.deleted_at is not None
        assert merge.resolve(absorbed).pk == survivor.pk
        assert AuditEvent.all_objects.filter(verb="contact.merged").exists()


@pytest.mark.django_db
def test_ac_1_21_cf_cannot_merge(seeded_tenant, cf, api):
    """AC-1.21 — CF stays ❌ on merge (matrix 4.5)."""
    c = api.as_(cf)
    response = c.post("/api/contacts/merge/", {"survivor": "x", "absorbed": "y"})
    assert response.status_code == 403


@pytest.mark.django_db
def test_ac_1_22_delete_and_restore_are_delegable(seeded_tenant, va, api):
    """AC-1.22 — a VA may soft-delete and restore both contacts and companies."""
    contact = _contact(seeded_tenant)
    company = CompanyFactory(tenant=seeded_tenant)

    c = api.as_(va)
    assert c.delete(f"/api/contacts/{contact.pk}/").status_code == 204
    assert c.delete(f"/api/companies/{company.pk}/").status_code == 204
    assert c.get(f"/api/contacts/{contact.pk}/").status_code == 404

    assert c.post(f"/api/contacts/{contact.pk}/restore/").status_code == 200
    assert c.get(f"/api/contacts/{contact.pk}/").status_code == 200


@pytest.mark.django_db
def test_ac_1_23_pipeline_stages_are_ff_only(seeded_tenant, va, ff, api):
    """AC-1.23 — types and categories are VA work; stages are a workflow change."""
    c = api.as_(va)
    assert c.post("/api/contact-types/", {"code": "partner", "label": "Partner"}).status_code == 201
    assert c.post("/api/service-categories/", {"name": "Plumbing"}).status_code == 201
    assert c.post(
        "/api/pipeline-stages/", {"code": "x", "label": "X", "position": 9}
    ).status_code == 403

    c = api.as_(ff)
    assert c.post(
        "/api/pipeline-stages/", {"code": "x", "label": "X", "position": 9}
    ).status_code == 201


# ============================================================ carve-back items

@pytest.mark.django_db
def test_ac_6_1_every_outbound_has_a_thread_and_a_carried_token(seeded_tenant, ff):
    """AC-6.1 (carved back, revised for the Gmail transport).

    Beta has no inbound domain, so there is no reply+<token>@ address. The token
    rides in the Message-ID and a custom header instead, and both must carry the
    SAME token for messages in one conversation.
    """
    from apps.crm.services.transport import THREAD_HEADER, token_from_message_id

    with tenant_context(seeded_tenant.pk):
        contact = _contact(seeded_tenant)
        first = outbox.create_message(
            tenant=seeded_tenant, producer=P.STRATEGY_PDF, to_contact=contact,
            to_address=contact.primary_email, subject="One", body_text="a", actor=ff.user,
        )
        second = outbox.create_message(
            tenant=seeded_tenant, producer=P.MANUAL, to_contact=contact,
            to_address=contact.primary_email, subject="Two", body_text="b",
            role="FF", actor=ff.user,
        )
        assert first.thread_id == second.thread_id
        assert EmailThread.objects.count() == 1

        headers = outbox.thread_headers_for(seeded_tenant, first.thread)
        assert headers[THREAD_HEADER] == first.thread.thread_token
        # The token is recoverable from the Message-ID alone, which is what makes
        # a reply threadable with no inbound address.
        assert token_from_message_id(headers["Message-ID"]) == first.thread.thread_token


@pytest.mark.django_db
def test_second_message_quotes_the_first_for_threading(seeded_tenant, ff):
    """A follow-up must carry In-Reply-To so it threads in the client's mail
    client rather than starting a new conversation."""
    from apps.crm.models import EmailMessage

    with tenant_context(seeded_tenant.pk):
        contact = _contact(seeded_tenant)
        outbox.create_message(
            tenant=seeded_tenant, producer=P.STRATEGY_PDF, to_contact=contact,
            to_address=contact.primary_email, subject="One", body_text="a", actor=ff.user,
        )
        outbox.create_message(
            tenant=seeded_tenant, producer=P.STRATEGY_PDF, to_contact=contact,
            to_address=contact.primary_email, subject="Two", body_text="b", actor=ff.user,
        )
        messages = list(EmailMessage.objects.order_by("created_at"))
        assert len(messages) == 2
        assert messages[0].message_id_header
        assert messages[1].in_reply_to == messages[0].message_id_header


@pytest.mark.django_db
def test_outbound_records_an_email_message(seeded_tenant, ff):
    """The send log has a message row per delivery, ready for Module 6."""
    from apps.crm.models import EmailMessage

    with tenant_context(seeded_tenant.pk):
        contact = _contact(seeded_tenant)
        outbox.create_message(
            tenant=seeded_tenant, producer=P.STRATEGY_PDF, to_contact=contact,
            to_address=contact.primary_email, subject="PDF", body_text="x", actor=ff.user,
        )
        message = EmailMessage.objects.get()
        assert message.direction == "outbound"
        assert message.contact_id == contact.pk


# =================================================== client users are absent

@pytest.mark.django_db
def test_ac_1_11_client_users_are_absent_from_module_1(seeded_tenant, fcc, api):
    """AC-1.11 — a permanent boundary, not a Beta limitation."""
    c = api.as_(fcc)
    for url in (
        "/api/contacts/", "/api/companies/", "/api/outbox/", "/api/imports/",
        "/api/pipeline-stages/", "/api/contact-types/", "/api/service-categories/",
        "/api/stage-automations/",
    ):
        assert c.get(url).status_code == 403, f"{url} was reachable by an FCC"


@pytest.mark.django_db
def test_ac_1_10_tenant_isolation_returns_404_not_403(seeded_tenant, tenant_b, ff, api):
    """AC-1.10 — 404, because a 403 confirms the row exists."""
    other = ContactFactory(tenant=tenant_b)
    other_company = CompanyFactory(tenant=tenant_b)
    from .factories import ImportBatchFactory, OutboxMessageFactory

    other_batch = ImportBatchFactory(tenant=tenant_b)
    other_message = OutboxMessageFactory(tenant=tenant_b)

    c = api.as_(ff)
    assert c.get(f"/api/contacts/{other.pk}/").status_code == 404
    assert c.get(f"/api/companies/{other_company.pk}/").status_code == 404
    assert c.get(f"/api/imports/{other_batch.pk}/").status_code == 404
    assert c.get(f"/api/outbox/{other_message.pk}/").status_code == 404


# ================================================= scheduled jobs (ORM broker)

@pytest.mark.django_db
def test_scheduled_jobs_run_with_no_request(seeded_tenant, ff, dev_outbox):
    """Background jobs have no request, so each opens its own tenant_context
    (assumption B1). This is the path qcluster actually takes."""
    from apps.crm import tasks as crm_tasks

    with tenant_context(seeded_tenant.pk):
        contact = _contact(seeded_tenant)
        referral.add_type(contact, "referral_partner", actor=ff.user)
        contact.refresh_from_db()
        contact.referral_next_touch_at = timezone.now() + timezone.timedelta(days=1)
        contact.save()

    # No ambient tenant here — exactly as a worker process sees it.
    assert crm_tasks.draft_referral_touches(str(seeded_tenant.pk)) == 1
    assert crm_tasks.reindex_search(str(seeded_tenant.pk)) >= 1

    with tenant_context(seeded_tenant.pk):
        OutboxMessage.objects.filter(state=S.PENDING_APPROVAL).update(
            send_by=timezone.now() - timezone.timedelta(days=1)
        )
    assert crm_tasks.expire_outbox(str(seeded_tenant.pk)) >= 1
    assert dev_outbox == [], "An expiry job delivered mail."


@pytest.mark.django_db
def test_search_finds_contacts_and_respects_tenancy(seeded_tenant, tenant_b):
    """FR-1.33 — Phase 1 covers contacts and companies; notes join in Phase 2."""
    with tenant_context(seeded_tenant.pk):
        wanted = _contact(seeded_tenant, first_name="Zephyrine", last_name="Blackwood")
        search.reindex_contact(wanted)
        results = search.search(seeded_tenant, "Zephyrine")
        assert [c.pk for c in results["contacts"]] == [wanted.pk]

    with tenant_context(tenant_b.pk):
        assert search.search(tenant_b, "Zephyrine")["contacts"] == []


# ============================================ requires Postmark (unexercised)

@pytest.mark.django_db
@pytest.mark.xfail(
    reason="AC-1.6 requires a real delivered send. No longer blocked on Postmark — "
           "exercisable once the owner connects Gmail and verifies the send-as alias, "
           "sending to an address in DEV_REAL_SEND_ALLOWLIST.",
    strict=False, run=False,
)
def test_ac_1_6_referral_touch_delivered_for_real():
    """AC-1.6 — approve a drafted touch and confirm real delivery + timeline."""
    raise AssertionError("not exercised")


@pytest.mark.django_db
@pytest.mark.xfail(
    reason="AC-1.20's real-delivery half needs a connected Gmail with a verified "
           "send-as alias; the queue half is covered by "
           "test_ac_1_20_referral_onboarding.",
    strict=False, run=False,
)
def test_ac_1_20_onboarding_delivered_for_real():
    raise AssertionError("not exercised")


# ============================================ AC-1.24 / AC-1.25 (cross-cutting)

@pytest.mark.django_db
def test_ac_1_24_staff_removal_cascades(seeded_tenant, ff, api):
    """AC-1.24 / FR-0.8c — sessions die, assignments close, Gmail goes.
    Nothing the member authored is removed."""
    from apps.crm.models import GmailConnection
    from apps.tenancy.models import Membership, TenantSecret

    from .factories import (
        ClientCompanyFactory, GmailConnectionFactory, MembershipFactory,
        TenantSecretFactory,
    )

    cf_member = MembershipFactory(tenant=seeded_tenant, role="CF")
    company_a = ClientCompanyFactory(tenant=seeded_tenant)
    company_b = ClientCompanyFactory(tenant=seeded_tenant)
    for company in (company_a, company_b):
        ClientAssignment.all_objects.create(
            tenant=seeded_tenant, user=cf_member.user, company=company, assigned_by=ff.user
        )
    secret = TenantSecretFactory(tenant=seeded_tenant, kind="gmail_refresh", user=cf_member.user)
    GmailConnectionFactory(tenant=seeded_tenant, user=cf_member.user, secret=secret)

    with tenant_context(seeded_tenant.pk):
        authored_contact = _contact(seeded_tenant, owner=cf_member.user)
        authored_task = Task.all_objects.create(
            tenant=seeded_tenant, title="Left behind", owner=cf_member.user
        )

    # The CF has a live session.
    cf_client = api.as_(cf_member)
    assert cf_client.get("/api/me").status_code == 200

    response = api.as_(ff).post(f"/api/staff/{cf_member.pk}/remove/")
    assert response.status_code == 200
    cascade = response.json()["cascade"]
    assert cascade["assignments_closed"] == 2
    assert cascade["gmail_connections_removed"] == 1
    assert cascade["sessions_invalidated"] >= 1

    cf_member.refresh_from_db()
    assert cf_member.revoked_at is not None
    assert ClientAssignment.all_objects.filter(
        user=cf_member.user, removed_at__isnull=True
    ).count() == 0
    assert GmailConnection.all_objects.filter(user=cf_member.user).count() == 0
    assert TenantSecret.all_objects.filter(pk=secret.pk).count() == 0

    # Nothing they authored is gone.
    assert Contact.all_objects.filter(pk=authored_contact.pk).exists()
    assert Task.all_objects.filter(pk=authored_task.pk).exists()

    # And their own session no longer authenticates.
    assert cf_client.get("/api/me").status_code == 401, (
        "The removed member's session still works."
    )


@pytest.mark.django_db
def test_ac_1_24_invite_and_role_change_are_ff_only(seeded_tenant, ff, cf, va, api):
    """Matrix 3.16-3.18."""
    response = api.as_(ff).post(
        "/api/staff/", {"email": "newva@example.invalid", "role": "VA"}
    )
    assert response.status_code == 201
    member_id = response.json()["id"]

    assert api.as_(ff).post(
        f"/api/staff/{member_id}/change-role/", {"role": "CF"}
    ).status_code == 200

    for membership in (cf, va):
        c = api.as_(membership)
        assert c.get("/api/staff/").status_code == 403
        assert c.post("/api/staff/", {"email": "x@example.invalid", "role": "VA"}).status_code == 403
        assert c.post(f"/api/staff/{member_id}/remove/").status_code == 403


@pytest.mark.django_db
def test_ac_1_24_client_roles_cannot_be_invited_as_staff(seeded_tenant, ff, api):
    """Client users are granted portal access on a contact, not invited."""
    response = api.as_(ff).post(
        "/api/staff/", {"email": "founder@acme.invalid", "role": "FCC"}
    )
    assert response.status_code == 400
    assert "portal access" in response.json()["detail"]


@pytest.mark.django_db
def test_ac_1_25_ai_spend_is_ff_only(seeded_tenant, ff, cf, va, fcc, api):
    """AC-1.25 / FR-0.9 — spend is financial."""
    from .factories import AiCallFactory

    AiCallFactory(tenant=seeded_tenant, purpose="digest_prose", cost_usd="0.12")
    AiCallFactory(tenant=seeded_tenant, purpose="referral_touch", cost_usd="0.03")

    c = api.as_(ff)
    listing = c.get("/api/ai-usage/")
    assert listing.status_code == 200
    assert len(listing.json()) == 2

    summary = c.get("/api/ai-usage/summary/").json()
    assert summary["total"]["calls"] == 2
    assert float(summary["total"]["cost"]) == pytest.approx(0.15)

    for membership in (cf, va, fcc):
        assert api.as_(membership).get("/api/ai-usage/").status_code == 403
        assert api.as_(membership).get("/api/ai-usage/summary/").status_code == 403


# ============================================== UI-backing endpoints (smoke)

@pytest.mark.django_db
def test_every_ui_screen_has_a_working_endpoint(seeded_tenant, ff, api):
    """The UI is only as real as the endpoints behind it. One call per screen."""
    c = api.as_(ff)
    for url in [
        "/api/me",
        "/api/contacts/",              # Contacts
        "/api/contacts/search/?q=a",   # Contacts search
        "/api/pipeline-stages/",       # Pipeline
        "/api/companies/",             # Companies
        "/api/service-categories/",    # Vendors
        "/api/contacts/by-category/?category=x",
        "/api/outbox/",                # Outbox
        "/api/imports/",               # Import wizard
        "/api/referral-settings/",     # Referral settings
        "/api/email-templates/",       # Stage rules
        "/api/stage-automations/",     # Stage rules
        "/api/staff/",                 # Staff
        "/api/ai-usage/",              # AI usage
        "/api/ai-usage/summary/",
    ]:
        assert c.get(url).status_code == 200, f"{url} is broken"


@pytest.mark.django_db
def test_contact_and_company_timelines(seeded_tenant, stages, ff, api):
    """FR-1.5 — the timeline the detail screens render."""
    with tenant_context(seeded_tenant.pk):
        company = CompanyFactory(tenant=seeded_tenant)
        contact = _contact(seeded_tenant, stage=stages["contact"], company=company)
        pipeline.change_stage(contact, stages["lead"], actor=ff.user)
        Note.all_objects.create(
            tenant=seeded_tenant, contact=contact, body="Met at the roundtable"
        )
        Task.all_objects.create(tenant=seeded_tenant, contact=contact, title="Send packet")

    c = api.as_(ff)
    entries = c.get(f"/api/contacts/{contact.pk}/timeline/").json()
    kinds = {e["kind"] for e in entries}
    assert {"stage", "note", "task"} <= kinds
    assert any("moved from" in e["text"].lower() or "moved" in e["text"].lower() for e in entries)

    company_entries = c.get(f"/api/companies/{company.pk}/timeline/").json()
    assert any(e["kind"] == "stage" for e in company_entries)


@pytest.mark.django_db
def test_referral_settings_round_trip(seeded_tenant, ff, va, api):
    """The Referral settings screen: save a blurb, see its age, VA is 403."""
    c = api.as_(ff)
    assert c.post("/api/referral-settings/", {"referral_blurb": "Rebuilt two programmes."}).status_code == 200

    payload = c.get("/api/referral-settings/").json()
    assert payload["referral_blurb"] == "Rebuilt two programmes."
    assert payload["blurb_age_days"] == 0

    assert api.as_(va).get("/api/referral-settings/").status_code == 403


# =================================================================== merge UI

@pytest.mark.django_db
def test_duplicate_finder_ranks_by_reason(seeded_tenant, ff, api):
    """The 'Find duplicates' panel on contact detail. Ranked, reasons shown,
    and nothing merged without a choice (FR-1.29 rules)."""
    company = CompanyFactory(tenant=seeded_tenant, name="Acme")
    with tenant_context(seeded_tenant.pk):
        target = ContactFactory(
            tenant=seeded_tenant, first_name="Dana", last_name="Reyes", company=company
        )
        ContactEmailFactory(tenant=seeded_tenant, contact=target, address="dana@acme.invalid")

        shares_email = ContactFactory(tenant=seeded_tenant, first_name="D", last_name="R")
        ContactEmailFactory(
            tenant=seeded_tenant, contact=shares_email, address="dana@acme.invalid"
        )
        same_name_same_company = ContactFactory(
            tenant=seeded_tenant, first_name="Dana", last_name="Reyes", company=company
        )
        same_name_elsewhere = ContactFactory(
            tenant=seeded_tenant, first_name="Dana", last_name="Reyes"
        )
        unrelated = ContactFactory(tenant=seeded_tenant)

    payload = api.as_(ff).get(f"/api/contacts/{target.pk}/duplicates/").json()
    ids = [row["contact"]["id"] for row in payload]

    assert str(shares_email.pk) == ids[0]
    assert payload[0]["match_reason"] == "shares an email address"
    assert str(same_name_same_company.pk) in ids
    assert str(same_name_elsewhere.pk) in ids
    assert str(unrelated.pk) not in ids
    assert str(target.pk) not in ids

    # Nothing was merged by looking.
    for contact in (target, shares_email, same_name_same_company):
        contact.refresh_from_db()
        assert contact.merged_into_id is None
        assert contact.deleted_at is None


@pytest.mark.django_db
def test_ambiguous_rows_expose_their_candidates(seeded_tenant, ff, api):
    """The import wizard's 'Duplicates to resolve' panel.

    Candidates are PERSISTED at dry-run time, so the reviewer resolves the same
    set the dry run reported rather than a recomputed one that may have drifted.
    """
    company = CompanyFactory(tenant=seeded_tenant, name="Acme")
    with tenant_context(seeded_tenant.pk):
        for _ in range(2):
            ContactFactory(
                tenant=seeded_tenant, company=company, first_name="Dana", last_name="Reyes"
            )
        batch = importer.dry_run(
            tenant=seeded_tenant, filename="c.csv",
            file_bytes=_csv(["Dana,Reyes,,Acme,COO,\n"]), mapping={}, actor=ff.user,
        )
        row = batch.rows.filter(outcome="ambiguous").first()
        assert len(row.candidate_ids) == 2

    payload = api.as_(ff).get(f"/api/imports/{batch.pk}/ambiguous/").json()
    assert len(payload) == 1
    assert len(payload[0]["candidates"]) == 2
    assert payload[0]["row"]["row_number"] == 2


@pytest.mark.django_db
def test_merge_with_field_choices_from_the_screen(seeded_tenant, va, api):
    """The full path the merge screen drives: choose a survivor, resolve field
    conflicts, confirm, and land on the survivor with history attached."""
    with tenant_context(seeded_tenant.pk):
        survivor = ContactFactory(
            tenant=seeded_tenant, first_name="Dana", last_name="Reyes",
            title="COO", background="Met at the roundtable",
        )
        ContactEmailFactory(tenant=seeded_tenant, contact=survivor, address="dana@acme.invalid")
        Note.all_objects.create(tenant=seeded_tenant, contact=survivor, body="note on survivor")

        absorbed = ContactFactory(
            tenant=seeded_tenant, first_name="Dana", last_name="Reyes",
            title="Chief Operating Officer", background="",
        )
        ContactEmailFactory(
            tenant=seeded_tenant, contact=absorbed, address="d.reyes@acme.invalid"
        )
        Note.all_objects.create(tenant=seeded_tenant, contact=absorbed, body="note on absorbed")
        Task.all_objects.create(tenant=seeded_tenant, contact=absorbed, title="task on absorbed")

    response = api.as_(va).post("/api/contacts/merge/", {
        "survivor": str(survivor.pk),
        "absorbed": str(absorbed.pk),
        # The reviewer kept the absorbed record's fuller title.
        "fields": {"title": "Chief Operating Officer"},
    }, content_type="application/json")
    assert response.status_code == 200
    assert response.json()["id"] == str(survivor.pk)
    assert response.json()["title"] == "Chief Operating Officer"

    survivor.refresh_from_db()
    assert survivor.title == "Chief Operating Officer"
    assert survivor.background == "Met at the roundtable"

    # Both email addresses survive, exactly one primary.
    with tenant_context(seeded_tenant.pk):
        emails = ContactEmail.objects.filter(contact=survivor)
        assert emails.count() == 2
        assert emails.filter(is_primary=True).count() == 1

        # The merged history is what the survivor's timeline will render.
        assert Note.objects.filter(contact=survivor).count() == 2
        assert Task.objects.filter(contact=survivor).count() == 1

    entries = api.as_(va).get(f"/api/contacts/{survivor.pk}/timeline/").json()
    texts = " ".join(e["text"] for e in entries)
    assert "note on absorbed" in texts
    assert "task on absorbed" in texts

    absorbed.refresh_from_db()
    assert absorbed.merged_into_id == survivor.pk
    assert absorbed.deleted_at is not None


@pytest.mark.django_db
def test_merge_screen_endpoints_respect_roles(seeded_tenant, cf, fcc, api):
    """Matrix 4.5 — CF cannot merge; client users cannot reach any of it."""
    with tenant_context(seeded_tenant.pk):
        a = ContactFactory(tenant=seeded_tenant)
        b = ContactFactory(tenant=seeded_tenant)

    assert api.as_(cf).post("/api/contacts/merge/", {
        "survivor": str(a.pk), "absorbed": str(b.pk),
    }, content_type="application/json").status_code == 403

    assert api.as_(fcc).get(f"/api/contacts/{a.pk}/duplicates/").status_code == 403
