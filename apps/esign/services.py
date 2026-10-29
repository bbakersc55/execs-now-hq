"""E-signature, version one (owner, 2026-10-29; `docs/p6_esign.md`).

**Making a document.** From a template (its fields filled, merged for the
signer) or from an uploaded PDF. Either way the PDF is stored once and its
SHA-256 kept; a draft made from a template can be filled in again, which
makes a new PDF, and nothing else ever changes it.

**Sending.** The request is an email in the Outbox, waiting for approval
like everything else, with `{SignLink}` where the link goes. The link is made
when the email is delivered (`delivery_text`) and never stored on the row;
delivery is what moves the document to Sent and starts its 30 days.

**Signing.** The public page (`views_sign.py`) reads the document by its
link. The first look makes it Viewed. Signing needs the consent line ticked
and a typed or drawn signature; the stored PDF's hash is checked against the
one recorded when it was made, and a mismatch refuses. The signature page is
appended, the link is spent, and the sender is told it needs countersigning.

**Countersigning** (a practice owner or an associate, from the company
card): the same capture, then the final PDF (the PDF as sent, plus both
signatures) is kept, and emailed to both sides. That completes it.

**Every day** (`daily`): an unsigned document 30 days after it was sent
expires; one 7 days after, unsigned, gets one reminder.
"""

from __future__ import annotations

import base64
import binascii
import io
import re
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.esign import consent, links
from apps.esign import pdf as pdfs
from apps.esign.models import Document, DocumentTemplate, Signature
from apps.tenancy.models import AuditEvent

S = Document.State
EXPIRES_AFTER = timedelta(days=30)
REMIND_AFTER = timedelta(days=7)
#: The states in which the practice may still withdraw it.
VOIDABLE = (S.DRAFT, S.SENT, S.VIEWED, S.SIGNED)
#: Waiting on the signer.
WAITING = (S.SENT, S.VIEWED)
#: Signed by the client, whatever happened after.
SIGNED_STATES = (S.SIGNED, S.COUNTERSIGNED, S.COMPLETE)
#: The largest drawn signature accepted, as a PNG.
MAX_DRAWN_BYTES = 300 * 1024

#: The fields a document template has beyond an email's general ones, and
#: what the form asks for each.
DOC_FIELDS = (("Scope", "Scope of work"), ("Fee", "Fee"), ("Term", "Term"),
              ("StartDate", "Start date"))
GENERAL = (("FirstName", "Signer's first name"), ("LastName", "Signer's last name"),
           ("Company", "Company"), ("FractionalName", "Your name"),
           ("PracticeName", "The practice's name"), ("Today", "Today's date"))
FIELDS = GENERAL + DOC_FIELDS
NAMES = tuple(name for name, _ in FIELDS)
_FIELD = re.compile(r"\{([A-Za-z][A-Za-z ]*)\}")
SIGN_LINK = "{SignLink}"


class DocumentRefused(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class HashMismatch(DocumentRefused):
    """The stored PDF is not the one recorded when the document was made."""

    def __init__(self, document, found: str):
        super().__init__("This document has changed since it was sent, so it can't be "
                         "signed. Ask the practice to send it again.", 409)
        self.document, self.found = document, found


def _recorded(refusal):
    """A hash mismatch is kept on the record, outside the signing's
    transaction, which it has just rolled back."""
    AuditEvent.all_objects.create(
        tenant_id=refusal.document.tenant_id, verb="document.hash_mismatch",
        target_type="document", target_id=refusal.document.pk,
        payload={"recorded": refusal.document.pdf_sha256, "found": refusal.found})


# ------------------------------------------------------------- templates

def check_template(*texts: str) -> None:
    unknown = sorted({f for t in texts for f in _FIELD.findall(t or "") if f not in NAMES})
    if unknown:
        raise DocumentRefused(
            "There is no merge field called " + ", ".join(f"{{{f}}}" for f in unknown)
            + ". The ones you can use: " + ", ".join(f"{{{f}}}" for f in NAMES) + ".")


def fields_used(template) -> list[str]:
    """The template's own fields, in the form's order: what to ask for."""
    used = set(_FIELD.findall(f"{template.title}\n{template.body}"))
    return [name for name, _ in DOC_FIELDS if name in used]


def is_changed(template) -> bool:
    from apps.esign.seed import ORIGINALS

    original = ORIGINALS.get(template.original)
    if original is None:
        return False
    _name, title, body = original
    return (template.title, template.body) != (title, body)


def restore(template, *, actor=None):
    from apps.esign.seed import ORIGINALS

    original = ORIGINALS.get(template.original)
    if original is None:
        raise DocumentRefused("Only a built-in template has an original to restore.")
    _name, template.title, template.body = original
    template.save(update_fields=["title", "body", "updated_at"])
    AuditEvent.all_objects.create(
        tenant=template.tenant, actor=actor, verb="document_template.restored",
        target_type="document_template", target_id=template.pk,
        payload={"original": template.original})
    return template


def used_for(template) -> list[str]:
    from apps.crm.models import StageAutomation

    rules = StageAutomation.all_objects.filter(document_template=template).count()
    return [f"{rules} stage rule{'s' if rules != 1 else ''}"] if rules else []


def long_date(day) -> str:
    return f"{day:%B} {day.day}, {day.year}"


def _start_date(value: str) -> str:
    """A start date as typed, or a date picker's ISO day in words."""
    from datetime import date

    value = (value or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            return long_date(date.fromisoformat(value))
        except ValueError:
            return value
    return value


def merge(template, signer, *, sender, fields: dict) -> tuple[str, str]:
    """`(title, text)`: the template merged for this signer and these fields."""
    from apps.crm.services import templates

    values = templates.values_for(signer, tenant=template.tenant, sender=sender)
    values = {name: values.get(name, "") for name, _ in GENERAL}
    values["Today"] = long_date(timezone.localdate())
    for name, _ in DOC_FIELDS:
        value = (fields or {}).get(name, "")
        values[name] = _start_date(value) if name == "StartDate" else (value or "").strip()

    def fill(text):
        return _FIELD.sub(lambda m: values.get(m.group(1), m.group(0)), text or "")

    return fill(template.title).strip(), fill(template.body)


# ------------------------------------------------------------- making one

def _store(tenant, content: bytes, filename: str):
    from apps.tenancy import storage

    return storage.save(tenant=tenant, content=content,
                        object_key=storage.object_key("documents", filename),
                        purpose="esign_document", content_type="application/pdf")


def _filename(title: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9]+", "-", title or "document").strip("-") or "document"
    return f"{stem[:80]}.pdf"


def _check_signer(company, signer):
    if signer is None or signer.company_id != company.pk or signer.deleted_at is not None:
        raise DocumentRefused("Choose the signer from this company's contacts.")
    if not (signer.primary_email or "").strip():
        raise DocumentRefused(f"{signer.first_name or 'That contact'} has no email address "
                              "to send the link to.")


def _signer_name(signer) -> str:
    return f"{signer.first_name or ''} {signer.last_name or ''}".strip() or signer.primary_email


@transaction.atomic
def from_template(company, template, signer, *, fields: dict, actor, rule=None):
    _check_signer(company, signer)
    clean = {name: str((fields or {}).get(name, ""))[:4000] for name, _ in DOC_FIELDS}
    title, text = merge(template, signer, sender=actor, fields=clean)
    content = pdfs.render_document(company.tenant, title=title or template.name, text=text)
    document = Document.all_objects.create(
        tenant=company.tenant, company=company, title=(title or template.name)[:160],
        source=Document.Source.TEMPLATE, template=template, fields=clean,
        pdf=_store(company.tenant, content, _filename(title)), pdf_sha256=pdfs.sha256(content),
        signer=signer, signer_name=_signer_name(signer)[:200],
        signer_email=signer.primary_email.strip(), created_by=actor, from_rule=rule)
    _audit(document, actor, "document.created", {"source": "template",
                                                 "template": str(template.pk)})
    return document


@transaction.atomic
def from_upload(company, signer, *, title: str, content: bytes, actor):
    _check_signer(company, signer)
    title = (title or "").strip()
    if not title:
        raise DocumentRefused("Give the document a title.")
    try:
        pdfs.check_upload(content)
    except pdfs.PdfRefused as exc:
        raise DocumentRefused(str(exc)) from None
    document = Document.all_objects.create(
        tenant=company.tenant, company=company, title=title[:160],
        source=Document.Source.UPLOAD, fields={},
        pdf=_store(company.tenant, content, _filename(title)), pdf_sha256=pdfs.sha256(content),
        signer=signer, signer_name=_signer_name(signer)[:200],
        signer_email=signer.primary_email.strip(), created_by=actor)
    _audit(document, actor, "document.created", {"source": "upload",
                                                 "bytes": len(content)})
    return document


@transaction.atomic
def refill(document, *, fields: dict, actor):
    """A draft from a template, filled in again: a new PDF, a new hash."""
    if document.state != S.DRAFT or document.template is None:
        raise DocumentRefused("Only a draft made from a template can be filled in again.", 409)
    if _request_waiting(document) and document.request_message.state != "pending_approval":
        raise DocumentRefused("Its email is on its way; void it and make a new one.", 409)
    clean = {name: str((fields or {}).get(name, ""))[:4000] for name, _ in DOC_FIELDS}
    title, text = merge(document.template, document.signer, sender=actor, fields=clean)
    content = pdfs.render_document(document.tenant, title=title or document.template.name,
                                   text=text)
    document.fields = clean
    document.title = (title or document.template.name)[:160]
    document.pdf = _store(document.tenant, content, _filename(title))
    document.pdf_sha256 = pdfs.sha256(content)
    document.save(update_fields=["fields", "title", "pdf", "pdf_sha256", "updated_at"])
    _audit(document, actor, "document.refilled", {})
    return document


def preview(company, template, signer, *, fields: dict, actor) -> bytes:
    """The PDF a template would make, made and not kept."""
    _check_signer(company, signer)
    title, text = merge(template, signer, sender=actor, fields=fields)
    return pdfs.render_document(company.tenant, title=title or template.name, text=text)


# ------------------------------------------------------------- sending

def request_wording(document, sender) -> tuple[str, str]:
    """The request's subject and words, `{SignLink}` where the link goes."""
    from apps.crm.services import templates

    who = (getattr(sender, "full_name", "") or "").strip() or document.tenant.name
    first = (document.signer.first_name or "").strip() or "there"
    subject = f"{document.title} from {document.tenant.name}, to sign"
    body = (f"Hi {first},\n\n"
            f"{who} has sent you {document.title} to read and sign.\n\n"
            f"Read and sign it here: {SIGN_LINK}\n\n"
            "The link is yours alone. It stops working once you sign or decline, "
            "and 30 days after it was sent.")
    return subject[:255], templates.with_signature(body, document.tenant, sender)


def _request_waiting(document) -> bool:
    message = document.request_message
    return message is not None and message.state in ("draft", "pending_approval", "approved")


@transaction.atomic
def queue_request(document, *, actor, role=None, mailbox=None):
    """The request into the Outbox, for approval. The document stays a draft
    until it is delivered."""
    from apps.crm.models import OutboxMessage
    from apps.crm.services import outbox

    if document.state != S.DRAFT:
        raise DocumentRefused("Only a draft is sent for signature.", 409)
    if _request_waiting(document):
        raise DocumentRefused("Its email is already in the Outbox, waiting for approval.", 409)
    subject, body = request_wording(document, actor)
    message = outbox.create_message(
        tenant=document.tenant, producer=OutboxMessage.Producer.SIGNATURE_REQUEST,
        to_contact=document.signer, to_address=document.signer_email,
        subject=subject, body_text=body, actor=actor, role=role, mailbox=mailbox,
        send_by=timezone.now() + timedelta(days=7),
        source_type="document", source_id=document.pk)
    document.request_message = message
    document.mailbox = message.mailbox
    document.save(update_fields=["request_message", "mailbox", "updated_at"])
    _audit(document, actor, "document.queued", {"outbox_message": str(message.pk)})
    return message


def _of_message(message):
    if message.source_type != "document" or message.source_id is None:
        return None
    return Document.all_objects.filter(pk=message.source_id,
                                       tenant_id=message.tenant_id).first()


def send_refusal(message) -> str:
    """Why a request may not go now, or "": its document voided, or past
    waiting."""
    document = _of_message(message)
    if document is None:
        return "This email's document is gone."
    if document.state not in (S.DRAFT,) + WAITING:
        return f"This document is {document.get_state_display().lower()}, so it is not sent."
    return ""


def delivery_text(message) -> tuple[str, str | None]:
    """`(text, html)` as the request goes: `{SignLink}` filled in with a link
    made now. Never stored. A body someone edited the link out of gets it
    back at the end."""
    from apps.crm.services.transport import TransportUnavailable

    document = _of_message(message)
    url = links.ensure(document) if document is not None else ""
    if not url:
        raise TransportUnavailable(send_refusal(message) or "No signing link could be made.")
    text = message.body_text or ""
    text = text.replace(SIGN_LINK, url) if SIGN_LINK in text else \
        f"{text.rstrip()}\n\nRead and sign it here: {url}"
    html = message.body_html or ""
    return text, (html.replace(SIGN_LINK, url) if html.strip() else None)


@transaction.atomic
def request_sent(message, *, actor=None):
    """Delivered: Sent, its 30 days started, and the "is sent a document"
    rules run."""
    document = _of_message(message)
    if document is None or document.state != S.DRAFT:
        return None
    now = timezone.now()
    document.state = S.SENT
    document.sent_at = now
    document.expires_at = now + EXPIRES_AFTER
    document.mailbox = message.mailbox or document.mailbox
    document.save(update_fields=["state", "sent_at", "expires_at", "mailbox", "updated_at"])
    _audit(document, actor, "document.sent", {"outbox_message": str(message.pk)})
    fire(document, "sent", actor=actor)
    return document


# ------------------------------------------------------------- the signer

def page_for(document) -> dict:
    """What the public page shows: the practice, the document, the consent."""
    return {
        "practice": document.tenant.name,
        "title": document.title,
        "signer_name": document.signer_name,
        "signer_email": document.signer_email,
        "state": document.state,
        "expires_at": document.expires_at.isoformat() if document.expires_at else None,
        "sha256": document.pdf_sha256,
        "consent_version": consent.CURRENT,
        "consent_text": consent.wording(practice=document.tenant.name,
                                        email=document.signer_email),
    }


@transaction.atomic
def viewed(document, *, ip=None, user_agent=""):
    """The first look: Viewed, and the sender told once."""
    if document.state != S.SENT:
        return document
    document.state = S.VIEWED
    document.viewed_at = timezone.now()
    document.save(update_fields=["state", "viewed_at", "updated_at"])
    _audit(document, None, "document.viewed", {"ip": ip or "", "user_agent": user_agent[:300]})
    _tell(document, "viewed", "A document was opened",
          f"{document.signer_name} opened {document.title}.")
    return document


def _drawn_png(data_url: str) -> bytes:
    from PIL import Image

    prefix = "data:image/png;base64,"
    if not (data_url or "").startswith(prefix):
        raise DocumentRefused("Draw your signature, or type it instead.")
    try:
        content = base64.b64decode(data_url[len(prefix):], validate=True)
    except (binascii.Error, ValueError):
        raise DocumentRefused("That drawing could not be read. Try again.") from None
    if len(content) > MAX_DRAWN_BYTES:
        raise DocumentRefused("That drawing is too large. Clear it and draw it again.")
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
            if image.format != "PNG":
                raise DocumentRefused("That drawing could not be read. Try again.")
    except DocumentRefused:
        raise
    except Exception:
        raise DocumentRefused("That drawing could not be read. Try again.") from None
    return content


def _signature(document, *, role, name, email, user=None, method, typed, drawn, agreed,
               ip=None, user_agent="") -> Signature:
    """The checks every signature passes, then the row."""
    from apps.tenancy import storage

    if agreed is not True:
        raise DocumentRefused("Tick the consent line to sign electronically.")
    if method == Signature.Method.TYPED:
        typed = " ".join((typed or "").split())[:200]
        if not typed:
            raise DocumentRefused("Type your name to sign.")
        png = None
    elif method == Signature.Method.DRAWN:
        typed, png = "", _drawn_png(drawn)
    else:
        raise DocumentRefused("Type or draw your signature.")
    # The PDF in front of them is the one recorded when the document was made.
    try:
        content = storage.read(document.pdf)
    except storage.StorageError as exc:
        raise DocumentRefused(f"The document could not be read just now: {exc}", 503) from None
    if pdfs.sha256(content) != document.pdf_sha256:
        raise HashMismatch(document, pdfs.sha256(content))
    return Signature.all_objects.create(
        tenant_id=document.tenant_id, document=document, role=role, name=name[:200],
        email=email, user=user, method=method, typed_text=typed, drawn_png=png,
        consent_version=consent.CURRENT,
        consent_text=(consent.countersign_wording(practice=document.tenant.name)
                      if role == Signature.Role.COUNTERSIGNER
                      else consent.wording(practice=document.tenant.name, email=email)),
        ip_address=ip or None, user_agent=(user_agent or "")[:500],
        signed_at=timezone.now(), pdf_sha256=document.pdf_sha256)


def sign(document, **kwargs):
    try:
        return _sign(document, **kwargs)
    except HashMismatch as refusal:
        _recorded(refusal)
        raise


@transaction.atomic
def _sign(document, *, method, typed="", drawn="", agreed=False, ip=None, user_agent=""):
    document = Document.all_objects.select_for_update().get(pk=document.pk)
    if document.state not in WAITING:
        raise DocumentRefused("This document is no longer waiting for a signature.", 409)
    signature = _signature(document, role=Signature.Role.SIGNER, name=document.signer_name,
                           email=document.signer_email, method=method, typed=typed,
                           drawn=drawn, agreed=agreed, ip=ip, user_agent=user_agent)
    from apps.tenancy import storage

    original = storage.read(document.pdf)
    signed = pdfs.appended(original, pdfs.signature_page(document, [signature]))
    document.signed_pdf = _store(document.tenant, signed, _filename(f"{document.title} signed"))
    document.state = S.SIGNED
    document.signed_at = signature.signed_at
    document.link_hash = ""
    document.save(update_fields=["signed_pdf", "state", "signed_at", "link_hash", "updated_at"])
    _audit(document, None, "document.signed", {"ip": ip or "", "method": method,
                                               "consent_version": signature.consent_version,
                                               "sha256": signature.pdf_sha256})
    _tell(document, "signed", "A document was signed",
          f"{document.signer_name} signed {document.title}.")
    _tell(document, "countersign", "Countersign needed",
          f"{document.title} is signed by {document.signer_name} and needs your countersignature.")
    fire(document, "signed")
    return document


@transaction.atomic
def decline(document, *, reason: str, ip=None, user_agent=""):
    document = Document.all_objects.select_for_update().get(pk=document.pk)
    if document.state not in WAITING:
        raise DocumentRefused("This document is no longer waiting for a signature.", 409)
    reason = (reason or "").strip()
    if not reason:
        raise DocumentRefused("Say why you are declining, so the practice knows.")
    document.state = S.DECLINED
    document.declined_at = timezone.now()
    document.decline_reason = reason[:2000]
    document.link_hash = ""
    document.save(update_fields=["state", "declined_at", "decline_reason", "link_hash",
                                 "updated_at"])
    _audit(document, None, "document.declined", {"ip": ip or "", "user_agent": user_agent[:300]})
    _tell(document, "declined", "A document was declined",
          f"{document.signer_name} declined {document.title}: {reason[:200]}")
    return document


# ------------------------------------------------------------- the practice

def countersign(document, **kwargs):
    try:
        return _countersign(document, **kwargs)
    except HashMismatch as refusal:
        _recorded(refusal)
        raise


@transaction.atomic
def _countersign(document, *, actor, method, typed="", drawn="", agreed=False, ip=None,
                 user_agent=""):
    from apps.tenancy import storage

    document = Document.all_objects.select_for_update().get(pk=document.pk)
    if document.state != S.SIGNED:
        raise DocumentRefused("Only a document the client has signed is countersigned.", 409)
    name = (getattr(actor, "full_name", "") or "").strip() or actor.email
    signature = _signature(document, role=Signature.Role.COUNTERSIGNER, name=name,
                           email=actor.email, user=actor, method=method, typed=typed,
                           drawn=drawn, agreed=agreed, ip=ip, user_agent=user_agent)
    both = list(document.signatures.order_by("signed_at"))
    final = pdfs.appended(storage.read(document.pdf), pdfs.signature_page(document, both))
    document.final_pdf = _store(document.tenant, final, _filename(f"{document.title} signed"))
    document.final_sha256 = pdfs.sha256(final)
    document.state = S.COUNTERSIGNED
    document.countersigned_at = signature.signed_at
    document.countersigned_by = actor
    document.save(update_fields=["final_pdf", "final_sha256", "state", "countersigned_at",
                                 "countersigned_by", "updated_at"])
    _audit(document, actor, "document.countersigned", {"sha256": document.final_sha256})
    send_copy(document, actor=actor)
    document.state = S.COMPLETE
    document.completed_at = timezone.now()
    document.save(update_fields=["state", "completed_at", "updated_at"])
    _audit(document, actor, "document.completed", {})
    return document


def send_copy(document, *, actor):
    """The final PDF to the signer, and to whoever countersigned."""
    from apps.crm.models import OutboxMessage
    from apps.crm.services import outbox

    first = (document.signer.first_name or "").strip() or "there"
    body = (f"Hi {first},\n\n"
            f"{document.title} is now signed by you and countersigned by "
            f"{document.countersigned_by.full_name or document.tenant.name}. The signed "
            "copy is attached, with the signature page at the end.\n\n"
            f"Thank you,\n{document.tenant.name}")
    also = "" if (actor.email or "").lower() == document.signer_email.lower() else actor.email
    return outbox.create_message(
        tenant=document.tenant, producer=OutboxMessage.Producer.SIGNED_COPY,
        to_contact=document.signer, to_address=document.signer_email,
        also_to_address=also, subject=f"Signed: {document.title}"[:255], body_text=body,
        actor=actor, mailbox=document.mailbox,
        attachments=[(document.final_pdf, _filename(f"{document.title} signed"))],
        source_type="document", source_id=document.pk)


@transaction.atomic
def void(document, *, actor, reason=""):
    from apps.crm.services import outbox

    document = Document.all_objects.select_for_update().get(pk=document.pk)
    if document.state not in VOIDABLE:
        raise DocumentRefused(f"A {document.get_state_display().lower()} document can't be "
                              "voided.", 409)
    message = document.request_message
    if message is not None and message.state in ("draft", "pending_approval"):
        outbox.reject(message, actor=actor)
    document.state = S.VOID
    document.voided_at = timezone.now()
    document.voided_by = actor
    document.void_reason = (reason or "").strip()[:2000]
    document.link_hash = ""
    document.save(update_fields=["state", "voided_at", "voided_by", "void_reason", "link_hash",
                                 "updated_at"])
    _audit(document, actor, "document.voided", {"reason": document.void_reason})
    return document


def demo_link(document) -> str:
    """The demo's "Open the signing page": the document's own link, for a
    visitor who is both sides. Nowhere else."""
    from config import environment

    if not environment.is_demo():
        raise DocumentRefused("Only on the demo.", 404)
    if document.state not in WAITING:
        raise DocumentRefused("This document is not waiting for a signature.", 409)
    return links.ensure(document)


# ------------------------------------------------------------- every day

def daily(tenant, now=None) -> dict:
    """Expire what is 30 days unsigned; remind once at 7 days."""
    now = now or timezone.now()
    expired = reminded = 0
    for document in Document.all_objects.filter(tenant=tenant, state__in=WAITING,
                                                expires_at__lte=now):
        Document.all_objects.filter(pk=document.pk).update(
            state=S.EXPIRED, link_hash="", updated_at=now)
        _audit(document, None, "document.expired", {})
        expired += 1
    for document in Document.all_objects.filter(
            tenant=tenant, state__in=WAITING, reminded_at__isnull=True,
            sent_at__lte=now - REMIND_AFTER, expires_at__gt=now).select_related(
            "signer", "tenant", "mailbox", "created_by"):
        if remind(document, now=now):
            reminded += 1
    return {"expired": expired, "reminded": reminded}


def remind(document, *, now=None):
    """The one reminder: the same link, fixed words, straight out."""
    from apps.crm.models import OutboxMessage
    from apps.crm.services import outbox
    from apps.tenancy.context import tenant_context

    url = links.ensure(document)
    if not url:
        return None
    first = (document.signer.first_name or "").strip() or "there"
    expires = timezone.localtime(document.expires_at).date() if document.expires_at else None
    words = (f"Hi {first},\n\n"
             f"A reminder that {document.title} from {document.tenant.name} is waiting for "
             f"your signature{f' until {long_date(expires)}' if expires else ''}.\n\n")
    stored = words + "[The signing link was in this email.]"
    sent = words + f"Read and sign it here: {url}"
    with tenant_context(document.tenant_id):
        message = outbox.create_message(
            tenant=document.tenant, producer=OutboxMessage.Producer.SIGNATURE_REMINDER,
            to_contact=document.signer, to_address=document.signer_email,
            subject=f"Reminder: {document.title} to sign"[:255], body_text=stored,
            deliver_body_text=sent, mailbox=document.mailbox, actor=document.created_by,
            source_type="document", source_id=document.pk)
    Document.all_objects.filter(pk=document.pk).update(reminded_at=now or timezone.now())
    _audit(document, None, "document.reminded", {"outbox_message": str(message.pk)})
    return message


# ------------------------------------------------------------- stage rules

def fire(document, trigger, *, actor=None) -> list:
    """The "is sent a document" or "signs a document" rules, for the signer.
    A rule's move only goes forward: someone already past the stage it names
    (a client sent an engagement letter) stays where they are."""
    from apps.crm.models import StageAutomation
    from apps.crm.services import pipeline, stage_rules

    contact = document.signer
    results = []
    for rule in (StageAutomation.all_objects.filter(tenant_id=document.tenant_id,
                                                    is_active=True, trigger=trigger)
                 .select_related("pipeline", "move_to_stage", "document_template",
                                 "email_template", "task_assignee")
                 .order_by("position", "created_at")):
        if rule.action_type == StageAutomation.Action.MOVE_STAGE and rule.move_to_stage:
            here = pipeline.position_for(contact, rule.pipeline)
            if here is not None and here.stage.position >= rule.move_to_stage.position:
                continue
        if rule.action_type == StageAutomation.Action.SEND_SIGNATURE and trigger == "sent":
            continue                          # never a loop of documents
        results.append(stage_rules.run(rule, contact, actor=actor))
    return results


def from_rule(contact, rule, *, actor=None):
    """A stage rule's "Send a document for signature": the template's document
    for the contact, its fields blank to fill in on the company card, and its
    email in the Outbox for approval."""
    template = rule.document_template
    why = ""
    if template is None:
        why = "the rule has no document template"
    elif not contact.company_id:
        why = "the contact has no company"
    elif not (contact.primary_email or "").strip():
        why = "the contact has no email address"
    if why:
        AuditEvent.all_objects.create(
            tenant_id=contact.tenant_id, actor=actor, verb="stage_rule.document_skipped",
            target_type="contact", target_id=contact.pk,
            payload={"rule": str(rule.pk), "why": why})
        return None
    document = from_template(contact.company, template, contact, fields={}, actor=actor,
                             rule=rule)
    queue_request(document, actor=actor)
    return document


# ------------------------------------------------------------- the welcome letter

def welcome_values(contact) -> dict:
    """{Scope}, {Fee}, {Term} and {StartDate} from the company's latest signed
    document, and {Goals}: its goals, one a line."""
    from apps.work.models import Goal

    out = {"Scope": "", "Fee": "", "Term": "", "StartDate": "", "Goals": ""}
    company_id = getattr(contact, "company_id", None) if contact is not None else None
    if not company_id:
        return out
    latest = (Document.all_objects.filter(company_id=company_id, state__in=SIGNED_STATES,
                                          source=Document.Source.TEMPLATE)
              .order_by("-signed_at").first())
    if latest is not None:
        for name, _ in DOC_FIELDS:
            value = (latest.fields or {}).get(name, "") or ""
            out[name] = _start_date(value) if name == "StartDate" else value.strip()
    goals = Goal.all_objects.filter(client_company_id=company_id, deleted_at__isnull=True) \
        .order_by("created_at").values_list("title", flat=True)
    out["Goals"] = "\n".join(f"- {title}" for title in goals)
    return out


# ------------------------------------------------------------- telling

def _audit(document, actor, verb, payload):
    AuditEvent.all_objects.create(
        tenant_id=document.tenant_id, actor=actor, verb=verb, target_type="document",
        target_id=document.pk, payload={"company": str(document.company_id), **payload})


def _tell(document, what, title, text):
    """A notice, and a push, to whoever sent it (else the practice owner)."""
    from apps.notify.models import Kind
    from apps.notify.service import tell
    from apps.tenancy.models import Membership, Role

    recipient = document.created_by_id
    if recipient is None or not Membership.all_objects.filter(
            tenant_id=document.tenant_id, user_id=recipient, revoked_at__isnull=True,
            role__in=(Role.FF, Role.CF)).exists():
        owner = Membership.all_objects.filter(tenant_id=document.tenant_id, role=Role.FF,
                                              revoked_at__isnull=True).order_by("created_at") \
            .first()
        recipient = owner.user_id if owner else None
    tell(tenant_id=document.tenant_id, recipient_id=recipient, kind=Kind.DOCUMENT,
         title=title, text=text, url=f"/companies/{document.company_id}?documents={document.pk}",
         source_type=f"document.{what}", source_id=document.pk)
