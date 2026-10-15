"""The practice's own words in digests, the value report, strategy conversion,
meeting approval and billing refusals (2026-10-15, Melissa's feedback).

Each place is checked with custom words (the custom words show, the defaults
do not) and, where a default text exists, that the default reads as before.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from django.template.loader import render_to_string

from apps.tenancy import words
from apps.tenancy.roles import MAY_CREATE_LABEL, may_create_label
from apps.work import digests
from apps.work.models import TaskUpdate

from . import registry_config  # noqa: F401

CUSTOM = {"goal": ["objective", "objectives"], "project": ["initiative", "initiatives"],
          "task": ["action", "actions"], "step": ["checkpoint", "checkpoints"]}
DEFAULT_WORDS = ("goal", "project", "task", "step")


@pytest.fixture
def worded(tenant_a):
    tenant_a.work_words = CUSTOM
    tenant_a.save(update_fields=["work_words"])
    return tenant_a


def _has_default_word(text: str) -> bool:
    import re

    return bool(re.search(r"\b(goals?|projects?|tasks?|steps?)\b", text, re.I))


def _checklist_update(tenant):
    task = SimpleNamespace(pk=uuid.uuid4(), title="Hire a bookkeeper", project=None,
                           goal=None, is_client_visible=True)
    return SimpleNamespace(task=task, tenant=tenant, tenant_id=tenant.pk,
                           kind=TaskUpdate.Kind.CHECKLIST_COMPLETED, to_value="Post the role",
                           from_value="", client_facing_line="")


# ------------------------------------------------------------------ digests

def test_digest_lines_use_the_practice_words(worded):
    w = words.of(worded)
    update = _checklist_update(worded)
    assert digests._describe(update, w) == "Hire a bookkeeper: checkpoint done — Post the role"
    assert digests._item(update, w)["line"] == "Checkpoint done: Post the role"
    body = digests.deterministic_body([(update, None)], w)
    assert "checkpoint done" in body and "step" not in body


def test_digest_lines_with_default_words_read_as_before(tenant_a):
    update = _checklist_update(tenant_a)
    assert digests._describe(update) == "Hire a bookkeeper: step done — Post the role"
    assert digests._item(update)["line"] == "Step done: Post the role"


def test_rendered_digest_uses_the_practice_words(worded):
    digest = SimpleNamespace(tenant=worded)
    text, html = digests.render(digest, [(_checklist_update(worded), None)])
    assert "Checkpoint done: Post the role" in text
    assert "Checkpoint done: Post the role" in html
    assert "Step done" not in text + html


def test_ai_prompt_is_unchanged_with_default_words():
    assert digests.ai_system(words.DEFAULT) is digests.AI_SYSTEM


def test_ai_prompt_names_the_practice_words(worded, monkeypatch):
    from apps.tenancy import claude

    seen = {}

    def complete(**kwargs):
        seen.update(kwargs)
        return "prose"

    monkeypatch.setattr(claude, "complete", complete)
    update = _checklist_update(worded)
    assert digests.narrative_for(worded, [(update, None)],
                                 contact=SimpleNamespace(pk=uuid.uuid4())) == "prose"
    system = seen["system"]
    assert system.startswith(digests.AI_SYSTEM)
    for one, many in CUSTOM.values():
        assert f'"{one}" (plural "{many}")' in system
    assert "checkpoint done" in seen["user_text"]


def test_ai_prompt_names_only_the_words_that_changed(tenant_a):
    tenant_a.work_words = {"task": ["action", "actions"]}
    system = digests.ai_system(words.of(tenant_a))
    added = system[len(digests.AI_SYSTEM):]
    assert '"action" (plural "actions")' in added
    assert "objective" not in added and '"goal"' not in added


# ------------------------------------------------------------- value report

def _value_report(w, blocks):
    return render_to_string("work/value_report.html", {
        "brand": SimpleNamespace(header_color="#000", accent_color="#000", logo=None),
        "practice": "P", "company": {"name": "Acme"}, "generated_on": "today",
        "timeline": None, "blocks": blocks, "is_single_goal": False, "words": w})


def test_value_report_uses_the_practice_words(worded):
    w = words.of(worded)
    empty = _value_report(w, [])
    assert "No objectives are being tracked" in empty and "goals" not in empty
    block = {"title": "Faster close", "headline": {}, "measure": {}, "completion": {}}
    assert "<h2>The objectives</h2>" in _value_report(w, [block])


def test_value_report_with_default_words_reads_as_before():
    assert "No goals are being tracked" in _value_report(words.DEFAULT, [])


# ----------------------------------------------------------------- strategy

def test_delete_refusal_uses_the_practice_words(worded):
    from apps.strategy.models import StrategySession
    from apps.strategy.session_admin import delete_refusal

    session = SimpleNamespace(archived_at="x", state=StrategySession.State.CONVERTED,
                              converted_at="x", tenant=worded)
    text = delete_refusal(session)
    assert "its objectives, initiatives and actions link back" in text
    assert not _has_default_word(text)
    session.tenant = None
    assert ("its goals, projects and tasks link back") in delete_refusal(session)


def test_conversion_refusal_uses_the_practice_words(worded, monkeypatch):
    from apps.strategy import conversion
    from apps.strategy.models import StrategySession

    row = SimpleNamespace(pk=uuid.uuid4())
    monkeypatch.setattr(conversion, "accepted_rows", lambda session: [row])
    assert StrategySession.State.CONVERTED != "in_progress"
    session = SimpleNamespace(state="in_progress", tenant=worded)
    with pytest.raises(conversion.ConversionRefused) as refused:
        conversion.convert(session, choices={str(row.pk): {"as": "skip"}})
    text = str(refused.value)
    assert "Choose an objective or an initiative for at least one" in text
    assert not _has_default_word(text)


# ------------------------------------------------------------------ meetings

def test_approval_refusal_uses_the_practice_words(worded):
    from apps.meetings import approval

    item = SimpleNamespace(tenant=worded, source_excerpt="")
    seat = SimpleNamespace(client_company=SimpleNamespace(name="Acme", pk=uuid.uuid4()),
                           user=None)
    with pytest.raises(approval.ApprovalRefused) as refused:
        approval._file_for_client(item, actor=None, role="FF",
                                  choice={"file": {"goal": "new"}}, seat=seat,
                                  contact=None, title="t", due=None)
    assert str(refused.value) == "Give the new objective a name."


# ------------------------------------------------------------------- billing

def test_billing_refusal_uses_the_practice_words(worded):
    from apps.billing.services import BillingError, _clean_lines

    for key, word in (("project", "initiative"), ("goal", "objective")):
        with pytest.raises(BillingError) as refused:
            _clean_lines(worded, [{"description": "Work", key: str(uuid.uuid4())}])
        assert str(refused.value) == f"That {word} is not in this practice."


# -------------------------------------------------------------------- roles

def test_may_create_label_uses_the_practice_words(worded):
    w = words.of(worded)
    assert may_create_label("tasks", w) == "Actions only"
    assert may_create_label("projects", w) == "Initiatives and actions"
    assert may_create_label("goals", w) == "Objectives too"
    for code in MAY_CREATE_LABEL:
        assert may_create_label(code, words.DEFAULT) == MAY_CREATE_LABEL[code]
