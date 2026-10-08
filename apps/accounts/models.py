"""Identity. Tenant staff and client portal users share one User table."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import timedelta

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone

from apps.tenancy.models import TenantScopedModel

MAGIC_LINK_TTL = timedelta(minutes=20)  # C3.2
#: A portal invitation is read when the person gets to it, not while they are
#: waiting for it, so it lasts a week. A link someone asks for stays short.
INVITATION_TTL = timedelta(days=7)
STAKEHOLDER_TOKEN_TTL = timedelta(days=30)  # FR-3.33b


class UserManager(BaseUserManager):
    def create_user(self, email, full_name="", **extra):
        if not email:
            raise ValueError("Email is required")
        user = self.model(email=self.normalize_email(email), full_name=full_name, **extra)
        # C4: no passwords anywhere in Beta.
        user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        user = self.model(email=self.normalize_email(email), **extra)
        # The local `createsuperuser` account is the one exception to C4.
        user.set_password(password)
        user.save(using=self._db)
        return user


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=200, blank=True, default="")
    timezone = models.CharField(max_length=64, blank=True, default="")
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    #: P2: may open the Practices area. Set only by `manage.py
    #: set_platform_owner`; no screen or API writes it. Grants **no** access
    #: inside any practice (apps/platform/README in docs/p2…).
    is_platform_owner = models.BooleanField(default=False, db_default=False)
    last_login_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "app_user"

    def __str__(self):
        return self.email

    @property
    def membership(self):
        """The user's live membership, or None.

        Uses `all_objects` deliberately: a User is NOT tenant-scoped, and this
        property is what DETERMINES the tenant — so it necessarily runs before a
        tenant is bound. Going through the fail-closed reverse manager raised
        TenantContextMissing during magic-link login, which is exactly the
        moment nothing is bound yet.

        Third instance of this defect class (after Company.seats_in_use and
        Contact.primary_email); found by the property audit in Phase 1.
        """
        from apps.tenancy.models import Membership

        return (
            Membership.all_objects.select_related("tenant")
            .filter(user=self, revoked_at__isnull=True)
            .exclude(tenant__status="archived")
            .first()
        )


def _hash_token(raw: str) -> str:
    """Store only the hash; a database read never yields a working credential."""
    return hashlib.sha256(raw.encode()).hexdigest()


class MagicLinkPurpose(models.TextChoices):
    SIGNIN = "signin", "Sign in"
    INVITE = "invite", "Portal invitation"
    PIN_RESET = "pin_reset", "Note PIN reset"


#: The purposes that sign a person in. An invitation is a sign-in link with a
#: longer life; a PIN reset never signs anyone in.
SIGN_IN_PURPOSES = (MagicLinkPurpose.SIGNIN, MagicLinkPurpose.INVITE)
_TTL = {MagicLinkPurpose.INVITE: INVITATION_TTL}


class MagicLinkToken(TenantScopedModel):
    """Single-use and hashed (assumption C3). 20 minutes, except a portal
    invitation, which lasts `INVITATION_TTL`.

    The raw token exists only in the email. Issuing one invalidates every
    other outstanding token of its purpose for that user, and signing in with
    one invalidates every other sign-in token they hold (`spend_sign_in_links`).
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="magic_links")
    token_hash = models.CharField(max_length=64, db_index=True)
    purpose = models.CharField(
        max_length=16, choices=MagicLinkPurpose.choices, default=MagicLinkPurpose.SIGNIN
    )
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    requested_ip = models.GenericIPAddressField(null=True, blank=True)
    redirect_to = models.CharField(max_length=500, blank=True, default="")

    class Meta(TenantScopedModel.Meta):
        db_table = "magic_link_token"

    @classmethod
    def issue(cls, *, tenant, user, purpose=MagicLinkPurpose.SIGNIN,
              redirect_to="", requested_ip=None):
        raw = secrets.token_urlsafe(32)
        cls.all_objects.filter(
            tenant=tenant, user=user, purpose=purpose, used_at__isnull=True
        ).update(used_at=timezone.now())
        token = cls.all_objects.create(
            tenant=tenant, user=user, token_hash=_hash_token(raw), purpose=purpose,
            expires_at=timezone.now() + _TTL.get(purpose, MAGIC_LINK_TTL),
            redirect_to=redirect_to, requested_ip=requested_ip,
        )
        return token, raw

    @classmethod
    def resolve(cls, raw: str, purpose=MagicLinkPurpose.SIGNIN):
        """The live token for `raw`, or None. `purpose` is one or several."""
        purposes = [purpose] if isinstance(purpose, str) else list(purpose)
        return (
            cls.all_objects.select_related("user", "tenant")
            .filter(
                token_hash=_hash_token(raw), purpose__in=purposes,
                used_at__isnull=True, expires_at__gt=timezone.now(),
            )
            .first()
        )

    @classmethod
    def find_sign_in(cls, raw: str):
        """The sign-in token for `raw` in any state — used, expired or live.

        For the page a dead link lands on, which says what kind of link it was.
        It authorises nothing: only `resolve` answers whether a link works.
        """
        return (
            cls.all_objects.select_related("user", "tenant")
            .filter(token_hash=_hash_token(raw), purpose__in=SIGN_IN_PURPOSES)
            .first()
        )

    @classmethod
    def spend_sign_in_links(cls, *, tenant_id, user_id) -> int:
        """End every sign-in link this person still holds. Once they are in, a
        week-long invitation left in an inbox should not also work."""
        return cls.all_objects.filter(
            tenant_id=tenant_id, user_id=user_id, purpose__in=SIGN_IN_PURPOSES,
            used_at__isnull=True,
        ).update(used_at=timezone.now())

    def consume(self):
        self.used_at = timezone.now()
        self.save(update_fields=["used_at", "updated_at"])

    @property
    def is_valid(self):
        return self.used_at is None and self.expires_at > timezone.now()
