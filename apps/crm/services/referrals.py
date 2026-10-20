"""Inbound referrals: who sent the practice a prospect (owner, 2026-10-20).

Recording one puts the prospect in the sales pipeline at its first stage,
unless they are in it already, in which case they keep their stage and the
referral is recorded against it. Any contact may be the referrer (a client or
a friend refers people too); being one does not make them a referral partner.

The outcome is written when the prospect first reaches a won or lost stage
(`after_stage_change`, called by `pipeline.change_stage`) and then holds.

At three moments a thank-you to the referrer is drafted into the Outbox, each
a practice setting: when the referral is recorded, when the prospect is won,
when lost. The lost one gives no reason. A draft is never sent without
approval, is never made twice for the same referrer and moment, and once
approved counts as the referrer's next touch.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.crm.models import Contact, OutboxMessage, Referral, StageSemantic
from apps.tenancy.models import AuditEvent

RECORDED, WON, LOST = "recorded", "won", "lost"
MOMENTS = (RECORDED, WON, LOST)
#: Where each moment's draft is marked, so it is made once.
SOURCE_TYPE = {moment: f"referral_{moment}" for moment in MOMENTS}
SETTING = {moment: f"referral_thanks_{moment}" for moment in MOMENTS}
#: How long a thank-you waits for approval before it expires unsent.
SEND_BY_DAYS = 14


class ReferralRefused(Exception):
    pass


def full_name(contact) -> str:
    return f"{contact.first_name} {contact.last_name}".strip()


def referral_for(prospect, pipeline=None):
    """The inbound referral that brought this prospect into `pipeline` (the
    sales pipeline by default), or None."""
    from apps.crm.services import pipeline as pipeline_service

    pipeline = pipeline or pipeline_service.sales_pipeline(prospect.tenant)
    if pipeline is None:
        return None
    return Referral.all_objects.filter(
        tenant_id=prospect.tenant_id, prospect=prospect, pipeline=pipeline,
        direction=Referral.Direction.INBOUND,
    ).select_related("referrer").first()


def _check_referrer(prospect, referrer):
    if referrer.tenant_id != prospect.tenant_id or referrer.deleted_at is not None:
        raise ReferralRefused("That contact is not available.")
    if referrer.pk == prospect.pk:
        raise ReferralRefused("Someone cannot refer themselves.")


@transaction.atomic
def record(prospect, referrer, *, actor=None, note="", referred_on=None,
           from_import=False):
    """Record `referrer` as having sent `prospect`, or change who did.

    `from_import` is the CSV import's path: a statement about history, so the
    placement runs no stage rules and no thank-you is drafted.
    """
    from apps.crm.services import pipeline as pipeline_service

    _check_referrer(prospect, referrer)
    sales = pipeline_service.sales_pipeline(prospect.tenant)
    if sales is None:
        raise ReferralRefused("This practice has no sales pipeline to put them in.")

    existing = referral_for(prospect, sales)
    if existing is not None:
        if existing.referrer_id == referrer.pk:
            if note and note != existing.note:
                existing.note = note
                existing.save(update_fields=["note", "updated_at"])
            return existing
        return change_referrer(existing, referrer, actor=actor, quiet=from_import)

    position = pipeline_service.position_for(prospect, sales)
    if position is None:
        stage = pipeline_service.entry_stage(sales)
        if stage is not None:
            if from_import:
                pipeline_service.set_stage_from_import(prospect, stage, actor=actor)
            else:
                pipeline_service.change_stage(
                    prospect, stage, actor=actor,
                    reason=f"referred by {full_name(referrer)}")
        position = pipeline_service.position_for(prospect, sales)

    referral = Referral.all_objects.create(
        tenant=prospect.tenant, prospect=prospect, referrer=referrer, pipeline=sales,
        referred_on=referred_on or timezone.localdate(), note=note,
        fee_terms=referrer.referral_fee_terms or "", created_by=actor,
    )
    # Recorded after the fact for someone already decided: the outcome is
    # history, written without a thank-you for it.
    if position is not None and position.stage.semantic in (StageSemantic.WON,
                                                            StageSemantic.LOST):
        _set_outcome(referral, position.stage.semantic, at=_reached(position))
    AuditEvent.all_objects.create(
        tenant=prospect.tenant, actor=actor, verb="referral.recorded",
        target_type="contact", target_id=prospect.pk,
        payload={"referral": str(referral.pk), "referrer": str(referrer.pk),
                 "from_import": from_import},
    )
    if not from_import:
        draft_thanks(referral, RECORDED, actor=actor)
    return referral


@transaction.atomic
def change_referrer(referral, referrer, *, actor=None, quiet=False):
    """The credit moves to someone else. Their fee terms are taken as they are
    today; a thank-you for the referral goes to them, not again to the first."""
    _check_referrer(referral.prospect, referrer)
    if referral.referrer_id == referrer.pk:
        return referral
    before = referral.referrer_id
    referral.referrer = referrer
    referral.fee_terms = referrer.referral_fee_terms or ""
    referral.save(update_fields=["referrer", "fee_terms", "updated_at"])
    AuditEvent.all_objects.create(
        tenant=referral.tenant, actor=actor, verb="referral.referrer_changed",
        target_type="contact", target_id=referral.prospect_id,
        payload={"referral": str(referral.pk), "from": str(before), "to": str(referrer.pk)},
    )
    if not quiet:
        draft_thanks(referral, RECORDED, actor=actor)
    return referral


def remove(referral, *, actor=None):
    """Not referred after all. Their pipeline place stays: being in Sales is
    a fact of its own. An unapproved thank-you for it is withdrawn."""
    OutboxMessage.all_objects.filter(
        tenant_id=referral.tenant_id, source_type__in=SOURCE_TYPE.values(),
        source_id=referral.pk,
        state__in=[OutboxMessage.State.DRAFT, OutboxMessage.State.PENDING_APPROVAL],
    ).update(state=OutboxMessage.State.REJECTED, updated_at=timezone.now())
    AuditEvent.all_objects.create(
        tenant=referral.tenant, actor=actor, verb="referral.removed",
        target_type="contact", target_id=referral.prospect_id,
        payload={"referral": str(referral.pk), "referrer": str(referral.referrer_id)},
    )
    referral.delete()


# ----------------------------------------------------------------- outcome

def _reached(position):
    """When the prospect reached the stage they hold: the move that put them
    there, not the day the referral was written down."""
    from apps.crm.models import StageChange

    change = StageChange.all_objects.filter(
        tenant_id=position.tenant_id, contact_id=position.contact_id,
        pipeline_id=position.pipeline_id, to_stage_id=position.stage_id,
    ).order_by("-created_at").first()
    return change.created_at if change else position.updated_at


def _set_outcome(referral, semantic, *, at=None) -> bool:
    """Won holds for good; lost holds until a win. True when it changed."""
    outcome = Referral.Outcome.WON if semantic == StageSemantic.WON else Referral.Outcome.LOST
    if referral.outcome == Referral.Outcome.WON or referral.outcome == outcome:
        return False
    referral.outcome = outcome
    referral.outcome_at = at or timezone.now()
    referral.save(update_fields=["outcome", "outcome_at", "updated_at"])
    return True


def after_stage_change(contact, to_stage, *, actor=None, quiet=False):
    """Called on every stage move. A referred prospect reaching won or lost
    records the outcome and, unless `quiet` (an import), drafts the thanks."""
    if to_stage.semantic not in (StageSemantic.WON, StageSemantic.LOST):
        return None
    referral = Referral.all_objects.filter(
        tenant_id=contact.tenant_id, prospect=contact, pipeline_id=to_stage.pipeline_id,
        direction=Referral.Direction.INBOUND,
    ).select_related("referrer", "prospect").first()
    if referral is None or not _set_outcome(referral, to_stage.semantic):
        return None
    AuditEvent.all_objects.create(
        tenant=contact.tenant, actor=actor, verb="referral.outcome",
        target_type="contact", target_id=contact.pk,
        payload={"referral": str(referral.pk), "outcome": referral.outcome},
    )
    if quiet:
        return None
    return draft_thanks(referral, WON if referral.outcome == Referral.Outcome.WON else LOST,
                        actor=actor)


# ----------------------------------------------------------------- thanks

def compose_thanks(referral, moment, *, actor=None) -> str:
    """The words. Plain and short, as a person writes; the lost one says
    only that it did not go ahead, never why."""
    from apps.crm.services import sender as sender_service

    referrer, prospect = referral.referrer, referral.prospect
    name = full_name(prospect)
    if moment == RECORDED:
        middle = (f"Thank you for introducing me to {name}. I'll take good care of them, "
                  "and I'll let you know how it goes.")
    elif moment == WON:
        middle = (f"Good news: {name} has decided to work with us. Thank you for the "
                  "introduction; it means a lot.")
    else:
        middle = (f"A quick update on {name}: it didn't turn into an engagement this time. "
                  "Thank you all the same for thinking of me. I appreciate every "
                  "introduction.")
    signature_text, _ = sender_service.signature(referral.tenant, actor)
    return "\n".join([f"Hi {referrer.first_name},", "", middle, "", signature_text]).rstrip()


SUBJECT = {
    RECORDED: "Thank you for the introduction",
    WON: "Good news, and thank you",
    LOST: "A quick update, and thank you",
}


def draft_thanks(referral, moment, *, actor=None):
    """One draft per referrer per moment, when the practice has it on."""
    from apps.crm.services.outbox import P, create_message

    tenant = referral.tenant
    if not getattr(tenant, SETTING[moment]):
        return None
    referrer = Contact.all_objects.filter(pk=referral.referrer_id,
                                          deleted_at__isnull=True).first()
    if referrer is None:
        return None
    if OutboxMessage.all_objects.filter(
            tenant=tenant, source_type=SOURCE_TYPE[moment], source_id=referral.pk,
            to_contact=referrer).exists():
        return None
    address = referrer.primary_email or ""
    # Signed by the person whose relationship it is when no one is at the
    # keyboard (a stage move from a job).
    actor = actor or referrer.owner
    return create_message(
        tenant=tenant, producer=P.REFERRAL_THANKS, to_contact=referrer,
        to_address=address, subject=SUBJECT[moment],
        body_text=compose_thanks(referral, moment, actor=actor), actor=actor,
        warning="" if address else f"{full_name(referrer)} has no email address.",
        send_by=timezone.now() + timezone.timedelta(days=SEND_BY_DAYS),
        source_type=SOURCE_TYPE[moment], source_id=referral.pk,
    )


def thanks_sent(message):
    """An approved thank-you is the referrer's touch: the next one is a full
    cadence period from now. Only for someone on a touch schedule."""
    from apps.crm.services.referral import _next_touch

    contact = message.to_contact
    if contact is None or contact.referral_next_touch_at is None:
        return
    contact.referral_next_touch_at = _next_touch(contact, message.sent_at or timezone.now())
    contact.save(update_fields=["referral_next_touch_at", "updated_at"])


# ----------------------------------------------------------------- reading

def represent(referral) -> dict:
    """One row, as the API sends it: who, when, and where the prospect is now."""
    from apps.crm.services import pipeline as pipeline_service

    prospect, referrer = referral.prospect, referral.referrer
    position = pipeline_service.position_for(prospect, referral.pipeline)
    return {
        "id": str(referral.pk),
        "direction": referral.direction,
        "referrer": {"id": str(referrer.pk), "name": full_name(referrer)},
        "prospect": {"id": str(prospect.pk), "name": full_name(prospect),
                     "company": prospect.company.name if prospect.company_id else ""},
        "pipeline": str(referral.pipeline_id),
        "stage": ({"label": position.stage.label, "semantic": position.stage.semantic}
                  if position else None),
        "outcome": referral.outcome,
        "outcome_at": referral.outcome_at.isoformat() if referral.outcome_at else None,
        "referred_on": referral.referred_on.isoformat(),
        "note": referral.note,
        "fee_terms": referral.fee_terms,
    }
