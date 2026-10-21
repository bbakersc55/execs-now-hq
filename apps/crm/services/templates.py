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

#: (field, what it is). The first seven work anywhere; the last two only where
#: they mean something, and read as nothing elsewhere.
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
)
NAMES = tuple(name for name, _ in FIELDS)
_FIELD = re.compile(r"\{([A-Za-z][A-Za-z ]*)\}")
DEFAULT_FALLBACK = "there"
FLYER_NOTE = "I've attached a short overview of what we do, so you know what to look out for."

#: What a preview shows when no one is chosen: a visible placeholder.
PLACEHOLDERS = {
    "FirstName": "[First name]", "LastName": "[Last name]", "Company": "[Company]",
    "FractionalName": "[Your name]", "PracticeName": "[Practice name]",
    "PracticeNews": "[What you're working on lately]", "FeeTerms": "[Fee terms]",
    "ProspectName": "[Who they referred]", "FlyerNote": "[The flyer line]",
}


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
        **extra,
    }


def render(text: str, values: dict, *, fallback: str = DEFAULT_FALLBACK,
           drop_empty_lines: bool = True) -> str:
    """Each field replaced; a field this email has no value for reads as
    nothing, and {FirstName} as the fallback."""
    fallback = (fallback or "").strip() or DEFAULT_FALLBACK

    def value(name):
        got = values.get(name, "")
        return fallback if name == "FirstName" and not got else got

    def line_of(line):
        known = [f for f in _FIELD.findall(line) if f in NAMES]
        merged = _FIELD.sub(lambda m: value(m.group(1)) if m.group(1) in NAMES
                            else m.group(0), line)
        if drop_empty_lines and known and not any(value(f) for f in known):
            return None
        return merged

    lines = [line_of(line) for line in (text or "").split("\n")]
    out = "\n".join(line for line in lines if line is not None)
    return re.sub(r"\n{3,}", "\n\n", out).strip("\n")


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
