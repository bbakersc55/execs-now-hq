"""Apply FR-5.9e to proposals parsed before the rule existed.

The owner's queue held **eight proposals stuck at `partially_actioned`**, each
on a pending participant item that was his own name — a question with no true
answer, which is why nobody ever answered it.

Dry-run by default, like every other repair in this project. It changes only
participant items that **recognise as the practice right now**, and it creates
nothing: the contact it points at already exists, no type is added, no pipeline
stage moves, nothing is sent.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.meetings import approval, practice
from apps.meetings.models import MeetingProposal, ProposalItem
from apps.tenancy.context import tenant_context
from apps.tenancy.models import AuditEvent, Tenant


class Command(BaseCommand):
    help = "Recognise staff participants on existing meeting proposals (FR-5.9e)."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", help="Tenant slug. Default: every tenant.")
        parser.add_argument("--apply", action="store_true",
                            help="Write the changes. Without it, nothing is saved.")

    def handle(self, *args, **options):
        tenants = Tenant.objects.all()
        if options.get("tenant"):
            tenants = tenants.filter(slug=options["tenant"])
        for tenant in tenants:
            with tenant_context(tenant.id):
                self.one(tenant, apply=options["apply"])

    def one(self, tenant, *, apply: bool):
        roster = practice.staff(tenant)
        self.stdout.write(f"\n{tenant.slug}: {len(roster)} on staff")
        for member in roster:
            found = member.contact
            self.stdout.write(
                f"  {member.role} {member.name} -> "
                + (f"contact {found.first_name} {found.last_name}" if found
                   else "no contact row (recognised, but attendance cannot be "
                        "recorded against a contact)"))

        pending = ProposalItem.objects.filter(
            kind=ProposalItem.Kind.PARTICIPANT, state=ProposalItem.State.PENDING)
        changed, proposals = [], set()
        for item in pending:
            payload = item.payload or {}
            ours = practice.recognise(tenant, name=payload.get("parsed_name") or "",
                                      email=payload.get("parsed_email") or "",
                                      roster=roster)
            if ours is None:
                continue
            changed.append((item, ours))
            proposals.add(item.proposal_id)

        self.stdout.write(f"  {len(changed)} participant item(s) are the practice, "
                          f"across {len(proposals)} proposal(s)")
        for item, ours in changed:
            payload = item.payload or {}
            self.stdout.write(
                f"    “{payload.get('parsed_name') or payload.get('parsed_email')}”"
                f" in “{item.proposal.title}” -> {ours.name} (by {ours.matched_on})")

        if not apply:
            was = dict(MeetingProposal.objects.filter(pk__in=proposals)
                       .values_list("pk", "state"))
            after = {}
            for proposal in MeetingProposal.objects.filter(pk__in=proposals):
                # What settle would say, without saving it.
                after[proposal.pk] = self.would_be(proposal, roster)
            for pk, before in was.items():
                if before != after.get(pk):
                    self.stdout.write(f"    proposal {before} -> {after[pk]}")
            self.stdout.write(self.style.WARNING(
                "  Dry run. Nothing written. Re-run with --apply."))
            return

        with transaction.atomic():
            for item, ours in changed:
                item.payload = {**(item.payload or {}), **practice.payload_for(ours)}
                item.state = ProposalItem.State.APPROVED
                item.created_record_type = "contact" if ours.contact else ""
                item.created_record_id = ours.contact.pk if ours.contact else None
                item.save(update_fields=["payload", "state", "created_record_type",
                                         "created_record_id", "updated_at"])
            for proposal in MeetingProposal.objects.filter(pk__in=proposals):
                before = proposal.state
                approval.settle(proposal)
                proposal.refresh_from_db()
                AuditEvent.all_objects.create(
                    tenant=tenant, actor=None, verb="meeting.practice_recognised",
                    target_type="meeting_proposal", target_id=proposal.pk,
                    payload={"state_before": before, "state_after": proposal.state})
        self.stdout.write(self.style.SUCCESS(
            f"  Applied to {len(changed)} item(s) in {len(proposals)} proposal(s)."))

    @staticmethod
    def would_be(proposal, roster) -> str:
        """`settle`'s answer, computed without touching anything."""
        theirs = [item for item in ProposalItem.objects.filter(proposal=proposal)
                  if not (item.kind == ProposalItem.Kind.PARTICIPANT
                          and practice.is_practice_item(item, tenant=proposal.tenant,
                                                        roster=roster))]
        states = {item.state for item in theirs}
        if not theirs:
            return MeetingProposal.State.ACTIONED
        if not states or states == {ProposalItem.State.PENDING}:
            return MeetingProposal.State.PENDING
        if ProposalItem.State.PENDING in states:
            return MeetingProposal.State.PARTIALLY_ACTIONED
        if states == {ProposalItem.State.REJECTED}:
            return MeetingProposal.State.REJECTED
        return MeetingProposal.State.ACTIONED
