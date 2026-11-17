"""A tool's definition, checked and worked out (P12).

A definition is JSON:

    {"sections": [{"title": "...", "fields": [FIELD, ...]}],
     "results": [{"key", "label", "formula", "format", "note", "says"}],
     "views": [{"type": "org_chart", ...} | {"type": "cadence", ...}],
     "actions": ["calendar", "import_sop"],
     "how_to": ["three or four plain steps"],
     "sample": {a full set of input values, as a run keeps them}}

A FIELD is {"key", "label", "type", ...}. Types: text, long_text, number,
money, percent, date, choice (with "options"), person, people, table (with
"columns", each a field of the types above or computed), and computed (with
"formula" and "format"). A table's computed column is worked out for each row
from that row's columns, the worksheet's fields and other tables' columns.

A run's values are {field key: value, table key: [{column key: value,
"_flag": bool}, ...]}. `evaluate` returns every computed value with its text
and any error, said in words.

The three optional parts (2026-11-14, E3): `how_to` is the "How to use this"
panel's steps; `sample` is what "Load sample values" puts in; a result's
`says` is a sentence with {result_key} placeholders, filled with the results'
texts. A sentence one of whose results has no value is left out, never shown
half-filled.
"""

from __future__ import annotations

import re
from decimal import Decimal

from . import formula as F

INPUT_TYPES = ("text", "long_text", "number", "money", "percent", "date", "choice", "person",
               "people")
TYPES = INPUT_TYPES + ("table", "computed")
FORMATS = ("number", "money", "percent", "text", "list", "hours", "people")
NUMERIC = ("number", "money", "percent")
KEY = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
MOST_SECTIONS, MOST_FIELDS, MOST_COLUMNS, MOST_RESULTS, MOST_ROWS = 12, 40, 16, 12, 200
VIEW_TYPES = ("org_chart", "cadence")
ACTIONS = ("calendar", "import_sop")
HOW_TO_STEPS = (3, 4)
MOST_STEP, MOST_SAYS = 300, 300
_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")


class DefinitionInvalid(ValueError):
    def __init__(self, errors: list[dict]):
        super().__init__(errors[0]["message"] if errors else "The tool isn't valid.")
        self.errors = errors


def _fields(definition):
    for section in definition.get("sections") or []:
        yield from section.get("fields") or []


def scalars(definition) -> dict:
    return {f["key"]: f for f in _fields(definition) if f.get("type") != "table"}


def tables(definition) -> dict:
    return {f["key"]: f for f in _fields(definition) if f.get("type") == "table"}


def check(definition) -> list[dict]:
    """Every problem with a definition, each with where it is: [] when sound."""
    errors = []

    def err(where, message):
        errors.append({"where": where, "message": message})

    if not isinstance(definition, dict):
        return [{"where": "", "message": "A tool is sections of fields."}]
    sections = definition.get("sections")
    if not isinstance(sections, list) or not 1 <= len(sections) <= MOST_SECTIONS:
        err("sections", f"A tool has one to {MOST_SECTIONS} sections.")
        return errors
    keys = {}
    count = 0
    for s, section in enumerate(sections):
        if not isinstance(section, dict) or not str(section.get("title") or "").strip():
            err(f"sections.{s}", "Each section needs a title.")
            continue
        for f, field in enumerate(section.get("fields") or []):
            count += 1
            where = f"sections.{s}.fields.{f}"
            if not isinstance(field, dict):
                err(where, "A field is a key, a label and a type.")
                continue
            key, kind = str(field.get("key") or ""), field.get("type")
            if not KEY.match(key):
                err(where, f"“{key}” isn't a usable key: lower-case letters, digits and _, "
                           "starting with a letter.")
            elif key in keys:
                err(where, f"Two fields are called “{key}”.")
            keys[key] = field
            if not str(field.get("label") or "").strip():
                err(where, "Each field needs a label.")
            if kind not in TYPES:
                err(where, f"“{kind}” isn't a field type.")
            if kind == "choice" and not (isinstance(field.get("options"), list)
                                         and field["options"]):
                err(where, f"{field.get('label') or key} needs its choices.")
            if kind == "computed" and field.get("format", "number") not in FORMATS:
                err(where, "Choose how the result is shown.")
            if kind == "table":
                columns = field.get("columns")
                if not isinstance(columns, list) or not 1 <= len(columns) <= MOST_COLUMNS:
                    err(where, f"A table has one to {MOST_COLUMNS} columns.")
                    continue
                seen = set()
                for c, column in enumerate(columns):
                    cwhere = f"{where}.columns.{c}"
                    ckey = str(column.get("key") or "")
                    if not KEY.match(ckey):
                        err(cwhere, f"“{ckey}” isn't a usable column key.")
                    elif ckey in seen:
                        err(cwhere, f"Two columns are called “{ckey}”.")
                    seen.add(ckey)
                    if column.get("type") not in INPUT_TYPES + ("computed",):
                        err(cwhere, f"“{column.get('type')}” isn't a column type.")
                    if column.get("type") == "choice" and not column.get("options"):
                        err(cwhere, f"{column.get('label') or ckey} needs its choices.")
    if count > MOST_FIELDS:
        err("sections", f"A tool has at most {MOST_FIELDS} fields.")
    results = definition.get("results") or []
    if not isinstance(results, list) or len(results) > MOST_RESULTS:
        err("results", f"A tool has at most {MOST_RESULTS} result cards.")
        results = []
    for r, result in enumerate(results):
        if not isinstance(result, dict) or not str(result.get("label") or "").strip():
            err(f"results.{r}", "Each result card needs a label.")
        elif result.get("format", "number") not in FORMATS:
            err(f"results.{r}", "Choose how the result is shown.")
    for v, view in enumerate(definition.get("views") or []):
        if not isinstance(view, dict) or view.get("type") not in VIEW_TYPES:
            err(f"views.{v}", "That view isn't one the app draws.")
    for a in definition.get("actions") or []:
        if a not in ACTIONS:
            err("actions", f"“{a}” isn't an action the app has.")
    errors += _check_how_to(definition.get("how_to"))
    result_keys = {str(r.get("key") or "") for r in results if isinstance(r, dict)} - {""}
    for r, result in enumerate(results):
        if isinstance(result, dict) and result.get("says") not in (None, ""):
            errors += _check_says(result["says"], f"results.{r}", result_keys,
                                  str(result.get("label") or ""))
        for name in SIGNED_SAYS:
            if isinstance(result, dict) and result.get(name) not in (None, ""):
                errors += _check_says(result[name], f"results.{r}.{name}", result_keys,
                                      str(result.get("label") or ""))
    if errors:
        return errors
    errors += _check_sample(definition, definition.get("sample"))
    if errors:
        return errors
    # Every formula reads, and names only what the worksheet has.
    table_defs = tables(definition)
    known = set(scalars(definition))
    dotted = {f"{t}.{c['key']}" for t, d in table_defs.items() for c in d["columns"]}
    for s, section in enumerate(sections):
        for f, field in enumerate(section.get("fields") or []):
            where = f"sections.{s}.fields.{f}"
            if field.get("type") == "computed":
                errors += _check_formula(field.get("formula"), where, known | dotted,
                                         f"{field.get('label')}")
            if field.get("type") == "table":
                own = {c["key"] for c in field["columns"]}
                for c, column in enumerate(field["columns"]):
                    if column.get("type") == "computed":
                        errors += _check_formula(column.get("formula"),
                                                 f"{where}.columns.{c}", known | dotted | own,
                                                 f"{column.get('label')}")
    for r, result in enumerate(results):
        errors += _check_formula(result.get("formula"), f"results.{r}", known | dotted,
                                 f"{result.get('label')}")
    return errors


def _check_how_to(steps) -> list[dict]:
    if steps in (None, [], ""):
        return []
    low, high = HOW_TO_STEPS
    if not isinstance(steps, list) or not low <= len(steps) <= high \
            or not all(isinstance(x, str) and x.strip() for x in steps):
        return [{"where": "how_to", "message": "“How to use this” is three or four plain "
                                               "steps, one a line."}]
    if any(len(x) > MOST_STEP for x in steps):
        return [{"where": "how_to", "message": f"Each step of “How to use this” is at most "
                                               f"{MOST_STEP} characters."}]
    return []


def placeholders(text) -> list[str]:
    return [m.strip() for m in _PLACEHOLDER.findall(str(text or ""))]


def _check_says(text, where, result_keys, label) -> list[dict]:
    label = label or "A result"
    if not isinstance(text, str):
        return [{"where": where, "message": f"{label}: what it says is a sentence."}]
    if len(text) > MOST_SAYS:
        return [{"where": where, "message": f"{label}: what it says is at most {MOST_SAYS} "
                                            "characters."}]
    if "{" in _PLACEHOLDER.sub("", text) or "}" in _PLACEHOLDER.sub("", text):
        return [{"where": where, "message": f"{label}: a {{ or }} that isn't a result's "
                                            "{key}."}]
    for key in placeholders(text):
        if key not in result_keys:
            return [{"where": where, "message": f"{label}: there is no result called "
                                                f"“{key}” to put in what it says."}]
    return []


def _check_value(field, value, where, label) -> list[dict]:
    kind = field.get("type")
    if value in (None, ""):
        return []
    if kind in NUMERIC:
        try:
            F._num(value)
        except (F.EvalError, ValueError, ArithmeticError):
            return [{"where": where, "message": f"The sample's {label} isn't a number."}]
        if isinstance(value, (list, dict)):
            return [{"where": where, "message": f"The sample's {label} isn't a number."}]
    elif kind == "choice":
        if str(value) not in [str(o) for o in field.get("options") or []]:
            return [{"where": where, "message": f"The sample's {label} isn't one of its "
                                                "choices."}]
    elif kind == "people":
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            return [{"where": where, "message": f"The sample's {label} is a list of names."}]
    elif isinstance(value, (list, dict)):
        return [{"where": where, "message": f"The sample's {label} is a single value."}]
    return []


def _check_sample(definition, sample) -> list[dict]:
    """A sample is a set of input values the worksheet has: no field it lacks,
    numbers that are numbers, choices that are its choices."""
    if sample in (None, {}):
        return []
    if not isinstance(sample, dict):
        return [{"where": "sample", "message": "The sample is a set of values for the fields."}]
    errors = []
    fields, table_defs = scalars(definition), tables(definition)
    for key, value in sample.items():
        where = f"sample.{key}"
        if key in table_defs:
            table = table_defs[key]
            if not isinstance(value, list) or len(value) > MOST_ROWS:
                errors.append({"where": where, "message": f"The sample's {table['label']} is "
                                                          f"a list of up to {MOST_ROWS} rows."})
                continue
            columns = {c["key"]: c for c in table["columns"] if c.get("type") != "computed"}
            for i, row in enumerate(value):
                if not isinstance(row, dict):
                    errors.append({"where": f"{where}.{i}", "message": f"Each row of the "
                                   f"sample's {table['label']} is a set of values."})
                    continue
                for ckey, cvalue in row.items():
                    if ckey == "_flag":
                        continue
                    if ckey not in columns:
                        errors.append({"where": f"{where}.{i}", "message": f"The sample's "
                                       f"{table['label']} has no column called “{ckey}”."})
                        continue
                    errors += _check_value(columns[ckey], cvalue, f"{where}.{i}",
                                           f"{columns[ckey].get('label') or ckey}, row {i + 1}")
        elif key in fields and fields[key].get("type") != "computed":
            errors += _check_value(fields[key], value, where, fields[key].get("label") or key)
        else:
            errors.append({"where": where, "message": f"The sample has a value for "
                                                      f"“{key}”, which isn't a field."})
    return errors[:20]


def _check_formula(text, where, names, label) -> list[dict]:
    try:
        node = F.compile_(text)
    except F.FormulaError as exc:
        return [{"where": where, "message": f"{label}: {exc}"}]
    unknown = sorted(F.references(node) - names)
    if unknown:
        return [{"where": where, "message": f"{label}: there is no field called "
                                            f"“{unknown[0]}”."}]
    return []


def require(definition) -> dict:
    errors = check(definition)
    if errors:
        raise DefinitionInvalid(errors)
    return definition


# ------------------------------------------------------------------ values

def _coerce(field, raw):
    kind = field.get("type")
    if kind in NUMERIC:
        if raw in (None, ""):
            return None
        try:
            return F._num(raw)
        except F.EvalError:
            return None
    if kind == "people":
        return [str(x) for x in raw] if isinstance(raw, list) else []
    if raw is None:
        return ""
    return str(raw)


def clean_values(definition, values) -> dict:
    """What a run keeps: each input field's value, each table's rows with
    their inputs and flag. Computed values are never stored."""
    values = values if isinstance(values, dict) else {}
    out = {}
    for key, field in scalars(definition).items():
        if field.get("type") == "computed":
            continue
        raw = values.get(key)
        value = _coerce(field, raw)
        out[key] = str(value) if isinstance(value, Decimal) else value
    for key, table in tables(definition).items():
        rows = values.get(key) if isinstance(values.get(key), list) else []
        kept = []
        for row in rows[:MOST_ROWS]:
            row = row if isinstance(row, dict) else {}
            cleaned = {"_flag": bool(row.get("_flag"))}
            for column in table["columns"]:
                if column.get("type") == "computed":
                    continue
                value = _coerce(column, row.get(column["key"]))
                if column.get("type") == "long_text" and column.get("max_lines") and value:
                    value = "\n".join(value.splitlines()[:int(column["max_lines"])])
                cleaned[column["key"]] = str(value) if isinstance(value, Decimal) else value
            kept.append(cleaned)
        out[key] = kept
    return out


def text_of(value, fmt="number") -> str:
    if value is None or value == "":
        return "–"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) if value else "none"
    if isinstance(value, str):
        return value
    value = Decimal(value)
    if fmt == "money":
        q = value.quantize(Decimal("0.01"))
        return f"${q:,.0f}" if q == q.to_integral_value() or abs(q) >= 1000 else f"${q:,.2f}"
    rounded = value.quantize(Decimal("0.1"))
    text = f"{rounded:,.1f}".rstrip("0").rstrip(".") if rounded != rounded.to_integral_value() \
        else f"{rounded:,.0f}"
    if fmt == "percent":
        return f"{text}%"
    if fmt == "hours":
        return f"{text} hours"
    if fmt == "people":
        return f"{text} {'person' if rounded == 1 else 'people'}"
    return text


def says(template, results) -> str:
    """A result's sentence, each {key} the text of that result. Empty when a
    result it names has no value or an error: never half-filled."""
    if not isinstance(template, str) or not template.strip():
        return ""
    found = {r["key"]: r for r in results if r.get("key")}
    texts = {}
    for key in placeholders(template):
        r = found.get(key)
        if r is None or r.get("error") or r.get("value") in (None, "") or r.get("text") == "–":
            return ""
        texts[key] = r["text"]
    return _PLACEHOLDER.sub(lambda m: texts.get(m.group(1).strip(), ""), template).strip()


#: A result's other sentences, by its value's sign (2026-11-17): a negative
#: value is said with its number shown without the sign ("4.3 hours a week to
#: spare", never "-4.3 hours ... a minus means"), and zero in words of its own.
SIGNED_SAYS = ("says_if_negative", "says_if_zero")


def _sentence_for(out, result, results):
    """The template, and the results it is filled from, for one result."""
    value = out.get("value")
    if out.get("numeric") and not out.get("error") and isinstance(value, (int, float)):
        if value < 0 and result.get("says_if_negative"):
            unsigned = text_of(Decimal(str(-value)), out.get("format", "number"))
            return result["says_if_negative"], [
                dict(r, text=unsigned) if r is out else r for r in results]
        if value == 0 and result.get("says_if_zero"):
            return result["says_if_zero"], results
    return result.get("says"), results


def _plain(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def evaluate(definition, values) -> dict:
    """Every computed field, computed column and result card, worked out from
    the values. Passes until nothing changes (at most four), so a formula may
    read a computed value defined after it; what can't be worked out says why."""
    values = clean_values(definition, values)
    fields = scalars(definition)
    table_defs = tables(definition)
    env = {}
    for key, field in fields.items():
        if field.get("type") != "computed":
            env[key] = _coerce(field, values.get(key))
    rows = {t: [{c["key"]: _coerce(c, r.get(c["key"])) for c in d["columns"]
                 if c.get("type") != "computed"} | {"_flag": r.get("_flag", False)}
                for r in values.get(t, [])] for t, d in table_defs.items()}
    compiled = {}

    def node_of(text):
        if text not in compiled:
            compiled[text] = F.compile_(text)
        return compiled[text]

    errors = {}

    def column_of(name):
        table, column = name.split(".", 1)
        if table not in rows:
            raise F.EvalError(f"There is no table called “{table}”.")
        return [r.get(column) for r in rows[table]]

    def lookup_for(row=None):
        def lookup(name):
            if row is not None and name in row:
                return row[name]
            if "." in name:
                return column_of(name)
            if name in env:
                return env[name]
            raise F.EvalError(f"“{name}” isn't worked out yet.")
        return lookup

    for _ in range(4):
        before = repr((env, rows))
        errors = {}
        for t, d in table_defs.items():
            for i, row in enumerate(rows[t]):
                for column in d["columns"]:
                    if column.get("type") != "computed":
                        continue
                    try:
                        row[column["key"]] = F.evaluate(node_of(column["formula"]),
                                                        lookup_for(row))
                    except (F.EvalError, F.FormulaError) as exc:
                        row[column["key"]] = None
                        errors[f"{t}.{i}.{column['key']}"] = str(exc)
        for key, field in fields.items():
            if field.get("type") != "computed":
                continue
            try:
                env[key] = F.evaluate(node_of(field["formula"]), lookup_for())
            except (F.EvalError, F.FormulaError) as exc:
                env[key] = None
                errors[key] = str(exc)
        if repr((env, rows)) == before:
            break
    results = []
    for result in definition.get("results") or []:
        fmt = result.get("format", "number")
        try:
            value = F.evaluate(node_of(result["formula"]), lookup_for())
            error = ""
        except (F.EvalError, F.FormulaError) as exc:
            value, error = None, str(exc)
        results.append({"key": result.get("key") or "", "label": result["label"],
                        "format": fmt, "value": _plain(value), "text": text_of(value, fmt)
                        if not error else "–", "error": error,
                        "note": result.get("note", ""),
                        "numeric": isinstance(value, Decimal)})
    for out, result in zip(results, definition.get("results") or []):
        out["says"] = says(*_sentence_for(out, result, results))
    computed = {key: {"value": _plain(env.get(key)),
                      "text": text_of(env.get(key), field.get("format", "number"))
                      if key not in errors else "–", "error": errors.get(key, "")}
                for key, field in fields.items() if field.get("type") == "computed"}
    table_out = {}
    for t, d in table_defs.items():
        out_rows = []
        for i, row in enumerate(rows[t]):
            cells = {}
            for column in d["columns"]:
                if column.get("type") != "computed":
                    continue
                k = column["key"]
                cells[k] = {"value": _plain(row.get(k)),
                            "text": text_of(row.get(k), column.get("format", "number"))
                            if f"{t}.{i}.{k}" not in errors else "–",
                            "error": errors.get(f"{t}.{i}.{k}", "")}
            out_rows.append(cells)
        table_out[t] = out_rows
    return {"values": values, "computed": computed, "tables": table_out, "results": results}
