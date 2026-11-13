"""Video and audio in the SOP studio (P10, "Video and audio").

The practice's **media key** (Gemini) is used for one thing only: reading an
uploaded video or audio file into a transcript and a step-by-step summary,
which becomes a source in a brainstorm. It is set under Settings → AI usage,
encrypted like the other keys, with Test and Remove, and off until entered.
Those files go to Google under the practice's own agreement with Google; the
screen says so. The model is the platform owner's "Media (Gemini)" row in the
model table.

- **The price is shown first**, from the file's length (the browser reads
  it): audio at 32 tokens a second, video at 300, and the transcript and
  summary out.
- **Limits:** audio up to 60 minutes and 50 MB; video up to 15 minutes and
  100 MB (`LIMITS`). Formats: the audio and video types Gemini reads.
- **The original isn't kept** unless the person ticks "keep the file"; it is
  sent to Google and never written to storage. Google's copy is deleted as
  soon as the transcript is back.
- **Without a key** an upload is refused with what to do instead: add a media
  key, or paste a transcript.

Reading happens in two steps, each well inside a web request's time: the
upload sends the file to Google and leaves the source "being read"; the
screen then asks again every few seconds, and once Google has the file ready
one request asks for the transcript.
"""

from __future__ import annotations

import json
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import BrainstormSource

API = "https://generativelanguage.googleapis.com"
PURPOSE = "sop_media"
TIMEOUT = 100
AUDIO_TOKENS_PER_SECOND = 32
VIDEO_TOKENS_PER_SECOND = 300
OUT_TOKENS_PER_MINUTE = 220
OUT_TOKENS_BASE = 1500
LIMITS = {"audio": {"seconds": 60 * 60, "bytes": 50 * 1024 * 1024},
          "video": {"seconds": 15 * 60, "bytes": 100 * 1024 * 1024}}
MEDIA_TYPES = {
    "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/aac", "audio/ogg",
    "audio/flac", "audio/aiff", "audio/webm", "audio/mp4", "audio/x-m4a", "audio/m4a",
    "video/mp4", "video/quicktime", "video/webm", "video/mpeg", "video/x-msvideo",
    "video/3gpp", "video/x-flv", "video/mov",
}
NO_KEY = ("Video and audio are read with a media key (Gemini), and none is set. The practice "
          "owner adds one under AI usage; or paste a transcript as text instead.")
ASK = """Transcribe this recording, then summarize the process it shows or describes as
ordered steps. Reply with JSON only: {"transcript": "...", "steps": ["...", "..."],
"summary": "..."}. The transcript is what is said, with who says it where that is clear.
Each step is one action, as an instruction. If nothing is said, describe what is done."""


class MediaRefused(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# ------------------------------------------------------------------ the key

def _secret(tenant):
    from apps.tenancy.models import SecretKind, TenantSecret

    return TenantSecret.all_objects.filter(tenant=tenant, kind=SecretKind.GEMINI_API_KEY,
                                           user__isnull=True).first()


def key_of(tenant) -> str:
    from apps.crm.services.secrets import read_secret

    return read_secret(_secret(tenant))


def model() -> str:
    from apps.tenancy import ai_actions

    return ai_actions.tier_row(ai_actions.MEDIA).model


def _http(method, url, *, key, headers=None, body=None, json_body=None, timeout=TIMEOUT):
    """(status, response headers, parsed JSON or {}). The one place a request
    leaves for Google; tests stand a fake in its place."""
    import requests

    sent = {"x-goog-api-key": key, **(headers or {})}
    try:
        r = requests.request(method, url, headers=sent, data=body, json=json_body,
                             timeout=timeout, allow_redirects=False)
    except requests.RequestException as exc:
        raise MediaRefused(f"Google couldn't be reached: {type(exc).__name__}.", 502) from None
    try:
        data = r.json() if r.content else {}
    except ValueError:
        data = {}
    return r.status_code, r.headers, data


def _said(status, data) -> str:
    message = ((data or {}).get("error") or {}).get("message") or ""
    if status in (400, 401, 403):
        return "Google refused the media key" + (f": {message}" if message else ".")
    return f"Google answered {status}" + (f": {message}" if message else ".")


def test_key(key: str) -> str:
    """"Connected: …", or MediaRefused saying why."""
    key = (key or "").strip()
    if len(key) < 20 or " " in key:
        raise MediaRefused("That doesn't look like a Gemini API key.")
    status, _, data = _http("GET", f"{API}/v1beta/models/{model()}", key=key, timeout=15)
    if status != 200:
        raise MediaRefused(_said(status, data))
    return f"Connected: {data.get('displayName') or model()} answers."


@transaction.atomic
def save_key(tenant, key, *, actor) -> dict:
    from apps.crm.services.secrets import write_secret
    from apps.tenancy.demo import visitors
    from apps.tenancy.models import AuditEvent, SecretKind

    if visitors.is_copy(tenant):
        raise MediaRefused("Your demo takes no media key of its own.", 409)
    detail = test_key(key)
    had = _secret(tenant) is not None
    secret = write_secret(tenant=tenant, kind=SecretKind.GEMINI_API_KEY, value=key.strip())
    now = timezone.now()
    secret.verified_at, secret.verified_by = now, actor
    if had:
        secret.rotated_at = now
    secret.save(update_fields=["verified_at", "verified_by", "rotated_at", "updated_at"])
    AuditEvent.all_objects.create(tenant=tenant, actor=actor,
                                  verb="ai.media_key_rotated" if had else "ai.media_key_set",
                                  target_type="tenant_secret", target_id=secret.pk,
                                  payload={"last4": secret.last4})
    return {**status(tenant), "detail": detail}


def check_saved(tenant) -> dict:
    key = key_of(tenant)
    if not key:
        raise MediaRefused("No media key is set.", 409)
    return {**status(tenant), "detail": test_key(key)}


@transaction.atomic
def remove_key(tenant, *, actor) -> dict:
    from apps.tenancy.models import AuditEvent

    secret = _secret(tenant)
    if secret is not None:
        AuditEvent.all_objects.create(tenant=tenant, actor=actor, verb="ai.media_key_removed",
                                      target_type="tenant_secret", target_id=secret.pk,
                                      payload={"last4": secret.last4})
        secret.delete()
    return status(tenant)


def rates() -> dict:
    from apps.tenancy import ai_actions

    row = ai_actions.tier_row(ai_actions.MEDIA)
    return {"input_usd_per_mtok": row.input_usd_per_mtok,
            "output_usd_per_mtok": row.output_usd_per_mtok}


def estimate(kind: str, seconds) -> Decimal:
    r = rates()
    seconds = max(int(seconds or 0), 1)
    per_second = VIDEO_TOKENS_PER_SECOND if kind == "video" else AUDIO_TOKENS_PER_SECOND
    tokens_in = seconds * per_second
    tokens_out = OUT_TOKENS_BASE + OUT_TOKENS_PER_MINUTE * (seconds // 60 + 1)
    return ((r["input_usd_per_mtok"] * tokens_in + r["output_usd_per_mtok"] * tokens_out)
            / Decimal(1_000_000)).quantize(Decimal("0.0001"))


def status(tenant) -> dict:
    secret = _secret(tenant)
    r = rates()
    per_minute = {kind: str(estimate(kind, 60)) for kind in ("audio", "video")}
    return {"set": secret is not None, "last4": secret.last4 if secret else "",
            "verified_at": secret.verified_at.isoformat() if secret and secret.verified_at
            else None, "model": model(),
            "input_usd_per_mtok": str(r["input_usd_per_mtok"]),
            "output_usd_per_mtok": str(r["output_usd_per_mtok"]),
            "about_per_minute": per_minute,
            "limits": {k: {"minutes": v["seconds"] // 60, "mb": v["bytes"] // (1024 * 1024)}
                       for k, v in LIMITS.items()},
            "refused": "" if secret else NO_KEY,
            "notice": "Video and audio files are sent to Google to be read, under the "
                      "practice's own agreement with Google. Nothing else is."}


# ------------------------------------------------------------------ reading a file

def _kind_of(content_type: str) -> str:
    return "video" if content_type.startswith("video/") else "audio"


@transaction.atomic
def upload(brainstorm, upload_file, *, seconds, keep, actor) -> BrainstormSource:
    from apps.tenancy import storage

    tenant = brainstorm.company.tenant
    key = key_of(tenant)
    if not key:
        raise MediaRefused(NO_KEY, 409)
    content_type = (getattr(upload_file, "content_type", "") or "").split(";")[0].lower()
    if content_type not in MEDIA_TYPES:
        raise MediaRefused("That isn't a video or audio file Gemini reads (MP4, MOV, WebM, MP3, "
                           "WAV, M4A, AAC, OGG or FLAC).")
    kind = _kind_of(content_type)
    limit = LIMITS[kind]
    try:
        seconds = int(float(seconds))
    except (TypeError, ValueError):
        raise MediaRefused("The recording's length couldn't be read; try another file.") from None
    if seconds <= 0:
        raise MediaRefused("The recording's length couldn't be read; try another file.")
    if seconds > limit["seconds"]:
        raise MediaRefused(f"A {kind} file is {limit['seconds'] // 60} minutes at most.")
    if upload_file.size > limit["bytes"]:
        raise MediaRefused(f"A {kind} file is {limit['bytes'] // (1024 * 1024)} MB at most.")
    from .brainstorm import refusal

    stop = refusal(tenant)
    if stop and "Anthropic" not in stop:
        raise MediaRefused(stop, 409)
    content = upload_file.read()
    name = (getattr(upload_file, "name", "") or f"{kind} file")[:120]
    status_code, headers, data = _http(
        "POST", f"{API}/upload/v1beta/files", key=key, timeout=30,
        headers={"X-Goog-Upload-Protocol": "resumable", "X-Goog-Upload-Command": "start",
                 "X-Goog-Upload-Header-Content-Length": str(len(content)),
                 "X-Goog-Upload-Header-Content-Type": content_type,
                 "Content-Type": "application/json"},
        json_body={"file": {"display_name": name}})
    upload_url = (headers or {}).get("x-goog-upload-url") or (headers or {}).get(
        "X-Goog-Upload-URL")
    if status_code != 200 or not upload_url:
        raise MediaRefused(_said(status_code, data), 502)
    status_code, _, data = _http(
        "POST", upload_url, key=key,
        headers={"Content-Length": str(len(content)), "X-Goog-Upload-Offset": "0",
                 "X-Goog-Upload-Command": "upload, finalize"}, body=content)
    handle = (data or {}).get("file") or {}
    if status_code != 200 or not handle.get("name"):
        raise MediaRefused(_said(status_code, data), 502)
    stored = None
    if keep:
        stored = storage.save(tenant=tenant, content=content,
                              object_key=storage.object_key(f"brainstorms/{brainstorm.pk}", name),
                              purpose="sop_media", content_type=content_type)
    return BrainstormSource.objects.create(
        tenant_id=brainstorm.tenant_id, brainstorm=brainstorm, kind=BrainstormSource.Kind.MEDIA,
        title=name, content_type=content_type, state=BrainstormSource.State.READING,
        seconds=seconds, keep_file=bool(keep), file=stored,
        external_ref=json.dumps({"name": handle["name"], "uri": handle.get("uri", "")})[:200],
        created_by=actor)


def _forget(key, ref):
    try:
        _http("DELETE", f"{API}/v1beta/{ref['name']}", key=key, timeout=15)
    except MediaRefused:
        pass


def _fail(source, message):
    source.state, source.error = BrainstormSource.State.FAILED, message[:1000]
    source.save(update_fields=["state", "error", "updated_at"])
    return source


@transaction.atomic
def read(source) -> BrainstormSource:
    """Ask Google once: still being processed, failed, or ready, in which
    case the transcript and the steps become the source's text."""
    from apps.tenancy.models import AiCall

    if source.state != BrainstormSource.State.READING:
        return source
    tenant = source.brainstorm.company.tenant
    key = key_of(tenant)
    if not key:
        return _fail(source, "The media key was removed before the file was read.")
    try:
        ref = json.loads(source.external_ref or "{}")
    except ValueError:
        ref = {}
    if not ref.get("name"):
        return _fail(source, "The file never reached Google. Upload it again.")
    status_code, _, data = _http("GET", f"{API}/v1beta/{ref['name']}", key=key, timeout=15)
    state = (data or {}).get("state")
    if status_code != 200 or state == "FAILED":
        _forget(key, ref)
        return _fail(source, "Google couldn't process the file" + (
            f" ({_said(status_code, data)})" if status_code != 200 else "."))
    if state != "ACTIVE":
        return source
    status_code, _, data = _http(
        "POST", f"{API}/v1beta/models/{model()}:generateContent", key=key,
        json_body={"contents": [{"parts": [
            {"file_data": {"mime_type": source.content_type,
                           "file_uri": ref.get("uri") or f"{API}/v1beta/{ref['name']}"}},
            {"text": ASK}]}],
            "generationConfig": {"responseMimeType": "application/json"}})
    _forget(key, ref)
    usage = (data or {}).get("usageMetadata") or {}
    tokens_in = int(usage.get("promptTokenCount") or 0)
    tokens_out = int(usage.get("candidatesTokenCount") or 0) + int(
        usage.get("thoughtsTokenCount") or 0)
    r = rates()
    cost = (r["input_usd_per_mtok"] * tokens_in + r["output_usd_per_mtok"] * tokens_out) \
        / Decimal(1_000_000)
    call = AiCall.all_objects.create(
        tenant=tenant, purpose=PURPOSE, target_type="sop_brainstorm",
        target_id=source.brainstorm_id, model=model(), input_tokens=tokens_in,
        output_tokens=tokens_out, cost_usd=cost, trigger="button",
        succeeded=status_code == 200, error="" if status_code == 200 else _said(status_code, data))
    if status_code != 200:
        return _fail(source, _said(status_code, data))
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(text)
    except (KeyError, IndexError, TypeError, ValueError):
        call.succeeded, call.error = False, "The answer couldn't be read."
        call.save(update_fields=["succeeded", "error"])
        return _fail(source, "Google's answer couldn't be read. Try again, or paste a transcript.")
    steps = [str(s).strip() for s in parsed.get("steps") or [] if str(s).strip()]
    body = []
    if parsed.get("summary"):
        body.append(f"Summary: {parsed['summary']}")
    if steps:
        body.append("Steps:\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(steps, start=1)))
    body.append("Transcript:\n" + str(parsed.get("transcript") or "(nothing said)"))
    source.text = "\n\n".join(body)[:80000]
    source.state, source.error = BrainstormSource.State.READY, ""
    source.save(update_fields=["text", "state", "error", "updated_at"])
    return source
