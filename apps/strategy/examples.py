"""Examples a practice can start a template from (P3 §9, 2026-10-08).

"Start from the Operations example" gives a practice a complete, ready-to-run
v3 template as **its own copy**. Three rules this module keeps:

- **An example is data written here**, like the seed is. Creating from one
  reads no practice's rows: no template, no session, no setting (§9.2).
- **The copy is made through the builder's own functions**, so every rule the
  builder enforces is enforced on the example, and the copy is an ordinary
  template the practice edits like any other (§9.4).
- **An example is versioned and a copy never follows it** (E9). A change to the
  wording is a new version beside the old one; the old one stays, because
  "from the example" is judged against the version a copy was made from.

The Operations wording is the industry-neutral wording of
`docs/strategy_session_seed.md` (owner, 2026-09-26): each entry below names
the seed question it is, and `tests/test_strategy_examples.py` holds the two
to the same words.
"""

from __future__ import annotations

from django.db import transaction

from apps.strategy import builder
from apps.strategy.models import StrategyQuestion
from apps.strategy.services import SessionError
from apps.tenancy.models import AuditEvent

OPERATIONS = "operations_example"


def item(seed_key, prompt, **fields):
    return {"seed_key": seed_key, "prompt": prompt, **fields}


OPERATIONS_V1 = {
    "settings": {"advisor_role": "fractional operations executive"},
    "questions": {
        builder.PRECALL: [
            item("s1_revenue", "Revenue — last year / this year",
                 label="Revenue", pdf_chip=True),
            item("s1_team", "Team — full-time / part-time / admin & management",
                 label="Team", pdf_chip=True),
            item("s1_sites", "Active customer sites (or active accounts)",
                 label="Sites", pdf_chip=True),
            item("s1_service_mix", "Service mix — contract / projects / supplies / other"),
            item("s1_branches",
                 "Branches or locations — established vs. finding footing"),
            item("s1_top_accounts", "Top 5 accounts as % of revenue"),
            item("s1_software", "Software stack — and what lives in someone's head "
                                "instead of a system"),
        ],
        builder.RATINGS: [
            item("s2_vision", "Vision — Our 3-year picture is clear, written down, and "
                              "shared by the whole leadership team.", label="Vision"),
            item("s2_people", "People — We have the right people in the right seats, "
                              "and every seat on the chart is filled.", label="People"),
            item("s2_data", "Data — We run the week from a short scorecard of numbers "
                            "(utilization, pipeline, cash).", label="Data"),
            item("s2_issues", "Issues — Problems get raised openly and solved for good, "
                              "not worked around.", label="Issues"),
            item("s2_process", "Process — Our core processes are documented, "
                               "simplified, and followed by everyone.", label="Process"),
            item("s2_traction", "Traction — Everyone has quarterly priorities and a "
                                "weekly meeting that keeps them on track.",
                 label="Traction"),
        ],
        # The fixed fallback, asked when nothing Claude proposes is accepted
        # (E3, named by the owner).
        builder.DIAGNOSTIC: [
            item("s4_decisions_stall",
                 "Where do decisions stall because they need {Visionary}?"),
            item("s4_turnover", "Turnover, time-to-fill, who recruits and how much of "
                                "their week it takes"),
            item("s4_cash_pinch", "Cash pinch points. Projects and supplies: profit "
                                  "centers or distractions?"),
        ],
        builder.MIRROR: [
            item("s3_three_year_picture",
                 "3-year picture — revenue, locations, {Visionary}'s role, "
                 "{Second-in-command}'s role"),
            item("s3_current_rocks",
                 "Current quarterly priorities (Rocks) — which is most at risk?"),
            item("s3_stalled_goal", "A goal that has been on the list for over a year — "
                                    "what has been in the way?"),
            # Never asked aloud, and off the PDF, the emails and prep unless
            # its flag is on (FR-4.17), as in the seed.
            item("s3_alignment_observation",
                 "Do {Visionary} and {Second-in-command} describe the destination "
                 "the same way?", observation=True),
        ],
        builder.VALUES: [
            item(f"s7_value_{n}", f"Value {n} — in their words, and why it matters to them")
            for n in range(1, 6)
        ],
        builder.PATHS: [
            item("s8_path_a",
                 "Path A — They run it: {Second-in-command} owns the map; rows become "
                 "next quarter's priorities (Rocks); reviewed at every weekly "
                 "leadership meeting (L10); progress depends on capacity they "
                 "already have."),
            item("s8_path_b",
                 "Path B — Run it together: fractional operator alongside "
                 "{Second-in-command}; weekly working sessions plus on-site days; "
                 "90-day sprints with measurables; execution load carried, not "
                 "just advised."),
        ],
        builder.SCOPE: [
            item("s9_scope", "Scope — which map rows are in the first 90 days"),
            item("s9_start_date", "Start date"),
            item("s9_cadence", "Sprint length / check-in cadence"),
            item("s9_investment_range", "Investment range discussed ($/month × months)",
                 is_financial=True),
            item("s9_reaction_to_range", "Their reaction to the range", is_financial=True),
            item("s9_who_else", "Who else needs to weigh in, and by when"),
            item("s9_follow_up_call", "Follow-up call booked (date/time)"),
            item("s9_map_sent", "Strategy Map sent (same day) — time"),
            item("s9_proposal_due", "Proposal due date"),
        ],
    },
}



def reworded(example, prompts: dict) -> dict:
    """A new version: the same example with some lines in other words."""
    known = {entry["seed_key"] for items in example["questions"].values()
             for entry in items}
    assert set(prompts) <= known, set(prompts) - known
    return {**example, "questions": {
        kind: [{**entry, "prompt": prompts.get(entry["seed_key"], entry["prompt"])}
               for entry in items]
        for kind, items in example["questions"].items()}}


#: Version 2 (owner, 2026-10-08): two lines that still spoke of a service
#: business, in words any practice's prospect can answer.
OPERATIONS_V2_PROMPTS = {
    "s2_data": "Data — We run the week from a short scorecard of numbers.",
    "s4_cash_pinch": "Cash pinch points: which parts of the business make money, "
                     "and which are distractions?",
}
OPERATIONS_V2 = reworded(OPERATIONS_V1, OPERATIONS_V2_PROMPTS)

#: name → {version: content}. A new version is added; none is edited.
EXAMPLES = {OPERATIONS: {1: OPERATIONS_V1, 2: OPERATIONS_V2}}


def latest(name) -> int:
    return max(EXAMPLES[name])


def content(name, version=None) -> dict:
    if not isinstance(name, str) or name not in EXAMPLES:
        raise SessionError("start_from is absent for a blank template, or one of: "
                           + ", ".join(sorted(EXAMPLES)) + ".")
    return EXAMPLES[name][version or latest(name)]


@transaction.atomic
def create(tenant, *, name, start_from, version=None):
    """`(template, version)`: a blank v3 template filled in from the example,
    one builder call per question. A part the blank template already holds
    something in (the two paths, three scope items) has those reworded in
    place rather than archived, so the copy starts with no spent keys. The
    version is the latest unless one is named, which only a test does."""
    example = content(start_from, version)
    template = builder.create_blank(tenant, name=name)
    for kind, items in example["questions"].items():
        section = builder._sections(template).get(kind=kind)
        held = list(StrategyQuestion.objects.filter(section=section, deleted_at__isnull=True)
                    .order_by("position", "created_at"))
        for position, entry in enumerate(items):
            fields = {key: value for key, value in entry.items() if key != "seed_key"}
            if position < len(held):
                if kind == builder.SCOPE:
                    fields.setdefault("is_financial", False)
                builder.edit_question(template, key=held[position].key, **fields)
            else:
                builder.add_question(template, section=section.code, **fields)
    builder.update_settings(template, example["settings"])
    return template, version or latest(start_from)


# ------------------------------------------------- "from the example" (E6)

def origin(template):
    """`(name, version)` when this template was made from an example, read
    from the audit event of its creation: where a template came from is
    recorded there and nowhere else (E7). A duplicate is its own template and
    has no origin."""
    payload = (AuditEvent.all_objects
               .filter(tenant_id=template.tenant_id, verb="strategy.template_created",
                       target_id=template.pk, payload__has_key="start_from")
               .values_list("payload", flat=True).first())
    if not payload:
        return None
    name, version = payload.get("start_from"), payload.get("example_version")
    if name not in EXAMPLES or version not in EXAMPLES[name]:
        return None
    return name, version


def represent(template) -> dict:
    """The builder's view of a template, and for one made from an example,
    which of its lines are still exactly the example's. Computed against the
    version the copy was made from, each time, so nothing is stored and
    nothing can drift. A template not made from an example gains no key."""
    out = builder.represent(template)
    made_from = origin(template)
    if made_from is None:
        return out
    name, version = made_from
    example = EXAMPLES[name][version]
    for section in out["sections"]:
        theirs = {(entry["prompt"], entry.get("label", ""))
                  for entry in example["questions"].get(section["kind"], ())}
        for question in section["questions"]:
            question["from_example"] = (question["prompt"], question["label"]) in theirs
    out["example"] = {
        "start_from": name, "version": version,
        "unchanged_settings": sorted(
            key for key, value in example["settings"].items()
            if out["settings"].get(key) == value),
    }
    return out
