"""The document's PDF, and the signature page appended to it.

- A template's document is its words merged and laid out on Letter pages on
  the practice's letterhead, the strategy map PDF's (`templates/esign/pdf.html`):
  its mark or logo, colors, name and footer on every page, its margins and
  type ("# " lines are headings). Rendered and hashed once, when it is made,
  so a later change to Branding never alters one already made.
- An uploaded PDF is kept exactly as uploaded; only its signature page wears
  the letterhead.
- **The signature page** goes after the last page: each signature's name,
  the signature itself (a typed one in the cursive face, embedded; a drawn
  one as drawn), the time, the email, the IP address, the consent version,
  and the SHA-256 of the PDF they signed. Signing appends it with the
  signer's; countersigning makes it again with both, on the PDF as sent.

Fonts are bundled and OFL (licences beside them), so nothing is fetched.
"""

from __future__ import annotations

import base64
import hashlib
import io
from datetime import timezone as dt_timezone
from html import escape
from pathlib import Path

from django.template.loader import render_to_string
from django.utils import timezone

FONTS = Path(__file__).resolve().parent / "fonts"
SCRIPT_FONT = FONTS / "DancingScript-Medium.ttf"
#: The largest PDF an upload may be.
MAX_UPLOAD_BYTES = 15 * 1024 * 1024


class PdfRefused(ValueError):
    pass


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _render(company, *, prepared_by, day, **context) -> bytes:
    """The letterhead around `context`, as `apps/strategy/pdf.py` builds its
    own, with the same images and bundled faces."""
    from weasyprint import HTML

    from apps.crm.services.email_layout import branding
    from apps.strategy import document as strategy_document
    from apps.strategy import pdf as strategy_pdf

    tenant = company.tenant
    brand = branding(tenant)
    mark = strategy_pdf._image(tenant.email_mark) if tenant.email_mark_id else ""
    html = render_to_string("esign/pdf.html", {
        "brand": brand, "practice": brand.display_name or brand.practice_name,
        "company": company.name, "fractional": prepared_by,
        "mark_src": mark,
        "logo_src": ("" if mark or not tenant.email_logo_id
                     else strategy_pdf._image(tenant.email_logo)),
        "dateline": strategy_document.long_date(day),
        "font_faces": strategy_pdf.font_faces(), "script_font": SCRIPT_FONT.as_uri(),
        **context})
    return HTML(string=html, base_url=strategy_pdf._BASE).write_pdf()


def _name_of(person) -> str:
    return (getattr(person, "full_name", "") or "").strip()


def body_html(text: str) -> str:
    """Merged plain text as paragraphs; a line starting with "# " is a heading."""
    out, para = [], []

    def flush():
        if para:
            out.append("<p>" + "<br>".join(escape(line) for line in para) + "</p>")
            para.clear()

    for line in (text or "").split("\n"):
        if line.startswith("# "):
            flush()
            out.append(f"<h2>{escape(line[2:].strip())}</h2>")
        elif not line.strip():
            flush()
        else:
            para.append(line)
    flush()
    return "\n".join(out)


def render_document(company, *, title: str, text: str, actor=None) -> bytes:
    return _render(company, prepared_by=_name_of(actor), day=timezone.localdate(),
                   title=title, body=body_html(text))


def check_upload(content: bytes) -> int:
    """The page count of an uploaded PDF, or a refusal saying why not."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    if not content:
        raise PdfRefused("The file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise PdfRefused("The file is larger than 15 MB.")
    if not content.startswith(b"%PDF"):
        raise PdfRefused("That file is not a PDF.")
    try:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            raise PdfRefused("That PDF is password-protected. Upload one without a password.")
        pages = len(reader.pages)
    except PdfReadError as exc:
        raise PdfRefused("That PDF could not be read.") from exc
    if pages == 0:
        raise PdfRefused("That PDF has no pages.")
    return pages


def _when(moment) -> str:
    utc = moment.astimezone(dt_timezone.utc)
    return utc.strftime("%B %-d, %Y at %H:%M:%S UTC")


def signature_page(document, signatures) -> bytes:
    """The page appended to the PDF: one block per signature, on the
    letterhead whatever the PDF before it is. Rendered on its own and put
    after the last page, so it does not count itself as "1 of 1": it says
    what it is."""
    from apps.esign.models import Signature

    blocks = []
    for sig in signatures:
        drawn = ""
        if sig.method == Signature.Method.DRAWN and sig.drawn_png:
            drawn = f"data:image/png;base64,{base64.b64encode(bytes(sig.drawn_png)).decode()}"
        blocks.append({
            "role": sig.get_role_display(), "drawn": drawn,
            "typed": sig.typed_text or sig.name, "hash": sig.pdf_sha256,
            "rows": [("Name", sig.name), ("Email", sig.email),
                     ("Signed", _when(sig.signed_at)),
                     ("IP address", sig.ip_address or "not recorded"),
                     ("Signature",
                      "Typed" if sig.method == Signature.Method.TYPED else "Drawn"),
                     ("Consent", f"Version {sig.consent_version}, ticked before signing")]})
    return _render(document.company, prepared_by=_name_of(document.created_by),
                   day=timezone.localdate(max(s.signed_at for s in signatures)),
                   signature_page=True, signatures=blocks, title=document.title,
                   signer_name=document.signer_name, signer_email=document.signer_email)


def appended(original: bytes, page: bytes) -> bytes:
    """The original PDF with the signature page after its last page."""
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(original)))
    writer.append(PdfReader(io.BytesIO(page)))
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def now():
    return timezone.now()
