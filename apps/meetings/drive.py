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

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

#: What Beta can read (FR-5.6). Anything else is recorded and skipped **with a
#: reason**, because a file that vanished silently is a file the fractional
#: will assume was processed.
GOOGLE_DOC = "application/vnd.google-apps.document"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PLAIN = "text/plain"
SUPPORTED = {GOOGLE_DOC, DOCX, PLAIN}

FOLDER = "application/vnd.google-apps.folder"

#: A Drive id is a URL-safe string. The point of the check is not to validate
#: against Google — only Google can do that — but to tell "the id" apart from
#: "a whole web address the fractional pasted" and from "nothing useful",
#: so the screen can say which of those went wrong.
ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{6,128}")

#: `describe_folder` counts what is in the folder. A folder with thousands of
#: files is a folder the fractional pointed at by mistake, and paging to the
#: end of it to say so helps nobody.
MAX_COUNT_PAGES = 10


def folder_id_from(value: str) -> str:
    """The folder id out of whatever was pasted, or `""`.

    **Nobody has the id; everybody has the address.** The id is a substring of
    a URL in the address bar, and asking a person to cut it out by hand is
    asking for the trailing `?usp=sharing` to come with it. So take either.
    """
    value = (value or "").strip().strip("<>").rstrip("/")
    if not value:
        return ""
    if "/" in value or "?" in value or ":" in value:
        parsed = urlparse(value if "//" in value else f"https://{value}")
        parts = [p for p in parsed.path.split("/") if p]
        if "folders" in parts:
            candidate = parts[parts.index("folders") + 1:]
            if candidate:
                return _clean_id(candidate[0])
        # The older `?id=` form, still what "Get link" gives for some folders.
        for key in ("id", "folderId"):
            found = parse_qs(parsed.query).get(key)
            if found:
                return _clean_id(found[0])
        return ""
    return _clean_id(value)


def _clean_id(value: str) -> str:
    value = (value or "").split("?")[0].split("#")[0].strip()
    return value if ID_PATTERN.fullmatch(value) else ""

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
class FolderInfo:
    """What the folder turned out to be — shown before anything is saved.

    `readable` is separate from `files` on purpose: a folder of twelve PDFs is
    a connected folder that will never produce a proposal, and the fractional
    should learn that now rather than from an empty queue tomorrow.
    """

    folder_id: str
    name: str
    files: int = 0
    readable: int = 0
    truncated: bool = False


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

    def describe_folder(self, folder_id: str) -> FolderInfo:
        """Prove we can actually read it, and say what is in it (FR-5.1a).

        Called **before** the watch is saved. A folder id that is a typo, or a
        folder on an account this connection cannot see, fails here — on the
        screen, with a reason — instead of becoming a watch that quietly
        returns nothing every ten minutes.
        """
        service = self._service()
        try:
            meta = service.files().get(
                fileId=folder_id, fields="id,name,mimeType,trashed").execute()
        except Exception as exc:                     # pragma: no cover - network
            raise DriveUnavailable(
                "Drive would not open that folder. Check the link, and that the "
                "folder is on the Google account you connected."
            ) from exc
        if meta.get("trashed"):
            raise DriveUnavailable("That folder is in the Drive bin.")
        if meta.get("mimeType") != FOLDER:
            raise DriveUnavailable(
                f"“{meta.get('name') or folder_id}” is a file, not a folder. "
                "Open the folder that holds the notes and copy that address.")

        files = readable = 0
        token, truncated = "", False
        try:
            for _ in range(MAX_COUNT_PAGES):
                response = service.files().list(
                    q=f"'{folder_id}' in parents and trashed = false",
                    fields="nextPageToken,files(id,mimeType)",
                    pageSize=100, pageToken=token or None,
                ).execute()
                for row in response.get("files", []):
                    files += 1
                    if row.get("mimeType") in SUPPORTED:
                        readable += 1
                token = response.get("nextPageToken", "")
                if not token:
                    break
            else:
                truncated = bool(token)
        except Exception as exc:                     # pragma: no cover - network
            raise DriveUnavailable(
                f"Opened “{meta.get('name')}” but could not list it: {exc}") from exc
        return FolderInfo(folder_id=folder_id, name=meta.get("name", ""),
                          files=files, readable=readable, truncated=truncated)

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
