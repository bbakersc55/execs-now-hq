"""`scrub_dev_data` (05_dev_environment.md §8; built 2026-09-29, Phase 7).

The command that rewrites every address in a database is the last thing that
should ever run against production, so its refusals are tested as carefully as
its scrub.
"""

from __future__ import annotations

import pytest
from django.conf import settings
from django.core.management import CommandError, call_command

from apps.accounts.models import MagicLinkToken, User
from apps.crm.models import (
    ContactEmail, ContactPhone, DevSendAllowlistEntry, GmailConnection, ImportRow, OutboxMessage,
)
from apps.tenancy.models import Tenant, TenantSecret
from apps.work.models import StakeholderToken

from . import registry_config  # noqa: F401
from .factories import (
    ClientCompanyFactory, ContactEmailFactory, ContactPhoneFactory, DevSendAllowlistEntryFactory,
    GmailConnectionFactory, ImportRowFactory, MagicLinkTokenFactory, MembershipFactory, OutboxMessageFactory, StakeholderTokenFactory,
    TenantSecretFactory,
)


def _name():
    return settings.DATABASES["default"]["NAME"]


def _scrub(**kw):
    call_command("scrub_dev_data", database=kw.pop("database", _name()), **kw)


@pytest.mark.django_db
def test_refuses_off_localhost(settings):
    settings.IS_LOCAL = False
    settings.PUBLIC_BASE_URL = "https://app.getexecutivesnow.com"
    with pytest.raises(CommandError, match="not localhost"):
        _scrub()


@pytest.mark.django_db
def test_refuses_a_remote_database(monkeypatch):
    monkeypatch.setitem(settings.DATABASES["default"], "HOST", "postgres.railway.internal")
    with pytest.raises(CommandError, match="not local"):
        _scrub()


@pytest.mark.django_db
def test_refuses_the_laptops_production_database_by_name(monkeypatch):
    """Today execsnowhq_dev *is* production and passes both checks above."""
    monkeypatch.setitem(settings.DATABASES["default"], "NAME", "execsnowhq_dev")
    with pytest.raises(CommandError, match="never scrubbed"):
        _scrub(database="execsnowhq_dev")


@pytest.mark.django_db
def test_refuses_when_the_typed_name_is_not_the_configured_one(seeded_tenant, in_tenant_a):
    ContactEmailFactory(tenant=seeded_tenant, address="dana@acme.com")
    with pytest.raises(CommandError, match="You typed"):
        _scrub(database="execsnowhq_local")
    assert ContactEmail.objects.get().address == "dana@acme.com", "nothing was touched"


@pytest.mark.django_db
def test_nothing_left_can_receive_mail_send_or_sign_in(seeded_tenant, in_tenant_a):
    ContactEmailFactory(tenant=seeded_tenant, address="dana@acme.com")
    ContactPhoneFactory(tenant=seeded_tenant, number="+13035550123")
    client = MembershipFactory(tenant=seeded_tenant, role="ECC",
                               client_company=ClientCompanyFactory(tenant=seeded_tenant))
    staff = MembershipFactory(tenant=seeded_tenant, role="FF")
    GmailConnectionFactory(tenant=seeded_tenant)
    TenantSecretFactory(tenant=seeded_tenant)
    OutboxMessageFactory(tenant=seeded_tenant)
    MagicLinkTokenFactory(tenant=seeded_tenant)
    StakeholderTokenFactory(tenant=seeded_tenant)
    # B7: a production copy carried a client's address in the allow-list, and
    # every import row's preview still held the CSV's addresses.
    DevSendAllowlistEntryFactory(tenant=seeded_tenant, address="dana@acme.com")
    ImportRowFactory(tenant=seeded_tenant, raw={"Email": "dana@acme.com"},
                     preview={"email": "dana@acme.com", "phones": ["+13035550123"]})
    Tenant.objects.filter(pk=seeded_tenant.pk).update(hold_all_digests=False)

    _scrub()

    assert all(a.endswith("@example.invalid")
               for a in ContactEmail.objects.values_list("address", flat=True))
    assert ContactPhone.objects.get().number.startswith("+1555")
    assert User.objects.get(pk=client.user_id).email.endswith("@example.invalid")
    assert User.objects.get(pk=staff.user_id).email.endswith("@example.invalid")
    for model in (GmailConnection, TenantSecret, OutboxMessage, MagicLinkToken,
                  StakeholderToken, DevSendAllowlistEntry):
        assert model.all_objects.count() == 0, model.__name__
    assert Tenant.objects.get(pk=seeded_tenant.pk).hold_all_digests is True
    assert list(ImportRow.objects.values_list("raw", "preview")) == [({}, {})]


@pytest.mark.django_db
def test_keep_staff_keeps_only_the_practices_own_sign_in(seeded_tenant, in_tenant_a):
    client = MembershipFactory(tenant=seeded_tenant, role="FCC",
                               client_company=ClientCompanyFactory(tenant=seeded_tenant))
    staff = MembershipFactory(tenant=seeded_tenant, role="VA")
    kept = staff.user.email
    _scrub(keep_staff=True)
    assert User.objects.get(pk=staff.user_id).email == kept
    assert User.objects.get(pk=client.user_id).email.endswith("@example.invalid")
