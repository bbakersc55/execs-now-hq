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


TODAY = date(2026, 11, 19)  # the practice's date; never the server's
#: Every sensitive value `answers()` calls for, all held.
HELD = {"tax_id", "wifi_password", "code:door", "code:owner_closet", "code:alarm",
        "code:extra-0"}


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
    s = derive.staff_with_defaults({"node_id": 24, **over}, a, SETTINGS, LISTS, TODAY)
    return s


# ------------------------------------------------------------ defaults

def test_defaults_come_from_skyruns_lists_by_name():
    common = {c["key"]: c["amenity_ids"] for c in SETTINGS["common_amenities"]}
    assert len(common) == 18
    assert common["washer_dryer"] == [235, 185]
    assert common["community_pool"] == [1335] and common["community_hot_tub"] == [1320]
    states = SETTINGS["custom_fields"]
    assert sum(1 for s in states.values() if s["state"] == "owner") == 24       # the two new fields in, Other Maintenance out
    assert sum(1 for s in states.values() if s["state"] == "staff") == 8
    assert len(states) == 74                    # 72, and Water Softener and Landscaping
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
              "Double/Queen Over Double/Queen Bunk Bed": 4, "Twin Over Full Bunk Bed": 3,
              # Owner, 2026-11-23: the two SkyRun added.
              "King Sofa Sleeper": 2, "Roll Away Bed": 1}
    for name, sleeps in expect.items():
        assert table[name]["sleeps"] == sleeps, name
    assert table["Double"]["label"] == "Double (Full)"
    assert table["Double Sleeper Sofa"]["label"] == "Double (Full) Sleeper Sofa"
    assert table["Queen Sofa Bed"]["other_places"] and not table["King"]["other_places"]
    assert table["Roll Away Bed"]["other_places"] and table["King Sofa Sleeper"]["other_places"]


def test_the_new_bed_types_arrive_confirmed_on_a_refresh():
    """Owner, 2026-11-23: King Sofa Sleeper sleeps 2 and Roll Away Bed 1; a
    name the rules know needs no manager's confirmation."""
    before = {**SETTINGS, "sleeps": {k: v for k, v in SETTINGS["sleeps"].items()
                                     if k not in ("20", "21")}}
    refreshed = defaults.refreshed(before, LISTS)
    assert refreshed["sleeps"]["20"] == {"sleeps": 2, "label": "King Sofa Sleeper",
                                         "confirmed": True, "other_places": True}
    assert refreshed["sleeps"]["21"] == {"sleeps": 1, "label": "Roll Away Bed",
                                         "confirmed": True, "other_places": True}


def test_the_two_answers_move_to_their_own_fields_once():
    """A form whose Other Maintenance or Service Notes was "owner" (it carried
    the two answers) gets the two new fields as "owner" and the old one off,
    once; a manager's later choice stands."""
    old = "pms_units_other_maintenance_or_service_notes"
    fields = {k: v for k, v in SETTINGS["custom_fields"].items()
              if k not in ("pms_units_water_softener", "pms_units_landscaping")}
    fields[old] = {"state": "owner", "label": "Other Maintenance or Service Notes", "help": "",
                   "section": "home"}
    moved = defaults.refreshed({**SETTINGS, "custom_fields": fields}, LISTS)["custom_fields"]
    assert moved[old]["state"] == "off"
    assert moved["pms_units_water_softener"]["state"] == "owner"
    assert moved["pms_units_landscaping"]["state"] == "owner"
    assert moved["pms_units_landscaping"]["label"] == "Landscaping"
    moved[old] = {**moved[old], "state": "owner"}            # a manager switches it back
    again = defaults.refreshed({**SETTINGS, "custom_fields": moved}, LISTS)["custom_fields"]
    assert again[old]["state"] == "owner"


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
    assert derive.staff_defaults(answers(), SETTINGS, LISTS, TODAY)["node_id"] is None


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
    # Owner, 2026-11-23: each to its own field, not Other Maintenance or Service Notes.
    assert values["pms_units_landscaping"].startswith("I take care of it.")
    assert values["pms_units_water_softener"].startswith("Yes.")
    assert "pms_units_other_maintenance_or_service_notes" not in values
    off = {**SETTINGS, "custom_fields": {**SETTINGS["custom_fields"],
                                         "pms_units_wifi_password": {"state": "off"}}}
    assert "pms_units_wifi_password" not in derive.custom_values(a, staff(), off, LISTS)


# ------------------------------------------------------------ the plan

def test_new_owner_plan_order_and_bodies():
    p = plan.build(answers=answers(), staff=staff(), settings=SETTINGS, lists=LISTS,
                   brand="Mountain Stays", held=HELD, today=date(2026, 11, 20))
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
                   held=HELD, today=TODAY)
    keys = [step["key"] for step in p["steps"]]
    assert not any(k.startswith(("contact:", "link:")) or k == "owner" for k in keys)
    assert keys[0] == "unit" and keys[-1] == "ownership"
    assert "Nothing about that owner" in p["summary"][0]


def test_plan_problems_block_a_send():
    bad = answers(about={**answers()["about"], "email": "alex@example.com"})
    p = plan.build(answers=bad, staff=derive.staff_with_defaults({}, bad, SETTINGS, LISTS, TODAY),
                   settings=SETTINGS, lists=LISTS, brand="X", held=set(), today=TODAY)
    text = " ".join(p["problems"])
    assert "test domain" in text and "Pick the area" in text
    # A missing Tax ID stops a send now; it is no longer a note beside it.
    assert "The business Tax ID isn't in ENHQ: enter it beside its question, or mark that " \
        "there is none." in p["problems"]
    assert not any("Tax ID" in w for w in p["warnings"])


def test_the_proof_can_keep_the_owner_inactive():
    p = plan.build(answers=answers(), staff=staff(), settings=SETTINGS, lists=LISTS, brand="X",
                   held=HELD - {"tax_id"}, owner_active=False, unit_bookable=False,
                   today=TODAY)
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


# ------------------------------------------------------------ sensitive values
# Owner, 2026-11-20, after intake #1 stopped at "Add the door code": a code
# was never saved (the form wanted its own Save), and the plan made the step
# anyway. Never start a send that can't finish.

def build(a=None, held=HELD, sent=frozenset(), **staff_over):
    a = a or answers()
    s = derive.staff_with_defaults({"node_id": 24, **staff_over}, a, SETTINGS, LISTS, TODAY)
    return plan.build(answers=a, staff=s, settings=SETTINGS, lists=LISTS, brand="X",
                      held=held, sent=sent, today=TODAY)


def states(p):
    return {item["name"]: item["state"] for item in p["secrets"]}


def test_a_code_step_is_planned_only_for_a_code_that_is_held():
    p = build(held=HELD - {"code:door", "code:alarm", "wifi_password"})
    assert "The Wi-Fi password isn't in ENHQ: enter it beside its question, or mark that " \
        "there is none." in p["problems"]
    keys = {s["key"] for s in p["steps"]}
    assert "code:door" not in keys and "code:alarm" not in keys
    assert {"code:owner_closet", "code:extra-0"} <= keys
    assert "The door code isn't in ENHQ: enter it beside its question, or mark that there " \
        "is none." in p["problems"]
    assert any(x.startswith("The alarm code isn't in ENHQ") for x in p["problems"])
    assert states(p)["code:door"] == "missing" and states(p)["code:owner_closet"] == "held"
    assert "2 access codes (values hidden)" in " ".join(p["summary"])


def test_marked_as_none_it_is_left_out_and_stops_nothing():
    p = build(held=HELD - {"code:door", "tax_id", "wifi_password"},
              no_value=["code:door", "tax_id", "wifi_password"])
    assert p["problems"] == []
    assert states(p) == {"tax_id": "none", "wifi_password": "none", "code:door": "none",
                         "code:owner_closet": "held", "code:alarm": "held",
                         "code:extra-0": "held"}
    by = {s["key"]: s for s in p["steps"]}
    assert "code:door" not in by and "taxId" not in by["owner"]["body"]
    assert "pms_units_wifi_password" not in by["details"]["body"]["custom"]
    assert by["details"]["confirms"] == []
    assert "pms_units_wifi_network_name" in by["details"]["body"]["custom"]
    text = " ".join(p["summary"])
    assert "No door code is sent: marked as having none." in text
    assert "No business Tax ID is sent: marked as having none." in text
    assert "No Wi-Fi password is sent: marked as having none." in text
    # Entered after all, it is sent: the mark no longer matters.
    p = build(held=HELD, no_value=["code:door"])
    assert "code:door" in {s["key"] for s in p["steps"]} and states(p)["code:door"] == "held"


def test_none_marks_keep_known_names_only():
    assert plan.clean_none_marks(["code:door", "code:door", "tax_id", "rm -rf", 7,
                                  "code:" + "x" * 30, "wifi_password"]) == \
        ["code:door", "tax_id", "wifi_password"]
    assert plan.clean_none_marks("code:door") == []


def test_a_closet_that_opens_with_a_key_needs_no_code():
    a = answers(access={"door": "keypad", "owner_closet": "key", "alarm": "no",
                        "extra_codes": []})
    assert [c["slot"] for c in derive.code_slots(a, LISTS, SETTINGS)] == ["door"]
    p = build(a, held={"tax_id", "wifi_password", "code:door"})
    assert p["problems"] == []
    assert [s["key"] for s in p["steps"] if s["key"].startswith("code:")] == ["code:door"]
    assert [x["name"] for x in p["secrets"]] == ["tax_id", "wifi_password", "code:door"]
    # With a code, it needs one.
    a = answers(access={"door": "key", "owner_closet": "code", "alarm": "no"})
    assert [c["slot"] for c in derive.code_slots(a, LISTS, SETTINGS)] == ["owner_closet"]
    assert any(x.startswith("The owner closet code isn't in ENHQ")
               for x in build(a, held={"tax_id", "wifi_password"})["problems"])


def test_the_door_and_the_alarm_ask_for_a_code_only_when_they_have_one():
    a = answers(access={"door": "key", "owner_closet": "no", "alarm": "no_code"})
    assert derive.code_slots(a, LISTS, SETTINGS) == []
    assert build(a, held={"tax_id", "wifi_password"})["problems"] == []
    # An alarm without a code is still an alarm.
    assert "Security System" in {d["name"] for d in derive.derived_amenities(a, LISTS, None)}
    for door in ("unsure", "key"):
        a = answers(access={"door": door})
        assert derive.code_slots(a, LISTS, SETTINGS) == []
    a = answers(access={"door": "lockbox", "alarm": "code"})
    assert [(c["slot"], c["label"]) for c in derive.code_slots(a, LISTS, SETTINGS)] == \
        [("door", "Lockbox code"), ("alarm", "Alarm code")]


def test_a_closet_or_alarm_answered_yes_before_the_rewording_reads_as_with_a_code():
    raw = {"door": "smart_lock", "owner_closet": "yes", "alarm": "yes"}
    assert schema.clean_access(raw)["owner_closet"] == "code"
    assert schema.clean_access(raw)["alarm"] == "code"
    # Answers saved before then, never saved again, still ask for their codes.
    a = answers()
    a["access"] = {**raw, "extra_codes": []}
    assert [c["slot"] for c in derive.code_slots(a, LISTS, SETTINGS)] == \
        ["door", "owner_closet", "alarm"]
    assert schema.clean_access({"owner_closet": "maybe", "alarm": "loud"}) == \
        {"door": "", "owner_closet": "", "alarm": "", "extra_codes": []}


def test_values_track_already_has_are_done_on_a_retry():
    # Intake #1's state after its stop: the owner and the details done (the
    # Tax ID and the Wi-Fi password sent, then deleted from ENHQ), and from
    # before this change, no record of what was sent.
    legacy = {"ids": {"unit": 223}, "attempted": ["owner", "details"],
              "done": ["contact:0", "contact:1", "owner", "link:0", "link:1", "unit",
                       "details"]}
    p = build(held=HELD - {"tax_id", "wifi_password"}, sent=plan.sent_from(legacy))
    assert p["problems"] == [] and not any("Tax ID" in w for w in p["warnings"])
    assert states(p)["tax_id"] == "sent" and states(p)["wifi_password"] == "sent"
    # A code Track confirmed, though the worker stopped before marking it done.
    state = {**legacy, "attempted": legacy["attempted"] + ["code:door"], "sent": ["code:door"]}
    p = build(held=HELD - {"tax_id", "wifi_password", "code:door"}, sent=plan.sent_from(state))
    assert p["problems"] == [] and states(p)["code:door"] == "sent"
    assert "code:door" in {s["key"] for s in p["steps"]}   # found in Track on the retry
    # The Wi-Fi password sent, its step not marked done: not asked for again.
    state = {"done": [], "attempted": ["details"], "sent": ["wifi_password"]}
    p = build(held=HELD - {"wifi_password"}, sent=plan.sent_from(state))
    by = {s["key"]: s for s in p["steps"]}
    assert "pms_units_wifi_password" not in by["details"]["body"]["custom"]
    assert not any("Wi-Fi" in x for x in p["problems"])


def test_an_existing_owner_needs_no_tax_id():
    p = build(held=HELD - {"tax_id"}, owner_mode="existing", existing_owner_id=900)
    assert "tax_id" not in states(p) and p["problems"] == []


def test_the_writer_stops_before_any_write_when_a_value_is_missing():
    from apps.intake import track_writer

    p = build()
    calls, saved = [], []

    class Client:
        def get(self, *a):
            calls.append(("GET",) + a)
            return {}

        def send(self, *a):
            calls.append(a)
            return {"id": 1}

    held = {"tax_id": "12-3456789", "wifi_password": "pw", "code:door": "1",
            "code:owner_closet": "2", "code:extra-0": "4"}      # no alarm code
    ok, key, message = track_writer.execute(
        p, Client(), {}, secret=held.get, save=lambda *a: saved.append(a[1:]),
        confirm=lambda n: None, track_errors=())
    assert not ok and key == "code:alarm" and calls == []
    assert message == ("A sensitive value this step needs isn't in ENHQ (code:alarm). Enter it "
                       "on the review screen, or mark that there is none. Nothing was written "
                       "to Track this time.")
    assert saved == [("code:alarm", "failed", message)]
    # A step already done is not looked at: the writing starts.
    track_writer.execute(p, Client(), {"done": ["code:alarm"]}, secret=held.get,
                         save=lambda *a: None, confirm=lambda n: None, track_errors=())
    assert calls[0] == ("POST", "/crm/contacts", p["steps"][0]["body"])


def test_no_message_says_no_longer_for_a_value_never_saved():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for path in [*root.glob("apps/intake/*.py"), *root.glob("frontend/src/forms/*.tsx"),
                 root / "frontend/src/screens/IntakeReview.tsx"]:
        assert "no longer in ENHQ" not in path.read_text(), path
