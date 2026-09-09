"""CSV import — three steps, reversible (FR-1.26 - FR-1.32).

The first real import of an existing book of business is the highest-
consequence data event in Beta, which is why the dry run is mandatory, the
commit is one transaction, and rollback is field-level rather than "restore
last night's backup".
"""

from __future__ import annotations

import csv
import io

from django.db import transaction
from django.utils import timezone

from apps.crm.models import (
    Company, Contact, ContactEmail, ImportBatch, ImportRow, PipelineStage,
)
from apps.notes.models import Note
from apps.tenancy.models import AuditEvent

O = ImportRow.Outcome

#: Fields an import may write to a Contact. `notes` is deliberately absent —
#: FR-1.1a routes it to a real `note` row instead (§12.2).
CONTACT_FIELDS = {"first_name", "last_name", "title", "source", "background"}


def parse(file_bytes: bytes, mapping: dict) -> list[dict]:
    text = file_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for index, raw in enumerate(reader, start=2):  # row 1 is the header
        rows.append({"row_number": index, "raw": {k: (v or "").strip() for k, v in raw.items()}})
    return rows


def _normalised_name(first, last):
    return f"{(first or '').strip().lower()} {(last or '').strip().lower()}".strip()


def _match(tenant, values):
    """FR-1.29 — exact email, then normalised name + company, then create new.

    Returns (outcome, contact, candidates). Ambiguity is REPORTED, never guessed.
    """
    email = (values.get("email") or "").strip().lower()
    if email:
        hit = ContactEmail.all_objects.filter(
            tenant=tenant, address__iexact=email, contact__deleted_at__isnull=True
        ).select_related("contact").first()
        if hit:
            return O.UPDATE, hit.contact, []

    name = _normalised_name(values.get("first_name"), values.get("last_name"))
    company_name = (values.get("company") or "").strip()
    if name and company_name:
        candidates = list(
            Contact.all_objects.filter(
                tenant=tenant, deleted_at__isnull=True,
                company__name__iexact=company_name,
            ).filter(
                first_name__iexact=(values.get("first_name") or "").strip(),
                last_name__iexact=(values.get("last_name") or "").strip(),
            )
        )
        if len(candidates) == 1:
            return O.UPDATE, candidates[0], []
        if len(candidates) > 1:
            return O.AMBIGUOUS, None, candidates
    return O.CREATE, None, []


def _validate(values):
    errors = []
    if not (values.get("first_name") or values.get("last_name")):
        errors.append("row has neither a first nor a last name")
    email = (values.get("email") or "").strip()
    if email and ("@" not in email or email.startswith("@") or email.endswith("@")):
        errors.append(f"column 'email': {email!r} is not a valid address")
    return errors


@transaction.atomic
def dry_run(*, tenant, filename, file_bytes, mapping, actor=None):
    """FR-1.28 — reports counts and every error with its row number and column.

    Writes NOTHING to contacts. The batch and its rows are the report.
    """
    batch = ImportBatch.all_objects.create(
        tenant=tenant, filename=filename, status=ImportBatch.Status.DRY_RUN,
        created_by=actor, counts={},
    )
    counts = {"create": 0, "update": 0, "skip": 0, "error": 0, "ambiguous": 0}

    for parsed in parse(file_bytes, mapping):
        values = {mapping.get(k, k): v for k, v in parsed["raw"].items()}
        errors = _validate(values)
        candidates = []
        if errors:
            outcome, contact = O.ERROR, None
            error_text = "; ".join(errors)
        else:
            outcome, contact, candidates = _match(tenant, values)
            error_text = ""
            if outcome == O.AMBIGUOUS:
                error_text = (
                    "more than one existing contact matches this name at this "
                    "company — a human must choose"
                )
        counts[outcome] += 1
        ImportRow.all_objects.create(
            tenant=tenant, import_batch=batch, row_number=parsed["row_number"],
            raw=parsed["raw"], outcome=outcome, error_text=error_text, contact=contact,
            candidate_ids=[str(c.pk) for c in candidates],
        )

    batch.counts = counts
    batch.save(update_fields=["counts", "updated_at"])
    return batch


@transaction.atomic
def commit(batch, *, actor=None, mapping=None):
    """FR-1.30 — one transaction, and an ImportBatch that can be rolled back."""
    if batch.status != ImportBatch.Status.DRY_RUN:
        raise ValueError(f"Batch is {batch.status}; only a dry run can be committed.")

    tenant = batch.tenant
    mapping = mapping or {}
    default_stage = PipelineStage.all_objects.filter(tenant=tenant, code="contact").first()

    for row in batch.rows.filter(outcome__in=[O.CREATE, O.UPDATE]).order_by("row_number"):
        values = {mapping.get(k, k): v for k, v in row.raw.items()}
        company = _company_for(tenant, values)

        if row.outcome == O.CREATE:
            contact = Contact.all_objects.create(
                tenant=tenant, company=company, owner=actor, stage=default_stage,
                **{f: values.get(f, "") for f in CONTACT_FIELDS if values.get(f)},
            )
            email = (values.get("email") or "").strip()
            if email:
                ContactEmail.all_objects.create(
                    tenant=tenant, contact=contact, address=email, is_primary=True
                )
            row.contact = contact
            row.previous_values = None  # a create; rollback deletes
        else:
            contact = row.contact
            previous = {}
            for field in CONTACT_FIELDS:
                new = values.get(field)
                if new and getattr(contact, field) != new:
                    previous[field] = getattr(contact, field)
                    setattr(contact, field, new)
            if previous:
                contact.save()
            # FR-1.31 — the pre-import value of every field the import changed.
            row.previous_values = previous

        _maybe_create_note(tenant, contact, values, batch)
        row.save(update_fields=["contact", "previous_values", "updated_at"])

    batch.status = ImportBatch.Status.COMMITTED
    batch.save(update_fields=["status", "updated_at"])
    AuditEvent.all_objects.create(
        tenant=tenant, actor=actor, verb="import.committed",
        target_type="import_batch", target_id=batch.pk, payload=batch.counts,
    )
    return batch


def _company_for(tenant, values):
    name = (values.get("company") or "").strip()
    if not name:
        return None
    company, _ = Company.all_objects.get_or_create(
        tenant=tenant, name=name, defaults={"deleted_at": None}
    )
    return company


def _maybe_create_note(tenant, contact, values, batch):
    """FR-1.1a — a notes column becomes a real note, not a blob on the contact."""
    body = (values.get("notes") or "").strip()
    if not body:
        return None
    return Note.all_objects.create(
        tenant=tenant, contact=contact, body=body,
        source=Note.Source.IMPORT, import_batch=batch,
        title="Imported note", title_is_auto=False,
    )


@transaction.atomic
def rollback(batch, *, actor=None):
    """FR-1.31 — reverts creates and field-level updates.

    A row whose contact was hand-edited after the import is LISTED AND SKIPPED,
    not silently clobbered.
    """
    if batch.status != ImportBatch.Status.COMMITTED:
        raise ValueError(f"Batch is {batch.status}; only a committed batch can be rolled back.")

    skipped, reverted, deleted = [], 0, 0
    batch.notes.all().delete()

    for row in batch.rows.filter(contact__isnull=False).select_related("contact"):
        contact = row.contact
        if contact is None:
            continue
        if _edited_since_import(contact, batch):
            skipped.append({"row": row.row_number, "contact": str(contact.pk)})
            continue
        if row.previous_values is None:
            contact.delete()
            deleted += 1
        else:
            for field, old in row.previous_values.items():
                setattr(contact, field, old)
            contact.save()
            reverted += 1

    batch.status = ImportBatch.Status.ROLLED_BACK
    batch.rolled_back_at = timezone.now()
    batch.save(update_fields=["status", "rolled_back_at", "updated_at"])
    report = {"deleted": deleted, "reverted": reverted, "skipped": skipped}
    AuditEvent.all_objects.create(
        tenant=batch.tenant, actor=actor, verb="import.rolled_back",
        target_type="import_batch", target_id=batch.pk, payload=report,
    )
    return report


def _edited_since_import(contact, batch):
    return contact.updated_at > batch.updated_at + timezone.timedelta(seconds=1)
