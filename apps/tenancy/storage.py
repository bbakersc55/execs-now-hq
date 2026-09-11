"""Blob storage for `stored_file` rows.

**This did not exist.** `StoredFile` recorded a bucket, an object key and a byte
size, and nothing ever wrote the bytes — so the marketing flyer was 404,710
bytes according to the database and zero bytes everywhere else. The Outbox
showed an attachment, Gmail delivered an attachment, and the file opened empty.

Two rules follow from that, and both matter more than the storage backend:

1. **Writing a `StoredFile` and writing its content are one operation.** `save()`
   below is the only way to make one, so metadata without content cannot happen
   again. The bytes go first and the row second: if the row fails, the cost is
   an orphan object; the reverse order would leave a row describing nothing.
2. **Missing content is an error, never an empty file.** `read()` raises. A send
   that would attach nothing fails loudly instead of delivering a 0-byte file
   the recipient has to open to discover is broken.

Phase 2 adds two more:

3. **A write never replaces an existing object.** Two flyer uploads with the
   same filename used to share one key, so the second silently rewrote the
   bytes behind the first row. Harmless until anything deletes — and the audio
   retention job deletes. Keys come from `object_key()`, which makes them
   unique, and both backends refuse to overwrite.
4. **"Gone" and "unreachable" are different errors.** Content lives in GCS, so
   an offline laptop or a revoked key is now a possible failure. That raises
   `StorageUnavailable` (retry later) and never `MissingContent` (re-upload),
   because telling the owner a client file is lost when the Wi-Fi is down is
   its own kind of wrong.

Backends: `gcs` (the default) and `local` (MEDIA_ROOT/<bucket>/<object_key>,
the same shape) for the test suite and the restore drill.
"""

from __future__ import annotations

import functools
import uuid
from pathlib import Path

from django.conf import settings

# Recording audio is excluded from the backup mirror so that audio_retention_days
# actually deletes it (owner decision, Phase 2). scripts/backup_db.sh excludes
# this prefix, so the prefix IS the rule — save() enforces it both ways.
RECORDINGS_PREFIX = "recordings/"
RECORDING_PURPOSE = "recording_audio"

# Storage scope only: the key can read and write objects, nothing else.
_GCS_SCOPES = ["https://www.googleapis.com/auth/devstorage.read_write"]


class StorageError(Exception):
    pass


class MissingContent(StorageError):
    """The row exists; its bytes do not."""


class StorageUnavailable(StorageError):
    """Storage could not be reached. The content may be fine; try again."""


class ObjectExists(StorageError):
    """A write targeted a key that already holds another file's bytes."""


def object_key(prefix: str, filename: str) -> str:
    """A key no other row can share: `<prefix>/<uuid>/<filename>`.

    The filename stays last so a downloaded object keeps its real name.
    """
    return f"{prefix.strip('/')}/{uuid.uuid4()}/{filename}"


def save(*, tenant, content: bytes, object_key: str, purpose: str,
         content_type: str = "", bucket: str = "", delete_after=None):
    """Write the bytes, then the row.

    `byte_size` is measured from what was actually written, not copied from an
    upload's claimed size: those agree right up until the moment they do not,
    and a truncated write that still reports the full size is exactly the bug
    this module exists to prevent.
    """
    from apps.tenancy.models import StoredFile

    _check_prefix(purpose, object_key)
    bucket = bucket or settings.GCS_BUCKET_MEDIA
    written = _backend().write(bucket, object_key, content, content_type)
    return StoredFile.all_objects.create(
        tenant=tenant, bucket=bucket, object_key=object_key,
        content_type=content_type, byte_size=written, purpose=purpose,
        delete_after=delete_after,
    )


def write_content(stored_file, content: bytes) -> int:
    return _backend().write(
        stored_file.bucket, stored_file.object_key, content, stored_file.content_type
    )


def read(stored_file) -> bytes:
    """The bytes, or a refusal naming the file.

    Deliberately not `b""` on a miss. An empty attachment is indistinguishable
    from a working one until the recipient opens it, which makes it the worst
    possible failure mode for something sent to a client.
    """
    content = _backend().read(stored_file.bucket, stored_file.object_key)
    if content is None:
        raise MissingContent(
            f"{stored_file.object_key!r} is recorded as {stored_file.byte_size} bytes "
            f"but its content is not in storage. Re-upload the file; sending it "
            f"would attach an empty document."
        )
    if not content:
        raise MissingContent(
            f"{stored_file.object_key!r} is stored but empty. Re-upload the file."
        )
    return content


def exists(stored_file) -> bool:
    """Present and non-empty. Raises `StorageUnavailable` rather than guess."""
    return bool(_backend().size(stored_file.bucket, stored_file.object_key))


def present_or_unknown(stored_file) -> bool | None:
    """For display: `None` when storage cannot be asked right now.

    A screen that says "file missing" because the laptop is offline sends the
    owner to re-upload a file that is fine.
    """
    try:
        return exists(stored_file)
    except StorageUnavailable:
        return None


def sizes(bucket: str) -> dict[str, int]:
    """Every object in `bucket` with its size — one listing, for `check_media`."""
    return _backend().list_sizes(bucket)


def _check_prefix(purpose: str, key: str) -> None:
    is_recording = purpose == RECORDING_PURPOSE
    if is_recording != key.startswith(RECORDINGS_PREFIX):
        raise ValueError(
            f"{purpose!r} stored at {key!r}: recording audio must live under "
            f"{RECORDINGS_PREFIX!r} and nothing else may. The backup excludes that "
            f"prefix so retention can delete audio; a recording elsewhere would be "
            f"kept forever, and a flyer there would never be backed up."
        )


def _backend():
    if settings.STORAGE_BACKEND == "local":
        return LocalBackend(Path(settings.MEDIA_ROOT))
    return GcsBackend()


class LocalBackend:
    def __init__(self, root: Path):
        self.root = root

    def _path(self, bucket: str, key: str) -> Path:
        return self.root / bucket / key

    def write(self, bucket, key, content, content_type) -> int:
        path = self._path(bucket, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("xb") as f:
                f.write(content)
        except FileExistsError as exc:
            raise ObjectExists(f"{bucket}/{key} already exists; not overwriting.") from exc
        return path.stat().st_size

    def read(self, bucket, key):
        path = self._path(bucket, key)
        return path.read_bytes() if path.is_file() else None

    def size(self, bucket, key):
        path = self._path(bucket, key)
        return path.stat().st_size if path.is_file() else None

    def list_sizes(self, bucket):
        base = self.root / bucket
        if not base.is_dir():
            return {}
        return {
            p.relative_to(base).as_posix(): p.stat().st_size
            for p in base.rglob("*") if p.is_file()
        }


class GcsBackend:
    """gs://<bucket>/<object_key>, as the app's service account."""

    def write(self, bucket, key, content, content_type) -> int:
        from google.api_core.exceptions import PreconditionFailed

        blob = self._bucket(bucket).blob(key)
        with _unavailable_on_failure(f"write {bucket}/{key}"):
            try:
                # if_generation_match=0: create only. Also what makes the
                # library's automatic retry safe for an upload.
                blob.upload_from_string(
                    content, content_type=content_type or "application/octet-stream",
                    if_generation_match=0,
                )
            except PreconditionFailed as exc:
                raise ObjectExists(f"gs://{bucket}/{key} already exists; not overwriting.") from exc
        # The upload is CRC32C-checked by the library; this catches the one
        # thing a checksum cannot — having been handed the wrong bytes to send.
        if blob.size != len(content):
            raise StorageUnavailable(
                f"gs://{bucket}/{key} stored {blob.size} bytes of {len(content)}."
            )
        return blob.size

    def read(self, bucket, key):
        from google.api_core.exceptions import NotFound

        with _unavailable_on_failure(f"read {bucket}/{key}"):
            try:
                return self._bucket(bucket).blob(key).download_as_bytes()
            except NotFound:
                return None

    def size(self, bucket, key):
        with _unavailable_on_failure(f"stat {bucket}/{key}"):
            blob = self._bucket(bucket).get_blob(key)
        return blob.size if blob is not None else None

    def list_sizes(self, bucket):
        with _unavailable_on_failure(f"list {bucket}"):
            return {b.name: b.size for b in _client().list_blobs(bucket)}

    def _bucket(self, name):
        return _client().bucket(name)


@functools.cache
def _client_for(credentials_path: str, project: str):
    from google.cloud import storage as gcs
    from google.oauth2 import service_account

    credentials = service_account.Credentials.from_service_account_file(
        credentials_path, scopes=_GCS_SCOPES
    )
    return gcs.Client(project=project, credentials=credentials)


def _client():
    path = settings.GOOGLE_APPLICATION_CREDENTIALS
    if not path or not Path(path).is_file():
        # Explicitly not a fallback to gcloud ADC (assumption A7): that would
        # work on this laptop, bill the wrong project, and fail on Railway.
        raise StorageUnavailable(
            f"No service-account key at GOOGLE_APPLICATION_CREDENTIALS={path!r}. "
            f"See docs/05_dev_environment.md §5b."
        )
    return _client_for(path, settings.GOOGLE_CLOUD_PROJECT)


class _unavailable_on_failure:
    """Map transport, auth and API failures onto `StorageUnavailable`."""

    def __init__(self, what: str):
        self.what = what

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc is None or isinstance(exc, StorageError):
            return False
        from google.api_core.exceptions import GoogleAPIError
        from google.auth.exceptions import GoogleAuthError
        from google.resumable_media.common import DataCorruption, InvalidResponse
        from requests.exceptions import RequestException

        if isinstance(exc, (GoogleAPIError, GoogleAuthError, RequestException,
                            InvalidResponse, DataCorruption, OSError)):
            raise StorageUnavailable(f"Could not {self.what}: {exc}") from exc
        return False
