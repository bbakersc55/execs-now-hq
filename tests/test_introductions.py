"""R3 (outbound introductions) and R3b's specialties (owner, 2026-10-24).

An introduction is an outbound referral row from a partner's page to another
contact, with a date, a note and who made it; it drafts the library's
Introduction template to each of the two, for approval; it shows on both
pages with the outcome the practice sets, and a count on the partner's page.
Specialties: a discipline and free-text specialties, suggested from those
used, filterable and found by the search box. Isolation and roles.
"""

from __future__ import annotations

import json

import pytest

from apps.crm.models import OutboxMessage, Referral
from apps.crm.services import introductions, referrals
from apps.tenancy.models import AuditEvent

from . import registry_config  # noqa: F401
from .factories import (
    CompanyFactory, ContactEmailFactory, ContactFactory, ContactTypeLinkFactory,
    MembershipFactory, TenantFactory,
)

pytestmark = pytest.mark.django_db


def post(client, url, data):
    return client.post(url, json.dumps(data), content_type="application/json")


def patch(client, url, data):
    return client.patch(url, json.dumps(data), content_type="application/json")


def person(t, first, last, *, owner=None, partner=False, types=None, company=None, **extra):
    c = ContactFactory(tenant=t, first_name=first, last_name=last, owner=owner,
                       company=company, **extra)
    ContactEmailFactory(tenant=t, contact=c, is_primary=True,
                        address=f"{first.lower()}@{last.lower()}.invalid")
    if partner:
        ContactTypeLinkFactory(tenant=t, contact=c, contact_type=types["referral_partner"])
    return c


@pytest.fixture
def cast(seeded_tenant, ff, types):
    t = seeded_tenant
    acme = CompanyFactory(tenant=t, name="Acme")
    maya = person(t, "Maya", "Chen", owner=ff.user, partner=True, types=types,
                  discipline="cmo", specialties=["Go to market", "Social media ads"],
                  pronouns="she", intro_blurb="Maya has launched more products than anyone I know.")
    ravi = person(t, "Ravi", "Patel", owner=ff.user, partner=True, types=types,
                  discipline="cfo", specialties=["Cash flow", "Fundraising"])
    dana = person(t, "Dana", "Reyes", owner=ff.user, company=acme)
    return {"t": t, "maya": maya, "ravi": ravi, "dana": dana}


def introduce(api, who, partner, to, note=""):
    return post(api.as_(who), "/api/introductions/", {"partner": str(partner.pk),
                                                       "to": str(to.pk), "note": note})


# ---------------------------------------------------------------- introductions

def test_an_introduction_is_recorded_and_drafted_to_both_for_approval(cast, ff, api):
    response = introduce(api, ff, cast["maya"], cast["dana"],
                         note="Dana is launching a new product line in the spring.")
    assert response.status_code == 201, response.content
    assert response.json()["drafts"] == 2
    row = Referral.all_objects.get(direction="outbound")
    assert (row.referrer_id, row.prospect_id, row.created_by_id) == (
        cast["maya"].pk, cast["dana"].pk, ff.user_id)
    assert row.pipeline.kind == "referral" and row.note.startswith("Dana is launching")
    drafts = {m.to_contact_id: m for m in OutboxMessage.all_objects.filter(
        producer="introduction")}
    assert set(drafts) == {cast["maya"].pk, cast["dana"].pk}
    assert all(m.state == OutboxMessage.State.PENDING_APPROVAL for m in drafts.values())
    to_maya, to_dana = drafts[cast["maya"].pk], drafts[cast["dana"].pk]
    # Dana's pronouns aren't set: they. Maya's are she, with her blurb.
    assert to_maya.subject == "Someone I'd like you to meet: Dana Reyes"
    body = to_maya.body_text
    assert "Hi Maya," in body and "really enjoy knowing them." in body
    assert "You'll find them at Acme." in body
    assert "Dana is launching a new product line" in body
    assert "so they'll be glad to hear from you" in body
    # Dana has no specialties and no blurb: those lines are left out.
    assert "work focuses on" not in body
    assert to_dana.subject == "Someone I'd like you to meet: Maya Chen"
    body = to_dana.body_text
    assert "really enjoy knowing her." in body
    assert "Maya has launched more products than anyone I know." in body
    assert "Her work focuses on Go to market, Social media ads." in body   # capitalised
    assert "so she'll be glad to hear from you" in body
    assert "You'll find" not in body                                      # Maya has no company
    # Activity, on both contacts.
    assert AuditEvent.all_objects.filter(verb="introduction.made").count() == 2


def test_partner_to_partner_and_the_partners_page_counts(cast, ff, api):
    introduce(api, ff, cast["maya"], cast["ravi"])
    first = introduce(api, ff, cast["maya"], cast["dana"]).json()
    introduce(api, ff, cast["ravi"], cast["dana"])
    client = api.as_(ff)
    assert patch(client, f"/api/introductions/{first['id']}/",
                 {"outcome": "client"}).json()["outcome_label"] == "Became a client"
    page = client.get(f"/api/introductions/?contact={cast['maya'].pk}").json()
    assert page["counts"] == {"made": 2, "became_client": 1}
    assert page["counts_text"] == "2 introductions made · 1 became a client"
    # Both sides' pages list it; the other contact's lists both it is on.
    ravi = client.get(f"/api/introductions/?contact={cast['ravi'].pk}").json()
    assert len(ravi["introductions"]) == 2 and ravi["counts"]["made"] == 1
    dana = client.get(f"/api/introductions/?contact={cast['dana'].pk}").json()
    assert {i["partner"]["name"] for i in dana["introductions"]} == {"Maya Chen", "Ravi Patel"}
    # Outcomes are only the four, or cleared.
    assert patch(client, f"/api/introductions/{first['id']}/",
                 {"outcome": "won"}).status_code == 400
    assert patch(client, f"/api/introductions/{first['id']}/", {"outcome": ""}).status_code == 200
    assert AuditEvent.all_objects.filter(verb="introduction.outcome").count() == 4


def test_introductions_never_mix_with_inbound_referrals(cast, ff, api):
    from apps.tenancy.context import tenant_context

    with tenant_context(cast["t"].pk):
        referrals.record(cast["dana"], cast["ravi"], actor=ff.user)
    introduce(api, ff, cast["maya"], cast["dana"])
    client = api.as_(ff)
    inbound = client.get(f"/api/referrals/?prospect={cast['dana'].pk}").json()
    assert [r["referrer"]["name"] if isinstance(r["referrer"], dict) else r["referrer"]
            for r in inbound].__len__() == 1
    contact = client.get(f"/api/contacts/{cast['dana'].pk}/").json()
    assert contact["referred_by"]["referrer_name"] == "Ravi Patel"
    assert client.get(f"/api/referrals/?referrer={cast['maya'].pk}").json() == []


def test_what_an_introduction_refuses(cast, ff, api, types):
    assert "isn't a referral partner" in str(
        introduce(api, ff, cast["dana"], cast["maya"]).json())
    assert "other than" in str(introduce(api, ff, cast["maya"], cast["maya"]).json())
    from apps.crm.models import ContactEmail

    silent = person(cast["t"], "No", "Email", owner=ff.user)
    ContactEmail.all_objects.filter(contact=silent).delete()
    assert "no email address" in str(introduce(api, ff, cast["maya"], silent).json())
    assert not Referral.all_objects.filter(direction="outbound").exists()


def test_a_merge_carries_introductions_to_the_survivor(cast, ff, api):
    from apps.crm.services import merge

    introduce(api, ff, cast["maya"], cast["dana"])
    introduce(api, ff, cast["ravi"], cast["dana"])
    twin = person(cast["t"], "Dana", "Reyes2", owner=ff.user)
    introduce(api, ff, cast["maya"], twin)
    from apps.tenancy.context import tenant_context

    with tenant_context(cast["t"].pk):
        merge.merge_contacts(cast["dana"], twin, actor=ff.user)
    assert Referral.all_objects.filter(direction="outbound", prospect=cast["dana"]).count() == 3


# ---------------------------------------------------------------- specialties

def test_specialties_are_cleaned_suggested_and_on_activity(cast, ff, api):
    client = api.as_(ff)
    url = f"/api/contacts/{cast['ravi'].pk}/"
    saved = patch(client, url, {"discipline": "cfo",
                                "specialties": ["  Cash   flow ", "cash flow", "SaaS metrics", ""]})
    assert saved.status_code == 200, saved.content
    assert saved.json()["specialties"] == ["Cash flow", "SaaS metrics"]
    assert saved.json()["discipline_label"] == "Fractional CFO"
    assert patch(client, url, {"specialties": ["x" * 61]}).status_code == 400
    assert patch(client, url, {"discipline": "ceo"}).status_code == 400
    used = client.get("/api/contacts/specialties/").json()
    assert {"specialty": "Cash flow", "contacts": 1} in used
    assert [u["specialty"] for u in used][:1] in (["Cash flow"], ["Go to market"],
                                                 ["Social media ads"], ["SaaS metrics"])
    assert AuditEvent.all_objects.filter(verb="contact.specialties_changed",
                                         target_id=cast["ravi"].pk).exists()


def test_found_by_discipline_and_specialty_filters_and_the_search_box(cast, ff, api):
    client = api.as_(ff)
    names = lambda rows: sorted(r["first_name"] for r in rows)  # noqa: E731
    assert names(client.get("/api/contacts/?discipline=cmo").json()) == ["Maya"]
    assert names(client.get("/api/contacts/?specialty=social").json()) == ["Maya"]
    assert names(client.get("/api/contacts/?specialty=CFO").json()) == ["Ravi"]
    assert names(client.get("/api/contacts/?specialty=nothing").json()) == []
    found = client.get("/api/contacts/search/?q=fundraising").json()
    assert [c["first_name"] for c in found["contacts"]] == ["Ravi"]
    found = client.get("/api/contacts/search/?q=fractional cmo").json()
    assert "Maya" in [c["first_name"] for c in found["contacts"]]


# ---------------------------------------------------------------- roles and isolation

def test_roles(cast, seeded_tenant, ff, fcc, api):
    va = MembershipFactory(tenant=seeded_tenant, role="VA")
    assert introduce(api, va, cast["maya"], cast["dana"]).status_code == 201
    # A client never reaches introductions or the specialties list.
    assert api.as_(fcc).get(f"/api/introductions/?contact={cast['maya'].pk}").status_code == 403
    assert introduce(api, fcc, cast["maya"], cast["dana"]).status_code == 403
    assert api.as_(fcc).get("/api/contacts/specialties/").status_code == 403
    # An associate makes and sees introductions between contacts they can see only.
    cf = MembershipFactory(tenant=seeded_tenant, role="CF")
    response = introduce(api, cf, cast["maya"], cast["dana"])
    assert response.status_code == 400 and "not available" in str(response.json())
    row = Referral.all_objects.filter(direction="outbound").first()
    assert patch(api.as_(cf), f"/api/introductions/{row.pk}/",
                 {"outcome": "met"}).status_code == 404


def test_another_practice_never_sees_or_reaches_them(cast, ff, api):
    from apps.crm.seed import seed_tenant

    made = introduce(api, ff, cast["maya"], cast["dana"]).json()
    other = TenantFactory()
    seed_tenant(other)
    b = api.as_(MembershipFactory(tenant=other, role="FF"))
    assert b.get(f"/api/introductions/?contact={cast['maya'].pk}").status_code == 400
    assert patch(b, f"/api/introductions/{made['id']}/", {"outcome": "met"}).status_code == 404
    assert introduce(api, MembershipFactory(tenant=other, role="FF"),
                     cast["maya"], cast["dana"]).status_code == 400
    assert b.get("/api/contacts/specialties/").json() == []
    assert b.get("/api/contacts/?specialty=social").json() == []
    assert b.get("/api/contacts/search/?q=fundraising").json()["contacts"] == []


def test_pronouns_and_how_id_introduce_them_are_set_on_the_contact_page(cast, ff, api):
    """Bryan, 2026-10-24: every contact has pronouns (he, she, or unset, which
    reads as they) and "How I'd introduce them", on Activity when changed."""
    url = f"/api/contacts/{cast['dana'].pk}/"
    saved = patch(api.as_(ff), url, {"pronouns": "he", "intro_blurb": "  Dana builds teams.  "})
    assert saved.status_code == 200
    assert (saved.json()["pronouns"], saved.json()["intro_blurb"]) == ("he", "Dana builds teams.")
    assert AuditEvent.all_objects.filter(verb="contact.introduction_words_changed").count() == 1
    assert patch(api.as_(ff), url, {"pronouns": "it"}).status_code == 400
    assert patch(api.as_(ff), url, {"intro_blurb": "x" * 601}).status_code == 400
    # Unset again reads as they.
    assert patch(api.as_(ff), url, {"pronouns": ""}).json()["pronouns"] == ""


def test_the_pronoun_and_blurb_fields_work_for_both_people(cast):
    """{HeShe} {HimHer} {HisHer} {Blurb} {Specialties} for the person written
    to, the Other* ones for who they're meeting; a pronoun that starts a
    sentence gets its capital; a line whose fact is missing goes."""
    from apps.crm.services import templates

    maya, dana = cast["maya"], cast["dana"]
    text = ("{HeShe} said yes. Ask {HimHer} about {HisHer} plans.\n{Blurb}\n"
            "Specialties: {Specialties}\n{OtherHeShe}'ll call; {OtherHisHer} card: {OtherBlurb}")
    values = introductions._values(maya, dana, Referral(note=""), None)
    assert templates.render(text, values) == (
        "She said yes. Ask her about her plans.\n"
        "Maya has launched more products than anyone I know.\n"
        "Specialties: Go to market, Social media ads")         # Dana has no blurb: line gone
    dana.pronouns, dana.intro_blurb = "he", "Dana builds teams."
    values = introductions._values(maya, dana, Referral(note=""), None)
    assert templates.render("{OtherHeShe}'ll call; {OtherHisHer} card: {OtherBlurb}", values) == \
        "He'll call; his card: Dana builds teams."
    # Unset reads as they; outside an introduction the Other* pronouns are they.
    plain = templates.values_for(dana.__class__(first_name="Sam"), tenant=cast["t"])
    assert (plain["HeShe"], plain["HimHer"], plain["HisHer"]) == ("they", "them", "their")
    assert templates.unknown_fields(text) == []
