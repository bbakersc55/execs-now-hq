"""The two-page strategy document's words (2026-10-15).

1. Where each part comes from: a person's saved words, else the session's own
   data (the ratings' pills, the map's rows, a converted goal), else a default.
2. Every line has a length; a save past it is refused, naming the line, and
   the longest words the limits allow still fit both pages.
3. Claude's draft is a proposal; nothing on the document changes until a
   person saves.
4. Practice isolation and role boundaries on the two new routes.
5. The sign-off's closing line, email and website from Settings → Branding,
   as Branding has them now, unless the document has its own (2026-10-17).
"""

from __future__ import annotations

import json

import pytest

from apps.strategy import conversion, document, pdf as pdf_service
from apps.strategy.models import StrategyMapRow
from apps.tenancy.models import AiCall, AuditEvent

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import ClientCompanyFactory
from .test_module4_acceptance import (  # noqa: F401  (fixtures and helpers)
    _a_full_session, answer, company, prospect, session, template,
)


def url(session, tail="document-words/"):
    return f"/api/strategy-sessions/{session.pk}/{tail}"


def patch(api, who, session, body):
    return api.as_(who).patch(url(session), json.dumps(body),
                              content_type="application/json")


def text(n: int, seed: str = "Weekly site review with the leads ") -> str:
    """Ordinary words, exactly `n` characters, ending on a letter."""
    out = (seed * (n // len(seed) + 2))[:n]
    return out[:-1] + "x" if out.endswith(" ") else out


def longest(session) -> dict:
    """Every part of the document at its most: every line at its length and
    every list at its count."""
    L, M = document.LIMITS, document.MOST
    words = document.merged(session, pdf_service.context_for(session))
    body = ". ".join([text(L["mirror_body"] // 3 - 2)] * 3) + "."
    return {
        "headline": text(L["headline"]), "intro": text(L["intro"]),
        "tile": {"number": "1,234,56", "label": text(L["tile_label"])},
        "mirror_headline": text(L["mirror_headline"]), "mirror_body": body[:L["mirror_body"]],
        "working": text(L["working"]), "not_yet": text(L["not_yet"]),
        "components": [{"key": c["key"], "name": text(L["component_name"], "Leadership "),
                        "pill": "fix", "line": text(L["component_line"])}
                       for c in words["components"]],
        "boxes": {h: [{"text": text(L["bullet"]), "owner": text(L["owner"], "Alexandra ")}
                      for _ in range(M["bullets"])] for h in document.HORIZONS},
        "paths": [{"side": side, "title": text(L["path_title"], "Centre first "),
                   "blurb": text(L["path_blurb"]),
                   "for": [text(L["path_point"])] * M["path_points"],
                   "against": [text(L["path_point"])] * M["path_points"]}
                  for side in ("a", "b")],
        "recommended": "a",
        "next_moves": [{"lead": text(24, "Approve the form "), "rest": text(L["next_move"] - 25)}
                       for _ in range(M["next_moves"])],
        "signoff": {"closing": text(L["closing"])},
    }


def overflow(session) -> list[int]:
    return pdf_service.overflowing_pages(session)


# ================================================ where the words come from

@pytest.mark.django_db
def test_before_anyone_writes_the_words_come_from_the_session(session):
    _a_full_session(session)
    context = pdf_service.context_for(session)
    words = document.merged(session, context)
    # The mirror: the first thing that unlocks it as the headline, the goal
    # beneath.
    assert words["mirror_headline"] == "Solid processes and accountability mechanisms."
    assert words["mirror_body"] == "To grow, but do it more sustainably."
    # A pill from each rating: Strong from 7, Watch at 5 and 6, Fix under.
    assert [document.pill_for(n) for n in (10, 7, 6, 5, 4, 1, None)] == [
        "strong", "strong", "watch", "watch", "fix", "fix", "watch"]
    # The map's rows, each under its horizon with its owner, four to a box.
    assert [len(words["boxes"][h]) for h in document.HORIZONS] == [3, 3, 3]
    assert words["boxes"]["30"][0] == {
        "text": "Bottleneck 0 — decisions stall waiting on the founder",
        "owner": "Noble Baker"}
    # Tile one counts the map until a goal says otherwise.
    assert words["tile"] == {"number": "9", "label": "fixes on the map, each with an owner"}
    assert words["closing"] == document.DEFAULT_CLOSING
    # Every default fits its line.
    for key in ("headline", "intro", "mirror_headline", "mirror_body", "closing"):
        assert len(words[key]) <= document.LIMITS[key], key


@pytest.mark.django_db
def test_tile_one_is_the_first_goals_target_once_the_map_has_goals(session, ff):
    _a_full_session(session, rows=1)
    row = StrategyMapRow.objects.get(session=session)
    conversion.convert(session, actor=ff.user, role="FF", choices={str(row.pk): {
        "as": "goal", "baseline_value": "48", "target_value": "85",
        "measurable_unit": "%", "direction": "up_is_good", "baseline_at": "2026-10-01"}})
    session.refresh_from_db()
    tile = pdf_service.context_for(session)["doc"]["tiles"][0]
    assert tile == {"number": "85%",
                    "label": "up from 48%: count of decisions…"}
    assert len(tile["label"]) <= document.LIMITS["tile_label"]


@pytest.mark.django_db
def test_saved_words_win_part_by_part_and_reset_returns_the_sessions_own(session, ff, api):
    _a_full_session(session)
    saved = patch(api, ff, session, {
        "headline": "One rhythm across the company.",
        "components": [{"key": "s2_process", "name": "Process", "pill": "watch",
                        "line": "Written down at one site of three."}],
        "boxes": {"30": [{"text": "Publish the approval ladder.", "owner": "Noble"}],
                  "60": [], "90": []},
        "recommended": "b"})
    assert saved.status_code == 200, saved.json()
    doc = pdf_service.context_for(session.__class__.objects.get(pk=session.pk))["doc"]
    assert doc["headline"] == "One rhythm across the company."
    assert {c["key"]: c["pill"] for c in doc["components"]}["s2_process"] == "watch"
    assert {c["key"]: c["pill"] for c in doc["components"]}["s2_vision"] == "strong", \
        "a component nobody touched keeps its pill from the rating"
    assert [box["days"] for box in doc["boxes"]] == ["30", "60", "90"]
    assert doc["boxes"][0]["bullets"] == [{"text": "Publish the approval ladder.",
                                           "owner": "Noble"}]
    assert doc["mirror"]["headline"] == "Solid processes and accountability mechanisms.", \
        "a part not saved still reads from the session"
    assert [p["recommended"] for p in doc["paths"]] == [False, True]
    html = pdf_service.render_html(session.__class__.objects.get(pk=session.pk))
    assert "<h1>One rhythm across the company.</h1>" in html
    assert "Publish the approval ladder. <b>Noble</b>" in html
    assert AuditEvent.all_objects.filter(verb="strategy.document_words_saved").exists()

    reset = patch(api, ff, session, {"reset": True})
    assert reset.status_code == 200 and reset.json()["saved"] == {}
    assert reset.json()["words"]["headline"] != "One rhythm across the company."


# ===================================================== lengths and the fit

@pytest.mark.django_db
def test_a_line_over_its_length_is_refused_and_named(session, ff, api):
    _a_full_session(session)
    refused = patch(api, ff, session, {
        "headline": text(61), "intro": "Fine.",
        "boxes": {"30": [{"text": text(71), "owner": "Noble"}]},
        "next_moves": [{"lead": "Pick the path", "rest": text(57)}]})
    assert refused.status_code == 400
    body = refused.json()
    assert body["over"] == {"headline": [61, 60], "boxes.30.0.text": [71, 70],
                            "next_moves.0": [71, 70]}
    assert "3 lines are over their length" in body["detail"]
    session.refresh_from_db()
    assert session.document_words == {}, "nothing of a refused save is kept"
    too_many = patch(api, ff, session, {"next_moves": [{"lead": "A", "rest": "b"}] * 5})
    assert too_many.status_code == 400 and "4 next moves at most" in too_many.json()["detail"]
    assert patch(api, ff, session, {"recommended": "c"}).status_code == 400


@pytest.mark.django_db
def test_words_at_the_mocks_own_lengths_fit_both_pages(session, ff, api):
    """The approved mock's words, as the demo has them, with room to spare."""
    from apps.tenancy.demo.sessions import WAYNE_WORDS

    _a_full_session(session)
    keys = [c["key"] for c in document.merged(session, pdf_service.context_for(session))[
        "components"]]
    words = WAYNE_WORDS
    saved = patch(api, ff, session, {
        **{key: words[key] for key in ("headline", "tile", "mirror_headline", "mirror_body",
                                       "working", "not_yet", "recommended")},
        "signoff": {"closing": words["closing"]},
        "components": [{"key": key, "name": name, "pill": "watch", "line": line}
                       for key, (name, line) in zip(keys, words["components"])],
        "boxes": {h: [{"text": t, "owner": o} for t, o in b] for h, b in words["boxes"].items()},
        "paths": words["paths"],
        "next_moves": [{"lead": lead, "rest": rest.format(pick="October 20")}
                       for lead, rest in words["next_moves"]]})
    assert saved.status_code == 200, saved.json()
    session.refresh_from_db()
    assert pdf_service.page_count(session) == 2 and overflow(session) == []


@pytest.mark.django_db
def test_a_save_that_would_overrun_a_page_is_refused_naming_the_page(session, ff, api):
    """Every line within its length can still, all together, fill a page. The
    longest words the limits allow, everywhere at once, are measured: a page
    they would overrun is named and nothing is kept; whatever is kept fits."""
    _a_full_session(session)
    saved = patch(api, ff, session, longest(session))
    session.refresh_from_db()
    if saved.status_code == 200:
        assert overflow(session) == []
    else:
        assert saved.status_code == 400
        assert "past" in saved.json()["detail"] and "foot" in saved.json()["detail"]
        assert saved.json()["errors"]["pages"]
        assert session.document_words == {}, "nothing of a refused save is kept"
        assert overflow(session) == []
    assert pdf_service.page_count(session) == 2


@pytest.mark.django_db
def test_the_fit_check_finds_an_overflow_when_there_is_one(session):
    """The check is only worth having if it can fail."""
    _a_full_session(session)
    session.document_words = {"mirror_body": text(1400)}
    session.save()
    assert overflow(session) == [1], "a mirror five times its length runs into the footer"


# ========================================================== Claude's draft

DRAFT = {
    "headline": "One operating rhythm across four sites.",
    "intro": "What we heard, where the gaps are, and the ninety days that close them.",
    "tile": {"number": "4", "label": "sites on one scorecard by day 90"},
    "mirror_headline": "Safety before the scorecard.",
    "mirror_body": "Arkham Road ran its first scorecard meeting. Lucius sends the report.",
    "working": "Gotham Central runs the weekly meeting — without us.",
    "not_yet": "Two sites still report on different forms.",
    "components": [{"key": "s2_vision", "line": "A plan nobody has read."},
                   {"key": "unknown", "line": "Dropped on use, kept as drafted."}],
    "boxes": {"30": [{"text": "Start-of-shift check at all four sites.", "owner": "Alfred"}],
              "60": [{"text": "One agenda.", "owner": ""}], "90": []},
    "paths": [{"side": "a", "title": "Sites first", "blurb": "Each lead runs it.",
               "for": ["Leads own the numbers"], "against": ["Slower first month"]}],
    "next_moves": [{"lead": "Approve the form", "rest": "Lucius sends Friday."}],
}


@pytest.mark.django_db
def test_claudes_draft_is_a_proposal_until_a_person_saves(session, ff, api, fake_claude):
    _a_full_session(session)
    answer(session, "s1_revenue", {"text": "4.2m"}, note="MARKERNOTE")
    before = pdf_service.render_html(session)
    fake_claude.reply = json.dumps(DRAFT)
    drafted = api.as_(ff).post(url(session, "draft-document-words/"))
    assert drafted.status_code == 200, drafted.json()
    proposed = drafted.json()["proposed"]
    assert proposed["headline"] == "One operating rhythm across four sites."
    assert proposed["working"] == "Gotham Central runs the weekly meeting, without us.", \
        "no em dashes in drafted words"
    assert proposed["boxes"]["30"] == [{"text": "Start-of-shift check at all four sites.",
                                        "owner": "Alfred"}]
    session.refresh_from_db()
    assert session.document_words == {}
    assert pdf_service.render_html(session) == before, "the document is unchanged"

    # What Claude was asked for, and what it was not given.
    request = fake_claude.requests[-1]
    system = request["system"] if isinstance(request["system"], str) else json.dumps(
        request["system"])
    for line in ('"headline": the one line the document leads with, at most 60',
                 "two to four bullets in each", '"mirror_body": up to three sentences, at '
                 "most 280", "Bullets, not paragraphs"):
        assert line in system, line
    sent = json.dumps(request["messages"])
    assert "MARKERNOTE" not in sent and "Investment" not in sent
    assert "Bottleneck 0" in sent and "Noble Baker" in sent
    assert AiCall.objects.filter(purpose=document.PURPOSE).count() == 1


@pytest.mark.django_db
def test_a_draft_that_does_not_come_back_changes_nothing(session, ff, api, fake_claude):
    _a_full_session(session)
    fake_claude.reply = "Not JSON at all."
    refused = api.as_(ff).post(url(session, "draft-document-words/"))
    assert refused.status_code == 502
    session.refresh_from_db()
    assert session.proposed_document_words == {} and session.document_words == {}


# ====================================== role boundaries and practice isolation

@pytest.mark.django_db
def test_an_assistant_reads_the_words_and_changes_none_of_them(session, va, api,
                                                              fake_claude):
    assert api.as_(va).get(url(session)).status_code == 200
    assert patch(api, va, session, {"headline": "Mine."}).status_code == 403
    assert api.as_(va).post(url(session, "draft-document-words/")).status_code == 403
    assert fake_claude.requests == []
    session.refresh_from_db()
    assert session.document_words == {}


@pytest.mark.django_db
def test_an_associate_changes_the_words_only_on_their_own_session(session, cf, api):
    assert patch(api, cf, session, {"headline": "Mine."}).status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FCC", "ECC"])
def test_no_client_user_reaches_the_words(session, api, role):
    client_user = _member(session.tenant, role,
                          company=ClientCompanyFactory(tenant=session.tenant))
    assert api.as_(client_user).get(url(session)).status_code in (403, 404)
    assert patch(api, client_user, session, {"headline": "x"}).status_code in (403, 404)


@pytest.mark.django_db
def test_another_practice_reaches_nothing(session, api, tenant_b, fake_claude):
    other = _member(tenant_b, "FF")
    assert api.as_(other).get(url(session)).status_code == 404
    assert patch(api, other, session, {"headline": "x"}).status_code == 404
    assert api.as_(other).post(url(session, "draft-document-words/")).status_code == 404
    session.refresh_from_db()
    assert session.document_words == {} and fake_claude.requests == []


# ==================================================== the sign-off band

@pytest.mark.django_db
def test_the_sign_off_comes_from_branding_with_sensible_fallbacks(session, ff, api):
    tenant = session.tenant
    tenant.brand_footer_text = "12 Main St · Denver\nhello@acme.example · www.acme.example"
    tenant.save()
    session.refresh_from_db()
    html = pdf_service.render_html(session)
    # No settings: the owner's email, the footer's web address, a standard line.
    assert f"{ff.user.email} · acme.example" in html
    assert document.DEFAULT_CLOSING in html

    saved = api.as_(ff).put("/api/settings/branding", json.dumps({
        "display_name": "", "primary_color": "#0A3A65", "accent_color": "#F58220",
        "footer_text": tenant.brand_footer_text,
        "document_closing": "Tell me what moved.", "document_email": "jo@acme.example",
        "document_website": "acme.example/maps"}), content_type="application/json")
    assert saved.status_code == 200, saved.json()
    assert saved.json()["document_closing"] == "Tell me what moved."
    session.refresh_from_db()
    html = pdf_service.render_html(session)
    assert "Tell me what moved." in html and "jo@acme.example · acme.example/maps" in html

    bad = api.as_(ff).put("/api/settings/branding", json.dumps({
        "display_name": "", "primary_color": "#0A3A65", "accent_color": "#F58220",
        "footer_text": "", "document_email": "not an email",
        "document_closing": text(121)}), content_type="application/json")
    assert bad.status_code == 400
    assert set(bad.json()["errors"]) >= {"document_email", "document_closing"}


def branding(api, ff, **signoff):
    saved = api.as_(ff).put("/api/settings/branding", json.dumps({
        "display_name": "", "primary_color": "#0A3A65", "accent_color": "#F58220",
        "footer_text": "", **signoff}), content_type="application/json")
    assert saved.status_code == 200, saved.json()


@pytest.mark.django_db
def test_a_document_with_no_sign_off_of_its_own_follows_branding_as_it_changes(
        session, ff, api):
    """The owner's finding (2026-10-17): "Back to the session's own words",
    then Save, then a new closing line in Branding. The document has the new
    line, because the editor saves no sign-off it was not given."""
    _a_full_session(session)
    branding(api, ff, document_closing="Tell me what moved.")
    assert patch(api, ff, session, {"reset": True}).status_code == 200
    shown = api.as_(ff).get(url(session)).json()
    body = {k: v for k, v in shown["words"].items()
            if k not in ("closing", "email", "website")}
    saved = patch(api, ff, session, {**body, "signoff": {}})
    assert saved.status_code == 200, saved.json()
    assert saved.json()["signoff"]["own"] == {}
    assert "signoff" not in saved.json()["saved"]

    branding(api, ff, document_closing="The map moves with you.",
             document_email="jo@acme.example", document_website="acme.example")
    session.refresh_from_db()
    html = pdf_service.render_html(session)
    assert "The map moves with you." in html and "Tell me what moved." not in html
    assert "jo@acme.example · acme.example" in html
    words = api.as_(ff).get(url(session)).json()
    assert words["words"]["closing"] == "The map moves with you."
    assert words["signoff"]["branding"]["closing"] == "The map moves with you."


@pytest.mark.django_db
def test_a_closing_line_saved_before_the_fix_is_branding_s_and_follows_it(session, ff,
                                                                          api):
    """Before 2026-10-17 the editor saved Branding's closing line, as it was
    then, with every save: the standard line, or the practice's own. Neither
    is the document's own, so the document has Branding's line as it is now,
    and the next save drops the copy."""
    _a_full_session(session)
    for copied in (document.DEFAULT_CLOSING, "Tell me what moved."):
        branding(api, ff, document_closing="" if copied == document.DEFAULT_CLOSING
                 else copied)
        session.document_words = {"headline": "Kept", "closing": copied}
        session.save()
        branding(api, ff, document_closing="The map moves with you.")
        session.refresh_from_db()
        assert document.signoff_overrides(session) == {}
        html = pdf_service.render_html(session)
        assert "The map moves with you." in html and "Kept" in html
        assert copied not in html
        shown = api.as_(ff).get(url(session)).json()
        assert shown["signoff"]["own"] == {}
        assert shown["words"]["closing"] == "The map moves with you."

    saved = patch(api, ff, session, {"headline": "Kept again"})
    assert saved.status_code == 200, saved.json()
    assert saved.json()["saved"] == {"headline": "Kept again"}


@pytest.mark.django_db
def test_a_sign_off_of_the_documents_own_wins_until_it_is_cleared(session, ff, api):
    _a_full_session(session)
    branding(api, ff, document_closing="Tell me what moved.",
             document_email="jo@acme.example", document_website="acme.example")
    saved = patch(api, ff, session, {"signoff": {
        "closing": "Written for Acme alone.", "email": "sam@acme.example",
        "website": "acme.example/acme"}})
    assert saved.status_code == 200, saved.json()
    assert saved.json()["signoff"]["own"] == {
        "closing": "Written for Acme alone.", "email": "sam@acme.example",
        "website": "acme.example/acme"}

    branding(api, ff, document_closing="The map moves with you.",
             document_email="kim@acme.example", document_website="acme.example/new")
    session.refresh_from_db()
    html = pdf_service.render_html(session)
    assert "Written for Acme alone." in html and "The map moves with you." not in html
    assert "sam@acme.example · acme.example/acme" in html

    # One line back to Branding's, by sending it empty or as Branding has it.
    saved = patch(api, ff, session, {"signoff": {
        "closing": "", "email": "kim@acme.example", "website": "acme.example/acme"}})
    assert saved.json()["signoff"]["own"] == {"website": "acme.example/acme"}
    assert saved.json()["words"]["closing"] == "The map moves with you."
    assert saved.json()["words"]["email"] == "kim@acme.example"

    # "Back to the session's own words" clears the rest.
    cleared = patch(api, ff, session, {"reset": True}).json()
    assert cleared["signoff"]["own"] == {} and cleared["saved"] == {}
    session.refresh_from_db()
    assert "kim@acme.example · acme.example/new" in pdf_service.render_html(session)

    bad = patch(api, ff, session, {"signoff": {"email": "not an email",
                                               "closing": text(101)}})
    assert bad.status_code == 400
    assert "signoff.email" in bad.json()["errors"] and "signoff.closing" in bad.json()["over"]


@pytest.mark.django_db
def test_the_header_wears_the_mark_or_the_logo_or_the_drawn_mark(session):
    """With no image the mock's own mark, drawn in the practice's colors."""
    html = pdf_service.render_html(session)
    assert '<svg width="34" height="30"' in html
    assert 'fill="' + session.tenant.email_header_color in html


@pytest.mark.django_db
def test_a_document_that_overruns_a_page_is_not_sent_and_the_editor_says_so(session, ff,
                                                                           api):
    from apps.crm.models import OutboxMessage

    _a_full_session(session)
    session.document_words = {"mirror_body": text(1400)}
    session.save()
    assert api.as_(ff).get(url(session)).json()["full_pages"] == [1]
    refused = api.as_(ff).post(url(session, "send-pdf/"))
    assert refused.status_code == 409 and refused.json()["full_pages"] == [1]
    assert "Page 1 of the document runs past the foot" in refused.json()["detail"]
    assert not OutboxMessage.all_objects.exists()
    session.document_words = {}
    session.save()
    assert api.as_(ff).get(url(session)).json()["full_pages"] == []
