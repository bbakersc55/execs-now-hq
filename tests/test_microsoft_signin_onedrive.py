"""Sign in with Microsoft, and meeting notes from OneDrive (2026-10-27;
docs/m365_transport.md D1, D2, §§9–10).

The mandatory families: tenant isolation (a sign-in lands only in the
signer's own practice; a OneDrive folder is read through that practice's own
connection and recorded there) and role boundaries (staff only, no sign-ups;
the folder is the practice owner's to choose). Then that **Google sign-in and
Drive polling are unchanged**.

Microsoft's network is the fake from `test_microsoft_transport`, answering
from `tests/fixtures/graph/`. Nothing here was checked against a real tenant.
"""

from __future__ import annotations

import base64
import io
import json
from datetime import datetime, timezone as dt_timezone
from urllib.parse import parse_qs, urlparse

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.crm.models import MicrosoftConnection
from apps.crm.services import microsoft_oauth
from apps.meetings import drive, ingest, onedrive
from apps.meetings.models import DriveWatch, MeetingSourceFile
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Role

from . import registry_config  # noqa: F401
from .factories import DriveWatchFactory, MembershipFactory, TenantFactory
from .test_microsoft_transport import (  # noqa: F401 - `ms` is a fixture
    FIXTURES, OWN, Reply, _connect, fixture, ms, ms_practice,
)

DIRECTORY = "9188040d-6c67-4c5b-b112-36a304b66dad"
ACCOUNT = "87d349ed-44d7-43e1-9a83-5f2406dee5bd"
MEETINGS = "01MEETAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
CLIENTS = "01SUBFAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
SETTLED = datetime(2026, 10, 27, 17, 0, tzinfo=dt_timezone.utc)
WRITING = datetime(2026, 10, 27, 16, 10, tzinfo=dt_timezone.utc)


def signin_token(tid=DIRECTORY, oid=ACCOUNT):
    def part(data):
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    claims = {"aud": "client-id", "tid": tid, "oid": oid, "ver": "2.0",
              "preferred_username": OWN, "email": OWN}
    return dict(fixture("token_signin.json"),
                id_token=".".join([part({"alg": "none"}), part(claims), "unsigned"]))


def raw(name):
    return (FIXTURES / name).read_bytes()


def a_docx(*lines):
    from docx import Document

    document = Document()
    for line in lines:
        document.add_paragraph(line)
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


# ============================================================ sign-in

@pytest.fixture
def ms_staff(ms_practice, ff):
    ff.user.email = OWN
    ff.user.save()
    return ff


def _sign_in(client, ms, *, token=None, me=None, organization=None, email=OWN):
    ms.on("POST", "/oauth2/v2.0/token", Reply(payload=token or signin_token()))
    ms.on("GET", "/v1.0/me", Reply(payload=me or fixture("me_signin.json")))
    ms.on("GET", "/v1.0/organization", Reply(payload=organization
                                              or fixture("organization.json")))
    started = client.get("/accounts/microsoft/start", {"email": email})
    state = parse_qs(urlparse(started["Location"]).query)["state"][0]
    return client.get("/accounts/microsoft/callback", {"code": "c", "state": state})


def _signed_in_as(client):
    return client.session.get("_auth_user_id")


@pytest.mark.django_db
def test_start_goes_to_microsoft_with_the_address_as_the_hint(ms, client):
    response = client.get("/accounts/microsoft/start", {"email": "Bryan@Contoso.example"})
    url = urlparse(response["Location"])
    query = parse_qs(url.query)
    assert url.netloc == "login.microsoftonline.com"
    assert url.path == "/organizations/oauth2/v2.0/authorize"
    assert query["login_hint"] == ["bryan@contoso.example"]
    assert query["scope"][0].split() == ["openid", "email", "profile", "User.Read"]
    assert query["redirect_uri"][0].endswith("/accounts/microsoft/callback")


@pytest.mark.django_db
def test_start_without_the_registration_refuses(client, settings):
    settings.MICROSOFT_CLIENT_ID = ""
    response = client.get("/accounts/microsoft/start", {"email": OWN})
    assert response["Location"].endswith("/accounts/refused")


@pytest.mark.django_db
def test_staff_of_a_microsoft_practice_signs_in(ms_staff, ms, client):
    response = _sign_in(client, ms)
    assert response.status_code == 302 and not response["Location"].endswith("/refused")
    assert _signed_in_as(client) == str(ms_staff.user_id)
    user = User.objects.get(pk=ms_staff.user_id)
    assert (user.microsoft_directory_id, user.microsoft_object_id) == (DIRECTORY, ACCOUNT)
    assert user.last_login_at is not None
    # Nothing is kept from a sign-in: no connection, no token.
    assert not MicrosoftConnection.all_objects.exists()


@pytest.mark.django_db
def test_an_address_its_directory_has_not_verified_is_not_believed(ms_staff, ms, client):
    """nOAuth: another directory's admin puts our address on their user."""
    response = _sign_in(client, ms, organization=fixture("organization_other.json"),
                        token=signin_token(tid="72f988bf-0000-0000-0000-2d7cd011db47"))
    assert response["Location"].endswith("/accounts/refused")
    assert _signed_in_as(client) is None


@pytest.mark.django_db
def test_nobody_is_signed_up(ms_practice, ms, client):
    response = _sign_in(client, ms)
    assert response["Location"].endswith("/accounts/refused")
    assert not User.objects.filter(email__iexact=OWN).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("why", ["google practice", "archived", "revoked", "client user",
                                 "inactive"])
def test_only_live_staff_of_a_live_microsoft_practice(why, ms_staff, ms, client):
    tenant = ms_staff.tenant
    if why == "google practice":
        tenant.mail_provider = "google"
        tenant.save()
    elif why == "archived":
        tenant.status = "archived"
        tenant.save()
    elif why == "revoked":
        ms_staff.revoked_at = timezone.now()
        ms_staff.save()
    elif why == "client user":
        from .factories import ClientCompanyFactory

        ms_staff.role = Role.FCC
        ms_staff.client_company = ClientCompanyFactory(tenant=tenant)
        ms_staff.save()
    else:
        ms_staff.user.is_active = False
        ms_staff.user.save()
    response = _sign_in(client, ms)
    assert response["Location"].endswith("/accounts/refused")
    assert _signed_in_as(client) is None


@pytest.mark.django_db
def test_a_different_work_account_with_the_same_address_is_refused(ms_staff, ms, client):
    ms_staff.user.microsoft_directory_id = DIRECTORY
    ms_staff.user.microsoft_object_id = "someone-else"
    ms_staff.user.save()
    response = _sign_in(client, ms)
    assert response["Location"].endswith("/accounts/refused")
    assert _signed_in_as(client) is None


@pytest.mark.django_db
def test_two_people_behind_one_account_is_refused(ms_staff, ms, client):
    """Its mailbox address is one member and its sign-in name another."""
    other = MembershipFactory(tenant=ms_staff.tenant, role=Role.CF)
    other.user.email = "casey@contoso.example"
    other.user.save()
    me = dict(fixture("me_signin.json"), userPrincipalName="casey@contoso.example")
    response = _sign_in(client, ms, me=me)
    assert response["Location"].endswith("/accounts/refused")


@pytest.mark.django_db
def test_a_sign_in_lands_in_the_signers_own_practice(ms_staff, ms, client):
    """Isolation: another Microsoft practice's member with another address is
    untouched, and the session is this user's."""
    other = TenantFactory(name="Other", slug="other-signin", mail_provider="microsoft")
    theirs = MembershipFactory(tenant=other, role=Role.FF)
    _sign_in(client, ms)
    assert _signed_in_as(client) == str(ms_staff.user_id) != str(theirs.user_id)
    theirs.user.refresh_from_db()
    assert theirs.user.microsoft_object_id == ""


@pytest.mark.django_db
def test_a_mail_connection_on_the_same_redirect_is_not_a_sign_in(ms_practice, ff, api, ms):
    """The two share the registration's redirect URI and are told apart by
    their state: a mail connect still connects mail."""
    ms.on("POST", "/oauth2/v2.0/token", [Reply(payload=fixture("token.json")),
                                         Reply(payload=fixture("refreshed.json"))])
    client = api.as_(ff)
    session = client.session
    session[microsoft_oauth.STATE_SESSION_KEY] = "st"
    session.save()
    response = client.get("/accounts/microsoft/callback", {"code": "c", "state": "st"})
    assert "ms_connected" in response["Location"]
    assert MicrosoftConnection.all_objects.filter(user=ff.user).exists()


@pytest.mark.django_db
def test_the_sign_in_page_offers_microsoft_only_where_it_applies(ms_practice, ms, client,
                                                                settings):
    assert client.get("/api/branding").json()["microsoft_sign_in"] is True
    settings.MICROSOFT_CLIENT_ID = ""
    assert client.get("/api/branding").json()["microsoft_sign_in"] is False


@pytest.mark.django_db
def test_no_microsoft_practice_no_microsoft_button(seeded_tenant, ms, client):
    assert client.get("/api/branding").json()["microsoft_sign_in"] is False


# ---------------------------------------------------- Google sign-in unchanged

@pytest.mark.django_db
def test_google_start_is_unchanged_for_every_kind_of_address(ms_staff, client):
    """A Microsoft practice's member, an unknown address and a Workspace one
    all get Google's Workspace sign-in from Google's start, as before (now at
    Google's chooser directly, the address as its hint)."""
    from urllib.parse import parse_qs, urlparse

    for email in (OWN, "nobody@nowhere.example", "bryan.baker@getexecutivesnow.com"):
        location = client.get("/accounts/google/start", {"email": email})["Location"]
        params = {k: v[0] for k, v in parse_qs(urlparse(location).query).items()}
        assert location.startswith("https://accounts.google.com/")
        assert params["redirect_uri"].endswith("/accounts/google/login/callback/")
        assert params["login_hint"] == email


@pytest.mark.django_db
def test_google_sign_in_still_admits_a_google_practices_staff(seeded_tenant, ff, rf):
    """The invite-only adapter decides as before; the Microsoft binding
    columns do not enter into it."""
    from unittest import mock

    from apps.accounts.adapters import InviteOnlySocialAdapter

    login = mock.Mock(is_existing=False, email_addresses=[
        mock.Mock(verified=True, email=ff.user.email)])
    request = rf.get("/")
    InviteOnlySocialAdapter().pre_social_login(request, login)
    login.connect.assert_called_once_with(request, ff.user)


# ============================================================ OneDrive notes

def _drive(fake):
    fake.on("GET", "/me/drive/root", Reply(payload=fixture("drive_root.json")))
    fake.on("GET", "/me/drive/root/children", Reply(payload=fixture("drive_root_children.json")))
    fake.on("GET", f"/me/drive/items/{MEETINGS}", Reply(payload=fixture("meetings_folder.json")))
    fake.on("GET", f"/me/drive/items/{MEETINGS}/children",
            Reply(payload=fixture("meetings_children.json")))
    fake.on("GET", f"/me/drive/items/{CLIENTS}/children",
            Reply(payload=fixture("clients_children.json")))
    fake.on("GET", "/me/drive/root/delta", Reply(payload=fixture("delta_latest.json")))
    fake.on("GET", "delta?token=LATEST1", Reply(payload=fixture("delta_page.json")))


@pytest.fixture
def onedrive_practice(ms_practice, ff, ms):
    _connect(ms_practice, ff, read=True)
    MicrosoftConnection.all_objects.filter(user=ff.user).update(
        scopes=["Mail.Send", "Mail.ReadBasic", "User.Read", "Mail.Read", "Files.Read"])
    _drive(ms)
    return ms_practice


def _client(tenant, now=SETTLED):
    with tenant_context(tenant.pk):
        connection = ingest.drive_connection(tenant)
    return onedrive.OneDriveClient(connection, now=now)


@pytest.mark.django_db
def test_a_microsoft_practice_reads_onedrive_and_a_google_one_drive(onedrive_practice, ms):
    with tenant_context(onedrive_practice.pk):
        assert isinstance(ingest.client_for(onedrive_practice), onedrive.OneDriveClient)
    google = TenantFactory(name="G", slug="g-practice")
    from .factories import GmailConnectionFactory

    GmailConnectionFactory(tenant=google, user=MembershipFactory(tenant=google, role="FF").user,
                           scopes=["https://www.googleapis.com/auth/drive.readonly"])
    with tenant_context(google.pk):
        assert isinstance(ingest.client_for(google), drive.DriveClient)


@pytest.mark.django_db
def test_without_files_read_the_queue_says_what_to_allow(ms_practice, ff, ms):
    _connect(ms_practice, ff)
    with tenant_context(ms_practice.pk), \
            pytest.raises(ingest.NotConnected, match="Allow OneDrive access"):
        ingest.client_for(ms_practice)


@pytest.mark.django_db
def test_the_picker_lists_folders(onedrive_practice, ff, api):
    root = api.as_(ff).get("/api/drive-watch/onedrive-folders/").json()
    assert root["is_root"] is True and root["name"] == "OneDrive"
    assert [f["name"] for f in root["folders"]] == ["Documents", "Meetings"]
    assert root["files"] == 1 and root["readable"] == 0
    meetings = api.as_(ff).get("/api/drive-watch/onedrive-folders/",
                               {"folder": MEETINGS}).json()
    assert meetings["path"] == ["Meetings"] and meetings["parent_id"].startswith("01ROOT")
    assert meetings["readable"] == 2 and meetings["files"] == 3
    assert [f["name"] for f in meetings["folders"]] == ["Clients"]


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["CF", "VA"])
def test_only_the_practice_owner_browses_and_chooses(role, onedrive_practice, api):
    member = MembershipFactory(tenant=onedrive_practice, role=role)
    assert api.as_(member).get("/api/drive-watch/onedrive-folders/").status_code == 403
    assert api.as_(member).post("/api/drive-watch/", {"folder": MEETINGS}).status_code == 403


@pytest.mark.django_db
def test_clients_never_reach_the_picker(onedrive_practice, fcc, api):
    assert api.as_(fcc).get("/api/drive-watch/onedrive-folders/").status_code == 403


@pytest.mark.django_db
def test_a_google_practice_has_no_onedrive_picker(seeded_tenant, ff, api):
    assert api.as_(ff).get("/api/drive-watch/onedrive-folders/").status_code == 409


@pytest.mark.django_db
def test_choosing_a_folder_watches_it_on_onedrive(onedrive_practice, ff, api):
    checked = api.as_(ff).post("/api/drive-watch/check/", {"folder": MEETINGS},
                               content_type="application/json").json()
    assert checked["name"] == "Meetings" and checked["readable"] == 3
    assert checked["in_subfolders"] == 1
    body = api.as_(ff).post("/api/drive-watch/", {"folder": MEETINGS},
                            content_type="application/json").json()
    assert body["provider"] == "microsoft" and body["connected"] is True
    watch = DriveWatch.all_objects.get(tenant=onedrive_practice)
    assert (watch.provider, watch.folder_id, watch.page_token) == ("microsoft", MEETINGS, "")


@pytest.mark.django_db
def test_a_pasted_link_is_not_a_onedrive_folder(onedrive_practice, ff, api):
    response = api.as_(ff).post("/api/drive-watch/check/",
                                {"folder": "https://contoso-my.sharepoint.com/:f:/g/x y"},
                                content_type="application/json")
    assert response.status_code == 400


@pytest.mark.django_db
def test_a_google_watch_is_not_read_after_moving_to_microsoft(ms_practice, ms):
    DriveWatchFactory(tenant=ms_practice, folder_id="google-folder", provider="google")
    with tenant_context(ms_practice.pk):
        assert ingest.watch_for(ms_practice) is None
        with pytest.raises(ingest.NotConnected, match="No folder is being watched"):
            ingest.poll(ms_practice, parse=False)


@pytest.mark.django_db
def test_a_poll_records_the_new_notes_and_moves_the_cursor(onedrive_practice, ms):
    watch = DriveWatchFactory(tenant=onedrive_practice, folder_id=MEETINGS,
                              provider="microsoft", page_token="")
    with tenant_context(onedrive_practice.pk):
        report = ingest.poll(onedrive_practice, client=_client(onedrive_practice),
                             parse=False)
        rows = {r.name: r for r in MeetingSourceFile.objects.all()}

    assert sorted(r.name for r in report["recorded"]) == [
        "Acme weekly 2026-10-27.vtt", "Pipeline review 2026-10-27 Meeting notes.loop"]
    assert [r.name for r in report["skipped"]] == ["Handout.pdf"]
    assert "Personal plan 2026-10-27.docx" not in rows       # outside the folder
    loop = rows["Pipeline review 2026-10-27 Meeting notes.loop"]
    assert loop.provider == "microsoft" and loop.drive_version == '"c:{NEWLOOP},4"'
    assert loop.drive_file_owner_email == OWN
    assert loop.web_view_link == "https://contoso-my.sharepoint.com/new-loop"
    assert rows["Handout.pdf"].skip_reason.startswith("A PDF is not read yet")
    watch.refresh_from_db()
    assert watch.page_token == "https://graph.microsoft.com/v1.0/me/drive/root/delta?token=NEXT2"


@pytest.mark.django_db
def test_notes_still_being_written_hold_the_cursor(onedrive_practice, ms):
    """The Loop page was edited five minutes ago: nothing is recorded yet, and
    the cursor stays, so the next poll sees it finished."""
    watch = DriveWatchFactory(tenant=onedrive_practice, folder_id=MEETINGS,
                              provider="microsoft",
                              page_token="https://graph.microsoft.com/v1.0/me/drive/root/delta?token=LATEST1")
    with tenant_context(onedrive_practice.pk):
        report = ingest.poll(onedrive_practice, client=_client(onedrive_practice, WRITING),
                             parse=False)
        assert not MeetingSourceFile.objects.exists()
    assert report["recorded"] == [] and report["error"] == ""
    watch.refresh_from_db()
    assert watch.page_token.endswith("token=LATEST1")


@pytest.mark.django_db
def test_a_second_poll_records_nothing_twice(onedrive_practice, ms):
    DriveWatchFactory(tenant=onedrive_practice, folder_id=MEETINGS, provider="microsoft",
                      page_token="https://graph.microsoft.com/v1.0/me/drive/root/delta?token=LATEST1")
    ms.on("GET", "delta?token=NEXT2", Reply(payload=fixture("delta_page.json")))
    with tenant_context(onedrive_practice.pk):
        ingest.poll(onedrive_practice, client=_client(onedrive_practice), parse=False)
        again = ingest.poll(onedrive_practice, client=_client(onedrive_practice), parse=False)
        assert MeetingSourceFile.objects.count() == 3
    assert again["recorded"] == []


@pytest.mark.django_db
def test_notes_edited_after_they_were_read_are_not_read_twice(onedrive_practice, ms):
    from .factories import MeetingSourceFileFactory

    MeetingSourceFileFactory(tenant=onedrive_practice, provider="microsoft",
                             drive_file_id="01NEWLOOPAAAAAAAAAAAAAAAAAAAAAAAAA",
                             drive_version='"c:{NEWLOOP},2"', state="parsed",
                             name="Pipeline review 2026-10-27 Meeting notes.loop")
    DriveWatchFactory(tenant=onedrive_practice, folder_id=MEETINGS, provider="microsoft",
                      page_token="https://graph.microsoft.com/v1.0/me/drive/root/delta?token=LATEST1")
    with tenant_context(onedrive_practice.pk):
        report = ingest.poll(onedrive_practice, client=_client(onedrive_practice), parse=False)
        later = MeetingSourceFile.objects.get(drive_version='"c:{NEWLOOP},4"')
    assert later.state == "skipped" and later.skip_reason.startswith("Changed after it was read")
    assert later in report["skipped"]


@pytest.mark.django_db
def test_the_folder_import_lists_oldest_first(onedrive_practice, ms):
    client = _client(onedrive_practice)
    with tenant_context(onedrive_practice.pk):
        found = client.files_in([MEETINGS, CLIENTS])
    assert [f.name for f in found] == [
        "Weekly ops sync 2026-10-20 Meeting notes.loop", "Dunder Mifflin review 2026-10-21.docx",
        "Slides.pdf", "Acme kickoff 2026-10-22.vtt"]
    assert found[2].skip.startswith("A PDF")


@pytest.mark.django_db
def test_a_loop_page_is_read_from_graphs_html(onedrive_practice, ms):
    ms.on("GET", "/content", Reply(content=raw("meeting_notes.html")))
    client = _client(onedrive_practice)
    text = client.text_of(drive.DriveFile(file_id="01NEWLOOP", version="1",
                                          name="Pipeline review Meeting notes.loop",
                                          mime_type=""))
    assert ms.calls[-1]["params"] == {"format": "html"}
    assert text.splitlines() == [
        "Pipeline review Meeting notes", "Pipeline review", "Attendees: Bryan Baker, Dana Reyes",
        "Notes", "- Acme wants the onboarding plan by Friday",
        "- Hiring plan needs a second look", "Follow-up tasks",
        "Send onboarding plan | Bryan Baker | Oct 31"]


@pytest.mark.django_db
def test_a_transcript_is_read_as_who_said_what(onedrive_practice, ms):
    ms.on("GET", "/content", Reply(content=raw("transcript.vtt")))
    text = _client(onedrive_practice).text_of(drive.DriveFile(
        file_id="01VTT", version="1", name="Acme weekly.vtt", mime_type="text/vtt"))
    assert text.splitlines() == [
        "Bryan Baker: Thanks for joining. Let's start with the hiring plan. "
        "I'll send the revised plan by Friday.",
        "Dana Reyes: Great, and we need the onboarding checklist too."]


@pytest.mark.django_db
def test_a_word_document_is_read(onedrive_practice, ms):
    ms.on("GET", "/content", Reply(content=a_docx("Dunder Mifflin review",
                                                  "Michael will send the overtime numbers.")))
    text = _client(onedrive_practice).text_of(drive.DriveFile(
        file_id="01DOCX", version="1", name="Review.docx", mime_type=drive.DOCX))
    assert text == "Dunder Mifflin review\nMichael will send the overtime numbers."


@pytest.mark.django_db
def test_notes_read_from_onedrive_become_the_same_proposals(onedrive_practice, ms, fake_claude):
    """The parse is Google's: the same prompt and the same proposal, here
    from a Loop page's text."""
    from apps.meetings import parsing

    ms.on("GET", "/content", Reply(content=raw("meeting_notes.html")))
    fake_claude.reply = json.dumps({
        "title": "Pipeline review", "meeting_date": "2026-10-27",
        "summary": "The onboarding plan is due Friday.", "participants": [],
        "action_items": [{"text": "Send onboarding plan", "owner": "Bryan Baker",
                          "due_date": "2026-10-31", "excerpt": "Send onboarding plan"}]})
    with tenant_context(onedrive_practice.pk):
        row = MeetingSourceFile.objects.create(
            tenant=onedrive_practice, provider="microsoft", drive_file_id="01NEWLOOP",
            drive_version="1", name="Pipeline review 2026-10-27 Meeting notes.loop",
            mime_type="application/octet-stream", state="recorded")
        proposal = parsing.parse(row, client=_client(onedrive_practice))
        assert proposal is not None and proposal.title == "Pipeline review"
        assert [i.source_excerpt for i in proposal.items.filter(kind="action_item")] \
            == ["Send onboarding plan"]
    assert "Acme wants the onboarding plan by Friday" in row.text


@pytest.mark.django_db
def test_another_practices_onedrive_is_never_used(onedrive_practice, ms):
    """Isolation: a second Microsoft practice whose owner granted Files.Read
    has its own connection; this practice's client is never built on it."""
    other = TenantFactory(name="Other", slug="other-onedrive", mail_provider="microsoft")
    theirs = _connect(other, MembershipFactory(tenant=other, role="FF"))
    MicrosoftConnection.all_objects.filter(pk=theirs.pk).update(scopes=["Files.Read"])
    with tenant_context(onedrive_practice.pk):
        mine = ingest.drive_connection(onedrive_practice)
    assert mine.tenant_id == onedrive_practice.pk and mine.pk != theirs.pk
    with tenant_context(other.pk):
        assert ingest.drive_connection(other).pk == theirs.pk


@pytest.mark.django_db
def test_files_recorded_belong_to_the_polled_practice(onedrive_practice, ms):
    other = TenantFactory(name="Other", slug="other-onedrive-2", mail_provider="microsoft")
    DriveWatchFactory(tenant=onedrive_practice, folder_id=MEETINGS, provider="microsoft",
                      page_token="https://graph.microsoft.com/v1.0/me/drive/root/delta?token=LATEST1")
    with tenant_context(onedrive_practice.pk):
        ingest.poll(onedrive_practice, client=_client(onedrive_practice), parse=False)
    assert set(MeetingSourceFile.all_objects.values_list("tenant_id", flat=True)) \
        == {onedrive_practice.pk}
    assert not MeetingSourceFile.all_objects.filter(tenant=other).exists()


# ------------------------------------------------- allowing OneDrive access

@pytest.mark.django_db
def test_allowing_onedrive_asks_for_files_and_keeps_replies(ms_practice, ff, api, ms):
    _connect(ms_practice, ff, read=True)
    url = api.as_(ff).post("/api/drive-watch/consent/").json()["authorization_url"]
    scopes = parse_qs(urlparse(url).query)["scope"][0].split()
    assert "Files.Read" in scopes and "Mail.Read" in scopes and "Mail.Send" in scopes


@pytest.mark.django_db
def test_onedrive_consent_returns_to_the_queue_and_keeps_the_address_check(
        ms_practice, ff, api, ms):
    connection = _connect(ms_practice, ff)
    passed = connection.send_as_verified_at
    ms.on("POST", "/oauth2/v2.0/token", Reply(payload=dict(
        fixture("token.json"), scope="Mail.ReadBasic Mail.Send User.Read Files.Read")))
    ms.on("GET", "/v1.0/me", Reply(payload=dict(fixture("me.json"), mail=connection.email_address)))
    client = api.as_(ff)
    client.post("/api/drive-watch/consent/")
    state = client.session[microsoft_oauth.STATE_SESSION_KEY]
    response = client.get("/accounts/microsoft/callback", {"code": "c", "state": state})
    assert urlparse(response["Location"]).path == "/meetings"
    assert "drive_connected" in response["Location"]
    connection.refresh_from_db()
    assert connection.send_as_verified_at == passed
    assert microsoft_oauth.files_granted(connection.scopes)
    assert ms.of("POST", "/me/messages") == []          # no second test send


@pytest.mark.django_db
def test_consent_without_files_says_so_on_the_queue(ms_practice, ff, api, ms):
    connection = _connect(ms_practice, ff)
    ms.on("POST", "/oauth2/v2.0/token", Reply(payload=fixture("token.json")))
    ms.on("GET", "/v1.0/me", Reply(payload=dict(fixture("me.json"), mail=connection.email_address)))
    client = api.as_(ff)
    client.post("/api/drive-watch/consent/")
    state = client.session[microsoft_oauth.STATE_SESSION_KEY]
    response = client.get("/accounts/microsoft/callback", {"code": "c", "state": state})
    assert urlparse(response["Location"]).path == "/meetings"
    assert "drive_error" in response["Location"]


# ------------------------------------------------- Drive polling unchanged

@pytest.mark.django_db
def test_a_drive_file_is_recorded_as_before(seeded_tenant):
    """A Drive file carries no skip of its own, so its mime type decides, and
    it is recorded as Google's."""
    with tenant_context(seeded_tenant.pk):
        doc, _ = ingest.record(seeded_tenant, drive.DriveFile(
            file_id="d1", version="7", name="Notes by Gemini", mime_type=drive.GOOGLE_DOC))
        pdf, _ = ingest.record(seeded_tenant, drive.DriveFile(
            file_id="d2", version="1", name="Deck", mime_type="application/pdf"))
        vtt, _ = ingest.record(seeded_tenant, drive.DriveFile(
            file_id="d3", version="1", name="talk.vtt", mime_type="text/vtt"))
    assert (doc.provider, doc.state, doc.skip_reason) == ("google", "recorded", "")
    assert pdf.state == "skipped" and pdf.skip_reason == drive.SKIP_REASONS["application/pdf"]
    # A .vtt in Drive is skipped as it always was; only OneDrive reads them.
    assert vtt.state == "skipped"


@pytest.mark.django_db
def test_a_google_practices_watch_and_health_are_as_before(seeded_tenant, ff, api):
    DriveWatchFactory(tenant=seeded_tenant, folder_id="g-folder")
    with tenant_context(seeded_tenant.pk):
        assert ingest.watch_for(seeded_tenant).folder_id == "g-folder"
    body = api.as_(ff).get("/api/drive-watch/").json()
    assert body["provider"] == "google" and body["folder_id"] == "g-folder"
    assert body["google_connected"] is False


@pytest.mark.django_db
def test_a_google_practice_saves_a_drive_folder_as_before(seeded_tenant, ff, api):
    from unittest import mock

    info = drive.FolderInfo(folder_id="abcdef123", name="Notes", files=2, readable=2)
    with mock.patch.object(ingest, "describe_folder", return_value=info):
        response = api.as_(ff).post("/api/drive-watch/", {
            "folder": "https://drive.google.com/drive/folders/abcdef123?usp=sharing"},
            content_type="application/json")
    assert response.status_code == 201
    watch = DriveWatch.all_objects.get(tenant=seeded_tenant)
    assert (watch.provider, watch.folder_id) == ("google", "abcdef123")


# ------------------------------------------------- the Practices area

@pytest.mark.django_db
def test_the_platform_owner_sets_up_a_microsoft_practice(ms, settings):
    from apps.platform import mail as platform_mail
    from apps.platform import provisioning

    owner = User.objects.create_user(email="owner@platform.example")
    tenant = provisioning.provision_practice(
        legal_name="Contoso LLC", display_name="Contoso", domain="contoso.example",
        owner_email="pat@contoso.example", actor=owner, mail_provider="microsoft")
    assert tenant.mail_provider == "microsoft"
    settings.MICROSOFT_CLIENT_ID = ""
    with pytest.raises(platform_mail.PlatformMailUnavailable, match="Sign in with Microsoft"):
        platform_mail.send_invitation(tenant, actor=owner)
