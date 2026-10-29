"""The template library's one renderer (owner, 2026-10-20).

Every place that drafts an email from the practice's words comes through
here: stage rules, referral touches, a new partner's first email, the
referral thank-yous and the bulk "Email these contacts". Campaigns start from
a template by copying it, and merge with the same fields.

**One merge-field style everywhere:** `{FirstName}`, as campaigns had it. A
missing first name reads as the template's fallback ("Hi there,"). Unknown
fields are refused when a template is saved, so nothing goes out with a
`{Typo}` in it.

Templates are plain text. **A line made only of merge fields that came out
empty is left out**, so "{PracticeNews}" or "…arrangement: {FeeTerms}." with
nothing to say leaves no gap. **The signature is never in a template:**
`compose` adds the sender's, once, so the draft in the Outbox reads exactly as
it will land.
"""

from __future__ import annotations

import re

#: (field, what it is). The first seven work anywhere; the last three only
#: where they mean something, and read as nothing elsewhere. {PayLink} is
#: filled by the invoice email (`apps/billing/services.with_pay_link`).
FIELDS = (
    ("FirstName", "First name"),
    ("LastName", "Last name"),
    ("Company", "Company"),
    ("FractionalName", "Your name"),
    ("PracticeName", "The practice's name"),
    ("PracticeNews", "What you're working on lately (Referral settings)"),
    ("FeeTerms", "Their referral fee terms"),
    ("ProspectName", "Who they referred (thank-yous)"),
    ("FlyerNote", "A line saying the flyer is attached (new partner's email)"),
    ("PayLink", "The invoice's payment link (invoice emails)"),
    # R3: an introduction, written to one person about the other.
    ("OtherName", "Who they're being introduced to (introductions)"),
    ("OtherFirstName", "Their first name (introductions)"),
    ("OtherCompany", "Their company (introductions)"),
    ("OtherDiscipline", "Their discipline, like Fractional CMO (introductions)"),
    ("OtherSpecialties", "Their specialties (introductions)"),
    ("IntroNote", "Why you're introducing them (introductions)"),
    # How each person is spoken of (owner, 2026-10-24): pronouns from the
    # contact's page (unset reads as they), their specialties, and "How I'd
    # introduce them". A pronoun that starts a sentence gets its capital.
    ("HeShe", "He, she or they"), ("HimHer", "Him, her or them"),
    ("HisHer", "His, her or their"),
    ("Specialties", "Their specialties"),
    ("Blurb", "How you'd introduce them (their contact page)"),
    ("OtherHeShe", "He, she or they, for who they're meeting (introductions)"),
    ("OtherHimHer", "Him, her or them, for who they're meeting (introductions)"),
    ("OtherHisHer", "His, her or their, for who they're meeting (introductions)"),
    ("OtherBlurb", "How you'd introduce who they're meeting (introductions)"),
    # E-signature (owner, 2026-10-29): what the company's latest signed
    # document says, and its goals, for the welcome letter.
    ("Scope", "The scope in their latest signed document"),
    ("Fee", "The fee in their latest signed document"),
    ("Term", "The term in their latest signed document"),
    ("StartDate", "The start date in their latest signed document"),
    ("Goals", "Their company's goals, one a line"),
)
NAMES = tuple(name for name, _ in FIELDS)
_FIELD = re.compile(r"\{([A-Za-z][A-Za-z ]*)\}")
DEFAULT_FALLBACK = "there"
FLYER_NOTE = "I've attached a short overview of what we do, so you know what to look out for."

#: The fields that have a value in one kind of email only, and where. Anywhere
#: else they read as blank, so a composer offers them greyed (finding T5).
ONLY_IN = {
    "ProspectName": "only in referral thank-yous",
    "FlyerNote": "only in a new partner's first email",
    "PayLink": "only in invoice emails",
    "OtherName": "only in introductions", "OtherFirstName": "only in introductions",
    "OtherCompany": "only in introductions", "OtherDiscipline": "only in introductions",
    "OtherSpecialties": "only in introductions", "IntroNote": "only in introductions",
    "OtherHeShe": "only in introductions", "OtherHimHer": "only in introductions",
    "OtherHisHer": "only in introductions", "OtherBlurb": "only in introductions",
    "Scope": "only once their company has signed a document",
    "Fee": "only once their company has signed a document",
    "Term": "only once their company has signed a document",
    "StartDate": "only once their company has signed a document",
}

#: What a preview shows when no one is chosen: a visible placeholder.
PLACEHOLDERS = {
    "FirstName": "[First name]", "LastName": "[Last name]", "Company": "[Company]",
    "FractionalName": "[Your name]", "PracticeName": "[Practice name]",
    "PracticeNews": "[What you're working on lately]", "FeeTerms": "[Fee terms]",
    "ProspectName": "[Who they referred]", "FlyerNote": "[The flyer line]",
    "PayLink": "[The invoice's payment link]",
    "OtherName": "[Who they're meeting]", "OtherFirstName": "[Their first name]",
    "OtherCompany": "[Their company]", "OtherDiscipline": "[Their discipline]",
    "OtherSpecialties": "[Their specialties]", "IntroNote": "[Why you're introducing them]",
    "HeShe": "[he/she/they]", "HimHer": "[him/her/them]", "HisHer": "[his/her/their]",
    "Specialties": "[Their specialties]", "Blurb": "[How you'd introduce them]",
    "OtherHeShe": "[he/she/they]", "OtherHimHer": "[him/her/them]",
    "OtherHisHer": "[his/her/their]", "OtherBlurb": "[How you'd introduce who they're meeting]",
    "Scope": "[The signed scope]", "Fee": "[The signed fee]", "Term": "[The signed term]",
    "StartDate": "[The signed start date]", "Goals": "[Their goals]",
}

#: A contact's pronouns as (HeShe, HimHer, HisHer); unset reads as they.
PRONOUNS = {"he": ("he", "him", "his"), "she": ("she", "her", "her"),
            "": ("they", "them", "their")}
PRONOUN_FIELDS = ("HeShe", "HimHer", "HisHer", "OtherHeShe", "OtherHimHer", "OtherHisHer")


def pronoun_values(contact, prefix="") -> dict:
    he, him, his = PRONOUNS.get(getattr(contact, "pronouns", "") or "", PRONOUNS[""]) \
        if contact is not None else PRONOUNS[""]
    return {f"{prefix}HeShe": he, f"{prefix}HimHer": him, f"{prefix}HisHer": his}


class TemplateRefused(Exception):
    pass


def unknown_fields(text: str) -> list[str]:
    return sorted({f for f in _FIELD.findall(text or "") if f not in NAMES})


def check(*texts: str) -> None:
    unknown = sorted({f for text in texts for f in unknown_fields(text)})
    if unknown:
        raise TemplateRefused(
            "There is no merge field called " + ", ".join(f"{{{f}}}" for f in unknown)
            + ". The ones you can use: " + ", ".join(f"{{{f}}}" for f in NAMES) + ".")


def values_for(contact, *, tenant, sender=None, **extra) -> dict:
    """What each field becomes for one person. `extra` fills the fields that
    belong to one email (ProspectName, FlyerNote)."""
    company = contact.company if contact is not None and contact.company_id else None
    return {
        "FirstName": (contact.first_name or "").strip() if contact else "",
        "LastName": (contact.last_name or "").strip() if contact else "",
        "Company": company.name if company else "",
        "FractionalName": (getattr(sender, "full_name", "") or "").strip() if sender else "",
        "PracticeName": tenant.name,
        "PracticeNews": (tenant.referral_blurb or "").strip(),
        "FeeTerms": (contact.referral_fee_terms or "").strip() if contact else "",
        "ProspectName": "",
        "FlyerNote": "",
        "OtherName": "", "OtherFirstName": "", "OtherCompany": "", "OtherDiscipline": "",
        "OtherSpecialties": "", "IntroNote": "",
        **pronoun_values(contact),
        "Specialties": ", ".join(contact.specialties or []) if contact else "",
        "Blurb": (contact.intro_blurb or "").strip() if contact else "",
        **pronoun_values(None, "Other"), "OtherBlurb": "",
        **_signed_values(contact),
        **extra,
    }


def _signed_values(contact) -> dict:
    from apps.esign.services import welcome_values

    return welcome_values(contact)


#: The fields whose whole line goes when they have nothing to say ("{PracticeNews}",
#: "…arrangement: {FeeTerms}.", "{FlyerNote}", "Pay here: {PayLink}"). Any other
#: field with no value reads as blank where it stands, and its line stays.
LINE_FIELDS = ("PracticeNews", "FeeTerms", "FlyerNote", "PayLink", "OtherCompany",
               "OtherDiscipline", "OtherSpecialties", "IntroNote", "Specialties", "Blurb",
               "OtherBlurb", "Scope", "Fee", "Term", "StartDate", "Goals")


def render(text: str, values: dict, *, fallback: str = DEFAULT_FALLBACK,
           drop_empty_lines: bool = True) -> str:
    """Each field replaced; a field this email has no value for reads as
    nothing, and {FirstName} as the fallback.

    Never empty when there were words to send (finding T5, 2026-10-22): a
    {ProspectName} outside a thank-you once took its whole line with it, and a
    one-paragraph email came out blank. Now only the line fields leave their
    line, and if that would leave nothing, nothing is left out."""
    fallback = (fallback or "").strip() or DEFAULT_FALLBACK

    def value(name):
        got = values.get(name, "")
        return fallback if name == "FirstName" and not got else got

    def merge(m, line):
        name = m.group(1)
        if name not in NAMES:
            return m.group(0)
        got = value(name)
        if name in PRONOUN_FIELDS and got:
            # "She'd be glad…": a pronoun that starts a sentence is capitalised.
            before = line[:m.start()].rstrip()
            if not before or before[-1] in ".!?":
                got = got[0].upper() + got[1:]
        return got

    def line_of(line, dropping):
        known = [f for f in _FIELD.findall(line) if f in NAMES]
        merged = _FIELD.sub(lambda m: merge(m, line), line)
        # A pronoun always has a value but says nothing on its own, so it
        # doesn't hold open a line whose facts are missing.
        facts = [f for f in known if f not in PRONOUN_FIELDS]
        if (dropping and facts and all(f in LINE_FIELDS for f in facts)
                and not any(value(f) for f in facts)):
            return None
        return merged

    def whole(dropping):
        lines = [line_of(line, dropping) for line in (text or "").split("\n")]
        out = "\n".join(line for line in lines if line is not None)
        return re.sub(r"\n{3,}", "\n\n", out).strip("\n")

    out = whole(drop_empty_lines)
    if drop_empty_lines and not out.strip() and (text or "").strip():
        out = whole(False)
    return out


def empty_fields(values: dict, *texts: str) -> list[str]:
    """The fields these words use that have nothing in this email ({FirstName}
    is never one: it has its fallback). What a preview names."""
    used = {f for text in texts for f in _FIELD.findall(text or "") if f in NAMES}
    return [name for name in NAMES
            if name in used and name != "FirstName" and not values.get(name)]


def render_subject(text: str, values: dict, *, fallback: str = DEFAULT_FALLBACK) -> str:
    return " ".join(render(text, values, fallback=fallback, drop_empty_lines=False).split())


def with_signature(body: str, tenant, actor) -> str:
    """The sender's signature at the end, once."""
    from apps.crm.services import sender as sender_service

    signature_text, _ = sender_service.signature(tenant, actor)
    body = (body or "").rstrip()
    if signature_text and not body.endswith(signature_text.strip()):
        body = f"{body}\n\n{signature_text}" if body else signature_text
    return body


def compose(template, contact, *, actor=None, **extra) -> tuple[str, str]:
    """`(subject, body)` for one person, merged and signed. `extra` fills
    ProspectName and FlyerNote."""
    values = values_for(contact, tenant=template.tenant, sender=actor, **extra)
    fallback = template.first_name_fallback
    subject = render_subject(template.subject, values, fallback=fallback)
    body = render(template.body, values, fallback=fallback)
    return subject, with_signature(body, template.tenant, actor)


def for_use(tenant, use):
    """The template the practice has chosen for a use, seeding the library
    first if this practice has never had one."""
    from apps.crm import template_seed
    from apps.crm.models import EmailTemplateUse

    row = EmailTemplateUse.all_objects.filter(tenant=tenant, use=use).select_related(
        "template").first()
    if row is None:
        template_seed.seed_tenant(tenant)
        row = EmailTemplateUse.all_objects.filter(tenant=tenant, use=use).select_related(
            "template").first()
    return row.template if row else None


def is_changed(template) -> bool:
    from apps.crm import template_seed

    original = template_seed.ORIGINALS.get(template.original)
    if original is None:
        return False
    _name, subject, body = original
    return (template.subject, template.body, template.first_name_fallback) != (
        subject, body, DEFAULT_FALLBACK)


def restore(template, *, actor=None):
    """"Restore the original": the built-in wording back, the name kept."""
    from apps.crm import template_seed
    from apps.tenancy.models import AuditEvent

    original = template_seed.ORIGINALS.get(template.original)
    if original is None:
        raise TemplateRefused("Only a built-in template has an original to restore.")
    _name, template.subject, template.body = original
    template.first_name_fallback = DEFAULT_FALLBACK
    template.save(update_fields=["subject", "body", "first_name_fallback", "updated_at"])
    AuditEvent.all_objects.create(
        tenant=template.tenant, actor=actor, verb="email_template.restored",
        target_type="email_template", target_id=template.pk,
        payload={"original": template.original})
    return template


def used_for(template) -> list[str]:
    """Where a template is in use, in words, for the library page and for
    refusing a delete."""
    from apps.crm.models import Contact, EmailTemplateUse, StageAutomation

    out = [EmailTemplateUse.Use(row.use).label
           for row in EmailTemplateUse.all_objects.filter(template=template)]
    rules = StageAutomation.all_objects.filter(email_template=template).count()
    if rules:
        out.append(f"{rules} stage rule{'s' if rules != 1 else ''}")
    partners = Contact.all_objects.filter(referral_template=template,
                                          deleted_at__isnull=True).count()
    if partners:
        out.append(f"the touch for {partners} partner{'s' if partners != 1 else ''}")
    return out
