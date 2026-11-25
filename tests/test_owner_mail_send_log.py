"""Owner agreement, intake and code mail in the send log (owner, 2026-11-24,
after the demo walk).

Owner-agreement emails, intake notices and tax-number code emails show in the
Outbox send log only to people with the matching tick for that company on
People and permissions; the practice owner always does. An Assistant who
isn't ticked sees none of them. A code email shows only to the person it went
to and the practice owner. The same rule holds wherever the send log's rows
show: the Activity feed, the shared email history, and the Sending queue (and
so the AI apps' sending_queue tool, which reads it).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from apps.agreements.models import Program, StaffAccess
from apps.crm import permissions as crm_perms
from apps.crm.models import OutboxMessage
from apps.crm.services import outbox
from apps.intake import taxnumbers
from apps.tenancy.context import tenant_context
from apps.tenancy.models import ClientAssignment

from .factories import ClientCompanyFactory, MembershipFactory
from .test_agreements import aw, create, owner_signs  # noqa: F401
from .test_intake_flow import as_, fake, world  # noqa: F401
from .test_tax_numbers import tick, with_ssn

pytestmark = pytest.mark.django_db

OWNER_MAIL = {"owner_agreement", "owner_agreement_notice", "intake_notice", "tax_number_code"}


@pytest.fixture
def sent(aw, fake, monkeypatch):
    """Mail of every kind, made by the app's own flows: an owner agreement
    sent and signed (the owner's emails and the team's notices), an intake
    submitted (its notices), a code to Jackie and one to the practice owner,
    and one ordinary message that has nothing to do with any of it."""
    w = aw
    a = create(w)
    assert as_(w["jackie"]).post(f"/api/agreements/{a.pk}/send").status_code == 200
    owner_signs(a)
    sub, _, _ = with_ssn(w)
    monkeypatch.setattr(taxnumbers.pysecrets, "randbelow", lambda n: 482913)
    tick(w, "manager")
    tick(w, "ff")
    for who in ("manager", "ff"):
        r = as_(w[who]).post(f"/api/intake/submissions/{sub.pk}/tax-code")
        assert r.status_code == 200, r.content
    with tenant_context(w["practice"].pk):
        outbox.create_message(tenant=w["practice"], producer=OutboxMessage.Producer.CLIENT_ACTIVITY,
                              to_address=w["ff"].user.email, subject="An ordinary notice",
                              body_text="Nothing to do with owners.")
    mail = OutboxMessage.all_objects.filter(tenant=w["practice"])
    assert set(mail.values_list("producer", flat=True)) >= OWNER_MAIL | {"client_activity"}
    w["mail"] = mail
    w["codes"] = {m.to_address: m for m in mail.filter(producer="tax_number_code")}
    assert set(w["codes"]) == {w["manager"].user.email, w["ff"].user.email}
    return w


def outbox_rows(member) -> list[dict]:
    r = as_(member).get("/api/outbox/")
    assert r.status_code == 200, r.content
    return r.json()


def producers(rows) -> set[str]:
    return {r["producer"] for r in rows}


def subjects(member, path) -> set[str]:
    data = as_(member).get(path).json()
    rows = data.get("entries", data) if isinstance(data, dict) else data
    return {r.get("subject") or (r.get("entity") or {}).get("title") or "" for r in rows}


def owner_subjects(w) -> set[str]:
    return set(w["mail"].filter(producer__in=OWNER_MAIL).values_list("subject", flat=True))


def test_the_practice_owner_sees_all_of_it(sent):
    rows = outbox_rows(sent["ff"])
    assert producers(rows) >= OWNER_MAIL
    # Both codes: the one sent to them, and the one sent to Jackie.
    assert {r["to_address"] for r in rows if r["producer"] == "tax_number_code"} == set(
        sent["codes"])
    assert owner_subjects(sent) <= subjects(sent["ff"], "/api/activity/")
    assert owner_subjects(sent) <= subjects(sent["ff"], "/api/email-threads/")


def test_an_assistant_who_isnt_ticked_sees_none_of_it_and_the_rest_as_before(sent):
    rows = outbox_rows(sent["va"])
    assert not producers(rows) & OWNER_MAIL
    assert "An ordinary notice" in {r["subject"] for r in rows}
    # Nor anywhere else the send log's rows show.
    assert not owner_subjects(sent) & subjects(sent["va"], "/api/activity/")
    threads = subjects(sent["va"], "/api/email-threads/")
    assert not owner_subjects(sent) & threads and "An ordinary notice" in threads
    for message in sent["mail"].filter(producer__in=OWNER_MAIL):
        assert as_(sent["va"]).get(f"/api/outbox/{message.pk}/").status_code == 404
        if message.thread_id:
            assert as_(sent["va"]).get(
                f"/api/email-threads/{message.thread_id}/").status_code == 404


def test_an_associate_on_the_company_sees_none_of_it(sent):
    ClientAssignment.all_objects.create(tenant=sent["practice"], user=sent["cf"].user,
                                        company=sent["company"])
    assert not producers(outbox_rows(sent["cf"])) & OWNER_MAIL
    assert not owner_subjects(sent) & subjects(sent["cf"], "/api/activity/")


def test_the_waiting_queue_and_the_ai_apps_read_the_same_rule(sent):
    """A message of these kinds never waits (each goes straight to sent), but
    if one did, the Sending queue would leave it out for the Assistant."""
    waiting = OutboxMessage.all_objects.filter(producer="owner_agreement")
    ids = {f"outbox:{pk}" for pk in waiting.values_list("pk", flat=True)}
    assert ids
    waiting.update(state=OutboxMessage.State.PENDING_APPROVAL)
    keys = lambda member: {r["key"] for r in as_(member).get(  # noqa: E731
        "/api/sending-queue/").json()}
    assert ids <= keys(sent["ff"])
    assert not ids & keys(sent["va"])


def request_of(member):
    return SimpleNamespace(membership=member, user=member.user)


def visible(member, w) -> set[tuple[str, str]]:
    qs = crm_perms.without_owner_mail(request_of(member), w["mail"])
    return {(m.producer, m.to_address) for m in qs if m.producer in OWNER_MAIL}


def test_each_tick_opens_its_own_mail_for_its_own_company_only(sent):
    """People with the ticks have no send log of their own today (it is the
    practice's staff's), so the rule itself is checked: what a ticked company
    user would be shown, through the same function every view uses."""
    w = sent
    every = {(m.producer, m.to_address) for m in w["mail"] if m.producer in OWNER_MAIL}
    kinds = lambda seen: {p for p, _ in seen}  # noqa: E731
    # Jackie: agreements, signed PDFs and intake; her own code, not the practice owner's.
    jackie = visible(w["jackie"], w)
    assert kinds(jackie) == OWNER_MAIL
    assert ("tax_number_code", w["manager"].user.email) in jackie
    assert ("tax_number_code", w["ff"].user.email) not in jackie
    assert jackie == every - {("tax_number_code", w["ff"].user.email)}
    # Sandra: owner agreements only.
    assert kinds(visible(w["sandra"], w)) == {"owner_agreement", "owner_agreement_notice"}
    # Michael, the Client owner, ticked for intake by the world but not agreements.
    assert kinds(visible(w["michael"], w)) == {"intake_notice"}
    # The tick taken away: gone at once.
    StaffAccess.all_objects.filter(company=w["company"], user=w["sandra"].user).update(
        agreements=False)
    assert visible(w["sandra"], w) == set()


def test_a_tick_at_one_company_opens_nothing_at_another(sent, settings):
    w = sent
    other = ClientCompanyFactory(tenant=w["practice"], name="Other Stays",
                                 intake_forms_enabled=True)
    from django.core.management import call_command
    import io

    call_command("owner_agreements", str(other.pk), "on", stdout=io.StringIO())
    program = Program.all_objects.get(company=other)
    with tenant_context(w["practice"].pk):
        outbox.create_message(tenant=w["practice"], producer="owner_agreement_notice",
                              to_address="someone@other-stays.test", subject="Other's notice",
                              body_text="x", source_type="owner_agreement_program",
                              source_id=program.pk)
    w["mail"] = OutboxMessage.all_objects.filter(tenant=w["practice"])
    # Jackie is ticked at Mountain Stays, and is a user of it only.
    assert ("owner_agreement_notice", "someone@other-stays.test") not in visible(w["jackie"], w)
    # A user of the other company, ticked there, sees its notice and none of Mountain Stays'.
    theirs = MembershipFactory(tenant=w["practice"], role="ECC", client_company=other)
    StaffAccess.all_objects.create(tenant=w["practice"], company=other, user=theirs.user,
                                   agreements=True)
    assert visible(theirs, w) == {("owner_agreement_notice", "someone@other-stays.test")}
    # Mail with no source to trace it by is shut, not open.
    with tenant_context(w["practice"].pk):
        outbox.create_message(tenant=w["practice"], producer="owner_agreement_notice",
                              to_address="nobody@other-stays.test", subject="No source",
                              body_text="x")
    w["mail"] = OutboxMessage.all_objects.filter(tenant=w["practice"])
    assert ("owner_agreement_notice", "nobody@other-stays.test") not in visible(theirs, w)
    assert ("owner_agreement_notice", "nobody@other-stays.test") in {
        (m.producer, m.to_address) for m in crm_perms.without_owner_mail(
            request_of(w["ff"]), w["mail"])}
