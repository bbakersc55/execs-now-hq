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
        return self.memberships.filter(revoked_at__isnull=True).first()


def _hash_token(raw: str) -> str:
    """Store only the hash; a database read never yields a working credential."""
    return hashlib.sha256(raw.encode()).hexdigest()


class MagicLinkPurpose(models.TextChoices):
    SIGNIN = "signin", "Sign in"
    PIN_RESET = "pin_reset", "Note PIN reset"


class MagicLinkToken(TenantScopedModel):
    """Single-use, hashed, 20-minute (assumption C3).

    The raw token exists only in the email. Consuming one invalidates every
    other outstanding token for that user.
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
            expires_at=timezone.now() + MAGIC_LINK_TTL,
            redirect_to=redirect_to, requested_ip=requested_ip,
        )
        return token, raw

    @classmethod
    def resolve(cls, raw: str, purpose=MagicLinkPurpose.SIGNIN):
        return (
            cls.all_objects.select_related("user", "tenant")
            .filter(
                token_hash=_hash_token(raw), purpose=purpose,
                used_at__isnull=True, expires_at__gt=timezone.now(),
            )
            .first()
        )

    def consume(self):
        self.used_at = timezone.now()
        self.save(update_fields=["used_at", "updated_at"])

    @property
    def is_valid(self):
        return self.used_at is None and self.expires_at > timezone.now()
