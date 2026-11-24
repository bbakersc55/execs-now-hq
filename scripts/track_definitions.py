"""A read-only look at the definitions SkyRun added in Track: bed types and
unit custom fields (owner-agreements, Part 1, change 1). Prepared 2026-11-23.

Run in production's web container under `manage.py shell` (the Track key
lives only there), by scripts/track_definitions.sh, with the company's id in
TRACK_DEFS_COMPANY. Nothing is unpacked or written in the container.

ENHQ's database: one READ ONLY transaction, rolled back at its end; then the
connection is closed and any further query stops the script. It reads the
company's Track connection, the stored copy of Track's lists, and the form's
sleeps table and custom-field settings for the definitions named below.

Track: GET only, and only to skyrunparkcity.trackhs.com. The client is built
with a sender that stops the script, so no write can leave it.

What it prints: definitions only (a bed type's id, name and whether it is
active; a unit custom field's id, name, reference, type and choices; Track's
owner contracts), with ids, yes/no and dates. Of one test unit and one test
owner (ZZ TEST 2, unit 222 and owner 266, made by the proof) it prints the
field NAMES only, never a value, to show where square footage and an
emergency contact could go. For the five people named for the agreements it
prints, by the first name given here, how many active ENHQ users of SkyRun's
company or practice have it and their roles: never a surname or an email.
It prints no owner's name, address, email, phone or any sensitive value.
"""

import os
import re

from django.db import connection, transaction

from apps.crm.services.secrets import decrypt
from apps.intake import access, defaults
from apps.intake.models import IntakeForm, TrackListSnapshot
from apps.intake.trackread import every
from apps.scorecard import track
from apps.scorecard.models import TrackConnection
from apps.tenancy.models import Membership

COMPANY = os.environ["TRACK_DEFS_COMPANY"]
TRACK_BASE = "https://skyrunparkcity.trackhs.com/api"
NEW_BEDS = re.compile(r"king\s*sofa\s*sleeper|roll\s*-?\s*away", re.I)
NEW_FIELDS = re.compile(r"water\s*soft|landscap|other\s*maintenance|emergency|square|footage|"
                        r"sq\.?\s*f|\barea\b|size", re.I)
TEST_UNIT, TEST_OWNER = 222, 266          # ZZ TEST 2, made by the proof (p14)
PEOPLE = ("Sandra", "Jackie", "Kendra", "Michael", "Bryan")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ][\d:.]+(?:Z|[+-]\d{2}:?\d{2})?)?$")


def p(*a):
    print(*a, flush=True)


def when(value):
    return value.strip() if isinstance(value, str) and _DATE.match(value.strip()) else "-"


# ------------------------------------------------------------ ENHQ: one read

with transaction.atomic():
    with connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION READ ONLY")
    found = list(TrackConnection.all_objects.filter(company_id=COMPANY))
    if len(found) != 1:
        raise SystemExit(f"STOPPED: expected one Track connection for the company, found "
                         f"{len(found)}")
    conn = found[0]
    if track.base_url(conn.domain) != TRACK_BASE:
        raise SystemExit("STOPPED: the company's Track isn't SkyRun Park City's")
    TRACK_DOMAIN = conn.domain
    TRACK_KEY, TRACK_SECRET = decrypt(conn.key_ciphertext), decrypt(conn.secret_ciphertext)
    snap = {s.kind: (s.fetched_at, s.payload or [])
            for s in TrackListSnapshot.all_objects.filter(
                company_id=COMPANY, tenant_id=conn.tenant_id,
                kind__in=("bed_types", "custom_fields"))}
    forms = [(str(f.pk)[:8], f.settings or {})
             for f in IntakeForm.all_objects.filter(company_id=COMPANY, tenant_id=conn.tenant_id)]
    managers = set(access.manager_memberships(conn.company).values_list("pk", flat=True))
    people = {}
    for first in PEOPLE:
        ms = Membership.all_objects.filter(tenant_id=conn.tenant_id, revoked_at__isnull=True,
                                           user__is_active=True,
                                           user__full_name__iregex=rf"^{first}(\s|$)")
        ms = ms.filter(client_company_id=COMPANY) | ms.filter(client_company__isnull=True)
        people[first] = sorted(f"{m.role}{' (intake manager)' if m.pk in managers else ''}"
                               for m in ms)
    transaction.set_rollback(True)
connection.close()


def _no_database(execute, sql, params, many, context):
    raise SystemExit("STOPPED: this read touches ENHQ's database only once")


connection.execute_wrapper(_no_database).__enter__()
p("ENHQ database: one read-only transaction, rolled back, then closed.")


# ------------------------------------------------------------ Track: GET only

def guarded_get(url, headers):
    if not url.startswith(TRACK_BASE + "/"):
        raise SystemExit("GUARD REFUSED: not SkyRun Park City's Track")
    return track.http_transport(url, headers)


def no_writes(method, url, headers, body):
    raise SystemExit(f"GUARD REFUSED {method}: this read never writes to Track")


client = track.TrackClient(TRACK_DOMAIN, TRACK_KEY, TRACK_SECRET, transport=guarded_get,
                           sender=no_writes)
del TRACK_KEY, TRACK_SECRET
calls = {"n": 0}
_get = client.get


def counted_get(path, params=None):
    calls["n"] += 1
    return _get(path, params)


client.get = counted_get

# ------------------------------------------------------------ bed types

p("\n== Bed types in Track (GET /pms/units/bed-types) ==")
beds = every(client, "/pms/units/bed-types")
stored_beds = {str(b.get("id")) for b in snap.get("bed_types", (None, []))[1]}
for b in sorted(beds, key=lambda r: int(r["id"])):
    mark = "  <== new" if NEW_BEDS.search(str(b.get("name", ""))) else ""
    p(f"  id={b['id']} active={b.get('isActive', True) is not False} "
      f"name={str(b.get('name', ''))[:60]!r} created={when(b.get('createdAt'))} "
      f"in ENHQ's copy={str(b['id']) in stored_beds}{mark}")
p(f"  {len(beds)} bed types; ENHQ's copy has {len(stored_beds)}, fetched "
  f"{snap['bed_types'][0].isoformat() if 'bed_types' in snap else 'never'}")
for b in beds:
    if NEW_BEDS.search(str(b.get("name", ""))):
        rule = defaults.sleeps_for_name(str(b.get("name", "")))
        p(f"  rule today for {str(b.get('name'))!r}: sleeps {rule[0]}, "
          f"{'known' if rule[1] else 'unknown (flagged)'}; "
          f"other places people sleep: {defaults.other_place_bed(str(b.get('name', '')))}")
        for short, settings in forms:
            row = (settings.get("sleeps") or {}).get(str(b["id"]))
            p(f"    form {short} sleeps table: "
              + (f"sleeps={row.get('sleeps')} confirmed={row.get('confirmed')} "
                 f"other_places={row.get('other_places')}" if row else "not there yet"))

# ------------------------------------------------------------ unit custom fields

p("\n== Unit custom fields in Track (GET /custom-fields?entity=pms_units) ==")
raw = every(client, "/custom-fields", {"entity": "pms_units"})
stored_refs = {str(f.get("reference")) for f in snap.get("custom_fields", (None, []))[1]}
for f in sorted(raw, key=lambda r: int(r["id"])):
    new = NEW_FIELDS.search(f"{f.get('name', '')} {f.get('reference', '')}")
    p(f"  id={f['id']} ref={str(f.get('reference', ''))[:70]} type={f.get('type')} "
      f"subType={f.get('subType') or '-'} active={f.get('isActive', True) is not False} "
      f"required={f.get('isRequired', '-')} created={when(f.get('createdAt'))} "
      f"in ENHQ's copy={str(f.get('reference')) in stored_refs}"
      + ("  <== asked about" if new else ""))
p(f"  {len(raw)} unit custom fields; ENHQ's copy has {len(stored_refs)}, fetched "
  f"{snap['custom_fields'][0].isoformat() if 'custom_fields' in snap else 'never'}")

p("\n== The fields asked about, in full ==")
for f in raw:
    if not NEW_FIELDS.search(f"{f.get('name', '')} {f.get('reference', '')}"):
        continue
    p(f"  id={f['id']} name={str(f.get('name', ''))[:80]!r} ref={f.get('reference')}")
    p(f"    type={f.get('type')} subType={f.get('subType') or '-'} "
      f"keys={sorted(k for k in f if not k.startswith('_'))}")
    values = ((f.get("_embedded") or {}).get("values") or [])
    if f.get("type") in ("select", "multiselect"):
        values = every(client, f"/custom-fields/{f['id']}/values") or values
    for v in values:
        p(f"    choice id={v.get('id')} handle={str(v.get('handle', ''))[:60]!r} "
          f"name={str(v.get('name', ''))[:60]!r} active={v.get('isActive', True) is not False}")
    for short, settings in forms:
        row = (settings.get("custom_fields") or {}).get(str(f.get("reference")))
        p(f"    form {short} setting: " + (f"state={row.get('state')}" if row else "not there yet"))

# ------------------------------------------------------------ contracts

p("\n== Owner contracts in Track (GET /pms/owners/contracts) ==")
for c in sorted(every(client, "/pms/owners/contracts"), key=lambda r: int(r["id"])):
    p(f"  id={c['id']} code={str(c.get('code', ''))[:30]!r} name={str(c.get('name', ''))[:60]!r} "
      f"type={c.get('type')} active={c.get('isActive', True) is not False}")

# ------------------------------------------------------------ field names only

p(f"\n== Field names (no values) on test unit {TEST_UNIT} and test owner {TEST_OWNER} ==")
for label, path in (("unit", f"/pms/units/{TEST_UNIT}"), ("owner", f"/pms/owners/{TEST_OWNER}")):
    try:
        row = client.get(path)
    except track.TrackUnavailable:
        p(f"  {label}: Track didn't answer")
        continue
    row = row if isinstance(row, dict) else {}
    p(f"  {label}: {', '.join(sorted(k for k in row if not k.startswith('_')))}")
    custom = row.get("custom")
    if isinstance(custom, dict):
        p(f"  {label} custom: {', '.join(sorted(custom))}")

# ------------------------------------------------------------ the people named

p("\n== ENHQ users by the first names given (active, SkyRun's company or the practice) ==")
for first, roles in people.items():
    p(f"  {first}: {len(roles)} user(s){': ' + ', '.join(roles) if roles else ''}")

p(f"\nTrack: {calls['n']} GET(s), 0 writes.")
