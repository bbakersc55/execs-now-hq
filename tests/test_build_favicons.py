"""manage.py build_favicons (P1): the product's tab icons from its mark."""

from __future__ import annotations

import pytest
from django.core.management import CommandError, call_command
from PIL import Image


def mark(path, size=(464, 464), fmt="PNG"):
    Image.new("RGBA", size, (10, 58, 101, 255)).save(path, fmt)
    return path


def test_writes_every_size_from_a_464_px_mark_enlarging_only_the_512(tmp_path):
    out = tmp_path / "brand"
    call_command("build_favicons", "--source", str(mark(tmp_path / "mark.png")), "--out", str(out))
    sizes = {name: Image.open(out / name).size for name in
             ("favicon-32.png", "apple-touch-icon.png", "icon-192.png", "icon-512.png")}
    assert sizes == {"favicon-32.png": (32, 32), "apple-touch-icon.png": (180, 180),
                     "icon-192.png": (192, 192), "icon-512.png": (512, 512)}
    with Image.open(out / "favicon.ico") as ico:
        assert {(16, 16), (32, 32), (48, 48)} <= set(ico.info["sizes"])


def test_a_nearly_square_mark_is_padded_not_refused(tmp_path):
    out = tmp_path / "brand"
    call_command("build_favicons", "--source", str(mark(tmp_path / "m.png", (467, 469))),
                 "--out", str(out))
    assert Image.open(out / "icon-192.png").size == (192, 192)


@pytest.mark.parametrize("size,fmt,needle", [
    ((464, 400), "PNG", "must be square"),
    ((128, 128), "PNG", "at least 192"),
    ((464, 464), "JPEG", "use a PNG"),
])
def test_refuses_a_mark_it_cannot_make_good_icons_from(tmp_path, size, fmt, needle):
    source = tmp_path / ("mark.jpg" if fmt == "JPEG" else "mark.png")
    Image.new("RGB", size, (10, 58, 101)).save(source, fmt)
    with pytest.raises(CommandError, match=needle):
        call_command("build_favicons", "--source", str(source), "--out", str(tmp_path / "o"))


def test_says_when_there_is_no_mark_yet(tmp_path):
    with pytest.raises(CommandError, match="No mark at"):
        call_command("build_favicons", "--source", str(tmp_path / "mark.png"))


def test_derive_makes_the_edge_white_transparent_and_keeps_white_inside(tmp_path):
    """Only white connected to the edge is background: a white hole inside
    the mark stays white, a gray bar stays solid, and the margins go."""
    from PIL import ImageDraw

    source = tmp_path / "mark.png"
    image = Image.new("RGB", (400, 400), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((100, 100, 300, 300), fill=(10, 58, 101))       # navy block
    draw.rectangle((180, 180, 220, 220), fill=(255, 255, 255))     # white hole inside
    draw.rectangle((120, 120, 150, 280), fill=(147, 149, 152))     # gray bar
    image.save(source)

    out = tmp_path / "brand"
    call_command("build_favicons", "--source", str(source), "--out", str(out), "--derive")
    derived = Image.open(tmp_path / "mark-transparent.png")
    assert source.exists() and Image.open(source).mode == "RGB", "the original is unchanged"
    side = derived.size[0]
    assert derived.size == (side, side) and side < 400, "trimmed and square"
    corner = derived.getpixel((0, 0))
    centre = derived.getpixel((side // 2, side // 2))
    bar = derived.getpixel((round(side * 0.2), side // 2))
    assert corner[3] == 0
    assert centre == (255, 255, 255, 255), "white enclosed by the mark stays"
    assert bar[3] == 255 and bar[:3] == (147, 149, 152), "gray stays solid"
    assert Image.open(out / "icon-192.png").mode == "RGBA"
