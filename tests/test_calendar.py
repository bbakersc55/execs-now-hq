"""Calendar (owner, 2026-10-27): one calendar per user, Home's two days, a
company's meetings, "Add to calendar", and the stage rule's calendar event.

The mandatory families: role boundaries (the practice's team only, each for
their own; clients reach nothing) and tenant isolation (a connection, an
event, a match or an added event never crosses practices, and a person sees
only what their role lets them). Then the promise: an event's body is never
read, so it cannot reach a prompt.

Google and Microsoft answer from `tests/fixtures/calendar/`, shaped from their
references; nothing here reached either.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

import pytest

from apps.calendars import providers, sync
from apps.calendars.models import (
    CalendarConnection, CalendarEntry, CalendarEvent, CalendarEventMatch,
)
from apps.crm.models import StageAutomation
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Role, TenantSecret

from . import registry_config  # noqa: F401
from .factories import (
    ClientCompanyFactory, CompanyFactory, ContactEmailFactory, ContactFactory,
    MembershipFactory, TenantFactory,
)
from .test_microsoft_transport import Reply, ms  # noqa: F401 - `ms` is a fixture

FIXTURES = Path(__file__).parent / "fixtures" / "calendar"
NOW = datetime(2026, 10, 27, 15, 0, tzinfo=dt_timezone.utc)      # 09:00 in Denver


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


class FakeGoogle:
    def __init__(self):
        self.calls = []
        self.events = fixture("google_events.json")

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        if url.endswith("/userinfo"):
            return Reply(payload={"email": "bryan@getexecutivesnow.com"})
        return Reply(payload=self.events)

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        if url.endswith("/token"):
            return Reply(payload=fixture("google_token.json"))
        return Reply(payload=fixture("google_created.json"))


@pytest.fixture
def google(monkeypatch, settings):
    settings.GOOGLE_OAUTH_CLIENT_ID, settings.GOOGLE_OAUTH_CLIENT_SECRET = "gid", "gsecret"
    fake = FakeGoogle()
    for module in ("apps.calendars.providers", "apps.crm.services.gmail_oauth"):
        stub = mock.Mock(get=fake.get, post=fake.post,
                         RequestException=__import__("requests").RequestException)
        monkeypatch.setattr(f"{module}.requests", stub)
    monkeypatch.setattr("django.utils.timezone.now", lambda: NOW)
    return fake


@pytest.fixture
def acme(seeded_tenant):
    """Dana at Acme (a contact), Acme known by its domain, and Initech known
    by its domain only."""
    acme_co = ClientCompanyFactory(tenant=seeded_tenant, name="Acme")
    from apps.crm.models import CompanyDomain

    CompanyDomain.all_objects.create(tenant=seeded_tenant, company=acme_co, domain="acme.invalid")
    initech = CompanyFactory(tenant=seeded_tenant, name="Initech")
    CompanyDomain.all_objects.create(tenant=seeded_tenant, company=initech,
                                     domain="initech.invalid")
    dana = ContactFactory(tenant=seeded_tenant, first_name="Dana", last_name="Reyes",
                          company=acme_co)
    ContactEmailFactory(tenant=seeded_tenant, contact=dana, address="dana@acme.invalid")
    return {"acme": acme_co, "initech": initech, "dana": dana}


def _connect(tenant, membership, provider="google", email="bryan@getexecutivesnow.com"):
    from apps.crm.services.secrets import write_secret
    from apps.tenancy.models import SecretKind

    secret = write_secret(tenant=tenant, kind=SecretKind.CALENDAR_REFRESH,
                          value="refresh", user=membership.user)
    return CalendarConnection.all_objects.create(
        tenant=tenant, user=membership.user, provider=provider, email_address=email,
        secret=secret)


def _sync(connection):
    with tenant_context(connection.tenant_id):
        return sync.sync(connection, now=NOW)


# ============================================================ role boundaries

ENDPOINTS = ["/api/calendar/", "/api/calendar/start/", "/api/calendar/sync/",
             "/api/calendar/disconnect/", "/api/calendar/upcoming/", "/api/calendar/add/"]


@pytest.mark.django_db
@pytest.mark.parametrize("path", ENDPOINTS)
def test_clients_reach_nothing(path, fcc, api, google):
    client = api.as_(fcc)
    response = client.get(path) if path in ENDPOINTS[:1] + ENDPOINTS[4:5] else client.post(path)
    assert response.status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FF", "CF", "VA"])
def test_every_team_member_connects_their_own(role, seeded_tenant, api, google):
    member = MembershipFactory(tenant=seeded_tenant, role=role)
    url = api.as_(member).post("/api/calendar/start/").json()["authorization_url"]
    query = parse_qs(urlparse(url).query)
    assert query["scope"][0].split() == providers.GOOGLE_SCOPES
    assert query["redirect_uri"][0].endswith("/accounts/gmail/callback")
    assert query["access_type"] == ["offline"]


@pytest.mark.django_db
def test_one_person_never_sees_anothers_calendar(seeded_tenant, ff, cf, api, google, acme):
    _sync(_connect(seeded_tenant, ff))
    assert api.as_(cf).get("/api/calendar/").json()["connected"] is False
    upcoming = api.as_(cf).get("/api/calendar/upcoming/").json()
    assert all(not day["events"] for day in upcoming["days"])
    assert api.as_(cf).post("/api/calendar/disconnect/").status_code == 400
    assert CalendarConnection.all_objects.filter(user=ff.user).exists()


@pytest.mark.django_db
def test_a_company_page_shows_only_a_company_one_may_see(seeded_tenant, ff, cf, api, google,
                                                         acme):
    """An associate sees a client's meetings only once assigned to it."""
    from apps.tenancy.models import ClientAssignment

    _sync(_connect(seeded_tenant, ff))
    url = f"/api/calendar/company/{acme['acme'].pk}/"
    assert api.as_(cf).get(url).status_code == 404
    ClientAssignment.all_objects.create(tenant=seeded_tenant, user=cf.user,
                                        company=acme["acme"])
    rows = api.as_(cf).get(url).json()
    assert [r["title"] for r in rows] == ["Weekly check-in, Acme", "Acme offsite"]
    assert rows[0]["on_calendar_of"]


# ============================================================ isolation

@pytest.mark.django_db
def test_matching_stays_inside_the_practice(seeded_tenant, ff, google, acme):
    """Another practice's contact with the same address is not matched."""
    other = TenantFactory(name="Other", slug="other-cal")
    theirs = ContactFactory(tenant=other, first_name="Dana", last_name="Elsewhere")
    ContactEmailFactory(tenant=other, contact=theirs, address="dana@acme.invalid")
    _sync(_connect(seeded_tenant, ff))
    matched = set(CalendarEventMatch.all_objects.values_list("contact_id", flat=True)) - {None}
    assert matched == {acme["dana"].pk}
    assert set(CalendarEventMatch.all_objects.values_list("tenant_id", flat=True)) \
        == {seeded_tenant.pk}


@pytest.mark.django_db
def test_another_practices_company_is_a_404(seeded_tenant, ff, api, google):
    other = TenantFactory(name="Other", slug="other-cal-2")
    theirs = ClientCompanyFactory(tenant=other)
    assert api.as_(ff).get(f"/api/calendar/company/{theirs.pk}/").status_code == 404


@pytest.mark.django_db
def test_a_task_in_another_practice_cannot_be_added(seeded_tenant, ff, api, google):
    from .factories import TaskFactory

    _connect(seeded_tenant, ff)
    other = TenantFactory(name="Other", slug="other-cal-3")
    theirs = TaskFactory(tenant=other, due_date="2026-10-30")
    response = api.as_(ff).post("/api/calendar/add/", {
        "source": "task", "source_id": str(theirs.pk), "date": "2026-10-30", "time": "10:00"},
        content_type="application/json")
    assert response.status_code == 404
    assert not CalendarEntry.all_objects.exists()


@pytest.mark.django_db
def test_the_callback_connects_in_the_signed_in_practice(seeded_tenant, ff, api, google):
    other = TenantFactory(name="Other", slug="other-cal-4")
    client = api.as_(ff)
    client.post("/api/calendar/start/")
    state = client.session[providers.STATE_KEY]["state"]
    response = client.get("/accounts/gmail/callback", {"code": "c", "state": state})
    assert "calendar_connected" in response["Location"] and "/profile?" in response["Location"]
    row = CalendarConnection.all_objects.get()
    assert row.tenant_id == seeded_tenant.pk and row.user_id == ff.user_id
    assert not CalendarConnection.all_objects.filter(tenant=other).exists()
    assert TenantSecret.all_objects.get(pk=row.secret_id).kind == "calendar_refresh"
    # A calendar consent on Gmail's callback is not a Gmail connection.
    from apps.crm.models import GmailConnection

    assert not GmailConnection.all_objects.exists()


@pytest.mark.django_db
def test_a_consent_without_the_calendar_stores_nothing(seeded_tenant, ff, api, google):
    google.post = lambda url, **kw: Reply(payload=fixture("google_token_no_calendar.json"))
    import apps.calendars.providers as p
    import apps.crm.services.gmail_oauth as g

    g.requests.post = google.post
    p.requests.post = google.post
    client = api.as_(ff)
    client.post("/api/calendar/start/")
    state = client.session[providers.STATE_KEY]["state"]
    response = client.get("/accounts/gmail/callback", {"code": "c", "state": state})
    assert "calendar_error" in response["Location"]
    assert not CalendarConnection.all_objects.exists()


# ============================================================ reading

@pytest.mark.django_db
def test_a_sync_keeps_titles_times_and_links_and_drops_private_and_cancelled(
        seeded_tenant, ff, google, acme):
    connection = _connect(seeded_tenant, ff)
    assert _sync(connection) == {"events": 4}
    titles = sorted(CalendarEvent.all_objects.values_list("title", flat=True))
    assert titles == ["Acme offsite", "Intro with Initech", "Team planning",
                      "Weekly check-in, Acme"]
    checkin = CalendarEvent.all_objects.get(provider_event_id="g-checkin")
    assert checkin.starts_at == datetime(2026, 10, 27, 16, 0, tzinfo=dt_timezone.utc)
    assert checkin.web_link.startswith("https://www.google.com/calendar/event")
    assert CalendarEvent.all_objects.get(provider_event_id="g-allday").all_day


@pytest.mark.django_db
def test_matches_by_contact_then_by_domain_never_staff_or_public_mail(
        seeded_tenant, ff, google, acme):
    MembershipFactory(tenant=seeded_tenant, role="CF").user.__class__.objects.filter(
        pk=MembershipFactory(tenant=seeded_tenant, role="CF").user_id).update(
        email="casey@getexecutivesnow.com")
    _sync(_connect(seeded_tenant, ff))

    def of(event_id):
        rows = CalendarEventMatch.all_objects.filter(event__provider_event_id=event_id)
        return ({r.contact_id for r in rows if r.contact_id},
                {r.company_id for r in rows if r.company_id})

    assert of("g-checkin") == ({acme["dana"].pk}, {acme["acme"].pk})
    assert of("g-domain") == (set(), {acme["initech"].pk})     # gmail.com matched nothing
    assert of("g-internal") == (set(), set())                   # a colleague is not a client


@pytest.mark.django_db
def test_no_attendee_address_is_kept(seeded_tenant, ff, google, acme):
    _sync(_connect(seeded_tenant, ff))
    fields = {f.name for m in (CalendarEvent, CalendarEventMatch) for f in m._meta.get_fields()}
    assert not fields & {"attendees", "emails", "email", "address", "body", "description"}


@pytest.mark.django_db
def test_an_events_body_is_never_asked_for(seeded_tenant, ff, google, ms):
    """Google's field mask and Graph's $select name what is read; neither
    names the description or body."""
    _sync(_connect(seeded_tenant, ff))
    asked = next(kw["params"]["fields"] for verb, url, kw in google.calls
                 if verb == "GET" and url.endswith("/events"))
    assert "description" not in asked and "attachments" not in asked
    assert "summary" in asked and "attendees(email,self)" in asked
    assert "body" not in providers.GRAPH_SELECT.split(",")
    assert "bodyPreview" not in providers.GRAPH_SELECT.split(",")


@pytest.mark.django_db
def test_an_event_gone_from_the_calendar_goes_and_a_past_one_stays(
        seeded_tenant, ff, google, acme):
    connection = _connect(seeded_tenant, ff)
    with tenant_context(seeded_tenant.pk):
        old = CalendarEvent.objects.create(
            tenant=seeded_tenant, connection=connection, provider_event_id="old",
            title="Last month", starts_at=datetime(2026, 9, 27, tzinfo=dt_timezone.utc),
            ends_at=datetime(2026, 9, 27, 1, tzinfo=dt_timezone.utc))
    _sync(connection)
    google.events = {"items": [i for i in fixture("google_events.json")["items"]
                               if i["id"] != "g-domain"]}
    _sync(connection)
    ids = set(CalendarEvent.all_objects.values_list("provider_event_id", flat=True))
    assert "g-domain" not in ids and old.provider_event_id in ids


@pytest.mark.django_db
def test_a_refused_calendar_says_so_and_keeps_what_it_had(seeded_tenant, ff, google, acme):
    connection = _connect(seeded_tenant, ff)
    _sync(connection)
    google.get = lambda url, **kw: Reply(401, {"error": {"code": 401}})
    import apps.calendars.providers as p

    p.requests.get = google.get
    assert "error" in _sync(connection)
    connection.refresh_from_db()
    assert "would not list events (401)" in connection.last_error
    assert CalendarEvent.all_objects.count() == 4


@pytest.mark.django_db
def test_home_shows_today_and_tomorrow_in_ones_own_zone(seeded_tenant, ff, api, google, acme):
    _sync(_connect(seeded_tenant, ff))
    body = api.as_(ff).get("/api/calendar/upcoming/").json()
    assert [d["label"] for d in body["days"]] == ["Today", "Tomorrow"]
    today, tomorrow = body["days"]
    assert today["date"] == "2026-10-27"
    assert [e["title"] for e in today["events"]] == ["Weekly check-in, Acme", "Intro with Initech"]
    assert today["events"][0]["contacts"] == [{"id": str(acme["dana"].pk), "name": "Dana Reyes"}]
    assert today["events"][0]["companies"] == [{"id": str(acme["acme"].pk), "name": "Acme"}]
    assert [e["title"] for e in tomorrow["events"]] == ["Acme offsite", "Team planning"]


@pytest.mark.django_db
def test_an_associate_sees_no_contact_they_may_not_see(seeded_tenant, ff, cf, api, google, acme):
    """The meeting is theirs; a client they are not assigned to is not named."""
    _sync(_connect(seeded_tenant, cf, email="casey@getexecutivesnow.com"))
    today = api.as_(cf).get("/api/calendar/upcoming/").json()["days"][0]
    checkin = next(e for e in today["events"] if e["title"] == "Weekly check-in, Acme")
    assert checkin["contacts"] == [] and checkin["companies"] == []


@pytest.mark.django_db
def test_microsoft_practices_read_their_calendar_through_graph(seeded_tenant, ff, ms, acme,
                                                               monkeypatch):
    seeded_tenant.mail_provider = "microsoft"
    seeded_tenant.save()
    monkeypatch.setattr("django.utils.timezone.now", lambda: NOW)
    ms.on("GET", "/me/calendarView", Reply(payload=fixture("graph_calendarview.json")))
    connection = _connect(seeded_tenant, ff, provider="microsoft", email="bryan@contoso.example")
    assert _sync(connection) == {"events": 1}
    event = CalendarEvent.all_objects.get()
    assert event.starts_at == datetime(2026, 10, 27, 16, 0, tzinfo=dt_timezone.utc)
    assert set(CalendarEventMatch.all_objects.values_list("contact_id", flat=True)) \
        == {acme["dana"].pk, None}
    view = ms.of("GET", "/me/calendarView")[0]
    assert view["headers"]["Prefer"] == 'outlook.timezone="UTC"'
    assert view["params"]["$select"] == providers.GRAPH_SELECT


# ============================================================ adding events

@pytest.mark.django_db
def test_a_task_goes_on_ones_own_calendar_inviting_nobody(seeded_tenant, ff, api, google):
    from .factories import TaskFactory

    _connect(seeded_tenant, ff)
    task = TaskFactory(tenant=seeded_tenant, title="Send the margin breakdown",
                       due_date="2026-10-30", owner=ff.user)
    response = api.as_(ff).post("/api/calendar/add/", {
        "source": "task", "source_id": str(task.pk), "date": "2026-10-30", "time": "10:30",
        "minutes": 45}, content_type="application/json")
    assert response.status_code == 201
    sent = next(kw["json"] for verb, url, kw in google.calls
                if verb == "POST" and url.endswith("/events"))
    assert sent["summary"] == "Send the margin breakdown"
    assert sent["start"] == {"dateTime": "2026-10-30T10:30:00-06:00",
                             "timeZone": "America/Denver"}
    assert sent["end"]["dateTime"] == "2026-10-30T11:15:00-06:00"
    assert "attendees" not in sent
    entry = CalendarEntry.all_objects.get()
    assert (entry.source_type, entry.source_id, entry.minutes) == ("task", task.pk, 45)
    assert entry.web_link == fixture("google_created.json")["htmlLink"]


@pytest.mark.django_db
def test_adding_needs_a_connected_calendar(seeded_tenant, ff, api, google):
    from .factories import TaskFactory

    task = TaskFactory(tenant=seeded_tenant, due_date="2026-10-30")
    response = api.as_(ff).post("/api/calendar/add/", {
        "source": "task", "source_id": str(task.pk), "date": "2026-10-30"},
        content_type="application/json")
    assert response.status_code == 409 and "Connect your calendar" in response.json()["detail"]


@pytest.mark.django_db
def test_a_follow_up_step_goes_on_the_calendar(seeded_tenant, ff, api, google, acme):
    from apps.crm.models import FollowUp, FollowUpRun, PipelineStage

    stage = PipelineStage.all_objects.filter(tenant=seeded_tenant).first()
    follow_up = FollowUp.all_objects.create(tenant=seeded_tenant, stage=stage)
    run = FollowUpRun.all_objects.create(tenant=seeded_tenant, follow_up=follow_up,
                                         contact=acme["dana"], stage=stage)
    _connect(seeded_tenant, ff)
    response = api.as_(ff).post("/api/calendar/add/", {
        "source": "follow_up", "source_id": str(run.pk), "date": "2026-11-02",
        "time": "09:00"}, content_type="application/json")
    assert response.status_code == 201
    assert response.json()["title"] == f"Follow up with Dana Reyes ({stage.label})"


@pytest.mark.django_db
def test_microsoft_adds_through_graph(seeded_tenant, ff, api, ms):
    from .factories import TaskFactory

    seeded_tenant.mail_provider = "microsoft"
    seeded_tenant.save()
    ms.on("POST", "/me/events", Reply(201, fixture("graph_created.json")))
    _connect(seeded_tenant, ff, provider="microsoft")
    task = TaskFactory(tenant=seeded_tenant, title="Send it", due_date="2026-10-30",
                       owner=ff.user)
    response = api.as_(ff).post("/api/calendar/add/", {
        "source": "task", "source_id": str(task.pk), "date": "2026-10-30", "time": "14:00"},
        content_type="application/json")
    assert response.status_code == 201
    made = ms.of("POST", "/me/events")[0]["json"]
    assert made["start"] == {"dateTime": "2026-10-30T14:00:00", "timeZone": "America/Denver"}
    assert "attendees" not in made


# ============================================================ the stage rule

def _calendar_rule(tenant, stage, **kw):
    return StageAutomation.all_objects.create(
        tenant=tenant, pipeline=stage.pipeline, to_stage=stage,
        action_type=StageAutomation.Action.CALENDAR_EVENT,
        task_title_template="Follow up with {FirstName}", task_due_offset_days=2,
        event_minutes=45, **kw)


@pytest.mark.django_db
def test_a_move_offers_the_rules_event_and_makes_nothing_by_itself(
        seeded_tenant, ff, api, google, acme):
    from apps.crm.models import PipelineStage
    from apps.crm.services import pipeline

    stages = list(PipelineStage.all_objects.filter(
        pipeline=pipeline.sales_pipeline(seeded_tenant)).order_by("position"))
    target = stages[1]
    rule = _calendar_rule(seeded_tenant, target)
    response = api.as_(ff).post(f"/api/contacts/{acme['dana'].pk}/change-stage/",
                                {"stage": str(target.pk)}, content_type="application/json")
    offers = response.json()["calendar_offers"]
    assert offers == [{"rule": str(rule.pk), "contact": str(acme["dana"].pk),
                       "title": "Follow up with Dana", "date": "2026-10-29", "minutes": 45}]
    assert not CalendarEntry.all_objects.exists()
    assert not [c for c in google.calls if c[0] == "POST" and c[1].endswith("/events")]

    _connect(seeded_tenant, ff)
    made = api.as_(ff).post("/api/calendar/add/", {
        "source": "stage_rule", "source_id": str(rule.pk), "contact": str(acme["dana"].pk),
        "date": offers[0]["date"], "time": "11:00", "minutes": 45},
        content_type="application/json")
    assert made.status_code == 201
    assert CalendarEntry.all_objects.get().contact_id == acme["dana"].pk


@pytest.mark.django_db
def test_the_rule_is_for_a_contact_entering_a_stage(seeded_tenant, ff, api):
    from apps.crm.services import pipeline

    sales = pipeline.sales_pipeline(seeded_tenant)
    response = api.as_(ff).post("/api/stage-automations/", {
        "pipeline": str(sales.pk), "trigger": "won", "action_type": "calendar_event",
        "task_title_template": "Kickoff"}, content_type="application/json")
    assert response.status_code == 400 and "entering a stage" in json.dumps(response.json())


@pytest.mark.django_db
def test_the_rule_reads_as_a_sentence(seeded_tenant):
    from apps.crm.models import PipelineStage
    from apps.crm.services import stage_rules

    stage = PipelineStage.all_objects.filter(tenant=seeded_tenant).first()
    rule = _calendar_rule(seeded_tenant, stage)
    assert "offer a calendar event 'Follow up with {FirstName}' (45 minutes, suggested 2 days " \
           "ahead) at a time the person moving them picks" in stage_rules.summary(rule)


# ============================================================ the demo, removal

@pytest.mark.django_db
def test_the_demo_connects_no_calendar(seeded_tenant, ff, api, google, settings):
    settings.APP_ENVIRONMENT, settings.IS_DEMO, settings.IS_LOCAL = "demo", True, False
    assert api.as_(ff).post("/api/calendar/start/").status_code == 409
    assert "connects no calendar" in api.as_(ff).get("/api/calendar/").json()["refusal"]


@pytest.mark.django_db
def test_disconnecting_removes_the_token_and_its_events(seeded_tenant, ff, api, google, acme):
    connection = _connect(seeded_tenant, ff)
    _sync(connection)
    api.as_(ff).post("/api/calendar/disconnect/")
    assert not CalendarEvent.all_objects.exists()
    assert not TenantSecret.all_objects.filter(pk=connection.secret_id).exists()


@pytest.mark.django_db
def test_removing_a_member_removes_their_calendar(seeded_tenant, cf, google):
    from apps.tenancy.services import remove_member

    connection = _connect(seeded_tenant, cf)
    remove_member(cf)
    assert not CalendarConnection.all_objects.filter(pk=connection.pk).exists()
