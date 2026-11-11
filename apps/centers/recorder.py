"""The practice library's recorder (P8): each of the practice's own records,
with its structure pulled out, kept as a `LibraryRecord` for the learning
tool to come. Only while the practice has a Command Center on, and never a
PIN-locked note (one locked later leaves the library). Nothing generates from
it yet: a count on Settings → Command Centers, and the owner's export and
delete, are all that reads it.

What is kept: notes; map rows accepted onto the map, and those discarded;
finished documents (an SOP when made from an SOP template); playbook runs.
"""

from __future__ import annotations

import logging

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone

log = logging.getLogger(__name__)


def _recording(tenant_id) -> bool:
    from apps.centers import services

    return bool(services.enabled(tenant_id))


def keep(tenant_id, *, kind, source_type, source_id, title="", structure=None):
    from apps.centers.models import LibraryRecord

    LibraryRecord.all_objects.update_or_create(
        tenant_id=tenant_id, source_type=source_type, source_id=source_id,
        defaults={"kind": kind, "title": (title or "")[:255], "structure": structure or {},
                  "recorded_at": timezone.now()})


def drop(tenant_id, source_type, source_id):
    from apps.centers.models import LibraryRecord

    LibraryRecord.all_objects.filter(tenant_id=tenant_id, source_type=source_type,
                                     source_id=source_id).delete()


def _safely(fn):
    """The library never gets in the way of the save that fed it."""
    def run(sender, instance, **kwargs):
        if kwargs.get("raw"):
            return
        try:
            fn(instance)
        except Exception as exc:  # noqa: BLE001
            log.warning("practice library: %s not kept (%s)", type(instance).__name__,
                        type(exc).__name__)
    return run


@receiver(post_save, sender="notes.Note", dispatch_uid="library_note")
def _note(sender, instance, **kwargs):
    _safely(_keep_note)(sender, instance, **kwargs)


def _keep_note(note):
    if note.pin_hash or note.deleted_at is not None:
        drop(note.tenant_id, "note", note.pk)
        return
    if not _recording(note.tenant_id):
        return
    keep(note.tenant_id, kind="note", source_type="note", source_id=note.pk, title=note.title,
         structure={"title": note.title, "body": note.body, "source": note.source,
                    "contact": str(note.contact_id or ""), "company": str(note.company_id or "")})


@receiver(post_delete, sender="notes.Note", dispatch_uid="library_note_gone")
def _note_gone(sender, instance, **kwargs):
    drop(instance.tenant_id, "note", instance.pk)


@receiver(post_save, sender="strategy.StrategyMapRow", dispatch_uid="library_map_row")
def _map_row(sender, instance, **kwargs):
    _safely(_keep_map_row)(sender, instance, **kwargs)


def _keep_map_row(row):
    from apps.centers.models import LibraryRecord

    kinds = {"accepted": LibraryRecord.Kind.MAP_ROW_ACCEPTED,
             "discarded": LibraryRecord.Kind.MAP_ROW_REJECTED}
    if row.state not in kinds or not _recording(row.tenant_id):
        return
    keep(row.tenant_id, kind=kinds[row.state], source_type="map_row", source_id=row.pk,
         title=row.bottleneck[:255],
         structure={"bottleneck": row.bottleneck, "root_cause": row.root_cause,
                    "fix": row.the_fix, "owner": row.owner_text, "horizon": row.horizon,
                    "measurable": row.measurable, "header": row.header,
                    "statement": row.statement})


@receiver(post_save, sender="esign.Document", dispatch_uid="library_document")
def _document(sender, instance, **kwargs):
    _safely(_keep_document)(sender, instance, **kwargs)


def _keep_document(document):
    from apps.centers.models import LibraryRecord

    if document.state != "complete" or not _recording(document.tenant_id):
        return
    original = document.template.original if document.template_id else ""
    kind = LibraryRecord.Kind.SOP if original.endswith("_sop") else LibraryRecord.Kind.DOCUMENT
    keep(document.tenant_id, kind=kind, source_type="document", source_id=document.pk,
         title=document.title,
         structure={"title": document.title, "template": original,
                    "template_name": document.template.name if document.template_id else "",
                    "fields": document.fields})


@receiver(post_save, sender="centers.PlaybookRun", dispatch_uid="library_playbook_run")
def _playbook_run(sender, instance, **kwargs):
    _safely(_keep_run)(sender, instance, **kwargs)


def _keep_run(run):
    if not _recording(run.tenant_id):
        return
    keep(run.tenant_id, kind="playbook_run", source_type="playbook_run", source_id=run.pk,
         title=run.playbook.name,
         structure={"playbook": run.playbook.name, "source_key": run.playbook.source_key,
                    "outline": run.playbook.outline, "company": str(run.company_id),
                    "start_date": run.start_date.isoformat(), "made": run.made})
