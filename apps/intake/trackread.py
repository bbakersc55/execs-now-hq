"""Reading Track's lists for a form (bed types, amenities, custom fields, …).
Pure: no database, no Django; `tracklists.py` keeps the copies, and the
production proof (scripts/intake_track_proof.sh) runs this same code."""

from __future__ import annotations


def rows(data) -> list:
    data = data if isinstance(data, dict) else {}
    embedded = data.get("_embedded") or data.get("embedded") or {}
    return next((v for v in embedded.values() if isinstance(v, list)), [])


def every(client, path, params=None, most_pages=20) -> list:
    out, page = [], 1
    while page <= most_pages:
        data = client.get(path, {**(params or {}), "page": page, "size": 100})
        out += rows(data)
        if page >= int((data or {}).get("page_count") or 1):
            break
        page += 1
    return out


def _active(row) -> bool:
    return row.get("isActive", True) is not False


def fetch(client) -> dict:
    """Every list, as plain rows, from Track. Raises the client's refusals."""
    node_types = {int(t["id"]): t.get("name", "") for t in every(client, "/pms/nodes/types")}
    fields = []
    for field in every(client, "/custom-fields", {"entity": "pms_units"}):
        values = ((field.get("_embedded") or {}).get("values") or [])
        if field.get("type") in ("select", "multiselect"):
            values = every(client, f"/custom-fields/{field['id']}/values") or values
        fields.append({"id": field["id"], "name": field.get("name", ""),
                       "reference": field.get("reference", ""), "type": field.get("type", ""),
                       "subType": field.get("subType") or "",
                       "values": [{"id": v.get("id"), "handle": v.get("handle"),
                                   "name": v.get("name")} for v in values]})
    return {
        "bed_types": [{"id": r["id"], "name": r.get("name", ""), "isActive": _active(r)}
                      for r in every(client, "/pms/units/bed-types")],
        "bathroom_amenities": [{"id": r["id"], "name": r.get("name", ""),
                                "isActive": _active(r)}
                               for r in every(client, "/pms/amenities/bathroom-amenities")],
        "amenities": [{"id": r["id"], "name": r.get("name", ""),
                       "group": (r.get("group") or {}).get("name", "")}
                      for r in every(client, "/pms/units/amenities")],
        "amenity_groups": [{"id": r["id"], "name": r.get("name", "")}
                           for r in every(client, "/pms/units/amenity-groups")],
        "lodging_types": [{"id": r["id"], "name": r.get("name", ""), "isActive": _active(r)}
                          for r in every(client, "/pms/units/lodging-types")],
        "unit_types": [{"id": r["id"], "name": r.get("name", ""), "isActive": _active(r)}
                       for r in every(client, "/pms/units/types")],
        "nodes": [{"id": r["id"], "name": r.get("name", ""), "typeId": r.get("typeId"),
                   "typeName": node_types.get(int(r.get("typeId") or 0), ""),
                   "parentId": r.get("parentId"),
                   "amenitiesIds": [int(a) for a in r.get("amenitiesIds") or []]}
                  for r in every(client, "/pms/nodes")],
        "code_types": [{"id": r["id"], "name": r.get("name", ""), "isActive": _active(r)}
                       for r in every(client, "/pms/units/security-code-types")],
        "custom_fields": fields,
        "contracts": [{"id": r["id"], "code": r.get("code", ""), "name": r.get("name", ""),
                       "type": r.get("type", ""), "isActive": _active(r)}
                      for r in every(client, "/pms/owners/contracts")],
        "block_reasons": [{"id": r["id"], "name": r.get("name", ""), "code": r.get("code", "")}
                          for r in every(client, "/pms/unit-blocks/reasons")],
    }
