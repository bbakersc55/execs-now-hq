"""P3 phase 4 — session v3: the PDF, conversion and the prep panel.

1. The two-page PDF takes its chips, chart heading, scale and path copy from
   the template, and still keeps every private thing out (AC-4.9 on v3).
2. Conversion makes the same goals and projects from the same rows.
3. Prep addresses the practice's own kind of advisor and stays private.
"""

from __future__ import annotations

import json

import pytest

from apps.strategy import builder, conversion, emails, pdf as pdf_service, prep, seed
from apps.strategy import services, v3
from apps.strategy.models import StrategyMapRow, StrategyPathNote
from apps.work.models import Goal, Project

from . import registry_config  # noqa: F401
from .conftest import _member
from .test_strategy_v3_session import (  # noqa: F401  (fixtures)
    FRACTIONAL, PROSPECT, answer, base, build, keys, patch, post, precall, prospect, rate,
    session, template,
)

ROWS = (
    ("A Weekly Scorecard", "Run the week from five numbers.", "No weekly numbers",
     "A five-line scorecard", "Jen Park", 30, "Scorecard reviewed 4 weeks running"),
    ("Scheduling In A System", "Put the schedule where everyone can see it.",
     "Scheduling lives in one head", "Move it into the dispatch tool", "", 60,
     "Schedule published by Friday"),
    ("A Price Book", "Price every job the same way.", "Pricing is from memory",
     "Write the price book", "Dana Reyes", 90, ""),
)


def add_rows(session, rows=ROWS):
    made = []
    for position, (header, statement, bottleneck, fix, owner, horizon, measurable) in \
            enumerate(rows):
        made.append(StrategyMapRow.objects.create(
            tenant=session.tenant, session=session, position=position, header=header,
            statement=statement, bottleneck=bottleneck, the_fix=fix, owner_text=owner,
            horizon=horizon, measurable=measurable, root_cause="No system",
            mechanics_note="MARKER-MECHANICS", state=StrategyMapRow.State.ACCEPTED))
    return made


def run(session):
    """A whole v3 session's worth of content, with every private thing marked."""
    precall(session)
    answer(session, keys(session, "precall")[0],
           {"text": "Office cleaning, to property managers"}, FRACTIONAL,
           note="MARKER-PRIVATE-NOTE")
    rate(session)
    answer(session, keys(session, "diagnostic")[0],
           {"said": "Pricing waits for Dana", "cause": "No price book", "tried": ""},
           note="MARKER-DIAGNOSTIC-NOTE")
    answer(session, keys(session, "mirror")[0], {"text": "Two branches"})
    session.mirror_goal = "Two branches running. Dana off the tools."
    session.mirror_unlocks = "Weekly numbers first."
    session.save()
    add_rows(session)
    if v3.section_of(session, "values"):
        answer(session, keys(session, "values")[0],
               {"value": "Straight talk", "why": "Oversold before"})
    path_a, path_b = keys(session, "paths")
    answer(session, path_a, {"reaction": "MARKER-REACTION", "risk": "MARKER-RISK",
                             "leaning": ""})
    answer(session, path_b, {"reaction": "Interested", "risk": "Cost",
                             "leaning": "Leaning this way"})
    for path, kind, text, state in (("a", "pro", "You set the pace", "accepted"),
                                    ("a", "con", "It slips again", "accepted"),
                                    ("b", "pro", "Someone owns the list", "accepted"),
                                    ("b", "con", "MARKER-UNACCEPTED-CON", "proposed")):
        StrategyPathNote.objects.create(tenant=session.tenant, session=session, path=path,
                                        kind=kind, text=text, state=state)
    scope, start, money = keys(session, "scope")
    answer(session, scope, {"agreed": True, "notes": "Rows 1 and 2"})
    answer(session, start, {"agreed": True, "notes": "November 3"})
    answer(session, money, {"agreed": True, "notes": "MARKER-MONEY"})
    return session


# ==================================================================== the PDF

@pytest.mark.django_db
def test_the_v3_pdf_is_two_pages_with_the_templates_own_words(session, template):
    builder.update_settings(template, {"rating_scale": "1 is not yet, 10 is every week"})
    builder.update_section(template, code="six_key_components", title="Three things we rate")
    # The session froze the template when it was created: start another.
    fresh_session = services.start(tenant=session.tenant, contact=session.contact,
                                   template=template, owner=session.owner)
    html = pdf_service.render_html(run(fresh_session))
    assert pdf_service.page_count(fresh_session) == 2
    # The two-page design (2026-10-15): the rated items are cards under their
    # own labels, with a pill from the rating, never their wording.
    doc = pdf_service.context_for(fresh_session)["doc"]
    assert [c["name"] for c in doc["components"]] == ["Plan", "Team", "Numbers"]
    assert "The three components" in html
    for label in ("Plan", "Team", "Numbers"):
        assert f'<div class="name">{label}</div>' in html, label
    assert "Our plan is written down" not in html, "the card names the item, not its wording"
    # The two paths, in the template's words, with {Practice} filled.
    assert '<div class="name">Continue to run it yourself</div>' in html
    assert '<div class="name">Work with Tenant A</div>' in html
    assert "Use the map Tenant A handed you" in html
    assert "{Practice}" not in html
    # The leaning recommends path B.
    assert [p["recommended"] for p in doc["paths"]] == [False, True]
    # The map in its boxes, in horizon order, and the mirror.
    assert html.index("A Weekly Scorecard") < html.index("Scheduling In A System") \
        < html.index("A Price Book")
    assert "A Weekly Scorecard <b>Jen Park</b>" in html
    assert "<p>Two branches running. Dana off the tools.</p>" in html
    assert '<div class="said">Weekly numbers first.</div>' in html
    assert pdf_service.render_pdf(fresh_session).startswith(b"%PDF")


@pytest.mark.django_db
def test_the_pdf_keeps_every_private_thing_out_until_its_flag_is_on(session, ff, api):
    run(session)
    html = pdf_service.render_html(session)
    for marker in ("MARKER-PRIVATE-NOTE", "MARKER-DIAGNOSTIC-NOTE", "MARKER-MECHANICS",
                   "MARKER-MONEY", "MARKER-REACTION", "MARKER-RISK",
                   "MARKER-UNACCEPTED-CON", "Investment discussed"):
        assert marker not in html, marker
    assert "You set the pace" in html and "Someone owns the list" in html
    cover = emails.default_pdf_cover(session)
    assert "MARKER" not in cover and "Work with Tenant A" in cover
    assert "We talked about starting on" not in cover, \
        "no automatic next-step sentence in a v3 covering note"

    def with_flag(flag):
        assert patch(api, ff, base(session) + "pdf-flags/", {flag: True}).status_code == 200
        out = pdf_service.render_html(services.StrategySession.objects.get(pk=session.pk))
        patch(api, ff, base(session) + "pdf-flags/", {flag: False})
        return out

    money = with_flag("investment")
    assert "MARKER-MONEY" in money and "MARKER-PRIVATE-NOTE" not in money, "one at a time"
    # As on a focused map: a card map never printed the mechanics note,
    # whatever its flag says, and the two-page design keeps it that way.
    assert "MARKER-MECHANICS" not in with_flag("mechanics")
    # The reaction, the stated risk and an unaccepted line never print at all.
    everything = pdf_service.render_html(session)
    for never in ("MARKER-REACTION", "MARKER-RISK", "MARKER-UNACCEPTED-CON"):
        assert never not in everything and never not in money


@pytest.mark.django_db
def test_a_template_without_what_they_value_prints_no_such_block(seeded_tenant, in_tenant_a,
                                                                prospect, ff):
    plain = build(seeded_tenant, name="No values", values=False)
    session = run(services.start(tenant=seeded_tenant, contact=prospect, template=plain,
                                 owner=ff.user))
    html = pdf_service.render_html(session)
    assert "What you told us matters" not in html
    assert pdf_service.page_count(session) == 2


@pytest.mark.django_db
def test_eight_rated_items_with_long_labels_still_fit(seeded_tenant, in_tenant_a, prospect,
                                                     ff):
    full = build(seeded_tenant, name="Eight")
    for n in range(5):
        builder.add_question(full, section="six_key_components",
                             prompt=f"Area {n} — It works the way we want it to.",
                             label=f"A fairly long label for area number {n}")
    session = services.start(tenant=seeded_tenant, contact=prospect, template=full,
                             owner=ff.user)
    for key in keys(session, "ratings"):
        answer(session, key, {"rating": 6, "comment": ""})
    run(session)
    add_rows(session, (("Fourth Card", "S.", "Fourth", "F", "", 30, ""),
                       ("Fifth Card", "S.", "Fifth", "F", "", 90, "")))
    html = pdf_service.render_html(session)
    doc = pdf_service.context_for(session)["doc"]
    # Six cards fill the page; the seventh and eighth are named beneath them,
    # and the tile counts all eight.
    assert html.count('class="card component"') == 6
    assert doc["also_rated"] == ["A fairly long label… (Watch)"] * 2
    assert "Also rated: A fairly long label… (Watch);" in html
    assert {"number": "8", "label": "components assessed, two to fix"} in doc["tiles"]
    assert all(len(c["name"]) <= 24 for c in doc["words"]["components"]), \
        "a long label is cut at a word, not overflowed"
    assert sum(len(box["bullets"]) for box in doc["boxes"]) == 5
    assert pdf_service.page_count(session) == 2


@pytest.mark.django_db
def test_generating_is_open_to_an_assistant_and_flags_are_not(session, va, ff, api,
                                                             tenant_b):
    run(session)
    made = api.as_(va).get(base(session) + "pdf/")
    assert made.status_code == 200 and made.content.startswith(b"%PDF")
    assert patch(api, va, base(session) + "pdf-flags/", {"investment": True}).status_code == 403
    other = _member(tenant_b, "FF")
    assert api.as_(other).get(base(session) + "pdf/").status_code == 404


# ================================================================= conversion

def _made(model):
    skip = {"id", "tenant_id", "created_at", "updated_at", "source_map_row_id", "company_id",
            "client_company_id", "goal_id", "project_id"}
    return [{f.attname: getattr(obj, f.attname) for f in model._meta.concrete_fields
             if f.attname not in skip} for obj in model.objects.order_by("created_at")]


@pytest.mark.django_db
def test_conversion_makes_the_same_work_from_a_v3_session_as_from_a_v2_one(
        seeded_tenant, in_tenant_a, ff, api):
    from .factories import CompanyFactory, ContactFactory

    results = {}
    for kind in ("focused", "v3"):
        company = CompanyFactory(tenant=seeded_tenant, name=f"Acme {kind}")
        contact = ContactFactory(tenant=seeded_tenant, first_name="Dana", last_name="Reyes",
                                 company=company)
        ContactFactory(tenant=seeded_tenant, first_name="Jen", last_name="Park",
                       company=company)
        if kind == "focused":
            seed.seed_tenant(seeded_tenant)
            source = seed.create_focused(seeded_tenant)
        else:
            source = build(seeded_tenant)
        made = services.start(tenant=seeded_tenant, contact=contact, template=source,
                              owner=ff.user)
        rows = add_rows(made)
        preview = api.as_(ff).get(base(made) + "conversion-preview/").json()["rows"]
        choices = {str(rows[0].pk): {"as": "goal", "baseline_unknown": True},
                   str(rows[1].pk): {"as": "project"}, str(rows[2].pk): {"as": "skip"}}
        before = (Goal.objects.count(), Project.objects.count())
        converted = post(api, ff, base(made) + "convert/", {"choices": choices})
        assert converted.status_code == 201, converted.content
        goals, projects = _made(Goal)[before[0]:], _made(Project)[before[1]:]
        results[kind] = {
            "preview": [{k: v for k, v in row.items()
                         if k not in ("row", "client_owner_contact")}
                        | {"owner": (row["client_owner_contact"] or {}).get("name")}
                        for row in preview],
            "created": [(c["as"], c["title"]) for c in converted.json()["created"]],
            "goals": goals, "projects": projects,
            "state": services.StrategySession.objects.get(pk=made.pk).state,
        }
    assert results["v3"]["created"] == [("goal", "No weekly numbers"),
                                        ("project", "Scheduling lives in one head")]
    assert results["v3"]["preview"][0]["owner"] == "Jen Park"
    assert results["v3"]["state"] == "converted"
    comparable = json.loads(json.dumps(results, default=str))
    for part in ("preview", "created", "state"):
        assert comparable["v3"][part] == comparable["focused"][part], part
    for part in ("goals", "projects"):
        strip = lambda rows: [{k: v for k, v in row.items()                # noqa: E731
                               if not k.endswith("_id")} for row in rows]
        assert strip(comparable["v3"][part]) == strip(comparable["focused"][part]), part


@pytest.mark.django_db
def test_an_assistant_cannot_convert_a_v3_session(session, va, api):
    add_rows(session)
    assert api.as_(va).get(base(session) + "conversion-preview/").status_code == 403
    assert post(api, va, base(session) + "convert/", {"choices": {}}).status_code == 403
    assert not Goal.objects.exists()


# ======================================================================= prep

PREP_REPLY = json.dumps({
    "summary": "Their site says they clean offices.",
    "bottlenecks": ["Likely supervisor span of control"],
    "rewordings": [],
    "questions": [{"text": "How are night supervisors measured?", "why": "Their site"}],
})


@pytest.mark.django_db
def test_prep_addresses_the_practices_own_advisor_and_reads_its_questions(session, ff, va,
                                                                         api, fake_claude):
    sells, team, want = keys(session, "precall")
    fake_claude.reply = json.dumps({**json.loads(PREP_REPLY), "rewordings": [
        {"key": sells, "suggested": "What does {Company} clean, and for whom?", "why": "Site"},
        {"key": team, "suggested": "How many work for {The Boss}?", "why": "Unknown field"},
        {"key": keys(session, "ratings")[0], "suggested": "Not a pre-call question",
         "why": ""},
    ]})
    made = post(api, ff, base(session) + "prepare/", {"website_url": "https://acme.invalid",
                                                      "notes": "Met at the chamber."})
    assert made.status_code == 201, made.content
    request = fake_claude.requests[-1]
    assert "preparing a business consultant for a strategy session" in request["system"]
    assert "fractional operations executive" not in request["system"]
    assert "ordinary operational bottlenecks" not in request["system"]
    assert "Do not invent" in request["system"], "the rules are the same words"
    user = request["messages"][0]["content"]
    assert f"{sells}: What does Acme Facilities sell, and to whom?" in user
    assert "rated 1-10" not in user and "Our plan is written down" not in user, \
        "a v3 rating is not a pre-call question"
    body = made.json()
    assert [r["key"] for r in body["rewordings"]] == [sells]
    assert body["dropped_rewordings"] == [team], "an unknown merge field is not offered"
    # Fractional-only, as for every session: an assistant cannot run or read it.
    assert post(api, va, base(session) + "prepare/", {}).status_code == 403
    assert api.as_(va).get(base(session)).json()["prep"] is None
    assert api.as_(ff).get(base(session)).json()["prep"]["state"] == "ready"
    # And nothing it produced has changed what the session asks.
    assert prep.precall_questions(session)[0][1] == \
        "What does Acme Facilities sell, and to whom?"


@pytest.mark.django_db
def test_prep_never_reaches_the_prospect(session, ff, api, fake_claude, client):
    fake_claude.reply = PREP_REPLY
    assert post(api, ff, base(session) + "prepare/", {"notes": "MARKER-PREP-NOTES"}) \
        .status_code == 201
    run(session)
    token = services.issue_precall_token(session)
    form = client.get(f"/api/strategy/precall/{token}").content.decode()
    text, html = emails._questions_body(session, emails.default_intro(session))
    for surface in (form, text, html, pdf_service.render_html(session),
                    emails.default_pdf_cover(session)):
        assert "MARKER-PREP-NOTES" not in surface
        assert "night supervisors" not in surface and "Their site says" not in surface


@pytest.mark.django_db
def test_the_optional_scorecard_section_lists_the_moves_kpis_with_latest_and_status(
        session, ff, api):
    import io
    import zipfile

    from django.utils import timezone

    from apps.crm.models import Company
    from apps.scorecard import board, periods as P, setup
    from apps.scorecard.models import KpiReading
    from apps.strategy import docx_export
    from apps.tenancy.context import tenant_context

    run(session)
    session.company = session.contact.company
    session.save(update_fields=["company"])
    rows = list(StrategyMapRow.objects.filter(session=session).order_by("position"))
    other = Company.all_objects.create(tenant=session.tenant, name="Someone Else Co")
    today = board.today_for(session.tenant)
    week = P.previous_start(P.start_of(today, P.WEEKLY, "monday"), P.WEEKLY, "monday")
    with tenant_context(session.tenant_id):
        card = setup.ensure(session.company, ff.user)
        page = str(card.pages.get().pk)

        def kpi(name, on=card, **extra):
            return setup.create_kpi(on, {"name": name, "kind": "count", "cadence": "weekly",
                                         "rollup": "sum", "target_value": 10,
                                         "page": page if on is card
                                         else str(on.pages.get().pk), **extra}, ff.user)

        jobs = kpi("Jobs priced from the book")
        idle = kpi("Schedules published")
        gone = kpi("Archived one")
        theirs = kpi("Not this company's", on=setup.ensure(other, ff.user))
        KpiReading.objects.create(tenant=session.tenant, kpi=jobs, period_start=week, value=12,
                                  entered_by=ff.user, entered_at=timezone.now())
        gone.archived_at = timezone.now()
        gone.save(update_fields=["archived_at"])
    for row, k in ((rows[0], jobs), (rows[1], idle), (rows[2], jobs)):
        row.kpi = k
        row.save(update_fields=["kpi"])
    StrategyMapRow.objects.create(tenant=session.tenant, session=session, position=9,
                                  header="Old", bottleneck="x", kpi=gone,
                                  state=StrategyMapRow.State.ACCEPTED)
    StrategyMapRow.objects.create(tenant=session.tenant, session=session, position=10,
                                  header="Theirs", bottleneck="y", kpi=theirs,
                                  state=StrategyMapRow.State.ACCEPTED)

    off = pdf_service.render_html(session)
    assert "Jobs priced from the book" not in off and pdf_service.page_count(session) == 2

    assert patch(api, ff, base(session) + "pdf-flags/", {"scorecard": True}).status_code == 200
    session.refresh_from_db()
    items = pdf_service.context_for(session)["scorecard"]
    assert [i["name"] for i in items] == ["Jobs priced from the book", "Schedules published"]
    jobs_item = items[0]
    assert jobs_item["moves"] == ["A Weekly Scorecard", "A Price Book"]
    assert (jobs_item["value"], jobs_item["status_label"]) == ("12", "On track")
    assert jobs_item["target"] == "target 10" and jobs_item["period"]
    assert (items[1]["value"], items[1]["status_label"]) == ("No reading yet", "")
    html = pdf_service.render_html(session)
    assert "<h2>Scorecard</h2>" in html and "Jobs priced from the book" in html
    assert "Archived one" not in html and "Not this company" not in html
    assert pdf_service.page_count(session) == 3
    xml = zipfile.ZipFile(io.BytesIO(docx_export.render_docx(session))).read(
        "word/document.xml").decode()
    assert "Scorecard" in xml and "Jobs priced from the book" in xml and "On track" in xml
