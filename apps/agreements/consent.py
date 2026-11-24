"""The words an owner, a countersigner and the signer agree to. Kept by
version: each signature and authorization stores its version and the exact
words shown, so a later wording never changes what was agreed. A new wording
is a new key; old keys are never edited or removed. They name the company,
never the product or the practice (white label)."""

from __future__ import annotations

CURRENT = "2026-11-24"

OWNER = {
    "2026-11-23": (
        "By signing electronically, I agree that my electronic signature is the legal "
        "equivalent of my handwritten signature on this agreement, and I consent to use "
        "electronic records and signatures for it under the U.S. ESIGN Act and UETA. I "
        "understand that I may ask {company} for a paper copy at no charge; that I may withdraw "
        "this consent before I sign by not signing here and asking {company} for a paper "
        "agreement instead, which does not undo anything already signed; that I need a device "
        "that can open PDF files to read and keep this agreement; that a copy of the agreement "
        "will be emailed to {email}; and that I should tell {company} if that email address "
        "changes."),
}
OWNER["2026-11-24"] = OWNER["2026-11-23"]

#: The signer countersigning themselves.
SIGNER = {
    "2026-11-23": (
        "By signing electronically, I agree that my electronic signature is the legal "
        "equivalent of my handwritten signature on this agreement, and that it records my "
        "signature for {company}."),
}
SIGNER["2026-11-24"] = SIGNER["2026-11-23"]

#: Someone applying the signer's signature under the standing authorization.
APPLY = {
    "2026-11-23": (
        "I am applying {principal}'s signature to this agreement for {company}, under "
        "{principal}'s authorization of {authorized_on}. The signing record will show that I "
        "applied it, with my name, the time and my IP address."),
    # Owner, 2026-11-24: name the account that recorded the authorization, not
    # the name in the signature block.
    "2026-11-24": (
        "I am applying {company}'s signature, the one {recorded_by} adopted for the block that "
        "reads \u201c{principal}\u201d, to this agreement, under the authorization {recorded_by} "
        "recorded on {authorized_on}. The signing record will show that I applied it, with my "
        "name, the time and my IP address."),
}

#: The signer's standing authorization.
AUTHORIZATION = {
    "2026-11-23": (
        "I, {principal}, {title} of {company}, adopt the signature shown here as my signature. "
        "I authorize the people named here to apply it, on my behalf and for {company}, to "
        "new-owner rental management agreements once the owner has signed. Each time it is "
        "applied, the signing record will show who applied it, when, from what IP address, and "
        "that it was applied under this authorization. It covers new-owner agreements only. I "
        "may withdraw it at any time; withdrawing it does not undo an agreement already "
        "countersigned."),
    # Owner, 2026-11-24: the account that records it speaks for itself.
    "2026-11-24": (
        "I, {recorded_by}, adopt the signature shown here as {company}'s signature in the block "
        "that reads \u201c{principal}, {title}\u201d. I authorize the people named here to apply "
        "it, on my behalf and for {company}, to new-owner rental management agreements once the "
        "owner has signed. Each time it is applied, the signing record will show who applied "
        "it, when, from what IP address, and that it was applied under this authorization. It "
        "covers new-owner agreements only. I may withdraw it at any time; withdrawing it does "
        "not undo an agreement already countersigned."),
}


def owner(*, company: str, email: str, version: str = CURRENT) -> str:
    return OWNER[version].format(company=company, email=email)


def signer(*, company: str, version: str = CURRENT) -> str:
    return SIGNER[version].format(company=company)


def apply(*, company: str, principal: str, authorized_on: str, recorded_by: str = "",
          version: str = CURRENT) -> str:
    return APPLY[version].format(company=company, principal=principal,
                                 authorized_on=authorized_on, recorded_by=recorded_by)


def authorization(*, company: str, principal: str, title: str, recorded_by: str = "",
                  version: str = CURRENT) -> str:
    return AUTHORIZATION[version].format(company=company, principal=principal, title=title,
                                         recorded_by=recorded_by)
