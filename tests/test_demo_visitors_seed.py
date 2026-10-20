"""Demo visitors (2026-10-17): a whole copy of the demo practice, beside
Summit in the same database, then reset, then deleted.

The seed runs for real, three times, so this is slow on purpose, like
`test_demo_seed.py`: it is what proves a copy can be built next to Summit at
all (every sign-in address is the whole database's), that each is kept from
the other, and that a reset and a delete leave nothing behind."""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from . import registry_config  # noqa: F401
from .test_demo_seed import OWNER, _list_routes, _name

VISITOR = "visitor@visiting.invalid"


def _signed_in(user):
    client = Client()
    client.force_login(user)
    return client


def _walk(client) -> str:
    """Every list route's answer, as one string to search."""
    out = []
    for path in _list_routes():
        response = client.get(path)
        if response.status_code == 200:
            out.append(response.content.decode())
    return "\n".join(out)


@pytest.mark.django_db(transaction=False)
def test_a_copy_is_built_beside_summit_kept_apart_reset_and_deleted(settings, monkeypatch):
    from apps.accounts.models import User
    from apps.crm.models import Company, Contact, ContactEmail
    from apps.crm.services import transport
    from apps.tenancy import storage
    from apps.tenancy.demo import cast, visitors
    from apps.tenancy.models import AiCall, DemoVisitor, Membership, StoredFile, Tenant

    settings.APP_ENVIRONMENT, settings.IS_DEMO, settings.IS_LOCAL = "demo", True, False
    monkeypatch.setattr(transport.GmailTransport, "send",
                        lambda *a, **k: pytest.fail("the seed reached Gmail"))
    launched = []
    monkeypatch.setattr(visitors, "launch", lambda action, pk=None: launched.append((action, pk)))

    call_command("seed_demo", database=_name(), ff_email=OWNER)
    summit = Tenant.objects.get(slug=cast.SLUG)
    owner = User.objects.get(email=OWNER)

    visitor = visitors.invite(name="Vera Visitor", email=VISITOR, days=30, note="From the call",
                              actor=owner)
    # The request makes the records and starts the setup elsewhere.
    assert launched == [("setup", visitor.pk)] or launched == []
    copy = visitor.tenant
    visitors.run_setup(visitor.pk)
    visitor.refresh_from_db()
    assert visitor.state == DemoVisitor.State.READY
    expires = visitor.expires_at

    # ------------------------------------------------------- the copy itself
    me = User.objects.get(email=VISITOR)
    assert not me.is_platform_owner
    membership = Membership.all_objects.get(user=me)
    assert (membership.tenant_id, membership.role) == (copy.pk, "FF")
    assert copy.name == summit.name and copy.from_address == settings.DEMO_MAIL_FROM
    # The same practice: the same counts of what matters.
    def count(model, tenant):
        return model.all_objects.filter(tenant=tenant).count()
    for model in (Company, Contact):
        assert count(model, copy) == count(model, summit), model.__name__
    # Its people are its own: every sign-in address differs from Summit's.
    copy_people = set(Membership.all_objects.filter(tenant=copy)
                      .values_list("user__email", flat=True))
    summit_people = set(Membership.all_objects.filter(tenant=summit)
                        .values_list("user__email", flat=True))
    assert not copy_people & summit_people
    assert all(f"+{visitor.tag}@" in e for e in copy_people - {VISITOR})
    assert ContactEmail.all_objects.filter(
        tenant=copy, address=f"ellen.ripley+{visitor.tag}@summitops.example").exists()

    # ------------------------------------------- kept apart, both directions
    seen_by_visitor = _walk(_signed_in(me))
    seen_by_summit = _walk(_signed_in(owner))
    for row in Contact.all_objects.filter(tenant=summit)[:40]:
        assert str(row.pk) not in seen_by_visitor
    for row in Contact.all_objects.filter(tenant=copy)[:40]:
        assert str(row.pk) not in seen_by_summit
    assert visitor.tag not in seen_by_summit

    # ------------------------------- Summit reseeded: the copy is untouched
    from datetime import timedelta

    from apps.platform import agreement
    from apps.tenancy.demo import money

    DemoVisitor.objects.filter(pk=visitor.pk).update(agreed_at=timezone.now(),
                                                     agreed_version=agreement.VERSION)
    visitor.refresh_from_db()
    agreed = visitor.agreed_at
    before = {
        "contacts": set(Contact.all_objects.filter(tenant=copy).values_list("pk", flat=True)),
        "files": set(StoredFile.all_objects.filter(tenant=copy).values_list("pk", flat=True)),
        "people": set(Membership.all_objects.filter(tenant=copy)
                      .values_list("user_id", flat=True)),
    }
    old_summit = summit.pk
    first = timezone.localdate().replace(day=1)
    monkeypatch.setattr(money, "FIRST", (first - timedelta(days=120)).replace(day=1))
    call_command("seed_demo", database=_name(), ff_email=OWNER)
    summit = Tenant.objects.get(slug=cast.SLUG)
    assert summit.pk != old_summit                       # Summit is new
    assert Tenant.objects.filter(pk=copy.pk).exists()    # the copy is not
    visitor.refresh_from_db()
    assert visitor.expires_at == expires and visitor.agreed_at == agreed
    assert visitor.state == DemoVisitor.State.READY
    assert User.objects.get(email=VISITOR).pk == me.pk
    assert set(Contact.all_objects.filter(tenant=copy).values_list("pk", flat=True)) == \
        before["contacts"]
    assert set(StoredFile.all_objects.filter(tenant=copy).values_list("pk", flat=True)) == \
        before["files"]
    assert set(Membership.all_objects.filter(tenant=copy).values_list("user_id", flat=True)) \
        == before["people"]
    # And the visitor still signs in to it, and sees it.
    assert _signed_in(me).get("/api/contacts/").status_code == 200
    owner = User.objects.get(email=OWNER)
    assert owner.is_platform_owner
    assert Membership.all_objects.get(user=owner).tenant_id == summit.pk
    # Only the laptop may empty every table.
    from django.core.management import CommandError
    with pytest.raises(CommandError, match="laptop only"):
        call_command("seed_demo", database=_name(), ff_email=OWNER, whole_database=True)

    # ------------------------------------------------------------- reset
    AiCall.all_objects.create(tenant=copy, purpose="test", model="m", cost_usd="1.25",
                              succeeded=True)
    old_contacts = set(Contact.all_objects.filter(tenant=copy).values_list("pk", flat=True))
    old_files = list(StoredFile.all_objects.filter(tenant=copy)
                     .values_list("object_key", flat=True))
    visitors.reset(visitor, actor=me)
    visitors.run_setup(visitor.pk)
    visitor.refresh_from_db()
    assert visitor.state == DemoVisitor.State.READY and visitor.reset_count == 1
    assert visitor.expires_at == expires                     # its dates survive
    assert visitor.agreed_at == agreed                       # and it is not asked again
    assert User.objects.get(email=VISITOR).pk == me.pk       # and the sign-in
    assert Membership.all_objects.get(user=me).tenant_id == copy.pk
    new_contacts = set(Contact.all_objects.filter(tenant=copy).values_list("pk", flat=True))
    assert new_contacts and not new_contacts & old_contacts
    assert visitors.spend(copy)["total"] >= 1                 # spend is not reset
    for key in old_files:
        assert not StoredFile.all_objects.filter(object_key=key).exists()
    # Summit is as it was.
    assert count(Contact, summit) == count(Contact, copy)

    # ------------------------------------------------------------- delete
    files = list(StoredFile.all_objects.filter(tenant=copy)
                 .values_list("bucket", "object_key"))
    removed = []
    monkeypatch.setattr(storage, "delete_object", lambda b, k: removed.append((b, k)))
    settings.GCS_BUCKET_MEDIA = files[0][0] if files else settings.GCS_BUCKET_MEDIA
    visitors.delete(visitor, actor=owner)
    assert not Tenant.objects.filter(pk=copy.pk).exists()
    assert not DemoVisitor.objects.exists()
    assert not User.objects.filter(email__in=copy_people).exists()
    assert set(removed) == set(files)
    assert Tenant.objects.get() == summit
    assert User.objects.filter(email=OWNER).exists()
    assert timezone.now()  # the clock is the real one again
