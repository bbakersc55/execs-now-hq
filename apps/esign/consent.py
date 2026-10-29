"""The consent line a signer ticks before signing (owner, 2026-10-29).

Kept by version: each signature stores the version it was given and the
words exactly as shown, so changing the wording later never changes what an
earlier signer agreed to. A new wording is a new key, and `CURRENT` moves to
it; old keys are never edited or removed.
"""

from __future__ import annotations

#: version -> wording. `{practice}` and `{email}` are filled when shown.
VERSIONS = {
    "2026-10-29": (
        "By signing electronically, I agree that my electronic signature is the legal "
        "equivalent of my handwritten signature on this document, and I consent to use "
        "electronic records and signatures for it under the U.S. ESIGN Act and UETA. "
        "I understand that I may ask {practice} for a paper copy at no charge; that I may "
        "withdraw this consent before I sign by choosing Decline instead, which ends "
        "electronic signing of this document but does not undo anything already signed; "
        "that I need a device that can open PDF files to read and keep this document; "
        "that a copy of the signed document will be emailed to {email}; and that I should "
        "tell {practice} if that email address changes."
    ),
}
CURRENT = "2026-10-29"


#: The practice's own countersignature: a shorter line, shown on the company
#: card, kept under the same version key with its own words.
COUNTERSIGN = {
    "2026-10-29": (
        "By signing electronically, I agree that my electronic signature is the legal "
        "equivalent of my handwritten signature on this document, and that it records my "
        "countersignature for {practice}."
    ),
}


def wording(*, practice: str, email: str, version: str = CURRENT) -> str:
    return VERSIONS[version].format(practice=practice, email=email)


def countersign_wording(*, practice: str, version: str = CURRENT) -> str:
    return COUNTERSIGN[version].format(practice=practice)
