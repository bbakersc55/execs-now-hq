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
    "application/pdf": "A PDF is not read yet — export the notes as a Doc or text.",
    "video": "Audio and video are not read from Drive.",
    "audio": "Audio and video are not read from Drive.",
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
    return f"{mime_type or 'That file type'} is not read yet."


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
    #: RFC 3339. Only the backfill needs it — it walks the folder oldest first.
    created_time: str = ""
    parents: list = field(default_factory=list)
    #: For a file found under a folder watched at any depth: that folder's id,
    #: and the names of the folders between it and the file, outermost first.
    #: Exclusions match against these as well as the file's own name.
    root: str = ""
    path_names: list = field(default_factory=list)


#: How far up a file's parents are followed looking for a watched folder.
#: Google Meet notes sit two levels down; twelve is generous and still bounded.
MAX_ANCESTRY = 12


def locate(parents, roots, lookup, *, max_depth: int = MAX_ANCESTRY):
    """Which watched folder, if any, a file sits under — at any depth.

    `lookup(folder_id)` returns `(name, parents)` for a folder, or `None` when
    it cannot be read. Returns `(root_id, path_names)`, with `path_names` the
    folders between the root and the file, outermost first; or `None`.

    Walks upward from the file's parents rather than downward from the root,
    so a poll costs a lookup per *changed* file, not a listing of every
    meeting folder Google Meet has ever made.
    """
    roots = set(roots)
    frontier = [(parent, []) for parent in parents or []]
    seen = set()
    for _ in range(max_depth):
        following = []
        for folder_id, below in frontier:
            if folder_id in roots:
                return folder_id, below
            if folder_id in seen:
                continue
            seen.add(folder_id)
            meta = lookup(folder_id)
            if not meta:
                continue
            name, grandparents = meta
            following += [(up, [name] + below) for up in grandparents or []]
        if not following:
            return None
        frontier = following
    return None


@dataclass
class SubFolder:
    """A folder inside the watched one. Beta descends exactly one level."""

    folder_id: str
    name: str
    files: int = 0
    readable: int = 0


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
    #: One level down, because that is where some practices keep them — a
    #: folder per client, or per month. Named on the screen either way, so
    #: "nothing is being read" is never the first way you find out.
    subfolders: list = field(default_factory=list)
    oldest: str = ""
    newest: str = ""

    @property
    def readable_below(self) -> int:
        return sum(sub.readable for sub in self.subfolders)

    @property
    def readable_total(self) -> int:
        return self.readable + self.readable_below

    @property
    def folder_ids(self) -> list[str]:
        """Everything the watcher reads: this folder and one level below."""
        return [self.folder_id] + [sub.folder_id for sub in self.subfolders]


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
        self._folders: dict = {}

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

    def folder_meta(self, folder_id: str):
        """`(name, parents)` for one folder, remembered for this client's life.
        `None` when Drive will not say — a folder shared from elsewhere, say."""
        if folder_id not in self._folders:
            try:
                meta = self._service().files().get(
                    fileId=folder_id, fields="name,parents",
                    supportsAllDrives=True).execute()
                self._folders[folder_id] = (meta.get("name", ""), meta.get("parents") or [])
            except Exception:                        # pragma: no cover - network
                self._folders[folder_id] = None
        return self._folders[folder_id]

    def changes(self, page_token: str, *, folder_ids, deep_roots=()) -> DrivePage:
        """One page of changes, filtered to the watched folder **and one level
        below it** — some practices keep a folder per client or per month, and
        a watcher that reads only direct children finds nothing in those.

        Files under a `deep_roots` folder are kept at any depth, found by
        walking up from the file (`locate`)."""
        wanted = set(folder_ids)
        try:
            response = self._service().changes().list(
                pageToken=page_token, spaces="drive",
                fields=("nextPageToken,newStartPageToken,"
                        "changes(fileId,removed,file(id,name,mimeType,version,"
                        "trashed,parents,webViewLink,createdTime,"
                        "owners(emailAddress)))"),
                pageSize=100,
            ).execute()
        except Exception as exc:                     # pragma: no cover - network
            raise DriveUnavailable(str(exc)) from exc

        files = []
        for change in response.get("changes", []):
            raw = change.get("file") or {}
            if change.get("removed") or not raw:
                continue
            parents = raw.get("parents") or []
            placed = None
            if not wanted & set(parents):
                if not deep_roots or raw.get("mimeType") == FOLDER:
                    continue
                placed = locate(parents, deep_roots, self.folder_meta)
                if placed is None:
                    continue
            owners = raw.get("owners") or [{}]
            files.append(DriveFile(
                parents=parents,
                root=placed[0] if placed else "",
                path_names=placed[1] if placed else [],
                file_id=raw.get("id", ""), version=str(raw.get("version", "")),
                name=raw.get("name", ""), mime_type=raw.get("mimeType", ""),
                owner_email=(owners[0] or {}).get("emailAddress", ""),
                web_view_link=raw.get("webViewLink", ""),
                trashed=bool(raw.get("trashed")),
                created_time=raw.get("createdTime", ""),
            ))
        return DrivePage(files=files,
                         next_page_token=response.get("nextPageToken", ""),
                         new_start_page_token=response.get("newStartPageToken", ""))

    def open_folder(self, folder_id: str) -> str:
        """The folder's name, having proved it is a folder this account can
        read. The cheap check, for a folder watched at any depth: describing
        Google Meet would count every meeting folder it has ever made."""
        try:
            meta = self._service().files().get(
                fileId=folder_id, fields="id,name,mimeType,trashed").execute()
        except Exception as exc:                     # pragma: no cover - network
            raise DriveUnavailable(
                "Drive would not open that folder. Check the link, and that the "
                "folder is on the Google account you connected.") from exc
        if meta.get("trashed"):
            raise DriveUnavailable("That folder is in the Drive bin.")
        if meta.get("mimeType") != FOLDER:
            raise DriveUnavailable(
                f"\u201c{meta.get('name') or folder_id}\u201d is a file, not a folder.")
        return meta.get("name", "")

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

        try:
            here = self._count(service, folder_id)
            subfolders, dates = [], [here["oldest"], here["newest"]]
            # One level, and one only. Two would be a crawl of somebody's whole
            # Drive from a single pasted link.
            for child in here.pop("folders"):
                below = self._count(service, child["id"])
                subfolders.append(SubFolder(folder_id=child["id"],
                                            name=child.get("name", ""),
                                            files=below["files"],
                                            readable=below["readable"]))
                dates += [below["oldest"], below["newest"]]
            dates = sorted(d for d in dates if d)
            here["oldest"], here["newest"] = (dates[0], dates[-1]) if dates else ("", "")
        except DriveUnavailable:
            raise
        except Exception as exc:                     # pragma: no cover - network
            raise DriveUnavailable(
                f"Opened “{meta.get('name')}” but could not list it: {exc}") from exc
        return FolderInfo(folder_id=folder_id, name=meta.get("name", ""),
                          files=here["files"], readable=here["readable"],
                          truncated=here["truncated"], subfolders=subfolders,
                          oldest=here["oldest"], newest=here["newest"])

    def _count(self, service, folder_id: str) -> dict:
        """One folder's direct children: how many, how many readable, the date
        range, and the folders among them."""
        files = readable = 0
        folders, oldest, newest = [], "", ""
        token, truncated = "", False
        for _ in range(MAX_COUNT_PAGES):
            response = service.files().list(
                q=f"'{folder_id}' in parents and trashed = false",
                fields="nextPageToken,files(id,name,mimeType,createdTime)",
                pageSize=100, pageToken=token or None,
            ).execute()
            for row in response.get("files", []):
                if row.get("mimeType") == FOLDER:
                    folders.append(row)
                    continue
                files += 1
                if row.get("mimeType") in SUPPORTED:
                    readable += 1
                    created = row.get("createdTime", "")
                    oldest = min(oldest or created, created) if created else oldest
                    newest = max(newest, created)
            token = response.get("nextPageToken", "")
            if not token:
                break
        else:
            truncated = bool(token)
        return {"files": files, "readable": readable, "folders": folders,
                "oldest": oldest, "newest": newest, "truncated": truncated}

    def files_in(self, folder_ids, *, created_from: str = "",
                 page_size: int = 50, max_pages: int = 1) -> list[DriveFile]:
        """Readable files in these folders, **oldest first** (FR-5.1b).

        The backfill walks the folder in the order the meetings happened, so a
        queue half-built is the first half of the engagement rather than a
        random scatter of it.
        """
        service = self._service()
        clause = " or ".join(f"'{fid}' in parents" for fid in folder_ids)
        query = f"({clause}) and trashed = false"
        if created_from:
            query += f" and createdTime >= '{created_from}'"
        found, token = [], None
        for _ in range(max_pages):
            try:
                response = service.files().list(
                    q=query, orderBy="createdTime", pageSize=page_size,
                    pageToken=token,
                    fields=("nextPageToken,files(id,name,mimeType,version,trashed,"
                            "createdTime,webViewLink,owners(emailAddress))"),
                ).execute()
            except Exception as exc:                 # pragma: no cover - network
                raise DriveUnavailable(
                    f"Drive would not list the folder: {exc}") from exc
            for raw in response.get("files", []):
                if raw.get("mimeType") == FOLDER:
                    continue
                owners = raw.get("owners") or [{}]
                found.append(DriveFile(
                    file_id=raw.get("id", ""), version=str(raw.get("version", "")),
                    name=raw.get("name", ""), mime_type=raw.get("mimeType", ""),
                    owner_email=(owners[0] or {}).get("emailAddress", ""),
                    web_view_link=raw.get("webViewLink", ""),
                    trashed=bool(raw.get("trashed")),
                    created_time=raw.get("createdTime", ""),
                ))
            token = response.get("nextPageToken")
            if not token:
                break
        return found

    def search(self, name_pattern: str, *, roots, created_from: str = "",
               page_size: int = 50, max_pages: int = 10) -> list[DriveFile]:
        """Google Docs named like `name_pattern`, under one of `roots` at any
        depth, **oldest first** — the backfill's listing for a folder watched
        at any depth.

        Asked by name rather than by folder, because a folder watched at any
        depth may hold hundreds of meeting folders and Drive's query language
        cannot say "anywhere below". Each hit is then placed by `locate`.
        """
        service = self._service()
        safe = name_pattern.replace("\\", "\\\\").replace("'", "\\'")
        query = (f"name contains '{safe}' and mimeType = '{GOOGLE_DOC}' "
                 "and trashed = false")
        if created_from:
            query += f" and createdTime >= '{created_from}'"
        found, token = [], None
        for _ in range(max_pages):
            try:
                response = service.files().list(
                    q=query, orderBy="createdTime", pageSize=page_size,
                    pageToken=token,
                    fields=("nextPageToken,files(id,name,mimeType,version,trashed,"
                            "createdTime,webViewLink,parents,owners(emailAddress))"),
                ).execute()
            except Exception as exc:                 # pragma: no cover - network
                raise DriveUnavailable(f"Drive would not search: {exc}") from exc
            for raw in response.get("files", []):
                placed = locate(raw.get("parents") or [], roots, self.folder_meta)
                if placed is None:
                    continue
                owners = raw.get("owners") or [{}]
                found.append(DriveFile(
                    file_id=raw.get("id", ""), version=str(raw.get("version", "")),
                    name=raw.get("name", ""), mime_type=raw.get("mimeType", ""),
                    owner_email=(owners[0] or {}).get("emailAddress", ""),
                    web_view_link=raw.get("webViewLink", ""),
                    trashed=bool(raw.get("trashed")),
                    created_time=raw.get("createdTime", ""),
                    parents=raw.get("parents") or [],
                    root=placed[0], path_names=placed[1],
                ))
            token = response.get("nextPageToken")
            # Hits outside the roots are dropped, so a page of Drive's is not a
            # page of ours: keep asking until ours is full or Drive runs out.
            # A short list therefore means the end, which the backfill relies on.
            if not token or len(found) >= page_size:
                break
        return found

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
