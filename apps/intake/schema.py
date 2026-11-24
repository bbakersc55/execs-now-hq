"""The "New owner and property" form: its sections, its choices, and how an
answer is cleaned before it is saved. One source: the API serves `OPTIONS`
and `SECTIONS` to the form, so the screens and the server never disagree.

Answers are one JSON document per submission, by section. Sensitive values
(the tax id, codes, the Wi-Fi password) are never in it; see `secrets.py`.
"""

from __future__ import annotations

import re
from datetime import date

SECTIONS = [
    ("welcome", "Welcome"),
    ("about", "About you"),
    ("tax", "Tax details"),
    ("property", "The property"),
    ("bedrooms", "Bedrooms"),
    ("other_sleeping", "Other places people sleep"),
    ("bathrooms", "Bathrooms"),
    ("amenities", "Amenities"),
    ("home", "Home details"),
    ("access", "Getting in"),
    ("stays", "Your own stays"),
    ("documents", "Documents"),
    ("review", "Review and submit"),
]

OPTIONS = {
    "contact_pref": [("text", "Text message"), ("call", "Phone call"), ("email", "Email")],
    "heard": [("referral", "Someone referred me"), ("search", "Online search"),
              ("social", "Social media"), ("owner", "Another owner"),
              ("sign", "A sign or a vehicle"), ("other", "Something else")],
    # Owner, 2026-11-24: which number goes on the rental permit, or a call.
    "tax_kind": [("tax_id", "My business tax ID (EIN)"),
                 ("ssn", "My Social Security number or ITIN"),
                 ("phone", "I'd rather give it by phone")],
    # The phone choice: which number staff were given on the call.
    "tax_phone_kind": [("tax_id", "Their business tax ID (EIN)"),
                       ("ssn", "Their Social Security number or ITIN")],
    "ready": [("now", "It's ready now"), ("date", "On a date"), ("unsure", "Not sure yet")],
    "yes_no": [("yes", "Yes"), ("no", "No")],
    "yes_no_unsure": [("yes", "Yes"), ("no", "No"), ("unsure", "Not sure")],
    "where": [("living", "Living room"), ("den", "Den or family room"), ("loft", "Loft"),
              ("bonus", "Bonus or media room"), ("other", "Somewhere else")],
    "heating": [("forced_air", "Forced-air furnace"), ("baseboard", "Electric baseboard"),
                ("radiant", "Radiant floor or boiler"), ("heat_pump", "Heat pump or mini-split"),
                ("other", "Something else")],
    "cooling": [("central", "Central air conditioning"), ("mini_split", "Mini-split"),
                ("window", "Window or portable units"), ("fans", "Ceiling fans only"),
                ("none", "No air conditioning")],
    "parking": [("garage", "Garage"), ("driveway", "Driveway"), ("assigned", "Assigned spot"),
                ("shared_lot", "Shared lot"), ("street", "Street parking")],
    "tv": [("smart_tv", "Smart TV"), ("cable", "Cable or satellite"),
           ("streaming", "Streaming device (Roku, Apple TV, Fire TV)")],
    "trash_by": [("hoa", "The HOA, or a community dumpster"), ("city", "The city"),
                 ("company", "A company I pay"), ("unsure", "Not sure")],
    "done_by": [("hoa", "The HOA"), ("company", "A company"), ("owner", "I take care of it"),
                ("unsure", "Not sure")],
    "door": [("smart_lock", "Wi-Fi smart lock"), ("keypad", "Keypad lock (not on Wi-Fi)"),
             ("lockbox", "Lockbox"), ("key", "A key only"), ("unsure", "Not sure")],
    # Whether each needs a code is part of the answer (owner, 2026-11-20): a
    # closet that opens with a key, or an alarm without a code, plans no code
    # step. An answer of "yes" from before then reads as "code".
    "owner_closet": [("code", "Yes, it opens with a code"), ("key", "Yes, it opens with a key"),
                     ("no", "No")],
    "alarm": [("code", "Yes, it's set with a code"), ("no_code", "Yes, but it has no code"),
              ("no", "No")],
}

#: A closet or alarm answer that comes with a code to enter.
WITH_CODE = ("code", "yes")

#: Custom fields fed by a built-in question: reference -> how it is worded.
BUILTIN_FIELDS = {
    "pms_units_wifi_network_name": "Wi-Fi network name",
    "pms_units_wifi_password": "Wi-Fi password",
    "pms_units_wifi_router_location_notes": "Where the router is",
    "pms_units_internet_service_provider": "Internet provider",
    "pms_units_cable_or_satellite_tv_provider": "TV provider",
    "pms_units_cable_or_satellite_tv_notes": "TV setup",
    "pms_units_trash_service_provider": "Who collects the trash",
    "pms_units_trash_pickup_day": "Pickup days",
    "pms_units_trash_notes": "Trash notes",
    "pms_units_hoa_management_company_name": "HOA management company",
    "pms_units_hoa_management_company_point_of_contact": "HOA contact person",
    "pms_units_hoa_management_company_phone_number": "HOA phone",
    "pms_units_hoa_management_company_email_address": "HOA email",
    "pms_units_hoa_management_company_other_notes": "HOA notes",
    "pms_units_heat_tape_notes": "Heat tape",
    "pms_units_snow_plowing_provider": "Snow removal",
    "pms_units_snow_shoveling_provider": "Snow removal",
    "pms_units_snow_plowing_notes": "Snow removal notes",
    "pms_units_nightly_rental_permit": "Rental permit number",
    "pms_units_hvac_notes": "Heating and cooling",
    "pms_units_parking_instructions": "Parking",
    "pms_units_water_softener": "Water softener",
    "pms_units_landscaping": "Landscaping",
}

#: Code slots with their own questions; extras are "extra-<n>".
CODE_SLOTS = ("door", "owner_closet", "alarm")
MOST_EXTRA_CODES = 8
MOST_EXTRA_OWNERS = 6
MOST_ROOMS = 30
MOST_BEDS_PER_ROOM = 12
MOST_RANGES = 20
SHORT, MEDIUM, LONG = 120, 300, 2000

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def option_keys(name):
    return {key for key, _ in OPTIONS[name]}


def label(name, key):
    return dict(OPTIONS[name]).get(key, "")


# ------------------------------------------------------------ cleaning
def _text(value, most=SHORT) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())[:most] if most <= SHORT else str(value).strip()[:most]


def _choice(value, name) -> str:
    value = str(value or "")
    return value if value in option_keys(name) else ""


def _choices(value, name) -> list:
    keys = option_keys(name)
    return [v for v in dict.fromkeys(value or []) if isinstance(v, str) and v in keys]


def _int(value, lo=0, hi=99):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return max(lo, min(hi, number))


def _date(value) -> str:
    try:
        return date.fromisoformat(str(value or "")[:10]).isoformat()
    except ValueError:
        return ""


def _ranges(value) -> list:
    out = []
    for item in (value or [])[:MOST_RANGES]:
        if not isinstance(item, dict):
            continue
        start, end = _date(item.get("start")), _date(item.get("end"))
        if start or end:
            out.append({"start": start, "end": end})
    return out


def _beds(value) -> list:
    out = []
    for item in (value or [])[:MOST_BEDS_PER_ROOM]:
        if not isinstance(item, dict):
            continue
        type_id, count = _int(item.get("type"), 0, 10**9), _int(item.get("count"), 0, 20)
        if type_id and count:
            out.append({"type": type_id, "count": count})
    return out


def email_ok(value: str) -> bool:
    return bool(_EMAIL.match(value or ""))


def clean_about(data) -> dict:
    data = data if isinstance(data, dict) else {}
    extras = []
    for item in (data.get("extra_owners") or [])[:MOST_EXTRA_OWNERS]:
        if not isinstance(item, dict):
            continue
        extras.append({"first_name": _text(item.get("first_name"), 80),
                       "last_name": _text(item.get("last_name"), 80),
                       "email": _text(item.get("email"), 200).lower(),
                       "mobile": _text(item.get("mobile"), 40),
                       "portal": item.get("portal") is True})
    return {
        "first_name": _text(data.get("first_name"), 80),
        "last_name": _text(data.get("last_name"), 80),
        "account_name": _text(data.get("account_name")),
        "street": _text(data.get("street")), "street2": _text(data.get("street2")),
        "city": _text(data.get("city"), 80), "state": _text(data.get("state"), 40),
        "postal": _text(data.get("postal"), 16), "country": _text(data.get("country"), 2).upper()
        or "US",
        "mobile": _text(data.get("mobile"), 40),
        "email": _text(data.get("email"), 200).lower(),
        "contact_pref": _choice(data.get("contact_pref"), "contact_pref"),
        "heard": _choice(data.get("heard"), "heard"),
        "heard_detail": _text(data.get("heard_detail")),
        "has_extra_owners": _choice(data.get("has_extra_owners"), "yes_no"),
        "extra_owners": extras,
        # Owner, 2026-11-23: someone to call in an emergency.
        "emergency": _emergency(data.get("emergency")),
    }


def _emergency(value) -> dict:
    d = value if isinstance(value, dict) else {}
    return {"name": _text(d.get("name"), 120), "address": _text(d.get("address"), MEDIUM),
            "phone": _text(d.get("phone"), 40)}


def clean_tax(data) -> dict:
    data = data if isinstance(data, dict) else {}
    return {"kind": _choice(data.get("kind"), "tax_kind"),
            "phone_kind": _choice(data.get("phone_kind"), "tax_phone_kind")}


def clean_property(data) -> dict:
    data = data if isinstance(data, dict) else {}
    return {
        "street": _text(data.get("street")), "street2": _text(data.get("street2")),
        "city": _text(data.get("city"), 80), "state": _text(data.get("state"), 40),
        "postal": _text(data.get("postal"), 16),
        # Owner, 2026-11-23: goes to the unit's `area` in Track.
        "square_feet": _int(str(data.get("square_feet") or "").replace(",", "") or None,
                            0, 100000) or None,
        "lodging_type_id": _int(data.get("lodging_type_id"), 0, 10**9),
        "ready": _choice(data.get("ready"), "ready"),
        "ready_date": _date(data.get("ready_date")),
        "has_bookings": _choice(data.get("has_bookings"), "yes_no"),
        "bookings": _ranges(data.get("bookings")),
    }


def clean_bedrooms(data) -> list:
    out = []
    for item in (data or [])[:MOST_ROOMS]:
        if isinstance(item, dict):
            out.append({"beds": _beds(item.get("beds")), "own_bath": item.get("own_bath") is True})
    return out


def clean_other_sleeping(data) -> dict:
    data = data if isinstance(data, dict) else {}
    places = []
    for item in (data.get("places") or [])[:MOST_ROOMS]:
        if isinstance(item, dict):
            places.append({"where": _choice(item.get("where"), "where"),
                           "label": _text(item.get("label"), 60),
                           "beds": _beds(item.get("beds"))})
    return {"has": _choice(data.get("has"), "yes_no"), "places": places}


def clean_bathrooms(data) -> list:
    out = []
    for item in (data or [])[:MOST_ROOMS]:
        if not isinstance(item, dict):
            continue
        fixtures = {}
        for key, count in (item.get("fixtures") or {}).items():
            fixture, number = _int(key, 0, 10**9), _int(count, 0, 9)
            if fixture and number:
                fixtures[str(fixture)] = number
        out.append({"fixtures": fixtures})
    return out


def clean_amenities(data) -> dict:
    data = data if isinstance(data, dict) else {}
    common = [k for k in dict.fromkeys(data.get("common") or []) if isinstance(k, str)][:60]
    more = [i for i in (_int(v, 0, 10**9) for v in (data.get("more") or [])[:200]) if i]
    return {"common": common, "more": list(dict.fromkeys(more)),
            "gondola": _choice(data.get("gondola"), "yes_no")}


def clean_home(data) -> dict:
    d = data if isinstance(data, dict) else {}
    return {
        "heating": _choices(d.get("heating"), "heating"),
        "cooling": _choices(d.get("cooling"), "cooling"),
        "hvac_note": _text(d.get("hvac_note"), MEDIUM),
        "parking": _choices(d.get("parking"), "parking"),
        "parking_pass": _choice(d.get("parking_pass"), "yes_no"),
        "parking_note": _text(d.get("parking_note"), MEDIUM),
        "wifi": _choice(d.get("wifi"), "yes_no"),
        "wifi_provider": _text(d.get("wifi_provider")),
        "wifi_network": _text(d.get("wifi_network")),
        "wifi_router": _text(d.get("wifi_router"), MEDIUM),
        "tv": _choices(d.get("tv"), "tv"),
        "tv_count": _int(d.get("tv_count"), 0, 20) or 0,
        "tv_provider": _text(d.get("tv_provider")),
        "tv_note": _text(d.get("tv_note"), MEDIUM),
        "trash_by": _choice(d.get("trash_by"), "trash_by"),
        "trash_provider": _text(d.get("trash_provider")),
        "trash_days": [v for v in dict.fromkeys(d.get("trash_days") or [])
                       if isinstance(v, str) and len(v) <= 80][:7],
        "trash_note": _text(d.get("trash_note"), MEDIUM),
        "hoa": _choice(d.get("hoa"), "yes_no_unsure"),
        "hoa_company": _text(d.get("hoa_company")),
        "hoa_contact": _text(d.get("hoa_contact")),
        "hoa_phone": _text(d.get("hoa_phone"), 40),
        "hoa_email": _text(d.get("hoa_email"), 200).lower(),
        "hoa_note": _text(d.get("hoa_note"), MEDIUM),
        "heat_tape": _choice(d.get("heat_tape"), "yes_no_unsure"),
        "heat_tape_by": _text(d.get("heat_tape_by")),
        "snow_by": _choice(d.get("snow_by"), "done_by"),
        "snow_provider": _text(d.get("snow_provider")),
        "snow_note": _text(d.get("snow_note"), MEDIUM),
        "landscaping_by": _choice(d.get("landscaping_by"), "done_by"),
        "landscaping_note": _text(d.get("landscaping_note"), MEDIUM),
        "softener": _choice(d.get("softener"), "yes_no_unsure"),
        "softener_note": _text(d.get("softener_note"), MEDIUM),
        "permit": _choice(d.get("permit"), "yes_no_unsure"),
        "permit_number": _text(d.get("permit_number"), 60),
    }


def _was_yes(value):
    """A closet or alarm answered "yes" before the question said how it opens."""
    return "code" if value == "yes" else value


def clean_access(data) -> dict:
    d = data if isinstance(data, dict) else {}
    extras = []
    for item in (d.get("extra_codes") or [])[:MOST_EXTRA_CODES]:
        if isinstance(item, dict):
            extras.append({"type": _int(item.get("type"), 0, 10**9) or 0})
    return {"door": _choice(d.get("door"), "door"),
            "owner_closet": _choice(_was_yes(d.get("owner_closet")), "owner_closet"),
            "alarm": _choice(_was_yes(d.get("alarm")), "alarm"),
            "extra_codes": extras}


def clean_stays(data) -> dict:
    d = data if isinstance(data, dict) else {}
    return {"has": _choice(d.get("has"), "yes_no"), "ranges": _ranges(d.get("ranges"))}


def clean_custom(data, allowed: set) -> dict:
    """Owner-answered custom fields without a built-in question: by reference."""
    out = {}
    for ref, value in (data or {}).items() if isinstance(data, dict) else ():
        if ref not in allowed:
            continue
        if isinstance(value, list):
            out[ref] = [str(v)[:80] for v in value if isinstance(v, (str, int))][:20]
        elif isinstance(value, (str, int)):
            out[ref] = str(value).strip()[:LONG]
    return out


CLEANERS = {"about": clean_about, "tax": clean_tax, "property": clean_property,
            "bedrooms": clean_bedrooms, "other_sleeping": clean_other_sleeping,
            "bathrooms": clean_bathrooms, "amenities": clean_amenities, "home": clean_home,
            "access": clean_access, "stays": clean_stays}


def clean(answers: dict, *, custom_allowed: set) -> dict:
    """A whole answers document, cleaned; unknown sections dropped."""
    answers = answers if isinstance(answers, dict) else {}
    out = {name: fn(answers.get(name)) for name, fn in CLEANERS.items()}
    out["custom"] = clean_custom(answers.get("custom"), custom_allowed)
    return out


def merge(current: dict, section: str, value, *, custom_allowed: set) -> dict:
    """`current` with one section replaced by its cleaned new value."""
    if section != "custom" and section not in CLEANERS:
        raise ValueError(f"No section called {section!r}.")
    merged = dict(current or {})
    merged[section] = value
    return clean(merged, custom_allowed=custom_allowed)
