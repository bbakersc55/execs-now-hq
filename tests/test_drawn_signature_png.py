"""A drawn signature is a PNG, and only Pillow's PNG reader opens it
(apps/esign/drawing.py, 2026-11-27). Both pages that take a drawing, the
signing page and the owner-agreement page, go through the one check. No
database is needed."""
import base64
import io
from unittest import mock

import pytest
from PIL import Image

from apps.agreements.services import Refused, drawn_png
from apps.esign.drawing import PNG_SIGNATURE, is_png
from apps.esign.services import DocumentRefused, _drawn_png


def image_bytes(fmt: str) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 12), "white").save(out, format=fmt)
    return out.getvalue()


def data_url(content: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(content).decode()


def test_a_real_png_passes():
    assert is_png(image_bytes("PNG"))


@pytest.mark.parametrize("fmt", ["JPEG", "GIF", "TIFF", "BMP", "WEBP"])
def test_another_format_labelled_png_is_refused_before_pillow_opens_it(fmt):
    content = image_bytes(fmt)
    assert not content.startswith(PNG_SIGNATURE)
    with mock.patch("PIL.Image.open", side_effect=AssertionError("Pillow was called")) as opened:
        assert is_png(content) is False
    opened.assert_not_called()


def test_pillow_is_asked_for_its_png_reader_alone():
    content = image_bytes("PNG")
    real = Image.open
    with mock.patch("PIL.Image.open", side_effect=real) as opened:
        assert is_png(content)
    assert opened.call_args.kwargs["formats"] == ["PNG"]


@pytest.mark.parametrize("content", [
    PNG_SIGNATURE,                                   # the signature and nothing else
    PNG_SIGNATURE + b"\x00" * 40,                    # no valid chunks
    PNG_SIGNATURE + image_bytes("JPEG"),             # a JPEG behind a PNG signature
    image_bytes("PNG")[:-20],                        # cut short
])
def test_a_broken_or_disguised_png_is_refused(content):
    assert is_png(content) is False


def test_a_disguised_file_never_reaches_another_reader():
    """With the PNG signature in front, the PNG reader alone is tried: the
    JPEG plugin's opener is never called."""
    from PIL import JpegImagePlugin

    content = PNG_SIGNATURE + image_bytes("JPEG")
    with mock.patch.object(JpegImagePlugin.JpegImageFile, "_open",
                           side_effect=AssertionError("the JPEG reader ran")) as jpeg:
        assert is_png(content) is False
    jpeg.assert_not_called()


@pytest.mark.parametrize("reader,refusal", [(_drawn_png, DocumentRefused), (drawn_png, Refused)])
def test_both_pages_accept_a_drawing_and_refuse_a_disguised_file(reader, refusal):
    png = image_bytes("PNG")
    assert reader(data_url(png)) == png
    with pytest.raises(refusal, match="could not be read"):
        reader(data_url(image_bytes("JPEG")))
    with pytest.raises(refusal, match="Draw your signature"):
        reader("data:image/jpeg;base64," + base64.b64encode(png).decode())
