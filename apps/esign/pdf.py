"""The document's PDF, and the signature page appended to it.

- A template's document is its words merged and laid out on A4-ish Letter
  pages: the practice's name, the title, the body ("# " lines are headings).
- An uploaded PDF is kept exactly as uploaded.
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

from django.utils import timezone

FONTS = Path(__file__).resolve().parent / "fonts"
TEXT_FONTS = Path(__file__).resolve().parent.parent / "strategy" / "fonts"
SCRIPT_FONT = FONTS / "DancingScript-Medium.ttf"
#: The largest PDF an upload may be.
MAX_UPLOAD_BYTES = 15 * 1024 * 1024


class PdfRefused(ValueError):
    pass


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _faces() -> str:
    return "\n".join([
        f'@font-face {{ font-family: "Lato"; font-weight: 400; '
        f'src: url("{(TEXT_FONTS / "Lato-Regular.ttf").as_uri()}"); }}',
        f'@font-face {{ font-family: "Lato"; font-weight: 700; '
        f'src: url("{(TEXT_FONTS / "Lato-Bold.ttf").as_uri()}"); }}',
        f'@font-face {{ font-family: "Dancing Script"; font-weight: 400; '
        f'src: url("{SCRIPT_FONT.as_uri()}"); }}',
    ])


_STYLE = """
@page { size: Letter; margin: 22mm 20mm 20mm 20mm;
        @bottom-right { content: %(footer)s;
                        font: 9pt "Lato", sans-serif; color: #6D6E71; } }
body { font: 10.5pt/1.5 "Lato", sans-serif; color: #1f2933; }
.practice { font-size: 9.5pt; color: #6D6E71; letter-spacing: .04em; text-transform: uppercase; }
h1 { font-size: 20pt; margin: 4mm 0 6mm; color: %(accent)s; }
h2 { font-size: 12pt; margin: 6mm 0 1.5mm; color: %(accent)s; }
p { margin: 0 0 3mm; }
table { width: 100%%; border-collapse: collapse; margin-top: 4mm; }
td { vertical-align: top; padding: 2mm 0; }
.sig { border: 1px solid #d5d9de; border-radius: 3mm; padding: 4mm 5mm; margin: 0 0 5mm;
       page-break-inside: avoid; }
.sig .role { font-size: 9pt; color: #6D6E71; text-transform: uppercase; letter-spacing: .05em; }
.sig .mark { font-family: "Dancing Script"; font-size: 26pt; line-height: 1.2; color: #0A3A65;
             border-bottom: 1px solid #939598; padding: 1mm 0 1mm; margin: 2mm 0 2mm;
             min-height: 14mm; }
.sig .mark img { height: 16mm; }
.facts { font-size: 9pt; color: #374151; }
.facts td { padding: .5mm 0; }
.facts td:first-child { width: 34mm; color: #6D6E71; }
.hash { font-family: "Lato"; font-size: 8pt; word-break: break-all; }
"""


def _accent(tenant) -> str:
    """The practice's header color, as its emails use (Settings → Branding)."""
    from apps.crm.services.email_layout import branding

    return branding(tenant).header_color


def _page(tenant, content: str, *, footer: str = 'counter(page) " of " counter(pages)') -> str:
    style = _STYLE % {"accent": _accent(tenant), "footer": footer}
    return (f"<!doctype html><html><head><meta charset='utf-8'><style>{_faces()}"
            f"{style}</style></head><body>{content}</body></html>")


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


def render_document(tenant, *, title: str, text: str) -> bytes:
    from weasyprint import HTML

    content = (f"<div class='practice'>{escape(tenant.name)}</div>"
               f"<h1>{escape(title)}</h1>{body_html(text)}")
    return HTML(string=_page(tenant, content)).write_pdf()


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
    """The page appended to the PDF: one block per signature."""
    from weasyprint import HTML

    from apps.esign.models import Signature

    blocks = []
    for sig in signatures:
        if sig.method == Signature.Method.DRAWN and sig.drawn_png:
            png = base64.b64encode(bytes(sig.drawn_png)).decode()
            mark = f"<img src='data:image/png;base64,{png}' alt=''>"
        else:
            mark = escape(sig.typed_text or sig.name)
        rows = [("Name", escape(sig.name)), ("Email", escape(sig.email)),
                ("Signed", _when(sig.signed_at)),
                ("IP address", escape(sig.ip_address or "not recorded")),
                ("Signature", "Typed" if sig.method == Signature.Method.TYPED else "Drawn"),
                ("Consent", f"Version {escape(sig.consent_version)}, ticked before signing"),
                ("Document hash", f"<span class='hash'>SHA-256 {escape(sig.pdf_sha256)}</span>")]
        facts = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in rows)
        blocks.append(f"<div class='sig'><div class='role'>{escape(sig.get_role_display())}"
                      f"</div><div class='mark'>{mark}</div>"
                      f"<table class='facts'>{facts}</table></div>")
    content = (f"<div class='practice'>{escape(document.tenant.name)}</div>"
               f"<h1>Signatures</h1>"
               f"<p>{escape(document.title)}, sent to {escape(document.signer_name)} "
               f"({escape(document.signer_email)}). Signed electronically; the hash below "
               f"is of the PDF before this page, as each person saw it.</p>"
               + "".join(blocks))
    # Rendered on its own and put after the last page, so it does not count
    # itself as "1 of 1": it says what it is.
    return HTML(string=_page(document.tenant, content,
                             footer='"Signature page"')).write_pdf()


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
