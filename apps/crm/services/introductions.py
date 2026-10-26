"""R3, outbound introductions (owner, 2026-10-24), and R3b's specialties.

An introduction is an **outbound** `referral` row: `referrer` is the referral
partner whose page it was made from, `prospect` the contact they were
introduced to (another partner or a prospect), on the referral pipeline. It
carries the date, a note, who made it, and the outcome the practice sets:
no reply, met, became a client, not a fit.

Making one drafts the introduction from the library's "Introduction" template
**to each of the two**, each draft introducing the other, into the Outbox for
approval; or, chosen on the Introduce form, **one email to both** from
"Introduction, one email to both" (owner, 2026-10-26). That one email carries
its second recipient past every guard with a check of its own: the dev
allow-list, the demo's redirect and each person's unsubscribes
(`outbox.recipients_of`).

Specialties: a partner's general **discipline** (fractional CMO, CFO, COO,
CHRO, other) and several **specialties** in the practice's own words.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.crm.models import Contact, OutboxMessage, Referral
from apps.tenancy.models import AuditEvent

OUT = Referral.Direction.OUTBOUND
USE = "introduction"
USE_BOTH = "introduction_both"
SOURCE_TYPE = "introduction"
SEND_BY_DAYS = 14
#: How many specialties a contact carries, and how long each may be.
MOST_SPECIALTIES, LONGEST = 12, 60


class IntroductionRefused(ValueError):
    pass


def full_name(contact) -> str:
    return f"{contact.first_name} {contact.last_name}".strip() or "them"


def discipline_label(contact) -> str:
    """"Fractional CMO"; nothing for "other", which says nothing in a sentence."""
    if not contact.discipline or contact.discipline == Contact.Discipline.OTHER:
        return ""
    return contact.get_discipline_display()


def clean_specialties(values) -> list[str]:
    """Trimmed, one space between words, no repeats (case aside), at most
    twelve of at most sixty characters. Refuses rather than cuts."""
    if values in (None, ""):
        return []
    if not isinstance(values, (list, tuple)):
        raise IntroductionRefused("Specialties are a list of short phrases.")
    out, seen = [], set()
    for raw in values:
        text = " ".join(str(raw or "").split())
        if not text:
            continue
        if len(text) > LONGEST:
            raise IntroductionRefused(f"“{text[:20]}…” is longer than {LONGEST} characters.")
        if text.casefold() in seen:
            continue
        seen.add(text.casefold())
        out.append(text)
    if len(out) > MOST_SPECIALTIES:
        raise IntroductionRefused(f"At most {MOST_SPECIALTIES} specialties.")
    return out


def used_specialties(tenant_id) -> list[dict]:
    """Every specialty already used in the practice, most used first, for
    suggesting as a phrase is typed."""
    counts: dict = {}
    spelled: dict = {}
    for values in Contact.all_objects.filter(tenant_id=tenant_id, deleted_at__isnull=True) \
            .exclude(specialties=[]).values_list("specialties", flat=True):
        for value in values:
            key = value.casefold()
            counts[key] = counts.get(key, 0) + 1
            spelled.setdefault(key, value)
    return [{"specialty": spelled[k], "contacts": n}
            for k, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


# ------------------------------------------------------------- introductions

def introductions_of(contact):
    """Every introduction this contact is on, either side."""
    from django.db.models import Q

    return (Referral.all_objects.filter(tenant_id=contact.tenant_id, direction=OUT)
            .filter(Q(referrer=contact) | Q(prospect=contact))
            .select_related("referrer", "referrer__company", "prospect", "prospect__company",
                            "created_by", "outbox_message"))


def counts_for(partner) -> dict:
    made = Referral.all_objects.filter(tenant_id=partner.tenant_id, direction=OUT,
                                       referrer=partner)
    return {"made": made.count(),
            "became_client": made.filter(intro_outcome=Referral.IntroOutcome.CLIENT).count()}


def counts_text(counts) -> str:
    made, won = counts["made"], counts["became_client"]
    text = f"{made} introduction{'s' if made != 1 else ''} made"
    return text + (f" · {won} became a client" if made else "")


def _values(recipient, other, referral, actor):
    from apps.crm.services import templates

    values = templates.values_for(recipient, tenant=recipient.tenant, sender=actor)
    company = other.company.name if other.company_id else ""
    values.update({
        "OtherName": full_name(other), "OtherFirstName": (other.first_name or "").strip(),
        "OtherCompany": company, "OtherDiscipline": discipline_label(other),
        "OtherSpecialties": ", ".join(other.specialties or []),
        "IntroNote": (referral.note or "").strip(),
        **templates.pronoun_values(other, "Other"),
        "OtherBlurb": (other.intro_blurb or "").strip(),
    })
    return values


def compose(template, recipient, other, referral, actor):
    from apps.crm.services import templates

    values = _values(recipient, other, referral, actor)
    fallback = template.first_name_fallback or templates.DEFAULT_FALLBACK
    subject = templates.render_subject(template.subject, values, fallback=fallback)
    body = templates.render(template.body, values, fallback=fallback)
    return subject, templates.with_signature(body, recipient.tenant, actor)


def template_for(tenant, together=False):
    """The practice's introduction template, or its one-email-to-both one.
    `for_use` seeds it the first time it is wanted; the library never rewrites
    one already there."""
    from apps.crm.services import templates

    return templates.for_use(tenant, USE_BOTH if together else USE)


@transaction.atomic
def introduce(partner, other, *, actor, note="", on=None, together=False):
    """Record an introduction from `partner`'s page to `other`, and draft it
    to each of them for approval, or, `together`, as one email to both."""
    from apps.crm.services import outbox, pipeline

    if partner.pk == other.pk:
        raise IntroductionRefused("Choose someone other than the partner themselves.")
    if partner.tenant_id != other.tenant_id:
        raise IntroductionRefused("That contact isn't in this practice.")
    if not partner.type_links.filter(contact_type__code="referral_partner").exists():
        raise IntroductionRefused(f"{full_name(partner)} isn't a referral partner.")
    missing = [full_name(c) for c in (partner, other) if not c.primary_email]
    if missing:
        raise IntroductionRefused(f"{' and '.join(missing)} {'has' if len(missing) == 1 else 'have'} "
                                  "no email address, so the introduction can't be drafted.")
    referral_pipeline = pipeline.referral_pipeline(partner.tenant)
    if referral_pipeline is None:
        raise IntroductionRefused("This practice has no referral pipeline.")
    row = Referral.all_objects.create(
        tenant_id=partner.tenant_id, direction=OUT, referrer=partner, prospect=other,
        pipeline=referral_pipeline, referred_on=on or timezone.localdate(),
        note=(note or "").strip()[:2000], created_by=actor,
        fee_terms=(partner.referral_fee_terms or "")[:255])
    send_by = timezone.now() + timezone.timedelta(days=SEND_BY_DAYS)
    drafts = []
    if together:
        if partner.primary_email.strip().lower() == other.primary_email.strip().lower():
            raise IntroductionRefused("They share one email address, so one email to both "
                                      "would reach one inbox. Send two instead.")
        subject, body = compose(template_for(partner.tenant, together=True), partner, other,
                                row, actor)
        drafts.append(outbox.create_message(
            tenant=partner.tenant, producer=OutboxMessage.Producer.INTRODUCTION,
            to_contact=partner, to_address=partner.primary_email,
            also_to_contact=other, also_to_address=other.primary_email, subject=subject,
            body_text=body, actor=actor, send_by=send_by, source_type=SOURCE_TYPE,
            source_id=row.pk))
    template = template_for(partner.tenant)
    for recipient, about in (() if together else ((partner, other), (other, partner))):
        subject, body = compose(template, recipient, about, row, actor)
        drafts.append(outbox.create_message(
            tenant=partner.tenant, producer=OutboxMessage.Producer.INTRODUCTION,
            to_contact=recipient, to_address=recipient.primary_email, subject=subject,
            body_text=body, actor=actor, send_by=send_by, source_type=SOURCE_TYPE,
            source_id=row.pk))
    row.outbox_message = drafts[0]
    row.save(update_fields=["outbox_message", "updated_at"])
    for target in (partner, other):
        AuditEvent.all_objects.create(
            tenant_id=partner.tenant_id, actor=actor, verb="introduction.made",
            target_type="contact", target_id=target.pk,
            payload={"introduction": str(row.pk), "partner": full_name(partner),
                     "to": full_name(other), "drafts": [str(d.pk) for d in drafts],
                     "together": bool(together)})
    return row, drafts


def set_outcome(row, outcome, *, actor):
    if outcome not in Referral.IntroOutcome.values and outcome != "":
        raise IntroductionRefused("No reply, met, became a client or not a fit.")
    row.intro_outcome = outcome
    row.intro_outcome_at = timezone.now() if outcome else None
    row.save(update_fields=["intro_outcome", "intro_outcome_at", "updated_at"])
    for target in (row.referrer_id, row.prospect_id):
        AuditEvent.all_objects.create(
            tenant_id=row.tenant_id, actor=actor, verb="introduction.outcome",
            target_type="contact", target_id=target,
            payload={"introduction": str(row.pk), "outcome": outcome,
                     "label": row.get_intro_outcome_display() if outcome else "cleared"})
    return row


def represent(row, viewer=None) -> dict:
    """An introduction as either contact's page shows it."""
    def person(c):
        return {"id": str(c.pk), "name": full_name(c),
                "company": c.company.name if c.company_id else "",
                "discipline": discipline_label(c)}

    message = row.outbox_message
    return {"id": str(row.pk), "partner": person(row.referrer), "to": person(row.prospect),
            "on": row.referred_on.isoformat(), "note": row.note,
            "made_by": (getattr(row.created_by, "full_name", "") or
                        getattr(row.created_by, "email", "")) if row.created_by_id else "",
            "outcome": row.intro_outcome, "outcome_label": row.get_intro_outcome_display()
            if row.intro_outcome else "",
            "draft_state": message.state if message is not None else ""}
