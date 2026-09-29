"""The one place the app calls Claude (CLAUDE.md: Anthropic only).

Three things every call gets, so no feature has to remember them:

1. **The tenant's own key** (assumption E1), decrypted per call. The `.env`
   fallback exists for local build-out only and is refused off localhost.
2. **An `AiCall` row**, success or failure, with tokens and cost — spend is a
   number the FF can look up (E1.7), including what a failed call cost.
3. **Server-side refusal fallback** (`fallbacks: "default"`): if Opus declines,
   the API re-runs the request on Anthropic's recommended model in the same
   call. The row records the model that actually served it.
"""

from __future__ import annotations

import contextlib
import contextvars
import functools

from decimal import Decimal

from django.conf import settings

FALLBACK_BETA = "server-side-fallback-2026-07-01"

# USD per million tokens (input, output). A served model missing from this
# table is recorded at $0 with the gap noted, never guessed.
PRICES_PER_MTOK = {
    "claude-opus-5": (Decimal("5.00"), Decimal("25.00")),
    "claude-opus-4-8": (Decimal("5.00"), Decimal("25.00")),
}


class ClaudeUnavailable(Exception):
    """No key, a rejected key, or the API could not be reached. Retryable.

    `call` is the `AiCall` row the failure wrote, when it got that far — so a
    caller can tell a failure that cost money (an answer cut off at the limit)
    from one that cost nothing (no key, no network)."""

    call = None


class ClaudeRefused(Exception):
    """Every model in the fallback chain declined."""


class ClaudeSkipped(ClaudeUnavailable):
    """An unattended call not made (apps/tenancy/ai_guard.py): the day's cap is
    reached, or this exact input has failed twice. Nothing was sent to
    Anthropic and nothing was billed. `reason` is `ai_guard.DAILY_CAP` or
    `ai_guard.FAILED_TWICE`. A subclass of ClaudeUnavailable, so every caller
    that already survives an outage survives this; callers that should wait
    for tomorrow rather than give up check for it."""

    def __init__(self, message, reason):
        super().__init__(message)
        self.reason = reason


# ------------------------------------------------------- who is asking

#: The worker job making calls right now, or None in a web request. Set only by
#: `unattended`, which every scheduled job entry point wears.
_UNATTENDED: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "claude_unattended", default=None)


@contextlib.contextmanager
def unattended(job: str):
    """Calls made inside are the worker's own, with nobody asking: they count
    against the daily cap and stop after two failures (owner, 2026-09-29)."""
    token = _UNATTENDED.set(job)
    try:
        yield
    finally:
        _UNATTENDED.reset(token)


def unattended_job(job: str):
    """The decorator form, for a scheduled task function."""
    def wrap(fn):
        @functools.wraps(fn)
        def run(*args, **kwargs):
            with unattended(job):
                return fn(*args, **kwargs)
        return run
    return wrap


def current_job() -> str | None:
    return _UNATTENDED.get()


def key_source(tenant) -> str | None:
    """'tenant', 'env' (local fallback), or None. Never the key itself."""
    if _tenant_key(tenant):
        return "tenant"
    if settings.IS_LOCAL and settings.ANTHROPIC_API_KEY:
        return "env"
    return None


def _tenant_secret(tenant):
    from apps.tenancy.models import SecretKind, TenantSecret

    return TenantSecret.all_objects.filter(
        tenant=tenant, kind=SecretKind.ANTHROPIC_API_KEY, user__isnull=True
    ).first()


def _tenant_key(tenant) -> str:
    from apps.crm.services.secrets import read_secret

    return read_secret(_tenant_secret(tenant))


def _resolve_key(tenant) -> str:
    key = _tenant_key(tenant)
    if key:
        return key
    if settings.IS_LOCAL and settings.ANTHROPIC_API_KEY:
        return settings.ANTHROPIC_API_KEY
    raise ClaudeUnavailable(
        "No Anthropic API key is set. The founder fractional adds one under AI usage."
    )


def _client(key):
    import anthropic

    return anthropic.Anthropic(api_key=key, max_retries=2, timeout=300.0)


def validate_key(key: str) -> None:
    """E1.4 — one cheap call before a key replaces the working one.

    Retrieving the configured model costs no tokens and proves both that the
    key authenticates and that it can reach the model the app will use.
    """
    import anthropic

    try:
        _client(key).models.retrieve(settings.ANTHROPIC_MODEL)
    except anthropic.AuthenticationError as exc:
        raise ClaudeUnavailable("Anthropic rejected that key.") from exc
    except anthropic.PermissionDeniedError as exc:
        raise ClaudeUnavailable(
            f"That key cannot use {settings.ANTHROPIC_MODEL}."
        ) from exc
    except anthropic.NotFoundError as exc:
        raise ClaudeUnavailable(
            f"The configured model {settings.ANTHROPIC_MODEL!r} was not found."
        ) from exc
    except (anthropic.APIConnectionError, anthropic.APIStatusError) as exc:
        raise ClaudeUnavailable(f"Could not reach Anthropic to check the key: {exc}") from exc


def save_key(*, tenant, key: str, actor) -> None:
    """Validate, then replace. On failure nothing changes (E1.4)."""
    from django.utils import timezone

    from apps.crm.services.secrets import write_secret
    from apps.tenancy.models import AuditEvent, SecretKind

    key = (key or "").strip()
    validate_key(key)
    had_key = _tenant_secret(tenant) is not None
    secret = write_secret(tenant=tenant, kind=SecretKind.ANTHROPIC_API_KEY, value=key)
    now = timezone.now()
    secret.verified_at = now
    secret.verified_by = actor
    if had_key:
        secret.rotated_at = now
    secret.save(update_fields=["verified_at", "verified_by", "rotated_at", "updated_at"])
    AuditEvent.all_objects.create(
        tenant=tenant, actor=actor,
        verb="ai.key_rotated" if had_key else "ai.key_set",
        target_type="tenant_secret", target_id=secret.pk,
        payload={"last4": secret.last4},
    )


def cost_of(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    prices = PRICES_PER_MTOK.get(model)
    if prices is None:
        return Decimal("0")
    per_in, per_out = prices
    return (per_in * input_tokens + per_out * output_tokens) / Decimal(1_000_000)


def complete(*, tenant, **kwargs) -> str:
    """One request, one text answer. Raises rather than returning a partial."""
    return complete_with_call(tenant=tenant, **kwargs)[0]


#: Anthropic's own search tool. Used by session prep, which has to read a
#: prospect's website — and by nothing else, because every other call in this
#: product answers from material the practice already holds.
WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 6}


def complete_with_call(*, tenant, purpose: str, system: str, user_text: str,
                       target_type: str = "", target_id=None, trigger: str = "auto",
                       max_tokens: int = 16000, tools=None, effort: str | None = None):
    """As `complete`, and also hands back the `AiCall` row it wrote.

    Module 4 needs it: a drafted map row records **which run produced it**, so a
    row in the tray can always be traced to the call that cost money.

    `tools` passes Anthropic's server-side tools through — today only
    `WEB_SEARCH_TOOL`. The searches it ran are counted onto the row; **their
    cost is not in `cost_usd`**, which is the token cost, because Anthropic
    bills searches separately and a number that quietly under-reports spend is
    worse than one that admits what it covers.

    `effort` ("low" … "max") sets how hard the model reasons, which is billed
    as output. Left unset, the model's own default. A labelling job — the
    owner classification — asks for "low" (2026-09-28).
    """
    import anthropic

    from apps.tenancy.models import AiCall

    job = current_job()
    input_hash = ""
    if job is not None:
        import hashlib

        from apps.tenancy import ai_guard

        input_hash = hashlib.sha256(
            "\x1f".join([purpose, system, user_text]).encode()).hexdigest()
        reason = ai_guard.refusal(tenant, purpose=purpose, target_type=target_type,
                                  target_id=target_id, input_hash=input_hash)
        if reason is not None:
            ai_guard.record_skip(tenant, reason=reason, purpose=purpose,
                                 target_type=target_type, target_id=target_id, job=job)
            raise ClaudeSkipped(
                "Today's limit on automatic AI spend is reached; this waits until "
                "tomorrow." if reason == ai_guard.DAILY_CAP else
                "This failed twice on the same input, so it is not tried again "
                "automatically until someone runs it.", reason)

    call = AiCall(
        tenant=tenant, purpose=purpose, target_type=target_type, target_id=target_id,
        model=settings.ANTHROPIC_MODEL, trigger=trigger,
        unattended=job is not None, input_hash=input_hash,
    )

    def fail(message, exc=None):
        call.succeeded = False
        call.error = message
        call.save()
        error = ClaudeUnavailable(message)
        error.call = call
        raise error from exc

    try:
        key = _resolve_key(tenant)
    except ClaudeUnavailable as exc:
        fail(str(exc), exc)

    try:
        response = _client(key).beta.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_text}],
            betas=[FALLBACK_BETA],
            fallbacks="default",
            **({"tools": tools} if tools else {}),
            **({"output_config": {"effort": effort}} if effort else {}),
        )
    except anthropic.AuthenticationError as exc:
        fail("Anthropic rejected the stored key. The founder fractional can replace it "
             "under AI usage.", exc)
    except anthropic.PermissionDeniedError as exc:
        fail(f"The stored key cannot use {settings.ANTHROPIC_MODEL}.", exc)
    except anthropic.RateLimitError as exc:
        fail("Anthropic is rate-limiting this key. Try again in a few minutes.", exc)
    except anthropic.BadRequestError as exc:
        fail(f"Anthropic refused the request: {exc.message}", exc)
    except anthropic.APIStatusError as exc:
        fail(f"Anthropic returned {exc.status_code}. Try again later.", exc)
    except anthropic.APIConnectionError as exc:
        fail("Could not reach Anthropic. Check the connection and try again.", exc)

    usage = response.usage
    call.web_searches = getattr(
        getattr(usage, "server_tool_use", None), "web_search_requests", 0) or 0
    call.model = response.model or settings.ANTHROPIC_MODEL
    call.input_tokens = usage.input_tokens or 0
    call.output_tokens = usage.output_tokens or 0
    call.cost_usd = cost_of(call.model, call.input_tokens, call.output_tokens)
    if call.model not in PRICES_PER_MTOK:
        call.error = f"No price on file for {call.model}; cost recorded as $0."

    if response.stop_reason == "refusal":
        call.succeeded = False
        call.error = "Declined by every model in the fallback chain."
        call.save()
        raise ClaudeRefused(call.error)

    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if response.stop_reason == "max_tokens" or not text:
        # A summary cut off mid-sentence reads as complete to whoever skims it.
        fail("Claude's answer was cut off or empty; nothing was kept.")

    call.succeeded = True
    call.save()
    return text, call
