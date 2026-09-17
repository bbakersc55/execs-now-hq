"""The practice's activity feed — everything happening across the accounts.

**This supersedes the Phase 3 decision** that the activity log belonged to the
client (FR-3.41, matrix 7.16). The owner asked for a client-visible log on
2026-09-13 and reversed it on 2026-09-16 after using it: the log's value is to
the practice, not to the client. A founder does not want an audit feed of their
own company; they want to know whether the engagement is working, which is the
value report's job (Module 4B). The practice, running several accounts at once,
does want the feed — including what its own team did.

So the shape is inverted. It is no longer "one company's work, client-visible
only". It is **every action touching any contact, company, referral partner or
prospect**, in one chronological list, read-only, for tenant staff.

Read-only is absolute and structural: this module has no write path at all, and
the viewset exposes only `list`. A history that can be tidied is not a history.

Sources, and what is not here yet:

- `task_update` — task, project and goal movement, including the client-facing
  line when one was given.
- `comment` — **both internal and shared**, because staff see both. This is the
  clearest single difference from the client version, which never saw internal.
- `note` — that one was written, and on what. **Never the body**, and never the
  title of a PIN-gated note: the PIN is a screen (FR-2.8) and the feed must not
  be the hole in it.
- `audit_event` — stage changes, imports, portal grants and revokes, act-as
  sessions, digest approvals and sends, Gmail connections, merges, deletes.
- `outbox_message` — mail that left, with who it went to.

**Meetings and inbound email are absent because Modules 5 and 6 do not exist
yet**, not because they were left out. Each joins as a source when its module
lands; the owner's list named them and this is where they go.
"""

from __future__ import annotations

from apps.crm import permissions as crm_perms
from apps.crm.models import Company, Contact, ImportBatch, OutboxMessage, Task
from apps.notes.models import Note
from apps.tenancy.models import AuditEvent, Membership
from apps.work.models import Comment, Goal, Project, TaskUpdate

# Per-source cap before merging. Beta volume is small and the feed is a read of
# five tables; when real volume arrives this becomes keyset pagination rather
# than a bigger number. Filtering happens before the final slice, so a narrow
# filter does not return three rows out of a pre-truncated 200.
SOURCE_CAP = 500
LIMIT = 200

CATEGORIES = ("work", "comment", "note", "email", "pipeline", "import",
              "portal", "act_as", "digest", "settings")

# Verb → (category, phrasing). A verb absent here is absent from the feed, so
# adding an audited action is a deliberate act rather than an automatic leak.
AUDIT = {
    "stage.changed": ("pipeline", "moved {target} to a new stage"),
    "contact.merged": ("pipeline", "merged {target}"),
    "contact.deleted": ("pipeline", "deleted {target}"),
    "contact_type.derived": ("pipeline", "{target} became a client"),
    "company.flagged": ("pipeline", "flagged {target}"),
    "company.primary_contact_changed": ("pipeline", "changed the primary contact for {target}"),
    "referral.blurb_updated": ("pipeline", "updated the referral blurb"),
    "referral.onboarded": ("pipeline", "onboarded {target} as a referral partner"),
    "referral.touch_drafted": ("pipeline", "drafted a referral touch for {target}"),
    "import.committed": ("import", "committed a CSV import"),
    "import.rolled_back": ("import", "rolled back a CSV import"),
    "portal.access_granted": ("portal", "gave {target} access to the portal"),
    "portal.access_revoked": ("portal", "removed {target}'s portal access"),
    "portal.role_changed": ("portal", "changed {target}'s portal role"),
    "act_as.started": ("act_as", "began acting as {target}"),
    "act_as.stopped": ("act_as", "stopped acting as {target}"),
    "act_as.ended": ("act_as", "stopped acting as {target}"),
    "digest.approved": ("digest", "approved a digest"),
    "digest.sent": ("digest", "sent a digest"),
    "digest.edited": ("digest", "edited a digest"),
    "digest.expired": ("digest", "let a digest expire"),
    "digest.skipped": ("digest", "skipped a digest"),
    "digest.generated_on_demand": ("digest", "generated a digest by hand"),
    "outbox.approved": ("email", "approved a message"),
    "outbox.rejected": ("email", "rejected a message"),
    "outbox.expired": ("email", "let a message expire"),
    "email.sent": ("email", "sent a message"),
    "email.failed": ("email", "a message failed to send"),
    "email.suppressed": ("email", "a message was suppressed"),
    "task.created_by_rule": ("work", "a stage rule created a task"),
    "task.deleted": ("work", "deleted a task"),
    "task.visibility_changed": ("work", "changed what the client can see on a task"),
    "project.deleted": ("work", "deleted a project"),
    "goal.deleted": ("work", "deleted a goal"),
    "note.deleted": ("note", "deleted a note"),
    "gmail.connected": ("settings", "connected Gmail"),
    "gmail.disconnected": ("settings", "disconnected Gmail"),
    "gmail.alias_verified": ("settings", "verified a send-as alias"),
    "member.invited": ("settings", "invited {target}"),
    "member.removed": ("settings", "removed {target}"),
    "member.role_changed": ("settings", "changed {target}'s role"),
    "stakeholder.cadence_changed": ("settings", "changed a stakeholder's cadence"),
    "notes.retention_changed": ("settings", "changed the note retention period"),
    "ai.key_rotated": ("settings", "rotated the Claude API key"),
}


def _name(user):
    return (user.full_name or user.email) if user else ""


def _person(user, acting_user):
    """"by X on behalf of Y" — X is the real person, Y who they acted as."""
    if acting_user:
        return _name(acting_user), _name(user)
    return _name(user) or "The system", None


class Scope:
    """What this requester may see, resolved once.

    FF and VA see the whole tenant. A CF sees exactly what `contact_queryset_for`
    already defines for them — assigned client companies plus contacts they own —
    so the feed cannot drift from the CRM's own answer to the same question.
    """

    def __init__(self, request):
        self.role = crm_perms.role_of(request)
        self.everything = self.role in ("FF", "VA")
        if self.everything:
            self.company_ids = None
            self.contact_ids = None
        else:
            # Strings, because an entry carries `str(pk)` and a UUID never
            # equals its own string form — a mismatch that reads as "this CF has
            # no accounts" rather than as an error.
            self.company_ids = {str(pk) for pk in crm_perms.company_queryset_for(
                request, Company.objects.all()).values_list("pk", flat=True)}
            self.contact_ids = {str(pk) for pk in crm_perms.contact_queryset_for(
                request, Contact.objects.all()).values_list("pk", flat=True)}

    def allows(self, company_id, contact_id) -> bool:
        if self.everything:
            return True
        if company_id and company_id in self.company_ids:
            return True
        if contact_id and contact_id in self.contact_ids:
            return True
        # A CF sees their accounts, and only their accounts. An event attached to
        # no company and no contact — a Gmail connection, a retention change, the
        # API key rotated — is the practice's own business and not one of theirs.
        return False


def _entry(key, at, category, kind, text, *, by, on_behalf_of=None,
           company=None, contact=None, entity=None):
    return {
        "id": key,
        "at": at.isoformat(),
        "category": category,
        "kind": kind,
        "text": text,
        "by": by,
        "on_behalf_of": on_behalf_of,
        "company": ({"id": str(company.pk), "name": company.name} if company else None),
        "contact": ({"id": str(contact.pk),
                     "name": f"{contact.first_name} {contact.last_name}".strip()}
                    if contact else None),
        "entity": entity,
    }


def _window(qs, since, until, actor, actor_field="actor"):
    """The three filters every source shares. `actor_field` differs per table —
    `author` on a comment, `created_by` on a note — and is passed rather than
    discovered, so a rename fails loudly instead of silently filtering nothing."""
    if since:
        qs = qs.filter(created_at__gte=since)
    if until:
        qs = qs.filter(created_at__lte=until)
    if actor:
        qs = qs.filter(**{f"{actor_field}_id": actor})
    return qs


STATUS_LABELS = dict(Task.Status.choices)


def _work_entries(scope, since, until, actor):
    """`task_update` — the same rows the digests read, so the feed and the
    client's report can never disagree about what happened."""
    qs = (TaskUpdate.objects.exclude(kind=TaskUpdate.Kind.COMMENT_ADDED)
          .select_related("task", "task__client_company", "task__contact",
                          "project", "project__client_company",
                          "goal", "goal__client_company", "actor", "acting_user")
          .order_by("-created_at"))
    qs = _window(qs, since, until, actor)
    out = []
    for u in qs[:SOURCE_CAP]:
        entity = u.task or u.project or u.goal
        if entity is None:
            continue
        title = f"“{entity.title}”"
        text = {
            "created": f"created {title}",
            "status_changed": f"moved {title} from {STATUS_LABELS.get(u.from_value, u.from_value)} "
                              f"to {STATUS_LABELS.get(u.to_value, u.to_value)}",
            "assignee_changed": f"reassigned {title} to {u.to_value or 'nobody'}",
            "due_changed": f"set the due date of {title} to {u.to_value or 'none'}",
            "checklist_completed": f"completed the step “{u.to_value}” on {title}",
            "completed": f"completed {title}",
            "narrative": f"added a note on {title}: {u.client_facing_line}",
        }.get(u.kind, f"updated {title}")
        if u.kind == TaskUpdate.Kind.STATUS_CHANGED and u.client_facing_line:
            text += f" — {u.client_facing_line}"
        by, behalf = _person(u.actor, u.acting_user)
        out.append(_entry(
            f"u-{u.pk}", u.created_at, "work", u.kind, text, by=by, on_behalf_of=behalf,
            company=entity.client_company,
            contact=getattr(entity, "contact", None),
            entity={"type": entity._meta.model_name, "id": str(entity.pk),
                    "title": entity.title},
        ))
    return out


def _comment_entries(scope, since, until, actor):
    """Both visibilities. Staff see internal comments everywhere else in the
    product; a feed that hid them would be lying by omission rather than
    protecting anything."""
    qs = (Comment.objects.filter(deleted_at__isnull=True)
          .select_related("task", "task__client_company", "task__contact",
                          "project", "project__client_company",
                          "goal", "goal__client_company", "author", "acting_user")
          .order_by("-created_at"))
    qs = _window(qs, since, until, actor, actor_field="author")
    out = []
    for c in qs[:SOURCE_CAP]:
        entity = c.task or c.project or c.goal
        if entity is None:
            continue
        internal = c.visibility == Comment.Visibility.INTERNAL
        label = "an internal comment" if internal else "a comment"
        by, behalf = _person(c.author, c.acting_user)
        out.append(_entry(
            f"c-{c.pk}", c.created_at, "comment", c.visibility,
            f"left {label} on “{entity.title}”: {c.body}", by=by, on_behalf_of=behalf,
            company=entity.client_company,
            contact=getattr(entity, "contact", None),
            entity={"type": entity._meta.model_name, "id": str(entity.pk),
                    "title": entity.title},
        ))
    return out


def _note_entries(scope, since, until, actor):
    """That a note exists and what it is attached to — never its body.

    A PIN-gated note does not even give up its title here. The PIN is a screen
    over the note (FR-2.8), and a feed that printed the title beside the author
    and the timestamp would be a way around it for anyone who can read the feed.
    """
    qs = (Note.objects.filter(deleted_at__isnull=True)
          .select_related("contact", "contact__company", "company", "task",
                          "task__client_company", "created_by")
          .order_by("-created_at"))
    qs = _window(qs, since, until, actor, actor_field="created_by")
    out = []
    for n in qs[:SOURCE_CAP]:
        locked = bool(n.pin_hash)
        what = "a PIN-protected note" if locked else (
            f"a note, “{n.title}”" if n.title else "a note")
        attached = n.contact or n.company or n.task
        where = f" on “{getattr(attached, 'title', None) or attached}”" if attached else ""
        company = n.company or getattr(n.contact, "company", None) or \
            getattr(n.task, "client_company", None)
        out.append(_entry(
            f"n-{n.pk}", n.created_at, "note", n.source,
            f"wrote {what}{where}", by=_name(n.created_by) or "The system",
            company=company, contact=n.contact,
            entity={"type": "note", "id": str(n.pk),
                    "title": "" if locked else n.title},
        ))
    return out


def _email_entries(scope, since, until, actor):
    """Mail that left, from the Outbox, which FR-1.15 already makes the complete
    send log. Only `sent` and `suppressed`: a draft is not an action taken."""
    qs = (OutboxMessage.objects.filter(state__in=(OutboxMessage.State.SENT,
                                                  OutboxMessage.State.SUPPRESSED))
          .select_related("to_contact", "to_contact__company", "approved_by")
          .order_by("-created_at"))
    if since:
        qs = qs.filter(created_at__gte=since)
    if until:
        qs = qs.filter(created_at__lte=until)
    if actor:
        qs = qs.filter(approved_by_id=actor)
    out = []
    for m in qs[:SOURCE_CAP]:
        who = m.to_contact and f"{m.to_contact.first_name} {m.to_contact.last_name}".strip()
        verb = "sent" if m.state == OutboxMessage.State.SENT else "suppressed (acting as)"
        out.append(_entry(
            f"o-{m.pk}", m.sent_at or m.created_at, "email", m.producer,
            f"{verb} “{m.subject}” to {who or m.to_address}",
            by=_name(m.approved_by) or "The app",
            company=getattr(m.to_contact, "company", None), contact=m.to_contact,
            entity={"type": "outbox_message", "id": str(m.pk), "title": m.subject},
        ))
    return out


def _audit_entries(scope, since, until, actor):
    """The whitelist in `AUDIT`, with each target resolved to something a person
    recognises — a contact's name, a company's, a colleague's."""
    qs = (AuditEvent.objects.filter(verb__in=AUDIT)
          .select_related("actor", "acting_user").order_by("-created_at"))
    qs = _window(qs, since, until, actor)
    rows = list(qs[:SOURCE_CAP])

    def ids(target_type):
        return [r.target_id for r in rows if r.target_type == target_type and r.target_id]

    contacts = {c.pk: c for c in Contact.all_objects.filter(pk__in=ids("contact"))
                .select_related("company")}
    companies = {c.pk: c for c in Company.all_objects.filter(pk__in=ids("company"))}
    members = {m.pk: m for m in Membership.all_objects.filter(pk__in=ids("membership"))
               .select_related("user", "client_company")}
    tasks = {t.pk: t for t in Task.all_objects.filter(pk__in=ids("task"))
             .select_related("client_company", "contact")}
    batches = {b.pk: b for b in ImportBatch.all_objects.filter(pk__in=ids("import_batch"))}

    out = []
    for a in rows:
        category, phrasing = AUDIT[a.verb]
        contact = company = None
        target = ""
        if a.target_type == "contact":
            c = contacts.get(a.target_id)
            if c:
                contact, company = c, c.company
                target = f"{c.first_name} {c.last_name}".strip()
        elif a.target_type == "company":
            company = companies.get(a.target_id)
            target = company.name if company else ""
        elif a.target_type == "membership":
            m = members.get(a.target_id)
            if m:
                company = m.client_company
                target = _name(m.user)
        elif a.target_type == "task":
            t = tasks.get(a.target_id)
            if t:
                company, contact = t.client_company, t.contact
                target = t.title
        elif a.target_type == "import_batch":
            target = str(batches.get(a.target_id) or "")
        by, behalf = _person(a.actor, a.acting_user)
        text = phrasing.format(target=target or "a record")
        if a.verb == "act_as.ended":
            text += f" ({a.payload.get('reason') or 'no longer permitted'})"
        out.append(_entry(f"a-{a.pk}", a.created_at, category, a.verb, text,
                          by=by, on_behalf_of=behalf, company=company, contact=contact))
    return out


BUILDERS = (_work_entries, _comment_entries, _note_entries, _email_entries, _audit_entries)


def build(request, *, company=None, contact=None, actor=None, category=None,
          since=None, until=None, limit=LIMIT):
    """The feed, filtered and merged. Scope is applied last and always."""
    scope = Scope(request)
    entries = []
    for builder in BUILDERS:
        entries += builder(scope, since, until, actor)

    kept = []
    for e in entries:
        e_company = e["company"]["id"] if e["company"] else None
        e_contact = e["contact"]["id"] if e["contact"] else None
        if not scope.allows(e_company, e_contact):
            continue
        if company and e_company != company:
            continue
        if contact and e_contact != contact:
            continue
        if category and e["category"] != category:
            continue
        kept.append(e)

    kept.sort(key=lambda e: e["at"], reverse=True)
    return kept[:limit]
