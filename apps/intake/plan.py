"""The send plan: every Track call a reviewed submission needs, in order, with
the "what will be sent" summary and anything that stops it being sent.

Pure: plain data in, plain data out. Paths and bodies carry placeholders,
"{unit}", "{owner}", "{owner_company}", "{contact:0}", for ids Track gives
earlier in the same send, and {"$secret": "..."} where a sensitive value goes:
those are filled in by `track_writer` at the moment a call is made, so a
stored plan, a run's record or a log never holds one.

The order (owner, 2026-11-19, "the least mess when a step fails"):
contacts first, because they can be deleted by API and are where Track's
firewall refuses content (an @example.com email); then the owner and the
unit, which can't be deleted by API, only once those passed; the owner's
link to the unit last, so the owner's statements and portal never show a
half-built unit. An existing owner is left untouched: only the unit and the
owner-to-unit link are written (owner, change 4).

Never start a send that can't finish (owner, 2026-11-20, after intake #1
stopped at its door code): every sensitive value the answers call for is
held, already in Track, or marked by the reviewer as having none, or the plan
has a problem and Send stays off. A code step is planned only for a code
that is held (or already in Track), so a send never reaches a step whose
value isn't there.
"""

from __future__ import annotations

import re
from datetime import date

from . import derive, schema

#: Track's firewall refuses these (2026-11-19: an @example.com email is a 403).
TEST_DOMAINS = re.compile(r"@(?:[^@]*\.)?(?:example\.(?:com|org|net)|[^@]+\.(?:test|invalid|"
                          r"example|localhost))$", re.I)


def e164(phone: str) -> str:
    """A US-style number as Track's E.164, or "" when it can't be read."""
    raw = (phone or "").strip()
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+") and 8 <= len(digits) <= 15:
        return "+" + digits
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return ""


def _clean(body: dict) -> dict:
    return {k: v for k, v in body.items() if v not in ("", None)}


def people(answers) -> list[dict]:
    """The owner's contact first, then each additional owner."""
    about = answers.get("about") or {}
    out = [{"first": about.get("first_name", ""), "last": about.get("last_name", ""),
            "email": about.get("email", ""), "mobile": about.get("mobile", ""),
            "portal": True, "primary": True}]
    if about.get("has_extra_owners") == "yes":
        for extra in about.get("extra_owners") or []:
            if extra.get("first_name") or extra.get("last_name"):
                out.append({"first": extra.get("first_name", ""),
                            "last": extra.get("last_name", ""),
                            "email": extra.get("email", ""), "mobile": extra.get("mobile", ""),
                            "portal": bool(extra.get("portal")), "primary": False})
    return out


def account_name(answers) -> str:
    about = answers.get("about") or {}
    return about.get("account_name") or " ".join(
        p for p in (about.get("first_name"), about.get("last_name")) if p)


def _names(lists, key):
    return derive.by_id(lists.get(key))


#: The step that carries each sensitive value; a code's is its own key.
CARRIER = {"tax_id": "owner", "wifi_password": "details"}
WIFI_FIELD = "pms_units_wifi_password"
_NAME = re.compile(r"^(?:tax_id|wifi_password|code:[\w-]{1,24})$")


def sent_from(track_state) -> set[str]:
    """The sensitive values already done in Track: confirmed by Track
    (`track_writer`'s confirm, recorded as "sent"), or whose step is done.
    ENHQ deletes its copy of each, so these are never asked for again."""
    state = track_state or {}
    done = set(state.get("done") or [])
    out = {n for n in state.get("sent") or [] if isinstance(n, str)}
    out |= {name for name, key in CARRIER.items() if key in done}
    out |= {key for key in done if key.startswith("code:")}
    return out


def none_marked(staff) -> set[str]:
    return {n for n in (staff or {}).get("no_value") or [] if isinstance(n, str) and
            _NAME.match(n)}


def clean_none_marks(value) -> list[str]:
    """The reviewer's "there is none" marks, as saved: known names only."""
    if not isinstance(value, list):
        return []
    return [n for n in dict.fromkeys(value) if isinstance(n, str) and _NAME.match(n)][:20]


def needed(answers, staff, settings, lists) -> list[dict]:
    """Every sensitive value the answers call for, in the order the form asks:
    [{name, label, noun, section}] ("noun" for a sentence: "door code"). The
    Tax ID only for a new owner who chose one; the Wi-Fi password only when
    there is Wi-Fi and its field is sent."""
    staff = staff or {}
    out = []
    if staff.get("owner_mode") != "existing" and \
            (answers.get("tax") or {}).get("kind") == "tax_id":
        out.append({"name": "tax_id", "label": "Business Tax ID", "noun": "business Tax ID",
                    "section": "tax"})
    if WIFI_FIELD in derive.custom_values(answers, staff, settings, lists):
        out.append({"name": "wifi_password", "label": "Wi-Fi password",
                    "noun": "Wi-Fi password", "section": "home"})
    for code in derive.code_slots(answers, lists, settings):
        out.append({"name": f"code:{code['slot']}", "label": code["label"],
                    "noun": code["label"].lower(), "section": "access"})
    return out


def secret_states(answers, staff, settings, lists, *, held, sent) -> list[dict]:
    """Each needed value with its state: "sent" (done in Track), "held",
    "none" (the reviewer marked that there is none) or "missing"."""
    none = none_marked(staff)
    out = []
    for item in needed(answers, staff, settings, lists):
        name = item["name"]
        state = ("sent" if name in sent else "held" if name in held
                 else "none" if name in none else "missing")
        out.append({**item, "state": state})
    return out


def build(*, answers, staff, settings, lists, brand, held, today: date, sent=frozenset(),
          owner_active=None, unit_bookable=None) -> dict:
    """The plan for one submission. `staff` is the reviewer's choices merged
    with the defaults (`derive.staff_with_defaults`). `held`: the sensitive
    values ENHQ holds now, by name (`vault.held_names`); `sent`: those already
    done in Track (`sent_from`). `owner_active`/`unit_bookable` override the
    form's settings (the production proof keeps both off). `today` is the
    practice's date (services.practice_today), never the server's."""
    staff = staff or {}
    held, sent = set(held or ()), set(sent or ())
    mode = "existing" if staff.get("owner_mode") == "existing" else "new"
    problems, warnings, summary, steps = [], [], [], []
    about = answers.get("about") or {}
    prop = answers.get("property") or {}
    persons = people(answers)
    reuse = {str(k): v for k, v in (staff.get("reuse_contacts") or {}).items() if v}
    shares = {str(k): v for k, v in (staff.get("shares") or {}).items() if v not in ("", None)}

    # ----------------------------------------------------- checks first
    for i, person in enumerate(persons):
        who = "The owner" if i == 0 else f"Additional owner {i}"
        if mode == "existing" and i > 0:
            continue
        if not (person["first"] and person["last"]):
            problems.append(f"{who} needs a first and a last name.")
        if not (person["email"] or person["mobile"]):
            problems.append(f"{who} needs an email or a mobile number.")
        if person["email"] and not schema.email_ok(person["email"]):
            problems.append(f"{who}'s email doesn't look right.")
        if person["email"] and TEST_DOMAINS.search(person["email"]):
            problems.append(f"{who}'s email is at a test domain (like example.com): Track's "
                            "firewall refuses those. Use a real address.")
        if person["mobile"] and not e164(person["mobile"]):
            problems.append(f"{who}'s mobile number can't be read as a phone number.")
    if mode == "new":
        if not account_name(answers):
            problems.append("The owner needs a name for the account.")
        for key, words in (("street", "street"), ("city", "city"), ("state", "state"),
                           ("postal", "ZIP code")):
            if not about.get(key):
                problems.append(f"The owner's mailing address needs a {words} (Track requires "
                                "the tax address).")
        if not e164(about.get("mobile", "")):
            problems.append("The owner needs a mobile number: Track requires a tax phone.")
        total = 0.0
        for i in range(1, len(persons)):
            if str(i) in shares:
                try:
                    total += float(shares[str(i)])
                except (TypeError, ValueError):
                    problems.append(f"Additional owner {i}'s share isn't a number.")
        if total > 100:
            problems.append("The owners' shares add up to more than 100%.")
    elif not staff.get("existing_owner_id"):
        problems.append("Choose the owner in Track to attach the unit to.")
    if not staff.get("node_id"):
        problems.append("Pick the area (Track's node) for the unit.")
    if not staff.get("contract_id"):
        problems.append("Pick the contract.")
    if not staff.get("start_date"):
        problems.append("Set the start date.")
    if not (staff.get("unit_name") or "").strip():
        problems.append("The unit needs a name.")
    if not prop.get("street"):
        problems.append("The property needs a street address.")
    if not prop.get("lodging_type_id"):
        warnings.append("No property type: the unit is created without a lodging type.")
    if not staff.get("unit_type_id"):
        warnings.append("No unit type is chosen.")
    for i, room in enumerate(answers.get("bedrooms") or []):
        if not room.get("beds"):
            warnings.append(f"Bedroom {i + 1} has no beds.")
    tax_kind = (answers.get("tax") or {}).get("kind")
    secrets = secret_states(answers, staff, settings, lists, held=held, sent=sent)
    state_of = {item["name"]: item["state"] for item in secrets}
    for item in secrets:
        if item["state"] == "missing":
            problems.append(f"The {item['noun']} isn't in ENHQ: enter it beside its "
                            "question, or mark that there is none.")

    # ----------------------------------------------------- the calls
    owner_active = settings.get("owner_active", True) if owner_active is None else owner_active
    unit_bookable = (settings.get("new_units_bookable", False) if unit_bookable is None
                     else unit_bookable)
    node = _names(lists, "nodes").get(int(staff["node_id"])) if staff.get("node_id") else None
    if mode == "new":
        for i, person in enumerate(persons):
            if str(i) in reuse:
                continue
            steps.append({
                "key": f"contact:{i}", "kind": "create",
                "label": ("Create the owner's contact" if i == 0
                          else f"Create the contact for additional owner {i}"),
                "method": "POST", "path": "/crm/contacts",
                "body": _clean({"firstName": person["first"], "lastName": person["last"],
                                "primaryEmail": person["email"],
                                "cellPhone": e164(person["mobile"]),
                                **({"streetAddress": about.get("street"),
                                    "extendedAddress": about.get("street2"),
                                    "locality": about.get("city"), "region": about.get("state"),
                                    "postalCode": about.get("postal"),
                                    "country": about.get("country") or "US"} if i == 0 else {}),
                                "isOwnerContact": True}),
                "find": {"kind": "contact", "email": person["email"], "first": person["first"],
                         "last": person["last"]},
            })
        name = account_name(answers)
        owner_body = _clean({
            "name": name, "isActive": bool(owner_active),
            "email": about.get("email"), "phone": e164(about.get("mobile", "")),
            "streetAddress": about.get("street"), "extendedAddress": about.get("street2"),
            "locality": about.get("city"), "region": about.get("state"),
            "postal": about.get("postal"), "country": about.get("country") or "US",
            "notes": derive.owner_notes(answers, brand),
            "taxName": name, "taxStreetAddress": about.get("street"),
            "taxLocality": about.get("city"), "taxRegion": about.get("state"),
            "taxPostalCode": about.get("postal"), "taxCountry": about.get("country") or "US",
            "taxPhone": e164(about.get("mobile", "")),
        })
        # Required by Track even when there is none.
        owner_body["taxExtendedAddress"] = about.get("street2") or ""
        owner_body["openingBalance"] = 0
        if state_of.get("tax_id") == "held":
            owner_body["taxId"] = {"$secret": "tax_id"}
        steps.append({"key": "owner", "kind": "create",
                      "label": "Create the owner" + (" (active)" if owner_active
                                                     else " (inactive)"),
                      "method": "POST", "path": "/pms/owners", "body": owner_body,
                      "keep": {"owner_company": "companyId"},
                      "confirms": ["tax_id"] if "taxId" in owner_body else [],
                      "find": {"kind": "owner", "name": name, "email": about.get("email", "")}})
        for i, person in enumerate(persons):
            body = {"contactId": f"{{contact:{i}}}", "isPrimaryContact": i == 0}
            if i > 0 and str(i) in shares:
                body.update({"ownerType": "owner", "ownerSplit": float(shares[str(i)])})
            steps.append({"key": f"link:{i}", "kind": "link",
                          "label": ("Link the owner's contact as primary" if i == 0
                                    else f"Link additional owner {i} to the owner"),
                          "method": "POST", "path": "/crm/companies/{owner_company}/contacts/",
                          "body": body,
                          "find": {"kind": "link", "contact": f"{{contact:{i}}}"}})
    room_list = derive.rooms(answers, settings, lists, staff)
    sleeps = derive.total_sleeps(answers, settings, lists, staff)
    unit_body = _clean({
        "name": (staff.get("unit_name") or "").strip()[:120],
        "shortName": (staff.get("short_name") or staff.get("unit_name") or "").strip()[:60],
        "isActive": False, "isBookable": bool(unit_bookable), "useRoomConfiguration": True,
        "nodeId": staff.get("node_id"), "typeId": staff.get("unit_type_id"),
        "lodgingTypeId": prop.get("lodging_type_id"),
        "streetAddress": prop.get("street"), "extendedAddress": prop.get("street2"),
        "locality": prop.get("city"), "region": prop.get("state"), "postal": prop.get("postal"),
        "country": "US", "maxOccupancy": sleeps or None,
    })
    steps.append({"key": "unit", "kind": "create",
                  "label": "Create the unit (inactive, " + ("bookable" if unit_bookable
                                                           else "not bookable") + ")",
                  "method": "POST", "path": "/pms/units", "body": unit_body,
                  "find": {"kind": "unit", "name": unit_body.get("name", ""),
                           "street": prop.get("street", "")}})
    for order, room in enumerate(room_list, start=1):
        body = {"name": room["name"], "roomType": room["roomType"], "sortOrder": order}
        if room["roomType"] in ("bedroom", "common"):
            body["beds"] = [{"bedTypeId": b["type"], "count": b["count"]} for b in room["beds"]]
            body["sleeps"] = room["sleeps"]
        if room["roomType"] == "bedroom":
            body["hasAttachedBathroom"] = room["hasAttachedBathroom"]
        if room["roomType"].endswith("bathroom"):
            body["amenities"] = [{"bathroomAmenityId": int(k), "count": int(n)}
                                 for k, n in sorted(room["fixtures"].items())]
        steps.append({"key": f"room:{room['key']}", "kind": "create",
                      "label": f"Add {room['name']}", "method": "POST",
                      "path": "/pms/units/{unit}/rooms", "body": body,
                      "find": {"kind": "room", "name": room["name"]}})
    amenities = derive.chosen_amenities(answers, settings, lists, staff)
    custom = derive.custom_values(answers, staff, settings, lists)
    if WIFI_FIELD in custom and state_of.get("wifi_password") != "held":
        del custom[WIFI_FIELD]               # not held: nothing to send for it
    details = {}
    if amenities:
        details["amenitiesIds"] = [a["id"] for a in amenities]
    if custom:
        details["custom"] = custom
    if details:
        steps.append({"key": "details", "kind": "update",
                      "label": f"Set {len(amenities)} amenities and {len(custom)} details",
                      "method": "PUT", "path": "/pms/units/{unit}", "body": details,
                      "confirms": ["wifi_password"] if "pms_units_wifi_password" in custom
                      else []})
    tv_count = int((answers.get("home") or {}).get("tv_count") or 0)
    tv = derive.by_name(lists.get("amenities")).get("tv")
    if tv_count > 1 and tv:
        steps.append({"key": "count:tv", "kind": "amenity_count",
                      "label": f"Set the number of TVs ({tv_count})",
                      "amenity_id": int(tv["id"]), "count": tv_count})
    for code in derive.code_slots(answers, lists, settings):
        if state_of.get(f"code:{code['slot']}") not in ("held", "sent"):
            continue
        steps.append({"key": f"code:{code['slot']}", "kind": "create",
                      "label": f"Add the {code['label'].lower()}", "method": "POST",
                      "path": "/pms/units/{unit}/security-codes",
                      "body": {"codeTypeId": code["type_id"],
                               "code": {"$secret": f"code:{code['slot']}"},
                               "startDate": today.isoformat(), "isPublic": False},
                      "confirms": [f"code:{code['slot']}"],
                      "find": {"kind": "code", "type_id": code["type_id"],
                               "secret": f"code:{code['slot']}"}})
    contract = _names(lists, "contracts").get(int(staff["contract_id"])) \
        if staff.get("contract_id") else None
    owner_ref = "{owner}"
    steps.append({"key": "ownership", "kind": "create",
                  "label": "Link the owner to the unit"
                           + (f" (contract {contract['name']}, from {staff.get('start_date')})"
                              if contract else ""),
                  "method": "POST", "path": f"/pms/owners/{owner_ref}/units",
                  "body": {"ownerId": owner_ref, "unitId": "{unit}",
                           "contractId": staff.get("contract_id"),
                           "startDate": staff.get("start_date"),
                           "contractType": "standard", "taxMode": "pmc"},
                  "find": {"kind": "ownership"}})

    # ----------------------------------------------------- in words
    if mode == "new":
        names = ", ".join(f"{p['first']} {p['last']}".strip() for p in persons)
        summary.append(f"A new owner, {'active' if owner_active else 'inactive'}: "
                       f"{account_name(answers)}, with contacts {names} (the first is primary).")
        if state_of.get("tax_id") == "held":
            summary.append("The owner's business Tax ID goes with it.")
        elif tax_kind == "ssn":
            summary.append("No tax id is sent: the owner chose Social Security and adds it "
                           "in the owner portal.")
        if reuse:
            summary.append(f"{len(reuse)} existing Track contact(s) are used instead of new ones.")
    else:
        summary.append(f"The unit goes to the existing owner #{staff.get('existing_owner_id')} "
                       "in Track. Nothing about that owner, its notes or its contacts changes.")
    summary.append(
        f"A unit named {unit_body.get('name', '')}, inactive and "
        f"{'bookable' if unit_bookable else 'not bookable'}, in "
        f"{node['name'] if node else '(no area chosen)'}; sleeps {sleeps}.")
    for room in room_list:
        if room["roomType"] in ("bedroom", "common"):
            summary.append(derive.room_summary(room["name"], room["beds"], settings, lists))
        else:
            summary.append(f"{room['name']}: {derive.BATH_LABEL[room['roomType']]} bathroom")
    summary.append(f"{len(amenities)} amenities, {len(custom)} details, "
                   f"{sum(1 for s in steps if s['key'].startswith('code:'))} access codes "
                   "(values hidden).")
    for item in secrets:
        if item["state"] == "none":
            summary.append(f"No {item['noun']} is sent: marked as having none.")
    if contract:
        summary.append(f"The owner linked to the unit on {contract['name']} from "
                       f"{staff.get('start_date')} (standard, pmc).")
    summary.append("Never sent: Social Security numbers and bank details (not collected). "
                   "Owner dates, current bookings and documents stay in ENHQ.")
    return {"mode": mode, "steps": steps, "summary": summary, "problems": problems,
            "warnings": warnings, "secrets": secrets}
