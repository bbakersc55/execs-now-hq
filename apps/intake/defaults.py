"""A new form's starting settings, built from the company's Track lists.

Ids differ from one Track account to another, so everything here is found by
the name Track gives it and stored as that account's id. Pure: no database,
no Track; `lists` is what `tracklists.lists_for` returns.
"""

from __future__ import annotations

import re

SETTING_KEYS = (
    "common_amenities", "hidden_groups", "lodging_type_ids", "code_type_ids",
    "custom_fields", "sleeps", "checklist", "checklist_offered", "message_invite",
    "message_reminder",
    "new_units_bookable", "owner_active", "default_contract_id",
    "default_management_agreement", "test_mode",
)

#: The owner's common list (owner, 2026-11-19): label, then Track amenity names.
COMMON_AMENITIES = [
    ("washer_dryer", "Washer and dryer in the home", ["Washer - Private", "Dryer - Private"]),
    ("shared_laundry", "Shared laundry", ["Washer - Community", "Dryer - Community"]),
    ("dishwasher", "Dishwasher", ["Dishwasher"]),
    ("private_hot_tub", "Private hot tub", ["Hot Tub - Private"]),
    ("community_pool", "Community pool", ["Pool - Community"]),
    ("community_hot_tub", "Community hot tub", ["Hot Tub - Community"]),
    ("grill", "Grill", ["BBQ Grill - Private"]),
    ("gas_fireplace", "Gas fireplace", ["Fireplace - Gas"]),
    ("wood_fireplace", "Wood fireplace or wood stove", ["Fireplace - Wood or Wood Stove"]),
    ("workspace", "Dedicated workspace (desk and chair)",
     ["Laptop Friendly Workspace", "Desk", "Desk Chair"]),
    ("ski_in_out", "Ski in / ski out", ["Ski In/Ski Out"]),
    ("ski_storage", "Ski storage", ["Ski Storage"]),
    ("mountain_view", "Mountain view", ["View - Mountain"]),
    ("patio", "Patio or balcony", ["Patio or Balcony"]),
    ("fire_pit", "Fire pit", ["Fire Pit"]),
    ("game_room", "Game room", ["Game Room"]),
    ("ping_pong", "Ping pong table", ["Ping Pong Table"]),
    ("ev_charger", "Electric vehicle charger", ["Electric Vehicle Charger"]),
]

#: Never offered to owners in "Anything more?".
HIDDEN_GROUPS = ["Website Badges", "Internal Use Amenities"]

#: Code types offered for "Add another code"; the door, owner closet and alarm
#: have their own questions. All active types but these, to start.
CODE_TYPES_NOT_OFFERED = ["Master Programming Code"]

#: Custom fields an owner answers through a built-in question, by reference.
#: The question that feeds each one is in `schema.BUILTIN_FIELDS`.
OWNER_FIELDS = [
    "pms_units_wifi_network_name", "pms_units_wifi_password",
    "pms_units_wifi_router_location_notes", "pms_units_internet_service_provider",
    "pms_units_cable_or_satellite_tv_provider", "pms_units_cable_or_satellite_tv_notes",
    "pms_units_trash_service_provider", "pms_units_trash_pickup_day", "pms_units_trash_notes",
    "pms_units_hoa_management_company_name",
    "pms_units_hoa_management_company_point_of_contact",
    "pms_units_hoa_management_company_phone_number",
    "pms_units_hoa_management_company_email_address",
    "pms_units_hoa_management_company_other_notes", "pms_units_heat_tape_notes",
    "pms_units_snow_plowing_provider", "pms_units_snow_shoveling_provider",
    "pms_units_snow_plowing_notes", "pms_units_nightly_rental_permit", "pms_units_hvac_notes",
    "pms_units_parking_instructions", "pms_units_water_softener", "pms_units_landscaping",
    "pms_units_coffee_maker_type",
]
#: Owner, 2026-11-23: the water softener and landscaping answers have their own
#: fields in Track now. Other Maintenance or Service Notes carried them before;
#: a form set up then has it "owner", which would now ask it as a question of
#: its own, so the move switches it off (once; a manager can switch it back).
MOVED_FIELDS = {"pms_units_other_maintenance_or_service_notes":
                ("pms_units_water_softener", "pms_units_landscaping")}
#: Filled in by the reviewer.
STAFF_FIELDS = [
    "pms_units_management_agreement_type", "pms_units_contract_effective_date",
    "pms_units_trigger_automation_keywords", "pms_units_property_hoa_booking_link",
    "pms_units_video_tour", "pms_units_3d_tour", "pms_units_arrival_video_instructions",
    "pms_units_internet_service_account_number",
]
#: Where an owner-answered field without a built-in question appears.
GENERIC_SECTION = "home"

#: Owner-facing names for some of Track's bed types (owner, 2026-11-19).
BED_LABELS = {
    "Double": "Double (Full)",
    "Double Sleeper Sofa": "Double (Full) Sleeper Sofa",
}

#: The onboarding checklist (owner, 2026-11-19). `when` decides whether a
#: submission gets the task; due dates count from the owner's ready date, or
#: the day it was sent when that is blank or past. Titles never carry a name.
HOLD_NOTE = " (needs the unit bookable in Track)"
CHECKLIST = [
    {"key": "portal", "offset_days": 0, "when": "always",
     "title": "Invite everyone marked for owner portal access in the intake to Track's owner "
              "portal"},
    {"key": "permit", "offset_days": 0, "when": "no_permit",
     "title": "Get or confirm the nightly rental permit"},
    {"key": "insurance", "offset_days": 1, "when": "has_insurance",
     "title": "Upload the insurance declarations page from the intake to Track"},
    {"key": "insurance_missing", "offset_days": 1, "when": "no_insurance",
     "title": "Get the insurance declarations page from the owner and upload it to Track"},
    {"key": "inspection", "offset_days": 1, "when": "always",
     "title": "Place the Property Onboarding - Inspection Walkthrough hold" + HOLD_NOTE},
    {"key": "maintenance", "offset_days": 2, "when": "always",
     "title": "Place the Property Onboarding - Maintenance Walkthrough hold" + HOLD_NOTE},
    {"key": "bookings", "offset_days": 3, "when": "has_bookings",
     "title": "Bring over the current bookings listed in the intake from the former manager"},
    {"key": "extra_owners", "offset_days": 3, "when": "existing_owner_new_people",
     "title": "Add the new additional owners listed in the intake to the owner in Track"},
    # Owner, 2026-11-23: a new owner's emergency contact goes in its notes; an
    # existing owner is never changed, so a person adds it.
    {"key": "emergency_contact", "offset_days": 3, "when": "existing_owner_emergency",
     "title": "Add the emergency contact from the intake to the owner's notes in Track"},
    {"key": "housekeeping", "offset_days": 4, "when": "always",
     "title": "Place the Property Onboarding - Housekeeping Set Up hold" + HOLD_NOTE},
    {"key": "photography", "offset_days": 6, "when": "always",
     "title": "Place the Property Onboarding - Photography hold" + HOLD_NOTE},
    {"key": "owner_portal_details", "offset_days": 7, "when": "always",
     "title": "Owner adds bank details and Social Security number in the owner portal "
              "(follow up)"},
    {"key": "listing", "offset_days": 14, "when": "always",
     "title": "Finish the listing and make it live"},
    {"key": "place_dates", "offset_days": 14, "when": "has_owner_dates",
     "title": "Right after the listing is made bookable, press Place owner dates now"},
    {"key": "confirm_dates", "offset_days": 15, "when": "has_owner_dates",
     "title": "Confirm the owner's dates were placed"},
]
CHECKLIST_WHEN = ("always", "no_permit", "has_insurance", "no_insurance", "has_bookings",
                  "existing_owner_new_people", "existing_owner_emergency", "has_owner_dates")
#: Checklist items added after forms were made: offered once to a form's
#: checklist (a manager may then remove them).
ADDED_ITEMS = ("emergency_contact",)

#: The message staff copy or open in their own email (owner, 2026-11-19: ENHQ
#: never emails owners). {first_name}, {link}, {signature}, {brand}.
MESSAGE_INVITE = {
    "subject": "Welcome to {brand}: tell us about your home",
    "body": ("Hi {first_name},\n\n"
             "Welcome to {brand}! We're excited to get started. This link takes you to a "
             "short form about you and your home:\n\n{link}\n\n"
             "It saves as you go, so you can stop and come back with the same link. It never "
             "asks for your Social Security number or bank details; you'll add those yourself "
             "in your owner portal later.\n\n"
             "Thank you,\n{signature}"),
}
MESSAGE_REMINDER = {
    "subject": "A quick reminder from {brand}",
    "body": ("Hi {first_name},\n\n"
             "Just a friendly reminder about the form for your home. Everything you've entered "
             "is saved, and the same link picks up where you left off:\n\n{link}\n\n"
             "It never asks for your Social Security number or bank details.\n\n"
             "Thank you,\n{signature}"),
}


def _by_name(rows):
    return {str(r.get("name", "")).strip().lower(): r for r in rows or []}


def sleeps_for_name(name: str) -> tuple[int, bool]:
    """(sleeps, known) for a bed type by Track's name, from the owner's rules:
    2 for a king, queen, double, Murphy bed, futon or any sofa bed except the
    twin one (King Sofa Sleeper, owner 2026-11-23); 1 for a twin, twin sofa bed,
    child bed, trundle, day bed or roll away bed (owner, 2026-11-23); a bunk by
    its two beds; a crib 0. A name that fits none starts at 2, unconfirmed."""
    n = name.strip().lower()
    if "crib" in n:
        return 0, True
    if "bunk" in n:
        parts = re.split(r"\s+over\s+", n.replace("bunk bed", "").replace("bunk", "").strip())
        if len(parts) == 2:
            return sum(1 if "twin" in p and "/" not in p else 2 for p in parts), True
        return 2, False
    if n in ("twin", "twin sofa bed", "child bed", "twin trundle", "twin day bed", "toddler bed",
             "roll away bed", "rollaway bed", "rollaway", "roll away", "roll-away bed"):
        return 1, True
    if n in ("king", "california king", "queen", "double", "full", "murphy bed", "futon") \
            or ("sofa" in n or "sleeper" in n):
        return 2, True
    return 2, False


def other_place_bed(name: str) -> bool:
    """Bed types for "Other places people sleep": sofa beds, futons, Murphy
    beds and roll away beds."""
    n = name.lower()
    return any(word in n for word in ("sofa", "sleeper", "futon", "murphy", "roll"))


def sleeps_table(bed_types, existing=None) -> dict:
    """The sleeps table for these bed types, keeping what a manager already set.
    A bed type new in Track whose name the rules know arrives confirmed; one
    they don't know starts at 2 and is flagged for a manager."""
    table = dict(existing or {})
    for bed in bed_types or []:
        key = str(bed["id"])
        if key in table:
            continue
        sleeps, known = sleeps_for_name(bed["name"])
        table[key] = {"sleeps": sleeps, "label": BED_LABELS.get(bed["name"], bed["name"]),
                      "confirmed": known,
                      "other_places": other_place_bed(bed["name"])}
    return table


def build(lists: dict) -> dict:
    """A new form's settings."""
    amenities = _by_name(lists.get("amenities"))
    common = []
    for key, label, names in COMMON_AMENITIES:
        ids = [amenities[n.lower()]["id"] for n in names if n.lower() in amenities]
        if ids:
            common.append({"key": key, "label": label, "amenity_ids": ids})
    code_types = [c for c in lists.get("code_types") or [] if c.get("isActive", True)]
    fields = {}
    for field in lists.get("custom_fields") or []:
        ref = field.get("reference") or ""
        state = "owner" if ref in OWNER_FIELDS else "staff" if ref in STAFF_FIELDS else "off"
        fields[ref] = {"state": state, "label": field.get("name", ""), "help": "",
                       "section": GENERIC_SECTION}
    contracts = _by_name(lists.get("contracts"))
    contract = contracts.get("standard 30")
    return {
        "common_amenities": common,
        "hidden_groups": list(HIDDEN_GROUPS),
        "lodging_type_ids": [t["id"] for t in lists.get("lodging_types") or []
                             if t.get("isActive", True)],
        "code_type_ids": [c["id"] for c in code_types if c["name"] not in CODE_TYPES_NOT_OFFERED],
        "custom_fields": fields,
        "sleeps": sleeps_table(lists.get("bed_types") or [], None),
        "checklist": [dict(item) for item in CHECKLIST],
        "checklist_offered": list(ADDED_ITEMS),
        "message_invite": dict(MESSAGE_INVITE),
        "message_reminder": dict(MESSAGE_REMINDER),
        # Make's unit call sends no isBookable, and the unit it made (211) is
        # not bookable: new units start the same way until a manager changes it.
        "new_units_bookable": False,
        # Make creates the owner active; so does a real send.
        "owner_active": True,
        "default_contract_id": contract["id"] if contract else None,
        "default_management_agreement": "full_service",
        # Owner, 2026-11-23: on to start with. Send to Track checks everything
        # and writes nothing while it is on.
        "test_mode": True,
    }


def refreshed(settings: dict, lists: dict) -> dict:
    """Settings after a refresh of Track's lists: new bed types and custom
    fields join (flagged or off); nothing a manager set is changed."""
    out = dict(settings)
    out["sleeps"] = sleeps_table(lists.get("bed_types") or [], settings.get("sleeps") or {})
    fields = dict(settings.get("custom_fields") or {})
    refs = {field.get("reference") or "" for field in lists.get("custom_fields") or []}
    for old, new_refs in MOVED_FIELDS.items():
        if (fields.get(old) or {}).get("state") == "owner" \
                and any(r in refs and r not in fields for r in new_refs):
            fields[old] = {**fields[old], "state": "off"}
            for ref in new_refs:
                if ref in refs and ref not in fields:
                    fields[ref] = {"state": "owner", "label": "", "help": "",
                                   "section": GENERIC_SECTION}
    for field in lists.get("custom_fields") or []:
        ref = field.get("reference") or ""
        fields.setdefault(ref, {"state": "off", "label": field.get("name", ""), "help": "",
                                "section": GENERIC_SECTION})
        if not fields[ref].get("label"):
            fields[ref] = {**fields[ref], "label": field.get("name", "")}
    out["custom_fields"] = fields
    offered = set(settings.get("checklist_offered") or [])
    if settings.get("checklist") is not None and any(k not in offered for k in ADDED_ITEMS):
        keys = {item.get("key") for item in settings.get("checklist") or []}
        items = list(settings.get("checklist") or [])
        for item in CHECKLIST:
            if item["key"] in ADDED_ITEMS and item["key"] not in offered and item["key"] not in keys:
                items.append(dict(item))
        out["checklist"] = items
        out["checklist_offered"] = sorted(offered | set(ADDED_ITEMS))
    return out
