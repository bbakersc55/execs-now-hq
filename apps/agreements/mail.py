"""Email about owner agreements.

**To owners**, by the company's chosen sender (owner, 2026-11-23):

- "ENHQ's own sender (testing)": the practice's own outbound mail, through the
  Outbox (producer `owner_agreement`). Owners would see Executives Now: the
  settings say so.
- "Our own domain": Postmark, from an address on a domain we control, replies
  to the reply-to address. It can be chosen only once a domain is set and
  "Send a test to me" has worked.

If sending fails, owner emails pause (each one waiting is kept, `held`) and
the people with the agreements tick and the practice owner are told. Nothing
ever falls back to another sender. Both go through the Outbox, as every email
does (tests/test_mail_paths.py). The owner's link is put in at delivery and
never stored. No real email leaves a laptop: the two producers are never real
there, whatever the allow-list says.

**To staff**: in the app, and by email from ENHQ (producer
`owner_agreement_notice`, ENHQ's internal layout).
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone
from django.utils.html import escape

from . import access, postmark, render
from .models import OwnerEmail, Program

log = logging.getLogger(__name__)

OWNER_KINDS = ("invite", "reminder", "owner_copy", "final_copy", "intake_link",
               "intake_reminder", "withdrawn")
#: Sent once to each address, however many owners share it (owner, 2026-11-24).
COPY_KINDS = ("owner_copy", "final_copy", "withdrawn")


def real_sending() -> bool:
    """Postmark is called only from production."""
    return getattr(settings, "APP_ENVIRONMENT", "local") == "production" and not settings.IS_LOCAL


def _form(company):
    from apps.intake.services import form_for

    return form_for(company)


def _owner_address(agreement, position=1) -> str:
    if position != 1:
        from .models import CoOwner

        co = CoOwner.all_objects.filter(agreement=agreement, position=position).first()
        return co.email if co else ""
    return ((agreement.details or {}).get("email") or agreement.owner_email or "").strip()


def _first(agreement, position=1) -> str:
    if position != 1:
        from .models import CoOwner

        co = CoOwner.all_objects.filter(agreement=agreement, position=position).first()
        return (co.name.split(" ")[0] if co else "") or "there"
    first = (agreement.details or {}).get("first_name") or agreement.owner_name.split(" ")[0]
    return first or "there"


def _and(names) -> str:
    names = [n for n in names if n]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _property(agreement) -> str:
    from . import services

    return render.one_line(services.terms_for(agreement).get("property_address")) \
        or "your property"


# ------------------------------------------------------------ owner messages

def owner_message(agreement, kind: str, position: int = 1, greet=None) -> dict:
    """{subject, text, html, link, attachment}: the words for one owner email.
    `link` is that owner's own link, put in only at delivery. `greet` names
    everyone at one shared address, for a copy."""
    from apps.intake import links as intake_links

    from . import services

    form = _form(agreement.company)
    brand = form.brand_name
    first = _and(greet) if greet else _first(agreement, position)
    prop = _property(agreement)
    link, button, attachment = "", "", None
    everyone = services.owners(agreement)
    later = [o["name"] for o in everyone if o["position"] > position]
    if kind == "invite" and position != 1:
        link, button = services.owner_link(agreement, position), "Read and sign the agreement"
        before = _and([o["name"] for o in everyone if o["position"] < position])
        subject = f"Your rental management agreement with {brand}"
        paras = [f"Hi {first},",
                 f"{before} signed the rental management agreement for {prop}. As an owner, "
                 "you sign it too, and it's your turn now. It takes about ten minutes, and works "
                 "well on a phone."]
        paras.append((f"After you, {_and(later)} signs. " if later else "")
                     + "Once every owner has signed, we'll countersign it and email you the "
                     "final copy.")
    elif kind == "invite":
        link, button = services.owner_link(agreement), "Read and sign the agreement"
        subject = f"Your rental management agreement with {brand}"
        paras = [f"Hi {first},",
                 f"Thank you for trusting your property to the care of the {brand} team. Your "
                 "rental management agreement is ready to read and sign. It takes about ten "
                 "minutes, and works well on a phone."]
        if later:
            paras.append(f"After you sign, {_and(later)} sign it too, in that order, each on "
                         "their own link. Then we'll countersign it and email you the final "
                         "copy, and you can start telling us about your property.")
        else:
            paras.append("After you sign, we'll countersign it and email you the final copy, and "
                         "you can start telling us about your property.")
    elif kind == "reminder":
        link, button = services.owner_link(agreement, position), "Read and sign the agreement"
        subject = f"Reminder: your rental management agreement with {brand}"
        paras = [f"Hi {first},",
                 f"Your rental management agreement with {brand} is waiting for your "
                 "signature. It takes about ten minutes."]
    elif kind == "owner_copy":
        subject = f"Your signed agreement with {brand} (awaiting our signature)"
        paras = [f"Hi {first},",
                 (f"Thank you for signing your rental management agreement for {prop}. "
                  if len(everyone) == 1 else
                  f"Every owner has now signed the rental management agreement for {prop}. "
                  "Thank you. ")
                 + f"Your copy is attached. It shows as awaiting {brand}'s signature until we "
                 "countersign it; we'll email you the final copy then."]
        attachment = (agreement.owner_pdf, f"{_filename(agreement)} (awaiting signature).pdf")
    elif kind == "final_copy":
        subject = f"Your rental management agreement with {brand} is complete"
        paras = [f"Hi {first},",
                 f"Your rental management agreement for {prop} is now signed by you and by "
                 f"{brand}. The final copy is attached; please keep it for your records."]
        attachment = (agreement.final_pdf, f"{_filename(agreement)}.pdf")
    elif kind == "withdrawn":
        # Owner, 2026-11-24: to every owner who already signed; nobody else.
        subject = f"Your rental management agreement with {brand} was withdrawn"
        paras = [f"Hi {first},",
                 f"The rental management agreement for {prop} that you signed has been "
                 "withdrawn. It won't take effect, and there's nothing you need to do.",
                 f"{brand} will be in touch with you about what happens next."]
    elif kind in ("intake_link", "intake_reminder"):
        link = intake_links.url_for(agreement.submission)
        button = "Tell us about your property"
        if kind == "intake_link":
            subject = f"Next step: tell {brand} about your property"
            paras = [f"Hi {first},",
                     f"Here's your link to tell us about {prop}. Your answers save as you go, "
                     "and the same link brings you back."]
        else:
            subject = f"Reminder: tell {brand} about your property"
            paras = [f"Hi {first},",
                     f"A reminder to finish telling us about {prop}. Your answers so far are "
                     "saved."]
    else:
        raise ValueError(kind)
    contact = " · ".join(x for x in (form.contact_phone, form.contact_email) if x)
    sign_off = [f"Thank you,\n{brand}"] + ([contact] if contact else [])
    return {"subject": subject, "paras": paras, "link": link, "button": button,
            "sign_off": sign_off, "attachment": attachment, "form": form}


def _filename(agreement) -> str:
    return f"Rental Management Agreement #{agreement.number}"


def _text(msg, link: str) -> str:
    lines = list(msg["paras"])
    if link:
        lines.append(f"{msg['button']}: {link}")
    return "\n\n".join(lines + msg["sign_off"])


def _html(msg, link: str) -> str:
    form = msg["form"]
    colors = {"primary": "#428227", "heading": "#36424A", "text": "#4A4A4A",
              "background": "#FAF9F5", **(form.colors or {})}
    paras = "".join(f'<p style="margin:0 0 14px">{escape(p)}</p>' for p in msg["paras"])
    button = (f'<p style="margin:22px 0"><a href="{escape(link)}" style="background:'
              f'{colors["primary"]};color:#ffffff;padding:13px 22px;border-radius:10px;'
              f'text-decoration:none;font-weight:700;display:inline-block">'
              f'{escape(msg["button"])}</a></p>') if link else ""
    sign = "".join(f'<p style="margin:0 0 6px">{escape(p).replace(chr(10), "<br>")}</p>'
                   for p in msg["sign_off"])
    return (f'<div style="background:{colors["background"]};padding:24px 12px;font-family:'
            f'Montserrat,Arial,Helvetica,sans-serif;color:{colors["text"]};font-size:16px;'
            f'line-height:1.5"><div style="max-width:560px;margin:0 auto;background:#ffffff;'
            f'border-radius:14px;padding:28px 24px"><div style="font-weight:800;font-size:'
            f'20px;color:{colors["heading"]};margin:0 0 18px">{escape(form.brand_name)}</div>'
            f"{paras}{button}{sign}</div></div>")


def to_owner(agreement, kind: str, *, to: str = "", position: int = 1, greet=None):
    """Send one owner email by the company's sender, or hold it while sending
    is paused. Returns the OwnerEmail row."""
    from . import services

    program = services.program_for(agreement.company, create=True)
    to = to or _owner_address(agreement, position)
    if not to:
        return None
    msg = owner_message(agreement, kind, position, greet=greet)
    row = OwnerEmail.all_objects.create(
        tenant_id=agreement.tenant_id, company=agreement.company, agreement=agreement,
        kind=kind, position=position, to_address=to, subject=msg["subject"][:300],
        sender=program.sender, state=OwnerEmail.State.HELD)
    if program.paused_at is not None:
        services._event(agreement, "email_held",
                        detail=f"Held while owner emails are paused: {msg['subject']}")
        return row
    return _deliver(program, agreement, row, msg)


def to_owners(agreement, kind: str, positions=None):
    """A copy (or the withdrawn notice) to every owner, or to `positions`:
    once to each address, greeting everyone who shares it."""
    from . import services

    by_address = {}
    for o in services.owners(agreement):
        if positions is not None and o["position"] not in positions:
            continue
        address = (o["email"] or "").strip().lower()
        if address:
            by_address.setdefault(address, []).append(o)
    rows = []
    for address, people in by_address.items():
        greet = [p["name"].split(" ")[0] for p in people] if len(people) > 1 else None
        rows.append(to_owner(agreement, kind, to=address, position=people[0]["position"],
                             greet=greet))
    return rows


def _deliver(program, agreement, row, msg):
    from . import services

    link = msg["link"]
    attachments = []
    if msg["attachment"] and msg["attachment"][0] is not None:
        attachments = [msg["attachment"]]
    try:
        if program.sender == Program.Sender.DOMAIN:
            _by_domain(program, agreement, row, msg, link, attachments)
        else:
            _by_testing_sender(agreement, row, msg, link, attachments)
    except Exception as exc:                                       # noqa: BLE001
        recipient_only = bool(getattr(exc, "recipient_only", False))
        row.error = str(exc)[:300]
        row.state = OwnerEmail.State.FAILED if recipient_only else OwnerEmail.State.HELD
        row.save(update_fields=["error", "state"])
        services._event(agreement, "email_failed",
                        detail=f"{msg['subject']}: not sent. {exc}"[:300])
        if recipient_only:
            tell_staff_failed(agreement, str(exc))
        else:
            pause(program, str(exc))
        return row
    services._event(agreement, "email_" + row.state,
                    detail=f"{msg['subject']} ({'sent' if row.state == 'sent' else 'kept on '
                                                 'this computer, not sent'})")
    return row


def _by_testing_sender(agreement, row, msg, link, attachments):
    """ENHQ's own sender: the practice's outbound mail, through the Outbox."""
    _through_outbox(agreement, row, msg, link, attachments, owner_domain=False)


def _by_domain(program, agreement, row, msg, link, attachments):
    """Our own domain: Postmark, through the Outbox like every email (the
    Outbox keeps it on a laptop), white label, never another sender."""
    if not (program.sender_domain and program.from_address):
        raise postmark.PostmarkError("Our own domain isn't set up: set the domain and the "
                                     "from-address in the agreement settings.")
    _through_outbox(agreement, row, msg, link, attachments, owner_domain=True,
                    from_address=program.from_address)


def _through_outbox(agreement, row, msg, link, attachments, *, owner_domain, from_address=None):
    """The link is only in what is delivered, never on the stored row."""
    from apps.crm.models import OutboxMessage
    from apps.crm.services import outbox

    files = [(f, name) for f, name in attachments]
    message = outbox.create_message(
        tenant=agreement.company.tenant, producer=OutboxMessage.Producer.OWNER_AGREEMENT,
        to_address=row.to_address, subject=row.subject,
        body_text=_text(msg, "[the owner's link, put in when sent]" if link else ""),
        body_html=_html(msg, ""), deliver_body_text=_text(msg, link),
        deliver_body_html=_html(msg, link), attachments=files,
        from_address=from_address,
        sent_via=postmark.OWNER_DOMAIN if owner_domain else "postmark",
        source_type="owner_agreement", source_id=agreement.pk)
    row.state = (OwnerEmail.State.SENT if (owner_domain and real_sending()) or
                 (not owner_domain and not settings.IS_LOCAL) else OwnerEmail.State.CAPTURED)
    row.provider_id = message.provider_message_id or str(message.pk)
    row.sent_at = timezone.now()
    row.save(update_fields=["state", "provider_id", "sent_at"])


# ------------------------------------------------------------ pausing

def pause(program, reason: str):
    if program.paused_at is None:
        program.paused_at = timezone.now()
        program.pause_reason = reason[:300]
        program.save(update_fields=["paused_at", "pause_reason"])
        tell_paused(program)


def resume(program, actor):
    """Staff resume owner emails: the ones held go out, oldest first."""
    from . import services

    if program.paused_at is None:
        return 0
    program.paused_at, program.pause_reason = None, ""
    program.save(update_fields=["paused_at", "pause_reason"])
    sent = 0
    for row in OwnerEmail.all_objects.filter(company=program.company,
                                             state=OwnerEmail.State.HELD).order_by("created_at"):
        program.refresh_from_db()
        if program.paused_at is not None:
            break
        if row.agreement is None or row.kind not in OWNER_KINDS:
            continue
        row.sender = program.sender
        row.error = ""
        row.save(update_fields=["sender", "error"])
        _deliver(program, row.agreement, row, owner_message(row.agreement, row.kind,
                                                            row.position))
        sent += 1
    services._audit(program.company, actor, "agreements.emails_resumed", {"sent": sent})
    return sent


def send_test(program, user) -> str:
    """"Send a test to me" by our own domain, through the Outbox. Records that
    it worked, for this domain and from-address, only from production: on any
    other machine the Outbox keeps the test here and it proves nothing."""
    from apps.crm.models import OutboxMessage
    from apps.crm.services import outbox
    from apps.crm.services.transport import TransportUnavailable

    from . import services

    if not (program.sender_domain and program.from_address):
        raise services.Refused("Set the domain and the from-address first.")
    if not program.from_address.lower().endswith("@" + program.sender_domain.lower()):
        raise services.Refused("The from-address must be on the domain.")
    if not user.email:
        raise services.Refused("Your account has no email to send the test to.")
    form = _form(program.company)
    subject = f"Test from {form.brand_name}'s owner emails"
    text = (f"This is a test of owner email from {program.from_address}. Replies go to "
            f"{program.reply_to or program.from_address}.")
    try:
        outbox.create_message(
            tenant=program.company.tenant, producer=OutboxMessage.Producer.OWNER_AGREEMENT,
            to_address=user.email, subject=subject, body_text=text,
            body_html=f"<p>{escape(text)}</p>", from_address=program.from_address,
            sent_via=postmark.OWNER_DOMAIN, source_type="owner_agreement_program",
            source_id=program.pk)
    except TransportUnavailable as exc:
        raise services.Refused(str(exc)) from None
    if not real_sending():
        return ("Kept on this computer: a test here proves nothing. Send the test from "
                "production to prove the domain.")
    program.tested_at = timezone.now()
    program.tested_for = tested_key(program)
    program.save(update_fields=["tested_at", "tested_for"])
    return f"Sent to {user.email}. Our own domain can now be chosen."


def tested_key(program) -> str:
    return f"{program.sender_domain.lower()}|{program.from_address.lower()}"


def domain_ready(program) -> bool:
    return bool(program.sender_domain and program.from_address and program.tested_at
                and program.tested_for == tested_key(program))


# ------------------------------------------------------------ staff

def _app_url(path: str) -> str:
    base = settings.APP_ROOT_URL if settings.IS_LOCAL else settings.PUBLIC_BASE_URL
    return f"{base.rstrip('/')}{path}"


def to_staff(agreement, users, *, title, text, source_type, attach=None, attach_to=()):
    """In the app for each of `users`, and by email; `attach` (a stored PDF and
    its name) goes only to those in `attach_to`."""
    from apps.crm.models import OutboxMessage
    from apps.crm.services import email_layout, outbox
    from apps.notify.models import Kind
    from apps.notify.service import tell

    path = f"/agreements/{agreement.pk}"
    pdf_ids = {u.pk for u in attach_to}
    seen = set()
    for user in list(users) + [u for u in attach_to if u not in users]:
        if user.pk in seen:
            continue
        seen.add(user.pk)
        tell(tenant_id=agreement.tenant_id, recipient_id=user.pk, kind=Kind.AGREEMENT,
             title=title, text=text, url=path, source_type=source_type,
             source_id=agreement.pk)
        if not user.email:
            continue
        link = _app_url(path)
        files = [attach] if attach and attach[0] is not None and user.pk in pdf_ids else []
        try:
            outbox.create_message(
                tenant=agreement.company.tenant,
                producer=OutboxMessage.Producer.OWNER_AGREEMENT_NOTICE,
                to_address=user.email, subject=title,
                body_text=f"{text}\n\nOpen it in the app: {link}",
                body_html=email_layout.document(
                    agreement.company.tenant, subject=title, preheader=text[:140],
                    internal=True,
                    content_html=(f"<p>{escape(text)}</p><p><a href=\"{escape(link)}\">Open it in "
                                  "the app</a></p>")),
                attachments=files, source_type="owner_agreement", source_id=agreement.pk)
        except Exception:                                          # noqa: BLE001
            log.exception("owner agreement notice to user %s not sent", user.pk)


def _who(agreement) -> str:
    from . import services

    d = agreement.details or {}
    name = " ".join(x for x in (d.get("first_name"), d.get("last_name")) if x) \
        or agreement.owner_name
    if d.get("owner_type") == "entity" and d.get("entity_name"):
        name = f"{d['entity_name']} ({name})"
    others = [c.name for c in services.co_owners(agreement)]
    return _and([name] + others) if others else name


def countersign_request(agreement, *, reminder=False):
    company = agreement.company
    reminders = len((agreement.reminders or {}).get("countersign", [])) + 1 if reminder else 0
    title = (f"{'Reminder: c' if reminder else 'C'}ountersign owner agreement #{agreement.number}"
             f": {_who(agreement)}, {_property(agreement)}")
    to_staff(agreement, access.countersigners(company), title=title,
             text=(f"{_who(agreement)} signed the rental management agreement for "
                   f"{_property(agreement)}. It needs SkyRun's signature."),
             source_type=f"agreement_countersign{'_r' + str(reminders) if reminder else ''}")


def owner_signed_notice(agreement, position):
    """The team, when one owner of several signs (owner, 2026-11-24). No PDF:
    the copy is made once every owner has signed."""
    from . import services

    company = agreement.company
    everyone = services.owners(agreement)
    me = services.owner_at(agreement, position)
    nxt = services.turn(agreement)
    to_staff(agreement, access.users_with(company, "agreements", practice_owner=True),
             title=f"Owner agreement #{agreement.number}: {me['name']} signed ({position} of "
                   f"{len(everyone)}), {_property(agreement)}",
             text=(f"{me['name']} signed the rental management agreement for "
                   f"{_property(agreement)}."
                   + (f" Next to sign: {services.owner_at(agreement, nxt)['name']}, emailed "
                      "their own link now." if nxt else "")),
             source_type=f"agreement_signed_{position}")


def signed_notice(agreement):
    """The team: every owner signed; the signed-PDF people get the copy
    awaiting SkyRun's signature."""
    from . import services

    company = agreement.company
    team = access.users_with(company, "agreements", practice_owner=True)
    n = len(services.owners(agreement))
    to_staff(agreement, team,
             title=(f"Owner agreement #{agreement.number} signed: " if n == 1 else
                    f"Owner agreement #{agreement.number} signed by all {n} owners: ")
             + f"{_who(agreement)}, {_property(agreement)}",
             text=(f"{_who(agreement)} signed the rental management agreement for "
                   f"{_property(agreement)}. It is waiting for SkyRun's signature."),
             source_type="agreement_signed",
             attach=(agreement.owner_pdf, f"{_filename(agreement)} (awaiting signature).pdf"),
             attach_to=access.users_with(company, "signed_pdfs"))


def final_notice(agreement):
    from . import services

    company = agreement.company
    to_staff(agreement, access.users_with(company, "agreements", practice_owner=True),
             title=f"Owner agreement #{agreement.number} countersigned: {_who(agreement)}, "
                   f"{_property(agreement)}",
             text=(f"The rental management agreement for {_property(agreement)} is signed by "
                   f"both sides, dated {agreement.agreement_date:%B} {agreement.agreement_date.day}"
                   f", {agreement.agreement_date.year}. The final copy went to the "
                   f"{'owners' if len(services.owners(agreement)) > 1 else 'owner'}."),
             source_type="agreement_countersigned",
             attach=(agreement.final_pdf, f"{_filename(agreement)}.pdf"),
             attach_to=access.users_with(company, "signed_pdfs"))


def tell_paused(program):
    from apps.notify.models import Kind
    from apps.notify.service import tell

    users = access.users_with(program.company, "agreements", practice_owner=True)
    title = "Owner emails are paused"
    text = (f"Sending to owners failed: {program.pause_reason} Nothing is sent to owners, and "
            "nothing goes out another way, until someone fixes it and presses Resume in the "
            "owner agreement settings.")
    for user in users:
        tell(tenant_id=program.tenant_id, recipient_id=user.pk, kind=Kind.AGREEMENT,
             title=title, text=text, url="/agreements",
             source_type=f"agreement_paused_{program.paused_at:%Y%m%d%H%M%S}",
             source_id=program.company_id)
    _staff_email(program, users, title, text)


def tell_staff_failed(agreement, reason):
    from apps.notify.models import Kind
    from apps.notify.service import tell

    users = access.users_with(agreement.company, "agreements", practice_owner=True)
    for user in users:
        tell(tenant_id=agreement.tenant_id, recipient_id=user.pk, kind=Kind.AGREEMENT,
             title=f"An email to owner #{agreement.number} wasn't sent",
             text=f"{reason} Check the owner's email address.",
             url=f"/agreements/{agreement.pk}",
             source_type=f"agreement_email_failed_{timezone.now():%Y%m%d%H%M%S}",
             source_id=agreement.pk)


def _staff_email(program, users, title, text):
    from apps.crm.models import OutboxMessage
    from apps.crm.services import email_layout, outbox

    for user in users:
        if not user.email:
            continue
        try:
            outbox.create_message(
                tenant=program.company.tenant,
                producer=OutboxMessage.Producer.OWNER_AGREEMENT_NOTICE, to_address=user.email,
                subject=title, body_text=text,
                body_html=email_layout.document(program.company.tenant, subject=title,
                                                preheader=text[:140], internal=True,
                                                content_html=f"<p>{escape(text)}</p>"),
                source_type="owner_agreement_program", source_id=program.pk)
        except Exception:                                          # noqa: BLE001
            log.exception("owner agreement paused notice to user %s not sent", user.pk)
