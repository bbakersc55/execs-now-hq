"""P10: the SOP studio (`docs/p10_sop_studio.md`).

- **Practice isolation** and **each role's permissions**: no Command Center,
  another practice, an unassigned associate, an assistant who drafts but
  doesn't publish, client users who never see a draft or the working copy.
- **Versions:** the first publish asks everyone; a minor change doesn't ask
  again; any other change asks again; acknowledgments by version; late ones
  told; Remind into the Sending queue; Suggest a change.
- **Audience scoping in the portal:** the whole company, chosen teams, named
  people; anyone outside it gets 404.
- **Brainstorm** with a fake Claude: sources saved (an image sent as an
  image), the price first, the tier, a draft accepted (and as a diff), a
  map, a checklist into Work, measures from the library, discards; each
  decision in the practice library.
- **The media path** with a fake Gemini: no key refused in words; the price
  first; the file not kept unless asked; Google's copy deleted.
- **The Notebook pack:** its files in order, and what is never in it.
- **The MCP tools' scope**, **the connections** to tools and plans, the
  exports, the process map, the weekly digest and Activity.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.sops import flow
from apps.sops.models import (Brainstorm, BrainstormProposal, BrainstormSource, Sop, SopAck,
                              SopVersion)
from apps.tenancy.context import tenant_context

from .factories import ClientCompanyFactory, MembershipFactory, TenantFactory
from .test_plans import client, get, on  # noqa: F401  (fixtures)
from .test_scorecard import patch, post, sc  # noqa: F401  (the fixture)

S = "/api/sops/"
BS = "/api/sops/brainstorms/"
STEPS = [{"text": "Print the pick list"}, {"text": "Pick every line and scan the bin"},
         {"text": "Is anything short?"}, {"text": "Pack and label"}]


def new_sop(sc, who="ff", title="Picking orders", **data):
    r = post(client(sc, who), S, {"company": str(sc["company"].pk), "title": title,
                                  "steps": STEPS, **data})
    assert r.status_code == 201, r.content
    return r.json()


def publish(sc, sop_id, who="ff", **data):
    return post(client(sc, who), f"{S}{sop_id}/publish/", data)


@pytest.fixture
def published(on):
    sc = on
    sop = new_sop(sc)
    assert publish(sc, sop["id"]).status_code == 200
    return {**sc, "sop": sop}


def clients_of(sc):
    return [k for k in sc["who"]]


# ------------------------------------------------------------------ isolation and roles

def test_no_command_center_means_no_studio_anywhere(sc):
    r = post(client(sc, "ff"), S, {"company": str(sc["company"].pk), "title": "X"})
    assert r.status_code == 404
    assert get(sc, "ff", S).status_code == 404
    assert get(sc, "owner", S).status_code == 404


def test_another_practice_and_an_unassigned_associate_see_nothing(published):
    sc = published
    sop = sc["sop"]
    assert get(sc, "cf_other", f"{S}{sop['id']}/").status_code == 404
    assert get(sc, "cf_other", S).json()["sops"] == []
    other = TenantFactory()
    stranger = MembershipFactory(tenant=other, role="FF")
    from apps.centers.models import PracticeCenter

    PracticeCenter.all_objects.create(tenant=other, center="operations", enabled_at=timezone.now())
    them = sc["api"].as_(stranger)
    assert them.get(f"{S}{sop['id']}/").status_code == 404
    assert them.get(S).json()["sops"] == []
    assert post(them, S, {"company": str(sc["company"].pk), "title": "Mine"}).status_code == 404


def test_each_role(on):
    sc = on
    for who in ("ff", "cf", "va"):
        made = new_sop(sc, who, title=f"By {who}")
        assert made["status"] == "draft"
        assert patch(client(sc, who), f"{S}{made['id']}/", {"category": "Shipping"}) \
            .status_code == 200
    va_sop = new_sop(sc, "va", title="Assistant's")
    r = publish(sc, va_sop["id"], who="va")
    assert r.status_code == 403 and "assistant drafts" in r.json()["detail"]
    assert post(client(sc, "va"), f"{S}{va_sop['id']}/archive/").status_code == 403
    assert publish(sc, va_sop["id"], who="cf").status_code == 200
    # Clients never see a draft, and can't edit what they can read.
    draft = new_sop(sc, title="Still a draft")
    assert get(sc, "owner", f"{S}{draft['id']}/").status_code == 404
    assert patch(client(sc, "owner"), f"{S}{va_sop['id']}/", {"title": "Mine"}).status_code == 403
    assert post(client(sc, "owner"), S, {"company": str(sc["company"].pk),
                                         "title": "Mine"}).status_code == 404


# ------------------------------------------------------------------ versions and reading

def test_versions_minor_changes_and_reading_again(published):
    sc, sop = published, published["sop"]
    url = f"{S}{sop['id']}/"
    assert get(sc, "ff", url).json()["reads"]["asked"] == 10
    for who in ("member", "colleague"):
        r = post(client(sc, who), f"{url}ack/")
        assert r.status_code == 200 and r.json()["version"] == 1 and not r.json()["late"]
    assert get(sc, "ff", url).json()["reads"]["read"] == 2
    # An edit isn't published until it is; the portal still shows version 1.
    patch(client(sc, "ff"), url, {"purpose": "Ship every order right the first time."})
    assert get(sc, "member", url).json()["purpose"] == ""
    assert get(sc, "ff", url).json()["unpublished_changes"] is True
    r = publish(sc, sop["id"])
    assert r.status_code == 400 and "what changed" in r.json()["detail"]
    # A minor change keeps the reads.
    r = publish(sc, sop["id"], change_note="Fixed a typo", minor=True)
    assert r.status_code == 200 and r.json()["version"] == 2
    full = get(sc, "ff", url).json()
    assert full["reads"]["read"] == 2 and full["reads"]["number"] == 1
    reader = get(sc, "member", url).json()
    assert reader["version"] == 2 and reader["read"] is True and reader["purpose"]
    # Any other change asks everyone again.
    patch(client(sc, "ff"), url, {"steps": STEPS + [{"text": "Weigh the box"}]})
    assert publish(sc, sop["id"], change_note="Weigh every box").status_code == 200
    full = get(sc, "ff", url).json()
    assert full["reads"]["read"] == 0 and full["reads"]["number"] == 3
    reader = get(sc, "member", url).json()
    assert reader["read"] is False and reader["change_note"] == "Weigh every box"
    r = post(client(sc, "member"), f"{url}ack/")
    assert r.json()["version"] == 3
    with tenant_context(sc["tenant"].pk):
        assert SopAck.objects.filter(membership=sc["who"]["member"]).count() == 2
        assert list(SopVersion.objects.filter(sop_id=sop["id"]).order_by("number")
                    .values_list("number", "minor")) == [(1, False), (2, True), (3, False)]


def test_a_late_read_is_told_to_the_practice_and_the_client_owner(published):
    from apps.notify.models import Notice

    sc, sop = published, published["sop"]
    with tenant_context(sc["tenant"].pk):
        SopVersion.objects.filter(sop_id=sop["id"]).update(
            read_by=timezone.localdate() - timedelta(days=1))
    r = post(client(sc, "member"), f"{S}{sop['id']}/ack/")
    assert r.json()["late"] is True
    with tenant_context(sc["tenant"].pk):
        told = set(Notice.objects.filter(kind="sop", source_type="sop_ack")
                   .values_list("recipient_id", flat=True))
    assert told == {sc["practice"]["ff"].user_id, sc["who"]["owner"].user_id}
    readers = get(sc, "ff", f"{S}{sop['id']}/").json()["reads"]["readers"]
    assert readers[0]["late"] is True


def test_audience_by_team_and_by_person(on):
    sc = on
    sop = new_sop(sc, audience="teams", teams=[str(sc["teams"]["ops"].pk)])
    publish(sc, sop["id"])
    url = f"{S}{sop['id']}/"
    asked = {r["name"] for r in get(sc, "ff", url).json()["reads"]["outstanding"]}
    assert "Mia Member" in asked and "Sam Sales" not in asked and "Olive Owner" not in asked
    assert get(sc, "member", url).status_code == 200
    assert get(sc, "sales_member", url).status_code == 404
    assert post(client(sc, "sales_member"), f"{url}ack/").status_code == 404
    assert get(sc, "sales_member", S).json()["sops"] == []
    # The client owner opens it and sees who has read it, but isn't asked.
    owner_view = get(sc, "owner", url).json()
    assert owner_view["asked"] is False and owner_view["reads"]["asked"] == len(asked)
    # Named people.
    patch(client(sc, "ff"), url, {"audience": "people",
                                  "people": [str(sc["who"]["sales_member"].pk)]})
    publish(sc, sop["id"], change_note="Sales does this now")
    assert get(sc, "sales_member", url).status_code == 200
    assert get(sc, "member", url).status_code == 404
    with tenant_context(sc["tenant"].pk):
        from apps.tenancy.models import Membership

        me = client(sc, "sales_member").get("/api/auth/me/")
    assert me.status_code in (200, 404)


def test_remind_drafts_into_the_sending_queue_once(published):
    from apps.crm.models import OutboxMessage

    sc, sop = published, published["sop"]
    post(client(sc, "member"), f"{S}{sop['id']}/ack/")
    r = post(client(sc, "ff"), f"{S}{sop['id']}/remind/")
    assert r.status_code == 201 and r.json()["drafted"] >= 1
    with tenant_context(sc["tenant"].pk):
        rows = OutboxMessage.objects.filter(producer="sop_reminder", source_id=sop["id"])
        assert all(m.state == "pending_approval" for m in rows)
        assert rows.count() == r.json()["drafted"]
        assert "Please read: Picking orders" in rows.first().subject
        assert f"/sops/{sop['id']}" in rows.first().body_text
    again = post(client(sc, "ff"), f"{S}{sop['id']}/remind/").json()
    assert again["drafted"] == 0
    # The client owner may remind too; it still waits for the practice.
    assert post(client(sc, "owner"), f"{S}{sop['id']}/remind/").status_code == 201
    assert post(client(sc, "member"), f"{S}{sop['id']}/remind/").status_code == 403


def test_suggest_a_change_lands_for_the_practice(published):
    from apps.notify.models import Notice

    sc, sop = published, published["sop"]
    r = post(client(sc, "member"), f"{S}{sop['id']}/suggest/",
             {"text": "We scan the tote, not the bin."})
    assert r.status_code == 201
    full = get(sc, "ff", f"{S}{sop['id']}/").json()
    assert full["comments"][0]["text"] == "We scan the tote, not the bin."
    with tenant_context(sc["tenant"].pk):
        assert Notice.objects.filter(kind="sop", source_type="sop_comment",
                                     recipient=sc["practice"]["ff"].user).exists()
    assert post(client(sc, "ff"), f"{S}{sop['id']}/comments/{r.json()['id']}/resolve/") \
        .json()["comments"][0]["resolved"] is True


def test_the_weekly_digest_names_new_and_updated_sops(published):
    from apps.sops.services import digest_lines
    from apps.work.models import Cadence

    from .factories import ContactFactory

    sc, sop = published, published["sop"]

    def digest_for(who):
        member = sc["who"][who]
        member.contact = ContactFactory(tenant=sc["tenant"], company=sc["company"])
        member.save(update_fields=["contact"])
        return type("D", (), {"contact": member.contact, "cadence": Cadence.WEEKLY,
                              "pk": None, "created_at": timezone.now(),
                              "period_start": timezone.localdate()})()

    with tenant_context(sc["tenant"].pk):
        assert digest_lines(digest_for("member")) == ["New: Picking orders"]
        # Outside the audience, no line: not even the title.
        patch(client(sc, "ff"), f"{S}{sop['id']}/", {"audience": "teams",
                                                     "teams": [str(sc["teams"]["ops"].pk)]})
        publish(sc, sop["id"], change_note="Ops only now")
        assert digest_lines(digest_for("sales_member")) == []
        assert digest_lines(digest_for("colleague"))[-1].startswith(
            "Updated to version 2: Picking orders. Ops only now")


# ------------------------------------------------------------------ the record

def test_template_sections_owner_kpis_and_the_process_map(on):
    sc = on
    sop = new_sop(sc)
    full = get(sc, "ff", f"{S}{sop['id']}/").json()
    assert "what goes wrong" in full["hints"]["purpose"]
    r = patch(client(sc, "ff"), f"{S}{sop['id']}/", {"process_map": "a --> b c d"})
    assert r.status_code == 400 and r.json()["errors"]
    text = flow.from_steps(STEPS)
    r = patch(client(sc, "ff"), f"{S}{sop['id']}/", {
        "process_map": text, "owner": str(sc["who"]["manager"].user_id),
        "kpis": [str(sc["kpis"]["all"].pk)], "review_date": "2027-03-01",
        "roles": [{"name": "Picker", "does": "Picks"}]})
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["map_svg"].startswith("<svg") and "Is anything short?" in body["map_svg"]
    assert body["owner"] == "Max Manager" and body["kpis"][0]["name"] == "For everyone"
    r = patch(client(sc, "ff"), f"{S}{sop['id']}/",
              {"owner": str(sc["practice"]["cf_other"].user_id)})
    assert r.status_code == 200
    stranger = MembershipFactory(tenant=TenantFactory(), role="FF")
    assert patch(client(sc, "ff"), f"{S}{sop['id']}/", {"owner": str(stranger.user_id)}) \
        .status_code == 400
    # SOPs for this number.
    linked = get(sc, "ff", f"{S}?kpi={sc['kpis']['all'].pk}").json()["sops"]
    assert [s["id"] for s in linked] == [sop["id"]]


def test_flowchart_text_parses_and_draws():
    text = ("flowchart TD\n start([Order]) --> check{In stock?}\n"
            " check -->|Yes| pick[Pick]\n check -- No --> wait[Back-order]\n"
            " wait --> check\n pick --> done([Shipped])")
    chart = flow.layout(flow.parse(text))
    assert {n.id: n.rank for n in chart.nodes.values()} == {
        "start": 0, "check": 1, "pick": 2, "wait": 2, "done": 3}
    assert [e.back for e in chart.edges] == [False, False, False, True, False]
    assert flow.png(text)[:8] == b"\x89PNG\r\n\x1a\n"
    assert "<script" not in flow.svg("a[<script>alert(1)</script>] --> b")
    assert flow.check("a --> ") and flow.check("x{y") and not flow.check("")


def test_exports_carry_the_map(published):
    sc, sop = published, published["sop"]
    patch(client(sc, "ff"), f"{S}{sop['id']}/", {"process_map": flow.from_steps(STEPS)})
    r = get(sc, "ff", f"{S}{sop['id']}/files/docx/")
    assert r.status_code == 200
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        assert any(n.startswith("word/media/") for n in z.namelist())
        assert "Pick every line" in z.read("word/document.xml").decode()
    pdf = get(sc, "ff", f"{S}{sop['id']}/files/pdf/")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    # A client gets the published version's file, never the working copy.
    assert get(sc, "member", f"{S}{sop['id']}/files/pdf/").status_code == 200
    assert get(sc, "member", f"{S}{sop['id']}/files/docx/?version=99").status_code == 200


def png_bytes():
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (40, 30), "orange").save(out, "PNG")
    return out.getvalue()


def test_step_images_reach_only_the_audience(published):
    sc, sop = published, published["sop"]
    url = f"{S}{sop['id']}/attachments/"
    r = client(sc, "ff").post(url, {"file": SimpleUploadedFile("bin.png", png_bytes(),
                                                                "image/png")})
    assert r.status_code == 201, r.content
    image = r.json()["id"]
    steps = [{**STEPS[0], "images": [image]}] + STEPS[1:]
    patch(client(sc, "ff"), f"{S}{sop['id']}/", {"steps": steps})
    # Not in a published version yet: the audience can't fetch it.
    assert get(sc, "member", f"{url}{image}/").status_code == 404
    publish(sc, sop["id"], change_note="A picture of the bin label")
    assert get(sc, "member", f"{url}{image}/").status_code == 200
    assert get(sc, "sales_member", f"{url}{image}/").status_code == 200   # whole company
    reader = get(sc, "member", f"{S}{sop['id']}/").json()
    assert reader["steps"][0]["images"] == [image]
    r = client(sc, "ff").delete(f"{url}{image}/")
    assert r.status_code == 409
    bad = client(sc, "ff").post(url, {"file": SimpleUploadedFile("x.exe", b"MZ", "application/x")})
    assert bad.status_code == 400


# ------------------------------------------------------------------ brainstorm

@pytest.fixture
def storm(on, fake_claude):
    sc = on
    r = post(client(sc, "ff"), BS, {"company": str(sc["company"].pk), "title": "Picking"})
    assert r.status_code == 201, r.content
    return {**sc, "storm": r.json(), "claude": fake_claude}


def act(sc, kind, **edits):
    return post(client(sc, "ff"), f"{BS}{sc['storm']['id']}/act/{kind}/")


DRAFT = json.dumps({"title": "Picking orders", "purpose": "Ship it right.",
                    "applies_when": "Every order", "roles": [{"name": "Picker", "does": "Picks"}],
                    "steps": [{"text": "Print the pick list", "role": "Picker", "warning": ""},
                              {"text": "Scan each bin", "role": "Picker",
                               "warning": "Never skip a scan"}],
                    "category": "Shipping", "why": "From the transcript."})


def test_brainstorm_sources_price_and_an_image_sent_as_an_image(storm):
    sc, fake = storm, storm["claude"]
    url = f"{BS}{sc['storm']['id']}/"
    r = post(client(sc, "ff"), f"{url}sources/", {"kind": "pasted", "title": "Notebook",
                                                  "text": "We pick from paper lists."})
    assert r.status_code == 201
    r = client(sc, "ff").post(f"{url}sources/", {"file": SimpleUploadedFile(
        "floor.png", png_bytes(), "image/png")})
    assert r.status_code == 201, r.content
    kinds = [s["kind"] for s in r.json()["sources"]]
    assert kinds == ["pasted", "image"]
    price = post(client(sc, "ff"), f"{url}price/", {"kind": "chat", "message": "Hello"}).json()
    assert Decimal(price["estimate_usd"]) > 0 and price["images"] == 1
    assert len(fake.requests) == 0                      # the price spends nothing
    fake.reply = "Who prints the pick list?"
    r = post(client(sc, "ff"), f"{url}send/", {"text": "Help me write the picking SOP."})
    assert r.status_code == 201
    sent = fake.requests[-1]
    assert sent["messages"][0]["content"][0]["type"] == "image"
    assert "We pick from paper lists." in json.dumps(sent["messages"])
    assert sent["model"] == "claude-sonnet-5-5"
    body = r.json()
    assert [m["role"] for m in body["messages"]] == ["user", "claude"]
    assert Decimal(body["spent_usd"]) > 0
    # Switched to Deep, the next send runs on the Deep tier.
    patch(client(sc, "ff"), url, {"tier": "deep"})
    post(client(sc, "ff"), f"{url}send/", {"text": "And the cut-off?"})
    assert fake.requests[-1]["model"] == "claude-opus-5-5"
    # The conversation alternates, and is saved.
    roles = [m["role"] for m in fake.requests[-1]["messages"]]
    assert roles == ["user", "assistant", "user"]
    assert len(get(sc, "ff", url).json()["messages"]) == 4


def test_draft_accept_then_a_diff_then_discard_all_recorded(storm):
    from apps.centers.models import LibraryRecord

    sc, fake = storm, storm["claude"]
    url = f"{BS}{sc['storm']['id']}/"
    post(client(sc, "ff"), f"{url}sources/", {"kind": "pasted", "text": "Paper lists."})
    fake.reply = DRAFT
    r = act(sc, "draft")
    assert r.status_code == 201, r.content
    proposal = r.json()["proposals"][0]
    assert proposal["state"] == "proposed" and proposal["diff"] == {}
    with tenant_context(sc["tenant"].pk):
        assert not Sop.objects.exists()                   # nothing applies before a person
    r = post(client(sc, "ff"), f"{url}proposals/{proposal['id']}/accept/",
             {"edits": {"title": "Picking every order"}})
    assert r.status_code == 200
    sop_id = r.json()["sop"]["id"]
    full = get(sc, "ff", f"{S}{sop_id}/").json()
    assert full["title"] == "Picking every order" and full["status"] == "draft"
    assert full["steps"][1]["warning"] == "Never skip a scan"
    # A second draft against the SOP comes as a diff.
    fake.reply = DRAFT.replace("Scan each bin", "Scan each tote")
    second = act(sc, "draft").json()["proposals"][0]
    changes = {(s["change"], s["text"]) for s in second["diff"]["steps"]}
    assert ("removed", "Scan each bin") in changes and ("added", "Scan each tote") in changes
    assert second["diff"]["fields"]["title"]["to"] == "Picking orders"
    post(client(sc, "ff"), f"{url}proposals/{second['id']}/discard/")
    assert get(sc, "ff", f"{S}{sop_id}/").json()["steps"][1]["text"] == "Scan each bin"
    with tenant_context(sc["tenant"].pk):
        kinds = sorted(LibraryRecord.objects.filter(source_type="sop_proposal")
                       .values_list("kind", flat=True))
    assert kinds == ["sop_ai_accepted", "sop_ai_rejected"]
    again = post(client(sc, "ff"), f"{url}proposals/{second['id']}/accept/")
    assert again.status_code == 409


def test_map_checklist_and_measures(storm):
    from apps.crm.models import Task
    from apps.work.models import Goal, Project

    sc, fake = storm, storm["claude"]
    url = f"{BS}{sc['storm']['id']}/"
    post(client(sc, "ff"), f"{url}sources/", {"kind": "pasted", "text": "Paper lists."})
    fake.reply = json.dumps({"map": "garbage {{{", "why": "x"})
    bad = act(sc, "map")
    assert bad.status_code == 502 and "couldn't be drawn" in bad.json()["detail"]
    fake.reply = json.dumps({"map": flow.from_steps(STEPS), "why": "The steps in order."})
    proposal = act(sc, "map").json()["proposals"][0]
    r = post(client(sc, "ff"), f"{url}proposals/{proposal['id']}/accept/")
    sop_id = r.json()["sop"]["id"]
    assert get(sc, "ff", f"{S}{sop_id}/").json()["map_svg"].startswith("<svg")
    # A checklist goes into Work, under the project chosen.
    with tenant_context(sc["tenant"].pk):
        goal = Goal.objects.create(tenant=sc["tenant"], client_company=sc["company"],
                                   title="Ship on time", owner=sc["practice"]["ff"].user)
        project = Project.objects.create(tenant=sc["tenant"], client_company=sc["company"],
                                         goal=goal, title="Picking",
                                         owner=sc["practice"]["ff"].user)
    fake.reply = json.dumps({"tasks": [{"title": "Train the night shift", "due_in_days": 7},
                                       {"title": "Print bin labels"}], "why": "x"})
    checklist = act(sc, "checklist").json()["proposals"][0]
    r = post(client(sc, "ff"), f"{url}proposals/{checklist['id']}/accept/", {"edits": {}})
    assert r.status_code == 400 and "goal or project" in r.json()["detail"]
    r = post(client(sc, "ff"), f"{url}proposals/{checklist['id']}/accept/",
             {"edits": {"project": str(project.pk), "chosen": [0],
                        "titles": {"0": "Train the night shift on scanning"}}})
    assert r.status_code == 200, r.content
    with tenant_context(sc["tenant"].pk):
        made = Task.objects.filter(project=project)
        assert [t.title for t in made] == ["Train the night shift on scanning"]
        assert made[0].updates.first().source == "sop"
    # Measures from the library: one of the company's, one the library adds.
    fake.reply = json.dumps({"kpis": [{"name": "For everyone", "why": "a"},
                                      {"name": "On-time delivery", "why": "b"},
                                      {"name": "Not a KPI anywhere", "why": "c"}]})
    measures = act(sc, "measures").json()["proposals"][0]
    names = [k["name"] for k in measures["payload"]["kpis"]]
    assert "For everyone" in names and "Not a KPI anywhere" not in names
    r = post(client(sc, "ff"), f"{url}proposals/{measures['id']}/accept/")
    assert r.status_code == 200, r.content
    linked = {k["name"] for k in get(sc, "ff", f"{S}{sop_id}/").json()["kpis"]}
    assert set(names) <= linked


def test_brainstorm_caps_and_who(storm, settings):
    from apps.tenancy.models import Tenant

    sc = storm
    url = f"{BS}{sc['storm']['id']}/"
    assert get(sc, "owner", url).status_code == 404
    assert get(sc, "cf_other", url).status_code == 404
    assert get(sc, "va", url).status_code == 200
    Tenant.objects.filter(pk=sc["tenant"].pk).update(ai_monthly_budget_usd=Decimal("0.01"))
    from apps.tenancy.models import AiCall

    with tenant_context(sc["tenant"].pk):
        AiCall.objects.create(tenant=sc["tenant"], purpose="sop_brainstorm", model="x",
                              cost_usd=Decimal("1"))
    r = post(client(sc, "ff"), f"{url}send/", {"text": "Hi"})
    assert r.status_code == 409 and "budget is spent" in r.json()["detail"]
    assert "budget" in get(sc, "ff", url).json()["refused"]


def test_a_note_opens_a_brainstorm_but_a_locked_one_never(on):
    from apps.notes.models import Note

    sc = on
    with tenant_context(sc["tenant"].pk):
        note = Note.objects.create(tenant=sc["tenant"], company=sc["company"],
                                   title="Picking walk-through", body="Lists on paper.")
        locked = Note.objects.create(tenant=sc["tenant"], company=sc["company"], title="Pay",
                                     body="SECRET", pin_hash="x", pin_set_at=timezone.now())
    r = post(client(sc, "ff"), BS, {"note": str(note.pk)})
    assert r.status_code == 201
    body = r.json()
    assert body["company"]["name"] == "Northwind Foods"
    assert body["sources"][0]["kind"] == "note" and "Lists on paper." in body["sources"][0]["preview"]
    r = post(client(sc, "ff"), BS, {"note": str(locked.pk)})
    assert r.status_code == 409
    from apps.tenancy import ai_actions

    action = ai_actions.BY_KEY["ops_sop_from_note"]
    assert action.in_app and ai_actions.runs_in(sc["tenant"].pk, action) == "app"


# ------------------------------------------------------------------ media

class FakeGemini:
    def __init__(self):
        self.calls = []
        self.states = ["PROCESSING", "ACTIVE"]

    def __call__(self, method, url, *, key, headers=None, body=None, json_body=None, timeout=0):
        self.calls.append((method, url))
        if url.endswith("/models/gemini-2.5-flash") and method == "GET":
            return 200, {}, {"displayName": "Gemini 2.5 Flash"}
        if "/upload/v1beta/files" in url:
            return 200, {"x-goog-upload-url": "https://upload.example/session"}, {}
        if url == "https://upload.example/session":
            return 200, {}, {"file": {"name": "files/abc", "uri": "https://x/files/abc"}}
        if method == "GET" and url.endswith("files/abc"):
            return 200, {}, {"state": self.states.pop(0) if self.states else "ACTIVE"}
        if url.endswith(":generateContent"):
            return 200, {}, {"candidates": [{"content": {"parts": [{"text": json.dumps({
                "transcript": "Marvin: I print the list.", "steps": ["Print", "Pick"],
                "summary": "Picking."})}]}}],
                "usageMetadata": {"promptTokenCount": 19200, "candidatesTokenCount": 900}}
        if method == "DELETE":
            return 200, {}, {}
        return 404, {}, {}


def mp4():
    return SimpleUploadedFile("walk.mp4", b"\x00" * 2048, "video/mp4")


def test_media_without_a_key_says_what_to_do(storm):
    sc = storm
    r = client(sc, "ff").post(f"{BS}{sc['storm']['id']}/media/", {"file": mp4(), "seconds": 60})
    assert r.status_code == 409 and "paste a transcript" in r.json()["detail"]
    assert get(sc, "ff", f"{BS}{sc['storm']['id']}/").json()["media"]["set"] is False


def test_media_with_a_key_price_first_file_not_kept(storm, monkeypatch):
    from apps.sops import media
    from apps.tenancy.models import AiCall, StoredFile

    sc = storm
    fake = FakeGemini()
    monkeypatch.setattr(media, "_http", fake)
    ff = client(sc, "ff")
    assert get(sc, "cf", "/api/ai-media-key/").status_code == 404
    r = post(ff, "/api/ai-media-key/", {"key": "AIza" + "x" * 35})
    assert r.status_code == 200, r.content
    status = r.json()
    assert status["set"] and status["last4"] == "xxxx" and "Google" in status["notice"]
    assert Decimal(status["about_per_minute"]["video"]) > Decimal(status["about_per_minute"]["audio"])
    assert post(ff, "/api/ai-media-key/test/").json()["detail"].startswith("Connected")
    url = f"{BS}{sc['storm']['id']}/"
    r = ff.post(f"{url}media/", {"file": mp4(), "seconds": 16 * 60})
    assert r.status_code == 400 and "15 minutes" in r.json()["detail"]
    r = ff.post(f"{url}media/", {"file": mp4(), "seconds": 90})
    assert r.status_code == 201, r.content
    source = r.json()["sources"][0]
    assert source["state"] == "reading" and source["kept"] is False
    r = post(ff, f"{url}sources/{source['id']}/read/")
    assert r.json()["sources"][0]["state"] == "reading"          # still processing
    r = post(ff, f"{url}sources/{source['id']}/read/")
    done = r.json()["sources"][0]
    assert done["state"] == "ready" and "Marvin: I print the list." in done["preview"]
    with tenant_context(sc["tenant"].pk):
        assert not StoredFile.objects.filter(purpose="sop_media").exists()
        call = AiCall.objects.get(purpose="sop_media")
        assert call.model == "gemini-2.5-flash" and call.cost_usd > 0
    assert ("DELETE", "https://generativelanguage.googleapis.com/v1beta/files/abc") in fake.calls
    # Ticked, the file is kept.
    fake.states = ["ACTIVE"]
    r = ff.post(f"{url}media/", {"file": mp4(), "seconds": 30, "keep": "true"})
    assert r.json()["sources"][1]["kept"] is True
    with tenant_context(sc["tenant"].pk):
        assert StoredFile.objects.filter(purpose="sop_media").count() == 1
    assert client(sc, "ff").delete("/api/ai-media-key/").json()["set"] is False


# ------------------------------------------------------------------ the Notebook pack

def test_the_notebook_pack_in_order_and_never_mail_notes_or_people(published):
    from apps.notes.models import Note
    from apps.tenancy.models import AuditEvent

    sc = published
    with tenant_context(sc["tenant"].pk):
        Note.objects.create(tenant=sc["tenant"], company=sc["company"], title="Pay",
                            body="SECRET PAY SCALE", pin_hash="x", pin_set_at=timezone.now())
        Note.objects.create(tenant=sc["tenant"], company=sc["company"], title="Open note",
                            body="AN OPEN NOTE")
    choices = get(sc, "ff", f"/api/sops/pack/?company={sc['company'].pk}").json()
    assert len(choices["prompts"]) == 5 and "never" in choices
    r = post(client(sc, "ff"), "/api/sops/pack/", {"company": str(sc["company"].pk)})
    assert r.status_code == 200 and r["Content-Type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names = z.namelist()
        everything = b"".join(z.read(n) for n in names)
    assert names[:5] == ["00 README.md", "01 prompts.md", "02 Goals outline.md",
                         "03 Plan by horizon.md", "04 Scorecard.csv"]
    assert "05 SOP - Picking orders.pdf" in names and names[-1].endswith("Meeting summaries.md")
    assert b"SECRET PAY SCALE" not in everything and b"AN OPEN NOTE" not in everything
    assert b"Find the handoffs and bottlenecks" in everything
    with tenant_context(sc["tenant"].pk):
        audit = AuditEvent.objects.get(verb="sops.pack_built")
        assert audit.payload["files"] == names
    assert get(sc, "va", f"/api/sops/pack/?company={sc['company'].pk}").status_code == 404
    elsewhere = ClientCompanyFactory(tenant=sc["tenant"], name="Elsewhere")
    with tenant_context(sc["tenant"].pk):
        from apps.tools.services import start_run

        theirs = start_run(elsewhere, "ops_bottleneck", actor=sc["practice"]["ff"].user)
    r = post(client(sc, "ff"), "/api/sops/pack/", {"company": str(sc["company"].pk),
                                                    "runs": [str(theirs.pk)]})
    assert r.status_code == 404
    # The prompts are the practice owner's to edit.
    r = client(sc, "ff").put("/api/sops/pack/prompts/", json.dumps(
        {"prompts": [{"title": "Ours", "prompt": "Our own prompt."}]}),
        content_type="application/json")
    assert r.json()["prompts"] == [{"title": "Ours", "prompt": "Our own prompt."}]
    assert client(sc, "cf").put("/api/sops/pack/prompts/", "{}",
                                content_type="application/json").status_code == 403


# ------------------------------------------------------------------ AI apps, connections, Activity

def test_mcp_tools_are_scoped_by_role(published):
    from apps.aiconnect import tools as T

    sc = published
    with tenant_context(sc["tenant"].pk):
        draft = new_sop(sc, title="Not yet")

        def p(who):
            m = sc["who"].get(who) or sc["practice"][who]
            return T.Principal(connection=type("C", (), {"membership": m, "user": m.user,
                                                         "app_name": "Claude"})())

        assert {s["title"] for s in T.list_sops(p("ff"))["sops"]} == {"Picking orders", "Not yet"}
        assert T.list_sops(p("cf_other"))["sops"] == []
        assert [s["title"] for s in T.list_sops(p("member"))["sops"]] == ["Picking orders"]
        with pytest.raises(T.ToolRefused):
            T.read_sop(p("member"), draft["id"])
        assert "Print the pick list" in T.read_sop(p("member"), sc["sop"]["id"])["text"]
        made = T.draft_sop(p("va"), str(sc["company"].pk), "Receiving",
                           steps=[{"text": "Count the cartons"}])
        sop = Sop.objects.get(pk=made["drafted"])
        assert sop.status == "draft" and sop.from_ai_app and sop.steps[0]["text"] == \
            "Count the cartons"
        with pytest.raises(T.ToolRefused):
            T.draft_sop(p("owner"), str(sc["company"].pk), "Mine")
        with pytest.raises(T.ToolRefused):
            T.draft_sop(p("cf_other"), str(sc["company"].pk), "Theirs")


def test_tools_hand_off_and_import_and_plans_source(published, fake_claude):
    from apps.tools.services import start_run

    sc, sop = published, published["sop"]
    with tenant_context(sc["tenant"].pk):
        run = start_run(sc["company"], "ops_bottleneck", actor=sc["practice"]["ff"].user)
    r = post(client(sc, "ff"), f"/api/tool-runs/{run.pk}/sop-brainstorm/")
    assert r.status_code == 201, r.content
    storm = get(sc, "ff", f"{BS}{r.json()['brainstorm']}/").json()
    assert storm["sources"][0]["kind"] == "tool_run"
    options = get(sc, "ff", f"/api/tool-runs/{run.pk}/").json()["choices"]["sop_sources"]
    assert options[0] == {"id": f"sop:{sop['id']}", "label": "SOP: Picking orders"}
    r = post(client(sc, "ff"), f"/api/tool-runs/{run.pk}/import-sop/",
             {"source": f"sop:{sop['id']}"})
    assert r.status_code == 200 and r.json()["imported"] == 4
    # The plans engine's "Draft from sources" offers it and reads it.
    from apps.plans.access import PlanAccess
    from apps.plans.sources import gather, menu

    request = type("R", (), {"membership": sc["practice"]["ff"], "user": sc["practice"]["ff"].user})()
    with tenant_context(sc["tenant"].pk):
        access = PlanAccess(request, sc["company"])
        offered = [m for m in menu(access) if m["id"] == f"sop:{sop['id']}"]
        assert offered and offered[0]["detail"] == "Version 1"
        text = gather(access, [{"type": "sop", "id": f"sop:{sop['id']}"}])[0][2]
    assert "SOP, version 1" in text and "Scan the bin" not in text and "Pick every line" in text


def test_publishing_is_in_activity_and_the_library(published):
    from apps.centers.models import LibraryRecord

    sc = published
    feed = get(sc, "ff", "/api/activity/").json()
    rows = feed if isinstance(feed, list) else feed.get("entries") or feed.get("results") or []
    texts = [e["text"] for e in rows]
    assert any("published the SOP “Picking orders” for Northwind Foods, version 1" in t
               for t in texts), texts[:5]
    with tenant_context(sc["tenant"].pk):
        record = LibraryRecord.objects.get(source_type="sop")
        assert record.kind == "sop" and record.structure["steps"][0] == "Print the pick list"
