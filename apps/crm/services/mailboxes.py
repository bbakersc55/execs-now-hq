"""A practice's mailboxes (2026-10-28): someone's own, a shared address like
info@, a client's mailbox the practice runs.

**A mailbox is a row of `Mailbox`.** Someone's own mailbox is the Gmail (or
Microsoft 365) connection they made in Settings → Email, as before: its
credential, send-as check and read grant stay on that connection, and the
mailbox row says whose it is. A shared or a client's mailbox belongs to
nobody's connection, so its credential, send-as and grant are on the row.

**A practice with one connection works as it did.** Its connection becomes
a mailbox the first time anything asks (`ensure`); nothing picks a mailbox
unless someone sets a default or a From; the address a message goes from is
the one it always was (`sender.choose`), through the same connection.

**Disconnected stops both.** The row stays, so a thread still says which
mailbox it was, but nothing is sent through it and nothing is read from it
until it is connected again. A message already waiting on it is refused at
send, with the reason, rather than quietly sent from another mailbox; a
default that names it is passed over.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

#: How far back "File mail with contacts and companies" starts.
FILE_BACK_DAYS = 30
#: Messages filed per mailbox per run (every 15 minutes).
FILE_PER_RUN = 100

GMAIL_READ = "https://www.googleapis.com/auth/gmail.readonly"


class MailboxRefused(ValueError):
    pass


def _model():
    from apps.crm.models import Mailbox

    return Mailbox


def _off_mailboxes(tenant) -> bool:
    """The demo, and a demo visitor's copy, keep their one sending path."""
    from apps.tenancy.demo import visitors
    from config import environment

    return environment.is_demo() or visitors.is_copy(tenant)


# ---------------------------------------------------------------- the rows

def ensure(tenant) -> None:
    """Every practice owner's and associate's own connection, as a mailbox.
    Idempotent; a reconnected connection finds its old row by address."""
    from apps.crm.models import GmailConnection, MicrosoftConnection
    from apps.tenancy.models import Membership, Role

    Mailbox = _model()
    staff = set(Membership.all_objects.filter(
        tenant=tenant, role__in=[Role.FF, Role.CF], revoked_at__isnull=True,
    ).values_list("user_id", flat=True))
    for model, field, provider in ((GmailConnection, "gmail", Mailbox.Provider.GMAIL),
                                   (MicrosoftConnection, "microsoft",
                                    Mailbox.Provider.MICROSOFT)):
        for connection in model.all_objects.filter(tenant=tenant, user_id__in=staff) \
                .select_related("user").filter(mailbox__isnull=True):
            address = connection.email_address.strip().lower()
            row = Mailbox.all_objects.filter(tenant=tenant, provider=provider,
                                             email_address=address).first()
            if row is not None and row.kind != Mailbox.Kind.OWN:
                continue           # that address is a shared mailbox already
            name = (getattr(connection.user, "full_name", "") or "").strip()
            fields = {field: connection, "user": connection.user, "disconnected_at": None,
                      "label": row.label if row is not None and row.label
                      else (f"{name}'s own" if name else address)}
            if row is None:
                Mailbox.all_objects.create(tenant=tenant, provider=provider,
                                           kind=Mailbox.Kind.OWN, email_address=address,
                                           connected_by=connection.user, **fields)
            else:
                for key, value in fields.items():
                    setattr(row, key, value)
                row.save()


def of_tenant(tenant, *, connected_only=False):
    ensure(tenant)
    rows = _model().all_objects.filter(tenant=tenant).select_related(
        "gmail", "microsoft", "user", "client_company", "connected_by")
    if connected_only:
        return [m for m in rows.order_by("kind", "email_address") if is_connected(m)]
    return list(rows.order_by("disconnected_at", "kind", "email_address"))


def is_connected(mailbox) -> bool:
    return mailbox is not None and mailbox.connection is not None


def reads(mailbox) -> bool:
    """Holds the grant to read mail: replies, and the Mail tab's filing."""
    from apps.crm.services import microsoft_oauth

    connection = mailbox.connection if mailbox is not None else None
    if connection is None:
        return False
    scopes = connection.scopes or []
    if mailbox.provider == "microsoft":
        return microsoft_oauth.inbound_granted(scopes)
    return GMAIL_READ in scopes


def addresses(mailbox) -> list[str]:
    """What it may send as: its own address, and its send-as once checked."""
    connection = mailbox.connection
    if connection is None:
        return []
    out = [connection.email_address.lower()]
    if connection.send_as_address and connection.send_as_verified_at is not None \
            and connection.send_as_address.lower() not in out:
        out.append(connection.send_as_address.lower())
    return out


def address_of(mailbox) -> str:
    """The From it sends as by default: a shared or client mailbox's checked
    send-as, else its own address. Someone's own mailbox, its own address."""
    connection = mailbox.connection
    if connection is None:
        return mailbox.email_address
    if mailbox.kind != mailbox.Kind.OWN and connection.send_as_address \
            and connection.send_as_verified_at is not None:
        return connection.send_as_address.lower()
    return connection.email_address.lower()


def describe(mailbox) -> str:
    """"info@practice.com (shared)", for a From line."""
    kind = {"own": "", "shared": "shared", "client": "client's"}[mailbox.kind]
    name = mailbox.label or mailbox.email_address
    return f"{address_of(mailbox)} · {name}" + (f" ({kind})" if kind and not mailbox.label else "")


def of_connection(connection):
    if connection is None:
        return None
    Mailbox = _model()
    if isinstance(connection, Mailbox):
        return connection
    field = "microsoft" if connection.__class__.__name__ == "MicrosoftConnection" else "gmail"
    ensure(connection.tenant)
    return Mailbox.all_objects.filter(**{field: connection}).first()


def legacy_for(tenant, from_address=""):
    """The mailbox the practice's one-connection rules send `from_address`
    through: a person's own address through their own, anything else
    through the practice owner's. None when they would refuse."""
    from apps.crm.services import transport

    if _off_mailboxes(tenant):
        return None
    try:
        if transport.is_microsoft(tenant):
            from apps.crm.services import graph

            connection = graph.sending_connection_for(tenant, from_address)
        else:
            connection = transport.sending_connection_for(tenant, from_address)
    except transport.TransportUnavailable:
        return None
    return of_connection(connection)


def usable(tenant, mailbox_id):
    """A connected mailbox of this practice by id, or None."""
    import uuid

    try:
        uuid.UUID(str(mailbox_id))
    except (TypeError, ValueError):
        return None
    found = _model().all_objects.filter(tenant=tenant, pk=mailbox_id).select_related(
        "gmail", "microsoft").first()
    return found if is_connected(found) else None


# ------------------------------------------------------------ the defaults

def company_default(company):
    mailbox = getattr(company, "mail_from", None) if company is not None else None
    return mailbox if is_connected(mailbox) else None


def user_default(tenant, user):
    from apps.crm.models import MailPreference

    if user is None or not getattr(user, "pk", None):
        return None
    preference = MailPreference.all_objects.filter(tenant=tenant, user=user) \
        .select_related("default_mailbox").first()
    mailbox = preference.default_mailbox if preference is not None else None
    return mailbox if is_connected(mailbox) else None


def options(tenant, user=None) -> list[dict]:
    """Every From a person may pick: each connected mailbox, by address."""
    return [{"value": f"mailbox:{m.pk}", "mailbox": str(m.pk), "address": address_of(m),
             "label": m.label or m.get_kind_display()}
            for m in of_tenant(tenant, connected_only=True)]


# ---------------------------------------------------------- disconnecting

def disconnect(mailbox, *, actor) -> None:
    """Stops sending and reading at once. An own mailbox's connection goes
    with its stored token, as Settings → Email's own Disconnect does; a
    shared or client mailbox's token is wiped from its row."""
    from apps.tenancy.models import AuditEvent

    connection = mailbox.gmail or mailbox.microsoft
    if connection is not None:
        if connection.secret_id:
            connection.secret.delete()
        connection.delete()
    mailbox.refresh_from_db()
    mailbox.token_ciphertext = None
    mailbox.disconnected_at = timezone.now()
    mailbox.save(update_fields=["token_ciphertext", "disconnected_at", "updated_at"])
    AuditEvent.all_objects.create(
        tenant=mailbox.tenant, actor=actor, verb="mailbox.disconnected",
        target_type="mailbox", target_id=mailbox.pk,
        payload={"email_address": mailbox.email_address})


def disconnected_own(connection) -> None:
    """Settings → Email's own Disconnect deleted `connection`: its mailbox
    says so (called before the delete, which clears the link)."""
    mailbox = getattr(connection, "mailbox", None)
    if mailbox is not None:
        mailbox.disconnected_at = timezone.now()
        mailbox.save(update_fields=["disconnected_at", "updated_at"])


def file_start(mailbox) -> None:
    if mailbox.files_after is None:
        mailbox.files_after = timezone.now() - timedelta(days=FILE_BACK_DAYS)


# ------------------------------------------------------------- connecting

def store(tenant, *, actor, provider, email_address, refresh_token, scopes, kind, label="",
          company=None, files_mail=False, directory_id=""):
    """A shared or client mailbox, connected (or connected again). Its token
    goes on its own row: the person connecting keeps their own connection
    and its token untouched."""
    from apps.crm.services.secrets import encrypt
    from apps.tenancy.models import AuditEvent

    Mailbox = _model()
    address = (email_address or "").strip().lower()
    if kind not in (Mailbox.Kind.SHARED, Mailbox.Kind.CLIENT):
        raise MailboxRefused("Connect your own mailbox from Your connection above.")
    ensure(tenant)
    row = Mailbox.all_objects.filter(tenant=tenant, provider=provider,
                                     email_address=address).first()
    if row is not None and row.is_own and is_connected(row):
        whose = (getattr(row.user, "full_name", "") or "").strip() or "someone"
        raise MailboxRefused(f"{address} is already connected as {whose}'s own mailbox.")
    if row is None:
        row = Mailbox(tenant=tenant, provider=provider, email_address=address)
    row.kind, row.user, row.gmail, row.microsoft = kind, None, None, None
    row.label = (label or "").strip()[:80] or row.label or address
    row.client_company = company if kind == Mailbox.Kind.CLIENT else None
    row.token_ciphertext = encrypt(refresh_token)
    row.scopes, row.directory_id = list(scopes or []), (directory_id or "")[:64]
    row.send_as_address = row.send_as_address or address
    row.send_as_verified_at, row.send_as_error = None, ""
    row.connected_by, row.disconnected_at = actor, None
    row.files_mail = bool(files_mail)
    if row.files_mail:
        file_start(row)
    row.save()
    AuditEvent.all_objects.create(
        tenant=tenant, actor=actor, verb="mailbox.connected", target_type="mailbox",
        target_id=row.pk, payload={"email_address": address, "kind": kind})
    return row


def check_send_as(mailbox) -> str:
    """Runs the send-as check for a shared or client mailbox; "" when it
    passed, else what was wrong (also kept on the row)."""
    from apps.crm.services import transport

    connection = mailbox.connection
    if connection is None:
        return f"{mailbox.email_address} is disconnected."
    try:
        if mailbox.provider == "microsoft":
            from apps.crm.services import graph

            graph.verify_send_as(connection, connection.send_as_address or mailbox.email_address)
        else:
            transport.verify_send_as(connection,
                                     connection.send_as_address or mailbox.email_address)
    except transport.TransportUnavailable as exc:
        return str(exc)
    return ""


def refusal(message) -> str:
    """Why `message` may not go out through its mailbox, or ""."""
    mailbox = message.mailbox
    if mailbox is None or is_connected(mailbox):
        return ""
    return (f"{mailbox.email_address} is disconnected, so this was not sent. Choose another "
            "From on it, or connect the mailbox again in Settings → Email.")


def for_address(tenant, address):
    """The mailbox a literal From goes through: a shared or client mailbox
    that sends as it, else the one-connection rules' (`legacy_for`)."""
    address = (address or "").strip().lower()
    if not address or _off_mailboxes(tenant):
        return None
    for mailbox in of_tenant(tenant, connected_only=True):
        if not mailbox.is_own and address in addresses(mailbox):
            return mailbox
    return legacy_for(tenant, address)
