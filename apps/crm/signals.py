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


# ------------------------------------------------ activity (stage rules, part 2)
# An email either way, a note, a meeting and a finished task are activity on a
# contact: an idle rule counts its days from the last of them. A stage move is
# activity too, set by `pipeline.change_stage` itself.

def _touch(contact_id, tenant_id):
    if contact_id and tenant_id:
        from apps.crm.services.stage_rules import touch

        touch(contact_id, tenant_id)


@receiver(post_save, sender="crm.EmailMessage", dispatch_uid="crm.activity_email")
def activity_on_email(sender, instance, created, **kwargs):
    if created:
        thread = instance.thread
        _touch(thread.contact_id if thread else None, instance.tenant_id)
        # Pipeline part 3: the contact sending any email stops their follow-ups.
        if instance.direction == "inbound" and thread is not None and thread.contact_id:
            from apps.crm.models import Contact
            from apps.crm.services import follow_ups

            contact = Contact.all_objects.filter(pk=thread.contact_id).first()
            if contact is not None:
                follow_ups.stop_all(contact, reason="replied")


@receiver(post_save, sender="notes.Note", dispatch_uid="crm.activity_note")
def activity_on_note(sender, instance, created, **kwargs):
    if created:
        _touch(instance.contact_id, instance.tenant_id)


@receiver(post_save, sender="meetings.MeetingParticipant", dispatch_uid="crm.activity_meeting")
def activity_on_meeting(sender, instance, created, **kwargs):
    if created:
        _touch(instance.contact_id, instance.tenant_id)


@receiver(post_save, sender="crm.Task", dispatch_uid="crm.activity_task_done")
def activity_on_task_done(sender, instance, created, update_fields=None, **kwargs):
    if instance.status == instance.Status.DONE and (
            created or update_fields is None or "status" in update_fields):
        _touch(instance.contact_id, instance.tenant_id)
