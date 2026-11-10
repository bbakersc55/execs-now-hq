"""POST /api/public/leads: the marketing site's "Request demo access" form
(2026-11-09). The site's own server forwards each form here with the shared
secret; the lead lands in the Executives Now practice only, and the reply
waits in the Outbox for a person to approve it."""

from __future__ import annotations

import json

import pytest

from apps.accounts.models import RateCount
from apps.crm.models import (
    Company, CompanyDomain, Contact, ContactEmail, ContactPipelinePosition, ContactTypeLink,
    EmailTemplate, OutboxMessage,
)
from apps.crm.services import outbox
from apps.notes.models import Note
from apps.notify.models import Notice
from apps.tenancy.context import tenant_context

from .factories import (
    ContactEmailFactory, ContactFactory, ContactPipelinePositionFactory, MembershipFactory,
)

URL = "/api/public/leads"
SECRET = "site-lead-secret-for-tests"
SITE = "https://www.execsnowhq.com"

pytestmark = pytest.mark.django_db


@pytest.fixture
def practice(seeded_tenant, ff, settings):
    """Executives Now: tenant A, named by SITE_LEAD_PRACTICE, with its owner."""
    settings.SITE_LEAD_TOKEN = SECRET
    settings.SITE_LEAD_PRACTICE = seeded_tenant.slug
    ff.user.full_name = "Bryan Owner"
    ff.user.save(update_fields=["full_name"])
    return seeded_tenant


@pytest.fixture
def other(tenant_b):
    """Another practice, seeded, with its own owner."""
    from apps.crm.seed import seed_tenant

    seed_tenant(tenant_b)
    owner = MembershipFactory(tenant=tenant_b, role="FF")
    return tenant_b, owner


def lead(**over):
    data = {"name": "Dana Rivera", "email": "dana@rivera-ops.com",
            "practice_name": "Rivera Operations", "discipline": "coo",
            "email_platform": "microsoft", "wants": "demo_copy",
            "message": "Looking forward to\nseeing it."}
    data.update(over)
    return data


def post(client, data, *, secret=SECRET, ip="203.0.113.5", origin=None, form=False):
    headers = {}
    if secret is not None:
        headers["X-Site-Lead-Token"] = secret
    if ip is not None:
        headers["X-Lead-Client-IP"] = ip
    if origin is not None:
        headers["Origin"] = origin
    if form:
        return client.post(URL, data, headers=headers)
    return client.post(URL, json.dumps(data), content_type="application/json", headers=headers)


def nothing_written():
    return not (Contact.all_objects.exists() or Note.all_objects.exists()
                or Notice.all_objects.exists() or OutboxMessage.all_objects.exists())


def contact_of(tenant, email):
    row = ContactEmail.all_objects.filter(tenant=tenant, address__iexact=email).first()
    return row.contact if row else None


# ------------------------------------------------------------------ the secret

def test_a_missing_or_wrong_secret_is_refused_and_writes_nothing(practice, client):
    assert post(client, lead(), secret=None).status_code == 403
    assert post(client, lead(), secret="").status_code == 403
    assert post(client, lead(), secret=SECRET + "x").status_code == 403
    assert post(client, lead(), secret=SECRET[:-1]).status_code == 403
    assert nothing_written()
    # Refused before anything is counted.
    assert not RateCount.objects.exists()


def test_no_secret_on_the_server_refuses_everything(practice, client, settings):
    settings.SITE_LEAD_TOKEN = ""
    for secret in (None, "", SECRET):
        assert post(client, lead(), secret=secret).status_code == 503
    assert nothing_written()


def test_no_practice_to_receive_it_is_a_clean_refusal(practice, client, settings, caplog):
    settings.SITE_LEAD_PRACTICE = "no-such-practice"
    response = post(client, lead())
    assert response.status_code == 503
    assert "no active practice" in caplog.text
    assert nothing_written()


def test_unset_it_is_the_platform_owners_own_practice(practice, ff, client, settings):
    settings.SITE_LEAD_PRACTICE = ""
    ff.user.is_platform_owner = True
    ff.user.save(update_fields=["is_platform_owner"])
    assert post(client, lead()).status_code == 201
    assert contact_of(practice, "dana@rivera-ops.com") is not None


# ------------------------------------------------------------------ a new lead

def test_a_new_lead_does_all_seven_things_and_sends_nothing(practice, ff, stages, types,
                                                           client, dev_outbox):
    response = post(client, lead())
    assert response.status_code == 201
    assert response.json() == {"ok": True}                # never an id

    contact = contact_of(practice, "dana@rivera-ops.com")
    # 1. The contact, a prospect.
    assert (contact.first_name, contact.last_name) == ("Dana", "Rivera")
    assert contact.source == "Website" and contact.discipline == "coo"
    assert contact.owner_id == ff.user_id
    assert ContactTypeLink.all_objects.filter(contact=contact,
                                              contact_type=types["prospect"]).exists()
    # 2. The company, by the address's domain.
    assert contact.company.name == "Rivera Operations"
    assert CompanyDomain.all_objects.get(company=contact.company).domain == "rivera-ops.com"
    # 3. The tag.
    assert contact.tags == ["Website lead"]
    # 4. New, in the Website leads pipeline (2026-11-09), and nowhere else.
    position = ContactPipelinePosition.all_objects.get(contact=contact)
    assert (position.pipeline.kind, position.stage.code) == ("website", "new")
    # 5. What the form said, on the contact.
    note = Note.all_objects.get(contact=contact)
    assert note.source == Note.Source.WEBSITE and note.title == "Website request"
    for line in ("Practice: Rivera Operations", "Discipline: Fractional COO",
                 "Email: Microsoft 365 (Outlook)", "Wants: a private demo copy for 30 days",
                 "Message: Looking forward to seeing it."):
        assert line in note.body
    # 6. The owner is told.
    notice = Notice.all_objects.get(tenant=practice)
    assert notice.recipient_id == ff.user_id
    assert notice.text == "Website lead: Dana Rivera, Rivera Operations, wants a demo copy."
    assert notice.url == f"/contacts/{contact.pk}"
    # 7. The reply, from the built-in template, waiting for approval: unsent.
    message = OutboxMessage.all_objects.get(tenant=practice)
    assert message.producer == OutboxMessage.Producer.WEBSITE_REPLY
    assert message.state == OutboxMessage.State.PENDING_APPROVAL
    assert message.sent_at is None and message.approved_at is None
    assert message.to_contact_id == contact.pk and message.to_address == "dana@rivera-ops.com"
    assert message.subject == "Thanks for getting in touch"
    assert message.body_text.startswith("Hi Dana,")
    assert "within one business day with your private demo copy, yours to use for 30 days" \
        in message.body_text
    assert message.body_text.rstrip().endswith(f"Bryan Owner\n{practice.name}")
    assert message.category == "correspondence"
    assert EmailTemplate.all_objects.filter(tenant=practice, original="website_reply",
                                            name="Website reply").exists()
    assert dev_outbox == []


def test_asking_for_a_call_says_times_for_a_call(practice, client):
    assert post(client, lead(wants="call")).status_code == 201
    message = OutboxMessage.all_objects.get()
    assert "within one business day with a few times for a call." in message.body_text
    assert Notice.all_objects.get().text.endswith("wants a call.")


def test_only_name_and_email_are_needed(practice, client):
    assert post(client, {"name": "Sam", "email": "sam@solo-cfo.com"}).status_code == 201
    contact = contact_of(practice, "sam@solo-cfo.com")
    assert (contact.first_name, contact.last_name) == ("Sam", "")
    # No practice name: the company is named for the domain.
    assert contact.company.name == "solo-cfo.com"
    assert "or a few times for a call" in OutboxMessage.all_objects.get().body_text


def test_form_encoded_is_accepted(practice, client):
    assert post(client, lead(), form=True).status_code == 201
    assert contact_of(practice, "dana@rivera-ops.com") is not None


# ------------------------------------------------------------------ the company

def test_a_company_with_that_domain_is_reused(practice, client):
    with tenant_context(practice.pk):
        acme = Company.all_objects.create(tenant=practice, name="Rivera Ops LLC")
        CompanyDomain.all_objects.create(tenant=practice, company=acme, domain="rivera-ops.com")
    assert post(client, lead()).status_code == 201
    assert contact_of(practice, "dana@rivera-ops.com").company_id == acme.pk
    assert Company.all_objects.filter(tenant=practice).count() == 1


@pytest.mark.parametrize("address", ["dana@gmail.com", "dana@outlook.com", "dana@icloud.com",
                                     "dana@proton.me"])
def test_a_public_mail_address_takes_the_practice_name_not_the_domain(practice, client,
                                                                      address):
    assert post(client, lead(email=address)).status_code == 201
    company = contact_of(practice, address).company
    assert company.name == "Rivera Operations"
    assert not CompanyDomain.all_objects.exists()


def test_a_public_mail_address_and_no_practice_name_is_no_company(practice, client):
    assert post(client, lead(email="dana@gmail.com", practice_name="")).status_code == 201
    assert contact_of(practice, "dana@gmail.com").company_id is None
    assert not Company.all_objects.filter(tenant=practice).exists()


# ------------------------------------------------------- an existing contact

def test_an_existing_contact_further_along_is_not_moved_back(practice, stages, sales, client):
    """Decision (2026-11-09): anyone already in the sales pipeline stays at
    their sales stage, wherever it is (and the request lands in Website
    leads' New beside it). A form on the website does not move a deal
    backwards; the notice says they are already a contact."""
    with tenant_context(practice.pk):
        dana = ContactFactory(tenant=practice, first_name="Dana", last_name="R.",
                              tags=["VIP"])
        ContactEmailFactory(tenant=practice, contact=dana, address="Dana@Rivera-Ops.com")
        ContactPipelinePositionFactory(tenant=practice, contact=dana, pipeline=sales,
                                       stage=stages["proposal_given"])
    assert post(client, lead()).status_code == 201

    dana.refresh_from_db()
    # Their sales stage is kept; the request itself lands in Website leads' New.
    held = {p.pipeline.kind: p.stage_id
            for p in ContactPipelinePosition.all_objects.filter(contact=dana)}
    assert held["sales"] == stages["proposal_given"].pk
    assert set(held) == {"sales", "website"}
    # Their record is kept; only what was missing is added.
    assert (dana.first_name, dana.last_name) == ("Dana", "R.")
    assert dana.tags == ["VIP", "Website lead"]
    assert dana.company.name == "Rivera Operations"
    assert Contact.all_objects.filter(tenant=practice).count() == 1
    assert Notice.all_objects.get().text.endswith("Already one of your contacts.")
    assert OutboxMessage.all_objects.get().to_contact_id == dana.pk


def test_asking_twice_tags_once(practice, client):
    assert post(client, lead()).status_code == 201
    assert post(client, lead(wants="call")).status_code == 201
    contact = contact_of(practice, "dana@rivera-ops.com")
    assert contact.tags == ["Website lead"]
    assert Contact.all_objects.count() == 1
    assert Note.all_objects.filter(contact=contact).count() == 2
    assert OutboxMessage.all_objects.filter(state="pending_approval").count() == 2


# ------------------------------------------------------------- isolation

def test_another_practices_contact_with_that_address_is_untouched(practice, other, client):
    tenant_b, owner_b = other
    with tenant_context(tenant_b.pk):
        theirs = ContactFactory(tenant=tenant_b, first_name="Dana", last_name="B")
        ContactEmailFactory(tenant=tenant_b, contact=theirs, address="dana@rivera-ops.com")
    before = Contact.all_objects.filter(tenant=tenant_b).count()

    assert post(client, lead()).status_code == 201

    theirs.refresh_from_db()
    assert theirs.tags == [] and theirs.company_id is None and theirs.source == ""
    assert Contact.all_objects.filter(tenant=tenant_b).count() == before
    for model in (ContactPipelinePosition, ContactTypeLink, Note, Notice, OutboxMessage,
                  CompanyDomain):
        assert not model.all_objects.filter(tenant=tenant_b).exists(), model.__name__
    assert not Company.all_objects.filter(tenant=tenant_b, name="Rivera Operations").exists()
    # The lead is in the Executives Now practice, and only there.
    ours = contact_of(practice, "dana@rivera-ops.com")
    assert ours is not None and ours.pk != theirs.pk


def test_another_practices_people_cannot_see_the_lead(practice, other, client, api):
    _tenant_b, owner_b = other
    assert post(client, lead()).status_code == 201
    contact = contact_of(practice, "dana@rivera-ops.com")
    message = OutboxMessage.all_objects.get(tenant=practice)

    them = api.as_(owner_b)
    listed = {row["id"] for row in them.get("/api/contacts/").json()}
    assert str(contact.pk) not in listed
    assert them.get(f"/api/contacts/{contact.pk}/").status_code == 404
    assert str(message.pk) not in {row["id"] for row in them.get("/api/outbox/").json()}
    assert them.get(f"/api/outbox/{message.pk}/").status_code == 404
    assert not Notice.all_objects.filter(recipient=owner_b.user).exists()


def test_the_practice_sees_it_and_an_assistant_cannot_send_the_reply(practice, ff, va,
                                                                     client, api):
    assert post(client, lead()).status_code == 201
    contact = contact_of(practice, "dana@rivera-ops.com")
    message = OutboxMessage.all_objects.get(tenant=practice)
    assert api.as_(ff).get(f"/api/contacts/{contact.pk}/").status_code == 200
    # An assistant can see the queue but not approve: the reply stays unsent.
    assert api.as_(va).post(f"/api/outbox/{message.pk}/approve/").status_code == 403
    message.refresh_from_db()
    assert message.state == OutboxMessage.State.PENDING_APPROVAL


def test_a_client_user_cannot_reach_the_lead(practice, fcc, client, api):
    assert post(client, lead()).status_code == 201
    contact = contact_of(practice, "dana@rivera-ops.com")
    assert api.as_(fcc).get(f"/api/contacts/{contact.pk}/").status_code in (403, 404)


# ------------------------------------------------------------- rate limits

def test_five_an_hour_per_visitor_address_then_429(practice, client):
    for n in range(5):
        response = post(client, lead(email=f"p{n}@firm{n}.com"), ip="198.51.100.7")
        assert response.status_code == 201, n
    sixth = post(client, lead(email="p6@firm6.com"), ip="198.51.100.7")
    assert sixth.status_code == 429
    assert contact_of(practice, "p6@firm6.com") is None
    # Keyed on the address the site's server passed: another visitor is fine.
    assert post(client, lead(email="p7@firm7.com"), ip="198.51.100.8").status_code == 201
    # Counted in the database, so every worker sees the same count.
    row = RateCount.objects.get(prefix="site-lead-ip", count=6)
    assert "198.51.100.7" not in row.key_digest


def test_the_visitor_address_is_believed_only_with_the_secret(practice, client):
    for _ in range(10):
        assert post(client, lead(), secret="wrong", ip="198.51.100.9").status_code == 403
    assert post(client, lead(), ip="198.51.100.9").status_code == 201


def test_a_daily_cap_on_leads_overall(practice, client, monkeypatch):
    from apps.accounts.ratelimit import RateLimit
    from apps.crm import views_site_leads

    monkeypatch.setattr(views_site_leads, "PER_DAY",
                        RateLimit(limit=2, window_seconds=86400, prefix="site-lead-all"))
    assert post(client, lead(email="a@one.com"), ip="192.0.2.1").status_code == 201
    assert post(client, lead(email="b@two.com"), ip="192.0.2.2").status_code == 201
    assert post(client, lead(email="c@three.com"), ip="192.0.2.3").status_code == 429
    assert contact_of(practice, "c@three.com") is None


# ------------------------------------------------------------- the honeypot

def test_the_honeypot_answers_as_a_success_and_writes_nothing(practice, client):
    real = post(client, lead(email="real@firm.com"), ip="192.0.2.10")
    Contact.all_objects.all().delete()
    for model in (Note, Notice, OutboxMessage):
        model.all_objects.all().delete()
    trap = post(client, lead(website="http://spam.example"), ip="192.0.2.11")
    assert (trap.status_code, trap.json()) == (real.status_code, real.json()) \
        == (201, {"ok": True})
    assert nothing_written()


# ------------------------------------------------------------- validation

@pytest.mark.parametrize("over, says", [
    ({"name": ""}, "Please enter your name."),
    ({"name": "   "}, "Please enter your name."),
    ({"email": "not-an-address"}, "Please enter a valid email address."),
    ({"email": ""}, "Please enter your email address."),
    ({"discipline": "ceo"}, "Choose one of the options given."),
    ({"email_platform": "yahoo"}, "Choose one of the options given."),
    ({"wants": "everything"}, "Choose one of the options given."),
    ({"message": "x" * 1001}, "Please keep the message under 1,000 characters."),
])
def test_bad_input_is_a_400_in_plain_words(practice, client, over, says):
    response = post(client, lead(**over))
    assert response.status_code == 400
    assert response.json()["detail"] == says
    assert nothing_written()


def test_a_missing_field_and_unreadable_body(practice, client):
    data = lead()
    del data["email"]
    assert post(client, data).json()["detail"] == "Please enter your email address."
    response = client.post(URL, "{not json", content_type="application/json",
                           headers={"X-Site-Lead-Token": SECRET})
    assert response.status_code == 400
    assert nothing_written()


def test_only_post(practice, client):
    response = client.get(URL, headers={"X-Site-Lead-Token": SECRET})
    assert response.status_code == 405


# ------------------------------------------------------------- CORS

def test_cors_names_only_the_site_and_only_for_the_site(practice, client):
    ours = post(client, lead(), origin=SITE)
    assert ours["Access-Control-Allow-Origin"] == SITE
    assert "Origin" in ours["Vary"]
    for origin in ("https://evil.example", "http://www.execsnowhq.com",
                   "https://execsnowhq.com", "null"):
        response = post(client, lead(email="x@firm.com"), origin=origin)
        assert "Access-Control-Allow-Origin" not in response, origin
    assert "Access-Control-Allow-Origin" not in post(client, lead())
    # A refusal carries it for the site too, so the site can read the reason.
    assert post(client, lead(), secret="wrong", origin=SITE)[
        "Access-Control-Allow-Origin"] == SITE


def test_preflight(practice, client):
    ours = client.options(URL, headers={"Origin": SITE,
                                        "Access-Control-Request-Method": "POST"})
    assert ours.status_code == 204
    assert ours["Access-Control-Allow-Origin"] == SITE
    assert "X-Site-Lead-Token" not in ours["Access-Control-Allow-Headers"]
    theirs = client.options(URL, headers={"Origin": "https://evil.example",
                                          "Access-Control-Request-Method": "POST"})
    assert "Access-Control-Allow-Origin" not in theirs
    assert "Access-Control-Allow-Methods" not in theirs
    assert nothing_written()


# ------------------------------------------------------------- the template

def test_every_practice_gets_the_built_in_website_reply(other):
    from apps.crm import template_seed
    from apps.crm.services import templates

    tenant_b, _owner = other
    template_seed.seed_tenant(tenant_b)
    row = EmailTemplate.all_objects.get(tenant=tenant_b, original="website_reply")
    assert row.name == "Website reply"
    templates.check(row.subject, row.body)               # only fields that exist
    # Three to five lines of words, and no signature in it: the draft adds it.
    assert 3 <= len([line for line in row.body.splitlines() if line.strip()]) <= 5
    assert "{FractionalName}" not in row.body


def test_the_reply_is_refused_by_a_role_that_cannot_send(practice, va):
    from apps.crm.services.outbox import SendNotPermitted

    message = None
    with tenant_context(practice.pk):
        from apps.crm.services import site_leads

        site_leads.receive(site_leads.Lead(name="Ana Lee", email="ana@lee-hr.com"))
        message = OutboxMessage.all_objects.get(tenant=practice)
        with pytest.raises(SendNotPermitted):
            outbox.approve(message, actor=va.user, role="VA")
    message.refresh_from_db()
    assert message.state == OutboxMessage.State.PENDING_APPROVAL
