"""Print a new VAPID key pair for browser notifications (2026-10-26).

Writes nothing: the two lines are pasted into `.env` on the laptop, or into
the service's variables on Railway. Each environment has its own pair.
"""

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.core.management.base import BaseCommand


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


class Command(BaseCommand):
    help = "Print a new VAPID key pair (VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY)."

    def handle(self, *args, **options):
        key = ec.generate_private_key(ec.SECP256R1())
        private = key.private_numbers().private_value.to_bytes(32, "big")
        public = key.public_key().public_bytes(serialization.Encoding.X962,
                                               serialization.PublicFormat.UncompressedPoint)
        self.stdout.write(f"VAPID_PUBLIC_KEY={_b64(public)}")
        self.stdout.write(f"VAPID_PRIVATE_KEY={_b64(private)}")
