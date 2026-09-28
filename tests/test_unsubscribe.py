"""Email categories and unsubscribe (owner, 2026-09-28).

Marketing and updates carry an unsubscribe link that leaves that category
only; transactional never carries one. Suppression is per contact per
category, the Outbox refuses a suppressed category and says why, and every
unsubscribe is audited.
"""

from __future__ import annotations

import re

import pytest
from django.utils import timezone

from apps.crm.models import EmailSuppression, OutboxMessage
from apps.crm.services import email_layout, enrollment, outbox, referral, unsubscribe
from apps.tenancy.models import AuditEvent
from apps.work import digests as digest_service
from apps.work.models import Digest

from . import registry_config  # noqa: F401
from .factories import (
    ContactEmailFactory, ContactFactory, DigestFactory, GoalFactory, StakeholderFactory,
)

P = OutboxMessage.Producer
S = OutboxMessage.State
LINK = re.compile(r"/unsubscribe/([^\s\"'<>)]+)")


def _contact(tenant, **kw):
    contact = ContactFactory(tenant=tenant, first_name="Maria", **kw)
    ContactEmailFactory(tenant=tenant, contact=contact, address="maria@partner.invalid")
    return contact


def _draft(tenant, contact, producer=P.REFERRAL_TOUCH, **kw):
    return outbox.create_message(
        tenant=tenant, producer=producer, to_contact=contact,
        to_address="maria@partner.invalid", subject="Checking in", body_text="Hi Maria", **kw)


def _token(html):
    return LINK.search(html).group(1)


# ------------------------------------------------------------ the categories

@pytest.mark.django_db
def test_every_message_is_made_with_its_category(seeded_tenant, ff, in_tenant_a):
    contact = _contact(seeded_tenant)
    assert _draft(seeded_tenant, contact).category == "marketing"
    assert _draft(seeded_tenant, contact, P.STAGE_RULE).category == "marketing"
    # Rows from before the column read through the producer.
    old = _draft(seeded_tenant, contact)
    OutboxMessage.objects.filter(pk=old.pk).update(category="")
    old.refresh_from_db()
    assert unsubscribe.category_of(old) == "marketing"


@pytest.mark.django_db
def test_marketing_carries_the_link_in_both_parts(seeded_tenant, ff, in_tenant_a):
    message = _draft(seeded_tenant, _contact(seeded_tenant))
    html, text = email_layout.for_delivery(message)
    assert "Unsubscribe from marketing emails" in html and LINK.search(html)
    assert LINK.search(text) and "Unsubscribe from marketing emails:" in text
    assert unsubscribe.MARKER not in html


@pytest.mark.django_db
def test_a_digest_carries_an_updates_link_beside_its_cadence_link(
    seeded_tenant, ff, dev_outbox, in_tenant_a
):
    contact = _contact(seeded_tenant)
    digest = DigestFactory(tenant=seeded_tenant, contact=contact, state="approved",
                           body_text="Dispatch is on schedule.")
    digest_service.send(digest, actor=ff.user)

    sent = dev_outbox[0]
    html = sent.alternatives[0][0]
    assert "Unsubscribe from progress updates" in html
    data = unsubscribe.read_token(_token(html))
    assert (data["k"], data["c"]) == ("updates", str(contact.pk))


@pytest.mark.django_db
@pytest.mark.parametrize("producer", sorted(
    p for p, c in unsubscribe.BY_PRODUCER.items() if c in unsubscribe.UNLISTED))
def test_transactional_mail_never_carries_an_unsubscribe_link(
    seeded_tenant, ff, dev_outbox, producer, in_tenant_a
):
    """Sign-in links, PIN resets, pre-call mail, the strategy PDF, staff notices:
    a link someone could switch off is one they could lock themselves out of."""
    contact = _contact(seeded_tenant)
    # Both shapes: a finished document (the branded layout) and plain words.
    for body_html in ("", email_layout.document(seeded_tenant, content_html="<p>x</p>")):
        message = outbox.create_message(
            tenant=seeded_tenant, producer=producer, to_contact=contact,
            to_address="maria@partner.invalid", subject="Your link",
            body_text="Here it is.", body_html=body_html, actor=ff.user,
            force_direct=True)
        assert message.category in ("transactional", "correspondence")
        html, text = email_layout.for_delivery(message)
        assert not LINK.search(html) and not LINK.search(text)
        assert "nsubscribe" not in html and unsubscribe.MARKER not in html
    for sent in dev_outbox:
        assert "nsubscribe" not in sent.body
        assert all("nsubscribe" not in part for part, _ in sent.alternatives)
        assert "List-Unsubscribe" not in sent.extra_headers


# ------------------------------------------------------------------ the token

@pytest.mark.django_db
def test_the_token_is_signed_and_names_one_category(seeded_tenant, in_tenant_a):
    contact = _contact(seeded_tenant)
    token = unsubscribe.token_for(tenant_id=seeded_tenant.pk, category="marketing",
                                  contact_id=contact.pk)
    assert unsubscribe.read_token(token)["c"] == str(contact.pk)
    assert unsubscribe.read_token(token[:-2] + ("AA" if token[-2:] != "AA" else "BB")) is None
    # A transactional "token" is not a thing that can be honoured.
    fake = unsubscribe.token_for(tenant_id=seeded_tenant.pk, category="transactional",
                                 contact_id=contact.pk)
    assert unsubscribe.read_token(fake) is None


# ------------------------------------------------------------ unsubscribing

@pytest.mark.django_db
def test_opening_the_link_changes_nothing_and_posting_leaves_one_category(
    seeded_tenant, referrals, ff, client, in_tenant_a
):
    contact = _contact(seeded_tenant)
    referral.add_type(contact, "referral_partner", actor=ff.user, onboard=False)
    enrollment.enroll(contact, "referral_touches", actor=ff.user)
    waiting = referral.draft_touch_now(contact, actor=ff.user)
    html, _ = email_layout.for_delivery(waiting)
    url = f"/api/unsubscribe/{_token(html)}"

    seen = client.get(url).json()                        # a scanner fetching the link
    assert not EmailSuppression.objects.exists()
    assert [c["unsubscribed"] for c in seen["categories"]] == [False, False]

    left = client.post(url, {}, content_type="application/json").json()

    assert {c["category"]: c["unsubscribed"] for c in left["categories"]} == \
        {"marketing": True, "updates": False}
    row = EmailSuppression.objects.get()
    assert (row.contact_id, row.category) == (contact.pk, "marketing")
    assert not enrollment.is_enrolled(contact, "referral_touches")
    waiting.refresh_from_db()
    assert waiting.state == S.SUPPRESSED
    assert AuditEvent.all_objects.filter(verb="email.unsubscribed").count() == 1


@pytest.mark.django_db
def test_the_page_offers_the_other_category_and_an_undo(seeded_tenant, ff, client,
                                                        in_tenant_a):
    contact = _contact(seeded_tenant)
    goal = GoalFactory(tenant=seeded_tenant)
    stake = StakeholderFactory(tenant=seeded_tenant, contact=contact, goal=goal, task=None)
    token = unsubscribe.token_for(tenant_id=seeded_tenant.pk, category="marketing",
                                  contact_id=contact.pk)
    url = f"/api/unsubscribe/{token}"
    client.post(url, {}, content_type="application/json")

    both = client.post(url, {"category": "updates"}, content_type="application/json").json()
    assert all(c["unsubscribed"] for c in both["categories"])
    stake.refresh_from_db()
    assert stake.is_muted is True

    undone = client.post(url, {"category": "marketing", "action": "resubscribe"},
                         content_type="application/json").json()
    assert {c["category"]: c["unsubscribed"] for c in undone["categories"]} == \
        {"marketing": False, "updates": True}
    assert AuditEvent.all_objects.filter(verb="email.resubscribed").exists()


@pytest.mark.django_db
def test_a_bad_token_is_a_404_that_says_what_to_do(client):
    response = client.get("/api/unsubscribe/not-a-token")
    assert response.status_code == 404 and "reply to the email" in response.json()["detail"]


# --------------------------------------------------------- the Outbox refuses

@pytest.mark.django_db
def test_the_outbox_refuses_a_suppressed_category_and_says_why(
    seeded_tenant, ff, api, dev_outbox, in_tenant_a
):
    contact = _contact(seeded_tenant)
    EmailSuppression.objects.create(tenant=seeded_tenant, contact=contact,
                                    category="marketing")
    message = _draft(seeded_tenant, contact, P.STAGE_RULE)

    response = api.as_(ff).post(f"/api/outbox/{message.pk}/approve/")

    assert response.status_code == 403
    assert "unsubscribed from marketing emails" in response.json()["detail"]
    message.refresh_from_db()
    assert message.state == S.SUPPRESSED and message.warning.startswith("Not sent")
    assert dev_outbox == []


@pytest.mark.django_db
def test_leaving_marketing_does_not_stop_updates(seeded_tenant, ff, dev_outbox, in_tenant_a):
    contact = _contact(seeded_tenant)
    EmailSuppression.objects.create(tenant=seeded_tenant, contact=contact,
                                    category="marketing")
    digest = DigestFactory(tenant=seeded_tenant, contact=contact, state="approved")
    digest_service.send(digest, actor=ff.user)
    digest.refresh_from_db()
    assert digest.state == Digest.State.SENT and len(dev_outbox) == 1


@pytest.mark.django_db
def test_a_digest_to_someone_who_left_updates_is_skipped_not_sent(
    seeded_tenant, ff, dev_outbox, in_tenant_a
):
    contact = _contact(seeded_tenant)
    EmailSuppression.objects.create(tenant=seeded_tenant, contact=contact, category="updates")
    digest = DigestFactory(tenant=seeded_tenant, contact=contact, state="approved")
    message = digest_service.send(digest, actor=ff.user)
    digest.refresh_from_db()
    assert digest.state == Digest.State.SKIPPED
    assert message.state == S.SUPPRESSED and dev_outbox == []


@pytest.mark.django_db
def test_a_staff_notice_is_suppressed_by_address(seeded_tenant, ff, dev_outbox, in_tenant_a):
    """Client-activity notices go to staff, who are not contacts."""
    notice = outbox.create_message(
        tenant=seeded_tenant, producer=P.CLIENT_ACTIVITY, to_address="Cf@Practice.invalid",
        subject="Activity", body_text="Dana commented.", force_direct=True)
    token = _token(email_layout.for_delivery(notice)[0])
    assert unsubscribe.read_token(token)["a"] == "cf@practice.invalid"
    unsubscribe.unsubscribe(unsubscribe.read_token(token))

    again = outbox.create_message(
        tenant=seeded_tenant, producer=P.CLIENT_ACTIVITY, to_address="cf@practice.invalid",
        subject="Activity", body_text="Dana commented again.", force_direct=True)
    assert again.state == S.SUPPRESSED and len(dev_outbox) == 1


@pytest.mark.django_db
def test_the_contact_page_shows_suppressions(seeded_tenant, ff, va, api, in_tenant_a):
    contact = _contact(seeded_tenant)
    EmailSuppression.objects.create(tenant=seeded_tenant, contact=contact,
                                    category="marketing")
    rows = api.as_(va).get(f"/api/contacts/{contact.pk}/suppressions/").json()
    assert [r["label"] for r in rows] == ["marketing emails"]


# ------------------------------------- 2026-09-28 adjustments: correspondence

@pytest.mark.django_db
def test_one_person_writing_to_one_person_is_correspondence(seeded_tenant, ff, api,
                                                            dev_outbox, in_tenant_a):
    """Never suppressed by a marketing unsubscribe, and no link on it."""
    contact = _contact(seeded_tenant)
    EmailSuppression.objects.create(tenant=seeded_tenant, contact=contact,
                                    category="marketing")
    drafted = api.as_(ff).post("/api/contacts/draft-emails/", {
        "ids": [str(contact.pk)], "subject": "Following up", "body_text": "Hi Maria"},
        content_type="application/json").json()
    message = OutboxMessage.objects.get(pk=drafted["drafted"][0])
    assert message.category == "correspondence"

    assert api.as_(ff).post(f"/api/outbox/{message.pk}/approve/").status_code == 200
    assert len(dev_outbox) == 1
    assert "nsubscribe" not in dev_outbox[0].body


@pytest.mark.django_db
def test_the_same_email_drafted_to_several_is_marketing(seeded_tenant, ff, api, in_tenant_a):
    first, second = _contact(seeded_tenant), ContactFactory(tenant=seeded_tenant)
    ContactEmailFactory(tenant=seeded_tenant, contact=second, address="b@x.invalid")
    drafted = api.as_(ff).post("/api/contacts/draft-emails/", {
        "ids": [str(first.pk), str(second.pk)], "subject": "News", "body_text": "Hi"},
        content_type="application/json").json()
    assert set(OutboxMessage.objects.filter(pk__in=drafted["drafted"])
               .values_list("category", flat=True)) == {"marketing"}


# -------------------------------- 2026-09-28 adjustments: one-click headers

@pytest.mark.django_db
@pytest.mark.parametrize("producer,category", [(P.REFERRAL_TOUCH, "marketing"),
                                               (P.CLIENT_ACTIVITY, "updates")])
def test_marketing_and_updates_carry_the_one_click_headers(
    seeded_tenant, ff, dev_outbox, producer, category, in_tenant_a
):
    contact = _contact(seeded_tenant)
    message = _draft(seeded_tenant, contact, producer, force_direct=True)
    headers = dev_outbox[0].extra_headers
    assert headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    url = headers["List-Unsubscribe"]
    assert url.startswith("<") and url.endswith("/one-click>")
    token = url[1:-1].split("/api/unsubscribe/")[1].rsplit("/one-click", 1)[0]
    assert unsubscribe.read_token(token)["k"] == category
    # The same token the body's link carries.
    assert token in email_layout.for_delivery(message)[0]


@pytest.mark.django_db
def test_the_gmail_mime_carries_them_too(seeded_tenant):
    from apps.crm.services import transport

    mime = transport.build_mime(
        to_address="a@x.invalid", from_address="b@x.invalid", subject="s", body_text="t",
        message_id="<m@x>", thread_token="tok",
        headers={"List-Unsubscribe": "<https://x/api/unsubscribe/t/one-click>",
                 "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"})
    assert mime["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert mime["List-Unsubscribe"].endswith("/one-click>")


@pytest.mark.django_db
def test_one_click_unsubscribes_on_the_mail_clients_post(seeded_tenant, ff, client,
                                                         in_tenant_a):
    contact = _contact(seeded_tenant)
    message = _draft(seeded_tenant, contact)
    url = unsubscribe.headers_for(message)["List-Unsubscribe"][1:-1]
    path = "/api/" + url.split("/api/", 1)[1]

    assert client.get(path).status_code == 405          # a GET does nothing
    response = client.post(path, "List-Unsubscribe=One-Click",
                           content_type="application/x-www-form-urlencoded")

    assert response.status_code == 200
    row = EmailSuppression.objects.get()
    assert (row.contact_id, row.category, row.source) == (contact.pk, "marketing", "one_click")
    assert AuditEvent.all_objects.get(verb="email.unsubscribed").payload["source"] == "one_click"


@pytest.mark.django_db
def test_onboarding_is_still_drafted_automatically_for_approval(seeded_tenant, referrals,
                                                                ff, in_tenant_a):
    """Owner, 2026-09-28: one email, still approved by hand."""
    contact = _contact(seeded_tenant)
    referral.add_type(contact, "referral_partner", actor=ff.user)
    onboarding = OutboxMessage.objects.get(producer=P.REFERRAL_ONBOARDING)
    assert (onboarding.state, onboarding.category) == (S.PENDING_APPROVAL, "marketing")
