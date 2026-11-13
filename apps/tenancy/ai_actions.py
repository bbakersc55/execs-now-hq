"""Every AI action in the app, where each runs and on which model (P7,
2026-11-10; docs/p7_mcp.md, "Actions").

An action is one or more `AiCall.purpose` strings a person knows by one name
("Explain this scorecard"). For each, the practice owner picks:

- **Runs in**: "In the app with my key", or "In my AI app" — then the in-app
  button becomes "Do this in your AI", which shows a prompt to paste into the
  AI app connected over MCP. Only an action whose records the MCP server can
  read may move (`movable`); scheduled and rule-fired runs always run in the
  app on the practice's key, whatever is chosen.
- **Model tier**: Fast, Standard or Deep, each a model id in the platform's
  `ModelTier` table, which the platform owner edits without a code change.

`model_for(tenant, purpose)` is what `claude.complete_with_call` asks.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

FAST, STANDARD, DEEP = "fast", "standard", "deep"
TIERS = (FAST, STANDARD, DEEP)

#: Used only if the platform table is missing a tier (a fresh database before
#: its migration, a test that emptied it): the current models of each tier.
FALLBACK_MODELS = {
    FAST: ("claude-haiku-5-5", Decimal("0.10"), Decimal("0.50"), False),
    STANDARD: ("claude-sonnet-5-5", Decimal("2.00"), Decimal("10.00"), True),
    DEEP: ("claude-opus-5-5", Decimal("4.00"), Decimal("20.00"), True),
}


@dataclass(frozen=True)
class Action:
    key: str
    label: str
    where: str
    purposes: tuple[str, ...]
    tier: str
    #: "user" (a button), "both" (a button, and also a job or rule), or
    #: "unattended" (only ever a job or rule: fixed in the app).
    started: str
    #: Whether "In my AI app" is offered: the MCP server must expose what it
    #: works on. False shows "In the app" fixed, with `fixed_why`.
    movable: bool
    #: The prompt "Do this in your AI" shows, with {record} named.
    prompt: str = ""
    fixed_why: str = ""
    #: P8: the Command Center that brings it ("operations"): listed only for a
    #: practice with it on.
    center: str = ""
    #: P8: False for an action with no in-app run yet: it runs in the AI app.
    in_app: bool = True

    @property
    def fixed(self) -> bool:
        return self.started == "unattended" or not self.movable or not self.in_app


SCHEDULED = "Runs on a schedule or a rule, so always in the app with your key."
AI_APP_ONLY = "Runs in your AI app in this version: it has no in-app button yet."
NOT_EXPOSED = "AI apps can't read what this works on, so it runs in the app."

ACTIONS: tuple[Action, ...] = (
    Action("scorecard_explain", "Explain this scorecard", "Scorecard", ("scorecard_explain",),
           STANDARD, "user", True,
           "Using Execs NOW HQ, read the scorecard for {record} and explain it: what moved, "
           "what is off target and why it might be, and what to ask about."),
    Action("scorecard_weekly_note", "Draft the weekly note", "Scorecard",
           ("scorecard_weekly_note",), STANDARD, "user", True,
           "Using Execs NOW HQ, read this week's scorecard for {record} and draft the weekly "
           "note to the client: what went well, what needs attention, what happens next."),
    Action("session_prep", "Prepare (session prep and its rewordings)", "Strategy session",
           ("session_prep",), STANDARD, "user", True,
           "Using Execs NOW HQ, prep me for the strategy session {record}: read the session, "
           "the contact and their company, and reword the questions for this prospect."),
    Action("strategy_rows", "Draft rows with Claude (strategy map)", "Strategy session",
           ("strategy_rows",), DEEP, "user", True,
           "Using Execs NOW HQ, read the strategy session {record} and propose Strategy Map "
           "rows into its tray: bottleneck, root cause, fix, owner, 30/60/90, measurable."),
    Action("strategy_rows_consolidate", "Consolidate with Claude", "Strategy session",
           ("strategy_rows_consolidate",), DEEP, "user", True,
           "Using Execs NOW HQ, read the strategy session {record} and its map rows, and "
           "propose a consolidated set of rows into its tray."),
    Action("strategy_mirror", "Draft the mirror", "Strategy session", ("strategy_mirror",),
           DEEP, "user", True,
           "Using Execs NOW HQ, read the strategy session {record} and draft the mirror: "
           "the bottlenecks set against the stated goal."),
    Action("strategy_diagnostic_questions", "Propose diagnostic questions", "Strategy session",
           ("strategy_diagnostic_questions",), DEEP, "both", True,
           "Using Execs NOW HQ, read the strategy session {record} and its pre-call ratings, "
           "and propose the diagnostic questions to ask."),
    Action("strategy_path_notes", "Draft pros and cons (paths)", "Strategy session",
           ("strategy_path_notes",), STANDARD, "both", True,
           "Using Execs NOW HQ, read the strategy session {record} and draft the pros and "
           "cons of each path."),
    Action("strategy_document", "Draft the words (strategy document)", "Strategy session",
           ("strategy_document",), STANDARD, "user", True,
           "Using Execs NOW HQ, read the strategy session {record} and draft the words of "
           "its strategy document."),
    Action("goal_narrative", "Draft the narrative (goal report)", "Goals", ("goal_narrative",),
           STANDARD, "user", True,
           "Using Execs NOW HQ, read the goal {record}, its projects and tasks, and draft the "
           "narrative of the progress report as value delivered."),
    Action("note_summary", "Note summary", "Notes", ("note_summary",), STANDARD, "both", True,
           "Using Execs NOW HQ, read the note {record} and summarize it."),
    Action("referral_touch", "Referral touch draft", "Contacts", ("referral_touch",),
           STANDARD, "both", True,
           "Using Execs NOW HQ, read the referral partner {record} and draft a short touch "
           "email (3 to 5 lines) into the Sending queue for approval."),
    Action("digest_prose", "Digest prose", "Digests", ("digest_prose",), STANDARD,
           "unattended", False, fixed_why=SCHEDULED),
    Action("meeting_parse", "Meeting notes reading", "Meetings", ("meeting_parse",),
           STANDARD, "both", False, fixed_why=NOT_EXPOSED),
    Action("meeting_owner_classify", "Meeting owner and contact matching", "Meetings",
           ("meeting_owner_classify",), FAST, "unattended", False, fixed_why=SCHEDULED),
    Action("finance_review_forecast", "Review with Claude (13-week forecast)", "Finance",
           ("finance_review_forecast",), DEEP, "user", False, fixed_why=NOT_EXPOSED),
    Action("finance_explain_forecast", "Explain this forecast", "Finance",
           ("finance_explain_forecast",), STANDARD, "user", False, fixed_why=NOT_EXPOSED),
    Action("finance_explain_step", "Explain this step (reconcile)", "Finance",
           ("finance_explain_step",), STANDARD, "user", False, fixed_why=NOT_EXPOSED),
    Action("finance_read_statement", "Read it with Claude (statement PDF)", "Finance",
           ("finance_read_statement",), DEEP, "user", False, fixed_why=NOT_EXPOSED),
    Action("personal_sort_lines", "Sort bank lines into categories", "Personal",
           ("personal_sort_lines",), FAST, "user", False, fixed_why=NOT_EXPOSED),
    Action("personal_review_forecast", "Review with Claude (personal forecast)", "Personal",
           ("personal_review_forecast",), DEEP, "user", False, fixed_why=NOT_EXPOSED),
    Action("personal_explain_forecast", "Explain this forecast (personal)", "Personal",
           ("personal_explain_forecast",), STANDARD, "user", False, fixed_why=NOT_EXPOSED),
    Action("personal_explain_budget", "Explain this budget", "Personal",
           ("personal_explain_budget",), STANDARD, "user", False, fixed_why=NOT_EXPOSED),
    # P8: the Operations Command Center's. Each lands where it waits for a
    # person: the SOP as a note marked as the AI app's, the rows in the
    # session's tray, the weekly note as a digest awaiting approval.
    Action("ops_sop_from_note", "Draft an SOP from a note", "Notes", ("ops_sop_from_note",),
           STANDARD, "user", True,
           "Using Execs NOW HQ, read the note {record} (list_notes) and draft a standard "
           "operating procedure from it with five parts: purpose, roles, steps, measures and "
           "review date. Show me the draft; if I say so, save it with add_note on the same "
           "company, titled \"SOP draft: \" and the procedure's name.",
           fixed_why=AI_APP_ONLY, center="operations", in_app=False),
    Action("ops_map_rows_from_meeting", "Map rows from a meeting proposal", "Meetings",
           ("ops_map_rows_from_meeting",), DEEP, "user", True,
           "Using Execs NOW HQ, read the meeting proposal {record} "
           "(pending_meeting_proposals), find the company's strategy session "
           "(list_strategy_sessions) and propose Strategy Map rows into its tray with "
           "propose_map_rows: bottleneck, root cause, fix, owner, 30/60/90, measurable.",
           fixed_why=AI_APP_ONLY, center="operations", in_app=False),
    # P11: the plans engine's drafts, with any Command Center on.
    Action("plan_draft", "Draft from sources and Break this down (plan)", "Plan",
           ("plan_draft",), DEEP, "user", False,
           fixed_why="Runs in the app on the practice's key, so its proposals land in the "
                     "plan's tray. AI apps propose items with propose_plan_items.",
           center="any"),
    # P12: the tool builder, with any Command Center on.
    Action("tool_builder", "New tool: propose a worksheet (tool builder)", "Tools",
           ("tool_builder",), DEEP, "user", False,
           fixed_why="Runs in the app on the practice's key, so the proposal opens in the "
                     "tool editor before anything is saved.", center="any"),
    Action("ops_weekly_note", "Weekly note from the scorecard", "Scorecard",
           ("ops_weekly_note",), STANDARD, "user", True,
           "Using Execs NOW HQ, read this week's scorecard_readings for {record} and draft "
           "the weekly note: what went well, what needs attention, the numbers, what "
           "happens next. Show me the draft; if I say so, save it with create_digest_draft "
           "to the company's main contact, where it waits for approval.",
           fixed_why=AI_APP_ONLY, center="operations", in_app=False),
)

BY_KEY = {a.key: a for a in ACTIONS}
BY_PURPOSE = {p: a for a in ACTIONS for p in a.purposes}


@dataclass(frozen=True)
class Resolved:
    tier: str
    model: str
    input_usd_per_mtok: Decimal
    output_usd_per_mtok: Decimal
    server_fallback: bool

    def cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        return (self.input_usd_per_mtok * input_tokens
                + self.output_usd_per_mtok * output_tokens) / Decimal(1_000_000)


def tier_row(code: str) -> Resolved:
    from apps.aiconnect.models import ModelTier

    row = ModelTier.objects.filter(code=code).first()
    if row is not None:
        return Resolved(code, row.model, row.input_usd_per_mtok, row.output_usd_per_mtok,
                        row.server_fallback)
    model, per_in, per_out, fallback = FALLBACK_MODELS[code]
    return Resolved(code, model, per_in, per_out, fallback)


def settings_for(tenant_id) -> dict:
    from apps.tenancy.models import AiActionSetting

    return {row.action: row for row in AiActionSetting.all_objects.filter(tenant_id=tenant_id)}


_LOOK = object()


def tier_for(tenant_id, action: Action, row=_LOOK) -> str:
    if row is _LOOK:
        row = settings_for(tenant_id).get(action.key)
    return row.tier if row is not None and row.tier in TIERS else action.tier


def runs_in(tenant_id, action: Action, row=_LOOK) -> str:
    if not action.in_app:
        return "ai_app"
    if action.fixed:
        return "app"
    if row is _LOOK:
        row = settings_for(tenant_id).get(action.key)
    return row.runs_in if row is not None else "app"


def model_for(tenant_id, purpose: str) -> Resolved:
    """The model a call of this purpose runs on, for this practice. A purpose
    no action names runs Standard."""
    action = BY_PURPOSE.get(purpose)
    tier = tier_for(tenant_id, action) if action is not None and tenant_id else (
        action.tier if action is not None else STANDARD)
    return tier_row(tier)


def table(tenant_id) -> list[dict]:
    """Settings → AI, "Actions": every action with its current choices."""
    from apps.centers import services as centers

    saved = settings_for(tenant_id)
    on = set(centers.enabled(tenant_id))
    out = []
    for a in ACTIONS:
        # "any": listed while any Command Center is on (the plans engine).
        if a.center == "any" and not on or a.center not in ("", "any") and a.center not in on:
            continue
        row = saved.get(a.key)
        out.append({
            "key": a.key, "label": a.label, "where": a.where, "started": a.started,
            "fixed": a.fixed, "fixed_why": a.fixed_why,
            "runs_in": runs_in(tenant_id, a, row), "tier": tier_for(tenant_id, a, row),
            "default_tier": a.tier, "prompt": a.prompt,
        })
    return out
