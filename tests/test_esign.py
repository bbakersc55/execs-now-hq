"""E-signature, version one (owner, 2026-10-29; `docs/p6_esign.md`).

1. A document from a template is merged and kept as one PDF with its hash;
   an upload is checked and kept as uploaded.
2. Sending: the request waits in the Outbox with {SignLink}; delivery fills
   the link in (never stored) and makes it Sent for 30 days.
3. The signing page: the first look makes it Viewed; signing needs the
   consent line and a typed or drawn signature; the PDF's hash is checked;
   the link is one use, and an expired, voided, used or wrong one is a 404.
4. Decline with a reason; countersign by the practice; the final PDF to both.
5. The two stage triggers, forward only, and the default rules.
6. The welcome letter's chips.
7. Isolation and roles: another practice never sees a document; an
   assistant sees state only; a client sees their own company's in the
   portal, never a draft.
"""

from __future__ import annotations

import base64
import io
import json
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.crm.models import ContactPipelinePosition, OutboxMessage, Pipeline, PipelineStage
from apps.esign import links, seed, services
from apps.esign.models import Document, DocumentTemplate, Signature
from apps.notify.models import Notice
from apps.tenancy.context import tenant_context
from apps.tenancy.models import AuditEvent

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import (
    ClientCompanyFactory, ContactEmailFactory, ContactFactory, DocumentTemplateFactory,
    TenantFactory,
)

pytestmark = pytest.mark.django_db
SIGNER = "dana.whitfield@hooli.invalid"


def post(client, url, data=None):
    return client.post(url, json.dumps(data or {}), content_type="application/json")


def _pdf_text(content: bytes) -> str:
    from pypdf import PdfReader

    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(content)).pages)


def _pages(content: bytes) -> int:
    from pypdf import PdfReader

    return len(PdfReader(io.BytesIO(content)).pages)


def _blank_pdf() -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(612, 792)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _png() -> str:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGBA", (120, 40), (10, 58, 101, 255)).save(out, format="PNG")
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()


@pytest.fixture
def world(seeded_tenant, ff, cf, va):
    t = seeded_tenant
    hooli = ClientCompanyFactory(tenant=t, name="Hooli Field Services")
    dana = ContactFactory(tenant=t, company=hooli, first_name="Dana", last_name="Whitfield")
    ContactEmailFactory(tenant=t, contact=dana, address=SIGNER)
    with tenant_context(t.pk):
        seed.seed_tenant(t)
        proposal = DocumentTemplate.all_objects.get(tenant=t, original="proposal")
    return {"t": t, "hooli": hooli, "dana": dana, "proposal": proposal, "ff": ff, "cf": cf,
            "va": va}


FIELDS = {"Scope": "Fix dispatch and the weekly schedule", "Fee": "$6,000 a month",
          "Term": "Six months", "StartDate": "2026-12-01"}


def _document(world, **fields):
    with tenant_context(world["t"].pk):
        return services.from_template(world["hooli"], world["proposal"], world["dana"],
                                      fields=fields or FIELDS, actor=world["ff"].user)


def _sent(world, dev_outbox):
    """A document, its request approved and delivered: (document, token)."""
    from apps.crm.services import outbox

    document = _document(world)
    with tenant_context(world["t"].pk):
        message = services.queue_request(document, actor=world["ff"].user, role="FF")
        outbox.approve(message, actor=world["ff"].user, role="FF")
    sent = dev_outbox[-1]
    token = sent.body.split("/sign/")[1].split()[0].strip()
    document.refresh_from_db()
    return document, token


def _sign(api_client, token, **data):
    body = {"agreed": True, "method": "typed", "typed": "Dana Whitfield", **data}
    return api_client.post(f"/api/sign/{token}", json.dumps(body),
                           content_type="application/json", HTTP_USER_AGENT="Phone browser")


# ------------------------------------------------------------- making one

def test_a_template_document_is_merged_kept_once_and_hashed(world):
    from apps.tenancy import storage

    document = _document(world)
    content = storage.read(document.pdf)
    assert document.state == "draft" and document.source == "template"
    assert document.pdf_sha256 == services.pdfs.sha256(content)
    text = _pdf_text(content)
    for words in ("Proposal", "Dana Whitfield", "Hooli Field Services", "$6,000 a month",
                  "Six months", "December 1, 2026", "Fix dispatch"):
        assert words in text, words
    assert "{" not in text


def test_an_upload_must_be_a_readable_pdf(world, api):
    client = api.as_(world["ff"])
    bad = client.post("/api/documents/", {"company": str(world["hooli"].pk),
                                          "signer": str(world["dana"].pk), "title": "MSA",
                                          "file": io.BytesIO(b"not a pdf")})
    assert bad.status_code == 400 and "not a PDF" in bad.json()["detail"]
    upload = io.BytesIO(_blank_pdf())
    upload.name = "msa.pdf"
    good = client.post("/api/documents/", {"company": str(world["hooli"].pk),
                                           "signer": str(world["dana"].pk), "title": "MSA",
                                           "file": upload})
    assert good.status_code == 201, good.content
    document = Document.all_objects.get(pk=good.json()["id"])
    assert document.source == "upload" and document.pdf_sha256 == services.pdfs.sha256(_blank_pdf())


def test_the_signer_is_one_of_the_companys_contacts(world, api):
    elsewhere = ContactFactory(tenant=world["t"], first_name="Gavin")
    response = post(api.as_(world["ff"]), "/api/documents/", {
        "company": str(world["hooli"].pk), "signer": str(elsewhere.pk),
        "template": str(world["proposal"].pk), "fields": FIELDS})
    assert response.status_code == 400
    assert "this company's contacts" in response.json()["detail"]


# ------------------------------------------------------------- sending

def test_the_request_waits_with_its_chip_and_delivery_makes_the_link(world, dev_outbox):
    from apps.crm.services import outbox

    document = _document(world)
    with tenant_context(world["t"].pk):
        message = services.queue_request(document, actor=world["ff"].user, role="FF")
    assert message.state == "pending_approval" and "{SignLink}" in message.body_text
    document.refresh_from_db()
    assert document.state == "draft" and not document.link_hash
    with tenant_context(world["t"].pk):
        outbox.approve(message, actor=world["ff"].user, role="FF")
    message.refresh_from_db()
    document.refresh_from_db()
    assert message.state == "sent"
    # The link went; the row still says {SignLink}, and holds no working link.
    assert "/sign/" in dev_outbox[-1].body and "{SignLink}" not in dev_outbox[-1].body
    assert "{SignLink}" in message.body_text and "/sign/" not in message.body_text
    assert document.state == "sent" and document.link_hash
    assert document.expires_at - document.sent_at == timedelta(days=30)


def test_a_voided_documents_request_is_not_sent(world, dev_outbox):
    from apps.crm.services import outbox

    document = _document(world)
    with tenant_context(world["t"].pk):
        message = services.queue_request(document, actor=world["ff"].user, role="FF")
        services.void(document, actor=world["ff"].user, reason="Wrong fee")
    message.refresh_from_db()
    assert message.state == "rejected"
    with tenant_context(world["t"].pk), pytest.raises(outbox.SendNotPermitted):
        outbox.approve(message, actor=world["ff"].user, role="FF")
    assert dev_outbox == []


# ------------------------------------------------------------- signing

def test_the_framed_pdf_reaches_a_signed_out_visitor_with_the_token(world, dev_outbox):
    """The page frames `/api/sign/<token>/pdf`: a signed-out browser must get
    the PDF itself, inline, and a frame header that lets our own page show it
    (the site-wide DENY showed Chrome's broken document, 2026-10-29). Opening
    it full size is the same URL at the top level."""
    from django.test import Client

    document, token = _sent(world, dev_outbox)
    visitor = Client()
    page = visitor.get(f"/api/sign/{token}")
    assert page.status_code == 200 and page["X-Frame-Options"] == "DENY"
    pdf = visitor.get(f"/api/sign/{token}/pdf")
    assert pdf.status_code == 200
    assert pdf["Content-Type"] == "application/pdf"
    assert pdf["Content-Disposition"].startswith("inline;")
    assert pdf["X-Frame-Options"] == "SAMEORIGIN"
    assert "frame-ancestors 'none'" not in pdf.get("Content-Security-Policy", "")
    assert pdf.content.startswith(b"%PDF-") and _pages(pdf.content) >= 1
    _sign(visitor, token)
    assert visitor.get(f"/api/sign/{token}/pdf").status_code == 404


def test_viewing_then_signing_records_everything_and_appends_the_page(world, dev_outbox, client):
    from apps.tenancy import storage

    document, token = _sent(world, dev_outbox)
    page = client.get(f"/api/sign/{token}")
    assert page.status_code == 200
    body = page.json()
    assert body["title"] == document.title and body["consent_version"] == "2026-10-29"
    assert "ESIGN" in body["consent_text"] and SIGNER in body["consent_text"]
    document.refresh_from_db()
    assert document.state == "viewed"
    assert Notice.all_objects.filter(kind="document", source_type="document.viewed",
                                     recipient=world["ff"].user).count() == 1
    client.get(f"/api/sign/{token}")
    assert Notice.all_objects.filter(source_type="document.viewed").count() == 1

    assert client.get(f"/api/sign/{token}/pdf").content == storage.read(document.pdf)
    signed = _sign(client, token)
    assert signed.status_code == 200, signed.content
    document.refresh_from_db()
    signature = Signature.all_objects.get(document=document)
    assert document.state == "signed" and not document.link_hash
    assert (signature.role, signature.email, signature.method) == ("signer", SIGNER, "typed")
    assert signature.consent_version == "2026-10-29" and "ESIGN" in signature.consent_text
    assert signature.pdf_sha256 == document.pdf_sha256
    assert signature.user_agent == "Phone browser" and signature.ip_address
    final = storage.read(document.signed_pdf)
    assert _pages(final) == _pages(storage.read(document.pdf)) + 1
    text = _pdf_text(final)
    assert "Signatures" in text and SIGNER in text and document.pdf_sha256 in text.replace("\n", "")
    assert {n.source_type for n in Notice.all_objects.filter(kind="document")} >= {
        "document.signed", "document.countersign"}


def test_the_typed_signature_is_drawn_in_the_embedded_cursive_face(world, dev_outbox, client):
    from pypdf import PdfReader

    from apps.tenancy import storage

    document, token = _sent(world, dev_outbox)
    _sign(client, token)
    document.refresh_from_db()
    reader = PdfReader(io.BytesIO(storage.read(document.signed_pdf)))
    fonts = set()
    for page in reader.pages:
        for font in (page.get("/Resources", {}).get("/Font", {}) or {}).values():
            fonts.add(str(font.get_object().get("/BaseFont")))
    assert any("Dancing" in name for name in fonts), fonts


def test_a_drawn_signature_is_accepted_and_kept(world, dev_outbox, client):
    document, token = _sent(world, dev_outbox)
    response = _sign(client, token, method="drawn", typed="", drawn=_png())
    assert response.status_code == 200, response.content
    signature = Signature.all_objects.get(document=document)
    assert signature.method == "drawn" and bytes(signature.drawn_png).startswith(b"\x89PNG")


def test_no_signature_without_the_consent_line(world, dev_outbox, client):
    document, token = _sent(world, dev_outbox)
    response = _sign(client, token, agreed=False)
    assert response.status_code == 400 and "consent" in response.json()["detail"]
    document.refresh_from_db()
    assert document.state == "sent" or document.state == "viewed"
    assert not Signature.all_objects.filter(document=document).exists()


def test_the_link_is_one_use(world, dev_outbox, client):
    document, token = _sent(world, dev_outbox)
    assert _sign(client, token).status_code == 200
    assert client.get(f"/api/sign/{token}").status_code == 404
    assert _sign(client, token).status_code == 404
    assert client.get(f"/api/sign/{token}/pdf").status_code == 404
    assert Signature.all_objects.filter(document=document).count() == 1


def test_an_expired_link_is_refused_and_the_daily_job_expires_it(world, dev_outbox, client):
    document, token = _sent(world, dev_outbox)
    Document.all_objects.filter(pk=document.pk).update(
        expires_at=timezone.now() - timedelta(minutes=1))
    assert client.get(f"/api/sign/{token}").status_code == 404
    assert _sign(client, token).status_code == 404
    assert services.daily(world["t"])["expired"] == 1
    document.refresh_from_db()
    assert document.state == "expired" and not document.link_hash


def test_a_wrong_token_is_the_same_refusal(client):
    response = client.get("/api/sign/not-a-real-token")
    assert response.status_code == 404 and "not valid" in response.json()["detail"]


def test_a_changed_pdf_cannot_be_signed(world, dev_outbox, client):
    from apps.tenancy import storage

    document, token = _sent(world, dev_outbox)
    # Someone changes the stored bytes behind the app's back.
    from pathlib import Path

    from django.conf import settings

    Path(settings.MEDIA_ROOT, document.pdf.bucket, document.pdf.object_key).write_bytes(
        _blank_pdf())
    assert storage.read(document.pdf) == _blank_pdf()
    response = _sign(client, token)
    assert response.status_code == 409 and "changed since it was sent" in response.json()["detail"]
    document.refresh_from_db()
    assert document.state in ("sent", "viewed") and document.link_hash
    assert AuditEvent.all_objects.filter(verb="document.hash_mismatch").exists()


def test_decline_needs_a_reason_and_spends_the_link(world, dev_outbox, client):
    document, token = _sent(world, dev_outbox)
    url = f"/api/sign/{token}/decline"
    assert post(client, url, {"reason": " "}).status_code == 400
    response = post(client, url, {"reason": "The fee is over our budget."})
    assert response.status_code == 200
    document.refresh_from_db()
    assert document.state == "declined" and document.decline_reason == "The fee is over our budget."
    assert not document.link_hash and client.get(f"/api/sign/{token}").status_code == 404
    assert Notice.all_objects.filter(source_type="document.declined").exists()


# ------------------------------------------------------------- countersigning

def test_countersigning_completes_it_and_emails_the_final_pdf_to_both(world, dev_outbox, client,
                                                                     api):
    from apps.tenancy import storage

    document, token = _sent(world, dev_outbox)
    _sign(client, token)
    url = f"/api/documents/{document.pk}/countersign/"
    assert post(api.as_(world["va"]), url, {"agreed": True, "method": "typed",
                                            "typed": "Avery"}).status_code == 403
    assert post(api.as_(world["ff"]), url, {"agreed": False, "method": "typed",
                                            "typed": "Bryan"}).status_code == 400
    response = post(api.as_(world["ff"]), url, {"agreed": True, "method": "typed",
                                                "typed": "Bryan Baker"})
    assert response.status_code == 200, response.content
    document.refresh_from_db()
    assert document.state == "complete" and document.countersigned_by == world["ff"].user
    final = storage.read(document.final_pdf)
    assert document.final_sha256 == services.pdfs.sha256(final)
    assert _pages(final) == _pages(storage.read(document.pdf)) + 1
    text = _pdf_text(final).upper()
    assert "COUNTERSIGNER" in text and SIGNER.upper() in text and "SIGNATURE PAGE" in text
    counter = Signature.all_objects.get(document=document, role="countersigner")
    # The countersigner's line is kept as the card showed it.
    assert counter.consent_text == response.json()["countersign_consent"]
    assert "countersignature for" in counter.consent_text
    copy = OutboxMessage.all_objects.get(producer="signed_copy")
    assert copy.state == "sent" and copy.to_address == SIGNER
    assert copy.also_to_address == world["ff"].user.email
    sent = dev_outbox[-1]
    assert sent.attachments and sent.attachments[0][1] == final
    assert set(sent.to) | set(sent.cc or []) >= {SIGNER} or SIGNER in sent.to


def test_only_a_signed_document_is_countersigned(world, api):
    document = _document(world)
    response = post(api.as_(world["ff"]), f"/api/documents/{document.pk}/countersign/",
                    {"agreed": True, "method": "typed", "typed": "Bryan"})
    assert response.status_code == 409


# ------------------------------------------------------------- the daily job

def test_one_reminder_at_seven_days_with_the_same_link(world, dev_outbox, client):
    document, token = _sent(world, dev_outbox)
    Document.all_objects.filter(pk=document.pk).update(sent_at=timezone.now() - timedelta(days=8))
    assert services.daily(world["t"])["reminded"] == 1
    assert services.daily(world["t"])["reminded"] == 0
    reminder = OutboxMessage.all_objects.get(producer="signature_reminder")
    assert "/sign/" not in reminder.body_text
    assert f"/sign/{token}" in dev_outbox[-1].body
    assert client.get(f"/api/sign/{token}").status_code == 200


# ------------------------------------------------------------- stage rules

def _at(world, code):
    sales = Pipeline.all_objects.get(tenant=world["t"], kind="sales")
    stage = PipelineStage.all_objects.get(pipeline=sales, code=code)
    ContactPipelinePosition.all_objects.update_or_create(
        tenant=world["t"], contact=world["dana"], pipeline=sales, defaults={"stage": stage})
    return sales


def _stage_of(world, pipeline):
    return ContactPipelinePosition.all_objects.get(contact=world["dana"],
                                                   pipeline=pipeline).stage.code


def test_sending_moves_them_to_proposal_given_and_signing_to_closed_won(world, dev_outbox, client):
    with tenant_context(world["t"].pk):
        made = seed.default_rules(world["t"])
    assert len(made) == 3 and seed.default_rules(world["t"]) == []
    sales = _at(world, "qualified")
    document, token = _sent(world, dev_outbox)
    assert _stage_of(world, sales) == "proposal_given"
    _sign(client, token)
    assert _stage_of(world, sales) == "closed_won"
    # ...where the Welcome letter is drafted, with what was signed, for approval.
    welcome = OutboxMessage.all_objects.get(producer="stage_rule", to_contact=world["dana"])
    assert welcome.state == "pending_approval" and "Fee: $6,000 a month" in welcome.body_text


def test_a_document_rule_never_moves_anyone_backwards(world, dev_outbox):
    with tenant_context(world["t"].pk):
        seed.default_rules(world["t"])
    sales = _at(world, "closed_won")
    _sent(world, dev_outbox)
    assert _stage_of(world, sales) == "closed_won"


def test_a_stage_rule_can_send_a_template_for_signature(world):
    from apps.crm.models import StageAutomation
    from apps.crm.services import pipeline

    sales = Pipeline.all_objects.get(tenant=world["t"], kind="sales")
    given = PipelineStage.all_objects.get(pipeline=sales, code="proposal_given")
    StageAutomation.all_objects.create(
        tenant=world["t"], pipeline=sales, trigger="enters", to_stage=given,
        action_type="send_signature", document_template=world["proposal"])
    with tenant_context(world["t"].pk):
        pipeline.change_stage(world["dana"], given, actor=world["ff"].user)
    document = Document.all_objects.get(signer=world["dana"])
    assert document.state == "draft" and document.from_rule is not None
    assert document.request_message.state == "pending_approval"


def test_the_rule_editor_refuses_a_document_sent_on_a_document_being_sent(world, api):
    sales = Pipeline.all_objects.get(tenant=world["t"], kind="sales")
    response = post(api.as_(world["ff"]), "/api/stage-automations/", {
        "pipeline": str(sales.pk), "trigger": "sent", "action_type": "send_signature",
        "document_template": str(world["proposal"].pk)})
    assert response.status_code == 400 and "never stop" in json.dumps(response.json())
    ok = post(api.as_(world["ff"]), "/api/stage-automations/", {
        "pipeline": str(sales.pk), "trigger": "signed", "action_type": "move_stage",
        "move_to_stage": str(PipelineStage.all_objects.get(pipeline=sales,
                                                           code="closed_won").pk)})
    assert ok.status_code == 201, ok.content
    assert ok.json()["summary"].startswith("When a contact signs a document")


# ------------------------------------------------------------- the welcome letter

def test_the_welcome_letter_fills_its_chips_from_the_signed_document_and_goals(world, dev_outbox,
                                                                               client):
    from apps.crm import template_seed
    from apps.crm.models import EmailTemplate
    from apps.crm.services import templates
    from apps.work.models import Goal

    Goal.all_objects.create(tenant=world["t"], client_company=world["hooli"],
                            title="Dispatch runs without Dana")
    Goal.all_objects.create(tenant=world["t"], client_company=world["hooli"],
                            title="A weekly schedule out by Thursday")
    template_seed.seed_tenant(world["t"])
    welcome = EmailTemplate.all_objects.get(tenant=world["t"], original="welcome_letter")
    # Before anything is signed the term lines leave no gaps.
    _, before = templates.compose(welcome, world["dana"], actor=world["ff"].user)
    assert "Fee:" not in before and "Dispatch runs without Dana" in before
    document, token = _sent(world, dev_outbox)
    _sign(client, token)
    subject, body = templates.compose(welcome, world["dana"], actor=world["ff"].user)
    assert subject == f"Welcome to {world['t'].name}"
    for line in ("Scope: Fix dispatch and the weekly schedule", "Fee: $6,000 a month",
                 "Term: Six months", "Starting: December 1, 2026",
                 "- Dispatch runs without Dana", "- A weekly schedule out by Thursday"):
        assert line in body, line


# ------------------------------------------------------------- isolation and roles

def test_another_practice_never_sees_or_touches_a_document(world, api):
    document = _document(world)
    other = TenantFactory()
    from apps.crm.seed import seed_tenant

    seed_tenant(other)
    stranger = _member(other, "FF")
    client = api.as_(stranger)
    assert client.get("/api/documents/").json() == []
    for url in (f"/api/documents/{document.pk}/", f"/api/documents/{document.pk}/pdf/"):
        assert client.get(url).status_code == 404
    for url in (f"/api/documents/{document.pk}/void/", f"/api/documents/{document.pk}/send/",
                f"/api/documents/{document.pk}/countersign/"):
        assert post(client, url, {"agreed": True, "method": "typed", "typed": "x"}).status_code == 404
    response = post(client, "/api/documents/", {"company": str(world["hooli"].pk),
                                                "signer": str(world["dana"].pk),
                                                "template": str(world["proposal"].pk)})
    assert response.status_code == 404
    assert not DocumentTemplate.all_objects.filter(tenant=other).exists()
    assert client.get(f"/api/document-templates/{world['proposal'].pk}/").status_code == 404


def test_an_assistant_sees_state_and_nothing_in_it(world, api):
    document = _document(world)
    client = api.as_(world["va"])
    row = client.get(f"/api/documents/?company={world['hooli'].pk}").json()[0]
    assert row["state"] == "draft" and "fields" not in row and "pdf_sha256" not in row
    assert client.get(f"/api/documents/{document.pk}/pdf/").status_code == 403
    assert post(client, f"/api/documents/{document.pk}/send/").status_code == 403
    assert post(client, f"/api/documents/{document.pk}/void/").status_code == 403


def test_an_associate_reaches_only_assigned_companies(world, api):
    from .factories import ClientAssignmentFactory

    document = _document(world)
    client = api.as_(world["cf"])
    assert client.get(f"/api/documents/{document.pk}/").status_code == 404
    ClientAssignmentFactory(tenant=world["t"], user=world["cf"].user, company=world["hooli"])
    assert client.get(f"/api/documents/{document.pk}/").json()["fields"]["Fee"] == "$6,000 a month"


def test_a_client_sees_their_own_companys_documents_from_sent_on(world, dev_outbox, api):
    document, _ = _sent(world, dev_outbox)
    draft = _document(world)
    fcc = _member(world["t"], "FCC", company=world["hooli"])
    ecc = _member(world["t"], "ECC", company=world["hooli"])
    other = ClientCompanyFactory(tenant=world["t"])
    elsewhere = _member(world["t"], "FCC", company=other)
    for member in (fcc, ecc):
        rows = api.as_(member).get("/api/portal-documents/").json()
        assert [r["id"] for r in rows] == [str(document.pk)]
        assert "fields" not in rows[0]
        assert api.as_(member).get(f"/api/portal-documents/{document.pk}/pdf/").status_code == 200
        assert api.as_(member).get(f"/api/portal-documents/{draft.pk}/pdf/").status_code == 404
        assert api.as_(member).get("/api/documents/").status_code == 403
    assert api.as_(elsewhere).get("/api/portal-documents/").json() == []
    assert api.as_(elsewhere).get(f"/api/portal-documents/{document.pk}/pdf/").status_code == 404
    assert api.as_(world["ff"]).get("/api/portal-documents/").status_code == 404


def test_the_branding_of_a_signing_link_is_its_practices(world, dev_outbox, client):
    _, token = _sent(world, dev_outbox)
    assert links.document_for(token).tenant_id == world["t"].pk
    from apps.accounts.views import tenant_from_link

    assert tenant_from_link(f"sign:{token}") == world["t"]
    assert tenant_from_link("sign:nope") is None


# ------------------------------------------------------------- the library

def test_the_built_in_templates_restore_and_refuse_unknown_fields(world, api):
    client = api.as_(world["ff"])
    rows = client.get("/api/document-templates/").json()
    assert {r["name"] for r in rows} >= {"Proposal", "Engagement letter"}
    proposal = next(r for r in rows if r["original"] == "proposal")
    assert proposal["fields_used"] == ["Scope", "Fee", "Term", "StartDate"]
    url = f"/api/document-templates/{proposal['id']}/"
    bad = client.patch(url, json.dumps({"body": "Hello {Nonsense}"}),
                       content_type="application/json")
    assert bad.status_code == 400 and "{Nonsense}" in json.dumps(bad.json())
    changed = client.patch(url, json.dumps({"body": "# Fee\n{Fee}"}),
                           content_type="application/json")
    assert changed.json()["changed"] is True
    restored = post(client, f"{url}restore/").json()
    assert restored["changed"] is False and "{Scope}" in restored["body"]
    assert client.delete(url).status_code == 409
    assert api.as_(world["va"]).patch(url, json.dumps({"body": "x"}),
                                      content_type="application/json").status_code == 403


def test_open_the_signing_page_is_the_demos_only(world, dev_outbox, api, settings):
    document, token = _sent(world, dev_outbox)
    url = f"/api/documents/{document.pk}/demo-link/"
    assert post(api.as_(world["ff"]), url).status_code == 404
    settings.APP_ENVIRONMENT = "demo"
    got = post(api.as_(world["ff"]), url)
    assert got.status_code == 200 and got.json()["url"].endswith(f"/sign/{token}")
