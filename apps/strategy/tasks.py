"""Worker jobs for Module 4 (owner, 2026-09-29)."""

from __future__ import annotations

# The worker's own: capped per day and stopped after two failures on the same
# input (apps/tenancy/ai_guard.py).
from apps.tenancy.claude import unattended_job
from apps.tenancy.context import tenant_context


@unattended_job("strategy.propose_diagnostic")
def propose_diagnostic(tenant_id: str, session_id: str) -> int:
    """Queued when a prospect completes the pre-call form: Claude's proposed
    diagnostic questions, into the tray. Off the prospect's request, so they
    are not kept waiting on Claude."""
    from apps.strategy import diagnostic
    from apps.strategy.models import StrategySession

    with tenant_context(tenant_id):
        session = StrategySession.objects.filter(pk=session_id).first()
        if session is None:
            return 0
        return len(diagnostic.propose(session, trigger="auto"))
