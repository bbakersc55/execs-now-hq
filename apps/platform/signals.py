"""A provisioned practice is "invited" until its owner first signs in (P2)."""

from __future__ import annotations

from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver


@receiver(user_logged_in)
def practice_owner_arrived(sender, request, user, **kwargs):
    from apps.tenancy.models import Membership, Role, Tenant

    membership = (Membership.all_objects.select_related("tenant")
                  .filter(user=user, role=Role.FF, revoked_at__isnull=True,
                          tenant__status=Tenant.Status.INVITED).first())
    if membership is not None:
        Tenant.objects.filter(pk=membership.tenant_id, status=Tenant.Status.INVITED) \
            .update(status=Tenant.Status.ACTIVE)
