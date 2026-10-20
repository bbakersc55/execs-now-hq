"""Demo visitors (Melissa's feedback W1, owner's decisions 2026-10-17).

A visitor gets **their own private copy of the demo practice**, on the demo,
seeded by the same seed as Summit Operations Partners (`demo.build`) with its
dates relative to the day it is made. They are its practice owner. A copy is
an ordinary practice, so everything that keeps practices apart keeps it apart;
`DemoVisitor` is the platform's record of who it is for and how long it lives.

- **Sign-in** by a link to the visitor's email, as portal users sign in.
- **Mail**: everything the copy sends goes to the visitor's own address,
  through the demo's one send-only connection, from `DEMO_MAIL_FROM`
  (`config/environment.py`). Nothing reaches the fictional people.
- **AI**: the platform's demo key, stopped hard per copy at `AI_PER_DAY` a
  day and `AI_IN_ALL` for its life (`ai_stop`, checked in
  `apps/tenancy/claude.py` before any call). Spend survives a reset.
- **Life**: `DEFAULT_DAYS` from the invitation, extendable by the platform
  owner; read-only for `READ_ONLY_DAYS` after it ends, then deleted, files
  and the people in it included (`sweep`).
- **Reset my demo** empties the copy and seeds it again the same way, as of
  the day of the reset. The visitor's sign-in and the copy's own dates (when
  it was made, when it ends) survive.

**Setting a copy up takes minutes** (the demo's own seed took 185 s on
Railway), and the seed moves the process's clock while it runs
(`clock.at`), so it never runs inside a web request. The request writes the
records and starts `manage.py demo_visitors setup <id>` as a process of its
own (`launch`), and the visitor sees "Your demo is being set up" until it
finishes. The demo has no worker; a process started from the web container
needs none. A process killed part-way (a redeploy) rolls back whole: the
copy is marked as not finished after `SETUP_STALE` and "Reset" tries again.

Summit's own reseed (`manage.py seed_demo`) is unchanged, and empties the
whole demo database as it always has, every copy included.
"""

from __future__ import annotations

import logging
import secrets
import string
import subprocess
import sys
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Sum
from django.utils import timezone

log = logging.getLogger(__name__)

DEFAULT_DAYS = 30
MOST_DAYS = 365
READ_ONLY_DAYS = 7
AI_PER_DAY = Decimal("2.00")
AI_IN_ALL = Decimal("10.00")
SETUP_STALE = timedelta(minutes=20)
#: How often any request on the demo may start a sweep, at most.
SWEEP_EVERY = 3600

FAILED_MESSAGE = ("Your demo's setup did not finish. Ask whoever invited you to reset it, "
                  "and it will be set up again.")
#: Said wherever Gmail or Drive would be connected (the Email settings page).
NO_CONNECTIONS = ("This is your own copy of the demo, so it connects no Gmail or Drive. "
                  "Everything it sends goes to your own address, through the demo's own "
                  "connection.")

_EMAIL = __import__("re").compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class VisitorRefused(ValueError):
    def __init__(self, errors: dict[str, str]):
        super().__init__("; ".join(errors.values()))
        self.errors = errors


# ------------------------------------------------------------------ reading

def of(tenant):
    """The practice's `DemoVisitor`, or None for every practice that is not a
    visitor's copy. Remembered on the tenant object for the request."""
    from apps.tenancy.models import DemoVisitor

    if tenant is None:
        return None
    if not hasattr(tenant, "_demo_visitor_row"):
        tenant._demo_visitor_row = DemoVisitor.objects.filter(tenant_id=tenant.pk).first()
    return tenant._demo_visitor_row


def get(pk):
    """One visitor's record, with its practice, or None."""
    from apps.tenancy.models import DemoVisitor

    return DemoVisitor.objects.select_related("tenant").filter(pk=pk).first()


def is_copy(tenant) -> bool:
    return of(tenant) is not None


def deletes_on(visitor) -> datetime:
    return visitor.expires_at + timedelta(days=READ_ONLY_DAYS)


def ended(visitor, now=None) -> bool:
    return (now or timezone.now()) >= visitor.expires_at


def gone(visitor, now=None) -> bool:
    return (now or timezone.now()) >= deletes_on(visitor)


def read_only_message(visitor) -> str:
    end = timezone.localtime(deletes_on(visitor)).date()
    return (f"This demo has ended. It can be looked at until {end:%B} {end.day}, then it is "
            "deleted. Nothing in it can be changed.")


def setting_up(visitor, now=None) -> bool:
    """Being set up, and not stuck: a setup started more than `SETUP_STALE`
    ago was killed part-way and reads as not finished."""
    from apps.tenancy.models import DemoVisitor

    if visitor.state != DemoVisitor.State.SETTING_UP:
        return False
    started = visitor.setup_started_at or visitor.created_at
    return (now or timezone.now()) - started < SETUP_STALE


def shown_state(visitor) -> str:
    from apps.tenancy.models import DemoVisitor

    if visitor.state == DemoVisitor.State.SETTING_UP and not setting_up(visitor):
        return DemoVisitor.State.FAILED
    return visitor.state


def spend(tenant) -> dict:
    """What the copy has spent on Claude: today (its own time zone) and in
    all. From the calls themselves, which a reset keeps."""
    from apps.tenancy.models import AiCall

    zone = ZoneInfo(tenant.timezone or "America/Denver")
    start = datetime.combine(timezone.now().astimezone(zone).date(), time.min, tzinfo=zone)
    calls = AiCall.all_objects.filter(tenant_id=tenant.pk)
    today = calls.filter(created_at__gte=start).aggregate(s=Sum("cost_usd"))["s"]
    total = calls.aggregate(s=Sum("cost_usd"))["s"]
    return {"today": Decimal(today or 0).quantize(Decimal("0.01")),
            "total": Decimal(total or 0).quantize(Decimal("0.01"))}


def ai_stop(tenant) -> str:
    """Why this copy may not call Claude now, or "" when it may. Every AI
    control shows this instead of itself, and the server refuses the call."""
    visitor = of(tenant)
    if visitor is None:
        return ""
    if ended(visitor):
        return "This demo has ended, so its AI is off."
    spent = spend(tenant)
    if spent["total"] >= AI_IN_ALL:
        return (f"This demo's AI allowance (${AI_IN_ALL} in all) is used up, so its AI "
                "is off.")
    if spent["today"] >= AI_PER_DAY:
        return (f"This demo's AI allowance for today (${AI_PER_DAY}) is used up. It "
                "comes back tomorrow.")
    return ""


def days_of(visitor) -> int:
    """How many days the copy was given, as the visitor reads it."""
    return max(1, round((visitor.expires_at - visitor.created_at).total_seconds() / 86400))


def agree(visitor, *, version: str, actor) -> None:
    """The visitor's tick (2026-10-17), with the time, against the beta
    agreement's current version. Once per version: a second tick changes
    nothing, and a new version asks again (2026-10-20)."""
    from apps.platform import agreement
    from apps.tenancy.models import AuditEvent, DemoVisitor

    current = agreement.VERSION
    if version != current:
        raise VisitorRefused({"version": "The beta agreement changed. Reload the page."})
    if not must_agree(visitor):
        return
    now = timezone.now()
    DemoVisitor.objects.filter(pk=visitor.pk).update(agreed_at=now, agreed_version=current)
    visitor.agreed_at, visitor.agreed_version = now, current
    AuditEvent.all_objects.create(
        tenant=visitor.tenant, actor=actor, verb="demo_visitor.agreed", target_type="tenant",
        target_id=visitor.tenant_id, payload={"version": current})


def must_agree(visitor) -> bool:
    """Not yet ticked, or ticked against an older version of the agreement."""
    from apps.platform import agreement

    return visitor.agreed_at is None or visitor.agreed_version != agreement.VERSION


def describe(tenant) -> dict | None:
    """What the copy's own screens are told about it (`/api/me`)."""
    from apps.platform import agreement

    visitor = of(tenant)
    if visitor is None:
        return None
    spent = spend(tenant)
    return {
        "agreement_required": must_agree(visitor),
        "agreement_version": agreement.VERSION,
        "days": days_of(visitor),
        "state": shown_state(visitor),
        "expires_at": visitor.expires_at.isoformat(),
        "deletes_on": deletes_on(visitor).isoformat(),
        "read_only": ended(visitor),
        "ai_stop": ai_stop(tenant),
        "ai_spent_today_usd": str(spent["today"]),
        "ai_spent_total_usd": str(spent["total"]),
        "ai_per_day_usd": str(AI_PER_DAY),
        "ai_in_all_usd": str(AI_IN_ALL),
        "reset_count": visitor.reset_count,
    }


def rows() -> list[dict]:
    """The platform's list: who each copy is for and how it stands. The
    platform's record and totals, nothing from inside a copy."""
    from apps.tenancy.models import DemoVisitor, Membership

    out = []
    for visitor in DemoVisitor.objects.select_related("tenant").order_by("-created_at"):
        seen = (Membership.all_objects.filter(tenant_id=visitor.tenant_id, role="FF",
                                              user__email__iexact=visitor.email)
                .values_list("user__last_login_at", flat=True).first())
        spent = spend(visitor.tenant)
        out.append({
            "id": str(visitor.pk), "name": visitor.name, "email": visitor.email,
            "note": visitor.note, "state": shown_state(visitor),
            "state_error": visitor.state_error,
            "created_at": visitor.created_at.isoformat(),
            "expires_at": visitor.expires_at.isoformat(),
            "deletes_on": deletes_on(visitor).isoformat(),
            "ended": ended(visitor),
            "invited_at": visitor.invited_at.isoformat() if visitor.invited_at else None,
            "agreed_at": visitor.agreed_at.isoformat() if visitor.agreed_at else None,
            "last_activity_at": seen.isoformat() if seen else None,
            "ai_spent_today_usd": str(spent["today"]),
            "ai_spent_total_usd": str(spent["total"]),
            "reset_count": visitor.reset_count,
        })
    return out


# ------------------------------------------------------------ the platform

def _require_demo():
    from config import environment

    if not environment.is_demo():
        raise VisitorRefused({"demo": "Demo visitors are made only on the demo."})


def _new_tag() -> str:
    from apps.tenancy.models import DemoVisitor

    alphabet = string.ascii_lowercase + string.digits
    while True:
        tag = "".join(secrets.choice(alphabet) for _ in range(6))
        if not DemoVisitor.objects.filter(tag=tag).exists():
            return tag


def invite(*, name: str, email: str, days=DEFAULT_DAYS, note: str = "", actor):
    """The copy's records, now; its setup and the invitation, in a process
    of their own (`launch`). Refused, naming the field, before anything is
    written."""
    from apps.accounts.models import User
    from apps.tenancy.demo import cast
    from apps.tenancy.models import AuditEvent, DemoVisitor, Membership, Tenant

    _require_demo()
    name, email, note = (name or "").strip(), (email or "").strip().lower(), (note or "").strip()
    errors = {}
    if not name:
        errors["name"] = "Give the visitor's name."
    elif len(name) > 200:
        errors["name"] = "The name is at most 200 characters."
    if not _EMAIL.match(email):
        errors["email"] = "Give the visitor's email address."
    elif Membership.all_objects.filter(user__email__iexact=email,
                                       revoked_at__isnull=True).exists():
        # One practice per sign-in (B4): an address that signs in to Summit or
        # to another copy cannot have one more.
        errors["email"] = ("That address already signs in to a practice on the demo. Use "
                           "another, such as a plus address (you+demo@…).")
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = 0
    if not 1 <= days <= MOST_DAYS:
        errors["days"] = f"Give a number of days from 1 to {MOST_DAYS}."
    if errors:
        raise VisitorRefused(errors)

    now = timezone.now()
    with transaction.atomic():
        tag = _new_tag()
        tenant = Tenant.objects.create(
            name=cast.PRACTICE, email_display_name=cast.PRACTICE, slug=f"demo-visitor-{tag}",
            created_by=actor, from_address=settings.DEMO_MAIL_FROM, inbound_domain="",
            hold_all_digests=True, ai_unattended_daily_cap_usd=Decimal("0"))
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            user = User.objects.create_user(email=email, full_name=name)
        visitor = DemoVisitor.objects.create(
            tenant=tenant, name=name, email=email, note=note, tag=tag, invited_by=actor,
            expires_at=now + timedelta(days=days), setup_started_at=now)
        AuditEvent.all_objects.create(
            tenant=tenant, actor=actor, verb="demo_visitor.invited", target_type="tenant",
            target_id=tenant.pk, payload={"email": email, "days": days})
        transaction.on_commit(lambda: launch("setup", visitor.pk))
    return visitor


def extend(visitor, *, days=DEFAULT_DAYS, actor) -> None:
    """More days: from its end, or from now when it has already ended."""
    from apps.tenancy.models import AuditEvent

    try:
        days = int(days)
    except (TypeError, ValueError):
        days = 0
    if not 1 <= days <= MOST_DAYS:
        raise VisitorRefused({"days": f"Give a number of days from 1 to {MOST_DAYS}."})
    start = max(visitor.expires_at, timezone.now())
    visitor.expires_at = start + timedelta(days=days)
    visitor.save(update_fields=["expires_at", "updated_at"])
    AuditEvent.all_objects.create(
        tenant=visitor.tenant, actor=actor, verb="demo_visitor.extended",
        target_type="tenant", target_id=visitor.tenant_id,
        payload={"days": days, "expires_at": visitor.expires_at.isoformat()})


def reset(visitor, *, actor) -> None:
    """Empty the copy and seed it again, in a process of its own. Refused
    while it is already being set up."""
    from apps.tenancy.models import AuditEvent, DemoVisitor

    if setting_up(visitor):
        raise VisitorRefused({"state": "It is already being set up."})
    now = timezone.now()
    visitor.state, visitor.state_error = DemoVisitor.State.SETTING_UP, ""
    visitor.setup_started_at, visitor.last_reset_at = now, now
    visitor.reset_count += 1
    visitor.save(update_fields=["state", "state_error", "setup_started_at", "last_reset_at",
                                "reset_count", "updated_at"])
    AuditEvent.all_objects.create(
        tenant=visitor.tenant, actor=actor, verb="demo_visitor.reset",
        target_type="tenant", target_id=visitor.tenant_id, payload={})
    transaction.on_commit(lambda: launch("setup", visitor.pk))


# --------------------------------------------------------------- processes

def launch(action: str, visitor_id=None) -> None:
    """`manage.py demo_visitors <action> [id]`, as a process of its own that
    outlives the request. Its output goes to the container's log."""
    command = [sys.executable, str(settings.BASE_DIR / "manage.py"), "demo_visitors", action]
    if visitor_id is not None:
        command.append(str(visitor_id))
    subprocess.Popen(command, cwd=str(settings.BASE_DIR), stdin=subprocess.DEVNULL,
                     start_new_session=True)


def maybe_sweep() -> None:
    """At most once an hour per web process: start a sweep. The demo has no
    worker to schedule it on."""
    from django.core.cache import cache

    from config import environment

    if environment.is_demo() and cache.add("demo-visitors-sweep", 1, SWEEP_EVERY):
        try:
            launch("sweep")
        except OSError:                         # a sweep is never worth a failed request
            log.exception("demo visitors: could not start a sweep")


def run_setup(visitor_id) -> None:
    """In its own process: empty the copy (nothing, the first time) and seed
    it, in one transaction; then the invitation, the first time only. A
    failure leaves the copy as it was and says why."""
    from apps.tenancy import demo
    from apps.tenancy.models import DemoVisitor

    visitor = DemoVisitor.objects.select_related("tenant").get(pk=visitor_id)
    try:
        with transaction.atomic():
            old_files = empty_practice(visitor.tenant, keep_user_email=visitor.email,
                                       keep_ai_calls=True)
            demo.build(visitor=visitor, today=timezone.localdate(
                timezone=ZoneInfo("America/Denver")))
            DemoVisitor.objects.filter(pk=visitor.pk).update(
                state=DemoVisitor.State.READY, state_error="",
                setup_finished_at=timezone.now())
    except Exception as exc:
        log.exception("demo visitors: setup of %s failed", visitor_id)
        DemoVisitor.objects.filter(pk=visitor.pk).update(
            state=DemoVisitor.State.FAILED, state_error=str(exc)[:2000])
        raise
    _remove_files(old_files)
    visitor.refresh_from_db()
    if visitor.invited_at is None:
        send_invitation(visitor)


def send_invitation(visitor) -> str:
    """The sign-in link, a week to use it, from `DEMO_MAIL_FROM`, through the
    copy's own Outbox: the copy's mail goes to the visitor, who is also who
    this is for. Returns "" when it went, else why not, which the platform's
    list shows; it is never marked sent when it could not reach them."""
    from apps.accounts.models import MagicLinkPurpose, MagicLinkToken
    from apps.accounts.views import send_visitor_invitation
    from apps.crm.services.outbox import _demo_recipient
    from apps.tenancy.models import DemoVisitor, Membership

    membership = (Membership.all_objects.select_related("user", "tenant")
                  .filter(tenant_id=visitor.tenant_id, role="FF",
                          user__email__iexact=visitor.email).first())
    why = ""
    if membership is None:
        why = "Their demo is not set up yet."
    elif _demo_recipient(membership.tenant) != visitor.email.lower():
        why = (f"The invitation was not sent: the demo has no working Gmail connection "
               f"sending as {settings.DEMO_MAIL_FROM}. Connect it in Summit, then send it.")
    else:
        _, raw = MagicLinkToken.issue(tenant=membership.tenant, user=membership.user,
                                      purpose=MagicLinkPurpose.INVITE)
        if not send_visitor_invitation(membership, raw, visitor=visitor):
            why = "The invitation was not sent: Gmail refused it. Try sending it again."
    if why:
        DemoVisitor.objects.filter(pk=visitor.pk).update(state_error=why)
    else:
        DemoVisitor.objects.filter(pk=visitor.pk).update(invited_at=timezone.now(),
                                                         state_error="")
    return why


def delete(visitor, *, actor=None) -> None:
    """The copy, its files, the fictional people in it and the visitor's own
    sign-in, all gone. The audit trail of it goes with it."""
    from apps.accounts.models import User
    from apps.tenancy.models import Tenant

    tenant = visitor.tenant
    with transaction.atomic():
        files = empty_practice(tenant, keep_user_email="", keep_ai_calls=False)
        visitor_user = User.objects.filter(email__iexact=visitor.email).first()
        if visitor_user is not None and not visitor_user.is_platform_owner:
            visitor_user.delete()
        Tenant.objects.filter(pk=tenant.pk).delete()
    _remove_files(files)
    log.info("demo visitors: deleted the copy for %s (by %s)", visitor.email,
             getattr(actor, "email", "the sweep"))


def sweep(now=None) -> dict:
    """Delete each copy whose read-only week is over. Run by `maybe_sweep`."""
    from apps.tenancy.models import DemoVisitor

    now = now or timezone.now()
    deleted = 0
    for visitor in DemoVisitor.objects.select_related("tenant").filter(
            expires_at__lte=now - timedelta(days=READ_ONLY_DAYS)):
        delete(visitor)
        deleted += 1
    return {"deleted": deleted}


# ----------------------------------------------------------- emptying one

def empty_practice(tenant, *, keep_user_email: str, keep_ai_calls: bool) -> list:
    """Every row of one practice, and the people only it had, in one go; the
    practice row itself is kept. Returns its stored files, for the caller to
    take out of the bucket once this has committed.

    Each practice's rows carry `tenant_id` (the isolation meta-test holds
    every domain table to it), so they are deleted by that, table by table,
    with the foreign keys checked at the end; the many-to-many tables first,
    by the rows they join. A person's own ledger is theirs, not the
    practice's: the people of this practice have theirs taken too.

    `keep_ai_calls` keeps what it has spent, so a reset cannot buy a copy a
    new AI allowance."""
    from django.apps import apps

    from apps.accounts.models import User
    from apps.personal.models import OwnedModel, PersonalLedger
    from apps.tenancy.management.commands.ensure_schedules import remove_for
    from apps.tenancy.models import (
        AiCall, Membership, PracticeModule, StoredFile, Tenant, TenantScopedModel,
    )

    files = [(f.bucket, f.object_key) for f in StoredFile.all_objects.filter(tenant=tenant)]
    people = set(Membership.all_objects.filter(tenant=tenant).values_list("user_id", flat=True))
    ledgers = list(PersonalLedger.objects.filter(owner_id__in=people)
                   .values_list("pk", flat=True))
    scoped = [m for m in apps.get_models() if issubclass(m, TenantScopedModel)
              and not (keep_ai_calls and m is AiCall)]
    practice = TenantScopedModel._meta.get_field("tenant").column
    owned = [m for m in apps.get_models() if issubclass(m, OwnedModel)]
    Tenant.objects.filter(pk=tenant.pk).update(email_logo=None, email_mark=None,
                                               marketing_flyer=None)
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL DEFERRED")
        if ledgers:
            for model in owned:
                cursor.execute(f'DELETE FROM "{model._meta.db_table}" WHERE ledger_id = ANY(%s)',
                               [ledgers])
            cursor.execute(f'DELETE FROM "{PersonalLedger._meta.db_table}" WHERE id = ANY(%s)',
                           [ledgers])
        for model in scoped:
            table = model._meta.db_table
            for m2m in model._meta.local_many_to_many:
                through = m2m.remote_field.through
                if through._meta.auto_created:
                    column = m2m.m2m_column_name()
                    cursor.execute(
                        f'DELETE FROM "{through._meta.db_table}" WHERE "{column}" IN '
                        f'(SELECT id FROM "{table}" WHERE "{practice}" = %s)', [tenant.pk])
        for model in scoped:
            cursor.execute(f'DELETE FROM "{model._meta.db_table}" WHERE "{practice}" = %s',
                           [tenant.pk])
        # Checked now, and deferred again for whatever this transaction does
        # next (a reset seeds the copy straight after).
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute("SET CONSTRAINTS ALL DEFERRED")
    PracticeModule.objects.filter(tenant=tenant).delete()
    remove_for(tenant)
    # The fictional people: only this practice had them.
    fictional = User.objects.filter(pk__in=people, is_platform_owner=False)
    if keep_user_email:
        fictional = fictional.exclude(email__iexact=keep_user_email)
    for user in fictional:
        if not Membership.all_objects.filter(user=user).exists():
            user.delete()
    return files


def remove_files(files) -> int:
    """Take these out of the demo's bucket; how many went."""
    from apps.tenancy import storage

    removed = 0
    for bucket, key in files:
        if bucket != settings.GCS_BUCKET_MEDIA:
            continue                    # only ever the demo's own configured bucket
        try:
            storage.delete_object(bucket, key)
            removed += 1
        except storage.StorageError:    # an orphan in the demo bucket costs nothing
            pass
    return removed


_remove_files = remove_files
