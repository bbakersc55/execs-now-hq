"""What the app needs that Python will not mention until it is too late.

Almost every third-party import in this codebase is **deferred** — written
inside the function that uses it rather than at the top of its module. That is
deliberate: importing WeasyPrint or the Google client libraries costs real time
at startup, and most requests need none of them. The cost of it is that a
missing package is invisible. Nothing fails at boot; nothing fails in the test
suite, which runs against fakes at exactly those boundaries. It fails the first
time a person uses the feature, in front of whatever they were doing.

That is not hypothetical. Module 5's Drive client imports `googleapiclient`,
which was installed on the laptop and **never added to `requirements.txt`** —
so 1331 tests passed against the fake and the real path died with
`ModuleNotFoundError` the first time a folder was connected.

So the list below names every deferred third-party import in the app, what
provides it, and what stops working without it. Two things use it:

- `config.checks` — `runserver` and `qcluster` import the lot before they
  start, and **refuse to start naming what is missing** rather than beginning
  and failing later.
- `tests/test_runtime_dependencies.py` — imports each one for real, and
  checks each one's distribution is pinned. Installed-but-unpinned is the
  failure that happened, and a test that only imported would have missed it.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Need:
    #: The import as the code writes it.
    module: str
    #: The distribution on PyPI, as `requirements.txt` pins it.
    distribution: str
    #: What stops working without it — in the words the refusal will use.
    why: str


NEEDS: tuple[Need, ...] = (
    Need("anthropic", "anthropic",
         "every Claude call: summaries, strategy map rows, meeting parsing"),
    Need("weasyprint", "weasyprint",
         "the strategy session PDF and the client value report"),
    Need("googleapiclient.discovery", "google-api-python-client",
         "reading the meeting-notes folder in Drive (Module 5)"),
    Need("google.oauth2.credentials", "google-auth",
         "signing Google API calls with the practice's OAuth token"),
    Need("google.oauth2.service_account", "google-auth",
         "the app's own service-account calls to GCS and Speech-to-Text"),
    Need("google.auth.exceptions", "google-auth",
         "telling a dead Google credential apart from a network failure"),
    Need("google.api_core.exceptions", "google-api-core",
         "telling a Google API refusal apart from a network failure"),
    Need("google.cloud.storage", "google-cloud-storage",
         "stored files — note recordings, logos, exported PDFs"),
    Need("google.cloud.speech_v1", "google-cloud-speech",
         "transcribing note recordings (Module 2)"),
    Need("google.resumable_media.common", "google-resumable-media",
         "detecting a corrupted upload to GCS"),
    Need("cryptography.fernet", "cryptography",
         "reading and writing every stored secret, including API keys"),
    Need("requests", "requests",
         "sending mail through Gmail, and the Google OAuth token exchange"),
)


def missing(needs: tuple[Need, ...] = NEEDS) -> list[tuple[Need, Exception]]:
    """Every need that will not import, with the reason it would not.

    Catches `Exception`, not `ImportError`: a package whose native library is
    missing — WeasyPrint without Pango is the usual one — raises `OSError` at
    import, and "it is installed" is no comfort when the PDF still will not
    render. What matters is whether the import the code writes works.
    """
    found = []
    for need in needs:
        try:
            importlib.import_module(need.module)
        except Exception as exc:                        # noqa: BLE001 - the point
            found.append((need, exc))
    return found
