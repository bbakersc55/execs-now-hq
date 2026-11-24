"""The fixes before merging owner agreements (owner, 2026-11-24): nothing that
signs, authorizes or changes anything while acting as someone; the signing
record names the account that did it; the two fingerprints explained, with the
exact signed text to download; the permissions screen whenever intake or
agreements is on; test mode changed only by the practice owner and the Client
owner, each change recorded; stored Outbox copies never hold an owner's link;
and no trace when owner agreements are off."""

from __future__ import annotations

import hashlib
import io
import json
import re

import pytest
from django.core.management import call_command
from django.test import Client

from apps.agreements import mail, services
from apps.agreements.models import (
    AgreementSignature, CountersignAuthority, OwnerAgreement, Program, StaffAccess,
)
from apps.crm.models import EmailMessage, OutboxMessage
from apps.intake import links as intake_links
from apps.intake.models import IntakeForm
from apps.tenancy.models import AuditEvent

from .factories import ClientCompanyFactory, MembershipFactory
from .test_agreements import (  # noqa: F401
    DETAILS, TERMS, as_, aw, countersign, create, fake, flat, owner_signs, pdf_text,
    record_authority, token_of, world,
)

pytestmark = pytest.mark.django_db


def acting(w, real, target):
    """A client for `real`, acting as `target`."""
    c = as_(w[real])
    r = c.post("/api/act-as/", json.dumps({"membership": str(w[target].pk)}),
               content_type="application/json")
    assert r.status_code in (200, 201), r.content
    return c


def refused_as(response, w, target):
    assert response.status_code == 403, response.content
    name = w[target].user.full_name
    assert response.json()["detail"] == f"You're acting as {name}. Stop acting as them to do this."


def j(c, method, url, body=None):
    return getattr(c, method)(url, json.dumps(body or {}), content_type="application/json")


# ------------------------------------------------------------ 1. acting as someone

def test_while_acting_nothing_that_signs_authorizes_or_changes_goes_through(aw):
    co = aw["company"].pk
    a = create(aw)
    c = acting(aw, "ff", "michael")                      # the practice owner as Michael
    # Recording the authorization.
    refused_as(j(c, "post", f"/api/agreements/companies/{co}/authority",
                 {"method": "typed", "typed": "Michael LeClerc", "people": [],
                  "agreed": True}), aw, "michael")
    assert not CountersignAuthority.all_objects.exists()
    # Who signs for the company; the sender.
    refused_as(j(c, "put", f"/api/agreements/companies/{co}/settings",
                 {"signer_id": str(aw["jackie"].user_id)}), aw, "michael")
    refused_as(j(c, "put", f"/api/agreements/companies/{co}/settings",
                 {"from_name": "Changed"}), aw, "michael")
    refused_as(j(c, "post", f"/api/agreements/companies/{co}/settings", {"action": "resume"}),
               aw, "michael")
    assert Program.all_objects.get(company=aw["company"]).signer_id == aw["michael"].user_id
    # Ticks on the permissions screen.
    rows = as_(aw["ff"]).get(f"/api/agreements/companies/{co}/access").json()["rows"]
    sandra = next(r for r in rows if r["user_id"] == str(aw["sandra"].user_id))
    refused_as(j(c, "put", f"/api/agreements/companies/{co}/access",
                 {"rows": [{**sandra, "signed_pdfs": True}]}), aw, "michael")
    assert not StaffAccess.all_objects.get(user=aw["sandra"].user).signed_pdfs
    # Test mode.
    refused_as(j(c, "post", f"/api/intake/companies/{co}/test-mode", {"on": False}),
               aw, "michael")
    # Creating, correcting, sending, copying the link, withdrawing an agreement.
    refused_as(j(c, "post", f"/api/agreements/companies/{co}/agreements",
                 {"name": "X", "email": "x@y.co", "terms": TERMS}), aw, "michael")
    refused_as(j(c, "patch", f"/api/agreements/{a.pk}", {"terms": {**TERMS,
               "owner_percent": "75", "manager_percent": "25"}}), aw, "michael")
    for action in ("send", "link", "cancel"):
        refused_as(j(c, "post", f"/api/agreements/{a.pk}/{action}"), aw, "michael")
    a.refresh_from_db()
    assert a.sent_at is None and a.voided_at is None
    assert OwnerAgreement.all_objects.filter(company=aw["company"]).count() == 1
    # Viewing still works.
    for url in (f"/api/agreements/{a.pk}", f"/api/agreements/companies/{co}",
                f"/api/agreements/companies/{co}/authority",
                f"/api/agreements/companies/{co}/access",
                f"/api/agreements/companies/{co}/settings", f"/api/intake/companies/{co}/form"):
        assert c.get(url).status_code == 200, url


def test_while_acting_nobody_signs_personally_applies_or_withdraws(aw):
    a = create(aw)
    owner_signs(a)
    # Signing personally, acting as Michael.
    c = acting(aw, "ff", "michael")
    refused_as(j(c, "post", f"/api/agreements/{a.pk}/countersign",
                 {"agreed": True, "method": "typed", "typed": "Michael LeClerc"}),
               aw, "michael")
    # Applying the company signature, Michael acting as Jackie (named in it).
    record_authority(aw, [aw["jackie"].user])
    c = acting(aw, "michael", "jackie")
    refused_as(j(c, "post", f"/api/agreements/{a.pk}/countersign", {"agreed": True}),
               aw, "jackie")
    assert not AgreementSignature.all_objects.filter(agreement=a, role="manager").exists()
    # Withdrawing the authorization, acting as Michael.
    c = acting(aw, "ff", "michael")
    refused_as(j(c, "delete", f"/api/agreements/companies/{aw['company'].pk}/authority"),
               aw, "michael")
    assert CountersignAuthority.all_objects.get(company=aw["company"]).ended_at is None


# ------------------------------------------------------------ 2. names from the account

def test_the_record_names_the_account_never_the_template(aw):
    dana = aw["michael"].user
    dana.full_name = "Dana Fictional"                 # "Who signs" is not named Michael
    dana.save()
    a = create(aw)
    owner_signs(a)
    record_authority(aw, [aw["jackie"].user])
    authority = CountersignAuthority.all_objects.get(company=aw["company"], ended_at=None)
    assert authority.recorded_by_name == "Dana Fictional"
    assert authority.wording.startswith("I, Dana Fictional, adopt the signature")
    assert countersign(aw, a, "jackie").status_code == 200
    a.refresh_from_db()
    final = pdf_text(a.final_pdf)
    jackie = aw["jackie"].user
    for phrase in (f"Applied by {jackie.full_name} under the authorization Dana Fictional "
                   "recorded on",
                   "the standing authorization recorded by Dana Fictional on",
                   "Signature block Michael LeClerc, President (as printed in the agreement)",
                   "NAME: Michael LeClerc, President"):
        assert flat(phrase) in final, phrase
    assert flat("Michael LeClerc's standing authorization") not in final
    for email in (jackie.email, dana.email, aw["ff"].user.email):
        assert flat(email) not in final
    assert "getexecutivesnow" not in final.lower() and "ExecutivesNow" not in final
    # The event log keeps the account's id and email.
    event = AuditEvent.all_objects.get(verb="agreements.countersigned")
    assert event.payload["user_id"] == str(jackie.pk) and event.payload["email"] == jackie.email
    recorded = AuditEvent.all_objects.get(verb="agreements.authority_recorded")
    assert recorded.payload["user_id"] == str(dana.pk) and recorded.payload["email"] == dana.email


def test_signing_personally_names_the_account(aw):
    dana = aw["michael"].user
    dana.full_name = "Dana Fictional"
    dana.save()
    a = create(aw)
    owner_signs(a)
    assert countersign(aw, a, "michael", method="typed", typed="Dana Fictional") \
        .status_code == 200
    a.refresh_from_db()
    final = pdf_text(a.final_pdf)
    assert flat("Signed personally by Dana Fictional") in final
    assert flat("Michael LeClerc, personally") not in final


# ------------------------------------------------------------ 3. the fingerprints

def test_the_fingerprints_are_explained_and_the_signed_text_matches(aw):
    a = create(aw)
    owner_signs(a)
    sig = AgreementSignature.all_objects.get(agreement=a, role="owner")
    kept = sig.signed_text
    assert kept and "on the date of Manager’s signature below" in kept
    owner_copy = pdf_text(a.owner_pdf)
    assert flat("SkyRun Park City has not signed yet") in owner_copy
    countersign(aw, a, "michael", method="typed", typed="Michael LeClerc")
    a.refresh_from_db()
    final = pdf_text(a.final_pdf)
    for sentence in (
        "Words signed is the fingerprint of the full text of the agreement as the Owner saw "
        "and signed it: every section, the terms set for this Owner, the property address and "
        "the Owner's answers. In that text the agreement date read 'on the date of Manager's "
        "signature below', and it contains no signatures.",
        "Agreement pages is the fingerprint of the finished pages above, which add the "
        "agreement date and both signatures. The agreement date was filled in when SkyRun Park "
        "City signed.",
        "SkyRun Park City keeps the exact text the Owner signed and can provide it on request."):
        assert flat(sentence) in final, sentence[:40]
    printed = re.search(r"Wordssigned\(SHA-256\)([0-9a-f]{64})", final).group(1)
    # Jackie is ticked for signed PDFs: the download, unchanged since signing.
    r = as_(aw["jackie"]).get(f"/api/agreements/{a.pk}/signed-text")
    assert r.status_code == 200 and r["Content-Type"].startswith("text/plain")
    assert hashlib.sha256(r.content).hexdigest() == printed == sig.text_sha256
    sig.refresh_from_db()
    assert sig.signed_text == kept and r.content.decode("utf-8") == kept
    # Not for people without the signed-PDFs tick.
    assert as_(aw["sandra"]).get(f"/api/agreements/{a.pk}/signed-text").status_code == 404
    docs = as_(aw["jackie"]).get(f"/api/agreements/companies/{aw['company'].pk}/documents")
    assert docs.json()["documents"][0]["text"].endswith("/signed-text")


# ------------------------------------------------------------ 4. the permissions screen

def test_the_permissions_screen_with_intake_on_and_agreements_off(world):
    co = world["company"].pk
    url = f"/api/agreements/companies/{co}/access"
    page = as_(world["ff"]).get(url)
    assert page.status_code == 200
    assert page.json()["columns"] == {"agreements": False, "signed_pdfs": False, "intake": True}
    member = next(r for r in page.json()["rows"] if r["user_id"] == str(world["member"].user_id))
    assert "agreements" not in member and member["intake"] is False
    r = j(as_(world["fcc"]), "put", url, {"rows": [{**member, "intake": True,
                                                    "agreements": True}]})
    assert r.status_code == 200
    row = StaffAccess.all_objects.get(user=world["member"].user)
    assert row.intake and not row.agreements                   # an off column isn't set
    assert as_(world["member"]).get(f"/api/intake/companies/{co}/submissions").status_code == 200
    assert as_(world["manager"]).get(url).status_code == 404    # not an editor
    form = as_(world["ff"]).get(f"/api/intake/companies/{co}/form").json()
    assert form["may_edit_access"] is True
    rows = as_(world["ff"]).get(f"/api/intake/companies/{co}/submissions").json()
    assert rows["may_edit_access"] is True


def test_the_permissions_screen_with_both_on_and_with_both_off(aw):
    url = f"/api/agreements/companies/{aw['company'].pk}/access"
    assert as_(aw["michael"]).get(url).json()["columns"] == {
        "agreements": True, "signed_pdfs": True, "intake": True}
    other = ClientCompanyFactory(tenant=aw["practice"], name="Other Client")
    assert as_(aw["ff"]).get(f"/api/agreements/companies/{other.pk}/access").status_code == 404


# ------------------------------------------------------------ 5. test mode

def test_only_the_practice_owner_and_the_client_owner_change_test_mode(aw):
    co = aw["company"].pk
    url = f"/api/intake/companies/{co}/test-mode"
    form = as_(aw["jackie"]).get(f"/api/intake/companies/{co}/form").json()
    assert form["test_mode"] is False and form["may_change_test_mode"] is False   # sees it
    r = j(as_(aw["jackie"]), "post", url, {"on": True})
    assert r.status_code == 403 and "practice owner and the Client owner" in r.json()["detail"]
    # Form settings can't change it either.
    j(as_(aw["jackie"]), "put", f"/api/intake/companies/{co}/form",
      {"settings": {"test_mode": True}})
    assert IntakeForm.all_objects.get(company=aw["company"]).settings["test_mode"] is False
    r = j(as_(aw["michael"]), "post", url, {"on": True})
    assert r.status_code == 200 and r.json()["test_mode"] is True
    r = j(as_(aw["ff"]), "post", url, {"on": False})
    assert r.json()["test_mode"] is False
    j(as_(aw["ff"]), "post", url, {"on": False})                # no change: no event
    events = list(AuditEvent.all_objects.filter(verb="intake.test_mode_changed")
                  .order_by("created_at"))
    assert [(e.actor_id, e.payload["from"], e.payload["to"]) for e in events] == [
        (aw["michael"].user_id, False, True), (aw["ff"].user_id, True, False)]
    change = r.json()["test_mode_change"]
    assert change["to"] is False and change["by"] == aw["ff"].user.full_name


# ------------------------------------------------------------ 6b. stored copies

def test_stored_outbox_copies_never_hold_an_owners_link(aw):
    from apps.agreements.models import OwnerEmail
    from apps.tenancy.context import tenant_context

    a = create(aw)
    as_(aw["jackie"]).post(f"/api/agreements/{a.pk}/send")
    with tenant_context(a.tenant_id):
        mail.to_owner(a, "reminder")
    o, t = owner_signs(a)
    a.refresh_from_db()
    with tenant_context(a.tenant_id):
        mail.to_owner(a, "intake_link")
        mail.to_owner(a, "intake_reminder")
    intake_token = intake_links.token_of(a.submission)
    sent = set(OwnerEmail.all_objects.filter(agreement=a).exclude(state="held")
               .values_list("kind", flat=True))
    assert {"invite", "reminder", "owner_copy", "intake_link", "intake_reminder"} <= sent
    messages = list(OutboxMessage.all_objects.filter(producer="owner_agreement"))
    assert len(messages) >= 5
    for m in messages:
        for part in (m.body_text, m.body_html):
            assert t not in part and intake_token not in part and "/a/" not in part, m.subject
    for e in EmailMessage.all_objects.all():
        assert t not in (e.body_text or "") and intake_token not in (e.body_text or "")


# ------------------------------------------------------------ 6d. no trace when off

def test_no_trace_when_off_settings_documents_and_the_notification_choice(aw):
    from apps.notify.service import kinds_for

    co = aw["company"].pk
    assert "agreement" in kinds_for(aw["jackie"])
    nobody = MembershipFactory(tenant=aw["practice"], role="ECC", client_company=aw["company"])
    assert "agreement" not in kinds_for(nobody)
    call_command("owner_agreements", str(co), "off", stdout=io.StringIO())
    for who in ("ff", "michael", "jackie"):
        assert "agreement" not in kinds_for(aw[who]), who
        for url in (f"/api/agreements/companies/{co}/settings",
                    f"/api/agreements/companies/{co}/authority",
                    f"/api/agreements/companies/{co}"):
            assert as_(aw[who]).get(url).status_code == 404, (who, url)
        assert as_(aw[who]).get(f"/api/agreements/companies/{co}/documents") \
            .json()["documents"] == []
    # With agreements off, the permissions screen shows intake only.
    assert as_(aw["ff"]).get(f"/api/agreements/companies/{co}/access").json()["columns"] == {
        "agreements": False, "signed_pdfs": False, "intake": True}
    # Another practice and another company: nothing at all.
    other = ClientCompanyFactory(tenant=aw["practice"], name="Other Client")
    for url in (f"/api/agreements/companies/{other.pk}/settings",
                f"/api/agreements/companies/{other.pk}/access"):
        assert as_(aw["ff"]).get(url).status_code == 404
    assert Client().get("/api/agreements/companies").status_code in (401, 403)
