"""How the app's email looks — one place, used by every send and every preview.

Two layouts, both table-based with inline CSS only, because Gmail (web and
mobile) strips `<style>` blocks and most clients ignore stylesheets:

- **base** — the practice's logo on a white header (its name when there is no
  logo), a bar in the header colour and an accent rule beneath, a white 680px
  body at 16px, and a small footer naming the practice. Used for
  everything the app itself sends: digests, client-activity notices, sign-in and
  PIN links.
- **personal** — clean typography, no header block, no footer. Used for mail a
  person sends from their own address (referral touches and onboarding, manual
  and stage-rule drafts), because an over-designed email from a person reads as
  marketing. Its one branded element is the sign-off: when the draft ends with
  a staff member's signature, it is set beside the practice's mark.

Branding comes from the tenant row (`email_display_name`, `email_header_color`,
`email_accent_color`, `email_logo`), with Executives Now's values as the defaults, so a V1
tenant gets its own look without a template change.

Every send keeps a text/plain part built from the same content as the HTML.
`for_delivery` is the single function that decides what leaves: `outbox._deliver`
calls it, and so does every preview, so a preview is exactly the send.
"""

from __future__ import annotations

import base64
import re
import struct
from dataclasses import dataclass

from django.template.loader import render_to_string
from django.utils.html import escape

FONT_STACK = ("-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, "
              "sans-serif")
#: White-label: the product never brands a tenant's mail. A practice that has
#: set nothing gets its own name over neutral greys — never the product owner's
#: name or palette, which live on the Executives Now tenant row like any other
#: tenant's do.
DEFAULT_DISPLAY_NAME = ""
DEFAULT_HEADER_COLOR = "#1F2933"
DEFAULT_ACCENT_COLOR = "#52606D"
TEXT_COLOR = "#333333"
MUTED_COLOR = "#6D6E71"
FAINT_COLOR = "#939598"

#: Present on every finished document, so a stored document is never wrapped twice.
LAYOUT_MARKER = "data-enhq-email"

#: Sent from a person's own address: the light layout.
PERSONAL_PRODUCERS = frozenset({"referral_touch", "referral_onboarding", "manual", "stage_rule"})

#: The logo travels as an inline image part referenced by this Content-ID. Gmail
#: blocks `data:` images, and a laptop URL is unreachable from Gmail's image
#: proxy, so an attached part is the one form every client shows in Beta.
LOGO_CID = "enhq-logo"
LOGO_MAX_WIDTH = 260    # display size; a logo supplied at 2x stays sharp on retina
LOGO_MAX_HEIGHT = 84
LOGO_MAX_BYTES = 500 * 1024
#: The square mark beside a personal sign-off.
MARK_CID = "enhq-mark"
MARK_MAX = 56

#: (Content-ID, tenant field, the markup that shows it). The mark's pattern takes
#: its whole table cell, so an unreadable mark leaves no empty column behind.
_SLOTS = (
    (LOGO_CID, "email_logo", re.compile(r"<img\b[^>]*\bdata-enhq-logo\b[^>]*>")),
    (MARK_CID, "email_mark", re.compile(r"<td\b[^>]*\bdata-enhq-mark\b[^>]*>.*?</td>", re.S)),
)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

_URL = re.compile(r"https?://[^\s<>\"']+")
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


@dataclass(frozen=True)
class Logo:
    width: int
    height: int


@dataclass(frozen=True)
class Branding:
    display_name: str
    practice_name: str
    header_color: str
    accent_color: str
    logo: Logo | None = None
    mark: Logo | None = None


def branding(tenant) -> Branding:
    def colour(value, default):
        return value if value and _HEX.match(value) else default

    return Branding(
        display_name=(getattr(tenant, "email_display_name", "") or getattr(tenant, "name", "")
                      or DEFAULT_DISPLAY_NAME).strip(),
        practice_name=(getattr(tenant, "name", "") or getattr(tenant, "email_display_name", "")
                       or DEFAULT_DISPLAY_NAME).strip(),
        header_color=colour(getattr(tenant, "email_header_color", ""), DEFAULT_HEADER_COLOR),
        accent_color=colour(getattr(tenant, "email_accent_color", ""), DEFAULT_ACCENT_COLOR),
        logo=_shown_size(tenant, "email_logo"),
        mark=_shown_size(tenant, "email_mark"),
    )


def _shown_size(tenant, field) -> Logo | None:
    width = getattr(tenant, f"{field}_width", 0) or 0
    height = getattr(tenant, f"{field}_height", 0) or 0
    if getattr(tenant, f"{field}_id", None) and width and height:
        return Logo(width=width, height=height)
    return None


def template_context(tenant, **extra):
    brand = branding(tenant)
    return {"brand": brand, "font": FONT_STACK, "text_color": TEXT_COLOR,
            "muted": MUTED_COLOR, "faint": FAINT_COLOR, "accent": brand.accent_color,
            "logo_cid": LOGO_CID, **extra}


def document(tenant, *, content_html, subject="", preheader="", footer_link=None,
             personal=False) -> str:
    """A finished HTML email around already-safe content.

    `footer_link` is `(label, url)` — the digest's "change how often you hear from
    us" control, small and unobtrusive in the footer.
    """
    link = {"label": footer_link[0], "url": footer_link[1]} if footer_link else None
    return render_to_string(
        "email/personal.html" if personal else "email/base.html",
        template_context(tenant, content=content_html, subject=subject, preheader=preheader,
                         footer_link=link),
    )


def is_document(value) -> bool:
    return LAYOUT_MARKER in (value or "")


def link(url, label=None, *, accent) -> str:
    return (f'<a href="{escape(url)}" style="color:{accent};text-decoration:underline;">'
            f"{escape(label if label is not None else url)}</a>")


def text_to_html(text, *, accent) -> str:
    """Plain text as paragraphs: escaped, line breaks kept, URLs as accent links."""
    paragraphs = [p for p in re.split(r"\n\s*\n", (text or "").strip()) if p.strip()]
    out = []
    for paragraph in paragraphs:
        body = linked(paragraph, accent=accent).replace("\n", "<br>")
        out.append(f'<p style="margin:0 0 16px;">{body}</p>')
    return "".join(out)


def linked(value, *, accent, emails=False) -> str:
    """Escaped text with URLs (and, when asked, email addresses) as accent links."""
    pattern = re.compile(f"{_URL.pattern}|{_EMAIL.pattern}") if emails else _URL
    pieces, last = [], 0
    for match in pattern.finditer(value):
        pieces.append(escape(value[last:match.start()]))
        found = match.group(0)
        href = found if found.startswith("http") else f"mailto:{found}"
        pieces.append(link(href, found, accent=accent))
        last = match.end()
    pieces.append(escape(value[last:]))
    return "".join(pieces)


def style_links(fragment, *, accent) -> str:
    """An edited Outbox body is HTML from the editor: give its links the accent
    colour unless they already carry their own style."""
    return re.sub(r"<a(?![^>]*\bstyle=)(?=[\s>])",
                  f'<a style="color:{accent};text-decoration:underline;"', fragment or "")


def for_delivery(message, *, body_text=None, body_html=None) -> tuple[str, str]:
    """`(html, text)` exactly as they are sent. Previews call this too.

    A stored finished document (digests, notices, sign-in links) goes out as it
    is. Anything else — a draft a person wrote or edited — is wrapped here, in
    the layout its producer calls for, so the Outbox editor only ever holds the
    words and never the layout.
    """
    text = message.body_text if body_text is None else body_text
    html = message.body_html if body_html is None else body_html
    if is_document(html):
        return html, text
    accent = branding(message.tenant).accent_color
    personal = message.producer in PERSONAL_PRODUCERS
    if (html or "").strip():
        content = style_links(html, accent=accent)
    elif personal:
        words, signed = split_signature(message.tenant, text)
        content = text_to_html(words, accent=accent) + (
            signature_block(message.tenant, signed) if signed else "")
    else:
        content = text_to_html(text, accent=accent)
    return document(message.tenant, content_html=content, subject=message.subject,
                    personal=personal), text


# ------------------------------------------------------------------ the sign-off

def split_signature(tenant, text) -> tuple[str, str]:
    """`(words, signature)` when the text ends with a staff member's sign-off,
    else `(text, "")`. Exact match only: a sign-off someone edited or removed
    is left as they wrote it, never guessed at."""
    from apps.crm.services import sender as sender_service

    body = (text or "").replace("\r\n", "\n").rstrip()
    for signature in sender_service.signature_texts(tenant):
        if body.endswith(signature) and (
            len(body) == len(signature) or body[-len(signature) - 1] == "\n"
        ):
            return body[:-len(signature)].rstrip(), signature
    return text, ""


def signature_block(tenant, text) -> str:
    """The sign-off on mail from a person: the practice's mark beside the name
    and contact lines, set off by an accent rule. Its words are exactly the
    signature in the text part; only the presentation differs."""
    brand = branding(tenant)
    lines = [line.strip() for line in (text or "").strip().split("\n") if line.strip()]
    if not lines:
        return ""
    details = "".join(f"<br>{linked(line, accent=brand.accent_color, emails=True)}"
                      for line in lines[1:])
    mark = ""
    if brand.mark:
        w, h = brand.mark.width, brand.mark.height
        mark = (f'<td data-enhq-mark valign="top" width="{w}" style="padding:2px 14px 0 0;">'
                f'<img src="cid:{MARK_CID}" width="{w}" height="{h}" alt="" '
                f'style="display:block;border:0;outline:none;text-decoration:none;'
                f'width:{w}px;height:{h}px;"></td>')
    return (
        '<table role="presentation" data-enhq-signature cellpadding="0" cellspacing="0" '
        'border="0" style="margin:8px 0 0;border-collapse:collapse;">'
        f'<tr>{mark}<td valign="top" style="padding:0 0 0 14px;'
        f'border-left:3px solid {brand.accent_color};font-family:{FONT_STACK};'
        f'font-size:14px;line-height:1.5;color:{MUTED_COLOR};">'
        f'<strong style="font-size:15px;color:{brand.header_color};">{escape(lines[0])}</strong>'
        f"{details}</td></tr></table>"
    )


# --------------------------------------------------------------------- the logo

def image_size(content: bytes) -> tuple[str, int, int]:
    """`(content_type, width, height)` of a PNG or JPEG, read from its header.

    Raises ValueError for anything else. Enough to size the `<img>` (Outlook
    ignores CSS sizes and needs the attributes) without adding an imaging library.
    """
    if content[:8] == b"\x89PNG\r\n\x1a\n" and content[12:16] == b"IHDR":
        width, height = struct.unpack(">II", content[16:24])
        return "image/png", width, height
    if content[:2] == b"\xff\xd8":
        i = 2
        while i + 9 <= len(content):
            if content[i] != 0xFF:
                break
            marker = content[i + 1]
            if marker == 0xFF:
                i += 1
                continue
            if marker in (0x01, *range(0xD0, 0xD9)):
                i += 2
                continue
            (length,) = struct.unpack(">H", content[i + 2:i + 4])
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                height, width = struct.unpack(">HH", content[i + 5:i + 9])
                return "image/jpeg", width, height
            i += 2 + length
        raise ValueError("The JPEG's size could not be read.")
    raise ValueError("The logo must be a PNG or a JPEG.")


def logo_display_size(width: int, height: int, *, max_width=LOGO_MAX_WIDTH,
                      max_height=LOGO_MAX_HEIGHT) -> tuple[int, int]:
    """Shrink to fit the box, never enlarge."""
    if width <= 0 or height <= 0:
        raise ValueError("The image has no size.")
    scale = min(1.0, max_width / width, max_height / height)
    return max(1, round(width * scale)), max(1, round(height * scale))


def with_logo(html, tenant, *, as_data_uri=False) -> tuple[str, list[tuple]]:
    """Resolve the header logo and the sign-off mark for a send or a preview.

    Returns the HTML and the inline parts to send with it, as
    `(cid, bytes, content_type, filename)`. A preview gets the same markup with
    the images embedded, because a browser cannot resolve `cid:`.

    **An image that cannot be read never stops a send.** Unlike an attachment
    the message says it carries, these are decoration — and the logo rides on
    sign-in links, where failing the send locks a client out. The header falls
    back to the practice's name; the sign-off simply loses its mark.
    """
    from apps.tenancy import storage

    inline = []
    for cid, field, tag in _SLOTS:
        if not tag.search(html or ""):
            continue
        stored = getattr(tenant, field) if getattr(tenant, f"{field}_id", None) else None
        content = None
        if stored is not None:
            try:
                content = storage.read(stored)
            except storage.StorageError:
                content = None
        if not content:
            fallback = str(escape(branding(tenant).display_name)) if field == "email_logo" else ""
            html = tag.sub(lambda _match, text=fallback: text, html)
            continue
        content_type = stored.content_type or "image/png"
        if as_data_uri:
            uri = f"data:{content_type};base64,{base64.b64encode(content).decode()}"
            html = html.replace(f'src="cid:{cid}"', f'src="{uri}"')
        else:
            extension = "jpg" if content_type == "image/jpeg" else "png"
            inline.append((cid, content, content_type,
                           f"{field.removeprefix('email_')}.{extension}"))
    return html, inline


# ------------------------------------------------------------ one-button emails

def action_link_email(tenant, *, subject, heading, paragraphs, button_label, url, expiry,
                      closing="", redacted_note="") -> tuple[str, str]:
    """Magic links and PIN resets: one prominent accent button, the plain URL
    beneath it for mail that blocks buttons, and the expiry said plainly.

    With `url=None` it renders the STORED copy: the button and the URL are
    replaced by `redacted_note`, so no row ever holds a working credential
    (assumption C3). Both copies come from this one function.
    """
    ctx = template_context(tenant, heading=heading, paragraphs=paragraphs,
                           button_label=button_label, url=url, expiry=expiry,
                           closing=closing, redacted_note=redacted_note)
    content = render_to_string("email/action_link_content.html", ctx)
    lines = [heading, "", *[p for para in paragraphs for p in (para, "")]]
    lines += [f"{button_label}: {url}" if url else redacted_note, "", expiry]
    if closing:
        lines += ["", closing]
    text = "\n".join(lines).strip()
    return document(tenant, content_html=content, subject=subject, preheader=heading), text
