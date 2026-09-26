"""The map tray, after dry run 2 (2026-09-26): one session produced 45
candidate rows, many on the same theme.

- a draft run proposes at most five, and is told what is already there;
- Consolidate merges map and tray into 3–5 targets (10 at most), each citing
  what it merges, **proposed** — never applied;
- an accepted row can be taken off the map again, audited.
"""

from __future__ import annotations

import json

import pytest

from apps.strategy import ai, services
from apps.strategy.models import StrategyMapRow
from apps.strategy.seed import seed_tenant
from apps.tenancy.models import AiCall, AuditEvent

from . import registry_config  # noqa: F401
from .factories import CompanyFactory, ContactFactory

PROPOSED, ACCEPTED, DISCARDED = (StrategyMapRow.State.PROPOSED,
                                 StrategyMapRow.State.ACCEPTED,
                                 StrategyMapRow.State.DISCARDED)


@pytest.fixture
def session(seeded_tenant, in_tenant_a, ff):
    template = seed_tenant(seeded_tenant)
    company = CompanyFactory(tenant=seeded_tenant, name="Acme Facilities")
    contact = ContactFactory(tenant=seeded_tenant, first_name="Dana", last_name="Reyes",
                             company=company)
    s = services.start(tenant=seeded_tenant, contact=contact, template=template,
                       owner=ff.user)
    services.save_answer(s, question_key="s4_span_of_control",
                         value={"said": "One supervisor covers 14 sites.",
                                "cause": "We never hired area leads.",
                                "tried": "Overtime."}, answered_by="fractional")
    return s


def row(session, bottleneck, state, **extra):
    return StrategyMapRow.objects.create(tenant=session.tenant, session=session,
                                         bottleneck=bottleneck, state=state, **extra)


def rows_reply(n, prefix="Theme"):
    return json.dumps([{"bottleneck": f"{prefix} {i}", "root_cause": "", "the_fix": "",
                        "owner_text": "", "horizon": 30, "measurable": ""}
                       for i in range(n)])


def user_text(fake):
    return json.dumps(fake.requests[-1]["messages"], ensure_ascii=False)


# ----------------------------------------------------------- (a) the cap

@pytest.mark.django_db
def test_a_draft_run_proposes_at_most_five_whatever_the_model_sends(session, ff, api,
                                                                    fake_claude):
    fake_claude.reply = rows_reply(12)
    drafted = api.as_(ff).post(f"/api/strategy-sessions/{session.pk}/draft-rows/")
    assert len(drafted.json()["drafted"]) == 5
    assert StrategyMapRow.objects.filter(session=session).count() == 5
    assert "AT MOST FIVE" in fake_claude.requests[-1]["system"]


@pytest.mark.django_db
def test_a_draft_run_is_told_what_is_on_the_map_and_in_the_tray(session, ff, api,
                                                                fake_claude):
    row(session, "Supervisor overload", ACCEPTED, the_fix="Area lead per 8 sites")
    row(session, "Hiring takes too long", PROPOSED)
    row(session, "A discarded idea", DISCARDED)
    fake_claude.reply = "[]"
    api.as_(ff).post(f"/api/strategy-sessions/{session.pk}/draft-rows/")
    sent = user_text(fake_claude)
    assert "do not repeat their themes" in sent
    assert "(on the map) Supervisor overload — fix: Area lead per 8 sites" in sent
    assert "(in the tray) Hiring takes too long" in sent
    assert "A discarded idea" not in sent


# ----------------------------------------------------- (b) consolidate

@pytest.mark.django_db
def test_consolidate_proposes_merged_rows_that_cite_their_originals(session, ff, api,
                                                                    fake_claude):
    a = row(session, "Supervisor overload", ACCEPTED, owner_text="Integrator")
    b = row(session, "One supervisor, 14 sites", PROPOSED)
    c = row(session, "Hiring is slow", PROPOSED, mechanics_note="MARKER-PRIVATE")
    fake_claude.reply = json.dumps([
        {"bottleneck": "Supervision does not scale", "root_cause": "No area leads",
         "the_fix": "Area lead per 8 sites", "owner_text": "Integrator", "horizon": 60,
         "measurable": "Sites per supervisor", "merges": [1, 2]},
        {"bottleneck": "Hiring is slow", "merges": [3]},
        # Cites nothing real: a new claim, not a merge — dropped.
        {"bottleneck": "Invented target", "merges": [9]},
        # Cites a row another target already took — dropped.
        {"bottleneck": "Double counted", "merges": [1]},
    ])
    made = api.as_(ff).post(f"/api/strategy-sessions/{session.pk}/consolidate/")
    assert made.status_code == 201
    drafted = made.json()["drafted"]
    assert [d["bottleneck"] for d in drafted] == ["Supervision does not scale",
                                                  "Hiring is slow"]
    assert [m["id"] for m in drafted[0]["merged_from"]] == [str(a.pk), str(b.pk)]
    assert drafted[0]["merged_from"][0]["bottleneck"] == "Supervisor overload"
    assert {d["state"] for d in drafted} == {"proposed"}

    # Never applied: the originals are exactly as they were.
    for original, state in ((a, ACCEPTED), (b, PROPOSED), (c, PROPOSED)):
        original.refresh_from_db()
        assert original.state == state

    # AC-3.5: the model gets the rows and the constraint, never the private note.
    system = fake_claude.requests[-1]["system"]
    assert "Use ONLY what the rows say" in system
    assert "Do not assert any fact" in system
    assert "never more than ten" in system
    sent = user_text(fake_claude)
    assert "1. (accepted) bottleneck: Supervisor overload" in sent
    assert "MARKER-PRIVATE" not in sent
    assert AiCall.objects.filter(purpose="strategy_rows_consolidate").count() == 1
    assert AuditEvent.all_objects.filter(verb="strategy.map_consolidation_proposed").exists()


@pytest.mark.django_db
def test_consolidate_proposes_ten_at_most(session, ff, api, fake_claude):
    for i in range(14):
        row(session, f"Row {i}", PROPOSED)
    fake_claude.reply = json.dumps([{"bottleneck": f"Target {i}", "merges": [i + 1]}
                                    for i in range(14)])
    made = api.as_(ff).post(f"/api/strategy-sessions/{session.pk}/consolidate/").json()
    assert len(made["drafted"]) == 10


@pytest.mark.django_db
def test_a_consolidated_row_is_accepted_like_any_other(session, ff, api, fake_claude):
    row(session, "A", PROPOSED)
    row(session, "B", PROPOSED)
    fake_claude.reply = json.dumps([{"bottleneck": "A and B", "merges": [1, 2]}])
    merged = api.as_(ff).post(f"/api/strategy-sessions/{session.pk}/consolidate/"
                              ).json()["drafted"][0]
    assert api.as_(ff).post(f"/api/strategy-map-rows/{merged['id']}/accept/"
                            ).status_code == 200
    assert StrategyMapRow.objects.get(pk=merged["id"]).state == ACCEPTED


@pytest.mark.django_db
def test_a_va_cannot_consolidate(session, va, api, fake_claude):
    assert api.as_(va).post(f"/api/strategy-sessions/{session.pk}/consolidate/"
                            ).status_code == 403
    assert fake_claude.requests == []


# ------------------------------------------------------- (c) prune the map

@pytest.mark.django_db
def test_an_accepted_row_can_be_removed_from_the_map_and_is_audited(session, ff, va, api):
    on_map = row(session, "Supervisor overload", ACCEPTED)
    assert api.as_(va).post(f"/api/strategy-map-rows/{on_map.pk}/remove/"
                            ).status_code == 403
    removed = api.as_(ff).post(f"/api/strategy-map-rows/{on_map.pk}/remove/")
    assert removed.status_code == 200
    on_map.refresh_from_db()
    assert on_map.state == DISCARDED
    event = AuditEvent.all_objects.get(verb="strategy.map_row_removed")
    assert event.target_id == on_map.pk and event.payload["bottleneck"] == "Supervisor overload"


@pytest.mark.django_db
def test_a_converted_row_stays_on_the_map(session, ff, api):
    converted = row(session, "Supervisor overload", ACCEPTED, converted_to="goal")
    refused = api.as_(ff).post(f"/api/strategy-map-rows/{converted.pk}/remove/")
    assert refused.status_code == 409
    assert "links back" in refused.json()["detail"]
    tray = row(session, "Not on the map", PROPOSED)
    assert api.as_(ff).post(f"/api/strategy-map-rows/{tray.pk}/remove/").status_code == 400
