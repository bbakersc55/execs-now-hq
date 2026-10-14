"""A portal user is on a team from the moment they have a sign-in (P7 §7).

Every path that makes or restores a client membership (an invitation, a
restored one, the demo's seed, a test's factory) saves a `Membership`, so
this is the one place that cannot be forgotten. Without it a new portal user
would be on no team, which the rule reads as "a member with nothing
assigned", and would see less than everyone invited before them.
"""

from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.tenancy.models import Membership

#: The saves that can leave a client user without a team: a new sign-in, one
#: given back, and a move to another company.
PLACING_FIELDS = frozenset({"revoked_at", "client_company", "role"})


@receiver(post_save, sender=Membership, dispatch_uid="work.place_portal_user_on_a_team")
def place_on_save(sender, instance, created, update_fields=None, raw=False, **kwargs):
    from apps.work import teams

    if raw:
        return
    if not created and update_fields is not None \
            and PLACING_FIELDS.isdisjoint(update_fields):
        return
    # In the same transaction as the write: if that rolls back, so does this.
    teams.place_on_default(instance)
