"""A practice's branding: what Settings → Branding saves (P1, owner 2026-10-02).

The fields live on `tenant` under their original email-era names
(`email_display_name`, `email_header_color` = primary, `email_accent_color` =
accent, `email_logo`, `email_mark`) plus `brand_footer_text`. Every surface
reads them through `apps/crm/services/email_layout.branding`, so a save here
reaches emails, PDFs and the portal together.

**Defaults (D2):** an unbranded practice wears its own name over neutral grays,
never the product's palette or mark; `branding_updated_at` records whether
the practice owner has ever saved, for P2's "Set branding" checklist item.

Only the practice owner reaches this (the views enforce it); the functions take
the tenant explicitly and touch nothing else.
"""

from __future__ import annotations

from django.utils import timezone

from apps.crm.services import email_layout
from apps.tenancy import contrast, storage
from apps.tenancy.models import AuditEvent

DISPLAY_NAME_MAX = 80
FOOTER_MAX_CHARS = 500
FOOTER_MAX_LINES = 6
IMAGE_MAX_BYTES = email_layout.LOGO_MAX_BYTES
MARK_MIN = 64

KINDS = {"logo": "email_logo", "mark": "email_mark"}


class BrandingInvalid(ValueError):
    """`errors` maps a field to what is wrong with it, in words."""

    def __init__(self, errors: dict[str, str]):
        super().__init__("; ".join(errors.values()))
        self.errors = errors


def current(tenant) -> dict:
    brand = email_layout.branding(tenant)
    return {
        "display_name": tenant.email_display_name,
        "practice_name": tenant.name,
        "primary_color": brand.header_color,
        "accent_color": brand.accent_color,
        "footer_text": tenant.brand_footer_text,
        "has_logo": tenant.email_logo_id is not None,
        "has_mark": tenant.email_mark_id is not None,
        "branding_updated_at": tenant.branding_updated_at,
        "contrast": [c.as_dict() for c in contrast.check(brand.header_color,
                                                          brand.accent_color)],
        "defaults": {"primary_color": email_layout.DEFAULT_HEADER_COLOR,
                     "accent_color": email_layout.DEFAULT_ACCENT_COLOR},
    }


def save(tenant, *, actor, display_name: str, primary_color: str, accent_color: str,
         footer_text: str) -> None:
    display_name = (display_name or "").strip()
    primary = (primary_color or "").strip().upper()
    accent = (accent_color or "").strip().upper()
    footer = "\n".join(line.rstrip() for line in (footer_text or "").strip().splitlines())

    errors = {}
    if len(display_name) > DISPLAY_NAME_MAX:
        errors["display_name"] = f"The display name is at most {DISPLAY_NAME_MAX} characters."
    for field, value in (("primary_color", primary), ("accent_color", accent)):
        if not contrast.HEX.match(value):
            errors[field] = "Use a six-digit hex color, like #0A3A65."
    if len(footer) > FOOTER_MAX_CHARS:
        errors["footer_text"] = f"The footer is at most {FOOTER_MAX_CHARS} characters."
    elif len(footer.splitlines()) > FOOTER_MAX_LINES:
        errors["footer_text"] = f"The footer is at most {FOOTER_MAX_LINES} lines."
    if "primary_color" not in errors and "accent_color" not in errors:
        for failure in contrast.blocking_failures(primary, accent):
            field = "primary_color" if failure.rule == "primary_on_white" else "accent_color"
            errors[field] = (f"{failure.label} is {failure.ratio:.2f} : 1; it needs at "
                             f"least {failure.required:g} : 1.")
    if errors:
        raise BrandingInvalid(errors)

    tenant.email_display_name = display_name
    tenant.email_header_color = primary
    tenant.email_accent_color = accent
    tenant.brand_footer_text = footer
    tenant.branding_updated_at = timezone.now()
    tenant.save(update_fields=["email_display_name", "email_header_color",
                               "email_accent_color", "brand_footer_text",
                               "branding_updated_at", "updated_at"])
    _audit(tenant, actor, "branding.updated",
           {"display_name": display_name, "primary_color": primary,
            "accent_color": accent, "footer_lines": len(footer.splitlines())})


def check_image(kind: str, content: bytes) -> tuple[str, int, int, tuple[int, int]]:
    """`(content_type, width, height, display_size)`, or BrandingInvalid."""
    if kind not in KINDS:
        raise BrandingInvalid({"kind": "Choose the logo or the mark."})
    if len(content) > IMAGE_MAX_BYTES:
        raise BrandingInvalid({kind: f"The file is {len(content) // 1024} KB; the limit is "
                                     f"{IMAGE_MAX_BYTES // 1024} KB."})
    try:
        content_type, width, height = email_layout.image_size(content)
    except ValueError:
        # SVG lands here too: it can carry script, and mail clients disagree on it.
        raise BrandingInvalid({kind: "Use a PNG or a JPEG." if kind == "logo"
                               else "Use a PNG."}) from None
    if kind == "mark":
        if content_type != "image/png":
            raise BrandingInvalid({"mark": "Use a PNG."})
        if width != height:
            raise BrandingInvalid({"mark": f"The mark must be square; this one is "
                                           f"{width} x {height} px."})
        if width < MARK_MIN:
            raise BrandingInvalid({"mark": f"The mark must be at least {MARK_MIN} x "
                                           f"{MARK_MIN} px; 180 or more looks sharp."})
        display = email_layout.logo_display_size(
            width, height, max_width=email_layout.MARK_MAX, max_height=email_layout.MARK_MAX)
    else:
        display = email_layout.logo_display_size(width, height)
    return content_type, width, height, display


def set_image(tenant, *, actor, kind: str, content: bytes) -> dict:
    content_type, width, height, display = check_image(kind, content)
    field = KINDS[kind]
    extension = "jpg" if content_type == "image/jpeg" else "png"
    stored = storage.save(
        tenant=tenant, content=content,
        object_key=storage.object_key(f"branding/{tenant.slug}", f"{kind}.{extension}"),
        content_type=content_type, purpose=field,
    )
    setattr(tenant, field, stored)
    setattr(tenant, f"{field}_width", display[0])
    setattr(tenant, f"{field}_height", display[1])
    tenant.branding_updated_at = timezone.now()
    tenant.save(update_fields=[field, f"{field}_width", f"{field}_height",
                               "branding_updated_at", "updated_at"])
    _audit(tenant, actor, f"branding.{kind}_set",
           {"content_type": content_type, "width": width, "height": height})
    return {"content_type": content_type, "width": width, "height": height,
            "shown_at": list(display)}


def clear_image(tenant, *, actor, kind: str) -> None:
    if kind not in KINDS:
        raise BrandingInvalid({"kind": "Choose the logo or the mark."})
    field = KINDS[kind]
    setattr(tenant, field, None)
    setattr(tenant, f"{field}_width", 0)
    setattr(tenant, f"{field}_height", 0)
    tenant.save(update_fields=[field, f"{field}_width", f"{field}_height", "updated_at"])
    _audit(tenant, actor, f"branding.{kind}_cleared", {})


def reset(tenant, *, actor) -> None:
    """Back to the defaults: own name, neutral grays, no images, no footer."""
    tenant.email_display_name = ""
    tenant.email_header_color = email_layout.DEFAULT_HEADER_COLOR
    tenant.email_accent_color = email_layout.DEFAULT_ACCENT_COLOR
    tenant.brand_footer_text = ""
    for field in KINDS.values():
        setattr(tenant, field, None)
        setattr(tenant, f"{field}_width", 0)
        setattr(tenant, f"{field}_height", 0)
    tenant.branding_updated_at = None
    tenant.save()
    _audit(tenant, actor, "branding.reset", {})


def initials(name: str) -> str:
    """Up to two letters for the default mark: "Blue Sky Business" -> "BS"."""
    words = [w for w in (name or "").replace("&", " ").split() if w[:1].isalnum()]
    letters = "".join(w[0] for w in words[:2]).upper()
    return letters or "·"


def initials_svg(name: str, color: str = email_layout.DEFAULT_HEADER_COLOR) -> str:
    """The default mark when a practice has none (D2): its initials on gray.

    Generated here from two letters and a validated color, never from upload,
    so serving it as SVG carries no script.
    """
    from django.utils.html import escape

    fill = color if contrast.HEX.match(color or "") else email_layout.DEFAULT_HEADER_COLOR
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        f'<rect width="64" height="64" rx="12" fill="{fill}"/>'
        f'<text x="32" y="41" text-anchor="middle" font-family="Helvetica, Arial, sans-serif" '
        f'font-size="26" font-weight="700" fill="{contrast.text_on(fill)}">'
        f"{escape(initials(name))}</text></svg>"
    )


def _audit(tenant, actor, verb, payload):
    AuditEvent.all_objects.create(tenant=tenant, actor=actor, verb=verb,
                                  target_type="tenant", target_id=tenant.pk, payload=payload)
