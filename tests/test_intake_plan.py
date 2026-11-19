"""Intake forms: the pure parts (defaults, derivations, the send plan).
Lists are SkyRun's real ones, settings only (tests/fixtures/intake)."""

from __future__ import annotations

import json
from datetime import date

from apps.intake import checklist, defaults, derive, plan, schema

from .intake_fake_track import LISTS

SETTINGS = defaults.build(LISTS)


def bed(name):
    return next(b["id"] for b in LISTS["bed_types"] if b["name"] == name)


def fixture(name):
    return next(f["id"] for f in LISTS["bathroom_amenities"] if f["name"] == name)


def answers(**over):
    a = {
        "about": {"first_name": "Alex", "last_name": "Sample", "account_name": "Sample Homes LLC",
                  "street": "12 Pine Way", "city": "Denver", "state": "CO", "postal": "80202",
                  "country": "US", "mobile": "(303) 555-0142", "email": "alex@samplehomes.net",
                  "contact_pref": "text", "heard": "referral", "heard_detail": "a neighbour",
                  "has_extra_owners": "yes",
                  "extra_owners": [{"first_name": "Jo", "last_name": "Sample",
                                    "email": "jo@samplehomes.net", "mobile": "", "portal": True}]},
        "tax": {"kind": "tax_id"},
        "property": {"street": "400 Lift Road", "city": "Park City", "state": "UT",
                     "postal": "84060", "lodging_type_id": 2, "ready": "date",
                     "ready_date": "2030-01-10", "has_bookings": "no", "bookings": []},
        "bedrooms": [{"beds": [{"type": bed("King"), "count": 1}, {"type": bed("Twin"), "count": 2}],
                      "own_bath": False},
                     {"beds": [{"type": bed("Queen"), "count": 1}], "own_bath": True}],
        "other_sleeping": {"has": "yes", "places": [{"where": "living", "label": "",
                                                     "beds": [{"type": bed("Queen Sofa Bed"),
                                                               "count": 1}]}]},
        "bathrooms": [{"fixtures": {str(fixture("Bathtub")): 1, str(fixture("Shower")): 1}},
                      {"fixtures": {str(fixture("Shower")): 1, str(fixture("Sink")): 2}},
                      {"fixtures": {str(fixture("Toilet")): 1, str(fixture("Sink")): 1}}],
        "amenities": {"common": ["dishwasher", "private_hot_tub"], "more": [], "gondola": "yes"},
        "home": {"heating": ["forced_air"], "cooling": ["none"], "parking": ["garage"],
                 "parking_pass": "yes", "wifi": "yes", "wifi_provider": "Mountain Net",
                 "wifi_network": "Cabin", "tv": ["smart_tv"], "tv_count": 3,
                 "trash_by": "company", "trash_provider": "Valley Waste",
                 "trash_days": ["monday", "Thursday"], "hoa": "no", "heat_tape": "yes",
                 "heat_tape_by": "HOA", "snow_by": "hoa", "landscaping_by": "owner",
                 "softener": "yes", "softener_note": "In the garage", "permit": "yes",
                 "permit_number": "P-000123"},
        "access": {"door": "smart_lock", "owner_closet": "yes", "alarm": "yes",
                   "extra_codes": [{"type": 2}]},
        "stays": {"has": "yes", "ranges": [{"start": "2030-02-01", "end": "2030-02-08"}]},
        "custom": {"pms_units_coffee_maker_type": "Keurig Coffee Maker"},
    }
    a.update(over)
    return schema.clean(a, custom_allowed={"pms_units_coffee_maker_type"})


def staff(**over):
    a = answers()
    s = derive.staff_with_defaults({"node_id": 24, **over}, a, SETTINGS, LISTS)
    return s


# ------------------------------------------------------------ defaults

def test_defaults_come_from_skyruns_lists_by_name():
    common = {c["key"]: c["amenity_ids"] for c in SETTINGS["common_amenities"]}
    assert len(common) == 18
    assert common["washer_dryer"] == [235, 185]
    assert common["community_pool"] == [1335] and common["community_hot_tub"] == [1320]
    states = SETTINGS["custom_fields"]
    assert sum(1 for s in states.values() if s["state"] == "owner") == 23
    assert sum(1 for s in states.values() if s["state"] == "staff") == 8
    assert len(states) == 72
    assert SETTINGS["new_units_bookable"] is False and SETTINGS["owner_active"] is True
    assert SETTINGS["default_contract_id"] == 1
    assert "Master Programming Code" not in {c["name"] for c in LISTS["code_types"]
                                             if c["id"] in SETTINGS["code_type_ids"]}


def test_the_sleeps_table_follows_the_owners_rules():
    table = {b["name"]: SETTINGS["sleeps"][str(b["id"])] for b in LISTS["bed_types"]}
    expect = {"King": 2, "California King": 2, "Queen": 2, "Double": 2, "Murphy Bed": 2,
              "Futon": 2, "Queen Sofa Bed": 2, "Double Sleeper Sofa": 2, "Twin": 1,
              "Twin Sofa Bed": 1, "Child Bed": 1, "Twin Trundle": 1, "Twin Day Bed": 1,
              "Crib": 0, "Twin Over Twin Bunk Bed": 2, "Twin Over Double/Queen Bunk Bed": 3,
              "Double/Queen Over Double/Queen Bunk Bed": 4, "Twin Over Full Bunk Bed": 3}
    for name, sleeps in expect.items():
        assert table[name]["sleeps"] == sleeps, name
    assert table["Double"]["label"] == "Double (Full)"
    assert table["Double Sleeper Sofa"]["label"] == "Double (Full) Sleeper Sofa"
    assert table["Queen Sofa Bed"]["other_places"] and not table["King"]["other_places"]


def test_a_bed_type_new_in_track_starts_at_two_flagged():
    lists = {**LISTS, "bed_types": LISTS["bed_types"] + [{"id": 99, "name": "Hammock Bed",
                                                         "isActive": True}]}
    refreshed = defaults.refreshed(SETTINGS, lists)
    assert refreshed["sleeps"]["99"] == {"sleeps": 2, "label": "Hammock Bed",
                                         "confirmed": False, "other_places": False}


# ------------------------------------------------------------ rooms

def test_bathroom_type_is_worked_out_from_its_fixtures():
    assert derive.bath_type({str(fixture("Bathtub")): 1, str(fixture("Shower")): 1},
                            LISTS) == "full_bathroom"
    assert derive.bath_type({str(fixture("Shower")): 1, str(fixture("Sink")): 2},
                            LISTS) == "three_quarter_bathroom"
    assert derive.bath_type({str(fixture("Toilet")): 1, str(fixture("Sink")): 1},
                            LISTS) == "half_bathroom"
    assert derive.bath_type({str(fixture("Jetted Bathtub")): 1}, LISTS) == "full_bathroom"
    assert derive.bath_type({str(fixture("Shower Chair")): 1}, LISTS) == "half_bathroom"


def test_rooms_sleeps_and_summaries():
    a = answers()
    rooms = derive.rooms(a, SETTINGS, LISTS)
    assert [r["roomType"] for r in rooms] == ["bedroom", "bedroom", "common", "full_bathroom",
                                              "three_quarter_bathroom", "half_bathroom"]
    assert rooms[0]["sleeps"] == 4 and rooms[1]["hasAttachedBathroom"] is True
    assert derive.room_summary("Bedroom 1", rooms[0]["beds"], SETTINGS, LISTS) == \
        "Bedroom 1: King x1, Twin x2, sleeps 4"
    assert rooms[2]["name"] == "Living room" and rooms[2]["sleeps"] == 2
    assert derive.total_sleeps(a, SETTINGS, LISTS) == 8
    assert derive.total_sleeps(a, SETTINGS, LISTS, {"sleeps_total": 7}) == 7
    assert derive.counts(a, LISTS) == {"bedrooms": 2, "full": 1, "three_quarter": 1, "half": 1}
    overridden = derive.rooms(a, SETTINGS, LISTS, {"bath_types": {"2": "three_quarter_bathroom"}})
    assert overridden[-1]["roomType"] == "three_quarter_bathroom"
    assert overridden[-1]["worked_out"] == "half_bathroom"


def test_unit_type_and_name_are_preselected():
    s = staff()
    assert s["unit_type_id"] == 5                       # "2 Bedrooms"
    assert s["unit_name"] == "400 Lift Road" and s["start_date"] == "2030-01-10"
    assert s["contract_effective_date"] == "2030-01-10" and s["contract_id"] == 1
    assert derive.unit_type_for(0, LISTS) == 2           # Studio
    assert derive.staff_defaults(answers(), SETTINGS, LISTS)["node_id"] is None


# ------------------------------------------------------------ amenities and fields

def test_worked_out_amenities_say_why_and_skip_what_the_area_has():
    a = answers()
    found = {d["name"]: d["why"] for d in derive.derived_amenities(a, LISTS, None)}
    assert found["Wifi"] == "Wi-Fi: yes" and found["Resort Access"].startswith("Gondola")
    assert found["Heat Tape"] == "Heat tape: yes" and "Water Softener" in found
    in_area = {d["name"] for d in derive.derived_amenities(a, LISTS, 24)}
    assert "Wifi" not in in_area                         # every SkyRun area has Wi-Fi
    unticked = derive.chosen_amenities(a, SETTINGS, LISTS, {"untick": [900]})
    assert 900 not in {x["id"] for x in unticked}


def test_custom_values_go_by_handle_and_respect_states():
    a = answers()
    values = derive.custom_values(a, staff(), SETTINGS, LISTS)
    assert values["pms_units_trash_pickup_day"] == ["monday", "thursday"]
    assert values["pms_units_coffee_maker_type"] == "keurig_coffee"     # a name became a handle
    assert values["pms_units_wifi_password"] == {"$secret": "wifi_password"}
    assert values["pms_units_management_agreement_type"] == "full_service"
    assert values["pms_units_trigger_automation_keywords"] == [
        "Unit has Parking Pass that Requires Return",
        "Unit has Hot Tub that Requires Service Every Few Days", "Unit Does Not Have AC"]
    assert "Landscaping: I take care of it." in values[
        "pms_units_other_maintenance_or_service_notes"]
    off = {**SETTINGS, "custom_fields": {**SETTINGS["custom_fields"],
                                         "pms_units_wifi_password": {"state": "off"}}}
    assert "pms_units_wifi_password" not in derive.custom_values(a, staff(), off, LISTS)


# ------------------------------------------------------------ the plan

def test_new_owner_plan_order_and_bodies():
    p = plan.build(answers=answers(), staff=staff(), settings=SETTINGS, lists=LISTS,
                   brand="Mountain Stays", has_tax_id=True, today=date(2026, 11, 20))
    keys = [s["key"] for s in p["steps"]]
    assert keys[:6] == ["contact:0", "contact:1", "owner", "link:0", "link:1", "unit"]
    assert keys[-1] == "ownership" and "details" in keys and "count:tv" in keys
    assert {"code:door", "code:owner_closet", "code:alarm", "code:extra-0"} <= set(keys)
    assert p["problems"] == []
    by = {s["key"]: s for s in p["steps"]}
    assert by["owner"]["body"]["taxId"] == {"$secret": "tax_id"}
    assert by["owner"]["body"]["isActive"] is True and by["owner"]["body"]["phone"] == "+13035550142"
    assert "Preferred contact: Text message." in by["owner"]["body"]["notes"]
    assert by["unit"]["body"]["isActive"] is False and by["unit"]["body"]["isBookable"] is False
    assert by["unit"]["body"]["useRoomConfiguration"] is True
    assert by["unit"]["body"]["maxOccupancy"] == 8
    assert all("roomType" in s["body"] for s in p["steps"] if s["key"].startswith("room:"))
    assert by["code:door"]["body"]["code"] == {"$secret": "code:door"}
    assert by["ownership"]["body"]["contractType"] == "standard"
    assert by["ownership"]["body"]["taxMode"] == "pmc"
    assert by["link:0"]["body"] == {"contactId": "{contact:0}", "isPrimaryContact": True}
    flat = json.dumps(p)
    assert "P-000123" in flat           # the permit is not a secret; codes and passwords are


def test_existing_owner_plan_writes_nothing_to_the_owner():
    s = staff(owner_mode="existing", existing_owner_id=900)
    p = plan.build(answers=answers(), staff=s, settings=SETTINGS, lists=LISTS, brand="X",
                   has_tax_id=True)
    keys = [step["key"] for step in p["steps"]]
    assert not any(k.startswith(("contact:", "link:")) or k == "owner" for k in keys)
    assert keys[0] == "unit" and keys[-1] == "ownership"
    assert "Nothing about that owner" in p["summary"][0]


def test_plan_problems_block_a_send():
    bad = answers(about={**answers()["about"], "email": "alex@example.com"})
    p = plan.build(answers=bad, staff=derive.staff_with_defaults({}, bad, SETTINGS, LISTS),
                   settings=SETTINGS, lists=LISTS, brand="X", has_tax_id=False)
    text = " ".join(p["problems"])
    assert "test domain" in text and "Pick the area" in text
    assert any("Tax ID was chosen" in w for w in p["warnings"])


def test_the_proof_can_keep_the_owner_inactive():
    p = plan.build(answers=answers(), staff=staff(), settings=SETTINGS, lists=LISTS, brand="X",
                   has_tax_id=False, owner_active=False, unit_bookable=False)
    owner = next(s for s in p["steps"] if s["key"] == "owner")
    assert owner["body"]["isActive"] is False and "taxId" not in owner["body"]


def test_checklist_counts_from_the_ready_date_or_the_send_day():
    a = answers()
    assert checklist.base_day(a, date(2029, 12, 1)) == date(2030, 1, 10)
    assert checklist.base_day(a, date(2030, 2, 1)) == date(2030, 2, 1)      # already past
    blank = answers(property={**a["property"], "ready": "unsure", "ready_date": ""})
    assert checklist.base_day(blank, date(2030, 2, 1)) == date(2030, 2, 1)


def test_no_checklist_title_names_anyone():
    for item in defaults.CHECKLIST:
        assert item["when"] in defaults.CHECKLIST_WHEN
    holds = [i for i in defaults.CHECKLIST if "Onboarding" in i["title"]]
    assert len(holds) == 4 and all("needs the unit bookable in Track" in i["title"]
                                   for i in holds)
    assert any(i["title"] == "Right after the listing is made bookable, press Place owner "
                             "dates now" for i in defaults.CHECKLIST)
