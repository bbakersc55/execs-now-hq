"""Owner agreements (docs/p15_owner_agreements.md), end to end against the
fake Track: staff send, the owner signs on their link, the signer's standing
authorization, a countersignature applied under it and recorded as such, the
PDFs, the emails, the intake made from it, and Send to Track held until it is
countersigned. Also who may do what (one permissions screen), the switch, the
owner email senders (never a fallback, never a real email from here), the
reminders, white label, and that none of it writes to Track."""

from __future__ import annotations

import io
import json
import re
from datetime import timedelta

import pytest
from django.core import mail as django_mail
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from apps.agreements import links, mail, postmark, services
from apps.agreements.models import (
    AgreementSignature, CountersignAuthority, OwnerAgreement, OwnerEmail, Program, StaffAccess,
)
from apps.crm.models import OutboxMessage
from apps.intake.models import Submission
from apps.notify.models import Notice
from apps.tenancy.context import tenant_context

from .factories import ClientCompanyFactory, MembershipFactory, TenantFactory, UserFactory
from .test_intake_flow import as_, fake, world  # noqa: F401

pytestmark = pytest.mark.django_db

DETAILS = {"owner_type": "person", "first_name": "Alex", "last_name": "Sample",
           "phone": "435-555-0123", "email": "alex@samplehomes.net",
           "business_phone": "", "mailing": {"street": "9 Elm St", "city": "Denver",
                                             "state": "CO", "zip": "80202"},
           "bedrooms": "3", "bathrooms": "2.5", "square_feet": "1,850",
           "emergency": {"name": "Jamie Sample", "phone": "435-555-0188",
                         "address": "1 Oak Ave, Denver"}}
TERMS = {"owner_percent": "70", "manager_percent": "30",
         "fees": {"winter": {"threshold": "4000", "fee": "250"},
                  "summer": {"threshold": "0", "fee": "0"},
                  "fall": {"threshold": "0", "fee": "0"}},
         "additional_items": "",
         "property_address": {"street": "400 Lift Road", "unit": "#3", "city": "Park City",
                              "state": "UT", "zip": "84060"}}
NEVER_TO_OWNERS = ("Execs NOW HQ", "Executives Now", "Noble Rose", "practice-staff.test")


@pytest.fixture
def aw(world, settings):
    """The world with owner agreements on: the Client owner is the signer
    ("Michael"), the team manager is "Jackie" (agreements, signed PDFs,
    intake), the plain member "Sandra" (agreements only)."""
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    django_mail.outbox = []
    company = world["company"]
    call_command("owner_agreements", str(company.pk), "on", stdout=io.StringIO())
    program = Program.all_objects.get(company=company)
    program.signer = world["fcc"].user
    program.save()
    StaffAccess.all_objects.update_or_create(
        tenant=world["practice"], company=company, user=world["manager"].user,
        defaults={"agreements": True, "signed_pdfs": True, "intake": True})
    StaffAccess.all_objects.create(tenant=world["practice"], company=company,
                                   user=world["member"].user, agreements=True)
    world["jackie"], world["sandra"], world["michael"] = (world["manager"], world["member"],
                                                          world["fcc"])
    return world


def create(w, by="jackie", terms=None, **over):
    body = {"name": "Alex Sample", "email": "alex@samplehomes.net", "phone": "",
            "terms": terms or TERMS, **over}
    r = as_(w[by]).post(f"/api/agreements/companies/{w['company'].pk}/agreements",
                        json.dumps(body), content_type="application/json")
    assert r.status_code == 201, r.content
    return OwnerAgreement.all_objects.get(pk=r.json()["id"])


def token_of(a) -> str:
    with tenant_context(a.tenant_id):
        return links.ensure(a)


def owner_signs(a, details=None, **sig):
    o = Client(REMOTE_ADDR="203.0.113.9", HTTP_USER_AGENT="Phone browser")
    t = token_of(a)
    assert o.get(f"/api/fa/{t}").status_code == 200
    r = o.patch(f"/api/fa/{t}/details", json.dumps({"details": details or DETAILS}),
                content_type="application/json")
    assert r.status_code == 200, r.content
    r = o.post(f"/api/fa/{t}/sign", json.dumps({"method": "typed", "typed": "Alex Sample",
                                                 "agreed": True, **sig}),
               content_type="application/json")
    assert r.status_code == 200, r.content
    a.refresh_from_db()
    return o, t


def record_authority(w, people):
    r = as_(w["michael"]).post(f"/api/agreements/companies/{w['company'].pk}/authority",
                               json.dumps({"method": "typed", "typed": "Michael LeClerc",
                                           "people": [str(u.pk) for u in people],
                                           "agreed": True}),
                               content_type="application/json", REMOTE_ADDR="198.51.100.7")
    assert r.status_code == 200, r.content
    return r.json()


def countersign(w, a, by, **body):
    return as_(w[by]).post(f"/api/agreements/{a.pk}/countersign",
                           json.dumps({"agreed": True, **body}),
                           content_type="application/json", REMOTE_ADDR="198.51.100.20")


def pdf_text(stored) -> str:
    """The PDF's words with all spacing taken out: pypdf's extraction puts
    stray spaces inside words ("City’ s", "V .2"). Check phrases with `flat`."""
    from pypdf import PdfReader

    from apps.tenancy import storage

    return flat("".join(p.extract_text() for p in
                        PdfReader(io.BytesIO(storage.read(stored))).pages))


def attached(message) -> int:
    from apps.crm.models import OutboxAttachment

    return OutboxAttachment.all_objects.filter(outbox_message=message).count()


def flat(text: str) -> str:
    return re.sub(r"\s+", "", text)


# ------------------------------------------------------------ the whole way

def test_staff_send_owner_signs_jackie_countersigns_under_michaels_authorization(aw, fake):
    writes = len(fake.writes())
    a = create(aw)
    r = as_(aw["jackie"]).post(f"/api/agreements/{a.pk}/send")
    assert r.status_code == 200, r.content
    a.refresh_from_db()
    assert a.sent_at is not None
    invite = OwnerEmail.all_objects.get(agreement=a, kind="invite")
    assert invite.sender == "testing" and invite.state == "captured"       # never real, here
    out = OutboxMessage.all_objects.get(producer="owner_agreement", source_id=a.pk)
    assert "/a/" not in out.body_text                                       # link never stored

    # The owner reads, fills in, signs.
    o, t = owner_signs(a)
    page = o.get(f"/api/fa/{t}").json()
    assert page["state"] == "signed"
    owner_sig = AgreementSignature.all_objects.get(agreement=a, role="owner")
    assert owner_sig.ip_address == "203.0.113.9" and owner_sig.user_agent == "Phone browser"
    assert owner_sig.text_sha256 and owner_sig.consent_text.startswith("By signing electronically")

    # Their copy, awaiting SkyRun's signature, by email; the team told; Jackie gets the PDF.
    assert a.owner_pdf_id and flat("Awaiting SkyRun Park City’s signature") in \
        pdf_text(a.owner_pdf)
    assert OwnerEmail.all_objects.filter(agreement=a, kind="owner_copy").exists()
    team = OutboxMessage.all_objects.filter(producer="owner_agreement_notice",
                                            subject__startswith="Owner agreement #")
    assert {m.to_address for m in team} >= {aw["jackie"].user.email, aw["sandra"].user.email,
                                             aw["ff"].user.email}
    jackie_mail = team.get(to_address=aw["jackie"].user.email)
    assert attached(jackie_mail) == 1
    assert attached(team.get(to_address=aw["sandra"].user.email)) == 0
    assert "Alex Sample" in jackie_mail.subject and "400 Lift Road" in jackie_mail.subject

    # Before any authorization, only Michael may countersign.
    assert countersign(aw, a, "jackie").status_code == 403
    request = Notice.all_objects.filter(source_type="agreement_countersign")
    assert {n.recipient_id for n in request} == {aw["michael"].user_id}

    # Michael records his authorization, naming himself, Jackie and Bryan.
    record_authority(aw, [aw["michael"].user, aw["jackie"].user, aw["ff"].user])
    authority = CountersignAuthority.all_objects.get(company=aw["company"], ended_at=None)
    assert authority.ip_address == "198.51.100.7"
    assert "new-owner rental management agreements" in authority.wording
    assert countersign(aw, a, "sandra").status_code == 403         # not named

    r = countersign(aw, a, "jackie")
    assert r.status_code == 200, r.content
    a.refresh_from_db()
    sig = AgreementSignature.all_objects.get(agreement=a, role="manager")
    # Truthful: Michael's signature, applied by Jackie under his authorization.
    assert sig.printed_name == "Michael LeClerc" and sig.applied_by_id == aw["jackie"].user_id
    assert sig.authority_id == authority.pk and sig.ip_address == "198.51.100.20"
    assert sig.consent_text.startswith("I am applying Mountain Stays's signature, the one "
                                       f"{aw['michael'].user.full_name} adopted")
    assert a.agreement_date == services.practice_today(aw["company"])

    final = pdf_text(a.final_pdf)
    for phrase in ("V.2 – November 2026", "© Park City Ski Chalets, LLC", "Signing record",
                   "not part of the agreement’s terms", "standing authorization recorded",
                   f"Applied by {aw['jackie'].user.full_name}", "NAME: Michael LeClerc, President",
                   "THIS AGREEMENT is made and entered into this"):
        assert flat(phrase) in final, phrase
    assert "DocuSign" not in final and "Awaiting" not in final
    assert owner_sig.text_sha256 in final
    for name in NEVER_TO_OWNERS:
        assert flat(name) not in final, name
    assert aw["jackie"].user.email not in final                      # names only, no emails

    # The final copy to the owner and to the signed-PDF people; in Documents.
    assert OwnerEmail.all_objects.filter(agreement=a, kind="final_copy").exists()
    assert attached(OutboxMessage.all_objects.filter(
        producer="owner_agreement_notice", to_address=aw["jackie"].user.email,
        subject__contains="countersigned").get()) == 1
    docs = as_(aw["jackie"]).get(f"/api/agreements/companies/{aw['company'].pk}/documents")
    assert [d["id"] for d in docs.json()["documents"]] == [str(a.pk)]

    # Nothing in all of it wrote to Track.
    assert len(fake.writes()) == writes


def test_the_intake_is_made_prefilled_and_held_until_countersigned(aw, fake):
    a = create(aw)
    o, t = owner_signs(a)
    sub = a.submission
    about, prop = sub.answers["about"], sub.answers["property"]
    assert (about["first_name"], about["last_name"], about["email"], about["mobile"]) == (
        "Alex", "Sample", "alex@samplehomes.net", "435-555-0123")
    assert (about["street"], about["city"], about["state"], about["postal"]) == (
        "9 Elm St", "Denver", "CO", "80202")
    assert about["emergency"] == {"name": "Jamie Sample", "address": "1 Oak Ave, Denver",
                                  "phone": "435-555-0188"}
    assert (prop["street"], prop["street2"], prop["city"], prop["postal"]) == (
        "400 Lift Road", "#3", "Park City", "84060")
    assert prop["square_feet"] == 1850
    assert len(sub.answers["bedrooms"]) == 3 and len(sub.answers["bathrooms"]) == 3   # 2.5
    assert sub.staff.get("contract_id") == 1                         # 30% is Standard 30

    # "Now" opens the intake at once; the review says it waits on the countersignature.
    r = o.post(f"/api/fa/{t}/onboarding", json.dumps({"choice": "now"}),
               content_type="application/json")
    assert r.status_code == 200 and r.json()["link"].endswith(
        "/" + __import__("apps.intake.links", fromlist=["x"]).token_of(sub))
    review = as_(aw["jackie"]).get(f"/api/intake/submissions/{sub.pk}").json()
    assert review["agreement"]["number"] == a.number and not review["agreement"]["countersigned"]
    assert any("isn't countersigned" in p for p in review["plan"]["problems"])
    assert not review["may_send"]
    r = as_(aw["jackie"]).post(f"/api/intake/submissions/{sub.pk}/send")
    assert r.status_code == 400 and "countersigned" in r.json()["detail"]

    countersign(aw, a, "michael", method="typed", typed="Michael LeClerc")
    a.refresh_from_db()
    sig = AgreementSignature.all_objects.get(agreement=a, role="manager")
    assert sig.applied_by_id == aw["michael"].user_id and sig.authority_id is None
    assert flat(f"Signed personally by {aw['michael'].user.full_name}") in pdf_text(a.final_pdf)
    sub.refresh_from_db()
    assert sub.staff["contract_effective_date"] == a.agreement_date.isoformat()
    review = as_(aw["jackie"]).get(f"/api/intake/submissions/{sub.pk}").json()
    assert review["agreement"]["countersigned"] and review["agreement"]["waiting"] == ""


def test_later_emails_the_intake_link(aw):
    a = create(aw)
    o, t = owner_signs(a)
    r = o.post(f"/api/fa/{t}/onboarding", json.dumps({"choice": "later"}),
               content_type="application/json")
    assert r.status_code == 200
    a.refresh_from_db()
    assert a.onboarding_choice == "later"
    assert OwnerEmail.all_objects.filter(agreement=a, kind="intake_link").count() == 1


# ------------------------------------------------------------ staff side

def test_terms_are_checked(aw):
    c = as_(aw["jackie"])
    url = f"/api/agreements/companies/{aw['company'].pk}/agreements"
    bad = {**TERMS, "owner_percent": "70", "manager_percent": "25"}
    r = c.post(url, json.dumps({"name": "A", "email": "a@b.co", "terms": bad}),
               content_type="application/json")
    assert r.status_code == 400 and "add up to 100" in r.json()["detail"]
    never = {**TERMS, "fees": {**TERMS["fees"], "summer": {"threshold": "0", "fee": "50"}}}
    r = c.post(url, json.dumps({"name": "A", "email": "a@b.co", "terms": never}),
               content_type="application/json")
    assert r.status_code == 400 and "needs a revenue threshold above $0" in r.json()["detail"]
    r = c.post(url, json.dumps({"name": "A", "email": "", "phone": "", "terms": TERMS}),
               content_type="application/json")
    assert r.status_code == 400 and "email, or a phone" in r.json()["detail"]
    split = {**TERMS, "owner_percent": "76.65", "manager_percent": "23.35"}
    a = create(aw, terms=split, email="", phone="435-555-0100")      # phone only: copy the link
    assert services.contract_for(a)["name"] == "Contract 23.35"
    twenty = create(aw, terms={**TERMS, "owner_percent": "80", "manager_percent": "20"})
    assert "Pick one" in services.contract_for(twenty)["flag"]
    odd = create(aw, terms={**TERMS, "owner_percent": "73", "manager_percent": "27"})
    assert "Create it in Track" in services.contract_for(odd)["flag"]


def test_a_correction_replaces_an_unsigned_agreement_and_a_signed_one_is_locked(aw):
    a = create(aw)
    c = as_(aw["jackie"])
    c.post(f"/api/agreements/{a.pk}/send")
    t = token_of(a)
    r = c.patch(f"/api/agreements/{a.pk}", json.dumps({"terms": {**TERMS,
                "owner_percent": "75", "manager_percent": "25"}}), content_type="application/json")
    assert r.status_code == 200 and r.json()["version"] == 2
    page = Client().get(f"/api/fa/{t}").json()                       # same link, new version
    assert page["terms"]["owner_percent"] == "75"
    owner_signs(a)
    r = c.patch(f"/api/agreements/{a.pk}", json.dumps({"terms": TERMS}),
                content_type="application/json")
    assert r.status_code == 409 and "can't be edited" in r.json()["detail"]


def test_the_owner_may_correct_the_address_and_staff_see_it(aw):
    a = create(aw)
    owner_signs(a, details={**DETAILS, "property_address": {
        "street": "402 Lift Road", "unit": "", "city": "Park City", "state": "UT",
        "zip": "84060"}})
    detail = as_(aw["michael"]).get(f"/api/agreements/{a.pk}").json()
    assert detail["address_changed"] and detail["owner_address"].startswith("402 Lift Road")
    assert a.submission.answers["property"]["street"] == "402 Lift Road"


def test_the_words_the_owner_signed_cannot_change_before_countersigning(aw):
    a = create(aw)
    owner_signs(a)
    version = services.current(a)
    version.terms = {**version.terms, "owner_percent": "71", "manager_percent": "29"}
    version.save()
    r = countersign(aw, a, "michael", method="typed", typed="Michael LeClerc")
    assert r.status_code == 409 and "don't match what the owner signed" in r.json()["detail"]
    assert not AgreementSignature.all_objects.filter(agreement=a, role="manager").exists()


def test_withdrawing_leaves_only_the_signer(aw):
    record_authority(aw, [aw["jackie"].user])
    r = as_(aw["jackie"]).post(f"/api/agreements/companies/{aw['company'].pk}/authority",
                               json.dumps({"method": "typed", "typed": "X", "people": [],
                                           "agreed": True}), content_type="application/json")
    assert r.status_code == 403                                      # only the signer records
    r = as_(aw["michael"]).delete(f"/api/agreements/companies/{aw['company'].pk}/authority")
    assert r.status_code == 200 and r.json()["authority"] is None
    row = CountersignAuthority.all_objects.get(company=aw["company"])
    assert row.withdrawn and row.ended_at is not None
    a = create(aw)
    owner_signs(a)
    assert countersign(aw, a, "jackie").status_code == 403


# ------------------------------------------------------------ who may do what

def test_the_permissions_screen_is_for_the_practice_owner_and_the_client_owner(aw):
    url = f"/api/agreements/companies/{aw['company'].pk}/access"
    assert as_(aw["ff"]).get(url).status_code == 200
    assert as_(aw["michael"]).get(url).status_code == 200
    assert as_(aw["jackie"]).get(url).status_code == 404
    rows = as_(aw["ff"]).get(url).json()["rows"]
    newcomer = MembershipFactory(tenant=aw["practice"], role="ECC",
                                 client_company=aw["company"])
    rows = as_(aw["ff"]).get(url).json()["rows"]
    row = next(r for r in rows if r["user_id"] == str(newcomer.user_id))
    assert not (row["agreements"] or row["signed_pdfs"] or row["intake"])   # nothing ticked
    owner = next(r for r in rows if r["practice_owner"])
    assert owner["agreements"] and owner["intake"]
    row["intake"] = True
    r = as_(aw["michael"]).put(url, json.dumps({"rows": [row]}), content_type="application/json")
    assert r.status_code == 200
    assert as_(newcomer).get(f"/api/intake/companies/{aw['company'].pk}/submissions") \
        .status_code == 200
    # Intake no longer follows team levels: a team manager without the tick is out.
    StaffAccess.all_objects.filter(user=aw["jackie"].user).update(intake=False)
    assert as_(aw["jackie"]).get(f"/api/intake/companies/{aw['company'].pk}/submissions") \
        .status_code == 404


def test_people_without_a_tick_and_other_practices_see_nothing(aw):
    a = create(aw)
    nobody = MembershipFactory(tenant=aw["practice"], role="ECC", client_company=aw["company"])
    for m in (nobody, aw["cf"], aw["va"]):
        assert as_(m).get(f"/api/agreements/{a.pk}").status_code == 404
        assert as_(m).get("/api/agreements/companies").json()["companies"] == []
    other = TenantFactory(name="Another Practice")
    stranger = MembershipFactory(tenant=other, role="FF")
    assert as_(stranger).get(f"/api/agreements/{a.pk}").status_code == 404
    assert as_(stranger).get(f"/api/agreements/companies/{aw['company'].pk}").status_code == 404
    me = as_(aw["sandra"]).get("/api/me").json()
    assert me["has_agreements"] is True
    assert as_(nobody).get("/api/me").json()["has_agreements"] is False


def test_no_trace_for_another_company_or_with_it_off(aw):
    other = ClientCompanyFactory(tenant=aw["practice"], name="Other Client",
                                 intake_forms_enabled=True)
    assert as_(aw["ff"]).get(f"/api/agreements/companies/{other.pk}").status_code == 404
    a = create(aw)
    t = token_of(a)
    call_command("owner_agreements", str(aw["company"].pk), "off", stdout=io.StringIO())
    assert Client().get(f"/api/fa/{t}").status_code == 404
    assert as_(aw["ff"]).get("/api/agreements/companies").json()["companies"] == []
    assert as_(aw["ff"]).get("/api/me").json()["has_agreements"] is False
    out = io.StringIO()
    call_command("owner_agreements", str(other.pk), stdout=out)
    assert "off" in out.getvalue()


# ------------------------------------------------------------ the sender

def test_our_own_domain_needs_a_test_that_worked_and_never_falls_back(aw, monkeypatch, settings):
    program = Program.all_objects.get(company=aw["company"])
    url = f"/api/agreements/companies/{aw['company'].pk}/settings"
    c = as_(aw["ff"])
    r = c.put(url, json.dumps({"sender": "domain"}), content_type="application/json")
    assert r.status_code == 400 and "Send a test to me" in r.json()["detail"]
    c.put(url, json.dumps({"sender_domain": "owners.example.org",
                           "from_address": "hello@owners.example.org",
                           "from_name": "Mountain Stays", "reply_to": "team@example.org"}),
          content_type="application/json")
    # Here, a test is kept on this computer and proves nothing.
    r = c.post(url, json.dumps({"action": "test"}), content_type="application/json")
    assert "proves nothing" in r.json()["message"] and not r.json()["domain_ready"]
    # In production (the Outbox's real path), Postmark answers and it counts.
    sent = []
    settings.IS_LOCAL = False
    monkeypatch.setattr(mail, "real_sending", lambda: True)
    monkeypatch.setattr(postmark, "send", lambda **kw: sent.append(kw) or f"pm-{len(sent)}")
    r = c.post(url, json.dumps({"action": "test"}), content_type="application/json")
    assert r.json()["domain_ready"] and sent[0]["to"] == aw["ff"].user.email
    assert c.put(url, json.dumps({"sender": "domain"}),
                 content_type="application/json").json()["sender"] == "domain"
    a = create(aw)
    as_(aw["jackie"]).post(f"/api/agreements/{a.pk}/send")
    assert sent[-1]["from_address"] == "hello@owners.example.org"
    assert sent[-1]["from_name"] == "Mountain Stays"
    assert sent[-1]["reply_to"] == "team@example.org" and "/a/" in sent[-1]["text"]
    for name in NEVER_TO_OWNERS:
        assert name not in sent[-1]["html"] and name not in sent[-1]["text"]
    # Through the Outbox, like every email, with the link never stored there.
    logged = OutboxMessage.all_objects.filter(producer="owner_agreement", source_id=a.pk).get()
    assert logged.sent_via == "owner_domain" and "/a/" not in logged.body_text
    assert OwnerEmail.all_objects.get(agreement=a, kind="invite").state == "sent"

    # It fails: owner emails pause, are held, and nothing goes another way.
    def refuse(**kw):
        raise postmark.PostmarkError("Postmark refused it (400): sender not confirmed")
    monkeypatch.setattr(postmark, "send", refuse)
    before = OutboxMessage.all_objects.filter(producer="owner_agreement").count()
    as_(aw["jackie"]).post(f"/api/agreements/{a.pk}/send")
    program.refresh_from_db()
    assert program.paused_at is not None and "not confirmed" in program.pause_reason
    assert OwnerEmail.all_objects.filter(agreement=a, state="held").count() == 1
    assert OutboxMessage.all_objects.filter(producer="owner_agreement").count() == before
    told = Notice.all_objects.filter(source_type__startswith="agreement_paused")
    assert {n.recipient_id for n in told} == {aw["jackie"].user_id, aw["sandra"].user_id,
                                               aw["ff"].user_id}
    # Resumed once fixed: the held one goes out.
    monkeypatch.setattr(postmark, "send", lambda **kw: sent.append(kw) or f"pm-{len(sent)}")
    r = c.post(url, json.dumps({"action": "resume"}), content_type="application/json")
    assert "1 held" in r.json()["message"]
    assert OwnerEmail.all_objects.filter(agreement=a, state="held").count() == 0


# ------------------------------------------------------------ reminders

def test_reminders_on_their_days_and_hours(aw, monkeypatch):
    from zoneinfo import ZoneInfo

    a = create(aw)
    as_(aw["jackie"]).post(f"/api/agreements/{a.pk}/send")
    tz = ZoneInfo(aw["practice"].timezone or "UTC")
    start = timezone.now().astimezone(tz)

    def at(days, hour):
        moment = (start + timedelta(days=days)).replace(hour=hour, minute=5)
        monkeypatch.setattr(services, "practice_now", lambda company: moment)
        monkeypatch.setattr(timezone, "now", lambda: moment.astimezone(ZoneInfo("UTC")))

    real_now = timezone.now
    at(2, 10)
    services.tick()
    assert not OwnerEmail.all_objects.filter(agreement=a, kind="reminder").exists()
    at(3, 8)
    services.tick()                                    # day 3, but before 9:00
    assert not OwnerEmail.all_objects.filter(agreement=a, kind="reminder").exists()
    at(3, 9)
    services.tick()
    services.tick()
    assert OwnerEmail.all_objects.filter(agreement=a, kind="reminder").count() == 1
    at(7, 11)
    services.tick()
    assert OwnerEmail.all_objects.filter(agreement=a, kind="reminder").count() == 2
    monkeypatch.setattr(timezone, "now", real_now)


# ------------------------------------------------------------ white label

def test_the_owners_pages_name_only_the_company(aw):
    a = create(aw)
    o = Client()
    t = token_of(a)
    body = o.get(f"/api/fa/{t}").content.decode()
    for name in NEVER_TO_OWNERS + (aw["jackie"].user.email, aw["ff"].user.full_name):
        assert name not in body, name
    shell = o.get(f"/forms/{aw['form'].slug}/a/{t}")
    assert shell.status_code in (200, 503)
    assert "Rental Management Agreement" in shell.content.decode()
    assert "Executives Now" not in shell.content.decode()


def test_on_the_forms_own_domain_the_agreement_answers_and_nothing_else(aw, settings):
    from apps.intake import hosts

    domain = "agreements-test.localhost"
    settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, domain]
    form = aw["form"]
    form.domain = domain
    form.save()
    hosts.forget()
    try:
        a = create(aw)
        t = token_of(a)
        c = Client(HTTP_HOST=domain)
        page = c.get(f"/a/{t}")
        assert page.status_code in (200, 503)
        assert "Rental Management Agreement" in page.content.decode()
        assert "Executives Now" not in page.content.decode()
        assert c.get(f"/api/fa/{t}").json()["number"] == a.number
        assert c.get(f"/api/agreements/{a.pk}").status_code == 404        # staff API: not here
        call_command("owner_agreements", str(aw["company"].pk), "off", stdout=io.StringIO())
        assert c.get(f"/a/{t}").status_code == 404
    finally:
        hosts.forget()
