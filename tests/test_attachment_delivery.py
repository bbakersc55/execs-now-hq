"""Attachment bytes, end to end (Check 5 re-test).

The delivered flyer arrived with the right name and **zero bytes**. Two separate
failures stacked:

1. Nothing ever wrote a `stored_file`'s content anywhere. The row recorded
   404,710 bytes; the bucket did not exist and no file had ever been written.
2. `_deliver` handed the transport a literal `b""` for every attachment.

Either alone produces an empty file. Together they made the Outbox, the API and
Gmail all agree there was an attachment, while the document opened blank.

These tests assert the thing none of the existing ones did: that what leaves the
app is the same number of bytes that went in.
"""

from __future__ import annotations

import base64
from email import message_from_bytes
from unittest import mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.crm.models import OutboxMessage
from apps.crm.services import outbox, referral, transport
from apps.tenancy import storage
from apps.tenancy.context import tenant_context

from . import registry_config  # noqa: F401
from .factories import (
    ContactEmailFactory, ContactFactory, OutboxAttachmentFactory,
    OutboxMessageFactory, StoredFileFactory,
)

S = OutboxMessage.State
P = OutboxMessage.Producer
PDF = b"%PDF-1.4" + b"A" * 404702  # the flyer's real size


def _contact(tenant, **kw):
    contact = ContactFactory(tenant=tenant, **kw)
    ContactEmailFactory(tenant=tenant, contact=contact)
    return contact


# ------------------------------------------------------- storage holds bytes

@pytest.mark.django_db
def test_saving_a_file_writes_its_content_and_measures_it(seeded_tenant):
    stored = storage.save(
        tenant=seeded_tenant, content=PDF, object_key="flyers/x/Flyer.pdf",
        purpose="marketing_flyer", content_type="application/pdf",
    )
    assert stored.byte_size == len(PDF) == 404710
    assert storage.read(stored) == PDF


@pytest.mark.django_db
def test_byte_size_is_measured_not_claimed(seeded_tenant):
    """A truncated write that still reported the full size is exactly the shape
    of the bug this replaces."""
    stored = storage.save(
        tenant=seeded_tenant, content=b"short", object_key="k", purpose="p",
    )
    assert stored.byte_size == 5


@pytest.mark.django_db
def test_reading_a_file_with_no_content_raises_rather_than_returning_empty(
    seeded_tenant,
):
    """The old behaviour returned nothing and sent a 0-byte attachment. An empty
    file is indistinguishable from a working one until the recipient opens it."""
    from apps.tenancy.models import StoredFile

    orphan = StoredFile.all_objects.create(
        tenant=seeded_tenant, bucket="b", object_key="never/written.pdf",
        byte_size=404710, purpose="marketing_flyer",
    )
    with pytest.raises(storage.MissingContent) as exc:
        storage.read(orphan)
    assert "Re-upload" in str(exc.value)


# ------------------------------------ the bytes reach the MIME part, intact

@pytest.mark.django_db
def test_a_delivered_attachment_is_the_same_size_as_the_stored_file(
    seeded_tenant, ff, dev_outbox
):
    """THE regression test: what leaves equals what went in."""
    stored = StoredFileFactory(
        tenant=seeded_tenant, purpose="marketing_flyer",
        content_type="application/pdf", content=PDF,
    )
    message = OutboxMessageFactory(
        tenant=seeded_tenant, state=S.PENDING_APPROVAL,
        to_address="partner@example.invalid",
    )
    OutboxAttachmentFactory(
        tenant=seeded_tenant, outbox_message=message, stored_file=stored,
        filename="Executives-Now.pdf",
    )

    with tenant_context(seeded_tenant.pk):
        outbox.approve(message, actor=ff.user, role="FF")

    assert len(dev_outbox) == 1
    delivered = dev_outbox[0].attachments
    assert len(delivered) == 1
    filename, content, content_type = delivered[0]
    assert filename == "Executives-Now.pdf"
    assert len(content) == stored.byte_size == 404710
    assert content == PDF
    assert content_type == "application/pdf"


@pytest.mark.django_db
def test_the_gmail_transport_base64_encodes_the_real_bytes(seeded_tenant):
    """Gmail takes one base64 blob for the whole MIME message, so a lost
    attachment would be invisible at the API boundary — decode it back."""
    from apps.crm.models import EmailThread

    thread = EmailThread.all_objects.create(
        tenant=seeded_tenant, thread_token="tok-attachment-test",
    )
    mime = transport.build_mime(
        to_address="partner@example.invalid",
        from_address="info@getexecutivesnow.com",
        subject="Good to meet you", body_text="Body",
        message_id="<x@y>", thread_token=thread.thread_token,
        attachments=[("Executives-Now.pdf", PDF, "application/pdf")],
    )
    raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()

    # Exactly what Gmail receives, decoded back to a MIME tree.
    parsed = message_from_bytes(base64.urlsafe_b64decode(raw))
    parts = [
        part for part in parsed.walk()
        if part.get_filename() == "Executives-Now.pdf"
    ]
    assert len(parts) == 1
    assert parts[0].get_payload(decode=True) == PDF
    assert len(parts[0].get_payload(decode=True)) == 404710


@pytest.mark.django_db
def test_a_send_fails_loudly_when_the_content_is_missing(
    seeded_tenant, ff, dev_outbox
):
    """The exact state the owner's database was in. Sending the message without
    the file it claims to attach is worse than not sending it."""
    from apps.tenancy.models import StoredFile

    orphan = StoredFile.all_objects.create(
        tenant=seeded_tenant, bucket="b", object_key="never/written.pdf",
        byte_size=404710, purpose="marketing_flyer", content_type="application/pdf",
    )
    message = OutboxMessageFactory(tenant=seeded_tenant, state=S.PENDING_APPROVAL)
    OutboxAttachmentFactory(
        tenant=seeded_tenant, outbox_message=message, stored_file=orphan,
        filename="Executives-Now.pdf",
    )

    with tenant_context(seeded_tenant.pk), pytest.raises(
        transport.TransportUnavailable
    ) as exc:
        outbox.approve(message, actor=ff.user, role="FF")

    assert "content is not in storage" in str(exc.value)
    assert dev_outbox == [], "An empty attachment was delivered."
    message.refresh_from_db()
    assert message.state != S.SENT


# ----------------------------- both upload paths produce real, sendable bytes

@pytest.mark.django_db
def test_an_uploaded_flyer_is_delivered_whole(seeded_tenant, referrals, ff, api, dev_outbox):
    """The flyer path: upload in Referral settings -> onboarding draft -> send."""
    upload = SimpleUploadedFile("Flyer.pdf", PDF, content_type="application/pdf")
    assert api.as_(ff).post("/api/referral-settings/flyer/", {"flyer": upload}).status_code == 200

    seeded_tenant.refresh_from_db()
    assert seeded_tenant.marketing_flyer.byte_size == 404710

    with tenant_context(seeded_tenant.pk):
        contact = _contact(seeded_tenant)
        referral.add_type(contact, "referral_partner", actor=ff.user)
        message = OutboxMessage.objects.get(producer=P.REFERRAL_ONBOARDING)
        outbox.approve(message, actor=ff.user, role="FF")

    assert len(dev_outbox[0].attachments) == 1
    assert len(dev_outbox[0].attachments[0][1]) == 404710


@pytest.mark.django_db
def test_an_attachment_added_by_hand_is_delivered_whole(
    seeded_tenant, ff, api, dev_outbox
):
    """The Review & edit path had the identical defect — same metadata-only
    write, same `b""` read."""
    draft = OutboxMessageFactory(tenant=seeded_tenant, state=S.PENDING_APPROVAL)
    upload = SimpleUploadedFile("brief.pdf", PDF, content_type="application/pdf")

    added = api.as_(ff).post(f"/api/outbox/{draft.pk}/attachments/", {"file": upload})
    assert added.status_code == 201
    assert added.json()["attachments"][0]["byte_size"] == 404710

    with tenant_context(seeded_tenant.pk):
        outbox.approve(draft, actor=ff.user, role="FF")

    assert len(dev_outbox[0].attachments[0][1]) == 404710
    assert dev_outbox[0].attachments[0][1] == PDF


@pytest.mark.django_db
def test_a_real_gmail_send_carries_the_bytes(seeded_tenant, ff, settings):
    """Through the Gmail transport itself, with Google's HTTP stubbed: assert
    the payload Google would receive contains the whole file."""
    settings.DEV_REAL_SEND_ALLOWLIST = ["partner@example.invalid"]
    from django.utils import timezone

    from .factories import GmailConnectionFactory

    GmailConnectionFactory(
        tenant=seeded_tenant, user=ff.user, email_address="bryan@getexecutivesnow.com",
        send_as_address=seeded_tenant.from_address,
        send_as_verified_at=timezone.now(),
    )
    stored = StoredFileFactory(tenant=seeded_tenant, purpose="marketing_flyer",
                               content_type="application/pdf", content=PDF)
    message = OutboxMessageFactory(
        tenant=seeded_tenant, state=S.PENDING_APPROVAL,
        to_address="partner@example.invalid",
    )
    OutboxAttachmentFactory(
        tenant=seeded_tenant, outbox_message=message, stored_file=stored,
        filename="Executives-Now.pdf",
    )

    sent_payloads = []

    def fake_post(url, **kwargs):
        stub = mock.Mock()
        stub.ok = True
        stub.status_code = 200
        if "messages/send" in url:
            sent_payloads.append(kwargs["json"])
            stub.json.return_value = {"id": "m1", "threadId": "t1"}
        else:
            stub.json.return_value = {"access_token": "at"}
        return stub

    with mock.patch("apps.crm.services.transport.requests.post", side_effect=fake_post), \
            mock.patch("apps.crm.services.secrets.read_secret", return_value="refresh"), \
            tenant_context(seeded_tenant.pk):
        outbox.approve(message, actor=ff.user, role="FF")

    assert len(sent_payloads) == 1
    parsed = message_from_bytes(base64.urlsafe_b64decode(sent_payloads[0]["raw"]))
    attachment = next(
        part for part in parsed.walk()
        if part.get_filename() == "Executives-Now.pdf"
    )
    assert len(attachment.get_payload(decode=True)) == 404710
