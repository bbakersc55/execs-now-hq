"""Reading the watched folder (FR-5.1 to FR-5.7).

**Cursor-based, not event-based** (assumption A6). The app runs on a laptop
that is shut at night: ingestion has to be something that catches up, not
something that must be listening at the moment a file lands. Drive's
`changes.list` gives exactly that — a token you hand back next time.

The client is thin on purpose. Everything that decides anything — what is
supported, when the cursor moves, what gets parsed — is in `ingest.py`, so the
tests that matter run against a fake that returns pages, not against Google.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: What Beta can read (FR-5.6). Anything else is recorded and skipped **with a
#: reason**, because a file that vanished silently is a file the fractional
#: will assume was processed.
GOOGLE_DOC = "application/vnd.google-apps.document"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PLAIN = "text/plain"
SUPPORTED = {GOOGLE_DOC, DOCX, PLAIN}

SKIP_REASONS = {
    "application/pdf": "A PDF is not read in Beta — export the notes as a Doc or text.",
    "video": "Audio and video are out of scope for Beta.",
    "audio": "Audio and video are out of scope for Beta.",
}


def skip_reason(mime_type: str) -> str:
    """Why this file is not being parsed, in the words the screen shows."""
    if mime_type in SUPPORTED:
        return ""
    if mime_type in SKIP_REASONS:
        return SKIP_REASONS[mime_type]
    family = (mime_type or "").split("/")[0]
    if family in SKIP_REASONS:
        return SKIP_REASONS[family]
    if mime_type.startswith("application/vnd.google-apps."):
        kind = mime_type.rsplit(".", 1)[-1]
        return f"A Google {kind} is not meeting notes; only Docs are read."
    return f"{mime_type or 'That file type'} is not read in Beta."


@dataclass
class DriveFile:
    """One file as the poller sees it."""

    file_id: str
    version: str
    name: str
    mime_type: str
    owner_email: str = ""
    web_view_link: str = ""
    trashed: bool = False


@dataclass
class DrivePage:
    files: list[DriveFile] = field(default_factory=list)
    next_page_token: str = ""
    #: Drive hands this back at the end of a run; it is the cursor for next
    #: time, and `ingest` only stores it once everything in the page is safe.
    new_start_page_token: str = ""


class DriveUnavailable(Exception):
    """Drive could not be reached, or refused. Retryable; the cursor stays."""


class DriveClient:
    """The real one. Constructed from the tenant's Gmail/Drive OAuth
    connection, which already holds the refresh token Module 1 obtained."""

    def __init__(self, connection):
        self.connection = connection

    def _service(self):
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        from apps.crm.services import transport

        # The same refresh path Gmail sending already uses: one connection,
        # one token story, and Drive is a scope on it rather than a second
        # thing to keep alive.
        token = transport.access_token_for(self.connection)
        return build("drive", "v3", credentials=Credentials(token),
                     cache_discovery=False)

    def start_token(self) -> str:
        try:
            return self._service().changes().getStartPageToken().execute()[
                "startPageToken"]
        except Exception as exc:                     # pragma: no cover - network
            raise DriveUnavailable(str(exc)) from exc

    def changes(self, page_token: str, *, folder_id: str) -> DrivePage:
        """One page of changes, filtered to the watched folder."""
        try:
            response = self._service().changes().list(
                pageToken=page_token, spaces="drive",
                fields=("nextPageToken,newStartPageToken,"
                        "changes(fileId,removed,file(id,name,mimeType,version,"
                        "trashed,parents,webViewLink,owners(emailAddress)))"),
                pageSize=100,
            ).execute()
        except Exception as exc:                     # pragma: no cover - network
            raise DriveUnavailable(str(exc)) from exc

        files = []
        for change in response.get("changes", []):
            raw = change.get("file") or {}
            if change.get("removed") or not raw:
                continue
            if folder_id not in (raw.get("parents") or []):
                continue
            owners = raw.get("owners") or [{}]
            files.append(DriveFile(
                file_id=raw.get("id", ""), version=str(raw.get("version", "")),
                name=raw.get("name", ""), mime_type=raw.get("mimeType", ""),
                owner_email=(owners[0] or {}).get("emailAddress", ""),
                web_view_link=raw.get("webViewLink", ""),
                trashed=bool(raw.get("trashed")),
            ))
        return DrivePage(files=files,
                         next_page_token=response.get("nextPageToken", ""),
                         new_start_page_token=response.get("newStartPageToken", ""))

    def text_of(self, drive_file: DriveFile) -> str:
        """The document as text. A Doc is exported; a `.txt` is downloaded; a
        `.docx` is converted by Drive on the way out."""
        try:
            service = self._service()
            if drive_file.mime_type == GOOGLE_DOC:
                content = service.files().export(
                    fileId=drive_file.file_id, mimeType="text/plain").execute()
            elif drive_file.mime_type == DOCX:
                content = service.files().export_media(
                    fileId=drive_file.file_id, mimeType="text/plain").execute()
            else:
                content = service.files().get_media(
                    fileId=drive_file.file_id).execute()
        except Exception as exc:                     # pragma: no cover - network
            raise DriveUnavailable(str(exc)) from exc
        return content.decode("utf-8", "replace") if isinstance(content, bytes) \
            else str(content)
