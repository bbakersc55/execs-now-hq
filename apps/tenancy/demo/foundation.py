"""The practice itself: its name and look, its staff, its clients and their
people, the sales pipeline, referral partners and vendors."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from . import cast
from .clock import at, dice, moment, month_start


@dataclass
class World:
    """What has been made so far, by name, for the parts built after it."""

    tenant: object
    owner: object
    today: date
    staff: dict = field(default_factory=dict)        # key -> User
    staff_contacts: dict = field(default_factory=dict)   # key -> Contact (the payee)
    companies: dict = field(default_factory=dict)    # name -> Company
    people: dict = field(default_factory=dict)       # company name -> [Contact]
    portal: dict = field(default_factory=dict)       # company name -> [Membership]
    lead: dict = field(default_factory=dict)         # company name -> User who runs it
    start: dict = field(default_factory=dict)        # company name -> date
    fee: dict = field(default_factory=dict)          # company name -> cents a month
    prospects: dict = field(default_factory=dict)    # "First Last" -> Contact
    partners: list = field(default_factory=list)
    vendors: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)

    def role_of(self, user) -> str:
        if user.pk == self.owner.pk:
            return "FF"
        return "CF" if user in [self.staff[k] for k, *_ in cast.ASSOCIATES] else "VA"


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def address_for(first: str, last: str, company: str) -> str:
    return f"{slug(first)}.{slug(last)}@{slug(company)}.example"


# ------------------------------------------------------------ the practice

def practice(*, ff_email, ff_name, oauth_client, today) -> World:
    from django.conf import settings

    from apps.accounts.models import User
    from apps.crm.seed import seed_tenant as seed_crm
    from apps.platform import agreement
    from apps.platform.models import AgreementAcceptance
    from apps.tenancy import branding, modules
    from apps.tenancy.context import tenant_context
    from apps.tenancy.models import Membership, Role, Tenant

    opened = month_start(2025, 1) - timedelta(days=20)
    with at(opened):
        tenant = Tenant.objects.create(
            name=cast.PRACTICE, slug=cast.SLUG, legal_name=cast.LEGAL_NAME,
            domain=cast.DOMAIN, timezone="America/Denver", oauth_client=oauth_client,
            # The one address the demo sends from (config/environment.py).
            from_address=settings.DEMO_MAIL_FROM, hold_all_digests=True,
            # No Claude in the demo's own content: its prose is deterministic.
            digest_ai_prose_default=False, ai_unattended_daily_cap_usd=Decimal("0"),
            email_display_name=cast.PRACTICE)
        # Also the platform owner there, so the demo has a Practices area to
        # show. It holds the one practice.
        owner = User.objects.create(email=ff_email.strip().lower(),
                                    full_name=ff_name or cast.OWNER_NAME,
                                    is_platform_owner=True)
        with tenant_context(tenant.pk):
            seed_crm(tenant)
            Membership.objects.create(tenant=tenant, user=owner, role=Role.FF)
            terms = agreement.current()
            AgreementAcceptance.all_objects.create(
                tenant=tenant, user=owner, version=terms["version"],
                text_sha256=terms["sha256"])
            # It has the Bookkeeping module, as every practice that existed
            # when the module arrived does.
            modules.set_enabled(tenant, modules.BOOKKEEPING, True, actor=owner)
            branding.save(tenant, actor=owner, display_name=cast.PRACTICE,
                          primary_color=cast.PRIMARY, accent_color=cast.ACCENT,
                          footer_text=cast.FOOTER)
            branding.set_image(tenant, actor=owner, kind="logo", content=logo_png())
            branding.set_image(tenant, actor=owner, kind="mark", content=mark_png())
    tenant.refresh_from_db()
    return World(tenant=tenant, owner=owner, today=today)


def _mountain(draw, box, color, line):
    """Two peaks and the line they stand on."""
    left, top, right, bottom = box
    width, height = right - left, bottom - top
    draw.polygon([(left, bottom), (left + width * 0.38, top + height * 0.10),
                  (left + width * 0.62, bottom)], fill=color)
    draw.polygon([(left + width * 0.36, bottom), (left + width * 0.70, top + height * 0.34),
                  (right, bottom)], fill=color)
    draw.polygon([(left + width * 0.38, top + height * 0.10),
                  (left + width * 0.30, top + height * 0.32),
                  (left + width * 0.38, top + height * 0.27),
                  (left + width * 0.46, top + height * 0.33)], fill="#FFFFFF")
    draw.rectangle([left - width * 0.08, bottom + height * 0.10,
                    right + width * 0.08, bottom + height * 0.17], fill=line)


def mark_png() -> bytes:
    """The square mark: the mountain and its line on the practice's green."""
    from PIL import Image, ImageDraw

    size = 360
    image = Image.new("RGB", (size, size), cast.PRIMARY)
    _mountain(ImageDraw.Draw(image), (70, 80, 290, 240), "#FFFFFF", cast.ACCENT)
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def logo_png() -> bytes:
    """The wordmark: the mountain, the line, and the practice's name."""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1040, 240), "#FFFFFF")
    draw = ImageDraw.Draw(image)
    _mountain(draw, (36, 40, 236, 176), cast.PRIMARY, cast.ACCENT)
    draw.text((290, 44), "SUMMIT", fill=cast.PRIMARY, font=ImageFont.load_default(size=92))
    draw.text((294, 146), "OPERATIONS PARTNERS", fill=cast.ACCENT,
              font=ImageFont.load_default(size=44))
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


# -------------------------------------------------------------- the people

def people(world: World) -> None:
    _staff(world)
    _clients(world)
    _prospects(world)
    _partners(world)
    _vendors(world)


def contact(world, first, last, title, company, email, *, when=None, kind=None,
            owner=None, source="demo", background=""):
    from apps.crm.models import Contact, ContactEmail, ContactPhone
    from apps.crm.services import referral

    row = Contact.objects.create(tenant=world.tenant, first_name=first, last_name=last,
                                 title=title, company=company, source=source,
                                 owner=owner or world.owner, background=background)
    ContactEmail.objects.create(tenant=world.tenant, contact=row, address=email,
                                is_primary=True)
    roll = dice("phone", email)
    ContactPhone.objects.create(
        tenant=world.tenant, contact=row, is_primary=True,
        # 555-01xx: the range kept for fiction.
        number=f"(303) 555-01{roll.randrange(100):02d}")
    if kind:
        referral.add_type(row, kind, onboard=False)
    return row


def _staff(world: World) -> None:
    from apps.accounts.models import User
    from apps.crm.models import Contact
    from apps.tenancy.models import Membership, Role

    for group, role, terms in ((cast.ASSOCIATES, Role.CF, "Associate. Keeps {n}% of the "
                                "fees of the clients they lead; the practice keeps the rest."),
                               (cast.ASSISTANTS, Role.VA, "Assistant, on contract at "
                                "${n} an hour.")):
        for key, name, email, (year, month), number in group:
            joined = month_start(year, month)
            with at(joined):
                user = User.objects.create(email=email, full_name=name)
                user.last_login_at = moment(world.today - timedelta(days=1 + len(world.staff)),
                                            8, 40)
                user.save(update_fields=["last_login_at"])
                Membership.objects.create(tenant=world.tenant, user=user, role=role,
                                          invited_by=world.owner, invited_at=moment(joined))
                first, _, last = name.partition(" ")
                payee = contact(world, first, last, role.label, None, email,
                                kind="coworker", background=terms.format(n=number))
                Contact.objects.filter(pk=payee.pk).update(is_1099_payee=True)
            world.staff[key] = user
            world.staff_contacts[key] = payee
            world.extra.setdefault("joined", {})[key] = joined


def _clients(world: World) -> None:
    from apps.crm.models import Company, CompanyDomain, PipelineStage
    from apps.crm.services import pipeline
    from apps.tenancy.models import ClientAssignment
    from apps.work import portal

    sales = pipeline.sales_pipeline(world.tenant)
    stage = {s.code: s for s in PipelineStage.objects.filter(pipeline=sales)}
    for name, industry, city, (year, month), fee, lead, team in cast.CLIENTS:
        started = month_start(year, month)
        # They were prospects first: met, qualified, given a session and a
        # proposal in the weeks before the engagement began.
        with at(started - timedelta(days=45)):
            company = Company.objects.create(
                tenant=world.tenant, name=name, industry=industry, seat_count=4,
                digest_ai_prose=False,
                address={"lines": [f"{100 + len(world.companies) * 37} Main Street", city]})
            CompanyDomain.objects.create(tenant=world.tenant, company=company,
                                         domain=f"{slug(name)}.example")
            rows = [contact(world, first, last, title, company,
                            address_for(first, last, name), kind="prospect")
                    for first, last, title, _ in team]
            company.primary_contact = rows[0]
            company.save(update_fields=["primary_contact", "updated_at"])
        for code, days in (("qualified", 30), ("consult_given", 21), ("proposal_given", 14),
                           ("closed_won", 5)):
            with at(started - timedelta(days=days)):
                # Reaching the won stage is what makes them a client (FR-1.6a).
                pipeline.change_stage(rows[0], stage[code], actor=world.owner,
                                      reason="", run_automations=False)
        with at(started):
            from apps.crm.services import referral

            for row in rows[1:]:
                referral.add_type(row, "client", onboard=False)
            members = []
            for row, (_, _, _, access) in zip(rows, team):
                if not access:
                    continue
                member = portal.grant(tenant=world.tenant, contact=row, actor=world.owner,
                                      role="FCC" if access == "owner" else "ECC")
                if access != "team-never":
                    seen = world.today - timedelta(days=dice("seen", row.pk).randrange(1, 9))
                    member.user.last_login_at = moment(seen, 10, 5)
                    member.user.save(update_fields=["last_login_at"])
                members.append(member)
            leader = world.staff[lead] if lead else world.owner
            if lead:
                ClientAssignment.objects.create(tenant=world.tenant, user=leader,
                                                company=company, assigned_by=world.owner)
        company.refresh_from_db()
        world.companies[name], world.people[name] = company, rows
        world.portal[name], world.lead[name] = members, leader
        world.start[name], world.fee[name] = started, fee * 100


def _prospects(world: World) -> None:
    from apps.crm.models import Company, PipelineStage
    from apps.crm.services import pipeline

    sales = pipeline.sales_pipeline(world.tenant)
    stage = {s.code: s for s in PipelineStage.objects.filter(pipeline=sales)}
    owners = [world.owner, world.owner, world.staff["ripley"], world.owner,
              world.staff["lasso"]]
    for index, (first, last, title, company_name, code, ago, path) in enumerate(cast.PROSPECTS):
        reached = world.today - timedelta(days=ago)
        # Each earlier stage a few days before the next, all inside two months.
        gaps = dice("prospect", first, last)
        steps, day = [], reached
        for earlier in reversed(path):
            day -= timedelta(days=gaps.randrange(3, 9))
            steps.append((earlier, day))
        steps.reverse()
        first_seen = min([reached] + [d for _, d in steps]) - timedelta(days=1)
        first_seen = max(first_seen, world.today - timedelta(days=59))
        with at(first_seen):
            company = Company.objects.create(tenant=world.tenant, name=company_name)
            row = contact(world, first, last, title, company,
                          address_for(first, last, company_name), kind="prospect",
                          owner=owners[index % len(owners)])
        for earlier, day in steps + [(code, reached)]:
            day = max(day, first_seen)
            if earlier == "initial_contact_made" and \
                    pipeline.position_for(row, sales) is not None:
                continue
            with at(moment(day, 9 + index % 8, 15)):
                pipeline.change_stage(row, stage[earlier], actor=row.owner,
                                      reason=LOST.get(f"{first} {last}", "")
                                      if earlier == code else "",
                                      run_automations=False)
        world.prospects[f"{first} {last}"] = row


LOST = {
    "Cosmo Spacely": "Chose to keep it in the family for now; open to talking next year.",
    "Eldon Tyrell": "Budget went to a new production line instead.",
    "Krusty Clown": "Wanted a turnaround in thirty days. Not a fit.",
    "George Jetson": "Not the decision maker; the owner is not ready.",
    "Charles Kane": "Interested, but in the middle of a sale. Check back in the spring.",
    "Norma Desmond": "Liked the session. Wants to revisit after the busy season.",
}


def _partners(world: World) -> None:
    from apps.crm.models import Contact, Enrollment, PipelineStage
    from apps.crm.services import enrollment, pipeline

    referral_pipeline = pipeline.referral_pipeline(world.tenant)
    stages = list(PipelineStage.objects.filter(pipeline=referral_pipeline)
                  .order_by("position"))
    for index, (first, last, title, firm, cadence, enrolled) in enumerate(cast.PARTNERS):
        roll = dice("partner", first, last)
        met = world.today - timedelta(days=roll.randrange(40, 520))
        with at(met):
            row = contact(world, first, last, title, None, address_for(first, last, firm),
                          kind="referral_partner",
                          background=f"{title} at {firm}. Met at a Denver owners' event.")
            Contact.objects.filter(pk=row.pk).update(
                referral_cadence=cadence,
                referral_fee_terms="" if index % 4 else "10% of the first three months")
            row.refresh_from_db()
            pipeline.change_stage(row, stages[0], actor=world.owner, run_automations=False)
        settled = stages[min(len(stages) - 1, 1 + roll.randrange(len(stages) - 1))]
        if not enrolled:
            settled = stages[-1] if index % 2 else stages[1]
        with at(min(met + timedelta(days=roll.randrange(10, 35)), world.today)):
            pipeline.change_stage(row, settled, actor=world.owner, run_automations=False)
            if enrolled:
                enrollment.enroll(row, Enrollment.Program.REFERRAL_TOUCHES, actor=world.owner)
        if enrolled:
            # Their next touch falls somewhere in the weeks ahead, not all at once.
            row.refresh_from_db()
            row.referral_next_touch_at = moment(
                world.today + timedelta(days=4 + roll.randrange(60)), 8)
            row.save(update_fields=["referral_next_touch_at", "updated_at"])
        world.partners.append(row)


def _vendors(world: World) -> None:
    from apps.crm.models import Contact, ContactServiceCategory, ServiceCategory

    for first, last, title, firm, service, payee in cast.VENDORS:
        with at(world.today - timedelta(days=dice("vendor", firm, last).randrange(90, 600))):
            row = contact(world, first, last, title, None, address_for(first, last, firm),
                          kind="vendor", background=f"{firm}. {service}.")
            category, _ = ServiceCategory.objects.get_or_create(tenant=world.tenant,
                                                                name=service)
            ContactServiceCategory.objects.create(tenant=world.tenant, contact=row,
                                                  service_category=category)
            if payee:
                Contact.objects.filter(pk=row.pk).update(is_1099_payee=True)
        world.vendors[f"{first} {last}"] = row


# ------------------------------------------------------ the mail connection

def restore_mail_connection(world: World, kept) -> bool:
    """Put back the connection lifted out before the reset, when it still
    belongs: the same person signs in as the owner, and the practice uses the
    OAuth client that issued the token."""
    from apps.crm.models import GmailConnection
    from apps.tenancy.models import SecretKind, TenantSecret

    if not kept or kept["user_email"].lower() != world.owner.email.lower() \
            or kept["oauth_client"] != world.tenant.oauth_client \
            or (kept["send_as_address"] or "").lower() != world.tenant.from_address.lower():
        return False
    secret = TenantSecret.all_objects.create(
        tenant=world.tenant, kind=SecretKind.GMAIL_REFRESH, user=world.owner,
        ciphertext=kept["ciphertext"], last4=kept["last4"])
    GmailConnection.all_objects.create(
        tenant=world.tenant, user=world.owner, email_address=kept["email_address"],
        scopes=kept["scopes"], send_as_address=kept["send_as_address"],
        send_as_verified_at=kept["send_as_verified_at"], secret=secret)
    world.extra["mail_connection_kept"] = True
    return True


# ------------------------------------------------------------------ counts

def counts(world: World) -> dict:
    """What was seeded, counted from the database rather than remembered."""
    from apps.billing.models import ClientInvoice, ClientInvoiceSchedule, ClientPayment
    from apps.crm.models import (
        Campaign, Company, Contact, EmailSuppression, Enrollment, OutboxMessage, StageChange,
        Task, UnmatchedInbound,
    )
    from apps.finance.models import (
        FinanceAccount, FinanceEntry, FinanceImportBatch, FinanceRule,
    )
    from apps.meetings.models import Commitment, Meeting, MeetingProposal
    from apps.notes.models import Note
    from apps.strategy.models import StrategySession, StrategyTemplate
    from apps.tenancy.models import ClientAssignment, Membership, StoredFile
    from apps.work.models import (
        Comment, Digest, Goal, GoalMeasurement, GoalMilestone, GoalOrderProposal,
        GoalProposal, GoalResolution, Project, Stakeholder,
    )

    def typed(code):
        return Contact.objects.filter(types__code=code).distinct().count()

    members = Membership.objects.all()
    invoices = ClientInvoice.objects.all()
    entries = FinanceEntry.objects.filter(removed_at__isnull=True)
    today = world.today
    return {
        "staff": {r: members.filter(role=r).count() for r in ("FF", "CF", "VA")},
        "client companies": Company.objects.filter(is_client_company=True).count(),
        "client assignments": ClientAssignment.objects.count(),
        "portal users": members.filter(role__in=("FCC", "ECC")).count(),
        "portal users never signed in": members.filter(
            role__in=("FCC", "ECC"), user__last_login_at__isnull=True).count(),
        "contacts": Contact.objects.count(),
        "prospects in the pipeline": len(world.prospects),
        "stage moves, last 60 days": StageChange.objects.filter(
            created_at__gte=moment(today - timedelta(days=60))).count(),
        "referral partners": typed("referral_partner"),
        "partners on touches": Enrollment.objects.filter(ended_at__isnull=True).count(),
        "vendors": typed("vendor"),
        "1099 payees": Contact.objects.filter(is_1099_payee=True).count(),
        "goals": Goal.objects.count(),
        "goal readings": GoalMeasurement.objects.count(),
        "milestones": GoalMilestone.objects.count(),
        "goal resolutions": GoalResolution.objects.count(),
        "goal proposals pending": GoalProposal.objects.filter(state="pending").count(),
        "order proposals pending": GoalOrderProposal.objects.filter(state="pending").count(),
        "projects": Project.objects.count(),
        "tasks": {s: Task.objects.filter(status=s).count() for s in Task.Status.values},
        "tasks overdue": Task.objects.filter(due_date__lt=today).exclude(
            status__in=("done", "cancelled")).count(),
        "tasks due in the next 7 days": Task.objects.filter(
            due_date__gte=today, due_date__lte=today + timedelta(days=7)).exclude(
            status__in=("done", "cancelled")).count(),
        "comments": Comment.objects.count(),
        "stakeholders": Stakeholder.objects.count(),
        "digests": {s: Digest.objects.filter(state=s).count()
                    for s in ("pending", "sent")},
        "commitments open": Commitment.objects.filter(state="open").count(),
        "commitments overdue": Commitment.objects.filter(
            state="open", due_date__lt=today).count(),
        "strategy templates": StrategyTemplate.objects.count(),
        "strategy sessions": {s: StrategySession.objects.filter(state=s).count()
                              for s in ("draft", "in_call", "complete", "converted")},
        "meeting proposals": {s: MeetingProposal.objects.filter(state=s).count()
                              for s in ("pending", "partially_actioned", "actioned",
                                        "dismissed")},
        "meetings on record": Meeting.objects.count(),
        "notes": Note.objects.count(),
        "campaigns": Campaign.objects.count(),
        "sending queue, waiting": OutboxMessage.objects.filter(
            state="pending_approval").count(),
        "emails on record as sent": OutboxMessage.objects.filter(state="sent").count(),
        "unmatched replies": UnmatchedInbound.objects.filter(state="pending").count(),
        "unsubscribes": EmailSuppression.objects.count(),
        "invoices": {s: invoices.filter(status=s).count()
                     for s in ClientInvoice.Status.values},
        "invoices overdue": invoices.filter(status__in=("sent", "partially_paid"),
                                            due_date__lt=today).count(),
        "invoice schedules": ClientInvoiceSchedule.objects.filter(is_active=True).count(),
        "payments": ClientPayment.objects.filter(removed_at__isnull=True).count(),
        "accounts": FinanceAccount.objects.count(),
        "book entries": {k: entries.filter(kind=k).count()
                         for k in FinanceEntry.Kind.values},
        "bank imports committed": FinanceImportBatch.objects.filter(
            status="committed").count(),
        "import rules": FinanceRule.objects.count(),
        "stored files": StoredFile.objects.count(),
        "mail connection kept": bool(world.extra.get("mail_connection_kept")),
    }
