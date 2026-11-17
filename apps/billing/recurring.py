"""Recurring invoices that bill automatically (2026-11-17, `docs/p4_billing.md` §14).

A recurring invoice is one of two kinds. **You send each invoice** writes a
draft on its day, as before (`services.run_schedules`). **Bill
automatically** is this module:

1. **The client owner agrees** in the portal to the terms in short plain
   words (what is billed and the total each time, the days, the start, the
   contract's end or "Month to month", how to stop and when billing ends
   then), with a card saved in the same flow. The agreement is kept as given,
   like the auto-pay consent. Until then nothing is billed, and the practice
   owner sees "Waiting for <client> to agree" and can email the link.
2. **The invoice makes itself** `lead_days` before each billing date (default
   3, 0 allowed), at the 5:00 job: numbered, its PDF stored, and emailed with
   no approval step, saying the amount and "will be charged to the card
   ending NNNN on <date>". With no usable card it still goes, with its pay
   link, and the owner is told.
3. **The card is charged on the billing date** at the 9:00 job (auto-pay's),
   and the receipt sent. A decline follows auto-pay's rule: once more on a
   later day, both sides told. Anything that stops a charge is recorded on
   the invoice and the owner is told (`autopay.passed_over`).
4. **Stopping.** The client gives notice in the portal: billing ends on the
   last day of the month after the month of notice (`timing.notice_end`), or
   the contract's end if later; every billing date up to it is billed. The
   client can withdraw their notice before then. The practice owner can bring
   the end earlier, or stop at once, never later; invoices already made for
   dates after the new end are voided. After the end it is **Ended**; billing
   again needs a new agreement, offered once the owner sends the link again.
5. **Changes** to the lines or price apply from the first billing date at
   least 7 days out that has no invoice yet, and the client is emailed. The
   days, the first date and the contract's end are fixed while an agreement
   is in force.

While the card processor is in Test Mode, "Run the next billing now" makes,
sends and charges the next invoice at once, so the path can be proved
without waiting for the clock. Cards only; a bank account is meant to be
another kind of `card` here later.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.html import escape

from apps.billing import card_payments, money, payment_accounts, services, timing
from apps.billing import gateway as gw
from apps.billing.models import (
    BillingAgreement, ClientInvoice, ClientInvoiceSchedule, PaymentAttempt,
)

log = logging.getLogger(__name__)
A = PaymentAttempt.Status
AUTO = ClientInvoiceSchedule.Mode.AUTO
S = ClientInvoice.Status

#: The words a client owner agrees to. A change of wording is a new version;
#: what each agreed to is kept on their agreement as they saw it.
WORDING_VERSION = "2026-11-17"
#: A change of lines or price applies from a billing date at least this far out.
CHANGE_NOTICE = timedelta(days=7)

WAITING, ACTIVE, ENDING, ENDED = "waiting", "active", "ending", "ended"


class BillingRefused(Exception):
    """Refused, with a sentence for whoever asked."""

    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def _date(day: date) -> str:
    return f"{day:%B} {day.day}, {day.year}"


# ---------------------------------------------------------------- reading

def in_force(schedule) -> BillingAgreement | None:
    return (BillingAgreement.all_objects.filter(schedule=schedule, ended_at__isnull=True)
            .select_related("agreed_by", "client_company").first())


def latest(schedule) -> BillingAgreement | None:
    return (BillingAgreement.all_objects.filter(schedule=schedule)
            .select_related("agreed_by").order_by("-agreed_at").first())


def total_of(lines) -> int:
    return sum(money.line_amount(Decimal(str(line["quantity"])), line["unit_price_cents"])
               for line in lines or [])


def lines_for(schedule, billing_date: date) -> list[dict]:
    if schedule.pending_lines and schedule.pending_from and billing_date >= schedule.pending_from:
        return schedule.pending_lines
    return schedule.lines


def starts_on(schedule, agreement) -> date:
    """Nothing is billed before the first billing date, nor before the day
    the client agreed."""
    agreed = timezone.localtime(agreement.agreed_at).date()
    return max(schedule.first_billing_on, agreed)


def ended(agreement, today: date) -> bool:
    return agreement.ended_at is not None or (agreement.ends_on is not None
                                              and agreement.ends_on < today)


def state_of(schedule, today: date | None = None) -> str:
    today = today or timezone.localdate()
    agreement = latest(schedule)
    if agreement is None:
        return WAITING
    if ended(agreement, today):
        if schedule.invited_at and agreement.ended_at and schedule.invited_at > agreement.ended_at:
            return WAITING
        return ENDED
    return ENDING if agreement.ends_on else ACTIVE


def can_agree(schedule, today: date | None = None) -> bool:
    return (schedule.mode == AUTO and schedule.is_active
            and state_of(schedule, today) == WAITING)


def _billed(schedule):
    return ClientInvoice.all_objects.filter(schedule=schedule, billing_date__isnull=False)


def next_billing_on(schedule, today: date | None = None) -> date | None:
    """The next billing date from today with no invoice yet, within the
    agreement (or, waiting, from the first billing date)."""
    today = today or timezone.localdate()
    agreement = in_force(schedule)
    start = max(today, schedule.first_billing_on)
    through = None
    if agreement is not None:
        if agreement.stopped_at:
            return None
        start = max(start, starts_on(schedule, agreement))
        through = agreement.ends_on
    elif state_of(schedule, today) == ENDED:
        return None
    done = set(_billed(schedule).filter(billing_date__gte=start)
               .values_list("billing_date", flat=True))
    for day in timing.dates(schedule, start, through or start + timing.HORIZON):
        if day not in done:
            return day
    return None


def last_charge_on(schedule, agreement, ends_on: date) -> date | None:
    return timing.last_date(schedule, starts_on(schedule, agreement), ends_on)


def owner_contact(tenant) -> tuple[str, str]:
    """The practice owner's name and email, for "for an exception, contact"."""
    from apps.tenancy.models import Membership, Role

    first = (Membership.all_objects.filter(tenant=tenant, role=Role.FF, revoked_at__isnull=True)
             .select_related("user").order_by("created_at").first())
    if first is None:
        return services.practice_name(tenant), ""
    return (first.user.full_name or first.user.email), first.user.email


# ------------------------------------------------------------- the words

def words(schedule, today: date | None = None) -> str:
    """What the client owner agrees to, in short plain words."""
    today = today or timezone.localdate()
    practice = services.practice_name(schedule.tenant)
    company = schedule.client_company.name
    lines = schedule.lines
    what = "; ".join(
        f"{line['description']} ({money.dollars(money.line_amount(Decimal(str(line['quantity'])), line['unit_price_cents']))})"
        for line in lines)
    start = timing.next_date(schedule, max(schedule.first_billing_on, today))
    lead = schedule.lead_days
    emailed = ("on its date" if lead == 0 else
               f"{lead} day{'' if lead == 1 else 's'} before its date")
    term = (f"Term ends {_date(schedule.term_ends_on)}, then month to month."
            if schedule.term_ends_on and schedule.term_ends_on >= today else "Month to month.")
    return "\n".join([
        f"I agree that {practice} bills {company} automatically, on these terms:",
        f"What is billed: {what}.",
        f"Total each time: {money.dollars(total_of(lines))}.",
        f"When: {timing.describe(schedule)}, starting {_date(start) if start else 'its first date'}.",
        term,
        f"How it is paid: each invoice is emailed {emailed} and charged to the card saved here "
        "on that date. If a charge fails, it is tried once more on a later day.",
        "How to stop: press Stop automatic billing here in the portal.",
        "When billing ends after you stop: every billing date through the last day of the "
        "next calendar month is billed (or through the term's end, if that is later), and "
        "nothing after.",
    ])


def words_key(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


# ------------------------------------------------------- the client's acts

def _refuse_acting() -> None:
    from apps.tenancy.context import get_acting

    if get_acting() is not None:
        raise BillingRefused("An agreement is the client's own: nothing is agreed or stopped "
                             "while acting as someone else.")


def _auto(schedule) -> None:
    if schedule.mode != AUTO:
        raise BillingRefused("This recurring invoice is sent by the practice, not billed "
                             "automatically.")


def agree(schedule, *, user, version, key, ip_address=None, user_agent="") -> BillingAgreement:
    """The client owner's agreement, with the card on file saved in the same
    flow. Kept as given: who, when, the exact words, their version, the
    address and the browser."""
    from apps.billing import autopay
    from apps.tenancy.models import AuditEvent

    _refuse_acting()
    _auto(schedule)
    today = timezone.localdate()
    # One whose last day has passed is ended before a new one is made.
    close_past(schedule.tenant, today)
    if not schedule.is_active or schedule.client_company.deleted_at is not None:
        raise BillingRefused("This recurring invoice is not being billed.")
    if not can_agree(schedule, today):
        if in_force(schedule) is not None:
            raise BillingRefused("You have already agreed to this.")
        raise BillingRefused(f"Ask {services.practice_name(schedule.tenant)} to send the link "
                             "again to agree to it anew.")
    if not payment_accounts.is_ready(schedule.tenant):
        raise BillingRefused(f"{services.practice_name(schedule.tenant)} cannot take cards yet.")
    card = autopay.card_on_file(schedule.client_company)
    if card is None:
        raise BillingRefused("Save a card first.")
    text = words(schedule, today)
    if version != WORDING_VERSION or key != words_key(text):
        raise BillingRefused("The terms have changed. Please read them again.")
    try:
        with transaction.atomic():
            row = BillingAgreement.all_objects.create(
                tenant=schedule.tenant, schedule=schedule,
                client_company=schedule.client_company, agreed_by=user,
                agreed_at=timezone.now(), wording=text, wording_version=WORDING_VERSION,
                ip_address=ip_address or None, user_agent=(user_agent or "")[:400], card=card)
    except IntegrityError:
        raise BillingRefused("You have already agreed to this.") from None
    AuditEvent.all_objects.create(
        tenant=schedule.tenant, actor=user, verb="billing.billing_agreed",
        target_type="client_invoice_schedule", target_id=schedule.pk,
        payload={"company": str(schedule.client_company_id), "version": WORDING_VERSION,
                 "card": card.last4})
    first = next_billing_on(schedule, today)
    _tell_owner(schedule, title=f"{schedule.client_company.name} agreed to automatic billing",
                text=(f"{user.full_name or user.email} agreed to bill "
                      f"{schedule.client_company.name} automatically, "
                      f"{timing.describe(schedule)}, "
                      f"{money.dollars(total_of(schedule.lines))} each time"
                      + (f", from {_date(first)}." if first else ".")),
                key=f"agreed:{row.pk}")
    return row


def stop_preview(schedule, today: date | None = None) -> dict:
    """What the client sees before confirming "Stop automatic billing"."""
    today = today or timezone.localdate()
    agreement = in_force(schedule)
    if agreement is None:
        raise BillingRefused("Automatic billing is not on for this.", 404)
    ends_on = agreement.ends_on or timing.notice_end(today, schedule.term_ends_on)
    last = last_charge_on(schedule, agreement, ends_on)
    name, email = owner_contact(schedule.tenant)
    contact = f"{name} ({email})" if email and email != name else name
    return {
        "ends_on": ends_on.isoformat(), "last_charge_on": last.isoformat() if last else None,
        "contact": contact,
        "text": " ".join([
            f"Billing continues through {_date(ends_on)}.",
            f"Your last charge will be on {_date(last)}." if last
            else "There will be no further charge.",
            f"For an exception, contact {contact}.",
        ]),
    }


def give_notice(schedule, *, user) -> BillingAgreement:
    _refuse_acting()
    _auto(schedule)
    today = timezone.localdate()
    with transaction.atomic():
        agreement = (BillingAgreement.all_objects.select_for_update()
                     .filter(schedule=schedule, ended_at__isnull=True).first())
        if agreement is None or ended(agreement, today):
            raise BillingRefused("Automatic billing is not on for this.", 404)
        if agreement.ends_on is not None:
            raise BillingRefused(f"Automatic billing already ends on {_date(agreement.ends_on)}.")
        preview = stop_preview(schedule, today)
        agreement.notice_given_at, agreement.notice_given_by = timezone.now(), user
        agreement.ends_on = date.fromisoformat(preview["ends_on"])
        agreement.ends_set_by, agreement.ends_set_at = BillingAgreement.SetBy.CLIENT, timezone.now()
        agreement.save()
        _audit(schedule, "billing_notice_given", user, ends_on=preview["ends_on"])
    company = schedule.client_company.name
    _tell_client(schedule, agreement, extra=[user.email],
                 subject=f"Automatic billing ends {_date(agreement.ends_on)}",
                 lines=[f"You asked to stop automatic billing for {company} with "
                        f"{services.practice_name(schedule.tenant)}.", preview["text"],
                        "You can withdraw this notice in the portal before then."])
    _tell_owner(schedule, title=f"{company} gave notice: billing ends "
                                f"{_date(agreement.ends_on)}",
                text=(f"{user.full_name or user.email} stopped automatic billing for {company}. "
                      + preview["text"].split(" For an exception")[0]),
                key=f"notice:{agreement.pk}:{agreement.notice_given_at:%Y%m%d%H%M%S}",
                email=True)
    return agreement


def withdraw_notice(schedule, *, user) -> BillingAgreement:
    _refuse_acting()
    _auto(schedule)
    today = timezone.localdate()
    with transaction.atomic():
        agreement = (BillingAgreement.all_objects.select_for_update()
                     .filter(schedule=schedule, ended_at__isnull=True).first())
        if agreement is None or ended(agreement, today) or agreement.ends_on is None:
            raise BillingRefused("There is no notice to withdraw.", 404)
        if agreement.ends_set_by != BillingAgreement.SetBy.CLIENT:
            name, email = owner_contact(schedule.tenant)
            raise BillingRefused(f"{services.practice_name(schedule.tenant)} set this end date. "
                                 f"For a change, contact {name}"
                                 + (f" ({email})." if email and email != name else "."))
        was = agreement.ends_on
        agreement.notice_given_at = agreement.notice_given_by = None
        agreement.ends_on, agreement.ends_set_by, agreement.ends_set_at = None, "", None
        agreement.save()
        _audit(schedule, "billing_notice_withdrawn", user, was=was.isoformat())
    company = schedule.client_company.name
    _tell_client(schedule, agreement, extra=[user.email],
                 subject="Automatic billing continues",
                 lines=[f"You withdrew your notice. Automatic billing for {company} continues "
                        f"as agreed, {timing.describe(schedule)}."])
    _tell_owner(schedule, title=f"{company} withdrew its notice",
                text=(f"{user.full_name or user.email} withdrew the notice to stop automatic "
                      f"billing for {company}. It would have ended {_date(was)}; it continues."),
                key=f"withdrawn:{agreement.pk}:{timezone.now():%Y%m%d%H%M%S}")
    return agreement


# ------------------------------------------------------ the owner's acts

def send_link(schedule, *, actor) -> int:
    """Email the client owner(s) the link to agree. Returns how many."""
    from apps.tenancy.models import Membership, Role

    _auto(schedule)
    if state_of(schedule) not in (WAITING, ENDED):
        raise BillingRefused(f"{schedule.client_company.name} has agreed already.")
    owners = [m.user for m in Membership.all_objects.filter(
        tenant=schedule.tenant, client_company=schedule.client_company, role=Role.FCC,
        revoked_at__isnull=True).select_related("user") if m.user.email]
    if not owners:
        raise BillingRefused(f"{schedule.client_company.name} has no client owner with portal "
                             "access yet. Give one access first, under the company's Portal "
                             "access.")
    ClientInvoiceSchedule.all_objects.filter(pk=schedule.pk).update(invited_at=timezone.now())
    schedule.refresh_from_db()
    practice = services.practice_name(schedule.tenant)
    url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/invoices"
    for user in owners:
        _client_mail(schedule, user.email,
                     f"{practice}: please review automatic billing",
                     [f"{practice} has set up automatic billing for "
                      f"{schedule.client_company.name}: "
                      f"{money.dollars(total_of(schedule.lines))} {timing.describe(schedule)}.",
                      f"Nothing is billed until you agree. To read the terms, save a card and "
                      f"agree, sign in to the portal and open Invoices: {url}"])
    _audit(schedule, "billing_link_sent", actor, to=", ".join(u.email for u in owners))
    return len(owners)


def set_end(schedule, *, actor, ends_on: date | None = None, at_once: bool = False
            ) -> BillingAgreement:
    """The practice owner brings the end earlier (never later), or stops at
    once. Invoices already made for dates after the end are voided; the
    client is emailed the new date."""
    _auto(schedule)
    today = timezone.localdate()
    voided = []
    with transaction.atomic():
        agreement = (BillingAgreement.all_objects.select_for_update()
                     .filter(schedule=schedule, ended_at__isnull=True).first())
        if agreement is None or ended(agreement, today):
            raise BillingRefused("Automatic billing is not on for this.", 404)
        was = agreement.ends_on
        if at_once:
            new = today
        else:
            if ends_on is None:
                raise BillingRefused("Choose the last day to bill.", 400)
            if ends_on < today:
                raise BillingRefused("The end can't be in the past. To stop now, choose Stop now.",
                                     400)
            if was is not None and ends_on >= was:
                raise BillingRefused(f"Billing already ends {_date(was)}. The end can be moved "
                                     "earlier, never later.", 400)
            new = ends_on
        agreement.ends_on, agreement.ends_set_by = new, BillingAgreement.SetBy.OWNER
        agreement.ends_set_at = timezone.now()
        if at_once:
            agreement.stopped_at, agreement.stopped_by = timezone.now(), actor
            agreement.ended_at = timezone.now()
        agreement.save()
        after = today if at_once else new
        for invoice in (ClientInvoice.all_objects.select_for_update()
                        .filter(billing_agreement=agreement, billing_date__gt=after,
                                paid_cents=0).exclude(status=S.VOID)):
            if invoice.number:
                services.void(invoice, actor=actor,
                              reason=f"Automatic billing ends {_date(new)}: "
                                     f"{_date(invoice.billing_date)} is not billed.")
                voided.append(invoice)
        _audit(schedule, "billing_stopped" if at_once else "billing_end_moved", actor,
               ends_on=new.isoformat(), was=was.isoformat() if was else "",
               voided=[i.number for i in voided])
        if at_once:
            _promote_pending(schedule)
    company = schedule.client_company.name
    practice = services.practice_name(schedule.tenant)
    last = None if at_once else last_charge_on(schedule, agreement, new)
    lines = ([f"{practice} has stopped automatic billing for {company} as of today. No card "
              "will be charged again under it."] if at_once else
             [f"{practice} has moved the end of automatic billing for {company} to "
              f"{_date(new)}.",
              f"Your last charge will be on {_date(last)}." if last
              else "There will be no further charge."])
    if voided:
        lines.append("Not billed after all: " + ", ".join(
            f"invoice {i.number} for {_date(i.billing_date)}" for i in voided) + " (voided).")
    _tell_client(schedule, agreement,
                 subject=(f"Automatic billing stopped" if at_once
                          else f"Automatic billing now ends {_date(new)}"), lines=lines)
    return agreement


def run_next_now(schedule, *, actor) -> tuple[ClientInvoice, str]:
    """Test Mode only: make, send and charge the next invoice at once."""
    from apps.billing import autopay, gateway_mode

    _auto(schedule)
    today = timezone.localdate()
    if gateway_mode.for_practice(schedule.tenant) is not True:
        raise BillingRefused("Run the next billing now works only while the card processor is "
                             "in Test Mode, so no real card is charged ahead of its date.")
    agreement = in_force(schedule)
    if agreement is None or agreement.stopped_at or ended(agreement, today):
        raise BillingRefused(f"{schedule.client_company.name} has not agreed to automatic "
                             "billing, so nothing is billed.")
    start = starts_on(schedule, agreement)
    done = set(_billed(schedule).values_list("billing_date", flat=True))
    through = agreement.ends_on or start + timing.HORIZON
    nxt = next((d for d in timing.dates(schedule, start, through) if d not in done), None)
    if nxt is None:
        raise BillingRefused("There is no billing date left to bill.")
    invoice = make_one(schedule, agreement, nxt, today, actor=actor)
    if invoice is None:
        raise BillingRefused("The invoice for the next billing date could not be made.")
    invoice.refresh_from_db()
    card = autopay.card_on_file(schedule.client_company)
    reason = autopay.unusable_card(schedule.tenant, card)
    if not reason:
        try:
            attempt, message = card_payments.charge_on_file(invoice, card=card)
        except card_payments.PaymentRefused as exc:
            reason = autopay.refusal_reason(exc)
    if reason:
        # Never silent: on its history too, as the 9:00 job would put it.
        autopay.passed_over(invoice, reason, today)
        return invoice, f"Invoice {invoice.number} was sent; it was not charged: {reason}"
    if attempt.status in (A.DECLINED, A.FAILED):
        autopay._tell_failure(attempt, card, message)
    invoice.refresh_from_db()
    return invoice, f"Invoice {invoice.number} for {_date(nxt)}: {message}"


def change_lines(schedule, new_lines, *, actor, today: date | None = None) -> dict:
    """A change of lines or price while an agreement is in force: from the
    first billing date at least 7 days out that has no invoice yet. The
    client is emailed. Returns {from, total}."""
    today = today or timezone.localdate()
    agreement = in_force(schedule)
    start = max(today + CHANGE_NOTICE, starts_on(schedule, agreement))
    done = set(_billed(schedule).values_list("billing_date", flat=True))
    through = agreement.ends_on or start + timing.HORIZON
    when = next((d for d in timing.dates(schedule, start, through) if d not in done), None)
    old_total = total_of(lines_for(schedule, when) if when else schedule.lines)
    if when is None:
        raise services.BillingError(
            "No billing date is left at least 7 days out, so the change would never apply.")
    schedule.pending_lines, schedule.pending_from = new_lines, when
    company = schedule.client_company.name
    new_total = total_of(new_lines)
    _tell_client(schedule, agreement, subject=f"Automatic billing changes from {_date(when)}",
                 lines=[f"From {_date(when)}, automatic billing for {company} changes to: "
                        + "; ".join(f"{line['description']} ({money.dollars(money.line_amount(Decimal(str(line['quantity'])), line['unit_price_cents']))})"
                                    for line in new_lines) + ".",
                        f"Total each time: {money.dollars(new_total)} (until then, "
                        f"{money.dollars(old_total)}).",
                        "To stop instead, press Stop automatic billing in the portal."])
    _audit(schedule, "billing_change_scheduled", actor, applies_from=when.isoformat(),
           total=money.dollars(new_total), was=money.dollars(old_total))
    return {"from": when.isoformat(), "total_cents": new_total}


def _promote_pending(schedule) -> None:
    """Once nothing more is billed under an agreement, a waiting change is
    simply the lines."""
    if schedule.pending_lines:
        ClientInvoiceSchedule.all_objects.filter(pk=schedule.pk).update(
            lines=schedule.pending_lines, pending_lines=None, pending_from=None,
            updated_at=timezone.now())


# ------------------------------------------------------------ the jobs

def close_past(tenant, today: date) -> int:
    """Agreements whose last day has passed are Ended."""
    closed = 0
    for agreement in (BillingAgreement.all_objects
                      .filter(tenant=tenant, ended_at__isnull=True, ends_on__lt=today)
                      .select_related("schedule")):
        BillingAgreement.all_objects.filter(pk=agreement.pk).update(
            ended_at=timezone.now(), updated_at=timezone.now())
        _promote_pending(agreement.schedule)
        _audit(agreement.schedule, "billing_ended", None, ends_on=agreement.ends_on.isoformat())
        closed += 1
    return closed


def make_due(tenant, today: date | None = None) -> list[ClientInvoice]:
    """The 5:00 job: each billing date whose invoice is due to be made
    (`lead_days` before it, or missed), made, numbered and emailed."""
    today = today or timezone.localdate()
    close_past(tenant, today)
    made = []
    schedules = ClientInvoiceSchedule.all_objects.filter(tenant=tenant, mode=AUTO,
                                                         is_active=True)
    for schedule in schedules.select_related("client_company", "contact", "tenant"):
        agreement = in_force(schedule)
        if agreement is None or agreement.stopped_at:
            continue
        if schedule.client_company.deleted_at is not None:
            continue
        start = starts_on(schedule, agreement)
        end = today + timedelta(days=schedule.lead_days)
        if agreement.ends_on is not None:
            end = min(end, agreement.ends_on)
        done = set(_billed(schedule).filter(billing_date__gte=start)
                   .values_list("billing_date", flat=True))
        for day in timing.dates(schedule, start, end):
            if day in done:
                continue
            invoice = make_one(schedule, agreement, day, today)
            if invoice is not None:
                made.append(invoice)
    return made


def make_one(schedule, agreement, billing_date: date, today: date, *, actor=None
             ) -> ClientInvoice | None:
    """One billing date's invoice: written, numbered and emailed with no
    approval step (the client agreed to it). A failure to send is never
    silent: the invoice stays, ready, and the practice owner is told."""
    from apps.crm.services import outbox
    from apps.tenancy.models import Role

    tenant = schedule.tenant
    try:
        with transaction.atomic():
            locked = ClientInvoiceSchedule.all_objects.select_for_update().get(pk=schedule.pk)
            if _billed(locked).filter(billing_date=billing_date).exists():
                return None
            lines = list(lines_for(locked, billing_date))
            if locked.pending_lines and locked.pending_from and billing_date >= locked.pending_from:
                ClientInvoiceSchedule.all_objects.filter(pk=locked.pk).update(
                    lines=locked.pending_lines, pending_lines=None, pending_from=None,
                    updated_at=timezone.now())
            own = {field: getattr(locked, field)
                   for field in ("notes", "terms", "pay_instructions", "email_subject",
                                 "email_body") if getattr(locked, field)}
            category = (locked.income_category if locked.income_category_id
                        and locked.income_category.archived_at is None else None)
            invoice = services.create_draft(
                tenant, actor=actor, kind=ClientInvoice.Kind.RECURRING,
                client_company=locked.client_company, contact=locked.contact, schedule=locked,
                lines=lines, income_category=category,
                issue_date=min(today, billing_date), due_date=billing_date, **own)
            ClientInvoice.all_objects.filter(pk=invoice.pk).update(
                billing_date=billing_date, billing_agreement=agreement)
            invoice.refresh_from_db()
            invoice = services.make_ready(invoice, actor=actor, role=Role.FF)
            services.audit(invoice, "billed_automatically", actor,
                           billing_date=billing_date.isoformat())
    except (services.BillingError, IntegrityError) as exc:
        _tell_owner(schedule, title=f"Automatic invoice not made: {schedule.client_company.name}",
                    text=(f"The invoice for {_date(billing_date)} could not be made: {exc}. "
                          "Nothing was sent or charged."),
                    key=f"not-made:{schedule.pk}:{billing_date}", email=True)
        return None
    invoice.refresh_from_db()
    message = invoice.outbox_message
    try:
        if message is None:
            raise outbox.SendNotPermitted("Its email was not queued.")
        # The approval happened upstream: the practice owner set this up and
        # the client agreed to it. The Outbox's own checks still apply.
        outbox.approve(message, actor=actor, role=Role.FF)
    except outbox.SendNotPermitted as exc:
        _tell_owner(schedule, title=f"Not sent: invoice {invoice.number}",
                    text=(f"{schedule.client_company.name}'s automatic invoice {invoice.number} "
                          f"for {_date(billing_date)} was made but could not be emailed: {exc} "
                          "Send it from the invoice."),
                    key=f"not-sent:{invoice.pk}", email=True, url=f"/invoices/{invoice.pk}")
        return invoice
    if not email_line(invoice):
        from apps.billing import autopay

        reason = card_problem(schedule.tenant, autopay.card_on_file(schedule.client_company),
                              billing_date)
        _tell_owner(schedule, title=f"Sent without a card: invoice {invoice.number}",
                    text=(f"{schedule.client_company.name}'s automatic invoice {invoice.number} "
                          f"for {_date(billing_date)} was emailed with its pay link only. "
                          f"{reason}"),
                    key=f"no-card:{invoice.pk}", email=True, url=f"/invoices/{invoice.pk}")
    invoice.refresh_from_db()
    return invoice


def card_problem(tenant, card, billing_date: date) -> str:
    """Why the card on file can't be charged on `billing_date`, or "": the
    card itself (none, the other environment, expired by then, or saved in
    Test Mode while the processor is live)."""
    from apps.billing import autopay, gateway_mode

    if card is None:
        return "There is no card on file."
    row = payment_accounts.PaymentAccount.all_objects.filter(tenant=tenant).first()
    if row is None or row.environment != card.environment:
        return (f"The card ending {card.last4} was saved in the other environment of the card "
                "processor, so it can't be charged.")
    if autopay.expires_on(card) < billing_date:
        return f"The card ending {card.last4} expires before {_date(billing_date)}."
    if card.is_test:
        if gw.paused():
            return card_payments.test_card_refusal(card, live=None)
        if gateway_mode.for_practice(tenant) is not True:
            return card_payments.test_card_refusal(card, live=True)
    return ""


def email_line(invoice) -> str:
    """The invoice email's sentence for an invoice billed automatically:
    the amount, the card and the date; "" when no card can be charged."""
    from apps.billing import autopay

    if not invoice.billing_date or not invoice.client_company_id:
        return ""
    card = autopay.card_on_file(invoice.client_company)
    if card_problem(invoice.tenant, card, invoice.billing_date):
        return ""
    return (f"{money.dollars(invoice.total_cents)} will be charged to the card ending "
            f"{card.last4} on {_date(invoice.billing_date)}.")


def charge_due(tenant, today: date | None = None) -> int:
    """The 9:00 job: each invoice billed automatically whose billing date has
    come, charged to the card on file under its agreement. Never passed over
    silently (`autopay.passed_over`)."""
    from apps.billing import autopay

    today = today or timezone.localdate()
    made = 0
    due = (ClientInvoice.all_objects
           .filter(tenant=tenant, billing_agreement__isnull=False, billing_date__lte=today,
                   status__in=ClientInvoice.OPEN)
           .select_related("billing_agreement", "client_company", "tenant")
           .order_by("billing_date", "number"))
    for invoice in due:
        if invoice.balance_cents <= 0:
            continue
        agreement = invoice.billing_agreement
        if agreement.stopped_at is not None:
            autopay.passed_over(invoice, "Automatic billing was stopped on "
                                f"{_date(timezone.localtime(agreement.stopped_at).date())}, so "
                                "the card was not charged.", today, daily=False)
            continue
        if agreement.ends_on is not None and invoice.billing_date > agreement.ends_on:
            autopay.passed_over(invoice, f"Automatic billing ended {_date(agreement.ends_on)}, "
                                "before this billing date, so the card was not charged.",
                                today, daily=False)
            continue
        if not autopay._another_try_due(invoice, today):
            continue
        card = autopay.card_on_file(invoice.client_company)
        reason = autopay.unusable_card(tenant, card)
        if not reason and card is not None and autopay.expires_on(card) < today:
            reason = f"The card ending {card.last4} has expired, so nothing was charged."
        if reason:
            autopay.passed_over(invoice, reason, today)
            continue
        try:
            attempt, message = card_payments.charge_on_file(invoice, card=card)
        except card_payments.PaymentRefused as exc:
            autopay.passed_over(invoice, autopay.refusal_reason(exc), today)
            continue
        made += 1
        if attempt.status in (A.DECLINED, A.FAILED):
            autopay._tell_failure(attempt, card, message)
    return made


# ------------------------------------------------------------ the record

def _audit(schedule, verb, actor, **payload) -> None:
    from apps.tenancy.models import AuditEvent

    AuditEvent.all_objects.create(
        tenant_id=schedule.tenant_id, actor=actor, verb=f"billing.{verb}",
        target_type="client_invoice_schedule", target_id=schedule.pk,
        payload={"company": str(schedule.client_company_id), **payload})


def timeline(schedule, today: date | None = None) -> list[dict]:
    """Started, the contract's end if any, month to month since, notice
    given, the last billing date: for the latest agreement."""
    today = today or timezone.localdate()
    agreement = latest(schedule)
    if agreement is None:
        return []
    start = starts_on(schedule, agreement)
    first = timing.next_date(schedule, start, through=agreement.ends_on)
    rows = [{"what": "Agreed", "on": timezone.localtime(agreement.agreed_at).date().isoformat(),
             "by": agreement.agreed_by.full_name or agreement.agreed_by.email}]
    if first:
        rows.append({"what": "First billing date", "on": first.isoformat()})
    if schedule.term_ends_on:
        rows.append({"what": "Contract ends", "on": schedule.term_ends_on.isoformat()})
        rows.append({"what": "Month to month since",
                     "on": (schedule.term_ends_on + timedelta(days=1)).isoformat(),
                     "future": schedule.term_ends_on >= today})
    else:
        rows.append({"what": "Month to month since", "on": start.isoformat()})
    if agreement.notice_given_at:
        rows.append({"what": "Notice given",
                     "on": timezone.localtime(agreement.notice_given_at).date().isoformat(),
                     "by": (agreement.notice_given_by.full_name or agreement.notice_given_by.email)
                     if agreement.notice_given_by else ""})
    if agreement.stopped_at:
        rows.append({"what": "Stopped by the practice",
                     "on": timezone.localtime(agreement.stopped_at).date().isoformat()})
    if agreement.ends_on:
        last = last_charge_on(schedule, agreement, agreement.ends_on)
        rows.append({"what": "Billing ends", "on": agreement.ends_on.isoformat()})
        if last and not agreement.stopped_at:
            rows.append({"what": "Last billing date", "on": last.isoformat()})
    if agreement.ended_at:
        rows.append({"what": "Ended", "on": timezone.localtime(agreement.ended_at).date().isoformat()})
    return rows


STATE_LABELS = {WAITING: "Waiting for {company} to agree", ACTIVE: "Active",
                ENDING: "Notice given, ending {ends}", ENDED: "Ended"}


def represent(schedule, *, owner: bool = True, today: date | None = None) -> dict:
    """What the practice's screen shows of a recurring invoice that bills
    automatically (merged into the schedule's own answer)."""
    from apps.billing import gateway_mode

    today = today or timezone.localdate()
    if schedule.mode != AUTO:
        return {}
    code = state_of(schedule, today)
    agreement = latest(schedule)
    last = _billed(schedule).order_by("-billing_date").values_list("billing_date",
                                                                    flat=True).first()
    nxt = next_billing_on(schedule, today)
    return {
        "state": code,
        "state_label": STATE_LABELS[code].format(
            company=schedule.client_company.name,
            ends=_date(agreement.ends_on) if agreement and agreement.ends_on else ""),
        "next_billing_on": nxt.isoformat() if nxt else None,
        "last_billed_on": last.isoformat() if last else None,
        "timing_words": timing.describe(schedule),
        "ends_on": agreement.ends_on.isoformat() if agreement and agreement.ends_on
        and code in (ENDING,) else None,
        "ends_set_by": agreement.ends_set_by if agreement and code == ENDING else "",
        "timeline": timeline(schedule, today),
        "pending": ({"from": schedule.pending_from.isoformat(),
                     "total_cents": total_of(schedule.pending_lines)}
                    if schedule.pending_lines and schedule.pending_from else None),
        "invited_at": schedule.invited_at.isoformat() if schedule.invited_at else None,
        # Only while the processor last said Test Mode.
        "can_run_now": (owner and code in (ACTIVE, ENDING)
                        and gateway_mode.last_for_practice(schedule.tenant) is True),
    }


def portal(company, today: date | None = None) -> list[dict]:
    """What the client owner sees: each recurring invoice billed
    automatically for the company, its terms and what can be done."""
    today = today or timezone.localdate()
    rows = []
    for schedule in (ClientInvoiceSchedule.all_objects
                     .filter(client_company=company, mode=AUTO, is_active=True)
                     .select_related("tenant", "client_company").order_by("created_at")):
        code = state_of(schedule, today)
        agreement = latest(schedule)
        text = words(schedule, today) if code == WAITING else (agreement.wording if agreement else "")
        row = {
            "id": str(schedule.pk), "state": code,
            "what": [{"description": line["description"],
                      "amount_cents": money.line_amount(Decimal(str(line["quantity"])),
                                                        line["unit_price_cents"])}
                     for line in schedule.lines],
            "total_cents": total_of(schedule.lines), "timing_words": timing.describe(schedule),
            "words": text, "version": WORDING_VERSION, "key": words_key(text),
            "next_billing_on": None, "ends_on": None, "last_charge_on": None,
            "can_withdraw": False, "agreed_at": None,
            "pending": ({"from": schedule.pending_from.isoformat(),
                         "total_cents": total_of(schedule.pending_lines)}
                        if schedule.pending_lines and schedule.pending_from else None),
        }
        if agreement is not None and code in (ACTIVE, ENDING):
            nxt = next_billing_on(schedule, today)
            row.update(agreed_at=agreement.agreed_at.isoformat(),
                       agreed_by=agreement.agreed_by.full_name or agreement.agreed_by.email,
                       next_billing_on=nxt.isoformat() if nxt else None)
            if agreement.ends_on:
                last = last_charge_on(schedule, agreement, agreement.ends_on)
                row.update(ends_on=agreement.ends_on.isoformat(),
                           last_charge_on=last.isoformat() if last else None,
                           can_withdraw=agreement.ends_set_by == BillingAgreement.SetBy.CLIENT)
        if code == ENDED and agreement is not None:
            row["ended_on"] = (agreement.ends_on.isoformat() if agreement.ends_on else None)
        rows.append(row)
    return rows


# ------------------------------------------------------------ the mail

def _tell_owner(schedule, *, title, text, key, email=False, url="/invoices") -> None:
    """A Notice to each practice owner, once per `key`; and an email, when
    asked, with it."""
    import uuid

    from apps.crm.models import OutboxMessage
    from apps.crm.services import email_layout, outbox
    from apps.notify import service as notify
    from apps.notify.models import Kind
    from apps.tenancy.context import tenant_context
    from apps.tenancy.models import Membership, Role

    tenant = schedule.tenant
    source_id = uuid.uuid5(uuid.UUID("0b8f7a52-3c1d-4e9f-8a6b-2d4c6e8f0a13"), f"{tenant.pk}:{key}")
    try:
        with tenant_context(tenant.pk):
            for owner in Membership.all_objects.filter(
                    tenant=tenant, role=Role.FF, revoked_at__isnull=True).select_related("user"):
                notice = notify.tell(tenant_id=tenant.pk, recipient_id=owner.user_id,
                                     kind=Kind.PAYMENTS, title=title, text=text, url=url,
                                     source_type="automatic_billing", source_id=source_id)
                if notice is not None and email and owner.user.email:
                    outbox.create_message(
                        tenant=tenant, producer=OutboxMessage.Producer.PAYMENT_NOTICE,
                        to_address=owner.user.email, subject=title, body_text=text,
                        body_html=email_layout.document(
                            tenant, subject=title, preheader=text, internal=True,
                            content_html=f"<p>{escape(text)}</p>"),
                        source_type="client_invoice_schedule", source_id=schedule.pk,
                        force_direct=True)
    except Exception as exc:  # noqa: BLE001 — what it tells of already happened
        log.warning("automatic billing notice for %s not sent (%s)", schedule.pk,
                    type(exc).__name__)


def _client_mail(schedule, to, subject, lines) -> None:
    from apps.crm.models import OutboxMessage
    from apps.crm.services import email_layout, outbox
    from apps.tenancy.context import tenant_context

    tenant = schedule.tenant
    with tenant_context(tenant.pk):
        outbox.create_message(
            tenant=tenant, producer=OutboxMessage.Producer.AUTOPAY_NOTICE, to_address=to,
            subject=subject, body_text="\n\n".join(lines),
            body_html=email_layout.document(
                tenant, subject=subject, preheader=lines[0],
                content_html="".join(f"<p>{escape(line)}</p>" for line in lines)),
            source_type="client_invoice_schedule", source_id=schedule.pk, force_direct=True)


def _tell_client(schedule, agreement, *, subject, lines, extra=()) -> None:
    """The client owner who agreed, and whoever else acted, by email."""
    seen = []
    for address in (agreement.agreed_by.email if agreement and agreement.agreed_by else "",
                    *extra):
        if address and address.lower() not in (s.lower() for s in seen):
            seen.append(address)
    for to in seen:
        try:
            _client_mail(schedule, to, subject, lines)
        except Exception as exc:  # noqa: BLE001 — what it tells of already happened
            log.warning("automatic billing email for %s not sent (%s)", schedule.pk,
                        type(exc).__name__)
