"""A person's documents (2026-11-17): offer letters, handbook
acknowledgments, reviews, exit interviews and others, uploaded or sent for
signature. A sensitive field: an HR Director and the person themself open
them, and each opening is logged. The upload says what never belongs here.
"""

from __future__ import annotations

import re

from apps.people.models import HELD_IN_PAYROLL, PersonDocument

MAX_BYTES = 15 * 1024 * 1024
TYPES = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg",
         "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx"}
NOT_HERE = ("Don't upload Social Security cards or numbers, bank details, I-9 documents, "
            "medical or leave paperwork, background checks or benefits forms: "
            + HELD_IN_PAYROLL)


class FileRefused(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def listed(record) -> list[dict]:
    out = []
    for d in (PersonDocument.all_objects.filter(person=record)
              .select_related("esign_document").order_by("-created_at")):
        e = d.esign_document
        out.append({
            "id": str(d.pk), "kind": d.kind, "kind_label": d.get_kind_display(),
            "title": d.title, "added_at": d.created_at.isoformat(),
            "signature": ({"state": e.state, "state_label": e.get_state_display(),
                           "document_id": str(e.pk)} if e else None),
            "has_file": bool(d.stored_file_id or (e is not None and (
                e.final_pdf_id or e.signed_pdf_id or e.pdf_id))),
        })
    return out


def _filename(title: str, suffix: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9]+", "-", title or "document").strip("-")[:80] or "document"
    return stem + suffix


def upload(record, *, kind: str, title: str, content: bytes, content_type: str, actor):
    from apps.tenancy import storage

    if kind not in PersonDocument.Kind.values:
        raise FileRefused("Choose what kind of document it is.")
    title = (title or "").strip()[:160]
    if not title:
        raise FileRefused("Give the document a title.")
    if content_type not in TYPES:
        raise FileRefused("Upload a PDF, a Word document, or a PNG or JPEG image.")
    if not content or len(content) > MAX_BYTES:
        raise FileRefused("The file is empty or larger than 15 MB.")
    stored = storage.save(tenant=record.tenant, content=content,
                          object_key=storage.object_key("people", _filename(title,
                                                                            TYPES[content_type])),
                          purpose="people_document", content_type=content_type)
    return PersonDocument.all_objects.create(tenant=record.tenant, person=record, kind=kind,
                                             title=title, stored_file=stored,
                                             uploaded_by=actor)


def content_of(document) -> tuple[bytes, str, str]:
    """(bytes, content type, filename): the upload, or the signed PDF as it
    stands (final, signed, or as sent)."""
    from apps.tenancy import storage

    if document.stored_file_id:
        stored = document.stored_file
    else:
        e = document.esign_document
        stored = e and (e.final_pdf or e.signed_pdf or e.pdf)
    if stored is None:
        raise FileRefused("There is no file for this document yet.", 404)
    content_type = stored.content_type or "application/pdf"
    return storage.read(stored), content_type, _filename(document.title,
                                                         TYPES.get(content_type, ".pdf"))
