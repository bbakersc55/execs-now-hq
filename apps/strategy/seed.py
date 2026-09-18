"""The Operations template, seeded **verbatim** from `docs/strategy_session_seed.md`.

Verbatim is the requirement, not a nicety: this is the owner's real session
structure, generalised from a real client call, and a reworded prompt is a
different question. Every `prompt` below is the seed document's own wording,
including its `{merge fields}` and its ★ marks (carried as `must_ask`, not as
punctuation).

Keys are assigned once here and **never reused**: a historical answer resolves
by key, so a recycled key would quietly change what a past session appears to
have answered.

The data migration seeds tenants that already exist; `seed_tenant` covers every
tenant created afterwards — the same split the CRM seed uses.
"""

from __future__ import annotations

FREE_TEXT = "free_text"
RATING = "rating_1_10"
TRIPLE = "diagnostic_triple"
VALUE_PAIR = "value_pair"
AGREED = "agreed_note"
PATH = "path_reaction"

PRECALL = "precall"
LIVE = "live"

TEMPLATE_NAME = "Operations — strategy session"
DISCIPLINE = "operations"


def q(key, prompt, *, ask_when=LIVE, schema=FREE_TEXT, must_ask=False, area="",
      note=False, observation=False, financial=False):
    return {
        "key": key, "prompt": prompt, "ask_when": ask_when, "response_schema": schema,
        "must_ask": must_ask, "area": area, "has_fractional_note": note,
        "is_fractional_observation": observation, "is_financial": financial,
    }


# (code, title, time_budget_minutes, [question, ...])
#
# Time budgets are the seed's 10/25/5/15/5/10 (FR-4.15), laid on the six LIVE
# blocks of the stated flow. §1 and §2 go out on the pre-call form, so they hold
# none; §9 runs inside §7's "what you value & next steps" block and holds none
# of its own. See the open question raised with the owner on 2026-09-18.
SECTIONS = [
    ("snapshot", "Snapshot: where they are today", None, [
        # "Fractional-only field per item: Notes / follow-up" — hence `note=True`
        # on all seven. The diagnostic carries one too: AC-4.9 names a "§4
        # internal observation" as one of the five things the PDF excludes, and
        # the data model's walkthrough has two diagnostic answers holding one.
        q("s1_revenue", "Revenue — last year / this year", ask_when=PRECALL, note=True),
        q("s1_team", "Team — full-time / part-time / admin & management",
          ask_when=PRECALL, note=True),
        q("s1_sites", "Active customer sites (or active accounts)",
          ask_when=PRECALL, note=True),
        q("s1_service_mix", "Service mix — contract / projects / supplies / other",
          ask_when=PRECALL, note=True),
        q("s1_branches", "Branches or locations — established vs. finding footing",
          ask_when=PRECALL, note=True),
        q("s1_top_accounts", "Top 5 accounts as % of revenue",
          ask_when=PRECALL, note=True),
        q("s1_software", "Software stack — and what lives in someone's head "
                         "instead of a system", ask_when=PRECALL, note=True),
    ]),
    ("six_key_components", "Six Key Components: self-rating", None, [
        q("s2_vision", "Vision", ask_when=PRECALL, schema=RATING),
        q("s2_people", "People", ask_when=PRECALL, schema=RATING),
        q("s2_data", "Data", ask_when=PRECALL, schema=RATING),
        q("s2_issues", "Issues", ask_when=PRECALL, schema=RATING),
        q("s2_process", "Process", ask_when=PRECALL, schema=RATING),
        q("s2_traction", "Traction", ask_when=PRECALL, schema=RATING),
    ]),
    # "items 1–3 may be flipped to `precall`" — seeded LIVE, and the FF may
    # override `ask_when` per question (FR-4.2).
    ("where_they_want_to_go", "Where they want to go", 10, [
        q("s3_three_year_picture",
          "3-year picture — revenue, locations, {Visionary}'s role, {Integrator}'s role"),
        q("s3_current_rocks",
          "Current Rocks (quarterly priorities) — which is most at risk?"),
        q("s3_stalled_goal",
          "A goal that has been on the list for over a year — what has been in the way?"),
        # FR-4.17 — shown to the fractional, never asked aloud.
        q("s3_alignment_observation",
          "Do {Visionary} and {Integrator} describe the destination the same way?",
          observation=True),
    ]),
    ("diagnostic", "Diagnostic: where it's breaking", 25, [
        q("s4_decisions_stall", "Where do decisions stall because they need {Visionary}?",
          schema=TRIPLE, note=True, must_ask=True, area="Leadership & succession"),
        q("s4_integrator_owns",
          "What does {Integrator} own outright? Is {Integrator} empowered to say no?",
          schema=TRIPLE, note=True, must_ask=True, area="Leadership & succession"),
        q("s4_accountability_chart",
          "Is every seat on the Accountability Chart filled — right person, right seat?",
          schema=TRIPLE, note=True, area="Leadership & succession"),
        q("s4_turnover",
          "Turnover, time-to-fill, who recruits and how much of their week it takes",
          schema=TRIPLE, note=True, must_ask=True, area="People & labor"),
        q("s4_no_show",
          "If a frontline worker no-shows tonight: what happens, who covers?",
          schema=TRIPLE, note=True, area="People & labor"),
        q("s4_span_of_control", "Span of control per supervisor / area manager",
          schema=TRIPLE, note=True, must_ask=True, area="People & labor"),
        q("s4_new_business", "Source of new business, close rate, who owns it",
          schema=TRIPLE, note=True, area="Sales engine"),
        q("s4_referrals_stopped", "If referrals stopped for 90 days?",
          schema=TRIPLE, note=True, area="Sales engine"),
        q("s4_done_right",
          "How do you know a site (job) was done right last night? "
          "Inspection cadence and tooling",
          schema=TRIPLE, note=True, must_ask=True, area="Operations & quality"),
        q("s4_location_parity", "Is {Location B} run the way {Location A} is?",
          schema=TRIPLE, note=True, area="Operations & quality"),
        q("s4_gross_margin", "Gross margin by site / service line. Pricing method.",
          schema=TRIPLE, note=True, must_ask=True, area="Money"),
        q("s4_cash_pinch",
          "Cash pinch points. Projects and supplies: profit centers or distractions?",
          schema=TRIPLE, note=True, area="Money"),
        q("s4_lost_accounts",
          "The last two lost accounts: what did they have in common?",
          schema=TRIPLE, note=True, area="Customer loss"),
        q("s4_double_customers",
          "If you doubled customer count in 18 months, what breaks first?",
          schema=TRIPLE, note=True, must_ask=True, area="Scaling stress test"),
    ]),
    # The mirror's two fields live on `strategy_session` (`mirror_goal`,
    # `mirror_unlocks`), with Claude's draft held in `proposed_mirror_*`, so the
    # section carries no questions of its own.
    ("mirror", "The mirror", 5, []),
    # Likewise the map: its rows are `strategy_map_row`, not answers.
    ("strategy_map", "Strategy Map", 15, []),
    ("what_they_value", "What they value", 10, [
        q("s7_value_1", "Value 1 — in their words, and why it matters to them",
          schema=VALUE_PAIR),
        q("s7_value_2", "Value 2 — in their words, and why it matters to them",
          schema=VALUE_PAIR),
        q("s7_value_3", "Value 3 — in their words, and why it matters to them",
          schema=VALUE_PAIR),
        q("s7_value_4", "Value 4 — in their words, and why it matters to them",
          schema=VALUE_PAIR),
        q("s7_value_5", "Value 5 — in their words, and why it matters to them",
          schema=VALUE_PAIR),
    ]),
    ("two_paths", "Two paths", 5, [
        q("s8_path_a",
          "Path A — They run it: {Integrator} owns the map; rows become next "
          "quarter's Rocks; reviewed at every L10; progress depends on capacity "
          "they already have.", schema=PATH),
        q("s8_path_b",
          "Path B — Run it together: fractional operator alongside {Integrator}; "
          "weekly working sessions plus on-site days; 90-day sprints with "
          "measurables; execution load carried, not just advised.", schema=PATH),
    ]),
    ("scope_agreement", "Scope agreement", None, [
        q("s9_scope", "Scope — which map rows are in the first 90 days", schema=AGREED),
        q("s9_start_date", "Start date", schema=AGREED),
        q("s9_cadence", "Sprint length / check-in cadence", schema=AGREED),
        # AC-4.13 / matrix 10.8 — the investment fields a VA never sees.
        q("s9_investment_range", "Investment range discussed ($/month × months)",
          schema=AGREED, financial=True),
        q("s9_reaction_to_range", "Their reaction to the range",
          schema=AGREED, financial=True),
        q("s9_who_else", "Who else needs to weigh in, and by when", schema=AGREED),
        q("s9_follow_up_call", "Follow-up call booked (date/time)", schema=AGREED),
        q("s9_map_sent", "Strategy Map sent (same day) — time", schema=AGREED),
        q("s9_proposal_due", "Proposal due date", schema=AGREED),
    ]),
]


def seed_tenant(tenant, *, apps=None):
    """Idempotent. Safe to re-run; never rewrites a question the FF has edited.

    `apps` is the migration's historical registry when called from one, and the
    live models otherwise — the same shape either way.
    """
    if apps is None:
        from apps.strategy.models import (
            StrategyQuestion, StrategySection, StrategyTemplate,
        )
    else:
        StrategyTemplate = apps.get_model("strategy", "StrategyTemplate")
        StrategySection = apps.get_model("strategy", "StrategySection")
        StrategyQuestion = apps.get_model("strategy", "StrategyQuestion")

    template, _ = StrategyTemplate.objects.get_or_create(
        tenant=tenant, name=TEMPLATE_NAME, version=1,
        defaults={"discipline": DISCIPLINE, "is_default": True},
    )
    for position, (code, title, budget, questions) in enumerate(SECTIONS):
        section, _ = StrategySection.objects.get_or_create(
            tenant=tenant, template=template, code=code,
            defaults={"title": title, "position": position,
                      "time_budget_minutes": budget},
        )
        for q_position, question in enumerate(questions):
            StrategyQuestion.objects.get_or_create(
                tenant=tenant, template=template, key=question["key"],
                defaults={**{k: v for k, v in question.items() if k != "key"},
                          "section": section, "position": q_position},
            )
    return template
