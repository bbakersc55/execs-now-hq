"""What follows from the answers: room types, sleeps, the unit's choices,
amenities worked out from other sections, and the values Track's custom
fields take. Pure functions over plain data, shared by the review screen, the
"what will be sent" summary and the send itself.

`lists` is the company's Track lists (`tracklists.lists_for`); `settings` the
form's settings (`defaults.build`). Nothing here reads a database or Track,
so the same code runs in the worker, in tests and in the production proof.
"""

from __future__ import annotations

from datetime import date

from . import schema

# ------------------------------------------------------------ lookups


def by_id(rows) -> dict:
    return {int(r["id"]): r for r in rows or [] if r.get("id") is not None}


def by_name(rows) -> dict:
    return {str(r.get("name", "")).strip().lower(): r for r in rows or []}


def field_def(lists, reference):
    for field in lists.get("custom_fields") or []:
        if field.get("reference") == reference:
            return field
    return None


def handle_for(lists, reference, name_or_handle):
    """A choice field's option, as its handle, from a name or a handle.
    Choices go to Track by handle (a name answers 200 and clears the field)."""
    field = field_def(lists, reference)
    if not field:
        return None
    wanted = str(name_or_handle or "").strip().lower()
    for value in field.get("values") or []:
        if wanted in (str(value.get("handle", "")).lower(), str(value.get("name", "")).lower(),
                      str(value.get("id", ""))):
            return value.get("handle")
    return None


# ------------------------------------------------------------ rooms

def fixture_kind(name: str) -> str:
    """"tub", "shower" or "" for a bathroom fixture, by Track's name."""
    n = name.lower()
    if "tub" in n:
        return "tub"
    if "shower" in n and "grab" not in n and "chair" not in n:
        return "shower"
    return ""


def bath_type(fixtures: dict, lists) -> str:
    """Any tub makes it full, a shower without a tub three-quarter, neither half."""
    names = {str(f["id"]): f.get("name", "") for f in lists.get("bathroom_amenities") or []}
    kinds = {fixture_kind(names.get(str(k), "")) for k, n in (fixtures or {}).items() if n}
    if "tub" in kinds:
        return "full_bathroom"
    if "shower" in kinds:
        return "three_quarter_bathroom"
    return "half_bathroom"


BATH_LABEL = {"full_bathroom": "Full", "three_quarter_bathroom": "Three-quarter",
              "half_bathroom": "Half"}


def bed_sleeps(settings, bed_type_id) -> int:
    row = (settings.get("sleeps") or {}).get(str(bed_type_id))
    return int(row["sleeps"]) if row and row.get("sleeps") is not None else 2


def bed_label(settings, lists, bed_type_id) -> str:
    row = (settings.get("sleeps") or {}).get(str(bed_type_id))
    if row and row.get("label"):
        return row["label"]
    bed = by_id(lists.get("bed_types")).get(int(bed_type_id))
    return bed["name"] if bed else "Bed"


def room_sleeps(beds, settings) -> int:
    return sum(bed_sleeps(settings, b["type"]) * int(b["count"]) for b in beds or [])


def room_summary(title, beds, settings, lists) -> str:
    """"Bedroom 2: Queen x1, Twin x2, sleeps 4"."""
    parts = [f"{bed_label(settings, lists, b['type'])} x{b['count']}" for b in beds or []]
    head = f"{title}: " + (", ".join(parts) if parts else "no beds yet")
    return f"{head}, sleeps {room_sleeps(beds, settings)}"


def where_label(place) -> str:
    if place.get("where") == "other" and place.get("label"):
        return place["label"]
    return schema.label("where", place.get("where")) or "Another room"


def rooms(answers, settings, lists, staff=None) -> list[dict]:
    """Every room Track will hold, in order: bedrooms, other places people
    sleep, then bathrooms. Each with Track's roomType, beds or fixtures, and
    sleeps. The reviewer may override a bathroom's type."""
    staff = staff or {}
    overrides = staff.get("bath_types") or {}
    out = []
    for i, room in enumerate(answers.get("bedrooms") or []):
        out.append({"key": f"bedroom-{i}", "name": f"Bedroom {i + 1}", "roomType": "bedroom",
                    "beds": room.get("beds") or [], "hasAttachedBathroom": bool(room.get("own_bath")),
                    "sleeps": room_sleeps(room.get("beds"), settings)})
    other = answers.get("other_sleeping") or {}
    if other.get("has") == "yes":
        for i, place in enumerate(other.get("places") or []):
            if not place.get("beds"):
                continue
            out.append({"key": f"other-{i}", "name": where_label(place), "roomType": "common",
                        "beds": place["beds"], "hasAttachedBathroom": False,
                        "sleeps": room_sleeps(place["beds"], settings)})
    for i, bath in enumerate(answers.get("bathrooms") or []):
        worked_out = bath_type(bath.get("fixtures"), lists)
        chosen = overrides.get(str(i)) if overrides.get(str(i)) in BATH_LABEL else worked_out
        out.append({"key": f"bathroom-{i}", "name": f"Bathroom {i + 1}", "roomType": chosen,
                    "worked_out": worked_out, "fixtures": bath.get("fixtures") or {},
                    "sleeps": 0})
    return out


def total_sleeps(answers, settings, lists, staff=None) -> int:
    staff = staff or {}
    if staff.get("sleeps_total") not in (None, ""):
        try:
            return max(0, int(staff["sleeps_total"]))
        except (TypeError, ValueError):
            pass
    return sum(r["sleeps"] for r in rooms(answers, settings, lists, staff))


def counts(answers, lists, staff=None) -> dict:
    rs = rooms(answers, {}, lists, staff)
    return {"bedrooms": sum(1 for r in rs if r["roomType"] == "bedroom"),
            "full": sum(1 for r in rs if r["roomType"] == "full_bathroom"),
            "three_quarter": sum(1 for r in rs if r["roomType"] == "three_quarter_bathroom"),
            "half": sum(1 for r in rs if r["roomType"] == "half_bathroom")}


# ------------------------------------------------------------ the unit

def unit_type_for(bedrooms: int, lists):
    """"Studio" for none, "1 Bedroom", "N Bedrooms" otherwise; None if Track has
    no such type."""
    names = by_name(lists.get("unit_types"))
    wanted = "studio" if bedrooms == 0 else ("1 bedroom" if bedrooms == 1
                                             else f"{bedrooms} bedrooms")
    row = names.get(wanted)
    return row["id"] if row else None


def street_line(prop) -> str:
    line = (prop or {}).get("street", "").strip()
    extra = (prop or {}).get("street2", "").strip()
    return f"{line}, {extra}" if line and extra else line


def ready_date(answers):
    prop = answers.get("property") or {}
    if prop.get("ready") == "date" and prop.get("ready_date"):
        return prop["ready_date"]
    return None


def staff_defaults(answers, settings, lists) -> dict:
    """The reviewer's choices before they change any: what the form preselects."""
    n = counts(answers, lists)["bedrooms"]
    start = ready_date(answers) or date.today().isoformat()
    name = street_line(answers.get("property"))
    return {
        "node_id": None,                      # owner, 2026-11-19: the reviewer must pick
        "contract_id": settings.get("default_contract_id"),
        "management_agreement": settings.get("default_management_agreement") or "full_service",
        "start_date": start,
        "contract_effective_date": start,
        "unit_type_id": unit_type_for(n, lists),
        "unit_name": name[:120],
        "short_name": name[:60],
        "bath_types": {},
        "sleeps_total": None,
        "shares": {},
        "untick": [],
        "keywords": None,                     # None: the presets below apply
        "custom": {},
        "owner_mode": "new",
        "existing_owner_id": None,
        "reuse_contacts": {},
    }


def staff_with_defaults(staff, answers, settings, lists) -> dict:
    merged = staff_defaults(answers, settings, lists)
    for key, value in (staff or {}).items():
        if value is not None or key in ("node_id", "existing_owner_id", "sleeps_total"):
            merged[key] = value
    return merged


# ------------------------------------------------------------ amenities

#: Amenities worked out from other answers: (answer, Track names, why), owner
#: 2026-11-19. Each is shown pre-ticked at review, marked as coming from the
#: owner's answers, and the reviewer may untick it.
def _derived_rules(answers):
    home = answers.get("home") or {}
    amen = answers.get("amenities") or {}
    access = answers.get("access") or {}
    rules = []
    if home.get("wifi") == "yes":
        rules.append((["Wifi", "Wifi - Free"], "Wi-Fi: yes"))
    tv = set(home.get("tv") or [])
    if tv:
        rules.append((["TV"], "TV: " + ", ".join(schema.label("tv", k) for k in sorted(tv))))
    if "smart_tv" in tv:
        rules.append((["Smart TV"], "TV: Smart TV"))
    if "cable" in tv:
        rules.append((["Satellite or Cable"], "TV: Cable or satellite"))
    parking = set(home.get("parking") or [])
    if "garage" in parking:
        rules.append((["Garage"], "Parking: Garage"))
    if parking & {"driveway", "assigned", "shared_lot"}:
        rules.append((["Parking - On Site Free"], "Parking: on site"))
    if "driveway" in parking or "garage" in parking:
        rules.append((["Parking - Private"], "Parking: driveway or garage"))
    if "street" in parking:
        rules.append((["Parking - Street"], "Parking: Street parking"))
    heating = [k for k in home.get("heating") or [] if k != "other"]
    if heating:
        rules.append((["Heating"], "Heating: " + ", ".join(schema.label("heating", k)
                                                          for k in heating)))
    cooling = set(home.get("cooling") or [])
    if cooling & {"central", "mini_split", "window"}:
        rules.append((["Air Conditioning"], "Cooling: air conditioning"))
    if "fans" in cooling:
        rules.append((["Ceiling Fan"], "Cooling: Ceiling fans"))
    if access.get("alarm") == "yes":
        rules.append((["Security System"], "Alarm: yes"))
    if home.get("heat_tape") == "yes":
        rules.append((["Heat Tape"], "Heat tape: yes"))
    if home.get("softener") == "yes":
        rules.append((["Water Softener"], "Water softener: yes"))
    if amen.get("gondola") == "yes":
        rules.append((["Resort Access"], "Gondola or lift access: yes"))
    return rules


def node_amenity_ids(lists, node_id) -> set:
    node = by_id(lists.get("nodes")).get(int(node_id)) if node_id else None
    return {int(a) for a in (node or {}).get("amenitiesIds") or []}


def derived_amenities(answers, lists, node_id=None) -> list[dict]:
    """[{id, name, why}] worked out from other sections, minus any the chosen
    area already provides."""
    names = by_name(lists.get("amenities"))
    provided = node_amenity_ids(lists, node_id)
    out, seen = [], set()
    for track_names, why in _derived_rules(answers):
        for name in track_names:
            row = names.get(name.lower())
            if not row or int(row["id"]) in provided or int(row["id"]) in seen:
                continue
            seen.add(int(row["id"]))
            out.append({"id": int(row["id"]), "name": row["name"], "why": why})
    return out


def chosen_amenities(answers, settings, lists, staff=None) -> list[dict]:
    """[{id, name, why}]: the owner's common picks, their "anything more"
    picks, and the worked-out ones the reviewer left ticked; never one the
    chosen area already provides (the unit has it through the area)."""
    staff = staff or {}
    names = by_id(lists.get("amenities"))
    provided = node_amenity_ids(lists, staff.get("node_id"))
    common = {c["key"]: c for c in settings.get("common_amenities") or []}
    untick = {int(a) for a in staff.get("untick") or []}
    out, seen = [], set()

    def add(amenity_id, why):
        amenity_id = int(amenity_id)
        if amenity_id in seen or amenity_id in provided or amenity_id not in names:
            return
        seen.add(amenity_id)
        out.append({"id": amenity_id, "name": names[amenity_id]["name"], "why": why})

    amen = answers.get("amenities") or {}
    for key in amen.get("common") or []:
        for amenity_id in (common.get(key) or {}).get("amenity_ids") or []:
            add(amenity_id, "Owner's pick")
    for amenity_id in amen.get("more") or []:
        add(amenity_id, "Owner's pick")
    for item in derived_amenities(answers, lists, staff.get("node_id")):
        if item["id"] not in untick:
            add(item["id"], item["why"])
    return out


# ------------------------------------------------------------ custom fields

def _join(*parts) -> str:
    return "\n".join(p for p in parts if p)


def _by_label(name, key, other=""):
    if key == "company" and other:
        return other
    return schema.label(name, key) if key else ""


def owner_field_values(answers, lists) -> dict:
    """Values for the built-in owner questions' custom fields, by reference.
    The Wi-Fi password is a placeholder: the value is only ever read from its
    encrypted row at the moment it is sent."""
    home = answers.get("home") or {}
    v = {}
    if home.get("wifi") == "yes":
        v["pms_units_internet_service_provider"] = home.get("wifi_provider", "")
        v["pms_units_wifi_network_name"] = home.get("wifi_network", "")
        v["pms_units_wifi_router_location_notes"] = home.get("wifi_router", "")
        v["pms_units_wifi_password"] = {"$secret": "wifi_password"}
    tv = home.get("tv") or []
    if tv or home.get("tv_provider") or home.get("tv_note"):
        v["pms_units_cable_or_satellite_tv_provider"] = home.get("tv_provider", "")
        v["pms_units_cable_or_satellite_tv_notes"] = _join(
            ", ".join(schema.label("tv", k) for k in tv), home.get("tv_note", ""))
    if home.get("trash_by"):
        v["pms_units_trash_service_provider"] = _by_label("trash_by", home["trash_by"],
                                                          home.get("trash_provider", ""))
        days = [h for h in (handle_for(lists, "pms_units_trash_pickup_day", d)
                            for d in home.get("trash_days") or []) if h]
        if days:
            v["pms_units_trash_pickup_day"] = days
        v["pms_units_trash_notes"] = home.get("trash_note", "")
    if home.get("hoa") == "yes":
        v["pms_units_hoa_management_company_name"] = home.get("hoa_company", "")
        v["pms_units_hoa_management_company_point_of_contact"] = home.get("hoa_contact", "")
        v["pms_units_hoa_management_company_phone_number"] = home.get("hoa_phone", "")
        v["pms_units_hoa_management_company_email_address"] = home.get("hoa_email", "")
        v["pms_units_hoa_management_company_other_notes"] = home.get("hoa_note", "")
    if home.get("heat_tape") in ("yes", "unsure"):
        v["pms_units_heat_tape_notes"] = _join(
            "Heat tape: " + schema.label("yes_no_unsure", home["heat_tape"]).lower() + ".",
            f"Maintained by: {home['heat_tape_by']}." if home.get("heat_tape_by") else "")
    if home.get("snow_by"):
        who = _by_label("done_by", home["snow_by"], home.get("snow_provider", ""))
        v["pms_units_snow_plowing_provider"] = who
        v["pms_units_snow_shoveling_provider"] = who
        v["pms_units_snow_plowing_notes"] = home.get("snow_note", "")
    if home.get("permit") == "yes" and home.get("permit_number"):
        v["pms_units_nightly_rental_permit"] = home["permit_number"]
    heating = ", ".join(schema.label("heating", k) for k in home.get("heating") or [])
    cooling = ", ".join(schema.label("cooling", k) for k in home.get("cooling") or [])
    if heating or cooling or home.get("hvac_note"):
        v["pms_units_hvac_notes"] = _join(f"Heating: {heating}." if heating else "",
                                          f"Cooling: {cooling}." if cooling else "",
                                          home.get("hvac_note", ""))
    parking = ", ".join(schema.label("parking", k) for k in home.get("parking") or [])
    if parking or home.get("parking_note"):
        v["pms_units_parking_instructions"] = _join(
            f"Parking: {parking}." if parking else "",
            "Guests need a parking pass that must be returned."
            if home.get("parking_pass") == "yes" else "",
            home.get("parking_note", ""))
    other = []
    if home.get("landscaping_by"):
        who = _by_label("done_by", home["landscaping_by"])
        other.append(_join(f"Landscaping: {who}.", home.get("landscaping_note", "")))
    if home.get("softener") in ("yes", "unsure"):
        other.append(_join("Water softener: "
                           + schema.label("yes_no_unsure", home["softener"]).lower() + ".",
                           home.get("softener_note", "")))
    if other:
        v["pms_units_other_maintenance_or_service_notes"] = "\n\n".join(other)
    return {k: val for k, val in v.items() if val not in ("", None, [])}


def keyword_presets(answers, lists) -> list[str]:
    """Trigger/Automation Keywords preselected for the reviewer, by handle."""
    home = answers.get("home") or {}
    amen = answers.get("amenities") or {}
    ref = "pms_units_trigger_automation_keywords"
    wanted = []
    if home.get("parking_pass") == "yes":
        wanted.append("Parking Pass")
    if "private_hot_tub" in (amen.get("common") or []):
        wanted.append("Private Hot Tub")
    if "none" in (home.get("cooling") or []):
        wanted.append("No AC")
    return [h for h in (handle_for(lists, ref, w) for w in wanted) if h]


def custom_values(answers, staff, settings, lists) -> dict:
    """Every custom field value to send, by reference: owner-answered fields
    whose state is "owner", reviewer fields whose state is "staff". Choices
    by handle; anything Track would not take is dropped here, not sent."""
    states = settings.get("custom_fields") or {}
    out = {}
    builtin = owner_field_values(answers, lists)
    for ref, value in builtin.items():
        if (states.get(ref) or {}).get("state") == "owner":
            out[ref] = value
    for ref, value in (answers.get("custom") or {}).items():
        if (states.get(ref) or {}).get("state") == "owner" and ref not in schema.BUILTIN_FIELDS:
            out[ref] = value
    staff = staff or {}
    staff_values = dict(staff.get("custom") or {})
    if (states.get("pms_units_management_agreement_type") or {}).get("state") == "staff" \
            and staff.get("management_agreement"):
        staff_values.setdefault("pms_units_management_agreement_type",
                                staff["management_agreement"])
    if (states.get("pms_units_contract_effective_date") or {}).get("state") == "staff" \
            and staff.get("contract_effective_date"):
        staff_values.setdefault("pms_units_contract_effective_date",
                                staff["contract_effective_date"])
    if (states.get("pms_units_trigger_automation_keywords") or {}).get("state") == "staff":
        keywords = staff.get("keywords")
        staff_values.setdefault("pms_units_trigger_automation_keywords",
                                keyword_presets(answers, lists) if keywords is None else keywords)
    for ref, value in staff_values.items():
        if (states.get(ref) or {}).get("state") == "staff":
            out[ref] = value
    return {ref: _typed(lists, ref, value) for ref, value in out.items()
            if _typed(lists, ref, value) not in (None, "", [])}


def _typed(lists, ref, value):
    """A value as Track takes it for the field's type; None if it can't."""
    if isinstance(value, dict):          # a secret placeholder
        return value
    field = field_def(lists, ref)
    if not field:
        return None
    kind = field.get("type")
    if kind == "select":
        return handle_for(lists, ref, value)
    if kind == "multiselect":
        values = value if isinstance(value, list) else [value]
        return [h for h in (handle_for(lists, ref, x) for x in values) if h]
    if kind == "date":
        try:
            return date.fromisoformat(str(value)[:10]).isoformat()
        except ValueError:
            return None
    if kind in ("integer", "decimal"):
        try:
            return float(value) if kind == "decimal" else int(value)
        except (TypeError, ValueError):
            return None
    if kind == "boolean":
        return str(value).lower() in ("1", "true", "yes")
    return str(value)[:4000]


# ------------------------------------------------------------ owner notes

def owner_notes(answers, brand: str) -> str:
    about = answers.get("about") or {}
    lines = []
    if about.get("contact_pref"):
        lines.append("Preferred contact: " + schema.label("contact_pref", about["contact_pref"])
                     + ".")
    if about.get("heard"):
        heard = schema.label("heard", about["heard"])
        detail = f" ({about['heard_detail']})" if about.get("heard_detail") else ""
        lines.append(f"How they heard about {brand}: {heard}{detail}.")
    return "\n".join(lines)


# ------------------------------------------------------------ codes

def code_slots(answers, lists, settings) -> list[dict]:
    """[{slot, type_id, label}] the owner was asked for, in order. Their values
    are secrets, read only at the moment of sending."""
    names = by_name(lists.get("code_types"))
    ids = by_id(lists.get("code_types"))

    def type_named(name):
        row = names.get(name.lower())
        return row["id"] if row else None

    access = answers.get("access") or {}
    out = []
    door = access.get("door")
    if door in ("smart_lock", "keypad"):
        out.append({"slot": "door", "type_id": type_named("Door Code"), "label": "Door code"})
    elif door == "lockbox":
        out.append({"slot": "door", "type_id": type_named("Lockbox Code"),
                    "label": "Lockbox code"})
    if access.get("owner_closet") == "yes":
        out.append({"slot": "owner_closet", "type_id": type_named("Owner Closet"),
                    "label": "Owner closet code"})
    if access.get("alarm") == "yes":
        out.append({"slot": "alarm", "type_id": type_named("Alarm Code"), "label": "Alarm code"})
    offered = {int(i) for i in settings.get("code_type_ids") or []}
    for i, extra in enumerate(access.get("extra_codes") or []):
        type_id = int(extra.get("type") or 0)
        if type_id in offered and type_id in ids:
            out.append({"slot": f"extra-{i}", "type_id": type_id, "label": ids[type_id]["name"]})
    return [c for c in out if c["type_id"]]
