"""Staff management and AI spend. Both FF-only (matrix 3.16-3.19)."""

from __future__ import annotations

from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.crm.permissions import IsFF, IsTenantStaff
from apps.tenancy import services
from apps.tenancy.models import AiCall, Membership


class MembershipSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email", read_only=True)
    full_name = serializers.CharField(source="user.full_name", read_only=True)
    is_active = serializers.SerializerMethodField()

    class Meta:
        model = Membership
        fields = ["id", "email", "full_name", "role", "invited_at",
                  "revoked_at", "is_active"]

    def get_is_active(self, obj):
        return obj.revoked_at is None


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
