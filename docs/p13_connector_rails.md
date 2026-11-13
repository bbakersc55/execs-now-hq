# P13 — the connector rails (as built, 2026-11-12)

Three ways any system can feed a scorecard KPI without a connector built for
it. They are in the base app for every practice, whatever Command Centers are
on. In the feed buttons on a tile's back, they come under **"Connect anything"**
after the named connectors (Sheet, Track, HubSpot, Besty, Google reviews):
**Webhook**, **Any MCP server**, **Any API**, and then **Request a connector**.
All three open one dialog with a tab for each rail.

Code: `apps/scorecard/rails.py` (the rails), `apps/scorecard/safe_http.py`
(every outbound request), `apps/scorecard/rails_ai.py` (Claude's proposal),
`apps/scorecard/views_rails.py` (the routes, listed in its docstring), and
`frontend/src/components/ScorecardRails.tsx`.

**Who does what.**
- **Setting a feed** on a KPI is for the practice owner and associates, like
  the rest of the scorecard's setup. Assistants and client users are refused.
- **Making an MCP or API connection** is for the practice owner alone, as
  with Besty and HubSpot.
- **Every company route** finds the company through `access.company_for`, so
  another practice's company is a 404.
- **A per-person KPI or a computed one** takes no rail: a rail feeds one
  number for the company.

## 1. Webhook

- **The KPI's own address**, `POST /webhooks/kpi/<token>/`.
  - The token (`kh_` + 32 random characters) is shown once, when the address
    is made, with a ready-to-copy test.
  - It is stored only as a SHA-256 hash, with its last four characters as a
    hint.
  - **Rotate** makes a new address. The old one is then a 404.
- **What it accepts.** One merged set of names and values:
  - query parameters;
  - then a JSON object, or form fields, on top.
  - `value` is required; `date` (YYYY-MM-DD, or a date-time read in the
    practice's zone) and `note` are optional.
  - With no date, the post counts for today.
  - The note is kept on the delivery record (a reading has no note field).
- **Another system's own payload.** The feed can hold a **path to the value**
  and a **path to the date**, as dotted paths with `[n]` for a list item
  (`data.count`, `rows[0].value`). A JSON array body is read through the paths.
- **Replace or add.**
  - *Replace* (the default) makes the post the period's reading.
  - *Add* adds it to the period's webhook reading, for one event per post.
- **A reading typed by hand is never replaced.** The post answers "kept" and
  says why. A date in a period that hasn't started is refused.
- **The company's address**, `POST /webhooks/company/<token>/`, takes
  `{"kpi": "<key>", "value": …}`.
  - A KPI's key is its name in lower case with `_` between the words. The
    webhook tab shows it.
  - Only KPIs whose feed is an active webhook take posts there.
  - The address is made, and rotated, from the same tab, and shown once.
- **Rate limits** (all answered 429 in words, counted in the database):
  - **per sender** (the address the proxy saw, `TRUSTED_PROXY_HOPS`): 120
    posts a minute across every webhook address;
  - **per sender, to addresses that don't exist:** 10 a minute. Past that,
    everything from that sender is refused until the minute is out, its real
    addresses included. A made-up address never gets a counter of its own, so
    trying random addresses can't grow the counter table (added 2026-11-13);
  - **per real address:** 60 posts a minute.
  - Each new minute deletes the finished minutes' counters of all three.
- **The last 20 deliveries** are listed, per KPI and for the company's
  address. Each shows when it came, what was done ("Week of Nov 2: saved, now
  14.", or the refusal), and what was received.
- **The Test panel:**
  - a `curl` example to copy;
  - Zapier steps (Webhooks by Zapier, POST, JSON);
  - Make steps (HTTP, Make a request, raw JSON).
- **Source:** readings say "From a webhook". The tile's back reads "From a
  webhook, as each post arrives".

## 2. Any MCP server

- **A company's connections** to other vendors' MCP servers: a name, the
  server's https address, and a token (sent as `Bearer`) or headers given as
  JSON.
  - The client speaks Streamable HTTP: `initialize`,
    `notifications/initialized`, `tools/list`, `tools/call`. The answer may be
    JSON or an SSE stream. The session id the server gives is sent back.
- **Test connection** lists the server's tools (name and description) and
  keeps them on the connection. A failure is said in words.
- **Mapping a number.** The person describes the number they want. Claude
  proposes three things:
  - the tool;
  - its arguments, with period placeholders;
  - the path to the number in the tool's answer.
- **How the proposal runs:**
  - Claude uses the practice's own key, on the Standard tier.
  - The price is shown on the button before anything is spent.
  - There is a cap of 20 proposals a day, and the month's AI budget applies.
  - Claude's one-sentence reason is shown with the proposal.
- **The live preview.** The app runs the proposed call once, for the last
  closed period, and shows the number found, or "no number at that path", and
  an excerpt of the answer.
  - **Confirm and read it** is only enabled when the preview found a number.
  - The confirm (`PUT`) runs the preview again on the server and refuses to
    save if it finds no number.
- **Set by hand.** The tool, the arguments and the path are plain fields. A
  person can type them, edit Claude's, preview and confirm. Editing the tool
  clears the "proposed by Claude" mark.
- **The nightly read** is the saved tool call with the placeholders filled.
  It is deterministic and uses no AI.
  - It runs with the other feeds in `read_feeds`, once a day per feed.
  - The first read covers 13 closed periods, later reads 2, plus the open
    period when the KPI reads it.
- **Source:** readings say "From an MCP server".

## 3. Any API

- **A company's API connections:**
  - a name;
  - an https base address;
  - a secret, placed one of three ways: **in a header** (named, e.g.
    `Authorization`), **as basic sign-in** (`user:password`), or **as a query
    key** (named, e.g. `api_key`).
- **A KPI's feed:**
  - a GET or a POST;
  - a path under the base address;
  - a query (JSON names and values) and, for a POST, a JSON body;
  - placeholders anywhere in the path, query or body;
  - the path to the value in the JSON answer.
  - The path cannot leave the connection's address: a `..` or another host is
    refused.
- **Preview, then Save and read it**, as for MCP. The nightly read is the same
  request.
- 401 and 403 answers say "The API refused the secret. Check it on the
  connection."
- **Source:** readings say "From an API".

**Placeholders** (both MCP and API):
- `{period_start}` and `{period_end}` (YYYY-MM-DD);
- `{period_start_iso}` and `{period_end_iso}` (UTC date and time);
- `{year}`, `{month}` (two digits) and `{quarter}`.

## Safety (MCP and API: `safe_http.fetch`)

- **https only.** No user name or password in the address.
- **Public addresses only.** These are refused:
  - private, loopback, link-local, multicast, reserved and unspecified
    addresses;
  - IPv6 site-local addresses;
  - the cloud metadata addresses (169.254.169.254, 169.254.170.2,
    100.100.100.200, fd00:ec2::254) and their names;
  - anything not global.
  - The check happens **after DNS**, on every resolved address, and **again on
    connect**, against the socket's own peer address. That catches DNS
    rebinding.
  - A connection to a refused address is refused when it is made, as well as
    when it is read.
- **Redirects:** at most three, and only on the same host. A redirect to
  another host is refused and said.
- **Caps:**
  - 10 s per read, 25 s overall;
  - 1 MB per answer. A larger answer is refused, and the KB is said.
- **Secrets** are encrypted with the app's key (as the other connections'
  are), never sent to the browser again, and shown only as their last four.
- **Every failure is recorded on the feed in plain words:**
  - `last_error`, and since when;
  - shown on the tile's back to the practice and the reading owner;
  - shown in the rail's tab.
  - Nothing already read is deleted by a failure.

## Request a connector

The **Request a connector** link under "Connect anything" opens a short form:
- the system;
- the numbers wanted;
- the client, filled with the company's name.

It lands in the platform owner's **Feedback**:
- as a *connector request*, a new `kind` on Feedback;
- labelled System, Numbers wanted and Client in the list and in the notice
  email ("Connector request from …").

## Data (migrations, additive)

- **`scorecard` 0017_connector_rails** creates seven tables:
  - `kpi_webhook_feed` (one per KPI; `secret_hash` unique);
  - `company_kpi_webhook` (one per company);
  - `kpi_webhook_delivery`;
  - `kpi_mcp_connection` and `kpi_mcp_feed` (one per KPI);
  - `kpi_api_connection` and `kpi_api_feed` (one per KPI).

  It also adds three feed kinds and three reading sources. Those are choices
  only, with no SQL.
- **`platform` 0002_feedback_kind:**
  `ALTER TABLE "feedback" ADD COLUMN "kind" varchar(12) DEFAULT 'feedback' NOT NULL`.

## Choices made where the brief was open

1. **The company's address** writes only KPIs that already have an active
   webhook feed. Any other key is refused. Turning a feed on is a choice made
   per KPI.
2. **A note** is kept on the delivery record, since a reading has no note
   field.
3. **No rail ever replaces a reading typed by hand.** It answers "kept"
   instead. A future period is refused.
4. **Per-person and computed KPIs are refused** by all three rails.
5. **On the demo**, outbound connections are refused: adding, testing,
   previewing and reading. Webhooks are inbound, so the demo accepts posts to
   them.
6. **Claude's MCP mapping** runs on the Standard tier, with 20 a day.
   - Its estimate uses 5,000 tokens in and 700 out.
   - It is registered as the AI action `rail_mcp_map`, fixed in the app.
7. **Connections are the practice owner's alone**, to add and to remove;
   associates see them and pick one. Feeds are the owner's and associates'.
8. **The rate limits** are 120 a minute per sender, 10 a minute per sender
   to addresses that don't exist, and 60 a minute per real address, kept in
   the database (`too_many_shared`), so they hold across web workers.
9. **The MCP token is sent as `Bearer`**; any other scheme is given as
   headers.
10. **The rails are on every scorecard**, the practice's own included,
    wherever the named connectors are offered.
11. **The preview reads the last closed period.** The open one is read
    nightly only when the KPI is set to read it.
12. **Stop this feed** returns the KPI to entry by hand and keeps its
    readings. A connection that is removed stops its feeds.

## Proof

- **`tests/test_rails.py`** has 29 tests, some parametrized:
  - **Webhook:**
    - shown once and stored hashed;
    - JSON, form and query styles;
    - replace versus add;
    - paths into another system's payload;
    - hand reading kept;
    - four bad posts, each refused in words and listed;
    - rotation retires the old address;
    - the rate limit;
    - 20 deliveries kept;
    - the company's key;
    - per-person KPIs and another practice refused.
  - **MCP**, against a fake Streamable HTTP server:
    - Test lists the tools and never shows the token;
    - Claude proposes, the preview is live, and nothing saves until
      confirmed;
    - the nightly read is deterministic with no AI call;
    - an empty path is said.
  - **API**, against a fake server:
    - the secret is placed by each kind;
    - a failure is said on the feed;
    - the path is confined under the base address (another host, `..`, and a
      sibling such as `/v1evil` next to `/v1`).
  - **Safety**, each rule with a breaking test:
    - nine refused addresses;
    - a name resolving to a private address;
    - rebinding on connect;
    - a redirect off the host;
    - a same-host redirect followed;
    - the size cap and the time cap;
    - private connections refused when made;
    - JSON paths.
  - **The demo** refusing, and **a connector request** in Feedback.
- **`frontend/src/components/ScorecardRails.test.tsx`** has 9 tests:
  - the webhook address shown once with the Zapier and Make steps;
  - deliveries, Rotate and Stop;
  - MCP: the price before Claude, and nothing saved until Confirm;
  - MCP set by hand, and a failed Test in words;
  - the API GET previewed then saved;
  - the secret in a password field;
  - an associate sees connections but can't add or remove one;
  - the demo's words;
  - Request a connector.
- **`Scorecard.test.tsx`** checks that "Connect anything" comes after the
  named connectors and opens the rail.
- **`tests/test_demo_seed.py`** checks that the demo has one KPI on each rail,
  with readings written through the rails' own code.

## The demo

Pied Piper Compression's scorecard has a **Connected systems** page with one
KPI on each rail. The readings are written by the rails' own code from
stand-ins. No call leaves the app and no Claude is used.

- **New signups** (weekly), from a webhook:
  - twelve weekly posts, as a Zap would send them, and one refused post (a
    Zap that sent its own field name), among its deliveries;
  - the address's token is kept nowhere, as a real one once shown; Rotate
    shows a new one.
- **Support tickets open** (weekly, lower is better), from **Help desk**, an
  MCP server:
  - the connection lists three tools;
  - the feed calls `count_tickets` with `{"status": "open", "as_of":
    "{period_end}"}` and reads `total`, marked as proposed by Claude.
- **Monthly recurring revenue** (monthly), from **Billing API**: a GET of
  `/metrics/mrr?month={year}-{month}`, with the value at `data.mrr`.

On the demo, adding, testing or previewing a connection says that the demo
never connects to another system.
