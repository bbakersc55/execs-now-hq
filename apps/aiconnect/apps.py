from django.apps import AppConfig


class AiConnectConfig(AppConfig):
    """AI apps (P7, 2026-11-10): a practice user's own Claude or ChatGPT
    connected over MCP. The OAuth 2.1 authorization server is here and served
    by web; the MCP server itself is `apps/aiconnect/mcp_server.py`, served by
    the `mcp` service (`config/mcp_asgi.py`). docs/p7_mcp.md."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.aiconnect"
    label = "aiconnect"
