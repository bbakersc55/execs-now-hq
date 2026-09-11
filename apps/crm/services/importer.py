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
    Company, Contact, ContactEmail, ContactPhone, ContactPipelinePosition,
    ContactType, ContactTypeLink, ImportBatch, ImportRow, Pipeline, PipelineStage,
    StageSemantic,
)
from apps.notes.models import Note
from apps.tenancy.models import AuditEvent

O = ImportRow.Outcome

#: Fields an import may write to a Contact. `notes` is deliberately absent —
#: FR-1.1a routes it to a real `note` row instead (§12.2).
CONTACT_FIELDS = {"first_name", "last_name", "title", "source", "background"}

#: Targets a column may be mapped to. `phone` and `tags` are multi-valued, and
#: `contact_type` / `pipeline_stage` drive the value-mapping sub-step, so none of
#: them go through the plain scalar path below.
MULTI_TARGETS = {"phone"}
TAG_TARGET = "tags"
TYPE_TARGET = "contact_type"
STAGE_TARGET = "pipeline_stage"
#: The owner's real CRM has both: a Status (type) column AND a separate Stage
#: column. They are mapped independently and both go through step 2b.
VALUE_TARGETS = (TYPE_TARGET, STAGE_TARGET)

TAG_SEPARATORS = ",;"
MAX_TAG_LENGTH = 64  # Contact.tags is varchar(64)[]


def parse(file_bytes: bytes, mapping: dict) -> list[dict]:
    text = file_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for index, raw in enumerate(reader, start=2):  # row 1 is the header
        rows.append({"row_number": index, "raw": {k: (v or "").strip() for k, v in raw.items()}})
    return rows


def split_tags(value: str) -> list[str]:
    """FR-1.1b — one tags column, comma or semicolon separated.

    De-duplicated case-insensitively but keeping the first spelling seen: a file
    carrying both "VIP" and "vip" means one tag, and the owner's own casing is
    the one worth keeping.
    """
    parts = [value]
    for separator in TAG_SEPARATORS:
        parts = [piece for part in parts for piece in part.split(separator)]
    tags, seen = [], set()
    for part in parts:
        tag = part.strip()
        if not tag or tag.lower() in seen:
            continue
        seen.add(tag.lower())
        tags.append(tag)
    return tags


def normalise_value_key(value: str) -> str:
    """Value-mapping keys match trimmed and case-insensitively — a CSV that
    spells the same status "Client" and "client " must not need two rows in the
    sub-step."""
    return (value or "").strip().lower()


def block_for(value_mapping: dict, target: str) -> dict:
    """The value-mapping block for one target column.

    Shape (both blocks optional):

        {"contact_type": {"column": "Status",
                          "values": {"Client": {"contact_type": "client",
                                                "pipeline": "Sales",
                                                "stage": "closed_won"}}},
         "pipeline_stage": {"column": "Stage", "pipeline": "Sales",
                            "values": {"Qualified": {"stage": "qualified"}}}}

    A `pipeline_stage` block names its pipeline once, at the top: the whole
    column belongs to one pipeline, which is the question the wizard asks first.
    A `contact_type` value may name a pipeline of its own, because "Client" can
    legitimately mean "put them at Closed Won in Sales".
    """
    return (value_mapping or {}).get(target) or {}


def value_rule(value_mapping: dict, target: str, value: str) -> dict:
    """The rule for one raw value in one column, or {} if never mapped."""
    wanted = normalise_value_key(value)
    if not wanted:
        return {}
    for key, rule in (block_for(value_mapping, target).get("values") or {}).items():
        if normalise_value_key(key) == wanted:
            return rule or {}
    return {}


def resolve_pipeline(tenant, reference):
    """A pipeline by id or by name.

    Ids are what the wizard sends, so a saved mapping profile survives a
    rename; names are accepted too because a hand-written mapping is far easier
    to read, and a UUID cannot collide with a pipeline name.
    """
    if not reference:
        return None
    pipelines = Pipeline.all_objects.filter(tenant=tenant)
    for pipeline in pipelines:
        if str(pipeline.pk) == str(reference):
            return pipeline
    for pipeline in pipelines:
        if pipeline.name.strip().lower() == str(reference).strip().lower():
            return pipeline
    return None


def resolve_stage(pipeline, reference):
    """A stage within one pipeline, by id or by code."""
    if pipeline is None or not reference:
        return None
    for stage in pipeline.stages.all():
        if str(stage.pk) == str(reference) or stage.code == str(reference):
            return stage
    return None


def rule_target_stage(tenant, rule, *, default_pipeline_ref=""):
    """(pipeline, stage, error) for one mapped value.

    `error` is a human sentence naming what could not be found, so the dry run
    can report it against the row instead of failing the import.
    """
    stage_ref = rule.get("stage") or ""
    if not stage_ref:
        return None, None, ""
    pipeline_ref = rule.get("pipeline") or default_pipeline_ref
    if not pipeline_ref:
        return None, None, "a stage was chosen but no pipeline was named"
    pipeline = resolve_pipeline(tenant, pipeline_ref)
    if pipeline is None:
        return None, None, f"no pipeline {pipeline_ref!r} in this practice"
    stage = resolve_stage(pipeline, stage_ref)
    if stage is None:
        return pipeline, None, (
            f"no stage {stage_ref!r} in pipeline {pipeline.name!r}"
        )
    return pipeline, stage, ""


def fires_client_invariant(stage):
    """FR-1.6a — only a `won` stage in a SALES pipeline makes someone a client.

    Reaching "Active Referrer" in the referral pipeline must not flag their
    company as a client company.
    """
    return bool(
        stage is not None
        and stage.semantic == StageSemantic.WON
        and stage.pipeline.kind == Pipeline.Kind.SALES
    )


class Resolved:
    """One CSV row, read through the column mapping.

    A plain `{target: value}` dict cannot express this any more: two columns may
    both map to `phone`, and collapsing them into one key silently dropped the
    second number.
    """

    __slots__ = ("values", "phones", "tags", "type_value", "stage_value")

    def __init__(self, values, phones, tags, type_value, stage_value):
        self.values = values
        self.phones = phones
        self.tags = tags
        self.type_value = type_value
        self.stage_value = stage_value


def resolve(raw: dict, mapping: dict) -> Resolved:
    values, phones, tags, type_value, stage_value = {}, [], [], "", ""
    for column, cell in raw.items():
        target = mapping.get(column, column)
        cell = (cell or "").strip()
        if target in MULTI_TARGETS:
            # File column order decides: the first phone column is the primary
            # one, which is the only ordering the owner can see and predict.
            if cell:
                phones.append(cell)
        elif target == TAG_TARGET:
            tags.extend(t for t in split_tags(cell) if t.lower() not in
                        {existing.lower() for existing in tags})
        elif target == TYPE_TARGET:
            type_value = cell
        elif target == STAGE_TARGET:
            stage_value = cell
        else:
            values[target] = cell
    return Resolved(values, phones, tags, type_value, stage_value)


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


def _validate(resolved, *, tenant, value_mapping, known_types):
    values = resolved.values
    errors = []
    if not (values.get("first_name") or values.get("last_name")):
        errors.append("row has neither a first nor a last name")
    email = (values.get("email") or "").strip()
    if email and ("@" not in email or email.startswith("@") or email.endswith("@")):
        errors.append(f"column 'email': {email!r} is not a valid address")
    for tag in resolved.tags:
        if len(tag) > MAX_TAG_LENGTH:
            # Caught here rather than at commit: Postgres would reject the whole
            # transaction, losing 200 good rows to one long tag.
            errors.append(
                f"column 'tags': {tag[:30]!r}… is {len(tag)} characters, "
                f"over the {MAX_TAG_LENGTH}-character limit"
            )

    for target, raw_value in (
        (TYPE_TARGET, resolved.type_value), (STAGE_TARGET, resolved.stage_value),
    ):
        if not raw_value:
            continue
        rule = value_rule(value_mapping, target, raw_value)
        if not rule:
            errors.append(
                f"column {target!r}: {raw_value!r} was not mapped. "
                "Map it, or ignore it."
            )
            continue
        if rule.get("ignore"):
            continue
        type_code = rule.get("contact_type") or ""
        if type_code and type_code not in known_types:
            errors.append(f"column {target!r}: no contact type {type_code!r} in this practice")
        _, _, stage_error = rule_target_stage(
            tenant, rule,
            default_pipeline_ref=block_for(value_mapping, target).get("pipeline", ""),
        )
        if stage_error:
            errors.append(f"column {target!r}: {stage_error}")
    return errors


def _preview_for(resolved, *, tenant, value_mapping, known_types):
    """What this row will actually write — the dry run's whole job (FR-1.28)."""
    placements, type_code, ignored = [], "", False

    for target, raw_value in (
        (TYPE_TARGET, resolved.type_value), (STAGE_TARGET, resolved.stage_value),
    ):
        if not raw_value:
            continue
        rule = value_rule(value_mapping, target, raw_value)
        if rule.get("ignore"):
            ignored = True
            continue
        if target == TYPE_TARGET:
            type_code = rule.get("contact_type") or ""
        pipeline, stage, _ = rule_target_stage(
            tenant, rule,
            default_pipeline_ref=block_for(value_mapping, target).get("pipeline", ""),
        )
        if stage is not None:
            placements.append({
                "pipeline": pipeline.name,
                "stage": stage.label,
                "stage_code": stage.code,
                "semantic": stage.semantic,
                "from_column": target,
                "fires_client_invariant": fires_client_invariant(stage),
            })

    return {
        "first_name": resolved.values.get("first_name", ""),
        "last_name": resolved.values.get("last_name", ""),
        "email": resolved.values.get("email", ""),
        "company": resolved.values.get("company", ""),
        "title": resolved.values.get("title", ""),
        "phones": [
            {"number": number, "is_primary": index == 0}
            for index, number in enumerate(resolved.phones)
        ],
        "tags": resolved.tags,
        "type_value": resolved.type_value,
        "stage_value": resolved.stage_value,
        "contact_type": type_code,
        "contact_type_label": known_types.get(type_code, ""),
        # One row may land in BOTH pipelines — that is the point of the change.
        "placements": placements,
        "value_ignored": ignored,
        "fires_client_invariant": any(p["fires_client_invariant"] for p in placements),
        "note": resolved.values.get("notes", ""),
    }


def _known_types(tenant):
    return {t.code: t.label for t in ContactType.all_objects.filter(tenant=tenant)}


def pipelines_payload(tenant):
    """Every pipeline with its stages — what the wizard needs to offer choices."""
    return [
        {
            "id": str(p.pk), "name": p.name, "kind": p.kind,
            "stages": [
                {"id": str(s.pk), "code": s.code, "label": s.label,
                 "semantic": s.semantic, "position": s.position}
                for s in p.stages.order_by("position")
            ],
        }
        for p in Pipeline.all_objects.filter(tenant=tenant).order_by("position", "name")
    ]


def scan_values(*, tenant, file_bytes, mapping):
    """Every distinct value in each value-mapped column, with its row count.

    Read with the same parser the import uses, not re-split in the browser: the
    sub-step must offer the values that will actually arrive, including the ones
    only quoting or encoding reveal.
    """
    columns = {}
    for target in VALUE_TARGETS:
        column = next((c for c, t in (mapping or {}).items() if t == target), "")
        if column:
            columns[target] = {"column": column, "counts": {}}

    for parsed in parse(file_bytes, mapping):
        resolved = resolve(parsed["raw"], mapping)
        for target, raw_value in (
            (TYPE_TARGET, resolved.type_value), (STAGE_TARGET, resolved.stage_value),
        ):
            if not raw_value or target not in columns:
                continue
            key = normalise_value_key(raw_value)
            entry = columns[target]["counts"].setdefault(
                key, {"value": raw_value, "count": 0}
            )
            entry["count"] += 1

    types = _known_types(tenant)
    return {
        "targets": [
            {
                "target": target,
                "column": data["column"],
                "values": sorted(
                    data["counts"].values(),
                    key=lambda e: (-e["count"], e["value"].lower()),
                ),
            }
            for target, data in columns.items()
        ],
        "contact_types": [{"code": c, "label": l} for c, l in types.items()],
        "pipelines": pipelines_payload(tenant),
    }


@transaction.atomic
def dry_run(*, tenant, filename, file_bytes, mapping, value_mapping=None, actor=None):
    """FR-1.28 — reports counts and every error with its row number and column.

    Writes NOTHING to contacts. The batch and its rows are the report.
    """
    value_mapping = value_mapping or {}
    known_types = _known_types(tenant)
    batch = ImportBatch.all_objects.create(
        tenant=tenant, filename=filename, status=ImportBatch.Status.DRY_RUN,
        created_by=actor, counts={}, mapping=mapping or {}, value_mapping=value_mapping,
    )
    counts = {"create": 0, "update": 0, "skip": 0, "error": 0, "ambiguous": 0}

    for parsed in parse(file_bytes, mapping):
        resolved = resolve(parsed["raw"], mapping)
        errors = _validate(
            resolved, tenant=tenant, value_mapping=value_mapping,
            known_types=known_types,
        )
        candidates = []
        if errors:
            outcome, contact = O.ERROR, None
            error_text = "; ".join(errors)
        else:
            outcome, contact, candidates = _match(tenant, resolved.values)
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
            preview=_preview_for(
                resolved, tenant=tenant, value_mapping=value_mapping,
                known_types=known_types,
            ),
        )

    batch.counts = counts
    batch.save(update_fields=["counts", "updated_at"])
    return batch


@transaction.atomic
def commit(batch, *, actor=None, mapping=None, value_mapping=None):
    """FR-1.30 — one transaction, and an ImportBatch that can be rolled back.

    `mapping` defaults to the one the dry run was computed with, so the commit
    writes what the preview showed rather than whatever the browser last held.
    """
    if batch.status != ImportBatch.Status.DRY_RUN:
        raise ValueError(f"Batch is {batch.status}; only a dry run can be committed.")

    tenant = batch.tenant
    mapping = mapping if mapping is not None else (batch.mapping or {})
    value_mapping = (
        value_mapping if value_mapping is not None else (batch.value_mapping or {})
    )
    for row in batch.rows.filter(outcome__in=[O.CREATE, O.UPDATE]).order_by("row_number"):
        resolved = resolve(row.raw, mapping)
        values = resolved.values
        company = _company_for(tenant, values)
        created = {"phone_ids": [], "type_link_ids": []}
        previous_related = {}

        if row.outcome == O.CREATE:
            contact = Contact.all_objects.create(
                tenant=tenant, company=company, owner=actor,
                tags=resolved.tags,
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

            # Union, not replace: a CSV that omits a tag the owner added by hand
            # is not an instruction to delete it.
            merged = _merge_tags(contact.tags, resolved.tags)
            tags_changed = merged != list(contact.tags)
            if tags_changed:
                previous_related["tags"] = list(contact.tags)
                contact.tags = merged

            if previous or tags_changed:
                contact.save()
            # FR-1.31 — the pre-import value of every field the import changed.
            row.previous_values = previous

        created["phone_ids"] = _write_phones(tenant, contact, resolved.phones)
        created["position_ids"] = []
        previous_related["positions"] = []
        for target, raw_value in (
            (TYPE_TARGET, resolved.type_value), (STAGE_TARGET, resolved.stage_value),
        ):
            link_id, position_id, previous_position = _apply_value_rule(
                tenant, contact, target, raw_value,
                value_mapping=value_mapping, actor=actor,
            )
            if link_id:
                created["type_link_ids"].append(link_id)
            if position_id:
                created["position_ids"].append(position_id)
            if previous_position:
                previous_related["positions"].append(previous_position)

        _maybe_create_note(tenant, contact, values, batch)
        row.created_related = created
        row.previous_related = previous_related
        row.save(update_fields=[
            "contact", "previous_values", "created_related", "previous_related",
            "updated_at",
        ])

    batch.status = ImportBatch.Status.COMMITTED
    batch.save(update_fields=["status", "updated_at"])
    AuditEvent.all_objects.create(
        tenant=tenant, actor=actor, verb="import.committed",
        target_type="import_batch", target_id=batch.pk, payload=batch.counts,
    )
    return batch


def _merge_tags(existing, incoming):
    """Union, de-duplicated case-insensitively, existing spellings winning."""
    merged = list(existing or [])
    seen = {t.lower() for t in merged}
    for tag in incoming:
        if tag.lower() not in seen:
            seen.add(tag.lower())
            merged.append(tag)
    return merged


def _write_phones(tenant, contact, numbers):
    """First mapped phone column is primary, the rest are not (FR-1.1c).

    `contact_phone_one_primary` is a partial unique index, so a contact that
    already has a primary number keeps it and the imported one lands alongside
    rather than failing the whole import.
    """
    if not numbers:
        return []
    has_primary = ContactPhone.all_objects.filter(
        tenant=tenant, contact=contact, is_primary=True
    ).exists()
    existing = {
        p.number.strip()
        for p in ContactPhone.all_objects.filter(tenant=tenant, contact=contact)
    }
    created = []
    for number in numbers:
        if number in existing:
            continue  # re-importing the same file must not stack duplicates
        phone = ContactPhone.all_objects.create(
            tenant=tenant, contact=contact, number=number,
            is_primary=not has_primary,
        )
        existing.add(number)
        has_primary = True
        created.append(str(phone.pk))
    return created


def _apply_value_rule(tenant, contact, target, raw_value, *, value_mapping, actor=None):
    """One value-mapped column, applied.

    Returns (created_type_link_id, created_position_id, previous_position).

    A stage placement goes through `pipeline.set_stage_from_import`, which runs
    the SAME `apply_client_invariant` a manual stage change runs (FR-1.6a) — so
    a value mapped to a `won` stage in the sales pipeline flags the company and
    adds the client type, or the import would create clients the rest of the app
    does not recognise. A `won` stage in the REFERRAL pipeline does neither,
    which is the whole reason the semantics are per pipeline.
    """
    from apps.crm.services import pipeline as pipeline_service

    rule = value_rule(value_mapping, target, raw_value)
    if not rule or rule.get("ignore"):
        return None, None, None

    created_link_id = None
    type_code = rule.get("contact_type") or ""
    if type_code:
        contact_type = ContactType.all_objects.filter(tenant=tenant, code=type_code).first()
        if contact_type is not None:
            existed = ContactTypeLink.all_objects.filter(
                tenant=tenant, contact=contact, contact_type=contact_type
            ).exists()
            # Routed through referral.add_type so an imported referral partner
            # lands on the touch cadence. `onboard=False`: a backfill must not
            # queue a first-touch email to forty partners met years ago — but a
            # partner with no cadence is invisible to the scheduler, which is
            # the bug this closes.
            from apps.crm.services import referral

            link = referral.add_type(contact, type_code, actor=actor, onboard=False)
            if link is not None and not existed:
                created_link_id = str(link.pk)

    _, stage, _ = rule_target_stage(
        tenant, rule,
        default_pipeline_ref=block_for(value_mapping, target).get("pipeline", ""),
    )
    if stage is None:
        return created_link_id, None, None

    before = pipeline_service.position_for(contact, stage.pipeline)
    previous_position = None
    if before is not None:
        if before.stage_id == stage.pk:
            return created_link_id, None, None
        # Rollback restores where they were, rather than deleting a position the
        # import only moved.
        previous_position = {"position_id": str(before.pk), "stage_id": str(before.stage_id)}

    pipeline_service.set_stage_from_import(contact, stage, actor=actor)
    after = pipeline_service.position_for(contact, stage.pipeline)
    created_position_id = str(after.pk) if before is None and after is not None else None
    return created_link_id, created_position_id, previous_position


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
            # A create. Phones, type links and pipeline positions all cascade
            # with the contact.
            contact.delete()
            deleted += 1
        else:
            for field, old in row.previous_values.items():
                setattr(contact, field, old)
            _undo_related(row, contact)
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


def _undo_related(row, contact):
    """Reverse what an UPDATE row wrote outside the scalar fields.

    The company's `is_client_company` flag is deliberately NOT unset: FR-1.6a
    rule 2 says leaving `client` unwinds nothing, and the company may have other
    live client contacts. Unflagging it is a manual act, and the rollback report
    is where that shows up rather than a silent difference.
    """
    created = row.created_related or {}
    previous = row.previous_related or {}

    if created.get("phone_ids"):
        ContactPhone.all_objects.filter(pk__in=created["phone_ids"]).delete()
    if created.get("type_link_ids"):
        ContactTypeLink.all_objects.filter(pk__in=created["type_link_ids"]).delete()
    # Positions the import CREATED are removed; positions it merely moved are
    # put back where they were.
    if created.get("position_ids"):
        ContactPipelinePosition.all_objects.filter(pk__in=created["position_ids"]).delete()
    for entry in previous.get("positions") or []:
        ContactPipelinePosition.all_objects.filter(
            pk=entry["position_id"]
        ).update(stage_id=entry["stage_id"])
    if "tags" in previous:
        contact.tags = previous["tags"]


def _edited_since_import(contact, batch):
    return contact.updated_at > batch.updated_at + timezone.timedelta(seconds=1)
