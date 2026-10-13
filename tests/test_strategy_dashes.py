"""No em dashes in the map text Claude drafts (owner, 2026-10-12): a colon in
a title, a comma or a full stop in a sentence. A person's own words are not
touched."""

from __future__ import annotations

import json

import pytest

from apps.strategy import ai, dashes
from apps.strategy.models import StrategyPathNote

from . import registry_config  # noqa: F401
from .test_strategy_v3_session import (  # noqa: F401  (fixtures and helpers)
    answer, base, diagnose, fresh, keys, post, precall, prospect, rate, session, template,
)


@pytest.mark.parametrize("given,wanted", [
    ("Scheduling — one owner", "Scheduling: one owner"),
    ("Scheduling—one owner", "Scheduling: one owner"),
    ("Scheduling – one owner", "Scheduling: one owner"),
    ("— Scheduling —", "Scheduling"),
    ("A Weekly Scorecard", "A Weekly Scorecard"),
    ("", ""),
])
def test_a_dash_in_a_title_becomes_a_colon(given, wanted):
    assert dashes.title(given) == wanted


@pytest.mark.parametrize("given,wanted", [
    ("Jobs wait on Dana — nobody else can price.", "Jobs wait on Dana, nobody else can price."),
    ("Jobs wait on Dana — Nobody else can price.", "Jobs wait on Dana. Nobody else can price."),
    ("Jobs wait on Dana—nobody else can price.", "Jobs wait on Dana, nobody else can price."),
    ("One owner – and a price book.", "One owner, and a price book."),
    ("Done. — Then the next.", "Done. Then the next."),
    ("— Starts with one", "Starts with one"),
    ("Ends with one —", "Ends with one"),
    # A range between two figures is not a dash, and a hyphen never was.
    ("In 30–60 days, part-time.", "In 30–60 days, part-time."),
    ("No dash here.", "No dash here."),
])
def test_a_dash_in_a_sentence_becomes_a_comma_or_a_full_stop(given, wanted):
    assert dashes.sentence(given) == wanted


ROW = {"header": "Pricing — one owner", "statement": "Quotes wait on Dana — every time.",
       "bottleneck": "Pricing waits for Dana — nobody else can quote",
       "root_cause": "No price book — It lives in her head", "the_fix": "Write the book — then train two people",
       "owner_text": "Dana — owner", "horizon": 30,
       "measurable": "Quotes out in a day — not a week"}


@pytest.mark.django_db
def test_no_drafted_row_reaches_the_tray_with_an_em_dash(session, fake_claude):
    precall(session)
    rate(session)
    diagnose(session)
    fake_claude.reply = json.dumps({"rows": [ROW]})
    row, = ai.draft_map_rows(session)
    assert (row.header, row.proposed_header) == ("Pricing: one owner", "Pricing: one owner")
    assert row.statement == "Quotes wait on Dana, every time."
    assert row.bottleneck == "Pricing waits for Dana, nobody else can quote"
    assert row.root_cause == "No price book. It lives in her head"
    assert row.the_fix == "Write the book, then train two people"
    assert row.owner_text == "Dana, owner"
    assert row.measurable == "Quotes out in a day, not a week"
    for field in ("header", "proposed_header", "statement", "proposed_statement",
                  "bottleneck", "root_cause", "the_fix", "owner_text", "measurable"):
        assert "—" not in getattr(row, field) and "–" not in getattr(row, field), field


@pytest.mark.django_db
def test_the_drafted_mirror_and_pros_and_cons_have_none_either(session, ff, api, fake_claude):
    answer(session, keys(session, "mirror")[0], {"text": "Two branches, Dana off the tools"})
    fake_claude.reply = json.dumps({"goal": "Two branches — the owner off the tools.",
                                    "unlocks": "Pricing first — It frees her week."})
    post(api, ff, base(session) + "draft-mirror/")
    kept = fresh(session)
    assert kept.proposed_mirror_goal == "Two branches, the owner off the tools."
    assert kept.proposed_mirror_unlocks == "Pricing first. It frees her week."

    path_a, path_b = keys(session, "paths")
    for key in (path_a, path_b):
        answer(session, key, {"reaction": "Interested", "risk": "Cost", "leaning": ""})
    fake_claude.reply = json.dumps({
        "a": {"pros": ["You keep control — for now"], "cons": ["It slips — again"]},
        "b": {"pros": ["Someone owns it"], "cons": ["A cost — every month"]}})
    made = ai.draft_path_notes(session)
    assert sorted(note.text for note in made) == [
        "A cost, every month", "It slips, again", "Someone owns it",
        "You keep control, for now"]
    assert all("—" not in note.proposed_text for note in made)


@pytest.mark.django_db
def test_a_persons_own_dash_is_left_alone(session, ff, api):
    session.mirror_goal = "Two branches — what Dana said."
    session.save()
    assert fresh(session).mirror_goal == "Two branches — what Dana said."
    note = StrategyPathNote.objects.create(
        tenant=session.tenant, session=session, path="a", kind="pro",
        text="Their own words — kept", state=StrategyPathNote.State.ACCEPTED)
    assert "—" in note.text
