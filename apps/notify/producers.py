"""What puts a notice on someone's list (owner, 2026-10-26).

- **notice**: a stage rule's notice (`stage_rules.notify`).
- **reading**: a scorecard reading waiting on its owner (`readings.remind`).
- **client_message**: a comment on work shared with the client. The practice
  writing one tells the client's people who can see the work; a client
  writing one tells the practice people the work belongs to.
- **mention**: "@Name" in a comment tells that person, if they can see the
  comment (an internal one: never a client). A mention takes the place of a
  client message to the same person.

Who can see the work is asked of the same rules every screen asks
(`apps.work.permissions`), as that person, so a notice never tells anyone
about work they could not open.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

from .models import Kind
from .service import tell

SNIPPET = 160


def _name(user) -> str:
    return (getattr(user, "full_name", "") or "").strip() or getattr(user, "email", "")


# ------------------------------------------------------------- stage rules

def pipeline_notice(row) -> None:
    tell(tenant_id=row.tenant_id, recipient_id=row.recipient_id, kind=Kind.NOTICE,
         title="Pipeline", text=row.text,
         url=f"/contacts/{row.contact_id}" if row.contact_id else "/dashboard",
         source_type="pipeline_notice", source_id=row.pk)


# ------------------------------------------------------------- the scorecard

def reading_reminder(reminder) -> None:
    from apps.scorecard import periods as P
    from apps.tenancy.models import CLIENT_ROLES, Membership

    kpi = reminder.kpi
    company_id = kpi.scorecard.company_id
    member = Membership.all_objects.filter(tenant_id=reminder.tenant_id,
                                           user_id=reminder.recipient_id,
                                           revoked_at__isnull=True).first()
    if member is None:
        return
    url = "/scorecard/enter" if member.role in CLIENT_ROLES \
        else f"/companies/{company_id}/scorecard/enter"
    tell(tenant_id=reminder.tenant_id, recipient_id=reminder.recipient_id, kind=Kind.READING,
         title="A reading is waiting on you",
         text=f"{kpi.name}: no reading yet for {P.long_label(reminder.period_start, kpi.cadence)}.",
         url=url, source_type="kpi_reminder", source_id=reminder.pk)


# ------------------------------------------------------------- comments

def _entity_of(comment):
    for kind in ("task", "project", "goal"):
        if getattr(comment, f"{kind}_id", None):
            return kind, getattr(comment, kind)
    return None, None


def _url(kind, entity) -> str:
    return {"task": f"/tasks/{entity.pk}", "project": f"/work/projects/{entity.pk}",
            "goal": f"/work/goals/{entity.pk}"}[kind]


def _as(membership):
    return SimpleNamespace(membership=membership, user=membership.user,
                           tenant=membership.tenant)


def sees(kind, entity, membership, comment=None) -> bool:
    """Whether this person could open the work, and the comment on it."""
    from apps.crm.models import Task
    from apps.tenancy.models import CLIENT_ROLES
    from apps.work import permissions as work_perms
    from apps.work.models import Comment, Goal, Project

    if comment is not None and membership.role in CLIENT_ROLES \
            and comment.visibility != Comment.Visibility.SHARED:
        return False
    model, scoper = {"task": (Task, work_perms.task_queryset_for),
                     "project": (Project, work_perms.project_queryset_for),
                     "goal": (Goal, work_perms.goal_queryset_for)}[kind]
    rows = model.all_objects.filter(pk=entity.pk, tenant_id=entity.tenant_id,
                                    deleted_at__isnull=True)
    return scoper(_as(membership), rows).exists()


def _candidates(entity):
    """The practice's people, and the client's people of the work's company."""
    from apps.tenancy.models import CLIENT_ROLES, Membership, Role

    staff_roles = (Role.FF, Role.CF, Role.VA)
    rows = Membership.all_objects.filter(tenant_id=entity.tenant_id, revoked_at__isnull=True) \
        .select_related("user", "tenant")
    staff = [m for m in rows if m.role in staff_roles]
    clients = [m for m in rows if m.role in CLIENT_ROLES and entity.client_company_id
               and m.client_company_id == entity.client_company_id]
    return staff, clients


def mentionable(kind, entity, *, author, visibility) -> list[dict]:
    """Who "@" may suggest in a comment on this work (owner, 2026-10-27): the
    people a mention would tell, by the same rules as `comment` below (the
    work's people, each only when they could see a comment of this
    visibility), the writer left out, and only those with a name to type."""
    staff, clients = _candidates(entity)
    seen_as = SimpleNamespace(visibility=visibility)
    out = []
    for m in staff + clients:
        full = (getattr(m.user, "full_name", "") or "").strip()
        if m.user_id == author.pk or not full or not sees(kind, entity, m, seen_as):
            continue
        out.append({"id": str(m.user_id), "name": full})
    return sorted(out, key=lambda row: row["name"].lower())


def mentioned(body: str, people) -> list:
    """The people "@Full Name" names, and "@First" where the first name is one
    person's alone. Case is ignored; a name must end at a word's end."""
    text = body or ""
    firsts = {}
    for m in people:
        first = (_name(m.user).split() or [""])[0].lower()
        if first:
            firsts.setdefault(first, []).append(m)
    found = []
    for m in people:
        full = _name(m.user)
        if not full:
            continue
        first = full.split()[0]
        patterns = [re.escape(full)]
        if len(firsts.get(first.lower(), [])) == 1:
            patterns.append(re.escape(first))
        if any(re.search(rf"(?<![\w@])@{p}(?!\w)", text, re.IGNORECASE) for p in patterns):
            found.append(m)
    return found


def comment(comment, *, author, role) -> None:
    from apps.tenancy.models import CLIENT_ROLES
    from apps.work.models import Comment

    kind, entity = _entity_of(comment)
    if entity is None:
        return
    staff, clients = _candidates(entity)
    everyone = [m for m in staff + clients if m.user_id != author.pk]
    title = getattr(entity, "title", "") or "the work"
    snippet = " ".join((comment.body or "").split())
    snippet = snippet if len(snippet) <= SNIPPET else snippet[:SNIPPET - 1] + "…"
    url = _url(kind, entity)
    told = set()
    for m in mentioned(comment.body, everyone):
        if sees(kind, entity, m, comment):
            tell(tenant_id=entity.tenant_id, recipient_id=m.user_id, kind=Kind.MENTION,
                 title=f"{_name(author)} mentioned you",
                 text=f"On “{title}”: {snippet}", url=url, source_type="comment",
                 source_id=comment.pk)
            told.add(m.user_id)
    if comment.visibility != Comment.Visibility.SHARED or not entity.client_company_id:
        return
    if role in CLIENT_ROLES:
        # A client's message: the practice people the work belongs to; with
        # nobody at the practice on it, the practice owner and the associates
        # assigned to the client.
        owners = {getattr(entity, "owner_id", None), getattr(entity, "assignee_id", None)}
        to = [m for m in staff if m.user_id in owners]
        if not to:
            from apps.tenancy.models import ClientAssignment, Role

            assigned = set(ClientAssignment.all_objects.filter(
                tenant_id=entity.tenant_id, company_id=entity.client_company_id)
                .values_list("user_id", flat=True))
            to = [m for m in staff if m.role == Role.FF
                  or (m.role == Role.CF and m.user_id in assigned)]
    else:
        to = clients
    for m in to:
        if m.user_id == author.pk or m.user_id in told or not sees(kind, entity, m, comment):
            continue
        tell(tenant_id=entity.tenant_id, recipient_id=m.user_id, kind=Kind.CLIENT_MESSAGE,
             title=f"New message from {_name(author)}", text=f"On “{title}”: {snippet}",
             url=url, source_type="comment", source_id=comment.pk)
