"""Blob storage for `stored_file` rows.

**This did not exist.** `StoredFile` recorded a bucket, an object key and a byte
size, and nothing ever wrote the bytes — so the marketing flyer was 404,710
bytes according to the database and zero bytes everywhere else. The Outbox
showed an attachment, Gmail delivered an attachment, and the file opened empty.

Two rules follow from that, and both matter more than the storage backend:

1. **Writing a `StoredFile` and writing its content are one operation.** `save()`
   below is the only way to make one, so metadata without content cannot happen
   again.
2. **Missing content is an error, never an empty file.** `read()` raises. A send
   that would attach nothing fails loudly instead of delivering a 0-byte file
   the recipient has to open to discover is broken.

Beta runs on the laptop, so the backend is the local filesystem under
`MEDIA_ROOT`, laid out as `<bucket>/<object_key>` — the same shape as the GCS
object path, so the Phase 7 move is a backend swap and not a re-keying.
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings


class MissingContent(Exception):
    """The row exists; its bytes do not."""


def _path(stored_file) -> Path:
    root = Path(settings.MEDIA_ROOT)
    # Mirrors the GCS object path exactly, so keys do not change at the move.
    return root / stored_file.bucket / stored_file.object_key


def save(*, tenant, content: bytes, object_key: str, purpose: str,
         content_type: str = "", bucket: str = "", delete_after=None):
    """Write the bytes AND the row, together.

    `byte_size` is measured from what was actually written, not copied from an
    upload's claimed size: those agree right up until the moment they do not,
    and a truncated write that still reports the full size is exactly the bug
    this module exists to prevent.
    """
    from apps.tenancy.models import StoredFile

    stored = StoredFile.all_objects.create(
        tenant=tenant, bucket=bucket or settings.GCS_BUCKET_MEDIA,
        object_key=object_key, content_type=content_type,
        byte_size=0, purpose=purpose, delete_after=delete_after,
    )
    written = write_content(stored, content)
    stored.byte_size = written
    stored.save(update_fields=["byte_size", "updated_at"])
    return stored


def write_content(stored_file, content: bytes) -> int:
    destination = _path(stored_file)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return len(content)


def read(stored_file) -> bytes:
    """The bytes, or a refusal naming the file.

    Deliberately not `b""` on a miss. An empty attachment is indistinguishable
    from a working one until the recipient opens it, which makes it the worst
    possible failure mode for something sent to a client.
    """
    source = _path(stored_file)
    if not source.exists():
        raise MissingContent(
            f"{stored_file.object_key!r} is recorded as {stored_file.byte_size} bytes "
            f"but its content is not in storage. Re-upload the file; sending it "
            f"would attach an empty document."
        )
    content = source.read_bytes()
    if not content:
        raise MissingContent(
            f"{stored_file.object_key!r} is stored but empty. Re-upload the file."
        )
    return content


def exists(stored_file) -> bool:
    path = _path(stored_file)
    return path.exists() and path.stat().st_size > 0
