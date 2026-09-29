"""Contact matching and merging (owner, 2026-09-29).

1. The meeting queue's candidates are looked up when the proposal is opened,
   with what tells same-named people apart, for participants and for an
   action item's owner.
2. "Merge duplicates": groups across the whole book, merged in one click.
3. The merge behind it now moves everything that points at a contact. Before
   today it moved only Module 1's tables, so a merged contact kept its
   meetings, commitments, stakeholder rows and unsubscribes on the record
   that was merged away.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.crm.models import Contact, ContactPipelinePosition, EmailSuppression, Enrollment
from apps.crm.services import duplicates, merge
from apps.meetings import ingest
from apps.meetings.models import Commitment, DriveWatch, MeetingParticipant, ProposalItem
from apps.strategy.models import StrategySession
from apps.tenancy.models import Membership
from apps.work.models import Stakeholder

from . import registry_config  # noqa: F401
from .factories import (
    ClientCompanyFactory, CommitmentFactory, CompanyFactory, ContactEmailFactory,
    ContactFactory, ContactPipelinePositionFactory, EmailSuppressionFactory,
    EnrollmentFactory, MeetingFactory, MeetingParticipantFactory, MembershipFactory,
    PipelineFactory, PipelineStageFactory, StakeholderFactory, StrategySessionFactory,
    TaskFactory,
)
from .test_module5_acceptance import NOTES, PARSED, FakeDrive, a_file, one_page


def person(tenant, first, last, email=None, **kw):
    contact = ContactFactory(tenant=tenant, first_name=first, last_name=last, **kw)
    if email:
        ContactEmailFactory(tenant=tenant, contact=contact, address=email, is_primary=True)
    return contact


# ================================================================ the groups

@pytest.mark.django_db
def test_groups_by_email_case_insensitively_and_by_normalized_name(seeded_tenant, in_tenant_a):
    a = person(seeded_tenant, "Mike", "Eller", "Eller.Mike@populist.test")
    b = person(seeded_tenant, "Michael", "Eller", "eller.mike@populist.test")
    c = person(seeded_tenant, "Richard", "Hein")
    d = person(seeded_tenant, "richard ", "Hein.")
    person(seeded_tenant, "Someone", "Else")
    found = {frozenset(x["id"] for x in g["contacts"]): g["reasons"]
             for g in duplicates.groups(Contact.objects.all())}
    assert found == {
        frozenset({str(a.pk), str(b.pk)}): ["same email address"],
        frozenset({str(c.pk), str(d.pk)}): ["same name"],
    }


@pytest.mark.django_db
def test_one_person_caught_by_both_rules_is_one_group(seeded_tenant, in_tenant_a):
    a = person(seeded_tenant, "Dana", "Reyes", "dana@acme.test")
    b = person(seeded_tenant, "Dana", "Reyes")
    c = person(seeded_tenant, "D", "Reyes", "dana@acme.test")
    [group] = duplicates.groups(Contact.objects.all())
    assert {x["id"] for x in group["contacts"]} == {str(a.pk), str(b.pk), str(c.pk)}
    assert group["reasons"] == ["same email address", "same name"]


@pytest.mark.django_db
def test_a_first_name_alone_is_not_a_name_match(seeded_tenant, in_tenant_a):
    person(seeded_tenant, "Tim", "")
    person(seeded_tenant, "Tim", "")
    assert duplicates.groups(Contact.objects.all()) == []


@pytest.mark.django_db
def test_the_suggested_survivor_carries_the_most_history(seeded_tenant, in_tenant_a):
    thin = person(seeded_tenant, "Ross", "Aymami")
    rich = person(seeded_tenant, "Ross", "Aymami")
    TaskFactory(tenant=seeded_tenant, contact=rich)
    MeetingParticipantFactory(tenant=seeded_tenant, contact=rich)
    [group] = duplicates.groups(Contact.objects.all())
    assert group["suggested_survivor"] == str(rich.pk)
    member = next(m for m in group["contacts"] if m["id"] == str(rich.pk))
    assert (member["tasks"], member["meetings"]) == (1, 1)
    assert str(thin.pk) in {m["id"] for m in group["contacts"]}


# ============================================================= the endpoints

@pytest.mark.django_db
def test_merge_group_merges_every_other_into_the_survivor(seeded_tenant, in_tenant_a, ff, api):
    acme = CompanyFactory(tenant=seeded_tenant)
    keep = person(seeded_tenant, "Mike", "Eller", "eller.mike@populist.test", title="")
    gone1 = person(seeded_tenant, "Mike", "Eller", title="Visionary", company=acme)
    gone2 = person(seeded_tenant, "Mike", "Eller", "mike@other.test", title="Owner")
    response = api.as_(ff).post("/api/contacts/merge-group/", {
        "survivor": str(keep.pk), "absorbed": [str(gone1.pk), str(gone2.pk)]},
        content_type="application/json")
    assert response.status_code == 200, response.content
    keep.refresh_from_db()
    assert keep.title == "Visionary", "an empty field takes the first value held"
    assert keep.company_id == acme.pk
    assert sorted(keep.emails.values_list("address", flat=True)) == [
        "eller.mike@populist.test", "mike@other.test"]
    for gone in (gone1, gone2):
        gone.refresh_from_db()
        assert gone.deleted_at is not None and gone.merged_into_id == keep.pk
    assert duplicates.groups(Contact.objects.filter(deleted_at__isnull=True)) == []


@pytest.mark.django_db
def test_merge_group_is_all_or_nothing(seeded_tenant, in_tenant_a, ff, api):
    keep = person(seeded_tenant, "A", "B")
    other = person(seeded_tenant, "A", "B")
    response = api.as_(ff).post("/api/contacts/merge-group/", {
        "survivor": str(keep.pk),
        "absorbed": [str(other.pk), "00000000-0000-0000-0000-000000000000"]},
        content_type="application/json")
    assert response.status_code == 404
    other.refresh_from_db()
    assert other.deleted_at is None


@pytest.mark.django_db
def test_merge_group_refuses_the_survivor_as_absorbed(seeded_tenant, in_tenant_a, ff, api):
    keep = person(seeded_tenant, "A", "B")
    response = api.as_(ff).post("/api/contacts/merge-group/", {
        "survivor": str(keep.pk), "absorbed": [str(keep.pk)]}, content_type="application/json")
    assert response.status_code == 400


@pytest.mark.django_db
@pytest.mark.parametrize("role,expected", [
    ("FF", 200), ("VA", 200), ("CF", 403), ("FCC", 403), ("ECC", 403)])
def test_role_boundaries_duplicates_follow_merge(role, expected, seeded_tenant, in_tenant_a, api):
    """Matrix 4.5: merge is FF and VA. The list of groups is its way in."""
    keep = person(seeded_tenant, "A", "B")
    other = person(seeded_tenant, "A", "B")
    company = ClientCompanyFactory(tenant=seeded_tenant) if role in ("FCC", "ECC") else None
    member = MembershipFactory(tenant=seeded_tenant, role=role, client_company=company)
    client = api.as_(member)
    assert client.get("/api/contacts/duplicate-groups/").status_code == expected
    response = client.post("/api/contacts/merge-group/", {
        "survivor": str(keep.pk), "absorbed": [str(other.pk)]}, content_type="application/json")
    assert response.status_code == expected
    other.refresh_from_db()
    assert (other.deleted_at is not None) is (expected == 200)


@pytest.mark.django_db
def test_tenant_isolation_groups_and_merges_stay_in_the_tenant(tenant_a, tenant_b, api):
    from apps.tenancy.context import tenant_context

    with tenant_context(tenant_b.pk):
        theirs = person(tenant_b, "Dana", "Reyes", "dana@acme.test")
    with tenant_context(tenant_a.pk):
        mine = person(tenant_a, "Dana", "Reyes", "dana@acme.test")
        ff = MembershipFactory(tenant=tenant_a, role="FF")
    client = api.as_(ff)
    assert client.get("/api/contacts/duplicate-groups/").json() == [], \
        "a same-named, same-address contact in another practice is not a duplicate"
    response = client.post("/api/contacts/merge-group/", {
        "survivor": str(mine.pk), "absorbed": [str(theirs.pk)]}, content_type="application/json")
    assert response.status_code == 404
    with tenant_context(tenant_b.pk):
        theirs.refresh_from_db()
        assert theirs.deleted_at is None


# ============================================== the merge leaves nothing behind

def test_every_contact_relation_has_a_merge_rule():
    """A table added later that points at contacts fails here until the merge
    says what happens to it."""
    relations = {f"{r.related_model._meta.db_table}.{r.field.name}"
                 for r in Contact._meta.related_objects}
    assert relations - merge.HANDLED_RELATIONS == set()


@pytest.mark.django_db
def test_merge_moves_meetings_commitments_sessions_and_logins(seeded_tenant, in_tenant_a):
    keep, gone = person(seeded_tenant, "Mike", "Eller"), person(seeded_tenant, "Mike", "Eller")
    shared = MeetingFactory(tenant=seeded_tenant)
    MeetingParticipantFactory(tenant=seeded_tenant, meeting=shared, contact=keep)
    MeetingParticipantFactory(tenant=seeded_tenant, meeting=shared, contact=gone)
    only_gone = MeetingParticipantFactory(tenant=seeded_tenant, contact=gone)
    commitment = CommitmentFactory(tenant=seeded_tenant, contact=gone)
    session = StrategySessionFactory(tenant=seeded_tenant, contact=gone)
    login = MembershipFactory(tenant=seeded_tenant, role="ECC",
                              client_company=ClientCompanyFactory(tenant=seeded_tenant))
    Membership.all_objects.filter(pk=login.pk).update(contact=gone)

    merge.merge_contacts(keep, gone)

    assert set(MeetingParticipant.objects.filter(contact=keep).values_list(
        "meeting_id", flat=True)) == {shared.pk, only_gone.meeting_id}
    assert not MeetingParticipant.objects.filter(contact=gone).exists()
    assert Commitment.objects.get(pk=commitment.pk).contact_id == keep.pk
    assert StrategySession.objects.get(pk=session.pk).contact_id == keep.pk
    assert Membership.all_objects.get(pk=login.pk).contact_id == keep.pk


@pytest.mark.django_db
def test_an_unsubscribe_follows_the_person(seeded_tenant, in_tenant_a):
    """Otherwise merging a duplicate makes someone who unsubscribed mailable."""
    keep, gone = person(seeded_tenant, "A", "B"), person(seeded_tenant, "A", "B")
    EmailSuppressionFactory(tenant=seeded_tenant, contact=gone, category="marketing")
    merge.merge_contacts(keep, gone)
    assert EmailSuppression.objects.filter(contact=keep, category="marketing",
                                           lifted_at__isnull=True).exists()


@pytest.mark.django_db
def test_where_both_hold_the_same_thing_the_survivor_wins(seeded_tenant, in_tenant_a):
    keep, gone = person(seeded_tenant, "A", "B"), person(seeded_tenant, "A", "B")
    task = TaskFactory(tenant=seeded_tenant)
    StakeholderFactory(tenant=seeded_tenant, contact=keep, task=task, cadence="weekly")
    StakeholderFactory(tenant=seeded_tenant, contact=gone, task=task, cadence="every_update")
    pipeline = PipelineFactory(tenant=seeded_tenant)
    stage = PipelineStageFactory(tenant=seeded_tenant, pipeline=pipeline)
    ContactPipelinePositionFactory(tenant=seeded_tenant, contact=keep, pipeline=pipeline,
                                   stage=stage)
    ContactPipelinePositionFactory(tenant=seeded_tenant, contact=gone, pipeline=pipeline,
                                   stage=stage)
    EnrollmentFactory(tenant=seeded_tenant, contact=keep)
    theirs = EnrollmentFactory(tenant=seeded_tenant, contact=gone)

    merge.merge_contacts(keep, gone)

    [row] = Stakeholder.objects.filter(task=task)
    assert (row.contact_id, row.cadence) == (keep.pk, "weekly")
    assert ContactPipelinePosition.objects.filter(contact=keep).count() == 1
    theirs.refresh_from_db()
    assert theirs.ended_at is not None, "the merged-away record cannot keep a live enrollment"
    assert Enrollment.objects.filter(contact=keep, ended_at__isnull=True).count() == 1


# ======================================= the queue: live candidates, owners

@pytest.fixture
def watch(seeded_tenant, in_tenant_a):
    return DriveWatch.objects.create(tenant=seeded_tenant, folder_id="folder-1")


def _proposal(seeded_tenant, fake_claude):
    fake_claude.reply = PARSED
    ingest.poll(seeded_tenant, client=FakeDrive(pages=one_page([a_file("f1")]),
                                                texts={"f1": NOTES}))


@pytest.mark.django_db
def test_a_contact_created_after_the_parse_is_a_candidate(seeded_tenant, watch, fake_claude,
                                                          ff, api):
    _proposal(seeded_tenant, fake_claude)
    item = ProposalItem.objects.get(payload__parsed_name="Tom Okafor")
    assert item.payload["existing_candidates"] == []
    tom = person(seeded_tenant, "Tom", "Okafor", "tom@elsewhere.test",
                 company=CompanyFactory(tenant=seeded_tenant, name="Okafor Logistics"))
    MeetingParticipantFactory(tenant=seeded_tenant, contact=tom,
                              meeting=MeetingFactory(tenant=seeded_tenant,
                                                     meeting_date=timezone.localdate()))
    body = api.as_(ff).get(f"/api/meeting-proposals/{item.proposal_id}/").json()
    row = next(i for i in body["items"] if i["id"] == str(item.pk))
    [candidate] = row["candidates"]
    assert candidate["contact_id"] == str(tom.pk)
    assert candidate["company"] == "Okafor Logistics"
    assert candidate["emails"] == ["tom@elsewhere.test"]
    assert candidate["last_meeting"] == timezone.localdate().isoformat()


@pytest.mark.django_db
def test_an_ambiguous_owner_lists_everyone_it_could_be(seeded_tenant, watch, fake_claude,
                                                       ff, api):
    a = person(seeded_tenant, "Dana", "Reyes", "dana@one.test")
    b = person(seeded_tenant, "Dana", "Reyes", "dana@two.test")
    _proposal(seeded_tenant, fake_claude)
    item = ProposalItem.objects.get(kind=ProposalItem.Kind.ACTION_ITEM)
    assert item.payload["proposed_owner_contact_id"] is None, "two Danas: not guessed"
    body = api.as_(ff).get(f"/api/meeting-proposals/{item.proposal_id}/").json()
    row = next(i for i in body["items"] if i["id"] == str(item.pk))
    assert {c["contact_id"] for c in row["owner_candidates"]} == {str(a.pk), str(b.pk)}


@pytest.mark.django_db
def test_the_owner_the_reviewer_picks_is_the_one_recorded(seeded_tenant, watch, fake_claude,
                                                          ff, api):
    person(seeded_tenant, "Dana", "Reyes")
    b = person(seeded_tenant, "Dana", "Reyes")
    _proposal(seeded_tenant, fake_claude)
    item = ProposalItem.objects.get(kind=ProposalItem.Kind.ACTION_ITEM)
    response = api.as_(ff).post(f"/api/proposal-items/{item.pk}/approve/", {
        "owner_side": "other", "owner_kind": "client", "outcome": "record_only",
        "owner_contact_id": str(b.pk)}, content_type="application/json")
    assert response.status_code == 201, response.content
    assert Commitment.objects.get().contact_id == b.pk


@pytest.mark.django_db
def test_not_one_of_these_keeps_the_name_only(seeded_tenant, watch, fake_claude, ff, api):
    person(seeded_tenant, "Dana", "Reyes")
    person(seeded_tenant, "Dana", "Reyes")
    _proposal(seeded_tenant, fake_claude)
    item = ProposalItem.objects.get(kind=ProposalItem.Kind.ACTION_ITEM)
    response = api.as_(ff).post(f"/api/proposal-items/{item.pk}/approve/", {
        "owner_side": "other", "owner_kind": "client", "outcome": "record_only",
        "owner_contact_id": None}, content_type="application/json")
    assert response.status_code == 201, response.content
    commitment = Commitment.objects.get()
    assert commitment.contact_id is None and commitment.owner_name == "Dana Reyes"
