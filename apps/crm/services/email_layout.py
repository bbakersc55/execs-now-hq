"""How the app's email looks — one place, used by every send and every preview.

Two layouts, both table-based with inline CSS only, because Gmail (web and
mobile) strips `<style>` blocks and most clients ignore stylesheets:

- **base** — the practice's header wordmark on its header colour, an accent rule,
  a white 600px body at 16px, and a small footer naming the practice. Used for
  everything the app itself sends: digests, client-activity notices, sign-in and
  PIN links.
- **personal** — clean typography, no header block, no footer. Used for mail a
  person sends from their own address (referral touches and onboarding, manual
  and stage-rule drafts), because an over-designed email from a person reads as
  marketing.

Branding comes from the tenant row (`email_display_name`, `email_header_color`,
`email_accent_color`), with Executives Now's values as the defaults, so a V1
tenant gets its own look without a template change.

Every send keeps a text/plain part built from the same content as the HTML.
`for_delivery` is the single function that decides what leaves: `outbox._deliver`
calls it, and so does every preview, so a preview is exactly the send.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from django.template.loader import render_to_string
from django.utils.html import escape

FONT_STACK = ("-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, "
              "sans-serif")
DEFAULT_DISPLAY_NAME = "Executives Now"
DEFAULT_HEADER_COLOR = "#0A3A65"
DEFAULT_ACCENT_COLOR = "#F58220"
TEXT_COLOR = "#333333"
MUTED_COLOR = "#6D6E71"
FAINT_COLOR = "#939598"

#: Present on every finished document, so a stored document is never wrapped twice.
LAYOUT_MARKER = "data-enhq-email"

#: Sent from a person's own address: the light layout.
PERSONAL_PRODUCERS = frozenset({"referral_touch", "referral_onboarding", "manual", "stage_rule"})

_URL = re.compile(r"https?://[^\s<>\"']+")
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


@dataclass(frozen=True)
class Branding:
    display_name: str
    practice_name: str
    header_color: str
    accent_color: str


def branding(tenant) -> Branding:
    def colour(value, default):
        return value if value and _HEX.match(value) else default

    return Branding(
        display_name=(getattr(tenant, "email_display_name", "") or getattr(tenant, "name", "")
                      or DEFAULT_DISPLAY_NAME).strip(),
        practice_name=(getattr(tenant, "name", "") or DEFAULT_DISPLAY_NAME).strip(),
        header_color=colour(getattr(tenant, "email_header_color", ""), DEFAULT_HEADER_COLOR),
        accent_color=colour(getattr(tenant, "email_accent_color", ""), DEFAULT_ACCENT_COLOR),
    )


def template_context(tenant, **extra):
    brand = branding(tenant)
    return {"brand": brand, "font": FONT_STACK, "text_color": TEXT_COLOR,
            "muted": MUTED_COLOR, "faint": FAINT_COLOR, "accent": brand.accent_color, **extra}


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
        pieces, last = [], 0
        for match in _URL.finditer(paragraph):
            pieces.append(escape(paragraph[last:match.start()]))
            pieces.append(link(match.group(0), accent=accent))
            last = match.end()
        pieces.append(escape(paragraph[last:]))
        body = "".join(pieces).replace("\n", "<br>")
        out.append(f'<p style="margin:0 0 16px;">{body}</p>')
    return "".join(out)


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
    content = style_links(html, accent=accent) if (html or "").strip() \
        else text_to_html(text, accent=accent)
    return document(message.tenant, content_html=content, subject=message.subject,
                    personal=message.producer in PERSONAL_PRODUCERS), text


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
