"""Email presentation — one branded layout, a personal one, and a text part for
every send (apps/crm/services/email_layout.py).

What these hold down, in order of consequence:

1. A one-time link is never stored: the Outbox row's HTML and text hold neither
   the link nor the button, while the delivered copy holds both.
2. Every send carries text/plain AND text/html, built from the same content.
3. Inline styles only — no <style> block, which Gmail strips.
4. The digest reads as the flagship: narrative first, grouped by task, chips for
   status, the fractional's sentence set apart from the status line.
5. Branding comes from the tenant row.
6. Previews render exactly what sends, only on localhost, only for staff.
7. The samples command never touches a real engagement.
"""

from __future__ import annotations

import io
import json
from datetime import timedelta
from email import message_from_bytes

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from apps.crm.models import OutboxMessage, Task
from apps.crm.services import email_layout, outbox, transport
from apps.tenancy.models import AuditEvent
from apps.work import digests as digest_service
from apps.work.models import Cadence, Digest, DigestItem, Stakeholder, StakeholderToken, TaskUpdate
from apps.work.services import apply_task_changes, create_task

from . import registry_config  # noqa: F401
from .factories import (
    ClientCompanyFactory, ContactEmailFactory, ContactFactory, MembershipFactory, ProjectFactory,
    UserFactory,
)

S = Task.Status
K = TaskUpdate.Kind


@pytest.fixture(autouse=True)
def beta_branding(seeded_tenant):
    """Executives Now's name and palette live on its tenant row, like any other
    practice's — the code's defaults are neutral (white-label). These tests
    assert the Beta look, so they set the Beta row."""
    seeded_tenant.name = "Executives Now"
    seeded_tenant.email_display_name = "Executives Now"
    seeded_tenant.email_header_color = "#0A3A65"
    seeded_tenant.email_accent_color = "#F58220"
    seeded_tenant.save()
    return seeded_tenant


def html_part(email):
    """The text/html alternative of a Django EmailMultiAlternatives."""
    return next(content for content, mime in email.alternatives if mime == "text/html")


@pytest.fixture
def company(seeded_tenant):
    return ClientCompanyFactory(tenant=seeded_tenant, name="Northwind Foods",
                                digest_ai_prose=False, seat_count=3)


@pytest.fixture
def recipient(seeded_tenant, company):
    contact = ContactFactory(tenant=seeded_tenant, first_name="Dana", last_name="Okafor",
                             company=company)
    ContactEmailFactory(tenant=seeded_tenant, contact=contact,
                        address="dana@northwind.invalid", is_primary=True)
    return contact


@pytest.fixture
def project(seeded_tenant, company):
    return ProjectFactory(tenant=seeded_tenant, title="Order-to-cash", client_company=company)


def weekly_digest(tenant, ff, company, recipient, project, moves):
    """A real generated weekly digest for `recipient`: `moves` is
    [(task title, status, client line)]."""
    tasks = {}
    for title, _status, _line in moves:
        if title not in tasks:
            tasks[title] = create_task(tenant=tenant, actor=ff.user, role="FF", title=title,
                                       client_company=company, project=project)
    Stakeholder.all_objects.create(tenant=tenant, contact=recipient, project=project)
    for title, status, line in moves:
        task = tasks[title]
        apply_task_changes(task, actor=ff.user, role="FF", changes={"status": status},
                           client_facing_line=line)
        task.refresh_from_db()
    window = digest_service.next_window(tenant, Cadence.WEEKLY, after=timezone.now())
    return digest_service.generate_scheduled(tenant, cadence=Cadence.WEEKLY,
                                             now=window - timedelta(hours=1))[0]


# ------------------------------------------------------------------ the layout

@pytest.mark.django_db
def test_the_base_layout_is_branded_from_the_tenant_row_with_inline_styles_only(seeded_tenant):
    html = email_layout.document(seeded_tenant, content_html="<p>Hello</p>", subject="Hi")
    assert 'data-enhq-email="base"' in html
    assert "background-color:#0A3A65" in html, "Executives Now's header colour by default."
    assert "background-color:#F58220" in html, "The accent rule beneath the header."
    assert ">Executives Now<" in html
    assert "max-width:600px" in html and "font-size:16px" in html
    assert "<style" not in html.lower() and "<link" not in html.lower(), (
        "Gmail strips <style> blocks; everything must be inline.")

    seeded_tenant.email_display_name = "Acme Fractional"
    seeded_tenant.email_header_color = "#123456"
    seeded_tenant.email_accent_color = "#ABCDEF"
    seeded_tenant.save()
    rebranded = email_layout.document(seeded_tenant, content_html="<p>Hello</p>")
    assert ">Acme Fractional<" in rebranded
    assert "background-color:#123456" in rebranded and "background-color:#ABCDEF" in rebranded
    assert "#0A3A65" not in rebranded

    # A malformed colour never reaches the markup. (Set on the row object, not
    # saved: the column is 7 characters and the database would refuse it anyway.)
    seeded_tenant.email_header_color = "red;display:none"
    assert "display:none\"" not in email_layout.document(seeded_tenant, content_html="x")
    # Falls back to the neutral default, never to the product owner's blue.
    assert f"background-color:{email_layout.DEFAULT_HEADER_COLOR}" in \
        email_layout.document(seeded_tenant, content_html="x")


@pytest.mark.django_db
def test_the_personal_layout_has_no_header_block_and_accent_links(seeded_tenant):
    html = email_layout.document(seeded_tenant, personal=True, content_html=email_layout.text_to_html(
        "Hi Maria,\n\nBook here: https://example.com/book?a=1&b=2\n\nBryan", accent="#F58220"))
    assert 'data-enhq-email="personal"' in html
    assert "#0A3A65" not in html, "No corporate header on mail from a person."
    assert 'href="https://example.com/book?a=1&amp;b=2" style="color:#F58220' in html
    assert "<style" not in html.lower()


def test_plain_text_is_escaped_never_trusted_as_html():
    html = email_layout.text_to_html("<script>alert(1)</script>\nline two", accent="#F58220")
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "<br>" in html


# --------------------------------------------------- the MIME: both parts, always

def test_the_mime_carries_text_then_html_and_keeps_attachments():
    mime = transport.build_mime(
        to_address="a@example.invalid", from_address="info@example.invalid", subject="S",
        body_text="Plain words", body_html="<p>Rich words</p>", message_id="<x@y>",
        thread_token="tok", attachments=[("f.pdf", b"%PDF-1", "application/pdf")])
    parsed = message_from_bytes(mime.as_bytes())
    types = [part.get_content_type() for part in parsed.walk()]
    assert types.index("text/plain") < types.index("text/html")
    assert "multipart/alternative" in types
    assert [p.get_filename() for p in parsed.walk() if p.get_filename()] == ["f.pdf"]


# ------------------------------------------------------------- the flagship

@pytest.mark.django_db
def test_the_digest_leads_with_the_narrative_groups_by_task_and_chips_each_status(
    seeded_tenant, ff, company, recipient, project, in_tenant_a
):
    digest = weekly_digest(seeded_tenant, ff, company, recipient, project, [
        ("Map the invoice process", S.DONE, "Invoices now clear in four days."),
        ("Automate matching", S.IN_PROGRESS, ""),
        ("AP system access", S.WAITING_ON_CLIENT, "We need an AP login."),
        ("Vendor clean-up", S.BLOCKED, ""),
    ])
    narrative = "A good week: the invoice process is mapped."
    digest.body_text, digest.body_html = digest_service.render(
        digest, digest_service.owed_to(recipient.pk, tenant=seeded_tenant,
                                       cadence=Cadence.WEEKLY) or
        [(di.task_update, di.stakeholder) for di in digest.items.all()],
        narrative=narrative)
    html, text = digest_service.email_for(digest, footer_url="https://app/updates/tok")

    assert html.index(narrative) < html.index("Map the invoice process"), "Narrative first."
    assert "font-weight:700;color:#1A1A1A;\">Map the invoice process" in html, "Bold task subhead."
    assert "Order-to-cash" in html, "The project it sits under."
    for label, colour in (("Done", "#1E7B34"), ("In progress", "#1F5FA8"),
                          ("Waiting on client", "#A04A00"), ("Blocked", "#B42318")):
        assert f"color:{colour};" in html and f">{label}</span>" in html, label
    # The fractional's sentence is set apart from the status line.
    assert "border-left:3px solid #F58220;font-size:16px;line-height:1.6;color:#333333;\">" \
           "Invoices now clear in four days." in html
    assert "Moved from Not started to Done" in html
    assert html.count(">Completed<") == 0, "Moved-to-Done already says it."
    # The footer control, small and unobtrusive.
    assert 'href="https://app/updates/tok"' in html and "font-size:13px" in html
    # The text part: the same content.
    assert text.startswith(narrative)
    assert "Map the invoice process (Order-to-cash)" in text
    assert "[Done] Moved from Not started to Done" in text
    assert "“Invoices now clear in four days.”" in text
    assert text.rstrip().endswith("https://app/updates/tok")
    assert "<style" not in html.lower()


@pytest.mark.django_db
def test_a_sent_digest_carries_both_parts_and_the_cadence_link_in_each(
    seeded_tenant, ff, company, recipient, project, dev_outbox, in_tenant_a
):
    digest = weekly_digest(seeded_tenant, ff, company, recipient, project,
                           [("Map the invoice process", S.IN_PROGRESS, "Mapping has begun.")])
    digest_service.approve(digest, actor=ff.user, role="FF")
    digest_service.send_due(seeded_tenant, now=digest.send_window_at)

    assert len(dev_outbox) == 1
    email = dev_outbox[0]
    html = html_part(email)
    assert "Mapping has begun." in email.body and "Mapping has begun." in html
    assert "/updates/" in email.body and "/updates/" in html
    token = email.body.split("/updates/")[1].split()[0].strip()
    assert f"/updates/{token}" in html, "One link, issued once, in both parts."
    row = OutboxMessage.all_objects.get(producer="digest")
    assert email_layout.is_document(row.body_html), "The Outbox logs the email as sent."


@pytest.mark.django_db
def test_edited_digest_wording_is_what_sends(seeded_tenant, ff, company, recipient, project,
                                            dev_outbox, in_tenant_a):
    digest = weekly_digest(seeded_tenant, ff, company, recipient, project,
                           [("Map the invoice process", S.IN_PROGRESS, "Original line.")])
    digest_service.edit_body(digest, actor=ff.user, role="FF",
                             body_text="A rewritten week, in my own words.")
    digest.refresh_from_db()
    assert digest.body_html == ""
    digest_service.approve(digest, actor=ff.user, role="FF")
    digest_service.send_due(seeded_tenant, now=digest.send_window_at)
    html = html_part(dev_outbox[0])
    assert "A rewritten week, in my own words." in html
    assert "Original line." not in html and "Original line." not in dev_outbox[0].body


# --------------------------------------------------------- client-activity notice

@pytest.mark.django_db
def test_the_client_activity_notice_lists_who_what_and_when(seeded_tenant, ff, company,
                                                           dev_outbox, in_tenant_a):
    from apps.work.tasks import notify_client_activity

    ecc = MembershipFactory(tenant=seeded_tenant, role="ECC", client_company=company,
                            user=UserFactory(full_name="Priya Shah"))
    create_task(tenant=seeded_tenant, actor=ecc.user, role="ECC",
                title="Share the vendor list", client_company=company)
    assert notify_client_activity(seeded_tenant, now=timezone.now() + timedelta(minutes=31)) == 1

    email = dev_outbox[0]
    html = html_part(email)
    assert 'data-enhq-email="base"' in html
    assert "<strong style=\"color:#1A1A1A;\">Priya Shah</strong> created “Share the vendor list”" in html
    assert "Priya Shah created “Share the vendor list” — " in email.body
    assert "Your clients have been active in the portal." in email.body


# ------------------------------------------------------------- one-time links

@pytest.mark.django_db
def test_a_magic_link_has_one_button_the_plain_url_and_its_expiry_and_is_never_stored(
    client, seeded_tenant, company, dev_outbox, in_tenant_a
):
    member = MembershipFactory(tenant=seeded_tenant, role="FCC", client_company=company)
    client.post("/auth/magic/request", {"email": member.user.email})

    email = dev_outbox[0]
    html = html_part(email)
    link = email.body.split("Sign in: ")[1].split()[0]
    assert "/auth/magic/" in link
    assert html.count(f'href="{link}"') == 2, "The button, and the plain link beneath it."
    assert ">Sign in</a>" in html and "background-color:#F58220" in html
    assert "expires in 20 minutes" in html and "expires in 20 minutes" in email.body

    row = OutboxMessage.all_objects.get(producer="magic_link")
    for stored in (row.body_html, row.body_text):
        assert "/auth/magic/" not in stored, "A stored copy held a working credential."
    assert ">Sign in</a>" not in row.body_html and "not stored" in row.body_html


@pytest.mark.django_db
def test_a_pin_reset_link_is_the_same_shape_and_never_stored(seeded_tenant):
    from apps.notes.pins import pin_reset_email

    html, text = pin_reset_email(seeded_tenant, title="Q4 <board>", url="https://x/notes/pin-reset/T")
    assert html.count('href="https://x/notes/pin-reset/T"') == 2
    assert "Q4 &lt;board&gt;" in html and "CLEARS the PIN" in text
    stored_html, stored_text = pin_reset_email(seeded_tenant, title="Q4", url=None)
    assert "pin-reset" not in stored_html and "pin-reset" not in stored_text


# ----------------------------------------------------- mail from a person

@pytest.mark.django_db
def test_a_referral_touch_goes_out_in_the_personal_layout(seeded_tenant, ff, dev_outbox,
                                                         in_tenant_a):
    contact = ContactFactory(tenant=seeded_tenant, first_name="Maria")
    ContactEmailFactory(tenant=seeded_tenant, contact=contact, address="maria@partner.invalid",
                        is_primary=True)
    message = outbox.create_message(
        tenant=seeded_tenant, producer=OutboxMessage.Producer.REFERRAL_TOUCH,
        to_contact=contact, to_address="maria@partner.invalid", subject="Checking in",
        body_text="Hi Maria,\n\nSee https://example.com\n\nBryan", actor=ff.user,
    )
    outbox.approve(message, actor=ff.user, role="FF")

    html = html_part(dev_outbox[0])
    assert 'data-enhq-email="personal"' in html and "#0A3A65" not in html
    assert 'href="https://example.com" style="color:#F58220' in html
    assert dev_outbox[0].body == "Hi Maria,\n\nSee https://example.com\n\nBryan"
    message.refresh_from_db()
    assert message.body_html == "", "The draft keeps only its words; the layout is added at send."


# --------------------------------------------------------------------- previews

@pytest.mark.django_db
def test_the_outbox_preview_is_exactly_what_sends_and_only_on_localhost(
    seeded_tenant, ff, api, settings, in_tenant_a
):
    contact = ContactFactory(tenant=seeded_tenant, first_name="Maria")
    message = outbox.create_message(
        tenant=seeded_tenant, producer=OutboxMessage.Producer.REFERRAL_TOUCH,
        to_contact=contact, to_address="maria@partner.invalid", subject="Checking in",
        body_text="Hi Maria", actor=ff.user,
    )
    response = api.as_(ff).get(f"/api/outbox/{message.pk}/preview/")
    assert response.status_code == 200 and response["Content-Type"].startswith("text/html")
    assert response.content.decode() == email_layout.for_delivery(message)[0]
    text = api.as_(ff).get(f"/api/outbox/{message.pk}/preview/?part=text")
    assert text["Content-Type"].startswith("text/plain") and text.content.decode() == "Hi Maria"

    settings.IS_LOCAL = False
    assert api.as_(ff).get(f"/api/outbox/{message.pk}/preview/").status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize("role,expected", [("FF", 200), ("VA", 200), ("ECC", 403)])
def test_who_may_preview_an_outbox_message(role, expected, seeded_tenant, ff, api, company,
                                          in_tenant_a):
    message = outbox.create_message(
        tenant=seeded_tenant, producer=OutboxMessage.Producer.MANUAL,
        to_address="x@partner.invalid", subject="S", body_text="B", actor=ff.user)
    member = MembershipFactory(tenant=seeded_tenant, role=role,
                               client_company=company if role == "ECC" else None)
    assert api.as_(member).get(f"/api/outbox/{message.pk}/preview/").status_code == expected


@pytest.mark.django_db
def test_the_digest_preview_is_the_send_without_issuing_a_real_cadence_link(
    seeded_tenant, ff, api, company, recipient, project, settings, dev_outbox, in_tenant_a
):
    digest = weekly_digest(seeded_tenant, ff, company, recipient, project,
                           [("Map the invoice process", S.IN_PROGRESS, "Preview me.")])
    tokens_before = StakeholderToken.all_objects.count()
    response = api.as_(ff).get(f"/api/digests/{digest.pk}/preview/")
    assert response.status_code == 200
    body = response.content.decode()
    assert "Preview me." in body and 'data-enhq-email="base"' in body
    assert "your-own-link-is-issued-when-it-sends" in body
    assert StakeholderToken.all_objects.count() == tokens_before, "A preview issued a credential."
    assert api.as_(ff).get(f"/api/digests/{digest.pk}/preview/?part=text").content.decode() \
        .startswith("Map the invoice process")

    digest_service.approve(digest, actor=ff.user, role="FF")
    assert api.as_(ff).get(f"/api/digests/{digest.pk}/preview/").status_code == 409
    settings.IS_LOCAL = False
    assert api.as_(ff).get(f"/api/digests/{digest.pk}/preview/").status_code == 404


# --------------------------------------------------------------- the samples

class RecordingTransport:
    name = "recording"

    def __init__(self):
        self.sent = []

    def send(self, **kwargs):
        self.sent.append(kwargs)
        n = len(self.sent)   # a real provider gives every message its own id
        return {"provider": "gmail", "provider_message_id": f"m{n}",
                "gmail_message_id": f"m{n}", "gmail_thread_id": f"t{n}",
                "message_id_header": f"<m{n}@x>",
                # Like a real transport: the address it actually sent from.
                "from_address": kwargs.get("from_address") or "info@getexecutivesnow.com"}


@pytest.mark.django_db
def test_samples_go_only_to_an_allow_listed_address_on_localhost(seeded_tenant, ff, settings,
                                                                in_tenant_a):
    settings.DEV_REAL_SEND_ALLOWLIST = ["owner@example.invalid"]
    with pytest.raises(CommandError, match="not in the dev allow-list"):
        call_command("send_email_samples", "--to", "client@example.invalid", stdout=io.StringIO())
    settings.IS_LOCAL = False
    with pytest.raises(CommandError, match="localhost"):
        call_command("send_email_samples", "--to", "owner@example.invalid", stdout=io.StringIO())
    assert not OutboxMessage.all_objects.exists()


@pytest.mark.django_db
def test_samples_send_one_of_each_producer_and_touch_no_engagement(
    seeded_tenant, ff, settings, monkeypatch, in_tenant_a
):
    settings.DEV_REAL_SEND_ALLOWLIST = ["owner@example.invalid"]
    fake = RecordingTransport()
    monkeypatch.setattr(transport, "get_transport", lambda name=None: fake)

    dry = io.StringIO()
    call_command("send_email_samples", "--to", "owner@example.invalid", "--dry-run", stdout=dry)
    assert dry.getvalue().count("would send") == 8 and not fake.sent
    assert not OutboxMessage.all_objects.exists()

    out = io.StringIO()
    call_command("send_email_samples", "--to", "owner@example.invalid", stdout=out)
    assert "8 of 8 samples sent" in out.getvalue()
    assert len(fake.sent) == 8
    rows = OutboxMessage.all_objects.filter(source_type="email_sample")
    assert sorted(rows.values_list("producer", flat=True)) == sorted([
        "digest", "client_activity", "referral_touch", "referral_onboarding", "manual",
        "stage_rule", "magic_link", "note_pin_reset"])
    for sent in fake.sent:
        assert sent["subject"].startswith("[Sample] ")
        assert sent["body_text"].strip(), sent["subject"]
        assert "<style" not in sent["body_html"].lower()
        personal = 'data-enhq-email="personal"' in sent["body_html"]
        base = 'data-enhq-email="base"' in sent["body_html"]
        assert personal or base, sent["subject"]
    personal_subjects = [s["subject"] for s in fake.sent
                         if 'data-enhq-email="personal"' in s["body_html"]]
    assert len(personal_subjects) == 4, personal_subjects

    # Real engagements are untouched.
    assert not Digest.all_objects.exists() and not DigestItem.all_objects.exists()
    assert not StakeholderToken.all_objects.exists()
    assert not AuditEvent.all_objects.filter(verb="client_activity.notified").exists()


# ---------------------------------------------------------------------- the logo

def png(width, height):
    """A real, minimal PNG — no imaging library in the stack."""
    import struct
    import zlib

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    rows = b"".join(b"\x00" + b"\xff\x82\x20" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


@pytest.fixture
def logo(seeded_tenant, tmp_path):
    path = tmp_path / "executives-now-logo.png"
    path.write_bytes(png(440, 100))
    call_command("set_email_logo", str(path), "--tenant", seeded_tenant.slug,
                 stdout=io.StringIO())
    seeded_tenant.refresh_from_db()
    return seeded_tenant.email_logo


@pytest.mark.django_db
def test_the_header_shows_the_tenant_logo_on_white_above_both_brand_bars(seeded_tenant, logo):
    assert (seeded_tenant.email_logo_width, seeded_tenant.email_logo_height) == (260, 59), (
        "Fitted into the 260 x 84 header box, proportions kept.")
    html = email_layout.document(seeded_tenant, content_html="<p>Hello</p>", subject="Hi")
    assert f'src="cid:{email_layout.LOGO_CID}"' in html
    assert 'width="260" height="59" alt="Executives Now"' in html, (
        "Outlook needs the size attributes; the alt text is the name when images are off.")
    assert "background-color:#FFFFFF;padding:22px 32px" in html, "White header."
    assert "background-color:#0A3A65;height:6px" in html, "The header-colour bar."
    assert "background-color:#F58220;height:4px" in html, "The accent rule."
    assert '0.2px;color:#0A3A65;">Executives Now<' not in html, (
        "The logo replaces the text wordmark in the header; the footer still names "
        "the practice.")
    assert "<style" not in html.lower()


@pytest.mark.django_db
def test_without_a_logo_the_header_is_the_practice_name(seeded_tenant):
    html = email_layout.document(seeded_tenant, content_html="x")
    assert "<img" not in html and ">Executives Now<" in html
    assert email_layout.with_logo(html, seeded_tenant) == (html, [])


def test_the_mime_puts_the_logo_beside_the_html_it_is_cited_by():
    mime = transport.build_mime(
        to_address="a@example.invalid", from_address="info@example.invalid", subject="S",
        body_text="Plain", body_html='<img data-enhq-logo src="cid:enhq-logo">', message_id="<x@y>",
        thread_token="tok", attachments=[("f.pdf", b"%PDF-1", "application/pdf")],
        inline_images=[("enhq-logo", png(4, 2), "image/png", "logo.png")])
    parsed = message_from_bytes(mime.as_bytes())
    types = [part.get_content_type() for part in parsed.walk()]
    assert types.index("text/plain") < types.index("text/html")
    related = next(p for p in parsed.walk() if p.get_content_type() == "multipart/related")
    inside = [p.get_content_type() for p in related.walk()]
    assert inside == ["multipart/related", "text/html", "image/png"]
    image = next(p for p in parsed.walk() if p.get_content_type() == "image/png")
    assert image["Content-ID"] == "<enhq-logo>"
    assert image.get_content_disposition() == "inline"
    assert image.get_payload(decode=True) == png(4, 2)
    assert [p.get_filename() for p in parsed.walk()
            if p.get_content_disposition() == "attachment"] == ["f.pdf"], (
        "The logo is not an attachment; the real attachment still is.")


@pytest.mark.django_db
def test_a_sent_digest_carries_the_logo_bytes_inline(
    seeded_tenant, ff, company, recipient, project, logo, dev_outbox, in_tenant_a
):
    digest = weekly_digest(seeded_tenant, ff, company, recipient, project,
                           [("Map the invoice process", S.IN_PROGRESS, "Mapping has begun.")])
    digest_service.approve(digest, actor=ff.user, role="FF")
    digest_service.send_due(seeded_tenant, now=digest.send_window_at)

    email = dev_outbox[0]
    assert 'src="cid:enhq-logo"' in html_part(email)
    images = [a for a in email.attachments if getattr(a, "get", None) and a.get("Content-ID")]
    assert len(images) == 1 and images[0]["Content-ID"] == "<enhq-logo>"
    assert images[0].get_payload(decode=True) == png(440, 100)
    assert email.mixed_subtype == "related"


@pytest.mark.django_db
def test_an_unreadable_logo_never_stops_a_send_the_name_takes_its_place(
    seeded_tenant, ff, logo, dev_outbox, in_tenant_a
):
    from apps.tenancy import storage

    storage.delete(logo)   # the row still points at it; the bytes are gone
    message = outbox.create_message(
        tenant=seeded_tenant, producer=OutboxMessage.Producer.MANUAL,
        to_address="x@partner.invalid", subject="S", body_text="B", actor=ff.user)
    html = email_layout.document(seeded_tenant, content_html="<p>Sign in</p>")
    resolved, inline = email_layout.with_logo(html, seeded_tenant)
    assert inline == [] and "<img" not in resolved and ">Executives Now<" in resolved

    # And end to end, through the one path out of the app.
    message.body_html = html
    message.save(update_fields=["body_html"])
    outbox.approve(message, actor=ff.user, role="FF")
    assert len(dev_outbox) == 1
    assert "<img" not in html_part(dev_outbox[0]) and not dev_outbox[0].attachments


@pytest.mark.django_db
def test_the_preview_embeds_the_logo_because_a_browser_cannot_resolve_cid(
    seeded_tenant, ff, api, logo, company, recipient, project, dev_outbox, in_tenant_a
):
    digest = weekly_digest(seeded_tenant, ff, company, recipient, project,
                           [("Map the invoice process", S.IN_PROGRESS, "Preview me.")])
    body = api.as_(ff).get(f"/api/digests/{digest.pk}/preview/").content.decode()
    assert 'src="data:image/png;base64,' in body and "cid:" not in body
    expected, _ = email_layout.with_logo(
        digest_service.email_for(digest, footer_url=digest_service.preview_footer_url())[0],
        seeded_tenant, as_data_uri=True)
    assert body == expected, "Apart from the image source, the preview is the send."


@pytest.mark.django_db
def test_one_tenants_logo_never_appears_in_another_tenants_email(seeded_tenant, logo, tenant_b):
    html = email_layout.document(tenant_b, content_html="x")
    assert "<img" not in html and email_layout.with_logo(html, tenant_b) == (html, [])
    # Even a document that cites the logo resolves against its own tenant only.
    borrowed = email_layout.document(seeded_tenant, content_html="x")
    resolved, inline = email_layout.with_logo(borrowed, tenant_b)
    assert inline == [] and "<img" not in resolved


@pytest.mark.django_db
def test_set_email_logo_refuses_what_cannot_be_a_logo_and_clears(seeded_tenant, tmp_path, logo):
    text = tmp_path / "logo.png"
    text.write_bytes(b"not an image")
    with pytest.raises(CommandError, match="PNG or a JPEG"):
        call_command("set_email_logo", str(text), "--tenant", seeded_tenant.slug)
    big = tmp_path / "big.png"
    big.write_bytes(png(1, 1) + b"\x00" * (email_layout.LOGO_MAX_BYTES + 1))
    with pytest.raises(CommandError, match="the limit is 500 KB"):
        call_command("set_email_logo", str(big), "--tenant", seeded_tenant.slug)

    dry = io.StringIO()
    small = tmp_path / "small.png"
    small.write_bytes(png(100, 40))
    call_command("set_email_logo", str(small), "--tenant", seeded_tenant.slug, "--dry-run",
                 stdout=dry)
    assert "shown at 100 x 40 px" in dry.getvalue(), "Never enlarged."
    seeded_tenant.refresh_from_db()
    assert seeded_tenant.email_logo_id == logo.pk, "A dry run changes nothing."

    call_command("set_email_logo", "--clear", "--tenant", seeded_tenant.slug, stdout=io.StringIO())
    seeded_tenant.refresh_from_db()
    assert seeded_tenant.email_logo_id is None and seeded_tenant.email_logo_width == 0


def test_image_size_reads_png_and_jpeg_headers():
    assert email_layout.image_size(png(440, 100)) == ("image/png", 440, 100)
    jpeg = (b"\xff\xd8" + b"\xff\xe0\x00\x04\x00\x00"
            + b"\xff\xc0\x00\x0b\x08\x00\x64\x01\xb8\x01\x01\x11\x00" + b"\xff\xd9")
    assert email_layout.image_size(jpeg) == ("image/jpeg", 440, 100)
    assert email_layout.logo_display_size(400, 400) == (84, 84), "The height caps a square."


# ------------------------------------------------------ the personal sign-off

SIGNATURE = ("Bryan Baker\nFractional COO, Executives Now\n(555) 010-0000\n"
             "bryan.baker@getexecutivesnow.com\nhttps://getexecutivesnow.com")


@pytest.fixture
def mark(seeded_tenant, tmp_path):
    path = tmp_path / "mark.png"
    path.write_bytes(png(112, 112))
    call_command("set_email_logo", str(path), "--mark", "--tenant", seeded_tenant.slug,
                 stdout=io.StringIO())
    seeded_tenant.refresh_from_db()
    return seeded_tenant.email_mark


def _touch(tenant, ff, body):
    return outbox.create_message(
        tenant=tenant, producer=OutboxMessage.Producer.REFERRAL_TOUCH,
        to_address="maria@partner.invalid", subject="Checking in", body_text=body, actor=ff.user)


@pytest.mark.django_db
def test_mail_from_a_person_signs_off_with_the_mark_beside_the_contact_lines(
    seeded_tenant, ff, mark, in_tenant_a
):
    from apps.crm.models import MailPreference

    MailPreference.all_objects.update_or_create(tenant=seeded_tenant, user=ff.user,
                                                defaults={"signature_text": SIGNATURE})
    body = f"Hi Maria,\n\nGood to see you last week.\n\n{SIGNATURE}"
    message = _touch(seeded_tenant, ff, body)
    preferences = MailPreference.all_objects.count()

    html, text = email_layout.for_delivery(message)
    assert text == body, "The plain part is the words as written."
    assert 'data-enhq-email="personal"' in html and "data-enhq-signature" in html
    assert '<strong style="font-size:15px;color:#0A3A65;">Bryan Baker</strong>' in html
    assert 'href="mailto:bryan.baker@getexecutivesnow.com"' in html
    assert 'href="https://getexecutivesnow.com"' in html
    assert "border-left:3px solid #F58220" in html
    assert html.count("Fractional COO") == 1, "The sign-off is not also left in the body."
    assert f'src="cid:{email_layout.MARK_CID}"' in html and 'width="56" height="56"' in html
    assert "#0A3A65;height:6px" not in html, "Still no corporate header on mail from a person."

    _, inline = email_layout.with_logo(html, seeded_tenant)
    assert [part[0] for part in inline] == [email_layout.MARK_CID]
    assert inline[0][1] == png(112, 112)
    assert MailPreference.all_objects.count() == preferences, "Rendering writes nothing."


@pytest.mark.django_db
def test_the_default_sign_off_is_recognised_and_an_edited_one_is_left_alone(
    seeded_tenant, ff, mark, in_tenant_a
):
    ff.user.full_name = "Bryan Baker"
    ff.user.save()
    signed = _touch(seeded_tenant, ff, f"Hi Maria,\n\nBryan Baker\n{seeded_tenant.name}")
    assert "data-enhq-signature" in email_layout.for_delivery(signed)[0]

    edited = _touch(seeded_tenant, ff, "Hi Maria,\n\nThanks,\nB")
    html = email_layout.for_delivery(edited)[0]
    assert "data-enhq-signature" not in html and "enhq-mark" not in html


@pytest.mark.django_db
def test_an_unreadable_mark_leaves_the_sign_off_without_an_image(seeded_tenant, ff, mark,
                                                                  in_tenant_a):
    from apps.tenancy import storage

    ff.user.full_name = "Bryan Baker"
    ff.user.save()
    storage.delete(mark)
    html = email_layout.for_delivery(
        _touch(seeded_tenant, ff, f"Hi Maria,\n\nBryan Baker\n{seeded_tenant.name}"))[0]
    resolved, inline = email_layout.with_logo(html, seeded_tenant)
    assert inline == [] and "<img" not in resolved and "data-enhq-mark" not in resolved
    assert "data-enhq-signature" in resolved and "Bryan Baker" in resolved


@pytest.mark.django_db
def test_a_client_signs_in_to_the_practice_not_to_the_product(seeded_tenant):
    from apps.accounts.views import magic_link_email, magic_link_subject
    from config.branding import PRODUCT_NAME

    html, text = magic_link_email(seeded_tenant, url="https://app.example.invalid/auth/magic/x")
    assert magic_link_subject(seeded_tenant) == "Sign in to Executives Now"
    assert "Sign in to Executives Now" in html and "Sign in to Executives Now" in text
    assert PRODUCT_NAME not in html and PRODUCT_NAME not in text
    seeded_tenant.email_display_name = "Acme Fractional"
    assert magic_link_subject(seeded_tenant) == "Sign in to Acme Fractional"


@pytest.mark.django_db
def test_the_four_personal_samples_send_from_the_owners_own_address(
    seeded_tenant, ff, settings, monkeypatch, in_tenant_a
):
    from .factories import GmailConnectionFactory

    settings.DEV_REAL_SEND_ALLOWLIST = ["owner@example.invalid"]
    GmailConnectionFactory(tenant=seeded_tenant, user=ff.user,
                           email_address="bryan.baker@getexecutivesnow.com",
                           send_as_address=seeded_tenant.from_address,
                           send_as_verified_at=timezone.now())
    fake = RecordingTransport()
    monkeypatch.setattr(transport, "get_transport", lambda name=None: fake)

    out = io.StringIO()
    call_command("send_email_samples", "--to", "owner@example.invalid", stdout=out)
    by_producer = {row.producer: row.from_address
                   for row in OutboxMessage.all_objects.filter(source_type="email_sample")}
    handed = {kwargs["subject"]: kwargs["from_address"] for kwargs in fake.sent}
    for producer in ("referral_touch", "referral_onboarding", "manual", "stage_rule"):
        assert by_producer[producer] == "bryan.baker@getexecutivesnow.com", producer
    assert sum(1 for a in handed.values() if a == "bryan.baker@getexecutivesnow.com") == 4, (
        "The transport was handed the own address for exactly the four personal samples.")
    assert sum(1 for a in handed.values() if a == seeded_tenant.from_address) == 4
    assert "[Sample] Sign in to Executives Now" in handed
    assert out.getvalue().count("from bryan.baker@getexecutivesnow.com") == 4
