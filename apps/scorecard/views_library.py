"""The KPI library (P8): "From the library" and the practice's own entries.

    GET    /api/scorecard/library/            every entry offered, by page
    POST   /api/scorecard/library/            a practice entry (`source_key`: an
                                              edited copy of a shipped one)
    PATCH  /api/scorecard/library/<id>/       change one
    DELETE /api/scorecard/library/<id>/       archive one (a shipped entry it
                                              copied comes back)

Read by the practice's own team; written by those who set up scorecards
(the practice owner and associates).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.http import Http404
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.crm import permissions as crm_perms
from apps.scorecard import library
from apps.scorecard.models import Kpi, KpiLibraryEntry


def _role(request):
    return crm_perms.role_of(request)


def _clean(data, entry=None) -> dict:
    def pick(key, choices, fallback):
        value = data.get(key, getattr(entry, key, fallback) if entry else fallback)
        if value not in choices:
            raise ValueError(f"{key} is one of: {', '.join(choices)}.")
        return value

    name = " ".join(str(data.get("name", entry.name if entry else "") or "").split())[:120]
    if not name:
        raise ValueError("An entry needs a name.")
    out = {"name": name,
           "page": pick("page", KpiLibraryEntry.Page.values, "operations"),
           "kind": pick("kind", Kpi.Kind.values, "number"),
           "direction": pick("direction", Kpi.Direction.values, "higher"),
           "cadence": pick("cadence", Kpi.Cadence.values, "weekly"),
           "rollup": pick("rollup", Kpi.Rollup.values, "sum"),
           "guidance": str(data.get("guidance", entry.guidance if entry else "") or "")[:200],
           "duration_unit": str(data.get("duration_unit", entry.duration_unit if entry
                                         else "") or "")[:8]}
    feeds = data.get("feeds", entry.feeds if entry else [])
    if not isinstance(feeds, list) or any(f not in Kpi.Feed.values for f in feeds):
        raise ValueError("Feeds are a list of feed codes.")
    out["feeds"] = feeds
    try:
        band = Decimal(str(data.get("behind_band_pct", entry.behind_band_pct if entry else 10)))
    except (InvalidOperation, ValueError):
        raise ValueError("The behind band is a percent from 0 to 100.") from None
    if not 0 <= band <= 100:
        raise ValueError("The behind band is a percent from 0 to 100.")
    out["behind_band_pct"] = int(band)
    if out["kind"] == "rating":
        scale = data.get("rating_scale", entry.rating_scale if entry else 5)
        if scale not in (5, 10):
            raise ValueError("A rating is out of 5 or 10.")
        out["rating_scale"] = scale
    if out["kind"] == "duration" and out["duration_unit"] not in ("days", "hours", "minutes"):
        raise ValueError("A duration is in days, hours or minutes.")
    return out


class LibraryView(APIView):
    def get(self, request):
        if _role(request) not in crm_perms.TENANT_ROLES:
            raise Http404
        return Response({"pages": [{"code": code, "label": label}
                                   for code, label in library.PAGES],
                         "entries": library.entries(request.tenant),
                         "can_edit": _role(request) in ("FF", "CF")})

    def post(self, request):
        if _role(request) not in ("FF", "CF"):
            return Response({"detail": "The practice owner and associates keep the library."},
                            status=403)
        source_key = str(request.data.get("source_key") or "")
        base = library.shipped(source_key) if source_key else None
        if source_key and base is None:
            return Response({"detail": "There is no such library entry."}, status=404)
        data = {**(base or {}), **request.data}
        try:
            fields = _clean(data)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        if source_key:
            KpiLibraryEntry.objects.filter(source_key=source_key,
                                           archived_at__isnull=True).update(
                archived_at=timezone.now())
        row = KpiLibraryEntry.objects.create(tenant=request.tenant, source_key=source_key,
                                             created_by=request.user, **fields)
        return Response({"id": str(row.pk), "entries": library.entries(request.tenant)},
                        status=201)


class LibraryEntryView(APIView):
    def _row(self, request, pk):
        if _role(request) not in ("FF", "CF"):
            return None
        return KpiLibraryEntry.objects.filter(pk=pk, archived_at__isnull=True).first()

    def patch(self, request, pk):
        row = self._row(request, pk)
        if row is None:
            raise Http404
        try:
            fields = _clean(request.data, row)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        for key, value in fields.items():
            setattr(row, key, value)
        row.save()
        return Response({"entries": library.entries(request.tenant)})

    def delete(self, request, pk):
        row = self._row(request, pk)
        if row is None:
            raise Http404
        row.archived_at = timezone.now()
        row.save(update_fields=["archived_at", "updated_at"])
        return Response({"entries": library.entries(request.tenant)})
