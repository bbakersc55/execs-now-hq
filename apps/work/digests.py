"""Digests — FR-3.19 to FR-3.32. The module the product is judged by.

Everything here is arranged so that **an unintended send is structurally
impossible**:

- A digest is assembled from `task_update` rows, never from diffing state.
- What a recipient has already been sent is a row in `digest_item`, so nothing
  is sent twice and nothing is silently dropped: an expiring draft **deletes
  its items**, which hands its updates back to the next period (FR-3.30).
- `hold_all_digests` ON (the Beta default) means every digest waits, AI-written
  or not. With it off, an AI-drafted digest **still** waits; only a
  deterministic one sends on cadence (FR-3.26/3.27).
- Approval is the only thing that can send, and once approved a digest is never
  rewritten: a late update goes to the next period (FR-3.30b).
- A period with nothing in it produces no digest and no email (FR-3.31).

Timing (FR-3.23/3.28, tenant timezone): weekly generates 24 h before its send
window; monthly goes out on the **first send-day of the month covering the
previous calendar month** (owner decision, 2026-09-11). `every_update` is
generated when its 30-minute quiet window closes (FR-3.28a) and then follows
exactly the same rules as any other digest.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from apps.crm.models import OutboxMessage, Task
from apps.tenancy.models import AuditEvent
from apps.work import stakeholders as stakeholder_service
from apps.work import updates as update_service
from apps.work.models import Cadence, Comment, Digest, DigestItem, TaskUpdate

QUIET_WINDOW = timedelta(minutes=30)      # FR-3.22
REVIEW_LEAD = timedelta(hours=24)         # FR-3.28
K = TaskUpdate.Kind


# --------------------------------------------------------------- the windows

def zone(tenant) -> ZoneInfo:
    return ZoneInfo(tenant.timezone)


def _at_send_hour(tenant, day):
    """The tenant's send hour on a given local date, as an aware datetime.

    Built in the tenant's own zone, so a DST boundary moves the UTC instant
    rather than the local time the client sees (AC-3.22).
    """
    return datetime.combine(day, time(tenant.digest_send_hour), tzinfo=zone(tenant))


def next_weekly_window(tenant, after):
    """The next send day/hour at or after `after` (ISO weekday, 1=Monday)."""
    local = after.astimezone(zone(tenant))
    ahead = (tenant.digest_send_day - local.isoweekday()) % 7
    candidate = _at_send_hour(tenant, local.date() + timedelta(days=ahead))
    if candidate <= after:
        candidate = _at_send_hour(tenant, local.date() + timedelta(days=ahead + 7))
    return candidate


def first_send_day_of_month(tenant, year, month):
    day = datetime(year, month, 1, tzinfo=zone(tenant)).date()
    ahead = (tenant.digest_send_day - day.isoweekday()) % 7
    return _at_send_hour(tenant, day + timedelta(days=ahead))


def next_monthly_window(tenant, after):
    local = after.astimezone(zone(tenant))
    candidate = first_send_day_of_month(tenant, local.year, local.month)
    if candidate <= after:
        year, month = (local.year + 1, 1) if local.month == 12 else (local.year, local.month + 1)
        candidate = first_send_day_of_month(tenant, year, month)
    return candidate


def next_window(tenant, cadence, after=None):
    after = after or timezone.now()
    if cadence == Cadence.MONTHLY:
        return next_monthly_window(tenant, after)
    return next_weekly_window(tenant, after)


def period_for(tenant, cadence, send_window):
    """The span a digest covers. Weekly: the seven days ending at generation.
    Monthly: the previous calendar month, in the tenant's zone."""
    if cadence == Cadence.MONTHLY:
        local = send_window.astimezone(zone(tenant))
        this_month = datetime(local.year, local.month, 1, tzinfo=zone(tenant))
        previous = (this_month - timedelta(days=1)).replace(day=1)
        return previous, this_month
    end = send_window - REVIEW_LEAD
    return end - timedelta(days=7), end


# ------------------------------------------------------------ what is owed

def qualifying_updates(task_ids, contact_id, *, since=None, until=None):
    """Updates a recipient is still owed (FR-3.19, FR-3.30).

    Filtered to client-visible tasks and shared comments, excluding the
    recipient's own client-side actions, and excluding anything already claimed
    by a `sent` digest for this very contact — the claim is per recipient, which
    is the whole reason `digest_item` exists.
    """
    rows = TaskUpdate.objects.filter(task_id__in=task_ids).select_related(
        "task", "actor"
    ).exclude(
        # FR-3.19 — internal comments are never client material.
        kind=K.COMMENT_ADDED, to_value=Comment.Visibility.INTERNAL,
    ).exclude(
        # Already claimed for THIS person — by a draft, an approved digest or a
        # sent one. A claim exists exactly as long as its `digest_item` does, and
        # expiry or skipping deletes those, which is what hands the update back.
        digest_items__digest__contact_id=contact_id,
    )
    if since is not None:
        rows = rows.filter(created_at__gte=since)
    if until is not None:
        rows = rows.filter(created_at__lt=until)
    return rows.order_by("created_at")


def since_for(contact_id, cadence=None) -> object:
    """The lower bound for what a recipient is owed: when they were first
    attached to anything.

    Deliberately NOT a period boundary. FR-3.30 rolls unsent content forward, so
    content released by last week's expiry is older than this week's window and
    a window-based floor would silently lose it. Nothing needs a floor for
    "already sent" either — that is what the `digest_item` claims are for. The
    only thing this prevents is a stakeholder added today being sent the entire
    history of a task they were not following.
    """
    from apps.work.models import Stakeholder

    return (Stakeholder.objects.filter(contact_id=contact_id)
            .order_by("created_at").values_list("created_at", flat=True).first())


def owed_to(contact_id, *, tenant, cadence, since=None, until=None):
    """[(update, stakeholder)] for one recipient at one cadence."""
    if since is None:
        since = since_for(contact_id, cadence)
    reach = stakeholder_service.tasks_for_contact(tenant, contact_id)
    at_cadence = {
        task_id: (task, row) for task_id, (task, row) in reach.items()
        if stakeholder_service.cadence_of(row) == cadence and task.is_client_visible
    }
    if not at_cadence:
        return []
    updates = qualifying_updates(list(at_cadence), contact_id, since=since, until=until)
    owed = []
    for update in updates:
        task, row = at_cadence[update.task_id]
        # A client's own action is visible to them but never the trigger for
        # their own email.
        if update.is_client_actor and _is_same_person(update, row):
            continue
        owed.append((update, row))
    return owed


def _is_same_person(update, row):
    """Whether the actor behind an update IS this stakeholder.

    A login attaches to a Contact through its membership (assumption F1), so
    that row is what connects "who did it" to "who would be told".
    """
    from apps.tenancy.models import Membership

    if update.actor_id is None:
        return False
    return Membership.all_objects.filter(
        tenant_id=update.tenant_id, user_id=update.actor_id, contact_id=row.contact_id
    ).exists()


# ------------------------------------------------------------- composition

AI_SYSTEM = """\
You write the connective narrative of a progress report that a fractional \
executive sends to their client.

You are given ONLY status transitions and lines the fractional wrote for the \
client. You must not assert any fact, figure, name, date, cause, or outcome \
that is not present in that input. Do not infer why something happened, do not \
estimate progress, and do not predict what happens next unless a line says so. \
If the input is thin, write less.

Write two to four sentences of plain prose that connect the work into a story \
of progress. Do not list the items — they are listed underneath you. Do not \
greet or sign off. Where a line the fractional wrote covers the point, prefer \
their words to yours."""


def _describe(update) -> str:
    task = update.task
    what = task.title if task else "work"
    if update.kind == K.STATUS_CHANGED:
        return f"{what}: {update.from_value or 'new'} → {update.to_value}"
    if update.kind == K.COMPLETED:
        return f"{what}: completed"
    if update.kind == K.CREATED:
        return f"{what}: added"
    if update.kind == K.DUE_CHANGED:
        return f"{what}: due date now {update.to_value or 'unset'}"
    if update.kind == K.ASSIGNEE_CHANGED:
        return f"{what}: now with {update.to_value or 'nobody'}"
    if update.kind == K.CHECKLIST_COMPLETED:
        return f"{what}: step done — {update.to_value}"
    if update.kind == K.COMMENT_ADDED:
        return f"{what}: comment"
    if update.kind == K.NARRATIVE:
        return what
    return f"{what}: {update.kind}"


def deterministic_body(owed) -> str:
    """FR-3.24 with AI prose OFF: transitions and human text, nothing else."""
    lines = []
    for update, _row in owed:
        entry = f"- {_describe(update)}"
        if update.client_facing_line:
            entry += f"\n  {update.client_facing_line}"
        lines.append(entry)
    return "\n".join(lines)


def ai_input(owed) -> str:
    parts = []
    for update, _row in owed:
        parts.append(_describe(update))
        if update.client_facing_line:
            parts.append(f'  line written for the client: "{update.client_facing_line}"')
    return "\n".join(parts)


def narrative_for(tenant, owed, *, contact):
    """Claude's connective prose, or '' if it cannot be produced.

    A failure is not fatal: the digest still goes out as the deterministic list,
    which is the one thing that is always true.
    """
    from apps.tenancy import claude

    try:
        return claude.complete(
            tenant=tenant, purpose="digest_prose", system=AI_SYSTEM,
            user_text=ai_input(owed), target_type="contact", target_id=contact.pk,
            trigger="auto", max_tokens=2000,
        )
    except (claude.ClaudeUnavailable, claude.ClaudeRefused):
        return ""


def render(digest, owed, *, narrative=""):
    body = deterministic_body(owed)
    text = f"{narrative}\n\n{body}" if narrative else body
    html_items = "".join(
        f"<li>{_describe(u)}"
        + (f"<br><em>{u.client_facing_line}</em>" if u.client_facing_line else "")
        + "</li>"
        for u, _ in owed
    )
    html = (f"<p>{narrative}</p>" if narrative else "") + f"<ul>{html_items}</ul>"
    return text.strip(), html


# -------------------------------------------------------------- generation

@transaction.atomic
def generate(*, tenant, contact, cadence, period_start, period_end, send_window_at,
             owed=None, until=None):
    """One digest for one recipient, or None when there is nothing to say.

    FR-3.31 — a period with no qualifying updates produces no digest at all.
    Nobody should ever receive "nothing happened this week".
    """
    # `period_start` labels the digest; what is OWED is decided by claims and
    # `since_for`, so content deferred from an earlier period is not lost to a
    # window that has since moved on (FR-3.30).
    # `until` is the moment generation runs. `period_end` only labels the row:
    # the weekly label can sit in the future (it is derived from the send
    # window), and bounding the query by it would hide everything owed today.
    owed = owed if owed is not None else owed_to(
        contact.pk, tenant=tenant, cadence=cadence, until=until or timezone.now(),
    )
    if not owed:
        return None

    company = contact.company
    ai = bool(company.digest_ai_prose) if company is not None else bool(
        tenant.digest_ai_prose_default
    )
    digest, created = Digest.objects.get_or_create(
        contact=contact, cadence=cadence, period_start=period_start,
        defaults={
            "tenant": tenant, "period_end": period_end,
            "send_window_at": send_window_at, "is_ai_generated": ai,
        },
    )
    if not created:
        return digest

    narrative = narrative_for(tenant, owed, contact=contact) if ai else ""
    digest.body_text, digest.body_html = render(digest, owed, narrative=narrative)
    # FR-3.26/3.27: held means pending. Unheld and deterministic needs no
    # human, so it is pre-approved and will go at its window.
    if not tenant.hold_all_digests and not ai:
        digest.state = Digest.State.APPROVED
        digest.approved_at = timezone.now()
    digest.save(update_fields=["body_text", "body_html", "state", "approved_at",
                               "updated_at"])
    for update, row in owed:
        DigestItem.objects.create(tenant=tenant, digest=digest, task_update=update,
                                  stakeholder=row)
    return digest


def generate_scheduled(tenant, *, cadence, now=None):
    """Generate every due digest for one cadence, 24 hours before the window."""
    now = now or timezone.now()
    window = next_window(tenant, cadence, after=now)
    if now < window - REVIEW_LEAD:
        return []                      # not yet inside the review window
    period_start, period_end = period_for(tenant, cadence, window)
    made = []
    for contact_id in stakeholder_service.contacts_with_attachments(tenant):
        from apps.crm.models import Contact

        contact = Contact.objects.filter(pk=contact_id).select_related("company").first()
        if contact is None:
            continue
        digest = generate(tenant=tenant, contact=contact, cadence=cadence,
                          period_start=period_start, period_end=period_end,
                          send_window_at=window, until=now)
        if digest is not None:
            made.append(digest)
    return made


def close_quiet_windows(tenant, *, now=None):
    """FR-3.22/3.28a — one editing session produces one email.

    An `every_update` recipient's digest is generated only once nothing new has
    landed for 30 minutes, and its send window is immediately.
    """
    now = now or timezone.now()
    made = []
    from apps.crm.models import Contact

    for contact_id in stakeholder_service.contacts_with_attachments(tenant):
        owed = owed_to(contact_id, tenant=tenant, cadence=Cadence.EVERY_UPDATE)
        if not owed:
            continue
        latest = max(u.created_at for u, _ in owed)
        if now - latest < QUIET_WINDOW:
            continue                   # still typing
        contact = Contact.objects.filter(pk=contact_id).select_related("company").first()
        if contact is None:
            continue
        digest = generate(
            tenant=tenant, contact=contact, cadence=Cadence.EVERY_UPDATE,
            period_start=min(u.created_at for u, _ in owed), period_end=now,
            send_window_at=now, owed=owed,
        )
        if digest is not None:
            made.append(digest)
    return made


# ------------------------------------------------------- staleness (FR-3.30a)

def flag_stale_for(update: TaskUpdate):
    """A draft overtaken by events is flagged, never silently sent.

    Only `pending` digests: an approved one is an artefact and is never
    rewritten (FR-3.30b).
    """
    if update.task_id is None:
        return 0
    task = update.task
    contacts = stakeholder_service.effective_for_task(task)
    if not contacts:
        return 0
    pending = Digest.all_objects.filter(
        tenant_id=update.tenant_id, state=Digest.State.PENDING,
        contact_id__in=list(contacts),
    )
    reason = f"{_describe(update)} landed after this draft was written."
    return pending.update(is_stale=True, stale_reason=reason,
                          updated_at=timezone.now())


@transaction.atomic
def regenerate(digest, *, actor=None):
    """FR-3.30a — one click. Re-collect, re-render, clear the flag."""
    if digest.state != Digest.State.PENDING:
        raise ValueError("Only a pending digest can be regenerated.")
    digest.items.all().delete()
    owed = owed_to(digest.contact_id, tenant=digest.tenant, cadence=digest.cadence,
                   until=timezone.now())
    if not owed:
        digest.state = Digest.State.SKIPPED
        digest.save(update_fields=["state", "updated_at"])
        return digest
    narrative = narrative_for(digest.tenant, owed, contact=digest.contact) \
        if digest.is_ai_generated else ""
    digest.body_text, digest.body_html = render(digest, owed, narrative=narrative)
    digest.is_stale = False
    digest.stale_reason = ""
    digest.period_end = timezone.now()
    digest.save(update_fields=["body_text", "body_html", "is_stale", "stale_reason",
                               "period_end", "updated_at"])
    for update, row in owed:
        DigestItem.objects.create(tenant=digest.tenant, digest=digest,
                                  task_update=update, stakeholder=row)
    return digest


# ------------------------------------------------- approval, send, expiry

class DigestActionRefused(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


@transaction.atomic
def approve(digest, *, actor, role):
    from apps.tenancy.models import Role

    if role not in (Role.FF, Role.CF):
        # Matrix 8.3 — the single most important role boundary in the product.
        raise DigestActionRefused("A VA cannot approve a digest.", status=403)
    if digest.state != Digest.State.PENDING:
        raise DigestActionRefused(f"This digest is {digest.state}.", status=409)
    digest.state = Digest.State.APPROVED
    digest.approved_by = actor
    digest.approved_at = timezone.now()
    digest.save(update_fields=["state", "approved_by", "approved_at", "updated_at"])
    AuditEvent.all_objects.create(
        tenant=digest.tenant, actor=actor, verb="digest.approved",
        target_type="digest", target_id=digest.pk,
        payload={"contact": str(digest.contact_id), "cadence": digest.cadence,
                 "was_stale": digest.is_stale},
    )
    return digest


@transaction.atomic
def skip(digest, *, actor, role):
    from apps.tenancy.models import Role

    if role not in (Role.FF, Role.CF):
        # Skipping suppresses a client email: a send decision either way.
        raise DigestActionRefused("A VA cannot skip a digest.", status=403)
    if digest.state != Digest.State.PENDING:
        raise DigestActionRefused(f"This digest is {digest.state}.", status=409)
    digest.state = Digest.State.SKIPPED
    digest.items.all().delete()        # its claim is released
    digest.save(update_fields=["state", "updated_at"])
    AuditEvent.all_objects.create(
        tenant=digest.tenant, actor=actor, verb="digest.skipped",
        target_type="digest", target_id=digest.pk, payload={})
    return digest


def edit_body(digest, *, actor, role, body_text):
    if digest.state != Digest.State.PENDING:
        raise DigestActionRefused(f"This digest is {digest.state}.", status=409)
    digest.body_text = body_text
    digest.save(update_fields=["body_text", "updated_at"])
    AuditEvent.all_objects.create(
        tenant=digest.tenant, actor=actor, verb="digest.edited",
        target_type="digest", target_id=digest.pk, payload={})
    return digest


def footer_for(digest) -> str:
    """FR-3.33 — every digest carries the recipient's own cadence control."""
    from django.conf import settings

    from apps.work.models import StakeholderToken

    row = (digest.items.exclude(stakeholder__isnull=True)
           .select_related("stakeholder").first())
    if row is None:
        return ""
    _, raw = StakeholderToken.issue(row.stakeholder)
    root = settings.APP_ROOT_URL
    if not root.startswith("http"):
        root = settings.PUBLIC_BASE_URL.rstrip("/") + "/" + root.lstrip("/")
    return (f"\n\n—\nChange how often you hear from us, or stop these updates: "
            f"{root.rstrip('/')}/updates/{raw}")


@transaction.atomic
def send(digest, *, actor=None):
    """The only path from approved to sent. Goes out through the Outbox."""
    from apps.crm.services import outbox

    if digest.state != Digest.State.APPROVED:
        raise DigestActionRefused(f"This digest is {digest.state}; it cannot be sent.")
    address = digest.contact.primary_email
    if not address:
        raise DigestActionRefused(
            f"{digest.contact.first_name} has no email address to send to.")
    subject = _subject(digest)
    message = outbox.create_message(
        tenant=digest.tenant, producer=OutboxMessage.Producer.DIGEST,
        to_address=address, to_contact=digest.contact, subject=subject,
        body_text=digest.body_text + footer_for(digest),
        body_html=digest.body_html, is_ai_generated=digest.is_ai_generated,
        actor=actor, force_direct=True,
        source_type="digest", source_id=digest.pk,
    )
    digest.state = Digest.State.SENT
    digest.outbox_message = message
    digest.save(update_fields=["state", "outbox_message", "updated_at"])
    digest.items.exclude(stakeholder__isnull=True).update(updated_at=timezone.now())
    from apps.work.models import Stakeholder

    Stakeholder.all_objects.filter(
        pk__in=digest.items.values_list("stakeholder_id", flat=True)
    ).update(last_notified_at=timezone.now())
    AuditEvent.all_objects.create(
        tenant=digest.tenant, actor=actor, verb="digest.sent",
        target_type="digest", target_id=digest.pk,
        payload={"to": address, "cadence": digest.cadence,
                 "outbox_message": str(message.pk)},
    )
    return message


def _subject(digest) -> str:
    label = {Cadence.WEEKLY: "Weekly update", Cadence.MONTHLY: "Monthly update",
             Cadence.EVERY_UPDATE: "Progress update"}[digest.cadence]
    return f"{label} from {digest.tenant.name}"


def send_due(tenant, *, now=None):
    now = now or timezone.now()
    sent = []
    for digest in Digest.objects.filter(state=Digest.State.APPROVED,
                                        send_window_at__lte=now).select_related(
                                            "contact", "tenant"):
        send(digest, actor=digest.approved_by)
        sent.append(digest)
    return sent


def expire_due(tenant, *, now=None):
    """FR-3.30 — an unapproved digest never sends. Its items are deleted, so
    everything in it is owed again next period: deferred, not dropped."""
    now = now or timezone.now()
    expired = []
    for digest in Digest.objects.filter(state=Digest.State.PENDING,
                                        send_window_at__lte=now):
        digest.items.all().delete()
        digest.state = Digest.State.EXPIRED
        digest.save(update_fields=["state", "updated_at"])
        AuditEvent.all_objects.create(
            tenant=digest.tenant, verb="digest.expired", target_type="digest",
            target_id=digest.pk, payload={"cadence": digest.cadence})
        expired.append(digest)
    return expired


# ---------------------------------------------------- the on-demand report

def report_for(tenant, *, contact, since, until=None):
    """FR-3.38 — the same content as a digest, pulled rather than sent.

    No approval and no email, because a client pulling a report has no outward
    effect. It deliberately does NOT consume anything: no `digest_item` is
    written, so reading a report never eats the Friday email.
    """
    until = until or timezone.now()
    reach = stakeholder_service.tasks_for_contact(tenant, contact.pk)
    task_ids = [task_id for task_id, (task, _row) in reach.items() if task.is_client_visible]
    rows = list(qualifying_updates(task_ids, contact.pk, since=since, until=until))
    owed = [(row, None) for row in rows]
    return {"body_text": deterministic_body(owed), "updates": rows,
            "since": since, "until": until}


def report_for_company(tenant, *, company, since, until=None):
    """The portal's report for a client user: their company's client-visible
    work, whether or not they are a stakeholder on it."""
    until = until or timezone.now()
    task_ids = list(Task.objects.filter(
        client_company=company, is_client_visible=True, deleted_at__isnull=True
    ).values_list("pk", flat=True))
    rows = TaskUpdate.objects.filter(
        task_id__in=task_ids, created_at__gte=since, created_at__lt=until,
    ).exclude(kind=K.COMMENT_ADDED, to_value=Comment.Visibility.INTERNAL).select_related(
        "task", "actor").order_by("created_at")
    owed = [(row, None) for row in rows]
    return {"body_text": deterministic_body(owed), "updates": list(rows),
            "since": since, "until": until}
