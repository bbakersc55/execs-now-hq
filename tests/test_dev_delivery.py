"""Real-delivery visibility and control on dev builds (FR-0.7, assumption H6).

Found in Check 4: the Outbox did not say, before approval, whether approving
would reach a real person — and the only way to change the allow-list was to
edit `.env` and restart mid-check.
"""

from __future__ import annotations

import pytest
from django.test import override_settings

from apps.accounts.mailer import (
    AllowlistEntryInvalid, dev_allowlist, is_real_send_allowed,
    normalise_allowlist_entry,
)
from apps.crm.models import DevSendAllowlistEntry, OutboxMessage
from apps.tenancy.context import tenant_context
from apps.tenancy.models import AuditEvent

from . import registry_config  # noqa: F401
from .factories import DevSendAllowlistEntryFactory, OutboxMessageFactory

ALLOWLIST = "/api/dev-allowlist/"
EFFECTIVE = "/api/dev-allowlist/effective/"


# ------------------------------------------------------------- the H6 rule

@pytest.mark.parametrize("bad", [
    "@getexecutivesnow.com",       # bare domain
    "*@getexecutivesnow.com",      # wildcard
    "getexecutivesnow.com",        # no local part
    "bryan@",                      # no domain
    "bryan@localhost",             # no dot in the domain
    "",
    "   ",
])
def test_a_widening_entry_is_rejected(bad):
    """One of these would put every colleague and client at that domain back in
    range, which is the whole thing H6 exists to prevent."""
    with pytest.raises(AllowlistEntryInvalid):
        normalise_allowlist_entry(bad)


@pytest.mark.parametrize("raw,expected", [
    ("Bryan@GetExecutivesNow.com", "bryan@getexecutivesnow.com"),
    ("  spaced@example.co.uk  ", "spaced@example.co.uk"),
])
def test_a_valid_entry_is_normalised(raw, expected):
    assert normalise_allowlist_entry(raw) == expected


# ------------------------------------------------------- the effective list

@pytest.mark.django_db
@override_settings(DEV_REAL_SEND_ALLOWLIST=["fromenv@example.invalid"])
def test_env_and_database_entries_are_unioned(seeded_tenant):
    DevSendAllowlistEntryFactory(tenant=seeded_tenant, address="fromdb@example.invalid")

    assert dev_allowlist(seeded_tenant) == {
        "fromenv@example.invalid", "fromdb@example.invalid",
    }
    assert is_real_send_allowed("fromdb@example.invalid", seeded_tenant) is True
    assert is_real_send_allowed("fromenv@example.invalid", seeded_tenant) is True
    assert is_real_send_allowed("stranger@example.invalid", seeded_tenant) is False


@pytest.mark.django_db
@override_settings(PUBLIC_BASE_URL="https://app.getexecutivesnow.com", IS_LOCAL=False)
def test_off_a_localhost_build_every_recipient_is_real(seeded_tenant):
    """The guard is a dev mechanism only. In production nothing is held back."""
    assert is_real_send_allowed("anyone@example.invalid", seeded_tenant) is True


# ------------------------------------------------------------- the API

@pytest.mark.django_db
def test_ff_can_add_and_remove_an_address(seeded_tenant, ff, api):
    added = api.as_(ff).post(
        ALLOWLIST, {"address": "Bryan@Example.invalid", "note": "me"},
        content_type="application/json",
    )
    assert added.status_code == 201
    assert added.json()["address"] == "bryan@example.invalid"

    with tenant_context(seeded_tenant.pk):
        assert AuditEvent.objects.filter(verb="dev_allowlist.added").count() == 1

    removed = api.as_(ff).delete(f"{ALLOWLIST}{added.json()['id']}/")
    assert removed.status_code == 204
    with tenant_context(seeded_tenant.pk):
        assert not DevSendAllowlistEntry.objects.exists()
        assert AuditEvent.objects.filter(verb="dev_allowlist.removed").count() == 1


@pytest.mark.django_db
def test_the_api_rejects_a_wildcard_with_the_reason(seeded_tenant, ff, api):
    response = api.as_(ff).post(
        ALLOWLIST, {"address": "@getexecutivesnow.com"}, content_type="application/json",
    )
    assert response.status_code == 400
    assert "not an exact address" in str(response.json())


@pytest.mark.django_db
def test_the_same_address_cannot_be_added_twice(seeded_tenant, ff, api):
    body = {"address": "bryan@example.invalid"}
    assert api.as_(ff).post(ALLOWLIST, body, content_type="application/json").status_code == 201
    second = api.as_(ff).post(ALLOWLIST, body, content_type="application/json")
    assert second.status_code == 400
    assert "already on the list" in str(second.json())


@pytest.mark.django_db
@override_settings(DEV_REAL_SEND_ALLOWLIST=["fromenv@example.invalid"])
def test_effective_marks_env_entries_as_not_removable(seeded_tenant, ff, api):
    """`.env` is the deployment's floor — the UI cannot lower it."""
    DevSendAllowlistEntryFactory(tenant=seeded_tenant, address="fromdb@example.invalid")

    body = api.as_(ff).get(EFFECTIVE).json()

    assert body["from_env"] == ["fromenv@example.invalid"]
    assert [e["address"] for e in body["entries"]] == ["fromdb@example.invalid"]
    assert all(e["removable"] for e in body["entries"])
    assert body["effective"] == ["fromdb@example.invalid", "fromenv@example.invalid"]


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["CF", "VA"])
def test_only_the_ff_may_touch_the_allowlist(role, seeded_tenant, api):
    """Who may receive real mail is a safety setting, not CRM hygiene."""
    from .factories import MembershipFactory

    member = MembershipFactory(tenant=seeded_tenant, role=role)
    assert api.as_(member).get(ALLOWLIST).status_code == 403
    assert api.as_(member).post(
        ALLOWLIST, {"address": "x@example.invalid"}, content_type="application/json",
    ).status_code == 403


@pytest.mark.django_db
@override_settings(PUBLIC_BASE_URL="https://app.getexecutivesnow.com", IS_LOCAL=False)
def test_the_whole_mechanism_is_absent_on_a_non_localhost_build(seeded_tenant, ff, api):
    """404, not 403: in production this switch does not exist, and a 403 would
    advertise one that is not there."""
    client = api.as_(ff)
    assert client.get(ALLOWLIST).status_code == 404
    assert client.get(EFFECTIVE).status_code == 404
    assert client.post(
        ALLOWLIST, {"address": "x@example.invalid"}, content_type="application/json",
    ).status_code == 404


@pytest.mark.django_db
@override_settings(PUBLIC_BASE_URL="https://app.getexecutivesnow.com", IS_LOCAL=False)
def test_email_settings_does_not_advertise_the_section_in_production(
    seeded_tenant, ff, api
):
    body = api.as_(ff).get("/api/gmail-connection/").json()
    assert body["is_local_build"] is False


@pytest.mark.django_db
def test_email_settings_reports_a_localhost_build(seeded_tenant, ff, api):
    assert api.as_(ff).get("/api/gmail-connection/").json()["is_local_build"] is True


# ------------------------------------------------- the badge, before approval

@pytest.mark.django_db
@override_settings(DEV_REAL_SEND_ALLOWLIST=["bryan@example.invalid"])
def test_an_outbox_row_says_where_it_will_go_before_approval(seeded_tenant, ff, api):
    """`dev_real_send` is only written once a message has been SENT, which is
    too late for the person deciding whether to approve it."""
    OutboxMessageFactory(
        tenant=seeded_tenant, to_address="bryan@example.invalid",
        state=OutboxMessage.State.PENDING_APPROVAL,
    )
    OutboxMessageFactory(
        tenant=seeded_tenant, to_address="stranger@example.invalid",
        state=OutboxMessage.State.PENDING_APPROVAL,
    )

    rows = {r["to_address"]: r["delivery"] for r in api.as_(ff).get("/api/outbox/").json()}

    assert rows["bryan@example.invalid"]["target"] == "real"
    assert rows["bryan@example.invalid"]["label"] == "Real delivery"
    assert "real email to a real person" in rows["bryan@example.invalid"]["detail"]
    assert rows["stranger@example.invalid"]["target"] == "dev"
    assert rows["stranger@example.invalid"]["label"] == "Dev mailbox (Mailpit)"


@pytest.mark.django_db
def test_adding_an_address_flips_the_badge_without_a_restart(seeded_tenant, ff, api):
    """The point of storing it in the database: no `.env` edit, no restart, in
    the middle of a manual check."""
    OutboxMessageFactory(
        tenant=seeded_tenant, to_address="later@example.invalid",
        state=OutboxMessage.State.PENDING_APPROVAL,
    )
    before = api.as_(ff).get("/api/outbox/").json()[0]["delivery"]["target"]
    api.as_(ff).post(ALLOWLIST, {"address": "later@example.invalid"},
                     content_type="application/json")
    after = api.as_(ff).get("/api/outbox/").json()[0]["delivery"]["target"]

    assert (before, after) == ("dev", "real")
