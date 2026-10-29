"""The built-in document templates, and the two default stage rules
(owner, 2026-10-29).

Templates are plain text with merge fields, as email templates are; a line
starting with "# " is a heading. "Restore the original" puts back the words
below. The library is seeded on first sight (`seed_tenant`), so a practice
made before e-signature gets it the first time it opens Settings → Documents.

The rules ("a document is sent: move to Proposal Given"; "a document is
signed: move to Closed Won") are seeded for new practices and the demo only
(`default_rules`). An existing practice adds them from the stage rules'
examples.
"""

from __future__ import annotations

_TERMS = ("# Scope of work\n{Scope}\n\n"
          "# Fee\n{Fee}\n\n"
          "# Term\n{Term}\n\n"
          "# Start date\n{StartDate}\n\n")

#: original key -> (name, title, body). Keys are never reused.
ORIGINALS = {
    "proposal": (
        "Proposal",
        "Proposal",
        "Prepared for {FirstName} {LastName}, {Company}\n"
        "Prepared by {FractionalName}, {PracticeName}, on {Today}\n\n"
        + _TERMS +
        "# Acceptance\n"
        "This proposal is open for 30 days from the date above. Signing it accepts the "
        "work on these terms, and {PracticeName} will confirm the start date with you.",
    ),
    "engagement_letter": (
        "Engagement letter",
        "Engagement letter",
        "{Today}\n\n"
        "Dear {FirstName},\n\n"
        "This letter sets out the terms on which {PracticeName} will work with {Company}.\n\n"
        + _TERMS +
        "# Ending the engagement\n"
        "Either of us may end this engagement with 30 days' written notice. Fees for work "
        "done up to the end date remain due.\n\n"
        "# Confidentiality\n"
        "Each of us will keep the other's confidential information confidential, during "
        "the engagement and after it.\n\n"
        "Signing below confirms {Company}'s agreement to these terms.\n\n"
        "{FractionalName}\n{PracticeName}",
    ),
}


def seed_tenant(tenant) -> list:
    """Idempotent: adds a missing built-in, never rewrites one."""
    from apps.esign.models import DocumentTemplate

    made = []
    for key, (name, title, body) in ORIGINALS.items():
        if DocumentTemplate.all_objects.filter(tenant_id=tenant.pk, original=key).exists():
            continue
        made.append(DocumentTemplate.all_objects.create(
            tenant_id=tenant.pk, name=name, title=title, body=body, original=key))
    return made


#: (trigger, stage code it moves to) on the sales pipeline.
DEFAULT_RULES = (("sent", "proposal_given"), ("signed", "closed_won"))


def default_rules(tenant) -> list:
    """The two default rules on the sales pipeline, unless an equal one is
    there already. For a new practice and the demo."""
    from apps.crm.models import Pipeline, PipelineStage, StageAutomation

    pipeline = Pipeline.all_objects.filter(tenant_id=tenant.pk, kind="sales").first()
    if pipeline is None:
        return []
    made = []
    for position, (trigger, code) in enumerate(DEFAULT_RULES):
        stage = PipelineStage.all_objects.filter(pipeline=pipeline, code=code).first()
        if stage is None:
            continue
        if StageAutomation.all_objects.filter(pipeline=pipeline, trigger=trigger,
                                              action_type="move_stage",
                                              move_to_stage=stage).exists():
            continue
        made.append(StageAutomation.all_objects.create(
            tenant_id=tenant.pk, pipeline=pipeline, trigger=trigger,
            action_type="move_stage", move_to_stage=stage, position=position))
    return made
