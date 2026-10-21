"""The template library (owner, 2026-10-20).

1. Each practice's library is seeded with the app's own wording: five built-in
   templates and the five uses that point at them. Idempotent; the dry run
   writes nothing; a practice's own onboarding template stays its onboarding
   email; the old "AI-drafted" touch becomes "My template".
2. One merge-field style: {FirstName} and the rest, a fallback for a missing
   first name, a line of empty fields left out, unknown fields refused.
3. Every place that drafts picks from the library and is signed once: stage
   rules, touches, onboarding, thank-yous, bulk email.
4. "Draft with Claude" uses the partner's record and last meeting, and falls
   back to the template with no key.
5. Restore, deleting, the uses, role boundaries and isolation.
"""

from __future__ import annotations

import pytest
from django.core.management import call_command

from apps.crm import template_seed
from apps.crm.models import EmailTemplate, EmailTemplateUse, OutboxMessage, StageAutomation
from apps.crm.services import outbox, pipeline, referral, templates
from apps.crm.services import referrals as referral_service
from apps.tenancy.context import tenant_context

from . import registry_config  # noqa: F401
from .factories import (
    ContactEmailFactory, ContactFactory, EmailTemplateFactory, MeetingFactory,
    MeetingParticipantFactory, TenantFactory,
)

ROOT = "/api/email-templates/"
TOUCH_WORDS = ("If there's a type of introduction that would help you right now, "
               "tell me and I'll keep an eye out.")


def person(tenant, first, last="Reyes", **kw):
    contact = ContactFactory(tenant=tenant, first_name=first, last_name=last, **kw)
    ContactEmailFactory(tenant=tenant, contact=contact, is_primary=True,
                        address=f"{(first or 'x').lower()}@x.invalid")
    return contact


def signed_by(ff, name="Bryan Baker"):
    ff.user.full_name = name
    ff.user.save(update_fields=["full_name"])


def use(tenant, key):
    return EmailTemplateUse.all_objects.get(tenant=tenant, use=key).template


# -------------------------------------------------------------- 1. seeding

@pytest.mark.django_db
def test_a_new_practice_gets_the_built_in_library_once(seeded_tenant):
    rows = EmailTemplate.all_objects.filter(tenant=seeded_tenant)
    assert sorted(rows.values_list("original", flat=True)) == sorted(template_seed.ORIGINALS)
    assert sorted(EmailTemplateUse.all_objects.filter(tenant=seeded_tenant)
                  .values_list("use", flat=True)) == sorted(template_seed.USES)
    assert use(seeded_tenant, "thanks_won").original == "thanks_won"
    assert template_seed.seed_tenant(seeded_tenant) == []
    assert rows.count() == 5
    touch = rows.get(original="referral_touch")
    assert "{Signature}" not in touch.body and "Bryan" not in touch.body


@pytest.mark.django_db
def test_the_dry_run_writes_nothing_and_says_what_it_would_do(tenant_a, capsys):
    other = TenantFactory(name="Other Practice", slug="other-practice")
    own = EmailTemplateFactory(tenant=other, kind="referral_onboarding", name="Our hello")
    old = ContactFactory(tenant=other, referral_touch_mode="ai")

    call_command("seed_email_templates", "--dry-run")
    out = capsys.readouterr().out
    assert "Other Practice (other-practice): 10 change(s)" in out
    assert "use “Our hello” for referral_onboarding" in out
    assert "the same words): 1" in out and "Dry run: nothing was written." in out
    assert not EmailTemplate.all_objects.filter(tenant=other).exclude(original="").exists()
    old.refresh_from_db()
    assert old.referral_touch_mode == "ai"

    call_command("seed_email_templates")
    assert use(other, "referral_onboarding") == own, "their own words stay their email"
    assert EmailTemplate.all_objects.get(tenant=other, original="referral_onboarding")
    old.refresh_from_db()
    assert old.referral_touch_mode == "template"
    call_command("seed_email_templates", "--dry-run")
    assert "Other Practice (other-practice): nothing to do" in capsys.readouterr().out


# ------------------------------------------------------------ 2. merging

def test_fields_fallback_and_empty_lines():
    values = {"FirstName": "", "Company": "Acme", "FeeTerms": "", "PracticeNews": "News."}
    text = ("Hi {FirstName},\n\n{PracticeNews}\nAs a reminder: {FeeTerms}.\n"
            "At {Company}, {LastName}.\nBye.")
    assert templates.render(text, values, fallback="friend") == (
        "Hi friend,\n\nNews.\nAt Acme, .\nBye.")
    assert templates.render("{PracticeNews}\n\n\n{FeeTerms}\nEnd", values) == "News.\n\nEnd"
    assert templates.render_subject("For {FirstName}", values) == "For there"
    assert templates.unknown_fields("{FirstName} {Frist} {Company}") == ["Frist"]


@pytest.mark.django_db
def test_an_unknown_field_is_refused_on_save(seeded_tenant, ff, api):
    made = api.as_(ff).post(ROOT, {"name": "Nudge", "subject": "Hi {FirstName}",
                                   "body": "Hello {Frist}"}, content_type="application/json")
    assert made.status_code == 400
    assert "no merge field called {Frist}" in str(made.json())
    made = api.as_(ff).post(ROOT, {"name": "Nudge", "subject": "Hi {FirstName}",
                                   "body": "Hello {FirstName}", "first_name_fallback": " "},
                            content_type="application/json")
    assert made.status_code == 201, made.json()
    assert made.json()["first_name_fallback"] == "there"
    assert made.json()["kind"] == "general" and made.json()["is_original"] is False


# --------------------------------------------- 3. every place that drafts

@pytest.mark.django_db
def test_the_touch_template_is_the_old_wording(seeded_tenant, ff):
    signed_by(ff)
    seeded_tenant.referral_blurb = "Rebuilt two inspection programs."
    seeded_tenant.save(update_fields=["referral_blurb"])
    with tenant_context(seeded_tenant.pk):
        with_fee = person(seeded_tenant, "Marta", referral_fee_terms="10% of year one")
        without = person(seeded_tenant, "", "Okafor")
        subject, body, is_ai, _ = referral.compose_touch(with_fee, actor=ff.user)
        _, bare, _, _ = referral.compose_touch(without, actor=ff.user)
    assert subject == f"Checking in from {seeded_tenant.name}"
    assert body == ("Hi Marta,\n\nRebuilt two inspection programs.\n"
                    "As a reminder of our arrangement: 10% of year one.\n"
                    f"{TOUCH_WORDS}\n\nBryan Baker\n{seeded_tenant.name}")
    assert is_ai is False
    assert bare.startswith("Hi there,\n\nRebuilt two inspection programs.\nIf there's")
    assert bare.count("Bryan Baker") == 1


@pytest.mark.django_db
def test_a_partner_can_have_a_touch_template_of_their_own(seeded_tenant, ff, api):
    signed_by(ff)
    with tenant_context(seeded_tenant.pk):
        own = EmailTemplateFactory(tenant=seeded_tenant, subject="For {FirstName}",
                                   body="Hi {FirstName} at {Company}.")
        marta = person(seeded_tenant, "Marta")
    saved = api.as_(ff).patch(f"/api/contacts/{marta.pk}/", {"referral_template": str(own.pk)},
                              content_type="application/json")
    assert saved.status_code == 200 and saved.json()["referral_template"] == str(own.pk)
    with tenant_context(seeded_tenant.pk):
        marta.refresh_from_db()
        subject, body, _, _ = referral.compose_touch(marta, actor=ff.user)
    assert subject == "For Marta"
    assert body == f"Hi Marta at .\n\nBryan Baker\n{seeded_tenant.name}"


@pytest.mark.django_db
def test_onboarding_says_the_flyer_is_attached_only_when_it_is(seeded_tenant, ff):
    with tenant_context(seeded_tenant.pk):
        partner = person(seeded_tenant, "Lee")
        _, bare = referral.compose_onboarding(partner, actor=ff.user)
        subject, flyer = referral.compose_onboarding(partner, actor=ff.user, with_attachment=True)
    assert subject == "Good to meet you"
    assert templates.FLYER_NOTE not in bare and "\n\n\n" not in bare
    assert templates.FLYER_NOTE in flyer


@pytest.mark.django_db
def test_a_thank_you_uses_the_template_chosen_for_its_moment(seeded_tenant, ff, api, stages):
    signed_by(ff)
    with tenant_context(seeded_tenant.pk):
        mark = person(seeded_tenant, "Mark", "Ellis")
        dana = person(seeded_tenant, "Dana", "Cole")
        warm = EmailTemplateFactory(tenant=seeded_tenant, name="Warm", subject="Thanks, {FirstName}",
                                    body="{FirstName}, thank you for {ProspectName}!")
    chosen = api.as_(ff).post(ROOT + "uses/", {"use": "thanks_recorded", "template": str(warm.pk)},
                              content_type="application/json")
    assert chosen.status_code == 200
    with tenant_context(seeded_tenant.pk):
        referral_service.record(dana, mark, actor=ff.user)
    draft = OutboxMessage.all_objects.get(tenant=seeded_tenant,
                                          producer=OutboxMessage.Producer.REFERRAL_THANKS)
    assert draft.subject == "Thanks, Mark"
    assert draft.body_text == f"Mark, thank you for Dana Cole!\n\nBryan Baker\n{seeded_tenant.name}"


@pytest.mark.django_db
def test_the_built_in_lost_thank_you_still_gives_no_reason(seeded_tenant, ff):
    with tenant_context(seeded_tenant.pk):
        mark = person(seeded_tenant, "Mark", "Ellis")
        dana = person(seeded_tenant, "Dana", "Cole")
        row = referral_service.record(dana, mark, actor=ff.user, from_import=True)
        subject, body = referral_service.compose_thanks(row, "lost", actor=ff.user)
    assert subject == "A quick update, and thank you"
    assert "Dana Cole: it didn't turn into an engagement this time." in body


@pytest.mark.django_db
def test_a_stage_rule_email_is_merged_and_signed(seeded_tenant, ff, stages):
    signed_by(ff)
    with tenant_context(seeded_tenant.pk):
        template = EmailTemplateFactory(tenant=seeded_tenant, subject="Next steps, {FirstName}",
                                        body="Hi {FirstName},\n\nGood to talk.")
        code = next(c for c, s in stages.items() if s.semantic == "qualified")
        StageAutomation.all_objects.create(
            tenant=seeded_tenant, pipeline=stages[code].pipeline, to_stage=stages[code],
            action_type="draft_email", email_template=template)
        dana = person(seeded_tenant, "Dana")
        pipeline.change_stage(dana, stages[code], actor=ff.user)
    draft = OutboxMessage.all_objects.get(tenant=seeded_tenant,
                                          producer=OutboxMessage.Producer.STAGE_RULE)
    assert draft.subject == "Next steps, Dana"
    assert draft.body_text == f"Hi Dana,\n\nGood to talk.\n\nBryan Baker\n{seeded_tenant.name}"


@pytest.mark.django_db
def test_bulk_email_merges_from_a_template_and_refuses_a_typo(seeded_tenant, ff, api, dev_outbox):
    with tenant_context(seeded_tenant.pk):
        template = EmailTemplateFactory(tenant=seeded_tenant, subject="Hello {FirstName}",
                                        body="Hi {FirstName}.", first_name_fallback="friend")
        unnamed = person(seeded_tenant, "", "Okafor")
        dana = person(seeded_tenant, "Dana")
    sent = api.as_(ff).post("/api/contacts/draft-emails/", {
        "ids": [str(unnamed.pk), str(dana.pk)], "template": str(template.pk)},
        content_type="application/json")
    assert sent.status_code == 201, sent.json()
    bodies = sorted(OutboxMessage.all_objects.filter(
        tenant=seeded_tenant, producer=OutboxMessage.Producer.MANUAL)
        .values_list("subject", flat=True))
    assert bodies == ["Hello Dana", "Hello friend"]
    typo = api.as_(ff).post("/api/contacts/draft-emails/", {
        "ids": [str(dana.pk)], "subject": "Hi", "body_text": "Hi {FirstNmae}"},
        content_type="application/json")
    assert typo.status_code == 400 and "{FirstNmae}" in typo.json()["detail"]
    with tenant_context(seeded_tenant.pk):
        old = outbox.create_manual_draft(dana, subject="For {first_name}", body_text="Hi {first_name}",
                                         actor=ff.user)
    assert old.subject == "For Dana" and old.body_text.startswith("Hi Dana")


# ----------------------------------------------------- 4. Draft with Claude

@pytest.mark.django_db
def test_claude_drafts_from_the_record_and_the_last_meeting(seeded_tenant, ff, fake_claude):
    signed_by(ff)
    fake_claude.reply = "Hi Marta,\n\nGood to see you at the expo."
    with tenant_context(seeded_tenant.pk):
        marta = person(seeded_tenant, "Marta", referral_touch_mode="claude",
                       background="Runs a bookkeeping firm.", referral_fee_terms="10%")
        old = MeetingFactory(tenant=seeded_tenant, title="Coffee", summary="Old news.")
        MeetingParticipantFactory(tenant=seeded_tenant, meeting=old, contact=marta)
        recent = MeetingFactory(tenant=seeded_tenant, title="Expo", summary="Talked hiring.",
                                meeting_date="2026-10-01")
        MeetingParticipantFactory(tenant=seeded_tenant, meeting=recent, contact=marta)
        subject, body, is_ai, _ = referral.compose_touch(marta, actor=ff.user)
    asked = str(fake_claude.requests[-1]["messages"])
    assert "Runs a bookkeeping firm." in asked and "Talked hiring." in asked
    assert "Old news." not in asked and "Fee terms: 10%" in asked
    assert "keep an eye out" in asked, "the template is given for its shape"
    assert is_ai is True and subject == f"Checking in from {seeded_tenant.name}"
    assert body == f"Hi Marta,\n\nGood to see you at the expo.\n\nBryan Baker\n{seeded_tenant.name}"


@pytest.mark.django_db
def test_with_no_key_claude_mode_falls_back_to_the_template(seeded_tenant, ff, settings):
    settings.ANTHROPIC_API_KEY = ""
    with tenant_context(seeded_tenant.pk):
        marta = person(seeded_tenant, "Marta", referral_touch_mode="claude")
        _, body, is_ai, warning = referral.compose_touch(marta, actor=ff.user)
    assert is_ai is False and TOUCH_WORDS in body
    assert warning.startswith("Drafted from the template instead of by Claude: No Anthropic")


# -------------------------------------------- 5. restore, delete, roles

@pytest.mark.django_db
def test_restore_puts_the_original_back(seeded_tenant, ff, va, api):
    with tenant_context(seeded_tenant.pk):
        won = use(seeded_tenant, "thanks_won")
    listed = api.as_(ff).get(ROOT).json()
    assert [t["is_original"] for t in listed][:5] == [True] * 5, "built-in ones first"
    edited = api.as_(va).patch(f"{ROOT}{won.pk}/", {"body": "Yay {ProspectName}!"},
                               content_type="application/json")
    assert edited.status_code == 200 and edited.json()["changed"] is True
    assert "Thank-you when the prospect is won" in edited.json()["used_for"]
    restored = api.as_(va).post(f"{ROOT}{won.pk}/restore/").json()
    assert restored["body"] == template_seed.ORIGINALS["thanks_won"][2]
    assert restored["changed"] is False


@pytest.mark.django_db
def test_a_built_in_or_used_template_is_not_deleted(seeded_tenant, ff, va, api):
    with tenant_context(seeded_tenant.pk):
        touch = use(seeded_tenant, "referral_touch")
        spare = EmailTemplateFactory(tenant=seeded_tenant)
        busy = EmailTemplateFactory(tenant=seeded_tenant)
        person(seeded_tenant, "Marta", referral_template=busy)
    assert api.as_(ff).delete(f"{ROOT}{touch.pk}/").status_code == 409
    refused = api.as_(ff).delete(f"{ROOT}{busy.pk}/")
    assert refused.status_code == 409 and "the touch for 1 partner" in refused.json()["detail"]
    assert api.as_(va).delete(f"{ROOT}{spare.pk}/").status_code == 403
    assert api.as_(ff).delete(f"{ROOT}{spare.pk}/").status_code == 204


@pytest.mark.django_db
def test_only_the_owner_chooses_a_use_and_only_from_their_own(seeded_tenant, ff, va, api):
    with tenant_context(seeded_tenant.pk):
        mine = EmailTemplateFactory(tenant=seeded_tenant)
    elsewhere = EmailTemplateFactory(tenant=TenantFactory())
    assert api.as_(va).get(ROOT + "uses/").status_code == 200
    body = {"use": "thanks_won", "template": str(mine.pk)}
    assert api.as_(va).post(ROOT + "uses/", body, content_type="application/json").status_code == 403
    assert api.as_(va).post(ROOT, {"name": "x", "subject": "y", "body": "z"},
                            content_type="application/json").status_code == 403
    foreign = api.as_(ff).post(ROOT + "uses/", {"use": "thanks_won", "template": str(elsewhere.pk)},
                               content_type="application/json")
    assert foreign.status_code == 400
    assert api.as_(ff).post(ROOT + "uses/", {"use": "nope", "template": str(mine.pk)},
                            content_type="application/json").status_code == 400
    with tenant_context(seeded_tenant.pk):
        assert use(seeded_tenant, "thanks_won").original == "thanks_won"
