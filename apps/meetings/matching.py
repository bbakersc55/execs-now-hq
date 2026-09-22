"""Who in the notes is someone we already know (FR-5.10, FR-5.11).

**The order is exactly: email address → email domain + name → name alone**, and
the reason is carried with the candidate so the screen can say *"matched on
email domain + name"* rather than presenting a name and a shrug.

**Nothing here decides anything.** It ranks, it explains, and it always leaves
both paths open — pick a candidate, or reject them all and create new. A match
this module is sure about is still a match a person confirms (R10).
"""

from __future__ import annotations

from apps.crm.models import Contact, ContactEmail

EMAIL = "email"
DOMAIN_AND_NAME = "email_domain_and_name"
NAME_ONLY = "name_only"

#: How much each rule is worth saying out loud. These are the confidences the
#: screen shows; they rank, they do not authorise.
CONFIDENCE = {EMAIL: 0.98, DOMAIN_AND_NAME: 0.71, NAME_ONLY: 0.40}

#: Domains that say nothing about which company somebody belongs to, so
#: "domain + name" on one of them is really "name alone" wearing a hat.
PUBLIC_DOMAINS = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com",
    "yahoo.com", "icloud.com", "me.com", "aol.com", "proton.me", "protonmail.com",
}


def domain_of(email: str) -> str:
    email = (email or "").strip().lower()
    return email.split("@", 1)[1] if "@" in email else ""


def _name_matches(contact, name: str) -> bool:
    full = f"{contact.first_name} {contact.last_name}".strip().lower()
    return bool(name) and full == name.strip().lower()


def candidates_for(tenant, *, name: str = "", email: str = "") -> list[dict]:
    """Ranked existing contacts, best first, each with its reason.

    A contact reached by more than one rule appears once, at its best rank: two
    reasons for the same person is one candidate, not two.
    """
    name = (name or "").strip()
    email = (email or "").strip().lower()
    found: dict[str, dict] = {}

    def add(contact, reason):
        key = str(contact.pk)
        if key in found:
            return
        found[key] = {
            "contact_id": key,
            "name": f"{contact.first_name} {contact.last_name}".strip(),
            "company": contact.company.name if contact.company_id else "",
            "email": contact.primary_email or "",
            "match_reason": reason,
            "confidence": CONFIDENCE[reason],
        }

    # 1. The address itself.
    if email:
        for row in ContactEmail.objects.filter(address__iexact=email).select_related(
                "contact", "contact__company"):
            if row.contact.deleted_at is None:
                add(row.contact, EMAIL)

    # 2. The domain, plus the name. Only for a domain that means something:
    #    "dana@gmail.com" and a matching name is not a company match.
    domain = domain_of(email)
    if domain and domain not in PUBLIC_DOMAINS and name:
        by_domain = ContactEmail.objects.filter(
            address__iendswith=f"@{domain}").select_related("contact", "contact__company")
        for row in by_domain:
            if row.contact.deleted_at is None and _name_matches(row.contact, name):
                add(row.contact, DOMAIN_AND_NAME)

    # 3. The name on its own — offered, ranked last, and never more than that.
    if name:
        parts = name.split()
        first, last = parts[0], (parts[-1] if len(parts) > 1 else "")
        query = Contact.objects.filter(deleted_at__isnull=True, first_name__iexact=first)
        if last:
            query = query.filter(last_name__iexact=last)
        for contact in query.select_related("company")[:10]:
            add(contact, NAME_ONLY)

    ranked = sorted(found.values(), key=lambda row: -row["confidence"])
    for index, row in enumerate(ranked, start=1):
        row["rank"] = index
    return ranked
