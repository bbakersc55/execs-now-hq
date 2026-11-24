"""More than one owner (owner, 2026-11-24): up to four, signing in the order
listed, each on their own link; the first fills in the owner's page, the rest
read and sign the same words. SkyRun signs after the last. Also cancelling with
a reason (and who is told), starting a new agreement from a cancelled one,
Exhibit A from Sleeps, the owner's page and the signature page each on one
page, and what the intake is given."""

from __future__ import annotations

import io
import json
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.agreements import exhibit_a, links, services
from apps.agreements.models import (
    AgreementEvent, AgreementSignature, CoOwner, OwnerAgreement, OwnerEmail,
)
from apps.intake import services as intake_services
from apps.intake import vault
from apps.intake.models import SubmissionEvent, SubmissionSecret
from apps.notify.models import Notice
from apps.tenancy.context import tenant_context
from apps.tenancy.models import AuditEvent

from .test_agreements import (  # noqa: F401
    DETAILS, TERMS, as_, aw, countersign, create, fake, flat, owner_signs, pdf_text,
    record_authority, token_of, world,
)

pytestmark = pytest.mark.django_db

PAT = {"name": "Pat Sample", "email": "alex@samplehomes.net", "title": ""}  # shares Alex's
LEE = {"name": "Lee Sample", "email": "lee@samplehomes.net", "title": "Trustee"}


def co_token(a, position) -> str:
    co = CoOwner.all_objects.get(agreement=a, position=position)
    with tenant_context(a.tenant_id):
        return links.ensure(co)


def co_signs(a, position, **body):
    o = Client(REMOTE_ADDR=f"203.0.113.{20 + position}", HTTP_USER_AGENT="Their phone")
    t = co_token(a, position)
    r = o.post(f"/api/fa/{t}/sign", json.dumps({"method": "typed", "typed": "Their name",
                                                 "agreed": True, **body}),
               content_type="application/json")
    a.refresh_from_db()
    return r


def emails(a, kind):
    return list(OwnerEmail.all_objects.filter(agreement=a, kind=kind).order_by("created_at"))


def test_three_owners_sign_in_order_each_on_their_own_link(aw):
    a = create(aw, co_owners=[PAT, LEE])
    detail = as_(aw["jackie"]).get(f"/api/agreements/{a.pk}").json()
    assert [o["name"] for o in detail["owners"]] == ["Alex Sample", "Pat Sample", "Lee Sample"]
    assert detail["shared_email"] is True                  # Alex and Pat share one address
    assert as_(aw["jackie"]).post(f"/api/agreements/{a.pk}/send").status_code == 200
    assert [(m.position, m.to_address) for m in emails(a, "invite")] == \
        [(1, "alex@samplehomes.net")]
    assert not CoOwner.all_objects.filter(agreement=a).exclude(link_hash="").exists()

    o, _ = owner_signs(a)
    assert a.owner_signed_at and a.all_signed_at is None
    assert a.submission is not None                        # the intake is made at once
    assert "isn't countersigned yet" in intake_services.agreement_waiting(a.submission)
    page = o.get(f"/api/fa/{token_of(a)}").json()
    assert page["state"] == "signed" and page["role"] == "first"
    assert page["waiting_for"] == "Pat Sample"
    r = o.post(f"/api/fa/{token_of(a)}/onboarding", json.dumps({"choice": "later"}),
               content_type="application/json")
    assert r.status_code == 200                            # the first owner may start at once
    # Pat's turn: Pat's own link, to the address Pat shares with Alex.
    assert [(m.position, m.to_address) for m in emails(a, "invite")] == \
        [(1, "alex@samplehomes.net"), (2, "alex@samplehomes.net")]
    assert not emails(a, "owner_copy")                      # copies wait for every owner
    title = Notice.all_objects.filter(source_type="agreement_signed_1").first().title
    assert "Alex Sample signed (1 of 3)" in title
    assert countersign(aw, a, "michael", method="typed", typed="Michael").status_code == 409

    # Lee's link says who signs first, and shows nothing yet; Lee can't sign.
    lee = Client().get(f"/api/fa/{co_token(a, 3)}").json()
    assert lee["state"] == "waiting" and lee["waiting_for"] == "Pat Sample"
    assert lee["blocks"] == [] and lee["details"] == {}
    r = co_signs(a, 3)
    assert r.status_code == 409 and "isn't your turn" in r.json()["detail"]

    # Pat reads the whole agreement with Alex's answers, and fills nothing in.
    t2 = co_token(a, 2)
    pat = Client().get(f"/api/fa/{t2}").json()
    assert pat["state"] == "open" and pat["role"] == "co_owner" and pat["details"] == {}
    owner_page = next(b for b in pat["blocks"] if b["type"] == "owner_section")
    values = {f["key"]: f["value"] for line in owner_page["lines"] for f in line.get("fields", [])}
    assert values["mailing_street"] == "9 Elm St" and values["sleeps"] == "8"
    sigs = next(b for b in pat["blocks"] if b["type"] == "signatures")
    assert [x["name"] for x in sigs["owners"]] == ["Alex Sample", "Pat Sample",
                                                  "Lee Sample, Trustee"]
    r = Client().patch(f"/api/fa/{t2}/details", json.dumps({"details": {"sleeps": "2"}}),
                       content_type="application/json")
    assert r.status_code == 403
    r = Client().post(f"/api/fa/{t2}/onboarding", json.dumps({"choice": "now"}),
                      content_type="application/json")
    assert r.status_code == 403
    assert co_signs(a, 2).status_code == 200
    assert [m.position for m in emails(a, "invite")] == [1, 2, 3]
    assert co_signs(a, 2).status_code == 409                # once only

    assert co_signs(a, 3).status_code == 200
    assert a.all_signed_at is not None
    sigs = list(AgreementSignature.all_objects.filter(agreement=a, role="owner")
                .order_by("position"))
    assert [s.position for s in sigs] == [1, 2, 3]
    assert len({s.text_sha256 for s in sigs}) == 1 and len({s.signed_text for s in sigs}) == 1
    assert [s.printed_name for s in sigs] == ["Alex Sample", "Pat Sample", "Lee Sample"]
    assert "alex@samplehomes.net" in sigs[1].consent_text
    # One copy to each address, greeting everyone who shares it.
    copies = emails(a, "owner_copy")
    assert sorted(m.to_address for m in copies) == ["alex@samplehomes.net",
                                                    "lee@samplehomes.net"]
    line = services.status_line(a)[2]
    assert line["label"] == "Signed by owners (3 of 3)" and line["at"]
    assert services.turn_text(a) == "Waiting for SkyRun's signature"
    assert Notice.all_objects.filter(source_type="agreement_countersign").exists()

    record_authority(aw, [aw["jackie"].user])
    assert countersign(aw, a, "jackie").status_code == 200
    a.refresh_from_db()
    finals = emails(a, "final_copy")
    assert sorted(m.to_address for m in finals) == ["alex@samplehomes.net",
                                                    "lee@samplehomes.net"]
    final = pdf_text(a.final_pdf)
    pages, record = final.split(flat("Signing record"), 1)
    for name in ("NAME: Alex Sample", "NAME: Pat Sample", "NAME: Lee Sample, Trustee"):
        assert flat(name) in pages, name
    assert flat("(ALL owners of Unit must sign)") in pages
    for role in ("Owner 1 of 3", "Owner 2 of 3", "Owner 3 of 3"):
        assert flat(role) in record, role
    assert record.count(flat("the same as the first owner's")) == 2
    assert "intake" not in final.lower()


def test_the_owner_emails_for_a_later_owner(aw):
    from apps.agreements import mail

    a = create(aw, co_owners=[LEE])
    as_(aw["jackie"]).post(f"/api/agreements/{a.pk}/send")
    owner_signs(a)
    msg = mail.owner_message(a, "invite", 2)
    assert msg["paras"][0] == "Hi Lee,"
    assert "Alex Sample signed the rental management agreement" in msg["paras"][1]
    assert "it's your turn now" in msg["paras"][1]
    assert msg["link"] == services.owner_link(a, 2) != services.owner_link(a, 1)
    first = mail.owner_message(a, "invite", 1)
    assert "Lee Sample sign it too, in that order" in first["paras"][2]


def test_every_owner_signs_the_same_words_or_nobody_signs(aw):
    a = create(aw, co_owners=[LEE])
    as_(aw["jackie"]).post(f"/api/agreements/{a.pk}/send")
    owner_signs(a)
    # Something changes the words after the first owner signed.
    a.details = {**a.details, "mailing": {**a.details["mailing"], "street": "10 Elm St"}}
    a.save(update_fields=["details"])
    r = co_signs(a, 2)
    assert r.status_code == 409 and "changed after Alex Sample signed it" in r.json()["detail"]
    assert not AgreementSignature.all_objects.filter(agreement=a, position=2).exists()
    assert Notice.all_objects.filter(title__contains="can't be signed").exists()
    # Put back, Lee signs; then a change before countersigning is caught for both.
    a.details = {**a.details, "mailing": {**a.details["mailing"], "street": "9 Elm St"}}
    a.save(update_fields=["details"])
    assert co_signs(a, 2).status_code == 200
    CoOwner.all_objects.filter(agreement=a, position=2).update(title="Co-trustee")
    r = countersign(aw, a, "michael", method="typed", typed="Michael")
    assert r.status_code == 409 and "don't match what the owners signed" in r.json()["detail"]
    a.refresh_from_db()
    assert a.countersigned_at is None


def test_reminders_go_to_whose_turn_it_is_from_when_it_began(aw, monkeypatch):
    from zoneinfo import ZoneInfo

    a = create(aw, co_owners=[LEE])
    as_(aw["jackie"]).post(f"/api/agreements/{a.pk}/send")
    tz = ZoneInfo(aw["practice"].timezone or "UTC")
    real_now = timezone.now
    start = real_now().astimezone(tz)
    OwnerAgreement.all_objects.filter(pk=a.pk).update(sent_at=real_now() - timedelta(days=9))
    owner_signs(a)                                        # Lee's turn starts now

    def at(days, hour):
        moment = (start + timedelta(days=days)).replace(hour=hour, minute=5)
        monkeypatch.setattr(services, "practice_now", lambda company: moment)
        monkeypatch.setattr(timezone, "now", lambda: moment.astimezone(ZoneInfo("UTC")))

    at(2, 10)
    services.tick()
    assert not emails(a, "reminder")                      # Alex isn't reminded: Alex signed
    at(3, 10)
    services.tick()
    services.tick()
    assert [(m.position, m.to_address) for m in emails(a, "reminder")] == \
        [(2, "lee@samplehomes.net")]
    at(7, 10)
    services.tick()
    assert len(emails(a, "reminder")) == 2
    assert CoOwner.all_objects.get(agreement=a, position=2).reminders == [3, 7]
    monkeypatch.setattr(timezone, "now", real_now)


def test_the_owners_can_be_corrected_until_the_first_owner_signs(aw):
    a = create(aw, co_owners=[LEE])
    c = as_(aw["jackie"])
    c.post(f"/api/agreements/{a.pk}/send")
    r = c.patch(f"/api/agreements/{a.pk}", json.dumps({"co_owners": [LEE, PAT]}),
                content_type="application/json")
    assert r.status_code == 200
    assert [o["name"] for o in r.json()["owners"]] == ["Alex Sample", "Lee Sample", "Pat Sample"]
    assert AgreementEvent.all_objects.filter(agreement=a, kind="owners_corrected").exists()
    r = c.patch(f"/api/agreements/{a.pk}", json.dumps({"co_owners": [LEE] * 4}),
                content_type="application/json")
    assert r.status_code == 400 and "up to four owners" in r.json()["detail"]
    r = c.patch(f"/api/agreements/{a.pk}", json.dumps({"co_owners": [{"name": "No Email"}]}),
                content_type="application/json")
    assert r.status_code == 400 and "No Email's email" in r.json()["detail"]
    owner_signs(a)
    r = c.patch(f"/api/agreements/{a.pk}", json.dumps({"co_owners": [LEE]}),
                content_type="application/json")
    assert r.status_code == 409 and "Cancel it, then start a new agreement" in r.json()["detail"]


def test_cancelling_needs_a_reason_and_tells_only_the_owners_who_signed(aw):
    c = as_(aw["jackie"])
    a = create(aw, co_owners=[LEE])
    c.post(f"/api/agreements/{a.pk}/send")
    owner_signs(a)
    r = c.post(f"/api/agreements/{a.pk}/cancel", json.dumps({"reason": "  "}),
               content_type="application/json")
    assert r.status_code == 400 and "reason" in r.json()["detail"]
    r = c.post(f"/api/agreements/{a.pk}/cancel",
               json.dumps({"reason": "Lee is selling their share"}),
               content_type="application/json")
    assert r.status_code == 200 and r.json()["cancel_reason"] == "Lee is selling their share"
    withdrawn = emails(a, "withdrawn")
    assert [(m.position, m.to_address) for m in withdrawn] == [(1, "alex@samplehomes.net")]
    assert "was withdrawn" in withdrawn[0].subject
    assert Client().get(f"/api/fa/{token_of(a)}").status_code == 404
    assert AuditEvent.all_objects.filter(verb="agreements.cancelled").exists()
    assert "Lee is selling their share" in AgreementEvent.all_objects.get(
        agreement=a, kind="cancelled").detail

    # After every owner has signed, still; after SkyRun has signed, never.
    b = create(aw)
    c.post(f"/api/agreements/{b.pk}/send")
    owner_signs(b)
    r = c.post(f"/api/agreements/{b.pk}/cancel", json.dumps({"reason": "Wrong split"}),
               content_type="application/json")
    assert r.status_code == 200 and len(emails(b, "withdrawn")) == 1
    d = create(aw)
    owner_signs(d)
    assert countersign(aw, d, "michael", method="typed", typed="Michael").status_code == 200
    r = c.post(f"/api/agreements/{d.pk}/cancel", json.dumps({"reason": "Too late"}),
               content_type="application/json")
    assert r.status_code == 409 and "can't be cancelled or corrected" in r.json()["detail"]
    # Nobody who hadn't signed is told.
    e = create(aw, co_owners=[LEE])
    c.post(f"/api/agreements/{e.pk}/send")
    c.post(f"/api/agreements/{e.pk}/cancel", json.dumps({"reason": "Duplicate"}),
           content_type="application/json")
    assert not emails(e, "withdrawn")


def test_a_new_agreement_from_a_cancelled_one_carries_the_intake(aw):
    c = as_(aw["jackie"])
    a = create(aw, co_owners=[LEE])
    c.post(f"/api/agreements/{a.pk}/send")
    owner_signs(a)
    sub = a.submission
    with tenant_context(a.tenant_id):
        vault.put(sub, vault.Kind.CODE, "door", "4821")
    secret = SubmissionSecret.all_objects.get(submission=sub)
    cipher = bytes(secret.ciphertext)
    assert c.post(f"/api/agreements/{a.pk}/restart").status_code == 409    # not cancelled
    c.post(f"/api/agreements/{a.pk}/cancel", json.dumps({"reason": "Lee's name was wrong"}),
           content_type="application/json")
    r = c.post(f"/api/agreements/{a.pk}/restart")
    assert r.status_code == 201, r.content
    new = OwnerAgreement.all_objects.get(pk=r.json()["id"])
    assert new.number == a.number + 1 and new.started_from_id == a.pk and new.sent_at is None
    assert services.current(new).terms == services.terms_for(a)
    assert [(x.name, x.email, x.title) for x in services.co_owners(new)] == \
        [("Lee Sample", "lee@samplehomes.net", "Trustee")]
    assert new.details == a.details and new.owner_signed_at is None
    # The same intake, moved, its encrypted values untouched where they are.
    a.refresh_from_db()
    assert a.submission_id is None and new.submission_id == sub.pk
    again = SubmissionSecret.all_objects.get(submission=sub)
    assert again.pk == secret.pk and bytes(again.ciphertext) == cipher
    assert SubmissionSecret.all_objects.count() == 1
    sub.refresh_from_db()
    assert "isn't countersigned yet" in intake_services.agreement_waiting(sub)
    assert SubmissionEvent.all_objects.filter(
        submission=sub, detail__contains=f"Carried over to owner agreement #{new.number}").exists()
    assert c.post(f"/api/agreements/{a.pk}/restart").status_code == 409    # once only
    detail = c.get(f"/api/agreements/{a.pk}").json()
    assert detail["successor"]["number"] == new.number and detail["may_restart"] is False
    # The new one is signed from the start, and its first signing finds the intake.
    c.post(f"/api/agreements/{new.pk}/send")
    owner_signs(new)
    assert new.submission_id == sub.pk


def test_a_change_to_exhibit_a_that_blocks_countersigning_is_named(aw, monkeypatch):
    a = create(aw)
    owner_signs(a)                                    # sleeps 8: 12 place settings, mats 8
    sig = AgreementSignature.all_objects.get(agreement=a, role="owner")
    assert sig.exhibit_a["place_settings"] == 12 and sig.exhibit_a["place_mats"] == 8
    monkeypatch.setitem(exhibit_a.RULES, "place_settings", (2, 4, 8))    # now 16
    detail = as_(aw["michael"]).get(f"/api/agreements/{a.pk}").json()
    assert detail["may_countersign"] is False
    problem = detail["words_problem"]
    assert "Exhibit A's quantities were changed after the owner signed" in problem
    assert "12 place settings" in problem and "16 place settings" in problem
    assert "Start a new agreement from this one" in problem
    r = countersign(aw, a, "michael", method="typed", typed="Michael")
    assert r.status_code == 409 and "Exhibit A's quantities were changed" in r.json()["detail"]


def _page_texts(stored):
    from pypdf import PdfReader

    from apps.tenancy import storage

    return [flat(p.extract_text()) for p in PdfReader(io.BytesIO(storage.read(stored))).pages]


def test_the_owner_page_and_the_signature_page_each_fit_one_page(aw):
    long = {**DETAILS, "owner_type": "entity",
            "entity_name": "The Alexandra Samplesworth-Montgomery Family Revocable Trust",
            "signer_title": "Successor Co-Trustee", "business_phone": "435-555-0199",
            "mailing": {"street": "12345 North Longstreet Boulevard", "street2": "Suite 1200",
                        "city": "Salt Lake City", "state": "UT", "zip": "84101-1234"},
            "emergency": {"name": "Jamie Samplesworth-Montgomery", "phone": "435-555-0188",
                          "address": "4567 West Very Long Avenue Name, Apartment 89, Denver, "
                                     "CO 80202"}}
    others = [PAT, LEE, {"name": "Morgan Samplesworth-Montgomery",
                         "email": "morgan@samplehomes.net", "title": "Co-Trustee"}]
    a = create(aw, co_owners=others)
    as_(aw["jackie"]).post(f"/api/agreements/{a.pk}/send")
    owner_signs(a, details=long)
    for position in (2, 3, 4):
        assert co_signs(a, position).status_code == 200
    assert countersign(aw, a, "michael", method="typed", typed="Michael").status_code == 200
    a.refresh_from_db()
    texts = _page_texts(a.final_pdf)
    owner_page = next(i for i, t in enumerate(texts) if "UnitInformation" in t)
    page = texts[owner_page]
    for part in ("OwnerInformation", "ALTERNATEPHONE(optional)", "Ifonlyoneowner",
                 "PHONE:435-555-0188"):
        assert part in page, part
    sign_page = texts[owner_page + 1]
    assert sign_page.startswith("THEPARTIESHERETO")
    for name in ("NAME:AlexSample,SuccessorCo-Trustee", "NAME:PatSample",
                 "NAME:LeeSample,Trustee", "NAME:MorganSamplesworth-Montgomery,Co-Trustee",
                 "(ALLownersofUnitmustsign)"):
        assert name in sign_page, name
    assert "EXHIBITA" in texts[owner_page + 2]


def test_the_intake_is_given_sleeps_and_the_other_owners(aw):
    a = create(aw, co_owners=[LEE])
    as_(aw["jackie"]).post(f"/api/agreements/{a.pk}/send")
    owner_signs(a)
    sub = a.submission
    assert sub.staff["sleeps_total"] == 8
    about = sub.answers["about"]
    assert about["has_extra_owners"] == "yes"
    assert about["extra_owners"] == [{"first_name": "Lee", "last_name": "Sample",
                                      "email": "lee@samplehomes.net", "mobile": "",
                                      "portal": False}]


def test_the_emergency_contact_is_needed_only_with_one_owner(aw):
    no_contact = {**DETAILS, "emergency": {"name": "", "phone": "", "address": ""}}
    a = create(aw)
    o = Client()
    t = token_of(a)
    o.patch(f"/api/fa/{t}/details", json.dumps({"details": no_contact}),
            content_type="application/json")
    assert "an emergency contact's name and phone" in o.get(f"/api/fa/{t}").json()["missing"]
    b = create(aw, co_owners=[LEE])
    t = token_of(b)
    o.patch(f"/api/fa/{t}/details", json.dumps({"details": no_contact}),
            content_type="application/json")
    assert o.get(f"/api/fa/{t}").json()["missing"] == []
    o.patch(f"/api/fa/{t}/details", json.dumps({"details": {"sleeps": ""}}),
            content_type="application/json")
    assert "how many guests the property sleeps" in o.get(f"/api/fa/{t}").json()["missing"]
