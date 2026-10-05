"""Profile pictures (docs/ui3_top_bar_settings_profile.md §6).

Whatever is uploaded, what is stored is a 256x256 JPEG made here. Re-encoding
is the safety step, not a nicety: it drops the original file, any location or
camera data inside it, and anything that only claims to be an image.
"""

from __future__ import annotations

import io

from PIL import Image, ImageOps, UnidentifiedImageError

from apps.tenancy import storage
from apps.tenancy.models import CLIENT_ROLES, Membership

PURPOSE = "avatar"
MAX_BYTES = 5 * 1024 * 1024
SIZE = 256
#: By what the file is, never by what its name or content type claims.
FORMATS = {"JPEG", "PNG", "WEBP"}
#: A small file can still unpack to an enormous picture.
MAX_PIXELS = 40_000_000

ACCEPTED = "Use a JPEG, PNG or WebP picture."


class PictureInvalid(Exception):
    pass


def process(content: bytes) -> bytes:
    """The square 256x256 JPEG to store, or PictureInvalid saying why not."""
    if not content:
        raise PictureInvalid("Choose a picture to upload.")
    if len(content) > MAX_BYTES:
        raise PictureInvalid(
            f"That picture is {len(content) / 1024 / 1024:.1f} MB; the limit is 5 MB.")
    try:
        with Image.open(io.BytesIO(content)) as picture:
            if picture.format not in FORMATS:
                raise PictureInvalid(ACCEPTED)
            if picture.width * picture.height > MAX_PIXELS:
                raise PictureInvalid("That picture is too large. Use one under 40 megapixels.")
            # Phones store the rotation beside the pixels; apply it, then drop it.
            picture = ImageOps.exif_transpose(picture)
            if picture.mode in ("RGBA", "LA", "P"):
                picture = picture.convert("RGBA")
                flat = Image.new("RGB", picture.size, (255, 255, 255))
                flat.paste(picture, mask=picture.getchannel("A"))
                picture = flat
            else:
                picture = picture.convert("RGB")
            # The browser sends a square crop; anything else is cropped to its
            # center rather than squashed.
            picture = ImageOps.fit(picture, (SIZE, SIZE), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            picture.save(out, format="JPEG", quality=88, optimize=True)
            return out.getvalue()
    except PictureInvalid:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise PictureInvalid(ACCEPTED) from None


def set_picture(membership, content: bytes):
    """Store the new picture, then remove the one it replaces."""
    stored = storage.save(
        tenant=membership.tenant, content=process(content),
        object_key=storage.object_key(f"avatars/{membership.tenant.slug}", "picture.jpg"),
        content_type="image/jpeg", purpose=PURPOSE,
    )
    previous = membership.avatar
    membership.avatar = stored
    membership.save(update_fields=["avatar"])
    if previous is not None:
        _discard(previous)
    return stored


def remove_picture(membership) -> None:
    previous = membership.avatar
    if previous is None:
        return
    membership.avatar = None
    membership.save(update_fields=["avatar"])
    _discard(previous)


def _discard(stored_file) -> None:
    try:
        storage.delete(stored_file)
    except storage.StorageError:
        # The person's picture is already changed; an object that could not be
        # removed right now is left for `check_media` to report, not shown.
        pass


def url_for(membership) -> str | None:
    """Versioned by the file, so a new picture is a new address."""
    if membership is None or not membership.avatar_id:
        return None
    return f"/api/people/{membership.pk}/picture?v={str(membership.avatar_id)[:8]}"


def visible_to(viewer, membership_id):
    """The membership whose picture `viewer` may fetch, or None.

    Staff: anyone in their practice. A client user: themselves, the other
    users of their own company, and the practice's staff; never another client
    company's people. Another practice's is never found, whoever asks.
    """
    if viewer is None:
        return None
    target = (Membership.all_objects.select_related("avatar", "tenant")
              .filter(pk=membership_id, tenant_id=viewer.tenant_id,
                      revoked_at__isnull=True, avatar__isnull=False).first())
    if target is None:
        return None
    if viewer.role in CLIENT_ROLES and target.role in CLIENT_ROLES \
            and target.client_company_id != viewer.client_company_id:
        return None
    return target
