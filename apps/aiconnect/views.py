"""The app's own screens for AI apps and AI actions (P7, docs/p7_mcp.md).

- `/api/ai/connections/` — Profile, "Connected AI apps": your own.
- `/api/ai/apps/` — Settings → AI, "AI apps": the connector URL and, for the
  practice owner, every connected app in the practice.
- `/api/ai/connections/<id>/revoke` — yours, or any in the practice for its
  owner.
- `/api/ai/actions/` — Settings → AI, "Actions": every AI action, where it
  runs and on which tier. Read by all staff (the screens swap a button for
  "Do this in your AI"); changed by the practice owner.
- `/api/platform/model-tiers` — the platform owner's tier table.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.conf import settings
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.aiconnect.models import AiAppConnection
from apps.aiconnect.oauth import revoke_connection
from apps.crm import permissions as crm_perms
from apps.tenancy import ai_actions
from apps.tenancy.models import AiActionSetting
from apps.tenancy.roles import role_label


def _row(c) -> dict:
    name = (c.user.full_name or c.user.email) if c.user_id else ""
    return {"id": str(c.pk), "app": c.app_name, "connected_at": c.created_at,
            "last_used_at": c.last_used_at, "person": name, "role": role_label(c.role)}


class MyConnections(APIView):
    permission_classes = [permissions.IsAuthenticated, crm_perms.IsTenantStaff]

    def get(self, request):
        rows = (AiAppConnection.objects.filter(user=request.user, revoked_at__isnull=True)
                .select_related("user"))
        return Response([_row(c) for c in rows])


class PracticeApps(APIView):
    permission_classes = [permissions.IsAuthenticated, crm_perms.IsTenantStaff]

    def get(self, request):
        owner = crm_perms.role_of(request) == crm_perms.Role.FF
        rows = AiAppConnection.objects.filter(revoked_at__isnull=True).select_related("user")
        if not owner:
            rows = rows.filter(user=request.user)
        return Response({"connector_url": settings.MCP_RESOURCE_URL,
                         "everyone": owner, "connections": [_row(c) for c in rows]})


class RevokeConnection(APIView):
    permission_classes = [permissions.IsAuthenticated, crm_perms.IsTenantStaff]

    def post(self, request, pk):
        connection = AiAppConnection.objects.filter(pk=pk, revoked_at__isnull=True).first()
        owner = crm_perms.role_of(request) == crm_perms.Role.FF
        if connection is None or (connection.user_id != request.user.pk and not owner):
            return Response({"detail": "No connected AI app with that id."}, status=404)
        revoke_connection(connection, by=request.user, reason="revoked in the app")
        return Response({"revoked": True})


class Actions(APIView):
    permission_classes = [permissions.IsAuthenticated, crm_perms.IsTenantStaff]

    def get(self, request):
        return Response({"actions": ai_actions.table(request.tenant.pk),
                         "tiers": [{"code": t, "label": t.title(),
                                    "model": ai_actions.tier_row(t).model}
                                   for t in ai_actions.TIERS],
                         "may_change": crm_perms.role_of(request) == crm_perms.Role.FF})

    def patch(self, request):
        if crm_perms.role_of(request) != crm_perms.Role.FF:
            return Response({"detail": "Only the practice owner changes AI actions."},
                            status=403)
        key = request.data.get("action")
        action = ai_actions.BY_KEY.get(key)
        if action is None:
            return Response({"detail": "No such AI action."}, status=400)
        row, _ = AiActionSetting.objects.get_or_create(
            tenant=request.tenant, action=key, defaults={"tier": action.tier})
        runs_in = request.data.get("runs_in")
        if runs_in is not None:
            if runs_in not in AiActionSetting.RunsIn.values:
                return Response({"detail": "Runs in is the app or your AI app."}, status=400)
            if action.fixed and runs_in != AiActionSetting.RunsIn.APP:
                return Response({"detail": action.fixed_why}, status=400)
            row.runs_in = runs_in
        tier = request.data.get("tier")
        if tier is not None:
            if tier not in ai_actions.TIERS:
                return Response({"detail": "The tier is Fast, Standard or Deep."}, status=400)
            row.tier = tier
        row.updated_by = request.user
        row.save()
        return Response(next(a for a in ai_actions.table(request.tenant.pk) if a["key"] == key))


class ModelTiers(APIView):
    """The platform owner's table: each tier's model id and price."""

    def get_permissions(self):
        from apps.platform.permissions import IsPlatformOwnerInPracticesArea

        return [IsPlatformOwnerInPracticesArea()]

    def get(self, request):
        from apps.aiconnect.models import ModelTier

        rows = {r.code: r for r in ModelTier.objects.all()}
        return Response([_tier(rows.get(code), code)
                         for code in (*ai_actions.TIERS, ai_actions.MEDIA)])

    def patch(self, request):
        from apps.aiconnect.models import ModelTier

        code = request.data.get("code")
        if code not in (*ai_actions.TIERS, ai_actions.MEDIA):
            return Response({"detail": "The tier is fast, standard, deep or media."}, status=400)
        model = str(request.data.get("model") or "").strip()
        if not model or len(model) > 80 or " " in model:
            return Response({"detail": "The model is an id such as claude-sonnet-5-5"
                                       + (" or gemini-2.5-flash." if code == ai_actions.MEDIA
                                          else ".")}, status=400)
        try:
            per_in = Decimal(str(request.data.get("input_usd_per_mtok")))
            per_out = Decimal(str(request.data.get("output_usd_per_mtok")))
        except (InvalidOperation, TypeError):
            return Response({"detail": "Prices are dollars per million tokens."}, status=400)
        if per_in < 0 or per_out < 0:
            return Response({"detail": "Prices can't be negative."}, status=400)
        row, _ = ModelTier.objects.update_or_create(code=code, defaults={
            "model": model, "input_usd_per_mtok": per_in, "output_usd_per_mtok": per_out,
            "server_fallback": bool(request.data.get("server_fallback", True)),
            "updated_by": request.user})
        return Response(_tier(row, code))


def _tier(row, code) -> dict:
    fallback = ai_actions.tier_row(code)
    return {"code": code, "label": "Media (Gemini)" if code == ai_actions.MEDIA else code.title(),
            "model": row.model if row else fallback.model,
            "input_usd_per_mtok": str(row.input_usd_per_mtok if row else
                                      fallback.input_usd_per_mtok),
            "output_usd_per_mtok": str(row.output_usd_per_mtok if row else
                                       fallback.output_usd_per_mtok),
            "server_fallback": row.server_fallback if row else fallback.server_fallback,
            "updated_at": row.updated_at if row else None}
