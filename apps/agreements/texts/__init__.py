"""The agreements an owner can be sent. Locked: the words live in this folder,
in the repo, and change only by a commit through the gate. Each entry pins its
file's SHA-256; tests/test_agreement_text.py fails when the file and the pin
disagree, and compares the words with the PDF they come from.

A second agreement (the flat-fee "white glove" one) will be a second file and
a second entry, with its own variables.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Template:
    key: str
    title: str
    #: The footer's version line, and its copyright line.
    version: str
    copyright: str
    file: str
    sha256: str
    #: Covered by the signer's standing authorization (new-owner agreements).
    new_owner: bool
    #: The variables staff set before sending.
    variables: tuple[str, ...]
    #: The manager's signature block (change A9).
    signer_name: str = ""
    signer_title: str = ""

    def source(self) -> str:
        return (HERE / self.file).read_text(encoding="utf-8")

    def file_sha256(self) -> str:
        return hashlib.sha256((HERE / self.file).read_bytes()).hexdigest()


TEMPLATES = {
    "rental_management": Template(
        key="rental_management", title="Rental Management Agreement",
        version="V.2 – November 2026", copyright="© Park City Ski Chalets, LLC",
        file="rental_management_v2.txt",
        sha256="33d2a346f607cace407852ea527a4bec2dd73d68a774953eccc4be6a6a1bfd74",
        new_owner=True,
        variables=("split", "fees", "additional_items", "property_address"),
        signer_name="Michael LeClerc", signer_title="President"),
}
DEFAULT = "rental_management"


def get(key: str) -> Template:
    return TEMPLATES[key]
