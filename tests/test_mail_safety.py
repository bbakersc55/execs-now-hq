"""FR-0.7 and assumption H6 — a mis-send must be structurally impossible."""

from __future__ import annotations

import pytest
from django.test import override_settings

from apps.accounts.mailer import is_real_send_allowed


@override_settings(IS_LOCAL=True, DEV_REAL_SEND_ALLOWLIST=["bryan@example.invalid"])
def test_local_build_diverts_everything_not_on_the_allowlist():
    assert is_real_send_allowed("bryan@example.invalid") is True
    assert is_real_send_allowed("client@acme.invalid") is False


@override_settings(IS_LOCAL=True, DEV_REAL_SEND_ALLOWLIST=["bryan@example.invalid"])
def test_allowlist_matching_is_exact_and_case_insensitive():
    assert is_real_send_allowed("BRYAN@example.invalid") is True
    assert is_real_send_allowed("someone.else@example.invalid") is False


@override_settings(IS_LOCAL=False, DEV_REAL_SEND_ALLOWLIST=[])
def test_production_sends_normally():
    assert is_real_send_allowed("client@acme.invalid") is True


def test_wildcard_entries_are_rejected_at_startup():
    """H6 — one wildcard would put every colleague and client back in range."""
    import importlib

    with pytest.raises(RuntimeError, match="not an exact address"):
        with override_settings():
            import os
            os.environ["DEV_REAL_SEND_ALLOWLIST"] = "@getexecutivesnow.com"
            importlib.reload(importlib.import_module("config.settings"))
