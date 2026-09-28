"""Who owns an action item, and what approving it should do (owner,
2026-09-28).

An action item owned by the practice is one of the practice's tasks, as it
always was. One owned by someone else — a client, a prospect, a vendor, a
third party — is a *commitment*: approving it makes a follow-up task for the
practice, records it on the person, or (for a client user with a portal seat)
makes it their task in their portal.

Claude proposes the owner from the notes; the classification below is the
proposal the reviewer confirms. It leans on facts the app already holds over
Claude's reading wherever it can: a name that is one of the practice's staff
is the practice, full stop; a contact with a portal seat is a client user.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

PRACTICE = "practice"
OTHER = "other"
KINDS = ("client", "prospect", "vendor", "third_party")

FOLLOW_UP, RECORD_ONLY, PORTAL = "follow_up", "record_only", "portal"
OUTCOMES = (FOLLOW_UP, RECORD_ONLY, PORTAL)

#: A commitment with no date of its own is checked on after this many days.
DEFAULT_FOLLOW_UP_DAYS = 7


def seat_for(contact):
    """The contact's active client portal membership, or None. A seat is the
    only thing that makes "Assign in the portal" possible: without one there
    is nobody to assign the task to."""
    if contact is None:
        return None
    from apps.tenancy.models import Membership

    return (Membership.objects.filter(contact=contact, role__in=("FCC", "ECC"),
                                      revoked_at__isnull=True,
                                      client_company__isnull=False)
            .select_related("user", "client_company").first())


def _kind_from_record(contact) -> str:
    """What the app already knows about this person, if anything."""
    if contact is None:
        return ""
    codes = set(contact.type_links.values_list("contact_type__code", flat=True))
    if "client" in codes or (contact.company_id and contact.company.is_client_company):
        return "client"
    if "vendor" in codes:
        return "vendor"
    if "prospect" in codes:
        return "prospect"
    return ""


def default_outcome(side: str, kind: str, has_seat: bool) -> str:
    """The owner's rule: Follow up for prospects and third parties; Assign in
    the portal for a client user with a seat; Record only otherwise."""
    if side != OTHER:
        return ""
    if has_seat:
        return PORTAL
    if kind in ("prospect", "third_party"):
        return FOLLOW_UP
    return RECORD_ONLY


def classify(tenant, *, owner_text: str, owner_contact_id=None, claude_side: str = "",
             claude_kind: str = "", roster=None) -> dict:
    """The owner classification for one action item, as payload fields."""
    from apps.crm.models import Contact
    from apps.meetings import practice

    owner_text = (owner_text or "").strip()
    if not owner_text:
        # Nobody named: the practice's to do, as before.
        return {"owner_side": "", "owner_kind": "", "owner_has_seat": False,
                "proposed_outcome": ""}
    member = practice.recognise(tenant, name=owner_text, roster=roster)
    if member is not None or claude_side == PRACTICE:
        return {"owner_side": PRACTICE, "owner_kind": "",
                "owner_practice_name": member.name if member else owner_text,
                "owner_has_seat": False, "proposed_outcome": ""}
    contact = (Contact.objects.filter(pk=owner_contact_id, deleted_at__isnull=True)
               .select_related("company").first() if owner_contact_id else None)
    seat = seat_for(contact)
    kind = ("client" if seat else _kind_from_record(contact)) or (
        claude_kind if claude_kind in KINDS else "third_party")
    return {"owner_side": OTHER, "owner_kind": kind, "owner_has_seat": seat is not None,
            "proposed_outcome": default_outcome(OTHER, kind, seat is not None)}


def default_follow_up(due_date):
    """The commitment's own date, or a week from today."""
    return due_date or (timezone.localdate() + timedelta(days=DEFAULT_FOLLOW_UP_DAYS))


# ------------------------------------------------- re-classifying the queue

CLASSIFY_PURPOSE = "meeting_owner_classify"

CLASSIFY_SYSTEM = """\
You are given the action items already drawn from one meeting's notes, each \
with the sentence it came from, and who was in the meeting. For each item, say \
who owns it: "practice" when the owner is the fractional executive or someone \
on their team, "other" when it is anyone else, "" when nobody is named. When \
"other", give "owner_kind": one of client, prospect, vendor, third_party, from \
how the notes describe them. Assert nothing the sentence does not carry.

Reply with JSON only: [{"item": 1, "owner_side": "", "owner_kind": ""}], one \
per item, in order. No prose, no markdown fence."""


def _norm(value: str) -> str:
    return " ".join((value or "").lower().split())


def confident(tenant, payload: dict, *, roster=None):
    """The classification the free rules can give with confidence, or None
    when Claude is needed (owner, 2026-09-28): nobody named; a staff name; or
    an exact match to a contact whose record (or portal seat) says what they
    are. Anything else — a first name only, an unknown name, a contact the
    records do not describe — goes to Claude."""
    from apps.crm.models import Contact
    from apps.meetings import practice

    owner = (payload.get("proposed_owner_text") or "").strip()
    if not owner:
        return classify(tenant, owner_text="")
    if practice.recognise(tenant, name=owner, roster=roster) is not None:
        return classify(tenant, owner_text=owner, roster=roster)
    contact_id = payload.get("proposed_owner_contact_id")
    contact = (Contact.objects.filter(pk=contact_id, deleted_at__isnull=True)
               .select_related("company").first() if contact_id else None)
    if contact is None or _norm(f"{contact.first_name} {contact.last_name}") != _norm(owner):
        return None
    if seat_for(contact) is None and not _kind_from_record(contact):
        return None
    return classify(tenant, owner_text=owner, owner_contact_id=contact.pk, roster=roster)


def tenant_of_context():
    from apps.tenancy.context import require_current_tenant_id
    from apps.tenancy.models import Tenant

    return Tenant.objects.get(pk=require_current_tenant_id())


def pending_to_classify():
    """Action items still waiting for review, on proposals still open, that
    have no owner classification yet. Reviewed meetings are left alone."""
    from apps.meetings.models import MeetingProposal, ProposalItem

    return (ProposalItem.objects
            .filter(kind=ProposalItem.Kind.ACTION_ITEM, state=ProposalItem.State.PENDING,
                    proposal__state__in=[MeetingProposal.State.PENDING,
                                         MeetingProposal.State.PARTIALLY_ACTIONED])
            .exclude(payload__has_key="owner_side")
            .select_related("proposal").order_by("proposal_id", "position"))


def _classify_input(proposal, items) -> str:
    from apps.meetings.models import ProposalItem

    people = [i.payload.get("parsed_name", "") for i in ProposalItem.objects.filter(
        proposal=proposal, kind=ProposalItem.Kind.PARTICIPANT)]
    lines = [f"Meeting: {proposal.title}", "In the meeting: " + ", ".join(p for p in people if p),
             ""]
    for n, item in enumerate(items, 1):
        lines.append(f"{n}. {item.payload.get('text', '')} — owner as noted: "
                     f"{item.payload.get('proposed_owner_text') or '(nobody named)'}\n"
                     f"   from: {item.source_excerpt}")
    return "\n".join(lines)


def _measured_per_item():
    """What classifying one item has actually cost, from the calls already
    made — or None before there are any. The first estimate (2026-09-28)
    assumed about 25 output tokens an item; the model's own reasoning is
    billed as output too, and real calls ran 100 to 375 an item."""
    from django.db.models import Sum

    from apps.meetings.models import ProposalItem
    from apps.tenancy.models import AiCall

    calls = AiCall.objects.filter(purpose=CLASSIFY_PURPOSE, succeeded=True)
    if not calls.exists():
        return None
    items = ProposalItem.objects.filter(
        proposal_id__in=calls.values("target_id"), kind=ProposalItem.Kind.ACTION_ITEM).count()
    spent = calls.aggregate(s=Sum("cost_usd"))["s"] or 0
    return (float(spent) / items) if items else None


def plan_reclassification() -> dict:
    """The count and the estimated cost, before anything runs: from what real
    calls have cost per item when there are any, from a model until then."""
    from django.conf import settings

    from apps.tenancy import claude

    from apps.meetings import practice

    roster = practice.staff(tenant_of_context())
    groups, placed = {}, 0
    for item in pending_to_classify():
        if confident(item.tenant, item.payload, roster=roster) is not None:
            placed += 1
            continue
        groups.setdefault(item.proposal, []).append(item)
    count = sum(len(v) for v in groups.values())
    measured = _measured_per_item()
    if measured is not None:
        cost = measured * count
    else:
        cost = 0
        for proposal, items in groups.items():
            tokens_in = (len(CLASSIFY_SYSTEM) + len(_classify_input(proposal, items))) // 4 + 50
            tokens_out = 250 * len(items) + 20
            cost += float(claude.cost_of(settings.ANTHROPIC_MODEL, tokens_in, tokens_out))
    return {"proposals": len(groups), "items": count, "placed_free": placed,
            "estimated_cost_usd": round(float(cost), 2),
            "measured": measured is not None, "groups": groups}


def reclassify(tenant, *, use_claude: bool, actor=None) -> dict:
    """Classify the pending items. With Claude: one small call per proposal,
    its answer checked against the staff roster and the records, exactly as a
    fresh parse is. Without: the same checks on the owner names already there,
    with an unrecognised name taken as a third party."""
    import json

    from apps.tenancy import claude

    from apps.meetings import practice

    roster = practice.staff(tenant)
    # The free rules first, for everything they can place with confidence.
    free = 0
    for item in pending_to_classify():
        placed = confident(tenant, item.payload, roster=roster)
        if placed is not None:
            item.payload = {**item.payload, **placed}
            item.save(update_fields=["payload", "updated_at"])
            free += 1
    plan = plan_reclassification()
    done, calls, cost, failed = 0, 0, 0, []
    for proposal, items in plan["groups"].items():
        hints = {}
        if use_claude:
            try:
                # Room for the model's reasoning as well as the answer: at 2000
                # one proposal's answer came back cut off (2026-09-28).
                reply, call = claude.complete_with_call(
                    tenant=tenant, purpose=CLASSIFY_PURPOSE, system=CLASSIFY_SYSTEM,
                    user_text=_classify_input(proposal, items),
                    target_type="meeting_proposal", target_id=proposal.pk,
                    trigger="backfill", max_tokens=8000,
                    # A labelling job, not a judgment call: low effort.
                    effort="low")
            except (claude.ClaudeUnavailable, claude.ClaudeRefused) as exc:
                # One proposal failing does not stop the rest; it stays
                # unclassified, and is named, so a second run picks it up.
                calls += 1
                failed.append({"proposal": str(proposal.pk), "error": str(exc)})
                continue
            calls += 1
            cost += call.cost_usd if call else 0
            try:
                rows = json.loads(reply.strip().strip("`").removeprefix("json").strip())
                hints = {int(r.get("item")): r for r in rows if isinstance(r, dict)}
            except (ValueError, TypeError, AttributeError):
                hints = {}
        for n, item in enumerate(items, 1):
            hint = hints.get(n, {})
            item.payload = {**item.payload, **classify(
                tenant, owner_text=item.payload.get("proposed_owner_text", ""),
                owner_contact_id=item.payload.get("proposed_owner_contact_id"),
                claude_side=str(hint.get("owner_side") or "").lower(),
                claude_kind=str(hint.get("owner_kind") or "").lower())}
            item.save(update_fields=["payload", "updated_at"])
            done += 1
    return {"proposals": plan["proposals"], "items": done, "placed_free": free,
            "claude_calls": calls, "cost_usd": str(cost), "failed": failed}
