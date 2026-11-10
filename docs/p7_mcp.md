# P7: AI apps over MCP, and the AI-action settings (as built, 2026-11-10)

A practice user connects their own AI app (Claude first, ChatGPT second;
Gemini and Grok later) to Execs NOW HQ over MCP and works with the practice's
data from there, on their own subscription. The app's own AI actions keep
running on the practice's Claude key. Scheduled and rule-fired actions always
use the key; user-started actions can run either way.

## Pieces

| Piece | Where | Served by |
|---|---|---|
| OAuth 2.1 authorization server | `apps/aiconnect/oauth.py`, `templates/aiconnect/` | web (`execs-now-hq`), at `PUBLIC_BASE_URL` |
| MCP server (resource server) | `apps/aiconnect/mcp_server.py`, `apps/aiconnect/tools.py` | the `mcp` service: `config/mcp_asgi.py`, `scripts/start_mcp.sh`, `railway/mcp.json` |
| Connected AI apps, AI actions, tiers | `apps/aiconnect/views.py`, `apps/tenancy/ai_actions.py`, `apps/aiconnect/models.py` (`ModelTier`) | web |
| Screens | `frontend/src/components/AiApps.tsx`: Profile, Settings → AI, Practices area, "Do this in your AI" | web |

**A separate service, not mounted in web.** Web is gunicorn with synchronous
workers. The MCP SDK's server is an ASGI (Starlette) app, so it runs under
uvicorn in its own service from the same image, settings and database. It is
**stateless and answers in JSON** (`stateless_http=True`, `json_response=True`),
so there are no sticky sessions or held-open streams and it scales by
replicas. Like the worker, it **waits** with a migration unapplied and never
migrates.

Settings: `MCP_PUBLIC_URL` (default `https://mcp.getexecutivesnow.com`; local
`http://localhost:8110`). The resource is `{MCP_PUBLIC_URL}/mcp`. The issuer is
`PUBLIC_BASE_URL`.

## Server

- Streamable HTTP at `/mcp`, official Python SDK `mcp` 2.3.0, current protocol
  revision `2026-07-28`; the older handshake revisions are still answered.
- `/.well-known/oauth-protected-resource/mcp`: the resource and the app as its
  authorization server. A request without a valid token is a 401 whose
  `WWW-Authenticate` names it.
- DNS-rebinding protection: only the MCP host is accepted.
- Each tool runs off the event loop in the connection's practice, in one
  transaction, and writes one Activity line: `ai_app.tool`, with the tool name
  and the record ids it touched, never content.

## Sign-in (OAuth 2.1)

- `/.well-known/oauth-authorization-server` (RFC 8414).
- `/oauth/register`: dynamic client registration (RFC 7591). **Public clients
  only** (`token_endpoint_auth_method: none`). Redirects must be https, or http
  to localhost. 30 an hour per address.
- `/oauth/authorize`: authorization code, **PKCE S256 only**.
  - Signed out: the page asks for the normal practice sign-in and keeps its own
    address. The app shell sends the person back after any sign-in
    (`config/spa.py`, 15 minutes).
  - The page names the practice, the role ("Acting as"), the AI app, what it
    can and never can do, and the line: *"{app}'s provider will receive the
    data of {practice} that you choose to work with there, under your
    practice's own agreement with that provider."*
  - **Client users are refused outright**, and so is someone acting as
    another person.
- `/oauth/token`:
  - **Access tokens last an hour.** Refresh tokens last **thirty days and are
    rotated**: each use returns a new pair.
  - A spent refresh token or code used again revokes the connection.
  - Every token is bound to the user, practice and role through its
    connection, and to the resource.
  - A role change or a revoked membership stops it.
- **Resource indicators** (RFC 8707): any `resource` other than the MCP
  server's own is `invalid_target`.
- `/oauth/revoke` (RFC 7009) disconnects the app.
- Tokens and codes are stored as SHA-256 digests only.

**Connections.** One active connection per person, practice and AI app;
connecting again renews it. Profile → "Connected AI apps" lists the person's
own, with the app name, when it connected, when it was last used, and Revoke.
Settings → AI lists the practice's: all of them for the owner, their own for
anyone else. The owner can revoke anyone's. Connected and disconnected are
Activity lines too.

## Tools

Every tool runs as the connection's person through the same scoping the web
app uses: the querysets, viewset methods and serializers its screens call.

**Read**
- `practice_summary` (Home's tiles)
- `list_companies`
- `company_overview`: people, goals and projects, open tasks, invoices
  summary, documents and their states, scorecard summary, latest mail
  subjects
- `search_contacts`, `get_contact`
- `list_pipelines`
- `list_tasks`: status, company, assignee "me", due before, overdue
- `list_goals`
- `list_notes`: **PIN-locked notes are left out entirely**
- `scorecard_readings`: company and window
- `pending_meeting_proposals`
- `sending_queue`
- `digest_drafts`
- `invoices_summary`: practice owner and associates only
- `documents`
- `list_strategy_sessions`, `strategy_session`: sections and map

**Write.** Each write lands where a person approves, or as an internal record,
and is marked as made by an AI app:

| Tool | Lands | Marker |
|---|---|---|
| `create_task` | an internal task (client sees it only if shown), owned by the person | `TaskUpdate.Source.AI_APP` |
| `add_note` | a note on a contact or a company | `Note.Source.AI_APP` |
| `draft_email` | the Sending queue, **pending approval**, from the person's default mailbox (`outbox.create_manual_draft`) | `source_type="ai_app"`, "From an AI app" |
| `propose_map_rows` | the session's tray, proposed (owner and associates) | `StrategyMapRow.from_ai_app` |
| `enter_kpi_reading` | the reading, under the entry form's rules | source "Entered by AI" |
| `create_digest_draft` | Digests, **pending approval** (owner and associates) | `Digest.from_ai_app` |

**Never.** No tool sends mail, moves or charges money, signs, deletes,
changes a pipeline stage, or changes settings or connections.

**Prompts.** `weekly_note` (a company), `prep_contact` (a contact),
`whats_late`.

## Settings → AI

The tab once called "AI usage" is now "AI". It has two new parts above the
key, credits and usage.

**AI apps.** The connector URL with Copy, the steps for Claude and for
ChatGPT, and the connected apps.

**Actions.** Every AI action (`apps/tenancy/ai_actions.ACTIONS`, 23), with
two columns the owner changes:

- **Runs in**: "In the app with my key" or "In my AI app". An action whose
  records the MCP server cannot read, or that only runs on a schedule or a
  rule, shows "In the app" fixed: finance, personal, the meeting notes reader,
  digest prose and owner classification. An action that is also scheduled or
  rule-fired keeps those runs in the app whatever is chosen.
- **Model tier**: Fast, Standard or Deep.

Defaults:

- **Fast**: bank-line sorting (Personal), and meeting owner and contact
  matching.
- **Standard**: digests, the weekly note, Explain this scorecard, session
  prep, referral touches, note summaries, goal narratives, path notes, the
  strategy document, and the explainers.
- **Deep**: strategy map drafting and consolidation, the mirror, the
  diagnostic, Review with Claude (both forecasts), and the statement-PDF
  reader.

**"Do this in your AI".** An action set to "In my AI app" swaps its in-app
button for "Do this in your AI". That opens the prompt to paste, naming the
record by name and id. It is wired on the scorecard (Explain, weekly note),
the strategy session (prepare, draft rows, consolidate, mirror, diagnostic,
paths, document words), the goal narrative, the note summary, and referral
touches.

**Tiers.** One platform table (`ModelTier`): Fast `claude-haiku-5-5`, Standard
`claude-sonnet-5-5`, Deep `claude-opus-5-5`, each with its price. Haiku has no
server-side refusal fallback, so its row has the fallback off. The platform
owner edits the table in the Practices area ("AI model tiers") without a code
change. `claude.complete_with_call` resolves the model per practice and
purpose. The price before a click averages the practice's own calls on the
model in use now.

## Open, and the simplest readings taken

- **No per-run "use a stronger model" choice existed** to keep. Only `effort`
  varies per call, and that is unchanged. The tier is now the model choice.
- **Not AI today, so not rows:** reply filing, follow-ups, introductions,
  thank-yous, and business bank-line categories. Contact matching is
  deterministic. The Fast row named for it is meeting owner classification.
- **"Runs in: In my AI app" is a screen choice.** The in-app endpoint still
  answers if called directly.
- **Tasks, notes and KPI readings have no approval queue** in the app. They are
  created internal and marked; email and digests wait for approval, and map
  rows sit in the tray.
- **The digest draft is a one-off** in the AI app's words: weekly, its send
  window the next one. It claims no task updates, so the scheduled digest still
  reports them.
- **Demo:** allowed. A demo visitor connects their own copy (the address is on
  Profile, since the demo hides Settings → AI), and mail stays redirected. The
  demo needs its own `mcp` service and `MCP_PUBLIC_URL`.
- **Google user data** (mail subjects in `company_overview`) can now reach an
  AI app the user connects. Weigh it against the Limited Use wording before
  Google verification.
- **The ChatGPT steps** follow its custom-connector flow as described; they
  have not been run against ChatGPT here.

## Proof

- `tests/test_ai_apps_oauth.py` (26): registration, the PKCE flow, refusals,
  rotation, revocation, isolation.
- `tests/test_ai_apps_mcp.py` (11): the SDK's own client against the ASGI app.
  - a 401 with the resource metadata, and tools and prompts listed;
  - role scoping on invoices, companies and notes;
  - each write in its queue with its marker;
  - revocation ending access;
  - Activity lines.
- `tests/test_ai_actions.py` (10): tiers, settings, the call on its tier, and
  every read tool for each staff role.
- `frontend/src/components/AiApps.test.tsx` (6).
- **MCP Inspector 2.14.0**, command-line mode, against a local `mcp` service
  and a real token from this flow:
  - `tools/list` returned 23 tools and `prompts/list` 3;
  - `list_companies`, `list_tasks` (overdue), `company_overview`,
    `practice_summary` and `create_task` all answered;
  - an out-of-scope id was refused in words;
  - a made-up token got a 401, and the Inspector started its own OAuth.
