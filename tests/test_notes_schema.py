"""Module 2 schema invariants — asserted against Postgres, not the ORM's view of it.

The search index is a generated column, so these tests write through the
paths a view would NOT use — `QuerySet.update()`, straight to the columns —
and check the index anyway. If locked text is findable after a bulk update,
the invariant was never structural.
"""

from __future__ import annotations

import pytest
from django.contrib.postgres.search import SearchQuery
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.notes.models import SEARCH_CONFIG, Note

from . import registry_config  # noqa: F401
from .factories import NoteFactory

SECRET = "CONFIDENTIAL SEVERANCE DISCUSSION"


def _found(tenant, term):
    return set(
        Note.all_objects.filter(
            tenant=tenant, search_vector=SearchQuery(term, config=SEARCH_CONFIG)
        ).values_list("pk", flat=True)
    )


def _lock(note):
    Note.all_objects.filter(pk=note.pk).update(pin_hash="x", pin_set_at=timezone.now())


@pytest.mark.django_db
def test_an_unlocked_note_is_searchable_by_title_and_body(seeded_tenant):
    note = NoteFactory(tenant=seeded_tenant, title="HR matter", body=SECRET)
    assert note.pk in _found(seeded_tenant, "severance")
    assert note.pk in _found(seeded_tenant, "HR matter")


@pytest.mark.django_db
def test_locking_removes_the_body_from_the_index_even_via_bulk_update(seeded_tenant):
    note = NoteFactory(tenant=seeded_tenant, title="HR matter", body=SECRET)
    _lock(note)  # bypasses every model method and view
    assert note.pk not in _found(seeded_tenant, "severance")
    assert note.pk in _found(seeded_tenant, "HR matter"), "A typed title stays findable."


@pytest.mark.django_db
def test_a_locked_auto_titled_note_indexes_nothing(seeded_tenant):
    """FR-2.11b at the index: the auto title IS the body's first line."""
    note = NoteFactory(tenant=seeded_tenant, title=SECRET, title_is_auto=True,
                       body=SECRET + "\nmore detail")
    _lock(note)
    assert note.pk not in _found(seeded_tenant, "severance")
    assert note.pk not in _found(seeded_tenant, "confidential")


@pytest.mark.django_db
def test_clearing_the_pin_restores_the_body_to_the_index(seeded_tenant):
    note = NoteFactory(tenant=seeded_tenant, title="HR matter", body=SECRET)
    _lock(note)
    Note.all_objects.filter(pk=note.pk).update(pin_hash=None, pin_set_at=None)
    assert note.pk in _found(seeded_tenant, "severance")


@pytest.mark.django_db
def test_only_an_accepted_summary_is_searchable(seeded_tenant):
    note = NoteFactory(tenant=seeded_tenant, body="call notes",
                       proposed_summary="Discussed the warehouse relocation",
                       summary_state=Note.SummaryState.PROPOSED)
    assert note.pk not in _found(seeded_tenant, "warehouse"), "A proposal was indexed."

    Note.all_objects.filter(pk=note.pk).update(
        summary="Discussed the warehouse relocation", summary_state="accepted"
    )
    assert note.pk in _found(seeded_tenant, "warehouse")


@pytest.mark.django_db
def test_a_summary_cannot_be_stored_without_acceptance(seeded_tenant):
    """R3 in the database: the draft reaches `summary` only through acceptance."""
    note = NoteFactory(tenant=seeded_tenant)
    for state in ("none", "drafting", "proposed", "discarded", "failed"):
        with pytest.raises(IntegrityError), transaction.atomic():
            Note.all_objects.filter(pk=note.pk).update(summary="x", summary_state=state)


@pytest.mark.django_db
def test_a_pin_hash_requires_its_set_time(seeded_tenant):
    note = NoteFactory(tenant=seeded_tenant, title="t")
    with pytest.raises(IntegrityError), transaction.atomic():
        Note.all_objects.filter(pk=note.pk).update(pin_hash="x")
