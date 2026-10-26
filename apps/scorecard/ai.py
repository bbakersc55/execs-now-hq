""""Explain this scorecard" and "Draft the weekly note" (spec, "How it ties into
the rest of the app", Claude): both on the practice's own key, both only when
their button is pressed, by the practice owner or an associate.

- **What is sent:** the company's name and today's date; for each KPI the
  presser sees, its name, kind, which way is good, its target, its note on
  how it is measured, and its last periods' readings with their status; and
  the company's last meeting's notes (its title, date and summary). Nothing
  else. A per-person KPI is sent **as its total only**: no person's name and
  no person's row ever go. **Nothing about bonuses goes** (no plan, no
  amount, no earnings), and the prompt says never to speak of them.
  `what_is_sent` is the whole of it, and the tests read it.
- **It changes nothing.** It writes its `ai_call` and returns words; the
  weekly note is a draft the practice copies where it wants it.
- **Capped:** `DAILY_CAP` presses a day per practice for the two together,
  never past the practice's monthly AI budget, and on a demo visitor's copy
  never past its allowance (`claude.complete_with_call` stops it too).
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db.models import Q, Sum
from django.utils import timezone

from . import board
from . import periods as P
from .bonus import fmt
from .ties import _target_text, tiles_for

EXPLAIN, NOTE = "scorecard_explain", "scorecard_weekly_note"
PURPOSES = (EXPLAIN, NOTE)
DAILY_CAP = 20
#: Roughly what one press reads and writes, until the practice has its own
#: average: the price shown on the button before it is pressed.
TOKENS = {EXPLAIN: (2500, 500), NOTE: (2500, 700)}
MAX_TOKENS = 16000
#: The periods of each KPI sent: enough to say what moved.
PERIODS = 6
MEETING_CHARS = 4000

RULES = (
    "Use only the numbers and notes given. Where you suggest why something moved, say it "
    "as a possibility (\"may\", \"might\", \"one reason could be\"), never as a fact, and "
    "say so plainly when the notes give no reason. Never mention bonuses, pay, commission, "
    "compensation or anyone's earnings, even if asked or hinted at. Never name or single "
    "out a person's own numbers: the numbers given are the company's totals. Plain "
    "sentences; no headings; no tables."
)
SYSTEM = {
    EXPLAIN: (
        "You are helping a fractional executive read a client company's KPI scorecard. "
        "In at most 180 words, say what moved since the last period or two, what is Off "
        "track or Behind, and what might explain it, drawing on the KPIs' notes and the "
        "last meeting's notes. " + RULES),
    NOTE: (
        "You are drafting the short note a fractional executive reads out or shares at the "
        "start of a client company's weekly leadership meeting. In at most 220 words: one "
        "line on the week overall; the KPIs that are Off track or Behind, each with its "
        "number and target; anything that recovered; then two or three questions for the "
        "team to discuss, drawn from the numbers and the last meeting's notes. Write it as "
        "a draft the executive will edit, in a warm, direct voice. " + RULES),
}


class ScorecardAiRefused(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def last_meeting(company):
    """The company's latest meeting with notes: its own, or one its people
    were in (as its Call notes card reads them)."""
    from apps.crm.models import Contact
    from apps.meetings.models import Meeting

    return (Meeting.objects.filter(
        Q(client_company_id=company.pk)
        | Q(participants__contact__in=Contact.objects.filter(
            company_id=company.pk, deleted_at__isnull=True)))
        .exclude(summary="").order_by("-meeting_date", "-created_at").distinct().first())


def what_is_sent(reader, scorecard, today) -> str:
    """The whole of what goes to Claude. Kept in one place so it can be read,
    and tested, as a list."""
    from .models import Kpi

    company = scorecard.company
    kpis = list(Kpi.objects.filter(scorecard=scorecard, archived_at__isnull=True)
                .select_related("scorecard", "page", "page__team", "audience_team",
                                "reading_owner", "source_a__page__team",
                                "source_a__audience_team", "source_b__page__team",
                                "source_b__audience_team")
                .order_by("page__position", "position"))
    tiles = tiles_for(reader, kpis, today)
    parts = [f"COMPANY: {company.name}", f"TODAY: {today.isoformat()}", "KPIS:"]
    for kpi in kpis:
        tile = tiles.get(kpi.pk)
        if tile is None:
            continue
        # A per-person KPI as its total, never a row: `history` is the total's
        # when the tile has one, and a tile of only one person's row is not sent.
        if kpi.per_person and not tile.get("total"):
            continue
        head = f"- {kpi.name} ({kpi.get_kind_display()}, {kpi.get_cadence_display().lower()}"
        head += {"higher": ", higher is better", "lower": ", lower is better",
                 "range": ", within a range"}.get(kpi.direction, "") + ")"
        if kpi.per_person:
            head += ", the team's total"
        lines = [head]
        if kpi.note:
            lines.append(f"  How it's measured: {kpi.note.strip()}")
        closed = [p for p in tile.get("history") or []
                  if P.closed(date_of(p["period_start"]), kpi.cadence, today)][-PERIODS:]
        for point in closed:
            start = date_of(point["period_start"])
            value = fmt(kpi, point["value"]) if point["value"] is not None else "no reading"
            target = _target_text(kpi, point["target"])
            status = P.STATUS_LABEL.get(point["status"], "") if point["status"] else ""
            lines.append(f"  {P.long_label(start, kpi.cadence)}: {value}"
                         + (f", {target}" if target else "") + (f", {status}" if status else ""))
        parts += lines
    if len(parts) == 3:
        parts.append("(none with readings yet)")
    meeting = last_meeting(company)
    if meeting is not None:
        when = meeting.meeting_date.isoformat() if meeting.meeting_date else "undated"
        summary = meeting.summary.strip()
        if len(summary) > MEETING_CHARS:
            summary = summary[:MEETING_CHARS] + " …"
        parts += [f"LAST MEETING: {meeting.title or 'Meeting'} ({when})", summary]
    else:
        parts.append("LAST MEETING: none on record")
    return "\n".join(parts)


def date_of(text):
    from datetime import date

    return date.fromisoformat(text)


def _day_start(tenant) -> datetime:
    zone = ZoneInfo(tenant.timezone)
    return datetime.combine(timezone.localdate(timezone=zone), time.min, tzinfo=zone)


def _used_today(tenant) -> int:
    from apps.tenancy.models import AiCall

    return AiCall.all_objects.filter(tenant=tenant, purpose__in=PURPOSES,
                                     created_at__gte=_day_start(tenant)).count()


def _over_budget(tenant) -> bool:
    from apps.tenancy import ai_budget
    from apps.tenancy.models import AiCall

    budget = tenant.ai_monthly_budget_usd
    if not budget:
        return False
    month = timezone.localdate(timezone=ZoneInfo(tenant.timezone)).replace(day=1)
    spent = AiCall.all_objects.filter(
        tenant=tenant, created_at__gte=ai_budget._start_of(tenant, month)
    ).aggregate(s=Sum("cost_usd"))["s"] or Decimal("0")
    return spent >= budget


def status(tenant) -> dict:
    """What the two buttons say before they are pressed: about what a press
    costs, how many are left today, and why they can't be pressed when they
    can't."""
    from apps.tenancy import ai_budget, claude
    from apps.tenancy.context import tenant_context
    from apps.tenancy.demo import visitors

    with tenant_context(tenant.pk):
        estimates = {p: ai_budget.call_estimate(p, TOKENS[p]) for p in PURPOSES}
    used = _used_today(tenant)
    resets = _day_start(tenant) + timedelta(days=1)
    refused = ""
    stop = visitors.ai_stop(tenant)
    if stop:
        refused = stop
    elif claude.key_source(tenant) is None:
        refused = ("No Anthropic API key is set. The practice owner adds one under AI "
                   "usage.")
    elif used >= DAILY_CAP:
        refused = (f"That is today's {DAILY_CAP} for the scorecard. More from "
                   f"{resets:%-I:%M %p} tomorrow.")
    elif _over_budget(tenant):
        refused = ("This month's AI budget is spent. Raise it under AI usage, or wait "
                   "for next month.")
    return {"explain_estimate_usd": str(Decimal(estimates[EXPLAIN]).quantize(Decimal("0.0001"))),
            "note_estimate_usd": str(Decimal(estimates[NOTE]).quantize(Decimal("0.0001"))),
            "used_today": used, "cap": DAILY_CAP, "resets_at": resets.isoformat(),
            "refused": refused}


def ask(reader, scorecard, purpose, today) -> dict:
    """One press. Writes nothing but its `ai_call`."""
    from apps.tenancy import claude

    if purpose not in PURPOSES:
        raise ScorecardAiRefused("Ask to explain the scorecard or to draft the note.", 400)
    tenant = scorecard.company.tenant
    now = status(tenant)
    if now["refused"]:
        raise ScorecardAiRefused(now["refused"])
    try:
        text, call = claude.complete_with_call(
            tenant=tenant, purpose=purpose, system=claude.drafting(SYSTEM[purpose]),
            user_text=what_is_sent(reader, scorecard, today), trigger="button",
            max_tokens=MAX_TOKENS, target_type="company", target_id=scorecard.company_id)
    except claude.ClaudeRefused:
        raise ScorecardAiRefused("Claude declined to answer that.", 502) from None
    except claude.ClaudeUnavailable as exc:
        raise ScorecardAiRefused(str(exc), 502) from None
    return {"text": text, "cost_usd": str(call.cost_usd),
            "used_today": now["used_today"] + 1, "cap": DAILY_CAP}


def today_of(company):
    return board.today_for(company.tenant)
