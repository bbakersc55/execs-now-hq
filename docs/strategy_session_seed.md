# Strategy Session Seed — Operations (Beta template)

This is the owner's actual strategy session structure, generalized from a real client session. Seed it verbatim as the default Operations template. Items in `{braces}` are merge fields filled per session (from the contact/company record or by the fractional when scheduling). Every question carries an `ask_when` value: **precall** (goes on the web form sent to the prospect ahead of the call) or **live** (captured in-app during the call). The fractional can override `ask_when` per question when editing their template.

Session flow and timing (about 75 minutes): 1) Where you are, where you're going — 10 min. 2) Diagnostic — 25 min. 3) The mirror — 5 min. 4) Strategy Map — 15 min. 5) Two paths — 5 min. 6) What you value & next steps — 10 min.

## Section 1 — Snapshot: where they are today (`precall`)

Free-text answers, one per line item.

1. Revenue — last year / this year
2. Team — full-time / part-time / admin & management
3. Active customer sites (or active accounts)
4. Service mix — contract / projects / supplies / other
5. Branches or locations — established vs. finding footing
6. Top 5 accounts as % of revenue
7. Software stack — and what lives in someone's head instead of a system

Fractional-only field per item: *Notes / follow-up* (never shown to the prospect).

## Section 2 — Six Key Components: self-rating (`precall`)

Each rated 1–10 with an optional comment. The app computes the average and flags the lowest score ("lowest score = where to look first").

1. Vision
2. People
3. Data
4. Issues
5. Process
6. Traction

## Section 3 — Where they want to go (`live`; items 1–3 may be flipped to `precall`)

1. 3-year picture — revenue, locations, `{Visionary}`'s role, `{Integrator}`'s role
2. Current Rocks (quarterly priorities) — which is most at risk?
3. A goal that has been on the list for over a year — what has been in the way?
4. Do `{Visionary}` and `{Integrator}` describe the destination the same way? *(fractional observation, not asked aloud)*

## Section 4 — Diagnostic: where it's breaking (`live`)

Each question captures three fields: **What they said**, **Who or what causes it?**, **What have they tried — why didn't it stick?** A `must_ask` flag (★) marks the questions to prioritize if time is short. Grouped by area; the area list is the six places growth pressure shows up first in a service business.

**Leadership & succession**
- ★ Where do decisions stall because they need `{Visionary}`?
- ★ What does `{Integrator}` own outright? Is `{Integrator}` empowered to say no?
- Is every seat on the Accountability Chart filled — right person, right seat?

**People & labor**
- ★ Turnover, time-to-fill, who recruits and how much of their week it takes
- If a frontline worker no-shows tonight: what happens, who covers?
- ★ Span of control per supervisor / area manager

**Sales engine**
- Source of new business, close rate, who owns it
- If referrals stopped for 90 days?

**Operations & quality**
- ★ How do you know a site (job) was done right last night? Inspection cadence and tooling
- Is `{Location B}` run the way `{Location A}` is?

**Money**
- ★ Gross margin by site / service line. Pricing method.
- Cash pinch points. Projects and supplies: profit centers or distractions?

**Customer loss**
- The last two lost accounts: what did they have in common?

**Scaling stress test**
- ★ If you doubled customer count in 18 months, what breaks first?

## Section 5 — The mirror (`live`, AI-assisted)

Two fields: **Goal** (their stated destination, in their words) and **Unlocks most** (which bottleneck, if fixed first, unlocks the goal). Claude drafts a first pass from Sections 3 and 4; the fractional edits.

## Section 6 — Strategy Map (`live`, AI-assisted)

3–5 rows, sequenced; each row becomes a Rock. Columns:

| # | Bottleneck | Root cause | The fix (what) | Owner | 30 / 60 / 90 | Measurable | Notes / mechanics from experience |

Claude proposes candidate rows as diagnostic answers land; the fractional accepts, edits, discards, and reorders. Sequence check prompt: "What has to happen first for the rest to work? Renumber if needed."

Worked example row (from the source sheet, keep as the in-app example): Supervisor overload → 1 supervisor covering 14 sites → Add area lead per 8 sites; move inspections to app → Integrator → 60 → Inspections per site per month → Window-cleaning co. hit this at the same size.

## Section 7 — What they value (`live`)

Up to 5 rows: **Value** (in their words) and **Why it matters to them**.

## Section 8 — Two paths (`live`)

Presented side by side; capture **Their reaction**, **Honest risk (their own words on what didn't stick)**, and **Leaning** for each.

- **Path A — They run it:** `{Integrator}` owns the map; rows become next quarter's Rocks; reviewed at every L10; progress depends on capacity they already have.
- **Path B — Run it together:** fractional operator alongside `{Integrator}`; weekly working sessions plus on-site days; 90-day sprints with measurables; execution load carried, not just advised.

## Section 9 — Scope agreement (`live`)

Each item: **Agreed on the call** and **Notes**.

1. Scope — which map rows are in the first 90 days
2. Start date
3. Sprint length / check-in cadence
4. Investment range discussed ($/month × months)
5. Their reaction to the range
6. Who else needs to weigh in, and by when
7. Follow-up call booked (date/time)
8. Strategy Map sent (same day) — time
9. Proposal due date

## Outputs

- **Same-day PDF to the prospect:** Snapshot, Six Key Components chart, the mirror, the Strategy Map, the two paths, and what they value. Excludes all fractional-only notes and Section 9 financial details unless the fractional includes them.
- **On conversion to client:** each Strategy Map row becomes a Goal (or Project — fractional chooses per row) in the task engine, carrying owner, 30/60/90 target date, and measurable, editable before the engagement starts.

## Merge fields used

`{Visionary}` (usually the founder/CEO contact), `{Integrator}` (their #2 / COO-type), `{Location A}`, `{Location B}`, `{Company}`, `{Session date}`, `{Fractional name}`. If a company has no Integrator, the template should degrade gracefully (questions referencing `{Integrator}` show a "no Integrator identified" note rather than a blank).
