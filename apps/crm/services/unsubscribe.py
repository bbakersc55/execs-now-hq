"""Email categories, the unsubscribe link, and suppression (owner, 2026-09-28).

**Every email the app sends has a category.**

- *marketing* — referral touches, campaigns, referral onboarding, and the
  outreach a stage rule or a one-off draft sends;
- *updates* — progress digests and client-activity notices;
- *transactional* — sign-in links, PIN resets, pre-call invites and questions,
  the strategy PDF, and the app's own notices to staff.

Marketing and updates carry an unsubscribe link; **transactional never does**
— a sign-in link someone could switch off is a sign-in they could lock
themselves out of. The link is signed, needs no login and does not expire,
and it leaves one category only: leaving marketing does not stop a client's
project updates. The Outbox refuses a suppressed category and says why.

The link is placed in one function, `apply`, which `email_layout.for_delivery`
calls for every message it renders — the send and every preview alike — so
what is previewed is what lands.
"""

from __future__ import annotations

import re

from django.conf import settings
from django.core import signing
from django.utils import timezone
from django.utils.html import escape

from apps.crm.models import EmailSuppression, OutboxMessage
from apps.tenancy.models import AuditEvent

P = OutboxMessage.Producer
MARKETING = EmailSuppression.Category.MARKETING
UPDATES = EmailSuppression.Category.UPDATES
TRANSACTIONAL = "transactional"
CATEGORIES = (MARKETING, UPDATES, TRANSACTIONAL)

#: The owner's list, plus the producers it does not name. Stage-rule and
#: one-off ("manual") drafts are outreach to contacts, so they are marketing
#: and carry the link; the app's notices to its own staff are transactional.
BY_PRODUCER = {
    P.REFERRAL_TOUCH: MARKETING,
    P.REFERRAL_ONBOARDING: MARKETING,
    P.STAGE_RULE: MARKETING,
    P.MANUAL: MARKETING,
    P.DIGEST: UPDATES,
    P.CLIENT_ACTIVITY: UPDATES,
    P.MAGIC_LINK: TRANSACTIONAL,
    P.NOTE_PIN_RESET: TRANSACTIONAL,
    P.PRECALL_INVITE: TRANSACTIONAL,
    P.PRECALL_QUESTIONS: TRANSACTIONAL,
    P.STRATEGY_PDF: TRANSACTIONAL,
    P.PRECALL_COMPLETE: TRANSACTIONAL,
    P.CADENCE_CHANGE: TRANSACTIONAL,
    P.INBOUND_FORWARD: TRANSACTIONAL,
}

LABELS = {MARKETING: "marketing emails", UPDATES: "progress updates"}

#: Where the link goes in a layout. Replaced by the link, or by nothing.
MARKER = "<!--enhq-unsubscribe-->"

_SALT = "enhq.unsubscribe.v1"


def category_for(producer) -> str:
    return BY_PRODUCER.get(producer, TRANSACTIONAL)


def category_of(message) -> str:
    return message.category or category_for(message.producer)


# ------------------------------------------------------------------ the token

def token_for(*, tenant_id, category, contact_id=None, address="") -> str:
    """Signed, not stored: the link carries who and which category, and the
    signature is what makes it trustworthy. Deliberately without an expiry —
    an unsubscribe link in a year-old email must still work."""
    return signing.dumps({"t": str(tenant_id), "k": category,
                          "c": str(contact_id) if contact_id else "",
                          "a": (address or "").strip().lower()},
                         salt=_SALT, compress=True)


def read_token(token) -> dict | None:
    try:
        data = signing.loads(token, salt=_SALT)
    except signing.BadSignature:
        return None
    if data.get("k") not in (MARKETING, UPDATES) or not data.get("t"):
        return None
    return data


def _root() -> str:
    root = settings.APP_ROOT_URL
    if not root.startswith("http"):
        root = settings.PUBLIC_BASE_URL.rstrip("/") + "/" + root.lstrip("/")
    return root.rstrip("/")


def url_for(message) -> str:
    """The message's unsubscribe link, or "" when it must not have one."""
    category = category_of(message)
    if category == TRANSACTIONAL:
        return ""
    if not message.to_contact_id and not message.to_address:
        return ""
    token = token_for(tenant_id=message.tenant_id, category=category,
                      contact_id=message.to_contact_id,
                      address="" if message.to_contact_id else message.to_address)
    return f"{_root()}/unsubscribe/{token}"


# ------------------------------------------------------------- the rendering

def apply(message, html: str, text: str, *, personal: bool) -> tuple[str, str]:
    """Put the link where the layout marked, for marketing and updates; take
    the marker out, and add nothing, for transactional."""
    url = url_for(message)
    if not url:
        return html.replace(MARKER, ""), text
    label = f"Unsubscribe from {LABELS[category_of(message)]}"
    muted, faint = "#6D6E71", "#939598"
    if personal:
        block = (f'<p style="margin:28px 0 0;font-size:12px;line-height:1.5;color:{faint};">'
                 f'<a href="{escape(url)}" style="color:{muted};text-decoration:underline;">'
                 f'{label}</a></p>')
    else:
        block = (f'<br><a href="{escape(url)}" style="color:{muted};'
                 f'text-decoration:underline;">{label}</a>')
    if url not in html:
        if MARKER in html:
            html = html.replace(MARKER, block, 1)
        else:
            # A document stored before the marker existed: still carries it.
            html = re.sub(r"</body>", block + "</body>", html, count=1) \
                if "</body>" in html else html + block
    html = html.replace(MARKER, "")
    if url not in (text or ""):
        text = f"{(text or '').rstrip()}\n\n—\n{label}: {url}"
    return html, text


# --------------------------------------------------------------- suppression

def suppression_for(message):
    """The open suppression that stops this message, if any."""
    category = category_of(message)
    if category == TRANSACTIONAL:
        return None
    rows = EmailSuppression.all_objects.filter(tenant_id=message.tenant_id,
                                               category=category, lifted_at__isnull=True)
    if message.to_contact_id:
        return rows.filter(contact_id=message.to_contact_id).first()
    return rows.filter(contact__isnull=True,
                       address=(message.to_address or "").lower()).first()


def refusal(message) -> str:
    """Why the Outbox will not send this, in words for the queue; "" if it will."""
    row = suppression_for(message)
    if row is None:
        return ""
    who = (f"{message.to_contact.first_name} {message.to_contact.last_name}".strip()
           if message.to_contact_id else message.to_address)
    return (f"Not sent: {who} unsubscribed from {LABELS[row.category]} on "
            f"{timezone.localdate(row.created_at):%Y-%m-%d}.")


def unsubscribe(data: dict, *, category=None, message_id=None) -> EmailSuppression:
    """The recipient leaves one category. Idempotent; audited every time.

    Leaving marketing also ends their marketing enrolments; leaving updates
    mutes their digests. Anything of that category still waiting for
    approval is marked suppressed, so it does not sit in the queue one click
    from being refused.
    """
    from apps.crm.models import Contact
    from apps.crm.services import enrollment

    category = category or data["k"]
    tenant_id = data["t"]
    contact = (Contact.all_objects.filter(tenant_id=tenant_id, pk=data["c"]).first()
               if data.get("c") else None)
    address = "" if contact else data.get("a", "")
    row = EmailSuppression.all_objects.filter(
        tenant_id=tenant_id, category=category, lifted_at__isnull=True,
        **({"contact": contact} if contact else {"contact__isnull": True, "address": address}),
    ).first()
    created = row is None
    if created:
        row = EmailSuppression.all_objects.create(
            tenant_id=tenant_id, contact=contact, address=address, category=category,
            outbox_message_id=message_id)
    # Waiting drafts first, so they read "suppressed" — the true reason —
    # rather than "withdrawn" by the unenrolment below.
    waiting = OutboxMessage.all_objects.filter(
        tenant_id=tenant_id, state__in=[OutboxMessage.State.DRAFT,
                                        OutboxMessage.State.PENDING_APPROVAL],
        **({"to_contact": contact} if contact else {"to_address__iexact": address}))
    held = [m.pk for m in waiting if category_of(m) == category]
    if held:
        OutboxMessage.all_objects.filter(pk__in=held).update(
            state=OutboxMessage.State.SUPPRESSED,
            warning=f"Suppressed: the recipient unsubscribed from {LABELS[category]}.",
            updated_at=timezone.now())
    if contact is not None and category == MARKETING:
        for program in enrollment.PROGRAMS.values:
            enrollment.unenroll(contact, program, actor=None,
                                reason="unsubscribed")
    if contact is not None and category == UPDATES:
        from apps.work.models import Stakeholder

        Stakeholder.all_objects.filter(tenant_id=tenant_id, contact=contact,
                                       is_muted=False).update(is_muted=True,
                                                              updated_at=timezone.now())
    AuditEvent.all_objects.create(
        tenant_id=tenant_id, verb="email.unsubscribed", target_type="email_suppression",
        target_id=row.pk,
        payload={"category": category, "contact": str(contact.pk) if contact else None,
                 "address": address, "already": not created,
                 "message": str(message_id) if message_id else None,
                 "held_drafts": [str(pk) for pk in held]})
    return row


def resubscribe(data: dict, *, category) -> bool:
    """The recipient's own undo, from the same page. Lifts the suppression;
    it does not re-enrol them in anything — that is the practice's to offer."""
    rows = EmailSuppression.all_objects.filter(
        tenant_id=data["t"], category=category, lifted_at__isnull=True,
        **({"contact_id": data["c"]} if data.get("c")
           else {"contact__isnull": True, "address": data.get("a", "")}))
    ids = list(rows.values_list("pk", flat=True))
    rows.update(lifted_at=timezone.now(), updated_at=timezone.now())
    for pk in ids:
        AuditEvent.all_objects.create(
            tenant_id=data["t"], verb="email.resubscribed",
            target_type="email_suppression", target_id=pk,
            payload={"category": category})
    return bool(ids)


def state_for(data: dict) -> dict:
    """What the unsubscribe page shows: which categories this person is out
    of, and the practice's name. Nothing else about them."""
    from apps.tenancy.models import Tenant

    tenant = Tenant.objects.filter(pk=data["t"]).first()
    rows = EmailSuppression.all_objects.filter(
        tenant_id=data["t"], lifted_at__isnull=True,
        **({"contact_id": data["c"]} if data.get("c")
           else {"contact__isnull": True, "address": data.get("a", "")}))
    out = set(rows.values_list("category", flat=True))
    return {
        "practice": (tenant.email_display_name or tenant.name) if tenant else "",
        "category": data["k"],
        "categories": [{"category": c, "label": LABELS[c], "unsubscribed": c in out}
                       for c in (MARKETING, UPDATES)],
    }
