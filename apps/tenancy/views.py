"""Staff management and AI spend. Both FF-only (matrix 3.16-3.19)."""

from __future__ import annotations

from django.conf import settings
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.crm.permissions import IsFF, IsTenantStaff
from apps.tenancy import branding, services
from apps.tenancy.models import AiCall, Membership
from apps.tenancy.roles import role_label


class MembershipSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email", read_only=True)
    full_name = serializers.CharField(source="user.full_name", read_only=True)
    is_active = serializers.SerializerMethodField()
    role_label = serializers.SerializerMethodField()

    class Meta:
        model = Membership
        fields = ["id", "email", "full_name", "role", "role_label", "invited_at",
                  "revoked_at", "is_active"]

    def get_is_active(self, obj):
        return obj.revoked_at is None

    def get_role_label(self, obj):
        return role_label(obj.role)


class StaffViewSet(viewsets.ReadOnlyModelViewSet):
    """FR-0.8 — invite, change role, remove. FF only."""

    permission_classes = [IsTenantStaff, IsFF]
    serializer_class = MembershipSerializer

    def get_queryset(self):
        return Membership.objects.select_related("user").filter(
            role__in=["FF", "CF", "VA"]
        ).order_by("role", "user__email")

    def create(self, request):
        try:
            membership = services.invite_member(
                tenant=request.tenant,
                email=request.data.get("email", ""),
                role=request.data.get("role", ""),
                full_name=request.data.get("full_name", ""),
                actor=request.user,
            )
        except services.StaffActionNotPermitted as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(membership).data, status=201)

    @action(detail=True, methods=["post"], url_path="change-role")
    def change_role(self, request, pk=None):
        membership = self.get_object()
        try:
            services.change_role(membership, request.data.get("role"), actor=request.user)
        except services.StaffActionNotPermitted as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(membership).data)

    @action(detail=True, methods=["post"])
    def remove(self, request, pk=None):
        membership = self.get_object()
        report = services.remove_member(membership, actor=request.user)
        membership.refresh_from_db()
        return Response({"member": self.get_serializer(membership).data, "cascade": report})


class AiCallSerializer(serializers.ModelSerializer):
    class Meta:
        model = AiCall
        fields = ["id", "purpose", "model", "input_tokens", "output_tokens",
                  "cost_usd", "trigger", "succeeded", "error", "created_at"]


class AiUsageViewSet(viewsets.ReadOnlyModelViewSet):
    """FR-0.9 — AI spend is FF-only.

    `CLAUDE.md` gives a VA no financials, and a CF's financial visibility is
    limited to assigned clients — which tenant-wide API spend is not.
    """

    permission_classes = [IsTenantStaff, IsFF]
    serializer_class = AiCallSerializer

    def get_queryset(self):
        return AiCall.objects.order_by("-created_at")

    @action(detail=False, methods=["get"])
    def summary(self, request):
        from django.db.models import Count, Sum

        rows = (
            self.get_queryset().values("purpose")
            .annotate(calls=Count("id"), cost=Sum("cost_usd"),
                      input_tokens=Sum("input_tokens"), output_tokens=Sum("output_tokens"))
            .order_by("-cost")
        )
        total = self.get_queryset().aggregate(cost=Sum("cost_usd"), calls=Count("id"))
        return Response({"by_purpose": list(rows), "total": total})


class AnthropicKeyView(viewsets.ViewSet):
    """Assumption E1 — the tenant's Anthropic key. FF only; write-only.

    GET says whether a key is in force and its last four characters. POST
    validates a new key with one free call before it replaces anything; on
    failure the working key is untouched. No response ever contains a key.
    """

    permission_classes = [IsTenantStaff, IsFF]

    def list(self, request):
        from apps.tenancy import claude
        from apps.tenancy.models import SecretKind, TenantSecret

        secret = TenantSecret.objects.filter(
            kind=SecretKind.ANTHROPIC_API_KEY, user__isnull=True
        ).first()
        return Response({
            "source": claude.key_source(request.tenant),
            "last4": secret.last4 if secret else "",
            "verified_at": secret.verified_at if secret else None,
            "rotated_at": secret.rotated_at if secret else None,
            "model": settings.ANTHROPIC_MODEL,
        })

    def create(self, request):
        from apps.tenancy import claude

        try:
            claude.save_key(tenant=request.tenant, key=request.data.get("key", ""),
                            actor=request.user)
        except claude.ClaudeUnavailable as exc:
            return Response({"detail": f"{exc} The existing key, if any, is unchanged."},
                            status=status.HTTP_400_BAD_REQUEST)
        return self.list(request)


class AiBudgetView(viewsets.ViewSet):
    """Credits on the Anthropic account, the monthly budget, and the estimate
    (owner, 2026-09-28). Behind the same FF-only rule as the rest of AI spend
    (FR-0.9): only the FF has the AI usage screen, and only the FF sets these.
    """

    permission_classes = [IsTenantStaff, IsFF]

    def list(self, request):
        from apps.tenancy import ai_budget

        return Response(ai_budget.state(request.tenant))

    def create(self, request):
        """Set what was sent: `credits_usd` with `credits_as_of`, and/or
        `monthly_budget_usd` (null clears the budget)."""
        from datetime import date
        from decimal import Decimal, InvalidOperation

        from django.utils import timezone

        from apps.tenancy import ai_budget
        from apps.tenancy.models import AuditEvent

        tenant = request.tenant
        before = {"credits_usd": str(tenant.ai_credits_usd),
                  "credits_as_of": str(tenant.ai_credits_as_of),
                  "monthly_budget_usd": str(tenant.ai_monthly_budget_usd)}

        def money(value):
            try:
                amount = Decimal(str(value)).quantize(Decimal("0.01"))
            except (InvalidOperation, ValueError):
                return None
            return amount if amount >= 0 else None

        fields = []
        if "credits_usd" in request.data:
            amount = money(request.data.get("credits_usd"))
            try:
                as_of = date.fromisoformat(str(request.data.get("credits_as_of") or "")[:10])
            except ValueError:
                as_of = None
            if amount is None or as_of is None:
                return Response({"detail": "Give the credits on the account as an amount "
                                           "in dollars, and the date you topped up."},
                                status=status.HTTP_400_BAD_REQUEST)
            if as_of > timezone.localdate():
                return Response({"detail": "The top-up date cannot be in the future."},
                                status=status.HTTP_400_BAD_REQUEST)
            tenant.ai_credits_usd, tenant.ai_credits_as_of = amount, as_of
            fields += ["ai_credits_usd", "ai_credits_as_of"]
        if "monthly_budget_usd" in request.data:
            raw = request.data.get("monthly_budget_usd")
            budget = None if raw in (None, "") else money(raw)
            if raw not in (None, "") and budget is None:
                return Response({"detail": "The monthly budget is an amount in dollars."},
                                status=status.HTTP_400_BAD_REQUEST)
            tenant.ai_monthly_budget_usd = budget
            fields.append("ai_monthly_budget_usd")
        if fields:
            tenant.save(update_fields=fields)
            AuditEvent.all_objects.create(
                tenant=tenant, actor=request.user, verb="ai.budget_changed",
                target_type="tenant", target_id=tenant.pk,
                payload={"before": before, "after": {
                    "credits_usd": str(tenant.ai_credits_usd),
                    "credits_as_of": str(tenant.ai_credits_as_of),
                    "monthly_budget_usd": str(tenant.ai_monthly_budget_usd)}})
        return Response(ai_budget.state(tenant))


class AiGuardView(viewsets.ViewSet):
    """The daily cap on unattended AI spend (owner, 2026-09-29). FF only, like
    the rest of AI spend (FR-0.9). The pause itself, without amounts, reaches
    every staff role through the dashboard."""

    permission_classes = [IsTenantStaff, IsFF]

    def list(self, request):
        from apps.tenancy import ai_guard

        return Response(ai_guard.status(request.tenant, financial=True))

    def create(self, request):
        """`daily_cap_usd`: a dollar amount, zero or more. Zero stops all
        unattended AI calls; it is allowed, and said to be allowed."""
        from decimal import Decimal, InvalidOperation

        from apps.tenancy import ai_guard
        from apps.tenancy.models import AuditEvent

        try:
            cap = Decimal(str(request.data.get("daily_cap_usd"))).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            cap = None
        if cap is None or cap < 0:
            return Response({"detail": "The daily limit is an amount in dollars, zero or more."},
                            status=status.HTTP_400_BAD_REQUEST)
        tenant = request.tenant
        before = str(tenant.ai_unattended_daily_cap_usd)
        tenant.ai_unattended_daily_cap_usd = cap
        tenant.save(update_fields=["ai_unattended_daily_cap_usd"])
        AuditEvent.all_objects.create(
            tenant=tenant, actor=request.user, verb="ai.daily_cap_changed",
            target_type="tenant", target_id=tenant.pk,
            payload={"before": before, "after": str(cap)})
        return Response(ai_guard.status(tenant, financial=True))


# ------------------------------------------------------------------ branding

class BrandingSettingsView(APIView):
    """Settings → Branding (P1, 2026-10-02). The practice owner only: an
    associate, an assistant and every client user get 403."""

    permission_classes = [IsTenantStaff, IsFF]

    def get(self, request):
        return Response(branding.current(request.tenant))

    def put(self, request):
        data = request.data
        try:
            branding.save(request.tenant, actor=request.user,
                          display_name=data.get("display_name", ""),
                          primary_color=data.get("primary_color", ""),
                          accent_color=data.get("accent_color", ""),
                          footer_text=data.get("footer_text", ""))
        except branding.BrandingInvalid as exc:
            return Response({"detail": str(exc), "errors": exc.errors}, status=400)
        return Response(branding.current(request.tenant))


class BrandingImageView(APIView):
    """Upload (multipart `file`) or clear the logo or the mark."""

    permission_classes = [IsTenantStaff, IsFF]

    def post(self, request, kind):
        upload = request.FILES.get("file")
        if upload is None:
            return Response({"detail": "Choose a file."}, status=400)
        if upload.size > branding.IMAGE_MAX_BYTES:
            return Response({"detail": f"The file is {upload.size // 1024} KB; the limit is "
                                       f"{branding.IMAGE_MAX_BYTES // 1024} KB."}, status=400)
        try:
            shown = branding.set_image(request.tenant, actor=request.user, kind=kind,
                                       content=upload.read())
        except branding.BrandingInvalid as exc:
            return Response({"detail": str(exc), "errors": exc.errors}, status=400)
        return Response({**branding.current(request.tenant), "uploaded": shown})

    def delete(self, request, kind):
        branding.clear_image(request.tenant, actor=request.user, kind=kind)
        return Response(branding.current(request.tenant))


class BrandingResetView(APIView):
    permission_classes = [IsTenantStaff, IsFF]

    def post(self, request):
        branding.reset(request.tenant, actor=request.user)
        return Response(branding.current(request.tenant))
