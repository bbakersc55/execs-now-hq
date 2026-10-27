"""The Notices list and browser notifications (owner, 2026-10-26).

- **The opt-in:** a person turns notifications on in a browser (one
  subscription per browser), only on a real browser push service, never on a
  demo visitor's copy, never while acting as someone, never without keys.
- **Every kind is optional:** a notice is always on the list; a browser hears
  of it only for a kind the person has on, and only kinds of their side.
- **The list is the source of truth:** what is pushed is a notice's own
  title, text and link, and nothing is pushed that is not a notice.
- **Isolation:** a person sees and marks only their own notices; a notice in
  one practice never reaches a browser subscribed in another; a client is
  never told of an internal comment, nor of another company's work.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.notify import producers, service
from apps.notify.models import Notice, PushPreference, PushSubscription
from apps.tenancy.context import tenant_context
from apps.work import services as work

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import ClientCompanyFactory, MembershipFactory

pytestmark = pytest.mark.django_db
FCM = "https://fcm.googleapis.com/fcm/send/abc123"
KEYS = {"p256dh": "BPk3" + "x" * 80, "auth": "a" * 22}


def post(client, url, data=None):
    return client.post(url, json.dumps(data or {}), content_type="application/json")


def put(client, url, data):
    return client.put(url, json.dumps(data), content_type="application/json")


@pytest.fixture(autouse=True)
def keys_and_capture(settings, monkeypatch):
    settings.VAPID_PUBLIC_KEY, settings.VAPID_PRIVATE_KEY = "BPub" + "k" * 80, "priv" + "k" * 39
    sent = []

    def fake(**kw):
        sent.append(kw)

    monkeypatch.setattr(service, "_webpush", lambda: fake)
    # Pushes go once committed; a test's transaction never commits.
    monkeypatch.setattr(service.transaction, "on_commit", lambda fn, **kw: fn())
    return sent


def subscribe(api, who, endpoint=FCM):
    return post(api.as_(who), "/api/notify/push/subscribe/", {"endpoint": endpoint, "keys": KEYS})


@pytest.fixture
def world(seeded_tenant, ff, api):
    t = seeded_tenant
    company = ClientCompanyFactory(tenant=t, name="Northwind Foods", seat_count=10)
    other = ClientCompanyFactory(tenant=t, name="Elsewhere Co.", seat_count=10)

    def named(m, name):
        m.user.full_name = name
        m.user.save(update_fields=["full_name"])
        return m

    who = {"ff": named(ff, "Fran Founder"),
           "va": named(MembershipFactory(tenant=t, role="VA"), "Val Assistant"),
           "owner": named(MembershipFactory(tenant=t, role="FCC", client_company=company),
                          "Olive Owner"),
           "outsider": named(MembershipFactory(tenant=t, role="FCC", client_company=other),
                             "Otto Outsider")}
    with tenant_context(t.pk):
        task = work.create_task(tenant=t, actor=ff.user, role="FF", title="Count the cold room",
                                client_company=company, is_client_visible=True)
    return {"t": t, "company": company, "who": who, "task": task, "api": api}


# ---------------------------------------------------------------- the opt-in

def test_turning_it_on_makes_one_subscription_per_browser_with_every_kind(world, keys_and_capture):
    api, who = world["api"], world["who"]
    made = subscribe(api, who["ff"])
    assert made.status_code == 201, made.content
    state = made.json()
    assert state["browsers"] == 1 and state["refusal"] == ""
    assert {k["key"] for k in state["kinds"] if k["on"]} == {"notice", "client_message",
                                                             "reading", "mention"}
    # The same browser again, even signed in as someone else: still one, now theirs.
    subscribe(api, who["ff"])
    subscribe(api, who["va"])
    [sub] = PushSubscription.all_objects.filter(tenant=world["t"])
    assert sub.user_id == who["va"].user_id
    # A client's choices are a client's: no pipeline notices.
    state = subscribe(api, who["owner"], "https://updates.push.services.mozilla.com/wpush/v2/x").json()
    assert {k["key"] for k in state["kinds"]} == {"client_message", "reading", "mention"}
    # Turning it off in this browser.
    post(api.as_(who["owner"]), "/api/notify/push/unsubscribe/",
         {"endpoint": "https://updates.push.services.mozilla.com/wpush/v2/x"})
    assert not PushSubscription.all_objects.filter(user=who["owner"].user).exists()


@pytest.mark.parametrize("endpoint", ["http://fcm.googleapis.com/x", "https://localhost/x",
                                      "https://evil.example/push", "https://169.254.169.254/x"])
def test_only_a_browsers_own_push_service_is_ever_posted_to(world, endpoint):
    refused = subscribe(world["api"], world["who"]["ff"], endpoint)
    assert refused.status_code == 400 and "push address" in refused.json()["detail"]
    assert not PushSubscription.all_objects.exists()


def test_never_on_a_demo_copy_never_without_keys_never_while_acting(world, settings, monkeypatch):
    from apps.tenancy.demo import visitors

    api, ff = world["api"], world["who"]["ff"]
    monkeypatch.setattr(visitors, "is_copy", lambda tenant: True)
    refused = subscribe(api, ff)
    assert refused.status_code == 409 and "demo copy" in refused.json()["detail"]
    assert "demo copy" in api.as_(ff).get("/api/notify/push/").json()["refusal"]
    monkeypatch.setattr(visitors, "is_copy", lambda tenant: False)
    settings.VAPID_PRIVATE_KEY = ""
    assert subscribe(api, ff).status_code == 409
    settings.VAPID_PRIVATE_KEY = "priv" + "k" * 39
    from apps.notify import views

    monkeypatch.setattr(views, "_acting", lambda: True)
    assert subscribe(api, ff).status_code == 403
    assert put(api.as_(ff), "/api/notify/push/", {"kinds": []}).status_code == 403


def test_a_demo_copy_is_never_pushed_to_even_with_a_subscription(world, keys_and_capture,
                                                                  monkeypatch):
    from apps.tenancy.demo import visitors

    subscribe(world["api"], world["who"]["ff"])
    monkeypatch.setattr(visitors, "is_copy", lambda tenant: True)
    with tenant_context(world["t"].pk):
        service.tell(tenant_id=world["t"].pk, recipient_id=world["who"]["ff"].user_id,
                     kind="notice", title="Pipeline", text="Call Dana")
    assert keys_and_capture == []
    assert Notice.all_objects.filter(recipient=world["who"]["ff"].user).count() == 1


# ---------------------------------------------------------------- every kind optional

def test_a_kind_switched_off_is_on_the_list_and_not_in_the_browser(world, keys_and_capture):
    api, ff = world["api"], world["who"]["ff"]
    subscribe(api, ff)
    state = put(api.as_(ff), "/api/notify/push/", {"kinds": ["mention"]}).json()
    assert [k["key"] for k in state["kinds"] if k["on"]] == ["mention"]
    with tenant_context(world["t"].pk):
        service.tell(tenant_id=world["t"].pk, recipient_id=ff.user_id, kind="notice",
                     title="Pipeline", text="Call Dana back", url="/contacts/x")
        service.tell(tenant_id=world["t"].pk, recipient_id=ff.user_id, kind="mention",
                     title="Val mentioned you", text="On “Count”: hi", url="/tasks/y")
    listed = api.as_(ff).get("/api/notify/notices/").json()
    assert listed["unread"] == 2
    [pushed] = keys_and_capture
    body = json.loads(pushed["data"])
    # What is pushed is the notice itself.
    notice = Notice.all_objects.get(kind="mention")
    assert body == {"title": notice.title, "body": notice.text, "url": notice.url,
                    "tag": str(notice.pk)}
    assert pushed["subscription_info"]["endpoint"] == FCM
    assert notice.pushed_at is None or Notice.all_objects.get(pk=notice.pk).pushed_at
    assert Notice.all_objects.get(kind="notice").pushed_at is None


def test_a_kind_not_of_their_side_is_refused(world):
    refused = put(world["api"].as_(world["who"]["owner"]), "/api/notify/push/",
                  {"kinds": ["notice"]})
    assert refused.status_code == 400


def test_a_browser_that_let_go_is_forgotten(world, monkeypatch):
    from pywebpush import WebPushException

    subscribe(world["api"], world["who"]["ff"])

    def gone(**kw):
        raise WebPushException("gone", response=SimpleNamespace(status_code=410))

    monkeypatch.setattr(service, "_webpush", lambda: gone)
    with tenant_context(world["t"].pk):
        service.tell(tenant_id=world["t"].pk, recipient_id=world["who"]["ff"].user_id,
                     kind="notice", title="Pipeline", text="x")
    assert not PushSubscription.all_objects.exists()


# ---------------------------------------------------------------- isolation

def test_each_person_sees_and_marks_only_their_own(world):
    api, who = world["api"], world["who"]
    with tenant_context(world["t"].pk):
        mine = service.tell(tenant_id=world["t"].pk, recipient_id=who["ff"].user_id,
                            kind="notice", title="Pipeline", text="for Fran")
        theirs = service.tell(tenant_id=world["t"].pk, recipient_id=who["va"].user_id,
                              kind="notice", title="Pipeline", text="for Val")
    got = api.as_(who["ff"]).get("/api/notify/notices/").json()
    assert [n["id"] for n in got["notices"]] == [str(mine.pk)]
    done = post(api.as_(who["ff"]), "/api/notify/notices/read/", {"ids": [str(theirs.pk)]})
    assert done.json()["read"] == 0
    assert Notice.all_objects.get(pk=theirs.pk).read_at is None
    assert post(api.as_(who["ff"]), "/api/notify/notices/read/", {"all": True}).json() == \
        {"read": 1, "unread": 0}


def test_a_notice_in_one_practice_never_reaches_a_browser_subscribed_in_another(
        world, tenant_b, keys_and_capture):
    from apps.crm.seed import seed_tenant

    seed_tenant(tenant_b)
    ff = world["who"]["ff"]
    # The same person, a member of a second practice too, with a browser there.
    MembershipFactory(tenant=tenant_b, role="FF", user=ff.user)
    PushSubscription.all_objects.create(tenant=tenant_b, user=ff.user, endpoint=FCM + "-b",
                                        **KEYS)
    PushPreference.all_objects.create(tenant=tenant_b, user=ff.user, kinds=["notice"])
    with tenant_context(world["t"].pk):
        service.tell(tenant_id=world["t"].pk, recipient_id=ff.user_id, kind="notice",
                     title="Pipeline", text="practice A's")
    assert keys_and_capture == []                       # no browser of A's: nothing at all
    assert not Notice.all_objects.filter(tenant=tenant_b).exists()


def test_a_shared_message_tells_the_clients_who_see_it_and_an_internal_one_nobody_outside(
        world):
    t, who, task = world["t"], world["who"], world["task"]
    with tenant_context(t.pk):
        work.add_comment(task, author=who["ff"].user, role="FF",
                         body="The counts are in; thank you all.", visibility="shared")
        work.add_comment(task, author=who["ff"].user, role="FF",
                         body="Internal: @Olive Owner is late again.", visibility="internal")
    told = Notice.all_objects.filter(recipient=who["owner"].user)
    assert [(n.kind, n.text) for n in told] == [
        ("client_message", "On “Count the cold room”: The counts are in; thank you all.")]
    assert told[0].url == f"/tasks/{task.pk}"
    # Another company's owner hears of neither.
    assert not Notice.all_objects.filter(recipient=who["outsider"].user).exists()


def test_a_mention_tells_who_is_named_and_can_see_it(world):
    t, who, task = world["t"], world["who"], world["task"]
    with tenant_context(t.pk):
        work.add_comment(task, author=who["owner"].user, role="FCC",
                         body="@Fran Founder and @val, can you check the freezer log?")
    fran = Notice.all_objects.get(recipient=who["ff"].user)
    assert fran.kind == "mention" and fran.title == "Olive Owner mentioned you"
    assert Notice.all_objects.get(recipient=who["va"].user).kind == "mention"
    # Mentioning someone who can't see the work tells them nothing.
    with tenant_context(t.pk):
        work.add_comment(task, author=who["ff"].user, role="FF",
                         body="Looping in @Otto Outsider.", visibility="shared")
    assert not Notice.all_objects.filter(recipient=who["outsider"].user).exists()


def test_a_clients_message_tells_the_practice_people_the_work_belongs_to(world):
    t, who, task = world["t"], world["who"], world["task"]
    with tenant_context(t.pk):
        work.add_comment(task, author=who["owner"].user, role="FCC", body="Done on our side.")
    [notice] = Notice.all_objects.filter(recipient=who["ff"].user)
    assert notice.kind == "client_message" and notice.title == "New message from Olive Owner"
    assert not Notice.all_objects.filter(recipient=who["va"].user).exists()


def test_a_stage_rules_notice_and_a_waiting_reading_are_on_the_list(world, monkeypatch):
    from apps.crm.models import PipelineNotice
    from apps.crm.services import stage_rules

    from .factories import ContactFactory

    t, ff = world["t"], world["who"]["ff"]
    with tenant_context(t.pk):
        contact = ContactFactory(tenant=t, first_name="Dana", last_name="Reyes")
        monkeypatch.setattr(stage_rules, "person_for", lambda rule, c: ff.user)
        rule = SimpleNamespace(notice_text="Call Dana back", pipeline_id=None, pk=None)
        monkeypatch.setattr(stage_rules, "merged", lambda text, c, r: text)
        monkeypatch.setattr(PipelineNotice.all_objects, "create",
                            lambda **kw: SimpleNamespace(pk=__import__("uuid").uuid4(), **{
                                "tenant_id": kw["tenant_id"], "recipient_id": kw["recipient"].pk,
                                "contact_id": kw["contact"].pk, "text": kw["text"]}))
        stage_rules.notify(contact, rule)
    [notice] = Notice.all_objects.filter(recipient=ff.user, kind="notice")
    assert notice.text == "Call Dana back" and notice.url == f"/contacts/{contact.pk}"


def test_a_reading_reminder_is_told_to_its_owner(world):
    from apps.scorecard import readings, setup
    from apps.scorecard.models import Kpi

    t, ff, owner = world["t"], world["who"]["ff"], world["who"]["owner"]
    with tenant_context(t.pk):
        card = setup.ensure(world["company"], ff.user)
        kpi = setup.create_kpi(card, {"name": "Deliveries", "kind": "count",
                                      "cadence": "weekly", "page": str(card.pages.get().pk),
                                      "reading_owner": str(owner.user_id)}, ff.user)
        Kpi.objects.filter(pk=kpi.pk).update(created_at=timezone.now() - timezone.timedelta(days=30))
        readings.remind(t, timezone.localdate())
        readings.remind(t, timezone.localdate())                # told once
    [notice] = Notice.all_objects.filter(recipient=owner.user, kind="reading")
    assert notice.text.startswith("Deliveries: no reading yet for")
    assert notice.url == "/scorecard/enter"


# ------------------------------------------- "@" suggestions (2026-10-27)

def mentionable(world, who, visibility="internal", task=None):
    task = task or world["task"]
    return world["api"].as_(world["who"][who]).get(
        f"/api/comments/mentionable/?task={task.pk}&visibility={visibility}")


def names(response):
    assert response.status_code == 200, response.content
    return [row["name"] for row in response.json()]


def test_suggestions_are_who_a_mention_would_tell(world):
    """An internal comment: the practice's people only, never the writer. A
    shared one: the client's people of the work's company too; never another
    company's."""
    assert names(mentionable(world, "ff")) == ["Val Assistant"]
    assert names(mentionable(world, "ff", "shared")) == ["Olive Owner", "Val Assistant"]
    assert "Otto Outsider" not in names(mentionable(world, "va", "shared"))


def test_a_clients_suggestions_are_for_a_shared_comment_whatever_they_ask(world):
    assert names(mentionable(world, "owner", "internal")) == ["Fran Founder", "Val Assistant"]


def test_suggestions_for_work_one_cannot_see_are_a_404(world):
    assert mentionable(world, "outsider").status_code == 404


def test_suggestions_never_cross_practices(world, api):
    from .factories import TenantFactory

    other = TenantFactory()
    stranger = MembershipFactory(tenant=other, role="FF")
    assert api.as_(stranger).get(
        f"/api/comments/mentionable/?task={world['task'].pk}").status_code == 404
    assert mentionable(world, "ff", "shared").json()[0].keys() == {"id", "name"}
