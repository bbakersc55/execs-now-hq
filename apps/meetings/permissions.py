"""Who sees which proposal — matrix §11, and the `proposal-scope` rule.

**A meeting proposal usually precedes any company link**: matching participants
to contacts is the point of the queue, so an unmatched proposal has no company
to scope by. The tempting fix is to show unmatched proposals to everyone, and
it is wrong — a CF is not assigned to the FF's prospects and must not read the
FF's prospect meeting notes before anyone has decided they should.

So the CF's scope has **exactly two limbs**:

1. a participant is matched to a company the CF is assigned to, **or**
2. the source Drive file is owned by that CF — it was their own meeting.

Anything else is FF and VA only, which is the right default for an unreviewed
document. FF and VA see everything; a client role reaches none of it, ever.
"""

from __future__ import annotations

from django.db.models import Q

from apps.crm import permissions as crm_perms
from apps.meetings.models import MeetingProposal, MeetingSourceFile, ProposalItem
from apps.tenancy.models import CLIENT_ROLES, Role


def own_email(request) -> str:
    """The address the CF's Drive files are owned by. Their connected Google
    account where there is one, else the address they sign in with."""
    from apps.crm.models import GmailConnection

    connection = GmailConnection.objects.filter(user=request.user).first()
    if connection is not None and connection.email_address:
        return connection.email_address.lower()
    return (getattr(request.user, "email", "") or "").lower()


def may_use(request) -> bool:
    """Module 5 has no client-facing surface at all — not even for a meeting
    about their own company. What reaches them is the task, once approved."""
    role = crm_perms.role_of(request)
    return role in (Role.FF, Role.CF, Role.VA)


def may_connect(request) -> bool:
    """Connecting the folder is the FF's (matrix 11.10).

    Narrower than using the queue on purpose. Clearing the queue is the VA's
    job, but **pointing the app at a folder grants it a standing read of a
    Drive**, and choosing which folder that is belongs with the person who
    answers for the practice's data. A CF is not refused because they are less
    trusted — their own meetings are in there — but because there is one
    folder per practice and one owner of the decision.
    """
    return crm_perms.role_of(request) == Role.FF


def source_files_for(request, queryset=None):
    queryset = MeetingSourceFile.objects.all() if queryset is None else queryset
    role = crm_perms.role_of(request)
    if role in (Role.FF, Role.VA):
        return queryset
    if role != Role.CF:
        return queryset.none()
    return queryset.filter(
        Q(drive_file_owner_email__iexact=own_email(request))
        | Q(pk__in=_matched_file_ids(request))
    ).distinct()


def _matched_file_ids(request):
    """Files with a participant matched to a company this CF is assigned to.

    Read from the **created** contact where one exists, and from the ranked
    candidates where it does not — a proposal is in scope before it is actioned
    or it is no use to the person who has to action it.
    """
    from apps.crm.models import Contact

    assigned = set(crm_perms.assigned_company_ids(request))
    if not assigned:
        return []
    contacts = set(str(pk) for pk in Contact.objects.filter(
        company_id__in=assigned).values_list("pk", flat=True))
    if not contacts:
        return []
    found = []
    for item in ProposalItem.objects.filter(
            kind=ProposalItem.Kind.PARTICIPANT).select_related("proposal"):
        payload = item.payload or {}
        ids = {str(row.get("contact_id")) for row in
               (payload.get("existing_candidates") or [])}
        if item.created_record_type == "contact" and item.created_record_id:
            ids.add(str(item.created_record_id))
        if ids & contacts:
            found.append(item.proposal.source_file_id)
    return found


def proposals_for(request, queryset=None):
    queryset = MeetingProposal.objects.all() if queryset is None else queryset
    role = crm_perms.role_of(request)
    if role in (Role.FF, Role.VA):
        return queryset
    if role != Role.CF:
        return queryset.none()
    return queryset.filter(
        Q(source_file__drive_file_owner_email__iexact=own_email(request))
        | Q(source_file_id__in=_matched_file_ids(request))
    ).distinct()


def items_for(request, queryset=None):
    queryset = ProposalItem.objects.all() if queryset is None else queryset
    if crm_perms.role_of(request) in CLIENT_ROLES:
        return queryset.none()
    return queryset.filter(proposal__in=proposals_for(request))
