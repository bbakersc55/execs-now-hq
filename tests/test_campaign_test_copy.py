"""A campaign's test copy and preview, and the first-name fallback (owner,
2026-10-20).

1. "Send me a test" carries the campaign's files, as a queued copy does.
2. With no person chosen, the preview and the test show each merge field as
   its bracketed placeholder, and the test opens with one line saying so.
   Real sends are unchanged.
3. "If a first name is missing, use:" is saved with the campaign and used on
   the real send; queueing names who has no first name and waits for a yes.
"""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.crm.models import CampaignRecipient, OutboxAttachment, OutboxMessage
from apps.crm.services import campaigns

from . import registry_config  # noqa: F401
from .factories import CampaignFactory, ContactEmailFactory, ContactFactory
from .test_campaigns import person


@pytest.fixture
def campaign(seeded_tenant, ff):
    return CampaignFactory(tenant=seeded_tenant, created_by=ff.user,
                           subject="Hello {FirstName}",
                           body_html="<p>Hi {FirstName}, a note from {FractionalName} "
                                     "at {Company}.</p>")


def nameless(tenant):
    contact = ContactFactory(tenant=tenant, first_name="", last_name="Okafor")
    ContactEmailFactory(tenant=tenant, contact=contact, address="okafor@x.invalid")
    return contact


@pytest.mark.django_db
def test_the_test_copy_has_the_files_the_placeholders_and_the_line(
        seeded_tenant, ff, api, campaign, dev_outbox, in_tenant_a):
    api.as_(ff).post(f"/api/campaigns/{campaign.pk}/attachments/",
                     {"file": SimpleUploadedFile("flyer.pdf", b"%PDF-1", "application/pdf")})
    sent = api.as_(ff).post(f"/api/campaigns/{campaign.pk}/test-send/")
    assert sent.status_code == 201
    test = OutboxMessage.objects.get(source_type="campaign_test")
    assert test.subject == "[Test] Hello [First name]"
    # Escaped in the HTML, as every merged value is.
    assert "Hi [First name], a note from [Your name] at [Company]." \
        in test.body_html
    assert test.body_html.index(campaigns.TEST_LINE) < test.body_html.index("Hi [First name]")
    assert test.body_text.startswith(campaigns.TEST_LINE)
    assert [a.filename for a in OutboxAttachment.objects.filter(outbox_message=test)] \
        == ["flyer.pdf"]
    assert [a[0] for a in dev_outbox[-1].attachments] == ["flyer.pdf"]
    assert "there" not in test.body_text


@pytest.mark.django_db
def test_the_test_line_goes_inside_a_whole_document(seeded_tenant, ff, campaign,
                                                    in_tenant_a):
    campaign.body_mode, campaign.send_as_is = "html", True
    campaign.body_html = "<html><body><p>Hi {FirstName}</p></body></html>"
    _subject, html, _text = campaigns.rendered_for(campaign, None, actor=ff.user, test=True)
    assert html.index("<body>") < html.index(campaigns.TEST_LINE) < html.index("Hi [First name]")


@pytest.mark.django_db
def test_the_preview_shows_placeholders_with_nobody_chosen_and_merges_for_someone(
        seeded_tenant, ff, api, campaign, in_tenant_a):
    blank = api.as_(ff).post(f"/api/campaigns/{campaign.pk}/preview/", {},
                             content_type="application/json").json()
    assert blank["subject"] == "Hello [First name]"
    assert "Hi [First name]" in blank["html"] and campaigns.TEST_LINE not in blank["html"]
    dana = person(seeded_tenant, "Dana")
    merged = api.as_(ff).post(f"/api/campaigns/{campaign.pk}/preview/",
                              {"contact": str(dana.pk)},
                              content_type="application/json").json()
    assert merged["subject"] == "Hello Dana" and "[First name]" not in merged["html"]


@pytest.mark.django_db
def test_real_sends_are_unchanged_and_use_the_saved_fallback(
        seeded_tenant, ff, api, campaign, in_tenant_a):
    saved = api.as_(ff).patch(f"/api/campaigns/{campaign.pk}/",
                              {"first_name_fallback": "friend"},
                              content_type="application/json")
    assert saved.status_code == 200 and saved.json()["first_name_fallback"] == "friend"
    dana, someone = person(seeded_tenant, "Dana"), nameless(seeded_tenant)
    ids = [str(dana.pk), str(someone.pk)]
    refused = api.as_(ff).post(f"/api/campaigns/{campaign.pk}/queue/", {"ids": ids},
                               content_type="application/json")
    assert refused.status_code == 409
    body = refused.json()
    assert [m["name"] for m in body["missing_first_names"]] == ["Okafor"]
    assert body["fallback"] == "friend" and "1 of them has no first name" in body["detail"]
    assert not OutboxMessage.objects.filter(source_type="campaign").exists()
    queued = api.as_(ff).post(f"/api/campaigns/{campaign.pk}/queue/",
                              {"ids": ids, "confirm_missing_names": True},
                              content_type="application/json")
    assert queued.status_code == 201
    by = {r.contact_id: r.outbox_message for r in CampaignRecipient.objects.all()}
    assert by[dana.pk].subject == "Hello Dana" and by[someone.pk].subject == "Hello friend"
    for message in by.values():
        assert "[" not in message.body_html and campaigns.TEST_LINE not in message.body_html


@pytest.mark.django_db
def test_no_question_when_the_email_does_not_use_the_first_name(
        seeded_tenant, ff, api, campaign, in_tenant_a):
    campaign.subject, campaign.body_html = "News", "<p>Hello from {Company}.</p>"
    campaign.save()
    someone = nameless(seeded_tenant)
    assert api.as_(ff).post(f"/api/campaigns/{campaign.pk}/queue/",
                            {"ids": [str(someone.pk)]},
                            content_type="application/json").status_code == 201


@pytest.mark.django_db
def test_an_empty_fallback_is_there(seeded_tenant, ff, campaign, in_tenant_a):
    campaign.first_name_fallback = "  "
    someone = nameless(seeded_tenant)
    assert campaigns.rendered_for(campaign, someone, actor=ff.user)[0] == "Hello there"
