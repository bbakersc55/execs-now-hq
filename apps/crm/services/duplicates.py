"""Likely duplicates across the whole book, and the context that tells two
same-named people apart (owner, 2026-09-29).

Two rules, and a contact caught by both is one group, not two:

- **the same email address**, compared case-insensitively;
- **the same normalized full name**: lower-cased, punctuation dropped,
  whitespace collapsed ("Mike  Eller", "mike eller", "Mike Eller." are one).
  **A first name alone is not a name match.** Two "Tim"s with no surname are
  more often two people than one, and a list that is mostly those would bury
  the real duplicates.

Nothing here merges. It proposes groups; a person picks the survivor
(FR-1.34, matrix 4.5).

**"Not duplicates"** (backlog, 2026-10-03): a pair a person dismissed is never
linked again. A third contact matching both can still bring them into one
group (that is new information), and the group lists the pairs already
dismissed so the screen can say so.
"""

from __future__ import annotations

import re
from collections import defaultdict

from django.db.models import Count, Max

EMAIL = "same email address"
NAME = "same name"


def normalized_name(first: str, last: str) -> str:
    joined = f"{first or ''} {last or ''}".lower()
    joined = re.sub(r"[^\w\s]", " ", joined)
    return " ".join(joined.split())


def contact_context(contact_ids) -> dict[str, dict]:
    """What distinguishes one contact from another with the same name: their
    company, their addresses, when they were last in a meeting, and how much
    history hangs on them. One query per kind, not per contact."""
    from apps.crm.models import Contact, ContactEmail
    from apps.meetings.models import MeetingParticipant

    ids = list(contact_ids)
    out: dict[str, dict] = {}
    for contact in (Contact.objects.filter(pk__in=ids).select_related("company")
                    .annotate(n_tasks=Count("tasks", distinct=True),
                              n_notes=Count("notes", distinct=True))):
        out[str(contact.pk)] = {
            "id": str(contact.pk),
            "name": f"{contact.first_name} {contact.last_name}".strip(),
            "company": contact.company.name if contact.company_id else "",
            "emails": [],
            "created_at": contact.created_at.isoformat(),
            "last_meeting": None,
            "meetings": 0,
            "tasks": contact.n_tasks,
            "notes": contact.n_notes,
        }
    for row in ContactEmail.objects.filter(contact_id__in=ids).order_by(
            "-is_primary", "address"):
        if str(row.contact_id) in out:
            out[str(row.contact_id)]["emails"].append(row.address)
    for row in (MeetingParticipant.objects.filter(contact_id__in=ids)
                .values("contact_id")
                .annotate(last=Max("meeting__meeting_date"), n=Count("id"))):
        entry = out.get(str(row["contact_id"]))
        if entry:
            entry["last_meeting"] = row["last"].isoformat() if row["last"] else None
            entry["meetings"] = row["n"]
    return out


def _history(entry: dict) -> int:
    return entry["meetings"] + entry["tasks"] + entry["notes"] + len(entry["emails"])


def groups(contacts) -> list[dict]:
    """Groups of two or more likely duplicates among `contacts` (a queryset
    already scoped to what the person may see), largest first."""
    from apps.crm.models import ContactEmail

    # Just the three columns: the view's queryset prefetches emails, phones and
    # types for display, which the whole book does not need here.
    contacts = list(contacts.model.objects.filter(pk__in=contacts.values("pk"))
                    .only("id", "first_name", "last_name"))
    ids = {str(c.pk) for c in contacts}
    parent = {i: i for i in ids}
    reasons: dict[str, set] = defaultdict(set)

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    dismissed = dismissed_pairs(ids)

    def join(members, reason):
        members = sorted(members)
        if len(members) < 2:
            return
        # Every pair that matches, except the ones a person said are not
        # duplicates. Buckets are small (one address, one name).
        for i, first in enumerate(members):
            for second in members[i + 1:]:
                if (first, second) in dismissed:
                    continue
                a, b = root(first), root(second)
                if a != b:
                    parent[b] = a
                reasons[first].add(reason)
                reasons[second].add(reason)

    by_address = defaultdict(set)
    for contact_id, address in ContactEmail.objects.filter(
            contact_id__in=ids).values_list("contact_id", "address"):
        by_address[address.strip().lower()].add(str(contact_id))
    for members in by_address.values():
        join(members, EMAIL)

    by_name = defaultdict(set)
    for c in contacts:
        if (c.first_name or "").strip() and (c.last_name or "").strip():
            by_name[normalized_name(c.first_name, c.last_name)].add(str(c.pk))
    for members in by_name.values():
        join(members, NAME)

    clusters = defaultdict(list)
    for i in ids:
        clusters[root(i)].append(i)
    found = [m for m in clusters.values() if len(m) > 1]
    context = contact_context([i for m in found for i in m])

    result = []
    for members in found:
        rows = sorted((context[i] for i in members if i in context),
                      key=lambda e: e["created_at"])
        # The suggestion: the record carrying the most history, the older
        # on a tie. It is a default for the picker, never a decision.
        survivor = max(rows, key=lambda e: (_history(e), -rows.index(e)))
        result.append({
            "key": min(members),
            "reasons": sorted({r for m in members for r in reasons[m]}),
            "contacts": rows,
            "suggested_survivor": survivor["id"],
            "dismissed_pairs": sorted([a, b] for a, b in dismissed
                                      if a in members and b in members),
        })
    result.sort(key=lambda g: (-len(g["contacts"]), g["contacts"][0]["name"].lower()))
    return result


def _pair(a, b) -> tuple[str, str]:
    a, b = str(a), str(b)
    return (a, b) if a < b else (b, a)


def dismissed_pairs(contact_ids) -> set[tuple[str, str]]:
    from apps.crm.models import DuplicateDismissal

    ids = [str(i) for i in contact_ids]
    return {(str(a), str(b)) for a, b in DuplicateDismissal.objects.filter(
        contact_a_id__in=ids, contact_b_id__in=ids).values_list("contact_a_id", "contact_b_id")}


def dismiss(contacts, *, actor) -> int:
    """Every pair among `contacts` (already scoped to what the person may see)
    is not a duplicate. Returns how many pairs were newly recorded."""
    from itertools import combinations

    from apps.crm.models import DuplicateDismissal
    from apps.tenancy.models import AuditEvent

    contacts = list(contacts)
    made = 0
    for x, y in combinations(contacts, 2):
        a, b = _pair(x.pk, y.pk)
        _, created = DuplicateDismissal.objects.get_or_create(
            contact_a_id=a, contact_b_id=b, defaults={"dismissed_by": actor})
        made += created
    if contacts:
        AuditEvent.objects.create(
            actor=actor, verb="contacts.not_duplicates", target_type="contact",
            target_id=contacts[0].pk,
            payload={"contacts": [str(c.pk) for c in contacts], "pairs": made})
    return made


def undo_dismissal(contacts, *, actor) -> int:
    from apps.crm.models import DuplicateDismissal
    from apps.tenancy.models import AuditEvent

    ids = [str(c.pk) for c in contacts]
    deleted, _ = DuplicateDismissal.objects.filter(
        contact_a_id__in=ids, contact_b_id__in=ids).delete()
    if ids:
        AuditEvent.objects.create(
            actor=actor, verb="contacts.not_duplicates_undone", target_type="contact",
            target_id=ids[0], payload={"contacts": ids, "pairs": deleted})
    return deleted
