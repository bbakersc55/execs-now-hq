"""Several mailboxes per practice (2026-10-28).

1. A practice with one connection sends exactly as before, its connection
   its one mailbox and every default.
2. The From defaults: the draft's own choice, then the thread's mailbox, the
   company's default, the person's own address where they asked for it,
   their default mailbox, the practice alias; a disconnected one passed over.
3. A mailbox disconnected stops both sending and polling.
4. The Mail tab's filing keeps mail with contacts and companies' domains, and
   stores nothing else.
5. Isolation and roles: another practice never sees or touches a mailbox or
   a message; an assistant only for assigned clients; a client never.
"""

from __future__ import annotations

import base64
import json
from datetime import timedelta
from email import message_from_bytes
from unittest import mock

import pytest
from django.utils import timezone

from apps.crm.models import (
    EmailMessage, EmailThread, GmailConnection, Mailbox, MailPreference, OutboxMessage,
    UnmatchedInbound,
)
from apps.crm.services import inbound_poll, mail_filing, mailboxes, outbox, sender, transport
from apps.tenancy.context import tenant_context
from apps.tenancy.models import ClientAssignment, SecretKind, TenantSecret

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import (
    ClientCompanyFactory, CompanyDomainFactory, ContactEmailFactory, ContactFactory,
    GmailConnectionFactory,
)

pytestmark = pytest.mark.django_db
ALIAS = "info@getexecutivesnow.com"
SHARED = "hello@shared-box.invalid"
CLIENT_BOX = "ops@hooli-box.invalid"
READ = "https://www.googleapis.com/auth/gmail.readonly"


def post(client, url, data=None):
    return client.post(url, json.dumps(data or {}), content_type="application/json")


def patch(client, url, data):
    return client.patch(url, json.dumps(data), content_type="application/json")


def _response(ok=True, status=200, payload=None, text=""):
    stub = mock.Mock()
    stub.ok, stub.status_code, stub.text = ok, status, text
    stub.json.return_value = payload or {}
    return stub


@pytest.fixture
def practice(seeded_tenant, ff, cf, va):
    """The practice owner's own Gmail (sending as the alias), a shared info
    box and a client's mailbox, both checked and reading; a client company
    with a contact; and a prospect at no company."""
    t = seeded_tenant
    t.from_address = ALIAS
    t.save(update_fields=["from_address"])
    own = GmailConnectionFactory(tenant=t, user=ff.user, email_address="bryan@getexecutivesnow.com",
                                 scopes=["gmail.send", READ], send_as_address=ALIAS,
                                 send_as_verified_at=timezone.now())
    secret = TenantSecret.all_objects.create(tenant=t, kind=SecretKind.GMAIL_REFRESH,
                                             user=ff.user, ciphertext=b"own", last4="own")
    GmailConnection.all_objects.filter(pk=own.pk).update(secret=secret)
    hooli = ClientCompanyFactory(tenant=t, name="Hooli Field Services")
    CompanyDomainFactory(tenant=t, company=hooli, domain="hooli.invalid")
    with tenant_context(t.pk):
        shared = mailboxes.store(t, actor=ff.user, provider="gmail", email_address=SHARED,
                                 refresh_token="refresh-shared", scopes=["gmail.send", READ],
                                 kind="shared", label="Info")
        client_box = mailboxes.store(t, actor=ff.user, provider="gmail",
                                     email_address=CLIENT_BOX, refresh_token="refresh-client",
                                     scopes=["gmail.send", READ], kind="client",
                                     label="Hooli ops", company=hooli)
    Mailbox.all_objects.filter(pk__in=[shared.pk, client_box.pk]).update(
        send_as_verified_at=timezone.now())
    dana = ContactFactory(tenant=t, first_name="Dana", last_name="Hooli", company=hooli)
    ContactEmailFactory(tenant=t, contact=dana, address="dana@hooli.invalid", is_primary=True)
    pat = ContactFactory(tenant=t, first_name="Pat", last_name="Prospect")
    ContactEmailFactory(tenant=t, contact=pat, address="pat@prospect.invalid", is_primary=True)
    shared.refresh_from_db()
    client_box.refresh_from_db()
    return {"t": t, "ff": ff, "cf": cf, "va": va, "own": own, "shared": shared,
            "client": client_box, "hooli": hooli, "dana": dana, "pat": pat}


def draft(p, contact, *, actor=None, producer=outbox.P.STAGE_RULE, **extra):
    with tenant_context(p["t"].pk):
        return outbox.create_message(
            tenant=p["t"], producer=producer, actor=actor or p["ff"].user,
            role="FF", to_contact=contact, to_address=contact.primary_email,
            subject="Hello", body_text="Hi", **extra)


def own_mailbox(p):
    return Mailbox.all_objects.get(gmail=p["own"])


# ------------------------------------------------------- one connection, as before

def test_a_practice_with_one_connection_sends_exactly_as_before(seeded_tenant, ff, dev_outbox):
    seeded_tenant.from_address = ALIAS
    seeded_tenant.save(update_fields=["from_address"])
    GmailConnectionFactory(tenant=seeded_tenant, user=ff.user, email_address="bryan@x.invalid",
                           send_as_address=ALIAS, send_as_verified_at=timezone.now())
    contact = ContactFactory(tenant=seeded_tenant)
    ContactEmailFactory(tenant=seeded_tenant, contact=contact, address="a@b.invalid",
                        is_primary=True)
    with tenant_context(seeded_tenant.pk):
        message = outbox.create_message(
            tenant=seeded_tenant, producer=outbox.P.MANUAL, role="FF", actor=ff.user,
            to_contact=contact, to_address="a@b.invalid", subject="Hi", body_text="Hi")
    assert message.state == "sent" and message.from_address == ALIAS
    only = Mailbox.all_objects.get(tenant=seeded_tenant)
    assert only.kind == "own" and only.user_id == ff.user_id
    assert message.mailbox_id == only.pk and message.thread.mailbox_id == only.pk
    assert dev_outbox[0].from_email == ALIAS


# ------------------------------------------------------------ the From defaults

def test_with_no_defaults_the_alias_through_the_owners_own_mailbox(practice):
    message = draft(practice, practice["pat"])
    assert (message.from_address, message.mailbox_id) == (ALIAS, own_mailbox(practice).pk)


def test_a_persons_default_mailbox_takes_the_alias_place(practice):
    MailPreference.all_objects.update_or_create(
        tenant=practice["t"], user=practice["ff"].user,
        defaults={"default_mailbox": practice["shared"]})
    message = draft(practice, practice["pat"])
    assert (message.from_address, message.mailbox_id) == (SHARED, practice["shared"].pk)
    assert message.thread.mailbox_id == practice["shared"].pk, "its own thread in that mailbox"


def test_the_companys_default_beats_the_persons(practice):
    MailPreference.all_objects.update_or_create(
        tenant=practice["t"], user=practice["ff"].user,
        defaults={"default_mailbox": practice["shared"]})
    practice["hooli"].mail_from = practice["client"]
    practice["hooli"].save(update_fields=["mail_from"])
    to_client = draft(practice, practice["dana"])
    to_prospect = draft(practice, practice["pat"])
    assert (to_client.from_address, to_client.mailbox_id) == (CLIENT_BOX, practice["client"].pk)
    assert to_prospect.mailbox_id == practice["shared"].pk


def test_my_own_address_where_i_asked_for_it_beats_my_default(practice):
    MailPreference.all_objects.update_or_create(
        tenant=practice["t"], user=practice["ff"].user,
        defaults={"default_mailbox": practice["shared"],
                  "sender_by_producer": {"stage_rule": "self"}})
    message = draft(practice, practice["pat"])
    assert message.from_address == "bryan@getexecutivesnow.com"
    assert message.mailbox_id == own_mailbox(practice).pk


def test_the_choice_on_the_outbox_item_wins_and_moves_it_to_that_mailboxs_thread(practice, api):
    practice["hooli"].mail_from = practice["client"]
    practice["hooli"].save(update_fields=["mail_from"])
    message = draft(practice, practice["dana"])
    item = api.as_(practice["ff"]).get(f"/api/outbox/{message.pk}/").json()
    assert f"mailbox:{practice['shared'].pk}" in [o["value"] for o in item["sender_options"]]
    assert item["mailbox_label"] == "Hooli ops"
    changed = patch(api.as_(practice["ff"]), f"/api/outbox/{message.pk}/edit/",
                    {"sender": f"mailbox:{practice['shared'].pk}"})
    assert changed.status_code == 200, changed.content
    message.refresh_from_db()
    assert (message.from_address, message.mailbox_id) == (SHARED, practice["shared"].pk)
    assert message.thread.mailbox_id == practice["shared"].pk
    assert changed.json()["mailbox_label"] == "Info"


def test_a_disconnected_default_is_passed_over(practice):
    MailPreference.all_objects.update_or_create(
        tenant=practice["t"], user=practice["ff"].user,
        defaults={"default_mailbox": practice["shared"]})
    with tenant_context(practice["t"].pk):
        mailboxes.disconnect(practice["shared"], actor=practice["ff"].user)
    message = draft(practice, practice["pat"])
    assert (message.from_address, message.mailbox_id) == (ALIAS, own_mailbox(practice).pk)


def test_setting_my_default_and_a_companys_through_the_api(practice, api):
    ff = api.as_(practice["ff"])
    made = post(ff, "/api/mailboxes/default/", {"mailbox": str(practice["shared"].pk)})
    assert made.status_code == 200 and made.json()["default"] == str(practice["shared"].pk)
    set_company = post(ff, "/api/mailboxes/company/", {"company": str(practice["hooli"].pk),
                                                       "mailbox": str(practice["client"].pk)})
    assert set_company.status_code == 200 and set_company.json()["mailbox"] == str(
        practice["client"].pk)
    practice["hooli"].refresh_from_db()
    with tenant_context(practice["t"].pk):
        assert sender.choose(practice["t"], practice["ff"].user, "manual",
                             company=practice["hooli"])[0] == practice["client"]


# ------------------------------------------------ disconnected: no send, no poll

def test_a_disconnected_mailbox_sends_nothing_and_says_why(practice, api, dev_outbox):
    MailPreference.all_objects.update_or_create(
        tenant=practice["t"], user=practice["ff"].user,
        defaults={"default_mailbox": practice["shared"]})
    waiting = draft(practice, practice["pat"])
    assert waiting.mailbox_id == practice["shared"].pk
    gone = post(api.as_(practice["ff"]), f"/api/mailboxes/{practice['shared'].pk}/disconnect/")
    assert gone.status_code == 200
    practice["shared"].refresh_from_db()
    assert practice["shared"].disconnected_at is not None
    assert practice["shared"].token_ciphertext is None
    with mock.patch.object(transport.GmailTransport, "send") as sent:
        refused = post(api.as_(practice["ff"]), f"/api/outbox/{waiting.pk}/approve/")
    assert refused.status_code == 403 and "is disconnected" in refused.json()["detail"]
    sent.assert_not_called()
    assert dev_outbox == []
    waiting.refresh_from_db()
    assert waiting.state == "pending_approval"
    # A direct send through it is refused the same way, never sent from another.
    with pytest.raises(transport.TransportUnavailable, match="is disconnected"):
        draft(practice, practice["pat"], producer=outbox.P.MANUAL,
              mailbox=practice["shared"])
    assert dev_outbox == []


class FakeReader:
    def __init__(self, threads=None, listed=None, full=None):
        self.threads, self.listed, self.fulls = threads or {}, listed or [], full or {}
        self.asked, self.listings = [], 0

    def thread(self, key):
        self.asked.append(key)
        return self.threads.get(key, {})

    def attachment(self, *a):
        return ""

    def listing(self, after, *, limit=100):
        self.listings += 1
        return [e for e in self.listed if e["at"] > after][:limit]

    def full(self, envelope):
        return self.fulls[envelope["id"]]


def test_a_disconnected_mailbox_is_not_polled_or_filed(practice):
    t = practice["t"]
    thread = EmailThread.all_objects.create(tenant=t, thread_token="tok-shared",
                                            contact=practice["pat"], mailbox=practice["shared"],
                                            gmail_thread_id="g-shared")
    Mailbox.all_objects.filter(pk=practice["shared"].pk).update(
        files_mail=True, files_after=timezone.now() - timedelta(days=1))
    reader = FakeReader(listed=[{"id": "m1", "thread": "x", "at": timezone.now(),
                                 "from": "pat@prospect.invalid", "to": SHARED, "cc": "",
                                 "message_id": ""}],
                        full={"m1": {"id": "m1", "threadId": "x", "payload": {"headers": []}}})
    with tenant_context(t.pk):
        inbound_poll.poll(t, readers={practice["shared"].pk: reader})
        assert reader.asked == ["g-shared"]
        mailboxes.disconnect(Mailbox.all_objects.get(pk=practice["shared"].pk),
                             actor=practice["ff"].user)
        EmailThread.all_objects.filter(pk=thread.pk).update(last_polled_at=None)
        reader.asked = []
        inbound_poll.poll(t, readers={practice["shared"].pk: reader})
        filed = inbound_poll.file_mail(t, readers={practice["shared"].pk: reader})
    assert reader.asked == [] and reader.listings == 0
    assert SHARED not in filed


# ------------------------------------------------------------- the filing

def _envelope(mid, sender, to, minutes):
    return {"id": mid, "thread": f"t-{mid}", "at": timezone.now() - timedelta(minutes=minutes),
            "from": sender, "to": to, "cc": "", "message_id": f"<{mid}@x>"}


def _payload(mid, sender, to, subject):
    body = base64.urlsafe_b64encode(f"About {subject}.".encode()).decode()
    return {"id": mid, "threadId": f"t-{mid}", "internalDate": "1761700000000",
            "payload": {"mimeType": "text/plain", "body": {"data": body},
                        "headers": [{"name": "From", "value": sender},
                                    {"name": "To", "value": to},
                                    {"name": "Subject", "value": subject},
                                    {"name": "Message-ID", "value": f"<{mid}@x>"}]}}


def test_filing_keeps_mail_with_contacts_and_company_domains_and_nothing_personal(practice):
    t, box = practice["t"], practice["shared"]
    Mailbox.all_objects.filter(pk=box.pk).update(
        files_mail=True, files_after=timezone.now() - timedelta(days=1))
    rows = [
        ("in1", "Dana <dana@hooli.invalid>", SHARED, "Schedule", 50),
        ("dom", "Someone New <newperson@hooli.invalid>", SHARED, "Hello from Hooli", 40),
        ("out1", SHARED, "pat@prospect.invalid", "Following up", 30),
        ("home", "Mum <mum@family.invalid>", SHARED, "Sunday lunch", 20),
        ("staff", "bryan@getexecutivesnow.com", SHARED, "Note to self", 10),
    ]
    reader = FakeReader(listed=[_envelope(m, s, to, n) for m, s, to, _, n in rows],
                        full={m: _payload(m, s, to, subj) for m, s, to, subj, _ in rows})
    with tenant_context(t.pk):
        counts = mail_filing.file_mailbox(Mailbox.all_objects.get(pk=box.pk), client=reader)
        again = mail_filing.file_mailbox(Mailbox.all_objects.get(pk=box.pk), client=reader)
    assert counts["kept"] == 3 and counts["passed_over"] == 2
    assert again["kept"] == 0
    kept = {m.provider_message_id: m for m in EmailMessage.all_objects.filter(tenant=t)}
    assert set(kept) == {"in1", "dom", "out1"}
    assert kept["in1"].contact == practice["dana"] and kept["in1"].direction == "inbound"
    assert kept["dom"].contact is None and kept["dom"].thread.client_company == practice["hooli"]
    assert kept["out1"].direction == "outbound" and kept["out1"].contact == practice["pat"]
    assert {m.thread.mailbox_id for m in kept.values()} == {box.pk}
    # Nothing of the personal mail anywhere: not a message, not the unmatched queue.
    blob = json.dumps([m.raw for m in EmailMessage.all_objects.all()])
    assert "Sunday lunch" not in blob and "Note to self" not in blob
    assert not UnmatchedInbound.all_objects.exists()


def test_filing_is_off_until_turned_on(practice):
    reader = FakeReader(listed=[_envelope("in1", "dana@hooli.invalid", SHARED, 5)])
    with tenant_context(practice["t"].pk):
        counts = mail_filing.file_mailbox(practice["shared"], client=reader)
    assert counts["kept"] == 0 and reader.listings == 0


# ------------------------------------------------------------- the Mail tab

def _mail(p):
    with tenant_context(p["t"].pk):
        thread = EmailThread.all_objects.create(tenant=p["t"], thread_token="tok-dana",
                                                contact=p["dana"], client_company=p["hooli"],
                                                mailbox=p["client"], gmail_thread_id="g-dana")
        EmailMessage.all_objects.create(tenant=p["t"], thread=thread, direction="inbound",
                                        provider="gmail", provider_message_id="r1",
                                        from_address="dana@hooli.invalid",
                                        to_addresses=[CLIENT_BOX], subject="Schedule",
                                        body_text="Can we move Friday?", contact=p["dana"],
                                        received_at=timezone.now(),
                                        message_id_header="<r1@hooli.invalid>")
        invoice = EmailThread.all_objects.create(tenant=p["t"], thread_token="tok-inv",
                                                 contact=p["dana"], client_company=p["hooli"],
                                                 is_financial=True)
        EmailMessage.all_objects.create(tenant=p["t"], thread=invoice, direction="outbound",
                                        provider="gmail", from_address=ALIAS,
                                        to_addresses=["dana@hooli.invalid"],
                                        subject="Invoice INV-7", body_text="Attached.",
                                        contact=p["dana"], sent_at=timezone.now())
    return thread


def test_the_mail_tab_lists_every_message_newest_first_with_its_mailbox(practice, api):
    _mail(practice)
    ff = api.as_(practice["ff"])
    for query in (f"contact={practice['dana'].pk}", f"company={practice['hooli'].pk}"):
        got = ff.get(f"/api/mail/?{query}")
        assert got.status_code == 200, got.content
        subjects = [m["subject"] for m in got.json()["results"]]
        assert set(subjects) == {"Schedule", "Invoice INV-7"}
    item = next(m for m in got.json()["results"] if m["subject"] == "Schedule")
    assert item["mailbox"]["label"] == "Hooli ops" and item["reply_from"] == CLIENT_BOX


def test_assistants_see_mail_only_for_assigned_clients_and_never_an_invoice(practice, api):
    _mail(practice)
    va = api.as_(practice["va"])
    url = f"/api/mail/?company={practice['hooli'].pk}"
    assert va.get(url).status_code == 403
    assert va.get(f"/api/mail/?contact={practice['pat'].pk}").status_code == 403
    ClientAssignment.all_objects.create(tenant=practice["t"], user=practice["va"].user,
                                        company=practice["hooli"],
                                        assigned_by=practice["ff"].user)
    got = va.get(url)
    assert got.status_code == 200
    assert [m["subject"] for m in got.json()["results"]] == ["Schedule"]


def test_an_unassigned_associate_and_a_client_get_nothing(practice, api, fcc):
    _mail(practice)
    url = f"/api/mail/?company={practice['hooli'].pk}"
    assert api.as_(practice["cf"]).get(url).status_code == 404
    assert api.as_(fcc).get(url).status_code == 403


def test_another_practice_never_sees_or_touches_a_mailbox_or_its_mail(practice, api, tenant_b):
    _mail(practice)
    other = api.as_(_member(tenant_b, "FF"))
    listed = other.get("/api/mailboxes/").json()["mailboxes"]
    assert SHARED not in [m["email_address"] for m in listed]
    box = practice["shared"].pk
    assert patch(other, f"/api/mailboxes/{box}/", {"label": "Mine"}).status_code == 404
    assert post(other, f"/api/mailboxes/{box}/disconnect/").status_code == 404
    assert post(other, "/api/mailboxes/default/", {"mailbox": str(box)}).status_code == 400
    assert other.get(f"/api/mail/?company={practice['hooli'].pk}").status_code == 404
    message = EmailMessage.all_objects.get(provider_message_id="r1")
    assert post(other, "/api/mail/reply/", {"message": str(message.pk),
                                            "body_text": "x"}).status_code == 404
    Mailbox.all_objects.get(pk=box)  # still there, still connected
    assert mailboxes.is_connected(Mailbox.all_objects.get(pk=box))


def test_only_the_owner_or_whoever_connected_it_changes_a_mailbox(practice, api):
    cf = api.as_(practice["cf"])
    box = practice["shared"].pk
    assert post(cf, f"/api/mailboxes/{box}/disconnect/").status_code == 403
    assert api.as_(practice["va"]).get("/api/mailboxes/").status_code == 403


def test_reply_in_place_goes_through_the_threads_mailbox_with_its_own_token(practice, api,
                                                                          settings):
    thread = _mail(practice)
    settings.DEV_REAL_SEND_ALLOWLIST = ["dana@hooli.invalid"]
    message = EmailMessage.all_objects.get(provider_message_id="r1")
    own_secret = TenantSecret.all_objects.get(user=practice["ff"].user,
                                              kind=SecretKind.GMAIL_REFRESH)
    sent = _response(payload={"id": "s1", "threadId": "g-dana"})
    with mock.patch.object(transport, "access_token_for", return_value="tok") as token, \
            mock.patch("apps.crm.services.transport.requests.post", return_value=sent) as out:
        replied = post(api.as_(practice["ff"]), "/api/mail/reply/",
                       {"message": str(message.pk), "body_text": "Friday is fine."})
    assert replied.status_code == 201, replied.content
    assert token.call_args.args[0] == practice["client"], "the client mailbox's own token"
    body = out.call_args.kwargs["json"]
    assert body["threadId"] == "g-dana"
    mime = message_from_bytes(base64.urlsafe_b64decode(body["raw"]))
    assert mime["From"] == CLIENT_BOX and mime["Subject"] == "Re: Schedule"
    assert "<r1@hooli.invalid>" in mime["In-Reply-To"]
    row = OutboxMessage.all_objects.get(pk=replied.json()["outbox"])
    assert row.thread_id == thread.pk and row.mailbox_id == practice["client"].pk
    own_secret.refresh_from_db()
    assert bytes(own_secret.ciphertext) == b"own", "the owner's own token is untouched"


def test_an_assistants_reply_waits_in_the_outbox(practice, api, dev_outbox):
    _mail(practice)
    ClientAssignment.all_objects.create(tenant=practice["t"], user=practice["va"].user,
                                        company=practice["hooli"],
                                        assigned_by=practice["ff"].user)
    message = EmailMessage.all_objects.get(provider_message_id="r1")
    replied = post(api.as_(practice["va"]), "/api/mail/reply/",
                   {"message": str(message.pk), "body_text": "On it."})
    assert replied.status_code == 201 and replied.json()["state"] == "pending_approval"
    assert dev_outbox == []


def test_connecting_a_shared_mailbox_leaves_the_persons_own_connection_alone(practice):
    own = GmailConnection.all_objects.get(pk=practice["own"].pk)
    with tenant_context(practice["t"].pk):
        with pytest.raises(mailboxes.MailboxRefused, match="own mailbox"):
            mailboxes.store(practice["t"], actor=practice["ff"].user, provider="gmail",
                            email_address="bryan@getexecutivesnow.com", refresh_token="x",
                            scopes=[], kind="shared")
    assert GmailConnection.all_objects.get(pk=own.pk).secret_id == own.secret_id
    assert practice["shared"].stored_token() == "refresh-shared"


def test_the_dev_allow_list_can_be_for_one_mailbox(practice, settings):
    from apps.accounts.mailer import is_real_send_allowed
    from apps.crm.models import DevSendAllowlistEntry

    settings.IS_LOCAL = True
    settings.DEV_REAL_SEND_ALLOWLIST = []
    DevSendAllowlistEntry.all_objects.create(tenant=practice["t"], address="dana@hooli.invalid",
                                             mailbox=practice["client"])
    assert is_real_send_allowed("dana@hooli.invalid", practice["t"], practice["client"])
    assert not is_real_send_allowed("dana@hooli.invalid", practice["t"], practice["shared"])
    assert not is_real_send_allowed("dana@hooli.invalid", practice["t"])
