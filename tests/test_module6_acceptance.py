"""Module 6 — AC-6.2 to AC-6.11, AC-6.15 to AC-6.17, **by replay**.

Every one of these runs against a captured Gmail `threads.get` payload from
`tests/fixtures/inbound/`. That is the point, not a compromise: everything
that decides anything about an inbound message is a pure function over a parsed
payload (FR-6.13), so the fixtures are the regression suite (FR-6.15) and the
only untested part is fetching the JSON.

**A replay pass is not evidence that mail is being delivered or ingested.**
AC-6.12 and the manual checks are what say that, and they are reported
separately.

The three that carry the most weight:

- **AC-6.4** — an unmatched message is *stored*, not logged. The failure mode
  that matters in this module is silence.
- **AC-6.5 / FR-6.12** — every poll re-reads the whole thread, so the second
  sighting of a message is the normal case rather than the exception.
- **AC-6.16** — a fortnight of downtime ingests on the next run, because the
  cursor is "which thread did we look at least recently" and not a Gmail
  historyId that would have expired.
"""

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone as dt_timezone

import pytest

from apps.crm.models import (
    Contact, EmailMessage, EmailThread, UnmatchedInbound,
)
from apps.crm.services import inbound, inbound_poll, transport

from . import registry_config  # noqa: F401
from .factories import ContactEmailFactory, ContactFactory, MembershipFactory

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "inbound"
TOKEN = "thread-token-1"


def fixture(name: str) -> dict:
    """The payload as Gmail returns it, with the token stitched in.

    The token is a placeholder in the file so the fixtures stay readable and
    diffable; substituting it here is what makes them portable between runs.
    """
    body = FIXTURES.read_bytes if False else (FIXTURES / name).read_text()
    return json.loads(body.replace("TOKEN", TOKEN))


def messages_of(payload):
    return payload["messages"]


# ------------------------------------------------------------------ the world

@pytest.fixture
def known(seeded_tenant, in_tenant_a):
    """A contact we know, on a thread the app started."""
    contact = ContactFactory(tenant=seeded_tenant, first_name="Dana",
                             last_name="Reyes")
    ContactEmailFactory(tenant=seeded_tenant, contact=contact,
                        address="dana@acme.invalid")
    thread = EmailThread.objects.create(
        tenant=seeded_tenant, thread_token=TOKEN, contact=contact,
        gmail_thread_id="gmail-thread-1", subject="Your progress report")
    EmailMessage.objects.create(
        tenant=seeded_tenant, thread=thread, direction="outbound",
        provider="gmail", provider_message_id="m-sent-1",
        from_address="info@x.test", to_addresses=["dana@acme.invalid"],
        subject="Your progress report", body_text="Three things moved.",
        message_id_header=f"<{TOKEN}.abc123@x.test>",
        gmail_message_id="m-sent-1", gmail_thread_id="gmail-thread-1",
        # An hour before the replies in the fixtures, so the thread reads in
        # the order it happened rather than in the order the rows were made.
        sent_at=datetime(2026, 9, 22, 9, 0, tzinfo=dt_timezone.utc))
    return {"contact": contact, "thread": thread}


class FakeGmail:
    """Gmail at its boundary: a thread id in, a payload out."""

    def __init__(self, payloads=None):
        self.payloads = payloads or {}
        self.asked = []
        self.fail = None

    def thread(self, gmail_thread_id):
        self.asked.append(gmail_thread_id)
        if self.fail:
            raise transport.TransportUnavailable(self.fail)
        return self.payloads.get(gmail_thread_id, {})

    def attachment(self, message_id, attachment_id):   # pragma: no cover - inline
        return ""


# ------------------------------------------------------------------- AC-6.2

@pytest.mark.django_db
def test_ac_6_2_the_gmail_thread_id_matches_and_makes_no_new_thread(
    seeded_tenant, known, in_tenant_a
):
    """First rule in FR-6.6's order, and the one that carries a Gmail-native
    reply the fractional typed in Gmail rather than in the app."""
    counts = inbound.ingest_thread(seeded_tenant, fixture("thread_id_match.json"))

    assert counts["matched"] == 1
    message = EmailMessage.objects.get(direction="inbound")
    assert message.thread == known["thread"]
    assert message.contact == known["contact"]
    assert message.matched_by == inbound.BY_THREAD_ID
    assert EmailThread.objects.count() == 1


@pytest.mark.django_db
def test_ac_6_2_in_reply_to_matches_a_message_id_we_issued(
    seeded_tenant, known, in_tenant_a
):
    """Second rule. A client whose mail client started a fresh Gmail thread
    still quotes our Message-ID back at us, and the token is in it."""
    inbound.ingest_thread(seeded_tenant, fixture("in_reply_to_match.json"))

    message = EmailMessage.objects.get(direction="inbound")
    assert message.thread == known["thread"]
    assert message.matched_by == inbound.BY_IN_REPLY_TO


@pytest.mark.django_db
def test_ac_6_2_the_custom_header_matches_when_nothing_else_does(
    seeded_tenant, known, in_tenant_a
):
    """Third rule — the belt to In-Reply-To's braces, for clients that drop
    references but forward custom headers."""
    inbound.ingest_thread(seeded_tenant, fixture("header_match.json"))

    message = EmailMessage.objects.get(direction="inbound")
    assert message.thread == known["thread"]
    assert message.matched_by == inbound.BY_HEADER


# ------------------------------------------------------------------- AC-6.3

@pytest.mark.django_db
def test_ac_6_3_a_known_sender_is_matched_by_address(
    seeded_tenant, known, in_tenant_a
):
    """Fourth and last rule. A new conversation from somebody we know is
    theirs, and gets its own thread rather than being forced into an old one."""
    inbound.ingest_thread(seeded_tenant, fixture("sender_fallback.json"))

    message = EmailMessage.objects.get(direction="inbound")
    assert message.contact == known["contact"]
    assert message.matched_by == inbound.BY_SENDER
    assert message.thread != known["thread"]
    assert EmailThread.objects.count() == 2


# ------------------------------------------------------------------- AC-6.4

@pytest.mark.django_db
def test_ac_6_4_no_match_is_queued_and_never_dropped(
    seeded_tenant, known, in_tenant_a
):
    """**Stored, not logged.** The thing a person files has to still exist
    when they get to it, and it has to say why it could not be placed."""
    counts = inbound.ingest_thread(seeded_tenant, fixture("no_match.json"))

    assert counts["unmatched"] == 1
    row = UnmatchedInbound.objects.get()
    assert row.state == UnmatchedInbound.State.PENDING
    assert row.from_address == "nobody@elsewhere.invalid"
    assert row.body_stripped.startswith("Forwarding this on")
    assert "no contact holds nobody@elsewhere.invalid" in row.reason
    assert row.raw                                    # the whole payload, kept
    assert not EmailMessage.objects.filter(direction="inbound").exists()


@pytest.mark.django_db
def test_ac_6_4_filing_moves_it_onto_the_contacts_timeline(
    seeded_tenant, known, api, in_tenant_a
):
    ff = MembershipFactory(tenant=seeded_tenant, role="FF")
    inbound.ingest_thread(seeded_tenant, fixture("no_match.json"))
    row = UnmatchedInbound.objects.get()

    response = api.as_(ff).post(f"/api/unmatched-inbound/{row.pk}/file/", {
        "contact": str(known["contact"].pk), "add_address": True})

    assert response.status_code == 201, response.data
    row.refresh_from_db()
    assert row.state == UnmatchedInbound.State.FILED
    message = EmailMessage.objects.get(pk=response.data["message"])
    assert message.contact == known["contact"]
    assert message.matched_by == "filed_by_hand"
    # FR-6.8 — optionally teaching the CRM the address, so the *next* reply
    # from it matches itself.
    assert known["contact"].emails.filter(
        address="nobody@elsewhere.invalid").exists()


@pytest.mark.django_db
def test_filing_the_same_message_twice_is_refused(
    seeded_tenant, known, api, in_tenant_a
):
    ff = MembershipFactory(tenant=seeded_tenant, role="FF")
    inbound.ingest_thread(seeded_tenant, fixture("no_match.json"))
    row = UnmatchedInbound.objects.get()
    body = {"contact": str(known["contact"].pk)}

    assert api.as_(ff).post(f"/api/unmatched-inbound/{row.pk}/file/",
                            body).status_code == 201
    assert api.as_(ff).post(f"/api/unmatched-inbound/{row.pk}/file/",
                            body).status_code == 409
    assert EmailMessage.objects.filter(direction="inbound").count() == 1


# ------------------------------------------------------------------- AC-6.5

@pytest.mark.django_db
def test_ac_6_5_a_re_poll_creates_no_duplicate(seeded_tenant, known, in_tenant_a):
    """FR-6.12. **Every poll re-reads the whole thread**, so this is the
    normal case, not an edge one."""
    inbound.ingest_thread(seeded_tenant, fixture("thread_id_match.json"))
    counts = inbound.ingest_thread(seeded_tenant, fixture("repoll.json"))

    assert counts["already_had"] == 1
    assert counts["matched"] == 0
    assert EmailMessage.objects.filter(direction="inbound").count() == 1


@pytest.mark.django_db
def test_an_unmatched_message_is_not_re_queued_on_the_next_poll(
    seeded_tenant, known, in_tenant_a
):
    """The queue must not grow by one every fifteen minutes."""
    inbound.ingest_thread(seeded_tenant, fixture("no_match.json"))
    inbound.ingest_thread(seeded_tenant, fixture("no_match.json"))

    assert UnmatchedInbound.objects.count() == 1


@pytest.mark.django_db
def test_our_own_sent_message_is_not_ingested_as_a_reply(
    seeded_tenant, known, in_tenant_a
):
    """A thread contains what we sent as well as what came back. Recognised by
    the Message-ID we issued, not by the From address: a CF sending from their
    own mailbox is still us."""
    payload = {"id": "gmail-thread-1", "messages": [{
        "id": "m-sent-1", "threadId": "gmail-thread-1",
        "payload": {"headers": [
            {"name": "From", "value": "info@x.test"},
            {"name": "Message-ID", "value": f"<{TOKEN}.abc123@x.test>"}], "parts": []},
    }]}

    counts = inbound.ingest_thread(seeded_tenant, payload)

    assert counts["skipped_outbound"] == 1
    assert EmailMessage.objects.filter(direction="inbound").count() == 0


# ------------------------------------------------------------------- AC-6.6

@pytest.mark.django_db
def test_ac_6_6_quoted_history_is_trimmed_for_display_and_kept_whole(
    seeded_tenant, known, api, in_tenant_a
):
    """Trimming is a display decision, so it is never allowed to be lossy."""
    ff = MembershipFactory(tenant=seeded_tenant, role="FF")
    inbound.ingest_thread(seeded_tenant, fixture("quoted_history.json"))
    message = EmailMessage.objects.get(direction="inbound")

    assert message.body_stripped == "Thanks Bryan — Friday works. I'll bring the margin numbers."
    assert "progress report" in message.body_text      # the whole thing is kept
    assert "On Mon, 22 Sep 2026" not in message.body_stripped

    shown = api.as_(ff).get(f"/api/email-threads/{message.thread_id}/").data
    assert shown["messages"][-1]["body"] == message.body_stripped
    assert shown["messages"][-1]["has_more"] is True

    whole = api.as_(ff).get(f"/api/email-threads/{message.pk}/raw/").data
    assert "> Here is this week's progress report." in whole["body_text"]


@pytest.mark.parametrize("text,expected", [
    ("Yes please.\n\nOn Mon, 1 Jan 2026 at 09:00, A B <a@b.test> wrote:\n> old",
     "Yes please."),
    ("Agreed.\n\n-----Original Message-----\nFrom: someone", "Agreed."),
    ("Sure.\n\n-- \nDana Reyes\nCOO", "Sure."),
    ("Nothing quoted here.", "Nothing quoted here."),
    ("", ""),
])
def test_trimming_is_conservative(text, expected):
    """A missed quote is untidy; an over-eager one hides what somebody wrote.
    The raw message is kept either way, so the bias is deliberate."""
    assert inbound.strip_quoted(text) == expected


# ------------------------------------------------------------------- AC-6.7

@pytest.mark.django_db
def test_ac_6_7_authenticity_comes_from_the_transport(seeded_tenant, api, in_tenant_a):
    """**There is no webhook to forge.** AC-6.7 was written for the Postmark
    design; under polling there is no unauthenticated way in at all, and the
    thing to assert is the absence of the endpoint."""
    from django.urls import NoReverseMatch, reverse

    for name in ("inbound-webhook", "postmark-inbound"):
        with pytest.raises(NoReverseMatch):
            reverse(name)
    # And the read surface refuses an unauthenticated caller outright.
    from django.test import Client

    assert Client().get("/api/unmatched-inbound/").status_code in (401, 403)


# ------------------------------------------------------------ attachments

@pytest.mark.django_db
def test_an_attachment_is_stored_and_listed(seeded_tenant, known, api, in_tenant_a):
    ff = MembershipFactory(tenant=seeded_tenant, role="FF")
    inbound.ingest_thread(seeded_tenant, fixture("attachment.json"))
    message = EmailMessage.objects.get(direction="inbound")

    attachment = message.attachments.get()
    assert attachment.filename == "q3-margin.csv"
    assert attachment.byte_size > 0

    shown = api.as_(ff).get(f"/api/email-threads/{message.thread_id}/").data
    assert shown["messages"][-1]["attachments"][0]["filename"] == "q3-margin.csv"


@pytest.mark.django_db
def test_an_oversized_attachment_is_named_rather_than_dropped(
    seeded_tenant, known, in_tenant_a
):
    """FR-6.10. Silence is the failure mode this module is built against."""
    payload = fixture("attachment.json")
    part = payload["messages"][0]["payload"]["parts"][-1]
    part["body"]["size"] = inbound.MAX_ATTACHMENT_BYTES + 1

    inbound.ingest_thread(seeded_tenant, payload)

    message = EmailMessage.objects.get(direction="inbound")
    assert message.attachments.count() == 0
    assert "was not stored" in message.body_stripped
    assert "q3-margin.csv" in message.body_stripped


# ----------------------------------------------------------- the poll itself

@pytest.mark.django_db
def test_ac_6_15_polling_reads_only_threads_the_app_started(
    seeded_tenant, known, in_tenant_a
):
    """FR-6 out-of-scope 1, and the boundary the consent screen promises.

    `gmail.readonly` grants the whole mailbox; the app asks only for thread
    ids it stored itself, and that is enforced here rather than by Google.
    """
    client = FakeGmail({"gmail-thread-1": fixture("thread_id_match.json")})

    inbound_poll.poll(seeded_tenant, client=client)

    assert client.asked == ["gmail-thread-1"]
    assert EmailMessage.objects.filter(direction="inbound").count() == 1
    known["thread"].refresh_from_db()
    assert known["thread"].last_polled_at is not None


@pytest.mark.django_db
def test_ac_6_16_downtime_is_ingested_on_the_next_run_with_no_resync(
    seeded_tenant, known, in_tenant_a
):
    """A fortnight of a closed laptop. The cursor is "which thread did we look
    at least recently", which cannot expire — a Gmail historyId can."""
    from datetime import timedelta

    from django.utils import timezone

    known["thread"].last_polled_at = timezone.now() - timedelta(days=14)
    known["thread"].save(update_fields=["last_polled_at"])
    # Two replies landed while the app was off.
    payload = fixture("thread_id_match.json")
    payload["messages"] += fixture("quoted_history.json")["messages"]
    client = FakeGmail({"gmail-thread-1": payload})

    first = inbound_poll.poll(seeded_tenant, client=client)
    second = inbound_poll.poll(seeded_tenant, client=client)

    assert first["matched"] == 2
    assert second["already_had"] == 2 and second["matched"] == 0
    assert EmailMessage.objects.filter(direction="inbound").count() == 2


@pytest.mark.django_db
def test_a_thread_that_fails_keeps_its_place_and_does_not_stop_the_run(
    seeded_tenant, known, in_tenant_a
):
    """One deleted conversation must not hold up the other forty."""
    client = FakeGmail()
    client.fail = "Gmail would not return that thread (503)."

    report = inbound_poll.poll(seeded_tenant, client=client)

    assert report["errors"] == 1
    known["thread"].refresh_from_db()
    assert known["thread"].poll_error.startswith("Gmail would not return")
    # The cursor did NOT move, so the next run tries this one again.
    assert known["thread"].last_polled_at is None


@pytest.mark.django_db
def test_ac_6_17_a_connection_without_the_read_scope_says_so(
    seeded_tenant, in_tenant_a
):
    """A mailbox that sends perfectly well and cannot be read. The two halves
    fail separately, so the message names the half."""
    from .factories import GmailConnectionFactory

    GmailConnectionFactory(tenant=seeded_tenant,
                           scopes=["https://www.googleapis.com/auth/gmail.send"])

    with pytest.raises(inbound_poll.NotConnected) as refused:
        inbound_poll.poll(seeded_tenant)

    assert "has not granted permission to read mail" in str(refused.value)


@pytest.mark.django_db
def test_the_read_scope_is_asked_for_separately_from_sending(seeded_tenant):
    """A practice that never collects replies should never be asked to let the
    app read its mail."""
    from apps.crm.services import gmail_oauth

    assert gmail_oauth.TIER2_SCOPES[0] not in gmail_oauth.scopes_for()
    assert gmail_oauth.TIER2_SCOPES[0] in gmail_oauth.scopes_for(inbound=True)
    assert "https://www.googleapis.com/auth/gmail.send" in \
        gmail_oauth.scopes_for(inbound=True)


# ------------------------------------------------------------- the replay path

@pytest.mark.django_db
def test_every_fixture_replays_through_the_command(seeded_tenant, known, in_tenant_a):
    """FR-6.14/6.15 — the eight fixtures **are** the regression suite, and the
    command a person runs is the path they run through."""
    from io import StringIO

    from django.core.management import call_command

    names = sorted(p.name for p in FIXTURES.glob("*.json"))
    assert names == ["attachment.json", "header_match.json", "in_reply_to_match.json",
                     "no_match.json", "quoted_history.json", "repoll.json",
                     "sender_fallback.json", "thread_id_match.json"]

    out = StringIO()
    call_command("replay_inbound", *[str(FIXTURES / n) for n in names],
                 tenant=seeded_tenant.slug, apply=True, stdout=out)
    printed = out.getvalue()

    for name in names:
        assert name in printed
    assert "1 unmatched" in printed
    assert "1 already had" in printed          # repoll.json, replayed after the first


@pytest.mark.django_db
def test_a_replay_keeps_nothing_unless_asked(seeded_tenant, known, in_tenant_a):
    """It writes rows, and the development database holds the practice's real
    contacts and real threads. A default that leaves seven invented replies in
    somebody's queue is a default that is wrong."""
    from io import StringIO

    from django.core.management import call_command

    out = StringIO()
    call_command("replay_inbound", str(FIXTURES / "no_match.json"),
                 tenant=seeded_tenant.slug, stdout=out)

    assert "Dry run" in out.getvalue()
    assert UnmatchedInbound.objects.count() == 0
