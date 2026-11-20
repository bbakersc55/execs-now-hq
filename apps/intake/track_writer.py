"""Running a send plan (`plan.build`) against Track, one call at a time.

- Every id Track gives is saved the moment it arrives (`save`), so "Try the
  rest again" never repeats a finished step.
- A step that was started but never recorded (the worker stopped between
  Track's answer and the save) is looked for in Track before it is created
  again: a contact by email, the owner by name, the unit by name, a room by
  name, a code by type, the owner's link to the unit by unit.
- A placeholder ("{unit}") is filled from earlier ids; a secret
  ({"$secret": ...}) is read through `secret()` only as the call is made, and
  confirmed (`confirm()`) when Track's answer shows it holds it, so ENHQ can
  delete its copy.
- The first refusal stops the run, with Track's own words.
- Before any call, every sensitive value a step still to run needs is looked
  for (`secret()`); if one isn't there, the run stops before writing anything
  (owner, 2026-11-20: never start a send that can't finish).

Pure apart from the client it is given: no database, no Django settings. The
production proof (scripts) runs this same module.
"""

from __future__ import annotations

import copy
import re

_TOKEN = re.compile(r"^\{([a-z_]+(?::[\w-]+)?)\}$")
_IN_PATH = re.compile(r"\{([a-z_]+(?::[\w-]+)?)\}")


class StepFailed(Exception):
    def __init__(self, step, text):
        super().__init__(text)
        self.step = step
        self.text = text


def rows_of(data) -> list:
    data = data if isinstance(data, dict) else {}
    embedded = data.get("_embedded") or data.get("embedded") or {}
    return next((v for v in embedded.values() if isinstance(v, list)), [])


def _fill(value, ids, secret):
    """`value` with placeholders filled; secrets read through `secret`."""
    if isinstance(value, dict):
        if set(value) == {"$secret"}:
            found = secret(value["$secret"])
            if not found:
                raise LookupError(value["$secret"])
            return found
        return {k: _fill(v, ids, secret) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v, ids, secret) for v in value]
    if isinstance(value, str):
        match = _TOKEN.match(value)
        if match:
            if match.group(1) not in ids:
                raise KeyError(match.group(1))
            return ids[match.group(1)]
    return value


def _path(path, ids):
    def one(match):
        key = match.group(1)
        if key not in ids:
            raise KeyError(key)
        return str(ids[key])
    return _IN_PATH.sub(one, path)


def _same(a, b) -> bool:
    return str(a or "").strip().lower() == str(b or "").strip().lower()


def find_existing(step, client, ids, secret):
    """The Track id of what this step would create, if an earlier attempt
    already created it; None otherwise. Only ever reads."""
    spec = step.get("find") or {}
    kind = spec.get("kind")
    if kind == "contact" and (spec.get("email") or spec.get("last")):
        query = spec.get("email") or f"{spec.get('first', '')} {spec.get('last', '')}".strip()
        for row in rows_of(client.get("/crm/contacts", {"search": query, "size": 50})):
            if _same(row.get("firstName"), spec.get("first")) \
                    and _same(row.get("lastName"), spec.get("last")) \
                    and (not spec.get("email") or _same(row.get("primaryEmail"), spec["email"])):
                return row.get("id"), {}
    elif kind == "owner" and spec.get("name"):
        for row in rows_of(client.get("/pms/owners", {"search": spec["name"], "size": 50})):
            if _same(row.get("name"), spec["name"]) and \
                    (not spec.get("email") or _same(row.get("email"), spec["email"])):
                return row.get("id"), {"owner_company": row.get("companyId")}
    elif kind == "unit" and spec.get("name"):
        for active in (0, 1):
            data = client.get("/pms/units", {"search": spec["name"], "isActive": active,
                                             "size": 50})
            for row in rows_of(data):
                if _same(row.get("name"), spec["name"]) and \
                        (not spec.get("street") or _same(row.get("streetAddress"),
                                                         spec["street"])):
                    return row.get("id"), {}
    elif kind == "room" and "unit" in ids:
        for row in rows_of(client.get(f"/pms/units/{ids['unit']}/rooms", {"size": 100})):
            if _same(row.get("name"), spec.get("name")):
                return row.get("id"), {}
    elif kind == "code" and "unit" in ids:
        value = secret(spec.get("secret"))
        for row in rows_of(client.get(f"/pms/units/{ids['unit']}/security-codes",
                                      {"size": 100})):
            if str(row.get("codeTypeId")) == str(spec.get("type_id")) and \
                    (value is None or str(row.get("code")) == str(value)):
                return row.get("id"), {}
    elif kind == "ownership" and "owner" in ids and "unit" in ids:
        for row in rows_of(client.get(f"/pms/owners/{ids['owner']}/units", {"size": 100})):
            if str(row.get("unitId")) == str(ids["unit"]):
                return row.get("id"), {}
    elif kind == "link" and "owner_company" in ids:
        contact = _fill(spec.get("contact"), ids, secret)
        data = client.get(f"/crm/companies/{ids['owner_company']}/contacts/", {"size": 100})
        for row in rows_of(data):
            if str(row.get("contactId")) == str(contact):
                return "linked", {}
    return None, {}


def secrets_in(value) -> list[str]:
    """The sensitive values a body asks for, by name, in order."""
    if isinstance(value, dict):
        if set(value) == {"$secret"}:
            return [value["$secret"]]
        return [n for v in value.values() for n in secrets_in(v)]
    if isinstance(value, list):
        return [n for v in value for n in secrets_in(v)]
    return []


def missing_message(name: str) -> str:
    return (f"A sensitive value this step needs isn't in ENHQ ({name}). Enter it on the "
            "review screen, or mark that there is none.")


def _confirmed(step, answer) -> list[str]:
    """The secrets Track's answer shows it now holds."""
    out = []
    answer = answer if isinstance(answer, dict) else {}
    for name in step.get("confirms") or []:
        if name == "tax_id" and answer.get("taxIdMasked"):
            out.append(name)
        elif name.startswith("code:") and answer.get("id") and answer.get("code"):
            out.append(name)
        elif name == "wifi_password" and (answer.get("custom") or {}).get(
                "pms_units_wifi_password"):
            out.append(name)
    return out


def execute(plan, client, state, *, secret, save, confirm, track_errors):
    """Run what is left of `plan`. `state` is {"ids": {}, "done": [],
    "attempted": []}, saved by `save(state, key, status, detail)` after every
    change. `track_errors` is the tuple of the Track client's refusals.
    Returns (ok, failed_step_key, message)."""
    state.setdefault("ids", {})
    state.setdefault("done", [])
    state.setdefault("attempted", [])
    ids = state["ids"]
    sent = set(state.get("sent") or [])
    for step in plan["steps"]:
        if step["key"] in state["done"]:
            continue
        for name in secrets_in(step.get("body")):
            if name not in sent and not secret(name):
                message = missing_message(name) + " Nothing was written to Track this time."
                save(state, step["key"], "failed", message)
                return False, step["key"], message
    for step in plan["steps"]:
        key = step["key"]
        if key in state["done"]:
            save(state, key, "skipped", "Already in Track")
            continue
        save(state, key, "running", "")
        try:
            if key in state["attempted"] and step.get("find"):
                found, extra = find_existing(step, client, ids, secret)
                if found:
                    if found != "linked":
                        ids[key] = found
                    ids.update({k: v for k, v in extra.items() if v})
                    state["done"].append(key)
                    save(state, key, "done", "Found in Track from the last try")
                    continue
            state["attempted"].append(key)
            save(state, key, "running", "")
            if step["kind"] == "amenity_count":
                _amenity_count(step, client, ids)
                state["done"].append(key)
                save(state, key, "done", "")
                continue
            path = _path(step["path"], ids)
            body = _fill(copy.deepcopy(step.get("body")), ids, secret)
            answer = client.send(step["method"], path, body)
            if step["kind"] == "create":
                new_id = (answer or {}).get("id") if isinstance(answer, dict) else None
                if new_id is None:
                    raise StepFailed(step, "Track did not say what it created.")
                ids[key] = new_id
            for name, field in (step.get("keep") or {}).items():
                if isinstance(answer, dict) and answer.get(field) is not None:
                    ids[name] = answer[field]
            for name in _confirmed(step, answer):
                confirm(name)
            state["done"].append(key)
            save(state, key, "done", f"Track id {ids[key]}" if key in ids else "")
        except LookupError as exc:
            message = missing_message(exc.args[0])
            save(state, key, "failed", message)
            return False, key, message
        except KeyError as exc:
            message = f"This step needs an id from an earlier step that isn't there ({exc})."
            save(state, key, "failed", message)
            return False, key, message
        except StepFailed as exc:
            save(state, key, "failed", exc.text)
            return False, key, exc.text
        except track_errors as exc:
            save(state, key, "failed", str(exc))
            return False, key, str(exc)
    return True, None, ""


def _amenity_count(step, client, ids):
    """Set a per-unit amenity's count (the TVs). Its row is there when the
    amenitiesIds write made it, and is changed in place by its own id; when
    the unit has it only through its area, the unit's own row is added with
    the count (Track's per-unit amenities call, seen working 2026-11-19)."""
    for row in rows_of(client.get(f"/pms/units/{ids['unit']}/amenities", {"size": 100})):
        if str(row.get("amenityId")) == str(step["amenity_id"]):
            client.send("PATCH", f"/pms/units/{ids['unit']}/amenities/{row['id']}",
                        {"count": step["count"], "isEnabled": True})
            return
    client.send("POST", f"/pms/units/{ids['unit']}/amenities",
                {"amenityId": str(step["amenity_id"]), "count": step["count"],
                 "isEnabled": True})
