# Besty feed: what Besty's MCP server exposes, and what the scorecard reads

M5 part 6. Written 2026-10-28 from a live connection: `initialize`,
`tools/list` and `describe_export_schemas` on `https://mcp.getbesty.ai/mcp`
with the read-only token in `.env` as `BESTY_MCP_TOKEN` (never printed,
logged or committed), and one aggregated call per measure to confirm Besty
accepts each query as written. The column tables below are Besty's own
schema answer, unedited except for spacing; "Carries" is ours, worked out
from each column's name and type, to answer what the feed can be built on.

## Summary

- **The server.** `ask-besty-mcp` 0.1.0, MCP protocol `2025-03-26`, over
  Streamable HTTP. `initialize` answers as a one-event SSE stream and sets
  `Mcp-Session-Id`; `notifications/initialized` answers 202; every later call
  carries the session id and `Authorization: Bearer`. A token reads one
  Besty account, read-only, and `tools/list` shows
  only the tools its scopes grant: this token sees **124 tools**.
- **The tools.** 86 `export_*` / `compute_*` tools with a described schema
  (one more, `compute_call_summary`, has none), 36 `list_*` / `get_*` tools
  over the account's configuration (workflows, journeys, guidebook pages,
  upsell settings, agreements, users, ops departments and templates), and
  `describe_export_schemas`. Every export takes `filter`, `time_range`,
  `fields`, `include_pii` and `aggregation`.
- **Answers.** `result.content[0].text` is JSON: `{"ok": [{"mode":
  "inline", "rows": [...], "warnings": [...]}], "failed": [...]}`. A refusal
  is `result.isError` with plain words ("compute_response_time window is 92
  days; max is 90 days"). **Large answers are not gzipped NDJSON:** they are
  `"mode": "file"`, `"format": "parquet"`, with a `presigned_url` (S3, valid
  24 hours). The feed never asks for one: it uses Besty's aggregation grammar
  (`measures` like `count(*)`, `sum(revenue_amount)`, `avg(rating)`;
  `filters` with `eq`, `neq`, `lt`, `gte`, `is_null`…; `dimensions`;
  `limit`), whose answers are small and inline. Numbers come back as
  strings. `aggregation.time.granularity` does not bucket rows (grouping by a
  timestamp groups by the exact instant), so the feed asks once per period.
  Should a gzipped NDJSON link ever come, it is fetched without the token,
  read, and dropped; a Parquet one is refused in words (the app has no
  Parquet reader, and adding one wasn't worth it for an answer the feed
  never asks for).
- **Windows.** Besty clamps or refuses long windows: ops tasks, threads and
  calls 365 days; reviews and upsells 730; messages 31; response time 90
  (refused past it). The feed reads a longer period in pieces and adds them
  up (a quarter's response time is two pieces, each with Besty's own
  outlier rule, weighted by replies).
- **Due dates, assignees, completion times.** Ops tasks carry all three:
  `due_at`, `is_overdue`, `hours_late`; `assignee_subuser_ids` /
  `assignee_names`; `completed_at`, `status`. **Besty deliberately does not
  give created-to-completed time**: 86% of automation-made tasks have
  negative cycle times. It offers `time_total_seconds` (timer-tracked work)
  instead. The feed's "average days to close" is therefore only for tasks a
  person made (`created_by` = `person`), with any negative span dropped;
  "average tracked work time" is the measure Besty recommends.
  `export_ops_task_history` has every status and assignee change with its
  actor and time.
- **Contacts and timestamps.** Messages carry `thread_id`, `subuser_id`
  (who sent it), `sender_type` (guest, host, host_external, autopilot,
  automated) and `created_at`; property owners (`export_owners`) each have a
  `thread_id`. So a **per-user, per-owner contact log is supported**: the
  messages a team member sent on an owner's thread, by period. Calls carry
  `thread_id`, `answered_by_subuser_id`, `initiated_by_subuser_id` and
  times; CRM contact events carry `contact_id`, `kind`, `occurred_at` and
  `created_by_subuser_id` (manual events); internal thread notes carry their
  author. Guest identity (names, emails, phones) is behind `include_pii`,
  which the feed never sets.
- **Revenue.** `export_upsell_events` (purchases, de-duplicated as Besty's
  revenue dashboard does: standard upsells, damage waivers, workflow-sold),
  `export_reservations` and `export_reservation_financials` (stay revenue),
  `export_payment_ledger`, `summarize_upsell_revenue`.
- **Reviews and rating.** `export_reviews`: `rating` out of
  `rating_denominator` (5, or 10 on some channels), category sub-scores
  where the PMS sends them, `has_reply`, `has_major_issue`, `reviewed_at`.
- **Guest response time.** `compute_response_time`: the dashboard's figure,
  per day or for the window, per responder (`autopilot` or a team member's
  name), with its outlier rule. It includes autopilot's delay.
- **What the token's account holds** (a real client's, so only counts
  here): reviews (about 550 in the last year), inbox threads, 154 property
  owners, 15 team members and 219 listings; **no ops tasks, upsell
  purchases, calls or synced reservations in the last year**, and no
  replies for response time. So the measures over those read 0 or nothing on
  this account until it uses them; every query was still accepted live.

## The measures built

On the menu (`apps/scorecard/besty.py`, `MEASURES`), each for a monthly,
quarterly or weekly KPI, read for each closed period once a day on the
worker by the Sheets feed's rules (hand-entered wins, nothing deleted, one
notice on a failed read), the open period too where the feed reads it as it
goes. Nothing Besty answers is stored beyond the readings.

| Measure | Besty tool | KPI kind | For |
|---|---|---|---|
| Ops tasks open (at the period's end) | `export_ops_tasks` | Count | total or one team member |
| Ops tasks overdue (at the period's end) | `export_ops_tasks` | Count | total or one team member |
| Ops tasks completed | `export_ops_tasks` | Count | total or one team member |
| Ops tasks: average days to close (made by a person) | `export_ops_tasks` | Duration | total or one team member |
| Ops tasks: average tracked work time | `export_ops_tasks` | Duration | total or one team member |
| Upsell revenue | `export_upsell_events` | Money | total or one upsell type |
| Upsells sold | `export_upsell_events` | Count | total or one upsell type |
| Guest response time (average) | `compute_response_time` | Duration | everyone, people only, autopilot only, or one team member |
| Reviews received | `export_reviews` | Count | the account |
| Average rating (out of 5) | `export_reviews` | Rating | the account |
| Messages to owners (sent by people) | `export_messages` + `export_owners` | Count | total, one team member, one owner, or both |
| Owners contacted | `export_messages` + `export_owners` | Count | total or one team member |
| Calls answered | `export_calls` | Count | total or one team member |

Open at a period's end is "made before it, and not completed by then"; a
task Besty shows as done with no completion time is not counted open, and a
task made more than 365 days earlier is past Besty's window. Messages to
owners count only `host` and `host_external` messages (a person, in Besty or
the PMS), never automated or autopilot ones. Average rating puts each
denominator's average out of 5.

Not built, and why: occupancy, ADR and revenue per stay (Track already
reads them, and this account has no synced reservations); sentiment (Besty:
about 80% of threads are never scored, and null is not neutral); turnover
readiness (a today-only view, not a period's number).

## Every tool and every column

### Configuration tools (`list_*`, `get_*`)

| Tool | Arguments | What it does |
|---|---|---|
| `list_workflows` | `filter`, `page`, `page_size` | Filtered + paginated list of the account's automation workflows — use this to answer "what will Besty do when X happens?" by scanning names/descriptions, then fetch matches with get_workflows. Each row exposes id, name, description, is_enabled, has_trigger_config, is_sub_workflow, published_at, and scope_summary ({listing_count, listing_set_names[]}). Filters: is_enabled, published_after (ISO date |
| `get_workflows` | `workflow_ids` | Fetch full workflow definitions by id (from list_workflows): the trigger configuration (what event starts it, with conditions) and the step graph (the messages, tasks, and actions Besty executes). Returns the PUBLISHED definition, i.e. what actually runs; has_unpublished_changes=true means an unreleased edit exists but its content is not exposed here. Cap 100 ids per call; unknown ids are reported |
| `list_anchor_events` | `include_payload_attributes` | Catalog of events that can trigger workflows on this account (e.g. a guest message, a reservation reaching a lifecycle moment), filtered to events the account is actually configured for. Each entry has name and optionally payload_attributes describing the data available when the event fires. Use to understand what Besty can react to; pass include_payload_attributes=false for a slimmer response. |
| `list_journeys` | `active_only` | List scheduled message campaigns (journeys): id, name, active, message count, and the listing set ids the journey applies to. Use to answer "what messages does every guest get, and when?" — then fetch details with get_journey. Map listing set ids to listings via list_listing_sets to check coverage. |
| `get_journey` | `journey_id` | Fetch one journey fully hydrated: every message (content, send timing relative to its anchor event, per-message conditions), journey-level conditions, and the listing sets it applies to. Use after list_journeys to read exactly what guests are told and when. |
| `list_journey_event_catalog` | none | Catalog of events and conditions journey messages can be anchored to. Timing anchors include "booking", "check-in", "check-out", "check-out-or-departure" plus account-specific catalog entries where isEvent=true. Time units may be "hours", "days", or "months". Use to interpret the timing/conditions returned by get_journey. |
| `list_journey_overall_conditions` | none | Schema of journey-level audience conditions supported by this account (e.g. stay_type, campaign, rate_type, tags). Each entry has a key, prettyName, description, and fields[]; enum fields list their options, and polarity is a field conventionally named "include_or_exclude". Returns [] when the account's booking platform has no journey-level conditions. Use to interpret the journey_conditions retur |
| `list_pages` | none | List all guidebook pages the account shows to guests, each with its section name + icon and visibility settings. Use to scan what topics are covered (house rules, wifi, check-in instructions, local tips), then fetch full content with get_page. |
| `get_page` | `page_id` | Fetch one guidebook page (by page_id from list_pages) with its full HTML content and any attached place data. This is the actual guest-facing text — use it to answer "what are guests told about X in the guidebook?". |
| `list_channels` | none | List the booking-channel options guidebook pages can be shown or hidden on (channel names vary by the account's booking platform). Use to interpret per-page visibility settings from list_pages. |
| `list_sections` | none | List the guidebook's section structure with page-count totals. Use with list_pages to understand how guest-facing content is organized. |
| `get_guidebook_checkout_config` | none | Read the guidebook checkout-button feature config: whether it is enabled and which listings it applies to. Use when asked whether guests can check out from the guidebook. |
| `list_pending_auto_hostnotes` | `status`, `page`, `page_size` | Paginated read of the Teach Besty queue: knowledge-base entries Besty extracted from real guest conversations. Filter by status — 'pending' = learned and awaiting the host's confirmation, 'accepted' = confirmed and added to the knowledge base, 'rejected', 'processing', 'failed', or 'all'; default 'pending'. Each row carries the extracted datapoints, the source guest message body, guest name, and l |
| `get_listing_kb_summary` | `listing_ids` | Per-listing knowledge-base coverage rollup for the given listing ids (from list_listings): how many knowledge-base notes apply to each listing (including account-wide notes), which categories are covered, and whether the listing's knowledge embeddings are fresh or pending a refresh. Use to spot listings with thin or stale knowledge coverage. For reading the notes themselves, use export_hostnotes. |
| `get_upsell_settings` | none | Read the account-level upsell configuration: upsell_percentage (numeric markup, default 6.00), upsell_timing_limits (time-of-day send window or null), upsell_pricing_option (per_night/total/etc), upsells_include_taxes, and upsell_approval_mode (true = host must pre-approve each offer before it is sent). There is no account-level upsell kill-switch; upsells can be disabled per reservation. Use to a |
| `list_custom_upsells` | `listing_type` | List the account's enabled custom upsell offerings. Each item has id, name, description, listing scope (listing_type 'all'\|'individual'\|'set' plus the listing or listing-set id), price + price_type ('flat'\|'perNight'\|'variable'), and reminder configuration. Use to answer "do we offer/sell X?" for ad-hoc items (firewood, pool heating, equipment rental). Built-in upsell types (early check-in, la |
| `get_upsell_fees` | `listing_ids`, `include_similar_listings` | Resolve the upsell fee setup (extra charges and tax) that applies to each given listing id (from list_listings). For each listing returns the fees array ({name, amount}), the tax_rate (decimal), how the setup is scoped ('Individual listings'\|'Listing sets'\|'All listings'\|'Default'), and which other listings share the same setup. Lookup precedence is per-listing → listing-set → all-listings; fir |
| `summarize_upsell_revenue` | `start_date`, `end_date` | Canonical total upsell revenue over a window — the fastest way to get THE upsell revenue number. Returns total_revenue (rounded) and currency; includes upsell, damage waiver, and workflow-sold upsell revenue. export_upsell_events covers the same three sources, de-duplicated with the same key, and is the right tool for a per-reservation or per-item breakdown; summing its is_acceptance rows reproduc |
| `list_listings` | `include_virtual`, `besty_enabled_only` | List the account's listings with friendly labels: id, pms_id, display_name (the label the host sees in their dashboard), nickname, internal_name, and is_besty_enabled. Resolve property names to ids here FIRST — listing ids returned by this tool are what every other tool's listing_id inputs and outputs refer to. Excludes virtual listings by default. |
| `list_listing_sets` | `include_listing_ids` | List the account's listing sets (named groupings of listings). Each set has id (uuid), name, and listing_ids[]. Journeys, workflows, and several configs scope to listing sets — use this to expand a set id into concrete listings (e.g. to check whether a journey really covers every guest). Pass include_listing_ids=false if you only need id+name. |
| `list_messaging_fields` | `query`, `editable_only`, `scope`, `listing_id`, `listing_set_id` | List the account's messaging template variables: custom fields (source='custom_field') with their current value and scope (all_listings \| listing_set \| this_listing), plus read-only tokens from the booking platform (source='pms'), Besty internals (source='besty_internal'), and rental-agreement fields (source='rental_agreement' — the structured fields collected by the rental agreement, e.g. quiet |
| `get_direct_booking_url` | `listing_id` | Read the direct booking URL configured for a listing (by listing_id from list_listings). Returns null when none is set. |
| `list_agreement_templates` | none | List the account's rental agreement templates: name, whether the template is active, and its settings (age minimum, ID verification). Page content is excluded here — fetch it with get_agreement_template. Use to answer "what agreement do guests sign?". Which listings and channels each template covers is a separate lookup: list_agreement_applications. |
| `get_agreement_template` | `template_id` | Fetch one rental agreement template (by template_id from list_agreement_templates) with its full page content: the actual text a guest reads and signs, plus the interactive fields (signature, guest details) the signing flow collects. |
| `list_agreement_applications` | none | List which rental agreement template applies to which listings, booking channels, and timing. Use with list_agreement_templates to answer "which guests get which agreement, and when are they asked to sign?". Resolve listing ids via list_listings and channel values via list_agreement_channels. |
| `list_agreement_addendums` | none | List agreement addendums: extra pages appended to the base rental agreement, each with the listings it applies to. Use to find property-specific terms (pool rules, pet policies) layered on top of the main agreement. Fetch full content with get_agreement_addendum. |
| `get_agreement_addendum` | `addendum_id` | Fetch one agreement addendum (by addendum_id from list_agreement_addendums) with its full page content and the listings it applies to. |
| `list_agreement_channels` | none | List the exact booking-channel values that agreement channel filters match against. These vary by booking platform: Streamline accounts match stay-type codes such as "SC-ABnB" rather than display names such as "Airbnb". Use these values verbatim when reading or setting agreement scope; anything else is rejected. |
| `list_users` | `include_inactive` | List the team logins on the account: id, name, email, phone, type (admin, regular, or owner), role, and state. is_account marks the account's main login. Deactivated logins are excluded unless include_inactive is true. Use to answer "who has access to this account?". |
| `list_users_for_account` | none | List team logins with their payroll fields: default hourly rate, currency, and profile picture. Use when the question is about pay rates rather than access; use list_users for access and contact details. |
| `list_ops_departments` | none | List the account's ops departments: the shared built-ins (Cleaning, Maintenance, Inspection, Guest Services) plus any custom departments. Returns id, name, and is_custom. Departments are referenced by id elsewhere, so resolve a name to its id here before passing one, for example when changing an ops task notification setting. |
| `list_ops_task_templates` | `department_id` | List the account's ops task templates: reusable task definitions with a title, department, default description, priority, due time, estimated duration, and checklist (requirement_items). Use to find the template id to pass to create_ops_tasks as task_template_id, so the new task gets the template's checklist and costs. department_id resolves to a name via list_ops_departments. Optional filter: dep |
| `list_ops_tags` | none | List the account's ops task tags with id and name, sorted by name. Use to resolve a tag name to the id that create_ops_tasks and update_ops_tasks take in tag_ids. |
| `list_ops_issue_templates` | `listing_ids` | List the account's issue templates: the kinds of problem the team can report, such as damage or a missing item. An issue is always created from a template, which supplies its title. Each entry has id, title, description, which listings it applies to, and its questions (requirement_items). Pass listing_ids (from list_listings) to get only the templates that cover all of those listings. Use it to fi |
| `list_ops_bulk_assignments` | none | List the account's bulk assignment rules: named rules that say who gets a department's or a task template's tasks on a set of listings, either assigned directly to team members or offered to them to claim in timed windows. Returns fingerprint, config_count, and configs in order. Each config has name, level ('department' or 'task_template'), department_id or task_template_id, subdepartment_ids, sco |
| `list_notification_preferences` | none | Read the notification settings for the login this connection belongs to: which events send an alert, and over which channel. A row means that alert is ON; no row means it is OFF. This connection cannot see other team members' settings. Ops task alerts are per department, so read list_ops_departments to interpret the department ids. Change a setting with toggle_notifications. |

### Export and compute tools

`compute_call_summary` is listed but has no schema in `describe_export_schemas`: "Canonical call metrics for the account's phone lines… calls answered and made per team member… max 92 days."

#### `compute_occupancy`

Per-bucket occupancy derived from reservations.arrival_date/departure_date. Supports compare_to: 'prior_period' \| 'yoy'.

Join keys: `period`, `group_key`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `period` | date | time | Bucket start (truncated by grain). |
| `group_key` | string |  | Grouping value (listing_id when group_by=listing; "_all" otherwise). |
| `nights_booked` | int |  | Number of nights blocked by qualifying reservations. |
| `available_nights` | int |  | Bucket-nights × listing count. For group_by='all', uses the host's total Besty-enabled listings (idle ones included). For group_by='listing', the multiplier is 1 (the group_key IS the listing). |
| `occupancy_pct` | float |  | nights_booked / available_nights (0..1). Fleet-wide for group_by=all (idle listings counted in the denominator); per-listing for group_by=listing. |
| `nights_booked_prior` | int |  | Comparison-window booked nights (present when compare_to is set). |
| `occupancy_pct_prior` | float |  | Comparison-window occupancy_pct (present when compare_to is set). |

Besty's caveats:

- Default status filter ['confirmed'] (mapped via resolvePmsStatuses across all BFF PMSes).
- available_nights denominator for group_by='all' counts the host's total Besty-enabled listings (idle listings included). Empty buckets emit zero occupancy rows.
- Besty-only standalone listings (pms ical, ops cleaning only) are excluded from both the numerator and the denominator.
- Stays not yet assigned to a unit (Beds24, Cloudbeds, Mews room-type rows) count in group_by='all', capped per night at the room type's units in scope. group_by='listing' cannot place them on a unit and returns an unassigned_stays_excluded warning.
- compare_to='prior_period' uses immediately-preceding window of same length; 'yoy' uses same calendar window 1 year prior.

#### `compute_response_time`

Per-day average host response time to guest messages, broken down by responder (autopilot or a named subuser). Same query and outlier rule as the dashboard. Source is raw bt_messages, NOT the response_times aggregate table.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `date` | date | time | Bucket date. |
| `responder_label` | string | assignee | "autopilot" \| subuser name / email / id. |
| `avg_response_minutes` | float |  | Average response latency in minutes, after dropping unusually long waits per responder, as the dashboard does (includes autopilot delay). |
| `response_count` | int |  | Number of replies in this bucket. |

Besty's caveats:

- Runs the dashboard query (analytics/responseTimeQuery.ts) unchanged, including its outlier rule: per responder, replies more than 3 standard deviations above the mean in log minutes are dropped (only when the responder has 20 or more replies).
- Values include autopilot delay (raw next-message gap, not human-only).
- Does NOT read from the response_times aggregate table (worker silently broken since 2025-07-08 — see out-of-scope production ticket).
- Default window is the last 30 days.

#### `export_ad_feed_diffs`

Bulk export of Meta ad feed membership changes, one row per listing added to or removed from the feed by a run. Answers which listings entered or left the ad catalog and when. `run_started_at` comes from the run row via inner join. Primary time field is run_started_at.

Primary time field: `run_started_at`. Limits: raw row cap 5000. Join keys: `diff_id`, `run_id`, `listing_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `diff_id` | int |  | Diff row id. |
| `run_id` | int |  | Feed run that produced the change. Join key to export_ad_feed_runs.run_id. |
| `site_index` | int |  | Direct booking site whose catalog changed. 1 is the primary site. |
| `run_started_at` | timestamp | time | When that run started (inner join on run_id and user_id, converted from epoch seconds). |
| `run_status` | string |  | Status of the run that produced the change. |
| `listing_id` | int |  | Besty internal listing id that was added or removed. |
| `listing_name` | string |  | Listing name at the time of the run. |
| `action` | string |  | 'added' (listing entered the feed) or 'removed' (listing left the feed). |
| `details` | string |  | Free-text reason, for example why a listing was excluded. NULL when the job gave none. |

Besty's caveats:

- Only membership changes are recorded. Price changes for a listing that stayed in the feed do not appear here.
- Inner join to ads_meta_feed_runs drops diff rows whose run row was deleted.
- Empty on accounts that do not run Meta ads through Besty.

#### `export_ad_feed_prices`

Bulk export of the prices Besty is advertising to Meta (Facebook and Instagram) travel ads, one row per listing, check-in date and length of stay. Answers "what prices are we advertising right now". Money columns are parsed from the feed's "399.48 USD" text into numbers; `price_raw` is opt-in. The table holds tens of thousands of rows per account, so filter by `listing_ids`, `length_of_stay` or `checkin_from` / `checkin_to`. Primary time field is refreshed_at; `time_range.field=checkin_date` windows by stay date.

Primary time field: `refreshed_at`. Limits: raw row cap 5000. Join keys: `listing_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `listing_id` | int |  | Besty internal listing id the price row advertises. |
| `checkin_date` | date | time | Check-in date the advertised price is for (stored as YYYY-MM-DD text). |
| `length_of_stay` | int |  | Nights the advertised price covers. Each listing has several length-of-stay variants per check-in date. |
| `price` | float |  | Advertised total for the stay in major units, numeric part of the feed value (base plus tax plus fees). |
| `base_price` | float |  | Accommodation-only total for the stay in major units. |
| `tax` | float |  | Tax total for the stay in major units. |
| `fees` | float |  | Fee total (cleaning and other fees) for the stay in major units. |
| `currency` | string |  | ISO currency code for the money columns. |
| `nightly_price` | float |  | price / length_of_stay, rounded to 2 decimals. NULL when length_of_stay is 0. |
| `refreshed_at` | timestamp | time | When the feed job last wrote this row (converted from epoch seconds). |
| `price_raw` | string |  | The feed value as published, for example "399.48 USD". |

Besty's caveats:

- Rows are the current feed snapshot, not history. A row is overwritten on each successful run, and refreshed_at is the last write, not when the price changed.
- The table is dense: one row per listing per check-in date per length of stay (about 8 variants) across roughly six months. Unfiltered reads hit the row cap. Filter by listing_ids or checkin dates.
- Money columns are stored as text like "399.48 USD". The numeric fields parse the leading number; a value in an unexpected format yields NULL.
- Empty on accounts that do not run Meta ads through Besty.

#### `export_ad_feed_runs`

Bulk export of Meta ad feed regeneration runs, one row per run, with status, row counts, sizes and timings. Answers whether the feed is refreshing and when it last succeeded. Runs are per direct booking site (`site_index`) and have no listing attribution. `started_at` and `ended_at` are converted from epoch seconds. Primary time field is started_at.

Primary time field: `started_at`. Limits: raw row cap 5000. Join keys: `run_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `run_id` | int |  | Feed run id. |
| `site_index` | int |  | Direct booking site the run published for. 1 is the primary site; multi-site accounts have one catalog per site. |
| `status` | string |  | 'running' (in progress), 'success', 'failed' (see error_message), 'skipped' (nothing to regenerate). |
| `started_at` | timestamp | time | When the run started (converted from epoch seconds). |
| `ended_at` | timestamp | completion, time | When the run finished. NULL while running. |
| `duration_seconds` | int |  | ended_at minus started_at in seconds. NULL while running. |
| `hotel_row_count` | int |  | Listings written to the hotel (property) feed file. |
| `prices_row_count` | int |  | Price rows written to the prices feed file. |
| `hotel_bytes` | int |  | Size of the hotel feed file in bytes. |
| `prices_bytes` | int |  | Size of the prices feed file in bytes. |
| `hotel_seconds` | float |  | Time spent building the hotel feed. |
| `prices_seconds` | float |  | Time spent building the prices feed. |
| `error_message` | string |  | Error text when status='failed'. NULL otherwise. |

Besty's caveats:

- The job runs on a schedule, so most rows are 'success' with the same row counts. A 'skipped' run means nothing changed. Look at 'failed' rows and error_message for problems.
- Row counts and byte sizes are NULL on skipped, failed and running rows.
- Empty on accounts that do not run Meta ads through Besty.

#### `export_autopilot_response_logs`

Bulk export of Autopilot response-log rows, one per AI drafting job. seconds_to_complete includes queue and model time. Primary time field is created_at.

Primary time field: `created_at`. Limits: raw row cap 10000, max window days 365, default window days 30. Join keys: `response_log_id`, `job_group_id`, `reservation_id`, `listing_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `response_log_id` | int |  | AI response log id. |
| `job_group_id` | int |  | Queue job group id. It is not unique and can group several rows. |
| `created_at` | timestamp | time | When the AI drafting job was created. |
| `processed_at` | timestamp | time | When processing started. |
| `completed_at` | timestamp | completion, time | When processing completed. |
| `prompt_type` | string |  | Prompt path used for the job. |
| `error` | string |  | Recorded processing error, when present. |
| `has_error` | bool |  | Whether an error was recorded. |
| `is_completed` | bool |  | Whether completed_at is set. |
| `seconds_to_complete` | float |  | Seconds from creation to completion. Includes queue and model time. |
| `seconds_queued` | float |  | Seconds from creation until processing started. |
| `external_reservation_id` | string |  | PMS reservation id. |
| `reservation_id` | int |  | Besty reservation linked by PMS id. |
| `listing_id` | int |  | Besty listing linked to the reservation. |
| `queue_job_id` | int |  | Underlying GPT job queue id. |

Besty's caveats:

- completed_at is null for running jobs or jobs that crashed before writing completion.
- error is null on success and may miss runtime failures recorded in Datadog.
- The pilot account showed 0 errors in a 30-day window, so a zero here does not prove nothing failed.
- seconds_to_complete includes queue and model time.
- Rows with null user_id are unreachable.

#### `export_autopilot_runs`

Bulk export of row-level Autopilot runs. Use aggregation for weekly run, escalation, and mode counts. Escalation reason fields are parsed from sparse Vellum output and cannot be grouped by aggregation. Primary time field is created_at.

Primary time field: `created_at`. Limits: raw row cap 10000, max window days 365, default window days 30. Join keys: `run_id`, `thread_id`, `reservation_id`, `listing_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `run_id` | int |  | Besty Autopilot run id. |
| `created_at` | timestamp | time | When the Autopilot run started. |
| `thread_id` | int |  | Besty inbox thread. chatbot_logs.hostaway_conversation_id stores this thread id as text, not a PMS conversation id. |
| `reservation_id` | int |  | Besty reservation linked to the thread. |
| `external_reservation_id` | string |  | PMS reservation id linked to the thread. |
| `listing_id` | int |  | Besty listing linked to the reservation. |
| `is_escalated` | bool |  | Whether this run escalated the guest turn. |
| `is_autopilot` | bool |  | Whether this run was an automatic send. False means draft or suggest mode. |
| `guest_message` | string |  | Incoming guest message answered by the run. |
| `summary` | string |  | AI-generated run summary. |
| `final_draft` | string |  | Final drafted response. |
| `end_conversation_raw` | jsonb |  | Raw end-conversation value from the Autopilot log. |
| `ended_conversation` | bool |  | True when the raw end-conversation value is boolean true or the string true. |
| `escalation_reason_raw` | jsonb |  | Raw Vellum escalation categorization. It may be an object, a JSON string, an empty string, or null. |
| `escalation_top_level_reason` | string |  | Top-level escalation reason key parsed from the categorization. |
| `escalation_category` | string |  | Escalation category parsed from the categorization. |
| `escalation_notes` | string |  | Escalation notes parsed from the categorization. |
| `belongs_in_sop` | string |  | Usually a boolean-like value indicating whether the issue belongs in an SOP. |
| `belongs_in_static_data` | string |  | Usually a boolean-like value indicating whether the issue belongs in static data. |
| `has_escalation_reason` | bool |  | Whether a non-empty escalationReason value is stored. The parsed reason columns are null when the value is not valid categorization JSON. |
| `escalation_reason_parsed` | bool |  | Whether escalationReason contains valid categorization JSON. |

Besty's caveats:

- hostaway_conversation_id is a thread id, not a PMS conversation id.
- Thread and listing joins are left joins, so linked ids are null when source rows are gone.
- escalationReason is empty on most escalated rows (on the pilot account 5101 of about 5105 escalated rows in 30 days were an empty string), so the parsed reason columns are null for most rows and any count by reason under-counts escalations. Parsing runs in the tool, not SQL, so `aggregation` cannot group by the parsed reason columns; fetch rows and group client-side.
- Empty on accounts that do not use Autopilot or drafts.
- conversation_content and system_prompt are not exposed.

#### `export_availability_ranges`

Live PMS availability ranges for up to 50 listings and 365 inclusive dates. Compresses consecutive available nights into checkout-exclusive ranges.

Join keys: `listing_id`, `start_date`, `end_date`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `listing_id` | int |  | Besty internal listing id. |
| `start_date` | date | time | First available stay date in the range. |
| `end_date` | date | time | Checkout date after the final available night, exclusive. |
| `nights` | int |  | Number of available nights in this contiguous range. |
| `availability_source` | string |  | pms_realtime when fetched live from PMS; fallback when using cache + reservations. |
| `synced_at` | timestamp | time | ISO timestamp for this availability ranges sync call. |

Besty's caveats:

- Each call attempts live PMS fetches with prefer=live. If the requested window exceeds a PMS hard cap, rows use availability_source=fallback.
- Fallback rows come from cache + reservations and may understate PMS-side manual blocks when cache coverage is sparse.
- Ranges are availability-only. They do not validate minimum stay, check-in rules, checkout rules, or quoteability.
- Listings with no available nights return no rows.

#### `export_blog_posts`

Bulk export of blog posts on the direct booking site, one row per post. Answers how many posts are live, what is in draft, and what was published when. `status` is 'draft' or 'published'; `published_at` is NULL on drafts. Body, HTML, hero and the AI generation trace are opt-in. Account-level; no listing attribution. Primary time field is created_at; use `time_range.field=published_at` for publish dates.

Primary time field: `created_at`. Limits: raw row cap 5000. Join keys: `post_id`, `slug`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `post_id` | int |  | Blog post id. |
| `slug` | string |  | URL slug of the post on the site. |
| `title` | string |  | Post title. |
| `subtitle` | string |  | Subtitle shown under the title. NULL when none. |
| `description` | string |  | Meta description used for SEO. Empty string when unset. |
| `excerpt` | string |  | Short teaser shown in post lists. NULL when unset. |
| `category` | string |  | Primary category label. |
| `categories` | array |  | All category labels (text array). May contain an empty string on older rows. |
| `status` | string |  | 'draft' (not on the public site) or 'published' (live). |
| `is_published` | bool |  | True when status is 'published'. |
| `post_date` | string |  | Display date string shown on the post, as the author typed it. Not a timestamp; empty when unset. Use published_at for ordering. |
| `published_at` | timestamp | time | When the post went live. NULL on drafts. |
| `site_index` | int |  | Which of the account's direct booking sites the post belongs to. Defaults to 1. |
| `thumb_url` | string |  | Thumbnail image URL. NULL when none. |
| `thumb_alt` | string |  | Thumbnail alt text. |
| `word_count` | int |  | Approximate word count of body_html with tags stripped. NULL when body_html is NULL. |
| `created_at` | timestamp | time | When the post was created. |
| `updated_at` | timestamp | time | Last edit. |
| `turn_started_at` | timestamp | time | When the AI writing turn that produced the current draft began. NULL for hand-written posts. |
| `dek` | string |  | Standfirst paragraph under the subtitle. |
| `hero` | jsonb |  | Hero image block: {url, alt, ...}. |
| `body` | jsonb |  | Structured body blocks the editor stores. |
| `body_html` | string |  | Rendered HTML of the body. |
| `generation` | jsonb |  | AI generation trace (model, prompt, outline). NULL for hand-written posts. |
| `grounding` | jsonb |  | Facts the AI used when writing (listing details, local info). |

Besty's caveats:

- post_date is free text the author typed for display. It can be empty or disagree with published_at. Order and window by published_at.
- word_count strips HTML tags with a regex and splits on whitespace, so it is approximate.
- Posts have no listing id. Grounding may mention listings but is not a join key.
- Empty on accounts without a direct booking site or with no blog.

#### `export_booking_acknowledgements`

One row per booking acknowledgement recorded during direct-booking checkout. OTA bookings do not appear. The reservation link comes through the checkout session PMS id and can be NULL until booking sync completes. Primary time field is accepted_at.

Primary time field: `accepted_at`. Limits: raw row cap 5000. Join keys: `acknowledgement_id`, `checkout_session_id`, `reservation_id`, `listing_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `acknowledgement_id` | int |  | Policy acknowledgement id. |
| `checkout_session_id` | int |  | Direct-booking checkout session id. |
| `checkout_status` | string |  | Checkout session status. |
| `listing_id` | int |  | Direct-booking listing id. |
| `pms_reservation_id` | string |  | PMS reservation id from the checkout session. NULL until the checkout produces a booking. |
| `reservation_id` | int |  | Besty reservation linked by the checkout session PMS id. booking_acknowledgements.reservation_id itself is unpopulated in production. |
| `check_in` | date | time | Requested direct-booking check-in date. |
| `check_out` | date | time | Requested direct-booking check-out date. |
| `guest_name` | string | contact | Guest display name. |
| `policy_source` | string |  | Policy source: preset or listing_override. |
| `policy_key` | string |  | Policy key, such as strict, moderate, or firm. |
| `policy_version` | int |  | Policy version accepted by the guest. |
| `content_hash` | string |  | Hash of the accepted policy content. |
| `content_snapshot` | string |  | Full policy text shown during checkout. |
| `accepted_at` | timestamp | time | When the guest accepted the policy. |
| `ip_address` | string |  | Guest IP address. |
| `user_agent` | string |  | Guest browser user agent. |
| `created_at` | timestamp | time | When the acknowledgement row was created. |

Besty's caveats:

- Only direct-booking checkouts record acknowledgements. OTA bookings never appear.
- The reservation link is by PMS id through the checkout session and is NULL until the booking syncs.
- Empty on accounts that do not use direct booking.

#### `export_broadcasts`

Bulk export of broadcasts from reservation messaging and Marketing Hub email. The two sources have different audiences and channels. Marketing counts are attributed to the broadcast state, while reservation counts come from recipient jobs and exclude previews. Primary time field is created_at.

Primary time field: `created_at`. Limits: raw row cap 2000, max window days 1825. Join keys: `broadcast_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `broadcast_id` | string |  | Broadcast id. |
| `source` | string |  | Broadcast system: 'reservation_broadcast' or 'marketing_email'. |
| `created_at` | timestamp | time | When the broadcast was created. |
| `sent_at` | timestamp | time | When a marketing email was sent. |
| `state` | string |  | Derived state: reservation broadcasts use 'empty' \| 'queued' \| 'failed' \| 'partially_failed' \| 'sent'; marketing broadcasts use 'queued' \| 'sent' \| 'failed'. |
| `state_raw` | string |  | Stored marketing broadcast state. |
| `name` | string | contact | Marketing broadcast name. |
| `subject` | string |  | Broadcast subject. |
| `channel` | string |  | Channel: text or html for reservation broadcasts, email for marketing broadcasts. |
| `audience_size` | int |  | Number of intended recipients, excluding preview jobs for reservation broadcasts. |
| `sent_count` | int |  | Number of recipient jobs completed successfully, or audience size for a sent marketing broadcast. |
| `failed_count` | int |  | Number of failed recipient jobs, or audience size for a failed marketing broadcast. |
| `pending_count` | int |  | Number of pending recipient jobs, or audience size for a queued marketing broadcast. |
| `skipped_no_email` | int | contact | Marketing recipients skipped because they had no email. |
| `error` | string |  | Marketing broadcast error. |
| `body_preview` | string |  | Message text for reservation broadcasts and rendered HTML for marketing emails, limited to 200 characters. |
| `body` | string |  | Message text for reservation broadcasts and rendered HTML for marketing emails. |
| `template_name` | string |  | Marketing template name. |
| `audience_description` | string |  | Marketing audience description. |
| `created_by_subuser_id` | string | assignee | Subuser id that created the marketing broadcast. |
| `selected_phone_number_id` | string | contact | Selected phone number id for reservation broadcasts. |

Besty's caveats:

- Reservation broadcasts target reservations; marketing emails target CRM contacts.
- Marketing sent and failed counts represent the whole broadcast state, not per-recipient delivery.
- Opened, clicked, and delivered metrics live in Customer.io and are not stored here.
- Reservation recipient counts exclude preview jobs.
- Marketing broadcasts do not create bt_messages rows.
- Accounts that never used one path return no rows from it (the pilot account has 0 reservation broadcasts and 2 marketing broadcasts).
- `states` filters the stored marketing state only; reservation broadcasts have no stored state, use the derived `state` column client-side.

#### `export_calendar`

Day-by-day availability for one or more listings over a date range. Uses production calendar overlap semantics via the besty-data MCP DB pool. Max 50 listings per call.

Join keys: `listing_id`, `date`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `listing_id` | int |  | Besty listing id. |
| `date` | date | time | YYYY-MM-DD calendar date. |
| `available` | bool |  | True if no blocking reservation (and no cache block, if source=reservations+cache). |

Besty's caveats:

- Default source='reservations' (only blocking reservations). Pass source='reservations+cache' to overlay bt_calendar_cache manual blocks.
- Warning surfaces when cache coverage is <30% for the user × date range.
- Behaviour matches the production dashboard widget and widgetV2 Phase-1 filter.

#### `export_calendar_gaps`

Runs of consecutive available nights from the cached PMS calendar. Use is_bounded_before and is_bounded_after to distinguish a run between blocked periods from the edge of cached coverage. Filter with from_date/to_date; time_range is not supported because the data is forward-looking.

Primary time field: `gap_start`. Limits: raw row cap 20000. Join keys: `listing_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `listing_id` | int |  | Besty internal listing id. |
| `gap_start` | date | time | First available night in the consecutive run. |
| `gap_end` | date | time | Checkout-exclusive end, the first night after the run that is blocked or not cached. |
| `nights` | int |  | Number of consecutive available nights in the run. |
| `is_bounded_before` | bool |  | True when the night before the run is cached as blocked. |
| `is_bounded_after` | bool |  | True when the night after the run is cached as blocked. |
| `is_orphan_gap` | bool |  | True when both sides of the available run are bounded by cached blocked nights. |
| `cached_at` | timestamp | time | Most recent cache write inside the run. |

Besty's caveats:

- The cache mirrors PMS availability and freshness varies by listing. A run edge can be the edge of cached coverage rather than a booking.
- This export contains availability only. It does not apply minimum-stay or check-in rules; join export_daily_rates for those details.
- Listings without cached available nights have no rows. A CALENDAR_NOT_SYNCED warning lists listings whose cache is missing for part or all of the window: their availability there is unknown, so read them with export_live_calendar.
- Orphan settings are not joined.
- Besty-only standalone listings (pms ical, ops cleaning only) are excluded: they have no PMS calendar.

#### `export_call_transcripts`

Bulk export of call transcript turns, one row per turn. `is_incoming` is true for the remote party or caller and false for the host side. Search matches any term with stemming, while quoted searches use exact web-search phrase semantics and digit-bearing terms match literal substrings. Transcript and recording ownership routes through the linked call. Orphan recordings with no call log are excluded. Calls have no listing attribution. Primary time field is turn_at.

Primary time field: `turn_at`. Limits: raw row cap 5000, max window days 365, default window days 30. Join keys: `call_id`, `recording_id`, `thread_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `transcript_item_id` | int |  | Transcript turn id. |
| `call_id` | int |  | Besty call log id. |
| `call_sid` | string |  | Provider call id. A v3: prefix identifies Telnyx. A CA prefix identifies Twilio. |
| `recording_id` | int |  | Besty call recording id. |
| `thread_id` | int |  | Besty messaging thread linked to the call. |
| `turn_at` | timestamp | time | Timestamp of this transcript turn. |
| `is_incoming` | bool |  | True for the remote party or caller. False for the host side. |
| `body` | string |  | Transcript text for this turn. |
| `call_summary` | string |  | AI-generated summary for the call recording. |
| `call_created_at` | timestamp | time | When the call started. |

Besty's caveats:

- Search matches any term (stemmed) and ranks by relevance. It has no typo tolerance or synonym expansion.
- Quotes switch the entire search to web-search semantics. Quoted phrases match exactly, every other term becomes required, and "or" between terms is honored.
- Terms containing a digit are matched as literal substrings, not stemmed words. Digit-only searches are ordered by recency rather than relevance.
- transcript_items and call_recordings have no user_id. Tenant scope routes through call_logs.user_id.
- The inner join intentionally hides orphan recordings with no call log.
- Each row is one transcript turn, not a complete transcript blob.
- Calls have no listing attribution and are unavailable under listing-scoped tokens.

#### `export_calls`

Bulk export of account calls, with recording, voicemail, and answered or initiating subuser details. `call_sid` uses `v3:` for Telnyx and `CA` for Twilio. `forwarded` means the call leg was handed to a forwarding number, not that it failed. `ai_answered` means the AI receptionist handled the call and no person picked up; it is not a missed call. `duration_seconds` is recording duration, not call duration. `targeted_subuser_ids` is post-filtered after routing eligibility and is not a routing-health denominator. Phone fields require include_pii=true and explicit fields. Calls have no listing attribution. Primary time field is created_at.

Primary time field: `created_at`. Limits: raw row cap 5000, max window days 365, default window days 90. Join keys: `call_id`, `thread_id`, `recording_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `call_id` | int |  | Besty call log id. |
| `call_sid` | string |  | Provider call id. A v3: prefix identifies Telnyx. A CA prefix identifies Twilio. |
| `direction` | string |  | Call direction: 'inbound' or 'outbound'. |
| `status` | string |  | Call leg status: 'answered', 'ai_answered', 'forwarded', 'no_answer', 'busy', or 'failed'. 'forwarded' means the leg was handed to a forwarding number, not that the call failed. 'ai_answered' means the AI receptionist handled the call and no person picked up. |
| `created_at` | timestamp | time | When the call started. |
| `ended_at` | timestamp | completion, time | When the call ended. |
| `duration_seconds` | int |  | Recording duration in seconds. Present only for recorded calls. This is not a reliable call duration. Use ended_at - created_at for call duration. |
| `recording_id` | int |  | Besty recording id linked from the call log. |
| `has_recording` | bool |  | True when the call log has a recording_id. |
| `recording_url` | string |  | Playback URL for the call recording. Opens in the Besty dashboard for a signed-in user of the account; the audio file is not publicly fetchable. |
| `summary` | string |  | AI-generated call summary. Null until summary generation finishes. |
| `has_summary` | bool |  | True when an AI-generated call summary exists. |
| `thread_id` | int |  | Besty messaging thread linked to the call. |
| `caller_country` | string |  | Country detected for the caller. |
| `caller_state` | string |  | State detected for the caller. |
| `answered_by_subuser_id` | string | assignee | UUID of the subuser who answered the call. |
| `answered_by_name` | string | assignee | Display name of the subuser who answered the call. |
| `initiated_by_subuser_id` | string | assignee | UUID of the subuser who initiated the call. |
| `initiated_by_name` | string | assignee | Display name of the subuser who initiated the call. |
| `targeted_subuser_ids` | array | assignee | Post-filter subuser UUIDs after the online and fresh-token eligibility gate. This is not the set of people who should have been rung. The intended target set is the union of voice_waterfall_levels.target_subuser_ids from the enabled voice_waterfall_configs row. Do not use this field as a routing-health denominator. |
| `has_voicemail` | bool | contact | True when a voicemail is linked to the call. |
| `voicemail_id` | string | contact | UUID of the linked voicemail. |
| `voicemail_transcript` | string | contact | Voicemail transcript. |
| `voicemail_summary` | string | contact | AI-generated voicemail summary. |
| `voicemail_is_read` | bool | contact | Whether the voicemail has been marked read. |
| `to_number` | string | contact | Number the call was placed to. |
| `from_number` | string | contact | Number the call came from. |
| `forwarded_to_number` | string | contact | Forwarding destination number, when used. |
| `voicemail_caller_number` | string | contact | Number associated with the voicemail caller. |

Besty's caveats:

- call_recordings has no user_id. Tenant scope routes through call_logs.recording_id, so a recording is reachable only through its call.
- duration_seconds is recording duration and is absent for unrecorded calls. Use ended_at - created_at for call duration.
- targeted_subuser_ids is the post-filter set after online and fresh-token routing eligibility. It is not the intended target set or a routing-health denominator. The intended target set comes from the union of voice_waterfall_levels.target_subuser_ids on the enabled voice_waterfall_configs row, over ring levels only: a level_type = 'ai' level is the AI receptionist and has no targets.
- summary is generated asynchronously and is null for recent calls.
- Calls have no listing attribution and are unavailable under listing-scoped tokens.

#### `export_checkin_form_submissions`

One row per check-in form record, joined to its template and reservation. Field names vary per template, so read field_names before values. Full values and guest_name require include_pii=true. Primary time field is submitted_at.

Primary time field: `submitted_at`. Limits: raw row cap 5000, max window days 730, default window days 365. Join keys: `record_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `record_id` | string |  | Check-in form record UUID. |
| `template_id` | string |  | Check-in form template UUID. |
| `template_name` | string |  | Template name. |
| `template_is_active` | bool |  | Whether the template is active. |
| `reservation_id` | int |  | Besty reservation id. |
| `listing_id` | int |  | Besty listing id from the record, falling back to the reservation. |
| `arrival_date` | date | time | Reservation arrival date. |
| `departure_date` | date | time | Reservation departure date. |
| `arrival_at` | timestamp | time | Reservation arrival timestamp. |
| `submitted_at` | timestamp | time | When submitted. Null means the form was created or sent but not submitted. |
| `is_submitted` | bool |  | True when submitted_at is set. |
| `field_names` | array |  | Field names defined by this template. Read this before values because names differ per template. |
| `value_count` | int |  | Number of keys in the submitted values object. |
| `party_total` | string |  | Party total when this template uses that field name. |
| `additional_people` | string |  | Additional people value when this template uses that field name. |
| `vehicle_plates` | array |  | Non-empty vehicle plate values from vehicleN_plate keys. |
| `vehicle_count` | int |  | Number of non-empty vehicle plate values. |
| `values` | jsonb |  | Full form submission. Field names vary by template and values are PII. |
| `guest_name` | string | contact | Reservation guest name. |

Besty's caveats:

- Field names vary by template. party_total, additional_people, and vehicle_plates are null or empty when templates use different names.
- values is the full submission and is PII. Templates with custom HTML can have an empty fields_schema.
- Unsubmitted forms have submitted_at = null and fall outside a submitted_at time window.
- check-in records have no user_id. Ownership is the template account, and the reservation must belong to that same account.

#### `export_checkout_sessions`

Bulk export of direct booking site checkout sessions, one row per checkout started. Answers funnel questions (started vs confirmed), abandoned checkouts by listing, average quote, upsells and discounts in carts, and traffic source (`channel`, `channel_source`). Only status='confirmed' is a paid booking; 'cancelled' and 'expired' are abandoned carts. Quote fields come from the frozen `quote_snapshot`. `channel` is NULL for untagged traffic. Primary time field is created_at.

Primary time field: `created_at`. Limits: raw row cap 5000. Join keys: `session_id`, `listing_id`, `pms_reservation_id`, `guest_account_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `session_id` | int |  | Besty internal checkout session id. |
| `listing_id` | int |  | Besty internal listing id the guest was booking. |
| `pms_listing_id` | string |  | The booking platform's id for the listing (the PMS id, whichever PMS the account uses). |
| `status` | string |  | Checkout lifecycle state: 'active' (cart open), 'authorized' (card authorized), 'confirming' (creating the PMS reservation), 'confirmed' (paid and booked), 'cancelled' (guest left or hold released), 'expired' (hold timed out), 'failed' (payment or PMS error). Only 'confirmed' is a paid booking. |
| `check_in` | date | time | Requested check-in date. |
| `check_out` | date | time | Requested check-out date. |
| `nights` | int |  | Night count from the frozen quote. |
| `currency` | string |  | ISO currency code of the quote. |
| `quote_total` | float |  | Guest-facing quote total in major currency units, from the frozen quote (accommodation, fees, taxes, upsells, less discount). The amount charged can differ by card surcharge; see display_total_cents. |
| `accommodation_total` | float |  | Accommodation subtotal in major units, before fees and taxes. |
| `average_nightly` | float |  | Average nightly rate in major units, as quoted. |
| `display_total_cents` | bigint |  | Total shown to the guest at payment time, in minor units (cents), including any card surcharge. |
| `surcharge_cents` | bigint |  | Card processing surcharge in minor units. NULL on rows quoted before surcharges existed. |
| `fee_breakdown` | jsonb |  | Array of {label, value, kind?} line items in major units: 'accommodation', 'cleaning', PMS fees, and kind='tax' lines. |
| `ota_markup` | jsonb |  | Array of {channel, markupPercent} the site displayed as the OTA comparison. Marketing copy, not a charge. |
| `upsells` | jsonb |  | Array of upsells in the cart: {category, priceCents, currency, status, selectedTime?}. NULL when the cart had none. Categories seen: 'early_checkin', 'late_checkout'. |
| `upsell_count` | int |  | Number of upsell items in the cart. 0 when none. |
| `has_upsells` | bool |  | True when the cart held at least one upsell. |
| `discount_amount` | float |  | Discount applied to the quote in major units. NULL when no discount. |
| `has_discount` | bool |  | True when a discount (coupon or loyalty) was applied to the quote. |
| `coupons` | jsonb |  | Coupon codes applied, when the quote recorded them. NULL on most discounted rows; use export_coupon_redemptions for redemption rows. |
| `pms_reservation_id` | string |  | The reservation id on the booking platform (PMS). Set once a hold or booking was created there, so it is present on cancelled and expired sessions too, not only confirmed ones. |
| `pms_hold_kind` | string |  | How the dates were held on the PMS during checkout (for example a hold reservation vs a quote). |
| `payment_provider` | string |  | Payment processor used ('stripe', 'guesty', ...). NULL on rows that never reached payment. |
| `guest_account_id` | bigint |  | Direct booking guest account id when the guest was signed in. NULL for anonymous checkouts. |
| `channel` | string |  | Marketing channel from the landing UTM: 'cpc' (paid search), 'paid_social', 'ai' (AI assistant catalog). NULL for untagged traffic, which is most rows. |
| `channel_source` | string |  | Channel source from the landing UTM: 'google', 'meta', 'fb', 'ig', 'mcp'. NULL when channel is NULL. |
| `first_touch_referrer` | string |  | HTTP referrer on the first visit of this browser, when captured. NULL on most rows. |
| `first_touch_landing_page` | string |  | Landing path on the first visit, when captured. |
| `last_touch_referrer` | string |  | HTTP referrer on the visit that reached checkout, when captured. |
| `page_referrer` | string |  | HTTP referrer of the checkout page itself. Often the site itself or a search engine. |
| `booking_mode` | string |  | 'instant' or 'request', from the site config at checkout time. |
| `site_index` | int |  | Which of the account's direct booking sites the checkout happened on (0-based). NULL on single-site accounts and older rows. |
| `failure_reason` | string |  | Error text for status='failed'. NULL otherwise. |
| `expires_at` | timestamp | time | When the hold expires or expired. |
| `confirmed_at` | timestamp | time | When payment completed and the booking was confirmed. NULL unless status is confirmed. |
| `cancelled_at` | timestamp | time | When the session was cancelled. |
| `failed_at` | timestamp | time | When the session failed. |
| `created_at` | timestamp | time | When the guest started checkout. |
| `updated_at` | timestamp | time | Last status change. |
| `quote_snapshot` | jsonb |  | Full frozen quote. Large; use the projected quote fields unless you need line items. |
| `analytics_context` | jsonb |  | Full analytics context captured at checkout (page, tenant host, first/last touch). |
| `guest_draft` | jsonb |  | Guest contact details typed during checkout (name, email, phone). |

Besty's caveats:

- Only status='confirmed' means the guest paid. 'active', 'authorized' and 'confirming' are in-flight and will move to confirmed, cancelled, expired or failed.
- pms_reservation_id is set when a hold was created on the booking platform, so it is present on most cancelled and expired rows. It does not mean the booking completed.
- quote_snapshot keys upsells, discount and coupons are optional and absent on most rows. Use has_upsells, upsell_count and has_discount rather than testing for NULL in the jsonb.
- channel and channel_source come from landing UTM tags and are NULL on most sessions. first_touch fields inside analytics_context are null on most rows, so attribution is thin.
- quote_total is the quoted amount, not a payment ledger. Refunds and PMS-side changes after booking are not reflected here.
- Empty on accounts without a direct booking site.

#### `export_config_changes`

Export configuration changes made through Besty App MCP. Ask which settings changed, who changed them, or which changes were rolled back.

Primary time field: `created_at`. Limits: raw row cap 5000, max window days 730, default window days 90. Join keys: `operation_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `operation_id` | string |  | MCP operation UUID. |
| `tool` | string |  | Besty App MCP tool name. |
| `status` | string |  | Operation status. |
| `summary` | jsonb |  | Per-tool operation summary. Shape varies by tool. |
| `actor_subuser_id` | string |  | Subuser UUID that made the change. |
| `actor_name` | string |  | Name of the subuser who made the change. Null when the actor is not a subuser. |
| `actor_type` | string |  | Who made the change: staff (Besty staff via the admin MCP), subuser (a team member on this account), ask_ai (an Ask AI or builder session), token (an access token with no person attached), static_key (the shared internal key), system (internal code). Null for changes recorded before 2026-10-07 that could not be attributed. |
| `actor_email` | string | contact | Email of the person who made the change: the staff Google login for staff, the login email for subusers. Copied at write time, so it survives the subuser being deleted. |
| `created_at` | timestamp | time | When the operation was recorded. |
| `rolled_back_at` | timestamp | time | When the operation was rolled back. |
| `is_rolled_back` | bool |  | True when rolled_back_at is set. |
| `token_id` | string |  | MCP token id. |

Besty's caveats:

- Only writes made through the Besty App MCP appear here; dashboard settings edits are not logged except the handful in export_dashboard_action_logs.
- actor_type and actor_email are null for older changes made with the shared internal key or by internal code, which were not told apart before 2026-10-07.

#### `export_coupon_redemptions`

Bulk export of direct booking coupon redemptions, one row per checkout that applied a code. `status` is 'pending' (checkout open or abandoned) or 'confirmed' (paid). Includes the coupon `code` via inner join and `checkout_session_id` to join export_checkout_sessions. Account-level; no listing attribution. Primary time field is created_at.

Primary time field: `created_at`. Limits: raw row cap 5000. Join keys: `redemption_id`, `coupon_id`, `checkout_session_id`, `guest_account_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `redemption_id` | string |  | Redemption uuid. |
| `coupon_id` | string |  | Coupon uuid. Join key to export_coupons.coupon_id. |
| `code` | string |  | Current code on the coupon row (inner join on coupon_id and user_id). |
| `code_entered` | string |  | What the guest typed. Differs from code only in case or when the coupon was renamed later. |
| `discount_type` | string |  | 'percentage' or 'flat', from the coupon row. |
| `checkout_session_id` | int |  | Checkout session that applied the code. Join key to export_checkout_sessions.session_id. NULL on rows written before session linking. |
| `guest_account_id` | int |  | Direct booking guest account id when the guest was signed in. NULL for anonymous checkouts. |
| `amount_discounted_cents` | int |  | Discount applied to that checkout, in minor units (cents). |
| `amount_discounted` | float |  | amount_discounted_cents / 100, in major units. |
| `status` | string |  | 'pending' while the checkout is open (the code is reserved against max_redemptions for a few minutes), 'confirmed' once the checkout paid. Pending rows older than the checkout hold are abandoned carts. |
| `created_at` | timestamp | time | When the code was applied at checkout. |

Besty's caveats:

- Rows with status='pending' include abandoned carts. Count paid usage with status='confirmed'.
- Inner join to direct_booking_coupons drops redemptions whose coupon was deleted.
- No listing id on the row. The listing is reachable through checkout_session_id in export_checkout_sessions.
- Empty on accounts without a direct booking site or without coupons.

#### `export_coupons`

Bulk export of direct booking site discount codes, one row per coupon, with a derived `confirmed_redemptions` count and `is_live` flag. Answers which codes are live, what they discount, and whether anyone has used them. `filter.codes` matches case-insensitively. For per-checkout detail use export_coupon_redemptions. Coupons are account-level and have no listing attribution. Primary time field is created_at.

Primary time field: `created_at`. Limits: raw row cap 5000. Join keys: `coupon_id`, `code`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `coupon_id` | string |  | Coupon uuid. |
| `code` | string |  | The code guests type at checkout. Stored uppercase. |
| `discount_type` | string |  | 'percentage' (amount is a percent off) or 'flat' (amount is a fixed sum in the site currency). |
| `amount` | float |  | Percent off when discount_type is percentage, else a fixed amount in major currency units. |
| `applies_to` | string |  | What the discount applies to. Only 'accommodation' exists today: the nightly subtotal, not fees or taxes. |
| `enabled` | bool |  | Host toggle. False means the code is rejected at checkout regardless of dates. |
| `starts_at` | timestamp | time | First moment the code is valid. NULL means no start restriction. |
| `expires_at` | timestamp | time | Last moment the code is valid. NULL means no expiry. |
| `max_redemptions` | int |  | Cap on confirmed redemptions. NULL means unlimited. |
| `confirmed_redemptions` | int |  | Count of redemptions with status 'confirmed' (paid checkouts). Pending and abandoned carts are excluded. |
| `is_live` | bool |  | True when the code would be accepted now: enabled, inside its date window, and under max_redemptions. |
| `created_at` | timestamp | time | When the host created the coupon. |
| `updated_at` | timestamp | time | Last edit. |

Besty's caveats:

- confirmed_redemptions counts status='confirmed' only. Open and abandoned carts that entered the code are 'pending' rows in export_coupon_redemptions.
- Coupons have no listing id on the row. Listing restrictions live in the coupon scope config and are not exported here, so a listing-scoped token cannot use this tool.
- Empty on accounts without a direct booking site.

#### `export_crm_contact_consents`

One row per CRM contact, consent channel, and source. A contact can be granted by one source and denied by another. Marketable means any granted and no denied. Listing scope is unsupported. Primary time field is occurred_at.

Primary time field: `occurred_at`. Limits: raw row cap 5000, max window days 1825. Join keys: `consent_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `consent_id` | string |  | CRM consent row id as a string. |
| `contact_id` | string | contact | Owning CRM contact id as a string. |
| `channel` | string |  | Consent channel: 'email' or 'sms'. |
| `source` | string |  | Source of the consent state. |
| `status` | string |  | Consent state: 'granted' or 'denied'. |
| `is_granted` | bool |  | True when status is granted. |
| `occurred_at` | timestamp | time | When the consent event occurred. |
| `updated_at` | timestamp | time | When the consent row was last updated. |
| `created_at` | timestamp | time | When the consent row was created. |
| `external_ref` | string |  | External provider reference, when present. |
| `contact_labels` | array |  | Label keys on the owning contact: vendor, staff, guest, owner_prospect. |
| `contact_source` | string |  | Owning contact source. |
| `contact_guest_id` | string | contact | Linked Besty guest id, or null. |
| `contact_display_name` | string | contact | Owning contact display name. |

Besty's caveats:

- Consent rows are empty on accounts without Guesty marketing consent sync or web opt-ins.
- One row represents one contact, channel, and source. A contact can be granted by one source and denied by another; marketable means any granted and no denied.
- occurred_at can be null for legacy rows.
- Listing scope is unsupported.

#### `export_crm_contact_events`

One row per CRM contact event. Payload keys vary by kind, and reservation_id is parsed only from numeric payload.reservationId. Listing scope is unsupported. Primary time field is occurred_at.

Primary time field: `occurred_at`. Limits: raw row cap 5000, max window days 730, default window days 365. Join keys: `event_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `event_id` | string |  | CRM contact event id as a string. |
| `contact_id` | string | contact | Owning CRM contact id as a string. |
| `kind` | string |  | Event kind: imported, created, booking_created, checkout_started, checkout_abandoned, offer_submitted, form_submission, thread_opened, meta_lead, widget_capture, call_received, instantly_reply, or consent_updated. |
| `body` | string |  | Event body, when present. |
| `occurred_at` | timestamp | time | When the event occurred. |
| `created_at` | timestamp | time | When Besty created the event. |
| `created_by_subuser_id` | string | assignee | Creating subuser UUID, or null. |
| `is_manual` | bool |  | True when a subuser created the event. |
| `reservation_id` | bigint |  | Reservation id parsed from payload.reservationId when it is a positive integer up to 18 digits. |
| `payload` | jsonb |  | Full event payload. Shape varies by event kind and may contain names or emails. |
| `contact_labels` | array |  | Label keys on the owning contact: vendor, staff, guest, owner_prospect. |
| `contact_source` | string |  | Owning contact source. |
| `contact_guest_id` | string | contact | Linked Besty guest id, or null. |
| `contact_display_name` | string | contact | Owning contact display name. |

Besty's caveats:

- Imported events, which are about 95% of rows on PMS accounts, use the backfill time in occurred_at rather than the original stay time.
- checkout_abandoned is written by a delayed job, so recent checkout_started rows may not have it yet.
- Payload keys differ by event kind. Thread and message content is in export_threads and export_messages.
- Listing scope is unsupported.

#### `export_crm_contact_methods`

One row per CRM contact method. A contact with three phone numbers produces three rows. Archived contacts are hidden by default. Listing scope is unsupported. Primary time field is created_at.

Primary time field: `created_at`. Limits: raw row cap 5000, max window days 1825. Join keys: `method_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `method_id` | string |  | CRM contact method id as a string. |
| `contact_id` | string | contact | Owning CRM contact id as a string. |
| `method_type` | string |  | Method type: 'email' or 'phone'. |
| `source` | string |  | System that supplied the method. |
| `sms_consent_at` | timestamp | time | SMS consent timestamp, when present. |
| `has_sms_consent` | bool |  | True when this method carries SMS consent. |
| `created_at` | timestamp | time | When this method was created. |
| `contact_labels` | array |  | Label keys on the owning contact: vendor, staff, guest, owner_prospect. |
| `contact_source` | string |  | Owning contact source. |
| `contact_guest_id` | string | contact | Linked Besty guest id, or null. |
| `contact_is_archived` | bool |  | True when the owning contact is archived. |
| `value` | string |  | Normalized contact method value. |
| `value_raw` | string |  | Original contact method value. |
| `contact_display_name` | string | contact | Owning contact display name. |

Besty's caveats:

- This is one row per method. Count distinct contact_id for people.
- sms_consent_at is populated only from website and manual sources.
- Archived contacts are hidden by default. Pass include_archived_contacts=true to include their methods.
- Listing scope is unsupported.

#### `export_crm_contacts`

One row per CRM contact with methods, consent status, provider identities, and linked guest lifetime metrics. Archived contacts are hidden by default. Listing scope is unsupported; filter by property through export_guests or export_reservations. Primary time field is created_at.

Primary time field: `created_at`. Limits: raw row cap 5000, max window days 1825. Join keys: `contact_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `contact_id` | string | contact | CRM contact id as a string. |
| `labels` | array |  | Label keys on the contact: 'vendor', 'staff', 'guest', 'owner_prospect'. Empty when unlabeled. |
| `source` | string |  | System that created or imported the contact. |
| `guest_id` | string | contact | Linked Besty guest id, or null when unlinked. |
| `is_linked_to_guest` | bool |  | True when this contact links to a Besty guest. |
| `is_archived` | bool |  | True when the contact is archived. |
| `archived_at` | timestamp | time | When the contact was archived. |
| `created_at` | timestamp | time | When the contact was created. |
| `updated_at` | timestamp | time | When the contact was last updated. |
| `email_count` | int | contact | Number of email methods on the contact. |
| `phone_count` | int | contact | Number of phone methods on the contact. |
| `has_email` | bool | contact | True when the contact has at least one email method. |
| `has_phone` | bool | contact | True when the contact has at least one phone method. |
| `sms_consent_at` | timestamp | time | Most recent SMS consent timestamp on any phone method. |
| `has_sms_consent` | bool |  | true when any phone method carries sms_consent_at. Set only by website forms and manual entry, never by PMS import. Email marketability is not stored on methods; see email_consent_status. |
| `email_consent_status` | string | contact | granted, denied, or NULL when no email consent record exists, which is the common case. |
| `sms_consent_status` | string |  | granted, denied, or NULL when no SMS consent record exists, which is the common case. |
| `provider_identity_count` | int |  | Number of external provider identities linked to the contact. |
| `stay_count` | int |  | Linked guest stay count, or null when unlinked. |
| `lifetime_revenue_amount` | float |  | Linked guest lifetime revenue, or null when unlinked. |
| `display_name` | string | contact | Contact display name. |
| `first_name` | string |  | Contact first name. |
| `last_name` | string |  | Contact last name. |
| `primary_email` | string | contact | First normalized email method by creation time. |
| `primary_phone` | string | contact | First normalized phone method by creation time. |

Besty's caveats:

- Archived contacts are hidden by default. Pass include_archived=true to include them.
- crm_contact_consents is empty on accounts without Guesty consent sync or web opt-ins. Email marketability is otherwise not stored.
- PMS imports mirror guests 1:1 into contacts, so counting contacts can approximate counting guests.
- Listing scope is unsupported. Filter by property through export_guests or export_reservations.

#### `export_daily_rates`

Stored daily rate grid written by the direct booking catalog sweep. It covers a 365-day horizon and is refreshed roughly every 4 hours. Prefer this over export_rates when the account has rows because it needs no live PMS call. Use export_rates for accounts with no grid rows. Filter with from_date/to_date; time_range is not supported because the data is forward-looking.

Primary time field: `date`. Limits: raw row cap 20000. Join keys: `listing_id`, `date`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `listing_id` | int |  | Besty internal listing id. |
| `date` | date | time | Night for which the rate and availability apply. |
| `nightly_rate` | float |  | Nightly asking rate in `currency` for a stay starting that night; NULL when the PMS returned no price. |
| `currency` | string |  | ISO 4217 currency for nightly_rate. |
| `available` | bool |  | Whether the PMS calendar reports the night as available. |
| `min_stay` | int |  | Minimum nights for a stay starting on this date; NULL when the PMS does not publish one. |
| `checkin_allowed` | bool |  | Whether check-in is allowed on this night. |
| `checkout_allowed` | bool |  | Whether checkout is allowed on this night. |
| `refreshed_at` | timestamp | time | When the catalog sweep last rewrote this listing's grid. |
| `is_stale` | bool |  | True when refreshed_at is older than 48 hours. |

Besty's caveats:

- Rows exist only for Besty-enabled, non-virtual listings active in the PMS when the account has a direct booking site customization row.
- Accounts without a direct booking site have no rows; use export_rates there.
- Rows are ordered date DESC, so pass from_date/to_date to avoid receiving far-future dates first.
- nightly_rate and min_stay are NULL when the PMS calendar omits them. refreshed_at is per listing; check is_stale.

#### `export_damage_waivers`

One row per damage waiver choice attached to a reservation. Amounts use major currency units, unlike stripe hold amounts. Use export_stripe_holds for the money state of a hold. Primary time field is created_at.

Primary time field: `created_at`. Limits: raw row cap 5000. Join keys: `record_id`, `reservation_id`, `listing_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `record_id` | int |  | Damage waiver record id. |
| `reservation_id` | int |  | Besty internal reservation id. |
| `listing_id` | int |  | FK to listings.id. |
| `arrival_date` | date | time | Reservation arrival date. |
| `channel` | string |  | Raw booking channel as written by the connector. |
| `type` | string |  | waiver means the guest paid a non-refundable waiver; hold means the guest chose a refundable card hold; none means declined or not applicable. |
| `amount` | int |  | Amount in major currency units. For example, 20 means 20 USD, not cents. |
| `currency` | string |  | Currency for amount. |
| `config_id` | int |  | Damage waiver configuration id. |
| `config_name` | string |  | Current damage waiver configuration name. |
| `config_waiver_cost` | int |  | Current configured waiver cost in major currency units. |
| `config_hold_amount` | int |  | Current configured hold amount in major currency units. |
| `config_enabled` | bool |  | Whether the current damage waiver configuration is enabled. |
| `stripe_payment_intent_id` | string |  | Stripe payment intent for the waiver record. |
| `created_at` | timestamp | time | When the record was created. |

Besty's caveats:

- Waiver purchases also appear in export_upsell_events with source damage_waiver. Hold rows here record the guest choice; the authorization state is in export_stripe_holds.
- Empty on accounts that do not use damage waivers. Config columns show current values, not values at purchase time.

#### `export_dashboard_action_logs`

Export the small set of dashboard actions recorded in the action log. Ask which logged dashboard settings changed and when.

Primary time field: `created_at`. Limits: raw row cap 5000, max window days 1825, default window days 365. Join keys: `action_log_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `action_log_id` | int |  | Dashboard action log id. |
| `action` | string |  | Dashboard action name. |
| `action_data` | jsonb |  | Action payload. |
| `message_id` | string |  | PMS message id. Sparse and misnamed for non-Hostaway PMSes. |
| `unanswered_messages_id` | int |  | Unanswered-messages row id. Sparse. |
| `created_at` | timestamp | time | When the action was logged. |

Besty's caveats:

- This log is sparse, only a few dashboard actions log here; no actor column exists, so who did it is unknown; empty on accounts that never touched the logged settings.

#### `export_escalation_gate_runs`

Bulk export of row-level escalation gate runs. Use aggregation for weekly gate metrics such as runs, escalations, parity, enforcement, and average latency. Primary time field is created_at.

Primary time field: `created_at`. Limits: raw row cap 10000, max window days 365, default window days 30. Join keys: `gate_run_id`, `thread_id`, `message_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `gate_run_id` | int |  | Escalation gate run id. |
| `created_at` | timestamp | time | When the gate run started. |
| `thread_id` | string |  | Besty thread id stored as text. |
| `message_id` | int |  | Besty message id scored by the gate. |
| `external_listing_id` | string |  | PMS listing id, not a Besty listing id. |
| `external_reservation_id` | string |  | PMS reservation id. |
| `gate_score` | float |  | Classifier probability that the guest turn needs a human. |
| `gate_threshold` | float |  | Score at or above which gate_confident_escalation is true. |
| `gate_confident_escalation` | bool |  | Whether the gate confidently escalated the turn. |
| `gate_model_id` | string |  | Gate model identifier. |
| `latency_ms` | int |  | Gate classifier latency in milliseconds, not end-to-end Autopilot latency. |
| `gate_error` | string |  | Gate error, when one was recorded. |
| `has_error` | bool |  | Whether the gate recorded an error. |
| `autopilot_escalation` | bool |  | Autopilot escalation decision used as the comparison ground truth. |
| `autopilot_decision` | string |  | Autopilot's own label for the turn. |
| `agrees_with_autopilot` | bool |  | Whether gate and Autopilot decisions agree. Null when either decision is null. |
| `is_holdout` | bool |  | Whether the run was in the 5% holdout control group. |
| `enforced` | bool |  | Whether the gate flipped the turn into draft mode. |
| `parity_match` | bool |  | Whether pre- and post-Autopilot payloads matched. |
| `gate_git_sha` | string |  | Git SHA for the gate implementation. |
| `guest_message` | string |  | Guest message scored by the gate. |
| `gate_text` | string |  | Text sent to the gate classifier. |
| `execution_id` | string |  | Model execution id. |

Besty's caveats:

- Rows with null user_id are unreachable because tenant ownership cannot be proven.
- Empty on accounts where the gate has not run.
- enforced is false while enforcement is off; would-have-enforced is gate_confident_escalation AND NOT is_holdout.
- parity_match is null when the check was skipped.
- latency_ms measures the gate classifier only.

#### `export_faq_suggestions`

Bulk export of AI-suggested FAQ entries for direct booking site listings, one row per suggestion. Answers whether FAQ suggestions are waiting (`is_pending`, `filter.status=['suggested']`) and what was approved or dismissed per listing. `question` and `answer` are the current text; the model's originals and the source host note text are opt-in. Primary time field is created_at.

Primary time field: `created_at`. Limits: raw row cap 5000. Join keys: `suggestion_id`, `listing_id`, `source_hostnote_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `suggestion_id` | string |  | Suggestion uuid. |
| `listing_id` | int |  | Besty internal listing id the FAQ is for. |
| `status` | string |  | 'suggested' (waiting for the host), 'approved' (published to the listing FAQ), 'dismissed' (host rejected). |
| `is_pending` | bool |  | True when status is 'suggested' and the host has not acted. |
| `question` | string |  | FAQ question as it stands now (host edits apply here). |
| `answer` | string |  | FAQ answer as it stands now (host edits apply here). |
| `relevance` | string |  | Who the FAQ helps: 'pre_booking' (a guest deciding to book), 'in_stay' (a guest already staying), 'internal' (staff only, not for the public site). |
| `sensitive` | bool |  | True when the model flagged the source as containing codes, addresses or other details that should not be public. |
| `unusable` | bool |  | True when the model could not turn the source into a public FAQ. |
| `source_suppressed` | bool |  | True when the host hid the source host note from future suggestion runs. |
| `source_hostnote_id` | string |  | Id of the host note the FAQ was drawn from. Join key to export_hostnotes. NULL when the source was not a host note. |
| `model` | string |  | Model name that generated the suggestion. |
| `generated_at` | timestamp | time | When the model produced the suggestion. |
| `approved_at` | timestamp | time | When the host approved it. NULL unless approved. |
| `approved_by_subuser_id` | string |  | Sub-user uuid who approved. NULL when the account owner approved or the row is not approved. |
| `created_at` | timestamp | time | When the suggestion row was created. |
| `updated_at` | timestamp | time | Last change. |
| `generated_question` | string |  | The model's original question before host edits. |
| `generated_answer` | string |  | The model's original answer before host edits. |
| `source_text` | string |  | The host note text the FAQ was drawn from. Can contain door codes and private instructions. |

Besty's caveats:

- Empty on accounts that have not run FAQ suggestions. The pilot account has zero rows. An empty result means the feature is unused, not that the site has no FAQs.
- 'approved' means the entry was pushed to the listing FAQ at that time. Later edits or deletions on the live FAQ are not reflected here.
- source_text is the raw host note and can contain private details. It is opt-in for that reason.

#### `export_feature_listing_scopes`

Feature-to-listing scope configuration. mode is 'all', 'individual', 'sets', 'excludes', or 'excludeSets'. config_id identifies the configured workflow, journey, or other feature object. Primary time field is created_at.

Primary time field: `created_at`. Limits: raw row cap 10000. Join keys: `scope_id`, `config_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `scope_id` | string |  | Feature listing-scope UUID. |
| `feature` | string |  | Feature key whose configured object uses this scope. |
| `config_id` | string |  | Id of the configured object this scope applies to. The feature column says which table it lives in. |
| `mode` | string |  | Scope mode: 'all' applies to every listing, 'individual' uses direct members, 'sets' uses set members, 'excludes' removes direct members, and 'excludeSets' removes set members. |
| `listing_ids` | array |  | Direct listing members that still exist on this account. |
| `listing_set_ids` | array |  | Listing-set UUIDs referenced by this scope. |
| `listing_set_names` | array |  | Names of listing sets referenced by this scope. |
| `resolved_listing_ids` | array | completion | Union of direct members and current members of referenced sets. For mode 'individual' or 'sets' these are the listings the feature applies to; for 'excludes' or 'excludeSets' these are the listings it is excluded from; empty for mode 'all'. |
| `resolved_listing_count` | int | completion | Count of the union of direct and current set members. For 'individual'/'sets' these are included listings; for 'excludes'/'excludeSets' excluded listings; zero for 'all'. |
| `created_at` | timestamp | time | When the scope was created. |
| `updated_at` | timestamp | time | When the scope was last updated. |

Besty's caveats:

- A feature with no scope row applies to all listings, so absence means all listings rather than off.
- mode semantics come from listing_scope_mode. Set membership is resolved live.
- listing_ids contain ids that still exist on the account. The export is empty for accounts that never restricted a feature.
- filter.listing_id matches scopes that name the listing directly or through a set, plus mode 'all' scopes. For exclude modes a match means the feature is excluded for that listing, so read mode before concluding the feature is on.

#### `export_gap_night_offers`

Export gap-night offers sent between reservations. Ask which guests received an offer, whether they replied, and what the offer contained.

Primary time field: `send_messages_after`. Limits: raw row cap 5000, max window days 1825, default window days 365. Join keys: `offer_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `offer_id` | int |  | Gap-night offer id. |
| `first_reservation_id` | string |  | PMS reservation id before the gap. |
| `second_reservation_id` | string |  | PMS reservation id after the gap. |
| `message_sent` | bool |  | Whether the offer message was sent. |
| `first_message` | string |  | Message sent to the first stay conversation. |
| `second_message` | string |  | Message sent to the second stay conversation. |
| `send_messages_after` | timestamp | time | When the messages became eligible to send. This is the closest thing to a creation time and the default time axis. |
| `message_sent_at` | timestamp | time | When the offer message was sent. |
| `message_send_error` | bool |  | Whether sending the offer failed. |
| `first_response` | string |  | Guest response from the first stay conversation. |
| `first_response_checked_at` | timestamp | time | When the first response was checked. |
| `second_response` | string |  | Guest response from the second stay conversation. |
| `second_response_checked_at` | timestamp | time | When the second response was checked. |
| `number_of_nights` | int |  | Number of nights in the gap. Often null. |
| `dates_offered` | array |  | Dates offered to the guest. |
| `rule_id` | string |  | Gap-night rule id. |
| `has_response` | bool |  | True when either response is present. |

Besty's caveats:

- Empty on accounts that never sent a gap-night offer, including accounts with the feature enabled; number_of_nights is often null; responses are free text captured from the guest reply; rows have no created_at, so the default window is on send_messages_after; first_response and second_response are guest free text and only return when named in fields.

#### `export_guest_duplicate_candidates`

One row per CRM contact pair and shared normalized email or phone. A pair with two shared methods produces two rows. Listing scope is unsupported. Primary time field is pair_seen_at.

Primary time field: `pair_seen_at`. Limits: raw row cap 5000, max window days 1825. Join keys: `contact_a_id`, `contact_b_id`, `shared_method_type`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `method_id_a` | string |  | Shared method id on contact A. |
| `method_id_b` | string |  | Shared method id on contact B. |
| `contact_a_id` | string |  | Contact A id. |
| `contact_b_id` | string |  | Contact B id. |
| `shared_method_type` | string |  | Shared method type: 'email' or 'phone'. |
| `contact_a_source` | string |  | Contact A source. |
| `contact_b_source` | string |  | Contact B source. |
| `contact_a_labels` | array |  | Contact A label keys. |
| `contact_b_labels` | array |  | Contact B label keys. |
| `is_cross_source` | bool |  | True when the contacts came from different sources. |
| `contact_a_guest_id` | string | contact | Contact A linked guest id, or null. |
| `contact_b_guest_id` | string | contact | Contact B linked guest id, or null. |
| `both_linked_to_guests` | bool |  | True when both contacts link to guests. |
| `guest_a_stay_count` | int |  | Contact A linked guest stay count. |
| `guest_b_stay_count` | int |  | Contact B linked guest stay count. |
| `pair_seen_at` | timestamp | time | Later creation time of the two shared methods. |
| `shared_value` | string |  | Normalized method value shared by both contacts. |
| `contact_a_display_name` | string | contact | Contact A display name. |
| `contact_b_display_name` | string | contact | Contact B display name. |

Besty's caveats:

- Pairs are found through CRM contact methods only. Overlapping guests arrays without CRM methods are not detected.
- A contact with two shared methods produces two rows. Count distinct contact pairs for people.
- Meta leads with no email or phone do not match. No merge exists yet.
- Listing scope is unsupported.

#### `export_guests`

CRM-style guest export. emails/phones/display_name are truncated to the first 10 entries to bound envelope size (some users have 4k+ email rows). Counts are surfaced alongside (*_count). PII fields require include_pii=true. first_reservation_at is derived from reservations.booking_timestamp. Primary time field is created_at.

Primary time field: `created_at`. Limits: raw row cap 5000, max window days 730, default window days 365. Join keys: `guest_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `guest_id` | string | contact | Internal guest id (bigserial → string). |
| `stay_count` | int |  | Total completed stays. |
| `lifetime_revenue_amount` | float |  | Lifetime revenue across all reservations for this guest. |
| `crm_contact_id` | int | contact | Linked CRM contact id. Null when the guest has no CRM contact. |
| `reservation_ids` | array |  | Besty internal reservation ids associated with this guest. |
| `cancelled_reservation_ids` | array |  | Besty internal reservation ids that were cancelled. |
| `email_count` | int | contact | Length of guests.emails — surfaced because some rows have 4k+ entries. |
| `phone_count` | int | contact | Length of guests.phones. |
| `display_name_count` | int | contact | Length of guests.display_name. |
| `first_reservation_at` | timestamp | time | Earliest booking_timestamp across linked reservations. |
| `last_reservation_at` | timestamp | time | Most recent booking_timestamp across linked reservations, cancelled included. |
| `first_arrival_date` | date | time | Earliest arrival_date across linked reservations. Cancelled stays are excluded. |
| `last_arrival_date` | date | time | Most recent arrival_date across linked reservations. Cancelled stays are excluded. |
| `is_repeat_guest` | bool |  | true when stay_count is 2 or more. High lifetime revenue is often a single long stay, not loyalty; check stay_count. |
| `created_at` | timestamp | time | When Besty first created the guest row. |
| `updated_at` | timestamp | time | Most recent update. |
| `emails` | array | contact | First 10 emails — full array can be huge. |
| `phones` | array | contact | First 10 phones. |
| `display_name` | array | contact | First 10 display names. |

Besty's caveats:

- emails/phones/display_name are truncated to the first 10 entries (some guest super-rows have 4k+ emails). Counts are surfaced alongside.
- PII fields require include_pii=true AND being explicitly listed in `fields`.
- first_reservation_at derived via MIN(reservations.booking_timestamp) across linked reservations.
- Top guests by lifetime_revenue_amount often have stay_count = 1: long single stays, not repeat visitors.

#### `export_guidebook_pages`

Guidebook page rows with their section metadata. Pages may apply to all listings, direct listing ids, or listing sets. HTML is opt-in because it can be large. Primary time field is created_at.

Primary time field: `created_at`. Limits: raw row cap 5000, max window days 1825. Join keys: `page_id`, `section_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `page_id` | string |  | Guidebook page UUID. |
| `title` | string |  | Page title. |
| `page_type` | string |  | 'place' for a Google Places entry, 'custom' for host-written HTML; other values are possible. |
| `section_id` | string |  | Guidebook section UUID. |
| `section_name` | string |  | Name of the guidebook section. |
| `section_order` | int |  | Display order of the guidebook section. |
| `page_order` | int |  | Display order within the section. |
| `all_listings` | bool |  | True when the page applies to every listing in the account. |
| `listing_ids` | array |  | Direct listing ids the page applies to. |
| `listing_set_ids` | array |  | Listing-set UUIDs the page applies to. |
| `place_name` | string |  | Google Places display name. |
| `google_place_id` | string |  | Google Places identifier. |
| `place_lat` | float |  | Latitude of the place. |
| `place_lng` | float |  | Longitude of the place. |
| `place_photo_url` | string |  | Photo URL for a place page. |
| `pin_style` | string |  | Map pin style for a place page. |
| `google_places_full_response` | jsonb |  | Raw Google Places response for this page. Opt-in because it is large. |
| `place_data_last_fetched_at` | timestamp | time | When Google Places data was last fetched. |
| `source_id` | string |  | External source identifier for an imported page. |
| `source_url` | string |  | Source URL imported for this page. |
| `imported_at` | timestamp | time | When the page was imported. |
| `visibility_event` | string |  | Event that controls page visibility. |
| `visibility_offset_direction` | string |  | Direction of the event visibility offset. |
| `visibility_offset_value` | int |  | Numeric event visibility offset. |
| `visibility_offset_unit` | string |  | Unit for the event visibility offset. |
| `length_of_stay_enabled` | bool |  | Whether length-of-stay visibility is enabled. |
| `length_of_stay_operator` | string |  | Length-of-stay comparison operator. |
| `length_of_stay_value` | int |  | Length-of-stay threshold. |
| `visibility_conditions` | jsonb |  | Event-based visibility condition objects. |
| `channel_names` | array |  | Booking channels for which this page is visible. |
| `all_channels` | bool |  | True when the page is visible for every booking channel. |
| `is_exclude_channels` | bool |  | When true, channel_names is an exclusion list. |
| `hide_event` | string |  | Event that hides the page. |
| `hide_offset_direction` | string |  | Direction of the hide-event offset. |
| `hide_offset_value` | int |  | Numeric hide-event offset. |
| `hide_offset_unit` | string |  | Unit for the hide-event offset. |
| `public_guide_review_state` | string |  | Public guide review state, approved or rejected. |
| `public_guide_reviewed_at` | timestamp | time | When the public guide review state was set. |
| `public_guide_reviewed_by` | int |  | User id that set the public guide review state. |
| `html_length` | int |  | Character count of the page HTML. |
| `html` | string |  | Host-authored page HTML. |
| `created_at` | timestamp | time | When the page was created. |
| `updated_at` | timestamp | time | When the page was last updated. |

Besty's caveats:

- Sections with zero pages do not appear. A listing is covered when at least one page applies to it; there is no per-listing guidebook object.
- HTML is opt-in and can be large. Accounts that do not use guidebooks have no rows.
- google_places_full_response is opt-in.

#### `export_hostnotes`

Bulk export of hostnotes with resolved scope (total_listing_ids). SQL-paginated — do NOT confuse with the besty-app list_hostnotes tool which loads everything in memory. For listing_category='all' the total_listing_ids column is null (don't inline; treat as 'every listing the host owns'). Category is free-form text — 27 suggested values come from the dashboard widget. Primary time field is created_at.

Primary time field: `created_at`. Limits: raw row cap 5000, max window days 730, default window days 365. Join keys: `hostnote_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `hostnote_id` | string |  | Hostnote UUID (char(36)). |
| `category` | string |  | Free-form category text (NOT an enum — 27 suggested values from the dashboard widget). |
| `hostnote_text` | string |  | Hostnote body. |
| `listing_category` | string |  | Scope: all \| individual \| sets. |
| `is_draft` | bool |  | Draft flag. |
| `datapoints_need_updating` | bool |  | True if the Vellum datapoint extractor hasn't yet processed this note. |
| `ai_response` | jsonb |  | Vellum classifier output: { invalid: string[], data_points: string[], upsell_items: string[] }. |
| `subuser_id` | string | assignee | Subuser that authored the hostnote (nullable). |
| `created_at` | timestamp | time | Creation timestamp. |
| `direct_listing_ids` | array |  | Listings the hostnote is directly attached to. |
| `listing_set_ids` | array |  | Listing-set ids the hostnote is attached to. |
| `total_listing_ids` | array |  | Resolved scope. For listing_category='individual' or 'sets', this is the de-duplicated listing-id union. For listing_category='all' the column is NULL — agents should treat 'all' as 'every listing the host owns' rather than inlining. |

Besty's caveats:

- category is free-form text — NOT an enum. 27 suggested values come from the dashboard widget.
- For listing_category='all', total_listing_ids is NULL. Treat 'all' as 'every listing the host owns'; do not inline.
- Does NOT use Hostnote.loadUserHostnotes (which loads everything into memory; 18k-hostnote users crash it).
- datapoints_need_updating means the extractor has not processed the latest note text; it is distinct from is_draft.

#### `export_improvement_suggestions`

Bulk export of offline owner-portal improvement suggestions. Each row is one recommendation for a listing, with its score, evidence count, and optional cross-listing theme. Hosts can use it to ask which property improvements are most urgent, but the results reflect the last offline run rather than live reviews.

Primary time field: `created_at`. Limits: raw row cap 5000. Join keys: `suggestion_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `suggestion_id` | int |  | Besty internal id for one offline owner-portal improvement suggestion. |
| `listing_id` | int |  | Besty internal listing id affected by this suggestion. NULL when the listing row is missing. |
| `listing_name` | string |  | Internal listing name from bt_listing_info. NULL when the listing row is missing. |
| `external_listing_id` | string |  | PMS-side listing id from the suggestion. It identifies the listing in the account PMS. |
| `title` | string |  | Short imperative recommendation, for example 'Add a grill'. |
| `description` | string |  | Longer explanation of what guests asked for and why the recommendation was made. |
| `category` | string |  | Free-text category assigned offline, for example amenity, upgrade, kitchen, privacy, or furniture. |
| `effort_estimate` | int |  | 1 (easy) to 5 (major project), estimated offline. Lower effort raises the score. |
| `score` | float |  | Priority score computed offline from how many guests mentioned the suggestion and how important they said it was. Higher is more urgent. Rank suggestions by this value. |
| `status` | string |  | 'active' or 'archived'. Archived rows are hidden unless filter.include_archived is true. |
| `source_count` | int |  | Number of guest quotes backing the suggestion. The rows are available in export_suggestion_evidence. |
| `theme_id` | int |  | Cross-listing theme this suggestion belongs to, returned as export_improvement_themes.theme_id. NULL when not clustered. |
| `created_at` | timestamp | time | When the offline run first created the suggestion. |
| `updated_at` | timestamp | time | When the offline run last updated the suggestion. |

Besty's caveats:

- Archived suggestions are excluded by default and appear only when filter.include_archived is true.
- Suggestions are computed offline by suggestionService.processSignalsForUser.
- The rows represent the last offline run and do not update from live reviews until another run completes.
- Category is free text, so equivalent recommendations can use different category values.
- Accounts without the owner-portal analytics feature have no rows in this export.

#### `export_improvement_themes`

Bulk export of portfolio-level offline improvement themes. Each row groups related listing suggestions into one problem statement so hosts can ask which issues affect multiple properties. Counts cannot be narrowed to a listing subset because a theme is a portfolio-level row.

Primary time field: `created_at`. Limits: raw row cap 5000. Join keys: `theme_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `theme_id` | int |  | Besty internal id for one portfolio-level offline improvement theme. |
| `title` | string |  | Portfolio-wide problem statement, for example 'Provide adequate air conditioning for summer comfort'. |
| `description` | string |  | Explanation of the portfolio-wide problem represented by the theme. |
| `relation_type` | string |  | How the member listings are related: amenity, street, geo, or portfolio. |
| `relation_label` | string |  | Label describing the relation, for example 'Amenity: Carbon monoxide detector'. Known to be wrong on some themes (label unrelated to the theme title). Show it with care and never as the theme's subject. |
| `relation_coverage` | float |  | Share of the theme's listings that share the relation, from 0 to 1. |
| `listing_count` | int |  | Number of listings with a member suggestion, stored by the offline run. |
| `suggestion_count` | int |  | Number of member suggestions in the theme, stored by the offline run. |
| `avg_effort` | float |  | Mean effort_estimate from 1 (easy) to 5 (major) across member suggestions. |
| `score` | float |  | Priority score for the theme. Higher is more urgent, so rank themes by this value. |
| `sample_evidence` | string |  | One representative guest quote picked offline. |
| `status` | string |  | 'active' or 'archived'. Archived rows are hidden unless filter.include_archived is true. |
| `created_at` | timestamp | time | When the offline run first created the theme. |
| `updated_at` | timestamp | time | When the offline run last updated the theme. |
| `suggestion_ids` | array |  | Member suggestion IDs. Pass them to export_improvement_suggestions.filter.suggestion_ids to list affected listings. |

Besty's caveats:

- listing_count and suggestion_count are stored by the offline themeService run and are not recomputed by this export.
- relation_label is wrong on some themes, for example 'Amenity: Carbon monoxide detector' on an air conditioning theme. Never present it as the theme subject.
- Accounts without the owner-portal analytics feature have no rows in this export.
- Listing-scoped tokens cannot use this tool because portfolio counts cannot be narrowed to the token listings.

#### `export_listing_knowledge_coverage`

Coverage of host-authored knowledge by listing and category. It counts active, draft, and stale-extraction notes and includes categories used by the account. No primary time field; rows are ordered by listing and category.

Limits: raw row cap 5000. Join keys: `listing_id`, `category`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `listing_id` | int |  | Besty internal listing id. |
| `is_besty_enabled` | bool |  | Whether Besty messaging is enabled for this listing. |
| `category` | string |  | Free-form category text as typed by the host, trimmed; '(uncategorized)' groups notes with no category. Not an enum. |
| `notes_total` | int |  | Total hostnotes in this category that apply to the listing. |
| `notes_active` | int |  | Non-draft notes in this category that apply to the listing. Only these reach the AI. |
| `notes_draft` | int |  | Draft notes in this category that apply to the listing. |
| `notes_needing_reindex` | int |  | Notes whose datapoints have not been re-extracted since the last edit. |
| `latest_note_at` | timestamp | time | Creation time of the newest applicable note in this category. |
| `has_coverage` | bool |  | True when at least one active note applies to the listing and category. |

Besty's caveats:

- The category set comes from categories used by this account. A category with no note ever used has no row, so absence of a row is not coverage.
- Categories are free text, so Parking and parking are different rows.
- Notes attached through listing sets use current membership. Extracted listing_datapoints are not counted.
- The relation has one row for every listing and category used by the account. Filter large accounts.

#### `export_listing_sets`

Listing sets and their current membership. Auto-managed sets are rewritten by Besty as account configuration changes. Feature scope names are internal feature keys. This account-level export has no primary time field.

Limits: raw row cap 2000. Join keys: `listing_set_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `listing_set_id` | string |  | Listing-set UUID. |
| `name` | string | contact | Host-facing listing-set name. |
| `color` | int |  | Display color hue from 0 to 359, or NULL. |
| `is_auto_managed` | bool |  | True when Besty maintains membership automatically. |
| `listing_ids` | array |  | Current members that still exist on this account. |
| `listing_count` | int |  | Count of current listing members on this account. |
| `hostnote_count` | int |  | Count of hostnotes attached to this listing set. |
| `feature_scopes` | array |  | Feature keys that reference this listing set. |
| `feature_scope_count` | int |  | Count of feature-scope rows that reference this listing set. |

Besty's caveats:

- Membership is live. Besty can rewrite auto-managed sets without a host action.
- listing_ids include members that still exist on the account.
- feature_scopes contains internal feature identifiers. Use export_feature_listing_scopes for the configuration each one references.
- Accounts without listing sets have no rows.

#### `export_listings`

Bulk export of listings LEFT JOIN bt_listing_info. bt_listing_info carries the normalised face (bedrooms, bathrooms, city, amenities, image_url) lazily filled by PMSConnection.getListingX dispatchers. Description and description_length are computed per row from the normalised description and the PMS adapter fallback, so they cannot be used in aggregation dimensions, measures, or filters. Meta Hotel Feed fields (address_street, address_postal_code, address_country_iso, default_base_price, default_currency, min_nights_default) are derived from Guesty listing_object and return NULL for non-Guesty PMSes. `is_pms_active` reads `isActiveInPms` off the normalised BestyListing envelope, so it works for every BFF PMS (NULL only when the row's listing_object lacks the field). `is_besty_enabled` + `is_pms_active` together gate whether the listing should land in a hotel feed. `direct_booking_site_url` is the canonical Besty-hosted DBS URL (`<slug>.bestystays.com/listings/<id>`); NULL for tenants without a slug mapping. `photos` (opt-in) is derived per-row from listings.listing_object via PMSConnection.getListingPhotos; loads the PMS adapter graph on first request. `parent_listing_id` is the Besty internal int of the parent listing for sub-units (NULL otherwise). To look up by PMS-side string id, use `filter.external_listing_ids`. No primary timestamp, order is by listing_id DESC.

Limits: raw row cap 5000. Join keys: `listing_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `listing_id` | int |  | Besty internal listing id. |
| `listing_url` | string |  | Canonical listing URL: https://app.getbesty.ai/listings?listingId=<listing_id>. |
| `pms` | string |  | Owning PMS string. |
| `is_besty_enabled` | bool |  | True if Besty messaging is enabled for this listing. |
| `autopilot` | bool |  | True if autopilot is enabled. |
| `is_virtual` | bool |  | True if this is a virtual sub-unit. |
| `parent_listing_id` | int |  | Parent listing id when this is a sub-unit; NULL otherwise. Resolved via self-JOIN on (user_id, pms, parent_listing_pms_id). |
| `is_ready` | bool |  | True once initial sync + embedding has completed. |
| `description_length` | int |  | Character count of description; NULL when there is none. |
| `has_listing_info` | bool |  | True when this listing has a normalized bt_listing_info row. |
| `custom_internal_name` | string |  | Host-set internal display name. |
| `timezone` | string |  | Listing timezone (IANA). |
| `listing_name` | string |  | Normalised internal listing name. |
| `listing_name_for_guest` | string |  | Guest-facing listing name. |
| `description` | string |  | Listing description text. Normalised bt_listing_info.description; when that is empty, derived per-row via PMSConnection.getListingDescription({ listing_object, pms }) from the raw PMS payload. |
| `bedrooms` | float |  | Bedrooms (PMSConnection.getListingBedrooms normalised value). |
| `bathrooms` | float |  | Bathrooms (PMSConnection.getListingBathrooms normalised value). |
| `max_guests` | int |  | Max guest occupancy for this listing (capacity). Distinct from reservations.num_guests (booking party size). |
| `amenities` | array |  | Normalised amenities array. |
| `pets_allowed` | bool |  | Are pets allowed? |
| `children_allowed` | bool |  | Are children allowed? |
| `city` | string |  | City. |
| `state` | string |  | State / region. |
| `country` | string |  | Country. |
| `unit_type` | string |  | Unit type (entire_place, private_room, etc.). |
| `direct_booking_url` | string |  | Host-supplied direct-booking URL (free text). Often unset. Prefer `direct_booking_site_url` when emitting feeds that should land on the Besty-hosted DBS. |
| `direct_booking_site_url` | string |  | Canonical per-listing URL on the tenant's Besty-hosted direct booking site (`https://<slug>.bestystays.com/listings/<title-city>-<id>`). Slug is built from `listing_name_for_guest` (fallback `listing_name`, then `custom_internal_name`) + `city`, mirroring besty-dbs/lib/slug.ts. NULL when the tenant has no DBS slug mapping OR no sluggable title/city is available (the bare-id path 404s on the live DBS). Tenant resolved from the MCP session userId. NOTE: this is a pure URL builder, not a publish gate. Before emitting to Meta, AND with `is_besty_enabled && is_pms_active && !is_virtual` to match what backend/directBookingSite/service.ts exposes publicly. |
| `image_url` | string |  | Cover image URL (the primary photo, persisted into bt_listing_info via getListingFullImage at sync time). |
| `address_street` | string |  | Street address for Meta Hotel Feed. Guesty-only today; NULL for non-Guesty PMSes. |
| `address_postal_code` | string |  | Postal code for Meta Hotel Feed. Guesty-only today; NULL for non-Guesty PMSes. |
| `address_country_iso` | string |  | ISO 3166-1 alpha-2 country code for Meta Hotel Feed. Guesty-only today; NULL for non-Guesty PMSes. |
| `default_base_price` | float |  | Default base nightly price for Meta Hotel Feed from Guesty prices.basePrice. Guesty-only today; NULL for non-Guesty PMSes. |
| `default_currency` | string |  | Default listing currency for Meta Hotel Feed. Guesty-only today; NULL for non-Guesty PMSes. |
| `min_nights_default` | int |  | Default minimum nights for Meta Hotel Feed from Guesty terms.minNights. Guesty-only today; NULL for non-Guesty PMSes. |
| `is_pms_active` | bool |  | Whether the listing is active on the PMS side, read from the normalised BestyListing `isActiveInPms` field on listings.listing_object. Works for every PMS in BASE_PMS_LIST (all BFF-style PMSes including guestyBff). NULL when the field is missing on the row (raw-payload PMSes like hostawayBff / track). Pair with `is_besty_enabled` to gate Meta hotel feed inclusion. |
| `photos` | array |  | Gallery photo URLs (de-duped per PMS adapter, uncapped). Derived per-row via PMSConnection.getListingPhotos({ listing_object, pms }) — the PMS-agnostic dispatcher. Falls back to [image_url] when the PMS adapter is missing or errors. Opt-in: loads the PMS adapter graph on first request. |
| `_normalized_description` | string |  | INTERNAL — normalised bt_listing_info.description before the PMS fallback. Dependency of `description`; use `description` instead. |
| `_raw_listing_object` | jsonb |  | INTERNAL — raw PMS payload jsonb. Surface is PMS-specific and unstable; do not consume directly. Exists as a dependency for derived fields (e.g. `photos`). Prefer normalised fields like `photos`, `description`, `amenities`, `bedrooms` instead. |
| `lat` | float |  | Latitude. |
| `lon` | float |  | Longitude. |

Besty's caveats:

- bt_listing_info is lazily filled by PMSConnection.getListingX dispatchers. Description and description_length are computed per row from bt_listing_info.description and the PMS adapter fallback. They cannot be used in aggregation dimensions, measures, or filters.
- Meta Hotel Feed scalar fields are Guesty-only today. Non-Guesty PMS rows return NULL for address_street, address_postal_code, address_country_iso, default_base_price, default_currency, and min_nights_default.
- `direct_booking_site_url` returns NULL for any tenant without a slug entry in backend/directBookingSite/dbsHosts.ts (2132 = oceancity today). Mirror the besty-dbs `SLUG_HOSTS` map when adding entries.
- Gallery `photos` is opt-in and derived per-row from listings.listing_object via PMSConnection.getListingPhotos. Photos are not persisted in bt_listing_info; only the cover `image_url` is.
- `parent_listing_id` is LEFT-JOINed via self-JOIN — NULL when parent_listing_pms_id is null OR the parent row is missing.
- No primary timestamp, order is by listing_id DESC.
- is_ready, is_besty_enabled, and the bt_listing_info join describe different listing subsets. A listing can be synced but not ready, enabled without normalized info, or have normalized info while disabled.

#### `export_live_calendar`

Live availability + nightly rates for up to 20 listings over a date range. Calls PMSConnection.getCalendar per listing when the requested window is within the PMS-specific cap; falls back to bt_calendar_cache + reservations otherwise. Read-only from Besty's perspective.

Join keys: `listing_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `listing_id` | int |  | Besty internal listing id. |
| `pms` | string |  | Owning PMS string. |
| `source` | string |  | How this listing's days were resolved: 'live_pms' (called PMSConnection.getCalendar) or 'cache' (read from bt_calendar_cache + reservations). |
| `rates_supported` | bool |  | True when the PMS surfaces nightly rates in its calendar response AND source = live_pms. Always false on cache fallback. |
| `days` | jsonb |  | Array of { date, available, price?, currency?, minimumStay?, maximumStay? } per BestyCalendarDay. `price` and `currency` appear only when source='live_pms' and the PMS supports rates. |
| `warnings` | jsonb |  | Per-listing warnings (e.g. LIVE_RANGE_HARD_CAP_EXCEEDED, PMS_RETURNED_EMPTY_FELL_BACK_TO_CACHE). |

Besty's caveats:

- Live PMS fetches use PMSConnection.getCalendar. Per-PMS window caps in backend/pms/calendarCostModel.ts. Beyond the hard cap, falls back to cache+reservations with a LIVE_RANGE_HARD_CAP_EXCEEDED warning.
- Rates are surfaced only when source='live_pms' AND the PMS supports rates (ratesIncluded != 'never'). Cache fallback never carries rates today.
- Cache coverage is sparse because the cacheGetCalendar worker is offline. source=cache may rely largely on reservations alone for unwarmed (listing, date) combinations. Warning CALENDAR_CACHE_LOW_COVERAGE surfaces when cache rows cover <30% of the listing-day grid.
- PMS API failures degrade to cache with PMS_RETURNED_EMPTY_FELL_BACK_TO_CACHE warning (never blocks the caller).
- Max 20 listings per call; range cap is per-PMS (cloudbeds = 30 days; streamline/beds24 = 180; most BFFs = 365-730).

#### `export_loyalty_subscriptions`

Bulk export of direct booking loyalty program subscriptions (stripe_subscriptions where feature='direct_booking_loyalty'), one row per guest subscription attempt. Answers whether the loyalty program is working and why signups fail: `status` includes Besty's 'pending_checkout' and 'failed' plus Stripe states. `program_name` is joined from the loyalty program. `customer_email` requires include_pii; Stripe ids are opt-in. Account-level; no listing attribution. Primary time field is created_at.

Primary time field: `created_at`. Limits: raw row cap 5000. Join keys: `subscription_id`, `program_id`, `guest_account_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `subscription_id` | bigint |  | Besty internal subscription row id. |
| `status` | string |  | 'pending_checkout' (guest opened Stripe Checkout, has not paid), 'failed' (the Checkout session expired unpaid, or Stripe refused to create it; this is an abandoned signup, not a declined card), then Stripe states: 'active', 'trialing', 'past_due', 'canceled', 'unpaid', 'incomplete', 'incomplete_expired', 'paused'. Only 'active' and 'trialing' are paying members. |
| `is_active` | bool |  | True when status is 'active' or 'trialing'. |
| `program_id` | bigint |  | Loyalty program id from metadata.programId. Join key to direct_booking_loyalty_programs. NULL on rows without it. |
| `program_name` | string |  | Program name (LEFT JOIN on program_id and tenant). NULL when the program was deleted or metadata lacks programId. |
| `program_enabled` | bool |  | Whether the program is currently switched on. NULL when the program row is missing. |
| `guest_account_id` | bigint |  | Direct booking guest account id from metadata.guestAccountId. NULL when absent. |
| `cancel_at_period_end` | bool |  | True when the guest asked to cancel and the subscription ends at current_period_end. |
| `canceled_at` | timestamp | time | When cancellation was requested. |
| `ended_at` | timestamp | completion, time | When the subscription stopped. |
| `current_period_start` | timestamp | time | Start of the current billing period. |
| `current_period_end` | timestamp | time | End of the current billing period (next renewal). |
| `trial_start` | timestamp | time | Trial start. NULL when the plan has no trial. |
| `trial_end` | timestamp | time | Trial end. NULL when the plan has no trial. |
| `last_event_at` | timestamp | time | Time of the last Stripe webhook that touched this row. |
| `created_at` | timestamp | time | When the guest started signing up. |
| `updated_at` | timestamp | time | Last change. |
| `metadata` | jsonb |  | Checkout metadata as written: {programId, guestAccountId, ...}. |
| `stripe_subscription_id` | string |  | Stripe subscription id (sub_...). NULL until checkout completes. |
| `stripe_customer_id` | string |  | Stripe customer id (cus_...). |
| `connected_account_id` | string |  | The host's Stripe connected account (acct_...) the subscription bills through. |
| `latest_invoice_id` | string |  | Latest Stripe invoice id. |
| `customer_email` | string | contact | Guest email on the Stripe customer. |

Besty's caveats:

- Rows are attempts, not members. 'pending_checkout' rows are guests who opened checkout and left; 'failed' rows never paid. Count members with is_active.
- 'failed' is written when the Stripe Checkout session expires unpaid (guest opened it and left) or when Stripe refused to create the session (host Stripe account not ready). It is not a card decline. There is no reason column; a run of failed rows usually means guests are dropping out of checkout or the host's Stripe account is not connected.
- Status is updated by Stripe webhooks. If webhooks lag, status and current_period_end are stale until the next event.
- Retrying a failed subscription is a Stripe action. There is no Besty endpoint for it.
- Empty on accounts without a loyalty program.

#### `export_message_reports`

Bulk export of row-level team reports on incorrect AI messages. Search covers report notes and manual steps. Manual steps and notes are free text, not classified. Primary time field is created_at.

Primary time field: `created_at`. Limits: raw row cap 5000, max window days 730, default window days 365. Join keys: `report_id`, `message_id`, `thread_id`, `reservation_id`, `listing_id`, `reporter_subuser_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `report_id` | int |  | Message report id. |
| `created_at` | timestamp | time | When the team member filed the report. |
| `message_id` | int |  | Reported Besty message id. |
| `thread_id` | int |  | Thread containing the reported message. |
| `thread_url` | string |  | Canonical thread URL: https://app.getbesty.ai/message-dashboard?id=1&threadId=<thread_id>. |
| `reservation_id` | int |  | Besty reservation linked to the thread. |
| `external_reservation_id` | string |  | PMS reservation id linked to the thread. |
| `listing_id` | int |  | Besty listing linked to the reservation. |
| `reporter_subuser_id` | string |  | UUID of the team member who filed the report. |
| `reporter_name` | string |  | Name of the team member who filed the report. |
| `report_type` | string |  | Report kind: 'escalation_response' or 'proactive_send'; null on older reports. |
| `knowledge_source` | string |  | Knowledge source selected in the report modal. |
| `manual_steps` | string |  | Free-text manual steps recorded by the reporter. |
| `proactive_reason` | string |  | Reason recorded for a proactive-send report. |
| `did_teach` | string |  | Whether the report taught Besty: 'taught' or 'not_taught'. |
| `notes` | string |  | Free-text notes written by the reporter. |
| `linear_issue_id` | string |  | Linked Linear issue id, when present. |
| `linear_issue_url` | string |  | Linked Linear issue URL, when present. |
| `has_linear_issue` | bool |  | Whether a Linear issue link is present. |
| `options_raw` | jsonb |  | Full report options payload. |
| `message_body` | string |  | Body of the reported message. |

Besty's caveats:

- manual_steps and notes are free text without theme classification.
- options is null on reports created before the modal added it, so report_type may be null.
- Linear issue links are rarely set (0 of 1087 reports on the pilot account).
- Reports whose message was deleted are excluded by the inner message join.

#### `export_messages`

Bulk export of bt_messages. Owner is resolved via bt_threads.user_id (FROM expression JOINs). `sender_type` is derived per row from (is_incoming, event_type, subuser_id) — matches live inbox semantics, not the PDF-export helper. event jsonb is surfaced shallowly: event_type, event_subtype, automation_id. Default filter excludes is_hidden_because_processing=true; pass filter.include_hidden=true to include. Primary time field is created_at.

Primary time field: `created_at`. Limits: raw row cap 5000, max window days 31, default window days 30. Join keys: `message_id`, `thread_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `message_id` | int |  | bt_messages primary key. |
| `thread_id` | int |  | FK to bt_threads.id. |
| `thread_url` | string |  | Canonical thread URL: https://app.getbesty.ai/message-dashboard?id=1&threadId=<thread_id>. |
| `is_incoming` | bool |  | True if from guest (vs host/automation). |
| `body` | string |  | Message body as rendered. |
| `body_raw` | string |  | Original PMS payload before normalisation. |
| `message_subject` | string |  | Subject (email channel only). |
| `subuser_id` | string | assignee | Subuser that authored an outbound message (null for guest/automation). |
| `event_type` | string |  | Top-level event marker — 'automated_message', 'sentByBesty', null for plain host/guest messages. |
| `event_subtype` | string |  | Sub-classification — e.g. 'workflow' / 'journey' / 'sop'. |
| `automation_id` | string |  | For automated_message rows, the originating automation/SOP/journey id. |
| `event_raw` | jsonb |  | Full event jsonb payload (variable shape). |
| `created_at` | timestamp | time | When the message hit Besty. |
| `sender_type` | string |  | Canonical sender role ('guest' \| 'host' \| 'host_external' \| 'autopilot' \| 'automated'). Derived client-side from (is_incoming, event_type, event_subtype, subuser_id) — matches the live inbox semantics, not the PDF-export getMessageSenderLabel helper. host_external: sent outside Besty, mostly synced from the PMS (event_subtype 'pms'): typed by the team in the PMS or sent by the PMS's own automated messages; the data cannot tell which. automated includes upsell offers and workflow messages (event_subtype workflow_message), which are not autopilot replies. |

Besty's caveats:

- No user_id on bt_messages — ownership chains through bt_threads.user_id (FROM expression JOINs).
- sender_type matches the live inbox semantics, NOT the PDF-export getMessageSenderLabel helper.
- Default filter excludes is_hidden_because_processing=true. Pass filter.include_hidden=true to include.

#### `export_ops_automations`

Bulk export of task automations, one row per rule, with its trigger, listing coverage, templates, and how many tasks it has created. `listing_scope` says how to read coverage: 'all' covers every listing, 'specific' lists them in scoped_listing_ids, 'sets' resolves through listing sets at run time. filter.listing_ids returns rules that name a listing directly or cover all listings. To find listings with no automation, export_listings and subtract. Automations are account-level configuration and are unavailable under listing-scoped tokens. Primary time field is created_at.

Primary time field: `created_at`. Limits: raw row cap 5000. Join keys: `automation_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `automation_id` | string |  | Automation UUID. |
| `name` | string | contact | Automation name as shown in the dashboard. |
| `is_enabled` | bool |  | True when the rule is on and creating tasks. Disabled rules keep their past tasks. |
| `trigger_type` | string |  | What fires the rule: 'reservation' (relative to a check-in or check-out) \| 'occupancy' (during a stay) \| 'vacancy' (while empty) \| 'repeating' (calendar schedule). |
| `listing_scope` | string |  | Which properties the rule covers: 'all' (every listing) \| 'specific' (the listings in scoped_listing_ids) \| 'sets' (members of the listing sets in scoped_listing_set_ids) \| 'none' (not tied to a property). |
| `scoped_listing_ids` | array |  | Besty listing ids the rule names directly. Only meaningful when listing_scope is 'specific'. Empty for 'all', 'sets', and 'none'. |
| `scoped_listing_count` | int |  | Number of listings named directly. 0 unless listing_scope is 'specific'. |
| `scoped_listing_set_ids` | array |  | Listing set UUIDs the rule covers. Only meaningful when listing_scope is 'sets'. |
| `template_ids` | array |  | Task template UUIDs the rule creates tasks from, in order. |
| `template_titles` | array |  | Titles of the task templates the rule creates tasks from, in the same order as template_ids. |
| `lookahead_days` | int |  | How many days ahead the rule pre-creates tasks. New automations default to 90. Older rows may hold 60, the column default. |
| `scheduling` | jsonb |  | Timing rule. For reservation triggers: relativeTo (checkin, checkout, ...), offsetDays, offsetDirection. For occupancy and vacancy: mode and intervalDays or onDay. For repeating: intervalValue, intervalUnit, startDate. |
| `conditions` | jsonb |  | Extra gates such as stay length or stay type. Empty object when unconditional. Opt-in. |
| `tasks_created` | int |  | Live tasks this rule has created, all statuses, excluding soft-deleted tasks. |
| `tasks_completed` | int |  | Live tasks this rule created that are done. |
| `tasks_deleted` | int |  | Tasks this rule created that were later soft-deleted, for example when a reservation was cancelled. |
| `last_task_created_at` | timestamp | time | When the rule most recently created a task. Null when it has never fired. |
| `created_at` | timestamp | time | When the automation was created. |
| `updated_at` | timestamp | time | Last edit to the rule. |

Besty's caveats:

- Coverage for listing_scope 'sets' is resolved through listing set membership at run time. Only the set ids are exposed here, so per-listing coverage for those rules needs the set contents.
- filter.listing_ids matches rules that name the listing directly or have listing_scope 'all'. It cannot see through listing sets, so rules with listing_scope 'sets' never match.
- tasks_created excludes soft-deleted tasks. Automations delete their own tasks when the triggering reservation is cancelled, so tasks_deleted is not a sign of manual cleanup.
- Task counts are lifetime totals, not bounded by time_range. time_range applies to the automation row timestamps only.
- Disabled rules stop creating tasks but keep every task already created. is_enabled=false with tasks_created > 0 is normal.
- Empty on accounts that create tasks by hand or through a PMS integration only.

#### `export_ops_issues`

Bulk export of ops issues, one row per issue. An issue is a problem reported at one or more listings, filed from an issue template. Columns cover status (open \| approved \| resolved), priority, the template, the reporter, the listings (listing_ids array), the stay, the task the reporter was working (source_task_id), the tasks meant to fix it (linked_task_ids array), and who resolved it. has_linked_task=false finds issues nobody has been given yet. Join linked_task_ids or source_task_id to export_ops_tasks.ops_task_id for task detail. The reporter's answers to the template's questions, attachments, comments, and the change history are not in this export. Deleted issues are excluded by default (filter.include_deleted=true to include). Primary time field is created_at.

Primary time field: `created_at`. Limits: raw row cap 5000. Join keys: `issue_id`, `issue_template_id`, `reservation_id`, `source_task_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `issue_id` | string |  | Ops issue UUID. |
| `issue_dashboard_url` | string |  | Besty dashboard URL for the issue. |
| `title` | string |  | Issue title. Copied from the issue template when the issue was filed, and not editable. |
| `description` | string |  | The reporter's notes. |
| `status` | string |  | open \| approved \| resolved. 'approved' only appears on accounts that turned on issue approval. An issue resolves on its own when every linked task is done, and reopens when a task is linked or a linked task is reopened. |
| `priority` | int |  | Priority 1 (low) to 5 (high). Nullable. |
| `issue_template_id` | string |  | Issue template the issue was filed from. |
| `issue_template_title` | string |  | The template's current title. Differs from `title` when the template was renamed after filing. |
| `reporter_subuser_id` | string |  | Team member who reported the issue. Null when the account owner reported it. |
| `reporter_name` | string |  | Display name of the reporter. Null when reporter_subuser_id is null. |
| `listing_ids` | array |  | Besty listing ids the issue is filed against. An issue has at least one. |
| `listing_count` | int |  | Number of listings on the issue. |
| `reservation_id` | int |  | FK to reservations.id for the stay the issue is about. Nullable. |
| `source_task_id` | string |  | Ops task the reporter was working when they filed the issue. Nullable. |
| `linked_task_ids` | array |  | Ops tasks meant to fix the issue, oldest link first. Null when no task is linked. |
| `linked_task_count` | int |  | Number of linked tasks. |
| `has_linked_task` | bool |  | True when at least one task is linked. False means nobody has been given the work yet. |
| `resolved_at` | timestamp | completion, time | When the issue was last resolved. Null unless status is resolved. |
| `resolved_by_subuser_id` | string | completion | Team member who resolved the issue by hand. Null when it resolved on its own because its tasks were done, and when the account owner resolved it. |
| `resolved_by_name` | string | completion | Display name of resolved_by_subuser_id. |
| `created_at` | timestamp | time | When the issue was reported. |
| `updated_at` | timestamp | time | Most recent change. |
| `deleted_at` | timestamp | time | Soft-delete timestamp. Null on a live issue. |

Besty's caveats:

- Row grain is one issue. listing_ids and linked_task_ids are arrays built with correlated subqueries, so an issue on three listings is still one row.
- Under a listing-limited connection an issue is included when ANY of its listings is allowed, the same rule the app applies to a team member limited to some listings. listing_ids, linked_task_ids, and source_task_id on such a row can therefore name listings and tasks outside the allowed set. Only the ids are exposed.
- title is copied from the template when the issue is filed and never changes. issue_template_title is the current template title, and stays readable after the template is deleted.
- linked_task_ids, linked_task_count, and has_linked_task count live tasks only. A link to a deleted task is ignored, as it is in the app.
- status mostly follows the linked tasks: all linked tasks done resolves the issue, and linking a task or reopening a linked one sets it back to open. resolved_by_subuser_id is set only when a team member resolved the issue by hand. Null means it resolved on its own or the account owner resolved it. 'approved' exists only on accounts with issue approval turned on.
- resolved_at and resolved_by_subuser_id are cleared when an issue reopens, so they describe the latest resolution only. Earlier resolutions are in the issue history, which this export does not include.
- reporter_subuser_id is null when the account owner filed the issue, and also when the reporting team member was later deleted.
- Not exported: the reporter's answers to the template's questions (ops_issue_requirement_items), attachments, comments, and the per-issue history.
- Default filter excludes soft-deleted issues (deleted_at IS NULL). Pass filter.include_deleted=true to include them.
- No default time window. An unfiltered call returns the newest issues up to the row cap.

#### `export_ops_requirement_items`

Bulk export of checklist items on operations tasks, one row per item. `is_filled` applies the same per-type rule the app uses before allowing completion. `has_evidence` also counts an attachment_url, which is where most photo evidence lives, so use it for photo questions. Unfilled items on a task with task_status 'done' were skipped. Group by task_template_id or type for fill rates. Items on soft-deleted tasks are excluded by default (filter.include_deleted_tasks=true to include). Listing scope follows the task. Primary time field is created_at.

Primary time field: `created_at`. Limits: raw row cap 5000. Join keys: `requirement_item_id`, `task_id`, `listing_id`, `task_template_id`, `parent_requirement_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `requirement_item_id` | int |  | Checklist item id. |
| `task_id` | string |  | Operations task UUID the item belongs to. |
| `task_dashboard_url` | string |  | Besty dashboard URL for the task. |
| `task_title` | string |  | Current title of the task. |
| `task_status` | string |  | Task status: 'todo' \| 'in_progress' \| 'done'. Unfilled items on a 'done' task were skipped. |
| `task_completed_at` | timestamp | completion, time | When the task was completed. Null while the task is open. |
| `task_template_id` | string |  | Template the task was created from. Group by this to compare templates. Null for ad hoc tasks. |
| `listing_id` | int |  | Besty listing id of the task. Null when the task is not tied to a property. |
| `type` | string |  | Item kind: 'todo_list' (checkbox) \| 'checkbox' \| 'radio_button' \| 'input' \| 'textarea' \| 'number' \| 'date_picker' \| 'multi_select' \| 'media' \| 'photo'. |
| `label` | string |  | Item label as shown to the team member. Null when the item has no label. |
| `category_name` | string |  | Checklist section the item sits under. Null for uncategorized items. |
| `is_required` | bool |  | True when the app blocks task completion until this item is filled. |
| `is_filled` | bool |  | True when `value` counts as filled under the per-type rule the app uses to allow completion: checkboxes and radios need a truthy value, text needs non-blank text, number needs a non-negative integer (a numeric 0 counts as empty, the string "0" as filled, matching the app), media/photo/multi_select need a non-empty array. |
| `has_attachment` | bool |  | True when attachment_url is set. Photo and media evidence often lives here rather than in value. |
| `has_evidence` | bool |  | True when the item is filled or has an attachment. Use this, not is_filled, when asking whether a photo was actually taken. |
| `parent_requirement_id` | int |  | Parent item id for nested sub-items. Null for top-level items. |
| `value` | jsonb |  | Raw stored value, wrapped as { value: ... }. Opt-in. |
| `options` | jsonb |  | Raw item configuration (label, choices, placeholder). Opt-in. |
| `attachment_url` | string |  | URL of the uploaded evidence. Opt-in. |
| `created_at` | timestamp | time | When the item was added to the task. |
| `updated_at` | timestamp | time | Last change to the item, including fills. |

Besty's caveats:

- ops_requirement_items has no user_id. Tenant scope routes through ops_tasks.user_id.
- is_filled looks only at value. Photo and media items are often evidenced through attachment_url with an empty value, so is_filled undercounts them. has_evidence includes attachments.
- A skipped item is an unfilled item on a task with task_status 'done'. Unfilled items on open tasks are pending, not skipped.
- Per-assignee skip rates are not available from this export. Items belong to tasks, and tasks may have several assignees.
- Items are copied onto each task when it is created, so counts scale with task volume. Compare fill rates, not raw counts, across templates.
- Items on soft-deleted tasks are excluded by default. Pass filter.include_deleted_tasks=true to include them.

#### `export_ops_task_durations`

Bulk export of expected task durations, one row per task template and listing pair: `expected_minutes` is the cached mean labor (timer minutes × crew size) of past timer-tracked completions, `sample_size` says how many, and `last_actual_minutes` is the timer on the most recently completed task for that pair. `last_minus_expected_minutes` compares the labor on that task with the mean and is positive when it ran long (filter.ran_long=true). Pairs with no usable timed completion have no row. Primary time field is updated_at.

Primary time field: `updated_at`. Limits: raw row cap 5000. Join keys: `task_template_id`, `listing_id`, `last_task_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `duration_cache_id` | string |  | Cache row UUID. |
| `task_template_id` | string |  | Task template the expectation is for. |
| `template_title` | string |  | Title of the task template. |
| `department` | string |  | Department the template belongs to (Cleaning, Maintenance, ...). Null when the department row is gone. |
| `listing_id` | int |  | Besty listing id the expectation is for. Expectations are per template and listing. |
| `expected_minutes` | float |  | Mean labor minutes (timer minutes × crew size) across the completed tasks that fed the cache. This is the expected duration for one person working alone. |
| `stddev_minutes` | float |  | Standard deviation of the labor minutes behind expected_minutes. 0 when sample_size is 1. |
| `sample_size` | int |  | Number of completed timed tasks behind the mean. Treat small samples as weak evidence. |
| `mean_crew_size` | float |  | Average crew size behind expected_minutes. Null until the pair is recomputed in labor units. |
| `template_estimated_minutes` | int |  | Duration the host typed on the template, in labor minutes. Independent of the observed mean and null when never set. |
| `last_task_id` | string |  | Most recently completed task for this template and listing. Null when none is completed. |
| `last_actual_minutes` | float |  | Timer minutes on the most recently completed task. 0 when the task was completed without running the timer. |
| `last_crew_size` | int |  | Crew that completed the most recent task. Null when nobody was assigned at completion, and on tasks completed before the crew was recorded. |
| `last_completed_at` | timestamp | completion, time | When the most recently completed task finished. |
| `last_minus_expected_minutes` | float |  | Labor on the most recent task (last_actual_minutes × last_crew_size, crew 1 when unknown) minus expected_minutes. Positive means the latest task ran long. |
| `updated_at` | timestamp | time | When the cache row was last recomputed. |

Besty's caveats:

- ops_task_duration_cache has no user_id. Tenant scope routes through ops_task_templates.user_id.
- A row exists only where at least one completion passed the sample rule: a timer of 5 min to 8 h that is not over 3x the plan, or a time someone confirmed or edited, up to 24 h. Templates or listings with no such history are absent, not zero.
- expected_minutes is labor: timer minutes times the crew that completed each task. It is recomputed when tasks complete and when a tracked time is edited or confirmed. Rows with a null mean_crew_size were computed from timer minutes alone and convert on their next recompute.
- last_minus_expected_minutes and ran_long count a task with no recorded crew (last_crew_size null: nobody was assigned at completion, or it predates the crew snapshot) as a crew of 1. The cache recompute uses the current assignee count of the task instead, so a legacy task worked by a real crew reads low here. The backfill does not change this (it recomputes the cache, not the crew stored on the task); the residual is right again once a task completed with a recorded crew becomes the latest.
- template_estimated_minutes is what the host typed on the template. It can disagree with the observed mean and is null when never set.
- last_actual_minutes is 0 when the latest task was completed without the timer. That row still counts as completed.
- Empty on accounts whose team does not use task timers.

#### `export_ops_task_history`

Bulk export of the operations task audit log, one row per event, oldest first within a task when ordered by created_at. `action` names the event and `field`, `old_value`, `new_value` describe 'field_updated' events. `actor_subuser_id` is who made the change and `target_subuser_id` is who an assignment or claim event is about. Events on soft-deleted tasks are excluded by default (filter.include_deleted_tasks=true to include). Listing scope follows the task. Primary time field is created_at.

Primary time field: `created_at`. Limits: raw row cap 5000. Join keys: `history_id`, `task_id`, `listing_id`, `actor_subuser_id`, `target_subuser_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `history_id` | int |  | Audit event id. Increases in write order. |
| `task_id` | string |  | Operations task UUID the event belongs to. |
| `task_dashboard_url` | string |  | Besty dashboard URL for the task. |
| `task_title` | string |  | Current title of the task. |
| `listing_id` | int |  | Besty listing id of the task. Null when the task is not tied to a property. |
| `created_at` | timestamp | time | When the event happened. |
| `actor_subuser_id` | string |  | Team member who made the change. Null for system, automation, and host-account actions. |
| `actor_name` | string |  | Display name of the acting team member. Null when actor_subuser_id is null. |
| `action` | string |  | Event kind, for example 'task_created', 'field_updated', 'user_assigned', 'user_unassigned', 'comment_added', 'attachment_added', 'requirement_added', 'requirement_updated', 'requirement_deleted', 'timer_paused', 'task_deleted', 'task_reopened', 'claim_claimed'. |
| `field` | string |  | Task field that changed, for 'field_updated' events: 'status', 'dueAt', 'title', 'description', 'priority', 'department', 'estimatedDurationMinutes'. Null for other actions. |
| `old_value` | string |  | Previous value of `field`, as text. Null when the action is not a field update or the value was null. |
| `new_value` | string |  | New value of `field`, as text. Null when the action is not a field update or the value was null. |
| `target_subuser_id` | string |  | Team member the event is about, for assignment and claim events. This is the person assigned, not the actor. |
| `requirement_label` | string |  | Checklist item label for requirement_* events. Null otherwise. |
| `reason` | string |  | Free-text reason attached to the event, when the writer recorded one. Sparse. |
| `attachment_link` | string |  | URL of the attachment for attachment_* events. Sparse. |
| `change` | jsonb |  | Raw event payload. Use when a key is not projected as a column. |

Besty's caveats:

- ops_task_history has no user_id. Tenant scope routes through ops_tasks.user_id.
- actor_subuser_id is null for changes made by automations, the system, or the host account itself. Null does not mean unknown, it means no team member acted.
- old_value and new_value are text casts of JSON values. Timestamps such as dueAt appear in whatever format the writer stored.
- reason and attachment_link are populated on a small minority of events.
- Checklist check-offs (a team member filling a requirement value) are not written to history. Only requirement_added, requirement_updated (structural edits) and requirement_deleted appear. Use export_ops_requirement_items for fill state.
- Events on soft-deleted tasks are excluded by default. Pass filter.include_deleted_tasks=true to include them.
- History is append-only and never edited. Rows exist from when history logging was introduced, so old tasks may have no task_created event.

#### `export_ops_task_line_items`

Bulk export of labor and supply line items on operations tasks, one row per line item. `amount` is the line total: supplies are fixed_amount * quantity, per-project labor is fixed_amount, hourly labor is hourly_rate * hours on the task timer. `payee_subuser_id` is sparse, so per-person cost is only answerable for rows that carry one. `approval_status` is the cost approval state (pending, approved, or null when never gated); filter.approval_status takes pending, approved, or none. `bill_to_owner` marks pass-through costs on the owner statement. Owner statements: filter.owner_statement_view matches the tabs of the Ops Owner statements page. `not_synced` returns every bill_to_owner line of done tasks that still have an unsynced bill_to_owner line. `synced` returns the bill_to_owner lines of tasks whose bill_to_owner lines are all synced. Count distinct task_id for the tab counts. The Not synced tab of the page can also list tasks that only wait on a PMS takedown and have no bill_to_owner lines left. This export cannot return those, so present the not_synced count as at least that many. filter.pms_synced filters single lines by pms_synced_at. Line items on soft-deleted tasks are excluded by default (filter.include_deleted_tasks=true to include). Listing scope follows the parent task. Primary time field is created_at.

Primary time field: `created_at`. Limits: raw row cap 5000. Join keys: `line_item_id`, `task_id`, `listing_id`, `payee_subuser_id`, `task_template_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `line_item_id` | string |  | Line item UUID. |
| `task_id` | string |  | Parent operations task UUID. |
| `task_dashboard_url` | string |  | Besty dashboard URL for the task. |
| `task_title` | string |  | Title of the parent task. |
| `task_status` | string |  | Parent task status: 'todo' \| 'in_progress' \| 'done'. |
| `task_completed_at` | timestamp | completion, time | When the parent task was completed. Null while the task is open. |
| `task_template_id` | string |  | Template the parent task was created from. Null for ad hoc tasks. |
| `listing_id` | int |  | Besty listing id of the parent task. Null when the task is not tied to a property. |
| `category` | string |  | 'labor' (paid to a person) or 'supplies' (a purchased item). |
| `name` | string | contact | Line item label as shown on the task. |
| `rate_type` | string |  | Labor pricing basis: 'per_project' \| 'hourly' \| 'default_per_project' \| 'default_hourly' \| 'default'. 'default' means the payee rate had not yet been resolved. Null on supplies. |
| `hourly_rate` | float |  | Hourly labor rate. Set only for hourly rate types. |
| `fixed_amount` | float |  | Per-project labor price, or unit price for supplies. |
| `quantity` | int |  | Units for supplies. Defaults to 1. Ignored for labor. |
| `amount` | float |  | Line total in `currency`: supplies are fixed_amount * quantity, per-project labor is fixed_amount, hourly labor is hourly_rate * hours on the task timer (time_total_seconds / 3600). Null when the rate type is unresolved or the price is missing. |
| `currency` | string |  | ISO 4217 currency of the amounts. |
| `payee_subuser_id` | string |  | Team member the labor is owed to. Sparse: most labor rows have no payee. |
| `payee_name` | string |  | Display name of the payee team member. Null when payee_subuser_id is null. |
| `pay_to_task_completer` | bool |  | True when the payee is whoever completes the task instead of a fixed person. |
| `bill_to_owner` | bool |  | True when the cost is passed through to the property owner on their statement. Defaults to true. |
| `owner_markup_type` | string |  | Markup applied when billing the owner: 'percentage' \| 'fixed' \| null. |
| `owner_markup_value` | float |  | Markup amount. A percentage when owner_markup_type is percentage, otherwise a currency amount. |
| `uses_besty_payments` | bool |  | True when the labor is paid out through Besty Payments (rows in export_payment_ledger). |
| `instant_payout` | bool |  | True when the Besty Payments payout is sent instantly on completion. |
| `fee_mode` | string |  | Who absorbs the processing fee on a Besty Payments payout: 'added_to_base' \| 'deducted_from_base' \| null. |
| `inventory_item_id` | string |  | Inventory item this supply line deducts from. Null for labor and untracked supplies. |
| `pms_synced_at` | timestamp | time | When the expense was synced to the PMS owner statement. Null when not synced yet. |
| `approval_status` | string |  | Cost approval state: 'pending' (waiting for a manager to approve; not paid until then), 'approved', or null (never gated: the account had cost approval off, or the task was not completed). |
| `approved_at` | timestamp | time | When the line was last approved. Cleared when an approved line goes back to pending. |
| `approved_by_label` | string |  | Name of the person who approved the line. Cleared when an approved line goes back to pending. |
| `approved_amount` | float |  | The line total the approver saw when approving, in approved_currency. Kept when the line goes back to pending, so a pending line with an approved_amount was changed after an earlier approval. |
| `approved_currency` | string |  | ISO 4217 currency of approved_amount. |
| `created_at` | timestamp | time | When the line item was added. |
| `updated_at` | timestamp | time | Last edit to the line item. |

Besty's caveats:

- ops_task_line_items has no user_id. Tenant scope routes through ops_tasks.user_id, so a line item is reachable only through its task.
- payee_subuser_id is null on almost all labor rows. Summing amount by payee describes only the rows that carry one, not total labor spend per person.
- amount for hourly labor depends on the task timer. It is 0 for hourly rows on tasks that were never timed and grows while a timer runs.
- Rows with rate_type 'default' have no amount because the payee rate was never resolved.
- Line items on soft-deleted tasks are excluded by default. Pass filter.include_deleted_tasks=true to include them.
- Amounts are not currency-converted. Group or sum by currency.
- owner_statement_view=not_synced leaves out tasks that only wait on a PMS takedown and have no bill_to_owner lines left. The page lists those too.

#### `export_ops_task_reports`

Bulk export of shared task reports, one row per public share link a host or team member created over a set of operations tasks. `view_count` and `last_viewed_at` record opens of the public link, `is_revoked` marks links that no longer open. filter.task_ids returns reports that include any of those tasks. `share_token` is the live link secret and requires include_pii=true. Empty on accounts that have never shared a task report. Reports have no listing attribution. Primary time field is created_at.

Primary time field: `created_at`. Limits: raw row cap 5000. Join keys: `report_id`, `created_by_subuser_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `report_id` | string |  | Report UUID. |
| `created_by_subuser_id` | string | assignee | Team member who created the share link. Null when the host account created it. |
| `created_by_name` | string |  | Display name of the creating team member. Null when created_by_subuser_id is null. |
| `task_ids` | array |  | Operations task UUIDs included in the report, as stored at creation. Tasks deleted later are still listed. |
| `task_count` | int |  | Number of tasks in the report. |
| `include_comments` | bool |  | True when task comments are visible to anyone opening the link. |
| `view_count` | int |  | Number of times the public link was opened. Every open counts, including repeat opens by the same person. |
| `last_viewed_at` | timestamp | time | Most recent open of the public link. Null when never opened. |
| `is_revoked` | bool |  | True when the link has been revoked and no longer opens. |
| `revoked_at` | timestamp | time | When the link was revoked. Null while it is live. |
| `share_token` | string |  | Public link token. Anyone holding it can open the report, so it requires include_pii=true and an explicit fields request. |
| `created_at` | timestamp | time | When the report was created. |
| `updated_at` | timestamp | time | Last change to the report row, including view-count increments. |

Besty's caveats:

- Empty on accounts that have never shared a task report. Zero rows means the feature is unused, not that the read failed.
- view_count counts link opens, not distinct viewers. The public endpoint records no viewer identity, so "who opened it" is not answerable.
- task_ids is a snapshot from creation. It is not filtered for tasks deleted since, and the report still shows those tasks as they were.
- share_token is the public capability for the link. It is hidden unless include_pii=true and fields includes share_token.
- Reports span tasks from any listing and carry no listing of their own, so this export is unavailable under listing-scoped tokens.

#### `export_ops_tasks`

Bulk export of ops_tasks with assignees, due dates, overdue flags, lateness, and shareable public task_url links. `time_total_seconds` (timer-tracked) is the reliable duration measure; `cycle_seconds` (completed_at - created_at) is NOT surfaced because 86% of automation-created tasks have negative cycle times in production. `is_imported` is a derived flag (automation_id IS NOT NULL). `created_by` says who made each task: task_automation, workflow (any workflow run), pms_sync, person (a team member recorded making it) or other (another Besty feature or by hand, cannot tell); only person is known to be made by hand. Default filter excludes soft-deleted rows; pass filter.include_deleted=true to include. Assignee arrays are null when no assignee exists. `hours_late` is null when due_at is null. Primary time field is created_at.

Primary time field: `created_at`. Limits: raw row cap 5000, max window days 365, default window days 90. Join keys: `ops_task_id`, `reservation_id`, `listing_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `ops_task_id` | string |  | Ops task UUID. |
| `task_url` | string |  | Shareable public task page URL (https://app.getbesty.ai/tasks/<id>/public), same link as Copy link in the Ops task detail. |
| `task_dashboard_url` | string |  | Besty dashboard URL for the task. |
| `department` | string |  | Department name (built-in or custom); null if the department was deleted. |
| `title` | string |  | Task title. |
| `status` | string |  | Task state: todo \| in_progress \| done. |
| `priority` | int |  | Priority 1 (low) — 5 (high). |
| `listing_id` | int |  | FK to listings.id (nullable). |
| `reservation_id` | int |  | FK to reservations.id (nullable). |
| `task_template_id` | string |  | FK to ops_task_templates.id (nullable). |
| `automation_id` | string |  | FK to ops_automations.id (nullable). Non-null implies the task was created by an automation. |
| `is_imported` | bool |  | Derived flag: true if created by an automation/import path. |
| `created_by` | string |  | Who made the task: task_automation (an Operations task automation), workflow (a workflow run, including classic workflows), pms_sync (synced from the PMS), person (a team member is recorded making it), or other (another Besty feature such as an upsell purchase, a direct-booking drop-off or the AI VA, or by hand with no record; the data can't tell which). |
| `assignment_mode` | string |  | How the task is assigned (direct \| claim \| ...). |
| `assignee_subuser_ids` | array | assignee | UUIDs of assigned subusers. Null means the task has no assignees. |
| `assignee_names` | array | assignee | Display names of assigned subusers. Null means the task has no assignees. |
| `estimated_duration_minutes` | int |  | Pre-set duration estimate in minutes. |
| `time_total_seconds` | int |  | Tracked work seconds (sum across timer sessions). Use for "how long did the task take" analytics. |
| `due_at` | timestamp | due, time | Due-at timestamp. |
| `is_overdue` | bool | due | True when the task is past due, not done, and has no completion timestamp. |
| `hours_late` | float |  | Hours from due_at to completion or now. Positive means late; null when due_at is null. |
| `is_unassigned` | bool |  | True when no subuser is assigned to the task. |
| `completed_at` | timestamp | completion, time | Completion timestamp (null while pending). |
| `created_at` | timestamp | time | Creation timestamp. |
| `updated_at` | timestamp | time | Most recent update timestamp. |
| `deleted_at` | timestamp | time | Soft-delete timestamp (null if live). |
| `description` | string |  | Free-text description. |
| `summary` | string |  | Optional summary text. |

Besty's caveats:

- `cycle_seconds` (completed_at - created_at) deliberately not exposed: 86% of automation-created tasks have negative values in production. Use `time_total_seconds` (timer-tracked) instead.
- is_imported is derived from automation_id IS NOT NULL.
- Default filter excludes soft-deleted rows (deleted_at IS NULL). Pass filter.include_deleted=true to include.
- Assignee arrays use correlated subqueries to preserve one row per task. Tasks without assignees return null rather than an empty array.
- hours_late is measured from due_at to completion or now. due_at is null on a meaningful share of automation-created tasks.

#### `export_owners`

Export messaging property owners linked to this account. Ask which owners receive booking digests, have portal accounts, or are attached to listings.

Primary time field: `created_at`. Limits: raw row cap 5000. Join keys: `owner_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `owner_id` | int | contact | Messaging owner row id. |
| `name` | string | contact | Property owner name. |
| `applies_to` | string |  | Whether this owner applies to listings or a listing set. |
| `listing_ids` | jsonb |  | Besty listing ids directly attached to this owner. Listings that arrive through listing_set_ids are not expanded here, but filter.listing_ids matches both. |
| `listing_set_ids` | jsonb |  | Besty listing-set ids attached to this owner. |
| `thread_id` | int |  | Besty thread id used to message this owner. |
| `created_at` | timestamp | time | When this owner was added. |
| `is_deleted` | bool |  | True when this owner was deleted. |
| `weekly_booking_digest` | bool |  | Whether weekly booking digests are enabled. |
| `weekly_booking_digest_last_sent_at` | timestamp | time | When the last weekly booking digest was sent. |
| `has_portal_account` | bool |  | Whether an owner portal account exists. |
| `portal_account_created_at` | timestamp | time | When the owner portal account was created. |
| `has_pending_portal_invite` | bool |  | Whether an unexpired portal invite exists. |
| `portal_invite_expires_at` | timestamp | time | When the portal invite expires. |
| `portal_username` | string | contact | Owner portal username. |
| `hubspot_id` | string | contact | HubSpot contact id. |

Besty's caveats:

- These are messaging owners, not owner-portal subusers; listing-scoped tokens cannot use this tool because owners can be attached through listing sets; on most accounts digest and portal flags are all false, this is not missing data; deleted owners are hidden by default.

#### `export_payment_ledger`

ops_payment_ledger payouts (Stripe-backed) to subusers for completed ops_tasks. `payment_method` is extracted from payment_method_snapshot->card->brand. `platform_revenue` is opt-in (Besty-internal). Primary time field is created_at.

Primary time field: `created_at`. Limits: raw row cap 5000, max window days 730, default window days 365. Join keys: `ledger_id`, `task_id`, `payee_subuser_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `ledger_id` | string |  | Payout entry UUID. |
| `task_id` | string |  | Linked ops_tasks UUID (nullable). |
| `line_item_id` | string |  | Linked ops_task_template_line_item id (nullable). |
| `payee_subuser_id` | string |  | Subuser being paid. |
| `payee_name` | string |  | Display name of the team member being paid. Null when the subuser row is gone. |
| `created_by_subuser_id` | string | assignee | Subuser that created this payout entry. |
| `executed_by_subuser_id` | string |  | Subuser that executed (paid) it. |
| `executed_by_name` | string |  | Display name of the team member who released the payout. Null when not yet executed. |
| `payee_amount` | float |  | Net amount paid to the subuser. |
| `charged_amount` | float |  | Amount charged to the host card. |
| `base_amount` | float |  | The agreed rate this payment was priced from. Equals payee_amount under added_to_base and charged_amount under deducted_from_base. Null on rows written before BES-9456. |
| `fee_mode` | string |  | Who absorbed the Stripe processing fee: added_to_base (host paid rate + fee, payee got the full rate) \| deducted_from_base (host paid the rate, fee came out of the payout). |
| `stripe_fee` | float |  | Stripe-side processing fee. |
| `platform_revenue` | float |  | Internal — Besty platform revenue on this charge. |
| `currency` | string |  | ISO 4217 currency. |
| `payment_method` | string |  | Card brand at time of charge (visa, mastercard, ...). |
| `payment_method_id` | string |  | Stripe payment_method id. |
| `status` | string |  | pending \| succeeded \| failed \| ... |
| `error_code` | string |  | Stripe-side error code on failure. |
| `error_message` | string |  | Stripe-side error message. |
| `attempt_count` | int |  | Retry attempt count. |
| `last_attempt_at` | timestamp | time | Most recent attempt timestamp. |
| `description` | string |  | Free-text description. |
| `created_at` | timestamp | time | Creation timestamp. |

Besty's caveats:

- `payment_method` is extracted from payment_method_snapshot->card->brand (no separate column).
- `platform_revenue` is Besty-internal — opt-in only.
- Empty results may indicate accountSettings.is_payments_enabled = false; the tool does not pre-check.
- Empty on accounts that pay their team outside Besty Payments. Zero rows means the feature is unused, not that no labor was paid.
- status, error_code and error_message come from the Stripe attempt. A failed row may be retried and later succeed as the same row, so read attempt_count alongside status.

#### `export_pms_rate_limit_locks`

Export PMS API rate-limit backoff records. Ask when Besty backed off a PMS and how long each lock lasted.

Primary time field: `created_at`. Limits: raw row cap 10000, max window days 90, default window days 7. Join keys: `lock_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `lock_id` | int |  | Rate-limit lock history id. |
| `pms` | string |  | Property management system name. |
| `reason` | string |  | Reason for the backoff, such as rate_limit_hit. |
| `backoff_ms` | int |  | Backoff duration in milliseconds. |
| `locked_until` | timestamp | time | When the lock ends. |
| `created_at` | timestamp | time | When the lock was recorded. |

Besty's caveats:

- One row per time Besty backed off, not per rejected request; empty on accounts whose PMS never rate limits.

#### `export_pms_webhooks`

Export queued PMS webhooks and processing status. Ask which PMS events failed, are pending, or were retried.

Primary time field: `created_at`. Limits: raw row cap 10000, max window days 90, default window days 7. Join keys: `webhook_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `webhook_id` | bigint |  | Webhook queue id. |
| `status` | string |  | Queue status, such as pending, done, or failed. |
| `event` | string |  | Webhook event name. |
| `pms_reservation_id` | string |  | PMS reservation id from the webhook payload. The column holds the PMS id for every PMS, despite the generic name. |
| `attempts` | int |  | Number of processing attempts. |
| `run_at` | timestamp | time | When processing is scheduled. |
| `locked_at` | timestamp | time | When a worker claimed the row. |
| `error_message` | string |  | Last processing error. It can remain set on rows that later succeeded. |
| `created_at` | timestamp | time | When the webhook was queued. |
| `completed_at` | timestamp | completion, time | When processing completed. |
| `is_failed` | bool |  | True when status is failed. |
| `payload` | jsonb |  | Full webhook payload. |

Besty's caveats:

- error_message is set on done rows too (a retry that later succeeded keeps its last error), so use status, not error_message, to find failures; the queue is high volume, default window is 7 days.

#### `export_price_offers`

Bulk export of guest 'name your price' offers from the direct booking site, one row per offer. `asking_total` is the quoted price, `offer_amount` the guest's proposal, and `offer_percent_of_asking` the ratio. `ai_verdict` ('accept' \| 'counter') is the AI's first response; `status` is where the offer stands now ('accepted', 'countered', 'counter_accepted', 'booked', 'declined', 'counter_expired'). Guest name, email, phone, IP and free-text message require include_pii=true and explicit fields. Primary time field is created_at.

Primary time field: `created_at`. Limits: raw row cap 5000. Join keys: `offer_id`, `listing_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `offer_id` | string |  | Offer uuid. |
| `listing_id` | int |  | Besty internal listing id the offer was made on. |
| `start_date` | date | time | Requested check-in date. |
| `end_date` | date | time | Requested check-out date. |
| `nights` | int |  | end_date minus start_date. |
| `guests` | int |  | Guest count the offer was for. NULL when not given. |
| `pets` | int |  | Pet count the offer was for. NULL when not given. |
| `currency` | string |  | ISO currency code for the amounts. |
| `asking_total` | float |  | Total the site quoted for the stay before the guest made an offer, in major units. |
| `offer_amount` | float |  | Guest's proposed total for the stay, in major units. |
| `offer_percent_of_asking` | float |  | offer_amount / asking_total * 100, rounded to one decimal. NULL when asking_total is 0. |
| `ai_verdict` | string |  | The AI's first decision on the offer: 'accept' or 'counter'. NULL while the offer is unprocessed. |
| `ai_counter_amount` | float |  | The AI's counter total in major units. Set when ai_verdict='counter'. |
| `ai_warmth` | int |  | AI score of how serious the guest seems, on the model's own scale (higher is warmer). NULL when not scored. |
| `ai_signals` | array |  | Short tags the AI cited for its verdict (text array). |
| `status` | string |  | Offer state after the AI verdict: 'accepted' (AI accepted the offer), 'countered' (counter sent, guest has not answered), 'counter_accepted' (guest took the counter), 'booked' (a reservation was created from the offer), 'declined' (AI declined), 'counter_expired' (counter lapsed unanswered). |
| `fees_on_top` | bool |  | True when fees and taxes are added on top of the offered amount rather than included in it. |
| `sms_consent` | bool |  | True when the guest agreed to SMS follow-up. |
| `site_index` | int |  | Which of the account's direct booking sites the offer came from (0-based). NULL on single-site accounts. |
| `expires_at` | timestamp | time | When the offer or counter stops being bookable. |
| `created_at` | timestamp | time | When the guest submitted the offer. |
| `updated_at` | timestamp | time | Last status change. |
| `ai_rationale` | string |  | The AI's internal reasoning for its verdict. Not shown to the guest. |
| `ai_guest_message` | string |  | The reply the AI sent to the guest. |
| `guest_message` | string |  | The guest's free-text note with the offer. Can contain names and contact details. |
| `guest_name` | string | contact | Guest name as typed. |
| `guest_email` | string | contact | Guest email as typed. |
| `guest_phone` | string | contact | Guest phone as typed. NULL when not given. |
| `ip_address` | string |  | Client IP that submitted the offer. |

Besty's caveats:

- ai_verdict is the AI's first answer and never changes. status moves after it: an offer with ai_verdict='counter' can end in status 'countered', 'counter_accepted' or 'booked'. Count counters from ai_verdict, outcomes from status.
- offer_percent_of_asking is NULL when asking_total is 0.
- status 'countered' can be stale: the flip to 'counter_expired' happens lazily when the offer is next read, so compare expires_at to now for live counters.
- There is no reservation id on the offer. 'booked' rows link to the resulting reservation only by listing and dates.
- Empty on accounts without a direct booking site or with name-your-price disabled.

#### `export_proactive_upsell_schedule`

One row per proactive upsell schedule entry with its canonical kind, send window, attempts, and current status. Primary time field is scheduled_at.

Primary time field: `scheduled_at`. Limits: raw row cap 5000. Join keys: `schedule_id`, `reservation_id`, `listing_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `schedule_id` | int |  | Queued proactive offer id. |
| `reservation_id` | int |  | Besty internal reservation id. |
| `listing_id` | int |  | FK to listings.id. |
| `arrival_date` | date | time | Reservation arrival date. |
| `type_raw` | string |  | Stored scheduler kind: eci, lco, ext, or custom. |
| `upsell_kind` | string |  | Canonical upsell kind mapped from type_raw. |
| `custom_item_id` | int |  | Custom upsell item id. Set only for custom rows. |
| `scheduled_at` | timestamp | time | When the scheduler row was created, stored as a UTC wall-clock value. |
| `window_start_at` | timestamp | time | Start of the send window. |
| `window_end_at` | timestamp | time | End of the send window. |
| `started_at` | timestamp | time | When processing started. |
| `attempt_count` | int |  | Number of send attempts. |
| `sent` | bool |  | Whether the scheduled offer was sent. |
| `invalidated_at` | timestamp | time | When the queued row was invalidated. |
| `offer_log_id` | int |  | Originating proactive upsell log id. |
| `status` | string |  | sent when sent; invalidated when invalidated before sending; otherwise pending. Sent wins if both flags are set. |

Besty's caveats:

- The invalidation reason is not stored, so this export cannot explain why a row was invalidated.
- window_start_at and window_end_at are the send window, not the send time. The actual send is an offer message.
- Empty on accounts that do not use proactive upsells.

#### `export_rates`

Flat daily rates export for Meta Prices Feed. Calls PMSConnection.getCalendar per listing when within each PMS hard cap; otherwise falls back to bt_calendar_cache + reservations. Max 50 listings and 365 inclusive dates.

Join keys: `listing_id`, `date`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `listing_id` | int |  | Besty internal listing id. |
| `date` | date | time | YYYY-MM-DD stay date. |
| `nightly_rate` | float |  | Nightly asking rate from the PMS live calendar when available. |
| `currency` | string |  | Rate currency from the PMS live calendar when available. |
| `is_available` | bool |  | True when the date is available. |
| `minimum_stay` | int |  | Day-level minimum stay when the PMS returns it. |
| `maximum_stay` | int |  | Day-level maximum stay when the PMS returns it. |
| `rate_source` | string |  | pms_realtime when fetched live from PMS; fallback when using cache + reservations. |
| `synced_at` | timestamp | time | ISO timestamp for this rates sync call. |

Besty's caveats:

- Each call attempts live PMS fetches with prefer=live. If the requested window exceeds a PMS hard cap, rows use rate_source=fallback.
- Fallback rows come from cache + reservations and do not have nightly_rate or currency today.
- minimum_stay and maximum_stay are only populated when the PMS calendar response exposes day-level stay rules.

#### `export_reactive_upsell_offers`

One row per reactive upsell offer generated in reply to a guest message. These are generated replies, not proof of delivery. Drafts are excluded by default. Primary time field is created_at.

Primary time field: `created_at`. Limits: raw row cap 5000. Join keys: `log_id`, `reservation_id`, `listing_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `log_id` | int |  | Reactive upsell log id. |
| `reservation_id` | int |  | Reservation id. The source column is named besty_reservation_id. |
| `listing_id` | int |  | FK to listings.id. |
| `arrival_date` | date | time | Reservation arrival date. |
| `type_raw` | string |  | Stored reactive kind in camelCase, such as extraNights or lateCheckOut. |
| `upsell_kind` | string |  | Canonical upsell kind mapped from type_raw. |
| `is_draft` | bool |  | True when the reply was drafted for host review and not sent to the guest. |
| `offered_price` | float |  | Price offered in the generated reply. |
| `offered_currency` | string |  | Currency for offered_price. |
| `avg_nightly_rate` | float |  | Average nightly rate used by the offer generator. |
| `experiment_bucket` | string |  | Experiment assignment used by the offer generator. |
| `guest_message` | string |  | Guest text that triggered the offer. |
| `message_to_guest` | string |  | Reply text generated for the guest. |
| `created_at` | timestamp | time | When the generated reply was created, stored as a UTC wall-clock value. |

Besty's caveats:

- A log row is a generated reply, not proof of delivery. The actual send is a bt_messages row.
- The upsells and settings_snapshot JSON columns are not exposed.
- One reservation can have many rows, one for each guest question. Drafts are excluded by default.

#### `export_reservation_financials`

Explodes the reservation_financials jsonb blob into 12 discrete numeric columns + currency. `revenue_amount` is the gross figure (taxes/fees included). `reservation_id` and `listing_id` are Besty internal ints (LEFT JOIN). To look up by PMS-side string id, use `filter.external_reservation_ids`. Coverage is biased toward Hostaway; other PMSes lazy-write. NO FX conversion — group/sum by currency. Primary time field is fetched_at.

Primary time field: `fetched_at`. Limits: raw row cap 5000, max window days 730, default window days 365. Join keys: `reservation_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `financials_id` | int |  | Internal row id. |
| `pms` | string |  | Owning PMS. |
| `reservation_id` | int |  | Besty internal reservation id (LEFT JOIN — NULL when the linked reservation row is missing). |
| `listing_id` | int |  | Besty internal listing id (LEFT JOIN via reservations — NULL when the linked reservation row is missing). |
| `data_source` | string |  | Provenance — typically 'api'. |
| `fetched_at` | timestamp | time | When Besty pulled this blob. |
| `arrival_date` | date | time | Arrival date of the linked reservation (LEFT JOIN, NULL when the reservation row is missing). |
| `currency` | string |  | Currency code (NB: NO FX conversion happens — group/sum by currency). |
| `revenue_amount` | float |  | Gross revenue including taxes/fees. |
| `host_payout` | float |  | Net to host after channel fees + taxes remitted. |
| `fare_accommodation` | float |  | Base accommodation fare. |
| `cleaning_fee` | float |  | Cleaning fee component. |
| `additional_fees` | float |  | Sum of misc fees. |
| `channel_fee` | float |  | Channel-side commission. |
| `taxes_collected` | float |  | Total taxes collected from guest. |
| `taxes_remitted_by_channel` | float |  | Taxes the channel remitted on behalf of the host. |
| `discounts` | float |  | Total discount. |
| `total_refunded` | float |  | Total refunded across the lifecycle. |
| `additional_fee_details` | jsonb |  | Per-fee jsonb breakdown. |
| `financials_raw` | jsonb |  | Full PMS-provided jsonb (variable shape). |

Besty's caveats:

- Coverage is biased toward Hostaway (eager-writes inline on every reservation refresh); other PMSes lazy-write on read. Filter on `pms` when comparing portfolios.
- NO FX conversion across `currency` values — group/sum by currency.
- `reservation_id` and `listing_id` are LEFT-JOINed — NULL when the linked reservation row is missing.

#### `export_reservations`

Bulk reservation export for a host. Returns either inline rows (≤200 rows ≤50 KB) or a Parquet file URL backed by S3 (24h TTL, idempotent on input hash). Columns expose normalised channel + status_category + revenue (`revenue_amount` = COALESCE(total_price, price), matching production CRM). Guest contact info is opt-in via `include_pii`. To look up reservations by PMS-side string id, pass `filter.external_reservation_ids`. To find the stays of a named guest, pass `filter.guest_name` with no time range, then narrow by date. Optional `aggregation` parameter runs a flat group-by in Postgres before delivery; `channel` and `status_category` are first-class aggregation dimensions/filters. Primary time field is booking_at.

Primary time field: `booking_at`. Limits: raw row cap 10000, max window days 730, default window days 365. Join keys: `reservation_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `reservation_id` | int |  | Besty internal reservation id (stable across PMS refreshes). |
| `external_reservation_id` | string |  | PMS-side reservation id. Matches filter.external_reservation_ids. |
| `pms` | string |  | Owning PMS ("hostaway", "ownerrez", "guesty", "airbnb_official", "direct", ...). |
| `listing_id` | int |  | FK to listings.id. |
| `status_raw` | string |  | PMS-specific status string as written by the connector (no normalisation). |
| `channel_raw` | string |  | Raw channel string as written by the connector. Some PMSs write their own booking-source labels here (Streamline: 'Internet Reservation', 'Admin Reservation', 'Wholesale Reservation'), which `channel` maps to 'unknown'. Usable as an aggregation dimension. |
| `arrival_date` | date | time | Arrival date (no TZ). Use for occupancy queries. |
| `departure_date` | date | time | Departure date (no TZ). |
| `arrival_at` | timestamp | time | Arrival timestamp (PMS-provided check-in time). |
| `departure_at` | timestamp | time | Departure timestamp. |
| `booking_at` | timestamp | time | When the reservation was booked. |
| `created_at` | timestamp | time | When Besty first synced this reservation. |
| `number_of_nights` | int |  | Reservation length in nights. |
| `num_guests` | int |  | Booking party size (this reservation). Distinct from listing.max_guests. |
| `num_adults` | int |  | Adult headcount. |
| `num_children` | int |  | Children headcount. |
| `num_infants` | int |  | Infants headcount. |
| `num_pets` | int |  | Pet count. |
| `currency` | string |  | ISO 4217 currency code. Owner-portal aggregations do NOT FX-convert — group/sum by currency. |
| `revenue_amount` | float |  | Reservation total. PMS-varying inclusion of taxes/fees — treat as host-facing revenue figure, not nightly rate. Matches CRM revenue convention. |
| `guest_name` | string | contact | Guest display name. |
| `email` | string | contact | Guest email. |
| `phone` | string | contact | Guest phone. |
| `channel` | string |  | Canonical channel ('airbnb', 'bookingcom', 'vrbo', 'direct', 'unknown'). Derived from channel_raw via normalizeChannel — airbnb/airbnb2/airbnbOfficial all collapse to 'airbnb'. Usable in aggregation dimensions/filters/measures. |
| `status_category` | string |  | Canonical reservation status ('confirmed' \| 'active' \| 'canceled' \| 'inquiry' \| 'unknown'). Derived from (pms, status_raw) via the PMS dispatcher. Usable in aggregation dimensions/filters/measures. |

Besty's caveats:

- `revenue_amount` = COALESCE(total_price, price) — PMS-varying inclusion of taxes/fees. NOT a nightly rate.
- No FX conversion across `currency` values — group/sum by currency.
- status_category and channel are derived; in raw exports they are computed client-side, in aggregations they compile to SQL CASE expressions.
- status_category 'canceled' includes status_raw 'closed' (Guesty and others): a booking closed without a stay, which is neither a finished stay nor necessarily a guest cancellation. For a cancellation rate, group by status_raw and report closed apart from canceled.

#### `export_returning_guest_flags`

One row per reservation with the raw PMS returning-guest value and a nullable boolean. Only Guesty writes this flag. NULL means unreported, not first-time. The 'returning share' comes from aggregating is_returning_guest over non-null rows. Primary time field is booking_at.

Primary time field: `booking_at`. Limits: raw row cap 5000, max window days 730, default window days 365. Join keys: `reservation_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `reservation_id` | int |  | Besty internal reservation id. |
| `listing_id` | int |  | Besty internal listing id. |
| `pms` | string |  | PMS that supplied the reservation. |
| `status_raw` | string |  | Raw PMS reservation status. |
| `channel_raw` | string |  | Raw PMS booking channel. |
| `arrival_date` | date | time | Guest arrival date. |
| `departure_date` | date | time | Guest departure date. |
| `booking_at` | timestamp | time | When the reservation was booked. |
| `arrival_at` | timestamp | time | Reservation arrival timestamp. |
| `num_guests` | int |  | Number of guests on the reservation. |
| `returning_flag_raw` | string |  | Raw PMS value. Only Guesty writes this field; it is null on other PMSes. |
| `is_returning_guest` | bool |  | PMS returning-guest flag. NULL means the PMS did not report it, not 'first-time'. Compute a returning share only over rows where this is not null. |
| `has_returning_flag` | bool |  | True when the raw reservation JSON contains isReturningGuest. |
| `guest_name` | string | contact | Guest name from the reservation. |
| `email` | string | contact | Guest email from the reservation. |
| `phone` | string | contact | Guest phone from the reservation. |

Besty's caveats:

- The flag lives in raw PMS JSON and only Guesty writes it. Other PMSes usually return NULL.
- status_raw is the raw PMS status. Use export_reservations for canonical status_category.
- This is a row-level export. A 'share of returning' comes from aggregating is_returning_guest over rows where it is not null.

#### `export_review_issues`

Bulk export of review scanner issue rows. Each row is one review the scanner flagged for a problem. Use this, not export_reviews, for flagged reviews: how many, their causes and the homes involved. Hosts can also ask which issues were read or remain open. Category is NULL on the pilot and should not be grouped.

Primary time field: `reviewed_at`. Limits: raw row cap 10000, max window days 730, default window days 365. Join keys: `issue_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `issue_id` | int |  | Besty internal id for one review scanner issue row. |
| `pms_review_id` | string |  | PMS-side review id. Joins export_reviews.pms_review_id. |
| `listing_id` | int |  | Besty internal listing id resolved from the PMS listing id through the listings table. |
| `listing_url` | string |  | Canonical listing URL: https://app.getbesty.ai/listings?listingId=<listing_id>. |
| `external_listing_id` | string |  | PMS-side listing id. It resolves to listing_id through the listings table. |
| `listing_name` | string |  | Listing name as captured when the issue was flagged. |
| `pms` | string |  | PMS connector name, for example guestyBff. |
| `guest_name` | string | contact | Guest display name captured by the review scanner. |
| `reviewed_at` | timestamp | time | Date and time when the review was recorded, stored without a time zone. |
| `rating` | string |  | Star rating as text as stored by the scanner. Cast before math. |
| `denominator` | string |  | Maximum star rating as text as stored by the scanner. |
| `category` | string |  | Issue category. NULL on every row for accounts observed so far. Do not group by it. Use export_reviews.has_major_issue or export_improvement_suggestions instead. |
| `combined_feedback` | string |  | Public review text and private feedback concatenated by the scanner. |
| `actions` | jsonb |  | Suggested follow-up actions produced by the scanner, with a variable JSON shape. |
| `is_read` | bool |  | True once someone opened the issue in the Besty UI. |

Besty's caveats:

- Category was never populated on the pilot, so category groups do not identify distinct issue types.
- Almost all rows are unread in the observed data.
- There is one row per review because review_id is unique, not one row per distinct problem.
- Accounts without the review scanner have no rows in this export.

#### `export_review_replies`

Bulk export of review replies processed by Besty. Each row is one review in the responder pipeline, so hosts can ask which reviews were sent, drafted, or left unanswered. Use export_reviews for the complete review list because this export covers only the responder subset.

Primary time field: `reviewed_at`. Limits: raw row cap 10000, max window days 730, default window days 365. Join keys: `reply_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `reply_id` | int |  | Besty internal ID for this review-responder row. Each row represents one review processed by Besty. |
| `pms_review_id` | string |  | PMS-side review id. Joins export_reviews.pms_review_id. |
| `external_reservation_id` | string |  | PMS-side reservation id. The database column is named hostaway_reservation_id, but it holds the PMS reservation id for every PMS. |
| `reservation_id` | int |  | Besty internal reservation id from the linked stay. NULL when the reservation was not synced. |
| `listing_id` | int |  | Besty internal listing id stored on the linked reservation. NULL when there is no linked stay row. |
| `listing_url` | string |  | Canonical listing URL: https://app.getbesty.ai/listings?listingId=<listing_id>. |
| `channel_raw` | string |  | Raw review channel value stored by the responder. Use channel for the canonical channel name. |
| `channel` | string |  | Canonical review channel: 'airbnb', 'bookingcom', 'vrbo', 'direct', or 'unknown'. Derived from channel_raw. |
| `guest_name` | string | contact | Guest name attached to the review responder row. It is the display name supplied by the PMS. |
| `rating` | float |  | Star rating the guest gave, out of rating_denominator. |
| `rating_denominator` | int |  | Maximum value for rating. Use it as the denominator when comparing star ratings. |
| `reviewed_at` | timestamp | time | Date and time when the guest review was recorded, stored without a time zone. |
| `reply_draft` | string |  | Reply text Besty generated. It can be present even when nothing was sent. |
| `reply_sent_text` | string |  | Reply text actually posted to the channel. |
| `reply_sent_at` | timestamp | time | Date and time when the reply was posted, stored without a time zone. NULL when no reply was sent. |
| `autopilot` | bool |  | True when Besty generated and sent the reply without a human. |
| `manual_reply_needed` | bool |  | True when the responder decided a human must write the reply, for example when the rating is below the autopilot threshold. |
| `manual_reply_notified` | bool |  | True when Besty notified the host that a human reply is needed. |
| `private_feedback` | string |  | Text the guest sent only to the host, copied from the PMS payload. |
| `review_text` | string |  | Public review body. |
| `account_autopilot_enabled` | bool |  | Account-level setting, repeated on every row. True when Besty auto-sends review replies. |
| `account_autopilot_min_stars` | int |  | Reviews at or above this star count are auto-replied. The same value appears on every row for the account. |
| `reply_state` | string |  | Reply state: 'sent' when posted, 'drafted' when only a draft exists, or 'none' when neither exists. |
| `has_reply_sent` | bool |  | True when reply_sent_at is populated and a reply was posted to the channel. |

Besty's caveats:

- Rows exist only for reviews processed by Besty's responder. Pilot coverage was 4,730 of 13,948 reviews, starting in 2025-02.
- This is not the complete review list. Use export_reviews when a host asks about all reviews.
- `reviewed_at` and `reply_sent_at` are stored without a time zone, so they do not identify a time zone.
- The account_autopilot_* columns are account settings repeated on each row, not facts about the individual review.
- Accounts that never enabled the review responder have no rows in this export.

#### `export_reviews`

Bulk export of guest reviews with canonical channel, category scores, private feedback, and linked stay and guest fields. Category scores exist only for PMSes that send them, such as Guesty. Private feedback is opt-in. Stay and guest columns are NULL for reviews that predate reservation sync. Per-guest or revenue answers must report the has_linked_stay = false count. To look up by PMS-side review id, use `filter.pms_review_ids`. Default filter excludes empty placeholder rows (no rating, no text, no private feedback: reviews the guest never left); pass filter.include_empty=true to include them. Primary time field is reviewed_at.

Primary time field: `reviewed_at`. Limits: raw row cap 10000, max window days 730, default window days 365. Join keys: `review_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `review_id` | int |  | Besty internal review id. |
| `pms_review_id` | string |  | PMS-side review ID. This joins to export_review_replies.pms_review_id and export_review_issues.pms_review_id. |
| `listing_id` | int |  | Besty internal listing id. LEFT-JOINed through the matched reservation row (the JOIN needs reservations.pms to disambiguate listings, which is unique on (pms, pms_id) but not on pms_id alone). NULL when the reservation is missing OR the listing row is missing. |
| `listing_url` | string |  | Canonical listing URL: https://app.getbesty.ai/listings?listingId=<listing_id>. |
| `external_listing_id` | string |  | PMS-side listing ID. It remains populated when listing_id is NULL. |
| `external_reservation_id` | string |  | PMS-side reservation ID. It matches reservations.hostaway_reservation_id, which stores PMS reservation IDs for every PMS. |
| `reservation_id` | int |  | Besty internal reservation id (LEFT JOIN — NULL when the linked reservation row is missing). |
| `channel_raw` | string |  | Raw channel id (airbnb / airbnb2 / airbnbOfficial / bookingcom / ...). Always selected so the `channel` normaliser transform sees it. |
| `guest_name` | string | contact | Reviewer display name as supplied by the channel. |
| `rating` | float |  | Overall rating. |
| `rating_denominator` | int |  | Denominator for the rating (defaults to 5). |
| `has_reply` | bool |  | True if the host has replied. |
| `has_major_issue` | bool |  | Set by Besty's review scanner when the review text describes a serious problem. Prefer this over export_review_issues.category for grouping. |
| `category_cleanliness` | float |  | Guest sub-score for cleanliness, out of rating_denominator, from the raw PMS payload. The Guesty key is category_ratings_cleanliness. NULL when absent or skipped. Use it in aggregation measures such as avg. |
| `category_accuracy` | float |  | Guest sub-score for accuracy, out of rating_denominator, from the raw PMS payload. The Guesty key is category_ratings_accuracy. NULL when absent or skipped. Use it in aggregation measures such as avg. |
| `category_checkin` | float |  | Guest sub-score for checkin, out of rating_denominator, from the raw PMS payload. The Guesty key is category_ratings_checkin. NULL when absent or skipped. Use it in aggregation measures such as avg. |
| `category_communication` | float |  | Guest sub-score for communication, out of rating_denominator, from the raw PMS payload. The Guesty key is category_ratings_communication. NULL when absent or skipped. Use it in aggregation measures such as avg. |
| `category_location` | float |  | Guest sub-score for location, out of rating_denominator, from the raw PMS payload. The Guesty key is category_ratings_location. NULL when absent or skipped. Use it in aggregation measures such as avg. |
| `category_value` | float |  | Guest sub-score for value, out of rating_denominator, from the raw PMS payload. The Guesty key is category_ratings_value. NULL when absent or skipped. Use it in aggregation measures such as avg. |
| `has_private_feedback` | bool |  | True when the raw PMS payload contains non-empty private feedback. |
| `private_feedback` | string |  | Text sent only to the host and not published on the channel. It comes from the Guesty privateFeedback payload key and is not replyable on the channel. |
| `stay_arrival_date` | date | time | Arrival date for the linked stay. NULL when no stay is linked. |
| `stay_departure_date` | date | time | Departure date for the linked stay. NULL when no stay is linked. |
| `stay_channel_raw` | string |  | Raw booking channel for the linked stay. NULL when no stay is linked. |
| `stay_revenue` | float |  | Total price in stay_currency as stored by the PMS, not net payout. NULL when no stay is linked. |
| `stay_currency` | string |  | Currency for stay_revenue. NULL when no stay is linked. |
| `stay_nights` | int |  | Nights for the linked stay. Sparse for many PMS connectors; compute it from dates when needed. |
| `guest_external_id` | string | contact | PMS-side guest ID for the reviewed stay. It identifies repeat guests across stays in the account even without a Besty guest row. |
| `guest_prior_stays` | int |  | Count of earlier confirmed or completed stays by the same PMS guest ID in the account. 0 means first stay. NULL when there is no linked stay. |
| `guest_id` | string | contact | Besty guest row ID for the linked stay. Opt-in per-row lookup. |
| `crm_contact_id` | string | contact | CRM contact ID for the linked guest. Opt-in per-row lookup. |
| `review_text` | string |  | Free-text review body. |
| `review_object` | jsonb |  | Full PMS payload — variable shape per PMS. |
| `reviewed_at` | timestamp | time | When the channel says the review was left. |
| `synced_at` | timestamp | time | When Besty last pulled this review from the PMS. |
| `channel` | string |  | Canonical channel ('airbnb', 'bookingcom', 'vrbo', 'direct', 'unknown'). Derived from channel_raw via normalizeChannel — airbnb/airbnb2/airbnbOfficial collapse to 'airbnb'. Usable in aggregation dimensions/filters/measures. |
| `has_linked_stay` | bool |  | True when the review has a linked stay. Every answer based on stay or guest columns must report the number of reviews where this is false. |

Besty's caveats:

- channel_id is NOT normalised at write time on the PMS-reviews table — UI currently shows airbnb/airbnb2/airbnbOfficial as separate bars. `channel` here is canonicalised; `channel_raw` is opt-in for the raw value.
- `review_text` and `review_object` (full PMS payload) are opt-in to keep default payloads small.
- `reservation_id` is LEFT-JOINed — NULL when the linked reservation row is missing (historical reviews predating the booking sync).
- `listing_id` is LEFT-JOINed THROUGH the matched reservation (needs reservations.pms to disambiguate the listings unique constraint), or by pms_id alone when there is no reservation and the pms_id is unambiguous for the user. NULL when the listing cannot be told apart OR the listing row is missing. Multi-PMS users with overlapping pms_id values across PMSes would silently get duplicate rows without this discriminator.
- Category scores exist only for PMSes that send them, such as Guesty. Private feedback is opt-in.
- Stay and guest columns are NULL for reviews that predate reservation sync. The pilot account had approximately 40 percent of reviews without linked stays, so per-guest or revenue answers must report the has_linked_stay = false count.
- `guest_prior_stays` uses PMS guest IDs and misses guests who rebooked through another channel account. `guest_id` and `crm_contact_id` are opt-in per-row lookups.

#### `export_scheduled_journey_messages`

One row per planned automated send. Default ordering and the default time axis use added_at, so pending future sends are never dropped. For what goes out in the next 24 hours, set filter.scheduled_after = now, filter.scheduled_before = now + 24h and filter.pending_only = true. If you use time_range on scheduled_for, pass both since and until, because a missing until is snapshotted to now on pageable calls.

Primary time field: `added_at`. Limits: raw row cap 5000. Join keys: `scheduled_message_id`, `journey_id`, `message_id`, `reservation_id`, `listing_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `scheduled_message_id` | bigint |  | Scheduled journey message id. |
| `scheduled_for` | timestamp | time | When the message is scheduled to send. |
| `added_at` | timestamp | time | When the message entered the schedule. |
| `window_closes_at` | timestamp | time | Latest time at which the send window closes. |
| `last_constraint_check_at` | timestamp | time | When journey constraints were last checked. |
| `occurrence_date` | date | time | Occurrence date. '1970-01-01' is the sentinel for a single occurrence. |
| `journey_id` | int |  | Journey id. |
| `journey_name` | string |  | Journey name. |
| `journey_is_active` | bool |  | Whether the journey is active. |
| `message_id` | int |  | Automated journey message id. |
| `message_name` | string |  | Automated journey message name. |
| `send_channel` | string |  | Channel used for the automated send. |
| `scheduling_type` | string |  | Journey scheduling type. |
| `external_reservation_id` | string |  | PMS reservation id. |
| `reservation_id` | int |  | Besty reservation linked by PMS id. |
| `listing_id` | int |  | Besty listing linked to the reservation. |
| `guest_name` | string | contact | Guest display name. |
| `arrival_date` | date | time | Reservation arrival date. |
| `departure_date` | date | time | Reservation departure date. |
| `message_sent` | bool |  | Whether the scheduled message was sent. |
| `failed_check` | bool |  | Whether a journey constraint check failed. |
| `status` | string |  | Derived status: sent, skipped_failed_check, overdue, or pending. |
| `sent_despite_failed_check` | bool |  | Whether the message was sent even though failed_check is true. |

Besty's caveats:

- The failed-check reason is not stored.
- Some rows are sent with failed_check = true (78 on the pilot account); the flag was set and later overridden, so filter on message_sent for what actually went out.
- There is no default time window. The row cap keeps the newest added_at rows first.
- Guest fields are null when the reservation row is gone.

#### `export_signer_sessions`

One row per signer session for a rental agreement and its identity verification status. Tokens, raw guest answers, signatures, and provider report ids are never exposed. Primary time field is created_at.

Primary time field: `created_at`. Limits: raw row cap 5000. Join keys: `session_id`, `reservation_id`, `listing_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `session_id` | string |  | Signing session UUID. |
| `reservation_id` | int |  | Besty internal reservation id. |
| `listing_id` | int |  | FK to listings.id. |
| `arrival_date` | date | time | Reservation arrival date. |
| `departure_date` | date | time | Reservation departure date. |
| `guest_name` | string | contact | Guest display name. |
| `template_id` | string |  | Agreement template UUID. |
| `template_name` | string |  | Agreement template name. |
| `template_is_active` | bool |  | Whether the template is currently active. |
| `status` | string |  | Signing state: sent, in_progress, pending_review (signed, ID name awaiting host review), completed, expired, or invalidated. |
| `is_completed` | bool |  | True when status is completed. |
| `created_at` | timestamp | time | When the signing link was created and sent. |
| `completed_at` | timestamp | completion, time | When signing completed. |
| `token_expires_at` | timestamp | time | Link expiry time. Expired status is set when this passes without completion. |
| `updated_at` | timestamp | time | When the session was last updated. |
| `pms_agreement_uploaded` | bool |  | True when the signed PDF was pushed to at least one PMS integration. |
| `fields_completed` | int |  | Number of form fields the guest has filled. |
| `verification_status` | string |  | Identity verification state. NULL when disabled or not started. |
| `verified_at` | timestamp | time | When identity verification succeeded. |
| `verification_attempts` | int |  | Number of identity verification attempts. |
| `verification_enabled` | bool |  | Whether identity verification is enabled on the template. |
| `minimum_age` | int |  | Minimum guest age configured for the template. |
| `guest_age` | int |  | Guest age used for verification. |
| `verification_failures` | int |  | Number of recorded identity verification failures. |
| `verification_failure_history` | jsonb |  | Identity verification failure history. |

Besty's caveats:

- Multiple sessions can exist for one reservation when a link is resent. Session completion rates are lower than reservation-level rates.
- Verification fields are NULL on accounts with verification disabled. rental_agreement_signed sidekick events are not joined here.
- For arrivals without a signed agreement, filter arrival_date and unsigned_only, then deduplicate by reservation_id. unsigned_only excludes pending_review sessions: the guest has signed, only the host review is outstanding.
- Empty on accounts that do not use rental agreements.

#### `export_site_searches`

Bulk export of natural language searches visitors ran on the direct booking site, one row per search. Answers what people search for, which searches return zero homes (`is_zero_result`, `filter.zero_results`), and which stay months are in demand (`start_date`; use `time_range.field=start_date`). Geography and ip_address reflect a server IP on most rows and are not visitor locations. Searches have no listing attribution. Primary time field is created_at.

Primary time field: `created_at`. Limits: raw row cap 5000. Join keys: `search_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `search_id` | bigint |  | Besty internal search id. |
| `query` | string |  | Visitor's raw search text, as typed. |
| `start_date` | date | time | Requested check-in date, when the visitor gave dates. NULL for undated searches. |
| `end_date` | date | time | Requested check-out date, when the visitor gave dates. |
| `flex_days` | int |  | How many days either side of the dates the visitor allowed. NULL or 0 for exact dates. |
| `adults` | int |  | Adults in the party. NULL when not given. |
| `children` | int |  | Children in the party. NULL when not given. |
| `infants` | int |  | Infants in the party. NULL when not given. |
| `pets` | int |  | Pets in the party. NULL when not given; 0 means the visitor said no pets. |
| `party_size` | int |  | adults + children + infants, treating NULL as 0. 0 when the visitor gave no party size. |
| `result_count` | int |  | Number of homes returned as matches. 0 is a zero-result search. |
| `similar_count` | int |  | Number of near-miss homes shown as alternatives under the results. NULL when the site did not compute them. |
| `is_zero_result` | bool |  | True when the search matched no homes. |
| `ranker_used` | bool |  | True when the AI ranker ordered the results; false or NULL when plain filtering was used. |
| `device_summary` | string |  | Short device label parsed from the user agent (for example 'Mobile Safari on iOS'). |
| `geo_country` | string |  | Country resolved from ip_address. Unreliable: on the pilot account nearly every search shares one server IP, so this reflects the proxy, not the visitor. |
| `geo_region` | string |  | Region or state resolved from ip_address. Same caveat as geo_country. |
| `geo_city` | string |  | City resolved from ip_address. Same caveat as geo_country. |
| `user_agent` | string |  | Raw HTTP user agent. |
| `ip_address` | string |  | Client IP the search API saw. Mostly a server or proxy IP today. |
| `created_at` | timestamp | time | When the search ran. |

Besty's caveats:

- ip_address, geo_country, geo_region and geo_city describe the IP the search API received. On the pilot account 1351 of 1371 searches share one IP, so they describe a proxy or crawler, not visitors. Do not report visitor geography from this table until source IP capture is fixed.
- Rows are searches, not visitors. One visitor refining a query produces several rows, and there is no session or visitor id to group them.
- start_date and end_date are NULL on undated searches. Aggregating by stay month only covers dated searches.
- Searches carry no listing id and are unavailable under listing-scoped tokens.
- Empty on accounts without a direct booking site or with AI search disabled.

#### `export_stripe_holds`

One row per Stripe hold against a reservation. Sum amount where status is hold to estimate current authorised money. Stripe webhook updates can lag. Primary time field is created_at.

Primary time field: `created_at`. Limits: raw row cap 5000. Join keys: `hold_id`, `reservation_id`, `listing_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `hold_id` | string |  | Stable hold UUID. |
| `reservation_id` | int |  | Besty internal reservation id. |
| `listing_id` | int |  | FK to listings.id. |
| `arrival_date` | date | time | Reservation arrival date. |
| `departure_date` | date | time | Reservation departure date. |
| `type` | string |  | Hold type. Today this is damage_waiver. |
| `status` | string |  | pending_session means checkout opened; hold means money is authorised; captured means charged; released means cancelled or refunded; expired means the authorisation lapsed; failed means authorisation failed. |
| `is_active` | bool |  | True only while status is hold. |
| `amount_in_cents` | int |  | Authorised amount in cents. |
| `amount` | float |  | Authorised amount in major currency units. |
| `currency` | string |  | Currency for the hold amount. |
| `capture_before` | timestamp | time | Last moment the hold can be captured, stored as a UTC wall-clock value. |
| `extends_id` | string |  | Earlier hold UUID that this row re-authorised. |
| `reauthorization_failed_attempts` | int |  | Number of failed reauthorization attempts. |
| `reauthorization_failed_at` | timestamp | time | When reauthorization last failed. |
| `card_brand` | string |  | Card brand. |
| `last4` | string |  | Last four card digits. |
| `payment_intent_id` | string |  | Stripe payment intent id. |
| `charge_id` | string |  | Stripe charge id. |
| `checkout_session_id` | string |  | Stripe checkout session id. |
| `created_at` | timestamp | time | When the hold row was created. |
| `updated_at` | timestamp | time | When the hold row was last updated. |

Besty's caveats:

- Current authorised money is sum(amount) for status hold. Captured amount is the authorised amount, and partial captures are not recorded separately.
- Status comes from Stripe webhooks and recent rows may lag. Empty on accounts that do not use holds.

#### `export_suggestion_evidence`

Bulk export of evidence supporting offline improvement suggestions. Each row is one guest quote from a review or message conversation, so hosts can ask why a recommendation was made. Review fields are NULL for thread evidence, and source_date gives the guest-side date when a review date exists.

Primary time field: `created_at`. Limits: raw row cap 5000. Join keys: `evidence_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `evidence_id` | int |  | Besty internal id for one evidence row supporting an offline improvement suggestion. |
| `suggestion_id` | int |  | Besty internal id of the suggestion that this evidence supports. |
| `suggestion_title` | string |  | Title of the suggestion this quote supports. |
| `listing_id` | int |  | Besty internal listing id affected by the suggestion. NULL when the listing row is missing. |
| `external_listing_id` | string |  | PMS-side listing id from the suggestion. It identifies the affected listing in the account PMS. |
| `source_type` | string |  | 'review' (a guest review) or 'thread' (a guest message conversation). |
| `source_id` | string |  | Besty internal id of the source as text: pms_reviews.id for review evidence, or bt_threads.id for thread evidence. |
| `review_id` | int |  | Besty internal review id for review evidence. NULL for thread evidence. |
| `review_rating` | float |  | Star rating from the linked review. NULL for thread evidence. |
| `reviewed_at` | timestamp | time | Date and time when the linked review was recorded. NULL for thread evidence. |
| `quote` | string |  | Excerpt of the guest's words that supports the suggestion. |
| `importance` | float |  | Weight assigned offline. Higher means the guest stressed the issue more. |
| `created_at` | timestamp | time | When the offline run recorded this evidence, not when the guest wrote it. Use source_date for the guest-side date. |
| `source_date` | timestamp | time | Date of the underlying review when known, else when the evidence row was created. |

Besty's caveats:

- Evidence for archived suggestions is hidden by default and appears only when filter.include_archived is true.
- Thread sources carry no review columns because they come from guest message conversations.
- Evidence for a deleted suggestion is unreachable because this export uses an inner join to owner_portal_suggestions.
- Accounts without the owner-portal analytics feature have no rows in this export.

#### `export_team_logins`

Export refresh-token login events for team members and account owners. Ask when people signed in and how their refresh tokens rotated.

Primary time field: `issued_at`. Limits: raw row cap 10000, max window days 365, default window days 30. Join keys: `refresh_token_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `refresh_token_id` | string |  | Refresh-token UUID. |
| `parent_id` | string |  | Parent refresh-token UUID. Null identifies a fresh interactive login. |
| `issued_at` | timestamp | time | Derived issue time. Refresh tokens expire 14 days after issue. |
| `rotated_at` | timestamp | time | When this refresh token rotated. |
| `expires_at` | timestamp | time | When this refresh token expires. |
| `revoked_at` | timestamp | time | When this refresh token was revoked. |
| `subuser_id` | string | assignee | Subuser UUID. |
| `subuser_name` | string |  | Name of the logged-in team member. |
| `user_agent` | string |  | Client user-agent string. |
| `device` | string |  | Derived device class. |
| `ip` | string |  | Client IP address. |
| `is_fresh_login` | bool |  | True when parent_id is null. |
| `is_revoked` | bool |  | True when revoked_at is set. |

Besty's caveats:

- Default excludes rotated tokens, pass fresh_only=false to see the rotation chain; issued_at is derived from expires_at.

#### `export_team_members`

Export the team roster, app installs, and account-scoped activity metrics. Ask who uses Besty, and sort by days_active_30d to find power users. Deactivated members are excluded by default (filter.include_inactive=true to include).

Limits: raw row cap 2000. Join keys: `subuser_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `subuser_id` | string | assignee | Subuser UUID. |
| `name` | string | contact | Team member display name. |
| `role` | string |  | Besty role. Null for owner-type logins. |
| `type` | string |  | Login type: admin, regular, or owner. |
| `state` | string |  | Invite state. invited means the invite was not accepted. deactivated rows are excluded unless filter.include_inactive=true. |
| `is_account` | bool |  | True for the login that owns the account. |
| `email` | string | contact | Team member email address. |
| `phone` | string | contact | Team member phone number. |
| `updated_at` | timestamp | time | When the team member row last changed. |
| `invite_last_sent_at` | timestamp | time | When the last invite was sent. |
| `mobile_platform` | string |  | Mobile platform recorded by the device status row. |
| `mobile_app_version` | string |  | Mobile app version recorded by the device status row. |
| `mobile_last_refresh_at` | timestamp | time | Last mobile refresh. |
| `mobile_last_refresh_ok` | bool |  | Whether the last mobile refresh succeeded. |
| `days_active_30d` | int |  | Number of distinct calendar days with at least one access token in the trailing 30 days. |
| `mobile_days_30d` | int |  | Distinct mobile session days in the trailing 30 days. |
| `desktop_days_30d` | int |  | Distinct non-mobile session days in the trailing 30 days. |
| `fresh_logins_30d` | int |  | Interactive sign-ins in the trailing 30 days. A refresh token with parent_id null is a fresh login; issued_at is derived from expires_at minus 14 days. |
| `first_seen_at` | timestamp | time | First session time for this team member. |
| `last_seen_at` | timestamp | time | Most recent session use or creation time. |
| `dashboard_messages_30d` | int |  | Dashboard messages sent in the trailing 30 days. |
| `task_changes_30d` | int |  | Task history rows in the trailing 30 days, including automated changes. |
| `calls_answered_30d` | int |  | Calls answered by this member in the trailing 30 days. Plain call forwarding does not set answered_by_subuser_id. |
| `copilot_sessions_30d` | int |  | Copilot sessions in the trailing 30 days. |
| `voice_device_count` | int |  | Registered voice devices. |
| `device_mix` | string |  | Mobile and desktop activity mix over the trailing 30 days. |
| `never_signed_in` | bool |  | True when no session exists for this member. |

Besty's caveats:

- Activity counters are a fixed trailing 30 day window and ignore time_range; a sessions row is a 20 minute access token, so use days active and fresh_logins, not row counts, for "logins"; calls_answered_30d is 0 on accounts whose numbers use plain call forwarding because call_logs.answered_by_subuser_id is never set on that path; task_changes_30d counts every ops_task_history row including automated status changes made through the app; online-now presence lives in Redis and is not available; push subscriptions (bt_mobile_app_push_notification_subscriptions) are per account, not per teammate, so they are not exposed here; mobile_* columns are null when the teammate never opened the mobile app.
- Deactivated members (state = deactivated) are excluded by default; pass filter.include_inactive=true to include them.

#### `export_team_sessions`

Export Besty access-token sessions for team members and account owners. Ask when a teammate or account owner accessed Besty and from which device.

Primary time field: `created_at`. Limits: raw row cap 10000, max window days 90, default window days 30. Join keys: `session_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `session_id` | string |  | Session UUID for a 20 minute access token. |
| `subuser_id` | string | assignee | Subuser UUID. Null means the account owner login. |
| `subuser_name` | string |  | Name of the logged-in team member. |
| `subuser_role` | string |  | Role of the logged-in team member. |
| `created_at` | timestamp | time | When this access token was created. |
| `last_used_at` | timestamp | time | When this token was last used. |
| `expires_at` | timestamp | time | When this access token expires. |
| `revoked_at` | timestamp | time | When this token was revoked, if ever. |
| `user_agent` | string |  | Client user-agent string. |
| `ip` | string |  | Client IP address. |
| `device` | string |  | Derived device class: ios, android, browser, or null when user_agent is null. |
| `is_revoked` | bool |  | True when revoked_at is set. |

Besty's caveats:

- One row is one 20 minute access token, not one login; count distinct days per subuser for activity; for fresh logins use export_team_logins.

#### `export_template_variables`

Bulk export of the listing-by-token matrix of stored messaging template values. Group rows by token to find listings with or without a value. PMS-derived tokens resolve from reservations at send time and do not appear here. Primary time field: none.

Limits: raw row cap 5000. Join keys: `variable_id`, `listing_id`, `listing_set_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `variable_id` | string |  | Stable variable row key. |
| `scope` | string |  | Variable scope: 'global', 'listing', or 'listing_set'. |
| `token` | string |  | Template token name as typed in a message. |
| `label` | string |  | Human-readable template variable label. |
| `value` | string |  | Text substituted at send time. |
| `has_value` | bool |  | Whether value is non-null and non-empty after trimming. |
| `external_listing_id` | string |  | PMS listing id for listing-scope rows. |
| `listing_id` | int |  | Besty listing id resolved from external_listing_id. |
| `listing_set_id` | string |  | Listing set id for listing-set rows. |
| `version_id` | int |  | Template variable version id. |

Besty's caveats:

- A listing with no row for a token is missing, not present with a null value. Join against export_listings to list absent listings.
- Global and listing-set rows have no listing_id and are dropped under a listing-scoped token.
- The listing join uses LATERAL LIMIT 1 because (user_id, pms_id) is not unique-indexed.

#### `export_thread_notes`

Bulk export of internal inbox notes written on guest threads. Guests never see these notes. Search matches note text. Primary time field is created_at.

Primary time field: `created_at`. Limits: raw row cap 5000, max window days 730, default window days 365. Join keys: `note_id`, `thread_id`, `reservation_id`, `listing_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `note_id` | int |  | Internal inbox note id. |
| `created_at` | timestamp | time | When the note was written. |
| `thread_id` | int |  | Guest thread containing the note. |
| `thread_url` | string |  | Canonical thread URL: https://app.getbesty.ai/message-dashboard?id=1&threadId=<thread_id>. |
| `reservation_id` | int |  | Besty reservation linked to the thread. |
| `external_reservation_id` | string |  | PMS reservation id linked to the thread. |
| `listing_id` | int |  | Besty listing linked to the reservation. |
| `author_subuser_id` | string | assignee | UUID of the team member who wrote the note. |
| `author_name` | string | assignee | Name of the team member who wrote the note. |
| `body` | string |  | Internal staff text. Guests never see inbox notes. |
| `guest_name` | string | contact | Guest display name from the linked reservation. |
| `thread_name` | string |  | Thread display name. |

Besty's caveats:

- Author is null for account-owner notes or notes written before subuser tracking.
- This is a small table, usually tens of rows per account.
- Listing is null when the thread has no linked reservation.

#### `export_threads`

Bulk export of bt_threads (host inbox), with reservation stay dates, listing ids, and `sentiment_label` derived from the raw integer (1=happy, 2=neutral, 3=unhappy; 0/null = never scored, surfaced as null + sentiment_is_default=true). `reservation_id` is the Besty internal int (LEFT JOIN — NULL when the linked reservation row is missing). Filter with `in_house_on` to require arrival_date <= date and departure_date > date, and use reservation_status to exclude cancelled stays. To look up by PMS-side string id, use `filter.external_reservation_ids`. Filter by Besty listing id with `filter.listing_ids`. Default filter excludes ghost threads (is_ghost_thread=false); pass filter.include_ghost=true to include them. Primary time field is last_message_at. ~80% of non-BFF threads have null sentiment — do NOT treat null as 'neutral'.

Primary time field: `last_message_at`. Limits: raw row cap 10000, max window days 365, default window days 90. Join keys: `thread_id`, `reservation_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `thread_id` | int |  | Besty thread id. |
| `thread_url` | string |  | Canonical thread URL: https://app.getbesty.ai/message-dashboard?id=1&threadId=<thread_id>. |
| `reservation_id` | int |  | Besty internal reservation id (LEFT JOIN — NULL when the linked reservation row is missing). |
| `arrival_date` | date | time | Arrival date (no TZ). Use for occupancy queries. |
| `departure_date` | date | time | Reservation departure date. |
| `guest_name` | string | contact | Reservation guest name. |
| `num_guests` | int |  | Booking party size. |
| `booking_channel` | string |  | Booking channel recorded on the reservation. |
| `reservation_status` | string |  | Reservation status recorded by the PMS. |
| `besty_listing_id` | int |  | Besty listing id linked to the thread reservation. |
| `pms_reservation_id` | string |  | Reservation id from the PMS. |
| `thread_type` | string |  | Thread type (reservation, inquiry, owner, etc.). |
| `is_archived` | bool |  | Host-archived flag. |
| `is_trash` | bool |  | Host-trashed flag. |
| `is_read` | bool |  | Inbox-read flag. |
| `is_ghost_thread` | bool |  | BT placeholder — typically excluded from analytics. Default filter is is_ghost_thread = false. |
| `resolved` | bool | completion | Set only when someone ticks the conversation on the Guest Sentiment page, which few accounts use: false does not mean unresolved. To learn whether a problem was resolved, read or label the conversation. |
| `ap_ended_convo` | bool |  | True if autopilot ended the conversation. |
| `has_no_contact_methods` | bool |  | True if the guest has no reachable channel. |
| `sentiment_raw` | int |  | Raw integer score: 0=never scored, 1=happy, 2=neutral, 3=unhappy. Always selected so the sentiment_label / sentiment_is_default transforms see it; agents can ignore in favour of those derived columns. |
| `sentiment_reason` | string |  | Short LLM-generated rationale for the sentiment score. |
| `summary` | string |  | LLM-generated longer summary of the thread. |
| `short_summary` | string |  | LLM-generated short summary. |
| `purpose_of_stay` | string |  | LLM-classified guest stay purpose. |
| `occasion_category` | string |  | Stored occasion bucket from the fixed taxonomy. Null when the thread was never analyzed. purpose_of_stay is raw evidence. Do not reclassify at query time. |
| `occasion_categorized_at` | timestamp | time | When the stored occasion category was assigned. |
| `pms` | string |  | Owning PMS for the linked reservation. |
| `status_raw` | string |  | Raw status for the linked reservation. |
| `arrival_at` | timestamp | time | Arrival timestamp (PMS-provided check-in time). |
| `revenue_amount` | float |  | Reservation total. PMS-varying inclusion of taxes/fees — treat as host-facing revenue figure, not nightly rate. Matches CRM revenue convention. |
| `status_category` | string |  | Canonical reservation status ('confirmed' \| 'active' \| 'canceled' \| 'inquiry' \| 'unknown'). Derived from (pms, status_raw) via the PMS dispatcher. Usable in aggregation dimensions/filters/measures. |
| `thread_name` | string |  | Host-set thread label (optional). |
| `created_at` | timestamp | time | Thread creation timestamp. |
| `last_message_at` | timestamp | time | Most recent message timestamp. |
| `last_incoming_message_at` | timestamp | time | Most recent incoming (guest) message timestamp. |
| `last_message_is_incoming` | bool |  | True if the most recent message was from the guest. |
| `snooze_until` | timestamp | time | Snooze deadline. Snoozed while this is in the future; a past value is a snooze that already elapsed, kept as the thread inbox sort key (BES-9471). Null if never snoozed. |
| `sentiment_label` | string |  | Canonical sentiment label ('happy' \| 'neutral' \| 'unhappy' \| null for never-scored). Derived client-side from sentiment_raw (1→happy, 2→neutral, 3→unhappy; 0/null→null). |
| `sentiment_is_default` | bool |  | True if sentiment_raw is the never-scored sentinel (0 or null). Use this to distinguish "never scored" from a real classification. |

Besty's caveats:

- Sentiment scale inversion: 1=happy, 2=neutral, 3=unhappy. Rows with sentiment=0 mean "never scored" — surfaced as sentiment_label=null + sentiment_is_default=true.
- ~80% of non-BFF threads have null sentiment in production. Do NOT treat null as "neutral".
- Default filter excludes is_ghost_thread=true. Pass filter.include_ghost=true to include.
- `reservation_id` is LEFT-JOINed — NULL when the linked reservation row is missing.
- occasion_category is populated only for analyzed threads, so category totals represent a share of analyzed stays.
- in_house_on uses an arrival-inclusive and departure-exclusive date window through the linked reservation.

#### `export_turnover_readiness`

One row per reservation arrival with open task counts, readiness, and the latest readiness event. The readiness_mode field names whether the count uses all tasks, resolved custom department criteria, or a PMS basis. Unresolved custom criteria fall back to all tasks with a warning; PMS readiness is returned as unknown because this tool does not read PMS clean status.

Primary time field: `arrival_date`. Limits: raw row cap 5000. Join keys: `reservation_id`, `external_reservation_id`, `besty_listing_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `reservation_id` | int |  | Besty internal reservation id. |
| `external_reservation_id` | string |  | Reservation id from the PMS. |
| `besty_listing_id` | int |  | Besty listing id for the reservation. |
| `readiness_mode` | string |  | Readiness basis: 'all', 'custom', or 'pms'. Missing settings default to 'all'. |
| `listing_name` | string |  | Listing display name. |
| `guest_name` | string | contact | Reservation guest name. |
| `arrival_date` | date | time | Reservation arrival date. |
| `departure_date` | date | time | Reservation departure date. |
| `reservation_status` | string |  | Raw reservation status from the PMS. |
| `open_required_task_count` | int |  | Open task count under the account readiness mode and configured department criteria. |
| `open_required_task_titles` | array |  | Titles of counted open tasks under the account readiness mode, capped at 100. |
| `is_ready` | bool |  | Readiness result when the account readiness basis is exact; null for PMS or unresolved criteria. |
| `last_readiness_event` | string |  | Newest listing readiness event for this reservation. |
| `last_readiness_event_at` | timestamp | time | Creation time of the newest listing readiness event. |

Besty's caveats:

- Readiness is derived from open tasks according to readiness_mode. 'all' counts every open task, while 'custom' uses the union of department values across every valid account config.
- listing_ready and listing_not_ready events only exist for accounts running the readiness feature. Tenant 2377 has 678 ready events and 93 not-ready events all time.
- A reservation with no tasks reads as ready only under the exact 'all' or resolved 'custom' basis. PMS mode and unresolved custom criteria return null readiness. A ready result is not proof that cleaning is complete.

#### `export_upsell_events`

Upsell purchases (the revenue side), one row per purchased item, covering ALL three revenue sources: standard upsells, damage waivers, and workflow-sold upsells. `source` (upsell_event \| damage_waiver \| workflow) says which, `upsell_type` carries damage_waiver / workflow_upsell for the latter two, and `product_name` is the invoice-ready item label. Rows are de-duplicated with the same key the revenue dashboard uses (reservation_id, product_name, revenue_amount), so a host acknowledging a purchase on the ROI page does not add a row; it sets `acknowledged`. Summing revenue_amount over is_acceptance rows therefore reconciles to summarize_upsell_revenue less the taxes and application fees that tool adds (and less admin-test rows unless filter.include_synthetic=true). This export is for per-reservation and per-item breakdowns; for THE single revenue number, summarize_upsell_revenue is still faster. Holds and failed payments are included as their own lifecycle rows (event_type). The lifecycle starts at hold/purchase — offers SENT to guests are NOT recorded here; for offer volume use export_upsell_offers. Default filter excludes admin-test rows (event_type_details->>'synthetic' = 'true'). Primary time field is created_at, the purchase time.

Primary time field: `created_at`. Limits: raw row cap 10000, max window days 730, default window days 365. Join keys: `upsell_event_id`, `reservation_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `upsell_event_id` | bigint |  | Event id. Positive for upsell_events rows (the id of the latest lifecycle row for the item); large negative values for damage_waiver and workflow rows, which are NOT keys into upsell_events. Returned as a string on the inline path because it is a bigint — compare as a string, not a number. |
| `reservation_id` | int |  | FK to reservations.id. |
| `upsell_type` | string |  | booking_booster \| early_checkin \| late_checkout \| custom_upsell \| damage_waiver \| workflow_upsell. |
| `source` | string |  | Which table the row came from — upsell_event \| damage_waiver \| workflow. Damage waivers and workflow-sold upsells are separate tables unioned in; filter on this to isolate or exclude them. workflow also includes reservation upsells a person created by hand, which carry upsell_type custom_upsell. |
| `product_name` | string |  | Item label suitable for an invoice line (e.g. "Damage Waiver"). Null on older rows with no productName. |
| `event_type` | string |  | Lifecycle state — payment_failed \| hold \| purchase_direct \| awaiting_payment \| hold_released \| purchase_from_hold_failed \| purchase_from_hold. Acknowledgement is not a state here; see acknowledged. |
| `acknowledged` | bool |  | True once the host marked the purchase done on the ROI page. Informational only; it does not affect revenue. Always false for damage_waiver rows. |
| `is_acceptance` | bool |  | True if the row represents a completed purchase (purchase_direct or purchase_from_hold). |
| `revenue_amount` | float |  | Revenue captured by this item, in currency. Rows are already de-duplicated to one per purchased item, so sum(revenue_amount) over is_acceptance rows reconciles to summarize_upsell_revenue less the taxes and application fees that tool adds. |
| `currency` | string |  | ISO 4217 currency for revenue_amount. |
| `offered_amount` | float |  | Price shown to the guest (if present). Always null for damage_waiver rows — a waiver has no separately offered price. |
| `off_platform_airbnb` | bool |  | True for off-platform Airbnb upsells. |
| `synthetic` | bool |  | Admin-test marker — true rows are excluded by default. |
| `event_type_details` | jsonb |  | Full event jsonb (variable shape per event type). |
| `created_at` | timestamp | time | Purchase time: the earliest purchase-state row for the item, not the time the host acknowledged it. Holds and failed payments carry their own time. |

Besty's caveats:

- DE-DUPLICATION: the raw upsell_events table is append-only and holds a second copy of every purchase the host acknowledged. This export collapses those with the same DISTINCT ON (reservation_id, product_name, revenue_amount) key the revenue dashboard and summarize_upsell_revenue use, keeping the latest lifecycle state and reporting the acknowledgement as `acknowledged`. The key has the same known side effects as on the dashboard: a hold collapses into the purchase_from_hold that follows it, and two genuine purchases of the same item at the same price on the same reservation collapse into one row.
- created_at is the earliest purchase-state time for the item. The dashboard and summarize_upsell_revenue apply their date window to each raw row instead, so a purchase acknowledged in a later month is dated to the purchase month here but may count in the acknowledgement month there. All-time totals agree; a narrow window straddling an acknowledgement may not.
- summarize_upsell_revenue additionally adds event_type_details taxAmount and applicationFeeAmount (minor units, /100), which this export does not expose, and it does not exclude synthetic rows. Those are the only differences from summing is_acceptance rows here.
- Rows come from three tables (see `source`): upsell_events, damage_waiver_records, and workflow-sold upsells. Damage waiver and workflow rows have NEGATIVE upsell_event_id values so ids stay unique across sources; they are not keys into upsell_events. list_recent_upsell_events uses a different negative-id scheme for the same rows; do not join the two on id.
- Damage waiver rows carry only a synthesized productName in event_type_details, so offered_amount and synthetic are null on them and off_platform_airbnb is always false.
- Damage waiver rows are always event_type 'purchase_direct' with acknowledged = false — the waiver table records completed waivers only, and acknowledgement cannot be performed on a waiver at all. Waiver HOLDS (damage_waiver_records.type = 'hold') are payment authorizations, not revenue, and are excluded entirely.
- Workflow rows: reservation upsells a person created by hand share the workflow tables and appear with source = 'workflow' but upsell_type = 'custom_upsell'. A free item (amount 0) is a purchase_direct; event_type 'hold' appears only when the upsell was configured as a hold. revenue_amount is amount_in_cents / 100 on every surface, which is wrong for zero-decimal currencies (JPY, KRW); no such purchases exist today.
- Default filter excludes admin-test rows (event_type_details->>'synthetic' = 'true'); host-facing dashboards currently leak these — see out-of-scope production ticket.
- offered_amount is derived from event_type_details->>'amountInCents' / 100.

#### `export_upsell_follow_ups`

One row per upsell follow-up about an earlier proactive offer. Use export_upsell_offers for delivery confirmation. Primary time field is created_at.

Primary time field: `created_at`. Limits: raw row cap 5000. Join keys: `follow_up_id`, `reservation_id`, `listing_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `follow_up_id` | int |  | Last-minute follow-up id. |
| `reservation_id` | int |  | Besty internal reservation id. |
| `listing_id` | int |  | FK to listings.id. |
| `arrival_date` | date | time | Reservation arrival date. |
| `type_raw` | string |  | Stored follow-up kind: late_check_out, early_checkin, or extra_nights. |
| `upsell_kind` | string |  | Canonical upsell kind mapped from type_raw. |
| `created_at` | timestamp | time | When the follow-up was created, stored as a UTC wall-clock value. |
| `send_after` | timestamp | time | Earliest time the reminder may be sent, stored as a UTC wall-clock value. |
| `sent_at` | timestamp | time | When the reminder was sent, stored as a UTC wall-clock value. |
| `invalidated_at` | timestamp | time | When the reminder was invalidated, stored as a UTC wall-clock value. |
| `status` | string |  | sent when sent_at exists; invalidated when invalidated_at exists before sending; otherwise pending. |
| `message` | string |  | Reminder text sent to the guest. |
| `offer_log_id` | int |  | Original proactive upsell log id. |
| `parent_offer_log_id` | int |  | Earlier proactive upsell log id that this reminder follows. |

Besty's caveats:

- Only reservations whose original proactive offer qualified for a reminder get a row.
- Empty on accounts that do not use last-minute follow-ups. This table has no delivery confirmation.

#### `export_upsell_funnel`

One row per reservation and canonical upsell kind that had an offer or purchase. Aggregate with the aggregation grammar by upsell_kind, month of activity_at, or listing_id; sum offers_sent, count purchased rows, and sum revenue_amount. Conversion is reservations purchased divided by reservations offered. Offers are send attempts, and purchase rows without offers can be reactive or manual. Primary time field is activity_at.

Primary time field: `activity_at`. Limits: raw row cap 10000, max window days 730, default window days 365. Join keys: `reservation_id`, `listing_id`, `upsell_kind`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `reservation_id` | int |  | Besty internal reservation id. |
| `listing_id` | int |  | FK to listings.id. Use for per-listing funnel breakdowns. |
| `pms_reservation_id` | string |  | PMS reservation id for every PMS despite the hostaway_reservation_id column name. |
| `arrival_date` | date | time | Reservation arrival date. |
| `departure_date` | date | time | Reservation departure date. |
| `channel` | string |  | Raw booking channel as written by the connector. |
| `upsell_kind` | string |  | Canonical upsell kind: booking_booster, early_checkin, late_checkout, or custom_upsell. |
| `offers_sent` | int |  | Offer send attempts for this reservation and kind. Zero means a purchase had no offer message. |
| `offers_delivered` | int |  | Offer messages with at least one successful delivery-channel record. |
| `first_offered_at` | timestamp | time | First offer timestamp, stored as a UTC wall-clock value. |
| `last_offered_at` | timestamp | time | Last offer timestamp, stored as a UTC wall-clock value. |
| `purchases` | int |  | Completed purchase events for this reservation and kind. |
| `purchased` | bool |  | True when at least one completed purchase exists. |
| `revenue_amount` | float |  | Sum of purchase revenue, excluding tax and application fees. |
| `revenue_currency` | string |  | Currency reported by the purchase events. |
| `first_purchased_at` | timestamp | time | First purchase timestamp, stored as a UTC wall-clock value. |
| `activity_at` | timestamp | time | First offer timestamp or, when no offer exists, first purchase timestamp. Use for monthly funnels. |

Besty's caveats:

- Offers and purchases have no foreign-key link. This joins them by reservation and canonical kind, so reminders collapse into one row and multiple purchases are counted together.
- Offers are send attempts. Use offers_delivered for a delivered-only rate.
- Custom upsells often have no offer messages. addedNightDates is empty in production, so nights sold are not available.
- Damage waivers, workflow purchases, synthetic test rows, and reservations not synced by Besty are excluded.
- Defaults to the last 365 days of activity_at when no time range is given; windows cap at 730 days.

#### `export_upsell_offers`

Upsell offer messages sent to guests (bt_messages rows with event_type 'offer'). Use this for "how many offers went out" / offer-volume questions — export_upsell_events has NO record of offers, its lifecycle starts at hold/purchase. Rows are send ATTEMPTS: the message row is written before delivery resolves, so failed/no-method sends are included; `delivery_confirmed` is true when a channel confirmed delivery (filter.delivered_only restricts to those, but excludes PMS-API direct sends which have no per-channel record). `upsell_kind` is the offer's event_subtype ('upsell', 'early_checkin', 'late_check_out', 'extra_nights', 'custom_upsells', plus campaign kinds like 'winback'). No FK to upsell_events — join analytically on reservation_id + kind + time window, minding reminder offers and the differing kind vocabularies. Primary time field is sent_at.

Primary time field: `sent_at`. Limits: raw row cap 5000. Join keys: `message_id`, `thread_id`, `reservation_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `message_id` | int |  | bt_messages primary key. |
| `thread_id` | int |  | FK to bt_threads.id. |
| `reservation_id` | int |  | Besty internal reservation id (LEFT JOIN via the thread — NULL when the linked reservation row is missing). |
| `upsell_kind` | string |  | Kind of upsell offered. Known values: 'upsell' (multi-item), 'early_checkin', 'late_check_out', 'extra_nights', 'custom_upsells'; other campaign kinds (e.g. 'winback', 'booking_booster') also appear. Open-ended string, not an enum. |
| `delivery_confirmed` | bool |  | True when at least one delivery channel confirmed the send (bt_messages_to_bt_methods.is_success). False is NOT proof of non-delivery: messages sent directly through the booking platform API have no per-channel record, and recent sends may still be pending. |
| `body` | string |  | The offer message text sent to the guest. |
| `offer_log_id` | string |  | Originating proactive_upsell_logs id for the offer send. |
| `sent_at` | timestamp | time | When the offer was sent. |

Besty's caveats:

- Offer sends only — purchases/revenue live in export_upsell_events; no FK links the two (analytical join on reservation_id + kind + window).
- Rows are send ATTEMPTS — the message row is created before delivery resolves, so failed/no-method sends are included. delivery_confirmed=true means a channel confirmed the send; false also covers PMS-API direct sends (no per-channel record), so it is not proof of non-delivery.
- upsell_kind vocabulary differs from export_upsell_events' upsell_type (e.g. extra_nights here vs booking_booster there).
- `reservation_id` is LEFT-JOINed via the thread — NULL when the linked reservation row is missing.

#### `export_widget_sessions`

Export website chat widget browser sessions. Ask how many visitors were blocked, which sessions reached a thread, and when they were active.

Primary time field: `created_at`. Limits: raw row cap 5000, max window days 730, default window days 90. Join keys: `widget_session_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `widget_session_id` | string |  | Website widget session id. |
| `installation_id` | string |  | Widget installation id. |
| `thread_id` | int |  | Besty thread id. Null until the visitor sends a message. |
| `status` | string |  | Widget session state, such as active or a completed browser visit. |
| `is_blocked` | bool |  | Whether the session is blocked. |
| `created_at` | timestamp | time | When the browser session started. |
| `last_activity_at` | timestamp | time | When the browser session last had activity. |
| `user_agent` | string |  | Visitor browser user-agent. |
| `ip` | string |  | Visitor IP address. |
| `guest_input` | jsonb |  | Guest input captured by the widget. |

Besty's caveats:

- Empty on accounts without the website chat widget installed; a session is a browser visit, not a conversation, and thread_id is null when the visitor never typed.

#### `export_winback_sends`

Export winback messages sent to past guests. Ask which past inquiries received a winback message and what discount was offered.

Primary time field: `sent_at`. Limits: raw row cap 5000, max window days 1825, default window days 365. Join keys: `winback_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `winback_id` | int |  | Winback send id. The id column is not the primary key. |
| `pms_reservation_id` | string |  | PMS reservation id for every PMS. The hostaway_reservation_id column is misnamed for non-Hostaway PMSes. |
| `pms_conversation_id` | string |  | PMS conversation id for every PMS. The hostaway_conversation_id column is misnamed for non-Hostaway PMSes. |
| `inquiry_id` | int |  | Inquiry id. |
| `discount` | int |  | Winback discount value stored as an integer percent. |
| `message` | string |  | Winback message text. |
| `sent_at` | timestamp | time | When the winback message was sent. |

Besty's caveats:

- Empty when winback is disabled (users.winback_enabled); a row means a message was sent, recovery is not tracked here; join reservations by pms_reservation_id to see if the stay rebooked.

#### `export_workflow_events`

Export the account workflow event ledger. Ask what events triggered workflows, when they happened, and whether a workflow handled them.

Primary time field: `created_at`. Limits: raw row cap 10000, max window days 365, default window days 7. Join keys: `event_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `event_id` | bigint |  | Workflow event id. |
| `event_type` | string |  | Event type. |
| `source_type` | string |  | Source type such as thread, reservation, or task. |
| `source_id` | string |  | Text id of the source row: bt_threads.id for thread, the reservation id for reservation, or ops_tasks.id for task. |
| `description` | string |  | Human-readable event description. |
| `outcome` | string |  | Routing outcome: trigger_only means no workflow picked it up; routed means a workflow instance handled it. |
| `created_at` | timestamp | time | When the event was recorded. |
| `payload` | jsonb |  | Full event payload. |

Besty's caveats:

- This is the activity ledger of the whole account (guest messages, escalations, reservations, tasks, reviews), not only workflow runs; volume is high (tens of thousands per month), so filter by event_types or narrow the window; listing is not stored on the row.

#### `export_workflow_instances`

Export workflow execution instances and their current state. Ask which workflows are waiting, completed, escalated, or discarded.

Primary time field: `created_at`. Limits: raw row cap 5000, max window days 730, default window days 90. Join keys: `instance_id`.

| Column | Type | Carries | What it is |
|---|---|---|---|
| `instance_id` | bigint |  | Workflow instance id. |
| `workflow_id` | bigint |  | Standard operating procedure id. |
| `workflow_name` | string |  | Workflow name. |
| `workflow_enabled` | bool |  | Whether the workflow is enabled. |
| `workflow_review_status` | string |  | Workflow review status. |
| `workflow_is_emergency` | bool |  | Whether this is an emergency workflow. |
| `mode` | string |  | Workflow mode, such as event_driven or sop. |
| `status` | string |  | Current workflow instance status, such as completed, waiting_event, escalated, discarded, or active. |
| `trigger_event_type` | string |  | Event type that started the instance. |
| `thread_id` | int |  | Besty thread id. |
| `current_node_id` | string |  | Current workflow node id. |
| `waiting_type` | string |  | Waiting state type. |
| `waiting_event_type` | string |  | Event type being awaited. |
| `waiting_source_type` | string |  | Source type being awaited. |
| `pingpong_turn_count` | int |  | Number of ping-pong turns. |
| `conversation_summary` | string |  | Conversation summary. |
| `created_at` | timestamp | time | When the instance was created. |
| `updated_at` | timestamp | time | When the instance last changed. |
| `is_waiting` | bool |  | True when status is waiting_event. |
| `waiting_since` | timestamp | time | Updated time when waiting for an event, otherwise null. |

Besty's caveats:

- discarded means the first turn was thrown away before any state was written (zombie prevention in backend/sidekick/types.ts), so there is no discard reason to show; a row stays waiting_event until the event it waits for arrives, so age alone does not mean stuck; check waiting_event_type against the events in export_workflow_events.
