"""Reminder emails about digests (docs/digest_schedule.md §6).

Three notices, all to the practice's **own people** and never to a client:

- **ready**: this cycle's digests are written and waiting for approval;
- **last call**: the send time is near and something is still waiting;
- **not sent**: the send time passed and something was not approved.

They go to the practice owner for every digest and to each associate for their
own clients' (the companies assigned to them, the rule the Digests screen
uses). Assistants get none: they cannot approve.

**What they contain:** who each digest is for, their company, the cadence and
the times. **Never a digest's text**: client material is read in the app. They
are sent without an approval step for the same reason the client-activity
notice is: they are internal, and say only that something is waiting.

"Already sent" is one audit event per person, kind and send time, the way the
client-activity notice keeps its place. No table.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from django.conf import settings
from django.utils import timezone

from apps.crm.models import OutboxMessage
from apps.tenancy.models import AuditEvent, ClientAssignment, Membership, Role
from apps.work import digests
from apps.work.models import Cadence, Digest

VERB = "digest_reminder.sent"
READY, LAST_CALL, NOT_SENT, READY_EVERY_UPDATE = (
    "ready", "last_call", "not_sent", "ready_every_update")
SCHEDULED = (Cadence.WEEKLY, Cadence.MONTHLY)
#: D9: the last call goes this long before the send time...
LAST_CALL_LEAD = timedelta(hours=2)
#: ...unless that is outside working hours, when it goes at this hour on the
#: last weekday before the send time.
END_OF_DAY_HOUR = 16
#: D8: every-update digests are announced at most this often per person.
EVERY_UPDATE_THROTTLE = timedelta(hours=1)
#: A "not sent" notice is about now; a digest that went late long ago (the
#: worker was down, say) is not announced as news.
NOT_SENT_FRESH = timedelta(hours=24)


def _working(local: datetime) -> bool:
    return local.weekday() < 5 and 9 <= local.hour < 17


def last_call_at(tenant, drafted_at, send_at):
    """When the last call goes for digests drafted at one time and sent at
    another: two hours before the send when someone would be at work then,
    otherwise 4:00 PM on the last weekday before it (after the draft)."""
    zone = digests.zone(tenant)
    candidate = send_at - LAST_CALL_LEAD
    if _working(candidate.astimezone(zone)):
        return candidate
    day = send_at.astimezone(zone).date()
    for back in range(8):
        end_of_day = datetime.combine(day - timedelta(days=back), time(END_OF_DAY_HOUR),
                                      tzinfo=zone)
        if end_of_day >= send_at or end_of_day.weekday() >= 5:
            continue
        if end_of_day > drafted_at:
            return end_of_day
        break
    return candidate


def recipients(tenant):
    """`[(user, company_ids or None)]`: None is every digest (practice owner)."""
    found = []
    members = (Membership.all_objects
               .filter(tenant=tenant, role__in=[Role.FF, Role.CF], revoked_at__isnull=True,
                       user__is_active=True)
               .select_related("user").order_by("role", "user__email"))
    for member in members:
        if not member.user.email:
            continue
        if member.role == Role.FF:
            found.append((member.user, None))
            continue
        companies = list(ClientAssignment.all_objects.filter(
            tenant=tenant, user_id=member.user_id, removed_at__isnull=True,
        ).values_list("company_id", flat=True))
        if companies:
            found.append((member.user, companies))
    return found


def _visible(tenant, companies, **filters):
    rows = (Digest.all_objects.filter(tenant=tenant, **filters)
            .select_related("contact", "contact__company").order_by("send_window_at"))
    if companies is not None:
        rows = rows.filter(contact__company_id__in=companies)
    return list(rows)


def _already(tenant, user, kind, key) -> bool:
    return AuditEvent.all_objects.filter(
        tenant=tenant, verb=VERB, payload__user=str(user.pk), payload__kind=kind,
        payload__key=key).exists()


def _mark(tenant, user, kind, key, rows, now) -> None:
    AuditEvent.all_objects.create(
        tenant=tenant, verb=VERB, target_type="tenant", target_id=tenant.pk,
        payload={"user": str(user.pk), "kind": kind, "key": key, "digests": len(rows),
                 "ids": [str(row.pk) for row in rows], "at": now.isoformat()})


def _said(tenant, moment) -> str:
    local = moment.astimezone(digests.zone(tenant))
    hour = local.strftime("%I:%M %p").lstrip("0")
    return f"{local:%A} {local.day} {local:%B}, {hour}"


def _digests_url() -> str:
    base = settings.APP_ROOT_URL if settings.IS_LOCAL else settings.PUBLIC_BASE_URL
    return base.rstrip("/") + "/digests"


def _rows(tenant, rows):
    items = []
    for digest in rows:
        contact = digest.contact
        company = contact.company.name if contact.company_id else ""
        who = f"{contact.first_name} {contact.last_name}".strip() or "A stakeholder"
        what = f"{digest.get_cadence_display().lower()} digest" + (f" · {company}" if company else "")
        when = ("is sent as soon as it is approved" if digest.cadence == Cadence.EVERY_UPDATE
                and digest.state == Digest.State.PENDING
                else f"send time: {_said(tenant, digest.send_window_at)}")
        items.append({"who": who, "what": what, "when": when})
    return items


def compose(tenant, kind, rows, *, send_at=None) -> tuple[str, str, str]:
    """`(subject, html, text)`. Names, cadences and times; no digest text."""
    from django.template.loader import render_to_string

    from apps.crm.services import email_layout

    count = len(rows)
    noun = f"{count} digest{'' if count == 1 else 's'}"
    verb = "is" if count == 1 else "are"
    until = ("You can still send it yourself with Send now until the next digest for that "
             "person is drafted; after that its updates move into the next one.")
    if kind == READY:
        subject = f"{noun} {verb} ready to approve"
        intro = (f"{noun.capitalize()} {verb} written and waiting for your approval. Anything "
                 f"not approved by {_said(tenant, send_at)} is not sent.")
    elif kind == READY_EVERY_UPDATE:
        subject = f"{noun} {verb} ready to approve"
        intro = (f"{noun.capitalize()} for people who asked to hear about every update "
                 f"{verb} waiting. Each is sent as soon as it is approved.")
    elif kind == LAST_CALL:
        subject = f"Last call: {noun} still waiting for approval"
        intro = (f"{noun.capitalize()} {verb} still waiting. Anything not approved by "
                 f"{_said(tenant, send_at)} is not sent.")
    else:
        subject = f"{noun} {'was' if count == 1 else 'were'} not sent"
        intro = (f"Nobody approved {'this digest' if count == 1 else 'these digests'} in "
                 f"time, so {'it was' if count == 1 else 'they were'} not sent. {until}")
    items = _rows(tenant, rows)
    closing = f"Open Digests to read and approve: {_digests_url()}"
    content = render_to_string("email/client_activity_content.html",
                               email_layout.template_context(tenant, intro=intro, rows=items,
                                                             closing=closing))
    html = email_layout.document(tenant, content_html=content, subject=subject, internal=True,
                                 preheader=intro)
    text = (intro + "\n\n" + "\n".join(f"- {i['who']}: {i['what']} ({i['when']})" for i in items)
            + "\n\n" + closing)
    return subject, html, text


def _send(tenant, user, kind, key, rows, now, *, send_at=None) -> bool:
    from apps.crm.services import outbox

    subject, html, text = compose(tenant, kind, rows, send_at=send_at)
    try:
        outbox.create_message(
            tenant=tenant, producer=OutboxMessage.Producer.DIGEST_REMINDER,
            to_address=user.email, subject=subject, body_text=text, body_html=html,
            force_direct=True)
    except Exception:                                   # noqa: BLE001
        # No working mail connection, most likely. The Dashboard and the
        # Digests screen still show what is waiting; try again next tick, and
        # do not record a reminder that did not go.
        return False
    _mark(tenant, user, kind, key, rows, now)
    return True


def run(tenant, *, now=None) -> int:
    """Send whatever reminders are due. Called from the tick, after digests
    are drafted, marked late and sent, so it sees this minute's truth."""
    if not settings.DIGEST_REMINDERS_ENABLED:
        return 0
    now = now or timezone.now()
    sent = 0
    for user, companies in recipients(tenant):
        waiting = _visible(tenant, companies, state=Digest.State.PENDING,
                           cadence__in=SCHEDULED, send_window_at__gt=now)
        by_send = {}
        for digest in waiting:
            by_send.setdefault(digest.send_window_at, []).append(digest)
        for send_at, rows in by_send.items():
            key = send_at.isoformat()
            if not _already(tenant, user, READY, key):
                sent += _send(tenant, user, READY, key, rows, now, send_at=send_at)
                continue            # never "ready" and "last call" in one minute
            drafted = min(d.generated_at for d in rows)
            if (now >= last_call_at(tenant, drafted, send_at)
                    and not _already(tenant, user, LAST_CALL, key)):
                sent += _send(tenant, user, LAST_CALL, key, rows, now, send_at=send_at)

        late = _visible(tenant, companies, state=Digest.State.LATE,
                        send_window_at__gt=now - NOT_SENT_FRESH)
        by_send = {}
        for digest in late:
            by_send.setdefault(digest.send_window_at, []).append(digest)
        for send_at, rows in by_send.items():
            key = send_at.isoformat()
            if not _already(tenant, user, NOT_SENT, key):
                sent += _send(tenant, user, NOT_SENT, key, rows, now, send_at=send_at)

        # Every-update digests have no shared send time to key on, so what has
        # been announced is kept by digest: each is announced once, and no
        # more than one such email goes to a person in an hour.
        earlier = list(AuditEvent.all_objects
                       .filter(tenant=tenant, verb=VERB, payload__user=str(user.pk),
                               payload__kind=READY_EVERY_UPDATE)
                       .order_by("-created_at")[:200])
        last_at = max((datetime.fromisoformat(e.payload["at"]) for e in earlier), default=None)
        if last_at is None or now - last_at >= EVERY_UPDATE_THROTTLE:
            announced = {pk for e in earlier for pk in e.payload.get("ids", [])}
            fresh = [d for d in _visible(tenant, companies, state=Digest.State.PENDING,
                                         cadence=Cadence.EVERY_UPDATE)
                     if str(d.pk) not in announced]
            if fresh:
                sent += _send(tenant, user, READY_EVERY_UPDATE, now.isoformat(), fresh, now)
    return sent
