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

from apps.meetings import matching, practice
from apps.meetings.models import MeetingProposal, MeetingSourceFile, ProposalItem

PARSE_PURPOSE = "meeting_parse"

#: Room for the answer and the model's reasoning, which is billed as output.
#: At 6000, 78 reads (to 2026-09-29) came back cut off: successful answers ran
#: to 5,984, and long notes ran past it. 16000 is the wrapper's default and
#: stays below the SDK's non-streaming ceiling.
PARSE_MAX_TOKENS = 16000

#: Billed automatic failures before the poll stops retrying a file: twice on
#: the same input, the rule for every automatic job (owner, 2026-09-29).
MAX_AUTO_PARSE_FAILURES = 2

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
name them and "due_date" only if the notes give one. For each, "owner_side": \
"practice" when the owner is the fractional executive or someone on their team, \
"other" when it is anyone else, "" when the notes name nobody; and when \
"other", "owner_kind": one of client, prospect, vendor, third_party, from how \
the notes describe them. And "deliverables": something promised TO the client \
that somebody outside the room is waiting on.

**Every item carries "excerpt": the sentence from the notes it came from**, \
copied exactly, so the reviewer can check it. An item you cannot quote is an \
item you invented — leave it out.

**Assert nothing the notes do not carry.** No owner nobody named, no date \
nobody agreed, no company nobody mentioned. Do not extract decisions, risks or \
sentiment: participants, action items and deliverables only.

Reply with JSON only: {"title": "", "meeting_date": null, "summary": "", \
"participants": [{"name": "", "email": "", "title": "", "company": "", \
"contact_type": "", "excerpt": ""}], "action_items": [{"text": "", "owner": "", \
"owner_side": "", "owner_kind": "", "due_date": null, "excerpt": ""}], "deliverables": [{"text": "", "owner": "", \
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

    roster = practice.staff(tenant)
    for position, raw in enumerate(payload.get("participants") or []):
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        email = str(raw.get("email") or "").strip()
        if not name and not email:
            continue

        # FR-5.9e — our own side of the table is recognised, not asked about.
        # The fractional is in every meeting; asking "what are they to us"
        # about the practice itself is a question with no true answer.
        ours = practice.recognise(tenant, name=name, email=email, roster=roster)
        if ours is not None:
            ProposalItem.objects.create(
                tenant=tenant, proposal=proposal,
                kind=ProposalItem.Kind.PARTICIPANT, position=position,
                source_excerpt=str(raw.get("excerpt") or "").strip(),
                # Approved on arrival because there is nothing to decide: no
                # record is created, no type is added, no stage moves. It is
                # already approved so that it never holds a proposal open.
                state=ProposalItem.State.APPROVED,
                created_record_type="contact" if ours.contact is not None else "",
                created_record_id=ours.contact.pk if ours.contact is not None else None,
                payload={"parsed_name": name, "parsed_email": email,
                         **practice.payload_for(ours)})
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
                # FR-5.10a — the company the notes named, what we already hold
                # that might be it, and the domain a new one would get. A
                # contact created without its company is a contact somebody has
                # to go back and fix.
                "parsed_company_domain": matching.domain_for_new_company(email),
                "company_candidates": matching.company_candidates_for(
                    tenant, name=str(raw.get("company") or "").strip(), email=email),
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
            else:
                # Who owns it (owner, 2026-09-28): Claude's reading, checked
                # against the staff roster and the owner's own record.
                from apps.meetings import ownership

                body.update(ownership.classify(
                    tenant, owner_text=owner,
                    owner_contact_id=body["proposed_owner_contact_id"],
                    claude_side=str(raw.get("owner_side") or "").strip().lower(),
                    claude_kind=str(raw.get("owner_kind") or "").strip().lower()))
            ProposalItem.objects.create(
                tenant=tenant, proposal=proposal, kind=kind, position=position,
                source_excerpt=str(raw.get("excerpt") or "").strip(), payload=body)

    source_file.state = MeetingSourceFile.State.PARSED
    source_file.error = ""
    source_file.auto_parse_failures = 0
    source_file.save(update_fields=["state", "error", "auto_parse_failures", "updated_at"])
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


def claim(source_file) -> bool:
    """Take a recorded file for parsing, or learn that someone else has.

    The poll and the backfill both parse, on different schedules, and a file
    the backfill has just recorded is `recorded` — so the poll would read it
    too. On 2026-09-28 that is what happened to one note: two Claude calls in
    the same minute and two proposals in the queue. One conditional UPDATE
    decides which of them reads it.
    """
    taken = MeetingSourceFile.objects.filter(
        pk=source_file.pk,
        state__in=[MeetingSourceFile.State.RECORDED, MeetingSourceFile.State.FAILED],
    ).update(state=MeetingSourceFile.State.PARSING, updated_at=timezone.now())
    if taken:
        source_file.state = MeetingSourceFile.State.PARSING
    return bool(taken)


def already_read(source_file, text: str) -> MeetingSourceFile | None:
    """An earlier version of this same file, with this same text, already read.

    Drive raises a file's version for changes that are not to its words —
    sharing, moving, a rename — so a new version is not a new note. On
    2026-09-28 eleven September notes came back one version up with their text
    unchanged, and each was read again: $1.54 and eleven duplicate proposals.
    """
    return (MeetingSourceFile.objects
            .filter(drive_file_id=source_file.drive_file_id, text=text,
                    state=MeetingSourceFile.State.PARSED)
            .exclude(pk=source_file.pk).order_by("created_at").first())


def parse(source_file, *, client=None, trigger="auto",
          skip_unchanged=True) -> MeetingProposal | None:
    """Read one file. Returns the proposal, or None and a recorded failure.

    **A failure leaves the file recorded and retryable** and does not touch the
    cursor (FR-5.5, AC-5.10).

    A version whose text an earlier version already had is **not** read again:
    it is marked skipped with the reason, and None comes back with the file in
    state `skipped`, which callers count as skipped rather than failed. Only a
    person asking for a re-read (`reparse`) passes `skip_unchanged=False`.
    """
    from apps.tenancy import claude

    # A file whose proposal was dismissed stays dismissed at every later
    # version — not fetched, not read (owner, 2026-09-28). Restore clears it.
    dismissed = (MeetingSourceFile.objects
                 .filter(drive_file_id=source_file.drive_file_id,
                         dismissed_at__isnull=False)
                 .exclude(pk=source_file.pk).first()) if skip_unchanged else None
    if dismissed is not None:
        source_file.state = MeetingSourceFile.State.SKIPPED
        source_file.skip_reason = (
            f"Dismissed on {timezone.localdate(dismissed.dismissed_at):%Y-%m-%d}; "
            "later versions of it are not read.")
        source_file.save(update_fields=["state", "skip_reason", "updated_at"])
        return None

    text = text_of(source_file, client=client)
    if not text.strip():
        source_file.state = MeetingSourceFile.State.FAILED
        source_file.error = "The document could not be read, or is empty."
        source_file.save(update_fields=["state", "error", "updated_at"])
        return None

    earlier = already_read(source_file, text) if skip_unchanged else None
    if earlier is not None:
        source_file.state = MeetingSourceFile.State.SKIPPED
        source_file.skip_reason = (
            f"Unchanged since version {earlier.drive_version}, read on "
            f"{timezone.localdate(earlier.created_at):%Y-%m-%d}. Not read again.")
        source_file.save(update_fields=["state", "skip_reason", "updated_at"])
        return None

    source_file.state = MeetingSourceFile.State.PARSING
    source_file.save(update_fields=["state", "updated_at"])
    try:
        reply, call = claude.complete_with_call(
            tenant=source_file.tenant, purpose=PARSE_PURPOSE, system=SYSTEM,
            user_text=f"{source_file.name}\n\n{text}",
            target_type="meeting_source_file", target_id=source_file.pk,
            trigger=trigger, max_tokens=PARSE_MAX_TOKENS,
            # Extraction, not judgment: low effort, as the owner
            # classification was (2026-09-28). Reasoning is billed as output,
            # and at the default it was what ran past the old 6000 limit.
            effort="low",
        )
    except (claude.ClaudeUnavailable, claude.ClaudeRefused) as exc:
        call = getattr(exc, "call", None)
        return _failed(source_file, str(exc), trigger=trigger,
                       billed=bool(call and call.output_tokens))

    payload = _payload(reply)
    if not isinstance(payload, dict):
        return _failed(source_file, "Claude answered with something this could not read.",
                       trigger=trigger, billed=True)
    return _build(source_file, payload, call)


def _failed(source_file, message: str, *, trigger: str, billed: bool) -> None:
    """Record a failed read, **named**, and say what happens next.

    A failed file is picked up again by the next poll, so a re-read is queued
    by the failure itself. That retry is what cost $17 by 2026-09-29: one note
    failed at the limit 54 times, every ten minutes. So a failure that was
    billed counts against the file, and after `MAX_AUTO_PARSE_FAILURES` the
    poll stops and the queue names the file for a person to read again. A
    failure that cost nothing (no key, no network) never counts: fixing the
    key must still let every file retry by itself.
    """
    if billed and trigger != "button":
        source_file.auto_parse_failures += 1
    tries = source_file.auto_parse_failures
    if tries >= MAX_AUTO_PARSE_FAILURES:
        message += (f" Failed {tries} times automatically; not tried again until "
                    "someone chooses Read again on the meeting queue.")
    elif billed and trigger != "button":
        message += (f" Queued to be read again on the next poll "
                    f"({tries} of {MAX_AUTO_PARSE_FAILURES} automatic tries).")
    source_file.state = MeetingSourceFile.State.FAILED
    source_file.error = message
    source_file.save(update_fields=["state", "error", "auto_parse_failures", "updated_at"])
    return None


def retries_automatically(source_file) -> bool:
    return source_file.auto_parse_failures < MAX_AUTO_PARSE_FAILURES


def read_again(source_file, *, actor=None) -> MeetingSourceFile:
    """A person asks for a failed file to be read again: queued for the next
    poll, with its automatic tries restored. Nothing is read here — the read
    costs money and takes a minute, so it happens on the worker, not in the
    request."""
    from apps.tenancy.models import AuditEvent

    if source_file.state != MeetingSourceFile.State.FAILED:
        raise ValueError("Only a file whose read failed can be read again.")
    before = source_file.auto_parse_failures
    source_file.state = MeetingSourceFile.State.RECORDED
    source_file.auto_parse_failures = 0
    source_file.error = ""
    source_file.save(update_fields=["state", "auto_parse_failures", "error", "updated_at"])
    from apps.tenancy import ai_guard

    ai_guard.allow_again(source_file.tenant, purpose=PARSE_PURPOSE,
                         target_type="meeting_source_file", target_id=source_file.pk,
                         actor=actor)
    AuditEvent.all_objects.create(
        tenant_id=source_file.tenant_id, actor=actor, verb="meeting.file_read_again",
        target_type="meeting_source_file", target_id=source_file.pk,
        payload={"file": source_file.name, "automatic_failures_before": before})
    return source_file


def reparse(proposal, *, actor=None) -> MeetingProposal | None:
    """A fresh proposal that supersedes this one (FR-5.17).

    **Approved items are untouched** — what a person has already decided is not
    up for a second opinion — and the old proposal is kept as `superseded`
    rather than deleted, so the trail of what was proposed survives.
    """
    source_file = proposal.source_file
    source_file.state = MeetingSourceFile.State.RECORDED
    source_file.save(update_fields=["state", "updated_at"])
    fresh = parse(source_file, trigger="button", skip_unchanged=False)
    if fresh is None:
        return None
    proposal.state = MeetingProposal.State.SUPERSEDED
    proposal.save(update_fields=["state", "updated_at"])
    ProposalItem.objects.filter(proposal=proposal,
                                state=ProposalItem.State.PENDING).update(
        state=ProposalItem.State.REJECTED, actioned_at=timezone.now())
    return fresh
