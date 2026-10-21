"""Each practice's template library, seeded with the words the app used before
the library (owner, 2026-10-20).

Until then these emails were written in code: the referral touch, a new
partner's first email, and the three referral thank-yous. Each is now a
built-in template the practice can rewrite, and "Restore the original" puts
back the wording below. The signature is not in any of them: the draft adds
it, so a template never signs as the wrong person.

Two departures from the old code, both because a template has no `if`:
- **A line that is only empty merge fields is left out.** The touch's fee
  reminder had been written only when the partner has terms; it is now a line
  around `{FeeTerms}` that drops out when there are none, and the same holds
  for the blurb.
- **The onboarding opening** was one of two sentences depending on whether a
  flyer was attached. It is now one sentence and `{FlyerNote}`, a line that
  says the flyer is attached, or is left out when there is none.

The data migration seeds practices that already exist; `seed_tenant` covers
every practice created afterwards, the same split the CRM seed uses.
"""

from __future__ import annotations

RECIPROCAL = ("If there's a type of introduction that would help you right now, "
              "tell me and I'll keep an eye out.")

#: original key -> (name, subject, body). Keys are never reused.
ORIGINALS = {
    "referral_touch": (
        "Referral touch",
        "Checking in from {PracticeName}",
        "Hi {FirstName},\n\n"
        "{PracticeNews}\n"
        "As a reminder of our arrangement: {FeeTerms}.\n"
        f"{RECIPROCAL}",
    ),
    "referral_onboarding": (
        "New referral partner",
        "Good to meet you",
        "Hi {FirstName},\n\n"
        "Great to meet you, and good to know what you're working on.\n"
        "{FlyerNote}\n\n"
        "If there's a type of introduction that would help you, tell me and "
        "I'll keep an eye out.",
    ),
    "thanks_recorded": (
        "Referral thank-you: recorded",
        "Thank you for the introduction",
        "Hi {FirstName},\n\n"
        "Thank you for introducing me to {ProspectName}. I'll take good care of them, "
        "and I'll let you know how it goes.",
    ),
    "thanks_won": (
        "Referral thank-you: won",
        "Good news, and thank you",
        "Hi {FirstName},\n\n"
        "Good news: {ProspectName} has decided to work with us. Thank you for the "
        "introduction; it means a lot.",
    ),
    "thanks_lost": (
        "Referral thank-you: lost",
        "A quick update, and thank you",
        "Hi {FirstName},\n\n"
        "A quick update on {ProspectName}: it didn't turn into an engagement this time. "
        "Thank you all the same for thinking of me. I appreciate every introduction.",
    ),
}

#: use -> the original it starts on.
USES = {
    "referral_touch": "referral_touch",
    "referral_onboarding": "referral_onboarding",
    "thanks_recorded": "thanks_recorded",
    "thanks_won": "thanks_won",
    "thanks_lost": "thanks_lost",
}


def seed_tenant(tenant, *, apps=None, dry_run=False) -> list[str]:
    """Idempotent: adds only what is missing, never rewrites a template.

    A use already pointing somewhere is left alone. A practice that wrote its
    own onboarding template before the library keeps it as that use (it is
    what the app sent), with the original seeded beside it to restore from.
    Returns a line per thing done, or that would be done with `dry_run`.

    `apps` is the migration's historical registry when called from one, and
    the live models otherwise.
    """
    if apps is None:
        from apps.crm.models import EmailTemplate, EmailTemplateUse
    else:
        EmailTemplate = apps.get_model("crm", "EmailTemplate")
        EmailTemplateUse = apps.get_model("crm", "EmailTemplateUse")
    # The live models' `objects` is scoped to a bound practice; a historical
    # model's is plain.
    templates = EmailTemplate.all_objects if apps is None else EmailTemplate.objects
    uses = EmailTemplateUse.all_objects if apps is None else EmailTemplateUse.objects

    done = []
    originals = {}
    for key, (name, subject, body) in ORIGINALS.items():
        row = templates.filter(tenant_id=tenant.pk, original=key).first()
        if row is None:
            done.append(f"add template “{name}”")
            if not dry_run:
                row = templates.create(
                    tenant_id=tenant.pk, name=name, kind="general", subject=subject,
                    body=body, original=key)
        originals[key] = row

    for use, key in USES.items():
        if uses.filter(tenant_id=tenant.pk, use=use).exists():
            continue
        template = originals[key]
        if use == "referral_onboarding":
            own = (templates.filter(tenant_id=tenant.pk, kind="referral_onboarding")
                   .order_by("created_at").first())
            if own is not None:
                template = own
        done.append(f"use “{template.name if template else ORIGINALS[key][0]}” for {use}")
        if not dry_run:
            uses.create(tenant_id=tenant.pk, use=use, template=template)
    return done


def touch_modes(*, apps=None, dry_run=False) -> int:
    """The old "AI-drafted" touch was this fixed wording, so every partner on
    it moves to "My template", which now holds the same words."""
    if apps is None:
        from apps.crm.models import Contact
    else:
        Contact = apps.get_model("crm", "Contact")
    manager = Contact.all_objects if apps is None else Contact.objects
    rows = manager.filter(referral_touch_mode="ai")
    return rows.count() if dry_run else rows.update(referral_touch_mode="template")
