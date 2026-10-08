"""Two additions to the strategy map (owner, 2026-10-08).

1. A row written by hand on the map.
2. The call notes as context for Claude's drafts.

Both are for a session with a card map: started from "Operations — focused"
(v2) or from a builder template (v3). A classic session is left as it was.
"""

from __future__ import annotations

import json

import pytest

from apps.meetings import drive, ingest
from apps.strategy import ai, call_notes, emails, pdf, services
from apps.strategy.models import StrategyCallNotes, StrategyMapRow, StrategyPathNote
from apps.tenancy.context import tenant_context
from apps.tenancy.models import AiCall, AuditEvent

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import (
    GmailConnectionFactory, MeetingProposalFactory,
    MeetingSourceFileFactory,
)
from .test_platform_isolation import in_practices_area
from .test_strategy_focused import (  # noqa: F401  (fixtures: a v2 session)
    classic, focused, prospect, session,
)
from .test_strategy_focused import answer as answer_v2

NOTES = """Call with Dana Reyes, Acme Facilities. Notes taken by the advisor.

Dana said scheduling lives in Jen's head and nobody else can build the week's rota.
Advisor suggested a shared scheduling board; Dana did not commit to it.
Dana: "We lost the Hartwell account in March because two shifts went uncovered."
Advisor mentioned that most cleaning firms this size run a 12% no-show rate.
Dana wants a second supervisor in place before the new branch opens.
SECRET-NOTES-MARKER
"""
PASSAGE = "Dana said scheduling lives in Jen's head and nobody else can build the week's rota."


def post(api, who, url, body=None):
    return api.as_(who).post(url, data=json.dumps(body or {}),
                             content_type="application/json")


def base(session):
    return f"/api/strategy-sessions/{session.pk}/"


def attach(api, who, session, **body):
    return post(api, who, base(session) + "call-notes/", body or {"source": "pasted",
                                                                  "text": NOTES})


def add_row(api, who, session, **more):
    return post(api, who, "/api/strategy-map-rows/", {
        "session": str(session.pk), "header": "Schedule Off One Person",
        "statement": "The week's rota is built by one person, so we will make it "
                     "something two people can run.",
        "owner_text": "Jen", "horizon": 60, "measurable": "People able to build the rota",
        **more})


def make_theirs(session, associate):
    """An associate reaches a session they own (their own prospect), or one on
    a company they are assigned to. This prospect has no company."""
    type(session).objects.filter(pk=session.pk).update(owner=associate.user)


def row_reply(*rows):
    return json.dumps([{
        "header": header, "statement": f"{header} is costing us.", "bottleneck": bottleneck,
        "root_cause": "", "the_fix": "Fix it.", "owner_text": "", "horizon": 60,
        "measurable": "", **({"passage": passage} if passage else {})}
        for header, bottleneck, passage in rows])


def sent(fake_claude, index=-1):
    request = fake_claude.requests[index]
    return request["system"], request["messages"][0]["content"]


def diagnosed(session):
    key = next(q["key"] for s, q in services.questions_in(session.template_snapshot)
               if s["code"] == "diagnostic")
    answer_v2(session, key, {"said": "Pricing waits for Dana", "cause": "No price book",
                             "tried": ""})


# ================================================= 1. a row written by hand

@pytest.mark.django_db
def test_a_row_added_by_hand_is_on_the_map_and_says_who_added_it(session, ff, va, api):
    made = add_row(api, ff, session)
    assert made.status_code == 201
    row = made.json()
    assert (row["header"], row["owner_text"], row["horizon"], row["state"]) == (
        "Schedule Off One Person", "Jen", 60, "accepted")
    assert row["measurable"] == "People able to build the rota"
    assert row["from_ai"] is False, "not drafted"
    assert row["added_by"] == (ff.user.full_name or ff.user.email)
    # Everyone on the practice who sees the session sees who added it.
    for who in (ff, va):
        shown = api.as_(who).get(base(session)).json()["map_rows"]
        assert [r.get("added_by") for r in shown] == [row["added_by"]]
    with tenant_context(session.tenant_id):
        stored = StrategyMapRow.objects.get(pk=row["id"])
        assert stored.added_by_id == ff.user.pk and stored.ai_call_id is None
        assert AuditEvent.objects.filter(verb="strategy.map_row_added",
                                         target_id=stored.pk).count() == 1


@pytest.mark.django_db
def test_a_hand_added_row_needs_a_header_and_a_statement_and_counts_toward_five(session, ff,
                                                                              api):
    assert add_row(api, ff, session, header=" ").status_code == 400
    assert add_row(api, ff, session, statement="").status_code == 400
    assert add_row(api, ff, session, horizon=45).status_code == 400
    for n in range(5):
        assert add_row(api, ff, session, header=f"Row {n}").status_code == 201
    full = add_row(api, ff, session, header="A sixth")
    assert full.status_code == 409 and "holds 5 rows" in full.json()["detail"]
    with tenant_context(session.tenant_id):
        assert StrategyMapRow.objects.filter(session=session).count() == 5
    # Take one off and there is room again.
    first = api.as_(ff).get(base(session)).json()["map_rows"][0]["id"]
    assert post(api, ff, f"/api/strategy-map-rows/{first}/remove/").status_code == 200
    assert add_row(api, ff, session, header="A sixth").status_code == 201


@pytest.mark.django_db
def test_a_hand_added_row_is_edited_removed_and_printed_like_any_row(session, ff, api):
    row = add_row(api, ff, session).json()
    one = f"/api/strategy-map-rows/{row['id']}/"
    edited = api.as_(ff).patch(one, data=json.dumps({"header": "Two People Can Schedule"}),
                               content_type="application/json")
    assert edited.status_code == 200 and edited.json()["header"] == "Two People Can Schedule"
    assert edited.json()["added_by"], "still theirs after an edit"
    with tenant_context(session.tenant_id):
        html = pdf.render_html(type(session).objects.get(pk=session.pk))
    assert "Two People Can Schedule" in html
    assert "The week&#x27;s rota is built by one person" in html or \
        "The week's rota is built by one person" in html
    assert "added by" not in html.lower(), "who added it is not the prospect's business"
    assert post(api, ff, one + "remove/").json()["state"] == "discarded"
    with tenant_context(session.tenant_id):
        assert "Two People Can Schedule" not in pdf.render_html(
            type(session).objects.get(pk=session.pk))


@pytest.mark.django_db
def test_role_boundaries_an_assistant_cannot_add_a_row_and_an_associate_only_on_their_own(
        session, ff, cf, va, api, seeded_tenant):
    assert add_row(api, va, session).status_code == 403
    assert add_row(api, cf, session).status_code == 404, "not their prospect"
    with tenant_context(seeded_tenant.pk):
        assert not StrategyMapRow.objects.filter(session=session).exists()
        make_theirs(session, cf)
    assert add_row(api, cf, session).status_code == 201


@pytest.mark.django_db
def test_tenant_isolation_another_practice_cannot_add_a_row_to_this_session(session, tenant_b,
                                                                           api):
    other = _member(tenant_b, "FF")
    assert add_row(api, other, session).status_code == 404
    with tenant_context(session.tenant_id):
        assert not StrategyMapRow.objects.filter(session=session).exists()


@pytest.mark.django_db
def test_both_paths_take_a_pro_or_a_con_written_by_hand(session, ff, api):
    for path in ("a", "b"):
        for kind in ("pro", "con"):
            made = post(api, ff, "/api/strategy-path-notes/", {
                "session": str(session.pk), "path": path, "kind": kind,
                "text": f"A {kind} of path {path}"})
            assert made.status_code == 201 and made.json()["state"] == "accepted", (path, kind)
    with tenant_context(session.tenant_id):
        assert StrategyPathNote.objects.filter(session=session, from_ai=False).count() == 4


# ============================================= 2. the call notes: attaching

@pytest.mark.django_db
def test_pasted_notes_are_stored_on_the_session_and_shown_back(session, ff, api):
    empty = api.as_(ff).get(base(session) + "call-notes/").json()
    assert empty["attached"] is None and empty["candidates"] == []
    made = attach(api, ff, session)
    assert made.status_code == 201
    attached = made.json()["attached"]
    assert (attached["source"], attached["title"]) == ("pasted", "Pasted notes")
    assert attached["text"] == NOTES.strip() and attached["characters"] == len(NOTES.strip())
    assert attached["added_by"] == (ff.user.full_name or ff.user.email)
    assert api.as_(ff).get(base(session)).json()["call_notes"]["title"] == "Pasted notes"
    # Attaching again replaces them; removing takes them off.
    attach(api, ff, session, source="pasted", text="Shorter notes of the call.")
    with tenant_context(session.tenant_id):
        assert StrategyCallNotes.objects.get().text == "Shorter notes of the call."
        events = [e.verb for e in AuditEvent.objects.filter(
            verb__startswith="strategy.call_notes").order_by("created_at")]
        assert events == ["strategy.call_notes_attached", "strategy.call_notes_replaced"]
        # The audit trail says what was attached, never the notes themselves.
        assert "SECRET-NOTES-MARKER" not in json.dumps(list(AuditEvent.objects.values_list(
            "payload", flat=True)))
    assert api.as_(ff).delete(base(session) + "call-notes/").json() == {"attached": None}
    assert "call_notes" not in api.as_(ff).get(base(session)).json()
    for bad in ({"source": "pasted", "text": "  "}, {"source": "pasted"},
                {"source": "pasted", "text": "x" * (call_notes.MOST + 1)},
                {"source": "carrier pigeon", "text": "x"}):
        assert attach(api, ff, session, **bad).status_code == 400, bad


@pytest.mark.django_db
def test_the_meeting_queues_files_for_that_day_are_offered_in_any_state(session, ff, api,
                                                                      seeded_tenant):
    day = call_notes.day_of(session)
    with tenant_context(seeded_tenant.pk):
        pending = MeetingSourceFileFactory(tenant=seeded_tenant, name="Dana call, notes",
                                           text=NOTES, state="parsed")
        MeetingProposalFactory(tenant=seeded_tenant, source_file=pending, meeting_date=day)
        dismissed = MeetingSourceFileFactory(tenant=seeded_tenant, name="Dana call, transcript",
                                             text="Transcript text.", state="skipped")
        MeetingProposalFactory(tenant=seeded_tenant, source_file=dismissed, meeting_date=day,
                               state="dismissed")
        another_day = MeetingSourceFileFactory(tenant=seeded_tenant, name="Last month")
        MeetingProposalFactory(tenant=seeded_tenant, source_file=another_day,
                               meeting_date=day.replace(year=day.year - 1))
        type(another_day).objects.filter(pk=another_day.pk).update(
            created_at=session.created_at.replace(year=day.year - 1))
        unread = MeetingSourceFileFactory(tenant=seeded_tenant, name="Not read yet", text="")
        MeetingProposalFactory(tenant=seeded_tenant, source_file=unread, meeting_date=day)
    offered = api.as_(ff).get(base(session) + "call-notes/").json()
    assert offered["day"] == day.isoformat()
    assert {c["name"] for c in offered["candidates"]} == {"Dana call, notes",
                                                         "Dana call, transcript"}
    made = attach(api, ff, session, source="meeting_file", source_file=str(pending.pk))
    assert made.status_code == 201
    assert made.json()["attached"]["title"] == "Dana call, notes"
    assert made.json()["attached"]["source_label"] == "From the meeting queue"
    assert made.json()["attached"]["text"] == NOTES.strip()
    assert attach(api, ff, session, source="meeting_file",
                  source_file=str(unread.pk)).status_code == 400
    assert attach(api, ff, session, source="meeting_file", source_file="nonsense"
                  ).status_code == 404


class OneDoc:
    """Drive at its boundary, for a document picked by its link."""

    def __init__(self, files):
        self.files, self.asked = files, []

    def file(self, file_id):
        self.asked.append(file_id)
        return self.files.get(file_id)

    def text_of(self, found):
        return NOTES


DOC_ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcd"
DOC_LINK = f"https://docs.google.com/document/d/{DOC_ID}/edit?usp=sharing"


@pytest.mark.django_db
def test_a_drive_document_is_picked_by_its_link_through_the_practices_own_grant(
        session, ff, api, monkeypatch):
    client = OneDoc({DOC_ID: drive.DriveFile(
        file_id=DOC_ID, version="3", name="Dana / Bryan, Oct 8",
        mime_type="application/vnd.google-apps.document")})
    asked_for = []
    monkeypatch.setattr(ingest, "client_for",
                        lambda tenant: asked_for.append(tenant.pk) or client)
    made = attach(api, ff, session, source="drive", link=DOC_LINK)
    assert made.status_code == 201
    assert asked_for == [session.tenant_id], "this practice's connection, and no other"
    assert client.asked == [DOC_ID]
    attached = made.json()["attached"]
    assert (attached["title"], attached["source_label"]) == ("Dana / Bryan, Oct 8",
                                                             "A Drive document")
    assert attached["text"] == NOTES.strip()
    # A document the connected account cannot see, a PDF, and not a link at all.
    assert attach(api, ff, session, source="drive",
                  link=DOC_LINK.replace("1AbC", "9ZzZ")).status_code == 404
    client.files["x" * 30] = drive.DriveFile(file_id="x" * 30, version="1", name="Scan",
                                             mime_type="application/pdf")
    refused = attach(api, ff, session, source="drive", link="x" * 30)
    assert refused.status_code == 400 and "PDF" in refused.json()["detail"]
    for link in ("", "the notes from today", "https://example.com/notes"):
        assert attach(api, ff, session, source="drive", link=link).status_code == 400, link


@pytest.mark.django_db
def test_the_drive_pick_is_refused_when_the_practice_has_not_granted_drive(session, ff, api,
                                                                         seeded_tenant):
    """The real `client_for`: no connection, and then a connection that sends
    mail and cannot see a file."""
    no_connection = attach(api, ff, session, source="drive", link=DOC_LINK)
    assert no_connection.status_code == 409
    assert "pasted in instead" in no_connection.json()["detail"]
    with tenant_context(seeded_tenant.pk):
        GmailConnectionFactory(tenant=seeded_tenant, user=ff.user, scopes=["gmail.send"])
    mail_only = attach(api, ff, session, source="drive", link=DOC_LINK)
    assert mail_only.status_code == 409 and "Drive" in mail_only.json()["detail"]
    with tenant_context(seeded_tenant.pk):
        assert not StrategyCallNotes.objects.exists()


@pytest.mark.parametrize("link, found", [
    (DOC_LINK, DOC_ID), (f"docs.google.com/document/d/{DOC_ID}", DOC_ID),
    (f"https://drive.google.com/file/d/{DOC_ID}/view", DOC_ID),
    (f"https://drive.google.com/open?id={DOC_ID}", DOC_ID), (DOC_ID, DOC_ID),
    ("https://docs.google.com/document/u/0/", ""), ("short", ""), ("", ""),
])
def test_a_file_id_is_read_out_of_whatever_was_pasted(link, found):
    assert call_notes.file_id_from(link) == found


# ====================================== the notes stay the practice's own

@pytest.mark.django_db
def test_role_boundaries_an_assistant_has_no_route_to_the_notes_and_none_in_any_payload(
        session, ff, cf, va, api, fake_claude, seeded_tenant):
    attach(api, ff, session)
    fake_claude.reply = row_reply(("Scheduling In One Head", "Only Jen can build the rota",
                                   PASSAGE))
    assert post(api, ff, base(session) + "draft-rows/").status_code == 201
    for method in ("get", "post", "delete"):
        refused = getattr(api.as_(va), method)(base(session) + "call-notes/")
        assert refused.status_code == 403, method
    payload = api.as_(va).get(base(session))
    body = payload.content.decode()
    assert payload.status_code == 200
    assert "call_notes" not in payload.json()
    for private in ("SECRET-NOTES-MARKER", "Jen's head", "Hartwell", "source_passage",
                    "from_call_notes"):
        assert private not in body, private
    assert "SECRET-NOTES-MARKER" not in api.as_(va).get(
        "/api/strategy-sessions/").content.decode()
    # The practice owner's payload is where it is, so the check above is real.
    mine = api.as_(ff).get(base(session)).json()
    assert mine["call_notes"]["characters"] and mine["map_rows"][0]["source_passage"] == PASSAGE
    # An associate: their own prospect's, and nobody else's.
    assert api.as_(cf).get(base(session) + "call-notes/").status_code == 404
    with tenant_context(seeded_tenant.pk):
        make_theirs(session, cf)
    theirs = api.as_(cf).get(base(session)).json()
    assert theirs["call_notes"]["title"] == "Pasted notes"
    with tenant_context(seeded_tenant.pk):
        assert StrategyCallNotes.objects.count() == 1


@pytest.mark.django_db
def test_tenant_isolation_another_practice_and_the_platform_owner_reach_no_notes(
        session, ff, tenant_b, api, seeded_tenant):
    attach(api, ff, session)
    other = _member(tenant_b, "FF")
    owner = _member(seeded_tenant, "FF")
    owner.user.is_platform_owner = True
    owner.user.save()
    outside = in_practices_area(api.as_(owner))
    for client, allowed in ((api.as_(other), (404,)), (outside, (403, 404))):
        for method in ("get", "delete"):
            response = getattr(client, method)(base(session) + "call-notes/")
            assert response.status_code in allowed
            assert b"SECRET-NOTES-MARKER" not in response.content
        response = client.post(base(session) + "call-notes/", data=json.dumps(
            {"source": "pasted", "text": "Overwritten"}), content_type="application/json")
        assert response.status_code in allowed
    with tenant_context(seeded_tenant.pk):
        assert StrategyCallNotes.objects.get().text == NOTES.strip()
    # Nor can a file from another practice's meeting queue be attached here.
    with tenant_context(tenant_b.pk):
        theirs = MeetingSourceFileFactory(tenant=tenant_b, text="THEIR-MEETING")
    assert attach(api, ff, session, source="meeting_file",
                  source_file=str(theirs.pk)).status_code == 404


@pytest.mark.django_db
def test_the_notes_never_reach_the_form_the_emails_or_the_pdf(session, ff, api, client,
                                                             fake_claude):
    services.save_answer(session, question_key="s1_revenue", value={"text": "$920k"},
                         answered_by="prospect")
    diagnosed(session)
    attach(api, ff, session)
    fake_claude.reply = row_reply(("Scheduling In One Head", "Only Jen can build the rota",
                                   PASSAGE))
    row = post(api, ff, base(session) + "draft-rows/").json()["drafted"][0]
    post(api, ff, f"/api/strategy-map-rows/{row['id']}/accept/")
    with tenant_context(session.tenant_id):
        fresh = type(session).objects.get(pk=session.pk)
        token = services.issue_precall_token(fresh)
        form = client.get(f"/api/strategy/precall/{token}").content.decode()
        text, html = emails._questions_body(fresh, emails.default_intro(fresh))
        blocks = json.dumps(emails.question_blocks(fresh), default=str)
        fresh.pdf_include_flags = {key: True for key in fresh.pdf_include_flags}
        fresh.save()
        document = pdf.render_html(fresh)
        printed = json.dumps(pdf.context_for(fresh), default=str)
        cover = json.dumps(emails.cover_note(fresh), default=str) if hasattr(
            emails, "cover_note") else ""
    assert "Scheduling In One Head" in document, "the accepted row is on the PDF"
    for where, body in (("the pre-call form", form), ("the questions email", text + html),
                        ("the question blocks", blocks), ("the PDF", document),
                        ("the PDF's context", printed), ("the covering note", cover)):
        for private in ("SECRET-NOTES-MARKER", "Hartwell", "12% no-show", PASSAGE,
                        "From the call notes", "call notes"):
            assert private not in body, f"{private!r} reached {where}"


# ============================================== the notes as Claude's input

@pytest.mark.django_db
def test_draft_rows_is_given_the_notes_and_told_how_to_read_them(session, ff, api,
                                                                fake_claude):
    diagnosed(session)
    attach(api, ff, session)
    fake_claude.reply = row_reply(
        ("Scheduling In One Head", "Only Jen can build the rota", PASSAGE),
        ("Pricing Waits For Dana", "Quotes wait for Dana", None),
        ("No-Show Rate", "A 12% no-show rate", "Dana said the no-show rate is 12%."),
    )
    done = post(api, ff, base(session) + "draft-rows/")
    assert done.status_code == 201
    system, user = sent(fake_claude)
    assert user.count("THE CALL NOTES") == 1 and "Hartwell account in March" in user
    assert "Pricing waits for Dana" in user, "the answers are still there"
    assert "both sides of the conversation" in system
    assert "ONLY where the notes do" in system
    assert "nothing that is in neither the notes nor the answers" in system
    assert '"passage"' in system
    assert len(fake_claude.requests) == 1, "one call, as before"
    rows = {r["header"]: r for r in done.json()["drafted"]}
    # From the notes, with its passage word for word.
    assert rows["Scheduling In One Head"]["from_call_notes"] is True
    assert rows["Scheduling In One Head"]["source_passage"] == PASSAGE
    # From the answers alone: no marker.
    assert "from_call_notes" not in rows["Pricing Waits For Dana"]
    # A passage that is not in the notes is not shown as if it were.
    assert "from_call_notes" not in rows["No-Show Rate"]
    assert "source_passage" not in rows["No-Show Rate"]
    assert all(r["state"] == "proposed" for r in rows.values()), "proposed, never applied"
    # The cost of the call is shown to the practice owner.
    assert float(done.json()["cost_usd"]) >= 0 and done.json()["used_call_notes"] is True
    with tenant_context(session.tenant_id):
        call = AiCall.objects.get(purpose=ai.ROWS_PURPOSE)
        assert call.target_id == session.pk and call.tenant_id == session.tenant_id


@pytest.mark.django_db
def test_a_passage_is_matched_whatever_its_spacing_and_capitals(session, ff, api):
    attach(api, ff, session)
    with tenant_context(session.tenant_id):
        assert call_notes.passage_in(session, "dana said   scheduling lives in\nJen's head"
                                     ) == "dana said scheduling lives in Jen's head"
        assert call_notes.passage_in(session, '"We lost the Hartwell account in March') \
            .startswith("We lost the Hartwell")
        for absent in ("Dana said the rota is fine.", "", None, "Dana", 12,
                       "Advisor suggested a shared board and Dana agreed"):
            assert call_notes.passage_in(session, absent) == "", absent


@pytest.mark.django_db
def test_notes_alone_are_enough_to_draft_from(session, ff, api, fake_claude):
    """Nothing was typed into the session during the call."""
    fake_claude.reply = row_reply(("Scheduling In One Head", "Only Jen can build the rota",
                                   PASSAGE))
    assert post(api, ff, base(session) + "draft-rows/").json()["drafted"] == []
    assert fake_claude.requests == [], "no notes and no answers: no call"
    attach(api, ff, session)
    drafted = post(api, ff, base(session) + "draft-rows/").json()["drafted"]
    assert [r["header"] for r in drafted] == ["Scheduling In One Head"]


@pytest.mark.django_db
def test_without_notes_the_drafts_are_exactly_as_they_were(session, ff, api, fake_claude):
    diagnosed(session)
    fake_claude.reply = row_reply(("Pricing Waits For Dana", "Quotes wait for Dana", PASSAGE))
    done = post(api, ff, base(session) + "draft-rows/").json()
    system, user = sent(fake_claude)
    assert system == ai.ROWS_SYSTEM and "CALL NOTES" not in user
    assert set(done) == {"drafted"}, "no cost key without notes"
    assert "from_call_notes" not in done["drafted"][0], "a passage with no notes is nothing"


@pytest.mark.django_db
def test_consolidate_reads_the_notes_and_a_merged_row_keeps_its_passage(session, ff, api,
                                                                      fake_claude):
    diagnosed(session)
    attach(api, ff, session)
    fake_claude.reply = row_reply(
        ("Scheduling In One Head", "Only Jen can build the rota", PASSAGE),
        ("Rota Depends On Jen", "The rota depends on Jen", None))
    post(api, ff, base(session) + "draft-rows/")
    merged = [{"header": "Scheduling Off One Person", "statement": "Two people can build it.",
               "bottleneck": "The rota is built by one person", "the_fix": "Train a second.",
               "horizon": 60, "merges": [1, 2]}]
    fake_claude.reply = json.dumps(merged)
    done = post(api, ff, base(session) + "consolidate/")
    assert done.status_code == 201
    system, user = sent(fake_claude)
    assert "THE CALL NOTES" in user and "Hartwell account" in user
    assert "attribute a statement to the prospect only where the notes do" in system
    row = done.json()["drafted"][0]
    assert row["from_call_notes"] is True and row["source_passage"] == PASSAGE, \
        "from the row it merged"
    assert "cost_usd" in done.json()


@pytest.mark.django_db
def test_the_pros_and_cons_draft_reads_the_notes_and_marks_nothing(session, ff, api,
                                                                  fake_claude):
    diagnosed(session)
    attach(api, ff, session)
    fake_claude.reply = json.dumps({"a": {"pros": ["You keep control"], "cons": ["It slips"]},
                                    "b": {"pros": ["Someone owns it"], "cons": ["It costs"]}})
    done = post(api, ff, base(session) + "draft-paths/")
    assert done.status_code == 201 and len(done.json()["drafted"]) == 4
    system, user = sent(fake_claude)
    assert "THE CALL NOTES" in user and "second supervisor" in user
    assert "Attribute a statement or a view to the prospect only where the notes do" in system
    assert all(note["state"] == "proposed" for note in done.json()["drafted"])
    assert "cost_usd" in done.json() and len(fake_claude.requests) == 1


@pytest.mark.django_db
def test_an_associate_is_not_sent_the_cost(session, ff, cf, api, fake_claude, seeded_tenant):
    diagnosed(session)
    attach(api, ff, session)
    with tenant_context(seeded_tenant.pk):
        make_theirs(session, cf)
    fake_claude.reply = row_reply(("Scheduling In One Head", "Only Jen can build the rota",
                                   PASSAGE))
    done = post(api, cf, base(session) + "draft-rows/").json()
    assert done["drafted"][0]["source_passage"] == PASSAGE
    assert "cost_usd" not in done, "AI spend is the practice owner's"


@pytest.mark.django_db
def test_a_classic_session_is_left_as_it_was(seeded_tenant, classic, prospect, ff, api,
                                            in_tenant_a):
    old = services.start(tenant=seeded_tenant, contact=prospect, template=classic,
                         owner=ff.user)
    assert attach(api, ff, old).status_code == 409
    assert api.as_(ff).get(base(old) + "call-notes/").status_code == 409
    # Its hand-written rows are as before: a bottleneck, and no cap of five.
    assert post(api, ff, "/api/strategy-map-rows/",
                {"session": str(old.pk), "header": "x", "statement": "y"}).status_code == 400
    assert post(api, ff, "/api/strategy-map-rows/",
                {"session": str(old.pk), "bottleneck": "Quotes wait"}).status_code == 201
