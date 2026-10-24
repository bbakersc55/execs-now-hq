"""The practice itself: its name and look, its staff, its clients and their
people, the sales pipeline, referral partners and vendors."""

from __future__ import annotations

import io
import re
from contextvars import ContextVar
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


#: A visitor's copy (2026-10-17) adds its tag to every fictional address it
#: makes, `ellen.ripley+k3x9q2@summitops.example`: a sign-in address is the
#: whole database's, so the copy's people must not meet Summit's. Empty for
#: Summit, whose addresses are as they always were.
TAG: ContextVar[str] = ContextVar("demo_address_tag", default="")


def tagged(address: str) -> str:
    tag = TAG.get()
    if not tag:
        return address
    local, _, domain = address.partition("@")
    return f"{local}+{tag}@{domain}"


def address_for(first: str, last: str, company: str) -> str:
    return tagged(f"{slug(first)}.{slug(last)}@{slug(company)}.example")


# ------------------------------------------------------------ the practice

def practice(*, ff_email, ff_name, oauth_client, today, visitor=None) -> World:
    """Summit, made new; or, given a visitor's copy (`DemoVisitor`), the same
    practice made inside the copy's own practice row, with the visitor as its
    owner. A copy's owner is not the platform owner, and is not shown the
    beta agreement as accepted: they never accepted it."""
    from django.conf import settings

    from apps.accounts.models import User
    from apps.crm.seed import seed_tenant as seed_crm
    from apps.platform import agreement
    from apps.platform.models import AgreementAcceptance
    from apps.tenancy import branding, modules
    from apps.tenancy.context import tenant_context
    from apps.tenancy.models import Membership, Role, Tenant

    opened = month_start(2025, 1) - timedelta(days=20)
    fields = dict(
        name=cast.PRACTICE, legal_name=cast.LEGAL_NAME,
        domain=cast.DOMAIN, timezone="America/Denver", oauth_client=oauth_client,
        # The one address the demo sends from (config/environment.py).
        from_address=settings.DEMO_MAIL_FROM, hold_all_digests=True,
        # No Claude in the demo's own content: its prose is deterministic.
        digest_ai_prose_default=False, ai_unattended_daily_cap_usd=Decimal("0"),
        email_display_name=cast.PRACTICE)
    with at(opened):
        if visitor is None:
            tenant = Tenant.objects.create(slug=cast.SLUG, **fields)
            # Also the platform owner there, so the demo has a Practices area
            # to show. A reseed that leaves visitors' copies keeps this sign-in
            # (`reset_summit`), and the new Summit takes it over.
            owner, _ = User.objects.update_or_create(
                email=ff_email.strip().lower(),
                defaults={"full_name": ff_name or cast.OWNER_NAME, "is_platform_owner": True})
        else:
            tenant = visitor.tenant
            Tenant.objects.filter(pk=tenant.pk).update(
                status=Tenant.Status.ACTIVE, created_at=moment(opened), **fields)
            tenant.refresh_from_db()
            # The visitor plays John Carter, as the platform owner does in
            # Summit: the practice's story is his.
            owner = User.objects.get(email__iexact=visitor.email)
            User.objects.filter(pk=owner.pk).update(full_name=ff_name or cast.OWNER_NAME)
            owner.refresh_from_db()
        with tenant_context(tenant.pk):
            seed_crm(tenant)
            Membership.objects.create(tenant=tenant, user=owner, role=Role.FF)
            if visitor is None:
                terms = agreement.current()
                AgreementAcceptance.all_objects.create(
                    tenant=tenant, user=owner, version=terms["version"],
                    text_sha256=terms["sha256"])
            # It has the Bookkeeping module, as every practice that existed
            # when the module arrived does.
            modules.set_enabled(tenant, modules.BOOKKEEPING, True, actor=owner)
            # And the Cash forecast (P6 M2), which rests on it.
            modules.set_enabled(tenant, modules.FORECAST, True, actor=owner)
            # And Personal finance (P6 M4 decision 27: on for the demo).
            modules.set_enabled(tenant, modules.PERSONAL, True, actor=owner)
            branding.save(tenant, actor=owner, display_name=cast.PRACTICE,
                          primary_color=cast.PRIMARY, accent_color=cast.ACCENT,
                          footer_text=cast.FOOTER,
                          document={"document_closing": cast.CLOSING,
                                    "document_email": cast.OWNER_EMAIL,
                                    "document_website": cast.DOMAIN})
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
    _referrals(world)
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
            email = tagged(email)
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


#: Who referred whom (prospect, partner). Elle's introduction of Lucille is
#: the one Bryan thanks her for in his touch; Ben's of Selina is two days old,
#: so its thank-you is still waiting in the Outbox.
REFERRALS = [
    ("Wiley Coyote", "Ben Wyatt"),
    ("Eldon Tyrell", "Ben Wyatt"),
    ("Selina Kyle", "Ben Wyatt"),
    ("Lucille Bluth", "Elle Woods"),
    ("Harvey Specter", "Jessica Pearson"),
]


def _referrals(world: World) -> None:
    """Recorded as history, as an import would: the outcome of a won or lost
    prospect is taken from where they stand, and nothing is drafted, except
    the one thank-you a fresh referral would still be waiting on."""
    from django.utils import timezone

    from apps.crm.services import referrals

    partners = {f"{p.first_name} {p.last_name}": p for p in world.partners}
    prospects = dict(world.prospects)
    for name, rows in world.people.items():
        prospects[f"{rows[0].first_name} {rows[0].last_name}"] = rows[0]
    for prospect_name, partner_name in REFERRALS:
        prospect, partner = prospects[prospect_name], partners[partner_name]
        met = timezone.localtime(prospect.created_at)
        if prospect_name == "Selina Kyle":
            met = moment(world.today - timedelta(days=2), 16, 15)
        with at(met):
            referral = referrals.record(prospect, partner, actor=world.owner,
                                        referred_on=met.date(), from_import=True)
        if prospect_name == "Selina Kyle":
            with at(moment(world.today - timedelta(days=2), 16, 20)):
                referrals.draft_thanks(referral, referrals.RECORDED, actor=world.owner)


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


def restore_ai_key(world: World, kept) -> bool:
    """Put back the Anthropic key lifted out before the reset, when the same
    person signs in as the practice owner. Its sealed bytes are copied as
    they were; nothing here reads the key.

    The practice keeps the limits it is seeded with: **$0 a day of automatic
    spend** (and the demo runs no worker to make any), so the key is spent
    only when a person presses something."""
    from apps.tenancy.models import SecretKind, TenantSecret

    if not kept or world.owner.email.lower() not in kept["owner_emails"]:
        return False
    TenantSecret.all_objects.create(
        tenant=world.tenant, kind=SecretKind.ANTHROPIC_API_KEY, user=None,
        ciphertext=kept["ciphertext"], last4=kept["last4"],
        verified_at=kept["verified_at"], verified_by=world.owner,
        rotated_at=kept["rotated_at"])
    world.extra["ai_key_kept"] = True
    return True


# ------------------------------------------------------------------ counts

def _forecast_counts(world) -> dict:
    from apps.finance import forecast
    from apps.finance.models import (
        FinanceForecastAdjustment, FinanceForecastPlanned, FinanceForecastSnapshot,
    )

    result = forecast.build(world.tenant, world.today, snapshot=False)
    return {
        "cash today (USD)": result["cash_today_cents"] / 100,
        "floor (USD)": (result["floor_cents"] or 0) / 100,
        "lowest in 90 days (USD)": result["views"]["90"]["low_cents"] / 100,
        "first week under the floor": result["views"]["90"]["first_below_floor"],
        "lines": {kind: len({row["group"] for row in result["lines"]
                             if row["kind"] == kind})
                  for kind in ("known", "regular", "card", "planned")},
        "planned": FinanceForecastPlanned.objects.filter(is_what_if=False).count(),
        "what-ifs": FinanceForecastPlanned.objects.filter(is_what_if=True).count(),
        "changes by the owner": FinanceForecastAdjustment.objects.count(),
        "not counted": len(result["left_out"]),
        "likely annual": len(result["likely_annual"]),
        "months with a forecast kept": FinanceForecastSnapshot.objects.count(),
        "months in how good it has been": len(result["history"]),
    }


def _scorecard_count(model: str) -> int:
    from apps.scorecard import models

    return getattr(models, model).objects.count()


def counts(world: World) -> dict:
    """What was seeded, counted from the database rather than remembered."""
    from apps.billing.models import ClientInvoice, ClientInvoiceSchedule, ClientPayment
    from apps.crm.models import (
        Campaign, Company, Contact, EmailSuppression, Enrollment, OutboxMessage, StageChange,
        Task, UnmatchedInbound,
    )
    from apps.finance.models import (
        FinanceAccount, FinanceCategory, FinanceCategoryChange, FinanceEntry,
        FinanceImportBatch, FinanceMonthClose, FinanceReconciliation, FinanceRule,
        FinanceSettings,
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
        # M5 part 1: one client's scorecard.
        "scorecard KPIs": _scorecard_count("Kpi"),
        "scorecard readings": _scorecard_count("KpiReading"),
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
        "categories": {
            "top level": FinanceCategory.objects.filter(
                parent__isnull=True, archived_at__isnull=True).count(),
            "sub-categories": FinanceCategory.objects.filter(
                parent__isnull=False, archived_at__isnull=True).count(),
            "archived": FinanceCategory.objects.filter(archived_at__isnull=False).count()},
        "categories combined or split": FinanceCategoryChange.objects.count(),
        "reconciliations": {s: FinanceReconciliation.objects.filter(state=s).count()
                            for s in ("finished", "open")},
        "months closed": FinanceMonthClose.objects.filter(reopened_at__isnull=True).count(),
        "months reopened": FinanceMonthClose.objects.filter(
            reopened_at__isnull=False).count(),
        "books locked through": FinanceSettings.objects.values_list(
            "locked_through", flat=True).first(),
        "forecast": _forecast_counts(world),
        "book entries": {k: entries.filter(kind=k).count()
                         for k in FinanceEntry.Kind.values},
        "bank imports committed": FinanceImportBatch.objects.filter(
            status="committed").count(),
        "PDF statements imported": FinanceImportBatch.objects.filter(
            status="committed", statement_file__isnull=False).count(),
        "import rules": FinanceRule.objects.count(),
        "personal side": _personal_counts(world),
        "stored files": StoredFile.objects.count(),
        "mail connection kept": bool(world.extra.get("mail_connection_kept")),
        "AI key kept": bool(world.extra.get("ai_key_kept")),
        "AI, automatic spend allowed a day (USD)": world.tenant.ai_unattended_daily_cap_usd,
    }


def _personal_counts(world) -> dict:
    """John Carter's own ledger (P6 M4): counted from it, not remembered."""
    from apps.finance.models import FinanceAccount, FinanceEntry
    from apps.personal import models as personal

    def of(model):
        return model.of(world.owner)

    lines = of(personal.PersonalLine).filter(removed_at__isnull=True)
    return {
        "household": list(of(personal.PersonalMember).values_list("name", flat=True)),
        "personal accounts": of(personal.PersonalAccount).count(),
        "mixed accounts": FinanceAccount.objects.filter(side="mixed").count(),
        "lines": lines.count(),
        "lines to sort": lines.filter(category__isnull=True).count()
        + FinanceEntry.objects.filter(side="to_sort", removed_at__isnull=True).count(),
        "owner draws for personal lines": FinanceEntry.objects.filter(
            side="personal", removed_at__isnull=True).count(),
        "paid personally": FinanceEntry.objects.filter(
            side="paid_personally", removed_at__isnull=True).count(),
        "transfers paired": lines.filter(transfer_pair__isnull=False).count() // 2,
        "personal imports committed": of(personal.PersonalImport).filter(
            status="committed").count(),
        "personal reconciliations finished": of(personal.PersonalReconciliation).filter(
            state="finished").count(),
        "debts": of(personal.PersonalDebt).count(),
        "retirement and investments": of(personal.PersonalHolding).count(),
        "balances": of(personal.PersonalBalance).count(),
        "goals": of(personal.PersonalGoal).count(),
        "set-aside": of(personal.PersonalSetAside).values_list("saved_cents", flat=True)
        .first(),
        "budget": _budget_counts(world),
        "forecast, debts and net worth": _stop3_counts(world),
    }


def _stop3_counts(world) -> dict:
    """Stop 3: the personal forecast, the payoff plan and net worth, counted
    from them."""
    from apps.personal import debts, networth, services
    from apps.personal import forecast as personal_forecast
    from apps.personal.models import PersonalForecastSnapshot

    ledger = services.ledger_for(world.owner)
    found = personal_forecast.build(ledger, world.today, snapshot=False)
    plan = debts.represent(ledger, world.today)
    worth = networth.summary(ledger, world.today)
    return {
        "forecast ready": found["ready"],
        "forecast lines (12 months)": len(found["lines"]),
        "known lines": sum(1 for row in found["lines"] if row["kind"] == "known"),
        "planned lines": sorted({row["label"] for row in found["lines"]
                                 if row["kind"] == "planned"}),
        "months in how good it has been": len(found["history"]),
        "snapshots kept": PersonalForecastSnapshot.objects.filter(ledger=ledger).count(),
        "payoff order": plan["order"], "payoff extra (USD)": plan["extra_cents"] / 100,
        "debt free on": plan["debt_free_on"],
        "net worth (USD)": worth["total_cents"] / 100,
        "net worth months": len(worth["series"]),
        "home equity (USD)": next((row["equity_cents"] / 100 for row in worth["equity"]
                                   if row["kind"] == "home"), None),
    }


def _budget_counts(world) -> dict:
    """Stop 2: John's budget, counted from it."""
    from apps.personal import budget, services
    from apps.personal.models import PersonalQuestion

    ledger = services.ledger_for(world.owner)
    view = budget.month_view(ledger, world.today.replace(day=1))
    return {
        "envelopes": len(view["envelopes"]), "income envelopes": len(view["income"]),
        "goals with an envelope": sum(1 for row in view["envelopes"] if row["goal"]),
        "yearly bills spread": sum(1 for row in view["envelopes"] if row["yearly_cents"]),
        "over this month": sorted(row["name"] for row in view["envelopes"] if row["over"]),
        "unassigned (USD)": view["unassigned_cents"] / 100,
        "questions waiting": PersonalQuestion.objects.filter(ledger=ledger,
                                                             state="open").count(),
    }


def stage_rules(world: World) -> None:
    """Stage rules, part 2: a few of the starter rules on each pipeline, made
    after every move the seed makes so none of them fires during it, and one
    notice waiting for the owner on Home."""
    from apps.crm.models import ContactPipelinePosition, PipelineNotice, StageAutomation
    from apps.crm.services import pipeline, stage_rules as rules

    keep = {"first_call", "prospecting_quiet", "decision_quiet", "won_kickoff",
            "partner_touches", "nurturing_quiet"}
    for pipe in (pipeline.sales_pipeline(world.tenant), pipeline.referral_pipeline(world.tenant)):
        for example in rules.examples_for(pipe):
            if example["key"] in keep:
                StageAutomation.objects.create(tenant=world.tenant, pipeline=pipe,
                                               **example["fields"])
    # Part 3: the two follow-up starters, and one prospect part-way through
    # the proposal one (its first email waiting in the Outbox).
    from apps.crm.models import FollowUpRun
    from apps.crm.services import follow_ups

    sales = pipeline.sales_pipeline(world.tenant)
    for pipe, key in ((sales, "proposal_follow_up_sequence"),
                      (pipeline.referral_pipeline(world.tenant), "new_partner_follow_up_sequence")):
        try:
            follow_ups.add_starter(pipe, key, actor=world.owner)
        except follow_ups.FollowUpRefused:
            pass
    proposal = ContactPipelinePosition.objects.filter(
        pipeline=sales, stage__code="proposal_given").select_related("contact", "stage").first()
    if proposal is not None and proposal.contact.primary_email:
        try:
            run, _ = follow_ups.start(proposal.contact, proposal.stage, actor=world.owner,
                                      via="asked")
            FollowUpRun.objects.filter(pk=run.pk).update(next_on=world.today)
            follow_ups.advance(world.tenant, world.today)
        except follow_ups.FollowUpRefused:
            pass

    # P4 §4: what a read-back finds, shown on Invoices for the owner: a charge
    # made in NMI's portal that no invoice made. The demo has no NMI account,
    # so this one is written, not read.
    from apps.billing.models import NmiEvent

    NmiEvent.objects.create(
        tenant=world.tenant, event_id="demo-portal-sale", kind="sale", action_type="sale",
        transaction_id="10248311", amount_cents=45000, outcome="unmatched",
        happened_at=moment(world.today - timedelta(days=2), 15, 20),
        note=(f"A charge of $450.00 made in NMI on {world.today - timedelta(days=2):%b} "
              f"{(world.today - timedelta(days=2)).day} that no invoice here made "
              "(NMI transaction 10248311)."))

    waiting = ContactPipelinePosition.objects.filter(
        pipeline__kind="sales", stage__semantic="qualified").select_related(
        "contact", "stage", "pipeline").order_by("contact__last_name").first()
    if waiting is not None:
        c = waiting.contact
        PipelineNotice.objects.create(
            tenant=world.tenant, recipient=world.owner, contact=c, pipeline=waiting.pipeline,
            text=f"{c.first_name} {c.last_name} has been in {waiting.stage.label} 12 days "
                 "with no activity")
