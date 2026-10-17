"""The words on the two-page strategy document (2026-10-15).

The document was redesigned from an approved mock, for every practice: page
one carries the headline, three stat tiles, the mirror as a dark callout and
the components as cards; page two the 30/60/90 map as three boxes of bullets,
the two paths, "Before we meet again" and the sign-off band.

**Every line has a length.** The pages are a fixed size and print nothing past
their edge, so what decides whether a line fits is here, in `LIMITS`, and the
same numbers are what the editor counts against, what Claude is told, and what
a save refuses past. Words the session supplies itself (a map row's header, a
pro, the mirror) are shortened to fit at a word, with an ellipsis, rather than
being allowed to push the page over.

Where the words come from, for each part of the document:

1. what a person saved (`session.document_words`), part by part;
2. otherwise, the session's own data: the mirror, the ratings, the accepted
   map rows and path notes, the agreed next steps, a converted goal;
3. otherwise, a plain default, or nothing (an empty part is not drawn).

**The sign-off belongs to the practice** (owner, 2026-10-17). The closing
line, the email and the website are Settings → Branding's as they are now,
unless this document has its own, written in the words editor and held under
`document_words["signoff"]`. "Back to the session's own words" clears it. A
closing line saved before then (`document_words["closing"]`) is not the
document's own: the editor sent Branding's line, as it was then, with every
save, and which line that was is not kept.

Claude's draft (`proposed_document_words`) is a proposal: it reaches the
document only when a person uses it and saves, as the mirror's draft does.

**Nothing private is added here.** The parts are built from
`pdf.context_for`, which has already left out the private notes, the
observation never asked aloud and the money; what Claude is sent is the same
material the map rows are drafted from.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from django.utils import timezone

from apps.strategy import dashes

PURPOSE = "strategy_document"

#: The most characters each kind of line may hold.
LIMITS = {
    "headline": 60,
    "intro": 140,
    "tile_number": 8,
    "tile_label": 40,
    "mirror_headline": 80,
    "mirror_body": 280,
    "working": 80,
    "not_yet": 80,
    "component_name": 20,
    "component_line": 90,
    "bullet": 70,
    "owner": 16,
    "path_title": 40,
    "path_blurb": 120,
    "path_point": 40,
    "next_move": 70,
    "closing": 100,
    "email": 254,
    "website": 120,
}
#: The sign-off band's lines: Branding's, unless the document has its own.
SIGNOFF = ("closing", "email", "website")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
#: How many of each a part holds.
MOST = {"bullets": 4, "path_points": 3, "next_moves": 4, "components": 6,
        "mirror_sentences": 3}
HORIZONS = ("30", "60", "90")
PILLS = ("strong", "watch", "fix")
PILL_LABEL = {"strong": "Strong", "watch": "Watch", "fix": "Fix"}

DEFAULT_CLOSING = ("The map changes as the business does. Tell me what moved, and the "
                   "next version will show it.")

NUMBER_WORDS = ("none", "one", "two", "three", "four", "five", "six", "seven", "eight",
                "nine", "ten")


class WordsInvalid(ValueError):
    """`over` maps a line to (its length, its limit); `errors` to what else is
    wrong with it."""

    def __init__(self, message, *, over=None, errors=None):
        super().__init__(message)
        self.over = over or {}
        self.errors = errors or {}


# ------------------------------------------------------------------ helpers

def _plain(value) -> str:
    return " ".join(str(value or "").split())


def fit(text, most: int) -> str:
    """`text` in at most `most` characters: whole if it fits, else cut at a
    word with an ellipsis. For the session's own words only — a person's are
    held to the limit when they are saved."""
    text = _plain(text)
    if len(text) <= most:
        return text
    cut = text[:most - 1]
    if text[most - 1] != " " and " " in cut:
        cut = cut[:cut.rindex(" ")]          # not halfway through a word
    return cut.rstrip(" ,;:.") + "…"


def sentences(text) -> list[str]:
    text = _plain(text)
    return [part for part in re.split(r"(?<=[.!?])\s+", text) if part]


def pill_for(rating) -> str:
    """Strong from 7, Watch at 5 and 6, Fix at 4 and under; Watch with no
    rating."""
    if not isinstance(rating, int):
        return "watch"
    if rating >= 7:
        return "strong"
    if rating >= 5:
        return "watch"
    return "fix"


def number_word(n: int) -> str:
    return NUMBER_WORDS[n] if 0 <= n < len(NUMBER_WORDS) else str(n)


def _decimal(value) -> str:
    text = f"{value:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def session_day(session) -> date:
    moment = session.started_at or session.scheduled_at
    return timezone.localdate(moment) if moment else timezone.localdate()


def long_date(day: date) -> str:
    return f"{day:%B} {day.day}, {day.year}"


def short_date(day: date) -> str:
    return f"{day:%b} {day.day}"


def hidden_parts(session) -> set:
    """The parts the session's template keeps off the document (v3)."""
    from apps.strategy import services

    if not services.is_v3(session):
        return set()
    from apps.strategy import v3

    return set(v3.off_the_map(session))


# ----------------------------------------------------- from the session itself

def defaults(session, context: dict) -> dict:
    """The words the session supplies before anybody writes any: every part,
    in the saved shape, each line already fitted to its length."""
    L = LIMITS
    day = session_day(session)
    goal_points = sentences(context.get("mirror_goal"))
    unlock_points = sentences(context.get("mirror_unlocks"))
    headline = (goal_points[0] if goal_points and len(goal_points[0]) <= L["headline"]
                else "Where you are, and the next ninety days.")
    body = " ".join((goal_points + unlock_points[1:])[:MOST["mirror_sentences"]])

    components = []
    for rating in context["six_key"]["ratings"] or []:
        components.append({
            "key": rating.get("key", ""),
            "name": fit(rating["label"], L["component_name"]),
            "pill": pill_for(rating.get("rating")),
            "line": fit(rating.get("comment"), L["component_line"]),
        })

    boxes = {h: [] for h in HORIZONS}
    for row in context.get("map_rows") or []:
        horizon = str(row.get("horizon") or "")
        if horizon in boxes and len(boxes[horizon]) < MOST["bullets"]:
            boxes[horizon].append({
                "text": fit((row.get("header") or "").strip() or row["bottleneck"],
                            L["bullet"]),
                "owner": fit(row.get("owner_text"), L["owner"])})

    paths = []
    for path in context.get("path_pair") or []:
        moves = path.get("moves") or []
        paths.append({
            "side": path["side"],
            "title": fit(path["title"], L["path_title"]),
            "blurb": fit(moves[0]["headline"] if moves else "", L["path_blurb"]),
            "for": [fit(x, L["path_point"]) for x in path.get("pros") or []][:MOST["path_points"]],
            "against": [fit(x, L["path_point"])
                        for x in path.get("cons") or []][:MOST["path_points"]],
        })
    leaning = [p["side"] for p in context.get("path_pair") or [] if p.get("leaning")]

    moves = []
    for step in context.get("next_steps") or []:
        if not (step.get("agreed") or step.get("detail")):
            continue
        lead = _plain(step["label"])
        rest = _plain(step.get("detail"))
        if len(lead) + 1 + len(rest) > L["next_move"]:
            room = L["next_move"] - len(lead) - 1
            rest = fit(rest, room) if room >= 12 else ""
            lead = fit(lead, L["next_move"])
        moves.append({"lead": lead, "rest": rest})
    moves = moves[:MOST["next_moves"]]

    tile = goal_tile(session)
    if tile is None:
        count = len(context.get("map_rows") or [])
        tile = ({"number": str(count), "label": "fixes on the map, each with an owner"
                 if count != 1 else "fix on the map, with an owner"} if count else
                {"number": "", "label": ""})
    return {
        "headline": headline,
        "intro": fit(f"What we heard on {day:%B} {day.day}, where the gaps are, and the "
                     "ninety days that close them.", L["intro"]),
        "tile": tile,
        "mirror_headline": fit(unlock_points[0] if unlock_points else "",
                               L["mirror_headline"]),
        "mirror_body": fit(body, L["mirror_body"]),
        "working": "",
        "not_yet": "",
        "components": components,
        "boxes": boxes,
        "paths": paths,
        "recommended": leaning[0] if len(leaning) == 1 else "",
        "next_moves": moves,
        **branding_signoff(session),
    }


def branding_signoff(session) -> dict:
    """The sign-off as Settings → Branding has it now: its closing line, else
    the standard one; its email, else the session owner's; its website, else
    the first web address in the footer."""
    from apps.strategy import pdf as pdf_service

    tenant = session.tenant
    return {"closing": fit(tenant.document_closing or DEFAULT_CLOSING, LIMITS["closing"]),
            "email": tenant.document_email or (session.owner.email if session.owner_id
                                               else ""),
            "website": pdf_service.website_of(tenant)}


def signoff_overrides(session) -> dict:
    """The sign-off lines this document has of its own. A closing line saved
    before 2026-10-17, at `document_words["closing"]`, is Branding's copy and
    is not read."""
    saved = session.document_words or {}
    own = saved.get("signoff") if isinstance(saved.get("signoff"), dict) else {}
    return {key: own[key] for key in SIGNOFF if _plain(own.get(key))}


def goal_tile(session) -> dict | None:
    """Tile one from the map's first goal with a target: the target, and the
    baseline it moves from, in its unit. None before conversion."""
    from apps.work.models import Goal

    goal = (Goal.objects.filter(source_map_row__session=session, target_value__isnull=False)
            .order_by("created_at").first())
    if goal is None:
        return None
    unit = (goal.measurable_unit or "").strip()
    tight = unit in ("%", "x")
    number = _decimal(goal.target_value) + (unit if tight else "")
    if len(number) > LIMITS["tile_number"]:
        number = fit(number, LIMITS["tile_number"])
    what = _plain(goal.measurable or goal.title)
    if not tight and unit:
        what = f"{unit}, {what[:1].lower()}{what[1:]}" if what else unit
    if goal.baseline_value is not None:
        start = _decimal(goal.baseline_value) + (unit if tight else "")
        way = {"up_is_good": "up from", "down_is_good": "down from"}.get(goal.direction,
                                                                        "from")
        what = f"{way} {start}: {what[:1].lower()}{what[1:]}" if what else f"{way} {start}"
    return {"number": number, "label": fit(what, LIMITS["tile_label"])}


# ------------------------------------------------------- saved over defaults

def merged(session, context: dict) -> dict:
    """What the document says: each part a person saved, over the session's
    own words."""
    base = defaults(session, context)
    saved = session.document_words or {}
    out = dict(base)
    for key in ("headline", "intro", "mirror_headline", "mirror_body", "working", "not_yet",
                "recommended"):
        if key in saved:
            out[key] = saved[key]
    out.update(signoff_overrides(session))
    if isinstance(saved.get("tile"), dict):
        out["tile"] = {"number": saved["tile"].get("number", ""),
                       "label": saved["tile"].get("label", "")}
    by_key = {c.get("key"): c for c in saved.get("components") or [] if isinstance(c, dict)}
    out["components"] = [{**c, **{f: by_key[c["key"]][f] for f in ("name", "pill", "line")
                                  if f in by_key.get(c["key"], {})}}
                         for c in base["components"]]
    if isinstance(saved.get("boxes"), dict):
        out["boxes"] = {h: saved["boxes"].get(h, base["boxes"][h]) for h in HORIZONS}
    saved_paths = {p.get("side"): p for p in saved.get("paths") or [] if isinstance(p, dict)}
    out["paths"] = [{**p, **{f: saved_paths[p["side"]][f]
                             for f in ("title", "blurb", "for", "against")
                             if f in saved_paths.get(p["side"], {})}}
                    for p in base["paths"]]
    if "next_moves" in saved:
        out["next_moves"] = saved["next_moves"]
    return out


# ---------------------------------------------------------------- the save

def _line(value, kind, where, over) -> str:
    text = _plain(value)
    if len(text) > LIMITS[kind]:
        over[where] = [len(text), LIMITS[kind]]
    return text


def clean(payload) -> dict:
    """What a person saved, in the stored shape, or WordsInvalid naming each
    line that is over its length. Only the parts sent are kept."""
    if not isinstance(payload, dict):
        raise WordsInvalid("Send the document's words.")
    over: dict = {}
    errors: dict = {}
    out: dict = {}
    for key in ("headline", "intro", "mirror_headline", "mirror_body", "working",
                "not_yet"):
        if key in payload:
            out[key] = _line(payload[key], key, key, over)
    # The sign-off the document has of its own: a line left out, or empty,
    # is Branding's. The editor sends all of it, so it replaces what was kept.
    if "signoff" in payload:
        own = payload["signoff"] if isinstance(payload["signoff"], dict) else {}
        out["signoff"] = {}
        for key in SIGNOFF:
            value = _line(own.get(key), key, f"signoff.{key}", over)
            if key == "email" and value and not _EMAIL.match(value):
                errors["signoff.email"] = "Use an email address, like you@yourpractice.com."
            if value:
                out["signoff"][key] = value
    if "mirror_body" in out and len(sentences(out["mirror_body"])) > MOST["mirror_sentences"]:
        errors["mirror_body"] = "The mirror is three sentences at most."
    if "tile" in payload:
        tile = payload["tile"] if isinstance(payload["tile"], dict) else {}
        out["tile"] = {"number": _line(tile.get("number"), "tile_number", "tile.number", over),
                       "label": _line(tile.get("label"), "tile_label", "tile.label", over)}
    if "recommended" in payload:
        side = _plain(payload["recommended"]).lower()
        if side not in ("", "a", "b"):
            errors["recommended"] = "Recommend path A, path B, or neither."
        out["recommended"] = side
    if "components" in payload:
        out["components"] = []
        for index, item in enumerate(payload["components"] or []):
            if not isinstance(item, dict) or not item.get("key"):
                continue
            pill = _plain(item.get("pill")).lower() or "watch"
            if pill not in PILLS:
                errors[f"components.{index}.pill"] = "Strong, Watch or Fix."
            out["components"].append({
                "key": str(item["key"]),
                "name": _line(item.get("name"), "component_name",
                              f"components.{index}.name", over),
                "pill": pill,
                "line": _line(item.get("line"), "component_line",
                              f"components.{index}.line", over)})
    if "boxes" in payload:
        boxes = payload["boxes"] if isinstance(payload["boxes"], dict) else {}
        out["boxes"] = {}
        for h in HORIZONS:
            items = [b for b in boxes.get(h) or [] if isinstance(b, dict)
                     and (_plain(b.get("text")) or _plain(b.get("owner")))]
            if len(items) > MOST["bullets"]:
                errors[f"boxes.{h}"] = f"Day {h} holds {MOST['bullets']} bullets at most."
            out["boxes"][h] = [
                {"text": _line(b.get("text"), "bullet", f"boxes.{h}.{i}.text", over),
                 "owner": _line(b.get("owner"), "owner", f"boxes.{h}.{i}.owner", over)}
                for i, b in enumerate(items)]
    if "paths" in payload:
        out["paths"] = []
        for path in payload["paths"] or []:
            if not isinstance(path, dict) or path.get("side") not in ("a", "b"):
                continue
            side = path["side"]
            cleaned = {"side": side}
            for field, kind in (("title", "path_title"), ("blurb", "path_blurb")):
                if field in path:
                    cleaned[field] = _line(path[field], kind, f"paths.{side}.{field}", over)
            for field in ("for", "against"):
                if field in path:
                    points = [p for p in (path[field] or []) if _plain(p)]
                    if len(points) > MOST["path_points"]:
                        errors[f"paths.{side}.{field}"] = (
                            f"{MOST['path_points']} at most, for and against.")
                    cleaned[field] = [_line(p, "path_point", f"paths.{side}.{field}.{i}", over)
                                      for i, p in enumerate(points)]
            out["paths"].append(cleaned)
    if "next_moves" in payload:
        moves = [m for m in payload["next_moves"] or [] if isinstance(m, dict)
                 and (_plain(m.get("lead")) or _plain(m.get("rest")))]
        if len(moves) > MOST["next_moves"]:
            errors["next_moves"] = f"{MOST['next_moves']} next moves at most."
        out["next_moves"] = []
        for i, move in enumerate(moves):
            lead, rest = _plain(move.get("lead")), _plain(move.get("rest"))
            length = len(lead) + (1 + len(rest) if rest else 0)
            if length > LIMITS["next_move"]:
                over[f"next_moves.{i}"] = [length, LIMITS["next_move"]]
            out["next_moves"].append({"lead": lead, "rest": rest})
    if over or errors:
        message = (f"{len(over)} line{'s are' if len(over) != 1 else ' is'} over "
                   f"{'their' if len(over) != 1 else 'its'} length on the document. "
                   f"Shorten {'them' if len(over) != 1 else 'it'} to save."
                   if over else next(iter(errors.values())))
        raise WordsInvalid(message, over=over, errors=errors)
    return out


def save(session, payload, *, actor) -> dict:
    """Save the parts sent, over what was saved before. `{"reset": true}`
    clears the saved words, and the document reads from the session again."""
    from apps.tenancy.models import AuditEvent

    if isinstance(payload, dict) and payload.get("reset"):
        session.document_words = {}
    else:
        before = session.document_words
        words = {**(before or {}), **clean(payload)}
        words.pop("closing", None)          # Branding's copy, from before 2026-10-17
        if "signoff" in payload:
            # A line the same as Branding's now is Branding's, so it follows
            # Branding when Branding changes.
            branding = branding_signoff(session)
            words["signoff"] = {key: value for key, value in words["signoff"].items()
                                if value != branding[key]}
            if not words["signoff"]:
                del words["signoff"]
        session.document_words = words
        # Every line within its length can still, all together, fill a page:
        # the page is measured, and a save that would run it into its footer
        # is refused, naming the page, before anything is kept.
        from apps.strategy import pdf as pdf_service

        full = pdf_service.overflowing_pages(session)
        if full:
            session.document_words = before
            pages = " and ".join(f"page {n}" for n in full)
            raise WordsInvalid(
                f"With these words {pages} {'runs past its' if len(full) == 1 else 'run past their'} "
                f"foot. Shorten a few lines on {'it' if len(full) == 1 else 'them'} to save.",
                errors={"pages": full})
    session.save(update_fields=["document_words", "updated_at"])
    AuditEvent.all_objects.create(
        tenant=session.tenant, actor=actor, verb="strategy.document_words_saved",
        target_type="strategy_session", target_id=session.pk,
        payload={"parts": sorted(session.document_words)})
    return session.document_words


def represent(session) -> dict:
    """For the editor: the words as the document has them, what is saved,
    Claude's draft if there is one, the limits, and the computed tiles."""
    from apps.strategy import pdf as pdf_service

    context = pdf_service.context_for(session)
    page = for_pdf(session, context)
    return {"words": merged(session, context), "saved": session.document_words or {},
            "proposed": session.proposed_document_words or {},
            "signoff": {"branding": branding_signoff(session),
                        "own": signoff_overrides(session)},
            "limits": LIMITS, "most": MOST, "hidden": sorted(hidden_parts(session)),
            "tiles": page["tiles"], "box_dates": page["box_dates"],
            # The session's own words are fitted line by line but never saved,
            # so the page is measured here too, and the editor says so.
            "full_pages": pdf_service.overflowing_pages(session)}


# -------------------------------------------------------------- for the PDF

def for_pdf(session, context: dict) -> dict:
    """The document's two pages, ready to draw: the merged words, minus any
    part the template keeps off the document, with the tiles worked out."""
    words = merged(session, context)
    hidden = hidden_parts(session)
    day = session_day(session)
    components = [] if "ratings" in hidden else words["components"]
    for component in components:
        component["pill_label"] = PILL_LABEL.get(component.get("pill"), "Watch")
    paths = [] if "paths" in hidden else words["paths"]
    if len(paths) > 2:
        paths = paths[:2]
    mirror_on = "mirror" not in hidden
    boxes = [] if "map" in hidden else [
        {"days": h, "date": short_date(day + timedelta(days=int(h))),
         "bullets": words["boxes"].get(h) or []} for h in HORIZONS]
    if not any(box["bullets"] for box in boxes):
        boxes = []
    undated = [] if "map" in hidden else [
        fit((row.get("header") or "").strip() or row["bottleneck"], LIMITS["bullet"])
        for row in context.get("map_rows") or [] if not row.get("horizon")]
    # A box holds four. A fifth row in a horizon is named under the boxes, not
    # dropped, while the boxes are still the map's own rows.
    also = []
    if "map" not in hidden and "boxes" not in (session.document_words or {}):
        counted: dict = {}
        for row in context.get("map_rows") or []:
            horizon = str(row.get("horizon") or "")
            if horizon in HORIZONS:
                counted[horizon] = counted.get(horizon, 0) + 1
                if counted[horizon] > MOST["bullets"]:
                    also.append(fit((row.get("header") or "").strip() or row["bottleneck"],
                                    LIMITS["bullet"]))

    tiles = []
    if "map" not in hidden and words["tile"].get("number"):
        tiles.append(words["tile"])
    if components:
        fixes = sum(1 for c in components if c.get("pill") == "fix")
        tiles.append({"number": str(len(components)),
                      "label": f"components assessed, {number_word(fixes)} to fix"})
    if paths:
        recommended = words["recommended"] in {p["side"] for p in paths}
        tiles.append({"number": str(len(paths)),
                      "label": "paths, one recommended" if recommended
                      else "paths to choose between"})
    for path in paths:
        path["recommended"] = path["side"] == words["recommended"]
    next_moves = [] if "scope" in hidden and "next_moves" not in (
        session.document_words or {}) else words["next_moves"]
    # "Book the review: thirty minutes" reads on with no space before its colon.
    next_moves = [{**m, "tight": (m.get("rest") or "")[:1] in ",.:;"} for m in next_moves]
    return {
        "words": words,
        "headline": words["headline"],
        "intro": words["intro"],
        "tiles": tiles,
        "mirror": {"headline": words["mirror_headline"], "body": words["mirror_body"],
                   "working": words["working"], "not_yet": words["not_yet"]}
        if mirror_on and (words["mirror_headline"] or words["mirror_body"]) else None,
        # Six cards fill the page; a seventh and eighth are named beneath.
        "components": components[:MOST["components"]],
        "also_rated": [f"{c['name']} ({c['pill_label']})"
                       for c in components[MOST["components"]:]],
        "components_count": number_word(len(components)),
        "boxes": boxes,
        "box_dates": {h: short_date(day + timedelta(days=int(h))) for h in HORIZONS},
        "undated": undated,
        "also": also[:3],
        "paths": paths,
        "next_moves": next_moves,
        "closing": words["closing"],
        "email": words["email"],
        "website": words["website"],
        "long_date": long_date(day),
    }


# ----------------------------------------------------------- Claude's draft

SYSTEM = """\
You are writing the words of a two-page strategy document a fractional operations \
executive sends a prospect the same day as their strategy session. You are given \
what was said in the session, the mirror read back to them, how they rated \
themselves, the map as accepted, the two paths and what was agreed next.

The document is visual and short. Bullets, not paragraphs. Every line has a \
hard length, in characters, and a line over its length will not fit the page:

- "headline": the one line the document leads with, at most 60 characters.
- "intro": one line under it, at most 140.
- "tile": {"number": a short figure, at most 8, "label": what it counts, at most \
40}. Only a figure the input states. If there is none, {"number": "", "label": ""}.
- "mirror_headline": what we heard, as one line, at most 80.
- "mirror_body": up to three sentences, at most 280 in all.
- "working": one thing that is working, at most 80. "not_yet": one thing that is \
not yet, at most 80.
- "components": one object for each rated component you are given, with its "key", \
and "line": one line on where it stands, at most 90.
- "boxes": {"30": [...], "60": [...], "90": [...]}: two to four bullets in each, \
each {"text": at most 70, "owner": the person who owns it, a first name or a role \
of at most 16, as the input names them, or ""}. What is done by day 30, 60 and 90, from the map.
- "paths": [{"side": "a" or "b", "title": at most 40, "blurb": one line, at most \
120, "for": two or three short points, "against": two or three short points}], \
each point a few words, at most 40.
- "next_moves": four items, each {"lead": the action, a few words, "rest": the \
detail}, lead and rest together at most 70.

Assert nothing that is not in the input: no figures, names, dates or causes it \
does not state, no claim about the practice's results elsewhere, and no promise of \
an outcome. Name an owner only where the input names one. Write to the reader as \
"you" where a line addresses them.

Write no em dashes. Where you would use one, use a comma, a colon or a new \
sentence.

Reply with JSON only, an object with exactly those keys. No prose around it, no \
markdown fence."""


def draft_input(session, context: dict) -> str:
    from apps.strategy import ai

    lines = [ai.drafting_input(session)]
    company = context.get("company") or ""
    lines.append(f"\nThe company: {company or 'not named'}. The session: "
                 f"{long_date(session_day(session))}.")
    if context.get("mirror_goal") or context.get("mirror_unlocks"):
        lines.append("\nThe mirror, as read back to them:")
        if context.get("mirror_goal"):
            lines.append(f"  their goal: {context['mirror_goal']}")
        if context.get("mirror_unlocks"):
            lines.append(f"  what unlocks it: {context['mirror_unlocks']}")
    ratings = context["six_key"]["ratings"] or []
    if ratings:
        lines.append("\nThe rated components (key, name, rating of 10, their comment):")
        for rating in ratings:
            comment = f" — \"{rating['comment']}\"" if rating.get("comment") else ""
            lines.append(f"  {rating.get('key', '')}: {rating['label']}, "
                         f"{rating['rating']}{comment}")
    rows = context.get("map_rows") or []
    if rows:
        lines.append("\nThe map as accepted, in priority order:")
        for row in rows:
            horizon = f"{row['horizon']} days" if row.get("horizon") else "not dated"
            owner = f", owner {row['owner_text']}" if row.get("owner_text") else ""
            lines.append(f"  [{horizon}{owner}] {row.get('header') or row['bottleneck']}: "
                         f"{row.get('statement') or row.get('the_fix') or ''}".rstrip(": "))
    for path in context.get("path_pair") or []:
        lines.append(f"\nPath {path['side'].upper()}: {path['title']}")
        for move in path.get("moves") or []:
            lines.append(f"  {move['headline']}")
        for label, items in (("for", path.get("pros")), ("against", path.get("cons"))):
            for item in items or []:
                lines.append(f"  {label}: {item}")
        if path.get("leaning"):
            lines.append(f"  their leaning: {path['leaning']}")
    steps = [s for s in context.get("next_steps") or [] if s.get("agreed") or s.get("detail")]
    if steps:
        lines.append("\nAgreed next:")
        lines += [f"  {s['label']}: {s.get('detail') or 'agreed'}" for s in steps]
    return "\n".join(lines).strip()


def _drafted(payload: dict) -> dict:
    """Claude's reply in the stored shape. A line over its length is kept as
    written: the editor shows the count, and the save refuses it until a
    person shortens it."""
    out: dict = {}
    for key in ("headline", "intro", "mirror_headline", "mirror_body", "working",
                "not_yet"):
        if isinstance(payload.get(key), str):
            out[key] = dashes.sentence(_plain(payload[key]))
    tile = payload.get("tile")
    if isinstance(tile, dict):
        out["tile"] = {"number": _plain(tile.get("number")), "label": _plain(tile.get("label"))}
    components = payload.get("components")
    if isinstance(components, list):
        out["components"] = [{"key": str(c.get("key")), "line": dashes.sentence(_plain(c.get("line")))}
                             for c in components if isinstance(c, dict) and c.get("key")]
    boxes = payload.get("boxes")
    if isinstance(boxes, dict):
        out["boxes"] = {h: [{"text": dashes.sentence(_plain(b.get("text"))),
                             "owner": _plain(b.get("owner"))}
                            for b in (boxes.get(h) or []) if isinstance(b, dict)
                            and _plain(b.get("text"))][:MOST["bullets"]]
                        for h in HORIZONS}
    paths = payload.get("paths")
    if isinstance(paths, list):
        out["paths"] = [{"side": p["side"], "title": _plain(p.get("title")),
                         "blurb": dashes.sentence(_plain(p.get("blurb"))),
                         "for": [_plain(x) for x in p.get("for") or [] if _plain(x)][:3],
                         "against": [_plain(x) for x in p.get("against") or []
                                     if _plain(x)][:3]}
                        for p in paths if isinstance(p, dict) and p.get("side") in ("a", "b")]
    moves = payload.get("next_moves")
    if isinstance(moves, list):
        out["next_moves"] = [{"lead": _plain(m.get("lead")), "rest": _plain(m.get("rest"))}
                             for m in moves if isinstance(m, dict)
                             and _plain(m.get("lead"))][:MOST["next_moves"]]
    return out


def draft(session, *, trigger="button") -> dict | None:
    """Claude's words for the document, into `proposed_document_words`.
    Never the saved words: using the draft is a person's act."""
    from apps.strategy import ai, pdf as pdf_service
    from apps.tenancy import claude

    context = pdf_service.context_for(session)
    user_text = draft_input(session, context)
    if not user_text:
        return None
    try:
        text = claude.complete(
            tenant=session.tenant, purpose=PURPOSE, system=ai._system(SYSTEM, session),
            user_text=user_text, target_type="strategy_session", target_id=session.pk,
            trigger=trigger, max_tokens=3000)
    except (claude.ClaudeUnavailable, claude.ClaudeRefused):
        return None
    payload = ai._json_payload(text)
    if not isinstance(payload, dict):
        return None
    session.proposed_document_words = _drafted(payload)
    session.save(update_fields=["proposed_document_words", "updated_at"])
    return session.proposed_document_words
