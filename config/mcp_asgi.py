"""The `mcp` service's ASGI app (P7, docs/p7_mcp.md): the Execs NOW HQ MCP
server, sharing web's settings and database.

    uvicorn config.mcp_asgi:app --host 0.0.0.0 --port 8080

Its own service, not mounted in web: web is gunicorn's synchronous workers,
and the MCP SDK's server is an ASGI (Starlette) app. Stateless and
JSON-answered, so it needs no sticky sessions and scales by replicas.
"""

import os
from urllib.parse import urlsplit

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from mcp.server.transport_security import TransportSecuritySettings  # noqa: E402
from starlette.responses import PlainTextResponse  # noqa: E402

from apps.aiconnect.mcp_server import build  # noqa: E402

def create_app():
    """The ASGI app, with the server it serves (tests build their own)."""
    server = build()

    @server.custom_route("/healthz", methods=["GET"], include_in_schema=False)
    async def healthz(request):
        return PlainTextResponse("ok")

    host = urlsplit(settings.MCP_PUBLIC_URL).netloc
    app = server.streamable_http_app(
        streamable_http_path="/mcp", stateless_http=True, json_response=True,
        # DNS-rebinding protection: only our own host name. AI apps call from
        # their servers (no Origin); a browser page must be on our own origins.
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[host, f"{host}:*"] + (["localhost:*", "127.0.0.1:*"]
                                                 if settings.IS_LOCAL else []),
            allowed_origins=[settings.OAUTH_ISSUER_URL, settings.MCP_PUBLIC_URL]),
    )
    return app, server


app, server = create_app()
