"""The People Command Center's security foundation (2026-11-17,
`docs/p9_people_hris.md`): two-factor sign-in, the twelve hours, the People
re-check, HR permissions, sensitive fields encrypted and their access log,
connected AI apps never seeing People data, and the catalog. Each gate has a
test that tries to break it.
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest
from django.db import connection

from apps.accounts import totp
from apps.accounts import two_factor as tf
from apps.accounts.middleware import SIGNED_IN_KEY
from apps.accounts.models import BackupCode, TwoFactor
from apps.crm.models import OutboxMessage
from apps.people import access as A
from apps.people.models import HRGrant, PeopleAccessLog, PersonRecord
from apps.tenancy.context import tenant_context
from apps.tenancy.models import AuditEvent

from . import registry_config  # noqa: F401
from .conftest import _member
from .factories import ClientCompanyFactory, ClientTeamMemberFactory, TenantFactory

HOURS = 60 * 60


# ------------------------------------------------------------------ helpers

class Clock:
    """The authenticator's clock, moved by the test: a code is good for its
    30-second step, never twice."""

    def __init__(self):
        self.now = 1_800_000_000.0

    def tick(self, steps=1):
        self.now += 30 * steps


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr("apps.accounts.totp.time", SimpleNamespace(time=lambda: c.now))
    return c


def post(client, path, body=None):
    return client.post(path, data=json.dumps(body or {}), content_type="application/json")


def fresh(api, member):
    """A new sign-in for this person: the twelve hours start, and with
    two-factor on, the code is asked for."""
    api._clients.pop(str(member.pk), None)
    return api.as_(member)


def secret_of(key: str) -> str:
    return key.replace(" ", "")


def enroll(api, member, clock):
    client = api.as_(member)
    started = post(client, "/api/me/two-factor/start").json()
    secret = secret_of(started["key"])
    done = post(client, "/api/me/two-factor/confirm", {"code": totp.code_now(secret, clock.now)})
    assert done.status_code == 200, done.content
    clock.tick()
    return secret, done.json()["backup_codes"]


def verify(client, secret, clock):
    clock.tick()
    return post(client, "/api/me/two-factor/verify", {"code": totp.code_now(secret, clock.now)})


def people_on(tenant, ff):
    from apps.centers import services as centers

    with tenant_context(tenant.pk):
        centers.switch(tenant, "people", True, actor=ff.user)


# ------------------------------------------------------- the code itself

@pytest.mark.parametrize("at, code", [
    (59, "287082"), (1111111109, "081804"), (1111111111, "050471"),
    (1234567890, "005924"), (2000000000, "279037"),
])
def test_codes_are_rfc_6238s_own_test_values(at, code):
    """RFC 6238, appendix B, SHA-1, the last six digits."""
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"      # "12345678901234567890"
    assert totp.code_now(secret, at) == code


def test_a_code_is_good_one_step_either_side_and_never_twice():
    secret = totp.new_secret()
    now = 1_800_000_000
    step = totp.step_of(now)
    assert totp.matching_step(secret, totp.code_at(secret, step - 1), now=now) == step - 1
    assert totp.matching_step(secret, totp.code_at(secret, step + 1), now=now) == step + 1
    assert totp.matching_step(secret, totp.code_at(secret, step + 2), now=now) is None
    assert totp.matching_step(secret, totp.code_at(secret, step), after=step, now=now) is None
    assert totp.matching_step(secret, "12345", now=now) is None


def test_the_qr_code_and_the_key_hold_the_same_key():
    secret = totp.new_secret()
    uri = totp.provisioning_uri(secret, account="dana@example.invalid", issuer="Execs NOW HQ")
    assert uri.startswith("otpauth://totp/Execs%20NOW%20HQ:dana@example.invalid?")
    assert f"secret={secret}" in uri and "period=30" in uri and "digits=6" in uri
    assert totp.qr_svg(uri).lstrip().startswith("<svg")
    assert totp.grouped(secret).replace(" ", "") == secret


# ----------------------------------------------------------- enrolling

@pytest.mark.django_db
def test_anyone_enrolls_under_profile_with_a_code_and_gets_ten_backup_codes(api, va, clock):
    client = api.as_(va)
    assert client.get("/api/me/two-factor").json()["enabled"] is False
    started = post(client, "/api/me/two-factor/start").json()
    assert started["uri"].startswith("otpauth://totp/") and "<svg" in started["qr_svg"]
    secret = secret_of(started["key"])
    wrong = post(client, "/api/me/two-factor/confirm", {"code": "000000"})
    assert wrong.status_code == 400 and not tf.enabled(va.user)
    done = post(client, "/api/me/two-factor/confirm", {"code": totp.code_now(secret, clock.now)})
    codes = done.json()["backup_codes"]
    assert len(codes) == 10 and len(set(codes)) == 10 and tf.enabled(va.user)
    # Shown once: only hashes are kept, and the key is encrypted at rest.
    stored = set(BackupCode.objects.filter(user=va.user).values_list("code_hash", flat=True))
    assert not stored & set(codes)
    row = TwoFactor.objects.get(user=va.user)
    assert secret.encode() not in bytes(row.secret_ciphertext)
    assert client.get("/api/me/two-factor").json()["backup_codes_left"] == 10


@pytest.mark.django_db
def test_backup_codes_are_replaced_all_at_once_with_a_code(api, va, clock):
    secret, old = enroll(api, va, clock)
    client = api.as_(va)
    clock.tick()
    new = post(client, "/api/me/two-factor/backup-codes",
               {"code": totp.code_now(secret, clock.now)}).json()["backup_codes"]
    assert len(new) == 10 and not set(new) & set(old)
    later = fresh(api, va)
    assert post(later, "/api/me/two-factor/verify", {"code": old[0]}).status_code == 400
    assert post(later, "/api/me/two-factor/verify", {"code": new[0]}).status_code == 200


# ------------------------------------------------------- after sign-in

@pytest.mark.django_db
def test_after_any_sign_in_nothing_answers_until_the_code(api, va, clock):
    secret, _ = enroll(api, va, clock)
    client = fresh(api, va)
    me = client.get("/api/me").json()
    assert me["authenticated"] is True and me["two_factor_pending"] is True
    blocked = client.get("/api/contacts/")
    assert blocked.status_code == 403 and blocked.json()["two_factor_pending"] is True
    assert verify(client, secret, clock).status_code == 200
    assert client.get("/api/me").json()["two_factor_pending"] is False
    assert client.get("/api/contacts/").status_code == 200


@pytest.mark.django_db
def test_a_backup_code_works_once(api, va, clock):
    _, codes = enroll(api, va, clock)
    client = fresh(api, va)
    assert post(client, "/api/me/two-factor/verify", {"code": codes[3].upper()}).status_code == 200
    again = fresh(api, va)
    assert post(again, "/api/me/two-factor/verify", {"code": codes[3]}).status_code == 400
    assert AuditEvent.all_objects.filter(verb="two_factor.backup_code_used").count() == 1


@pytest.mark.django_db
def test_codes_are_rate_limited_and_a_right_one_waits_too(api, va, clock):
    secret, _ = enroll(api, va, clock)              # one try: the enrolling code
    client = fresh(api, va)
    for _ in range(4):
        assert post(client, "/api/me/two-factor/verify", {"code": "000000"}).status_code == 400
    clock.tick()
    limited = post(client, "/api/me/two-factor/verify", {"code": totp.code_now(secret, clock.now)})
    assert limited.status_code == 429


@pytest.mark.django_db
def test_turning_it_off_takes_a_code_and_is_refused_to_an_hr_holder(api, va, ff, seeded_tenant,
                                                                    clock):
    secret, _ = enroll(api, va, clock)
    clock.tick()
    assert post(api.as_(va), "/api/me/two-factor/off",
                {"code": totp.code_now(secret, clock.now)}).status_code == 200
    assert not tf.enabled(va.user)
    people_on(seeded_tenant, ff)
    owner_secret, _ = enroll(api, ff, clock)
    clock.tick()
    refused = post(api.as_(ff), "/api/me/two-factor/off",
                   {"code": totp.code_now(owner_secret, clock.now)})
    assert refused.status_code == 409 and "HR permission" in refused.json()["detail"]


# ------------------------------------------------------------- resets

@pytest.mark.django_db
def test_a_practice_owner_resets_their_team_and_their_clients_users(api, ff, cf, seeded_tenant,
                                                                    clock):
    company = ClientCompanyFactory(tenant=seeded_tenant)
    client_user = _member(seeded_tenant, "ECC", company=company)
    enroll(api, cf, clock)
    enroll(api, client_user, clock)
    listed = api.as_(ff).get("/api/two-factor/resets").json()["people"]
    assert {p["membership"] for p in listed} == {str(cf.pk), str(client_user.pk)}
    before = OutboxMessage.all_objects.count()
    from django.test import TestCase

    with TestCase.captureOnCommitCallbacks(execute=True):
        done = post(api.as_(ff), "/api/two-factor/resets", {"membership": str(cf.pk)})
    assert done.status_code == 200 and not tf.enabled(cf.user)
    told = OutboxMessage.all_objects.order_by("created_at")[before:]
    assert [m.to_address for m in told] == [cf.user.email]
    assert "reset two-factor sign-in" in told[0].body_text
    assert AuditEvent.all_objects.filter(verb="two_factor.reset", target_id=cf.user_id).exists()


@pytest.mark.django_db
def test_a_client_owner_resets_only_their_own_people(api, seeded_tenant, cf, clock):
    acme, other = ClientCompanyFactory(tenant=seeded_tenant), ClientCompanyFactory(
        tenant=seeded_tenant)
    owner = _member(seeded_tenant, "FCC", company=acme)
    mine = _member(seeded_tenant, "ECC", company=acme)
    theirs = _member(seeded_tenant, "ECC", company=other)
    for m in (mine, theirs, cf):
        enroll(api, m, clock)
    listed = api.as_(owner).get("/api/two-factor/resets").json()["people"]
    assert [p["membership"] for p in listed] == [str(mine.pk)]
    for target in (theirs, cf):        # another company's, and the practice's own
        assert post(api.as_(owner), "/api/two-factor/resets",
                    {"membership": str(target.pk)}).status_code == 404
    assert tf.enabled(theirs.user) and tf.enabled(cf.user)
    assert post(api.as_(owner), "/api/two-factor/resets",
                {"membership": str(mine.pk)}).status_code == 200


@pytest.mark.django_db
def test_nobody_else_resets_and_the_platform_owner_resets_a_practice_owner(api, seeded_tenant,
                                                                           cf, ff, clock):
    from .test_platform_practices import practices

    enroll(api, ff, clock)
    assert api.as_(cf).get("/api/two-factor/resets").status_code == 404
    assert post(api.as_(cf), "/api/two-factor/resets",
                {"membership": str(ff.pk)}).status_code == 404
    other_practice = TenantFactory()
    platform = _member(other_practice, "FF")
    platform.user.is_platform_owner = True
    platform.user.save()
    area = practices(api, platform)
    listed = area.get("/api/platform/two-factor/resets").json()["people"]
    assert str(ff.pk) in {p["membership"] for p in listed}
    assert post(area, "/api/platform/two-factor/resets",
                {"membership": str(ff.pk)}).status_code == 200
    assert not tf.enabled(ff.user)


# ------------------------------------------------------------ twelve hours

@pytest.mark.django_db
def test_everyone_is_signed_out_12_hours_after_signing_in(api, cf):
    client = fresh(api, cf)
    me = client.get("/api/me").json()
    assert me["session_ends_at"]
    session = client.session
    session[SIGNED_IN_KEY] = time.time() - 12 * HOURS + 60
    session.save()
    assert client.get("/api/me").status_code == 200          # a minute to go
    session = client.session
    session[SIGNED_IN_KEY] = time.time() - 12 * HOURS - 1
    session.save()
    ended = client.get("/api/contacts/")
    assert ended.status_code == 401 and "12 hours since you signed in" in ended.json()["detail"]
    assert client.get("/api/me").status_code == 401


@pytest.mark.django_db
def test_a_session_from_before_the_rule_gets_its_twelve_hours_from_now(api, cf):
    client = api.as_(cf)
    session = client.session
    session.pop(SIGNED_IN_KEY, None)
    session.save()
    assert client.get("/api/me").status_code == 200
    assert time.time() - client.session[SIGNED_IN_KEY] < 5


@pytest.mark.django_db
def test_the_pay_link_and_the_signing_link_need_no_session(client):
    """No session, no sign-in: twelve hours and two-factor never reach them."""
    assert client.get("/api/pay/not-a-real-token").status_code == 404
    assert client.get("/api/sign/not-a-real-token").status_code == 404


# ------------------------------------------------------------- People

@pytest.fixture
def acme(seeded_tenant, ff):
    """People on; Acme with its owner, a senior leader, a manager with a
    report, the report, someone with no record; and a second company."""
    from apps.crm.services.secrets import encrypt

    people_on(seeded_tenant, ff)
    t = seeded_tenant
    company = ClientCompanyFactory(tenant=t, name="Acme Fasteners")
    other = ClientCompanyFactory(tenant=t, name="Globex")
    owner = _member(t, "FCC", company=company)
    leader = ClientTeamMemberFactory(tenant=t, level="leader",
                                     membership=_member(t, "ECC", company=company)).membership
    manager = _member(t, "ECC", company=company)
    employee = _member(t, "ECC", company=company)
    nobody = _member(t, "ECC", company=company)
    other_owner = _member(t, "FCC", company=other)

    def person(first, user=None, boss=None, at=company, pay="$31.00 an hour"):
        row = PersonRecord.all_objects.create(
            tenant=t, client_company=at, first_name=first, last_name="Placeholder",
            title="Machinist", user=user, manager=boss,
            sensitive_ciphertext=encrypt(json.dumps({
                "pay_rate": pay, "home_address": f"{first}'s home, Tucson",
                "date_of_birth": "1990-04-02", "personal_phone": "520-555-0100",
                "personal_email": f"{first.lower()}@home.invalid",
                "emergency_contact": "A sibling", "documents": ["Offer letter"]})))
        return row

    marvin = person("Marvin", manager.user)
    daffy = person("Daffy", employee.user, boss=marvin)
    elmer = person("Elmer")
    globex = person("Hank", at=other, pay="$99.99 an hour")
    return SimpleNamespace(company=company, other=other, owner=owner, leader=leader,
                           manager=manager, employee=employee, nobody=nobody,
                           other_owner=other_owner, marvin=marvin, daffy=daffy, elmer=elmer,
                           globex=globex)


def scope(company):
    return f"/api/people/{company.pk}/"


def ready(api, member, clock):
    """Enrolled and verified: past every two-factor gate."""
    secret, _ = enroll(api, member, clock)
    return api.as_(member), secret


@pytest.mark.django_db
def test_with_people_off_nobody_reaches_anything(api, ff, seeded_tenant, clock):
    company = ClientCompanyFactory(tenant=seeded_tenant)
    client, _ = ready(api, ff, clock)
    assert client.get("/api/people/").status_code == 404
    assert client.get(scope(company)).status_code == 404
    assert client.get("/api/me").json()["people"] is False


@pytest.mark.django_db
def test_an_hr_holder_must_enroll_before_any_people_screen(api, ff, acme, clock):
    client = api.as_(ff)
    refused = client.get(scope(acme.company))
    assert refused.status_code == 403 and refused.json()["two_factor"] == "enroll"
    assert client.get("/api/people/").json()["two_factor"] == "enroll"
    ready(api, ff, clock)
    assert client.get(scope(acme.company)).status_code == 200


@pytest.mark.django_db
def test_people_screens_ask_again_after_four_hours(api, ff, acme, clock):
    client, secret = ready(api, ff, clock)
    assert client.get(scope(acme.company)).status_code == 200
    session = client.session
    session[tf.SESSION_VERIFIED] = time.time() - 4 * HOURS - 60
    session.save()
    asked = client.get(scope(acme.company))
    assert asked.status_code == 403 and asked.json()["two_factor"] == "recheck"
    assert client.get("/api/contacts/").status_code == 200     # only People asks again
    assert verify(client, secret, clock).status_code == 200
    assert client.get(scope(acme.company)).status_code == 200


@pytest.mark.django_db
def test_the_practice_owner_is_hr_director_and_every_unmasked_view_is_logged(api, ff, acme,
                                                                             clock):
    client, _ = ready(api, ff, clock)
    page = client.get(scope(acme.company), HTTP_USER_AGENT="Chrome test").json()
    assert page["level"] == "director" and page["guidance"] == "HR guidance, not legal advice"
    daffy = next(r for r in page["records"] if r["first_name"] == "Daffy")
    assert daffy["sensitive"]["pay_rate"] == "$31.00 an hour" and daffy["masked"] is False
    assert daffy["manager"]["name"] == "Marvin Placeholder"
    with tenant_context(acme.company.tenant_id):
        logged = PeopleAccessLog.objects.filter(person=acme.daffy)
        assert logged.count() == 1
        row = logged.get()
    assert row.action == "view" and row.actor_id == ff.user_id and "pay_rate" in row.fields
    assert row.user_agent == "Chrome test" and row.ip_address
    # Another company of the practice: also the owner's.
    assert client.get(scope(acme.other)).json()["level"] == "director"


@pytest.mark.django_db
def test_a_generalist_sees_sensitive_fields_masked_and_changes_nothing(api, ff, cf, acme, clock):
    HRGrant.all_objects.create(tenant=acme.company.tenant, user=cf.user, level="generalist",
                               client_company=acme.company, granted_by=ff.user)
    client, _ = ready(api, cf, clock)
    page = client.get(scope(acme.company)).json()
    assert page["level"] == "generalist"
    marvin = next(r for r in page["records"] if r["first_name"] == "Marvin")
    assert marvin["masked"] is True and marvin["sensitive"]["pay_rate"] == A.MASK
    assert marvin["sensitive"]["documents"] == "1 document"
    assert "$31.00" not in json.dumps(page) and "Tucson" not in json.dumps(page)
    with tenant_context(acme.company.tenant_id):
        assert not PeopleAccessLog.objects.exists()          # nothing sensitive was shown
    # Break attempts: change a person, add one, open a company not granted.
    assert client.patch(f"{scope(acme.company)}records/{acme.marvin.pk}/",
                        data=json.dumps({"sensitive": {"pay_rate": "$1"}}),
                        content_type="application/json").status_code == 403
    assert post(client, f"{scope(acme.company)}records/", {"first_name": "X"}).status_code == 403
    assert client.get(scope(acme.other)).status_code == 404
    assert client.get(f"{scope(acme.company)}access-log/").status_code == 404


@pytest.mark.django_db
def test_a_director_grant_sees_all_and_a_change_and_an_export_are_logged(api, ff, cf, acme,
                                                                          clock):
    HRGrant.all_objects.create(tenant=acme.company.tenant, user=cf.user, level="director",
                               all_companies=True, granted_by=ff.user)
    client, _ = ready(api, cf, clock)
    changed = client.patch(f"{scope(acme.company)}records/{acme.marvin.pk}/",
                           data=json.dumps({"sensitive": {"pay_rate": "$33.00 an hour"}}),
                           content_type="application/json")
    assert changed.status_code == 200 and changed.json()["sensitive"]["pay_rate"] == \
        "$33.00 an hour"
    exported = client.get(f"{scope(acme.company)}export/")
    assert exported.status_code == 200 and b"$33.00 an hour" in exported.content
    with tenant_context(acme.company.tenant_id):
        actions = sorted(PeopleAccessLog.objects.filter(person=acme.marvin)
                         .values_list("action", flat=True))
    assert actions == ["change", "export"]
    assert PeopleAccessLog.all_objects.get(person=acme.marvin, action="change").fields == \
        ["pay_rate"]


@pytest.mark.django_db
def test_sensitive_fields_are_encrypted_at_rest(acme):
    with connection.cursor() as cursor:
        cursor.execute("SELECT sensitive_ciphertext::text FROM person_record")
        stored = " ".join(row[0] for row in cursor.fetchall())
    for plain in ("31.00", "Tucson", "1990-04-02", "520-555-0100", "home.invalid", "Offer letter"):
        assert plain not in stored


@pytest.mark.django_db
def test_a_client_owner_is_hr_director_of_their_own_company_only(api, acme, clock):
    client, _ = ready(api, acme.owner, clock)
    assert client.get(scope(acme.company)).json()["level"] == "director"
    for elsewhere in (scope(acme.other), "/api/people/practice/"):
        assert client.get(elsewhere).status_code == 404
    home = client.get("/api/people/").json()
    assert [s["key"] for s in home["scopes"]] == [str(acme.company.pk)]
    grant = post(client, f"{scope(acme.company)}permissions/",
                 {"member": str(acme.employee.pk), "level": "generalist"})
    assert grant.status_code == 201, grant.content
    # Break attempts: grant to someone of another company, or everywhere.
    assert post(client, f"{scope(acme.company)}permissions/",
                {"member": str(acme.other_owner.pk), "level": "director"}).status_code == 400
    everywhere = post(client, f"{scope(acme.company)}permissions/",
                      {"member": str(acme.manager.pk), "level": "director", "all": True})
    assert everywhere.status_code == 201
    assert HRGrant.all_objects.get(user=acme.manager.user).all_companies is False


@pytest.mark.django_db
def test_senior_leadership_sees_the_directory_of_everyone_and_nothing_sensitive(api, acme):
    page = api.as_(acme.leader).get(scope(acme.company)).json()
    assert page["level"] == "directory"
    assert {r["first_name"] for r in page["records"]} == {"Marvin", "Daffy", "Elmer"}
    assert all("sensitive" not in r for r in page["records"])
    assert "31.00" not in json.dumps(page)


@pytest.mark.django_db
def test_a_manager_sees_their_reports_directory_and_their_own_record(api, acme):
    client = api.as_(acme.manager)
    page = client.get(scope(acme.company)).json()
    assert page["level"] == "reports"
    rows = {r["first_name"]: r for r in page["records"]}
    assert set(rows) == {"Marvin", "Daffy"}
    assert rows["Marvin"]["own"] and rows["Marvin"]["sensitive"]["pay_rate"] == "$31.00 an hour"
    assert "sensitive" not in rows["Daffy"]
    # Break attempt: someone who isn't their report, by id.
    assert client.get(f"{scope(acme.company)}records/{acme.elmer.pk}/").status_code == 404


@pytest.mark.django_db
def test_an_employee_sees_their_own_record_only(api, acme):
    client = api.as_(acme.employee)
    page = client.get(scope(acme.company)).json()
    assert page["level"] == "self" and [r["first_name"] for r in page["records"]] == ["Daffy"]
    assert client.get(f"{scope(acme.company)}records/{acme.marvin.pk}/").status_code == 404
    assert client.get(f"{scope(acme.company)}export/").status_code == 403


@pytest.mark.django_db
def test_nobody_else_gets_people_data_at_all_and_the_answer_is_404(api, acme, va, cf,
                                                                    seeded_tenant):
    stranger_practice = TenantFactory()
    stranger = _member(stranger_practice, "FF")
    for member in (acme.nobody, va, cf, stranger):
        client = api.as_(member)
        assert client.get("/api/people/").status_code == 404
        assert client.get(scope(acme.company)).status_code == 404
        assert client.get(f"{scope(acme.company)}records/{acme.daffy.pk}/").status_code == 404
        assert client.get("/api/me").json()["people"] is False


@pytest.mark.django_db
def test_two_factor_pending_reaches_no_people_screen(api, ff, acme, clock):
    enroll(api, ff, clock)
    client = fresh(api, ff)
    assert client.get(scope(acme.company)).status_code == 403
    assert client.get(scope(acme.company)).json()["two_factor_pending"] is True


@pytest.mark.django_db
def test_the_access_log_is_read_by_the_owners_for_their_scope_and_edited_by_nobody(
        api, ff, acme, clock):
    owner, _ = ready(api, ff, clock)
    owner.get(scope(acme.company))
    owner.get(scope(acme.other))
    log = owner.get(f"{scope(acme.company)}access-log/").json()["entries"]
    assert {e["person"] for e in log} == {"Marvin Placeholder", "Daffy Placeholder",
                                          "Elmer Placeholder"}
    client_owner, _ = ready(api, acme.owner, clock)
    theirs = client_owner.get(f"{scope(acme.company)}access-log/").json()["entries"]
    assert "Hank Placeholder" not in {e["person"] for e in theirs}
    # Nobody can edit it: no route changes it, and the database refuses too.
    assert owner.post(f"{scope(acme.company)}access-log/").status_code == 405
    assert owner.delete(f"{scope(acme.company)}access-log/").status_code == 405
    row = PeopleAccessLog.all_objects.first()
    with pytest.raises(PermissionError):
        row.save()
    with pytest.raises(PermissionError):
        row.delete()
    with pytest.raises(PermissionError):
        PeopleAccessLog.all_objects.filter(pk=row.pk).update(action="export")
    with pytest.raises(PermissionError):
        PeopleAccessLog.all_objects.filter(pk=row.pk).delete()


@pytest.mark.django_db
def test_the_practice_owner_grants_either_level_for_a_company_or_for_all(api, ff, cf, va, acme,
                                                                       clock):
    client, _ = ready(api, ff, clock)
    page = client.get(f"{scope(acme.company)}permissions/").json()
    assert {p["id"] for p in page["grantable"]} == {str(cf.pk), str(va.pk)}
    assert page["may_grant_all"] is True
    done = post(client, f"{scope(acme.company)}permissions/",
                {"member": str(va.pk), "level": "director", "all": True})
    assert done.status_code == 201 and done.json()["scope"] == "all"
    # Holding it now, the assistant must enroll before People opens.
    refused = api.as_(va).get(scope(acme.other))
    assert refused.status_code == 403 and refused.json()["two_factor"] == "enroll"
    revoked = post(client, f"{scope(acme.company)}permissions/{done.json()['id']}/revoke/")
    assert revoked.status_code == 200
    assert api.as_(va).get(scope(acme.other)).status_code == 404


# ------------------------------------------------- AI apps never see it

@pytest.mark.django_db
def test_no_ai_app_tool_returns_people_data_and_search_leaves_it_out(acme, ff):
    from apps.aiconnect import tools
    from apps.crm.services import search

    markers = ["Marvin", "Daffy", "Elmer", "Placeholder", "31.00", "Tucson", "home.invalid",
               "Offer letter", "520-555"]
    p = tools.Principal(connection=SimpleNamespace(membership=ff, user=ff.user))
    company = str(acme.company.pk)
    seen = []
    with tenant_context(ff.tenant_id):
        for tool in tools.READ_TOOLS:
            args = {}
            names = tool.__code__.co_varnames[:tool.__code__.co_argcount]
            for name in names[1:]:
                args[name] = {"company_id": company, "query": "Placeholder"}.get(name, None)
            try:
                result = tool(p, **{k: v for k, v in args.items() if v is not None})
            except Exception as exc:  # noqa: BLE001 — a refusal says nothing either
                result = str(exc)
            seen.append(json.dumps(result, default=str))
        found = search.search(ff.tenant, "Placeholder")
    text = " ".join(seen) + json.dumps(found, default=str)
    for marker in markers:
        assert marker not in text, marker
    names = {t.__name__ for t in tools.READ_TOOLS + tools.WRITE_TOOLS}
    assert not {n for n in names if "people" in n or "person" in n or "hr_" in n}


def test_no_ai_or_ai_app_code_reaches_people():
    """Connected AI apps never receive People data, and in-app AI reads a
    record only when a person presses an action on it: no AI code imports
    People, and People imports no AI."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "apps"
    for path in list((root / "aiconnect").rglob("*.py")) + [root / "tenancy" / "claude.py",
                                                           root / "tenancy" / "ai_actions.py"]:
        assert "apps.people" not in path.read_text(), path
    for path in (root / "people").rglob("*.py"):
        text = path.read_text()
        assert "anthropic" not in text and "tenancy.claude" not in text, path


# ------------------------------------------------------------ the catalog

@pytest.mark.django_db
def test_people_is_available_at_50_and_free_for_the_platform_owners_practice(api, ff,
                                                                             seeded_tenant):
    from apps.billing.models import PracticeSubscriptionAddon
    from apps.centers import services as centers

    state = api.as_(ff).get("/api/command-centers/").json()
    people = next(c for c in state["centers"] if c["code"] == "people")
    assert people["status"] == "available" and people["price_cents"] == 5000
    people_on(seeded_tenant, ff)
    assert PracticeSubscriptionAddon.all_objects.filter(addon__code="center_people").count() == 1
    home = TenantFactory()
    platform = _member(home, "FF")
    platform.user.is_platform_owner = True
    platform.user.save()
    assert "Included for your practice" in centers.price_line(home)
    with tenant_context(home.pk):
        centers.switch(home, "people", True, actor=platform.user)
    assert PracticeSubscriptionAddon.all_objects.filter(tenant=home).count() == 0


# --------------------------------------------------------------- the demo

@pytest.mark.django_db
def test_the_demo_lets_visitors_try_two_factor_and_never_asks_for_it(api, ff, acme, clock,
                                                                     settings):
    settings.IS_DEMO = True
    secret, _ = enroll(api, ff, clock)
    client = fresh(api, ff)
    assert client.get("/api/me").json()["two_factor_pending"] is False
    assert client.get(scope(acme.company)).status_code == 200
    assert client.get("/api/me/two-factor").json()["demo"] is True
