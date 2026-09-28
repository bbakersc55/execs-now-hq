"""Campaigns (owner, 2026-09-28): compose once, merge per person, and "Enrol
and queue" — one pending_approval Outbox row per recipient, category
marketing. Nothing sends without approval."""

from __future__ import annotations

import pytest

from apps.crm.models import Campaign, CampaignRecipient, EmailSuppression, OutboxMessage
from apps.crm.services import campaigns, email_layout, enrollment
from apps.tenancy.models import AuditEvent

from . import registry_config  # noqa: F401
from .factories import (
    CampaignFactory, CompanyFactory, ContactEmailFactory, ContactFactory,
)

S = OutboxMessage.State


def person(tenant, first, *, email=True, company=None, tags=()):
    contact = ContactFactory(tenant=tenant, first_name=first, last_name="Reyes",
                             company=company, tags=list(tags))
    if email:
        ContactEmailFactory(tenant=tenant, contact=contact,
                            address=f"{first.lower()}@x.invalid")
    return contact


@pytest.fixture
def campaign(seeded_tenant, ff):
    return CampaignFactory(tenant=seeded_tenant, created_by=ff.user)


@pytest.mark.django_db
def test_enrol_and_queue_makes_one_pending_marketing_row_per_person(
    seeded_tenant, ff, api, campaign, dev_outbox, in_tenant_a
):
    acme = CompanyFactory(tenant=seeded_tenant, name="Acme")
    dana, priya = person(seeded_tenant, "Dana", company=acme), person(seeded_tenant, "Priya")

    response = api.as_(ff).post(f"/api/campaigns/{campaign.pk}/queue/",
                                {"ids": [str(dana.pk), str(priya.pk)]},
                                content_type="application/json")

    assert response.status_code == 201, response.json()
    rows = OutboxMessage.objects.filter(source_type="campaign").order_by("to_address")
    assert [r.to_address for r in rows] == ["dana@x.invalid", "priya@x.invalid"]
    assert {(r.state, r.category, r.producer) for r in rows} == {
        (S.PENDING_APPROVAL, "marketing", "campaign")}
    # Merged per person, and escaped in the HTML.
    assert rows[0].subject == "Hello Dana"
    assert "a note from" in rows[0].body_html and "at Acme." in rows[0].body_html
    assert "at ." in rows[1].body_text                    # no company: left empty
    assert CampaignRecipient.objects.filter(campaign=campaign).count() == 2
    assert dev_outbox == [], "Queueing a campaign sent mail."
    assert response.json()["campaign"]["stats"]["queued"] == 2


@pytest.mark.django_db
def test_queue_skips_and_names_who_cannot_be_sent_to(seeded_tenant, ff, api, campaign,
                                                     in_tenant_a):
    ok = person(seeded_tenant, "Dana")
    no_email = person(seeded_tenant, "Nomail", email=False)
    left = person(seeded_tenant, "Left")
    EmailSuppression.objects.create(tenant=seeded_tenant, contact=left, category="marketing")
    client = api.as_(ff)
    ids = [str(c.pk) for c in (ok, no_email, left)]

    first = client.post(f"/api/campaigns/{campaign.pk}/queue/", {"ids": ids},
                        content_type="application/json").json()
    assert first["queued_count"] == 1
    assert {s["detail"] for s in first["skipped"]} == {
        "no email address", "unsubscribed from marketing emails"}

    again = client.post(f"/api/campaigns/{campaign.pk}/queue/", {"ids": [str(ok.pk)]},
                        content_type="application/json")
    assert again.status_code == 400
    assert again.json()["skipped"][0]["detail"] == "already in this campaign"


@pytest.mark.django_db
def test_the_branded_layout_wraps_it_and_the_link_is_on_it(seeded_tenant, ff, campaign,
                                                          in_tenant_a):
    dana = person(seeded_tenant, "Dana")
    html, text = campaigns.preview(campaign, dana, actor=ff.user)
    assert "data-enhq-email" in html and campaigns.AS_IS not in html   # the branded layout
    assert "Unsubscribe from marketing emails" in html and "/unsubscribe/" in text


@pytest.mark.django_db
def test_send_as_is_goes_out_as_written_with_only_the_link_added(
    seeded_tenant, ff, campaign, in_tenant_a
):
    campaign.body_mode, campaign.send_as_is = "html", True
    campaign.body_html = ("<html><body><table><tr><td>Hi {FirstName}</td></tr></table>"
                          "</body></html>")
    dana = person(seeded_tenant, "Dana")
    html, _ = campaigns.preview(campaign, dana, actor=ff.user)
    assert "<td>Hi Dana</td>" in html
    assert "#0A3A65" not in html and "data-enhq-logo" not in html   # no layout around it
    assert "Unsubscribe from marketing emails" in html               # but still the link


@pytest.mark.django_db
def test_recipients_by_filter(seeded_tenant, referrals, ff, api, campaign, in_tenant_a):
    from apps.crm.services import referral

    tagged = person(seeded_tenant, "Tagged", tags=["newsletter"])
    partner = person(seeded_tenant, "Partner")
    referral.add_type(partner, "referral_partner", actor=ff.user, onboard=False)
    enrollment.enroll(partner, "referral_touches", actor=ff.user)
    client = api.as_(ff)
    base = f"/api/campaigns/{campaign.pk}/candidates/"

    assert [r["name"] for r in client.get(base + "?tag=newsletter").json()] == ["Tagged Reyes"]
    assert [r["name"] for r in client.get(base + "?type=referral_partner").json()] \
        == ["Partner Reyes"]
    assert [r["name"] for r in client.get(base + "?enrolled=referral_touches").json()] \
        == ["Partner Reyes"]
    assert "Partner Reyes" not in [r["name"] for r in
                                   client.get(base + "?enrolled=none").json()]


@pytest.mark.django_db
def test_test_send_goes_to_the_composer_now_marked_as_a_test(
    seeded_tenant, ff, api, campaign, dev_outbox, in_tenant_a
):
    response = api.as_(ff).post(f"/api/campaigns/{campaign.pk}/test-send/")
    assert response.status_code == 201
    assert response.json()["to"] == ff.user.email
    assert dev_outbox[0].subject.startswith("[Test] Hello")


@pytest.mark.django_db
def test_unsubscribing_from_marketing_ends_the_campaign_enrolment(
    seeded_tenant, ff, campaign, in_tenant_a
):
    from apps.crm.services import unsubscribe

    dana = person(seeded_tenant, "Dana")
    campaigns.queue(campaign, [dana], actor=ff.user)
    unsubscribe.unsubscribe({"t": str(seeded_tenant.pk), "k": "marketing",
                             "c": str(dana.pk), "a": ""})

    row = CampaignRecipient.objects.get()
    assert row.ended_reason == "unsubscribed"
    assert row.outbox_message.state == S.SUPPRESSED
    assert campaigns.stats(campaign)["unsubscribed"] == 1


@pytest.mark.django_db
def test_a_campaign_shows_on_the_enrolled_in_list_and_comes_off_it(
    seeded_tenant, ff, api, campaign, in_tenant_a
):
    dana = person(seeded_tenant, "Dana")
    campaigns.queue(campaign, [dana], actor=ff.user)
    client = api.as_(ff)
    [row] = client.get(f"/api/contacts/{dana.pk}/enrollments/").json()
    assert row["kind"] == "campaign" and "Autumn note" in row["label"]

    client.post(f"/api/contacts/{dana.pk}/unenroll/", {"campaign_recipient": row["id"]})
    assert client.get(f"/api/contacts/{dana.pk}/enrollments/").json() == []
    assert CampaignRecipient.objects.get().outbox_message.state == S.REJECTED


@pytest.mark.django_db
def test_archiving_keeps_the_rows(seeded_tenant, ff, api, campaign, in_tenant_a):
    assert api.as_(ff).delete(f"/api/campaigns/{campaign.pk}/").status_code == 204
    assert Campaign.objects.get().archived_at is not None
    assert api.as_(ff).get("/api/campaigns/").json() == []
    assert AuditEvent.all_objects.filter(verb="campaign.archived").exists()


@pytest.mark.django_db
def test_a_client_cannot_reach_campaigns(seeded_tenant, fcc, api, campaign):
    assert api.as_(fcc).get("/api/campaigns/").status_code in (403, 404)
