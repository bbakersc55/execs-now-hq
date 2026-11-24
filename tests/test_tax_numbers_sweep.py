"""The AI and MCP sweep, with a full tax number held (owner, 2026-11-24): the
owner's intake holds a Social Security number, and every MCP tool and prompt,
and every in-app AI feature that takes company data, is run again. Neither
the number nor its digits may reach any of them. The static check of every
module that calls Claude (tests/test_agreements_ai_sweep.py) already shows
none of them reads intakes or their secrets."""

from __future__ import annotations

import pytest

from apps.intake import vault
from apps.tenancy.context import tenant_context

from . import test_agreements_ai_sweep as sweep
from .test_agreements import aw, fake, world  # noqa: F401
from .test_agreements_ai_sweep import signed  # noqa: F401

pytestmark = pytest.mark.django_db(transaction=True)

SSN = "078-05-1120"
SHAPES = (SSN, "078051120", "078 05 1120")


@pytest.fixture
def with_ssn(signed, monkeypatch):  # noqa: F811
    sub = signed["agreement"].submission
    sub.answers = {**(sub.answers or {}), "tax": {"kind": "ssn"}}
    sub.save(update_fields=["answers"])
    with tenant_context(sub.tenant_id):
        vault.put(sub, vault.Kind.TAX_ID, "", SSN)
    assert vault.value(sub, "tax_id") == SSN
    monkeypatch.setattr(sweep, "NEVER", sweep.NEVER + SHAPES)
    return signed


def test_no_mcp_tool_or_prompt_shows_a_tax_number(with_ssn):
    sweep.test_no_mcp_tool_or_prompt_ever_shows_the_owner_or_the_agreement(with_ssn)


def test_no_ai_feature_is_sent_a_tax_number(with_ssn, fake_claude):
    sweep.test_no_ai_feature_that_takes_company_data_is_sent_the_owner_or_the_agreement(
        with_ssn, fake_claude)


def test_no_module_that_calls_claude_reads_the_tax_number_module():
    from pathlib import Path
    import re

    apps = Path(__file__).resolve().parent.parent / "apps"
    for path in apps.rglob("*.py"):
        text = path.read_text()
        if re.search(r"complete_with_call\(|claude\.complete\(", text) and \
                not (path.parent.name == "tenancy" and path.name == "claude.py"):
            for word in ("taxnumbers", "SubmissionSecret", "vault"):
                assert word not in text, f"{path} mentions {word}"
