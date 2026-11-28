"""A drawn signature is a PNG, and only Pillow's PNG reader ever opens it
(2026-11-27, the security updates, docs/p17_security_updates.md).

The signing page and the owner-agreement page send the signer's drawing as a
`data:image/png` URL, from a person holding a link and nothing else. Before
this, the bytes went to `Image.open` with every reader Pillow has: a JPEG,
TIFF or FlashPix file labelled PNG reached that format's decoder before the
"is it a PNG" check ran, and Pillow 12.3's decoders carried critical flaws.

Now the file's own first eight bytes must be the PNG signature before Pillow
is called at all, and Pillow is told to try its PNG reader alone
(`formats=["PNG"]`), so no other decoder can be reached from these pages.
"""
from __future__ import annotations

import io

#: Every PNG file starts with these eight bytes (the PNG specification, 5.2).
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def is_png(content: bytes) -> bool:
    """True for a PNG that Pillow's PNG reader opens and verifies, and that
    nothing else is asked to read."""
    if not content.startswith(PNG_SIGNATURE):
        return False
    from PIL import Image

    try:
        with Image.open(io.BytesIO(content), formats=["PNG"]) as image:
            image.verify()
            return image.format == "PNG"
    except Exception:
        return False
