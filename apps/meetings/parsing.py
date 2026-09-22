"""Claude reads the notes and proposes (FR-5.8 to FR-5.14).

**Nothing here creates a record.** It produces a `MeetingProposal` and a row
per proposed thing, each carrying the passage of the document it was drawn from
so a reviewer can check the claim rather than trust it (FR-5.14).

Two constraints the prompt is written around:

1. **Assert nothing the notes do not carry** — the same rule the digest and the
   strategy map work under (AC-3.5). No invented owners, no invented dates.
2. **Extract participants, action items and deliverables, and nothing else.**
   Decisions, risks and sentiment are out of scope for Beta and a model asked
   for them will happily supply them.
"""

from __future__ import annotations

import json
import re
from datetime import date

from django.db import transaction
from django.utils import timezone

from apps.meetings import matching
from apps.meetings.models import MeetingProposal, MeetingSourceFile, ProposalItem

PARSE_PURPOSE = "meeting_parse"

SYSTEM = """\
You are reading the notes of one business meeting for a fractional operations \
executive, and proposing what should be recorded. A person reviews everything \
you propose; nothing you say is acted on by itself.

Produce four things.

1. "title" and "meeting_date" (YYYY-MM-DD) as the notes give them. If the notes \
do not say, leave the date null — do not infer one from today.
2. "summary": four to six sentences on what the meeting was about and what came \
out of it, in plain English.
3. "participants": everybody the notes show was in the room or on the call, with \
whatever the notes give — name, email, title, company — and nothing they do not. \
Also propose "contact_type", one of prospect, client, referral_partner, vendor, \
coworker, from how the notes describe them.
4. "action_items": something somebody agreed to do, with "owner" as the notes \
name them and "due_date" only if the notes give one. And "deliverables": \
something promised TO the client that somebody outside the room is waiting on.

**Every item carries "excerpt": the sentence from the notes it came from**, \
copied exactly, so the reviewer can check it. An item you cannot quote is an \
item you invented — leave it out.

**Assert nothing the notes do not carry.** No owner nobody named, no date \
nobody agreed, no company nobody mentioned. Do not extract decisions, risks or \
sentiment: participants, action items and deliverables only.

Reply with JSON only: {"title": "", "meeting_date": null, "summary": "", \
"participants": [{"name": "", "email": "", "title": "", "company": "", \
"contact_type": "", "excerpt": ""}], "action_items": [{"text": "", "owner": "", \
"due_date": null, "excerpt": ""}], "deliverables": [{"text": "", "owner": "", \
"due_date": null, "excerpt": ""}]}. No prose around it, no markdown fence."""

VALID_TYPES = {"prospect", "client", "referral_partner", "vendor", "coworker"}


def _payload(text: str):
    cleaned = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.S)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None


def _a_date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def text_of(source_file, *, client=None) -> str:
    """The document, fetched once and kept, so a re-parse costs no second trip
    to Drive and the review screen can quote it."""
    if source_file.text:
        return source_file.text
    if client is None:
        return ""
    from apps.meetings.drive import DriveFile, DriveUnavailable

    try:
        text = client.text_of(DriveFile(
            file_id=source_file.drive_file_id, version=source_file.drive_version,
            name=source_file.name, mime_type=source_file.mime_type))
    except DriveUnavailable:
        return ""
    source_file.text = text
    source_file.save(update_fields=["text", "updated_at"])
    return text


@transaction.atomic
def _build(source_file, payload, call) -> MeetingProposal:
    tenant = source_file.tenant
    proposal = MeetingProposal.objects.create(
        tenant=tenant, source_file=source_file,
        title=str(payload.get("title") or source_file.name)[:255],
        meeting_date=_a_date(payload.get("meeting_date")),
        proposed_summary=str(payload.get("summary") or "").strip(),
        ai_call=call, state=MeetingProposal.State.PENDING,
    )

    for position, raw in enumerate(payload.get("participants") or []):
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        email = str(raw.get("email") or "").strip()
        if not name and not email:
            continue
        proposed_type = str(raw.get("contact_type") or "").strip()
        ProposalItem.objects.create(
            tenant=tenant, proposal=proposal, kind=ProposalItem.Kind.PARTICIPANT,
            position=position, source_excerpt=str(raw.get("excerpt") or "").strip(),
            payload={
                "parsed_name": name,
                "parsed_email": email,
                "parsed_title": str(raw.get("title") or "").strip(),
                "parsed_company": str(raw.get("company") or "").strip(),
                # Proposed, never applied (FR-5.9a).
                "proposed_contact_type": (proposed_type if proposed_type in VALID_TYPES
                                          else "prospect"),
                # **Both paths, always** (FR-5.11): the candidate to create, and
                # whatever we already hold that might be them.
                "new_contact_candidate": {
                    "first_name": name.split(" ")[0] if name else "",
                    "last_name": " ".join(name.split(" ")[1:]) if " " in name else "",
                    "email": email,
                    "title": str(raw.get("title") or "").strip(),
                    "company": str(raw.get("company") or "").strip(),
                },
                "existing_candidates": matching.candidates_for(
                    tenant, name=name, email=email),
                "service_categories": [],
            })

    for kind, key in ((ProposalItem.Kind.ACTION_ITEM, "action_items"),
                      (ProposalItem.Kind.DELIVERABLE, "deliverables")):
        for position, raw in enumerate(payload.get(key) or []):
            if not isinstance(raw, dict) or not str(raw.get("text") or "").strip():
                continue
            owner = str(raw.get("owner") or "").strip()
            body = {
                "text": str(raw["text"]).strip(),
                "proposed_owner_text": owner,
                # Resolved to a contact where the name is unambiguous; left as
                # text where it is not, exactly as a map row's owner is
                # (FR-4.29a). Guessing an accountable person is worse than
                # leaving the field.
                "proposed_owner_contact_id": _owner_contact_id(tenant, owner),
                "proposed_due_date": (_a_date(raw.get("due_date")).isoformat()
                                      if _a_date(raw.get("due_date")) else None),
            }
            if kind == ProposalItem.Kind.DELIVERABLE:
                body["proposed_stakeholders"] = []
            ProposalItem.objects.create(
                tenant=tenant, proposal=proposal, kind=kind, position=position,
                source_excerpt=str(raw.get("excerpt") or "").strip(), payload=body)

    source_file.state = MeetingSourceFile.State.PARSED
    source_file.error = ""
    source_file.save(update_fields=["state", "error", "updated_at"])
    return proposal


def _owner_contact_id(tenant, owner_text: str):
    if not owner_text:
        return None
    ranked = matching.candidates_for(tenant, name=owner_text)
    exact = [row for row in ranked if row["match_reason"] != matching.NAME_ONLY]
    if exact:
        return exact[0]["contact_id"]
    named = [row for row in ranked if row["match_reason"] == matching.NAME_ONLY]
    return named[0]["contact_id"] if len(named) == 1 else None


def parse(source_file, *, client=None, trigger="auto") -> MeetingProposal | None:
    """Read one file. Returns the proposal, or None and a recorded failure.

    **A failure leaves the file recorded and retryable** and does not touch the
    cursor (FR-5.5, AC-5.10).
    """
    from apps.tenancy import claude

    text = text_of(source_file, client=client)
    if not text.strip():
        source_file.state = MeetingSourceFile.State.FAILED
        source_file.error = "The document could not be read, or is empty."
        source_file.save(update_fields=["state", "error", "updated_at"])
        return None

    source_file.state = MeetingSourceFile.State.PARSING
    source_file.save(update_fields=["state", "updated_at"])
    try:
        reply, call = claude.complete_with_call(
            tenant=source_file.tenant, purpose=PARSE_PURPOSE, system=SYSTEM,
            user_text=f"{source_file.name}\n\n{text}",
            target_type="meeting_source_file", target_id=source_file.pk,
            trigger=trigger, max_tokens=6000,
        )
    except (claude.ClaudeUnavailable, claude.ClaudeRefused) as exc:
        source_file.state = MeetingSourceFile.State.FAILED
        source_file.error = str(exc)
        source_file.save(update_fields=["state", "error", "updated_at"])
        return None

    payload = _payload(reply)
    if not isinstance(payload, dict):
        source_file.state = MeetingSourceFile.State.FAILED
        source_file.error = "Claude answered with something this could not read."
        source_file.save(update_fields=["state", "error", "updated_at"])
        return None
    return _build(source_file, payload, call)


def reparse(proposal, *, actor=None) -> MeetingProposal | None:
    """A fresh proposal that supersedes this one (FR-5.17).

    **Approved items are untouched** — what a person has already decided is not
    up for a second opinion — and the old proposal is kept as `superseded`
    rather than deleted, so the trail of what was proposed survives.
    """
    source_file = proposal.source_file
    source_file.state = MeetingSourceFile.State.RECORDED
    source_file.save(update_fields=["state", "updated_at"])
    fresh = parse(source_file, trigger="button")
    if fresh is None:
        return None
    proposal.state = MeetingProposal.State.SUPERSEDED
    proposal.save(update_fields=["state", "updated_at"])
    ProposalItem.objects.filter(proposal=proposal,
                                state=ProposalItem.State.PENDING).update(
        state=ProposalItem.State.REJECTED, actioned_at=timezone.now())
    return fresh
