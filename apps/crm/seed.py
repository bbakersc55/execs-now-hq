"""Seeding a NEW tenant. The data migration covers tenants that already exist;
this covers every tenant created afterwards."""

from __future__ import annotations

# (name, kind, position, [(code, label, semantic, position), ...])
#
# These are the owner's ACTUAL stages, not a generic funnel. The old six-stage
# seed (contact -> lead -> qualified_lead -> client + lost/dormant) is gone: it
# was a guess, and it collapsed two real processes into one.
#
# `semantic` is what behaviour keys on; every label here is the FF's to rename.
PIPELINES = [
    ("Sales", "sales", 0, [
        ("initial_contact_made", "Initial Contact Made", "entry", 0),
        ("prospecting", "Prospecting", "working", 1),
        ("follow_up_needed", "Follow Up Needed", "working", 2),
        ("qualified", "Qualified", "qualified", 3),
        ("consult_given", "Consult Given", "qualified", 4),
        ("proposal_given", "Proposal Given", "qualified", 5),
        ("decision_making", "Decision Making", "qualified", 6),
        ("negotiation", "Negotiation", "qualified", 7),
        ("closed_won", "Closed Won", "won", 8),
        ("closed_lost", "Closed Lost", "lost", 9),
        ("nurture", "Nurture", "parked", 10),
    ]),
    ("Referral partners", "referral", 1, [
        ("new_partner", "New Partner", "entry", 0),
        ("follow_up_sent", "Follow-up Sent", "working", 1),
        ("flyer_sent", "Flyer Sent", "working", 2),
        ("nurturing", "Nurturing", "working", 3),
        ("active_referrer", "Active Referrer", "qualified", 4),
        ("dormant", "Dormant", "parked", 5),
    ]),
]

CONTACT_TYPES = [
    ("prospect", "Prospect", 0),
    ("client", "Client", 1),
    ("referral_partner", "Referral partner", 2),
    ("vendor", "Vendor", 3),
    ("coworker", "Coworker", 4),
]


def seed_tenant(tenant):
    """Idempotent. Safe to call on an already-seeded tenant."""
    from apps.crm.models import ContactType, Pipeline, PipelineStage

    for name, kind, position, stages in PIPELINES:
        pipeline, _ = Pipeline.all_objects.get_or_create(
            tenant=tenant, name=name, defaults={"kind": kind, "position": position},
        )
        for code, label, semantic, stage_position in stages:
            PipelineStage.all_objects.get_or_create(
                tenant=tenant, pipeline=pipeline, code=code,
                defaults={"label": label, "semantic": semantic, "position": stage_position},
            )
    for code, label, position in CONTACT_TYPES:
        ContactType.all_objects.get_or_create(
            tenant=tenant, code=code,
            defaults={"label": label, "position": position},
        )
