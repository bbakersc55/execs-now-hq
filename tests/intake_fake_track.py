"""A fake Track for intake forms: SkyRun's real lists (settings only, from
the 2026-11-19 live reads; tests/fixtures/intake/skyrun_lists.json) and the
write behaviour seen live that day (docs/p14_intake_forms.md):

- PUT and PATCH on a unit change only what is sent;
- amenitiesIds replaces the unit's own amenities; a dropped one keeps its
  per-unit row with isEnabled null; the area's (node's) are always there;
- a unit's bedroom and bath counts follow its rooms' types; beds in a
  "common" room are kept but don't count as a bedroom;
- an @example.com email is refused by the firewall: 403, Server awselb/2.0,
  HTML;
- a unit block needs a bookable unit;
- /crm/contacts?search= matches email; /pms/owners?search= matches name only.

`fail_once[(METHOD, path template)] = "refuse" | "lose"`: the next such call
is refused (422), or is carried out and its answer lost (the connection drops
after Track did it), which is what "Try the rest again" has to survive.
"""

from __future__ import annotations

import copy
import itertools
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

LISTS = json.loads((Path(__file__).parent / "fixtures" / "intake" / "skyrun_lists.json")
                   .read_text())
FIREWALL_HTML = ("<html>\r\n<head><title>403 Forbidden</title></head>\r\n<body>\r\n<center>"
                 "<h1>403 Forbidden</h1></center>\r\n</body>\r\n</html>\r\n")


class Lost(Exception):
    pass


def _page(rows, query, key="items"):
    size = int((query.get("size") or ["25"])[0])
    page = int((query.get("page") or ["1"])[0])
    start = (page - 1) * size
    count = max(1, -(-len(rows) // size))
    return {"_embedded": {key: rows[start:start + size]}, "page": page, "page_count": count,
            "page_size": size, "total_items": len(rows)}


class FakeTrack:
    def __init__(self):
        self.ids = itertools.count(5000)
        self.contacts, self.owners, self.units, self.rooms = {}, {}, {}, {}
        self.links, self.amenity_rows, self.codes, self.ownerships = {}, {}, {}, {}
        self.blocks = {}
        self.calls = []
        self.fail_once = {}
        self.existing_owner(900, "Existing Owner LLC", "existing.owner@owners.test.invalid")

    # ------------------------------------------------------------ seeding
    def existing_owner(self, owner_id, name, email):
        self.owners[owner_id] = {"id": owner_id, "type": "owner", "name": name, "email": email,
                                 "phone": "+14355550190", "streetAddress": "1 Old Road",
                                 "locality": "Park City", "region": "UT", "postal": "84060",
                                 "isActive": True, "companyId": 7000 + owner_id, "notes": "",
                                 "taxIdMasked": None}
        self.links[7000 + owner_id] = []
        return self.owners[owner_id]

    def existing_unit(self, name, street, bookable=False):
        unit_id = next(self.ids)
        self.units[unit_id] = self._unit({"name": name, "streetAddress": street,
                                          "isBookable": bookable, "isActive": False})
        self.units[unit_id]["id"] = unit_id
        return unit_id

    # ------------------------------------------------------------ transports
    def get(self, url, headers):
        return self._answer("GET", url, headers, None)

    def send(self, method, url, headers, body):
        return self._answer(method, url, headers, body)

    def _answer(self, method, url, headers, body):
        parsed = urlparse(url)
        path = parsed.path
        assert path.startswith("/api/"), path
        path = path[4:].rstrip("/") or "/"
        query = parse_qs(parsed.query)
        template = re.sub(r"/\d+", "/{n}", path)
        self.calls.append({"method": method, "path": path, "template": template,
                           "body": copy.deepcopy(body),
                           "accept": headers.get("Accept"), "agent": headers.get("User-Agent")})
        assert headers.get("Accept") == "application/json"
        failure = self.fail_once.pop((method, template), None)
        if failure == "refuse":
            return 422, {"Content-Type": "application/problem+json"}, json.dumps(
                {"validation_messages": ["Simulated refusal"], "status": 422,
                 "detail": "Failed Validation"})
        if method != "GET" and "example.com" in json.dumps(body or {}):
            return 403, {"Server": "awselb/2.0", "Content-Type": "text/html"}, FIREWALL_HTML
        try:
            status, data = self._route(method, path, query, body or {})
        except KeyError:
            status, data = 404, {"detail": "Not Found", "status": 404}
        if failure == "lose":
            raise _lost()
        return status, {"Content-Type": "application/hal+json"}, \
            "" if data is None else json.dumps(data)

    # ------------------------------------------------------------ routes
    def _route(self, method, path, q, body):
        m = lambda pattern: re.fullmatch(pattern, path)  # noqa: E731
        lists = {"/pms/units/bed-types": ("bed_types", "bedTypes"),
                 "/pms/amenities/bathroom-amenities": ("bathroom_amenities", "BathroomAmenities"),
                 "/pms/units/amenity-groups": ("amenity_groups", "amenitiesCategory"),
                 "/pms/units/lodging-types": ("lodging_types", "lodgingTypes"),
                 "/pms/units/types": ("unit_types", "unitTypes"),
                 "/pms/units/security-code-types": ("code_types", "codes"),
                 "/pms/owners/contracts": ("contracts", "contracts"),
                 "/pms/unit-blocks/reasons": ("block_reasons", "reasons")}
        if method == "GET" and path in lists:
            kind, key = lists[path]
            return 200, _page(copy.deepcopy(LISTS[kind]), q, key)
        if method == "GET" and path == "/pms/units/amenities":
            rows = [{"id": a["id"], "name": a["name"], "group": {"name": a["group"]}}
                    for a in LISTS["amenities"]]
            return 200, _page(rows, q, "amenities")
        if method == "GET" and path == "/pms/nodes":
            return 200, _page(copy.deepcopy(LISTS["nodes"]), q, "nodes")
        if method == "GET" and path == "/pms/nodes/types":
            types = {(n["typeId"], n["typeName"]) for n in LISTS["nodes"]}
            return 200, _page([{"id": a, "name": b} for a, b in sorted(types)], q, "nodeTypes")
        if method == "GET" and path == "/custom-fields":
            rows = [{"id": f["id"], "name": f["name"], "reference": f["reference"],
                     "type": f["type"], "subType": f["subType"],
                     "_embedded": {"values": f["values"]}} for f in LISTS["custom_fields"]]
            return 200, _page(rows, q, "customFields")
        if method == "GET" and (x := m(r"/custom-fields/(\d+)/values")):
            field = next(f for f in LISTS["custom_fields"] if f["id"] == int(x.group(1)))
            return 200, _page(field["values"], q, "customFields")
        # contacts
        if path == "/crm/contacts" and method == "POST":
            if not body.get("firstName") or not body.get("lastName"):
                return 422, {"validation_messages": ["First and last name is required"]}
            cid = next(self.ids)
            self.contacts[cid] = {"id": cid, **body, "isOwnerContact": False}
            return 201, self.contacts[cid]
        if path == "/crm/contacts" and method == "GET":
            term = (q.get("search") or [""])[0].lower()
            rows = [c for c in self.contacts.values()
                    if term in (c.get("primaryEmail") or "").lower()
                    or term in f"{c.get('firstName', '')} {c.get('lastName', '')}".lower()]
            return 200, _page(rows, q, "contacts")
        if (x := m(r"/crm/contacts/(\d+)")) and method == "GET":
            return 200, self.contacts[int(x.group(1))]
        # owners
        if path == "/pms/owners" and method == "POST":
            oid = next(self.ids)
            company = next(self.ids)
            owner = {"id": oid, "type": "owner", "companyId": company, **body,
                     "taxIdMasked": ("**-***" + body["taxId"][-4:]) if body.get("taxId") else None}
            owner.pop("taxId", None)
            self.owners[oid] = owner
            self.links[company] = []
            return 201, owner
        if path == "/pms/owners" and method == "GET":
            term = (q.get("search") or [""])[0].lower()
            rows = [o for o in self.owners.values() if term in o["name"].lower()]
            return 200, _page(rows, q, "owners")
        if (x := m(r"/pms/owners/(\d+)")) and method == "GET":
            return 200, self.owners[int(x.group(1))]
        if (x := m(r"/pms/owners/(\d+)")) and method in ("PUT", "PATCH"):
            raise AssertionError("An owner record must never be changed by an intake.")
        if (x := m(r"/crm/companies/(\d+)/contacts")):
            company = int(x.group(1))
            if method == "GET":
                return 200, _page(self.links[company], q, "contacts")
            if method == "POST":
                row = {"contactId": body["contactId"], "companyId": company,
                       "isPrimaryContact": body.get("isPrimaryContact", False),
                       "ownerType": body.get("ownerType"), "ownerSplit": body.get("ownerSplit")}
                self.links[company].append(row)
                self.contacts[int(body["contactId"])]["isOwnerContact"] = True
                return 201, row
        if (x := m(r"/pms/owners/(\d+)/units")):
            owner = int(x.group(1))
            if method == "GET":
                return 200, _page([o for o in self.ownerships.values() if o["ownerId"] == owner],
                                  q, "ownerUnits")
            if method == "POST":
                if owner not in self.owners or int(body["unitId"]) not in self.units:
                    return 422, {"validation_messages": ["Owner or unit not found"]}
                oid = next(self.ids)
                self.ownerships[oid] = {"id": oid, **body}
                return 201, self.ownerships[oid]
        # units
        if path == "/pms/units" and method == "POST":
            uid = next(self.ids)
            self.units[uid] = self._unit(body)
            self.units[uid]["id"] = uid
            return 201, self._unit_out(uid)
        if path == "/pms/units" and method == "GET":
            term = (q.get("search") or [""])[0].lower()
            active = (q.get("isActive") or [None])[0]
            rows = [self._unit_out(u) for u in self.units
                    if term in self.units[u]["name"].lower()
                    and (active is None or bool(int(active)) == bool(self.units[u]["isActive"]))]
            return 200, _page(rows, q, "units")
        if (x := m(r"/pms/units/(\d+)")):
            uid = int(x.group(1))
            if method == "GET":
                return 200, self._unit_out(uid)
            unit = self.units[uid]
            for key, value in body.items():
                if key == "custom":
                    unit["custom"].update(value)
                elif key == "amenitiesIds":
                    keep = {int(a) for a in value}
                    for row in self.amenity_rows.values():
                        if row["unitId"] == uid:
                            row["isEnabled"] = True if row["amenityId"] in keep else None
                    have = {r["amenityId"] for r in self.amenity_rows.values()
                            if r["unitId"] == uid}
                    for a in keep - have:
                        rid = next(self.ids)
                        self.amenity_rows[rid] = {"id": rid, "amenityId": a, "unitId": uid,
                                                  "isEnabled": True, "count": None}
                elif key in ("bedrooms", "fullBathrooms", "threeQuarterBathrooms",
                             "halfBathrooms") and unit["useRoomConfiguration"]:
                    continue
                else:
                    unit[key] = value
            return 200, self._unit_out(uid)
        if (x := m(r"/pms/units/(\d+)/rooms")):
            uid = int(x.group(1))
            if method == "GET":
                return 200, _page([r for r in self.rooms.values() if r["unitId"] == uid], q,
                                  "unitRooms")
            rid = next(self.ids)
            self.rooms[rid] = {"id": rid, "unitId": uid, "roomType": body.get("roomType", ""),
                               **body}
            return 201, self.rooms[rid]
        if (x := m(r"/pms/units/(\d+)/amenities")) and method == "GET":
            uid = int(x.group(1))
            return 200, _page([r for r in self.amenity_rows.values() if r["unitId"] == uid], q,
                              "amenities")
        if (x := m(r"/pms/units/(\d+)/amenities")) and method == "POST":
            rid = next(self.ids)
            self.amenity_rows[rid] = {"id": rid, "amenityId": int(body["amenityId"]),
                                      "unitId": int(x.group(1)), "isEnabled": True,
                                      "count": body.get("count")}
            return 201, self.amenity_rows[rid]
        if (x := m(r"/pms/units/(\d+)/amenities/(\d+)")) and method == "PATCH":
            row = self.amenity_rows[int(x.group(2))]
            row.update(body)
            return 200, row
        if (x := m(r"/pms/units/(\d+)/security-codes")):
            uid = int(x.group(1))
            if method == "GET":
                return 200, _page([c for c in self.codes.values() if c["unitId"] == uid], q,
                                  "codes")
            cid = next(self.ids)
            self.codes[cid] = {"id": cid, "unitId": uid, **body}
            return 201, self.codes[cid]
        if path == "/pms/unit-blocks" and method == "POST":
            unit = self.units.get(int(body["unitId"]))
            if not unit or not unit.get("isBookable"):
                return 422, {"validation_messages": ["Unit was not found, or the unit is not "
                                                     "bookable."], "status": 422}
            bid = next(self.ids)
            self.blocks[bid] = {"id": bid, **body}
            return 201, self.blocks[bid]
        raise KeyError(path)

    def _unit(self, body):
        return {"name": "", "isActive": False, "isBookable": False, "useRoomConfiguration": False,
                "custom": {}, "maxOccupancy": None, **{k: v for k, v in body.items()
                                                        if k != "custom"},
                **({"custom": dict(body["custom"])} if "custom" in body else {})}

    def _unit_out(self, uid):
        unit = copy.deepcopy(self.units[uid])
        rooms = [r for r in self.rooms.values() if r["unitId"] == uid]
        if unit.get("useRoomConfiguration"):
            unit["bedrooms"] = sum(1 for r in rooms if r["roomType"] == "bedroom")
            unit["fullBathrooms"] = sum(1 for r in rooms if r["roomType"] == "full_bathroom")
            unit["threeQuarterBathrooms"] = sum(1 for r in rooms
                                                if r["roomType"] == "three_quarter_bathroom")
            unit["halfBathrooms"] = sum(1 for r in rooms if r["roomType"] == "half_bathroom")
        node = next((n for n in LISTS["nodes"] if n["id"] == unit.get("nodeId")), None)
        own = [r["amenityId"] for r in self.amenity_rows.values()
               if r["unitId"] == uid and r["isEnabled"]]
        unit["amenitiesIds"] = sorted(set((node or {}).get("amenitiesIds", [])) | set(own))
        return unit

    # ------------------------------------------------------------ reading back
    def writes(self):
        return [c for c in self.calls if c["method"] != "GET"]


def _lost():
    from apps.scorecard import track

    return track.TrackUnavailable("Track didn't answer. Nothing more was sent; try the rest "
                                  "again in a minute.")


def client(fake: FakeTrack):
    from apps.scorecard import track

    return track.TrackClient("skyrunparkcity.trackhs.com", "key", "secret", transport=fake.get,
                             sender=fake.send, sleep=lambda s: None)
