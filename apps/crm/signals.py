"""Keep the search index honest at the moment a contact changes.

FR-1.33's index was refreshed only by the periodic `reindex_search` job, which
means a contact created a minute ago was unfindable until the job next ran —
exactly the failure that hid Module 1's 142 unindexed contacts, and the reason a
brand new contact could not be found in a picker. The job stays as the backstop
for paths that bypass signals (`bulk_create`, a raw `UPDATE`, a restored dump).
"""

from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.crm.models import Contact

#: The fields CONTACT_VECTOR is built from. A save that touches none of them
#: cannot change the vector, so it earns no second write.
INDEXED_FIELDS = frozenset({"first_name", "last_name", "title", "background", "source"})


@receiver(post_save, sender=Contact, dispatch_uid="crm.reindex_contact_on_save")
def reindex_on_save(sender, instance, created, update_fields=None, **kwargs):
    from apps.crm.services.search import reindex_contact

    if not created and update_fields is not None \
            and INDEXED_FIELDS.isdisjoint(update_fields):
        return
    # In the same transaction as the write on purpose: if that rolls back so does
    # this, and the row it would have described no longer exists.
    reindex_contact(instance)
