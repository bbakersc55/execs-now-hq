"""A read-only look at one company's intakes and what they made in Track
(docs/p14_intake_forms.md). Prepared 2026-11-23, to settle which test records
SkyRun's Track holds and whether each owner is tied to its unit.

Run in production's web container under `manage.py shell` (the Track key
lives only there), by scripts/intake_inspect.sh, with the company's id in
INTAKE_INSPECT_COMPANY. Nothing is unpacked or written in the container.

ENHQ's database: one READ ONLY transaction, rolled back at its end; then the
connection is closed and any further query stops the script.

Track: GET only, and only to skyrunparkcity.trackhs.com. The client is built
with a sender that stops the script, so no write can leave it.

What it prints: ids, kinds, states, times, dates and yes/no. Never a name, an
address, an email, a phone number, an answer or a sensitive value. Free text
(a step's detail, a run's error) is printed only when it matches one of the
app's own fixed sentences, reduced to its kind and ids; anything else is
"[withheld, n chars]". Values from Track are printed only for named fields,
and only when they are a number, a yes/no, or a date.
"""

import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from django.db import connection, transaction

from apps.crm.services.secrets import decrypt
from apps.intake import derive, plan
from apps.intake.models import OwnerDate, SendRun, Submission, SubmissionEvent, SubmissionSecret
from apps.intake.track_writer import find_existing, rows_of
from apps.scorecard import track
from apps.scorecard.models import TrackConnection

COMPANY = os.environ["INTAKE_INSPECT_COMPANY"]
TRACK_BASE = "https://skyrunparkcity.trackhs.com/api"


def p(*a):
    print(*a, flush=True)


# ------------------------------------------------------------ safe printing

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?"
                   r"(?:Z|[+-]\d{2}:?\d{2})?)?$")


def safe(value):
    """A number, a yes/no, a date, or a list of numbers; anything else withheld."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, str) and _DATE.match(value.strip()):
        return value.strip()
    if isinstance(value, list) and all(isinstance(v, int) and not isinstance(v, bool)
                                       for v in value):
        return value[:60]
    return "[withheld]"


def fields(row, names):
    row = row if isinstance(row, dict) else {}
    return " ".join(f"{n}={safe(row.get(n))}" for n in names if n in row)


def matching(row, words):
    """Fields whose name holds one of `words` (owner, unit, date), safe values only."""
    row = row if isinstance(row, dict) else {}
    out = []
    for key in sorted(row):
        if any(w in key.lower() for w in words):
            out.append(f"{key}={safe(row[key])}")
    return " ".join(out)


_FIXED = [
    (re.compile(r"^Track id (\d+)$"), lambda m: f"Track id {m.group(1)}"),
    # The link's step while it starts after the send day (services.LINK_NOTE).
    (re.compile(r"^(Track id \d+|Found in Track from the last try)\. Owner linked in Track\. "
                r"The link takes effect on ([A-Z][a-z]{2,8} \d{1,2}, \d{4})\."),
     lambda m: f"{m.group(1)}; the link takes effect on {m.group(2)}"),
    (re.compile(r"^(Already in Track|Found in Track from the last try|Already made|"
                r"Already held)$"), lambda m: m.group(1)),
    (re.compile(r"^(\d+) tasks$"), lambda m: f"{m.group(1)} tasks"),
    (re.compile(r"^(\d+) date range\(s\) held$"), lambda m: f"{m.group(1)} date range(s) held"),
    # Release 49 says "is no longer in ENHQ"; the fix round says "isn't in ENHQ".
    (re.compile(r"(?:isn't|is no longer) in ENHQ \((tax_id|wifi_password|code:[\w-]{1,24})\)"),
     lambda m: f"MISSING VALUE {m.group(1)}"),
    (re.compile(r"needs an id from an earlier step that isn't there \('([\w:-]{1,40})'\)"),
     lambda m: f"NEEDS ID OF {m.group(1)}"),
    (re.compile(r"^Track refused it: it answered (\d{3})\.$"),
     lambda m: f"TRACK REFUSED, status {m.group(1)}"),
    (re.compile(r"^Track refused it: (.*)$", re.S),
     lambda m: "TRACK REFUSED, fields: " + (", ".join(
         re.findall(r"(?:^|; )([A-Za-z_][\w.]{0,40}): ", m.group(1))) or "none named")),
    (re.compile(r"^Track's firewall refused"), lambda m: "TRACK FIREWALL REFUSED"),
    (re.compile(r"^Track answered (\d{3})\."), lambda m: f"TRACK ANSWERED {m.group(1)}"),
    (re.compile(r"^Track didn't answer"), lambda m: "TRACK DIDN'T ANSWER"),
    (re.compile(r"^Track did not say what it created"), lambda m: "TRACK GAVE NO ID"),
    (re.compile(r"^Track refused the key"), lambda m: "KEY REFUSED"),
    (re.compile(r"^Track's key doesn't allow"), lambda m: "KEY NOT ALLOWED"),
    (re.compile(r"^Track's request limit"), lambda m: "RATE LIMIT"),
    (re.compile(r"^Not ready to send: (.*)$", re.S),
     lambda m: "NOT READY, missing: " + (", ".join(
         re.findall(r"The ([a-z][a-z -]{0,40}) isn't in ENHQ", m.group(1))) or "other problems")
     + "; nothing written" * ("Nothing was written" in m.group(1))),
]


def said(text):
    """A detail or an error, reduced to its kind and ids, or withheld."""
    text = (text or "").strip()
    if not text:
        return ""
    for pattern, out in _FIXED:
        m = pattern.search(text)
        if m:
            return out(m)
    return f"[withheld, {len(text)} chars]"


# ------------------------------------------------------------ ENHQ: one read

def _when(dt, tz):
    if dt is None:
        return "-"
    return (dt.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%SZ")
            + dt.astimezone(tz).strftime(" (%H:%M:%S %Z)"))


_FROM = re.compile(r"from (\d{4}-\d{2}-\d{2})\)")

intakes = []
private = {}            # for Track searches only; never printed
with transaction.atomic():
    with connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION READ ONLY")
    found = list(TrackConnection.all_objects.select_related("company__tenant")
                 .filter(company_id=COMPANY))
    if len(found) != 1:
        raise SystemExit(f"STOPPED: expected one Track connection for the company, found "
                         f"{len(found)}")
    conn = found[0]
    if track.base_url(conn.domain) != TRACK_BASE:
        raise SystemExit("STOPPED: the company's Track isn't SkyRun Park City's")
    TZ = ZoneInfo(conn.company.tenant.timezone)
    TRACK_DOMAIN = conn.domain
    TRACK_KEY, TRACK_SECRET = decrypt(conn.key_ciphertext), decrypt(conn.secret_ciphertext)
    for sub in Submission.all_objects.filter(company_id=COMPANY, tenant_id=conn.tenant_id)\
            .order_by("number"):
        answers, staff = sub.answers or {}, sub.staff or {}
        state = sub.track or {}
        short = str(sub.pk)[:8]
        intakes.append({
            "number": sub.number, "short": short, "status": sub.status,
            "created": _when(sub.created_at, TZ), "submitted": _when(sub.submitted_at, TZ),
            "sent": _when(sub.sent_at, TZ), "locked": _when(sub.locked_at, TZ),
            "discarded": _when(sub.discarded_at, TZ),
            "carried_from": str(sub.carried_from_id)[:8] if sub.carried_from_id else "-",
            "mode": staff.get("owner_mode") or "new",
            "existing_owner_id": safe(staff.get("existing_owner_id")),
            "start_set_at_review": safe(staff.get("start_date")) if staff.get("start_date")
            else "no",
            "ready_date": safe(derive.ready_date(answers)) if derive.ready_date(answers)
            else "none",
            "contract_id": safe(staff.get("contract_id")),
            "ids": {k: safe(v) for k, v in (state.get("ids") or {}).items()},
            "done": list(state.get("done") or []),
            "attempted": list(state.get("attempted") or []),
            "confirmed": [n for n in state.get("sent") or [] if isinstance(n, str)],
            "held": sorted(f"{kind}:{slot}" if slot else kind
                           for kind, slot in SubmissionSecret.all_objects.filter(
                               submission=sub).values_list("kind", "slot")),
            "none_marked": [n for n in staff.get("no_value") or [] if isinstance(n, str)],
            "events": [(e.kind, _when(e.created_at, TZ),
                        (re.match(r"^Stopped at ([\w:-]{1,40}):", e.detail or "") or [None,
                                                                                     ""])[1])
                       for e in SubmissionEvent.all_objects.filter(submission=sub).order_by("created_at")],
            "runs": [{"id": str(r.pk)[:8], "state": r.state, "created": _when(r.created_at, TZ),
                      "finished": _when(r.finished_at, TZ), "error": said(r.error),
                      "steps": [(s.get("key", ""), s.get("state", ""), said(s.get("detail")),
                                 (_FROM.search(s.get("label") or "") or [None, ""])[1]
                                 if s.get("key") == "ownership" else "")
                                for s in r.steps or []]}
                     for r in SendRun.all_objects.filter(submission=sub).order_by("created_at")],
            "owner_dates": [(d.state, d.start.isoformat(), d.end.isoformat(), d.block_id or "-",
                             _when(d.placed_at, TZ))
                            for d in OwnerDate.all_objects.filter(submission=sub).order_by("start")],
            "project": "yes" if sub.project_id else "no",
        })
        prop = answers.get("property") or {}
        private[short] = {
            "people": plan.people(answers), "account": plan.account_name(answers),
            "owner_email": (answers.get("about") or {}).get("email", ""),
            "unit_name": (staff.get("unit_name") or derive.street_line(prop))[:120].strip(),
            "street": prop.get("street", ""),
        }
    transaction.set_rollback(True)
connection.close()


def _no_database(execute, sql, params, many, context):
    raise SystemExit("STOPPED: this read touches ENHQ's database only once")


connection.execute_wrapper(_no_database).__enter__()
p(f"ENHQ database: one read-only transaction, rolled back, then closed. "
  f"{len(intakes)} intake(s) for company {COMPANY[:8]}.")


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


def get(path, params=None):
    """Track's answer, or None with the reason printed."""
    try:
        return client.get(path, params)
    except track.TrackUnavailable as exc:
        p(f"    GET {track.path_template(path)}: {said(str(exc)) or 'refused'}")
        return None


def every(path, most_pages=10):
    out, page = [], 1
    while page <= most_pages:
        data = get(path, {"page": page, "size": 100})
        if data is None:
            return None
        out += rows_of(data)
        if page >= int((data or {}).get("page_count") or 1):
            break
        page += 1
    return out


def no_secret(_name):
    return None


ROW_DATES = ("startDate", "endDate", "createdAt", "updatedAt")

for it in intakes:
    p("")
    p(f"=== INTAKE #{it['number']} ({it['short']}): {it['status']}")
    p(f"  created {it['created']}; submitted {it['submitted']}; sent {it['sent']}; "
      f"locked {it['locked']}; discarded {it['discarded']}; carried from {it['carried_from']}")
    p(f"  owner mode {it['mode']}"
      + (f", existing owner {it['existing_owner_id']}" if it["mode"] == "existing" else "")
      + f"; contract {it['contract_id'] if it['contract_id'] is not None else 'form default'}"
      + "; start date set at review: "
      f"{it['start_set_at_review']}; owner's ready date: {it['ready_date']}")
    p(f"  Track ids recorded: {it['ids'] or 'none'}")
    p(f"  steps done: {', '.join(it['done']) or 'none'}")
    unrecorded = [k for k in it["attempted"] if k not in it["done"]]
    p(f"  attempted, not done: {', '.join(unrecorded) or 'none'}")
    p(f"  sensitive values: confirmed by Track {it['confirmed'] or 'none'}; held in ENHQ "
      f"{it['held'] or 'none'}; marked none {it['none_marked'] or 'none'}")
    p(f"  onboarding project: {it['project']}")
    for kind, when, key in it["events"]:
        p(f"  event {kind:15} {when}" + (f" at {key}" if key else ""))
    for n, run in enumerate(it["runs"], 1):
        p(f"  RUN {n} ({run['id']}): {run['state']}, created {run['created']}, finished "
          f"{run['finished']}" + (f"; error: {run['error']}" if run["error"] else ""))
        for key, st, detail, start in run["steps"]:
            p(f"    {st:8} {key}" + (f"  {detail}" if detail else "")
              + (f"  [start date sent: {start}]" if start else ""))
    for state, start, end, block, placed in it["owner_dates"]:
        p(f"  owner date {state}: {start} to {end}, block {block}, placed {placed}")

    ids = dict(it["ids"])
    private_it = private[it["short"]]
    if it["mode"] == "existing" and isinstance(it["existing_owner_id"], int):
        ids.setdefault("owner", it["existing_owner_id"])

    # Anything started but never recorded: looked for in Track, by reads only.
    for key in unrecorded:
        step = None
        if key.startswith("contact:"):
            i = int(key.split(":")[1])
            person = (private_it["people"] + [{}] * (i + 1))[i]
            step = {"find": {"kind": "contact", "email": person.get("email", ""),
                             "first": person.get("first", ""), "last": person.get("last", "")}}
        elif key == "owner":
            step = {"find": {"kind": "owner", "name": private_it["account"],
                             "email": private_it["owner_email"]}}
        elif key == "unit":
            step = {"find": {"kind": "unit", "name": private_it["unit_name"],
                             "street": private_it["street"]}}
        if step:
            try:
                got, extra = find_existing(step, client, ids, no_secret)
                p(f"  LOOKED FOR {key} in Track (unrecorded): "
                  + (f"found {safe(got)} {fields(extra, ('owner_company',))}" if got
                     else "not found"))
            except track.TrackUnavailable as exc:
                got, extra = None, {}
                p(f"  LOOKED FOR {key} in Track (unrecorded): not read, {said(str(exc))}")
            if got and got != "linked":
                ids.setdefault(key, got)
                for k, v in extra.items():
                    if v:
                        ids.setdefault(k, v)

    owner, unit, company = ids.get("owner"), ids.get("unit"), ids.get("owner_company")
    p("  TRACK NOW:")
    if isinstance(owner, int):
        row = get(f"/pms/owners/{owner}")
        if row is not None:
            p(f"    owner {owner}: present; "
              + fields(row, ("isActive", "companyId", "createdAt", "updatedAt"))
              + (f"; unit fields: {matching(row, ('unit',))}" if matching(row, ("unit",))
                 else ""))
        links = every(f"/pms/owners/{owner}/units")
        if links is not None:
            mine = [r for r in links if str(r.get("unitId")) == str(unit)]
            p(f"    owner {owner}'s unit links: {len(links)} in all, {len(mine)} to unit {unit}")
            for r in mine:
                p(f"      link {safe(r.get('id'))}: "
                  + fields(r, ("unitId", "ownerId", "contractId") + ROW_DATES
                           + ("isActive",))
                  + f"; fields Track gives: {', '.join(sorted(r))}")
            if it["mode"] != "existing":
                for r in links:
                    if r not in mine:
                        p(f"      other link {safe(r.get('id'))}: unit {safe(r.get('unitId'))} "
                          + fields(r, ROW_DATES))
    else:
        p("    no owner id")
    if isinstance(unit, int):
        row = get(f"/pms/units/{unit}")
        if row is not None:
            p(f"    unit {unit}: present; "
              + fields(row, ("isActive", "isBookable", "createdAt", "updatedAt"))
              + (f"; owner fields: {matching(row, ('owner',))}" if matching(row, ("owner",))
                 else ""))
        rooms = every(f"/pms/units/{unit}/rooms")
        if rooms is not None:
            p(f"    rooms: {[safe(r.get('id')) for r in rooms] or 'none'}")
        codes = every(f"/pms/units/{unit}/security-codes")
        if codes is not None:
            p("    codes: " + ("; ".join(
                f"{safe(c.get('id'))} " + fields(c, ("codeTypeId", "startDate", "endDate",
                                                     "createdAt")) for c in codes) or "none"))
    else:
        p("    no unit id")
    for key in sorted(k for k in ids if k.startswith("contact:")):
        if isinstance(ids[key], int):
            row = get(f"/crm/contacts/{ids[key]}")
            p(f"    {key} {ids[key]}: " + ("present; " + fields(row, ("createdAt",))
                                           if row is not None else "not read"))
    if isinstance(company, int):
        linked = every(f"/crm/companies/{company}/contacts/")
        if linked is not None:
            p(f"    owner company {company}: contacts linked "
              f"{[safe(r.get('contactId')) for r in linked] or 'none'}")

p("")
p(f"CALLS: {client.calls} GET to Track, 0 writes. DONE.")
