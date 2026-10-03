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
