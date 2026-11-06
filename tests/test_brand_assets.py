"""The product's brand files (owner, 2026-11-05; docs/brand/README.md) and the
surfaces that use them: the tab icons and manifest, and the platform's own
mail. A practice's surfaces never carry them."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from django.conf import settings
from django.test import RequestFactory
from PIL import Image

from apps.crm.services import email_layout
from config.spa import with_identity

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import ClientCompanyFactory

BRAND = Path(settings.BASE_DIR, "frontend/public/brand")
PIECES = ("mark", "stacked", "line")
COLORWAYS = ("standard", "reversed", "blue", "white")
ON = {"standard": ["white"], "reversed": ["blue"], "blue": ["white"], "white": ["blue", "orange"]}
HEX = {"white": (255, 255, 255), "blue": (0x0D, 0x2C, 0x54), "orange": (0xE8, 0x77, 0x22)}


@pytest.mark.parametrize("piece", PIECES)
@pytest.mark.parametrize("colorway", COLORWAYS)
def test_every_piece_is_a_vector_in_every_colorway_with_text_as_paths(piece, colorway):
    svg = (BRAND / "svg" / f"enhq-{piece}-{colorway}.svg").read_text()
    assert "<text" not in svg and "font-family" not in svg, "text converted to paths"
    assert "<rect" not in svg and "<image" not in svg, "no background, no embedded bitmap"
    fills = set(re.findall(r'fill="([^"]+)"', svg))
    allowed = {"standard": {"#0D2C54", "#E87722", "#FFFFFF"},
               "reversed": {"#0D2C54", "#E87722", "#FFFFFF"},
               "blue": {"#0D2C54"}, "white": {"#FFFFFF"}}[colorway]
    assert fills and fills <= allowed


@pytest.mark.parametrize("piece", PIECES)
@pytest.mark.parametrize("colorway", COLORWAYS)
def test_every_png_is_the_width_asked_and_on_the_background_it_names(piece, colorway):
    for width in (512, 2048):
        with Image.open(BRAND / "png" / f"enhq-{piece}-{colorway}-transparent-{width}.png") as im:
            assert im.width == width and im.mode == "RGBA"
            if piece != "mark":   # the mark's square runs to its corners
                assert im.getpixel((0, im.height - 1))[3] == 0, "transparent"
        for bg in ON[colorway]:
            with Image.open(BRAND / "png" / f"enhq-{piece}-{colorway}-{bg}-{width}.png") as im:
                assert im.width == width
                # The clear space is included: the corner is the background.
                assert im.convert("RGB").getpixel((2, 2)) == HEX[bg]


def test_the_tab_icons_are_the_mark_square_at_every_size():
    for name, size in {"favicon-16.png": 16, "favicon-32.png": 32, "favicon-48.png": 48,
                       "apple-touch-icon.png": 180, "icon-192.png": 192,
                       "icon-512.png": 512}.items():
        with Image.open(BRAND / name) as im:
            assert im.size == (size, size)
            # No rounding: the corner is the square's own dark blue.
            assert im.convert("RGB").getpixel((0, 0)) == HEX["blue"], name
    with Image.open(BRAND / "favicon.ico") as ico:
        assert {(16, 16), (32, 32), (48, 48)} <= set(ico.info["sizes"])
    manifest = json.loads((BRAND / "site.webmanifest").read_text())
    for icon in manifest["icons"]:
        assert (BRAND / icon["src"].removeprefix("/static/brand/")).is_file()


def test_the_readme_and_contact_sheet_are_there():
    readme = Path(settings.BASE_DIR, "docs/brand/README.md").read_text()
    assert "#0D2C54" in readme and "#E87722" in readme
    assert "half the square's width" in readme
    assert Path(settings.BASE_DIR, "docs/brand/contact-sheet.png").is_file()


# ----------------------------------------------------------------- the tab

def _page(membership=None, area=None):
    request = RequestFactory().get("/work")
    request.membership = membership
    if area:
        request.area = area
    return with_identity('<html><head><title>Portal</title>'
                         '<link rel="icon" href="/api/branding/mark" /></head></html>', request)


@pytest.mark.django_db
def test_staff_and_the_practices_area_get_the_manifest_and_every_icon(seeded_tenant):
    for html in (_page(_member(seeded_tenant, "FF")), _page(area="platform"), _page(None)):
        assert '<link rel="manifest" href="/static/brand/site.webmanifest" />' in html
        for name in ("favicon.ico", "favicon-16.png", "favicon-32.png", "favicon-48.png",
                     "apple-touch-icon.png"):
            assert f"/static/brand/{name}" in html


@pytest.mark.django_db
def test_a_client_gets_no_manifest_and_no_product_icon(seeded_tenant):
    html = _page(_member(seeded_tenant, "FCC", ClientCompanyFactory(tenant=seeded_tenant)))
    assert "manifest" not in html and "/static/brand/" not in html


# ---------------------------------------------------------------- the mail

@pytest.fixture
def platform_owner(seeded_tenant):
    owner = _member(seeded_tenant, "FF")
    owner.user.is_platform_owner = True
    owner.user.save()
    return owner


@pytest.mark.django_db
def test_platform_mail_is_headed_by_the_one_line_lockup_at_160_px(platform_owner, monkeypatch):
    from apps.crm.models import OutboxMessage
    from apps.platform import mail

    monkeypatch.setattr("apps.crm.services.outbox._deliver", lambda message, **kw: None,
                        raising=False)
    message = mail.send_platform_mail(to="owner@bluesky.invalid", subject="Your receipt",
                                      paragraphs=["Thank you."],
                                      producer=OutboxMessage.Producer.PRACTICE_INVITE)
    header = re.search(r"<img\b[^>]*data-enhq-product[^>]*>", message.body_html).group(0)
    with Image.open(BRAND / "png/enhq-line-standard-transparent-512.png") as im:
        height = round(160 * im.height / im.width)
    assert 'width="160"' in header and f'height="{height}"' in header
    assert 'alt="Execs NOW HQ"' in header
    assert "data-enhq-logo" not in message.body_html, "not the sending practice's logo"

    html, inline = email_layout.with_logo(message.body_html, message.tenant)
    (part,) = [p for p in inline if p[0] == email_layout.PRODUCT_CID]
    assert part[1] == (BRAND / "png/enhq-line-standard-transparent-512.png").read_bytes()
    assert part[2] == "image/png"
    preview, _ = email_layout.with_logo(message.body_html, message.tenant, as_data_uri=True)
    assert "data:image/png;base64," in preview and "cid:enhq-product" not in preview


@pytest.mark.django_db
def test_without_the_file_platform_mail_names_the_product_in_text(platform_owner, monkeypatch):
    monkeypatch.setattr(email_layout, "PRODUCT_LOCKUP", "frontend/public/brand/png/none.png")
    html = email_layout.document(platform_owner.tenant, content_html="<p>Hi</p>",
                                 internal=True, product=True)
    assert "data-enhq-product" not in html and "Execs NOW HQ" in html


@pytest.mark.django_db
def test_a_practices_own_mail_never_carries_the_product(seeded_tenant):
    """White-label: even the platform owner's own practice's mail wears its
    own logo or name, never the product's lockup."""
    for internal in (False, True):
        html = email_layout.document(seeded_tenant, content_html="<p>Hi</p>", internal=internal)
        assert "data-enhq-product" not in html and "Execs NOW HQ" not in html
        _, inline = email_layout.with_logo(html, seeded_tenant)
        assert all(part[0] != email_layout.PRODUCT_CID for part in inline)
