"""The demo's connector rails (`docs/p13_connector_rails.md`, "The demo").

The demo never connects to another system: adding an MCP or API connection is
refused there, and so is testing or reading one. So that each rail has
something to show, Pied Piper Compression's scorecard has a "Connected
systems" page with one KPI on each, its readings written by the rails' own
code from stand-ins, the way the Google reviews seed reads its reviews:

- **New signups** (weekly), from a webhook: twelve weekly posts as Zapier
  would send them, and one refused post, in its deliveries. The address's
  token is thrown away, as a real one is once shown; Rotate makes a new one.
- **Support tickets open** (weekly), from "Help desk", an MCP server: a
  connection with three tools, and the tool, arguments and path a person
  confirmed after Claude proposed them. Read by the nightly code, no AI.
- **Monthly recurring revenue** (monthly), from "Billing API", any API: a GET
  of `/metrics/mrr` with the month in the query, the value at `data.mrr`.
"""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

from .clock import at, dice, moment

COMPANY = "Pied Piper Compression"
PAGE = "Connected systems"
#: The help desk's tools, as its server lists them.
TOOLS = [
    {"name": "count_tickets", "description": "Count tickets by status as of a date.",
     "input_schema": {"type": "object", "properties": {
         "status": {"type": "string", "enum": ["open", "pending", "solved"]},
         "as_of": {"type": "string", "description": "YYYY-MM-DD"}}, "required": ["status"]}},
    {"name": "list_tickets", "description": "List tickets, newest first.",
     "input_schema": {"type": "object", "properties": {"limit": {"type": "integer"}}}},
    {"name": "first_reply_time", "description": "Average hours to the first reply in a range.",
     "input_schema": {"type": "object", "properties": {
         "from": {"type": "string"}, "to": {"type": "string"}}}},
]


def connect(world) -> dict:
    from apps.crm.services import secrets
    from apps.scorecard import rails, setup
    from apps.scorecard import periods as P
    from apps.scorecard.models import (ApiConnection, Kpi, KpiApiFeed, KpiMcpFeed, KpiReading,
                                       KpiWebhookFeed, McpConnection)

    company = world.companies[COMPANY]
    when = moment(world.today, 6, 45)
    with at(when):
        card = setup.ensure(company, world.owner)
        page = card.pages.order_by("position").first()
        page.name = PAGE
        page.save(update_fields=["name", "updated_at"])

        def kpi(fields):
            return setup.create_kpi(card, {"page": str(page.pk), "tile": "number_trend",
                                           "reading_owner": str(world.owner.pk), **fields},
                                    world.owner)

        signups = kpi({"name": "New signups", "kind": "count", "cadence": "weekly",
                       "rollup": "sum", "target_value": 40, "tile": "bars",
                       "strategy_component": "traction",
                       "note": "Posted each Monday by a Zap from the signup form"})
        tickets = kpi({"name": "Support tickets open", "kind": "count", "cadence": "weekly",
                       "rollup": "last", "direction": "lower", "target_value": 15,
                       "strategy_component": "process",
                       "note": "Open at the week's end, read from the help desk"})
        mrr = kpi({"name": "Monthly recurring revenue", "kind": "money", "cadence": "monthly",
                   "rollup": "last", "target_value": 60000, "strategy_component": "data",
                   "note": "From the billing system's API at each month's end"})

    # ------------------------------------------------------------ the webhook
    week = P.start_of(world.today, P.WEEKLY, card.week_start)
    posts = []
    for n in range(12, 0, -1):
        start = P.previous_start(week, P.WEEKLY, card.week_start)
        for _ in range(n - 1):
            start = P.previous_start(start, P.WEEKLY, card.week_start)
        roll = dice("signups", n)
        posts.append((start, 22 + (12 - n) * 2 + roll.randrange(-4, 6)))
    _, hashed, hint = rails.new_token("kh_")
    with at(moment(posts[0][0] + timedelta(days=7), 7, 0)):
        hook = KpiWebhookFeed.objects.create(
            tenant=world.tenant, kpi=signups, secret_hash=hashed, secret_hint=hint,
            mode=KpiWebhookFeed.Mode.REPLACE, created_by=world.owner)
        Kpi.objects.filter(pk=signups.pk).update(feed=Kpi.Feed.WEBHOOK)
    hook.refresh_from_db()
    for i, (start, value) in enumerate(posts):
        posted = moment(start + timedelta(days=7), 7, 5 + dice("post", i).randrange(20))
        with at(posted):
            body = {"value": value, "date": (start + timedelta(days=6)).isoformat(),
                    "note": "From Zapier: signups in the week"}
            result = rails.receive(hook, body)
            rails.record(company=company, feed=hook, ok=True,
                         what=f"{result['period']}: saved, now {result['value']}.",
                         payload_text=json.dumps(body))
            if i == len(posts) - 3:
                # A Zap that once sent its own field name: refused, said, nothing written.
                rails.record(company=company, feed=hook, ok=False,
                             what="No value was sent.",
                             payload_text=json.dumps({"signups": value}))
            KpiWebhookFeed.objects.filter(pk=hook.pk).update(last_received_at=posted)

    # ------------------------------------------------------------ any MCP server
    with at(when):
        desk = McpConnection.objects.create(
            tenant=world.tenant, company=company, name="Help desk",
            url="https://mcp.helpdesk.example/mcp",
            # Never a real token: the demo refuses every outbound call.
            secret_ciphertext=secrets.encrypt(json.dumps({"token": "demo-no-connection",
                                                          "headers": {}})),
            secret_hint="tion", tools=TOOLS, checked_at=when, check_ok=True,
            check_detail=f"Connected: {len(TOOLS)} tools.", created_by=world.owner)
        mcp_feed = KpiMcpFeed.objects.create(
            tenant=world.tenant, kpi=tickets, connection=desk, tool="count_tickets",
            arguments={"status": "open", "as_of": "{period_end}"}, value_path="total",
            from_ai=True, created_by=world.owner)
        Kpi.objects.filter(pk=tickets.pk).update(feed=Kpi.Feed.MCP)
        mcp_feed.refresh_from_db()

        def open_tickets(start, end):
            n = (world.today - start).days // 7
            return Decimal(14 + n + dice("tickets", start.isoformat()).randrange(-3, 4))

        mcp_run = rails.run_feed(mcp_feed, world.today, open_tickets,
                                 source=KpiReading.Source.MCP, now=when)

    # ------------------------------------------------------------ any API
    with at(when):
        billing = ApiConnection.objects.create(
            tenant=world.tenant, company=company, name="Billing API",
            base_url="https://api.billing.example/v1", auth_kind=ApiConnection.AuthKind.HEADER,
            auth_name="Authorization", secret_ciphertext=secrets.encrypt("demo-no-connection"),
            secret_hint="tion", created_by=world.owner)
        api_feed = KpiApiFeed.objects.create(
            tenant=world.tenant, kpi=mrr, connection=billing, method="GET",
            path="/metrics/mrr", query={"month": "{year}-{month}"}, value_path="data.mrr",
            created_by=world.owner)
        Kpi.objects.filter(pk=mrr.pk).update(feed=Kpi.Feed.API)
        api_feed.refresh_from_db()

        def revenue(start, end):
            months = (world.today.year - start.year) * 12 + world.today.month - start.month
            return Decimal(58000 - months * 1450 + dice("mrr", start.isoformat()).randrange(-600, 600))

        api_run = rails.run_feed(api_feed, world.today, revenue,
                                 source=KpiReading.Source.API, now=when)
    if not (mcp_run["ok"] and api_run["ok"]):
        raise RuntimeError(f"The demo's rails didn't read: {mcp_run} {api_run}")
    return {"rails KPIs": [signups.name, tickets.name, mrr.name], "webhook posts": len(posts)}
