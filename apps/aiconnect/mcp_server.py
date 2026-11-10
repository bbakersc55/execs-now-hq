"""The Execs NOW HQ MCP server (P7, docs/p7_mcp.md).

Streamable HTTP at `{MCP_PUBLIC_URL}/mcp`, stateless and JSON-answered (no
session state, so any replica answers any request), on the SDK's current
protocol revision. It is a resource server only: tokens come from the app's
own authorization server (`oauth.py`), named in the protected-resource
metadata the SDK serves at `/.well-known/oauth-protected-resource/mcp`.

Every tool is a thin wrapper over `tools.py`, run off the event loop inside
the connection's practice, in one transaction, with an Activity line after.
Served by `config/mcp_asgi.py` (the `mcp` service).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import close_old_connections

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from apps.aiconnect import tools as T

log = logging.getLogger(__name__)

INSTRUCTIONS = (
    "Execs NOW HQ is a fractional executive's practice: companies, contacts, pipelines, "
    "goals, projects and tasks, notes, scorecards, meetings, the Sending queue, digests, "
    "invoices, documents and strategy sessions. You act as the person who connected you, "
    "with their role, and see what they see. Reads are live. Writes only draft: a task or "
    "note marked as made by an AI app, an email waiting in the Sending queue, Strategy Map "
    "rows in a session's tray, a KPI reading marked entered by AI, a digest waiting for "
    "approval. Nothing here sends mail, moves money, signs, deletes, changes a pipeline "
    "stage or changes settings. Ids come from other tools' answers; never invent one.")

READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
DRAFT = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False,
                        open_world_hint=False)


class ConnectionTokens:
    """The SDK's TokenVerifier, against the app's own token table."""

    async def verify_token(self, token: str) -> AccessToken | None:
        connection, row = await sync_to_async(_lookup)(token)
        if connection is None:
            return None
        return AccessToken(
            token=token, client_id=connection.client.client_id, scopes=[T_SCOPE],
            expires_at=int(row.expires_at.timestamp()), resource=row.resource,
            subject=str(connection.user_id),
            claims={"iss": settings.OAUTH_ISSUER_URL, "connection": str(connection.pk),
                    "practice": str(connection.tenant_id), "role": connection.role})


T_SCOPE = "practice"


def _lookup(token):
    from apps.aiconnect.oauth import principal_for

    try:
        return principal_for(token)
    finally:
        close_old_connections()


def _connection_now():
    """The connection of the token on this request, checked again (a revoke
    between two calls of one request stops the second)."""
    from apps.aiconnect.models import AiAppConnection
    from apps.aiconnect.oauth import connection_usable

    token = get_access_token()
    claims = (token.claims or {}) if token else {}
    connection = (AiAppConnection.all_objects
                  .select_related("membership__tenant", "user", "client")
                  .filter(pk=claims.get("connection")).first())
    if connection is None or not connection_usable(connection):
        raise ToolError("This AI app is no longer connected. Connect it again from the AI app.")
    if token.expires_at and token.expires_at < int(time.time()):
        raise ToolError("The sign-in has expired; the AI app should refresh it.")
    return connection


def _run_sync(name: str, fn, kwargs: dict):
    from django.db import transaction

    from apps.tenancy.context import tenant_context

    connection = _connection_now()
    principal = T.Principal(connection)
    ok = False
    try:
        with tenant_context(connection.tenant_id), transaction.atomic():
            result = fn(principal, **kwargs)
        ok = True
        return result
    except T.ToolRefused as exc:
        raise ToolError(str(exc)) from exc
    except ToolError:
        raise
    except Exception as exc:
        log.exception("MCP tool %s failed", name)
        raise ToolError("Something went wrong in Execs NOW HQ; nothing was changed.") from exc
    finally:
        T.record_call(connection, name, principal.touched, ok=ok)
        # Off a request, Django leaves connection hygiene to us (CONN_MAX_AGE).
        close_old_connections()


async def run(name: str, fn, **kwargs) -> Any:
    return await sync_to_async(_run_sync)(name, fn, kwargs)


def build() -> MCPServer:
    server = MCPServer(
        name="Execs NOW HQ", title="Execs NOW HQ", instructions=INSTRUCTIONS, version="1.0",
        website_url="https://www.execsnowhq.com",
        token_verifier=ConnectionTokens(),
        auth=AuthSettings(issuer_url=settings.OAUTH_ISSUER_URL,
                          resource_server_url=settings.MCP_RESOURCE_URL,
                          validate_token_resource=True, required_scopes=[T_SCOPE]),
    )

    # ------------------------------------------------------------- read
    @server.tool(annotations=READ)
    async def practice_summary() -> dict:
        """The practice at a glance: Home's tiles for you (what's due, late, waiting)."""
        return await run("practice_summary", T.practice_summary)

    @server.tool(annotations=READ)
    async def list_companies(query: str = "", clients_only: bool = False,
                             limit: int = 50) -> dict:
        """Companies you can see, by name. clients_only for client companies."""
        return await run("list_companies", T.list_companies, query=query,
                         clients_only=clients_only, limit=limit)

    @server.tool(annotations=READ)
    async def company_overview(company_id: str) -> dict:
        """One company's full picture: people, goals and projects, open tasks, invoices
        summary, documents and their states, scorecard summary. No mail from Gmail or
        Microsoft 365."""
        return await run("company_overview", T.company_overview, company_id=company_id)

    @server.tool(annotations=READ)
    async def search_contacts(query: str, limit: int = 25) -> dict:
        """Contacts by name, email address or company name."""
        return await run("search_contacts", T.search_contacts, query=query, limit=limit)

    @server.tool(annotations=READ)
    async def get_contact(contact_id: str) -> dict:
        """One contact: details, types, pipeline stages, and their recent timeline."""
        return await run("get_contact", T.get_contact, contact_id=contact_id)

    @server.tool(annotations=READ)
    async def list_pipelines() -> dict:
        """The practice's pipelines with their stages and how many contacts are in each."""
        return await run("list_pipelines", T.list_pipelines)

    @server.tool(annotations=READ)
    async def list_tasks(status: str = "", company_id: str = "", assignee: str = "",
                         due_before: str = "", overdue: bool = False,
                         limit: int = 100) -> dict:
        """Tasks you can see. status: "open", "done" or a status; assignee: "me";
        due_before: YYYY-MM-DD; overdue: past due and not done."""
        return await run("list_tasks", T.list_tasks, status=status, company_id=company_id,
                         assignee=assignee, due_before=due_before, overdue=overdue,
                         limit=limit)

    @server.tool(annotations=READ)
    async def list_goals(company_id: str = "") -> dict:
        """Goals with their projects, for one company or all you can see."""
        return await run("list_goals", T.list_goals, company_id=company_id)

    @server.tool(annotations=READ)
    async def list_notes(contact_id: str = "", company_id: str = "", query: str = "",
                         limit: int = 25) -> dict:
        """Notes you can open, newest first. PIN-locked notes are never included."""
        return await run("list_notes", T.list_notes, contact_id=contact_id,
                         company_id=company_id, query=query, limit=limit)

    @server.tool(annotations=READ)
    async def scorecard_readings(company_id: str, window: str = "this_week",
                                 from_date: str = "", to_date: str = "") -> dict:
        """A company's scorecard KPIs and readings for a window (this_week, last_week,
        this_month, last_month, last_13_weeks, or custom with from_date and to_date)."""
        return await run("scorecard_readings", T.scorecard_readings, company_id=company_id,
                         window=window, from_date=from_date, to_date=to_date)

    @server.tool(annotations=READ)
    async def pending_meeting_proposals() -> dict:
        """Meetings waiting in the review queue, with what each proposes."""
        return await run("pending_meeting_proposals", T.pending_meeting_proposals)

    @server.tool(annotations=READ)
    async def sending_queue() -> dict:
        """Email waiting in the Sending queue for approval, and how many digests wait.
        Replies in a mail thread are counted, not shown."""
        return await run("sending_queue", T.sending_queue)

    @server.tool(annotations=READ)
    async def digest_drafts() -> dict:
        """Progress digests waiting for approval, with their words."""
        return await run("digest_drafts", T.digest_drafts)

    @server.tool(annotations=READ)
    async def invoices_summary(company_id: str = "", status: str = "") -> dict:
        """Invoices and their totals (practice owner and associates only)."""
        return await run("invoices_summary", T.invoices_summary, company_id=company_id,
                         status=status)

    @server.tool(annotations=READ)
    async def documents(company_id: str = "") -> dict:
        """Documents for signature and where each stands."""
        return await run("documents", T.documents, company_id=company_id)

    @server.tool(annotations=READ)
    async def list_strategy_sessions(limit: int = 50) -> dict:
        """Strategy sessions you can see, newest first."""
        return await run("list_strategy_sessions", T.list_strategy_sessions, limit=limit)

    @server.tool(annotations=READ)
    async def strategy_session(session_id: str) -> dict:
        """A strategy session's sections, answers and Strategy Map rows."""
        return await run("strategy_session", T.strategy_session, session_id=session_id)

    # ------------------------------------------------------------ draft
    @server.tool(annotations=DRAFT)
    async def create_task(title: str, due_date: str = "", company_id: str = "",
                          contact_id: str = "", description: str = "") -> dict:
        """Create an internal task owned by you, marked as made by an AI app. The client
        sees it only if a person shows it. due_date: YYYY-MM-DD."""
        return await run("create_task", T.create_task, title=title, due_date=due_date,
                         company_id=company_id, contact_id=contact_id,
                         description=description)

    @server.tool(annotations=DRAFT)
    async def add_note(body: str, title: str = "", contact_id: str = "",
                       company_id: str = "") -> dict:
        """Add a note, marked as added by an AI app, optionally on a contact or company."""
        return await run("add_note", T.add_note, body=body, title=title,
                         contact_id=contact_id, company_id=company_id)

    @server.tool(annotations=DRAFT)
    async def draft_email(contact_id: str, subject: str, body: str) -> dict:
        """Draft an email to a contact from your default mailbox. It waits in the Sending
        queue for a person to approve; it is never sent from here."""
        return await run("draft_email", T.draft_email, contact_id=contact_id,
                         subject=subject, body=body)

    @server.tool(annotations=DRAFT)
    async def propose_map_rows(session_id: str, rows: list[dict[str, Any]]) -> dict:
        """Propose Strategy Map rows into a session's tray for a person to accept, edit or
        discard. Each row: bottleneck (required), root_cause, the_fix, owner, horizon
        (30, 60 or 90), measurable, header, statement."""
        return await run("propose_map_rows", T.propose_map_rows, session_id=session_id,
                         rows=rows)

    @server.tool(annotations=DRAFT)
    async def enter_kpi_reading(company_id: str, kpi_id: str, period_start: str, value: str,
                                membership_id: str = "") -> dict:
        """Enter one KPI reading, marked "entered by AI". period_start: the period's first
        day (YYYY-MM-DD); membership_id only for a per-person KPI."""
        return await run("enter_kpi_reading", T.enter_kpi_reading, company_id=company_id,
                         kpi_id=kpi_id, period_start=period_start, value=value,
                         membership_id=membership_id)

    @server.tool(annotations=DRAFT)
    async def create_digest_draft(contact_id: str, body: str) -> dict:
        """Draft a progress digest to a client contact in these words. It waits for
        approval in Digests and the Sending queue; it is never sent from here. Write it as
        value delivered, not a changelog."""
        return await run("create_digest_draft", T.create_digest_draft,
                         contact_id=contact_id, body=body)

    # ---------------------------------------------------------- prompts
    @server.prompt(title="Weekly note for a company")
    def weekly_note(company: str) -> str:
        """Draft this week's note to a client company."""
        return (f"Using Execs NOW HQ, find the company \"{company}\" (list_companies), read "
                "its company_overview and this week's scorecard_readings, and draft the "
                "weekly note to the client: what went well, what needs attention, and what "
                "happens next. Show me the draft; if I say so, save it with "
                "create_digest_draft to the client's main contact.")

    @server.prompt(title="Prep me for a contact")
    def prep_contact(contact: str) -> str:
        """Everything worth knowing before a call with a contact."""
        return (f"Using Execs NOW HQ, find the contact \"{contact}\" (search_contacts), read "
                "get_contact, their company's company_overview and recent list_notes, and "
                "prep me for a call: who they are, where things stand, open tasks and "
                "promises, anything late, and three questions to ask.")

    @server.prompt(title="What's late this week")
    def whats_late() -> str:
        """Late and due-this-week work across the practice."""
        return ("Using Execs NOW HQ, list_tasks with overdue=true and list_tasks due before "
                "the end of this week, then practice_summary. Group what's late and what's "
                "due by company, say who owns each, and suggest what to chase first.")

    return server
