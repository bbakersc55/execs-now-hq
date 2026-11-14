"""The SOP's eleven sections, the brain dump, training material and the
SOP's own Notebook pack, and accepted proposals that say where they went
(2026-11-14, docs/p10_sop_studio.md).

- **The layout:** the shipped eleven in order; a practice's copy renames
  (`# New name (Standard name)`), reorders and adds sections; an incomplete
  copy keeps the shipped order.
- **The overview:** numbers per company from the category, editable and
  unique; the review frequency sets the next review; the first publish sets
  the effective date.
- **The sections** saved, versioned, read in the portal, exported in order;
  a version from before them is not "changes not published yet".
- **Part A:** an accepted map is on the SOP at once, and every accepted
  proposal says where it went, with a link.
- **The brain dump:** priced first, nothing spent; filled into a proposal.
- **Training material** and **the SOP's Notebook pack**, with practice
  isolation and each role's boundary.
"""

from __future__ import annotations

import importlib
import io
import json
import zipfile
from datetime import date

import pytest
from dateutil.relativedelta import relativedelta
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.sops import layout as L
from apps.sops.models import BrainstormSource, Sop, SopTrainingAsset, SopVersion
from apps.tenancy.context import tenant_context

from .factories import MembershipFactory, TenantFactory
from .test_plans import client, get, on  # noqa: F401  (fixtures)
from .test_scorecard import patch, post, sc  # noqa: F401  (the fixture)
from .test_sops import BS, S, STEPS, new_sop, publish, storm  # noqa: F401  (fixture)

ELEVEN = ["overview", "purpose", "scope", "definitions", "roles", "steps", "flowchart",
          "related", "training", "metrics", "revisions"]


def png() -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (40, 30), "white").save(out, "PNG")
    return out.getvalue()


# ------------------------------------------------------------------ the layout

def test_the_shipped_layout_is_the_eleven_in_order():
    from apps.centers.content import operations

    shape = L.resolve(operations.DOCUMENTS["ops_sop"][2])
    assert [s["key"] for s in shape] == ELEVEN
    assert [s["title"] for s in shape][:3] == ["Overview", "Purpose", "Scope"]
    assert shape[-1]["title"] == "Revision history"


def test_a_complete_copy_renames_and_reorders_and_an_incomplete_one_falls_back():
    complete = "\n".join(
        ["# 1. About this SOP (Overview)", "# Why we do this (Purpose)", "# Scope",
         "# Words we use (Definitions and acronyms)", "# Roles and responsibilities",
         "# Safety notes", "Gloves on.", "# Procedure steps", "# Flowchart",
         "# Performance metrics and monitoring", "# Training requirements",
         "# Related documents and resources", "# Revision history"])
    shape = L.resolve(complete)
    assert [s["key"] for s in shape] == [
        "overview", "purpose", "scope", "definitions", "roles", "custom", "steps",
        "flowchart", "metrics", "training", "related", "revisions"]
    assert shape[0]["title"] == "About this SOP" and shape[1]["title"] == "Why we do this"
    assert shape[5] == {"key": "custom", "title": "Safety notes", "hint": "Gloves on."}
    # The old five-heading template: the shipped order and names, and an
    # extra heading before the revision history.
    old = "# Purpose\nWhy.\n# Roles\n# Steps\n1.\n# Measures\n# Review date\n# Records\nKeep them."
    shape = L.resolve(old)
    assert [s["key"] for s in shape] == ELEVEN[:-1] + ["custom", "revisions"]
    assert shape[4]["title"] == "Roles and responsibilities" and shape[1]["hint"] == "Why."
    assert shape[-2]["title"] == "Records"


def test_a_practice_copy_sets_the_editor_portal_and_export_order(on):
    from apps.esign.models import DocumentTemplate

    from apps.sops import exports

    sc = on
    with tenant_context(sc["tenant"].pk):
        DocumentTemplate.objects.create(
            tenant=sc["tenant"], original="ops_sop", name="SOP", title="SOP", body="\n".join(
                ["# Overview", "# Why we do this (Purpose)", "# Scope", "# Procedure steps",
                 "# Definitions and acronyms", "# Roles and responsibilities", "# Flowchart",
                 "# Related documents and resources", "# Training requirements",
                 "# Performance metrics and monitoring", "# Safety notes", "# Revision history"]))
    made = new_sop(sc, purpose="Ship it right.")
    full = get(sc, "ff", f"{S}{made['id']}/").json()
    assert [s["key"] for s in full["layout"]][:5] == ["overview", "purpose", "scope", "steps",
                                                     "definitions"]
    assert full["layout"][1]["title"] == "Why we do this"
    assert full["sections"] == [{"title": "Safety notes", "body": ""}]
    with tenant_context(sc["tenant"].pk):
        html = exports.body_html(Sop.objects.get(pk=made["id"]))
    assert html.index("<h2>Why we do this</h2>") < html.index("<h2>Procedure steps</h2>") \
        < html.index("<h2>Definitions and acronyms</h2>")


# ------------------------------------------------------------------ the overview

def test_numbers_per_company_from_the_category_editable_and_unique(on):
    from .factories import ClientCompanyFactory

    sc = on
    a = new_sop(sc, title="One", category="Operations")
    b = new_sop(sc, title="Two", category="Operations")
    c = new_sop(sc, title="Three")
    assert (a["number"], b["number"], c["number"]) == ("OPS-01", "OPS-02", "SOP-01")
    # A draft's automatic number follows its category…
    r = patch(client(sc, "ff"), f"{S}{c['id']}/", {"category": "Quality"})
    assert r.json()["number"] == "QA-01"
    # …until a person types one.
    r = patch(client(sc, "ff"), f"{S}{c['id']}/", {"number": "qa 7"})
    assert r.json()["number"] == "QA-7" and r.json()["number_by_hand"] is True
    assert patch(client(sc, "ff"), f"{S}{c['id']}/", {"category": "Safety"}).json()["number"] \
        == "QA-7"
    r = patch(client(sc, "ff"), f"{S}{b['id']}/", {"number": "OPS-01"})
    assert r.status_code == 400 and "already" in r.json()["detail"]
    # Published, the number stays whatever the category becomes.
    publish(sc, a["id"])
    assert patch(client(sc, "ff"), f"{S}{a['id']}/", {"category": "Sales"}).json()["number"] \
        == "OPS-01"
    # Another company starts again at 01.
    with tenant_context(sc["tenant"].pk):
        other = ClientCompanyFactory(tenant=sc["tenant"])
    r = post(client(sc, "ff"), S, {"company": str(other.pk), "title": "Elsewhere",
                                   "category": "Operations", "steps": STEPS})
    assert r.json()["number"] == "OPS-01"


def test_review_frequency_sets_the_next_review_and_publish_sets_the_dates(on):
    sc = on
    made = new_sop(sc, category="Shipping")
    today = timezone.localdate()
    url = f"{S}{made['id']}/"
    start = (today - relativedelta(months=4)).isoformat()
    r = patch(client(sc, "ff"), url, {"effective_date": start, "review_months": 3,
                                      "review_date": made["review_date"]})
    expected = date.fromisoformat(start) + relativedelta(months=6)   # rolled past today
    assert r.json()["review_date"] == expected.isoformat()
    assert r.json()["review_label"] == "Quarterly"
    assert patch(client(sc, "ff"), url, {"review_months": 18}).json()["review_label"] \
        == "Every 18 months"
    assert patch(client(sc, "ff"), url, {"review_months": 0}).status_code == 400
    assert patch(client(sc, "ff"), url, {"review_months": 61}).status_code == 400
    # A date typed by hand with the frequency wins.
    r = patch(client(sc, "ff"), url, {"review_months": 12, "review_date": "2030-01-01"})
    assert r.json()["review_date"] == "2030-01-01"
    fresh = new_sop(sc, title="Fresh")
    patch(client(sc, "ff"), f"{S}{fresh['id']}/", {"review_months": 6})
    publish(sc, fresh["id"])
    after = get(sc, "ff", f"{S}{fresh['id']}/").json()
    assert after["effective_date"] is not None
    assert after["review_date"] == (date.fromisoformat(after["effective_date"])
                                    + relativedelta(months=6)).isoformat()


# ------------------------------------------------------------------ the sections

def test_the_sections_are_saved_versioned_and_read_in_the_portal(on):
    sc = on
    other = new_sop(sc, title="Receiving")
    made = new_sop(sc, title="Picking")
    url = f"{S}{made['id']}/"
    r = patch(client(sc, "ff"), url, {
        "definitions": [{"term": "SKU", "definition": "A stock-keeping unit"}, {"term": ""}],
        "related": [{"kind": "link", "title": "Bin map", "url": "https://example.com/bins"},
                    {"kind": "sop", "ref": other["id"]}],
        "steps": [{"text": "Pick it", "when": "When the list prints", "role": "Picker"}],
        "training": "Two supervised picks.", "metrics": "Mis-picks a week, by Ana."})
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["definitions"] == [{"term": "SKU", "definition": "A stock-keeping unit"}]
    assert body["related"][1]["title"] == "Receiving" and body["related"][1]["href"] \
        == f"/sops/{other['id']}"
    assert body["steps"][0]["when"] == "When the list prints"
    bad = patch(client(sc, "ff"), url, {"related": [{"kind": "link", "url": "ftp://x"}]})
    assert bad.status_code == 400
    assert patch(client(sc, "ff"), url, {"related": [{"kind": "sop", "ref": made["id"]}]}) \
        .status_code == 400                                   # itself isn't related
    publish(sc, made["id"])
    reader = get(sc, "member", url).json()
    assert [s["key"] for s in reader["layout"]] == ELEVEN
    assert reader["number"] == made["number"] and reader["training"] == "Two supervised picks."
    assert reader["steps"][0]["when"] == "When the list prints"
    assert reader["revisions"][0]["version"] == 1 and reader["revisions"][0]["author"]
    # The other SOP is a draft: named, but no link for the reader.
    assert reader["related"][1]["href"] is None


def test_a_version_from_before_the_sections_is_not_changes_to_publish(on):
    sc = on
    made = new_sop(sc)
    publish(sc, made["id"])
    old_keys = {"title", "purpose", "applies_when", "roles", "steps", "sections", "owner",
                "category", "review_date", "process_map", "kpis", "attachments"}
    with tenant_context(sc["tenant"].pk):
        v = SopVersion.objects.get(sop_id=made["id"])
        v.snapshot = {k: val for k, val in v.snapshot.items() if k in old_keys}
        v.snapshot["steps"] = [{k: x for k, x in s.items() if k != "when"}
                               for s in v.snapshot["steps"]]
        v.save()
        # As the migration leaves an SOP published before: numbered, no effective date.
        Sop.objects.filter(pk=made["id"]).update(effective_date=None)
    full = get(sc, "ff", f"{S}{made['id']}/").json()
    assert full["unpublished_changes"] is False
    reader = get(sc, "member", f"{S}{made['id']}/").json()
    assert reader["definitions"] == [] and reader["training"] == ""


def test_the_exports_carry_the_eleven_sections_in_order(on):
    from docx import Document as Word

    from apps.sops import exports

    sc = on
    made = new_sop(sc, title="Picking", purpose="Ship it right.")
    patch(client(sc, "ff"), f"{S}{made['id']}/", {
        "definitions": [{"term": "SKU", "definition": "A stock-keeping unit"}],
        "training": "Two supervised picks."})
    publish(sc, made["id"])
    with tenant_context(sc["tenant"].pk):
        sop = Sop.objects.get(pk=made["id"])
        html = exports.body_html(sop)
        word = Word(io.BytesIO(exports.docx(sop)))
    titles = ["Overview", "Purpose", "Scope", "Definitions and acronyms",
              "Roles and responsibilities", "Procedure steps", "Flowchart",
              "Related documents and resources", "Training requirements",
              "Performance metrics and monitoring", "Revision history"]
    at = [html.index(f"<h2>{t}</h2>") for t in titles]
    assert at == sorted(at)
    assert "SKU" in html and "First version." in html and made["number"] in html
    headings = [p.text for p in word.paragraphs if p.style.name == "Heading 1"]
    assert headings == titles


def test_existing_sops_are_numbered_by_the_migration(on):
    from django.apps import apps as django_apps

    sc = on
    a, b, c = (new_sop(sc, title=t, category=cat) for t, cat in
               (("A", "Operations"), ("B", "Operations"), ("C", "")))
    with tenant_context(sc["tenant"].pk):
        Sop.objects.filter(pk__in=[a["id"], b["id"], c["id"]]).update(number="")
    step = importlib.import_module("apps.sops.migrations.0002_sop_layout_and_training")
    step.number_existing(django_apps, None)
    with tenant_context(sc["tenant"].pk):
        got = dict(Sop.objects.filter(pk__in=[a["id"], b["id"], c["id"]])
                   .values_list("title", "number"))
    assert got == {"A": "OPS-01", "B": "OPS-02", "C": "SOP-01"}


# ------------------------------------------------------------------ part A: where it went

def test_an_accepted_map_is_on_the_sop_at_once_and_says_where_it_went(storm):
    from apps.sops import flow

    sc, fake = storm, storm["claude"]
    made = new_sop(sc, title="Picking orders")
    r = post(client(sc, "ff"), BS, {"sop": made["id"]})
    storm_id = r.json()["id"]
    url = f"{BS}{storm_id}/"
    post(client(sc, "ff"), f"{url}sources/", {"kind": "pasted", "text": "Paper lists."})
    fake.reply = json.dumps({"map": flow.from_steps(STEPS), "why": "The steps."})
    proposal = post(client(sc, "ff"), f"{url}act/map/").json()["proposals"][0]
    before = get(sc, "ff", f"{S}{made['id']}/").json()["updated_at"]
    r = post(client(sc, "ff"), f"{url}proposals/{proposal['id']}/accept/")
    landed = next(p for p in r.json()["proposals"] if p["id"] == proposal["id"])["landed"]
    assert landed["href"] == f"/sops/{made['id']}#flowchart"
    assert "flowchart of the SOP “Picking orders”" in landed["text"]
    sop = get(sc, "ff", f"{S}{made['id']}/").json()
    assert sop["process_map"].startswith("flowchart TD") and sop["map_svg"].startswith("<svg")
    assert sop["updated_at"] != before         # the editor's key changes, so it shows the map


def test_a_draft_fills_every_section_and_says_where_it_went(storm):
    sc, fake = storm, storm["claude"]
    url = f"{BS}{sc['storm']['id']}/"
    post(client(sc, "ff"), f"{url}sources/", {"kind": "pasted", "text": "How we pick."})
    fake.reply = json.dumps({
        "title": "Picking orders", "category": "Shipping", "review_months": 6,
        "purpose": "Ship it right.", "applies_when": "Every order, both shifts.",
        "definitions": [{"term": "SKU", "definition": "A stock-keeping unit"}],
        "roles": [{"name": "Picker", "does": "Picks and scans"}],
        "steps": [{"text": "Print the list", "role": "Picker", "when": "When an order lands",
                   "warning": ""}, {"text": "Scan each bin", "role": "Picker", "when": "",
                                    "warning": "Never skip a scan"}],
        "map": "flowchart TD\n  a([Order]) --> b[Pick]", "related": [{"title": "Bin map"}],
        "training": "Two supervised picks.", "metrics": "Mis-picks a week.", "why": "x"})
    proposal = post(client(sc, "ff"), f"{url}act/draft/").json()["proposals"][0]
    assert proposal["payload"]["definitions"][0]["term"] == "SKU"
    system = fake.requests[-1]["messages"][-1]["content"]
    assert "definitions" in str(system) and "training" in str(system)
    r = post(client(sc, "ff"), f"{url}proposals/{proposal['id']}/accept/")
    sop_id = r.json()["sop"]["id"]
    landed = next(p for p in r.json()["proposals"] if p["id"] == proposal["id"])["landed"]
    assert landed["href"] == f"/sops/{sop_id}"
    sop = get(sc, "ff", f"{S}{sop_id}/").json()
    assert sop["applies_when"] == "Every order, both shifts."
    assert sop["definitions"] == [{"term": "SKU", "definition": "A stock-keeping unit"}]
    assert sop["steps"][0]["when"] == "When an order lands"
    assert sop["process_map"].startswith("flowchart TD")
    assert sop["related"][0]["title"] == "Bin map"
    assert (sop["training"], sop["metrics"], sop["review_months"]) == \
        ("Two supervised picks.", "Mis-picks a week.", 6)
    assert sop["number"] == "SHP-01"


def test_a_checklist_and_measures_say_where_they_went(storm):
    from apps.work.models import Goal, Project

    sc, fake = storm, storm["claude"]
    url = f"{BS}{sc['storm']['id']}/"
    post(client(sc, "ff"), f"{url}sources/", {"kind": "pasted", "text": "Paper lists."})
    with tenant_context(sc["tenant"].pk):
        goal = Goal.objects.create(tenant=sc["tenant"], client_company=sc["company"],
                                   title="Ship on time", owner=sc["practice"]["ff"].user)
        project = Project.objects.create(tenant=sc["tenant"], client_company=sc["company"],
                                         goal=goal, title="Picking",
                                         owner=sc["practice"]["ff"].user)
    fake.reply = json.dumps({"tasks": [{"title": "Train the night shift"}], "why": "x"})
    checklist = post(client(sc, "ff"), f"{url}act/checklist/").json()["proposals"][0]
    r = post(client(sc, "ff"), f"{url}proposals/{checklist['id']}/accept/",
             {"edits": {"project": str(project.pk)}})
    landed = next(p for p in r.json()["proposals"] if p["id"] == checklist["id"])["landed"]
    assert landed["href"] == f"/work/projects/{project.pk}" and "under “Picking”" in landed["text"]
    fake.reply = json.dumps({"kpis": [{"name": "For everyone", "why": "b"}]})
    measures = post(client(sc, "ff"), f"{url}act/measures/").json()["proposals"][0]
    r = post(client(sc, "ff"), f"{url}proposals/{measures['id']}/accept/")
    landed = next(p for p in r.json()["proposals"] if p["id"] == measures["id"])["landed"]
    assert landed["href"].endswith("#metrics") and "For everyone" in landed["text"]


# ------------------------------------------------------------------ the brain dump

def test_the_brain_dump_is_priced_first_then_fills_a_proposal(on, fake_claude):
    sc = on
    made = new_sop(sc, title="Cycle counts")
    base = f"{S}{made['id']}/brain-dump/"
    r = post(client(sc, "ff"), base, {})
    assert r.status_code == 201 and r.json()["sop"]["id"] == made["id"]
    storm_id = r.json()["id"]
    assert post(client(sc, "ff"), base, {}).json()["id"] == storm_id     # the same one
    image = client(sc, "ff").post(f"{BS}{storm_id}/sources/",
                                  {"file": SimpleUploadedFile("bins.png", png(), "image/png")})
    assert image.status_code == 201, image.content
    price = post(client(sc, "ff"), f"{base}price/", {"text": "We count bins on Fridays."})
    assert price.status_code == 200 and float(price.json()["estimate_usd"]) > 0
    assert price.json()["images"] == 1 and fake_claude.requests == []    # nothing spent
    empty = new_sop(sc, title="Nothing yet")
    r = post(client(sc, "ff"), f"{S}{empty['id']}/brain-dump/fill/", {"text": ""})
    assert r.status_code == 409 and fake_claude.requests == []
    fake_claude.reply = json.dumps({"title": "Cycle counts", "steps": [{"text": "Count bin A"}],
                                    "why": "From the notes."})
    r = post(client(sc, "ff"), f"{base}fill/", {"text": "We count bins on Fridays."})
    assert r.status_code == 201, r.content
    body = r.json()
    assert [p["kind"] for p in body["proposals"] if p["state"] == "proposed"] == ["draft"]
    assert {s["kind"] for s in body["sources"]} == {"image", "pasted"}
    assert len(fake_claude.requests) == 1
    # Nothing applied before it is accepted.
    assert get(sc, "ff", f"{S}{made['id']}/").json()["steps"][0]["text"] == STEPS[0]["text"]
    # Who: an assistant may; a client never; a published SOP has no brain dump.
    assert post(client(sc, "va"), f"{base}price/", {"text": "x"}).status_code == 200
    assert post(client(sc, "owner"), f"{base}price/", {"text": "x"}).status_code == 404
    publish(sc, made["id"])
    assert post(client(sc, "ff"), f"{base}price/", {"text": "x"}).status_code == 409


# ------------------------------------------------------------------ training material

def test_training_material_files_and_links_seen_by_the_audience_only(on, settings):
    sc = on
    made = new_sop(sc, title="Picking")
    url = f"{S}{made['id']}/training/"
    r = client(sc, "ff").post(url, {"kind": "quiz", "title": "Picking quiz",
                                    "file": SimpleUploadedFile("quiz.pdf", b"%PDF-1.4 quiz",
                                                               "application/pdf")})
    assert r.status_code == 201, r.content
    r = post(client(sc, "va"), url, {"kind": "video", "title": "Walkthrough",
                                     "url": "https://drive.google.com/file/d/abc/view"})
    assert r.status_code == 201
    assert post(client(sc, "ff"), url, {"kind": "video", "url": "http://plain"}).status_code \
        == 400
    assert post(client(sc, "ff"), url, {"kind": "mixtape", "url": "https://x.y"}).status_code \
        == 400
    from apps.sops import services

    settings_limit = services.TRAINING_LIMITS_MB["slides"]
    services.TRAINING_LIMITS_MB["slides"] = 0
    try:
        big = client(sc, "ff").post(url, {"kind": "slides", "title": "Deck", "file":
                                          SimpleUploadedFile("deck.pdf", b"x" * 10,
                                                             "application/pdf")})
        assert big.status_code == 400 and "MB at most" in big.json()["detail"]
    finally:
        services.TRAINING_LIMITS_MB["slides"] = settings_limit
    assets = r.json()["training_assets"]
    assert [a["kind"] for a in assets] == ["quiz", "video"]
    # Clients add nothing; another practice sees nothing.
    assert post(client(sc, "owner"), url, {"kind": "quiz", "url": "https://x.y"}).status_code \
        in (403, 404)
    stranger = MembershipFactory(tenant=TenantFactory(), role="FF")
    assert sc["api"].as_(stranger).get(assets[0]["url"]).status_code == 404
    # The audience sees them with the published SOP; outside it, 404.
    patch(client(sc, "ff"), f"{S}{made['id']}/", {
        "audience": "teams", "teams": [str(sc["teams"]["ops"].pk)]})
    publish(sc, made["id"])
    reader = get(sc, "member", f"{S}{made['id']}/").json()
    assert [a["title"] for a in reader["training_assets"]] == ["Picking quiz", "Walkthrough"]
    assert get(sc, "member", assets[0]["url"]).content == b"%PDF-1.4 quiz"
    assert get(sc, "sales_member", assets[0]["url"]).status_code == 404
    gone = client(sc, "ff").delete(f"{url}{assets[0]['id']}/")
    assert gone.status_code == 200 and len(gone.json()["training_assets"]) == 1
    with tenant_context(sc["tenant"].pk):
        assert SopTrainingAsset.objects.filter(sop_id=made["id"]).count() == 1


def test_the_sops_own_notebook_pack_and_what_is_never_in_it(on):
    from apps.notes.models import Note
    from apps.sops import brainstorm as B

    sc = on
    made = new_sop(sc, title="Picking")
    with tenant_context(sc["tenant"].pk):
        sop = Sop.objects.get(pk=made["id"])
        storm = B.start(sc["company"], actor=sc["practice"]["ff"].user, sop=sop)
        B.add_pasted(storm, title="Transcript", text="Ana picks by the map.",
                     actor=sc["practice"]["ff"].user)
        note = Note.objects.create(tenant=sc["tenant"], created_by=sc["practice"]["ff"].user,
                                   title="Private", body="A note's words.")
        BrainstormSource.objects.create(tenant=sc["tenant"], brainstorm=storm,
                                        kind=BrainstormSource.Kind.NOTE, title="A note",
                                        text="A note's words.", source_id=note.pk)
    r = get(sc, "ff", f"{S}{made['id']}/pack/")
    assert r.status_code == 200 and r["Content-Type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = zf.namelist()
        prompts = zf.read(names[1]).decode()
        everything = b"".join(zf.read(n) for n in names)
    assert names[:3] == ["00 README.md", "01 prompts.md", "02 SOP - Picking (draft).pdf"]
    assert names[3] == "03 Source - Transcript.md" and len(names) == 4
    for kind in ("Quiz", "Flashcards", "Slide deck", "Video overview", "Audio overview"):
        assert f". {kind}" in prompts
    assert b"A note's words." not in everything
    assert get(sc, "va", f"{S}{made['id']}/pack/").status_code == 404
    assert get(sc, "owner", f"{S}{made['id']}/pack/").status_code == 404
    with tenant_context(sc["tenant"].pk):
        from apps.tenancy.models import AuditEvent

        assert AuditEvent.objects.filter(verb="sops.pack_built",
                                         payload__sop=made["id"]).exists()
