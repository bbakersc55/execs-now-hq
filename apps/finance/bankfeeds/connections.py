"""Bank connections: connect, map, Check now, Reconnect, Disconnect, and what
the provider's webhooks change (`docs/p6_bank_feeds.md`).

The practice owner's alone, as the rest of the books are. A **personal**
connection is the owner's household's: made from Personal finance, its
accounts mapped to their personal ledger's accounts, its lines in that ledger
only (`personal.py`), and reached by nobody but the owner who made it. The access token is
encrypted on the connection's own row with the key NMI's are kept under
(`crm.services.secrets`), and is never sent to a browser or written to a log.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from apps.crm.services import secrets
from apps.finance import services
from apps.finance.models import (
    BankConnection, BankFeedAccount, BankFeedTransaction, FinanceAccount, FinanceEntry,
)
from apps.finance.services import FinanceError

from . import providers

log = logging.getLogger(__name__)

S = BankConnection.Status
#: Check now, at most once an hour per connection.
CHECK_EVERY = timedelta(hours=1)
#: What the plan includes before each further connection is charged. Shown
#: only: nothing is charged yet (owner, 2026-11-04).
INCLUDED = 5
EACH_AFTER_CENTS = 50
PRICE_LINE = "5 bank connections included, then $0.50 a month each"
DEMO_REFUSAL = ("This is the demo. It never connects to a real bank, so connecting one is "
                "switched off here. The connection shown is the demo's own sample.")
NOT_SET_UP = "Bank feeds are not set up on this server yet."


def webhook_url() -> str:
    return settings.PUBLIC_BASE_URL.rstrip("/") + "/webhooks/plaid"


def available() -> bool:
    """Whether the feature shows: the provider's keys are set, or this is the
    demo (which shows its seeded connection and refuses new ones)."""
    from config import environment

    return providers.configured() or environment.is_demo()


def _refuse_demo() -> None:
    """The demo's connection is a sample: nothing may reach a provider with it."""
    from config import environment

    if environment.is_demo():
        raise FinanceError(DEMO_REFUSAL, status=409)


def _refuse_new() -> None:
    from config import environment

    if environment.is_demo():
        raise FinanceError(DEMO_REFUSAL, status=409)
    if not providers.configured():
        raise FinanceError(NOT_SET_UP, status=409)


def token_of(connection) -> str:
    return secrets.decrypt(connection.access_token_ciphertext)


def live(tenant):
    return BankConnection.all_objects.filter(tenant=tenant).exclude(status=S.DISCONNECTED)


def count(tenant) -> int:
    """Connections that count toward the plan: every one not disconnected."""
    return live(tenant).count()


# ------------------------------------------------------------------ notices

def tell_owner(tenant, *, title, text, source_type, source_id, url="/settings/finance",
               only=None):
    """The practice's owners; `only` (a user id) for a personal connection,
    whose news is its owner's alone."""
    from apps.notify.models import Kind
    from apps.notify.service import tell
    from apps.tenancy.models import Membership, Role

    owners = Membership.all_objects.filter(tenant=tenant, role=Role.FF,
                                           revoked_at__isnull=True)
    if only is not None:
        owners = owners.filter(user_id=only)
    for owner in owners:
        tell(tenant_id=tenant.pk, recipient_id=owner.user_id, kind=Kind.BANK, title=title,
             text=text, url=url, source_type=source_type[:40], source_id=source_id)


def needs_attention(connection, code: str, detail: str = "") -> None:
    """The login needs the owner: the card shows Reconnect, and a notice says
    so, once a day per connection."""
    BankConnection.all_objects.filter(pk=connection.pk).update(
        status=S.NEEDS_ATTENTION, attention_code=code[:60], attention_detail=detail[:300],
        updated_at=timezone.now())
    name = connection.institution_name or "Your bank"
    why = {"ITEM_LOGIN_REQUIRED": "needs you to sign in to it again",
           "PENDING_DISCONNECT": "will stop sharing data soon unless you reconnect",
           "PENDING_EXPIRATION": "will stop sharing data soon unless you reconnect"}.get(
        code, "has stopped updating")
    tell_owner(connection.tenant, title=f"{name}: reconnect the bank feed",
               text=f"{name} {why}. Open Settings, Finance, Bank connections and choose "
                    "Reconnect." + (f" The bank said: {detail}" if detail else ""),
               source_type=f"bank.attention.{timezone.localdate():%Y-%m-%d}",
               source_id=connection.pk, url=f"/settings/finance?reconnect={connection.pk}",
               only=_owner_only(connection))


def _owner_only(connection):
    """Who hears about a connection: a personal one's owner only."""
    if connection.side == BankConnection.Side.PERSONAL and connection.ledger_id:
        from apps.personal.models import PersonalLedger

        return PersonalLedger.objects.filter(pk=connection.ledger_id).values_list(
            "owner_id", flat=True).first()
    return None


def personal_ledger(tenant, actor):
    """The owner's own ledger, for a personal connection: only in a practice
    with Personal finance switched on."""
    from apps.personal import services as personal
    from apps.tenancy import modules

    if not modules.has(tenant, modules.PERSONAL):
        raise FinanceError("Personal finance is not switched on in this practice.", status=404)
    return personal.ledger_for(actor)


def repaired(connection) -> None:
    BankConnection.all_objects.filter(pk=connection.pk, status=S.NEEDS_ATTENTION).update(
        status=S.CONNECTED, attention_code="", attention_detail="", updated_at=timezone.now())


def failed(connection, exc) -> None:
    """A sync the provider refused. A login problem is the owner's to fix;
    anything else is kept as the last error and tried again next time."""
    BankConnection.all_objects.filter(pk=connection.pk).update(
        last_error=str(exc)[:300], updated_at=timezone.now())
    if exc.code in providers.LOGIN_CODES or exc.code in ("ITEM_LOCKED", "ITEM_NOT_SUPPORTED",
                                                          "INVALID_CREDENTIALS",
                                                          "INSUFFICIENT_CREDENTIALS",
                                                          "USER_SETUP_REQUIRED",
                                                          "ACCESS_NOT_GRANTED"):
        needs_attention(connection, exc.code, str(exc))


# ---------------------------------------------------------------- connecting

def link_token(tenant, *, actor, connection=None) -> dict:
    """A token for the provider's widget: a new connection, or (Reconnect) the
    update mode of this one."""
    _refuse_new()
    provider = providers.get(connection.provider if connection else providers.DEFAULT)
    try:
        token = provider.link_token(
            user_ref=f"{tenant.pk}:{actor.pk}", webhook_url=webhook_url(),
            access_token=token_of(connection) if connection is not None else "")
    except providers.ProviderError as exc:
        raise FinanceError(str(exc), status=502) from None
    return {"link_token": token, "update": connection is not None}


def connect(tenant, *, actor, public_token: str, side: str = "practice") -> BankConnection:
    _refuse_new()
    if side not in BankConnection.Side.values:
        raise FinanceError("side is practice or personal.")
    ledger = personal_ledger(tenant, actor) if side == BankConnection.Side.PERSONAL else None
    public_token = str(public_token or "").strip()
    if not public_token:
        raise FinanceError("The bank's sign-in did not finish. Try Connect a bank again.")
    provider = providers.get(providers.DEFAULT)
    try:
        linked = provider.exchange(public_token)
    except providers.ProviderError as exc:
        raise FinanceError(str(exc), status=502) from None
    with transaction.atomic():
        connection = BankConnection.all_objects.filter(
            provider=provider.name or providers.DEFAULT, item_id=linked.item_id).first()
        if connection is not None and connection.tenant_id != tenant.pk:
            raise FinanceError("That bank login is connected elsewhere.", status=409)
        if connection is not None and (connection.side, connection.ledger_id) != (
                side, ledger.pk if ledger else None):
            raise FinanceError("That bank login is already connected on the other side "
                               "(the practice's or personal). Disconnect it there first.",
                               status=409)
        connection = connection or BankConnection(
            tenant=tenant, provider=provider.name or providers.DEFAULT,
            item_id=linked.item_id, created_by=actor, side=side, ledger=ledger)
        connection.institution_id = linked.institution_id[:60]
        connection.institution_name = linked.institution_name[:160]
        connection.access_token_ciphertext = secrets.encrypt(linked.access_token)
        connection.status, connection.attention_code, connection.attention_detail = \
            S.CONNECTED, "", ""
        connection.disconnected_at = connection.disconnected_by = None
        connection.save()
        services.audit(tenant, "bank_connected", actor, connection,
                       institution=connection.institution_name, side=connection.side)
    try:
        from .sync import store_accounts

        store_accounts(connection, provider.accounts(linked.access_token))
    except providers.ProviderError as exc:
        failed(connection, exc)
    return connection


def reconnected(connection, *, actor) -> BankConnection:
    """Update mode finished in the browser: the login is repaired, and a sync
    picks up what was missed."""
    _refuse_demo()
    BankConnection.all_objects.filter(pk=connection.pk).update(
        status=S.CONNECTED, attention_code="", attention_detail="", updated_at=timezone.now())
    services.audit(connection.tenant, "bank_reconnected", actor, connection)
    connection.refresh_from_db()
    _sync_quietly(connection, actor=actor)
    connection.refresh_from_db()
    return connection


def _feed_from(account) -> object:
    """Lines already in the books are not brought in again: the feed begins
    the day after the newest entry the account has from anywhere else, and
    never inside a closed month."""
    newest = FinanceEntry.all_objects.filter(
        Q(account=account) | Q(to_account=account), tenant_id=account.tenant_id,
        removed_at__isnull=True).exclude(source=FinanceEntry.Source.BANK).aggregate(
            m=Max("on_date"))["m"]
    start = account.opening_on
    if newest is not None:
        start = max(start, newest + timedelta(days=1))
    locked = services.settings_for(account.tenant).locked_through
    if locked is not None:
        start = max(start, locked + timedelta(days=1))
    return start


def _personal_feed_from(account) -> object:
    """As `_feed_from`, in the household's ledger: the day after the newest
    line the account has from anywhere but the feed. (No months close there.)"""
    from apps.personal.models import PersonalLine

    newest = PersonalLine.objects.filter(account=account, removed_at__isnull=True).exclude(
        source=PersonalLine.Source.BANK).aggregate(m=Max("on_date"))["m"]
    start = account.opening_on
    if newest is not None:
        start = max(start, newest + timedelta(days=1))
    return start


def _target(connection, target_id):
    """The account a feed account is mapped to: one of the practice's ledger
    accounts, or (a personal connection) one of its owner's household ones."""
    if connection.side == BankConnection.Side.PERSONAL:
        from apps.personal.models import PersonalAccount

        found = PersonalAccount.objects.filter(
            ledger_id=connection.ledger_id, pk=target_id).first() \
            if _uuid(target_id) else None
        if found is None:
            raise FinanceError("That account is not one of your personal accounts.",
                               status=404)
        return found
    found = FinanceAccount.all_objects.filter(
        tenant=connection.tenant, pk=target_id).first() if _uuid(target_id) else None
    if found is None:
        raise FinanceError("That ledger account is not in this practice.", status=404)
    return found


def set_mapping(connection, *, actor, mapping: dict) -> BankConnection:
    """`{feed account id: ledger account id, or "" for not fed}`. An account
    whose feed has made entries keeps its ledger account; it can be stopped
    (not fed), and its entries stay. A personal connection's accounts map to
    its owner's household accounts, and only to those."""
    _refuse_demo()
    if connection.status == S.DISCONNECTED:
        raise FinanceError("This connection is disconnected.", status=409)
    personal = connection.side == BankConnection.Side.PERSONAL
    field = "personal_account" if personal else "finance_account"
    feeds = {str(f.pk): f for f in BankFeedAccount.all_objects.filter(connection=connection)}
    changed = False
    with transaction.atomic():
        for feed_id, target_id in (mapping or {}).items():
            feed = feeds.get(str(feed_id))
            if feed is None:
                raise FinanceError("That account is not under this connection.", status=404)
            target = None
            if target_id:
                target = _target(connection, target_id)
                if target.closed_at is not None:
                    raise FinanceError(f"“{target.name}” is closed.")
                taken = BankFeedAccount.all_objects.filter(
                    tenant=connection.tenant, **{field: target}).exclude(
                        pk=feed.pk).exclude(connection__status=S.DISCONNECTED).first()
                if taken is not None:
                    raise FinanceError(f"“{target.name}” is already fed by "
                                       f"{taken.name or 'another account'}.", status=409)
            current = getattr(feed, field + "_id")
            if (target.pk if target else None) == current and feed.skipped == (target is None):
                continue
            if current and target is not None and \
                    BankFeedTransaction.all_objects.filter(feed_account=feed).exists():
                raise FinanceError(f"{feed.name} has already fed {getattr(feed, field).name}. "
                                   "Stop feeding it first; its entries stay.", status=409)
            was_fed = current is not None
            setattr(feed, field, target)
            feed.skipped = target is None
            if target is not None:
                feed.feed_from = _personal_feed_from(target) if personal else _feed_from(target)
            feed.save()
            if target is not None and not was_fed:
                # Lines the cursor passed while this account was not fed are
                # read again from the beginning; the ones already known are
                # recognized by the bank's id and not entered twice.
                changed = True
            services.audit(connection.tenant, "bank_account_mapped", actor, feed,
                           ledger=target.name if target else "", side=connection.side,
                           feed_from=str(feed.feed_from))
        if changed:
            BankConnection.all_objects.filter(pk=connection.pk).update(
                cursor="", updated_at=timezone.now())
    connection.refresh_from_db()
    _sync_quietly(connection, actor=actor)
    connection.refresh_from_db()
    return connection


def _uuid(value) -> bool:
    import uuid

    try:
        uuid.UUID(str(value))
    except ValueError:
        return False
    return True


def _sync_quietly(connection, *, actor=None) -> None:
    from .sync import SyncRefused, run

    try:
        run(connection, actor=actor)
    except (SyncRefused, providers.ProviderError) as exc:
        log.info("bank sync after a change did not run: %s", type(exc).__name__)


def check_now(connection, *, actor) -> dict:
    from .sync import SyncRefused, run

    _refuse_demo()
    if connection.status == S.DISCONNECTED:
        raise FinanceError("This connection is disconnected.", status=409)
    now = timezone.now()
    if connection.last_checked_at and now - connection.last_checked_at < CHECK_EVERY:
        wait = connection.last_checked_at + CHECK_EVERY - now
        minutes = max(1, int(wait.total_seconds() // 60) + 1)
        raise FinanceError(f"Checked within the hour. Check again in {minutes} minute"
                           f"{'' if minutes == 1 else 's'}; it also checks every night "
                           "and whenever the bank says there is something new.", status=429)
    BankConnection.all_objects.filter(pk=connection.pk).update(last_checked_at=now)
    try:
        return run(connection, actor=actor)
    except SyncRefused as exc:
        raise FinanceError(str(exc), status=409) from None
    except providers.ProviderError as exc:
        raise FinanceError(str(exc), status=502) from None


def disconnect(connection, *, actor) -> BankConnection:
    """Removed at the provider, polling stops, the entries stay."""
    _refuse_demo()
    token = token_of(connection)
    if token:
        try:
            providers.get(connection.provider).remove(token)
        except providers.ProviderError as exc:
            # Gone at the provider already, or not reachable: the connection
            # ends here either way, and its key is destroyed.
            log.info("bank item removal: %s", exc.code or "error")
    BankConnection.all_objects.filter(pk=connection.pk).update(
        status=S.DISCONNECTED, access_token_ciphertext=None, cursor="",
        disconnected_at=timezone.now(), disconnected_by=actor, updated_at=timezone.now())
    services.audit(connection.tenant, "bank_disconnected", actor, connection,
                   institution=connection.institution_name)
    connection.refresh_from_db()
    return connection


# ----------------------------------------------------------------- webhooks

def webhook(event) -> str:
    """What a verified webhook does. Returns what happened, for the log."""
    connection = BankConnection.all_objects.filter(item_id=event.item_id).exclude(
        status=S.DISCONNECTED).first() if event.item_id else None
    if connection is None:
        return "unknown item"
    if event.kind == "sync":
        queue_sync(connection)
        return "sync queued"
    if event.kind == "attention":
        needs_attention(connection, event.code, event.detail)
        return "needs attention"
    if event.kind == "repaired":
        repaired(connection)
        return "repaired"
    return "ignored"


def queue_sync(connection) -> None:
    from django_q.tasks import async_task

    async_task("apps.finance.tasks.sync_bank_connection", str(connection.tenant_id),
               str(connection.pk))


# ------------------------------------------------------------- representing

def represent(connection) -> dict:
    feeds = list(BankFeedAccount.all_objects.filter(connection=connection)
                 .select_related("finance_account", "personal_account"))
    return {
        "id": str(connection.pk), "provider": connection.provider, "side": connection.side,
        "institution": connection.institution_name or "Your bank",
        "status": connection.status, "status_label": connection.get_status_display(),
        "attention_code": connection.attention_code,
        "attention_detail": connection.attention_detail,
        "reconnect": connection.status == S.NEEDS_ATTENTION,
        "last_synced_at": connection.last_synced_at.isoformat()
        if connection.last_synced_at else None,
        "last_checked_at": connection.last_checked_at.isoformat()
        if connection.last_checked_at else None,
        "can_check_at": (connection.last_checked_at + CHECK_EVERY).isoformat()
        if connection.last_checked_at else None,
        "last_sync_counts": connection.last_sync_counts or {},
        "last_error": connection.last_error,
        "waiting": sum(1 for f in feeds if f.finance_account_id is None
                       and f.personal_account_id is None and not f.skipped),
        "accounts": [{
            "id": str(f.pk), "name": f.name, "official_name": f.official_name,
            "mask": f.mask, "type": f.type, "subtype": f.subtype,
            "finance_account": ({"id": str(f.finance_account_id),
                                 "name": f.finance_account.name}
                                if f.finance_account_id else None),
            "personal_account": ({"id": str(f.personal_account_id),
                                  "name": f.personal_account.name}
                                 if f.personal_account_id else None),
            "skipped": f.skipped,
            "feed_from": f.feed_from.isoformat() if f.feed_from else None,
            "balance_cents": f.balance_cents, "available_cents": f.available_cents,
            "currency": f.currency,
            "balance_at": f.balance_at.isoformat() if f.balance_at else None,
        } for f in feeds],
        "created_at": connection.created_at.isoformat(),
        "disconnected_at": connection.disconnected_at.isoformat()
        if connection.disconnected_at else None,
    }


def overview(tenant, user=None) -> dict:
    """The practice's connections, and the viewer's own personal ones under
    their own heading. The plan's count covers both sides together."""
    from config import environment

    from apps.tenancy import modules

    rows = list(BankConnection.all_objects.filter(
        tenant=tenant, side=BankConnection.Side.PRACTICE).order_by("status", "created_at"))
    personal_on = modules.has(tenant, modules.PERSONAL)
    mine = list(BankConnection.all_objects.filter(
        tenant=tenant, side=BankConnection.Side.PERSONAL,
        ledger__owner=user).order_by("status", "created_at")) \
        if personal_on and user is not None else []
    return {
        "personal_on": personal_on,
        "personal": [represent(c) for c in mine if c.status != S.DISCONNECTED],
        "personal_disconnected": [represent(c) for c in mine if c.status == S.DISCONNECTED],
        "available": available(), "configured": providers.configured(),
        "demo": environment.is_demo(),
        "refusal": DEMO_REFUSAL if environment.is_demo()
        else ("" if providers.configured() else NOT_SET_UP),
        "connections": [represent(c) for c in rows if c.status != S.DISCONNECTED],
        "disconnected": [represent(c) for c in rows if c.status == S.DISCONNECTED],
        "count": count(tenant), "included": INCLUDED, "each_after_cents": EACH_AFTER_CENTS,
        "price_line": PRICE_LINE,
    }


def balances(tenant) -> dict:
    """`{ledger account id: {"cents", "at"}}` from the feeds of live
    connections, for the forecast's cash today and Reconcile."""
    out = {}
    for feed in BankFeedAccount.all_objects.filter(
            tenant=tenant, finance_account__isnull=False, balance_cents__isnull=False,
            balance_at__isnull=False).exclude(connection__status=S.DISCONNECTED):
        out[feed.finance_account_id] = {"cents": feed.balance_cents, "at": feed.balance_at}
    return out
