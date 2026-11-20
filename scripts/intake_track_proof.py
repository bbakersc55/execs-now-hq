"""The production proof of intake forms (docs/p14_intake_forms.md): one
complete submission sent to SkyRun Park City's real Track through the
feature's own code (schema, defaults, derive, plan, track_writer, trackread
and the Track client), creating a second test set named "ZZ TEST 2 ... DELETE
ME": the owner inactive, the unit inactive and not bookable.

Run in production's web container with `manage.py shell` (the key lives only
there), by scripts/intake_track_proof.sh, which unpacks the modules into a
private folder ($INTAKE_PROOF_DIR) and removes it afterwards. The modules are
imported from the END of the import path, and checked to be this run's own.

ENHQ's database: one read (SkyRun's Track connection, with its company) in a
READ ONLY transaction; then the connection is closed and any further query
stops the proof. It writes nothing to ENHQ.

Track: only skyrunparkcity.trackhs.com. A guard refuses every write but these:
creating a contact, owner or unit whose name starts "ZZ TEST 2", and writing
to what this proof itself created. Progress (Track ids and step names, never a
value) is kept in /tmp/zztest2_state.json so running it again carries on
without duplicates ("Try the rest again"), and once everything is done a run
stops before Track. The file stays in the container until the next deploy.
"""

import json
import os
import re
import sys
from datetime import date

from django.db import connection, transaction

from apps.crm.services.secrets import decrypt
from apps.scorecard.models import TrackConnection

PROOF_DIR = os.path.realpath(os.environ["INTAKE_PROOF_DIR"])
sys.path.append(os.path.join(PROOF_DIR, "lib"))  # last: it can shadow nothing

from intake_proof import (  # noqa: E402
    defaults, derive, plan, schema, track, track_writer, trackread,
)

for _module in (defaults, derive, plan, schema, track, track_writer, trackread):
    if not os.path.realpath(_module.__file__).startswith(PROOF_DIR + os.sep):
        raise SystemExit(f"STOPPED: {_module.__name__} isn't this run's own copy")

STATE = "/tmp/zztest2_state.json"
PREFIX = "ZZ TEST 2"
TRACK_BASE = "https://skyrunparkcity.trackhs.com/api"


def p(*a):
    print(*a, flush=True)


# ENHQ's database: this one read, in a read-only transaction, and nothing else.
with transaction.atomic():
    with connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION READ ONLY")
    found = list(TrackConnection.all_objects.select_related("company").filter(
        company__name__icontains="skyrun"))
    if len(found) != 1:
        raise SystemExit(f"STOPPED: expected one SkyRun Track connection, found {len(found)}")
    conn = found[0]
    TRACK_DOMAIN = conn.domain
    TRACK_KEY, TRACK_SECRET = decrypt(conn.key_ciphertext), decrypt(conn.secret_ciphertext)
connection.close()


def _no_database(execute, sql, params, many, context):
    raise SystemExit("STOPPED: the proof touches ENHQ's database only to read the Track key")


connection.execute_wrapper(_no_database).__enter__()
p("ENHQ database: read SkyRun's Track connection (read-only), then closed")

created = {"contact": set(), "owner": set(), "company": set(), "unit": set()}
if os.path.exists(STATE):
    saved = json.load(open(STATE))
    ids = saved.get("ids", {})
    for key, value in ids.items():
        kind = key.split(":")[0]
        if kind in created and value:
            created[kind].add(int(value))
    if ids.get("owner_company"):
        created["company"].add(int(ids["owner_company"]))
else:
    saved = {}
if saved.get("complete"):
    p("STOPPED: this proof already finished; nothing sent. Track ids: "
      + json.dumps(saved.get("ids", {})))
    raise SystemExit(0)


def guard(method, path, body):
    """Refuse anything but this proof's own records."""
    path = path.split("?")[0].rstrip("/")
    b = body if isinstance(body, dict) else {}
    named = lambda key: str(b.get(key, "")).startswith(PREFIX)  # noqa: E731
    mine = lambda kind, value: value is not None and int(value) in created[kind]  # noqa: E731
    if method == "POST" and path == "/crm/contacts":
        return named("firstName")
    if method == "POST" and path == "/pms/owners":
        return named("name")
    if method == "POST" and path == "/pms/units":
        return named("name")
    if (m := re.fullmatch(r"/crm/companies/(\d+)/contacts", path)) and method == "POST":
        return mine("company", m.group(1)) and mine("contact", b.get("contactId"))
    if (m := re.fullmatch(r"/pms/units/(\d+)(/rooms|/amenities(/\d+)?|/security-codes)?", path)):
        return mine("unit", m.group(1)) and method in ("POST", "PUT", "PATCH")
    if (m := re.fullmatch(r"/pms/owners/(\d+)/units", path)) and method == "POST":
        return mine("owner", m.group(1)) and mine("unit", b.get("unitId"))
    return False


def guarded_send(method, url, headers, body):
    if not url.startswith(TRACK_BASE + "/"):
        raise SystemExit(f"GUARD REFUSED {method}: not SkyRun Park City's Track")
    path = re.sub(r"^https?://[^/]+/api", "", url)
    if not guard(method, path, body):
        raise SystemExit(f"GUARD REFUSED {method} {track.path_template(path)}")
    status, response_headers, text = track.http_send(method, url, headers, body)
    if status in (200, 201) and method == "POST":
        try:
            data = json.loads(text)
        except ValueError:
            data = {}
        if path == "/crm/contacts":
            created["contact"].add(int(data["id"]))
        elif path == "/pms/owners":
            created["owner"].add(int(data["id"]))
            created["company"].add(int(data["companyId"]))
        elif path == "/pms/units":
            created["unit"].add(int(data["id"]))
    p(f"  {method} {track.path_template(path)} -> {status}")
    return status, response_headers, text


client = track.TrackClient(TRACK_DOMAIN, TRACK_KEY, TRACK_SECRET, sender=guarded_send)
if client.base != TRACK_BASE:
    raise SystemExit(f"STOPPED: SkyRun's Track connection points at {client.base}")
p(f"Track: {client.base}")
lists = trackread.fetch(client)
p("Lists read: " + ", ".join(f"{k} {len(v)}" for k, v in lists.items()))
settings = defaults.build(lists)


def named(kind, name):
    return next(r["id"] for r in lists[kind] if r["name"] == name)


bed = lambda name: named("bed_types", name)  # noqa: E731
fixture = lambda name: named("bathroom_amenities", name)  # noqa: E731
answers = {
    "about": {"first_name": f"{PREFIX}", "last_name": "Contact One - DELETE ME",
              "account_name": f"{PREFIX} OWNER - DELETE ME", "street": "101 Example Way",
              "street2": "", "city": "Testville", "state": "UT", "postal": "84060",
              "country": "US", "mobile": "+18015550111",
              "email": "bryan.baker+zztest2-contact-one@getexecutivesnow.com",
              "contact_pref": "email", "heard": "other", "heard_detail": "ENHQ intake proof",
              "has_extra_owners": "yes",
              "extra_owners": [{"first_name": f"{PREFIX}", "last_name": "Contact Two - DELETE ME",
                                "email": "bryan.baker+zztest2-contact-two@getexecutivesnow.com",
                                "mobile": "", "portal": True}]},
    "tax": {"kind": "tax_id"},
    "property": {"street": "500 Example Way", "street2": "", "city": "Testville", "state": "UT",
                 "postal": "84060", "lodging_type_id": named("lodging_types", "Condo"),
                 "ready": "unsure", "ready_date": "", "has_bookings": "no", "bookings": []},
    "bedrooms": [{"beds": [{"type": bed("King"), "count": 1}], "own_bath": True},
                 {"beds": [{"type": bed("Twin"), "count": 2}], "own_bath": False}],
    "other_sleeping": {"has": "yes", "places": [{"where": "living", "label": "",
                                                 "beds": [{"type": bed("Queen Sofa Bed"),
                                                           "count": 1}]}]},
    "bathrooms": [{"fixtures": {str(fixture("Bathtub")): 1, str(fixture("Shower")): 1,
                                str(fixture("Toilet")): 1, str(fixture("Sink")): 2}},
                  {"fixtures": {str(fixture("Toilet")): 1, str(fixture("Sink")): 1}}],
    "amenities": {"common": ["dishwasher", "washer_dryer", "gas_fireplace"], "more": [],
                  "gondola": "no"},
    "home": {"heating": ["forced_air"], "cooling": ["fans"], "wifi": "yes",
             "wifi_provider": "Test Net", "wifi_network": "ZZ-TEST-2", "wifi_router": "Hall closet",
             "tv": ["smart_tv"], "tv_count": 2, "trash_by": "hoa", "hoa": "no",
             "heat_tape": "no", "snow_by": "hoa", "landscaping_by": "hoa", "softener": "no",
             "permit": "no", "parking": ["garage"], "parking_pass": "no"},
    "access": {"door": "keypad", "owner_closet": "no", "alarm": "yes", "extra_codes": []},
    "stays": {"has": "yes", "ranges": [{"start": "2027-12-20", "end": "2027-12-27"}]},
    "custom": {},
}
# Made up for each run and kept only in memory: never printed, logged or saved.
# A tax id starting 00 is never issued, so this one can't be anyone's.
_rand = __import__("secrets").SystemRandom()
SECRETS = {"tax_id": "00-" + "".join(str(_rand.randrange(10)) for _ in range(7)),
           "wifi_password": "zz-test-2-" + __import__("secrets").token_hex(4),
           "code:door": str(_rand.randrange(1000, 10000)),
           "code:alarm": str(_rand.randrange(1000, 10000))}
answers = schema.clean(answers, custom_allowed=set())
staff = derive.staff_with_defaults({
    "node_id": named("nodes", "ZProperty Management"),
    "unit_name": f"{PREFIX} - ENHQ INTAKE PROOF - DELETE ME", "short_name": f"{PREFIX} PROOF",
    "shares": {"1": 50}, "start_date": date.today().isoformat(),
    "contract_effective_date": date.today().isoformat()}, answers, settings, lists)
the_plan = plan.build(answers=answers, staff=staff, settings=settings, lists=lists,
                      brand="SkyRun Park City", has_tax_id=True, owner_active=False,
                      unit_bookable=False)
p("\nWHAT WILL BE SENT")
for line in the_plan["summary"]:
    p(f"  - {line}")
for line in the_plan["problems"]:
    p(f"  PROBLEM: {line}")
if the_plan["problems"]:
    raise SystemExit("Not sent: the plan has problems.")
p("\nSTEPS")
state = saved or {"ids": {}, "done": [], "attempted": []}
confirmed = []


def save(current, key, status, detail):
    json.dump(current, open(STATE, "w"))
    if status in ("done", "skipped", "failed"):
        p(f"  [{status}] {key}" + (f": {detail}" if detail else ""))


ok, failed, message = track_writer.execute(
    the_plan, client, state, secret=lambda name: SECRETS.get(name), save=save,
    confirm=confirmed.append, track_errors=(track.TrackUnavailable,))
p(f"\nRESULT: {'all done' if ok else f'stopped at {failed}: {message}'}")
if ok:
    state["complete"] = True
    json.dump(state, open(STATE, "w"))
    p(f"STATE: complete; {STATE} keeps Track ids and step names only, so running "
      "the line again stops before Track")
else:
    p(f"STATE: kept in {STATE} (Track ids and step names only); run the same line "
      "again to carry on")
p(f"Secrets Track confirmed it holds: {sorted(confirmed)}")
ids = state["ids"]
p("IDS: " + json.dumps({k: v for k, v in ids.items()}))
if ids.get("unit"):
    unit = client.get(f"/pms/units/{ids['unit']}")
    p("UNIT: " + json.dumps({k: unit.get(k) for k in (
        "id", "name", "isActive", "isBookable", "useRoomConfiguration", "bedrooms",
        "fullBathrooms", "threeQuarterBathrooms", "halfBathrooms", "maxOccupancy", "nodeId",
        "typeId", "lodgingTypeId")}))
    rooms = trackread.rows(client.get(f"/pms/units/{ids['unit']}/rooms", {"size": 50}))
    p("ROOMS: " + json.dumps([(r["id"], r["name"], r["roomType"], r.get("sleeps"))
                              for r in rooms]))
    codes = trackread.rows(client.get(f"/pms/units/{ids['unit']}/security-codes", {"size": 50}))
    p(f"CODES: {len(codes)} (values not printed)")
if ids.get("owner"):
    owner = client.get(f"/pms/owners/{ids['owner']}")
    shown = {k: owner.get(k) for k in ("id", "name", "isActive", "companyId", "email")}
    shown["taxIdSet"] = bool(owner.get("taxIdMasked") or owner.get("taxId"))
    p("OWNER: " + json.dumps(shown))
p(f"CALLS: {client.calls}")
